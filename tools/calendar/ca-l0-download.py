#!/usr/bin/env python3
""
























import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from secrets_adapter import get_secret, set_secret  # noqa: E402

from sbk_config import (  # noqa: E402
    CALENDARS_DIR,
    acquire_pid_lock,
    mark_last_run,
    safe_write_parquet,
)

PROJECT_ROOT = _TOOLS_DIR.parent
RAW_CALENDAR_DIR = PROJECT_ROOT / "sbk" / "raw" / "calendar"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

import google_oauth  # noqa: E402

# Your own OAuth client (Desktop app): GOOGLE_OAUTH_CLIENT_SECRET_PATH or
# ~/.secrets/google-oauth/client_secret.json (tools/google_oauth.py).
CLIENT_SECRET = google_oauth.client_file()


from sbk_config import EMAILS_DIR  # noqa: E402

GMAIL_ACCOUNTS_FILE = EMAILS_DIR / "accounts.json"

log = logging.getLogger("ca-l0-download")


class SenzaLogin(Exception):
    ""


def get_calendar_service(account_name: str, email: str = "", senza_login: bool = False):
    ""





    # Every mailbox signs in with its own browser login (Keychain sbk-gcal/<label>).
    refresh_token = get_secret("sbk-gcal", account_name)

    if not refresh_token:
        if senza_login:
            raise SenzaLogin(account_name)
        log.info(f"No calendar token for '{account_name}'. Starting OAuth flow...")
        return _auth_and_build(account_name)

    client_id, client_secret = google_oauth.client_id_secret()

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=google_oauth.TOKEN_URI,
        scopes=SCOPES,
    )
    return build("calendar", "v3", credentials=creds)


def _auth_and_build(account_name: str):
    ""
    if not CLIENT_SECRET.exists():
        log.error(
            f"OAuth client file not found: {CLIENT_SECRET}. Download your Desktop-app client JSON "
            "there or set GOOGLE_OAUTH_CLIENT_SECRET_PATH (docs/CONNECTING.md#google)."
        )
        sys.exit(1)

    print(f"\nAuthorizing calendar access for '{account_name}'...")
    print("Select the correct Google account in the browser.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")


    set_secret("sbk-gcal", account_name, creds.refresh_token)
    log.info(f"Calendar token stored for '{account_name}'")

    return build("calendar", "v3", credentials=creds)


def list_calendars(service) -> list[dict]:
    ""
    calendars = []
    page_token = None
    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        calendars.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return calendars


