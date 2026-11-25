#!/usr/bin/env python3
"""Search one of your Gmail mailboxes (its own login) and print matching messages.

Usage: gsearch.py <mailbox label or address> "<gmail query>" [max results] [--full]
"""

import base64
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import google_oauth  # noqa: E402


def svc(mailbox):
    return google_oauth.gmail_service(mailbox)


def hdr(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def body(msg):
    out = []

    def walk(p):
        if p.get("mimeType", "").startswith("text/") and p.get("body", {}).get("data"):
            out.append(base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8", "replace"))
        for sp in p.get("parts", []) or []:
            walk(sp)

    walk(msg.get("payload", {}))
    return "\n".join(out)


if __name__ == "__main__":
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--help" in sys.argv or "-h" in sys.argv or len(pos) < 2:
        print(__doc__.strip())
        sys.exit(0 if ("--help" in sys.argv or "-h" in sys.argv) else 2)
    sub, q = pos[0], pos[1]
    n = int(pos[2]) if len(pos) > 2 else 10
    full = "--full" in sys.argv
    s = svc(sub)
    r = s.users().messages().list(userId="me", q=q, maxResults=n, includeSpamTrash=True).execute()
    msgs = r.get("messages", [])
    print(f"### {sub} | q={q!r} | {len(msgs)} results")
    for m in msgs:
        d = s.users().messages().get(userId="me", id=m["id"], format="full").execute()
        print("-" * 70)
        print("DATE:", hdr(d, "Date"))
        print("FROM:", hdr(d, "From"))
        print("TO:  ", hdr(d, "To"))
        print("SUBJ:", hdr(d, "Subject"))
        print("ID:  ", m["id"], "| thread:", d.get("threadId"))
        if full:
            print("---- BODY ----")
            print(body(d)[:6000])
        else:
            print("SNIP:", d.get("snippet", "")[:300])
