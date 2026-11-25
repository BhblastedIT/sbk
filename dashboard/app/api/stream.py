""



from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/stream", tags=["stream"])

_STREAM_TIMEOUT = 660


@router.get("/pipeline/{job_id}")
async def stream_pipeline_log(job_id: str, request: Request):
    ""
    runner = request.app.state.runner


    job = runner.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    async def event_generator():
        last_idx = 0
        elapsed = 0

        while elapsed < _STREAM_TIMEOUT:
            if await request.is_disconnected():
                break

            job = runner.get_job(job_id)
            if not job:
                yield {"event": "error", "data": json.dumps({"error": "Job not found"})}
                break


            new_parsed = job.parsed_lines[last_idx:]
            for pl in new_parsed:
                yield {
                    "event": "log",
                    "data": json.dumps(
                        {
                            "line": pl["line"],
                            "severity": pl["severity"],
                            "message": pl["message"],
                            "timestamp": pl["timestamp"],
                            "metrics": pl["metrics"],
                            "is_stage_header": pl["is_stage_header"],
                            "stage_name": pl["stage_name"],
                            "status": job.status,
                        }
                    ),
                }
            last_idx = len(job.parsed_lines)


            if job.status in ("completed", "failed", "cancelled", "timeout"):
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "status": job.status,
                            "exit_code": job.exit_code,
                            "summary": job.summary,
                        }
                    ),
                }
                break

            await asyncio.sleep(0.3)
            elapsed += 0.3


        if elapsed >= _STREAM_TIMEOUT:
            yield {
                "event": "done",
                "data": json.dumps({"status": "timeout", "exit_code": -2}),
            }

    return EventSourceResponse(event_generator())
