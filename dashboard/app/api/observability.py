""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request

log = logging.getLogger("sbk.dashboard.observability")

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/realtime")
async def realtime_health(request: Request):
    ""
    import asyncio

    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_realtime_health)


@router.get("/pipeline-metrics")
async def pipeline_metrics(request: Request, hours: int = Query(default=24, ge=1, le=720)):
    ""
    import asyncio

    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_pipeline_metrics, hours)


@router.get("/costs")
async def api_costs(request: Request, hours: int = Query(default=24, ge=1, le=720)):
    ""
    import asyncio

    from monitoring.api_ledger import get_cost_summary

    return await asyncio.to_thread(get_cost_summary, hours)


@router.get("/health-detailed")
async def health_detailed(request: Request):
    ""
    import asyncio

    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_detailed_health)


@router.get("/connections")
async def connections(request: Request):
    ""
    import asyncio

    bridge = request.app.state.bridge
    return await asyncio.to_thread(bridge.get_connection_status)


@router.get("/cost-trend")
async def cost_trend(request: Request, days: int = Query(default=7, ge=1, le=365)):
    ""
    import asyncio

    from monitoring.api_ledger import get_cost_trend

    return await asyncio.to_thread(get_cost_trend, days)
