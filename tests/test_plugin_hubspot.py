"""HubSpot plugin: mocked network only (no real account, no real HTTP to HubSpot, no Keychain).

The fake below answers the endpoints the plugin calls with the shapes documented on
developers.hubspot.com (search results/paging, owners, pipelines, OAuth v3 token and
introspection). It was never compared with a real HubSpot account.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
HS = ROOT / "tools" / "hubspot"
sys.path.insert(0, str(HS))
sys.path.insert(0, str(ROOT / "tools" / "cross-source"))

import hs_api  # noqa: E402
import plugin_intake  # noqa: E402
import secrets_adapter  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("hs_l0_download", "hs-l0-download.py")
L1 = _load("hs_l1_enrich", "hs-l1-enrich.py")
AUTH = _load("hs_l0_auth", "hs-l0-auth.py")

ME_EMAIL = "alex@personal.example"
ACCESS = "AT-fake-access"
REFRESH = "RT-fake-refresh"
SECRET = "CS-fake-secret"
CID = "client-id-demo"


def _rec(rid, props, assoc=None):
    r = {"id": rid, "properties": dict(props), "archived": False}
    if assoc:
        r["assoc"] = assoc
    return r


def _base_data():
    return {
        "contacts": [
            _rec(
                "c1",
                {
                    "firstname": "Mia",
                    "lastname": "Conti",
                    "email": "Mia@Client.example",
                    "jobtitle": "CFO",
                    "company": "",
                    "associatedcompanyid": "co1",
                    "hubspot_owner_id": "77",
                    "createdate": "2026-01-10T09:00:00Z",
                    "lastmodifieddate": "2026-11-01T10:00:00Z",
                },
            ),
            _rec(
                "c2",
                {
                    "firstname": "Alex",
                    "lastname": "Demo",
                    "email": ME_EMAIL,
                    "hubspot_owner_id": "77",
                    "lastmodifieddate": "2026-11-02T10:00:00Z",
                },
            ),
            _rec(
                "c3",
                {
                    "firstname": "Bo",
                    "lastname": "Rossi",
                    "email": "bo@supplier.example",
                    "company": "Contoso Demo",
                    "jobtitle": "Buyer",
                    "hubspot_owner_id": "88",
                    "lastmodifieddate": "2026-10-01T10:00:00Z",
                },
            ),
        ],
        "companies": [
            _rec("co1", {"name": "Northwind Demo", "domain": "northwind.example"}),
            _rec("co2", {"name": "Contoso Demo", "domain": "contoso.example"}),
        ],
        "deals": [
            _rec(
                "d1",
                {
                    "dealname": "Pilot",
                    "dealstage": "appt",
                    "pipeline": "default",
                    "amount": "5000",
                    "deal_currency_code": "EUR",
                    "closedate": "2026-12-15T00:00:00Z",
                    "hubspot_owner_id": "77",
                    "createdate": "2026-10-05T08:00:00Z",
                    "hs_lastmodifieddate": "2026-11-20T08:00:00Z",
                    "hs_is_closed": "false",
                    "hs_is_closed_won": "false",
                },
                {"contacts": ["c1", "c2", "c3"], "companies": ["co1"]},
            ),
            _rec(
                "d2",
                {
                    "dealname": "Renewal",
                    "dealstage": "won",
                    "closedate": "2026-09-30T00:00:00Z",
                    "hubspot_owner_id": "77",
                    "createdate": "2026-08-01T08:00:00Z",
                    "hs_lastmodifieddate": "2026-10-01T08:00:00Z",
                    "hs_is_closed": "true",
                    "hs_is_closed_won": "true",
                },
                {"contacts": ["c1"]},
            ),
            _rec(
                "d3",
                {
                    "dealname": "Teammate deal",
                    "dealstage": "appt",
                    "closedate": "2026-12-20T00:00:00Z",
                    "hubspot_owner_id": "88",
                    "createdate": "2026-11-01T08:00:00Z",
                    "hs_lastmodifieddate": "2026-11-21T08:00:00Z",
                },
                {"contacts": ["c3"], "companies": ["co2"]},
            ),
        ],
        "tasks": [
            _rec(
                "t1",
                {
                    "hs_task_subject": "Send the proposal",
                    "hs_task_body": "<p>Draft is in the folder</p>",
                    "hs_task_status": "NOT_STARTED",
                    "hs_task_priority": "HIGH",
                    "hs_timestamp": "2026-12-01T09:00:00Z",
                    "hubspot_owner_id": "77",
                    "hs_createdate": "2026-11-18T09:00:00Z",
                    "hs_lastmodifieddate": "2026-11-18T09:00:00Z",
                },
                {"contacts": ["c1"], "deals": ["d1"]},
            ),
            _rec(
                "t2",
                {
                    "hs_task_subject": "Book the call",
                    "hs_task_status": "COMPLETED",
                    "hs_timestamp": "2026-11-10T09:00:00Z",
                    "hubspot_owner_id": "77",
                    "hs_createdate": "2026-11-05T09:00:00Z",
                    "hs_lastmodifieddate": "2026-11-10T09:00:00Z",
                },
                {"contacts": ["c1"]},
            ),
        ],
        "notes": [
            _rec(
                "n1",
                {
                    "hs_note_body": "<p>Call recap</p><p>Next: send &amp; sign</p>",
                    "hs_timestamp": "2026-11-19T15:00:00Z",
                    "hubspot_owner_id": "77",
                    "hs_lastmodifieddate": "2026-11-19T15:00:00Z",
                },
                {"contacts": ["c1"], "deals": ["d1"]},
            ),
        ],
    }


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, code, body=b"{}", headers=None):
    return HTTPError(url, code, "err", headers or {}, io.BytesIO(body))


class FakeHubSpot:
    """Answers the HubSpot endpoints the plugin calls; records every request."""

    def __init__(self, user_level=True, owners_status=200, data=None):
        self.data = data or _base_data()
        self.user_level = user_level
        self.owners_status = owners_status
        self.calls: list[tuple[str, str, dict | None]] = []
        self.searches: list[tuple[str, dict]] = []
        self.fail_next: list[tuple[str, int, bytes]] = []  # (path fragment, status, body)
        self.refresh_tokens_out = [REFRESH]

    def _find(self, obj, rid):
        for r in self.data.get(obj, []):
            if r["id"] == rid:
                return r
        return None

    def __call__(self, req, timeout):
        url = req.full_url
        u = urlparse(url)
        body = req.data
        payload = None
        if body:
            ctype = req.headers.get("Content-type", "")
            payload = dict(parse_qs(body.decode())) if "form" in ctype else json.loads(body)
            if "form" in ctype:
                payload = {k: v[0] for k, v in payload.items()}
        self.calls.append((req.get_method(), url, payload))
        for i, (frag, code, b) in enumerate(self.fail_next):
            if frag in u.path:
                self.fail_next.pop(i)
                raise _http_error(url, code, b)
        if u.hostname not in ("api.hubapi.com", "api.hubspot.com"):
            raise AssertionError(f"unexpected host {u.hostname}")
        if u.path == "/oauth/v3/token":
            assert payload["client_secret"] == SECRET
            nxt = (
                self.refresh_tokens_out[0]
                if len(self.refresh_tokens_out) == 1
                else self.refresh_tokens_out.pop(0)
            )
            return _Resp(
                json.dumps(
                    {"access_token": ACCESS, "refresh_token": nxt, "expires_in": 1800}
                ).encode()
            )
        if u.path == "/oauth/v3/token/introspect":
            return _Resp(
                json.dumps(
                    {
                        "active": True,
                        "user": ME_EMAIL,
                        "user_id": 501,
                        "hub_id": 9001,
                        "scopes": ["oauth", *hs_api.REQUIRED_SCOPES, *hs_api.OPTIONAL_SCOPES],
                        "signed_access_token": {"hublet": "na1", "isUserLevel": self.user_level},
                    }
                ).encode()
            )
        assert req.headers.get("Authorization") == f"Bearer {ACCESS}"
        if u.path == "/crm/owners/2026-09":
            if self.owners_status != 200:
                raise _http_error(url, self.owners_status, b'{"message":"not allowed"}')
            return _Resp(
                json.dumps(
                    {
                        "results": [
                            {"id": "88", "email": "sam@team.example", "userId": 502},
                            {"id": "77", "email": ME_EMAIL, "userId": 501},
                        ]
                    }
                ).encode()
            )
        if u.path == "/crm/pipelines/2026-09/deals":
            stages = [
                {
                    "id": "appt",
                    "label": "Appointment",
                    "metadata": {"isClosed": "false", "probability": "0.2"},
                },
                {
                    "id": "won",
                    "label": "Closed won",
                    "metadata": {"isClosed": "true", "probability": "1.0"},
                },
                {
                    "id": "lost",
                    "label": "Closed lost",
                    "metadata": {"isClosed": "true", "probability": "0.0"},
                },
            ]
            return _Resp(
                json.dumps(
                    {"results": [{"id": "default", "label": "Sales", "stages": stages}]}
                ).encode()
            )
        parts = u.path.split("/")  # ['', 'crm', 'objects', '2026-09', obj, ...]
        assert parts[1:4] == ["crm", "objects", "2026-09"], u.path
        obj = parts[4]
        if len(parts) == 6 and parts[5] == "search":
            assert req.get_method() == "POST"
            self.searches.append((obj, payload))
            return _Resp(json.dumps(self._search(obj, payload)).encode())
        if len(parts) == 7 and parts[5:] == ["batch", "read"]:
            ids = [x["id"] for x in payload["inputs"]]
            out = [self._public(r) for r in self.data.get(obj, []) if r["id"] in ids]
            return _Resp(json.dumps({"status": "COMPLETE", "results": out}).encode())
        if len(parts) == 6 and req.get_method() == "GET":
            r = self._find(obj, parts[5])
            if r is None:
                raise _http_error(url, 404, b'{"message":"not found"}')
            out = self._public(r)
            wanted = (parse_qs(u.query).get("associations") or [""])[0].split(",")
            out["associations"] = {
                k: {"results": [{"id": i, "type": f"{obj}_to_{k}"} for i in v]}
                for k, v in (r.get("assoc") or {}).items()
                if k in wanted
            }
            return _Resp(json.dumps(out).encode())
        raise AssertionError(f"unexpected call {req.get_method()} {url}")

    @staticmethod
    def _public(r):
        return {"id": r["id"], "properties": r["properties"], "archived": False}

    def _search(self, obj, body):
        mod = hs_api.OBJECTS[obj]["modified"]
        rows = list(self.data.get(obj, []))
        for g in body.get("filterGroups") or []:
            for f in g["filters"]:
                if f["operator"] == "GTE":
                    lo = int(f["value"])
                    rows = [r for r in rows if (hs_api.to_ms(r["properties"].get(mod)) or 0) >= lo]
                elif f["operator"] == "EQ":
                    rows = [
                        r for r in rows if str(r["properties"].get(f["propertyName"])) == f["value"]
                    ]
        rows.sort(key=lambda r: hs_api.to_ms(r["properties"].get(mod)) or 0)
        start = int(body.get("after") or 0)
        page = rows[start : start + int(body["limit"])]
        out = {"total": len(rows), "results": [self._public(r) for r in page]}
        if start + len(page) < len(rows):
            out["paging"] = {"next": {"after": str(start + len(page))}}
        return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("HUBSPOT_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("SBK_CONTAINERIZED", raising=False)
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    stored = {
        ("sbk-hubspot", "client-id"): CID,
        ("sbk-hubspot", "client-secret"): SECRET,
        ("sbk-hubspot", "default"): REFRESH,
    }
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: stored.get((s, a)))
    monkeypatch.setattr(
        secrets_adapter, "set_secret", lambda s, a, v: stored.__setitem__((s, a), v)
    )
    monkeypatch.setattr(hs_api, "REQUEST_DELAY", 0)
    monkeypatch.setattr(hs_api, "SEARCH_DELAY", 0)
    fake = FakeHubSpot()
    monkeypatch.setattr(hs_api, "_default_opener", fake)
    return {"fake": fake, "stored": stored, "tmp": tmp_path}


def _download(**kw):
    client, me = L0.connect("default")
    client._sleep = lambda s: None
    return hs_api.run_download(client, me, **kw)


# --- end to end through the kernel reader ------------------------------------------------


def test_download_and_intake_end_to_end(env):
    stats = _download()
    assert stats["only_mine_applied"] is True and stats["user_level"] is True
    # every search asked for your records only
    for obj, body in env["fake"].searches:
        owner = [
            f
            for g in body["filterGroups"]
            for f in g["filters"]
            if f["propertyName"] == "hubspot_owner_id"
        ]
        assert owner == [{"propertyName": "hubspot_owner_id", "operator": "EQ", "value": "77"}], obj
    assert stats["deals_found"] == 2 and stats["tasks_found"] == 2 and stats["notes_found"] == 1

    L1.main(["--quiet"])
    root = sbk_config.DATA_ROOT
    contacts = plugin_intake.load_contacts(root)
    by_email = {r.email: r for r in contacts.itertuples(index=False)}
    assert ME_EMAIL not in by_email  # you are not your own contact
    mia = by_email["mia@client.example"]
    assert (mia.name, mia.company, mia.title) == ("Mia Conti", "Northwind Demo", "CFO")
    assert (
        mia.interactions == 5 and mia.url == "https://app.hubspot.com/contacts/9001/record/0-1/c1"
    )
    bo = by_email["bo@supplier.example"]  # linked to your deal, owned by someone else
    assert (bo.company, bo.title) == ("Contoso Demo", "Buyer")

    ev = plugin_intake.load_interactions(root)
    rows = {r.url.rsplit("/", 1)[-1]: r for r in ev.itertuples(index=False)}
    d1, d2, t1, t2, n1 = rows["d1"], rows["d2"], rows["t1"], rows["t2"], rows["n1"]
    assert (d1.kind, d1.owner_role, d1.status) == ("record", "assignee", "open")
    assert (
        d1.due.startswith("2026-12-15")
        and "amount: 5000 EUR" in d1.text
        and "Northwind Demo" in d1.text
    )
    assert d1.title == "Deal: Pilot (Appointment)"
    assert ME_EMAIL not in d1.participants
    assert set(plugin_intake.split_participants(d1.participants)) == {
        "Mia Conti <mia@client.example>",
        "Bo Rossi <bo@supplier.example>",
    }
    assert d2.status == "done"
    assert (t1.kind, t1.status, t1.owner_role) == (
        "issue",
        "open",
        "assignee",
    ) and t1.due.startswith("2026-12-01")
    assert t2.status == "done"
    assert (n1.kind, n1.status) == (
        "message",
        "done",
    ) and n1.text == "Call recap\nNext: send & sign"
    assert n1.title == "Note: Call recap"
    commitments = {
        r.url.rsplit("/", 1)[-1]
        for r in ev.itertuples(index=False)
        if plugin_intake.is_commitment(r)
    }
    assert commitments == {"d1", "t1"}
    people = plugin_intake.load_people(root)
    assert not people[plugin_intake.FROM_PARTICIPANTS].any()  # every participant is a contact row


def test_second_run_is_incremental(env):
    first = _download()
    env["fake"].searches.clear()
    _download()
    state = json.loads(hs_api.state_path().read_text())
    for obj, body in env["fake"].searches:
        gte = [f for g in body["filterGroups"] for f in g["filters"] if f["operator"] == "GTE"]
        assert len(gte) == 1, obj
        expected = state["watermarks"][obj]  # moved to this run's start
        assert int(gte[0]["value"]) < expected
    assert first["totals"]["deals"] == 2
    # nothing changed: only records modified since the overlap window are asked for details again
    assert hs_api.summary_path().exists()


def test_all_visible_keeps_teammates_out_of_your_commitments(env):
    _download(only_mine=False)
    L1.main(["--quiet"])
    ev = plugin_intake.load_interactions(sbk_config.DATA_ROOT)
    d3 = next(r for r in ev.itertuples(index=False) if r.url.endswith("/d3"))
    assert d3.owner_role == "other" and d3.due == "" and "close date: 2026-12-20" in d3.text
    assert not plugin_intake.is_commitment(d3)


def test_owner_lookup_refused_falls_back_without_due_dates(env, monkeypatch):
    env["fake"].owners_status = 403
    stats = _download()
    assert stats["only_mine_applied"] is False and stats["owner_lookup"] == "refused (HTTP 403)"
    assert any("only mine" in w for w in stats["warnings"])
    L1.main(["--quiet"])
    ev = plugin_intake.load_interactions(sbk_config.DATA_ROOT)
    assert set(ev["due"]) == {""} and set(ev["owner_role"]) == {"other"}
    assert not any(plugin_intake.is_commitment(r) for r in ev.itertuples(index=False))


def test_teammates_items_are_not_your_interactions(env):
    # review: a teammate's deal (d3, owner 88) must not count as a contact you had with Bo
    _download(only_mine=False)
    L1.main(["--quiet"])
    contacts = plugin_intake.load_contacts(sbk_config.DATA_ROOT)
    bo = next(r for r in contacts.itertuples(index=False) if r.email == "bo@supplier.example")
    assert bo.interactions == 1  # only d1, which you own
    assert bo.first_seen.startswith("2026-10-05") and bo.last_seen.startswith("2026-10-05")


def test_no_crm_dates_pass_as_first_or_last_contact(env):
    # review: with the owner unknown nothing is yours, so no interaction dates at all; the
    # contact's createdate (2026-01-10) must not become a "first contact" in the KB
    env["fake"].owners_status = 403
    _download()
    L1.main(["--quiet"])
    contacts = plugin_intake.load_contacts(sbk_config.DATA_ROOT)
    assert set(contacts["first_seen"]) == {""} and set(contacts["last_seen"]) == {""}
    assert set(contacts["interactions"]) == {0}
    mia = next(r for r in contacts.itertuples(index=False) if r.email == "mia@client.example")
    assert (mia.name, mia.company, mia.title) == ("Mia Conti", "Northwind Demo", "CFO")


def test_unsaved_rotated_refresh_token_is_reported(env, monkeypatch):
    # review: in container mode without HUBSPOT_TOKEN_FILE a new refresh token cannot be kept
    env["fake"].refresh_tokens_out = ["RT-newer"]
    monkeypatch.setattr(hs_api, "save_refresh_token", lambda token, label="default": "")
    stats = _download()
    assert any("could not be stored" in w for w in stats["warnings"])
    summary = json.loads(hs_api.summary_path().read_text())
    assert any("could not be stored" in w for w in summary["warnings"])
    assert "RT-newer" not in hs_api.summary_path().read_text()


def test_bad_number_in_config_keeps_the_default(env, monkeypatch, capsys):
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"hubspot": {"max_details": "lots"}})
    assert L0._int_cfg("max_details", 2000) == 2000
    assert "not a number" in capsys.readouterr().out


def test_account_level_app_is_refused(env, tmp_path):
    env["fake"].user_level = False
    with pytest.raises(hs_api.AccountLevelApp):
        L0.connect("default")
    assert not hs_api.raw_dir().exists()


def test_rotated_refresh_token_is_saved(env):
    env["fake"].refresh_tokens_out = ["RT-newer"]
    L0.connect("default")
    assert env["stored"][("sbk-hubspot", "default")] == "RT-newer"


def test_no_token_or_secret_on_disk(env):
    _download()
    L1.main(["--quiet"])
    for f in sbk_config.DATA_ROOT.rglob("*"):
        if f.is_file():
            blob = f.read_bytes()
            for s in (ACCESS, REFRESH, SECRET):
                assert s.encode() not in blob, (f, s)


# --- client behaviour ---------------------------------------------------------------------


def _client(fake, **kw):
    return hs_api.HubSpotClient(
        ACCESS, opener=fake, sleep=lambda s: None, delay=0, search_delay=0, **kw
    )


def test_client_only_reads_and_only_talks_to_hubspot():
    c = _client(FakeHubSpot())
    with pytest.raises(hs_api.HubSpotError, match="only search and batch read"):
        c.post("/crm/objects/2026-09/deals", {"properties": {}})
    with pytest.raises(hs_api.HubSpotError, match="only reads"):
        c._send("PATCH", "/crm/objects/2026-09/deals/d1")
    with pytest.raises(hs_api.HubSpotError, match="refusing to send"):
        c.get("https://collector.example/crm")
    with pytest.raises(hs_api.HubSpotError, match="refusing to send"):
        hs_api._oauth_post("http://api.hubspot.com/oauth/v3/token", {})


def test_expired_access_token_is_refreshed_once():
    fake = FakeHubSpot()
    fake.fail_next.append(("/crm/owners", 401, b"{}"))
    calls = []

    def refresher():
        calls.append(1)
        return ACCESS

    c = _client(fake, refresher=refresher)
    data = c.get("/crm/owners/2026-09")
    assert calls == [1] and data["results"]


def test_secondly_rate_limit_waits_then_retries():
    fake = FakeHubSpot()
    fake.fail_next.append(("/crm/owners", 429, b'{"policyName":"TEN_SECONDLY_ROLLING"}'))
    waits = []
    c = hs_api.HubSpotClient(ACCESS, opener=fake, sleep=waits.append, delay=0, search_delay=0)
    assert c.get("/crm/owners/2026-09")["results"]
    assert waits and waits[0] == 10.0


def test_daily_limit_stops_keeps_data_and_watermark(env):
    env["fake"].fail_next.append(
        ("/tasks/search", 429, b'{"policyName":"DAILY","errorType":"RATE_LIMIT"}')
    )
    with pytest.raises(hs_api.DailyLimitReached):
        _download()
    state = json.loads(hs_api.state_path().read_text())
    assert "contacts" in state["watermarks"] and "deals" in state["watermarks"]
    assert "tasks" not in state["watermarks"] and state["complete"] is False
    assert json.loads((hs_api.raw_dir() / "deals.json").read_text())  # kept
    summary = json.loads(hs_api.summary_path().read_text())
    assert "daily API limit" in summary["stopped"]


def test_search_goes_past_the_10k_window(monkeypatch):
    monkeypatch.setattr(hs_api, "SEARCH_CAP", 4)
    monkeypatch.setattr(hs_api, "SEARCH_PAGE", 2)
    deals = [
        _rec(
            f"x{i}",
            {"hs_lastmodifieddate": f"2026-11-{10 + i:02d}T00:00:00Z", "hubspot_owner_id": "77"},
        )
        for i in range(7)
    ]
    fake = FakeHubSpot(data={"deals": deals})
    found = hs_api.search_objects(_client(fake), "deals", None, "", {})
    assert sorted(r["id"] for r in found) == [f"x{i}" for i in range(7)]
    restarts = [b for o, b in fake.searches if "filterGroups" in b]
    assert restarts  # a second query started from the last modified date seen


def test_detail_budget_leaves_the_rest_for_the_next_run(env):
    stats = _download(max_details=2)
    assert stats["deals_details"] == 2 and stats["tasks_details_left_for_next_run"] == 2
    state = json.loads(hs_api.state_path().read_text())
    assert sorted(state["pending_details"]["tasks"]) == ["t1", "t2"]
    stats2 = _download(max_details=50)
    assert stats2["tasks_details"] >= 2
    state = json.loads(hs_api.state_path().read_text())
    assert all(not v for v in state["pending_details"].values())


def test_refused_batch_read_falls_back_to_single_reads(env):
    env["fake"].fail_next.append(("/contacts/batch/read", 403, b'{"message":"no"}'))
    stats = _download()
    assert stats["contacts_batch_refused"] == 403
    contacts = json.loads((hs_api.raw_dir() / "contacts.json").read_text())
    assert contacts["c3"]["properties"]["email"] == "bo@supplier.example"


def test_refused_search_on_one_object_does_not_stop_the_others(env):
    env["fake"].fail_next.append(("/notes/search", 403, b'{"message":"no access"}'))
    stats = _download()
    assert any("notes: HubSpot refused the search (HTTP 403)" in w for w in stats["warnings"])
    state = json.loads(hs_api.state_path().read_text())
    assert "notes" not in state["watermarks"] and "tasks" in state["watermarks"]
    assert stats["tasks_found"] == 2


def test_helpers():
    assert hs_api.iso("1579514400000") == "2020-01-20T10:00:00+00:00"
    assert hs_api.iso("2019-12-07T16:50:06.678Z") == "2019-12-07T16:50:06+00:00"
    assert hs_api.iso("") == "" and hs_api.iso("not a date") == ""
    assert hs_api.html_to_text("<div>A&nbsp;b</div><br><p>c</p>") == "A b\nc"
    assert hs_api.parse_associations(
        {
            "associations": {
                "contacts": {"results": [{"id": "1"}, {"id": "1"}]},
                "company": {"results": [{"id": 9}]},
            }
        }
    ) == {"contacts": ["1"], "companies": ["9"]}


# --- login ------------------------------------------------------------------------------


def test_authorize_url_asks_only_read_scopes():
    url = hs_api.authorize_url(CID, hs_api.redirect_uri(8723), "st")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://app.hubspot.com/oauth/authorize?")
    assert q["redirect_uri"] == "http://localhost:8723/oauth-callback" and q["state"] == "st"
    scopes = q["scope"].split() + q["optional_scope"].split()
    assert all(s == "oauth" or s.endswith(".read") for s in scopes)


def test_install_url_from_the_app_page():
    red = "http://localhost:8723/oauth-callback"
    given = f"https://app.hubspot.com/oauth/authorize?client_id=x&scope=oauth&redirect_uri={red}"
    q = parse_qs(urlparse(AUTH.install_url_from(given, red, "S1")).query)
    assert q["state"] == ["S1"] and q["client_id"] == ["x"]
    with pytest.raises(hs_api.HubSpotError, match="listens on"):
        AUTH.install_url_from(given.replace("8723", "3000"), red, "S1")
    with pytest.raises(hs_api.HubSpotError, match="hubspot.com"):
        AUTH.install_url_from("https://hubspot.example/oauth", red, "S1")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_wait_for_code_checks_the_state():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)

    def hit():
        time.sleep(0.2)
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/oauth-callback?code=C1&state=WRONG", timeout=5
            )
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=hit, daemon=True).start()
    with pytest.raises(hs_api.HubSpotError, match="did not match"):
        AUTH.wait_for_code(server, "RIGHT", timeout=10)


def test_login_stores_the_refresh_token(env, monkeypatch, capsys):
    env["stored"].pop(("sbk-hubspot", "default"))
    monkeypatch.setattr(
        AUTH, "wait_for_code", lambda server, state: (server.server_close(), "CODE")[1]
    )
    monkeypatch.setattr(AUTH.webbrowser, "open", lambda url: True)
    rc = AUTH.main(["--port", str(_free_port())])
    assert rc == 0
    assert env["stored"][("sbk-hubspot", "default")] == REFRESH
    exchange = [p for m, u, p in env["fake"].calls if u.endswith("/oauth/v3/token")][0]
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "CODE"
    assert "user-level app" in capsys.readouterr().out


def test_login_refuses_an_account_level_app(env, monkeypatch, capsys):
    env["stored"].pop(("sbk-hubspot", "default"))
    env["fake"].user_level = False
    monkeypatch.setattr(
        AUTH, "wait_for_code", lambda server, state: (server.server_close(), "CODE")[1]
    )
    monkeypatch.setattr(AUTH.webbrowser, "open", lambda url: True)
    assert AUTH.main(["--port", str(_free_port())]) == 1
    assert ("sbk-hubspot", "default") not in env["stored"]
    err = [x for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert len(err) == 1 and "account-level" in err[0]


# --- command line -------------------------------------------------------------------------


def _run(script, *args, env_extra=None, tmp=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("HUBSPOT_")}
    cfg = tmp / "owner-only.json"
    cfg.write_text(json.dumps({"owner": "Alex Demo", "own_emails": [ME_EMAIL]}), encoding="utf-8")
    e.update({"SBK_CONTAINERIZED": "1", "SBK_DATA_ROOT": str(tmp), "SBK_CONFIG": str(cfg)})
    e.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(HS / script), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=str(tmp),
        timeout=120,
    )


@pytest.mark.parametrize("script", ["hs-l0-auth.py", "hs-l0-download.py", "hs-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    r = _run(script, "--help", tmp=tmp_path)
    assert r.returncode == 0 and "usage" in r.stdout and "Traceback" not in r.stderr


@pytest.mark.parametrize("script", ["hs-l0-auth.py", "hs-l0-download.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    r = _run(script, tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("HubSpot: no app credentials")


def test_download_with_app_but_no_login(tmp_path):
    r = _run(
        "hs-l0-download.py",
        tmp=tmp_path,
        env_extra={"HUBSPOT_CLIENT_ID": CID, "HUBSPOT_CLIENT_SECRET": SECRET},
    )
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and len(lines) == 1 and "hs-l0-auth.py" in lines[0]


def test_l1_without_data_one_clear_line(tmp_path):
    r = _run("hs-l1-enrich.py", tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("HubSpot: nothing downloaded")


def test_project_template_is_user_level_and_read_only():
    meta = json.loads((HS / "hubspot-project" / "src" / "app" / "app-hsmeta.json").read_text())
    cfg = meta["config"]
    assert cfg["isUserLevel"] is True and cfg["distribution"] == "private"
    assert cfg["auth"]["type"] == "oauth"
    assert cfg["auth"]["redirectUrls"] == [hs_api.redirect_uri(hs_api.DEFAULT_REDIRECT_PORT)]
    assert tuple(cfg["auth"]["requiredScopes"]) == hs_api.REQUIRED_SCOPES
    assert tuple(cfg["auth"]["optionalScopes"]) == hs_api.OPTIONAL_SCOPES
    proj = json.loads((HS / "hubspot-project" / "hsproject.json").read_text())
    assert proj["platformVersion"] == "2026.09"
