#!/usr/bin/env python3
""









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
    # Synthetic DEMO data. Replace with the values from YOUR own lab reports.
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


def main():
    out = CLINICAL_PROCESSED_DIR
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    record_id = str(uuid.uuid4())[:8]

    for v in BLOOD_VALUES:
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
                "subject": v.get("subject", OWNER_SUBJECT),
            }
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    values_path = out / "values.parquet"
    safe_write_parquet(df, values_path)


    anomalies = df[df["is_anomaly"]]
    dates = df["date"].nunique()
    markers = df["marker"].nunique()

    print(f"\nClinical values built: {len(df)} rows")
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
