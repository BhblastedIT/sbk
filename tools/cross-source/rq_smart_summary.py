""








from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

log = logging.getLogger("rq.summary")




CONTEXT_THRESHOLDS = {
    "profile": {
        "min_score": 3.0,
        "states": ["active", "cooling"],
        "max_results": 10,
        "include_trend": False,
    },
    "colleagues": {
        "min_score": 2.0,
        "states": ["active", "cooling"],
        "types": [
            "colleague_team",
            "colleague_project",
            "direct_report",
            "manager",
        ],
        "max_results": 15,
        "include_trend": False,
    },
    "historical": {
        "min_score": 0.0,
        "states": ["active", "cooling", "dormant", "ended"],
        "max_results": 30,
        "include_trend": True,
    },
    "warm_intro": {
        "min_score": 0.0,
        "use_warm_intros": True,
        "max_results": 5,
        "include_trend": False,
    },
    "trend": {
        "min_score": 1.0,
        "states": ["active", "cooling", "dormant"],
        "include_trend": True,
        "max_results": 20,
    },
}


def get_adaptive_threshold(query_context: str) -> dict:
    ""








    return CONTEXT_THRESHOLDS.get(query_context, CONTEXT_THRESHOLDS["profile"]).copy()


def filter_relationships(
    relationships: list[dict],
    threshold: dict,
) -> list[dict]:
    ""








    min_score = threshold.get("min_score", 0.0)
    allowed_states = set(threshold.get("states", ["active", "cooling"]))
    allowed_types = threshold.get("types")
    max_results = threshold.get("max_results", 10)

    filtered = []
    for rel in relationships:
        score = rel.get("score", 0.0)
        state = rel.get("state", "active")
        rel_type = rel.get("relationship_type", "")

        if score < min_score:
            continue
        if state not in allowed_states:
            continue
        if allowed_types and rel_type not in allowed_types:
            continue


        confidence = rel.get("type_confidence", "")
        if confidence == "unverified" and min_score > 0.0:
            continue

        filtered.append(rel)


    filtered.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return filtered[:max_results]




CONFIDENCE_DISPLAY = {
    "certain": {
        "show": True,
        "style": "direct",
        "prefix": "",
        "suffix": "",
    },
    "probable": {
        "show": True,
        "style": "qualified",
        "prefix": "Probabilmente ",
        "suffix": "",
    },
    "unverified": {
        "show": False,
        "style": "hidden",
        "prefix": "",
        "suffix": " (da verificare)",
    },
}


def get_confidence_display(confidence: str) -> dict:
    ""







    return CONFIDENCE_DISPLAY.get(confidence, CONFIDENCE_DISPLAY["unverified"]).copy()


def format_type_with_confidence(rel_type: str, confidence: str) -> str:
    ""








    from rq_type_detection import get_type_label

    label = get_type_label(rel_type)
    display = get_confidence_display(confidence)

    if not display["show"]:
        return ""

    return f"{display['prefix']}{label}{display['suffix']}"





TREND_LABELS = {
    "strengthening": "in crescita",
    "stable": "stabile",
    "cooling": "in calo",
    "dormant": "dormiente",
    "ended": "conclusa",
}


DUNBAR_LABELS = {
    "inner_circle": "collaboratore strettissimo",
    "sympathy_group": "contatto importante",
    "active_network": "contatto regolare",
    "full_network": "conoscenza",
    "extended": "contatto marginale",
}


STATE_LABELS = {
    "active": "Attiva",
    "cooling": "In raffreddamento",
    "dormant": "Dormiente",
    "ended": "Conclusa",
}


def format_narrative(
    person_name: str,
    relationship: dict,
) -> str:
    ""









    score = relationship.get("score", 0.0)
    dunbar = relationship.get("dunbar_circle", "extended")
    trend = relationship.get("trend", "stable")
    state = relationship.get("state", "active")
    rel_type = relationship.get("relationship_type", "")
    confidence = relationship.get("type_confidence", "unverified")


    type_str = format_type_with_confidence(rel_type, confidence)


    dunbar_str = DUNBAR_LABELS.get(dunbar, dunbar)
    trend_str = TREND_LABELS.get(trend, trend)
    state_str = STATE_LABELS.get(state, state)

    parts = []


    if type_str:
        parts.append(f"{person_name} - {type_str}.")
    else:
        parts.append(f"{person_name}.")


    parts.append(f"Score: {score}/10 ({dunbar_str}).")


    if state in ("dormant", "ended"):
        parts.append(f"Stato: {state_str}.")
    elif trend != "stable":
        parts.append(f"Relazione {trend_str}.")

    return " ".join(parts)


