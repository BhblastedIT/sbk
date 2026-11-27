"""Fireflies plugin: mocked network only (no real account, no real HTTP, no real Keychain)."""

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

import pytest

ROOT = Path(__file__).resolve().parents[1]
FF = ROOT / "tools" / "fireflies"
sys.path.insert(0, str(FF))

import ff_api  # noqa: E402
import secrets_adapter  # noqa: E402

import sbk_config  # noqa: E402

API_KEY = "ffkey-demo-0123456789"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, FF / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("ff_l0_download", "ff-l0-download.py")
L1 = _load("ff_l1_enrich", "ff-l1-enrich.py")

ME = {"user_id": "U_ME", "email": "jordan@acme.example", "name": "Jordan Blake"}
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)

ACTIONS_M1 = (
    "**Jordan Blake**\n"
    "Send the revised proposal to the client (05:12)\n"
    "Book the follow-up call (12:40)\n"
    "\n"
    "**Mia Conti**\n"
    "Share the draft deck (20:01)\n"
)
ACTIONS_M3 = "Review the budget\n**Jordan**\n- Update the roadmap (01:02:03)\n"


def _meeting(tid, title, when, organizer, **kw):
    m = {
        "id": tid,
        "title": title,
        "dateString": when,
        "date": datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp() * 1000,
        "duration": 30,
        "organizer_email": organizer,
        "participants": [],
        "fireflies_users": [],
        "transcript_url": f"https://app.fireflies.ai/view/{tid}",
        "meeting_link": "",
        "calendar_id": "",
        "cal_id": "",
        "is_live": False,
        "user": dict(ME),
        "speakers": [],
        "meeting_attendees": [],
        "meeting_attendance": [],
        "meeting_info": {
            "fred_joined": True,
            "silent_meeting": False,
            "summary_status": "processed",
        },
        "summary": {"overview": "", "short_summary": "", "gist": "", "action_items": ""},
    }
    m.update(kw)
    return m


def _meetings():
    return [
        _meeting(
            "MTG1",
            "Project kickoff",
            "2026-11-20T09:00:00.000Z",
            "jordan@acme.example",
            participants=[
                "jordan@acme.example",
                "mia@client.example",
                "leo@client.example, ana@partner.example",
            ],
            meeting_attendees=[
                {
                    "displayName": "Mia Conti",
                    "email": "mia@client.example",
                    "phoneNumber": "+44 7700 900111",
                },
                {"name": "Fireflies.ai Notetaker", "email": "fred@fireflies.ai"},
            ],
            speakers=[
                {"id": 0, "name": "Jordan Blake"},
                {"id": 1, "name": "Mia Conti"},
                {"id": 2, "name": "Leo Rossi"},
                {"id": 3, "name": "Speaker 4"},
            ],
            meeting_attendance=[{"name": "Leo Rossi", "join_time": None, "leave_time": None}],
            summary={
                "overview": "Kickoff of the website project.",
                "short_summary": "",
                "gist": "",
                "action_items": ACTIONS_M1,
            },
        ),
        _meeting(
            "MTG2",
            "Weekly sync",
            "2026-11-21T15:00:00.000Z",
            "mia@client.example",
            participants=["mia@client.example", "jordan@acme.example"],
            meeting_info={"summary_status": "processing"},
            summary=None,
        ),
        _meeting(
            "LIVE1",
            "Happening now",
            "2026-11-25T11:30:00.000Z",
            "jordan@acme.example",
            is_live=True,
        ),
        _meeting(
            "MTG3",
            "Roadmap review",
            "2026-11-10T10:00:00.000Z",
            "jordan@acme.example",
            meeting_attendees=[{"name": "Ana Neri", "email": "ana@partner.example"}],
            summary={"overview": "Roadmap reviewed.", "action_items": ACTIONS_M3},
        ),
    ]


SENTENCES = [
    {"index": 0, "speaker_name": "Jordan Blake", "text": "Hello everyone."},
    {"index": 1, "speaker_name": "Jordan Blake", "text": "Let's start."},
    {"index": 2, "speaker_name": "Mia Conti", "text": "The draft is ready."},
]


