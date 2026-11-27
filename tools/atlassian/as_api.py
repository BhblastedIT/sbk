#!/usr/bin/env python3
"""Atlassian plugin (Jira + Confluence Cloud), shared code for as-l0-download.py and as-l1-enrich.py.

Read-only by construction: the client below has one method, GET, and sends your
credential only to your own site (https://<your-site>.atlassian.net) or to
https://api.atlassian.com (the route Atlassian requires for API tokens with
scopes). No write call exists in this plugin (a test checks it).

What it reads, as you, with your own API token (basic auth email:token):
  * Jira: the issues you created or reported, are assigned to, or watch
    (enhanced JQL search, GET /rest/api/3/search/jql), with status, due date,
    reporter, creator, assignee; the watcher list of those issues
    (GET /rest/api/3/issue/{key}/watchers), re-read only when the issue changed;
  * Confluence: the pages you created or edited (CQL `contributor = currentUser()`,
    GET /rest/api/search), with creator, last editor and contributors.

Vendor facts this code relies on (checked on Atlassian's documentation on 2026-11-25,
URLs in tools/atlassian/README.md):
  * basic auth with your Atlassian account email and an API token; an API token
    with scopes must call https://api.atlassian.com/ex/jira/{cloudId} or
    https://api.atlassian.com/ex/confluence/{cloudId} instead of the site URL;
  * the cloud id of a site is returned by https://<site>/_edge/tenant_info
    (Atlassian support article; not part of the versioned REST API, so it can
    also be set by hand);
  * GET /rest/api/3/search/jql pages with nextPageToken (absent on the last page);
    the default `fields` is `id`, so the fields are always named;
  * JQL relative dates ("-90m") avoid the time zone of absolute JQL dates;
  * Confluence search pages with `_links.next` (a cursor); the user fields
    `user`, `user.fullname`... are not supported there, `contributor` and
    `creator` with currentUser() are;
  * 429 Too Many Requests carries Retry-After (seconds); some 5xx carry it too;
    back off exponentially with jitter otherwise; API-token traffic is governed
    by the burst limits;
  * emailAddress / email may be empty or null depending on each user's profile
    visibility.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("as")

SOURCE_ID = "atlassian"
GATEWAY = "https://api.atlassian.com"
USER_AGENT = "sbk-atlassian-plugin"

KEYCHAIN_SERVICE = "sbk-atlassian"
ACCOUNT_TOKEN = "api-token"  # one token for both products (a token without scopes)
ACCOUNT_JIRA = "jira-token"  # optional: a scoped token for Jira only
ACCOUNT_CONFLUENCE = "confluence-token"  # optional: a scoped token for Confluence only

ENV_SITE = "ATLASSIAN_SITE"
ENV_EMAIL = "ATLASSIAN_EMAIL"
ENV_TOKEN = "ATLASSIAN_API_TOKEN"
ENV_JIRA_TOKEN = "ATLASSIAN_JIRA_API_TOKEN"
ENV_CONFLUENCE_TOKEN = "ATLASSIAN_CONFLUENCE_API_TOKEN"
ENV_CLOUD_ID = "ATLASSIAN_CLOUD_ID"

#: Data paths (own module, not sbk_config).
AS_DIR = cfg.DATA_ROOT / "atlassian"
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
STATE_FILE = "state.json"
SUMMARY_FILE = "download-summary.json"
CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

PRODUCTS = ("jira", "confluence")
TOKEN_KINDS = ("auto", "unscoped", "scoped")
JIRA_PAGE = 100
CONFLUENCE_PAGE = 50
TEXT_MAX = 4000
OVERLAP_MIN = 60  # minutes of overlap between two incremental Jira runs
MAX_WAIT_S = 600
WATCHERS_REFRESH_DAYS = 30
DONE_CATEGORY_KEYS = frozenset({"done", "completed"})
#: Display name Atlassian gives a deleted account (lowercase), left out of people:
#: https://support.atlassian.com/confluence-cloud/docs/what-happens-when-an-account-is-deactivated-vs-deleted/
DELETED_USER_NAMES = frozenset({"former user"})

JIRA_FIELDS = (
    "summary,status,resolutiondate,duedate,created,updated,project,issuetype,"
    "priority,reporter,creator,assignee,watches,description,labels"
)
JQL_MINE = (
    "(creator = currentUser() OR reporter = currentUser() OR assignee = currentUser() "
    "OR watcher = currentUser())"
)
CQL_MINE = "type = page AND contributor = currentUser()"
CONFLUENCE_EXPAND = (
    "content.space,content.version,content.history,content.history.lastUpdated,"
    "content.history.contributors.publishers.users"
)

GUIDE = "see docs/CONNECTING.md#atlassian"


# --------------------------------------------------------------------------- errors


class NotConfigured(RuntimeError):
    pass


class AtlassianError(RuntimeError):
    def __init__(self, status: int, path: str, message: str = ""):
        self.status = status
        self.path = path
        super().__init__(f"HTTP {status} on {path}: {message[:200]}")


# --------------------------------------------------------------------------- settings


def normalize_site(value: str) -> str:
    """'demo.atlassian.net', 'https://demo.atlassian.net/wiki/home' -> 'https://demo.atlassian.net'."""
    s = (value or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    u = urlparse(s)
    if u.scheme != "https" or not u.hostname:
        raise NotConfigured(f"atlassian: the site must be an https address, got {value!r}; {GUIDE}")
    return f"https://{u.hostname.lower()}" + (f":{u.port}" if u.port else "")


def _secret(account: str) -> tuple[str, str]:
    try:
        from secrets_adapter import get_secret

        v = get_secret(KEYCHAIN_SERVICE, account)
        if v and v.strip():
            return v.strip(), f"keychain {KEYCHAIN_SERVICE}/{account}"
    except Exception as exc:  # noqa: BLE001 - keyring missing or locked: try env
        log.debug("keychain lookup failed: %s", exc)
    return "", ""


def _env(name: str) -> tuple[str, str]:
    v = (os.environ.get(name) or "").strip()
    return (v, f"env {name}") if v else ("", "")


def resolve_token(product: str) -> tuple[str, str]:
    """(token, where). Product-specific entry first, then the shared one; Keychain before env."""
    specific = ACCOUNT_JIRA if product == "jira" else ACCOUNT_CONFLUENCE
    specific_env = ENV_JIRA_TOKEN if product == "jira" else ENV_CONFLUENCE_TOKEN
    for tok, where in (
        _secret(specific),
        _env(specific_env),
        _secret(ACCOUNT_TOKEN),
        _env(ENV_TOKEN),
    ):
        if tok:
            return tok, where
    return "", ""


@dataclass
class Settings:
    site: str
    email: str
    token_kind: str = "auto"
    cloud_id: str = ""
    products: tuple[str, ...] = PRODUCTS
    # repr=False: printing or logging a Settings never shows a token
    tokens: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    jira_projects: tuple[str, ...] = ()
    confluence_spaces: tuple[str, ...] = ()


def load_settings(only: tuple[str, ...] | None = None) -> Settings:
    """Everything the download needs, or NotConfigured with one line naming what is missing."""
    site_raw = str(cfg.user_cfg("atlassian.site", "") or os.environ.get(ENV_SITE, "") or "")
    email = str(cfg.user_cfg("atlassian.email", "") or os.environ.get(ENV_EMAIL, "") or "").strip()
    products = (
        tuple(
            p
            for p in (cfg.user_cfg("atlassian.products", list(PRODUCTS)) or PRODUCTS)
            if p in PRODUCTS
        )
        or PRODUCTS
    )
    if only:
        products = tuple(p for p in PRODUCTS if p in only)
    tokens = {p: resolve_token(p) for p in products}
    missing = []
    if not site_raw.strip():
        missing.append(f"site URL (atlassian.site in sbk.config.json or {ENV_SITE})")
    if not email:
        missing.append(f"account email (atlassian.email or {ENV_EMAIL})")
    if not all(t for t, _ in tokens.values()):
        missing.append(
            f"API token (Keychain {KEYCHAIN_SERVICE}/{ACCOUNT_TOKEN} or {ENV_TOKEN} in .env)"
        )
    if missing:
        raise NotConfigured("atlassian: missing " + ", ".join(missing) + f"; {GUIDE}")
    kind = str(cfg.user_cfg("atlassian.token_kind", "auto")).strip().lower()
    if kind not in TOKEN_KINDS:
        raise NotConfigured(
            f"atlassian: token_kind must be one of {', '.join(TOKEN_KINDS)}, got {kind!r}; {GUIDE}"
        )
    return Settings(
        site=normalize_site(site_raw),
        email=email,
        token_kind=kind,
        cloud_id=str(
            cfg.user_cfg("atlassian.cloud_id", "") or os.environ.get(ENV_CLOUD_ID, "") or ""
        ).strip(),
        products=products,
        tokens=tokens,
        jira_projects=tuple(str(p) for p in (cfg.user_cfg("atlassian.jira_projects", []) or [])),
        confluence_spaces=tuple(
            str(s) for s in (cfg.user_cfg("atlassian.confluence_spaces", []) or [])
        ),
    )


# --------------------------------------------------------------------------- client


class Client:
    """GET-only client for one Atlassian site and api.atlassian.com, with retries."""

    def __init__(
        self,
        email: str,
        token: str,
        site: str,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        max_retries: int = 5,
    ):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self._sleep = sleep
        self._jitter = jitter
        self.max_retries = max_retries
        self.allowed_hosts = {urlparse(site).netloc.lower(), urlparse(GATEWAY).netloc}
        raw = f"{email}:{token}".encode()
        self._headers = {
            "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self.calls = 0

    # The only HTTP verb in the plugin.
    def get(self, url: str, params: dict | None = None):
        u = urlparse(url)
        if u.scheme != "https" or u.netloc.lower() not in self.allowed_hosts:
            raise AtlassianError(
                0, url, "refusing to send the token outside your site and api.atlassian.com"
            )
        attempt = 0
        while True:
            self.calls += 1
            try:
                resp = self.session.get(url, params=params, headers=self._headers, timeout=60)
            except Exception as exc:  # noqa: BLE001 - network error: back off and retry
                attempt += 1
                if attempt > self.max_retries:
                    raise AtlassianError(0, url, f"network: {exc}") from exc
                self._sleep(self._backoff(attempt))
                continue
            code = resp.status_code
            if 200 <= code < 300:
                return (resp.json() if resp.content else None), resp
            body = (resp.text or "")[:300]
            if code == 429 or code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    raise AtlassianError(code, url, body or "gave up after retries")
                wait = self._retry_after(resp.headers)
                wait = self._backoff(attempt) if wait is None else wait
                log.warning("HTTP %s, waiting %ss", code, round(wait, 1))
                self._sleep(wait)
                continue
            raise AtlassianError(code, url, body)

    def _retry_after(self, headers) -> float | None:
        v = headers.get("Retry-After") or headers.get("retry-after")
        if not v:
            return None
        try:
            return min(max(float(v), 1.0), MAX_WAIT_S)
        except ValueError:
            return None

    def _backoff(self, attempt: int) -> float:
        return min(2.0**attempt + self._jitter(), MAX_WAIT_S)


def fetch_cloud_id(session, site: str) -> str:
    """Cloud id of the site from <site>/_edge/tenant_info (no credential sent)."""
    resp = session.get(
        f"{site}/_edge/tenant_info",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=30,
    )
    if resp.status_code != 200:
        raise AtlassianError(resp.status_code, f"{site}/_edge/tenant_info", "cloud id not found")
    cid = ((resp.json() if resp.content else {}) or {}).get("cloudId") or ""
    if not cid:
        raise AtlassianError(0, f"{site}/_edge/tenant_info", "no cloudId in the answer")
    return cid


def base_url(product: str, route: str, site: str, cloud_id: str) -> str:
    if route == "site":
        return site if product == "jira" else f"{site}/wiki"
    return f"{GATEWAY}/ex/{product}/{cloud_id}"


PROBE = {"jira": "/rest/api/3/myself", "confluence": "/rest/api/user/current"}


def resolve_route(
    product: str, settings: Settings, client: Client, session
) -> tuple[str, str, dict]:
    """(route, base, me) for a product: 'site' for a token without scopes, 'gateway' for a scoped one."""
    routes = {"unscoped": ("site",), "scoped": ("gateway",), "auto": ("site", "gateway")}[
        settings.token_kind
    ]
    last: AtlassianError | None = None
    for route in routes:
        if route == "gateway" and not settings.cloud_id:
            settings.cloud_id = fetch_cloud_id(session, settings.site)
        base = base_url(product, route, settings.site, settings.cloud_id)
        try:
            me, _ = client.get(base + PROBE[product])
            return route, base, me or {}
        except AtlassianError as e:
            last = e
            if e.status not in (401, 403):
                raise
    assert last is not None
    raise last


# --------------------------------------------------------------------------- helpers


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value) -> str:
    """Atlassian timestamp ('2026-11-01T10:00:00.000+0000') or datetime -> ISO 8601, '' if empty."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat()
    s = str(value).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s  # a date (Jira due date): kept as is, the kernel reads it as UTC
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if len(s) > 5 and s[-5] in "+-" and s[-4:].isdigit() and ":" not in s[-5:]:
        s = s[:-2] + ":" + s[-2:]  # +0000 -> +00:00
    try:
        d = datetime.fromisoformat(s)
        d = d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
        return d.replace(microsecond=0).isoformat()
    except ValueError:
        return s


