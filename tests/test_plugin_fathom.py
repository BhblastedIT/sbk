"""Fathom plugin: mocked network only (no real account, no real HTTP, no real Keychain)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
FA = ROOT / "tools" / "fathom"
sys.path.insert(0, str(FA))
sys.path.insert(0, str(ROOT / "tools" / "cross-source"))

import fa_api  # noqa: E402
import plugin_intake  # noqa: E402
import secrets_adapter  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, FA / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("fa_l0_download", "fa-l0-download.py")
L1 = _load("fa_l1_enrich", "fa-l1-enrich.py")

ME = "jordan@acme.example"
KEY = "fake-key-not-real"


def _meeting(
    rid, title, created, invitees, *, recorder=ME, transcript=None, summary="", items=None
):
    return {
        "title": title,
        "meeting_title": title,
        "recording_id": rid,
        "url": f"https://fathom.video/calls/{rid}",
        "share_url": f"https://fathom.video/share/x{rid}",
        "created_at": created,
        "scheduled_start_time": created,
        "recording_start_time": created,
        "calendar_invitees": [
            {"name": n, "email": e, "email_domain": (e or "@").split("@")[1], "is_external": True}
            for n, e in invitees
        ],
        "recorded_by": {"name": "Jordan Blake", "email": recorder, "team": None},
        "transcript": transcript,
        "default_summary": {"template_name": "general", "markdown_formatted": summary}
        if summary
        else None,
        "action_items": items,
    }


def _speaker(name, text, email=None):
    return {
        "speaker": {"display_name": name, "matched_calendar_invitee_email": email},
        "text": text,
        "timestamp": "00:00:01",
    }


def _item(desc, name, email, completed=False, ts=645, rid=1):
    return {
        "description": desc,
        "user_generated": False,
        "completed": completed,
        "recording_timestamp": "00:10:45",
        "recording_playback_url": f"https://fathom.video/calls/{rid}?timestamp={ts}",
        "assignee": {"name": name, "email": email, "team": None},
    }


M1 = _meeting(
    101,
    "Kickoff Demo Corp",
    "2026-10-01T09:00:00Z",
    [("Jordan Blake", ME), ("Mia Conti", "mia@client.example"), ("Leo Ross", "leo@client.example")],
    transcript=[
        _speaker("Jordan Blake", "Hello everyone.", ME),
        _speaker("Jordan Blake", "Let's start."),
        _speaker("Mia Conti", "The draft is ready.", "mia@client.example"),
    ],
    summary="## Summary\nWe agreed on the plan.",
    items=[
        _item("Send the revised proposal", "Jordan Blake", ME, rid=101),
        _item("Share the brand assets", "Mia Conti", "mia@client.example", ts=700, rid=101),
        _item("Book the venue", "Jordan Blake", ME, completed=True, ts=800, rid=101),
    ],
)
M2 = _meeting(
    102,
    "Quick call",
    "2026-10-05T15:00:00Z",
    [],
    transcript=[_speaker("Jordan Blake", "Hi."), _speaker("Mia Conti", "Hi Jordan.")],
    summary="",
    items=[],
)
M3 = _meeting(
    103,
    "Follow-up",
    "2026-10-09T10:00:00Z",
    [("Mia Conti", "mia@client.example"), ("Sam Ito", "sam@other.example")],
    items=None,
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, code, body=b"{}", headers=None):
    return HTTPError(url, code, "err", headers or {}, io.BytesIO(body))


class FakeFathom:
    """GET /meetings in pages of two; records every request (method, url, headers)."""

    def __init__(self, meetings, fail_page=None, fail_code=500, rate_limit_once=False):
        self.meetings = meetings
        self.calls = []
        self.fail_page = fail_page
        self.fail_code = fail_code
        self.rate_limit_once = rate_limit_once

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append((req.get_method(), url, dict(req.header_items())))
        u = urlparse(url)
        assert u.netloc == "api.fathom.ai" and u.path == "/external/v1/meetings", url
        q = parse_qsl(u.query)
        cursor = dict(q).get("cursor", "")
        page = int(cursor or 1)
        if self.rate_limit_once:
            self.rate_limit_once = False
            raise _http_error(url, 429, headers={"Retry-After": "7"})
        if self.fail_page == page:
            raise _http_error(url, self.fail_code)
        after = dict(q).get("created_after", "")
        wanted = [m for m in self.meetings if not after or m["created_at"] > after]
        chunk = wanted[(page - 1) * 2 : page * 2]
        nxt = str(page + 1) if len(wanted) > page * 2 else None
        return _Resp(json.dumps({"limit": 2, "next_cursor": nxt, "items": chunk}).encode())


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(sbk_config, "OWN_EMAILS", {ME})
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: None)
    for v in fa_api.ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def _args(**kw):
    base = {
        "dry_run": False,
        "full": False,
        "since": None,
        "days": None,
        "all_visible": False,
        "no_transcript": False,
        "no_summary": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _client(fake, sleeps=None):
    return fa_api.FathomClient(
        KEY, opener=fake, sleep=(sleeps.append if sleeps is not None else (lambda s: None))
    )


# --------------------------------------------------------------------------- key and client


def test_key_env_fallback_and_sdk_name(env, monkeypatch):
    with pytest.raises(fa_api.NoKey) as e:
        fa_api.resolve_key()
    assert str(e.value).startswith("fathom:") and "FATHOM_API_KEY" in str(e.value)
    monkeypatch.setenv("FATHOM_API_KEY_AUTH", "k2")
    assert fa_api.resolve_key() == ("k2", "env FATHOM_API_KEY_AUTH")
    monkeypatch.setenv("FATHOM_API_KEY", "k1")
    assert fa_api.resolve_key() == ("k1", "env FATHOM_API_KEY")


def test_key_keychain_first(env, monkeypatch):
    monkeypatch.setenv("FATHOM_API_KEY", "from-env")
    monkeypatch.setattr(
        secrets_adapter,
        "get_secret",
        lambda s, a: "from-keychain" if (s, a) == ("sbk-fathom", "api-key") else None,
    )
    assert fa_api.resolve_key() == ("from-keychain", "keychain sbk-fathom/api-key")


def test_client_header_get_only_and_host_guard(env):
    fake = FakeFathom([M1])
    c = _client(fake)
    c.get("/meetings", [("include_action_items", "true")])
    method, url, headers = fake.calls[0]
    assert method == "GET"
    assert {k.lower(): v for k, v in headers.items()}["x-api-key"] == KEY
    with pytest.raises(fa_api.FathomError):
        c.get("@evil.example/steal")
    assert len(fake.calls) == 1  # nothing sent for the refused URL


def test_no_write_verbs_in_plugin():
    src = "\n".join(p.read_text(encoding="utf-8") for p in FA.glob("*.py"))
    assert not re.search(r"method\s*=\s*\"(POST|PUT|PATCH|DELETE)\"", src)
    assert not re.search(
        r"\.(get|paged)\(\s*\"/users", src
    )  # the admin-only endpoint is never called
    assert "Bearer" not in src  # API key only, no OAuth
    assert re.findall(r"\.(?:get|paged)\(\s*\"(/[a-z_]+)", src) and set(
        re.findall(r"\.(?:get|paged)\(\s*\"(/[a-z_]+)", src)
    ) == {"/meetings"}


def test_redirect_never_followed_key_never_forwarded():
    # urllib's default handler copies X-Api-Key onto the redirect target, whatever its host.
    from email.message import Message
    from urllib.request import HTTPRedirectHandler, Request

    assert any(isinstance(h, fa_api._NoRedirect) for h in fa_api._OPENER.handlers)
    assert not any(type(h) is HTTPRedirectHandler for h in fa_api._OPENER.handlers)
    req = Request(f"{fa_api.API_BASE}/meetings", headers={"X-Api-Key": KEY}, method="GET")
    hdrs = Message()
    hdrs["Location"] = "https://evil.example/collect"
    opened = []
    h = fa_api._NoRedirect()
    h.parent = SimpleNamespace(open=lambda *a, **k: opened.append(a))
    assert h.http_error_302(req, io.BytesIO(b""), 302, "Found", hdrs) is None
    assert opened == []  # nothing was sent to the new host


def test_redirect_status_is_one_clear_error(env):
    def opener(req, timeout):
        raise _http_error(req.full_url, 302, b"", {"Location": "https://evil.example/"})

    with pytest.raises(fa_api.ApiHTTPError) as e:
        _client(opener).get("/meetings")
    assert e.value.code == 302 and KEY not in str(e.value)


def test_safe_id_and_cfg_int(env, monkeypatch):
    assert fa_api.safe_id(123456789) == "123456789"
    for bad in ("../../etc/x", "a/b", "", None, "x" * 65):
        assert fa_api.safe_id(bad) == ""
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"fathom": {"overlap_days": "two"}})
    assert fa_api.cfg_int("overlap_days", 14) == 14
    monkeypatch.setattr(sbk_config, "_USER_CFG", {"fathom": {"overlap_days": 3}})
    assert fa_api.cfg_int("overlap_days", 14) == 3


def test_429_waits_retry_after(env):
    sleeps: list[float] = []
    fake = FakeFathom([M1], rate_limit_once=True)
    c = _client(fake, sleeps)
    items = list(c.paged("/meetings", [], heavy=True))
    assert [m["recording_id"] for m in items] == [101]
    assert 7.0 in sleeps and c.rate_limited == 1


def test_401_one_clear_message(env):
    def opener(req, timeout):
        raise _http_error(req.full_url, 401, b'{"error":"unauthorized"}')

    c = _client(opener)
    with pytest.raises(fa_api.FathomError) as e:
        c.get("/meetings")
    assert "401" in str(e.value) and KEY not in str(e.value)


def test_pacing_heavy_requests(env):
    t = {"now": 0.0}
    sleeps: list[float] = []
    fake = FakeFathom([M1, M2, M3])
    c = fa_api.FathomClient(KEY, opener=fake, sleep=sleeps.append, clock=lambda: t["now"])
    list(c.paged("/meetings", [], heavy=True))
    assert len(fake.calls) == 2
    assert sleeps and abs(sleeps[0] - fa_api.HEAVY_PAUSE_SECS) < 1e-9


# --------------------------------------------------------------------------- L0


def test_l0_download_files_params_and_state(env):
    fake = FakeFathom([M1, M2, M3])
    now = datetime(2026, 11, 1, tzinfo=UTC)
    s = L0.run_download(_client(fake), _args(), now=now)
    assert s["meetings"] == 3 and s["complete"] and s["action_items"] == 3
    for rid in (101, 102, 103):
        assert (env / "fathom" / "raw" / "meetings" / f"{rid}.json").exists()
    assert (env / "fathom" / "download-summary.json").exists()
    state = json.loads((env / "fathom" / "raw" / "state.json").read_text())
    assert state["watermark"] == "2026-11-01T00:00:00Z" and state["recorded_by"] == [ME]
    q = parse_qsl(urlparse(fake.calls[0][1]).query)
    assert ("recorded_by[]", ME) in q
    for k in ("include_transcript", "include_summary", "include_action_items"):
        assert (k, "true") in q
    assert dict(q)["created_after"] == "2025-11-01T00:00:00Z"  # 365 days back

    # second run: from the watermark minus 14 days of overlap
    fake2 = FakeFathom([M1, M2, M3])
    L0.run_download(_client(fake2), _args(), now=datetime(2026, 11, 20, tzinfo=UTC))
    assert (
        dict(parse_qsl(urlparse(fake2.calls[0][1]).query))["created_after"]
        == "2026-10-18T00:00:00Z"
    )


def test_l0_all_visible_and_light(env):
    fake = FakeFathom([M1])
    s = L0.run_download(
        _client(fake), _args(all_visible=True, no_transcript=True, no_summary=True, full=True)
    )
    q = parse_qsl(urlparse(fake.calls[0][1]).query)
    keys = [k for k, _ in q]
    assert "recorded_by[]" not in keys and "created_after" not in keys
    assert "include_transcript" not in keys and "include_summary" not in keys
    assert s["filter"].startswith("none")


def test_l0_light_run_keeps_old_transcript(env):
    L0.run_download(_client(FakeFathom([M1])), _args(full=True))
    light = dict(M1, transcript=None, default_summary=None)
    L0.run_download(
        _client(FakeFathom([light])), _args(full=True, no_transcript=True, no_summary=True)
    )
    saved = json.loads((env / "fathom" / "raw" / "meetings" / "101.json").read_text())
    assert saved["transcript"] and saved["default_summary"]


def test_l0_interrupted_keeps_files_and_watermark(env):
    L0.run_download(_client(FakeFathom([M1])), _args(), now=datetime(2026, 10, 2, tzinfo=UTC))
    fake = FakeFathom([M1, M2, M3], fail_page=2, fail_code=503)
    s = L0.run_download(_client(fake), _args(full=True), now=datetime(2026, 11, 1, tzinfo=UTC))
    assert not s["complete"] and s["stopped"].startswith("fathom:")
    assert s["meetings"] == 2  # page 1 kept
    state = json.loads((env / "fathom" / "raw" / "state.json").read_text())
    assert state["watermark"] == "2026-10-02T00:00:00Z"  # not moved


def _state(env):
    return json.loads((env / "fathom" / "raw" / "state.json").read_text())


def _created_after_of(fake):
    return dict(parse_qsl(urlparse(fake.calls[0][1]).query)).get("created_after", "")


def test_l0_light_run_does_not_move_watermark(env):
    L0.run_download(_client(FakeFathom([M1])), _args(), now=datetime(2026, 10, 2, tzinfo=UTC))
    L0.run_download(
        _client(FakeFathom([M1, M2, M3])),
        _args(no_transcript=True, no_summary=True),
        now=datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert _state(env)["watermark"] == "2026-10-02T00:00:00Z"
    # the next full run still reads transcripts from the old watermark minus the overlap
    fake = FakeFathom([M1, M2, M3])
    L0.run_download(_client(fake), _args(), now=datetime(2026, 11, 21, tzinfo=UTC))
    assert _created_after_of(fake) == "2026-09-18T00:00:00Z"
    assert _state(env)["watermark"] == "2026-11-21T00:00:00Z"


def test_l0_since_after_watermark_leaves_no_gap(env):
    L0.run_download(_client(FakeFathom([M1])), _args(), now=datetime(2026, 10, 2, tzinfo=UTC))
    L0.run_download(
        _client(FakeFathom([M3])), _args(since="2026-11-10"), now=datetime(2026, 11, 20, tzinfo=UTC)
    )
    assert _state(env)["watermark"] == "2026-10-02T00:00:00Z"  # Oct 2 - Nov 10 never read
    L0.run_download(
        _client(FakeFathom([M3])), _args(since="2026-09-01"), now=datetime(2026, 11, 20, tzinfo=UTC)
    )
    assert _state(env)["watermark"] == "2026-11-20T00:00:00Z"


def test_l0_filter_change_ignores_watermark(env):
    L0.run_download(_client(FakeFathom([M1])), _args(), now=datetime(2026, 10, 2, tzinfo=UTC))
    fake = FakeFathom([M1, M2, M3])
    s = L0.run_download(
        _client(fake), _args(all_visible=True), now=datetime(2026, 11, 1, tzinfo=UTC)
    )
    assert not s["watermark_used"]
    assert _created_after_of(fake) == "2025-11-01T00:00:00Z"  # history_days, as a first run
    st = _state(env)
    assert st["recorded_by"] == [] and st["watermark"] == "2026-11-01T00:00:00Z"


def test_l0_light_then_full_without_watermark_history(env):
    L0.run_download(
        _client(FakeFathom([M1])),
        _args(no_transcript=True),
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert _state(env)["included"] == {"transcript": False, "summary": True}
    fake = FakeFathom([M1])
    L0.run_download(_client(fake), _args(), now=datetime(2026, 10, 3, tzinfo=UTC))
    assert _created_after_of(fake) == "2025-10-03T00:00:00Z"  # saved run had no transcripts


def test_l0_skips_unsafe_recording_id(env):
    bad = dict(M1, recording_id="../../evil")
    s = L0.run_download(_client(FakeFathom([bad, M2])), _args(full=True))
    assert s["meetings"] == 1 and s["skipped_bad_id"] == 1
    assert not list(env.rglob("evil*"))


def test_l0_since_must_be_a_date(capsys):
    with pytest.raises(SystemExit) as e:
        L0.parse_args(["--since", "yesterday"])
    assert e.value.code == 2 and "YYYY-MM-DD" in capsys.readouterr().err


def test_l0_main_dry_run_writes_nothing(env, monkeypatch, capsys):
    monkeypatch.setenv("FATHOM_API_KEY", KEY)
    rc = L0.main(["--dry-run"], opener=FakeFathom([M1]), sleep=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and "dry run" in out and KEY not in out
    assert not (env / "fathom").exists()


# --------------------------------------------------------------------------- L1


@pytest.fixture
def downloaded(env):
    L0.run_download(_client(FakeFathom([M1, M2, M3])), _args(full=True))
    return env


def test_l1_rows(downloaded):
    contacts, inter, stats = L1.build_rows()
    emails = {c["email"] for c in contacts}
    assert ME not in emails  # you are not a contact
    assert {"mia@client.example", "leo@client.example", "sam@other.example"} <= emails
    mia = next(c for c in contacts if c["email"] == "mia@client.example")
    # M1 invitee, M2 speaker folded into her email, M3 invitee
    assert mia["interactions"] == 3 and mia["name"] == "Mia Conti"
    assert mia["first_seen"].startswith("2026-10-01") and mia["last_seen"].startswith("2026-10-09")
    assert stats["speakers_fallback"] == 1

    meetings = [r for r in inter if r["kind"] == "meeting"]
    assert len(meetings) == 3 and all(r["status"] == "done" for r in meetings)
    k = next(r for r in meetings if r["title"] == "Kickoff Demo Corp")
    assert k["owner_role"] == "organizer" and ME not in k["participants"]
    assert "We agreed on the plan." in k["text"]
    assert "Jordan Blake: Hello everyone. Let's start." in k["text"]
    assert "Mia Conti: The draft is ready." in k["text"]
    assert k["url"] == "https://fathom.video/calls/101"

    items = [r for r in inter if r["kind"] == "record"]
    assert len(items) == 3
    mine_open = next(r for r in items if "revised proposal" in r["title"])
    assert mine_open["owner_role"] == "assignee" and mine_open["status"] == "open"
    assert set(mine_open["participants"].split("|||")) == {
        "mia@client.example",
        "leo@client.example",
    }
    theirs = next(r for r in items if "brand assets" in r["title"])
    assert theirs["owner_role"] == "other" and theirs["participants"] == "mia@client.example"
    done = next(r for r in items if "venue" in r["title"])
    assert done["status"] == "done"
    assert len({r["url"] for r in items}) == 3


def test_l1_infers_me_when_not_configured(downloaded, monkeypatch):
    monkeypatch.setattr(sbk_config, "OWN_EMAILS", set())
    state = downloaded / "fathom" / "raw" / "state.json"
    s = json.loads(state.read_text())
    s["recorded_by"] = []
    state.write_text(json.dumps(s))
    contacts, _inter, stats = L1.build_rows()
    assert stats["me"].startswith("inferred")
    assert ME not in {c["email"] for c in contacts}


def test_l1_kernel_reads_the_files(downloaded, monkeypatch):
    contacts, inter, _ = L1.build_rows()
    L1.write_outputs(contacts, inter)
    monkeypatch.setattr(plugin_intake, "_enabled", lambda p: True)
    c = plugin_intake.load_contacts(downloaded)
    i = plugin_intake.load_interactions(downloaded)
    assert c is not None and len(c) == len(contacts)
    assert i is not None and len(i) == len(inter)
    commitments = [r for r in i.itertuples(index=False) if plugin_intake.is_commitment(r)]
    assert [r.title for r in commitments] == ["Action item: Send the revised proposal"]
    for col in fa_api.CONTACT_COLUMNS:
        assert col in c.columns
    assert c["interactions"].dtype.kind == "i"


# --------------------------------------------------------------------------- CLI


def _run(script, *args, data_root: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FATHOM_", "SBK_"))}
    cfg = data_root / "sbk.config.json"
    cfg.write_text(json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}))
    env.update(
        {
            "FATHOM_API_KEY": "",
            "FATHOM_API_KEY_AUTH": "",
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
        [sys.executable, str(FA / script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(data_root),
    )


@pytest.mark.parametrize("script", ["fa-l0-download.py", "fa-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    p = _run(script, "--help", data_root=tmp_path)
    assert p.returncode == 0 and "usage" in p.stdout.lower() and "Traceback" not in p.stderr


@pytest.mark.parametrize("script", ["fa-l0-download.py", "fa-l1-enrich.py"])
def test_no_credentials_one_clear_line(script, tmp_path):
    p = _run(script, data_root=tmp_path)
    assert p.returncode == 1
    lines = [ln for ln in p.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("fathom:") and "Traceback" not in p.stderr
    assert not (tmp_path / "fathom" / "raw" / "meetings").exists()
