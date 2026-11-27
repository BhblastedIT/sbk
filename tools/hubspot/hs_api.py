"""HubSpot plugin core: your contacts, companies, deals, notes and tasks.

Personal access only. You build your own *user-level* OAuth app (developer platform
2026.09, ``"isUserLevel": true``, ``"distribution": "private"``) from the project in
``tools/hubspot/hubspot-project/`` and install it for yourself with one browser login
(``hs-l0-auth.py``). A user-level token is limited at runtime by your own HubSpot user
permissions, so the plugin sees what you can see in HubSpot and nothing more. Private
apps (Super Admin only), service keys and account-level apps (whose token reads every
record the scopes allow, whoever installed it) are not used: a token that introspection
reports as account-level is refused.

Read-only by construction: GET for reading, POST only to ``.../search`` and
``.../batch/read`` (both read endpoints) and to the two OAuth token endpoints. Any other
call is refused before it leaves the machine (a test checks it).

Vendor facts this module relies on (checked on HubSpot's official docs, 2026-11-25):
- user-level apps, ``isUserLevel``, supported REST APIs (contacts, companies, deals,
  notes, tasks, pipelines read, associations read on a record):
  https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/user-level-apps
- install permission (Super Admin or HubSpot Marketplace access, plus the scope groups),
  account-level tokens ignore user permissions:
  https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot
  https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/working-with-oauth
- token endpoint ``/oauth/v3/token``, 30-minute access tokens, introspection
  ``/oauth/v3/token/introspect`` (user, user_id, hub_id, hublet, isUserLevel):
  https://developers.hubspot.com/docs/api-reference/legacy/authentication/manage-oauth-tokens
- redirect URLs: https only, ``http://localhost`` allowed, no IP addresses:
  https://developers.hubspot.com/docs/apps/developer-platform/build-apps/app-configuration
- search ``/crm/objects/2026-09/{object}/search``: 200 per page, 10,000 results per query,
  5 requests/second, ``after`` paging, one sort rule:
  https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm
- limits of privately distributed apps: 100 requests / 10 s on Free and Starter, 429 with
  ``policyName`` DAILY or secondly (the page, checked 2026-11-25, names platform versions
  2025.2 and 2026.03, not 2026.09; the pacing here assumes the same limits):
  https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines
- scopes (notes and tasks need ``crm.objects.contacts.read``):
  https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes
  https://developers.hubspot.com/docs/api-reference/latest/crm/activities/notes/guide
  https://developers.hubspot.com/docs/api-reference/latest/crm/activities/tasks/guide
- owners ``/crm/owners/2026-09`` (owner id vs user id):
  https://developers.hubspot.com/docs/api-reference/latest/crm/owners/guide
- object type ids (0-1 contacts, 0-2 companies, 0-3 deals, 0-27 tasks, 0-46 notes):
  https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm

Nothing here prints or logs a token or the client secret.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

SOURCE = "hubspot"
KEYCHAIN_SERVICE = "sbk-hubspot"
CLIENT_ID_ACCOUNT = "client-id"
CLIENT_SECRET_ACCOUNT = "client-secret"
DEFAULT_LABEL = "default"

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubspot.com/oauth/v3/token"
INTROSPECT_URL = "https://api.hubspot.com/oauth/v3/token/introspect"
API_BASE = "https://api.hubapi.com"
API_VERSION = "2026-09"
ALLOWED_HOSTS = frozenset({"api.hubapi.com", "api.hubspot.com"})
REDIRECT_PATH = "/oauth-callback"
DEFAULT_REDIRECT_PORT = 8723
DEFAULT_APP_HOST = "app.hubspot.com"

# What the app in tools/hubspot/hubspot-project asks for. Notes and tasks are read with
# crm.objects.contacts.read (HubSpot's notes and tasks guides). No write scope at all.
REQUIRED_SCOPES = (
    "crm.objects.contacts.read",
    "crm.objects.companies.read",
    "crm.objects.deals.read",
)
# Owners tell which records are yours. Optional: the owners API is not in HubSpot's list
# of user-level APIs, so the download works (with a warning) when it is refused.
OPTIONAL_SCOPES = ("crm.objects.owners.read",)

ENV_CLIENT_ID = "HUBSPOT_CLIENT_ID"
ENV_CLIENT_SECRET = "HUBSPOT_CLIENT_SECRET"
ENV_REFRESH_TOKEN = "HUBSPOT_REFRESH_TOKEN"
ENV_TOKEN_FILE = "HUBSPOT_TOKEN_FILE"

SETUP_HINT = "see docs/CONNECTING.md#hubspot"

REQUEST_DELAY = 0.11  # 100 requests per 10 seconds (privately distributed app, Free/Starter)
SEARCH_DELAY = 0.25  # search endpoints: 5 requests per second per account
REQUEST_TIMEOUT_SECS = 60
MAX_RETRIES = 5
MAX_WAIT_SECS = 120
SEARCH_PAGE = 200
SEARCH_CAP = 10_000
BATCH_SIZE = 100
TEXT_MAX = 4000
REFRESH_DAYS = 30
MULTI_SEP = "|||"

TYPE_IDS = {"contacts": "0-1", "companies": "0-2", "deals": "0-3", "tasks": "0-27", "notes": "0-46"}

CONTACT_PROPS = (
    "firstname",
    "lastname",
    "email",
    "phone",
    "mobilephone",
    "company",
    "jobtitle",
    "associatedcompanyid",
    "hubspot_owner_id",
    "createdate",
    "lastmodifieddate",
    "notes_last_contacted",
)
COMPANY_PROPS = ("name", "domain", "hs_lastmodifieddate")
DEAL_PROPS = (
    "dealname",
    "dealstage",
    "pipeline",
    "amount",
    "deal_currency_code",
    "closedate",
    "hubspot_owner_id",
    "createdate",
    "hs_lastmodifieddate",
    "hs_is_closed",
    "hs_is_closed_won",
)
TASK_PROPS = (
    "hs_task_subject",
    "hs_task_body",
    "hs_task_status",
    "hs_task_priority",
    "hs_task_type",
    "hs_timestamp",
    "hubspot_owner_id",
    "hs_createdate",
    "hs_lastmodifieddate",
)
NOTE_PROPS = (
    "hs_note_body",
    "hs_timestamp",
    "hubspot_owner_id",
    "hs_createdate",
    "hs_lastmodifieddate",
)

# The objects found through search. "modified" is the property search filters and sorts on:
# contacts use lastmodifieddate, the other objects hs_lastmodifieddate (search guide).
OBJECTS: dict[str, dict] = {
    "contacts": {"modified": "lastmodifieddate", "props": CONTACT_PROPS, "assoc": ()},
    "deals": {
        "modified": "hs_lastmodifieddate",
        "props": DEAL_PROPS,
        "assoc": ("contacts", "companies"),
    },
    "tasks": {
        "modified": "hs_lastmodifieddate",
        "props": TASK_PROPS,
        "assoc": ("contacts", "companies", "deals"),
    },
    "notes": {
        "modified": "hs_lastmodifieddate",
        "props": NOTE_PROPS,
        "assoc": ("contacts", "companies", "deals"),
    },
}
ITEM_TYPES = ("deals", "tasks", "notes")

CONTACT_COLUMNS = [
    "source",
    "name",
    "email",
    "phone",
    "company",
    "title",
    "first_seen",
    "last_seen",
    "interactions",
    "url",
]
INTERACTION_COLUMNS = [
    "source",
    "ts",
    "kind",
    "title",
    "text",
    "participants",
    "owner_role",
    "due",
    "url",
    "status",
]


class HubSpotError(Exception):
    """A HubSpot problem worth one clear line to the user (never carries a token)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class AuthError(HubSpotError):
    """The login is missing, expired or revoked."""


