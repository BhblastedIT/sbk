"""GitHub plugin (tools/github/): mocked network only, no real account, no real call.

Checks: token lookup order, GET-only client, rate-limit waits, Link pagination,
the 1,000-result search window, the L0 files (repos.json compatible with
xs-l1-inventario.py), the incremental watermark, the L1 parquet contract
(tools/cross-source/plugin_intake.py), and that the three scripts give --help
and a one-line error without credentials.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest
from requests.structures import CaseInsensitiveDict

ROOT = Path(__file__).resolve().parents[1]
GH = ROOT / "tools" / "github"
for p in (GH, ROOT / "tools", ROOT / "tools" / "cross-source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import gh_api  # noqa: E402

ME = "demo-owner"


# --------------------------------------------------------------------------- fakes


class FakeResp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = json.dumps(data) if data is not None else ""
        self.content = self.text.encode()

    def json(self):
        return self._data


class FakeSession:
    """Routes GETs to a handler; records every call. Has no post/put/patch/delete."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["User-Agent"]
        assert headers["X-GitHub-Api-Version"] == gh_api.API_VERSION
        self.calls.append((url, dict(params or {})))
        return self.handler(url, dict(params or {}))


def user(login, typ="User"):
    return {"login": login, "type": typ, "html_url": f"https://github.com/{login}"}


def issue(
    n,
    repo,
    author,
    assignees=(),
    pr=False,
    milestone_due=None,
    state="open",
    updated="2026-11-01T10:00:00Z",
    merged=None,
):
    it = {
        "html_url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{n}",
        "id": n,
        "number": n,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "title": f"Item {n}",
        "body": f"Body {n}",
        "state": state,
        "created_at": "2026-10-01T09:00:00Z",
        "updated_at": updated,
        "closed_at": None,
        "user": user(author),
        "assignees": [user(a) for a in assignees],
        "milestone": {"title": "M1", "due_on": milestone_due} if milestone_due else None,
    }
    if pr:
        it["pull_request"] = {"merged_at": merged}
    return it


def world():
    """A small demo account: two repos, one collaborator list, a few issues/PRs."""
    repos = [
        {
            "name": "alpha",
            "full_name": f"{ME}/alpha",
            "owner": {"login": ME, "type": "User"},
            "description": "Demo alpha",
            "private": True,
            "archived": False,
            "fork": False,
            "pushed_at": "2026-11-20T08:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
            "language": "Python",
            "topics": ["demo"],
            "size": 120,
            "html_url": f"https://github.com/{ME}/alpha",
            "default_branch": "main",
            "permissions": {"admin": True, "push": True, "pull": True},
        },
        {
            "name": "beta",
            "full_name": "acme-demo/beta",
            "owner": {"login": "acme-demo", "type": "Organization"},
            "description": None,
            "private": False,
            "archived": True,
            "fork": False,
            "pushed_at": "2024-03-01T08:00:00Z",
            "created_at": "2023-01-01T00:00:00Z",
            "language": None,
            "topics": [],
            "size": 5,
            "html_url": "https://github.com/acme-demo/beta",
            "default_branch": "main",
            "permissions": {"admin": False, "push": False, "pull": True},
        },
    ]
    searches = {
        f"is:issue author:{ME}": [
            issue(
                1, f"{ME}/alpha", ME, assignees=["ada-demo"], milestone_due="2026-12-15T08:00:00Z"
            )
        ],
        f"is:issue assignee:{ME}": [issue(2, "acme-demo/beta", "bo-demo", assignees=[ME])],
        f"is:pr author:{ME}": [
            issue(3, f"{ME}/alpha", ME, pr=True, state="closed", merged="2026-11-02T00:00:00Z")
        ],
        f"is:pr assignee:{ME}": [],
        f"is:pr reviewed-by:{ME}": [issue(4, "acme-demo/beta", "ada-demo", pr=True)],
        gh_api.REQUESTED_QUERY.format(login=ME): [
            issue(5, "acme-demo/beta", "dependabot[bot]", pr=True)
        ],
    }
    profiles = {
        "ada-demo": {
            "login": "ada-demo",
            "name": "Ada Demo",
            "email": "ada@demo.example",
            "company": "@acme-demo",
            "type": "User",
            "html_url": "https://github.com/ada-demo",
        },
        "bo-demo": {
            "login": "bo-demo",
            "name": None,
            "email": None,
            "company": None,
            "type": "User",
            "html_url": "https://github.com/bo-demo",
        },
        "cy-demo": {
            "login": "cy-demo",
            "name": "Cy Demo",
            "email": "cy@users.noreply.github.com",
            "company": "",
            "type": "User",
            "html_url": "https://github.com/cy-demo",
        },
    }
    return repos, searches, profiles


