""

from __future__ import annotations

import asyncio
import csv
import io

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/decay", tags=["decay"])


@router.get("/state")
def decay_state(request: Request, tier: str = "all"):
    bridge = request.app.state.bridge
    items = bridge.get_decay_state(tier_filter=tier)
    return JSONResponse({"items": items, "count": len(items), "tier": tier})


@router.get("/export")
def decay_export(request: Request, tier: str = "all"):
    ""
    bridge = request.app.state.bridge
    items = bridge.get_decay_state(tier_filter=tier if tier != "all" else None)

    output = io.StringIO()
    if items:
        writer = csv.DictWriter(output, fieldnames=items[0].keys())
        writer.writeheader()
        writer.writerows(items)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=decay-export.csv"},
    )


@router.get("/breakdown")
def decay_breakdown(request: Request, pid: str = ""):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    bridge = request.app.state.bridge
    data = bridge.get_decay_breakdown(pid)
    return JSONResponse(data)


@router.get("/alerts")
def decay_alerts(request: Request):
    bridge = request.app.state.bridge
    alerts = bridge.get_decay_alerts()
    return JSONResponse({"alerts": alerts, "count": len(alerts)})


@router.get("/rfm")
async def rfm_analysis(request: Request):
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_rfm_analysis)


@router.get("/sparklines")
async def health_sparklines(request: Request):
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_health_sparklines)


@router.get("/company-pulse")
async def company_pulse(request: Request):
    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_company_pulse)
