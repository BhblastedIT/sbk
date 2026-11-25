#!/usr/bin/env python3
"""Search your Slack workspace with your user token (read only, scope search:read)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def get_token() -> str:
    """Your user token (xoxp-): Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""
    from dotenv import load_dotenv
    from secrets_adapter import get_secret

    load_dotenv(_TOOLS_DIR.parent / ".env", override=True)
    token = get_secret("sbk-slack", "user-token") or ""
    if not token.startswith("xoxp-"):
        token = os.environ.get("SBK_SLACK_USER_TOKEN") or os.environ.get("SLACK_USER_TOKEN") or ""
    if not token.startswith("xoxp-"):
        raise SystemExit(
            "No Slack user token (xoxp-) found: Keychain sbk-slack/user-token or SLACK_USER_TOKEN in .env."
        )
    return token


def search(query: str, count: int) -> dict:
    params = urllib.parse.urlencode({"query": query, "count": count, "sort": "timestamp"})
    req = urllib.request.Request(
        f"https://slack.com/api/search.messages?{params}",
        headers={"Authorization": f"Bearer {get_token()}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", help="Slack query (supports from:@user, in:#channel, after:YYYY-MM-DD)")
    ap.add_argument("--count", type=int, default=20, help="number of results (max 100)")
    ap.add_argument("--after", help="shortcut for after:YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="raw JSON output")
    args = ap.parse_args()

    query = f"{args.query} after:{args.after}" if args.after else args.query
    data = search(query, args.count)

    if not data.get("ok"):
        print(f"Slack error: {data.get('error')}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    matches = data.get("messages", {}).get("matches", [])
    total = data.get("messages", {}).get("total", 0)
    print(f"{total} results in total, showing {len(matches)}\n")
    for m in matches:
        chan = m.get("channel", {}).get("name", "?")
        user = m.get("username") or m.get("user") or "?"
        text = " ".join((m.get("text") or "").split())
        print(f"[{m.get('ts')}] #{chan} <{user}>")
        print(f"  {text[:400]}")
        if m.get("permalink"):
            print(f"  {m['permalink']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
