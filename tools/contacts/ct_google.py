"""Contacts plugin, Google part: your own Google Contacts through the People API.

Personal access only: the same Desktop-app OAuth client of your own Google Cloud project that
the other Google plugins use (tools/google_oauth.py), one browser login per Google account,
the single read-only scope contacts.readonly, the `people/me` context. The refresh token is
kept in the Keychain as sbk-gcontacts/<label>; without a Keychain, in the env variable
SBK_GCONTACTS_TOKEN_<LABEL>.

Vendor facts this module relies on (checked on Google's official docs, 2026-11-25):
- GET https://people.googleapis.com/v1/people/me/connections, personFields required,
  pageSize 1..1000 (default 100), pageToken, requestSyncToken / syncToken, sources[]
  (default CONTACT + PROFILE), nextSyncToken only on the last page, sync tokens expire 7 days
  after the full sync (error reason EXPIRED_SYNC_TOKEN, the guide's sample checks HTTP 410),
  deleted people come back with metadata.deleted on sync requests, every other parameter must
  match the first call, the first page of a full sync has an extra fixed quota (429):
  https://developers.google.com/people/api/rest/v1/people.connections/list
  https://developers.google.com/people/v1/contacts
- Person fields (names, emailAddresses, phoneNumbers.canonicalForm, organizations,
  birthdays.date with year 0 = no year, metadata.sources.updateTime,
  metadata.previousResourceNames): https://developers.google.com/people/api/rest/v1/people
- Scope https://www.googleapis.com/auth/contacts.readonly = "See and download your contacts":
  https://developers.google.com/identity/protocols/oauth2/scopes
- Refresh tokens of an External app in Testing expire after 7 days; 100 refresh tokens per
  account per client: https://developers.google.com/identity/protocols/oauth2
- The per-minute quota numbers of the People API are shown in your project's console
  (APIs & Services -> People API -> Quotas); no public Google page with the numbers was found.

Nothing here prints or logs a token.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ct_book  # noqa: E402
import google_oauth  # noqa: E402
from ct_book import ContactsError  # noqa: E402

KEYCHAIN_SERVICE = "sbk-gcontacts"
SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
API_URL = "https://people.googleapis.com/v1/people/me/connections"
TOKEN_URL = google_oauth.TOKEN_URI
PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,birthdays,metadata"
READ_SOURCES = "READ_SOURCE_TYPE_CONTACT"  # only the contacts you saved, not profile data
PAGE_SIZE = 1000
REQUEST_DELAY = 0.5  # one request at a time, at most two per second
REQUEST_TIMEOUT_SECS = 60
MAX_RETRIES = 5
ENV_TOKEN_PREFIX = "SBK_GCONTACTS_TOKEN_"
LOGIN_CMD = "uv run python tools/contacts/ct-l0-auth.py --account {label}"
SETUP_HINT = "see docs/CONNECTING.md#contacts"


class SyncTokenExpired(ContactsError):
    """The saved sync token is older than Google keeps it: a full sync is needed."""


class ApiHTTPError(ContactsError):
    def __init__(self, code: int, reason: str):
        super().__init__(f"HTTP {code}{': ' + reason if reason else ''}")
        self.code = code
        self.reason = reason


# --- secrets (patched in tests) ----------------------------------------------------------


def get_secret(service: str, account: str) -> str | None:
    try:
        from secrets_adapter import get_secret as _get

        return _get(service, account)
    except Exception:  # noqa: BLE001 - no keyring backend counts as "not set"
        return None


def set_secret(service: str, account: str, value: str) -> None:
    from secrets_adapter import set_secret as _set

    _set(service, account, value)


def env_token_name(label: str) -> str:
    return ENV_TOKEN_PREFIX + re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")


def _parse_stored(raw: str) -> tuple[str, str, str]:
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
        except ValueError:
            return "", "", ""
        return d.get("refresh_token", ""), d.get("client_id", ""), d.get("client_secret", "")
    return raw, "", ""


def load_login(label: str) -> tuple[str, str, str, str]:
    """(refresh_token, client_id, client_secret, where). Raises ContactsError when missing."""
    refresh, cid, csec = _parse_stored(get_secret(KEYCHAIN_SERVICE, label) or "")
    where = f"Keychain {KEYCHAIN_SERVICE}/{label}"
    if not refresh:
        refresh, cid, csec = _parse_stored(os.environ.get(env_token_name(label), ""))
        where = f"env {env_token_name(label)}"
    if not refresh:
        raise ContactsError(
            f"no Google login stored for '{label}' (Keychain {KEYCHAIN_SERVICE}/{label} or "
            f"{env_token_name(label)}); run: {LOGIN_CMD.format(label=label)}"
        )
    if not (cid and csec):
        cid, csec = google_oauth.client_id_secret()
    if not (cid and csec):
        raise ContactsError(
            "your Google OAuth client was not found (GOOGLE_OAUTH_CLIENT_ID + "
            "GOOGLE_OAUTH_CLIENT_SECRET, or the Desktop-app JSON at "
            f"{google_oauth.client_file()}); {SETUP_HINT}"
        )
    return refresh, cid, csec, where


# --- HTTP ------------------------------------------------------------------------------


def _default_opener(req: Request, timeout: float):
    return urlopen(req, timeout=timeout)


def _error_reason(body: bytes) -> str:
    try:
        err = json.loads(body.decode("utf-8", errors="replace")).get("error")
    except (ValueError, AttributeError):
        return ""
    if isinstance(err, str):
        return err
    if not isinstance(err, dict):
        return ""
    reasons = [
        d.get("reason", "")
        for d in err.get("details") or []
        if isinstance(d, dict) and d.get("reason")
    ]
    status = err.get("status") or ""
    return ", ".join(x for x in [status, *reasons] if x)


def refresh_access_token(refresh: str, cid: str, csec: str, opener=None) -> dict:
    form = urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": cid,
            "client_secret": csec,
        }
    ).encode()
    req = Request(TOKEN_URL, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with (opener or _default_opener)(req, REQUEST_TIMEOUT_SECS) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        reason = _error_reason(e.read() or b"")
        if "invalid_grant" in reason:
            raise ContactsError(
                "Google refused the stored login (invalid_grant: expired or revoked; an app in "
                "Testing gets 7-day logins); sign in again with ct-l0-auth.py"
            ) from None
        raise ContactsError(f"token refresh failed: HTTP {e.code} {reason}".strip()) from None
    except URLError as e:
        raise ContactsError(f"cannot reach Google ({e.reason})") from None


class PeopleClient:
    """people.connections.list, one request at a time. `opener` is injectable for tests."""

    def __init__(self, access_token: str, opener=None, sleep=None, refresher=None):
        self._token = access_token
        self._open = opener or _default_opener
        self._sleep = sleep or time.sleep
        self._refresher = refresher
        self._last = 0.0
        self.requests = 0
        self.retries = 0

    def _get(self, params: dict) -> dict:
        url = f"{API_URL}?{urlencode(params)}"
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            wait = self._last + REQUEST_DELAY - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            req = Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {self._token}")
            req.add_header("Accept", "application/json")
            self._last = time.monotonic()
            self.requests += 1
            try:
                with self._open(req, REQUEST_TIMEOUT_SECS) as r:
                    return json.loads(r.read().decode("utf-8"))
            except HTTPError as e:
                reason = _error_reason(e.read() or b"")
                if e.code == 410 or "EXPIRED_SYNC_TOKEN" in reason:
                    raise SyncTokenExpired("sync token expired") from None
                if e.code == 401 and self._refresher and not refreshed:
                    self._token = self._refresher()
                    refreshed = True
                    continue
                if e.code == 403 and (
                    "SERVICE_DISABLED" in reason or "accessNotConfigured" in reason
                ):
                    raise ContactsError(
                        "the People API is not enabled in your Google Cloud project: enable it "
                        "in APIs & Services -> Library"
                    ) from None
                if e.code == 403 and "SCOPE" in reason.upper():
                    raise ContactsError(
                        "the login lacks the contacts.readonly scope; sign in again with "
                        "ct-l0-auth.py"
                    ) from None
                if (e.code == 429 or e.code >= 500) and attempt < MAX_RETRIES:
                    self.retries += 1
                    retry_after = e.headers.get("Retry-After") if e.headers is not None else None
                    try:
                        delay = float(retry_after) if retry_after else 2.0 ** (attempt + 1)
                    except ValueError:
                        delay = 2.0 ** (attempt + 1)
                    self._sleep(min(delay, 120.0))
                    continue
                raise ApiHTTPError(e.code, reason) from None
            except URLError as e:
                if attempt < MAX_RETRIES:
                    self.retries += 1
                    self._sleep(2.0 ** (attempt + 1))
                    continue
                raise ContactsError(f"cannot reach Google ({e.reason})") from None
        raise ContactsError("Google kept failing; nothing was changed")

    def list_all(self, sync_token: str = "") -> tuple[list[dict], str, int]:
        """Every page of one list call: (connections, nextSyncToken, totalItems)."""
        base = {
            "personFields": PERSON_FIELDS,
            "pageSize": PAGE_SIZE,
            "requestSyncToken": "true",
            "sources": READ_SOURCES,
        }
        if sync_token:
            base["syncToken"] = sync_token
        people: list[dict] = []
        page_token = ""
        total = 0
        while True:
            params = dict(base, pageToken=page_token) if page_token else dict(base)
            data = self._get(params)
            people += data.get("connections") or []
            total = int(data.get("totalItems") or total or 0)
            page_token = data.get("nextPageToken") or ""
            if not page_token:
                return people, data.get("nextSyncToken") or "", total


def connect(label: str, opener=None, sleep=None) -> tuple[PeopleClient, str]:
    """A client with a fresh access token, and the scopes Google says it carries."""
    refresh, cid, csec, _where = load_login(label)
    tokens = refresh_access_token(refresh, cid, csec, opener)
    if "access_token" not in tokens:
        raise ContactsError("Google answered the token refresh without an access token")
    scope = tokens.get("scope", "")
    if scope and SCOPES[0] not in scope.split():
        raise ContactsError(
            f"the stored login for '{label}' does not carry contacts.readonly; run: "
            + LOGIN_CMD.format(label=label)
        )
    client = PeopleClient(
        tokens["access_token"],
        opener=opener,
        sleep=sleep,
        refresher=lambda: refresh_access_token(refresh, cid, csec, opener)["access_token"],
    )
    return client, scope


# --- Person -> contact -------------------------------------------------------------------


def _ordered(items: list | None) -> list[dict]:
    items = [i for i in items or [] if isinstance(i, dict)]
    return sorted(items, key=lambda i: not (i.get("metadata") or {}).get("primary", False))


def _birthday(person: dict) -> str:
    for b in _ordered(person.get("birthdays")):
        d = b.get("date") or {}
        if d.get("month") and d.get("day"):
            y = int(d.get("year") or 0)
            mo, day = int(d["month"]), int(d["day"])
            iso = f"--{mo:02d}-{day:02d}" if y == 0 else f"{y:04d}-{mo:02d}-{day:02d}"
            return ct_book.parse_birthday(iso)
        if b.get("text"):
            got = ct_book.parse_birthday(b["text"])
            if got:
                return got
    return ""


def _updated(person: dict) -> str:
    times = [
        s.get("updateTime", "")
        for s in (person.get("metadata") or {}).get("sources") or []
        if isinstance(s, dict) and s.get("type") == "CONTACT"
    ]
    return max((t for t in times if t), default="")


def person_to_contact(person: dict) -> dict:
    names = _ordered(person.get("names"))
    n = names[0] if names else {}
    orgs = _ordered(person.get("organizations"))
    o = orgs[0] if orgs else {}
    return {
        "full_name": n.get("displayName") or "",
        "first_name": n.get("givenName") or "",
        "middle_name": n.get("middleName") or "",
        "last_name": n.get("familyName") or "",
        "organization": o.get("name") or "",
        "title": o.get("title") or "",
        "emails": [e.get("value", "") for e in _ordered(person.get("emailAddresses"))],
        "phones": [
            p.get("canonicalForm") or p.get("value", "")
            for p in _ordered(person.get("phoneNumbers"))
            if "fax" not in str(p.get("type", "")).lower()
        ],
        "birthday": _birthday(person),
        "last_updated": _updated(person),
        "uid": person.get("resourceName", ""),
    }


# --- download (one label) --------------------------------------------------------------


def people_path(label: str) -> Path:
    return ct_book.google_dir(label) / "people.json"


def state_path(label: str) -> Path:
    return ct_book.google_dir(label) / "state.json"


def run_download(label: str, client: PeopleClient, full: bool = False) -> dict:
    """Full or incremental read; writes raw/google/<label>/people.json and state.json."""
    started = datetime.now(UTC)
    state = ct_book.read_json(state_path(label), {})
    if not isinstance(state, dict):
        state = {}
    stored = ct_book.read_json(people_path(label), None)
    people: dict = stored if isinstance(stored, dict) else {}
    token = "" if full else str(state.get("sync_token") or "")
    mode = "incremental" if token else "full"
    if token and not isinstance(stored, dict):
        # A sync token only gives the changes: applied to a missing or unreadable people.json
        # it would leave just those changes and drop every other contact.
        token, mode = "", "full (stored contacts missing)"
    elif token and (state.get("person_fields"), state.get("sources")) != (
        PERSON_FIELDS,
        READ_SOURCES,
    ):
        # Google: with a syncToken "all other request parameters must match the first call".
        token, mode = "", "full (request fields changed)"
    try:
        got, next_token, total = client.list_all(token)
    except SyncTokenExpired:
        mode = "full (sync token expired)"
        got, next_token, total = client.list_all("")
    added = changed = deleted = 0
    if mode.startswith("full"):
        fresh = {}
        for p in got:
            rn = p.get("resourceName")
            if rn and not (p.get("metadata") or {}).get("deleted"):
                fresh[rn] = p
        added = len(set(fresh) - set(people))
        deleted = len(set(people) - set(fresh))
        changed = len(set(fresh) & set(people))
        people = fresh
    else:
        for p in got:
            rn = p.get("resourceName")
            if not rn:
                continue
            meta = p.get("metadata") or {}
            renamed = False
            for old in meta.get("previousResourceNames") or []:
                if old != rn and people.pop(old, None) is not None:
                    renamed = True
            if meta.get("deleted"):
                if people.pop(rn, None) is not None or renamed:
                    deleted += 1
                continue
            if rn in people or renamed:
                changed += 1
            else:
                added += 1
            people[rn] = p
    now = datetime.now(UTC).isoformat()
    ct_book.write_json(people_path(label), people)
    new_state = {
        "sync_token": (next_token or state.get("sync_token", ""))
        if mode == "incremental"
        else next_token,
        "last_sync_at": now,
        "full_sync_at": now if mode.startswith("full") else state.get("full_sync_at", ""),
        "person_fields": PERSON_FIELDS,
        "sources": READ_SOURCES,
    }
    ct_book.write_json(state_path(label), new_state)
    return {
        "kind": "google",
        "label": label,
        "mode": mode,
        "contacts_stored": len(people),
        "total_items_reported": total,
        "added": added,
        "changed": changed,
        "deleted": deleted,
        "sync_token_saved": bool(new_state["sync_token"]),
        "requests": client.requests,
        "retries": client.retries,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": now,
    }
