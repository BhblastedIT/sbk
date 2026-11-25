""










from __future__ import annotations

import json
import logging
import time
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.sbk_bridge import safe_path_param

log = logging.getLogger("dashboard.api.relationships")

router = APIRouter(prefix="/api/relationships", tags=["relationships"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _apply_v2_fields(rel: dict) -> dict:
    ""
    from sbk_config import is_rq_v2_enabled

    if not is_rq_v2_enabled():
        return rel
    if "score_v2" not in rel:
        return rel
    rel = dict(rel)
    rel["score"] = rel["score_v2"]
    rel["breakdown"] = rel.get("breakdown_v2", rel.get("breakdown", {}))
    rel["dunbar_circle"] = rel.get("dunbar_circle_v2", rel.get("dunbar_circle", ""))
    rel["trend"] = rel.get("trend_v2", rel.get("trend", "stable"))
    return rel


_rels_cache: list[dict] = []
_rels_cache_ts: float = 0.0
_RELS_CACHE_TTL = 30.0


def _load_all_relationships(relationships_dir: Path) -> list[dict]:
    ""
    global _rels_cache, _rels_cache_ts
    now = time.time()
    if _rels_cache and (now - _rels_cache_ts) < _RELS_CACHE_TTL:
        return _rels_cache

    if not relationships_dir.exists():
        return []
    results = []
    for f in sorted(relationships_dir.glob("*.json")):
        if f.name in ("third-party-index.json",):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_person_id"] = f.stem
            results.append(_apply_v2_fields(data))
        except (json.JSONDecodeError, OSError):
            continue
    _rels_cache = results
    _rels_cache_ts = now
    return results


def _get_relationships_dir() -> Path:
    from sbk_config import KNOWLEDGE_RELATIONSHIPS_DIR

    return KNOWLEDGE_RELATIONSHIPS_DIR


def _get_rq_scoring_enabled() -> bool:
    from sbk_config import RQ_DIR

    flag_file = RQ_DIR / "rq-enabled.flag"
    return flag_file.exists()


@router.get("")
def list_relationships(
    request: Request,
    circle: str | None = None,
    state: str | None = None,
    type: str | None = None,
    trend: str | None = None,
    min_score: float = 0.0,
    sort: str = "score",
    limit: int = 50,
):
    ""
    rels = _load_all_relationships(_get_relationships_dir())


    if circle:
        rels = [r for r in rels if r.get("dunbar_circle") == circle]
    if state:
        rels = [r for r in rels if r.get("state") == state]
    if type:
        rels = [r for r in rels if r.get("relationship_type") == type]
    if trend:
        rels = [r for r in rels if r.get("trend") == trend]
    if min_score > 0:
        rels = [r for r in rels if (r.get("score") or 0) >= min_score]


    if sort == "score":
        rels.sort(key=lambda r: r.get("score") or 0, reverse=True)
    elif sort == "trend":
        trend_order = {"cooling": 0, "stable": 1, "strengthening": 2}
        rels.sort(key=lambda r: trend_order.get(r.get("trend", "stable"), 1))
    elif sort == "last_interaction":
        rels.sort(key=lambda r: r.get("last_interaction") or "", reverse=True)

    total = len(rels)
    rels = rels[:limit]

    return {"relationships": rels, "total": total}


@router.get("/alerts/cooling")
def cooling_alerts(request: Request, limit: int = 20):
    ""
    rels = _load_all_relationships(_get_relationships_dir())

    cooling = []
    for r in rels:
        if r.get("trend") == "cooling" or r.get("state") == "cooling":
            score = r.get("score") or 0
            prev_score = r.get("previous_score") or score
            cooling.append(
                {
                    "person_id": r.get("_person_id"),
                    "person": r.get("person", r.get("_person_id", "")),
                    "score": score,
                    "previous_score": prev_score,
                    "relationship_type": r.get("relationship_type", ""),
                    "last_interaction": r.get("last_interaction"),
                    "state": r.get("state", "active"),
                    "dunbar_circle": r.get("dunbar_circle", ""),
                }
            )


    cooling.sort(key=lambda r: r.get("score") or 0)
    return {"alerts": cooling[:limit], "total": len(cooling)}


@router.get("/network/overview")
def network_overview(request: Request):
    ""
    rels = _load_all_relationships(_get_relationships_dir())

    circle_counts = Counter()
    state_counts = Counter()
    total_active = 0

    for r in rels:
        circle = r.get("dunbar_circle", "extended")
        state = r.get("state", "active")
        circle_counts[circle] += 1
        state_counts[state] += 1
        if state in ("active", "cooling"):
            total_active += 1

    return {
        "circles": dict(circle_counts),
        "states": dict(state_counts),
        "total_active": total_active,
        "total": len(rels),
    }


@router.get("/scorecard")
def scorecard(request: Request):
    ""
    from sbk_config import is_rq_v2_enabled

    rels = _load_all_relationships(_get_relationships_dir())

    if not rels:
        return {
            "avg_score": 0,
            "breakdown_averages": {},
            "type_distribution": {},
            "trend_summary": {},
            "total": 0,
        }

    scores = [r.get("score") or 0 for r in rels if r.get("score")]


    if is_rq_v2_enabled():
        dims = [
            "intimacy",
            "interaction_quality",
            "structural",
            "trust_commitment",
            "negative_signals",
        ]
    else:
        dims = ["frequency", "intensity", "reciprocity", "shared_context"]

    breakdown_avgs = {}
    for dim in dims:
        vals = [r.get("breakdown", {}).get(dim, 0) for r in rels if r.get("breakdown")]
        breakdown_avgs[dim] = round(sum(vals) / len(vals), 3) if vals else 0

    type_counts = Counter()
    trend_counts = Counter()
    for r in rels:
        rtype = r.get("relationship_type", "unknown")
        type_counts[rtype] += 1
        trend = r.get("trend", "stable")
        trend_counts[trend] += 1


    total = len(rels)
    type_dist = {k: round(v / total * 100, 1) for k, v in type_counts.most_common()}

    return {
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "breakdown_averages": breakdown_avgs,
        "type_distribution": type_dist,
        "trend_summary": dict(trend_counts),
        "total": total,
    }


@router.get("/{entity_id}")
def relationship_detail(request: Request, entity_id: str):
    ""
    if safe_path_param(entity_id) is None:
        return JSONResponse({"error": "Invalid entity_id"}, status_code=400)
    rel_dir = _get_relationships_dir()
    detail_file = rel_dir / f"{entity_id}.json"

    if not detail_file.exists():
        return JSONResponse(
            {"error": "Relationship not found", "entity_id": entity_id}, status_code=404
        )

    try:
        data = json.loads(detail_file.read_text(encoding="utf-8"))
        data["_person_id"] = entity_id
        return _apply_v2_fields(data)
    except (json.JSONDecodeError, OSError) as e:
        return JSONResponse({"error": f"Failed to read: {e}"}, status_code=500)


@router.get("/{entity_id}/warm-intros")
def warm_intros(request: Request, entity_id: str):
    ""
    if safe_path_param(entity_id) is None:
        return JSONResponse({"error": "Invalid entity_id"}, status_code=400)
    rel_dir = _get_relationships_dir()
    detail_file = rel_dir / f"{entity_id}.json"

    if not detail_file.exists():
        return JSONResponse({"error": "Relationship not found"}, status_code=404)

    try:
        data = json.loads(detail_file.read_text(encoding="utf-8"))
        data = _apply_v2_fields(data)
        intros = data.get("warm_intros", [])
        return {"warm_intros": intros, "entity_id": entity_id}
    except (json.JSONDecodeError, OSError):
        return {"warm_intros": [], "entity_id": entity_id}
