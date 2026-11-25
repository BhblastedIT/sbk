""



from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.scheduler import (
    RECOMMENDED_INTERVALS,
    SCHEDULE_OPTIONS,
    VALID_INTERVALS,
    load_schedule_config,
    save_schedule_config,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ScheduleUpdate(BaseModel):
    source: str
    stage: str
    interval_min: int


@router.get("/schedules")
def get_schedules(request: Request):
    ""
    return load_schedule_config()


@router.get("/schedule-options")
def get_schedule_options():
    ""
    return SCHEDULE_OPTIONS


@router.post("/schedule")
def update_schedule(body: ScheduleUpdate, request: Request):
    ""

    if body.interval_min not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval: {body.interval_min}")

    config = load_schedule_config()

    if body.source not in config:
        config[body.source] = {"schedules": {}, "recommended": ""}

    config[body.source]["schedules"][body.stage] = body.interval_min
    save_schedule_config(config)


    return {
        "ok": True,
        "source": body.source,
        "stage": body.stage,
        "interval_min": body.interval_min,
    }


@router.post("/apply-recommended")
def apply_recommended(request: Request):
    ""
    config = load_schedule_config()

    applied = 0
    for source_id, stages in RECOMMENDED_INTERVALS.items():
        if source_id not in config:
            config[source_id] = {"schedules": {}, "recommended": ""}
        for stage, interval in stages.items():
            config[source_id]["schedules"][stage] = interval
            applied += 1

    save_schedule_config(config)
    return {"ok": True, "applied": applied}


@router.get("/scheduler-status")
def scheduler_status(request: Request):
    ""
    scheduler = request.app.state.scheduler
    return scheduler.get_status()


@router.post("/scheduler/start")
def start_scheduler(request: Request):
    ""
    scheduler = request.app.state.scheduler
    scheduler.start()
    return {"ok": True, "status": "running"}


@router.post("/scheduler/stop")
def stop_scheduler(request: Request):
    ""
    scheduler = request.app.state.scheduler
    scheduler.stop()
    return {"ok": True, "status": "stopped"}





@router.get("/all")
def get_all_settings(request: Request):
    ""
    store = request.app.state.settings_store
    return store.all_settings()


@router.get("/section/{section}")
def get_settings_section(section: str, request: Request):
    ""
    store = request.app.state.settings_store
    data = store.get_section(section)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    return {"section": section, "data": data}


@router.post("/section/{section}")
async def update_settings_section(section: str, request: Request):
    ""
    store = request.app.state.settings_store
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    ok = store.set(section, body)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    return {"ok": True, "section": section}


@router.post("/reset/{section}")
def reset_settings_section(section: str, request: Request):
    ""
    store = request.app.state.settings_store
    ok = store.reset_section(section)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    return {"ok": True, "section": section, "data": store.get_section(section)}
