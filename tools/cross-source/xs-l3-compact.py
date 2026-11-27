#!/usr/bin/env python3
"""Maintenance of the L3 vector index (LanceDB): compacts the table and removes old versions to free disk space,
skipping while an indexing run is in progress. Dry run by default; --apply executes.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from sbk_config import VECTOR_DB_DIR  # noqa E402

log = logging.getLogger("sbk-l3-compact")


def _setup_logging(verbose: bool = False) -> None:
    fmt = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _is_index_running() -> tuple[bool, str]:
    ""
    try:
        result = subprocess.run(

            ["pgrep", "-f", "xs-l3-index.py"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = result.stdout.strip()
        return (bool(out), out)
    except Exception as e:
        return (False, f"pgrep error {e}")


def _dir_size_bytes(path: Path) -> int:
    ""
    if not path.exists():
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _human(n: int) -> str:
    ""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _snapshot_sizes(table_path: Path) -> dict[str, int]:
    ""
    return {
        "data": _dir_size_bytes(table_path / "data"),
        "_indices": _dir_size_bytes(table_path / "_indices"),
        "_versions": _dir_size_bytes(table_path / "_versions"),
        "_transactions": _dir_size_bytes(table_path / "_transactions"),
        "_deletions": _dir_size_bytes(table_path / "_deletions"),
        "total": _dir_size_bytes(table_path),
    }


def _log_sizes(label: str, sizes: dict[str, int]) -> None:
    log.info("%s sizes", label)
    for k in ["data", "_indices", "_versions", "_transactions", "_deletions"]:
        log.info("  %-15s %s", k, _human(sizes[k]))
    log.info("  %-15s %s", "TOTAL", _human(sizes["total"]))


def main():
    parser = argparse.ArgumentParser(
        description="LanceDB maintenance for SBK L3 vector index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Runs the operations. Without this flag, dry-run.",
    )
    parser.add_argument(
        "--table-name",
        default="sbk_chunks",
        help="LanceDB table name (default sbk_chunks)",
    )
    parser.add_argument(
        "--older-than-hours",
        type=int,
        default=24,
        help="Removes versions older than N hours (default 24)",
    )
    parser.add_argument(
        "--no-compact",
        action="store_true",
        help="Skips compact_files, runs only cleanup",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Skips cleanup_old_versions, runs only compact",
    )
    parser.add_argument(
        "--skip-if-running",
        action="store_true",
        help="Exits without doing anything if xs-l3-index.py is running",
    )
    parser.add_argument(
        "--force-if-running",
        action="store_true",
        help="Runs even if xs-l3-index.py is running (risky)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    table_path = VECTOR_DB_DIR / f"{args.table_name}.lance"
    if not table_path.exists():
        log.error("Table not found, %s", table_path)
        sys.exit(1)


    is_running, info = _is_index_running()
    if is_running:
        log.warning("xs-l3-index.py appears to be running")
        log.warning("  %s", info)
        if args.apply:
            if args.skip_if_running:
                log.info("--skip-if-running active, exiting without operations")
                sys.exit(0)
            if not args.force_if_running:
                log.error(
                    "Exiting for safety. Use --force-if-running to proceed "
                    "anyway (not recommended during a write)"
                )
                sys.exit(2)
        else:
            log.info("Dry-run, proceeding in read-only mode despite active builder")


    try:
        du = shutil.disk_usage(table_path)
        log.info(
            "Disk, free %s of %s (%.1f percent used)",
            _human(du.free),
            _human(du.total),
            100 * (du.used / du.total),
        )
    except OSError:
        pass


    before = _snapshot_sizes(table_path)
    _log_sizes("BEFORE", before)


    log.info("\nOpening LanceDB %s, table %s", VECTOR_DB_DIR, args.table_name)
    import lancedb

    db = lancedb.connect(str(VECTOR_DB_DIR))
    tbl = db.open_table(args.table_name)


    versions = list(tbl.list_versions())
    log.info("\nTotal versions, %d", len(versions))
    if versions:
        first_ts = versions[0]["timestamp"]
        last_ts = versions[-1]["timestamp"]
        log.info("  first  v%-4d %s", versions[0]["version"], first_ts)
        log.info("  last   v%-4d %s", versions[-1]["version"], last_ts)
        log.info(
            "  current rows (last version metadata), %s",
            versions[-1]["metadata"].get("total_rows", "?"),
        )


    try:
        indices = list(tbl.list_indices())
        log.info("\nActive indices, %d", len(indices))
        for idx in indices:
            log.info("  - %s", idx)
    except Exception as e:
        log.warning("list_indices not available, %s", e)


    indices_dir = table_path / "_indices"
    if indices_dir.exists():
        index_dirs = [p for p in indices_dir.iterdir() if p.is_dir()]
        log.info("\n_indices/ contains %d folders (UUID)", len(index_dirs))
        active_count = len(indices) if "indices" in locals() else 0
        log.info(
            "  active %d, estimated orphans %d", active_count, max(0, len(index_dirs) - active_count)
        )

    if not args.apply:
        log.info("\n[DRY RUN] No operation performed. Use --apply to run.")
        log.info("Operations that would run with --apply,")
        if not args.no_compact:
            log.info("  1) tbl.compact_files()")
        if not args.no_cleanup:
            log.info(
                "  2) tbl.cleanup_old_versions(older_than=timedelta(hours=%d), delete_unverified=False)",
                args.older_than_hours,
            )
        sys.exit(0)


    t0 = time.time()


    if not args.no_compact:
        log.info("\nRunning compact_files...")
        try:
            t_c = time.time()
            stats = tbl.compact_files()
            log.info("compact_files completed in %.1fs", time.time() - t_c)
            log.info("  stats, %s", stats)
        except Exception as e:
            log.error("compact_files failed, %s", e)


    if not args.no_cleanup:
        cutoff = timedelta(hours=args.older_than_hours)
        log.info(
            "\nRunning cleanup_old_versions, older_than=%dh (cutoff %s UTC)",
            args.older_than_hours,
            datetime.utcnow() - cutoff,
        )
        try:
            t_c = time.time()
            cleanup_stats = tbl.cleanup_old_versions(
                older_than=cutoff,
                delete_unverified=False,
            )
            log.info("cleanup_old_versions completed in %.1fs", time.time() - t_c)
            log.info("  stats, %s", cleanup_stats)
        except Exception as e:
            log.error("cleanup_old_versions failed, %s", e)


    after = _snapshot_sizes(table_path)
    _log_sizes("\nAFTER", after)


    log.info("\nDELTA")
    for k in ["data", "_indices", "_versions", "_transactions", "_deletions", "total"]:
        delta = before[k] - after[k]
        sign = "-" if delta > 0 else "+"
        log.info("  %-15s %s%s", k, sign, _human(abs(delta)))

    elapsed = time.time() - t0
    log.info("\nTotal time, %.1fs", elapsed)


if __name__ == "__main__":
    main()
