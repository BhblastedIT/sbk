#!/usr/bin/env python3
"""Your own Claude Code login for the app's background sessions, and your consent to use it.

Some features of the macOS app hand work to a Claude Code session that runs in the background:

- a request you dictate or write on the Tasks page (sb_attivita_voce.py);
- Inspiration: understanding a saved idea, the re-read after your answer, the background
  sorting and the backlog re-read (sb_inspiration_azioni.py).

Each session runs `claude -p` on your Mac with YOUR own login: the one the `claude` command
uses in your terminal (your Claude plan, or the ANTHROPIC_API_KEY in your environment). What
the session reads is sent to Claude: the request and your task list, or the saved idea with
its files. Sessions run with `--permission-mode bypassPermissions`, with only the tools each
feature lists and no MCP servers (the Tasks session also has a hook that checks every tool
call, attivita/guardia_voce.py).

They are OFF until you opt in, with one of:

- "app": {"claude_sessions": true} in sbk.config.json
- SBK_APP_CLAUDE=1 in the environment the app starts with (the app does not read .env)

SBK_APP_CLAUDE=0 turns them off even when the config says true. Without consent nothing is
sent: the request stops and says how to turn the sessions on.

Each feature asks for a model by alias (opus for the Tasks requests and for understanding an
idea, haiku for the backlog re-read). If your plan does not include it, set
"app": {"claude_model": "sonnet"} (any alias or model id `claude --model` accepts) and every
session uses that one.

Usage:
    sb_own_claude.py status     print whether sessions are allowed and which `claude` is used
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

CONSENT_ENV = "SBK_APP_CLAUDE"
CONFIG_KEY = "app.claude_sessions"
MODEL_KEY = "app.claude_model"

OFF_MESSAGE = (
    "Claude Code sessions are off. This feature runs a Claude Code session with your own "
    '`claude` login and sends it {what}. To allow it, set "app": {{"claude_sessions": true}} '
    "in sbk.config.json, then try again."
)
MISSING_MESSAGE = (
    "I can't find the `claude` command on this Mac. Install Claude Code and sign in "
    "(run `claude` once in a terminal), or set SB_CLAUDE_CLI to its path."
)


class NotAllowed(Exception):
    """You did not opt in to background Claude Code sessions."""


class ClaudeMissing(Exception):
    """The `claude` command is not installed (or SB_CLAUDE_CLI points nowhere)."""


def _config_value(key: str = CONFIG_KEY):
    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        from sbk_config import user_cfg
    except Exception:  # noqa: BLE001
        return None
    return user_cfg(key, None)


def model(default: str) -> str:
    """The model for a session: "app.claude_model" in sbk.config.json if set, else `default`."""
    chosen = _config_value(MODEL_KEY)
    return str(chosen).strip() if isinstance(chosen, str) and chosen.strip() else default


def allowed() -> bool:
    """True only when you opted in (config "app.claude_sessions": true, or SBK_APP_CLAUDE=1)."""
    env = os.environ.get(CONSENT_ENV, "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in ("1", "true", "yes", "on"):
        return True
    return _config_value() is True


def find_claude() -> str | None:
    """The `claude` command to run: SB_CLAUDE_CLI, then PATH, then the usual install places."""
    chosen = os.environ.get("SB_CLAUDE_CLI")
    if chosen:
        return chosen if (Path(chosen).is_file() or shutil.which(chosen)) else None
    for p in (
        shutil.which("claude"),
        Path.home() / ".local" / "bin" / "claude",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if p and Path(p).exists():
            return str(p)
    return None


def check(what: str = "what the feature works on") -> str:
    """Raise NotAllowed or ClaudeMissing, else return the path of `claude`."""
    if not allowed():
        raise NotAllowed(OFF_MESSAGE.format(what=what))
    path = find_claude()
    if not path:
        raise ClaudeMissing(MISSING_MESSAGE)
    return path


class Session:
    """One background Claude Code session on your own login."""

    account = "own"

    def __init__(self, tool: str):
        self.tool = tool
        self.id = f"{tool}-{uuid.uuid4().hex[:12]}"

    def env(self) -> dict[str, str]:
        """The environment for `claude`: yours, unchanged, so it uses your own login."""
        return dict(os.environ)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def session(tool: str, what: str = "what the feature works on") -> Session:
    """A session for `tool`, after the consent and install checks (see check())."""
    check(what)
    return Session(tool)


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) > 1 and argv[1] != "status":
        print(__doc__, file=sys.stderr)
        return 2
    path = find_claude()
    print(f"claude sessions allowed: {'yes' if allowed() else 'no'} ({CONSENT_ENV} / {CONFIG_KEY})")
    print(f"claude command: {path or 'not found'}")
    print(f"model override ({MODEL_KEY}): {model('') or 'none, each feature uses its own'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
