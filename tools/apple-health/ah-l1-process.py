#!/usr/bin/env python3
"""Apple Health L1: reads export.xml and writes one row per day of the measures SBK uses (weight, body fat, blood
pressure, heart rate, resting heart rate, HRV, respiratory rate, steps, energy) to metrics.parquet.
"""

import argparse
import logging
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (  # noqa: E402
    APPLE_HEALTH_PROCESSED_DIR,
    APPLE_HEALTH_RAW_DIR,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("ah-l1")



TYPES_OF_INTEREST = {
    "HKQuantityTypeIdentifierBodyMass",
    "HKQuantityTypeIdentifierBloodPressureSystolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic",
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierActiveEnergyBurned",
    "HKQuantityTypeIdentifierBasalEnergyBurned",
    "HKQuantityTypeIdentifierHeartRate",
    "HKQuantityTypeIdentifierOxygenSaturation",

    "HKQuantityTypeIdentifierBodyFatPercentage",
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierRespiratoryRate",
}


TYPE_TO_FIELD = {
    "HKQuantityTypeIdentifierBodyMass": "weight_kg",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "systolic_bp",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "diastolic_bp",
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy_kcal",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "resting_energy_kcal",
    "HKQuantityTypeIdentifierHeartRate": "avg_heart_rate",
    "HKQuantityTypeIdentifierOxygenSaturation": "avg_spo2",

    "HKQuantityTypeIdentifierBodyFatPercentage": "body_fat_pct",
    "HKQuantityTypeIdentifierVO2Max": "vo2max",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr_apple",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv_sdnn_apple",
    "HKQuantityTypeIdentifierRespiratoryRate": "respiratory_rate_apple",
}


BP_CORRELATION_TYPE = "HKCorrelationTypeIdentifierBloodPressure"


AGG_SUM = {"steps", "active_energy_kcal", "resting_energy_kcal"}
AGG_MEAN = {
    "systolic_bp",
    "diastolic_bp",
    "avg_heart_rate",
    "avg_spo2",
    "hrv_sdnn_apple",
    "respiratory_rate_apple",
}
AGG_LAST = {"weight_kg", "body_fat_pct", "vo2max", "resting_hr_apple"}


LB_TO_KG = 0.453592


def _convert_value(value_str: str, unit: str, field: str) -> float:
    ""
    val = float(value_str)

    if field == "weight_kg":
        if unit == "lb":
            val *= LB_TO_KG
    elif field == "avg_spo2":

        if val <= 1.0:
            val *= 100.0
    elif field == "body_fat_pct":

        if val <= 1.0:
            val *= 100.0

    return val


def _parse_date(date_str: str) -> date | None:
    ""
    try:
        return date.fromisoformat(date_str[:10])
    except (ValueError, IndexError):
        return None


def _process_record(
    elem,
    daily_values: dict[date, dict[str, list[float]]],
    min_date: date | None = None,
) -> bool:
    ""
    rec_type = elem.get("type", "")
    if rec_type not in TYPES_OF_INTEREST:
        return False

    value_str = elem.get("value", "")
    unit = elem.get("unit", "")
    start_date_str = elem.get("startDate", "")

    if not value_str or not start_date_str:
        return False

    field = TYPE_TO_FIELD.get(rec_type)
    if not field:
        return False

    ref_date = _parse_date(start_date_str)
    if not ref_date:
        return False

    if min_date and ref_date <= min_date:
        return False

    try:
        val = _convert_value(value_str, unit, field)
        daily_values[ref_date][field].append(val)
        return True
    except (ValueError, TypeError):
        return False


def parse_xml(
    xml_path: Path,
    min_date: date | None = None,
) -> dict[date, dict[str, list[float]]]:
    ""








    daily_values: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    record_count = 0

    for event, elem in ET.iterparse(str(xml_path), events=("end",)):
        if elem.tag == "Record":
            if _process_record(elem, daily_values, min_date):
                record_count += 1

        elif elem.tag == "Correlation":

            corr_type = elem.get("type", "")
            if corr_type == BP_CORRELATION_TYPE:
                for child in elem.findall("Record"):
                    if _process_record(child, daily_values, min_date):
                        record_count += 1

        elif elem.tag == "ActivitySummary":

            date_str = elem.get("dateComponents", "")
            ref_date = _parse_date(date_str)
            if ref_date and (not min_date or ref_date > min_date):
                exercise_str = elem.get("appleExerciseTime", "")
                stand_str = elem.get("appleStandHours", "")
                if exercise_str:
                    try:
                        daily_values[ref_date]["apple_exercise_min"].append(float(exercise_str))
                    except (ValueError, TypeError):
                        pass
                if stand_str:
                    try:
                        daily_values[ref_date]["apple_stand_hours"].append(float(stand_str))
                    except (ValueError, TypeError):
                        pass

        elem.clear()

    log.info("Parsed %d records from %s", record_count, xml_path.name)
    return daily_values



ACTIVITY_SUMMARY_FIELDS = {"apple_exercise_min", "apple_stand_hours"}


ALL_OUTPUT_FIELDS = list(TYPE_TO_FIELD.values()) + sorted(ACTIVITY_SUMMARY_FIELDS)


def _aggregate(daily_values: dict[date, dict[str, list[float]]]) -> pd.DataFrame:
    ""
    rows = []
    for day in sorted(daily_values.keys()):
        row = {"date": day}
        values = daily_values[day]

        for field in ALL_OUTPUT_FIELDS:
            if field not in values or not values[field]:
                row[field] = None
            elif field in AGG_SUM:
                row[field] = sum(values[field])
            elif field in AGG_MEAN:
                row[field] = sum(values[field]) / len(values[field])
            elif field in AGG_LAST or field in ACTIVITY_SUMMARY_FIELDS:
                row[field] = values[field][-1]
            else:
                row[field] = values[field][0]

        rows.append(row)

    return pd.DataFrame(rows)


REQUIRED_COLUMNS = ["date"] + ALL_OUTPUT_FIELDS


def process(
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    incremental: bool = False,
) -> pd.DataFrame | None:
    ""









    raw = raw_dir or APPLE_HEALTH_RAW_DIR
    out = output_dir or APPLE_HEALTH_PROCESSED_DIR
    out.mkdir(parents=True, exist_ok=True)

    xml_path = raw / "export.xml"
    if not xml_path.exists():
        log.error("No export.xml found in %s", raw)
        return None

    output_path = out / "metrics.parquet"


    min_date = None
    existing_df = None
    if incremental and output_path.exists():
        existing_df = pd.read_parquet(output_path)
        if not existing_df.empty and "date" in existing_df.columns:
            existing_df["date"] = pd.to_datetime(existing_df["date"]).dt.date
            min_date = existing_df["date"].max()
            log.info("Incremental mode: skipping records on or before %s", min_date)

    log.info("Processing Apple Health export from %s", xml_path)
    daily_values = parse_xml(xml_path, min_date=min_date)

    if not daily_values and existing_df is None:
        log.warning("No records of interest found in export")
        empty = pd.DataFrame(columns=REQUIRED_COLUMNS)
        safe_write_parquet(empty, output_path)
        return empty

    if not daily_values and existing_df is not None:
        log.info("No new records found (incremental), keeping existing data")
        return existing_df

    df = _aggregate(daily_values)


    if existing_df is not None and not existing_df.empty:
        df = pd.concat([existing_df, df], ignore_index=True)

        agg_funcs = {}
        for col in df.columns:
            if col == "date":
                continue
            if col in AGG_SUM:
                agg_funcs[col] = "sum"
            elif col in AGG_MEAN:
                agg_funcs[col] = "mean"
            else:
                agg_funcs[col] = "last"
        df = df.groupby("date", as_index=False).agg(agg_funcs)


    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None


    df = df.sort_values("date").reset_index(drop=True)

    safe_write_parquet(df, output_path)
    mark_last_run("apple-health-l1")
    log.info("Saved metrics.parquet: %d days, %d columns", len(df), len(df.columns))

    return df


def main():
    parser = argparse.ArgumentParser(description="Apple Health L1 processor — SBK")
    parser.add_argument("--raw-dir", type=str, help="Override raw data directory")
    parser.add_argument("--output-dir", type=str, help="Override output directory")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process records newer than existing metrics.parquet",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    raw = Path(args.raw_dir) if args.raw_dir else None
    out = Path(args.output_dir) if args.output_dir else None

    df = process(raw_dir=raw, output_dir=out, incremental=args.incremental)
    if df is not None and len(df) > 0:
        print(f"\nApple Health L1 processing complete: {len(df)} days")
        print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        non_null = {c: df[c].notna().sum() for c in df.columns if c != "date"}
        print(f"  Data density: {non_null}")
    else:
        print("No data to process")


if __name__ == "__main__":
    main()
