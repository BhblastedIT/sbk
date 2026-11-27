#!/usr/bin/env python3
"""L1 Pipedrive: turns what pd-l0-download.py saved into the kernel's generic intake.

Writes, under ~/.sbk-data/pipedrive/processed/ (or $SBK_DATA_ROOT/pipedrive/processed/):

  plugin-contacts.parquet       one row per person (name, primary email and phone,
                                organization as company, job title when Pipedrive
                                sends it, link to the person)
  plugin-interactions.parquet   one row per event:
                                  deals       kind record, status open | done (won) | closed (lost),
                                              due = expected close date on your own open deals
                                  activities  kind meeting (meeting, lunch, call) | message (email) |
                                              record (task, deadline, custom types),
                                              status open | done, due = due date when it is yours
                                  notes       kind record, status done

Scope (`pipedrive.scope` or --scope): "mine" (default) keeps the deals you own or
created, the activities you own, created or attend, the notes you wrote, and the
persons you own or who appear in those; "all" keeps everything the download saw.

The columns are the contract in tools/cross-source/plugin_intake.py. No network, no
credential: it only reads the local files.

    uv run python tools/pipedrive/pd-l1-enrich.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tools"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Normalize the Pipedrive download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument(
        "--scope",
        choices=("mine", "all"),
        default=None,
        help="mine = your deals, activities, notes and their persons (default); all = everything downloaded",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("pd-l1")

    import pd_api

    dest = pd_api.pd_dir()
    raw = dest / pd_api.RAW_DIR
    if not (raw / "me.json").exists():
        print(
            f"pipedrive: nothing to enrich in {raw}; run tools/pipedrive/pd-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    scope = a.scope or str(pd_api.setting("scope", "mine") or "mine")
    if scope not in ("mine", "all"):
        scope = "mine"
    e = pd_api.write_frames(dest, scope)
    for k, v in e.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", dest / pd_api.PROCESSED_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