def _watermark(state: dict, key: str) -> datetime | None:
    """A watermark of state.json as an aware datetime; None when missing or unreadable,
    so a damaged state.json falls back to the first-run window instead of crashing."""
    try:
        d = datetime.fromisoformat(str(state.get(key) or ""))
    except ValueError:
        if state.get(key):
            log.warning("state.json: %s unreadable, using the first-run window", key)
        return None
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def adf_text(node, limit: int = TEXT_MAX) -> str:
    """Plain text of an Atlassian Document Format value (or a plain string)."""
    if not node:
        return ""
    if isinstance(node, str):
        return node[:limit]
    out: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text") or "")
            elif n.get("type") in ("hardBreak",):
                out.append("\n")
            elif n.get("type") == "mention":
                out.append((n.get("attrs") or {}).get("text") or "")
            for c in n.get("content") or []:
                walk(c)
            if n.get("type") in ("paragraph", "heading", "listItem", "codeBlock", "blockquote"):
                out.append("\n")
        elif isinstance(n, list):
            for c in n:
                walk(c)

    walk(node)
    return "".join(out).strip()[:limit]


def slim_user(u) -> dict:
    u = u or {}
    return {
        "accountId": u.get("accountId") or "",
        "displayName": u.get("displayName") or u.get("publicName") or "",
        "email": u.get("emailAddress") or u.get("email") or "",
        "accountType": u.get("accountType") or "",
    }


