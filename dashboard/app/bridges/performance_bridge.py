""






from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sbk_config import OWNER_SUBJECT, utc_now



WEEKLY_SCORE_WEIGHTS = {
    "recovery": {"col": "recovery_score", "weight": 0.25},
    "sleep": {"col": "sleep_score", "weight": 0.20},
    "hrv": {"col": "hrv_rmssd_ms", "weight": 0.15},
    "email_productivity": {"col": "email_sent_count", "weight": 0.15},
    "meeting_efficiency": {"col": "meeting_free_hours", "weight": 0.10},
    "relationship_engagement": {"col": "proactive_outreach_count", "weight": 0.10},
    "content_output": {"col": "action_items_generated", "weight": 0.05},
}



BLOOD_PANEL_MAP = {
    "metabolic": {
        "display": "Metabolic",
        "markers": ["glucose", "hemoglobin_a1c", "insulin", "homa_ir"],
    },
    "lipids": {
        "display": "Lipids",
        "markers": [
            "cholesterol_total",
            "cholesterol_hdl",
            "cholesterol_ldl",
            "triglycerides",
            "lipoprotein_a",
        ],
    },
    "thyroid": {
        "display": "Thyroid",
        "markers": ["tsh", "ft3", "ft4"],
    },
    "vitamins": {
        "display": "Vitamine",
        "markers": ["vitamin_d", "vitamin_b12", "folate"],
    },
    "iron": {
        "display": "Iron",
        "markers": ["ferritin", "iron", "transferrin"],
    },
    "hormones": {
        "display": "Hormones",
        "markers": ["testosterone", "testosterone_free", "cortisol"],
    },
}

log = logging.getLogger("sbk.bridge.performance")


