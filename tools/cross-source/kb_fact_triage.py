""












from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd

log = logging.getLogger("kb.triage")


CONF_MAP = {"high": 0.85, "medium": 0.60, "low": 0.35}


NEED_ACTIVE_DAYS = 30
NEED_RESOLVED_DAYS = 90


NEED_WEIGHTS = {
    "need_active": 0.5,
    "need_resolved": 0.1,
    "need_recurring": 0.8,
}


def convert_confidence_to_float(df: pd.DataFrame) -> pd.DataFrame:
    ""



    if "confidence" not in df.columns:
        return df

    def _convert(val):
        if isinstance(val, int | float):
            return float(val)
        s = str(val).strip().lower()
        return CONF_MAP.get(s, 0.60)

    df["confidence"] = df["confidence"].apply(_convert)
    return df


def categorize_need_facts(df: pd.DataFrame) -> pd.DataFrame:
    ""












    df = df.copy()
    df["need_category"] = ""
    df["need_weight"] = 1.0

    needs_mask = df["fact_type"] == "need"
    if not needs_mask.any():
        return df


    now = datetime.now(UTC)
    active_cutoff = now - timedelta(days=NEED_ACTIVE_DAYS)
    resolved_cutoff = now - timedelta(days=NEED_RESOLVED_DAYS)

    source_dates = pd.to_datetime(df.loc[needs_mask, "source_date"], errors="coerce", utc=True)


    need_rows = df[needs_mask]
    recurring_combos = set()
    if "subject_person_id" in need_rows.columns and "predicate" in need_rows.columns:
        counts = need_rows.groupby(["subject_person_id", "predicate"]).size()
        for (pid, pred), count in counts.items():
            if count >= 3:
                recurring_combos.add((pid, pred))


    for idx in df[needs_mask].index:
        dt = source_dates.get(idx)
        pid = df.at[idx, "subject_person_id"] if "subject_person_id" in df.columns else ""
        pred = df.at[idx, "predicate"] if "predicate" in df.columns else ""

        is_recurring = (pid, pred) in recurring_combos

        if is_recurring:
            df.at[idx, "need_category"] = "need_recurring"
            df.at[idx, "need_weight"] = NEED_WEIGHTS["need_recurring"]
        elif pd.notna(dt) and dt >= active_cutoff:
            df.at[idx, "need_category"] = "need_active"
            df.at[idx, "need_weight"] = NEED_WEIGHTS["need_active"]
        elif pd.notna(dt) and dt < resolved_cutoff:
            df.at[idx, "need_category"] = "need_resolved"
            df.at[idx, "need_weight"] = NEED_WEIGHTS["need_resolved"]
        else:

            df.at[idx, "need_category"] = "need_active"
            df.at[idx, "need_weight"] = NEED_WEIGHTS["need_active"]

    return df


def triage_relationship_facts(df: pd.DataFrame) -> pd.DataFrame:
    ""







    df = convert_confidence_to_float(df)
    df = categorize_need_facts(df)
    return df
