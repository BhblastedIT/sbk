#!/usr/bin/env python3
"""Catalogue of known pipeline errors: match a step's log to a known error and say what to do.

Usage:
  sb_errori.py catalogo                  print every known error as JSON
  sb_errori.py passo RUN_FOLDER STEP     diagnose one step of a run folder
  sb_errori.py rilettura LOG             diagnose the log of a reread
"""
























from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path





AZIONI: dict[str, dict] = {
    "riprova": {
        "tipo": "l0",
        "arg": "{sorgente}",
        "etichetta": "Retry",
        "comando": "uv run python tools/secondbrain/sb-app.py lancia l0 {sorgente}",
    },
    "riprendi_drive": {
        "tipo": "l0",
        "arg": "gdrive",
        "etichetta": "Resume Drive",
        "comando": "uv run python tools/secondbrain/sb-app.py lancia l0 gdrive",
    },
    "rileggi": {
        "tipo": "modo",
        "arg": "ingest",
        "etichetta": "Re-read and update",
        "comando": "uv run python tools/secondbrain/sb-app.py lancia modo ingest",
    },
    "full_free": {
        "tipo": "full",
        "arg": "",
        "etichetta": "Full run free",
        "comando": "uv run python tools/secondbrain/sb-app.py lancia full",
    },
    "full_completa": {
        "tipo": "full_completa",
        "arg": "",
        "etichetta": "Redo the estimate",

        "comando": "uv run python tools/secondbrain/sb-app.py stima",
        "nuova": True,
    },
    "fonti_a_mano": {
        "tipo": "come_si_fa",
        "arg": "a_mano",
        "etichetta": "How to do it",
        "comando": "",
    },
    "pulisci_lock": {
        "tipo": "pulisci_lock",
        "arg": "",
        "etichetta": "Remove the leftover locks",

        "comando": "uv run python tools/util/sb-pipeline-ctl.py cleanup",
        "nuova": True,
    },
    "apri_plaud": {
        "tipo": "apri_app",
        "arg": "Plaud",
        "etichetta": "Open Plaud",
        "comando": "open -a Plaud",
        "nuova": True,
    },
    "apri_tactiq": {
        "tipo": "apri_pagina",
        "arg": "https://app.tactiq.io/",
        "etichetta": "Open Tactiq",
        "comando": "open https://app.tactiq.io/",
        "nuova": True,
    },
    "consenso_docusign": {
        "tipo": "consenso_docusign",
        "arg": "",
        "etichetta": "Open the consent",

        "comando": "uv run python tools/docusign/ds-l0-api.py --consent-url, then the address opens",
        "nuova": True,
    },
    "copia_per_claude": {
        "tipo": "copia_per_claude",
        "arg": "",




        "etichetta": "Open agent in the terminal",
        "comando": "",
        "nuova": True,
    },
}


CHI = ("app", "tu", "claude", "nessuno")

GRAVITA = ("errore", "avviso", "nota")


@dataclass(frozen=True)
class Voce:
    ""

    id: str
    passi: tuple[str, ...]

    firme: tuple[str, ...]
    causa: str
    rimedio: str
    azione: str | None = None
    chi: str = "app"

    rc: tuple[int, ...] = ()
    gravita: str = "errore"

    peso: int = 50

    ritenta: bool = False

    anche_con_rc_0: bool = False

    visto: tuple[str, ...] = ()

    nota: str = ""
    _rx: re.Pattern | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.firme:
            object.__setattr__(self, "_rx", re.compile("|".join(f"(?:{f})" for f in self.firme)))



# The catalogue below is a small synthetic sample. In a real deployment it
# grows into a diagnosis table that maps a log signature (the `firme`
# regexes) to a human cause and remedy. Each Voce is one diagnosis rule;
# add your own as you meet new failure modes.
CATALOGO: tuple[Voce, ...] = (

    Voce(
        "source-login-expired",
        ("plaud", "tactiq"),
        (
            r"login required",
            r"token refresh failed",
            r"no valid session",
        ),
        "The connector's login has expired and does not renew on its own.",
        "Open the connector's app, sign in again, then retry. The run does the rest.",
        azione="apri_plaud",
        chi="tu",
        peso=90,
        visto=("demo: observed on a source step",),
        nota="Demo entry. Point `nota` at the module and line that emits the message.",
    ),
    Voce(
        "stale-lock",
        ("ingest",),
        (
            r"lock held",
            r"another run in progress",
        ),
        "A previous run left a lock file behind.",
        "Retry once. If it persists, remove the stale lock file.",
        azione="pulisci_lock",
        chi="app",
        peso=50,
        ritenta=True,
        nota="Demo entry.",
    ),
    Voce(
        "program-error",
        ("*",),
        (
            r"^Traceback \(most recent call last\)",
            r"^[\w.]*(Error|Exception): ",
            r"Failed: \S+ \([\d.]+s\) . \w+",
        ),
        "The step stopped on a program error.",
        "Retrying will not help. A maintainer needs to look at it.",
        azione="copia_per_claude",
        chi="claude",
        peso=10,
    ),
)


