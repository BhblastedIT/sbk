"""Atlassian plugin (tools/atlassian/): mocked network only, no real account, no real call.

Checks: settings and token lookup order, GET-only client that refuses other hosts,
basic auth header, Retry-After and backoff, enhanced JQL paging (nextPageToken),
Confluence cursor paging, the scoped-token route through api.atlassian.com with the
cloud id, the incremental watermarks, the L1 parquet contract
(tools/cross-source/plugin_intake.py), and that the two scripts give --help and a
one-line error without credentials.
"""

from __future__ import annotations

import base64
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
AS = ROOT / "tools" / "atlassian"
for p in (AS, ROOT / "tools", ROOT / "tools" / "cross-source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import as_api  # noqa: E402

SITE = "https://demo.atlassian.net"
EMAIL = "alex@personal.example"
ME = "acc-me"
CLOUD = "11111111-2222-3333-4444-555555555555"


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
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        return self.handler(url, dict(params or {}), dict(headers or {}))


def user(aid, name, email="", typ="atlassian"):
    return {"accountId": aid, "displayName": name, "emailAddress": email, "accountType": typ}


ME_USER = user(ME, "Alex Demo", EMAIL)
ADA = user("acc-ada", "Ada Demo", "ada@demo.example")
BO = user("acc-bo", "Bo Demo", "")  # email hidden by profile visibility
BOT = user("acc-bot", "Automation for Jira", "", "app")
CY = user("acc-cy", "Cy Demo", "cy@demo.example")


def issue(
    i,
    key,
    reporter,
    assignee=None,
    due=None,
    cat="new",
    resolved=None,
    watch=1,
    watching=False,
    updated="2026-11-10T10:00:00.000+0000",
):
    return {
        "id": str(i),
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": f"Body of {key}"}]}
                ],
            },
            "status": {
                "name": "Done" if cat == "done" else "In Progress",
                "statusCategory": {"key": cat},
            },
            "resolutiondate": resolved,
            "duedate": due,
            "created": "2026-10-01T09:00:00.000+0000",
            "updated": updated,
            "project": {"key": key.split("-")[0], "name": "Demo project"},
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "labels": [],
            "reporter": reporter,
            "creator": reporter,
            "assignee": assignee,
            "watches": {"isWatching": watching, "watchCount": watch},
        },
    }


def world():
    issues = [
        issue(1, "DEMO-1", ME_USER, ADA, due="2026-12-15"),  # you reported, Ada assigned, due
        issue(2, "DEMO-2", BO, ME_USER, due="2026-12-01", watch=3),  # assigned to you, watchers
        issue(3, "DEMO-3", ADA, ME_USER, cat="done", resolved="2026-11-02T00:00:00.000+0000"),
        issue(4, "OPS-4", CY, BO, due="2026-12-20", watching=True),  # only watched
    ]
    watchers = {"DEMO-2": [ME_USER, CY, BOT]}
    pages = [
        {
            "content": {
                "id": "100",
                "type": "page",
                "title": "Release notes",
                "space": {"key": "ENG", "name": "Engineering"},
                "version": {"number": 4, "when": "2026-11-05T08:00:00.000Z", "by": ADA},
                "history": {
                    "createdBy": ME_USER,
                    "createdDate": "2026-09-01T08:00:00.000Z",
                    "lastUpdated": {"when": "2026-11-05T08:00:00.000Z", "by": ADA, "number": 4},
                    "contributors": {"publishers": {"users": [ME_USER, ADA, CY]}},
                },
                "_links": {"webui": "/spaces/ENG/pages/100/Release+notes"},
            },
            "title": "Release notes",
            "url": "/spaces/ENG/pages/100/Release+notes",
            "lastModified": "2026-11-05T08:00:00.000Z",
        },
        {
            "content": {
                "id": "200",
                "type": "page",
                "title": "Team page",
                "space": {"key": "HR", "name": "People"},
                "version": {"number": 2, "when": "2026-11-06T08:00:00.000Z", "by": ME_USER},
                "history": {"createdBy": BO, "createdDate": "2026-08-01T08:00:00.000Z"},
                "_links": {"webui": "/spaces/HR/pages/200/Team+page"},
            },
        },
    ]
    return issues, watchers, pages


