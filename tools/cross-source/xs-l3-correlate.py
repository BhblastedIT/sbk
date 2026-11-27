#!/usr/bin/env python3
"""Correlation engine: lines up your daily health data (Whoop, Apple Health, lab values) with your daily activity
(email, calendar, Slack, relationship scores, NLP, HR) and looks for significant correlations, with Granger and
VAR models once there is enough history.
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
_LIB_DIR = _TOOLS_DIR / "lib"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from correlation_engine import (  # noqa: E402
    PHASE_THRESHOLDS,
    add_confidence_intervals,
    add_effect_sizes,
    adf_test,
    apply_bh_correction,
    apply_bonferroni,
    bsts_intervention,
    check_correlation_stability,
    check_source_freshness,
    compute_all_correlations,
    compute_confidence_level,
    compute_coverage,
    compute_quality_score,
    detect_change_points,
    detect_gap_patterns,
    detect_phase,
    granger_causality,
    seasonal_decompose,
    time_lagged_correlation,
    validate_clinical_values,
    var_model,
)

from sbk_config import (  # noqa: E402
    APPLE_HEALTH_PROCESSED_DIR,
    CALENDARS_DIR,
    CLINICAL_PROCESSED_DIR,
    EMAILS_DIR,
    PERFORMANCE_DIR,
    SLACK_DIR,
    WHOOP_PROCESSED_DIR,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("xs-l3-correlate")




PHASE1_PAIRS = [

    ("sleep_score", "email_sent_count", 0),
    ("sleep_score", "email_avg_sentiment", 0),
    ("recovery_score", "meetings_count", 0),
    ("recovery_score", "email_avg_response_min", 0),
    ("hrv_rmssd_ms", "email_avg_sentiment", 0),
    ("strain_score", "email_sent_count", 1),
    ("sleep_score", "meetings_count", 1),
    ("rem_sleep_ms", "content_created_count", 1),
    ("deep_sleep_ms", "action_items_generated", 1),
    ("workout_strain_total", "sleep_score", 1),

    ("sleep_score", "slack_messages_sent", 0),
    ("recovery_score", "slack_dm_count", 0),
    ("hrv_rmssd_ms", "meetings_count", 0),
    ("sleep_efficiency", "email_avg_sentiment", 0),
    ("resting_hr", "email_sent_count", 0),
    ("deep_sleep_ms", "meetings_count", 1),
    ("spo2_pct", "email_avg_sentiment", 0),
    ("recovery_score", "email_sent_count", 0),
    ("strain_score", "slack_messages_sent", 1),
    ("sleep_score", "meetings_total_minutes", 0),

    ("sleep_score", "back_to_back_count", 0),
    ("recovery_score", "total_communication_volume", 0),
    ("hrv_rmssd_ms", "email_avg_response_min", 0),
    ("strain_score", "meetings_total_minutes", 0),
    ("sleep_score", "meeting_free_hours", 0),
    ("sleep_score", "slack_messages_sent", 1),
    ("recovery_score", "email_unique_contacts", 0),
    ("strain_score", "action_items_generated", 1),
    ("deep_sleep_ms", "decisions_count", 1),

    ("sleep_score", "attendee_avg", 0),
    ("recovery_score", "proactive_outreach_count", 0),
    ("deep_sleep_ms", "new_contacts_count", 1),
    ("strain_score", "decisions_count", 0),
    ("recovery_score", "action_items_generated", 0),

    ("rem_sleep_ms", "cognitive_output_score", 1),
    ("deep_sleep_ms", "cognitive_output_score", 1),
    ("sleep_efficiency", "cognitive_output_score", 0),

    (
        "wake_time_deviation",
        "cognitive_output_score",
        0,
    ),
    ("wake_time_deviation", "email_avg_sentiment", 0),
    ("wake_time_hour", "decisions_count", 0),
    ("wake_time_hour", "action_items_generated", 0),

    ("sleep_score", "meeting_quality_score", 1),
    ("deep_sleep_ms", "meeting_quality_score", 1),
    ("recovery_score", "meeting_quality_score", 0),
    ("hrv_rmssd_ms", "meeting_quality_score", 0),

    ("strain_3d_mean", "proactive_outreach_count", 0),
    ("strain_3d_mean", "new_contacts_count", 0),
    ("strain_3d_mean", "relationship_maintenance_score", 0),

    ("hrv_rmssd_ms", "email_avg_sentiment", 1),
    ("recovery_score", "email_avg_sentiment", 1),
    ("strain_score", "email_avg_sentiment", 0),
]

PHASE2_GRANGER_PAIRS = [

    ("sleep_score", "email_avg_sentiment"),
    ("strain_score", "sleep_score"),
    ("recovery_score", "proactive_outreach_count"),

    ("hrv_rmssd_ms", "email_avg_response_min"),
    ("sleep_score", "meetings_count"),
    ("sleep_score", "slack_messages_sent"),
    ("email_sent_count", "strain_score"),
    ("meetings_count", "sleep_score"),
    ("recovery_score", "email_avg_sentiment"),

    ("sleep_score", "total_communication_volume"),
    ("recovery_score", "back_to_back_count"),
    ("hrv_rmssd_ms", "slack_messages_sent"),

    ("email_avg_sentiment", "hrv_rmssd_ms"),
    ("hrv_rmssd_ms", "cognitive_output_score"),
]


PHASE2_VAR_MODELS = [
    {
        "name": "bio-behavioral",
        "targets": ["email_sent_count", "meetings_count", "email_avg_sentiment"],
        "features": ["sleep_score", "hrv_rmssd_ms", "strain_score"],
    },
    {
        "name": "communication-volume",
        "targets": ["slack_messages_sent", "slack_dm_count", "email_sent_count"],
        "features": ["sleep_score", "recovery_score"],
    },
    {
        "name": "emotional-regulation",
        "targets": ["email_avg_sentiment", "meetings_count"],
        "features": ["hrv_rmssd_ms", "recovery_score"],
    },
]

PHASE2_VAR_TARGETS = [
    "email_sent_count",
    "meetings_count",
    "email_avg_sentiment",
    "slack_messages_sent",
    "total_communication_volume",
]
PHASE2_VAR_FEATURES = ["sleep_score", "hrv_rmssd_ms", "strain_score", "recovery_score"]





def load_whoop_daily(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    path = (data_dir or WHOOP_PROCESSED_DIR) / "daily.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.set_index("date")
    return df


def load_apple_health(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    path = (data_dir or APPLE_HEALTH_PROCESSED_DIR) / "metrics.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.set_index("date")
    return df


def load_clinical_values(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    path = (data_dir or CLINICAL_PROCESSED_DIR) / "values.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    return df


def load_email_stats(data_dir: Path | None = None) -> pd.DataFrame:
    ""




    email_dir = data_dir or EMAILS_DIR
    if not email_dir.exists():
        return pd.DataFrame()


    stats_path = email_dir / "daily-stats.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df

    return pd.DataFrame()


def load_calendar_stats(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    cal_dir = data_dir or CALENDARS_DIR
    stats_path = cal_dir / "daily-stats.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df
    return pd.DataFrame()


def load_slack_stats(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    slack_dir = data_dir or SLACK_DIR
    stats_path = slack_dir / "daily-stats.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df
    return pd.DataFrame()


def load_rq_stats(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    if data_dir is not None:
        stats_path = data_dir / "daily-stats.parquet"
    else:
        from sbk_config import DATA_ROOT

        stats_path = DATA_ROOT / "rq" / "daily-stats.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df
    return pd.DataFrame()


def load_nlp_stats(data_dir: Path | None = None) -> pd.DataFrame:
    ""
    if data_dir is not None:
        stats_path = data_dir / "daily-stats.parquet"
    else:
        from sbk_config import DATA_ROOT

        stats_path = DATA_ROOT / "l3" / "nlp" / "daily-stats.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df
    return pd.DataFrame()


def load_personio_stats(personio_dir: Path | None = None) -> pd.DataFrame:
    ""
    from sbk_config import DATA_ROOT

    if personio_dir is not None:
        stats_path = personio_dir / "absences-daily.parquet"
    else:
        stats_path = DATA_ROOT / "personio" / "processed" / "absences-daily.parquet"
    if stats_path.exists():
        df = pd.read_parquet(stats_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date")
        return df
    return pd.DataFrame()


def build_daily_features(
    whoop_dir: Path | None = None,
    apple_health_dir: Path | None = None,
    email_dir: Path | None = None,
    calendar_dir: Path | None = None,
    slack_dir: Path | None = None,
    rq_dir: Path | None = None,
    nlp_dir: Path | None = None,
    personio_dir: Path | None = None,
) -> pd.DataFrame:
    ""



    sources = {}


    wp = load_whoop_daily(whoop_dir)
    if not wp.empty:
        whoop_cols = [
            "sleep_score",
            "recovery_score",
            "strain_score",
            "hrv_rmssd_ms",
            "resting_hr",
            "rem_sleep_ms",
            "deep_sleep_ms",
            "sleep_efficiency",
            "hrv_delta_from_baseline",
            "recovery_zone",
            "workout_strain_total",
            "spo2_pct",
            "sleep_end",
        ]
        available = [c for c in whoop_cols if c in wp.columns]
        sources["whoop"] = wp[available]


    ah = load_apple_health(apple_health_dir)
    if not ah.empty:
        ah_cols = [
            "weight_kg",
            "body_fat_pct",
            "systolic_bp",
            "diastolic_bp",
            "steps",
            "active_energy_kcal",
            "resting_energy_kcal",
            "vo2max",
            "resting_hr_apple",
            "hrv_sdnn_apple",
            "apple_exercise_min",
            "apple_stand_hours",
        ]
        available = [c for c in ah_cols if c in ah.columns]
        if available:
            sources["apple_health"] = ah[available]


    em = load_email_stats(email_dir)
    if not em.empty:
        em_cols = [
            "email_sent_count",
            "email_received_count",
            "email_total_count",
            "email_thread_count",
            "email_new_thread_count",
            "email_reply_count",
            "email_avg_response_min",
            "email_median_response_min",
            "email_avg_sentiment",
            "email_unique_contacts",
            "email_attachment_count",
        ]
        available = [c for c in em_cols if c in em.columns]
        if available:
            sources["email"] = em[available]


    cal = load_calendar_stats(calendar_dir)
    if not cal.empty:
        cal_cols = [
            "meetings_count",
            "meetings_total_minutes",
            "first_meeting_hour",
            "last_meeting_hour",
            "back_to_back_count",
            "meeting_gap_avg_min",
            "longest_meeting_min",
            "attendee_avg",
            "solo_block_count",
        ]
        available = [c for c in cal_cols if c in cal.columns]
        if available:
            sources["calendar"] = cal[available]


    sl = load_slack_stats(slack_dir)
    if not sl.empty:
        sl_cols = [
            "slack_messages_sent",
            "slack_dm_count",
            "slack_channels_active",
            "slack_avg_response_min",
        ]
        available = [c for c in sl_cols if c in sl.columns]
        if available:
            sources["slack"] = sl[available]


    rq = load_rq_stats(rq_dir)
    if not rq.empty:
        rq_cols = [
            "proactive_outreach_count",
            "new_contacts_count",
            "relationship_maintenance_score",
        ]
        available = [c for c in rq_cols if c in rq.columns]
        if available:
            sources["rq"] = rq[available]


    nlp = load_nlp_stats(nlp_dir)
    if not nlp.empty:
        nlp_cols = ["action_items_generated", "decisions_count"]
        available = [c for c in nlp_cols if c in nlp.columns]
        if available:
            sources["nlp"] = nlp[available]


    pe = load_personio_stats(personio_dir)
    if not pe.empty:






        pe_cols = [
            "total_absent",
            "sickness_count",
            "vacation_count",
            "remote_count",
            "other_count",
            "parental_count",
            "family_care_count",
            "public_duty_count",
            "departments_affected",
            "hourly_employees",
            "hourly_minutes",
            "hourly_day_equivalent",
        ]
        available = [c for c in pe_cols if c in pe.columns]
        if available:
            sources["personio"] = pe[available]

    if not sources:
        return pd.DataFrame()


    result = None
    for name, df in sources.items():
        if result is None:
            result = df
        else:
            result = result.join(df, how="outer")

    result.index.name = "date"
    result = result.sort_index()



    comm_cols = ["email_sent_count", "email_received_count", "slack_messages_sent"]
    avail_comm = [c for c in comm_cols if c in result.columns]
    if avail_comm:
        result["total_communication_volume"] = result[avail_comm].sum(axis=1, min_count=1)


    if "meetings_total_minutes" in result.columns:
        result["meeting_free_hours"] = 24.0 - result["meetings_total_minutes"] / 60.0


    cog_cols = ["action_items_generated", "decisions_count"]
    avail_cog = [c for c in cog_cols if c in result.columns]
    if avail_cog:
        cog_raw = result[avail_cog].sum(axis=1, min_count=1)
        cog_mean = cog_raw.mean()
        cog_std = cog_raw.std()
        if cog_std > 0:
            result["cognitive_output_score"] = (cog_raw - cog_mean) / cog_std
        else:
            result["cognitive_output_score"] = 0.0


    if "strain_score" in result.columns:
        result["strain_3d_mean"] = result["strain_score"].rolling(3, min_periods=1).mean()


    if "sleep_end" in result.columns:
        sleep_end_dt = pd.to_datetime(result["sleep_end"], errors="coerce")
        result["wake_time_hour"] = sleep_end_dt.dt.hour + sleep_end_dt.dt.minute / 60.0

        wake_rolling = result["wake_time_hour"].rolling(30, min_periods=7).mean()
        result["wake_time_deviation"] = (result["wake_time_hour"] - wake_rolling).abs()

        result = result.drop(columns=["sleep_end"], errors="ignore")


    if "meetings_count" in result.columns:
        mq_parts = []
        meetings_safe = result["meetings_count"].replace(0, np.nan)
        if "action_items_generated" in result.columns:
            mq_parts.append(result["action_items_generated"] / meetings_safe)
        if "decisions_count" in result.columns:
            mq_parts.append(result["decisions_count"] / meetings_safe)
        if mq_parts:
            result["meeting_quality_score"] = pd.concat(mq_parts, axis=1).mean(axis=1)

    return result





def run_correlations(
    daily_features: pd.DataFrame,
    phase: int | None = None,
    window: int = 14,
    min_r: float = 0.3,
    min_p: float = 0.05,
    method: str = "spearman",
    has_blood: bool = False,
    blood_test_dates: list | None = None,
    correction: str = "auto",
) -> tuple[pd.DataFrame, dict]:
    ""







    if daily_features.empty:
        return pd.DataFrame(), {"active_phase": 0, "error": "no data"}


    whoop_cols = [
        c
        for c in daily_features.columns
        if c in {"sleep_score", "recovery_score", "strain_score", "hrv_rmssd_ms"}
    ]
    if whoop_cols:
        bio_mask = daily_features[whoop_cols].notna().any(axis=1)
        n_bio_days = int(bio_mask.sum())
    else:
        n_bio_days = 0

    detected_phase = phase if phase is not None else detect_phase(n_bio_days, has_blood)

    if detected_phase == 0:
        meta = {
            "active_phase": 0,
            "whoop_days": n_bio_days,
            "error": f"insufficient data ({n_bio_days} days, need 14+)",
        }
        return pd.DataFrame(), meta


    all_results = compute_all_correlations(daily_features, PHASE1_PAIRS, method, min_r)


    if detected_phase >= 2:

        for metric_a, metric_b in PHASE2_GRANGER_PAIRS:
            if metric_a in daily_features.columns and metric_b in daily_features.columns:
                gc_result = granger_causality(
                    daily_features[metric_a],
                    daily_features[metric_b],
                    max_lag=3,
                )
                if "error" not in gc_result:
                    for lag_key, lag_data in gc_result.items():
                        lag_num = int(lag_key.split("_")[1])
                        all_results.append(
                            {
                                "metric_a": metric_a,
                                "metric_b": metric_b,
                                "correlation_r": np.nan,
                                "p_value": lag_data["p_value"],
                                "lag_days": lag_num,
                                "method": "granger",
                                "n_observations": len(daily_features),
                            }
                        )


        for metric_a, metric_b, _ in PHASE1_PAIRS:
            if metric_a in daily_features.columns and metric_b in daily_features.columns:
                tlcc_df = time_lagged_correlation(
                    daily_features[metric_a],
                    daily_features[metric_b],
                    max_lag=3,
                    method=method,
                )
                if tlcc_df.empty or tlcc_df["correlation_r"].isna().all():
                    continue
                best = tlcc_df.loc[tlcc_df["correlation_r"].abs().idxmax()]
                if not np.isnan(best["correlation_r"]):
                    all_results.append(
                        {
                            "metric_a": metric_a,
                            "metric_b": metric_b,
                            "correlation_r": float(best["correlation_r"]),
                            "p_value": float(best["p_value"]),
                            "lag_days": int(best["lag"]),
                            "method": "tlcc",
                            "n_observations": int(best.get("n_observations", len(daily_features))),
                        }
                    )


        for var_spec in PHASE2_VAR_MODELS:
            available_targets = [c for c in var_spec["targets"] if c in daily_features.columns]
            available_features = [c for c in var_spec["features"] if c in daily_features.columns]
            if len(available_targets) >= 1 and len(available_features) >= 1:
                var_result = var_model(
                    daily_features, available_targets, available_features, order=2
                )
                if "error" not in var_result:
                    all_results.append(
                        {
                            "metric_a": ",".join(available_features),
                            "metric_b": ",".join(available_targets),
                            "correlation_r": np.nan,
                            "p_value": np.nan,
                            "lag_days": 0,
                            "method": "var",
                            "n_observations": var_result.get("n_observations", 0),
                            "var_aic": var_result.get("aic"),
                            "var_bic": var_result.get("bic"),
                            "var_model_name": var_spec["name"],
                        }
                    )


    if detected_phase >= 3 and blood_test_dates:

        bio_cols = [
            c
            for c in ["sleep_score", "recovery_score", "hrv_rmssd_ms"]
            if c in daily_features.columns
        ]

        behavioral_cols = [
            c
            for c in [
                "email_sent_count",
                "meetings_count",
                "cognitive_output_score",
                "meeting_quality_score",
                "total_communication_volume",
            ]
            if c in daily_features.columns
        ]
        bsts_cols = bio_cols + behavioral_cols
        for bt_date in blood_test_dates:
            for col in bsts_cols:
                series = daily_features[col].dropna()
                if len(series) < 30:
                    continue
                bsts_result = bsts_intervention(series, bt_date, pre_period=30, post_period=30)
                if "error" not in bsts_result:
                    all_results.append(
                        {
                            "metric_a": col,
                            "metric_b": f"blood_test_{bt_date}",
                            "correlation_r": np.nan,
                            "p_value": bsts_result["p_value"],
                            "lag_days": 0,
                            "method": "bsts",
                            "n_observations": bsts_result["pre_n"] + bsts_result["post_n"],
                            "absolute_effect": bsts_result["absolute_effect"],
                        }
                    )


    if detected_phase >= 3:
        try:
            import importlib.util as _ilu

            _supp_spec = _ilu.spec_from_file_location(
                "cl_supplements",
                Path(__file__).resolve().parent.parent / "clinical" / "cl-supplements.py",
            )
            _supp_mod = _ilu.module_from_spec(_supp_spec)
            _supp_spec.loader.exec_module(_supp_mod)
            supp_events = _supp_mod.get_intervention_events(min_days_since_start=30)
            for ev in supp_events:
                for col in bsts_cols:
                    series = daily_features[col].dropna()
                    if len(series) < 30:
                        continue
                    bsts_result = bsts_intervention(
                        series, ev["intervention_date"], pre_period=30, post_period=30
                    )
                    if "error" not in bsts_result:
                        all_results.append(
                            {
                                "metric_a": col,
                                "metric_b": f"supplement_{ev['supplement']}_{ev['intervention_date']}",
                                "correlation_r": np.nan,
                                "p_value": bsts_result["p_value"],
                                "lag_days": 0,
                                "method": "bsts_supplement",
                                "n_observations": bsts_result["pre_n"] + bsts_result["post_n"],
                                "absolute_effect": bsts_result["absolute_effect"],
                            }
                        )
            if supp_events:
                log.info("BSTS supplement: %d events, %d cols", len(supp_events), len(bsts_cols))
        except Exception as e:
            log.warning("Supplement BSTS skipped: %s", e)


    n_tests = len([r for r in all_results if not np.isnan(r.get("p_value", np.nan))])
    use_bh = correction == "bh" or (correction == "auto" and n_tests > 20)
    correction_used = "bh" if use_bh else "bonferroni"

    if use_bh:
        all_results = apply_bh_correction(all_results, min_r, min_p)
    else:
        all_results = apply_bonferroni(all_results, min_r, min_p)


    all_results = add_confidence_intervals(all_results)


    all_results = add_effect_sizes(all_results)


    now = datetime.now(UTC).isoformat()
    for r in all_results:
        r["window_days"] = window
        r["phase"] = detected_phase
        r["computed_at"] = now
        r["correction_method"] = correction_used


    if all_results:
        corr_df = pd.DataFrame(all_results)
    else:
        corr_df = pd.DataFrame()


    stationarity = {}
    key_cols = [
        c
        for c in daily_features.columns
        if c
        in {
            "sleep_score",
            "recovery_score",
            "strain_score",
            "hrv_rmssd_ms",
            "email_sent_count",
            "meetings_count",
            "slack_messages_sent",
        }
    ]
    for col in key_cols:
        adf = adf_test(daily_features[col])
        if "error" not in adf:
            stationarity[col] = {
                "is_stationary": adf["is_stationary"],
                "p_value": adf["p_value"],
            }


    change_points = {}
    for col in ["sleep_score", "recovery_score", "hrv_rmssd_ms"]:
        if col in daily_features.columns:
            cp = detect_change_points(daily_features[col])
            if "error" not in cp:
                change_points[col] = {
                    "n_segments": cp["n_segments"],
                    "breakpoint_dates": cp["breakpoint_dates"],
                }


    significant_count = sum(1 for r in all_results if r.get("is_significant", False))
    dates = daily_features.index
    meta = {
        "active_phase": detected_phase,
        "whoop_days": n_bio_days,
        "first_date": str(min(dates)) if len(dates) > 0 else None,
        "last_date": str(max(dates)) if len(dates) > 0 else None,
        "blood_tests_count": len(blood_test_dates) if blood_test_dates else 0,
        "total_correlations": len(all_results),
        "significant_correlations": significant_count,
        "correction_method": correction_used,
        "stationarity": stationarity,
        "change_points": change_points,
        "last_computed": now,
    }

    if detected_phase < 3:
        next_phase = detected_phase + 1
        days_needed = PHASE_THRESHOLDS.get(next_phase, 999)
        meta["next_phase_unlock"] = {
            "phase": next_phase,
            "days_needed": days_needed,
            "current": n_bio_days,
        }

    return corr_df, meta





def process(
    output_dir: Path | None = None,
    whoop_dir: Path | None = None,
    apple_health_dir: Path | None = None,
    clinical_dir: Path | None = None,
    email_dir: Path | None = None,
    calendar_dir: Path | None = None,
    slack_dir: Path | None = None,
    rq_dir: Path | None = None,
    nlp_dir: Path | None = None,
    personio_dir: Path | None = None,
    phase: int | None = None,
    window: int = 14,
    min_r: float = 0.3,
    min_p: float = 0.05,
    method: str = "spearman",
    correction: str = "auto",
    quality_report: bool = False,
    deseasonalize: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    ""




    out = output_dir or PERFORMANCE_DIR
    out.mkdir(parents=True, exist_ok=True)


    daily_features = build_daily_features(
        whoop_dir=whoop_dir,
        apple_health_dir=apple_health_dir,
        email_dir=email_dir,
        calendar_dir=calendar_dir,
        slack_dir=slack_dir,
        rq_dir=rq_dir,
        nlp_dir=nlp_dir,
        personio_dir=personio_dir,
    )

    if daily_features.empty:
        log.warning("No data available for daily features")
        meta = {"active_phase": 0, "error": "no data sources available"}
        empty_corr = pd.DataFrame()
        json_path = out / "correlation-meta.json"
        json_path.write_text(json.dumps(meta, indent=2, default=str))
        return daily_features, empty_corr, meta


    coverage = compute_coverage(daily_features)
    gap_patterns = detect_gap_patterns(daily_features)


    last_runs_path = (
        Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
        / "last-runs.json"
    )
    source_freshness = []
    if last_runs_path.exists():
        try:
            from datetime import datetime as _dt

            lr_data = json.loads(last_runs_path.read_text())
            lr_map = {}
            for key, ts_str in lr_data.items():

                key_map = {
                    "whoop": "whoop",
                    "apple-health": "apple_health",
                    "clinical": "clinical",
                    "email": "email_stats",
                    "calendar": "calendar_stats",
                    "slack": "slack_stats",
                }
                mapped = key_map.get(key)
                if mapped and isinstance(ts_str, str):
                    try:
                        lr_map[mapped] = (
                            _dt.fromisoformat(ts_str).replace(tzinfo=UTC)
                            if "+" not in ts_str
                            else _dt.fromisoformat(ts_str)
                        )
                    except (ValueError, TypeError):
                        pass
            source_freshness = check_source_freshness(lr_map)
        except Exception as e:
            log.warning("Could not read last-runs.json: %s", e)


    clinical_values = load_clinical_values(clinical_dir)
    clinical_violations = []
    if not clinical_values.empty:
        clinical_violations = validate_clinical_values(clinical_values)

    data_quality = {
        "coverage": coverage,
        "gap_patterns": gap_patterns,
        "source_freshness": source_freshness,
        "clinical_violations": clinical_violations,
    }

    if quality_report:
        print("\n── Data Quality Report ──")
        print(f"  Coverage: {len(coverage)} columns measured")
        low_cov = {k: v for k, v in coverage.items() if v < 50}
        if low_cov:
            print(f"  Low coverage (<50%): {low_cov}")
        print(f"  Gap patterns: {len(gap_patterns)} issues found")
        for g in gap_patterns:
            print(f"    {g['source']}/{g['column']}: {g['gap_type']} ({g['gap_days']}d)")
        print(f"  Source freshness: {len(source_freshness)} sources checked")
        for s in source_freshness:
            print(f"    {s['source']}: {s['status']} (days_ago={s['days_ago']})")
        if clinical_violations:
            print(f"  Clinical violations: {len(clinical_violations)}")
            for v in clinical_violations:
                print(
                    f"    {v['marker']}: {v['value']} (range {v['expected_min']}-{v['expected_max']})"
                )

    has_blood = False
    blood_test_dates = []
    if not clinical_values.empty and "date" in clinical_values.columns:
        clinical_values["date"] = pd.to_datetime(clinical_values["date"]).dt.date
        blood_test_dates = sorted(clinical_values["date"].unique().tolist())
        has_blood = len(blood_test_dates) > 0


    features_path = out / "daily-features.parquet"
    df_save = daily_features.reset_index()
    safe_write_parquet(df_save, features_path)
    log.info(
        "Saved daily-features.parquet (%d rows, %d columns)", len(df_save), len(df_save.columns)
    )


    corr_input = daily_features
    seasonal_confounds = []
    if deseasonalize and len(daily_features) >= 180:
        log.info("Deseasonalizing %d-day dataset", len(daily_features))
        deseasonalized = daily_features.copy()
        numeric_cols = daily_features.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            series = daily_features[col].dropna()
            if len(series) < 15:
                continue
            result = seasonal_decompose(series, period=7)
            if "error" not in result:

                deseas = result["trend"] + result["residual"]
                deseasonalized.loc[deseas.index, col] = deseas
        corr_input = deseasonalized


    corr_df, meta = run_correlations(
        corr_input,
        phase=phase,
        window=window,
        min_r=min_r,
        min_p=min_p,
        method=method,
        has_blood=has_blood,
        blood_test_dates=blood_test_dates,
        correction=correction,
    )


    if deseasonalize and len(daily_features) >= 180 and not corr_df.empty:
        raw_corr_df, _ = run_correlations(
            daily_features,
            phase=phase,
            window=window,
            min_r=min_r,
            min_p=min_p,
            method=method,
            has_blood=has_blood,
            blood_test_dates=blood_test_dates,
            correction=correction,
        )
        if not raw_corr_df.empty:
            for idx, row in corr_df.iterrows():
                ma, mb, lag = row.get("metric_a"), row.get("metric_b"), row.get("lag_days")
                r_deseas = row.get("correlation_r", np.nan)
                match = raw_corr_df[
                    (raw_corr_df["metric_a"] == ma)
                    & (raw_corr_df["metric_b"] == mb)
                    & (raw_corr_df["lag_days"] == lag)
                    & (raw_corr_df["method"] == row.get("method"))
                ]
                if not match.empty:
                    r_raw = match.iloc[0].get("correlation_r", np.nan)
                    if not np.isnan(r_raw) and not np.isnan(r_deseas):
                        if abs(r_raw - r_deseas) > 0.15:
                            corr_df.at[idx, "seasonal_confound_possible"] = True
                            seasonal_confounds.append(
                                {
                                    "metric_a": ma,
                                    "metric_b": mb,
                                    "r_raw": round(float(r_raw), 3),
                                    "r_deseasonalized": round(float(r_deseas), 3),
                                }
                            )
        if "seasonal_confound_possible" not in corr_df.columns:
            corr_df["seasonal_confound_possible"] = False
        corr_df["seasonal_confound_possible"] = corr_df["seasonal_confound_possible"].fillna(False)


    stability_results = []
    if not corr_df.empty and "is_significant" in corr_df.columns:
        sig_mask = corr_df["is_significant"] == True  # noqa: E712
        sig_pairs = corr_df[sig_mask][["metric_a", "metric_b", "method"]].drop_duplicates()
        for _, pair_row in sig_pairs.iterrows():
            ma, mb = pair_row["metric_a"], pair_row["metric_b"]
            if "," in str(ma) or "," in str(mb):
                continue
            stab = check_correlation_stability(daily_features, ma, mb, method=method)
            if "error" not in stab:
                stab["metric_a"] = ma
                stab["metric_b"] = mb
                stability_results.append(stab)


        if stability_results:
            stab_df = pd.DataFrame(stability_results)
            stab_lookup = {}
            for _, sr in stab_df.iterrows():
                stab_lookup[(sr["metric_a"], sr["metric_b"])] = sr

            is_stable_col = []
            stability_trend_col = []
            confidence_level_col = []
            for _, row in corr_df.iterrows():
                key = (row.get("metric_a"), row.get("metric_b"))
                sr = stab_lookup.get(key)
                if sr is not None:
                    is_stable_col.append(sr["is_stable"])
                    stability_trend_col.append(sr["trend"])
                    conf = compute_confidence_level(
                        row.get("correlation_r", np.nan),
                        row.get("p_adjusted", np.nan),
                        row.get("n_observations", 0),
                        row.get("ci_width", np.nan),
                        sr["is_stable"],
                    )
                    confidence_level_col.append(conf)
                else:
                    is_stable_col.append(None)
                    stability_trend_col.append(None)
                    conf = compute_confidence_level(
                        row.get("correlation_r", np.nan),
                        row.get("p_adjusted", np.nan),
                        row.get("n_observations", 0),
                        row.get("ci_width", np.nan),
                        False,
                    )
                    confidence_level_col.append(conf)

            corr_df["is_stable"] = is_stable_col
            corr_df["stability_trend"] = stability_trend_col
            corr_df["confidence_level"] = confidence_level_col


    hr_consistency = {}
    if "resting_hr" in daily_features.columns and "resting_hr_apple" in daily_features.columns:
        from correlation_engine import check_hr_consistency

        hr_consistency = check_hr_consistency(
            daily_features["resting_hr"], daily_features["resting_hr_apple"]
        )


    whoop_cols = [
        c
        for c in daily_features.columns
        if c in {"sleep_score", "recovery_score", "strain_score", "hrv_rmssd_ms"}
    ]
    n_bio_days = int(daily_features[whoop_cols].notna().any(axis=1).sum()) if whoop_cols else 0
    quality_score = compute_quality_score(source_freshness, coverage, n_bio_days, stability_results)

    data_quality["hr_consistency"] = hr_consistency
    data_quality["quality_score"] = quality_score
    data_quality["stability_results"] = stability_results
    data_quality["seasonal_confounds"] = seasonal_confounds if deseasonalize else []

    meta["data_quality"] = data_quality


    corr_path = out / "correlations.parquet"
    if not corr_df.empty:
        safe_write_parquet(corr_df, corr_path)
    else:
        safe_write_parquet(
            pd.DataFrame(
                columns=[
                    "metric_a",
                    "metric_b",
                    "correlation_r",
                    "p_value",
                    "p_adjusted",
                    "lag_days",
                    "window_days",
                    "method",
                    "n_observations",
                    "phase",
                    "is_significant",
                    "direction",
                    "computed_at",
                ]
            ),
            corr_path,
        )
    log.info("Saved correlations.parquet (%d rows)", len(corr_df))


    meta_path = out / "correlation-meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))

    mark_last_run("correlation-engine")

    return daily_features, corr_df, meta





def main():
    parser = argparse.ArgumentParser(description="Correlation Engine — SBK")
    parser.add_argument(
        "--phase", type=int, choices=[1, 2, 3], help="Force specific phase (default: auto-detect)"
    )
    parser.add_argument("--window", type=int, default=14, help="Rolling window days (default: 14)")
    parser.add_argument(
        "--min-r", type=float, default=0.3, help="Minimum |r| for significance (default: 0.3)"
    )
    parser.add_argument(
        "--min-p", type=float, default=0.05, help="Maximum p-value for significance (default: 0.05)"
    )
    parser.add_argument(
        "--method",
        type=str,
        default="spearman",
        choices=["spearman", "pearson"],
        help="Correlation method (default: spearman)",
    )
    parser.add_argument(
        "--correction",
        type=str,
        default="auto",
        choices=["bonferroni", "bh", "auto"],
        help="Multiple comparison correction: bonferroni, bh (Benjamini-Hochberg), or auto (default: auto)",
    )
    parser.add_argument(
        "--quality-report",
        action="store_true",
        help="Print data quality summary to stdout",
    )
    parser.add_argument(
        "--deseasonalize",
        action="store_true",
        help="Remove seasonal component before correlation (requires 180+ days)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    daily_features, corr_df, meta = process(
        phase=args.phase,
        window=args.window,
        min_r=args.min_r,
        min_p=args.min_p,
        method=args.method,
        correction=args.correction,
        quality_report=args.quality_report,
        deseasonalize=args.deseasonalize,
    )

    print("\nCorrelation Engine complete:")
    print(f"  Phase: {meta.get('active_phase', 0)}")
    print(f"  Daily features: {len(daily_features)} days x {len(daily_features.columns)} features")
    print(
        f"  Correlations: {len(corr_df)} total, {meta.get('significant_correlations', 0)} significant"
    )

    if not corr_df.empty and "is_significant" in corr_df.columns:
        sig = corr_df[corr_df["is_significant"]]
        if not sig.empty:
            print("\n  Significant correlations:")
            for _, row in sig.iterrows():
                direction = row.get("direction", "?")
                r_val = row.get("correlation_r", 0)
                r_str = f"r={r_val:.3f}" if not np.isnan(r_val) else "r=N/A"
                print(
                    f"    {row['metric_a']} → {row['metric_b']} "
                    f"({r_str}, lag={row['lag_days']}d, {direction})"
                )


if __name__ == "__main__":
    main()
