"""Linear plugin (tools/linear/): mocked network only, no real account, no real call.

Checks: key lookup order, the raw-key Authorization header, query-only client,
rate-limit waits (429 + Retry-After, RATELIMITED code + reset header, remaining 0),
errors inside a 200 answer, a refused key, cursor pagination, the L0 files and
the incremental watermark (overlap, re-check of open issues that left your
filter, wider selection, watermark kept on failure), the L1 parquet contract
(tools/cross-source/plugin_intake.py) and what the kernel will treat as a
commitment, and that both scripts give --help and a one-line error without
credentials.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
LN = ROOT / "tools" / "linear"
for p in (LN, ROOT / "tools", ROOT / "tools" / "cross-source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ln_api  # noqa: E402

KEY = "lin_api_DEMO"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any test that forgets a fake transport fails instead of calling Linear."""

    def refuse(*a, **k):
        raise AssertionError("real network call attempted in a test")

    monkeypatch.setattr(ln_api, "_urllib_transport", refuse)


# --------------------------------------------------------------------------- fakes


def user(uid, name, email="", app=False, me=False, title=""):
    return {
        "id": uid,
        "name": name,
        "displayName": name.split()[0].lower(),
        "email": email,
        "title": title,
        "url": f"https://linear.app/demo/profiles/{uid}",
        "app": app,
        "guest": False,
        "isMe": me,
        "active": True,
    }


ME = user("u-me", "Alex Demo", "alex@demo.example", me=True)
ADA = user("u-ada", "Ada Demo", "ada@acme.example", title="Engineer")
BO = user("u-bo", "Bo Demo", "bo@acme.example")
BOT = user("u-bot", "Demo Bot", "", app=True)


def issue(
    n,
    *,
    assignee=None,
    creator=None,
    subs=(),
    state=("In Progress", "started"),
    due=None,
    updated="2026-11-20T10:00:00.000Z",
    archived=None,
    project="Launch",
):
    return {
        "id": f"i-{n}",
        "identifier": f"DEM-{n}",
        "title": f"Item {n}",
        "description": f"Body {n}",
        "url": f"https://linear.app/demo/issue/DEM-{n}/item-{n}",
        "priority": 2,
        "priorityLabel": "High",
        "dueDate": due,
        "createdAt": f"2026-10-{n:02d}T09:00:00.000Z",
        "updatedAt": updated,
        "startedAt": None,
        "completedAt": "2026-11-10T00:00:00.000Z" if state[1] == "completed" else None,
        "canceledAt": "2026-11-11T00:00:00.000Z" if state[1] == "canceled" else None,
        "archivedAt": archived,
        "state": {"name": state[0], "type": state[1]},
        "team": {"key": "DEM", "name": "Demo Team"},
        "project": {"name": project, "url": "https://linear.app/demo/project/launch"}
        if project
        else None,
        "assignee": assignee,
        "creator": creator,
        "labels": {"nodes": [{"name": "Bug"}]},
        "subscribers": {"nodes": list(subs)},
    }


def comment(cid, issue_n, *, by=None, ext=None, created="2026-11-15T12:00:00.000Z"):
    return {
        "id": cid,
        "body": f"Comment {cid}",
        "url": f"https://linear.app/demo/issue/DEM-{issue_n}#comment-{cid}",
        "createdAt": created,
        "updatedAt": created,
        "editedAt": None,
        "user": by,
        "externalUser": ext,
        "issue": {"id": f"i-{issue_n}", "identifier": f"DEM-{issue_n}", "title": f"Item {issue_n}"},
    }


