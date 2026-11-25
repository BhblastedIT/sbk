#!/usr/bin/env python3
""





















































from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from knowledge_schema import (
    Fact,
    FactSource,
    esigi_supersessione_valida,
    generate_entity_id,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


from sbk_config import DATA_ROOT

INGESTION_DIR = DATA_ROOT / "manual-ingestion"
INGESTION_PENDING = INGESTION_DIR / "pending"
INGESTION_DONE = INGESTION_DIR / "done"

SOURCE_TYPE = "manual_input"
DEFAULT_CONFIDENCE = 0.90






_write_profiles_fn = None


def _get_write_profiles():
    global _write_profiles_fn
    if _write_profiles_fn is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "xs_l2_knowledge_extract",
            Path(__file__).parent / "xs-l2-knowledge-extract.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _write_profiles_fn = mod.write_profiles
    return _write_profiles_fn







def _now() -> str:
    return datetime.now(UTC).isoformat()


def parse_fact_file(path: Path) -> list[Fact]:
    ""
    data = json.loads(path.read_text())

    batch_id = data.get("batch_id", path.stem)
    source_desc = data.get("source", "manual")
    confidence = data.get("confidence", DEFAULT_CONFIDENCE)

    facts: list[Fact] = []

    for entity_block in data.get("entities", []):
        name = entity_block["name"]
        etype = entity_block.get("type", "person")
        eid = entity_block.get("entity_id") or generate_entity_id(etype, name)

        for fact_data in entity_block.get("facts", []):
            attr = fact_data["attribute"]
            value = fact_data["value"]
            fact_confidence = fact_data.get("confidence", confidence)
            valid_from = fact_data.get("valid_from")
            valid_to = fact_data.get("valid_to")








            expired_at = fact_data.get("expired_at")
            superseded_by = fact_data.get("superseded_by")



            superseded_at = fact_data.get("superseded_at")







            esigi_supersessione_valida(fact_data, dove=f"{path.name} · {eid} · {attr}")

            fact = Fact(
                fact_id=str(uuid.uuid4()),
                entity_id=eid,
                entity_type=etype,
                attribute=attr,
                value=value,
                confidence=fact_confidence,
                valid_from=valid_from,
                valid_to=valid_to,
                created_at=_now(),
                expired_at=expired_at,
                source=FactSource(
                    source_type=SOURCE_TYPE,
                    source_file=f"manual-ingestion/{batch_id}",
                    record_id=batch_id,
                    extracted_at=_now(),
                ),
                superseded_by=superseded_by,
                superseded_at=superseded_at,
            )
            facts.append(fact)

    return facts


def ingest_file(path: Path, dry_run: bool = False) -> dict:
    ""
    log.info("Parsing: %s", path.name)
    facts = parse_fact_file(path)

    if not facts:
        log.warning("  No facts found in %s", path.name)
        return {"entities": 0, "facts": 0, "new_entities": 0, "updated_entities": 0}


    entities = {}
    for f in facts:
        if f.entity_id not in entities:
            entities[f.entity_id] = {"name": "", "type": f.entity_type, "count": 0}
        if f.attribute == "identity.name":
            entities[f.entity_id]["name"] = f.value
        entities[f.entity_id]["count"] += 1

    if dry_run:
        print(f"\n  DRY RUN — {path.name}:")
        for eid, info in entities.items():
            print(f"    {eid} ({info['type']}) {info['name']:30} {info['count']:3} facts")
        print(f"    TOTAL: {len(entities)} entities, {len(facts)} facts\n")
        return {"entities": len(entities), "facts": len(facts)}

    write_profiles = _get_write_profiles()
    stats = write_profiles(facts, dry_run=False)
    log.info("  Ingested: %s", stats)


    INGESTION_DONE.mkdir(parents=True, exist_ok=True)
    done_path = INGESTION_DONE / f"{path.stem}--{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    shutil.move(str(path), str(done_path))
    log.info("  Moved to: %s", done_path.name)

    return stats







def main():
    parser = argparse.ArgumentParser(
        description="Manual knowledge ingestion — inject facts into Knowledge Layer"
    )
    parser.add_argument("files", nargs="*", help="Fact file(s) to ingest (JSON format)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ingest all pending files from ~/.sbk-data/manual-ingestion/pending/",
    )
    parser.add_argument("--list", action="store_true", help="List pending fact files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created")
    args = parser.parse_args()


    INGESTION_PENDING.mkdir(parents=True, exist_ok=True)
    INGESTION_DONE.mkdir(parents=True, exist_ok=True)

    if args.list:
        pending = sorted(INGESTION_PENDING.glob("*.json"))
        if not pending:
            print("No pending fact files.")
        else:
            print(f"\nPending fact files ({len(pending)}):")
            for p in pending:
                data = json.loads(p.read_text())
                n_entities = len(data.get("entities", []))
                n_facts = sum(len(e.get("facts", [])) for e in data.get("entities", []))
                desc = data.get("description", "")[:60]
                print(f"  {p.name:50} {n_entities:3} entities  {n_facts:4} facts  {desc}")
            print()
        return


    files: list[Path] = []
    if args.all:
        files = sorted(INGESTION_PENDING.glob("*.json"))
        if not files:
            log.info("No pending fact files.")
            return
    elif args.files:
        files = [Path(f) for f in args.files]
    else:
        parser.print_help()
        return


    total = {"entities": 0, "facts": 0, "new_entities": 0, "updated_entities": 0}
    for path in files:
        if not path.exists():
            log.error("File not found: %s", path)
            continue
        stats = ingest_file(path, dry_run=args.dry_run)
        for k in total:
            total[k] += stats.get(k, 0)

    log.info("TOTAL: %s", total)


if __name__ == "__main__":
    main()
