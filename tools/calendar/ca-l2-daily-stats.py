#!/usr/bin/env python3
"""Calendar daily stats: for each day, how many meetings, how many hours, the hour of the first and last one and
the back-to-back meetings, from the events of every account (duplicates removed), into daily-stats.parquet.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil import parser as dtparser



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    CALENDARS_DIR,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("sbk.calendar.daily-stats")

DEFAULT_MAX_DURATION = 720
DEFAULT_BTB_GAP = 15
FALLBACK_TZ = "UTC"





def load_all_events(calendars_dir: Path) -> pd.DataFrame:
    ""
    frames = []
    for subdir in sorted(calendars_dir.iterdir()):
        if not subdir.is_dir():
            continue
        parquet_path = subdir / "events.parquet"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
            log.info("Loaded %d events from %s", len(df), subdir.name)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def dedup_events(df: pd.DataFrame) -> pd.DataFrame:
    ""
    before = len(df)
    df = df.drop_duplicates(subset=["id"], keep="first")
    log.info("Dedup: %d -> %d events (%d removed)", before, len(df), before - len(df))
    return df


def parse_event_datetimes(df: pd.DataFrame) -> pd.DataFrame:
    ""




    mask_timed = df["start_datetime"].str.contains("T", na=False)
    all_day_count = (~mask_timed).sum()
    log.info("Excluding %d all-day events", all_day_count)
    df = df[mask_timed].copy()

    if df.empty:
        return df


    starts = df["start_datetime"].apply(_parse_dt)
    ends = df["end_datetime"].apply(_parse_dt)

    df["_start_dt"] = starts
    df["_end_dt"] = ends


    df["_local_date"] = starts.apply(_extract_local_date)


    df["_start_hour"] = starts.apply(_dt_to_hour)
    df["_end_hour"] = ends.apply(_dt_to_hour)

    return df


def _parse_dt(s: str) -> pd.Timestamp:
    ""
    try:
        dt = dtparser.isoparse(s)
        if dt.tzinfo is None:
            import zoneinfo

            dt = dt.replace(tzinfo=zoneinfo.ZoneInfo(FALLBACK_TZ))
        return pd.Timestamp(dt)
    except (ValueError, TypeError):
        return pd.NaT


def _extract_local_date(ts: pd.Timestamp) -> date | None:
    ""
    if pd.isna(ts):
        return None

    return ts.date()


def _dt_to_hour(ts: pd.Timestamp) -> float:
    ""
    if pd.isna(ts):
        return np.nan
    return ts.hour + ts.minute / 60.0


def compute_duration(df: pd.DataFrame, max_duration: int) -> pd.DataFrame:
    ""
    if df.empty:
        return df

    starts = pd.to_datetime(df["_start_dt"], utc=True)
    ends = pd.to_datetime(df["_end_dt"], utc=True)
    raw = (ends - starts).dt.total_seconds() / 60.0
    df["_duration_min"] = raw.clip(upper=max_duration)
    return df


def aggregate_daily(df: pd.DataFrame, btb_gap: int) -> pd.DataFrame:
    ""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "meetings_count",
                "meetings_total_minutes",
                "first_meeting_hour",
                "last_meeting_hour",
                "back_to_back_count",
                "meeting_gap_avg_min",
                "longest_meeting_min",
                "attendee_avg",
                "solo_block_count",
            ]
        )

    rows = []
    for local_date, group in df.groupby("_local_date"):
        if local_date is None:
            continue

        meetings_count = len(group)
        meetings_total_minutes = float(group["_duration_min"].sum())
        first_meeting_hour = float(group["_start_hour"].min())
        last_meeting_hour = float(group["_end_hour"].max())
        longest_meeting_min = float(group["_duration_min"].max())


        att = group["attendee_count"].fillna(0).astype(int)
        attendee_avg = float(att.mean())
        solo_block_count = int((att == 0).sum())


        btb_count = 0
        gap_avg = np.nan

        if meetings_count >= 2:
            sorted_g = group.sort_values("_start_dt")
            starts = sorted_g["_start_dt"].values
            ends = sorted_g["_end_dt"].values
            gaps = []
            for i in range(len(starts) - 1):
                gap_min = (starts[i + 1] - ends[i]) / np.timedelta64(1, "m")
                gaps.append(gap_min)
                if gap_min <= btb_gap:
                    btb_count += 1
            positive_gaps = [g for g in gaps if g > 0]
            gap_avg = float(np.mean(positive_gaps)) if positive_gaps else 0.0

        rows.append(
            {
                "date": local_date,
                "meetings_count": meetings_count,
                "meetings_total_minutes": meetings_total_minutes,
                "first_meeting_hour": first_meeting_hour,
                "last_meeting_hour": last_meeting_hour,
                "back_to_back_count": btb_count,
                "meeting_gap_avg_min": gap_avg,
                "longest_meeting_min": longest_meeting_min,
                "attendee_avg": attendee_avg,
                "solo_block_count": solo_block_count,
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("date").reset_index(drop=True)
        result["date"] = pd.to_datetime(result["date"]).dt.date
        result["meetings_count"] = result["meetings_count"].astype(int)
        result["back_to_back_count"] = result["back_to_back_count"].astype(int)
        result["solo_block_count"] = result["solo_block_count"].astype(int)
    return result


def run(
    calendars_dir: Path = CALENDARS_DIR,
    *,
    dry_run: bool = False,
    max_duration: int = DEFAULT_MAX_DURATION,
    btb_gap: int = DEFAULT_BTB_GAP,
    include_empty_days: bool = False,
) -> pd.DataFrame:
    ""

    all_events = load_all_events(calendars_dir)
    if all_events.empty:
        log.warning("No events found in %s", calendars_dir)
        return pd.DataFrame()

    log.info("Total raw events: %d", len(all_events))


    unique = dedup_events(all_events)


    parsed = parse_event_datetimes(unique)
    if parsed.empty:
        log.warning("No timed events after filtering")
        return pd.DataFrame()


    parsed = compute_duration(parsed, max_duration)


    daily = aggregate_daily(parsed, btb_gap)

    if include_empty_days and not daily.empty:
        all_dates = pd.date_range(start=daily["date"].min(), end=daily["date"].max(), freq="D")
        date_df = pd.DataFrame({"date": all_dates.date})
        daily = date_df.merge(daily, on="date", how="left")
        daily["meetings_count"] = daily["meetings_count"].fillna(0).astype(int)
        daily["back_to_back_count"] = daily["back_to_back_count"].fillna(0).astype(int)
        daily["solo_block_count"] = daily["solo_block_count"].fillna(0).astype(int)
        daily["meetings_total_minutes"] = daily["meetings_total_minutes"].fillna(0.0)

    log.info(
        "Daily stats: %d days, %d total meetings",
        len(daily),
        daily["meetings_count"].sum() if not daily.empty else 0,
    )


    if not dry_run:
        out_path = calendars_dir / "daily-stats.parquet"
        safe_write_parquet(daily, out_path)
        mark_last_run("calendar-daily-stats")
        log.info("Wrote %s (%d rows)", out_path, len(daily))
    else:
        log.info("[DRY RUN] Would write %d rows to daily-stats.parquet", len(daily))
        if not daily.empty:
            print("\n--- Sample output (first 10 rows) ---")
            print(daily.head(10).to_string(index=False))
            print("\n--- Stats ---")
            print(f"Days: {len(daily)}")
            print(f"Total meetings: {daily['meetings_count'].sum()}")
            print(f"Avg meetings/day: {daily['meetings_count'].mean():.1f}")
            print(f"Avg duration/day: {daily['meetings_total_minutes'].mean():.0f} min")

    return daily





def main():
    parser = argparse.ArgumentParser(description="Calendar Daily Stats Aggregator — SBK")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show stats without writing output",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=DEFAULT_MAX_DURATION,
        help=f"Cap per-event duration in minutes (default: {DEFAULT_MAX_DURATION})",
    )
    parser.add_argument(
        "--back-to-back-gap",
        type=int,
        default=DEFAULT_BTB_GAP,
        help=f"Back-to-back threshold in minutes (default: {DEFAULT_BTB_GAP})",
    )
    parser.add_argument(
        "--include-empty-days",
        action="store_true",
        help="Include days with 0 meetings (default: omit them)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run(
        dry_run=args.dry_run,
        max_duration=args.max_duration,
        btb_gap=args.back_to_back_gap,
        include_empty_days=args.include_empty_days,
    )


if __name__ == "__main__":
    main()
