""


















from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger("correlation-engine")



PHASE_THRESHOLDS = {1: 14, 2: 60, 3: 90}


def detect_phase(n_days: int, has_blood_tests: bool = False) -> int:
    ""





    if n_days >= PHASE_THRESHOLDS[3] and has_blood_tests:
        return 3
    if n_days >= PHASE_THRESHOLDS[2]:
        return 2
    if n_days >= PHASE_THRESHOLDS[1]:
        return 1
    return 0





def pairwise_correlation(
    x: pd.Series,
    y: pd.Series,
    method: str = "spearman",
) -> dict:
    ""



    mask = x.notna() & y.notna()
    x_clean = x[mask].values
    y_clean = y[mask].values

    n = len(x_clean)
    if n < MIN_N_CORRELATION:
        return {"correlation_r": np.nan, "p_value": np.nan, "n_observations": n}

    if method == "pearson":
        r, p = stats.pearsonr(x_clean, y_clean)
    elif method == "spearman":
        r, p = stats.spearmanr(x_clean, y_clean)
    else:
        raise ValueError(f"Unknown method: {method}. Use 'pearson' or 'spearman'.")

    return {"correlation_r": float(r), "p_value": float(p), "n_observations": n}


def rolling_correlation(
    x: pd.Series,
    y: pd.Series,
    window: int = 14,
    method: str = "spearman",
) -> pd.DataFrame:
    ""



    results = []

    for end in range(window, len(x) + 1):
        start = end - window
        x_win = x.iloc[start:end]
        y_win = y.iloc[start:end]

        result = pairwise_correlation(x_win, y_win, method)

        if hasattr(x.index, "__getitem__"):
            result["date"] = x.index[end - 1]
        results.append(result)

    return pd.DataFrame(results)


def compute_all_correlations(
    df: pd.DataFrame,
    pairs: list[tuple[str, str, int]],
    method: str = "spearman",
    min_r: float = 0.3,
) -> list[dict]:
    ""










    results = []

    for metric_a, metric_b, lag_days in pairs:
        if metric_a not in df.columns or metric_b not in df.columns:
            continue

        x = df[metric_a]
        if lag_days > 0:
            y = df[metric_b].shift(-lag_days)
        else:
            y = df[metric_b]

        result = pairwise_correlation(x, y, method)
        result["metric_a"] = metric_a
        result["metric_b"] = metric_b
        result["lag_days"] = lag_days
        result["method"] = method

        results.append(result)

    return results





def apply_bonferroni(
    results: list[dict],
    min_r: float = 0.3,
    alpha: float = 0.05,
) -> list[dict]:
    ""







    MODEL_METHODS = {"granger", "var", "bsts"}


    n_corr = len(
        [
            r
            for r in results
            if not np.isnan(r.get("p_value", np.nan)) and r.get("method", "") not in MODEL_METHODS
        ]
    )
    n_model = len(
        [
            r
            for r in results
            if not np.isnan(r.get("p_value", np.nan)) and r.get("method", "") in MODEL_METHODS
        ]
    )

    if n_corr == 0 and n_model == 0:
        return results

    for r in results:
        p = r.get("p_value", np.nan)
        corr_r = r.get("correlation_r", np.nan)
        method = r.get("method", "")

        if np.isnan(p):
            r["p_adjusted"] = np.nan
            r["is_significant"] = False
            r["direction"] = None
            continue


        n_tests = n_model if method in MODEL_METHODS else n_corr
        if n_tests == 0:
            n_tests = 1

        p_adj = min(p * n_tests, 1.0)
        r["p_adjusted"] = float(p_adj)


        if method in MODEL_METHODS and np.isnan(corr_r):
            r["is_significant"] = bool(p_adj < alpha)
            r["direction"] = None
        elif np.isnan(corr_r):
            r["is_significant"] = False
            r["direction"] = None
        else:
            r["is_significant"] = bool(p_adj < alpha and abs(corr_r) >= min_r)
            r["direction"] = "positive" if corr_r > 0 else "negative"

    return results





