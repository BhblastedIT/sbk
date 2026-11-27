#!/usr/bin/env python3
"""Voice for the tasks section: you dictate to your tasks, and a Claude Code session in the background understands and acts.

The session runs with your own `claude` login and only after you opt in (sb_own_claude.py:
"app": {"claude_sessions": true} in sbk.config.json, or SBK_APP_CLAUDE=1). It is sent what you
dictated or wrote and your task list. Without consent the request stops and says how to turn it on.
"""










































from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
if str(QUI) not in sys.path:
    sys.path.insert(0, str(QUI))
import sb_attivita as A  # noqa: E402
import sb_cose as C  # noqa: E402
import sb_own_claude  # noqa: E402

VENV = ROOT / ".venv" / "bin" / "python"
ISTRUZIONI = QUI / "attivita" / "SESSIONE-VOCE.md"
GUARDIA = QUI / "attivita" / "guardia_voce.py"

TRASCRIVI = Path(
    os.environ.get("SB_ATTIVITA_TRASCRIVI")
    or ROOT / "tools" / "voce" / "trascrivi-audio.py"
)

STRUMENTO = "attivita-voce"

MODELLO = "opus"
ATTREZZI = "Bash,Write"
AUDIO = re.compile(r"\.(m4a|mp3|aac|wav|ogg|opus|webm|caf|aiff?)$", re.I)


INTERVALLO_TENTATIVI_S = int(os.environ.get("SB_VOCE_INTERVALLO_S") or 600)
TENTATIVI = 7
TETTO_SESSIONE_S = int(os.environ.get("SB_VOCE_TETTO_S") or 1800)

PASSO_CODA_S = float(os.environ.get("SB_VOCE_PASSO_S") or 1)

RIAVVII_MAX = 3

NASCITA_S = 30

RECENTI = 30


TESTO_MAX = 20_000

RILEGGI_S = 5

STATI = {
    "in_trascrizione": ("Transcribing it", False),
    "aspetta_memoria": ("I'll transcribe it as soon as the Mac has free memory", False),
    "da_verificare": ("I'm not sure I understood", True),
    "in_coda": ("Waiting for the previous request to finish", False),
    "in_elaborazione": ("Working on it", False),
    "fatta": ("Done", True),
    "ti_chiede": ("I have a question for you", True),
    "non_riuscita": ("It didn't succeed", True),

    "non_si_puo": ("I can't do this yet", True),
}

SOGLIA = int(os.environ.get("SB_VOCE_SOGLIA") or 5)

RIGHE_PROPOSTA = 20

VERBI_PROPOSTA = (
    "nuova",
    "fatta",
    "riapri",
    "stato",
    "priorita",
    "data",
    "scadenza",
    "stima",
    "titolo",
    "descrizione",
    "descrizione-aggiungi",
    "area",
    "elimina",
    "ripristina",

    "pianifica",
    "commenta",

    "vista-imposta",
)

TESTI = {
    "stato_in_trascrizione": STATI["in_trascrizione"][0],
    "stato_aspetta_memoria": STATI["aspetta_memoria"][0],
    "stato_da_verificare": STATI["da_verificare"][0],
    "stato_in_coda": STATI["in_coda"][0],
    "stato_in_elaborazione": STATI["in_elaborazione"][0],
    "stato_fatta": STATI["fatta"][0],
    "stato_ti_chiede": STATI["ti_chiede"][0],
    "stato_non_riuscita": STATI["non_riuscita"][0],
    "stato_non_si_puo": STATI["non_si_puo"][0],
    "stato_da_confermare": "To confirm",
    "stato_sconosciuto": "I don't know where it stands",


    **{
        k: A.TESTI[k]
        for k in (
            "barra_segnaposto",
            "ferma",
            "aiuto_ferma",
            "aiuto_microfono",
            "lavoro_da",
            "aiuto_filo",
            "filo_vuoto",
            "aiuto_gesto",
            "lavoro_da_minuto",
            "lavoro_da_minuti",
        )
    },
    "da_confermare_aiuto": "Before doing it I need your yes. If it's right confirm it, otherwise correct the request.",
    "proposta_riga": "«{titolo}» {cosa}",
    "proposta_altre": "and {n} more",
    "proposta_altra": "and one more",
    "quando_alle": "{giorno} at {ora}",
    "proposta_perde": "The current description «{testo}» will be lost",
    "gia_fatto_uno": "Before asking you I already made one change, you see it below.",
    "gia_fatto_tanti": "Before asking you I already made {n} changes, you see them below.",
    "non_si_puo_senza_perche": "I can't do this by voice yet.",
    "ricevuta_si": "OK, I'll do it.",
    "stato_annullata": "Cancelled",
    "ricevuta_audio": "I heard you. I'll transcribe it and then work on it, here I'll tell you what I did.",
    "ricevuta_testo": "Got it. I'll work on it and here I'll tell you what I did.",

    "ricevuta_gia": "I'd already received this request, I'm working on it.",
    "ricevuta_conferma": "OK, I'll work on it with these words.",
    "ricevuta_riprova": "Retrying.",
    "titolo_sezione": "Voice requests",
    "aiuto_sezione": "What you asked by voice or wrote here. A session reads it, acts on the tasks and leaves you the answer.",
    "vuoto": "You haven't asked anything by voice yet.",
    "ho_sentito": "I heard «{testo}»",
    "hai_scritto": "You wrote «{testo}»",
    "dubbio_corta": "I heard little speech.",
    "dubbio_lingua": "I'm not sure of the language.",
    "dubbio_parole": "I guessed at several words.",
    "senza_parlato": "I heard no words in the audio.",
    "da_verificare_aiuto": "Before acting check above. If it's right confirm it, otherwise correct it.",
    "conferma": "It's right, go ahead",
    "correggi": "Correct",
    "riprova": "Retry",
    "ascolta": "Listen",
    "annulla": "Undo everything",
    "aiuto_annulla": "Restores all the tasks this request touched to how they were.",
    "rispondi": "Reply",
    "aiuto_rispondi": "Your reply goes to the same request, with the earlier question.",
    "nessun_gesto": "I didn't change anything.",
    "gesto_nuova": "Added «{titolo}»",
    "gesto_fatta": "Marked done «{titolo}»",
    "gesto_riaperta": "Reopened «{titolo}»",
    "gesto_stato": "«{titolo}» now has status {valore}",
    "gesto_priorita": "«{titolo}» is now {valore}",
    "gesto_data": "«{titolo}» is now due {valore}",
    "gesto_data_tolta": "Removed the date from «{titolo}»",
    "gesto_stima": "«{titolo}» now has an estimated time of {valore}",
    "gesto_stima_tolta": "Removed the estimated time from «{titolo}»",
    "gesto_titolo": "New title «{titolo}»",
    "gesto_descrizione": "Changed the description of «{titolo}»",
    "gesto_descrizione_aggiunta": "In «{titolo}» I added «{testo}»",
    "gesto_area": "«{titolo}» is now in {valore}",
    "gesto_elimina": "Deleted «{titolo}»",
    "gesto_ripristina": "Put back in the list «{titolo}»",
    "gesto_altro": "Changed «{titolo}»",
    "motivo_ricetta": "I can't find audio transcription on the Mac. Write the request instead of saying it.",

    "motivo_ricetta_commento": "I can't find audio transcription on the Mac. Write the comment instead of saying it.",
    "motivo_audio": "I couldn't read the audio. Try saying it again, or write it.",
    "motivo_whisper": "Transcription failed. Try again, or write it.",
    "motivo_memoria": "The Mac had no free memory to transcribe it. Try again later, or write it.",
    "motivo_memoria_sessione": "The Mac had no free memory to run the session. Press Retry later.",
    "motivo_spento": sb_own_claude.OFF_MESSAGE.format(what="what you dictated or wrote and your task list"),
    "motivo_claude_manca": sb_own_claude.MISSING_MESSAGE,
    "motivo_senza_esito": "The session closed without telling me what it did.",
    "motivo_tempo": "The session took too long and was stopped.",
    "motivo_processo": "The work stopped halfway. Press Retry.",
    "motivo_proposta_storta": "I wanted to ask you for confirmation, but I couldn't prepare it properly. Press Retry.",
    "motivo_gesti_diversi": "The session says it did things I can't find among the changes. Look at the actions below.",
    "errore_audio": "I can't find the audio to send.",
    "errore_testo": "Write what you want me to do.",
    "errore_sparita": "This request no longer exists.",
    "errore_dentro": "A voice request doesn't start another one.",
    "errore_non_da_verificare": "This request isn't awaiting a confirmation.",
    "errore_non_riprova": "This request isn't stuck, no need to retry.",
    "errore_in_corso": "I'm still working on it. Undo when I'm done.",
    "errore_gia_annullata": "You already undid this request.",

    "errore_annullata_non_riparte": "You undid this request. If you still need it, ask again.",

    "errore_testo_lungo": "It's too long for one request. Write it shorter, or split it into several requests.",
    "errore_comando": "I can't make this change.",
    "errore_motore": "Something didn't respond as it should. Try again.",
    "annullato_zero": "There was nothing to restore.",

    "annullato_niente_dopo_una": "I restored nothing, you changed «{titolo}» afterwards.",
    "annullato_niente_dopo_tante": "I restored nothing, you changed {titoli} afterwards.",
    "annullato_in_parte_una": "{fatto} What you changed afterwards in «{titolo}» I left as is.",
    "annullato_in_parte_tante": "{fatto} What you changed afterwards in {titoli} I left as is.",
    "saltata_in_parte": "«{titolo}» I only partly restored, the rest you changed afterwards.",
    "annullato_uno": "I restored one task.",
    "annullato_tanti": "I restored {n} tasks.",
    "saltata": "«{titolo}» I didn't touch, you changed it afterwards.",

    "gesto_nuova_con": "Added «{titolo}», {campi}",
    "gesto_campo_priorita": "{valore}",
    "gesto_campo_scade": "due {valore}",
    "gesto_campo_pianificata": "scheduled {valore}",
    "gesto_campo_stima": "{valore}",
    "gesto_campo_area": "in {valore}",
    "gesto_campo_stato": "{valore}",
    "gesto_pianificata": "«{titolo}» is scheduled {valore}",
    "gesto_pianificata_tolta": "Removed from the calendar «{titolo}»",
    "gesto_commento": "On «{titolo}» I left the comment «{testo}»",
    "gesto_commento_tolto": "Removed a comment from «{titolo}»",
    "gesto_vista": "Changed the view «{nome}»",
    "gesto_campi": "«{titolo}» {cambi}",
    "gesto_e": " and ",
    "gesto_e_fatta": "is done",
    "gesto_e_riaperta": "is reopened",
    "gesto_e_stato": "now has status {valore}",
    "gesto_e_priorita": "is now {valore}",
    "gesto_e_data": "is now due {valore}",
    "gesto_e_data_tolta": "no longer has a date",
    "gesto_e_stima": "has an estimated time of {valore}",
    "gesto_e_stima_tolta": "no longer has an estimated time",
    "gesto_e_area": "is now in {valore}",
    "gesto_e_pianificata": "is scheduled {valore}",
    "gesto_e_pianificata_tolta": "is no longer in the calendar",
    "annullato_vista": "I restored the view.",
    "annullato_viste": "I restored {n} views.",
    "errore_task_sparita": "This task no longer exists.",
    "motivo_task_sparita": "The comment's task no longer exists. The dictation stays saved.",
    "stato_commento_scritto": "Comment written",
    "ricevuta_commento": "I heard you. I'll transcribe it and write it as a comment.",
}


