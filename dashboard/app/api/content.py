""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class CaptureIdeaRequest(BaseModel):
    text: str = Field(..., min_length=1)


logger = logging.getLogger("dashboard.content")

router = APIRouter(prefix="/api", tags=["content"])


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None





@router.get("/content/ideas")
def list_content_ideas(request: Request, status: str = ""):
    ""
    bridge = request.app.state.bridge
    ideas = bridge.get_content_ideas(status_filter=status or None)
    return {"ideas": ideas, "total": len(ideas)}


@router.put("/content/ideas/{idea_id}")
async def update_content_idea(request: Request, idea_id: str):
    ""
    bridge = request.app.state.bridge
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    updated = await asyncio.to_thread(bridge.update_content_idea, idea_id, body)
    if updated is None:
        return JSONResponse({"error": f"Idea '{idea_id}' not found"}, status_code=404)
    return {"idea": updated}


@router.post("/content/generate")
def generate_content_ideas(request: Request):
    ""
    bridge = request.app.state.bridge
    result = bridge.generate_content_ideas()
    status_code = 200 if result.get("status", "error") == "ok" else 422
    return JSONResponse(result, status_code=status_code)





@router.post("/ideas/capture")
async def capture_idea(request: Request, body: CaptureIdeaRequest):
    ""
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.capture_idea, body.text.strip())
    status_code = 201 if result.get("status", "error") == "ok" else 422
    return JSONResponse(result, status_code=status_code)


@router.get("/ideas")
def list_ideas(request: Request, status: str = ""):
    ""
    bridge = request.app.state.bridge
    ideas = bridge.get_ideas(status_filter=status or None)
    return {"ideas": ideas, "total": len(ideas)}


@router.get("/ideas/{idea_id}")
def get_idea(request: Request, idea_id: str):
    ""
    bridge = request.app.state.bridge
    idea = bridge.get_idea(idea_id)
    if idea is None:
        return JSONResponse({"error": f"Idea '{idea_id}' not found"}, status_code=404)
    return {"idea": idea}


@router.put("/ideas/{idea_id}")
async def update_idea(request: Request, idea_id: str):
    ""
    bridge = request.app.state.bridge
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    updated = await asyncio.to_thread(bridge.update_idea, idea_id, body)
    if updated is None:
        return JSONResponse({"error": f"Idea '{idea_id}' not found"}, status_code=404)
    return {"idea": updated}
