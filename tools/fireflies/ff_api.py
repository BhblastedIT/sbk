"""Fireflies plugin core: your own meeting transcripts, participants, summaries, action items.

Personal access only. The plugin reads the GraphQL API with the API key of your own
Fireflies account (Integrations -> Fireflies API), sent as `Authorization: Bearer <key>`.
It asks only for meetings tied to you: the `transcripts` query filtered on your own
`user_id` (meetings where you are organizer or participant) or, with --only-organized,
on `mine: true` (meetings you organized). It never asks for another user, never uses the
team-wide Super Admin features, and sends queries only (no mutation exists here; a test
checks it).

Vendor facts this module relies on (checked on docs.fireflies.ai, 2026-11-25; the pages are
saved by the plugin author, URLs in tools/fireflies/README.md):
- endpoint https://api.fireflies.ai/graphql, POST JSON {query, variables}, header
  `Authorization: Bearer <api key>`; key from app.fireflies.ai Integrations -> Fireflies API:
  https://docs.fireflies.ai/fundamentals/authorization
- `user` without `id` = the owner of the API key: https://docs.fireflies.ai/graphql-api/query/user
- `transcripts(user_id, mine, fromDate, toDate, limit <= 50, skip)`; only one of
  organizer_email / participant_email / user_id / mine at a time:
  https://docs.fireflies.ai/graphql-api/query/transcripts and
  https://docs.fireflies.ai/additional-info/change-log (2.4.0)
- Transcript, Summary (action_items is a String), MeetingAttendeeModel, MeetingAttendance,
  Sentence, MeetingInfo.summary_status: https://docs.fireflies.ai/schema/transcript (and siblings)
- `contacts`: people who were in meetings with you: https://docs.fireflies.ai/graphql-api/query/contacts
- rate limits: Free 30/min and 500/day, Pro 60/min and 5,000/day (daily quota resets at
  midnight UTC), Business/Enterprise 60/min per paid seat, no daily cap; 429 carries
  Retry-After in seconds: https://docs.fireflies.ai/fundamentals/limits
- error shape and codes (auth_failed, too_many_requests, paid_required, ...):
  https://docs.fireflies.ai/fundamentals/errors , https://docs.fireflies.ai/miscellaneous/error-codes

NOT documented by Fireflies (so this code treats it as a guess and says so): the text layout of
`summary.action_items` (see parse_action_items), the sort order of `transcripts`, and the largest
`skip` it accepts. Nothing here prints or logs the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

SOURCE = "fireflies"
API_URL = "https://api.fireflies.ai/graphql"
KEYCHAIN_SERVICE = "sbk-fireflies"
KEYCHAIN_ACCOUNT = "api-key"
ENV_API_KEY = "FIREFLIES_API_KEY"
SETUP_HINT = "see docs/CONNECTING.md#fireflies"
NO_KEY_MSG = (
    f"Fireflies: no API key found (Keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}, or "
    f"{ENV_API_KEY} in .env); {SETUP_HINT}"
)

# Free allows 30 requests a minute: one every 2.1 s fits every plan.
REQUEST_DELAY = 2.1
REQUEST_TIMEOUT_SECS = 90
MAX_RETRIES = 5
PAGE_LIMIT = 50  # Fireflies: at most 50 transcripts per query
WINDOW_DAYS = 30  # one listing per window keeps `skip` small
# A 429 that asks to wait longer than this is the daily quota (or a long block): stop
# cleanly and keep what was downloaded, instead of sleeping for hours.
MAX_SHORT_WAIT_SECS = 90
# Default cap on requests per run, under the Free plan's 500 a day.
DEFAULT_MAX_REQUESTS = 400
MULTI_SEP = "|||"
TEXT_MAX = 20000

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
    "status",  # optional in the kernel contract: meetings "done", action items "open"
]

# Fields of one meeting asked in the listing (no sentences: they are fetched one meeting
# at a time, and only once). audio_url / video_url are never asked.
MEETING_FIELDS = """
      id
      title
      dateString
      date
      duration
      organizer_email
      participants
      fireflies_users
      transcript_url
      meeting_link
      calendar_id
      cal_id
      is_live
      user { user_id email name }
      speakers { id name }
      meeting_attendees { displayName email phoneNumber name }
      meeting_attendance { name join_time leave_time }
      meeting_info { fred_joined silent_meeting summary_status }
      summary {
        overview
        short_summary
        gist
        action_items
        keywords
        topics_discussed
        meeting_type
      }
