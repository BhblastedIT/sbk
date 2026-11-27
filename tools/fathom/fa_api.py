"""Fathom plugin core: your recorded meetings, invitees, summaries, transcripts, action items.

Personal access only. You generate an API key in your own Fathom account (User Settings ->
API Access) and the plugin sends it in the `X-Api-Key` header. The key sees what you can see
in Fathom: meetings you recorded and meetings shared with you or your team. By default the
plugin narrows that to the meetings *you* recorded (`recorded_by[]` = your own emails). It
never calls the admin-only endpoint (GET /users) and never uses OAuth, webhooks or
downloads. The client has one HTTP verb, GET, refuses any host but api.fathom.ai and never
follows a redirect (urllib would carry the key header to the new host).

Vendor facts this module relies on (checked on Fathom's official docs, 2026-11-25):
- API key per user, `X-Api-Key` header, base URL https://api.fathom.ai/external/v1, key sees
  only meetings you recorded or that were shared with you/your team:
  https://developers.fathom.ai/quickstart
- API access (keys and webhooks) included on all plans; page size fixed at 10 meetings,
  `next_cursor` -> `cursor`; 401 = missing/invalid/revoked key:
  https://developers.fathom.ai/faq
- GET /meetings parameters (created_after, cursor, include_transcript, include_summary,
  include_action_items, recorded_by[]) and response fields (recording_id, calendar_invitees,
  recorded_by, transcript, default_summary, action_items):
  https://developers.fathom.ai/api-reference/meetings/list-meetings
- Rate limits: 60 calls / 60 s per key; "heavy" requests (include_summary or
  include_transcript) 30 / 60 s, lowered to 5 / 60 s at busy times; 429 with Retry-After:
  https://developers.fathom.ai/api-overview
- GET /users is admin only (not used here):
  https://developers.fathom.ai/api-reference/users/list-users-and-their-permissions

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
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

SOURCE = "fathom"
API_BASE = "https://api.fathom.ai/external/v1"
USER_AGENT = "sbk-fathom-plugin"

KEYCHAIN_SERVICE = "sbk-fathom"
KEYCHAIN_ACCOUNT = "api-key"
#: Read after the Keychain. FATHOM_API_KEY_AUTH is the name Fathom's own SDKs read.
ENV_VARS = ("FATHOM_API_KEY", "FATHOM_API_KEY_AUTH")

SETUP_HINT = "see docs/CONNECTING.md#fathom"
NO_KEY_MSG = (
    "fathom: no API key found (Keychain sbk-fathom/api-key, or FATHOM_API_KEY in .env); "
    + SETUP_HINT
)

# Heavy requests (summary/transcript included) allow 30 per 60 s: one every 2.1 s stays
# under it. Light requests allow 60 per 60 s.
HEAVY_PAUSE_SECS = 2.1
LIGHT_PAUSE_SECS = 1.05
REQUEST_TIMEOUT_SECS = 60
MAX_RETRIES = 6
MAX_WAIT_SECS = 300  # never sleep longer than this on one 429
MULTI_SEP = "|||"

DEFAULT_HISTORY_DAYS = 365
DEFAULT_OVERLAP_DAYS = 14

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
    "status",  # optional in the kernel contract: meetings are done, action items open|done
]


class FathomError(Exception):
    """A Fathom problem worth one clear line to the user (never carries the key)."""


class ApiHTTPError(FathomError):
    def __init__(self, code: int, body: str):
        self.code = code
        self.body = body
        super().__init__(f"HTTP {code}: {body[:200]}")


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def fathom_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "fathom"


def raw_dir() -> Path:
    return fathom_dir() / "raw"


def meetings_dir() -> Path:
    return raw_dir() / "meetings"


def processed_dir() -> Path:
    return fathom_dir() / "processed"


def state_path() -> Path:
    return raw_dir() / "state.json"


def summary_path() -> Path:
    return fathom_dir() / "download-summary.json"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "fathom" section, read without touching sbk_config) ----


def cfg(key: str, default):
    return sbk_config.user_cfg(f"fathom.{key}", default)


def cfg_int(key: str, default: int) -> int:
    """A whole number of days from the config; a value that is not one keeps the default."""
    try:
        v = int(cfg(key, default))
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def _emails(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        e = str(v or "").strip().lower()
        if "@" in e and e not in out:
            out.append(e)
    return out


def my_emails() -> list[str]:
    """Your addresses: fathom.recorded_by first, then own_emails of sbk.config.json."""
    configured = cfg("recorded_by", []) or []
    if isinstance(configured, str):
        configured = [configured]
    return _emails(list(configured) + sorted(getattr(sbk_config, "OWN_EMAILS", set()) or []))


# --- the key ---------------------------------------------------------------------------


class NoKey(FathomError):
    pass


def resolve_key() -> tuple[str, str]:
    """(api key, where it came from). Keychain first, then the environment."""
    try:
        from secrets_adapter import get_secret

        key = (get_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) or "").strip()
        if key:
            return key, f"keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"
    except Exception:  # noqa: BLE001 - no keyring backend counts as "not set"
        pass
    for name in ENV_VARS:
        key = (os.environ.get(name) or "").strip()
        if key:
            return key, f"env {name}"
    raise NoKey(NO_KEY_MSG)


# --- HTTP -----------------------------------------------------------------------------


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect: urllib would copy the X-Api-Key header to the new URL,
    whatever its host. A 3xx surfaces as an HTTPError and the run stops with one line."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def _default_opener(req: Request, timeout: float):
    return _OPENER.open(req, timeout=timeout)


def _safe_body(e: HTTPError) -> str:
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _header(e: HTTPError, name: str) -> str:
    try:
        return str((e.headers or {}).get(name) or "")
    except Exception:  # noqa: BLE001
        return ""


class FathomClient:
    """GET-only Fathom client. `opener(Request, timeout)` and `sleep` are injectable for tests."""

    def __init__(
        self, api_key: str, opener=None, sleep=None, clock=None, pause: float | None = None
    ):
        self._key = api_key
        self._open = opener or _default_opener
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._pause = pause
        self._last = None
        self.requests = 0
        self.rate_limited = 0

    def _wait(self, heavy: bool) -> None:
        pause = (
            self._pause
            if self._pause is not None
            else (HEAVY_PAUSE_SECS if heavy else LIGHT_PAUSE_SECS)
        )
        if self._last is not None:
            gap = self._clock() - self._last
            if gap < pause:
                self._sleep(pause - gap)
        self._last = self._clock()

    # The only HTTP verb in the plugin.
    def get(self, path: str, params: list[tuple[str, str]] | None = None, heavy: bool = False):
        url = f"{API_BASE}{path}" + (f"?{urlencode(params)}" if params else "")
        if not url.startswith(API_BASE + "/"):
            raise FathomError("refusing to send the API key outside api.fathom.ai")
        headers = {
            "X-Api-Key": self._key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        for attempt in range(MAX_RETRIES):
            self._wait(heavy)
            self.requests += 1
            try:
                with self._open(
                    Request(url, headers=headers, method="GET"), REQUEST_TIMEOUT_SECS
                ) as r:
                    raw = r.read()
                    return json.loads(raw or b"{}")
            except HTTPError as e:
                body = _safe_body(e)
                if e.code == 401:
                    raise FathomError(
                        "fathom: the API key was refused (HTTP 401): wrong, revoked, or your "
                        f"Fathom user was deactivated; {SETUP_HINT}"
                    ) from None
                if e.code == 429:
                    self.rate_limited += 1
                    wait = _retry_after(e, attempt)
                    self._sleep(wait)
                    continue
                if e.code >= 500:
                    self._sleep(min(2 * (attempt + 1), 30))
                    continue
                raise ApiHTTPError(e.code, body) from None
            except URLError as e:
                if attempt == MAX_RETRIES - 1:
                    raise FathomError(
                        f"fathom: network error talking to Fathom: {e.reason}"
                    ) from None
                self._sleep(min(2 * (attempt + 1), 30))
            except ValueError:
                raise FathomError(
                    "fathom: Fathom answered with something that is not JSON"
                ) from None
        raise FathomError(
            f"fathom: Fathom kept refusing after {MAX_RETRIES} attempts ({path}); "
            "what was downloaded is kept, run again later"
        )

    def paged(self, path: str, params: list[tuple[str, str]], heavy: bool = False):
        """Every item of a cursor-paginated list (Fathom: `next_cursor` -> `cursor`)."""
        cursor = ""
        while True:
            p = list(params) + ([("cursor", cursor)] if cursor else [])
            data = self.get(path, p, heavy=heavy) or {}
            yield from data.get("items") or []
            cursor = data.get("next_cursor") or ""
            if not cursor:
                return


def _retry_after(e: HTTPError, attempt: int) -> float:
    """Seconds to wait on a 429: Retry-After, else RateLimit-Reset, else a growing pause."""
    for name in ("Retry-After", "RateLimit-Reset"):
        v = _header(e, name)
        try:
            if v:
                return max(1.0, min(float(v), MAX_WAIT_SECS))
        except ValueError:
            pass
    return float(min(15 * (attempt + 1), MAX_WAIT_SECS))


# --- helpers ---------------------------------------------------------------------------


def iso(ts) -> str:
    """ISO 8601 in UTC ('...Z' from Fathom becomes '+00:00'); '' when missing."""
    if not ts:
        return ""
    s = str(ts).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def zulu(dt: datetime) -> str:
    """A datetime as Fathom's query format, e.g. 2025-01-01T00:00:00Z."""
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_id(value) -> str:
    """The recording id when it is usable as a file name (Fathom: an integer), else ''."""
    s = str(value if value is not None else "").strip()
    return s if _SAFE_ID.match(s) else ""


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    sbk_config.safe_write_json(path, data)
