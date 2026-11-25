#!/usr/bin/env python3
""





























from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from contracts.artifacts_contract import ArtifactContract, ContractError, load_contract
from contracts.write_guard import check_write

import sbk_config

log = logging.getLogger("sbk.dl-l0-harvest")


ARTIFACT_ID = "downloads-harvest-inventory"



DOC_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".rtf",
        ".odt",
        ".txt",
        ".md",
        ".csv",
        ".tsv",
        ".xls",
        ".xlsx",
        ".ods",
        ".ppt",
        ".pptx",
        ".odp",
        ".pages",
        ".numbers",
        ".key",
    }
)



SECRET_NAME_SUBSTRINGS: tuple[str, ...] = (
    "credential",
    "secret",
    "password",
    "passwd",
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "private_key",
    "privatekey",
    "keychain",
    ".kdbx",
    ".keystore",
)


SECRET_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pem",
        ".p12",
        ".pfx",
        ".der",
        ".key",
        ".asc",
        ".gpg",
        ".pgp",
        ".jks",
        ".keychain",
        ".kdbx",
    }
)


EXCLUDED_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".config",
        "credentials",
        ".sbk-credentials",
    }
)


DEFAULT_MAX_SIZE = 100 * 1024 * 1024




INVENTORY_CONTRACT_ENTRY: dict = {
    "path": "downloads-harvest/inventory.parquet",
    "tier": 0,
    "domain": "infrastructure",
    "inventory_class": "derived",
    "rebuild_class": "rebuildable",
    "schema": {
        "columns": {
            "sha256": "str",
            "source_path": "str",
            "dest_path": "str",
            "size_bytes": "int",
            "mtime_utc": "str",
            "ext": "str",
            "harvested_at": "str",
        }
    },
    "sanity": {
        "min_rows": 1,

        "max_drop_pct": 0.0,
        "sentinels": [
            {"column": "sha256", "min_non_null_pct": 100.0},
            {"column": "dest_path", "min_non_null_pct": 100.0},
        ],
        "quota": {"min_present": 2},
    },
}

INVENTORY_COLUMNS = (
    "sha256",
    "source_path",
    "dest_path",
    "size_bytes",
    "mtime_utc",
    "ext",
    "harvested_at",
)





def _data_root(root: Path | None) -> Path:
    return Path(root) if root is not None else sbk_config.DATA_ROOT


def harvest_dir(root: Path | None = None) -> Path:
    return _data_root(root) / "downloads-harvest"


def files_dir(root: Path | None = None) -> Path:
    return harvest_dir(root) / "files"


def inventory_path(root: Path | None = None) -> Path:
    return harvest_dir(root) / "inventory.parquet"





def is_excluded(path: Path) -> bool:
    ""
    name = path.name.lower()

    if path.name.startswith("."):
        return True
    if path.suffix.lower() in SECRET_EXTENSIONS:
        return True
    if any(sub in name for sub in SECRET_NAME_SUBSTRINGS):
        return True
    parts_lower = {p.lower() for p in path.parts}
    return bool(parts_lower & EXCLUDED_PATH_SEGMENTS)


def is_document(path: Path) -> bool:
    ""
    return path.suffix.lower() in DOC_EXTENSIONS


def iter_candidates(source_dir: Path) -> Iterator[Path]:
    ""




    source_dir = Path(source_dir)
    if not source_dir.exists():
        return
    for p in sorted(source_dir.rglob("*")):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        if is_excluded(p):
            continue
        if not is_document(p):
            continue
        yield p


def sha256_of(path: Path, *, chunk: int = 1 << 20) -> str:
    ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _safe_name(name: str) -> str:
    return "".join(c if (c.isalnum() or c in ".-_") else "_" for c in name)


def dest_for(sha: str, name: str, fdir: Path) -> Path:
    ""
    return Path(fdir) / f"{sha[:16]}__{_safe_name(name)}"





def _load_existing_inventory(root: Path | None) -> dict[str, dict]:
    ""
    p = inventory_path(root)
    if not p.exists():
        return {}
    try:
        import pandas as pd

        df = pd.read_parquet(p)
    except Exception:
        log.warning("Existing inventory is unreadable, starting from empty: %s", p)
        return {}
    out: dict[str, dict] = {}
    for rec in df.to_dict(orient="records"):
        sha = rec.get("sha256")
        if sha:
            out[str(sha)] = {k: rec.get(k) for k in INVENTORY_COLUMNS}
    return out





@dataclass
class HarvestResult:
    scanned: int = 0
    copied: int = 0
    skipped_existing: int = 0
    excluded: int = 0
    too_large: int = 0
    rows_written: int = 0
    inventory_written: bool = False
    aborted: bool = False
    abort_reasons: list[str] = field(default_factory=list)
    dry_run: bool = False





