#!/usr/bin/env python3
"""Google Drive download: the files of each signed-in account (recently modified, all yours, shared with you, shared
drives, or shared with one person), Google documents exported to text formats, media only on request, with an
index.
"""

import argparse
import io
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from secrets_adapter import get_secret

from sbk_config import (
    DATA_ROOT,
    EMAILS_DIR,
    mark_last_run,
    user_cfg,
)

DATA_DIR = DATA_ROOT / "gdrive"
INDEX_FILE = DATA_DIR / "gdrive-index.json"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


EXPORT_MAP = {
    "application/vnd.google-apps.document": {
        "ext": ".md",
        "mime": "text/plain",
        "label": "Google Doc",
    },


    "application/vnd.google-apps.spreadsheet": {
        "ext": ".xlsx",
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "label": "Google Sheet",
    },
    "application/vnd.google-apps.presentation": {
        "ext": ".txt",
        "mime": "text/plain",
        "label": "Google Slides",
    },
}


SKIP_MIMES = {
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.script",
    "application/vnd.google-apps.foldershortcut",
    "application/vnd.google-apps.shortcut",
}


MAX_FILE_SIZE = 15 * 1024 * 1024

log = logging.getLogger("gdrive-dl")





def get_known_accounts() -> dict[str, str]:
    ""
    accounts_file = EMAILS_DIR / "accounts.json"
    if accounts_file.exists():
        data = json.loads(accounts_file.read_text())
        return {name: acc.get("email", "") for name, acc in data.items()}
    return {}





_FILE_FATTI: set[str] = set()
_DRIVE_FATTE: set[str] = set()
_PATH_CACHE: dict[str, str] = {}
_INDICE_PRIMA: dict[str, dict] = {}





_CARTELLA = "application/vnd.google-apps.folder"







# default: photo/video folders only; extend from user config if needed
_CARTELLE_VISIVE = (
    "foto",
    "photos",
    "video",
    "videos",
)

# Accounts/drives treated as a "group": visual-material folders are skipped for them.
# Defaults are empty; load the account prefixes and shared-drive names from user config.
_PREFISSI_GRUPPO: tuple[str, ...] = ()
_SPAZI_GRUPPO: tuple[str, ...] = ()


def _cartella_visiva(nome: str) -> bool:
    ""
    pulito = re.sub(r"[_\-\s]+", " ", re.sub(r"^[\d\s._-]+", "", nome.lower())).strip()
    return any(pulito == p or pulito.startswith(p + " ") for p in _CARTELLE_VISIVE)


def _di_gruppo(account_name: str, batch_name: str) -> bool:
    ""
    return any(account_name.startswith(p) for p in _PREFISSI_GRUPPO) or any(
        batch_name.endswith(f"-sd-{nome}") for nome in _SPAZI_GRUPPO
    )


def _carica_indice_prima() -> None:
    ""
    if _INDICE_PRIMA or not INDEX_FILE.exists():
        return
    try:
        for m in json.loads(INDEX_FILE.read_text()):
            if isinstance(m, dict) and m.get("id"):
                _INDICE_PRIMA[m["id"]] = m
    except Exception as e:  # noqa: BLE001
        log.warning(f"Previous index unreadable, re-downloading everything: {e}")


def _filtro_data(days: int) -> str:
    ""
    if days <= 0:
        return ""
    since = datetime.now(UTC) - timedelta(days=days)
    return f"modifiedTime > '{since.strftime('%Y-%m-%dT%H:%M:%S')}' and "


def get_credentials(account_name: str) -> Credentials:
    ""
    raw = get_secret("sbk-gdrive", account_name)


    if not raw and account_name != "default":
        raw = get_secret("sbk-gdrive", "default")
        if raw:

            data = json.loads(raw)
            default_email = data.get("email", "")
            known = get_known_accounts()
            expected_email = known.get(account_name, "")
            if default_email and expected_email and default_email != expected_email:
                raw = None

    if not raw:
        log.warning(
            f"No Drive credentials for '{account_name}'. "
            f"Run: uv run python tools/gdrive/gd-l0-auth.py --account {account_name}"
        )
        return None

    data = json.loads(raw)
    return Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def build_service(account_name: str, email: str = ""):
    # Every account signs in with its own browser login (Keychain sbk-gdrive/<label>).
    creds = get_credentials(account_name)
    if not creds:
        return None
    return build("drive", "v3", credentials=creds)





