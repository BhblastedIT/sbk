#!/usr/bin/env python3
"""Send a Slack message to channels or people (DM), through your own Slack app.

Token: the optional bot token of your app (Keychain sbk-slack/bot-token or
SLACK_BOT_TOKEN; Bot Token Scopes chat:write, im:write, users:read.email), so the
message comes from the app. Without it the message goes out as you, with your
user token (Keychain sbk-slack/user-token or SLACK_USER_TOKEN), which then needs
the chat:write user scope (users:read.email for --dm by email).
"""

















import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import slack_auth  # noqa: E402

API = "https://slack.com/api/"


def _token():
    """The optional bot token of your app, otherwise your user token."""
    return slack_auth.notify_token()


def _call(method, token, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        API + method,
        data=data,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _resolve_user_by_email(token, email):
    q = "?email=" + urllib.parse.quote(email)
    req = urllib.request.Request(
        API + "users.lookupByEmail" + q, headers={"Authorization": "Bearer " + token}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = json.loads(resp.read().decode())
        return d.get("user", {}).get("id") if d.get("ok") else None
    except Exception:
        return None


def _open_dm(token, user_id):
    d = _call("conversations.open", token, {"users": user_id})
    return d.get("channel", {}).get("id") if d.get("ok") else None


def notify(text="", channels=None, dm_emails=None, dm_user_ids=None, blocks=None, token=None):
    """Send `text` to each channel, each email (as a DM) and each user id (as a DM)."""
    token = token or _token()
    if not token:
        return {
            "ok": False,
            "error": "no_token",
            "detail": (
                "No Slack token: your user token (Keychain sbk-slack/user-token or "
                "SLACK_USER_TOKEN, with the chat:write user scope) or the optional bot token "
                "of the same app (Keychain sbk-slack/bot-token or SLACK_BOT_TOKEN)"
            ),
        }
    report = {"ok": True, "sent": [], "failed": []}
    targets = []
    for ch in channels or []:
        targets.append(("channel", ch))
    for em in dm_emails or []:
        uid = _resolve_user_by_email(token, em)
        if uid:
            dm = _open_dm(token, uid)
            targets.append(("dm:" + em, dm)) if dm else report["failed"].append(
                {"target": em, "error": "dm_open_failed"}
            )
        else:
            report["failed"].append({"target": em, "error": "user_not_found"})
    for uid in dm_user_ids or []:
        dm = _open_dm(token, uid)
        targets.append(("dm:" + uid, dm)) if dm else report["failed"].append(
            {"target": uid, "error": "dm_open_failed"}
        )

    for label, chan in targets:
        if not chan:
            continue
        payload = {"channel": chan, "text": text or " "}
        if blocks:
            payload["blocks"] = blocks
        d = _call("chat.postMessage", token, payload)
        if d.get("ok"):
            report["sent"].append({"target": label, "ts": d.get("ts")})
        else:
            report["failed"].append({"target": label, "error": d.get("error")})
    report["ok"] = len(report["failed"]) == 0
    return report


def main():
    ap = argparse.ArgumentParser(
        description="Send a Slack message through your own Slack app (see the module docstring)."
    )
    ap.add_argument(
        "--channel", action="append", default=[], help="#name or channel id C... (repeatable)"
    )
    ap.add_argument("--dm", action="append", default=[], help="email of a DM recipient (repeatable)")
    ap.add_argument("--dm-user", action="append", default=[], help="user id for a DM (repeatable)")
    ap.add_argument("--text", required=True, help="the message text")
    a = ap.parse_args()
    rep = notify(text=a.text, channels=a.channel, dm_emails=a.dm, dm_user_ids=a.dm_user)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    sys.exit(0 if rep.get("ok") else 1)


if __name__ == "__main__":
    main()
