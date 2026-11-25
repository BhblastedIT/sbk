"""Microsoft 365 plugin: mocked Graph and identity platform only.

No real account, no real HTTP to Microsoft, no real Keychain. The only socket opened is the
plugin's own loopback sign-in server on 127.0.0.1, driven by the test itself. The kernel
readers (email, calendar and contacts L1) run in subprocesses against a temporary data root.
"""

from __future__ import annotations

import base64
import hashlib
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
MS = ROOT / "tools" / "microsoft365"
sys.path.insert(0, str(MS))

import ms_graph as mg  # noqa: E402
import ms_slots as slots  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, MS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("ms_l0_download", "ms-l0-download.py")
AUTH = _load("ms_l0_auth", "ms-l0-auth.py")

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
ME = {
    "displayName": "Jordan Blake",
    "mail": "jordan@contoso.example",
    "userPrincipalName": "jordan@contoso.example",
    "id": "U1",
}


def _msg(
    mid,
    folder,
    subject,
    when,
    frm="mia@fabrikam.example",
    to="jordan@contoso.example",
    headers=None,
    **extra,
):
    m = {
        "id": mid,
        "conversationId": f"C-{mid}",
        "receivedDateTime": when,
        "sentDateTime": when,
        "from": {"emailAddress": {"name": "Mia Conti", "address": frm}},
        "toRecipients": [{"emailAddress": {"name": "Jordan Blake", "address": to}}],
        "ccRecipients": [],
        "bccRecipients": [],
        "subject": subject,
        "body": {"contentType": "text", "content": f"Body of {subject}"},
        "bodyPreview": f"Body of {subject}",
        "isRead": True,
        "isDraft": False,
        "categories": [],
        "internetMessageId": f"<{mid}@fabrikam.example>",
        "hasAttachments": False,
        "webLink": f"https://outlook.example/{mid}",
        "parentFolderId": folder,
    }
    if headers is not None:
        m["internetMessageHeaders"] = headers
    m.update(extra)
    return m


