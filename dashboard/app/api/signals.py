""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class SignalConfigUpdate(BaseModel):
    min_score: float | None = None
    days_back: int | None = None
    max_signals: int | None = None
    enabled_sources: list[str] | None = None


logger = logging.getLogger("dashboard.signals")

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def list_signals(
    request: Request,
    days_back: int = 30,
    min_score: float = 0.0,
    status: str = "all",
    limit: int = 50,
):
    ""







    days_back = max(1, min(days_back, 365))
    min_score = max(0.0, min(min_score, 1.0))
    if limit > 200:
        limit = 200
    bridge = request.app.state.bridge
    data = bridge.get_signals(
        days_back=days_back,
        min_score=min_score,
        status_filter=status,
        limit=limit,
    )
    return JSONResponse(data)


@router.get("/config")
def get_signal_config(request: Request):
    ""
    bridge = request.app.state.bridge
    return JSONResponse(bridge.get_signal_config())


@router.put("/config")
async def update_signal_config(request: Request, body: SignalConfigUpdate):
    ""
    bridge = request.app.state.bridge
    filtered = body.model_dump(exclude_none=True)
    if not filtered:
        return JSONResponse({"error": "No valid configuration fields provided"}, status_code=400)

    updated = await asyncio.to_thread(bridge.update_signal_config, filtered)
    return JSONResponse({"status": "ok", "config": updated})


@router.get("/{signal_id}")
def get_signal(request: Request, signal_id: str):
    ""
    bridge = request.app.state.bridge
    s = bridge.get_signal_detail(signal_id)
    if s is None:
        return JSONResponse({"error": "Signal not found"}, status_code=404)
    return JSONResponse(s)


@router.put("/{signal_id}/dismiss")
def dismiss_signal(request: Request, signal_id: str):
    ""
    bridge = request.app.state.bridge
    updated = bridge.dismiss_signal(signal_id)
    if updated is None:
        return JSONResponse({"error": "Signal not found"}, status_code=404)
    return JSONResponse({"status": "ok", "signal": updated})


@router.post("/scan")
async def trigger_scan(request: Request):
    ""
    import subprocess
    import sys
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tools"
        / "monitoring"
        / "signal-detector.py"
    )
    if not script.exists():
        return JSONResponse({"error": "Signal detector script not found"}, status_code=500)

    try:
        import asyncio

        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(script), "--scan", "--no-synthesize"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            logger.error("Signal scan failed: %s", result.stderr[-500:] if result.stderr else "")
        return JSONResponse(
            {
                "status": "ok" if result.returncode == 0 else "error",
            }
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Signal scan timed out"}, status_code=504)
