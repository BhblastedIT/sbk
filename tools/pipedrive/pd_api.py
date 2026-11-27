#!/usr/bin/env python3
"""Pipedrive plugin, shared code for pd-l0-auth.py, pd-l0-download.py and pd-l1-enrich.py.

Personal access only: your own personal API token, or an OAuth app you registered
yourself (a private app in your own Developer Hub) with read-only scopes. The data
client below has one method, GET, and sends your credential only to *.pipedrive.com
over https (a test checks both). The one POST in the plugin is the OAuth token call
to oauth.pipedrive.com, in pd_oauth.py.

What it reads, as the user who owns the credential (what that user can see):
  * you: GET /v1/users/me (your user id, email, company name and domain);
  * organizations, persons, deals (archived ones too, unless turned off) and
    activities: GET /api/v2/<entity>, cursor pagination, `updated_since`;
  * notes: GET /api/v1/notes (no v2 yet), offset pagination, `updated_since`;
  * deals deleted in the last 30 days: GET /api/v2/deals?status=deleted, to drop them.

Vendor facts this code relies on (checked on Pipedrive's docs, 2026-11-25; URLs in
tools/pipedrive/README.md):
  * API token in the `x-api-token` header; OAuth access token as `Authorization:
    Bearer`; base https://api.pipedrive.com or https://{company}.pipedrive.com, the
    company domain from GET /v1/users/me (`company_domain`) or from OAuth `api_domain`;
  * v2 list endpoints: `cursor` + `limit` (max 500), `additional_data.next_cursor`,
    `updated_since` in RFC 3339, `sort_by=update_time`; v1 notes: `start` + `limit`,
    `additional_data.pagination.more_items_in_collection` / `next_start`;
  * token-based rate limiting: one daily budget for the whole company (all users,
    API tokens and OAuth alike), 429 when it is used up until midnight server time;
    x-token-cost 10 for each v2 list page, 20 for /v1/notes, 2 for /v1/users/me;
  * burst limit per token on a rolling 2-second window (API token: 20 on Lite up
    to 120 on Ultimate), headers x-ratelimit-limit / -remaining / -reset; clients
    that keep calling after 429 get a Cloudflare 403;
  * all times are UTC; 401 invalid token, 402 company account not open.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("pd")

SOURCE_ID = "pipedrive"
ROOT_API = "https://api.pipedrive.com"
USER_AGENT = "sbk-pipedrive-plugin"

KEYCHAIN_SERVICE = "sbk-pipedrive"
ACC_API_TOKEN = "api-token"
ACC_CLIENT_ID = "client-id"
ACC_CLIENT_SECRET = "client-secret"
ACC_REFRESH = "refresh-token"

ENV_API_TOKEN = "PIPEDRIVE_API_TOKEN"
ENV_CLIENT_ID = "PIPEDRIVE_CLIENT_ID"
ENV_CLIENT_SECRET = "PIPEDRIVE_CLIENT_SECRET"
ENV_REFRESH = "PIPEDRIVE_REFRESH_TOKEN"
ENV_TOKEN_FILE = "PIPEDRIVE_TOKEN_FILE"

SETUP_HINT = "see docs/CONNECTING.md#pipedrive"
NO_CREDENTIALS_MSG = (
    "pipedrive: no credentials found (Keychain sbk-pipedrive/api-token or PIPEDRIVE_API_TOKEN "
    f"in .env; or an OAuth login made with pd-l0-auth.py); {SETUP_HINT}"
)

#: Data paths (own module, not sbk_config). Read at call time so tests and
#: SBK_DATA_ROOT changes are honoured.
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
STATE_FILE = "state.json"
SUMMARY_FILE = "download-summary.json"
CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

#: (entity, API version, path). Order matters: organizations and persons first so a
#: run stopped by the request cap still has the names the later entities point to.
ENTITIES: tuple[tuple[str, str, str], ...] = (
    ("organizations", "v2", "/organizations"),
    ("persons", "v2", "/persons"),
    ("deals", "v2", "/deals"),
    ("deals_archived", "v2", "/deals/archived"),
    ("activities", "v2", "/activities"),
    ("notes", "v1", "/notes"),
)
#: Where each entity is stored: archived deals share the deals store.
STORE_OF = {"deals_archived": "deals"}
STEP_CHOICES = ("organizations", "persons", "deals", "activities", "notes")

#: x-token-cost in Pipedrive's OpenAPI specs (v2: developers.pipedrive.com/docs/api/v1/openapi-v2.yaml,
#: v1: .../openapi.yaml), used only to report an estimate in download-summary.json.
#: GET /api/v2/deals/archived costs 20, the other v2 lists 10.
TOKEN_COST = {"v2_list": 10, "v2_deals_archived": 20, "v1_notes": 20, "v1_users_me": 2}

PAGE_LIMIT = 500  # documented maximum for both pagination styles
#: Offset pages (v1 notes) restart this many records before `next_start`: a note
#: edited or deleted while the run pages through them shifts the list, and without
#: the overlap the record at the page boundary would be skipped. Records are keyed
#: by id, so reading one twice is harmless.
OFFSET_OVERLAP = 10
#: One request every 0.2 s = 10 per 2 seconds, half the lowest documented burst
#: limit for an API token (Lite: 20 per 2 seconds).
REQUEST_DELAY = 0.2
MAX_RETRIES = 5
MAX_WAIT_S = 120
OVERLAP = timedelta(hours=1)  # incremental runs re-read one hour before the last run
TEXT_MAX = 4000

_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)?pipedrive\.com$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


# --------------------------------------------------------------------------- paths


def pd_dir() -> Path:
    return Path(cfg.DATA_ROOT) / SOURCE_ID


def setting(key: str, default):
    """A value of the sbk.config.json "pipedrive" section (missing/empty = default)."""
    return cfg.user_cfg(f"{SOURCE_ID}.{key}", default)


# --------------------------------------------------------------------------- errors


class PipedriveError(RuntimeError):
    def __init__(self, status: int, where: str, message: str = ""):
        self.status = status
        self.where = where
        super().__init__(f"HTTP {status} on {where}: {message[:200]}")


class NoCredentials(RuntimeError):
    pass


class RateLimited(PipedriveError):
    """Still 429 after the retries: the burst window, or the company's daily budget."""


