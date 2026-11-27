#!/usr/bin/env python3
"""Adds lab values you type by hand to the clinical values table (<data root>/clinical/processed/values.parquet).

Write a CSV from your lab reports with the columns date (YYYY-MM-DD), marker, value, unit, ref_min, ref_max and,
optionally, subject, and pass it with --file. The rows are added to the table: a row with the same date, marker
and subject replaces the old one, and the values parsed by cl-l1-parse.py stay. --demo adds five synthetic rows
instead, to try cl-alerts.py, and only while the table is empty. Nothing leaves your machine.

Usage: uv run python tools/clinical/cl-build-values.py --file my-values.csv [--subject <label>]
"""

import argparse
import sys
import uuid
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import CLINICAL_PROCESSED_DIR, OWNER_SUBJECT, safe_write_parquet  # noqa: E402


def _load_normalize_unit():
    ""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cl_l1_parse", Path(__file__).resolve().parent / "cl-l1-parse.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize_unit


normalize_unit = _load_normalize_unit()




BLOOD_VALUES = [
    # Synthetic demo rows for --demo. Your own values come from the CSV you pass with --file.
    {"date": "2024-01-15", "marker": "glucose", "value": 92, "unit": "mg/dl", "ref_min": 60, "ref_max": 110},
    {"date": "2024-01-15", "marker": "total_cholesterol", "value": 185, "unit": "mg/dl", "ref_min": 0, "ref_max": 200},
    {"date": "2024-01-15", "marker": "hdl", "value": 55, "unit": "mg/dl", "ref_min": 40, "ref_max": None},
    {"date": "2024-06-20", "marker": "glucose", "value": 95, "unit": "mg/dl", "ref_min": 60, "ref_max": 110},
    {"date": "2024-06-20", "marker": "total_cholesterol", "value": 190, "unit": "mg/dl", "ref_min": 0, "ref_max": 200},
]


def compute_anomaly(value: float, ref_min: float | None, ref_max: float | None) -> bool:
    ""
    if ref_min is not None and value < ref_min:
        return True
    if ref_max is not None and value > ref_max:
        return True
    return False


def _number(x):
    if x is None or (isinstance(x, float) and pd.isna(x)) or str(x).strip() == "":
        return None
    return float(x)


def _read_csv(path: Path) -> list[dict]:
    """Rows of the CSV as dicts; date, marker and value are required."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"date", "marker", "value"} - set(df.columns)
    if missing:
        raise SystemExit(f"{path}: missing column(s) {', '.join(sorted(missing))}")
    out = []
    for n, r in enumerate(df.to_dict("records"), start=2):
        try:
            out.append(
                {
                    "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"),
                    "marker": r["marker"].strip(),
                    "value": float(r["value"]),
                    "unit": r.get("unit", "").strip(),
                    "ref_min": _number(r.get("ref_min")),
                    "ref_max": _number(r.get("ref_max")),
                    "subject": r.get("subject", "").strip() or None,
                }
            )
        except (ValueError, TypeError) as exc:
            raise SystemExit(f"{path}, line {n}: {exc}") from None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="CSV with your values (columns listed above)")
    src.add_argument("--demo", action="store_true", help="add five synthetic rows, only into an empty table")
    ap.add_argument("--subject", help="label of the person, for rows without one (default: your owner, lower case)")
    args = ap.parse_args()

    out = CLINICAL_PROCESSED_DIR
    values_path = out / "values.parquet"
    existing = pd.read_parquet(values_path) if values_path.exists() else pd.DataFrame()
    if args.demo and not existing.empty:
        print(f"{values_path} already holds values: --demo adds nothing.", file=sys.stderr)
        sys.exit(1)
    entries = BLOOD_VALUES if args.demo else _read_csv(args.file)
    subject = args.subject or OWNER_SUBJECT
    if not subject and any(not v.get("subject") for v in entries):
        print("No subject: set owner in sbk.config.json, or pass --subject <label>.", file=sys.stderr)
        sys.exit(1)

    rows = []
    record_id = str(uuid.uuid4())[:8]

    for v in entries:
        is_anomaly = compute_anomaly(v["value"], v["ref_min"], v["ref_max"])
        rows.append(
            {
                "record_id": f"manual-{record_id}",
                "date": v["date"],
                "marker": v["marker"],
                "value": v["value"],
                "unit": normalize_unit(v["unit"]),
                "ref_min": v["ref_min"],
                "ref_max": v["ref_max"],
                "is_anomaly": is_anomaly,
                "subject": v.get("subject") or subject,
            }
        )
    if not rows:
        print("The file has no rows: nothing added.")
        return

    df = pd.DataFrame(rows)
    if not existing.empty:
        existing = existing.copy()
        existing["date"] = existing["date"].astype(str)
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(
            subset=["date", "marker", "subject"], keep="last"
        )
    out.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(df.reset_index(drop=True), values_path)


    anomalies = df[df["is_anomaly"]]
    dates = df["date"].nunique()
    markers = df["marker"].nunique()

    print(f"\nClinical values: {len(rows)} rows added, {len(df)} in the table")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"  Unique dates: {dates}")
    print(f"  Unique markers: {markers}")
    print(f"  Anomalies: {len(anomalies)}")
    print("\nAnomalous markers:")
    for _, row in anomalies.iterrows():
        flag = "LOW" if row["ref_min"] is not None and row["value"] < row["ref_min"] else "HIGH"
        print(f"  [{row['date']}] {row['marker']}: {row['value']} {row['unit']} ({flag})")
    print(f"\nSaved to {values_path}")


if __name__ == "__main__":
    main()