def _quote(v: str) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


# --------------------------------------------------------------------------- Jira


def build_jql(window_minutes: int | None, projects: tuple[str, ...] = ()) -> str:
    parts = [JQL_MINE]
    if projects:
        parts.append("project in (" + ", ".join(_quote(p) for p in projects) + ")")
    if window_minutes:
        parts.append(f'updated >= "-{int(window_minutes)}m"')
    return " AND ".join(parts) + " ORDER BY updated ASC"


def search_issues(client: Client, base: str, jql: str) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        params = {"jql": jql, "fields": JIRA_FIELDS, "maxResults": JIRA_PAGE}
        if token:
            params["nextPageToken"] = token
        data, _ = client.get(base + "/rest/api/3/search/jql", params)
        data = data or {}
        out.extend(data.get("issues") or [])
        token = data.get("nextPageToken")
        if not token or data.get("isLast"):
            return out


def slim_issue(it: dict, site: str) -> dict:
    f = it.get("fields") or {}
    st = f.get("status") or {}
    cat = st.get("statusCategory") or {}
    watches = f.get("watches") or f.get("watcher") or {}
    key = it.get("key") or ""
    return {
        "id": str(it.get("id") or key),
        "key": key,
        "summary": f.get("summary") or "",
        "description": adf_text(f.get("description")),
        "status": st.get("name") or "",
        "status_category": (cat.get("key") or "").lower(),
        "resolved": f.get("resolutiondate") or "",
        "due": f.get("duedate") or "",
        "created": f.get("created") or "",
        "updated": f.get("updated") or "",
        "project": (f.get("project") or {}).get("key") or "",
        "project_name": (f.get("project") or {}).get("name") or "",
        "issuetype": (f.get("issuetype") or {}).get("name") or "",
        "priority": (f.get("priority") or {}).get("name") or "",
        "labels": list(f.get("labels") or []),
        "reporter": slim_user(f.get("reporter")),
        "creator": slim_user(f.get("creator")),
        "assignee": slim_user(f.get("assignee")),
        "is_watching": bool(watches.get("isWatching")),
        "watch_count": int(watches.get("watchCount") or 0),
        "url": f"{site}/browse/{key}" if key else "",
    }


