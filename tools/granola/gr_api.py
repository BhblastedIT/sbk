"""Granola plugin core: your own Granola meeting notes, attendees and transcripts.

Two personal routes, both read-only:

1. The Granola API with a **personal API key** (`grn_...`) that you create in the
   Granola desktop app (Settings -> Connectors -> API keys) with the **Personal notes**
   access scope. Granola lets any workspace member on a Business or Enterprise plan
   create one; a single person can upgrade a personal workspace to Business. On the
   free Basic plan there is no API key. Used by gr-l0-download.py.
2. The **CSV export** of your own notes (Settings -> Profile -> Generate CSV), which
   Granola emails to you; it exists on Basic and Business, and holds your full note
   history. Read from a local file by gr-l0-import-csv.py.

Workspace API keys (admin-only), Enterprise-managed authorization and the admin
"API access" controls are never used here.

Vendor facts this module relies on (checked on Granola's official docs, 2026-11-25):
- Base URL https://public-api.granola.ai/v1, `Authorization: Bearer <key>`, personal
  vs workspace keys, access scopes, how to create a personal key, error codes, rate
  limits (burst 25 requests per 5 s, sustained 5 requests/s):
  https://docs.granola.ai/introduction
- Who can create keys (Business or Enterprise), Personal notes scope:
  https://docs.granola.ai/help-center/sharing/integrations/granola-api
- GET /v1/notes (created_after, updated_after, cursor, page_size <= 30, only notes with a
  generated summary): https://docs.granola.ai/api-reference/list-notes
- GET /v1/notes/{id}?include=transcript (attendees, calendar_event.invitees/organiser,
  summary_markdown, private_notes_* only for the key's own notes, 413
  TRANSCRIPT_TOO_LARGE): https://docs.granola.ai/api-reference/get-note
- GET /v1/notes/{id}/transcript (cursor, page_size <= 100, 403 when transcripts are off):
  https://docs.granola.ai/api-reference/get-transcript
- Plans (Basic: no API, MCP 30 days; Business $14/user/month: MCP and API):
  https://docs.granola.ai/help-center/managing-your-account/subscriptions-and-billing
- CSV export (own notes, full history, emailed, once every 24 h, columns not documented):
  https://docs.granola.ai/help-center/sharing/exporting-notes

Nothing here prints or logs the API key.
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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

SOURCE = "granola"
API_BASE = "https://public-api.granola.ai/v1"
USER_AGENT = "sbk-granola-plugin"

KEYCHAIN_SERVICE = "sbk-granola"
KEYCHAIN_ACCOUNT = "api-key"
ENV_API_KEY = "GRANOLA_API_KEY"
SETUP_HINT = "see docs/CONNECTING.md#granola"

# Sustained limit is 5 requests/second with a burst of 25 per 5 s: one request every
# 0.25 s stays under it on every plan.
REQUEST_DELAY = 0.25
REQUEST_TIMEOUT_SECS = 60
MAX_RETRIES = 5
LIST_PAGE_SIZE = 30  # documented maximum for GET /v1/notes
TRANSCRIPT_PAGE_SIZE = 100  # documented maximum for GET /v1/notes/{id}/transcript
MULTI_SEP = "|||"
NOTE_ID_RE = re.compile(r"^[Nn][Oo][Tt]_[a-zA-Z0-9]{14}$")

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
    "status",  # optional in the kernel contract; a note is about a past meeting: "done"
]


class GranolaError(Exception):
    """A Granola problem worth one clear line to the user (never carries the key)."""


class AuthError(GranolaError):
    """The key or the account cannot be used at all: the run stops (never carries the key)."""


class ApiHTTPError(GranolaError):
    def __init__(self, status: int, code: str, message: str, path: str):
        self.status = status
        self.code = code
        self.path = path
        super().__init__(f"HTTP {status} {code or ''} on {path}: {message[:200]}".strip())


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def granola_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "granola"


def raw_dir() -> Path:
    return granola_dir() / "raw"


def notes_dir() -> Path:
    return raw_dir() / "notes"


def processed_dir() -> Path:
    return granola_dir() / "processed"


def state_path() -> Path:
    return raw_dir() / "state.json"


def summary_path() -> Path:
    return granola_dir() / "download-summary.json"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "granola" section, read without touching sbk_config) ---


def cfg(key: str, default):
    return sbk_config.user_cfg(f"granola.{key}", default)


# --- API key --------------------------------------------------------------------------


def resolve_api_key() -> tuple[str, str]:
    """(key, where it came from) or ("", "") when none is set. Keychain first, then env."""
    try:
        from secrets_adapter import get_secret

        key = (get_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) or "").strip()
    except Exception:  # noqa: BLE001 - no keyring backend counts as "not set"
        key = ""
    if key:
        return key, f"Keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"
    key = os.environ.get(ENV_API_KEY, "").strip()
    if key:
        return key, f"env {ENV_API_KEY}"
    return "", ""


def key_kind(key: str) -> str:
    """'personal-or-workspace' for the documented grn_ prefix, else 'unknown'. Never the key."""
    return "grn" if key.startswith("grn_") else "unknown"


# --- HTTP -----------------------------------------------------------------------------


def _default_opener(req: Request, timeout: float):
    return urlopen(req, timeout=timeout)


def _error_fields(e: HTTPError) -> tuple[str, str]:
    try:
        body = json.loads(e.read().decode("utf-8", "replace") or "{}")
    except Exception:  # noqa: BLE001
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    return str(body.get("code") or ""), str(body.get("message") or "")


_FATAL = {
    "MISSING_API_KEY": "Granola did not receive the API key",
    "INVALID_API_KEY": "Granola refused the API key (unknown, revoked or expired); create a new "
    "personal key in Settings -> Connectors -> API keys",
    "ACCOUNT_SUSPENDED": "the Granola account that created the key is suspended",
    "SUBSCRIPTION_INACTIVE": "the workspace's Granola subscription is not active (the API needs a "
    "Business plan); on Basic use the CSV export, gr-l0-import-csv.py",
    "IP_ALLOWLIST_DENIED": "this network is outside the workspace's IP allowlist",
}


class GranolaClient:
    """Small read-only Granola API client (GET only). `opener(Request, timeout)` is injectable."""

    def __init__(self, api_key: str, opener=None, delay: float = REQUEST_DELAY, sleep=None):
        self._key = api_key
        self._open = opener or _default_opener
        self._delay = delay
        self._sleep = sleep or time.sleep
        self._last = 0.0
        self.requests = 0

    def _wait(self) -> None:
        gap = time.time() - self._last
        if gap < self._delay:
            self._sleep(self._delay - gap)
        self._last = time.time()

    def get(self, path: str, **params) -> dict:
        q = {k: v for k, v in params.items() if v not in (None, "")}
        url = f"{API_BASE}{path}" + (f"?{urlencode(q)}" if q else "")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        for attempt in range(MAX_RETRIES):
            self._wait()
            self.requests += 1
            try:
                with self._open(Request(url, headers=headers), REQUEST_TIMEOUT_SECS) as resp:
                    return json.loads(resp.read() or b"{}")
            except HTTPError as e:
                code, message = _error_fields(e)
                if e.code == 429:
                    retry = e.headers.get("Retry-After") if e.headers else None
                    self._sleep(float(retry) if retry and retry.isdigit() else 5 * (attempt + 1))
                    continue
                if e.code >= 500:
                    self._sleep(2 * (attempt + 1))
                    continue
                if code in _FATAL or e.code == 401:
                    raise AuthError(_FATAL.get(code, _FATAL["INVALID_API_KEY"])) from None
                raise ApiHTTPError(e.code, code, message, path) from None
            except URLError as e:
                if attempt == MAX_RETRIES - 1:
                    raise GranolaError(f"network error talking to Granola: {e.reason}") from None
                self._sleep(2 * (attempt + 1))
        raise GranolaError(f"Granola kept failing after {MAX_RETRIES} attempts on {path}")

    # -- the three endpoints the plugin uses -------------------------------------------

    def list_notes(self, **filters):
        """Every NoteSummary of GET /v1/notes, following `cursor` while `hasMore`."""
        cursor = ""
        while True:
            data = self.get("/notes", page_size=LIST_PAGE_SIZE, cursor=cursor, **filters)
            yield from data.get("notes") or []
            cursor = data.get("cursor") or ""
            if not data.get("hasMore") or not cursor:
                return

    def get_note(self, note_id: str, transcript: bool = True) -> dict:
        nid = quote(note_id, safe="")
        if transcript:
            return self.get(f"/notes/{nid}", include="transcript")
        return self.get(f"/notes/{nid}")

    def get_transcript(self, note_id: str) -> list[dict]:
        """The whole transcript of one note, page by page (for TRANSCRIPT_TOO_LARGE)."""
        nid = quote(note_id, safe="")
        items: list[dict] = []
        cursor = ""
        while True:
            data = self.get(
                f"/notes/{nid}/transcript", page_size=TRANSCRIPT_PAGE_SIZE, cursor=cursor
            )
            items.extend(data.get("transcript") or [])
            cursor = data.get("cursor") or ""
            if not data.get("hasMore") or not cursor:
                return items


# --- helpers --------------------------------------------------------------------------


def iso(ts) -> str:
    """ISO 8601 in UTC ('...Z'); '' when missing, the input unchanged when unparseable."""
    if not ts:
        return ""
    s = str(ts).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def safe_name(note_id: str) -> str:
    """A file name for a note id: the API id as is, anything else reduced to [A-Za-z0-9_-]."""
    s = str(note_id or "").strip()
    return s if NOTE_ID_RE.match(s) else re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:80] or "note"


def speaker_label(speaker: dict | None) -> str:
    """Readable speaker of a transcript item: name, else Me/Them, else the diarization label."""
    sp = speaker or {}
    if sp.get("name"):
        return str(sp["name"]).strip()
    attribution = str(sp.get("attribution") or "")
    if attribution == "me":
        return "Me"
    if attribution == "them":
        return "Them"
    if sp.get("diarization_label"):
        return str(sp["diarization_label"]).strip()
    return {"microphone": "Me", "speaker": "Them"}.get(str(sp.get("source") or ""), "")


def transcript_to_text(items: list[dict] | None) -> str:
    """'Speaker: words' lines, consecutive items of the same speaker joined."""
    lines: list[str] = []
    last, buf = None, []

    def flush():
        if buf:
            words = " ".join(buf).strip()
            lines.append(f"{last}: {words}" if last else words)

    for it in items or []:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        who = speaker_label(it.get("speaker"))
        if who != last:
            flush()
            last, buf = who, []
        buf.append(text)
    flush()
    return "\n".join(lines)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    sbk_config.safe_write_json(path, data)