def make_handler(issues, watchers, pages, seen=None, scoped=False):
    """Jira + Confluence of demo.atlassian.net. With scoped=True the site refuses the token
    and only api.atlassian.com/ex/{product}/{cloud} answers."""

    def handler(url, params, headers):
        u = urlparse(url)
        path = u.path
        if seen is not None:
            seen.append((url, params))
        if path == "/_edge/tenant_info":
            assert "Authorization" not in headers  # the cloud id lookup carries no credential
            return FakeResp(200, {"cloudId": CLOUD})
        assert headers["Authorization"].startswith("Basic ")
        if u.netloc == "api.atlassian.com":
            if not scoped:
                return FakeResp(401, {"message": "Unauthorized"})
            prefix_j, prefix_c = f"/ex/jira/{CLOUD}", f"/ex/confluence/{CLOUD}"
            if path.startswith(prefix_j):
                path = path[len(prefix_j) :]
            elif path.startswith(prefix_c):
                path = "/wiki" + path[len(prefix_c) :]
            else:
                return FakeResp(404, {})
        elif scoped:
            return FakeResp(401, {"message": "Client must be authenticated"})
        if path == "/rest/api/3/myself":
            return FakeResp(200, ME_USER)
        if path == "/wiki/rest/api/user/current":
            return FakeResp(200, {"accountId": ME, "displayName": "Alex Demo", "email": EMAIL})
        if path == "/rest/api/3/search/jql":
            assert params.get("fields") == as_api.JIRA_FIELDS or "nextPageToken" in params
            start = int(params.get("nextPageToken") or 0)
            chunk = issues[start : start + 2]
            body = {"issues": chunk}
            if start + 2 < len(issues):
                body["nextPageToken"] = str(start + 2)
            else:
                body["isLast"] = True
            return FakeResp(200, body)
        if path.startswith("/rest/api/3/issue/") and path.endswith("/watchers"):
            key = path.split("/")[-2]
            return FakeResp(
                200, {"watchers": watchers.get(key, []), "watchCount": len(watchers.get(key, []))}
            )
        if path == "/wiki/rest/api/search":
            cursor = params.get("cursor")
            if cursor is None and "cursor=" in url:
                cursor = url.split("cursor=")[1]
            if not cursor:
                return FakeResp(
                    200,
                    {
                        "results": pages[:1],
                        "_links": {
                            "base": f"{SITE}/wiki",
                            "next": "/rest/api/search?cql=x&limit=50&cursor=c2",
                        },
                    },
                )
            return FakeResp(200, {"results": pages[1:], "_links": {"base": f"{SITE}/wiki"}})
        return FakeResp(404, {"message": "Not Found"})

    return handler


def settings(kind="auto", products=as_api.PRODUCTS, cloud_id=""):
    return as_api.Settings(
        site=SITE,
        email=EMAIL,
        token_kind=kind,
        cloud_id=cloud_id,
        products=tuple(products),
        tokens=dict.fromkeys(products, ("ATATT-demo-token", "env ATLASSIAN_API_TOKEN")),
    )


# --------------------------------------------------------------------------- settings


def test_normalize_site():
    assert as_api.normalize_site("demo.atlassian.net") == SITE
    assert as_api.normalize_site("https://Demo.atlassian.net/wiki/home") == SITE
    with pytest.raises(as_api.NotConfigured):
        as_api.normalize_site("http://demo.atlassian.net")


def test_token_order_product_then_shared_keychain_then_env(monkeypatch):
    import secrets_adapter

    store = {("sbk-atlassian", "jira-token"): "k-jira", ("sbk-atlassian", "api-token"): "k-shared"}
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: store.get((s, a)))
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "e-shared")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_API_TOKEN", "e-conf")
    assert as_api.resolve_token("jira") == ("k-jira", "keychain sbk-atlassian/jira-token")
    assert as_api.resolve_token("confluence") == ("e-conf", "env ATLASSIAN_CONFLUENCE_API_TOKEN")
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_API_TOKEN")
    assert as_api.resolve_token("confluence")[0] == "k-shared"
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    assert as_api.resolve_token("confluence") == ("e-shared", "env ATLASSIAN_API_TOKEN")
    monkeypatch.delenv("ATLASSIAN_API_TOKEN")
    assert as_api.resolve_token("jira") == ("", "")