def apply_bh_correction(
    results: list[dict],
    min_r: float = 0.3,
    alpha: float = 0.05,
) -> list[dict]:
    ""






    MODEL_METHODS = {"granger", "var", "bsts"}


    corr_indices = []
    model_indices = []
    for i, r in enumerate(results):
        p = r.get("p_value", np.nan)
        if np.isnan(p):
            continue
        if r.get("method", "") in MODEL_METHODS:
            model_indices.append(i)
        else:
            corr_indices.append(i)

    def _bh_adjust(indices: list[int]) -> None:
        if not indices:
            return

        sorted_idx = sorted(indices, key=lambda i: results[i].get("p_value", 1.0))
        m = len(sorted_idx)
        for rank, i in enumerate(sorted_idx, 1):
            p = results[i]["p_value"]
            p_adj = min(p * m / rank, 1.0)
            results[i]["p_adjusted"] = float(p_adj)


        for j in range(len(sorted_idx) - 2, -1, -1):
            i_curr = sorted_idx[j]
            i_next = sorted_idx[j + 1]
            if results[i_curr]["p_adjusted"] > results[i_next]["p_adjusted"]:
                results[i_curr]["p_adjusted"] = results[i_next]["p_adjusted"]

    _bh_adjust(corr_indices)
    _bh_adjust(model_indices)


    for r in results:
        p = r.get("p_value", np.nan)
        corr_r = r.get("correlation_r", np.nan)
        method = r.get("method", "")

        if np.isnan(p):
            r.setdefault("p_adjusted", np.nan)
            r["is_significant"] = False
            r["direction"] = None
            continue

        p_adj = r.get("p_adjusted", p)

        if method in MODEL_METHODS and np.isnan(corr_r):
            r["is_significant"] = bool(p_adj < alpha)
            r["direction"] = None
        elif np.isnan(corr_r):
            r["is_significant"] = False
            r["direction"] = None
        else:
            r["is_significant"] = bool(p_adj < alpha and abs(corr_r) >= min_r)
            r["direction"] = "positive" if corr_r > 0 else "negative"

    return results





def fisher_ci(r: float, n: int, confidence: float = 0.95) -> tuple[float, float]:
    ""









    if np.isnan(r) or n < 4:
        return (np.nan, np.nan)

    z = np.arctanh(r)
    se = 1.0 / np.sqrt(n - 3)
    z_crit = stats.norm.ppf((1 + confidence) / 2)

    ci_low = np.tanh(z - z_crit * se)
    ci_high = np.tanh(z + z_crit * se)

    return (float(ci_low), float(ci_high))


def add_confidence_intervals(results: list[dict], confidence: float = 0.95) -> list[dict]:
    ""
    for r in results:
        corr_r = r.get("correlation_r", np.nan)
        n = r.get("n_observations", 0)
        ci_low, ci_high = fisher_ci(corr_r, n, confidence)
        r["ci_lower"] = ci_low
        r["ci_upper"] = ci_high
        r["ci_width"] = (
            float(ci_high - ci_low) if not (np.isnan(ci_low) or np.isnan(ci_high)) else np.nan
        )
    return results





def classify_effect_size(r: float) -> str:
    ""





    if np.isnan(r):
        return "none"
    abs_r = abs(r)
    if abs_r >= 0.50:
        return "large"
    if abs_r >= 0.30:
        return "medium"
    if abs_r >= 0.10:
        return "small"
    return "negligible"


def add_effect_sizes(results: list[dict]) -> list[dict]:
    ""
    for r in results:
        corr_r = r.get("correlation_r", np.nan)
        r["effect_size"] = classify_effect_size(corr_r)
    return results





def adf_test(series: pd.Series) -> dict:
    ""




    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return {"error": "statsmodels not installed"}

    clean = series.dropna()
    if len(clean) < 20:
        return {"error": f"insufficient data ({len(clean)} points, need 20+)"}

    try:
        result = adfuller(clean.values, autolag="AIC")
        return {
            "test_statistic": float(result[0]),
            "p_value": float(result[1]),
            "n_lags": int(result[2]),
            "n_observations": int(result[3]),
            "is_stationary": bool(result[1] < 0.05),
        }
    except Exception as e:
        return {"error": str(e)}