PER_ID: dict[str, Voce] = {v.id: v for v in CATALOGO}


SCONOSCIUTO = Voce(
    "sconosciuto",
    ("*",),
    (),
    "The step stopped and I don't recognize the reason.",
    "Retry once. If it stops again, open the agent in the terminal from the detail.",
    azione="riprova",
    peso=0,
    ritenta=True,
)




PASSI_GIRO: tuple[str, ...] = (
    "calendar",
    "email",
    "email-allegati",
    "microsoft365",
    "imap-caldav",
    "slack-index",
    "slack-canali",
    "slack-dm",
    "attio",
    "clickup",
    "personio",
    "whoop",
    "plaud",
    "tactiq",
    "zoom",
    "docusign",
    "docusign-pdf",
    "inv-github",
    "inv-gsc",
    "inv-analytics",
    "gdrive",
)

PASSI_DOPO: tuple[str, ...] = ("backup-kb", "ingest", "tutto")

# Steps whose whole name is a source id with a dash in it (not "<source>-<part>").
_PASSO_E_SORGENTE: frozenset[str] = frozenset({"imap-caldav"})


def sorgente_del_passo(passo: str) -> str:
    ""
    if passo in _PASSO_E_SORGENTE:
        return passo
    if passo.startswith("inv-"):
        return passo[4:]
    return passo.split("-")[0]


def famiglia_del_passo(passo: str) -> str:
    ""
    if passo in PASSI_GIRO or passo.startswith("inv-"):
        return "giro"
    if passo == "backup-kb":
        return "copia"
    return "rilettura"


def _chiavi(passo: str) -> set[str]:
    famiglia = famiglia_del_passo(passo)
    chiavi = {passo, "*"}
    if famiglia == "giro":
        chiavi.add(sorgente_del_passo(passo))
    elif famiglia == "rilettura":
        chiavi.add("rilettura")
    return chiavi




# Start of one attempt in a step log: "── attempt N", or "── tentativo N" in older logs.
_MARCA_TENTATIVO = ("── attempt ", "── tentativo ")


_PULIZIA = (
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"), "<jwt>"),
    (re.compile(r"eyJ[A-Za-z0-9_\-\.]{6,}"), "<jwt>"),
    (re.compile(r"(?i)(bearer\s+)[^\s)\"']{6,}"), r"\1<x>"),
    (re.compile(r"xox[abposr]-[A-Za-z0-9\-]+"), "<slack-token>"),
    (re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]+"), "<gh-token>"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "<sk-key>"),
    (
        re.compile(
            r"(?i)(token|key|secret|password|cookie|authorization|api[_-]?key)(\s*[=:]\s*)([\"']?)[^\s\"',;}]{8,}"
        ),
        r"\1\2\3<x>",
    ),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "<lungo>"),
)


def pulisci(riga: str) -> str:
    ""
    for rx, sost in _PULIZIA:
        riga = rx.sub(sost, riga)
    return riga[:300]




_PULIZIA_REGISTRO = tuple(x for x in _PULIZIA if x[1] != "<email>")


def pulisci_registro(riga: str) -> str:
    ""
    for rx, sost in _PULIZIA_REGISTRO:
        riga = rx.sub(sost, riga)
    return riga


def _righe(righe: list[str] | str) -> list[str]:
    return righe.splitlines() if isinstance(righe, str) else list(righe)


def ultimo_tentativo(righe: list[str]) -> list[str]:
    ""
    inizi = [i for i, r in enumerate(righe) if r.startswith(_MARCA_TENTATIVO)]
    return righe[inizi[-1] :] if inizi else righe