class Errore(Exception):
    def __init__(self, chiave: str):
        super().__init__(chiave)
        self.chiave = chiave





def casa() -> Path:
    return A.CARTELLA / "voce"


def _cartella(rid: str) -> Path:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}-[0-9a-f]{4}", rid or ""):
        raise Errore("errore_sparita")
    c = casa() / rid
    if not (c / "RICHIESTA.json").is_file():
        raise Errore("errore_sparita")
    return c


def _ora() -> str:
    return C._adesso().isoformat(timespec="seconds")


def _leggi(percorso: Path) -> dict:
    try:
        d = json.loads(percorso.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return {}
    return d if isinstance(d, dict) else {}


def _scrivi(percorso: Path, dati: dict) -> None:
    ""
    tmp = percorso.with_name(f".{percorso.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, percorso)


def _stato(cart: Path, **campi) -> dict:
    ""
    s = _leggi(cart / "STATO.json")


    adesso = A._adesso_ms()
    s.update(campi, aggiornato=_ora(), aggiornato_ms=adesso)
    if "partito" in campi:
        s["partito_ms"] = adesso
    _scrivi(cart / "STATO.json", s)
    return s


def _secondi_da(s: dict, chiave: str) -> float | None:
    ""
    try:
        testo = datetime.fromisoformat(s.get(chiave) or "")
    except (TypeError, ValueError):
        return None
    ms = s.get(f"{chiave}_ms")

    if A.ms_torna(ms, testo.isoformat()):
        return (A._adesso_ms() - ms) / 1000
    return (C._adesso() - testo).total_seconds()


def _log(*parti) -> None:
    ""
    print(_ora(), *parti, file=sys.stderr, flush=True)




_DA_EREDITARE: dict[str, int] = {}


@contextlib.contextmanager
def _lucchetto(percorso: Path, aspetta: bool = True):
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with open(percorso, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if aspetta else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield fh.fileno()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _vivo(cart: Path) -> bool:
    ""
    p = cart / ".processo.lock"
    if not p.exists():
        return False
    with open(p, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False





def _nuovo_id() -> str:
    return C._adesso().strftime("%Y-%m-%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _durata(valore) -> float | None:
    try:
        d = float(str(valore).replace(",", "."))
    except (TypeError, ValueError):
        return None

    return d if math.isfinite(d) and d > 0 else None


def _opzioni(resto: list[str], conosciute: tuple[str, ...]) -> tuple[list[str], dict]:
    liberi, opz, i = [], {}, 0
    while i < len(resto):
        if resto[i] in conosciute and i + 1 < len(resto):
            opz[resto[i][2:]] = resto[i + 1]
            i += 2
        else:
            liberi.append(resto[i])
            i += 1
    return liberi, opz


def _dopo(rid: str | None) -> str:
    ""
    if not rid:
        return ""
    try:
        _cartella(rid)
    except Errore:
        return ""
    return rid



UNA_VOLTA_S = 24 * 3600
UNA_VOLTA_MAX = 200


def _gia_con_chiave(chiave: str) -> Path | None:
    ""
    limite = time.time_ns() - UNA_VOLTA_S * 10**9
    for c in reversed(_richieste()):
        r = _leggi(c / "RICHIESTA.json")
        if isinstance(r.get("arrivo"), int) and r["arrivo"] < limite:
            break
        if r.get("una_volta") == chiave:
            return c
    return None


def nuova(via: str, testo: str = "", audio: str = "", durata=None, dopo: str = "", vista: str = "",
          scelte: str = "", commento: str = "", una_volta: str = "") -> dict:
    ""


    if not una_volta:
        return _nuova(via, testo, audio, durata, dopo, vista, scelte, commento, "")
    if len(una_volta) > UNA_VOLTA_MAX or _rompe_riga(una_volta):
        raise Errore("errore_comando")
    with _lucchetto(casa() / ".una-volta.lock") as _:
        c = _gia_con_chiave(una_volta)
        if c is None:
            return _nuova(via, testo, audio, durata, dopo, vista, scelte, commento, una_volta)
    s = _leggi(c / "STATO.json")
    stato = s.get("stato") if isinstance(s.get("stato"), str) else "in_coda"
    return {
        "ok": True,
        "id": c.name,
        "gia": True,
        "stato": stato,
        "stato_nome": TESTI.get(f"stato_{stato}", TESTI["stato_sconosciuto"]),
        "messaggio": TESTI["ricevuta_gia"],
        "rileggi_fra_s": RILEGGI_S,
    }


def _rompe_riga(x: str) -> bool:
    return any(ch in x for ch in "\n\r\u2028\u2029") or not x.strip()


def _nuova(via: str, testo: str, audio: str, durata, dopo: str, vista: str, scelte: str, commento: str,
           una_volta: str) -> dict:
    ""


    if os.environ.get("SB_ATTIVITA_DA"):
        raise Errore("errore_dentro")
    if commento:
        t = A._carica().get(commento)
        if t is None or t["eliminata"]:
            raise Errore("errore_task_sparita")
    if via == "voce":
        sorgente = Path(audio).expanduser()
        if not audio or not sorgente.is_file() or not AUDIO.search(sorgente.name):
            raise Errore("errore_audio")
    elif not testo.strip():
        raise Errore("errore_testo")


    try:
        testo = testo.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:
        testo = re.sub("[\ud800-\udfff]", "\ufffd", testo)
    if len(testo) > TESTO_MAX:
        raise Errore("errore_testo_lungo")
    casa().mkdir(parents=True, exist_ok=True)
    rid = _nuovo_id()
    cart = casa() / rid
    cart.mkdir()

    richiesta = {
        "id": rid,
        "creata": _ora(),
        "creata_ms": A._adesso_ms(),
        "arrivo": time.time_ns(),
        "via": via,
        "dopo": _dopo(dopo),
    }
    if vista:
        richiesta["vista"] = vista
    ids_scelte = [x for x in (scelte or "").split(",") if x]
    if ids_scelte:
        richiesta["scelte"] = list(dict.fromkeys(ids_scelte))[:500]
    if commento:
        richiesta["commento"] = commento
    if una_volta:
        richiesta["una_volta"] = una_volta
    if via == "voce":
        copia = cart / f"audio{sorgente.suffix.lower()}"
        shutil.copy2(sorgente, copia)
        richiesta.update(audio=copia.name, audio_origine=str(sorgente), durata_app=_durata(durata))
        stato = "in_trascrizione"
    else:
        richiesta["testo"] = testo.strip()
        stato = "in_coda"
    _scrivi(cart / "RICHIESTA.json", richiesta)
    _stato(cart, stato=stato, partito=_ora(), riavvii=0)
    _parti(rid)
    return {
        "ok": True,
        "id": rid,
        "stato": stato,
        "stato_nome": TESTI[f"stato_{stato}"],
        "messaggio": TESTI["ricevuta_commento"]
        if commento and via == "voce"
        else TESTI["ricevuta_audio" if via == "voce" else "ricevuta_testo"],
        "rileggi_fra_s": RILEGGI_S,
    }


def _parti(rid: str) -> int | None:
    ""
    if os.environ.get("SB_VOCE_SINCRONO"):
        catena(rid)
        return None
    cart = casa() / rid
    log = open(cart / "processo.log", "a")  # noqa: SIM115 stays open in the child process
    p = subprocess.Popen(
        [
            str(VENV if VENV.exists() else sys.executable),
            "-I",
            str(Path(__file__)),
            "sottofondo",
            rid,
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(ROOT),
    )
    return p.pid





def _ricetta():
    ""
    spec = importlib.util.spec_from_file_location("trascrivi_audio_voce", TRASCRIVI)
    if spec is None or not TRASCRIVI.is_file():
        raise FileNotFoundError(str(TRASCRIVI))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit as e:
        raise FileNotFoundError(str(e)) from None
    return m



_SOGLIE = {
    "VOCE_MINIMA_OWNER_S": 1.0,
    "SICUREZZA_LINGUA_MINIMA": 0.5,
    "SICUREZZA_PAROLE_MINIMA": 0.8,
    "QUOTA_PAROLE_INCERTE": 0.15,
}
_NOTE_DI_SUONO = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|[♪♫♬]")


def giudica(esito: dict, arch=None) -> dict:
    ""

    soglia = {k: getattr(arch, k, v) for k, v in _SOGLIE.items()}
    note = getattr(arch, "NOTE_DI_SUONO", _NOTE_DI_SUONO)
    testo = " ".join(note.sub(" ", esito.get("testo") or "").split())
    contare = getattr(arch, "parole_vere", None) or (lambda t: len(re.findall(r"[^\W\d_]+", t)))
    voce, lingua = esito.get("voce_s"), esito.get("sicurezza_lingua")
    sic, incerte = esito.get("sicurezza_parole"), esito.get("parole_incerte")
    misure = {
        k: esito.get(k)
        for k in (
            "voce_s",
            "lingua",
            "sicurezza_lingua",
            "sicurezza_parole",
            "parole_incerte",
            "durata_s",
            "modello",
            "secondi",
        )
    }
    if not contare(testo):
        return {
            "testo": "",
            "verdetto": "senza_parlato",
            "dubbi": ["senza_parlato"],
            "misure": misure,
        }
    dubbi = []
    if isinstance(voce, int | float) and voce < soglia["VOCE_MINIMA_OWNER_S"]:
        dubbi.append("corta")
    if isinstance(lingua, int | float) and lingua < soglia["SICUREZZA_LINGUA_MINIMA"]:
        dubbi.append("lingua")
    if (isinstance(sic, int | float) and sic < soglia["SICUREZZA_PAROLE_MINIMA"]) or (
        isinstance(incerte, int | float) and incerte >= soglia["QUOTA_PAROLE_INCERTE"]
    ):
        dubbi.append("parole")
    return {
        "testo": testo,
        "verdetto": "da_verificare" if dubbi else "ok",
        "dubbi": dubbi,
        "misure": misure,
    }


def _trascrivi(cart: Path, richiesta: dict) -> str | None:
    ""
    try:
        m = _ricetta()
    except Exception as e:  # noqa: BLE001 the request must not stay silent
        chiave = "motivo_ricetta_commento" if richiesta.get("commento") else "motivo_ricetta"
        _stato(cart, stato="non_riuscita", motivo=TESTI[chiave], dettaglio=repr(e)[:300])
        return None
    audio = cart / richiesta["audio"]
    uscita = cart / "trascrizione"
    for tentativo in range(TENTATIVI):
        if tentativo:
            time.sleep(INTERVALLO_TENTATIVI_S)
        _stato(cart, stato="in_trascrizione", tentativi_trascrizione=tentativo + 1)
        _log(f"transcription, attempt {tentativo + 1}")
        try:
            wav, err = m.wav_di(audio, uscita)
        except Exception as e:  # noqa: BLE001 the request must not stay «Transcribing it»
            wav, err = None, repr(e)
        if not wav:
            _stato(
                cart, stato="non_riuscita", motivo=TESTI["motivo_audio"], dettaglio=str(err)[:300]
            )
            return None
        try:
            esito = m.whisper(wav, uscita, INTERVALLO_TENTATIVI_S)
        except Exception as e:  # noqa: BLE001
            esito = {"esito": f"error {e!r}"}
        if not isinstance(esito, dict):
            esito = {"esito": f"error, whisper returned {type(esito).__name__}"}
        try:
            esito["durata_s"] = _durata(m.durata(audio))
        except Exception:  # noqa: BLE001 the duration decides nothing
            esito["durata_s"] = None
        _scrivi(uscita / "esito-trascrizione.json", esito)
        e = str(esito.get("esito") or "")
        _log("whisper", e, esito.get("modello"), esito.get("secondi"))
        if e.startswith("rimandata"):
            _stato(cart, stato="aspetta_memoria", dettaglio=e)
            continue
        if e != "ok":
            _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_whisper"], dettaglio=e[:300])
            return None
        g = giudica(esito, getattr(m, "arch", None))
        _stato(cart, sentito=g["testo"], dubbi=g["dubbi"], misure=g["misure"])
        if g["verdetto"] != "ok":
            _stato(cart, stato="da_verificare")
            return None
        return g["testo"]
    _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_memoria"])
    return None





def _breve(t: dict, imp: dict | None = None, aree=None, oggi: datetime | None = None) -> dict:
    ""


    imp = imp or A._imp()
    oggi = oggi or C._adesso()
    d = " ".join((t.get("descrizione") or "").split())
    sd = A._stato_di(imp, t["stato"])
    chiusa = A._chiuso_tipo(sd["tipo"])
    out = {
        "id": t["id"],
        "titolo": t["titolo"],
        "stato": t["stato"],
        "stato_nome": sd["nome"],
        "priorita": A.PRIORITA.get(t["priorita"], "P2"),
        "scadenza": t.get("scadenza") or "",
        "area": aree.nome(aree.finale(t.get("area")))
        if aree and t.get("area")
        else (t.get("area") or ""),
        "stima": t.get("stima"),
        **({"descrizione": d[:100]} if d else {}),

        **({"descrizione_caratteri": len(t.get("descrizione") or "")} if len(d) > 100 else {}),
        "cambiata": t.get("cambiata"),
    }
    if not chiusa and not t["eliminata"]:
        out["urgente"] = A._urgente(t, {}, oggi, imp)
    if chiusa and t.get("chiusa"):
        out["chiusa"] = t["chiusa"]
    if t.get("pianificata"):
        out["pianificata"] = t["pianificata"]
    commenti = t.get("commenti") or {}
    if commenti:
        testo = max(commenti.values(), key=lambda c: c[2])[1]
        out["commenti_n"] = len(commenti)
        out["ultimo_commento"] = " ".join(testo.split())[:100]
    return out


def contesto(rid: str, testo: str, via: str, dopo: str = "") -> dict:
    oggi = C._adesso()
    cache = _letti()
    tutte = list(cache[1].values())
    imp, aree = _imp_aree(cache)
    limite = (oggi - timedelta(days=14)).isoformat(timespec="seconds")
    aperte = sorted(
        (t for t in tutte if not t["eliminata"] and not A._chiuso(imp, t["stato"])),
        key=lambda t: (t["priorita"], t.get("scadenza") or "9999", t["titolo"].casefold()),
    )
    fatte = sorted(
        (
            t
            for t in tutte
            if not t["eliminata"] and A._chiuso(imp, t["stato"]) and t["cambiata"] >= limite
        ),
        key=lambda t: t["cambiata"],
        reverse=True,
    )[:40]
    eliminate = sorted(
        (t for t in tutte if t["eliminata"] and t["cambiata"] >= limite),
        key=lambda t: t["cambiata"],
        reverse=True,
    )[:20]

    def breve(t):
        return _breve(t, imp, aree, oggi)

    out = {
        "richiesta": rid,
        "via": via,
        "detto": testo,
        "adesso": oggi.isoformat(timespec="seconds"),
        "oggi": f"{C.GIORNI[oggi.weekday()]} {oggi.day} {C.MESI[oggi.month - 1]} {oggi.year}, {oggi.date().isoformat()}",

        "aree": [d["nome"] for d in aree.visibili()],
        "stati": [
            {"id": x["id"], "nome": x["nome"], "tipo": x["tipo"]} for x in A._stati_in_ordine(imp)
        ],
        "aperte": [breve(t) for t in aperte],
        "fatte_di_recente": [breve(t) for t in fatte],
        "eliminate_di_recente": [breve(t) for t in eliminate],

        "gia_fatto": [g["cosa"] for g in gesti(rid, cache)],
        "soglia": SOGLIA,

        "filtri_pronti": [{"id": x, "nome": A.TESTI[f"vista_{x}"]} for x in A.FILTRI_PRONTI],
    }
    r = _leggi(casa() / rid / "RICHIESTA.json")
    if r.get("vista"):

        try:
            v = next(x for vid, x in A._tutte_le_viste(A._leggi_viste()) if vid == r["vista"])
            ctx = A.Contesto(imp, aree, [])
            out["vista_di_adesso"] = {
                "id": r["vista"],
                "nome": A._nome_vista(r["vista"], v),
                "modo": v.get("modo"),
                "filtro": A._filtro_risolto(v["filtro"], ctx),
                "gruppo": v.get("gruppo"),
                "ordine": v.get("ordine") or [],
            }
        except StopIteration:
            pass
    if r.get("scelte"):
        per_id = {t["id"]: t for t in tutte}
        out["scelte"] = [
            {"id": x, "titolo": per_id[x]["titolo"]} for x in r["scelte"] if x in per_id
        ]
    si = _leggi(casa() / rid / "CONFERMATE.json")
    if si:
        out["confermato"] = {"proposta": si.get("proposta") or [], "quando": si.get("quando")}
    ultima = _ultima_con_cambi(rid, cache)
    if ultima:
        out["ultima_richiesta"] = ultima
    if dopo:
        cp = casa() / dopo
        prima_r, prima_s, prima_e = (
            _leggi(cp / "RICHIESTA.json"),
            _leggi(cp / "STATO.json"),
            _leggi(cp / "ESITO.json"),
        )
        out["prima"] = {
            "detto": prima_s.get("testo") or prima_r.get("testo") or prima_s.get("sentito") or "",
            "capito": prima_e.get("capito") or "",
            "risposta": prima_e.get("risposta") or "",
            "domanda": prima_e.get("domanda") or "",
            "gesti": prima_e.get("gesti") or [],
        }
    return out


def _ultima_con_cambi(rid: str, cache=None) -> dict | None:
    ""

    cache = _letti(cache)
    con_cambi = {e.get("da") for e in cache[0] if isinstance(e.get("da"), str)}
    mia = _arrivo(casa() / rid) if (casa() / rid).is_dir() else (float("inf"), rid)
    for c in reversed(_richieste()):
        if c.name not in con_cambi or c.name == rid or (c / "ANNULLA.json").is_file():
            continue
        if _arrivo(c) >= mia:
            continue
        g = gesti(c.name, cache)
        if not g:
            continue
        r, s = _leggi(c / "RICHIESTA.json"), _leggi(c / "STATO.json")
        return {
            "id": c.name,
            "quando": _quando(r.get("creata") or ""),
            "detto": s.get("testo") or r.get("testo") or s.get("sentito") or "",
            "cambi": [x["cosa"] for x in g],
        }
    return None


def _primo_messaggio(cart: Path, ctx: dict) -> str:
    istruzioni = ISTRUZIONI.read_text(encoding="utf-8")
    return (
        f"{istruzioni}\n\n## Your folder\n\n{cart}\n\nWrite ESITO.json there, in {cart / 'ESITO.json'}.\n\n"
        f"## The context\n\n```json\n{json.dumps(ctx, ensure_ascii=False)}\n```\n"
    )


def _python() -> str:
    return str(VENV if VENV.exists() else sys.executable)


def _impostazioni(cart: Path, rid: str) -> Path:
    ""
    comando = " ".join(
        shlex.quote(p)
        for p in (
            _python(),
            "-I",
            str(GUARDIA),
            "--cartella",
            str(cart),
            "--richiesta",
            rid,
            "--attivita",
            str(A.CARTELLA),
        )
    )
    dati = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": comando,
                            "timeout": 15,



                            "onFailure": "block",
                        }
                    ],
                }
            ]
        }
    }
    p = cart / "impostazioni.json"
    _scrivi(p, dati)
    return p


