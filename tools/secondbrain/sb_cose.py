#!/usr/bin/env python3
"""Words for dates, priorities and estimates of the tasks page, and the reader of a ClickUp list for the one-time import
into the tasks engine (sb_attivita.py).
"""





















from __future__ import annotations

import calendar
import fcntl
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TOOLS = Path(__file__).resolve().parents[1]


def _config(chiave: str) -> str:
    """A text value of sbk.config.json ("clickup.tasks_list"), "" when it is not set."""
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    try:
        from sbk_config import user_cfg
    except ImportError:
        return ""
    v = user_cfg(chiave, "")
    return str(v).strip() if isinstance(v, str | int) and not isinstance(v, bool) else ""


# The ClickUp list your tasks are read from (one-time import into the tasks engine):
# "clickup": {"tasks_list": "<list id>"} in sbk.config.json. No default: unset = no import.
LISTA = os.environ.get("SB_COSE_LISTA") or _config("clickup.tasks_list")
API = "https://api.clickup.com/api/v2"

CARTELLA = Path(
    os.environ.get("SB_COSE_DIR") or Path.home() / "Library/Application Support/SBK/cose"
)
VALIDITA = timedelta(minutes=2)


SETTIMANA = 7
PRIMA = 6


FUSO = ZoneInfo(os.environ.get("SB_COSE_FUSO", "UTC"))

VELOCE = 30

TANTE = 12
PESO = {"urgent": 0, "high": 1, "normal": 2, "low": 3, None: 4}
NUMERO_PRIORITA = {"urgent": 1, "high": 2, "normal": 3, "low": 4}

STATO_APERTO = "to do"
STATO_CHIUSO = "complete"

MESI = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
GIORNI = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")




# Task area mapping, generic defaults: edit these tables to match your own task codes.
# They map the prefix of a task code such as "[W-12] Call the bank" (AREE_FORMA for a
# full prefix, AREE for the leading letters) or an "Area: ..." line in the description
# (AREE_DESCRIZIONE) to an area name. Unmatched tasks fall back to TESTI["area_altro"].
# AREA_ATTESE is the area of the decisions only you can give: the "Waiting on you" view
# lists its tasks. Every lookup goes through AREA_ATTESE, so AREE_FORMA may be empty.
AREA_ATTESE = "Waiting on you"
AREE_FORMA: dict[str, str] = {"W-": AREA_ATTESE}
AREE = {
    "A1": "Area 1",
    "A2": "Area 2",
}
AREE_DESCRIZIONE = {
    "Area 1": "Area 1",
    "Area 2": "Area 2",
}


