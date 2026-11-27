#!/usr/bin/env python3
"""Schema migration of the L3 vector table (sbk_chunks): adds the new columns in place, with a check (--check exits
1 when a migration is pending), backup and disk checks, rollback and verify.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
for p in (_TOOLS_DIR, _THIS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sbk_config import VECTOR_DB_DIR  # noqa E402

log = logging.getLogger("sbk-l3-schema-migrate")

TABLE_NAME = "sbk_chunks"
TARGET_SCHEMA_VERSION = 2
LOCK_FILE = VECTOR_DB_DIR / ".schema-migration.lock"
AUDIT_LOG = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "l3"
    / "migration-audit.jsonl"
)


SCALAR_COLUMNS_SQL = {
    "context_summary": "''",
    "indexed_at": "''",
    "embedding_model": "'qwen3-0.6b-4bit-dwq'",
    "pii_level": "cast(1 as tinyint)",
    "lang": "'mixed'",
    "content_hash": "''",
    "chunker_version": "'v1-legacy'",
}

ALL_NEW_COLUMNS = list(SCALAR_COLUMNS_SQL) + ["schema_version"]

PII_RESTRICTED = ["clinical", "personio", "whoop", "docusign", "apple_health"]
PII_PUBLIC = ["network", "raw", "domain"]


def _setup_logging(verbose: bool = False) -> None:
    log_dir = (
        Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "l3"
        / "logs"
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"schema-migrate-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    handlers: list[logging.Handler] = [logging.StreamHandler(), logging.FileHandler(log_file)]
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers)
    log.info("log file, %s", log_file)


def _audit(event: str, **kw) -> None:
    ""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(UTC).isoformat(), "event": event, **kw}
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        log.warning("audit log failed, %s", e)


def _script_checksum() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def _running(pattern: str) -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False


def _check_freeze() -> list[str]:
    return [p for p in ["xs-l3-index.py", "xs-l3-brief", "xs-l3-search.py"] if _running(p)]


# The default --destination of tools/infrastructure/sb-backup.py (its DEFAULT_DESTINATION).
BACKUP_DIR_DEFAULT = Path.home() / "Backups" / "sbk"


def _sb_backup_archives(bdir: Path) -> list[Path]:
    """The finished archives sb-backup writes: sbk-<full|l1|l2|l3|l1-drive...>-<ts>.tar.gz, plain or .enc.

    Left out: config-only archives (sbk-config-*, they hold no data) and unfinished ones (*.parziale).
    """
    found = {*bdir.glob("sbk-*.tar.gz"), *bdir.glob("sbk-*.tar.gz.enc")}
    return sorted(
        (f for f in found if f.is_file() and not f.name.startswith("sbk-config-")),
        key=lambda f: f.stat().st_mtime,
    )


def _check_backup(backup_dir: Path | None = None) -> tuple[bool, str]:
    bdir = Path(backup_dir).expanduser() if backup_dir else BACKUP_DIR_DEFAULT
    hint = "run tools/infrastructure/sb-backup.py first, or pass --backup-dir where you keep its archives"
    if not bdir.is_dir():
        return False, f"no backup folder {bdir} ({hint})"
    backups = _sb_backup_archives(bdir)
    if not backups:
        return False, f"no sb-backup archive in {bdir} ({hint})"
    latest = backups[-1]
    age_h = (datetime.now().timestamp() - latest.stat().st_mtime) / 3600
    return True, f"{latest.name} (age {age_h:.1f}h)"


def _disk_free_gb() -> float:
    try:
        return shutil.disk_usage(VECTOR_DB_DIR).free / (1024**3)
    except OSError:
        return 0.0


def _open():
    import lancedb

    db = lancedb.connect(str(VECTOR_DB_DIR))
    return db, db.open_table(TABLE_NAME)


def _cols(tbl) -> set[str]:
    return set(tbl.schema.names)


def _schema_version_value(tbl) -> int | None:
    ""
    if "schema_version" not in _cols(tbl):
        return None
    try:
        df = tbl.search().select(["schema_version"]).limit(1).to_pandas()
        return int(df["schema_version"].iloc[0]) if len(df) else None
    except Exception:
        return None


def _is_migrated(tbl) -> bool:
    v = _schema_version_value(tbl)
    return v is not None and v >= TARGET_SCHEMA_VERSION





def cmd_check(args) -> int:
    ""
    _db, tbl = _open()
    if _is_migrated(tbl):
        log.info("schema_version >= %d, migration OK", TARGET_SCHEMA_VERSION)
        return 0
    log.warning("MIGRATION PENDING (schema_version < %d)", TARGET_SCHEMA_VERSION)
    return 1


def cmd_dry_run(args) -> int:
    _db, tbl = _open()
    cols = _cols(tbl)
    log.info("Table %s, %d rows, %d columns", TABLE_NAME, tbl.count_rows(), len(cols))
    if _is_migrated(tbl):
        log.info("ALREADY MIGRATED (schema_version=%d). Use --verify.", _schema_version_value(tbl))
        return 0
    to_add = [c for c in ALL_NEW_COLUMNS if c not in cols]
    log.info("\n[DRY RUN] Columns to add (%d), %s", len(to_add), to_add)
    log.info("\nBackfill pii_level per-source (CASE not supported in 0.29.2, using update),")
    log.info("  restricted->2, %s", ", ".join(PII_RESTRICTED))
    log.info("  public->0,     %s", ", ".join(PII_PUBLIC))
    log.info("  internal->1,   default (rest)")
    ok_bk, bk = _check_backup(getattr(args, "backup_dir", None))
    log.info("\nPre-conditions,")
    log.info("  backup, %s -> %s", "OK" if ok_bk else "MISSING", bk)
    log.info("  free disk, %.1f GB", _disk_free_gb())
    log.info("  active processes to stop, %s", _check_freeze() or "none")
    log.info(
        "\nApply order, scalars -> update pii_level -> sparse_vector -> compact -> schema_version (last) -> verify"
    )
    log.info("Use --apply to run.")
    return 0


def cmd_apply(args) -> int:
    db, tbl = _open()
    if _is_migrated(tbl):
        log.info("Already migrated, nothing to do.")
        return 0


    ok_bk, bk = _check_backup(getattr(args, "backup_dir", None))
    if not ok_bk and not args.skip_backup_check:
        log.error("Backup missing (%s). Use --skip-backup-check if sure.", bk)
        return 2
    log.info("Backup, %s", bk)
    if _disk_free_gb() < 20 and not args.force:
        log.error("Disk < 20 GB. Abort (--force to override).")
        return 2
    frozen = _check_freeze()
    if frozen and not args.force:
        log.error("Active processes, %s. Stop them or --force.", frozen)
        return 2


    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCK_FILE, "w")  # noqa: SIM115 (lock must live for all of cmd_apply, closed in finally)
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("Another migration in progress (lock %s). Abort.", LOCK_FILE)
        return 2

    t0 = time.time()
    cols = _cols(tbl)
    n = tbl.count_rows()
    _audit("apply_start", rows=n, cols_before=len(cols), checksum=_script_checksum())
    log.info("Migration %s, %d rows, %d columns", TABLE_NAME, n, len(cols))

    try:

        to_add = {c: e for c, e in SCALAR_COLUMNS_SQL.items() if c not in cols}
        if to_add:
            log.info("[1/5] scalar add_columns, %s", list(to_add))
            tbl.add_columns(to_add)
            log.info("  ok, %d columns", len(_cols(tbl)))


        log.info("[2/5] backfill pii_level per-source")
        restricted_in = "', '".join(PII_RESTRICTED)
        public_in = "', '".join(PII_PUBLIC)
        tbl.update(where=f"source_type IN ('{restricted_in}')", values={"pii_level": 2})
        tbl.update(where=f"source_type IN ('{public_in}')", values={"pii_level": 0})
        now_iso = datetime.now(UTC).isoformat()
        tbl.update(where="indexed_at = ''", values={"indexed_at": now_iso})
        log.info("  pii_level + indexed_at backfilled")



        log.info("[3/5] sparse_vector skip (E7-only, added if E7 enabled)")


        log.info("[4/5] compact_files post-migration")
        try:
            tbl.compact_files()
            log.info("  compact ok")
        except Exception as e:
            log.warning("  compact failed (non-critical), %s", e)


        log.info("[5/5] add_columns schema_version (marks completion)")
        tbl.add_columns({"schema_version": f"cast({TARGET_SCHEMA_VERSION} as int)"})

    except Exception as e:
        log.error("MIGRATION FAILED, %s", e)
        log.error(
            "Partial schema. schema_version NOT set, re-run resumes. Consider --rollback."
        )
        _audit("apply_failed", error=str(e), elapsed_s=round(time.time() - t0, 1))
        return 3
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()

    elapsed = time.time() - t0
    _audit("apply_done", cols_after=len(_cols(tbl)), elapsed_s=round(elapsed, 1))
    log.info("\nMigration completed in %.1fs.", elapsed)
    log.warning(
        "REMEMBER, (1) update Chunk.to_dict()+pa.schema in xs-l3-index.py BEFORE the next run (S5)"
    )
    log.warning("REMEMBER, (2) run xs-l3-compact.py --apply to clean up versions")


    log.info("\n=== auto-verify ===")
    return cmd_verify(args)


def cmd_rollback(args) -> int:
    _db, tbl = _open()
    present = [c for c in ALL_NEW_COLUMNS if c in _cols(tbl)]
    if not present:
        log.info("No new columns, nothing to roll back.")
        return 0
    if not args.apply:
        log.info("[DRY RUN] drop_columns it would run, %s", present)
        log.info("Use --rollback --apply.")
        return 0
    log.info("drop_columns, %s", present)
    tbl.drop_columns(present)
    _audit("rollback", dropped=present)
    log.info("Rollback completed, %d columns", len(_cols(tbl)))
    return 0


def cmd_verify(args) -> int:
    _db, tbl = _open()
    cols = _cols(tbl)
    missing = set(ALL_NEW_COLUMNS) - cols
    log.info("Total columns, %d", len(cols))
    log.info("schema_version, %s", _schema_version_value(tbl))
    if missing:
        log.error("MISSING columns, %s", sorted(missing))
        return 5

    pii_type = next((f.type for f in tbl.schema if f.name == "pii_level"), None)
    log.info("pii_level type, %s", pii_type)

    try:
        df = tbl.search().select(["source_type", "pii_level"]).limit(2_000_000).to_pandas()
        log.info("pii_level distribution, %s", df["pii_level"].value_counts().to_dict())
        for src in PII_RESTRICTED:
            sub = df[df["source_type"] == src]
            if len(sub) and not (sub["pii_level"] == 2).all():
                log.error("PRIVACY, source %s pii_level != 2", src)
                return 5
        log.info("privacy check ok (restricted sources = 2 where present)")
    except Exception as e:
        log.warning("distribution check failed, %s", e)
    log.info("VERIFY OK")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="SBK L3 schema migration via add_columns")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--check", action="store_true", help="exit 1 if migration pending (CI)")
    p.add_argument("--rollback", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip-backup-check", action="store_true")
    p.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help=f"folder with your sb-backup archives (sb-backup --destination; default {BACKUP_DIR_DEFAULT})",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    _setup_logging(args.verbose)

    if args.check:
        rc = cmd_check(args)
    elif args.rollback:
        rc = cmd_rollback(args)
    elif args.verify:
        rc = cmd_verify(args)
    elif args.apply:
        rc = cmd_apply(args)
    else:
        rc = cmd_dry_run(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
