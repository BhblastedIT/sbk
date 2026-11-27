#!/usr/bin/env python3
"""Linear plugin, shared code for ln-l0-download.py and ln-l1-enrich.py.

Read-only by construction: the client sends GraphQL *queries* only, to
https://api.linear.app/graphql, with your own personal API key. A document that
contains a mutation or a subscription is refused before it leaves the machine
(a test checks it), and the key can be created with the Read permission only.

What it reads, for the user that owns the key, in the one workspace the key
belongs to:
  * who you are (viewer) and the workspace name;
  * the issues you are assigned to, the issues you created and, unless you turn
    it off, the issues you are subscribed to: title, identifier, description,
    status, team, project, priority, labels, due date, assignee, creator,
    subscribers, dates (created, updated, started, completed, cancelled,
    archived);
  * the comments on those issues (yours and everyone else's), with their author.

Vendor facts this code relies on (checked on linear.app, 2026-11-25):
  * endpoint https://api.linear.app/graphql; a personal API key goes in the
    header `Authorization: <API_KEY>` (no "Bearer"); keys are created in
    Settings > Account > Security & Access, with full access or only some
    permissions (Read, Write, Admin, Create issues, Create comments), optionally
    only some teams. Admins can stop members from creating keys (Settings >
    Administration > API > Member API keys):
    https://linear.app/developers/graphql
    https://linear.app/docs/api-and-webhooks
  * Relay cursor pagination (first/after, pageInfo.hasNextPage/endCursor), 50
    results by default, `orderBy: updatedAt`, archived items only with
    `includeArchived: true`: https://linear.app/developers/pagination
  * filters with comparators (eq, in, gte...) and relations (assignee, creator,
    subscribers): https://linear.app/developers/filtering
  * API key: 2,500 requests and 3,000,000 complexity points per hour per user
    (Business 2x, Enterprise 5x), at most 10,000 points per query; over the limit
    HTTP 429 with error code RATELIMITED and a Retry-After header;
    X-RateLimit-Requests-Remaining / -Reset (epoch ms) on every answer:
    https://linear.app/developers/rate-limiting
  * an answer can be HTTP 200 with an `errors` array (partial success):
    https://linear.app/developers/graphql#error-handling
  * field and filter names (isMe, subscribers.some, dueDate as YYYY-MM-DD,
    WorkflowState.type values, IssueIDComparator) from Linear's published schema,
    github.com/linear/linear packages/sdk/src/schema.graphql, commit 31f4dd9
    (2026-11-25).
Not found in Linear's docs, so handled defensively: the exact status code of a
refused key (401 or an AUTHENTICATION_ERROR code are both treated as refused).
Redirects are never followed, so the key cannot be carried to another host.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import HTTPRedirectHandler

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("ln")

SOURCE_ID = "linear"
API = "https://api.linear.app/graphql"
USER_AGENT = "sbk-linear-plugin"

KEYCHAIN_SERVICE = "sbk-linear"
KEYCHAIN_ACCOUNT = "api-key"
#: Read after the Keychain.
ENV_VARS = ("LINEAR_API_KEY",)

#: Data paths (own module, not sbk_config).
LN_DIR = cfg.DATA_ROOT / "linear"
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
STATE_FILE = "state.json"
SUMMARY_FILE = "download-summary.json"
ME_FILE = "me.json"
ISSUES_FILE = "issues.json"
COMMENTS_FILE = "comments.json"
CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

ISSUE_PAGE = 50
COMMENT_PAGE = 100
SUBSCRIBERS_PER_ISSUE = 25
LABELS_PER_ISSUE = 10
REFRESH_CHUNK = 50
TEXT_MAX = 4000
MAX_WAIT_S = 3700  # never sleep longer than one rate-limit window

NO_KEY_MSG = (
    "linear: no API key found (Keychain sbk-linear/api-key, or LINEAR_API_KEY in .env); "
    "see docs/CONNECTING.md#linear"
)
REFUSED_MSG = (
    "linear: the API key was refused (expired, revoked, or member keys turned off by an admin); "
    "see docs/CONNECTING.md#linear"
)

# --------------------------------------------------------------------------- queries

_USER = "id name displayName email title url app guest isMe active"

VIEWER_QUERY = "query SbkViewer { viewer { " + _USER + " organization { name urlKey } } }"

_ISSUE = (
    "id identifier title description url priority priorityLabel dueDate "
    "createdAt updatedAt startedAt completedAt canceledAt archivedAt "
    "state { name type } team { key name } project { name url } "
    "assignee { " + _USER + " } creator { " + _USER + " } "
    f"labels(first: {LABELS_PER_ISSUE}) {{ nodes {{ name }} }} "
    f"subscribers(first: {SUBSCRIBERS_PER_ISSUE}) {{ nodes {{ " + _USER + " } } "
)

# About 3,600 complexity points per page (Linear counts 1 per object, 0.1 per
# field, connections multiplied by `first`): well under the 10,000 per query.
ISSUES_QUERY = (
    "query SbkIssues($filter: IssueFilter, $after: String) { "
    f"issues(filter: $filter, first: {ISSUE_PAGE}, after: $after, includeArchived: true, "
    "orderBy: updatedAt) { nodes { " + _ISSUE + "} pageInfo { hasNextPage endCursor } } }"
)

COMMENTS_QUERY = (
    "query SbkComments($filter: CommentFilter, $after: String) { "
    f"comments(filter: $filter, first: {COMMENT_PAGE}, after: $after, includeArchived: true, "
    "orderBy: updatedAt) { nodes { id body url createdAt updatedAt editedAt "
    "user { " + _USER + " } externalUser { id name displayName email } "
    "issue { id identifier title } } pageInfo { hasNextPage endCursor } } }"
)

ALL_QUERIES = (VIEWER_QUERY, ISSUES_QUERY, COMMENTS_QUERY)

_WRITE_OP = re.compile(r"\b(mutation|subscription)\b", re.IGNORECASE)


def is_read_only(document: str) -> bool:
    """True when the document is a query and names no mutation or subscription."""
    doc = document.strip()
    return (doc.startswith("query") or doc.startswith("{")) and not _WRITE_OP.search(doc)


# --------------------------------------------------------------------------- key


class NoKey(RuntimeError):
    pass


class LinearError(RuntimeError):
    def __init__(self, status: int, message: str = "", code: str = ""):
        self.status = status
        self.code = code
        super().__init__(f"HTTP {status}{' ' + code if code else ''}: {message[:200]}")


class KeyRefused(LinearError):
    pass


def resolve_key() -> tuple[str, str]:
    """(api key, where it came from). Keychain first, then the environment."""
    try:
        from secrets_adapter import get_secret

        key = get_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if key and key.strip():
            return key.strip(), f"keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"
    except Exception as exc:  # noqa: BLE001 - keyring missing or locked: try env
        log.debug("keychain lookup failed: %s", exc)
    for name in ENV_VARS:
        key = (os.environ.get(name) or "").strip()
        if key:
            return key, f"env {name}"
    raise NoKey(NO_KEY_MSG)


# --------------------------------------------------------------------------- client


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header (your
    key) to whatever host the redirect names. A 3xx becomes an error answer."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def _urllib_transport(url: str, body: bytes, headers: dict, timeout: float):
    """POST with urllib: (status, lower-case headers, body bytes). Network errors raise OSError."""
    from urllib.error import HTTPError
    from urllib.request import Request, build_opener

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with build_opener(_NoRedirect()).open(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        return e.code, hdrs, e.read() or b""


class Client:
    """Query-only Linear GraphQL client with rate-limit handling and pagination."""

    def __init__(
        self,
        api_key: str,
        transport: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_retries: int = 5,
    ):
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._clock = clock
        self.max_retries = max_retries
        self._headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self.calls = 0
        self.requests_remaining: str | None = None
        self.complexity_remaining: str | None = None
        self.max_complexity_seen = 0
        self._pause_until = 0.0

    def query(self, document: str, variables: dict | None = None) -> dict:
        """The `data` of one GraphQL query. Raises LinearError on any error in the answer."""
        if not is_read_only(document):
            raise LinearError(0, "refusing to send a document that is not a read-only query")
        body = json.dumps({"query": document, "variables": variables or {}}).encode("utf-8")
        attempt = 0
        while True:
            if self._pause_until > self._clock():
                self._sleep(min(self._pause_until - self._clock(), MAX_WAIT_S))
            self.calls += 1
            try:
                status, h, raw = self._transport(API, body, self._headers, 60)
            except OSError as exc:  # network error: back off and retry
                attempt += 1
                if attempt > self.max_retries:
                    raise LinearError(0, f"network: {exc}") from exc
                self._sleep(min(2**attempt, 60))
                continue
            self._note_limits(h)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                payload = {}
            errors = (payload.get("errors") or []) if isinstance(payload, dict) else []
            codes = {str(((e or {}).get("extensions") or {}).get("code") or "") for e in errors}
            first_msg = str((errors[0] or {}).get("message") or "") if errors else ""
            if status == 429 or "RATELIMITED" in codes:
                attempt += 1
                if attempt > self.max_retries:
                    raise LinearError(status, "rate limited, gave up after retries", "RATELIMITED")
                wait = self._rate_wait(h, attempt)
                log.warning("linear: rate limited, waiting %ss", int(wait))
                self._sleep(wait)
                continue
            if status == 401 or "AUTHENTICATION_ERROR" in codes:
                raise KeyRefused(
                    status, first_msg or "authentication failed", "AUTHENTICATION_ERROR"
                )
            if status >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    raise LinearError(status, first_msg or raw[:200].decode("utf-8", "replace"))
                self._sleep(min(2**attempt, 60))
                continue
            if status != 200 or errors:
                code = next((c for c in codes if c), "")
                raise LinearError(status, first_msg or "unexpected answer", code)
            return payload.get("data") or {}

    def _note_limits(self, h: dict) -> None:
        self.requests_remaining = h.get("x-ratelimit-requests-remaining", self.requests_remaining)
        self.complexity_remaining = h.get(
            "x-ratelimit-complexity-remaining", self.complexity_remaining
        )
        try:
            self.max_complexity_seen = max(
                self.max_complexity_seen, int(h.get("x-complexity") or 0)
            )
        except ValueError:
            pass
        # Out of requests for this window: wait for the reset before the next call.
        if h.get("x-ratelimit-requests-remaining") == "0":
            reset = _reset_seconds(h.get("x-ratelimit-requests-reset"))
            if reset:
                self._pause_until = reset + 1

    def _rate_wait(self, h: dict, attempt: int) -> float:
        ra = h.get("retry-after")
        if ra:
            try:
                return max(1.0, min(float(ra), MAX_WAIT_S))
            except ValueError:
                pass
        for name in (
            "x-ratelimit-requests-reset",
            "x-ratelimit-complexity-reset",
            "x-ratelimit-endpoint-requests-reset",
        ):
            reset = _reset_seconds(h.get(name))
            if reset and reset > self._clock():
                return max(1.0, min(reset - self._clock() + 1, MAX_WAIT_S))
        return float(min(60 * (2 ** (attempt - 1)), MAX_WAIT_S))

    def paginate(self, document: str, field: str, variables: dict | None = None):
        """Every node of the connection `field`, following pageInfo.endCursor."""
        after: str | None = None
        while True:
            data = self.query(document, {**(variables or {}), "after": after})
            conn = data.get(field) or {}
            yield from conn.get("nodes") or []
            info = conn.get("pageInfo") or {}
            if not info.get("hasNextPage") or not info.get("endCursor"):
                return
            after = info["endCursor"]


def _reset_seconds(value) -> float | None:
    """Linear's reset headers are UTC epoch milliseconds."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v / 1000.0 if v > 0 else None


