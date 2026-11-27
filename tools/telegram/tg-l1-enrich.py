#!/usr/bin/env python3
"""Telegram L1: imported chats -> the generic intake contract.

Reads <data root>/telegram/raw/ (written by tg-l0-import.py) and writes:
  telegram/processed/plugin-contacts.parquet      one row per person you talk with
  telegram/processed/plugin-interactions.parquet  one row per chat and day (kind=message,
                                                  the day's messages in `text`), plus one
                                                  row per promise found in a message

Who "you" are: the user id of the export's personal information (or telegram.own_user_id);
for a single personal chat exported alone, the sender who is not the other person. Only when
no id is known, the names in owner / own_names of sbk.config.json. You are left out of the
contacts and of `participants`.

People are the other person of each personal chat and the members who wrote in a group.
Their phone number comes from the export's contacts list (matched by user id, else by a
unique full name); Telegram writes no email. Members of groups where more people wrote than
telegram.group_contacts_max_senders are named in the day's participants but get no contact
row of their own, unless you also talk with them elsewhere.

Days are the calendar days of the export's local time. Conversation rows are "done": a chat
is never a commitment by itself. Promise rows ("I'll send...", "ti mando...") are open while
the message is younger than telegram.promise_open_days, then "closed"; yours have owner_role
assignee, the other person's "other" (the kernel makes those a commitment only when a due date
was found in the sentence).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_export as tg  # noqa: E402


def _norm(s) -> str:
    return " ".join(str(s or "").split())


def _self(me: dict) -> tuple[set[str], set[str], str]:
    """(your sender ids 'user<id>', your names lowercase, how they were found)."""
    import sbk_config

    ids: set[str] = set()
    how = []
    if me.get("user_id"):
        ids.add(f"user{me['user_id']}")
        how.append(f"user id from the {me.get('how') or 'export'}")
    extra = tg.cfg("own_user_id", "")
    for x in [extra] if isinstance(extra, (str, int)) else list(extra or []):
        x = str(x).strip().removeprefix("user")
        if x:
            ids.add(f"user{x}")
            how.append("telegram.own_user_id")
    names = {n for n in getattr(sbk_config, "OWN_NAMES_NORMALIZED", set()) or set() if n}
    if not ids and names:
        how.append("owner / own_names of sbk.config.json")
    return ids, names, ", ".join(how) or "unknown (set owner / own_names or telegram.own_user_id)"


def _phones(contacts: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """(user id -> phone, full name lowercase -> phone when the name is unique)."""
    by_uid: dict[str, str] = {}
    names: dict[str, list[str]] = defaultdict(list)
    for c in contacts or []:
        phone = _norm(c.get("phone_number"))
        if not phone:
            continue
        uid = str(c.get("user_id") or "").strip()
        if uid:
            by_uid[uid] = phone
        name = tg.full_name(c.get("first_name"), c.get("last_name")).lower()
        if name:
            names[name].append(phone)
    by_name = {n: p[0] for n, p in names.items() if len(set(p)) == 1}
    return by_uid, by_name


def _read_chats() -> list[Path]:
    d = tg.chats_dir()
    return sorted(d.glob("*.json")) if d.exists() else []


def _body(m: dict) -> str:
    text = _norm(m.get("text"))
    if m.get("type") == "service":
        what = ["group call" if m.get("action") == "group_call" else "call"]
        if m.get("duration_seconds"):
            what.append(f"{m['duration_seconds']} s")
        if m.get("discard_reason"):
            what.append(str(m["discard_reason"]))
        return "[" + ", ".join(what) + "]"
    parts = []
    if m.get("forwarded_from"):
        parts.append(f"(forwarded from {m['forwarded_from']})")
    if m.get("media_type"):
        parts.append(f"[{m['media_type']}]")
    if text:
        parts.append(text)
    return " ".join(parts)


def _cap(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit] + f"\n... ({len(text) - limit} more characters)"
    return text


def build_rows(now: datetime | None = None) -> tuple[list[dict], list[dict], dict]:
    now = now or datetime.now(UTC)
    stats = Counter()
    me = tg.read_json(tg.me_path(), {}) or {}
    my_ids, my_names, how = _self(me)
    phone_by_uid, phone_by_name = _phones(tg.read_json(tg.contacts_raw_path(), []) or [])

    allowed = {str(t) for t in (tg.cfg("chat_types", None) or tg.DEFAULT_CHAT_TYPES)}
    excluded = {str(x).strip().lower() for x in (tg.cfg("exclude_chats", None) or [])}
    max_senders = int(tg.cfg("group_contacts_max_senders", 30))
    max_text = int(tg.cfg("max_text_chars", 20000))
    detect = bool(tg.cfg("detect_promises", True))
    open_days = int(tg.cfg("promise_open_days", 30))
    patterns = tg.promise_patterns() if detect else []
    import sbk_config

    me_label = sbk_config.OWNER_NAME or "Me"

    def is_me(m: dict) -> bool:
        fid = str(m.get("from_id") or m.get("actor_id") or "")
        if my_ids:
            return fid in my_ids
        name = _norm(m.get("from") or m.get("actor")).lower()
        return bool(name) and name in my_names

    people: dict[str, dict] = {}
    interactions: list[dict] = []

    def touch(key: str, name: str, ts: str, eligible: bool) -> None:
        p = people.setdefault(
            key,
            {"names": Counter(), "days": 0, "first": ts, "last": ts, "eligible": False},
        )
        if name:
            p["names"][name] += 1
        p["days"] += 1
        p["eligible"] = p["eligible"] or eligible
        if ts and (not p["first"] or ts < p["first"]):
            p["first"] = ts
        if ts and ts > p["last"]:
            p["last"] = ts

    for f in _read_chats():
        chat = tg.read_json(f, None)
        if not isinstance(chat, dict):
            stats["unreadable"] += 1
            continue
        ctype = str(chat.get("type") or "")
        cname = _norm(chat.get("name"))
        if ctype not in allowed:
            stats["chats_skipped_type"] += 1
            continue
        if excluded & {cname.lower(), str(chat.get("key") or "").lower(), str(chat.get("id"))}:
            stats["chats_excluded"] += 1
            continue
        personal = ctype == "personal_chat"
        other_key = f"user{chat.get('id')}" if personal else ""
        if personal and other_key in my_ids:
            stats["chats_skipped_type"] += 1
            continue
        msgs = [
            m
            for m in chat.get("messages") or []
            if isinstance(m, dict)
            and (
                m.get("type") == "message"
                or (m.get("type") == "service" and m.get("action") in tg.CALL_ACTIONS)
            )
        ]
        if not msgs:
            stats["chats_empty"] += 1
            continue
        stats["chats_read"] += 1
        by_id = {m.get("id"): m for m in msgs}
        group_senders = {
            str(m.get("from_id"))
            for m in msgs
            if not is_me(m) and str(m.get("from_id") or "").startswith("user")
        }
        eligible = personal or len(group_senders) <= max_senders
        if not personal and not eligible:
            stats["groups_over_sender_limit"] += 1
        shown = cname or ("a deleted account" if personal else "without a name")
        label = f"Telegram chat with {shown}" if personal else f"Telegram group {shown}"

        by_day: dict[str, list[dict]] = defaultdict(list)
        for m in msgs:
            day = tg.message_day(m)
            if day:
                by_day[day].append(m)
        for day in sorted(by_day):
            day_msgs = by_day[day]
            ts_first = tg.message_ts(day_msgs[0])
            lines, senders, me_wrote, found = [], {}, False, []
            for m in day_msgs:
                mine = is_me(m)
                me_wrote = me_wrote or mine
                name = _norm(m.get("from") or m.get("actor"))
                who = me_label if mine else (name or "Deleted account")
                lines.append(f"{str(m.get('date') or '')[11:16]} {who}: {_body(m)}".strip())
                fid = str(m.get("from_id") or m.get("actor_id") or "")
                if not mine and fid.startswith("user") and fid not in my_ids:
                    senders.setdefault(fid, name)
                if patterns and m.get("type") == "message" and m.get("text"):
                    sentence = tg.find_promise(m["text"], patterns)
                    if sentence:
                        found.append((m, sentence, mine, name))
            day_people = {other_key: cname} if personal else senders
            for key, name in day_people.items():
                touch(key, name, ts_first, eligible)
            names = [n for n in day_people.values() if n]
            stats["days"] += 1
            stats["messages"] += len(day_msgs)
            interactions.append(
                {
                    "source": tg.SOURCE,
                    "ts": ts_first,
                    "kind": "message",
                    "title": f"{label}, {len(day_msgs)} message{'s' if len(day_msgs) != 1 else ''}",
                    "text": _cap("\n".join(lines), max_text),
                    "participants": tg.MULTI_SEP.join(names),
                    "owner_role": "author" if me_wrote else "attendee",
                    "due": "",
                    "url": "",
                    "status": "done",
                }
            )
            for m, sentence, mine, name in found:
                ts = tg.message_ts(m)
                if mine:
                    replied = by_id.get(m.get("reply_to_message_id"))
                    if personal:
                        to = [cname]
                    elif replied is not None and not is_me(replied) and replied.get("from"):
                        to = [_norm(replied["from"])]
                    else:
                        to = names
                else:
                    to = [name] if name else []
                try:
                    age = now - datetime.fromisoformat(ts)
                except ValueError:
                    age = timedelta(days=open_days + 1)
                status = "open" if age <= timedelta(days=open_days) else "closed"
                stats["promises"] += 1
                stats["promises_open"] += status == "open"
                interactions.append(
                    {
                        "source": tg.SOURCE,
                        "ts": ts,
                        "kind": "message",
                        "title": "Promise: " + _norm(sentence)[:120],
                        "text": f"{label}, {m.get('date') or ts}\n"
                        f"{me_label if mine else name}: {m.get('text')}",
                        "participants": tg.MULTI_SEP.join(x for x in to if x),
                        "owner_role": "assignee" if mine else "other",
                        "due": tg.due_from_text(sentence, tg.message_day(m)),
                        "url": "",
                        "status": status,
                    }
                )

    contacts = []
    for key, p in people.items():
        if not p["eligible"]:
            stats["people_only_in_large_groups"] += 1
            continue
        name = p["names"].most_common(1)[0][0] if p["names"] else ""
        uid = key[4:] if key.startswith("user") else ""
        phone = phone_by_uid.get(uid, "") or phone_by_name.get(name.lower(), "")
        if not name and not phone:
            stats["people_without_name"] += 1
            continue
        if not my_ids and name.lower() in my_names:
            continue
        contacts.append(
            {
                "source": tg.SOURCE,
                "name": name,
                "email": "",
                "phone": phone,
                "company": "",
                "title": "",
                "first_seen": p["first"],
                "last_seen": p["last"],
                "interactions": int(p["days"]),
                "url": "",
            }
        )
    contacts.sort(key=lambda r: (r["name"].lower(), r["phone"]))
    interactions.sort(key=lambda r: (r["ts"], r["title"]))
    out = dict(stats)
    out["contacts"] = len(contacts)
    out["with_phone"] = sum(bool(c["phone"]) for c in contacts)
    out["self"] = how
    return contacts, interactions, out


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

    import sbk_config

    cdf = pd.DataFrame(contacts, columns=tg.CONTACT_COLUMNS)
    idf = pd.DataFrame(interactions, columns=tg.INTERACTION_COLUMNS)
    for col in tg.CONTACT_COLUMNS:
        if col != "interactions":
            cdf[col] = cdf[col].fillna("").astype(str)
    cdf["interactions"] = cdf["interactions"].fillna(0).astype("int64")
    for col in tg.INTERACTION_COLUMNS:
        idf[col] = idf[col].fillna("").astype(str)
    sbk_config.safe_write_parquet(cdf, tg.contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, tg.interactions_path(), index=False)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Turn the imported Telegram chats into plugin-contacts.parquet and "
        "plugin-interactions.parquet (generic intake contract)."
    )
    return ap.parse_args(argv)


def _nothing_yet() -> bool:
    return not _read_chats()


def main(argv=None) -> int:
    parse_args(argv)
    if _nothing_yet():
        print(
            f"Telegram: nothing imported yet in {tg.chats_dir()}; run "
            "tools/telegram/tg-l0-import.py <export folder>",
            file=sys.stderr,
        )
        return 1
    try:
        contacts, interactions, s = build_rows()
    except tg.TelegramError as e:
        print(f"Telegram: {e}", file=sys.stderr)
        return 1
    write_outputs(contacts, interactions)
    print(
        f"Telegram L1: {s.get('chats_read', 0)} chats, {s.get('days', 0)} conversation days, "
        f"{s.get('messages', 0)} messages, {s.get('promises', 0)} promises "
        f"({s.get('promises_open', 0)} open), {s['contacts']} contacts ({s['with_phone']} with "
        f"phone); {s.get('chats_skipped_type', 0)} chats of other types skipped; you = {s['self']}"
    )
    return 0


if __name__ == "__main__":
    parse_args()  # --help and bad flags answer before the pipeline step starts
    if _nothing_yet():
        sys.exit(main([]))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-telegram-enrich", source=tg.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main([])

    sys.exit(_run())
