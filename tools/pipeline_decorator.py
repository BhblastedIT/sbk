#!/usr/bin/env python3
""

















from __future__ import annotations

import functools
import logging
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import mark_last_run

log = logging.getLogger("sbk-pipeline")


class PermanentAPIError(Exception):
    ""

    pass


def pipeline_step(
    name: str,
    source: str,
    stage: str = "",
    mark_run: bool = True,
    dlq_on_fail: bool = True,
):
    ""









    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            step_log = logging.getLogger(f"sbk-pipeline.{name}")
            step_log.info("Starting: %s", name)
            start = time.time()
            inizio_iso = datetime.now(UTC).isoformat()

            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                step_log.info("Completed: %s (%.1fs)", name, elapsed)



                if mark_run and "--dry-run" not in sys.argv:
                    try:
                        mark_last_run(source)
                        step_log.debug("mark_last_run(%s) OK", source)
                    except Exception as e:
                        step_log.warning("mark_last_run(%s) failed: %s", source, e)

                _log_metrics(name, stage, source, "success", elapsed, exit_code=0)
                if dlq_on_fail and "--dry-run" not in sys.argv:
                    _chiudi_superate(name, inizio_iso)

                return result

            except SystemExit as e:

                elapsed = time.time() - start
                if e.code == 0 or e.code is None:






                    step_log.info(
                        "Exited (sys.exit 0) without marking the run: %s (%.1fs)", name, elapsed
                    )
                    _log_metrics(name, stage, source, "exited", elapsed, exit_code=0)
                else:

                    messaggio = _con_il_perche(f"sys.exit({e.code})")
                    step_log.error(
                        "Failed (sys.exit %s): %s (%.1fs)",
                        e.code,
                        name,
                        elapsed,
                    )
                    if dlq_on_fail:
                        _record_failure(
                            name,
                            source,
                            stage,
                            messaggio,
                            "uso" if _da_argparse(e) else "SystemExit",
                        )
                    _log_metrics(
                        name,
                        stage,
                        source,
                        "failure",
                        elapsed,
                        exit_code=e.code if isinstance(e.code, int) else 1,
                    )
                raise

            except PermanentAPIError as e:
                elapsed = time.time() - start
                step_log.error("PERMANENT API ERROR: %s — aborting immediately", e)
                if dlq_on_fail:
                    _record_failure(name, source, stage, str(e), "PermanentAPIError")
                _log_metrics(name, stage, source, "failure", elapsed, exit_code=2)
                sys.exit(2)

            except Exception as e:
                elapsed = time.time() - start
                error_type = type(e).__name__
                error_msg = str(e)
                tb = traceback.format_exc()
                step_log.error(
                    "Failed: %s (%.1fs) — %s: %s\n%s",
                    name,
                    elapsed,
                    error_type,
                    error_msg,
                    tb,
                )

                if dlq_on_fail:
                    _record_failure(name, source, stage, error_msg, error_type)

                _log_metrics(name, stage, source, "failure", elapsed)

                raise

        return wrapper

    return decorator


def _log_metrics(
    name: str,
    stage: str,
    source: str,
    status: str,
    elapsed: float,
    exit_code: int | None = None,
) -> None:
    ""





    try:
        from monitoring.pipeline_metrics import log_pipeline_run

        log_pipeline_run(
            script=name,
            stage=stage,
            source=source,
            status=status,
            duration_s=elapsed,
            exit_code=exit_code,
            caller="pipeline_decorator",
        )
    except Exception as metrics_err:
        log.debug("pipeline metrics logging failed: %s", metrics_err)


def _da_argparse(e: SystemExit) -> bool:
    ""

    if e.code != 2:
        return False
    tb, ultimo = e.__traceback__, None
    while tb is not None:
        ultimo, tb = tb, tb.tb_next
    return bool(ultimo and ultimo.tb_frame.f_code.co_filename.endswith("argparse.py"))


def _con_il_perche(messaggio: str) -> str:
    ""


    percorso = os.environ.get("SBK_PASSO_LOG")
    if not percorso:
        return messaggio
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.flush()
        except Exception:  # noqa: BLE001 — un flusso chiuso non deve fermare la registrazione
            pass
    try:
        from pipeline_dlq import coda_del_log

        righe = coda_del_log(percorso)
    except Exception:  # noqa: BLE001
        return messaggio
    return f"{messaggio}: {righe}" if righe else messaggio


def _chiudi_superate(name: str, inizio_iso: str) -> None:
    ""
    try:
        from pipeline_dlq import chiudi_superate

        chiudi_superate(
            {name},
            f"closed: '{name}' succeeded on {datetime.now():%Y-%m-%d %H:%M}"
            + (
                f" (run {os.environ['SBK_CODA_RUN']})"
                if os.environ.get("SBK_CODA_RUN")
                else ""
            ),
            prima_di=inizio_iso,
        )
    except Exception as dlq_err:  # noqa: BLE001
        log.warning("DLQ: could not close the superseded entries: %s", dlq_err)


def _record_failure(name: str, source: str, stage: str, error_msg: str, error_type: str) -> None:
    ""
    try:
        from pipeline_dlq import add_failure

        add_failure(
            script=name,
            source=source,
            stage=stage,
            error_message=error_msg,
            error_type=error_type,
        )
    except Exception as dlq_err:
        log.warning("DLQ record failed: %s", dlq_err)
