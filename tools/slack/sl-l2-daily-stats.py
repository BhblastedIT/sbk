#!/usr/bin/env python3
"""Aggregate Slack daily statistics (L2)."""


















from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step  # noqa: E402

from sbk_config import OWN_NAMES_NORMALIZED, SLACK_DIR, safe_write_parquet  # noqa: E402

INPUT_FILE = SLACK_DIR / "interactions-slack.parquet"
OUTPUT_FILE = SLACK_DIR / "daily-stats.parquet"


log = logging.getLogger("slack-daily-stats")


def _is_owner(names: pd.Series) -> pd.Series:
    """Rows whose sender is you (sbk.config.json owner / own_names)."""
    return names.fillna("").astype(str).str.strip().str.lower().isin(OWN_NAMES_NORMALIZED)





def compute_daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    ""









    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "slack_messages_sent",
                "slack_dm_count",
                "slack_channels_active",
                "slack_avg_response_min",
            ]
        )


    owner = df[_is_owner(df["from_user"])].copy()
    if owner.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "slack_messages_sent",
                "slack_dm_count",
                "slack_channels_active",
                "slack_avg_response_min",
            ]
        )


    owner["date"] = pd.to_datetime(owner["timestamp"], errors="coerce").dt.date
    owner = owner.dropna(subset=["date"])


    daily = owner.groupby("date").agg(
        slack_messages_sent=("from_user", "count"),
        slack_dm_count=("message_type", lambda x: (x == "dm").sum()),
        slack_channels_active=("channel", "nunique"),
    )



    replies = df[
        _is_owner(df["from_user"]) & (df["message_type"].isin(["reply", "mention"]))
    ].copy()
    if not replies.empty:
        replies["date"] = pd.to_datetime(replies["timestamp"], errors="coerce").dt.date
        replies = replies.dropna(subset=["date"])

        reply_daily = replies.groupby("date").size().rename("_reply_count")
        daily = daily.join(reply_daily, on="date", how="left")


        daily["slack_avg_response_min"] = (480.0 / daily["_reply_count"].fillna(1)).round(1)
        daily["slack_avg_response_min"] = daily["slack_avg_response_min"].clip(upper=480.0)
        daily.drop(columns=["_reply_count"], inplace=True)
    else:
        daily["slack_avg_response_min"] = np.nan

    daily = daily.reset_index()
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").reset_index(drop=True)

    return daily





@pipeline_step(name="l2-slack-daily-stats", source="slack-daily-stats", stage="l2")
def main():
    parser = argparse.ArgumentParser(description="Slack Daily Stats Aggregator")
    parser.add_argument("--dry-run", action="store_true", help="Compute stats without writing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not INPUT_FILE.exists():
        log.error("Input file not found: %s", INPUT_FILE)
        sys.exit(1)

    log.info("Loading %s", INPUT_FILE)
    df = pd.read_parquet(INPUT_FILE)
    log.info("Loaded %d interactions", len(df))

    daily = compute_daily_stats(df)
    log.info("Computed stats for %d days", len(daily))

    if daily.empty:
        log.warning("No messages of yours found (check owner and own_names in sbk.config.json) — skipping write")
        return


    log.info(
        "Date range: %s to %s",
        daily["date"].min().strftime("%Y-%m-%d"),
        daily["date"].max().strftime("%Y-%m-%d"),
    )
    log.info(
        "Totals: %d messages sent, %d DMs",
        daily["slack_messages_sent"].sum(),
        daily["slack_dm_count"].sum(),
    )

    if args.dry_run:
        log.info("[DRY RUN] Would write %d rows to %s", len(daily), OUTPUT_FILE)
        print(daily.head(10).to_string(index=False))
        return

    safe_write_parquet(daily, OUTPUT_FILE)
    log.info("Wrote %d rows to %s", len(daily), OUTPUT_FILE)


if __name__ == "__main__":
    main()
