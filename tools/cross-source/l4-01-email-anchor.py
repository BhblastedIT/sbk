#!/usr/bin/env python3
"""L4-01: merges the person entities that share an email address (generic mailboxes excluded) into one canonical
entity, archiving the merged ones. Dry run by default; --apply executes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    KNOWLEDGE_ENTITIES_DIR,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from freno_massa import verifica_quota  # noqa: E402
from journal_fusioni import Journal  # noqa: E402

log = logging.getLogger("sbk-l4-01-email-anchor")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ARCHIVE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "merged"
RUN_LOG = QUALITY_METRICS_DIR / "l4-01-run-log.jsonl"


GENERIC_PREFIXES = {
    "info",
    "support",
    "hello",
    "noreply",
    "admin",
    "contact",
    "team",
    "help",
    "sales",
    "hr",
    "accounting",
    "office",
    "marketing",
    "dev",
    "engineering",
    "operations",
    "legal",
    "finance",
    "ceo",
    "founder",
    "no-reply",
    "notifications",
}

MIN_EMAIL_CONFIDENCE = 0.85





def scan_email_clusters() -> dict[str, list[dict]]:
    ""
    email_to_entities: dict[str, list[dict]] = defaultdict(list)

    for f in PERSON_DIR.iterdir():
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entity_id = data.get("entity_id", "")
            canonical = data.get("canonical_name", "")
            facts = data.get("facts", [])
            if not entity_id:
                continue

            for fact in facts:
                attr = fact.get("attribute", "")
                if attr not in ("contact.email", "identity.email"):
                    continue
                if fact.get("confidence", 0) < MIN_EMAIL_CONFIDENCE:
                    continue
                email = str(fact.get("value", "")).strip().lower()
                if not email or "@" not in email:
                    continue
                prefix = email.split("@")[0]
                if prefix in GENERIC_PREFIXES:
                    continue
                email_to_entities[email].append(
                    {
                        "entity_id": entity_id,
                        "canonical_name": canonical,
                        "fact_count": len(facts),
                        "file_path": str(f),
                        "high_conf_facts": sum(1 for ff in facts if ff.get("confidence", 0) >= 0.7),
                    }
                )
                break

        except (json.JSONDecodeError, OSError):
            continue


    return {email: ents for email, ents in email_to_entities.items() if len(ents) > 1}





def select_canonical(entities: list[dict]) -> dict:
    ""





    def quality_score(e: dict) -> tuple[float, int, int]:
        total = e["fact_count"]
        high_conf = e["high_conf_facts"]
        ratio = high_conf / total if total > 0 else 0
        weighted = total * (0.5 + 0.5 * ratio)
        name_len = len(e.get("canonical_name", ""))
        return (weighted, name_len, total)

    return max(entities, key=quality_score)


def merge_facts(
    canonical_facts: list[dict],
    incoming_facts: list[dict],
    canonical_id: str = "",
    journal=None,
    da: str = "",
) -> list[dict]:
    ""




    existing = set()
    for f in canonical_facts:
        key = (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
        existing.add(key)

    added = 0
    for f in incoming_facts:
        key = (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
        if key not in existing:
            merged = dict(f)
            if canonical_id:
                merged["source_entity_id"] = f.get("entity_id")
                merged["entity_id"] = canonical_id
            canonical_facts.append(merged)
            existing.add(key)
            added += 1
            if journal is not None:
                journal.fatto(f, da=da or f.get("entity_id", ""), a=canonical_id)
        elif journal is not None:





            journal.fatto_scartato(
                f, da=da or f.get("entity_id", ""), perche="duplicato (attributo,valore)"
            )

    return canonical_facts


def execute_merge(
    email: str,
    entities: list[dict],
    dry_run: bool = True,
    journal=None,
) -> dict | None:
    ""



    canonical_info = select_canonical(entities)
    canonical_id = canonical_info["entity_id"]
    non_canonical = [e for e in entities if e["entity_id"] != canonical_id]

    if not non_canonical:
        return None


    canonical_path = Path(canonical_info["file_path"])
    if not canonical_path.exists():
        log.warning("Canonical entity file missing: %s", canonical_path)
        return None

    canonical_data = json.loads(canonical_path.read_text(encoding="utf-8"))
    original_fact_count = len(canonical_data.get("facts", []))
    merged_ids = []

    for non_can in non_canonical:
        nc_path = Path(non_can["file_path"])
        if not nc_path.exists():
            continue

        nc_data = json.loads(nc_path.read_text(encoding="utf-8"))







        if journal is not None:
            journal.fusione(
                canonical_data.get("entity_id", ""),
                non_can["entity_id"],
                motivo=f"email condivisa: {email}",
                punteggi={
                    "canonico": canonical_info.get("quality_score"),
                    "fuso": non_can.get("quality_score"),
                },
            )


        nc_name = nc_data.get("canonical_name", "")
        can_name = canonical_data.get("canonical_name", "")
        if (
            len(nc_name) > len(can_name)
            and not nc_name.startswith("person_")
            and "@" not in nc_name
        ):
            canonical_data["canonical_name"] = nc_name


        canonical_data["facts"] = merge_facts(
            canonical_data.get("facts", []),
            nc_data.get("facts", []),
            canonical_id=canonical_data.get("entity_id", ""),
            journal=journal,
            da=non_can["entity_id"],
        )

        merged_ids.append(non_can["entity_id"])

        if not dry_run:

            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            archive_data = {
                **nc_data,
                "status": "merged",
                "merged_into": canonical_id,
                "merged_date": datetime.now(UTC).isoformat(),
                "merged_by": "l4-01-email-anchor",
                "merge_reason": f"shared email: {email}",
            }
            archive_path = ARCHIVE_DIR / nc_path.name
            safe_write_json(archive_path, archive_data)


            nc_path.unlink()

    new_fact_count = len(canonical_data.get("facts", []))

    if not dry_run:

        safe_write_json(canonical_path, canonical_data, backup=True)

    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "module": "l4-01-email-anchor",
        "action": "merge",
        "email": email,
        "canonical_id": canonical_id,
        "canonical_name": canonical_data.get("canonical_name", ""),
        "merged_ids": merged_ids,
        "facts_before": original_fact_count,
        "facts_after": new_fact_count,
        "facts_gained": new_fact_count - original_fact_count,
        "dry_run": dry_run,
    }

    action = "DRY-RUN" if dry_run else "MERGED"
    log.info(
        "%s: %s → %s (%s) [+%d facts, merged %d entities]",
        action,
        email,
        canonical_id,
        canonical_data.get("canonical_name", "?"),
        new_fact_count - original_fact_count,
        len(merged_ids),
    )

    return log_entry





def main():
    parser = argparse.ArgumentParser(description="L4-01: Email Anchor Merge")
    parser.add_argument("--apply", action="store_true", help="Execute merges (default: dry-run)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    dry_run = not args.apply

    log.info("=" * 60)
    log.info("L4-01 Email Anchor Merge — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)


    log.info("Scanning email clusters...")
    clusters = scan_email_clusters()
    total_entities = sum(len(ents) for ents in clusters.values())
    log.info("Found %d clusters with %d entities", len(clusters), total_entities)

    if not clusters:
        log.info("No email clusters found. Nothing to merge.")
        return


    results = []
    merged_count = 0
    facts_gained = 0






    _da_toccare = sum(len(e) - 1 for e in clusters.values())
    verifica_quota(_da_toccare, total_entities or 1, "l4-01 merge per email")

    with Journal("l4-01-email-anchor", attivo=not dry_run) as journal:
        for email, entities in sorted(clusters.items()):
            result = execute_merge(email, entities, dry_run=dry_run, journal=journal)
            if result:
                results.append(result)
                merged_count += len(result["merged_ids"])
                facts_gained += result["facts_gained"]
        if journal.percorso:
            log.info("merge journal: %s", journal.percorso)
            log.info(
                "per tornare indietro: xs-l4-disfa-fusione.py --journal %s --apply",
                journal.percorso.name,
            )


    if results and not dry_run:
        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Clusters processed: %d", len(results))
    log.info("  Entities merged: %d", merged_count)
    log.info("  Facts gained: %d", facts_gained)
    if dry_run:
        log.info("")
        log.info("  Run with --apply to execute merges.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
