""








from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("dashboard.api.insights")

router = APIRouter(prefix="/api/insights", tags=["insights"])


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None


@router.get("/weekly")
def weekly_insights_latest(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_weekly_insights()
    if data is None:
        return JSONResponse(
            {"error": "No weekly insights found. Run xs-temporal-analysis.py first."},
            status_code=404,
        )
    return data


@router.get("/weekly/partial", response_class=HTMLResponse)
def weekly_insights_partial(request: Request):
    ""
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
    bridge = request.app.state.bridge
    data = bridge.get_weekly_insights()
    insights = data.get("insights", []) if data else []
    return templates.TemplateResponse(
        "partials/weekly_insights.html",
        {"request": request, "insights": insights, "week_data": data},
    )


@router.get("/weekly/{week}")
def weekly_insights_by_week(request: Request, week: str):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_weekly_insights(week=week)
    if data is None:
        return JSONResponse({"error": f"No insights found for week {week}"}, status_code=404)
    return data


@router.post("/feedback")
async def insight_feedback(request: Request):
    ""



    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    week = body.get("week", "")
    insight_id = body.get("insight_id", "")
    feedback = body.get("feedback", "")

    if not all([week, insight_id, feedback]):
        return JSONResponse(
            {"error": "week, insight_id, and feedback are required"}, status_code=400
        )

    if feedback not in ("POSITIVE", "NEGATIVE"):
        return JSONResponse({"error": "feedback must be POSITIVE or NEGATIVE"}, status_code=400)

    bridge = request.app.state.bridge
    success = await asyncio.to_thread(bridge.save_insight_feedback, week, insight_id, feedback)

    if not success:
        return JSONResponse({"error": f"Could not save feedback for week {week}"}, status_code=500)

    return {"status": "ok", "week": week, "insight_id": insight_id, "feedback": feedback}
