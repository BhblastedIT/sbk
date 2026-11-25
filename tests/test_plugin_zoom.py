"""Zoom plugin: mocked network only (no real account, no real HTTP, no real Keychain)."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
ZOOM = ROOT / "tools" / "zoom"
sys.path.insert(0, str(ZOOM))

import secrets_adapter  # noqa: E402
import zm_api  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ZOOM / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("zm_l0_download", "zm-l0-download.py")
L1 = _load("zm_l1_enrich", "zm-l1-enrich.py")
AUTH = _load("zm_l0_auth", "zm-l0-auth.py")

ME = {"id": "U_ME", "email": "jordan@acme.example", "display_name": "Jordan Blake"}
UUID_A = "abc+/def=="  # contains '/', must be double-encoded
UUID_B = "plainUuid123=="
VTT = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
Jordan Blake: Hello everyone.

2
00:00:03.500 --> 00:00:05.000
Jordan Blake: Let's start.

3
00:00:05.500 --> 00:00:08.000
Mia Conti: Thanks, the draft is ready.
"""


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, code, body=b"{}", headers=None):
    return HTTPError(url, code, "err", headers or {}, io.BytesIO(body))


class FakeZoom:
    """Answers the Zoom endpoints the plugin calls; records every request."""

    def __init__(self, daily_limit_on_participants=False):
        self.calls = []
        self.daily = daily_limit_on_participants
        self.token_calls = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append((req.get_method(), url, dict(req.header_items())))
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if url == zm_api.TOKEN_URL:
            body = parse_qs(req.data.decode())
            self.token_calls.append(body)
            if body.get("refresh_token", [""])[0] == "revoked":
                raise _http_error(url, 400, b'{"reason":"Invalid Token!","error":"invalid_grant"}')
            return _Resp(
                json.dumps(
                    {
                        "access_token": "AT-1",
                        "refresh_token": "RT-rotated",
                        "expires_in": 3600,
                        "scope": " ".join(zm_api.REQUIRED_SCOPES),
                    }
                ).encode()
            )
        assert req.get_header("Authorization") == "Bearer AT-1"
        path = u.path
        if u.netloc == "files.zoom.example":
            return _Resp(VTT.encode())
        assert u.netloc == "api.zoom.us"
        if path == "/v2/users/me":
            return _Resp(json.dumps(ME).encode())
        if path == "/v2/users/me/recordings":
            if q.get("next_page_token") == "P2":
                return _Resp(
                    json.dumps({"meetings": [self._meeting(UUID_B, "Weekly sync", False)]}).encode()
                )
            if q["from"] <= "2026-11-20" <= q["to"]:
                return _Resp(
                    json.dumps(
                        {
                            "meetings": [self._meeting(UUID_A, "Project kickoff", True)],
                            "next_page_token": "P2",
                        }
                    ).encode()
                )
            return _Resp(json.dumps({"meetings": []}).encode())
        if path.startswith("/v2/past_meetings/"):
            seg = path.split("/")[3]
            if self.daily:
                raise _http_error(
                    url,
                    429,
                    b'{"message":"You have reached the maximum daily rate limit for this API."}',
                )
            if seg == zm_api.encode_uuid(UUID_A):
                if q.get("next_page_token") == "N2":
                    return _Resp(
                        json.dumps(
                            {
                                "participants": [
                                    {
                                        "name": "Sam Taylor",
                                        "user_email": "",
                                        "join_time": "2026-11-10T09:01:00Z",
                                    }
                                ]
                            }
                        ).encode()
                    )
                return _Resp(
                    json.dumps(
                        {
                            "participants": [
                                {
                                    "name": "Jordan Blake",
                                    "user_email": "jordan@acme.example",
                                    "join_time": "2026-11-10T09:00:00Z",
                                },
                                {
                                    "name": "Mia Conti",
                                    "user_email": "mia@globex.example",
                                    "join_time": "2026-11-10T09:00:30Z",
                                },
                                {
                                    "name": "Mia Conti",
                                    "user_email": "mia@globex.example",
                                    "join_time": "2026-11-10T09:20:00Z",
                                },
                            ],
                            "next_page_token": "N2",
                        }
                    ).encode()
                )
            raise _http_error(url, 400, b'{"code":3001,"message":"Meeting does not exist."}')
        raise AssertionError(f"unexpected URL {url}")

    @staticmethod
    def _meeting(uuid, topic, with_transcript):
        files = [
            {
                "file_type": "MP4",
                "download_url": "https://files.zoom.example/v.mp4",
                "status": "completed",
            }
        ]
        if with_transcript:
            files.append(
                {
                    "file_type": "TRANSCRIPT",
                    "file_extension": "VTT",
                    "recording_type": "audio_transcript",
                    "download_url": "https://files.zoom.example/t.vtt",
                    "status": "completed",
                }
            )
        start = "2026-11-10T09:00:00Z" if with_transcript else "2026-11-12T15:00:00Z"
        return {
            "uuid": uuid,
            "id": 123,
            "topic": topic,
            "host_id": "U_ME",
            "start_time": start,
            "share_url": f"https://zoom.example/rec/share/{topic[:4]}",
            "recording_files": files,
        }


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    stored = {}
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: stored.get((s, a)))
    monkeypatch.setattr(
        secrets_adapter, "set_secret", lambda s, a, v: stored.__setitem__((s, a), v)
    )
    for k in (
        zm_api.ENV_CLIENT_ID,
        zm_api.ENV_REFRESH_TOKEN,
        zm_api.ENV_TOKEN_FILE,
        "SBK_CONTAINERIZED",
    ):
        monkeypatch.delenv(k, raising=False)
    return stored


