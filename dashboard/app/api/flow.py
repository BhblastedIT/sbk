""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request

log = logging.getLogger("sbk.dashboard.flow")

router = APIRouter(prefix="/api/flow", tags=["flow"])


@router.get("/chord")
async def communication_chord(
    request: Request,
    top_n: int = Query(default=30, ge=1, le=200),
    channel: str = "all",
):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_communication_chord, top_n, channel)


@router.get("/sankey")
async def investor_sankey(request: Request):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_investor_sankey)


@router.get("/matrix")
async def communication_matrix(request: Request, top_n: int = Query(default=30, ge=1, le=200)):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_communication_matrix, top_n)


@router.get("/momentum/{person_id}")
async def person_momentum(request: Request, person_id: str):
    ""
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_person_momentum, person_id)