"""

ME_QUERY = "query Me { user { user_id email name } }"
CONTACTS_QUERY = "query Contacts { contacts { email name last_meeting_date } }"
LIST_BY_USER_QUERY = (
    "query MyTranscripts($userId: String, $fromDate: DateTime, $toDate: DateTime, "
    "$limit: Int, $skip: Int) {\n"
    "  transcripts(user_id: $userId, fromDate: $fromDate, toDate: $toDate, "
    "limit: $limit, skip: $skip) {" + MEETING_FIELDS + "  }\n}"
)
LIST_MINE_QUERY = (
    "query MyOrganizedTranscripts($fromDate: DateTime, $toDate: DateTime, "
    "$limit: Int, $skip: Int) {\n"
    "  transcripts(mine: true, fromDate: $fromDate, toDate: $toDate, "
    "limit: $limit, skip: $skip) {" + MEETING_FIELDS + "  }\n}"
)
ONE_QUERY = (
    "query OneTranscript($id: String!) {\n  transcript(id: $id) {" + MEETING_FIELDS + "  }\n}"
)
SENTENCES_QUERY = (
    "query TranscriptText($id: String!) {\n"
    "  transcript(id: $id) { id sentences { index speaker_name speaker_id text start_time "
    "end_time } }\n}"
)
ALL_QUERIES = (
    ME_QUERY,
    CONTACTS_QUERY,
    LIST_BY_USER_QUERY,
    LIST_MINE_QUERY,
    ONE_QUERY,
    SENTENCES_QUERY,
)


class FirefliesError(Exception):
    """A Fireflies problem worth one clear line to the user (never carries the key)."""


class NoApiKey(FirefliesError):
    pass


class AuthError(FirefliesError):
    pass


class DailyLimitReached(FirefliesError):
    """The daily quota (or the run's own request cap): stop and keep what was downloaded."""


class GraphQLError(FirefliesError):
    def __init__(self, code: str, message: str, status: int | None = None):
        self.code = code or "unknown"
        self.status = status
        super().__init__(f"{self.code}: {message[:200]}")


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def ff_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "fireflies"


def raw_dir() -> Path:
    return ff_dir() / "raw"


def processed_dir() -> Path:
    return ff_dir() / "processed"


def meetings_dir() -> Path:
    return raw_dir() / "meetings"


def sentences_dir() -> Path:
    return raw_dir() / "transcripts"


def state_path() -> Path:
    return raw_dir() / "state.json"


def summary_path() -> Path:
    return ff_dir() / "download-summary.json"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "fireflies" section, read without touching sbk_config) --


def cfg(key: str, default):
    return sbk_config.user_cfg(f"fireflies.{key}", default)


def resolve_api_key() -> tuple[str, str]:
    """(api key, where it came from). Keychain first, then the environment."""
    try:
        from secrets_adapter import get_secret

        key = (get_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) or "").strip()
        if key:
            return key, f"Keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"
    except Exception:  # noqa: BLE001 - no keyring backend counts as "not set"
        pass
    key = os.environ.get(ENV_API_KEY, "").strip()
    if key:
        return key, f"env {ENV_API_KEY}"
    raise NoApiKey(NO_KEY_MSG)