class FakeMicrosoft:
    """Answers the identity platform and the Graph endpoints the plugin calls."""

    WELL_KNOWN = {
        "inbox": "F_INBOX",
        "sentitems": "F_SENT",
        "drafts": "F_DRAFTS",
        "archive": "F_ARCH",
        "junkemail": "F_JUNK",
        "deleteditems": "F_DEL",
    }

    def __init__(self):
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.token_forms: list[dict] = []
        self.rotation = 0
        self.round = 1
        self.fail_headers_in_delta = False
        self.reset_folder: str | None = None
        self.forbid: set[str] = set()
        self.throttle_once: set[str] = set()

    # --- data
    def folders_top(self):
        return [
            {"id": "F_INBOX", "displayName": "Inbox", "childFolderCount": 1},
            {"id": "F_SENT", "displayName": "Sent Items", "childFolderCount": 0},
            {"id": "F_DRAFTS", "displayName": "Drafts", "childFolderCount": 0},
            {"id": "F_ARCH", "displayName": "Archive", "childFolderCount": 0},
            {"id": "F_JUNK", "displayName": "Junk Email", "childFolderCount": 0},
            {"id": "F_DEL", "displayName": "Deleted Items", "childFolderCount": 0},
            {"id": "F_PROJ", "displayName": "Projects, 2026", "childFolderCount": 0},
        ]

    def delta_items(self, folder: str, headers: bool):
        h = (
            [
                {"name": "In-Reply-To", "value": "<x@fabrikam.example>"},
                {"name": "List-Unsubscribe", "value": "<mailto:u@news.example>"},
            ]
            if headers
            else None
        )
        if self.round == 1:
            data = {
                "F_INBOX": [
                    _msg("M1", "F_INBOX", "Kickoff", "2026-11-10T09:00:00Z", headers=h),
                    _msg(
                        "M2",
                        "F_INBOX",
                        "Budget",
                        "2026-11-11T09:00:00Z",
                        headers=h,
                        isRead=False,
                        categories=["Blue category"],
                    ),
                ],
                "F_SENT": [
                    _msg(
                        "M3",
                        "F_SENT",
                        "Re: Kickoff",
                        "2026-11-10T10:00:00Z",
                        frm="jordan@contoso.example",
                        to="mia@fabrikam.example",
                    )
                ],
                "F_CLIENTS": [
                    _msg(
                        "M4",
                        "F_CLIENTS",
                        "Offer",
                        "2026-11-12T09:00:00Z",
                        body={
                            "contentType": "html",
                            "content": "<p>Hello<br>World</p><style>x{}</style>",
                        },
                    )
                ],
                "F_PROJ": [_msg("M5", "F_PROJ", "Plan", "2026-11-13T09:00:00Z")],
            }
        else:  # second round: M2 moved to Projects, M4 deleted, M6 new in inbox
            data = {
                "F_INBOX": [
                    {"id": "M2", "@removed": {"reason": "deleted"}},
                    _msg("M6", "F_INBOX", "New", "2026-11-19T09:00:00Z"),
                ],
                "F_PROJ": [_msg("M2", "F_PROJ", "Budget", "2026-11-11T09:00:00Z")],
                "F_CLIENTS": [{"id": "M4", "@removed": {"reason": "deleted"}}],
            }
        return data.get(folder, [])

    def events(self, cal):
        if cal == "CAL1":
            return [
                {
                    "id": "E1",
                    "subject": "Weekly sync",
                    "isAllDay": False,
                    "start": {"dateTime": "2026-11-18T08:30:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-11-18T09:00:00.0000000", "timeZone": "UTC"},
                    "organizer": {"emailAddress": {"address": "jordan@contoso.example"}},
                    "attendees": [
                        {
                            "emailAddress": {"address": "mia@fabrikam.example"},
                            "status": {"response": "accepted"},
                        },
                        {
                            "emailAddress": {"address": "lee@fabrikam.example"},
                            "status": {"response": "tentativelyAccepted"},
                        },
                    ],
                    "isOrganizer": True,
                    "responseStatus": {"response": "organizer"},
                    "onlineMeeting": {"joinUrl": "https://teams.example/j/1"},
                    "showAs": "busy",
                    "sensitivity": "normal",
                    "isCancelled": False,
                    "lastModifiedDateTime": "2026-11-01T00:00:00Z",
                    "webLink": "https://o.example/E1",
                },
                {
                    "id": "E2",
                    "subject": "Holiday",
                    "isAllDay": True,
                    "start": {"dateTime": "2026-11-25T00:00:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-11-26T00:00:00.0000000", "timeZone": "UTC"},
                    "organizer": {"emailAddress": {"address": "jordan@contoso.example"}},
                    "attendees": [],
                    "isCancelled": False,
                    "showAs": "free",
                },
                {
                    "id": "E3",
                    "subject": "Dropped",
                    "isAllDay": False,
                    "start": {"dateTime": "2026-11-19T15:00:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-11-19T16:00:00.0000000", "timeZone": "UTC"},
                    "organizer": {"emailAddress": {"address": "lee@fabrikam.example"}},
                    "attendees": [],
                    "isCancelled": True,
                },
            ]
        return [
            {
                "id": "E9",
                "subject": "Shared",
                "isAllDay": False,
                "start": {"dateTime": "2026-11-18T10:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-11-18T11:00:00", "timeZone": "UTC"},
                "organizer": {"emailAddress": {"address": "boss@fabrikam.example"}},
                "attendees": [],
            }
        ]

    # --- transport
    def request(self, method, url, *, headers=None, data=None, params=None):
        headers = headers or {}
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        q.update(params or {})
        self.calls.append((method, url, dict(headers), dict(q)))
        if u.netloc == "login.microsoftonline.com":
            return self._identity(u.path, data or {})
        assert headers.get("Authorization", "").startswith("Bearer AT")
        path = u.path.replace("/v1.0", "", 1)
        key = path.split("/")[2] if path.count("/") >= 2 else path
        if key in self.throttle_once:
            self.throttle_once.discard(key)
            return 429, {"Retry-After": "3"}, {"error": {"code": "TooManyRequests"}}
        if any(path.startswith(f) for f in self.forbid):
            return 403, {}, {"error": {"code": "ErrorAccessDenied", "message": "no"}}
        return self._graph(path, q, headers)

    def _identity(self, path, form):
        self.token_forms.append(dict(form))
        if path.endswith("/token") and form.get("grant_type") == "refresh_token":
            self.rotation += 1
            return (
                200,
                {},
                {
                    "access_token": f"AT{self.rotation}",
                    "expires_in": 3600,
                    "refresh_token": f"RT{self.rotation}",
                    "scope": "User.Read Mail.Read Calendars.Read Contacts.Read",
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
                    "scope": "https://graph.microsoft.com/User.Read "
                    "https://graph.microsoft.com/Mail.Read",
                },
            )
        return 400, {}, {"error": "invalid_request", "error_description": "unexpected"}

    def _page(self, items, nxt=None, delta=None):
        body = {"value": items}
        if nxt:
            body["@odata.nextLink"] = nxt
        if delta:
            body["@odata.deltaLink"] = delta
        return 200, {}, body

    def _graph(self, path, q, headers):
        G = mg.GRAPH_BASE
        if path == "/me":
            return 200, {}, ME
        parts = path.strip("/").split("/")
        if parts[:2] == ["me", "mailFolders"]:
            if len(parts) == 2:
                return self._page(self.folders_top())
            if len(parts) == 3:
                if parts[2] in self.WELL_KNOWN:
                    return 200, {}, {"id": self.WELL_KNOWN[parts[2]]}
                return 404, {}, {"error": {"code": "ErrorFolderNotFound"}}
            fid = parts[2]
            if parts[3] == "childFolders":
                return self._page(
                    [{"id": "F_CLIENTS", "displayName": "Clients", "childFolderCount": 0}]
                    if fid == "F_INBOX"
                    else []
                )
            if parts[3:] == ["messages", "delta"]:
                tok = q.get("$deltatoken")
                if tok:
                    if self.reset_folder == fid:
                        self.reset_folder = None
                        return 410, {}, {"error": {"code": "syncStateNotFound"}}
                    items = self.delta_items(fid, headers=False)
                    return self._page(
                        items, delta=f"{G}/me/mailFolders/{fid}/messages/delta?$deltatoken=D2{fid}"
                    )
                sel = q.get("$select", "")
                assert "receivedDateTime ge " in q.get("$filter", "")
                if "internetMessageHeaders" in sel and self.fail_headers_in_delta:
                    return 400, {}, {"error": {"code": "ErrorInvalidProperty", "message": "x"}}
                items = self.delta_items(fid, headers="internetMessageHeaders" in sel)
                if q.get("$skiptoken"):
                    return self._page(
                        items[1:],
                        delta=f"{G}/me/mailFolders/{fid}/messages/delta?$deltatoken=D1{fid}",
                    )
                if len(items) > 1:
                    return self._page(
                        items[:1],
                        nxt=f"{G}/me/mailFolders/{fid}/messages/delta?$skiptoken=S{fid}&$select={urllib.parse.quote(sel)}&$filter={urllib.parse.quote(q['$filter'])}",
                    )
                return self._page(
                    items, delta=f"{G}/me/mailFolders/{fid}/messages/delta?$deltatoken=D1{fid}"
                )
        if path == "/me/calendars":
            return self._page(
                [
                    {
                        "id": "CAL1",
                        "name": "Calendar",
                        "isDefaultCalendar": True,
                        "owner": {"address": "jordan@contoso.example"},
                    },
                    {
                        "id": "CAL2",
                        "name": "Team (shared)",
                        "isDefaultCalendar": False,
                        "owner": {"address": "boss@fabrikam.example"},
                    },
                ]
            )
        if parts[:2] == ["me", "calendars"] and parts[3:] == ["calendarView"]:
            assert q["startDateTime"].endswith("Z") and q["endDateTime"].endswith("Z")
            assert 'outlook.timezone="UTC"' in headers.get("Prefer", "")
            return self._page(self.events(parts[2]))
        if path == "/me/contactFolders":
            return self._page([{"id": "CF1", "displayName": "Clients"}])
        if path == "/me/contacts":
            return self._page(
                [
                    {
                        "id": "P1",
                        "displayName": "Mia Conti",
                        "givenName": "Mia",
                        "surname": "Conti",
                        "emailAddresses": [{"address": "mia@fabrikam.example"}],
                        "mobilePhone": "+39 333 000 0001",
                        "businessPhones": [],
                        "homePhones": [],
                        "companyName": "Fabrikam",
                        "jobTitle": "Buyer",
                    }
                ]
            )
        if path == "/me/contactFolders/CF1/contacts":
            return self._page(
                [
                    {
                        "id": "P2",
                        "displayName": "Lee Park",
                        "emailAddresses": [{"address": "lee@fabrikam.example"}],
                        "businessPhones": ["+1 555 0100"],
                    }
                ]
            )
        return 404, {}, {"error": {"code": "NotFound", "message": path}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temporary data root, no config, a fake Keychain, a stored sign-in."""
    monkeypatch.setattr(mg, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(
        mg, "iphone_json_paths", lambda: [tmp_path / "contacts" / "iphone-contacts.json"]
    )
    for k in (
        mg.ENV_CLIENT_ID,
        mg.ENV_TENANT,
        mg.ENV_TOKEN_FILE,
        "SBK_MS365_TOKEN_OUTLOOK",
        "SBK_CONTAINERIZED",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(mg.ENV_CLIENT_ID, "11111111-2222-3333-4444-555555555555")
    vault: dict = {}
    monkeypatch.setattr(mg, "get_secret", lambda s, a: vault.get((s, a)))
    monkeypatch.setattr(mg, "set_secret", lambda s, a, v: vault.__setitem__((s, a), v))
    vault[(mg.SECRET_SERVICE, "outlook")] = json.dumps(
        {
            "refresh_token": "RT_START",
            "client_id": "11111111-2222-3333-4444-555555555555",
            "tenant": "common",
        }
    )
    return tmp_path, vault


def _run(fake, *argv):
    args = L0.parse_args(["--account", "outlook", *argv])
    return L0.run_one("outlook", args, http=fake, sleep=lambda s: None, now=NOW)


# --------------------------------------------------------------------------- scopes and auth


def test_scopes_are_personal_and_need_no_admin_consent():
    assert set(mg.SCOPES) == {
        "offline_access",
        "User.Read",
        "Mail.Read",
        "Calendars.Read",
        "Contacts.Read",
    }
    for s in mg.SCOPES:
        assert ".All" not in s and "Shared" not in s and "Write" not in s


def test_pkce_pair_is_rfc7636_s256():
    verifier, challenge = mg.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expect.decode()


def test_authorize_url_shape():
    url = mg.authorize_url("CID", "common", "http://localhost:5555", "CH", "ST")
    u = urllib.parse.urlparse(url)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    assert u.netloc == "login.microsoftonline.com" and u.path == "/common/oauth2/v2.0/authorize"
    assert q["code_challenge_method"] == "S256" and q["response_type"] == "code"
    assert q["response_mode"] == "query" and "client_secret" not in q
    assert set(q["scope"].split()) == set(mg.SCOPES)


def test_browser_login_over_loopback_exchanges_code():
    fake = FakeMicrosoft()

    def open_browser(url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        redirect = q["redirect_uri"].replace("localhost", "127.0.0.1")

        def hit():
            # a stray request first (favicon), then the real redirect
            urllib.request.urlopen(redirect + "/favicon.ico", timeout=5).read()
            cb = redirect + "?" + urllib.parse.urlencode({"code": "C0DE", "state": q["state"]})
            urllib.request.urlopen(cb, timeout=5).read()

        threading.Thread(target=hit, daemon=True).start()

    tok = mg.browser_login("CID", "consumers", fake, open_browser=open_browser, timeout_s=20)
    assert tok["refresh_token"] == "RT0"
    form = fake.token_forms[-1]
    assert form["grant_type"] == "authorization_code" and form["code"] == "C0DE"
    assert form["code_verifier"] and "client_secret" not in form
    assert form["redirect_uri"].startswith("http://localhost:")


def test_device_code_flow_polls_until_signed_in():
    answers = [
        (
            200,
            {},
            {
                "device_code": "DC",
                "user_code": "ABCD",
                "interval": 1,
                "expires_in": 60,
                "message": "Go to https://microsoft.com/devicelogin and enter ABCD",
            },
        ),
        (400, {}, {"error": "authorization_pending"}),
        (400, {}, {"error": "slow_down"}),
        (200, {}, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}),
    ]

    class H:
        def __init__(self):
            self.forms = []

        def request(self, method, url, **kw):
            self.forms.append((url, kw.get("data")))
            return answers.pop(0)

    h, waits, out = H(), [], []
    tok = mg.device_code_login("CID", "consumers", h, sleep=waits.append, out=out.append)
    assert tok["refresh_token"] == "RT" and waits == [1, 1, 6]
    assert h.forms[0][0].endswith("/consumers/oauth2/v2.0/devicecode")
    assert h.forms[1][1]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert "devicelogin" in out[0]


def test_device_code_flow_stops_on_declined():
    answers = [
        (200, {}, {"device_code": "DC", "interval": 1, "expires_in": 60, "message": "m"}),
        (400, {}, {"error": "authorization_declined", "error_description": "no"}),
    ]

    class H:
        def request(self, *a, **k):
            return answers.pop(0)

    with pytest.raises(mg.TokenError, match="authorization_declined"):
        mg.device_code_login("CID", "common", H(), sleep=lambda s: None, out=lambda m: None)


def test_missing_scopes_reads_prefixed_and_plain():
    assert mg.missing_scopes(
        "https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read"
    ) == ["Calendars.Read", "Contacts.Read"]
    assert mg.missing_scopes("User.Read Mail.Read Calendars.Read Contacts.Read") == []
    assert mg.missing_scopes("") == []


def test_auth_cli_stores_sign_in_and_warns_on_missing_scopes(env, monkeypatch, capsys):
    tmp, vault = env
    vault.clear()
    fake = FakeMicrosoft()
    monkeypatch.setattr(
        mg,
        "browser_login",
        lambda cid, tenant, http: fake._identity(
            "/common/oauth2/v2.0/token", {"grant_type": "authorization_code"}
        )[2],
    )
    assert AUTH.main(["--account", "outlook"], http=fake) == 0
    rec = json.loads(vault[(mg.SECRET_SERVICE, "outlook")])
    assert rec["refresh_token"] == "RT0" and rec["username"] == "jordan@contoso.example"
    out = capsys.readouterr()
    assert "Keychain sbk-microsoft365/outlook" in out.out
    assert "Calendars.Read" in out.err and "RT0" not in out.out + out.err


def test_token_record_places(env, tmp_path, monkeypatch):
    _tmp, vault = env
    vault.clear()
    assert mg.load_token_record("outlook") is None
    monkeypatch.setenv("SBK_MS365_TOKEN_OUTLOOK", "RT_ENV")
    assert mg.load_token_record("outlook") == {"refresh_token": "RT_ENV"}
    tf = tmp_path / "tok" / "ms.json"
    monkeypatch.setenv(mg.ENV_TOKEN_FILE, str(tf))
    assert (
        mg.save_token_record("outlook", {"refresh_token": "RT_FILE"}) == f"file {mg.ENV_TOKEN_FILE}"
    )
    assert oct(tf.stat().st_mode & 0o777) == "0o600"
    assert mg.load_token_record("outlook")["refresh_token"] == "RT_FILE"
    assert vault == {}


def test_keychain_failure_gives_one_clear_line(env, monkeypatch):
    def boom(*a):
        raise RuntimeError("no backend")

    monkeypatch.setattr(mg, "set_secret", boom)
    with pytest.raises(mg.SetupError, match=mg.ENV_TOKEN_FILE):
        mg.save_token_record("outlook", {"refresh_token": "x"})
    monkeypatch.setattr(mg, "get_secret", boom)
    monkeypatch.setenv("SBK_MS365_TOKEN_OUTLOOK", "RT_ENV")
    assert mg.load_token_record("outlook")["refresh_token"] == "RT_ENV"


def test_refresh_rotates_and_stores_new_token(env):
    _tmp, vault = env
    fake = FakeMicrosoft()
    tp = mg.TokenProvider("outlook", fake)
    assert tp.token() == "AT1"
    assert json.loads(vault[(mg.SECRET_SERVICE, "outlook")])["refresh_token"] == "RT1"
    assert tp.token() == "AT1"  # cached
    assert fake.token_forms[0]["refresh_token"] == "RT_START"
    assert "client_secret" not in fake.token_forms[0]


def test_graph_retries_429_with_retry_after_and_refreshes_on_401(env):
    fake = FakeMicrosoft()
    waits = []
    g = mg.Graph(mg.TokenProvider("outlook", fake), fake, sleep=waits.append)

    seq = [
        (429, {"Retry-After": "7"}, {"error": {"code": "TooManyRequests"}}),
        (401, {}, {"error": {"code": "InvalidAuthenticationToken"}}),
        (200, {}, {"ok": 1}),
    ]
    real = fake.request

    def scripted(method, url, **kw):
        if "graph.microsoft.com" in url:
            real(method, url, **kw)  # keeps the bearer assertion
            return seq.pop(0)
        return real(method, url, **kw)

    fake.request = scripted
    assert g.get("/me/anything") == {"ok": 1}
    assert 7 in waits and g.throttled == 1
    assert len(fake.token_forms) == 2  # first token + forced refresh after 401


def test_graph_410_is_delta_reset(env):
    fake = FakeMicrosoft()
    g = mg.Graph(mg.TokenProvider("outlook", fake), fake, sleep=lambda s: None)
    fake.request = lambda m, u, **k: (
        (410, {}, {"error": {"code": "SyncStateNotFound"}})
        if "graph" in u
        else FakeMicrosoft._identity(fake, "/t/token", k.get("data") or {})
    )
    with pytest.raises(mg.DeltaReset):
        g.get("/me/mailFolders/F/messages/delta")


def test_network_error_is_retried_then_one_graph_error(env):
    import requests

    class DeadSession:
        headers: dict = {}

        def request(self, *a, **k):
            raise requests.ConnectionError("offline")

    h = mg.Http()
    h._s = DeadSession()
    status, _h, body = h.request("GET", "https://graph.microsoft.com/v1.0/me")
    assert status == 599 and body["error"] == "network_error"
    waits = []
    tp = mg.TokenProvider("outlook", h)
    with pytest.raises(mg.TokenError, match="network_error"):
        tp.token()
    tp._access, tp._expires = "AT", 1e12
    with pytest.raises(mg.GraphError) as ei:
        mg.Graph(tp, h, sleep=waits.append).get("/me")
    assert ei.value.code == "network_error" and len(waits) >= mg.MAX_RETRIES


# --------------------------------------------------------------------------- slots


def test_message_row_matches_kernel_columns():
    row = slots.message_row(
        _msg(
            "M1",
            "F_INBOX",
            "Hi",
            "2026-11-10T09:00:00Z",
            headers=[{"name": "List-Id", "value": "<l.example>"}],
            isRead=False,
            categories=["Red"],
        ),
        "F_INBOX",
        "INBOX",
    )
    gmail_cols = [
        "id",
        "thread_id",
        "date",
        "from_addr",
        "to_addr",
        "cc",
        "bcc",
        "subject",
        "body_text",
        "body_truncated",
        "labels",
        "message_id",
        "in_reply_to",
        "snippet",
        "has_attachments",
        "attachment_count",
        "attachments_json",
        "list_unsubscribe",
        "list_id",
        "precedence",
        "auto_submitted",
    ]
    assert all(c in row for c in gmail_cols)
    assert row["from_addr"] == '"Mia Conti" <mia@fabrikam.example>'
    assert row["labels"] == "INBOX,UNREAD,Red" and row["list_id"] == "<l.example>"
    assert str(row["date"].tz) == "UTC"


def test_html_body_becomes_text():
    assert (
        slots.body_text(
            {"contentType": "html", "content": "<p>Hi<br>there</p><script>x()</script>"}
        )
        == "Hi\nthere"
    )


def test_event_times_follow_local_zone_and_all_day_dates():
    tz = ZoneInfo("Europe/Rome")
    timed = slots.event_when(
        {"dateTime": "2026-11-18T23:30:00.0000000", "timeZone": "UTC"}, False, tz
    )
    assert timed == "2026-11-19T00:30:00+01:00"
    assert (
        slots.event_when({"dateTime": "2026-11-25T00:00:00", "timeZone": "UTC"}, True, tz)
        == "2026-11-25"
    )
    assert (
        slots.event_when({"dateTime": "2026-11-24T23:00:00", "timeZone": "UTC"}, True, tz)
        == "2026-11-25"
    )


def test_contacts_merge_keeps_other_rows_and_never_writes_nan():
    other = pd.DataFrame(
        [{"full_name": "Ann Example", "primary_email": "ann@example.example", "source": "carddav"}]
    )
    merged = slots.merge_contacts(
        other, [slots.contact_row({"id": "P1", "displayName": "Bo Example"}, "x")], "x"
    )
    assert set(merged["source"]) == {"carddav", "microsoft365:x"}
    assert not merged.isna().any().any()
    assert str(merged.loc[0, "title"]) == ""


# --------------------------------------------------------------------------- end to end (mocked)


def test_first_run_fills_the_three_slots(env):
    tmp, vault = env
    fake = FakeMicrosoft()
    s = _run(fake)
    assert s["errors"] == [] and s["account"] == "jordan@contoso.example"

    msgs = pd.read_parquet(tmp / "emails" / "outlook" / "messages.parquet")
    assert set(msgs["id"]) == {"M1", "M2", "M3", "M4", "M5"}  # junk and deleted never read
    by = msgs.set_index("id")
    assert by.loc["M3", "labels"].startswith("SENT")
    assert by.loc["M5", "labels"] == "Projects  2026"  # comma removed from a folder name
    assert by.loc["M4", "body_text"] == "Hello\nWorld"
    assert by.loc["M1", "in_reply_to"] == "<x@fabrikam.example>"
    assert by.loc["M1", "list_unsubscribe"] == "<mailto:u@news.example>"
    assert (msgs["source"] == "microsoft365").all()

    # first round: $filter on receivedDateTime, ImmutableId and text bodies asked for
    delta_calls = [c for c in fake.calls if "/messages/delta" in c[1]]
    assert all('IdType="ImmutableId"' in c[2].get("Prefer", "") for c in delta_calls)
    assert any(
        "receivedDateTime ge 2025-11-20T00:00:00Z" in c[3].get("$filter", "") for c in delta_calls
    )
    assert not any("/F_JUNK/" in c[1] or "/F_DEL/" in c[1] for c in delta_calls)

    ev = pd.read_parquet(tmp / "calendars" / "outlook" / "events.parquet")
    assert set(ev["id"]) == {"E1", "E2"}  # shared calendar skipped, cancelled set aside
    e1 = ev.set_index("id").loc["E1"]
    assert e1["start_datetime"] == "2026-11-18T08:30:00+00:00"  # SBK_DISPLAY_TZ default UTC
    assert json.loads(e1["attendees"]) == [
        {"email": "mia@fabrikam.example", "status": "accepted"},
        {"email": "lee@fabrikam.example", "status": "tentative"},
    ]
    assert e1["organizer_email"] == "jordan@contoso.example" and e1["calendar_name"] == "Calendar"
    assert e1["conference_url"] == "https://teams.example/j/1" and e1["organizer_self"] == "1"
    cancelled = pd.read_parquet(tmp / "calendars" / "outlook" / "cancellati.parquet")
    assert list(cancelled["id"]) == ["E3"]

    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert set(ct["full_name"]) == {"Mia Conti", "Lee Park"}
    mia = ct.set_index("full_name").loc["Mia Conti"]
    assert mia["primary_phone"] == "+39 333 000 0001" and mia["organization"] == "Fabrikam"

    st = json.loads((tmp / "microsoft365" / "outlook" / "state.json").read_text())
    assert st["mail"]["folders"]["F_INBOX"]["delta_link"].endswith("$deltatoken=D1F_INBOX")
    summary = json.loads((tmp / "microsoft365" / "outlook" / "download-summary.json").read_text())
    assert summary["mail"]["rows_in_slot"] == 5 and summary["contacts"]["contacts_read"] == 2
    # the rotated refresh token was stored, and no token is in the summary or state
    assert json.loads(vault[(mg.SECRET_SERVICE, "outlook")])["refresh_token"].startswith("RT")
    blob = json.dumps(summary) + json.dumps(st)
    assert "RT_START" not in blob and "AT1" not in blob


def test_second_run_applies_moves_and_deletes(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.round = 2
    s = _run(fake)
    msgs = pd.read_parquet(tmp / "emails" / "outlook" / "messages.parquet").set_index("id")
    assert set(msgs.index) == {"M1", "M2", "M3", "M5", "M6"}
    assert msgs.loc["M2", "folder_id"] == "F_PROJ"  # moved, same immutable id
    aside = pd.read_parquet(
        tmp / "microsoft365" / "outlook" / "set-aside" / "messages-removed.parquet"
    )
    assert list(aside["id"]) == ["M4"]
    second = [c for c in fake.calls if "$deltatoken=D1" in c[1]]
    assert second, "the saved deltaLink must be reused"
    assert s["mail"]["removed"] == 2


def test_expired_delta_token_restarts_that_folder(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.round = 2
    fake.reset_folder = "F_SENT"
    s = _run(fake)
    assert s["mail"]["delta_resets"] == 1 and s["errors"] == []
    assert "M3" not in set(pd.read_parquet(tmp / "emails" / "outlook" / "messages.parquet")["id"])


def test_headers_refused_in_delta_falls_back(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    fake.fail_headers_in_delta = True
    s = _run(fake)
    assert s["errors"] == [] and s["mail"]["headers"] is False
    st = json.loads((tmp / "microsoft365" / "outlook" / "state.json").read_text())
    assert st["mail"]["headers_supported"] is False


def test_forbidden_part_is_reported_and_others_still_written(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    fake.forbid = {"/me/contactFolders", "/me/contacts"}
    s = _run(fake)
    assert any(e.startswith("contacts: HTTP 403") for e in s["errors"])
    assert (tmp / "emails" / "outlook" / "messages.parquet").is_file()
    assert not (tmp / "contacts" / "contacts.parquet").exists()


def test_iphone_json_is_kept_when_the_contacts_slot_is_created(env):
    tmp, _ = env
    jp = tmp / "contacts" / "iphone-contacts.json"
    jp.parent.mkdir(parents=True)
    jp.write_text(
        json.dumps(
            {
                "contacts": [
                    {
                        "name": "Sam Example",
                        "phones": ["+1 555 0199"],
                        "emails": ["sam@example.example"],
                    }
                ]
            }
        )
    )
    s = _run(FakeMicrosoft(), "--only", "contacts")
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert "Sam Example" in set(ct["full_name"]) and s["contacts"]["seeded_from_iphone_json"] == 1


def test_refuses_a_gmail_label_and_a_foreign_slot(env):
    tmp, _ = env
    (tmp / "emails").mkdir()
    (tmp / "emails" / "accounts.json").write_text(
        json.dumps({"outlook": {"email": "x@example.example"}})
    )
    with pytest.raises(mg.SetupError, match="Gmail"):
        _run(FakeMicrosoft())
    (tmp / "emails" / "accounts.json").unlink()
    (tmp / "calendars" / "outlook").mkdir(parents=True)
    pd.DataFrame([{"id": "g1", "start_datetime": "2026-01-01"}]).to_parquet(
        tmp / "calendars" / "outlook" / "events.parquet"
    )
    with pytest.raises(mg.SetupError, match="another source"):
        _run(FakeMicrosoft())


def test_contacts_rerun_replaces_only_this_mailbox(env):
    tmp, _ = env
    _run(FakeMicrosoft(), "--only", "contacts")
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    extra = pd.concat(
        [ct, pd.DataFrame([{"full_name": "Kim Example", "source": "carddav"}])], ignore_index=True
    ).fillna("")
    extra.to_parquet(tmp / "contacts" / "contacts.parquet")
    _run(FakeMicrosoft(), "--only", "contacts")
    ct2 = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert len(ct2) == 3 and "Kim Example" in set(ct2["full_name"])


# --------------------------------------------------------------------------- kernel readers


def _kernel_env(tmp: Path) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SBK_", "MS365"))}
    # A config with only the owner fields: no microsoft365 section, and the kernel's
    # "no owner" warning stays out of the one-line error checks.
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


def test_kernel_l1_readers_accept_the_slots(env):
    tmp, _ = env
    _run(FakeMicrosoft())
    code = f"""
import importlib.util, json, sys
sys.argv = ['x']
def load(p):
    spec = importlib.util.spec_from_file_location('m', p); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m
em = load({str(ROOT / "tools/email/em-l1-enrich.py")!r})
msgs = em.load_all_messages()
contacts = em.build_contacts(msgs)
ca = load({str(ROOT / "tools/calendar/ca-l1-extract.py")!r})
files = ca.discover_parquet_files()
ev = ca.eventi_senza_doppioni(files)
emails = sorted({{e for _, df in ev for a in df['attendees'] for e in ca.parse_attendees(a)}})
xs = load({str(ROOT / "tools/cross-source/xs-l1-contacts-enrich.py")!r})
book = xs.load_contacts()
print(json.dumps({{"accounts": sorted(set(msgs['account'])), "msgs": len(msgs),
    "contacts": sorted(contacts['email'].tolist()) if 'email' in contacts else list(contacts.columns),
    "cal": [a for a, _ in files], "att": emails,
    "book": sorted((c['full_name'], c['primary_phone']) for c in book)}}))
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        env=_kernel_env(tmp),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["accounts"] == ["outlook"] and out["msgs"] == 5
    assert "mia@fabrikam.example" in out["contacts"]
    assert out["cal"] == ["outlook"] and out["att"] == [
        "lee@fabrikam.example",
        "mia@fabrikam.example",
    ]
    assert ["Lee Park", "+1 555 0100"] in out["book"] and ["Mia Conti", "+39 333 000 0001"] in out[
        "book"
    ]


# --------------------------------------------------------------------------- CLI


@pytest.mark.parametrize("script", ["ms-l0-auth.py", "ms-l0-download.py"])
def test_cli_help_and_no_credentials(tmp_path, script):
    env = _kernel_env(tmp_path)
    r = subprocess.run(
        [sys.executable, str(MS / script), "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and "Traceback" not in r.stderr and "usage" in r.stdout
    argv = [sys.executable, str(MS / script)] + (["--check"] if "auth" in script else [])
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "Traceback" not in r.stderr
    lines = [ln for ln in r.stderr.strip().splitlines() if ln]
    assert len(lines) == 1 and lines[0].startswith("microsoft365:")


def test_auth_without_client_id_is_one_line(tmp_path):
    r = subprocess.run(
        [sys.executable, str(MS / "ms-l0-auth.py")],
        env=_kernel_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert r.stderr.strip().splitlines() == [r.stderr.strip()] and "SBK_MS365_CLIENT_ID" in r.stderr


# --------------------------------------------------------------------------- review additions


def test_bearer_token_never_leaves_graph(env):
    fake = FakeMicrosoft()
    g = mg.Graph(mg.TokenProvider("outlook", fake), fake, sleep=lambda s: None)
    with pytest.raises(mg.GraphError) as ei:
        g.get("https://collector.example/me/mailFolders/F/messages/delta?$deltatoken=x")
    assert ei.value.code == "untrusted_link"
    assert not any("collector.example" in c[1] for c in fake.calls)


def test_message_row_accepts_a_date_without_zone():
    row = slots.message_row(_msg("M1", "F", "Hi", "2026-11-10T09:00:00"), "F", "INBOX")
    assert str(row["date"]) == "2026-11-10 09:00:00+00:00"


def test_partial_delta_update_patches_the_row_and_never_blanks_it(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.round = 2
    # Graph may send an update as the id plus only the changed properties.
    fake.delta_items = lambda folder, headers: {
        "F_INBOX": [{"id": "M1", "isRead": False}, {"id": "MX", "isRead": True}],
    }.get(folder, [])
    s = _run(fake)
    msgs = pd.read_parquet(tmp / "emails" / "outlook" / "messages.parquet").set_index("id")
    m1 = msgs.loc["M1"]
    assert m1["subject"] == "Kickoff" and m1["body_text"] == "Body of Kickoff"
    assert m1["from_addr"] == '"Mia Conti" <mia@fabrikam.example>'
    assert str(m1["date"]) == "2026-11-10 09:00:00+00:00"
    assert m1["labels"] == "INBOX,UNREAD" and m1["in_reply_to"] == "<x@fabrikam.example>"
    assert "MX" not in msgs.index  # never seen before: not written as an empty row
    assert s["mail"]["partial_patched"] == 1 and s["mail"]["partial_skipped"] == 1


def test_patch_message_keeps_categories_and_draft_flag():
    old = slots.message_row(
        _msg("M9", "F_A", "S", "2026-11-10T09:00:00Z", isRead=False, categories=["Red"]),
        "F_A",
        "INBOX",
    )
    row = slots.patch_message(old, {"id": "M9", "isRead": True}, "F_B", "Projects")
    assert row["labels"] == "Projects,Red" and row["folder_id"] == "F_B"
    assert row["subject"] == "S" and row["source"] == "microsoft365"


def test_one_refused_mail_folder_does_not_stop_the_others(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.round = 2
    fake.forbid = {"/me/mailFolders/F_PROJ/messages"}
    s = _run(fake)
    assert s["errors"] == [] and s["mail"]["folders_skipped"][0].startswith(
        "Projects, 2026: HTTP 403"
    )
    msgs = pd.read_parquet(tmp / "emails" / "outlook" / "messages.parquet")
    assert {"M1", "M5", "M6"} <= set(msgs["id"])
    st = json.loads((tmp / "microsoft365" / "outlook" / "state.json").read_text())
    assert st["mail"]["folders"]["F_PROJ"]["delta_link"].endswith("$deltatoken=D1F_PROJ")


def test_only_own_calendars_are_read():
    own = L0.own_calendar
    me = "jordan@contoso.example"
    assert own({"isDefaultCalendar": True, "owner": {"address": "x@y.example"}}, me)
    # personal accounts: the owner address can differ, canShare marks the creator
    assert own({"canShare": True, "owner": {"address": "outlook_0a1b@outlook.example"}}, me)
    assert not own({"isSharedWithMe": True, "canShare": False, "owner": {"address": me}}, me)
    assert not own({"canShare": False, "owner": {"address": "boss@fabrikam.example"}}, me)


def test_one_refused_calendar_keeps_its_rows(env):
    tmp, _ = env
    fake = FakeMicrosoft()
    _run(fake)
    fake.forbid = {"/me/calendars/CAL1/calendarView"}
    s = _run(fake)
    assert s["errors"] == [] and s["calendar"]["calendars_skipped"]
    ev = pd.read_parquet(tmp / "calendars" / "outlook" / "events.parquet")
    assert set(ev["id"]) == {"E1", "E2"}


def test_iphone_json_is_reseeded_while_the_parquet_is_ours(env):
    tmp, _ = env
    jp = tmp / "contacts" / "iphone-contacts.json"
    jp.parent.mkdir(parents=True)
    sam = {"name": "Sam Example", "phones": ["+1 555 0199"], "emails": []}
    jp.write_text(json.dumps({"contacts": [sam]}))
    _run(FakeMicrosoft(), "--only", "contacts")
    noa = {"name": "Noa Example", "phones": ["+1 555 0142"], "emails": []}
    jp.write_text(json.dumps({"contacts": [sam, noa]}))
    s = _run(FakeMicrosoft(), "--only", "contacts")
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    names = list(ct["full_name"])
    assert names.count("Sam Example") == 1 and "Noa Example" in names
    assert s["contacts"]["seeded_from_iphone_json"] == 2


def test_no_seed_into_an_address_book_written_by_someone_else(env):
    tmp, _ = env
    (tmp / "contacts").mkdir()
    pd.DataFrame(
        [{"full_name": "Kim Example", "source": "carddav", "is_business": True}]
    ).to_parquet(tmp / "contacts" / "contacts.parquet")
    (tmp / "contacts" / "iphone-contacts.json").write_text(
        json.dumps({"contacts": [{"name": "Sam Example", "phones": [], "emails": []}]})
    )
    s = _run(FakeMicrosoft(), "--only", "contacts")
    ct = pd.read_parquet(tmp / "contacts" / "contacts.parquet")
    assert s["errors"] == [] and s["contacts"]["seeded_from_iphone_json"] == 0
    assert "Sam Example" not in set(ct["full_name"]) and "Kim Example" in set(ct["full_name"])


def test_all_goes_on_when_one_mailbox_has_no_sign_in(env, monkeypatch, capsys):
    tmp, _ = env
    monkeypatch.setattr(
        sbk_config, "_USER_CFG", {"microsoft365": {"accounts": ["other", "outlook"]}}
    )
    rc = L0.main(["--all"], http=FakeMicrosoft(), sleep=lambda s: None)
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 1 and len(err) == 1 and "no sign-in for 'other'" in err[0]
    assert (tmp / "emails" / "outlook" / "messages.parquet").is_file()