def _coda(percorso: Path, byte: int = 2 << 20) -> list[str]:
    ""
    try:
        with percorso.open("rb") as f:
            f.seek(0, 2)
            dim = f.tell()
            f.seek(max(0, dim - byte))
            testo = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    righe = testo.splitlines()
    return righe[1:] if dim > byte else righe





def _risolvi_azione(nome: str | None, sorgente: str) -> dict | None:
    if not nome:
        return None
    a = dict(AZIONI[nome])
    a["arg"] = a["arg"].replace("{sorgente}", sorgente)
    a["comando"] = a["comando"].replace("{sorgente}", sorgente)
    a["id"] = nome
    return a


def _uscita(voce: Voce, passo: str, riga: str | None, rc: int | None) -> dict:
    famiglia = famiglia_del_passo(passo)
    sorgente = sorgente_del_passo(passo) if famiglia == "giro" else ""
    azione = voce.azione
    if azione == "riprova" and famiglia != "giro":

        azione = "rileggi"
    return {
        "id": voce.id,
        "passo": passo,
        "sorgente": sorgente,
        "causa": voce.causa,
        "rimedio": voce.rimedio,
        "azione": _risolvi_azione(azione, sorgente),
        "chi": voce.chi,
        "ritenta": voce.ritenta,
        "gravita": voce.gravita,
        "riga": pulisci(riga) if riga else None,
        "rc": rc,
        "nota": voce.nota,
    }


def _trovate(
    passo: str, righe: list[str], rc: int | None, solo: frozenset[str] | None = None
) -> list[tuple[Voce, str | None]]:
    chiavi = _chiavi(passo)
    righe = ultimo_tentativo(righe)
    fuori = []
    for voce in CATALOGO:
        if not chiavi & set(voce.passi) or (solo is not None and voce.id not in solo):
            continue
        if voce.rc and rc not in voce.rc:
            continue
        if rc == 0 and voce.gravita == "errore" and not voce.anche_con_rc_0:
            continue
        if voce._rx is None:

            if voce.rc:
                fuori.append((voce, None))
            continue
        riga = next((r for r in righe if voce._rx.search(r)), None)
        if riga is not None:
            fuori.append((voce, riga))
    fuori.sort(key=lambda t: (GRAVITA.index(t[0].gravita), -t[0].peso))
    return fuori


def tutte_le_diagnosi(passo: str, righe: list[str] | str, rc: int | None = None) -> list[dict]:
    ""
    return [_uscita(v, passo, r, rc) for v, r in _trovate(passo, _righe(righe), rc)]


def diagnosi_errore(passo: str, righe: list[str] | str, rc: int | None = None) -> dict | None:
    ""






    trovate = [t for t in _trovate(passo, _righe(righe), rc) if t[0].gravita == "errore"]
    if trovate:
        voce, riga = trovate[0]
        return _uscita(voce, passo, riga, rc)
    if rc not in (None, 0):
        return _uscita(SCONOSCIUTO, passo, None, rc)
    return None





def _ultimo_esito(esiti: Path, passo: str) -> tuple[int | None, bool]:
    ""
    rc, chiuso_male = None, False
    for r in _coda(esiti, 1 << 20):
        campi = r.split("\t")
        if len(campi) < 3 or campi[1] != passo:
            continue
        if campi[2].startswith("tent.") and len(campi) > 3:
            valore = campi[3].removeprefix("rc=")
            rc = (
                -15
                if valore == "INTERROTTO"
                else int(valore)
                if valore.lstrip("-").isdigit()
                else rc
            )
            chiuso_male = False
        elif campi[2].startswith(("NOT CLOSED", "NON CHIUSO")):
            chiuso_male = True
        elif passo == "backup-kb" and campi[2].startswith("rc="):
            valore = campi[2].removeprefix("rc=")
            rc = int(valore) if valore.lstrip("-").isdigit() else rc
    return rc, chiuso_male




_MEMO: dict[tuple, dict] = {}


def _firma_file(p: Path) -> tuple:
    try:
        st = p.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return (None, None)