def fetch_watchers(client: Client, base: str, store: dict, cap: int, stats: dict) -> None:
    """Watcher lists of issues with more than one watcher, re-read when the issue changed."""
    fresh_after = iso(now_utc() - timedelta(days=WATCHERS_REFRESH_DAYS))
    done = 0
    for it in store.values():
        if it.get("watch_count", 0) <= 1 and not it.get("watchers"):
            continue
        if it.get("watchers_for") == it.get("updated") and it.get("watchers_at", "") >= fresh_after:
            continue
        if done >= cap:
            stats["watchers_left_for_next_run"] = stats.get("watchers_left_for_next_run", 0) + 1
            continue
        try:
            data, _ = client.get(f"{base}/rest/api/3/issue/{it['key']}/watchers")
        except AtlassianError as e:
            stats["watchers_denied"] = stats.get("watchers_denied", 0) + 1
            log.warning("  watchers of %s: HTTP %s", it.get("key"), e.status)
            continue
        it["watchers"] = [slim_user(w) for w in (data or {}).get("watchers") or []]
        it["watchers_for"] = it.get("updated", "")
        it["watchers_at"] = iso(now_utc())
        done += 1
    stats["watchers_fetched"] = done


def run_jira(
    client, base, dest: Path, state: dict, *, full, since_days, projects, max_watchers, stats, site
):
    started = now_utc()
    path = dest / RAW_DIR / "issues.json"
    old: dict = _read_json(path, {})
    store: dict = {} if full else dict(old)
    last = _watermark(state, "jira_since")
    if full:
        window = None
    elif last:
        window = math.ceil((started - last).total_seconds() / 60) + OVERLAP_MIN
    else:
        window = since_days * 1440
    stats["jira_window_minutes"] = window or "(everything)"
    found = search_issues(client, base, build_jql(window, projects))
    for raw in found:
        new = slim_issue(raw, site)
        prev = old.get(new["id"], {})
        for k in ("watchers", "watchers_for", "watchers_at"):
            if k in prev:
                new[k] = prev[k]
        store[new["id"]] = new
    stats["jira_found"] = len(found)
    try:
        fetch_watchers(client, base, store, max_watchers, stats)
    finally:
        cfg.safe_write_json(path, store)
    state["jira_since"] = iso(started)
    stats["jira_issues"] = len(store)