def load_dotenv_if_present() -> None:
    """Load <repo>/.env without overriding the shell, as the other download scripts do."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_TOOLS_DIR.parent / ".env", override=False)


# --- HTTP / GraphQL ---------------------------------------------------------------------


def _default_opener(req: Request, timeout: float):
    return urlopen(req, timeout=timeout)


def _first_error(payload) -> tuple[str, str, int | None]:
    """(code, message, status) of the first GraphQL error, or ('', '', None)."""
    if not isinstance(payload, dict):
        return "", "", None
    errs = payload.get("errors") or []
    if not errs or not isinstance(errs[0], dict):
        return "", "", None
    e = errs[0]
    ext = e.get("extensions") if isinstance(e.get("extensions"), dict) else {}
    code = str(e.get("code") or ext.get("code") or "")
    status = ext.get("status")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    return code, str(e.get("message") or ""), status


def _retry_after_secs(headers, payload, now_ms: float) -> float | None:
    """Seconds to wait from Retry-After, else from extensions.metadata.retryAfter (epoch ms)."""
    ra = headers.get("Retry-After") if headers else None
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            pass
    try:
        meta = payload["errors"][0]["extensions"]["metadata"]
        return max(0.0, (float(meta["retryAfter"]) - now_ms) / 1000.0)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class Client:
    """Query-only GraphQL client. `opener(Request, timeout)` is injectable for tests."""

    def __init__(
        self,
        api_key: str,
        opener=None,
        delay: float = REQUEST_DELAY,
        sleep=None,
        clock=None,
        max_requests: int | None = None,
    ):
        self._key = api_key
        self._open = opener or _default_opener
        self._delay = delay
        self._sleep = sleep or time.sleep
        self._clock = clock or time.time
        self.max_requests = max_requests
        self._last = 0.0
        self.requests = 0
        self.rate_limit: str | None = None
        self.rate_remaining: str | None = None
        self.partial_errors: list[str] = []

    def _wait(self) -> None:
        gap = self._clock() - self._last
        if self._last and gap < self._delay:
            self._sleep(self._delay - gap)
        self._last = self._clock()

    def query(self, query: str, variables: dict | None = None) -> dict:
        """Send one query; return `data`. Raises FirefliesError subclasses."""
        if query.lstrip().lower().startswith("mutation"):
            raise FirefliesError("refusing to send a mutation: this plugin only reads")
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        for attempt in range(MAX_RETRIES):
            if self.max_requests is not None and self.requests >= self.max_requests:
                raise DailyLimitReached(
                    f"request cap of this run reached ({self.max_requests}, fireflies.max_requests); "
                    "what was downloaded is kept and the rest is asked next run"
                )
            self._wait()
            self.requests += 1
            req = Request(
                API_URL,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "sbk-fireflies-plugin",
                },
            )
            try:
                with self._open(req, REQUEST_TIMEOUT_SECS) as resp:
                    headers = getattr(resp, "headers", None)
                    raw = resp.read()
                status = 200
            except HTTPError as e:
                headers, status = e.headers, e.code
                try:
                    raw = e.read()
                except Exception:  # noqa: BLE001
                    raw = b""
            except URLError as e:
                if attempt == MAX_RETRIES - 1:
                    raise FirefliesError(
                        f"network error talking to Fireflies: {e.reason}"
                    ) from None
                self._sleep(2 * (attempt + 1))
                continue
            if headers is not None:
                self.rate_limit = headers.get("X-RateLimit-Limit") or self.rate_limit
                self.rate_remaining = headers.get("X-RateLimit-Remaining") or self.rate_remaining
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                payload = {}
            code, message, gql_status = _first_error(payload)
            eff = gql_status or status
            if code == "too_many_requests" or status == 429 or eff == 429:
                wait = _retry_after_secs(headers, payload, self._clock() * 1000)
                if wait is None or wait > MAX_SHORT_WAIT_SECS:
                    raise DailyLimitReached(
                        "Fireflies rate limit reached (daily quota or a long block); what was "
                        "downloaded is kept and the rest is asked next run"
                    )
                self._sleep(wait + 1)
                continue
            if code in ("auth_failed", "invalid_api_key") or status == 401 or eff == 401:
                raise AuthError(
                    "Fireflies refused the API key (auth_failed); copy it again from "
                    f"app.fireflies.ai Integrations -> Fireflies API; {SETUP_HINT}"
                )
            if status >= 500 or code in ("request_timeout", "invariant_violation"):
                if attempt == MAX_RETRIES - 1:
                    raise FirefliesError(
                        f"Fireflies kept failing after {MAX_RETRIES} attempts "
                        f"({code or 'HTTP ' + str(status)})"
                    )
                self._sleep(2 * (attempt + 1))
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict) and data and all(v is None for v in data.values()):
                data = None  # {"transcripts": null} next to an error: nothing usable
            if code and not data:
                raise GraphQLError(code, message, eff)
            if code:  # partial answer: keep the data, remember the error once per code
                if code not in self.partial_errors:
                    self.partial_errors.append(code)
            if status >= 400 and not data:
                raise GraphQLError(f"http_{status}", message or "no data", status)
            return data or {}
        raise FirefliesError(f"Fireflies kept failing after {MAX_RETRIES} attempts")


# --- dates ----------------------------------------------------------------------------


def iso(ts) -> str:
    """ISO 8601 in UTC with 'Z'; a number is read as epoch milliseconds; '' when missing."""
    if ts is None or ts == "":
        return ""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return (
            datetime.fromtimestamp(float(ts) / 1000.0, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    s = str(ts).strip()
    if re.fullmatch(r"\d{11,14}(\.\d+)?", s):
        return iso(float(s))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def api_datetime(dt: datetime) -> str:
    """The form the transcripts query documents: YYYY-MM-DDTHH:mm:ss.sssZ."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def windows(start: datetime, end: datetime, days: int = WINDOW_DAYS):
    """[from, to) datetime pairs of at most `days` days covering start..end."""
    cur = start
    while cur < end:
        stop = min(cur + timedelta(days=days), end)
        yield cur, stop
        cur = stop


