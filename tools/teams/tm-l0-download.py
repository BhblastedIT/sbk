#!/usr/bin/env python3
"""Microsoft Teams L0: download your own 1:1 and group chats and their messages.

Reads, with the per-user scope Chat.Read (your own account) and the sign-in of tm-l0-auth.py:
- GET /me                                         who you are (to leave you out later)
- GET /me/chats?$expand=members                   your chats and their members
- GET /chats/{id}/members                         only when the expanded list hit 25
- GET /chats/{id}/messages?$orderby=lastModifiedDateTime desc
      &$filter=lastModifiedDateTime gt <last run>  new and changed messages of each chat

Writes under <data root>/teams/raw/<label>/:
  me.json, chats.json, messages/<chat key>.json (one file per chat, messages by id),
  state.json (per-chat high-water mark), download-summary.json

Incremental: each chat is re-read from its newest lastModifiedDateTime seen, minus
teams.overlap_minutes. A changed message replaces the stored one; a deleted message keeps
its row, flagged, without text. Meeting chats are left out unless asked for.

Not read (admin consent or application permissions only): channel messages, meeting
transcripts. Setup: docs/CONNECTING.md#teams.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tm_graph as tg  # noqa: E402

import sbk_config  # noqa: E402

mg = tg.mg
log = logging.getLogger("teams")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your own Microsoft Teams 1:1 and group chats (per-user "
        "Chat.Read, your own account, see docs/CONNECTING.md#teams)."
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--account", default=None, help="label signed in with tm-l0-auth.py")
    g.add_argument("--all", action="store_true", help="every label in teams.accounts")
    ap.add_argument(
        "--since", help="start date YYYY-MM-DD for every chat (ignores the saved state)"
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help=f"ignore the saved state: re-read teams.history_days (default {tg.DEFAULT_HISTORY_DAYS})",
    )
    ap.add_argument(
        "--include-meeting-chats",
        action="store_true",
        help="also read the chats attached to online meetings (left out by default)",
    )
    ap.add_argument("--verbose", action="store_true")
    return ap.parse_args(argv)


# --------------------------------------------------------------------------- shaping


def _ms_slots():
    import ms_slots

    return ms_slots


def graph_time(dt: datetime) -> str:
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def slim_member(m: dict) -> dict:
    return {
        "userId": str(m.get("userId") or ""),
        "displayName": str(m.get("displayName") or ""),
        "email": str(m.get("email") or "").strip().lower(),
        "roles": list(m.get("roles") or []),
    }


def slim_chat(c: dict, members: list[dict]) -> dict:
    return {
        "id": c.get("id") or "",
        "chatType": c.get("chatType") or "",
        "topic": c.get("topic") or "",
        "createdDateTime": c.get("createdDateTime") or "",
        "lastUpdatedDateTime": c.get("lastUpdatedDateTime") or "",
        "webUrl": c.get("webUrl") or "",
        "tenantId": c.get("tenantId") or "",
        "members": [slim_member(m) for m in members],
    }


def slim_message(m: dict) -> dict:
    frm = m.get("from") or {}
    user = frm.get("user") or {}
    app = frm.get("application") or {}
    deleted = bool(m.get("deletedDateTime"))
    text = ""
    if not deleted:
        text = _ms_slots().body_text(m.get("body"))
        names = [str(a.get("name") or "").strip() for a in (m.get("attachments") or [])]
        names = [n for n in names if n]
        if names:
            text = (text + "\n" if text else "") + " ".join(f"[attachment: {n}]" for n in names)
        text = text[: tg.MESSAGE_TEXT_MAX_CHARS]
    return {
        "id": str(m.get("id") or ""),
        "created": m.get("createdDateTime") or "",
        "modified": m.get("lastModifiedDateTime") or "",
        "deleted": deleted,
        "type": m.get("messageType") or "",
        "from_id": str(user.get("id") or ""),
        "from_name": str(user.get("displayName") or app.get("displayName") or ""),
        "from_kind": "user" if user else ("application" if app else ""),
        "text": text,
    }


# --------------------------------------------------------------------------- steps


def list_chats(graph: tg.PacedGraph, types: tuple[str, ...], stats: dict) -> list[dict]:
    chats = []
    params = {"$expand": "members", "$top": str(tg.page_size())}
    for c in graph.items("/me/chats", params=params):
        stats["chats_listed"] += 1
        if (c.get("chatType") or "") not in types:
            stats["chats_not_included"] += 1
            continue
        members = c.get("members") or []
        if len(members) >= tg.EXPANDED_MEMBERS_CAP:
            try:
                members = list(graph.items(f"/chats/{tg.chat_path(c['id'])}/members"))
                stats["members_refetched"] += 1
            except tg.GraphError as e:
                stats["members_partial"].append(f"{c.get('topic') or c['id']}: HTTP {e.status}")
        chats.append(slim_chat(c, members))
    return chats


def read_chat_messages(
    graph: tg.PacedGraph, label: str, chat: dict, since: datetime, state: dict, stats: dict
) -> None:
    cid = chat["id"]
    key = tg.chat_key(cid)
    path = tg.messages_dir(label) / f"{key}.json"
    stored = tg.read_json(path, {}) or {}
    messages: dict = dict(stored.get("messages") or {})
    params = {
        "$top": str(tg.page_size()),
        "$orderby": "lastModifiedDateTime desc",
        "$filter": f"lastModifiedDateTime gt {graph_time(since)}",
    }
    newest = (state["chats"].get(cid) or {}).get("hwm", "")
    changed = 0
    for m in graph.items(f"/chats/{tg.chat_path(cid)}/messages", params=params):
        row = slim_message(m)
        if not row["id"]:
            continue
        messages[row["id"]] = row
        changed += 1
        stats["messages_deleted"] += row["deleted"]
        mod = parse_time(row["modified"])
        top = parse_time(newest)
        if mod and (top is None or mod > top):
            newest = row["modified"]
    # Data first, then the state that points past it: a crash in between only re-reads.
    if changed or not path.exists():
        tg.write_json(path, {"chat_id": cid, "messages": messages})
    state["chats"][cid] = {"hwm": newest, "key": key}
    stats["messages_new_or_changed"] += changed
    stats["chats_read"] += 1


def start_for(chat_id: str, state: dict, args, now: datetime) -> datetime:
    if args.since:
        since = datetime.fromisoformat(args.since)
        # A bare date or time is UTC; one with its own offset keeps it (not overwritten).
        return since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
    hwm = parse_time((state["chats"].get(chat_id) or {}).get("hwm"))
    if hwm and not args.full:
        return hwm - timedelta(minutes=tg.int_cfg("overlap_minutes", tg.DEFAULT_OVERLAP_MINUTES))
    return now - timedelta(days=tg.int_cfg("history_days", tg.DEFAULT_HISTORY_DAYS))


def run_one(label: str, args, http=None, sleep=None, now=None, clock=None) -> dict:
    label = tg.check_label(label)
    http = http or mg.Http()
    now = now or datetime.now(UTC)
    graph = tg.PacedGraph(
        tg.TeamsTokenProvider(label, http), http, sleep=sleep or time.sleep, clock=clock
    )
    started = datetime.now(UTC)
    me = tg.whoami(graph)
    tg.write_json(tg.raw_dir(label) / "me.json", me)
    state = tg.load_state(label)
    types = tg.chat_types(args.include_meeting_chats)
    stats = {
        "source": tg.SOURCE,
        "label": label,
        "chat_types": list(types),
        "chats_listed": 0,
        "chats_not_included": 0,
        "chats_read": 0,
        "chats_skipped": [],
        "members_refetched": 0,
        "members_partial": [],
        "messages_new_or_changed": 0,
        "messages_deleted": 0,
        "errors": [],
    }
    chats = list_chats(graph, types, stats)
    # Keep chats you left (no longer listed): their messages stay on disk and in L1.
    old = {c["id"]: c for c in tg.read_json(tg.raw_dir(label) / "chats.json", []) or []}
    old.update({c["id"]: c for c in chats})
    tg.write_json(tg.raw_dir(label) / "chats.json", list(old.values()))
    for chat in chats:
        try:
            since = start_for(chat["id"], state, args, now)
            read_chat_messages(graph, label, chat, since, state, stats)
        except tg.GraphError as e:
            name = chat["topic"] or chat["chatType"] or "chat"
            if e.status in (403, 404):
                stats["chats_skipped"].append(f"{name}: HTTP {e.status} {e.code}")
            else:
                stats["errors"].append(f"{name}: HTTP {e.status} {e.code}")
        except mg.DeltaReset as e:
            stats["errors"].append(f"{chat['topic'] or chat['chatType']}: {e}")
        tg.write_json(tg.state_path(label), state)  # after each chat: a stop loses one chat
    state["last_run"] = now.isoformat(timespec="seconds")
    tg.write_json(tg.state_path(label), state)
    stats["chats_skipped"] = stats["chats_skipped"][:50]
    stats["errors"] = stats["errors"][:50]
    stats.update(
        requests=graph.requests,
        throttled=graph.throttled,
        started=started.isoformat(timespec="seconds"),
        finished=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    tg.write_json(tg.summary_path(label), stats)
    return stats


def _line(s: dict) -> str:
    bits = [
        f"teams/{s['label']}: {s['chats_read']} chats read "
        f"({s['chats_not_included']} of other types left out), "
        f"{s['messages_new_or_changed']} new or changed messages"
    ]
    if s["chats_skipped"]:
        bits.append(f"skipped: {'; '.join(s['chats_skipped'][:5])}")
    if s["errors"]:
        bits.append(f"errors: {'; '.join(s['errors'][:5])}")
    return " | ".join(bits)


def main(argv=None, http=None, sleep=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )
    if args.since:
        try:
            datetime.fromisoformat(args.since)
        except ValueError:
            raise tg.SetupError(f"teams: --since {args.since!r} is not a date YYYY-MM-DD") from None
    if args.all:
        labels = [str(x) for x in (sbk_config.user_cfg("teams.accounts", []) or [])]
        if not labels:
            raise tg.SetupError("teams: --all needs teams.accounts in sbk.config.json")
    else:
        labels = [args.account or tg.default_label()]
    failed = 0
    for label in labels:
        if not args.all:
            s = run_one(label, args, http=http, sleep=sleep)
        else:
            # With --all one account whose sign-in expired, or whose organization refuses the
            # chats (a Graph error on /me or /me/chats), must not stop the others.
            try:
                s = run_one(label, args, http=http, sleep=sleep)
            except (tg.SetupError, tg.TokenError, mg.SetupError, mg.TokenError, mg.GraphError) as e:
                # one line per failed account, naming it (a Graph error does not)
                print(f"teams/{label}: {tg.one_line(e).removeprefix('teams: ')}", file=sys.stderr)
                failed += 1
                continue
        print(_line(s))
        failed += bool(s["errors"])
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (tg.SetupError, tg.TokenError, mg.SetupError, mg.TokenError, mg.GraphError) as e:
        print(tg.one_line(e), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("teams: interrupted; chats finished so far are saved", file=sys.stderr)
        sys.exit(130)
