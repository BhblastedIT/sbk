"""imap-caldav plugin: shared pieces (provider presets, account config, secrets, paths, state).

Personal access only: your own mailbox password for apps (app-specific password), your own
CalDAV app password, your own private ICS link, or, for Outlook.com, a token from your own
app registration. No admin scopes, no delegation, no service accounts.

The plugin writes into the EXISTING kernel slots:
  mail     -> <data root>/emails/<account>/messages.parquet   (read by tools/email/em-l1-enrich.py)
  calendar -> <data root>/calendars/<account>/events.parquet  (read by tools/calendar/ca-l1-extract.py)
Its own working files live in <data root>/imap-caldav/ (state, raw calendar objects, summary).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

PLUGIN_ID = "imap-caldav"
CONFIG_KEY = "imap_caldav"
SLOT_MARKER = ".imap-caldav"  # hidden file that says "this slot folder is written by imap-caldav"

# --- Provider presets ---------------------------------------------------------------------
# Only host names that the provider documents officially (checked 2026-11-25, re-verify on use).
# A preset never holds a secret. Anything missing here must be set by hand in sbk.config.json.
PRESETS: dict[str, dict] = {
    "icloud": {
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "auth": "password",
        # Apple: "Username: This is usually the name of your iCloud Mail email address (for
        # example, johnappleseed, not johnappleseed@icloud.com)". Set "username" to override.
        "username_local_part": True,
        # Apple documents no CalDAV host for third-party clients on the pages checked: use the
        # Public Calendar link of a calendar (calendar = "ics"), or set caldav_url yourself.
        "caldav_url": "",
        "docs": [
            "https://support.apple.com/en-us/102525",
            "https://support.apple.com/en-us/102654",
            "https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud",
        ],
    },
    "fastmail": {
        "imap_host": "imap.fastmail.com",
        "imap_port": 993,
        "auth": "password",
        "caldav_url": "https://caldav.fastmail.com/",
        "docs": [
            "https://www.fastmail.help/hc/en-us/articles/1500000278342-Server-names-and-ports",
            "https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords",
        ],
    },
    "yahoo": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "auth": "password",
        "caldav_url": "https://caldav.calendar.yahoo.com",
        "docs": [
            "https://help.yahoo.com/kb/SLN4075.html",
            "https://help.yahoo.com/kb/SLN15241.html",
            "https://help.yahoo.com/kb/SLN4707.html",
        ],
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        # Microsoft: "Outlook.com requires the use of Modern Auth / OAuth2" and "POP & IMAP access
        # is disabled by default". No CalDAV: use a published ICS link (calendar = "ics").
        "auth": "xoauth2",
        "caldav_url": "",
        "docs": [
            "https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040",
            "https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth",
            "https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code",
            "https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com",
        ],
    },
}

# Outlook.com XOAUTH2 (personal Microsoft account, your own app registration, device code flow).
MS_AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
MS_IMAP_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"

# --- Secrets: Keychain first (tools/secrets_adapter.get_secret), then the environment -------
# service -> env var template; {A} is the account label in upper case.
SECRET_ENV = {
    "sbk-mailbox": "SBK_MAILBOX_PASSWORD_{A}",  # already mapped in secrets_adapter._ENV_MAP
    "sbk-caldav": "SBK_CALDAV_PASSWORD_{A}",
    "sbk-ics": "SBK_ICS_URL_{A}",
    "sbk-imap-oauth": "SBK_IMAP_OAUTH_REFRESH_{A}",
}

ACCOUNT_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")


class SetupError(Exception):
    """A setup problem the person must fix; the message is one line, printed as is."""


def env_name(service: str, account: str) -> str:
    return SECRET_ENV[service].replace("{A}", account.upper())


def get_secret(service: str, account: str) -> str | None:
    """Keychain (or the container env map) through secrets_adapter, then our own env var."""
    value = None
    try:
        from secrets_adapter import get_secret as _adapter_get

        value = _adapter_get(service, account)
    except Exception:  # noqa: BLE001 - keyring missing or locked: fall back to env
        value = None
    if value:
        return value
    return os.environ.get(env_name(service, account)) or None


def set_secret(service: str, account: str, value: str) -> None:
    from secrets_adapter import set_secret as _adapter_set

    _adapter_set(service, account, value)


# --- Paths (own constants, not in sbk_config) ----------------------------------------------
def plugin_dir() -> Path:
    return cfg.DATA_ROOT / PLUGIN_ID


def state_dir() -> Path:
    return plugin_dir() / "state"


def raw_dir(account: str) -> Path:
    return plugin_dir() / "raw" / account


def chunks_dir(account: str) -> Path:
    return plugin_dir() / "chunks" / account


def mail_slot(account: str) -> Path:
    return cfg.EMAILS_DIR / account


def calendar_slot(account: str) -> Path:
    return cfg.CALENDARS_DIR / account


def summary_path() -> Path:
    return plugin_dir() / "download-summary.json"


# --- Account config ------------------------------------------------------------------------
@dataclass
class Account:
    label: str
    email: str
    username: str
    imap_host: str = ""
    imap_port: int = 993
    auth: str = "password"  # password | xoauth2
    mail: bool = True
    folders: list[str] | str = "auto"  # "auto" | "all" | [names]
    mail_since: str = ""  # YYYY-MM-DD, first run only; empty = whole mailbox
    max_message_mb: float = 10.0
    calendar: str = "none"  # none | caldav | ics
    caldav_url: str = ""
    caldav_username: str = ""
    calendar_include: list[str] = field(default_factory=list)
    calendar_exclude: list[str] = field(default_factory=list)
    oauth_client_id: str = ""
    preset: str = ""


def _as_bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def load_accounts() -> list[Account]:
    """Read sbk.config.json "imap_caldav.accounts" ({label: {...}}). Raises SetupError."""
    raw = cfg.user_cfg(f"{CONFIG_KEY}.accounts", {}) or {}
    if not isinstance(raw, dict) or not raw:
        raise SetupError(
            f'{PLUGIN_ID}: no account in sbk.config.json "{CONFIG_KEY}.accounts" '
            "(see tools/imap-caldav/README.md)"
        )
    out: list[Account] = []
    for label, a in raw.items():
        if str(label).startswith("_"):
            continue
        if not ACCOUNT_RE.match(str(label)):
            raise SetupError(
                f"{PLUGIN_ID}: account label '{label}' must be lower case letters, digits or _"
            )
        if not isinstance(a, dict):
            raise SetupError(f"{PLUGIN_ID}: account '{label}' must be an object")
        a = {k: v for k, v in a.items() if not str(k).startswith("_")}
        preset_name = str(a.get("preset", "") or "").lower()
        if preset_name and preset_name not in PRESETS:
            raise SetupError(
                f"{PLUGIN_ID}: account '{label}': unknown preset '{preset_name}' "
                f"(known: {', '.join(sorted(PRESETS))})"
            )
        p = PRESETS.get(preset_name, {})
        email = str(a.get("email", "") or "").strip()
        username = str(a.get("username", "") or "").strip()
        if not username:
            username = email.split("@")[0] if p.get("username_local_part") else email
        acc = Account(
            label=label,
            email=email,
            username=username,
            imap_host=str(a.get("imap_host", "") or p.get("imap_host", "")).strip(),
            imap_port=int(a.get("imap_port", 0) or p.get("imap_port", 993)),
            auth=str(a.get("auth", "") or p.get("auth", "password")).strip().lower(),
            mail=_as_bool(a.get("mail"), True),
            folders=a.get("folders") or "auto",
            mail_since=str(a.get("mail_since", "") or "").strip(),
            max_message_mb=float(a.get("max_message_mb", 0) or 10.0),
            calendar=str(a.get("calendar", "") or "none").strip().lower(),
            caldav_url=str(a.get("caldav_url", "") or p.get("caldav_url", "")).strip(),
            caldav_username=str(a.get("caldav_username", "") or "").strip(),
            calendar_include=list(a.get("calendar_include") or []),
            calendar_exclude=list(a.get("calendar_exclude") or []),
            oauth_client_id=str(a.get("oauth_client_id", "") or "").strip(),
            preset=preset_name,
        )
        if acc.auth not in ("password", "xoauth2"):
            raise SetupError(f"{PLUGIN_ID}: account '{label}': auth must be password or xoauth2")
        if acc.calendar not in ("none", "caldav", "ics"):
            raise SetupError(
                f"{PLUGIN_ID}: account '{label}': calendar must be none, caldav or ics"
            )
        if acc.mail and not acc.imap_host:
            raise SetupError(f"{PLUGIN_ID}: account '{label}': imap_host missing (or set a preset)")
        if acc.mail and not acc.username:
            raise SetupError(f"{PLUGIN_ID}: account '{label}': username (or email) missing")
        if acc.calendar == "caldav" and not acc.caldav_url:
            raise SetupError(
                f"{PLUGIN_ID}: account '{label}': calendar is caldav but caldav_url is empty "
                "(this provider documents no CalDAV host: set it, or use calendar = ics)"
            )
        if acc.calendar == "caldav" and not acc.caldav_url.startswith("https://"):
            raise SetupError(f"{PLUGIN_ID}: account '{label}': caldav_url must start with https://")
        if acc.auth == "xoauth2" and acc.mail and not acc.oauth_client_id:
            raise SetupError(
                f"{PLUGIN_ID}: account '{label}': auth xoauth2 needs oauth_client_id "
                "(the Application (client) ID of your own app registration)"
            )
        if acc.mail_since and not re.match(r"^\d{4}-\d{2}-\d{2}$", acc.mail_since):
            raise SetupError(f"{PLUGIN_ID}: account '{label}': mail_since must be YYYY-MM-DD")
        out.append(acc)
    if not out:
        raise SetupError(f'{PLUGIN_ID}: no account in sbk.config.json "{CONFIG_KEY}.accounts"')
    return out


def calendar_window_days() -> tuple[int, int]:
    past = int(cfg.user_cfg(f"{CONFIG_KEY}.calendar_past_days", 730) or 730)
    future = int(cfg.user_cfg(f"{CONFIG_KEY}.calendar_future_days", 365) or 365)
    return past, future


def own_addresses(acc: Account) -> set[str]:
    own = {e.lower() for e in getattr(cfg, "OWN_EMAILS", set()) or set()}
    if acc.email:
        own.add(acc.email.lower())
    if "@" in acc.username:
        own.add(acc.username.lower())
    return own


# --- Slot ownership: never write into a folder another downloader owns ----------------------
def gmail_labels() -> set[str]:
    p = cfg.EMAILS_DIR / "accounts.json"
    try:
        return set(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def claim_slot(folder: Path, data_file: str) -> None:
    """Mark `folder` as ours, or refuse if another downloader already writes there."""
    if folder.exists() and (folder / data_file).exists() and not (folder / SLOT_MARKER).exists():
        raise SetupError(
            f"{PLUGIN_ID}: {folder} already holds {data_file} from another downloader; "
            "pick another account label"
        )
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / SLOT_MARKER
    if not marker.exists():
        marker.write_text(PLUGIN_ID + "\n", encoding="utf-8")


def check_label_free(acc: Account) -> None:
    if acc.label in gmail_labels():
        raise SetupError(
            f"{PLUGIN_ID}: account label '{acc.label}' is a Gmail mailbox in emails/accounts.json; "
            "pick another label"
        )


# --- State (one JSON per account) ----------------------------------------------------------
def load_state(account: str) -> dict:
    p = state_dir() / f"{account}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("imap", {})
            data.setdefault("caldav", {})
            data.setdefault("ics", {})
            return data
    except (OSError, ValueError):
        pass
    return {"imap": {}, "caldav": {}, "ics": {}}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --- HTTP (stdlib only; tests replace HTTP_SEND) ---------------------------------------------
HTTP_TIMEOUT = 60


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # redirects are followed by hand, keeping the method (PROPFIND/REPORT)


def _urllib_send(method: str, url: str, headers: dict, body: bytes | None):
    """One HTTP exchange, no redirect following. Returns (status, headers, body bytes)."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


