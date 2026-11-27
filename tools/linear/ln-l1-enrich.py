#!/usr/bin/env python3
"""L1 Linear: turns what ln-l0-download.py saved into the kernel's generic intake.

Writes, under ~/.sbk-data/linear/processed/ (or $SBK_DATA_ROOT/linear/processed/):

  plugin-contacts.parquet       one row per person on your issues (assignees,
                                creators, subscribers, comment authors; you and
                                app users are left out)
  plugin-interactions.parquet   one row per issue (kind issue, owner_role
                                assignee | author | other, due only when the
                                issue is yours, status open | done | cancelled |
                                closed) and one per comment (kind message,
                                status done)

The columns are the contract in tools/cross-source/plugin_intake.py. No network,
no key: it only reads the local files.

    uv run python tools/linear/ln-l1-enrich.py
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
        description="Normalize the Linear download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("ln-l1")

    import ln_api

    raw = ln_api.LN_DIR / ln_api.RAW_DIR
    if not (raw / ln_api.ME_FILE).exists():
        print(
            f"linear: nothing to enrich in {raw}; run tools/linear/ln-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    e = ln_api.write_frames(ln_api.LN_DIR)
    for k, v in e.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", ln_api.LN_DIR / ln_api.PROCESSED_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