def _trova_claude() -> str:
    """Your own `claude` command (SB_CLAUDE_CLI, PATH or the usual install places)."""
    return sb_own_claude.find_claude() or "claude"


def comando_claude(cart: Path, rid: str) -> list[str]:
    ""


    vuoto = cart / "mcp-vuoto.json"
    vuoto.write_text('{"mcpServers": {}}\n')
    return [
        _trova_claude(),
        "-p",
        "--add-dir",
        str(cart),
        "--tools",
        ATTREZZI,
        "--strict-mcp-config",
        "--mcp-config",
        str(vuoto),
        "--settings",
        str(_impostazioni(cart, rid)),
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
        "--model",
        sb_own_claude.model(MODELLO),
        "-n",
        f"Voice activity {rid[11:13]}:{rid[13:15]}",
    ]


def _con_memoria(fai):
    ""

    if os.environ.get("SB_FINTO_LEASE"):
        return fai()
    sys.path.insert(0, str(ROOT / "tools"))
    import sbk_resources as sr

    soglia = min(float(os.environ.get("SB_SOGLIA_AMMISSIONE") or 65) / 100, sr.SEG_YIELD - 0.02)
    scadenza = time.time() + 1800
    while True:
        pressione = sr.pressure().seg_ratio
        if pressione < soglia:
            lz = sr.Lease(STRUMENTO, need_frac=0.03)
            lz.registra(0.03)
            try:
                return fai()
            finally:
                lz.release()
        if time.time() > scadenza:
            return None
        _log(f"Mac pressure at {pressione * 100:.0f}%, waiting")
        time.sleep(60)


