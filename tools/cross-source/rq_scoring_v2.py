""











from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

log = logging.getLogger("rq.scoring_v2")





DEFAULT_WEIGHTS_V2 = {
    "intimacy": 0.20,
    "interaction_quality": 0.45,
    "structural": 0.20,
    "trust_commitment": 0.15,
    "negative_penalty": 0.25,
}


DUNBAR_CIRCLES_V2 = [
    (8.0, 10.01, "inner_circle"),
    (5.0, 8.0, "sympathy_group"),
    (3.0, 5.0, "active_network"),
    (1.5, 3.0, "full_network"),
    (0.0, 1.5, "extended"),
]


@dataclass
class ScoringResult:
    ""

    score: float
    confidence: float
    breakdown: dict[str, float]
    trend: str
    dunbar_circle: str
    dunbar_label: str





def _log_norm(value: float, reference: float) -> float:
    ""
    import math

    if value <= 0 or reference <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(reference * 3))





def normalize_intimacy(signals: pd.Series) -> float:
    ""









    components = [
        0.15 * (1.0 if bool(signals.get("is_family", False)) else 0.0),
        0.25 * _log_norm(int(signals.get("personal_topic_count", 0)), 5),
        0.20 * float(signals.get("whatsapp_late_night_pct", 0.0)),
        0.15 * float(signals.get("whatsapp_informal_score", 0.0)),
        0.10 * float(signals.get("weekend_evening_email_ratio", 0.0)),
        0.15 * _log_norm(int(signals.get("topic_breadth", 0)), 10),
    ]
    return min(1.0, sum(components))


def normalize_interaction_quality(signals: pd.Series) -> float:
    ""










    import math

    components = []
    weights = []

    freq = float(signals.get("recency_weighted_frequency", 0.0))
    freq_log = math.log1p(freq * 100) / math.log1p(100)
    components.append(freq_log)
    weights.append(0.30)


    email_lat = float(signals.get("email_response_latency_hours", 48.0))
    if email_lat != 48.0:
        latency_score = max(0.0, 1.0 - email_lat / 48.0)
        components.append(latency_score)
        weights.append(0.20)


    slack_lat = float(signals.get("slack_response_latency_hours", 24.0))
    if slack_lat != 24.0:
        slack_score = max(0.0, 1.0 - slack_lat / 24.0)
        components.append(slack_score)
        weights.append(0.10)



    cov = float(signals.get("contact_rhythm_cov", 1.0))
    if cov != 1.0:
        rhythm_score = max(0.0, 1.0 - cov / 4.0)
        components.append(rhythm_score)
        weights.append(0.10)


    duration = float(signals.get("relationship_duration_days", 0.0))
    if duration > 0:
        components.append(_log_norm(duration, 365 * 5))
        weights.append(0.15)

    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return min(1.0, sum(c * w / total_w for c, w in zip(components, weights)))


def normalize_structural(
    signals: pd.Series,
    max_pagerank: float = 0.05,
    max_betweenness: float = 0.05,
) -> float:
    ""







    pr = min(1.0, float(signals.get("pagerank", 0.0)) / max_pagerank) if max_pagerank > 0 else 0.0
    bt = (
        min(1.0, float(signals.get("betweenness", 0.0)) / max_betweenness)
        if max_betweenness > 0
        else 0.0
    )
    intro = _log_norm(int(signals.get("introductions_count", 0)), 10)
    mux = _log_norm(int(signals.get("multiplexity_bidir", 0)), 4)

    return min(1.0, 0.40 * pr + 0.30 * bt + 0.25 * intro + 0.05 * mux)


def normalize_trust_commitment(signals: pd.Series) -> float:
    ""







    promise = float(signals.get("promise_completion_ratio", 0.0))
    ai = _log_norm(int(signals.get("action_items_count", 0)), 50)
    raw_attio = float(signals.get("attio_connection_strength", 0.0))
    attio = _log_norm(raw_attio, 100) if raw_attio > 0 else 0.0
    commit = _log_norm(int(signals.get("commitment_facts_count", 0)), 20)

    return min(1.0, 0.30 * promise + 0.25 * ai + 0.25 * attio + 0.20 * commit)


def normalize_negative_signals(signals: pd.Series) -> float:
    ""









    rejection = min(1.0, int(signals.get("rejection_count", 0)) / 15.0)
    ghosting = float(signals.get("ghosting_score", 0.0))

    raw_one_sided = float(signals.get("one_sided_ratio", 0.0))
    one_sided = max(0.0, (raw_one_sided - 0.7) / 0.3) if raw_one_sided > 0.7 else 0.0
    ex_emp = 0.5 if bool(signals.get("is_ex_employee", False)) else 0.0

    return min(1.0, 0.35 * rejection + 0.30 * ghosting + 0.10 * one_sided + 0.25 * ex_emp)


def normalize_negative_penalty_v3(signals: pd.Series) -> float:
    ""




    return float(signals.get("severity_penalty", 0.0))





def compute_score_v2(
    dims: dict[str, float],
    weights: dict[str, float] | None = None,
    recency_multiplier: float = 1.0,
    is_ex_employee: bool = False,
    use_severity_v3: bool = False,
    severity_penalty: float = 0.0,
) -> float:
    ""



















    w = weights or DEFAULT_WEIGHTS_V2

    positive = (
        w.get("intimacy", 0.20) * dims.get("intimacy", 0.0)
        + w.get("interaction_quality", 0.45) * dims.get("interaction_quality", 0.0)
        + w.get("structural", 0.20) * dims.get("structural", 0.0)
        + w.get("trust_commitment", 0.15) * dims.get("trust_commitment", 0.0)
    )


    penalty = 0.0

    raw = positive - penalty


    raw_clamped = max(0.0, raw)
    score = 1.0 + raw_clamped * 9.0


    score = 1.0 + (score - 1.0) * recency_multiplier



    return max(1.0, min(10.0, round(score, 1)))