def world():
    issues = [
        issue(1, assignee=ME, creator=ADA, subs=[ME, ADA, BOT], due="2026-12-15"),
        issue(2, assignee=None, creator=ME, state=("Backlog", "backlog"), due="2026-12-20"),
        issue(3, assignee=BO, creator=ME, due="2026-12-01"),
        issue(4, assignee=ADA, creator=BO, subs=[ME], state=("Done", "completed")),
        issue(5, assignee=ME, creator=ME, state=("Canceled", "canceled")),
        issue(6, assignee=ME, creator=BO, state=("Triage", "triage"), archived="2026-11-12T00:00Z"),
    ]
    comments = [
        comment("c1", 1, by=ADA),
        comment("c2", 3, by=ME),
        comment(
            "c3",
            1,
            ext={"id": "x-1", "name": "Cy Demo", "displayName": "cy", "email": "cy@client.example"},
        ),
    ]
    return issues, comments


def _involves_me(it, include_subscribed):
    if (it.get("assignee") or {}).get("isMe") or (it.get("creator") or {}).get("isMe"):
        return True
    return include_subscribed and any(s.get("isMe") for s in it["subscribers"]["nodes"])


def _split(flt):
    """(base filter, since) from the plugin's {"and": [base, {"updatedAt": {"gte": ...}}]}."""
    if "and" in flt:
        return flt["and"][0], flt["and"][1]["updatedAt"]["gte"]
    return flt, None


def _subscribed_flag(base):
    return any("subscribers" in o for o in base.get("or", []))


class FakeLinear:
    """A tiny Linear: routes queries by operation name, pages of `page` nodes."""

    def __init__(self, issues, comments, page=2):
        self.issues, self.comments, self.page = issues, comments, page
        self.calls: list[dict] = []

    def __call__(self, url, body, headers, timeout):
        assert url == ln_api.API
        assert headers["Authorization"] == KEY  # personal key, no "Bearer"
        assert headers["User-Agent"]
        req = json.loads(body)
        self.calls.append(req)
        q, v = req["query"], req["variables"]
        if "SbkViewer" in q:
            data = {"viewer": {**ME, "organization": {"name": "Demo Workspace", "urlKey": "demo"}}}
            return (
                200,
                {"x-ratelimit-requests-remaining": "2400"},
                json.dumps({"data": data}).encode(),
            )
        base, since = _split(v["filter"])
        since_dt = ln_api.iso(since) if since else ""
        if "SbkIssues" in q:
            if "id" in base:
                pool = [i for i in self.issues if i["id"] in base["id"]["in"]]
            else:
                pool = [i for i in self.issues if _involves_me(i, _subscribed_flag(base))]
            pool = [i for i in pool if not since_dt or ln_api.iso(i["updatedAt"]) >= since_dt]
            return self._page("issues", pool, v.get("after"))
        if "SbkComments" in q:
            if "id" in base["issue"]:
                mine = set(base["issue"]["id"]["in"])
            else:
                sub = _subscribed_flag(base["issue"])
                mine = {i["id"] for i in self.issues if _involves_me(i, sub)}
            pool = [c for c in self.comments if c["issue"]["id"] in mine]
            pool = [c for c in pool if not since_dt or ln_api.iso(c["updatedAt"]) >= since_dt]
            return self._page("comments", pool, v.get("after"))
        return 400, {}, json.dumps({"errors": [{"message": "unknown query"}]}).encode()

    def _page(self, field, pool, after):
        start = int(after or 0)
        chunk = pool[start : start + self.page]
        more = start + self.page < len(pool)
        data = {
            field: {
                "nodes": chunk,
                "pageInfo": {
                    "hasNextPage": more,
                    "endCursor": str(start + self.page) if more else None,
                },
            }
        }
        return 200, {"x-complexity": "120"}, json.dumps({"data": data}).encode()


def client_for(transport, sleeps=None, clock=lambda: 1_000_000.0):
    return ln_api.Client(
        KEY,
        transport=transport,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=clock,
    )


def answers(*items):
    """A transport that returns the given (status, headers, payload) in order."""
    seq = list(items)

    def t(url, body, headers, timeout):
        status, h, payload = seq.pop(0)
        return status, h, json.dumps(payload).encode()

    return t


# --------------------------------------------------------------------------- key


