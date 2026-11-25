""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class CommitmentStatusUpdate(BaseModel):
    status: Literal["PENDING", "KEPT", "BROKEN", "EXPIRED", "DISMISSED"]


logger = logging.getLogger("dashboard.commitments")

router = APIRouter(prefix="/api/commitments", tags=["commitments"])


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None


@router.get("")
def list_commitments(
    request: Request,
    status: str = "all",
    person: str = "",
    days_ahead: int = 0,
    limit: int = 100,
    offset: int = 0,
):
    ""








    if limit > 500:
        limit = 500
    bridge = request.app.state.bridge
    data = bridge.get_commitments(
        status_filter=status,
        person=person,
        days_ahead=days_ahead,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(data)


@router.get("/stats")
def commitment_stats(request: Request):
    ""
    bridge = request.app.state.bridge
    return JSONResponse(bridge.get_commitment_stats())


@router.get("/{commitment_id}")
def get_commitment(request: Request, commitment_id: str):
    ""
    bridge = request.app.state.bridge
    c = bridge.get_commitment_detail(commitment_id)
    if c is None:
        return JSONResponse({"error": "Commitment not found"}, status_code=404)
    return JSONResponse(c)


@router.put("/{commitment_id}/status")
async def update_status(request: Request, commitment_id: str):
    ""



    bridge = request.app.state.bridge
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        parsed = CommitmentStatusUpdate(**body)
    except Exception:
        return JSONResponse({"error": "Invalid status"}, status_code=400)

    updated = await asyncio.to_thread(bridge.update_commitment_status, commitment_id, parsed.status)
    if updated is None:
        return JSONResponse({"error": "Commitment not found"}, status_code=404)

    return JSONResponse({"status": "ok", "commitment": updated})


@router.post("/consolidate")
async def trigger_consolidate(request: Request):
    ""
    import subprocess
    import sys
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tools"
        / "cross-source"
        / "xs-commitment-consolidate.py"
    )
    if not script.exists():
        return JSONResponse({"error": "Consolidation script not found"}, status_code=500)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(script), "--incremental"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("Consolidation failed: %s", result.stderr[-500:] if result.stderr else "")
        return JSONResponse(
            {
                "status": "ok" if result.returncode == 0 else "error",
            }
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Consolidation timed out"}, status_code=504)