# --------------------------------------------------------------------------- Confluence


def build_cql(since_date: str | None, spaces: tuple[str, ...] = ()) -> str:
    parts = [CQL_MINE]
    if spaces:
        parts.append("space in (" + ", ".join(_quote(s) for s in spaces) + ")")
    if since_date:
        parts.append(f'lastmodified >= "{since_date}"')
    return " AND ".join(parts)


def search_pages(client: Client, base: str, cql: str) -> tuple[list[dict], str]:
    """(results, web base). Follows _links.next (a cursor) relative to `base`."""
    out: list[dict] = []
    web_base = ""
    url: str | None = base + "/rest/api/search"
    params: dict | None = {
        "cql": cql,
        "limit": CONFLUENCE_PAGE,
        "expand": CONFLUENCE_EXPAND,
        "excerpt": "none",
    }
    first = dict(params)
    while url:
        data, _ = client.get(url, params)
        data = data or {}
        out.extend(data.get("results") or [])
        links = data.get("_links") or {}
        web_base = web_base or links.get("base") or ""
        nxt = links.get("next")
        if not nxt or not (data.get("results") or []):
            break
        url = nxt if nxt.startswith("http") else base + nxt
        # Atlassian's example next link carries cql, limit and cursor only: the expansions
        # (creator, last editor, contributors) are sent again when the link lacks them.
        in_link = parse_qs(urlparse(url).query)
        params = {k: first[k] for k in ("expand", "excerpt") if k not in in_link} or None
    return out, web_base