class RequestCap(RuntimeError):
    """The run reached `max_requests_per_run`: stop and keep what was read."""


# --------------------------------------------------------------------------- credentials


def _secret(account: str) -> str:
    try:
        from secrets_adapter import get_secret

        return (get_secret(KEYCHAIN_SERVICE, account) or "").strip()
    except Exception as exc:  # noqa: BLE001 - keyring missing or locked: counts as "not set"
        log.debug("keychain lookup failed: %s", exc)
        return ""


def _lookup(account: str, env: str) -> tuple[str, str]:
    """(value, where) from the Keychain first, then the environment; ("", "") if neither."""
    v = _secret(account)
    if v:
        return v, f"keychain {KEYCHAIN_SERVICE}/{account}"
    v = (os.environ.get(env) or "").strip()
    if v:
        return v, f"env {env}"
    return "", ""


def client_id() -> tuple[str, str]:
    """Client ID of your own private app: Keychain, env, then sbk.config.json (not a secret)."""
    v, where = _lookup(ACC_CLIENT_ID, ENV_CLIENT_ID)
    if v:
        return v, where
    v = str(setting("client_id", "") or "").strip()
    return (v, "sbk.config.json pipedrive.client_id") if v else ("", "")


def client_secret() -> tuple[str, str]:
    return _lookup(ACC_CLIENT_SECRET, ENV_CLIENT_SECRET)


def _token_file() -> Path | None:
    p = (os.environ.get(ENV_TOKEN_FILE) or "").strip()
    return Path(p).expanduser() if p else None


def load_refresh_token() -> tuple[str, str]:
    v = _secret(ACC_REFRESH)
    if v:
        return v, f"keychain {KEYCHAIN_SERVICE}/{ACC_REFRESH}"
    tf = _token_file()
    if tf and tf.is_file():
        v = tf.read_text(encoding="utf-8").strip()
        if v:
            return v, f"file {ENV_TOKEN_FILE}"
    v = (os.environ.get(ENV_REFRESH) or "").strip()
    return (v, f"env {ENV_REFRESH}") if v else ("", "")


def save_refresh_token(token: str) -> str:
    """Store the refresh token; '' when there is nowhere to store it (container mode)."""
    tf = _token_file()
    if tf:
        tf.parent.mkdir(parents=True, exist_ok=True)
        tf.write_text(token, encoding="utf-8")
        os.chmod(tf, 0o600)
        return f"file {ENV_TOKEN_FILE}"
    if os.environ.get("SBK_CONTAINERIZED", "0") == "1":
        return ""
    from secrets_adapter import set_secret

    set_secret(KEYCHAIN_SERVICE, ACC_REFRESH, token)
    return f"keychain {KEYCHAIN_SERVICE}/{ACC_REFRESH}"


class Auth:
    """Which credential this run uses. Never printed: only `kind` and `where` are."""

    def __init__(self, kind: str, where: str, token: str = "", oauth: dict | None = None):
        self.kind = kind  # "api_token" | "oauth"
        self.where = where
        self.token = token  # api token, or the current OAuth access token
        self.oauth = oauth or {}  # client_id, client_secret, refresh_token, api_domain

    def headers(self) -> dict:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.kind == "api_token":
            h["x-api-token"] = self.token
        else:
            h["Authorization"] = f"Bearer {self.token}"
        return h


