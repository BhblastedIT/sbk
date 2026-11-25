#!/usr/bin/env python3
"""AI history, L0: what YOU typed to Claude Code, from its local session logs.

Reads   $CLAUDE_CONFIG_DIR/projects/**/*.jsonl   (default ~/.claude/projects)
Writes  $SBK_DATA_ROOT/ai-history/messages.jsonl (default ~/.sbk-data), source "claude-code"

Nothing leaves your machine: this script reads local files and writes a local
file. Nothing is sent to a model.

What is kept: the messages you typed at the prompt (user turns, plain string or
text parts). What is dropped, and counted by reason:

  subagent              transcripts of subagents (files under subagents/, records
                        marked isSidechain): their "user" turns are prompts written
                        by another agent, not by you. Files under subagents/ are
                        skipped without being opened.
  tool_result           tool output fed back to the model
  compaction_summary    "This session is being continued ..." summaries
  meta                  records Claude Code marks isMeta (injected context, images,
                        skill bodies, caveats)
  task_notification     background task / agent notifications
  teammate_or_cross_session  messages from teammates or other sessions
  automatic             other prompts not typed by a person (auto-continuation,
                        workflow harness tasks)
  injected              text placed in the session by a tool, a hook, a scheduled
                        prompt or another program. Recent Claude Code versions mark
                        every prompt typed at the keyboard (promptSource "typed" or
                        "queued", origin "human"); in turns written by such a
                        version, a user turn without any mark was not typed by you.
                        Turns from older versions carry no marks: there every
                        remaining user turn is kept.
  sdk                   prompts sent by scripts through the SDK / `claude -p`
                        (kept with --include-sdk)
  suggestion            a suggested prompt you accepted with one key
  command               slash-command and !bash wrappers (<command-name>, <bash-input>,
                        <local-command-stdout> ...)
  interrupted           "[Request interrupted by user]" markers
  empty_after_cleaning  nothing left once system reminders, pasted blocks and image
                        markers are removed
  duplicate             the same message seen again (resumed or forked sessions)
  before_since / project_filter   left out by --since / --project / --exclude-project

Inside a kept message, <system-reminder> blocks, <pasted_content> blocks (text you
pasted, not typed), "[Image #n]" / "[Pasted text #n]" markers are removed, then
secrets are redacted (see ai_redact.py).

Examples:
  python tools/ai-history/ai-l0-claude-code.py --dry-run
  python tools/ai-history/ai-l0-claude-code.py --since 2026-01-01 --exclude-project scratch
  python tools/ai-history/ai-l0-claude-code.py --project my-app --redact-emails
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_common import iso_utc, make_record, output_path, parse_since, print_counts, write_messages
from ai_redact import redact

SOURCE = "claude-code"

# Opening tags of text the harness writes into a user turn (not typed by you).
_COMMAND_PREFIXES = (
    "<command-name",
    "<command-message",
    "<command-args",
    "<local-command-",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
)
_TASK_PREFIXES = ("<task-notification",)
_PEER_PREFIXES = (
    "<teammate-message",
    "<cross-session-message",
    "<peer-message",
    "<channel-message",
)

_RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>[\s\S]*?</system-reminder>")
_RE_PASTED = re.compile(r"<pasted_content\b[^>]*>[\s\S]*?</pasted_content\b[^>]*>")
_RE_PASTED_OPEN = re.compile(r"<pasted_content\b[^>]*>[\s\S]*\Z")  # unclosed: drop to the end
_RE_ARTIFACT_MARK = re.compile(r"<artifact-content-authored-by-others\s*/>")
# "[Image #1]", "[Pasted text #2 +40 lines]", "[Image: source: /path/shot.png]"
_RE_MARKERS = re.compile(r"\[(?:Image|Pasted text)(?: #\d+[^\]\n]{0,200}|: [^\]\n]{0,300})\]")


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")).expanduser()


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out: list[str] = []
    if isinstance(content, list):
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                out.append(part["text"])
    return out


def _has_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(p, dict) and p.get("type") == "tool_result" for p in content
    )


def clean_text(text: str) -> tuple[str, int]:
    """Remove harness blocks from a typed message. Returns (text, pasted blocks removed)."""
    text = _RE_SYSTEM_REMINDER.sub("", text)
    text, n_pasted = _RE_PASTED.subn("", text)
    text, n_open = _RE_PASTED_OPEN.subn("", text)
    text = _RE_ARTIFACT_MARK.sub("", text)
    text = _RE_MARKERS.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), n_pasted + n_open


def classify(rec: dict, include_sdk: bool, marked_session: bool = False) -> tuple[str | None, str]:
    """Return (drop reason or None, raw text). Only called for type == "user".

    marked_session: the session file marks typed prompts (see "injected" above).
    """
    msg = rec.get("message") or {}
    content = msg.get("content")
    if rec.get("isSidechain"):
        return "subagent", ""
    if _has_tool_result(content):
        return "tool_result", ""
    raw = "\n\n".join(_texts(content))
    stripped = raw.lstrip()
    if rec.get("isCompactSummary") or stripped.startswith("This session is being continued"):
        return "compaction_summary", raw
    origin = rec.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind == "task-notification" or stripped.startswith(_TASK_PREFIXES):
        return "task_notification", raw
    if kind in ("peer", "teammate", "cross-session") or stripped.startswith(_PEER_PREFIXES):
        return "teammate_or_cross_session", raw
    if kind not in (None, "human"):
        return "automatic", raw
    if rec.get("isMeta"):
        return "meta", raw
    source = rec.get("promptSource")
    if not include_sdk and (rec.get("entrypoint") == "sdk-cli" or source == "sdk"):
        return "sdk", raw
    if source == "suggestion_accepted":
        return "suggestion", raw
    if source == "system":
        return "automatic", raw
    if stripped.startswith(_COMMAND_PREFIXES):
        return "command", raw
    if stripped.startswith("[Request interrupted"):
        return "interrupted", raw
    if stripped.startswith("[Workflow harness"):
        return "automatic", raw
    if marked_session and kind is None and source is None:
        return "injected", raw
    return None, raw


def _version(rec: dict) -> tuple[int, ...]:
    """Claude Code version of a record as a comparable tuple; unknown sorts last."""
    parts = re.findall(r"\d+", str(rec.get("version") or ""))
    return tuple(int(x) for x in parts[:3]) if parts else (10**6,)


def _is_marked(rec: dict) -> bool:
    """True when the record carries the typed-prompt marks of recent Claude Code versions."""
    return "promptSource" in rec or isinstance(rec.get("origin"), dict)


def _project_of(rec: dict, folder: str) -> str:
    cwd = rec.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return Path(cwd.rstrip("/")).name or cwd
    return folder


def _matches(needles: list[str], rec: dict, folder: str) -> bool:
    hay = " ".join([str(rec.get("cwd") or ""), folder]).lower()
    return any(n.lower() in hay for n in needles)


def run(args: argparse.Namespace) -> int:
    home = claude_home()
    projects = home / "projects"
    if not projects.is_dir():
        print(f"No Claude Code logs found: {projects} does not exist.")
        print(
            "Claude Code keeps them there by default; set CLAUDE_CONFIG_DIR if yours live elsewhere."
        )
        return 1
    since = parse_since(args.since)

    reasons: Counter = Counter()
    redactions: Counter = Counter()
    pasted_removed = 0
    files_read = files_subagent = files_unreadable = 0
    sessions_all: set[str] = set()
    sessions_kept: set[str] = set()
    projects_kept: set[str] = set()
    seen_uuid: set[str] = set()
    seen_text: set[tuple[str, str, str]] = set()
    user_records = 0
    kept: list[dict] = []

    for path in sorted(projects.rglob("*.jsonl")):
        rel = path.relative_to(projects)
        if "subagents" in rel.parts:
            files_subagent += 1
            continue
        folder = rel.parts[0] if len(rel.parts) > 1 else ""
        try:
            fh = path.open(encoding="utf-8", errors="replace")
        except OSError:
            files_unreadable += 1
            continue
        files_read += 1
        file_records: list[dict] = []
        with fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "user":
                    continue
                if _has_tool_result((rec.get("message") or {}).get("content")):
                    # counted, not kept in memory: tool output is most of a session file
                    user_records += 1
                    reasons["tool_result"] += 1
                    sessions_all.add(str(rec.get("sessionId") or path.stem))
                    continue
                file_records.append(rec)
        # the oldest Claude Code version that wrote typed-prompt marks in this file;
        # turns written by older versions (a session resumed after an upgrade) carry none
        marked_from = min((_version(r) for r in file_records if _is_marked(r)), default=None)
        for rec in file_records:
            user_records += 1
            session_id = str(rec.get("sessionId") or path.stem)
            sessions_all.add(session_id)
            marked = marked_from is not None and _version(rec) >= marked_from
            reason, raw = classify(rec, args.include_sdk, marked_session=marked)
            if reason:
                reasons[reason] += 1
                continue
            text, n_pasted = clean_text(raw)
            pasted_removed += n_pasted
            if not text:
                reasons["empty_after_cleaning"] += 1
                continue
            ts = iso_utc(rec.get("timestamp"))
            if since and (not ts or ts < since):
                reasons["before_since"] += 1
                continue
            if args.project and not _matches(args.project, rec, folder):
                reasons["project_filter"] += 1
                continue
            if args.exclude_project and _matches(args.exclude_project, rec, folder):
                reasons["project_filter"] += 1
                continue
            uuid = rec.get("uuid")
            text_key = (session_id, ts, text)
            if (uuid and uuid in seen_uuid) or text_key in seen_text:
                reasons["duplicate"] += 1
                continue
            if uuid:
                seen_uuid.add(uuid)
            seen_text.add(text_key)
            text, hits = redact(text, emails=args.redact_emails)
            redactions.update(hits)
            project = _project_of(rec, folder)
            sessions_kept.add(session_id)
            projects_kept.add(project)
            kept.append(make_record(SOURCE, session_id, project, ts, text))

    dropped = sum(reasons.values())
    print(f"Claude Code logs: {projects}")
    print(f"  session files read        {files_read}")
    print(f"  subagent files skipped    {files_subagent}")
    if files_unreadable:
        print(f"  files unreadable          {files_unreadable}")
    print(f"  sessions seen             {len(sessions_all)}")
    print(f"  sessions with your text   {len(sessions_kept)}")
    print(f"  projects with your text   {len(projects_kept)}")
    print(f"  user records              {user_records}")
    print(f"  kept (typed by you)       {len(kept)}")
    print(f"  dropped                   {dropped}")
    print_counts("Dropped by reason:", dict(reasons))
    print(f"Pasted blocks removed from your messages: {pasted_removed}")
    print_counts("Secrets redacted (rule: count):", dict(redactions))

    stats = {
        "source": SOURCE,
        "session_files_read": files_read,
        "subagent_files_skipped": files_subagent,
        "files_unreadable": files_unreadable,
        "sessions_seen": len(sessions_all),
        "sessions_with_text": len(sessions_kept),
        "projects_with_text": len(projects_kept),
        "user_records": user_records,
        "kept": len(kept),
        "dropped": dropped,
        "dropped_by_reason": dict(reasons),
        "pasted_blocks_removed": pasted_removed,
        "redactions": dict(redactions),
    }
    if args.stats_json:
        Path(args.stats_json).write_text(
            json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if args.dry_run:
        print(
            f"Dry run: nothing written. A real run would write {len(kept)} messages to {output_path()}"
        )
        return 0
    narrowed = bool(since or args.project)
    excluded = [n.lower() for n in (args.exclude_project or [])]

    def owns(r: dict) -> bool:
        """Existing lines this run replaces."""
        if r["source"] != SOURCE:
            return False
        if not narrowed:
            return True  # a full run rebuilds every claude-code line
        # a narrowed run only adds, but removes old lines of projects you now exclude
        return any(n in r["project"].lower() for n in excluded)

    out = write_messages(kept, owns=owns, replace=True)
    action = "added to" if narrowed else "replaced"
    print(
        f"Wrote {output_path()}: {out['total']} lines in total; claude-code lines {action} "
        f"({out['added']} new), existing lines kept: {out['kept_other']}."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Collect the messages you typed to Claude Code (local logs) into the AI-history file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Reads $CLAUDE_CONFIG_DIR/projects (default ~/.claude/projects). Nothing is sent anywhere.",
    )
    p.add_argument("--since", help="only messages from this date on (YYYY-MM-DD or ISO time, UTC)")
    p.add_argument(
        "--project",
        action="append",
        metavar="TEXT",
        help="only sessions whose working folder contains TEXT (repeatable)",
    )
    p.add_argument(
        "--exclude-project",
        action="append",
        metavar="TEXT",
        help="leave out sessions whose working folder contains TEXT (repeatable)",
    )
    p.add_argument("--redact-emails", action="store_true", help="also replace email addresses")
    p.add_argument(
        "--include-sdk",
        action="store_true",
        help="also keep prompts sent through the SDK or `claude -p` (scripts, not typed at the prompt)",
    )
    p.add_argument("--dry-run", action="store_true", help="print the counts only, write nothing")
    p.add_argument("--stats-json", metavar="FILE", help="also write the counts (no text) to FILE")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
