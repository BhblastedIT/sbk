#!/usr/bin/env python3
"""GitHub plugin, shared code for gh-l0-download.py, gh-l0-inventory.py and gh-l1-enrich.py.

Read-only by construction: the client below has one method, GET, against
https://api.github.com, with your own personal access token. No write call
exists in this plugin (a test checks it).

What it reads, for the account that owns the token:
  * the repositories you own, collaborate on, or reach through an organization
    you are a member of (GET /user/repos), written to github/repos.json in the
    shape tools/cross-source/xs-l1-inventario.py already reads;
  * optionally the top-level folders and README of each repository
    (github/alberi/, the same layout the inventory always had);
  * the collaborators of the repositories where you have write access
    (GET /repos/{owner}/{repo}/collaborators; GitHub refuses it otherwise);
  * issues and pull requests where you are author or assignee, open pull
    requests where your review is requested by name, and pull requests you reviewed
    (GET /search/issues), plus your own reviews on them;
  * the public profile of the people found (GET /users/{login}): name, public
    email if they chose to show one, company.

Vendor facts this code relies on (checked on docs.github.com, 2026-11-25):
  * auth header `Authorization: Bearer <token>`, `X-GitHub-Api-Version`, and a
    mandatory `User-Agent`;
  * 5,000 requests/hour for a personal token, search 30 requests/minute,
    at most 1,000 results per search;
  * on 403/429 with `x-ratelimit-remaining: 0` wait until `x-ratelimit-reset`;
    with `retry-after` wait that long; otherwise wait at least one minute and
    back off exponentially;
  * pagination via the `link` header, `rel="next"`.
URLs in tools/github/README.md.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("gh")

SOURCE_ID = "github"
API = "https://api.github.com"
#: Latest REST API version on 2026-11-25 (docs: rest/about-the-rest-api/api-versions).
#: The previous one, 2022-11-28, is supported until 2028-03-10.
API_VERSION = "2026-03-10"
USER_AGENT = "sbk-github-plugin"

KEYCHAIN_SERVICE = "sbk-github"
KEYCHAIN_ACCOUNT = "token"
#: Read after the Keychain. GITHUB_PERSONAL_ACCESS_TOKEN is the name
#: tools/monitoring/connection_checker.py already accepts.
ENV_VARS = ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN")

#: Data paths (own module, not sbk_config).
GH_DIR = cfg.DATA_ROOT / "github"
REPOS_FILE = "repos.json"
TREES_DIR = "alberi"
RAW_DIR = "raw"
PROCESSED_DIR = "processed"
STATE_FILE = "state.json"
SUMMARY_FILE = "download-summary.json"
CONTACTS_FILE = "plugin-contacts.parquet"
INTERACTIONS_FILE = "plugin-interactions.parquet"

PER_PAGE = 100
SEARCH_CAP = 1000  # GitHub returns at most 1,000 results per search
SEARCH_PAUSE_S = 2.1  # 30 search requests per minute
TEXT_MAX = 4000
README_MAX = 8000
COLLAB_REFRESH_DAYS = 7
PROFILE_REFRESH_DAYS = 30
MAX_WAIT_S = 3700  # never sleep longer than one rate-limit window
SKIP_DIRS_IN_TREE = 200

NO_TOKEN_MSG = (
    "github: no token found (Keychain sbk-github/token, or GITHUB_TOKEN in .env); "
    "see docs/CONNECTING.md#github"
)


# --------------------------------------------------------------------------- token


class NoToken(RuntimeError):
    pass


class GitHubError(RuntimeError):
    def __init__(self, status: int, path: str, message: str = ""):
        self.status = status
        self.path = path
        super().__init__(f"HTTP {status} on {path}: {message[:200]}")


def resolve_token() -> tuple[str, str]:
    """(token, where it came from). Keychain first, then the environment."""
    try:
        from secrets_adapter import get_secret

        tok = get_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if tok and tok.strip():
            return tok.strip(), f"keychain {KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT}"
    except Exception as exc:  # noqa: BLE001 - keyring missing or locked: try env
        log.debug("keychain lookup failed: %s", exc)
    for name in ENV_VARS:
        tok = (os.environ.get(name) or "").strip()
        if tok:
            return tok, f"env {name}"
    raise NoToken(NO_TOKEN_MSG)


def token_kind(token: str) -> str:
    """Kind of personal token from its documented prefix, never the token itself."""
    if token.startswith("github_pat_"):
        return "fine-grained"
    if token.startswith("ghp_"):
        return "classic"
    return "unknown"


# --------------------------------------------------------------------------- client

_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class Client:
    """GET-only GitHub REST client with rate-limit handling and pagination."""

    def __init__(
        self,
        token: str,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_retries: int = 5,
    ):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self._sleep = sleep
        self._clock = clock
        self.max_retries = max_retries
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        self.calls = 0
        self.scopes: str | None = None
        self.rate_remaining: str | None = None
        self._last_search = 0.0

    # The only HTTP verb in the plugin.
    def get(self, path_or_url: str, params: dict | None = None):
        url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
        if not url.startswith(API + "/"):
            raise GitHubError(0, url, "refusing to send the token outside api.github.com")
        attempt = 0
        while True:
            self.calls += 1
            try:
                resp = self.session.get(url, params=params, headers=self._headers, timeout=60)
            except Exception as exc:  # noqa: BLE001 - network error: back off and retry
                attempt += 1
                if attempt > self.max_retries:
                    raise GitHubError(0, url, f"network: {exc}") from exc
                self._sleep(min(2**attempt, 60))
                continue
            h = resp.headers
            if h.get("x-oauth-scopes") is not None:
                self.scopes = h.get("x-oauth-scopes")
            if h.get("x-ratelimit-remaining") is not None:
                self.rate_remaining = h.get("x-ratelimit-remaining")
            code = resp.status_code
            if 200 <= code < 300:
                return (resp.json() if resp.content else None), resp
            body = (resp.text or "")[:300]
            if code in (403, 429):
                wait = self._rate_wait(h, body, attempt, code)
                if wait is not None:
                    attempt += 1
                    if attempt > self.max_retries:
                        raise GitHubError(code, url, "rate limited, gave up after retries")
                    log.warning("rate limited (HTTP %s), waiting %ss", code, int(wait))
                    self._sleep(wait)
                    continue
                raise GitHubError(code, url, body)
            if code >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    raise GitHubError(code, url, body)
                self._sleep(min(2**attempt, 60))
                continue
            raise GitHubError(code, url, body)

    def _rate_wait(self, h, body: str, attempt: int, code: int = 403) -> float | None:
        """Seconds to wait if this 403/429 is a rate limit, None if it is a real refusal.

        A 429 is always a rate limit; a 403 only when the headers or the message say so.
        """
        if h.get("retry-after"):
            try:
                return min(float(h.get("retry-after")), MAX_WAIT_S)
            except ValueError:
                return 60.0
        if h.get("x-ratelimit-remaining") == "0":
            try:
                reset = float(h.get("x-ratelimit-reset") or 0)
            except ValueError:
                reset = 0
            return max(1.0, min(reset - self._clock() + 1, MAX_WAIT_S))
        if code == 429 or "rate limit" in body.lower():
            return min(60.0 * (2**attempt), MAX_WAIT_S)
        return None

    def paginate(self, path: str, params: dict | None = None, max_pages: int | None = None):
        url: str | None = path
        p: dict | None = {"per_page": PER_PAGE, **(params or {})}
        pages = 0
        while url:
            data, resp = self.get(url, p)
            items = data if isinstance(data, list) else (data or {}).get("items", [])
            yield from items
            pages += 1
            if max_pages and pages >= max_pages:
                return
            m = _NEXT.search(resp.headers.get("link") or "")
            url, p = (m.group(1), None) if m else (None, None)

    def _search_pause(self) -> None:
        gap = self._clock() - self._last_search
        if self._last_search and gap < SEARCH_PAUSE_S:
            self._sleep(SEARCH_PAUSE_S - gap)
        self._last_search = self._clock()

    def search_issues(self, query: str, since: str | None = None, stats: dict | None = None):
        """Every item for `query` updated at or after `since`.

        Goes past GitHub's 1,000-results cap by sorting on `updated` ascending
        and restarting from the last `updated_at` seen.
        """
        stats = stats if stats is not None else {}
        out: dict[str, dict] = {}
        lower = since
        while True:
            q = f"{query} updated:>={lower}" if lower else query
            got, total, last_upd = 0, 0, None
            for page in range(1, SEARCH_CAP // PER_PAGE + 1):
                self._search_pause()
                data, _ = self.get(
                    "/search/issues",
                    {"q": q, "sort": "updated", "order": "asc", "per_page": PER_PAGE, "page": page},
                )
                data = data or {}
                items = data.get("items") or []
                total = int(data.get("total_count") or 0)
                if data.get("incomplete_results"):
                    stats["incomplete_results"] = stats.get("incomplete_results", 0) + 1
                for it in items:
                    out[it.get("html_url") or str(it.get("id"))] = it
                    last_upd = it.get("updated_at") or last_upd
                got += len(items)
                if len(items) < PER_PAGE:
                    break
            if total <= got or not last_upd:
                return list(out.values())
            new_lower = iso(last_upd)
            if lower and new_lower <= lower:
                stats.setdefault("search_truncated", []).append(query)
                log.warning(
                    "search stuck at %s for %r: kept %d results", new_lower, query, len(out)
                )
                return list(out.values())
            lower = new_lower


# --------------------------------------------------------------------------- helpers


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value) -> str:
    """GitHub timestamp or datetime -> ISO 8601 with +00:00, '' if empty."""
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


def _key(owner: str, name: str) -> str:
    return f"{owner}__{name}"


def is_bot(login: str, typ: str = "") -> bool:
    return typ == "Bot" or str(login).endswith("[bot]")


def _trim(text, n: int = TEXT_MAX) -> str:
    return (text or "")[:n]


# --------------------------------------------------------------------------- L0 steps


def fetch_me(client: Client) -> dict:
    data, _ = client.get("/user")
    data = data or {}
    return {
        "login": data.get("login", ""),
        "name": data.get("name") or "",
        "html_url": data.get("html_url", ""),
        "type": data.get("type", ""),
    }


def fetch_repos(client: Client, skip_owners: list[str] | None = None) -> list[dict]:
    """GET /user/repos for owner, collaborator and organization_member repos."""
    skip = {s.lower() for s in (skip_owners or [])}
    out = []
    for r in client.paginate(
        "/user/repos",
        {"affiliation": "owner,collaborator,organization_member", "sort": "pushed"},
    ):
        owner = (r.get("owner") or {}).get("login", "")
        if owner.lower() in skip:
            continue
        perms = r.get("permissions") or {}
        out.append(
            {
                # the keys xs-l1-inventario.py reads (keep the names)
                "owner": owner,
                "name": r.get("name", ""),
                "descrizione": r.get("description") or "",
                "privata": bool(r.get("private")),
                "archiviata": bool(r.get("archived")),
                "fork": bool(r.get("fork")),
                "pushedAt": r.get("pushed_at") or "",
                "createdAt": r.get("created_at") or "",
                "linguaggio": r.get("language") or "",
                "temi": list(r.get("topics") or []),
                "kb": int(r.get("size") or 0),
                "url": r.get("html_url") or "",
                # extra, ignored by the inventory
                "full_name": r.get("full_name") or f"{owner}/{r.get('name', '')}",
                "owner_type": (r.get("owner") or {}).get("type", ""),
                "default_branch": r.get("default_branch") or "",
                "can_push": bool(perms.get("push") or perms.get("maintain") or perms.get("admin")),
            }
        )
    return out


def fetch_tree(client: Client, owner: str, name: str) -> dict:
    """Top-level folders and README of one repository (two calls at most)."""
    out: dict = {"cartelle": [], "file_radice": [], "readme": ""}
    try:
        data, _ = client.get(f"/repos/{owner}/{name}/contents")
    except GitHubError as e:
        out["errore"] = f"HTTP {e.status}"
        return out
    for v in data if isinstance(data, list) else []:
        # API 2026-03-10 reports submodules as type "submodule" (was "file")
        is_folder = v.get("type") in ("dir", "submodule")
        (out["cartelle"] if is_folder else out["file_radice"]).append(v.get("name", ""))
    out["cartelle"] = out["cartelle"][:SKIP_DIRS_IN_TREE]
    if any(f.lower().startswith("readme") for f in out["file_radice"]):
        try:
            rd, _ = client.get(f"/repos/{owner}/{name}/readme")
            content = (rd or {}).get("content") or ""
            out["readme"] = base64.b64decode(content).decode("utf-8", "replace")[:README_MAX]
        except (GitHubError, ValueError) as e:
            out["errore_readme"] = str(e)[:120]
    return out


def fetch_collaborators(client: Client, owner: str, name: str, affiliation: str) -> list[dict]:
    return [
        {
            "login": c.get("login", ""),
            "type": c.get("type", ""),
            "html_url": c.get("html_url", ""),
            "role_name": c.get("role_name", ""),
        }
        for c in client.paginate(
            f"/repos/{owner}/{name}/collaborators", {"affiliation": affiliation}
        )
    ]


#: (base kind, role, query template). Roles author/assignee are recomputed from
#: the item itself at L1, so an unassigned item does not keep a stale role.
WORK_QUERIES = (
    ("issue", "author", "is:issue author:{login}"),
    ("issue", "assignee", "is:issue assignee:{login}"),
    ("pr", "author", "is:pr author:{login}"),
    ("pr", "assignee", "is:pr assignee:{login}"),
    ("pr", "reviewed", "is:pr reviewed-by:{login}"),
)
#: Pending review requests on open PRs: a current-state query, read in full every
#: run. `user-review-requested:@me` matches only the requests made to you by name;
#: `review-requested:` would also match every request made to a team you are on,
#: and each of those would become a commitment of yours at L2 (owner_role
#: assignee). Syntax: docs.github.com/en/search-github/searching-on-github/
#: searching-issues-and-pull-requests, "Search by pull request review status and reviewer".
REQUESTED_QUERY = "is:pr is:open user-review-requested:@me"


def _repo_of(item: dict) -> str:
    # repository_url = https://api.github.com/repos/<owner>/<name>
    ru = item.get("repository_url") or ""
    return "/".join(ru.rstrip("/").split("/")[-2:]) if ru else ""


def slim_item(item: dict, base_kind: str) -> dict:
    pr = item.get("pull_request") or {}
    ms = item.get("milestone") or {}
    user = item.get("user") or {}
    return {
        "kind_base": "pr" if (pr or base_kind == "pr") else "issue",
        "repo": _repo_of(item),
        "number": item.get("number"),
        "title": item.get("title") or "",
        "body": _trim(item.get("body")),
        "state": item.get("state") or "",
        "draft": bool(item.get("draft")),
        "merged_at": pr.get("merged_at") or "",
        "created_at": item.get("created_at") or "",
        "updated_at": item.get("updated_at") or "",
        "closed_at": item.get("closed_at") or "",
        "user": user.get("login", ""),
        "user_type": user.get("type", ""),
        "assignees": [
            {"login": a.get("login", ""), "type": a.get("type", "")}
            for a in (item.get("assignees") or [])
        ],
        "milestone": {"title": ms.get("title") or "", "due_on": ms.get("due_on") or ""}
        if ms
        else {},
        "html_url": item.get("html_url") or "",
    }


def fetch_work(
    client: Client, login: str, store: dict, since: str | None, stats: dict
) -> dict[str, dict]:
    """Search issues/PRs/reviews and merge them into `store` (url -> item)."""
    for base, role, tmpl in WORK_QUERIES:
        found = client.search_issues(tmpl.format(login=login), since, stats)
        stats[f"search_{base}_{role}"] = len(found)
        for it in found:
            url = it.get("html_url") or ""
            prev = store.get(url, {})
            new = slim_item(it, base)
            new["roles"] = sorted(
                set(prev.get("roles", [])) | ({role} if role == "reviewed" else set())
            )
            new["my_reviews"] = prev.get("my_reviews", [])
            new["reviews_for"] = prev.get("reviews_for", "")
            store[url] = new
    # pending review requests: replace the role everywhere
    pending = client.search_issues(REQUESTED_QUERY.format(login=login), None, stats)
    stats["search_review_requested"] = len(pending)
    pending_urls = set()
    for it in pending:
        url = it.get("html_url") or ""
        pending_urls.add(url)
        prev = store.get(url, {})
        new = slim_item(it, "pr")
        new["roles"] = sorted(set(prev.get("roles", [])))
        new["my_reviews"] = prev.get("my_reviews", [])
        new["reviews_for"] = prev.get("reviews_for", "")
        store[url] = new
    for url, item in store.items():
        roles = set(item.get("roles", [])) - {"requested"}
        if url in pending_urls:
            roles.add("requested")
        item["roles"] = sorted(roles)
    return store


def fetch_my_reviews(client: Client, login: str, store: dict, cap: int, stats: dict) -> None:
    """Your own reviews on the PRs you reviewed, re-read only when the PR changed."""
    done = 0
    for item in store.values():
        if "reviewed" not in item.get("roles", []) or item.get("reviews_for") == item.get(
            "updated_at"
        ):
            continue
        if done >= cap:
            stats["reviews_left_for_next_run"] = stats.get("reviews_left_for_next_run", 0) + 1
            continue
        repo, num = item.get("repo", ""), item.get("number")
        if not repo or not num:
            continue
        try:
            mine = [
                {
                    "state": r.get("state", ""),
                    "submitted_at": r.get("submitted_at") or "",
                    "body": _trim(r.get("body")),
                    "html_url": r.get("html_url") or "",
                }
                for r in client.paginate(f"/repos/{repo}/pulls/{num}/reviews")
                if (r.get("user") or {}).get("login", "").lower() == login.lower()
            ]
        except GitHubError as e:
            stats["reviews_denied"] = stats.get("reviews_denied", 0) + 1
            log.warning("  reviews of %s#%s: HTTP %s", repo, num, e.status)
            continue
        item["my_reviews"] = mine
        item["reviews_for"] = item.get("updated_at", "")
        done += 1
    stats["reviews_fetched"] = done


def people_logins(me: str, collaborators: dict, store: dict) -> dict[str, str]:
    """login -> type for everyone except you and bots."""
    out: dict[str, str] = {}

    def add(login: str, typ: str = "") -> None:
        if login and login.lower() != me.lower() and not is_bot(login, typ):
            out.setdefault(login, typ)

    for lst in collaborators.values():
        for c in lst:
            add(c.get("login", ""), c.get("type", ""))
    for it in store.values():
        add(it.get("user", ""), it.get("user_type", ""))
        for a in it.get("assignees", []):
            add(a.get("login", ""), a.get("type", ""))
    return out


def fetch_profiles(client: Client, logins: list[str], cache: dict, cap: int, stats: dict) -> dict:
    """Public profile (name, public email, company) of each login, cached."""
    fresh_after = now_utc() - timedelta(days=PROFILE_REFRESH_DAYS)
    done = 0
    for login in sorted(logins):
        cur = cache.get(login)
        if cur and cur.get("fetched_at", "") >= iso(fresh_after):
            continue
        if done >= cap:
            stats["profiles_left_for_next_run"] = stats.get("profiles_left_for_next_run", 0) + 1
            continue
        try:
            data, _ = client.get(f"/users/{login}")
        except GitHubError as e:
            stats["profiles_failed"] = stats.get("profiles_failed", 0) + 1
            log.warning("  profile %s: HTTP %s", login, e.status)
            continue
        data = data or {}
        cache[login] = {
            "name": data.get("name") or "",
            "email": data.get("email") or "",
            "company": data.get("company") or "",
            "html_url": data.get("html_url") or f"https://github.com/{login}",
            "type": data.get("type", ""),
            "fetched_at": iso(now_utc()),
        }
        done += 1
    stats["profiles_fetched"] = done
    return cache


def write_repos_json(dest: Path, me: dict, repos: list[dict]) -> Path:
    owners = sorted({r["owner"] for r in repos})
    return cfg.safe_write_json(
        dest / REPOS_FILE,
        {
            "preso_il": iso(now_utc()),
            "login": me.get("login", ""),
            "proprietari": owners,
            "n": len(repos),
            "repo": repos,
        },
    )


def run_inventory(client: Client, dest: Path, *, trees: bool, skip_owners, full: bool, stats: dict):
    """Repos (+ optional trees). Returns (me, repos)."""
    dest.mkdir(parents=True, exist_ok=True)
    me = fetch_me(client)
    if not me["login"]:
        raise GitHubError(0, "/user", "no login in the response")
    previous = {
        _key(r.get("owner", ""), r.get("name", "")): r.get("pushedAt", "")
        for r in _read_json(dest / REPOS_FILE, {}).get("repo", [])
    }
    repos = fetch_repos(client, skip_owners)
    write_repos_json(dest, me, repos)
    stats["repos"] = len(repos)
    if trees:
        read = skipped = 0
        for r in repos:
            k = _key(r["owner"], r["name"])
            p = dest / TREES_DIR / f"{k}.json"
            if not full and p.exists():
                # The tree file records the pushedAt it was read at. repos.json is
                # not a safe watermark for trees: gh-l0-download.py rewrites it
                # without reading trees, which would hide a push from the next
                # gh-l0-inventory.py run. Older tree files without the key fall
                # back to repos.json, as the inventory always did.
                old = _read_json(p, {})
                seen = old.get("pushedAt") if "pushedAt" in old else previous.get(k)
                if seen == r["pushedAt"]:
                    skipped += 1
                    continue
            t = fetch_tree(client, r["owner"], r["name"])
            # a tree GitHub refused is read again next run, not kept until the next push
            t["pushedAt"] = "" if "errore" in t else r["pushedAt"]
            t["preso_il"] = iso(now_utc())
            cfg.safe_write_json(p, t)
            read += 1
        stats["trees_read"], stats["trees_unchanged"] = read, skipped
    return me, repos


def run_download(
    client: Client,
    dest: Path,
    *,
    steps: tuple[str, ...] = ("repos", "people", "work"),
    trees: bool = False,
    full: bool = False,
    since_days: int = 365,
    affiliation: str = "direct",
    skip_owners: list[str] | None = None,
    max_profiles: int = 300,
    max_reviews: int = 500,
) -> dict:
    """The whole L0. Writes under `dest`, returns the summary it also writes."""
    started = now_utc()
    stats: dict = {"run_at": iso(started), "steps": list(steps)}
    raw = dest / RAW_DIR
    state = _read_json(dest / STATE_FILE, {})

    if "repos" in steps:
        me, repos = run_inventory(
            client, dest, trees=trees, skip_owners=skip_owners, full=full, stats=stats
        )
    else:
        me = fetch_me(client)
        repos = _read_json(dest / REPOS_FILE, {}).get("repo", [])
    cfg.safe_write_json(raw / "me.json", me)
    stats["login"] = me["login"]

    collab_dir = raw / "collaborators"
    collaborators: dict[str, list] = {}
    for f in sorted(collab_dir.glob("*.json")) if collab_dir.exists() else []:
        collaborators[f.stem] = _read_json(f, [])
    if "people" in steps:
        fetched_at = state.get("collab_fetched", {})
        fresh_after = iso(started - timedelta(days=COLLAB_REFRESH_DAYS))
        ok = denied = unchanged = 0
        for r in repos:
            if not r.get("can_push"):
                continue
            k = _key(r["owner"], r["name"])
            if not full and fetched_at.get(k, "") >= fresh_after and k in collaborators:
                unchanged += 1
                continue
            try:
                collaborators[k] = fetch_collaborators(client, r["owner"], r["name"], affiliation)
            except GitHubError as e:
                denied += 1
                log.warning("  collaborators of %s/%s: HTTP %s", r["owner"], r["name"], e.status)
                continue
            cfg.safe_write_json(collab_dir / f"{k}.json", collaborators[k])
            fetched_at[k] = iso(started)
            ok += 1
        state["collab_fetched"] = fetched_at
        stats.update(
            collab_repos_read=ok, collab_repos_denied=denied, collab_repos_unchanged=unchanged
        )

    items_path = raw / "items.json"
    store: dict = _read_json(items_path, {})
    if "work" in steps:
        before = len(store)
        if full or not state.get("work_since"):
            since = None if full else iso(started - timedelta(days=since_days))[:10]
        else:
            since = iso(datetime.fromisoformat(state["work_since"]) - timedelta(days=1))
        stats["work_since"] = since or "(everything)"
        try:
            fetch_work(client, me["login"], store, since, stats)
            fetch_my_reviews(client, me["login"], store, max_reviews, stats)
        finally:
            # what was read is kept even if a later call failed; the watermark
            # moves only after a complete pass
            cfg.safe_write_json(items_path, store)
        # A search GitHub answered with incomplete_results, or one stuck on the
        # 1,000-results window, may have missed items: keep the old watermark so
        # the next run searches the same window again instead of skipping it.
        if stats.get("incomplete_results") or stats.get("search_truncated"):
            stats["watermark_kept"] = state.get("work_since") or "(none)"
            log.warning("search incomplete: the watermark stays where it was")
        else:
            state["work_since"] = iso(started)
        stats["items"], stats["items_new"] = len(store), len(store) - before

    if "people" in steps or "work" in steps:
        users_path = raw / "users.json"
        cache = _read_json(users_path, {})
        logins = people_logins(me["login"], collaborators, store)
        fetch_profiles(client, list(logins), cache, max_profiles, stats)
        cfg.safe_write_json(users_path, cache)
        stats["people"] = len(logins)

    state["last_run"] = iso(started)
    cfg.safe_write_json(dest / STATE_FILE, state)
    stats["api_calls"] = client.calls
    stats["rate_remaining"] = client.rate_remaining
    stats["classic_token_scopes"] = client.scopes
    cfg.safe_write_json(dest / SUMMARY_FILE, stats)
    return stats


# --------------------------------------------------------------------------- L1


def _status(item: dict) -> str:
    if item.get("merged_at"):
        return "merged"
    return "closed" if item.get("state") == "closed" else "open"


def build_frames(dest: Path):
    """(contacts, interactions) DataFrames in the generic intake contract."""
    import pandas as pd

    raw = dest / RAW_DIR
    me = (_read_json(raw / "me.json", {}) or {}).get("login", "")
    store: dict = _read_json(raw / "items.json", {})
    users: dict = _read_json(raw / "users.json", {})
    collaborators: dict[str, list] = {}
    cdir = raw / "collaborators"
    for f in sorted(cdir.glob("*.json")) if cdir.exists() else []:
        collaborators[f.stem] = _read_json(f, [])

    def person_id(login: str) -> str:
        """What goes in `participants`: public email, else profile name, else login."""
        u = users.get(login) or {}
        email = (u.get("email") or "").strip().lower()
        if email and not email.endswith("noreply.github.com"):
            return email
        return (u.get("name") or "").strip() or login

    def others(item: dict) -> list[str]:
        logins = [(item.get("user", ""), item.get("user_type", ""))]
        logins += [(a.get("login", ""), a.get("type", "")) for a in item.get("assignees", [])]
        seen: list[str] = []
        for login, typ in logins:
            if (
                login
                and login.lower() != me.lower()
                and not is_bot(login, typ)
                and login not in seen
            ):
                seen.append(login)
        return seen

    rows: list[dict] = []
    per_person: dict[str, list[str]] = {}
    for url, it in store.items():
        repo_ref = f"{it.get('repo', '')}#{it.get('number', '')}"
        due = iso((it.get("milestone") or {}).get("due_on"))
        people = others(it)
        parts = "|||".join(person_id(p) for p in people)
        assignees = {a.get("login", "").lower() for a in it.get("assignees", [])}
        mine_author = it.get("user", "").lower() == me.lower()
        mine_assignee = me.lower() in assignees
        status = _status(it)
        new_rows = []
        if mine_author or mine_assignee:
            new_rows.append(
                {
                    "ts": iso(it.get("created_at")),
                    "kind": it.get("kind_base", "issue"),
                    "title": f"{repo_ref} {it.get('title', '')}".strip(),
                    "text": it.get("body", ""),
                    "owner_role": "assignee" if mine_assignee else "author",
                    "url": url,
                    "status": status,
                }
            )
        roles = set(it.get("roles", []))
        if "requested" in roles:
            new_rows.append(
                {
                    "ts": iso(it.get("updated_at")),
                    "kind": "review",
                    "title": f"Review requested: {repo_ref} {it.get('title', '')}".strip(),
                    "text": "",
                    "owner_role": "assignee",
                    "url": url,
                    "status": "open" if status == "open" else status,
                }
            )
        elif "reviewed" in roles:
            revs = sorted(it.get("my_reviews", []), key=lambda r: r.get("submitted_at") or "")
            last = revs[-1] if revs else {}
            new_rows.append(
                {
                    "ts": iso(last.get("submitted_at") or it.get("updated_at")),
                    "kind": "review",
                    "title": f"Review: {repo_ref} {it.get('title', '')}".strip(),
                    "text": last.get("body", ""),
                    "owner_role": "author",
                    "url": last.get("html_url") or url,
                    "status": "done",
                }
            )
        for r in new_rows:
            r.update(source=SOURCE_ID, participants=parts, due=due)
            rows.append(r)
            for p in people:
                per_person.setdefault(p, []).append(r["ts"])

    contacts: list[dict] = []
    everyone = people_logins(me, collaborators, store) if me else {}
    for login in sorted(everyone):
        u = users.get(login) or {}
        email = (u.get("email") or "").strip().lower()
        if email.endswith("noreply.github.com"):
            email = ""
        stamps = sorted(t for t in per_person.get(login, []) if t)
        contacts.append(
            {
                "source": SOURCE_ID,
                "name": (u.get("name") or "").strip() or login,
                "email": email,
                "phone": "",
                "company": (u.get("company") or "").strip().lstrip("@").strip(),
                "title": "",
                "first_seen": stamps[0] if stamps else "",
                "last_seen": stamps[-1] if stamps else "",
                "interactions": len(per_person.get(login, [])),
                "url": u.get("html_url") or f"https://github.com/{login}",
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
    return {
        "contacts": len(cdf),
        "interactions": len(idf),
        **{f"kind_{k}": int(v) for k, v in by_kind.items()},
    }