TESTI: dict[str, str] = {
    "titolo": "Tasks",
    "sottotitolo": "The tasks you have to do, from your list on ClickUp. What you change here changes there too.",

    "gruppo_davanti": "Up front",
    "aiuto_gruppo_davanti": (
        "The urgent ones, all of them, and those dated this week, that is from seven days ago to six days from now. First "
        "the ones with a near date, then the urgent ones with no date, then the urgent ones whose date passed long ago."
    ),
    "gruppo_veloci": "Quick",
    "aiuto_gruppo_veloci": (
        "They take half an hour or less, according to the estimate written on ClickUp. These are the ones not up front and not low priority."
    ),
    "gruppo_altre": "The others",
    "aiuto_gruppo_altre": (
        "They take more than half an hour, or have no estimate on ClickUp. These are the ones not up front and not low priority."
    ),
    "gruppo_senza_fretta": "No rush",
    "aiuto_gruppo_senza_fretta": "The low-priority tasks on ClickUp. The group stays closed until you open it.",
    "gruppo_fatte": "Done now",

    "vista_urgenti": "Urgent",
    "aiuto_vista_urgenti": "The urgent-priority tasks and those dated this week.",
    "vuoto_vista_urgenti": "No urgent task and no date this week.",
    "vista_veloci": "Quick",
    "aiuto_vista_veloci": "The tasks of half an hour or less, according to the estimate written on ClickUp. First by due date, then by priority.",
    "vuoto_vista_veloci": "No task of half an hour or less.",
    "vista_attese": "Waiting on you",
    "aiuto_vista_attese": "The decisions and go-aheads that only you can give.",
    "vuoto_vista_attese": "No decision is waiting on you.",
    "vista_tutte": "All",
    "aiuto_vista_tutte": "All the open tasks in the list, by priority.",
    "vuoto_vista_tutte": "There is no open task in your list on ClickUp.",
    "colonna_task": "Task",
    "colonna_priorita": "Priority",
    "colonna_scadenza": "Due date",
    "colonna_stima": "Estimate",
    "colonna_area": "Area",
    "colonna_cambio": "Last change",
    "colonna_creata": "Created on",
    "priorita_1": "Urgent",
    "priorita_2": "High",
    "priorita_3": "Normal",
    "priorita_4": "Low",
    "priorita_0": "None",
    "aiuto_priorita": "The priority on ClickUp. You change it from here, and you see the same on your phone.",
    "aiuto_stima": "How long it takes, according to the estimate written on ClickUp. You change it from here.",
    "stima_togli": "Remove the estimate",
    "senza_stima": "no estimate",
    "esito_priorita": "On ClickUp it now has {nome} priority.",
    "esito_priorita_0": "On ClickUp it now has no priority.",
    "esito_stima": "Estimate changed on ClickUp. It is now {quanto}.",
    "esito_stima_tolta": "Estimate removed on ClickUp.",
    "errore_stima": "I could not change the estimate. On ClickUp it stayed as before.",
    "rivedi_ferme_uno": "Review the urgent one stuck since {mese}",
    "rivedi_ferme_tanti": "Review the {n} urgent ones stuck since {mese}",
    "aiuto_rivedi_ferme": "Selects the urgent ones whose date passed more than a week ago, to close, reschedule or re-prioritize them together.",
    "data_oggi": "Today",
    "fatte_oggi": "Done today",
    "scelte_uno": "One selected",
    "scelte_tanti": "{n} selected",
    "togli_scelta": "Clear the selection",
    "colonne_rimetti": "Reset the columns",
    "aiuto_gruppo_fatte": "The ones you closed from here since you opened the app. With Reopen they become open again on ClickUp.",
    "aiuto_apri_gruppo": "Shows this group's tasks.",
    "aiuto_chiudi_gruppo": "Hides this group's tasks.",
    "mostra_tutte": "Show all {n}",
    "vuoto_davanti": "Nothing up front. No urgent task and no date this week.",
    "ultimo_cambio": "Last change on ClickUp {giorno}.",
    "vuoto_veloci": "No task of half an hour or less.",
    "vuoto_altre": "No other open task.",
    "vuoto_senza_fretta": "No low-priority task.",

    "verdetto_lista_vuota": "There is no open task in your list on ClickUp.",
    "verdetto_niente": "Nothing up front.",
    "verdetto_uno": "One task up front.",
    "verdetto_tanti": "{n} tasks up front.",
    "verdetto_scadute_uno": "One is overdue.",
    "verdetto_scadute_tanti": "{n} are overdue.",
    "verdetto_oggi_uno": "One is due today.",
    "verdetto_oggi_tanti": "{n} are due today.",
    "davanti_tante": "There are many, want to remove some?",
    "nota_ferme_uno": (
        "One non-urgent task has a date that passed more than a week ago. It sits in its group with the date greyed out. "
        "To bring it up front, reschedule it or keep it up front."
    ),
    "nota_ferme_tanti": (
        "{n} non-urgent tasks have a date that passed more than a week ago. They sit in their group with the date "
        "greyed out. To bring one up front, reschedule it or keep it up front."
    ),

    "letto_oggi": "List read at {ora}.",
    "letto_ieri": "List read yesterday at {ora}.",
    "letto_il": "List read {giorno} at {ora}.",
    "rileggi": "Refresh",
    "aiuto_rileggi": "Re-reads your list on ClickUp now.",

    "tutte_le_aree": "All areas",
    "aiuto_aree": "Shows only the tasks of one area.",
    "cerca": "Search the tasks",
    "nessuna_trovata": "No open task matches.",
    "togli_filtri": "Clear the filters",
    "area_altro": "Other",

    "fatta": "Done",
    "aiuto_fatta": (
        "It closes it on ClickUp and removes it from the list. It does not delete it. You can undo right after. On ClickUp I leave a "
        "comment saying you closed it from here."
    ),
    "sposta_data": "Reschedule",
    "aiuto_data": "From here you pick a new due date. It changes on ClickUp too.",
    "senza_data": "no date",
    "data_domani": "Tomorrow, {giorno}",
    "data_lunedi": "Monday {numero}",
    "data_settimana": "In a week, {giorno}",
    "data_mese": "In a month, {data}",
    "data_scegli": "Pick a day…",
    "data_togli": "Remove the date",
    "foglio_sposta": "Move",
    "tieni_davanti": "Keep it up front",
    "aiuto_tieni_davanti": "On ClickUp I mark it urgent, and on your phone you see it among the urgent ones. It stays up front until you close it or remove it.",
    "togli_davanti": "Remove from up front",
    "aiuto_togli_davanti": "On ClickUp the priority goes from urgent to high. It moves to its group, with the others.",
    "non_urgente": "No longer urgent",
    "aiuto_non_urgente": (
        "On ClickUp the priority goes from urgent to high. It stays up front while the date is this week. To remove it "
        "right away, reschedule it."
    ),
    "aiuto_quanto": "The estimate written on ClickUp.",
    "aiuto_apri_dettaglio": "Shows the task description.",
    "aiuto_chiudi_dettaglio": "Hides the description.",
    "senza_dettaglio": "On ClickUp this task has no description.",
    "apri_clickup": "Open on ClickUp",
    "aiuto_apri_clickup": "Opens the task on ClickUp in the browser, with the full description and comments.",
    "copia_link": "Copy the link",
    "annulla": "Undo",
    "aiuto_annulla": "Puts the task back on ClickUp as it was before.",
    "riapri": "Reopen",
    "aiuto_riapri": "Reopens it on ClickUp and puts it back in the list.",
    "riprova": "Retry",

    "scadeva": "was due {giorno}",
    "aiuto_scadeva": "It was meant to be done by {giorno}. The date has not been moved since.",
    "scaduta_da": "overdue by {n} days",
    "scaduta_ieri": "overdue since yesterday",
    "aiuto_scaduta": "It was meant to be done by {giorno}.",
    "scade_oggi": "today",
    "scade_domani": "tomorrow",
    "aiuto_scade": "Due {quando}.",
    "minuti_tanti": "{n} minutes",
    "minuti_uno": "one minute",
    "ore_uno": "one hour",
    "ore_tanti": "{n} hours",
    "e_mezza": " and a half",
    "e_minuti": " and {n} minutes",
    "giornata": "more than a day",

    "esito_fatta": "Closed on ClickUp.",
    "esito_riaperta": "Reopened on ClickUp.",
    "esito_data_davanti": "Date changed on ClickUp. It is now due {quando} and is up front.",
    "esito_data_dopo": "Date changed on ClickUp. It is now due {quando}, comes back up front {torna}.",
    "esito_data_tolta_davanti": "Date removed on ClickUp. It stays up front because it is urgent.",
    "esito_data_tolta": "Date removed on ClickUp.",
    "esito_data": "Date changed on ClickUp.",
    "esito_davanti": "It is now up front. On ClickUp I marked it urgent.",
    "esito_non_davanti": "Removed from up front. On ClickUp it now has high priority.",
    "esito_non_urgente": "On ClickUp it now has high priority. It stays up front because of the date.",
    "esito_annullato": "Undone. On ClickUp it is back as it was.",

    "commento_fatta": "Closed from the SBK app, on {giorno} at {ora}.",
    "commento_riaperta": "Reopened from the SBK app, on {giorno} at {ora}.",

    "errore_clickup": "ClickUp is not responding.",
    "errore_rete": "The Mac is not connected to the internet.",
    "errore_lista": (
        "No ClickUp list is set for your tasks. Put its id in sbk.config.json, "
        '"clickup": {"tasks_list": "<list id>"}, then try again.'
    ),
    "errore_troppe": "ClickUp refused due to too many requests in a row.",
    "errore_rifiutato": "ClickUp refused the change.",
    "errore_strano": "ClickUp replied in a way I do not understand.",
    "errore_chiave": (
        "The Mac Keychain is missing the key to read ClickUp, so the list cannot be read. Ask me in chat to "
        "put it back."
    ),
    "errore_chiave_rifiutata": "ClickUp no longer accepts the key saved on the Mac. Ask me in chat to redo it.",
    "errore_sparita": "This task is no longer in your list on ClickUp. I removed it from here.",
    "errore_copia": "You see the list as it was at the last read. Try again with Refresh.",
    "errore_fatta": "I could not close it. On ClickUp it is still open.",
    "errore_riapri": "I could not reopen it. On ClickUp it is still closed.",
    "errore_data": "I could not change the date. On ClickUp it stayed as before.",
    "errore_priorita": "I could not change the priority. On ClickUp it stayed as before.",
    "errore_giorno": "I did not understand that day.",
    "errore_comando": "The engine does not know this gesture.",
    "errore_motore": "The engine did not respond as it should.",
}


