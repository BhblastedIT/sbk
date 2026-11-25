#!/usr/bin/env python3
"""L0 Databases: run your read-only queries against your own SQLite, PostgreSQL or MySQL.

Each source declared in sbk.config.json (section "databases") is one SELECT or
WITH query on one connection. The connection is opened read-only where the
driver allows it, and every query is checked before it is sent (see
tools/databases/db_reader.py). What lands in ~/.sbk-data/databases/ (or
$SBK_DATA_ROOT/databases/):

  raw/<source-id>.parquet   the query result, every column as text
  state.json                per source: query fingerprint, watermark, last run
  download-summary.json     what this run did (rows, mode, errors, redacted)

Incremental when a source declares "cursor" (a column that only grows, such as
updated_at or an id) and "key": only rows with cursor >= the last value seen
are read and merged by key. A changed query, or --full, re-reads everything.
Then run db-l1-enrich.py (it builds the generic intake files).

    uv run python tools/databases/db-l0-download.py --list      # the sources, no connection
    uv run python tools/databases/db-l0-download.py --dry-run   # opens each connection, runs SELECT 1, writes nothing
    uv run python tools/databases/db-l0-download.py
    uv run python tools/databases/db-l0-download.py --full --source crm-people
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
        description='Read people and companies from your own database with read-only queries (sbk.config.json "databases").',
    )
    ap.add_argument(
        "--list", action="store_true", help="print the configured sources and exit; no connection"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="open each connection read-only and run SELECT 1; write nothing",
    )
    ap.add_argument(
        "--full", action="store_true", help="ignore the watermarks and re-read every source"
    )
    ap.add_argument(
        "--source", action="append", metavar="ID", help="run only this source (repeatable)"
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")
    log = logging.getLogger("db-l0")

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

    if a.list:
        for s in settings["sources"]:
            c = settings["connections"][s["connection"]]
            print(
                f"{s['id']}: {s['intake']} from {s['connection']} ({c['engine']}/{c['driver']})"
                + (f", incremental on {s['cursor']}" if s["cursor"] else ", full read")
            )
        return 0

    if a.dry_run:
        names = sorted(
            {s["connection"] for s in settings["sources"] if not a.source or s["id"] in a.source}
        )
        failed = 0
        for name in names:
            conn = settings["connections"][name]
            try:
                secret, where = dr.resolve_secret(conn)
                reader = dr.open_reader(conn, secret)
                try:
                    reader.ping()
                finally:
                    reader.close()
                log.info(
                    "databases: %s (%s/%s) ok, connection string from %s, read-only",
                    name,
                    conn["engine"],
                    conn["driver"],
                    where,
                )
            except (dr.NoSecret, dr.DriverMissing, RuntimeError) as e:
                failed += 1
                print(str(e), file=sys.stderr)
        if failed:
            return 1
        log.info("  nothing written (dry run)")
        return 0

    try:
        summary = dr.run_download(settings, dr.DB_DIR, only=a.source, full=a.full)
    except dr.ConfigError as e:
        print(str(e), file=sys.stderr)
        return 1
    # Errors were already printed, one line each, by run_download (redacted).
    if summary["errors"] and not summary["sources"]:
        return 1
    log.info("  summary: %s", dr.DB_DIR / dr.SUMMARY_FILE)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
