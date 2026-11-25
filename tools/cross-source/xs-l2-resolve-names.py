#!/usr/bin/env python3
""






















from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from text_utils import normalize_phone

from sbk_config import (
    ATTIO_PROCESSED_DIR,
    ENRICHED_DIR,
    IPHONE_DIR,
    RELATIONSHIP_FACTS_FILE,
    SLACK_DIR,
    WHATSAPP_DIR,
)

log = logging.getLogger("resolve-names")

ENTITY_MAP_FILE = ENRICHED_DIR / "entity-map.json"





def load_entity_map() -> dict:
    ""
    if not ENTITY_MAP_FILE.exists():
        log.error(f"Entity map not found: {ENTITY_MAP_FILE}")
        return {}
    return json.loads(ENTITY_MAP_FILE.read_text())


def save_entity_map(entity_map: dict) -> None:
    ""
    import shutil

    if ENTITY_MAP_FILE.exists():
        backup = ENTITY_MAP_FILE.with_suffix(".json.bak")
        shutil.copy2(ENTITY_MAP_FILE, backup)
    tmp_file = ENTITY_MAP_FILE.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(entity_map, indent=2, ensure_ascii=False))
    tmp_file.replace(ENTITY_MAP_FILE)
    log.info(f"Updated entity-map.json ({len(entity_map)} entries)")


def count_resolved(entity_map: dict) -> dict:
    ""
    total = len(entity_map)
    with_pid = sum(1 for v in entity_map.values() if v.get("person_id"))
    nameonly = sum(1 for k in entity_map if k.startswith("nameonly:"))
    phone_keys = sum(1 for k in entity_map if k.startswith("phone:"))
    email_keys = sum(1 for k in entity_map if "@" in k)
    return {
        "total_entries": total,
        "with_person_id": with_pid,
        "nameonly_keys": nameonly,
        "phone_keys": phone_keys,
        "email_keys": email_keys,
        "resolution_rate": with_pid / max(total, 1) * 100,
    }





def strategy_phone_resolution(entity_map: dict, dry_run: bool = False) -> int:
    ""

    iphone_file = IPHONE_DIR / "contacts-iphone.parquet"
    if not iphone_file.exists():
        log.warning(f"iPhone contacts not found: {iphone_file}")
        return 0

    iphone_df = pd.read_parquet(iphone_file)
    if "phone" not in iphone_df.columns:
        log.warning("iPhone contacts have no phone column")
        return 0


    phone_to_info: dict[str, dict] = {}
    for _, row in iphone_df.iterrows():
        phone_raw = str(row.get("phone", ""))
        if not phone_raw or phone_raw == "nan":
            continue
        normalized = normalize_phone(phone_raw)
        if not normalized:
            continue
        name = str(row.get("name", ""))
        email = str(row.get("email", ""))

        pid = None
        if email and email != "nan" and email in entity_map:
            pid = entity_map[email].get("person_id")
        phone_to_info[normalized] = {"name": name, "email": email, "person_id": pid}

    log.info(f"  Phone index: {len(phone_to_info)} iPhone contacts with phones")


    wa_file = WHATSAPP_DIR / "contacts-whatsapp.parquet"
    if not wa_file.exists():
        log.warning(f"WhatsApp contacts not found: {wa_file}")
        return 0

    wa_df = pd.read_parquet(wa_file)
    matches = 0

    for _, row in wa_df.iterrows():
        wa_phone = str(row.get("phone", ""))
        if not wa_phone or wa_phone == "nan":
            continue
        wa_normalized = normalize_phone(wa_phone)
        if not wa_normalized:
            continue

        if wa_normalized in phone_to_info:
            info = phone_to_info[wa_normalized]
            if not info.get("person_id"):
                continue


            wa_name = str(row.get("name", "")).strip()
            wa_key = f"nameonly:whatsapp:{wa_name.lower()}"

            if wa_key in entity_map:
                existing_pid = entity_map[wa_key].get("person_id", "")
                if existing_pid and existing_pid != info["person_id"]:
                    continue
                if existing_pid == info["person_id"]:
                    continue

                if not dry_run:
                    entity_map[wa_key]["person_id"] = info["person_id"]
                    entity_map[wa_key].setdefault("resolution_sources", [])
                    if "phone" not in entity_map[wa_key]["resolution_sources"]:
                        entity_map[wa_key]["resolution_sources"].append("phone")
                    entity_map[wa_key].setdefault("phone_numbers", [])
                    if wa_normalized not in entity_map[wa_key]["phone_numbers"]:
                        entity_map[wa_key]["phone_numbers"].append(wa_normalized)
                matches += 1


            phone_key = f"phone:{wa_normalized}"
            if phone_key in entity_map and not entity_map[phone_key].get("person_id"):
                if not dry_run:
                    entity_map[phone_key]["person_id"] = info["person_id"]
                    entity_map[phone_key].setdefault("resolution_sources", []).append("phone")
                matches += 1

    log.info(f"  Strategy 1 (phone): {matches} new resolutions")
    return matches





