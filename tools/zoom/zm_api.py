"""Zoom plugin core: your own meetings, participants and cloud-recording transcripts.

Personal access only. You create a *user-managed* General app on the Zoom App
Marketplace, turn on "Use Public Client OAuth" (PKCE, no client secret) and register
the loopback redirect http://127.0.0.1/callback. One browser login stores a refresh
token in the macOS Keychain (sbk-zoom/<label>). Every call uses the `me` context and
user-level granular scopes only (no ":admin" or ":master" scope is ever requested).

Vendor facts this module relies on (checked on Zoom's official docs, 2026-11-25):
- OAuth endpoints, 1-hour access tokens, 90-day rotating refresh tokens:
  https://developers.zoom.us/docs/integrations/oauth/
- PKCE public client, loopback redirect 127.0.0.1 (port ignored), refresh without
  secret: https://developers.zoom.us/docs/integrations/PKCE/
- Granular scopes without suffix = grantable by the individual user:
  https://developers.zoom.us/docs/integrations/oauth-scopes-overview/
- Endpoints, scopes, plan prerequisites, 1-month `from`/`to` window, UUID double
  encoding: https://developers.zoom.us/docs/api/meetings/
- Rate limits (Free: Medium 2/s and 2000/day): https://developers.zoom.us/docs/api/rate-limits/

Nothing here prints or logs a token.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

SOURCE = "zoom"
KEYCHAIN_SERVICE = "sbk-zoom"
CLIENT_ID_ACCOUNT = "client-id"
DEFAULT_LABEL = "default"

AUTHORIZE_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"
API_BASE = "https://api.zoom.us/v2"
REDIRECT_PATH = "/callback"

# User-level granular scopes (no ":admin" / ":master" suffix). The app must list them
# in its build flow; the login checks what Zoom actually granted.
REQUIRED_SCOPES = (
    "user:read:user",
    "cloud_recording:read:list_user_recordings",
    "meeting:read:list_past_participants",
)
OPTIONAL_SCOPES = ("meeting:read:list_meetings",)

ENV_CLIENT_ID = "ZOOM_CLIENT_ID"
ENV_REFRESH_TOKEN = "ZOOM_REFRESH_TOKEN"
ENV_TOKEN_FILE = "ZOOM_TOKEN_FILE"

SETUP_HINT = "see docs/CONNECTING.md#zoom"

# Medium APIs on the Free plan allow 2 requests/second: one request every 0.5 s fits
# every plan. List-recordings windows are at most one month (Zoom docs).
REQUEST_DELAY = 0.5
REQUEST_TIMEOUT_SECS = 60
MAX_RETRIES = 5
WINDOW_DAYS = 30
PAGE_SIZE = 30
MULTI_SEP = "|||"

# Fields of a recording answer that open the recording for anyone holding them
# (List all recordings: password, recording_play_passcode; download_access_token when
# asked for). They are never written to disk.
SECRET_FIELDS = frozenset({"password", "recording_play_passcode", "download_access_token"})
# Query parameters that carry a passcode or a token inside a URL.
SECRET_QUERY_PARAMS = frozenset({"pwd", "passcode", "access_token"})

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
    "status",  # optional in the kernel contract; every meeting read here is over: "done"
]


class ZoomError(Exception):
    """A Zoom problem worth one clear line to the user (never carries a token)."""


class DailyLimitReached(ZoomError):
    """Zoom's daily rate limit for this API: stop and keep what was downloaded."""


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def zoom_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "zoom"


def raw_dir() -> Path:
    return zoom_dir() / "raw"


def processed_dir() -> Path:
    return zoom_dir() / "processed"


def state_path() -> Path:
    return raw_dir() / "state.json"


def summary_path() -> Path:
    return zoom_dir() / "download-summary.json"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "zoom" section, read without touching sbk_config) ------


def cfg(key: str, default):
    return sbk_config.user_cfg(f"zoom.{key}", default)


