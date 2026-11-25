#!/usr/bin/env python3
""









from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from event_bus import EventBus  # noqa: E402

from sbk_config import CASCADE_RULES  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="SBK Event Bus — Pipeline cascade")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pending", action="store_true", help="List pending events")
    group.add_argument(
        "--process", action="store_true", help="Process pending events (trigger cascades)"
    )
    group.add_argument("--cleanup", action="store_true", help="Remove old events (>24h)")
    group.add_argument("--emit", nargs=2, metavar=("SOURCE", "STAGE"), help="Emit event manually")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually run cascade scripts")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.pending:
        events = EventBus.pending()
        if not events:
            print("No pending events")
            return
        print(f"\n{'=' * 60}")
        print(f"  Pending events: {len(events)}")
        print(f"{'=' * 60}")
        for ev in events:
            cascade = CASCADE_RULES.get((ev["source"], ev["stage"]), "none")
            print(f"  {ev['ts'][:19]}  {ev['source']}/{ev['stage']}  -> {cascade}")
            for k, v in ev.items():
                if k not in ("source", "stage", "ts", "emitted_at", "_file", "processed"):
                    print(f"    {k}: {v}")
        print()

    elif args.process:
        actions = EventBus.process(dry_run=args.dry_run)
        if not actions:
            print("No cascades triggered (events may be in debounce window)")
            return
        print(f"\nCascade actions: {len(actions)}")
        for a in actions:
            print(f"  {a['target']}: {a['events_count']} events, status={a['status']}")

    elif args.cleanup:
        removed = EventBus.cleanup()
        print(f"Removed {removed} old events")

    elif args.emit:
        source, stage = args.emit
        path = EventBus.emit(source, stage, manual=True)
        print(f"Event emitted: {path.name}")


if __name__ == "__main__":
    main()
