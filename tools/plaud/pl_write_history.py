#!/usr/bin/env python3
"""History of the speaker names SBK wrote into Plaud transcripts and of the voices it enrolled, one JSON line per
write in <data root>/plaud/write_history.jsonl, so a rename can be looked up and reverted.

Usage: uv run python tools/plaud/pl_write_history.py [show]
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DIR = Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data") / "plaud"
HISTORY_PATH = _DIR / "write_history.jsonl"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_write(
    file_id: str,
    ops: dict[str, dict[str, str]],
    sources: list[str],
    *,
    note_title: str | None = None,
    ts: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    ""


    entry = {
        "ts": ts or _now_iso(),
        "kind": "rename",
        "file_id": file_id,
        "note_title": note_title,
        "sources": sources,
        "ops": ops,
    }
    _append(entry, path)
    return entry


def record_enroll(
    file_id: str,
    enrolled: list[dict[str, Any]],
    *,
    ts: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    ""
    entry = {
        "ts": ts or _now_iso(),
        "kind": "enroll",
        "file_id": file_id,
        "enrolled": enrolled,
    }
    _append(entry, path)
    return entry


def revert_rename_ops(entry: dict[str, Any]) -> dict[str, str]:
    ""
    if entry.get("kind") != "rename":
        return {}
    return {sid: op["old"] for sid, op in entry.get("ops", {}).items() if "old" in op}


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or HISTORY_PATH
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def last_write_for(file_id: str, path: Path | None = None) -> dict[str, Any] | None:
    ""
    hits = [
        e for e in load_history(path) if e.get("kind") == "rename" and e.get("file_id") == file_id
    ]
    return hits[-1] if hits else None


def _append(entry: dict[str, Any], path: Path | None = None) -> None:
    p = path or HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    import argparse

    _ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ap.add_argument("command", nargs="?", choices=["show"], help="show: print every entry")
    if _ap.parse_args().command == "show":
        for e in load_history():
            if e.get("kind") == "rename":
                ops = ", ".join(f"{k}:{v['old']}->{v['new']}" for k, v in e["ops"].items())
                print(f"{e['ts']} {e['file_id'][:12]} [{'+'.join(e['sources'])}] {ops}")
            else:
                print(f"{e['ts']} {e['file_id'][:12]} ENROLL {e.get('enrolled')}")
    else:
        print(f"Write history: {HISTORY_PATH}")
        print(f"Entries: {len(load_history())}")
