#!/usr/bin/env python3
""















































































from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()



CLICKUP_API_KEY = os.environ.get("CLICKUP_API_KEY")


def _richiedi_token() -> None:
    # Checked after argument parsing, so --help works without a token.
    if not CLICKUP_API_KEY:
        sys.exit(
            "CLICKUP_API_KEY env var not set: put your personal API token in .env and export it "
            "(set -a && source .env && set +a), see docs/CONNECTING.md#clickup. Nothing downloaded."
        )


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import CLICKUP_TEAMS, DATA_ROOT, mark_last_run  # noqa: E402





# Workspaces from sbk.config.json "clickup.teams" ({team_id: name}). The first one
# is stored in clickup/backup/, the others in clickup/backup-<id>/. Empty = every
# workspace the API token can see, asked to ClickUp at run time (_tutti_i_team).
TEAMS: dict[str, tuple[str, Path]] = {
    tid: (name or tid, DATA_ROOT / "clickup" / ("backup" if i == 0 else f"backup-{tid}"))
    for i, (tid, name) in enumerate(CLICKUP_TEAMS.items())
}


def cartella_del_team(tid: str, prima: str) -> str:
    """Folder name of a workspace's backup: the first one is backup/, the others backup-<id>/."""
    return "backup" if tid == prima else f"backup-{tid}"


TEAM_ID = os.environ.get("SBK_CLICKUP_TEAM", "")
if TEAM_ID and TEAM_ID not in TEAMS:
    if TEAMS:
        sys.exit(
            f"unknown ClickUp workspace: {TEAM_ID} (known: {', '.join(TEAMS)}); "
            "add it to clickup.teams in sbk.config.json"
        )
    # no clickup.teams configured: the parent run discovered this id and says where it goes
    TEAMS[TEAM_ID] = (
        TEAM_ID,
        DATA_ROOT / "clickup" / os.environ.get("SBK_CLICKUP_BACKUP_NAME", "backup"),
    )
BASE_URL = "https://api.clickup.com/api/v2"
BASE_URL_V3 = "https://api.clickup.com/api/v3"

BACKUP_DIR = TEAMS[TEAM_ID][1] if TEAM_ID else DATA_ROOT / "clickup" / "backup"
META_DIR = BACKUP_DIR / "_meta"
MANIFEST_PATH = META_DIR / "manifest.json"
EDIT_TRACKER_PATH = META_DIR / "edit-tracker.json"
RUN_HISTORY_PATH = META_DIR / "run-history.jsonl"





RATE_LIMIT_RPM = 90
RATE_INTERVAL = 60.0 / RATE_LIMIT_RPM
BURST_CAPACITY = 10
REQUEST_TIMEOUT_SECS = 30
MAX_RETRIES = 5
BACKOFF_BASE = 2
MAX_BACKOFF = 30


TASKS_PAGE_SIZE = 100













RETE_TETTO_S = 2 * 3600
RETE_PRIMA_ATTESA_S = 15
RETE_ATTESA_MAX_S = 300

ENV_RETE_SPESO = "SBK_CLICKUP_RETE_SPESO_S"
ENV_RETE_CONTO = "SBK_CLICKUP_RETE_CONTO"



_ERRNO_RETE = frozenset(
    {errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EHOSTDOWN, errno.EADDRNOTAVAIL}
)



_bucket_lock = threading.Lock()
_bucket_tokens = BURST_CAPACITY
_bucket_last_refill = time.monotonic()


def _wait_for_token():
    ""
    global _bucket_tokens, _bucket_last_refill

    while True:
        with _bucket_lock:
            now = time.monotonic()
            elapsed = now - _bucket_last_refill
            new_tokens = elapsed / RATE_INTERVAL
            if new_tokens >= 1.0:
                consumed = int(new_tokens)
                _bucket_tokens = min(BURST_CAPACITY, _bucket_tokens + consumed)
                _bucket_last_refill += consumed * RATE_INTERVAL

            if _bucket_tokens > 0:
                _bucket_tokens -= 1
                return


        time.sleep(RATE_INTERVAL / 2)







_rete_lock = threading.Lock()
_rete_ok = threading.Event()
_rete_ok.set()
_rete_persa = threading.Event()


_rete: dict = {
    "giu_dal": 0.0,
    "sonda": None,
    "prove": 0,
    "errore": "",
    "speso_prima": 0.0,
    "speso": 0.0,
}


def _rete_spesa(adesso: float | None = None) -> float:
    ""
    in_corso = 0.0
    if not _rete_ok.is_set() and not _rete_persa.is_set():
        in_corso = (time.monotonic() if adesso is None else adesso) - _rete["giu_dal"]
    return _rete["speso_prima"] + _rete["speso"] + max(in_corso, 0.0)


def _e_rete_assente(e: BaseException) -> bool:
    ""
    causa = e.reason if isinstance(e, URLError) and isinstance(e.reason, BaseException) else e
    if isinstance(causa, socket.gaierror):
        return True
    return isinstance(causa, OSError) and causa.errno in _ERRNO_RETE


def _rete_caduta(endpoint: str, e: BaseException) -> None:
    with _rete_lock:
        if _rete_ok.is_set() and not _rete_persa.is_set():
            _rete_ok.clear()
            _rete["giu_dal"] = time.monotonic()
            _rete["prove"] = 0
            _inc("cadute_di_rete")
            log.warning(
                "Network down (%s, on %s): all workers stop and wait for the network, cap %d s for"
                " the run, already spent %d s",
                e,
                endpoint,
                RETE_TETTO_S,
                _rete["speso_prima"] + _rete["speso"],
            )
        if _rete["sonda"] == threading.get_ident():
            _rete["sonda"] = None
        _rete["errore"] = str(e)[:200]


def _rete_tornata() -> None:
    if _rete_ok.is_set():
        return
    with _rete_lock:
        if _rete_ok.is_set():
            return
        durata = time.monotonic() - _rete["giu_dal"]
        _rete["speso"] += durata
        _rete["sonda"] = None
        _rete_ok.set()
    log.warning("Network back after %d s: resuming from the same object", durata)


def _lascia_la_sonda() -> None:
    ""
    with _rete_lock:
        if _rete["sonda"] == threading.get_ident():
            _rete["sonda"] = None


