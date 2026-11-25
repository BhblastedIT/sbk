""











from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ingestion.adapters.base import Adapter, RunResult  # noqa: E402
from ingestion.loud_fail import mark_if_healthy  # noqa: E402
from ingestion.manifest import Manifest  # noqa: E402

log = logging.getLogger("sbk-ingestion.runner")


@dataclass
class RunnerOutcome:
    ""

    source: str
    ok: bool
    adapter_used: str | None
    priority_used: int | None
    fallback_active: bool
    result: RunResult | None
    attempts: list[tuple[str, str]]


def _alert(level: str, source: str, msg: str) -> None:
    ""





    log.warning("[%s] %s: %s", level, source, msg)
    if os.environ.get("SBK_ALERTS_DISABLED"):
        return
    try:
        from monitoring import slack_alerter  # type: ignore

        slack_alerter.alert_custom(
            title=f"[{level}] ingestion/{source}",
            body=msg,
            alert_key=f"ingestion-{source}-{level}",
        )
    except Exception as e:  # pragma: no cover - best effort
        log.debug("alert not sent (%s): %s", source, e)


def run_source(
    manifest: Manifest,
    adapters: list[Adapter],
    watermark: str | None,
) -> RunnerOutcome:
    ""




    attempts: list[tuple[str, str]] = []

    for ad in adapters:
        prio = getattr(ad, "priority", 99)

        try:
            probe = ad.auth_probe()
        except Exception as e:
            attempts.append((ad.name, f"probe-exception: {e}"))
            _alert("AUTH", manifest.source, f"adapter {ad.name}: probe raised {e}")
            continue
        if not probe.ok:
            attempts.append((ad.name, f"probe-fail: {probe.detail}"))
            _alert("AUTH", manifest.source, f"adapter {ad.name}: auth dead ({probe.detail})")
            continue


        try:
            res = ad.run(watermark)
        except Exception as e:
            attempts.append((ad.name, f"run-exception: {e}"))
            _alert("RUN", manifest.source, f"adapter {ad.name}: run raised {e}")
            continue

        res.adapter = res.adapter or ad.name
        if res.healthy:




            min_full = int(manifest.sanity_baseline.get("min_records_full", 0) or 0)
            if watermark is None and min_full > 0 and res.records < min_full:
                attempts.append((ad.name, f"zero-suspicious records={res.records}<{min_full}"))
                _alert(
                    "ZERO",
                    manifest.source,
                    f"adapter {ad.name}: full-scan with {res.records} records < threshold {min_full} "
                    "-> suspected silent failure, watermark NOT advanced",
                )
                continue
            marked = mark_if_healthy(manifest.source, res)
            attempts.append(
                (ad.name, f"ok records={res.records} watermark={'advanced' if marked else 'no'}")
            )
            fallback = prio > 1
            if fallback:
                _alert(
                    "FALLBACK",
                    manifest.source,
                    f"primary down: activating fallback adapter {ad.name} (priority {prio})",
                )
            log.info(
                "%s: OK via %s (priority %d, records=%d)%s",
                manifest.source,
                ad.name,
                prio,
                res.records,
                " [FALLBACK]" if fallback else "",
            )
            return RunnerOutcome(
                source=manifest.source,
                ok=True,
                adapter_used=ad.name,
                priority_used=prio,
                fallback_active=fallback,
                result=res,
                attempts=attempts,
            )
        else:
            attempts.append(
                (ad.name, f"unhealthy ok={res.ok} degraded={res.degraded} errors={res.errors}")
            )
            _alert(
                "DEGRADED",
                manifest.source,
                f"adapter {ad.name}: run not healthy (degraded={res.degraded} errors={res.errors}) "
                "-> watermark NOT advanced, trying the next one",
            )
            continue


    _alert("P1", manifest.source, f"ALL adapters failed ({len(attempts)} attempts)")
    return RunnerOutcome(
        source=manifest.source,
        ok=False,
        adapter_used=None,
        priority_used=None,
        fallback_active=False,
        result=None,
        attempts=attempts,
    )
