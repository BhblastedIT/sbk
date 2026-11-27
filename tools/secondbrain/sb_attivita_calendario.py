#!/usr/bin/env python3
"""Your Google calendars in the tasks section: the week as Google shows it, the free slots, and the refresh."""




























































from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
sys.path.insert(0, str(QUI))
import sb_cose as C  # noqa: E402 the timezone, the fixable current time, the names of months and days

FUSO = C.FUSO
VENV = ROOT / ".venv" / "bin" / "python"
SCARICO_REPO = ROOT / "tools" / "calendar" / "ca-l0-download.py"


VERSIONE_INDICE = 1

GIORNI_PRIMA = 92
GIORNI_DOPO = 366

INDICE_VECCHIO_GIORNI = 7

DURATA_MINIMA = 15

TASK_SENZA_STIMA = 30

SCATTO = 15

VECCHI_DOPO_MIN = 15

INDIETRO_MIN = 30

TETTO_SCARICO_S = 300

GIA_CHIESTO_S = 15

QUOTA_MEMORIA = 0.02


GIORNO_PRIMO = date(2, 1, 1)
GIORNO_ULTIMO = date(9998, 12, 31)

FORMA_GIORNO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

FORMA_ORA = re.compile(r"([0-9]{1,2})(?:[:.]([0-9]{2}))?")

ISTANTE_MINIMO = -62_104_060_800
ISTANTE_MASSIMO = 253_370_678_400

SETTIMANA_PARTENZA = {
    "inizio": 0,
    "giorni": [0, 1, 2, 3, 4],
    "dalle": 9 * 60,
    "alle": 19 * 60,
    "giornata_minuti": 8 * 60,
}
GIORNI_BREVI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
NOMI_GIORNI = {
    "lunedi": 0,
    "lunedì": 0,
    "lun": 0,
    "martedi": 1,
    "martedì": 1,
    "mar": 1,
    "mercoledi": 2,
    "mercoledì": 2,
    "mer": 2,
    "giovedi": 3,
    "giovedì": 3,
    "gio": 3,
    "venerdi": 4,
    "venerdì": 4,
    "ven": 4,
    "sabato": 5,
    "sab": 5,
    "domenica": 6,
    "dom": 6,
}

RISPOSTE = {
    "accepted": "accettato",
    "tentative": "forse",
    "needsAction": "da_rispondere",
    "declined": "rifiutato",
}


COLORI_EVENTO = {
    "1": "#7986cb",
    "2": "#33b679",
    "3": "#8e24aa",
    "4": "#e67c73",
    "5": "#f6bf26",
    "6": "#f4511e",
    "7": "#039be5",
    "8": "#616161",
    "9": "#3f51b5",
    "10": "#0b8043",
    "11": "#d50000",
}

TAVOLOZZA = (
    "#039be5",
    "#33b679",
    "#8e24aa",
    "#e67c73",
    "#f6bf26",
    "#f4511e",
    "#7986cb",
    "#0b8043",
    "#3f51b5",
    "#d50000",
    "#616161",
)
CHIARI = {"#f6bf26"}


# Mailbox slug -> display label; load from user config. Empty by default.
NOMI_CASELLE: dict[str, str] = {}
# Timezone key -> city label override; empty means derive from the zoneinfo key.
CITTA: dict[str, str] = {}

COLONNE_INDICE = (
    "id",
    "summary",
    "start_datetime",
    "end_datetime",
    "start_timezone",
    "end_timezone",
    "location",
    "organizer_email",
    "attendees",
    "status",
    "calendar_id",
    "conference_url",
    "event_type",
    "transparency",
    "color_id",
    "html_link",
    "recurring_event_id",
    "self_status",
)

TESTI = {

    "titolo_settimana_mese": "{da}-{a} {mese} {anno}",
    "titolo_settimana_due_mesi": "{da} {mese_da}-{a} {mese_a} {anno}",
    "titolo_settimana_due_anni": "{da} {mese_da} {anno_da}-{a} {mese_a} {anno_a}",
    "titolo_giorno": "{giorno} {n} {mese} {anno}",
    "quando_giorno": "{giorno} {n}",
    "fuso_nome": "{citta} time",
    "scala_giorno": "Day",
    "scala_settimana": "Week",
    "scala_mese": "Month",
    "oggi": "Today",
    "aggiorna": "Refresh",
    "aiuto_aggiorna": "Download the Google calendars now. Meanwhile the week stays as it is.",
    "calendari": "Calendars",
    "aiuto_calendari": "Choose which calendars to see.",
    "mostra_rifiutati": "Also show declined events",
    "tutto_il_giorno": "All day",
    "altri_n": "{n} more",
    "apri_in_google": "Open in Google Calendar",
    "videochiamata": "Join the video call",
    "togli_dal_calendario": "Remove from the calendar",
    "trova_un_posto": "Find a time",
    "da_ripianificare": "To reschedule",
    "aiuto_da_ripianificare": "You'd put them at a time already past and they're not done.",

    "aggiornati": "Calendars updated {quando}",
    "aggiornata_casella": "Updated {quando}",
    "quando_adesso": "just now",
    "quando_alle": "at {ora}",
    "quando_ieri": "at {ora} yesterday",
    "quando_il": "{il} at {ora}",
    "aggiornati_mai": "The calendars have never been updated",
    "aggiornati_in_corso": "Updating the calendars",
    "calendari_mancano": "I can't find the Google calendars on this Mac",
    "casella_ferma": "{nome} didn't update",

    "casella_senza_nome": "A mailbox without a name",
    "motivo_senza_login": "It needs to be reconnected to Google. The browser can't open from here.",
    "motivo_accesso": "Google didn't grant access.",
    "motivo_identita": "The access belongs to another mailbox.",
    "motivo_errore": "Google responded with an error.",
    "motivo_mai": "It has never updated.",
    "motivo_indietro": "The latest update didn't arrive.",
    "motivo_rotto": "The downloaded calendar can't be read.",
    "aggiorna_partito": "Updating the calendars",
    "aggiorna_gia": "Already updating the calendars",
    "aggiorna_fatto": "Calendars updated",
    "aggiorna_occupato": "Another calendar update was already running. I'm showing you the week with what's there.",
    "aggiorna_errore": "Some calendars didn't update.",
    "aggiorna_tempo": "Google didn't respond in time. I'm showing you the week with what was there.",
    "aggiorna_memoria": "The Mac is under strain and I didn't update the calendars. Try again in a few minutes.",
    "aggiorna_manca": "I can't find the program that downloads the calendars.",

    "senza_titolo": "Untitled",
    "orario": "from {da} to {a}",
    "orario_giorni": "from {giorno_da} at {da} to {giorno_a} at {a}",
    "aiuto_evento": "{orario}, {calendario}.",
    "aiuto_evento_tutto_il_giorno": "All day, {calendario}.",
    "risposta_forse": "You replied maybe.",
    "risposta_da_rispondere": "You haven't replied yet.",
    "risposta_rifiutato": "You declined it.",
    "evento_libero": "Marked as free.",
    "evento_incerto": "Not yet confirmed.",
    "continua_prima": "Starts the day before.",
    "continua_dopo": "Ends the next day.",
    "calendario_altro": "Another calendar of {casella}",
    "calendario_altro_n": "Another calendar of {casella} {n}",

    "aiuto_task": "Scheduled {orario}.",
    "aiuto_task_senza_durata": "There's no time estimate, I count it as {durata}.",
    "aiuto_task_oltre_scadenza": "It's scheduled after the due date.",
    "aiuto_task_sovrapposta": "It overlaps with an appointment.",

    "buco": "{quando} at {ora}",
    "buco_oggi": "today",
    "buco_domani": "tomorrow",
    "buco_giorno": "{giorno} {n}",
    "buchi_uno": "One free slot for {durata}.",
    "buchi_tanti": "{n} free slots for {durata}.",
    "buchi_nessuno": "In this week's and next week's working hours there's no free slot for {durata}.",
    "breve_minuti": "{m} min",
    "breve_ore": "{h} h",
    "breve_ore_minuti": "{h} h {mm}",

    "errore_comando": "I don't know this calendar command.",
    "errore_giorno": "I don't understand this day.",
    "errore_task": "This task no longer exists.",
    "errore_durata": "The time must be written in minutes, from 1 to 1440.",
    "errore_pianificata": "I don't understand this time. Write the day and time, for example tomorrow at 15:00.",
    "errore_interno": "The calendar had a problem. Try again.",
}


class Errore(Exception):
    def __init__(self, chiave: str):
        super().__init__(chiave)
        self.chiave = chiave





def cartella_attivita() -> Path:
    return Path(
        os.environ.get("SB_ATTIVITA_DIR")
        or Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "attivita"
    )


def cartella_cache() -> Path:
    return cartella_attivita() / "cache"


def cartella_calendari() -> Path:
    return Path(
        os.environ.get("SB_CALENDARI_DIR")
        or Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "calendars"
    )


def file_marche() -> Path:
    return Path(
        os.environ.get("SB_CALENDARI_MARCHE") or cartella_calendari().parent / "last-runs.json"
    )


