""












from __future__ import annotations

import atexit
import fcntl
import json
import os
import struct
import sys
from datetime import datetime
from pathlib import Path

from sbk_config import DATA_ROOT


LOCK_RUN_APP = DATA_ROOT / "system" / "secondbrain-run.lock"

LOCKS_PIPELINE = ("pipeline-run", "l0-refresh")
NOMI = {"pipeline-run": "a re-read of the pipeline", "l0-refresh": "the download run"}


def tenuto(percorso: Path) -> bool:
    ""
    if not percorso.exists():
        return False
    richiesta = struct.pack("qqihh", 0, 0, 0, fcntl.F_WRLCK, os.SEEK_SET)
    try:
        with percorso.open("rb") as fh:
            risposta = fcntl.fcntl(fh, fcntl.F_GETLK, richiesta)
    except OSError:
        return False
    return struct.unpack("qqihh", risposta)[3] != fcntl.F_UNLCK


def pid_del_lock(nome: str) -> int | None:
    ""
    try:
        testo = (DATA_ROOT / f"{nome}.pid").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(testo) if testo.isdigit() else None


def chi_gira(
    *, app: bool = True, locks: tuple[str, ...] = LOCKS_PIPELINE, salta: frozenset = frozenset()
) -> list[str]:
    ""
    chi = []
    if app and tenuto(LOCK_RUN_APP):
        try:
            dentro = json.loads(LOCK_RUN_APP.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            dentro = {}
        chi.append(f"a run of the SBK app ({dentro.get('etichetta') or 'run'})")
    for nome in locks:
        if not tenuto(DATA_ROOT / ".locks" / f"{nome}.lock"):
            continue
        pid = pid_del_lock(nome)
        if pid is not None and pid in salta:
            continue
        chi.append(f"{NOMI.get(nome, nome)} (lock {nome}, pid {pid if pid is not None else '?'})")
    return chi







DIARIO = DATA_ROOT / "system" / "runs-da-terminale.jsonl"
_APERTI: set[str] = set()


def _scrivi(voce: dict) -> None:
    try:
        DIARIO.parent.mkdir(parents=True, exist_ok=True)
        with DIARIO.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps(voce, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _adesso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def diario_inizio(
    tipo: str, argv: list[str] | None = None, cartella: str | None = None
) -> str | None:
    ""





    if os.environ.get("SBK_RUN_ID"):
        return None
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{tipo}-{os.getpid()}"
    _scrivi(
        {
            "run_id": run_id,
            "tipo": tipo,
            "pid": os.getpid(),
            "argomenti": list((sys.argv if argv is None else argv)[1:]),
            "cartella": cartella,
            "giro_pid": os.environ.get("SBK_GIRO_PID"),
            "inizio": _adesso(),
            "fine": None,
        }
    )
    _APERTI.add(run_id)
    atexit.register(diario_fine, run_id, None)
    return run_id


def diario_fine(run_id: str | None, rc: int | None) -> None:
    ""
    if run_id and run_id in _APERTI:
        _APERTI.discard(run_id)
        _scrivi({"run_id": run_id, "fine": _adesso(), "rc": rc})