def test_missing_settings_one_line(monkeypatch):
    import secrets_adapter

    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    for v in (
        "ATLASSIAN_SITE",
        "ATLASSIAN_EMAIL",
        "ATLASSIAN_API_TOKEN",
        "ATLASSIAN_JIRA_API_TOKEN",
        "ATLASSIAN_CONFLUENCE_API_TOKEN",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(as_api.cfg, "user_cfg", lambda path, default=None: default)
    with pytest.raises(as_api.NotConfigured) as e:
        as_api.load_settings()
    msg = str(e.value)
    assert "\n" not in msg and "site URL" in msg and "account email" in msg and "API token" in msg
    monkeypatch.setenv("ATLASSIAN_SITE", "demo.atlassian.net")
    monkeypatch.setenv("ATLASSIAN_EMAIL", EMAIL)
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    s = as_api.load_settings(("jira",))
    assert s.site == SITE and s.products == ("jira",) and s.token_kind == "auto"


# --------------------------------------------------------------------------- client


def test_client_is_get_only():
    public = {n for n in dir(as_api.Client) if not n.startswith("_")}
    assert not public & {"post", "put", "patch", "delete", "request"}
    src = (AS / "as_api.py").read_text() + "".join(p.read_text() for p in AS.glob("as-*.py"))
    for verb in (".post(", ".put(", ".patch(", ".delete(", ".request("):
        assert verb not in src


def test_basic_auth_and_host_guard():
    sess = FakeSession(lambda u, p, h: FakeResp(200, {"ok": 1}))
    c = as_api.Client(EMAIL, "tok", SITE, session=sess, sleep=lambda s: None)
    assert c.get(SITE + "/rest/api/3/myself")[0] == {"ok": 1}
    auth = sess.calls[0][2]["Authorization"]
    assert base64.b64decode(auth.split()[1]).decode() == f"{EMAIL}:tok"
    for bad in (
        "https://evil.example/x",
        "http://demo.atlassian.net/x",
        "https://other.atlassian.net/x",
    ):
        with pytest.raises(as_api.AtlassianError):
            c.get(bad)
    assert len(sess.calls) == 1
    c.get("https://api.atlassian.com/ex/jira/x/rest/api/3/myself")  # the gateway is allowed


def test_retry_after_then_backoff_then_refusal():
    answers = [
        FakeResp(429, {"message": "rate"}, {"Retry-After": "7"}),
        FakeResp(503, {"message": "unavailable"}),
        FakeResp(200, {"ok": 2}),
    ]
    sleeps: list[float] = []
    c = as_api.Client(
        EMAIL,
        "t",
        SITE,
        session=FakeSession(lambda u, p, h: answers.pop(0)),
        sleep=sleeps.append,
        jitter=lambda: 0.5,
    )
    assert c.get(SITE + "/x")[0] == {"ok": 2}
    assert sleeps == [7.0, 4.5]
    sleeps.clear()
    c2 = as_api.Client(
        EMAIL,
        "t",
        SITE,
        session=FakeSession(lambda u, p, h: FakeResp(403, {})),
        sleep=sleeps.append,
    )
    with pytest.raises(as_api.AtlassianError) as e:
        c2.get(SITE + "/x")
    assert e.value.status == 403 and sleeps == []


def test_jql_and_cql():
    q = as_api.build_jql(90, ("DEMO",))
    assert q.startswith(as_api.JQL_MINE) and 'project in ("DEMO")' in q
    assert 'updated >= "-90m"' in q and q.endswith("ORDER BY updated ASC")
    assert "updated" not in as_api.build_jql(None).split("ORDER BY")[0]
    c = as_api.build_cql("2026-11-01", ("ENG",))
    assert (
        c
        == 'type = page AND contributor = currentUser() AND space in ("ENG") AND lastmodified >= "2026-11-01"'
    )


def test_adf_and_iso():
    assert (
        as_api.adf_text(
            {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Hi "},
                            {"type": "mention", "attrs": {"text": "@Ada"}},
                        ],
                    }
                ],
            }
        )
        == "Hi @Ada"
    )
    assert as_api.iso("2026-11-01T10:00:00.000+0000") == "2026-11-01T10:00:00+00:00"
    assert as_api.iso("2026-11-01T10:00:00.000Z") == "2026-11-01T10:00:00+00:00"
    assert as_api.iso("2026-12-15") == "2026-12-15"  # a due date stays a date, never shifted
    assert as_api.iso("2026-11-01T10:00:00") == "2026-11-01T10:00:00+00:00"  # no zone = UTC