def make_handler(repos, searches, profiles, seen_queries=None):
    def handler(url, params):
        path = urlparse(url).path
        if path == "/user":
            return FakeResp(
                200,
                {
                    "login": ME,
                    "name": "Demo Owner",
                    "type": "User",
                    "html_url": f"https://github.com/{ME}",
                },
                {"x-ratelimit-remaining": "4999"},
            )
        if path == "/user/repos":
            return FakeResp(200, repos)
        if path == "/search/issues":
            q = params["q"]
            if seen_queries is not None:
                seen_queries.append(q)
            base = q.split(" updated:")[0]
            items = searches.get(base, [])
            return FakeResp(
                200, {"total_count": len(items), "incomplete_results": False, "items": items}
            )
        if path.endswith("/collaborators"):
            if "alpha" in path:
                return FakeResp(
                    200, [user("ada-demo"), user("cy-demo"), user(ME), user("renovate[bot]", "Bot")]
                )
            return FakeResp(403, {"message": "Must have push access"})
        if path.endswith("/reviews"):
            return FakeResp(
                200,
                [
                    {
                        "user": user(ME),
                        "state": "APPROVED",
                        "submitted_at": "2026-11-03T12:00:00Z",
                        "body": "Looks fine",
                        "html_url": "https://github.com/acme-demo/beta/pull/4#pullrequestreview-1",
                    },
                    {
                        "user": user("ada-demo"),
                        "state": "COMMENTED",
                        "submitted_at": "2026-11-04T12:00:00Z",
                        "body": "x",
                        "html_url": "h",
                    },
                ],
            )
        if path.startswith("/users/"):
            login = path.rsplit("/", 1)[-1]
            return (
                FakeResp(200, profiles[login])
                if login in profiles
                else FakeResp(404, {"message": "Not Found"})
            )
        if path.endswith("/contents"):
            return FakeResp(
                200,
                [
                    {"name": "src", "type": "dir"},
                    {"name": "vendor-lib", "type": "submodule"},
                    {"name": "README.md", "type": "file"},
                ],
            )
        if path.endswith("/readme"):
            return FakeResp(200, {"content": base64.b64encode(b"# Demo readme").decode()})
        return FakeResp(404, {"message": "Not Found"})

    return handler


def client_for(handler, sleeps=None):
    sess = FakeSession(handler)
    c = gh_api.Client(
        "github_pat_DEMO",
        session=sess,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=lambda: 1_000_000.0,
    )
    return c, sess


# --------------------------------------------------------------------------- token


def test_token_keychain_first_then_env(monkeypatch):
    import secrets_adapter

    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    monkeypatch.setattr(
        secrets_adapter,
        "get_secret",
        lambda s, a: "from-keychain" if (s, a) == ("sbk-github", "token") else None,
    )
    assert gh_api.resolve_token() == ("from-keychain", "keychain sbk-github/token")
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    assert gh_api.resolve_token() == ("from-env", "env GITHUB_TOKEN")
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "pat2")
    assert gh_api.resolve_token()[0] == "pat2"
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    with pytest.raises(gh_api.NoToken):
        gh_api.resolve_token()


def test_token_kind():
    assert gh_api.token_kind("github_pat_x") == "fine-grained"
    assert gh_api.token_kind("ghp_x") == "classic"
    assert gh_api.token_kind("other") == "unknown"


# --------------------------------------------------------------------------- client


def test_client_is_get_only():
    public = {n for n in dir(gh_api.Client) if not n.startswith("_")}
    assert not public & {"post", "put", "patch", "delete", "request"}
    src = (GH / "gh_api.py").read_text() + "".join(p.read_text() for p in GH.glob("gh-*.py"))
    for verb in (".post(", ".put(", ".patch(", ".delete(", ".request("):
        assert verb not in src


def test_token_never_leaves_api_host():
    c, sess = client_for(lambda u, p: FakeResp(200, {}))
    with pytest.raises(gh_api.GitHubError):
        c.get("https://evil.example/steal")
    assert sess.calls == []