def test_key_keychain_first_then_env(monkeypatch):
    import secrets_adapter

    monkeypatch.setenv("LINEAR_API_KEY", "from-env")
    monkeypatch.setattr(
        secrets_adapter,
        "get_secret",
        lambda s, a: "from-keychain" if (s, a) == ("sbk-linear", "api-key") else None,
    )
    assert ln_api.resolve_key() == ("from-keychain", "keychain sbk-linear/api-key")
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    assert ln_api.resolve_key() == ("from-env", "env LINEAR_API_KEY")
    monkeypatch.delenv("LINEAR_API_KEY")
    with pytest.raises(ln_api.NoKey):
        ln_api.resolve_key()


# --------------------------------------------------------------------------- client


def test_queries_are_read_only_and_mutations_never_leave():
    for q in ln_api.ALL_QUERIES:
        assert ln_api.is_read_only(q), q[:40]
    sent: list = []
    c = client_for(lambda *a: sent.append(a) or (200, {}, b"{}"))
    for doc in (
        'mutation { issueUpdate(id: "DEM-1", input: {title: "x"}) { success } }',
        'query Q { viewer { id } } mutation M { issueArchive(id: "x") { success } }',
        "subscription { issues { id } }",
    ):
        with pytest.raises(ln_api.LinearError):
            c.query(doc)
    assert sent == []
    # no write call anywhere in the plugin's scripts
    src = "".join(p.read_text() for p in LN.glob("ln-*.py"))
    assert "mutation" not in src.lower()


def test_rate_limit_429_waits_retry_after():
    sleeps: list[float] = []
    t = answers(
        (
            429,
            {"retry-after": "7"},
            {"errors": [{"message": "x", "extensions": {"code": "RATELIMITED"}}]},
        ),
        (200, {}, {"data": {"viewer": {"id": "u-me"}}}),
    )
    c = client_for(t, sleeps)
    assert c.query(ln_api.VIEWER_QUERY)["viewer"]["id"] == "u-me"
    assert sleeps == [7.0]


def test_ratelimited_code_without_429_uses_reset_header_in_ms():
    sleeps: list[float] = []
    reset_ms = str(int((1_000_000 + 30) * 1000))
    t = answers(
        (
            400,
            {"x-ratelimit-requests-reset": reset_ms},
            {"errors": [{"message": "Rate limit exceeded", "extensions": {"code": "RATELIMITED"}}]},
        ),
        (200, {}, {"data": {"ok": 1}}),
    )
    c = client_for(t, sleeps)
    assert c.query("query { ok }") == {"ok": 1}
    assert sleeps == [31.0]


def test_remaining_zero_pauses_before_next_call():
    sleeps: list[float] = []
    reset_ms = str(int((1_000_000 + 100) * 1000))
    t = answers(
        (
            200,
            {"x-ratelimit-requests-remaining": "0", "x-ratelimit-requests-reset": reset_ms},
            {"data": {"a": 1}},
        ),
        (200, {}, {"data": {"a": 2}}),
    )
    c = client_for(t, sleeps)
    c.query("query { a }")
    assert sleeps == []
    assert c.query("query { a }") == {"a": 2}
    assert sleeps == [101.0]


def test_errors_inside_a_200_answer_raise():
    t = answers((200, {}, {"data": {"viewer": None}, "errors": [{"message": "Field broke"}]}))
    with pytest.raises(ln_api.LinearError) as e:
        client_for(t).query("query { viewer { id } }")
    assert "Field broke" in str(e.value)


@pytest.mark.parametrize(
    "status,payload",
    [
        (401, {"errors": [{"message": "Authentication required"}]}),
        (400, {"errors": [{"message": "bad key", "extensions": {"code": "AUTHENTICATION_ERROR"}}]}),
    ],
)
def test_refused_key(status, payload):
    sleeps: list[float] = []
    with pytest.raises(ln_api.KeyRefused):
        client_for(answers((status, {}, payload)), sleeps).query("query { viewer { id } }")
    assert sleeps == []


def test_server_error_backs_off_then_succeeds():
    sleeps: list[float] = []
    t = answers((502, {}, {}), (200, {}, {"data": {"ok": 1}}))
    assert client_for(t, sleeps).query("query { ok }") == {"ok": 1}
    assert sleeps == [2]