def _arrivo(c: Path) -> tuple:
    return (_leggi(c / "RICHIESTA.json").get("arrivo") or 0, c.name)


def _richieste() -> list[Path]:
    ""
    if not casa().is_dir():
        return []
    return sorted((c for c in casa().iterdir() if (c / "RICHIESTA.json").is_file()), key=_arrivo)


def _piu_vecchia_in_coda(rid: str) -> str | None:
    mia = _arrivo(casa() / rid)
    for c in _richieste():
        if _arrivo(c) >= mia:
            break
        st = _leggi(c / "STATO.json")
        if st.get("stato") == "in_coda" and (
            _vivo(c) or _appena_partita(st)
        ):
            return c.name
    return None


def _appena_partita(st: dict) -> bool:
    ""

    eta = _secondi_da(st, "partito")
    return eta is not None and eta < NASCITA_S


@contextlib.contextmanager
def _turno(rid: str):
    ""
    p = casa() / ".sessione.lock"
    with open(p, "a+") as fh:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(PASSO_CODA_S)
                continue
            if _piu_vecchia_in_coda(rid) is None:
                break
            fcntl.flock(fh, fcntl.LOCK_UN)
            time.sleep(PASSO_CODA_S)
        _DA_EREDITARE[".sessione.lock"] = fh.fileno()
        try:
            yield
        finally:
            _DA_EREDITARE.pop(".sessione.lock", None)
            fcntl.flock(fh, fcntl.LOCK_UN)


def _esito_dal_result(testo: str) -> dict:
    ""
    m = re.search(r"\{.*\}", testo or "", re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return {}
    return d if isinstance(d, dict) and ("risposta" in d or "stato" in d) else {}


def _permesso() -> str:
    """The consent and install check of sb_own_claude, as the key of the message to show."""
    try:
        sb_own_claude.check()
    except sb_own_claude.NotAllowed:
        return "motivo_spento"
    except sb_own_claude.ClaudeMissing:
        return "motivo_claude_manca"
    return ""


def _sessione(cart: Path, rid: str, richiesta: dict, testo: str) -> int:
    _stato(cart, stato="in_coda", testo=testo)
    chiave = _permesso()
    if chiave:
        _stato(cart, stato="non_riuscita", motivo=TESTI[chiave])
        return 2
    with _turno(rid):
        ctx = contesto(rid, testo, richiesta["via"], richiesta.get("dopo") or "")
        _scrivi(cart / "CONTESTO.json", ctx)
        uscita = _con_memoria(lambda ctx=ctx: _una_sessione(cart, rid, ctx))
        if uscita is None:
            _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_memoria_sessione"])
            return 75
        return uscita if isinstance(uscita, int) else 2


def _una_sessione(cart: Path, rid: str, ctx: dict):
    ""
    try:
        sessione = sb_own_claude.session(
            STRUMENTO, what="what you dictated or wrote and your task list"
        )
    except sb_own_claude.NotAllowed:
        _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_spento"])
        return 2
    except sb_own_claude.ClaudeMissing:
        _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_claude_manca"])
        return 2
    with sessione as p:




        messaggio = cart / "MESSAGGIO.md"
        messaggio.write_text(_primo_messaggio(cart, ctx), encoding="utf-8")
        cmd = comando_claude(cart, rid)
        env = p.env()
        env.update(SB_ATTIVITA_DA=rid, SB_ATTIVITA_DIR=str(A.CARTELLA))
        t0 = time.time()
        _stato(
            cart,
            stato="in_elaborazione",
            sessione_id=p.id,
            inizio_sessione=_ora(),
            motivo="",
            dettaglio="",
        )
        _log(f"claude starts with your own login ({p.id})")
        if (cart / "ESITO.json").is_file():

            os.replace(cart / "ESITO.json", cart / f"ESITO-prima-{time.time_ns()}.json")
        with open(cart / "claude-esito.json", "w") as out, open(messaggio, "rb") as dentro:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdin=dentro,
                stdout=out,
                start_new_session=True,
                pass_fds=tuple(fd for fd in _DA_EREDITARE.values() if isinstance(fd, int)),
            )
            try:
                uscita = proc.wait(timeout=TETTO_SESSIONE_S)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, 15)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=30)
                uscita = "tempo"
        secondi = round(time.time() - t0, 1)
        risultato = _leggi(cart / "claude-esito.json")
        finale = _leggi(cart / "ESITO.json")
        if not finale and risultato.get("result"):
            finale = _esito_dal_result(str(risultato["result"]))
            if finale:
                finale["da"] = "risposta della sessione"
                _scrivi(cart / "ESITO.json", finale)
    _log(
        f"claude closed, exit {uscita}, {secondi} s, {risultato.get('num_turns') or '?'} turns"
    )
    return _chiudi(cart, rid, finale, risultato, uscita, secondi)


