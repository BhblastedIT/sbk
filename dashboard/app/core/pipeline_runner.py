""





from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.log_parser import parse_log_line, summarize_job
from app.core.task_utils import safe_create_task

log = logging.getLogger("dashboard.runner")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


_TOOLS_DIR = _PROJECT_ROOT / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import utc_now

_JOB_TIMEOUT_DEFAULT = 600
_MAX_JOBS = 50
_PRUNE_AGE = 86400


_JOB_TIMEOUTS: dict[str, int] = {
    "sl-l0-download": 1200,
    "sl-l0-download-dm": 1200,
    "em-l0-download": 900,
    "xs-pipeline-run": 1800,
    "xs-l3-extract": 1200,
    "xs-l3-index": 1200,
    "xs-l3-deep-extract": 1200,
    "xs-l2-merge": 900,
}


def _get_job_timeout(script_path: str) -> int:
    ""
    for pattern, timeout in _JOB_TIMEOUTS.items():
        if pattern in script_path:
            return timeout
    return _JOB_TIMEOUT_DEFAULT


@dataclass
class PipelineJob:
    ""

    job_id: str
    source: str
    script: str
    stage: str
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: str = "running"
    exit_code: int | None = None
    log_lines: list[str] = field(default_factory=list)
    parsed_lines: list[dict] = field(default_factory=list)
    summary: dict | None = None
    _process: asyncio.subprocess.Process | None = field(default=None, repr=False)