def test_pagination_follows_end_cursor():
    issues, comments = world()
    fake = FakeLinear(issues, comments, page=2)
    c = client_for(fake)
    got = ln_api.fetch_issues(c, None, True)
    assert sorted(i["identifier"] for i in got) == [f"DEM-{n}" for n in range(1, 7)]
    assert len(fake.calls) == 3  # 6 issues, 2 per page
    assert [r["variables"]["after"] for r in fake.calls] == [None, "2", "4"]


def test_filter_shape_mine_and_subscribed():
    f = ln_api.mine_filter(True)
    assert {"assignee": {"isMe": {"eq": True}}} in f["or"]
    assert {"creator": {"isMe": {"eq": True}}} in f["or"]
    assert {"subscribers": {"some": {"isMe": {"eq": True}}}} in f["or"]
    assert len(ln_api.mine_filter(False)["or"]) == 2


# --------------------------------------------------------------------------- L0 + L1


@pytest.fixture
def downloaded(tmp_path):
    issues, comments = world()
    fake = FakeLinear(issues, comments)
    dest = tmp_path / "linear"
    summary = ln_api.run_download(client_for(fake), dest, history_days=30)
    return dest, summary, fake


def test_l0_files_and_summary(downloaded):
    dest, summary, fake = downloaded
    for f in (
        "state.json",
        "download-summary.json",
        "raw/me.json",
        "raw/issues.json",
        "raw/comments.json",
    ):
        assert (dest / f).exists(), f
    assert summary["workspace"] == "Demo Workspace"
    assert summary["issues"] == 6 and summary["comments"] == 3
    assert summary["max_query_complexity"] == 120
    # first run: windowed by history_days
    first = next(r for r in fake.calls if "SbkIssues" in r["query"])
    since = first["variables"]["filter"]["and"][1]["updatedAt"]["gte"]
    assert datetime.fromisoformat(since) > datetime.now(
        datetime.fromisoformat(since).tzinfo
    ) - timedelta(days=31)
    stored = json.loads((dest / "raw" / "issues.json").read_text())
    assert stored["i-1"]["subscribers"][2]["app"] is True
    state = json.loads((dest / "state.json").read_text())
    assert state["since"] and state["include_subscribed"] is True


def test_incremental_overlap_and_recheck_of_issues_that_left_the_filter(downloaded):
    dest, _, _ = downloaded
    prev = json.loads((dest / "state.json").read_text())["since"]
    issues, comments = world()
    # DEM-1 was handed to Ada and I unsubscribed: the main filter no longer returns it
    issues[0] = issue(
        1, assignee=ADA, creator=ADA, due="2026-12-15", updated="2099-01-01T00:00:00Z"
    )
    fake = FakeLinear(issues, comments)
    summary = ln_api.run_download(client_for(fake), dest, overlap_hours=24)
    first = next(r for r in fake.calls if "SbkIssues" in r["query"])
    since = first["variables"]["filter"]["and"][1]["updatedAt"]["gte"]
    assert datetime.fromisoformat(since) == datetime.fromisoformat(prev) - timedelta(hours=24)
    refresh = [
        r
        for r in fake.calls
        if "SbkIssues" in r["query"] and "id" in r["variables"]["filter"]["and"][0]
    ]
    assert refresh and "i-1" in refresh[0]["variables"]["filter"]["and"][0]["id"]["in"]
    assert summary["open_issues_changed"] == 1
    stored = json.loads((dest / "raw" / "issues.json").read_text())
    assert stored["i-1"]["assignee"]["id"] == "u-ada"
    ln_api.write_frames(dest)
    i = pd.read_parquet(dest / "processed" / "plugin-interactions.parquet")
    row = i[i["title"].str.startswith("DEM-1 ")].iloc[0]
    assert row.owner_role == "other" and row.due == ""