def resolve_auth(mode: str | None = None) -> Auth:
    """The credential to use. mode: auto (API token first, then OAuth) | api_token | oauth."""
    mode = (mode or str(setting("auth", "auto") or "auto")).strip().lower()
    if mode not in ("auto", "api_token", "oauth"):
        mode = "auto"
    if mode in ("auto", "api_token"):
        tok, where = _lookup(ACC_API_TOKEN, ENV_API_TOKEN)
        if tok:
            return Auth("api_token", where, token=tok)
        if mode == "api_token":
            raise NoCredentials(NO_CREDENTIALS_MSG)
    refresh, r_where = load_refresh_token()
    cid, _ = client_id()
    secret, _ = client_secret()
    if refresh and cid and secret:
        return Auth(
            "oauth",
            f"OAuth app, refresh token from {r_where}",
            oauth={"client_id": cid, "client_secret": secret, "refresh_token": refresh},
        )
    raise NoCredentials(NO_CREDENTIALS_MSG)


# --------------------------------------------------------------------------- helpers


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value) -> str:
    """Pipedrive time ('2026-01-02T03:04:05Z', '2026-01-02 03:04:05', a date) -> ISO 8601, '' if empty.

    Pipedrive sends every time in UTC, so a value without a zone gets +00:00; a
    bare date stays a date.
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    s = str(value).strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    s = s.replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if not re.search(r"[+-]\d{2}:\d{2}$", s):
        s += "+00:00"
    return s


def rfc3339(dt: datetime) -> str:
    """The `updated_since` format Pipedrive documents: 2025-01-01T10:20:00Z."""
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime | None:
    s = iso(value)
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"(?i)<\s*(br|/p|/div|/li)\s*/?>")


def strip_html(text, n: int = TEXT_MAX) -> str:
    """Notes come as HTML: plain text, entities decoded, whitespace folded."""
    if not text:
        return ""
    s = _BLOCK.sub("\n", str(text))
    s = html.unescape(_TAG.sub("", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s[:n]


def check_url(url: str) -> None:
    """The credential goes only to https://*.pipedrive.com."""
    u = urlparse(url)
    if u.scheme != "https" or not _HOST_RE.match((u.hostname or "").lower()):
        raise PipedriveError(0, url, "refusing to send the credential outside *.pipedrive.com")


def company_base(domain: str) -> str:
    """https://<company>.pipedrive.com for a valid company domain, else the shared host."""
    d = str(domain or "").strip().lower()
    return f"https://{d}.pipedrive.com" if _DOMAIN_RE.match(d) else ROOT_API


# --------------------------------------------------------------------------- client


class Client:
    """GET-only Pipedrive client: pacing, 429 back-off, both pagination styles, request cap."""

    def __init__(
        self,
        auth: Auth,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        delay: float = REQUEST_DELAY,
        max_retries: int = MAX_RETRIES,
        max_requests: int | None = None,
        refresher: Callable[[], str] | None = None,
    ):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.auth = auth
        self._sleep = sleep
        self._clock = clock
        self._delay = delay
        self.max_retries = max_retries
        self.max_requests = max_requests
        self._refresher = refresher  # () -> new OAuth access token
        self._last = None
        self.calls = 0
        self.tokens_estimate = 0
        self.base = ROOT_API
        self.burst_limit: str | None = None
        self.server_date: str | None = None

    def _pace(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._delay:
            self._sleep(self._delay - (now - self._last))
        self._last = self._clock()

    # The only HTTP verb of the data client.
    def get(self, url: str, params: dict | None = None, cost: int = 0):
        check_url(url)
        attempt = 0
        refreshed = False
        while True:
            if self.max_requests is not None and self.calls >= self.max_requests:
                raise RequestCap(f"request cap of {self.max_requests} reached")
            self._pace()
            self.calls += 1
            try:
                resp = self.session.get(url, params=params, headers=self.auth.headers(), timeout=60)
            except Exception as exc:  # noqa: BLE001 - network error: back off and retry
                attempt += 1
                if attempt > self.max_retries:
                    raise PipedriveError(0, _path(url), f"network: {type(exc).__name__}") from None
                self._sleep(min(2**attempt, MAX_WAIT_S))
                continue
            h = resp.headers
            if h.get("x-ratelimit-limit") is not None:
                self.burst_limit = h.get("x-ratelimit-limit")
            if self.server_date is None and h.get("date"):
                self.server_date = h.get("date")
            code = resp.status_code
            if 200 <= code < 300:
                self.tokens_estimate += cost
                try:
                    data = resp.json() if resp.content else {}
                except ValueError:
                    raise PipedriveError(code, _path(url), "answer is not JSON") from None
                if isinstance(data, dict) and data.get("success") is False:
                    raise PipedriveError(
                        code, _path(url), str(data.get("error") or "success=false")
                    )
                return data
            body = (resp.text or "")[:300]
            if code == 401 and self.auth.kind == "oauth" and self._refresher and not refreshed:
                self.auth.token = self._refresher()  # access tokens live 60 minutes
                refreshed = True
                continue
            if code == 429:
                attempt += 1
                if attempt > self.max_retries:
                    raise RateLimited(429, _path(url), "still rate limited after retries")
                wait = _wait_seconds(h, attempt)
                log.warning("rate limited (HTTP 429), waiting %ss", int(wait))
                self._sleep(wait)
                continue
            if code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    raise PipedriveError(code, _path(url), body)
                self._sleep(min(2**attempt, MAX_WAIT_S))
                continue
            raise PipedriveError(code, _path(url), _short_body(body))

    def cursor_pages(self, url: str, params: dict | None = None, cost: int = 0):
        """v2 lists: yields each page's `data`; `cursor` from additional_data.next_cursor."""
        p = {"limit": PAGE_LIMIT, **(params or {})}
        while True:
            data = self.get(url, p, cost)
            yield list(data.get("data") or [])
            nxt = (data.get("additional_data") or {}).get("next_cursor")
            if not nxt:
                return
            p = {**p, "cursor": nxt}

    def offset_pages(self, url: str, params: dict | None = None, cost: int = 0):
        """v1 lists: yields each page's `data`; `start` from additional_data.pagination.next_start."""
        p = {"limit": PAGE_LIMIT, "start": 0, **(params or {})}
        while True:
            data = self.get(url, p, cost)
            yield list(data.get("data") or [])
            pag = (data.get("additional_data") or {}).get("pagination") or {}
            if not pag.get("more_items_in_collection"):
                return
            nxt = pag.get("next_start")
            if nxt is None or int(nxt) <= int(p["start"]):
                return
            # step back a little so a shift of the list cannot skip a record
            back = int(nxt) - OFFSET_OVERLAP
            p = {**p, "start": back if back > int(p["start"]) else int(nxt)}


def server_time(date_header: str | None) -> datetime | None:
    if not date_header:
        return None
    try:
        from email.utils import parsedate_to_datetime

        d = parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError):
        return None
    return d.astimezone(UTC) if d and d.tzinfo else None