class _Resp(io.BytesIO):
    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {"X-RateLimit-Limit": "500", "X-RateLimit-Remaining": "480"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(code, payload, headers=None):
    return HTTPError(
        ff_api.API_URL, code, "err", headers or {}, io.BytesIO(json.dumps(payload).encode())
    )


class FakeFireflies:
    """Answers the GraphQL queries the plugin sends; records every request."""

    def __init__(self, meetings=None, fail_on=None, summary_ready=False):
        self.meetings = meetings if meetings is not None else _meetings()
        self.calls: list[dict] = []
        self.fail_on = fail_on or {}  # operation name -> callable(n) raising or None
        self.summary_ready = summary_ready

    def _op(self, query: str) -> str:
        return query.split("{", 1)[0].split("(")[0].replace("query", "").strip()

    def __call__(self, req, timeout):
        assert req.full_url == ff_api.API_URL and req.get_method() == "POST"
        assert req.get_header("Authorization") == f"Bearer {API_KEY}"
        assert req.get_header("Content-type") == "application/json"
        body = json.loads(req.data.decode())
        q, v = body["query"], body.get("variables") or {}
        assert q.lstrip().startswith("query")
        op = self._op(q)
        self.calls.append({"op": op, "vars": v, "query": q})
        n = sum(1 for c in self.calls if c["op"] == op)
        if op in self.fail_on:
            r = self.fail_on[op](n)
            if r is not None:
                return r
        if op == "Me":
            return self._ok({"user": ME})
        if op == "Contacts":
            return self._ok(
                {
                    "contacts": [
                        {
                            "email": "leo@client.example",
                            "name": "Leo Rossi",
                            "last_meeting_date": "2026-11-20",
                        },
                        {
                            "email": "old@friend.example",
                            "name": "Sam Old",
                            "last_meeting_date": "2025-01-05",
                        },
                        {
                            "email": "jordan@acme.example",
                            "name": "Jordan Blake",
                            "last_meeting_date": "2026-11-21",
                        },
                    ]
                }
            )
        if op in ("MyTranscripts", "MyOrganizedTranscripts"):
            frm, to = v["fromDate"], v["toDate"]
            hits = [m for m in self.meetings if frm <= m["dateString"] < to]
            if op == "MyOrganizedTranscripts":
                hits = [m for m in hits if m["organizer_email"] == ME["email"]]
            hits.sort(key=lambda m: m["dateString"], reverse=True)
            page = hits[v["skip"] : v["skip"] + v["limit"]]
            return self._ok({"transcripts": page})
        if op == "OneTranscript":
            m = next((x for x in self.meetings if x["id"] == v["id"]), None)
            if m and self.summary_ready:
                m = dict(
                    m,
                    meeting_info={"summary_status": "processed"},
                    summary={"overview": "Sync done."},
                )
            return self._ok({"transcript": m})
        if op == "TranscriptText":
            return self._ok({"transcript": {"id": v["id"], "sentences": SENTENCES}})
        raise AssertionError(f"unexpected operation {op}")

    @staticmethod
    def _ok(data, errors=None):
        payload = {"data": data}
        if errors:
            payload["errors"] = errors
        return _Resp(json.dumps(payload).encode())


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import pipeline_decorator

    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(ff_api, "load_dotenv_if_present", lambda: None)
    # The pipeline step writes metrics, the failure queue and last-runs to paths fixed at
    # import time (the real data root): an in-process cli() run must not touch them.
    for name in ("_log_metrics", "_record_failure", "mark_last_run"):
        monkeypatch.setattr(pipeline_decorator, name, lambda *a, **k: None)
    stored = {}
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda s, a: stored.get((s, a)))
    for k in (ff_api.ENV_API_KEY, "SBK_CONTAINERIZED"):
        monkeypatch.delenv(k, raising=False)
    return stored