class DailyLimitReached(HubSpotError):
    """HubSpot's daily request limit: stop and keep what was downloaded."""


class AccountLevelApp(HubSpotError):
    """The token belongs to an account-level app: refused, it would read beyond your access."""


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def hs_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "hubspot"


def raw_dir() -> Path:
    return hs_dir() / "raw"


def processed_dir() -> Path:
    return hs_dir() / "processed"


def state_path() -> Path:
    return hs_dir() / "state.json"


def summary_path() -> Path:
    return hs_dir() / "download-summary.json"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "hubspot" section) -------------------------------------


def cfg(key: str, default):
    return sbk_config.user_cfg(f"hubspot.{key}", default)


def _secret(account: str) -> str:
    try:
        from secrets_adapter import get_secret

        return (get_secret(KEYCHAIN_SERVICE, account) or "").strip()
    except Exception:  # noqa: BLE001 - no keyring backend counts as "not set"
        return ""


def client_id() -> str:
    """Client ID of your own app: env first, then sbk.config.json, then the Keychain."""
    return (
        os.environ.get(ENV_CLIENT_ID, "").strip()
        or str(cfg("client_id", "") or "").strip()
        or _secret(CLIENT_ID_ACCOUNT)
    )


def client_secret() -> str:
    """Client secret of your own app: Keychain first, then env. Never in sbk.config.json."""
    return _secret(CLIENT_SECRET_ACCOUNT) or os.environ.get(ENV_CLIENT_SECRET, "").strip()


def redirect_port() -> int:
    try:
        return int(cfg("redirect_port", DEFAULT_REDIRECT_PORT))
    except (TypeError, ValueError):
        return DEFAULT_REDIRECT_PORT


def redirect_uri(port: int | None = None) -> str:
    return f"http://localhost:{port or redirect_port()}{REDIRECT_PATH}"


def no_app_message() -> str:
    return (
        f"HubSpot: no app credentials ({ENV_CLIENT_ID} and {ENV_CLIENT_SECRET}, or Keychain "
        f"{KEYCHAIN_SERVICE}/{CLIENT_ID_ACCOUNT} and /{CLIENT_SECRET_ACCOUNT}); {SETUP_HINT}"
    )


# --- refresh token storage ------------------------------------------------------------


def _token_file() -> Path | None:
    p = os.environ.get(ENV_TOKEN_FILE, "").strip()
    return Path(p).expanduser() if p else None


def load_refresh_token(label: str = DEFAULT_LABEL) -> tuple[str, str]:
    """(refresh_token, where) or ("", "") when no login is stored anywhere."""
    tok = _secret(label)
    if tok:
        return tok, f"Keychain {KEYCHAIN_SERVICE}/{label}"
    tf = _token_file()
    if tf and tf.is_file():
        tok = tf.read_text(encoding="utf-8").strip()
        if tok:
            return tok, f"file {ENV_TOKEN_FILE}"
    tok = os.environ.get(ENV_REFRESH_TOKEN, "").strip()
    if tok:
        return tok, f"env {ENV_REFRESH_TOKEN}"
    return "", ""