def _chiudi(cart: Path, rid: str, finale: dict, risultato: dict, uscita, secondi: float) -> int:
    misure = {
        "secondi_sessione": secondi,
        "turni": risultato.get("num_turns"),
        "durata_ms": risultato.get("duration_ms"),
        "costo_equivalente_usd": risultato.get("total_cost_usd"),
        "uscita_claude": uscita,
        "fine_sessione": _ora(),
    }
    if uscita == "tempo":
        _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_tempo"], **misure)
        return 1
    if not finale:
        dettaglio = str(risultato.get("result") or risultato.get("subtype") or f"uscita {uscita}")[
            :300
        ]
        _stato(
            cart,
            stato="non_riuscita",
            motivo=TESTI["motivo_senza_esito"],
            dettaglio=dettaglio,
            **misure,
        )
        return 1
    fatti = gesti(rid)
    veri = {g["id_task"] for g in fatti if isinstance(g["id_task"], str)} | {
        g["id_vista"] for g in fatti if isinstance(g.get("id_vista"), str) and g["id_vista"]
    }


    detti = {
        x
        for g in _lista(finale.get("gesti"))
        if isinstance(g, dict)
        for x in str(g.get("id") or "").split(",")
        if x
    }
    avviso = TESTI["motivo_gesti_diversi"] if detti - veri else ""
    risposta = _testo(finale.get("risposta")).strip()
    proposta = _proposta(finale.get("proposta"))
    altro = {}
    if finale.get("stato") == "fermo":

        stato = "non_si_puo"
        avviso = risposta or TESTI["non_si_puo_senza_perche"]
    elif (
        finale.get("stato") == "da_confermare" and proposta and not all(map(_eseguibile, proposta))
    ):



        stato = "non_riuscita"
        avviso = TESTI["motivo_proposta_storta"]
    elif finale.get("stato") == "da_confermare" and proposta:


        stato = "da_verificare"
        altro = {"conferma_cambi": proposta, "domanda_conferma": risposta}
    elif _testo(finale.get("domanda")).strip() or finale.get("stato") in (
        "domanda",
        "da_confermare",
    ):
        stato = "ti_chiede"
    else:
        stato = "fatta"
    if finale.get("annulla_richiesta") and isinstance(finale["annulla_richiesta"], str):
        altro["annullata_prima"] = _annulla_l_ultima(rid, finale["annulla_richiesta"])
    apri = _apri(finale.get("apri"))
    if apri:
        altro["apri"] = apri
    _stato(cart, stato=stato, motivo=avviso, **altro, **misure)
    return 0


def _eseguibile(riga: dict) -> bool:
    ""
    verbo = riga.get("verbo")
    return verbo == "nuova" if not riga.get("id") else verbo in VERBI_PROPOSTA and verbo != "nuova"


def _testo(x) -> str:
    ""
    return x if isinstance(x, str) else ""


def _lista(x) -> list:
    return x if isinstance(x, list) else []


def _apri(valore) -> dict | None:
    ""

    if not isinstance(valore, dict):
        return None
    out = {}
    vista = valore.get("vista")
    if isinstance(vista, str) and vista in {vid for vid, _ in A._tutte_le_viste(A._leggi_viste())}:
        out["vista"] = vista
    if isinstance(valore.get("filtro"), dict):
        try:
            f = A._valida("filtro", valore["filtro"], stretto=False)

            aree = A._aree()
            f["area"] = [aree.finale(aree.cerca(x) or x) for x in f["area"]]
            if any(x not in (None, [], "") for x in f.values()):

                out["filtro"] = f
        except A.Errore:
            pass
    task = valore.get("task")
    if isinstance(task, str) and task in A._carica():
        out["task"] = task
    return out or None


def _proposta(righe) -> list[dict]:
    ""
    if not isinstance(righe, list):
        return []
    task = A._carica()
    viste = None
    out = []
    for r in righe:
        if not isinstance(r, dict):
            continue
        if r.get("verbo") == "vista-imposta":

            if viste is None:
                viste = {
                    vid: A._nome_vista(vid, v) for vid, v in A._tutte_le_viste(A._leggi_viste())
                }
            vid = str(r.get("id") or "")
            out.append(
                {
                    "id": vid if vid in viste else "",
                    "titolo": str(r.get("titolo") or viste.get(vid, "")),
                    "cosa": str(r.get("cosa") or ""),
                    "verbo": "vista-imposta",
                }
            )
            continue
        tid = str(r.get("id") or "")
        t = task.get(tid) or {}
        riga = {
            "id": tid if t else "",
            "titolo": str(r.get("titolo") or t.get("titolo") or ""),
            "cosa": str(r.get("cosa") or ""),
        }


        verbo = r.get("verbo")
        if verbo == "descrizione" or (verbo is None and r.get("campo") == "descrizione"):
            verbo = "descrizione"
        if isinstance(verbo, str) and verbo in VERBI_PROPOSTA:
            riga["verbo"] = verbo
        if riga.get("verbo") == "descrizione" and (t.get("descrizione") or "").strip():
            riga["campo"] = "descrizione"
            riga["perde"] = t["descrizione"]
        out.append(riga)
    return out


def _annulla_l_ultima(rid: str, quale: str) -> dict:
    ""

    ultima = _leggi(casa() / rid / "CONTESTO.json").get("ultima_richiesta") or {}
    if ultima.get("id") != quale:
        return {"id": quale, "ok": False, "messaggio": TESTI["errore_sparita"]}
    try:
        r = annulla(quale)
    except Errore as e:
        return {"id": quale, "ok": False, "messaggio": TESTI[e.chiave]}
    return {"id": quale, "ok": True, "messaggio": r["messaggio"], "rimesse": r["rimesse"]}


def catena(rid: str) -> int:
    ""
    cart = casa() / rid
    with _lucchetto(cart / ".processo.lock", aspetta=False) as mio:
        if not mio:
            _log("another process is already working on this request")
            return 0


        _DA_EREDITARE[".processo.lock"] = mio
        try:
            return _catena_dentro(cart, rid)
        finally:
            _DA_EREDITARE.pop(".processo.lock", None)


def _catena_dentro(cart: Path, rid: str) -> int:
    _stato(cart, pid=os.getpid())
    richiesta = _leggi(cart / "RICHIESTA.json")
    s = _leggi(cart / "STATO.json")
    testo = s.get("testo") or ""
    if not testo:
        if richiesta.get("via") == "voce":
            try:
                testo = _trascrivi(cart, richiesta) or ""
            except Exception as e:  # noqa: BLE001 never «Transcribing it» with a dead process
                _stato(
                    cart,
                    stato="non_riuscita",
                    motivo=TESTI["motivo_whisper"],
                    dettaglio=repr(e)[:300],
                )
                return 1
            if not testo:
                return 0
        else:
            testo = richiesta.get("testo") or ""
    if richiesta.get("commento"):
        return _scrivi_commento(cart, rid, richiesta, testo)
    try:
        return _sessione(cart, rid, richiesta, testo)
    except Exception as e:  # noqa: BLE001 the request must not stay silent
        _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_processo"], dettaglio=repr(e)[:300])
        raise


def _scrivi_commento(cart: Path, rid: str, richiesta: dict, testo: str) -> int:
    ""

    _stato(cart, testo=testo)
    audio = f"voce/{rid}/{richiesta['audio']}" if richiesta.get("audio") else None
    try:
        A.commenta(
            [richiesta["commento"]], testo, da=rid, via="voce" if audio else "testo", audio=audio
        )
    except A.Errore as e:
        chiave = "motivo_task_sparita" if e.chiave == "errore_sparita" else "motivo_processo"
        _stato(cart, stato="non_riuscita", motivo=TESTI[chiave])
        return 1
    _stato(cart, stato="fatta", motivo="", fine_sessione=_ora())
    return 0





def _eventi() -> list[dict]:
    ""


    try:
        righe = (
            (A.CARTELLA / "eventi.jsonl").read_text(encoding="utf-8", errors="replace").split("\n")
        )
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            e = json.loads(r)
        except (ValueError, RecursionError):
            continue
        if isinstance(e, dict):
            out.append(e)

    return A._senza_lotti_a_meta(out)


def _tid(e: dict):
    ""
    x = e.get("id")
    return x if isinstance(x, str) else None


class _Letti(tuple):
    ""


    def imp_aree(self):
        if not hasattr(self, "_ia"):
            imp = A._imp()
            aree = A.Aree(imp, A._valori_area(self[0]))

            aree.con_task = {
                aree.finale(t.get("area")) for t in self[1].values() if not t["eliminata"]
            }
            self._ia = (imp, aree)
        return self._ia

    def della(self, rid: str) -> list[dict]:
        if not hasattr(self, "_per_da"):
            self._per_da = {}
            for e in self[0]:
                if isinstance(e.get("da"), str):
                    self._per_da.setdefault(e["da"], []).append(e)
        return self._per_da.get(rid, [])


def _letti(cache=None) -> tuple[list[dict], dict]:
    ""
    if isinstance(cache, _Letti):
        return cache
    if cache is not None:
        return _Letti(cache)
    tutti = _eventi()
    return _Letti((tutti, _carica(tutti)))


def _imp_aree(cache=None):
    return _letti(cache).imp_aree()


def _carica(tutti: list[dict]) -> dict:
    ""

    return A._carica(
        [
            e
            for e in tutti
            if e.get("tipo") not in ("crea", "cambia") or isinstance(e.get("campi"), dict)
        ]
    )