def _args(**kw):
    base = {
        "since": None,
        "days": 30,
        "only_organized": False,
        "no_sentences": False,
        "no_contacts": False,
        "force": False,
        "max_requests": None,
        "check": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _client(fake, max_requests=None, sleeps=None):
    return ff_api.Client(
        API_KEY,
        opener=fake,
        delay=0,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        max_requests=max_requests,
    )


def _all_files_text(root: Path) -> str:
    return "".join(
        p.read_text(errors="replace")
        for p in root.rglob("*")
        if p.is_file() and p.suffix == ".json"
    )


# --- pure helpers ----------------------------------------------------------------------


def test_only_queries_never_a_mutation():
    for q in ff_api.ALL_QUERIES:
        assert q.lstrip().startswith("query") and "mutation" not in q.lower()
        assert "audio_url" not in q and "video_url" not in q
    with pytest.raises(ff_api.FirefliesError):
        _client(FakeFireflies()).query('mutation { deleteTranscript(id: "x") { id } }')


def test_parse_action_items_layouts():
    items = ff_api.parse_action_items(ACTIONS_M1)
    assert [(i["owner"], i["item"], i["offset"]) for i in items] == [
        ("Jordan Blake", "Send the revised proposal to the client", "05:12"),
        ("Jordan Blake", "Book the follow-up call", "12:40"),
        ("Mia Conti", "Share the draft deck", "20:01"),
    ]
    items = ff_api.parse_action_items(ACTIONS_M3)
    assert items[0] == {"owner": "", "item": "Review the budget", "offset": ""}
    assert items[1] == {"owner": "Jordan", "item": "Update the roadmap", "offset": "01:02:03"}
    inline = ff_api.parse_action_items("**Mia Conti**: send the minutes\n1. **Leo**: fix the form")
    assert [(i["owner"], i["item"]) for i in inline] == [
        ("Mia Conti", "send the minutes"),
        ("Leo", "fix the form"),
    ]
    assert ff_api.parse_action_items(None) == [] and ff_api.parse_action_items("") == []


def test_iso_and_api_datetime():
    assert ff_api.iso(1763629200000) == "2025-11-20T09:00:00Z"
    assert ff_api.iso("2026-11-20T09:00:00.000Z") == "2026-11-20T09:00:00Z"
    assert ff_api.iso("2026-11-20") == "2026-11-20T00:00:00Z"
    assert ff_api.api_datetime(NOW) == "2026-11-25T12:00:00.000Z"
    w = list(ff_api.windows(datetime(2026, 9, 1, tzinfo=UTC), NOW, 30))
    assert w[0][0] == datetime(2026, 9, 1, tzinfo=UTC) and w[-1][1] == NOW
    assert all((b - a).days <= 30 for a, b in w)


def test_sentences_to_text_merges_speakers():
    assert ff_api.sentences_to_text(SENTENCES) == (
        "Jordan Blake: Hello everyone. Let's start.\nMia Conti: The draft is ready."
    )


def test_safe_id_never_collides():
    assert ff_api.safe_id("01HABC_def-9") == "01HABC_def-9"
    a, b = ff_api.safe_id("a/b"), ff_api.safe_id("a?b")
    assert a != b and "/" not in a


# --- key lookup ----------------------------------------------------------------------------


def test_key_keychain_then_env(_isolated, monkeypatch):
    with pytest.raises(ff_api.NoApiKey):
        ff_api.resolve_api_key()
    monkeypatch.setenv(ff_api.ENV_API_KEY, "from-env")
    assert ff_api.resolve_api_key() == ("from-env", f"env {ff_api.ENV_API_KEY}")
    _isolated[(ff_api.KEYCHAIN_SERVICE, ff_api.KEYCHAIN_ACCOUNT)] = "from-keychain"
    assert ff_api.resolve_api_key()[0] == "from-keychain"


def test_cli_without_key_in_process(capsys):
    assert L0.cli([]) == 1
    err = [x for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert len(err) == 1 and err[0].startswith("Fireflies: no API key")
    assert not (sbk_config.DATA_ROOT / "fireflies").exists()


def test_check_prints_masked_account(monkeypatch, capsys):
    monkeypatch.setenv(ff_api.ENV_API_KEY, API_KEY)
    assert L0.cli(["--check"], opener=FakeFireflies(), sleep=lambda s: None) == 0
    out = capsys.readouterr().out
    assert "Jordan Blake" in out and "j***@acme.example" in out and API_KEY not in out
    assert not (sbk_config.DATA_ROOT / "fireflies").exists()


def test_auth_failed_is_one_clear_line(monkeypatch, capsys):
    monkeypatch.setenv(ff_api.ENV_API_KEY, API_KEY)
    fake = FakeFireflies(
        fail_on={
            "Me": lambda n: (_ for _ in ()).throw(
                _http_error(
                    401, {"errors": [{"code": "auth_failed", "message": "Invalid API key"}]}
                )
            )
        }
    )
    assert L0.cli([], opener=fake, sleep=lambda s: None) == 1
    err = [x for x in capsys.readouterr().err.splitlines() if x.strip()]
    assert len(err) == 1 and "auth_failed" in err[0] and API_KEY not in err[0]


# --- download -------------------------------------------------------------------------------


def test_download_writes_raw_state_and_summary(monkeypatch):
    monkeypatch.setattr(ff_api, "PAGE_LIMIT", 2)  # three meetings in one window: two pages
    fake = FakeFireflies()
    s = L0.run_download(_client(fake), _args(), now=NOW)
    lists = [c for c in fake.calls if c["op"] == "MyTranscripts"]
    assert all(c["vars"]["userId"] == "U_ME" for c in lists)
    assert all(c["vars"]["limit"] == 2 for c in lists)
    assert any(c["vars"]["skip"] == 2 for c in lists)
    assert all(
        c["vars"]["fromDate"].endswith("Z") and len(c["vars"]["fromDate"]) == 24 for c in lists
    )
    raw = ff_api.raw_dir()
    assert sorted(p.stem for p in (raw / "meetings").glob("*.json")) == ["MTG1", "MTG2", "MTG3"]
    assert s["live_skipped"] == 1 and s["meetings"] == 3
    assert sorted(p.stem for p in (raw / "transcripts").glob("*.json")) == ["MTG1", "MTG2", "MTG3"]
    assert ff_api.read_json(raw / "me.json") == ME
    assert len(ff_api.read_json(raw / "contacts.json")["contacts"]) == 3
    state = ff_api.read_json(ff_api.state_path())
    assert state["last_to"] == "2026-11-25T12:00:00Z" and state["pending_sentences"] == []
    assert list(state["pending_summary"]) == ["MTG2"]
    summary = ff_api.read_json(ff_api.summary_path())
    assert summary["complete"] is True and summary["requests"] == len(fake.calls)
    assert summary["summaries_pending"] == 1 and summary["rate_remaining"] == "480"
    assert API_KEY not in _all_files_text(sbk_config.DATA_ROOT)


def test_only_organized_uses_mine_and_no_user_id():
    fake = FakeFireflies()
    L0.run_download(_client(fake), _args(only_organized=True, no_sentences=True), now=NOW)
    lists = [c for c in fake.calls if c["op"].endswith("Transcripts")]
    assert lists and all(c["op"] == "MyOrganizedTranscripts" for c in lists)
    assert all("userId" not in c["vars"] and "mine: true" in c["query"] for c in lists)
    assert not any(c["op"] == "TranscriptText" for c in fake.calls)
    assert sorted(p.stem for p in ff_api.meetings_dir().glob("*.json")) == ["MTG1", "MTG3"]


def test_second_run_is_incremental_and_refetches_unfinished_summary():
    L0.run_download(_client(FakeFireflies()), _args(), now=NOW)
    fake = FakeFireflies(summary_ready=True)
    later = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)
    s = L0.run_download(_client(fake), _args(), now=later)
    lists = [c for c in fake.calls if c["op"] == "MyTranscripts"]
    assert lists[0]["vars"]["fromDate"] == "2026-11-22T12:00:00.000Z"  # last_to - 3 days overlap
    assert not any(c["op"] == "TranscriptText" for c in fake.calls)  # all on disk already
    assert [c["vars"]["id"] for c in fake.calls if c["op"] == "OneTranscript"] == ["MTG2"]
    assert s["summaries_pending"] == 0
    m2 = ff_api.read_json(ff_api.meetings_dir() / "MTG2.json")
    assert m2["summary"]["overview"] == "Sync done."


def test_summary_never_finished_is_dropped_after_two_weeks():
    L0.run_download(_client(FakeFireflies()), _args(), now=NOW)
    fake = FakeFireflies()
    s = L0.run_download(_client(fake), _args(), now=datetime(2026, 12, 20, 12, 0, tzinfo=UTC))
    assert not any(c["op"] == "OneTranscript" for c in fake.calls)
    assert s["summaries_pending"] == 0


def test_daily_quota_stops_keeps_window_and_pending_text():
    def quota(n):
        if n >= 2:
            raise _http_error(
                429,
                {"errors": [{"code": "too_many_requests", "message": "Too many requests"}]},
                headers={"Retry-After": "40000"},
            )

    fake = FakeFireflies(fail_on={"TranscriptText": quota})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert "rate limit" in s["stopped"] and s["complete"] is False
    state = ff_api.read_json(ff_api.state_path())
    assert state["last_to"] == "2026-11-25T12:00:00Z"  # the listing itself was complete
    assert len(state["pending_sentences"]) == 2
    # next run: the pending texts are asked first, without listing them again as new
    fake2 = FakeFireflies()
    L0.run_download(_client(fake2), _args(), now=NOW)
    assert len([c for c in fake2.calls if c["op"] == "TranscriptText"]) == 2
    assert ff_api.read_json(ff_api.state_path())["pending_sentences"] == []


def test_quota_during_listing_does_not_move_the_saved_date():
    def quota(n):
        raise _http_error(
            429, {"errors": [{"code": "too_many_requests"}]}, headers={"Retry-After": "9999"}
        )

    fake = FakeFireflies(fail_on={"MyTranscripts": quota})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["complete"] is False and ff_api.read_json(ff_api.state_path())["last_to"] == ""


def test_short_429_waits_retry_after_then_retries():
    sleeps = []

    def burst(n):
        if n == 1:
            raise _http_error(
                429, {"errors": [{"code": "too_many_requests"}]}, headers={"Retry-After": "7"}
            )

    fake = FakeFireflies(fail_on={"Me": burst})
    L0.run_download(_client(fake, sleeps=sleeps), _args(no_sentences=True), now=NOW)
    assert 8 in sleeps and [c["op"] for c in fake.calls][:2] == ["Me", "Me"]


def test_request_cap_stops_cleanly():
    fake = FakeFireflies()
    s = L0.run_download(_client(fake, max_requests=4), _args(), now=NOW)
    assert len(fake.calls) == 4 and "request cap" in s["stopped"]
    assert ff_api.read_json(ff_api.state_path())["pending_sentences"]


def test_partial_answer_keeps_data_and_notes_the_error():
    def partial(n):
        return FakeFireflies._ok(
            {"contacts": [{"email": "x@y.example", "name": "X"}]},
            errors=[{"code": "paid_required", "message": "pro_or_higher"}],
        )

    fake = FakeFireflies(fail_on={"Contacts": partial})
    s = L0.run_download(_client(fake), _args(no_sentences=True), now=NOW)
    assert s["contacts"] == 1 and s["partial_errors"] == ["paid_required"]


def test_server_error_retries_then_one_item_error_does_not_stop_the_run():
    def flaky(n):
        raise _http_error(500, {"errors": [{"code": "invariant_violation"}]})

    fake = FakeFireflies(fail_on={"TranscriptText": flaky})
    s = L0.run_download(_client(fake), _args(), now=NOW)
    assert s["errors"] == 3 and s["meetings"] == 3 and not s["stopped"]
    assert len(ff_api.read_json(ff_api.state_path())["pending_sentences"]) == 3


# --- L1 and the kernel contract --------------------------------------------------------------


def _download_and_build(**kw):
    L0.run_download(_client(FakeFireflies()), _args(), now=NOW)
    return L1.build_rows(**kw)


def test_l1_contacts():
    contacts, _i, stats = _download_and_build()
    by = {(c["email"] or c["name"]): c for c in contacts}
    assert "jordan@acme.example" not in by and "Jordan Blake" not in by  # you
    assert "fred@fireflies.ai" not in by and not any("Notetaker" in c["name"] for c in contacts)
    assert not any(c["name"].startswith("Speaker ") for c in contacts)
    assert by["mia@client.example"]["name"] == "Mia Conti"
    assert by["mia@client.example"]["phone"] == "+44 7700 900111"
    assert by["mia@client.example"]["interactions"] == 2  # MTG1 + MTG2
    # Leo: an email in participants and a name in speakers, joined by the contact list
    assert by["leo@client.example"]["name"] == "Leo Rossi" and "Leo Rossi" not in by
    assert by["ana@partner.example"]["interactions"] == 2  # split from "leo..., ana..."
    assert by["old@friend.example"]["interactions"] == 0  # contact list only
    assert by["old@friend.example"]["last_seen"] == "2025-01-05T00:00:00Z"
    assert stats["meetings"] == 3 and stats["with_transcript"] == 3


def test_l1_meetings_and_action_items():
    _c, inter, stats = _download_and_build()
    meetings = {r["title"]: r for r in inter if r["kind"] == "meeting"}
    assert set(meetings) == {"Project kickoff", "Weekly sync", "Roadmap review"}
    k = meetings["Project kickoff"]
    assert k["owner_role"] == "organizer" and k["status"] == "done"
    assert k["text"] == "Kickoff of the website project."
    assert set(k["participants"].split("|||")) == {
        "mia@client.example",
        "leo@client.example",
        "ana@partner.example",
    }
    w = meetings["Weekly sync"]
    assert w["owner_role"] == "attendee"
    assert w["text"].startswith("Jordan Blake: Hello everyone.")  # no summary yet: transcript
    items = {r["title"]: r for r in inter if r["kind"] == "record"}
    mine = items["Send the revised proposal to the client"]
    assert mine["owner_role"] == "assignee" and mine["status"] == "open"
    assert mine["participants"] == k["participants"]
    assert mine["url"].startswith("https://app.fireflies.ai/view/MTG1#action-")
    assert "05:12" in mine["text"]
    other = items["Share the draft deck"]
    assert other["owner_role"] == "other" and other["participants"] == "mia@client.example"
    assert items["Update the roadmap"]["owner_role"] == "assignee"  # lone first name, unique
    assert items["Review the budget"]["owner_role"] == "other"
    assert items["Review the budget"]["participants"] == ""
    assert len({r["url"] for r in items.values()}) == len(items)
    assert stats["action_items"] == 5 and stats["action_items_mine"] == 3


def test_first_name_shared_with_someone_else_is_not_yours():
    ms = _meetings()
    ms[3]["meeting_attendees"].append({"name": "Jordan Price", "email": "jp@other.example"})
    L0.run_download(_client(FakeFireflies(meetings=ms)), _args(), now=NOW)
    _c, inter, _s = L1.build_rows()
    item = next(r for r in inter if r["title"] == "Update the roadmap")
    assert item["owner_role"] == "other"


def test_action_item_modes():
    L0.run_download(_client(FakeFireflies()), _args(), now=NOW)
    _c, inter, _s = L1.build_rows(mode="mine")
    recs = [r for r in inter if r["kind"] == "record"]
    assert recs and all(r["owner_role"] == "assignee" for r in recs)
    _c, inter, _s = L1.build_rows(mode="none")
    assert not [r for r in inter if r["kind"] == "record"]


def test_kernel_intake_reader_accepts_the_files():
    sys.path.insert(0, str(ROOT / "tools" / "cross-source"))
    import plugin_intake

    contacts, interactions, _ = _download_and_build()
    L1.write_outputs(contacts, interactions)
    root = sbk_config.DATA_ROOT
    assert plugin_intake.contact_files(root) == [ff_api.contacts_path()]
    assert plugin_intake.interaction_files(root) == [ff_api.interactions_path()]
    events = plugin_intake.load_interactions(root)
    assert set(events["kind"]) == {"meeting", "record"}
    assert set(events["status"]) == {"done", "open"}
    commitments = [
        r.title for r in events.itertuples(index=False) if plugin_intake.is_commitment(r)
    ]
    assert sorted(commitments) == [
        "Book the follow-up call",
        "Send the revised proposal to the client",
        "Update the roadmap",
    ]
    people = plugin_intake.load_people(root)
    assert "jordan@acme.example" not in set(people["email"])
    import pandas as pd

    cdf = pd.read_parquet(ff_api.contacts_path())
    assert list(cdf.columns) == ff_api.CONTACT_COLUMNS and str(cdf["interactions"].dtype) == "int64"
    idf = pd.read_parquet(ff_api.interactions_path())
    assert list(idf.columns) == ff_api.INTERACTION_COLUMNS


# --- command line ---------------------------------------------------------------------------


def _run(script, *args, tmp=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FIREFLIES_")}
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    # FIREFLIES_API_KEY set to empty: a key in the repo's .env can never reach the script
    # (load_dotenv does not override a variable that exists), so no real request is possible.
    env.update(
        {
            "SBK_CONTAINERIZED": "1",
            "SBK_DATA_ROOT": str(tmp),
            "SBK_CONFIG": str(cfg),
            ff_api.ENV_API_KEY: "",
        }
    )
    return subprocess.run(
        [sys.executable, str(script if isinstance(script, Path) else FF / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp),
        timeout=120,
    )


@pytest.mark.parametrize("script", ["ff-l0-download.py", "ff-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    r = _run(script, "--help", tmp=tmp_path)
    assert r.returncode == 0 and "usage" in r.stdout and "Traceback" not in r.stderr


def test_no_key_one_clear_line(tmp_path):
    r = _run("ff-l0-download.py", tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("Fireflies: no API key")


def test_l1_without_data_one_clear_line(tmp_path):
    r = _run("ff-l1-enrich.py", tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith("Fireflies: nothing downloaded")


# --- review: edge cases ------------------------------------------------------------------------

_DRIVER = """
import importlib.util, io, json, os, sys
from pathlib import Path
from urllib.error import HTTPError

ff = Path(sys.argv[1])
sys.path.insert(0, str(ff.parent))
sys.path.insert(0, str(ff))
spec = importlib.util.spec_from_file_location("l0", ff / "ff-l0-download.py")
l0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l0)
os.environ["FIREFLIES_API_KEY"] = "ffkey-demo-0123456789"


def opener(req, timeout):  # no network: every request is refused like a bad key
    body = {"errors": [{"code": "auth_failed", "message": "Invalid API key"}]}
    raise HTTPError(req.full_url, 401, "x", {}, io.BytesIO(json.dumps(body).encode()))


sys.exit(l0.cli([], opener=opener, sleep=lambda s: None))
"""


def test_auth_failed_one_line_outside_pytest_logging(tmp_path):
    """The real command line, without pytest's log capture: one line, no traceback."""
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER, encoding="utf-8")
    r = _run(driver, str(FF), tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stderr
    assert len(lines) == 1 and "auth_failed" in lines[0] and API_KEY not in r.stderr
    assert not (tmp_path / "fireflies").exists()  # nothing downloaded, nothing written


def test_bad_since_is_a_usage_error_not_a_traceback(tmp_path):
    r = _run("ff-l0-download.py", "--since", "yesterday", tmp=tmp_path)
    assert r.returncode == 2 and "Traceback" not in r.stderr and "--since" in r.stderr


def test_summary_status_default_is_asked_again():
    ms = _meetings()
    ms[1]["meeting_info"] = {"summary_status": "default"}  # "no summary generated yet"
    L0.run_download(_client(FakeFireflies(meetings=ms)), _args(), now=NOW)
    assert "MTG2" in ff_api.read_json(ff_api.state_path())["pending_summary"]


def test_widening_from_only_organized_starts_over():
    L0.run_download(_client(FakeFireflies()), _args(only_organized=True), now=NOW)
    fake = FakeFireflies()
    later = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)
    L0.run_download(_client(fake), _args(days=30), now=later)
    first = [c for c in fake.calls if c["op"] == "MyTranscripts"][0]
    assert first["vars"]["fromDate"] == "2026-10-31T12:00:00.000Z"  # history, not last_to
    assert "MTG2" in {p.stem for p in ff_api.meetings_dir().glob("*.json")}


def test_network_down_mid_listing_saves_state_and_raises():
    from urllib.error import URLError

    L0.run_download(_client(FakeFireflies()), _args(no_sentences=True), now=NOW)
    before = ff_api.read_json(ff_api.state_path())

    def down(n):
        raise URLError("offline")

    fake = FakeFireflies(fail_on={"MyTranscripts": down})
    with pytest.raises(ff_api.FirefliesError):
        L0.run_download(_client(fake), _args(), now=datetime(2026, 11, 30, tzinfo=UTC))
    after = ff_api.read_json(ff_api.state_path())
    assert after["last_to"] == before["last_to"]  # the saved date does not move
    assert after["pending_summary"] == before["pending_summary"]
    summary = ff_api.read_json(ff_api.summary_path())
    assert summary["complete"] is False and "network" in summary["stopped"]
