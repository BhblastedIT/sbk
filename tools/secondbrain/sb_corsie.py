#!/usr/bin/env python3
"""Downloads one lightweight L0 source in its own lane, so sources that do not clash can download side by side."""





































from __future__ import annotations

import argparse
import ctypes
import fcntl
import importlib.util
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

_QUI = Path(__file__).resolve()
REPO = _QUI.parents[2]
TOOLS = REPO / "tools"
for _p in (TOOLS, TOOLS / "cross-source"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from sbk_config import DATA_ROOT  # noqa: E402


def _accanto(nome: str):
    ""
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(nome, _QUI.with_name(f"{nome}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod



RIPRESA = _accanto("sb_ripresa")

LOCK_DIR = DATA_ROOT / ".locks"

LOCK_RILETTURA = LOCK_DIR / "l0-rilettura.lock"






CORSIE_IN_PIU: dict[str, tuple[str, ...]] = {
    "drive": ("gdrive",),
    "slack": ("slack-index", "slack-canali", "slack-dm"),
    "clickup": ("clickup",),
}

PAUSE_S = {"lock": 120.0, "altro": 60.0}

GUARDA_S = 1.0
CAMPIONA_S = 10.0

ATTESA_FONTE_S = 30.0

GRAZIA_STOP_S = 5.0


class Fermato(Exception):
    ""


class FonteOccupata(Exception):
    ""





def carica_giro():
    ""
    nome = "xs_l0_refresh"
    mod = sys.modules.get(nome)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            nome, TOOLS / "cross-source" / "xs-l0-refresh.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[nome] = mod
        spec.loader.exec_module(mod)

    mod._esito = _esito_sicuro
    return mod


def _esito_sicuro(esiti: Path, *campi: object) -> None:
    ""




    riga = "\t".join([datetime.now().strftime("%d/%m %H:%M:%S"), *map(str, campi)]) + "\n"
    esiti.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(esiti, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, riga.encode("utf-8"))
    finally:
        os.close(fd)


def _riga_corsia(cartella: Path, *campi: object) -> None:
    ""
    _esito_sicuro(cartella / "corsie.tsv", *campi)





def _prendi(percorso: Path, *, aspetta: bool) -> int | None:
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(percorso, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if aspetta else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        return None
    os.set_inheritable(fd, False)
    return fd


def lock_fonte(sid: str) -> Path:
    return LOCK_DIR / f"l0-fonte-{sid}.lock"


def _script_vivo(script: str) -> bool:
    ""




    if not script:
        return False
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    for riga in out.splitlines():
        parti = riga.split(None, 1)
        if len(parti) < 2 or not parti[0].isdigit():
            continue
        argv = parti[1].split()
        if not argv or not Path(argv[0]).name.lower().startswith(("python", "zsh", "bash", "sh")):
            continue
        primo = next((t for t in argv[1:] if not t.startswith("-")), "")
        if Path(primo).name == script:
            return True
    return False




_LIBC = ctypes.CDLL("/usr/lib/libSystem.dylib", use_errno=True)


_RUSAGE_V4, _PICCO_DI_VITA = 4, 30


def picco_di_vita(pid: int) -> int:
    ""
    buf = (ctypes.c_uint64 * 64)()
    if _LIBC.proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(_RUSAGE_V4), ctypes.byref(buf)) != 0:
        return 0
    return int(buf[_PICCO_DI_VITA])


def _picco_albero(pid: int, visti: dict[int, int]) -> None:
    ""
    from sbk_resources import descendants

    for p in (pid, *descendants(pid)):
        visti[p] = max(visti.get(p, 0), picco_di_vita(p))


def _misure_picchi(cartelle: list[Path]) -> dict[str, float]:
    ""
    picchi: dict[str, float] = {}
    for c in cartelle:
        f = c / "corsie.tsv"
        if not f.is_file():
            continue
        for riga in f.read_text(encoding="utf-8", errors="replace").splitlines():
            campi = riga.split("\t")
            if len(campi) >= 7 and campi[6].replace(".", "", 1).isdigit():
                picchi[campi[2]] = max(picchi.get(campi[2], 0.0), float(campi[6]))
    return picchi


def bisogno(passi: list[str], picchi: dict[str, float]) -> float:
    ""




    from sbk_resources import total_ram_bytes

    mb = max((picchi[p] for p in passi if p in picchi), default=0.0)
    if not mb:
        return 0.02
    return max(0.01, mb * 1.25 * 1024**2 / total_ram_bytes())


def ammetti_lease(nome: str, need_frac: float):
    ""
    from sbk_resources import Lease

    lz = Lease(f"l0-corsia-{nome}", need_frac=need_frac, klass="batch")
    return lz if lz.acquire() else None


class _SenzaLease:
    def release(self) -> None:
        pass


def ammetti_pressione(nome: str, need_frac: float):
    ""






    from sbk_resources import SEG_OK, pressure

    return _SenzaLease() if pressure().seg_ratio < SEG_OK else None


def ammetti_lease_o_pressione(nome: str, need_frac: float):
    ""






    return ammetti_lease(nome, need_frac) or ammetti_pressione(nome, need_frac)




_SCALA_STOP = ((signal.SIGINT, 30), (signal.SIGTERM, 15), (signal.SIGKILL, 5))
_SCALA_TIMEOUT = ((signal.SIGTERM, 60), (signal.SIGKILL, 60))


def _chiudi_gruppo(proc: subprocess.Popen, scala) -> None:
    ""
    for sig, attesa in scala:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=attesa)
            return
        except subprocess.TimeoutExpired:
            continue


def _lancia(
    cmd: list[str], f, timeout_s: int, stop: threading.Event, cwd: Path
) -> tuple[int | None, float]:
    ""




    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, start_new_session=True
    )
    fine = time.monotonic() + timeout_s
    prossimo = 0.0
    visti: dict[int, int] = {}
    try:
        while True:
            if time.monotonic() >= prossimo:
                _picco_albero(proc.pid, visti)
                prossimo = time.monotonic() + CAMPIONA_S
            try:
                rc = proc.wait(timeout=GUARDA_S)
                mb = sum(visti.values()) / 1024**2
                return (None if stop.is_set() and rc != 0 else rc), mb
            except subprocess.TimeoutExpired:
                pass
            if stop.is_set():


                try:
                    rc = proc.wait(timeout=GRAZIA_STOP_S)

                    return (None if rc != 0 else rc), sum(visti.values()) / 1024**2
                except subprocess.TimeoutExpired:
                    _chiudi_gruppo(proc, _SCALA_STOP)
                return None, sum(visti.values()) / 1024**2
            if time.monotonic() >= fine:
                _chiudi_gruppo(proc, _SCALA_TIMEOUT)
                return 124, sum(visti.values()) / 1024**2
    except BaseException:

        _chiudi_gruppo(proc, _SCALA_STOP)
        raise


def esegui_in_corsia(
    L0R,
    passo,
    cartella: Path,
    corsia: str,
    stop: threading.Event,
    *,
    py: list[str],
    cwd: Path,
    rc_ok: tuple[int, ...] = (0,),
    pause: dict[str, float] | None = None,
    aspetta_fonte: bool = True,
) -> bool:
    ""




    pause = pause or PAUSE_S
    nome, cmd = passo.nome, [*py, *passo.args]
    esiti = cartella / "esiti.tsv"
    log = cartella / "log" / f"{nome}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    script = Path(passo.args[0]).name if passo.args else ""


    if RIPRESA.aspetta_se_in_pausa(cartella, nome, _esito_sicuro, stop=stop):
        raise Fermato

    fd = None
    detto = False
    while fd is None:
        if stop.is_set():
            raise Fermato
        fd = _prendi(lock_fonte(passo.sorgente), aspetta=False)
        if fd is not None and _script_vivo(script):
            os.close(fd)
            fd = None
        if fd is not None:
            break
        if not aspetta_fonte:
            raise FonteOccupata(passo.sorgente)
        if not detto:
            _esito_sicuro(
                esiti, nome, "attesa", f"{passo.sorgente} is being downloaded by another process"
            )
            detto = True
        if stop.wait(ATTESA_FONTE_S):
            raise Fermato
    try:
        for tentativo in (1, 2, 3):
            if stop.is_set():
                raise Fermato

            if tentativo > 1 and RIPRESA.aspetta_se_in_pausa(
                cartella, nome, _esito_sicuro, stop=stop
            ):
                raise Fermato
            t0 = time.time()
            inizio = log.stat().st_size if log.exists() else 0
            with log.open("a", encoding="utf-8") as f:
                f.write(
                    f"── attempt {tentativo} · {datetime.now():%d/%m %H:%M:%S} · {' '.join(cmd)}\n"
                )
                f.flush()
                try:
                    rc, picco = _lancia(cmd, f, passo.timeout_s, stop, cwd)
                except BaseException:
                    _esito_sicuro(
                        esiti,
                        nome,
                        f"attempt.{tentativo}",
                        L0R.DIARIO_INTERROTTO,
                        f"{int(time.time() - t0)}s",
                    )
                    raise
            durata = f"{int(time.time() - t0)}s"
            if rc is None:
                _esito_sicuro(esiti, nome, f"attempt.{tentativo}", L0R.DIARIO_INTERROTTO, durata)
                _riga_corsia(
                    cartella,
                    corsia,
                    nome,
                    f"attempt.{tentativo}",
                    L0R.DIARIO_INTERROTTO,
                    durata,
                    f"{picco:.0f}",
                )
                raise Fermato
            nota = ""
            if rc == 2 and 2 in rc_ok and not L0R._ingest_chiuso(log, inizio):
                nota = "rc 2 but the outcome is not only warnings (stages vanished or seriously skipped)"
            _esito_sicuro(esiti, nome, f"attempt.{tentativo}", f"rc={rc}", durata, nota)
            _riga_corsia(
                cartella, corsia, nome, f"attempt.{tentativo}", f"rc={rc}", durata, f"{picco:.0f}"
            )
            if rc in rc_ok and not nota:
                return True
            if tentativo < 3 and stop.wait(pause["lock"] if rc == 75 else pause["altro"]):
                raise Fermato
        _esito_sicuro(esiti, nome, "NOT CLOSED AFTER 3 ATTEMPTS")
        return False
    finally:
        os.close(fd)





def corsie_del_piano(piano: list) -> tuple[list, dict[str, list]]:
    ""
    assegnati = {n: c for c, passi in CORSIE_IN_PIU.items() for n in passi}
    extra: dict[str, list] = {c: [] for c in CORSIE_IN_PIU}
    base = []
    for p in piano:
        (extra[assegnati[p.nome]] if p.nome in assegnati else base).append(p)
    return base, {c: ps for c, ps in extra.items() if ps}


def scarica(
    L0R,
    cartella: Path,
    piano: list,
    *,
    stop: threading.Event | None = None,
    py: list[str] | None = None,
    cwd: Path | None = None,
    ammetti: Callable[[str, float], object | None] = ammetti_lease_o_pressione,
    pause: dict[str, float] | None = None,
) -> list[str]:
    ""





    stop = stop or threading.Event()
    py = py or list(L0R.PY)
    cwd = cwd or L0R.ROOT
    (cartella / "log").mkdir(parents=True, exist_ok=True)
    esiti = cartella / "esiti.tsv"
    ordine = {p.nome: i for i, p in enumerate(piano)}
    base, extra = corsie_del_piano(piano)
    picchi = _misure_picchi(sorted(cartella.parent.iterdir()) if cartella.parent.exists() else [])

    leases: list = []
    corsie: list[tuple[str, list]] = []
    for nome, passi in extra.items():
        lz = ammetti(nome, bisogno([p.nome for p in passi], picchi))
        if lz is None:
            base.extend(passi)
            _esito_sicuro(
                esiti, f"corsia:{nome}", L0R.DIARIO_NON_PARTITA,
                "memory under pressure and no room in the shared budget: its steps go to the base",
            )
            continue
        leases.append(lz)
        corsie.append((nome, passi))
    base.sort(key=lambda p: ordine[p.nome])
    corsie.insert(0, ("base", base))
    for nome, passi in corsie:
        _esito_sicuro(esiti, f"corsia:{nome}", ", ".join(p.nome for p in passi))

    non_chiusi: list[str] = []
    mutex = threading.Lock()
    finite = threading.Event()
    vive = [len(corsie)]

    def corri(nome: str, passi: list) -> None:
        fatti = 0
        try:
            fd = _prendi(LOCK_DIR / f"l0-corsia-{nome}.lock", aspetta=False)
            if fd is None:
                _esito_sicuro(
                    esiti,
                    f"corsia:{nome}",
                    L0R.DIARIO_NON_PARTITA,
                    "the same lane is already running in another process",
                )
                with mutex:
                    non_chiusi.extend(p.nome for p in passi)
                return
            try:
                for p in passi:
                    ok = esegui_in_corsia(L0R, p, cartella, nome, stop, py=py, cwd=cwd, pause=pause)
                    fatti += 1
                    if not ok:
                        with mutex:
                            non_chiusi.append(p.nome)
            except Fermato:
                with mutex:
                    non_chiusi.extend(p.nome for p in passi[fatti:])
            except Exception as e:  # noqa: BLE001 — a broken lane declares itself, the others go on
                _esito_sicuro(
                    esiti, f"corsia:{nome}", "ERRORE", f"{type(e).__name__}: {str(e)[:200]}"
                )
                with mutex:
                    non_chiusi.extend(p.nome for p in passi[fatti:])
            finally:
                os.close(fd)
        finally:
            with mutex:
                vive[0] -= 1
                if not vive[0]:
                    finite.set()

    for c in corsie:
        threading.Thread(target=corri, args=c, name=f"corsia-{c[0]}", daemon=True).start()
    try:
        while not finite.wait(
            0.5
        ):
            pass
    except KeyboardInterrupt:
        stop.set()
        _aspetta_corsie(finite)
        raise
    finally:
        for lz in leases:
            with suppress(Exception):
                lz.release()
    return sorted(set(non_chiusi), key=lambda n: ordine.get(n, len(ordine)))


def _aspetta_corsie(finite: threading.Event) -> None:
    ""





    while True:
        try:
            if finite.wait(0.5):
                return
        except KeyboardInterrupt:
            continue


@contextmanager
def fonti_ferme(L0R, cartella: Path, stop: threading.Event | None = None):
    ""





    stop = stop or threading.Event()
    presi: list[int] = []
    try:
        presi.append(_prendi(LOCK_RILETTURA, aspetta=True))
        for sid in sorted({p.sorgente for p in L0R.PIANO}):
            detto = False
            while (fd := _prendi(lock_fonte(sid), aspetta=False)) is None:
                if not detto:
                    _esito_sicuro(
                        cartella / "esiti.tsv", "rilettura", "attesa", f"{sid} is being downloaded"
                    )
                    detto = True
                if stop.wait(ATTESA_FONTE_S):
                    raise KeyboardInterrupt
            presi.append(fd)
        yield
    finally:
        for fd in presi:
            os.close(fd)








LEGGERE = frozenset(
    {
        "calendar",
        "email",
        "personio",
        "whoop",
        "plaud",
        "tactiq",
        "docusign",
        "github",
        "gsc",
        "analytics",
    }
)


def scarica_fonte(
    L0R, sid: str, cartella: Path, *, stop: threading.Event | None = None, ammetti=ammetti_lease_o_pressione,
    py: list[str] | None = None, cwd: Path | None = None, piano: list | None = None,
) -> int:
    ""

    stop = stop or threading.Event()
    passi = [p for p in (piano or L0R.PIANO) if p.sorgente == sid]
    if not passi or sid not in LEGGERE:
        print(f"⛔ {sid}: not a lightweight source of the run (LEGGERE)")
        return 2
    esiti = cartella / "esiti.tsv"
    ril = _prendi(LOCK_RILETTURA, aspetta=False)
    if ril is None:
        print("⛔ the full run is re-reading: the source downloads when it has finished")
        return 75
    os.close(
        ril
    )
    lz = ammetti(f"fonte-{sid}", bisogno([p.nome for p in passi], _misure_picchi([cartella])))
    if lz is None:
        print(
            "⛔ no memory for another job right now (shared budget): try again later"
        )
        return 75
    try:
        _esito_sicuro(esiti, "START", f"{len(passi)} steps", f"L0 only, source {sid}")
        chiusi = []
        try:
            for p in passi:
                chiusi.append(
                    esegui_in_corsia(
                        L0R,
                        p,
                        cartella,
                        f"fonte-{sid}",
                        stop,
                        py=py or list(L0R.PY),
                        cwd=cwd or L0R.ROOT,
                        aspetta_fonte=False,
                    )
                )
        except FonteOccupata:
            _esito_sicuro(
                esiti,
                L0R.DIARIO_FINE,
                L0R.DIARIO_NON_PARTITO,
                f"{sid} is already being downloaded by another process",
            )
            print(f"⛔ {sid} is already being downloaded by the full run or another process")
            return 75
        except (Fermato, KeyboardInterrupt):
            _esito_sicuro(esiti, L0R.DIARIO_FINE, L0R.DIARIO_FERMATO, "not closed: " + sid)
            return 130
        non = [p.nome for p, ok in zip(passi, chiusi, strict=False) if not ok]
        _esito_sicuro(esiti, "END", "not closed: " + (", ".join(non) or "none"))
        return 1 if non else 0
    finally:
        with suppress(Exception):
            lz.release()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Download one lightweight source"])[0]
    )
    ap.add_argument(
        "--fonte", required=True, help="registry id (tools/sorgenti.py), a lightweight source"
    )
    ap.add_argument("--dir", type=Path, required=True, help="diary folder for this download")
    a = ap.parse_args()

    signal.signal(signal.SIGTERM, lambda _s, _f: (_ for _ in ()).throw(KeyboardInterrupt()))
    stop = threading.Event()
    try:
        return scarica_fonte(carica_giro(), a.fonte, a.dir, stop=stop)
    except KeyboardInterrupt:
        stop.set()
        return 130


if __name__ == "__main__":
    sys.exit(main())
