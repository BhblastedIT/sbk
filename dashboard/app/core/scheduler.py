""







from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.task_utils import safe_create_task
from sbk_config import (
    DATA_ROOT,
    automatic_cascades_on,
    source_listed,
    to_utc_aware,
    utc_now,
)

if TYPE_CHECKING:
    from app.core.cascade_monitor import CascadeMonitor

log = logging.getLogger("dashboard.scheduler")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEDULE_CONFIG_FILE = DATA_ROOT / "pipeline-schedule.json"
_LAST_RUN_FILE = DATA_ROOT / "scheduler-last-run.json"


SCHEDULE_OPTIONS = [
    {"value": 0, "label": "Disabled"},
    {"value": 5, "label": "Every 5 min"},
    {"value": 15, "label": "Every 15 min"},
    {"value": 30, "label": "Every 30 min"},
    {"value": 60, "label": "Every hour"},
    {"value": 120, "label": "Every 2 hours"},
    {"value": 360, "label": "Every 6 hours"},
    {"value": 720, "label": "Every 12 hours"},
    {"value": 1440, "label": "Every day"},
    {"value": 10080, "label": "Every week"},
]

VALID_INTERVALS = {opt["value"] for opt in SCHEDULE_OPTIONS}



_DEFAULT_ACTIVE_HOURS = (6, 23)


_MAX_RETRIES = 2
_RETRY_BACKOFF_SEC = 60





_INCREMENTAL_SCRIPTS: set[str] = {

    "attio/at-l0-download.py",
    "notion/no-l0-download.py",
    "personio/pe-l0-download.py",

    "email/em-l1-enrich.py",
    "slack/sl-l1-enrich.py",
    "attio/at-l1-enrich.py",
    "gdrive/gd-l1-enrich.py",
    "linkedin/li-l1-enrich.py",
    "calendar/ca-l1-extract.py",
    "plaud/pl-l1-enrich.py",
    "whatsapp/wa-l1-enrich.py",
    "chatgpt/cg-l1-enrich.py",
}


_SCRIPT_DEFAULT_ARGS: dict[str, list[str]] = {
    "gdrive/gd-l0-download.py": ["--mode", "recent", "--days", "7"],
}


_MONITOR_SYNCED_SOURCES: set[str] = {"email", "slack", "calendar"}




_SENZA_COMANDO_DALLA_DASHBOARD: set[tuple[str, str]] = {
    ("email", "l0"),

    ("docusign", "l0"),
}


DEFAULT_SCHEDULES: dict[str, dict] = {
    "email": {"l0": 0, "l1": 0, "recommended": "Recommended: L0 every 30 min (monitor already active)"},
    "attio": {"l1": 0, "recommended": "Recommended: L1 daily"},
    "slack": {"l1": 0, "recommended": "Recommended: L1 every hour"},
    "slack-dm": {"l0": 0, "recommended": "Recommended: L0 every 5 min"},
    "whatsapp": {"l1": 0, "recommended": "Manual only (chat export from your phone)"},
    "linkedin": {"l0": 0, "l1": 0, "recommended": "Manual only (your LinkedIn data export)"},
    "plaud": {
        "l0": 0,
        "l1": 0,
        "recommended": "Manual only (Plaud desktop app session; L0 needs \"plaud\" in enabled_sources)",
    },
    "tactiq": {
        "l0": 0,
        "l1": 0,
        "recommended": "L0 weekly (Tactiq web app session in Chrome; needs \"tactiq\" in enabled_sources)",
    },
    "notion": {"l0": 0, "l1": 0, "recommended": "Recommended: L0 daily"},
    "chatgpt": {"l1": 0, "recommended": "Manual only (JSON export)"},
    "gdrive": {"l0": 0, "l1": 0, "recommended": "Recommended: L0 daily"},
    "docusign": {"l0": 0, "l1": 0, "recommended": "Manual only (DocuSign API, ds-l0-api.py)"},
    "personio": {"l1": 0, "recommended": "Recommended: L1 weekly"},
    "voicememos": {"l0": 0, "l1": 0, "recommended": "Manual only"},
    "calendar": {"l0": 0, "recommended": "Recommended: L0 daily"},
    "cross-source": {"l2": 0, "l3": 0, "recommended": "Manual after L1 batch"},
    "monitoring": {"l0": 0, "recommended": "Managed by launchd (sbk-monitor)"},
    "briefing": {"l3": 0, "recommended": "Recommended: L3 daily"},
}