# --------------------------------------------------------------------------- L0 + L1


@pytest.fixture
def downloaded(tmp_path):
    issues, watchers, pages = world()
    seen: list = []
    sess = FakeSession(make_handler(issues, watchers, pages, seen))
    dest = tmp_path / "atlassian"
    summary = as_api.run_download(
        settings(), dest, session=sess, sleep=lambda s: None, since_days=30
    )
    return dest, summary, sess, seen


def test_l0_files_and_summary(downloaded):
    dest, summary, sess, seen = downloaded
    for f in (
        "state.json",
        "download-summary.json",
        "raw/me.json",
        "raw/issues.json",
        "raw/pages.json",
    ):
        assert (dest / f).exists(), f
    assert summary["jira_route"] == "site" and summary["confluence_route"] == "site"
    assert summary["jira_issues"] == 4 and summary["confluence_pages"] == 2
    assert summary["watchers_fetched"] == 1  # only DEMO-2 has more than one watcher
    jql = [p["jql"] for u, p in seen if u.endswith("/search/jql") and "jql" in p]
    assert jql and 'updated >= "-43200m"' in jql[0]
    assert len([u for u, _ in seen if u.endswith("/search/jql")]) == 2  # two pages of two
    assert any("cursor=c2" in u for u, _ in seen)  # Confluence followed _links.next
    me = json.loads((dest / "raw" / "me.json").read_text())
    assert me["accountId"] == ME and me["site"] == SITE
    assert all(urlparse(u).netloc in ("demo.atlassian.net",) for u, _, _ in sess.calls)


def test_incremental_second_run(downloaded):
    dest, *_ = downloaded
    issues, watchers, pages = world()
    seen: list = []
    sess = FakeSession(make_handler(issues, watchers, pages, seen))
    s = as_api.run_download(settings(), dest, session=sess, sleep=lambda s: None)
    jql = [p["jql"] for u, p in seen if u.endswith("/search/jql") and "jql" in p][0]
    minutes = int(jql.split('updated >= "-')[1].split("m")[0])
    assert as_api.OVERLAP_MIN <= minutes <= as_api.OVERLAP_MIN + 5
    cql = [p["cql"] for u, p in seen if u.endswith("/rest/api/search") and "cql" in p][0]
    assert 'lastmodified >= "' in cql
    assert s["watchers_fetched"] == 0  # DEMO-2 unchanged: watchers not asked again


def test_full_run_drops_what_no_longer_matches(downloaded):
    dest, *_ = downloaded
    issues, watchers, pages = world()
    sess = FakeSession(make_handler(issues[:2], watchers, pages))
    s = as_api.run_download(settings(), dest, session=sess, sleep=lambda s: None, full=True)
    assert s["jira_issues"] == 2 and s["jira_window_minutes"] == "(everything)"


def test_scoped_token_goes_through_the_gateway(tmp_path):
    issues, watchers, pages = world()
    seen: list = []
    sess = FakeSession(make_handler(issues, watchers, pages, seen, scoped=True))
    s = as_api.run_download(settings(), tmp_path / "atlassian", session=sess, sleep=lambda s: None)
    assert s["jira_route"] == "gateway" and s["confluence_route"] == "gateway"
    assert s["jira_issues"] == 4 and s["confluence_pages"] == 2
    assert any(u.endswith("/_edge/tenant_info") for u, _ in seen)
    assert any(
        u.startswith(f"https://api.atlassian.com/ex/jira/{CLOUD}/rest/api/3/search/jql")
        for u, _ in seen
    )
    assert any(
        u.startswith(f"https://api.atlassian.com/ex/confluence/{CLOUD}/rest/api/search")
        for u, _ in seen
    )
    # with token_kind "scoped" and a cloud id in config the site is never tried
    seen2: list = []
    sess2 = FakeSession(make_handler(issues, watchers, pages, seen2, scoped=True))
    as_api.run_download(
        settings("scoped", cloud_id=CLOUD), tmp_path / "b", session=sess2, sleep=lambda s: None
    )
    assert all(urlparse(u).netloc == "api.atlassian.com" for u, _ in seen2)


