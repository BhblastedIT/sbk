#!/usr/bin/env python3
"""L1 HubSpot: turns what hs-l0-download.py saved into the kernel's generic intake.

Writes, under ~/.sbk-data/hubspot/processed/ (or $SBK_DATA_ROOT/hubspot/processed/):

  plugin-contacts.parquet       one row per HubSpot contact (name, email, phone, company,
                                job title); you are left out
  plugin-interactions.parquet   one row per item:
                                  deal -> kind record, due = close date, status open |
                                          done (won) | closed (lost)
                                  note -> kind message, status done
                                  task -> kind issue, due = due date, status open | done
                                owner_role assignee / author when you own the item, other
                                otherwise; due dates are written only for items you own, so
                                a teammate's deal never becomes your commitment

The columns are the contract in tools/cross-source/plugin_intake.py. No network, no
token: it only reads the local files.

    uv run python tools/hubspot/hs-l1-enrich.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hs_api  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Normalize the HubSpot download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("hs-l1")

    raw = hs_api.raw_dir()
    if not (raw / "me.json").exists():
        print(
            f"HubSpot: nothing downloaded in {raw}; run tools/hubspot/hs-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    e = hs_api.write_frames()
    for k, v in e.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", hs_api.processed_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