class PerformanceBridge:
    ""

    def __init__(self, data_root: Path | None = None):
        if data_root is None:
            data_root = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
        self._root = Path(data_root)
        self._perf_dir = self._root / "l3" / "performance"
        self._whoop_dir = self._root / "whoop" / "processed"
        self._clinical_dir = self._root / "clinical" / "processed"



    def _load_parquet(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_parquet(path)
        except Exception as e:
            log.warning("Failed to load %s: %s", path, e)
            return pd.DataFrame()

    def _load_daily_features(self) -> pd.DataFrame:
        df = self._load_parquet(self._perf_dir / "daily-features.parquet")
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def _load_correlations(self) -> pd.DataFrame:
        return self._load_parquet(self._perf_dir / "correlations.parquet")

    def _load_meta(self) -> dict:
        path = self._perf_dir / "correlation-meta.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    def _load_whoop_daily(self) -> pd.DataFrame:
        df = self._load_parquet(self._whoop_dir / "daily.parquet")
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def _load_clinical_values(self) -> pd.DataFrame:
        return self._load_parquet(self._clinical_dir / "values.parquet")



    def get_heatmap_data(self, months: int = 12) -> list[dict]:
        ""
        wp = self._load_whoop_daily()
        if wp.empty or "recovery_score" not in wp.columns:
            return []

        cutoff = date.today() - timedelta(days=months * 31)
        wp = wp[wp["date"] >= cutoff]

        result = []
        for _, row in wp.iterrows():
            score = row.get("recovery_score")
            if pd.isna(score):
                zone = "gray"
            elif score <= 33:
                zone = "red"
            elif score <= 66:
                zone = "yellow"
            else:
                zone = "green"

            result.append(
                {
                    "date": str(row["date"]),
                    "recovery_score": float(score) if not pd.isna(score) else None,
                    "zone": zone,
                }
            )

        return result

    def get_anomalies(self, subject: str | None = None) -> list[dict]:
        ""
        anomalies = []


        clinical = self._load_clinical_values()
        if not clinical.empty and "is_anomaly" in clinical.columns:

            if subject is not None and "subject" in clinical.columns:
                clinical = clinical[clinical["subject"] == subject]

            if "date" in clinical.columns:
                clinical_sorted = clinical.sort_values("date", ascending=False)
                latest = clinical_sorted.drop_duplicates(subset=["marker"], keep="first")
            else:
                latest = clinical

            for _, row in latest.iterrows():
                if row.get("is_anomaly"):
                    anomalies.append(
                        {
                            "type": "blood_out_of_range",
                            "marker": row.get("marker", "unknown"),
                            "severity": "high",
                            "value": float(row["value"]) if not pd.isna(row.get("value")) else None,
                            "unit": row.get("unit", ""),
                            "ref_min": float(row["ref_min"])
                            if not pd.isna(row.get("ref_min"))
                            else None,
                            "ref_max": float(row["ref_max"])
                            if not pd.isna(row.get("ref_max"))
                            else None,
                            "date": str(row.get("date", "")),
                            "description": f"{row.get('marker', '?')} out of range "
                            f"({row.get('value', '?')} {row.get('unit', '')})",
                        }
                    )


        wp = self._load_whoop_daily()
        if not wp.empty and "hrv_rmssd_ms" in wp.columns:
            wp_sorted = wp.sort_values("date")
            hrv = wp_sorted["hrv_rmssd_ms"].dropna()
            if len(hrv) >= 14:
                baseline = hrv.iloc[-30:].mean() if len(hrv) >= 30 else hrv.mean()
                recent = hrv.iloc[-7:].mean()
                if baseline > 0 and (baseline - recent) / baseline > 0.10:
                    pct = round((baseline - recent) / baseline * 100, 1)
                    anomalies.append(
                        {
                            "type": "hrv_decline",
                            "marker": "hrv_rmssd_ms",
                            "severity": "medium",
                            "description": f"HRV trending down (-{pct}% vs baseline)",
                        }
                    )


        if not wp.empty and "recovery_score" in wp.columns:
            wp_sorted = wp.sort_values("date")
            recent_recovery = wp_sorted["recovery_score"].dropna().iloc[-7:]
            consecutive_red = 0
            for val in recent_recovery:
                if val < 33:
                    consecutive_red += 1
                else:
                    consecutive_red = 0
            if consecutive_red >= 3:
                anomalies.append(
                    {
                        "type": "recovery_low",
                        "marker": "recovery_score",
                        "severity": "high",
                        "description": f"Low recovery for {consecutive_red} days in a row",
                    }
                )

        return anomalies

    def get_timeline_data(
        self,
        period_days: int = 30,
        metrics: list[str] | None = None,
    ) -> dict:
        ""
        df = self._load_daily_features()
        if df.empty:
            return {"dates": [], "series": []}

        cutoff = date.today() - timedelta(days=period_days)
        if "date" in df.columns:
            df = df[df["date"] >= cutoff]
        else:
            df = df.tail(period_days)

        if metrics is None:
            metrics = [
                "recovery_score",
                "sleep_score",
                "hrv_rmssd_ms",
                "strain_score",
                "email_sent_count",
                "meetings_count",
            ]

        available_metrics = [m for m in metrics if m in df.columns]

        dates = [str(d) for d in (df["date"] if "date" in df.columns else df.index)]

        series = []
        for m in available_metrics:
            values = df[m].tolist()

            values = [None if pd.isna(v) else float(v) for v in values]
            series.append({"name": m, "data": values})

        return {"dates": dates, "series": series}

    def get_correlations_summary(self, top_n: int = 10) -> list[dict]:
        ""
        corr = self._load_correlations()
        if corr.empty:
            return []

        if "is_significant" in corr.columns:
            sig = corr[corr["is_significant"] == True]  # noqa: E712
        else:
            return []

        if sig.empty:
            return []


        if "correlation_r" in sig.columns:
            sig = sig.copy()
            sig["abs_r"] = sig["correlation_r"].abs()
            sig = sig.sort_values("abs_r", ascending=False).head(top_n)
            sig = sig.drop(columns=["abs_r"])

        result = []
        for _, row in sig.iterrows():
            item = {}
            for col in row.index:
                val = row[col]
                if pd.isna(val):
                    item[col] = None
                elif isinstance(val, np.integer | np.floating):
                    item[col] = float(val)
                elif isinstance(val, np.bool_):
                    item[col] = bool(val)
                elif isinstance(val, date | pd.Timestamp):
                    item[col] = str(val)
                else:
                    item[col] = val
            result.append(item)

        return result

    def get_scatter_data(self, metric_a: str, metric_b: str) -> list[dict]:
        ""
        df = self._load_daily_features()
        if df.empty or metric_a not in df.columns or metric_b not in df.columns:
            return []

        result = []
        for _, row in df.iterrows():
            x_val = row.get(metric_a)
            y_val = row.get(metric_b)
            if pd.isna(x_val) or pd.isna(y_val):
                continue
            item = {
                "x": float(x_val),
                "y": float(y_val),
                "date": str(row["date"]) if "date" in row.index else "",
            }
            if "recovery_score" in row.index and not pd.isna(row["recovery_score"]):
                score = row["recovery_score"]
                if score <= 33:
                    item["zone"] = "red"
                elif score <= 66:
                    item["zone"] = "yellow"
                else:
                    item["zone"] = "green"
            result.append(item)

        return result

    def get_blood_trends(self, marker: str, subject: str = OWNER_SUBJECT) -> dict:
        ""
        clinical = self._load_clinical_values()
        if clinical.empty or "marker" not in clinical.columns:
            return {"marker": marker, "points": [], "ref_min": None, "ref_max": None, "unit": ""}


        if "subject" in clinical.columns:
            clinical = clinical[clinical["subject"] == subject]

        filtered = clinical[clinical["marker"] == marker].copy()
        if filtered.empty:
            return {"marker": marker, "points": [], "ref_min": None, "ref_max": None, "unit": ""}

        if "date" in filtered.columns:
            filtered = filtered.sort_values("date")

        points = []
        for _, row in filtered.iterrows():
            points.append(
                {
                    "date": str(row.get("date", "")),
                    "value": float(row["value"]) if not pd.isna(row.get("value")) else None,
                    "is_anomaly": bool(row.get("is_anomaly", False)),
                }
            )


        ref_min = None
        ref_max = None
        if "ref_min" in filtered.columns:
            ref_min_vals = filtered["ref_min"].dropna()
            if not ref_min_vals.empty:
                ref_min = float(ref_min_vals.iloc[-1])
        if "ref_max" in filtered.columns:
            ref_max_vals = filtered["ref_max"].dropna()
            if not ref_max_vals.empty:
                ref_max = float(ref_max_vals.iloc[-1])

        return {
            "marker": marker,
            "points": points,
            "ref_min": ref_min,
            "ref_max": ref_max,
            "unit": str(filtered.iloc[-1].get("unit", "")) if not filtered.empty else "",
        }

    def get_daily_detail(self, date_str: str) -> dict:
        ""
        df = self._load_daily_features()
        wp = self._load_whoop_daily()


        try:
            from datetime import datetime

            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"date": "", "error": "Invalid date format. Expected YYYY-MM-DD."}

        result = {"date": str(target_date), "biometric": {}, "behavioral": {}}


        if not wp.empty and "date" in wp.columns:
            day_row = wp[wp["date"] == target_date]
            if not day_row.empty:
                row = day_row.iloc[0]
                bio = {}
                for col in [
                    "sleep_score",
                    "recovery_score",
                    "strain_score",
                    "hrv_rmssd_ms",
                    "resting_hr",
                    "sleep_efficiency",
                    "rem_sleep_ms",
                    "deep_sleep_ms",
                ]:
                    val = row.get(col)
                    if val is not None and not pd.isna(val):
                        bio[col] = float(val)
                result["biometric"] = bio


        if not df.empty and "date" in df.columns:
            day_row = df[df["date"] == target_date]
            if not day_row.empty:
                row = day_row.iloc[0]
                beh = {}
                for col in [
                    "email_sent_count",
                    "email_received_count",
                    "email_avg_sentiment",
                    "email_avg_response_min",
                    "meetings_count",
                    "meetings_total_minutes",
                    "slack_messages_sent",
                    "slack_dm_count",
                ]:
                    val = row.get(col)
                    if val is not None and not pd.isna(val):
                        beh[col] = float(val)
                result["behavioral"] = beh

        return result

    def get_meta(self) -> dict:
        ""
        return self._load_meta()



    def get_clinical_alerts(self, subject: str = OWNER_SUBJECT) -> list[dict]:
        ""
        path = self._clinical_dir / "alerts.json"
        if not path.exists():
            return []
        try:
            alerts = json.loads(path.read_text())
            return [a for a in alerts if a.get("subject", OWNER_SUBJECT) == subject]
        except Exception as e:
            log.warning("Failed to load alerts.json: %s", e)
            return []



    def get_source_health(self) -> list[dict]:
        ""



        meta = self._load_meta()
        dq = meta.get("data_quality", {})
        return dq.get("source_freshness", [])

    def get_quality_score(self) -> dict:
        ""



        meta = self._load_meta()
        dq = meta.get("data_quality", {})
        return {
            "score": dq.get("quality_score", 0),
            "breakdown": {
                "coverage": dq.get("coverage", {}),
                "gap_patterns": dq.get("gap_patterns", []),
                "source_freshness": dq.get("source_freshness", []),
                "clinical_violations": dq.get("clinical_violations", []),
                "hr_consistency": dq.get("hr_consistency", {}),
            },
        }



    def _compute_weekly_score(
        self, weekly_means: dict, history_df: pd.DataFrame
    ) -> tuple[float, dict]:
        ""



        components = {}
        total_weight = 0.0
        weighted_sum = 0.0

        for name, cfg in WEEKLY_SCORE_WEIGHTS.items():
            col = cfg["col"]
            weight = cfg["weight"]
            val = weekly_means.get(col)
            if val is None or pd.isna(val):
                continue
            if col not in history_df.columns:
                continue

            col_data = history_df[col].dropna()
            if col_data.empty:
                continue

            col_min = float(col_data.min())
            col_max = float(col_data.max())
            if col_max == col_min:
                norm = 0.5
            else:
                norm = (val - col_min) / (col_max - col_min)
            norm = max(0.0, min(1.0, norm))

            components[name] = round(norm * 100, 1)
            weighted_sum += norm * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, {}

        score = round((weighted_sum / total_weight) * 100, 1)
        return score, components

    def get_weekly_score(self, weeks: int = 12) -> dict:
        ""
        df = self._load_daily_features()
        if df.empty or "date" not in df.columns:
            return {}

        df = df.copy()
        dates = pd.to_datetime(df["date"])
        iso = dates.dt.isocalendar()
        df["year_week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)

        numeric_cols = [c for c in df.columns if c not in ("date", "year_week", "recovery_zone")]
        week_groups = df.groupby("year_week", sort=True)

        trend = []
        for yw, group in week_groups:
            means = {}
            for col in numeric_cols:
                if col in group.columns:
                    val = group[col].mean()
                    if not pd.isna(val):
                        means[col] = float(val)
            score, components = self._compute_weekly_score(means, df)
            trend.append({"week": str(yw), "score": score, "components": components})

        trend = trend[-weeks:]
        if not trend:
            return {}

        current = trend[-1]
        score = current["score"]
        zone = "red" if score <= 33 else ("yellow" if score <= 66 else "green")

        wow_delta = None
        if len(trend) >= 2:
            wow_delta = round(trend[-1]["score"] - trend[-2]["score"], 1)

        scores = [t["score"] for t in trend]
        best_idx = scores.index(max(scores))
        worst_idx = scores.index(min(scores))

        return {
            "current_week": {
                "week": current["week"],
                "score": current["score"],
                "zone": zone,
                "components": current["components"],
            },
            "trend": trend,
            "wow_delta": wow_delta,
            "best_week": trend[best_idx]["week"],
            "worst_week": trend[worst_idx]["week"],
        }

    def get_data_coverage(self) -> dict:
        ""
        sources = {
            "whoop_daily": self._whoop_dir / "daily.parquet",
            "clinical_values": self._clinical_dir / "values.parquet",
            "daily_features": self._perf_dir / "daily-features.parquet",
            "correlations": self._perf_dir / "correlations.parquet",
        }

        now = utc_now()
        source_status = []
        for name, path in sources.items():
            if not path.exists():
                source_status.append(
                    {
                        "source": name,
                        "status": "outdated",
                        "last_modified": None,
                        "days_ago": None,
                    }
                )
                continue

            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)
            delta = now - mtime
            days_ago = round(delta.total_seconds() / 86400, 1)

            if delta < timedelta(hours=24):
                status = "fresh"
            elif delta < timedelta(days=7):
                status = "ok"
            elif delta < timedelta(days=30):
                status = "stale"
            else:
                status = "outdated"

            source_status.append(
                {
                    "source": name,
                    "status": status,
                    "last_modified": mtime.isoformat(),
                    "days_ago": days_ago,
                }
            )


        df = self._load_daily_features()
        column_coverage = []
        if not df.empty:
            for col in df.columns:
                if col in ("date", "recovery_zone"):
                    continue
                total = len(df)
                non_null = int(df[col].notna().sum())
                nan_pct = round((1 - non_null / total) * 100, 1) if total > 0 else 100.0
                column_coverage.append(
                    {
                        "column": col,
                        "total_rows": total,
                        "non_null": non_null,
                        "nan_pct": nan_pct,
                    }
                )


        recommendations = []
        for s in source_status:
            if s["status"] == "outdated":
                recommendations.append(f"Update {s['source']} (>30 days)")
            elif s["status"] == "stale":
                recommendations.append(
                    f"{s['source']} not updated for {s['days_ago']:.0f} days"
                )

        high_nan = [c for c in column_coverage if c["nan_pct"] > 50]
        if high_nan:
            names = ", ".join(c["column"] for c in high_nan[:3])
            recommendations.append(f"Columns with >50% NaN: {names}")

        return {
            "sources": source_status,
            "column_coverage": column_coverage,
            "recommendations": recommendations,
        }

    def get_correlation_matrix(self, min_r: float = 0.0, phase: str | None = None) -> dict:
        ""
        corr = self._load_correlations()
        if corr.empty:
            return {"metrics": [], "matrix": [], "significant": [], "p_values": []}


        if "method" in corr.columns:
            corr = corr[corr["method"] == "spearman"]

        if phase and "phase" in corr.columns:
            corr = corr[corr["phase"] == phase]


        if min_r > 0 and "correlation_r" in corr.columns:
            corr = corr[corr["correlation_r"].abs() >= min_r]

        if corr.empty:
            return {"metrics": [], "matrix": [], "significant": [], "p_values": []}


        metrics_set = set()
        for _, row in corr.iterrows():
            metrics_set.add(row["metric_a"])
            metrics_set.add(row["metric_b"])
        metrics = sorted(metrics_set)
        idx = {m: i for i, m in enumerate(metrics)}
        n = len(metrics)


        matrix = [[0.0] * n for _ in range(n)]
        significant = [[False] * n for _ in range(n)]
        p_values = [[1.0] * n for _ in range(n)]


        for i in range(n):
            matrix[i][i] = 1.0
            significant[i][i] = True
            p_values[i][i] = 0.0

        for _, row in corr.iterrows():
            a = row["metric_a"]
            b = row["metric_b"]
            if a not in idx or b not in idx:
                continue
            i, j = idx[a], idx[b]
            r = float(row["correlation_r"]) if not pd.isna(row.get("correlation_r")) else 0.0
            is_sig = bool(row.get("is_significant", False))
            p = float(row["p_adjusted"]) if not pd.isna(row.get("p_adjusted")) else 1.0

            matrix[i][j] = r
            matrix[j][i] = r
            significant[i][j] = is_sig
            significant[j][i] = is_sig
            p_values[i][j] = p
            p_values[j][i] = p

        return {
            "metrics": metrics,
            "matrix": matrix,
            "significant": significant,
            "p_values": p_values,
        }

    def get_blood_panel(self, panel: str = "all") -> dict:
        ""
        clinical = self._load_clinical_values()
        if clinical.empty or "marker" not in clinical.columns:
            return {"panels": [], "test_dates": []}


        if "subject" in clinical.columns:
            clinical = clinical[clinical["subject"] == OWNER_SUBJECT]


        if panel == "all":
            panels_to_show = BLOOD_PANEL_MAP
        elif panel in BLOOD_PANEL_MAP:
            panels_to_show = {panel: BLOOD_PANEL_MAP[panel]}
        else:
            return {"panels": [], "test_dates": []}

        available_markers = set(clinical["marker"].unique())
        all_dates = set()
        panels_result = []

        for panel_key, panel_info in panels_to_show.items():
            markers_data = []
            for marker_name in panel_info["markers"]:
                if marker_name not in available_markers:
                    continue

                m_df = clinical[clinical["marker"] == marker_name].copy()
                if "date" in m_df.columns:
                    m_df = m_df.sort_values("date")

                points = []
                for _, row in m_df.iterrows():
                    d = str(row.get("date", ""))
                    if d:
                        all_dates.add(d)
                    points.append(
                        {
                            "date": d,
                            "value": float(row["value"]) if not pd.isna(row.get("value")) else None,
                            "is_anomaly": bool(row.get("is_anomaly", False)),
                        }
                    )


                ref_min = None
                ref_max = None
                unit = ""
                if not m_df.empty:
                    last = m_df.iloc[-1]
                    if not pd.isna(last.get("ref_min")):
                        ref_min = float(last["ref_min"])
                    if not pd.isna(last.get("ref_max")):
                        ref_max = float(last["ref_max"])
                    unit = str(last.get("unit", ""))


                trend = "stable"
                values_for_trend = [p["value"] for p in points if p["value"] is not None]
                if len(values_for_trend) >= 3:
                    x = np.arange(len(values_for_trend), dtype=float)
                    y = np.array(values_for_trend, dtype=float)
                    slope = np.polyfit(x, y, 1)[0]
                    mean_val = np.mean(y)
                    if mean_val != 0:
                        pct_change = abs(slope * len(y)) / mean_val
                        if pct_change > 0.05:
                            trend = (
                                "improving"
                                if slope < 0 and ref_max and y[-1] > ref_max
                                else (
                                    "improving"
                                    if slope > 0 and ref_min and y[-1] < ref_min
                                    else (
                                        "declining"
                                        if slope > 0 and ref_max
                                        else ("declining" if slope < 0 and ref_min else "stable")
                                    )
                                )
                            )

                            if (
                                slope > 0
                                and ref_max
                                and y[-1] >= ref_max * 0.9
                                or slope < 0
                                and ref_min
                                and y[-1] <= ref_min * 1.1
                            ):
                                trend = "declining"
                            elif (
                                slope > 0
                                and (ref_max is None or y[-1] < ref_max * 0.9)
                                or slope < 0
                                and (ref_min is None or y[-1] > ref_min * 1.1)
                            ):
                                trend = "improving"

                latest_val = values_for_trend[-1] if values_for_trend else None

                markers_data.append(
                    {
                        "name": marker_name,
                        "display_name": marker_name.replace("_", " ").title(),
                        "unit": unit,
                        "points": points,
                        "ref_min": ref_min,
                        "ref_max": ref_max,
                        "trend": trend,
                        "latest": latest_val,
                    }
                )

            if markers_data:
                panels_result.append(
                    {
                        "panel": panel_key,
                        "display": panel_info["display"],
                        "markers": markers_data,
                    }
                )

        return {
            "panels": panels_result,
            "test_dates": sorted(all_dates),
        }

    def get_intervention_timeline(self, marker: str, months: int = 24) -> dict:
        ""
        blood = self.get_blood_trends(marker)


        supp_path = self._clinical_dir / "supplements.parquet"
        interventions = []
        if supp_path.exists():
            try:
                supps = pd.read_parquet(supp_path)
                if "subject" in supps.columns:
                    supps = supps[supps["subject"] == OWNER_SUBJECT]
                for _, row in supps.iterrows():
                    start = str(row.get("start_date", ""))
                    end = row.get("end_date")
                    end_str = str(end) if end and not pd.isna(end) else None
                    interventions.append(
                        {
                            "supplement": str(row.get("supplement", "")),
                            "start_date": start,
                            "end_date": end_str,
                            "dose": float(row["dose"]) if not pd.isna(row.get("dose")) else None,
                            "unit": str(row.get("unit", "")),
                            "frequency": str(row.get("frequency", "")),
                            "active": end_str is None,
                        }
                    )
            except Exception as e:
                log.warning("Failed to load supplements: %s", e)


        cutoff = date.today() - timedelta(days=months * 31)
        cutoff_str = str(cutoff)
        filtered_points = [p for p in blood["points"] if p["date"] >= cutoff_str]


        bsts = {"available": False}
        corr = self._load_correlations()
        if not corr.empty and "method" in corr.columns:
            bsts_rows = corr[
                (corr["method"] == "bsts")
                & ((corr["metric_a"] == marker) | (corr["metric_b"] == marker))
            ]
            if not bsts_rows.empty:
                row = bsts_rows.iloc[0]
                bsts = {
                    "available": True,
                    "causal_impact": float(row["absolute_effect"])
                    if not pd.isna(row.get("absolute_effect"))
                    else None,
                }

        return {
            "marker": marker,
            "unit": blood["unit"],
            "points": filtered_points,
            "ref_min": blood["ref_min"],
            "ref_max": blood["ref_max"],
            "interventions": interventions,
            "bsts": bsts,
        }

    def get_circadian_data(self, period_days: int = 90, metric: str = "meetings") -> dict:
        ""
        wp = self._load_whoop_daily()
        cutoff = date.today() - timedelta(days=period_days)


        recovery_by_date = {}
        if not wp.empty and "recovery_score" in wp.columns:
            for _, row in wp.iterrows():
                d = row.get("date")
                r = row.get("recovery_score")
                if d and not pd.isna(r):
                    recovery_by_date[str(d)] = float(r)

        hours_data = {}

        if metric == "meetings":

            cal_dir = self._root / "calendars"
            if cal_dir.exists():
                for account_dir in cal_dir.iterdir():
                    events_path = account_dir / "events.parquet"
                    if not events_path.exists():
                        continue
                    try:
                        events = pd.read_parquet(events_path)
                    except Exception:
                        continue

                    if "start_datetime" not in events.columns:
                        continue

                    for _, row in events.iterrows():
                        try:
                            dt = pd.Timestamp(row["start_datetime"])
                            if dt.date() < cutoff:
                                continue
                            hour = dt.hour
                            dow = dt.weekday()
                            if hour < 6 or hour > 22:
                                continue
                            key = (hour, dow)
                            if key not in hours_data:
                                hours_data[key] = {"count": 0, "recovery_sum": 0.0, "recovery_n": 0}
                            hours_data[key]["count"] += 1
                            date_str = str(dt.date())
                            if date_str in recovery_by_date:
                                hours_data[key]["recovery_sum"] += recovery_by_date[date_str]
                                hours_data[key]["recovery_n"] += 1
                        except Exception:
                            continue

        elif metric == "emails":

            email_dir = self._root / "emails"
            msg_path = email_dir / "filtered-messages.parquet"
            if not msg_path.exists():
                msg_path = email_dir / "messages.parquet"
            if msg_path.exists():
                try:
                    msgs = pd.read_parquet(msg_path)
                    date_col = "date" if "date" in msgs.columns else "sent_at"
                    if date_col in msgs.columns:
                        for _, row in msgs.iterrows():
                            try:
                                dt = pd.Timestamp(row[date_col])
                                if dt.date() < cutoff:
                                    continue
                                hour = dt.hour
                                dow = dt.weekday()
                                if hour < 6 or hour > 22:
                                    continue
                                key = (hour, dow)
                                if key not in hours_data:
                                    hours_data[key] = {
                                        "count": 0,
                                        "recovery_sum": 0.0,
                                        "recovery_n": 0,
                                    }
                                hours_data[key]["count"] += 1
                                date_str = str(dt.date())
                                if date_str in recovery_by_date:
                                    hours_data[key]["recovery_sum"] += recovery_by_date[date_str]
                                    hours_data[key]["recovery_n"] += 1
                            except Exception:
                                continue
                except Exception as e:
                    log.warning("Failed to load email data: %s", e)

        if not hours_data:
            return {"hours": [], "peak_hours": [], "avoid_hours": [], "metric": metric}


        hours_list = []
        for (hour, dow), data in sorted(hours_data.items()):
            avg_recovery = (
                round(data["recovery_sum"] / data["recovery_n"], 1)
                if data["recovery_n"] > 0
                else None
            )
            hours_list.append(
                {
                    "hour": hour,
                    "dow": dow,
                    "count": data["count"],
                    "avg_recovery": avg_recovery,
                }
            )


        hour_totals = {}
        for h in hours_list:
            hr = h["hour"]
            if hr not in hour_totals:
                hour_totals[hr] = {"count": 0, "recovery_sum": 0.0, "recovery_n": 0}
            hour_totals[hr]["count"] += h["count"]
            if h["avg_recovery"] is not None:
                hour_totals[hr]["recovery_sum"] += h["avg_recovery"] * h["count"]
                hour_totals[hr]["recovery_n"] += h["count"]

        scored_hours = []
        for hr, data in hour_totals.items():
            avg_rec = data["recovery_sum"] / data["recovery_n"] if data["recovery_n"] > 0 else 50
            scored_hours.append((hr, data["count"], avg_rec))

        scored_hours.sort(key=lambda x: x[2], reverse=True)
        peak_hours = [h[0] for h in scored_hours[:3]]
        avoid_hours = [h[0] for h in scored_hours[-3:]]

        return {
            "hours": hours_list,
            "peak_hours": peak_hours,
            "avoid_hours": avoid_hours,
            "metric": metric,
        }

    def get_behavioral_pattern(self, min_weeks: int = 8, percentile: int = 25) -> dict:
        ""
        df = self._load_daily_features()
        if df.empty or "date" not in df.columns:
            return {"sufficient_data": False, "weeks_analyzed": 0}

        df = df.copy()
        dates = pd.to_datetime(df["date"])
        iso = dates.dt.isocalendar()
        df["year_week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)

        numeric_cols = [c for c in df.columns if c not in ("date", "year_week", "recovery_zone")]

        week_scores = []
        for yw, group in df.groupby("year_week", sort=True):
            means = {}
            for col in numeric_cols:
                if col in group.columns:
                    val = group[col].mean()
                    if not pd.isna(val):
                        means[col] = float(val)
            score, _ = self._compute_weekly_score(means, df)
            week_scores.append({"week": str(yw), "score": score, "means": means})

        if len(week_scores) < min_weeks:
            return {"sufficient_data": False, "weeks_analyzed": len(week_scores)}


        all_scores = [w["score"] for w in week_scores]
        low_thresh = np.percentile(all_scores, percentile)
        high_thresh = np.percentile(all_scores, 100 - percentile)

        good_weeks = [w for w in week_scores if w["score"] >= high_thresh]
        bad_weeks = [w for w in week_scores if w["score"] <= low_thresh]

        if not good_weeks or not bad_weeks:
            return {"sufficient_data": False, "weeks_analyzed": len(week_scores)}


        dimensions = [
            ("recovery", "recovery_score"),
            ("sleep", "sleep_score"),
            ("hrv", "hrv_rmssd_ms"),
            ("email_volume", "email_sent_count"),
            ("meeting_load", "meetings_count"),
            ("meeting_free_time", "meeting_free_hours"),
            ("slack_activity", "slack_messages_sent"),
            ("outreach", "proactive_outreach_count"),
            ("decisions", "decisions_count"),
            ("communication", "total_communication_volume"),
        ]

        dim_results = []
        good_profile = []
        bad_profile = []
        insights = []

        for dim_name, col in dimensions:
            good_vals = [w["means"].get(col) for w in good_weeks if w["means"].get(col) is not None]
            bad_vals = [w["means"].get(col) for w in bad_weeks if w["means"].get(col) is not None]

            if not good_vals or not bad_vals:
                dim_results.append(dim_name)
                good_profile.append(50)
                bad_profile.append(50)
                continue

            good_mean = float(np.mean(good_vals))
            bad_mean = float(np.mean(bad_vals))


            all_vals = [w["means"].get(col) for w in week_scores if w["means"].get(col) is not None]
            if all_vals:
                vmin = min(all_vals)
                vmax = max(all_vals)
                if vmax == vmin:
                    good_norm = 50
                    bad_norm = 50
                else:
                    good_norm = round((good_mean - vmin) / (vmax - vmin) * 100, 1)
                    bad_norm = round((bad_mean - vmin) / (vmax - vmin) * 100, 1)
            else:
                good_norm = 50
                bad_norm = 50

            dim_results.append(dim_name)
            good_profile.append(good_norm)
            bad_profile.append(bad_norm)

            gap = abs(good_norm - bad_norm)
            if gap > 20:
                direction = "higher" if good_norm > bad_norm else "lower"
                insights.append(f"{dim_name}: good weeks have {direction} values (gap {gap:.0f}pt)")

        return {
            "sufficient_data": True,
            "weeks_analyzed": len(week_scores),
            "good_count": len(good_weeks),
            "bad_count": len(bad_weeks),
            "dimensions": dim_results,
            "good_profile": good_profile,
            "bad_profile": bad_profile,
            "insights": insights,
        }

    def get_correlation_confidence(self, metric_a: str, metric_b: str) -> dict:
        ""




        corr = self._load_correlations()
        if corr.empty:
            return {"error": "no correlations available"}

        match = corr[(corr["metric_a"] == metric_a) & (corr["metric_b"] == metric_b)]
        if match.empty:
            return {"error": f"pair {metric_a}/{metric_b} not found"}

        row = match.iloc[0]
        result = {}
        for col in [
            "correlation_r",
            "p_adjusted",
            "ci_lower",
            "ci_upper",
            "ci_width",
            "effect_size",
            "confidence_level",
            "is_stable",
            "stability_trend",
            "n_observations",
            "method",
        ]:
            val = row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                if isinstance(val, np.integer | np.floating):
                    result[col] = float(val)
                elif isinstance(val, np.bool_):
                    result[col] = bool(val)
                else:
                    result[col] = val
        return result
