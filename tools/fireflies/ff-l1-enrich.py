#!/usr/bin/env python3
"""Fireflies L1: raw meetings, contacts and transcripts -> the generic intake contract.

Reads <data root>/fireflies/raw/ (written by ff-l0-download.py) and writes:
  fireflies/processed/plugin-contacts.parquet      one row per person met in your meetings,
                                                   plus your Fireflies contact list
  fireflies/processed/plugin-interactions.parquet  one row per meeting (kind=meeting, status
                                                   done, the AI summary in `text`) and one row
                                                   per action item (kind=record, status open)

People: from meeting_attendees (email, name, phone), the participants' emails, and the
speaker and attendance names; a name is joined to an email when it belongs to exactly one
email. You (the key owner's email or name, or own_emails / own_names in sbk.config.json) and
the Fireflies note-taker are left out of contacts and of `participants`.

Action items: Fireflies gives them as one text per meeting; ff_api.parse_action_items splits
it by the bold owner names above the items. An item whose owner is you has owner_role
`assignee` (it becomes an open commitment in the knowledge layer, with the other people of the
meeting as `participants`); an item of someone else has owner_role `other` and that person as
participant; an item with no owner has owner_role `other`. `fireflies.action_items` in
sbk.config.json: "all" (default), "mine" (only yours), "none".
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ff_api  # noqa: E402

ACTION_MODES = ("all", "mine", "none")


def _own(me: dict):
    """(is_me_email, is_me_name) predicates for the key owner and sbk.config.json identity."""
    import sbk_config

    my_email = ff_api.norm_email(me.get("email"))
    my_name = ff_api.norm_name(me.get("name")).lower()

    def is_me_email(email: str) -> bool:
        return bool(email) and (email == my_email or sbk_config.is_own_email(email))

    def is_me_name(name: str) -> bool:
        n = ff_api.norm_name(name).lower()
        return bool(n) and (n == my_name or sbk_config.is_own_name(n))

    return is_me_email, is_me_name


def _attendees(m: dict) -> list[tuple[str, str, str]]:
    """(email, name, phone) of everyone Fireflies lists for one meeting, bots left out."""
    people: list[tuple[str, str, str]] = []
    for a in m.get("meeting_attendees") or []:
        if not isinstance(a, dict):
            continue
        email = ff_api.norm_email(a.get("email"))
        name = ff_api.norm_name(a.get("name") or a.get("displayName"))
        if name and "@" in name and not email:
            email, name = ff_api.norm_email(name), ""
        phone = str(a.get("phoneNumber") or "").strip()
        if (email or name or phone) and not ff_api.is_bot(name, email):
            people.append((email, name, phone))
    for e in m.get("participants") or []:
        # Fireflies sometimes joins several addresses in one string: split on , and ;
        for part in str(e or "").replace(";", ",").split(","):
            email = ff_api.norm_email(part)
            if email and not ff_api.is_bot("", email):
                people.append((email, "", ""))
    for s in m.get("speakers") or []:
        name = ff_api.norm_name((s or {}).get("name"))
        if name and not ff_api.is_bot(name) and not name.lower().startswith("speaker "):
            people.append(("", name, ""))
    for a in m.get("meeting_attendance") or []:
        name = ff_api.norm_name((a or {}).get("name"))
        if name and not ff_api.is_bot(name):
            people.append(("", name, ""))
    return people


def _name_to_email(meetings: list[dict], contacts: list[dict]) -> dict[str, str]:
    """Display name -> email, only for names that belong to exactly one email."""
    by_name: dict[str, set[str]] = {}
    for m in meetings:
        for email, name, _phone in _attendees(m):
            if email and name:
                by_name.setdefault(name.lower(), set()).add(email)
    for c in contacts:
        email = ff_api.norm_email(c.get("email"))
        name = ff_api.norm_name(c.get("name"))
        if email and name:
            by_name.setdefault(name.lower(), set()).add(email)
    return {n: next(iter(es)) for n, es in by_name.items() if len(es) == 1}


def _meeting_text(m: dict, sentences: list | None) -> str:
    s = m.get("summary") or {}
    text = ""
    for key in ("overview", "short_summary", "gist"):
        if str(s.get(key) or "").strip():
            text = str(s[key]).strip()
            break
    if not text and sentences:
        text = ff_api.sentences_to_text(sentences)  # no summary (plan, or not ready): transcript
    return text[: ff_api.TEXT_MAX]


def _owner_is_me(owner: str, is_me_email, is_me_name, me: dict, first_names: Counter) -> bool:
    if not owner:
        return False
    if "@" in owner:
        return is_me_email(ff_api.norm_email(owner))
    if is_me_name(owner):
        return True
    # A lone first name ("Alex") is yours only when it is your first name and nobody
    # else in that meeting has the same first name.
    my_first = ff_api.norm_name(me.get("name")).split(" ")[0].lower() if me.get("name") else ""
    o = ff_api.norm_name(owner).lower()
    # first_names counts the other people of the meeting (you are not in it).
    return bool(my_first) and " " not in o and o == my_first and first_names[o] == 0


def build_rows(raw: Path | None = None, mode: str | None = None):
    raw = raw or ff_api.raw_dir()
    mode = (mode or str(ff_api.cfg("action_items", "all"))).lower()
    if mode not in ACTION_MODES:
        mode = "all"
    me = ff_api.read_json(raw / "me.json", {}) or {}
    is_me_email, is_me_name = _own(me)
    contacts_list = (ff_api.read_json(raw / "contacts.json", {}) or {}).get("contacts") or []

    meetings: list[dict] = []
    mdir = raw / "meetings"
    for f in sorted(mdir.glob("*.json")) if mdir.exists() else []:
        m = ff_api.read_json(f, None)
        if isinstance(m, dict) and m.get("id"):
            meetings.append(m)
    known_email = _name_to_email(meetings, contacts_list)

    stats = {
        "meetings": 0,
        "with_summary": 0,
        "with_transcript": 0,
        "action_items": 0,
        "action_items_mine": 0,
        "action_items_unassigned": 0,
    }
    people: dict[str, dict] = {}
    names_seen: dict[str, Counter] = {}
    interactions: list[dict] = []

    def is_me(email: str, name: str) -> bool:
        return is_me_email(email) or (not email and is_me_name(name))

    for m in meetings:
        stats["meetings"] += 1
        ts = ff_api.meeting_ts(m)
        tid = str(m["id"])
        url = str(m.get("transcript_url") or "")
        sentences = (
            ff_api.read_json(raw / "transcripts" / f"{ff_api.safe_id(tid)}.json", {}) or {}
        ).get("sentences")
        stats["with_transcript"] += bool(sentences)

        per_meeting: dict[str, tuple[str, str, str]] = {}
        for email, name, phone in _attendees(m):
            email = email or known_email.get(name.lower(), "")
            if is_me(email, name):
                continue
            key = f"e:{email}" if email else f"n:{name.lower()}"
            old = per_meeting.get(key, ("", "", ""))
            per_meeting[key] = (email, name or old[1], phone or old[2])
        # A name already covered by an email row of the same meeting is the same person.
        named = {n.lower() for e, n, _p in per_meeting.values() if e and n}
        for key in [k for k in per_meeting if k.startswith("n:") and k[2:] in named]:
            per_meeting.pop(key)

        labels = []
        first_names: Counter = Counter()
        for key, (email, name, phone) in per_meeting.items():
            labels.append(email or name)
            if name:
                first_names[name.split(" ")[0].lower()] += 1
            row = people.setdefault(
                key,
                {
                    "source": ff_api.SOURCE,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "company": "",
                    "title": "",
                    "first_seen": ts,
                    "last_seen": ts,
                    "interactions": 0,
                    "url": "",
                },
            )
            row["interactions"] += 1
            if phone and not row["phone"]:
                row["phone"] = phone
            if ts and (not row["first_seen"] or ts < row["first_seen"]):
                row["first_seen"] = ts
            if ts and ts > row["last_seen"]:
                row["last_seen"] = ts
            if name:
                names_seen.setdefault(key, Counter())[name] += 1

        organizer = ff_api.norm_email(m.get("organizer_email"))
        role = "organizer" if organizer and is_me_email(organizer) else "attendee"
        text = _meeting_text(m, sentences)
        stats["with_summary"] += bool(str((m.get("summary") or {}).get("overview") or "").strip())
        title = str(m.get("title") or "").strip() or "(untitled meeting)"
        interactions.append(
            {
                "source": ff_api.SOURCE,
                "ts": ts,
                "kind": "meeting",
                "title": title,
                "text": text,
                "participants": ff_api.MULTI_SEP.join(labels),
                "owner_role": role,
                "due": "",
                "url": url,
                "status": "done",  # a transcript exists only once the meeting is over
            }
        )

        if mode == "none":
            continue
        for it in ff_api.parse_action_items((m.get("summary") or {}).get("action_items")):
            owner = it["owner"]
            mine = _owner_is_me(owner, is_me_email, is_me_name, me, first_names)
            if mode == "mine" and not mine:
                continue
            stats["action_items"] += 1
            stats["action_items_mine"] += mine
            stats["action_items_unassigned"] += not owner
            if mine:
                parts = labels
            elif owner:
                o_email = ff_api.norm_email(owner) or known_email.get(owner.lower(), "")
                parts = [o_email or owner]
            else:
                parts = []
            interactions.append(
                {
                    "source": ff_api.SOURCE,
                    "ts": ts,
                    "kind": "record",
                    "title": it["item"][:300],
                    "text": f"Action item from the meeting '{title}'"
                    + (f" at {it['offset']}" if it["offset"] else "")
                    + (f", owner: {owner}" if owner else ", no owner named"),
                    "participants": ff_api.MULTI_SEP.join(parts),
                    "owner_role": "assignee" if mine else "other",
                    "due": "",
                    # one id per item: the meeting link plus a hash of the item text
                    "url": f"{url}#action-{ff_api.item_key(it['item'])}" if url else "",
                    "status": "open",  # Fireflies has no done state for summary items
                }
            )

    # Your Fireflies contact list: people who were in meetings with you.
    for c in contacts_list:
        if not isinstance(c, dict):
            continue
        email = ff_api.norm_email(c.get("email"))
        name = ff_api.norm_name(c.get("name"))
        if not email or ff_api.is_bot(name, email) or is_me(email, name):
            continue
        key = f"e:{email}"
        last = ff_api.iso(c.get("last_meeting_date"))
        row = people.get(key)
        if row is None:
            people[key] = {
                "source": ff_api.SOURCE,
                "name": name,
                "email": email,
                "phone": "",
                "company": "",
                "title": "",
                "first_seen": "",
                "last_seen": last,
                "interactions": 0,
                "url": "",
            }
        else:
            if name and not row["name"]:
                row["name"] = name
            if last and last > (row["last_seen"] or ""):
                row["last_seen"] = last

    for k, c in names_seen.items():
        people[k]["name"] = c.most_common(1)[0][0]
    contacts = sorted(people.values(), key=lambda r: (r["email"] or "~", r["name"]))
    interactions.sort(key=lambda r: (r["ts"], r["kind"] != "meeting", r["title"]))
    stats["contacts"] = len(contacts)
    return contacts, interactions, stats


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

    import sbk_config

    cdf = pd.DataFrame(contacts, columns=ff_api.CONTACT_COLUMNS)
    idf = pd.DataFrame(interactions, columns=ff_api.INTERACTION_COLUMNS)
    for col in ff_api.CONTACT_COLUMNS:
        if col != "interactions":
            cdf[col] = cdf[col].fillna("").astype(str)
    cdf["interactions"] = cdf["interactions"].fillna(0).astype("int64")
    for col in ff_api.INTERACTION_COLUMNS:
        idf[col] = idf[col].fillna("").astype(str)
    sbk_config.safe_write_parquet(cdf, ff_api.contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, ff_api.interactions_path(), index=False)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the downloaded Fireflies data into plugin-contacts.parquet and "
        "plugin-interactions.parquet (generic intake contract)."
    )
    ap.add_argument(
        "--action-items",
        choices=ACTION_MODES,
        default=None,
        help="which action items to write (default fireflies.action_items or 'all')",
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    raw = ff_api.raw_dir()
    if not (raw / "meetings").exists():
        print(
            f"Fireflies: nothing downloaded yet in {raw}; run: "
            "uv run python tools/fireflies/ff-l0-download.py",
            file=sys.stderr,
        )
        return 1
    contacts, interactions, stats = build_rows(raw, args.action_items)
    write_outputs(contacts, interactions)
    print(
        f"Fireflies L1: {stats['meetings']} meetings ({stats['with_summary']} with summary, "
        f"{stats['with_transcript']} with transcript), {stats['action_items']} action items "
        f"({stats['action_items_mine']} yours), {stats['contacts']} contacts"
    )
    return 0


if __name__ == "__main__":
    _args = parse_args()  # --help and bad flags answer before the pipeline step starts
    _argv = ["--action-items", _args.action_items] if _args.action_items else []
    if not (ff_api.raw_dir() / "meetings").exists():
        sys.exit(main(_argv))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-fireflies-enrich", source=ff_api.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main(_argv)

    sys.exit(_run())
