""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request

log = logging.getLogger("sbk.dashboard.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("/heatmap")
async def timeline_heatmap(
    request: Request,
    channel: str = "all",
    person_id: str | None = None,
    months: int = Query(default=12, ge=1, le=60),
):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_timeline_heatmap, channel, person_id, months)


@router.get("/matrix")
async def timeline_matrix(
    request: Request,
    channel: str = "all",
    months: int = Query(default=6, ge=1, le=60),
):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_timeline_matrix, channel, months)


@router.get("/person/{person_id}")
async def person_timeline(
    request: Request,
    person_id: str,
    months: int = Query(default=12, ge=1, le=60),
):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_vis_person_timeline, person_id, months)