def esame_del_passo(cartella: Path, passo: str) -> dict:
    ""





    cartella = Path(cartella)
    esiti, log = cartella / "esiti.tsv", cartella / "log" / f"{passo}.log"
    chiave = (str(cartella), passo, _firma_file(esiti), _firma_file(log))
    if chiave in _MEMO:
        return _MEMO[chiave]
    rc, _ = _ultimo_esito(esiti, passo)
    righe = _coda(log)
    if passo in ("ingest", "tutto"):

        stadi = diagnosi_della_rilettura(ultimo_tentativo(righe))
        morti = [s for s in stadi if s["diagnosi"]["gravita"] == "errore"]
        diagnosi = {**morti[0]["diagnosi"], "stadio": morti[0]["stadio"]} if morti else None
        if diagnosi is None and rc not in (None, 0, 2):
            diagnosi = diagnosi_errore(passo, righe, rc)
        avvisi = [s["diagnosi"] for s in stadi if s["diagnosi"]["gravita"] == "avviso"]
    else:
        if rc == -15:
            righe = [*righe, "INTERROTTO"]
        diagnosi = diagnosi_errore(passo, righe, rc)
        avvisi = (
            [d for d in tutte_le_diagnosi(passo, righe, 0) if d["gravita"] == "avviso"]
            if rc == 0
            else []
        )
    if diagnosi:

        diagnosi = {**diagnosi, "log": str(log)}
    esame = {"diagnosi": diagnosi, "avvisi": avvisi}
    if len(_MEMO) > 512:
        _MEMO.clear()
    _MEMO[chiave] = esame
    return esame


def diagnosi_del_passo(cartella: Path, passo: str) -> dict | None:
    ""
    return esame_del_passo(cartella, passo)["diagnosi"]






CODA_DEI_FALLITI = Path(
    os.environ.get("SBK_CODA_FALLITI")
    or Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
    / "system"
    / "failure-queue.json"
)
_RE_RC_CODA = re.compile(r"(?:sys\.exit\(|Exit )(-?\d+)")


def _rc_dalla_coda(voce: dict) -> int:
    messaggio = str(voce.get("error_message") or "")
    if voce.get("error_type") == "timeout" or messaggio.startswith("Timeout after"):
        return 124
    if m := _RE_RC_CODA.search(messaggio):
        return int(m.group(1))
    return 1