def strategy_slack_resolution(entity_map: dict, dry_run: bool = False) -> int:
    ""
    slack_contacts_file = SLACK_DIR / "contacts-slack.parquet"
    if not slack_contacts_file.exists():
        log.warning(f"Slack contacts not found: {slack_contacts_file}")
        return 0

    slack_df = pd.read_parquet(slack_contacts_file)
    matches = 0


    for _, row in slack_df.iterrows():
        email = str(row.get("email", ""))
        if not email or email == "nan" or "@" not in email:
            continue
        real_name = str(row.get("real_name", "") or row.get("display_name", "")).strip()
        if not real_name:
            continue


        if email.lower() not in entity_map:
            continue
        pid = entity_map[email.lower()].get("person_id")
        if not pid:
            continue


        slack_key = f"nameonly:slack:{real_name.lower()}"
        if slack_key in entity_map:
            existing_pid = entity_map[slack_key].get("person_id", "")
            if existing_pid == pid:
                continue
            if existing_pid and existing_pid != pid:
                continue

            if not dry_run:
                entity_map[slack_key]["person_id"] = pid
                entity_map[slack_key].setdefault("resolution_sources", [])
                if "slack_email" not in entity_map[slack_key]["resolution_sources"]:
                    entity_map[slack_key]["resolution_sources"].append("slack_email")
            matches += 1

    log.info(f"  Strategy 2 (slack): {matches} new resolutions")
    return matches





def strategy_relationship_transitivity(entity_map: dict, dry_run: bool = False) -> int:
    ""




    if not RELATIONSHIP_FACTS_FILE.exists():
        log.info("  Strategy 3 (relationship): No relationship facts available, skipping")
        return 0

    facts_df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
    if facts_df.empty:
        return 0

    matches = 0


    resolved_names: dict[str, str] = {}
    for key, entry in entity_map.items():
        pid = entry.get("person_id", "")
        name = entry.get("canonical_name", "").lower().strip()
        if pid and name:
            resolved_names[name] = pid


    for _, fact in facts_df.iterrows():
        subject = str(fact.get("subject", "")).strip()
        obj = str(fact.get("object", "")).strip()
        subject_pid = str(fact.get("subject_person_id", ""))
        object_pid = str(fact.get("object_person_id", ""))

        if not subject or not obj:
            continue


        if subject_pid and not object_pid:
            obj_lower = obj.lower()
            for key in entity_map:
                if key.startswith("nameonly:") and not entity_map[key].get("person_id"):
                    entry_name = entity_map[key].get("canonical_name", "").lower()
                    if entry_name == obj_lower or key.endswith(f":{obj_lower}"):


                        if obj_lower in resolved_names:
                            if not dry_run:
                                entity_map[key]["person_id"] = resolved_names[obj_lower]
                                entity_map[key].setdefault("resolution_sources", []).append(
                                    "relationship_fact"
                                )
                            matches += 1
                            break


        if object_pid and not subject_pid:
            subj_lower = subject.lower()
            for key in entity_map:
                if key.startswith("nameonly:") and not entity_map[key].get("person_id"):
                    entry_name = entity_map[key].get("canonical_name", "").lower()
                    if entry_name == subj_lower or key.endswith(f":{subj_lower}"):
                        if subj_lower in resolved_names:
                            if not dry_run:
                                entity_map[key]["person_id"] = resolved_names[subj_lower]
                                entity_map[key].setdefault("resolution_sources", []).append(
                                    "relationship_fact"
                                )
                            matches += 1
                            break

    log.info(f"  Strategy 3 (relationship): {matches} new resolutions")
    return matches





