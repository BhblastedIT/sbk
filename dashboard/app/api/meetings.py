""





from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class MeetingCaptureRequest(BaseModel):
    source: Literal["plaud", "tactiq", "attio"]
    file_path: str = Field(..., min_length=1)
    provider: str = "anthropic"


from ..core.sbk_bridge import safe_path_param

logger = logging.getLogger("dashboard.meetings")

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None





@router.get("/summaries")
def list_meeting_summaries(
    request: Request,
    limit: int = 20,
    source: str = "all",
    person: str = "",
):
    ""






    if limit > 100:
        limit = 100
    bridge = request.app.state.bridge
    try:
        data = bridge.get_meeting_summaries(limit=limit, source_filter=source, person_filter=person)
    except Exception:
        logger.exception("Failed to load meeting summaries")
        return JSONResponse({"error": "Failed to load meeting summaries"}, status_code=500)
    return JSONResponse(data)


@router.get("/summaries/{meeting_id}")
def get_meeting_summary(request: Request, meeting_id: str):
    ""
    if safe_path_param(meeting_id) is None:
        return JSONResponse({"error": "Invalid meeting_id"}, status_code=400)
    bridge = request.app.state.bridge
    try:
        summary = bridge.get_meeting_summary(meeting_id)
    except Exception:
        logger.exception("Failed to load meeting summary %s", meeting_id)
        return JSONResponse({"error": "Failed to load meeting summary"}, status_code=500)
    if not summary:
        return JSONResponse({"error": "Meeting summary not found"}, status_code=404)
    return JSONResponse(summary)


@router.post("/capture")
async def trigger_meeting_capture(request: Request):
    ""






    body = MeetingCaptureRequest(**(await _parse_json(request) or {}))
    if safe_path_param(body.file_path) is None:
        return JSONResponse({"error": "Invalid file_path"}, status_code=400)

    bridge = request.app.state.bridge
    result = await asyncio.to_thread(
        bridge.capture_meeting_from_file,
        body.source,
        body.file_path.strip(),
        provider=body.provider,
    )
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@router.get("/by-person/{person_id}")
def meetings_by_person(request: Request, person_id: str, limit: int = 10):
    ""
    if limit > 50:
        limit = 50
    bridge = request.app.state.bridge
    try:
        data = bridge.get_meetings_by_person(person_id, limit=limit)
    except Exception:
        logger.exception("Failed to load meetings for person %s", person_id)
        return JSONResponse({"error": "Failed to load meetings for person"}, status_code=500)
    return JSONResponse(data)