def meeting_ts(m: dict) -> str:
    return iso(m.get("dateString")) or iso(m.get("date"))


# --- names, people ----------------------------------------------------------------------


def norm_name(name) -> str:
    return " ".join(str(name or "").split()).strip()


def norm_email(email) -> str:
    e = str(email or "").strip().lower()
    return e if re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", e) else ""


# The note-taker that joins the call. Fireflies does not document how it appears in
# meeting_attendance or speakers: these patterns are a guess, kept narrow on purpose.
_BOT_NAME = re.compile(r"(notetaker|fireflies\.ai)", re.I)
_BOT_EMAILS = frozenset({"fred@fireflies.ai"})


def is_bot(name: str = "", email: str = "") -> bool:
    return bool((email and email.lower() in _BOT_EMAILS) or (name and _BOT_NAME.search(name)))


# --- action items -------------------------------------------------------------------------

_HEADER = re.compile(r"^\s*(?:#+\s*)?\*\*\s*(?P<name>[^*]{1,80}?)\s*\*\*\s*:?\s*$")
_INLINE_OWNER = re.compile(r"^\s*\*\*\s*(?P<name>[^*]{1,80}?)\s*\*\*\s*[:\-–—]\s*(?P<item>.+)$")
_BULLET = re.compile(r"^\s*(?:[-*•●▪]|\d{1,3}[.)])\s+")
_OFFSET = re.compile(r"\s*\((\d{1,2}:\d{2}(?::\d{2})?)\)\s*$")


def parse_action_items(text) -> list[dict]:
    """Split Fireflies' `summary.action_items` string into items.

    Fireflies documents the field only as "A list of action items generated by the AI"
    (type String). The layout handled here is the one its summaries use in practice:
    a bold name on its own line (`**Name**`) followed by that person's items, one per
    line, often ending with a timestamp like `(12:34)`. Also handled: `**Name**: item`
    on one line, bullets (-, *, numbers) and items with no name above them (owner "").
    Returns [{"owner": str, "item": str, "offset": "mm:ss" or ""}].
    """
    out: list[dict] = []
    owner = ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HEADER.match(line)
        if m:
            owner = norm_name(m.group("name"))
            continue
        item_owner = owner
        line = _BULLET.sub("", line).strip()
        m = _INLINE_OWNER.match(line)
        if m:
            item_owner = norm_name(m.group("name"))
            line = m.group("item").strip()
        offset = ""
        mo = _OFFSET.search(line)
        if mo:
            offset = mo.group(1)
            line = line[: mo.start()].strip()
        line = line.replace("**", "").strip()
        if line:
            out.append({"owner": item_owner, "item": line, "offset": offset})
    return out


def item_key(item: str) -> str:
    """A short stable id for an action item text (case and spaces ignored)."""
    return hashlib.sha1(norm_name(item).lower().encode()).hexdigest()[:10]


def safe_id(tid: str) -> str:
    """A file name for a transcript id (Fireflies ids are alphanumeric; anything else is
    replaced, with a hash so two ids never collide)."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", str(tid))
    if s != str(tid):
        s += "-" + hashlib.sha1(str(tid).encode()).hexdigest()[:8]
    return s[:120]


def sentences_to_text(sentences) -> str:
    """'Speaker: words' lines, consecutive sentences of one speaker joined."""
    lines: list[str] = []
    last, buf = None, []
    for s in sorted(sentences or [], key=lambda x: (x or {}).get("index") or 0):
        if not isinstance(s, dict):
            continue
        sp = norm_name(s.get("speaker_name"))
        txt = str(s.get("text") or s.get("raw_text") or "").strip()
        if not txt:
            continue
        if sp != last and buf:
            lines.append(f"{last}: {' '.join(buf)}" if last else " ".join(buf))
            buf = []
        last = sp
        buf.append(txt)
    if buf:
        lines.append(f"{last}: {' '.join(buf)}" if last else " ".join(buf))
    return "\n".join(lines)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    sbk_config.safe_write_json(path, data)