def save_refresh_token(token: str, label: str = DEFAULT_LABEL) -> str:
    """Store the refresh token where the next run reads it first. '' when it cannot."""
    tf = _token_file()
    if tf:
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(token, encoding="utf-8")
        os.chmod(tf, 0o600)
        return f"file {ENV_TOKEN_FILE}"
    if os.environ.get("SBK_CONTAINERIZED", "0") == "1":
        return ""
    from secrets_adapter import set_secret

    set_secret(KEYCHAIN_SERVICE, label, token)
    return f"Keychain {KEYCHAIN_SERVICE}/{label}"


# --- OAuth ----------------------------------------------------------------------------


def _default_opener(req: Request, timeout: float):
    return urlopen(req, timeout=timeout)


def _check_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise HubSpotError(f"refusing to send credentials to {host or url!r}")


def _safe_body(e: HTTPError) -> str:
    try:
        return (e.read() or b"").decode("utf-8", "replace")[:500]
    except Exception:  # noqa: BLE001
        return ""


def _oauth_post(url: str, form: dict, opener=None) -> dict:
    """POST form-encoded to a HubSpot OAuth endpoint (v3: every value in the body)."""
    _check_host(url)
    req = Request(
        url,
        data=urlencode(form).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with (opener or _default_opener)(req, REQUEST_TIMEOUT_SECS) as resp:
            return json.loads(resp.read() or b"{}")
    except HTTPError as e:
        body = _safe_body(e)
        try:
            err = json.loads(body).get("error", "")
        except ValueError:
            err = ""
        if e.code in (400, 401) and err in (
            "invalid_grant",
            "invalid_client",
            "unauthorized_client",
        ):
            raise AuthError(
                f"HubSpot refused the login ({err}); run tools/hubspot/hs-l0-auth.py again",
                e.code,
            ) from None
        raise HubSpotError(
            f"HubSpot OAuth answered HTTP {e.code} ({err or 'no detail'})", e.code
        ) from None
    except URLError as e:
        raise HubSpotError(f"network error talking to HubSpot: {e.reason}") from None


def authorize_url(cid: str, redirect: str, state: str) -> str:
    return (
        AUTHORIZE_URL
        + "?"
        + urlencode(
            {
                "client_id": cid,
                "redirect_uri": redirect,
                "scope": " ".join(("oauth", *REQUIRED_SCOPES)),
                "optional_scope": " ".join(OPTIONAL_SCOPES),
                "state": state,
            }
        )
    )


def exchange_code(cid: str, secret: str, code: str, redirect: str, opener=None) -> dict:
    return _oauth_post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": cid,
            "client_secret": secret,
        },
        opener,
    )


def refresh_access(cid: str, secret: str, refresh: str, opener=None) -> dict:
    return _oauth_post(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": cid,
            "client_secret": secret,
        },
        opener,
    )


def introspect(cid: str, secret: str, access_token: str, opener=None) -> dict:
    return _oauth_post(
        INTROSPECT_URL,
        {
            "client_id": cid,
            "client_secret": secret,
            "token_type_hint": "access_token",
            "access_token": access_token,
        },
        opener,
    )


def describe_token(info: dict) -> dict:
    """What the introspection says about the login, without the token itself."""
    signed = info.get("signed_access_token") or {}
    level = signed.get("isUserLevel")
    if level is None:
        level = info.get("isUserLevel", info.get("is_user_level"))
    scopes = info.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return {
        "user_email": str(info.get("user") or "").strip().lower(),
        "user_id": str(info.get("user_id") or ""),
        "hub_id": str(info.get("hub_id") or signed.get("hubId") or ""),
        "hub_domain": str(info.get("hub_domain") or ""),
        "hublet": str(signed.get("hublet") or ""),
        "app_id": str(info.get("app_id") or ""),
        "is_user_level": level if isinstance(level, bool) else None,
        "scopes": sorted(str(s) for s in scopes),
    }


def check_user_level(me: dict) -> None:
    """Refuse an account-level app; an unknown answer is accepted with a warning upstream."""
    if me.get("is_user_level") is False:
        raise AccountLevelApp(
            "HubSpot: this app is account-level, so its token would read every record the "
            'scopes allow, not only yours; set "isUserLevel": true in app-hsmeta.json, create '
            f"a new app (HubSpot cannot convert it) and sign in again; {SETUP_HINT}"
        )


def missing_scopes(granted: list[str]) -> list[str]:
    g = set(granted)
    return [s for s in REQUIRED_SCOPES if s not in g]


# --- HTTP client ----------------------------------------------------------------------


def _allowed_post(path: str) -> bool:
    p = urlparse(path).path
    return p.endswith("/search") or p.endswith("/batch/read")


