#!/usr/bin/env python3
"""Create a Gmail draft (or send, when asked) in one of your mailboxes, through its own Gmail login."""




























import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import warnings
from email import charset as email_charset
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

warnings.filterwarnings("ignore")

from pathlib import Path  # noqa: E402

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import google_oauth  # noqa: E402

# The mailbox login made by tools/email/em-l0-auth.py <label> (scope https://mail.google.com/)
# covers drafts and sending.
SCOPE_DRAFT = "https://www.googleapis.com/auth/gmail.modify"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"


_QP_UTF8 = email_charset.Charset("utf-8")
_QP_UTF8.body_encoding = email_charset.QP


def _service(account: str, mailbox: str, scope: str):
    """Gmail client of the mailbox `account` (label or address); `scope` is informative."""
    return google_oauth.gmail_service(account or mailbox)


def _addrs(value: str) -> list:
    """Split a header value into addresses, ignoring commas inside <...>."""
    return [a.strip() for a in re.split(r",(?![^<]*>)", value or "") if a.strip()]


def _email_of(addr: str) -> str:
    m = re.search(r"<([^>]+)>", addr)
    return (m.group(1) if m else addr).strip().lower()


def _reply_context(account: str, mailbox: str, message_id: str) -> dict:
    """Build threading and reply-all context from an existing Gmail message id."""
    svc = _service(account, mailbox, SCOPE_DRAFT)
    d = (
        svc.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Cc", "Subject", "Message-ID", "References"],
        )
        .execute()
    )
    h = {x["name"].lower(): x["value"] for x in d["payload"].get("headers", [])}

    self_addrs = {mailbox.lower()}
    orig_from = h.get("from", "")
    to = [orig_from] if orig_from else []
    seen = {_email_of(a) for a in to} | self_addrs
    cc = []
    for a in _addrs(h.get("to", "")) + _addrs(h.get("cc", "")):
        e = _email_of(a)
        if e and e not in seen:
            seen.add(e)
            cc.append(a)

    subject = h.get("subject", "")
    bare = re.sub(r"^(\s*(re|r|fwd|fw|i)\s*:\s*|\s*\[ext\]\s*)+", "", subject, flags=re.I)
    mid = h.get("message-id", "")
    refs = " ".join(x for x in [h.get("references", ""), mid] if x).strip()

    return {
        "threadId": d.get("threadId"),
        "to": ", ".join(to),
        "cc": ", ".join(cc),
        "subject": f"Re: {bare}" if bare else subject,
        "in_reply_to": mid,
        "references": refs,
    }


