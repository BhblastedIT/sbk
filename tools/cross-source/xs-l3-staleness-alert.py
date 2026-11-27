#!/usr/bin/env python3
"""Daily L3 staleness alert: sources past twice their freshness target and recent failed jobs.

Prints one line, writes <data root>/l3/logs/staleness.alert and shows a macOS notice when something
is wrong (exit 1); removes the alert file when all is well (exit 0). No model call.
"""


















from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
for p in (_TOOLS_DIR, _THIS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

log = logging.getLogger("sbk-l3-staleness")

try:
    from sbk_config import L3_DIR as _L3_DIR
except ImportError:  # pragma: no cover - run outside the repo
    _L3_DIR = Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser() / "l3"

ALERT_FILE = _L3_DIR / "logs" / "staleness.alert"


def _load_health():
    ""
    spec = importlib.util.spec_from_file_location("xs_l3_health", _THIS_DIR / "xs-l3-health.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _notify(msg: str) -> None:
    ""
    try:
        ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_FILE.write_text(f"{datetime.now().isoformat()}\n{msg}\n")
    except Exception as e:
        log.warning("could not write the alert file: %s", e)


    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                "display notification (item 1 of argv) with title (item 2 of argv)",
                "-e",
                "end run",
                "--",
                msg[:200],
                "SBK L3 staleness",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            log.warning(
                "notice not shown, osascript exited %s (%s)",
                r.returncode,
                (r.stderr or "").strip()[:160],
            )
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="SBK L3 staleness alert")
    p.add_argument("--quiet", action="store_true", help="exit code only, no stdout")
    p.add_argument("--ignore", default="", help="sources to ignore, comma-separated (e.g. chatgpt,gdrive)")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)

    ignore = {s.strip() for s in args.ignore.split(",") if s.strip()}

    health = _load_health()
    data = health.gather()


    stale = [
        s["source"]
        for s in data.get("sources", [])
        if s.get("status") == "🔴" and s["source"] not in ignore
    ]

    jobs = data.get("jobs", {})
    failures = jobs.get("recent_failures") or []

    problems = []
    if stale:
        problems.append(f"{len(stale)} sources STALE past 2x their freshness target: {', '.join(stale)}")
    if failures:
        names = sorted({f.get("script", f.get("name", "?")) for f in failures})
        problems.append(f"{len(failures)} recent failed jobs: {', '.join(names)}")

    if problems:
        msg = " | ".join(problems)
        if not args.quiet:
            print(f"[ALERT] {msg}")
        _notify(msg)
        sys.exit(1)
    else:
        if not args.quiet:
            print("[OK] no stale source, no failed job")

        try:
            ALERT_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