class Errore(Exception):
    ""

    def __init__(self, chiave: str, dettaglio: str = ""):
        super().__init__(chiave)
        self.chiave = chiave
        self.dettaglio = dettaglio





def _chiave() -> str:
    sys.path.insert(0, str(_TOOLS))
    try:
        import secrets_adapter

        tok = secrets_adapter.get_secret("sbk-clickup", "api-token")
    except Exception as e:  # noqa: BLE001 the Keychain can fail in many ways, you need a single sentence
        raise Errore("errore_chiave", type(e).__name__) from e
    if not tok:
        raise Errore("errore_chiave")
    return tok


def _api(metodo: str, percorso: str, corpo: dict | None = None) -> dict:
    ""
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta = urllib.request.Request(
        API + percorso,
        data=dati,
        method=metodo,
        headers={"Authorization": _chiave(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=15) as r:  # noqa: S310 fixed ClickUp address
            testo = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Errore("errore_chiave_rifiutata", str(e.code)) from e
        if e.code == 429:
            raise Errore("errore_troppe", str(e.code)) from e
        if e.code == 404:
            raise Errore("errore_sparita", str(e.code)) from e
        if 400 <= e.code < 500:
            raise Errore("errore_rifiutato", str(e.code)) from e
        raise Errore("errore_clickup", str(e.code)) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Errore("errore_rete", type(e).__name__) from e
    try:
        return json.loads(testo) if testo.strip() else {}
    except ValueError as e:
        if metodo == "GET":
            raise Errore("errore_strano") from e

        return {}


def _leggi_clickup() -> list[dict]:
    if not LISTA:
        raise Errore("errore_lista")
    task: list[dict] = []
    pagina = 0
    while pagina < 20:
        d = _api("GET", f"/list/{LISTA}/task?page={pagina}&include_closed=false&subtasks=true")
        task += d.get("tasks", [])
        if d.get("last_page", True) or not d.get("tasks"):
            break
        pagina += 1
    return [_asciutta(t) for t in task]


def _asciutta(t: dict) -> dict:
    ""
    return {
        "id": t.get("id"),
        "name": t.get("name") or "",
        "description": (t.get("text_content") or t.get("description") or "")[:4000],
        "priority": (t.get("priority") or {}).get("priority"),
        "due_date": int(t["due_date"]) if t.get("due_date") else None,
        "time_estimate": int(t["time_estimate"]) if t.get("time_estimate") else None,
        "date_created": int(t.get("date_created") or 0),
        "date_updated": int(t.get("date_updated") or 0),
        "url": t.get("url"),
    }





def _file() -> Path:
    return CARTELLA / "ultima-lettura.json"


class _Lucchetto:
    ""

    def __enter__(self):
        CARTELLA.mkdir(parents=True, exist_ok=True)
        self.fh = open(CARTELLA / ".lucchetto", "a+")  # noqa: SIM115 closed in __exit__
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _scrivi_file(percorso: Path, dati: dict) -> None:
    ""
    CARTELLA.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=CARTELLA, suffix=".tmp", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(dati, tmp, ensure_ascii=False)
    Path(tmp.name).replace(percorso)


def _copia() -> dict | None:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d.get("task"), list) and d.get("letto") else None
    except (OSError, ValueError):
        return None


def _salva(task: list[dict], letto: datetime, giro: int = 0) -> None:
    ""

    _scrivi_file(_file(), {"letto": letto.isoformat(), "giro": giro, "task": task})


def _adesso() -> datetime:
    ""
    fissa = os.environ.get("SB_COSE_ADESSO")
    if not fissa:
        return datetime.now(FUSO).replace(tzinfo=None)
    d = datetime.fromisoformat(fissa)
    return d.astimezone(FUSO).replace(tzinfo=None) if d.tzinfo else d


def _da_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, FUSO).replace(tzinfo=None)


