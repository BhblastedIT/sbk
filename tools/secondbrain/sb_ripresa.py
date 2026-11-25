#!/usr/bin/env python3
""






























from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path



PAUSA_OGNI_S = 2.0


VIVO_SE_SEGNO_ENTRO_S = 15 * 60


def file_pausa(cartella: Path, run_id: str | None = None) -> Path:
    ""



    rid = run_id if run_id is not None else os.environ.get("SBK_RUN_ID", "")
    return cartella / (f"{rid}.pausa" if rid else "pausa")


def aspetta_se_in_pausa(
    cartella: Path,
    prima_di: str,
    scrivi: Callable[..., None],
    *,
    stop=None,
    ogni_s: float | None = None,
) -> bool:
    ""





    f = file_pausa(cartella)
    if not f.exists():
        return False
    ogni_s = PAUSA_OGNI_S if ogni_s is None else ogni_s
    esiti = cartella / "esiti.tsv"
    t0 = time.time()
    scrivi(esiti, "PAUSA", "paused", f"before {prima_di}")
    while f.exists():
        if stop is not None:
            if stop.wait(ogni_s):
                return True
        else:
            time.sleep(ogni_s)
    scrivi(esiti, "PAUSA", "resumed", f"before {prima_di}", f"{int(time.time() - t0)}s")
    return False





COPIE = Path.home() / ".sbk-backups"


SUFFISSO_INTERROTTA = ".interrotta"


def copia_del_cervello(L0R, cartella: Path, copie: Path | None = None) -> bool:
    ""






    copie = copie or COPIE
    t0 = time.time()
    try:
        return L0R.backup_kb(cartella)
    except BaseException:
        esiti = cartella / "esiti.tsv"
        trovate = (
            [*copie.glob("knowledge-*.tar.gz.parziale"), *copie.glob("knowledge-*.tar.gz")]
            if copie.exists()
            else []
        )
        for f in trovate:
            try:
                nuova = f.stat().st_mtime >= t0 - 1
            except OSError:
                continue
            if not nuova:
                continue
            if f.name.endswith(".parziale"):


                L0R._esito(esiti, "backup-kb", "INTERROTTO", f"half copy left in {f.name}")
            elif _copia_intera(f):

                L0R._esito(esiti, "backup-kb", "stopped after the copy", f"{f.name} whole")
            else:
                f.rename(f.with_name(f.name + SUFFISSO_INTERROTTA))
                L0R._esito(esiti, "backup-kb", "INTERROTTO", f.name + SUFFISSO_INTERROTTA)
        raise


