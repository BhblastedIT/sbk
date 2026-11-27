#!/usr/bin/env python3
"""NLP daily stats: the decisions and action items extracted per day, into l3/nlp/daily-stats.parquet."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step  # noqa: E402

from sbk_config import DECISIONS_FILE, NLP_DIR, safe_write_parquet  # noqa: E402

ACTION_ITEMS_FILE = NLP_DIR / "action-items.parquet"
OUTPUT_FILE = NLP_DIR / "daily-stats.parquet"

log = logging.getLogger("nlp-daily-stats")





def compute_daily_stats(
    action_df: pd.DataFrame,
    decisions_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ""








    out_cols = ["date", "action_items_generated", "decisions_count"]


    if action_df.empty:
        ai_daily = pd.DataFrame(columns=["date", "action_items_generated"])
    else:
        tmp = action_df.copy()
        tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce").dt.date
        tmp = tmp.dropna(subset=["date"])
        ai_daily = tmp.groupby("date").size().reset_index(name="action_items_generated")


    if decisions_df is None or decisions_df.empty:
        dec_daily = pd.DataFrame(columns=["date", "decisions_count"])
    else:
        tmp = decisions_df.copy()
        tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce").dt.date
        tmp = tmp.dropna(subset=["date"])
        dec_daily = tmp.groupby("date").size().reset_index(name="decisions_count")


    if ai_daily.empty and dec_daily.empty:
        return pd.DataFrame(columns=out_cols)

    daily = pd.merge(ai_daily, dec_daily, on="date", how="outer")
    daily["action_items_generated"] = daily["action_items_generated"].fillna(0).astype(int)
    daily["decisions_count"] = daily["decisions_count"].fillna(0).astype(int)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)
    return daily[out_cols]





@pipeline_step(name="l3-nlp-daily-stats", source="nlp-daily-stats", stage="l3")
def main():
    parser = argparse.ArgumentParser(description="NLP Daily Stats Aggregator")
    parser.add_argument("--dry-run", action="store_true", help="Compute without writing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not ACTION_ITEMS_FILE.exists():
        log.error("Input file not found: %s", ACTION_ITEMS_FILE)
        sys.exit(1)

    log.info("Loading %s", ACTION_ITEMS_FILE)
    action_df = pd.read_parquet(ACTION_ITEMS_FILE)
    log.info("Loaded %d action items", len(action_df))

    decisions_df = None
    if DECISIONS_FILE.exists():
        decisions_df = pd.read_parquet(DECISIONS_FILE)
        log.info("Loaded %d decisions from %s", len(decisions_df), DECISIONS_FILE)
    else:
        log.info("No decisions file found at %s — skipping", DECISIONS_FILE)

    daily = compute_daily_stats(action_df, decisions_df)
    log.info("Computed stats for %d days", len(daily))

    if daily.empty:
        log.warning("No data — skipping write")
        return

    log.info(
        "Date range: %s to %s",
        daily["date"].min().strftime("%Y-%m-%d"),
        daily["date"].max().strftime("%Y-%m-%d"),
    )
    log.info(
        "Totals: %d action items, %d decisions",
        daily["action_items_generated"].sum(),
        daily["decisions_count"].sum(),
    )

    if args.dry_run:
        log.info("[DRY RUN] Would write %d rows to %s", len(daily), OUTPUT_FILE)
        print(daily.head(10).to_string(index=False))
        return

    safe_write_parquet(daily, OUTPUT_FILE)
    log.info("Wrote %d rows to %s", len(daily), OUTPUT_FILE)


if __name__ == "__main__":
    main()
