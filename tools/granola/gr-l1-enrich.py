#!/usr/bin/env python3
"""Granola L1: downloaded or imported notes -> the generic intake contract.

Reads <data root>/granola/raw/notes/*.json (written by gr-l0-download.py or
gr-l0-import-csv.py) and writes:
  granola/processed/plugin-contacts.parquet      one row per person in your meetings
  granola/processed/plugin-interactions.parquet  one row per note (kind=meeting), the note
                                                 text in `text`

People come from the note's attendees and its calendar invitees (and the note's owner
when a note was shared with you), keyed by email, else by name. You are left out of
contacts and of `participants`, which the kernel reads as "the other people"
(tools/cross-source/plugin_intake.py). Who "you" are: the addresses in own_emails of
sbk.config.json plus granola.own_email; when neither is set, or none of them owns a
note, also the owner of most notes (printed, so you can check it). Deleted notes are
skipped, and so is a CSV-imported note that the API download also has (same title, same
day), so a meeting is never counted twice when you switch route.

`text` is the summary (markdown), then your private notes, then the transcript as
'Speaker: words' lines (granola.text_include_transcript, default true). Every note is
about a meeting that already happened, so `status` is "done": a note never becomes a
commitment by itself.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr_api  # noqa: E402


def _norm_name(name) -> str:
    return " ".join(str(name or "").split()).strip()


def _person_key(email: str, name: str) -> str:
    return f"e:{email.lower()}" if email else f"n:{_norm_name(name).lower()}"


def _read_notes(stats: dict) -> list[dict]:
    notes = []
    d = gr_api.notes_dir()
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        n = gr_api.read_json(f, None)
        if not isinstance(n, dict) or not n.get("id"):
            stats["unreadable"] += 1
            continue
        if n.get("deleted_at"):
            stats["deleted_skipped"] += 1
            continue
        notes.append(n)
    return notes


def _title_day(title, when) -> tuple[str, str]:
    return (_norm_name(title).lower(), gr_api.iso(when)[:10])


def drop_csv_duplicates(notes: list[dict]) -> tuple[list[dict], int]:
    """Leave out a CSV-imported note when the API download has the same note.

    A CSV export without an id column gives its rows their own ids, so after a switch from
    the CSV route to the API (or the other way round) the same meeting would count twice.
    Same title and same day (the API note's creation or scheduled start) = same note.
    """
    api_keys: set[tuple[str, str]] = set()
    for n in notes:
        if n.get("_origin") == "csv":
            continue
        cal = n.get("calendar_event") if isinstance(n.get("calendar_event"), dict) else {}
        title = n.get("title") or (cal or {}).get("event_title")
        for when in (n.get("created_at"), (cal or {}).get("scheduled_start_time")):
            if title and when:
                api_keys.add(_title_day(title, when))
    kept, dropped = [], 0
    for n in notes:
        if (
            n.get("_origin") == "csv"
            and n.get("title")
            and n.get("created_at")
            and _title_day(n["title"], n["created_at"]) in api_keys
        ):
            dropped += 1
            continue
        kept.append(n)
    return kept, dropped


def own_emails(notes: list[dict]) -> tuple[set[str], str]:
    """(your addresses, how they were found)."""
    import sbk_config

    mine = {str(e).strip().lower() for e in getattr(sbk_config, "OWN_EMAILS", ()) or () if e}
    extra = gr_api.cfg("own_email", "")
    if isinstance(extra, str):
        extra = [extra]
    mine |= {str(e).strip().lower() for e in extra or [] if str(e).strip()}
    owners = Counter(
        str((n.get("owner") or {}).get("email") or "").lower()
        for n in notes
        if isinstance(n.get("owner"), dict) and (n.get("owner") or {}).get("email")
    )
    if mine and (not owners or mine & set(owners)):
        return mine, "configured"
    if owners:
        # Nothing configured, or none of your configured addresses owns a note (your Granola
        # login uses another address): the owner of most notes is you, with the personal key.
        top = owners.most_common(1)[0][0]
        how = f"inferred: owner of most notes ({top})"
        return mine | {top}, ("configured + " + how) if mine else how
    return mine, "configured" if mine else "unknown"


def _people_of(note: dict) -> list[tuple[str, str]]:
    """(email, name) of attendees, calendar invitees and the owner, de-duplicated."""
    out: dict[str, tuple[str, str]] = {}

    def add(email, name):
        email = str(email or "").strip().lower()
        name = _norm_name(name)
        if not (email or name):
            return
        k = _person_key(email, name)
        if k not in out or (name and not out[k][1]):
            out[k] = (email, name)

    for a in note.get("attendees") or []:
        if isinstance(a, dict):
            add(a.get("email"), a.get("name"))
    cal = note.get("calendar_event") or {}
    if isinstance(cal, dict):
        for inv in cal.get("invitees") or []:
            if isinstance(inv, dict):
                add(inv.get("email"), "")
    owner = note.get("owner")
    if isinstance(owner, dict):
        add(owner.get("email"), owner.get("name"))
    # a name-only entry for a person whose email is also listed is the same person
    named = {name.lower(): e for e, name in out.values() if e and name}
    return [(e, n) for e, n in out.values() if e or n.lower() not in named]


def note_text(note: dict, include_transcript: bool = True) -> str:
    parts = []
    summary = str(note.get("summary_markdown") or note.get("summary_text") or "").strip()
    if summary:
        parts.append(summary)
    private = str(note.get("private_notes_markdown") or note.get("private_notes_text") or "")
    if private.strip():
        parts.append("## My notes\n" + private.strip())
    if include_transcript:
        transcript = str(note.get("transcript_text") or "").strip() or gr_api.transcript_to_text(
            note.get("transcript")
        )
        if transcript:
            parts.append("## Transcript\n" + transcript)
    return "\n\n".join(parts)


def _role(note: dict, mine: set[str], people: list[tuple[str, str]]) -> str:
    cal = note.get("calendar_event") or {}
    organiser = str((cal or {}).get("organiser") or "").lower() if isinstance(cal, dict) else ""
    if organiser and organiser in mine:
        return "organizer"
    owner = note.get("owner") if isinstance(note.get("owner"), dict) else {}
    if str((owner or {}).get("email") or "").lower() in mine:
        return "attendee"  # you took the note, so you were in the meeting
    if any(e in mine for e, _ in people):
        return "attendee"
    if note.get("_origin") == "csv":
        return "attendee"  # the export holds only notes you own
    return "other"  # a note shared with you from a meeting you were not listed in


def build_rows(notes: list[dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    stats = {"notes": 0, "unreadable": 0, "deleted_skipped": 0, "with_text": 0}
    notes = notes if notes is not None else _read_notes(stats)
    notes, stats["csv_duplicates_skipped"] = drop_csv_duplicates(notes)
    mine, how = own_emails(notes)
    include_transcript = bool(gr_api.cfg("text_include_transcript", True))
    people: dict[str, dict] = {}
    names_seen: dict[str, Counter] = {}
    interactions: list[dict] = []

    for n in notes:
        stats["notes"] += 1
        cal = n.get("calendar_event") if isinstance(n.get("calendar_event"), dict) else {}
        ts = gr_api.iso((cal or {}).get("scheduled_start_time") or n.get("created_at"))
        found = _people_of(n)
        labels = []
        for email, name in found:
            if email and email in mine:
                continue
            labels.append(f"{name} <{email}>" if email and name else (email or name))
            k = _person_key(email, name)
            row = people.setdefault(
                k,
                {
                    "source": gr_api.SOURCE,
                    "name": name,
                    "email": email,
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
            if name:
                names_seen.setdefault(k, Counter())[name] += 1
        text = note_text(n, include_transcript)
        stats["with_text"] += bool(text)
        interactions.append(
            {
                "source": gr_api.SOURCE,
                "ts": ts,
                "kind": "meeting",
                "title": str(n.get("title") or (cal or {}).get("event_title") or ""),
                "text": text,
                "participants": gr_api.MULTI_SEP.join(labels),
                "owner_role": _role(n, mine, found),
                "due": "",
                "url": str(n.get("web_url") or ""),
                "status": "done",
            }
        )

    for k, c in names_seen.items():
        people[k]["name"] = c.most_common(1)[0][0]
    contacts = sorted(people.values(), key=lambda r: (r["email"] or "~", r["name"]))
    interactions.sort(key=lambda r: r["ts"])
    stats["contacts"] = len(contacts)
    stats["self"] = how
    return contacts, interactions, stats


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

    import sbk_config

    cdf = pd.DataFrame(contacts, columns=gr_api.CONTACT_COLUMNS)
    idf = pd.DataFrame(interactions, columns=gr_api.INTERACTION_COLUMNS)
    for col in gr_api.CONTACT_COLUMNS:
        if col != "interactions":
            cdf[col] = cdf[col].fillna("").astype(str)
    cdf["interactions"] = cdf["interactions"].fillna(0).astype("int64")
    for col in gr_api.INTERACTION_COLUMNS:
        idf[col] = idf[col].fillna("").astype(str)
    sbk_config.safe_write_parquet(cdf, gr_api.contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, gr_api.interactions_path(), index=False)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the downloaded or imported Granola notes into plugin-contacts.parquet "
        "and plugin-interactions.parquet (generic intake contract)."
    )
    return ap.parse_args(argv)


def _nothing_yet() -> bool:
    d = gr_api.notes_dir()
    return not d.exists() or not any(d.glob("*.json"))


def main(argv=None) -> int:
    parse_args(argv)
    if _nothing_yet():
        print(
            f"Granola: nothing downloaded yet in {gr_api.notes_dir()}; run "
            "tools/granola/gr-l0-download.py (API key) or gr-l0-import-csv.py (CSV export)",
            file=sys.stderr,
        )
        return 1
    contacts, interactions, stats = build_rows()
    write_outputs(contacts, interactions)
    print(
        f"Granola L1: {stats['notes']} notes ({stats['with_text']} with text, "
        f"{stats['deleted_skipped']} deleted skipped, {stats['csv_duplicates_skipped']} CSV rows "
        f"already downloaded through the API), {stats['contacts']} contacts; "
        f"you = {stats['self']}"
    )
    return 0


if __name__ == "__main__":
    parse_args()  # --help and bad flags answer before the pipeline step starts
    if _nothing_yet():
        sys.exit(main([]))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-granola-enrich", source=gr_api.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main([])

    sys.exit(_run())
