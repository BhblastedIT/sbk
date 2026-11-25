#!/usr/bin/env python3
""






















import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import ENRICHED_DIR

DATA_DIR = ENRICHED_DIR
INPUT_FILE = DATA_DIR / "entity-review-enriched.json"
DECISIONS_FILE = DATA_DIR / "entity-decisions.json"


def load_enriched_review():
    ""
    if not INPUT_FILE.exists():
        print(f"ERRORE: {INPUT_FILE} non trovato. Eseguire xs-l3-enrich-review.py prima.")
        sys.exit(1)

    with open(INPUT_FILE) as f:
        items = json.load(f)
    print(f"Caricati {len(items)} items da entity-review-enriched.json")
    return items


def load_existing_decisions():
    ""
    if not DECISIONS_FILE.exists():
        return {"version": 1, "created": datetime.now(UTC).isoformat(), "decisions": []}

    with open(DECISIONS_FILE) as f:
        data = json.load(f)
    print(f"Decisioni esistenti: {len(data.get('decisions', []))} entries")
    return data


def get_item_keys(item):
    ""
    return item.get("keys", item.get("emails", []))


def already_decided(item, existing_keys_set):
    ""
    keys = get_item_keys(item)
    if len(keys) >= 2:
        pair = frozenset(keys[:2])
        return pair in existing_keys_set
    return False


def apply_rules(items, existing_keys_set):
    ""
    new_decisions = []
    stats = {
        "rule1_linkedin_merge": 0,
        "rule2_phone_merge": 0,
        "rule3_score90_merge": 0,
        "rule4_linkedin_reject": 0,
        "rule5_surname_reject": 0,
        "rule6_score30_reject": 0,
        "skipped_already_decided": 0,
        "uncovered": 0,
    }

    now = datetime.now(UTC).isoformat()

    for item in items:
        keys = get_item_keys(item)
        if len(keys) < 2:
            stats["uncovered"] += 1
            continue

        if already_decided(item, existing_keys_set):
            stats["skipped_already_decided"] += 1
            continue

        auto_decision = item.get("auto_decision") or ""
        auto_reason = str(item.get("auto_reason") or "")
        match_score = item.get("match_score", 0) or 0
        surname_analysis = item.get("surname_analysis") or {}
        assessment = surname_analysis.get("assessment", "")
        edit_distance = surname_analysis.get("edit_distance", 0) or 0

        decision = None


        if auto_decision == "merge" and "Stesso profilo LinkedIn" in auto_reason:
            decision = {
                "keys": list(keys[:2]),
                "action": "merge",
                "decided_at": now,
                "source": "auto_linkedin",
                "reason": "Stesso profilo LinkedIn (auto_decision=merge)",
            }
            stats["rule1_linkedin_merge"] += 1


        elif auto_decision == "merge" and "Stesso telefono" in auto_reason:
            decision = {
                "keys": list(keys[:2]),
                "action": "merge",
                "decided_at": now,
                "source": "auto_phone",
                "reason": "Stesso telefono (auto_decision=merge)",
            }
            stats["rule2_phone_merge"] += 1


        elif match_score >= 90 and assessment != "diversi":
            decision = {
                "keys": list(keys[:2]),
                "action": "merge",
                "decided_at": now,
                "source": "auto_match_score",
                "reason": f"match_score={match_score}, cognomi={assessment or 'N/A'}",
            }
            stats["rule3_score90_merge"] += 1


        elif auto_decision == "reject" and "Profili LinkedIn diversi" in auto_reason:
            decision = {
                "keys": list(keys[:2]),
                "action": "reject",
                "decided_at": now,
                "source": "auto_linkedin_reject",
                "reason": "Profili LinkedIn diversi (auto_decision=reject)",
            }
            stats["rule4_linkedin_reject"] += 1


        elif assessment == "diversi" and edit_distance >= 4:

            if auto_decision == "merge" and (
                "LinkedIn" in auto_reason or "telefono" in auto_reason
            ):
                stats["uncovered"] += 1
                continue
            decision = {
                "keys": list(keys[:2]),
                "action": "reject",
                "decided_at": now,
                "source": "auto_surname_reject",
                "reason": (
                    f"Cognomi diversi: {surname_analysis.get('surnameA', '?')} vs "
                    f"{surname_analysis.get('surnameB', '?')} (edit_distance={edit_distance})"
                ),
            }
            stats["rule5_surname_reject"] += 1


        elif match_score < 30:
            decision = {
                "keys": list(keys[:2]),
                "action": "reject",
                "decided_at": now,
                "source": "auto_low_score",
                "reason": f"match_score={match_score} troppo basso",
            }
            stats["rule6_score30_reject"] += 1

        else:
            stats["uncovered"] += 1
            continue

        if decision:
            new_decisions.append(decision)

    return new_decisions, stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Auto-apply entity resolution decisions")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing")
    args = parser.parse_args()

    items = load_enriched_review()
    existing = load_existing_decisions()


    existing_keys_set = set()
    for d in existing.get("decisions", []):
        dk = d.get("keys", [])
        if len(dk) >= 2:
            existing_keys_set.add(frozenset(dk[:2]))

    new_decisions, stats = apply_rules(items, existing_keys_set)


    total_merge = (
        stats["rule1_linkedin_merge"] + stats["rule2_phone_merge"] + stats["rule3_score90_merge"]
    )
    total_reject = (
        stats["rule4_linkedin_reject"]
        + stats["rule5_surname_reject"]
        + stats["rule6_score30_reject"]
    )

    print(f"\n{'=' * 60}")
    print("ENTITY RESOLUTION AUTO-DECISIONS")
    print(f"{'=' * 60}")
    print(f"\nInput: {len(items)} items in review queue")
    print(f"Gia' decisi (skip): {stats['skipped_already_decided']}")
    print(f"\nMERGE ({total_merge} items):")
    print(f"  Rule 1 (stesso LinkedIn):    {stats['rule1_linkedin_merge']}")
    print(f"  Rule 2 (stesso telefono):    {stats['rule2_phone_merge']}")
    print(f"  Rule 3 (match_score>=90):    {stats['rule3_score90_merge']}")
    print(f"\nREJECT ({total_reject} items):")
    print(f"  Rule 4 (LinkedIn diversi):   {stats['rule4_linkedin_reject']}")
    print(f"  Rule 5 (cognomi diversi):    {stats['rule5_surname_reject']}")
    print(f"  Rule 6 (score < 30):         {stats['rule6_score30_reject']}")
    print(f"\nTotale auto-decisi: {total_merge + total_reject}")
    print(f"Residuo manual review: {stats['uncovered']}")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n[DRY RUN] Nessun file scritto.")


        merges = [d for d in new_decisions if d["action"] == "merge"]
        rejects = [d for d in new_decisions if d["action"] == "reject"]

        if merges:
            print("\nEsempi MERGE (primi 5):")
            for d in merges[:5]:
                print(f"  {d['keys']}  ({d['source']}: {d['reason']})")

        if rejects:
            print("\nEsempi REJECT (primi 5):")
            for d in rejects[:5]:
                print(f"  {d['keys']}  ({d['source']}: {d['reason']})")

        return


    existing["decisions"].extend(new_decisions)
    existing["last_updated"] = datetime.now(UTC).isoformat()


    DECISIONS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"\nScritto: {DECISIONS_FILE}")
    print(f"Totale decisioni nel file: {len(existing['decisions'])}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-apply-decisions", source="l2-apply-decisions", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