HTTP_SEND = _urllib_send


def _site(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:])


def http_request(
    method: str,
    url: str,
    headers: dict | None = None,
    body: bytes | None = None,
    *,
    auth: tuple[str, str] | None = None,
    max_redirects: int = 5,
):
    """HTTP with manual redirects: https only; Basic credentials go only to the same site
    (last two labels of the host name) as the first URL. Returns (status, headers, body, url)."""
    first_site = _site(urllib.parse.urlsplit(url).hostname or "")
    for _ in range(max_redirects + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https":
            raise SetupError(
                f"{PLUGIN_ID}: refusing a non-https URL ({parts.scheme}://{parts.hostname})"
            )
        h = dict(headers or {})
        h.setdefault("User-Agent", "sbk-imap-caldav/0.1")
        if auth and _site(parts.hostname or "") == first_site:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            h["Authorization"] = f"Basic {token}"
        status, rh, data = HTTP_SEND(method, url, h, body)
        if status in (301, 302, 303, 307, 308) and rh.get("location"):
            url = urllib.parse.urljoin(url, rh["location"])
            if status == 303:
                method, body = "GET", None
            continue
        return status, rh, data, url
    raise SetupError(f"{PLUGIN_ID}: too many redirects")


# --- Outlook.com XOAUTH2 (your own app registration, personal account) -----------------------
def ms_refresh_access_token(acc: Account) -> str:
    """Trade the stored refresh token for an access token; store a rotated refresh token."""
    refresh = get_secret("sbk-imap-oauth", acc.label)
    if not refresh:
        raise SetupError(
            f"{PLUGIN_ID}: no Outlook.com sign-in for '{acc.label}' "
            f"(run tools/imap-caldav/ic-l0-auth.py --account {acc.label} --xoauth2)"
        )
    form = urllib.parse.urlencode(
        {
            "client_id": acc.oauth_client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "scope": MS_IMAP_SCOPE,
        }
    ).encode()
    status, _h, data, _u = http_request(
        "POST",
        f"{MS_AUTHORITY}/token",
        {"Content-Type": "application/x-www-form-urlencoded"},
        form,
    )
    try:
        payload = json.loads(data.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    if status != 200 or not payload.get("access_token"):
        err = payload.get("error", f"HTTP {status}")
        raise SetupError(
            f"{PLUGIN_ID}: Outlook.com token refresh failed for '{acc.label}' ({err}); "
            f"sign in again with ic-l0-auth.py --account {acc.label} --xoauth2"
        )
    new_refresh = payload.get("refresh_token")
    if new_refresh and new_refresh != refresh:
        try:
            set_secret("sbk-imap-oauth", acc.label, new_refresh)
        except Exception:  # noqa: BLE001 - container mode or no keyring: keep the old one
            pass
    return payload["access_token"]


def save_state(account: str, state: dict) -> None:
    write_json(state_dir() / f"{account}.json", state)


def require_secret(service: str, acc: Account, what: str) -> str:
    """The secret or a one-line SetupError naming both places the code looks."""
    value = get_secret(service, acc.label)
    if not value:
        flag = {"sbk-mailbox": "--imap", "sbk-caldav": "--caldav", "sbk-ics": "--ics"}[service]
        raise SetupError(
            f"{PLUGIN_ID}: no {what} for '{acc.label}' (Keychain {service}/{acc.label} or env "
            f"{env_name(service, acc.label)}); store it with "
            f"tools/imap-caldav/ic-l0-auth.py --account {acc.label} {flag}"
        )
    return value