def test_primary_rate_limit_waits_for_reset():
    answers = [
        FakeResp(
            403,
            {"message": "API rate limit exceeded"},
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(1_000_000 + 30)},
        ),
        FakeResp(200, {"ok": 1}),
    ]
    sleeps: list[float] = []
    c, _ = client_for(lambda u, p: answers.pop(0), sleeps)
    data, _ = c.get("/user")
    assert data == {"ok": 1}
    assert sleeps == [31.0]


def test_retry_after_and_secondary_limit():
    answers = [
        FakeResp(429, {"message": "slow down"}, {"retry-after": "7"}),
        FakeResp(403, {"message": "You have exceeded a secondary rate limit"}),
        FakeResp(200, {"ok": 2}),
    ]
    sleeps: list[float] = []
    c, _ = client_for(lambda u, p: answers.pop(0), sleeps)
    assert c.get("/user")[0] == {"ok": 2}
    assert sleeps[0] == 7.0 and sleeps[1] >= 60.0


def test_bare_429_waits():
    """A 429 is a rate limit even with no header and no 'rate limit' in the message."""
    answers = [FakeResp(429, {"message": "Too Many Requests"}), FakeResp(200, {"ok": 3})]
    sleeps: list[float] = []
    c, _ = client_for(lambda u, p: answers.pop(0), sleeps)
    assert c.get("/user")[0] == {"ok": 3}
    assert sleeps and sleeps[0] >= 60.0


def test_plain_403_is_a_refusal_not_a_wait():
    sleeps: list[float] = []
    c, _ = client_for(
        lambda u, p: FakeResp(403, {"message": "Resource not accessible by personal access token"}),
        sleeps,
    )
    with pytest.raises(gh_api.GitHubError) as e:
        c.get("/repos/a/b/collaborators")
    assert e.value.status == 403 and sleeps == []


def test_pagination_follows_link_next():
    def handler(url, params):
        if "page=2" in url:
            return FakeResp(200, [{"n": 3}])
        return FakeResp(
            200,
            [{"n": 1}, {"n": 2}],
            {
                "link": '<https://api.github.com/user/repos?page=2>; rel="next", <https://api.github.com/user/repos?page=2>; rel="last"'
            },
        )

    c, sess = client_for(handler)
    assert [x["n"] for x in c.paginate("/user/repos")] == [1, 2, 3]
    assert len(sess.calls) == 2


def test_search_goes_past_1000_results():
    """2,050 items: first window returns 1,000, then it restarts from the last updated_at."""
    all_items = [
        {
            "html_url": f"https://github.com/o/r/issues/{i}",
            "updated_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
        }
        for i in range(2050)
    ]

    def handler(url, params):
        q, page = params["q"], params["page"]
        lower = q.split("updated:>=")[1] if "updated:>=" in q else ""
        pool = [it for it in all_items if gh_api.iso(it["updated_at"]) >= lower]
        chunk = pool[(page - 1) * 100 : page * 100]
        return FakeResp(
            200, {"total_count": len(pool), "incomplete_results": False, "items": chunk}
        )

    c, sess = client_for(handler)
    found = c.search_issues("is:issue author:x")
    assert len(found) == 2050
    assert all(p["sort"] == "updated" and p["order"] == "asc" for _, p in sess.calls)


# --------------------------------------------------------------------------- L0 + L1


@pytest.fixture
def downloaded(tmp_path):
    repos, searches, profiles = world()
    queries: list[str] = []
    c, sess = client_for(make_handler(repos, searches, profiles, queries))
    dest = tmp_path / "github"
    summary = gh_api.run_download(c, dest, trees=True, since_days=30)
    return dest, summary, sess, queries


def test_l0_files_and_summary(downloaded):
    dest, summary, sess, queries = downloaded
    for f in (
        "repos.json",
        "state.json",
        "download-summary.json",
        "raw/me.json",
        "raw/items.json",
        "raw/users.json",
    ):
        assert (dest / f).exists(), f
    assert (dest / "alberi" / f"{ME}__alpha.json").exists()
    tree = json.loads((dest / "alberi" / f"{ME}__alpha.json").read_text())
    assert tree["cartelle"] == ["src", "vendor-lib"] and tree["readme"] == "# Demo readme"
    assert tree["file_radice"] == ["README.md"]
    # collaborators only where you can push; the 403 elsewhere is never asked
    assert (dest / "raw" / "collaborators" / f"{ME}__alpha.json").exists()
    assert not any("beta/collaborators" in u for u, _ in sess.calls)
    assert summary["repos"] == 2 and summary["login"] == ME
    assert summary["items"] == 5
    assert summary["reviews_fetched"] == 1
    # first run: windowed by since_days; review requests read in full
    assert all("updated:>=" in q for q in queries if "review-requested" not in q)
    assert any(q == gh_api.REQUESTED_QUERY.format(login=ME) for q in queries)


