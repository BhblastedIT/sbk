"""Telegram plugin: synthetic Telegram Desktop exports only (no account, no network)."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = ROOT / "tools" / "telegram"
sys.path.insert(0, str(TELEGRAM))

import pipeline_dlq  # noqa: E402
import tg_export as tg  # noqa: E402
from monitoring import pipeline_metrics  # noqa: E402

import sbk_config  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, TELEGRAM / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L0 = _load("tg_l0_import", "tg-l0-import.py")
L1 = _load("tg_l1_enrich", "tg-l1-enrich.py")

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
ME_ID, NORA_ID, LEO_ID, ZED_ID = 1000, 2001, 2002, 2003


def _msg(mid, when, sender, sender_id, text, **extra):
    """One exported message; `when` is 'YYYY-MM-DDTHH:MM:SS' written as UTC wall time."""
    unix = int(datetime.fromisoformat(when).replace(tzinfo=UTC).timestamp())
    m = {
        "id": mid,
        "type": "message",
        "date": when,
        "date_unixtime": str(unix),
        "from": sender,
        "from_id": f"user{sender_id}",
        "text": text,
        "text_entities": [],
    }
    m.update(extra)
    return m


def _full_export():
    return {
        "about": "Here is the data you requested.",
        "personal_information": {
            "user_id": ME_ID,
            "first_name": "Alex",
            "last_name": "Demo",
            "phone_number": "+1 555 0100",
        },
        "contacts": {
            "about": "contacts",
            "list": [
                {
                    "user_id": str(NORA_ID),
                    "first_name": "Nora",
                    "last_name": "Quinn",
                    "phone_number": "+44 7700 900123",
                    "date": "2025-01-01T10:00:00",
                    "date_unixtime": "1735725600",
                },
                {
                    "first_name": "Leo",
                    "last_name": "Park",
                    "phone_number": "+44 7700 900456",
                    "date": "2025-01-01T10:00:00",
                },
                {"date": "2025-01-01T10:00:00", "date_unixtime": "1735725600"},
            ],
        },
        "chats": {
            "about": "chats",
            "list": [
                {
                    "name": "Nora Quinn",
                    "type": "personal_chat",
                    "id": NORA_ID,
                    "messages": [
                        _msg(
                            1,
                            "2026-11-20T09:00:00",
                            "Nora Quinn",
                            NORA_ID,
                            "Hi Alex, got a minute?",
                        ),
                        _msg(
                            2,
                            "2026-11-20T09:05:00",
                            "Alex Demo",
                            ME_ID,
                            [
                                "Sure. ",
                                {"type": "bold", "text": "I'll send you the deck tomorrow."},
                            ],
                        ),
                        {
                            "id": 3,
                            "type": "service",
                            "date": "2026-11-20T10:00:00",
                            "date_unixtime": str(
                                int(datetime(2026, 11, 20, 10, tzinfo=UTC).timestamp())
                            ),
                            "actor": "Nora Quinn",
                            "actor_id": f"user{NORA_ID}",
                            "action": "phone_call",
                            "duration_seconds": 120,
                        },
                        _msg(
                            4,
                            "2026-11-21T08:00:00",
                            "Nora Quinn",
                            NORA_ID,
                            "",
                            media_type="voice_message",
                            file="voice_messages/audio_1.ogg",
                        ),
                        _msg(
                            5,
                            "2024-03-01T08:00:00",
                            "Nora Quinn",
                            NORA_ID,
                            "I will call you on Friday",
                        ),
                    ],
                },
                {
                    "name": "Project Alpha",
                    "type": "private_group",
                    "id": 3001,
                    "messages": [
                        {
                            "id": 1,
                            "type": "service",
                            "date": "2026-11-19T12:00:00",
                            "actor": "Alex Demo",
                            "actor_id": f"user{ME_ID}",
                            "action": "create_group",
                            "members": ["Nora Quinn", "Leo Park"],
                        },
                        _msg(
                            2, "2026-11-19T12:01:00", "Leo Park", LEO_ID, "Who prepares the budget?"
                        ),
                        _msg(
                            3,
                            "2026-11-19T12:02:00",
                            "Alex Demo",
                            ME_ID,
                            "Ci penso io, entro venerdì.",
                            reply_to_message_id=2,
                        ),
                        _msg(4, "2026-11-19T12:03:00", "Nora Quinn", NORA_ID, "Great"),
                    ],
                },
                {
                    "name": "Weather Bot",
                    "type": "bot_chat",
                    "id": 9001,
                    "messages": [_msg(1, "2026-11-19T12:00:00", "Weather Bot", 9001, "Sunny")],
                },
                {
                    "name": "News",
                    "type": "public_channel",
                    "id": 9100,
                    "messages": [_msg(1, "2026-11-19T12:00:00", "News", 9100, "Headline")],
                },
                {
                    "type": "saved_messages",
                    "id": ME_ID,
                    "messages": [
                        _msg(1, "2026-11-19T12:00:00", "Alex Demo", ME_ID, "note to self")
                    ],
                },
            ],
        },
        # Telegram Desktop always exports a left chat with your own messages only
        # (export_data_types.cpp, FinalizeDialogsInfo: onlyMyMessages = true).
        "left_chats": {
            "about": "left",
            "list": [
                {
                    "name": "Old Club",
                    "type": "private_supergroup",
                    "id": 5001,
                    "messages": [
                        _msg(10, "2025-06-01T18:00:00", "Alex Demo", ME_ID, "See you there"),
                    ],
                }
            ],
        },
    }


def _write_export(folder: Path, data: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "result.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(sbk_config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(sbk_config, "LAST_RUNS_FILE", tmp_path / "data" / "last-runs.json")
    monkeypatch.setattr(pipeline_metrics, "SYSTEM_DIR", tmp_path / "data" / "system")
    monkeypatch.setattr(
        pipeline_metrics, "METRICS_FILE", tmp_path / "data" / "system" / "pipeline-metrics.jsonl"
    )
    monkeypatch.setattr(
        pipeline_dlq, "FAILURE_QUEUE_FILE", tmp_path / "data" / "system" / "failure-queue.json"
    )
    monkeypatch.setattr(sbk_config, "_USER_CFG", {})
    monkeypatch.setattr(sbk_config, "OWNER_NAME", "Alex Demo")
    monkeypatch.setattr(sbk_config, "OWN_NAMES_NORMALIZED", {"alex demo"})

    def _no_network(*a, **k):
        raise AssertionError("the Telegram plugin must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)


def _import(tmp_path, data=None, **kw):
    f = _write_export(tmp_path / "export", data or _full_export())
    return L0.run_import([f.parent], **kw)


# --- export format helpers ---------------------------------------------------------------


def test_flatten_text_handles_string_and_entities():
    assert tg.flatten_text("plain") == "plain"
    assert tg.flatten_text(["a ", {"type": "bold", "text": "b"}, " c"]) == "a b c"
    assert tg.flatten_text(None) == ""


def test_chat_key_uses_the_peer_kind():
    assert tg.chat_key({"type": "personal_chat", "id": 5}) == "user5"
    assert tg.chat_key({"type": "private_group", "id": 5}) == "chat5"
    assert tg.chat_key({"type": "private_supergroup", "id": 5}) == "channel5"


def test_message_ts_prefers_unixtime_and_reads_old_exports_in_the_configured_zone():
    assert tg.message_ts({"date": "2026-11-20T10:00:00", "date_unixtime": "1795168800"}) == (
        "2026-11-20T10:00:00+00:00"
    )
    sbk_config._USER_CFG = {"telegram": {"timezone": "Europe/Rome"}}
    assert tg.message_ts({"date": "2026-07-01T10:00:00"}) == "2026-07-01T08:00:00+00:00"


@pytest.mark.parametrize(
    ("sentence", "day", "due"),
    [
        ("I'll send it tomorrow", "2026-11-20", "2026-11-21"),
        ("ti mando tutto dopodomani", "2026-11-20", "2026-11-22"),
        ("I will call you on Friday", "2026-11-20", "2026-11-27"),  # 20/11/2026 is a Friday
        ("entro venerdì", "2026-11-19", "2026-11-20"),
        ("I'll confirm by 2026-12-03", "2026-11-20", "2026-12-03"),
        ("will do next week", "2026-11-20", "2026-11-27"),
        ("I'll check", "2026-11-20", ""),
    ],
)
def test_due_from_text(sentence, day, due):
    assert tg.due_from_text(sentence, day) == due


def test_find_promise_is_conservative():
    pats = tg.promise_patterns()
    assert tg.find_promise("Thanks! I'll send you the file later.", pats) == (
        "I'll send you the file later."
    )
    assert tg.find_promise("Te lo mando stasera", pats) == "Te lo mando stasera"
    assert tg.find_promise("I sent it yesterday. Nice weather", pats) == ""


def test_bad_promise_pattern_is_one_clear_error():
    sbk_config._USER_CFG = {"telegram": {"promise_patterns": ["("]}}
    with pytest.raises(tg.TelegramError, match="promise_patterns"):
        tg.promise_patterns()


# --- L0 import ----------------------------------------------------------------------------


def test_import_writes_chats_contacts_me_state_and_summary(tmp_path):
    s = _import(tmp_path)
    assert s["files_imported"] == 1 and s["chats"] == 6 and s["messages_new"] == 13
    files = sorted(p.name for p in tg.chats_dir().glob("*.json"))
    assert files == [
        "channel5001.json",
        "channel9100.json",
        "chat3001.json",
        "user1000.json",
        "user2001.json",
        "user9001.json",
    ]
    nora = json.loads((tg.chats_dir() / "user2001.json").read_text())
    assert nora["messages"][1]["text"] == "Sure. I'll send you the deck tomorrow."
    voice = nora["messages"][3]
    assert voice["media_type"] == "voice_message" and "file" not in voice
    left = json.loads((tg.chats_dir() / "channel5001.json").read_text())
    assert left["left"] is True
    assert json.loads(tg.me_path().read_text())["user_id"] == str(ME_ID)
    contacts = json.loads(tg.contacts_raw_path().read_text())
    assert {c["phone_number"] for c in contacts} == {"+44 7700 900123", "+44 7700 900456"}
    summary = json.loads(tg.summary_path().read_text())
    assert summary["complete"] and summary["route"] == "desktop-json-export"
    assert oct(tg.summary_path().stat().st_mode & 0o777) == "0o600"


def test_same_export_twice_is_skipped_and_newer_export_adds_only_new(tmp_path):
    _import(tmp_path)
    again = _import(tmp_path)
    assert again["files_already_imported"] == 1 and again["messages_new"] == 0
    newer = _full_export()
    chat = newer["chats"]["list"][0]
    chat["messages"].append(_msg(6, "2026-11-22T09:00:00", "Nora Quinn", NORA_ID, "Deck received"))
    s = _import(tmp_path, newer)
    assert s["messages_new"] == 1
    nora = json.loads((tg.chats_dir() / "user2001.json").read_text())
    assert [m["id"] for m in nora["messages"]] == [1, 2, 3, 4, 5, 6]


def test_older_export_never_drops_messages(tmp_path):
    _import(tmp_path)
    older = _full_export()
    older["chats"]["list"][0]["messages"] = older["chats"]["list"][0]["messages"][:1]
    _import(tmp_path, older)
    nora = json.loads((tg.chats_dir() / "user2001.json").read_text())
    assert len(nora["messages"]) == 5


def test_older_export_never_rolls_back_an_edit(tmp_path):
    newer = _full_export()
    nora_msgs = newer["chats"]["list"][0]["messages"]
    nora_msgs[0] = _msg(
        1,
        "2026-11-20T09:00:00",
        "Nora Quinn",
        NORA_ID,
        "Hi Alex, got an hour?",
        edited_unixtime="1795165000",
    )
    _import(tmp_path, newer)
    s = _import(tmp_path, _full_export())  # older, unedited copy imported afterwards
    nora = json.loads((tg.chats_dir() / "user2001.json").read_text())
    assert nora["messages"][0]["text"] == "Hi Alex, got an hour?" and s["messages_changed"] == 0


def test_groups_with_only_your_messages_are_flagged(tmp_path, capsys):
    data = _full_export()
    group = data["chats"]["list"][1]
    group["messages"] = [m for m in group["messages"] if m.get("from_id") == f"user{ME_ID}"]
    f = _write_export(tmp_path / "export", data)
    assert L0.main([str(f.parent)]) == 0
    err = capsys.readouterr().err
    assert "1 group(s) hold only your own messages" in err and "Only my messages" in err
    summary = json.loads(tg.summary_path().read_text())
    assert summary["groups_only_your_messages"] == 1  # the left chat is not counted


def test_a_stray_result_json_does_not_stop_the_other_exports(tmp_path):
    _write_export(tmp_path / "all" / "DataExport_1", _full_export())
    stray = tmp_path / "all" / "other-tool" / "result.json"
    stray.parent.mkdir(parents=True)
    stray.write_text('{"score": 1}')
    s = L0.run_import([tmp_path / "all"])
    assert s["files_imported"] == 1 and s["messages_new"] == 13
    assert len(s["files_not_read"]) == 1 and "not a Telegram" in s["files_not_read"][0]


def test_dry_run_writes_nothing(tmp_path):
    s = _import(tmp_path, dry_run=True)
    assert s["dry_run"] and s["messages_new"] == 13
    assert not tg.raw_dir().exists() and not tg.summary_path().exists()


def test_single_chat_export_infers_you(tmp_path):
    single = _full_export()["chats"]["list"][0]
    s = _import(tmp_path, single)
    assert s["chats"] == 1
    me = json.loads(tg.me_path().read_text())
    assert me == {"user_id": str(ME_ID), "how": "inferred from a single personal chat"}


def test_html_export_is_one_clear_error(tmp_path):
    folder = tmp_path / "html-export"
    folder.mkdir()
    (folder / "export_results.html").write_text("<html></html>")
    with pytest.raises(tg.TelegramError, match="HTML export only"):
        L0.run_import([folder])


def test_not_a_telegram_export_is_one_clear_error(tmp_path):
    f = tmp_path / "x" / "result.json"
    f.parent.mkdir()
    f.write_text('{"hello": 1}')
    with pytest.raises(tg.TelegramError, match="not a Telegram Desktop JSON export"):
        L0.run_import([f])
    f.write_text('{"chats": ')
    with pytest.raises(tg.TelegramError, match="not valid JSON"):
        L0.run_import([f], force=True)


def test_default_folder_is_searched(tmp_path):
    _write_export(tg.exports_dir() / "DataExport_2026-11-25", _full_export())
    assert L0.main([]) == 0


# --- L1 enrich ----------------------------------------------------------------------------


def _l1(tmp_path, data=None):
    _import(tmp_path, data)
    contacts, interactions, stats = L1.build_rows(now=NOW)
    L1.write_outputs(contacts, interactions)
    return (
        pd.read_parquet(tg.contacts_path()),
        pd.read_parquet(tg.interactions_path()),
        stats,
    )


def test_l1_contacts_with_phone_and_you_left_out(tmp_path):
    c, _, stats = _l1(tmp_path)
    assert list(c.columns) == tg.CONTACT_COLUMNS
    rows = {r.name: r for r in c.itertuples(index=False)}
    assert set(rows) == {"Nora Quinn", "Leo Park"}  # the left chat holds only your messages
    assert rows["Nora Quinn"].phone == "+44 7700 900123"  # by user id
    assert rows["Leo Park"].phone == "+44 7700 900456"  # by unique full name
    # Nora: 3 days in the personal chat (2024-03-01, 2026-11-20, 2026-11-21) + 1 group day
    assert rows["Nora Quinn"].interactions == 4
    assert rows["Nora Quinn"].first_seen.startswith("2024-03-01")
    assert rows["Nora Quinn"].last_seen.startswith("2026-11-21")
    assert (c["email"] == "").all() and (c["source"] == "telegram").all()
    assert stats["self"].startswith("user id from the personal_information")
    assert stats["chats_skipped_type"] == 3  # bot, channel, saved messages


def test_l1_conversation_day_rows(tmp_path):
    _, i, _ = _l1(tmp_path)
    assert list(i.columns) == tg.INTERACTION_COLUMNS
    days = i[~i["title"].str.startswith("Promise")]
    assert set(days["kind"]) == {"message"} and set(days["status"]) == {"done"}
    nov20 = days[days["ts"].str.startswith("2026-11-20")].iloc[0]
    assert nov20["title"] == "Telegram chat with Nora Quinn, 3 messages"
    assert nov20["participants"] == "Nora Quinn" and nov20["owner_role"] == "author"
    assert "09:05 Alex Demo: Sure. I'll send you the deck tomorrow." in nov20["text"]
    assert "Nora Quinn: [call, 120 s]" in nov20["text"]
    nov21 = days[days["ts"].str.startswith("2026-11-21")].iloc[0]
    assert nov21["owner_role"] == "attendee" and "[voice_message]" in nov21["text"]
    group = days[days["title"].str.startswith("Telegram group Project Alpha")].iloc[0]
    assert set(group["participants"].split("|||")) == {"Leo Park", "Nora Quinn"}
    assert "create_group" not in group["text"]


def test_l1_conference_call_is_a_call(tmp_path):
    data = _full_export()
    data["chats"]["list"][0]["messages"].append(
        {
            "id": 7,
            "type": "service",
            "date": "2026-11-23T10:00:00",
            "date_unixtime": str(int(datetime(2026, 11, 23, 10, tzinfo=UTC).timestamp())),
            "actor": "Nora Quinn",
            "actor_id": f"user{NORA_ID}",
            "action": "conference_call",
            "duration_seconds": 60,
        }
    )
    _, i, _ = _l1(tmp_path, data)
    nov23 = i[i["ts"].str.startswith("2026-11-23")].iloc[0]
    assert "Nora Quinn: [call, 60 s]" in nov23["text"]


def test_l1_promises(tmp_path):
    _, i, stats = _l1(tmp_path)
    p = i[i["title"].str.startswith("Promise")].set_index("title")
    deck = p.loc["Promise: I'll send you the deck tomorrow."]
    assert deck["owner_role"] == "assignee" and deck["due"].startswith("2026-11-21")
    assert deck["status"] == "open" and deck["participants"] == "Nora Quinn"
    budget = p.loc["Promise: Ci penso io, entro venerdì."]
    assert budget["participants"] == "Leo Park"  # the message you replied to
    assert budget["due"].startswith("2026-11-20")
    old = p.loc["Promise: I will call you on Friday"]
    assert old["owner_role"] == "other" and old["status"] == "closed"
    assert stats["promises"] == 3 and stats["promises_open"] == 2


def test_l1_promises_can_be_turned_off(tmp_path):
    sbk_config._USER_CFG = {"telegram": {"detect_promises": False}}
    _, i, stats = _l1(tmp_path)
    assert not i["title"].str.startswith("Promise").any() and stats.get("promises", 0) == 0


def test_l1_large_group_members_get_no_contact_row(tmp_path):
    sbk_config._USER_CFG = {"telegram": {"group_contacts_max_senders": 1}}
    c, i, stats = _l1(tmp_path)
    names = set(c["name"])
    assert "Leo Park" not in names and "Nora Quinn" in names  # Nora also has a personal chat
    assert stats["groups_over_sender_limit"] == 1
    assert i["participants"].str.contains("Leo Park").any()


def test_l1_chat_types_and_exclusions_are_configurable(tmp_path):
    sbk_config._USER_CFG = {
        "telegram": {"chat_types": ["personal_chat", "bot_chat"], "exclude_chats": ["Weather Bot"]}
    }
    c, _, stats = _l1(tmp_path)
    assert set(c["name"]) == {"Nora Quinn"} and stats["chats_excluded"] == 1


def test_l1_falls_back_to_own_names_without_an_id(tmp_path):
    data = _full_export()
    del data["personal_information"]
    c, i, stats = _l1(tmp_path, data)
    assert "Alex Demo" not in set(c["name"])
    assert stats["self"] == "owner / own_names of sbk.config.json"
    assert "Alex Demo" not in "|||".join(i["participants"])


def test_kernel_intake_reader_accepts_the_files(tmp_path):
    import plugin_intake

    _l1(tmp_path)
    root = sbk_config.DATA_ROOT
    assert plugin_intake.contact_files(root) == [tg.contacts_path()]
    people = plugin_intake.load_people(root)
    assert not people[plugin_intake.FROM_PARTICIPANTS].any()  # every participant has a row
    events = plugin_intake.load_interactions(root)
    commitments = [
        r.title for r in events.itertuples(index=False) if plugin_intake.is_commitment(r)
    ]
    assert sorted(commitments) == [
        "Promise: Ci penso io, entro venerdì.",
        "Promise: I'll send you the deck tomorrow.",
    ]


# --- command line -------------------------------------------------------------------------


def _run(script, *args, tmp=None):
    env = dict(os.environ)
    cfg = tmp / "owner-only.json"
    cfg.write_text(
        json.dumps({"owner": "Alex Demo", "own_emails": ["alex@personal.example"]}),
        encoding="utf-8",
    )
    env.update({"SBK_CONTAINERIZED": "1", "SBK_DATA_ROOT": str(tmp / "d"), "SBK_CONFIG": str(cfg)})
    return subprocess.run(
        [sys.executable, str(TELEGRAM / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp),
        timeout=120,
    )


@pytest.mark.parametrize("script", ["tg-l0-import.py", "tg-l1-enrich.py"])
def test_help_without_traceback(script, tmp_path):
    r = _run(script, "--help", tmp=tmp_path)
    assert r.returncode == 0 and "usage" in r.stdout and "Traceback" not in r.stderr


@pytest.mark.parametrize(
    ("script", "args", "start"),
    [
        ("tg-l0-import.py", (), "Telegram: no export found"),
        ("tg-l0-import.py", ("missing-folder",), "Telegram: no such file or folder"),
        ("tg-l1-enrich.py", (), "Telegram: nothing imported yet"),
    ],
)
def test_nothing_to_read_is_one_clear_line(script, args, start, tmp_path):
    r = _run(script, *args, tmp=tmp_path)
    lines = [x for x in r.stderr.splitlines() if x.strip()]
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert len(lines) == 1 and lines[0].startswith(start), r.stderr


def test_cli_end_to_end_in_subprocesses(tmp_path):
    _write_export(tmp_path / "export", _full_export())
    r0 = _run("tg-l0-import.py", str(tmp_path / "export"), tmp=tmp_path)
    assert r0.returncode == 0 and "13 new messages" in r0.stdout, r0.stderr
    r1 = _run("tg-l1-enrich.py", tmp=tmp_path)
    assert r1.returncode == 0 and "2 contacts (2 with phone)" in r1.stdout, r1.stderr
    assert (tmp_path / "d" / "telegram" / "processed" / "plugin-interactions.parquet").exists()
