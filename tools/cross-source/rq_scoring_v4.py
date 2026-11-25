""























from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from rq_event_store import (
    EVENT_DIM_CONTRIBUTIONS,
    EVENT_HALF_LIVES,
    EVENT_WEIGHTS,
    EventStore,
)
from rq_scoring_v3 import (
    DUNBAR_LABELS,
    get_dunbar_circle,
    load_v3_config,
    normalize_type_key,
)
from rq_type_detection import load_golden_overrides

log = logging.getLogger("rq.scoring_v4")



DIMENSIONS = ("intimacy", "interaction_quality", "communication_quality", "structural", "trust")


_V3_DIM_TO_V4 = {
    "trust_commitment": "trust",
    "intimacy": "intimacy",
    "interaction_quality": "interaction_quality",
    "communication_quality": "communication_quality",
    "structural": "structural",
}


_V4_DIM_TO_V3 = {v: k for k, v in _V3_DIM_TO_V4.items()}





_NAME_MAP_CACHE: dict[str, str] | None = None


def _get_cached_name_map() -> dict[str, str]:
    ""
    global _NAME_MAP_CACHE
    if _NAME_MAP_CACHE is None:
        _NAME_MAP_CACHE = _load_name_map()
    return _NAME_MAP_CACHE













GOLDEN_TIER_FLOORS = {
    "inner_circle": 8.0,
    "sympathy_group": 5.0,
    "active_network": 3.0,
}
GOLDEN_TIER_CEILINGS = {
    "inner_circle": 10.0,
    "sympathy_group": 7.9,
    "active_network": 4.9,
}

_GOLDEN_TIER_CACHE: dict[str, str] | None = None


def _load_golden_tiers() -> dict[str, str]:
    ""
    global _GOLDEN_TIER_CACHE
    if _GOLDEN_TIER_CACHE is not None:
        return _GOLDEN_TIER_CACHE

    golden_path = Path("~/.sbk-data/rq/golden-ranking.json").expanduser()
    if not golden_path.exists():
        _GOLDEN_TIER_CACHE = {}
        return _GOLDEN_TIER_CACHE

    try:
        with open(golden_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        _GOLDEN_TIER_CACHE = {}
        return _GOLDEN_TIER_CACHE


    from rq_entity_bridge import load_bridge

    bridge = load_bridge()

    tier_map: dict[str, str] = {}
    for tier_name, tier_data in data.get("tiers", {}).items():
        for member in tier_data.get("members", []):
            name = member.get("name", "").strip()
            pid = bridge.get(name.lower()) or bridge.get(name)
            if pid:
                tier_map[pid] = tier_name

    _GOLDEN_TIER_CACHE = tier_map
    return _GOLDEN_TIER_CACHE








DIMENSION_REFS = {
    "intimacy": 50.0,
    "interaction_quality": 150.0,
    "communication_quality": 50.0,
    "structural": 25.0,
    "trust": 20.0,
}





@dataclass
class ScoringResultV4:
    ""

    person_id: str
    score: float
    confidence: float
    rel_type: str
    dunbar_circle: str
    dunbar_label: str
    dims: dict[str, float] = field(default_factory=dict)
    penalty: float = 0.0
    floor_applied: bool = False
    momentum: str = "dormant"
    event_count: int = 0
    last_event_at: str | None = None
    events_7d: int = 0
    events_30d: int = 0
    events_90d: int = 0
    computed_at: str = ""
    decay_multiplier: float = 1.0





def _log_norm(value: float, reference: float) -> float:
    ""
    if not (value > 0) or not (reference > 0):
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(reference * 3))


def _event_decay(event_timestamp: str, at_time: datetime, event_type: str) -> float:
    ""



    event_dt = datetime.fromisoformat(event_timestamp)
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=UTC)
    age_days = (at_time - event_dt).total_seconds() / 86400
    if age_days <= 0:
        return 1.0
    half_life = EVENT_HALF_LIVES.get(event_type, 30)
    return max(0.01, math.exp(-math.log(2) / half_life * age_days))


