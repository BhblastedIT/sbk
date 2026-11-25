""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

log = logging.getLogger("sbk.dashboard.slack_health")

router = APIRouter(prefix="/api/slack-health", tags=["slack-health"])

_DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
_SYSTEM_DIR = _DATA_ROOT / "system"
_LOG_DIR = _DATA_ROOT / "logs"


def _find_processes(pattern: str) -> list[dict]:
    ""
    try:
        result = subprocess.run(
            ["pgrep", "-fl", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
        procs = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) >= 2:
                procs.append({"pid": int(parts[0]), "cmd": parts[1][:120]})
        return procs
    except Exception as e:
        log.warning("pgrep failed for %s: %s", pattern, e)
        return []


def _get_daemon_status() -> dict:
    ""
    procs = _find_processes("sbk-monitor")
    if not procs:
        return {"running": False, "pid": None, "uptime": None}

    pid = procs[0]["pid"]
    uptime = None
    try:
        result = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        uptime = result.stdout.strip() or None
    except Exception:
        pass

    return {"running": True, "pid": pid, "uptime": uptime}


def _get_rate_limiter_stats() -> dict:
    ""
    import sys

    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    try:
        from monitoring.slack_alerter import (
            MAX_ALERTS_PER_DAY,
            MAX_ALERTS_PER_HOUR,
            _load_daily_count,
            _load_hourly_count,
            _load_pending_alerts,
        )

        hourly, _hw = _load_hourly_count()
        daily, _dw = _load_daily_count()
        pending = _load_pending_alerts()
        return {
            "hourly": hourly,
            "hourly_max": MAX_ALERTS_PER_HOUR,
            "daily": daily,
            "daily_max": MAX_ALERTS_PER_DAY,
            "pending": len(pending),
        }
    except Exception as e:
        log.warning("rate limiter stats failed: %s", e)
        return {
            "hourly": 0,
            "hourly_max": 10,
            "daily": 0,
            "daily_max": 30,
            "pending": 0,
            "error": str(e),
        }


def _get_api_stats_slack() -> dict:
    ""
    import sys

    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    try:
        from monitoring.api_ledger import get_stats

        stats = get_stats(hours=1)
        slack_stats = stats.get("by_service", {}).get("slack", {})
        return {
            "reads": slack_stats.get("READ", 0),
            "writes": slack_stats.get("WRITE", 0),
            "errors": slack_stats.get("errors", 0),
            "rate_limited": slack_stats.get("rate_limited", 0),
        }
    except Exception as e:
        log.warning("api stats failed: %s", e)
        return {"reads": 0, "writes": 0, "errors": 0, "rate_limited": 0, "error": str(e)}


def _get_state_file_info() -> dict:
    ""
    state_file = _SYSTEM_DIR / "slack-alerts-sent.json"
    if not state_file.exists():
        return {"total_entries": 0, "recent": []}

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))

        entries = {k: v for k, v in data.items() if not k.startswith("_")}

        sorted_entries = sorted(entries.items(), key=lambda x: x[1], reverse=True)[:10]
        recent = [
            {
                "key": k,
                "ts": datetime.fromtimestamp(v, tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for k, v in sorted_entries
        ]
        return {"total_entries": len(entries), "recent": recent}
    except Exception as e:
        log.warning("state file read failed: %s", e)
        return {"total_entries": 0, "recent": [], "error": str(e)}


def _get_recent_logs() -> list[str]:
    ""
    log_file = _LOG_DIR / "monitor-stderr.log"
    if not log_file.exists():
        return []

    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()


        slack_pattern = re.compile(r"slack", re.IGNORECASE)
        slack_lines = [line.rstrip() for line in lines[-200:] if slack_pattern.search(line)]
        return slack_lines[-20:]
    except Exception as e:
        log.warning("log read failed: %s", e)
        return [f"Error reading logs: {e}"]


def _collect_slack_health() -> dict:
    ""
    return {
        "mcp_processes": _find_processes("slack-mcp"),
        "daemon_status": _get_daemon_status(),
        "rate_limiter": _get_rate_limiter_stats(),
        "api_stats": _get_api_stats_slack(),
        "state_file": _get_state_file_info(),
        "recent_logs": _get_recent_logs(),
        "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
    }


@router.get("/stats")
def slack_health_stats():
    ""
    return _collect_slack_health()
