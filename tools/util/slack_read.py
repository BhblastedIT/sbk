#!/usr/bin/env python3
""











from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import slack_auth  # noqa: E402

# The workspace is the one your user token belongs to (auth.test): no team id is set or sent.
METODI_LETTURA = {
    "conversations.list",
    "conversations.history",
    "conversations.replies",
    "conversations.info",
    "users.info",
    "users.list",
}

_CACHE_UTENTI: dict[str, str] = {}


def token() -> str:
    """Your user token: Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""
    t = slack_auth.user_token()
    if not t:
        raise SystemExit(slack_auth.USER_TOKEN_HELP)
    return t


def api(metodo: str, **params) -> dict:
    if metodo not in METODI_LETTURA:
        raise SystemExit(f"method not allowed (read-only): {metodo}")
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        f"https://slack.com/api/{metodo}?{qs}",
        headers={"Authorization": f"Bearer {token()}"},
    )
    for tentativo in range(5):
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if data.get("ok"):
            return data
        if data.get("error") == "ratelimited":
            time.sleep(3 * (tentativo + 1))
            continue
        raise SystemExit(f"{metodo}: {data.get('error')}")
    raise SystemExit(f"{metodo}: ratelimited")


def nome_utente(uid: str) -> str:
    if not uid:
        return ""
    if uid not in _CACHE_UTENTI:
        try:
            u = api("users.info", user=uid)["user"]
            p = u.get("profile", {})
            _CACHE_UTENTI[uid] = p.get("display_name") or p.get("real_name") or u.get("name") or uid
        except SystemExit:
            _CACHE_UTENTI[uid] = uid
    return _CACHE_UTENTI[uid]


def quando(ts: str) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).strftime("%Y-%m-%d %H:%M")


def stampa_messaggi(msgs: list[dict], canale: str) -> None:
    for m in sorted(msgs, key=lambda x: float(x.get("ts", 0))):
        autore = nome_utente(m.get("user") or m.get("bot_id", ""))
        testo = (m.get("text") or "").replace("\n", "\n      ")
        extra = ""
        if m.get("reply_count"):
            extra = f"  [thread: {m['reply_count']} replies, ts={m['ts']}]"
        for f in m.get("files", []) or []:
            extra += (
                f"\n      [file] {f.get('name')} ({f.get('filetype')}) {f.get('permalink', '')}"
            )
        for a in m.get("attachments", []) or []:
            if a.get("title") or a.get("text"):
                extra += f"\n      [attachment] {a.get('title', '')} — {(a.get('text') or '')[:300]}"
        print(f"\n[{quando(m['ts'])}] {autore}{extra}\n      {testo}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Slack reading (read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("canali")
    c.add_argument("--filtro", default="")
    c.add_argument("--tipi", default="public_channel,private_channel,mpim,im")
    h = sub.add_parser("storia")
    h.add_argument("canale")
    h.add_argument("--n", type=int, default=100)
    h.add_argument("--oldest", default=None)
    t = sub.add_parser("thread")
    t.add_argument("canale")
    t.add_argument("ts")
    u = sub.add_parser("utente")
    u.add_argument("uid")
    args = ap.parse_args()

    if args.cmd == "canali":
        cursor, trovati = None, 0
        while True:
            d = api(
                "conversations.list",
                types=args.tipi,
                limit=1000,
                cursor=cursor,
                exclude_archived="true",
            )
            for ch in d.get("channels", []):
                nome = ch.get("name") or ""
                if ch.get("is_im"):
                    nome = f"DM with {nome_utente(ch.get('user', ''))}"
                if args.filtro.lower() in nome.lower():
                    print(f"{ch['id']:<13} {nome}")
                    trovati += 1
            cursor = d.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        print(f"\n({trovati} matches)", file=sys.stderr)
    elif args.cmd == "storia":
        d = api("conversations.history", channel=args.canale, limit=args.n, oldest=args.oldest)
        stampa_messaggi(d.get("messages", []), args.canale)
    elif args.cmd == "thread":
        d = api("conversations.replies", channel=args.canale, ts=args.ts, limit=200)
        stampa_messaggi(d.get("messages", []), args.canale)
    elif args.cmd == "utente":
        u = api("users.info", user=args.uid)["user"]
        p = u.get("profile", {})
        print(
            json.dumps(
                {
                    "id": u["id"],
                    "name": u.get("name"),
                    "real_name": p.get("real_name"),
                    "title": p.get("title"),
                    "email": p.get("email"),
                },
                indent=1,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
