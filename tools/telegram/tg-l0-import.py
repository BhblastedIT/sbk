#!/usr/bin/env python3
"""Telegram L0: import the JSON data export of Telegram Desktop from a local folder.

You make the export yourself: Telegram Desktop -> Settings -> Advanced -> Export Telegram
data, tick "Personal chats" and "Private groups" and UNTICK "Only my messages" under Private
groups (ticked by default: groups would hold only your own messages), keep "Contacts list"
for phone numbers, choose the format "Machine-readable JSON", then Export. A single chat can
be exported from the chat's menu -> Export chat history, also as JSON. Telegram writes a
folder with a `result.json` in it (https://core.telegram.org/import-export). Chats you have
left are always exported with your own messages only.

Give the folder (or the result.json, or a folder holding several exports); with no path,
the importer searches <data root>/telegram/exports/. Each chat is merged by message id into
raw/chats/<key>.json, so importing a newer export later adds only what is new, and an export
already imported (same file content) is skipped unless --force. Media files are never
copied, only the kind of media a message had.

Nothing goes to the network and no Telegram account is logged in.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_export as tg  # noqa: E402

USAGE_LINE = (
    "Telegram: no export found; in Telegram Desktop use Settings -> Advanced -> Export Telegram "
    "data (Private groups with 'Only my messages' unticked), format Machine-readable JSON, then "
    "run: uv run python tools/telegram/tg-l0-import.py "
    "<export folder> (or put the folder in {exports})"
)


def _self_from_single_chat(chat: dict) -> str:
    """In a personal chat the chat id is the other person's id: the other user sender is you."""
    if str(chat.get("type") or "") != "personal_chat":
        return ""
    other = f"user{chat.get('id')}"
    senders = {
        str(m.get("from_id") or "")
        for m in chat.get("messages") or []
        if isinstance(m, dict) and str(m.get("from_id") or "").startswith("user")
    }
    mine = senders - {other}
    return next(iter(mine)) if len(mine) == 1 else ""


def import_one(path: Path, *, force: bool, dry_run: bool, state: dict) -> dict:
    """Import one result.json. Returns its per-file stats."""
    stats = {
        "file": str(path),
        "skipped_already_imported": False,
        "chats": 0,
        "left_chats": 0,
        "messages_in_file": 0,
        "messages_new": 0,
        "messages_changed": 0,
        "contacts_in_file": 0,
        "kind": "",
        "chat_types": {},
        "groups_only_your_messages": 0,
    }
    fp = tg.fingerprint(path)
    stats["fingerprint"] = fp[:16]
    if fp in state.get("imported", {}) and not force:
        stats["skipped_already_imported"] = True
        return stats
    data = tg.load_export(path)
    chats = tg.export_chats(data)
    stats["kind"] = "single chat" if isinstance(data.get("messages"), list) else "full export"
    now = datetime.now(UTC).isoformat()

    me = tg.read_json(tg.me_path(), {}) or {}
    info = data.get("personal_information")
    if isinstance(info, dict) and info.get("user_id"):
        me.update(
            {
                "user_id": str(info.get("user_id")),
                "name": tg.full_name(info.get("first_name"), info.get("last_name")),
                "how": "personal_information of the export",
            }
        )
    elif not me.get("user_id") and len(chats) == 1:
        guess = _self_from_single_chat(chats[0][0])
        if guess:
            me.update({"user_id": guess[4:], "how": "inferred from a single personal chat"})

    my_id = f"user{me['user_id']}" if me.get("user_id") else ""
    for chat, left in chats:
        key = tg.chat_key(chat)
        if not key:
            continue
        ctype = str(chat.get("type") or "")
        stats["chat_types"][ctype] = stats["chat_types"].get(ctype, 0) + 1
        stats["chats"] += 1
        stats["left_chats"] += bool(left)
        msgs = [m for m in (tg.slim_message(x) for x in chat.get("messages") or []) if m]
        stats["messages_in_file"] += len(msgs)
        # A group you are still in whose messages are all yours was most likely exported
        # with "Only my messages" ticked (the default for Private groups).
        senders = {str(m.get("from_id")) for m in msgs if m.get("type") == "message"}
        if my_id and ctype in tg.GROUP_TYPES and not left and senders == {my_id}:
            stats["groups_only_your_messages"] += 1
        out = tg.chats_dir() / f"{key}.json"
        old = tg.read_json(out, {}) or {}
        merged, added, changed = tg.merge_messages(old.get("messages") or [], msgs)
        stats["messages_new"] += added
        stats["messages_changed"] += changed
        unchanged = (
            old
            and not added
            and not changed
            and old.get("name") == chat.get("name")
            and bool(old.get("left")) == bool(left)
        )
        if dry_run or unchanged:
            continue
        tg.write_json(
            out,
            {
                "key": key,
                "id": chat.get("id"),
                "name": chat.get("name") or old.get("name") or "",
                "type": ctype,
                "left": bool(left),
                "first_import": old.get("first_import") or now,
                "last_import": now,
                "messages": merged,
            },
        )

    contacts = tg.export_contacts(data)
    stats["contacts_in_file"] = len(contacts)
    if not dry_run:
        if contacts:
            have = tg.read_json(tg.contacts_raw_path(), []) or []
            by_key = {tg.contact_key(c): c for c in have if tg.contact_key(c)}
            for c in contacts:
                k = tg.contact_key(c)
                if k:
                    by_key[k] = {**by_key.get(k, {}), **{a: b for a, b in c.items() if b}}
            tg.write_json(tg.contacts_raw_path(), sorted(by_key.values(), key=tg.contact_key))
        if me:
            tg.write_json(tg.me_path(), me)
        state.setdefault("imported", {})[fp] = {
            "file": path.name,
            "imported_at": now,
            "chats": stats["chats"],
            "messages_new": stats["messages_new"],
        }
    return stats


