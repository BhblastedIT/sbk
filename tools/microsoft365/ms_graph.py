#!/usr/bin/env python3
"""Microsoft 365 plugin: sign-in, token store and Microsoft Graph client.

Personal access only. You register your own public-client app (no secret) and sign
in as yourself; the plugin asks for delegated scopes that need no admin consent:
User.Read, Mail.Read, Calendars.Read, Contacts.Read and offline_access.

Two sign-in flows of the Microsoft identity platform, both without a client secret:
- authorization code + PKCE with a loopback redirect (http://localhost), the default;
- device code (--device-code), for a machine without a browser.

The refresh token (a new one comes back at every use) is kept in the Keychain through
tools/secrets_adapter.py: service "sbk-microsoft365", account = the mailbox label.
Without a Keychain (container mode, Linux without a keyring): SBK_MS365_TOKEN_FILE, a JSON
file (mode 600) the plugin reads and keeps up to date, then SBK_MS365_TOKEN_<LABEL> as a
read-only seed. Nothing here prints or logs a token.

Vendor references (checked 2026-11-25):
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens
- https://learn.microsoft.com/en-us/graph/permissions-reference
- https://learn.microsoft.com/en-us/entra/identity-platform/reply-url (localhost redirect:
  the port is ignored when matching)
- https://learn.microsoft.com/en-us/graph/throttling-limits (Outlook: 10,000 requests per
  10 minutes and 4 concurrent requests per app and mailbox)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from secrets_adapter import get_secret, set_secret  # noqa: E402

import sbk_config  # noqa: E402

log = logging.getLogger("ms365")

PLUGIN_ID = "microsoft365"
SECRET_SERVICE = "sbk-microsoft365"
ENV_CLIENT_ID = "SBK_MS365_CLIENT_ID"
ENV_TENANT = "SBK_MS365_TENANT"
ENV_TOKEN_PREFIX = "SBK_MS365_TOKEN_"
ENV_TOKEN_FILE = "SBK_MS365_TOKEN_FILE"
SETUP_HINT = "see docs/CONNECTING.md#microsoft365"

LOGIN_BASE = "https://login.microsoftonline.com"
GRAPH_HOST = "graph.microsoft.com"
GRAPH_BASE = f"https://{GRAPH_HOST}/v1.0"

# Delegated scopes. Each one is "AdminConsentRequired: No" for Delegated and available
# for personal Microsoft accounts on the Graph permissions reference (2026-11-25).
SCOPES = ("offline_access", "User.Read", "Mail.Read", "Calendars.Read", "Contacts.Read")

# Data under DATA_ROOT. Looked up at call time so tests can point DATA_ROOT elsewhere.
DATA_ROOT: Path | None = None

_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")

# Sequential client (one request at a time, Outlook allows 4 concurrent), at least this
# many seconds between requests: at most 6,000 per 10 minutes, under Outlook's 10,000.
MIN_INTERVAL_S = 0.1
MAX_RETRIES = 6
REQUEST_TIMEOUT_S = 60


class SetupError(Exception):
    """Missing configuration or credentials: the message is one line for the user."""


class TokenError(Exception):
    """The identity platform refused a token request."""


class GraphError(Exception):
    def __init__(self, status: int, code: str, message: str, url: str = ""):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.url = url


class DeltaReset(Exception):
    """The delta token is no longer valid: restart that collection from scratch."""


# --------------------------------------------------------------------------- paths


def data_root() -> Path:
    return Path(DATA_ROOT) if DATA_ROOT is not None else Path(sbk_config.DATA_ROOT)


def plugin_dir(label: str) -> Path:
    return data_root() / PLUGIN_ID / label


def state_path(label: str) -> Path:
    return plugin_dir(label) / "state.json"


def summary_path(label: str) -> Path:
    return plugin_dir(label) / "download-summary.json"


def mail_slot(label: str) -> Path:
    return data_root() / "emails" / label / "messages.parquet"


def calendar_slot(label: str) -> Path:
    return data_root() / "calendars" / label / "events.parquet"


def contacts_slot() -> Path:
    return data_root() / "contacts" / "contacts.parquet"


def iphone_json_paths() -> list[Path]:
    """The two JSON address books tools/cross-source/xs-l1-contacts-enrich.py reads."""
    repo = _TOOLS_DIR.parent
    return [
        repo / "sbk" / "raw" / "contacts" / "iphone-contacts.json",
        data_root() / "contacts" / "iphone-contacts.json",
    ]


def check_label(label: str) -> str:
    label = (label or "").strip().lower()
    if not _LABEL_RE.match(label):
        raise SetupError(
            f"microsoft365: account label {label!r} is not valid "
            "(use lowercase letters, digits, '.', '_' or '-', e.g. outlook)"
        )
    return label


# --------------------------------------------------------------------------- state


def load_state(label: str) -> dict:
    p = state_path(label)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("state file unreadable, starting fresh: %s", p)
    return {
        "owner": PLUGIN_ID,
        "label": label,
        "mail": {"folders": {}},
        "calendar": {},
        "slots": {},
    }


def save_state(label: str, state: dict) -> None:
    p = state_path(label)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------- config


def client_id() -> str:
    cid = os.environ.get(ENV_CLIENT_ID) or sbk_config.user_cfg("microsoft365.client_id", "")
    return str(cid or "").strip()


def default_tenant() -> str:
    t = os.environ.get(ENV_TENANT) or sbk_config.user_cfg("microsoft365.tenant", "") or "common"
    return str(t).strip()


def env_token_name(label: str) -> str:
    return ENV_TOKEN_PREFIX + re.sub(r"[^A-Z0-9]", "_", label.upper())


# --------------------------------------------------------------------------- token store


def token_file() -> Path | None:
    p = os.environ.get(ENV_TOKEN_FILE, "").strip()
    return Path(p).expanduser() if p else None


def _parse_record(raw: str | None) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            rec = json.loads(raw)
        except ValueError:
            return None
        return rec if isinstance(rec, dict) and rec.get("refresh_token") else None
    return {"refresh_token": raw}


def _read_token_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_token_record(label: str) -> dict | None:
    """The saved sign-in of a mailbox: Keychain, then SBK_MS365_TOKEN_FILE, then env seed."""
    try:
        rec = _parse_record(get_secret(SECRET_SERVICE, label))
    except Exception:  # noqa: BLE001 - a broken keyring must not hide the other places
        rec = None
    if rec:
        return rec
    tf = token_file()
    if tf and tf.is_file():
        entry = _read_token_file(tf).get(label)
        rec = _parse_record(json.dumps(entry) if isinstance(entry, dict) else entry)
        if rec:
            return rec
    return _parse_record(os.environ.get(env_token_name(label)))


def save_token_record(label: str, record: dict) -> str:
    """Store the newest sign-in; returns where it went. Raises SetupError if nowhere."""
    record = dict(record)
    record["saved_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    tf = token_file()
    if tf:
        data = _read_token_file(tf) if tf.is_file() else {}
        data[label] = record
        tf.parent.mkdir(parents=True, exist_ok=True)
        tmp = tf.with_name(tf.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never world-readable
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, tf)
        return f"file {ENV_TOKEN_FILE}"
    if os.environ.get("SBK_CONTAINERIZED", "0") == "1":
        raise SetupError(
            f"microsoft365: container mode has no Keychain; set {ENV_TOKEN_FILE} to a file "
            f"path so the sign-in can be stored ({SETUP_HINT})"
        )
    try:
        set_secret(SECRET_SERVICE, label, json.dumps(record))
    except Exception as e:  # noqa: BLE001 - keyring backend missing or locked
        raise SetupError(
            f"microsoft365: the Keychain refused the sign-in ({type(e).__name__}); set "
            f"{ENV_TOKEN_FILE} to a file path instead ({SETUP_HINT})"
        ) from None
    return f"Keychain {SECRET_SERVICE}/{label}"


# --------------------------------------------------------------------------- HTTP


class Http:
    """Thin wrapper around requests, replaced by a fake in the tests."""

    def __init__(self):
        import requests

        self._s = requests.Session()
        self._s.headers["User-Agent"] = "sbk-microsoft365/1"

    def request(self, method: str, url: str, *, headers=None, data=None, params=None):
        import requests

        try:
            r = self._s.request(
                method,
                url,
                headers=headers or {},
                data=data,
                params=params,
                timeout=REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as e:
            # Treated like a 5xx: Graph.get retries with back-off, then gives one clear line.
            return 599, {}, {"error": "network_error", "error_description": type(e).__name__}
        try:
            body = r.json()
        except ValueError:
            body = {"_text": r.text[:500]}
        return r.status_code, dict(r.headers), body


# --------------------------------------------------------------------------- OAuth


def _endpoint(tenant: str, what: str) -> str:
    return f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/{what}"


def _token_request(http, tenant: str, form: dict) -> dict:
    status, _h, body = http.request("POST", _endpoint(tenant, "token"), data=form)
    if status != 200 or "access_token" not in body:
        body = body or {}
        err = body.get("error", f"http_{status}")
        lines = str(body.get("error_description") or "").splitlines()
        desc = lines[0][:300] if lines else ""
        hint = ""
        if err == "invalid_grant":
            hint = f" (sign in again: tools/microsoft365/ms-l0-auth.py; {SETUP_HINT})"
        raise TokenError(f"microsoft365: token request refused: {err}: {desc}{hint}")
    return body


def pkce_pair() -> tuple[str, str]:
    """RFC 7636 code_verifier (43-128 chars) and its S256 code_challenge."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(cid: str, tenant: str, redirect_uri: str, challenge: str, state: str) -> str:
    q = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return _endpoint(tenant, "authorize") + "?" + urllib.parse.urlencode(q)


