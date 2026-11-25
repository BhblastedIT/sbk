#!/usr/bin/env python3
""














from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    PERSONIO_DIR,
    RQ_DIR,
    safe_write_parquet,
)

log = logging.getLogger("rq-01")


def _load_terminated_employees() -> set[str]:
    ""
    terminated = set()
    personio_file = PERSONIO_DIR / "processed" / "employees.parquet"
    if not personio_file.exists():
        personio_file = PERSONIO_DIR / "employees.parquet"
    if not personio_file.exists():
        return terminated

    try:
        df = pd.read_parquet(personio_file)
        status_col = None
        for col in ["status", "employment_status", "Status"]:
            if col in df.columns:
                status_col = col
                break
        if status_col:
            term_df = df[df[status_col].str.lower().isin(["inactive", "terminated", "offboarded"])]
            email_col = None
            for col in ["email", "work_email", "Email"]:
                if col in df.columns:
                    email_col = col
                    break
            if email_col:
                terminated = set(term_df[email_col].dropna().str.lower())
    except Exception as exc:
        log.warning("Failed to load Personio terminated: %s", exc)

    return terminated


def _load_weighted_interactions() -> pd.DataFrame:
    ""
    rq_file = RQ_DIR / "interaction-weights.parquet"
    if not rq_file.exists():
        log.warning("RQ-00 output not found: %s. Run rq-00-weight-interactions.py first.", rq_file)
        return pd.DataFrame()


    return pd.read_parquet(rq_file, columns=["date", "to_addr", "weight"])


def main():
    parser = argparse.ArgumentParser(description="RQ-01: Temporal decay engine")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--person", type=str, help="Process single entity ID")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rq_temporal_decay import compute_relationship_decay

    interactions = _load_weighted_interactions()
    if interactions.empty:



        log.error(
            "No weighted interactions available (%s): nothing to compute, exiting with error.",
            RQ_DIR / "interaction-weights.parquet",
        )
        sys.exit(1)

    now = datetime.now(UTC)
    terminated_emails = _load_terminated_employees()


    if "date" in interactions.columns:
        interactions["date_parsed"] = pd.to_datetime(
            interactions["date"], errors="coerce", utc=True
        )
    else:
        log.warning("No 'date' column in interactions")
        return



    valid = interactions.dropna(subset=["date_parsed"])
    if valid.empty:
        log.warning("No interactions with valid dates")
        return


    grouped = valid.groupby("to_addr")
    log.info("Processing %d unique contacts", len(grouped))

    results = []
    state_counts = {"active": 0, "cooling": 0, "dormant": 0, "ended": 0}
    reactivation_count = 0

    for person, group in grouped:
        if args.person and args.person != str(person):
            continue

        dates = group["date_parsed"].dropna().tolist()
        if not dates:
            continue

        dates_sorted = sorted(dates)
        last_date = dates_sorted[-1]
        weighted_sum = group["weight"].sum()


        has_explicit_end = str(person).lower() in terminated_emails


        cutoff_30 = now - pd.Timedelta(days=30)
        recent_count = len([d for d in dates_sorted if d >= cutoff_30])

        result = compute_relationship_decay(
            score_at_last_interaction=weighted_sum,
            last_interaction_date=last_date,
            now=now,
            relationship_type="default",
            interaction_dates=dates_sorted,
            has_explicit_end=has_explicit_end,
            previous_state=None,
            recent_interaction_count=recent_count,
        )

        result["person"] = str(person)
        result["weighted_interaction_sum"] = round(weighted_sum, 2)
        result["interaction_count"] = len(dates)
        result["first_interaction"] = str(dates_sorted[0])
        result["last_interaction"] = str(dates_sorted[-1])
        results.append(result)

        state_counts[result["state"]] = state_counts.get(result["state"], 0) + 1
        if result["is_reactivation"]:
            reactivation_count += 1

    if not results:
        log.warning("No results computed")
        return

    df_out = pd.DataFrame(results)


    log.info("=" * 60)
    log.info("TOTAL: %d contacts processed", len(df_out))
    for state, count in sorted(state_counts.items()):
        pct = count / len(df_out) * 100 if df_out.shape[0] > 0 else 0
        log.info("  %-10s %5d (%5.1f%%)", state, count, pct)
    if reactivation_count:
        log.info("  Reactivations detected: %d", reactivation_count)


    log.info("")
    log.info("Score distribution (decayed):")
    for label, lo, hi in [
        ("8-10 inner", 8, 999),
        ("5-8 sympathy", 5, 8),
        ("3-5 active", 3, 5),
        ("1-3 full", 1, 3),
        ("<1 extended", 0, 1),
    ]:
        count = len(df_out[(df_out["decayed_score"] >= lo) & (df_out["decayed_score"] < hi)])
        log.info("  %-15s %5d", label, count)

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return

    RQ_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RQ_DIR / "decay-state.parquet"
    safe_write_parquet(df_out, output_path)
    log.info("Written: %s (%d rows)", output_path, len(df_out))


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-01-decay-engine", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