def _build_raw(
    mailbox: str,
    to: str,
    cc: str,
    subject: str,
    body: str,
    html: bool,
    in_reply_to: str = "",
    references: str = "",
    attachments: list | None = None,
    from_name: str = "",
    inline: list | None = None,
    text_alt: str = "",
) -> str:
    if html:
        alt = MIMEMultipart("alternative")
        if text_alt:
            alt.attach(MIMEText(text_alt, "plain", _charset=_QP_UTF8))
        alt.attach(MIMEText(body, "html", _charset=_QP_UTF8))
        if inline:


            inner = MIMEMultipart("related")
            inner.attach(alt)
            for path in inline:
                path = os.path.expanduser(path)
                ctype, _ = mimetypes.guess_type(path)
                maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
                with open(path, "rb") as fh:
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(fh.read())
                encoders.encode_base64(part)
                cid = os.path.splitext(os.path.basename(path))[0]
                part.add_header("Content-ID", f"<{cid}>")
                part.add_header("Content-Disposition", "inline", filename=os.path.basename(path))
                inner.attach(part)
        else:
            inner = alt
    else:
        inner = MIMEText(body, "plain", _charset=_QP_UTF8)

    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(inner)
        for path in attachments:
            path = os.path.expanduser(path)
            ctype, _ = mimetypes.guess_type(path)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            with open(path, "rb") as fh:
                part = MIMEBase(maintype, subtype)
                part.set_payload(fh.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=os.path.basename(path))
            msg.attach(part)
    else:
        msg = inner

    msg["From"] = formataddr((from_name, mailbox)) if from_name else mailbox
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject

    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=mailbox.split("@", 1)[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(
    account,
    mailbox,
    to,
    cc,
    subject,
    body,
    html,
    ctx=None,
    attachments=None,
    from_name="",
    inline=None,
    text_alt="",
):
    svc = _service(account, mailbox, SCOPE_DRAFT)
    ctx = ctx or {}
    raw = _build_raw(
        mailbox,
        to,
        cc,
        subject,
        body,
        html,
        ctx.get("in_reply_to", ""),
        ctx.get("references", ""),
        attachments,
        from_name,
        inline,
        text_alt,
    )
    message = {"raw": raw}
    if ctx.get("threadId"):
        message["threadId"] = ctx["threadId"]
    draft = svc.users().drafts().create(userId="me", body={"message": message}).execute()
    return {
        "id": draft.get("id"),
        "threadId": draft.get("message", {}).get("threadId"),
        "mode": "draft",
        "mailbox": mailbox,
    }


def send_message(
    account,
    mailbox,
    to,
    cc,
    subject,
    body,
    html,
    ctx=None,
    attachments=None,
    from_name="",
    inline=None,
    text_alt="",
):
    svc = _service(account, mailbox, SCOPE_SEND)
    ctx = ctx or {}
    raw = _build_raw(
        mailbox,
        to,
        cc,
        subject,
        body,
        html,
        ctx.get("in_reply_to", ""),
        ctx.get("references", ""),
        attachments,
        from_name,
        inline,
        text_alt,
    )
    payload = {"raw": raw}
    if ctx.get("threadId"):
        payload["threadId"] = ctx["threadId"]
    sent = svc.users().messages().send(userId="me", body=payload).execute()
    return {
        "id": sent.get("id"),
        "threadId": sent.get("threadId"),
        "mode": "sent",
        "mailbox": mailbox,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Create a Gmail draft in one of your mailboxes (default: draft, no send)"
    )
    p.add_argument("--to", help="Recipient(s), comma-separated. Optional with --reply-to")
    p.add_argument("--cc", default="", help="CC, comma-separated. Optional with --reply-to")
    p.add_argument("--subject", help="Subject. Optional with --reply-to")
    p.add_argument(
        "--reply-to",
        dest="reply_to",
        help="Gmail messageId to reply to: automatic threading + reply-all",
    )
    p.add_argument(
        "--no-reply-all",
        action="store_true",
        help="With --reply-to: reply only to the sender, without the others in Cc",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body-file", help="Path to a file with the body")
    g.add_argument("--body", help="Inline body")
    p.add_argument("--html", action="store_true", help="Body is HTML")
    p.add_argument(
        "--account",
        required=True,
        help="Your mailbox: its label (e.g. work) or its address, as signed in with em-l0-auth.py",
    )
    p.add_argument(
        "--from-name",
        dest="from_name",
        default="",
        help='Display name in From, e.g. "Alex Demo" (default: bare address)',
    )
    p.add_argument("--send", action="store_true", help="SEND instead of creating a draft (guarded)")
    p.add_argument(
        "--attach",
        action="append",
        default=[],
        help="Path of a file to attach (repeatable)",
    )
    p.add_argument(
        "--inline",
        action="append",
        default=[],
        help='Inline image (repeatable, --html only): in the HTML use <img src="cid:filename-without-extension">',
    )
    p.add_argument(
        "--text-file",
        dest="text_file",
        help="With --html: file with the plain-text alternative (recommended)",
    )
    args = p.parse_args()

    label, mailbox = google_oauth.gmail_label(args.account)
    if not mailbox:
        print(f"No address stored for '{label}' in emails/accounts.json", file=sys.stderr)
        return 2

    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    else:
        body = args.body
    text_alt = ""
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as fh:
            text_alt = fh.read()
    if args.inline and not args.html:
        print("--inline requires --html", file=sys.stderr)
        return 2

    ctx = None
    to, cc, subject = args.to, args.cc, args.subject
    if args.reply_to:
        try:
            ctx = _reply_context(label, mailbox, args.reply_to)
        except Exception as e:
            print(json.dumps({"error": f"reply-to not resolved: {str(e)[:300]}"}), file=sys.stderr)
            return 1
        to = to or ctx["to"]
        cc = cc or ("" if args.no_reply_all else ctx["cc"])
        subject = subject or ctx["subject"]

    if not to or not subject:
        print("--to and --subject are required (or --reply-to)", file=sys.stderr)
        return 2

    try:
        if args.send:
            out = send_message(
                label,
                mailbox,
                to,
                cc,
                subject,
                body,
                args.html,
                ctx,
                args.attach,
                args.from_name,
                args.inline,
                text_alt,
            )
        else:
            out = create_draft(
                label,
                mailbox,
                to,
                cc,
                subject,
                body,
                args.html,
                ctx,
                args.attach,
                args.from_name,
                args.inline,
                text_alt,
            )
    except Exception as e:
        print(json.dumps({"error": str(e)[:400]}), file=sys.stderr)
        return 1

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