RECOMMENDED_INTERVALS: dict[str, dict[str, int]] = {
    "email": {"l0": 5, "l1": 15},
    "attio": {"l1": 1440},
    "slack": {"l0": 15, "l1": 15},
    "slack-dm": {"l0": 5},
    "tactiq": {"l0": 10080},
    "notion": {"l0": 1440, "l1": 1440},
    "gdrive": {"l0": 1440, "l1": 1440},
    "personio": {"l0": 10080, "l1": 10080},
    "calendar": {"l0": 15},
    "briefing": {"l3": 1440},
}


def load_schedule_config() -> dict:
    ""
    if SCHEDULE_CONFIG_FILE.exists():
        try:
            return json.loads(SCHEDULE_CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load schedule config: {e}, using defaults")


    config = {}
    for source_id, defaults in DEFAULT_SCHEDULES.items():
        config[source_id] = {
            "schedules": {k: v for k, v in defaults.items() if k != "recommended"},
            "recommended": defaults.get("recommended", ""),
        }
    save_schedule_config(config)
    return config


def save_schedule_config(config: dict) -> None:
    ""
    SCHEDULE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    log.info(f"Schedule config saved to {SCHEDULE_CONFIG_FILE}")


def get_schedule_for_display(source_config: list[dict]) -> list[dict]:
    ""
    config = load_schedule_config()
    result = []

    for src in source_config:
        sid = src["id"]
        src_schedule = config.get(sid, {})
        schedules = src_schedule.get("schedules", {})
        recommended = src_schedule.get(
            "recommended", DEFAULT_SCHEDULES.get(sid, {}).get("recommended", "")
        )


        stages = []
        for stage, info in src.get("scripts", {}).items():
            if info.get("exists"):
                current_minutes = schedules.get(stage, 0)
                stages.append(
                    {
                        "stage": stage,
                        "current_minutes": current_minutes,
                        "current_label": _minutes_to_label(current_minutes),
                    }
                )

        result.append(
            {
                "id": sid,
                "name": src["name"],
                "method": src.get("method", "manual"),
                "recommended": recommended,
                "stages": stages,
            }
        )

    return result


def _minutes_to_label(minutes: int) -> str:
    ""
    for opt in SCHEDULE_OPTIONS:
        if opt["value"] == minutes:
            return opt["label"]
    return f"Every {minutes} min"


_STATUS_REGEN_SCRIPT = "cross-source/xs-util-pipeline-status.py"
_STATUS_REGEN_DEBOUNCE_SEC = 300





# Automatic cascades off (sb-pipeline-ctl.py off) = the scheduler starts nothing either.
def _cascades_off() -> bool:
    return not automatic_cascades_on()


# L0 downloads that read a login session of an app or a browser on this Mac: the scheduler
# starts them only when their source is written in enabled_sources (sbk.config.json).
_L0_SESSIONE = frozenset({"plaud", "tactiq"})


class AutoScheduler:
    ""

    def __init__(self, runner):
        self._runner = runner
        self._task: asyncio.Task | None = None
        self._last_run: dict[str, dict[str, datetime]] = {}
        self._last_error: dict[str, dict[str, str]] = {}
        self._retry_count: dict[str, int] = {}
        self._cascade: CascadeMonitor | None = None
        self._last_status_regen: datetime | None = None
        self._load_last_run()
        self._init_cascade()

    def _init_cascade(self):
        ""
        try:
            from app.core.cascade_monitor import CascadeMonitor

            self._cascade = CascadeMonitor(self._runner)
            log.info("CascadeMonitor initialized")
        except Exception as e:
            log.warning(f"CascadeMonitor init failed (cascade disabled): {e}")
            self._cascade = None

    def _load_last_run(self):
        ""
        if not _LAST_RUN_FILE.exists():
            return
        try:
            data = json.loads(_LAST_RUN_FILE.read_text())
            for src, stages in data.items():
                self._last_run[src] = {}
                for st, ts in stages.items():
                    self._last_run[src][st] = datetime.fromisoformat(ts)
            log.info(f"Loaded {sum(len(v) for v in self._last_run.values())} last_run timestamps")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.warning(f"Failed to load last_run: {e}")

    def _save_last_run(self):
        ""
        data = {}
        for src, stages in self._last_run.items():
            data[src] = {st: ts.isoformat() for st, ts in stages.items()}
        try:
            _LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
            _LAST_RUN_FILE.write_text(json.dumps(data, indent=2))
        except OSError as e:
            log.warning(f"Failed to save last_run: {e}")

    def start(self):
        ""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            log.info("AutoScheduler started")

    def stop(self):
        ""
        if self._task and not self._task.done():
            self._task.cancel()
            log.info("AutoScheduler stopped")

    async def _loop(self):
        ""

        await asyncio.sleep(30)
        while True:
            try:
                await self._check_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Scheduler error: {e}")
            await asyncio.sleep(60)

    async def _check_and_run(self):
        ""




        if _cascades_off():
            return

        config = load_schedule_config()
        now = datetime.now()


        active_hours = config.get("_settings", {}).get("active_hours", _DEFAULT_ACTIVE_HOURS)
        if isinstance(active_hours, list) and len(active_hours) == 2:
            h_start, h_end = active_hours
            if not (h_start <= now.hour < h_end):
                return

        for source_id, src_config in config.items():
            if source_id.startswith("_"):
                continue
            schedules = src_config.get("schedules", {})
            for stage, interval_min in schedules.items():
                if not isinstance(interval_min, int) or interval_min <= 0:
                    continue
                if (source_id, stage) in _SENZA_COMANDO_DALLA_DASHBOARD:
                    continue
                if stage == "l0" and source_id in _L0_SESSIONE and not source_listed(source_id):
                    continue


                if source_id in _MONITOR_SYNCED_SOURCES and stage == "l0":
                    if not self._is_monitor_stale(source_id, interval_min):
                        continue
                    log.warning(f"[auto] Monitor stale for {source_id}, scheduler taking over L0")


                last = self._last_run.get(source_id, {}).get(stage)
                if last and (now - last).total_seconds() < interval_min * 60:
                    continue


                script_path = self._resolve_script(source_id, stage)
                if not script_path:
                    continue


                extra_args = list(_SCRIPT_DEFAULT_ARGS.get(script_path, []))
                if script_path in _INCREMENTAL_SCRIPTS:
                    extra_args.append("--incremental")

                log.info(
                    f"[auto] Scheduling {source_id}/{stage} "
                    f"(interval={interval_min}min, args={extra_args or 'none'})"
                )
                job_id = await self._runner.run_script(
                    source=source_id,
                    script_path=script_path,
                    stage=stage,
                    extra_args=extra_args or None,
                )



                if source_id not in self._last_run:
                    self._last_run[source_id] = {}
                self._last_run[source_id][stage] = now
                self._save_last_run()


                safe_create_task(
                    self._track_job_result(source_id, stage, job_id, script_path, extra_args),
                    name=f"track-{source_id}-{stage}-{job_id[:8]}",
                )

    async def _track_job_result(
        self,
        source_id: str,
        stage: str,
        job_id: str,
        script_path: str | None = None,
        extra_args: list[str] | None = None,
    ):
        ""

        for _ in range(2100):
            await asyncio.sleep(1)
            job = self._runner.get_job(job_id)
            if not job or job.status != "running":
                break

        job = self._runner.get_job(job_id)
        if not job:
            return

        if job.status == "completed":

            if source_id in self._last_error:
                self._last_error[source_id].pop(stage, None)
            self._retry_count.pop(f"{source_id}/{stage}", None)

            if self._cascade:
                try:
                    await self._cascade.on_job_complete(
                        source=source_id,
                        stage=stage,
                        job_status=job.status,
                        job_id=job_id,
                    )
                except Exception as e:
                    log.error(f"Cascade failed after {source_id}/{stage}: {e}")


            await self._regen_pipeline_status()
        else:

            error_msg = f"Exit {job.exit_code} ({job.status}) at {datetime.now().isoformat()[:19]}"
            self._last_error.setdefault(source_id, {})[stage] = error_msg

            retry_key = f"{source_id}/{stage}"
            retries = self._retry_count.get(retry_key, 0)

            if retries < _MAX_RETRIES and script_path:
                self._retry_count[retry_key] = retries + 1
                backoff = _RETRY_BACKOFF_SEC * (retries + 1)
                log.warning(
                    f"[auto] Retry {retries + 1}/{_MAX_RETRIES} for {retry_key} "
                    f"in {backoff}s (was: {job.status})"
                )
                await asyncio.sleep(backoff)
                new_job_id = await self._runner.run_script(
                    source=source_id,
                    script_path=script_path,
                    stage=stage,
                    extra_args=extra_args,
                )
                safe_create_task(
                    self._track_job_result(source_id, stage, new_job_id, script_path, extra_args),
                    name=f"retry-{source_id}-{stage}-{new_job_id[:8]}",
                )
            else:
                if retries >= _MAX_RETRIES:
                    log.error(f"[auto] Max retries ({_MAX_RETRIES}) exceeded for {retry_key}")
                self._retry_count.pop(retry_key, None)

    async def _regen_pipeline_status(self):
        ""
        now = utc_now()
        if (
            self._last_status_regen
            and (now - self._last_status_regen).total_seconds() < _STATUS_REGEN_DEBOUNCE_SEC
        ):
            return

        script_path = _PROJECT_ROOT / "tools" / _STATUS_REGEN_SCRIPT
        if not script_path.exists():
            return

        self._last_status_regen = now
        try:
            job_id = await self._runner.run_script(
                source="system",
                script_path=_STATUS_REGEN_SCRIPT,
                stage="status",
            )
            log.info(f"[auto] Pipeline status regen triggered (job={job_id[:8]})")
        except Exception as e:
            log.warning(f"[auto] Pipeline status regen failed: {e}")

    def _is_monitor_stale(self, source_id: str, interval_min: int) -> bool:
        ""



        from sbk_config import get_last_run


        # Per-source last-run keys (one per mailbox/calendar). Load from user
        # config; the defaults below are generic placeholders.
        _SOURCE_TO_LASTRUN_KEYS: dict[str, list[str]] = {
            "email": ["email-primary"],
            "slack": ["slack-channels"],
            "calendar": ["calendar-primary"],
        }

        keys = _SOURCE_TO_LASTRUN_KEYS.get(source_id, [])
        if not keys:
            return False

        stale_threshold_sec = interval_min * 60 * 3
        now = utc_now()

        for key in keys:
            last = get_last_run(key)
            if last and (now - to_utc_aware(last)).total_seconds() < stale_threshold_sec:
                return False

        return True

    def _resolve_script(self, source_id: str, stage: str) -> str | None:
        ""
        from app.core.sbk_bridge import SOURCE_CONFIG

        for src in SOURCE_CONFIG:
            if src["id"] == source_id:
                scripts = src.get("scripts", {})
                path = scripts.get(stage)
                if path:
                    full = _PROJECT_ROOT / "tools" / path
                    if full.exists():
                        return path
        return None

    def get_status(self) -> dict:
        ""
        config = load_schedule_config()
        active_count = 0
        schedules_detail = []

        for source_id, src_config in config.items():
            for stage, interval_min in src_config.get("schedules", {}).items():
                if isinstance(interval_min, int) and interval_min > 0:
                    active_count += 1
                    last = self._last_run.get(source_id, {}).get(stage)
                    error = self._last_error.get(source_id, {}).get(stage)
                    schedules_detail.append(
                        {
                            "source": source_id,
                            "stage": stage,
                            "interval_min": interval_min,
                            "interval_label": _minutes_to_label(interval_min),
                            "last_run": last.isoformat() if last else None,
                            "last_error": error,
                        }
                    )

        cascade_status = self._cascade.get_status() if self._cascade else None

        return {
            "running": self._task is not None and not self._task.done(),
            "active_schedules": active_count,
            "details": schedules_detail,
            "cascade": cascade_status,
        }
