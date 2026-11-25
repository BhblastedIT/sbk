""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/status")
def monitor_status(request: Request):
    bridge = request.app.state.bridge
    status = bridge.get_monitor_status()
    return JSONResponse(status)


@router.post("/trigger/{source}")
async def trigger_sync(source: str, request: Request):
    ""
    runner = request.app.state.runner


    valid_sources = {"slack", "email", "calendar", "digest", "brief", "all"}
    if source not in valid_sources:
        return JSONResponse(
            {
                "error": f"Source '{source}' not supported. Valid: {', '.join(sorted(valid_sources))}"
            },
            status_code=400,
        )

    job_id = await runner.run_script(
        source=f"monitor-{source}",
        script_path="monitoring/sbk-monitor.py",
        stage="sync",
        extra_args=["--once", source],
    )

    job = runner.get_job(job_id)
    return {
        "job_id": job_id,
        "source": source,
        "status": job.status if job else "unknown",
    }