def _con_ritentativi(chiamata, attese=(5, 15, 45, 90, 180)):
    ""




    for i, attesa in enumerate((*attese, None)):
        try:
            return chiamata()
        except HttpError as e:
            stato = getattr(getattr(e, "resp", None), "status", 0)
            if attesa is None or not (stato == 429 or 500 <= int(stato or 0) < 600):
                raise
            log.warning(f"  Google answered {stato}, retrying in {attesa} s (attempt {i + 2})")
            time.sleep(attesa)



_DRIVE_FALLITE: list[str] = []


def list_files(service, query: str, page_size: int = 100, drive_id: str | None = None) -> list:
    ""




    files = []
    page_token = None

    fields = (
        "nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, "
        "owners, sharingUser, shared, parents, webViewLink, trashed, driveId)"
    )

    while True:
        params = {
            "q": query,
            "pageSize": page_size,
            "fields": fields,
            "orderBy": "modifiedTime desc",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            params["driveId"] = drive_id
            params["corpora"] = "drive"
        if page_token:
            params["pageToken"] = page_token

        resp = _con_ritentativi(lambda: service.files().list(**params).execute())
        batch = resp.get("files", [])
        files.extend(batch)
        log.info(f"  Listed {len(files)} files so far...")

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files


def list_shared_drives(service) -> list[dict]:
    ""
    drives = []
    page_token = None
    while True:
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        resp = service.drives().list(**params).execute()
        drives.extend(resp.get("drives", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return drives



PERCORSO_V = 2


def _mappa_cartelle(files: list) -> dict[str, tuple[str, str | None]]:
    ""
    return {
        f["id"]: (f.get("name", f["id"]), (f.get("parents") or [None])[0])
        for f in files
        if f.get("mimeType") == _CARTELLA
    }


def get_file_path(
    service, file_meta: dict, _cache: dict | None = None, cartelle: dict | None = None
) -> str:
    ""






    if _cache is None:
        _cache = {}
    cartelle = cartelle or {}
    parents = file_meta.get("parents", [])
    if not parents:
        return ""

    drive_id = file_meta.get("driveId")
    salita: list[tuple[str, str]] = []
    base = ""
    current = parents[0]

    while current and len(salita) < 10:
        if current in _cache:
            base = _cache[current]
            break
        if current == drive_id:
            try:
                base = (
                    service.drives().get(driveId=drive_id, fields="name").execute().get("name", "")
                )
            except HttpError:
                base = ""
            _cache[current] = base
            break
        if current in cartelle:
            nome, madre = cartelle[current]
        else:
            try:
                parent = (
                    service.files()
                    .get(fileId=current, fields="name, parents", supportsAllDrives=True)
                    .execute()
                )
            except HttpError:
                break
            nome, madre = parent.get("name", current), (parent.get("parents") or [None])[0]
        salita.append((current, nome))
        current = madre

    for fid, nome in reversed(salita):
        base = f"{base}/{nome}" if base else nome
        _cache[fid] = base
    return base


def download_file(
    service, file_meta: dict, output_dir: Path, *, include_media: bool = False, max_size: int = 0
) -> dict:
    ""
    file_id = file_meta["id"]
    name = file_meta["name"]
    mime = file_meta.get("mimeType", "")
    size = int(file_meta.get("size", 0))
    effective_max = max_size if max_size > 0 else MAX_FILE_SIZE

    result = {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "size": size,
        "createdTime": file_meta.get("createdTime", ""),
        "modifiedTime": file_meta.get("modifiedTime", ""),
        "owners": [o.get("emailAddress", "") for o in file_meta.get("owners", [])],
        "webViewLink": file_meta.get("webViewLink", ""),
        "downloaded": False,
        "export_format": None,
        "local_path": None,
    }


    if file_meta.get("trashed"):
        result["skip_reason"] = "trashed"
        return result


    if mime == "application/vnd.google-apps.folder":
        result["skip_reason"] = "folder"
        return result


    if mime in SKIP_MIMES:
        result["skip_reason"] = f"skipped_mime: {mime}"
        return result


    if size > effective_max:
        result["skip_reason"] = f"too_large: {size / 1024 / 1024:.0f}MB"
        return result



    safe_name = "".join(c if c.isalnum() or c in ".-_ " else "_" for c in name)
    stem, dot, ext_orig = safe_name.rpartition(".")
    if dot and 0 < len(ext_orig) <= 5 and mime not in EXPORT_MAP:
        safe_name = f"{stem}__{file_id[:10]}.{ext_orig}"
    else:
        safe_name = f"{safe_name}__{file_id[:10]}"

    if mime in EXPORT_MAP:

        export_info = EXPORT_MAP[mime]
        ext = export_info["ext"]
        export_mime = export_info["mime"]

        if not safe_name.endswith(ext):
            safe_name += ext

        out_path = output_dir / safe_name
        result["export_format"] = export_info["label"]

        for attempt in range(3):
            try:
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                content = request.execute()

                if isinstance(content, bytes):
                    out_path.write_bytes(content)
                else:
                    out_path.write_text(content)

                result["downloaded"] = True
                result["local_path"] = str(out_path)
                result["size"] = out_path.stat().st_size
                break
            except HttpError as e:
                if "fileNotExportable" in str(e) or "exportSizeLimitExceeded" in str(e):
                    result["skip_reason"] = f"export_failed: {e.resp.status}"
                    break
                else:
                    result["skip_reason"] = f"error: {e.resp.status}"
                    log.warning(f"Export failed for {name}: {e}")
            except Exception as e:
                if attempt < 2:
                    log.warning(f"Retry {attempt + 1}/3 for {name}: {e}")
                    time.sleep(2**attempt)
                else:
                    result["skip_reason"] = f"timeout_after_retries: {type(e).__name__}"
                    log.warning(f"Giving up on {name} after 3 attempts: {e}")

    elif mime.startswith(("image/", "video/", "audio/")) and not include_media:

        result["skip_reason"] = f"media: {mime}"

    else:

        out_path = output_dir / safe_name
        for attempt in range(3):
            try:
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

                out_path.write_bytes(fh.getvalue())
                result["downloaded"] = True
                result["local_path"] = str(out_path)
                result["size"] = out_path.stat().st_size
                break
            except HttpError as e:
                result["skip_reason"] = f"download_error: {e.resp.status}"
                log.warning(f"Download failed for {name}: {e}")
                break
            except Exception as e:
                if attempt < 2:
                    log.warning(f"Retry {attempt + 1}/3 for {name}: {e}")
                    time.sleep(2**attempt)
                else:
                    result["skip_reason"] = f"timeout_after_retries: {type(e).__name__}"
                    log.warning(f"Giving up on {name} after 3 attempts: {e}")

    return result





def run_recent(service, days: int, dry_run: bool, account_name: str, **dl_opts):
    ""
    query = f"{_filtro_data(days)}trashed = false"

    log.info(f"[{account_name}] Searching files modified in last {days or 'ALL'} days...")
    files = list_files(service, query)
    log.info(f"[{account_name}] Found {len(files)} files")

    if dry_run:
        for f in files[:50]:
            log.info(
                f"  {f['name']} ({f.get('mimeType', '?')}) modified {f.get('modifiedTime', '?')[:10]}"
            )
        return

    output_dir = DATA_DIR / account_name / "recent"
    output_dir.mkdir(parents=True, exist_ok=True)
    _download_batch(service, files, output_dir, f"{account_name}-recent", account_name, **dl_opts)


def run_shared(service, shared_with: str, dry_run: bool, account_name: str, **dl_opts):
    ""
    query = f"'{shared_with}' in owners and trashed = false"

    log.info(f"[{account_name}] Searching files owned by {shared_with}...")

    try:
        files = list_files(service, query)
    except HttpError:
        log.info("Owner query failed, falling back to sharedWithMe...")
        query = "trashed = false and sharedWithMe = true"
        files = list_files(service, query)

    log.info(f"[{account_name}] Found {len(files)} files")

    if dry_run:
        for f in files[:50]:
            owners = ", ".join(o.get("emailAddress", "?") for o in f.get("owners", []))
            log.info(f"  {f['name']} (owner: {owners}) modified {f.get('modifiedTime', '?')[:10]}")
        return

    output_dir = DATA_DIR / account_name / "shared"
    output_dir.mkdir(parents=True, exist_ok=True)
    _download_batch(service, files, output_dir, f"{account_name}-shared", account_name, **dl_opts)


def run_all_mine(service, dry_run: bool, account_name: str, **dl_opts):
    ""
    query = "'me' in owners and trashed = false"

    log.info(f"[{account_name}] Searching all files owned by me...")
    files = list_files(service, query)
    log.info(f"[{account_name}] Found {len(files)} files")

    if dry_run:
        for f in files[:50]:
            log.info(
                f"  {f['name']} ({f.get('mimeType', '?')}) modified {f.get('modifiedTime', '?')[:10]}"
            )
        return

    output_dir = DATA_DIR / account_name / "owned"
    output_dir.mkdir(parents=True, exist_ok=True)
    _download_batch(service, files, output_dir, f"{account_name}-owned", account_name, **dl_opts)





def _large_shared_drives() -> frozenset[str]:
    """Shared drives with heavier files: sbk.config.json gdrive.large_shared_drives (exact names)."""
    nomi = user_cfg("gdrive.large_shared_drives", [])
    if isinstance(nomi, str):
        nomi = [nomi]
    return frozenset(str(n).strip() for n in (nomi or []) if str(n).strip())


# Their files may be up to --max-size-mb-large MB; empty list = the option has no effect.
DRIVE_PIU_GRANDI: frozenset[str] = _large_shared_drives()
MAX_GRANDI_B = 0


def run_shared_drives(service, days: int, dry_run: bool, account_name: str, **dl_opts):
    ""
    drives = list_shared_drives(service)
    if not drives:
        log.info(f"[{account_name}] No Shared Drives found")
        return

    log.info(f"[{account_name}] Found {len(drives)} Shared Drives")

    for drive in drives:
        drive_name = drive["name"]
        drive_id = drive["id"]
        safe_drive_name = "".join(c if c.isalnum() or c in ".-_ " else "_" for c in drive_name)
        if drive_id in _DRIVE_FATTE:
            log.info(f"\n  --- Shared Drive: {drive_name} --- already done by another account")
            continue
        if not dry_run:
            _DRIVE_FATTE.add(drive_id)

        query = f"{_filtro_data(days)}trashed = false"

        log.info(f"\n  --- Shared Drive: {drive_name} ---")
        try:
            files = list_files(service, query, drive_id=drive_id)
        except HttpError as e:
            log.error(f"  Cannot access {drive_name}: {e}")

            _DRIVE_FATTE.discard(drive_id)
            _DRIVE_FALLITE.append(drive_name)
            continue

        log.info(f"  [{drive_name}] {len(files)} files modified in last {days or 'ALL'} days")

        if dry_run:
            for f in files[:10]:
                log.info(
                    f"    {f['name']} ({f.get('mimeType', '?')}) "
                    f"modified {f.get('modifiedTime', '?')[:10]}"
                )
            continue

        if not files:
            continue

        output_dir = DATA_DIR / account_name / "shared-drives" / safe_drive_name
        output_dir.mkdir(parents=True, exist_ok=True)
        _PATH_CACHE.setdefault(drive_id, drive_name)
        opzioni = dl_opts
        if drive_name in DRIVE_PIU_GRANDI and MAX_GRANDI_B:
            opzioni = {**dl_opts, "max_size": MAX_GRANDI_B}
        _download_batch(
            service,
            files,
            output_dir,
            f"{account_name}-sd-{safe_drive_name}",
            account_name,
            **opzioni,
        )


def run_shared_with_me(service, days: int, dry_run: bool, account_name: str, **dl_opts):
    ""
    query = f"sharedWithMe = true and {_filtro_data(days)}trashed = false"

    log.info(f"[{account_name}] Searching files shared with me (last {days or 'ALL'} days)...")
    files = list_files(service, query)
    log.info(f"[{account_name}] Found {len(files)} shared files")

    if dry_run:
        for f in files[:50]:
            owners = ", ".join(o.get("emailAddress", "?") for o in f.get("owners", []))
            log.info(f"  {f['name']} (from: {owners}) modified {f.get('modifiedTime', '?')[:10]}")
        return

    output_dir = DATA_DIR / account_name / "shared-with-me"
    output_dir.mkdir(parents=True, exist_ok=True)
    _download_batch(
        service, files, output_dir, f"{account_name}-shared-with-me", account_name, **dl_opts
    )


def _salva_indici(index: list, index_path: Path) -> None:
    ""






    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2, default=str))
    tmp.rename(index_path)

    master = []
    if INDEX_FILE.exists():
        try:
            master = json.loads(INDEX_FILE.read_text())
        except Exception:
            pass
    posizione = {m["id"]: j for j, m in enumerate(master) if isinstance(m, dict) and m.get("id")}
    for item in index:
        j = posizione.get(item["id"])
        if j is None:
            master.append(item)
            posizione[item["id"]] = len(master) - 1
        else:
            master[j] = item
    tmp = INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(master, indent=2, default=str))
    tmp.rename(INDEX_FILE)
    log.info(f"Master index: {len(master)} total files tracked")