def _attendi_la_rete() -> bool:
    ""
    while True:
        if _rete_persa.is_set():
            return False
        if _rete_ok.is_set():
            return True
        sonda = False
        with _rete_lock:
            if _rete_ok.is_set() or _rete_persa.is_set():
                continue
            adesso = time.monotonic()
            passati = adesso - _rete["giu_dal"]
            spesi = _rete_spesa(adesso)
            if spesi >= RETE_TETTO_S:
                _rete["speso"] += passati
                _rete_persa.set()
                _rete_ok.set()
                log.error(
                    "Network down for %d s, %d s without network over the whole run, beyond the cap of %d s (last"
                    " error: %s): no more calls, the objects not done go into _meta/%s",
                    passati,
                    spesi,
                    RETE_TETTO_S,
                    _rete["errore"],
                    DA_RIFARE_FILE,
                )
                return False
            if _rete["sonda"] is None:
                sonda = True
                _rete["sonda"] = threading.get_ident()


                attesa = min(
                    RETE_PRIMA_ATTESA_S * (2 ** min(_rete["prove"], 16)),
                    RETE_ATTESA_MAX_S,
                    max(RETE_TETTO_S - spesi, 0),
                )
                _rete["prove"] += 1
        if sonda:
            log.info("Network down for %d s: retrying in %d s", passati, attesa)
            time.sleep(attesa)
            return True
        _rete_ok.wait(timeout=min(RETE_PRIMA_ATTESA_S, 5.0))




_stats_lock = threading.Lock()
stats: dict[str, int | float | str | list | None] = {
    "start_time": None,
    "end_time": None,
    "duration_secs": 0,
    "mode": "full",
    "spaces": 0,
    "folders": 0,
    "lists": 0,
    "tasks_total": 0,
    "tasks_downloaded": 0,
    "tasks_skipped_unchanged": 0,
    "subtasks": 0,
    "comments": 0,
    "time_entries": 0,
    "docs": 0,
    "custom_fields": 0,
    "members": 0,
    "tags": 0,
    "api_calls": 0,
    "errors": [],
}


def _inc(key: str, n: int = 1):
    with _stats_lock:
        stats[key] = stats.get(key, 0) + n


def _add_error(msg: str):
    with _stats_lock:
        stats["errors"].append(msg)




logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("clickup-backup")






NEGATO = object()

SPARITO = object()

RIFIUTATO = object()


