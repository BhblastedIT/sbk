""











from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.task_utils import safe_create_task
from sbk_config import (
    CASCADE_DEBOUNCE,
    CASCADE_RULES,
    DATA_ROOT,
    calendar_labels,
    mail_labels,
    utc_now,
)

_CASCADE_STATE_FILE = DATA_ROOT / "cascade-state.json"
_CASCADE_FAILURES_FILE = DATA_ROOT / "cascade-failures.jsonl"

log = logging.getLogger("dashboard.cascade")







@dataclass
class VerificationResult:
    passed: bool
    source: str
    reason: str = ""
    file_count: int = 0
    newest_file_age_min: float = -1







_VERIFICATION_RULES: dict[str, dict] = {
    "email": {
        # your mailboxes, read at check time (sbk_config.mail_labels)
        "dirs": lambda: [f"emails/{label}" for label in mail_labels()],
        "file": "messages.parquet",
        "check": "any_parquet_fresh",
        "max_age_hours": 4,
    },
    "slack": {
        "dir": "slack/conversations",
        "pattern": "*.json",
        "min_files": 50,
        "max_age_hours": 2,
    },
    "slack-dm": {
        "dir": "slack/conversations",
        "pattern": "*.json",
        "min_files": 10,
        "max_age_hours": 1,
    },
    "attio": {
        "dir": "attio",
        "file": "people.parquet",
        "max_age_hours": 6,
    },
    "calendar": {
        # your calendar accounts, read at check time (sbk_config.calendar_labels)
        "dirs": lambda: [f"calendars/{label}" for label in calendar_labels()],
        "file": "events.parquet",
        "check": "any_parquet_fresh",
        "max_age_hours": 2,
    },
    "notion": {
        "dir": "notion/pages",
        "pattern": "*.json",
        "min_files": 10,
        "max_age_hours": 48,
    },
    "gdrive": {
        "dir": "gdrive",
        "file": "gdrive-index.json",
        "max_age_hours": 48,
    },
    "linkedin": {
        "dir": "linkedin/processed",
        "pattern": "*.parquet",
        "min_files": 1,
        "max_age_hours": 168,
    },
    "personio": {
        "dir": "personio",
        "file": "employees-raw.json",
        "max_age_hours": 168,
    },
}


def _file_age_minutes(path: Path) -> float:
    ""
    if not path.exists():
        return float("inf")
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)
    return (utc_now() - mtime).total_seconds() / 60


def _newest_in_dir(directory: Path, pattern: str = "*") -> tuple[int, float]:
    ""
    if not directory.exists():
        return 0, float("inf")
    files = list(directory.glob(pattern))
    if not files:
        return 0, float("inf")
    newest_mtime = max(os.path.getmtime(f) for f in files if f.is_file())
    age_min = (utc_now() - datetime.fromtimestamp(newest_mtime, tz=UTC)).total_seconds() / 60
    return len(files), age_min


def verify_l0(source: str) -> VerificationResult:
    ""
    rule = _VERIFICATION_RULES.get(source)
    if rule is None:

        return VerificationResult(passed=True, source=source, reason="no_rule")

    max_age_min = rule.get("max_age_hours", 24) * 60


    if rule.get("check") == "any_parquet_fresh":
        dirs = rule.get("dirs", [])
        if callable(dirs):
            dirs = dirs()
        fname = rule.get("file", "")
        any_fresh = False
        total_found = 0
        best_age = float("inf")
        for d in dirs:
            p = DATA_ROOT / d / fname
            if p.exists():
                total_found += 1
                age = _file_age_minutes(p)
                best_age = min(best_age, age)
                if age <= max_age_min:
                    any_fresh = True
        if total_found == 0:
            return VerificationResult(
                passed=False,
                source=source,
                reason=f"no {fname} found in any of {len(dirs)} dirs",
            )
        if not any_fresh:
            return VerificationResult(
                passed=False,
                source=source,
                reason=f"all {fname} older than {rule.get('max_age_hours')}h (best: {best_age:.0f}min)",
                file_count=total_found,
                newest_file_age_min=best_age,
            )
        return VerificationResult(
            passed=True,
            source=source,
            reason="ok",
            file_count=total_found,
            newest_file_age_min=best_age,
        )


    if "file" in rule:
        base_dir = DATA_ROOT / rule.get("dir", source)
        path = base_dir / rule["file"]
        if not path.exists():
            return VerificationResult(
                passed=False,
                source=source,
                reason=f"file missing: {path.name}",
            )
        age = _file_age_minutes(path)
        if age > max_age_min:
            return VerificationResult(
                passed=False,
                source=source,
                reason=f"{path.name} is {age:.0f}min old (max {max_age_min:.0f}min)",
                file_count=1,
                newest_file_age_min=age,
            )
        return VerificationResult(
            passed=True,
            source=source,
            reason="ok",
            file_count=1,
            newest_file_age_min=age,
        )


    base_dir = DATA_ROOT / rule["dir"]
    pattern = rule.get("pattern", "*")
    min_files = rule.get("min_files", 1)
    count, newest_age = _newest_in_dir(base_dir, pattern)
    if count < min_files:
        return VerificationResult(
            passed=False,
            source=source,
            reason=f"only {count} files (need {min_files})",
            file_count=count,
            newest_file_age_min=newest_age,
        )
    if newest_age > max_age_min:
        return VerificationResult(
            passed=False,
            source=source,
            reason=f"newest file is {newest_age:.0f}min old (max {max_age_min:.0f}min)",
            file_count=count,
            newest_file_age_min=newest_age,
        )
    return VerificationResult(
        passed=True,
        source=source,
        reason="ok",
        file_count=count,
        newest_file_age_min=newest_age,
    )