def seasonal_decompose(
    series: pd.Series,
    period: int = 7,
) -> dict:
    ""








    try:
        from statsmodels.tsa.seasonal import STL
    except ImportError:
        return {"error": "statsmodels not installed"}

    clean = series.dropna()
    if len(clean) < 2 * period + 1:
        return {"error": f"insufficient data ({len(clean)} points, need {2 * period + 1}+)"}

    try:
        stl = STL(clean, period=period, robust=True)
        result = stl.fit()
        return {
            "trend": result.trend,
            "seasonal": result.seasonal,
            "residual": result.resid,
            "period": period,
            "n_observations": len(clean),
        }
    except Exception as e:
        return {"error": str(e)}





def detect_change_points(
    series: pd.Series,
    n_bkps: int = 5,
    min_size: int = 14,
) -> dict:
    ""









    try:
        import ruptures as rpt
    except ImportError:
        return {"error": "ruptures not installed"}

    clean = series.dropna()
    if len(clean) < 2 * min_size:
        return {"error": f"insufficient data ({len(clean)} points, need {2 * min_size}+)"}

    values = clean.values.reshape(-1, 1)

    try:
        algo = rpt.Pelt(model="rbf", min_size=min_size).fit(values)
        bkps = algo.predict(pen=np.log(len(values)) * np.std(values) ** 2)


        dates = []
        if hasattr(clean.index, "__getitem__"):
            for b in bkps[:-1]:
                if b < len(clean.index):
                    dates.append(str(clean.index[b]))


        segments = []
        prev = 0
        for b in bkps:
            seg_values = clean.values[prev:b]
            segments.append(
                {
                    "start_idx": prev,
                    "end_idx": b,
                    "mean": float(np.mean(seg_values)),
                    "std": float(np.std(seg_values)),
                    "n": len(seg_values),
                }
            )
            prev = b

        return {
            "breakpoints": [int(b) for b in bkps[:-1]],
            "breakpoint_dates": dates,
            "n_segments": len(segments),
            "segments": segments,
            "n_observations": len(clean),
        }
    except Exception as e:
        return {"error": str(e)}





def time_lagged_correlation(
    x: pd.Series,
    y: pd.Series,
    max_lag: int = 3,
    method: str = "spearman",
) -> pd.DataFrame:
    ""




    results = []

    for lag in range(0, max_lag + 1):
        if lag == 0:
            y_shifted = y
        else:
            y_shifted = y.shift(-lag)

        result = pairwise_correlation(x, y_shifted, method)
        result["lag"] = lag
        results.append(result)

    return pd.DataFrame(results)


def granger_causality(
    x: pd.Series,
    y: pd.Series,
    max_lag: int = 3,
) -> dict:
    ""




    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ImportError:
        log.warning("statsmodels not installed, skipping Granger causality")
        return {"error": "statsmodels not installed"}

    mask = x.notna() & y.notna()
    x_clean = x[mask].values
    y_clean = y[mask].values

    n = len(x_clean)
    min_granger = max(MIN_N_GRANGER, max_lag * 3 + 10)
    if n < min_granger:
        return {"error": f"insufficient data ({n} points, need {min_granger}+)"}

    data = np.column_stack([y_clean, x_clean])

    try:
        result = grangercausalitytests(data, maxlag=max_lag, verbose=False)
        output = {}
        for lag_val in range(1, max_lag + 1):
            tests = result[lag_val][0]
            output[f"lag_{lag_val}"] = {
                "f_stat": float(tests["ssr_ftest"][0]),
                "p_value": float(tests["ssr_ftest"][1]),
                "is_significant": bool(tests["ssr_ftest"][1] < 0.05),
            }
        return output
    except Exception as e:
        log.warning("Granger causality failed: %s", e)
        return {"error": str(e)}