def slim_page(r: dict, web_base: str) -> dict:
    c = r.get("content") or {}
    h = c.get("history") or {}
    last = h.get("lastUpdated") or {}
    ver = c.get("version") or {}
    pubs = ((h.get("contributors") or {}).get("publishers") or {}).get("users") or []
    webui = (c.get("_links") or {}).get("webui") or ""
    rel = webui or r.get("url") or ""
    return {
        "id": str(c.get("id") or r.get("url") or ""),
        "title": c.get("title") or r.get("title") or "",
        "space": (c.get("space") or {}).get("key") or "",
        "space_name": (c.get("space") or {}).get("name") or "",
        "created": h.get("createdDate") or "",
        "created_by": slim_user(h.get("createdBy")),
        "last_updated": last.get("when") or ver.get("when") or r.get("lastModified") or "",
        "last_updated_by": slim_user(last.get("by") or ver.get("by")),
        "version": ver.get("number") or last.get("number") or 0,
        "contributors": [slim_user(u) for u in pubs],
        "url": (web_base + rel) if rel.startswith("/") and web_base else rel,
    }


def run_confluence(client, base, dest: Path, state: dict, *, full, since_days, spaces, stats, site):
    started = now_utc()
    path = dest / RAW_DIR / "pages.json"
    store: dict = {} if full else _read_json(path, {})
    last = _watermark(state, "confluence_since")
    if full:
        since = None
    elif last:
        since = (last - timedelta(days=1)).date().isoformat()
    else:
        since = (started - timedelta(days=since_days)).date().isoformat()
    stats["confluence_since"] = since or "(everything)"
    results, web_base = search_pages(client, base, build_cql(since, spaces))
    web_base = web_base or f"{site}/wiki"
    for r in results:
        p = slim_page(r, web_base)
        if p["id"]:
            store[p["id"]] = p
    cfg.safe_write_json(path, store)
    state["confluence_since"] = iso(started)
    stats["confluence_found"] = len(results)
    stats["confluence_pages"] = len(store)


# --------------------------------------------------------------------------- L0


