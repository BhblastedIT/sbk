#!/usr/bin/env python3
"""RQ-02b: extracts the qualitative signals about each relationship (from relationship facts and the weighted
interactions, with names resolved to people) into the signals table the scores read.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    ENRICHED_DIR,
    RQ_DIR,
    RQ_NAME_MATCHING_INDEX,
    RQ_SIGNALS_FILE,
    safe_write_parquet,
)

log = logging.getLogger("rq-02b")


def main():
    parser = argparse.ArgumentParser(description="RQ-02b: Extract qualitative signals")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    from rq_name_matching import NameMatcher

    matcher = None
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if cm_path.exists():
        if RQ_NAME_MATCHING_INDEX.exists():
            matcher = NameMatcher.load_index(RQ_NAME_MATCHING_INDEX)
            log.info("Loaded name matching index from %s", RQ_NAME_MATCHING_INDEX)
        else:
            matcher = NameMatcher(contacts_merged_path=cm_path)
            log.info("Built name matcher from contacts-merged (%s)", matcher.get_stats())

            RQ_DIR.mkdir(parents=True, exist_ok=True)
            matcher.save_index(RQ_NAME_MATCHING_INDEX)
    else:
        log.warning("No contacts-merged.parquet found")


    from rq_identity_resolver import IdentityResolver

    resolver = IdentityResolver(cm_path=cm_path, name_matcher=matcher) if cm_path.exists() else None
    if resolver:
        log.info("Identity resolver: %s", resolver.stats)


    from rq_signal_extraction import extract_all_signals

    signals_df = extract_all_signals(name_matcher=matcher, resolver=resolver)

    if signals_df.empty:
        log.warning("No signals extracted")
        return


    log.info("=" * 60)
    log.info("TOTAL: %d persons with signals", len(signals_df))
    log.info(
        "Signal coverage: min=%.2f, mean=%.2f, max=%.2f",
        signals_df["signal_coverage"].min(),
        signals_df["signal_coverage"].mean(),
        signals_df["signal_coverage"].max(),
    )


    for col in ["is_family", "is_ex_employee"]:
        if col in signals_df.columns:
            count = signals_df[col].sum()
            log.info("  %s: %d", col, count)

    for col in [
        "personal_topic_count",
        "topic_breadth",
        "introductions_count",
        "action_items_count",
        "commitment_facts_count",
        "rejection_count",
    ]:
        if col in signals_df.columns:
            nonzero = (signals_df[col] > 0).sum()
            log.info("  %s: %d non-zero", col, nonzero)


    log.info("  --- Content Quality (V3) ---")
    for col in [
        "formality_score",
        "self_disclosure_count",
        "emotional_word_density",
        "linguistic_style_matching",
        "meeting_warmth_score",
        "laughter_per_minute",
        "personal_topic_in_meeting",
    ]:
        if col in signals_df.columns:
            default_val = 0.5 if col == "formality_score" else 0.0
            nondefault = (signals_df[col] != default_val).sum()
            log.info("  %s: %d non-default", col, nondefault)

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return


    RQ_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(signals_df, RQ_SIGNALS_FILE)
    log.info("Written: %s (%d rows)", RQ_SIGNALS_FILE, len(signals_df))


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-02b-extract-signals", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