def file_caselle() -> Path:
    return Path(
        os.environ.get("SB_CALENDARI_CASELLE")
        or cartella_calendari().parent / "emails" / "accounts.json"
    )


def file_indice() -> Path:
    return cartella_cache() / "calendari-indice.json"


def file_stato_aggiorna() -> Path:
    return cartella_cache() / "calendari-aggiorna.json"


def lucchetto_indice() -> Path:
    return cartella_cache() / ".lucchetto-calendari-indice"


def lucchetto_aggiorna() -> Path:
    return cartella_cache() / ".lucchetto-calendari-aggiorna"


def scarico() -> Path:
    return Path(os.environ.get("SB_CALENDARI_SCARICO") or SCARICO_REPO)





def _adesso() -> datetime:
    ""
    return C._adesso().replace(tzinfo=FUSO)


def _mezzanotte(g: date) -> datetime:
    ""
    return datetime(g.year, g.month, g.day, tzinfo=FUSO).astimezone(UTC)


def _locale(g: date, minuto: int) -> datetime:
    ""
    h, m = divmod(minuto, 60)
    if h >= 24:
        return _mezzanotte(g + timedelta(days=1))
    return datetime(g.year, g.month, g.day, h, m, tzinfo=FUSO).astimezone(UTC)


def _minuto_muro(t: datetime) -> int:
    loc = t.astimezone(FUSO)
    return loc.hour * 60 + loc.minute


def _ora(t: datetime) -> str:
    loc = t.astimezone(FUSO)
    return f"{loc.hour}:{loc.minute:02d}"


def _breve(minuti: int) -> str:
    ""
    if minuti < 60:
        return TESTI["breve_minuti"].format(m=minuti)
    h, m = divmod(minuti, 60)
    if not m:
        return TESTI["breve_ore"].format(h=h)
    return TESTI["breve_ore_minuti"].format(h=h, mm=f"{m:02d}")


def _maiuscola(frase: str) -> str:
    return frase[:1].upper() + frase[1:]


def _leggi_json(percorso: Path):
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scrivi_json(percorso: Path, dati) -> None:
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=percorso.parent, suffix=".tmp", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(dati, tmp, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp.name, percorso)


def _log(riga: str) -> None:
    with contextlib.suppress(OSError):
        cartella_cache().mkdir(parents=True, exist_ok=True)
        with open(cartella_cache() / "calendari.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {riga}\n")


