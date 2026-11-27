#!/usr/bin/env python3
"""Microsoft Teams L1: downloaded chats -> the generic intake contract.

Reads <data root>/teams/raw/<label>/ (written by tm-l0-download.py) for every label and writes:
  teams/processed/plugin-contacts.parquet      one row per chat member (you left out)
  teams/processed/plugin-interactions.parquet  one row per chat and day with messages,
                                               kind=message, the day's lines in `text`

A day is a calendar day in teams.timezone (else SBK_DISPLAY_TZ, else UTC). `participants`
are the other people who wrote that day; in a 1:1 chat always the other person, and in a
group chat where only you wrote, the other members. owner_role is author when you wrote
that day, attendee otherwise. Rows are written with status done: a chat-day is never a
commitment. System events, deleted messages and bot messages are not counted as people.
No network, no token: it only reads the local files.

    uv run python tools/teams/tm-l1-enrich.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tm_graph as tg  # noqa: E402

import sbk_config  # noqa: E402

GROUP_FALLBACK_MAX = 50


def local_zone() -> ZoneInfo:
    name = str(tg.cfg("timezone", "") or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            print(
                f"teams: timezone {name!r} unknown, using {sbk_config.DISPLAY_TZ}", file=sys.stderr
            )
    return sbk_config.DISPLAY_TZ


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _is_self(user_id: str, email: str, me: dict) -> bool:
    if user_id and user_id == me.get("id"):
        return True
    if email:
        own = {str(me.get("mail") or "").lower(), str(me.get("userPrincipalName") or "").lower()}
        return email.lower() in own - {""} or sbk_config.is_own_email(email)
    return False


def _label(person: dict) -> str:
    name, email = person["name"], person["email"]
    if email:
        return f"{name} <{email}>" if name else email
    return name


def _title(chat: dict, others: list[dict]) -> str:
    names = sorted({p["name"] or p["email"] for p in others if p["name"] or p["email"]})
    if chat.get("chatType") == "oneOnOne":
        return f"Teams chat with {names[0]}" if names else "Teams chat"
    if chat.get("topic"):
        return f"Teams chat: {chat['topic']}"
    kind = "meeting chat" if chat.get("chatType") == "meeting" else "group chat"
    if not names:
        return f"Teams {kind}"
    shown = ", ".join(names[:3])
    more = f" and {len(names) - 3} others" if len(names) > 3 else ""
    return f"Teams {kind} with {shown}{more}"


class People:
    """Contacts keyed by email, else Entra user id, else name."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.by_uid: dict[str, str] = {}

    def add(self, user_id: str, name: str, email: str) -> str:
        key = self.by_uid.get(user_id) if user_id else None
        if key is None:
            key = f"e:{email}" if email else (f"u:{user_id}" if user_id else f"n:{name.lower()}")
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = {
                "source": tg.SOURCE,
                "name": name,
                "email": email,
                "phone": "",
                "company": "",
                "title": "",
                "first_seen": "",
                "last_seen": "",
                "interactions": 0,
                "url": "",
            }
        if name and not row["name"]:
            row["name"] = name
        if email and not row["email"]:
            row["email"] = email
        if user_id:
            self.by_uid[user_id] = key
        return key

    def seen(self, key: str, first: str, last: str) -> None:
        row = self.rows[key]
        row["interactions"] += 1
        if not row["first_seen"] or first < row["first_seen"]:
            row["first_seen"] = first
        if not row["last_seen"] or last > row["last_seen"]:
            row["last_seen"] = last


