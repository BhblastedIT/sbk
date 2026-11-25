""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

from sbk_config import EVENTS_DIR

log = logging.getLogger("dashboard.events")
router = APIRouter(prefix="/api/events", tags=["events"])

_EVENTS_DIR = EVENTS_DIR


@router.get("/recent")
def get_recent_events(limit: int = Query(default=50, ge=1, le=500)):
    ""
    if not _EVENTS_DIR.exists():
        return {"events": [], "total": 0}

    events = []
    for f in sorted(_EVENTS_DIR.glob("*.json"), reverse=True):
        if len(events) >= limit:
            break
        try:
            data = json.loads(f.read_text())
            events.append(
                {
                    "source": data.get("source", "?"),
                    "stage": data.get("stage", "?"),
                    "ts": data.get("ts", ""),
                    "processed": data.get("processed", False),
                    "processed_status": data.get("processed_status", ""),
                    "processed_at": data.get("processed_at", ""),
                    "trigger": data.get("trigger", ""),
                    "account": data.get("account", ""),
                    "rows": data.get("rows", ""),
                    "filename": f.name,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    return {"events": events, "total": len(events)}
