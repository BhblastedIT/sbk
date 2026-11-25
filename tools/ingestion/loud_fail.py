""








from __future__ import annotations

import logging
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ingestion.adapters.base import RunResult  # noqa: E402
from pipeline_decorator import PermanentAPIError  # noqa: E402

from sbk_config import mark_last_run  # noqa: E402

log = logging.getLogger("sbk-ingestion.loud_fail")


class AuthExpired(PermanentAPIError):
    ""







class ZeroSuspicious(PermanentAPIError):
    ""


def mark_if_healthy(source: str, result: RunResult) -> bool:
    ""




    if result.healthy:
        mark_last_run(source)
        log.debug(
            "watermark advanced for %s (adapter=%s, records=%d)",
            source,
            result.adapter,
            result.records,
        )
        return True
    log.warning(
        "watermark NOT advanced for %s: unhealthy run (ok=%s degraded=%s errors=%d)",
        source,
        result.ok,
        result.degraded,
        result.errors,
    )
    return False


def guard_zero_suspicious(records: int, min_expected: int, context: str = "") -> None:
    ""




    if min_expected > 0 and records < min_expected:
        raise ZeroSuspicious(
            f"{context or 'run'}: {records} records < suspicious threshold {min_expected} "
            "-> probable silent failure, watermark NOT advanced"
        )