class CascadeMonitor:
    ""

    def __init__(self, runner):
        self._runner = runner
        self._cascade_active: dict[str, bool] = {}
        self._last_l2_trigger: datetime | None = None
        self._l2_debounce_sec = CASCADE_DEBOUNCE.get("default", 300)
        self._cascade_log: list[dict] = []
        self._load_state()
        self.prune_old_failures()

    def _load_state(self):
        ""
        if not _CASCADE_STATE_FILE.exists():
            return
        try:
            data = json.loads(_CASCADE_STATE_FILE.read_text())
            if data.get("last_l2_trigger"):
                _dt = datetime.fromisoformat(data["last_l2_trigger"])


                self._last_l2_trigger = _dt if _dt.tzinfo else _dt.replace(tzinfo=UTC)
            self._cascade_log = data.get("cascade_log", [])[-100:]
            log.info(f"Loaded cascade state ({len(self._cascade_log)} log entries)")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.warning(f"Failed to load cascade state: {e}")

    def _save_state(self):
        ""
        data = {
            "last_l2_trigger": self._last_l2_trigger.isoformat() if self._last_l2_trigger else None,
            "cascade_log": self._cascade_log[-100:],
        }
        try:
            _CASCADE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CASCADE_STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except OSError as e:
            log.warning(f"Failed to save cascade state: {e}")

    def _log_failure(self, source: str, stage: str, action: str, detail: str):
        ""
        entry = {
            "ts": datetime.now().isoformat()[:19],
            "source": source,
            "stage": stage,
            "action": action,
            "detail": detail,
        }
        try:
            _CASCADE_FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_CASCADE_FAILURES_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning(f"Failed to write cascade failure log: {e}")

    async def on_job_complete(self, source: str, stage: str, job_status: str, job_id: str):
        ""





        if job_status != "completed":
            log.info(f"[cascade] Skip: {source}/{stage} status={job_status}")
            return

        if stage == "l0":
            await self._handle_l0_complete(source, job_id)
        elif stage == "l1":
            await self._handle_l1_complete(source, job_id)

    async def _handle_l0_complete(self, source: str, job_id: str):
        ""

        result = verify_l0(source)
        log.info(
            f"[cascade] L0 verify {source}: "
            f"{'PASS' if result.passed else 'FAIL'} "
            f"({result.reason}, files={result.file_count})"
        )

        self._cascade_log.append(
            {
                "ts": datetime.now().isoformat()[:19],
                "source": source,
                "action": "verify_l0",
                "passed": result.passed,
                "detail": result.reason,
            }
        )

        self._save_state()

        if not result.passed:
            log.warning(f"[cascade] L0 verification failed for {source}, skipping cascade")
            self._log_failure(source, "l0", "verify_failed", result.reason)
            return


        cascade_target = CASCADE_RULES.get((source, "l0"))
        if not cascade_target:
            log.info(f"[cascade] No cascade rule for ({source}, l0)")
            return


        parts = cascade_target.split()
        script_path = parts[0]
        extra_args = parts[1:] if len(parts) > 1 else None


        if self._runner._is_source_running(source, "l1"):
            log.info(f"[cascade] {source}/l1 already running, skipping")
            return

        log.info(f"[cascade] Triggering L1: {script_path} {' '.join(extra_args or [])}")
        l1_job_id = await self._runner.run_script(
            source=source,
            script_path=script_path,
            stage="l1",
            extra_args=extra_args,
        )

        self._cascade_log.append(
            {
                "ts": datetime.now().isoformat()[:19],
                "source": source,
                "action": "trigger_l1",
                "job_id": l1_job_id,
                "script": script_path,
            }
        )

        self._save_state()


        safe_create_task(
            self._wait_and_handle_l1(source, l1_job_id),
            name=f"cascade-l1-{source}-{l1_job_id[:8]}",
        )

    async def _wait_and_handle_l1(self, source: str, job_id: str):
        ""
        for _ in range(700):
            await asyncio.sleep(1)
            job = self._runner.get_job(job_id)
            if not job or job.status != "running":
                break

        job = self._runner.get_job(job_id)
        if job and job.status == "completed":
            await self._handle_l1_complete(source, job_id)
        else:
            status = job.status if job else "unknown"
            log.warning(f"[cascade] L1 {source} did not complete (status={status})")
            self._log_failure(source, "l1", "cascade_failed", f"L1 status={status}")

    async def _handle_l1_complete(self, source: str, job_id: str):
        ""




        now = utc_now()
        debounce = CASCADE_DEBOUNCE.get(source, self._l2_debounce_sec)


        if self._last_l2_trigger and (now - self._last_l2_trigger).total_seconds() < debounce:
            elapsed = (now - self._last_l2_trigger).total_seconds()
            log.info(f"[cascade] L2/L3 debounced for {source} ({elapsed:.0f}s < {debounce}s)")
            return


        if self._runner._is_source_running("cross-source", "l2"):
            log.info("[cascade] cross-source/l2 already running, skipping L2/L3")
            return

        self._last_l2_trigger = now

        log.info(f"[cascade] Triggering L2/L3 pipeline (source trigger: {source})")
        pipeline_job_id = await self._runner.run_script(
            source="cross-source",
            script_path="cross-source/xs-pipeline-run.py",
            stage="l2",
            extra_args=["--propaga"],
        )

        self._cascade_log.append(
            {
                "ts": now.isoformat()[:19],
                "source": source,
                "action": "trigger_l2l3",
                "job_id": pipeline_job_id,
            }
        )
        self._save_state()

    def prune_old_failures(self, days: int = 30):
        ""
        if not _CASCADE_FAILURES_FILE.exists():
            return
        try:
            cutoff = (utc_now() - timedelta(days=days)).isoformat()[:19]
            lines = _CASCADE_FAILURES_FILE.read_text().strip().split("\n")
            keep, archive = [], []
            for line in lines:
                if not line.strip():
                    continue
                entry = json.loads(line)
                (keep if entry.get("ts", "") >= cutoff else archive).append(line)
            if archive:
                archive_file = _CASCADE_FAILURES_FILE.with_name("cascade-failures-archive.jsonl")
                with open(archive_file, "a") as f:
                    f.write("\n".join(archive) + "\n")
                _CASCADE_FAILURES_FILE.write_text("\n".join(keep) + "\n" if keep else "")
                log.info(
                    f"[cascade] Pruned {len(archive)} old failures "
                    f"(kept {len(keep)}, archived {len(archive)})"
                )
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"Failed to prune cascade failures: {e}")

    def get_recent_failures(self, limit: int = 20) -> list[dict]:
        ""
        if not _CASCADE_FAILURES_FILE.exists():
            return []
        try:
            lines = _CASCADE_FAILURES_FILE.read_text().strip().split("\n")
            failures = []
            for line in lines[-limit:]:
                if line.strip():
                    failures.append(json.loads(line))
            return failures
        except (OSError, json.JSONDecodeError):
            return []

    def get_status(self) -> dict:
        ""
        return {
            "last_l2_trigger": self._last_l2_trigger.isoformat() if self._last_l2_trigger else None,
            "recent_actions": self._cascade_log[-20:],
            "recent_failures": self.get_recent_failures(10),
        }
