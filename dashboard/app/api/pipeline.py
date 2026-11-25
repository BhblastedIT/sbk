""



from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.task_utils import safe_create_task

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


async def _parse_body(request: Request) -> dict:
    ""
    content_type = request.headers.get("content-type", "")
    try:
        if "json" in content_type:
            return await request.json()
        form = await request.form()
        return dict(form)
    except Exception as e:

        raise HTTPException(status_code=400, detail=f"Malformed request body: {e}") from e


@router.post("/digest/refresh")
async def refresh_digest(request: Request):
    ""
    runner = request.app.state.runner
    job_id = await runner.run_script(
        source="digest",
        script_path="cross-source/xs-l3-digest-v2.py",
        stage="digest",
        extra_args=["--verbose"],
    )
    job = runner.get_job(job_id)
    return {"job_id": job_id, "status": job.status if job else "unknown"}


@router.get("/unified")
def get_unified(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_pipeline_unified()


@router.get("/grid")
def get_pipeline_grid(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_pipeline_grid()


def _get_allowed_grid_scripts(bridge) -> set[str]:
    ""
    try:
        grid = bridge.get_pipeline_grid()
    except Exception:
        return set()
    allowed: set[str] = set()
    for section in grid.get("pipeline", []):
        for row in section.get("rows", []):
            info = row.get("_run_info")
            if info and info.get("script"):
                allowed.add(info["script"])
        for sg in section.get("subgroups", []):
            for row in sg.get("rows", []):
                info = row.get("_run_info")
                if info and info.get("script"):
                    allowed.add(info["script"])
    return allowed


@router.post("/run-grid")
async def run_grid_script(request: Request):
    ""
    data = await _parse_body(request)
    script = data.get("script", "")
    args_str = data.get("args", "")
    if not script:
        raise HTTPException(status_code=400, detail="Missing 'script' parameter")

    bridge = request.app.state.bridge
    allowed = _get_allowed_grid_scripts(bridge)
    if allowed and script not in allowed:
        raise HTTPException(status_code=400, detail="Script not in pipeline grid allowlist")

    runner = request.app.state.runner
    extra_args = args_str.split() if args_str else []
    job_id = await runner.run_script(
        source="grid",
        script_path=script,
        stage="grid",
        extra_args=extra_args,
    )
    job = runner.get_job(job_id)
    return {"job_id": job_id, "status": job.status if job else "unknown"}


@router.get("/freshness")
def get_freshness(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_freshness_report()


@router.get("/sources")
def get_sources(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_source_config()


@router.get("/voice-memos")
def get_voice_memos(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_voice_memo_stats()


@router.post("/smart-run")
async def smart_pipeline_run(request: Request):
    ""



    runner = request.app.state.runner
    job_id = await runner.run_script(
        source="pipeline",
        script_path="cross-source/xs-pipeline-run.py",
        stage="smart-run",
        extra_args=["--propaga"],
    )
    job = runner.get_job(job_id)
    return {"job_id": job_id, "status": job.status if job else "unknown"}


@router.post("/full-rebuild")
async def full_pipeline_rebuild(request: Request):
    ""



    runner = request.app.state.runner
    job_id = await runner.run_script(
        source="pipeline",
        script_path="cross-source/xs-pipeline-run.py",
        stage="full-rebuild",
        extra_args=["--ricostruisci"],
    )
    job = runner.get_job(job_id)
    return {"job_id": job_id, "status": job.status if job else "unknown"}


def _argomenti_della_dashboard(source: str, stage: str, script_path: str) -> list[str] | None:
    ""





    from app.core.scheduler import _SCRIPT_DEFAULT_ARGS, _SENZA_COMANDO_DALLA_DASHBOARD

    if (source, stage) in _SENZA_COMANDO_DALLA_DASHBOARD:
        return None
    return list(_SCRIPT_DEFAULT_ARGS.get(script_path, []))


@router.post("/{source}/run")
async def run_pipeline(source: str, request: Request):
    ""
    data = await _parse_body(request)
    stage = data.get("stage", "l1")
    verbose = str(data.get("verbose", "false")).lower() in ("true", "1")

    bridge = request.app.state.bridge
    runner = request.app.state.runner


    source_cfg = None
    for cfg in await asyncio.to_thread(bridge.get_source_config):
        if cfg["id"] == source:
            source_cfg = cfg
            break

    if not source_cfg:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")


    scripts = source_cfg.get("scripts", {})
    stage_info = scripts.get(stage)

    if not stage_info or not stage_info.get("path"):
        raise HTTPException(status_code=400, detail=f"No {stage} script for source '{source}'")

    if not stage_info.get("exists"):
        raise HTTPException(status_code=404, detail=f"Script not found: {stage_info['path']}")

    argomenti = _argomenti_della_dashboard(source, stage, stage_info["path"])
    if argomenti is None:
        raise HTTPException(
            status_code=409,
            detail=f"{source} {stage}: downloaded by the L0 refresh (tools/cross-source/xs-l0-refresh.py), not by the dashboard",
        )
    extra_args = argomenti + (["--verbose"] if verbose else [])

    job_id = await runner.run_script(
        source=source,
        script_path=stage_info["path"],
        stage=stage,
        extra_args=extra_args,
    )

    job = runner.get_job(job_id)
    return {
        "job_id": job_id,
        "source": source,
        "stage": stage,
        "status": job.status if job else "unknown",
    }


@router.post("/{source}/run-full")
async def run_full_pipeline(source: str, request: Request):
    ""




    bridge = request.app.state.bridge
    runner = request.app.state.runner


    source_cfg = None
    for cfg in await asyncio.to_thread(bridge.get_source_config):
        if cfg["id"] == source:
            source_cfg = cfg
            break

    if not source_cfg:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")


    scripts = source_cfg.get("scripts", {})
    stage_order = ["l0", "l1", "l2", "l3"]
    stages = []
    for stage in stage_order:
        info = scripts.get(stage)
        if info and info.get("exists") and info.get("path"):
            argomenti = _argomenti_della_dashboard(source, stage, info["path"])
            if argomenti is None:
                continue
            stages.append({"stage": stage, "script_path": info["path"], "args": argomenti})

    if not stages:
        raise HTTPException(status_code=400, detail=f"No scripts available for source '{source}'")


    MONITOR_SYNC_SOURCES = {"slack", "email", "calendar"}
    needs_sync = source in MONITOR_SYNC_SOURCES

    if needs_sync:

        sync_job_id = await runner.run_script(
            source=f"monitor-{source}",
            script_path="monitoring/sbk-monitor.py",
            stage="sync",
            extra_args=["--once", source],
        )


        post_sync_stages = [s for s in stages if s["stage"] != "l0"]

        async def run_after_sync():

            sync_job = runner.get_job(sync_job_id)
            if sync_job:
                while sync_job.status == "running":
                    await asyncio.sleep(1)
                if sync_job.status != "completed":
                    return


            for stage_info in post_sync_stages:
                jid = await runner.run_script(
                    source=source,
                    script_path=stage_info["script_path"],
                    stage=stage_info["stage"],
                    extra_args=stage_info["args"],
                )
                j = runner.get_job(jid)
                if j:
                    while j.status == "running":
                        await asyncio.sleep(1)
                    if j.status != "completed":
                        break

        safe_create_task(run_after_sync(), name=f"pipeline-sync-{source}")

        return {
            "job_id": sync_job_id,
            "source": source,
            "stages": ["sync"] + [s["stage"] for s in post_sync_stages],
        }


    first_stage = stages[0]
    first_job_id = await runner.run_script(
        source=source,
        script_path=first_stage["script_path"],
        stage=first_stage["stage"],
        extra_args=first_stage["args"],
    )

    if len(stages) > 1:

        async def run_remaining():
            job = runner.get_job(first_job_id)
            if job:
                while job.status == "running":
                    await asyncio.sleep(1)
                if job.status != "completed":
                    return
            for stage_info in stages[1:]:
                jid = await runner.run_script(
                    source=source,
                    script_path=stage_info["script_path"],
                    stage=stage_info["stage"],
                    extra_args=stage_info["args"],
                )
                j = runner.get_job(jid)
                if j:
                    while j.status == "running":
                        await asyncio.sleep(1)
                    if j.status != "completed":
                        break

        safe_create_task(run_remaining(), name=f"pipeline-stages-{source}")

    return {
        "job_id": first_job_id,
        "source": source,
        "stages": [s["stage"] for s in stages],
        "status": "running",
    }


@router.get("/jobs")
def list_jobs(request: Request):
    ""
    runner = request.app.state.runner
    return runner.list_jobs()


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    ""
    runner = request.app.state.runner
    success = await runner.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot cancel job '{job_id}' (not running)")
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@router.get("/cascade")
def get_cascade_status(request: Request):
    ""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler or not scheduler._cascade:
        return {"cascade": None, "error": "Cascade monitor not initialized"}
    return scheduler._cascade.get_status()


@router.get("/scheduler")
def get_scheduler_status(request: Request):
    ""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    return scheduler.get_status()


@router.get("/dlq")
def pipeline_dlq_list(request: Request, include_resolved: bool = False):
    ""
    try:
        from pipeline_dlq import get_all_failures

        failures = get_all_failures(include_resolved=include_resolved)
        return JSONResponse({"failures": failures, "total": len(failures)})
    except Exception as e:
        log = logging.getLogger("dashboard.pipeline")
        log.warning("DLQ list failed: %s", e)
        return JSONResponse({"failures": [], "total": 0, "error": "Failed to load DLQ"})


@router.post("/dlq/resolve")
def pipeline_dlq_resolve(request: Request, id: str = ""):
    ""
    if not id:
        return JSONResponse({"error": "ID required"}, status_code=400)
    try:
        from pipeline_dlq import mark_resolved

        ok = mark_resolved(id)
        if ok:
            return JSONResponse({"ok": True, "resolved": id})
        return JSONResponse({"error": "Failure not found"}, status_code=404)
    except Exception as e:
        log = logging.getLogger("dashboard.pipeline")
        log.warning("DLQ resolve failed for %s: %s", id, e)
        return JSONResponse({"error": "Failed to resolve DLQ entry"}, status_code=500)
