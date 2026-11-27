#!/usr/bin/env python3
"""Fathom L1: downloaded meetings -> the generic intake contract.

Reads <data root>/fathom/raw/meetings/*.json (written by fa-l0-download.py) and writes:
  fathom/processed/plugin-contacts.parquet      one row per person met in your meetings
  fathom/processed/plugin-interactions.parquet  one row per meeting (kind=meeting, status
                                                done, text = summary + transcript) and one
                                                row per action item (kind=record, status
                                                open or done as ticked in Fathom)

People come from the calendar invitees of each meeting; for a meeting without invitees
(an impromptu call) the transcript speakers are used instead. A name that belongs to exactly
one email elsewhere is folded into that email. You are left out of contacts and of
`participants` (the kernel reads `participants` as "the other people"): your emails are
fathom.recorded_by and own_emails of sbk.config.json; when neither is set and every meeting
was recorded by the same address, that address is taken as yours.

Roles (owner_role): a meeting you recorded is `organizer` (you brought Fathom to it), one
where you are an invitee is `attendee`, otherwise `other`. An action item assigned to you is
`assignee` and, while open, becomes a commitment in the knowledge layer; its participants are
the other people of the meeting. An action item assigned to someone else is `other` with that
person as participant, so it is never your commitment.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fa_api  # noqa: E402

TITLE_MAX = 200


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


def _email(s) -> str:
    e = str(s or "").strip().lower()
    return e if "@" in e else ""


def _is_own_name(name: str) -> bool:
    import sbk_config

    fn = getattr(sbk_config, "is_own_name", None)
    try:
        return bool(name and fn and fn(name))
    except Exception:  # noqa: BLE001
        return False


def _transcript_text(items) -> tuple[str, list[tuple[str, str]]]:
    """'Speaker: words' lines (consecutive lines of one speaker joined) and the speakers."""
    lines: list[str] = []
    speakers: list[tuple[str, str]] = []
    last, buf = None, []
    for it in items or []:
        sp = it.get("speaker") or {}
        name = _norm(sp.get("display_name"))
        email = _email(sp.get("matched_calendar_invitee_email"))
        if (email, name) not in speakers and (email or name):
            speakers.append((email, name))
        text = _norm(it.get("text"))
        if not text:
            continue
        if name != last and buf:
            lines.append(f"{last}: {' '.join(buf)}" if last else " ".join(buf))
            buf = []
        last = name
        buf.append(text)
    if buf:
        lines.append(f"{last}: {' '.join(buf)}" if last else " ".join(buf))
    return "\n".join(lines), speakers


def _meeting_text(m: dict, transcript: str) -> str:
    summary = _norm_block((m.get("default_summary") or {}).get("markdown_formatted"))
    parts = []
    if summary:
        parts.append(summary)
    if transcript:
        parts.append("## Transcript\n" + transcript)
    return "\n\n".join(parts)


def _norm_block(s) -> str:
    return str(s or "").strip()


def load_meetings(raw: Path) -> list[dict]:
    mdir = raw / "meetings"
    out = []
    for f in sorted(mdir.glob("*.json")) if mdir.exists() else []:
        m = fa_api.read_json(f, None)
        if isinstance(m, dict) and m.get("recording_id") not in (None, ""):
            out.append(m)
    return out


def my_addresses(meetings: list[dict], state: dict) -> tuple[set[str], str]:
    """(your emails, how they were found)."""
    mine = set(fa_api.my_emails()) | set(fa_api._emails(state.get("recorded_by") or []))
    if mine:
        return mine, "configured"
    recorders = {_email((m.get("recorded_by") or {}).get("email")) for m in meetings} - {""}
    if len(recorders) == 1:
        return recorders, "inferred: every meeting was recorded by this one address"
    return set(), "unknown"


def build_rows(raw: Path | None = None) -> tuple[list[dict], list[dict], dict]:
    raw = raw or fa_api.raw_dir()
    meetings = load_meetings(raw)
    state = fa_api.read_json(raw / "state.json", {}) or {}
    me, me_how = my_addresses(meetings, state)

    def is_me(email: str, name: str) -> bool:
        if email:
            return email in me
        return _is_own_name(name)

    stats = {
        "meetings": len(meetings),
        "with_transcript": 0,
        "with_summary": 0,
        "speakers_fallback": 0,
        "action_items": 0,
        "action_items_mine_open": 0,
        "me": me_how,
    }

    # name -> email, for names that belong to exactly one email in all meetings
    emails_by_name: dict[str, set[str]] = {}
    parsed = []
    for m in meetings:
        transcript, speakers = _transcript_text(m.get("transcript"))
        invitees = []
        for inv in m.get("calendar_invitees") or []:
            e, n = _email(inv.get("email")), _norm(inv.get("name"))
            if e or n:
                invitees.append((e, n))
        rb = m.get("recorded_by") or {}
        recorder = (_email(rb.get("email")), _norm(rb.get("name")))
        for e, n in invitees + speakers + [recorder]:
            if e and n:
                emails_by_name.setdefault(n.lower(), set()).add(e)
        parsed.append((m, transcript, speakers, invitees, recorder))
    known = {n: next(iter(es)) for n, es in emails_by_name.items() if len(es) == 1}

    people: dict[str, dict] = {}
    names_seen: dict[str, Counter] = {}
    interactions: list[dict] = []
    used_urls: set[str] = set()

    for m, transcript, speakers, invitees, recorder in parsed:
        ts = fa_api.iso(
            m.get("recording_start_time") or m.get("scheduled_start_time") or m.get("created_at")
        )
        title = _norm(m.get("meeting_title") or m.get("title")) or "Fathom meeting"
        stats["with_transcript"] += bool(transcript)
        stats["with_summary"] += bool((m.get("default_summary") or {}).get("markdown_formatted"))

        attendees = list(invitees)
        if not attendees:
            if speakers:
                stats["speakers_fallback"] += 1
            attendees = list(speakers)
        if recorder[0] or recorder[1]:
            attendees.append(recorder)

        per_meeting: dict[str, tuple[str, str]] = {}
        for e, n in attendees:
            e = e or known.get(n.lower(), "")
            k = f"e:{e}" if e else f"n:{n.lower()}"
            if k not in per_meeting or (n and not per_meeting[k][1]):
                per_meeting[k] = (e, n)

        labels: list[str] = []
        for k, (e, n) in per_meeting.items():
            if is_me(e, n):
                continue
            labels.append(e or n)
            row = people.setdefault(
                k,
                {
                    "source": fa_api.SOURCE,
                    "name": n,
                    "email": e,
                    "phone": "",
                    "company": "",
                    "title": "",
                    "first_seen": ts,
                    "last_seen": ts,
                    "interactions": 0,
                    "url": "",
                },
            )
            row["interactions"] += 1
            if ts and (not row["first_seen"] or ts < row["first_seen"]):
                row["first_seen"] = ts
            if ts and ts > row["last_seen"]:
                row["last_seen"] = ts
            if n:
                names_seen.setdefault(k, Counter())[n] += 1

        if recorder[0] and is_me(recorder[0], recorder[1]):
            role = "organizer"
        elif any(is_me(e, n) for e, n in invitees):
            role = "attendee"
        else:
            role = "other"
        url = str(m.get("url") or "")
        interactions.append(
            {
                "source": fa_api.SOURCE,
                "ts": ts,
                "kind": "meeting",
                "title": title,
                "text": _meeting_text(m, transcript),
                "participants": fa_api.MULTI_SEP.join(labels),
                "owner_role": role,
                "due": "",
                "url": url,
                "status": "done",  # a recorded meeting is over
            }
        )

        for i, ai in enumerate(m.get("action_items") or [], start=1):
            desc = _norm(ai.get("description"))
            if not desc:
                continue
            stats["action_items"] += 1
            asg = ai.get("assignee") or {}
            a_email, a_name = _email(asg.get("email")), _norm(asg.get("name"))
            a_email = a_email or known.get(a_name.lower(), "")
            mine = bool((a_email or a_name) and is_me(a_email, a_name))
            done = bool(ai.get("completed"))
            if mine:
                parts = labels
            else:
                parts = [a_email or a_name] if (a_email or a_name) else []
            item_url = str(ai.get("recording_playback_url") or "") or (
                f"{url}#action-{i}" if url else ""
            )
            if item_url in used_urls:
                item_url = f"{item_url}#{i}"
            used_urls.add(item_url)
            if mine and not done:
                stats["action_items_mine_open"] += 1
            interactions.append(
                {
                    "source": fa_api.SOURCE,
                    "ts": ts,
                    "kind": "record",
                    "title": f"Action item: {desc}"[:TITLE_MAX],
                    "text": f"{desc}\nFrom the meeting: {title}",
                    "participants": fa_api.MULTI_SEP.join(p for p in parts if p),
                    "owner_role": "assignee" if mine else "other",
                    "due": "",
                    "url": item_url,
                    "status": "done" if done else "open",
                }
            )

    for k, c in names_seen.items():
        people[k]["name"] = c.most_common(1)[0][0]
    contacts = sorted(people.values(), key=lambda r: (r["email"] or "~", r["name"]))
    interactions.sort(key=lambda r: (r["ts"], r["kind"] != "meeting"))
    stats["contacts"] = len(contacts)
    return contacts, interactions, stats


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

    import sbk_config

    cdf = pd.DataFrame(contacts, columns=fa_api.CONTACT_COLUMNS)
    idf = pd.DataFrame(interactions, columns=fa_api.INTERACTION_COLUMNS)
    for col in fa_api.CONTACT_COLUMNS:
        if col != "interactions":
            cdf[col] = cdf[col].fillna("").astype(str)
    cdf["interactions"] = cdf["interactions"].fillna(0).astype("int64")
    for col in fa_api.INTERACTION_COLUMNS:
        idf[col] = idf[col].fillna("").astype(str)
    sbk_config.safe_write_parquet(cdf, fa_api.contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, fa_api.interactions_path(), index=False)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the downloaded Fathom meetings into plugin-contacts.parquet and "
        "plugin-interactions.parquet (generic intake contract)."
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    parse_args(argv)
    raw = fa_api.raw_dir()
    if not (raw / "meetings").exists():
        print(
            f"fathom: nothing downloaded yet in {raw}; run: uv run python tools/fathom/fa-l0-download.py",
            file=sys.stderr,
        )
        return 1
    contacts, interactions, stats = build_rows(raw)
    write_outputs(contacts, interactions)
    print(
        f"fathom L1: {stats['meetings']} meetings ({stats['with_transcript']} with transcript, "
        f"{stats['with_summary']} with summary), {stats['action_items']} action items "
        f"({stats['action_items_mine_open']} open and yours), {stats['contacts']} contacts; "
        f"your emails: {stats['me']}"
    )
    return 0


if __name__ == "__main__":
    parse_args()  # --help and bad flags answer before the pipeline step starts
    if not (fa_api.raw_dir() / "meetings").exists():
        sys.exit(main([]))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-fathom-enrich", source=fa_api.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main([])

    sys.exit(_run())
