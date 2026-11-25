""










from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

_DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
SYSTEM_DIR = _DATA_ROOT / "system"
METRICS_FILE = SYSTEM_DIR / "pipeline-metrics.jsonl"

_MAX_FILE_SIZE = 10 * 1024 * 1024
_last_rotation_date: str | None = None

log = logging.getLogger("sbk-pipeline-metrics")


def _ensure_dir() -> None:
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)


def _maybe_rotate() -> None:
    global _last_rotation_date
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if _last_rotation_date is not None and _last_rotation_date != today:
        _do_rotate(_last_rotation_date)
    _last_rotation_date = today
    try:
        if METRICS_FILE.exists() and METRICS_FILE.stat().st_size > _MAX_FILE_SIZE:
            _do_rotate(today)
    except OSError:
        pass


def _do_rotate(date_suffix: str) -> None:
    if not METRICS_FILE.exists():
        return
    archive = SYSTEM_DIR / f"pipeline-metrics-{date_suffix}.jsonl"
    if archive.exists():
        try:
            with (
                open(METRICS_FILE, encoding="utf-8") as src,
                open(archive, "a", encoding="utf-8") as dst,
            ):
                dst.write(src.read())
            METRICS_FILE.unlink()
        except OSError as e:
            log.warning("Pipeline metrics rotation (append) failed: %s", e)
    else:
        try:
            METRICS_FILE.rename(archive)
        except OSError as e:
            log.warning("Pipeline metrics rotation failed: %s", e)


def log_pipeline_run(
    script: str,
    stage: str,
    source: str,
    status: str,
    duration_s: float,
    exit_code: int | None = None,
    entities_out: int | None = None,
    caller: str = "unknown",
) -> None:
    ""
    _ensure_dir()
    _maybe_rotate()

    entry = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "script": script,
        "stage": stage,
        "source": source,
        "status": status,
        "duration_s": round(duration_s, 1),
        "caller": caller,
    }
    if exit_code is not None:
        entry["exit_code"] = exit_code
    if entities_out is not None:
        entry["entities_out"] = entities_out

    try:
        with open(METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except OSError as e:
        log.warning("Failed to write pipeline metrics: %s", e)


def get_metrics(hours: int = 24) -> dict:
    ""
    cutoff_epoch = time.time() - hours * 3600
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    total = 0
    by_status: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    durations: list[float] = []
    recent_runs: list[dict] = []
    recent_failures: list[dict] = []

    if not METRICS_FILE.exists():
        return {
            "hours": hours,
            "total": 0,
            "by_status": {},
            "by_stage": {},
            "avg_duration_s": 0,
            "recent_runs": [],
            "recent_failures": [],
        }

    try:
        with open(METRICS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("ts", "") < cutoff_ts:
                    continue

                total += 1
                st = entry.get("status", "unknown")
                by_status[st] = by_status.get(st, 0) + 1
                stg = entry.get("stage", "unknown")
                by_stage[stg] = by_stage.get(stg, 0) + 1
                dur = entry.get("duration_s", 0)
                if dur:
                    durations.append(dur)
                recent_runs.append(entry)
                if st in ("failed", "timeout", "error"):
                    recent_failures.append(entry)
    except OSError:
        pass

    avg_dur = round(sum(durations) / len(durations), 1) if durations else 0

    return {
        "hours": hours,
        "total": total,
        "by_status": by_status,
        "by_stage": by_stage,
        "avg_duration_s": avg_dur,
        "recent_runs": recent_runs[-20:],
        "recent_failures": recent_failures[-10:],
    }


def get_duration_trend(days: int = 7) -> list[dict]:
    ""
    cutoff_epoch = time.time() - days * 86400
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    daily: dict[str, list[float]] = {}

    if not METRICS_FILE.exists():
        return []

    try:
        with open(METRICS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("ts", "")
                if ts < cutoff_ts:
                    continue
                day = ts[:10]
                dur = entry.get("duration_s", 0)
                daily.setdefault(day, []).append(dur)
    except OSError:
        pass

    result = []
    for day in sorted(daily):
        durs = daily[day]
        result.append(
            {
                "date": day,
                "runs": len(durs),
                "avg_duration_s": round(sum(durs) / len(durs), 1) if durs else 0,
            }
        )
    return result