def client_id() -> str:
    """Public client ID of your Zoom app: env first, then sbk.config.json, then Keychain."""
    cid = os.environ.get(ENV_CLIENT_ID, "").strip()
    if cid:
        return cid
    cid = str(cfg("client_id", "") or "").strip()
    if cid:
        return cid
    try:
        from secrets_adapter import get_secret

        return (get_secret(KEYCHAIN_SERVICE, CLIENT_ID_ACCOUNT) or "").strip()
    except Exception:  # noqa: BLE001 — no keyring backend counts as "not set"
        return ""


# --- refresh token storage ------------------------------------------------------------


def _token_file() -> Path | None:
    p = os.environ.get(ENV_TOKEN_FILE, "").strip()
    return Path(p).expanduser() if p else None


def load_refresh_token(label: str = DEFAULT_LABEL) -> tuple[str, str]:
    """(refresh_token, where) or ("", "") when no login is stored anywhere."""
    try:
        from secrets_adapter import get_secret

        tok = (get_secret(KEYCHAIN_SERVICE, label) or "").strip()
    except Exception:  # noqa: BLE001
        tok = ""
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
    """Store the newest refresh token. Zoom rotates it on every refresh."""
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


# --- HTTP -----------------------------------------------------------------------------


def _default_opener(req: Request, timeout: float):
    return urlopen(req, timeout=timeout)


class ZoomClient:
    """Small Zoom REST client. `opener(Request, timeout)` is injectable for tests."""

    def __init__(
        self,
        access_token: str,
        opener=None,
        delay: float = REQUEST_DELAY,
        sleep=None,
        refresher=None,
    ):
        self._token = access_token
        self._open = opener or _default_opener
        self._delay = delay
        self._sleep = sleep or time.sleep
        self._refresher = refresher  # () -> new access token; access tokens last one hour
        self._last = 0.0
        self.requests = 0

    def _wait(self) -> None:
        gap = time.time() - self._last
        if gap < self._delay:
            self._sleep(self._delay - gap)
        self._last = time.time()

    def _send(self, url: str, accept: str = "application/json") -> bytes:
        refreshed = False
        for attempt in range(MAX_RETRIES):
            self._wait()
            self.requests += 1
            headers = {"Authorization": f"Bearer {self._token}", "Accept": accept}
            try:
                with self._open(Request(url, headers=headers), REQUEST_TIMEOUT_SECS) as resp:
                    return resp.read()
            except HTTPError as e:
                body = _safe_body(e)
                if e.code == 401 and self._refresher and not refreshed:
                    self._token = self._refresher()  # expired access token on a long run
                    refreshed = True
                    continue
                if e.code == 429:
                    if "daily" in body.lower():
                        raise DailyLimitReached(
                            "Zoom daily rate limit reached for this API; what was downloaded is kept"
                        ) from None
                    retry = e.headers.get("Retry-After") if e.headers else None
                    self._sleep(float(retry) if retry and retry.isdigit() else 2 * (attempt + 1))
                    continue
                if e.code >= 500:
                    self._sleep(2 * (attempt + 1))
                    continue
                raise ApiHTTPError(e.code, body) from None
            except URLError as e:
                if attempt == MAX_RETRIES - 1:
                    raise ZoomError(f"network error talking to Zoom: {e.reason}") from None
                self._sleep(2 * (attempt + 1))
        raise ZoomError(f"Zoom kept failing after {MAX_RETRIES} attempts: {url.split('?')[0]}")

    def get(self, path: str, **params) -> dict:
        q = {k: v for k, v in params.items() if v not in (None, "")}
        url = f"{API_BASE}{path}" + (f"?{urlencode(q)}" if q else "")
        return json.loads(self._send(url) or b"{}")

    def paged(self, path: str, key: str, **params):
        token = ""
        while True:
            data = self.get(path, page_size=PAGE_SIZE, next_page_token=token, **params)
            yield from data.get(key) or []
            token = data.get("next_page_token") or ""
            if not token:
                return

    def download(self, url: str) -> bytes:
        """A recording file `download_url`; Zoom accepts the user's OAuth token as Bearer."""
        return self._send(url, accept="*/*")