def run_download(
    settings: Settings,
    dest: Path,
    *,
    session=None,
    sleep: Callable[[float], None] = time.sleep,
    full: bool = False,
    since_days: int = 365,
    confluence_since_days: int = 180,
    max_watchers: int = 200,
    strict: bool = False,
) -> dict:
    """The whole L0. Writes under `dest`, returns the summary it also writes.

    A product that refuses the token (or is not on the site) is skipped and named in
    the summary while the other one still runs; with `strict`, or when every
    product fails, the error is raised.
    """
    if session is None:
        import requests

        session = requests.Session()
    started = now_utc()
    stats: dict = {
        "run_at": iso(started),
        "site": settings.site,
        "products": list(settings.products),
    }
    state = _read_json(dest / STATE_FILE, {})
    me_all: dict = _read_json(dest / RAW_DIR / "me.json", {})
    calls = 0
    skipped: dict[str, str] = {}
    errors: list[AtlassianError] = []
    for product in settings.products:
        token, where = settings.tokens[product]
        client = Client(settings.email, token, settings.site, session=session, sleep=sleep)
        try:
            route, base, me = resolve_route(product, settings, client, session)
            stats[f"{product}_route"], stats[f"{product}_token_from"] = route, where
            if me.get("accountId"):
                me_all.update(
                    accountId=me.get("accountId"),
                    displayName=me.get("displayName") or me.get("publicName") or "",
                    email=me.get("emailAddress") or me.get("email") or settings.email,
                )
            me_all["site"] = settings.site
            cfg.safe_write_json(dest / RAW_DIR / "me.json", me_all)
            if product == "jira":
                run_jira(
                    client,
                    base,
                    dest,
                    state,
                    full=full,
                    since_days=since_days,
                    projects=settings.jira_projects,
                    max_watchers=max_watchers,
                    stats=stats,
                    site=settings.site,
                )
            else:
                run_confluence(
                    client,
                    base,
                    dest,
                    state,
                    full=full,
                    since_days=confluence_since_days,
                    spaces=settings.confluence_spaces,
                    stats=stats,
                    site=settings.site,
                )
        except AtlassianError as e:
            if strict:
                raise
            errors.append(e)
            skipped[product] = f"HTTP {e.status}" if e.status else str(e)[:120]
            log.warning("%s skipped: %s", product, e)
        finally:
            calls += client.calls
    if errors and len(errors) == len(settings.products):
        raise errors[0]
    if skipped:
        stats["products_skipped"] = skipped
    state["last_run"] = iso(started)
    cfg.safe_write_json(dest / STATE_FILE, state)
    stats["api_calls"] = calls
    cfg.safe_write_json(dest / SUMMARY_FILE, stats)
    return stats


# --------------------------------------------------------------------------- L1


def issue_status(it: dict) -> str:
    if it.get("status_category") in DONE_CATEGORY_KEYS or it.get("resolved"):
        return "done"
    return "open"


