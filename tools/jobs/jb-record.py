#!/usr/bin/env python3
""





























from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jb_model import OUTCOMES, Event, append_event, stamp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="record a job start/end in the jobs ledger")
    ap.add_argument("phase", choices=("start", "end"))
    ap.add_argument("job", help="the job key, e.g. com.sbk.backup")
    ap.add_argument("--outcome", choices=OUTCOMES, help="required on 'end'")
    ap.add_argument("--detail", default="", help="one human sentence, not the raw log")
    ap.add_argument("--expected-at", default=None, help="ISO instant WITH offset, if known")
    a = ap.parse_args()

    if a.phase == "end" and not a.outcome:
        ap.error("'end' needs --outcome: the exit code is not the outcome")
    if a.phase == "start" and a.outcome:
        ap.error("'start' takes no --outcome")

    append_event(
        Event(
            job=a.job,
            phase=a.phase,
            outcome=a.outcome,
            detail=a.detail[:400],
            expected_at=a.expected_at,
        )
    )
    print(f"{stamp()} {a.phase} {a.job}" + (f" -> {a.outcome}" if a.outcome else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
