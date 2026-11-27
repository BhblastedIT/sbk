#!/usr/bin/env python3
"""Extracts the conversational text of the Claude Code sessions of this repo (~/.claude/projects/<repo path>), block
by block following manual-ingestion/extraction-plan.json, into manual-ingestion/session-text/ for a later fact
extraction.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Claude Code encodes a project's path into its sessions folder name by
# replacing every "/" with "-". Derive it from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = Path.home() / ".claude/projects" / str(_REPO_ROOT).replace("/", "-")
PLAN_FILE = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "manual-ingestion"
    / "extraction-plan.json"
)
OUTPUT_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "manual-ingestion"
    / "session-text"
)


def load_plan() -> dict:
    ""
    if not PLAN_FILE.exists():
        log.error("Plan file not found: %s", PLAN_FILE)
        log.error("Run the block planning script first.")
        sys.exit(1)
    return json.loads(PLAN_FILE.read_text())


def _clean_text(text: str) -> str:
    ""

    text = re.sub(r"<[a-z_-]+>.*?</[a-z_-]+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[a-z_-]+/>", "", text)


    text = re.sub(r"```[\s\S]{200,}?```", "[code block removed]", text)


    text = re.sub(r"/Users/[^/\s]+/[^\s]+", "[path]", text)


    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_session_text(jsonl_path: Path) -> str:
    ""
    lines = []
    msg_count = 0

    with open(jsonl_path) as f:
        for raw_line in f:
            d = json.loads(raw_line)
            msg_type = d.get("type", "")


            if msg_type not in ("user", "assistant"):
                continue


            if d.get("isMeta"):
                continue

            msg = d.get("message", {})
            content = msg.get("content", "")


            text = ""
            if isinstance(content, str):

                if "<command-" in content:
                    continue

                if content.startswith("<system-reminder>"):
                    continue
                text = content
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t.strip():
                            text_parts.append(t)
                text = "\n".join(text_parts)

            if not text.strip():
                continue


            text = _clean_text(text)
            if not text or len(text) < 10:
                continue

            role = "USER" if msg_type == "user" else "CLAUDE"
            timestamp = d.get("timestamp", "")[:19]
            lines.append(f"[{timestamp}] {role}:\n{text}\n")
            msg_count += 1

    return "\n".join(lines), msg_count


def extract_block(block_num: int) -> Path:
    ""
    plan = load_plan()
    blocks = plan.get("blocks", [])

    block = None
    for b in blocks:
        if b["block"] == block_num:
            block = b
            break

    if not block:
        log.error("Block %d not found (available: 1-%d)", block_num, len(blocks))
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"block-{block_num:02d}.txt"

    log.info(
        "Block %d: %d sessions, ~%d KB text, %s",
        block_num,
        block["session_count"],
        block["text_kb"],
        block["date_range"],
    )

    all_text = []
    total_msgs = 0

    all_text.append(f"# BLOCK {block_num} — {block['date_range']}")
    all_text.append(f"# {block['session_count']} sessions, ~{block['text_kb']} KB text")
    all_text.append("")

    for session_file in block["sessions"]:
        jsonl_path = SESSIONS_DIR / session_file
        if not jsonl_path.exists():
            log.warning("  Session not found: %s", session_file)
            continue

        text, msg_count = extract_session_text(jsonl_path)
        if msg_count == 0:
            continue

        all_text.append(f"\n{'=' * 80}")
        all_text.append(f"SESSION: {session_file}")
        all_text.append(f"{'=' * 80}\n")
        all_text.append(text)
        total_msgs += msg_count

    output_text = "\n".join(all_text)
    output_path.write_text(output_text)

    output_kb = len(output_text) / 1024
    log.info("  Output: %s (%.0f KB, %d messages)", output_path.name, output_kb, total_msgs)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Extract conversational text from session transcripts"
    )
    parser.add_argument("--block", type=int, help="Extract a specific block number")
    parser.add_argument("--session", help="Extract a single session JSONL file")
    parser.add_argument("--list", action="store_true", help="List available blocks")
    parser.add_argument("--all", action="store_true", help="Extract all blocks")
    args = parser.parse_args()

    if args.list:
        plan = load_plan()
        blocks = plan.get("blocks", [])
        print(f"\n{len(blocks)} blocks, {plan.get('total_sessions', '?')} sessions total\n")
        print(f"{'BLK':>3} | {'SESSIONS':>8} | {'TEXT KB':>7} | PERIOD")
        print("-" * 60)
        for b in blocks:
            done = "✓" if (OUTPUT_DIR / f"block-{b['block']:02d}.txt").exists() else " "
            print(
                f" {done}{b['block']:2d} | {b['session_count']:8d} | {b['text_kb']:6d}K | {b['date_range']}"
            )
        print()
        return

    if args.session:
        path = Path(args.session)
        if not path.exists():
            path = SESSIONS_DIR / args.session
        if not path.exists():
            log.error("Session file not found: %s", args.session)
            sys.exit(1)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        text, count = extract_session_text(path)
        out = OUTPUT_DIR / f"session-{path.stem[:8]}.txt"
        out.write_text(text)
        log.info("Extracted %d messages to %s", count, out)
        return

    if args.block:
        extract_block(args.block)
        return

    if args.all:
        plan = load_plan()
        for b in plan.get("blocks", []):
            extract_block(b["block"])
        return

    parser.print_help()


if __name__ == "__main__":
    main()