def _get_type_weights(rel_type: str, config: dict) -> dict[str, float]:
    ""



    profiles = config.get("type_profiles", {})
    v3_weights = profiles.get(
        rel_type,
        profiles.get(
            "unknown",
            {
                "intimacy": 0.05,
                "interaction_quality": 0.30,
                "communication_quality": 0.20,
                "structural": 0.25,
                "trust_commitment": 0.20,
            },
        ),
    )

    v4_weights = {}
    for v3_key, weight in v3_weights.items():
        v4_key = _V3_DIM_TO_V4.get(v3_key, v3_key)
        v4_weights[v4_key] = weight
    return v4_weights


def _get_type_priors(rel_type: str, config: dict) -> dict[str, float]:
    ""
    priors = config.get("type_priors", {})
    v3_priors = priors.get(rel_type, priors.get("unknown", {}))
    v4_priors = {}
    for v3_key, value in v3_priors.items():
        v4_key = _V3_DIM_TO_V4.get(v3_key, v3_key)
        v4_priors[v4_key] = value
    return v4_priors


def _get_rel_type(
    person_id: str,
    golden_overrides: dict,
    name_map: dict[str, str],
    type_map: dict[str, str],
    type_confidence_map: dict[str, str],
) -> tuple[str, str]:
    ""







    name = name_map.get(person_id, "")
    name_lower = name.lower().strip()
    if name_lower and name_lower in golden_overrides:
        raw_type = golden_overrides[name_lower]["type"]
        conf = golden_overrides[name_lower].get("confidence", "certain")
        return normalize_type_key(raw_type), conf


    if person_id in type_map:
        raw_type = type_map[person_id]
        conf = type_confidence_map.get(person_id, "probable")
        return normalize_type_key(raw_type), conf

    return "unknown", "unverified"


def compute_momentum(events_7d: int, events_30d: int, events_90d: int) -> str:
    ""






    if events_90d == 0:
        return "dormant"


    rate_7d = events_7d / 7.0
    rate_30d = events_30d / 30.0

    if rate_30d == 0:

        if events_7d > 0:
            return "accelerating"
        return "cooling"

    ratio = rate_7d / rate_30d

    if ratio > 2.0:
        return "accelerating"
    elif ratio >= 0.5:
        return "stable"
    else:
        return "cooling"


