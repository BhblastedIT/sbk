#!/usr/bin/env python3
""










from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


PROTECTED_SCRIPTS = [
    {"script": "xs-pipeline-run.py", "lock_name": "pipeline-run"},
    {"script": "xs-l3-index.py", "lock_name": "l3-index"},
    {"script": "xs-l3-graph.py", "lock_name": "l3-graph"},
    {"script": "xs-l2-knowledge-extract.py", "lock_name": "knowledge-extract"},
    {"script": "xs-l3-deep-extract.py", "lock_name": "deep-extract"},
    {"script": "xs-l3-extract-relationships.py", "lock_name": "extract-relationships"},
]


def check_source_has_lock(script_name: str) -> bool:
    ""
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        return False
    content = script_path.read_text(encoding="utf-8")
    return "acquire_pid_lock" in content


def check_duplicate_processes(script_name: str) -> int:
    ""
    try:
        result = subprocess.run(
            ["pgrep", "-f", script_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return 0
        pids = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

        own_pid = str(os.getpid())
        pids = [p for p in pids if p != own_pid]
        return len(pids)
    except (subprocess.TimeoutExpired, OSError):
        return 0


def main():
    parser = argparse.ArgumentParser(description="SBK Concurrency Guard Verification")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details")
    args = parser.parse_args()

    problems = 0
    print("SBK Concurrency Guard Check")
    print("=" * 60)
    print(f"{'Script':<40} {'Lock':<8} {'Dupes':<8} {'Status'}")
    print("-" * 60)

    for entry in PROTECTED_SCRIPTS:
        script = entry["script"]
        lock_name = entry["lock_name"]

        has_lock = check_source_has_lock(script)
        dupes = check_duplicate_processes(script)

        lock_str = "OK" if has_lock else "MISSING"
        dupe_str = str(dupes) if dupes > 1 else "OK"
        status = "OK" if (has_lock and dupes <= 1) else "PROBLEM"

        if not has_lock:
            problems += 1
        if dupes > 1:
            problems += 1

        print(f"  {script:<38} {lock_str:<8} {dupe_str:<8} {status}")

        if args.verbose:
            print(f"    lock_name: {lock_name}")

    print("-" * 60)
    print(f"Protected scripts: {len(PROTECTED_SCRIPTS)}")
    print(f"Problems: {problems}")

    if problems:
        print("\nFAILED — concurrency violations found")
        sys.exit(1)
    else:
        print("\nPASSED — all scripts protected, no duplicates")
        sys.exit(0)


if __name__ == "__main__":
    main()