def _valore(campo: str, v, imp: dict | None = None, aree=None) -> str:
    oggi = C._adesso()
    if campo == "stato":
        return A._stato_di(imp or A._imp(), v)["nome"]
    if campo == "priorita":
        return A.PRIORITA.get(v, str(v))
    try:
        if campo == "scadenza" and v:
            return C._quando_parole(datetime.strptime(v, "%Y-%m-%d"), oggi)
        if campo == "stima":
            return A.stima_frase(v)
        if campo == "area":
            aree = aree or A._aree()
            return aree.nome(aree.finale(v))
        if campo == "pianificata" and v:
            return A._pianificata_parole(v, oggi)
    except (TypeError, ValueError, AttributeError):
        pass
    return str(v)


def _frase_gesto(e: dict, titolo: str, imp: dict | None = None, aree=None) -> str:
    imp = imp or A._imp()
    tipo, campi = e.get("tipo"), e.get("campi") or {}
    if not isinstance(campi, dict):
        campi = {}
    if tipo == "crea":

        pezzi = []
        if campi.get("priorita") not in (None, 2):
            pezzi.append(
                TESTI["gesto_campo_priorita"].format(
                    valore=_valore("priorita", campi["priorita"], imp)
                )
            )
        if campi.get("scadenza"):
            pezzi.append(
                TESTI["gesto_campo_scade"].format(
                    valore=_valore("scadenza", campi["scadenza"], imp)
                )
            )
        if campi.get("pianificata"):
            pezzi.append(
                TESTI["gesto_campo_pianificata"].format(
                    valore=_valore("pianificata", campi["pianificata"], imp)
                )
            )
        if campi.get("stima"):
            pezzi.append(
                TESTI["gesto_campo_stima"].format(valore=_valore("stima", campi["stima"], imp))
            )
        if campi.get("area"):
            pezzi.append(
                TESTI["gesto_campo_area"].format(valore=_valore("area", campi["area"], imp, aree))
            )
        if campi.get("stato") and campi["stato"] != A._predefinito(imp):
            pezzi.append(
                TESTI["gesto_campo_stato"].format(valore=_valore("stato", campi["stato"], imp))
            )
        if pezzi:
            return TESTI["gesto_nuova_con"].format(titolo=titolo, campi=", ".join(pezzi))
        return TESTI["gesto_nuova"].format(titolo=titolo)
    if tipo in ("elimina", "ripristina"):
        return TESTI[f"gesto_{tipo}"].format(titolo=titolo)
    if tipo == "commento":
        return TESTI["gesto_commento"].format(
            titolo=titolo, testo=_corto(_cap(" ".join((e.get("testo") or "").split())), 160)
        )
    if tipo in ("commento_tolto", "commento_rimesso"):
        return TESTI["gesto_commento_tolto"].format(titolo=titolo)


    pred, frasi = [], []
    for k, v in campi.items():
        if k == "chiusa":
            continue
        if k == "stato" and A._stato_di(imp, v)["tipo"] == "fatta":
            frasi.append(TESTI["gesto_fatta"].format(titolo=titolo))
            pred.append(TESTI["gesto_e_fatta"])
        elif (
            k == "stato"
            and A._chiuso(imp, (e.get("prima") or {}).get("stato"))
            and not A._chiuso(imp, v)
        ):
            frasi.append(TESTI["gesto_riaperta"].format(titolo=titolo))
            pred.append(TESTI["gesto_e_riaperta"])
        elif k in ("scadenza", "stima", "pianificata") and v is None:
            chiave = {"scadenza": "data", "stima": "stima", "pianificata": "pianificata"}[k]
            frasi.append(TESTI[f"gesto_{chiave}_tolta"].format(titolo=titolo))
            pred.append(TESTI[f"gesto_e_{chiave}_tolta"])
        elif k == "scadenza":
            frasi.append(TESTI["gesto_data"].format(titolo=titolo, valore=_valore(k, v, imp)))
            pred.append(TESTI["gesto_e_data"].format(valore=_valore(k, v, imp)))
        elif k in ("stato", "priorita", "stima", "area", "pianificata"):
            frasi.append(TESTI[f"gesto_{k}"].format(titolo=titolo, valore=_valore(k, v, imp, aree)))
            pred.append(TESTI[f"gesto_e_{k}"].format(valore=_valore(k, v, imp, aree)))
        elif k == "titolo":
            frasi.append(TESTI["gesto_titolo"].format(titolo=_cap(v)))
            pred.append(None)
        elif k == "descrizione":
            vecchia = str((e.get("prima") or {}).get("descrizione") or "").rstrip()
            nuova = str(v or "")

            if nuova.startswith(vecchia) and len(nuova) > len(vecchia):
                aggiunta = " ".join(nuova[len(vecchia) :].split())
                frasi.append(
                    TESTI["gesto_descrizione_aggiunta"].format(
                        titolo=titolo, testo=_corto(_cap(aggiunta), 160)
                    )
                )
                pred.append(None)
            else:
                frasi.append(TESTI["gesto_descrizione"].format(titolo=titolo))
                pred.append(None)
        else:
            frasi.append(TESTI["gesto_altro"].format(titolo=titolo))
            pred.append(None)
    if len(frasi) > 1 and all(pred):
        unite = pred[0] if len(pred) == 1 else ", ".join(pred[:-1]) + TESTI["gesto_e"] + pred[-1]
        return TESTI["gesto_campi"].format(titolo=titolo, cambi=unite)
    return ", ".join(frasi) or TESTI["gesto_altro"].format(titolo=titolo)


def _viste_della(rid: str) -> list[dict]:
    ""
    try:


        righe = (
            (casa() / rid / "VISTE.jsonl").read_text(encoding="utf-8", errors="replace").split("\n")
        )
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            d = json.loads(r)
        except (ValueError, RecursionError):
            continue
        if isinstance(d, dict) and isinstance(d.get("annulla"), list):
            out.append(d)
    return out


def gesti(rid: str, cache=None) -> list[dict]:
    ""

    cache = _letti(cache)
    task = cache[1]
    imp, aree = cache.imp_aree()
    out = []
    for e in cache.della(rid):
        if e.get("da") != rid:
            continue
        t = task.get(_tid(e)) or {}
        campi = e.get("campi") if isinstance(e.get("campi"), dict) else {}
        titolo = t.get("titolo") or campi.get("titolo") or ""
        out.append(
            {
                "id_task": _tid(e),
                "titolo": titolo,
                "tipo": e.get("tipo"),
                "cosa": _frase_gesto(e, _cap(titolo), imp, aree),
                "quando": e.get("t"),
            }
        )
    sue_viste = _viste_della(rid)
    if sue_viste:
        nomi = {vid: A._nome_vista(vid, v) for vid, v in A._tutte_le_viste(A._leggi_viste())}
        for d in sue_viste:
            out.append(
                {
                    "id_task": "",
                    "id_vista": d.get("id") or "",
                    "titolo": nomi.get(d.get("id"), ""),
                    "tipo": "vista",
                    "cosa": TESTI["gesto_vista"].format(nome=nomi.get(d.get("id"), "")),
                    "quando": d.get("t"),
                }
            )
    return out


def _elenco(titoli: list[str]) -> str:
    t = [f"«{x}»" for x in titoli]
    return t[0] if len(t) == 1 else ", ".join(t[:-1]) + " and " + t[-1]


def _rimetti(task: dict, tid: str, indietro: dict, da: str) -> None:
    ""

    t = task[tid]
    campi = {k: v for k, v in indietro.items() if k != "chiusa" and t.get(k) != v}
    if not campi:
        return
    if "stato" in campi:
        chiuso = A._chiuso(A._imp(), campi["stato"])
        campi["chiusa"] = (indietro.get("chiusa") or A._ora()) if chiuso else None
    evento = {
        "t": A._ora(),
        "id": tid,
        "tipo": "cambia",
        "da": da,
        "campi": campi,
        "prima": {k: t.get(k) for k in campi},
    }
    A._scrivi(evento)
    A._applica(task, evento)


def annulla(rid: str) -> dict:
    ""



    cart = _cartella(rid)
    with _lucchetto(cart / ".annulla.lock"):
        return _annulla_una(cart, rid)