def get_dunbar_circle_v2(score: float) -> str:
    ""
    for low, high, circle in DUNBAR_CIRCLES_V2:
        if low <= score < high:
            return circle
    return "extended"


def get_dunbar_label_v2(circle: str) -> str:
    ""
    labels = {
        "inner_circle": "Collaboratore strettissimo",
        "sympathy_group": "Contatto importante",
        "active_network": "Contatto regolare",
        "full_network": "Conoscenza",
        "extended": "Sotto soglia",
    }
    return labels.get(circle, circle)





def _compute_recency_multiplier(days_ago: float, half_life: float = 180.0) -> float:
    ""











    import math

    if days_ago <= 0:
        return 1.0
    decay = math.pow(0.5, days_ago / half_life)
    return max(0.15, decay)


def score_person_v2(
    signals: pd.Series,
    weights: dict[str, float] | None = None,
    max_pagerank: float = 0.05,
    max_betweenness: float = 0.05,
) -> ScoringResult:
    ""










    dims = {
        "intimacy": normalize_intimacy(signals),
        "interaction_quality": normalize_interaction_quality(signals),
        "structural": normalize_structural(signals, max_pagerank, max_betweenness),
        "trust_commitment": normalize_trust_commitment(signals),
        "negative_signals": normalize_negative_signals(signals),
    }


    days_ago = float(signals.get("last_interaction_days_ago", 365.0))
    recency_mult = _compute_recency_multiplier(days_ago)


    is_ex = bool(signals.get("is_ex_employee", False))

    score = compute_score_v2(dims, weights, recency_mult, is_ex)
    confidence = float(signals.get("signal_coverage", 0.0))
    circle = get_dunbar_circle_v2(score)

    return ScoringResult(
        score=score,
        confidence=confidence,
        breakdown={k: round(v, 4) for k, v in dims.items()},
        trend="stable",
        dunbar_circle=circle,
        dunbar_label=get_dunbar_label_v2(circle),
    )





def load_weights_config(config_path: Path | None = None) -> dict[str, float]:
    ""
    from sbk_config import RQ_SCORING_CONFIG_V2

    if config_path is None:
        config_path = RQ_SCORING_CONFIG_V2

    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data.get("weights", DEFAULT_WEIGHTS_V2)
        except (ValueError, OSError):
            pass

    return DEFAULT_WEIGHTS_V2


def score_all_v2(
    signals_path: Path | None = None,
    config_path: Path | None = None,
    prev_scores_path: Path | None = None,
) -> pd.DataFrame:
    ""










    from sbk_config import (
        OWN_PERSON_ID,
        OWNER_GRAPH_ID,
        RQ_SCORES_V2_FILE,
        RQ_SCORING_CONFIG_V2,
        RQ_SIGNALS_FILE,
    )

    if signals_path is None:
        signals_path = RQ_SIGNALS_FILE

    if not signals_path.exists():
        log.warning("No signals file: %s", signals_path)
        return pd.DataFrame()

    signals_df = pd.read_parquet(signals_path)
    weights = load_weights_config(config_path)


    non_ego = signals_df[~signals_df["person_id"].isin([OWN_PERSON_ID, OWNER_GRAPH_ID])]
    max_pr = float(non_ego["pagerank"].max()) if "pagerank" in non_ego.columns else 0.05
    max_bt = float(non_ego["betweenness"].max()) if "betweenness" in non_ego.columns else 0.05
    max_pr = max(max_pr, 0.001)
    max_bt = max(max_bt, 0.001)

    rows = []
    for _, signals in signals_df.iterrows():
        result = score_person_v2(signals, weights, max_pr, max_bt)
        row = {
            "person": signals["person_id"],
            "score_v2": result.score,
            "confidence": result.confidence,
            "trend": result.trend,
            "dunbar_circle": result.dunbar_circle,
        }
        for dim, val in result.breakdown.items():
            row[f"dim_{dim}"] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df


    _prev_path = prev_scores_path if prev_scores_path is not None else RQ_SCORES_V2_FILE
    if _prev_path.exists():
        try:
            prev_df = pd.read_parquet(_prev_path, columns=["person", "score_v2"])
            prev_scores = dict(zip(prev_df["person"], prev_df["score_v2"]))


            trend_threshold = 0.3
            _cfg_path = config_path if config_path is not None else RQ_SCORING_CONFIG_V2
            if _cfg_path.exists():
                try:
                    cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
                    trend_threshold = cfg.get("trend_threshold", 0.3)
                except (ValueError, OSError):
                    pass

            trends = []
            for _, row in df.iterrows():
                pid = row["person"]
                if pid in prev_scores:
                    delta = row["score_v2"] - prev_scores[pid]
                    if delta > trend_threshold:
                        trends.append("strengthening")
                    elif delta < -trend_threshold:
                        trends.append("cooling")
                    else:
                        trends.append("stable")
                else:
                    trends.append("stable")

            df["trend"] = trends
            n_str = sum(1 for t in trends if t == "strengthening")
            n_cool = sum(1 for t in trends if t == "cooling")
            n_stab = sum(1 for t in trends if t == "stable")
            log.info("V2 trend: %d strengthening, %d cooling, %d stable", n_str, n_cool, n_stab)
        except Exception as e:
            log.warning("Could not load previous V2 scores for trend: %s", e)

    return df