def _copia_intera(f: Path) -> bool:
    ""
    try:
        return (
            subprocess.run(["gzip", "-t", str(f)], capture_output=True, timeout=300).returncode == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False





def _blocco(diario: Path) -> list[list[str]]:
    ""

    try:
        righe = diario.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    campi = [r.split("\t") for r in righe if r.strip()]
    inizi = [i for i, c in enumerate(campi) if len(c) > 1 and c[1].startswith("INIZIO")]
    return campi[inizi[-1] :] if inizi else campi


def _passo_chiuso(c: list[str], nome: str) -> bool:
    ""
    if len(c) < 3 or c[1] != nome:
        return False
    if c[2] == "ripreso":
        return True
    return c[2].startswith("tent.") and len(c) > 3 and c[3] == "rc=0"


def _finale_chiuso(c: list[str], finale: str) -> bool:
    ""

    if len(c) < 4 or c[1] != finale or not c[2].startswith("tent."):
        return False
    rc = c[3].removeprefix("rc=")
    return rc == "0" or (rc == "2" and not (len(c) > 5 and c[5]))


@dataclass
class Giro:
    ""

    cartella: Path
    trovato: bool = False
    testa: list[str] = field(default_factory=list)
    modo: str | None = None
    spesa: str | None = None

    chiusi: dict[str, str] = field(default_factory=dict)
    backup_chiuso: bool = False
    finale_chiuso: bool = False
    fine: list[str] | None = None

    ultimo_segno_s: float | None = None

    @property
    def fermato(self) -> bool:
        return bool(self.fine) and len(self.fine) > 2 and self.fine[2] == "FERMATO"

    @property
    def senza_fine(self) -> bool:
        return self.fine is None

    def forse_vivo(self) -> bool:
        return self.senza_fine and (self.ultimo_segno_s or 0) < VIVO_SE_SEGNO_ENTRO_S

    def da_rifare(self, piano: Iterable) -> list:
        return [p for p in piano if p.nome not in self.chiusi]

    def non_chiusi(self, nomi: Iterable[str], finale: str | None) -> list[str]:
        ""
        fuori = [n for n in nomi if n not in self.chiusi]
        if finale:
            if not self.backup_chiuso and not self.finale_chiuso:
                fuori.append("backup-kb")
            if not self.finale_chiuso:
                fuori.append(finale)
        return fuori


def leggi_giro(cartella: Path, nomi: Iterable[str], finale: str | None = None) -> Giro:
    ""



    g = Giro(cartella=cartella)
    diario = cartella / "esiti.tsv"
    blocco = _blocco(diario)
    if not blocco:
        return g
    g.trovato = True
    g.testa = blocco[0]
    testa = "\t".join(blocco[0])
    if "solo L0" in testa:
        g.modo = None
    elif "poi-tutto" in testa:
        g.modo = "tutto"
    else:
        g.modo = "ingest"
    finale = finale or g.modo
    nomi = list(nomi)
    for c in blocco:
        if len(c) < 2:
            continue
        if c[1] == "spesa" and len(c) > 3:
            g.spesa = c[3]
        for n in nomi:
            if n not in g.chiusi and _passo_chiuso(c, n):
                g.chiusi[n] = c[0]

        if c[1] == "backup-kb" and len(c) > 2 and "rc=0" in c[2:4]:
            g.backup_chiuso = True
        if finale and _finale_chiuso(c, finale):
            g.finale_chiuso = True
        if c[1] == "FINE" or c[1].startswith("FULL RUN CONCLUSO"):
            g.fine = c
    segni = [diario, *sorted((cartella / "log").glob("*.log"))]
    tempi = [p.stat().st_mtime for p in segni if p.exists()]
    g.ultimo_segno_s = time.time() - max(tempi) if tempi else None
    return g


def da_dove_si_riprende(vecchio: Giro, piano: list, finale: str) -> dict:
    ""
    rifare = vecchio.da_rifare(piano)
    rilettura = bool(rifare) or not vecchio.finale_chiuso
    return {
        "salta": [p.nome for p in piano if p.nome in vecchio.chiusi],
        "rifa": [p.nome for p in rifare],
        "copia": rilettura,
        "rilettura": rilettura,
        "niente_da_fare": not rifare and not rilettura,
    }






_RE_RUNNING = re.compile(r"RUNNING: (?P<nome>.+?)(?: \((?P<script>[^ )]+\.py)[^)]*\))?\s*$")
_RE_OK = re.compile(r"^\S+ INFO\s+OK in [\d.]+s")

# A skipped stage in the plan: "— SKIPPED (not chosen)" now, "— SALTATO (non_scelto)" in older logs.
_RE_SALTATO = re.compile(
    r"– (?P<nome>.+?)(?: \[PAID\].*?)? — (?:SKIPPED|SALTATO) \((?P<motivo>[^)]+)\)"
)
# Skip reasons that still count as closed: the English labels and the internal codes.
_SALTI_CHIUSI = ("not chosen", "resumed", "non_scelto", "ripreso")


def orchestratore_sa_riprendere(orchestratore: Path) -> bool:
    ""
    try:
        testo = orchestratore.read_text(encoding="utf-8", errors="replace")
        return "--resume-from" in testo or "--riprendi-da" in testo
    except OSError:
        return False


def orchestratore_sa_la_pausa(orchestratore: Path) -> bool:
    ""
    try:
        return "_aspetta_pausa" in orchestratore.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def punto_di_ripresa(log: Path, catena: list[tuple[str, str]]) -> str | None:
    ""








    try:
        testo = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # The last attempt: "── attempt N" now, "── tentativo N" in older logs.
    inizio = max(testo.rfind(m) for m in ("── attempt ", "── tentativo "))
    blocco = testo[inizio:] if inizio >= 0 else testo
    if not any(x in blocco for x in ("=== L1 Complete", "=== Resume from ", "=== Ripresa da ")):
        return None
    chiusi: set[str] = set()
    corrente = None
    for riga in blocco.splitlines():
        if m := _RE_RUNNING.search(riga):
            corrente = m["nome"].strip()
        elif corrente and _RE_OK.search(riga):
            chiusi.add(corrente)
            corrente = None
        elif (m := _RE_SALTATO.search(riga)) and m["motivo"] in _SALTI_CHIUSI:
            chiusi.add(m["nome"].strip())
    return next((sid for sid, nome in catena if nome not in chiusi), None)








FERMA: dict[str, str] = {
    "scarico": (
        "The downloads in progress stop and next time they start over. Those already finished stay. "
        "The brain is not touched. With Resume you restart from where you were."
    ),
    "drive": (
        "Drive keeps what it has already downloaded up to the last minute. Next time it redoes the file list "
        "and skips the ones it already has."
    ),
    "copia": (
        "The safety copy stops and the half-done one is not valid, I set it aside under a different name. "
        "The brain was not touched. With Resume the copy is redone."
    ),
    "rilettura": (
        "The re-read stops where it is. What it has already done stays, but the brain may stay half-updated "
        "until you redo it. With Resume, if the downloads had all closed, the re-read restarts from the "
        "step where it stopped. Otherwise it redoes the missing downloads and then the re-read from scratch."
    ),
    "pagato_invio": (
        "It is sending the paid batches. If you stop it now, the batches already sent are paid and next time "
        "they are paid again. Wait until the batches are saved, it takes a moment."
    ),
    "in_pausa": (
        "On pause nothing is running, so stopping does not interrupt any step. With Resume you restart from here."
    ),
    "pagato_attesa": (
        "The paid batches are already paid and work on Anthropic even if you stop here. With Resume they are collected "
        "without paying again. But first do not download anything, otherwise the answers can end up on the wrong "
        "documents."
    ),
}

PAUSA: dict[str, str] = {
    "scarico": (
        "The downloads in progress finish, then everything stops. On pause nothing runs and memory stays free. "
        "The Mac stays awake until you continue or stop."
    ),
    "copia": (
        "The safety copy finishes, then the re-read waits for you to continue. On pause nothing runs."
    ),
    "rilettura": (
        "During the re-read there is no pause, because the re-read cannot stop halfway and restart. "
        "You can wait for it to finish or stop it."
    ),

    "rilettura_con_gancio": (
        "The stage in progress finishes, then the re-read waits for you to continue. A long stage can take "
        "quite a while to finish."
    ),
    "pagato": (
        "During paid extraction the pause would come only when the batches return, even after hours. "
        "If the batches are saved you can stop without losing anything."
    ),
    "non_full": "The pause exists only in the two full runs. This run can only be stopped.",
}


def frase_in_pausa(fonti: list[str], dal: str, attivi: list[str] | None = None) -> str:
    ""


    if attivi:
        verbo = "finishes" if len(attivi) == 1 else "finish"
        return f"The pause comes when {_elenco(attivi)} {verbo}."
    ora = dal.split(" ")[-1][:5] if dal else ""
    return (
        f"Paused before {_elenco(fonti)}"
        + (f", from {ora}" if ora else "")
        + ". Continue whenever you want."
    )


def frase_ripresa(
    salta: int, fonti: list[str], rilettura: bool, quando: str, ore: float | None
) -> str:
    ""
    pezzi = [f"Resumes the run stopped {quando}."]
    if salta and fonti:
        pezzi.append(
            f"Skips {salta} already-closed downloads and redoes those of {_elenco(fonti, 'sources')}."
        )
    elif salta:
        pezzi.append(f"Skips {salta} already-closed downloads.")
    elif fonti:
        pezzi.append(f"Redoes the downloads of {_elenco(fonti, 'sources')}.")
    if rilettura:
        pezzi.append("Then makes a new brain copy and re-reads.")
    if ore is not None and ore > 24:
        pezzi.append(
            "The downloads it skips are more than a day old; for fresh data a new full run is better."
        )
    return " ".join(pezzi)


def _elenco(nomi: list[str], cosa: str = "") -> str:
    ""

    nomi = list(dict.fromkeys(nomi))
    if not nomi:
        return ""
    if len(nomi) <= 4:
        return nomi[0] if len(nomi) == 1 else ", ".join(nomi[:-1]) + " and " + nomi[-1]
    return f"{', '.join(nomi[:3])} and {len(nomi) - 3} more {cosa or ''}".rstrip()
