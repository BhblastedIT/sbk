""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request

log = logging.getLogger("sbk.api.notifications")
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _aggregate_notifications(bridge, include_date: bool = False) -> list[dict]:
    ""
    from concurrent.futures import ThreadPoolExecutor

    notifications: list[dict] = []


    with ThreadPoolExecutor(max_workers=3) as executor:
        f_sources = executor.submit(bridge.get_freshness_report)
        f_alerts = executor.submit(bridge.get_decay_alerts)
        f_followup = executor.submit(bridge.get_followup_items, 0)


    try:
        sources = f_sources.result()
        for s in sources:
            status = s.get("status", "OK")
            if status == "CRITICO":
                entry = {
                    "id": f"health-critico-{s['source']}",
                    "type": "health",
                    "severity": "error",
                    "title": f"{s['source']} CRITICAL",
                    "message": f"Last sync {s.get('elapsed', '?')}",
                    "link": "/health-overview",
                }
                if include_date:
                    entry["date"] = date.today().isoformat()
                notifications.append(entry)
            elif status == "STALE":
                entry = {
                    "id": f"health-stale-{s['source']}",
                    "type": "health",
                    "severity": "warning",
                    "title": f"{s['source']} not up to date",
                    "message": f"Last sync {s.get('elapsed', '?')}",
                    "link": "/health-overview",
                }
                if include_date:
                    entry["date"] = date.today().isoformat()
                notifications.append(entry)
    except Exception as e:
        log.warning("Failed to aggregate source health notifications: %s", e)


    try:
        alerts = f_alerts.result()
        for alert in alerts[:10]:
            name = alert.get("name", alert.get("person_id", "?"))
            days = alert.get("days_since", "?")
            entry = {
                "id": f"decay-{alert.get('person_id', name)}",
                "type": "decay",
                "severity": "warning",
                "title": f"Lost contact: {name}",
                "message": f"{days}d without contact"
                + (f", tier {alert.get('tier', '?')}" if include_date else ""),
                "link": f"/person?auto={name}",
            }
            if include_date:
                entry["date"] = date.today().isoformat()
            notifications.append(entry)
    except Exception as e:
        log.warning("Failed to aggregate decay notifications: %s", e)


    try:
        followup_data = f_followup.result()
        overdue = [
            i for i in followup_data.get("items", []) if i.get("urgency") in ("overdue", "critical")
        ]
        for item in overdue[:10]:
            person = item.get("person", "?")
            entry = {
                "id": f"followup-{item.get('hash', person)}",
                "type": "followup",
                "severity": "error" if item.get("urgency") == "critical" else "warning",
                "title": f"Follow-up overdue: {person}" if include_date else f"Follow-up: {person}",
                "message": item.get("action", "")[:80],
                "link": f"/person?auto={person}",
            }
            if include_date:
                entry["date"] = item.get("deadline", date.today().isoformat())
            notifications.append(entry)
    except Exception as e:
        log.warning("Failed to aggregate followup notifications: %s", e)

    return notifications


@router.get("")
def get_notifications(request: Request):
    ""






    bridge = request.app.state.bridge
    notifications = _aggregate_notifications(bridge, include_date=True)

    return JSONResponse(
        {
            "notifications": notifications,
            "count": len(notifications),
            "counts": {
                "health": sum(1 for n in notifications if n["type"] == "health"),
                "decay": sum(1 for n in notifications if n["type"] == "decay"),
                "followup": sum(1 for n in notifications if n["type"] == "followup"),
            },
        }
    )


@router.get("/panel", response_class=HTMLResponse)
def notifications_panel(request: Request):
    ""
    bridge = request.app.state.bridge
    notifications = _aggregate_notifications(bridge)

    return _templates.TemplateResponse(
        "partials/notifications_panel.html",
        {"request": request, "notifications": notifications},
    )