def var_model(
    df: pd.DataFrame,
    target_cols: list[str],
    feature_cols: list[str],
    order: int = 2,
) -> dict:
    ""




    try:
        from statsmodels.tsa.api import VAR as VARModel
    except ImportError:
        log.warning("statsmodels not installed, skipping VAR model")
        return {"error": "statsmodels not installed"}

    all_cols = list(set(target_cols + feature_cols))
    data = df[all_cols].dropna()

    if len(data) < order * 3 + 10:
        return {"error": f"insufficient data ({len(data)} rows)"}

    try:
        model = VARModel(data)
        fitted = model.fit(order)

        return {
            "aic": float(fitted.aic),
            "bic": float(fitted.bic),
            "order": order,
            "n_observations": len(data),
            "columns": all_cols,
            "coefficients": {col: fitted.params[col].to_dict() for col in all_cols},
        }
    except Exception as e:
        log.warning("VAR model failed: %s", e)
        return {"error": str(e)}





def bsts_intervention(
    series: pd.Series,
    intervention_date: str,
    pre_period: int = 30,
    post_period: int = 30,
) -> dict:
    ""




    try:
        idx = series.index.get_loc(intervention_date)
    except KeyError:
        return {"error": f"intervention_date {intervention_date} not in series index"}

    pre = series.iloc[max(0, idx - pre_period) : idx].dropna()
    post = series.iloc[idx : idx + post_period].dropna()

    if len(pre) < MIN_N_BSTS or len(post) < MIN_N_BSTS:
        return {"error": "insufficient pre/post data"}

    pre_mean = float(pre.mean())
    pre_std = float(pre.std())
    post_mean = float(post.mean())

    if pre_std == 0:

        z_score = float("inf") if post_mean != pre_mean else 0.0
    else:

        se = pre_std / np.sqrt(len(post))
        z_score = (post_mean - pre_mean) / se

    if np.isinf(z_score):
        p_value = 0.0
    else:
        p_value = float(2 * (1 - stats.norm.cdf(abs(z_score))))

    return {
        "pre_mean": pre_mean,
        "post_mean": post_mean,
        "absolute_effect": float(post_mean - pre_mean),
        "relative_effect": float((post_mean - pre_mean) / pre_mean) if pre_mean != 0 else None,
        "z_score": z_score,
        "p_value": p_value,
        "is_significant": bool(p_value < 0.05),
        "pre_n": len(pre),
        "post_n": len(post),
    }


def dtw_similarity(
    pattern_a: np.ndarray | pd.Series,
    pattern_b: np.ndarray | pd.Series,
) -> float:
    ""




    a = np.asarray(pattern_a, dtype=float)
    b = np.asarray(pattern_b, dtype=float)

    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("inf")


    a_std = np.std(a)
    b_std = np.std(b)
    if a_std > 0:
        a = (a - np.mean(a)) / a_std
    if b_std > 0:
        b = (b - np.mean(b)) / b_std


    dtw_matrix = np.full((n + 1, m + 1), np.inf)
    dtw_matrix[0, 0] = 0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(a[i - 1] - b[j - 1])
            dtw_matrix[i, j] = cost + min(
                dtw_matrix[i - 1, j],
                dtw_matrix[i, j - 1],
                dtw_matrix[i - 1, j - 1],
            )

    return float(dtw_matrix[n, m])





MIN_N_CORRELATION = 30
MIN_N_GRANGER = 60
MIN_N_BSTS = 20


PERF_FRESHNESS_CONFIG = {
    "whoop": {"stale_days": 2, "critical_days": 7},
    "apple_health": {"stale_days": 14, "critical_days": 30},
    "clinical": {"stale_days": 120, "critical_days": 200},
    "email_stats": {"stale_days": 2, "critical_days": 7},
    "calendar_stats": {"stale_days": 2, "critical_days": 7},
    "slack_stats": {"stale_days": 2, "critical_days": 7},
}


# Clinical marker plausibility ranges: load from user config (default empty)
CLINICAL_PLAUSIBILITY: dict[str, dict] = {}


def compute_coverage(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, float]:
    ""



    if df.empty:
        return {}
    cols = columns if columns is not None else list(df.columns)
    n_rows = len(df)
    result = {}
    for col in cols:
        if col in df.columns:
            non_null = int(df[col].notna().sum())
            result[col] = round(non_null / n_rows * 100, 1) if n_rows > 0 else 0.0
    return result