def download_events(
    service,
    calendar_id: str,
    calendar_name: str,
    since: str | None = None,
    updated_min: str | None = None,
) -> list[dict]:
    ""






    events = []
    page_token = None
    params = {
        "calendarId": calendar_id,
        "maxResults": 2500,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if updated_min:


        params["updatedMin"] = updated_min
        params["orderBy"] = "updated"
    elif since:
        params["timeMin"] = f"{since}T00:00:00Z"

    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = service.events().list(**params).execute()

        for ev in resp.get("items", []):
            ev["calendarName"] = calendar_name
            ev["calendarId"] = calendar_id
            events.append(ev)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return events


class TokenScaduto(Exception):
    ""


def scarica_sync(
    service, calendar_id: str, calendar_name: str, sync_token: str | None = None
) -> tuple[list[dict], str | None]:
    ""







    from googleapiclient.errors import HttpError

    eventi: list[dict] = []
    params: dict = {"calendarId": calendar_id, "maxResults": 2500, "singleEvents": True}
    if sync_token:
        params["syncToken"] = sync_token
    while True:
        try:
            resp = service.events().list(**params).execute()
        except HttpError as e:
            if int(getattr(e.resp, "status", 0) or 0) == 410:
                raise TokenScaduto(calendar_id) from e
            raise
        for ev in resp.get("items", []):
            ev["calendarName"] = calendar_name
            ev["calendarId"] = calendar_id
            eventi.append(ev)
        if resp.get("nextPageToken"):
            params["pageToken"] = resp["nextPageToken"]
            continue
        return eventi, resp.get("nextSyncToken")


def leggi_token(cartella: Path) -> dict[str, str]:
    ""
    try:
        d = json.loads((cartella / "sync-tokens.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def scrivi_token(cartella: Path, tokens: dict[str, str]) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    tmp = cartella / "sync-tokens.json.tmp"
    tmp.write_text(json.dumps(tokens, indent=1), encoding="utf-8")
    os.replace(tmp, cartella / "sync-tokens.json")
    os.chmod(cartella / "sync-tokens.json", 0o600)


def _riga_evento(ev: dict) -> dict:
    ""






    start = ev.get("start", {})
    end = ev.get("end", {})

    start_dt = start.get("dateTime") or start.get("date", "")
    end_dt = end.get("dateTime") or end.get("date", "")

    attendees_raw = ev.get("attendees", [])
    attendee_records = []
    if isinstance(attendees_raw, list):
        for a in attendees_raw:
            if isinstance(a, dict):
                email = a.get("email", "")
                if email:
                    attendee_records.append({"email": email, "status": a.get("responseStatus", "")})
            elif isinstance(a, str):
                attendee_records.append({"email": a, "status": ""})

    organizer = ev.get("organizer", {})
    organizer_email = ""
    if isinstance(organizer, dict):
        organizer_email = organizer.get("email", "")
    elif isinstance(organizer, str):
        organizer_email = organizer


    self_status = ""
    if isinstance(attendees_raw, list):
        for a in attendees_raw:
            if isinstance(a, dict) and a.get("self"):
                self_status = a.get("responseStatus", "") or ""
                break


    conference_url = ""
    conf_data = ev.get("conferenceData", {})
    if conf_data:
        entry_points = conf_data.get("entryPoints", [])
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                conference_url = ep.get("uri", "")
                break
        if not conference_url and entry_points:
            conference_url = entry_points[0].get("uri", "")

    return {
        "id": ev.get("id", ""),
        "summary": ev.get("summary", ""),
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "start_timezone": start.get("timeZone", ""),
        "location": ev.get("location", ""),

        "description": ev.get("description", "") or "",
        "organizer_email": organizer_email,
        "attendees": json.dumps(attendee_records),
        "attendee_count": len(attendee_records),
        "status": ev.get("status", ""),
        "calendar_name": ev.get("calendarName", ""),
        "calendar_id": ev.get("calendarId", ""),
        "conference_url": conference_url,


        "event_type": ev.get("eventType", "") or "",
        "transparency": ev.get("transparency", "") or "",
        "color_id": str(ev.get("colorId", "") or ""),
        "html_link": ev.get("htmlLink", "") or "",
        "recurring_event_id": ev.get("recurringEventId", "") or "",
        "visibility": ev.get("visibility", "") or "",
        "end_timezone": end.get("timeZone", "") or "",
        "updated": ev.get("updated", "") or "",
        "self_status": self_status,
        "organizer_self": "1" if isinstance(organizer, dict) and organizer.get("self") else "",
    }


def events_to_parquet(events: list[dict], output_path: Path):
    ""
    rows = []
    for ev in events:
        rows.append(_riga_evento(ev))

    df = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(df, output_path, index=False)
    return df


def events_to_json(events: list[dict], output_path: Path):
    ""

    clean_events = []
    for ev in events:
        clean = {
            "id": ev.get("id", ""),
            "summary": ev.get("summary", ""),
            "start": ev.get("start", {}),
            "end": ev.get("end", {}),
            "organizer": ev.get("organizer", ""),
            "attendees": ev.get("attendees", []),
            "calendarName": ev.get("calendarName", ""),
        }
        if ev.get("location"):
            clean["location"] = ev["location"]
        if ev.get("description"):
            clean["description"] = ev["description"][:500]
        clean_events.append(clean)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(clean_events, indent=2, ensure_ascii=False))


def merge_events_incremental(
    existing_path: Path, new_events: list[dict], output_path: Path
) -> pd.DataFrame:
    ""








    new_rows = [_riga_evento(ev) for ev in new_events]

    new_df = pd.DataFrame(new_rows) if new_rows else pd.DataFrame()


    if existing_path.exists():
        existing_df = pd.read_parquet(existing_path)
    else:
        existing_df = pd.DataFrame()

    if new_df.empty:




        return existing_df
    if existing_df.empty:
        merged = new_df
    else:

        updated_ids = set(new_df["id"])
        kept = existing_df[~existing_df["id"].isin(updated_ids)]
        merged = pd.concat([kept, new_df], ignore_index=True)


    if not merged.empty and "status" in merged.columns:
        cancellati = merged[merged["status"] == "cancelled"]
        if len(cancellati) > 0:
            log.info(f"{len(cancellati)} cancelled events set aside in cancellati.parquet")
            _metti_da_parte(output_path.parent / "cancellati.parquet", cancellati)
            merged = merged[merged["status"] != "cancelled"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(merged, output_path, index=False)
    return merged


def _metti_da_parte(percorso: Path, cancellati: pd.DataFrame) -> None:
    ""
    if percorso.exists():
        vecchi = pd.read_parquet(percorso)
        cancellati = pd.concat([vecchi[~vecchi["id"].isin(set(cancellati["id"]))], cancellati])
    safe_write_parquet(cancellati.reset_index(drop=True), percorso, index=False)


def get_known_accounts() -> dict[str, str]:
    ""


    if GMAIL_ACCOUNTS_FILE.exists():
        data = json.loads(GMAIL_ACCOUNTS_FILE.read_text())
        return {name: acc.get("email", "") for name, acc in data.items() if acc.get("email")}
    return {}


SKIP_CALENDARI = ("holiday@", "birthday@", "#contacts@", "#weather@")



SKIP_NOMI_CALENDARI = ("Compleanni", "Onomastici")


def _calendari_della_pipeline() -> set[str]:
    from sbk_config import KNOWLEDGE_META_DIR

    try:
        reg = json.loads((KNOWLEDGE_META_DIR / "ricorrenze-calendario.json").read_text())
        return set(reg.get("calendari", {}).values())
    except (OSError, ValueError):
        return set()


def _da_saltare(c: dict, nostri: set[str]) -> bool:
    cid = c.get("id", "")
    return (
        any(p in cid for p in SKIP_CALENDARI)
        or cid in nostri
        or c.get("summary") in SKIP_NOMI_CALENDARI
    )


def assegna_calendari(
    servizi: dict[str, object], liste: dict[str, list[dict]] | None = None
) -> dict[str, list[str]]:
    ""









    visti: dict[str, list[dict]] = {}
    nostri = _calendari_della_pipeline()
    for nome, svc in servizi.items():
        try:
            tutti = list_calendars(svc)
        except Exception as e:  # noqa: BLE001
            log.error(f"  {nome}: calendarList failed ({e}), account will download nothing")
            visti[nome] = []
            continue
        if liste is not None:
            liste[nome] = tutti
        visti[nome] = [c for c in tutti if not _da_saltare(c, nostri)]
    assegnati: dict[str, list[str]] = {nome: [] for nome in servizi}
    presi: set[str] = set()
    for nome, cals in visti.items():
        for c in cals:
            if c.get("primary") and c["id"] not in presi:
                assegnati[nome].append(c["id"])
                presi.add(c["id"])
    for nome, cals in visti.items():
        for c in cals:
            if c["id"] not in presi:
                assegnati[nome].append(c["id"])
                presi.add(c["id"])
    return assegnati


def _scrivi_json(percorso: Path, dati) -> None:
    ""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_name(f"{percorso.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dati, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, percorso)


def voce_calendario(c: dict, scaricato: bool, saltato: bool) -> dict:
    ""
    return {
        "id": c.get("id", ""),
        "nome": c.get("summaryOverride") or c.get("summary") or "",
        "nome_google": c.get("summary") or "",
        "colore": c.get("backgroundColor") or "",
        "testo": c.get("foregroundColor") or "",
        "colore_id": str(c.get("colorId") or ""),
        "ruolo": c.get("accessRole") or "",
        "primario": bool(c.get("primary")),
        "nascosto": bool(c.get("hidden")),
        "scelto": bool(c.get("selected")),
        "fuso": c.get("timeZone") or "",

        "scaricato": scaricato,

        "saltato": saltato,
    }


def scrivi_calendari(account_name: str, tutti: list[dict], assegnati: list[str]) -> Path:
    ""
    nostri = _calendari_della_pipeline()
    presi = set(assegnati)
    voci = [voce_calendario(c, c.get("id", "") in presi, _da_saltare(c, nostri)) for c in tutti]
    percorso = CALENDARS_DIR / account_name / "calendari.json"
    _scrivi_json(
        percorso,
        {
            "casella": account_name,
            "letto": datetime.now().astimezone().isoformat(timespec="seconds"),
            "calendari": voci,
        },
    )
    return percorso


class StatoGiro:
    ""







    def __init__(self, opzioni: dict):
        self.percorso = CALENDARS_DIR / "stato-giro.json"
        self.dati = {
            "in_corso": True,
            "partito": self._ora(),
            "finito": None,
            "uscita": None,
            "pid": os.getpid(),
            "opzioni": opzioni,
            "caselle": {},
        }
        self._salva()

    @staticmethod
    def _ora() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _salva(self) -> None:
        try:
            _scrivi_json(self.percorso, self.dati)
        except OSError as e:
            log.warning(f"run state not written: {e}")

    def casella(self, nome: str, esito: str, motivo: str = "", **altro) -> None:
        self.dati["caselle"][nome] = {
            "esito": esito,

            "motivo": motivo[:300],
            "finito": self._ora(),
            **altro,
        }
        self._salva()

    def fine(self, uscita: int) -> None:
        self.dati.update(in_corso=False, finito=self._ora(), uscita=uscita)
        self._salva()


def verifica_identita(service, email: str) -> bool:
    ""
    try:
        primario = service.calendars().get(calendarId="primary").execute().get("id", "")
    except Exception as e:  # noqa: BLE001
        log.error(f"  identity not verifiable for {email}: {e}")
        return False
    if email and primario.lower() != email.lower():
        log.error(f"  service belongs to {primario}, expected {email}: account skipped")
        return False
    return True


def save_accounts_config(accounts_info: list[dict]):
    ""
    accounts_file = CALENDARS_DIR / "accounts.json"
    accounts_file.parent.mkdir(parents=True, exist_ok=True)


    existing = {}
    if accounts_file.exists():
        try:
            data = json.loads(accounts_file.read_text())
            for c in data.get("calendars", []):
                existing[c["name"]] = c
        except (json.JSONDecodeError, KeyError):
            pass

    for info in accounts_info:
        existing[info["name"]] = info

    accounts_file.write_text(
        json.dumps({"calendars": list(existing.values())}, indent=2, ensure_ascii=False)
    )


def main():
    if not acquire_pid_lock("ca-l0-download", logger=log):



        log.warning("Another instance is running, exiting")
        sys.exit(75)

    parser = argparse.ArgumentParser(description="Google Calendar download — SBK")
    parser.add_argument("--account", help="Download single account")
    parser.add_argument("--since", help="Download events since YYYY-MM-DD")
    parser.add_argument(
        "--force",
        action="store_true",
        help="redo the full listing of every calendar ignoring syncTokens, and merge by id",
    )
    parser.add_argument(
        "--incremental", action="store_true", help="Incremental update (default behavior)"
    )
    parser.add_argument("--list", action="store_true", help="List calendars per account")
    parser.add_argument(
        "--all-calendars",
        action="store_true",
        help="Sync all calendars per account (not just primary)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="deprecated: without --since the first run already fetches the full history",
    )
    parser.add_argument(
        "--no-login",
        action="store_true",
        dest="senza_login",
        help="skip an account with no token instead of opening the browser login",
    )
    # Older Italian name, kept as a hidden alias.
    parser.add_argument("--senza-login", action="store_true", dest="senza_login", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    if args.full:
        default_since = "2020-01-01"
    else:
        default_since = (datetime.now(UTC) - timedelta(days=730)).strftime("%Y-%m-%d")
    since = args.since or default_since
    known_accounts = get_known_accounts()

    if not known_accounts:
        log.error(
            "No accounts found: the mailbox labels come from emails/accounts.json, written by "
            "uv run python tools/email/em-l0-auth.py <label>."
        )
        sys.exit(1)

    if args.account:
        if args.account not in known_accounts:
            log.error(f"Unknown account '{args.account}'. Known: {list(known_accounts.keys())}")
            sys.exit(1)
        targets = {args.account: known_accounts[args.account]}
    else:
        targets = known_accounts

    if args.list:
        _elenca(targets, args.senza_login)
        return

    stato = StatoGiro(
        {
            "account": args.account or "",
            "since": args.since or "",
            "force": bool(args.force),
            "senza_login": bool(args.senza_login),
        }
    )
    uscita = 1
    try:
        _giro(args, since, targets, stato)
        uscita = 0
    except SystemExit as e:
        uscita = e.code if isinstance(e.code, int) else 1
        raise
    finally:
        stato.fine(uscita)


def _elenca(targets: dict[str, str], senza_login: bool) -> None:
    for account_name, email in targets.items():
        try:
            svc = get_calendar_service(account_name, email, senza_login=senza_login)
        except Exception as e:  # noqa: BLE001
            log.error(f"Auth failed for {account_name}: {e}")
            continue
        if not verifica_identita(svc, email):
            continue
        print(f"=== {account_name}")
        for cal in list_calendars(svc):
            primary = " [PRIMARY]" if cal.get("primary") else ""
            print(f"  {cal.get('summary', '?')}{primary} ({cal.get('id', '')})")


def _giro(args, since: str, targets: dict[str, str], stato: StatoGiro) -> None:
    accounts_info = []
    falliti: list[str] = []

    servizi: dict[str, object] = {}
    for account_name, email in targets.items():
        try:
            svc = get_calendar_service(account_name, email, senza_login=args.senza_login)
        except SenzaLogin:
            log.warning(f"{account_name}: no token and --no-login, account skipped")
            falliti.append(account_name)
            stato.casella(account_name, "senza_login", "no calendar token")
            continue
        except Exception as e:  # noqa: BLE001
            log.error(f"Auth failed for {account_name}: {e}")
            falliti.append(account_name)
            stato.casella(account_name, "accesso", f"{type(e).__name__}: {e}")
            continue
        if not verifica_identita(svc, email):
            falliti.append(account_name)
            stato.casella(
                account_name, "identita", "primary calendar does not belong to the expected mailbox"
            )
            continue
        servizi[account_name] = svc

    liste: dict[str, list[dict]] = {}
    assegnati = assegna_calendari(servizi, liste)
    for account_name, tutti in liste.items():
        try:
            scrivi_calendari(account_name, tutti, assegnati.get(account_name, []))
        except OSError as e:
            log.warning(f"  {account_name}: calendari.json not written ({e})")

    for account_name, service in servizi.items():
        email = targets[account_name]
        calendar_ids = assegnati.get(account_name, [])
        log.info(f"\n=== {account_name} ({email}) — {len(calendar_ids)} calendars ===")
        if not calendar_ids:
            stato.casella(
                account_name,
                "senza_calendari" if account_name in liste else "errore",
                "no calendar to download"
                if account_name in liste
                else "calendar list not read",
            )
            continue



        pq_path = CALENDARS_DIR / account_name / "events.parquet"
        con_token = not args.since
        tokens = leggi_token(pq_path.parent) if con_token else {}
        use_incremental = con_token and pq_path.exists()

        events = []
        any_failed = False
        errori_cal: list[str] = []
        for cal_id in calendar_ids:
            try:
                if con_token:
                    token = None if args.force else tokens.get(cal_id)
                    try:
                        got, nuovo = scarica_sync(service, cal_id, account_name, token)
                    except TokenScaduto:
                        log.warning(f"    {cal_id}: token expired, redoing the full listing")
                        got, nuovo = scarica_sync(service, cal_id, account_name, None)
                    if nuovo:
                        tokens[cal_id] = nuovo
                    modo = "changed" if token else "full history"
                else:
                    got = download_events(service, cal_id, account_name, since=since)
                    modo = f"since {since}"
                events.extend(got)
                log.info(f"    {cal_id}: {len(got)} events ({modo})")
            except Exception as e:  # noqa: BLE001
                log.error(f"    {cal_id} failed: {e}")
                any_failed = True
                errori_cal.append(f"{type(e).__name__}: {e}")
        if any_failed:
            falliti.append(account_name)
            stato.casella(
                account_name,
                "errore",
                "; ".join(errori_cal),
                calendari=len(calendar_ids),
                eventi=len(events),
            )
            if not events:
                continue

        if use_incremental:
            existing_count = len(pd.read_parquet(pq_path)) if pq_path.exists() else 0
            log.info(
                f"Incremental: {len(events)} updated events, "
                f"merging with existing {existing_count} events"
            )
            df = merge_events_incremental(pq_path, events, pq_path)
            log.info(f"Saved parquet: {pq_path} ({len(df)} rows after merge)")
        elif con_token and events:


            df = merge_events_incremental(pq_path, events, pq_path)
            log.info(f"Saved parquet (first run, full history): {pq_path} ({len(df)} rows)")
        else:
            log.info(f"Full refresh since {since}: {len(events)} events")





            if args.since and pq_path.exists() and not args.force:
                df = merge_events_incremental(pq_path, events, pq_path)
                log.info(f"Saved parquet (MERGE, partial --since): {pq_path} ({len(df)} rows)")
            elif not events:













                if pq_path.exists():
                    df = pd.read_parquet(pq_path)
                    log.warning(
                        f"zero events for {account_name}: parquet NOT overwritten, "
                        f"the existing {len(df)} rows are kept"
                    )
                else:
                    df = pd.DataFrame()
                    log.warning(
                        f"zero events for {account_name} and no parquet: not writing "
                        "an empty one (a zero-column parquet cannot be opened)"
                    )
            else:
                df = events_to_parquet(events, pq_path)
                log.info(f"Saved parquet: {pq_path} ({len(df)} rows)")


        if not use_incremental:
            json_path = RAW_CALENDAR_DIR / f"cal-{account_name}.json"
            events_to_json(events, json_path)
            log.info(f"Saved JSON: {json_path}")








        dates = (
            df["start_datetime"].dropna()
            if "start_datetime" in df.columns
            else pd.Series([], dtype=object)
        )
        if len(dates) > 0:
            period = f"{dates.min()[:10]} to {dates.max()[:10]}"
        else:
            period = "unknown"

        accounts_info.append(
            {
                "name": account_name,
                "account": email,
                "events_count": len(events),
                "period": period,
                "last_download": datetime.now(UTC).isoformat(),
            }
        )

        if account_name not in falliti:

            if con_token:
                scrivi_token(pq_path.parent, tokens)
            mark_last_run(f"calendar-{account_name}")
            stato.casella(account_name, "ok", calendari=len(calendar_ids), eventi=len(events))

    if accounts_info and not args.list:
        save_accounts_config(accounts_info)
        total_events = sum(a["events_count"] for a in accounts_info)
        log.info(f"\nTotal: {total_events} events across {len(accounts_info)} accounts")


        try:
            from event_bus import EventBus

            EventBus.emit("calendar", "l0", accounts=len(accounts_info), events=total_events)
        except Exception as e:
            log.warning(f"EventBus emit failed: {e}")

    if falliti:
        log.error(f"Accounts with errors (not marked): {', '.join(falliti)}")
        sys.exit(1)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-calendar-download", source="calendar", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
