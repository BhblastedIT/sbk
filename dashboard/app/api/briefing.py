""







from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("sbk.dashboard.briefing")

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


import os

_DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
_BRIEFING_LOG_DIR = _DATA_ROOT / "briefings"


_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def _briefing_log_path(d: date | None = None) -> Path:
    d = d or date.today()
    return _BRIEFING_LOG_DIR / f"briefing-{d.isoformat()}.json"


def _collect_briefing_sections(bridge) -> tuple[list, list, list, list, str, dict]:
    ""



    from briefing import br_daily_briefing as br

    calendar = br._collect_calendar_events(bridge)
    emails = br._collect_emails_needing_reply(bridge)
    followups = br._collect_followups(bridge)
    focus = br._collect_focus_items(bridge)
    text = br.format_briefing(calendar, emails, followups, focus)
    sections = {
        "meetings_today": len(calendar),
        "emails_pending": len(emails),
        "followups_due": len(followups),
        "focus_items": len(focus),
    }
    return calendar, emails, followups, focus, text, sections


@router.get("/status")
def briefing_status():
    ""
    path = _briefing_log_path()
    if not path.exists():
        return {"sent": False, "date": date.today().isoformat()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "sent": data.get("sent", False),
            "date": data.get("date", ""),
            "sent_at": data.get("sent_at", ""),
            "sections": data.get("sections", {}),
        }
    except (json.JSONDecodeError, OSError):
        return {"sent": False, "date": date.today().isoformat()}


@router.get("/preview")
def briefing_preview(request: Request):
    ""
    bridge = request.app.state.bridge
    _calendar, _emails, _followups, _focus, text, sections = _collect_briefing_sections(bridge)

    return {
        "text": text,
        "sections": sections,
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/send")
def briefing_send(request: Request):
    ""
    from briefing import br_daily_briefing as br


    path = _briefing_log_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("sent"):
                return JSONResponse(
                    {"error": "Briefing already sent today", "sent_at": data.get("sent_at", "")},
                    status_code=409,
                )
        except (json.JSONDecodeError, OSError):
            pass

    bridge = request.app.state.bridge
    _calendar, _emails, _followups, _focus, text, sections = _collect_briefing_sections(bridge)
    sent = br.send_briefing(text)

    briefing_data = {
        "date": date.today().isoformat(),
        "sent_at": datetime.now(UTC).isoformat(),
        "sent": sent,
        "briefing_id": f"brief-{date.today().isoformat()}",
        "sections": sections,
        "char_count": len(text),
    }
    br._log_briefing(briefing_data)

    if sent:
        return {"status": "sent", **briefing_data}
    else:
        return JSONResponse({"error": "Slack send failed"}, status_code=500)


@router.get("/partial", response_class=HTMLResponse)
def briefing_partial(request: Request):
    ""
    from fastapi.templating import Jinja2Templates

    templates = getattr(request.app.state, "templates", None) or Jinja2Templates(
        directory=str(Path(__file__).resolve().parent.parent / "templates")
    )


    path = _briefing_log_path()
    already_sent = False
    sent_at = ""
    sections = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            already_sent = data.get("sent", False)
            sent_at = data.get("sent_at", "")
            sections = data.get("sections", {})
        except (json.JSONDecodeError, OSError):
            pass


    preview_text = ""
    if not already_sent:
        try:
            bridge = request.app.state.bridge
            _calendar, _emails, _followups, _focus, preview_text, sections = (
                _collect_briefing_sections(bridge)
            )
        except Exception as e:
            log.warning("Briefing preview generation failed: %s", e)

    return templates.TemplateResponse(
        "partials/briefing_preview.html",
        {
            "request": request,
            "already_sent": already_sent,
            "sent_at": sent_at,
            "sections": sections,
            "preview_text": preview_text,
        },
    )
