#!/usr/bin/env python3
"""AI history, L0: what YOU wrote in ChatGPT, Claude.ai and Manus, from their exports.

Reads   the export you downloaded: a .zip (read in place, never extracted), a
        .json file, or a folder
Writes  $SBK_DATA_ROOT/ai-history/messages.jsonl (default ~/.sbk-data)

Nothing leaves your machine and nothing is sent to a model. Only YOUR messages
are kept; the assistant's answers, system prompts, custom instructions, hidden
messages and attached files are left out. Secrets are redacted (ai_redact.py).

Formats
  chatgpt    ChatGPT > Settings > Data controls > Export data. The zip holds
             conversations.json (one or more conversations*.json files): a list
             of conversations, each a "mapping" of message nodes. Kept: nodes
             whose author role is "user" (every edited version too), text parts
             and voice transcriptions. Source "chatgpt".
  claude-ai  Claude.ai > Settings > Privacy > Export data. The zip holds
             conversations.json: a list of conversations with "chat_messages".
             Kept: messages whose sender is "human"; attachments are left out.
             Source "claude-ai".
  manus      Manus does not document a readable export format: its Data Backup
             Tool makes encrypted archives meant for restoring the account, and
             the help center mentions a "plaintext export" without describing its
             files (help.manus.im, "How to Back Up Your Data", checked 2026-11-25).
             So a Manus import is a folder of .md / .txt / .json files you saved
             yourself (or the plaintext export, if it is such files), read as
             "generic" with source "manus".
  generic    A folder (or zip) of .md / .txt / .json files from any AI tool.
             .json: lists of messages with a role ("role", "sender", "author",
             "from") and a text ("text", "content", "message", "body"); only the
             roles user / human / you / me are kept. .md / .txt: lines that start
             a turn ("User:", "**You:**", "## Human" ...) split the file; only
             your turns are kept. A file with no such lines is skipped unless you
             pass --whole-file-is-mine. Source = --source (default "generic").

With --format auto (default) a JSON file is recognised as chatgpt or claude-ai
by its structure; anything else is counted as "unrecognised" and skipped, with a
hint to pass --format manus or --format generic.

Writing: a run replaces the lines of each source it imported (an export is a
full snapshot). With --add, or with --since, it only adds (duplicates skipped),
so two accounts of the same tool can be imported one after the other.

Examples:
  python tools/ai-history/ai-l0-import-export.py ~/Downloads/chatgpt-export.zip --dry-run
  python tools/ai-history/ai-l0-import-export.py ~/Downloads/claude-export.zip
  python tools/ai-history/ai-l0-import-export.py ~/Documents/manus-tasks --format manus
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_common import (
    iso_utc,
    make_record,
    output_path,
    parse_since,
    print_counts,
    stable_id,
    write_messages,
)
from ai_redact import redact

TEXT_SUFFIXES = (".json", ".md", ".markdown", ".txt")
USER_ROLES = {"user", "human", "you", "me"}
# Other files of the ChatGPT / Claude.ai export zips: not conversations, skipped silently.
SIDE_FILES = {
    "projects.json",
    "users.json",
    "user.json",
    "memories.json",
    "message_feedback.json",
    "shared_conversations.json",
    "user_settings.json",
    "model_comparisons.json",
}
_ROLE_WORDS = (
    r"user|you|me|human|assistant|ai|manus|chatgpt|gpt|claude|gemini|bot|agent|model|system"
)
_RE_HEADING_TURN = re.compile(
    rf"^\s{{0,3}}#{{1,6}}\s+(?:\*\*|__)?(?P<role>{_ROLE_WORDS})(?:\*\*|__)?\s*:?\s*$", re.IGNORECASE
)
_RE_COLON_TURN = re.compile(
    rf"^\s{{0,3}}(?:\*\*|__)?(?P<role>{_ROLE_WORDS})(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s?(?P<rest>.*)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- reading inputs
def iter_documents(path: Path) -> Iterator[tuple[str, bytes]]:
    """(name, content) of every .json/.md/.txt file in a zip, a folder or a single file."""
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                name = info.filename
                if info.is_dir() or "__MACOSX" in name or Path(name).name.startswith("."):
                    continue
                if name.lower().endswith(TEXT_SUFFIXES):
                    yield f"{path.name}:{name}", zf.read(info)
    elif path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES and not f.name.startswith("."):
                yield str(f.relative_to(path)), f.read_bytes()
    elif path.is_file():
        yield path.name, path.read_bytes()
    else:
        raise SystemExit(f"Not found: {path}")


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace")


def detect(obj) -> str | None:
    convs = obj.get("conversations") if isinstance(obj, dict) else obj
    if not isinstance(convs, list):
        return None
    for c in convs[:20]:
        if isinstance(c, dict):
            if isinstance(c.get("mapping"), dict):
                return "chatgpt"
            if isinstance(c.get("chat_messages"), list):
                return "claude-ai"
    return None


# ---------------------------------------------------------------- ChatGPT
def _chatgpt_text(content: dict) -> str:
    parts = content.get("parts") or []
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, dict) and part.get("content_type") == "audio_transcription":
            if isinstance(part.get("text"), str):
                out.append(part["text"])
    if not parts and isinstance(content.get("text"), str):
        out.append(content["text"])
    return "\n\n".join(p for p in out if p.strip())


def parse_chatgpt(obj, stats: Counter) -> Iterator[tuple[str, str, str, str]]:
    """(session_id, project, ts, text) of your messages."""
    convs = obj.get("conversations") if isinstance(obj, dict) else obj
    for conv in convs or []:
        if not isinstance(conv, dict):
            continue
        stats["conversations"] += 1
        sid = str(
            conv.get("conversation_id")
            or conv.get("id")
            or stable_id(json.dumps(conv.get("title")))
        )
        gizmo = str(conv.get("gizmo_id") or "")
        project = gizmo if gizmo.startswith("g-p-") else ""
        nodes = conv.get("mapping")
        if isinstance(nodes, dict):
            messages = [n.get("message") for n in nodes.values() if isinstance(n, dict)]
        else:  # an already flattened export: {"messages": [{"role", "text", ...}]}
            messages = [
                {
                    "author": {"role": m.get("role")},
                    "content": {"parts": [m.get("text") or m.get("content") or ""]},
                    "create_time": m.get("create_time") or m.get("timestamp"),
                }
                for m in conv.get("messages") or []
                if isinstance(m, dict)
            ]
        seen: set[str] = set()
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            stats["messages_seen"] += 1
            role = ((msg.get("author") or {}).get("role") or "").lower()
            if role != "user":
                stats[f"dropped:role_{role or 'none'}"] += 1
                continue
            content = msg.get("content") or {}
            meta = msg.get("metadata") or {}
            ctype = content.get("content_type", "text")
            if ctype == "user_editable_context" or meta.get("is_user_system_message"):
                stats["dropped:custom_instructions"] += 1
                continue
            if meta.get("is_visually_hidden_from_conversation"):
                stats["dropped:hidden"] += 1
                continue
            if ctype not in ("text", "multimodal_text"):
                stats[f"dropped:content_{ctype}"] += 1
                continue
            text = _chatgpt_text(content).strip()
            if not text:
                stats["dropped:empty"] += 1
                continue
            if text in seen:
                stats["dropped:duplicate"] += 1
                continue
            seen.add(text)
            yield sid, project, iso_utc(msg.get("create_time") or conv.get("create_time")), text


# ---------------------------------------------------------------- Claude.ai
def parse_claude_ai(
    obj, stats: Counter, project_names: dict[str, str]
) -> Iterator[tuple[str, str, str, str]]:
    convs = obj.get("conversations") if isinstance(obj, dict) else obj
    for conv in convs or []:
        if not isinstance(conv, dict):
            continue
        stats["conversations"] += 1
        sid = str(conv.get("uuid") or conv.get("id") or stable_id(json.dumps(conv.get("name"))))
        proj = conv.get("project")
        proj_uuid = conv.get("project_uuid") or (proj.get("uuid") if isinstance(proj, dict) else "")
        project = (
            (proj.get("name") if isinstance(proj, dict) else "")
            or project_names.get(proj_uuid or "", "")
            or ""
        )
        seen: set[str] = set()
        for msg in conv.get("chat_messages") or []:
            if not isinstance(msg, dict):
                continue
            stats["messages_seen"] += 1
            sender = (msg.get("sender") or "").lower()
            if sender != "human":
                stats[f"dropped:sender_{sender or 'none'}"] += 1
                continue
            parts = [
                p.get("text")
                for p in msg.get("content") or []
                if isinstance(p, dict)
                and p.get("type") == "text"
                and isinstance(p.get("text"), str)
            ]
            text = ("\n\n".join(parts) if parts else (msg.get("text") or "")).strip()
            if not text:
                stats["dropped:empty"] += 1
                continue
            if text in seen:
                stats["dropped:duplicate"] += 1
                continue
            seen.add(text)
            yield sid, project, iso_utc(msg.get("created_at") or conv.get("created_at")), text


def claude_project_names(obj) -> dict[str, str]:
    """projects.json of a Claude.ai export: uuid -> name."""
    out: dict[str, str] = {}
    if isinstance(obj, list):
        for p in obj:
            if isinstance(p, dict) and p.get("uuid") and isinstance(p.get("name"), str):
                out[str(p["uuid"])] = p["name"]
    return out


# ---------------------------------------------------------------- generic / Manus
def _generic_role(m: dict) -> str:
    for key in ("role", "sender", "author", "from", "speaker"):
        v = m.get(key)
        if isinstance(v, dict):
            v = v.get("role") or v.get("name")
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return ""


def _generic_text(m: dict) -> str:
    for key in ("text", "content", "message", "body", "prompt"):
        v = m.get(key)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts = [
                p if isinstance(p, str) else p.get("text") for p in v if isinstance(p, (str, dict))
            ]
            return "\n\n".join(p for p in parts if isinstance(p, str))
        if isinstance(v, dict) and isinstance(v.get("parts"), list):
            return "\n\n".join(p for p in v["parts"] if isinstance(p, str))
    return ""


def _generic_ts(m: dict) -> str:
    for key in ("timestamp", "created_at", "create_time", "time", "date", "ts"):
        if m.get(key):
            return iso_utc(m[key])
    return ""


def _message_lists(obj, depth: int = 0) -> Iterator[tuple[str, list]]:
    """(conversation id, list of message dicts) found in a JSON document."""
    if depth > 3:
        return
    if isinstance(obj, list) and obj and all(isinstance(m, dict) for m in obj):
        if any(_generic_role(m) for m in obj):
            yield "", obj
            return
        for conv in obj:
            yield from _message_lists(conv, depth + 1)
    elif isinstance(obj, dict):
        cid = str(
            obj.get("id")
            or obj.get("uuid")
            or obj.get("task_id")
            or obj.get("conversation_id")
            or ""
        )
        for key in ("messages", "chat_messages", "conversation", "events", "turns", "history"):
            v = obj.get(key)
            if isinstance(v, list):
                for sub_id, msgs in _message_lists(v, depth + 1):
                    yield sub_id or cid, msgs


def parse_generic_json(name: str, obj, stats: Counter) -> Iterator[tuple[str, str, str, str]]:
    found = False
    for cid, msgs in _message_lists(obj):
        found = True
        stats["conversations"] += 1
        sid = cid or stable_id(name)
        for m in msgs:
            stats["messages_seen"] += 1
            role = _generic_role(m)
            if role not in USER_ROLES:
                stats[f"dropped:role_{role or 'none'}"] += 1
                continue
            text = _generic_text(m).strip()
            if not text:
                stats["dropped:empty"] += 1
                continue
            yield sid, "", _generic_ts(m), text
    if not found:
        stats["files_without_messages"] += 1


def parse_generic_text(
    name: str, body: str, stats: Counter, whole_file: bool
) -> Iterator[tuple[str, str, str, str]]:
    sid = stable_id(name)
    turns: list[tuple[str, list[str]]] = []
    for line in body.splitlines():
        m = _RE_HEADING_TURN.match(line)
        if m:
            turns.append((m.group("role").lower(), []))
            continue
        m = _RE_COLON_TURN.match(line)
        if m:
            turns.append((m.group("role").lower(), [m.group("rest")] if m.group("rest") else []))
            continue
        if turns:
            turns[-1][1].append(line)
    if not turns:
        if whole_file and body.strip():
            stats["conversations"] += 1
            stats["messages_seen"] += 1
            yield sid, "", "", body.strip()
        else:
            stats["files_without_role_markers"] += 1
        return
    stats["conversations"] += 1
    for role, lines in turns:
        stats["messages_seen"] += 1
        if role not in USER_ROLES:
            stats[f"dropped:role_{role}"] += 1
            continue
        text = "\n".join(lines).strip()
        if not text:
            stats["dropped:empty"] += 1
            continue
        yield sid, "", "", text


# ---------------------------------------------------------------- run
def run(args: argparse.Namespace) -> int:
    since = parse_since(args.since)
    fmt = args.format
    generic_source = "manus" if fmt == "manus" else (args.source or "generic")
    per_source: dict[str, Counter] = defaultdict(Counter)
    redactions: Counter = Counter()
    unrecognised = 0
    kept: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for raw_path in args.paths:
        path = Path(raw_path).expanduser()
        docs = list(iter_documents(path))
        project_names: dict[str, str] = {}
        for name, raw in docs:  # Claude.ai project names first, if the export has them
            if Path(name.split(":")[-1]).name == "projects.json":
                try:
                    project_names.update(claude_project_names(json.loads(_decode(raw))))
                except json.JSONDecodeError:
                    pass
        for name, raw in docs:
            base = Path(name.split(":")[-1]).name
            suffix = Path(base).suffix.lower()
            body = _decode(raw)
            rows: Iterator[tuple[str, str, str, str]]
            if suffix == ".json":
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError:
                    per_source["(all)"]["files_unreadable"] += 1
                    continue
                kind = detect(obj)
                if kind is None and fmt == "chatgpt" and _has_flat_messages(obj):
                    kind = "chatgpt"
                wanted = (
                    kind == fmt
                    if fmt in ("chatgpt", "claude-ai")
                    else (kind is not None or fmt != "auto")
                )
                if not wanted:
                    if base not in SIDE_FILES:
                        unrecognised += 1
                    continue
                if kind == "chatgpt":
                    source, rows = "chatgpt", parse_chatgpt(obj, per_source["chatgpt"])
                elif kind == "claude-ai":
                    source, rows = (
                        "claude-ai",
                        parse_claude_ai(obj, per_source["claude-ai"], project_names),
                    )
                else:
                    source = generic_source
                    rows = parse_generic_json(name, obj, per_source[source])
            else:
                if fmt not in ("manus", "generic"):
                    if fmt == "auto":
                        unrecognised += 1
                    continue
                source = generic_source
                rows = parse_generic_text(name, body, per_source[source], args.whole_file_is_mine)
            stats = per_source[source]
            stats["files"] += 1
            for sid, project, ts, text in rows:
                if since and (not ts or ts < since):
                    stats["dropped:before_since" if ts else "dropped:no_time_with_since"] += 1
                    continue
                key = (source, sid, ts, text)
                if key in seen:
                    stats["dropped:duplicate"] += 1
                    continue
                seen.add(key)
                text, hits = redact(text, emails=args.redact_emails)
                redactions.update(hits)
                stats["kept"] += 1
                kept.append(make_record(source, sid, project, ts, text))

    for source in sorted(per_source):
        st = per_source[source]
        print(f"Source {source}:")
        for k in ("files", "conversations", "messages_seen", "kept"):
            if k in st:
                print(f"  {k:<16} {st[k]}")
        drops = {k.split(":", 1)[1]: v for k, v in st.items() if k.startswith("dropped:")}
        if drops:
            print_counts("  dropped by reason:", drops, indent="    ")
        for k in ("files_without_role_markers", "files_without_messages", "files_unreadable"):
            if st.get(k):
                print(f"  {k:<16} {st[k]}")
    if unrecognised:
        print(
            f"Files not recognised as a ChatGPT or Claude.ai export: {unrecognised} "
            "(skipped; for Manus or other tools pass --format manus or --format generic)."
        )
    if not per_source:
        print("No conversations found.")
    print_counts("Secrets redacted (rule: count):", dict(redactions))

    if args.stats_json:
        out = {s: dict(c) for s, c in per_source.items()}
        out["_unrecognised_files"] = unrecognised
        out["_redactions"] = dict(redactions)
        out["_kept_total"] = len(kept)
        Path(args.stats_json).write_text(
            json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.dry_run:
        print(
            f"Dry run: nothing written. A real run would write {len(kept)} messages to {output_path()}"
        )
        return 0
    if not kept:
        print("Nothing to write.")
        return 0
    imported = {r["source"] for r in kept}
    add_only = bool(args.add or since)
    result = write_messages(
        kept, owns=lambda r: (not add_only) and r["source"] in imported, replace=True
    )
    print(
        f"Wrote {output_path()}: {result['total']} lines in total; {', '.join(sorted(imported))} "
        f"{'added to' if add_only else 'replaced'} ({result['added']} new), "
        f"existing lines kept: {result['kept_other']}."
    )
    return 0


def _has_flat_messages(obj) -> bool:
    convs = obj.get("conversations") if isinstance(obj, dict) else obj
    return isinstance(convs, list) and any(
        isinstance(c, dict) and isinstance(c.get("messages"), list) for c in convs[:20]
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Import your own messages from ChatGPT, Claude.ai and Manus exports into the AI-history file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Nothing is sent anywhere. See the top of this file for each format.",
    )
    p.add_argument("paths", nargs="+", metavar="PATH", help="export .zip, .json file or folder")
    p.add_argument(
        "--format",
        choices=("auto", "chatgpt", "claude-ai", "manus", "generic"),
        default="auto",
        help="auto recognises ChatGPT and Claude.ai exports; manus and generic read a folder of .md/.txt/.json",
    )
    p.add_argument("--source", help='source name written for --format generic (default "generic")')
    p.add_argument(
        "--whole-file-is-mine",
        action="store_true",
        help="generic/manus: a .md/.txt file with no turn markers is one message of yours",
    )
    p.add_argument("--since", help="only messages from this date on (YYYY-MM-DD or ISO time, UTC)")
    p.add_argument(
        "--add",
        action="store_true",
        help="add to the lines already imported instead of replacing them",
    )
    p.add_argument("--redact-emails", action="store_true", help="also replace email addresses")
    p.add_argument("--dry-run", action="store_true", help="print the counts only, write nothing")
    p.add_argument("--stats-json", metavar="FILE", help="also write the counts (no text) to FILE")
    args = p.parse_args(argv)
    if args.source and args.format != "generic":
        p.error("--source is only used with --format generic")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