def _in_ms(d: datetime) -> int:
    return int(d.replace(tzinfo=FUSO).timestamp() * 1000)





def _scadenza(t: dict) -> datetime | None:
    return _da_ms(t["due_date"]) if t.get("due_date") else None


def _giorni(t: dict, oggi: datetime) -> int | None:
    ""
    d = _scadenza(t)
    return None if d is None else (oggi.date() - d.date()).days


def _ferma(t: dict, oggi: datetime) -> bool:
    g = _giorni(t, oggi)
    return g is not None and g > SETTIMANA


def _minuti(t: dict) -> int | None:
    return round(t["time_estimate"] / 60000) if t.get("time_estimate") else None


def _in_settimana(t: dict, oggi: datetime) -> bool:
    g = _giorni(t, oggi)
    return g is not None and -PRIMA <= g <= SETTIMANA


def _davanti(t: dict, oggi: datetime) -> bool:
    ""


    return t.get("priority") == "urgent" or _in_settimana(t, oggi)


def _gruppo(t: dict, oggi: datetime) -> str:
    if _davanti(t, oggi):
        return "davanti"
    if t.get("priority") == "low":
        return "senza_fretta"
    m = _minuti(t)
    return "veloci" if m is not None and m <= VELOCE else "altre"


def _ordine_davanti(t: dict, oggi: datetime):
    ""

    g = _giorni(t, oggi)
    if _in_settimana(t, oggi):
        return (0, -(g or 0), 0)
    return (2 if _ferma(t, oggi) else 1, _minuti(t) or 9999, t["date_created"])


def _ordine_resto(t: dict, oggi: datetime):
    ""

    g = _giorni(t, oggi)
    viva = g is not None and not _ferma(t, oggi)
    fresca = (oggi - _da_ms(t["date_created"])).days < SETTIMANA if t.get("date_created") else False
    return (
        not fresca,
        PESO.get(t.get("priority"), 4),
        not viva,
        -(g or 0) if viva else 0,
        -t["date_created"],
    )





def _n(chiave: str, n: int) -> str:
    return TESTI[f"{chiave}_{'uno' if n == 1 else 'tanti'}"].format(n=n)


def _data_lunga(d: datetime, oggi: datetime) -> str:
    ""
    s = f"{MESI[d.month - 1]} {d.day}"
    return s if d.year == oggi.year else f"{s} {d.year}"


def _il(d: datetime, oggi: datetime) -> str:
    ""
    return _data_lunga(d, oggi)


def _quando_parole(d: datetime, oggi: datetime) -> str:
    ""
    g = (d.date() - oggi.date()).days
    if g == 0:
        return TESTI["scade_oggi"]
    if g == 1:
        return TESTI["scade_domani"]
    if 2 <= g <= 6:
        return f"{GIORNI[d.weekday()]} {d.day}"
    return _il(d, oggi)


def _frase_scadenza(t: dict, oggi: datetime) -> tuple[str, str, str]:
    ""
    g = _giorni(t, oggi)
    d = _scadenza(t)
    if g is None or d is None:
        return "", "vuota", ""
    il = _il(d, oggi)
    if g > SETTIMANA:
        return (
            TESTI["scadeva"].format(giorno=il),
            "spenta",
            TESTI["aiuto_scadeva"].format(giorno=il),
        )
    if g > 1:
        return TESTI["scaduta_da"].format(n=g), "allarme", TESTI["aiuto_scaduta"].format(giorno=il)
    if g == 1:
        return TESTI["scaduta_ieri"], "allarme", TESTI["aiuto_scaduta"].format(giorno=il)
    aiuto = TESTI["aiuto_scade"].format(quando=_quando_parole(d, oggi))
    if g == 0:
        return TESTI["scade_oggi"], "allarme", aiuto
    if g == -1:
        return TESTI["scade_domani"], "piana", aiuto
    if g >= -6:
        return GIORNI[d.weekday()], "piana", aiuto
    return il, "piana", aiuto


def _frase_minuti(m: int | None) -> str:
    ""
    if not m:
        return ""
    if m < 60:
        return TESTI["minuti_uno"] if m == 1 else TESTI["minuti_tanti"].format(n=m)
    if m > 8 * 60:
        return TESTI["giornata"]
    ore, resto = divmod(m, 60)
    base = TESTI["ore_uno"] if ore == 1 else TESTI["ore_tanti"].format(n=ore)
    if resto == 0:
        return base
    return base + (TESTI["e_mezza"] if resto == 30 else TESTI["e_minuti"].format(n=resto))


