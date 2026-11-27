"""Pipedrive plugin (tools/pipedrive/): mocked network only, no real account, no real call.

Checks: credential lookup order (API token, then your own OAuth app), the GET-only data
client and the single OAuth POST, the host check, pacing and 429 back-off, both
pagination styles, the L0 files and the update_time watermarks, deleted deals, the
request cap, the L1 parquet contract (tools/cross-source/plugin_intake.py) with the
"mine" and "all" scopes, and that the three scripts give --help and one clear line
without credentials.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest
from requests.structures import CaseInsensitiveDict

ROOT = Path(__file__).resolve().parents[1]
PD = ROOT / "tools" / "pipedrive"
for p in (PD, ROOT / "tools", ROOT / "tools" / "cross-source"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pd_api  # noqa: E402
import pd_oauth  # noqa: E402

ME_ID = 7
DOMAIN = "demo-co"
BASE = f"https://{DOMAIN}.pipedrive.com"
SERVER_DATE = "Wed, 25 Nov 2026 10:00:00 GMT"


# --------------------------------------------------------------------------- fakes


class FakeResp:
    def __init__(self, status=200, data=None, headers=None, text=None):
        self.status_code = status
        self._data = data
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = text if text is not None else (json.dumps(data) if data is not None else "")
        self.content = self.text.encode()

    def json(self):
        return self._data


class FakeSession:
    """Routes GETs to a handler and records them. POST exists only for the OAuth tests."""

    def __init__(self, handler, post_handler=None):
        self.handler = handler
        self.post_handler = post_handler
        self.calls: list[tuple[str, dict, dict]] = []
        self.posts: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        return self.handler(url, dict(params or {}))

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append((url, dict(data or {}), dict(headers or {})))
        return self.post_handler(url, dict(data or {}))


def ok(data, extra=None, headers=None):
    return FakeResp(200, {"success": True, "data": data, "additional_data": extra or {}}, headers)


def world():
    orgs = [
        {"id": 1, "name": "Acme Demo", "owner_id": ME_ID, "update_time": "2026-11-01T09:00:00Z"}
    ]
    persons = [
        {
            "id": 10,
            "name": "Ada Demo",
            "first_name": "Ada",
            "last_name": "Demo",
            "owner_id": ME_ID,
            "org_id": 1,
            "emails": [
                {"value": "ada.home@demo.example", "primary": False, "label": "home"},
                {"value": "Ada@Acme.example", "primary": True, "label": "work"},
            ],
            "phones": [{"value": "+1 555 0100", "primary": True, "label": "work"}],
            "job_title": "Buyer",
            "birthday": "1990-01-01",
            "postal_address": {"value": "1 Demo St"},
            "notes": "contact sync notes",
            "update_time": "2026-11-02T09:00:00Z",
        },
        {
            "id": 11,
            "name": "Bo Demo",
            "owner_id": 99,
            "org_id": None,
            "emails": [],
            "phones": [{"value": "+1 555 0111", "primary": True}],
            "update_time": "2026-11-03T09:00:00Z",
        },
        {
            "id": 12,
            "name": "Cy Demo",
            "owner_id": 99,
            "org_id": 1,
            "emails": [{"value": "cy@acme.example", "primary": True}],
            "phones": [],
            "update_time": "2026-11-04T09:00:00Z",
        },
        {
            "id": 13,
            "name": "Alex Demo",
            "owner_id": ME_ID,
            "emails": [{"value": "alex@demo.example", "primary": True}],
            "phones": [],
            "update_time": "2026-11-04T10:00:00Z",
        },
        {"id": 14, "name": "Gone Demo", "is_deleted": True, "update_time": "2026-11-04T11:00:00Z"},
    ]
    deals = [
        {
            "id": 100,
            "title": "Big deal",
            "owner_id": ME_ID,
            "creator_user_id": ME_ID,
            "person_id": 10,
            "org_id": 1,
            "status": "open",
            "value": 5000,
            "currency": "EUR",
            "expected_close_date": "2026-12-20",
            "add_time": "2026-10-01T08:00:00Z",
            "update_time": "2026-11-05T09:00:00Z",
        },
        {
            "id": 101,
            "title": "Old deal",
            "owner_id": ME_ID,
            "person_id": 10,
            "status": "won",
            "won_time": "2026-11-06T12:00:00Z",
            "expected_close_date": "2026-11-01",
            "add_time": "2026-09-01T08:00:00Z",
            "update_time": "2026-11-06T12:00:00Z",
        },
        {
            "id": 102,
            "title": "Colleague deal",
            "owner_id": 99,
            "creator_user_id": 99,
            "person_id": 12,
            "status": "open",
            "expected_close_date": "2026-12-01",
            "add_time": "2026-10-02T08:00:00Z",
            "update_time": "2026-11-07T09:00:00Z",
        },
    ]
    archived = [
        {
            "id": 103,
            "title": "Archived deal",
            "owner_id": ME_ID,
            "person_id": 11,
            "status": "lost",
            "lost_time": "2026-08-01T12:00:00Z",
            "lost_reason": "budget",
            "is_archived": True,
            "add_time": "2026-07-01T08:00:00Z",
            "update_time": "2026-11-08T09:00:00Z",
        }
    ]
    activities = [
        {
            "id": 200,
            "subject": "Follow-up call",
            "type": "call",
            "owner_id": ME_ID,
            "creator_user_id": ME_ID,
            "deal_id": 100,
            "person_id": 10,
            "due_date": "2026-12-01",
            "due_time": "15:00:00",
            "done": False,
            "participants": [{"person_id": 10, "primary": True}],
            "attendees": [],
            "note": "<p>Ask about <b>pricing</b></p>",
            "conference_meeting_url": "https://meet.demo.example/abc?pwd=SECRET",
            "add_time": "2026-11-09T08:00:00Z",
            "update_time": "2026-11-09T08:00:00Z",
        },
        {
            "id": 201,
            "subject": "Kick-off",
            "type": "meeting",
            "owner_id": 99,
            "creator_user_id": 99,
            "person_id": 11,
            "due_date": "2026-11-10",
            "due_time": "09:30:00",
            "done": True,
            "participants": [{"person_id": 11, "primary": True}],
            "attendees": [
                {
                    "user_id": ME_ID,
                    "email": "alex@demo.example",
                    "name": "Alex Demo",
                    "is_organizer": False,
                },
                {"email": "dee@guest.example", "name": "Dee Guest"},
                {"person_id": 11, "name": "Bo Demo"},
            ],
            "add_time": "2026-11-01T08:00:00Z",
            "update_time": "2026-11-10T10:00:00Z",
        },
        {
            "id": 202,
            "subject": "Colleague task",
            "type": "task",
            "owner_id": 99,
            "creator_user_id": 99,
            "person_id": 12,
            "due_date": "2026-12-05",
            "due_time": "",
            "done": False,
            "participants": [{"person_id": 12, "primary": True}],
            "add_time": "2026-11-11T08:00:00Z",
            "update_time": "2026-11-11T08:00:00Z",
        },
        {
            "id": 203,
            "subject": "Sent proposal",
            "type": "email",
            "owner_id": ME_ID,
            "deal_id": 100,
            "person_id": 10,
            "due_date": "2026-11-12",
            "due_time": "",
            "done": True,
            "participants": [{"person_id": 10, "primary": True}],
            "add_time": "2026-11-12T08:00:00Z",
            "update_time": "2026-11-12T08:00:00Z",
        },
    ]
    notes = [
        {
            "id": 300,
            "user_id": ME_ID,
            "deal_id": 100,
            "person_id": None,
            "org_id": 1,
            "content": "<p>Called &amp; agreed</p><br>next step",
            "active_flag": True,
            "add_time": "2026-11-13 08:00:00",
            "update_time": "2026-11-13 08:00:00",
        },
        {
            "id": 301,
            "user_id": 99,
            "person_id": 12,
            "content": "colleague note",
            "active_flag": True,
            "add_time": "2026-11-14 08:00:00",
            "update_time": "2026-11-14 08:00:00",
        },
    ]
    return {
        "organizations": orgs,
        "persons": persons,
        "deals": deals,
        "deals/archived": archived,
        "activities": activities,
        "notes": notes,
        "deleted_deals": [],
    }


def _ts(v: str) -> str:
    return pd_api.iso(v)


def make_handler(w, seen=None, page2_persons=True):
    def handler(url, params):
        u = urlparse(url)
        path = u.path
        if seen is not None:
            seen.append((url, params))
        if url == "https://api.pipedrive.com/v1/users/me" or path == "/api/v1/users/me":
            return ok(
                {
                    "id": ME_ID,
                    "name": "Alex Demo",
                    "email": "Alex@Demo.example",
                    "company_id": 5,
                    "company_name": "Demo Co",
                    "company_domain": DOMAIN,
                },
                headers={"date": SERVER_DATE, "x-ratelimit-limit": "20"},
            )
        assert u.hostname == f"{DOMAIN}.pipedrive.com", url
        since = params.get("updated_since")

        def recent(items):
            if not since:
                return list(items)
            lo = _ts(since)
            return [i for i in items if _ts(i.get("update_time")) >= lo]

        if path.startswith("/api/v2/"):
            name = path[len("/api/v2/") :]
            assert params.get("limit") == 500
            if name == "deals" and params.get("status") == "deleted":
                return ok(w["deleted_deals"])
            assert params.get("sort_by") == "update_time" and params.get("sort_direction") == "asc"
            if name == "activities":
                assert params.get("include_fields") == "attendees"
            items = recent(w[name])
            if name == "persons" and page2_persons and len(items) > 2:
                if params.get("cursor") == "c2":
                    return ok(items[2:], {"next_cursor": None})
                return ok(items[:2], {"next_cursor": "c2"})
            return ok(items, {"next_cursor": None})
        if path == "/api/v1/notes":
            assert params.get("sort") == "update_time ASC"
            items = recent(w["notes"])
            start = int(params.get("start", 0))
            chunk = items[start : start + 1]
            more = start + 1 < len(items)
            return ok(
                chunk,
                {
                    "pagination": {
                        "start": start,
                        "limit": 500,
                        "more_items_in_collection": more,
                        "next_start": start + 1 if more else None,
                    }
                },
            )
        return FakeResp(404, {"success": False, "error": "Not found"})

    return handler


def token_auth(tok="demo-api-token"):
    return pd_api.Auth("api_token", "test", token=tok)


def client_for(handler, sleeps=None, **kw):
    sess = FakeSession(handler)
    c = pd_api.Client(
        token_auth(),
        session=sess,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=lambda: 0.0,
        delay=0,
        **kw,
    )
    return c, sess


# --------------------------------------------------------------------------- credentials


@pytest.fixture
def no_secrets(monkeypatch):
    import secrets_adapter

    store: dict = {}
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: store.get((s, a)))
    for k in (
        pd_api.ENV_API_TOKEN,
        pd_api.ENV_CLIENT_ID,
        pd_api.ENV_CLIENT_SECRET,
        pd_api.ENV_REFRESH,
        pd_api.ENV_TOKEN_FILE,
    ):
        monkeypatch.delenv(k, raising=False)
    return store


def test_api_token_keychain_first_then_env(no_secrets, monkeypatch):
    monkeypatch.setenv(pd_api.ENV_API_TOKEN, "from-env")
    no_secrets[("sbk-pipedrive", "api-token")] = "from-keychain"
    a = pd_api.resolve_auth("auto")
    assert (a.kind, a.token, a.where) == (
        "api_token",
        "from-keychain",
        "keychain sbk-pipedrive/api-token",
    )
    no_secrets.clear()
    a = pd_api.resolve_auth("auto")
    assert (a.token, a.where) == ("from-env", "env PIPEDRIVE_API_TOKEN")
    assert "from-env" not in repr(vars(a)["where"])


def test_oauth_used_when_no_api_token(no_secrets, monkeypatch):
    monkeypatch.setenv(pd_api.ENV_CLIENT_ID, "cid")
    monkeypatch.setenv(pd_api.ENV_CLIENT_SECRET, "csecret")
    with pytest.raises(pd_api.NoCredentials):
        pd_api.resolve_auth("auto")  # app but no sign-in yet
    no_secrets[("sbk-pipedrive", "refresh-token")] = "rt"
    a = pd_api.resolve_auth("auto")
    assert a.kind == "oauth" and a.oauth["refresh_token"] == "rt" and a.token == ""
    with pytest.raises(pd_api.NoCredentials):
        pd_api.resolve_auth("api_token")
    monkeypatch.setenv(pd_api.ENV_API_TOKEN, "tok")
    assert pd_api.resolve_auth("oauth").kind == "oauth"
    assert pd_api.resolve_auth("auto").kind == "api_token"


def test_refresh_token_file(no_secrets, monkeypatch, tmp_path):
    f = tmp_path / "pd-refresh"
    monkeypatch.setenv(pd_api.ENV_TOKEN_FILE, str(f))
    assert pd_api.save_refresh_token("rt-file") == "file PIPEDRIVE_TOKEN_FILE"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert pd_api.load_refresh_token() == ("rt-file", "file PIPEDRIVE_TOKEN_FILE")


def test_headers_per_auth_kind():
    h = token_auth("t1").headers()
    assert h["x-api-token"] == "t1" and "Authorization" not in h and h["User-Agent"]
    h = pd_api.Auth("oauth", "x", token="acc").headers()
    assert h["Authorization"] == "Bearer acc" and "x-api-token" not in h


# --------------------------------------------------------------------------- client


def test_data_client_is_get_only_and_post_only_to_token_url():
    public = {n for n in dir(pd_api.Client) if not n.startswith("_")}
    assert not public & {"post", "put", "patch", "delete", "request"}
    data_src = (PD / "pd_api.py").read_text() + "".join(p.read_text() for p in PD.glob("pd-*.py"))
    for verb in (".post(", ".put(", ".patch(", ".delete(", ".request(", "urlopen("):
        assert verb not in data_src
    oauth_src = (PD / "pd_oauth.py").read_text()
    assert oauth_src.count(".post(") == 1 and "TOKEN_URL," in oauth_src
    assert pd_oauth.TOKEN_URL == "https://oauth.pipedrive.com/oauth/token"
    for verb in (".put(", ".patch(", ".delete("):
        assert verb not in oauth_src


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/users/me",
        "http://demo-co.pipedrive.com/api/v2/deals",
        "https://pipedrive.com.evil.example/api/v2/deals",
        "https://demo-co.pipedrive.com.evil.example/x",
    ],
)
def test_credential_never_leaves_pipedrive(url):
    c, sess = client_for(lambda u, p: ok({}))
    with pytest.raises(pd_api.PipedriveError):
        c.get(url)
    assert sess.calls == []


def test_company_base_validates_domain():
    assert pd_api.company_base("demo-co") == BASE
    assert pd_api.company_base("evil.example/x") == pd_api.ROOT_API
    assert pd_api.company_base("") == pd_api.ROOT_API


def test_429_waits_for_the_window_then_succeeds():
    answers = [
        FakeResp(429, {"success": False}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "2"}),
        FakeResp(429, {"success": False}, {"retry-after": "5"}),
        ok({"id": 1}),
    ]
    sleeps: list[float] = []
    c, _ = client_for(lambda u, p: answers.pop(0), sleeps)
    assert c.get(f"{BASE}/api/v2/deals")["data"] == {"id": 1}
    assert sleeps == [2.0, 5.0]


def test_429_forever_is_rate_limited():
    c, sess = client_for(lambda u, p: FakeResp(429, {"success": False}), max_retries=2)
    with pytest.raises(pd_api.RateLimited):
        c.get(f"{BASE}/api/v2/deals")
    assert len(sess.calls) == 3


def test_cloudflare_403_is_one_short_line():
    c, _ = client_for(lambda u, p: FakeResp(403, None, text="<html>Cloudflare 1020</html>"))
    with pytest.raises(pd_api.PipedriveError) as e:
        c.get(f"{BASE}/api/v2/deals")
    assert e.value.status == 403 and "<html>" not in str(e.value)


def test_pacing_between_requests():
    t = [0.0]
    sleeps: list[float] = []
    sess = FakeSession(lambda u, p: ok([]))
    c = pd_api.Client(token_auth(), session=sess, sleep=sleeps.append, clock=lambda: t[0])
    c.get(f"{BASE}/api/v2/deals")
    t[0] = 0.05
    c.get(f"{BASE}/api/v2/deals")
    assert sleeps and abs(sleeps[0] - (pd_api.REQUEST_DELAY - 0.05)) < 1e-9


def test_401_with_oauth_refreshes_once():
    answers = [FakeResp(401, {"success": False}), ok({"ok": 1})]
    sess = FakeSession(lambda u, p: answers.pop(0))
    auth = pd_api.Auth("oauth", "x", token="old")
    c = pd_api.Client(auth, session=sess, sleep=lambda s: None, delay=0, refresher=lambda: "new")
    assert c.get(f"{BASE}/api/v2/deals")["data"] == {"ok": 1}
    assert sess.calls[0][2]["Authorization"] == "Bearer old"
    assert sess.calls[1][2]["Authorization"] == "Bearer new"


def test_401_with_api_token_is_an_error():
    c, _ = client_for(lambda u, p: FakeResp(401, {"success": False, "error": "unauthorized"}))
    with pytest.raises(pd_api.PipedriveError) as e:
        c.get(f"{BASE}/api/v2/deals")
    assert e.value.status == 401


def test_request_cap():
    c, sess = client_for(lambda u, p: ok([]), max_requests=2)
    c.get(f"{BASE}/api/v2/deals")
    c.get(f"{BASE}/api/v2/deals")
    with pytest.raises(pd_api.RequestCap):
        c.get(f"{BASE}/api/v2/deals")
    assert len(sess.calls) == 2


# --------------------------------------------------------------------------- helpers


def test_iso_and_html():
    assert pd_api.iso("2026-01-02T03:04:05Z") == "2026-01-02T03:04:05+00:00"
    assert pd_api.iso("2026-01-02 03:04:05") == "2026-01-02T03:04:05+00:00"
    assert pd_api.iso("2026-01-02") == "2026-01-02"
    assert pd_api.iso("") == ""
    assert pd_api.strip_html("<p>A &amp; B</p><br>c") == "A & B\nc"


# --------------------------------------------------------------------------- L0


@pytest.fixture
def downloaded(tmp_path):
    w = world()
    seen: list = []
    c, sess = client_for(make_handler(w, seen))
    dest = tmp_path / "pipedrive"
    summary = pd_api.run_download(c, dest)
    return dest, summary, sess, seen, w


def test_l0_files_and_summary(downloaded):
    dest, summary, sess, seen, _ = downloaded
    for f in (
        "state.json",
        "download-summary.json",
        "raw/me.json",
        "raw/organizations.json",
        "raw/persons.json",
        "raw/deals.json",
        "raw/activities.json",
        "raw/notes.json",
    ):
        assert (dest / f).exists(), f
    me = json.loads((dest / "raw" / "me.json").read_text())
    assert (
        me["id"] == ME_ID and me["email"] == "alex@demo.example" and me["company_domain"] == DOMAIN
    )
    # after /v1/users/me every call goes to the company domain
    assert all(u.startswith(BASE) for u, _ in seen[1:])
    assert summary["complete"] is True and summary["user_id"] == ME_ID
    assert summary["persons_total"] == 4  # the deleted person is not kept
    assert summary["deals_total"] == 4  # 3 deals + 1 archived
    assert summary["notes_total"] == 2 and summary["activities_total"] == 4
    # me + 5 v2 list pages + 1 archived-deals page (20) + 2 notes pages (20)
    assert summary["api_tokens_estimate"] == 2 + 10 * 5 + 20 + 20 * 2
    assert summary["burst_limit_per_2s"] == "20"
    # first run: no updated_since
    assert not any("updated_since" in p for _, p in seen)
    # the cursor of the persons list was followed
    assert any(p.get("cursor") == "c2" for _, p in seen)


def test_l0_drops_private_fields(downloaded):
    dest, *_ = downloaded
    persons = json.loads((dest / "raw" / "persons.json").read_text())
    ada = persons["10"]
    assert "birthday" not in ada and "postal_address" not in ada and "notes" not in ada
    assert ada["emails"][1] == {"value": "Ada@Acme.example", "primary": True}
    acts = (dest / "raw" / "activities.json").read_text()
    assert "SECRET" not in acts and "conference" not in acts
    assert json.loads(acts)["200"]["note"] == "Ask about pricing"


def test_incremental_run_uses_watermark_and_drops_deleted_deals(downloaded):
    dest, _, _, _, w = downloaded
    state = json.loads((dest / "state.json").read_text())
    assert state["watermarks"]["deals"] == "2026-11-25T10:00:00+00:00"  # Pipedrive's Date header
    w["deals"][0]["update_time"] = "2026-11-25T10:30:00Z"
    w["deals"][0]["title"] = "Big deal renamed"
    w["deleted_deals"] = [{"id": 101, "status": "deleted"}]
    seen: list = []
    c, _ = client_for(make_handler(w, seen))
    summary = pd_api.run_download(c, dest)
    sinces = {p.get("updated_since") for _, p in seen if "updated_since" in p}
    assert sinces == {"2026-11-25T09:00:00Z"}  # one hour of overlap
    deals = json.loads((dest / "raw" / "deals.json").read_text())
    assert deals["100"]["title"] == "Big deal renamed" and "101" not in deals
    assert summary["deals_read"] == 1 and summary["deals_deleted_removed"] == 1
    assert summary["persons_total"] == 4  # nothing lost from the stores


def test_since_days_first_run(tmp_path):
    seen: list = []
    c, _ = client_for(make_handler(world(), seen))
    pd_api.run_download(c, tmp_path / "pipedrive", since_days=30, steps=("deals",))
    sinces = {p.get("updated_since") for _, p in seen if "updated_since" in p}
    assert sinces == {"2026-10-26T10:00:00Z"}


def test_request_cap_stops_and_resumes(tmp_path):
    w = world()
    c, _ = client_for(
        make_handler(w), max_requests=3
    )  # me + 2 persons pages... cap hits inside persons
    dest = tmp_path / "pipedrive"
    summary = pd_api.run_download(c, dest)
    assert summary["complete"] is False and summary["stopped_at"] == "persons"
    assert summary["stopped_because"].startswith("request cap")
    state = json.loads((dest / "state.json").read_text())
    # organizations finished, persons resume from the newest record of page 1
    assert state["watermarks"]["organizations"] == "2026-11-25T10:00:00+00:00"
    assert state["watermarks"]["persons"] == "2026-11-03T09:00:00+00:00"
    assert "deals" not in state["watermarks"]
    assert len(json.loads((dest / "raw" / "persons.json").read_text())) == 2


def test_rate_limit_mid_run_keeps_what_was_read(tmp_path):
    w = world()
    base = make_handler(w)

    def handler(url, params):
        if urlparse(url).path == "/api/v2/deals" and params.get("status") != "deleted":
            return FakeResp(429, {"success": False})
        return base(url, params)

    c, _ = client_for(handler, max_retries=1)
    dest = tmp_path / "pipedrive"
    with pytest.raises(pd_api.RateLimited):
        pd_api.run_download(c, dest)
    assert len(json.loads((dest / "raw" / "persons.json").read_text())) == 4
    s = json.loads((dest / "download-summary.json").read_text())
    assert (
        s["complete"] is False
        and s["stopped_at"] == "deals"
        and s["stopped_because"] == "rate limit"
    )


def test_full_run_drops_what_was_deleted(downloaded):
    dest, _, _, _, w = downloaded
    # deleted in Pipedrive after the first run: an incremental list never shows them
    w["persons"] = [p for p in w["persons"] if p["id"] != 12]
    w["organizations"] = []
    w["activities"] = [a for a in w["activities"] if a["id"] != 203]
    w["notes"] = [n for n in w["notes"] if n["id"] != 301]
    w["deals/archived"] = []
    c, _ = client_for(make_handler(w))
    summary = pd_api.run_download(c, dest)
    assert "12" in json.loads((dest / "raw" / "persons.json").read_text())  # incremental keeps
    c, _ = client_for(make_handler(w))
    summary = pd_api.run_download(c, dest, full=True)
    raw = dest / "raw"
    assert set(json.loads((raw / "persons.json").read_text())) == {"10", "11", "13"}
    assert json.loads((raw / "organizations.json").read_text()) == {}
    assert "203" not in json.loads((raw / "activities.json").read_text())
    assert set(json.loads((raw / "notes.json").read_text())) == {"300"}
    assert set(json.loads((raw / "deals.json").read_text())) == {"100", "101", "102"}
    assert summary["persons_pruned"] == 1 and summary["deals_pruned"] == 1
    assert summary["persons_total"] == 3


def test_full_run_stopped_early_prunes_only_finished_lists(downloaded):
    dest, _, _, _, w = downloaded
    w["persons"] = [p for p in w["persons"] if p["id"] != 12]
    w["deals"] = [d for d in w["deals"] if d["id"] != 102]
    # me, organizations, 2 persons pages, deals: the cap cuts the archived deals
    c, _ = client_for(make_handler(w), max_requests=5)
    summary = pd_api.run_download(c, dest, full=True)
    assert summary["complete"] is False and summary["stopped_at"] == "deals_archived"
    assert "12" not in json.loads((dest / "raw" / "persons.json").read_text())  # read to the end
    assert "102" in json.loads((dest / "raw" / "deals.json").read_text())  # deals store was cut
    assert summary["persons_pruned"] == 1 and "deals_pruned" not in summary


def test_offset_pages_overlap_so_a_shift_skips_nothing():
    # 30 notes, pages of 20; note 5 is deleted after the first page: the list shifts
    notes = [{"id": i, "update_time": f"2026-11-01T00:00:{i:02d}Z"} for i in range(30)]
    state = {"calls": 0}

    def handler(url, params):
        state["calls"] += 1
        items = notes if state["calls"] == 1 else [n for n in notes if n["id"] != 5]
        start, limit = int(params["start"]), int(params["limit"])
        chunk = items[start : start + limit]
        more = start + limit < len(items)
        pag = {"more_items_in_collection": more, "next_start": start + limit if more else None}
        return ok(chunk, {"pagination": pag})

    c, sess = client_for(handler)
    got = {r["id"] for page in c.offset_pages(f"{BASE}/api/v1/notes", {"limit": 20}) for r in page}
    assert got == set(range(30))  # without the overlap, id 20 would be skipped
    assert [p["start"] for _, p, _ in sess.calls] == [0, 20 - pd_api.OFFSET_OVERLAP]


def test_non_json_success_is_one_error():
    class Bad(FakeResp):
        def json(self):
            raise ValueError("not json")

    c, _ = client_for(lambda u, p: Bad(200, None, text="<html>maintenance</html>"))
    with pytest.raises(pd_api.PipedriveError) as e:
        c.get(f"{BASE}/api/v2/deals")
    assert "not JSON" in str(e.value)


def test_oauth_refused_mid_run_is_one_line(monkeypatch, tmp_path, capsys):
    """A refresh refused during the download ends with one line, not a traceback."""
    import importlib.util

    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)  # never a developer's .env

    spec = importlib.util.spec_from_file_location("pd_l0_download", PD / "pd-l0-download.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    auth = pd_api.Auth(
        "oauth", "x", oauth={"client_id": "c", "client_secret": "s", "refresh_token": "r"}
    )
    monkeypatch.setattr(pd_api, "resolve_auth", lambda mode=None: auth)
    calls = {"n": 0}

    def refresher_factory(a, session=None):
        def _do():
            calls["n"] += 1
            if calls["n"] > 1:
                raise pd_oauth.OAuthError("Pipedrive refused the token request (HTTP 400)")
            a.token = "acc"
            return "acc"

        return _do

    monkeypatch.setattr(pd_oauth, "make_refresher", refresher_factory)

    def run_download(client, *a, **k):
        client.auth.token = client._refresher()  # the 60-minute refresh, refused

    monkeypatch.setattr(pd_api, "run_download", run_download)
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path))
    assert mod.main(["--quiet"]) == 1
    err = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(err) == 1 and err[0].startswith("pipedrive: Pipedrive refused")


def test_archived_deals_can_be_left_out(tmp_path):
    seen: list = []
    c, _ = client_for(make_handler(world(), seen))
    pd_api.run_download(c, tmp_path / "pipedrive", include_archived_deals=False, steps=("deals",))
    assert not any(urlparse(u).path.endswith("/deals/archived") for u, _ in seen)


# --------------------------------------------------------------------------- L1


def _frames(dest, scope="mine"):
    pd_api.write_frames(dest, scope)
    c = pd.read_parquet(dest / "processed" / "plugin-contacts.parquet")
    i = pd.read_parquet(dest / "processed" / "plugin-interactions.parquet")
    return c, i


def test_l1_contract_scope_mine(downloaded):
    from plugin_intake import (
        CONTACT_COLUMNS,
        INTERACTION_COLUMNS,
        is_commitment,
        load_interactions,
        load_people,
    )

    dest, *_ = downloaded
    c, i = _frames(dest)
    assert tuple(c.columns) == CONTACT_COLUMNS
    assert (
        tuple(i.columns[: len(INTERACTION_COLUMNS)]) == INTERACTION_COLUMNS
        and "status" in i.columns
    )
    assert (c["source"] == "pipedrive").all() and (i["source"] == "pipedrive").all()

    # persons: yours or in your items; never you; the colleague-only person is left out
    assert set(c["name"]) == {"Ada Demo", "Bo Demo"}
    ada = c[c["name"] == "Ada Demo"].iloc[0]
    assert ada["email"] == "ada@acme.example" and ada["phone"] == "+1 555 0100"
    assert ada["company"] == "Acme Demo" and ada["title"] == "Buyer"
    assert ada["url"] == f"{BASE}/person/10"
    assert ada["interactions"] == 5  # deals 100, 101; activities 200, 203; note 300
    assert ada["first_seen"] < ada["last_seen"]
    assert ada["last_seen"] <= pd_api.iso(
        pd_api.now_utc()
    )  # planned activities are not contacts yet
    bo = c[c["name"] == "Bo Demo"].iloc[0]
    assert bo["email"] == "" and bo["phone"] == "+1 555 0111" and bo["interactions"] == 2

    rows = {r.url.rsplit("/", 1)[-1]: r for r in i.itertuples()}
    big = rows["100"]
    assert big.kind == "record" and big.status == "open" and big.owner_role == "assignee"
    assert big.due == "2026-12-20" and big.title == "Deal: Big deal"
    assert big.participants == "Ada Demo <ada@acme.example>"
    old = rows["101"]
    assert old.status == "done" and old.title.endswith("(won)") and old.due == ""
    assert old.ts.startswith("2026-11-06T12:00")
    arch = rows["103"]
    assert arch.status == "closed" and "lost reason budget" in arch.text and "archived" in arch.text
    assert "102" not in rows  # a colleague's deal

    call = rows["100#activity-200"]
    assert call.kind == "meeting" and call.status == "open" and call.owner_role == "assignee"
    assert call.ts == "2026-12-01T15:00:00+00:00" and call.due == call.ts
    assert call.text == "Ask about pricing"
    kick = rows["11#activity-201"]
    assert kick.owner_role == "attendee" and kick.status == "done" and kick.due == ""
    assert kick.participants == "Bo Demo|||Dee Guest <dee@guest.example>"
    mail = rows["100#activity-203"]
    assert mail.kind == "message" and mail.status == "done"
    assert not any(k.endswith("activity-202") for k in rows)

    note = rows["100#note-300"]
    assert note.kind == "record" and note.owner_role == "author" and note.status == "done"
    assert note.title == "Note: Big deal" and note.text == "Called & agreed\nnext step"
    assert note.ts == "2026-11-13T08:00:00+00:00"
    assert not any(k.endswith("note-301") for k in rows)

    # the kernel reader accepts both files as they are
    li = load_interactions(dest.parent)
    assert li is not None and len(li) == len(i)
    people = load_people(dest.parent)
    assert people is not None and "dee@guest.example" in set(people["email"])
    opened = {r.url.rsplit("/", 1)[-1] for r in li.itertuples() if is_commitment(r)}
    assert opened == {"100", "100#activity-200"}


def test_l1_scope_all(downloaded):
    from plugin_intake import is_commitment, load_interactions

    dest, *_ = downloaded
    c, i = _frames(dest, "all")
    assert set(c["name"]) == {"Ada Demo", "Bo Demo", "Cy Demo"}
    urls = {u.rsplit("/", 1)[-1] for u in i["url"]}
    assert {"102", "12#activity-202", "12#note-301"} <= urls
    col = i[i["url"].str.endswith("/102")].iloc[0]
    assert (
        col.owner_role == "other" and col.due == ""
    )  # a colleague's deal is no commitment of yours
    li = load_interactions(dest.parent)
    opened = {r.url.rsplit("/", 1)[-1] for r in li.itertuples() if is_commitment(r)}
    assert opened == {"100", "100#activity-200"}


def test_l1_empty_download(tmp_path):
    dest = tmp_path / "pipedrive"
    (dest / "raw").mkdir(parents=True)
    (dest / "raw" / "me.json").write_text(json.dumps({"id": ME_ID, "company_domain": DOMAIN}))
    c, i = _frames(dest)
    assert c.empty and i.empty and "status" in i.columns


# --------------------------------------------------------------------------- OAuth


def test_oauth_exchange_and_refresh_post_to_token_url(no_secrets, monkeypatch):
    def post(url, data):
        assert url == pd_oauth.TOKEN_URL
        body = {
            "access_token": "acc",
            "refresh_token": "rt2",
            "scope": "base deals:read contacts:read activities:read",
            "expires_in": 3599,
            "api_domain": BASE,
        }
        return FakeResp(200, body)

    sess = FakeSession(lambda u, p: ok({}), post)
    pd_oauth.exchange_code(sess, "cid", "sec", "code1", pd_oauth.redirect_uri(8765))
    url, form, headers = sess.posts[0]
    assert form == {
        "grant_type": "authorization_code",
        "code": "code1",
        "redirect_uri": "http://127.0.0.1:8765/callback",
    }
    assert headers["Authorization"] == "Basic Y2lkOnNlYw=="  # base64("cid:sec")
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"

    saved: list[str] = []
    monkeypatch.setattr(pd_api, "save_refresh_token", lambda t: saved.append(t) or "x")
    auth = pd_api.Auth(
        "oauth", "x", oauth={"client_id": "cid", "client_secret": "sec", "refresh_token": "rt1"}
    )
    tok = pd_oauth.make_refresher(auth, sess)()
    assert tok == "acc" and auth.token == "acc" and auth.oauth["api_domain"] == BASE
    assert saved == ["rt2"] and auth.oauth["refresh_token"] == "rt2"
    assert sess.posts[1][1] == {"grant_type": "refresh_token", "refresh_token": "rt1"}


def test_oauth_refused_is_one_line():
    sess = FakeSession(lambda u, p: ok({}), lambda u, d: FakeResp(401, {"error": "invalid_client"}))
    with pytest.raises(pd_oauth.OAuthError) as e:
        pd_oauth.refresh(sess, "cid", "SEC-XYZ", "RT-XYZ")
    msg = str(e.value)
    assert "HTTP 401" in msg and "SEC-XYZ" not in msg and "RT-XYZ" not in msg and "\n" not in msg


def test_oauth_scopes_check():
    assert pd_oauth.missing_scopes("base deals:read") == ["contacts:read", "activities:read"]
    assert pd_oauth.missing_scopes("base deals:read contacts:read activities:read") == []
    assert pd_oauth.extra_scopes("base deals:full admin contacts:read") == ["deals:full", "admin"]
    u = pd_oauth.authorize_url("cid", "http://127.0.0.1:8765/callback", "st")
    assert u.startswith("https://oauth.pipedrive.com/oauth/authorize?") and "state=st" in u


def test_oauth_download_uses_api_domain(tmp_path):
    seen: list = []
    sess = FakeSession(make_handler(world(), seen))
    auth = pd_api.Auth("oauth", "x", token="acc", oauth={"api_domain": BASE})
    c = pd_api.Client(auth, session=sess, sleep=lambda s: None, delay=0)
    pd_api.run_download(c, tmp_path / "pipedrive", api_domain=BASE, steps=("organizations",))
    assert seen[0][0] == f"{BASE}/api/v1/users/me"
    assert all(h["Authorization"] == "Bearer acc" for _, _, h in sess.calls)


# --------------------------------------------------------------------------- scripts


def _run(script, *args, data_root=None):
    """Run a script with no credential and no way out to the network.

    Credential variables are set to empty (python-dotenv never overrides an existing
    variable, so a developer's .env cannot slip one in), container mode keeps the
    Keychain out, and the proxies point to a closed local port.
    """
    env = dict(os.environ)
    cfg = data_root / "owner-only.json"
    cfg.write_text(json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}))
    env.update(
        {
            "PIPEDRIVE_API_TOKEN": "",
            "PIPEDRIVE_CLIENT_ID": "",
            "PIPEDRIVE_CLIENT_SECRET": "",
            "PIPEDRIVE_REFRESH_TOKEN": "",
            "PIPEDRIVE_TOKEN_FILE": "",
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
        [sys.executable, str(PD / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(data_root),
    )


@pytest.mark.parametrize("script", ["pd-l0-download.py", "pd-l0-auth.py", "pd-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    p = _run(script, "--help", data_root=tmp_path)
    assert p.returncode == 0 and "usage" in p.stdout.lower() and "Traceback" not in p.stderr


@pytest.mark.parametrize("script", ["pd-l0-download.py", "pd-l0-auth.py", "pd-l1-enrich.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    p = _run(script, data_root=tmp_path)
    assert p.returncode == 1
    lines = [ln for ln in p.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("pipedrive:") and "Traceback" not in p.stderr
    assert not (tmp_path / "pipedrive" / "raw").exists()


def test_no_secret_in_sources():
    src = "".join(p.read_text() for p in PD.glob("*.py"))
    assert not re.search(r"[0-9a-f]{40}", src)  # no API token pasted in the code