@contextlib.contextmanager
def _lucchetto(percorso: Path, blocca: bool):
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fh = open(percorso, "a+")  # noqa: SIM115 closed in the finally
    preso = False
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if blocca else fcntl.LOCK_NB))
            preso = True
        except BlockingIOError:
            preso = False
        yield preso
    finally:
        if preso:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _lucchetto_preso(percorso: Path) -> bool:
    if not percorso.exists():
        return False
    with open(percorso, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def _stacca(verbo: str) -> int | None:
    ""

    if os.environ.get("SB_CALENDARI_SINCRONO"):
        esegui([verbo])
        return None
    cartella_cache().mkdir(parents=True, exist_ok=True)
    py = VENV if VENV.exists() else Path(sys.executable)
    with open(cartella_cache() / "calendari.log", "a") as log:
        p = subprocess.Popen(
            [str(py), "-I", str(Path(__file__).resolve()), verbo],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(ROOT),
        )
    return p.pid





def _caselle_vive() -> dict[str, str]:
    ""
    d = _leggi_json(file_caselle())
    if not isinstance(d, dict):
        return {}
    return {k: ((v or {}).get("email") or "") for k, v in d.items() if isinstance(v, dict)}


def nome_casella(casella: str, vive: dict[str, str] | None = None) -> str:
    ""


    if casella in NOMI_CASELLE:
        return NOMI_CASELLE[casella]
    nome = _nome_principale(casella)
    if nome:
        return nome
    email = (vive if vive is not None else _caselle_vive()).get(casella)
    return email or TESTI["casella_senza_nome"]


_NOMI_PRINCIPALI: dict = {}


def _nome_principale(casella: str) -> str:
    ""
    f = cartella_calendari() / casella / "calendari.json"
    try:
        firma = (str(f), f.stat().st_mtime_ns)
    except OSError:
        return ""
    if firma not in _NOMI_PRINCIPALI:
        if len(_NOMI_PRINCIPALI) > 256:
            _NOMI_PRINCIPALI.clear()
        d = _leggi_json(f)
        voci = d.get("calendari") if isinstance(d, dict) else None
        nome = next(
            (str(c["nome"]).strip() for c in (voci if isinstance(voci, list) else [])
             if isinstance(c, dict) and c.get("primario") and isinstance(c.get("nome"), str) and c["nome"].strip()),
            "",
        )
        _NOMI_PRINCIPALI[firma] = nome
    return _NOMI_PRINCIPALI[firma]


def _propri(vive: dict[str, str]) -> set[str]:
    ""

    out = {e.lower() for e in vive.values() if e}
    extra = os.environ.get("SB_CALENDARI_PROPRI")
    if extra is not None:
        return out | {x.strip().lower() for x in extra.split(",") if x.strip()}
    try:
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        from sbk_config import OWN_EMAILS

        out |= {e.lower() for e in OWN_EMAILS}
    except Exception:  # noqa: BLE001 without the config the mailboxes remain
        pass
    return out


def _risposta(
    attendees: str | None, self_status: str | None, cal_id: str | None, email: str, propri: set[str]
) -> str:
    ""





    cal = (cal_id or "").lower()
    if self_status and cal in propri:
        return RISPOSTE.get(self_status, "accettato")
    testo = (attendees or "").strip()
    if not testo.startswith("["):
        return "accettato"
    try:
        lista = json.loads(testo)
    except ValueError:
        return "accettato"
    stati: dict[str, str] = {}
    for a in lista if isinstance(lista, list) else []:
        if isinstance(a, dict) and a.get("email"):
            stati.setdefault(str(a["email"]).lower(), str(a.get("status") or ""))

    for chi in (cal if cal in propri else "", email.lower()):
        if chi and chi in stati:
            return RISPOSTE.get(stati[chi], "accettato")
    for indirizzo, st in stati.items():
        if indirizzo in propri:
            return RISPOSTE.get(st, "accettato")
    return "accettato"





def firme() -> list[list]:
    ""


    percorsi = [file_caselle()]
    cal = cartella_calendari()
    with contextlib.suppress(OSError):
        for p in sorted(cal.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                percorsi += [p / "events.parquet", p / "calendari.json"]
    out = []
    for p in percorsi:
        try:
            st = p.stat()
        except OSError:
            continue
        out.append([str(p), st.st_mtime_ns, st.st_size])
    return out


def _istante(testo: str, fuso: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(testo)
    except ValueError:
        return None
    if d.tzinfo is None:
        try:
            d = d.replace(tzinfo=ZoneInfo(fuso) if fuso else FUSO)
        except (ValueError, KeyError):
            d = d.replace(tzinfo=FUSO)
    return d


def _stringa(x) -> str:
    ""

    if isinstance(x, str):
        return x
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, date):
        return x.isoformat()
    return ""


def _tipo_date_leggibile(tipo) -> bool:
    ""
    import pyarrow as pa

    if pa.types.is_dictionary(tipo):
        tipo = tipo.value_type
    return (
        pa.types.is_string(tipo)
        or pa.types.is_large_string(tipo)
        or pa.types.is_timestamp(tipo)
        or pa.types.is_date(tipo)
        or pa.types.is_null(tipo)
    )




COLONNE_SUBITO = ("id", "calendar_id", "start_datetime", "end_datetime")


def _evento_indice(
    cols: dict[str, list], tab, i: int, casella: str, vive: dict[str, str], propri: set[str]
) -> dict | None:
    nomi = set(tab.column_names) if tab is not None else set()

    def v(nome: str) -> str:
        col = cols.get(nome)
        if col is not None:
            return _stringa(col[i])
        if nome in nomi:
            return _stringa(tab.column(nome)[i].as_py())
        return ""

    if v("status") == "cancelled":
        return None
    inizio, fine = v("start_datetime"), v("end_datetime")
    if not inizio:
        return None
    ev: dict = {
        "id": v("id") or f"senza-id-{casella}-{i}",
        "titolo": v("summary"),
        "cal": v("calendar_id") or f"casella:{casella}",
        "casella": casella,
    }
    if len(inizio) == 10:
        try:
            d0 = date.fromisoformat(inizio)
        except ValueError:
            return None
        try:
            d1 = date.fromisoformat(fine[:10])
        except ValueError:
            d1 = d0
        if d1 <= d0:
            d1 = d0 + timedelta(days=1)
        ev["d0"], ev["d1"] = d0.isoformat(), d1.isoformat()
    else:
        s = _istante(inizio, v("start_timezone"))
        if s is None:
            return None
        e = _istante(fine, v("end_timezone") or v("start_timezone")) if fine else None
        if e is None or e < s:
            e = s
        ev["t0"], ev["t1"] = int(s.timestamp()), int(e.timestamp())
    ev["risposta"] = _risposta(
        v("attendees"), v("self_status"), v("calendar_id"), vive.get(casella, ""), propri
    )
    if v("status") == "tentative":
        ev["incerto"] = True
    if v("location"):
        ev["luogo"] = True
    if v("conference_url"):
        ev["video"] = v("conference_url")
    if v("event_type") and v("event_type") != "default":
        ev["tipo"] = v("event_type")
    if v("transparency") in ("transparent", "opaque"):
        ev["libero"] = v("transparency") == "transparent"
    if v("color_id") in COLORI_EVENTO:
        ev["colore"] = COLORI_EVENTO[v("color_id")]
    if v("html_link"):
        ev["link"] = v("html_link")
    if v("recurring_event_id"):
        ev["serie"] = v("recurring_event_id")
    return ev


def _inizio_ordinabile(ev: dict) -> float:
    if "t0" in ev:
        return ev["t0"]
    return _mezzanotte(date.fromisoformat(ev["d0"])).timestamp()


def _nella_finestra(ev: dict, dal: date, al_escluso: date) -> bool:
    if "d0" in ev:
        return ev["d1"] > dal.isoformat() and ev["d0"] < al_escluso.isoformat()
    w0, w1 = _mezzanotte(dal).timestamp(), _mezzanotte(al_escluso).timestamp()
    return ev["t0"] < w1 and max(ev["t1"], ev["t0"] + 1) > w0


def _testo_su(colore: str) -> str:
    return "#1d1d1d" if colore.lower() in CHIARI else "#ffffff"


def _calendari(
    cal_dir: Path, vive: dict[str, str], cartelle: list[str], eventi: list[dict]
) -> dict:
    ""

    ordine_caselle = list(vive) + [c for c in cartelle if c not in vive]
    out: dict[str, dict] = {}
    for casella in ordine_caselle:
        d = _leggi_json(cal_dir / casella / "calendari.json")
        voci = d.get("calendari") if isinstance(d, dict) else None
        for c in voci if isinstance(voci, list) else []:
            if not isinstance(c, dict) or not c.get("id") or not c.get("scaricato"):
                continue
            out[c["id"]] = {
                "nome": c.get("nome") or c["id"],
                "casella": casella,
                "colore": c.get("colore") or "",
                "testo": c.get("testo") or "",
                "primario": bool(c.get("primario")),
                "nascosto": bool(c.get("nascosto")),
                "scelto": bool(c.get("scelto", True)),
                "da_google": True,
            }
    altri: dict[str, int] = {}
    for ev in eventi:
        cid = ev["cal"]
        if cid in out:
            continue
        casella = ev["casella"]
        primario = cid.startswith("casella:") or cid.lower() == vive.get(casella, "").lower()
        if primario:
            nome = nome_casella(casella, vive)
        else:
            altri[casella] = altri.get(casella, 0) + 1
            n = altri[casella]
            chiave = "calendario_altro" if n == 1 else "calendario_altro_n"
            nome = TESTI[chiave].format(casella=nome_casella(casella, vive), n=n)
        out[cid] = {
            "nome": nome,
            "casella": casella,
            "colore": "",
            "testo": "",
            "primario": primario,
            "nascosto": False,
            "scelto": True,
            "da_google": False,
        }
    posto = {c: k for k, c in enumerate(ordine_caselle)}
    ordinati = sorted(
        out.items(),
        key=lambda kv: (posto.get(kv[1]["casella"], 999), not kv[1]["primario"], kv[1]["nome"]),
    )
    for k, (_, c) in enumerate(ordinati):
        c["ordine"] = k
        if not c["colore"]:
            c["colore"] = TAVOLOZZA[k % len(TAVOLOZZA)]
        if not c["testo"]:
            c["testo"] = _testo_su(c["colore"])
    return dict(ordinati)


def rifai_indice(dal: date | None = None, al: date | None = None, salva: bool = True) -> dict:
    ""




    oggi = _adesso().date()
    dal = dal or oggi - timedelta(days=GIORNI_PRIMA)
    al = al or oggi + timedelta(days=GIORNI_DOPO)
    al_escluso = al + timedelta(days=1)
    t_partenza = time.perf_counter()
    firme_prima = firme()
    cal_dir = cartella_calendari()
    vive = _caselle_vive()
    cartelle: list[tuple[str, Path]] = []
    with contextlib.suppress(OSError):
        for p in sorted(cal_dir.iterdir()):
            if p.is_dir() and not p.name.startswith(".") and (p / "events.parquet").is_file():
                cartelle.append((p.name, p / "events.parquet"))
    letti: list[tuple[str, dict[str, list], object, int]] = []
    rotti: list[str] = []
    righe = 0
    if cartelle:
        import pyarrow.parquet as pq

        for casella, percorso in cartelle:
            try:
                pf = pq.ParquetFile(percorso)
                nomi = set(pf.schema_arrow.names)

                for c in ("start_datetime", "end_datetime"):
                    if c in nomi and not _tipo_date_leggibile(pf.schema_arrow.field(c).type):
                        raise TypeError(f"{c} di tipo {pf.schema_arrow.field(c).type}")
                usa = [c for c in COLONNE_INDICE if c in nomi]
                tab = pf.read(columns=usa)
                cols = {c: tab.column(c).to_pylist() for c in usa if c in COLONNE_SUBITO}
                n = tab.num_rows
            except Exception as e:  # noqa: BLE001 a broken file doesn't stop the others
                _log(f"index: {casella} can't be read ({type(e).__name__})")
                rotti.append(casella)
                continue
            letti.append((casella, cols, tab, n))
            righe += n
    propri = _propri(vive) if letti else set()
    migliore: dict[str, tuple[tuple, int, int]] = {}
    senza_id: list[tuple[int, int]] = []
    for ordine, (casella, cols, _, n) in enumerate(letti):
        ferma = casella not in vive
        ids = cols.get("id")
        if ids is None:
            senza_id.extend((ordine, i) for i in range(n))
            continue
        calid = cols.get("calendar_id")
        for i, eid in enumerate(ids):
            if eid is None:
                senza_id.append((ordine, i))
                continue
            rango = (calid is None or calid[i] is None, ferma, ordine)
            ora = migliore.get(eid)
            if ora is None or rango < ora[0]:
                migliore[eid] = (rango, ordine, i)
    scelti = sorted([(o, i) for _, o, i in migliore.values()] + senza_id)

    da_testo = (dal - timedelta(days=1)).isoformat()
    a_testo = (al_escluso + timedelta(days=1)).isoformat()
    eventi = []
    for o, i in scelti:
        casella, cols, tab, _ = letti[o]
        inizio = _stringa((cols.get("start_datetime") or [None] * (i + 1))[i])[:10]
        fine = _stringa((cols.get("end_datetime") or [None] * (i + 1))[i])[:10] or inizio
        if inizio and (inizio > a_testo or fine < da_testo):
            continue
        ev = _evento_indice(cols, tab, i, casella, vive, propri)
        if ev is not None and _nella_finestra(ev, dal, al_escluso):
            eventi.append(ev)
    eventi.sort(key=lambda ev: (_inizio_ordinabile(ev), ev["id"]))
    nomi_cartelle = [c for c, _ in cartelle]
    caselle = {
        c: {"nome": nome_casella(c, vive), "viva": c in vive}
        for c in list(vive) + [c for c in nomi_cartelle if c not in vive]
    }
    d = {
        "versione": VERSIONE_INDICE,
        "fatto": _adesso().isoformat(timespec="seconds"),
        "dal": dal.isoformat(),
        "al": al.isoformat(),
        "firme": firme_prima,
        "manca": not cal_dir.is_dir(),
        "rotti": rotti,
        "righe_lette": righe,
        "eventi_distinti": len(migliore) + len(senza_id),
        "caselle": caselle,
        "calendari": _calendari(cal_dir, vive, nomi_cartelle, eventi),
        "eventi": eventi,
        "secondi": round(time.perf_counter() - t_partenza, 3),
    }
    if salva:
        _scrivi_json(file_indice(), d)
    return d



CAMPI_EVENTO_TESTO = ("titolo", "colore", "link", "video", "tipo", "serie")
CAMPI_EVENTO_SI_NO = ("incerto", "libero", "luogo")
CAMPI_CALENDARIO = (("nome", str), ("casella", str), ("colore", str), ("testo", str))
CAMPI_CALENDARIO_SI_NO = ("primario", "da_google", "nascosto", "scelto")


def _intero(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _giorno_iso(x) -> bool:
    if not isinstance(x, str) or not FORMA_GIORNO.fullmatch(x):
        return False
    try:
        return GIORNO_PRIMO <= date.fromisoformat(x) <= GIORNO_ULTIMO
    except ValueError:
        return False


def _evento_sano(ev) -> bool:
    ""


    if not isinstance(ev, dict):
        return False
    if not all(isinstance(ev.get(k), str) and ev[k] for k in ("id", "cal", "casella")):
        return False
    if "d0" in ev or "d1" in ev:
        if not (_giorno_iso(ev.get("d0")) and _giorno_iso(ev.get("d1")) and ev["d0"] < ev["d1"]):
            return False
    elif not all(
        _intero(ev.get(k)) and ISTANTE_MINIMO <= ev[k] <= ISTANTE_MASSIMO for k in ("t0", "t1")
    ):
        return False
    if "risposta" in ev and ev["risposta"] not in RISPOSTE.values():
        return False
    if any(k in ev and not isinstance(ev[k], str) for k in CAMPI_EVENTO_TESTO):
        return False
    return not any(k in ev and not isinstance(ev[k], bool) for k in CAMPI_EVENTO_SI_NO)


def _calendario_sano(c) -> bool:
    return (
        isinstance(c, dict)
        and all(isinstance(c.get(k), tipo) for k, tipo in CAMPI_CALENDARIO)
        and all(isinstance(c.get(k, False), bool) for k in CAMPI_CALENDARIO_SI_NO)
    )


def _leggi_indice() -> dict | None:
    d = _leggi_json(file_indice())
    if (
        isinstance(d, dict)
        and d.get("versione") == VERSIONE_INDICE
        and isinstance(d.get("eventi"), list)
        and isinstance(d.get("calendari"), dict)
    ):
        eventi = [ev for ev in d["eventi"] if _evento_sano(ev)]
        calendari = {k: c for k, c in d["calendari"].items() if _calendario_sano(c)}
        if len(eventi) != len(d["eventi"]) or len(calendari) != len(d["calendari"]):
            _log(
                f"index: skipped {len(d['eventi']) - len(eventi)} events and "
                f"{len(d['calendari']) - len(calendari)} malformed calendars"
            )
        rotti = d.get("rotti")
        d["eventi"], d["calendari"] = eventi, calendari
        d["rotti"] = [x for x in rotti if isinstance(x, str)] if isinstance(rotti, list) else []
        return d
    return None


def _fresco(d: dict) -> bool:
    try:
        fatto = datetime.fromisoformat(d["fatto"]).date()
    except (KeyError, TypeError, ValueError):
        return False
    return d.get("firme") == firme() and (_adesso().date() - fatto).days < INDICE_VECCHIO_GIORNI


def _rifai_sotto_lucchetto(forza: bool = False) -> dict:
    ""
    with _lucchetto(lucchetto_indice(), blocca=True):
        if not forza:
            d = _leggi_indice()
            if d is not None and _fresco(d):
                return d
        return rifai_indice()


def indice() -> tuple[dict, str]:
    ""

    d = _leggi_indice()
    if d is None:
        return _rifai_sotto_lucchetto(), "rifatto"
    if _fresco(d):
        return d, "fresco"
    if not _lucchetto_preso(lucchetto_indice()):
        _stacca("sottofondo-indice")
    return d, "rifacendo"


def eventi_fra(dal: date, al_escluso: date) -> tuple[list[dict], dict, str, list[str]]:
    ""

    d, come = indice()
    try:
        dentro = date.fromisoformat(d["dal"]) <= dal and al_escluso <= date.fromisoformat(
            d["al"]
        ) + timedelta(days=1)
    except (KeyError, TypeError, ValueError):
        dentro = False
    if not dentro:
        d = rifai_indice(dal, al_escluso - timedelta(days=1), salva=False)
        come = "dai_file"
    eventi = [ev for ev in d["eventi"] if _nella_finestra(ev, dal, al_escluso)]
    return eventi, d["calendari"], come, list(d.get("rotti") or [])





def _giorno_settimana(x) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if 0 <= x <= 6 else None
    if isinstance(x, str):
        return NOMI_GIORNI.get(x.strip().lower())
    return None


def _minuti_ora(x) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int | float):
        n = int(x)
        return n * 60 if 0 <= n <= 24 else n if 0 <= n <= 1440 else None
    if isinstance(x, str) and x.strip():


        m = FORMA_ORA.fullmatch(x.strip())
        if m is None or int(m.group(2) or 0) > 59:
            return None
        n = int(m.group(1)) * 60 + int(m.group(2) or 0)
        return n if 0 <= n <= 1440 else None
    return None


def impostazioni_settimana(impostazioni: dict | None) -> dict:
    ""
    imp = impostazioni if isinstance(impostazioni, dict) else {}
    s = imp.get("settimana") if isinstance(imp.get("settimana"), dict) else imp
    out = dict(SETTIMANA_PARTENZA)
    inizio = _giorno_settimana(s.get("inizio"))
    if inizio is not None:
        out["inizio"] = inizio
    giorni = s.get("giorni")
    if isinstance(giorni, list):
        letti = sorted({g for g in (_giorno_settimana(x) for x in giorni) if g is not None})
        if letti:
            out["giorni"] = letti
    dalle, alle = _minuti_ora(s.get("dalle")), _minuti_ora(s.get("alle"))
    if dalle is not None and alle is not None and dalle < alle:
        out["dalle"], out["alle"] = dalle, alle
    elif dalle is not None and dalle < out["alle"] and alle is None:
        out["dalle"] = dalle
    elif alle is not None and alle > out["dalle"] and dalle is None:
        out["alle"] = alle
    g = s.get("giornata_minuti")
    if isinstance(g, int) and not isinstance(g, bool) and 0 < g <= 1440:
        out["giornata_minuti"] = g
    return out


def _soglia_vecchi(impostazioni: dict | None) -> int:
    imp = impostazioni if isinstance(impostazioni, dict) else {}
    cal = imp.get("calendari") if isinstance(imp.get("calendari"), dict) else {}
    n = cal.get("vecchi_dopo_minuti")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else VECCHI_DOPO_MIN





def _quando_ts(testo) -> datetime | None:
    ""
    if not isinstance(testo, str) or not testo:
        return None
    try:
        d = datetime.fromisoformat(testo)
    except ValueError:
        return None
    return (d if d.tzinfo else d.astimezone()).astimezone(FUSO)


def _quando_aggiornato(t: datetime, adesso: datetime) -> str:
    if adesso - t < timedelta(minutes=1):
        return TESTI["quando_adesso"]
    ora = _ora(t)
    giorni = (adesso.date() - t.date()).days
    if giorni <= 0:
        return TESTI["quando_alle"].format(ora=ora)
    if giorni == 1:
        return TESTI["quando_ieri"].format(ora=ora)
    return TESTI["quando_il"].format(il=C._il(t, adesso), ora=ora)


def _aggiorna_in_corso() -> bool:
    if _lucchetto_preso(lucchetto_aggiorna()):
        return True
    st = _leggi_json(file_stato_aggiorna()) or {}
    chiesto = _quando_ts(st.get("chiesto"))
    finito = _quando_ts(st.get("finito"))
    if chiesto is None or (finito is not None and finito >= chiesto):
        return False
    return (datetime.now(FUSO) - chiesto).total_seconds() < GIA_CHIESTO_S


def _scarico_altrui_vivo() -> bool:
    ""

    try:
        pid = int((cartella_calendari().parent / "ca-l0-download.pid").read_text().strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _ci_sono_calendari(cal_dir: Path) -> bool:
    ""
    with contextlib.suppress(OSError):
        for p in cal_dir.iterdir():
            if p.is_dir() and not p.name.startswith(".") and (p / "events.parquet").is_file():
                return True
    return False


def stato_aggiornamento(adesso: datetime | None = None, impostazioni: dict | None = None) -> dict:
    ""




    adesso = adesso or _adesso()
    vive = _caselle_vive()
    cal_dir = cartella_calendari()
    marche = _leggi_json(file_marche())
    marche = marche if isinstance(marche, dict) else {}
    giro = _leggi_json(cal_dir / "stato-giro.json")
    giro = giro if isinstance(giro, dict) else {}
    esiti_giro = giro.get("caselle") if isinstance(giro.get("caselle"), dict) else {}
    ultime = {c: _quando_ts(marche.get(f"calendar-{c}")) for c in vive}
    piu_fresca = max((t for t in ultime.values() if t), default=None)
    caselle, errori, buone = [], [], []
    for c in vive:
        t = ultime[c]
        g = esiti_giro.get(c) if isinstance(esiti_giro.get(c), dict) else None
        tg = _quando_ts(g.get("finito")) if g else None
        if g and tg and (t is None or tg >= t - timedelta(minutes=1)):
            esito = str(g.get("esito") or "errore")
        elif t is None:
            esito = "mai"
        elif piu_fresca and piu_fresca - t > timedelta(minutes=INDIETRO_MIN):
            esito = "indietro"
        else:
            esito = "ok"
        nome = nome_casella(c, vive)
        voce = {
            "casella": c,
            "nome": nome,
            "ultima": t.isoformat(timespec="seconds") if t else None,
            "esito": esito,
            "frase": TESTI["aggiornata_casella"].format(quando=_quando_aggiornato(t, adesso))
            if t
            else TESTI["motivo_mai"],
            "motivo": "",
        }
        if esito in ("ok", "senza_calendari"):
            if t and esito == "ok":
                buone.append(t)
        else:
            voce["motivo"] = TESTI.get(f"motivo_{esito}", TESTI["motivo_errore"])
            errori.append(
                {
                    "casella": c,
                    "nome": nome,
                    "frase": TESTI["casella_ferma"].format(nome=nome),
                    "motivo": voce["motivo"],
                }
            )
        caselle.append(voce)
    in_corso = _aggiorna_in_corso()
    ultima = min(buone) if buone else None
    soglia = _soglia_vecchi(impostazioni)
    ci_sono = _ci_sono_calendari(cal_dir)
    if not ci_sono and not in_corso:


        errori = []
    if in_corso:
        frase = TESTI["aggiornati_in_corso"]
    elif not ci_sono:


        frase = TESTI["calendari_mancano"]
    elif ultima is None:
        frase = TESTI["aggiornati_mai"]
    else:
        frase = TESTI["aggiornati"].format(quando=_quando_aggiornato(ultima, adesso))
    return {
        "frase": frase,
        "vecchi": ultima is None or (adesso - ultima) > timedelta(minutes=soglia),
        "in_corso": in_corso,
        "scarico_altrui": _scarico_altrui_vivo(),
        "indice_in_corso": _lucchetto_preso(lucchetto_indice()),
        "ultima": ultima.isoformat(timespec="seconds") if ultima else None,
        "soglia_minuti": soglia,
        "errori": errori,
        "caselle": caselle,
    }





def colonne(
    intervalli: list[tuple[int, int]], minima: int = DURATA_MINIMA, giorno: int = 1440
) -> list[dict]:
    ""






    disegno = []
    for da, a in intervalli:
        da = max(0, min(int(da), giorno - 1))
        fine = min(max(int(a), da + minima), giorno)
        disegno.append((da, fine))
    ordine = sorted(
        range(len(disegno)), key=lambda i: (disegno[i][0], -(disegno[i][1] - disegno[i][0]), i)
    )
    out: list[dict | None] = [None] * len(disegno)

    def chiudi(grappolo: list[tuple[int, int]]) -> None:
        n_col = max(c for _, c in grappolo) + 1
        per_colonna: dict[int, list[int]] = {}
        for i, c in grappolo:
            per_colonna.setdefault(c, []).append(i)
        for i, c in grappolo:
            da, a = disegno[i]
            ampiezza = 1
            for k in range(c + 1, n_col):
                if any(disegno[j][0] < a and disegno[j][1] > da for j in per_colonna.get(k, [])):
                    break
                ampiezza += 1
            out[i] = {"colonna": c, "colonne": n_col, "ampiezza": ampiezza, "da": da, "a": a}

    grappolo: list[tuple[int, int]] = []
    fini: list[int] = []
    fine_grappolo = -1
    for i in ordine:
        da, a = disegno[i]
        if grappolo and da >= fine_grappolo:
            chiudi(grappolo)
            grappolo, fini = [], []
        for c, f in enumerate(fini):
            if f <= da:
                fini[c] = a
                break
        else:
            c = len(fini)
            fini.append(a)
        fine_grappolo = a if not grappolo else max(fine_grappolo, a)
        grappolo.append((i, c))
    if grappolo:
        chiudi(grappolo)
    return out  # type: ignore[return-value]





def _segmento(
    s: datetime, e: datetime, ds: datetime, de: datetime
) -> tuple[int, int, bool, bool] | None:
    ""


    if e < s:
        e = s
    if s == e:
        if not (ds <= s < de):
            return None
    elif s >= de or e <= ds:
        return None
    a0, a1 = max(s, ds), min(e, de)
    da = 0 if a0 == ds else _minuto_muro(a0)
    a = 1440 if a1 == de else _minuto_muro(a1)
    if a1 > a0 and a <= da:
        a = da + max(1, round((a1 - a0).total_seconds() / 60))
    return da, min(a, 1440), s < ds, e > de


def _giorno_da(testo, oggi: date) -> date:
    ""

    if testo in (None, "", "oggi"):
        return oggi
    if isinstance(testo, datetime):
        g = testo.date()
    elif isinstance(testo, date):
        g = testo
    else:
        if not FORMA_GIORNO.fullmatch(str(testo)):
            raise Errore("errore_giorno")
        try:
            g = date.fromisoformat(str(testo))
        except ValueError as e:
            raise Errore("errore_giorno") from e
    if not GIORNO_PRIMO <= g <= GIORNO_ULTIMO:
        raise Errore("errore_giorno")
    return g


def _pianificata(valore) -> tuple[date, int | None] | None:
    ""
    if not isinstance(valore, str) or not valore:
        return None
    if len(valore) == 10:
        try:
            return date.fromisoformat(valore), None
        except ValueError:
            return None
    try:
        d = datetime.fromisoformat(valore)
        d = d.astimezone(FUSO) if d.tzinfo else d
    except (ValueError, OverflowError):
        return None
    if not GIORNO_PRIMO <= d.date() <= GIORNO_ULTIMO:
        return (
            None
        )
    return d.date(), d.hour * 60 + d.minute


def _durata_task(t: dict) -> tuple[int, bool]:
    ""
    stima = t.get("stima")
    detta = _intero(stima) and stima > 0
    return (stima if detta else TASK_SENZA_STIMA), detta


def _intervallo_task(t: dict) -> tuple[datetime, datetime, bool] | None:
    ""




    valore = t.get("pianificata")
    p = _pianificata(valore)
    if not p or p[1] is None:
        return None
    durata, detta = _durata_task(t)
    try:
        d = datetime.fromisoformat(valore)
        if d.tzinfo:
            inizio_muro = d.astimezone(FUSO).replace(second=0, microsecond=0)
        else:
            g, minuto = p
            h, m = divmod(minuto, 60)
            inizio_muro = datetime(g.year, g.month, g.day, h, m, tzinfo=FUSO)
        fine_muro = (inizio_muro.replace(tzinfo=None) + timedelta(minutes=durata)).replace(
            tzinfo=FUSO, fold=inizio_muro.fold
        )
        return inizio_muro.astimezone(UTC), fine_muro.astimezone(UTC), detta
    except (ValueError, OverflowError):
        return None


def _chiusa(t: dict) -> bool:
    if "chiusa" in t:
        return bool(t["chiusa"])
    return t.get("stato") == "fatta"


def _orario(s: datetime, e: datetime) -> str:
    ls, le = s.astimezone(FUSO), e.astimezone(FUSO)
    fine_stesso_giorno = le.date() == ls.date() or (
        le.date() == ls.date() + timedelta(days=1) and le.hour == 0 and le.minute == 0
    )
    if fine_stesso_giorno:
        return TESTI["orario"].format(da=_ora(s), a=_ora(e))
    return TESTI["orario_giorni"].format(
        giorno_da=TESTI["quando_giorno"].format(giorno=C.GIORNI[ls.weekday()], n=ls.day),
        da=_ora(s),
        giorno_a=TESTI["quando_giorno"].format(giorno=C.GIORNI[le.weekday()], n=le.day),
        a=_ora(e),
    )


def _titolo(primo: date, ultimo: date, scala: str) -> str:
    if scala == "giorno":
        return TESTI["titolo_giorno"].format(
            giorno=C.GIORNI[primo.weekday()],
            n=primo.day,
            mese=C.MESI[primo.month - 1],
            anno=primo.year,
        )
    if primo.year != ultimo.year:
        return TESTI["titolo_settimana_due_anni"].format(
            da=primo.day,
            mese_da=C.MESI[primo.month - 1],
            anno_da=primo.year,
            a=ultimo.day,
            mese_a=C.MESI[ultimo.month - 1],
            anno_a=ultimo.year,
        )
    if primo.month != ultimo.month:
        return TESTI["titolo_settimana_due_mesi"].format(
            da=primo.day,
            mese_da=C.MESI[primo.month - 1],
            a=ultimo.day,
            mese_a=C.MESI[ultimo.month - 1],
            anno=primo.year,
        )
    return TESTI["titolo_settimana_mese"].format(
        da=primo.day, a=ultimo.day, mese=C.MESI[primo.month - 1], anno=primo.year
    )


def _fuso_nome() -> str:
    chiave = getattr(FUSO, "key", "") or ""
    citta = CITTA.get(chiave) or chiave.split("/")[-1].replace("_", " ") or chiave
    return TESTI["fuso_nome"].format(citta=citta)


def _nascosti(vista: dict, calendari: dict) -> set[str]:
    if isinstance(vista.get("calendari_nascosti"), list):
        return {str(x) for x in vista["calendari_nascosti"]}
    return {cid for cid, c in calendari.items() if c.get("nascosto") or not c.get("scelto", True)}


def _in_fascia(ev: dict) -> bool:
    ""


    if "d0" in ev or ev.get("tipo") == "workingLocation" or ev["t1"] - ev["t0"] >= 86400:
        return True
    s, e = datetime.fromtimestamp(ev["t0"], FUSO), datetime.fromtimestamp(ev["t1"], FUSO)
    a_mezzanotte = all((x.hour, x.minute, x.second) == (0, 0, 0) for x in (s, e))
    return a_mezzanotte and e.date() > s.date()


def _giorni_evento(ev: dict) -> tuple[date, date]:
    ""
    if "d0" in ev:
        return date.fromisoformat(ev["d0"]), date.fromisoformat(ev["d1"]) - timedelta(days=1)
    s = datetime.fromtimestamp(ev["t0"], FUSO)
    e = datetime.fromtimestamp(max(ev["t0"], ev["t1"] - 1), FUSO)
    return s.date(), e.date()


def _aiuto_evento(ev: dict, nome_cal: str, s: datetime | None, e: datetime | None) -> str:
    parti = []
    if s is not None and e is not None:
        parti.append(
            _maiuscola(TESTI["aiuto_evento"].format(orario=_orario(s, e), calendario=nome_cal))
        )
    else:
        parti.append(TESTI["aiuto_evento_tutto_il_giorno"].format(calendario=nome_cal))
    risposta = ev.get("risposta")
    if risposta and risposta != "accettato":
        parti.append(TESTI[f"risposta_{risposta}"])
    if ev.get("incerto"):
        parti.append(TESTI["evento_incerto"])
    if ev.get("libero"):
        parti.append(TESTI["evento_libero"])
    return " ".join(parti)


def _extra_evento(ev: dict, out: dict) -> dict:
    for chiave in ("colore", "link", "video", "tipo", "incerto", "libero", "luogo", "serie"):
        if chiave in ev:
            out["tipo_evento" if chiave == "tipo" else chiave] = ev[chiave]
    return out


def settimana(
    giorno=None,
    task: list[dict] | None = None,
    impostazioni: dict | None = None,
    scala: str = "settimana",
    vista: dict | None = None,
) -> dict:
    ""

    adesso = _adesso()
    oggi = adesso.date()
    imp = impostazioni_settimana(impostazioni)
    vista = vista if isinstance(vista, dict) else {}
    g = _giorno_da(giorno, oggi)
    if scala == "giorno":
        primo, n = g, 1
    else:
        scala = "settimana"
        primo, n = g - timedelta(days=(g.weekday() - imp["inizio"]) % 7), 7
    giorni_d = [primo + timedelta(days=i) for i in range(n)]
    dopo_fine = primo + timedelta(days=n)
    mezzanotti = [_mezzanotte(d) for d in [*giorni_d, dopo_fine]]
    eventi, calendari, come, rotti = eventi_fra(primo, dopo_fine)
    nascosti = _nascosti(vista, calendari)
    mostra_rifiutati = bool(vista.get("rifiutati"))
    nome_cal = {cid: c["nome"] for cid, c in calendari.items()}

    conta: dict[str, int] = {}
    rifiutati_nascosti = 0
    fascia: list[tuple[dict, int, int, bool, bool, bool]] = []
    segmenti: list[list[tuple]] = [[] for _ in range(n)]
    for ev in eventi:
        conta[ev["cal"]] = conta.get(ev["cal"], 0) + 1
        if ev["cal"] in nascosti:
            continue
        if ev.get("risposta") == "rifiutato" and not mostra_rifiutati:
            rifiutati_nascosti += 1
            continue
        if _in_fascia(ev):
            a, b = _giorni_evento(ev)
            i0, i1 = (a - primo).days, (b - primo).days
            if i1 < 0 or i0 > n - 1:
                continue
            fascia.append((ev, max(i0, 0), min(i1, n - 1), i0 < 0, i1 > n - 1, b > a))
            continue
        s = datetime.fromtimestamp(ev["t0"], UTC)
        e = datetime.fromtimestamp(ev["t1"], UTC)
        for i in range(n):
            seg = _segmento(s, e, mezzanotti[i], mezzanotti[i + 1])
            if seg:
                segmenti[i].append(("evento", ev, seg, s, e))

    giorni = []
    for i, d in enumerate(giorni_d):
        giorni.append(
            {
                "giorno": d.isoformat(),
                "nome": GIORNI_BREVI[d.weekday()],
                "numero": d.day,
                "oggi": d == oggi,
                "passato": d < oggi,
                "festivo": d.weekday() not in imp["giorni"],
                "quando": TESTI["quando_giorno"].format(giorno=C.GIORNI[d.weekday()], n=d.day),
                "scadenze": [],
                "pianificate": [],
                "tutto_il_giorno": [],
                "righe": 0,
                "blocchi": [],
                "minuti_task": 0,
                "minuti_giornata": imp["giornata_minuti"] if d.weekday() in imp["giorni"] else 0,
            }
        )


    scadenze: dict[int, list[tuple]] = {}
    da_ripianificare: list[tuple] = []
    for t in task or []:
        if not isinstance(t, dict) or t.get("eliminata") or not t.get("id"):
            continue
        tid = str(t["id"])
        chiusa = _chiusa(t)
        sc = t.get("scadenza")
        if isinstance(sc, str) and len(sc) >= 10:
            try:
                i = (date.fromisoformat(sc[:10]) - primo).days
            except ValueError:
                i = -1
            if 0 <= i < n:
                prio = t.get("priorita") if isinstance(t.get("priorita"), int) else 9
                scadenze.setdefault(i, []).append((chiusa, prio, tid))
        p = _pianificata(t.get("pianificata"))
        if not p:
            continue
        intervallo = _intervallo_task(t)
        if not chiusa:
            passata = p[0] < oggi if intervallo is None else intervallo[1] <= adesso
            if passata:
                da_ripianificare.append((t.get("pianificata"), tid))
        if intervallo is None:
            i = (p[0] - primo).days
            if 0 <= i < n:
                giorni[i]["pianificate"].append(tid)
            continue
        s, e, detta = intervallo
        oltre = False
        if isinstance(sc, str) and len(sc) >= 10:
            with contextlib.suppress(ValueError):
                oltre = p[0] > date.fromisoformat(sc[:10])



        minuti, _ = _durata_task(t)
        vero = (e - s).total_seconds()
        for i in range(n):
            seg = _segmento(s, e, mezzanotti[i], mezzanotti[i + 1])
            if seg:
                parte = (min(e, mezzanotti[i + 1]) - max(s, mezzanotti[i])).total_seconds()
                quota = minuti * parte / vero if vero > 0 else 0
                segmenti[i].append(("task", t, seg, s, e, detta, oltre, chiusa, quota))
    for i, voci in scadenze.items():
        giorni[i]["scadenze"] = [tid for _, _, tid in sorted(voci)]


    fascia.sort(key=lambda f: (f[1], -(f[2] - f[1]), not f[5], f[0].get("titolo", ""), f[0]["id"]))
    occupate: list[set[int]] = []
    barre = []
    for ev, i0, i1, cp, cd, piu_giorni in fascia:
        giorni_occupati = set(range(i0, i1 + 1))
        riga = next(
            (r for r, occ in enumerate(occupate) if not occ & giorni_occupati), len(occupate)
        )
        if riga == len(occupate):
            occupate.append(set())
        occupate[riga] |= giorni_occupati
        cal_nome = nome_cal.get(ev["cal"], "")
        s = e = None
        if "t0" in ev:
            s, e = datetime.fromtimestamp(ev["t0"], UTC), datetime.fromtimestamp(ev["t1"], UTC)
        voce = {
            "id": ev["id"],
            "titolo": ev.get("titolo") or TESTI["senza_titolo"],
            "cal": ev["cal"],
            "riga": riga,
            "risposta": ev.get("risposta", "accettato"),
            "aiuto": _aiuto_evento(ev, cal_nome, s, e),
        }
        if s is not None:
            voce["ora"] = _ora(s)
        _extra_evento(ev, voce)
        if piu_giorni or cp or cd:
            barre.append({**voce, "dal": i0, "al": i1, "continua_prima": cp, "continua_dopo": cd})
        else:
            giorni[i0]["tutto_il_giorno"].append(voce)
        for k in giorni_occupati:
            giorni[k]["righe"] = max(giorni[k]["righe"], riga + 1)


    for i, voci in enumerate(segmenti):
        if not voci:
            continue
        posti = colonne([(v[2][0], v[2][1]) for v in voci])
        occupato = [
            (v[2][0], v[2][1])
            for v in voci
            if v[0] == "evento" and not v[1].get("libero") and v[1].get("risposta") != "rifiutato"
        ]
        blocchi = []
        for v, posto in zip(voci, posti, strict=True):
            da, a_vero, cp, cd = v[2]
            s, e = v[3], v[4]
            base = {
                "da": posto["da"],
                "a": posto["a"],
                "fine_vera": a_vero,
                "colonna": posto["colonna"],
                "colonne": posto["colonne"],
                "ampiezza": posto["ampiezza"],
                "continua_prima": cp,
                "continua_dopo": cd,
                "ora": _ora(s),
                "ora_fine": _ora(e),
            }
            if v[0] == "evento":
                ev = v[1]
                aiuto = _aiuto_evento(ev, nome_cal.get(ev["cal"], ""), s, e)
                if cp:
                    aiuto += " " + TESTI["continua_prima"]
                if cd:
                    aiuto += " " + TESTI["continua_dopo"]
                blocco = {
                    "tipo": "evento",
                    "id": ev["id"],
                    "titolo": ev.get("titolo") or TESTI["senza_titolo"],
                    "cal": ev["cal"],
                    **base,
                    "risposta": ev.get("risposta", "accettato"),
                    "aiuto": aiuto,
                }
                blocchi.append(_extra_evento(ev, blocco))
                continue
            t, detta, oltre, chiusa = v[1], v[5], v[6], v[7]
            sovrapposta = any(o0 < a_vero and o1 > da for o0, o1 in occupato)
            aiuto = [_maiuscola(TESTI["aiuto_task"].format(orario=_orario(s, e)))]
            if not detta:
                aiuto.append(
                    TESTI["aiuto_task_senza_durata"].format(durata=_breve(TASK_SENZA_STIMA))
                )
            if oltre:
                aiuto.append(TESTI["aiuto_task_oltre_scadenza"])
            if sovrapposta:
                aiuto.append(TESTI["aiuto_task_sovrapposta"])
            if cp:
                aiuto.append(TESTI["continua_prima"])
            if cd:
                aiuto.append(TESTI["continua_dopo"])
            if not chiusa:
                giorni[i]["minuti_task"] += max(0, round(v[8]))
            blocchi.append(
                {
                    "tipo": "task",
                    "id": str(t["id"]),
                    **base,
                    "durata_detta": detta,
                    "sovrapposta": sovrapposta,
                    "oltre_scadenza": oltre,
                    "aiuto": " ".join(aiuto),
                }
            )
        blocchi.sort(key=lambda b: (b["da"], b["colonna"], b["tipo"], b["id"]))
        giorni[i]["blocchi"] = blocchi

    for gi in giorni:
        gi["tutto_il_giorno"].sort(key=lambda x: x["riga"])
    barre.sort(key=lambda b: (b["riga"], b["dal"]))
    aggiornati = stato_aggiornamento(adesso, impostazioni)
    if come == "rifacendo":
        aggiornati["indice_in_corso"] = True
    for casella in rotti:
        nome = nome_casella(casella)
        aggiornati["errori"].append(
            {
                "casella": casella,
                "nome": nome,
                "frase": TESTI["casella_ferma"].format(nome=nome),
                "motivo": TESTI["motivo_rotto"],
            }
        )
    in_settimana = primo <= oggi < dopo_fine
    return {
        "id": primo.isoformat(),
        "scala": scala,
        "titolo": _titolo(primo, giorni_d[-1], scala),
        "prima": (primo - timedelta(days=n)).isoformat(),
        "dopo": dopo_fine.isoformat(),
        "oggi": oggi.isoformat(),
        "fuso": getattr(FUSO, "key", str(FUSO)),
        "fuso_nome": _fuso_nome(),
        "apri_al_minuto": max(0, (adesso.hour - 1) * 60)
        if in_settimana
        else max(0, imp["dalle"] - 60),
        "ore_lavoro": {"dalle": imp["dalle"], "alle": imp["alle"], "giorni": imp["giorni"]},
        "giorni": giorni,
        "barre": barre,
        "righe_tutto_il_giorno": len(occupate),
        "calendari": [
            {
                "id": cid,
                "nome": c["nome"],
                "casella": nome_casella(c["casella"]),
                "colore": c["colore"],
                "testo": c["testo"],
                "primario": c["primario"],
                "visibile": cid not in nascosti,
                "n": conta.get(cid, 0),
                "da_google": c["da_google"],
            }
            for cid, c in calendari.items()
        ],
        "rifiutati_nascosti": rifiutati_nascosti,
        "mostra_rifiutati": mostra_rifiutati,
        "aggiornati": aggiornati,
        "da_ripianificare": [tid for _, tid in sorted(da_ripianificare)],
        "indice": come,
    }





def _arrotonda_su(t: datetime) -> datetime:
    ""


    u = t.astimezone(UTC)
    resto = (u.minute % SCATTO) * 60 + u.second + u.microsecond / 1e6
    if resto:
        u += timedelta(seconds=SCATTO * 60 - resto)
    return u.replace(second=0, microsecond=0)


def _frase_giorno(d: date, oggi: date) -> str:
    g = (d - oggi).days
    if g == 0:
        return TESTI["buco_oggi"]
    if g == 1:
        return TESTI["buco_domani"]
    if 2 <= g <= 6:
        return TESTI["buco_giorno"].format(giorno=C.GIORNI[d.weekday()], n=d.day)
    return C._il(d, oggi)


def buchi(
    tid: str,
    task: list[dict],
    impostazioni: dict | None = None,
    vista: dict | None = None,
    da: str | None = None,
    durata: int | None = None,
    quanti: int = 3,
) -> dict:
    ""




    t = next((x for x in task or [] if isinstance(x, dict) and str(x.get("id")) == tid), None)
    if t is None or t.get("eliminata"):
        raise Errore("errore_task")
    if durata is not None:


        if not 1 <= durata <= 1440:
            raise Errore("errore_durata")
    else:
        durata, _ = _durata_task(t)
    imp = impostazioni_settimana(impostazioni)
    vista = vista if isinstance(vista, dict) else {}
    adesso = _adesso()
    oggi = adesso.date()
    partenza = adesso.astimezone(UTC)
    if da:
        g = _giorno_da(da, oggi)
        partenza = max(partenza, _mezzanotte(g))
    partenza = _arrotonda_su(partenza)
    primo_giorno = partenza.astimezone(FUSO).date()
    inizio_sett = primo_giorno - timedelta(days=(primo_giorno.weekday() - imp["inizio"]) % 7)
    fine2 = inizio_sett + timedelta(days=14)
    eventi, calendari, _, _ = eventi_fra(primo_giorno, fine2)
    nascosti = _nascosti(vista, calendari)
    occupati: list[tuple[datetime, datetime]] = []
    for ev in eventi:
        if ev["cal"] in nascosti or ev.get("risposta") == "rifiutato" or ev.get("libero") is True:
            continue
        if ev.get("tipo") == "workingLocation":
            continue
        if "d0" in ev:
            if ev.get("libero") is False:
                occupati.append(
                    (
                        _mezzanotte(date.fromisoformat(ev["d0"])),
                        _mezzanotte(date.fromisoformat(ev["d1"])),
                    )
                )
            continue
        occupati.append(
            (datetime.fromtimestamp(ev["t0"], UTC), datetime.fromtimestamp(ev["t1"], UTC))
        )
    for altra in task or []:
        if not isinstance(altra, dict) or str(altra.get("id")) == tid:
            continue
        if altra.get("eliminata") or _chiusa(altra):
            continue
        intervallo = _intervallo_task(altra)
        if intervallo:
            occupati.append((intervallo[0], intervallo[1]))
    occupati.sort()

    entra = durata <= 14 * 1440
    passo = timedelta(minutes=durata if entra else 0)
    trovati: list[datetime] = []
    d = primo_giorno
    while entra and d < fine2 and len(trovati) < quanti:
        if d.weekday() in imp["giorni"]:
            w0, w1 = _locale(d, imp["dalle"]), _locale(d, imp["alle"])
            cursore = max(w0, partenza)
            for b0, b1 in [*[o for o in occupati if o[1] > cursore and o[0] < w1], (w1, w1)]:
                if b0 > cursore:
                    inizio = _arrotonda_su(cursore)
                    if inizio + passo <= min(b0, w1):
                        trovati.append(inizio)
                        if len(trovati) >= quanti:
                            break
                cursore = max(cursore, b1)
                if cursore >= w1:
                    break
        d += timedelta(days=1)
    proposte = []
    for s in trovati:
        e = s + passo
        loc = s.astimezone(FUSO)
        proposte.append(
            {
                "inizio": loc.isoformat(timespec="seconds"),
                "fine": e.astimezone(FUSO).isoformat(timespec="seconds"),
                "pianifica": loc.strftime("%Y-%m-%dT%H:%M"),
                "giorno": loc.date().isoformat(),
                "ora": _ora(s),
                "frase": TESTI["buco"].format(quando=_frase_giorno(loc.date(), oggi), ora=_ora(s)),
            }
        )
    breve = _breve(durata)
    if not proposte:
        messaggio = TESTI["buchi_nessuno"].format(durata=breve)
    elif len(proposte) == 1:
        messaggio = TESTI["buchi_uno"].format(durata=breve)
    else:
        messaggio = TESTI["buchi_tanti"].format(n=len(proposte), durata=breve)
    return {"ok": True, "buchi": proposte, "durata": durata, "messaggio": messaggio}





def leggi_pianificata(testo: str, adesso: datetime | None = None) -> str | None:
    ""




    adesso = adesso or _adesso()
    grezzo = str(testo or "").strip()
    t = " ".join(grezzo.lower().split())
    if t == "togli":
        return None
    if not t:
        raise Errore("errore_pianificata")
    if t[:4].isdigit() and len(t) >= 10:
        if len(t) == 10:
            try:
                return date.fromisoformat(t).isoformat()
            except ValueError as e:
                raise Errore("errore_pianificata") from e
        try:
            d = datetime.fromisoformat(grezzo.upper().replace(" ", "T", 1))
        except ValueError as e:
            raise Errore("errore_pianificata") from e
        d = d.astimezone(FUSO) if d.tzinfo else d.replace(tzinfo=FUSO)
        return d.replace(second=0, microsecond=0).isoformat(timespec="seconds")
    parole = t.split(" ")
    oggi = adesso.astimezone(FUSO).date()
    primo = parole[0]
    if primo == "oggi":
        g = oggi
    elif primo == "domani":
        g = oggi + timedelta(days=1)
    elif primo == "dopodomani":
        g = oggi + timedelta(days=2)
    elif primo in NOMI_GIORNI and len(primo) > 3:
        g = oggi + timedelta(days=(NOMI_GIORNI[primo] - oggi.weekday()) % 7 or 7)
    else:
        raise Errore("errore_pianificata")
    resto = [p for p in parole[1:] if p not in ("alle", "all'", "a")]
    if not resto:
        return g.isoformat()
    if len(resto) != 1:
        raise Errore("errore_pianificata")
    minuto = _minuti_ora(resto[0].replace("'", ""))
    if minuto is None or minuto >= 1440:
        raise Errore("errore_pianificata")
    h, m = divmod(minuto, 60)
    return datetime(g.year, g.month, g.day, h, m, tzinfo=FUSO).isoformat(timespec="seconds")


def in_fila(inizio: str, durate: list[int | None]) -> list[str]:
    ""

    d = datetime.fromisoformat(inizio)
    d = d.astimezone(FUSO) if d.tzinfo else d.replace(tzinfo=FUSO)
    out = []
    for durata in durate:
        out.append(d.isoformat(timespec="seconds"))
        passo = (
            durata
            if isinstance(durata, int) and not isinstance(durata, bool) and durata > 0
            else TASK_SENZA_STIMA
        )
        d = (d.replace(tzinfo=None) + timedelta(minutes=passo)).replace(tzinfo=FUSO)
    return out





def _con_memoria(fai):
    ""

    if os.environ.get("SB_FINTO_LEASE"):
        return fai()
    try:
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        import sbk_resources as sr
    except Exception:  # noqa: BLE001 without the module it runs, as before it existed
        return fai()
    soglia = min(float(os.environ.get("SB_SOGLIA_AMMISSIONE") or 65) / 100, sr.SEG_YIELD - 0.02)
    if sr.pressure().seg_ratio >= soglia:
        return None
    lz = sr.Lease("sb-attivita-calendario", need_frac=QUOTA_MEMORIA)
    lz.registra(QUOTA_MEMORIA)
    try:
        return fai()
    finally:
        lz.release()


def _lancia_scarico() -> tuple[str, int | None]:
    script = scarico()
    if not script.is_file():
        return "manca", None
    py = VENV if VENV.exists() else Path(sys.executable)

    def fai():
        with open(cartella_cache() / "calendari-scarico.log", "a") as log:
            try:
                r = subprocess.run(
                    [str(py), str(script), "--senza-login"],
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                    cwd=str(ROOT),
                    timeout=TETTO_SCARICO_S,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return "tempo", None
        return {0: "ok", 75: "occupato"}.get(r.returncode, "errore"), r.returncode

    esito = _con_memoria(fai)
    return esito if esito is not None else ("memoria", None)


def _stato_aggiorna(**campi) -> None:
    st = _leggi_json(file_stato_aggiorna())
    st = st if isinstance(st, dict) else {}
    st.update(campi)
    _scrivi_json(file_stato_aggiorna(), st)


def _ora_mac() -> str:
    return datetime.now(FUSO).isoformat(timespec="seconds")


def sottofondo_aggiorna() -> dict:
    ""
    with _lucchetto(lucchetto_aggiorna(), blocca=False) as preso:
        if not preso:
            return {"ok": True, "gia": True}
        _stato_aggiorna(in_corso=True, partito=_ora_mac(), esito=None, uscita=None)
        esito, uscita = _lancia_scarico()
        _log(f"refresh: download {esito} ({uscita})")
        eventi = None
        try:
            eventi = len(_rifai_sotto_lucchetto(forza=True)["eventi"])
        except Exception as e:  # noqa: BLE001 the old index stays, it's noted in the log
            _log(f"refresh: index not rebuilt ({type(e).__name__}: {e})")
        _stato_aggiorna(
            in_corso=False, finito=_ora_mac(), esito=esito, uscita=uscita, eventi=eventi
        )
        return {"ok": True, "esito": esito, "uscita": uscita, "eventi": eventi}


def aggiorna() -> dict:
    ""

    if _aggiorna_in_corso():
        return {"ok": True, "in_corso": True, "gia": True, "messaggio": TESTI["aggiorna_gia"]}
    _stato_aggiorna(chiesto=_ora_mac())
    if os.environ.get("SB_CALENDARI_SINCRONO"):
        r = sottofondo_aggiorna()
        esito = r.get("esito")
        chiave = {
            "ok": "aggiorna_fatto",
            "occupato": "aggiorna_occupato",
            "tempo": "aggiorna_tempo",
            "memoria": "aggiorna_memoria",
            "manca": "aggiorna_manca",
        }.get(esito, "aggiorna_errore")
        return {
            "ok": True,
            "in_corso": False,
            "gia": False,
            "esito": esito,
            "messaggio": TESTI[chiave],
        }
    _stacca("sottofondo-aggiorna")
    return {"ok": True, "in_corso": True, "gia": False, "messaggio": TESTI["aggiorna_partito"]}


def calendario_stato(impostazioni: dict | None = None) -> dict:
    st = stato_aggiornamento(impostazioni=impostazioni)
    ultimo = _leggi_json(file_stato_aggiorna())
    if isinstance(ultimo, dict) and ultimo.get("finito"):
        chiave = {
            "ok": "aggiorna_fatto",
            "occupato": "aggiorna_occupato",
            "tempo": "aggiorna_tempo",
            "memoria": "aggiorna_memoria",
            "manca": "aggiorna_manca",
        }.get(ultimo.get("esito"), "aggiorna_errore")
        st["ultimo_tasto"] = {
            "esito": ultimo.get("esito"),
            "finito": ultimo.get("finito"),
            "frase": TESTI[chiave],
        }
    return {"ok": True, **st}





def _opzione(resto: list[str], nome: str) -> tuple[list[str], str | None]:
    if nome in resto:
        i = resto.index(nome)
        valore = resto[i + 1] if i + 1 < len(resto) else None
        return resto[:i] + resto[i + 2 :], valore
    return resto, None


def esegui(
    argomenti: list[str],
    task: list[dict] | None = None,
    impostazioni: dict | None = None,
    vista: dict | None = None,
) -> dict:
    ""
    try:
        args = [str(a) for a in (argomenti or [])]
        if not args:
            raise Errore("errore_comando")
        verbo, resto = args[0], args[1:]
        if verbo in ("settimana", "--settimana", "--giorno"):

            scala = "giorno" if verbo == "--giorno" or "--giorno" in resto else "settimana"
            posizionali = [x for x in resto if not x.startswith("--")]
            return {
                "ok": True,
                "settimana": settimana(
                    posizionali[0] if posizionali else None, task or [], impostazioni, scala, vista
                ),
            }
        if verbo == "buchi" and resto:
            resto, da = _opzione(resto, "--da")
            resto, durata_t = _opzione(resto, "--durata")
            durata = None
            if durata_t is not None:
                try:
                    durata = int(durata_t)
                except ValueError as e:
                    raise Errore("errore_durata") from e
            return buchi(resto[0], task or [], impostazioni, vista, da=da, durata=durata)
        if verbo == "calendario-aggiorna":
            return aggiorna()
        if verbo == "calendario-stato":
            return calendario_stato(impostazioni)
        if verbo == "indice":
            d = _rifai_sotto_lucchetto(forza=True)
            return {
                "ok": True,
                "eventi": len(d["eventi"]),
                "calendari": len(d["calendari"]),
                "righe_lette": d["righe_lette"],
                "rotti": d["rotti"],
                "dal": d["dal"],
                "al": d["al"],
                "secondi": d["secondi"],
            }
        if verbo == "sottofondo-indice":
            with _lucchetto(lucchetto_indice(), blocca=False) as preso:
                if not preso:
                    return {"ok": True, "gia": True}
                d = _leggi_indice()
                if d is None or not _fresco(d):
                    d = rifai_indice()
                return {"ok": True, "eventi": len(d["eventi"])}
        if verbo == "sottofondo-aggiorna":
            return sottofondo_aggiorna()
        raise Errore("errore_comando")
    except Errore as e:
        return {"ok": False, "errore": TESTI[e.chiave]}
    except Exception as e:  # noqa: BLE001 the door never raises: the detail goes in the log
        _log(f"error {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return {"ok": False, "errore": TESTI["errore_interno"]}


if __name__ == "__main__":
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        sys.exit(0)
    print(json.dumps(esegui(sys.argv[1:]), ensure_ascii=False))