def _chat_rows(chat: dict, msgs: list[dict], me: dict, people: People, tz, cap: int) -> list[dict]:
    members = {}  # key -> person, the other members of this chat
    for m in chat.get("members") or []:
        uid, email, name = m.get("userId", ""), m.get("email", ""), m.get("displayName", "")
        if _is_self(uid, email, me) or not (uid or email or name):
            continue
        members[people.add(uid, name, email)] = None
    other_members = [people.rows[k] for k in members]

    days: dict[str, list[tuple[datetime, dict]]] = {}
    for msg in msgs:
        if msg.get("deleted") or msg.get("type") not in ("message", ""):
            continue
        when = _ts(msg.get("created"))
        if when is None:
            continue
        days.setdefault(when.astimezone(tz).date().isoformat(), []).append((when, msg))

    rows = []
    for _day, items in sorted(days.items()):
        items.sort(key=lambda x: x[0])
        mine = False
        writers: list[str] = []
        lines = []
        for when, msg in items:
            uid = msg.get("from_id", "")
            if msg.get("from_kind") == "user" and _is_self(uid, "", me):
                mine = True
                who = me.get("displayName") or "me"
            else:
                who = msg.get("from_name") or "?"
                if msg.get("from_kind") == "user" and (uid or who != "?"):
                    k = people.add(uid, msg.get("from_name", ""), "")
                    if k not in writers:
                        writers.append(k)
            lines.append(f"{when.astimezone(tz):%H:%M} {who}: {msg.get('text', '')}".rstrip())
        if chat.get("chatType") == "oneOnOne":
            keys = list(dict.fromkeys(list(members) + writers))
        else:
            keys = writers or list(members)[:GROUP_FALLBACK_MAX]
        first, last = _iso(items[0][0]), _iso(items[-1][0])
        for k in keys:
            people.seen(k, first, last)
        text = "\n".join(lines)
        if len(text) > cap:
            cut = text[:cap].rsplit("\n", 1)[0]
            rest = len(lines) - cut.count("\n") - 1
            text = f"{cut}\n[... {rest} more messages]"
        rows.append(
            {
                "source": tg.SOURCE,
                "ts": first,
                "kind": "message",
                "title": _title(chat, other_members),
                "text": text,
                "participants": tg.MULTI_SEP.join(_label(people.rows[k]) for k in keys),
                "owner_role": "author" if mine else "attendee",
                "due": "",
                "url": chat.get("webUrl", ""),
                "status": "done",
            }
        )
    return rows


def build_rows(labels: list[str] | None = None) -> tuple[list[dict], list[dict], dict]:
    tz = local_zone()
    cap = tg.int_cfg("text_max_chars", tg.DEFAULT_TEXT_MAX_CHARS)
    people = People()
    interactions: list[dict] = []
    stats = {"labels": 0, "chats": 0, "messages": 0}
    for label in labels if labels is not None else tg.labels_on_disk():
        raw = tg.raw_dir(label)
        me = tg.read_json(raw / "me.json", {}) or {}
        if not me:
            continue
        stats["labels"] += 1
        for chat in tg.read_json(raw / "chats.json", []) or []:
            if not isinstance(chat, dict) or not chat.get("id"):
                continue
            stored = tg.read_json(tg.messages_dir(label) / f"{tg.chat_key(chat['id'])}.json", {})
            msgs = list(((stored or {}).get("messages") or {}).values())
            stats["chats"] += 1
            stats["messages"] += len(msgs)
            interactions.extend(_chat_rows(chat, msgs, me, people, tz, cap))
    contacts = sorted(people.rows.values(), key=lambda r: (r["email"] or "~", r["name"]))
    interactions.sort(key=lambda r: (r["ts"], r["title"]))
    stats["contacts"] = len(contacts)
    stats["chat_days"] = len(interactions)
    return contacts, interactions, stats


def write_outputs(contacts: list[dict], interactions: list[dict]) -> None:
    import pandas as pd

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
        description="Turn the downloaded Teams chats into plugin-contacts.parquet and "
        "plugin-interactions.parquet (generic intake contract)."
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    parse_args(argv)
    if not tg.labels_on_disk():
        print(
            f"teams: nothing downloaded yet in {tg.plugin_root() / 'raw'}; run: uv run python "
            "tools/teams/tm-l0-download.py",
            file=sys.stderr,
        )
        return 1
    contacts, interactions, stats = build_rows()
    write_outputs(contacts, interactions)
    print(
        f"Teams L1: {stats['chats']} chats, {stats['messages']} messages -> "
        f"{stats['chat_days']} chat-days, {stats['contacts']} contacts"
    )
    return 0


if __name__ == "__main__":
    parse_args()  # --help and bad flags answer before the pipeline step starts
    if not tg.labels_on_disk():
        sys.exit(main([]))  # one clear line, nothing recorded as a pipeline failure
    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l1-teams-enrich", source=tg.SOURCE, stage="l1", mark_run=False)
    def _run():
        return main([])

    sys.exit(_run())