def _compute_confidence(events: list[dict], dims: dict[str, float]) -> float:
    ""






    if not events:
        return 0.0


    count_factor = min(1.0, len(events) / 50)


    sources = {e.get("source", "unknown") for e in events}
    diversity_factor = min(1.0, len(sources) / 3)


    now = datetime.now(UTC)
    cutoff_90d = now - timedelta(days=90)
    has_recent = False
    for e in events:
        try:
            ts = datetime.fromisoformat(e["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= cutoff_90d:
                has_recent = True
                break
        except (ValueError, KeyError):
            continue
    recency_factor = 1.0 if has_recent else 0.3

    return round(min(1.0, count_factor * 0.4 + diversity_factor * 0.3 + recency_factor * 0.3), 3)





def score_person_v4(
    person_id: str,
    store: EventStore | None = None,
    at_time: datetime | None = None,
    config: dict | None = None,
    golden_overrides: dict | None = None,
    name_map: dict[str, str] | None = None,
    type_map: dict[str, str] | None = None,
    type_confidence_map: dict[str, str] | None = None,
) -> ScoringResultV4:
    ""



























    if store is None:
        store = EventStore()
    if at_time is None:
        at_time = datetime.now(UTC)
    if at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=UTC)
    if config is None:
        config = load_v3_config()
    if golden_overrides is None:
        golden_overrides = load_golden_overrides()
    if name_map is None:
        name_map = _get_cached_name_map()
    if type_map is None:
        type_map = {}
    if type_confidence_map is None:
        type_confidence_map = {}

    computed_at = datetime.now(UTC).isoformat()


    events = store.get_events(person_id)

    if not events:

        rel_type, _conf = _get_rel_type(
            person_id,
            golden_overrides,
            name_map,
            type_map,
            type_confidence_map,
        )
        return ScoringResultV4(
            person_id=person_id,
            score=1.0,
            confidence=0.0,
            rel_type=rel_type,
            dunbar_circle=get_dunbar_circle(1.0),
            dunbar_label=DUNBAR_LABELS.get(get_dunbar_circle(1.0), "Sotto soglia"),
            dims=dict.fromkeys(DIMENSIONS, 0.0),
            penalty=0.0,
            floor_applied=False,
            momentum="dormant",
            event_count=0,
            last_event_at=None,
            events_7d=0,
            events_30d=0,
            events_90d=0,
            computed_at=computed_at,
            decay_multiplier=0.0,
        )


    raw_accum = dict.fromkeys(DIMENSIONS, 0.0)
    negative_accum = 0.0
    total_decay = 0.0
    decay_count = 0

    for ev in events:
        event_type = ev.get("event_type", "")
        timestamp = ev.get("timestamp", "")
        signal_weight = float(ev.get("signal_weight", EVENT_WEIGHTS.get(event_type, 1.0)))
        is_negative = bool(ev.get("is_negative", 0))


        decay = _event_decay(timestamp, at_time, event_type)
        total_decay += decay
        decay_count += 1

        if is_negative:

            severity = int(ev.get("severity_level", 1))
            negative_accum += severity * decay * 0.05
            continue


        dim_contribs = EVENT_DIM_CONTRIBUTIONS.get(event_type, {})
        if not dim_contribs:

            dim_contribs = {
                "intimacy": float(ev.get("dim_intimacy", 0.0)),
                "interaction_quality": float(ev.get("dim_interaction_quality", 0.0)),
                "communication_quality": float(ev.get("dim_communication_quality", 0.0)),
                "structural": float(ev.get("dim_structural", 0.0)),
                "trust": float(ev.get("dim_trust", 0.0)),
            }


        for dim in DIMENSIONS:
            contrib = dim_contribs.get(dim, 0.0)
            raw_accum[dim] += contrib * signal_weight * decay

    avg_decay = total_decay / decay_count if decay_count > 0 else 0.0




















    from rq_quality_signals import load_quality_profiles

    quality_profiles = load_quality_profiles()
    qp = quality_profiles.get(person_id)



    if qp:
        quality_base = min(
            1.0, max(0.0, (qp.overall_multiplier - 0.1) / 4.86)
        )
    else:
        quality_base = 0.15


    norm_dims = {}
    for dim in DIMENSIONS:
        ref = DIMENSION_REFS.get(dim, 10.0)
        norm_dims[dim] = _log_norm(raw_accum[dim], ref)


    rel_type, type_confidence = _get_rel_type(
        person_id,
        golden_overrides,
        name_map,
        type_map,
        type_confidence_map,
    )

    weights = _get_type_weights(rel_type, config)


    type_priors = _get_type_priors(rel_type, config)
    final_dims = {}
    for dim in DIMENSIONS:
        if norm_dims[dim] <= 0.0 and type_priors.get(dim, 0.0) > 0.0:
            final_dims[dim] = type_priors[dim]
        elif norm_dims[dim] > 0.0 and norm_dims[dim] < 0.1:
            prior = type_priors.get(dim, 0.0)
            final_dims[dim] = 0.7 * norm_dims[dim] + 0.3 * prior
        else:
            final_dims[dim] = norm_dims[dim]


    confidence = _compute_confidence(events, final_dims)


    interaction_signal = sum(final_dims[dim] * weights.get(dim, 0.0) for dim in DIMENSIONS)
    interaction_signal = min(1.0, interaction_signal)






    INTERACTION_CAPS = {
        "family": 1.0,
        "close_partner": 0.70,
        "personal_friend": 0.55,
        "business_partner": 0.20,
        "advisor": 0.12,
        "investor": 0.10,
        "colleague": 0.20,
        "ex_employee": 0.05,
        "acquaintance": 0.10,
        "vendor": 0.10,
        "unknown": 0.10,
    }
    type_cap = INTERACTION_CAPS.get(rel_type, 0.30)
    interaction_signal = min(type_cap, interaction_signal)






    OWNER_ACTIVE_TYPES = {
        "email_reply_sent",
        "email_1to1_sent",
        "call_1on1",
        "meeting_1on1",
        "slack_dm",
        "whatsapp_dm",
    }
    if events:
        active_count = sum(1 for ev in events if ev.get("event_type", "") in OWNER_ACTIVE_TYPES)
        total_count = len(events)
        if total_count > 0:
            sapr = active_count / total_count

            sapr_mult = 0.1 + 0.9 * min(1.0, sapr / 0.5)
            interaction_signal *= sapr_mult


    IDENTITY_WEIGHT = 0.50
    INTERACTION_WEIGHT = 0.30
    QUALITY_CONTENT_WEIGHT = 0.20


    quality_content = 0.0
    if qp:
        profile_quality = min(1.0, qp.content_richness * 0.6 + qp.communication_style * 0.4)
    else:
        profile_quality = 0.0


    event_qualities = [
        float(ev.get("content_quality", 0) or 0) for ev in events if ev.get("content_quality")
    ]
    if event_qualities:

        peak_eq = max(event_qualities)
        avg_eq = sum(event_qualities) / len(event_qualities)
        event_quality = 0.6 * peak_eq + 0.4 * avg_eq
    else:
        event_quality = 0.0


    if event_quality > 0:
        quality_content = min(1.0, 0.6 * event_quality + 0.4 * profile_quality)
    else:
        quality_content = profile_quality

    positive = (
        quality_base * IDENTITY_WEIGHT
        + interaction_signal * INTERACTION_WEIGHT
        + quality_content * QUALITY_CONTENT_WEIGHT
    )


    penalty = min(0.3, negative_accum)

    raw_score = max(0.0, positive - penalty)













    if events:

        TIME_WEIGHTS = {
            "call_1on1": 3.0,
            "meeting_1on1": 3.0,
            "whatsapp_dm": 0.5,
            "slack_dm": 0.5,
            "email_reply_sent": 0.3,
            "email_1to1_sent": 0.3,
            "email_reply_received": 0.15,
            "email_1to1_received": 0.15,
            "call_group": 0.5,
            "meeting_group_small": 0.5,
        }
        t_weighted = (
            sum(TIME_WEIGHTS.get(ev.get("event_type", ""), 0.05) for ev in events) / 10.0
        )


        sources = set(ev.get("source", "") for ev in events)
        d_channel = min(2.0, max(0.0, (len(sources) - 1) * 0.5))


        owner_sent = sum(1 for ev in events if ev.get("event_type", "") in OWNER_ACTIVE_TYPES)
        others_sent = sum(
            1
            for ev in events
            if ev.get("event_type", "") in {"email_reply_received", "email_1to1_received"}
        )
        if owner_sent + others_sent > 0:
            r_recip = min(owner_sent, others_sent) / max(owner_sent, others_sent)
        else:
            r_recip = 0.0

        rei = t_weighted + d_channel + r_recip



        LOW_REI_TYPES = {"advisor", "investor", "vendor", "acquaintance", "unknown"}
        rei_low = 0.5 if rel_type in LOW_REI_TYPES else 0.3
        rei_mid = 1.5 if rel_type in LOW_REI_TYPES else 1.0

        if rei < rei_low:

            raw_score = min(raw_score, 0.11)
        elif rei < rei_mid:

            progress = (rei - rei_low) / (rei_mid - rei_low)
            raw_score *= 0.4 + 0.6 * progress


    score = 1.0 + raw_score * 9.0









    score_floors = config.get("score_floors", {})
    floor = score_floors.get(rel_type)
    floor_applied = False

    permanent_types = {"family", "personal_friend"}
    if rel_type in permanent_types:

        if floor is not None and score < floor:
            score = floor
            floor_applied = True
    else:

        if floor is not None and score < floor:
            score = floor
            floor_applied = True






    population_mean = 2.0
    if type_confidence != "certain":
        score = confidence * score + (1.0 - confidence) * population_mean


    if rel_type in permanent_types and floor is not None and score < floor:
        score = floor
        floor_applied = True








    score = max(1.0, min(10.0, round(score, 1)))


    circle = get_dunbar_circle(score)
    label = DUNBAR_LABELS.get(circle, circle)


    cutoff_7d = (at_time - timedelta(days=7)).isoformat()
    cutoff_30d = (at_time - timedelta(days=30)).isoformat()
    cutoff_90d = (at_time - timedelta(days=90)).isoformat()

    events_7d = 0
    events_30d = 0
    events_90d = 0
    for ev in events:
        ts = ev.get("timestamp", "")
        if ts >= cutoff_90d:
            events_90d += 1
        if ts >= cutoff_30d:
            events_30d += 1
        if ts >= cutoff_7d:
            events_7d += 1

    momentum = compute_momentum(events_7d, events_30d, events_90d)














    if events_30d == 0:

        penalty_strength = max(0.05, 0.80 - quality_base)



        is_terminated = False
        try:
            import pandas as pd

            from sbk_config import ENRICHED_DIR

            cm_path = ENRICHED_DIR / "contacts-merged.parquet"
            if cm_path.exists():
                _cm_status = pd.read_parquet(cm_path, columns=["person_id", "personio_status"])
                _status = _cm_status.set_index("person_id")["personio_status"].to_dict()
                is_terminated = str(_status.get(person_id, "")).lower() == "terminated"
        except Exception:
            pass

        if rel_type == "ex_employee" or is_terminated:

            score = score * 0.25 + 1.0 * 0.75
        elif momentum == "dormant":
            score = score * (1.0 - penalty_strength) + 1.0 * penalty_strength
        elif momentum == "cooling":
            half_penalty = penalty_strength * 0.5
            score = score * (1.0 - half_penalty) + 1.0 * half_penalty




    try:
        golden_path = Path("~/.sbk-data/rq/golden-ranking.json").expanduser()
        if golden_path.exists():
            import json as _json

            with open(golden_path, encoding="utf-8") as _f:
                _gdata = _json.load(_f)
            name_lower = (name_map.get(person_id, "") or "").lower().strip()
            for neg in _gdata.get("negative_overrides", []):
                neg_name = neg.get("name", "").lower().strip()
                if neg_name and neg_name == name_lower:
                    sev = neg.get("severity", 0)
                    penalty_pct = {0: 0, 1: 0.05, 2: 0.15, 3: 0.30, 4: 0.60, 5: 0.90}.get(sev, 0)
                    score = score * (1.0 - penalty_pct)
                    break
    except Exception:
        pass

    score = max(1.0, min(10.0, round(score, 1)))


    last_event_at = events[0].get("timestamp") if events else None

    return ScoringResultV4(
        person_id=person_id,
        score=score,
        confidence=confidence,
        rel_type=rel_type,
        dunbar_circle=circle,
        dunbar_label=label,
        dims={d: round(v, 4) for d, v in final_dims.items()},
        penalty=round(penalty, 4),
        floor_applied=floor_applied,
        momentum=momentum,
        event_count=len(events),
        last_event_at=last_event_at,
        events_7d=events_7d,
        events_30d=events_30d,
        events_90d=events_90d,
        computed_at=computed_at,
        decay_multiplier=round(avg_decay, 4),
    )





def _load_name_map() -> dict[str, str]:
    ""




    name_map: dict[str, str] = {}
    try:
        import pandas as pd

        from sbk_config import ENRICHED_DIR

        cm_path = ENRICHED_DIR / "contacts-merged.parquet"
        if cm_path.exists():
            cm = pd.read_parquet(cm_path, columns=["person_id", "name"])
            for _, row in cm.iterrows():
                pid = str(row.get("person_id", ""))
                name = str(row.get("name", "")) if pd.notna(row.get("name")) else ""
                if pid and name:
                    name_map[pid] = name
    except Exception as exc:
        log.warning("Failed to load contacts-merged names: %s", exc)


    try:
        from rq_entity_bridge import load_bridge

        bridge = load_bridge()
        for key, pid in bridge.items():
            if pid not in name_map:

                if (
                    not key.startswith("p_")
                    and not key.startswith("person_")
                    and not key.startswith("pu_")
                    and "@" not in key
                    and "nameonly:" not in key.lower()
                    and len(key) > 2
                ):

                    existing = name_map.get(pid, "")
                    if len(key) > len(existing):
                        name_map[pid] = key.title()
    except Exception as exc:
        log.warning("Failed to load bridge names: %s", exc)

    return name_map


def _load_type_maps(config: dict) -> tuple[dict[str, str], dict[str, str]]:
    ""




    try:
        import pandas as pd

        from sbk_config import RQ_DIR


        types_path = RQ_DIR / "relationship-types-v2.parquet"
        if not types_path.exists():
            types_path = RQ_DIR / "relationship-types.parquet"
        if not types_path.exists():
            return {}, {}

        types_df = pd.read_parquet(types_path)

        pid_col = "person_id" if "person_id" in types_df.columns else "person"
        type_col = "relationship_type" if "relationship_type" in types_df.columns else "type"
        conf_col = (
            "type_confidence"
            if "type_confidence" in types_df.columns
            else ("confidence" if "confidence" in types_df.columns else None)
        )

        type_map: dict[str, str] = {}
        type_confidence_map: dict[str, str] = {}

        if pid_col in types_df.columns and type_col in types_df.columns:
            for _, row in types_df.iterrows():
                pid = str(row[pid_col]).strip()
                rtype = str(row[type_col]).strip()
                if pid and rtype and rtype != "nan":
                    type_map[pid] = rtype
                    if conf_col and conf_col in row.index:
                        tc = str(row[conf_col]).strip()
                        if tc and tc != "nan":
                            type_confidence_map[pid] = tc

        return type_map, type_confidence_map
    except Exception as exc:
        log.warning("Failed to load type maps: %s", exc)
        return {}, {}


def score_all_v4(
    store: EventStore | None = None,
    config: dict | None = None,
    use_cache: bool = True,
) -> list[ScoringResultV4]:
    ""












    if store is None:
        store = EventStore()
    if config is None:
        config = load_v3_config()

    from rq_scoring_blocklist import is_blocked, load_blocklist

    blocklist = load_blocklist()
    golden_overrides = load_golden_overrides()
    name_map = _load_name_map()
    type_map, type_confidence_map = _load_type_maps(config)

    at_time = datetime.now(UTC)
    all_person_ids = store.get_all_person_ids()

    log.info(
        "Scoring %d persons (cache=%s, golden=%d overrides)",
        len(all_person_ids),
        "on" if use_cache else "off",
        len(golden_overrides),
    )

    results: list[ScoringResultV4] = []
    cached_count = 0
    scored_count = 0
    blocked_count = 0

    for person_id in all_person_ids:

        person_name = name_map.get(person_id, person_id)
        if is_blocked(person_id, blocklist) or is_blocked(person_name, blocklist):
            blocked_count += 1
            continue


        if use_cache:
            cached = store.get_cached_score(person_id)
            if cached is not None:

                results.append(
                    ScoringResultV4(
                        person_id=person_id,
                        score=cached["score"],
                        confidence=cached.get("confidence", 0.0),
                        rel_type=cached.get("rel_type", "unknown"),
                        dunbar_circle=cached.get("dunbar_circle", "extended"),
                        dunbar_label=DUNBAR_LABELS.get(
                            cached.get("dunbar_circle", "extended"), "extended"
                        ),
                        dims=cached.get("dims", {}),
                        momentum=cached.get("momentum", "dormant"),
                        event_count=cached.get("event_count", 0),
                        last_event_at=cached.get("last_event_at"),
                        events_7d=cached.get("events_7d", 0),
                        events_30d=cached.get("events_30d", 0),
                        events_90d=cached.get("events_90d", 0),
                        computed_at=cached.get("computed_at", ""),
                    )
                )
                cached_count += 1
                continue


        result = score_person_v4(
            person_id=person_id,
            store=store,
            at_time=at_time,
            config=config,
            golden_overrides=golden_overrides,
            name_map=name_map,
            type_map=type_map,
            type_confidence_map=type_confidence_map,
        )
        results.append(result)
        scored_count += 1


        store.update_cache(
            person_id,
            {
                "score": result.score,
                "confidence": result.confidence,
                "rel_type": result.rel_type,
                "dunbar_circle": result.dunbar_circle,
                "dims": result.dims,
                "momentum": result.momentum,
                "event_count": result.event_count,
                "last_event_at": result.last_event_at,
                "events_7d": result.events_7d,
                "events_30d": result.events_30d,
                "events_90d": result.events_90d,
            },
        )


    results.sort(key=lambda r: (-r.score, r.person_id))

    log.info(
        "V4: %d scored fresh, %d from cache, %d blocked (total: %d)",
        scored_count,
        cached_count,
        blocked_count,
        len(results),
    )
    return results





def validate_golden_ranking(
    results: list[ScoringResultV4],
    name_map: dict[str, str] | None = None,
) -> list[str]:
    ""













    from sbk_config import RQ_DIR

    golden_path = RQ_DIR / "golden-ranking.json"
    if not golden_path.exists():
        return ["golden-ranking.json not found"]

    try:
        with open(golden_path, encoding="utf-8") as f:
            golden = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"Failed to load golden-ranking.json: {exc}"]

    if name_map is None:
        name_map = _get_cached_name_map()


    name_to_rank: dict[str, int] = {}
    for rank, result in enumerate(results, 1):
        name = name_map.get(result.person_id, "").lower().strip()
        if name:
            name_to_rank[name] = rank

    violations: list[str] = []
    tier_limits = {
        "inner_circle": 15,
        "sympathy_group": 30,
        "active_network": 50,
    }

    tiers = golden.get("tiers", {})
    for tier_name, limit in tier_limits.items():
        tier = tiers.get(tier_name, {})
        members = tier.get("members", [])
        for member in members:
            name = member.get("name", "").lower().strip()
            rank = name_to_rank.get(name)
            if rank is None:
                violations.append(
                    f"MISSING: {member['name']} ({tier_name}) not found in scored results"
                )
            elif rank > limit:
                violations.append(
                    f"RANK: {member['name']} ({tier_name}) ranked #{rank}, expected top {limit}"
                )

    return violations