def _path(url: str) -> str:
    return urlparse(url).path or url


def _short_body(body: str) -> str:
    # A Cloudflare block is an HTML page: say what it is instead of dumping it.
    if body.lstrip().startswith("<"):
        return "HTML error page (access blocked or service error)"
    return body


def _wait_seconds(h, attempt: int) -> float:
    for key in ("retry-after", "x-ratelimit-reset"):
        v = h.get(key)
        if v:
            try:
                return max(1.0, min(float(v), MAX_WAIT_S))
            except ValueError:
                pass
    return float(min(2 * (2 ** (attempt - 1)), MAX_WAIT_S))


# --------------------------------------------------------------------------- slim records


def _ids(items) -> list:
    return [x for x in (items or []) if x is not None]


def _values(items) -> list[dict]:
    out = []
    for it in items or []:
        if isinstance(it, dict) and str(it.get("value") or "").strip():
            out.append({"value": str(it["value"]).strip(), "primary": bool(it.get("primary"))})
        elif isinstance(it, str) and it.strip():
            out.append({"value": it.strip(), "primary": False})
    return out


def slim(entity: str, r: dict) -> dict:
    """Only the fields the L1 needs. Left out on purpose: custom fields, contact-sync
    notes, birthdays, postal addresses, conference links (they can carry passcodes)."""
    common = {
        "id": r.get("id"),
        "owner_id": r.get("owner_id"),
        "add_time": r.get("add_time") or "",
        "update_time": r.get("update_time") or "",
    }
    if entity == "organizations":
        return {**common, "name": r.get("name") or ""}
    if entity == "persons":
        return {
            **common,
            "name": r.get("name") or "",
            "first_name": r.get("first_name") or "",
            "last_name": r.get("last_name") or "",
            "org_id": r.get("org_id"),
            "emails": _values(r.get("emails") or r.get("email")),
            "phones": _values(r.get("phones") or r.get("phone")),
            "job_title": r.get("job_title") or "",
        }
    if entity in ("deals", "deals_archived"):
        return {
            **common,
            "title": r.get("title") or "",
            "creator_user_id": r.get("creator_user_id"),
            "person_id": r.get("person_id"),
            "org_id": r.get("org_id"),
            "status": r.get("status") or "",
            "value": r.get("value"),
            "currency": r.get("currency") or "",
            "expected_close_date": r.get("expected_close_date") or "",
            "close_time": r.get("close_time") or "",
            "won_time": r.get("won_time") or "",
            "lost_time": r.get("lost_time") or "",
            "lost_reason": r.get("lost_reason") or "",
            "is_archived": bool(r.get("is_archived")) or entity == "deals_archived",
        }
    if entity == "activities":
        return {
            **common,
            "subject": r.get("subject") or "",
            "type": r.get("type") or "",
            "creator_user_id": r.get("creator_user_id"),
            "deal_id": r.get("deal_id"),
            "person_id": r.get("person_id"),
            "org_id": r.get("org_id"),
            "due_date": r.get("due_date") or "",
            "due_time": r.get("due_time") or "",
            "duration": r.get("duration") or "",
            "done": bool(r.get("done")),
            "marked_as_done_time": r.get("marked_as_done_time") or "",
            "participants": _ids(
                p.get("person_id") for p in (r.get("participants") or []) if isinstance(p, dict)
            ),
            "attendees": [
                {
                    "email": (a.get("email") or "").strip(),
                    "name": (a.get("name") or "").strip(),
                    "user_id": a.get("user_id"),
                    "person_id": a.get("person_id"),
                    "is_organizer": bool(a.get("is_organizer")),
                }
                for a in (r.get("attendees") or [])
                if isinstance(a, dict)
            ],
            "note": strip_html(r.get("note")),
            "public_description": strip_html(r.get("public_description")),
        }
    if entity == "notes":
        return {
            "id": r.get("id"),
            "user_id": r.get("user_id"),
            "deal_id": r.get("deal_id"),
            "person_id": r.get("person_id"),
            "org_id": r.get("org_id"),
            "add_time": r.get("add_time") or "",
            "update_time": r.get("update_time") or "",
            "content": strip_html(r.get("content")),
        }
    return common


