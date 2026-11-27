#!/usr/bin/env python3
"""Fact search index: builds l3/fact-index.json from the extracted facts (high and medium confidence, names
resolved), rebuilt only when the sources change; --search tests a query.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, setup_logging

from sbk_config import (
    CONFIDENZA_MEDIA,
    L3_DIR,
    RELATIONSHIP_FACTS_FILE,
    confidenza,
    safe_write_json,
)

log = logging.getLogger("sbk-l3")



FACT_INDEX_FILE = L3_DIR / "fact-index.json"



VALID_CONFIDENCE = {"high", "medium"}





def _source_mtime() -> float:
    ""
    if RELATIONSHIP_FACTS_FILE.exists():
        return RELATIONSHIP_FACTS_FILE.stat().st_mtime
    return 0.0


def _needs_rebuild(force: bool = False) -> bool:
    ""
    if force:
        return True
    if not FACT_INDEX_FILE.exists():
        return True
    try:
        index = json.loads(FACT_INDEX_FILE.read_text(encoding="utf-8"))
        prev_mtime = index.get("source_mtime", 0)
        return _source_mtime() > prev_mtime
    except (json.JSONDecodeError, OSError, KeyError):
        return True





def _colonna(df, nome: str, vuoto=None) -> list:
    ""
    return df[nome].tolist() if nome in df.columns else [vuoto] * len(df)


def _build_name_lookup(data: SBKData) -> dict[str, str]:
    ""
    lookup: dict[str, str] = {}
    contacts = data.contacts
    if contacts.empty:
        return lookup

    for pid, name in zip(_colonna(contacts, "person_id"), _colonna(contacts, "name"), strict=True):
        if pid and name and str(pid).strip() and str(name).strip():
            lookup[str(pid).strip()] = str(name).strip()
    return lookup





def build_fact_index(data: SBKData) -> dict:
    ""



    facts_df = data.relationship_facts
    if facts_df.empty:
        log.warning("No relationship facts found — generating empty index")
        return {
            "generated": datetime.now(UTC).isoformat(),
            "source_mtime": _source_mtime(),
            "total_indexed": 0,
            "predicates": [],
            "entries": [],
        }

    name_lookup = _build_name_lookup(data)
    log.info(f"Name lookup: {len(name_lookup)} person_id -> name mappings")

    entries: list[dict] = []
    predicates_seen: set[str] = set()




    def _testi(nome: str) -> list[str]:
        return [str(v).strip() for v in _colonna(facts_df, nome, "")]

    righe = zip(
        _colonna(facts_df, "confidence"),
        _testi("subject_person_id"),
        _testi("predicate"),
        _testi("object"),
        _testi("source_type"),
        _testi("source_date"),
        strict=True,
    )
    for confidence, subject_pid, predicate, value, source_type, source_date in righe:

        if confidenza(confidence) < CONFIDENZA_MEDIA:
            continue
        if not subject_pid:
            continue

        person_name = name_lookup.get(subject_pid, "")


        if not predicate or not value:
            continue

        predicates_seen.add(predicate)

        entries.append(
            {
                "person_id": subject_pid,
                "person_name": person_name,
                "predicate": predicate,
                "value": value,
                "source_type": source_type,
                "source_date": source_date,
                "confidence": confidence,
            }
        )


    entries.sort(key=lambda e: e.get("source_date", ""), reverse=True)

    index = {
        "generated": datetime.now(UTC).isoformat(),
        "source_mtime": _source_mtime(),
        "total_indexed": len(entries),
        "predicates": sorted(predicates_seen),
        "entries": entries,
    }

    log.info(f"Fact index built: {len(entries)} entries, {len(predicates_seen)} unique predicates")
    return index





def search_facts(
    index: dict,
    query: str,
    predicate: str | None = None,
    limit: int = 20,
) -> list[dict]:
    ""










    query_lower = query.strip().lower()
    predicate_lower = predicate.strip().lower() if predicate else None

    results: list[dict] = []
    for entry in index.get("entries", []):

        if query_lower not in entry.get("value", "").lower():
            continue

        if predicate_lower and entry.get("predicate", "").lower() != predicate_lower:
            continue
        results.append(entry)
        if len(results) >= limit:
            break

    return results





def main():
    parser = argparse.ArgumentParser(
        description="SBK Fact Search Index Builder",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force rebuild even if source unchanged"
    )
    parser.add_argument("--search", type=str, default="", help="Search query to test")
    parser.add_argument("--predicate", type=str, default="", help="Filter by predicate")
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-fact-index")


    if args.search:
        if not FACT_INDEX_FILE.exists():
            log.error(f"Fact index not found at {FACT_INDEX_FILE} — run without --search first")
            sys.exit(1)
        index = json.loads(FACT_INDEX_FILE.read_text(encoding="utf-8"))
        results = search_facts(
            index,
            args.search,
            predicate=args.predicate or None,
        )
        print(f"\n--- Fact search: '{args.search}' ---")
        if args.predicate:
            print(f"    Predicate filter: {args.predicate}")
        print(f"    Results: {len(results)}\n")
        for r in results:
            name = r.get("person_name") or r.get("person_id", "?")
            print(
                f"  {name:30s}  {r['predicate']:20s}  "
                f"{r['value'][:60]:60s}  [{r['source_type']}  {r['source_date']}]"
            )
        return


    if args.stats:
        if not FACT_INDEX_FILE.exists():
            log.error(f"Fact index not found at {FACT_INDEX_FILE}")
            sys.exit(1)
        index = json.loads(FACT_INDEX_FILE.read_text(encoding="utf-8"))
        print("\n--- Fact Index Stats ---")
        print(f"  Generated:     {index.get('generated', '?')}")
        print(f"  Total indexed: {index.get('total_indexed', 0):,}")
        print(f"  Predicates:    {len(index.get('predicates', []))}")
        print("\n  Predicate list:")
        for p in index.get("predicates", []):

            count = sum(1 for e in index["entries"] if e["predicate"] == p)
            print(f"    {p:30s}  ({count:,} entries)")
        return


    if not _needs_rebuild(force=args.force):
        log.info("Fact index is up-to-date — skipping rebuild (use --force to override)")
        return

    if not RELATIONSHIP_FACTS_FILE.exists():
        # Written by the paid relationship extract (--all with spending consent), never by --ingest:
        # a first install has none yet. Nothing to index, not an error.
        log.info(
            f"No relationship facts yet ({RELATIONSHIP_FACTS_FILE.name}, written by the paid "
            "relationship extract): nothing to index"
        )
        return

    log.info("Building fact search index...")
    data = SBKData()
    index = build_fact_index(data)



    safe_write_json(FACT_INDEX_FILE, index, indent=2, ensure_ascii=False)
    log.info(f"Fact index written to {FACT_INDEX_FILE} ({index['total_indexed']:,} entries)")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-fact-index", source="l3-fact-index", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
