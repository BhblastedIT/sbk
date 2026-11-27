"""Slack reads only the conversations you are a member of; archived ones only on request.

Mocked Slack API, no network, temporary data root.
"""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CHANNELS = [
    {"id": "C_MEMBER", "name": "team", "is_member": True, "is_archived": False},
    {"id": "C_NOT_MEMBER", "name": "other-dept", "is_member": False, "is_archived": False},
    {"id": "C_ARCHIVED", "name": "old", "is_member": True, "is_archived": True},
    {"id": "D_DM", "is_im": True, "user": "U0DEMO0001"},
]


@pytest.fixture
def sl0(monkeypatch, tmp_path):
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SBK_CONFIG", str(tmp_path / "none.json"))
    import sbk_config

    importlib.reload(sbk_config)
    spec = importlib.util.spec_from_file_location(
        "sl_l0_download_under_test", ROOT / "tools/slack/sl-l0-download.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "API_DELAY", 0)
    yield mod
    sys.modules.pop(spec.name, None)
    monkeypatch.delenv("SBK_DATA_ROOT")
    monkeypatch.delenv("SBK_CONFIG")
    importlib.reload(sbk_config)


def test_listing_asks_users_conversations_never_conversations_list(sl0, monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_api(method, token, params=None, *a, **k):
        calls.append((method, dict(params or {})))
        if params and params.get("types") == "public_channel":
            return {"ok": True, "channels": [CHANNELS[0]], "response_metadata": {}}
        return {"ok": True, "channels": [], "response_metadata": {}}

    monkeypatch.setattr(sl0, "slack_api", fake_api)
    listed = sl0.list_all_conversations("xoxp-1-fake", team_ids=[""])
    assert [c["id"] for c in listed] == ["C_MEMBER"]
    methods = {m for m, _ in calls}
    assert methods == {"users.conversations"}
    assert {p["types"] for _, p in calls} == {"public_channel", "private_channel", "mpim", "im"}


def test_keep_drops_non_member_and_archived_by_default(sl0):
    kept = sl0.keep_your_conversations(CHANNELS)
    assert [c["id"] for c in kept] == ["C_MEMBER", "D_DM"]


def test_keep_includes_archived_only_on_request(sl0):
    kept = sl0.keep_your_conversations(CHANNELS, include_archived=True)
    assert [c["id"] for c in kept] == ["C_MEMBER", "C_ARCHIVED", "D_DM"]
    assert "C_NOT_MEMBER" not in {c["id"] for c in kept}


def test_dry_run_plans_only_your_conversations(sl0, caplog):
    kept = sl0.keep_your_conversations(CHANNELS)
    with caplog.at_level(logging.INFO, logger="slack-dl"):
        stats = sl0.download_incremental("xoxp-1-fake", kept, {}, dry_run=True)
    assert stats["channels_processed"] == 2
    planned = caplog.text
    assert "C_MEMBER" in planned and "D_DM" in planned
    assert "C_NOT_MEMBER" not in planned and "C_ARCHIVED" not in planned


def test_help_names_the_archived_flag(sl0, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sl-l0-download.py", "--help"])
    with pytest.raises(SystemExit) as e:
        sl0.main()
    assert e.value.code == 0
    assert "--include-archived" in capsys.readouterr().out


def test_monitor_lists_only_your_conversations():
    text = (ROOT / "tools/monitoring/sbk-monitor.py").read_text(encoding="utf-8")
    assert '"conversations.list"' not in text
    assert '"users.conversations"' in text