# --------------------------------------------------------------------------- L0


def fetch_me(client: Client, api_domain: str = "") -> dict:
    """GET /v1/users/me, then point the client at your company domain."""
    base = api_domain.rstrip("/") if api_domain else ROOT_API
    data = client.get(
        f"{base}/v1/users/me" if base == ROOT_API else f"{base}/api/v1/users/me",
        cost=TOKEN_COST["v1_users_me"],
    )
    d = (data or {}).get("data") or {}
    me = {
        "id": d.get("id"),
        "name": d.get("name") or "",
        "email": (d.get("email") or "").strip().lower(),
        "company_id": d.get("company_id"),
        "company_name": d.get("company_name") or "",
        "company_domain": d.get("company_domain") or "",
    }
    if me["id"] is None:
        raise PipedriveError(0, "/v1/users/me", "no user id in the response")
    client.base = company_base(me["company_domain"]) if not api_domain else base
    return me


def _url(client: Client, version: str, path: str) -> str:
    return f"{client.base}/api/{version}{path}"


def _remove_deleted(store: dict, rec: dict) -> bool:
    if rec.get("is_deleted") or rec.get("active_flag") is False:
        store.pop(str(rec.get("id")), None)
        return True
    return False


def fetch_entity(
    client: Client,
    entity: str,
    version: str,
    path: str,
    store: dict,
    since: str | None,
    stats: dict,
    seen: set | None = None,
) -> str:
    """Reads one entity into `store` (id -> slim record). Returns the newest update_time seen.

    `seen`, when given, collects the ids Pipedrive still lists (used by --full to drop
    the local records of what was deleted).
    """
    params: dict = {}
    if since:
        params["updated_since"] = since
    newest = ""
    read = new = 0
    if version == "v2":
        params.update(sort_by="update_time", sort_direction="asc")
        if entity == "activities":
            params["include_fields"] = "attendees"
        cost = TOKEN_COST["v2_deals_archived" if entity == "deals_archived" else "v2_list"]
        pages = client.cursor_pages(_url(client, "v2", path), params, cost)
    else:
        params["sort"] = "update_time ASC"
        pages = client.offset_pages(_url(client, "v1", path), params, TOKEN_COST["v1_notes"])
    try:
        for page in pages:
            for rec in page:
                if not isinstance(rec, dict) or rec.get("id") is None:
                    continue
                read += 1
                if _remove_deleted(store, rec):
                    continue
                key = str(rec["id"])
                if seen is not None:
                    seen.add(key)
                new += key not in store
                store[key] = slim(entity, rec)
                upd = iso(rec.get("update_time"))
                newest = max(newest, upd)
    finally:
        stats[f"{entity}_read"] = read
        stats[f"{entity}_new"] = new
        stats[f"{entity}_newest"] = newest
    return newest


def fetch_deleted_deals(client: Client, store: dict, stats: dict) -> None:
    """Deals deleted in the last 30 days (Pipedrive keeps them that long) leave the store."""
    gone = 0
    for page in client.cursor_pages(
        _url(client, "v2", "/deals"), {"status": "deleted"}, TOKEN_COST["v2_list"]
    ):
        for rec in page:
            if isinstance(rec, dict) and store.pop(str(rec.get("id")), None) is not None:
                gone += 1
    stats["deals_deleted_removed"] = gone