def detect_gap_patterns(
    df: pd.DataFrame,
    key_columns: dict[str, str] | None = None,
) -> list[dict]:
    ""















    if df.empty:
        return []

    if key_columns is None:
        key_columns = {}
        whoop_cols = {"sleep_score", "recovery_score", "strain_score", "hrv_rmssd_ms"}
        behavioral_cols = {
            "email_sent_count",
            "meetings_count",
            "slack_messages_sent",
        }
        apple_cols = {"weight_kg", "steps", "active_energy_kcal", "resting_hr_apple"}
        for col in df.columns:
            if col in whoop_cols:
                key_columns[col] = "whoop"
            elif col in behavioral_cols:
                key_columns[col] = "behavioral"
            elif col in apple_cols:
                key_columns[col] = "apple_health"

    gaps = []
    dates = pd.DatetimeIndex(df.index)

    for col, source in key_columns.items():
        if col not in df.columns:
            continue


        if source == "apple_health":
            non_null_dates = dates[df[col].notna()]
            if len(non_null_dates) >= 2:
                last_val = non_null_dates.max()
                if len(dates) > 0:
                    end_date = dates.max()
                    gap_days = (end_date - last_val).days
                    if gap_days > 30:
                        gaps.append(
                            {
                                "source": "apple_health",
                                "column": col,
                                "gap_type": "stale_source",
                                "start_date": str(last_val.date()),
                                "end_date": str(end_date.date()),
                                "gap_days": gap_days,
                                "severity": "warning",
                            }
                        )
            continue


        is_nan = df[col].isna()

        is_weekday = dates.weekday < 5

        streak_start = None
        streak_len = 0

        for i in range(len(df)):
            if is_nan.iloc[i] and is_weekday[i]:
                if streak_start is None:
                    streak_start = i
                streak_len += 1
            else:
                if streak_len >= 3 and streak_start is not None:
                    gap_type = "unworn_streak" if source == "whoop" else "sync_issue"
                    gaps.append(
                        {
                            "source": source,
                            "column": col,
                            "gap_type": gap_type,
                            "start_date": str(dates[streak_start].date()),
                            "end_date": str(dates[streak_start + streak_len - 1].date()),
                            "gap_days": streak_len,
                            "severity": "warning",
                        }
                    )
                streak_start = None
                streak_len = 0


        if streak_len >= 3 and streak_start is not None:
            gap_type = "unworn_streak" if source == "whoop" else "sync_issue"
            gaps.append(
                {
                    "source": source,
                    "column": col,
                    "gap_type": gap_type,
                    "start_date": str(dates[streak_start].date()),
                    "end_date": str(dates[streak_start + streak_len - 1].date()),
                    "gap_days": streak_len,
                    "severity": "warning",
                }
            )

    return gaps


def check_source_freshness(
    last_runs: dict[str, datetime],
    config: dict | None = None,
) -> list[dict]:
    ""








    cfg = config or PERF_FRESHNESS_CONFIG
    now = datetime.now(UTC)
    results = []

    for source, thresholds in cfg.items():
        last = last_runs.get(source)
        if last is None:
            results.append(
                {
                    "source": source,
                    "status": "missing",
                    "last_sync": None,
                    "days_ago": None,
                }
            )
            continue


        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)

        delta = (now - last).total_seconds() / 86400.0
        if delta >= thresholds["critical_days"]:
            status = "critical"
        elif delta >= thresholds["stale_days"]:
            status = "stale"
        else:
            status = "fresh"

        results.append(
            {
                "source": source,
                "status": status,
                "last_sync": last.isoformat(),
                "days_ago": round(delta, 1),
            }
        )

    return results