def exchange_code(http, cid: str, tenant: str, code: str, redirect_uri: str, verifier: str) -> dict:
    return _token_request(
        http,
        tenant,
        {
            "client_id": cid,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": " ".join(SCOPES),
        },
    )


def browser_login(
    cid: str,
    tenant: str,
    http,
    open_browser: Callable[[str], object] | None = None,
    timeout_s: int = 300,
) -> dict:
    """Authorization code + PKCE on a loopback server (http://localhost:<free port>).

    The app registers `http://localhost` (Mobile and desktop platform); the identity
    platform ignores the port of a localhost redirect URI when matching it.
    """
    import webbrowser

    open_browser = open_browser or webbrowser.open
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def _finish(self, params: dict):
            if "code" in params or "error" in params:  # ignore favicon and stray requests
                result.update({k: v[0] for k, v in params.items()})
            ok = "code" in result and result.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Signed in. You can close this tab." if ok else b"Sign-in did not complete."
            )

        def do_GET(self):  # noqa: N802
            self._finish(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            self._finish(urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")))

        def log_message(self, *_a):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}"
    server.timeout = 1
    deadline = time.monotonic() + timeout_s

    def serve():
        while not result and time.monotonic() < deadline:
            server.handle_request()

    url = authorize_url(cid, tenant, redirect_uri, challenge, state)
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    print(f"Opening the Microsoft sign-in page. If it does not open, visit:\n{url}")
    open_browser(url)
    t.join(timeout_s + 5)
    server.server_close()
    if result.get("error"):
        raise TokenError(f"{result['error']}: {result.get('error_description', '')[:300]}")
    if result.get("state") != state or "code" not in result:
        raise TokenError("no authorization code came back (timeout or state mismatch)")
    return exchange_code(http, cid, tenant, result["code"], redirect_uri, verifier)


def device_code_login(cid: str, tenant: str, http, sleep=time.sleep, out=print) -> dict:
    status, _h, body = http.request(
        "POST", _endpoint(tenant, "devicecode"), data={"client_id": cid, "scope": " ".join(SCOPES)}
    )
    if status != 200 or "device_code" not in body:
        raise TokenError(
            f"{body.get('error', f'http_{status}')}: {body.get('error_description', '')[:300]}"
        )
    out(
        body.get("message")
        or f"Go to {body.get('verification_uri')} and enter {body.get('user_code')}"
    )
    interval = int(body.get("interval", 5))
    deadline = time.monotonic() + int(body.get("expires_in", 900))
    while time.monotonic() < deadline:
        sleep(interval)
        st, _h, tok = http.request(
            "POST",
            _endpoint(tenant, "token"),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": cid,
                "device_code": body["device_code"],
            },
        )
        if st == 200 and "access_token" in tok:
            return tok
        err = tok.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise TokenError(f"{err or f'http_{st}'}: {str(tok.get('error_description', ''))[:300]}")
    raise TokenError("expired_token: the device code expired before sign-in finished")