class HubSpotClient:
    """Small read-only HubSpot REST client. `opener(Request, timeout)` is injectable."""

    def __init__(
        self,
        access_token: str,
        opener=None,
        sleep=None,
        clock=None,
        refresher=None,
        delay: float | None = None,
        search_delay: float | None = None,
    ):
        self._token = access_token
        self._open = opener or _default_opener
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._refresher = refresher  # () -> new access token; access tokens last 30 minutes
        self._delay = REQUEST_DELAY if delay is None else delay
        self._search_delay = SEARCH_DELAY if search_delay is None else search_delay
        self._last = 0.0
        self._last_search = 0.0
        self.requests = 0
        self.warnings: list[str] = []  # copied into download-summary.json by run_download

    def _pace(self, search: bool) -> None:
        now = self._clock()
        gap = now - self._last
        if self._last and gap < self._delay:
            self._sleep(self._delay - gap)
        if search:
            sgap = self._clock() - self._last_search
            if self._last_search and sgap < self._search_delay:
                self._sleep(self._search_delay - sgap)
            self._last_search = self._clock()
        self._last = self._clock()

    def _send(self, method: str, path: str, params: dict | None = None, body=None):
        if method not in ("GET", "POST"):
            raise HubSpotError(f"refusing {method}: this plugin only reads")
        if method == "POST" and not _allowed_post(path):
            raise HubSpotError(f"refusing POST {path}: only search and batch read are allowed")
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        _check_host(url)
        search = urlparse(url).path.endswith("/search")
        refreshed = False
        attempt = 0
        while True:
            self._pace(search)
            self.requests += 1
            headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            req = Request(url, data=data, method=method, headers=headers)
            try:
                with self._open(req, REQUEST_TIMEOUT_SECS) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except HTTPError as e:
                text = _safe_body(e)
                if e.code == 401 and self._refresher and not refreshed:
                    self._token = self._refresher()
                    refreshed = True
                    continue
                if e.code == 401:
                    raise AuthError(
                        "HubSpot: the login was refused (HTTP 401); run tools/hubspot/hs-l0-auth.py again",
                        401,
                    ) from None
                if e.code == 429:
                    policy = ""
                    try:
                        policy = str(json.loads(text).get("policyName") or "")
                    except ValueError:
                        pass
                    if policy.upper() == "DAILY":
                        raise DailyLimitReached(
                            "HubSpot: daily API limit reached; what was read is kept, run again tomorrow",
                            429,
                        ) from None
                    attempt += 1
                    if attempt > MAX_RETRIES:
                        raise HubSpotError(
                            "HubSpot: rate limited, gave up after retries", 429
                        ) from None
                    self._sleep(_retry_after(e, attempt))
                    continue
                if e.code >= 500:
                    attempt += 1
                    if attempt > MAX_RETRIES:
                        raise HubSpotError(
                            f"HubSpot: HTTP {e.code} on {urlparse(url).path}", e.code
                        ) from None
                    self._sleep(min(2**attempt, MAX_WAIT_SECS))
                    continue
                msg = ""
                try:
                    msg = str(json.loads(text).get("message") or "")[:200]
                except ValueError:
                    msg = text[:200]
                raise HubSpotError(
                    f"HubSpot: HTTP {e.code} on {urlparse(url).path}: {msg}", e.code
                ) from None
            except URLError as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise HubSpotError(f"network error talking to HubSpot: {e.reason}") from None
                self._sleep(min(2**attempt, MAX_WAIT_SECS))

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._send("GET", path, params)

    def post(self, path: str, body: dict) -> dict:
        return self._send("POST", path, body=body)


def _retry_after(e: HTTPError, attempt: int) -> float:
    try:
        ra = float((e.headers or {}).get("Retry-After") or 0)
    except (TypeError, ValueError):
        ra = 0
    if ra > 0:
        return min(ra, MAX_WAIT_SECS)
    return min(10.0 * attempt, MAX_WAIT_SECS)  # the burst window is 10 seconds


# --- helpers --------------------------------------------------------------------------


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value) -> str:
    """HubSpot timestamp (ISO string or epoch milliseconds) -> ISO 8601 UTC, '' if empty."""
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    s = str(value).strip()
    if re.fullmatch(r"\d{10,14}", s):
        n = int(s)
        if n > 10**11:
            n = n / 1000
        return datetime.fromtimestamp(n, UTC).replace(microsecond=0).isoformat()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC).replace(microsecond=0).isoformat()


def to_ms(value) -> int | None:
    s = iso(value)
    if not s:
        return None
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def prop(record: dict, name: str) -> str:
    v = (record.get("properties") or {}).get(name)
    return "" if v is None else str(v).strip()


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|tr|h\d)[^>]*>", re.IGNORECASE)


def html_to_text(value: str) -> str:
    """Note and task bodies are HTML: keep the words, one line per block."""
    if not value:
        return ""
    s = _BLOCK.sub("\n", value)
    s = html.unescape(_TAG.sub("", s))
    lines = [re.sub(r"[ \t ]+", " ", x).strip() for x in s.splitlines()]
    return "\n".join(x for x in lines if x)[:TEXT_MAX]


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _ids_of(assoc_block) -> list[str]:
    out: list[str] = []
    for r in (assoc_block or {}).get("results") or []:
        rid = r.get("id") or r.get("toObjectId")
        if rid is not None and str(rid) not in out:
            out.append(str(rid))
    return out


_ASSOC_KEYS = {
    "contacts": "contacts",
    "contact": "contacts",
    "companies": "companies",
    "company": "companies",
    "deals": "deals",
    "deal": "deals",
}


def parse_associations(record: dict) -> dict[str, list[str]]:
    """{'contacts': [...], 'companies': [...], 'deals': [...]} from a GET with associations."""
    out: dict[str, list[str]] = {}
    for key, block in (record.get("associations") or {}).items():
        name = _ASSOC_KEYS.get(str(key).lower())
        if not name:
            continue
        bucket = out.setdefault(name, [])
        for i in _ids_of(block):
            if i not in bucket:
                bucket.append(i)
    return out


