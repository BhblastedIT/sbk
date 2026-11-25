#!/usr/bin/env python3
"""L1 Databases: turns what db-l0-download.py saved into the kernel's generic intake.

Applies the column map of each source (sbk.config.json "databases.sources[].columns")
to raw/<source-id>.parquet and writes, under ~/.sbk-data/databases/processed/
(or $SBK_DATA_ROOT/databases/processed/):

  plugin-contacts.parquet       one row per person (sources with "intake": "contacts");
                                rows with the same email (else phone, else name) are merged
  plugin-interactions.parquet   one row per event (sources with "intake": "interactions"),
                                kind and owner_role from the source or a mapped column

The columns are the contract in tools/cross-source/plugin_intake.py. No network,
no database connection: it only reads the local files, so a changed column map
needs no new download.

    uv run python tools/databases/db-l1-enrich.py
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
        description="Map the database download into plugin-contacts/plugin-interactions parquet."
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("db-l1")

    # Same as the L0: SBK_DATA_ROOT / SBK_CONFIG may live in .env, and they are
    # read when db_reader imports sbk_config, so .env is loaded first.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import db_reader as dr

    try:
        settings = dr.load_settings()
    except dr.ConfigError as e:
        print(str(e), file=sys.stderr)
        return 1
    raw = dr.DB_DIR / dr.RAW_DIR
    if not any((raw / f"{s['id']}.parquet").exists() for s in settings["sources"]):
        print(
            f"databases: nothing to enrich in {raw}; run tools/databases/db-l0-download.py first",
            file=sys.stderr,
        )
        return 1
    stats = dr.write_frames(settings, dr.DB_DIR)
    for k, v in stats.items():
        log.info("  %-18s %s", k, v)
    log.info("  written to %s", dr.DB_DIR / dr.PROCESSED_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
