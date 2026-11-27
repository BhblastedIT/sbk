#!/usr/bin/env python3
"""Personio absences per day: expands each absence (by day or by hours, weekdays only) into one row per person per
day, with its category.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from sbk_config import DATA_ROOT, mark_last_run, safe_write_parquet  # noqa: E402

log = logging.getLogger("pe-absences-daily")

PERSONIO_DIR = DATA_ROOT / "personio"
PROCESSED_DIR = PERSONIO_DIR / "processed"
ABSENCES_FILE = PERSONIO_DIR / "absences-raw.json"
ABSENCE_PERIODS_FILE = PERSONIO_DIR / "absence-periods-raw.json"
ABSENCE_TYPES_FILE = PERSONIO_DIR / "absence-types.json"
EMPLOYEES_FILE = PERSONIO_DIR / "employees-flat.json"
OUTPUT_FILE = PROCESSED_DIR / "absences-daily.parquet"





CATEGORY_COLUMN = {
    "sick_leave": "sickness_count",
    "paid_vacation": "vacation_count",
    "unpaid_vacation": "vacation_count",
    "offsite_work": "remote_count",
    "maternity_parental_leave": "parental_count",
    "family_care": "family_care_count",
    "public_duty": "public_duty_count",
    "other": "other_count",
}


FALLBACK_COLUMN = "other_count"
COUNT_COLUMNS = [
    "sickness_count",
    "vacation_count",
    "remote_count",
    "other_count",
    "parental_count",
    "family_care_count",
    "public_duty_count",
]




NOT_TAKEN_STATUSES = {
    "declined",
    "rejected",
    "denied",
    "cancelled",
    "canceled",
    "deleted",
    "deletion_pending",
    "withdrawn",
}



DEFAULT_DAILY_MINUTES = 8 * 60


def _load_records(path: Path) -> list[dict]:
    ""
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    data = raw.get("data", [])
    return data if isinstance(data, list) else []


def load_employee_index(path: Path) -> dict[str, dict]:
    ""




    index: dict[str, dict] = {}
    if not path.exists():
        return index
    with open(path) as f:
        employees = json.load(f)
    if not isinstance(employees, list):
        return index
    for e in employees:
        eid = str(e.get("id", "")).strip()
        if not eid:
            continue
        daily_minutes = DEFAULT_DAILY_MINUTES
        try:
            weekly = float(e.get("weekly_working_hours") or 0)
            if weekly > 0:
                daily_minutes = weekly * 60 / 5
        except (TypeError, ValueError):
            pass
        index[eid] = {
            "department": str(e.get("department") or "").strip() or "unknown",
            "daily_minutes": daily_minutes,
        }
    return index


def load_category_by_type_id(path: Path) -> dict[str, str]:
    ""




    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    for record in _load_records(path):
        attrs = record.get("attributes", record)
        type_id = str(attrs.get("id", "")).strip()
        category = str(attrs.get("category", "") or "").strip().lower()
        if type_id and category:
            mapping[type_id] = category
    return mapping


def _employee_id(attrs: dict) -> str:
    ""





    employee = attrs.get("employee") or {}
    node = employee.get("attributes", employee).get("id")
    if isinstance(node, dict):
        value = node.get("value")
    else:
        value = node
    if value in (None, ""):
        value = attrs.get("employee_id", "")
    return str(value).strip()


def _weekdays(start: date, end: date):
    ""




    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def expand_day_absences(records: list[dict], employees: dict[str, dict]) -> list[dict]:
    ""
    rows: list[dict] = []
    unknown_categories: set[str] = set()
    skipped_status = 0
    for record in records:
        attrs = record.get("attributes", record)
        status = str(attrs.get("status", "") or "").strip().lower()
        if status in NOT_TAKEN_STATUSES:
            skipped_status += 1
            continue
        start_raw = str(attrs.get("start_date", "") or "")
        if not start_raw:
            continue
        type_attrs = (attrs.get("time_off_type") or {}).get("attributes", {})
        category = str(type_attrs.get("category", "") or "").strip().lower()
        column = CATEGORY_COLUMN.get(category)
        if column is None:
            unknown_categories.add(category or "<vuota>")
            column = FALLBACK_COLUMN
        eid = _employee_id(attrs)
        emp = employees.get(eid, {})
        department = emp.get("department", "unknown")
        end_raw = str(attrs.get("end_date", "") or "") or start_raw
        try:
            start_dt = datetime.strptime(start_raw[:10], "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_raw[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        for day in _weekdays(start_dt, end_dt):
            rows.append(
                {
                    "date": day.isoformat(),
                    "employee_id": eid,
                    "department": department,
                    "column": column,
                    "category": category,
                }
            )
    if skipped_status:
        log.info(f"  Skipped {skipped_status} day-based absences with non-approved status")
    if unknown_categories:
        log.warning(
            f"  Unmapped day categories → {FALLBACK_COLUMN}: {sorted(unknown_categories)}"
        )
    return rows


def expand_hour_absences(
    records: list[dict],
    employees: dict[str, dict],
    category_by_type: dict[str, str],
) -> list[dict]:
    ""






    rows: list[dict] = []
    unknown_categories: set[str] = set()
    skipped_status = 0
    for record in records:
        attrs = record.get("attributes", record)
        status = str(attrs.get("status", "") or "").strip().lower()
        if status in NOT_TAKEN_STATUSES:
            skipped_status += 1
            continue
        type_attrs = (attrs.get("absence_type") or {}).get("attributes", {})
        type_id = str(type_attrs.get("time_off_type_id", "") or "").strip()
        category = category_by_type.get(type_id, "")
        column = CATEGORY_COLUMN.get(category)
        if column is None:
            unknown_categories.add(category or f"time_off_type_id={type_id or '<empty>'}")
            column = FALLBACK_COLUMN
        eid = _employee_id(attrs)
        emp = employees.get(eid, {})
        department = emp.get("department", "unknown")
        daily_minutes = emp.get("daily_minutes", DEFAULT_DAILY_MINUTES) or DEFAULT_DAILY_MINUTES
        breakdowns = attrs.get("breakdowns") or []
        if not breakdowns:

            start_raw = str(attrs.get("start", "") or attrs.get("start_date", "") or "")
            breakdowns = [
                {"date": start_raw[:10], "effective_duration": attrs.get("effective_duration")}
            ]
        for item in breakdowns:
            day_raw = str(item.get("date", "") or "")[:10]
            if not day_raw:
                continue
            try:
                day = datetime.strptime(day_raw, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            try:
                minutes = float(item.get("effective_duration") or 0)
            except (TypeError, ValueError):
                minutes = 0.0
            rows.append(
                {
                    "date": day.isoformat(),
                    "employee_id": eid,
                    "department": department,
                    "column": column,
                    "category": category,
                    "minutes": minutes,
                    "day_equivalent": minutes / daily_minutes,
                }
            )
    if skipped_status:
        log.info(f"  Skipped {skipped_status} hourly absences with non-approved status")
    if unknown_categories:
        log.warning(
            f"  Unmapped hour categories → {FALLBACK_COLUMN}: {sorted(unknown_categories)}"
        )
    return rows


def build_daily(day_rows: list[dict], hour_rows: list[dict]) -> pd.DataFrame:
    ""






    day_df = pd.DataFrame(day_rows)
    hour_df = pd.DataFrame(hour_rows)

    frames = []
    if not day_df.empty:
        counts = (
            day_df.pivot_table(
                index="date", columns="column", values="employee_id", aggfunc="count"
            )
            .reindex(columns=COUNT_COLUMNS, fill_value=0)
            .fillna(0)
            .astype(int)
        )
        base = day_df.groupby("date").agg(
            total_absent=("employee_id", "nunique"),
            departments_affected=("department", "nunique"),
        )
        frames.append(base.join(counts))
    if not hour_df.empty:
        hourly = hour_df.groupby("date").agg(
            hourly_employees=("employee_id", "nunique"),
            hourly_minutes=("minutes", "sum"),
            hourly_day_equivalent=("day_equivalent", "sum"),
        )
        frames.append(hourly)

    if not frames:
        return pd.DataFrame()

    daily = pd.concat(frames, axis=1).fillna(0)
    daily.index.name = "date"
    daily = daily.reset_index()

    for col in ["total_absent", "departments_affected", *COUNT_COLUMNS, "hourly_employees"]:
        if col not in daily.columns:
            daily[col] = 0
        daily[col] = daily[col].astype(int)
    for col in ["hourly_minutes", "hourly_day_equivalent"]:
        if col not in daily.columns:
            daily[col] = 0.0
        daily[col] = daily[col].astype(float)



    ordered = [
        "date",
        "total_absent",
        "sickness_count",
        "vacation_count",
        "remote_count",
        "other_count",
        "departments_affected",
        "parental_count",
        "family_care_count",
        "public_duty_count",
        "hourly_employees",
        "hourly_minutes",
        "hourly_day_equivalent",
    ]
    daily = daily[ordered]
    daily["date"] = pd.to_datetime(daily["date"])
    return daily.sort_values("date").reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="Personio absences daily aggregation")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")



    if not ABSENCES_FILE.exists():
        log.error(f"Not found: {ABSENCES_FILE}")
        sys.exit(1)

    day_records = _load_records(ABSENCES_FILE)
    log.info(f"Loaded {len(day_records)} time-off records (days)")

    hour_records: list[dict] = []
    if ABSENCE_PERIODS_FILE.exists():
        hour_records = _load_records(ABSENCE_PERIODS_FILE)
        log.info(f"Loaded {len(hour_records)} absence-period records (hours)")
    else:
        log.warning(
            f"Hourly absences missing ({ABSENCE_PERIODS_FILE.name}): hourly_* columns set to zero"
        )

    employees = load_employee_index(EMPLOYEES_FILE)
    log.info(f"Loaded {len(employees)} employee→department mappings")
    category_by_type = load_category_by_type_id(ABSENCE_TYPES_FILE)
    if hour_records and not category_by_type:
        log.warning(
            f"No category from {ABSENCE_TYPES_FILE.name}: hours will end up in other_count"
        )

    day_rows = expand_day_absences(day_records, employees)
    hour_rows = expand_hour_absences(hour_records, employees, category_by_type)
    log.info(f"Expanded to {len(day_rows)} absence-days (days) + {len(hour_rows)} (hours)")

    daily = build_daily(day_rows, hour_rows)
    if daily.empty:
        log.error("No absence day aggregated: input present but unusable")
        sys.exit(1)

    log.info(f"Aggregated to {len(daily)} days")
    log.info(f"  Date range: {daily['date'].min().date()} to {daily['date'].max().date()}")
    log.info(f"  Avg absent/day: {daily['total_absent'].mean():.1f}")
    log.info(f"  Peak absent/day: {daily['total_absent'].max()}")
    log.info(f"  Hours -> equivalent days: {daily['hourly_day_equivalent'].sum():.1f}")

    if args.dry_run:
        log.info("\nDRY RUN — not saving")
        log.info(daily.head(10).to_string())
    else:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        safe_write_parquet(daily, OUTPUT_FILE)
        log.info(f"Saved → {OUTPUT_FILE}")
        mark_last_run("l2-personio-absences-daily")


if __name__ == "__main__":
    main()