def _annulla_una(cart: Path, rid: str) -> dict:
    s = _leggi(cart / "STATO.json")
    if not STATI.get(s.get("stato"), ("", True))[1] or _vivo(cart):
        raise Errore("errore_in_corso")
    da = f"annulla:{rid}"
    viste = _viste_della(rid)





    with A._Lucchetto():
        if (cart / "ANNULLA.json").is_file():
            raise Errore("errore_gia_annullata")
        tutti = _eventi()
        if not any(e.get("da") == rid for e in tutti) and not viste:

            return {"ok": True, "messaggio": TESTI["annullato_zero"], "rimesse": 0, "saltate": []}
        gia_scritte = {_tid(e) for e in tutti if e.get("da") == da and _tid(e)}
        if gia_scritte:
            _togli_aree_nate(rid, _carica(tutti), da)



            return _esito_annulla(cart, gia_scritte, {}, [], 0)


        toccate_dopo = set()
        primo = next((i for i, e in enumerate(tutti) if e.get("da") == rid), len(tutti))
        for e in tutti[primo:]:
            if e.get("da") not in (rid, da) and _tid(e):
                toccate_dopo.add(_tid(e))
        task = _carica(tutti)
        rimesse, lasciate, saltate = set(), {}, []
        for e in reversed([e for e in tutti if e.get("da") == rid]):
            tid, tipo = _tid(e), e.get("tipo")
            t = task.get(tid)
            if t is None:
                continue
            try:
                if tipo == "crea" and tid in toccate_dopo:
                    lasciate[tid] = t["titolo"]
                elif tipo == "crea" and not t["eliminata"]:
                    A._segna_dentro(task, tid, "elimina", da)
                    rimesse.add(tid)
                elif tipo == "elimina" and t["eliminata"]:
                    A._segna_dentro(task, tid, "ripristina", da)
                    rimesse.add(tid)
                elif tipo == "ripristina" and not t["eliminata"]:
                    A._segna_dentro(task, tid, "elimina", da)
                    rimesse.add(tid)
                elif tipo == "commento" and t["eliminata"]:

                    if e.get("eid") in t.get("commenti", {}):
                        lasciate[tid] = t["titolo"]
                elif tipo == "commento":

                    if e.get("eid") in t.get("commenti", {}):
                        inv = {
                            "t": A._ora(),
                            "id": tid,
                            "tipo": "commento_tolto",
                            "da": da,
                            "commento": e["eid"],
                        }
                        A._scrivi(inv)
                        A._applica(task, inv)
                        rimesse.add(tid)
                elif tipo == "cambia":
                    prima, campi = e.get("prima") or {}, e.get("campi") or {}
                    if not isinstance(prima, dict) or not isinstance(campi, dict):
                        continue
                    scritti = [k for k in campi if k in A.CAMPI]
                    indietro = {k: prima.get(k) for k in scritti if t.get(k) == campi[k]}
                    if len(indietro) < len(scritti) or (indietro and t["eliminata"]):
                        lasciate[tid] = t["titolo"]
                    if indietro and not t["eliminata"]:
                        if "stato" in indietro:
                            indietro["chiusa"] = prima.get("chiusa")
                        _rimetti(task, tid, indietro, da)
                        rimesse.add(tid)
            except A.Errore:
                lasciate[tid] = t["titolo"]
        for tid, titolo in lasciate.items():
            chiave = "saltata_in_parte" if tid in rimesse else "saltata"
            saltate.append(TESTI[chiave].format(titolo=titolo))



        A._svuota_coda()
        _togli_aree_nate(rid, task, da)
        if not viste:
            return _esito_annulla(cart, rimesse, lasciate, saltate, 0)
    viste_rimesse = 0


    for d in reversed(viste):
        r = (
            A.esegui_vista(d["annulla"][0], [str(x) for x in d["annulla"][1:]])
            if _vista_ok(d["annulla"])
            else {}
        )
        if r.get("ok"):
            viste_rimesse += 1
    return _esito_annulla(cart, rimesse, lasciate, saltate, viste_rimesse)


def _togli_aree_nate(rid: str, task: dict, da: str) -> int:
    ""


    righe = A._righe_impostazioni()
    nate = [
        r["id"]
        for r in righe
        if r.get("da") == rid and r.get("cosa") == "area-nuova" and isinstance(r.get("id"), str)
    ]
    if not nate:
        return 0
    toccate = {r.get("id") for r in righe if r.get("id") in nate and r.get("da") != rid}
    imp = A._imp()
    tolte = 0
    for aid in nate:
        d = imp["aree"].get(aid)
        if aid in toccate or not d or d.get("tolta"):
            continue
        if any(not t["eliminata"] and t.get("area") == aid for t in task.values()):
            continue
        prima = {"tolta": False, "unita_in": d.get("unita_in"), "senza": bool(d.get("senza"))}
        A._scrivi_impostazione({"voce": "area", "cosa": "area-togli", "id": aid,
                                "dopo": {"tolta": True, "prima_togli": prima}, "prima": prima, "da": da})
        tolte += 1
    return tolte


def _esito_annulla(
    cart: Path, rimesse: set, lasciate: dict, saltate: list, viste_rimesse: int
) -> dict:
    ""
    n = len(rimesse)
    fatto = TESTI["annullato_uno"] if n == 1 else TESTI["annullato_tanti"].format(n=A.numero(n))
    if not n and viste_rimesse:
        fatto = (
            TESTI["annullato_vista"]
            if viste_rimesse == 1
            else TESTI["annullato_viste"].format(n=A.numero(viste_rimesse))
        )
    titoli = list(lasciate.values())
    if not n and not viste_rimesse and titoli:
        chiave = "annullato_niente_dopo_una" if len(titoli) == 1 else "annullato_niente_dopo_tante"
        messaggio = TESTI[chiave].format(titolo=titoli[0], titoli=_elenco(titoli))
    elif not n and not viste_rimesse:
        messaggio = TESTI["annullato_zero"]
    elif titoli:
        chiave = "annullato_in_parte_una" if len(titoli) == 1 else "annullato_in_parte_tante"
        messaggio = TESTI[chiave].format(fatto=fatto, titolo=titoli[0], titoli=_elenco(titoli))
    else:
        messaggio = fatto
    if n or viste_rimesse:

        _scrivi(
            cart / "ANNULLA.json",
            {
                "quando": _ora(),
                "rimesse": sorted(rimesse),
                "saltate": saltate,
                "messaggio": messaggio,
                **({"viste": viste_rimesse} if viste_rimesse else {}),
            },
        )
    out = {
        "ok": True,
        "messaggio": messaggio,
        "rimesse": n,
        "saltate": list(dict.fromkeys(saltate)),
    }
    if viste_rimesse:
        out["viste_rimesse"] = viste_rimesse
    return out


def _vista_ok(args: list) -> bool:
    ""
    return bool(args) and isinstance(args[0], str) and args[0].startswith("vista-")





def _riprendi_se_morta(cart: Path, s: dict) -> dict:
    ""
    stato = s.get("stato")
    if STATI.get(stato, ("", True))[1] or _vivo(cart):
        return s
    eta = _secondi_da(s, "aggiornato") if s.get("aggiornato") else _secondi_da(s, "partito")
    if eta is not None and eta < NASCITA_S:
        return s
    if int(s.get("riavvii") or 0) >= RIAVVII_MAX:
        return _stato(cart, stato="non_riuscita", motivo=TESTI["motivo_processo"])
    s = _stato(cart, riavvii=int(s.get("riavvii") or 0) + 1, partito=_ora())
    _parti(cart.name)
    return _leggi(cart / "STATO.json") or s


