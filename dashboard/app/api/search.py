""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    source: str = ""
    after: str = ""
    before: str = ""
    person: str = ""
    top_k: int = Field(default=10, ge=1, le=100)


class SynthesizeQuery(BaseModel):
    query: str = Field(..., min_length=1)
    results: list = Field(..., min_length=1)


logger = logging.getLogger("dashboard.search")

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/query")
async def search_query(request: Request, body: SearchQuery):
    query = body.query.strip()
    bridge = request.app.state.bridge
    source = body.source or None
    after = body.after or None
    before = body.before or None
    person = body.person or None
    top_k = body.top_k

    try:
        result = await asyncio.to_thread(
            bridge.search,
            query=query,
            source=source,
            after=after,
            before=before,
            person=person,
            top_k=top_k,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Search failed for query: %s", query)
        return JSONResponse(
            {"error": "Internal search error", "results": [], "count": 0},
            status_code=500,
        )


@router.post("/unified")
async def search_unified(request: Request, body: SearchQuery):
    ""
    query = body.query.strip()
    bridge = request.app.state.bridge
    try:
        result = await asyncio.to_thread(bridge.unified_search, query)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Unified search failed for query: %s", query)
        return JSONResponse(
            {"error": "Internal search error", "facts": {}, "semantic": {}, "deep": {}},
            status_code=500,
        )


@router.post("/synthesize")
async def search_synthesize(request: Request, body: SynthesizeQuery):
    query = body.query.strip()
    results = body.results

    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.synthesize_search, query, results)
    return JSONResponse(result)
