""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("sbk.dashboard.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/cache-stats")
def cache_stats(request: Request) -> JSONResponse:
    ""
    from app.core.sbk_bridge import _METHOD_CACHE, _METHOD_CACHE_MAXSIZE

    bridge = request.app.state.bridge
    data = bridge._data

    mtime_props = {}
    for prop in ("contacts", "interactions", "threads", "relationship_facts"):
        mt = getattr(data, f"_mtime_prop_{prop}_mt", None)
        mtime_props[prop] = {"loaded": mt is not None and mt > 0, "mtime": mt}

    return JSONResponse(
        {
            "method_cache": {"size": len(_METHOD_CACHE), "maxsize": _METHOD_CACHE_MAXSIZE},
            "sbk_data_mtime": mtime_props,
            "bridge_json_cache": {
                "decay_state_mtime": bridge._decay_state_mtime,
                "entity_map_mtime": bridge._entity_map_mtime,
                "centrality_mtime": bridge._centrality_mtime,
                "annotations_mtime": bridge._annotations_mtime,
            },
        }
    )


@router.post("/cache-clear")
def cache_clear(request: Request) -> JSONResponse:
    ""
    from app.core.sbk_bridge import _METHOD_CACHE

    bridge = request.app.state.bridge
    data = bridge._data

    mc_size = len(_METHOD_CACHE)
    _METHOD_CACHE.clear()


    for prop in ("contacts", "interactions", "threads", "relationship_facts"):
        mt_key = f"_mtime_prop_{prop}_mt"
        if hasattr(data, mt_key):
            object.__setattr__(data, mt_key, 0)


    bridge._decay_state_mtime = 0
    bridge._entity_map_mtime = 0
    bridge._centrality_mtime = 0
    bridge._annotations_mtime = 0


    cleared = [k for k in list(data.__dict__) if not k.startswith("_")]
    for k in cleared:
        del data.__dict__[k]

    return JSONResponse(
        {
            "status": "cleared",
            "method_cache_cleared": mc_size,
            "cached_properties_cleared": cleared,
        }
    )


@router.get("/api-stats")
def api_stats(hours: int = Query(default=1, ge=1, le=24)):
    ""
    try:
        import sys
        from pathlib import Path

        tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))

        from monitoring.api_ledger import get_stats

        stats = get_stats(hours=hours)
        return JSONResponse(stats)
    except Exception as e:
        log.warning("api-stats failed: %s", e)
        return JSONResponse({"error": "Failed to load API stats"}, status_code=500)