# Example task-text conventions (configurable): an optional "[CODE] title" prefix,
# an "Area: … · Fonte: …" line in the description, and colored bullet markers.
_CODICE = re.compile(r"^\s*\[([^\]]+)\]\s*")
_AREA = re.compile(r"Area:\s*([^·\n]+)")


def _titolo(nome: str) -> str:
    ""
    pulito = _CODICE.sub("", nome).replace("**", "").replace("`", "").strip()
    return pulito[:1].upper() + pulito[1:] if pulito else nome


def _area(t: dict) -> str:
    m = _CODICE.match(t.get("name") or "")
    if m:
        codice = m.group(1)
        for inizio, nome in AREE_FORMA.items():
            if codice.startswith(inizio):
                return nome
        sigla = re.match(r"[A-Za-z]+", codice)
        if sigla and sigla.group(0).upper() in AREE:
            return AREE[sigla.group(0).upper()]
    a = _AREA.search(t.get("description") or "")
    if a:
        return AREE_DESCRIZIONE.get(a.group(1).strip(), TESTI["area_altro"])
    return TESTI["area_altro"]


_PALLINI = re.compile("[\U0001f7e0-\U0001f7eb\U0001f534\U0001f535\u26aa\u26ab]\\s*")


def _dettaglio(t: dict) -> str:
    ""

    testo = re.sub(r"^\s*Area:[^·\n]*(?:·\s*)?", "", (t.get("description") or "").strip())
    righe = [r for r in testo.splitlines() if not r.lstrip().startswith("Fonte:")]
    return re.sub(r"\n{3,}", "\n\n", _PALLINI.sub("", "\n".join(righe))).strip()[:2500]





def _segno(t: dict, oggi: datetime) -> str:
    ""
    if t.get("priority") != "urgent":
        return "tieni"

    return "non_urgente" if _in_settimana(t, oggi) else "togli"


def _voce(t: dict, oggi: datetime, gruppo: str) -> dict:
    frase, tono, aiuto = _frase_scadenza(t, oggi)
    if gruppo != "davanti" and tono == "allarme":
        tono = "piana"
    return {
        "id": t["id"],
        "titolo": _titolo(t["name"]),
        "area": _area(t),
        "urgente": t.get("priority") == "urgent",
        "davanti": gruppo == "davanti",
        "segno": _segno(t, oggi),
        "scadenza": frase,
        "tono": tono,
        "aiuto_scadenza": aiuto,
        "con_data": bool(t.get("due_date")),
        "quanto": _frase_minuti(_minuti(t)),
        "dettaglio": _dettaglio(t),

        "fermo": TESTI["ultimo_cambio"].format(giorno=_il(_da_ms(t["date_updated"]), oggi))
        if t.get("date_updated")
        else "",
        "link": t.get("url"),

        "priorita": NUMERO_PRIORITA.get(t.get("priority"), 0),
        "priorita_nome": TESTI[f"priorita_{NUMERO_PRIORITA.get(t.get('priority'), 0)}"],
        "ultimo_cambio": _data_lunga(_da_ms(t["date_updated"]), oggi)
        if t.get("date_updated")
        else "",
        "creata": _data_lunga(_da_ms(t["date_created"]), oggi) if t.get("date_created") else "",

        "o_priorita": NUMERO_PRIORITA.get(t.get("priority"), 9),
        "o_scadenza": t.get("due_date") or 9_999_999_999_999,
        "o_stima": _minuti(t) or 999_999,
        "o_cambio": t.get("date_updated") or 0,
        "o_creata": t.get("date_created") or 0,
    }


def _scelte_data(oggi: datetime) -> list[dict]:
    ""
    domani = oggi + timedelta(days=1)
    settimana = oggi + timedelta(days=7)
    lunedi = oggi + timedelta(days=(7 - oggi.weekday()) or 7)
    mese = _da_ms(_quando("mese", oggi))
    scelte = [
        {"id": "oggi", "nome": TESTI["data_oggi"]},
        {
            "id": "domani",
            "nome": TESTI["data_domani"].format(giorno=f"{GIORNI[domani.weekday()]} {domani.day}"),
        },
    ]
    if lunedi.date() not in (domani.date(), settimana.date()):
        scelte.append({"id": "lunedi", "nome": TESTI["data_lunedi"].format(numero=lunedi.day)})
    scelte.append(
        {
            "id": "settimana",
            "nome": TESTI["data_settimana"].format(
                giorno=f"{GIORNI[settimana.weekday()]} {settimana.day}"
            ),
        }
    )
    scelte.append({"id": "mese", "nome": TESTI["data_mese"].format(data=_data_lunga(mese, oggi))})
    return scelte


