#!/usr/bin/env python3
"""Custodian of one run started by the SBK app: it runs a command, logs it, writes a heartbeat and stops it on request.

Usage: sb-run.py RUN_ID RUN_FOLDER -- COMMAND [ARG...]
"""






























from __future__ import annotations

import ctypes
import fcntl
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
SYSTEM = DATA_ROOT / "system"

RUNS = Path(os.environ.get("SBK_RUN_REGISTRO", str(SYSTEM / "secondbrain-app-runs.jsonl")))
LOCK = Path(os.environ.get("SBK_RUN_LOCK", str(SYSTEM / "secondbrain-run.lock")))
BATTITO_S = 10
FILE_APERTI = 65536


SCALA = ((signal.SIGINT, 30), (signal.SIGTERM, 15), (signal.SIGKILL, 5))


def _adesso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _durata(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _registra(voce: dict) -> None:
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(voce, ensure_ascii=False) + "\n")


def _alza_file_aperti() -> int:
    ""
    morbido, duro = resource.getrlimit(resource.RLIMIT_NOFILE)
    voluto = FILE_APERTI if duro == resource.RLIM_INFINITY else min(FILE_APERTI, duro)
    if morbido >= voluto:
        return morbido
    for prova in (voluto, 10240):
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (prova, duro))
            return prova
        except (ValueError, OSError):
            continue
    return morbido





def _tabella() -> dict[int, tuple[int, int]]:
    ""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid="], capture_output=True, text=True, timeout=10
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    t: dict[int, tuple[int, int]] = {}
    for riga in out.splitlines():
        try:
            pid, ppid, pgid = (int(x) for x in riga.split())
        except ValueError:
            continue
        t[pid] = (ppid, pgid)
    return t


_LIBC = ctypes.CDLL("/usr/lib/libSystem.dylib", use_errno=True)


def marcato(pid: int, marca: bytes) -> bool:
    ""





    mib = (ctypes.c_int * 3)(1, 49, pid)
    size = ctypes.c_size_t(0)
    if _LIBC.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or not size.value:
        return False
    buf = ctypes.create_string_buffer(size.value)
    if _LIBC.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return False
    return marca in buf.raw[: size.value]


def albero(radice: int | None, marca: bytes) -> set[int]:
    ""

    t = _tabella()
    figli: dict[int, list[int]] = {}
    for pid, (ppid, _) in t.items():
        figli.setdefault(ppid, []).append(pid)
    io = os.getpid()
    semi = [radice] if radice in t else []
    semi += [p for p, (pp, _) in t.items() if pp == 1 and p != io and marcato(p, marca)]
    visti: set[int] = set()
    pila = list(semi)
    while pila:
        p = pila.pop()
        if p in visti or p == io or p not in t:
            continue
        visti.add(p)
        pila.extend(figli.get(p, []))
    return visti


def _lanciatori_uv() -> set[int]:
    ""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=10
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return set()
    uv = set()
    for riga in out.splitlines():
        parti = riga.strip().split(None, 1)
        if len(parti) == 2 and parti[0].isdigit() and Path(parti[1]).name == "uv":
            uv.add(int(parti[0]))
    return uv


def _segnala(pids: set[int], sig: int) -> None:
    ""





    t = _tabella()
    if sig in (signal.SIGINT, signal.SIGTERM):
        uv = _lanciatori_uv()
        for p in pids:
            if p in t and p not in uv:
                try:
                    os.kill(p, sig)
                except (ProcessLookupError, PermissionError):
                    pass
        return
    gruppi = {t[p][1] for p in pids if p in t and t[p][1] in pids}
    for g in gruppi:
        try:
            os.killpg(g, sig)
        except (ProcessLookupError, PermissionError):
            pass
    for p in pids:
        if p in t and t[p][1] not in gruppi:
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass


def ferma_albero(marca: bytes, radice: int | None = None, log=None, figlio=None) -> list[int]:
    ""





    def _radice() -> int | None:
        if figlio is not None:
            return figlio.pid if figlio.poll() is None else None
        return radice

    for sig, attesa in SCALA:
        pids = albero(_radice(), marca)
        if not pids:
            return []
        if sig == signal.SIGTERM:

            _segnala(pids, signal.SIGCONT)
        if log is not None:
            log.write(f"── stopping: {signal.Signals(sig).name} to {len(pids)} processes of the run\n")
            log.flush()
        _segnala(pids, sig)
        fine = time.monotonic() + attesa
        while time.monotonic() < fine:
            if not albero(_radice(), marca):
                return []
            time.sleep(0.5)
    return sorted(albero(_radice(), marca))





