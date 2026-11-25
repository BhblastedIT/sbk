""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/ner", tags=["ner"])


@router.get("/query")
def ner_query(
    request: Request,
    entity_type: str = "all",
    search: str = "",
    speaker: str = "",
    page: int = 1,
    per_page: int = 50,
):
    ""
    if entity_type not in ("all", "person", "organization", "location", "date", "product", "money"):
        return JSONResponse({"error": f"Invalid entity_type '{entity_type}'"}, status_code=400)
    bridge = request.app.state.bridge
    result = bridge.query_ner(
        entity_type=entity_type if entity_type != "all" else None,
        search=search or None,
        speaker=speaker or None,
        page=page,
        per_page=per_page,
    )
    return JSONResponse(result)


@router.get("/stats")
def ner_stats(request: Request):
    ""
    bridge = request.app.state.bridge
    stats = bridge.get_ner_stats()
    return JSONResponse(stats)
