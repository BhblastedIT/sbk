#!/usr/bin/env python3
"""Annotation of the relationship facts: saves the high-confidence ones automatically (--auto), lets you review the
uncertain ones (--review), shows a person's facts or the statistics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from xs_l3_common import setup_logging

from sbk_config import (
    CONFIDENZA_ALTA,
    PERSON_ANNOTATIONS_FILE,
    RELATIONSHIP_FACTS_FILE,
    check_inputs_changed,
    confidenza_almeno,
    mark_last_run,
    save_input_checkpoint,
)

log = logging.getLogger("sbk-annotate")





def load_annotations() -> dict:
    ""





    if PERSON_ANNOTATIONS_FILE.exists():
        try:
            data = json.loads(PERSON_ANNOTATIONS_FILE.read_text())
            if isinstance(data, dict):
                return data
            if isinstance(data, list):


                log.info(
                    f"Legacy list format in {PERSON_ANNOTATIONS_FILE} ({len(data)} items). "
                    "Using empty dict for fact annotations."
                )
                return {"_legacy_notes": data}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_annotations(annotations: dict) -> None:
    ""
    PERSON_ANNOTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERSON_ANNOTATIONS_FILE.write_text(json.dumps(annotations, ensure_ascii=False, indent=2))
    log.info(f"Saved annotations for {len(annotations)} persons to {PERSON_ANNOTATIONS_FILE}")


def load_facts() -> pd.DataFrame:
    ""
    if not RELATIONSHIP_FACTS_FILE.exists():
        log.error(f"No relationship facts found at {RELATIONSHIP_FACTS_FILE}")
        log.error("Run xs-l3-extract-relationships.py --batch first.")
        return pd.DataFrame()
    return pd.read_parquet(RELATIONSHIP_FACTS_FILE)





def auto_annotate(facts: pd.DataFrame, annotations: dict) -> dict:
    ""


    high_conf = facts[confidenza_almeno(facts["confidence"], CONFIDENZA_ALTA)]
    added = 0

    for _, fact in high_conf.iterrows():
        subject = str(fact.get("subject", "")).strip()
        if not subject:
            continue
        key = subject.lower()

        if key not in annotations:
            annotations[key] = {"name": subject, "facts": [], "manual_notes": []}


        fact_entry = {
            "predicate": fact.get("predicate", ""),
            "object": fact.get("object", ""),
            "fact_type": fact.get("fact_type", ""),
            "source_type": fact.get("source_type", ""),
            "source_date": fact.get("source_date", ""),
            "context": fact.get("context", ""),
            "fact_id": fact.get("fact_id", ""),
        }


        existing_ids = {f.get("fact_id") for f in annotations[key].get("facts", [])}
        if fact_entry["fact_id"] not in existing_ids:
            annotations[key].setdefault("facts", []).append(fact_entry)
            added += 1

    log.info(f"Auto-annotated: {added} new high-confidence facts added")
    return annotations





def review_facts(facts: pd.DataFrame, annotations: dict) -> dict:
    ""
    review_pool = facts[facts["confidence"].isin(["medium", "low"])]

    if review_pool.empty:
        log.info("No medium/low confidence facts to review.")
        return annotations

    log.info("%d facts to review. Commands: [y]es, [n]o, [s]kip, [q]uit", len(review_pool))

    for i, (_, fact) in enumerate(review_pool.iterrows()):
        subject = fact.get("subject", "")
        predicate = fact.get("predicate", "")
        obj = fact.get("object", "")
        context = fact.get("context", "")
        confidence = fact.get("confidence", "")
        source = fact.get("source_type", "")

        log.info("[%d/%d] (%s, %s)", i + 1, len(review_pool), confidence, source)
        log.info("  %s -> %s -> %s", subject, predicate, obj)
        if context:
            log.info('  Context: "%s"', context)

        try:
            answer = input("  Accept? [y/n/s/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            log.info("Exiting review.")
            break

        if answer == "q":
            break
        elif answer == "y":
            key = subject.lower()
            if key not in annotations:
                annotations[key] = {"name": subject, "facts": [], "manual_notes": []}
            fact_entry = {
                "predicate": predicate,
                "object": obj,
                "fact_type": fact.get("fact_type", ""),
                "source_type": source,
                "source_date": fact.get("source_date", ""),
                "context": context,
                "fact_id": fact.get("fact_id", ""),
                "reviewed": True,
            }
            existing_ids = {f.get("fact_id") for f in annotations[key].get("facts", [])}
            if fact_entry["fact_id"] not in existing_ids:
                annotations[key]["facts"].append(fact_entry)
                log.info("  Added")
        elif answer == "n":
            log.info("  Skipped")

    return annotations





def show_person_facts(facts: pd.DataFrame, person_name: str) -> None:
    ""
    name_lower = person_name.lower()


    subject_match = facts["subject"].fillna("").str.lower().str.contains(name_lower, na=False)
    object_match = facts["object"].fillna("").str.lower().str.contains(name_lower, na=False)
    person_facts = facts[subject_match | object_match]

    if person_facts.empty:
        log.info("No facts found for '%s'", person_name)
        return

    log.info("=" * 60)
    log.info("Facts for: %s (%d facts)", person_name, len(person_facts))
    log.info("=" * 60)

    for ft in ["relationship_fact", "personal_detail", "introduction", "need"]:
        subset = person_facts[person_facts["fact_type"] == ft]
        if subset.empty:
            continue
        log.info("  %s:", ft.upper().replace("_", " "))
        for _, fact in subset.iterrows():
            conf = fact.get("confidence", "")
            src = fact.get("source_type", "")
            log.info(
                "    [%6s] %s -> %s -> %s", conf, fact["subject"], fact["predicate"], fact["object"]
            )
            ctx = fact.get("context", "")
            if ctx:
                log.info('             "%s"  (%s, %s)', ctx, src, fact.get("source_date", ""))





def show_stats(facts: pd.DataFrame) -> None:
    ""
    log.info("=" * 60)
    log.info("RELATIONSHIP FACTS STATISTICS")
    log.info("=" * 60)
    log.info("Total facts: %d", len(facts))

    log.info("By fact type:")
    for ft, count in facts["fact_type"].value_counts().items():
        log.info("  %s: %d", f"{ft:25s}", count)

    log.info("By source:")
    for src, count in facts["source_type"].value_counts().items():
        log.info("  %s: %d", f"{src:25s}", count)

    log.info("By confidence:")
    for conf, count in facts["confidence"].value_counts().items():
        log.info("  %s: %d", f"{conf:25s}", count)

    log.info("Top predicates:")
    for pred, count in facts["predicate"].value_counts().head(15).items():
        log.info("  %s: %d", f"{pred:25s}", count)


    unique_subjects = facts["subject"].nunique()
    resolved = facts[facts["subject_person_id"].fillna("").str.len() > 0]["subject"].nunique()
    log.info("Unique subjects: %d", unique_subjects)
    log.info(
        "  Resolved to person_id: %d (%.1f%%)", resolved, resolved / max(unique_subjects, 1) * 100
    )





def main():
    parser = argparse.ArgumentParser(description="SBK Relationship Fact Annotation")
    parser.add_argument("--auto", action="store_true", help="Auto-save high-confidence facts")
    parser.add_argument(
        "--review", action="store_true", help="Interactive review of uncertain facts"
    )
    parser.add_argument("--person", type=str, help="Show facts for a specific person")
    parser.add_argument("--stats", action="store_true", help="Show fact statistics")
    parser.add_argument("--force", action="store_true", help="Bypass incremental guard")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-annotate")

    facts = load_facts()
    if facts.empty and not args.stats:
        return

    if args.stats:
        if facts.empty:
            log.warning("No facts found. Run xs-l3-extract-relationships.py --batch first.")
        else:
            show_stats(facts)
        return

    if args.person:
        show_person_facts(facts, args.person)
        return


    if (args.auto or args.review) and not args.force:
        _guard_inputs = [RELATIONSHIP_FACTS_FILE]
        if not check_inputs_changed("annotate", _guard_inputs):
            log.info("Incremental: inputs unchanged, skipping")
            mark_last_run("annotate")
            return

    annotations = load_annotations()

    if args.auto:
        annotations = auto_annotate(facts, annotations)
        save_annotations(annotations)
        save_input_checkpoint("annotate", [RELATIONSHIP_FACTS_FILE])
        mark_last_run("annotate")
    elif args.review:
        annotations = review_facts(facts, annotations)
        save_annotations(annotations)
        save_input_checkpoint("annotate", [RELATIONSHIP_FACTS_FILE])
        mark_last_run("annotate")
    else:
        parser.print_help()


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-annotate", source="annotate", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
