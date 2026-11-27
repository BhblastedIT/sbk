#!/usr/bin/env python3
"""L1 Atlassian: turns what as-l0-download.py saved into the kernel's generic intake.

Writes, under ~/.sbk-data/atlassian/processed/ (or $SBK_DATA_ROOT/atlassian/processed/):

  plugin-contacts.parquet       one row per person met on your issues and pages
                                (reporter, creator, assignee, watchers, page
                                contributors; you and app accounts are left out)
  plugin-interactions.parquet   kind issue (owner_role assignee | author | other,
                                due from the Jira due date, status open | done)
                                and kind record for Confluence pages

The columns are the contract in tools/cross-source/plugin_intake.py. No network,
no token: it only reads the local files.

    uv run python tools/atlassian/as-l1-enrich.py
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
        description="Normalize the Atlassian download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("as-l1")

    import as_api

    raw = as_api.AS_DIR / as_api.RAW_DIR
    if not (raw / "me.json").exists():
        print(
            f"atlassian: nothing to enrich in {raw}; run tools/atlassian/as-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    e = as_api.write_frames(as_api.AS_DIR)
    for k, v in e.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", as_api.AS_DIR / as_api.PROCESSED_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
