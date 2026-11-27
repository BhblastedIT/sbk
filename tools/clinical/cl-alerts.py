#!/usr/bin/env python3
"""Clinical alerts: from the lab values table, the markers out of range, worsening over time, close to a limit or
improving, written to alerts.json.
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import CLINICAL_PROCESSED_DIR, OWNER_SUBJECT  # noqa: E402

log = logging.getLogger("cl-alerts")





def _is_out_of_range(value: float, ref_min, ref_max) -> bool:
    ""
    if ref_min is not None and not pd.isna(ref_min) and value < float(ref_min):
        return True
    if ref_max is not None and not pd.isna(ref_max) and value > float(ref_max):
        return True
    return False


def _is_in_range(value: float, ref_min, ref_max) -> bool:
    ""
    return not _is_out_of_range(value, ref_min, ref_max)


def detect_out_of_range(history: list[dict]) -> list[dict]:
    ""







    if not history:
        return []

    alerts = []
    latest = history[-1]
    ref_min = latest.get("ref_min")
    ref_max = latest.get("ref_max")

    if ref_min is None and ref_max is None:
        return []
    if pd.isna(ref_min) if ref_min is not None else True:
        if pd.isna(ref_max) if ref_max is not None else True:
            return []

    if not _is_out_of_range(latest["value"], ref_min, ref_max):
        return []


    consecutive = 0
    for entry in reversed(history):
        if _is_out_of_range(entry["value"], ref_min, ref_max):
            consecutive += 1
        else:
            break

    if consecutive >= 2:
        alerts.append(
            {
                "type": "out_of_range_persistent",
                "severity": "HIGH",
                "marker": latest.get("marker", "unknown"),
                "value": latest["value"],
                "ref_min": ref_min,
                "ref_max": ref_max,
                "consecutive_count": consecutive,
                "date": latest.get("date", ""),
            }
        )
    else:
        alerts.append(
            {
                "type": "out_of_range_new",
                "severity": "HIGH",
                "marker": latest.get("marker", "unknown"),
                "value": latest["value"],
                "ref_min": ref_min,
                "ref_max": ref_max,
                "date": latest.get("date", ""),
            }
        )

    return alerts


def detect_worsening_trend(history: list[dict], min_points: int = 3) -> list[dict]:
    ""




    if len(history) < min_points:
        return []

    recent = history[-min_points:]
    ref_min = recent[-1].get("ref_min")
    ref_max = recent[-1].get("ref_max")
    values = [e["value"] for e in recent]


    if any(_is_out_of_range(v, ref_min, ref_max) for v in values):
        return []


    if ref_max is not None and not pd.isna(ref_max):
        ref_max_f = float(ref_max)
        if all(values[i] < values[i + 1] for i in range(len(values) - 1)):

            if values[-1] > values[0]:
                return [
                    {
                        "type": "worsening_trend",
                        "severity": "MEDIUM",
                        "marker": recent[-1].get("marker", "unknown"),
                        "direction": "increasing_toward_max",
                        "values": values,
                        "ref_max": ref_max_f,
                        "date": recent[-1].get("date", ""),
                    }
                ]


    if ref_min is not None and not pd.isna(ref_min):
        ref_min_f = float(ref_min)
        if all(values[i] > values[i + 1] for i in range(len(values) - 1)):
            if values[-1] < values[0]:
                return [
                    {
                        "type": "worsening_trend",
                        "severity": "MEDIUM",
                        "marker": recent[-1].get("marker", "unknown"),
                        "direction": "decreasing_toward_min",
                        "values": values,
                        "ref_min": ref_min_f,
                        "date": recent[-1].get("date", ""),
                    }
                ]

    return []


def detect_approaching_limit(latest: dict, threshold_pct: float = 0.10) -> list[dict]:
    ""
    value = latest["value"]
    ref_min = latest.get("ref_min")
    ref_max = latest.get("ref_max")

    if _is_out_of_range(value, ref_min, ref_max):
        return []

    alerts = []


    if ref_max is not None and not pd.isna(ref_max):
        ref_max_f = float(ref_max)
        if ref_max_f > 0:
            distance_pct = (ref_max_f - value) / ref_max_f
            if distance_pct <= threshold_pct:
                alerts.append(
                    {
                        "type": "approaching_limit",
                        "severity": "LOW",
                        "marker": latest.get("marker", "unknown"),
                        "value": value,
                        "boundary": "max",
                        "ref_max": ref_max_f,
                        "distance_pct": round(distance_pct * 100, 1),
                        "date": latest.get("date", ""),
                    }
                )


    if ref_min is not None and not pd.isna(ref_min):
        ref_min_f = float(ref_min)
        if ref_min_f > 0:
            distance_pct = (value - ref_min_f) / ref_min_f
            if distance_pct <= threshold_pct:
                alerts.append(
                    {
                        "type": "approaching_limit",
                        "severity": "LOW",
                        "marker": latest.get("marker", "unknown"),
                        "value": value,
                        "boundary": "min",
                        "ref_min": ref_min_f,
                        "distance_pct": round(distance_pct * 100, 1),
                        "date": latest.get("date", ""),
                    }
                )

    return alerts


def detect_improvement(history: list[dict]) -> list[dict]:
    ""
    if len(history) < 2:
        return []

    latest = history[-1]
    previous = history[-2]
    ref_min = latest.get("ref_min")
    ref_max = latest.get("ref_max")

    if _is_in_range(latest["value"], ref_min, ref_max) and _is_out_of_range(
        previous["value"], ref_min, ref_max
    ):
        return [
            {
                "type": "improvement",
                "severity": "INFO",
                "marker": latest.get("marker", "unknown"),
                "current_value": latest["value"],
                "previous_value": previous["value"],
                "date": latest.get("date", ""),
            }
        ]

    return []





def generate_alerts(
    values_df: pd.DataFrame,
    subject: str = OWNER_SUBJECT,
    output_path: Path | None = None,
) -> list[dict]:
    ""









    if values_df.empty:
        return []


    if "subject" in values_df.columns:
        df = values_df[values_df["subject"] == subject].copy()
    else:
        df = values_df.copy()

    if df.empty:
        return []


    if "date" in df.columns:
        df = df.sort_values("date")

    all_alerts = []

    for marker, group in df.groupby("marker"):
        history = group.to_dict("records")


        all_alerts.extend(detect_out_of_range(history))


        all_alerts.extend(detect_worsening_trend(history))


        if history:
            all_alerts.extend(detect_approaching_limit(history[-1]))


        all_alerts.extend(detect_improvement(history))


    now = datetime.now(UTC).isoformat()
    for alert in all_alerts:
        alert["subject"] = subject
        alert["generated_at"] = now


    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(all_alerts, indent=2, default=str))
        log.info("Wrote %d alerts to %s", len(all_alerts), output_path)

    return all_alerts





def main():
    parser = argparse.ArgumentParser(description="Clinical marker alerts — SBK")
    parser.add_argument(
        "--subject",
        default=OWNER_SUBJECT or None,
        required=not OWNER_SUBJECT,
        help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)",
    )
    parser.add_argument("--output", type=str, help="Output path for alerts.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    values_path = CLINICAL_PROCESSED_DIR / "values.parquet"
    if not values_path.exists():
        print("No values.parquet found. Run cl-build-values.py or cl-l1-parse.py first.")
        sys.exit(1)

    df = pd.read_parquet(values_path)
    out = Path(args.output) if args.output else CLINICAL_PROCESSED_DIR / "alerts.json"

    alerts = generate_alerts(df, subject=args.subject, output_path=out)

    print(f"\nAlerts generated: {len(alerts)}")
    for a in alerts:
        print(f"  [{a['severity']}] {a['type']} — {a['marker']} ({a.get('date', '')})")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
