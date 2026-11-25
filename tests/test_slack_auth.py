"""Slack reads only the personal app's user token; no browser token, no hard-coded ids."""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Fake values shaped like Slack tokens, never real ones.
USER = "xoxp-1-fake-user"
BOT = "xoxb-1-fake-bot"
BROWSER = "xoxc-1-fake-browser"


@pytest.fixture
def sa(monkeypatch):
    import slack_auth

    slack_auth = importlib.reload(slack_auth)
    for var in slack_auth.USER_TOKEN_ENV + slack_auth.BOT_TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(slack_auth, "get_secret", lambda s, a: store.get((s, a)))
    slack_auth._store = store
    return slack_auth


def test_user_token_keychain_first(sa, monkeypatch):
    sa._store[("sbk-slack", "user-token")] = USER
    monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-2-other")
    assert sa.user_token() == USER


def test_user_token_from_env(sa, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN", USER)
    assert sa.user_token() == USER


def test_user_token_rejects_browser_and_bot_tokens(sa, monkeypatch):
    sa._store[("sbk-slack", "user-token")] = BROWSER
    monkeypatch.setenv("SLACK_USER_TOKEN", BOT)
    assert sa.user_token() is None


def test_notify_token_prefers_optional_bot(sa, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN", USER)
    assert sa.notify_token() == USER
    monkeypatch.setenv("SLACK_BOT_TOKEN", BOT)
    assert sa.notify_token() == BOT


def test_own_user_id_from_config(sa, monkeypatch, tmp_path):
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text('{"slack": {"own_user_id": "U0DEMO0001"}}', encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    import sbk_config

    importlib.reload(sbk_config)
    try:
        assert sa.own_user_id() == "U0DEMO0001"
    finally:
        monkeypatch.delenv("SBK_CONFIG")
        importlib.reload(sbk_config)


def test_own_user_id_from_auth_test(sa, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN", USER)
    monkeypatch.setattr(sa, "auth_test", lambda t: {"ok": True, "user_id": "U0DEMO0002"})
    assert sa.own_user_id() == "U0DEMO0002"


def test_own_user_id_empty_without_token(sa, monkeypatch):
    monkeypatch.setattr(sa, "auth_test", lambda t: pytest.fail("no token, no call"))
    assert sa.own_user_id() == ""


SLACK_FILES = [
    "tools/monitoring/sbk-monitor.py",
    "tools/monitoring/connection_checker.py",
    "tools/monitoring/slack_alerter.py",
    "tools/notify/slack_notify.py",
    "tools/util/slack_read.py",
    "dashboard/app/api/slack_msg.py",
    "tools/slack/sl-l0-download.py",
    "tools/slack/sl-l0-channel-index.py",
    "tools/slack/sl-realtime.py",
]


@pytest.mark.parametrize("rel", SLACK_FILES)
def test_no_browser_token_or_hardcoded_ids(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "xoxc" not in text
    assert "osascript" not in text
    assert "boot_data" not in text
    assert "api-token" not in text
    assert not re.search(r"\b[TU]000[A-Z0-9]{6,}\b", text), "demo Slack ids must come from config"
    # no team id constant sent to Slack (an org-level parameter); data fields named team_id are fine
    assert not re.search(
        r"""\["team_id"\]\s*=|team_id\s*=\s*[A-Z_]{3,}\b|"team_id":\s*[A-Z_]{3,}\b""", text
    )