def _quando(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    oggi = C._adesso()
    giorno = (
        "today"
        if d.date() == oggi.date()
        else "yesterday"
        if d.date() == (oggi - timedelta(days=1)).date()
        else C._il(d, oggi)
    )

    testo = TESTI["quando_alle"].format(giorno=giorno, ora=f"{d:%H:%M}")
    return testo[:1].upper() + testo[1:]


def _filo(r: dict) -> str:
    ""
    primo, visti = r.get("id") or "", set()
    dopo = r.get("dopo") or ""
    while dopo and dopo not in visti and len(visti) < 50:
        visti.add(dopo)
        primo = dopo
        dopo = _leggi(casa() / dopo / "RICHIESTA.json").get("dopo") or ""
        if not isinstance(dopo, str):
            break
    return primo


def _corto(testo: str, n: int) -> str:
    ""
    if len(testo) <= n:
        return testo
    taglio = testo[:n].rsplit(" ", 1)[0] if " " in testo[:n] else testo[:n]
    return taglio.rstrip(" ,;.") + "…"


def _cap(titolo) -> str:
    ""
    return str(titolo or "").replace("«", "“").replace("»", "”")




_TESTI_RICHIESTA = ("creata", "via", "dopo", "audio", "testo", "commento")
_TESTI_STATO = ("stato", "testo", "sentito", "motivo", "domanda_conferma")


def _solo_testi(d: dict, campi: tuple) -> dict:
    sbagliati = [k for k in campi if d.get(k) is not None and not isinstance(d[k], str)]
    return {**d, **dict.fromkeys(sbagliati)} if sbagliati else d



_PROPONE = re.compile(
    r"\b(?:se vuoi|se ti va|vuoi che|ti va (?:di|se)|posso (?:metter|far|segnar|spostar|aggiunger|scriver|crear|pianificar)"
    r"|preferisci|in alternativa|ti propongo|se preferisci)",
    re.I,
)


def _propone(testo) -> bool:
    return isinstance(testo, str) and bool(_PROPONE.search(testo))


def voce_di(cart: Path, riprendi: bool = True, cache=None) -> dict:
    r = _solo_testi(_leggi(cart / "RICHIESTA.json"), _TESTI_RICHIESTA)
    s = _leggi(cart / "STATO.json")
    if riprendi:
        s = _riprendi_se_morta(cart, s)
    s = _solo_testi(s, _TESTI_STATO)
    e = _leggi(cart / "ESITO.json")
    an = _leggi(cart / "ANNULLA.json")
    stato = s.get("stato") or "in_coda"
    finita = STATI.get(stato, ("", False))[1]
    g = gesti(cart.name, cache)
    testo = s.get("testo") or s.get("sentito") or r.get("testo") or ""
    if r.get("via") == "voce":
        detto = TESTI["ho_sentito"].format(testo=testo) if testo else ""
    else:
        detto = TESTI["hai_scritto"].format(testo=testo) if testo else ""


    dubbi = [
        TESTI.get(
            "senza_parlato" if d == "senza_parlato" else f"dubbio_{d}", TESTI["stato_da_verificare"]
        )
        for d in (s.get("dubbi") if isinstance(s.get("dubbi"), list) else [])
    ]
    cambi = s.get("conferma_cambi") if stato == "da_verificare" else None
    if cambi:

        dubbi = [s.get("domanda_conferma")] if s.get("domanda_conferma") else []
        for c in cambi[:RIGHE_PROPOSTA]:
            dubbi.append(TESTI["proposta_riga"].format(titolo=c["titolo"], cosa=c["cosa"]).strip())
            if c.get("perde"):
                dubbi.append(
                    TESTI["proposta_perde"].format(
                        testo=_corto(_cap(" ".join(c["perde"].split())), 600)
                    )
                )
        if len(cambi) > RIGHE_PROPOSTA:
            altre = len(cambi) - RIGHE_PROPOSTA
            dubbi.append(
                TESTI["proposta_altra"]
                if altre == 1
                else TESTI["proposta_altre"].format(n=A.numero(altre))
            )
    prima = s.get("annullata_prima") or {}
    frase_gesti = "" if g or not finita else TESTI["nessun_gesto"]
    if prima and not g:
        frase_gesti = prima.get("messaggio") or frase_gesti
    gia_fatto = ""
    if g and stato in ("ti_chiede", "da_verificare"):
        gia_fatto = (
            TESTI["gia_fatto_uno"]
            if len(g) == 1
            else TESTI["gia_fatto_tanti"].format(n=A.numero(len(g)))
        )
    nome = (
        TESTI["stato_da_confermare"]
        if cambi
        else TESTI.get(f"stato_{stato}", TESTI["stato_sconosciuto"])
    )
    return {
        "id": cart.name,
        "creata": r.get("creata"),
        "quando": _quando(r.get("creata") or ""),
        "via": r.get("via"),
        "audio": str(cart / r["audio"]) if r.get("audio") else "",

        "durata_s": _durata(r.get("durata_app"))
        or _durata((s.get("misure") or {}).get("durata_s")),
        "dopo": r.get("dopo") or "",
        "stato": stato,
        "stato_nome": TESTI["stato_annullata"] if an else nome,
        "finita": finita,
        "annullata": bool(an),
        "testo": testo,
        "detto": detto,
        "dubbi": dubbi,
        "motivo": s.get("motivo") or "",

        "capito": _testo(e.get("capito")),
        "risposta": _testo(e.get("risposta")),

        "domanda": _testo(e.get("domanda"))
        or (_testo(e.get("risposta")) if stato == "ti_chiede" else ""),
        "gesti": g,
        "gesti_detti": _lista(e.get("gesti")),
        "frase_gesti": frase_gesti,


        "gia_fatto": gia_fatto,
        "conferma_cambi": cambi or None,
        "annullata_prima": prima or None,
        "annulla": ["voce-annulla", cart.name] if g and finita and not an else None,

        "conferma": ["voce-conferma", cart.name] if stato == "da_verificare" and not an else None,
        "riprova": ["voce-riprova", cart.name] if stato == "non_riuscita" and not an else None,


        "rispondi": ["voce-testo", "<your answer>", "--dopo", cart.name]
        if stato == "ti_chiede" or (stato == "non_si_puo" and not an and _propone(s.get("motivo")))
        else None,
        "annullate": an.get("saltate") or [] if an else [],

        "filo": _filo({**r, "id": cart.name}),
        "da_secondi": _da_secondi(r, finita),
        "apri": s.get("apri") or None,
        "commento": r.get("commento") or None,
        "misure": {
            k: s.get(k)
            for k in (
                "secondi_sessione",
                "turni",
                "sessione_id",
                "inizio_sessione",
                "fine_sessione",
            )
            if s.get(k) is not None
        },
    }


def _da_secondi(r: dict, finita: bool) -> int | None:
    if finita:
        return None
    if type(r.get("creata_ms")) is int:
        return max(0, (A._adesso_ms() - r["creata_ms"]) // 1000)
    try:
        return max(
            0, int((C._adesso() - datetime.fromisoformat(r.get("creata") or "")).total_seconds())
        )
    except ValueError:
        return None


def stato(solo: str = "") -> dict:
    cartelle = list(reversed(_richieste()))
    if solo:
        cartelle = [c for c in cartelle if c.name == solo]


    cache = _letti() if cartelle[:RECENTI] else None
    voci = []
    for c in cartelle[:RECENTI]:

        try:
            voci.append(voce_di(c, cache=cache))
        except Exception:  # noqa: BLE001
            continue
    aperte = sum(not v["finita"] for v in voci)
    return {
        "ok": True,

        "contesto": True,

        "contratto": A.CONTRATTO,
        "richieste": voci,
        "in_corso": aperte,
        "rileggi_fra_s": RILEGGI_S if aperte else 0,
        "testi": TESTI,
    }


def _metti_da_parte_il_si(cart: Path) -> None:
    ""
    vecchio = cart / "CONFERMATE.json"
    if vecchio.exists() or vecchio.is_symlink():
        os.replace(vecchio, cart / f"CONFERMATE-prima-{time.time_ns()}.json")


def conferma(rid: str, corretto: str = "") -> dict:
    cart = _cartella(rid)
    s = _leggi(cart / "STATO.json")
    if s.get("stato") != "da_verificare" or _vivo(cart):
        raise Errore("errore_non_da_verificare")
    if (cart / "ANNULLA.json").is_file():
        raise Errore("errore_annullata_non_riparte")
    if corretto.strip():


        _metti_da_parte_il_si(cart)
    if s.get("conferma_cambi") and not corretto.strip():


        cambi = s["conferma_cambi"]
        _metti_da_parte_il_si(cart)
        _scrivi(
            cart / "CONFERMATE.json",
            {
                "quando": _ora(),
                "ids": sorted({c["id"] for c in cambi if c.get("id")}),
                "nuove": sum(not c.get("id") and c.get("verbo") == "nuova" for c in cambi),
                "proposta": cambi,
            },
        )
        _stato(cart, stato="in_coda", confermata=_ora(), partito=_ora(), motivo="")
        _parti(rid)
        return {
            "ok": True,
            "id": rid,
            "messaggio": TESTI["ricevuta_si"],
            "rileggi_fra_s": RILEGGI_S,
        }
    if s.get("conferma_cambi"):

        _stato(cart, conferma_cambi=None, domanda_conferma="")
    testo = (corretto or s.get("sentito") or s.get("testo") or "").strip()
    if not testo:
        raise Errore("errore_testo")
    _stato(
        cart,
        stato="in_coda",
        testo=testo,
        confermato=_ora(),
        corretto=bool(corretto),
        partito=_ora(),
    )
    _parti(rid)
    return {
        "ok": True,
        "id": rid,
        "messaggio": TESTI["ricevuta_conferma"],
        "rileggi_fra_s": RILEGGI_S,
    }


def riprova(rid: str) -> dict:
    cart = _cartella(rid)
    s = _leggi(cart / "STATO.json")
    if s.get("stato") != "non_riuscita" or _vivo(cart):
        raise Errore("errore_non_riprova")
    if (cart / "ANNULLA.json").is_file():
        raise Errore("errore_annullata_non_riparte")
    _stato(
        cart,
        stato="in_coda" if s.get("testo") else "in_trascrizione",
        riavvii=0,
        partito=_ora(),
        motivo="",
    )
    _parti(rid)
    return {
        "ok": True,
        "id": rid,
        "messaggio": TESTI["ricevuta_riprova"],
        "rileggi_fra_s": RILEGGI_S,
    }





def esegui(argv: list[str]) -> dict:
    ""
    try:

        argv = [unicodedata.normalize("NFC", a) for a in argv]
        verbo, resto = (argv[0], argv[1:]) if argv else ("voce-stato", [])

        una_volta = ""
        if verbo in ("voce", "voce-testo") and len(resto) >= 2 and resto[-2] == "--una-volta":
            una_volta, resto = resto[-1], resto[:-2]
        if verbo == "voce":
            liberi, o = _opzioni(resto, ("--durata", "--dopo", "--vista", "--scelte", "--commento"))
            if len(liberi) != 1:
                raise Errore("errore_audio")
            return nuova("voce", audio=liberi[0], durata=o.get("durata"), dopo=o.get("dopo", ""),
                         vista=o.get("vista", ""), scelte=o.get("scelte", ""), commento=o.get("commento", ""),
                         una_volta=una_volta)
        if verbo == "voce-testo":
            liberi, o = _opzioni(resto, ("--dopo", "--vista", "--scelte", "--commento"))
            return nuova("testo", testo=" ".join(liberi), dopo=o.get("dopo", ""), vista=o.get("vista", ""),
                         scelte=o.get("scelte", ""), commento=o.get("commento", ""), una_volta=una_volta)
        if verbo == "voce-stato":
            _, o = _opzioni(resto, ("--id",))
            return stato(o.get("id", ""))
        if verbo == "voce-conferma" and resto:
            return conferma(resto[0], " ".join(resto[1:]))
        if verbo == "voce-riprova" and len(resto) == 1:
            return riprova(resto[0])
        if verbo == "voce-annulla" and len(resto) == 1:
            return annulla(resto[0])
        return {"ok": False, "errore": TESTI["errore_comando"]}
    except Errore as e:
        return {"ok": False, "errore": TESTI[e.chiave]}
    except Exception as e:  # noqa: BLE001 the app always expects JSON, never a traceback
        return {"ok": False, "errore": TESTI["errore_motore"], "dettaglio": type(e).__name__}


def main(argv: list[str]) -> int:
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if argv[:1] == ["sottofondo"] and len(argv) == 2:
        return catena(argv[1])
    print(json.dumps(esegui(argv), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