def test_one_product_refused_the_other_still_runs(tmp_path):
    issues, watchers, pages = world()
    base = make_handler(issues, watchers, pages)

    def handler(url, params, headers):
        if "/wiki/" in url:
            return FakeResp(404, {"message": "no Confluence on this site"})
        return base(url, params, headers)

    s = as_api.run_download(
        settings(), tmp_path / "a", session=FakeSession(handler), sleep=lambda s: None
    )
    assert s["products_skipped"] == {"confluence": "HTTP 404"} and s["jira_issues"] == 4
    with pytest.raises(as_api.AtlassianError):
        as_api.run_download(
            settings(),
            tmp_path / "b",
            session=FakeSession(handler),
            sleep=lambda s: None,
            strict=True,
        )
    refuse = FakeSession(
        lambda u, p, h: (
            FakeResp(401, {}) if "tenant_info" not in u else FakeResp(200, {"cloudId": CLOUD})
        )
    )
    with pytest.raises(as_api.AtlassianError) as e:
        as_api.run_download(settings(), tmp_path / "c", session=refuse, sleep=lambda s: None)
    assert e.value.status == 401


def test_l1_contract(downloaded):
    from plugin_intake import (
        CONTACT_COLUMNS,
        INTERACTION_COLUMNS,
        is_commitment,
        load_interactions,
        load_people,
    )

    dest, *_ = downloaded
    as_api.write_frames(dest)
    c = pd.read_parquet(dest / "processed" / "plugin-contacts.parquet")
    i = pd.read_parquet(dest / "processed" / "plugin-interactions.parquet")
    assert tuple(c.columns) == CONTACT_COLUMNS
    assert (
        tuple(i.columns[: len(INTERACTION_COLUMNS)]) == INTERACTION_COLUMNS
        and "status" in i.columns
    )

    # people: not you, not the app account; hidden email kept empty
    assert set(c["name"]) == {"Ada Demo", "Bo Demo", "Cy Demo"}
    ada = c[c["name"] == "Ada Demo"].iloc[0]
    assert ada["email"] == "ada@demo.example" and ada["interactions"] == 3
    assert c[c["name"] == "Bo Demo"].iloc[0]["email"] == ""
    assert (c["source"] == "atlassian").all()

    rows = {
        r.url.rsplit("/", 1)[-1]
        if r.kind == "issue"
        else r.url.split("/pages/")[1].split("/")[0]: r
        for r in i.itertuples()
    }
    assert rows["DEMO-1"].owner_role == "author" and rows["DEMO-1"].due.startswith("2026-12-15")
    assert rows["DEMO-1"].participants == "ada@demo.example" and rows["DEMO-1"].status == "open"
    assert rows["DEMO-1"].text.startswith(
        "Status: In Progress. Project: Demo project. Type: Task. Body of DEMO-1"
    )
    assert rows["DEMO-2"].owner_role == "assignee"
    assert set(rows["DEMO-2"].participants.split("|||")) == {"Bo Demo", "cy@demo.example"}
    assert rows["DEMO-3"].status == "done"
    assert rows["OPS-4"].owner_role == "other" and rows["OPS-4"].due == ""  # only watched
    assert rows["100"].kind == "record" and rows["100"].owner_role == "author"
    assert rows["100"].url == f"{SITE}/wiki/spaces/ENG/pages/100/Release+notes"
    assert set(rows["100"].participants.split("|||")) == {"ada@demo.example", "cy@demo.example"}
    assert rows["200"].owner_role == "other" and rows["200"].participants == "Bo Demo"
    assert set(i["kind"]) == {"issue", "record"} and (i["source"] == "atlassian").all()

    li = load_interactions(dest.parent)
    assert li is not None and len(li) == len(i)
    assert load_people(dest.parent) is not None
    open_items = {r.title.split()[0] for r in li.itertuples() if is_commitment(r)}
    assert open_items == {"DEMO-1", "DEMO-2"}


def test_confluence_next_link_keeps_the_expansions(downloaded):
    """Atlassian's example next link has cql, limit and cursor only: expand is sent again."""
    _, _, _, seen = downloaded
    second = [(u, p) for u, p in seen if "/rest/api/search" in u and "cursor=c2" in u]
    assert second, "the cursor link was not followed"
    url, params = second[0]
    assert params.get("expand") == as_api.CONFLUENCE_EXPAND and "cql" not in params


