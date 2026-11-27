#!/usr/bin/env python3
"""Pipeline control panel: what is running, how much memory it takes, and leftover jobs or stale locks (status, on, off, check, cleanup)."""





















from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_resources import (  # noqa: E402
    budget,
    descendants,
    phys_footprint,
    pressure,
)

from sbk_config import CASCADES_OFF_FLAG, DATA_ROOT, automatic_cascades_on  # noqa: E402

PROJECT_ROOT = _TOOLS_DIR.parent


LONG_LIVED = ("sbk-monitor", "uvicorn", "em-realtime", "sl-realtime")


def _ps_sbk() -> list[dict]:
    ""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,etime=,command="],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    rows = []
    me = os.getpid()
    for line in out.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid_s, ppid_s, etime, cmd = parts
        if str(PROJECT_ROOT) not in cmd:
            continue
        try:
            pid, ppid = int(pid_s), int(ppid_s)
        except ValueError:
            continue
        if pid == me or "sb-pipeline-ctl" in cmd:
            continue
        script = next(
            (Path(tok).name for tok in cmd.split() if tok.endswith(".py")),
            cmd.split()[0].rsplit("/", 1)[-1],
        )
        rows.append(
            {
                "pid": pid,
                "ppid": ppid,
                "etime": etime,
                "script": script,
                "cmd": cmd,
                "footprint": phys_footprint(pid) or 0,
                "service": any(s in cmd for s in LONG_LIVED),
                "orphan": ppid == 1,
            }
        )
    return rows


def _locks() -> list[dict]:
    out = []
    for p in sorted(DATA_ROOT.glob("*.pid")):
        try:
            pid = int(p.read_text().strip())
        except (ValueError, OSError):
            out.append({"file": p, "pid": None, "alive": False, "stale": True})
            continue
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
        out.append({"file": p, "pid": pid, "alive": alive, "stale": not alive})
    return out


def _pending_events() -> int:
    ev_dir = DATA_ROOT / "events"
    if not ev_dir.exists():
        return 0
    n = 0
    for f in ev_dir.glob("*.json"):
        try:
            import json

            if not json.loads(f.read_text()).get("processed"):
                n += 1
        except (ValueError, OSError):
            continue
    return n


def _gb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB"


def cmd_status() -> int:
    p = pressure()
    b = budget()
    print("── SBK · pipeline status ────────────────────────────────────")
    auto = automatic_cascades_on()
    print(
        "  automatic cascades: "
        + ("on (the next step starts on its own)" if auto else "off (you run the pipeline by hand)")
    )
    print(f"  memory       : {p}")
    print(
        f"  job budget   : {b.job_gb:.1f} GB · DuckDB {b.duckdb_memory_limit} · {b.threads} threads"
    )
    pend = _pending_events()
    print(
        f"  events queued: {pend}"
        + ("  (will be processed at the next manual run)" if pend and not auto else "")
    )

    procs = _ps_sbk()
    jobs = [x for x in procs if not x["service"]]
    svcs = [x for x in procs if x["service"]]
    print(f"\n  SERVICES ({len(svcs)})")
    for x in sorted(svcs, key=lambda r: -r["footprint"]):
        print(f"    {x['pid']:>7}  {_gb(x['footprint']):>10}  up {x['etime']:>11}  {x['script']}")
    print(f"\n  JOBS ({len(jobs)})" + ("  ← none: pipeline idle" if not jobs else ""))
    for x in sorted(jobs, key=lambda r: -r["footprint"]):
        flag = "  ORPHAN" if x["orphan"] else ""
        print(
            f"    {x['pid']:>7}  {_gb(x['footprint']):>10}  up {x['etime']:>11}  {x['script']}{flag}"
        )

    lk = _locks()
    if lk:
        print(f"\n  LOCKS ({len(lk)})")
        for x in lk:
            state = "alive" if x["alive"] else "STALE"
            print(f"    {x['file'].name:<34} PID {x['pid']}  {state}")
    tot = sum(x["footprint"] for x in procs)
    print(f"\n  total SBK footprint: {_gb(tot)}")
    return 0


