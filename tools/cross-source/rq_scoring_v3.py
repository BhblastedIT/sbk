""













from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd
from rq_missing_data import MissingDataHandler

log = logging.getLogger("rq.scoring_v3")

CONFIG_PATH = Path(__file__).resolve().parent / "scoring-config-v3.json"


DUNBAR_CIRCLES = [
    (8.0, 10.01, "inner_circle"),
    (5.0, 8.0, "sympathy_group"),
    (3.0, 5.0, "active_network"),
    (1.5, 3.0, "full_network"),
    (0.0, 1.5, "extended"),
]

DUNBAR_LABELS = {
    "inner_circle": "Collaboratore strettissimo",
    "sympathy_group": "Contatto importante",
    "active_network": "Contatto regolare",
    "full_network": "Conoscenza",
    "extended": "Sotto soglia",
}


DEFAULT_PROFILES = {
    "unknown": {
        "intimacy": 0.15,
        "interaction_quality": 0.30,
        "communication_quality": 0.20,
        "structural": 0.15,
        "trust_commitment": 0.20,
    },
}
DEFAULT_HALF_LIVES = {"unknown": 60}




TYPE_KEY_MAP = {
    "colleague_team": "colleague",
    "colleague_project": "colleague",
    "direct_report": "colleague",
    "manager": "colleague",
    "business_partner": "business_partner",
    "professional_friend": "personal_friend",
    "family_personal": "family",
    "introduced": "acquaintance",

    "acquaintance": "acquaintance",
    "ex_employee": "ex_employee",
    "investor": "investor",
    "vendor": "vendor",
    "family": "family",
    "colleague": "colleague",
    "close_partner": "close_partner",
    "personal_friend": "personal_friend",
    "advisor": "advisor",
    "client": "client",
    "unknown": "unknown",
}


def normalize_type_key(raw_type: str) -> str:
    ""
    return TYPE_KEY_MAP.get(raw_type, "unknown")


@dataclass
class ScoringResultV3:
    ""

    score: float
    dims: dict[str, float]
    raw_dims: dict[str, float]
    confidence: float
    severity_level: int
    penalty: float
    rel_type: str
    weights_used: dict[str, float]
    floor_applied: bool
    dunbar_circle: str
    dunbar_label: str
    trend: str = "stable"
    decay_multiplier: float = 1.0





def _log_norm(value: float, reference: float) -> float:
    ""




    if not (value > 0) or not (reference > 0):
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(reference * 3))


def _safe_float(signals, key: str, default: float = 0.0) -> float:
    ""
    val = signals.get(key, default)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return float(val)


def _safe_int(signals, key: str, default: int = 0) -> int:
    ""
    val = signals.get(key, default)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return int(val)





def normalize_intimacy_v3(signals: pd.Series) -> float:
    ""













    disclosure = _log_norm(_safe_int(signals, "self_disclosure_count", 0), 10)
    trend = _safe_float(signals, "formality_trend", 0.0)
    trend_norm = max(0.0, min(1.0, 0.5 + trend))
    laughter = _log_norm(_safe_float(signals, "laughter_per_minute", 0.0), 1.0)

    is_family = 1.0 if bool(signals.get("is_family", False)) else 0.0
    family_facts = _log_norm(_safe_int(signals, "family_fact_count", 0), 5)
    family_signal = max(is_family, family_facts)
    hobby = _log_norm(_safe_int(signals, "hobby_fact_count", 0), 10)

    return min(
        1.0,
        0.15 * family_signal
        + 0.18 * _log_norm(_safe_int(signals, "personal_topic_count", 0), 10)
        + 0.13 * _safe_float(signals, "whatsapp_late_night_pct", 0.0)
        + 0.10 * _safe_float(signals, "whatsapp_informal_score", 0.0)
        + 0.10 * _safe_float(signals, "weekend_evening_email_ratio", 0.0)
        + 0.09 * _log_norm(_safe_int(signals, "topic_breadth", 0), 10)
        + 0.09 * disclosure
        + 0.09 * trend_norm
        + 0.05 * laughter
        + 0.02 * hobby,
    )


