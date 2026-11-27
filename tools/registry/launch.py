"""Launches a job of the registry by its id, in the given mode, with the perimeter check and the consent for paid
work (--paid-ok), and writes a run receipt.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

if not __package__:
    # Run as a script (python tools/registry/<file>.py): put tools/ on the path, drop this folder from it
    # (its module names would shadow other modules) and make the relative imports below work.
    import sys as _sys

    _here = Path(__file__).resolve().parent
    _sys.path[:] = [p for p in _sys.path if Path(p or ".").resolve() != _here]
    if str(_here.parent) not in _sys.path:
        _sys.path.insert(0, str(_here.parent))
    __package__ = "registry"
    import registry  # noqa: F401, E402

from truth.receipt import Mode, Outcome, Receipt, write_receipt  # noqa: E402

import sbk_config  # noqa: E402

from .env import assert_no_secrets_in_argv, build_env  # noqa: E402
from .schema import JobManifest, load_job  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]


EXIT_CODES: dict[Outcome, int] = {
    Outcome.OK: 0,
    Outcome.EMPTY_CONFIRMED: 0,
    Outcome.DEGRADED: 1,
    Outcome.BROKEN: 1,
    Outcome.SKIPPED_LOCK: 75,
    Outcome.SKIPPED_WINDOW: 75,
    Outcome.SKIPPED_STATE: 75,
    Outcome.REFUSED_PAID: 77,
    Outcome.REFUSED_STATE: 77,
    Outcome.REFUSED_PERIMETER: 77,
    Outcome.REFUSED_BUDGET: 77,
}


def exit_code_for(outcome: Outcome) -> int:
    ""
    return EXIT_CODES.get(outcome, 1)


@dataclass
class RunResult:
    ""

    exit_code: int
    records_seen: int = 0
    records_written: int = 0
    stdout: str = ""
    stderr: str = ""
    empty_confirmed: bool = False
    cost_usd: float = 0.0


def _default_runner(job: JobManifest, *, env: dict, timeout: int) -> RunResult:
    ""



    cmd = [job.cmd, *job.args]
    cwd = job.cwd or str(_REPO_ROOT)
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(exit_code=-2, stderr=f"timeout after {timeout}s")
    _telem = _parse_run_telemetry(res.stdout)
    return RunResult(
        exit_code=res.returncode,
        stdout=res.stdout,
        stderr=res.stderr,
        records_seen=int(_telem.get("records_seen", 0) or 0),
        records_written=int(_telem.get("records_written", 0) or 0),
        empty_confirmed=bool(_telem.get("empty_confirmed", False)),
        cost_usd=float(_telem.get("cost_usd", 0.0) or 0.0),
    )


_TELEMETRY_MARKER = "##SBK_RECEIPT##"


def _parse_run_telemetry(stdout: str) -> dict:
    ""





    import json

    if not stdout or _TELEMETRY_MARKER not in stdout:
        return {}
    payload: dict = {}
    for line in stdout.splitlines():
        s = line.strip()
        if s.startswith(_TELEMETRY_MARKER):
            try:
                data = json.loads(s[len(_TELEMETRY_MARKER) :].strip())
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                payload = data
    return payload


def _default_perimeter_check(job: JobManifest) -> bool:
    """Fail-closed: the kit ships no perimeter registry, so a job that declares a perimeter is refused."""
    return not job.perimeter


def _mk_receipt(
    job: JobManifest,
    status: Outcome,
    *,
    mode: Mode,
    caller: str,
    duration_s: float = 0.0,
    records_seen: int = 0,
    records_written: int = 0,
    cost_usd: float = 0.0,
    detail: str = "",
) -> Receipt:
    return Receipt(
        job_id=job.job_id,
        caller=caller,
        status=status,
        mode=mode,
        records_seen=records_seen,
        records_written=records_written,
        paid=job.paid,
        cost_usd=cost_usd,
        campaign_id=job.campaign,
        duration_s=duration_s,
        detail=detail,
    )


def launch(
    job: JobManifest,
    *,
    mode: Mode | str = Mode.NORMAL,
    caller: str = "cli",
    paid_ok: bool = False,
    budget_ok: bool = True,
    perimeter_check: Callable[[JobManifest], bool] | None = None,
    runner: Callable[..., RunResult] | None = None,
    now: datetime | None = None,
    night_window: tuple[int, int] | None = None,
    write: bool = True,
    root: Path | None = None,
) -> Receipt:
    ""





    mode = Mode(mode) if isinstance(mode, str) else mode
    perimeter_check = perimeter_check or _default_perimeter_check
    runner = runner or _default_runner

    def finalize(receipt: Receipt) -> Receipt:
        if write:
            write_receipt(receipt, root=root)
        return receipt


    if not job.runnable:
        return finalize(
            _mk_receipt(
                job,
                Outcome.REFUSED_STATE,
                mode=mode,
                caller=caller,
                detail=f"state {job.state!r} not launchable",
            )
        )


    if night_window is not None and not job.night_ok:
        hour = (now or sbk_config.utc_now()).hour
        start, end = night_window
        in_window = (start <= hour < end) if start <= end else (hour >= start or hour < end)
        if in_window:
            return finalize(
                _mk_receipt(
                    job,
                    Outcome.SKIPPED_WINDOW,
                    mode=mode,
                    caller=caller,
                    detail=f"hour {hour} in night window {night_window}",
                )
            )


    if job.paid and not paid_ok:
        return finalize(
            _mk_receipt(
                job,
                Outcome.REFUSED_PAID,
                mode=mode,
                caller=caller,
                detail="paid job without explicit OK: refused (script not launched)",
            )
        )


    if job.paid and not budget_ok:
        return finalize(
            _mk_receipt(
                job,
                Outcome.REFUSED_BUDGET,
                mode=mode,
                caller=caller,
                detail="paid job without budget: refused",
            )
        )


    if not perimeter_check(job):
        return finalize(
            _mk_receipt(
                job,
                Outcome.REFUSED_PERIMETER,
                mode=mode,
                caller=caller,
                detail=f"perimeter {job.perimeter!r} declared, and no perimeter registry is configured",
            )
        )


    assert_no_secrets_in_argv(job.args)


    have_lock = True
    if job.lock:
        have_lock = sbk_config.acquire_pid_lock(job.lock)
        if not have_lock:
            return finalize(
                _mk_receipt(
                    job,
                    Outcome.SKIPPED_LOCK,
                    mode=mode,
                    caller=caller,
                    detail=f"lock {job.lock!r} busy: skipping (exit 75, never 0)",
                )
            )


    env = build_env(paid=job.paid)
    t0 = time.time()
    try:
        result = runner(job, env=env, timeout=job.timeout_s)
    finally:
        if job.lock and have_lock:
            sbk_config.release_pid_lock(job.lock)
    duration = time.time() - t0

    if result.exit_code == 0:
        status = Outcome.EMPTY_CONFIRMED if result.empty_confirmed else Outcome.OK
    else:
        status = Outcome.BROKEN

    return finalize(
        _mk_receipt(
            job,
            status,
            mode=mode,
            caller=caller,
            duration_s=duration,
            records_seen=result.records_seen,
            records_written=result.records_written,
            cost_usd=result.cost_usd,
            detail=(result.stderr or "")[:500] if status is Outcome.BROKEN else "",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="registry launch — launch a job from the registry")
    parser.add_argument("job_id", help="job id (manifest name)")
    parser.add_argument(
        "--mode",
        default="normal",
        choices=[m.value for m in Mode],
        help="execution mode",
    )
    parser.add_argument("--caller", default="cli")
    parser.add_argument(
        "--paid-ok",
        action="store_true",
        help="explicit OK for a paid job (without it, the paid job is refused)",
    )
    args = parser.parse_args(argv)

    job = load_job(args.job_id)
    receipt = launch(
        job,
        mode=args.mode,
        caller=args.caller,
        paid_ok=args.paid_ok,
    )
    print(receipt.to_json())
    return exit_code_for(receipt.status)


if __name__ == "__main__":
    raise SystemExit(main())