def _download_batch(
    service,
    files: list,
    output_dir: Path,
    batch_name: str,
    account_name: str,
    *,
    include_media: bool = False,
    max_size: int = 0,
):
    ""
    index = []
    total = len(files)
    downloaded = 0
    skipped = 0

    account_dir = DATA_DIR / account_name
    index_path = account_dir / f"index-{batch_name}.json"
    ultimo_salvataggio = time.monotonic()

    invariati = 0
    gia_fatti = 0
    cartelle = _mappa_cartelle(files)
    gruppo = _di_gruppo(account_name, batch_name)
    visivi_gruppo = 0
    for i, f in enumerate(files):
        name = f["name"]

        if i % 50 == 0:
            log.info(
                f"[{i}/{total}] Processing... ({downloaded} downloaded, "
                f"{invariati} unchanged, {skipped} skipped)"
            )

        if f["id"] in _FILE_FATTI:
            gia_fatti += 1
            continue
        _FILE_FATTI.add(f["id"])

        prima = _INDICE_PRIMA.get(f["id"])
        if (
            prima
            and prima.get("downloaded")
            and prima.get("modifiedTime") == f.get("modifiedTime")
            and prima.get("local_path")
            and Path(prima["local_path"]).exists()
        ):
            if prima.get("folder_path_v") != PERCORSO_V:

                try:
                    prima["folder_path"] = get_file_path(service, f, _PATH_CACHE, cartelle)
                    prima["folder_path_v"] = PERCORSO_V
                except Exception:  # noqa: BLE001
                    pass
            index.append(prima)
            invariati += 1
            continue

        if gruppo and f.get("mimeType") != _CARTELLA:
            percorso = get_file_path(service, f, _PATH_CACHE, cartelle)
            if any(_cartella_visiva(parte) for parte in percorso.split("/")):
                visivi_gruppo += 1
                continue

        result = download_file(
            service, f, output_dir, include_media=include_media, max_size=max_size
        )



        try:
            result["folder_path"] = get_file_path(service, f, _PATH_CACHE, cartelle)
            result["folder_path_v"] = PERCORSO_V
        except Exception:
            result["folder_path"] = ""

        result["account"] = account_name
        index.append(result)

        if result["downloaded"]:
            downloaded += 1
            log.info(f"  OK: {name}")
        else:
            skipped += 1





        if time.monotonic() - ultimo_salvataggio >= 60:
            _salva_indici(index, index_path)
            ultimo_salvataggio = time.monotonic()

    _salva_indici(index, index_path)
    log.info(
        f"\n[{account_name}] Done: {downloaded} downloaded, {invariati} unchanged, "
        f"{skipped} skipped, {gia_fatti} already seen by another account"
    )
    if visivi_gruppo:
        log.info(
            f"[{account_name}] {visivi_gruppo} group visual-material files not downloaded "
            "(photo/video folders)"
        )
    log.info(f"Index saved: {index_path}")





