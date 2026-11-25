#!/usr/bin/env python3
"""Zoom L1: raw meetings, participants and transcripts -> the generic intake contract.

Reads <data root>/zoom/raw/ (written by zm-l0-download.py) and writes:
  zoom/processed/plugin-contacts.parquet      one row per person met in your meetings
  zoom/processed/plugin-interactions.parquet  one row per meeting instance (kind=meeting),
                                              the transcript as plain text in `text`

People are keyed by email when Zoom gives one, otherwise by display name; a name that
belongs to exactly one email elsewhere is folded into that email. Zoom shows the email of
people outside your account only in some cases (email display rules), so external guests
often appear by name only. When the participant list is unavailable, the speaker names of
the transcript are used instead.
You yourself (the login's email or display name, or an address in own_emails) are left out
of contacts and of `participants`, which the kernel reads as "the other people"
(tools/cross-source/plugin_intake.py). Passcodes are removed from `url`.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zm_api  # noqa: E402


def _norm_name(name: str) -> str:
    return " ".join(str(name or "").split()).strip()


def _person_key(email: str, name: str) -> str:
    return f"e:{email.lower()}" if email else f"n:{_norm_name(name).lower()}"


def _is_self(email: str, name: str, me: dict) -> bool:
    import sbk_config

    if email and (
        email.lower() == str(me.get("email") or "").lower() or sbk_config.is_own_email(email)
    ):
        return True
    dn = _norm_name(me.get("display_name") or "").lower()
    return bool(not email and name and dn and _norm_name(name).lower() == dn)


def _read_meetings(raw: Path, stats: dict) -> list[tuple[dict, str, str, list]]:
    """(meeting, ts, transcript text, attendees) per meeting; attendees = (email, name, seen)."""
    out = []
    for mf in sorted((raw / "meetings").glob("*.json")) if (raw / "meetings").exists() else []:
        m = zm_api.read_json(mf, None)
        if not isinstance(m, dict) or not m.get("uuid"):
            continue
        key = mf.stem
        stats["meetings"] += 1
        ts = zm_api.iso(m.get("start_time"))

        text, speakers = "", []
        vtt = raw / "transcripts" / f"{key}.vtt"
        if vtt.exists():
            text, speakers = zm_api.vtt_to_text(vtt.read_text(encoding="utf-8", errors="replace"))
            stats["with_transcript"] += bool(text)

        attendees: list[tuple[str, str, str]] = []
        pj = zm_api.read_json(raw / "participants" / f"{key}.json", {}) or {}
        if pj.get("status") == "ok":
            stats["with_participants"] += 1
            for p in pj.get("participants") or []:
                email = str(p.get("user_email") or "").strip().lower()
                name = _norm_name(p.get("name"))
                if email or name:
                    attendees.append((email, name, zm_api.iso(p.get("join_time")) or ts))
        elif speakers:
            stats["speakers_fallback"] += 1
            attendees = [("", _norm_name(s), ts) for s in speakers]
        out.append((m, ts, text, attendees))
    return out


def _name_to_email(meetings) -> dict[str, str]:
    """Display name -> email, only for names that belong to exactly one email."""
    emails_by_name: dict[str, set[str]] = {}
    for _m, _ts, _text, attendees in meetings:
        for email, name, _seen in attendees:
            if email and name:
                emails_by_name.setdefault(name.lower(), set()).add(email)
    return {n: next(iter(es)) for n, es in emails_by_name.items() if len(es) == 1}


def build_rows(raw: Path | None = None) -> tuple[list[dict], list[dict], dict]:
    raw = raw or zm_api.raw_dir()
    me = zm_api.read_json(raw / "me.json", {}) or {}
    my_id = me.get("id")
    interactions: list[dict] = []
    people: dict[str, dict] = {}
    names_seen: dict[str, Counter] = {}
    stats = {"meetings": 0, "with_transcript": 0, "with_participants": 0, "speakers_fallback": 0}

    meetings = _read_meetings(raw, stats)
    # A guest who joined once with an email and once by name only (or who is known only
    # from the transcript's speaker names) is the same person when that name belongs to
    # exactly one email: one contact, not two.
    known_email = _name_to_email(meetings)

    for m, ts, text, attendees in meetings:
        # one entry per person per meeting (people rejoin: several rows in Zoom's list)
        per_meeting: dict[str, tuple[str, str, str]] = {}
        for email, name, seen in attendees:
            email = email or known_email.get(name.lower(), "")
            k = _person_key(email, name)
            if k not in per_meeting or (seen and seen < per_meeting[k][2]):
                per_meeting[k] = (email, name or per_meeting.get(k, ("", "", ""))[1], seen)

        labels = []  # the other people (the kernel contract: you are not a participant)
        for k, (email, name, seen) in per_meeting.items():
            if _is_self(email, name, me):
                continue
            labels.append(email or name)
            row = people.setdefault(
                k,
                {
                    "source": zm_api.SOURCE,
                    "name": name,
                    "email": email,
                    "phone": "",
                    "company": "",
                    "title": "",
                    "first_seen": seen,
                    "last_seen": seen,
                    "interactions": 0,
                    "url": "",
                },
            )
            row["interactions"] += 1
            if seen and (not row["first_seen"] or seen < row["first_seen"]):
                row["first_seen"] = seen
            if seen and seen > row["last_seen"]:
                row["last_seen"] = seen
            if name:
                names_seen.setdefault(k, Counter())[name] += 1

        if my_id and m.get("host_id") == my_id:
            role = "organizer"
        elif m.get("host_id"):
            role = "attendee"
        else:
            role = "other"
        interactions.append(
            {
                "source": zm_api.SOURCE,
                "ts": ts,
                "kind": "meeting",
                "title": str(m.get("topic") or ""),
                "text": text,
                "participants": zm_api.MULTI_SEP.join(labels),
                "owner_role": role,
                "due": "",
                "url": zm_api.clean_url(m.get("share_url")),
                "status": "done",  # recordings and previous_meetings are past meetings
            }
        )

    for k, c in names_seen.items():
        people[k]["name"] = c.most_common(1)[0][0]
    contacts = sorted(people.values(), key=lambda r: (r["email"] or "~", r["name"]))
    interactions.sort(key=lambda r: r["ts"])
    stats["contacts"] = len(contacts)
    return contacts, interactions, stats


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

    import sbk_config

    cdf = pd.DataFrame(contacts, columns=zm_api.CONTACT_COLUMNS)
    idf = pd.DataFrame(interactions, columns=zm_api.INTERACTION_COLUMNS)
    for col in zm_api.CONTACT_COLUMNS:
        if col != "interactions":
            cdf[col] = cdf[col].fillna("").astype(str)
    cdf["interactions"] = cdf["interactions"].fillna(0).astype("int64")
    for col in zm_api.INTERACTION_COLUMNS:
        idf[col] = idf[col].fillna("").astype(str)
    sbk_config.safe_write_parquet(cdf, zm_api.contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, zm_api.interactions_path(), index=False)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the downloaded Zoom data into plugin-contacts.parquet and "
        "plugin-interactions.parquet (generic intake contract)."
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    parse_args(argv)
    raw = zm_api.raw_dir()
    if not (raw / "meetings").exists():
        print(
            f"Zoom: nothing downloaded yet in {raw}; run: uv run python tools/zoom/zm-l0-download.py",
            file=sys.stderr,
        )
        return 1
    contacts, interactions, stats = build_rows(raw)
    write_outputs(contacts, interactions)
    print(
        f"Zoom L1: {stats['meetings']} meetings ({stats['with_transcript']} with transcript, "
        f"{stats['with_participants']} with participant list), {stats['contacts']} contacts"
    )
    return 0


if __name__ == "__main__":
    parse_args()  # --help and bad flags answer before the pipeline step starts
    if not (zm_api.raw_dir() / "meetings").exists():
        sys.exit(main([]))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-zoom-enrich", source=zm_api.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main([])

    sys.exit(_run())
