"""Slack credentials for every SBK script, in one place.

SBK talks to Slack through your own Slack app, installed in your workspace:

- the **user token** (``xoxp-...``) is the one credential SBK needs. It reads
  what your account can see and it is what the download, the monitor and the
  health check use. Keychain ``sbk-slack`` / ``user-token``, or
  ``SLACK_USER_TOKEN`` (``SBK_SLACK_USER_TOKEN``) in ``.env``.
- a **bot token** (``xoxb-...``) of the same app is an optional extra, used only
  to send notifications (alerts, the dashboard "send" box,
  ``tools/notify/slack_notify.py``) as the app instead of as you. Keychain
  ``sbk-slack`` / ``bot-token``, or ``SLACK_BOT_TOKEN`` (``SBK_SLACK_BOT_TOKEN``).
  Without it, notifications go out with the user token, which then needs the
  ``chat:write`` user scope.

Your workspace and your own Slack user id come from Slack itself
(``auth.test`` on the user token). ``slack.own_user_id`` in sbk.config.json
overrides the user id if you want it fixed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from secrets_adapter import get_secret  # noqa: E402

log = logging.getLogger("sbk.slack_auth")

KEYCHAIN_SERVICE = "sbk-slack"
USER_TOKEN_ACCOUNT = "user-token"
BOT_TOKEN_ACCOUNT = "bot-token"
USER_TOKEN_ENV = ("SBK_SLACK_USER_TOKEN", "SLACK_USER_TOKEN")
BOT_TOKEN_ENV = ("SBK_SLACK_BOT_TOKEN", "SLACK_BOT_TOKEN")

# User tokens start with xoxp-; with token rotation on they start with xoxe.xoxp-.
_USER_PREFIXES = ("xoxp-", "xoxe.xoxp-")
_BOT_PREFIXES = ("xoxb-", "xoxe.xoxb-")

USER_TOKEN_HELP = (
    "No Slack user token (xoxp-) found. Put the User OAuth Token of your own Slack app in the "
    "Keychain (service sbk-slack, account user-token) or in .env as SLACK_USER_TOKEN "
    "(docs/CONNECTING.md, slack)."
)

_auth_cache: dict[str, dict] = {}


def _first(
    keychain_account: str, env_vars: tuple[str, ...], prefixes: tuple[str, ...]
) -> str | None:
    try:
        token = get_secret(KEYCHAIN_SERVICE, keychain_account)
    except Exception as e:  # keyring missing or locked: fall back to the environment
        log.debug("Keychain read failed for %s/%s: %s", KEYCHAIN_SERVICE, keychain_account, e)
        token = None
    if token and token.strip().startswith(prefixes):
        return token.strip()
    for var in env_vars:
        token = (os.environ.get(var) or "").strip()
        if token.startswith(prefixes):
            return token
    return None


def user_token() -> str | None:
    """Your user token: Keychain sbk-slack/user-token, then SBK_SLACK_USER_TOKEN, SLACK_USER_TOKEN."""
    return _first(USER_TOKEN_ACCOUNT, USER_TOKEN_ENV, _USER_PREFIXES)


def bot_token() -> str | None:
    """The optional bot token of the same app: Keychain sbk-slack/bot-token, then the env."""
    return _first(BOT_TOKEN_ACCOUNT, BOT_TOKEN_ENV, _BOT_PREFIXES)


def notify_token() -> str | None:
    """Token for sending notifications: the optional bot token, otherwise your user token."""
    return bot_token() or user_token()


def auth_test(token: str, timeout: int = 10) -> dict:
    """auth.test for this token (cached per process). {} when Slack cannot be reached."""
    if not token:
        return {}
    if token in _auth_cache:
        return _auth_cache[token]
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        data=b"",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("Slack auth.test failed: %s", e)
        return {}
    if data.get("ok"):
        _auth_cache[token] = data
    return data


def own_user_id(token: str | None = None) -> str:
    """Your Slack user id: slack.own_user_id in sbk.config.json, else auth.test on your user token."""
    try:
        from sbk_config import user_cfg

        configured = str(user_cfg("slack.own_user_id", "") or "").strip()
    except Exception:
        configured = ""
    if configured:
        return configured
    token = token if token and token.startswith(_USER_PREFIXES) else user_token()
    if not token:
        return ""
    return str(auth_test(token).get("user_id", "") or "")
