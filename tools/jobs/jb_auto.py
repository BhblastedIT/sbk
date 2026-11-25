#!/usr/bin/env python3
""









































































from __future__ import annotations

import atexit
import os
import signal
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))



_STATO = {
    "job": None,
    "outcome": None,
    "detail": "",
    "chiuso": False,
    "dichiarato": False,
    "esploso": False,
    "a_mano": False,

    "fermato": "",

    "t0": 0.0,
}


def _scrivi(phase: str, outcome: str | None = None, detail: str = "") -> None:
    try:
        from jb_model import Event, append_event

        if _STATO["a_mano"]:
            detail = (detail + " [manual]").strip()
        append_event(Event(job=_STATO["job"], phase=phase, outcome=outcome, detail=detail[:400]))
    except Exception:  # noqa: BLE001 -- the registry must not break the work
        pass


def esito(outcome: str, detail: str = "") -> None:
    ""









    _STATO["outcome"] = outcome
    _STATO["detail"] = detail
    _STATO["dichiarato"] = True


def _chiudi() -> None:
    if _STATO["chiuso"] or not _STATO["job"]:
        return
    _STATO["chiuso"] = True
    detail = _STATO["detail"]
    if _STATO["dichiarato"]:
        outcome = _STATO["outcome"]
    elif _STATO["fermato"]:


        outcome, detail = "skipped", _STATO["fermato"]
    elif _STATO["esploso"]:
        outcome = "failed"
    else:

        outcome = "unknown"
        detail = detail or "ran and did not declare how it went"
    _scrivi("end", outcome, detail)


def _hook(tipo, valore, tb) -> None:
    _STATO["esploso"] = True
    if not _STATO["detail"]:
        _STATO["detail"] = f"{tipo.__name__}: {valore}"[:400]
    sys.__excepthook__(tipo, valore, tb)


def _motivo_segnale(num: int, job: str | None, t0: float) -> tuple[str, str]:
    ""





    try:
        from jb_model import fermato_da_fuori, motivo_stop, nome_segnale
    except Exception:  # noqa: BLE001 -- without the model we stay on the old one
        return "failed", f"killed by signal {num}"
    nome = nome_segnale(num)
    if fermato_da_fuori(num):
        motivo = motivo_stop(job, t0) if job else ""
        if motivo:
            return "skipped", f"stopped by {nome}: {motivo}"
        return "skipped", (
            f"stopped by {nome} (by hand, launchctl, logout or shutdown): "
            "not done, the next slot catches up"
        )
    return "failed", f"killed by {nome} (crash; SIGKILL is often memory)"


def _segnale(num, _frame):
    ""




    try:
        esito_s, motivo = _motivo_segnale(num, _STATO["job"], _STATO["t0"])
    except Exception:  # noqa: BLE001 -- the registry must not break the work
        esito_s, motivo = "failed", f"killed by signal {num}"
    if esito_s == "skipped":
        _STATO["fermato"] = motivo
    else:
        _STATO["esploso"] = True
        _STATO["detail"] = _STATO["detail"] or motivo
    _chiudi()
    signal.signal(num, signal.SIG_DFL)
    os.kill(os.getpid(), num)


def _a_mano() -> bool:
    ""















    import os as _os

    return bool(_os.environ.get("TERM") or _os.environ.get("SSH_TTY"))


def aggancia(job: str) -> None:
    ""
    if _STATO["job"]:
        return



    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        return
    _STATO["a_mano"] = _a_mano()
    _STATO["job"] = job
    _STATO["t0"] = time.time()
    _scrivi("start")
    atexit.register(_chiudi)
    sys.excepthook = _hook
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(s, _segnale)
        except (ValueError, OSError):
            pass


def uscita(codice) -> None:
    ""





    try:
        if _STATO["dichiarato"] or codice is None or codice == 0 or codice is False:
            return
        _STATO["esploso"] = True
        if isinstance(codice, int):
            motivo = f"exit code {int(codice)}"
        else:

            motivo = f"exit code 1: {codice}"
        _STATO["detail"] = (_STATO["detail"] or motivo)[:400]
    except Exception:  # noqa: BLE001 -- the registry must not break the work
        pass


if __name__ == "__main__":


    aggancia("com.sbk.PROVA-jb-auto")
    if "--esplodi" in sys.argv:
        raise RuntimeError("deliberate crash")
    esito("ok", "test passed")
    print("ok", file=sys.stderr)
    _ = traceback