def run_download(
    client: Client,
    dest: Path,
    *,
    steps: tuple[str, ...] = STEP_CHOICES,
    full: bool = False,
    since_days: int | None = None,
    include_archived_deals: bool = True,
    api_domain: str = "",
) -> dict:
    """The whole L0. Writes under `dest`, returns the summary it also writes.

    Incremental by update_time: each entity keeps its own watermark in state.json
    (the start of the last complete pass); the next run asks for `updated_since`
    one hour before it. A pass stopped by the request cap or a rate limit keeps the
    newest update_time it read as its watermark (pages are sorted by update_time
    ascending), so the next run continues from there.

    Deletions: an incremental list never shows a deleted record. Deals deleted in
    the last 30 days are dropped on each incremental run (status=deleted); with
    `full`, every store whose passes all completed keeps only the ids Pipedrive
    listed, so deleted persons, organizations, activities and notes leave too. A
    `full` run stopped early prunes only the stores it read to the end.
    """
    started = now_utc()
    stats: dict = {"run_at": iso(started), "steps": list(steps), "complete": True}
    raw = dest / RAW_DIR
    state = _read_json(dest / STATE_FILE, {})
    watermarks: dict = state.setdefault("watermarks", {})

    me = fetch_me(client, api_domain)
    # watermarks use Pipedrive's clock (Date header of the first answer) when it is there,
    # so a wrong local clock cannot skip updates
    started = server_time(client.server_date) or started
    cfg.safe_write_json(raw / "me.json", me)
    stats["user_id"], stats["company"] = me["id"], me["company_name"]

    stores: dict[str, dict] = {}
    listed: dict[str, set] = {}  # --full only: store name -> ids Pipedrive still lists
    cut: set[str] = set()  # stores whose pass was stopped early: never pruned
    stop: Exception | None = None
    for entity, version, path in ENTITIES:
        step = "deals" if entity == "deals_archived" else entity
        if step not in steps:
            continue
        if entity == "deals_archived" and not include_archived_deals:
            continue
        name = STORE_OF.get(entity, entity)
        store_path = raw / f"{name}.json"
        store = stores.setdefault(name, _read_json(store_path, {}))
        mark = None if full else watermarks.get(entity)
        if mark:
            since_dt = parse_iso(mark)
            since = rfc3339(since_dt - OVERLAP) if since_dt else None
        elif since_days and not full:
            since = rfc3339(started - timedelta(days=int(since_days)))
        else:
            since = None
        stats[f"{entity}_since"] = since or "(everything)"
        try:
            seen = listed.setdefault(name, set()) if full else None
            fetch_entity(client, entity, version, path, store, since, stats, seen)
            watermarks[entity] = iso(started)
        except (RequestCap, RateLimited) as e:
            stop = e
            cut.add(name)
            # pages come sorted by update_time ascending: everything up to the newest
            # record read in this pass is in, so the next run continues from there
            newest = stats.get(f"{entity}_newest", "")
            if newest and (not mark or newest > mark):
                watermarks[entity] = newest
            stats["complete"] = False
            stats["stopped_at"] = entity
            stats["stopped_because"] = (
                "request cap (max_requests_per_run)" if isinstance(e, RequestCap) else "rate limit"
            )
        finally:
            cfg.safe_write_json(store_path, store)
        if stop is not None:
            break
        if entity == "deals" and not full and watermarks.get("deals_deleted_checked"):
            try:
                fetch_deleted_deals(client, store, stats)
                cfg.safe_write_json(store_path, store)
            except (RequestCap, RateLimited) as e:
                stop = e
                stats["complete"] = False
                stats["stopped_at"] = "deals_deleted"
                stats["stopped_because"] = (
                    "request cap (max_requests_per_run)"
                    if isinstance(e, RequestCap)
                    else "rate limit"
                )
                break
        if entity == "deals":
            watermarks["deals_deleted_checked"] = iso(started)

    if full:
        # these stores read their whole list: what is not listed was deleted
        for name, ids in listed.items():
            if name in cut:
                continue
            store = stores[name]
            gone = [k for k in store if k not in ids]
            for k in gone:
                del store[k]
            stats[f"{name}_pruned"] = len(gone)
            if gone:
                cfg.safe_write_json(raw / f"{name}.json", store)

    for name in ("organizations", "persons", "deals", "activities", "notes"):
        p = raw / f"{name}.json"
        stats[f"{name}_total"] = len(stores[name]) if name in stores else len(_read_json(p, {}))

    state["last_run"] = iso(started)
    cfg.safe_write_json(dest / STATE_FILE, state)
    stats["api_calls"] = client.calls
    stats["api_tokens_estimate"] = client.tokens_estimate
    stats["burst_limit_per_2s"] = client.burst_limit
    cfg.safe_write_json(dest / SUMMARY_FILE, stats)
    if isinstance(stop, RateLimited):
        raise stop
    return stats


# --------------------------------------------------------------------------- L1

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

#: Activity type key -> intake kind. Custom types and the rest become "record".
ACTIVITY_KIND = {"meeting": "meeting", "lunch": "meeting", "call": "meeting", "email": "message"}

