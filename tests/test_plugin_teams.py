"""Microsoft Teams plugin: mocked Graph and identity platform only.

No real account, no real HTTP to Microsoft, no real Keychain. The only socket opened is the
microsoft365 loopback sign-in server on 127.0.0.1, driven by the test itself. The generic
intake loader (tools/cross-source/plugin_intake.py) reads the L1 output.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
TM = ROOT / "tools" / "teams"
sys.path.insert(0, str(TM))

import plugin_intake  # noqa: E402
import tm_graph as tg  # noqa: E402

import sbk_config  # noqa: E402

mg = tg.mg


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, TM / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("tm_l0_download", "tm-l0-download.py")
L1 = _load("tm_l1_enrich", "tm-l1-enrich.py")
AUTH = _load("tm_l0_auth", "tm-l0-auth.py")

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CID = "11111111-2222-3333-4444-555555555555"
ME = {
    "id": "U-ME",
    "displayName": "Jordan Blake",
    "mail": "jordan@contoso.example",
    "userPrincipalName": "jordan@contoso.example",
}


def _member(uid, name, email):
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "userId": uid,
        "displayName": name,
        "email": email,
        "roles": ["owner"],
    }


MEMBER_ME = _member("U-ME", "Jordan Blake", "jordan@contoso.example")
MIA = _member("U-MIA", "Mia Conti", "mia@fabrikam.example")
LEE = _member("U-LEE", "Lee Park", "lee@fabrikam.example")


def _msg(mid, when, uid, name, text, modified=None, **extra):
    m = {
        "id": mid,
        "messageType": "message",
        "createdDateTime": when,
        "lastModifiedDateTime": modified or when,
        "deletedDateTime": None,
        "from": {"application": None, "device": None, "user": {"id": uid, "displayName": name}},
        "body": {"contentType": "text", "content": text},
        "attachments": [],
    }
    m.update(extra)
    return m


class FakeMicrosoft:
    """Answers the identity platform and the Graph endpoints the plugin calls."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.token_forms: list[dict] = []
        self.rotation = 0
        self.round = 1
        self.forbid_chat: str | None = None
        self.refuse_refresh = False
        self.refuse_chats = False
        self.big_group_members = [
            _member(f"U-{i}", f"Person {i}", f"p{i}@fabrikam.example") for i in range(30)
        ]

    def chats(self):
        return [
            {
                "id": "19:one@unq.gbl.spaces",
                "chatType": "oneOnOne",
                "topic": None,
                "webUrl": "https://teams.example/l/chat/one",
                "members": [MEMBER_ME, MIA],
            },
            {
                "id": "19:grp@thread.v2",
                "chatType": "group",
                "topic": "Launch",
                "webUrl": "https://teams.example/l/chat/grp",
                "members": [MEMBER_ME, MIA, LEE],
            },
            {
                "id": "19:big@thread.v2",
                "chatType": "group",
                "topic": "All hands",
                "webUrl": "https://teams.example/l/chat/big",
                "members": [MEMBER_ME] + self.big_group_members[:24],  # capped at 25
            },
            {
                "id": "19:meet@thread.v2",
                "chatType": "meeting",
                "topic": "Weekly",
                "webUrl": "https://teams.example/l/chat/meet",
                "members": [MEMBER_ME, LEE],
            },
        ]

    def messages(self, chat_id):
        if self.round == 1:
            data = {
                "19:one@unq.gbl.spaces": [
                    _msg("3", "2026-11-18T16:00:00.000Z", "U-MIA", "Mia Conti", "See you"),
                    _msg("2", "2026-11-18T09:05:00.000Z", "U-ME", "Jordan Blake", "Sure"),
                    _msg("1", "2026-11-18T09:00:00.000Z", "U-MIA", "Mia Conti", "Call today?"),
                    _msg(
                        "0",
                        "2026-11-17T09:00:00.000Z",
                        "U-MIA",
                        "Mia Conti",
                        "",
                        attachments=[{"name": "plan.pdf"}],
                    ),
                ],
                "19:grp@thread.v2": [
                    _msg(
                        "g3",
                        "2026-11-19T10:00:00.000Z",
                        "U-ME",
                        "Jordan Blake",
                        "<p>Only me <b>today</b></p>",
                        body={"contentType": "html", "content": "<p>Only me <b>today</b></p>"},
                    ),
                    _msg("g2", "2026-11-18T10:00:00.000Z", "U-LEE", "Lee Park", "Draft ready"),
                    {
                        "id": "g1",
                        "messageType": "systemEventMessage",
                        "createdDateTime": "2026-11-18T08:00:00.000Z",
                        "lastModifiedDateTime": "2026-11-18T08:00:00.000Z",
                        "from": None,
                        "body": {"contentType": "html", "content": "<systemEventMessage/>"},
                    },
                ],
                "19:big@thread.v2": [],
            }
        else:  # second round: "1" edited, "3" deleted, "4" new
            data = {
                "19:one@unq.gbl.spaces": [
                    _msg("4", "2026-11-20T08:00:00.000Z", "U-MIA", "Mia Conti", "New one"),
                    {
                        **_msg("3", "2026-11-18T16:00:00.000Z", "U-MIA", "Mia Conti", ""),
                        "deletedDateTime": "2026-11-20T07:00:00.000Z",
                        "lastModifiedDateTime": "2026-11-20T07:00:00.000Z",
                    },
                    _msg(
                        "1",
                        "2026-11-18T09:00:00.000Z",
                        "U-MIA",
                        "Mia Conti",
                        "Call today at 3?",
                        modified="2026-11-20T06:00:00.000Z",
                    ),
                ],
            }
        return data.get(chat_id, [])

    # --- transport
    def request(self, method, url, *, headers=None, data=None, params=None):
        headers = headers or {}
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        q.update(params or {})
        self.calls.append((method, url, dict(headers), dict(q)))
        if u.netloc == "login.microsoftonline.com":
            return self._identity(u.path, data or {})
        assert u.netloc == "graph.microsoft.com"
        assert headers.get("Authorization", "").startswith("Bearer AT")
        return self._graph(urllib.parse.unquote(u.path.replace("/v1.0", "", 1)), q)

    def _identity(self, path, form):
        self.token_forms.append(dict(form))
        if path.endswith("/token") and form.get("grant_type") == "refresh_token":
            if self.refuse_refresh:
                return (
                    400,
                    {},
                    {"error": "invalid_grant", "error_description": "AADSTS65001: consent"},
                )
            self.rotation += 1
            return (
                200,
                {},
                {
                    "access_token": f"AT{self.rotation}",
                    "expires_in": 3600,
                    "refresh_token": f"RT{self.rotation}",
                    "scope": "User.Read Chat.Read",
                },
            )
        if path.endswith("/token") and form.get("grant_type") == "authorization_code":
            return (
                200,
                {},
                {
                    "access_token": "AT0",
                    "refresh_token": "RT0",
                    "expires_in": 3600,
                    "scope": " ".join(
                        f"https://graph.microsoft.com/{s}"
                        for s in form["scope"].split()
                        if s != "offline_access"
                    ),
                },
            )
        return 400, {}, {"error": "invalid_request", "error_description": "unexpected"}

    @staticmethod
    def _page(items, nxt=None):
        body = {"value": items}
        if nxt:
            body["@odata.nextLink"] = nxt
        return 200, {}, body

    def _graph(self, path, q):
        if path == "/me":
            return 200, {}, ME
        if path == "/me/chats":
            if self.refuse_chats:
                return 403, {}, {"error": {"code": "Forbidden", "message": "no"}}
            if q.get("$top") == "1":
                return self._page(self.chats()[:1])
            chats = self.chats()
            if q.get("$skiptoken"):  # Graph keeps the first request's options in the token
                return self._page(chats[2:])
            assert q["$expand"] == "members" and int(q["$top"]) <= 50
            return self._page(
                chats[:2], nxt="https://graph.microsoft.com/v1.0/me/chats?$skiptoken=S1"
            )
        parts = path.strip("/").split("/")
        if parts[0] == "chats" and parts[2:] == ["members"]:
            assert parts[1] == "19:big@thread.v2"
            return self._page([MEMBER_ME] + self.big_group_members)
        if parts[0] == "chats" and parts[2:] == ["messages"]:
            chat_id = parts[1]
            if chat_id == self.forbid_chat:
                return 403, {}, {"error": {"code": "Forbidden", "message": "no"}}
            assert q["$orderby"] == "lastModifiedDateTime desc"
            assert q["$filter"].startswith("lastModifiedDateTime gt ")
            assert int(q["$top"]) <= 50
            since = q["$filter"].split(" gt ", 1)[1]
            items = [m for m in self.messages(chat_id) if m["lastModifiedDateTime"] > since]
            if len(items) > 2 and not q.get("$skiptoken"):
                nxt = (
                    f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages?$skiptoken=P2"
                    f"&$orderby={urllib.parse.quote(q['$orderby'])}"
                    f"&$filter={urllib.parse.quote(q['$filter'])}&$top={q['$top']}"
                )
                return self._page(items[:2], nxt=nxt)
            if q.get("$skiptoken"):
                return self._page(items[2:])
            return self._page(items)
        return 404, {}, {"error": {"code": "NotFound", "message": path}}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any socket connection other than the loopback sign-in fails the test."""
    import socket

    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"network call in a test: {address!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temporary data root, no config, a fake Keychain, a stored Teams sign-in."""
    monkeypatch.setattr(tg, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(mg, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(sbk_config, "ENABLED_SOURCES", frozenset())
    monkeypatch.setattr(sbk_config, "DISPLAY_TZ", ZoneInfo("UTC"))
    for k in (
        mg.ENV_CLIENT_ID,
        mg.ENV_TENANT,
        mg.ENV_TOKEN_FILE,
        "SBK_MS365_TOKEN_WORK",
        "SBK_CONTAINERIZED",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(mg.ENV_CLIENT_ID, CID)
    vault: dict = {}
    monkeypatch.setattr(mg, "get_secret", lambda s, a: vault.get((s, a)))
    monkeypatch.setattr(mg, "set_secret", lambda s, a, v: vault.__setitem__((s, a), v))
    vault[(mg.SECRET_SERVICE, "work")] = json.dumps(
        {
            "refresh_token": "RT_START",
            "client_id": CID,
            "tenant": "organizations",
            "scopes": "User.Read Chat.Read",
        }
    )
    return tmp_path, vault


def _run(fake, *argv, now=NOW, sleeps=None):
    args = L0.parse_args(["--account", "work", *argv])
    sleep = (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    return L0.run_one("work", args, http=fake, sleep=sleep, now=now)


# --------------------------------------------------------------------------- scopes and auth


def test_scopes_are_per_user_and_need_no_admin_consent():
    assert tg.TEAMS_SCOPES == ("offline_access", "User.Read", "Chat.Read")
    for s in tg.TEAMS_SCOPES:
        assert ".All" not in s and "Write" not in s and "Channel" not in s
    assert "ChatMember.Read" not in tg.TEAMS_SCOPES  # that one needs admin consent
    union = tg.sign_in_scopes(with_outlook=True)
    assert set(union) == set(tg.TEAMS_SCOPES) | set(mg.SCOPES) and len(union) == len(set(union))
    assert tg.sign_in_scopes(with_outlook=False) == tg.TEAMS_SCOPES


def test_graph_scopes_swaps_and_restores_microsoft365_scopes():
    before = tuple(mg.SCOPES)
    with pytest.raises(RuntimeError), tg.graph_scopes(("x",)):
        assert mg.SCOPES == ("x",)
        raise RuntimeError
    assert tuple(mg.SCOPES) == before


def _login_via_loopback(fake, argv, vault):
    seen = {}

    def opener(url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        seen["scope"] = q["scope"]

        def hit():
            cb = f"{q['redirect_uri']}/?code=C0&state={q['state']}"
            urllib.request.urlopen(cb, timeout=10).read()

        threading.Thread(target=hit, daemon=True).start()

    rc = AUTH.main(argv, http=fake, open_browser=opener, sleep=lambda s: None)
    return rc, seen


def test_auth_adds_chat_read_to_an_existing_outlook_sign_in(env, capsys):
    _tmp, vault = env
    vault[(mg.SECRET_SERVICE, "work")] = json.dumps(
        {
            "refresh_token": "RT_OUTLOOK",
            "client_id": CID,
            "tenant": "organizations",
            "scopes": "User.Read Mail.Read Calendars.Read Contacts.Read",
        }
    )
    fake = FakeMicrosoft()
    rc, seen = _login_via_loopback(fake, ["--account", "work"], vault)
    assert rc == 0
    # an existing microsoft365 sign-in: the union, so both plugins keep working
    assert set(seen["scope"].split()) == set(tg.TEAMS_SCOPES) | set(mg.SCOPES)
    rec = json.loads(vault[(mg.SECRET_SERVICE, "work")])
    assert rec["refresh_token"] == "RT0" and "Chat.Read" in rec["scopes"]
    assert "Chat.Read" in rec["requested_scopes"] and rec["username"] == ME["mail"]
    assert "chats readable" in capsys.readouterr().out
    assert tuple(mg.SCOPES) == (
        "offline_access",
        "User.Read",
        "Mail.Read",
        "Calendars.Read",
        "Contacts.Read",
    )


def test_auth_again_on_a_teams_only_label_stays_teams_only(env):
    # the fixture's stored sign-in has User.Read Chat.Read only: no Mail/Calendars/Contacts
    _tmp, vault = env
    rc, seen = _login_via_loopback(FakeMicrosoft(), ["--account", "work"], vault)
    assert rc == 0 and set(seen["scope"].split()) == set(tg.TEAMS_SCOPES)


def test_auth_seed_without_scopes_keeps_outlook(env):
    _tmp, vault = env
    vault[(mg.SECRET_SERVICE, "work")] = "RT_SEED_ONLY"
    rc, seen = _login_via_loopback(FakeMicrosoft(), ["--account", "work"], vault)
    assert rc == 0 and set(seen["scope"].split()) == set(tg.TEAMS_SCOPES) | set(mg.SCOPES)


def test_auth_teams_only_for_a_new_label(env):
    _tmp, vault = env
    fake = FakeMicrosoft()
    rc, seen = _login_via_loopback(fake, ["--account", "chats"], vault)
    assert rc == 0 and set(seen["scope"].split()) == set(tg.TEAMS_SCOPES)
    assert (mg.SECRET_SERVICE, "chats") in vault


def test_auth_refuses_another_person_on_a_shared_label(env):
    _tmp, vault = env
    stored = {
        "refresh_token": "RT_OUTLOOK",
        "client_id": CID,
        "tenant": "common",
        "scopes": "User.Read Mail.Read",
        "username": "someone.else@personal.example",
    }
    vault[(mg.SECRET_SERVICE, "work")] = json.dumps(stored)
    with pytest.raises(tg.SetupError, match="holds the sign-in of someone.else@personal.example"):
        _login_via_loopback(FakeMicrosoft(), ["--account", "work"], vault)
    assert json.loads(vault[(mg.SECRET_SERVICE, "work")]) == stored  # untouched


def test_auth_same_person_on_a_shared_label_is_stored(env):
    _tmp, vault = env
    vault[(mg.SECRET_SERVICE, "work")] = json.dumps(
        {
            "refresh_token": "RT_OUTLOOK",
            "client_id": CID,
            "tenant": "organizations",
            "scopes": "User.Read Mail.Read",
            "username": ME["mail"].upper(),
        }
    )
    rc, _seen = _login_via_loopback(FakeMicrosoft(), ["--account", "work"], vault)
    assert rc == 0 and json.loads(vault[(mg.SECRET_SERVICE, "work")])["refresh_token"] == "RT0"


def test_auth_refuses_consumers_tenant(env):
    with pytest.raises(tg.SetupError, match="personal Microsoft accounts"):
        AUTH.main(["--account", "work", "--tenant", "consumers"], http=FakeMicrosoft())


def test_auth_check_reports_refused_chats(env):
    fake = FakeMicrosoft()
    fake.refuse_chats = True
    with pytest.raises(tg.SetupError, match="refused the chats"):
        AUTH.main(["--account", "work", "--check"], http=fake, sleep=lambda s: None)


def test_outlook_only_sign_in_is_refused_with_the_teams_command(env):
    _tmp, vault = env
    vault[(mg.SECRET_SERVICE, "work")] = json.dumps(
        {
            "refresh_token": "R",
            "client_id": CID,
            "tenant": "common",
            "scopes": "User.Read Mail.Read",
        }
    )
    with pytest.raises(tg.SetupError, match="tools/teams/tm-l0-auth.py --account work"):
        _run(FakeMicrosoft())


def test_no_sign_in_names_the_teams_command(env):
    _tmp, vault = env
    vault.clear()
    with pytest.raises(tg.SetupError) as ei:
        _run(FakeMicrosoft())
    assert str(ei.value).startswith("teams: no sign-in for 'work'")


def test_refused_refresh_points_to_the_teams_sign_in(env):
    fake = FakeMicrosoft()
    fake.refuse_refresh = True
    with pytest.raises(tg.TokenError) as ei:
        _run(fake)
    text = str(ei.value)
    assert text.startswith("teams:") and "invalid_grant" in text
    assert "tools/teams/tm-l0-auth.py" in text and "ms-l0-auth" not in text


def test_refresh_asks_only_teams_scopes_and_stores_the_rotated_token(env):
    _tmp, vault = env
    fake = FakeMicrosoft()
    _run(fake)
    forms = [f for f in fake.token_forms if f.get("grant_type") == "refresh_token"]
    assert forms and set(forms[0]["scope"].split()) == set(tg.TEAMS_SCOPES)
    rec = json.loads(vault[(mg.SECRET_SERVICE, "work")])
    assert rec["refresh_token"] == "RT1" and "Chat.Read" in rec["scopes"]


def test_pacing_is_one_request_every_1_25_seconds(env):
    sleeps: list[float] = []
    fake = FakeMicrosoft()
    tp = tg.TeamsTokenProvider("work", fake)
    g = tg.PacedGraph(tp, fake, sleep=sleeps.append, clock=lambda: 100.0)
    g.get("/me")
    g.get("/me")
    assert tg.MIN_INTERVAL_S in sleeps


def test_bearer_token_never_leaves_graph(env):
    fake = FakeMicrosoft()
    g = tg.PacedGraph(tg.TeamsTokenProvider("work", fake), fake, sleep=lambda s: None)
    with pytest.raises(tg.GraphError) as ei:
        g.get("https://collector.example/chats/x/messages")
    assert ei.value.code == "untrusted_link"
    assert not any("collector.example" in c[1] for c in fake.calls)


# --------------------------------------------------------------------------- download


def test_first_run_reads_chats_members_and_messages(env):
    tmp, _vault = env
    fake = FakeMicrosoft()
    s = _run(fake)
    assert s["chats_listed"] == 4 and s["chats_not_included"] == 1  # the meeting chat
    assert s["chats_read"] == 3 and s["members_refetched"] == 1
    assert s["messages_new_or_changed"] == 7 and s["errors"] == []  # the system event is kept raw
    raw = tmp / "teams" / "raw" / "work"
    chats = {c["id"]: c for c in json.loads((raw / "chats.json").read_text())}
    assert len(chats["19:big@thread.v2"]["members"]) == 31
    one = json.loads(
        (raw / "messages" / f"{tg.chat_key('19:one@unq.gbl.spaces')}.json").read_text()
    )
    assert set(one["messages"]) == {"0", "1", "2", "3"}
    assert one["messages"]["0"]["text"] == "[attachment: plan.pdf]"
    grp = json.loads((raw / "messages" / f"{tg.chat_key('19:grp@thread.v2')}.json").read_text())
    assert grp["messages"]["g3"]["text"] == "Only me today"
    state = json.loads((raw / "state.json").read_text())
    assert state["chats"]["19:one@unq.gbl.spaces"]["hwm"] == "2026-11-18T16:00:00.000Z"
    summary = json.loads((raw / "download-summary.json").read_text())
    assert summary["source"] == "teams" and summary["requests"] > 0
    msg_calls = [c for c in fake.calls if c[1].endswith("/messages") and "skiptoken" not in c[1]]
    assert all(
        c[3]["$filter"] == "lastModifiedDateTime gt 2025-11-20T12:00:00.000Z" for c in msg_calls
    )
    assert not any("/channels" in c[1] or "getAllMessages" in c[1] for c in fake.calls)


def test_second_run_is_incremental_and_applies_edits_and_deletes(env):
    tmp, _vault = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.round = 2
    fake.calls.clear()
    s = _run(fake, now=datetime(2026, 11, 21, 12, 0, tzinfo=UTC))
    one_call = [
        c for c in fake.calls if "19:one" in c[1] and c[1].split("?")[0].endswith("/messages")
    ][0]
    # high-water mark 16:00 minus the 10-minute overlap
    assert one_call[3]["$filter"] == "lastModifiedDateTime gt 2026-11-18T15:50:00.000Z"
    assert s["messages_new_or_changed"] == 3 and s["messages_deleted"] == 1
    raw = tmp / "teams" / "raw" / "work"
    one = json.loads(
        (raw / "messages" / f"{tg.chat_key('19:one@unq.gbl.spaces')}.json").read_text()
    )
    assert one["messages"]["1"]["text"] == "Call today at 3?"
    assert one["messages"]["3"]["deleted"] is True and one["messages"]["3"]["text"] == ""
    assert "4" in one["messages"] and "0" in one["messages"]


def test_meeting_chats_only_when_asked(env):
    fake = FakeMicrosoft()
    s = _run(fake, "--include-meeting-chats")
    assert s["chats_not_included"] == 0 and s["chats_read"] == 4


def test_since_keeps_its_own_offset(env):
    args = L0.parse_args(["--account", "work", "--since", "2026-11-01T10:00:00+02:00"])
    got = L0.start_for("x", {"chats": {}}, args, NOW)
    assert got == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    args = L0.parse_args(["--account", "work", "--since", "2026-11-01"])
    assert L0.start_for("x", {"chats": {}}, args, NOW) == datetime(2026, 11, 1, tzinfo=UTC)


def test_all_goes_on_when_graph_refuses_one_account(env, monkeypatch, capsys):
    _tmp, vault = env
    vault[(mg.SECRET_SERVICE, "blocked")] = vault[(mg.SECRET_SERVICE, "work")]
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"teams": {"accounts": ["blocked", "work"]}})

    class FirstChatsRefused(FakeMicrosoft):
        def _graph(self, path, q):
            if path == "/me/chats" and not getattr(self, "_refused", False):
                self._refused = True
                return 403, {}, {"error": {"code": "Forbidden", "message": "blocked"}}
            return super()._graph(path, q)

    rc = L0.main(["--all"], http=FirstChatsRefused(), sleep=lambda s: None)
    out, err = capsys.readouterr()
    assert rc == 1
    assert err.strip().splitlines() == ["teams/blocked: HTTP 403 Forbidden: blocked"]
    assert "teams/work: 3 chats read" in out
    assert (_tmp / "teams" / "raw" / "work" / "download-summary.json").is_file()


def test_one_refused_chat_does_not_stop_the_others(env):
    fake = FakeMicrosoft()
    fake.forbid_chat = "19:grp@thread.v2"
    s = _run(fake)
    assert s["chats_read"] == 2 and s["chats_skipped"] == ["Launch: HTTP 403 Forbidden"]
    assert s["errors"] == []


# --------------------------------------------------------------------------- L1 and intake


def test_l1_writes_the_intake_contract(env, monkeypatch):
    tmp, _vault = env
    _run(FakeMicrosoft())
    contacts, interactions, stats = L1.build_rows()
    L1.write_outputs(contacts, interactions)
    cdf = pd.read_parquet(tmp / "teams" / "processed" / "plugin-contacts.parquet")
    idf = pd.read_parquet(tmp / "teams" / "processed" / "plugin-interactions.parquet")
    assert list(cdf.columns) == tg.CONTACT_COLUMNS
    assert list(idf.columns) == tg.INTERACTION_COLUMNS
    assert "jordan@contoso.example" not in set(cdf["email"])  # you are left out
    mia = cdf[cdf["email"] == "mia@fabrikam.example"].iloc[0]
    # two 1:1 days, plus the group day where only you wrote (members are the participants)
    assert mia["name"] == "Mia Conti" and mia["interactions"] == 3
    assert mia["first_seen"].startswith("2026-11-17T09:00") and mia["last_seen"].startswith(
        "2026-11-19T10:00"
    )
    assert len(cdf) == 32  # Mia, Lee and the 30 members of the big group
    assert set(idf["kind"]) == {"message"} and set(idf["status"]) == {"done"}
    one = idf[idf["title"] == "Teams chat with Mia Conti"].sort_values("ts")
    assert len(one) == 2
    day = one.iloc[1]
    assert (
        day["owner_role"] == "author" and day["participants"] == "Mia Conti <mia@fabrikam.example>"
    )
    assert day["text"].splitlines()[0] == "09:00 Mia Conti: Call today?"
    assert "09:05 Jordan Blake: Sure" in day["text"]
    grp = idf[idf["title"] == "Teams chat: Launch"].sort_values("ts")
    assert list(grp["owner_role"]) == ["attendee", "author"]
    assert grp.iloc[0]["participants"] == "Lee Park <lee@fabrikam.example>"
    # only you wrote that day: the other members are the participants
    assert set(grp.iloc[1]["participants"].split("|||")) == {
        "Mia Conti <mia@fabrikam.example>",
        "Lee Park <lee@fabrikam.example>",
    }
    assert stats["chat_days"] == 4  # system events are not a day of messages

    people = plugin_intake.load_contacts(tmp)
    events = plugin_intake.load_interactions(tmp)
    assert people is not None and events is not None
    assert len(people) == 32 and set(people["source"]) == {"teams"}
    assert len(events) == 4 and not any(plugin_intake.is_commitment(r) for r in events.itertuples())


def test_l1_day_follows_the_configured_timezone(env, monkeypatch):
    _run(FakeMicrosoft())
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"teams": {"timezone": "Asia/Tokyo"}})
    _c, interactions, _s = L1.build_rows()
    one = [r for r in interactions if r["title"] == "Teams chat with Mia Conti"]
    # in Tokyo 18 Nov 16:00 UTC is already 19 Nov: three days instead of two
    assert len(one) == 3 and one[-1]["text"].startswith("01:00 Mia Conti: See you")


def test_l1_text_is_capped(env, monkeypatch):
    _run(FakeMicrosoft())
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"teams": {"text_max_chars": 30}})
    _c, interactions, _s = L1.build_rows()
    day = [r for r in interactions if r["title"] == "Teams chat with Mia Conti"][1]
    assert day["text"].endswith("more messages]") and len(day["text"]) < 80


