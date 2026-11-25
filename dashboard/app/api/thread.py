""

from __future__ import annotations

import json
import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..core.sbk_bridge import safe_path_param

router = APIRouter(prefix="/api/thread", tags=["thread"])


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


@router.get("/{source_type}/{source_id:path}")
def get_thread(request: Request, source_type: str, source_id: str):
    if safe_path_param(source_id) is None:
        raise HTTPException(status_code=400, detail="Invalid source_id path")
    bridge = request.app.state.bridge
    data = bridge.get_thread(source_type, source_id)
    return _json_response(data)
