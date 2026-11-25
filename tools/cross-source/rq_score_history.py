""






from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger("rq.score_history")


def append_score_snapshot(
    scores_df: pd.DataFrame,
    history_path: Path,
    run_date: date | None = None,
) -> None:
    ""






    if scores_df.empty:
        return

    run_dt = run_date or date.today()
    snapshot = scores_df.copy()
    snapshot["run_date"] = pd.Timestamp(run_dt)


    keep_cols = [
        "person",
        "run_date",
        "score",
        "dunbar_circle",
        "relationship_type",
        "confidence",
    ]
    available = [c for c in keep_cols if c in snapshot.columns]
    snapshot = snapshot[available]

    if history_path.exists():
        existing = pd.read_parquet(history_path)
        combined = pd.concat([existing, snapshot], ignore_index=True)

        cutoff = pd.Timestamp.now() - pd.Timedelta(days=730)
        combined = combined[combined["run_date"] >= cutoff]
    else:
        combined = snapshot


    tmp = history_path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp, index=False)
    tmp.replace(history_path)
    log.info("Score history: %d total snapshots (%d this run)", len(combined), len(snapshot))


def compute_score_diff(
    current_df: pd.DataFrame,
    history_path: Path,
) -> pd.DataFrame:
    ""



    if not history_path.exists() or current_df.empty:
        return pd.DataFrame()

    history = pd.read_parquet(history_path)
    if "run_date" not in history.columns or "person" not in history.columns:
        return pd.DataFrame()


    dates = sorted(history["run_date"].unique())
    if len(dates) < 2:
        return pd.DataFrame()

    prev_date = dates[-2]
    prev = history[history["run_date"] == prev_date].set_index("person")

    curr = current_df.set_index("person") if "person" in current_df.columns else current_df

    if "score" not in prev.columns or "score" not in curr.columns:
        return pd.DataFrame()


    common = prev.index.intersection(curr.index)
    if len(common) == 0:
        return pd.DataFrame()

    diffs = []
    for pid in common:
        delta = float(curr.loc[pid, "score"]) - float(prev.loc[pid, "score"])
        diffs.append(
            {
                "person": pid,
                "score_delta": round(delta, 2),
                "is_significant": abs(delta) > 0.5,
            }
        )

    return pd.DataFrame(diffs)


def compute_trends(
    history_path: Path,
    lookback_30d: int = 30,
    lookback_90d: int = 90,
) -> pd.DataFrame:
    ""




    if not history_path.exists():
        return pd.DataFrame()

    history = pd.read_parquet(history_path)
    if history.empty or "run_date" not in history.columns:
        return pd.DataFrame()

    now = pd.Timestamp.now()
    results = []

    for person, group in history.groupby("person"):
        if len(group) < 2:
            continue

        group = group.sort_values("run_date")
        scores = group[["run_date", "score"]].dropna()


        recent_30 = scores[scores["run_date"] >= now - pd.Timedelta(days=lookback_30d)]
        trend_30d = _compute_slope(recent_30) if len(recent_30) >= 2 else 0.0


        recent_90 = scores[scores["run_date"] >= now - pd.Timedelta(days=lookback_90d)]
        trend_90d = _compute_slope(recent_90) if len(recent_90) >= 2 else 0.0


        pattern = _classify_pattern(trend_30d, trend_90d, scores)

        results.append(
            {
                "person": person,
                "trend_30d": round(trend_30d, 4),
                "trend_90d": round(trend_90d, 4),
                "pattern": pattern,
            }
        )

    return pd.DataFrame(results)


def _compute_slope(scores_df: pd.DataFrame) -> float:
    ""
    if len(scores_df) < 2:
        return 0.0
    first = scores_df.iloc[0]
    last = scores_df.iloc[-1]
    days = (last["run_date"] - first["run_date"]).days
    if days <= 0:
        return 0.0
    return (float(last["score"]) - float(first["score"])) / days


def _classify_pattern(trend_30d: float, trend_90d: float, scores: pd.DataFrame) -> str:
    ""
    if trend_30d > 0.01 and trend_90d > 0.005:
        return "strengthening"
    if trend_30d < -0.01 and trend_90d < -0.005:
        return "cooling"
    if len(scores) >= 3:
        last_score = float(scores.iloc[-1]["score"])
        prev_score = float(scores.iloc[-2]["score"])
        if last_score < 1.5 and prev_score >= 3.0:
            return "breaking"
        if last_score >= 3.0 and prev_score < 1.5:
            return "rekindling"
    return "stable"