def _pagina(task: list[dict], letto: datetime, avviso: str = "") -> dict:
    oggi = _adesso()
    per_gruppo: dict[str, list[dict]] = {
        "davanti": [],
        "veloci": [],
        "altre": [],
        "senza_fretta": [],
    }
    for t in task:
        per_gruppo[_gruppo(t, oggi)].append(t)
    gruppi = []
    for gid, righe in per_gruppo.items():
        chiave = _ordine_davanti if gid == "davanti" else _ordine_resto
        righe.sort(key=lambda t, k=chiave: k(t, oggi))
        gruppi.append(
            {
                "id": gid,
                "titolo": TESTI[f"gruppo_{gid}"],
                "aiuto": TESTI[f"aiuto_gruppo_{gid}"],
                "vuoto": TESTI[f"vuoto_{gid}"],
                "chiuso": gid == "senza_fretta",
                "voci": [_voce(t, oggi, gid) for t in righe],
            }
        )
    davanti = per_gruppo["davanti"]

    scadute = sum(1 for t in davanti if (_giorni(t, oggi) or 0) > 0 and not _ferma(t, oggi))
    di_oggi = sum(1 for t in davanti if _giorni(t, oggi) == 0)
    if not task:
        verdetto = TESTI["verdetto_lista_vuota"]
    elif not davanti:
        verdetto = TESTI["verdetto_niente"]
    else:
        pezzi = [_n("verdetto", len(davanti))]
        if scadute:
            pezzi.append(_n("verdetto_scadute", scadute))
        if di_oggi:
            pezzi.append(_n("verdetto_oggi", di_oggi))
        verdetto = " ".join(pezzi)
    ferme = sum(1 for t in task if _ferma(t, oggi) and not _davanti(t, oggi))
    return {
        "ok": True,
        "verdetto": verdetto,
        "tante": TESTI["davanti_tante"] if len(davanti) > TANTE else "",
        "letto": _frase_letto(letto, oggi),
        "avviso": avviso,
        "davanti": len(davanti),
        "con_allarme": scadute + di_oggi,
        "aperte": len(task),
        "nota_ferme": _n("nota_ferme", ferme) if ferme else "",
        "gruppi": gruppi,
        "aree": sorted({v["area"] for g in gruppi for v in g["voci"]}, key=str.casefold),
        "scelte_data": _scelte_data(oggi),
        **_per_tabella(task, per_gruppo, oggi),
        "testi": TESTI,
    }


def _per_tabella(task: list[dict], per_gruppo: dict[str, list[dict]], oggi: datetime) -> dict:
    ""


    grande = 9_999_999_999_999

    def per_scadenza(t):
        return (t.get("due_date") or grande, PESO.get(t.get("priority"), 4), -t["date_created"])

    def per_priorita(t):
        return (PESO.get(t.get("priority"), 4), t.get("due_date") or grande, -t["date_created"])

    veloci = sorted((t for t in task if (_minuti(t) or 999) <= VELOCE), key=per_scadenza)
    attese = sorted(
        (t for t in task if _area(t) == AREA_ATTESE),
        key=lambda t: (t.get("due_date") or grande, -t["date_created"]),
    )
    viste = [
        ("urgenti", per_gruppo["davanti"]),
        ("veloci", veloci),
        ("attese", attese),
        ("tutte", sorted(task, key=per_priorita)),
    ]
    gruppo_di = {t["id"]: g for g, righe in per_gruppo.items() for t in righe}

    ferme = [t for t in per_gruppo["davanti"] if _ferma(t, oggi)]
    frase_ferme = ""
    if ferme:
        mese = MESI[min(_scadenza(t) for t in ferme).month - 1]
        chiave = "rivedi_ferme_uno" if len(ferme) == 1 else "rivedi_ferme_tanti"
        frase_ferme = TESTI[chiave].format(n=len(ferme), mese=mese)
    return {
        "righe": [_voce(t, oggi, gruppo_di[t["id"]]) for t in task],
        "viste": [
            {
                "id": vid,
                "titolo": TESTI[f"vista_{vid}"],
                "aiuto": TESTI[f"aiuto_vista_{vid}"],
                "vuoto": TESTI[f"vuoto_vista_{vid}"],
                "id_righe": [t["id"] for t in righe],
            }
            for vid, righe in viste
        ],
        "colonne": {
            c: TESTI[f"colonna_{c}"]
            for c in ("task", "priorita", "scadenza", "stima", "area", "cambio", "creata")
        },
        "scelte_priorita": [
            {"id": str(n), "nome": TESTI[f"priorita_{n}"]} for n in (1, 2, 3, 4, 0)
        ],
        "scelte_stima": [{"id": str(m), "nome": _frase_minuti(m)} for m in (5, 15, 30, 60, 120)],
        "ferme": {"frase": frase_ferme, "id_righe": [t["id"] for t in ferme]},
    }


def _frase_letto(letto: datetime, oggi: datetime) -> str:
    ora = letto.strftime("%H:%M")
    if letto.date() == oggi.date():
        return TESTI["letto_oggi"].format(ora=ora)
    if letto.date() == (oggi - timedelta(days=1)).date():
        return TESTI["letto_ieri"].format(ora=ora)
    return TESTI["letto_il"].format(giorno=_il(letto, oggi), ora=ora)


def stato(rileggi: bool = False) -> dict:
    ""
    copia = _copia()
    oggi = _adesso()
    if copia and not rileggi:
        letto = datetime.fromisoformat(copia["letto"])

        if os.environ.get("SB_COSE_FERMA") or abs(oggi - letto) < VALIDITA:
            return _pagina(copia["task"], letto)
    giro = (copia or {}).get("giro", 0)
    try:
        task = _leggi_clickup()
    except Errore as e:
        if copia:
            avviso = TESTI[e.chiave]
            if e.chiave in ("errore_clickup", "errore_rete", "errore_troppe", "errore_strano"):
                avviso += " " + TESTI["errore_copia"]
            return _pagina(copia["task"], datetime.fromisoformat(copia["letto"]), avviso)
        return {"ok": False, "errore": TESTI[e.chiave], "testi": TESTI}
    try:
        with _Lucchetto():
            adesso = _copia()
            if adesso and adesso.get("giro", 0) != giro:


                return _pagina(adesso["task"], datetime.fromisoformat(adesso["letto"]))
            _salva(task, oggi, giro)
    except OSError:
        pass
    return _pagina(task, oggi)





