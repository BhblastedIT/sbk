""





from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import sbk_config

from .base import CheckResult, CheckStatus, coerce_as_of

__all__ = ["check_sync_state_freshness", "load_sync_state"]


def load_sync_state(root: str | Path | None = None) -> dict:
    ""
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    path = base / ".sync-state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _verdict(ts_value: object, as_of_dt, warn_days: int, broken_days: int):
    try:
        ts = coerce_as_of(ts_value)
    except (ValueError, TypeError):
        return CheckStatus.BROKEN, None, "timestamp illeggibile"
    age_days = (as_of_dt - ts).days
    if age_days <= warn_days:
        status = CheckStatus.OK
    elif age_days <= broken_days:
        status = CheckStatus.DEGRADED
    else:
        status = CheckStatus.BROKEN
    return status, age_days, f"ultimo sync {ts.date()} ({age_days}g fa)"


def check_sync_state_freshness(
    sync_state: dict,
    *,
    as_of=None,
    warn_days: int = 1,
    broken_days: int = 3,
) -> list[CheckResult]:
    ""
    as_of_dt = coerce_as_of(as_of)
    results: list[CheckResult] = []

    email = sync_state.get("email", {})
    account_ts = email.get("account_timestamps", {}) if isinstance(email, dict) else {}
    for account, ts_value in sorted(account_ts.items()):
        status, age_days, detail = _verdict(ts_value, as_of_dt, warn_days, broken_days)
        results.append(
            CheckResult(
                check="sync_state",
                target=f"email:{account}",
                status=status,
                detail=detail,
                metrics={"age_days": age_days},
                as_of=as_of_dt.isoformat(),
            )
        )

    for section, payload in sorted(sync_state.items()):
        if not isinstance(payload, dict):
            continue
        last_check = payload.get("last_check")
        if not isinstance(last_check, str | datetime):
            continue
        status, age_days, detail = _verdict(last_check, as_of_dt, warn_days, broken_days)
        results.append(
            CheckResult(
                check="sync_state",
                target=f"sync:{section}",
                status=status,
                detail=detail,
                metrics={"age_days": age_days},
                as_of=as_of_dt.isoformat(),
            )
        )

    return results