def test_repos_json_matches_inventory_reader(downloaded, monkeypatch):
    dest, *_ = downloaded
    spec = importlib.util.spec_from_file_location(
        "xs_l1_inventario", ROOT / "tools" / "cross-source" / "xs-l1-inventario.py"
    )
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    monkeypatch.setattr(inv, "GITHUB", dest / "repos.json")
    rows = inv.costruisci_repo()
    alpha = next(r for r in rows if r["nome"] == "alpha")
    assert alpha["owner"] == ME and alpha["privata"] is True and alpha["linguaggio"] == "Python"
    assert (
        alpha["kb"] == 120
        and alpha["ultimo_push"] == "2026-11-20"
        and alpha["url"].endswith("/alpha")
    )
    beta = next(r for r in rows if r["nome"] == "beta")
    assert beta["archiviata"] is True and beta["descrizione"] == ""


def test_incremental_second_run_uses_watermark(downloaded):
    dest, _, _, _ = downloaded
    repos, searches, profiles = world()
    queries: list[str] = []
    c, sess = client_for(make_handler(repos, searches, profiles, queries))
    gh_api.run_download(c, dest, steps=("work",))
    state = json.loads((dest / "state.json").read_text())
    assert state["work_since"]
    windowed = [q for q in queries if "updated:>=" in q]
    assert windowed and all("T" in q.split("updated:>=")[1] for q in windowed)
    # profiles were cached: no second /users/ call
    assert not any("/users/" in u for u, _ in sess.calls)


def test_tree_watermark_survives_a_download_without_trees(downloaded):
    """gh-l0-download.py (no --trees) rewrites repos.json; the next inventory must still
    re-read the tree of a repository pushed in between."""
    dest, *_ = downloaded
    repos, searches, profiles = world()
    repos[0]["pushed_at"] = "2026-11-24T08:00:00Z"  # alpha pushed after the first run
    c, _ = client_for(make_handler(repos, searches, profiles))
    gh_api.run_download(c, dest, steps=("repos",), trees=False)  # repos.json now has the new date
    c2, sess2 = client_for(make_handler(repos, searches, profiles))
    stats: dict = {}
    gh_api.run_inventory(c2, dest, trees=True, skip_owners=None, full=False, stats=stats)
    assert any(u.endswith(f"/repos/{ME}/alpha/contents") for u, _ in sess2.calls)
    tree = json.loads((dest / "alberi" / f"{ME}__alpha.json").read_text())
    assert tree["pushedAt"] == "2026-11-24T08:00:00Z"
    # and an unchanged repository is still skipped
    c3, sess3 = client_for(make_handler(repos, searches, profiles))
    gh_api.run_inventory(c3, dest, trees=True, skip_owners=None, full=False, stats={})
    assert not any(u.endswith("/contents") for u, _ in sess3.calls)


def test_incomplete_search_keeps_the_watermark(downloaded):
    dest, *_ = downloaded
    before = json.loads((dest / "state.json").read_text())["work_since"]
    repos, searches, profiles = world()
    base = make_handler(repos, searches, profiles)

    def handler(url, params):
        resp = base(url, params)
        if urlparse(url).path == "/search/issues":
            resp._data["incomplete_results"] = True
        return resp

    c, _ = client_for(handler)
    summary = gh_api.run_download(c, dest, steps=("work",))
    assert json.loads((dest / "state.json").read_text())["work_since"] == before
    assert summary["watermark_kept"] == before and summary["incomplete_results"] >= 1