# --------------------------------------------------------------------------- CLI


def _kernel_env(tmp: Path) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "MS365"))}
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    e.update(
        SBK_DATA_ROOT=str(tmp),
        SBK_CONTAINERIZED="1",
        SBK_CONFIG=str(cfg),
        PYTHONPATH=os.pathsep.join([str(ROOT / "tools"), str(ROOT / "tools" / "cross-source")]),
    )
    return e


@pytest.mark.parametrize("script", ["tm-l0-auth.py", "tm-l0-download.py", "tm-l1-enrich.py"])
def test_cli_help_and_no_credentials(tmp_path, script):
    env = _kernel_env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(TM / script), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and "Traceback" not in r.stderr and "usage" in r.stdout
    argv = [sys.executable, str(TM / script)] + (["--check"] if "auth" in script else [])
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode in (1, 2) and "Traceback" not in r.stderr
    lines = [ln for ln in r.stderr.strip().splitlines() if ln]
    assert len(lines) == 1 and lines[0].startswith("teams:")


def test_auth_without_client_id_is_one_line(tmp_path):
    r = subprocess.run(
        [sys.executable, str(TM / "tm-l0-auth.py")],
        env=_kernel_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert r.stderr.strip().splitlines() == [r.stderr.strip()] and "SBK_MS365_CLIENT_ID" in r.stderr