def check_correlation_stability(
    df: pd.DataFrame,
    metric_a: str,
    metric_b: str,
    recent_window: int = 60,
    method: str = "spearman",
) -> dict:
    ""





    if metric_a not in df.columns or metric_b not in df.columns:
        return {"error": "columns not found"}

    full = pairwise_correlation(df[metric_a], df[metric_b], method)
    full_r = full["correlation_r"]

    recent_df = df.iloc[-recent_window:] if len(df) > recent_window else df
    recent = pairwise_correlation(recent_df[metric_a], recent_df[metric_b], method)
    recent_r = recent["correlation_r"]

    if np.isnan(full_r) or np.isnan(recent_r):
        return {
            "full_r": full_r,
            "recent_r": recent_r,
            "delta_r": np.nan,
            "is_stable": False,
            "trend": "insufficient_data",
        }

    delta = recent_r - full_r


    if abs(delta) < 0.20:
        trend = "stable"
    elif np.sign(full_r) != np.sign(recent_r) and abs(full_r) > 0.10:
        trend = "reversed"
    elif abs(recent_r) > abs(full_r):
        trend = "strengthening"
    else:
        trend = "weakening"

    return {
        "full_r": float(full_r),
        "recent_r": float(recent_r),
        "delta_r": float(delta),
        "is_stable": bool(abs(delta) < 0.20),
        "trend": trend,
    }


def compute_confidence_level(
    r: float,
    p_adj: float,
    n: int,
    ci_width: float,
    is_stable: bool,
) -> str:
    ""









    if np.isnan(r) or np.isnan(p_adj):
        return "low"

    score = 0
    if n >= 60:
        score += 2
    elif n >= 30:
        score += 1

    if not np.isnan(ci_width):
        if ci_width < 0.40:
            score += 2
        elif ci_width < 0.60:
            score += 1

    if is_stable:
        score += 1

    if abs(r) >= 0.50:
        score += 1

    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def validate_clinical_values(df: pd.DataFrame) -> list[dict]:
    ""




    violations = []
    if df.empty or "marker" not in df.columns or "value" not in df.columns:
        return violations

    for _, row in df.iterrows():
        marker = row["marker"]
        value = row["value"]
        if pd.isna(value) or marker not in CLINICAL_PLAUSIBILITY:
            continue
        bounds = CLINICAL_PLAUSIBILITY[marker]
        if value < bounds["min"] or value > bounds["max"]:
            violations.append(
                {
                    "marker": marker,
                    "value": float(value),
                    "expected_min": bounds["min"],
                    "expected_max": bounds["max"],
                    "unit": bounds["unit"],
                    "date": str(row.get("date", "")),
                    "severity": "error",
                }
            )

    return violations


def check_hr_consistency(
    whoop_hr: pd.Series,
    apple_hr: pd.Series,
    tolerance_bpm: int = 5,
) -> dict:
    ""









    combined = pd.DataFrame({"whoop": whoop_hr, "apple": apple_hr}).dropna()

    if combined.empty:
        return {"match_pct": 0.0, "mean_delta": np.nan, "outlier_dates": [], "n_compared": 0}

    delta = (combined["whoop"] - combined["apple"]).abs()
    matches = (delta <= tolerance_bpm).sum()
    match_pct = round(float(matches / len(combined) * 100), 1)

    outlier_mask = delta > tolerance_bpm
    outlier_dates = [str(d) for d in combined.index[outlier_mask]]

    return {
        "match_pct": match_pct,
        "mean_delta": round(float(delta.mean()), 1),
        "outlier_dates": outlier_dates,
        "n_compared": len(combined),
    }


def compute_quality_score(
    source_health: list[dict],
    coverage: dict[str, float],
    n_bio_days: int,
    stability_results: list[dict] | None = None,
) -> int:
    ""




    if source_health:
        status_scores = {"fresh": 1.0, "stale": 0.5, "critical": 0.1, "missing": 0.0}
        freshness_vals = [status_scores.get(s.get("status", "missing"), 0.0) for s in source_health]
        freshness_pct = sum(freshness_vals) / len(freshness_vals) * 100
    else:
        freshness_pct = 0.0


    if coverage:
        coverage_pct = sum(coverage.values()) / len(coverage)
    else:
        coverage_pct = 0.0


    sample_pct = min(n_bio_days / 90.0, 1.0) * 100


    if stability_results:
        stable_count = sum(1 for s in stability_results if s.get("is_stable", False))
        stability_pct = stable_count / len(stability_results) * 100
    else:
        stability_pct = 50.0

    score = 0.40 * freshness_pct + 0.30 * coverage_pct + 0.20 * sample_pct + 0.10 * stability_pct

    return max(0, min(100, int(round(score))))