class TokenProvider:
    """Access tokens for one mailbox label, refreshed from the stored refresh token."""

    def __init__(self, label: str, http, record: dict | None = None):
        self.label = label
        self.http = http
        self.record = record if record is not None else load_token_record(label)
        if not self.record:
            raise SetupError(
                f"microsoft365: no sign-in for '{label}' (Keychain {SECRET_SERVICE}/{label}, "
                f"{ENV_TOKEN_FILE} or {env_token_name(label)}); run: uv run python "
                f"tools/microsoft365/ms-l0-auth.py --account {label}"
            )
        self.cid = self.record.get("client_id") or client_id()
        if not self.cid:
            raise SetupError(
                f"microsoft365: no app client id; set {ENV_CLIENT_ID} or microsoft365.client_id "
                f"in sbk.config.json ({SETUP_HINT})"
            )
        self.tenant = self.record.get("tenant") or default_tenant()
        self._access: str | None = None
        self._expires = 0.0

    def token(self, force: bool = False) -> str:
        if not force and self._access and time.time() < self._expires - 120:
            return self._access
        body = _token_request(
            self.http,
            self.tenant,
            {
                "client_id": self.cid,
                "grant_type": "refresh_token",
                "refresh_token": self.record["refresh_token"],
                "scope": " ".join(SCOPES),
            },
        )
        self._access = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 3600))
        if body.get("refresh_token") and body["refresh_token"] != self.record.get("refresh_token"):
            self.record = {
                **self.record,
                "refresh_token": body["refresh_token"],
                "client_id": self.cid,
                "tenant": self.tenant,
            }
            try:
                save_token_record(self.label, self.record)
            except SetupError as e:
                # The old refresh token stays valid until its own lifetime ends (refresh-tokens doc).
                log.warning("new refresh token not stored: %s", e)
        return self._access