def api_get(
    endpoint: str,
    *,
    base: str = BASE_URL,
    params: dict | None = None,
    negato_e_errore: bool = True,
    sparito_e_none: bool = True,
    rifiutato_e_errore: bool = True,
) -> dict | list | object | None:
    ""











    url = f"{base}{endpoint}"
    if params:
        filtered = {k: v for k, v in params.items() if v is not None}
        if filtered:
            url = f"{url}?{urlencode(filtered)}"

    headers = {
        "Authorization": CLICKUP_API_KEY,
        "Content-Type": "application/json",
    }

    attempt = 0
    while attempt < MAX_RETRIES:
        if not _attendi_la_rete():
            _inc("chiamate_non_fatte_rete")
            return None
        _wait_for_token()
        _inc("api_calls")

        try:
            req = Request(url, method="GET", headers=headers)
            with urlopen(req, timeout=REQUEST_TIMEOUT_SECS) as resp:
                dati = json.loads(resp.read())
            _rete_tornata()
            return dati

        except HTTPError as e:
            _rete_tornata()
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass

            if e.code == 429:
                try:
                    retry_after = min(
                        int(e.headers.get("Retry-After", BACKOFF_BASE * (2**attempt))),
                        MAX_BACKOFF * 2,
                    )
                except (ValueError, TypeError):
                    retry_after = min(BACKOFF_BASE * (2**attempt), MAX_BACKOFF * 2)
                log.warning(
                    "Rate limited (429), waiting %ds (attempt %d/%d)",
                    retry_after,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(retry_after)
            elif e.code in (401, 403):
                if not negato_e_errore:
                    log.info("Outside access (%d): %s", e.code, endpoint)
                    return NEGATO
                log.error("Auth error %d for %s: %s", e.code, endpoint, body)
                _add_error(f"AUTH {e.code}: {endpoint}")
                return None
            elif e.code == 404:
                log.warning("Not found (404): %s", endpoint)
                return None if sparito_e_none else SPARITO
            elif e.code >= 500:
                wait = min(BACKOFF_BASE * (2**attempt), MAX_BACKOFF)
                log.warning(
                    "Server error %d, waiting %ds (attempt %d/%d)",
                    e.code,
                    wait,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(wait)
            else:
                if not rifiutato_e_errore:
                    log.info("Rejected (%d): %s", e.code, endpoint)
                    return RIFIUTATO
                log.error("HTTP %d for %s: %s", e.code, endpoint, body)
                _add_error(f"HTTP {e.code}: {endpoint}")
                return None

        except Exception as e:
            if _e_rete_assente(e):

                _rete_caduta(endpoint, e)
                continue
            _lascia_la_sonda()
            wait = min(BACKOFF_BASE * (2**attempt), MAX_BACKOFF)
            log.warning(
                "Request error for %s: %s, waiting %ds (attempt %d/%d)",
                endpoint,
                e,
                wait,
                attempt + 1,
                MAX_RETRIES,
            )
            time.sleep(wait)

        attempt += 1
        if attempt >= MAX_RETRIES and not _rete_ok.is_set():


            log.warning("Retries exhausted on %s while the network is down: waiting for the network", endpoint)
            attempt = 0

    log.error("Failed after %d retries: %s", MAX_RETRIES, endpoint)
    _add_error(f"MAX_RETRIES: {endpoint}")
    return None





def load_edit_tracker() -> dict:
    ""
    if EDIT_TRACKER_PATH.exists():
        try:
            return json.loads(EDIT_TRACKER_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt edit tracker, starting fresh")
    return {}


_tracker_save_count = 0
_TRACKER_CHECKPOINT_INTERVAL = 100


def save_edit_tracker(tracker: dict, *, force: bool = False):
    ""




    global _tracker_save_count
    _tracker_save_count += 1
    if not force and _tracker_save_count % _TRACKER_CHECKPOINT_INTERVAL != 0:
        return
    META_DIR.mkdir(parents=True, exist_ok=True)



    save_json(EDIT_TRACKER_PATH, dict(tracker))


def voci_degli_space(tracker: dict, space_ids: set[str]) -> set[str]:
    ""
    trovati: set[str] = set()
    for sid in space_ids:
        cartella = BACKUP_DIR / "spaces" / sid
        if cartella.is_dir():
            trovati.update(p.stem for p in cartella.rglob("tasks/*.json"))
    return trovati & set(tracker)


def tracker_di_partenza(incremental: bool, space_filter: set[str] | None) -> dict:
    ""







    if incremental:
        tracker = load_edit_tracker()
        log.info("Edit tracker: %d tasks tracked from previous run", len(tracker))
        return tracker
    if not space_filter:
        return {}
    tracker = load_edit_tracker()
    da_riscrivere = voci_degli_space(tracker, space_filter)
    for tid in da_riscrivere:
        del tracker[tid]
    log.info(
        "Full run on %d spaces: tracker loaded, %d entries of these spaces are rewritten, %d of the others remain",
        len(space_filter),
        len(da_riscrivere),
        len(tracker),
    )
    return tracker





def save_json(path: Path, data) -> None:
    ""



    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    with NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.rename(path)





def backup_members() -> list[dict]:
    ""
    log.info("Downloading workspace members...")



    data = api_get("/team")
    if not data:
        if not _rete_persa.is_set():
            _add_error("Failed to download members")
        return []

    members = []
    if isinstance(data, dict):
        for team in data.get("teams") or []:
            if str(team.get("id")) == TEAM_ID:
                members = team.get("members") or []
                break
        if not members and "members" in data:
            members = data["members"]
    elif isinstance(data, list):
        members = data

    save_json(BACKUP_DIR / "members.json", members)
    _inc("members", len(members))
    log.info("Members: %d", len(members))
    return members


def _vivi_e_archiviati(endpoint: str, chiave: str, esito: dict | None = None) -> list[dict] | None:
    ""


    vivi = api_get(endpoint, params={"archived": "false"})
    if not vivi or chiave not in vivi:
        if esito is not None:
            esito["completo"] = False
        return None
    archiviati = api_get(endpoint, params={"archived": "true"})
    if esito is not None and not (isinstance(archiviati, dict) and chiave in archiviati):
        esito["completo"] = False
    archiviati = archiviati or {}
    visti = {o.get("id") for o in vivi[chiave]}
    return vivi[chiave] + [o for o in archiviati.get(chiave, []) if o.get("id") not in visti]


def backup_spaces(space_filter: set[str] | None = None) -> list[dict]:
    ""
    log.info("Downloading spaces...")
    elenco = {"completo": True}
    spaces = _vivi_e_archiviati(f"/team/{TEAM_ID}/space", "spaces", elenco)
    if spaces is None:
        if not _rete_persa.is_set():
            _add_error("Failed to download spaces")
        return []
    if elenco["completo"]:


        _space_esistenti.clear()
        _space_esistenti.update(str(s.get("id")) for s in spaces)
        _space_esistenti_noti.set()
    data = {"spaces": spaces}
    if space_filter:
        spaces = [s for s in spaces if s["id"] in space_filter]
        log.info("Filtered to %d spaces (of %d total)", len(spaces), len(data["spaces"]))

    for space in spaces:
        space_dir = BACKUP_DIR / "spaces" / space["id"]
        save_json(space_dir / "space.json", space)

    _inc("spaces", len(spaces))
    log.info("Spaces: %d", len(spaces))
    return spaces


def backup_tags(space: dict) -> list[dict]:
    ""
    sid = space["id"]
    data = api_get(f"/space/{sid}/tag")
    if not data:
        return []

    tags = data.get("tags", [])
    if tags:
        save_json(BACKUP_DIR / "spaces" / sid / "tags.json", tags)
        _inc("tags", len(tags))
    return tags


def backup_folders(space: dict, esito: dict | None = None) -> list[dict]:
    ""
    sid = space["id"]
    folders = _vivi_e_archiviati(f"/space/{sid}/folder", "folders", esito)
    if folders is None:
        return []
    for folder in folders:
        fid = folder["id"]
        folder_dir = BACKUP_DIR / "spaces" / sid / "folders" / fid
        save_json(folder_dir / "folder.json", folder)
        _inc("folders")

    return folders


def backup_folderless_lists(space: dict, esito: dict | None = None) -> list[dict]:
    ""
    sid = space["id"]
    lists = _vivi_e_archiviati(f"/space/{sid}/list", "lists", esito)
    if lists is None:
        return []
    for lst in lists:
        lid = lst["id"]
        list_dir = BACKUP_DIR / "spaces" / sid / "folderless_lists" / lid
        save_json(list_dir / "list.json", lst)
        _inc("lists")

    return lists


def backup_lists_in_folder(space_id: str, folder: dict, esito: dict | None = None) -> list[dict]:
    ""
    fid = folder["id"]
    lists = _vivi_e_archiviati(f"/folder/{fid}/list", "lists", esito)
    if lists is None:
        return []
    for lst in lists:
        lid = lst["id"]
        list_dir = BACKUP_DIR / "spaces" / space_id / "folders" / fid / "lists" / lid
        save_json(list_dir / "list.json", lst)
        _inc("lists")

    return lists


def backup_custom_fields(list_dir: Path, list_id: str) -> list[dict]:
    ""
    data = api_get(f"/list/{list_id}/field")
    if not data or "fields" not in data:
        return []

    fields = data["fields"]
    if fields:
        save_json(list_dir / "fields.json", fields)
        _inc("custom_fields", len(fields))
    return fields


def get_all_tasks_in_list(list_id: str, esito: dict | None = None) -> list[dict]:
    ""





    all_tasks: list[dict] = []
    visti: set[str] = set()
    for archiviati in ("false", "true"):
        page = 0
        while True:
            data = api_get(
                f"/list/{list_id}/task",
                params={
                    "subtasks": "true",
                    "include_closed": "true",
                    "archived": archiviati,
                    "page": str(page),
                    "order_by": "updated",
                    "reverse": "true",
                },
            )
            if not data or "tasks" not in data:
                if esito is not None:
                    esito["completo"] = False
                break

            tasks = data["tasks"]
            if not tasks:
                break

            all_tasks.extend(t for t in tasks if t.get("id") not in visti)
            visti.update(t.get("id") for t in tasks)
            page += 1


            if len(tasks) < TASKS_PAGE_SIZE:
                break

    return all_tasks



COMMENTI_PER_PAGINA = 25


def tutti_i_commenti(tid: str) -> tuple[list[dict], bool]:
    ""

    commenti: list[dict] = []
    completo = True
    params: dict | None = None
    for _ in range(1000):
        data = api_get(f"/task/{tid}/comment", params=params)
        if not data or "comments" not in data:
            completo = False
            break
        pagina = data["comments"]
        commenti.extend(pagina)
        if len(pagina) < COMMENTI_PER_PAGINA:
            break
        ultimo = pagina[-1]
        params = {"start": ultimo.get("date"), "start_id": ultimo.get("id")}
    for c in commenti:
        if int(c.get("reply_count") or 0) > 0:
            risposte = api_get(f"/comment/{c.get('id')}/reply")
            if not risposte or "comments" not in risposte:
                completo = False
                continue
            c["_risposte"] = risposte["comments"]
            _inc("replies", len(risposte["comments"]))
    return commenti, completo


def da_completare(percorso: Path) -> bool:
    ""


    try:
        d = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if "_completo" in d:
        return not d["_completo"]
    commenti = d.get("_comments") or []
    return len(commenti) >= COMMENTI_PER_PAGINA or any(
        int(c.get("reply_count") or 0) > 0 for c in commenti
    )





TASK_SPARITI_FILE = "task-spariti.json"

TASK_STORICI_FILE = "task-storici.json"

PRIMA_DELLA_PASSATA_DIR = "task-prima-della-passata"

RITROVATI_DIR = "task-ritrovati"


def percorso_di_oggi(task: dict) -> str:
    ""


    spazio = str((task.get("space") or {}).get("id") or "")
    cartella = task.get("folder") or {}
    lista = str((task.get("list") or {}).get("id") or "")
    if cartella.get("hidden"):
        return f"spaces/{spazio}/folderless_lists/{lista}/tasks/{task['id']}.json"
    return f"spaces/{spazio}/folders/{cartella.get('id')}/lists/{lista}/tasks/{task['id']}.json"


def _leggi_meta(nome: str) -> dict:
    try:
        d = json.loads((META_DIR / nome).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}





DA_RIFARE_FILE = "da-rifare.json"
_TIPI_DA_RIFARE = ("spaces", "liste", "task")
_da_rifare_lock = threading.Lock()
_da_rifare: dict[str, dict] = {t: {} for t in _TIPI_DA_RIFARE}

_da_rifare_prima: dict[str, dict] = {t: {} for t in _TIPI_DA_RIFARE}



_fatti: dict[str, set[str]] = {t: set() for t in _TIPI_DA_RIFARE}

_space_esistenti: set[str] = set()
_space_esistenti_noti = threading.Event()

DA_RIFARE_SCARTATE_FILE = "da-rifare-scartate.json"


def _segna_da_rifare(tipo: str, chiave: str, space_id: str, cartella: Path | None = None) -> None:
    voce: dict = {"space": space_id}
    if cartella is not None:
        try:
            voce["dir"] = cartella.relative_to(BACKUP_DIR).as_posix()
        except ValueError:
            voce["dir"] = str(cartella)
    with _da_rifare_lock:
        _da_rifare[tipo].setdefault(chiave, voce)


def _segna_fatto(tipo: str, chiave: str) -> None:
    with _da_rifare_lock:
        _fatti[tipo].add(chiave)


def _metti_da_parte_il_da_rifare(perche: str) -> None:
    ""
    p = META_DIR / DA_RIFARE_FILE
    nuovo = p.with_name(f"{p.name}.illeggibile-{datetime.now(UTC):%Y%m%dT%H%M%S}")
    try:
        p.rename(nuovo)
    except OSError as e:
        log.warning(
            "_meta/%s %s and cannot be renamed (%s): leaving it as is", DA_RIFARE_FILE, perche, e
        )
        return
    log.warning(
        "_meta/%s %s: set aside as _meta/%s, the run continues without it",
        DA_RIFARE_FILE,
        perche,
        nuovo.name,
    )
    _inc("da_rifare_messo_da_parte")


def carica_da_rifare() -> dict[str, dict]:
    ""


    p = META_DIR / DA_RIFARE_FILE
    d: dict = {}
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = None
        if not isinstance(d, dict):
            _metti_da_parte_il_da_rifare("cannot be read")
            d = {}
    scartate: dict[str, object] = {}
    for tipo in _TIPI_DA_RIFARE:
        voci = d.get(tipo)
        if voci is not None and not isinstance(voci, dict):
            scartate[tipo] = voci
            voci = {}
        buone = {}
        for chiave, voce in (voci or {}).items():
            if isinstance(voce, dict):
                buone[str(chiave)] = voce
            else:
                scartate[f"{tipo}/{chiave}"] = voce
        _da_rifare_prima[tipo] = buone
    if scartate:
        vecchie = _leggi_meta(DA_RIFARE_SCARTATE_FILE)
        vecchie[datetime.now(UTC).isoformat(timespec="seconds")] = scartate
        save_json(META_DIR / DA_RIFARE_SCARTATE_FILE, vecchie)
        log.warning(
            "_meta/%s: %d entries that cannot be read (%s), set aside in _meta/%s",
            DA_RIFARE_FILE,
            len(scartate),
            ", ".join(sorted(scartate)),
            DA_RIFARE_SCARTATE_FILE,
        )
    n = sum(len(v) for v in _da_rifare_prima.values())
    if n:
        log.info(
            "To redo from the previous run (_meta/%s): %d spaces, %d lists, %d tasks, done first",
            DA_RIFARE_FILE,
            len(_da_rifare_prima["spaces"]),
            len(_da_rifare_prima["liste"]),
            len(_da_rifare_prima["task"]),
        )
    return _da_rifare_prima


def space_da_rifare_prima() -> set[str]:
    ""
    return set(_da_rifare_prima["spaces"]) | {
        str(v.get("space"))
        for tipo in ("liste", "task")
        for v in _da_rifare_prima[tipo].values()
        if isinstance(v, dict) and v.get("space")
    }


def salva_da_rifare(spazi_del_giro: set[str]) -> dict[str, dict]:
    ""




    with _da_rifare_lock:
        resta = {t: dict(_da_rifare[t]) for t in _TIPI_DA_RIFARE}
        fatti = {t: set(_fatti[t]) for t in _TIPI_DA_RIFARE}
    esistenti = set(_space_esistenti) if _space_esistenti_noti.is_set() else None
    usciti: dict[str, list[str]] = {t: [] for t in _TIPI_DA_RIFARE}
    for tipo in _TIPI_DA_RIFARE:
        for chiave, voce in _da_rifare_prima[tipo].items():
            sid = chiave if tipo == "spaces" else str(voce.get("space") or "")
            if chiave in fatti[tipo]:
                continue
            sparito = esistenti is not None and sid not in esistenti
            if tipo == "liste":
                sparito = sparito or sid in fatti["spaces"]
            if tipo == "task":
                lista = str(voce.get("dir") or "").rstrip("/").rsplit("/", 1)[-1]
                sparito = sparito or (bool(lista) and lista in fatti["liste"])
            if sparito:
                usciti[tipo].append(chiave)
                continue
            resta[tipo].setdefault(chiave, voce)
    if any(usciti.values()):
        log.warning(
            "To redo: dropping the entries of objects ClickUp no longer has (spaces %s, lists %s, tasks %s)",
            ", ".join(usciti["spaces"]) or "none",
            ", ".join(usciti["liste"]) or "none",
            ", ".join(usciti["task"]) or "none",
        )
    n = sum(len(v) for v in resta.values())
    save_json(
        META_DIR / DA_RIFARE_FILE,
        {
            "quando": datetime.now(UTC).isoformat(timespec="seconds"),
            "motivo": f"network down beyond {RETE_TETTO_S} s" if _rete_persa.is_set() else "",
            "oggetti": n,
            **resta,
        },
    )
    return resta


def _chiudi_senza_rete(spazi_del_giro: set[str], dry_run: bool) -> None:
    ""

    if dry_run:
        return
    resta = salva_da_rifare(spazi_del_giro)
    conti = {t: len(resta[t]) for t in _TIPI_DA_RIFARE}
    stats["da_rifare"] = conti
    if _rete_persa.is_set():
        stats["rete_persa"] = True
        messaggio = (
            f"NETWORK_DOWN: beyond {RETE_TETTO_S} s without network, the run stopped. To redo "
            f"{conti['spaces']} spaces, {conti['liste']} lists, {conti['task']} tasks in _meta/{DA_RIFARE_FILE}: "
            "the next run does them first"
        )
        log.error(messaggio)
        _add_error(messaggio)


def completa_i_vecchi(dry_run: bool = False) -> dict[str, int]:
    ""












    spariti = _leggi_meta(TASK_SPARITI_FILE)
    storici = _leggi_meta(TASK_STORICI_FILE)
    per_task: dict[str, list[Path]] = {}
    for percorso in sorted(BACKUP_DIR.rglob("tasks/*.json")):
        rel = percorso.relative_to(BACKUP_DIR).as_posix()
        if "_meta" in percorso.relative_to(BACKUP_DIR).parts or rel in storici:
            continue
        if percorso.stem in spariti or not da_completare(percorso):
            continue
        per_task.setdefault(percorso.stem, []).append(percorso)
    conti = {
        "da_completare": sum(len(v) for v in per_task.values()),
        "task": len(per_task),
        "completati": 0,
        "incompleti": 0,
        "ritrovati": 0,
        "gia_completi": 0,
        "storici": 0,
        "spariti": 0,
        "negati": 0,
        "errori": 0,
    }
    if dry_run:
        log.info("Old tasks (dry run): %s", conti)
        return conti
    adesso = datetime.now(UTC).isoformat(timespec="seconds")
    for tid, percorsi in per_task.items():
        task = api_get(f"/task/{tid}", negato_e_errore=False, sparito_e_none=False)
        if task is SPARITO or task is NEGATO:
            conti["spariti" if task is SPARITO else "negati"] += 1
            spariti[tid] = {
                "quando": adesso,
                "esito": "404" if task is SPARITO else "outside access",
                "file": [p.relative_to(BACKUP_DIR).as_posix() for p in percorsi],
            }
            save_json(META_DIR / TASK_SPARITI_FILE, spariti)
            continue
        if not isinstance(task, dict) or "id" not in task:
            conti["errori"] += 1
            continue
        oggi = percorso_di_oggi(task)
        nella_lista = [p for p in percorsi if p.relative_to(BACKUP_DIR).as_posix() == oggi]
        for p in percorsi:
            if p in nella_lista:
                continue
            storici[p.relative_to(BACKUP_DIR).as_posix()] = {
                "tid": tid,
                "percorso_di_oggi": oggi,
                "quando": adesso,
            }
            conti["storici"] += 1
        save_json(META_DIR / TASK_STORICI_FILE, storici)
        gia_li = [BACKUP_DIR / oggi] if (BACKUP_DIR / oggi).exists() and not nella_lista else []
        if gia_li and not any(da_completare(p) for p in gia_li):

            conti["gia_completi"] += 1
            continue
        if nella_lista:
            for p in nella_lista:
                prima = META_DIR / PRIMA_DELLA_PASSATA_DIR / p.relative_to(BACKUP_DIR)
                prima.parent.mkdir(parents=True, exist_ok=True)
                if not prima.exists():
                    prima.write_bytes(p.read_bytes())
                dettagli = backup_task_details(task, p.parent)
                conti["completati" if dettagli.get("_completo") else "incompleti"] += 1
        else:

            dettagli = backup_task_details(task, META_DIR / RITROVATI_DIR)
            conti["ritrovati"] += 1
            if not dettagli.get("_completo"):
                conti["incompleti"] += 1
    log.info("Old tasks: %s", conti)
    return conti


def backup_task_details(task: dict, task_dir: Path) -> dict:
    ""





    tid = task["id"]
    enriched = dict(task)


    enriched["_comments"], commenti_completi = tutti_i_commenti(tid)
    _inc("comments", len(enriched["_comments"]))




    tempi_completi = True


    enriched["_time_entries"] = _tempi_gia_salvati(task_dir / f"{tid}.json")
    if "time_spent" in task:
        time_data = api_get(
            f"/task/{tid}/time",
            negato_e_errore=False,
            sparito_e_none=False,
            rifiutato_e_errore=False,
        )
        if isinstance(time_data, dict) and "data" in time_data:
            enriched["_time_entries"] = time_data["data"]
            _inc("time_entries", len(time_data["data"]))
        elif any(time_data is r for r in (NEGATO, SPARITO, RIFIUTATO)):



            _inc("tempi_non_leggibili")
        else:


            tempi_completi = False
    enriched["_completo"] = commenti_completi and tempi_completi

    if _rete_persa.is_set():

        enriched["_completo"] = False
        enriched["_non_salvato"] = True
        return enriched


    save_json(task_dir / f"{tid}.json", enriched)
    return enriched


def _tempi_gia_salvati(percorso: Path) -> list:
    try:
        d = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    tempi = d.get("_time_entries") if isinstance(d, dict) else None
    return tempi if isinstance(tempi, list) else []


def backup_tasks_in_list(
    list_dir: Path,
    list_id: str,
    list_name: str,
    edit_tracker: dict,
    incremental: bool,
    dry_run: bool,
    space_id: str = "",
    etichetta: str = "",
) -> list[str]:
    ""












    elenco = {"completo": True}
    tasks = get_all_tasks_in_list(list_id, elenco)
    if _rete_persa.is_set():

        _segna_da_rifare("liste", list_id, space_id, list_dir)

    tutte_fatte = elenco["completo"] and not dry_run
    if not tasks:
        _avanzamento(etichetta, list_id, 0, 0, 0)
        if tutte_fatte and not _rete_persa.is_set():
            _segna_fatto("liste", list_id)
        return []

    tasks_dir = list_dir / "tasks"
    backed_up = []
    saltate = 0

    for task in tasks:
        tid = task["id"]
        date_updated = str(task.get("date_updated", ""))
        is_subtask = bool(task.get("parent"))

        _inc("tasks_total")
        if is_subtask:
            _inc("subtasks")


        if (
            incremental
            and tid in edit_tracker
            and edit_tracker[tid] == date_updated
            and tid not in _da_rifare_prima["task"]
            and not da_completare(tasks_dir / f"{tid}.json")
        ):
            _inc("tasks_skipped_unchanged")
            saltate += 1
            continue

        if dry_run:
            log.debug("  [DRY] Would backup task %s (%s)", tid, task.get("name", "")[:60])
            backed_up.append(tid)
            continue

        if _rete_persa.is_set():

            _segna_da_rifare("task", tid, space_id, list_dir)
            _segna_da_rifare("liste", list_id, space_id, list_dir)
            tutte_fatte = False
            continue

        dettagli = backup_task_details(task, tasks_dir)
        if dettagli.get("_non_salvato"):
            _segna_da_rifare("task", tid, space_id, list_dir)
            _segna_da_rifare("liste", list_id, space_id, list_dir)
            tutte_fatte = False
            continue
        _inc("tasks_downloaded")
        backed_up.append(tid)
        if len(backed_up) % 100 == 0:
            _avanzamento(etichetta, list_id, len(tasks), len(backed_up), saltate, finita=False)


        if not dettagli.get("_completo", True):
            _inc("tasks_incompleti")
            tutte_fatte = False
            continue
        edit_tracker[tid] = date_updated
        save_edit_tracker(edit_tracker)
        _segna_fatto("task", tid)

    _avanzamento(etichetta, list_id, len(tasks), len(backed_up), saltate)
    if tutte_fatte and not _rete_persa.is_set():
        _segna_fatto("liste", list_id)
    return backed_up


def _avanzamento(
    etichetta: str, list_id: str, lette: int, scaricate: int, saltate: int, *, finita: bool = True
) -> None:
    log.info(
        "  %s lista %s %s: %d task elencate, %d scaricate, %d invariate · chiamate fin qui %d",
        etichetta or "·",
        list_id,
        "fatta" if finita else "in corso",
        lette,
        scaricate,
        saltate,
        stats.get("api_calls", 0),
    )


def backup_docs() -> int:
    ""
    log.info("Downloading docs (v3 API)...")
    docs_dir = BACKUP_DIR / "docs"
    count = 0
    negati = BACKUP_DIR / "_meta" / DOCUMENTI_NEGATI_FILE
    _negati.clear()
    try:
        _negati.update(json.loads(negati.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


    next_cursor = None
    while True:
        params = {}
        if next_cursor:
            params["next_cursor"] = next_cursor

        data = api_get(
            f"/workspaces/{TEAM_ID}/docs",
            base=BASE_URL_V3,
            params=params if params else None,
        )

        if not data:
            if count == 0:
                _add_error("Failed to download docs (v3 API)")
            break


        docs = data.get("docs", [])
        if not docs:
            break

        for doc in docs:
            doc_id = doc.get("id", f"unknown_{count}")
            save_json(docs_dir / f"{doc_id}.json", doc)
            _pagine_del_documento(doc, docs_dir)
            count += 1
            _inc("docs")

        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break

    save_json(negati, dict(sorted(_negati.items())))
    log.info("Docs: %d (outside access: %d)", count, stats.get("docs_fuori_accesso", 0))
    return count






DOCUMENTI_NEGATI_FILE = "documenti-negati.json"
_negati: dict[str, str] = {}


def _pagine_del_documento(doc: dict, docs_dir: Path) -> None:
    ""

    doc_id = doc.get("id")
    if not doc_id:
        return
    file_pagine = docs_dir / f"{doc_id}.pages.json"
    cambiato = str(doc.get("date_updated") or doc.get("date_created") or "")
    if file_pagine.exists():
        try:
            if json.loads(file_pagine.read_text(encoding="utf-8")).get("_date_updated") == cambiato:
                return
        except (OSError, ValueError):
            pass
    elif _negati.get(doc_id) == cambiato:
        _inc("docs_fuori_accesso")
        return
    pagine = api_get(
        f"/workspaces/{TEAM_ID}/docs/{doc_id}/pages",
        base=BASE_URL_V3,
        params={"max_page_depth": "-1", "content_format": "text/md"},
        negato_e_errore=file_pagine.exists(),
    )
    if pagine is NEGATO:
        _negati[doc_id] = cambiato
        _inc("docs_fuori_accesso")
        return
    if pagine is None:
        _add_error(f"document pages {doc_id} did not arrive")
        return
    _negati.pop(doc_id, None)
    save_json(file_pagine, {"_date_updated": cambiato, "pages": pagine})
    _inc("doc_pages")


def backup_bulk_time_entries() -> int:
    ""




    log.info("Downloading bulk time entries...")
    from datetime import timedelta

    now = datetime.now(UTC)
    total = 0


    for months_back in range(3):
        end = now - timedelta(days=30 * months_back)
        start = end - timedelta(days=30)

        start_ms = str(int(start.timestamp() * 1000))
        end_ms = str(int(end.timestamp() * 1000))

        data = api_get(
            f"/team/{TEAM_ID}/time_entries",
            params={"start_date": start_ms, "end_date": end_ms},
        )

        if not data:
            continue

        entries = data.get("data", [])
        if entries:
            month_label = start.strftime("%Y-%m")
            save_json(BACKUP_DIR / "time_entries" / f"bulk_{month_label}.json", entries)
            total += len(entries)
            _inc("time_entries", len(entries))

    log.info("Bulk time entries: %d (last 90 days)", total)
    return total





def process_space(
    space: dict,
    edit_tracker: dict,
    incremental: bool,
    dry_run: bool,
) -> dict:
    ""



    sid = space["id"]
    sname = space["name"]
    space_summary = {"space_id": sid, "space_name": sname, "lists": 0, "tasks": 0}
    if _rete_persa.is_set():
        _segna_da_rifare("spaces", sid, sid)
        log.info("Space %s (%s) not done: network down, to redo", sname, sid)
        return space_summary
    log.info("Processing space: %s (%s)", sname, sid)


    backup_tags(space)



    voci: list[tuple[Path, str, str]] = []
    struttura = {"completo": True}
    for folder in backup_folders(space, struttura):
        fid = folder["id"]
        for lst in backup_lists_in_folder(sid, folder, struttura):
            lid = lst["id"]
            voci.append(
                (
                    BACKUP_DIR / "spaces" / sid / "folders" / fid / "lists" / lid,
                    lid,
                    lst.get("name", lid),
                )
            )
    for lst in backup_folderless_lists(space, struttura):
        lid = lst["id"]
        voci.append(
            (BACKUP_DIR / "spaces" / sid / "folderless_lists" / lid, lid, lst.get("name", lid))
        )
    voci.sort(key=lambda v: v[1] not in _da_rifare_prima["liste"])

    for n, (list_dir, lid, lname) in enumerate(voci, 1):
        backup_custom_fields(list_dir, lid)
        backed = backup_tasks_in_list(
            list_dir,
            lid,
            lname,
            edit_tracker,
            incremental,
            dry_run,
            space_id=sid,
            etichetta=f"{sname} {n}/{len(voci)}",
        )
        space_summary["lists"] += 1
        space_summary["tasks"] += len(backed)

    if _rete_persa.is_set():

        _segna_da_rifare("spaces", sid, sid)
    elif struttura["completo"] and not dry_run and all(v[1] in _fatti["liste"] for v in voci):
        _segna_fatto("spaces", sid)
    log.info("  %s: %d lists, %d tasks", sname, space_summary["lists"], space_summary["tasks"])
    return space_summary





def save_manifest():
    ""
    META_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(stats, indent=2, default=str))


def append_run_history():
    ""
    META_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": stats["start_time"],
        "mode": stats["mode"],
        "duration_secs": stats["duration_secs"],
        "tasks_downloaded": stats["tasks_downloaded"],
        "tasks_skipped": stats["tasks_skipped_unchanged"],
        "errors_count": len(stats["errors"]),
        "api_calls": stats["api_calls"],
        "cadute_di_rete": stats.get("cadute_di_rete", 0),
        "da_rifare": stats.get("da_rifare"),
    }
    with open(RUN_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def print_summary():
    ""
    duration = stats["duration_secs"]
    mins = int(duration // 60)
    secs = int(duration % 60)

    print("\n" + "=" * 60)
    print("CLICKUP BACKUP SUMMARY")
    print("=" * 60)
    print(f"Mode:           {stats['mode']}")
    print(f"Duration:       {mins}m {secs}s")
    print(f"API calls:      {stats['api_calls']}")
    print(f"Spaces:         {stats['spaces']}")
    print(f"Folders:        {stats['folders']}")
    print(f"Lists:          {stats['lists']}")
    print(f"Tasks total:    {stats['tasks_total']}")
    print(f"  Downloaded:   {stats['tasks_downloaded']}")
    print(f"  Skipped:      {stats['tasks_skipped_unchanged']}")
    print(f"  Subtasks:     {stats['subtasks']}")
    print(f"Comments:       {stats['comments']}")
    print(f"Time entries:   {stats['time_entries']}")
    print(f"Docs:           {stats['docs']}")
    if stats.get("docs_fuori_accesso"):
        print(
            f"  Outside access: {stats['docs_fuori_accesso']} (the account cannot enter those places, "
            f"list in _meta/{DOCUMENTI_NEGATI_FILE})"
        )
    print(f"Custom fields:  {stats['custom_fields']}")
    print(f"Members:        {stats['members']}")
    print(f"Tags:           {stats['tags']}")
    if stats.get("cadute_di_rete"):
        print(
            f"Network drops:  {stats['cadute_di_rete']} (waits, not errors, except beyond the cap)"
        )
    if any((stats.get("da_rifare") or {}).values()):
        print(f"To redo:        {stats['da_rifare']} (_meta/{DA_RIFARE_FILE})")

    errors = stats["errors"]
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("\nNo errors.")
    print("=" * 60)





def get_backup_size_mb() -> float:
    ""
    total = 0
    for f in BACKUP_DIR.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)





def _tutti_i_team(scelta: str) -> int:
    ""





    squadre = {tid: v[0] for tid, v in TEAMS.items()}
    if not squadre:
        # no clickup.teams in sbk.config.json: ask ClickUp which workspaces the token sees
        risposta = api_get("/team")
        if isinstance(risposta, dict):
            squadre = {
                str(t.get("id")): t.get("name") or str(t.get("id"))
                for t in risposta.get("teams", [])
                if t.get("id")
            }
        if not squadre:
            log.error(
                "ClickUp: no workspace found for this CLICKUP_API_KEY, and clickup.teams "
                "in sbk.config.json is empty. Nothing downloaded."
            )
            return 2
        log.info("ClickUp workspaces seen by the token: %s", ", ".join(f"{n} ({t})" for t, n in squadre.items()))
    prima = next(iter(squadre))
    team_ids = list(squadre) if scelta in ("all", "tutti") else [scelta]
    ignoti = [t for t in team_ids if t not in squadre]
    if ignoti:
        log.error("unknown workspace: %s (known: %s)", ", ".join(ignoti), ", ".join(squadre))
        return 2
    argv = [
        a
        for i, a in enumerate(sys.argv[1:])
        if a != "--team" and sys.argv[i] != "--team" and not a.startswith("--team=")
    ]
    peggiore = 0


    speso = _speso_dal_padre()
    for tid in team_ids:
        log.info("=== workspace %s (%s) ===", squadre[tid], tid)
        with NamedTemporaryFile(prefix="clickup-rete-", suffix=".json", delete=False) as f:
            conto = Path(f.name)
        env = {
            **os.environ,
            "SBK_CLICKUP_TEAM": tid,
            "SBK_CLICKUP_BACKUP_NAME": cartella_del_team(tid, prima),
            ENV_RETE_SPESO: str(round(speso, 1)),
            ENV_RETE_CONTO: str(conto),
        }
        try:
            rc = subprocess.run([sys.executable, __file__, *argv], env=env).returncode
            speso += _leggi_conto(conto)
        finally:
            conto.unlink(missing_ok=True)
        log.info(
            "=== workspace %s: exit %d · without network so far %d s out of a cap of %d s for the run ===",
            squadre[tid],
            rc,
            speso,
            RETE_TETTO_S,
        )
        peggiore = max(peggiore, rc)
    return peggiore


def _speso_dal_padre() -> float:
    ""
    try:
        return max(float(os.environ.get(ENV_RETE_SPESO) or 0), 0.0)
    except ValueError:
        return 0.0


def _leggi_conto(conto: Path) -> float:
    ""
    try:
        return max(float(json.loads(conto.read_text(encoding="utf-8")).get("speso_s") or 0), 0.0)
    except (OSError, ValueError, AttributeError, TypeError):
        log.warning("the workspace did not write how long it waited for the network: counting 0 s")
        return 0.0


def _scrivi_conto() -> None:
    ""
    conto = os.environ.get(ENV_RETE_CONTO)
    if not conto:
        return
    try:
        Path(conto).write_text(json.dumps({"speso_s": round(_rete["speso"], 1)}), encoding="utf-8")
    except OSError as e:
        log.warning("network count not written (%s)", e)


def main():
    try:
        _main()
    finally:
        _scrivi_conto()


def _main():
    parser = argparse.ArgumentParser(description="SBK ClickUp Workspace Backup")
    parser.add_argument(
        "--incremental", action="store_true", help="Only backup changed tasks since last run"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be backed up (no writes)"
    )
    parser.add_argument(
        "--spaces",
        type=str,
        default=None,
        help="Comma-separated space IDs to backup (default: all)",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Parallel workers for space processing (default: 4)"
    )
    parser.add_argument("--skip-docs", action="store_true", help="Skip docs backup (faster)")
    parser.add_argument("--skip-time", action="store_true", help="Skip bulk time entries backup")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug-level logging")
    parser.add_argument(
        "--team",
        default="all",
        help="Workspace to download: an id (clickup.teams in sbk.config.json, or any the token "
        "sees) or 'all' (default)",
    )
    parser.add_argument(
        "--backfill-old",
        action="store_true",
        dest="completa_vecchi",
        help="one-off pass for tasks saved by older versions that miss comments or replies "
        "and that the current run no longer lists",
    )
    # Older Italian name, kept as a hidden alias.
    parser.add_argument(
        "--completa-vecchi", action="store_true", dest="completa_vecchi", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    _richiedi_token()

    if not os.environ.get("SBK_CLICKUP_TEAM"):  # unset or empty (an empty line in .env)
        sys.exit(_tutti_i_team(args.team))

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)


    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    if args.completa_vecchi:

        conti = completa_i_vecchi(args.dry_run)
        print(json.dumps({"workspace": TEAMS[TEAM_ID][0], **conti}, ensure_ascii=False))
        sys.exit(1 if conti["errori"] else 0)

    stats["start_time"] = datetime.now(UTC).isoformat()
    stats["mode"] = "incremental" if args.incremental else "full"
    start = time.time()

    log.info("ClickUp backup starting (mode=%s, workers=%d)", stats["mode"], args.workers)


    space_filter = None
    if args.spaces:
        space_filter = set(args.spaces.split(","))
        log.info("Space filter: %s", space_filter)


    edit_tracker = tracker_di_partenza(args.incremental, space_filter)
    carica_da_rifare()
    _rete["speso_prima"] = _speso_dal_padre()
    if _rete["speso_prima"]:
        log.info(
            "Network: %d s already spent without network by the previous workspaces, the run cap is %d s",
            _rete["speso_prima"],
            RETE_TETTO_S,
        )


    if not args.dry_run:
        backup_members()


    spaces = backup_spaces(space_filter)
    if not spaces and _rete_persa.is_set():

        _chiudi_senza_rete(set(), args.dry_run)
        sys.exit(1)
    if not spaces:
        log.error("No spaces found. Check API key and team ID.")
        sys.exit(1)

    prima = space_da_rifare_prima()
    spaces = sorted(spaces, key=lambda s: s["id"] not in prima)




    space_summaries = []

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_space, space, edit_tracker, args.incremental, args.dry_run
                ): space
                for space in spaces
            }
            for future in as_completed(futures):
                space = futures[future]
                try:
                    summary = future.result()
                    space_summaries.append(summary)
                except Exception as e:
                    sname = space.get("name", space.get("id", "?"))
                    log.error("Error processing space %s: %s", sname, e)
                    _add_error(f"SPACE_ERROR: {sname}: {e}")
                    _segna_da_rifare("spaces", space["id"], space["id"])
    else:
        for space in spaces:
            try:
                summary = process_space(space, edit_tracker, args.incremental, args.dry_run)
                space_summaries.append(summary)
            except Exception as e:
                sname = space.get("name", space.get("id", "?"))
                log.error("Error processing space %s: %s", sname, e)
                _add_error(f"SPACE_ERROR: {sname}: {e}")
                _segna_da_rifare("spaces", space["id"], space["id"])


    if not args.skip_docs and not args.dry_run and not _rete_persa.is_set():
        backup_docs()


    if not args.skip_time and not args.dry_run and not _rete_persa.is_set():
        backup_bulk_time_entries()


    elapsed = time.time() - start
    stats["end_time"] = datetime.now(UTC).isoformat()
    stats["duration_secs"] = round(elapsed, 1)

    if not args.dry_run:
        save_edit_tracker(edit_tracker, force=True)
        _chiudi_senza_rete({s["id"] for s in spaces}, args.dry_run)
        save_manifest()
        append_run_history()



        if stats["errors"]:
            log.warning("last-run mark not written: there are errors")
        else:
            try:
                mark_last_run("clickup")
            except Exception as e:
                log.warning("mark_last_run failed: %s", e)

    print_summary()

    backup_mb = get_backup_size_mb()
    log.info("Backup size: %.1f MB at %s", backup_mb, BACKUP_DIR)


    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