#: Deal status -> intake status (the kernel's closed set is done/closed/merged/cancelled...).
DEAL_STATUS = {"open": "open", "won": "done", "lost": "closed"}


def _primary(values: list[dict]) -> str:
    for v in values or []:
        if v.get("primary"):
            return v.get("value", "")
    return (values[0].get("value", "") if values else "") or ""


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def build_frames(dest: Path, scope: str = "mine"):
    """(contacts, interactions) DataFrames in the generic intake contract.

    scope "mine": deals you own or created, activities you own, created or attend,
    notes you wrote, and the persons you own or that appear in those. scope "all":
    everything the download saw.
    """
    import pandas as pd

    raw = dest / RAW_DIR
    me = _read_json(raw / "me.json", {}) or {}
    me_id, me_email = me.get("id"), (me.get("email") or "").lower()
    web = company_base(me.get("company_domain", "")) if me.get("company_domain") else ""
    orgs: dict = _read_json(raw / "organizations.json", {})
    persons: dict = _read_json(raw / "persons.json", {})
    deals: dict = _read_json(raw / "deals.json", {})
    acts: dict = _read_json(raw / "activities.json", {})
    notes: dict = _read_json(raw / "notes.json", {})
    everything = scope == "all"

    def link(kind: str, rid) -> str:
        return f"{web}/{kind}/{rid}" if web and rid is not None else ""

    def person_ref(pid) -> tuple[str, str]:
        """(participant string, person key) for a person id, ('', '') if unknown or you."""
        p = persons.get(str(pid)) if pid is not None else None
        if not p:
            return "", ""
        email = _primary(p.get("emails", [])).lower()
        if email and email == me_email:
            return "", ""
        name = (p.get("name") or "").strip()
        if name and email:
            return f"{name} <{email}>", str(pid)
        return (name or email), str(pid)

    def org_name(oid) -> str:
        o = orgs.get(str(oid)) if oid is not None else None
        return (o or {}).get("name", "") if o else ""

    rows: list[dict] = []
    touched: dict[str, list[str]] = {}

    def add(row: dict, people: list[tuple[str, str]]) -> None:
        seen, keys, parts = set(), set(), []
        for ref, key in people:
            if ref and ref not in seen:
                seen.add(ref)
                parts.append(ref)
            if key and key not in keys:
                keys.add(key)
                touched.setdefault(key, []).append(row["ts"])
        row.update(source=SOURCE_ID, participants="|||".join(parts))
        rows.append(row)

    # deals
    for d in deals.values():
        if _same(d.get("owner_id"), me_id):
            role = "assignee"
        elif _same(d.get("creator_user_id"), me_id):
            role = "author"
        else:
            role = "other"
        if role == "other" and not everything:
            continue
        status_raw = (d.get("status") or "open").lower()
        if status_raw == "deleted":
            continue
        status = DEAL_STATUS.get(status_raw, "open")
        closed_at = d.get("won_time") or d.get("lost_time") or d.get("close_time")
        ts = iso(closed_at) if status != "open" and closed_at else iso(d.get("add_time"))
        suffix = {"won": " (won)", "lost": " (lost)"}.get(status_raw, "")
        bits = [f"status {status_raw}"]
        if d.get("value") not in (None, ""):
            bits.append(f"value {d.get('value')} {d.get('currency', '')}".strip())
        if org_name(d.get("org_id")):
            bits.append(f"organization {org_name(d.get('org_id'))}")
        if d.get("expected_close_date"):
            bits.append(f"expected close {d['expected_close_date']}")
        if d.get("lost_reason"):
            bits.append(f"lost reason {d['lost_reason']}")
        if d.get("is_archived"):
            bits.append("archived")
        add(
            {
                "ts": ts,
                "kind": "record",
                "title": f"Deal: {d.get('title', '')}{suffix}".strip(),
                "text": "; ".join(bits),
                "owner_role": role,
                # a due date only on your own open deals: a colleague's deal is not your commitment
                "due": iso(d.get("expected_close_date"))
                if role == "assignee" and status == "open"
                else "",
                "url": link("deal", d.get("id")),
                "status": status,
            },
            [person_ref(d.get("person_id"))],
        )

    # activities
    for a in acts.values():
        att = a.get("attendees") or []
        mine_att = [
            x
            for x in att
            if _same(x.get("user_id"), me_id)
            or (me_email and x.get("email", "").lower() == me_email)
        ]
        if _same(a.get("owner_id"), me_id):
            role = "assignee"
        elif mine_att and any(x.get("is_organizer") for x in mine_att):
            role = "organizer"
        elif mine_att:
            role = "attendee"
        elif _same(a.get("creator_user_id"), me_id):
            role = "author"
        else:
            role = "other"
        if role == "other" and not everything:
            continue
        due_date, due_time = a.get("due_date") or "", a.get("due_time") or ""
        when = iso(f"{due_date}T{due_time}") if due_date and due_time else iso(due_date)
        ts = when or iso(a.get("add_time"))
        done = bool(a.get("done"))
        typ = (a.get("type") or "").strip()
        people = [person_ref(pid) for pid in (a.get("participants") or [])]
        if not a.get("participants"):
            people.append(person_ref(a.get("person_id")))
        for x in att:
            if x in mine_att:
                continue
            if x.get("person_id") is not None and str(x.get("person_id")) in persons:
                people.append(person_ref(x.get("person_id")))
                continue
            name, email = x.get("name", ""), x.get("email", "").lower()
            ref = f"{name} <{email}>" if name and email else (name or email)
            people.append((ref, ""))
        text = "\n".join(t for t in (a.get("note", ""), a.get("public_description", "")) if t)
        anchor = (
            link("deal", a.get("deal_id"))
            if a.get("deal_id") is not None
            else link("person", a.get("person_id"))
            if a.get("person_id") is not None
            else link("organization", a.get("org_id"))
            if a.get("org_id") is not None
            else web
        )
        add(
            {
                "ts": ts,
                "kind": ACTIVITY_KIND.get(typ.lower(), "record"),
                "title": (a.get("subject") or typ or "Activity").strip(),
                "text": text[:TEXT_MAX],
                "owner_role": role,
                "due": when if role == "assignee" else "",
                "url": f"{anchor}#activity-{a.get('id')}" if anchor else "",
                "status": "done" if done else "open",
            },
            people,
        )

    # notes
    for n in notes.values():
        role = "author" if _same(n.get("user_id"), me_id) else "other"
        if role == "other" and not everything:
            continue
        deal = deals.get(str(n.get("deal_id"))) if n.get("deal_id") is not None else None
        about = (
            (deal or {}).get("title")
            or (persons.get(str(n.get("person_id"))) or {}).get("name")
            or org_name(n.get("org_id"))
            or ""
        )
        people = [person_ref(n.get("person_id"))]
        if deal and deal.get("person_id") is not None:
            people.append(person_ref(deal.get("person_id")))
        anchor = (
            link("deal", n.get("deal_id"))
            if n.get("deal_id") is not None
            else link("person", n.get("person_id"))
            if n.get("person_id") is not None
            else link("organization", n.get("org_id"))
            if n.get("org_id") is not None
            else web
        )
        add(
            {
                "ts": iso(n.get("add_time")),
                "kind": "record",
                "title": f"Note: {about}".strip() if about else "Note",
                "text": n.get("content", ""),
                "owner_role": role,
                "due": "",
                "url": f"{anchor}#note-{n.get('id')}" if anchor else "",
                "status": "done",
            },
            people,
        )

    # contacts
    contacts: list[dict] = []
    now_s = iso(now_utc())
    for key, p in persons.items():
        own = _same(p.get("owner_id"), me_id)
        if not (everything or own or key in touched):
            continue
        email = _primary(p.get("emails", [])).lower()
        if email and email == me_email:
            continue
        name = (
            p.get("name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
        ).strip()
        phone = _primary(p.get("phones", []))
        if not (name or email or phone):
            continue
        # first/last seen are past events only: a call planned for next week is not a contact yet
        stamps = sorted(t for t in touched.get(key, []) if t and t <= now_s)
        contacts.append(
            {
                "source": SOURCE_ID,
                "name": name,
                "email": email,
                "phone": phone,
                "company": org_name(p.get("org_id")),
                "title": p.get("job_title", ""),
                "first_seen": stamps[0] if stamps else "",
                "last_seen": stamps[-1] if stamps else "",
                "interactions": len(touched.get(key, [])),
                "url": link("person", p.get("id")),
            }
        )

    cdf = pd.DataFrame(contacts, columns=CONTACT_COLUMNS)
    cdf["interactions"] = cdf["interactions"].astype("int64")
    idf = pd.DataFrame(rows, columns=INTERACTION_COLUMNS)
    if not idf.empty:
        idf = idf.sort_values(["ts", "url"], kind="stable").reset_index(drop=True)
    return cdf, idf


def write_frames(dest: Path, scope: str = "mine") -> dict:
    cdf, idf = build_frames(dest, scope)
    out = dest / PROCESSED_DIR
    cfg.safe_write_parquet(cdf, out / CONTACTS_FILE, index=False)
    cfg.safe_write_parquet(idf, out / INTERACTIONS_FILE, index=False)
    by_kind = idf["kind"].value_counts().to_dict() if not idf.empty else {}
    open_items = int((idf["status"] == "open").sum()) if not idf.empty else 0
    return {
        "scope": scope,
        "contacts": len(cdf),
        "interactions": len(idf),
        "open_items": open_items,
        **{f"kind_{k}": int(v) for k, v in by_kind.items()},
    }