def test_wider_selection_reads_the_full_window_again(downloaded):
    dest, _, _ = downloaded
    issues, comments = world()
    ln_api.run_download(client_for(FakeLinear(issues, comments)), dest, include_subscribed=False)
    fake = FakeLinear(issues, comments)
    ln_api.run_download(client_for(fake), dest, include_subscribed=True, history_days=0)
    first = next(r for r in fake.calls if "SbkIssues" in r["query"])
    assert "and" not in first["variables"]["filter"]  # no since: everything


def test_failure_keeps_the_watermark_and_what_was_read(downloaded):
    dest, _, _ = downloaded
    before = json.loads((dest / "state.json").read_text())["since"]
    issues, comments = world()
    issues.append(issue(7, assignee=ME, creator=ME, updated="2099-01-01T00:00:00Z"))
    fake = FakeLinear(issues, comments)

    def broken(url, body, headers, timeout):
        if "SbkComments" in json.loads(body)["query"]:
            return 400, {}, json.dumps({"errors": [{"message": "Query too complex"}]}).encode()
        return fake(url, body, headers, timeout)

    with pytest.raises(ln_api.LinearError):
        ln_api.run_download(client_for(broken), dest)
    assert json.loads((dest / "state.json").read_text())["since"] == before
    assert "i-7" in json.loads((dest / "raw" / "issues.json").read_text())


def test_comments_turned_on_later_read_the_full_window_again(downloaded):
    dest, _, _ = downloaded
    issues, comments = world()
    ln_api.run_download(client_for(FakeLinear(issues, comments)), dest, comments=False)
    assert json.loads((dest / "state.json").read_text())["comments"] is False
    fake = FakeLinear(issues, comments)
    ln_api.run_download(client_for(fake), dest, comments=True, history_days=0)
    first = next(r for r in fake.calls if "SbkComments" in r["query"])
    assert "and" not in first["variables"]["filter"]  # no since: the whole window


def test_issue_that_became_yours_gets_its_older_comments(downloaded):
    dest, _, _ = downloaded
    issues, comments = world()
    # DEM-8 is Bo's, with an old comment; today it is handed to me
    issues.append(issue(8, assignee=ME, creator=BO, updated="2099-01-01T00:00:00Z"))
    comments.append(comment("c8", 8, by=BO, created="2020-01-01T00:00:00.000Z"))
    fake = FakeLinear(issues, comments)
    summary = ln_api.run_download(client_for(fake), dest)
    by_id = [
        r
        for r in fake.calls
        if "SbkComments" in r["query"] and "id" in (r["variables"]["filter"].get("issue") or {})
    ]
    assert by_id and by_id[0]["variables"]["filter"]["issue"]["id"]["in"] == ["i-8"]
    assert summary["comments_of_new_issues"] == 1
    assert "c8" in json.loads((dest / "raw" / "comments.json").read_text())


def test_redirects_are_not_followed():
    """urllib would resend the Authorization header to the redirect target."""
    from urllib.request import Request

    req = Request(ln_api.API, data=b"{}", headers={"Authorization": KEY}, method="POST")
    for code in (301, 302, 303, 307, 308):
        assert (
            ln_api._NoRedirect().redirect_request(req, None, code, "x", {}, "https://x.example/")
            is None
        )