def _format_score_line(r: ScoringResultV4, name: str, rank: int) -> str:
    ""
    dims_str = " ".join(f"{d[:3]}={v:.2f}" for d, v in r.dims.items())
    return (
        f"  {rank:>4}. {name:30s}  "
        f"score={r.score:5.1f}  conf={r.confidence:.2f}  "
        f"type={r.rel_type:18s}  circle={r.dunbar_circle:16s}  "
        f"mom={r.momentum:12s}  "
        f"ev={r.event_count:>5}  "
        f"7d={r.events_7d:>3}  30d={r.events_30d:>4}  90d={r.events_90d:>5}  "
        f"{dims_str}"
    )


def main() -> None:
    ""
    parser = argparse.ArgumentParser(
        description="RQV4 Scoring Engine — event-driven, per-event decay"
    )
    parser.add_argument("--person", help="Score specific person_id")
    parser.add_argument("--top", type=int, default=50, help="Show top N (default: 50)")
    parser.add_argument("--all", action="store_true", help="Score all and update cache")
    parser.add_argument(
        "--no-cache", action="store_true", help="Force recompute all (ignore cache)"
    )
    parser.add_argument(
        "--validate-golden", action="store_true", help="Check golden ranking invariants"
    )
    parser.add_argument("--db", type=str, default=None, help="Path to event store DB")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--snapshot", action="store_true", help="Write daily score snapshot after scoring"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    store = EventStore(db_path=args.db)
    if not store.db_path.exists():
        log.error(f"Event store not found at {store.db_path}")
        log.error("  Run: uv run tools/cross-source/rq_event_store.py --create")
        sys.exit(1)

    config = load_v3_config()
    name_map = _load_name_map()

    if args.person:

        golden_overrides = load_golden_overrides()
        type_map, type_confidence_map = _load_type_maps(config)

        result = score_person_v4(
            person_id=args.person,
            store=store,
            config=config,
            golden_overrides=golden_overrides,
            name_map=name_map,
            type_map=type_map,
            type_confidence_map=type_confidence_map,
        )

        name = name_map.get(args.person, args.person)

        if args.json:
            print(json.dumps(asdict(result), indent=2, default=str))
        else:
            print(f"\n{'=' * 70}")
            print(f"  V4 Score: {name} ({args.person})")
            print(f"{'=' * 70}")
            print(f"  Score:       {result.score:.1f} / 10.0")
            print(f"  Confidence:  {result.confidence:.3f}")
            print(f"  Type:        {result.rel_type}")
            print(f"  Circle:      {result.dunbar_circle} ({result.dunbar_label})")
            print(f"  Momentum:    {result.momentum}")
            print(f"  Floor:       {'YES' if result.floor_applied else 'no'}")
            print(f"  Penalty:     {result.penalty:.4f}")
            print(f"  Avg decay:   {result.decay_multiplier:.4f}")
            print(f"  Events:      {result.event_count} total")
            print(f"    7d: {result.events_7d}  30d: {result.events_30d}  90d: {result.events_90d}")
            print(f"  Last event:  {result.last_event_at or 'n/a'}")
            print("\n  Dimensions:")
            for dim, val in result.dims.items():
                bar = "#" * int(val * 40)
                print(f"    {dim:25s}  {val:.4f}  |{bar}")
            print()
        return


    results = score_all_v4(
        store=store,
        config=config,
        use_cache=not args.no_cache,
    )

    if args.snapshot:
        n = store.snapshot_daily()
        log.info("Snapshot: %d records written", n)

    if args.json:
        print(json.dumps([asdict(r) for r in results[: args.top]], indent=2, default=str))
        return


    show_n = min(args.top, len(results)) if not args.all else len(results)
    print(f"\n{'=' * 120}")
    print(f"  RQV4 Scoring — Top {show_n} of {len(results)} persons")
    print(f"{'=' * 120}")

    for rank, result in enumerate(results[:show_n], 1):
        name = name_map.get(result.person_id, result.person_id)
        print(_format_score_line(result, name, rank))

    print(f"\n  Total: {len(results)} scored persons")


    circle_counts: dict[str, int] = {}
    for r in results:
        circle_counts[r.dunbar_circle] = circle_counts.get(r.dunbar_circle, 0) + 1
    print("\n  Circle distribution:")
    for circle_name in [
        "inner_circle",
        "sympathy_group",
        "active_network",
        "full_network",
        "extended",
    ]:
        cnt = circle_counts.get(circle_name, 0)
        print(f"    {circle_name:20s}  {cnt:>5}")


    mom_counts: dict[str, int] = {}
    for r in results:
        mom_counts[r.momentum] = mom_counts.get(r.momentum, 0) + 1
    print("\n  Momentum distribution:")
    for mom in ["accelerating", "stable", "cooling", "dormant"]:
        cnt = mom_counts.get(mom, 0)
        print(f"    {mom:20s}  {cnt:>5}")


    if args.validate_golden:
        print(f"\n{'=' * 70}")
        print("  Golden Ranking Validation")
        print(f"{'=' * 70}")
        violations = validate_golden_ranking(results, name_map)
        if not violations:
            print("  ALL CHECKS PASSED")
        else:
            for v in violations:
                print(f"  VIOLATION: {v}")
            print(f"\n  {len(violations)} violation(s) found")

    print()


if __name__ == "__main__":
    main()
