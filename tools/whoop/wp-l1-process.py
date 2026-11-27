#!/usr/bin/env python3
"""WHOOP L1: one row per day with sleep, recovery (and its zone), strain and workouts, plus derived measures such as
sleep debt and the HRV baseline.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (  # noqa: E402
    WHOOP_PROCESSED_DIR,
    WHOOP_RAW_DIR,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("whoop-l1")

SLEEP_TARGET_MS = 7 * 3600 * 1000
HRV_BASELINE_WINDOW = 30


def classify_recovery_zone(score: float | None) -> str | None:
    ""







    if score is None or pd.isna(score):
        return None
    if score <= 33:
        return "red"
    if score <= 66:
        return "yellow"
    return "green"


def _load_json(path: Path) -> list[dict]:
    ""
    if not path.exists():
        log.warning("File not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception) as e:
        log.error("Failed to parse %s: %s", path, e)
        return []


def _parse_sleep(records: list[dict]) -> pd.DataFrame:
    ""
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        score = rec.get("score", {})
        stages = score.get("stage_summary", {})
        end_str = rec.get("end", "")
        if not end_str:
            continue

        end_dt = pd.Timestamp(end_str)
        ref_date = end_dt.normalize().date()

        rows.append(
            {
                "date": ref_date,
                "sleep_score": score.get("sleep_performance_percentage"),
                "sleep_efficiency": score.get("sleep_efficiency_percentage"),
                "respiratory_rate": score.get("respiratory_rate"),
                "total_sleep_ms": stages.get("total_sleep_duration"),
                "rem_sleep_ms": stages.get("total_rem_sleep_time_milli"),
                "deep_sleep_ms": stages.get("total_slow_wave_sleep_time_milli"),
                "light_sleep_ms": stages.get("total_light_sleep_time_milli"),
                "awake_ms": stages.get("total_awake_time_milli"),
                "time_in_bed_ms": stages.get("total_in_bed_time_milli"),
                "sleep_start": pd.Timestamp(rec.get("start", "")),
                "sleep_end": end_dt,
            }
        )

    return pd.DataFrame(rows)


def _parse_recovery(records: list[dict]) -> pd.DataFrame:
    ""
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        score = rec.get("score", {})
        created = rec.get("created_at", "")
        if not created:
            continue

        ref_date = pd.Timestamp(created).normalize().date()

        rows.append(
            {
                "date": ref_date,
                "recovery_score": score.get("recovery_score"),
                "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
                "spo2_pct": score.get("spo2_percentage"),
                "skin_temp_c": score.get("skin_temp_celsius"),
            }
        )

    return pd.DataFrame(rows)


def _parse_cycles(records: list[dict]) -> pd.DataFrame:
    ""
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        score = rec.get("score", {})
        start = rec.get("start", "")
        if not start:
            continue

        ref_date = pd.Timestamp(start).normalize().date()

        rows.append(
            {
                "date": ref_date,
                "strain_score": score.get("strain"),
            }
        )

    return pd.DataFrame(rows)


def _parse_workouts(records: list[dict]) -> pd.DataFrame:
    ""
    if not records:
        return pd.DataFrame()

    rows = []
    for rec in records:
        score = rec.get("score", {})
        start = rec.get("start", "")
        end = rec.get("end", "")
        if not start:
            continue

        ref_date = pd.Timestamp(start).normalize().date()

        rows.append(
            {
                "date": ref_date,
                "workout_strain": score.get("strain", 0),
                "workout_end": pd.Timestamp(end) if end else None,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    agg = (
        df.groupby("date")
        .agg(
            workout_count=("workout_strain", "count"),
            workout_strain_total=("workout_strain", "sum"),
            workout_last_end=("workout_end", "max"),
        )
        .reset_index()
    )
    return agg


def _compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    ""
    df = df.sort_values("date").reset_index(drop=True)


    if "hrv_rmssd_milli" in df.columns:
        df["hrv_rmssd_ms"] = df["hrv_rmssd_milli"] / 1000.0
        df = df.drop(columns=["hrv_rmssd_milli"])
    elif "hrv_rmssd_ms" not in df.columns:
        df["hrv_rmssd_ms"] = None


    if "hrv_rmssd_ms" in df.columns:
        baseline = (
            df["hrv_rmssd_ms"]
            .rolling(window=HRV_BASELINE_WINDOW, min_periods=HRV_BASELINE_WINDOW)
            .mean()
        )
        df["hrv_delta_from_baseline"] = df["hrv_rmssd_ms"] - baseline
    else:
        df["hrv_delta_from_baseline"] = None


    if "recovery_score" in df.columns:
        df["recovery_zone"] = df["recovery_score"].apply(classify_recovery_zone)
    else:
        df["recovery_zone"] = None


    if "total_sleep_ms" in df.columns:
        df["sleep_debt_ms"] = df["total_sleep_ms"].apply(
            lambda x: max(0, SLEEP_TARGET_MS - x) if pd.notna(x) else None
        )
    else:
        df["sleep_debt_ms"] = None

    return df


def process(
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
) -> pd.DataFrame | None:
    ""








    raw = raw_dir or WHOOP_RAW_DIR
    out = output_dir or WHOOP_PROCESSED_DIR
    out.mkdir(parents=True, exist_ok=True)

    log.info("Processing WHOOP raw data from %s", raw)


    sleep_df = _parse_sleep(_load_json(raw / "sleep.json"))
    recovery_df = _parse_recovery(_load_json(raw / "recovery.json"))
    cycles_df = _parse_cycles(_load_json(raw / "cycles.json"))
    workouts_df = _parse_workouts(_load_json(raw / "workouts.json"))


    all_dates = set()
    for df in [sleep_df, recovery_df, cycles_df, workouts_df]:
        if not df.empty and "date" in df.columns:
            all_dates.update(df["date"].unique())

    if not all_dates:
        log.warning("No data found in raw files")

        empty = pd.DataFrame(
            columns=[
                "date",
                "sleep_score",
                "recovery_score",
                "strain_score",
                "hrv_rmssd_ms",
                "resting_hr",
                "spo2_pct",
                "skin_temp_c",
                "respiratory_rate",
                "sleep_efficiency",
                "total_sleep_ms",
                "rem_sleep_ms",
                "deep_sleep_ms",
                "light_sleep_ms",
                "awake_ms",
                "time_in_bed_ms",
                "sleep_start",
                "sleep_end",
                "workout_count",
                "workout_strain_total",
                "workout_last_end",
                "hrv_delta_from_baseline",
                "recovery_zone",
                "sleep_debt_ms",
            ]
        )
        safe_write_parquet(empty, out / "daily.parquet")
        safe_write_parquet(empty, out / "daily.parquet")
        return empty


    daily = pd.DataFrame({"date": sorted(all_dates)})


    if not sleep_df.empty:

        sleep_df = sleep_df.sort_values("sleep_end").drop_duplicates("date", keep="last")
        daily = daily.merge(sleep_df, on="date", how="left")

    if not recovery_df.empty:
        recovery_df = recovery_df.drop_duplicates("date", keep="last")
        daily = daily.merge(recovery_df, on="date", how="left")

    if not cycles_df.empty:
        cycles_df = cycles_df.drop_duplicates("date", keep="last")
        daily = daily.merge(cycles_df, on="date", how="left")

    if not workouts_df.empty:
        daily = daily.merge(workouts_df, on="date", how="left")


    if "workout_count" not in daily.columns:
        daily["workout_count"] = 0
        daily["workout_strain_total"] = 0.0
        daily["workout_last_end"] = None
    else:
        daily["workout_count"] = daily["workout_count"].fillna(0).astype(int)
        daily["workout_strain_total"] = daily["workout_strain_total"].fillna(0.0)


    daily = _compute_derived(daily)


    required = [
        "date",
        "sleep_score",
        "recovery_score",
        "strain_score",
        "hrv_rmssd_ms",
        "resting_hr",
        "spo2_pct",
        "skin_temp_c",
        "respiratory_rate",
        "sleep_efficiency",
        "total_sleep_ms",
        "rem_sleep_ms",
        "deep_sleep_ms",
        "light_sleep_ms",
        "awake_ms",
        "time_in_bed_ms",
        "sleep_start",
        "sleep_end",
        "workout_count",
        "workout_strain_total",
        "workout_last_end",
        "hrv_delta_from_baseline",
        "recovery_zone",
        "sleep_debt_ms",
    ]
    for col in required:
        if col not in daily.columns:
            daily[col] = None


    daily = daily.sort_values("date").reset_index(drop=True)


    output_path = out / "daily.parquet"
    safe_write_parquet(daily, output_path)
    mark_last_run("whoop-l1")
    log.info("Saved daily.parquet: %d rows, %d columns", len(daily), len(daily.columns))

    return daily


def main():
    parser = argparse.ArgumentParser(description="WHOOP L1 processor — SBK")
    parser.add_argument("--raw-dir", type=str, help="Override raw data directory")
    parser.add_argument("--output-dir", type=str, help="Override output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    raw = Path(args.raw_dir) if args.raw_dir else None
    out = Path(args.output_dir) if args.output_dir else None

    df = process(raw_dir=raw, output_dir=out)
    if df is not None:
        print(f"\nWHOOP L1 processing complete: {len(df)} days")
        print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        zones = df["recovery_zone"].value_counts().to_dict()
        print(f"  Recovery zones: {zones}")
    else:
        print("No data to process")


if __name__ == "__main__":
    main()
