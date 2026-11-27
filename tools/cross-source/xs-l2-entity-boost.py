#!/usr/bin/env python3
"""Entity resolution boost: fuzzy-matches the people and organizations named in the NLP entity table to known
people and companies, incremental with a checkpoint.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import setup_logging

from sbk_config import ATTIO_PROCESSED_DIR, ENRICHED_DIR, NLP_DIR, safe_write_parquet

log = logging.getLogger("sbk-entity-boost")





NOISE_ENTITIES: set[str] = {

    "business",
    "brand",
    "il brand",
    "un brand",
    "e-commerce",
    "ecommerce",
    "aziende",
    "azienda",
    "l'azienda",
    "marketing",
    "agency",
    "agenzia",
    "startup",
    "company",
    "platform",
    "social media",
    "marketplace",
    "network",
    "team",
    "progetto",
    "project",
    "gruppo",
    "management",
    "finance",
    "community",
    "investitori",
    "investor",
    "investors",
    "banca",
    "media",
    "casino",
    "sas",
    "instagram",
    "youtube",
    "linkedin",
    "facebook",
    "tiktok",
    "google",
    "amazon",
    "whatsapp",
    "telegram",
    "twitter",
    "spotify",
    "uber",
    "airbnb",

    "budget",
    "soldi",
    "un milione",
    "money",
    "euro",
    "dollari",
    "mille",
    "fatturato",
    "revenue",
    "investimento",
    "costi",
    "prezzo",

    "mondo",
    "qui",
    "mercato",
    "italia",
    "estero",
    "online",

    "cliente",
    "il cliente",
    "clienti",
    "utente",
    "persona",
    "persone",
    "una persona",
    "gente",
    "founder",
    "ceo",
    "manager",
    "ragazzi",
    "qualcuno",
    "uno",
    "voi",
    "noi",
    "loro",
    "tutti",
    "nessuno",
    "chiunque",
    "ognuno",
    "secondo me",
    "insomma",
    "someone",
    "customer",
    "lead",
    "partner",
    "colleghi",
    "dipendenti",
    "candidato",
    "candidati",
    "il tipo",
    "la tipa",
    "il ragazzo",
    "la ragazza",
}



CHECKPOINT_FILE = NLP_DIR / "entity-boost-checkpoint.json"


def _load_checkpoint() -> dict:
    ""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_checkpoint(entities_mtime: float, stats: dict) -> None:
    ""
    data = {
        "entities_mtime": entities_mtime,
        "last_run": datetime.now(UTC).isoformat(),
        "stats": stats,
    }
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


def _should_skip(entities_path: Path) -> bool:
    ""
    ckpt = _load_checkpoint()
    if not ckpt.get("entities_mtime"):
        return False
    return entities_path.stat().st_mtime == ckpt["entities_mtime"]





def _build_person_lookup(people_df: pd.DataFrame) -> dict[str, str]:
    ""



    lookup: dict[str, str] = {}
    for _, row in people_df.iterrows():
        pid = row["person_id"]
        cname = str(row.get("canonical_name", "")).strip()
        if cname:
            lookup[cname.lower()] = pid


        aliases_raw = str(row.get("aliases", "")).strip()
        if aliases_raw and aliases_raw != "nan":
            for alias in aliases_raw.split("|"):
                alias = alias.strip()
                if alias:
                    lookup[alias.lower()] = pid

    return lookup


def _build_org_lookup(companies_df: pd.DataFrame) -> dict[str, str]:
    ""
    lookup: dict[str, str] = {}
    for _, row in companies_df.iterrows():
        rid = row.get("attio_record_id", "")
        if not rid:
            continue
        cname = str(row.get("company_name", "")).strip()
        if cname:
            lookup[cname.lower()] = rid

        domain = str(row.get("domain", "")).strip()
        if domain and domain != "nan":
            domain_name = domain.split(".")[0].lower()
            if domain_name and domain_name not in lookup:
                lookup[domain_name] = rid
    return lookup





def _fuzzy_match(
    name: str,
    lookup: dict[str, str],
    lookup_names: list[str],
    threshold: int = 85,
) -> str | None:
    ""




    from rapidfuzz import fuzz, process

    result = process.extractOne(
        name.lower(),
        lookup_names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold,
    )
    if result is not None:
        matched_name, _score, _idx = result
        return lookup[matched_name]
    return None





def resolve_entities(
    entities_df: pd.DataFrame,
    person_lookup: dict[str, str],
    org_lookup: dict[str, str],
    dry_run: bool = False,
) -> tuple[pd.DataFrame, dict]:
    ""



    stats = {
        "total_entities": len(entities_df),
        "person_total": 0,
        "person_already_resolved": 0,
        "person_noise_filtered": 0,
        "person_exact_match": 0,
        "person_fuzzy_match": 0,
        "org_total": 0,
        "org_already_resolved": 0,
        "org_noise_filtered": 0,
        "org_exact_match": 0,
        "org_fuzzy_match": 0,
    }


    if "resolved_person_id" not in entities_df.columns:
        entities_df["resolved_person_id"] = None
    if "resolved_org_id" not in entities_df.columns:
        entities_df["resolved_org_id"] = None


    person_names = list(person_lookup.keys())
    org_names = list(org_lookup.keys())



    person_mask = entities_df["entity_type"] == "person"
    person_entities = entities_df[person_mask]
    stats["person_total"] = len(person_entities)
    stats["person_already_resolved"] = int(person_entities["resolved_person_id"].notna().sum())


    unresolved_person_mask = person_mask & entities_df["resolved_person_id"].isna()
    unresolved_persons = entities_df.loc[unresolved_person_mask, "entity_text_normalized"]

    log.info(
        f"Person entities: {stats['person_total']} total, "
        f"{stats['person_already_resolved']} already resolved, "
        f"{len(unresolved_persons)} to process"
    )


    unique_person_names = unresolved_persons.dropna().unique()
    person_resolution_cache: dict[str, str | None] = {}
    person_noise_names: set[str] = set()

    for name_norm in unique_person_names:
        name_norm = str(name_norm).strip()
        if not name_norm or name_norm == "nan":
            continue


        if name_norm in NOISE_ENTITIES or len(name_norm) < 3:
            person_noise_names.add(name_norm)
            continue


        pid = person_lookup.get(name_norm)
        if pid:
            person_resolution_cache[name_norm] = pid
            continue


        if " " in name_norm:
            pid = _fuzzy_match(name_norm, person_lookup, person_names, threshold=85)
            if pid:
                person_resolution_cache[name_norm] = pid


    for idx in unresolved_persons.index:
        name_norm = str(entities_df.at[idx, "entity_text_normalized"]).strip()
        if name_norm in person_noise_names:
            stats["person_noise_filtered"] += 1
            continue
        pid = person_resolution_cache.get(name_norm)
        if pid:
            if not dry_run:
                entities_df.at[idx, "resolved_person_id"] = pid

            if name_norm in person_lookup:
                stats["person_exact_match"] += 1
            else:
                stats["person_fuzzy_match"] += 1



    org_mask = entities_df["entity_type"] == "organization"
    org_entities = entities_df[org_mask]
    stats["org_total"] = len(org_entities)
    stats["org_already_resolved"] = int(org_entities["resolved_org_id"].notna().sum())


    unresolved_org_mask = org_mask & entities_df["resolved_org_id"].isna()
    unresolved_orgs = entities_df.loc[unresolved_org_mask, "entity_text_normalized"]

    log.info(
        f"Org entities: {stats['org_total']} total, "
        f"{stats['org_already_resolved']} already resolved, "
        f"{len(unresolved_orgs)} to process"
    )


    unique_org_names = unresolved_orgs.dropna().unique()
    org_resolution_cache: dict[str, str | None] = {}
    org_noise_names: set[str] = set()

    for name_norm in unique_org_names:
        name_norm = str(name_norm).strip()
        if not name_norm or name_norm == "nan":
            continue


        if name_norm in NOISE_ENTITIES or len(name_norm) < 3:
            org_noise_names.add(name_norm)
            continue


        oid = org_lookup.get(name_norm)
        if oid:
            org_resolution_cache[name_norm] = oid
            continue


        oid = _fuzzy_match(name_norm, org_lookup, org_names, threshold=85)
        if oid:
            org_resolution_cache[name_norm] = oid


    for idx in unresolved_orgs.index:
        name_norm = str(entities_df.at[idx, "entity_text_normalized"]).strip()
        if name_norm in org_noise_names:
            stats["org_noise_filtered"] += 1
            continue
        oid = org_resolution_cache.get(name_norm)
        if oid:
            if not dry_run:
                entities_df.at[idx, "resolved_org_id"] = oid

            if name_norm in org_lookup:
                stats["org_exact_match"] += 1
            else:
                stats["org_fuzzy_match"] += 1

    return entities_df, stats





def _print_stats(stats: dict, elapsed: float) -> None:
    ""

    p_before = stats["person_already_resolved"]
    p_new = stats["person_exact_match"] + stats["person_fuzzy_match"]
    p_after = p_before + p_new
    p_total = stats["person_total"]
    p_pct_before = (p_before / p_total * 100) if p_total else 0
    p_pct_after = (p_after / p_total * 100) if p_total else 0


    o_before = stats["org_already_resolved"]
    o_new = stats["org_exact_match"] + stats["org_fuzzy_match"]
    o_after = o_before + o_new
    o_total = stats["org_total"]
    o_pct_before = (o_before / o_total * 100) if o_total else 0
    o_pct_after = (o_after / o_total * 100) if o_total else 0

    log.info("=" * 60)
    log.info("ENTITY RESOLUTION BOOST — RESULTS")
    log.info("=" * 60)
    log.info(f"Total entities:        {stats['total_entities']:,}")
    log.info(f"Elapsed:               {elapsed:.1f}s")
    log.info("-" * 60)
    log.info(f"PERSON entities:       {p_total:,}")
    log.info(f"  Already resolved:    {p_before:,} ({p_pct_before:.1f}%)")
    log.info(f"  Noise filtered:      {stats['person_noise_filtered']:,}")
    log.info(f"  New exact matches:   {stats['person_exact_match']:,}")
    log.info(f"  New fuzzy matches:   {stats['person_fuzzy_match']:,}")
    log.info(f"  After boost:         {p_after:,} ({p_pct_after:.1f}%)")
    log.info(f"  Delta:               +{p_new:,} (+{p_pct_after - p_pct_before:.1f}pp)")
    log.info("-" * 60)
    log.info(f"ORG entities:          {o_total:,}")
    log.info(f"  Already resolved:    {o_before:,} ({o_pct_before:.1f}%)")
    log.info(f"  Noise filtered:      {stats['org_noise_filtered']:,}")
    log.info(f"  New exact matches:   {stats['org_exact_match']:,}")
    log.info(f"  New fuzzy matches:   {stats['org_fuzzy_match']:,}")
    log.info(f"  After boost:         {o_after:,} ({o_pct_after:.1f}%)")
    log.info(f"  Delta:               +{o_new:,} (+{o_pct_after - o_pct_before:.1f}pp)")
    log.info("=" * 60)





def main():
    parser = argparse.ArgumentParser(
        description="SBK Entity Resolution Boost — fuzzy match entities to people/companies"
    )
    parser.add_argument("--force", action="store_true", help="Force reprocess even if unchanged")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    parser.add_argument("--stats", action="store_true", help="Show resolution stats only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-entity-boost")

    t0 = time.time()



    entities_path = NLP_DIR / "entities.parquet"
    if not entities_path.exists():
        log.error(f"entities.parquet not found at {entities_path}")
        sys.exit(1)


    if args.stats:
        df = pd.read_parquet(entities_path)
        persons = df[df["entity_type"] == "person"]
        orgs = df[df["entity_type"] == "organization"]
        p_resolved = int(persons["resolved_person_id"].notna().sum())
        o_resolved = int(orgs["resolved_org_id"].notna().sum())
        log.info(f"Total entities: {len(df):,}")
        log.info(
            f"PERSON: {len(persons):,} total, "
            f"{p_resolved:,} resolved ({p_resolved / len(persons) * 100:.1f}%)"
        )
        log.info(
            f"ORG:    {len(orgs):,} total, "
            f"{o_resolved:,} resolved ({o_resolved / len(orgs) * 100:.1f}%)"
        )
        sys.exit(0)


    if not args.force and _should_skip(entities_path):
        log.info("entities.parquet unchanged since last run — skipping (use --force to override)")
        sys.exit(0)

    log.info(f"Loading entities from {entities_path}")
    entities_df = pd.read_parquet(entities_path)
    log.info(f"Loaded {len(entities_df):,} entities")



    people_path = ENRICHED_DIR / "people-universe.parquet"
    if not people_path.exists():
        log.warning(f"people-universe.parquet not found at {people_path} — skipping person boost")
        person_lookup: dict[str, str] = {}
    else:
        log.info(f"Loading people-universe from {people_path}")
        people_df = pd.read_parquet(people_path)
        log.info(f"Loaded {len(people_df):,} people")
        person_lookup = _build_person_lookup(people_df)
        log.info(f"Person lookup: {len(person_lookup):,} name variants")



    companies_path = ATTIO_PROCESSED_DIR / "companies-attio.parquet"
    if not companies_path.exists():
        log.warning(f"companies-attio.parquet not found at {companies_path} — skipping org boost")
        org_lookup: dict[str, str] = {}
    else:
        log.info(f"Loading companies-attio from {companies_path}")
        companies_df = pd.read_parquet(companies_path)
        log.info(f"Loaded {len(companies_df):,} companies")
        org_lookup = _build_org_lookup(companies_df)
        log.info(f"Org lookup: {len(org_lookup):,} name variants")



    if not person_lookup and not org_lookup:
        log.warning("No lookup data available — nothing to do")
        sys.exit(0)

    entities_df, stats = resolve_entities(
        entities_df, person_lookup, org_lookup, dry_run=args.dry_run
    )

    elapsed = time.time() - t0
    _print_stats(stats, elapsed)



    total_new = (
        stats["person_exact_match"]
        + stats["person_fuzzy_match"]
        + stats["org_exact_match"]
        + stats["org_fuzzy_match"]
    )

    if args.dry_run:
        log.info("DRY RUN — no changes written")
    elif total_new == 0:
        log.info("No new resolutions found — file unchanged")
    else:
        log.info(f"Writing {total_new:,} new resolutions to {entities_path}")
        safe_write_parquet(entities_df, entities_path, index=False)
        log.info("entities.parquet updated")


    if not args.dry_run:
        _save_checkpoint(entities_path.stat().st_mtime, stats)

    log.info("Done")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-entity-boost", source="l2-entity-boost", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