def test_damaged_state_falls_back_to_first_window(downloaded):
    dest, *_ = downloaded
    (dest / "state.json").write_text(
        json.dumps({"jira_since": "yesterday", "confluence_since": 7}), encoding="utf-8"
    )
    issues, watchers, pages = world()
    seen: list = []
    sess = FakeSession(make_handler(issues, watchers, pages, seen))
    s = as_api.run_download(settings(), dest, session=sess, sleep=lambda s: None, since_days=2)
    assert s["jira_window_minutes"] == 2 * 1440 and s["jira_issues"] == 4


def test_people_deleted_accounts_and_stable_participants(tmp_path):
    """'Former user' (a deleted account) and nameless users never become a person; a person
    whose email shows up on any record is written by email on every row."""
    dest = tmp_path / "atlassian"
    raw = dest / "raw"
    raw.mkdir(parents=True)
    gone1 = {"accountId": "acc-g1", "displayName": "Former user", "email": "", "accountType": ""}
    gone2 = {"accountId": "acc-g2", "displayName": "Former user", "email": "", "accountType": ""}
    blank = {"accountId": "acc-x", "displayName": "", "email": "", "accountType": "atlassian"}
    dee_no_mail = {"accountId": "acc-dee", "displayName": "Dee Demo", "email": ""}
    dee_mail = dict(dee_no_mail, email="dee@demo.example")
    me = as_api.slim_user(ME_USER)
    (raw / "me.json").write_text(json.dumps({"accountId": ME}), encoding="utf-8")
    base = {"status": "Open", "status_category": "new", "created": "2026-10-01T09:00:00+00:00"}
    issues = {
        "1": dict(base, key="DEMO-1", reporter=gone1, creator=gone1, assignee=me, url="u1"),
        "2": dict(base, key="DEMO-2", reporter=dee_no_mail, creator=blank, assignee=me, url="u2"),
        "3": dict(base, key="DEMO-3", reporter=gone2, creator=dee_mail, assignee=me, url="u3"),
    }
    (raw / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
    (raw / "pages.json").write_text("{}", encoding="utf-8")
    c, i = as_api.build_frames(dest)
    assert list(c["name"]) == ["Dee Demo"] and c.iloc[0]["email"] == "dee@demo.example"
    by_key = {r.title.split()[0]: r.participants for r in i.itertuples()}
    assert by_key == {"DEMO-1": "", "DEMO-2": "dee@demo.example", "DEMO-3": "dee@demo.example"}


def test_settings_repr_hides_tokens():
    assert "ATATT-demo-token" not in repr(settings())


# --------------------------------------------------------------------------- scripts


def _run(script, *args, data_root=None):
    """Run a script with no credential and no way out to the network (see test_plugin_github)."""
    env = dict(os.environ)
    conf = data_root / "owner-only.json"
    conf.write_text(json.dumps({"owner": "Alex Demo", "own_emails": [EMAIL]}), encoding="utf-8")
    env.update(
        {
            "ATLASSIAN_SITE": "",
            "ATLASSIAN_EMAIL": "",
            "ATLASSIAN_API_TOKEN": "",
            "ATLASSIAN_JIRA_API_TOKEN": "",
            "ATLASSIAN_CONFLUENCE_API_TOKEN": "",
            "ATLASSIAN_CLOUD_ID": "",
            "SBK_CONTAINERIZED": "1",
            "SBK_CONFIG": str(conf),
            "SBK_DATA_ROOT": str(data_root),
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "no_proxy": "",
        }
    )
    return subprocess.run(
        [sys.executable, str(AS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(data_root),
    )


@pytest.mark.parametrize("script", ["as-l0-download.py", "as-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    p = _run(script, "--help", data_root=tmp_path)
    assert p.returncode == 0 and "usage" in p.stdout.lower() and "Traceback" not in p.stderr


@pytest.mark.parametrize("script", ["as-l0-download.py", "as-l1-enrich.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    p = _run(script, data_root=tmp_path)
    assert p.returncode == 1
    lines = [ln for ln in p.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("atlassian:") and "Traceback" not in p.stderr
    assert not (tmp_path / "atlassian" / "raw").exists()