def cmd_off() -> int:
    CASCADES_OFF_FLAG.parent.mkdir(parents=True, exist_ok=True)
    CASCADES_OFF_FLAG.write_text(
        "Automatic cascades: off. No step starts on its own.\n"
        "Events stay queued and are processed by the manual run:\n"
        "  uv run python tools/cross-source/xs-pipeline-run.py --propagate\n"
        "To switch them on:  uv run python tools/util/sb-pipeline-ctl.py on\n"
    )
    print("Automatic cascades: off.")
    print("  · no cascade starts on its own anymore")
    print("  · events keep being RECORDED (no data lost)")
    print("  · to process them: uv run python tools/cross-source/xs-pipeline-run.py --propagate")
    return 0


def cmd_on() -> int:
    CASCADES_OFF_FLAG.unlink(missing_ok=True)
    print("Automatic cascades: on. The next step starts on its own again.")
    return 0


def _ha_la_marca(pid: int, marca: bytes) -> bool:
    ""



    import ctypes
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, pid)
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or not size.value:
        return False
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return False
    return marca in buf.raw[: size.value]


def cmd_check(
    *,
    cleanup: bool = False,
    force: bool = False,
    ignora: tuple[int, ...] = (),
    del_run: str = "",
) -> int:
    ""










    problems = []
    procs = [x for x in _ps_sbk() if x["pid"] not in set(ignora)]
    if del_run:
        marca = f"SBK_CODA_RUN={del_run}".encode()
        procs = [x for x in procs if _ha_la_marca(x["pid"], marca)]
    jobs = [x for x in procs if not x["service"]]
    orphans = [x for x in procs if x["orphan"] and not x["service"]]
    lk = _locks()
    stale = [x for x in lk if x["stale"]]

    print("── shutdown check ──────────────────────────────────────────────")
    if jobs:
        problems.append(f"{len(jobs)} jobs still alive")
        print(f"  ⚠️  {len(jobs)} jobs still running:")
        for x in jobs:
            print(f"      PID {x['pid']}  {_gb(x['footprint'])}  up {x['etime']}  {x['script']}")
    else:
        print("  ✅ no leftover jobs")

    if orphans:
        print(f"  ⚠️  of which {len(orphans)} ORPHANS (parent dead):")
        for x in orphans:
            kids = descendants(x["pid"])
            print(
                f"      PID {x['pid']}  {x['script']}" + (f"  +{len(kids)} children" if kids else "")
            )

    if stale:
        print(f"  ⚠️  {len(stale)} stale locks (process dead, file left):")
        for x in stale:
            print(f"      {x['file'].name} (PID {x['pid']})")
            if cleanup:
                x["file"].unlink(missing_ok=True)
                print("        → removed")
        if not cleanup:
            problems.append(f"{len(stale)} stale locks")
    else:
        print("  ✅ no stale locks")

    p = pressure()
    if p.seg_ratio >= 0.70:
        problems.append(f"memory still under pressure ({p.seg_ratio * 100:.0f}%)")
        print(f"  ⚠️  {p}")
    else:
        print(f"  ✅ memory ok — {p}")

    if cleanup and force and jobs:
        for x in jobs:
            print(f"  → terminating PID {x['pid']} ({x['script']})")
            try:
                os.kill(x["pid"], 15)
            except ProcessLookupError:
                pass

    if problems:
        print(f"\n  OUTCOME: NOT clean — {', '.join(problems)}")
        return 1
    print("\n  OUTCOME: everything closed correctly")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "comando",
        choices=["status", "on", "off", "check", "cleanup"],
        help="status; on / off = automatic cascades on or off; check; cleanup",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="with 'cleanup': also terminate live jobs (default: only stale locks)",
    )
    ap.add_argument(
        "--ignora-pid",
        type=int,
        action="append",
        default=[],
        help="with 'check'/'cleanup': PIDs to not count among leftovers (the caller)",
    )
    ap.add_argument(
        "--del-run",
        default="",
        help="with 'check': only that run's processes count (SBK_CODA_RUN in their environment)",
    )
    a = ap.parse_args()
    if a.comando == "status":
        return cmd_status()
    if a.comando == "off":
        return cmd_off()
    if a.comando == "on":
        return cmd_on()
    if a.comando == "check":
        return cmd_check(ignora=tuple(a.ignora_pid), del_run=a.del_run)
    return cmd_check(cleanup=True, force=a.force, ignora=tuple(a.ignora_pid))


if __name__ == "__main__":
    sys.exit(main())
