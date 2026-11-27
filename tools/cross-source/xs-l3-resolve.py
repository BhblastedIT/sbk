#!/usr/bin/env python3
"""Event resolution: for the calendar events of the last and next days, the type (investor, travel, conference,
social...) and whether a follow-up happened by email, Slack or calendar, into l3/resolved-events.parquet.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, setup_logging

from sbk_config import INTERNAL_DOMAINS, L3_DIR, NETWORK_DIR, OWN_EMAILS, safe_write_parquet

log = logging.getLogger("sbk-l3-resolve")

OUTPUT_FILE = L3_DIR / "resolved-events.parquet"



TRAVEL_KEYWORDS = {"volo", "flight", "treno", "train", "hotel", "airport", "aeroporto"}
CONFERENCE_KEYWORDS = {"conference", "summit", "webinar"}
SOCIAL_KEYWORDS = {"cena", "pranzo", "dinner", "lunch", "aperitivo", "compleanno", "birthday"}
TEAM_RECURRING_KEYWORDS = {"standup", "sync", "weekly", "1:1"}


FOLLOWUP_WINDOWS = {
    "investor_meeting": 72,
    "intro_meeting": 48,
    "meeting": 48,
    "delegated_meeting": 48,
    "conference": 72,
    "social": 0,
    "travel": 0,
    "personal_task": 0,
    "team_recurring": 24,
}

INTERNAL_DOMAINS_LOWER = {d.lower() for d in INTERNAL_DOMAINS}
OWN_EMAILS_LOWER = {e.lower() for e in OWN_EMAILS}





def parse_event_datetime(event: dict) -> datetime | None:
    ""
    start = event.get("start", {})
    if not isinstance(start, dict):
        return None

    start_str = start.get("dateTime") or start.get("date", "")
    if not start_str:
        return None

    try:
        if "T" in str(start_str):
            dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            return dt.astimezone(UTC)
        else:
            return datetime.strptime(str(start_str)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def extract_attendee_emails(event: dict) -> list[str]:
    ""






    emails = set()


    attendees = event.get("attendees", [])
    if isinstance(attendees, str):
        for part in attendees.split(","):
            part = part.strip().lower()
            if "@" in part:
                emails.add(part)
    elif isinstance(attendees, list):
        for a in attendees:
            if isinstance(a, dict):
                email = (a.get("email") or "").strip().lower()
                if email:
                    emails.add(email)
            elif isinstance(a, str):
                a = a.strip().lower()
                if "@" in a:
                    emails.add(a)


    organizer = event.get("organizer", "")
    if isinstance(organizer, dict):
        org_email = (organizer.get("email") or "").strip().lower()
        if org_email:
            emails.add(org_email)
    elif isinstance(organizer, str):
        org_email = organizer.strip().lower()
        if "@" in org_email:
            emails.add(org_email)

    return sorted(emails)


def load_investor_signals(data: SBKData) -> set[str]:
    ""




    names: set[str] = set()
    # Optional, user-maintained list in a documented, generic format:
    # <data root>/network/investors.json -> {"investors": ["Name One", "Name Two"]}
    index_path = NETWORK_DIR / "investors.json"

    if not index_path.exists():
        log.debug(f"Investor list not found: {index_path}")
        return names

    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return names

    for entry in raw.get("investors", []):
        name = str(entry).strip().lower()
        if name:
            names.add(name)

    log.debug(f"Loaded {len(names)} investor names")
    return names


def _load_investor_fund_domains() -> set[str]:
    """First part of your investors' e-mail domains ("fundname" for fundname.com), from the
    same optional list as the investor names: <data root>/network/investors.json ->
    {"fund_domains": ["fundname", ...]}. Empty by default."""
    path = NETWORK_DIR / "investors.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(d).strip().lower() for d in raw.get("fund_domains", []) if str(d).strip()}


INVESTOR_FUND_DOMAINS: set[str] = _load_investor_fund_domains()





def classify_event(
    event: dict,
    investor_names: set[str],
    internal_domains: set[str] | None = None,
) -> dict:
    ""





    if internal_domains is None:
        internal_domains = INTERNAL_DOMAINS_LOWER

    attendee_emails = extract_attendee_emails(event)
    start_dt = parse_event_datetime(event)
    now = datetime.now(UTC)
    is_past = start_dt < now if start_dt else False

    summary = (event.get("summary") or "").strip()
    summary_lower = summary.lower()
    attendee_count = len(attendee_emails)


    external_emails = []
    for em in attendee_emails:
        if em in OWN_EMAILS_LOWER:
            continue
        domain = em.split("@")[1] if "@" in em else ""
        if domain and domain not in internal_domains:
            external_emails.append(em)


    raw_attendee_emails = set()
    raw_attendees = event.get("attendees", [])
    if isinstance(raw_attendees, str):
        for part in raw_attendees.split(","):
            part = part.strip().lower()
            if "@" in part:
                raw_attendee_emails.add(part)
    elif isinstance(raw_attendees, list):
        for a in raw_attendees:
            if isinstance(a, dict):
                em = (a.get("email") or "").strip().lower()
                if em:
                    raw_attendee_emails.add(em)
            elif isinstance(a, str) and "@" in a:
                raw_attendee_emails.add(a.strip().lower())
    owner_in_attendees = bool(raw_attendee_emails & OWN_EMAILS_LOWER)


    organizer = event.get("organizer", "")
    organizer_email = ""
    if isinstance(organizer, dict):
        organizer_email = (organizer.get("email") or "").lower()
    elif isinstance(organizer, str):
        organizer_email = organizer.lower()
    owner_is_organizer = organizer_email in OWN_EMAILS_LOWER


    all_internal = all(
        em.split("@")[1] in internal_domains if "@" in em else True
        for em in attendee_emails
        if em not in OWN_EMAILS_LOWER
    )




    if summary_lower.startswith("task"):
        event_type = "personal_task"
        owner = "self"
        needs_followup = False


    elif any(kw in summary_lower for kw in TRAVEL_KEYWORDS):
        event_type = "travel"
        owner = "self"
        needs_followup = False


    elif any(kw in summary_lower for kw in CONFERENCE_KEYWORDS) or attendee_count >= 10:
        event_type = "conference"
        owner = "self"
        needs_followup = True


    elif any(kw in summary_lower for kw in SOCIAL_KEYWORDS):
        event_type = "social"
        owner = "self"
        needs_followup = False


    elif _is_investor_meeting(summary_lower, attendee_emails, investor_names):
        event_type = "investor_meeting"
        owner = "self"
        needs_followup = True


    elif ("intro" in summary_lower or "introduction" in summary_lower) and external_emails:
        event_type = "intro_meeting"
        owner = "self"
        needs_followup = True


    elif all_internal and any(kw in summary_lower for kw in TEAM_RECURRING_KEYWORDS):
        event_type = "team_recurring"
        owner = "team"
        needs_followup = False


    elif owner_is_organizer and not owner_in_attendees and attendee_count > 0:
        event_type = "delegated_meeting"
        owner = "delegated"
        needs_followup = True


    else:
        event_type = "meeting"
        owner = "self"
        needs_followup = bool(external_emails)

    followup_window = FOLLOWUP_WINDOWS.get(event_type, 48)

    event["event_type"] = event_type
    event["owner"] = owner
    event["needs_followup"] = needs_followup
    event["followup_window_hours"] = followup_window
    event["_attendee_emails"] = attendee_emails
    event["_start_dt"] = start_dt
    event["_is_past"] = is_past

    return event


def _is_investor_meeting(
    summary_lower: str, attendee_emails: list[str], investor_names: set[str]
) -> bool:
    ""

    for name in investor_names:
        if name in summary_lower:
            return True


    for em in attendee_emails:
        if em in OWN_EMAILS_LOWER:
            continue
        domain = em.split("@")[1] if "@" in em else ""
        domain_base = domain.split(".")[0] if domain else ""
        if domain_base.lower() in INVESTOR_FUND_DOMAINS:
            return True

    return False





def detect_followup(event: dict, data: SBKData) -> dict:
    ""





    start_dt = event.get("_start_dt")
    needs_followup = event.get("needs_followup", False)
    is_past = event.get("_is_past", False)


    if not is_past:
        return {"resolution_status": "future", "resolution_signals": []}


    if not needs_followup:
        return {"resolution_status": "no_followup_needed", "resolution_signals": []}

    if not start_dt:
        return {"resolution_status": "unknown", "resolution_signals": []}

    window_hours = event.get("followup_window_hours", 48)
    window_end = start_dt + timedelta(hours=window_hours)
    now = datetime.now(UTC)

    attendee_emails = event.get("_attendee_emails", [])
    external_emails = [em for em in attendee_emails if em not in OWN_EMAILS_LOWER]

    signals = []


    email_signals = _check_email_signal(external_emails, start_dt, window_end, data)
    signals.extend(email_signals)


    slack_signals = _check_slack_signal(external_emails, start_dt, window_end, data)
    signals.extend(slack_signals)


    cal_signals = _check_calendar_signal(event, external_emails, data)
    signals.extend(cal_signals)


    if signals:
        return {"resolution_status": "resolved", "resolution_signals": signals}
    elif now > window_end:
        return {"resolution_status": "pending", "resolution_signals": []}
    else:
        return {"resolution_status": "unknown", "resolution_signals": []}


def _check_email_signal(
    external_emails: list[str],
    start_dt: datetime,
    window_end: datetime,
    data: SBKData,
) -> list[dict]:
    ""
    signals = []
    try:
        threads = data.threads
    except Exception:
        return signals


    start_ts = pd.Timestamp(start_dt)
    end_ts = pd.Timestamp(window_end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")


    mask = (threads["date_end"] >= start_ts) & (threads["date_start"] <= end_ts)
    window_threads = threads[mask]

    for _, row in window_threads.iterrows():
        participants_raw = row.get("participants", "") or ""
        participants = {p.strip().lower() for p in participants_raw.split(",") if p.strip()}

        matching = participants & set(external_emails)
        if matching:
            signals.append(
                {
                    "source": "email",
                    "type": "thread_activity",
                    "date": str(row.get("date_end", "")),
                    "detail": f"Thread: {row.get('subject', '')[:80]} (con {', '.join(list(matching)[:2])})",
                }
            )
            break

    return signals


def _check_slack_signal(
    external_emails: list[str],
    start_dt: datetime,
    window_end: datetime,
    data: SBKData,
) -> list[dict]:
    ""
    signals = []
    try:
        slack = data.slack_interactions
    except Exception:
        return signals


    attendee_names = set()
    for em in external_emails:
        person = data.resolve_person(em)
        if person:
            name = (person.get("name") or "").lower()
            if name:
                attendee_names.add(name)

    if not attendee_names:
        return signals

    for _, row in slack.iterrows():
        ts_str = row.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if ts < start_dt or ts > window_end:
            continue

        from_user = (row.get("from_user") or "").lower()
        if any(name in from_user or from_user in name for name in attendee_names):
            signals.append(
                {
                    "source": "slack",
                    "type": "message",
                    "date": str(ts_str),
                    "detail": f"Slack da {row.get('from_user', '')} in {row.get('channel', '')}",
                }
            )
            break

    return signals


def _check_calendar_signal(event: dict, external_emails: list[str], data: SBKData) -> list[dict]:
    ""
    signals = []
    event_id = event.get("id", "")
    start_dt = event.get("_start_dt")
    if not start_dt:
        return signals

    external_set = set(external_emails)

    for other_ev in data.calendar_events:
        if other_ev.get("id") == event_id:
            continue

        other_dt = parse_event_datetime(other_ev)
        if not other_dt or other_dt <= start_dt:
            continue

        other_emails = set(extract_attendee_emails(other_ev))
        overlap = other_emails & external_set
        if overlap:
            signals.append(
                {
                    "source": "calendar",
                    "type": "follow_up_scheduled",
                    "date": str(other_dt),
                    "detail": f"Upcoming event: {other_ev.get('summary', '')[:80]} (with {', '.join(list(overlap)[:2])})",
                }
            )
            break

    return signals





def resolve_events(
    data: SBKData,
    days_back: int = 30,
    days_forward: int = 7,
) -> pd.DataFrame:
    ""



    now = datetime.now(UTC)
    cutoff_past = now - timedelta(days=days_back)
    cutoff_future = now + timedelta(days=days_forward)

    investor_names = load_investor_signals(data)
    events = data.calendar_events

    log.info(
        f"Processing {len(events)} calendar events (back={days_back}d, forward={days_forward}d)"
    )

    rows = []
    for ev in events:
        start_dt = parse_event_datetime(ev)
        if not start_dt:
            continue
        if start_dt < cutoff_past or start_dt > cutoff_future:
            continue


        classified = classify_event(ev, investor_names)


        resolution = detect_followup(classified, data)

        row = {
            "event_id": ev.get("id", ""),
            "summary": ev.get("summary", ""),
            "start_datetime": str(start_dt),
            "end_datetime": str(
                ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
            ),
            "calendar_name": ev.get("calendarName", ""),
            "attendee_count": len(classified.get("_attendee_emails", [])),
            "attendee_emails": ",".join(classified.get("_attendee_emails", [])),
            "event_type": classified.get("event_type", "meeting"),
            "owner": classified.get("owner", "self"),
            "needs_followup": classified.get("needs_followup", False),
            "followup_window_hours": classified.get("followup_window_hours", 48),
            "resolution_status": resolution["resolution_status"],
            "resolution_signals_count": len(resolution["resolution_signals"]),
            "resolution_signals_json": json.dumps(
                resolution["resolution_signals"], ensure_ascii=False
            )
            if resolution["resolution_signals"]
            else "",
            "resolved_by": resolution["resolution_signals"][0]["source"]
            if resolution["resolution_signals"]
            else "",
            "resolved_at": resolution["resolution_signals"][0]["date"]
            if resolution["resolution_signals"]
            else "",
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("start_datetime", ascending=False)

    log.info(f"Resolved {len(df)} events")
    if not df.empty:
        status_counts = df["resolution_status"].value_counts().to_dict()
        type_counts = df["event_type"].value_counts().to_dict()
        log.info(f"  Status: {status_counts}")
        log.info(f"  Types: {type_counts}")

    return df





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Event Resolution Engine")
    parser.add_argument("--days-back", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument(
        "--days-forward", type=int, default=7, help="Days to look ahead (default: 7)"
    )
    parser.add_argument("--type", dest="event_type", help="Filter by event type")
    parser.add_argument("--status", help="Filter by resolution status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose, name="sbk-l3-resolve")

    data = SBKData()
    df = resolve_events(data, days_back=args.days_back, days_forward=args.days_forward)

    if df.empty:
        print("No events found in the selected period.")
        return


    if args.event_type:
        df = df[df["event_type"] == args.event_type]
    if args.status:
        df = df[df["resolution_status"] == args.status]

    if df.empty:
        print("No event matches the filters.")
        return


    if args.json:
        print(df.to_json(orient="records", force_ascii=False, indent=2))
    elif args.dry_run:
        print(f"\n=== Event Resolution: {len(df)} events ===\n")
        status_counts = df["resolution_status"].value_counts().to_dict()
        type_counts = df["event_type"].value_counts().to_dict()
        print(f"  Status: {status_counts}")
        print(f"  Types: {type_counts}")
        print()

        for _, row in df.head(20).iterrows():
            status_badge = {
                "resolved": "OK",
                "pending": "PENDING",
                "unknown": "?",
                "no_followup_needed": "N/A",
                "future": "FUTURE",
            }.get(row["resolution_status"], "?")
            print(
                f"  [{status_badge:7s}] [{row['event_type']:18s}] "
                f"{row['summary'][:50]:50s} | {row['start_datetime'][:16]} | "
                f"{row['attendee_count']} att."
            )
            if row["resolution_signals_json"]:
                print(f"           Signals: {row['resolution_signals_json'][:100]}")
    else:

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_write_parquet(df, OUTPUT_FILE, index=False)
        print(f"\nEvents resolved: {len(df)}")
        print(f"Output: {OUTPUT_FILE}")

        status_counts = df["resolution_status"].value_counts().to_dict()
        type_counts = df["event_type"].value_counts().to_dict()
        print(f"Status: {status_counts}")
        print(f"Types: {type_counts}")

        pending = df[df["resolution_status"] == "pending"]
        if not pending.empty:
            print(f"\n=== {len(pending)} PENDING (azione necessaria) ===")
            for _, row in pending.head(10).iterrows():
                print(
                    f"  {row['summary'][:60]} | {row['start_datetime'][:16]} | {row['attendee_count']} att."
                )


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-resolve", source="l3-resolve", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