class ApiHTTPError(ZoomError):
    def __init__(self, code: int, body: str):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


def _safe_body(e: HTTPError) -> str:
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def refresh_access_token(refresh_token: str, cid: str, opener=None) -> dict:
    """POST /oauth/token grant_type=refresh_token with the public client ID (PKCE app).

    Returns Zoom's JSON (access_token, refresh_token, scope, expires_in). Never logs it.
    """
    body = urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": cid}
    ).encode()
    req = Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with (opener or _default_opener)(req, REQUEST_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        reason = ""
        try:
            reason = json.loads(_safe_body(e)).get("reason") or ""
        except ValueError:
            pass
        raise ZoomError(
            f"Zoom refused the stored login (HTTP {e.code}{': ' + reason if reason else ''}); "
            "refresh tokens last 90 days and rotate on each use. Sign in again: "
            "uv run python tools/zoom/zm-l0-auth.py"
        ) from None
    except URLError as e:
        raise ZoomError(f"network error talking to Zoom: {e.reason}") from None
    if not data.get("access_token"):
        raise ZoomError(
            "Zoom returned no access token; sign in again with tools/zoom/zm-l0-auth.py"
        )
    return data


def missing_scopes(granted: str) -> list[str]:
    have = set((granted or "").split())
    return [s for s in REQUIRED_SCOPES if s not in have]


# --- ids, windows, transcripts ---------------------------------------------------------


def encode_uuid(uuid: str) -> str:
    """Path segment for a meeting UUID. Zoom asks to double-encode UUIDs with '/'."""
    once = quote(uuid, safe="")
    return quote(once, safe="") if "/" in uuid else once


def file_key(uuid: str) -> str:
    """Filesystem-safe, reversible name for a meeting UUID."""
    return base64.urlsafe_b64encode(uuid.encode()).decode().rstrip("=")


def windows(start: date, end: date, days: int = WINDOW_DAYS):
    """[from, to] date pairs of at most `days` days covering start..end."""
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


_CUE_TIME = re.compile(r"^\d{2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->\s+")


def vtt_to_text(vtt: str) -> tuple[str, list[str]]:
    """Plain 'Speaker: words' lines from a Zoom VTT transcript, plus the speakers seen."""
    lines: list[str] = []
    speakers: list[str] = []
    last_speaker, buf = None, []

    def flush():
        if buf:
            txt = " ".join(buf).strip()
            lines.append(f"{last_speaker}: {txt}" if last_speaker else txt)

    for raw in (vtt or "").splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit() or _CUE_TIME.match(line):
            continue
        if line.startswith(("NOTE", "STYLE", "Kind:", "Language:")):
            continue
        m = re.match(r"^([^:]{1,80}):\s+(.*)$", line)
        if m:
            speaker, words = m.group(1).strip(), m.group(2).strip()
            if speaker not in speakers:
                speakers.append(speaker)
            if speaker != last_speaker:
                flush()
                last_speaker, buf = speaker, []
            buf.append(words)
        else:
            buf.append(line)  # continuation of the current cue (or text without a speaker)
    flush()
    return "\n".join(lines), speakers


def iso(ts) -> str:
    """ISO 8601 in UTC ('...Z' from Zoom stays as is); '' when missing."""
    if not ts:
        return ""
    s = str(ts)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def strip_secrets(obj):
    """A copy of a Zoom answer without the fields that open a recording (SECRET_FIELDS)."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if k not in SECRET_FIELDS}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj


def clean_url(url) -> str:
    """The URL without query parameters that carry a passcode or a token."""
    s = str(url or "")
    if "?" not in s:
        return s
    from urllib.parse import parse_qsl, urlsplit, urlunsplit

    parts = urlsplit(s)
    keep = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in SECRET_QUERY_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(keep)))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    sbk_config.safe_write_json(path, data)
