#!/usr/bin/env python3
"""L1 GitHub: turns what gh-l0-download.py saved into the kernel's generic intake.

Writes, under ~/.sbk-data/github/processed/ (or $SBK_DATA_ROOT/github/processed/):

  plugin-contacts.parquet       one row per person you work with on GitHub
                                (collaborators, authors and assignees of your
                                issues and PRs; you and bots are left out)
  plugin-interactions.parquet   one row per event: kind issue | pr | review,
                                owner_role author | assignee, due from the
                                milestone when there is one, status open |
                                closed | merged | done

The columns are the contract in tools/cross-source/plugin_intake.py. No network,
no token: it only reads the local files.

    uv run python tools/github/gh-l1-enrich.py
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
        description="Normalize the GitHub download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("gh-l1")

    import gh_api

    raw = gh_api.GH_DIR / gh_api.RAW_DIR
    if not (raw / "me.json").exists():
        print(
            f"github: nothing to enrich in {raw}; run tools/github/gh-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    e = gh_api.write_frames(gh_api.GH_DIR)
    for k, v in e.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", gh_api.GH_DIR / gh_api.PROCESSED_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
