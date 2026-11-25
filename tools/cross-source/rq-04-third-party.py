#!/usr/bin/env python3
""











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

import pandas as pd

from sbk_config import (
    CALENDARS_DIR,
    DATA_ROOT,
    KNOWLEDGE_RELATIONSHIPS_DIR,
    PERSONIO_DIR,
    RQ_DIR,
)

log = logging.getLogger("rq-04")


def _load_calendar_events() -> list[dict]:
    ""
    events = []
    event_files = sorted(CALENDARS_DIR.glob("*/events.parquet"))
    for event_file in event_files:
        try:
            df = pd.read_parquet(event_file, columns=["attendees", "attendee_count"])
            for _, row in df.iterrows():
                if row.get("attendee_count", 0) and row.get("attendee_count", 0) > 1:
                    events.append(
                        {
                            "attendees": str(row.get("attendees", "")),
                            "attendee_count": int(row.get("attendee_count", 0)),
                        }
                    )
        except Exception as exc:
            log.warning("Failed to load %s: %s", event_file, exc)
    return events


def _load_emails() -> list[dict]:
    ""
    email_file = DATA_ROOT / "emails" / "filtered-messages.parquet"
    if not email_file.exists():
        return []

    cols_wanted = ["from_addr", "to_addr", "cc", "thread_id"]
    available = pd.read_parquet(email_file, columns=[]).columns.tolist()
    use_cols = [c for c in cols_wanted if c in available]

    df = pd.read_parquet(email_file, columns=use_cols)
    return df.to_dict("records")


def _load_composite_scores() -> pd.DataFrame:
    ""
    scores_file = RQ_DIR / "composite-scores.parquet"
    if not scores_file.exists():
        return pd.DataFrame()
    return pd.read_parquet(scores_file)


def main():
    parser = argparse.ArgumentParser(description="RQ-04: Third-party relationship mapping")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--person", type=str, help="Compute warm intros for single person")
    parser.add_argument(
        "--min-score",
        type=float,
        default=3.0,
        help="Minimum bridge score for warm intros (default: 3.0)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rq_third_party import (
        aggregate_signals,
        build_company_pairs,
        build_email_thread_pairs,
        build_meeting_pairs,
        compute_third_party_strength,
        find_warm_intros,
    )
    from rq_type_detection import load_personio_index


    log.info("Loading data...")
    calendar_events = _load_calendar_events()
    emails = _load_emails()
    personio_index = load_personio_index(PERSONIO_DIR)
    scores_df = _load_composite_scores()

    log.info(
        "Loaded: %d calendar events, %d emails, %d personio, %d scored contacts",
        len(calendar_events),
        len(emails),
        len(personio_index),
        len(scores_df),
    )


    log.info("Building co-occurrence indexes...")
    meeting_pairs = build_meeting_pairs(calendar_events)
    thread_pairs, cc_pairs = build_email_thread_pairs(emails)
    company_pairs, team_pairs = build_company_pairs(personio_index)

    log.info(
        "Pairs found: %d meeting, %d thread, %d CC, %d company, %d team",
        len(meeting_pairs),
        len(thread_pairs),
        len(cc_pairs),
        len(company_pairs),
        len(team_pairs),
    )


    log.info("Aggregating signals...")
    all_signals = aggregate_signals(
        meeting_pairs, thread_pairs, cc_pairs, company_pairs, team_pairs
    )
    log.info("Total third-party pairs with signals: %d", len(all_signals))


    third_party_strengths = {}
    for pair, signals in all_signals.items():
        third_party_strengths[pair] = compute_third_party_strength(signals)


    signal_type_counts: dict[str, int] = {}
    for signals in all_signals.values():
        for sig in signals:
            stype = sig["type"]
            signal_type_counts[stype] = signal_type_counts.get(stype, 0) + 1

    log.info("")
    log.info("Signal type distribution:")
    for stype, count in sorted(signal_type_counts.items(), key=lambda x: -x[1]):
        log.info("  %-20s %5d", stype, count)


    log.info("")
    log.info("Computing warm intro paths...")

    owner_relationships: dict[str, float] = {}
    if not scores_df.empty:
        for _, row in scores_df.iterrows():
            owner_relationships[str(row["person"])] = float(row.get("score", 1.0))


    targets = []
    if args.person:
        targets = [args.person]
    else:

        all_people_in_pairs = set()
        for pair_a, pair_b in all_signals:
            all_people_in_pairs.add(pair_a)
            all_people_in_pairs.add(pair_b)

        for person in all_people_in_pairs:
            direct_score = owner_relationships.get(person, 0.0)
            if direct_score < 3.0:
                targets.append(person)

    warm_intros_index: dict[str, list[dict]] = {}
    for target in targets:
        intros = find_warm_intros(
            target_email=target,
            owner_relationships=owner_relationships,
            third_party_strengths=third_party_strengths,
            third_party_signals=all_signals,
            min_bridge_score=args.min_score,
        )
        if intros:
            warm_intros_index[target] = intros

    log.info("Warm intro paths found for %d targets", len(warm_intros_index))


    log.info("=" * 60)
    log.info(
        "TOTAL: %d third-party pairs, %d warm intro targets",
        len(all_signals),
        len(warm_intros_index),
    )

    if args.dry_run:
        log.info("DRY RUN — no output written")

        for target, intros in list(warm_intros_index.items())[:3]:
            log.info("  Target: %s", target)
            for intro in intros[:2]:
                log.info(
                    "    via %s (owner:%.1f, bridge:%.2f, path:%.2f)",
                    intro["bridge"],
                    intro["owner_to_bridge_score"],
                    intro["bridge_to_target_strength"],
                    intro["path_strength"],
                )
        return


    KNOWLEDGE_RELATIONSHIPS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = KNOWLEDGE_RELATIONSHIPS_DIR / "third-party-index.json"


    pairs_data = []
    for pair, signals in all_signals.items():
        pairs_data.append(
            {
                "person_a": pair[0],
                "person_b": pair[1],
                "strength": round(third_party_strengths.get(pair, 0.0), 3),
                "signals": [
                    {"type": s["type"], "count": s["count"], "confidence": s["confidence"]}
                    for s in signals
                ],
            }
        )

    index_data = {
        "pairs_count": len(pairs_data),
        "warm_intros_count": len(warm_intros_index),
        "pairs": pairs_data,
        "warm_intros": warm_intros_index,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    index_file.write_text(json.dumps(index_data, indent=2), encoding="utf-8")
    log.info(
        "Written: %s (%d pairs, %d warm intros)",
        index_file,
        len(pairs_data),
        len(warm_intros_index),
    )


    updated = 0
    for target, intros in warm_intros_index.items():
        detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{target}.json"
        detail = {}
        if detail_file.exists():
            try:
                detail = json.loads(detail_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        detail["warm_intros"] = intros
        detail["warm_intros_updated"] = datetime.now(UTC).isoformat()
        detail_file.write_text(json.dumps(detail, indent=2), encoding="utf-8")
        updated += 1

    log.info("Updated %d relationship detail JSONs with warm intros", updated)


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-04-third-party", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