def normalize_iq_v3(signals: pd.Series) -> float:
    ""









    components = []
    weights = []

    freq = _safe_float(signals, "recency_weighted_frequency", 0.0)
    freq_log = math.log1p(freq * 100) / math.log1p(100)
    components.append(freq_log)
    weights.append(0.20)

    email_lat = _safe_float(signals, "email_response_latency_hours", 48.0)
    if email_lat != 48.0:
        components.append(max(0.0, 1.0 - email_lat / 48.0))
        weights.append(0.25)

    slack_lat = _safe_float(signals, "slack_response_latency_hours", 24.0)
    if slack_lat != 24.0:
        components.append(max(0.0, 1.0 - slack_lat / 24.0))
        weights.append(0.15)

    cov = _safe_float(signals, "contact_rhythm_cov", 1.0)
    if cov != 1.0:
        components.append(max(0.0, 1.0 - cov / 4.0))
        weights.append(0.15)

    balance = _safe_float(signals, "turn_taking_balance", 0.5)
    if balance != 0.5:
        components.append(balance)
        weights.append(0.15)


    duration = _safe_float(signals, "relationship_duration_days", 0.0)
    if duration > 0:
        components.append(_log_norm(duration, 365 * 5))
        weights.append(0.10)

    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return min(1.0, sum(c * w / total_w for c, w in zip(components, weights)))


def normalize_comm_quality(signals: pd.Series) -> float:
    ""











    trend = _safe_float(signals, "formality_trend", 0.0)
    trend_norm = max(0.0, min(1.0, 0.5 + trend))

    disclosure = _log_norm(_safe_int(signals, "self_disclosure_count", 0), 10)
    lsm = _safe_float(signals, "linguistic_style_matching", 0.0)
    warmth = _safe_float(signals, "meeting_warmth_score", 0.0)
    emo = _log_norm(_safe_float(signals, "emotional_word_density", 0.0), 0.1)
    inclusive = _safe_float(signals, "inclusive_pronoun_ratio", 0.0)
    laughter = _log_norm(_safe_float(signals, "laughter_per_minute", 0.0), 1.0)
    personal = _safe_float(signals, "personal_topic_in_meeting", 0.0)

    return min(
        1.0,
        0.15 * trend_norm
        + 0.15 * disclosure
        + 0.15 * lsm
        + 0.15 * warmth
        + 0.10 * emo
        + 0.10 * inclusive
        + 0.10 * laughter
        + 0.10 * personal,
    )


def normalize_structural_v3(
    signals: pd.Series,
    max_pagerank: float = 0.05,
    max_betweenness: float = 0.05,
) -> float:
    ""







    pr = min(1.0, _safe_float(signals, "pagerank", 0.0) / max_pagerank) if max_pagerank > 0 else 0.0
    bt = (
        min(1.0, _safe_float(signals, "betweenness", 0.0) / max_betweenness)
        if max_betweenness > 0
        else 0.0
    )
    intro = _log_norm(_safe_int(signals, "introductions_count", 0), 10)
    mux = _log_norm(_safe_int(signals, "multiplexity_bidir", 0), 4)

    return min(1.0, 0.40 * pr + 0.30 * bt + 0.25 * intro + 0.05 * mux)


def normalize_trust_v3(signals: pd.Series) -> float:
    ""







    promise = _safe_float(signals, "promise_completion_ratio", 0.0)
    ai = _log_norm(_safe_int(signals, "action_items_count", 0), 50)
    raw_attio = _safe_float(signals, "attio_connection_strength", 0.0)
    attio = _log_norm(raw_attio, 100) if raw_attio > 0 else 0.0
    commit = _log_norm(_safe_int(signals, "commitment_facts_count", 0), 20)

    return min(1.0, 0.30 * promise + 0.25 * ai + 0.25 * attio + 0.20 * commit)





def _compute_recency_multiplier(days_ago: float, half_life: float = 180.0) -> float:
    ""
    if days_ago <= 0:
        return 1.0
    decay = math.pow(0.5, days_ago / half_life)
    return max(0.15, decay)


def get_dunbar_circle(score: float) -> str:
    for low, high, circle in DUNBAR_CIRCLES:
        if low <= score < high:
            return circle
    return "extended"