def _quando(parola: str, oggi: datetime) -> int | None:
    ""

    if parola == "togli":
        return None
    if parola.startswith("ms:"):
        return int(parola[3:])
    base = oggi.replace(hour=12, minute=0, second=0, microsecond=0)
    if parola == "oggi":
        g = base
    elif parola == "domani":
        g = base + timedelta(days=1)
    elif parola == "lunedi":
        g = base + timedelta(days=(7 - base.weekday()) or 7)
    elif parola == "settimana":
        g = base + timedelta(days=7)
    elif parola == "mese":

        anno, mese = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
        ultimo = calendar.monthrange(anno, mese)[1]
        g = base.replace(year=anno, month=mese, day=min(base.day, ultimo))
    else:
        try:
            g = datetime.strptime(parola, "%Y-%m-%d").replace(hour=12)
        except ValueError as e:
            raise Errore("errore_giorno", parola) from e
    return _in_ms(g)


def _nella_copia(tid: str) -> dict | None:
    copia = _copia()
    return next((t for t in (copia or {}).get("task", []) if t["id"] == tid), None)


def _aggiorna_copia(tid: str, cambia: dict | None, rimetti: dict | None = None) -> None:
    ""


    try:
        with _Lucchetto():
            copia = _copia()
            if not copia:
                return
            task = []
            for t in copia["task"]:
                if t["id"] != tid:
                    task.append(t)
                elif cambia is not None:
                    task.append({**t, **cambia})
            if rimetti and not any(t["id"] == tid for t in task):
                task.append(rimetti)
            _salva(task, datetime.fromisoformat(copia["letto"]), copia.get("giro", 0) + 1)
    except (OSError, ValueError):
        pass


def _esito(messaggio: str, annulla: list[str] | None = None) -> dict:
    out = {"ok": True, "messaggio": messaggio, "testo_annulla": TESTI["annulla"]}
    if annulla:
        out["annulla"] = annulla
    return out


def _scrivi(tid: str, corpo: dict, non_riuscito: str) -> dict:
    ""

    try:
        risposta = _api("PUT", f"/task/{tid}", corpo)
    except Errore as e:
        if e.chiave == "errore_sparita":
            _aggiorna_copia(tid, None)
            raise
        if e.chiave in ("errore_chiave", "errore_chiave_rifiutata"):
            raise
        raise Errore(e.chiave, non_riuscito) from e
    if not isinstance(risposta, dict) or not risposta.get("id"):
        return {}
    asciutta = _asciutta(risposta)

    presenti = {"priority", "due_date", "date_updated", "name"} & set(risposta)
    dopo = {k: asciutta[k] for k in presenti}



    if "due_date" in corpo and "due_date" in dopo:
        chiesta, avuta = corpo["due_date"], dopo["due_date"]
        if (chiesta is None) != (avuta is None) or (
            chiesta and avuta and abs(chiesta - avuta) > 36 * 3600 * 1000
        ):
            raise Errore("errore_strano", non_riuscito)
    if "priority" in corpo and "priority" in dopo:
        if NUMERO_PRIORITA.get(dopo["priority"], 0) != (corpo["priority"] or 0):
            raise Errore("errore_strano", non_riuscito)
    return dopo


def _commenta(tid: str, chiave: str) -> None:
    adesso = _adesso()
    try:
        _api(
            "POST",
            f"/task/{tid}/comment",
            {
                "comment_text": TESTI[chiave].format(
                    giorno=adesso.strftime("%d/%m/%Y"), ora=adesso.strftime("%H:%M")
                ),
                "notify_all": False,
            },
        )
    except Exception:  # noqa: BLE001, S110 the gesture succeeded: a missing comment line does not make it look failed
        pass