# --------------------------------------------------------------------------- helpers


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value) -> str:
    """Linear timestamp or datetime -> ISO 8601 with +00:00, '' if empty."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return s


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _trim(text, n: int = TEXT_MAX) -> str:
    return (text or "")[:n]


def slim_user(u: dict | None) -> dict:
    if not u:
        return {}
    return {
        "id": u.get("id") or "",
        "name": u.get("name") or "",
        "displayName": u.get("displayName") or "",
        "email": u.get("email") or "",
        "title": u.get("title") or "",
        "url": u.get("url") or "",
        "app": bool(u.get("app")),
        "guest": bool(u.get("guest")),
        "isMe": bool(u.get("isMe")),
        "active": u.get("active", True) is not False,
    }


def slim_issue(it: dict) -> dict:
    return {
        "id": it.get("id") or "",
        "identifier": it.get("identifier") or "",
        "title": it.get("title") or "",
        "description": _trim(it.get("description")),
        "url": it.get("url") or "",
        "priority": it.get("priority"),
        "priorityLabel": it.get("priorityLabel") or "",
        "dueDate": it.get("dueDate") or "",
        "createdAt": it.get("createdAt") or "",
        "updatedAt": it.get("updatedAt") or "",
        "startedAt": it.get("startedAt") or "",
        "completedAt": it.get("completedAt") or "",
        "canceledAt": it.get("canceledAt") or "",
        "archivedAt": it.get("archivedAt") or "",
        "state": {
            "name": (it.get("state") or {}).get("name") or "",
            "type": (it.get("state") or {}).get("type") or "",
        },
        "team": {
            "key": (it.get("team") or {}).get("key") or "",
            "name": (it.get("team") or {}).get("name") or "",
        },
        "project": {
            "name": (it.get("project") or {}).get("name") or "",
            "url": (it.get("project") or {}).get("url") or "",
        }
        if it.get("project")
        else {},
        "assignee": slim_user(it.get("assignee")),
        "creator": slim_user(it.get("creator")),
        "labels": [lb.get("name", "") for lb in ((it.get("labels") or {}).get("nodes") or [])],
        "subscribers": [
            slim_user(s) for s in ((it.get("subscribers") or {}).get("nodes") or []) if s
        ],
    }


def slim_comment(c: dict) -> dict:
    ext = c.get("externalUser") or {}
    issue = c.get("issue") or {}
    return {
        "id": c.get("id") or "",
        "body": _trim(c.get("body")),
        "url": c.get("url") or "",
        "createdAt": c.get("createdAt") or "",
        "updatedAt": c.get("updatedAt") or "",
        "editedAt": c.get("editedAt") or "",
        "user": slim_user(c.get("user")),
        "externalUser": {
            "id": ext.get("id") or "",
            "name": ext.get("name") or ext.get("displayName") or "",
            "email": ext.get("email") or "",
        }
        if ext
        else {},
        "issue": {
            "id": issue.get("id") or "",
            "identifier": issue.get("identifier") or "",
            "title": issue.get("title") or "",
        },
    }


def mine_filter(include_subscribed: bool) -> dict:
    """Issues you are assigned to, you created, and (optionally) you are subscribed to."""
    ors: list[dict] = [
        {"assignee": {"isMe": {"eq": True}}},
        {"creator": {"isMe": {"eq": True}}},
    ]
    if include_subscribed:
        ors.append({"subscribers": {"some": {"isMe": {"eq": True}}}})
    return {"or": ors}


def _with_since(base: dict, since: str | None) -> dict:
    return {"and": [base, {"updatedAt": {"gte": since}}]} if since else base


# --------------------------------------------------------------------------- L0


def fetch_me(client: Client) -> dict:
    v = (client.query(VIEWER_QUERY) or {}).get("viewer") or {}
    org = v.get("organization") or {}
    me = slim_user(v)
    me["organization"] = {"name": org.get("name") or "", "urlKey": org.get("urlKey") or ""}
    return me


def fetch_issues(client: Client, since: str | None, include_subscribed: bool) -> list[dict]:
    flt = _with_since(mine_filter(include_subscribed), since)
    return [slim_issue(n) for n in client.paginate(ISSUES_QUERY, "issues", {"filter": flt})]


def fetch_comments(client: Client, since: str | None, include_subscribed: bool) -> list[dict]:
    flt = _with_since({"issue": mine_filter(include_subscribed)}, since)
    return [slim_comment(n) for n in client.paginate(COMMENTS_QUERY, "comments", {"filter": flt})]


def fetch_comments_of(client: Client, ids: list[str]) -> list[dict]:
    """Every comment of these issues, whatever its date (issues that just became yours:
    their older comments are outside the incremental window)."""
    out: list[dict] = []
    for i in range(0, len(ids), REFRESH_CHUNK):
        flt = {"issue": {"id": {"in": ids[i : i + REFRESH_CHUNK]}}}
        out += [
            slim_comment(n) for n in client.paginate(COMMENTS_QUERY, "comments", {"filter": flt})
        ]
    return out


def refresh_issues(client: Client, ids: list[str], since: str | None) -> list[dict]:
    """Issues already on disk, read again by id (an issue you were unassigned from no
    longer matches the main filter, but its new assignee must still reach the files)."""
    out: list[dict] = []
    for i in range(0, len(ids), REFRESH_CHUNK):
        flt = _with_since({"id": {"in": ids[i : i + REFRESH_CHUNK]}}, since)
        out += [slim_issue(n) for n in client.paginate(ISSUES_QUERY, "issues", {"filter": flt})]
    return out


def is_open_issue(it: dict) -> bool:
    return issue_status(it) == "open"


def run_download(
    client: Client,
    dest: Path,
    *,
    full: bool = False,
    history_days: int = 365,
    overlap_hours: int = 24,
    include_subscribed: bool = True,
    comments: bool = True,
) -> dict:
    """The whole L0. Writes under `dest`, returns the summary it also writes."""
    started = now_utc()
    stats: dict = {"run_at": iso(started)}
    raw = dest / RAW_DIR
    state = _read_json(dest / STATE_FILE, {})

    me = fetch_me(client)
    if not me.get("id"):
        raise LinearError(0, "no viewer in the answer")
    cfg.safe_write_json(raw / ME_FILE, me)
    stats["workspace"] = me["organization"]["name"]

    # A wider selection than last time (subscribed or comments turned on) needs the
    # full window again, or what changed before the saved date would never be read.
    widened = (include_subscribed and state.get("include_subscribed") is False) or (
        comments and state.get("comments") is False
    )
    incremental = not (full or not state.get("since") or widened)
    if not incremental:
        since = None if (full or not history_days) else iso(started - timedelta(days=history_days))
    else:
        since = iso(datetime.fromisoformat(state["since"]) - timedelta(hours=overlap_hours))
    stats["since"] = since or "(everything)"

    issues_path, comments_path = raw / ISSUES_FILE, raw / COMMENTS_FILE
    store: dict = {} if full else _read_json(issues_path, {})
    cstore: dict = {} if full else _read_json(comments_path, {})
    before_i, before_c = len(store), len(cstore)
    known_before = set(store)
    try:
        found = fetch_issues(client, since, include_subscribed)
        for it in found:
            store[it["id"]] = it
        stats["issues_read"] = len(found)
        seen = {it["id"] for it in found}
        stale = sorted(k for k, v in store.items() if k not in seen and is_open_issue(v))
        refreshed = refresh_issues(client, stale, since) if stale else []
        for it in refreshed:
            store[it["id"]] = it
        stats["open_issues_rechecked"] = len(stale)
        stats["open_issues_changed"] = len(refreshed)
        if comments:
            cfound = fetch_comments(client, since, include_subscribed)
            for c in cfound:
                cstore[c["id"]] = c
            stats["comments_read"] = len(cfound)
            # An issue that became yours since the last run (assigned to you today) has
            # comments older than the window: read them all once.
            new_ids = sorted(seen - known_before) if incremental else []
            older = fetch_comments_of(client, new_ids) if new_ids else []
            for c in older:
                cstore[c["id"]] = c
            stats["comments_of_new_issues"] = len(older)
    finally:
        # what was read is kept even if a later call failed; the watermark moves
        # only after a complete pass
        cfg.safe_write_json(issues_path, store)
        cfg.safe_write_json(comments_path, cstore)
    stats["issues"], stats["issues_new"] = len(store), len(store) - before_i
    stats["comments"], stats["comments_new"] = len(cstore), len(cstore) - before_c

    state.update(
        since=iso(started),
        last_run=iso(started),
        include_subscribed=bool(include_subscribed),
        comments=bool(comments),
    )
    cfg.safe_write_json(dest / STATE_FILE, state)
    stats["api_calls"] = client.calls
    stats["requests_remaining"] = client.requests_remaining
    stats["complexity_remaining"] = client.complexity_remaining
    stats["max_query_complexity"] = client.max_complexity_seen
    cfg.safe_write_json(dest / SUMMARY_FILE, stats)
    return stats


# --------------------------------------------------------------------------- L1

#: WorkflowState.type -> intake status. Linear's types: triage, backlog, unstarted,
#: started, completed, canceled, duplicate.
_STATE_STATUS = {"completed": "done", "canceled": "cancelled", "duplicate": "closed"}


def issue_status(it: dict) -> str:
    st = _STATE_STATUS.get(((it.get("state") or {}).get("type") or "").lower())
    if st:
        return st
    if it.get("completedAt"):
        return "done"
    if it.get("canceledAt"):
        return "cancelled"
    # Archived while still open: hidden in Linear, so no longer a commitment.
    if it.get("archivedAt"):
        return "closed"
    return "open"


def _is_me(u: dict, me_id: str) -> bool:
    return bool(u) and (bool(u.get("isMe")) or (bool(me_id) and u.get("id") == me_id))


def _person_key(u: dict) -> str:
    return u.get("id") or u.get("email") or u.get("name") or ""


def _display(u: dict) -> str:
    return (u.get("name") or u.get("displayName") or "").strip()


def _participant(u: dict) -> str:
    """'Name <email>' when there is an email, else the name."""
    name, email = _display(u), (u.get("email") or "").strip()
    if email:
        return f"{name} <{email}>" if name else email
    return name


def _issue_text(it: dict) -> str:
    st = it.get("state") or {}
    team = it.get("team") or {}
    lines = [f"Status: {st.get('name', '')} ({st.get('type', '')})".strip()]
    if team.get("key") or team.get("name"):
        lines.append(f"Team: {team.get('key', '')} {team.get('name', '')}".strip())
    if (it.get("project") or {}).get("name"):
        lines.append(f"Project: {it['project']['name']}")
    if it.get("priorityLabel"):
        lines.append(f"Priority: {it['priorityLabel']}")
    if it.get("dueDate"):
        lines.append(f"Due: {it['dueDate']}")
    if it.get("labels"):
        lines.append("Labels: " + ", ".join(x for x in it["labels"] if x))
    if it.get("assignee"):
        lines.append(f"Assignee: {_display(it['assignee'])}")
    head = "\n".join(lines)
    desc = (it.get("description") or "").strip()
    return _trim(f"{head}\n\n{desc}" if desc else head)


def build_frames(dest: Path):
    """(contacts, interactions) DataFrames in the generic intake contract."""
    import pandas as pd

    raw = dest / RAW_DIR
    me = _read_json(raw / ME_FILE, {}) or {}
    me_id = me.get("id", "")
    store: dict = _read_json(raw / ISSUES_FILE, {})
    cstore: dict = _read_json(raw / COMMENTS_FILE, {})

    people: dict[str, dict] = {}  # key -> user (with the richest data seen)
    per_person: dict[str, list[str]] = {}

    def keep(u: dict) -> str:
        """Register a person (not you, not an app) and return the key, '' if left out."""
        if not u or _is_me(u, me_id) or u.get("app"):
            return ""
        k = _person_key(u)
        if not k or (not _display(u) and not u.get("email")):
            return ""
        cur = people.get(k, {})
        people[k] = {**cur, **{kk: vv for kk, vv in u.items() if vv not in ("", None)}}
        return k

    rows: list[dict] = []
    issue_people: dict[str, list[str]] = {}
    for iid, it in store.items():
        assignee, creator = it.get("assignee") or {}, it.get("creator") or {}
        subs = it.get("subscribers") or []
        mine_assignee, mine_creator = _is_me(assignee, me_id), _is_me(creator, me_id)
        if mine_assignee:
            role = "assignee"
        elif mine_creator:
            role = "author"
        else:
            role = "other"  # subscribed, or no longer yours
        keys: list[str] = []
        for u in [assignee, creator, *subs]:
            k = keep(u)
            if k and k not in keys:
                keys.append(k)
        issue_people[iid] = keys
        # The due date is yours only when the issue is: assigned to you, or yours and unassigned.
        due = it.get("dueDate") or ""
        if not (mine_assignee or (mine_creator and not assignee)):
            due = ""
        ts = iso(it.get("createdAt"))
        rows.append(
            {
                "source": SOURCE_ID,
                "ts": ts,
                "kind": "issue",
                "title": f"{it.get('identifier', '')} {it.get('title', '')}".strip(),
                "text": _issue_text(it),
                "participants": "|||".join(_participant(people[k]) for k in keys),
                "owner_role": role,
                "due": due,
                "url": it.get("url") or "",
                "status": issue_status(it),
            }
        )
        for k in keys:
            per_person.setdefault(k, []).append(ts)

    for c in cstore.values():
        user = c.get("user") or {}
        ext = c.get("externalUser") or {}
        author = user or ext
        issue = c.get("issue") or {}
        ts = iso(c.get("createdAt"))
        if _is_me(user, me_id):
            role = "author"
            keys = list(issue_people.get(issue.get("id", ""), []))
        else:
            role = "other"
            k = keep(author)
            keys = [k] if k else []
        rows.append(
            {
                "source": SOURCE_ID,
                "ts": ts,
                "kind": "message",
                "title": f"Comment on {issue.get('identifier', '')} {issue.get('title', '')}".strip(),
                "text": c.get("body") or "",
                "participants": "|||".join(_participant(people[k]) for k in keys),
                "owner_role": role,
                "due": "",
                "url": c.get("url") or "",
                "status": "done",
            }
        )
        for k in keys:
            per_person.setdefault(k, []).append(ts)

    contacts: list[dict] = []
    for k in sorted(people, key=lambda x: _display(people[x]).lower()):
        u = people[k]
        stamps = sorted(t for t in per_person.get(k, []) if t)
        contacts.append(
            {
                "source": SOURCE_ID,
                "name": _display(u),
                "email": (u.get("email") or "").strip().lower(),
                "phone": "",
                "company": "",
                "title": (u.get("title") or "").strip(),
                "first_seen": stamps[0] if stamps else "",
                "last_seen": stamps[-1] if stamps else "",
                "interactions": len(per_person.get(k, [])),
                "url": u.get("url") or "",
            }
        )

    contact_cols = [
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
    inter_cols = [
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
    cdf = pd.DataFrame(contacts, columns=contact_cols)
    cdf["interactions"] = cdf["interactions"].astype("int64")
    idf = pd.DataFrame(rows, columns=inter_cols)
    if not idf.empty:
        idf = idf.sort_values("ts", kind="stable").reset_index(drop=True)
    return cdf, idf


def write_frames(dest: Path) -> dict:
    cdf, idf = build_frames(dest)
    out = dest / PROCESSED_DIR
    cfg.safe_write_parquet(cdf, out / CONTACTS_FILE, index=False)
    cfg.safe_write_parquet(idf, out / INTERACTIONS_FILE, index=False)
    by_kind = idf["kind"].value_counts().to_dict() if not idf.empty else {}
    by_status = idf["status"].value_counts().to_dict() if not idf.empty else {}
    return {
        "contacts": len(cdf),
        "interactions": len(idf),
        **{f"kind_{k}": int(v) for k, v in by_kind.items()},
        **{f"status_{k}": int(v) for k, v in by_status.items()},
    }
