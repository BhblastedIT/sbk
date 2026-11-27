"""Granola plugin: mocked network only (no real account, no real HTTP, no real Keychain)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
GRANOLA = ROOT / "tools" / "granola"
sys.path.insert(0, str(GRANOLA))

import gr_api  # noqa: E402
import pipeline_dlq  # noqa: E402
import secrets_adapter  # noqa: E402
from monitoring import pipeline_metrics  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, GRANOLA / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("gr_l0_download", "gr-l0-download.py")
CSVI = _load("gr_l0_import_csv", "gr-l0-import-csv.py")
L1 = _load("gr_l1_enrich", "gr-l1-enrich.py")

ME = {"name": "Jordan Blake", "email": "jordan@acme.example"}
MIA = {"name": "Mia Conti", "email": "mia@globex.example"}
LEO = {"name": "Leo Park", "email": "leo@initech.example"}
KEY = "grn_TESTKEY0000000000"

N1, N2, N3, N4 = (
    "not_AAAAAAAAAAAAA1",
    "not_AAAAAAAAAAAAA2",
    "not_AAAAAAAAAAAAA3",
    "not_AAAAAAAAAAAAA4",
)


def _note(nid, title, created, updated, attendees, owner=ME, organiser=None, deleted=None):
    return {
        "id": nid,
        "object": "note",
        "title": title,
        "owner": owner,
        "created_at": created,
        "updated_at": updated,
        "deleted_at": deleted,
        "web_url": f"https://notes.granola.ai/d/{nid}",
        "calendar_event": {
            "event_title": title,
            "invitees": [{"email": a["email"]} for a in attendees],
            "organiser": organiser,
            "calendar_event_id": "evt",
            "scheduled_start_time": created,
            "scheduled_end_time": created,
        },
        "attachments": [],
        "attendees": attendees,
        "folder_membership": [],
        "summary_text": f"{title} summary",
        "summary_markdown": f"## {title}\n- decided the plan",
        "private_notes_text": "ask about budget" if owner == ME else None,
        "private_notes_markdown": "- ask about budget" if owner == ME else None,
        "transcript": None,
    }


TRANSCRIPT = [
    {"speaker": {"source": "microphone", "attribution": "me"}, "text": "Hello.", "start_time": "x"},
    {
        "speaker": {"source": "microphone", "attribution": "me"},
        "text": "Shall we?",
        "start_time": "x",
    },
    {
        "speaker": {"source": "speaker", "attribution": "them", "name": "Mia Conti"},
        "text": "Yes.",
        "start_time": "x",
    },
]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, status, code="", headers=None):
    body = json.dumps({"code": code, "message": code.lower()}).encode()
    return HTTPError(url, status, "err", headers or {}, io.BytesIO(body))


class FakeGranola:
    """Answers the three endpoints the plugin calls; records every request."""

    def __init__(
        self, notes=None, too_large=(), transcript_off=(), missing=(), fail_once=(), refused=()
    ):
        self.notes = notes if notes is not None else self.default_notes()
        self.refused = set(refused)
        self.too_large = set(too_large)
        self.transcript_off = set(transcript_off)
        self.missing = set(missing)
        self.fail_always = set(fail_once)
        self.calls = []
        self.methods = []
        self.auth = set()

    @staticmethod
    def default_notes():
        return {
            N1: _note(
                N1,
                "Kickoff",
                "2026-11-01T10:00:00Z",
                "2026-11-01T11:00:00Z",
                [ME, MIA],
                organiser=ME["email"],
            ),
            N2: _note(N2, "Review", "2026-11-10T15:00:00Z", "2026-11-10T16:00:00Z", [ME, MIA, LEO]),
            N3: _note(
                N3, "Old shared", "2026-11-12T09:00:00Z", "2026-11-12T09:30:00Z", [LEO], owner=LEO
            ),
        }

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(url)
        self.methods.append(req.get_method())
        self.auth.add(req.get_header("Authorization"))
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.removeprefix("/v1")
        if path == "/notes":
            items = sorted(self.notes.values(), key=lambda n: n["created_at"], reverse=True)
            if "created_after" in q:
                items = [n for n in items if n["created_at"][:10] > q["created_after"][:10]]
            if "updated_after" in q:
                items = [n for n in items if n["updated_at"] > q["updated_after"]]
            start = int(q.get("cursor") or 0)
            size = int(q.get("page_size") or 10)
            page = items[start : start + 2]  # small pages to exercise the cursor
            more = start + 2 < len(items)
            summaries = [
                {
                    k: n[k]
                    for k in (
                        "id",
                        "object",
                        "title",
                        "owner",
                        "created_at",
                        "updated_at",
                        "deleted_at",
                    )
                }
                for n in page
            ]
            assert size <= gr_api.LIST_PAGE_SIZE
            return _Resp(
                json.dumps(
                    {
                        "notes": summaries,
                        "hasMore": more,
                        "cursor": str(start + 2) if more else None,
                    }
                ).encode()
            )
        parts = path.strip("/").split("/")
        nid = parts[1]
        if nid in self.fail_always:
            raise _http_error(url, 500, "INTERNAL_ERROR")
        if nid in self.refused:
            raise _http_error(url, 400, "BAD_REQUEST")
        if nid in self.missing or nid not in self.notes:
            raise _http_error(url, 404, "NOTE_NOT_FOUND")
        if len(parts) == 3 and parts[2] == "transcript":
            start = int(q.get("cursor") or 0)
            page = TRANSCRIPT[start : start + 2]
            more = start + 2 < len(TRANSCRIPT)
            return _Resp(
                json.dumps(
                    {
                        "transcript": page,
                        "hasMore": more,
                        "cursor": str(start + 2) if more else None,
                    }
                ).encode()
            )
        note = dict(self.notes[nid])
        if q.get("include") == "transcript":
            if nid in self.too_large:
                raise _http_error(url, 413, "TRANSCRIPT_TOO_LARGE")
            if nid in self.transcript_off:
                raise _http_error(url, 403, "FORBIDDEN")
            note["transcript"] = TRANSCRIPT
        return _Resp(json.dumps(note).encode())


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path / "data")
    # The pipeline step of cli() writes last-runs, metrics and the failure queue: those paths
    # are computed at import from the real data root, so they are moved into tmp_path too.
    monkeypatch.setattr(sbk_config, "LAST_RUNS_FILE", tmp_path / "data" / "last-runs.json")
    monkeypatch.setattr(pipeline_metrics, "SYSTEM_DIR", tmp_path / "data" / "system")
    monkeypatch.setattr(
        pipeline_metrics, "METRICS_FILE", tmp_path / "data" / "system" / "pipeline-metrics.jsonl"
    )
    monkeypatch.setattr(
        pipeline_dlq, "FAILURE_QUEUE_FILE", tmp_path / "data" / "system" / "failure-queue.json"
    )
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(sbk_config, "OWN_EMAILS", frozenset(), raising=False)
    stored = {}
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: stored.get((s, a)))
    for k in (gr_api.ENV_API_KEY, "SBK_CONTAINERIZED"):
        monkeypatch.delenv(k, raising=False)
    return stored


def _args(**kw):
    base = {
        "since": None,
        "days": 60,
        "all": False,
        "force": False,
        "no_transcripts": False,
        "limit": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _client(fake):
    return gr_api.GranolaClient(KEY, opener=fake, delay=0, sleep=lambda s: None)


NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


# --- helpers ---------------------------------------------------------------------------


def test_transcript_to_text_merges_speakers():
    assert gr_api.transcript_to_text(TRANSCRIPT) == "Me: Hello. Shall we?\nMia Conti: Yes."
    phone = [{"speaker": {"source": "microphone", "diarization_label": "Speaker A"}, "text": "Hi"}]
    assert gr_api.transcript_to_text(phone) == "Speaker A: Hi"


def test_key_from_keychain_then_env(_isolated, monkeypatch):
    assert gr_api.resolve_api_key() == ("", "")
    monkeypatch.setenv(gr_api.ENV_API_KEY, "grn_fromenv")
    assert gr_api.resolve_api_key() == ("grn_fromenv", f"env {gr_api.ENV_API_KEY}")
    _isolated[(gr_api.KEYCHAIN_SERVICE, gr_api.KEYCHAIN_ACCOUNT)] = "grn_fromkeychain"
    key, where = gr_api.resolve_api_key()
    assert key == "grn_fromkeychain" and where.startswith("Keychain")


def test_client_is_get_only_and_never_writes():
    fake = FakeGranola()
    L0.run_download(_client(fake), _args(), now=NOW)
    assert set(fake.methods) == {"GET"}
    assert fake.auth == {f"Bearer {KEY}"}
    assert all(c.startswith(gr_api.API_BASE) for c in fake.calls)
    src = (GRANOLA / "gr_api.py").read_text()
    assert "method=" not in src and "POST" not in src


# --- L0 --------------------------------------------------------------------------------


def test_download_writes_notes_state_and_summary():
    fake = FakeGranola()
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["listed"] == 3 and s["downloaded"] == 3 and s["with_transcript"] == 3
    assert s["complete"] and s["window"].startswith("created after 2026-09-26")
    first_list = next(c for c in fake.calls if "/notes?" in c)
    assert "created_after=2026-09-26" in first_list
    files = sorted(p.name for p in gr_api.notes_dir().glob("*.json"))
    assert files == [f"{N1}.json", f"{N2}.json", f"{N3}.json"]
    saved = json.loads((gr_api.notes_dir() / f"{N1}.json").read_text())
    assert saved["_origin"] == "api" and saved["transcript"][0]["text"] == "Hello."
    assert oct(os.stat(gr_api.notes_dir() / f"{N1}.json").st_mode & 0o777) == "0o600"
    state = json.loads(gr_api.state_path().read_text())
    assert state["last_complete_start"] and set(state["notes"]) == {N1, N2, N3}
    assert json.loads(gr_api.summary_path().read_text())["route"] == "api"
    assert KEY not in gr_api.summary_path().read_text() + gr_api.state_path().read_text()


def test_second_run_is_incremental_and_skips_unchanged():
    fake = FakeGranola()
    L0.run_download(_client(fake), _args(), now=NOW)
    fake.calls.clear()
    fake.notes[N2] = dict(fake.notes[N2], updated_at="2026-12-01T00:00:00Z")
    s = L0.run_download(_client(fake), _args(), now=NOW)
    lst = next(c for c in fake.calls if "/notes?" in c)
    assert "updated_after=" in lst and "created_after" not in lst
    # only N2 changed since the overlap point
    assert s["downloaded"] == 1
    assert [c for c in fake.calls if "/notes/" in c and N2 in c]


def test_too_large_transcript_is_read_in_pages():
    fake = FakeGranola(too_large={N1})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["transcripts_paged"] == 1
    saved = json.loads((gr_api.notes_dir() / f"{N1}.json").read_text())
    assert [t["text"] for t in saved["transcript"]] == ["Hello.", "Shall we?", "Yes."]


def test_transcripts_turned_off_keep_the_note():
    fake = FakeGranola(transcript_off={N2})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["downloaded"] == 3 and s["transcripts_unavailable"] == 1
    saved = json.loads((gr_api.notes_dir() / f"{N2}.json").read_text())
    assert saved["transcript"] is None and saved["summary_markdown"]


def test_server_error_on_one_note_does_not_stop_nor_move_the_point():
    fake = FakeGranola(fail_once={N3})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["downloaded"] == 2 and s["retry_next_run"] == 1 and not s["complete"]
    assert json.loads(gr_api.state_path().read_text())["last_complete_start"] == ""


def test_missing_note_is_counted_not_fatal():
    fake = FakeGranola(missing={N2})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["not_found"] == 1 and s["downloaded"] == 2 and s["complete"]


def test_invalid_key_is_one_clear_error():
    def opener(req, timeout):
        raise _http_error(req.full_url, 401, "INVALID_API_KEY")

    with pytest.raises(gr_api.AuthError) as e:
        L0.run_download(_client(opener), _args(), now=NOW)
    assert "API key" in str(e.value) and KEY not in str(e.value)


def test_inactive_subscription_points_to_csv():
    def opener(req, timeout):
        raise _http_error(req.full_url, 403, "SUBSCRIPTION_INACTIVE")

    with pytest.raises(gr_api.AuthError) as e:
        L0.run_download(_client(opener), _args(), now=NOW)
    assert "gr-l0-import-csv.py" in str(e.value)


def test_rate_limit_waits_and_retries():
    slept = []
    inner = FakeGranola()
    state = {"n": 0}

    def opener(req, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise _http_error(req.full_url, 429, "RATE_LIMITED", headers={"Retry-After": "7"})
        return inner(req, timeout)

    c = gr_api.GranolaClient(KEY, opener=opener, delay=0, sleep=slept.append)
    L0.run_download(c, _args(), now=NOW)
    assert 7.0 in slept


def test_limit_run_does_not_move_the_point():
    s = L0.run_download(_client(FakeGranola()), _args(limit=1), now=NOW)
    assert s["downloaded"] == 1 and not s["complete"]


def test_refused_note_does_not_move_the_point_and_comes_back():
    fake = FakeGranola(refused={N2})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["downloaded"] == 2 and s["retry_next_run"] == 1 and not s["complete"]
    assert json.loads(gr_api.state_path().read_text())["last_complete_start"] == ""
    fake.refused.clear()
    s = L0.run_download(_client(fake), _args(), now=NOW)
    # same window again (no saved point yet), N2 now fetched, N1/N3 skipped as unchanged
    assert s["downloaded"] == 1 and s["unchanged"] == 2 and s["complete"]
    assert (gr_api.notes_dir() / f"{N2}.json").exists()


def test_all_lists_every_note_also_after_the_first_run():
    fake = FakeGranola()
    L0.run_download(_client(fake), _args(), now=NOW)
    fake.calls.clear()
    s = L0.run_download(_client(fake), _args(all=True), now=NOW)
    lst = next(c for c in fake.calls if "/notes?" in c)
    assert "updated_after" not in lst and "created_after" not in lst
    assert s["window"] == "every note" and s["listed"] == 3 and s["unchanged"] == 3


def test_narrow_since_does_not_move_the_point():
    fake = FakeGranola()
    L0.run_download(_client(fake), _args(), now=NOW)
    before = json.loads(gr_api.state_path().read_text())["last_complete_start"]
    s = L0.run_download(_client(fake), _args(since="2026-12-31"), now=NOW)
    assert s["complete"] and not s["saved_point_moved"]
    assert json.loads(gr_api.state_path().read_text())["last_complete_start"] == before
    wide = L0.run_download(_client(fake), _args(since="2026-01-01"), now=NOW)
    assert wide["saved_point_moved"]


def test_bad_since_is_one_line(capsys):
    rc = L0.cli(["--since", "yesterday"], opener=FakeGranola(), sleep=lambda s: None)
    err = [x for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert rc == 1 and len(err) == 1 and "not a date" in err[0]


# --- L1 and the kernel contract --------------------------------------------------------


def _download_and_build(**cfg):
    sbk_config._USER_CFG = {"granola": cfg} if cfg else {}
    L0.run_download(_client(FakeGranola()), _args(), now=NOW)
    return L1.build_rows()


def test_l1_contract_and_self_inferred():
    contacts, interactions, stats = _download_and_build()
    assert stats["self"].startswith("inferred") and "jordan@acme.example" in stats["self"]
    emails = {c["email"] for c in contacts}
    assert emails == {"mia@globex.example", "leo@initech.example"}
    mia = next(c for c in contacts if c["email"] == "mia@globex.example")
    assert mia["name"] == "Mia Conti" and mia["interactions"] == 2
    assert (
        mia["first_seen"] == "2026-11-01T10:00:00Z" and mia["last_seen"] == "2026-11-10T15:00:00Z"
    )
    by_title = {i["title"]: i for i in interactions}
    assert by_title["Kickoff"]["owner_role"] == "organizer"
    assert by_title["Review"]["owner_role"] == "attendee"
    assert by_title["Old shared"]["owner_role"] == "other"  # shared by Leo, you not listed
    assert by_title["Kickoff"]["participants"] == "Mia Conti <mia@globex.example>"
    assert all(i["kind"] == "meeting" and i["status"] == "done" for i in interactions)
    text = by_title["Kickoff"]["text"]
    assert text.startswith("## Kickoff") and "## My notes" in text and "Me: Hello." in text
    assert by_title["Kickoff"]["url"].startswith("https://notes.granola.ai/d/")


def test_l1_configured_self_and_no_transcript_in_text():
    contacts, interactions, stats = _download_and_build(
        own_email="jordan@acme.example", text_include_transcript=False
    )
    assert stats["self"] == "configured"
    assert all("## Transcript" not in i["text"] for i in interactions)
    assert "jordan@acme.example" not in {c["email"] for c in contacts}


def test_l1_own_emails_of_another_address_still_infers_the_granola_login(monkeypatch):
    # own_emails lists a personal address; the Granola login is the work one
    monkeypatch.setattr(sbk_config, "OWN_EMAILS", frozenset({"alex@personal.example"}))
    contacts, _, stats = _download_and_build()
    assert stats["self"].startswith("configured + inferred")
    assert "jordan@acme.example" not in {c["email"] for c in contacts}


def test_l1_skips_deleted_notes():
    sbk_config._USER_CFG = {}
    fake = FakeGranola()
    fake.notes[N4] = _note(
        N4,
        "Gone",
        "2026-11-20T10:00:00Z",
        "2026-11-21T10:00:00Z",
        [ME, MIA],
        deleted="2026-11-21T10:00:00Z",
    )
    L0.run_download(_client(fake), _args(), now=NOW)
    _, interactions, stats = L1.build_rows()
    assert stats["deleted_skipped"] == 1 and "Gone" not in {i["title"] for i in interactions}


def test_kernel_intake_reader_accepts_the_files():
    sys.path.insert(0, str(ROOT / "tools" / "cross-source"))
    import plugin_intake

    contacts, interactions, _ = _download_and_build()
    L1.write_outputs(contacts, interactions)
    root = sbk_config.DATA_ROOT
    assert plugin_intake.contact_files(root) == [gr_api.contacts_path()]
    events = plugin_intake.load_interactions(root)
    assert set(events["kind"]) == {"meeting"} and len(events) == 3
    people = plugin_intake.load_people(root)
    assert "jordan@acme.example" not in set(people["email"])
    assert not people[plugin_intake.FROM_PARTICIPANTS].any()
    assert not any(plugin_intake.is_commitment(r) for r in events.itertuples(index=False))


# --- CSV export (free plan) ------------------------------------------------------------


CSV_TEXT = (
    "Title,Created At,Summary,Transcript,Attendees\n"
    '"Demo call",2026-10-02 09:00:00,"We agreed on next steps","Me: hi\nThem: hello",'
    '"Mia Conti <mia@globex.example>, leo@initech.example"\n'
    '"Solo memo",2026-10-03T08:00:00Z,"Just me",,\n'
    ",,,,\n"
)


def test_csv_import_maps_columns_and_feeds_l1(tmp_path):
    f = tmp_path / "granola-export.csv"
    f.write_text(CSV_TEXT, encoding="utf-8")
    s = CSVI.run_import(f)
    assert s["imported"] == 2 and s["empty_rows"] == 1 and s["with_attendees"] == 1
    assert set(s["columns_found"]) == {"title", "date", "summary", "transcript", "attendees"}
    assert set(s["columns_missing"]) == {"id", "url"}
    contacts, interactions, _ = L1.build_rows()
    assert {c["email"] for c in contacts} == {"mia@globex.example", "leo@initech.example"}
    demo = next(i for i in interactions if i["title"] == "Demo call")
    assert demo["ts"] == "2026-10-02T09:00:00Z" and "Them: hello" in demo["text"]
    assert demo["owner_role"] == "attendee"


def test_csv_override_and_missing_title(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("Meeting name,When\nPlanning,2026-10-01\n", encoding="utf-8")
    with pytest.raises(gr_api.GranolaError) as e:
        CSVI.run_import(f)
    assert "Meeting name" in str(e.value) and "csv_columns" in str(e.value)
    sbk_config._USER_CFG = {"granola": {"csv_columns": {"title": "Meeting name", "date": "When"}}}
    s = CSVI.run_import(f)
    assert s["imported"] == 1


def test_csv_never_replaces_an_api_note(tmp_path):
    L0.run_download(_client(FakeGranola()), _args(), now=NOW)
    f = tmp_path / "e.csv"
    f.write_text(f"ID,Title,Summary\n{N1},Kickoff from csv,other\n", encoding="utf-8")
    s = CSVI.run_import(f)
    assert s["kept_api_version"] == 1 and s["imported"] == 0
    assert json.loads((gr_api.notes_dir() / f"{N1}.json").read_text())["_origin"] == "api"


def test_csv_row_of_an_api_note_is_counted_once(tmp_path):
    # the CSV has no id column: its rows get csv_ ids, the API has the same meeting
    L0.run_download(_client(FakeGranola()), _args(), now=NOW)
    f = tmp_path / "e.csv"
    f.write_text(
        "Title,Created At,Summary\nKickoff,2026-11-01 10:00:00,other\nOnly here,2026-10-01,x\n",
        encoding="utf-8",
    )
    s = CSVI.run_import(f)
    assert s["imported"] == 2
    _, interactions, stats = L1.build_rows()
    titles = [i["title"] for i in interactions]
    assert titles.count("Kickoff") == 1 and "Only here" in titles
    assert stats["csv_duplicates_skipped"] == 1


def test_csv_reexport_with_new_summary_keeps_the_same_file(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("Title,Created At,Summary\nSync,2026-10-02 09:00:00,first\n", encoding="utf-8")
    CSVI.run_import(f)
    f.write_text("Title,Created At,Summary\nSync,2026-10-02 09:00:00,second\n", encoding="utf-8")
    CSVI.run_import(f)
    files = list(gr_api.notes_dir().glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["summary_text"] == "second"


def test_parse_attendees():
    got = CSVI.parse_attendees('Ana Demo <ana@x.example>; bo@y.example\n"Cy Demo"')
    assert got == [
        {"name": "Ana Demo", "email": "ana@x.example"},
        {"name": None, "email": "bo@y.example"},
        {"name": "Cy Demo", "email": ""},
    ]


# --- command line ----------------------------------------------------------------------


def _run(script, *args, env_extra=None, tmp=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GRANOLA_")}
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    env.update({"SBK_CONTAINERIZED": "1", "SBK_DATA_ROOT": str(tmp), "SBK_CONFIG": str(cfg)})
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(GRANOLA / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp),
        timeout=120,
    )


@pytest.mark.parametrize("script", ["gr-l0-download.py", "gr-l0-import-csv.py", "gr-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    r = _run(script, "--help", tmp=tmp_path)
    assert r.returncode == 0 and "usage" in r.stdout and "Traceback" not in r.stderr


@pytest.mark.parametrize(
    ("script", "start"),
    [
        ("gr-l0-download.py", "Granola: no API key"),
        ("gr-l0-import-csv.py", "Granola: give the CSV file"),
        ("gr-l1-enrich.py", "Granola: nothing downloaded"),
    ],
)
def test_no_credentials_one_clear_line(script, start, tmp_path):
    r = _run(script, tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith(start), r.stderr


def test_cli_end_to_end_in_process(capsys):
    os.environ[gr_api.ENV_API_KEY] = KEY
    try:
        rc = L0.cli([], opener=FakeGranola(), sleep=lambda s: None)
    finally:
        os.environ.pop(gr_api.ENV_API_KEY, None)
    out = capsys.readouterr()
    assert rc == 0 and "3 downloaded" in out.out and KEY not in out.out + out.err
    # the pipeline step's bookkeeping stayed inside the test data root
    assert sbk_config.LAST_RUNS_FILE.is_relative_to(sbk_config.DATA_ROOT)
    assert "granola" in json.loads(sbk_config.LAST_RUNS_FILE.read_text())


def test_cli_invalid_key_never_prints_the_key(capsys):
    def opener(req, timeout):
        raise _http_error(req.full_url, 401, "INVALID_API_KEY")

    os.environ[gr_api.ENV_API_KEY] = KEY
    try:
        rc = L0.cli([], opener=opener, sleep=lambda s: None)
    finally:
        os.environ.pop(gr_api.ENV_API_KEY, None)
    out = capsys.readouterr()
    assert rc == 1 and "Granola: Granola refused the API key" in out.err
    assert "Traceback" not in out.err and KEY not in out.out + out.err
    # still recorded as a failed step, inside the test data root
    queue = pipeline_dlq.FAILURE_QUEUE_FILE
    assert queue.is_relative_to(sbk_config.DATA_ROOT) and queue.exists()
    assert KEY not in queue.read_text()