def test_l1_contract(downloaded):
    from plugin_intake import CONTACT_COLUMNS, INTERACTION_COLUMNS, load_interactions, load_people

    dest, *_ = downloaded
    gh_api.write_frames(dest)
    c = pd.read_parquet(dest / "processed" / "plugin-contacts.parquet")
    i = pd.read_parquet(dest / "processed" / "plugin-interactions.parquet")
    assert tuple(c.columns) == CONTACT_COLUMNS
    assert (
        tuple(i.columns[: len(INTERACTION_COLUMNS)]) == INTERACTION_COLUMNS
        and "status" in i.columns
    )

    # people: no owner, no bots; public email kept, noreply dropped, company without "@"
    assert set(c["url"].str.rsplit("/", n=1).str[-1]) == {"ada-demo", "bo-demo", "cy-demo"}
    ada = c[c["name"] == "Ada Demo"].iloc[0]
    assert ada["email"] == "ada@demo.example" and ada["company"] == "acme-demo"
    assert ada["interactions"] == 2 and ada["first_seen"] and ada["last_seen"]
    assert c[c["url"].str.endswith("/cy-demo")].iloc[0]["email"] == ""
    assert c[c["url"].str.endswith("/cy-demo")].iloc[0]["interactions"] == 0
    assert c[c["url"].str.endswith("/bo-demo")].iloc[0]["name"] == "bo-demo"

    rows = {(r.kind, r.url.rsplit("/", 1)[-1].split("#")[0]): r for r in i.itertuples()}
    assert rows[("issue", "1")].owner_role == "author"
    assert rows[("issue", "1")].due.startswith("2026-12-15")
    assert rows[("issue", "1")].participants == "ada@demo.example"
    assert (
        rows[("issue", "2")].owner_role == "assignee"
        and rows[("issue", "2")].participants == "bo-demo"
    )
    assert rows[("pr", "3")].status == "merged"
    assert rows[("review", "4")].owner_role == "author" and rows[("review", "4")].status == "done"
    assert (
        rows[("review", "4")].ts.startswith("2026-11-03")
        and rows[("review", "4")].text == "Looks fine"
    )
    assert (
        rows[("review", "5")].owner_role == "assignee" and rows[("review", "5")].participants == ""
    )
    assert set(i["kind"]) <= {"issue", "pr", "review"} and (i["source"] == "github").all()

    # the kernel reader accepts both files as they are
    li = load_interactions(dest.parent)
    assert li is not None and len(li) == len(i)
    assert load_people(dest.parent) is not None

    # what the kernel will treat as an open commitment: assigned or with a due date, not closed
    from plugin_intake import is_commitment

    open_items = {
        (r.kind, r.url.rsplit("/", 1)[-1].split("#")[0])
        for r in li.itertuples()
        if is_commitment(r)
    }
    assert open_items == {("issue", "1"), ("issue", "2"), ("review", "5")}


def test_review_request_role_is_replaced_each_run(downloaded):
    dest, *_ = downloaded
    repos, searches, profiles = world()
    searches[gh_api.REQUESTED_QUERY.format(login=ME)] = []  # satisfied, withdrawn or PR closed
    c, _ = client_for(make_handler(repos, searches, profiles))
    gh_api.run_download(c, dest, steps=("work",))
    store = json.loads((dest / "raw" / "items.json").read_text())
    assert not any("requested" in it["roles"] for it in store.values())


# --------------------------------------------------------------------------- scripts


def _run(script, *args, env_extra=None, data_root=None):
    """Run a script with no credential and no way out to the network.

    The token variables are set to empty rather than removed: the scripts load the
    repo's .env with python-dotenv, which never overrides a variable that already
    exists, so a developer's .env cannot slip a real token in. Container mode keeps
    the Keychain out, and the proxies point to a closed local port, so even a bug
    that reached the network would fail at once instead of calling GitHub.
    """
    env = dict(os.environ)
    # Only the owner fields, no github section: the kernel's "no owner" warning stays out
    # of the one-line error checks.
    cfg = data_root / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    env.update(
        {
            "GITHUB_TOKEN": "",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "",
            "SBK_CONTAINERIZED": "1",
            "SBK_CONFIG": str(cfg),
            "SBK_DATA_ROOT": str(data_root),
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
        },
        **(env_extra or {}),
    )
    return subprocess.run(
        [sys.executable, str(GH / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(data_root),
    )


@pytest.mark.parametrize("script", ["gh-l0-download.py", "gh-l0-inventory.py", "gh-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    p = _run(script, "--help", data_root=tmp_path)
    assert p.returncode == 0 and "usage" in p.stdout.lower() and "Traceback" not in p.stderr


@pytest.mark.parametrize("script", ["gh-l0-download.py", "gh-l0-inventory.py", "gh-l1-enrich.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    p = _run(script, data_root=tmp_path)
    assert p.returncode == 1
    lines = [ln for ln in p.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("github:") and "Traceback" not in p.stderr
    assert not (tmp_path / "github" / "repos.json").exists()