def diagnosi_dalla_coda(
    sorgente: str, dal: str | None = None, coda: Path | None = None
) -> dict | None:
    ""





    try:
        voci = json.loads((coda or CODA_DEI_FALLITI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sue = [
        v
        for v in voci
        if isinstance(v, dict)
        and v.get("status") != "resolved"
        and (
            v.get("source") == sorgente
            or str(v.get("script_name", "")).startswith(f"l0-{sorgente}-")
        )


        and (v.get("stage") == "l0" or str(v.get("script_name", "")).startswith("l0-"))
        and (dal is None or str(v.get("timestamp", "")) >= dal)
    ]
    if not sue:
        return None
    ultima = max(sue, key=lambda v: str(v.get("timestamp", "")))
    righe = [
        str(ultima.get("error_message") or ""),
        f"{ultima.get('error_type')}: {ultima.get('error_message')}",
    ]
    d = diagnosi_errore(sorgente, righe, _rc_dalla_coda(ultima))
    return d and {
        **d,
        "quando_utc": str(ultima.get("timestamp", ""))[:19],
        "da": "failed queue",
    }




_ORA = r"^(?P<ora>\d\d:\d\d:\d\d) \w+ +"
_RE_RUNNING = re.compile(_ORA + r"RUNNING: (?P<nome>.+?)(?: \(.*\))?\s*$")
_RE_OK = re.compile(_ORA + r"OK in [\d.]+s")
_RE_FAILED = re.compile(_ORA + r"FAILED \(exit (?P<rc>-?\d+)\)")
# The runner writes English; the Italian of older logs is still accepted.
_RE_TIMEOUT = re.compile(_ORA + r"TIMEOUT (?:after|dopo)")
_RE_LOCK = re.compile(_ORA + r"LOCK (?:HELD|TENUTO)")

_RE_L1_START = re.compile(_ORA + r"Starting (?P<nome>[\w-]+): ")
_RE_L1_FINE = re.compile(
    _ORA + r"\[(?P<nome>[\w-]+)\] (?P<cosa>OK$|FAILED \(exit (?P<rc>-?\d+)\)|TIMEOUT (?:after|dopo))"
)
_RE_ESITO = re.compile(r"(?:Outcome|Esito): (?P<esito>.+)$")


def rc_del_run(righe: list[str] | str) -> int | None:
    """Exit code of the run from its last outcome line: 1 failed, 2 incomplete, 0 complete,
    None when the log has no outcome line. Reads the English outcome and the older Italian one."""
    esito = next((m["esito"] for r in reversed(_righe(righe)) if (m := _RE_ESITO.search(r))), "")
    if not esito:
        return None
    if any(x in esito for x in ("FAILED", "NOT VERIFIABLE", "FALLITA")):
        return 1
    if any(x in esito for x in ("INCOMPLETE", "INCOMPLETA")):
        return 2
    return 0


DEL_RUN = frozenset(
    {
        "rilettura-chiave-modello",
        "spesa-oltre-il-tetto",
        "rilettura-coda-illeggibile",
        "rilettura-senza-consenso",
        "rilettura-gia-in-corso",
        "stadio-senza-il-suo-file",
        "parquet-relazioni-rovinato",
        "copia-del-cervello-prima-di-rileggere",
        "fonte-non-indicizzata",
        "lavoro-rimasto-appeso",
        "qualita-peggiorata",
        "schede-sparite",
        "cervello-fermo",
        "fonti-a-mano-indietro",
        "fonti-mai-costruite",
        "recuperato-dopo-memoria",
        "orchestratore-rotto",
        "rilettura-incompleta",
        "disco-pieno",
    }
)


def diagnosi_della_rilettura(righe: list[str] | str) -> list[dict]:
    ""






    righe = _righe(righe)
    blocchi: dict[str, list[str]] = {}
    ordine: list[str] = []
    corrente = None
    for r in righe:
        if m := _RE_RUNNING.match(r):
            corrente = m["nome"].strip()
        elif m := _RE_L1_START.match(r):
            corrente = f"l1:{m['nome']}"
        elif (m := _RE_L1_FINE.match(r)) and f"l1:{m['nome']}" in blocchi:

            corrente = f"l1:{m['nome']}"
            blocchi[corrente].append(r)
            continue
        else:
            if corrente is not None:
                blocchi[corrente].append(r)
            continue
        if corrente not in blocchi:
            ordine.append(corrente)

        blocchi[corrente] = [r]
    fuori = []
    for nome in ordine:
        rc = None
        for r in blocchi[nome]:
            if m := _RE_L1_FINE.match(r):
                rc = 0 if m["cosa"] == "OK" else int(m["rc"]) if m["rc"] else 124
            elif m := _RE_FAILED.match(r):
                rc = int(m["rc"])
            elif _RE_TIMEOUT.match(r):
                rc = 124
            elif _RE_LOCK.match(r):
                rc = 75
            elif _RE_OK.match(r):
                rc = 0
        if rc not in (None, 0):
            d = diagnosi_errore(nome, blocchi[nome], rc)
            if d:
                fuori.append({"stadio": nome, "diagnosi": d})
    rc_run = rc_del_run(righe)
    gia = {f["diagnosi"]["id"] for f in fuori}
    for voce, riga in _trovate("ingest", righe, rc_run, solo=DEL_RUN):
        if voce.id not in gia:
            gia.add(voce.id)
            fuori.append({"stadio": "ingest", "diagnosi": _uscita(voce, "ingest", riga, rc_run)})
    return fuori





def catalogo_json() -> list[dict]:
    ""
    fuori = []
    for v in (*CATALOGO, SCONOSCIUTO):
        fuori.append(
            {
                "id": v.id,
                "passi": list(v.passi),
                "firme": list(v.firme),
                "rc": list(v.rc),
                "gravita": v.gravita,
                "peso": v.peso,
                "causa": v.causa,
                "rimedio": v.rimedio,
                "chi": v.chi,
                "ritenta": v.ritenta,
                "anche_con_rc_0": v.anche_con_rc_0,
                "azione": dict(AZIONI[v.azione], id=v.azione) if v.azione else None,
                "visto": list(v.visto),
                "nota": v.nota,
            }
        )
    return fuori


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "catalogo":
        print(json.dumps(catalogo_json(), ensure_ascii=False, indent=2))
        return 0
    if len(argv) == 3 and argv[0] == "passo":
        print(json.dumps(diagnosi_del_passo(Path(argv[1]), argv[2]), ensure_ascii=False, indent=2))
        return 0
    if len(argv) == 2 and argv[0] == "rilettura":
        righe = _coda(Path(argv[1]))
        print(json.dumps(diagnosi_della_rilettura(righe), ensure_ascii=False, indent=2))
        return 0
    print((__doc__ or "").strip())
    return 0 if argv[:1] in (["-h"], ["--help"]) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