def _args(**kw):
    base = {
        "label": "default",
        "since": None,
        "days": 30,
        "force": False,
        "no_participants": False,
        "no_transcripts": False,
        "include_unrecorded": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _client(fake):
    return zm_api.ZoomClient("AT-1", opener=fake, delay=0, sleep=lambda s: None)


# --- pure helpers ----------------------------------------------------------------------


def test_scopes_are_user_level_only():
    for s in (*zm_api.REQUIRED_SCOPES, *zm_api.OPTIONAL_SCOPES):
        assert not s.endswith((":admin", ":master")), s


def test_encode_uuid_double_encodes_slashes():
    assert zm_api.encode_uuid(UUID_B) == "plainUuid123%3D%3D"
    assert zm_api.encode_uuid(UUID_A) == "abc%252B%252Fdef%253D%253D"
    key = zm_api.file_key(UUID_A)
    assert "/" not in key and base64.urlsafe_b64decode(key + "==").decode() == UUID_A


def test_windows_are_at_most_a_month():
    w = list(zm_api.windows(date(2026, 8, 1), date(2026, 11, 25)))
    assert w[0][0] == date(2026, 8, 1) and w[-1][1] == date(2026, 11, 25)
    assert all((b - a).days <= 29 for a, b in w)
    assert all(w[i][1].toordinal() + 1 == w[i + 1][0].toordinal() for i in range(len(w) - 1))


def test_vtt_to_text_merges_speakers():
    text, speakers = zm_api.vtt_to_text(VTT)
    assert (
        text == "Jordan Blake: Hello everyone. Let's start.\nMia Conti: Thanks, the draft is ready."
    )
    assert speakers == ["Jordan Blake", "Mia Conti"]


def test_pkce_challenge_is_s256():
    verifier, challenge = AUTH.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expect = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert challenge == expect
    url = AUTH.authorize_url("PUBCID", "http://127.0.0.1:5555/callback", challenge, "st")
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["PUBCID"]
    assert "scope" not in q  # the app's own (user-level) scopes are used


def test_login_callback_survives_a_stray_browser_request():
    """Loopback only: a local server on 127.0.0.1, no request leaves this machine."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]

    def browser():
        for path in ("/favicon.ico", "/callback?code=C0DE&state=ST"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read()
            except HTTPError:
                pass

    t = threading.Thread(target=browser)
    t.start()
    assert AUTH.wait_for_code(server, "ST") == "C0DE"
    t.join()


def test_exchange_code_sends_verifier_and_public_client_id():
    seen = {}

    def opener(req, timeout):
        seen["body"] = parse_qs(req.data.decode())
        seen["auth"] = req.get_header("Authorization")
        return _Resp(b'{"access_token":"x","refresh_token":"y"}')

    AUTH.exchange_code("PUBCID", "CODE", "http://127.0.0.1:1/callback", "VER", opener=opener)
    assert seen["body"]["code_verifier"] == ["VER"] and seen["body"]["client_id"] == ["PUBCID"]
    assert seen["auth"] is None  # PKCE public client: no Basic header, no secret


# --- auth / refresh --------------------------------------------------------------------


def test_connect_rotates_refresh_token_into_keychain(_isolated, monkeypatch):
    monkeypatch.setenv(zm_api.ENV_CLIENT_ID, "PUBCID")
    _isolated[("sbk-zoom", "default")] = "RT-0"
    fake = FakeZoom()
    client, scope = L0.connect("default", opener=fake)
    assert _isolated[("sbk-zoom", "default")] == "RT-rotated"
    body = fake.token_calls[0]
    assert body["grant_type"] == ["refresh_token"] and body["client_id"] == ["PUBCID"]
    assert zm_api.missing_scopes(scope) == []


def test_connect_env_seed_and_token_file(monkeypatch, tmp_path):
    tf = tmp_path / "tok"
    monkeypatch.setenv(zm_api.ENV_CLIENT_ID, "PUBCID")
    monkeypatch.setenv(zm_api.ENV_REFRESH_TOKEN, "RT-env")
    monkeypatch.setenv(zm_api.ENV_TOKEN_FILE, str(tf))
    L0.connect("default", opener=FakeZoom())
    assert tf.read_text() == "RT-rotated"
    assert oct(tf.stat().st_mode & 0o777) == "0o600"
    # next run reads the file before the stale env seed
    assert zm_api.load_refresh_token("default")[0] == "RT-rotated"


def test_revoked_login_is_one_clear_error(_isolated, monkeypatch):
    monkeypatch.setenv(zm_api.ENV_CLIENT_ID, "PUBCID")
    _isolated[("sbk-zoom", "default")] = "revoked"
    with pytest.raises(zm_api.ZoomError) as e:
        L0.connect("default", opener=FakeZoom())
    msg = str(e.value)
    assert "zm-l0-auth.py" in msg and "revoked" not in msg


def test_cli_without_credentials_in_process(capsys):
    assert L0.cli([]) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("Zoom: ") and "ZOOM_CLIENT_ID" in err[0]


# --- download + L1 ---------------------------------------------------------------------


def test_download_and_l1_contract():
    fake = FakeZoom()
    s = L0.run_download(
        _client(fake), _args(), today=date(2026, 11, 25), scope=" ".join(zm_api.REQUIRED_SCOPES)
    )
    raw = zm_api.raw_dir()
    assert s["meetings"] == 2 and s["transcripts_downloaded"] == 1
    assert s["participants_downloaded"] == 1 and s["participants_unavailable"] == 1
    assert s["complete"] and s["window_from"] == "2026-10-26"
    assert (raw / "transcripts" / f"{zm_api.file_key(UUID_A)}.vtt").read_text() == VTT
    assert json.loads(zm_api.summary_path().read_text())["meetings"] == 2
    assert json.loads(zm_api.state_path().read_text())["last_to"] == "2026-11-25"
    # only `me` endpoints, never another user or account-level path
    api_paths = [urlparse(u).path for _, u, _ in fake.calls if "api.zoom.us" in u]
    assert all(p.startswith(("/v2/users/me", "/v2/past_meetings/")) for p in api_paths)
    # recordings were asked in windows of at most one month
    for _, u, _ in fake.calls:
        q = parse_qs(urlparse(u).query)
        if "from" in q:
            assert (date.fromisoformat(q["to"][0]) - date.fromisoformat(q["from"][0])).days <= 29

    contacts, interactions, stats = L1.build_rows()
    L1.write_outputs(contacts, interactions)
    import pandas as pd

    c = pd.read_parquet(zm_api.contacts_path())
    i = pd.read_parquet(zm_api.interactions_path())
    assert list(c.columns) == zm_api.CONTACT_COLUMNS
    assert list(i.columns) == zm_api.INTERACTION_COLUMNS
    assert str(c["interactions"].dtype) == "int64"
    assert set(i["kind"]) == {"meeting"} and set(i["source"]) == {"zoom"}
    assert set(i["status"]) == {"done"}
    kickoff = i[i["title"] == "Project kickoff"].iloc[0]
    assert kickoff["ts"] == "2026-11-10T09:00:00Z" and kickoff["owner_role"] == "organizer"
    assert kickoff["text"].startswith("Jordan Blake: Hello everyone.")
    # the other people only: the kernel reads participants as "the other people"
    assert kickoff["participants"].split("|||") == ["mia@globex.example", "Sam Taylor"]
    # self excluded; Mia once per meeting even after rejoining; Sam by name only
    assert "jordan@acme.example" not in set(c["email"])
    mia = c[c["email"] == "mia@globex.example"].iloc[0]
    assert mia["name"] == "Mia Conti" and mia["first_seen"] == "2026-11-10T09:00:30Z"
    assert mia["interactions"] == 1
    assert "Sam Taylor" in set(c["name"])
    weekly = i[i["title"] == "Weekly sync"].iloc[0]
    assert weekly["text"] == "" and weekly["participants"] == ""  # no transcript, no list


def test_second_run_is_incremental():
    L0.run_download(_client(FakeZoom()), _args(), today=date(2026, 11, 25))
    fake = FakeZoom()
    s = L0.run_download(_client(fake), _args(days=None), today=date(2026, 11, 26))
    assert s["window_from"] == "2026-11-18"  # last_to minus 7 overlap days
    assert s["transcripts_skipped"] == 1 and s["transcripts_downloaded"] == 0
    assert s["participants_skipped"] == 1 and s["participants_unavailable"] == 1  # retried
    assert not any("files.zoom.example" in u for _, u, _ in fake.calls)


def test_daily_limit_stops_and_keeps_state():
    s = L0.run_download(
        _client(FakeZoom(daily_limit_on_participants=True)), _args(), today=date(2026, 11, 25)
    )
    assert not s["complete"] and "daily" in s["stopped"]
    assert json.loads(zm_api.state_path().read_text())["last_to"] == ""


def test_speakers_fallback_when_no_participant_list():
    raw = zm_api.raw_dir()
    key = zm_api.file_key(UUID_B)
    zm_api.write_json(raw / "me.json", ME)
    zm_api.write_json(
        raw / "meetings" / f"{key}.json",
        {"uuid": UUID_B, "topic": "Call", "host_id": "OTHER", "start_time": "2026-11-01T10:00:00Z"},
    )
    zm_api.write_json(
        raw / "participants" / f"{key}.json", {"uuid": UUID_B, "status": "unavailable", "http": 400}
    )
    (raw / "transcripts").mkdir(parents=True, exist_ok=True)
    (raw / "transcripts" / f"{key}.vtt").write_text(VTT)
    contacts, interactions, stats = L1.build_rows()
    assert stats["speakers_fallback"] == 1
    assert [r["name"] for r in contacts] == ["Mia Conti"]  # Jordan Blake is the owner
    assert interactions[0]["owner_role"] == "attendee"


def test_recording_passcodes_never_reach_disk_or_parquet():
    class WithSecrets(FakeZoom):
        @staticmethod
        def _meeting(uuid, topic, with_transcript):
            m = FakeZoom._meeting(uuid, topic, with_transcript)
            m["password"] = "PASS-123"
            m["recording_play_passcode"] = "PLAY-456"
            m["share_url"] = "https://zoom.example/rec/share/abc?pwd=PWD-789&startTime=1"
            m["recording_files"][0]["download_access_token"] = "DAT-000"
            return m

    L0.run_download(_client(WithSecrets()), _args(), today=date(2026, 11, 25))
    blob = "".join(p.read_text() for p in (zm_api.raw_dir() / "meetings").glob("*.json"))
    for secret in ("PASS-123", "PLAY-456", "DAT-000"):
        assert secret not in blob
    contacts, interactions, _ = L1.build_rows()
    urls = [r["url"] for r in interactions]
    assert all("PWD-789" not in u for u in urls)
    assert "https://zoom.example/rec/share/abc?startTime=1" in urls


def test_transcript_download_asks_for_any_type():
    fake = FakeZoom()
    L0.run_download(_client(fake), _args(), today=date(2026, 11, 25))
    accepts = [h.get("Accept") for _, u, h in fake.calls if "files.zoom.example" in u]
    assert accepts == ["*/*"]


def test_server_errors_on_one_item_do_not_stop_the_run_nor_move_the_window():
    class Flaky(FakeZoom):
        def __call__(self, req, timeout):
            if "/v2/past_meetings/" in req.full_url:
                self.calls.append((req.get_method(), req.full_url, dict(req.header_items())))
                raise _http_error(req.full_url, 503, b"{}")
            return super().__call__(req, timeout)

    s = L0.run_download(_client(Flaky()), _args(), today=date(2026, 11, 25))
    assert s["meetings"] == 2 and s["transcripts_downloaded"] == 1
    assert s["retry_next_run"] == 2 and not s["complete"]
    assert json.loads(zm_api.state_path().read_text())["last_to"] == ""
    # nothing written for the failed lists, so the next run asks for them again
    assert not list((zm_api.raw_dir() / "participants").glob("*.json"))
    s2 = L0.run_download(_client(FakeZoom()), _args(), today=date(2026, 11, 25))
    assert s2["participants_downloaded"] == 1 and s2["complete"]


def test_name_only_guest_folds_into_the_one_email_with_that_name():
    raw = zm_api.raw_dir()
    zm_api.write_json(raw / "me.json", ME)
    k1, k2 = zm_api.file_key(UUID_A), zm_api.file_key(UUID_B)
    for k, u, t in ((k1, UUID_A, "2026-11-01T10:00:00Z"), (k2, UUID_B, "2026-11-08T10:00:00Z")):
        zm_api.write_json(
            raw / "meetings" / f"{k}.json",
            {"uuid": u, "topic": "Call", "host_id": "U_ME", "start_time": t},
        )
    zm_api.write_json(
        raw / "participants" / f"{k1}.json",
        {
            "status": "ok",
            "participants": [
                {
                    "name": "Mia Conti",
                    "user_email": "Mia@Globex.example",
                    "join_time": "2026-11-01T10:00:00Z",
                }
            ],
        },
    )
    # second meeting: no participant list, only the transcript speakers
    zm_api.write_json(raw / "participants" / f"{k2}.json", {"status": "unavailable", "http": 400})
    (raw / "transcripts").mkdir(parents=True, exist_ok=True)
    (raw / "transcripts" / f"{k2}.vtt").write_text(VTT)
    contacts, interactions, _ = L1.build_rows()
    assert len(contacts) == 1
    mia = contacts[0]
    assert mia["email"] == "mia@globex.example" and mia["interactions"] == 2
    assert (
        mia["first_seen"] == "2026-11-01T10:00:00Z" and mia["last_seen"] == "2026-11-08T10:00:00Z"
    )
    assert [r["participants"] for r in interactions] == ["mia@globex.example"] * 2


def test_kernel_intake_reader_accepts_the_files_and_never_sees_you():
    sys.path.insert(0, str(ROOT / "tools" / "cross-source"))
    import plugin_intake

    L0.run_download(_client(FakeZoom()), _args(), today=date(2026, 11, 25))
    contacts, interactions, _ = L1.build_rows()
    L1.write_outputs(contacts, interactions)
    root = sbk_config.DATA_ROOT
    assert plugin_intake.contact_files(root) == [zm_api.contacts_path()]
    events = plugin_intake.load_interactions(root)
    assert set(events["kind"]) == {"meeting"} and set(events["owner_role"]) == {"organizer"}
    people = plugin_intake.load_people(root)
    assert "jordan@acme.example" not in set(people["email"])
    assert not people[plugin_intake.FROM_PARTICIPANTS].any()  # every participant is a contact
    assert not any(plugin_intake.is_commitment(r) for r in events.itertuples(index=False))


# --- command line ----------------------------------------------------------------------


def _run(script, *args, env_extra=None, tmp=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZOOM_")}
    # Only the owner fields, no zoom section: the kernel's "no owner" warning stays out of
    # the one-line error checks.
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    env.update({"SBK_CONTAINERIZED": "1", "SBK_DATA_ROOT": str(tmp), "SBK_CONFIG": str(cfg)})
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(ZOOM / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp),
        timeout=120,
    )


@pytest.mark.parametrize("script", ["zm-l0-auth.py", "zm-l0-download.py", "zm-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    r = _run(script, "--help", tmp=tmp_path)
    assert r.returncode == 0 and "usage" in r.stdout and "Traceback" not in r.stderr


@pytest.mark.parametrize("script", ["zm-l0-auth.py", "zm-l0-download.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    r = _run(script, tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("Zoom: ")


def test_download_with_client_id_but_no_login(tmp_path):
    r = _run("zm-l0-download.py", tmp=tmp_path, env_extra={"ZOOM_CLIENT_ID": "PUBCID"})
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and len(lines) == 1 and "zm-l0-auth.py" in lines[0]


def test_l1_without_data_one_clear_line(tmp_path):
    r = _run("zm-l1-enrich.py", tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("Zoom: nothing downloaded")


def test_expired_access_token_is_refreshed_once():
    seen = []

    def opener(req, timeout):
        seen.append(req.get_header("Authorization"))
        if req.get_header("Authorization") != "Bearer AT-new":
            raise _http_error(
                req.full_url, 401, b'{"code":124,"message":"Access token is expired."}'
            )
        return _Resp(json.dumps(ME).encode())

    calls = []
    client = zm_api.ZoomClient(
        "AT-old",
        opener=opener,
        delay=0,
        sleep=lambda s: None,
        refresher=lambda: calls.append(1) or "AT-new",
    )
    assert client.get("/users/me")["id"] == "U_ME"
    assert seen == ["Bearer AT-old", "Bearer AT-new"] and calls == [1]
    # a second 401 on the same call is not retried forever
    client2 = zm_api.ZoomClient(
        "AT-old", opener=opener, delay=0, sleep=lambda s: None, refresher=lambda: "AT-bad"
    )
    with pytest.raises(zm_api.ApiHTTPError):
        client2.get("/users/me")
