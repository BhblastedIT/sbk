""






from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from sbk_config import DATA_ROOT

log = logging.getLogger("dashboard.job-store")

_MAX_HISTORY = 100
_DEFAULT_PATH = DATA_ROOT / "pipeline-jobs.json"


class JobStore:
    ""

    def __init__(self, path: Path | None = None):
        self._path = path or _DEFAULT_PATH
        self._jobs: list[dict] = []
        self._load()

    def _load(self):
        ""
        if not self._path.exists():
            self._jobs = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._jobs = data[-_MAX_HISTORY:]
            else:
                log.warning("Invalid job store format, resetting")
                self._jobs = []
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load job store: %s", e)
            self._jobs = []

    def _save(self):
        ""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._jobs, f, ensure_ascii=False, indent=1)
            os.replace(tmp_path, str(self._path))
        except OSError as e:
            log.error("Failed to save job store: %s", e)

            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def add_job(self, job_data: dict):
        ""





        self._jobs.append(job_data)

        if len(self._jobs) > _MAX_HISTORY:
            self._jobs = self._jobs[-_MAX_HISTORY:]
        self._save()

    def get_jobs(self, limit: int = 50) -> list[dict]:
        ""
        result = []
        for job in reversed(self._jobs[-limit:]):
            entry = {k: v for k, v in job.items() if k != "log_lines"}
            result.append(entry)
        return result

    def get_job(self, job_id: str) -> dict | None:
        ""
        for job in self._jobs:
            if job.get("job_id") == job_id:
                return job
        return None