def build_frames(dest: Path):
    """(contacts, interactions) DataFrames in the generic intake contract."""
    import pandas as pd

    raw = dest / RAW_DIR
    me_info = _read_json(raw / "me.json", {}) or {}
    me = me_info.get("accountId") or ""
    issues: dict = _read_json(raw / "issues.json", {})
    pages: dict = _read_json(raw / "pages.json", {})

    people: dict[str, dict] = {}  # accountId -> best known user
    stamps: dict[str, list[str]] = {}

    def keep(u: dict) -> bool:
        aid = u.get("accountId") or ""
        if not aid or aid == me or u.get("accountType") == "app":
            return False
        name = (u.get("displayName") or "").strip()
        email = (u.get("email") or "").strip()
        # A deleted account is shown as "Former user" (Atlassian support, "What happens when an
        # account is deactivated vs. deleted?"): every deleted person would merge into one
        # contact with that name. With no name and no email there is nothing to match on.
        if not email and (not name or name.lower() in DELETED_USER_NAMES):
            return False
        return True

    def note(u: dict) -> None:
        cur = people.setdefault(u["accountId"], dict(u))
        for k in ("displayName", "email"):
            if not cur.get(k) and u.get(k):
                cur[k] = u[k]

    def pid(u: dict) -> str:
        cur = people.get(u["accountId"], u)
        return (
            (cur.get("email") or "").strip().lower()
            or (cur.get("displayName") or "").strip()
            or u["accountId"]
        )

    def others(users: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for u in users:
            if keep(u):
                note(u)
                seen.setdefault(u["accountId"], u)
        return list(seen.values())

    def issue_users(it: dict) -> list[dict]:
        roles = [it.get("reporter") or {}, it.get("creator") or {}, it.get("assignee") or {}]
        return roles + list(it.get("watchers") or [])

    def page_users(p: dict) -> list[dict]:
        roles = [p.get("created_by") or {}, p.get("last_updated_by") or {}]
        return roles + list(p.get("contributors") or [])

    # First pass over everything: a person is then written the same way on every row
    # (the email when any record shows it), not by name on early rows and by email later.
    for it in issues.values():
        others(issue_users(it))
    for p in pages.values():
        others(page_users(p))

    rows: list[dict] = []
    for it in issues.values():
        who = others(issue_users(it))
        mine_assignee = bool(me) and (it.get("assignee") or {}).get("accountId") == me
        mine_author = bool(me) and me in {
            (it.get("reporter") or {}).get("accountId"),
            (it.get("creator") or {}).get("accountId"),
        }
        role = "assignee" if mine_assignee else "author" if mine_author else "other"
        status = issue_status(it)
        head = f"Status: {it.get('status') or '?'}"
        if it.get("project_name"):
            head += f". Project: {it['project_name']}"
        if it.get("issuetype"):
            head += f". Type: {it['issuetype']}"
        body = it.get("description") or ""
        row = {
            "source": SOURCE_ID,
            "ts": iso(it.get("created")),
            "kind": "issue",
            "title": f"{it.get('key', '')} {it.get('summary', '')}".strip(),
            "text": (head + (". " + body if body else "."))[:TEXT_MAX],
            "participants": "|||".join(pid(u) for u in who),
            "owner_role": role,
            # a due date on an issue you only watch is not your commitment: the kernel
            # counts every open row with a due date as one (plugin_intake.is_commitment)
            "due": iso(it.get("due")) if role != "other" else "",
            "url": it.get("url") or "",
            "status": status,
        }
        rows.append(row)
        for u in who:
            stamps.setdefault(u["accountId"], []).append(row["ts"])

    for p in pages.values():
        who = others(page_users(p))
        created_by_me = bool(me) and (p.get("created_by") or {}).get("accountId") == me
        title = p.get("title") or ""
        row = {
            "source": SOURCE_ID,
            "ts": iso(p.get("last_updated") or p.get("created")),
            "kind": "record",
            "title": (f"{p['space']}: {title}" if p.get("space") else title).strip(),
            "text": f"Confluence page in {p.get('space_name') or p.get('space') or 'a space'}, "
            f"version {p.get('version') or '?'}",
            "participants": "|||".join(pid(u) for u in who),
            "owner_role": "author" if created_by_me else "other",
            "due": "",
            "url": p.get("url") or "",
            "status": "",
        }
        rows.append(row)
        for u in who:
            stamps.setdefault(u["accountId"], []).append(row["ts"])

    contacts = []
    for aid, u in sorted(people.items(), key=lambda kv: (kv[1].get("displayName") or "", kv[0])):
        ts = sorted(t for t in stamps.get(aid, []) if t)
        contacts.append(
            {
                "source": SOURCE_ID,
                "name": (u.get("displayName") or "").strip(),
                "email": (u.get("email") or "").strip().lower(),
                "phone": "",
                "company": "",
                "title": "",
                "first_seen": ts[0] if ts else "",
                "last_seen": ts[-1] if ts else "",
                "interactions": len(stamps.get(aid, [])),
                "url": "",
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
    cdf = cdf[(cdf["name"] != "") | (cdf["email"] != "")].reset_index(drop=True)
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
    return {
        "contacts": len(cdf),
        "interactions": len(idf),
        **{f"kind_{k}": int(v) for k, v in by_kind.items()},
    }
