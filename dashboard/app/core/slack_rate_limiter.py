""








from __future__ import annotations

import json
import os
import time
from pathlib import Path

_DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
_SYSTEM_DIR = _DATA_ROOT / "system"
_SLACK_LIMITER_FILE = _SYSTEM_DIR / "slack-message-limits.json"


MAX_MESSAGES_PER_HOUR = 20
MAX_MESSAGES_PER_MINUTE = 3
IDEMPOTENCY_WINDOW_SECONDS = 300


class RateLimitExceeded(Exception):
    ""

    pass


class IdempotencyViolation(Exception):
    ""

    pass


def _ensure_dir() -> None:
    _SYSTEM_DIR.mkdir(parents=True, exist_ok=True)


def _load_limits() -> dict:
    ""
    _ensure_dir()
    if _SLACK_LIMITER_FILE.exists():
        try:
            return json.loads(_SLACK_LIMITER_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_limits(state: dict) -> None:
    ""
    _ensure_dir()
    _SLACK_LIMITER_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def check_rate_limit(client_ip: str, idempotency_key: str | None = None) -> tuple[bool, str]:
    ""














    state = _load_limits()
    now = time.time()

    if client_ip not in state:
        state[client_ip] = {"sent_times": [], "idempotency_keys": {}}

    ip_state = state[client_ip]


    cutoff_hour = now - 3600
    ip_state["sent_times"] = [t for t in ip_state["sent_times"] if t > cutoff_hour]


    cutoff_idempotency = now - IDEMPOTENCY_WINDOW_SECONDS
    ip_state["idempotency_keys"] = {
        k: v for k, v in ip_state["idempotency_keys"].items() if v > cutoff_idempotency
    }


    if len(ip_state["sent_times"]) >= MAX_MESSAGES_PER_HOUR:
        _save_limits(state)
        raise RateLimitExceeded(
            f"Hourly limit ({MAX_MESSAGES_PER_HOUR} messages) reached. Try again later."
        )


    recent_minute = [t for t in ip_state["sent_times"] if t > (now - 60)]
    if len(recent_minute) >= MAX_MESSAGES_PER_MINUTE:
        _save_limits(state)
        raise RateLimitExceeded(
            f"Too many messages in short time. Max {MAX_MESSAGES_PER_MINUTE} per minute."
        )


    if idempotency_key:
        if idempotency_key in ip_state["idempotency_keys"]:
            raise IdempotencyViolation(
                "Duplicate message detected. Message already sent within last 5 minutes."
            )
        ip_state["idempotency_keys"][idempotency_key] = now


    ip_state["sent_times"].append(now)
    _save_limits(state)

    return True, ""


def get_limit_status(client_ip: str) -> dict:
    ""










    state = _load_limits()
    now = time.time()

    if client_ip not in state:
        return {
            "messages_sent_hour": 0,
            "messages_sent_minute": 0,
            "limit_hour": MAX_MESSAGES_PER_HOUR,
            "limit_minute": MAX_MESSAGES_PER_MINUTE,
            "can_send": True,
        }

    ip_state = state[client_ip]


    cutoff_hour = now - 3600
    sent_times = [t for t in ip_state["sent_times"] if t > cutoff_hour]

    recent_minute = [t for t in sent_times if t > (now - 60)]

    can_send = (
        len(sent_times) < MAX_MESSAGES_PER_HOUR and len(recent_minute) < MAX_MESSAGES_PER_MINUTE
    )

    return {
        "messages_sent_hour": len(sent_times),
        "messages_sent_minute": len(recent_minute),
        "limit_hour": MAX_MESSAGES_PER_HOUR,
        "limit_minute": MAX_MESSAGES_PER_MINUTE,
        "can_send": can_send,
    }