def load_v3_config(config_path: Path | None = None) -> dict:
    ""
    if config_path is None:
        config_path = CONFIG_PATH
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def score_person_v3(
    signals: pd.Series,
    rel_type: str,
    missing_handler: MissingDataHandler,
    config: dict | None = None,
    max_pagerank: float = 0.05,
    max_betweenness: float = 0.05,
) -> ScoringResultV3:
    ""












    if config is None:
        config = {}


    rel_type = normalize_type_key(rel_type)


    profiles = config.get("type_profiles", DEFAULT_PROFILES)
    weights = profiles.get(rel_type, profiles.get("unknown", DEFAULT_PROFILES["unknown"]))


    raw_dims = {
        "intimacy": normalize_intimacy_v3(signals),
        "interaction_quality": normalize_iq_v3(signals),
        "communication_quality": normalize_comm_quality(signals),
        "structural": normalize_structural_v3(signals, max_pagerank, max_betweenness),
        "trust_commitment": normalize_trust_v3(signals),
    }


    signals_dict = signals.to_dict() if hasattr(signals, "to_dict") else dict(signals)
    md_result = missing_handler.process_person(signals_dict, rel_type)


    dims = {}
    for dim_name, raw_val in raw_dims.items():
        dim_status = md_result["dimension_statuses"].get(dim_name, "OBSERVED_STRONG")
        adjusted_val = missing_handler.apply_prior(raw_val, dim_status, dim_name, rel_type)
        dims[dim_name] = adjusted_val

    confidence = md_result["confidence"]


    positive = sum(dims[k] * weights.get(k, 0.0) for k in dims)



    from sbk_config import RQ_SEVERITY_ENABLED

    severity_level = _safe_int(signals, "severity_level", 0)
    severity_penalty = 0.0
    if not RQ_SEVERITY_ENABLED:
        pass

    raw_score = positive


    score = 1.0 + raw_score * 9.0


    floor = md_result.get("floor")
    floor_applied = False
    if floor is not None and score < floor:
        score = floor
        floor_applied = True


    half_lives = config.get("type_half_lives", DEFAULT_HALF_LIVES)
    half_life = half_lives.get(rel_type, half_lives.get("unknown", 60))
    days_ago = _safe_float(signals, "last_interaction_days_ago", 365.0)
    decay_mult = _compute_recency_multiplier(days_ago, half_life)
    score = 1.0 + (score - 1.0) * decay_mult

    score = max(1.0, min(10.0, round(score, 1)))

    circle = get_dunbar_circle(score)

    return ScoringResultV3(
        score=score,
        dims={k: round(v, 4) for k, v in dims.items()},
        raw_dims={k: round(v, 4) for k, v in raw_dims.items()},
        confidence=confidence,
        severity_level=severity_level,
        penalty=severity_penalty,
        rel_type=rel_type,
        weights_used=weights,
        floor_applied=floor_applied,
        dunbar_circle=circle,
        dunbar_label=DUNBAR_LABELS.get(circle, circle),
        decay_multiplier=round(decay_mult, 4),
    )





def score_all_v3(
    signals_path: Path | None = None,
    types_path: Path | None = None,
    config_path: Path | None = None,
) -> pd.DataFrame:
    ""









    from sbk_config import OWN_PERSON_ID, OWNER_GRAPH_ID, RQ_DIR, RQ_SIGNALS_FILE

    if signals_path is None:
        signals_path = RQ_SIGNALS_FILE
    if types_path is None:

        types_path = RQ_DIR / "relationship-types-v2.parquet"
        if not types_path.exists():
            types_path = RQ_DIR / "relationship-types.parquet"

    if not signals_path.exists():
        log.warning("No signals file: %s", signals_path)
        return pd.DataFrame()

    signals_df = pd.read_parquet(signals_path)
    config = load_v3_config(config_path)
    missing_handler = MissingDataHandler(config_path)


    type_map: dict[str, str] = {}
    if types_path.exists():
        types_df = pd.read_parquet(types_path)


        pid_col = "person_id" if "person_id" in types_df.columns else "person"
        type_col = "relationship_type" if "relationship_type" in types_df.columns else "type"
        if pid_col in types_df.columns and type_col in types_df.columns:
            for _, row in types_df.iterrows():
                pid = str(row[pid_col]).strip()
                rtype = str(row[type_col]).strip()
                if pid and rtype and rtype != "nan":
                    type_map[pid] = rtype
    log.info("Loaded %d relationship types from %s", len(type_map), types_path.name)


    non_ego = signals_df[~signals_df["person_id"].isin([OWN_PERSON_ID, OWNER_GRAPH_ID])]
    max_pr = max(0.001, float(non_ego["pagerank"].max()) if "pagerank" in non_ego.columns else 0.05)
    max_bt = max(
        0.001, float(non_ego["betweenness"].max()) if "betweenness" in non_ego.columns else 0.05
    )

    rows = []
    for _, signals in signals_df.iterrows():
        pid = str(signals["person_id"])
        rel_type = type_map.get(pid, "unknown")

        result = score_person_v3(signals, rel_type, missing_handler, config, max_pr, max_bt)

        row = {
            "person": pid,
            "score_v3": result.score,
            "confidence": result.confidence,
            "relationship_type": result.rel_type,
            "severity_level": result.severity_level,
            "severity_penalty": result.penalty,
            "floor_applied": result.floor_applied,
            "decay_multiplier": result.decay_multiplier,
            "dunbar_circle": result.dunbar_circle,
            "dunbar_label": result.dunbar_label,
            "trend_v3": result.trend,
            "weights_used": json.dumps(result.weights_used),
        }
        for dim, val in result.dims.items():
            row[f"dim_{dim}"] = val
        for dim, val in result.raw_dims.items():
            row[f"raw_dim_{dim}"] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info("Scored %d persons with V3 engine", len(df))
    return df
