""









from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field


class InvestorActionRequest(BaseModel):
    action_type: str = Field(..., min_length=1)
    notes: str = ""


log = logging.getLogger("dashboard.api.fundraising")

router = APIRouter(prefix="/api/fundraising", tags=["fundraising"])


_last_suggest_ts: float = 0.0


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None


@router.get("/pipeline")
def fundraising_pipeline(
    request: Request,
    stage: str | None = None,
    sort: str = "priority",
    order: str = "desc",
):
    ""
    bridge = request.app.state.bridge
    pipeline = bridge.get_fundraising_pipeline(
        stage_filter=stage,
        sort_by=sort,
        order=order,
    )
    return {"pipeline": pipeline, "total": len(pipeline)}


@router.get("/pipeline/partial", response_class=HTMLResponse)
def fundraising_pipeline_partial(
    request: Request,
    stage: str | None = None,
    sort: str = "priority",
    order: str = "desc",
):
    ""
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
    bridge = request.app.state.bridge
    pipeline = bridge.get_fundraising_pipeline(
        stage_filter=stage,
        sort_by=sort,
        order=order,
    )
    return templates.TemplateResponse(
        "partials/fundraising_pipeline.html",
        {"request": request, "pipeline": pipeline, "total": len(pipeline)},
    )


@router.get("/investor/{email}/momentum")
def investor_momentum(request: Request, email: str):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_investor_momentum(email=email)
    if data.get("entry") is None:
        return JSONResponse(
            {"error": "Investor not found in momentum scores", "email": email}, status_code=404
        )
    return data


@router.get("/investor/{email}/suggest")
def investor_suggest_action(request: Request, email: str):
    ""




    global _last_suggest_ts  # noqa: PLW0603
    now = time.time()
    if now - _last_suggest_ts < 5.0:
        return JSONResponse(
            {"error": "Rate limit: max 1 AI suggestion per 5 seconds."}, status_code=429
        )
    _last_suggest_ts = now

    if len(email) > 200:
        return JSONResponse({"error": "Email too long"}, status_code=400)

    bridge = request.app.state.bridge


    pipeline = bridge.get_fundraising_pipeline()
    investor = None
    for entry in pipeline:
        if entry.get("email", "").lower() == email.lower():
            investor = entry
            break

    if not investor:
        return JSONResponse(
            {"error": "Investor not found in pipeline", "email": email}, status_code=404
        )


    momentum = bridge.get_investor_momentum(email=email)
    mom_entry = momentum.get("entry", {}) or {}


    prompt = _build_suggest_prompt(investor, mom_entry)

    try:
        import anthropic

        client = anthropic.Anthropic(timeout=30.0)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        suggestion = json.loads(text)
        return {"suggestion": suggestion, "investor": investor["name"]}
    except Exception as e:
        log.error("AI suggestion failed for %s: %s", email, e)
        return {
            "suggestion": {
                "action": "Review the state of the relationship and consider a follow-up",
                "priority": "media",
                "reasoning": "Generic suggestion (AI unavailable)",
                "timing": "this week",
            },
            "investor": investor.get("name", email),
            "ai_error": True,
        }


def _build_suggest_prompt(investor: dict, momentum: dict) -> str:
    ""
    mom_score = momentum.get("score", "N/A")
    mom_trend = momentum.get("trend", "N/A")
    factors = momentum.get("factors", {})
    engagement = momentum.get("engagement_signals", [])
    risks = momentum.get("risk_signals", [])

    signals_text = ""
    if engagement:
        signals_text += f"\nPositive signals: {', '.join(engagement[:5])}"
    if risks:
        signals_text += f"\nNegative signals: {', '.join(risks[:5])}"

    from sbk_config import OWNER_LABEL

    return f"""You are the AI Chief of Staff of {OWNER_LABEL}. Suggest the next action for this investor.

INVESTOR: {investor.get("name", "N/A")} ({investor.get("company", "N/A")})
ROLE: {investor.get("job_title", "N/A")}
STAGE: {investor.get("stage", "N/A")}
DAYS SINCE LAST CONTACT: {investor.get("days_since", "N/A")}
MOMENTUM SCORE: {mom_score}/100 (trend: {mom_trend})
FACTORS: freq={factors.get("response_frequency", "N/A")}, speed={factors.get("response_speed", "N/A")}, sentiment={factors.get("sentiment", "N/A")}, depth={factors.get("question_depth", "N/A")}
EMAILS EXCHANGED: {investor.get("emails_exchanged", 0)}
CRM NOTES: {investor.get("notes_count", 0)}{signals_text}

Respond with ONLY valid JSON (no markdown, no backtick):
{{"action": "specific and concrete action (max 1 sentence)", "priority": "alta|media|bassa", "reasoning": "why this action (max 2 sentences)", "timing": "by when"}}"""


@router.post("/investor/{email}/action")
async def register_investor_action(request: Request, email: str):
    ""



    from sbk_config import INVESTORS_DIR

    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        parsed = InvestorActionRequest(**body)
    except Exception:
        return JSONResponse({"error": "action_type is required"}, status_code=400)
    action_type = parsed.action_type
    notes = parsed.notes

    log_file = INVESTORS_DIR / "action-log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "created": datetime.now(UTC).isoformat(),
        "investor_email": email,
        "type": action_type,
        "notes": notes,
        "source": "dashboard",
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "entry": entry}