def _battito(percorso: Path, t0_muro: float, t0_mono: float, figlio_pid: int) -> None:
    dormito = max(0.0, (time.time() - t0_muro) - (time.monotonic() - t0_mono))
    tmp = percorso.with_name(percorso.name + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "ts": _adesso(),
                "custode": os.getpid(),
                "figlio": figlio_pid,
                "dormito_s": round(dormito),
            }
        )
    )
    os.replace(tmp, percorso)


def main() -> int:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print((__doc__ or "").strip())
        return 0
    if len(sys.argv) < 5 or "--" not in sys.argv:
        print((__doc__ or "").strip(), file=sys.stderr)
        return 2
    run_id, cartella = sys.argv[1], Path(sys.argv[2])
    cmd = sys.argv[sys.argv.index("--") + 1 :]
    log_path = cartella / f"{run_id}.log"
    richiesta = cartella / f"{run_id}.ferma"
    battito = cartella / f"{run_id}.battito"
    marca = f"SBK_RUN_ID={run_id}".encode()



    fd = os.environ.pop("SBK_RUN_LOCK_FD", "")
    lock_fh = os.fdopen(int(fd), "a") if fd.isdigit() else LOCK.open("a")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"── not started {datetime.now():%d/%m %H:%M:%S} · another run of the app is already going\n"
            )
        _registra({"run_id": run_id, "fine": _adesso(), "rc": 75, "esito": "non_partito"})
        return 75



    try:
        subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass
    file_aperti = _alza_file_aperti()


    fermare: dict[str, str | None] = {"perche": None}

    def _segnale(sig, _frame) -> None:
        fermare["perche"] = fermare["perche"] or f"signal {signal.Signals(sig).name} to the custodian"

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, _segnale)

    env = dict(os.environ, SBK_RUN_ID=run_id, SBK_RUN_DIR=str(cartella), PYTHONUNBUFFERED="1")
    t0_muro, t0_mono = time.time(), time.monotonic()
    fermato = None
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"── start {datetime.now():%d/%m %H:%M:%S} · {' '.join(cmd)}\n")


        log.write(
            f"── environment · python {platform.python_version()} · LANG {env.get('LANG', 'absent')}"
            f" · open files {file_aperti}\n"
        )
        log.flush()
        try:

            figlio = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                process_group=0,
            )
        except OSError as e:
            log.write(f"── not started: {e}\n")
            _registra({"run_id": run_id, "fine": _adesso(), "rc": 127, "esito": "non_partito"})
            return 127
        prossimo = 0.0
        while (rc := figlio.poll()) is None:
            if fermare["perche"] is None and richiesta.exists():
                fermare["perche"] = "your request via the app"
            if fermare["perche"] and fermato is None:
                fermato = fermare["perche"]
                log.write(f"── stop requested {datetime.now():%d/%m %H:%M:%S} ({fermato})\n")
                log.flush()
                ferma_albero(marca, log=log, figlio=figlio)
                continue
            if time.monotonic() >= prossimo:
                _battito(battito, t0_muro, t0_mono, figlio.pid)
                prossimo = time.monotonic() + BATTITO_S
            try:
                figlio.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

        rimasti = sorted(albero(None, marca))
        if rimasti and fermato:
            rimasti = ferma_albero(marca, log=log)
        muro = time.time() - t0_muro
        dormito = max(0.0, muro - (time.monotonic() - t0_mono))
        coda = [f"exit {rc}", _durata(muro)]
        if dormito >= 60:
            coda.append(f"the Mac slept {_durata(dormito)}")
        if fermato:
            coda.append(f"stopped: {fermato}")
        if rimasti:
            coda.append(f"still alive: {len(rimasti)} processes")
        log.write(f"── end {datetime.now():%d/%m %H:%M:%S} · {' · '.join(coda)}\n")
    _registra(
        {
            "run_id": run_id,
            "fine": _adesso(),
            "rc": rc,
            "fermato": fermato,
            "durata_s": round(muro),
            "dormito_s": round(dormito),
            "rimasti": rimasti,
        }
    )
    battito.unlink(missing_ok=True)
    richiesta.unlink(missing_ok=True)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