class PipelineRunner:
    ""

    def __init__(self, job_store=None):
        self._jobs: dict[str, PipelineJob] = {}
        self._job_store = job_store

    def _is_source_running(self, source: str, stage: str) -> bool:
        ""
        for job in self._jobs.values():
            if job.source == source and job.stage == stage and job.status == "running":
                return True
        return False

    async def run_script(
        self,
        source: str,
        script_path: str,
        stage: str,
        extra_args: list[str] | None = None,
    ) -> str:
        ""




        if self._is_source_running(source, stage):
            job_id = uuid.uuid4().hex[:12]
            job = PipelineJob(
                job_id=job_id,
                source=source,
                script=script_path,
                stage=stage,
                status="failed",
            )
            job.log_lines.append(f"Already running: {source}/{stage}")
            job.finished_at = utc_now()
            self._jobs[job_id] = job
            return job_id

        job_id = uuid.uuid4().hex[:12]
        full_path = _PROJECT_ROOT / "tools" / script_path


        resolved = full_path.resolve()
        tools_base = (_PROJECT_ROOT / "tools").resolve()
        if not str(resolved).startswith(str(tools_base) + "/") and resolved != tools_base:
            job = PipelineJob(
                job_id=job_id,
                source=source,
                script=script_path,
                stage=stage,
                status="failed",
            )
            job.log_lines.append(f"Path traversal blocked: {script_path}")
            job.finished_at = utc_now()
            self._jobs[job_id] = job
            return job_id

        if not full_path.exists():
            job = PipelineJob(
                job_id=job_id,
                source=source,
                script=script_path,
                stage=stage,
                status="failed",
            )
            job.log_lines.append(f"Script not found: {full_path}")
            job.finished_at = utc_now()
            self._jobs[job_id] = job
            return job_id

        job = PipelineJob(
            job_id=job_id,
            source=source,
            script=script_path,
            stage=stage,
        )
        self._jobs[job_id] = job

        cmd = [sys.executable, str(full_path)]
        if extra_args:
            cmd.extend(extra_args)

        log.info(f"[{job_id}] Starting: {' '.join(cmd)}")

        safe_create_task(self._execute(job, cmd), name=f"run-{job.job_id}")
        self._prune_old_jobs()
        return job_id

    async def _execute(self, job: PipelineJob, cmd: list[str]):
        ""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
            )
            job._process = process

            async def read_output():
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    job.log_lines.append(decoded)
                    job.parsed_lines.append(parse_log_line(decoded))

            job_timeout = _get_job_timeout(job.script)
            try:
                await asyncio.wait_for(read_output(), timeout=job_timeout)
                await process.wait()
            except TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    log.warning("Process %s did not die after kill", process.pid)
                job.status = "timeout"
                job.exit_code = -2
                timeout_line = f"Job timed out after {job_timeout}s"
                job.log_lines.append(timeout_line)
                job.parsed_lines.append(parse_log_line(timeout_line))
                job.finished_at = utc_now()
                log.warning(f"[{job.job_id}] Timeout after {job_timeout}s")
                self._finalize_job(job)
                return

            job.exit_code = process.returncode
            job.status = "completed" if process.returncode == 0 else "failed"
            job.finished_at = utc_now()
            log.info(f"[{job.job_id}] Finished: status={job.status}, exit_code={job.exit_code}")

        except Exception as e:
            job.status = "failed"
            err_line = f"Execution error: {e}"
            job.log_lines.append(err_line)
            job.parsed_lines.append(parse_log_line(err_line))
            job.finished_at = utc_now()
            log.error(f"[{job.job_id}] Error: {e}")
        finally:
            job._process = None
            self._finalize_job(job)

    def _finalize_job(self, job: PipelineJob):
        ""
        if job.summary is not None:
            return
        job.summary = summarize_job(job.parsed_lines)

        delta = (job.finished_at - job.started_at) if job.finished_at else None
        duration_s = delta.total_seconds() if delta else 0

        if self._job_store:
            secs = int(duration_s)
            duration = f"{secs}s" if secs < 60 else f"{secs // 60}m {secs % 60}s"
            self._job_store.add_job(
                {
                    "job_id": job.job_id,
                    "source": job.source,
                    "script": job.script,
                    "stage": job.stage,
                    "status": job.status,
                    "exit_code": job.exit_code,
                    "started_at": job.started_at.isoformat(),
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "duration": duration,
                    "summary": job.summary,
                    "log_lines": job.log_lines,
                }
            )


        try:
            from monitoring.pipeline_metrics import log_pipeline_run

            log_pipeline_run(
                script=job.script,
                stage=job.stage,
                source=job.source,
                status=job.status,
                duration_s=duration_s,
                exit_code=job.exit_code,
                caller="dashboard",
            )
        except Exception:
            pass

    async def cancel_job(self, job_id: str) -> bool:
        ""
        job = self._jobs.get(job_id)
        if not job or job.status != "running":
            return False
        if job._process and job._process.returncode is None:
            job._process.terminate()
            await asyncio.sleep(0.5)
            if job._process.returncode is None:
                job._process.kill()
        job.status = "cancelled"
        job.finished_at = utc_now()
        job.exit_code = -1
        cancel_line = "Job cancelled by user"
        job.log_lines.append(cancel_line)
        job.parsed_lines.append(parse_log_line(cancel_line))
        self._finalize_job(job)
        log.info(f"[{job.job_id}] Cancelled")
        return True

    async def run_sequence(
        self,
        source: str,
        stages: list[dict],
    ) -> list[str]:
        ""





        job_ids = []
        for stage_info in stages:
            job_id = await self.run_script(
                source=source,
                script_path=stage_info["script_path"],
                stage=stage_info["stage"],
            )
            job_ids.append(job_id)


            job = self.get_job(job_id)
            if job:
                while job.status == "running":
                    await asyncio.sleep(1)

                if job.status != "completed":
                    break

        return job_ids

    def _prune_old_jobs(self):
        ""
        now = utc_now()
        to_remove = []
        completed = [
            (jid, j)
            for jid, j in self._jobs.items()
            if j.status in ("completed", "failed", "cancelled", "timeout") and j.finished_at
        ]

        for jid, j in completed:
            if (now - j.finished_at).total_seconds() > _PRUNE_AGE:
                to_remove.append(jid)

        if len(self._jobs) - len(to_remove) > _MAX_JOBS:
            remaining = [(jid, j) for jid, j in completed if jid not in to_remove]
            remaining.sort(key=lambda x: x[1].finished_at)
            excess = len(self._jobs) - len(to_remove) - _MAX_JOBS
            for jid, _ in remaining[:excess]:
                to_remove.append(jid)
        for jid in to_remove:
            del self._jobs[jid]

    def get_job(self, job_id: str) -> PipelineJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        ""
        result = []
        for job in sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True):
            duration = ""
            if job.finished_at:
                delta = job.finished_at - job.started_at
                secs = int(delta.total_seconds())
                if secs < 60:
                    duration = f"{secs}s"
                else:
                    duration = f"{secs // 60}m {secs % 60}s"
            elif job.status == "running":
                delta = utc_now() - job.started_at
                secs = int(delta.total_seconds())
                duration = f"{secs}s..."

            summary = job.summary or {}
            result.append(
                {
                    "job_id": job.job_id,
                    "source": job.source,
                    "script": job.script,
                    "stage": job.stage,
                    "started_at": job.started_at.strftime("%H:%M:%S"),
                    "finished_at": job.finished_at.strftime("%H:%M:%S")
                    if job.finished_at
                    else None,
                    "status": job.status,
                    "exit_code": job.exit_code,
                    "duration": duration,
                    "log_line_count": len(job.log_lines),
                    "error_count": summary.get("error_count", 0),
                    "warning_count": summary.get("warning_count", 0),
                    "total_rows": summary.get("metrics", {}).get("rows", 0),
                    "stored": False,
                }
            )
        return result