def format_breakdown(
    person_name: str,
    relationship: dict,
) -> str:
    ""








    score = relationship.get("score", 0.0)
    breakdown = relationship.get("breakdown", {})
    trend = relationship.get("trend", "stable")
    state = relationship.get("state", "active")
    rel_type = relationship.get("relationship_type", "")
    confidence = relationship.get("type_confidence", "unverified")
    dunbar = relationship.get("dunbar_circle", "extended")

    lines = [f"{person_name} - Score: {score}/10"]


    dim_labels = {
        "frequency": "Frequenza",
        "intensity": "Intensita'",
        "reciprocity": "Reciprocita'",
        "channel_diversity": "Canali",
        "shared_context": "Contesto",
    }

    for dim, label in dim_labels.items():
        val = breakdown.get(dim, 0.0)
        bar_filled = round(val * 10)
        bar_empty = 10 - bar_filled
        bar = "\u2588" * bar_filled + "\u2591" * bar_empty
        lines.append(f"  {label + ':':<16} {val * 10:.1f} {bar}")


    state_str = STATE_LABELS.get(state, state)
    trend_str = TREND_LABELS.get(trend, trend)
    dunbar_str = DUNBAR_LABELS.get(dunbar, dunbar)
    type_str = format_type_with_confidence(rel_type, confidence)

    lines.append(f"  Stato: {state_str} ({trend_str})")
    lines.append(f"  Cerchia: {dunbar_str}")
    if type_str:
        lines.append(f"  Tipo: {type_str}")

    return "\n".join(lines)





def load_relationship_detail(
    person_id: str,
    relationships_dir: Path | None = None,
) -> dict | None:
    ""








    if relationships_dir is None:
        from sbk_config import KNOWLEDGE_RELATIONSHIPS_DIR

        relationships_dir = KNOWLEDGE_RELATIONSHIPS_DIR

    detail_file = relationships_dir / f"{person_id}.json"
    if not detail_file.exists():
        return None

    try:
        return json.loads(detail_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load relationship detail %s: %s", detail_file, exc)
        return None


def load_all_relationships(
    relationships_dir: Path | None = None,
) -> list[dict]:
    ""




    if relationships_dir is None:
        from sbk_config import KNOWLEDGE_RELATIONSHIPS_DIR

        relationships_dir = KNOWLEDGE_RELATIONSHIPS_DIR

    if not relationships_dir.exists():
        return []

    results = []
    for detail_file in relationships_dir.glob("*.json"):
        if detail_file.name == "third-party-index.json":
            continue
        try:
            data = json.loads(detail_file.read_text(encoding="utf-8"))
            data["_person_id"] = detail_file.stem
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    return results





REFRESH_TIERS = [
    (50, 6),
    (500, 24),
    (float("inf"), 168),
]


def needs_refresh(
    last_scored: str | None,
    interaction_count: int = 0,
    now: datetime | None = None,
) -> bool:
    ""









    if not last_scored:
        return True

    if now is None:
        now = datetime.now(UTC)

    try:
        scored_at = datetime.fromisoformat(last_scored)
        if scored_at.tzinfo is None:
            scored_at = scored_at.replace(tzinfo=UTC)
        age_hours = (now - scored_at).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return True

    for max_interactions, max_age_hours in REFRESH_TIERS:
        if interaction_count < max_interactions:
            return age_hours > max_age_hours

    return False





def get_relationship_summary(
    person_id: str,
    context: str = "profile",
    relationships_dir: Path | None = None,
) -> dict:
    ""










    all_rels = load_all_relationships(relationships_dir)



    person_rel = load_relationship_detail(person_id, relationships_dir)

    threshold = get_adaptive_threshold(context)

    if person_rel:

        person_rel["_person_id"] = person_id
        filtered = filter_relationships([person_rel], threshold)
        return {
            "person_id": person_id,
            "context": context,
            "relationship": filtered[0] if filtered else None,
            "total_count": 1,
            "filtered_count": len(filtered),
        }


    filtered = filter_relationships(all_rels, threshold)
    return {
        "person_id": person_id,
        "context": context,
        "relationships": filtered,
        "total_count": len(all_rels),
        "filtered_count": len(filtered),
    }