def main():
    parser = argparse.ArgumentParser(description="Google Drive downloader — SBK")
    parser.add_argument(
        "--account",
        help="Label of one account (e.g. work). Omit to run every account in emails/accounts.json.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "recent",
            "shared",
            "all-mine",
            "shared-drives",
            "shared-with-me",
            "full-sync",
        ],
        help="Download mode. 'full-sync' runs shared-drives + shared-with-me + recent.",
    )
    parser.add_argument(
        "--days", type=int, default=14, help="Days back for recent modes (0 = full history)"
    )
    parser.add_argument("--shared-with", help="Email for 'shared' mode")
    parser.add_argument("--dry-run", action="store_true", help="List files only")
    parser.add_argument(
        "--include-media", action="store_true", help="Download media files (images/video/audio)"
    )
    parser.add_argument(
        "--max-size-mb", type=int, default=0, help="Max file size in MB (0 = default 15MB)"
    )
    parser.add_argument(
        "--max-size-mb-large",
        type=int,
        default=0,
        dest="max_size_mb_grandi",
        metavar="MB",
        help="size limit in MB for the shared drives listed in sbk.config.json "
        "gdrive.large_shared_drives (0 = same as the others)",
    )
    # Older Italian name, kept as a hidden alias.
    parser.add_argument("--max-size-mb-grandi", type=int, dest="max_size_mb_grandi", help=argparse.SUPPRESS)
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(DATA_DIR / "download.log"),
        ],
    )



    known = get_known_accounts()
    accounts = [args.account] if args.account else list(known)
    if not accounts:
        log.error("No account in emails/accounts.json")
        sys.exit(1)
    _carica_indice_prima()
    falliti: list[str] = []

    for account_name in accounts:
        log.info(f"\n{'=' * 60}")
        log.info(f"Account: {account_name}")
        log.info(f"{'=' * 60}")

        atteso = known.get(account_name, "")
        service = build_service(account_name, atteso)
        if not service:
            log.error(f"{account_name}: no credentials")
            falliti.append(account_name)
            continue


        try:
            about = service.about().get(fields="user, storageQuota").execute()
            email = about["user"]["emailAddress"]
            log.info(f"Connected: {email}")
        except Exception as e:
            log.error(f"Connection failed for {account_name}: {e}")
            falliti.append(account_name)
            continue
        if atteso and email.lower() != atteso.lower():
            log.error(f"{account_name}: service belongs to {email}, expected {atteso}: skipped")
            falliti.append(account_name)
            continue

        dl_opts = {
            "include_media": args.include_media,
            "max_size": args.max_size_mb * 1024 * 1024 if args.max_size_mb else 0,
        }
        global MAX_GRANDI_B
        MAX_GRANDI_B = args.max_size_mb_grandi * 1024 * 1024

        if args.mode == "full-sync":
            run_shared_drives(service, args.days, args.dry_run, account_name, **dl_opts)
            run_shared_with_me(service, args.days, args.dry_run, account_name, **dl_opts)
            run_recent(service, args.days, args.dry_run, account_name, **dl_opts)
        elif args.mode == "recent":
            run_recent(service, args.days, args.dry_run, account_name, **dl_opts)
        elif args.mode == "shared":
            if not args.shared_with:
                print("--shared-with required for 'shared' mode")
                return
            run_shared(service, args.shared_with, args.dry_run, account_name, **dl_opts)
        elif args.mode == "all-mine":
            run_all_mine(service, args.dry_run, account_name, **dl_opts)
        elif args.mode == "shared-drives":
            run_shared_drives(service, args.days, args.dry_run, account_name, **dl_opts)
        elif args.mode == "shared-with-me":
            run_shared_with_me(service, args.days, args.dry_run, account_name, **dl_opts)

    if _DRIVE_FALLITE:
        log.error(
            f"Shared Drives not read (will resume on the next run): {', '.join(_DRIVE_FALLITE)}"
        )
    if falliti or _DRIVE_FALLITE:
        log.error(f"Accounts with errors (not marked): {', '.join(falliti) or '-'}")
        sys.exit(1)
    if not args.dry_run:
        mark_last_run("gdrive")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-gdrive-download", source="gdrive", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
