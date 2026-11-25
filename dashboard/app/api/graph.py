""

from __future__ import annotations

import json
import math

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response

from sbk_config import GRAPH_DIR

router = APIRouter(prefix="/api/graph", tags=["graph"])

_GRAPH_DIR = GRAPH_DIR


def _sanitize(obj):
    ""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0
    return obj


def _json_response(data, status_code=200):
    ""
    clean = _sanitize(data)
    body = json.dumps(clean, ensure_ascii=False)
    return Response(content=body, status_code=status_code, media_type="application/json")


@router.get("/stats")
def graph_stats(request: Request):
    bridge = request.app.state.bridge
    stats = bridge.get_graph_stats()
    return _json_response(stats)


@router.get("/data")
def graph_data(
    request: Request,
    min_score: float = 0,
    community: int = -99,
    max_nodes: int = 200,
    tier: str = "",
    org: str = "",
    include_shadow: bool = False,
    max_shadow: int = 50,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_graph_data(
        min_score=min_score,
        community=community,
        max_nodes=max_nodes,
        tier=tier or None,
        org=org or None,
        include_shadow=include_shadow,
        max_shadow=max_shadow,
    )
    return _json_response(data)


@router.get("/warm-intro")
def warm_intro(request: Request, target: str = "", max_hops: int = 3):
    ""
    if not target:
        return _json_response({"paths": [], "error": "Target required"}, status_code=400)
    bridge = request.app.state.bridge
    paths = bridge.find_warm_intro_path(target, max_hops)
    return _json_response({"paths": paths, "target": target})


@router.get("/connection")
def graph_connection(request: Request, a: str = "", b: str = ""):
    ""
    if not a or not b:
        return _json_response({"error": "Parameters a and b are required"}, status_code=400)
    bridge = request.app.state.bridge
    detail = bridge.get_connection_detail(a, b)
    return _json_response(detail)


@router.get("/intelligence")
def graph_intelligence(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_network_intelligence()
    return _json_response(data)


@router.get("/shadow")
def shadow_contacts(
    request: Request,
    q: str = "",
    min_score: float = 0,
    limit: int = Query(default=50, ge=1, le=500),
):
    ""
    bridge = request.app.state.bridge
    results = bridge.get_shadow_contacts(query=q, min_score=min_score, limit=limit)
    return _json_response({"shadow_contacts": results, "count": len(results)})


@router.get("/ego")
def ego_network(
    request: Request,
    pid: str = "",
    max_neighbors: int = 20,
    exclude: str = "",
    include_shadow: bool = False,
):
    ""
    if not pid:
        return _json_response({"error": "pid required"}, status_code=400)
    bridge = request.app.state.bridge
    exclude_set = {p.strip() for p in exclude.split(",") if p.strip()} if exclude else None
    data = bridge.get_ego_network(
        pid=pid,
        max_neighbors=max_neighbors,
        exclude_pids=exclude_set,
        include_shadow=include_shadow,
    )
    return _json_response(data)


@router.get("/smart-intros")
def smart_intros(request: Request, limit: int = Query(default=20, ge=1, le=200)):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_smart_intro_suggestions(limit=limit)
    return _json_response(data)


@router.get("/smart-intros/{person_id}")
def smart_intros_for_person(
    request: Request, person_id: str, limit: int = Query(default=10, ge=1, le=100)
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_smart_intro_suggestions(person_id=person_id, limit=limit)
    return _json_response(data)


@router.get("/html")
def graph_html():
    html_path = _GRAPH_DIR / "sbk-network.html"
    if not html_path.exists():
        return _json_response({"error": "Graph HTML not found"}, status_code=404)
    return FileResponse(str(html_path), media_type="text/html")
