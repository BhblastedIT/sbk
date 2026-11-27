#!/usr/bin/env python3
"""Daily briefing: today's calendar, the emails waiting for your reply, the follow-ups and the focus items, sent to
you on Slack once a day (--preview or --dry-run to only look at it).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path


_TOOLS_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _TOOLS_DIR.parent
_XS_DIR = _TOOLS_DIR / "cross-source"
_DASHBOARD_DIR = _PROJECT_ROOT / "dashboard"

for p in (_TOOLS_DIR, _XS_DIR, str(_DASHBOARD_DIR)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env", override=True)

from sbk_config import DATA_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
log = logging.getLogger("br-daily-briefing")


BRIEFING_LOG_DIR = DATA_ROOT / "briefings"





def _briefing_log_path(d: date | None = None) -> Path:
    d = d or date.today()
    return BRIEFING_LOG_DIR / f"briefing-{d.isoformat()}.json"


def _already_sent(d: date | None = None) -> bool:
    ""
    path = _briefing_log_path(d)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("sent", False)
    except (json.JSONDecodeError, OSError):
        return False


def _log_briefing(briefing_data: dict) -> None:
    ""
    BRIEFING_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _briefing_log_path()
    path.write_text(json.dumps(briefing_data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Briefing log saved: %s", path)





def _collect_calendar_events(bridge) -> list[dict]:
    ""
    events = []
    try:
        cal_events = bridge._data.calendar_events or []
        today_str = date.today().isoformat()
        for ev in cal_events:
            start = ev.get("start", {})
            start_str = (
                start.get("dateTime", start.get("date", "")) if isinstance(start, dict) else ""
            )
            if not start_str:
                continue

            if today_str not in start_str[:10]:
                continue
            summary = str(ev.get("summary", ""))[:80]
            attendees = ev.get("attendees", [])
            time_part = ""
            if "T" in start_str:
                time_part = start_str.split("T")[1][:5]
            events.append(
                {
                    "time": time_part,
                    "summary": summary,
                    "attendees": len(attendees),
                }
            )
        events.sort(key=lambda x: x.get("time", ""))
    except Exception as e:
        log.warning("Calendar collection failed: %s", e)
    return events


def _collect_emails_needing_reply(bridge) -> list[dict]:
    ""
    try:
        data = bridge.get_emails_needing_reply(max_age_days=3, limit=10)
        return data.get("emails", [])
    except Exception as e:
        log.warning("Email collection failed: %s", e)
        return []


def _collect_followups(bridge) -> list[dict]:
    ""
    try:
        data = bridge.get_home_actions(max_items=10)
        return data.get("items", [])
    except Exception as e:
        log.warning("Follow-up collection failed: %s", e)
        return []


def _collect_focus_items(bridge) -> list[dict]:
    ""
    try:
        data = bridge.get_focus_items(max_items=3)
        return data.get("items", [])
    except Exception as e:
        log.warning("Focus items collection failed: %s", e)
        return []




_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _today_label() -> str:
    d = date.today()
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month]}"


def format_briefing(
    calendar: list[dict],
    emails: list[dict],
    followups: list[dict],
    focus: list[dict],
) -> str:
    ""
    now = datetime.now()
    lines = [
        f"*SBK Daily Briefing* | {_today_label()} | {now.strftime('%H:%M')}",
        "",
    ]


    if focus:
        lines.append("*Top 3 priorities:*")
        for i, item in enumerate(focus, 1):
            score = int(item.get("priority_score", 0) * 100)
            emoji = (
                ":red_circle:"
                if score >= 70
                else ":large_orange_diamond:"
                if score >= 50
                else ":white_circle:"
            )
            lines.append(f"  {emoji} {i}. {item['context']} — _{item.get('action', '')}_")
        lines.append("")


    if calendar:
        lines.append(f"*Agenda* ({len(calendar)} meetings)")
        for ev in calendar:
            time_str = ev.get("time", "")
            att = ev.get("attendees", 0)
            att_str = f" ({att} people)" if att else ""
            lines.append(f"  :calendar: {time_str} {ev['summary']}{att_str}")
        lines.append("")
    else:
        lines.append("*Agenda:* No meetings today :tada:")
        lines.append("")


    if emails:
        high = [e for e in emails if e.get("priority") == "high"]
        normal = [e for e in emails if e.get("priority") != "high"]
        total = len(emails)
        lines.append(f"*Emails to reply to* ({total})")
        for e in (high + normal)[:5]:
            icon = ":exclamation:" if e.get("priority") == "high" else ":envelope:"
            subject = e.get("subject", "")[:50]
            name = e.get("from_name", "")[:25]
            lines.append(f"  {icon} {name}: {subject}")
        if total > 5:
            lines.append(f"  _...and {total - 5} more_")
        lines.append("")


    overdue = [f for f in followups if f.get("urgency") == "OVERDUE"]
    today_items = [f for f in followups if f.get("urgency") == "TODAY"]
    if overdue or today_items:
        lines.append(f"*Follow-up* ({len(overdue)} overdue, {len(today_items)} today)")
        for f in (overdue + today_items)[:5]:
            icon = ":warning:" if f.get("urgency") == "OVERDUE" else ":pushpin:"
            text = f.get("action_text", f.get("text", ""))[:60]
            lines.append(f"  {icon} {text}")
        lines.append("")


    if not calendar and not emails and not followups and not focus:
        lines.append(":sunny: Free day! No urgent actions.")
        lines.append("")

    return "\n".join(lines)





def send_briefing(text: str) -> bool:
    ""
    try:
        from monitoring.slack_alerter import send_slack_dm

        return send_slack_dm(text)
    except Exception as e:
        log.error("Slack send failed: %s", e)
        return False





def _esito(outcome: str, detail: str = "") -> None:
    ""

    try:
        from jb_auto import esito

        esito(outcome, detail)
    except Exception:  # noqa: BLE001
        pass


def main():
    parser = argparse.ArgumentParser(description="SBK Daily Briefing Generator")
    parser.add_argument("--preview", action="store_true", help="Preview only, don't send")
    parser.add_argument("--force", action="store_true", help="Bypass idempotency check")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent")
    args = parser.parse_args()


    if not args.force and not args.preview and not args.dry_run:
        if _already_sent():
            log.info("Briefing already sent today. Use --force to resend.")
            _esito("nothing", "already sent today")
            return

    log.info("Collecting briefing data...")


    from app.core.sbk_bridge import SBKBridge

    bridge = SBKBridge()
    bridge.warmup()


    calendar = _collect_calendar_events(bridge)
    emails = _collect_emails_needing_reply(bridge)
    followups = _collect_followups(bridge)
    focus = _collect_focus_items(bridge)

    log.info(
        "Data collected: %d meetings, %d emails, %d followups, %d focus items",
        len(calendar),
        len(emails),
        len(followups),
        len(focus),
    )


    briefing_text = format_briefing(calendar, emails, followups, focus)

    if args.preview or args.dry_run:
        print("=" * 60)
        print(briefing_text)
        print("=" * 60)
        if args.dry_run:
            print(f"\n[DRY RUN] Would send to Slack ({len(briefing_text)} chars)")
        _esito("nothing", "preview or dry run, nothing sent")
        return


    log.info("Sending briefing to Slack...")
    sent = send_briefing(briefing_text)


    briefing_data = {
        "date": date.today().isoformat(),
        "sent_at": datetime.now(UTC).isoformat(),
        "sent": sent,
        "briefing_id": f"brief-{date.today().isoformat()}",
        "sections": {
            "meetings_today": len(calendar),
            "emails_pending": len(emails),
            "followups_due": len(followups),
            "focus_items": len(focus),
        },
        "char_count": len(briefing_text),
    }
    _log_briefing(briefing_data)

    if sent:
        log.info("Briefing sent successfully!")
        _esito(
            "ok",
            f"sent to Slack: {len(calendar)} meetings, {len(emails)} emails, "
            f"{len(followups)} follow-ups, {len(focus)} focus items",
        )
    else:
        log.error("Briefing send FAILED")
        _esito("failed", "Slack send failed")
        sys.exit(1)


if __name__ == "__main__":


    import sys as _sys
    from pathlib import Path as _P

    _sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools" / "jobs"))

    def _uscita(_codice) -> None:
        return None

    try:
        from jb_auto import aggancia as _aggancia
        from jb_auto import uscita as _uscita

        _aggancia("com.sbk.daily-briefing")
    except Exception:  # noqa: BLE001 -- the registry must never break the job
        pass



    try:
        main()
    except SystemExit as _e:
        _uscita(_e.code)
        raise
