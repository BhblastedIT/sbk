#!/usr/bin/env python3
"""Follow-up reminder: warn when a sent mail has had no reply after N days."""


























from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import google_oauth  # noqa: E402

STATE_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or str(Path.home() / ".sbk-data")).expanduser()
    / "state"
    / "followup-watch"
)


def _service(mailbox: str):
    """Gmail client of your mailbox (label or address), from its login made by em-l0-auth.py."""
    return google_oauth.gmail_service(mailbox)


def _newest(svc, query: str) -> dict | None:
    res = svc.users().messages().list(userId="me", q=query, maxResults=5).execute()
    msgs = res.get("messages", [])
    if not msgs:
        return None
    best = None
    for m in msgs:
        full = (
            svc.users()
            .messages()
            .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "Date"])
            .execute()
        )
        ts = int(full.get("internalDate", 0))
        if best is None or ts > best[0]:
            best = (ts, full)
    ts, full = best
    headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
    return {
        "id": full["id"],
        "when": dt.datetime.fromtimestamp(ts / 1000),
        "subject": headers.get("Subject", ""),
    }


def _notify(svc, mailbox: str, notify: str, label: str, sent, days: int) -> str:
    waited = (dt.datetime.now() - sent["when"]).days
    body = (
        f"No reply from {label}.\n\n"
        f"Mail sent on {sent['when']:%Y-%m-%d at %H:%M} with subject \"{sent['subject']}\".\n"
        f"{waited} days have passed (threshold: {days}).\n\n"
        "This message is only an automated reminder.\n"
    )
    msg = MIMEText(body, "plain", _charset="utf-8")
    msg["To"] = notify
    msg["From"] = formataddr(("Follow-up reminder", mailbox))
    msg["Subject"] = f"Reminder: {label} has not replied yet ({waited} days)"
    svc.users().messages().send(
        userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    ).execute()
    return f"notice sent to {notify}"


def _report_outcome(outcome: str, detail: str = "") -> None:
    """Report the run outcome to the optional job-registry hook (never raises)."""

    try:
        from jb_auto import esito

        esito(outcome, detail)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Follow-up reminder for a mail that got no reply")
    p.add_argument(
        "--mailbox", required=True, help="Your mailbox the mail was sent from (label or address)"
    )
    p.add_argument("--to", required=True, help="Recipient whose reply is awaited")
    p.add_argument("--days", type=int, default=20, help="Days to wait before the notice")
    p.add_argument("--notify", help="Where to send the notice (default: the mailbox itself)")
    p.add_argument("--label", default="", help="Readable name used in messages")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status", action="store_true", help="Only print the status")
    a = p.parse_args()

    label = a.label or a.to
    _, address = google_oauth.gmail_label(a.mailbox)
    notify = a.notify or address
    svc = _service(a.mailbox)

    sent = _newest(svc, f"in:sent to:{a.to}")
    if not sent:
        print(json.dumps({"status": "no mail sent to " + a.to}, ensure_ascii=False))
        _report_outcome("nothing", f"no mail sent to {label} yet")
        return 0

    after = int(sent["when"].timestamp())
    reply = _newest(svc, f"from:{a.to} after:{after}")
    waited = (dt.datetime.now() - sent["when"]).days

    state = {
        "label": label,
        "sent": sent["when"].strftime("%Y-%m-%d %H:%M"),
        "subject": sent["subject"],
        "days_elapsed": waited,
        "threshold": a.days,
        "replied": bool(reply),
    }
    if reply:
        state["replied_at"] = reply["when"].strftime("%Y-%m-%d %H:%M")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker = STATE_DIR / (a.to.replace("@", "_at_") + ".json")
    try:
        previous = json.loads(marker.read_text()) if marker.exists() else {}
    except ValueError:
        previous = {}



    already_notified = bool(previous.get("notified")) and previous.get("sent") == state["sent"]

    if a.status:
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return 0

    if reply:
        state["action"] = "none: replied"
    elif waited < a.days:
        state["action"] = f"none: {a.days - waited} days to go"
    elif already_notified:
        state["action"] = "none: notice already sent"
        state["notified"] = True
        state["notified_at"] = previous.get("notified_at")
    elif a.dry_run:
        state["action"] = f"would send the notice to {notify}"
    else:
        state["action"] = _notify(svc, address, notify, label, sent, a.days)
        state["notified"] = True
        state["notified_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    if not a.dry_run:
        marker.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(json.dumps(state, ensure_ascii=False, indent=1))
    if state.get("notified") and not str(state["action"]).startswith("none"):
        _report_outcome("ok", f"{label}: {state['action']}")
    else:
        _report_outcome("nothing", f"{label}: {state['action']}")
    return 0


if __name__ == "__main__":


    import sys as _sys
    from pathlib import Path as _P

    _sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools" / "jobs"))

    def _uscita(_codice) -> None:
        return None

    try:
        from jb_auto import aggancia as _aggancia
        from jb_auto import uscita as _uscita

        _aggancia("com.sbk.followup-watch")
    except Exception:  # noqa: BLE001 -- the registry must never break the job
        pass



    try:
        sys.exit(main())
    except SystemExit as _e:
        _uscita(_e.code)
        raise