# --- L0 steps ---------------------------------------------------------------------------


def find_owner(client: HubSpotClient, me: dict, stats: dict) -> str:
    """Your owner id (the id on hubspot_owner_id), '' when HubSpot does not give it."""
    if not me.get("user_email") and not me.get("user_id"):
        stats["owner_lookup"] = "no user in the token introspection"
        return ""
    params = {"limit": 100}
    if me.get("user_email"):
        params["email"] = me["user_email"]
    after = None
    for _ in range(20):
        if after:
            params["after"] = after
        try:
            data = client.get(f"/crm/owners/{API_VERSION}", dict(params))
        except (AuthError, DailyLimitReached):
            raise
        except HubSpotError as e:
            stats["owner_lookup"] = f"refused (HTTP {e.status})"
            return ""
        for o in data.get("results") or []:
            same_email = (
                me.get("user_email") and str(o.get("email") or "").lower() == me["user_email"]
            )
            same_user = me.get("user_id") and str(o.get("userId") or "") == me["user_id"]
            if same_email or same_user:
                stats["owner_lookup"] = "ok"
                return str(o.get("id") or "")
        after = ((data.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            break
    stats["owner_lookup"] = "you are not an owner in this account"
    return ""


def fetch_pipelines(client: HubSpotClient, stats: dict) -> dict:
    """{stage_id: {label, pipeline, is_closed, probability}} for deal pipelines."""
    try:
        data = client.get(f"/crm/pipelines/{API_VERSION}/deals")
    except (AuthError, DailyLimitReached):
        raise
    except HubSpotError as e:
        stats["pipelines"] = f"refused (HTTP {e.status})"
        return {}
    stages: dict[str, dict] = {}
    for p in data.get("results") or []:
        for s in p.get("stages") or []:
            meta = s.get("metadata") or {}
            stages[str(s.get("id"))] = {
                "label": s.get("label") or "",
                "pipeline": p.get("label") or "",
                "is_closed": str(meta.get("isClosed", "")).lower() == "true",
                "probability": str(meta.get("probability", "")),
            }
    stats["pipelines"] = "ok"
    stats["deal_stages"] = len(stages)
    return stages


def search_objects(
    client: HubSpotClient, obj: str, since_ms: int | None, owner_id: str, stats: dict
) -> list[dict]:
    """Every record of `obj` modified at or after `since_ms` (and owned by you if owner_id).

    Goes past the 10,000-results cap of one query by sorting on the modified date and
    starting again from the last date seen.
    """
    spec = OBJECTS[obj]
    mod = spec["modified"]
    out: dict[str, dict] = {}
    lower = since_ms
    while True:
        filters = []
        if lower is not None:
            filters.append({"propertyName": mod, "operator": "GTE", "value": str(lower)})
        if owner_id:
            filters.append(
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id}
            )
        body: dict = {
            "limit": SEARCH_PAGE,
            "properties": list(spec["props"]),
            "sorts": [{"propertyName": mod, "direction": "ASCENDING"}],
        }
        if filters:
            body["filterGroups"] = [{"filters": filters}]
        got, total, last_mod = 0, 0, None
        while True:
            data = client.post(f"/crm/objects/{API_VERSION}/{obj}/search", dict(body))
            results = data.get("results") or []
            total = int(data.get("total") or 0)
            for r in results:
                out[str(r.get("id"))] = r
                last_mod = prop(r, mod) or last_mod
            got += len(results)
            nxt = ((data.get("paging") or {}).get("next") or {}).get("after")
            if not nxt or not results or got >= SEARCH_CAP:
                break
            body["after"] = int(nxt) if str(nxt).isdigit() else nxt
        if got < SEARCH_CAP or total <= got or not last_mod:
            return list(out.values())
        new_lower = to_ms(last_mod)
        if new_lower is None or (lower is not None and new_lower <= lower):
            stats.setdefault("search_truncated", []).append(obj)
            return list(out.values())
        lower = new_lower


def fetch_detail(client: HubSpotClient, obj: str, rid: str) -> dict | None:
    """One record with its associations. None when HubSpot says it is gone."""
    spec = OBJECTS[obj]
    try:
        return client.get(
            f"/crm/objects/{API_VERSION}/{obj}/{rid}",
            {"properties": ",".join(spec["props"]), "associations": ",".join(spec["assoc"])},
        )
    except (AuthError, DailyLimitReached):
        raise
    except HubSpotError as e:
        if e.status == 404:
            return None
        raise


def batch_read(
    client: HubSpotClient, obj: str, ids: list[str], props, stats: dict, single_cap: int = 200
) -> list[dict]:
    """Records by id, 100 per batch. If HubSpot refuses the batch endpoint (it is not named
    one by one in the user-level list), falls back to single reads, at most `single_cap`."""
    out: list[dict] = []
    for i in range(0, len(ids), BATCH_SIZE):
        chunk = ids[i : i + BATCH_SIZE]
        try:
            data = client.post(
                f"/crm/objects/{API_VERSION}/{obj}/batch/read",
                {"properties": list(props), "inputs": [{"id": x} for x in chunk]},
            )
        except (AuthError, DailyLimitReached):
            raise
        except HubSpotError as e:
            if e.status not in (400, 403, 405):
                raise
            stats[f"{obj}_batch_refused"] = e.status
            rest = ids[i:]
            for rid in rest[:single_cap]:
                try:
                    rec = client.get(
                        f"/crm/objects/{API_VERSION}/{obj}/{rid}", {"properties": ",".join(props)}
                    )
                except (AuthError, DailyLimitReached):
                    raise
                except HubSpotError:
                    continue
                out.append(rec)
            if len(rest) > single_cap:
                stats[f"{obj}_left_for_next_run"] = len(rest) - single_cap
            return out
        out.extend(data.get("results") or [])
    return out


def _slim(record: dict, obj: str, fetched_at: str, prev: dict | None = None) -> dict:
    """The record as kept in raw/: only the properties this plugin asks for."""
    props = COMPANY_PROPS if obj == "companies" else OBJECTS[obj]["props"]
    got = record.get("properties") or {}
    keep = {k: got.get(k) for k in props}
    out = {
        "id": str(record.get("id")),
        "properties": keep,
        "url": record.get("url") or (prev or {}).get("url") or "",
        "fetched_at": fetched_at,
        "archived": bool(record.get("archived")),
    }
    if prev and "associations" in prev:
        out["associations"] = prev["associations"]
    return out


def run_download(
    client: HubSpotClient,
    me: dict,
    *,
    types: tuple[str, ...] = ITEM_TYPES + ("contacts",),
    full: bool = False,
    only_mine: bool = True,
    max_details: int = 2000,
    overlap_hours: int = 24,
    history_days: int = 0,
) -> dict:
    """The whole L0. Writes raw/, state.json and download-summary.json; returns the summary."""
    started = now_utc()
    start_ms = int(started.timestamp() * 1000)
    stats: dict = {
        "run_at": iso(started),
        "hub_id": me.get("hub_id", ""),
        "user_level": me.get("is_user_level"),
        "scopes": me.get("scopes", []),
        "types": list(types),
        "warnings": [],
    }
    if me.get("is_user_level") is None:
        stats["warnings"].append(
            "HubSpot did not say whether this app is user-level; check isUserLevel in app-hsmeta.json"
        )
    raw = raw_dir()
    raw.mkdir(parents=True, exist_ok=True)
    state = {} if full else _read_json(state_path(), {})
    marks: dict = state.get("watermarks", {})
    pending: dict = state.get("pending_details", {})
    stores = {
        o: ({} if full else _read_json(raw / f"{o}.json", {})) for o in (*OBJECTS, "companies")
    }
    fetched_at = iso(started)

    complete = True
    try:
        owner_id = find_owner(client, me, stats)
        stats["owner_id_known"] = bool(owner_id)
        apply_owner = owner_id if only_mine else ""
        if only_mine and not owner_id:
            stats["warnings"].append(
                "your owner id is unknown, so 'only mine' could not be applied: everything you "
                "can see was read, and due dates are left out of the intake"
            )
        stats["only_mine_applied"] = bool(apply_owner)
        sbk_config.safe_write_json(
            raw / "me.json",
            {k: me.get(k) for k in ("user_email", "user_id", "hub_id", "hublet", "is_user_level")}
            | {"owner_id": owner_id},
        )

        if "deals" in types:
            stages = fetch_pipelines(client, stats)
            if stages:
                sbk_config.safe_write_json(raw / "pipelines.json", stages)

        for obj in [t for t in ("contacts", *ITEM_TYPES) if t in types]:
            mark = marks.get(obj)
            if mark is not None:
                since = int(mark) - overlap_hours * 3600 * 1000
            elif history_days and history_days > 0:
                since = start_ms - history_days * 86400 * 1000
            else:
                since = None
            truncated_before = len(stats.get("search_truncated", []))
            try:
                found = search_objects(client, obj, since, apply_owner, stats)
            except (AuthError, DailyLimitReached):
                raise
            except HubSpotError as e:
                if e.status not in (400, 403):
                    raise
                # your user or the app has no access to this object: the others still run
                stats["warnings"].append(f"{obj}: HubSpot refused the search (HTTP {e.status})")
                continue
            stats[f"{obj}_found"] = len(found)
            store = stores[obj]
            todo = set(pending.get(obj, []))
            for r in found:
                rid = str(r.get("id"))
                store[rid] = _slim(r, obj, fetched_at, store.get(rid))
                if OBJECTS[obj]["assoc"]:
                    todo.add(rid)
            pending[obj] = sorted(todo)
            sbk_config.safe_write_json(raw / f"{obj}.json", store)
            if len(stats.get("search_truncated", [])) == truncated_before:
                marks[obj] = start_ms
            else:
                stats["warnings"].append(f"{obj}: search stopped at HubSpot's 10,000-result window")

        budget = max_details
        for obj in [t for t in ITEM_TYPES if t in types]:
            store = stores[obj]
            queue = list(pending.get(obj, []))
            left = []
            done = gone = failed = 0
            for n, rid in enumerate(queue):
                if budget <= 0:
                    left.append(rid)
                    continue
                budget -= 1
                try:
                    rec = fetch_detail(client, obj, rid)
                except (AuthError, DailyLimitReached):
                    # this one and every one not reached yet stay for the next run
                    pending[obj] = left + queue[n:]
                    raise
                except HubSpotError as e:
                    # kept for the next run; the record stays without its links meanwhile
                    failed += 1
                    left.append(rid)
                    stats.setdefault("detail_errors", {}).setdefault(obj, []).append(e.status)
                    continue
                if rec is None:
                    store.pop(rid, None)
                    gone += 1
                    continue
                slim = _slim(rec, obj, fetched_at, store.get(rid))
                slim["associations"] = parse_associations(rec)
                store[rid] = slim
                done += 1
            pending[obj] = left
            stats[f"{obj}_details"] = done
            stats[f"{obj}_details_failed"] = failed
            stats[f"{obj}_gone"] = gone
            stats[f"{obj}_details_left_for_next_run"] = len(left)
            sbk_config.safe_write_json(raw / f"{obj}.json", store)

        # contacts and companies linked to your items, read in batches when missing or stale
        stale = iso(started - timedelta(days=REFRESH_DAYS))
        contacts = stores["contacts"]
        want_contacts = {
            c
            for o in ITEM_TYPES
            for r in stores[o].values()
            for c in (r.get("associations") or {}).get("contacts", [])
        }
        need = sorted(
            c for c in want_contacts if (contacts.get(c) or {}).get("fetched_at", "") < stale
        )
        if need:
            for r in batch_read(client, "contacts", need, CONTACT_PROPS, stats):
                rid = str(r.get("id"))
                contacts[rid] = _slim(r, "contacts", fetched_at, contacts.get(rid))
        stats["linked_contacts_read"] = len(need)
        sbk_config.safe_write_json(raw / "contacts.json", contacts)

        companies = stores["companies"]
        want_co = {prop(c, "associatedcompanyid") for c in contacts.values()} - {""}
        want_co |= {
            c
            for o in ITEM_TYPES
            for r in stores[o].values()
            for c in (r.get("associations") or {}).get("companies", [])
        }
        need_co = sorted(
            c for c in want_co if (companies.get(c) or {}).get("fetched_at", "") < stale
        )
        if need_co:
            for r in batch_read(client, "companies", need_co, COMPANY_PROPS, stats):
                rid = str(r.get("id"))
                companies[rid] = _slim(r, "companies", fetched_at, companies.get(rid))
        stats["companies_read"] = len(need_co)
        sbk_config.safe_write_json(raw / "companies.json", companies)
    except HubSpotError as e:
        # what was read is kept; watermarks moved only for the objects read in full
        complete = False
        stats["stopped"] = str(e)
        for obj, store in stores.items():
            if store:
                sbk_config.safe_write_json(raw / f"{obj}.json", store)
        raise
    finally:
        state["watermarks"] = marks
        state["pending_details"] = pending
        state["last_run"] = iso(started)
        state["complete"] = complete
        sbk_config.safe_write_json(state_path(), state)
        stats["api_requests"] = client.requests
        stats["warnings"].extend(
            w for w in getattr(client, "warnings", []) if w not in stats["warnings"]
        )
        stats["totals"] = {o: len(s) for o, s in stores.items()}
        sbk_config.safe_write_json(summary_path(), stats)
    return stats


# --- L1 ---------------------------------------------------------------------------------


def _deal_status(d: dict, stages: dict) -> str:
    closed = prop(d, "hs_is_closed").lower()
    won = prop(d, "hs_is_closed_won").lower()
    if won == "true":
        return "done"
    if closed == "true":
        return "closed"
    st = stages.get(prop(d, "dealstage")) or {}
    if st.get("is_closed"):
        return "done" if st.get("probability") in ("1", "1.0") else "closed"
    return "open"


def _person_label(c: dict) -> str:
    name = " ".join(x for x in (prop(c, "firstname"), prop(c, "lastname")) if x).strip()
    email = prop(c, "email").lower()
    if name and email:
        return f"{name} <{email}>"
    return email or name


def _record_url(rec: dict, obj: str, hub_id: str, app_host: str) -> str:
    if rec.get("url"):
        return str(rec["url"])
    if not hub_id or not rec.get("id"):
        return ""
    return f"https://{app_host}/contacts/{hub_id}/record/{TYPE_IDS[obj]}/{rec['id']}"


def build_frames():
    """(contacts, interactions) DataFrames in the generic intake contract."""
    import pandas as pd

    raw = raw_dir()
    me = _read_json(raw / "me.json", {})
    my_email = str(me.get("user_email") or "").lower()
    my_owner = str(me.get("owner_id") or "")
    hub_id = str(me.get("hub_id") or "")
    app_host = str(cfg("app_host", DEFAULT_APP_HOST) or DEFAULT_APP_HOST)
    stages = _read_json(raw / "pipelines.json", {})
    contacts: dict = _read_json(raw / "contacts.json", {})
    companies: dict = _read_json(raw / "companies.json", {})
    items = {o: _read_json(raw / f"{o}.json", {}) for o in ITEM_TYPES}

    def is_me(c: dict) -> bool:
        return bool(my_email) and prop(c, "email").lower() == my_email

    def company_names(ids) -> list[str]:
        return [
            prop(companies[i], "name") for i in ids if i in companies and prop(companies[i], "name")
        ]

    rows: list[dict] = []
    # Only items you own count as YOUR interactions with a person: a teammate's deal or
    # note (read with --all-visible, or when your owner id is unknown) is not a contact
    # you had, so it never feeds interactions / first_seen / last_seen.
    per_contact: dict[str, list[str]] = {}

    def add(rec: dict, obj: str, row: dict, mine: bool) -> None:
        assoc = rec.get("associations") or {}
        people = [c for c in assoc.get("contacts", []) if c in contacts and not is_me(contacts[c])]
        row["participants"] = MULTI_SEP.join(
            x for x in (_person_label(contacts[c]) for c in people) if x
        )
        row["source"] = SOURCE
        row["url"] = _record_url(rec, obj, hub_id, app_host)
        rows.append(row)
        if mine:
            for c in people:
                per_contact.setdefault(c, []).append(row["ts"])

    for d in items["deals"].values():
        if d.get("archived"):
            continue
        mine = bool(my_owner) and prop(d, "hubspot_owner_id") == my_owner
        stage = stages.get(prop(d, "dealstage")) or {}
        stage_label = stage.get("label") or prop(d, "dealstage")
        amount = prop(d, "amount")
        cur = prop(d, "deal_currency_code")
        close = iso(prop(d, "closedate"))
        cos = company_names((d.get("associations") or {}).get("companies", []))
        bits = [f"stage: {stage_label}"]
        if stage.get("pipeline"):
            bits.append(f"pipeline: {stage['pipeline']}")
        if amount:
            bits.append(f"amount: {amount}{' ' + cur if cur else ''}")
        if close:
            bits.append(f"close date: {close[:10]}")
        if cos:
            bits.append("companies: " + ", ".join(cos))
        if not mine:
            bits.append("owner: " + ("someone else" if my_owner else "unknown"))
        add(
            d,
            "deals",
            {
                "ts": iso(prop(d, "createdate")) or iso(prop(d, "hs_lastmodifieddate")),
                "kind": "record",
                "title": f"Deal: {prop(d, 'dealname') or d.get('id')} ({stage_label})",
                "text": "; ".join(bits),
                "owner_role": "assignee" if mine else "other",
                "due": close if mine else "",
                "status": _deal_status(d, stages),
            },
            mine,
        )

    for t in items["tasks"].values():
        if t.get("archived"):
            continue
        mine = bool(my_owner) and prop(t, "hubspot_owner_id") == my_owner
        due = iso(prop(t, "hs_timestamp"))
        body = html_to_text(prop(t, "hs_task_body"))
        extra = []
        if prop(t, "hs_task_priority"):
            extra.append(f"priority: {prop(t, 'hs_task_priority')}")
        if due and not mine:
            extra.append(f"due: {due[:10]}")
        add(
            t,
            "tasks",
            {
                "ts": iso(prop(t, "hs_createdate")) or iso(prop(t, "hs_lastmodifieddate")) or due,
                "kind": "issue",
                "title": prop(t, "hs_task_subject") or f"Task {t.get('id')}",
                "text": "\n".join(x for x in (body, "; ".join(extra)) if x),
                "owner_role": "assignee" if mine else "other",
                "due": due if mine else "",
                "status": "done" if prop(t, "hs_task_status").upper() == "COMPLETED" else "open",
            },
            mine,
        )

    for n in items["notes"].values():
        if n.get("archived"):
            continue
        mine = bool(my_owner) and prop(n, "hubspot_owner_id") == my_owner
        text = html_to_text(prop(n, "hs_note_body"))
        first = text.splitlines()[0] if text else ""
        add(
            n,
            "notes",
            {
                "ts": iso(prop(n, "hs_timestamp")) or iso(prop(n, "hs_createdate")),
                "kind": "message",
                "title": "Note: " + (first[:80] if first else str(n.get("id"))),
                "text": text,
                "owner_role": "author" if mine else "other",
                "due": "",
                "status": "done",
            },
            mine,
        )

    out_contacts: list[dict] = []
    for cid, c in contacts.items():
        if c.get("archived") or is_me(c):
            continue
        name = " ".join(x for x in (prop(c, "firstname"), prop(c, "lastname")) if x).strip()
        email = prop(c, "email").lower()
        phone = prop(c, "phone") or prop(c, "mobilephone")
        if not (name or email or phone):
            continue
        company = prop(c, "company")
        co_id = prop(c, "associatedcompanyid")
        if not company and co_id in companies:
            company = prop(companies[co_id], "name")
        # first_seen / last_seen are YOUR interactions only (contract in plugin_intake.py).
        # The record's createdate (when someone added it to the CRM) and
        # notes_last_contacted (the last activity logged by anyone on the team) are not,
        # so they are not used: they would become a false "first contact" in the KB.
        stamps = sorted(x for x in per_contact.get(cid, []) if x)
        first_seen = stamps[0] if stamps else ""
        last_seen = stamps[-1] if stamps else ""
        out_contacts.append(
            {
                "source": SOURCE,
                "name": name,
                "email": email,
                "phone": phone,
                "company": company,
                "title": prop(c, "jobtitle"),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "interactions": len(per_contact.get(cid, [])),
                "url": _record_url(c, "contacts", hub_id, app_host),
            }
        )

    cdf = pd.DataFrame(out_contacts, columns=CONTACT_COLUMNS)
    cdf["interactions"] = cdf["interactions"].astype("int64")
    idf = pd.DataFrame(rows, columns=INTERACTION_COLUMNS)
    if not idf.empty:
        idf = idf.sort_values("ts", kind="stable").reset_index(drop=True)
    return cdf, idf


def write_frames() -> dict:
    cdf, idf = build_frames()
    sbk_config.safe_write_parquet(cdf, contacts_path(), index=False)
    sbk_config.safe_write_parquet(idf, interactions_path(), index=False)
    by_kind = idf["kind"].value_counts().to_dict() if not idf.empty else {}
    return {
        "contacts": len(cdf),
        "interactions": len(idf),
        **{f"kind_{k}": int(v) for k, v in by_kind.items()},
    }