# --------------------------------------------------------------------------- Graph


class Graph:
    """Sequential Microsoft Graph GET client with paging, 401 refresh and 429 back-off."""

    def __init__(self, tokens, http, sleep=time.sleep):
        self.tokens = tokens
        self.http = http
        self.sleep = sleep
        self._last = 0.0
        self.requests = 0
        self.throttled = 0

    def _url(self, path_or_url: str) -> str:
        if not path_or_url.startswith("https://"):
            return GRAPH_BASE + path_or_url
        # Paging and delta links come from Graph and from state.json: the bearer token is
        # only ever sent to Graph itself.
        if urllib.parse.urlparse(path_or_url).netloc.lower() != GRAPH_HOST:
            raise GraphError(0, "untrusted_link", "a paging or delta link is not on " + GRAPH_HOST)
        return path_or_url

    def get(
        self, path_or_url: str, params: dict | None = None, prefer: list[str] | None = None
    ) -> dict:
        url = self._url(path_or_url)
        refreshed = False
        last = (599, "retries_exhausted")
        for attempt in range(MAX_RETRIES):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            headers = {
                "Authorization": f"Bearer {self.tokens.token()}",
                "Accept": "application/json",
            }
            if prefer:
                headers["Prefer"] = ", ".join(prefer)
            status, rh, body = self.http.request("GET", url, headers=headers, params=params)
            self._last = time.monotonic()
            self.requests += 1
            if status == 200:
                return body
            err = (body or {}).get("error") or {}
            code = err.get("code", "") if isinstance(err, dict) else str(err)
            msg = err.get("message", "") if isinstance(err, dict) else ""
            if status == 401 and not refreshed:
                self.tokens.token(force=True)
                refreshed = True
                continue
            if status == 410 or code in (
                "syncStateNotFound",
                "SyncStateNotFound",
                "syncStateInvalid",
            ):
                raise DeltaReset(code or "410")
            if status in (429, 503, 504) or status >= 500:
                self.throttled += status == 429
                ra = _retry_after(rh)
                delay = ra if ra is not None else min(60, 2 ** (attempt + 1))
                log.warning("Graph %s on %s, waiting %ss", status, url.split("?")[0], delay)
                self.sleep(delay)
                last = (status, code)
                continue
            raise GraphError(status, code, msg, url)
        status, code = last
        raise GraphError(
            status, code or "retries_exhausted", f"gave up after {MAX_RETRIES} attempts", url
        )

    def pages(
        self, path_or_url: str, params: dict | None = None, prefer: list[str] | None = None
    ) -> Iterator[dict]:
        """Every page of a collection; the last one carries @odata.deltaLink if any."""
        body = self.get(path_or_url, params=params, prefer=prefer)
        yield body
        while body.get("@odata.nextLink"):
            body = self.get(body["@odata.nextLink"], prefer=prefer)
            yield body


def _retry_after(headers: dict) -> int | None:
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return max(1, int(float(v)))
            except (TypeError, ValueError):
                return None
    return None


def one_line(e: BaseException) -> str:
    """The single stderr line a CLI prints for an expected failure."""
    lines = str(e).strip().splitlines()
    text = lines[0] if lines else type(e).__name__
    return text if text.startswith("microsoft365") else f"microsoft365: {text}"


def missing_scopes(granted: str) -> list[str]:
    """Scopes of SCOPES absent from a token response's `scope` (it may carry a resource
    prefix such as https://graph.microsoft.com/). offline_access is checked through the
    refresh token instead, because it is not always echoed back."""
    have = {s.rsplit("/", 1)[-1].lower() for s in (granted or "").split()}
    if not have:
        return []
    return [s for s in SCOPES if s != "offline_access" and s.lower() not in have]


def whoami(graph: Graph) -> dict:
    me = graph.get("/me", params={"$select": "displayName,mail,userPrincipalName,id"})
    return {
        "display_name": me.get("displayName") or "",
        "email": me.get("mail") or me.get("userPrincipalName") or "",
    }