def run_import(paths: list[Path], *, force: bool = False, dry_run: bool = False) -> dict:
    started = datetime.now(UTC)
    files, html_only = tg.find_exports(paths)
    if not files:
        if html_only:
            raise tg.TelegramError(
                f"{html_only[0]} holds an HTML export only; export again with the format "
                "Machine-readable JSON (or Both)"
            )
        raise tg.TelegramError("no result.json in " + ", ".join(str(p) for p in paths))
    state = tg.read_json(tg.state_path(), {}) or {}
    per_file, errors = [], []
    for f in files:
        try:
            per_file.append(import_one(f, force=force, dry_run=dry_run, state=state))
        except tg.TelegramError as e:
            # A folder search can meet a result.json that is not a Telegram export, or an
            # unfinished one: it is reported and the other exports are still imported.
            errors.append(str(e))
    if not per_file:
        raise tg.TelegramError(errors[0])
    if not dry_run:
        state["last_import"] = datetime.now(UTC).isoformat()
        tg.write_json(tg.state_path(), state)
    summary = {
        "source": tg.SOURCE,
        "route": "desktop-json-export",
        "dry_run": dry_run,
        "files": per_file,
        "files_found": len(files),
        "files_imported": sum(not f["skipped_already_imported"] for f in per_file),
        "files_already_imported": sum(f["skipped_already_imported"] for f in per_file),
        "chats": sum(f["chats"] for f in per_file),
        "messages_new": sum(f["messages_new"] for f in per_file),
        "messages_changed": sum(f["messages_changed"] for f in per_file),
        "contacts_in_files": sum(f["contacts_in_file"] for f in per_file),
        "files_not_read": errors,
        "groups_only_your_messages": sum(f["groups_only_your_messages"] for f in per_file),
        "you": "not checked in a dry run"
        if dry_run
        else (tg.read_json(tg.me_path(), {}) or {}).get("how", "unknown"),
        "complete": True,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if not dry_run:
        tg.write_json(tg.summary_path(), summary)
    return summary


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Import your Telegram Desktop data export (format Machine-readable JSON) "
        "from a local folder. Reads local files only; no Telegram login."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="export folder(s) or result.json file(s); default: <data root>/telegram/exports/",
    )
    ap.add_argument("--force", action="store_true", help="import again an export already imported")
    ap.add_argument(
        "--dry-run", action="store_true", help="read the export(s) and print counts, write nothing"
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    paths = [Path(p) for p in args.paths] or [tg.exports_dir()]
    for p in paths:
        if not p.expanduser().exists() and args.paths:
            print(f"Telegram: no such file or folder: {p}", file=sys.stderr)
            return 1
    try:
        files, html_only = tg.find_exports(paths)
    except OSError as e:
        print(f"Telegram: cannot read {paths[0]}: {e}", file=sys.stderr)
        return 1
    if not files:
        if html_only:
            print(
                f"Telegram: {html_only[0]} holds an HTML export only; export again with the "
                "format Machine-readable JSON (or Both)",
                file=sys.stderr,
            )
        else:
            print(USAGE_LINE.format(exports=tg.exports_dir()), file=sys.stderr)
        return 1

    def _run():
        try:
            return run_import(paths, force=args.force, dry_run=args.dry_run)
        except tg.TelegramError as e:
            print(f"Telegram: {e}", file=sys.stderr)
            raise SystemExit(1) from None

    if args.dry_run:
        runner = _run
    else:
        from pipeline_decorator import pipeline_step

        runner = pipeline_step(name="l0-telegram-import", source=tg.SOURCE, stage="l0")(_run)
    try:
        s = runner()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    print(
        ("Telegram (dry run, nothing written): " if s["dry_run"] else "Telegram: ")
        + f"{s['files_found']} export file(s), {s['files_imported']} read, "
        f"{s['files_already_imported']} already imported; {s['chats']} chats, "
        f"{s['messages_new']} new messages, {s['messages_changed']} changed, "
        f"{s['contacts_in_files']} contacts in the list; you = {s['you']}"
    )
    for err in s["files_not_read"]:
        print(f"Telegram: skipped {err}", file=sys.stderr)
    if s["groups_only_your_messages"]:
        print(
            f"Telegram: {s['groups_only_your_messages']} group(s) hold only your own messages; "
            'export again with "Only my messages" unticked under Private groups',
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