def strategy_context_org_resolution(entity_map: dict, dry_run: bool = False) -> int:
    ""






    contacts_file = ENRICHED_DIR / "contacts-merged.parquet"
    if not contacts_file.exists():
        return 0

    contacts = pd.read_parquet(contacts_file)
    pid_to_org: dict[str, str] = {}
    name_to_pids: dict[str, list[str]] = defaultdict(list)

    for _, row in contacts.iterrows():
        pid = str(row.get("person_id", ""))
        org = str(row.get("organization", "") or "")
        name = str(row.get("name", "")).strip().lower()
        if pid and name:
            name_to_pids[name].append(pid)
            if org and org != "nan":
                pid_to_org[pid] = org.lower()

            first_name = name.split()[0] if name else ""
            if first_name and first_name != name:
                name_to_pids[first_name].append(pid)

    matches = 0


    for key, entry in list(entity_map.items()):
        if not key.startswith("nameonly:"):
            continue
        if entry.get("person_id"):
            continue

        name = entry.get("canonical_name", "").lower().strip()
        if not name or " " in name:
            continue


        candidates = name_to_pids.get(name, [])
        if len(candidates) != 1:
            continue


        pid = candidates[0]
        if not dry_run:
            entry["person_id"] = pid
            entry.setdefault("resolution_sources", []).append("context_org")
        matches += 1

    log.info(f"  Strategy 4 (context): {matches} new resolutions")
    return matches





def strategy_attio_crossref(entity_map: dict, dry_run: bool = False) -> int:
    ""
    attio_file = ATTIO_PROCESSED_DIR / "contacts-attio.parquet"
    if not attio_file.exists():
        log.warning(f"Attio contacts not found: {attio_file}")
        return 0

    attio_df = pd.read_parquet(attio_file)
    matches = 0


    attio_name_to_email: dict[str, str] = {}
    for _, row in attio_df.iterrows():
        name = str(row.get("name", "")).strip().lower()
        email = str(row.get("email", ""))
        if name and email and email != "nan" and "@" in email:
            attio_name_to_email[name] = email.lower()


    for key, entry in list(entity_map.items()):
        if not key.startswith("nameonly:"):
            continue
        if entry.get("person_id"):
            continue

        name = entry.get("canonical_name", "").lower().strip()
        if not name:
            continue


        if name in attio_name_to_email:
            attio_email = attio_name_to_email[name]
            if attio_email in entity_map:
                pid = entity_map[attio_email].get("person_id")
                if pid:
                    if not dry_run:
                        entry["person_id"] = pid
                        entry.setdefault("resolution_sources", []).append("attio_crossref")
                    matches += 1

    log.info(f"  Strategy 5 (attio): {matches} new resolutions")
    return matches




STRATEGIES = {
    "phone": strategy_phone_resolution,
    "slack": strategy_slack_resolution,
    "relationship": strategy_relationship_transitivity,
    "context": strategy_context_org_resolution,
    "attio": strategy_attio_crossref,
}


def main():
    parser = argparse.ArgumentParser(description="SBK Advanced Name Resolution")
    parser.add_argument("--dry-run", action="store_true", help="Count matches without modifying")
    parser.add_argument("--report", action="store_true", help="Print resolution report")
    parser.add_argument("--all", action="store_true", help="Run all 5 strategies")
    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES.keys()),
        help="Run a single strategy",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    entity_map = load_entity_map()
    if not entity_map:
        return

    before = count_resolved(entity_map)
    log.info(
        f"Before: {before['with_person_id']}/{before['total_entries']} resolved ({before['resolution_rate']:.1f}%)"
    )

    if args.report and not args.all and not args.strategy:

        stats = before
        print(f"\n{'=' * 60}")
        print("ENTITY MAP RESOLUTION REPORT")
        print(f"{'=' * 60}")
        for k, v in stats.items():
            print(f"  {k:25s}: {v}")
        return

    strategies_to_run = []
    if args.all:
        strategies_to_run = list(STRATEGIES.keys())
    elif args.strategy:
        strategies_to_run = [args.strategy]
    else:
        parser.print_help()
        print("\nUse --all to run all strategies, or --strategy <name> for one.")
        return

    total_matches = 0
    for name in strategies_to_run:
        log.info(f"\nRunning strategy: {name}")
        matches = STRATEGIES[name](entity_map, dry_run=args.dry_run)
        total_matches += matches

    after = count_resolved(entity_map)

    log.info(f"\n{'=' * 60}")
    log.info("SUMMARY")
    log.info(f"{'=' * 60}")
    log.info(
        f"Before: {before['resolution_rate']:.1f}% ({before['with_person_id']}/{before['total_entries']})"
    )
    log.info(
        f"After:  {after['resolution_rate']:.1f}% ({after['with_person_id']}/{after['total_entries']})"
    )
    log.info(f"New resolutions: {total_matches}")
    log.info(f"{'=' * 60}")

    if not args.dry_run and total_matches > 0:
        save_entity_map(entity_map)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-resolve-names", source="l2-resolve-names", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