def _chiuse() -> dict:
    ""
    try:
        return json.loads((CARTELLA / "chiuse-da-qui.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fatta(tid: str) -> dict:
    prima = _nella_copia(tid)
    _scrivi(tid, {"status": STATO_CHIUSO}, "errore_fatta")

    _commenta(tid, "commento_fatta")
    _aggiorna_copia(tid, None)
    if prima:
        try:
            with _Lucchetto():

                chiuse = {k: v for k, v in _chiuse().items() if k != tid}
                _scrivi_file(
                    CARTELLA / "chiuse-da-qui.json",
                    dict(list({**chiuse, tid: prima}.items())[-50:]),
                )
        except (OSError, ValueError):
            pass
    return _esito(TESTI["esito_fatta"], ["riapri", tid])


def riapri(tid: str) -> dict:
    _scrivi(tid, {"status": STATO_APERTO}, "errore_riapri")
    _commenta(tid, "commento_riaperta")
    rimetti = _chiuse().get(tid)
    if rimetti:
        _aggiorna_copia(tid, rimetti, rimetti=rimetti)
    return _esito(TESTI["esito_riaperta"])


def data(tid: str, parola: str, annulla: bool = False) -> dict:
    ""
    oggi = _adesso()
    prima = _nella_copia(tid)
    ms = _quando(parola, oggi)
    dopo_clickup = _scrivi(tid, {"due_date": ms, "due_date_time": False}, "errore_data")
    if ms is not None and dopo_clickup.get("due_date"):
        ms = dopo_clickup["due_date"]
    cambia = {"due_date": ms}
    if dopo_clickup.get("date_updated"):
        cambia["date_updated"] = dopo_clickup["date_updated"]
    _aggiorna_copia(tid, cambia)
    if annulla:
        return _esito(TESTI["esito_annullato"])
    indietro = None
    if prima is not None:
        vecchia = prima.get("due_date")
        indietro = ["data", tid, f"ms:{vecchia}" if vecchia else "togli", "annulla"]
    dopo = {**(prima or {}), "due_date": ms}
    if ms is None:
        chiave = "esito_data_tolta_davanti" if _davanti(dopo, oggi) else "esito_data_tolta"
        return _esito(TESTI[chiave], indietro)
    giorno = _da_ms(ms)
    if _davanti(dopo, oggi):
        return _esito(
            TESTI["esito_data_davanti"].format(quando=_quando_parole(giorno, oggi)), indietro
        )
    torna = giorno - timedelta(days=PRIMA)
    if torna.date() <= oggi.date():

        return _esito(TESTI["esito_data"], indietro)
    return _esito(
        TESTI["esito_data_dopo"].format(
            quando=_quando_parole(giorno, oggi), torna=_quando_parole(torna, oggi)
        ),
        indietro,
    )


def priorita(tid: str, numero: int, messaggio: str | None = None, annulla: bool = False) -> dict:
    ""

    prima = _nella_copia(tid)
    dopo_clickup = _scrivi(tid, {"priority": numero or None}, "errore_priorita")
    cambia = {"priority": next((k for k, v in NUMERO_PRIORITA.items() if v == numero), None)}
    if dopo_clickup.get("date_updated"):
        cambia["date_updated"] = dopo_clickup["date_updated"]
    _aggiorna_copia(tid, cambia)
    if annulla:
        return _esito(TESTI["esito_annullato"])
    indietro = None
    if prima is not None:
        indietro = ["priorita", tid, str(NUMERO_PRIORITA.get(prima.get("priority"), 0)), "annulla"]
    if messaggio is None:
        messaggio = TESTI["esito_priorita_0" if not numero else "esito_priorita"].format(
            nome=TESTI[f"priorita_{numero}"].lower()
        )
    return _esito(messaggio, indietro)


def stima(tid: str, parola: str, annulla: bool = False) -> dict:
    ""
    prima = _nella_copia(tid)
    try:
        minuti = None if parola == "togli" else int(parola)
    except ValueError as e:
        raise Errore("errore_comando", parola) from e
    ms = minuti * 60000 if minuti else None
    _scrivi(tid, {"time_estimate": ms}, "errore_stima")
    _aggiorna_copia(tid, {"time_estimate": ms})
    if annulla:
        return _esito(TESTI["esito_annullato"])
    indietro = None
    if prima is not None:
        vecchia = _minuti(prima)
        indietro = ["stima", tid, str(vecchia) if vecchia else "togli", "annulla"]
    return _esito(
        TESTI["esito_stima"].format(quanto=_frase_minuti(minuti))
        if minuti
        else TESTI["esito_stima_tolta"],
        indietro,
    )


def davanti(tid: str, si: bool) -> dict:
    if si:
        return priorita(tid, 1, TESTI["esito_davanti"])
    prima = _nella_copia(tid)
    resta = prima is not None and _in_settimana(prima, _adesso())
    return priorita(tid, 2, TESTI["esito_non_urgente" if resta else "esito_non_davanti"])


def esegui(argv: list[str]) -> dict:
    ""
    try:
        if not argv or argv == ["--rileggi"]:
            return stato(rileggi=bool(argv))
        verbo, resto = argv[0], argv[1:]
        if verbo == "fatta" and len(resto) == 1:
            return fatta(resto[0])
        if verbo == "riapri" and len(resto) == 1:
            return riapri(resto[0])
        if verbo == "data" and len(resto) == 2:
            return data(resto[0], resto[1])
        if verbo == "data" and len(resto) == 3 and resto[2] == "annulla":
            return data(resto[0], resto[1], annulla=True)
        if verbo == "davanti" and len(resto) == 2 and resto[1] in ("si", "no"):
            return davanti(resto[0], resto[1] == "si")
        if verbo == "priorita" and len(resto) in (2, 3) and resto[1] in ("0", "1", "2", "3", "4"):

            return priorita(resto[0], int(resto[1]), annulla=resto[2:] == ["annulla"])
        if verbo == "stima" and len(resto) in (2, 3):
            return stima(resto[0], resto[1], annulla=resto[2:] == ["annulla"])
        return {"ok": False, "errore": TESTI["errore_comando"]}
    except Errore as e:
        frase = TESTI[e.chiave]

        if e.dettaglio in TESTI and e.dettaglio.startswith("errore_"):
            frase += " " + TESTI[e.dettaglio]
        return {"ok": False, "errore": frase, "sparita": e.chiave == "errore_sparita"}
    except Exception as e:  # noqa: BLE001 the app always expects JSON, never a traceback
        return {
            "ok": False,
            "errore": TESTI["errore_motore"],
            "sparita": False,
            "dettaglio": type(e).__name__,
        }


if __name__ == "__main__":
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        sys.exit(0)
    print(json.dumps(esegui(sys.argv[1:]), ensure_ascii=False))
