""









from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("sbk-connection-checker")

_TIMEOUT = 5


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _check_env(var_name: str) -> dict:
    ""
    val = os.environ.get(var_name, "")
    if val:
        return {"status": "ok", "detail": f"{var_name} configured"}
    return {"status": "error", "detail": f"{var_name} not set"}


def _check_firecrawl() -> dict:
    ""
    import requests

    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "FIRECRAWL_API_KEY not set", "credits": None}
    try:
        resp = requests.get(
            "https://api.firecrawl.dev/v1/team/credits",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            remaining = data.get("remaining_credits") or data.get("credits")
            return {
                "status": "ok",
                "detail": f"{remaining} credits remaining"
                if remaining is not None
                else "Connected",
                "credits": remaining,
            }
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}", "credits": None}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100], "credits": None}


def _check_deepseek() -> dict:
    ""
    import requests

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "DEEPSEEK_API_KEY not set", "credits": None}
    try:
        resp = requests.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            balances = data.get("balance_infos", [])
            total = None
            if balances:
                total = sum(float(b.get("total_balance", 0)) for b in balances)
            return {
                "status": "ok",
                "detail": f"${total:.2f} balance" if total is not None else "Connected",
                "credits": total,
            }
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}", "credits": None}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100], "credits": None}


def _check_exa() -> dict:
    ""
    import requests

    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "EXA_API_KEY not set", "credits": None}
    try:

        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": "test", "numResults": 1},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return {"status": "ok", "detail": "API key valid", "credits": None}
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}", "credits": None}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100], "credits": None}


def _check_slack() -> dict:
    """Your personal Slack app's user token (Keychain sbk-slack/user-token or SLACK_USER_TOKEN)."""
    import sys
    from pathlib import Path

    import requests

    tools_dir = Path(__file__).resolve().parent.parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import slack_auth

    token = slack_auth.user_token()
    if not token:
        return {
            "status": "error",
            "detail": "No Slack user token (Keychain sbk-slack/user-token or SLACK_USER_TOKEN)",
        }
    try:
        resp = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
        data = resp.json()
        if data.get("ok"):
            return {
                "status": "ok",
                "detail": f"Workspace: {data.get('team', 'unknown')} (user token)",
            }
        return {"status": "error", "detail": data.get("error", "auth failed")}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}


def _check_gmail() -> dict:
    ""
    try:
        import keyring

        token = keyring.get_password("sbk-gmail", "access_token")
        if token:
            return {"status": "ok", "detail": "OAuth token in Keychain"}
        return {"status": "degraded", "detail": "No OAuth token found"}
    except Exception:
        return {"status": "degraded", "detail": "Keychain check failed"}


def _check_attio() -> dict:
    ""
    import requests

    api_key = os.environ.get("ATTIO_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "ATTIO_API_KEY not set"}
    try:
        resp = requests.get(
            "https://api.attio.com/v2/self",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return {"status": "ok", "detail": "Connected"}
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}


def _check_notion() -> dict:
    ""
    import requests

    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return {"status": "error", "detail": "NOTION_TOKEN not set"}
    try:
        resp = requests.get(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return {"status": "ok", "detail": "Connected"}
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}


def _check_github() -> dict:
    ""
    import requests

    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"status": "error", "detail": "GITHUB_TOKEN not set"}
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            user = resp.json().get("login", "unknown")
            return {"status": "ok", "detail": f"User: {user}"}
        return {"status": "degraded", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}



_SERVICES = [

    ("Firecrawl", _check_firecrawl, "billing"),
    ("DeepSeek", _check_deepseek, "billing"),
    ("Exa", _check_exa, "billing"),

    ("Slack", _check_slack, "health"),
    ("Gmail", _check_gmail, "health"),
    ("Attio", _check_attio, "health"),
    ("Notion", _check_notion, "health"),
    ("GitHub", _check_github, "health"),

    ("Anthropic", lambda: _check_env("ANTHROPIC_API_KEY"), "config"),
    ("Perplexity", lambda: _check_env("PERPLEXITY_API_KEY"), "config"),
    ("Manus", lambda: _check_env("MANUS_MCP_API_KEY"), "config"),
    ("Google Maps", lambda: _check_env("GOOGLE_MAPS_API_KEY"), "config"),
]


def check_all_connections() -> list[dict]:
    ""









    results = []
    check_time = _now_iso()

    for service_name, check_fn, category in _SERVICES:
        try:
            result = check_fn()
            results.append(
                {
                    "service": service_name,
                    "status": result.get("status", "unchecked"),
                    "detail": result.get("detail", ""),
                    "credits": result.get("credits"),
                    "category": category,
                    "last_check": check_time,
                }
            )
        except Exception as e:
            log.warning("Connection check failed for %s: %s", service_name, e)
            results.append(
                {
                    "service": service_name,
                    "status": "error",
                    "detail": f"Check failed: {str(e)[:80]}",
                    "credits": None,
                    "category": category,
                    "last_check": check_time,
                }
            )

    return results