def test_l1_contract(downloaded, monkeypatch):
    import plugin_intake
    from plugin_intake import (
        CONTACT_COLUMNS,
        INTERACTION_COLUMNS,
        is_commitment,
        load_interactions,
        load_people,
    )

    # independent of the enabled_sources in the sbk.config.json of the machine
    monkeypatch.setattr(plugin_intake, "_enabled", lambda plugin: True)
    dest, *_ = downloaded
    e = ln_api.write_frames(dest)
    assert e["kind_issue"] == 6 and e["kind_message"] == 3
    c = pd.read_parquet(dest / "processed" / "plugin-contacts.parquet")
    i = pd.read_parquet(dest / "processed" / "plugin-interactions.parquet")
    assert tuple(c.columns) == CONTACT_COLUMNS
    assert (
        tuple(i.columns[: len(INTERACTION_COLUMNS)]) == INTERACTION_COLUMNS
        and "status" in i.columns
    )

    # people: no owner, no app users; external commenter kept
    assert set(c["name"]) == {"Ada Demo", "Bo Demo", "Cy Demo"}
    ada = c[c["name"] == "Ada Demo"].iloc[0]
    assert ada["email"] == "ada@acme.example" and ada["title"] == "Engineer"
    assert ada["interactions"] == 3 and ada["first_seen"] <= ada["last_seen"]
    assert ada["url"].endswith("/u-ada")
    assert c[c["name"] == "Cy Demo"].iloc[0]["email"] == "cy@client.example"

    rows = {
        r.title.split(" ")[0] if r.kind == "issue" else r.url.rsplit("-", 1)[-1]: r
        for r in i.itertuples()
    }
    assert rows["DEM-1"].owner_role == "assignee" and rows["DEM-1"].due == "2026-12-15"
    assert rows["DEM-1"].participants == "Ada Demo <ada@acme.example>"
    assert "Project: Launch" in rows["DEM-1"].text and "Body 1" in rows["DEM-1"].text
    assert rows["DEM-2"].owner_role == "author" and rows["DEM-2"].due == "2026-12-20"
    assert rows["DEM-3"].owner_role == "author" and rows["DEM-3"].due == ""  # Bo's
    assert "Due: 2026-12-01" in rows["DEM-3"].text
    assert rows["DEM-4"].owner_role == "other" and rows["DEM-4"].status == "done"
    assert rows["DEM-5"].status == "cancelled" and rows["DEM-6"].status == "closed"
    assert (
        rows["c2"].owner_role == "author" and rows["c2"].participants == "Bo Demo <bo@acme.example>"
    )
    assert (
        rows["c1"].owner_role == "other"
        and rows["c1"].kind == "message"
        and rows["c1"].status == "done"
    )
    assert rows["c3"].participants == "Cy Demo <cy@client.example>"
    assert (i["source"] == "linear").all()

    li = load_interactions(dest.parent)
    assert li is not None and len(li) == len(i)
    assert load_people(dest.parent) is not None
    commitments = {r.title.split(" ")[0] for r in li.itertuples() if is_commitment(r)}
    assert commitments == {"DEM-1", "DEM-2"}


# --------------------------------------------------------------------------- scripts


def _run(script, *args, data_root):
    """Run a script with no credential and no way out to the network (see test_plugin_github)."""
    env = dict(os.environ)
    cfg = data_root / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    env.update(
        {
            "LINEAR_API_KEY": "",
            "SBK_CONTAINERIZED": "1",
            "SBK_CONFIG": str(cfg),
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
        [sys.executable, str(LN / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(data_root),
    )


@pytest.mark.parametrize("script", ["ln-l0-download.py", "ln-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    p = _run(script, "--help", data_root=tmp_path)
    assert p.returncode == 0 and "usage" in p.stdout.lower() and "Traceback" not in p.stderr


def test_bad_config_number_is_one_clear_line(tmp_path, monkeypatch, capsys):
    import importlib.util

    import sbk_config

    spec = importlib.util.spec_from_file_location("ln_l0", LN / "ln-l0-download.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(ln_api, "resolve_key", lambda: (KEY, "env LINEAR_API_KEY"))
    monkeypatch.setattr(
        sbk_config, "user_cfg", lambda p, d=None: "ten" if p == "linear.history_days" else d
    )
    monkeypatch.setattr(ln_api, "LN_DIR", tmp_path / "linear")
    assert mod.main(["--quiet"]) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("linear:") and "whole numbers" in err[0]
    assert not (tmp_path / "linear").exists()


@pytest.mark.parametrize("script", ["ln-l0-download.py", "ln-l1-enrich.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    p = _run(script, data_root=tmp_path)
    assert p.returncode == 1
    lines = [ln for ln in p.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("linear:") and "Traceback" not in p.stderr
    assert not (tmp_path / "linear" / "state.json").exists()