def _resolve_contract(contract: ArtifactContract | None, contract_path: Path | None):
    ""
    if contract is not None:
        return contract
    try:
        return load_contract(ARTIFACT_ID, contract_path)
    except ContractError:

        from contracts.artifacts_contract import _validate_entry

        return _validate_entry(ARTIFACT_ID, INVENTORY_CONTRACT_ENTRY)


def harvest(
    source_dir: Path | str | None = None,
    root: Path | None = None,
    *,
    dry_run: bool = False,
    max_size: int = DEFAULT_MAX_SIZE,
    workers: int = 4,
    contract: ArtifactContract | None = None,
    contract_path: Path | None = None,
) -> HarvestResult:
    ""









    import pandas as pd

    if source_dir is None:
        source_dir = Path.home() / "Downloads"
    source_dir = Path(source_dir)
    fdir = files_dir(root)

    result = HarvestResult(dry_run=dry_run)


    candidates = list(iter_candidates(source_dir))
    result.scanned = len(candidates)


    def _hash_one(p: Path) -> tuple[Path, str | None, int, str]:
        try:
            st = p.stat()
        except OSError:
            return (p, None, 0, "")
        if st.st_size > max_size:
            return (p, None, st.st_size, "too_large")
        try:
            digest = sha256_of(p)
        except OSError:
            return (p, None, st.st_size, "unreadable")
        mtime = sbk_config.to_utc_aware(datetime.fromtimestamp(st.st_mtime)).isoformat()
        return (p, digest, st.st_size, mtime)

    hashed: list[tuple[Path, str | None, int, str]] = []
    if candidates:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            hashed = list(ex.map(_hash_one, candidates))


    inventory = _load_existing_inventory(root)
    now_iso = sbk_config.utc_now().isoformat()

    for p, digest, size, meta in sorted(hashed, key=lambda t: str(t[0])):
        if digest is None:
            if meta == "too_large":
                result.too_large += 1
            continue
        dest = dest_for(digest, p.name, fdir)
        already = digest in inventory and dest.exists()
        if already:
            result.skipped_existing += 1
            continue

        if not dry_run:
            fdir.mkdir(parents=True, exist_ok=True)
            if not dest.exists():

                shutil.copy2(p, dest)
        result.copied += 1
        inventory[digest] = {
            "sha256": digest,
            "source_path": str(p),
            "dest_path": str(dest),
            "size_bytes": int(size),
            "mtime_utc": meta,
            "ext": p.suffix.lower(),
            "harvested_at": now_iso,
        }


    rows = [inventory[s] for s in sorted(inventory)]
    if not rows:
        log.info("No document to inventory (0 rows).")
        return result
    df = pd.DataFrame(rows, columns=list(INVENTORY_COLUMNS))
    result.rows_written = len(df)


    prev = inventory_path(root)
    verdict = check_write(
        df,
        ARTIFACT_ID,
        previous_path=prev if prev.exists() else None,
        contract=_resolve_contract(contract, contract_path),
        dry_run=dry_run,
    )
    if verdict.aborted:
        result.aborted = True
        result.abort_reasons = list(verdict.reasons)
        log.error("write-guard ABORT on %s: %s", ARTIFACT_ID, "; ".join(verdict.reasons))
        return result


    if not dry_run:
        sbk_config.safe_write_parquet(df, prev)
        result.inventory_written = True
        log.info("Inventory written: %s (%d rows)", prev, len(df))
    else:
        log.info("[dry-run] write-guard PASS; inventory NOT written (%d rows).", len(df))

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent harvest of ~/Downloads: copies documents once (by content hash) and keeps an inventory"
    )
    parser.add_argument("--source", default=None, help="Source folder (default ~/Downloads)")
    parser.add_argument("--dry-run", action="store_true", help="Copy nothing and write nothing, only report")
    parser.add_argument(
        "--max-size-mb", type=int, default=100, help="Skip files larger than this, in MB (default 100)"
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for hashing (default 4)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    res = harvest(
        source_dir=args.source,
        dry_run=args.dry_run,
        max_size=args.max_size_mb * 1024 * 1024,
        workers=args.workers,
    )
    log.info(
        "Harvest: scanned=%d copied=%d already_present=%d too_large=%d rows=%d written=%s%s",
        res.scanned,
        res.copied,
        res.skipped_existing,
        res.too_large,
        res.rows_written,
        res.inventory_written,
        " [dry-run]" if res.dry_run else "",
    )
    return 1 if res.aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
