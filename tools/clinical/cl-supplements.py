#!/usr/bin/env python3
"""Supplement tracking: add, stop and list the supplements you take (dose, unit, frequency, dates), kept in
supplements.parquet and shown as interventions next to the lab values.
"""

import argparse
import logging
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import CLINICAL_PROCESSED_DIR, OWNER_SUBJECT, safe_write_parquet  # noqa: E402

log = logging.getLogger("cl-supplements")

SUPPLEMENTS_FILE = "supplements.parquet"

COLUMNS = [
    "supplement_id",
    "subject",
    "supplement",
    "brand",
    "dose",
    "unit",
    "frequency",
    "start_date",
    "end_date",
    "protocol_phase",
    "notes",
    "created_at",
]





def load_supplements(clinical_dir: Path | None = None) -> pd.DataFrame:
    ""
    d = clinical_dir or CLINICAL_PROCESSED_DIR
    path = d / SUPPLEMENTS_FILE
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception as e:
            log.warning("Failed to load %s: %s", path, e)
    return pd.DataFrame(columns=COLUMNS)


def save_supplements(df: pd.DataFrame, clinical_dir: Path | None = None) -> None:
    ""
    d = clinical_dir or CLINICAL_PROCESSED_DIR
    d.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(df, d / SUPPLEMENTS_FILE)


def add_supplement(
    supplement: str,
    dose: float,
    unit: str,
    frequency: str,
    start_date: str,
    subject: str = OWNER_SUBJECT,
    brand: str | None = None,
    protocol_phase: str | None = None,
    notes: str | None = None,
    clinical_dir: Path | None = None,
) -> pd.DataFrame:
    ""
    df = load_supplements(clinical_dir)
    new_row = {
        "supplement_id": str(uuid.uuid4())[:8],
        "subject": subject,
        "supplement": supplement,
        "brand": brand,
        "dose": dose,
        "unit": unit,
        "frequency": frequency,
        "start_date": start_date,
        "end_date": None,
        "protocol_phase": protocol_phase,
        "notes": notes,
        "created_at": datetime.now(UTC).isoformat(),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_supplements(df, clinical_dir)
    log.info("Added supplement: %s %s %s (%s)", supplement, dose, unit, frequency)
    return df


def stop_supplement(
    supplement: str,
    end_date: str,
    subject: str = OWNER_SUBJECT,
    clinical_dir: Path | None = None,
) -> pd.DataFrame:
    ""
    df = load_supplements(clinical_dir)
    mask = (df["supplement"] == supplement) & (df["subject"] == subject) & (df["end_date"].isna())
    if mask.any():
        idx = df[mask].index[-1]
        df.loc[idx, "end_date"] = end_date
        save_supplements(df, clinical_dir)
        log.info("Stopped supplement: %s (end: %s)", supplement, end_date)
    else:
        log.warning("No active supplement '%s' found for subject '%s'", supplement, subject)
    return df


def list_supplements(
    subject: str = OWNER_SUBJECT,
    active_only: bool = False,
    clinical_dir: Path | None = None,
) -> pd.DataFrame:
    ""
    df = load_supplements(clinical_dir)
    if df.empty:
        return df
    df = df[df["subject"] == subject]
    if active_only:
        df = df[df["end_date"].isna()]
    return df


def get_intervention_events(
    subject: str = OWNER_SUBJECT,
    min_days_since_start: int = 30,
    clinical_dir: Path | None = None,
) -> list[dict]:
    ""




    df = load_supplements(clinical_dir)
    if df.empty:
        return []

    df = df[df["subject"] == subject]
    today = date.today()
    events = []

    for _, row in df.iterrows():
        start = row["start_date"]
        if pd.isna(start):
            continue
        if isinstance(start, str):
            start_date = date.fromisoformat(start)
        else:
            start_date = pd.Timestamp(start).date()

        days = (today - start_date).days
        if days >= min_days_since_start:
            events.append(
                {
                    "supplement": row["supplement"],
                    "intervention_date": row["start_date"],
                    "days_since_start": days,
                    "dose": row.get("dose"),
                    "unit": row.get("unit"),
                    "frequency": row.get("frequency"),
                    "active": pd.isna(row.get("end_date")),
                }
            )

    return events





def main():
    parser = argparse.ArgumentParser(description="Supplement tracking — SBK")
    sub = parser.add_subparsers(dest="command", required=True)


    p_add = sub.add_parser("add", help="Add a supplement")
    p_add.add_argument("--supplement", required=True, help="Supplement name")
    p_add.add_argument("--dose", type=float, required=True, help="Dose amount")
    p_add.add_argument("--unit", required=True, help="Dose unit (mg, IU, g, etc.)")
    p_add.add_argument("--frequency", required=True, help="Frequency (1x/day, 2x/day, etc.)")
    p_add.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    p_add.add_argument("--subject", default=OWNER_SUBJECT or None, required=not OWNER_SUBJECT, help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)")
    p_add.add_argument("--brand", help="Brand name")
    p_add.add_argument("--phase", help="Protocol phase")
    p_add.add_argument("--notes", help="Notes")


    p_stop = sub.add_parser("stop", help="Stop a supplement")
    p_stop.add_argument("--supplement", required=True, help="Supplement name")
    p_stop.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    p_stop.add_argument("--subject", default=OWNER_SUBJECT or None, required=not OWNER_SUBJECT, help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)")


    p_list = sub.add_parser("list", help="List supplements")
    p_list.add_argument("--active-only", action="store_true", help="Show only active")
    p_list.add_argument("--subject", default=OWNER_SUBJECT or None, required=not OWNER_SUBJECT, help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)")


    p_int = sub.add_parser("interventions", help="List intervention events for BSTS")
    p_int.add_argument("--min-days", type=int, default=30, help="Min days since start")
    p_int.add_argument("--subject", default=OWNER_SUBJECT or None, required=not OWNER_SUBJECT, help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.command == "add":
        add_supplement(
            args.supplement,
            args.dose,
            args.unit,
            args.frequency,
            args.start_date,
            subject=args.subject,
            brand=args.brand,
            protocol_phase=args.phase,
            notes=args.notes,
        )
        print(f"Added: {args.supplement} {args.dose}{args.unit} {args.frequency}")

    elif args.command == "stop":
        stop_supplement(args.supplement, args.end_date, subject=args.subject)
        print(f"Stopped: {args.supplement} (end: {args.end_date})")

    elif args.command == "list":
        df = list_supplements(subject=args.subject, active_only=args.active_only)
        if df.empty:
            print("No supplements found.")
        else:
            for _, row in df.iterrows():
                status = "ACTIVE" if pd.isna(row["end_date"]) else f"stopped {row['end_date']}"
                print(
                    f"  {row['supplement']} {row['dose']}{row['unit']} "
                    f"{row['frequency']} (since {row['start_date']}) [{status}]"
                )

    elif args.command == "interventions":
        events = get_intervention_events(subject=args.subject, min_days_since_start=args.min_days)
        if not events:
            print("No intervention events found.")
        else:
            for ev in events:
                status = "active" if ev["active"] else "stopped"
                print(
                    f"  {ev['supplement']} — started {ev['intervention_date']} "
                    f"({ev['days_since_start']}d ago, {status})"
                )


if __name__ == "__main__":
    main()
