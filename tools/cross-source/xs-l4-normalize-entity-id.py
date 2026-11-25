#!/usr/bin/env python3
""























from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-xs-l4-normalize-entity-id")


def _entity_files() -> list[Path]:
    out: list[Path] = []
    if not KNOWLEDGE_ENTITIES_DIR.exists():
        return out
    for type_dir in KNOWLEDGE_ENTITIES_DIR.iterdir():
        if not type_dir.is_dir():
            continue
        for f in type_dir.iterdir():
            if f.name.endswith(".json") and not f.name.startswith("_"):
                out.append(f)
    return out


def _process_file(path: Path, dry_run: bool) -> tuple[int, int, int]:
    ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return (0, 0, 0)

    file_eid = data.get("entity_id", "")
    if not file_eid:
        return (0, 0, 0)

    facts = data.get("facts", [])
    found = 0
    no_prov = 0
    changed = False

    for fact in facts:
        fe = fact.get("entity_id")
        if fe and fe != file_eid:
            found += 1

            if not fact.get("source_entity_id"):
                fact["source_entity_id"] = fe
                no_prov += 1
            fact["entity_id"] = file_eid
            changed = True

    if changed and not dry_run:


        safe_write_json(path, data, backup=False)

    return (found, no_prov, found if changed else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalizza foreign facts (entity_id -> file)")
    ap.add_argument("--apply", action="store_true", help="Esegue (default: dry-run)")
    ap.add_argument("--workers", type=int, default=8, help="Thread paralleli")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    dry_run = not args.apply

    log.info("=" * 60)
    log.info("xs-l4-normalize-entity-id — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)

    files = _entity_files()
    log.info("Scansiono %d file entità...", len(files))

    tot_found = tot_noprov = tot_files_changed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_process_file, f, dry_run): f for f in files}
        for fut in as_completed(futs):
            found, no_prov, rewritten = fut.result()
            tot_found += found
            tot_noprov += no_prov
            if rewritten:
                tot_files_changed += 1

    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Foreign facts trovati:        %d", tot_found)
    log.info("  ...di cui senza provenienza:  %d (source_entity_id aggiunto)", tot_noprov)
    log.info("  File con almeno 1 rewrite:    %d", tot_files_changed)
    if dry_run:
        log.info("")
        log.info("  Esegui con --apply per normalizzare.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
