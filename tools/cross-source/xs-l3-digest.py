#!/usr/bin/env python3
"""Morning digest (the older version; `sbk brief` runs xs-l3-digest-v2.py): today's calendar, urgent email, Slack
highlights, decay alerts, follow-ups, deadlines, decisions and stale threads, ranked and grouped by person.

Nothing is sent to a model by default: it prints the items. --synthesize (or "brief": {"synthesis": true} in
sbk.config.json) sends them to Claude through the Anthropic API with your ANTHROPIC_API_KEY and writes the digest.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, call_claude, notify_macos, setup_logging, write_brief

from sbk_config import (
    DECAY_DIR,
    DEEP_FACTS_FILE,
    L3_DIR,
    NLP_DIR,
    OWN_EMAILS,
    OWNER_LABEL,
    is_own_name,
)

log = logging.getLogger("sbk-l3-digest")



STATE_FILE = L3_DIR / "digest-state.json"

URGENCY_KEYWORDS = {
    "urgent",
    "urgente",
    "asap",
    "deadline",
    "scadenza",
    "immediately",
    "immediatamente",
    "critico",
    "critical",
    "blocco",
    "blocking",
    "bloccante",
    "priorita",
    "priority",
    "attenzione",
    "attention",
}


SHOW_SCHEDULE_DAYS = [0, 2, 6]





def load_state() -> dict:
    ""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"open_loops_shown": {}, "last_digest_date": None}


def save_state(state: dict):
    ""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def should_show_open_loop(thread_id: str, state: dict, today: str) -> bool:
    ""
    shown_dates = state.get("open_loops_shown", {}).get(thread_id, [])

    if not shown_dates:
        return True

    first_seen = shown_dates[0]
    try:
        first_dt = datetime.strptime(first_seen, "%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        return True

    days_since_first = (today_dt - first_dt).days


    for offset in SHOW_SCHEDULE_DAYS:
        if days_since_first == offset:
            return today not in shown_dates


    if days_since_first > 6 and (days_since_first % 7) == 0:
        return today not in shown_dates

    return False


def record_shown(thread_id: str, state: dict, today: str):
    ""
    loops = state.setdefault("open_loops_shown", {})
    dates = loops.setdefault(thread_id, [])
    if today not in dates:
        dates.append(today)





def collect_calendar_today(data: SBKData, target_date: datetime) -> list[dict]:
    ""
    items = []
    today_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_noon = today_start + timedelta(days=1, hours=12)

    own_emails_lower = {e.lower() for e in OWN_EMAILS}

    for ev in data.calendar_events:
        start = ev.get("start", {})
        start_str = start.get("dateTime") or start.get("date", "")
        if not start_str:
            continue

        try:
            if "T" in start_str:
                dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                dt_naive = dt.replace(tzinfo=None)
            else:
                dt_naive = datetime.strptime(start_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        if today_start <= dt_naive < tomorrow_noon:
            attendees = ev.get("attendees", [])
            attendee_emails = []
            if isinstance(attendees, list):
                for a in attendees:
                    if isinstance(a, str):
                        attendee_emails.append(a.lower())
                    elif isinstance(a, dict):
                        email = a.get("email", "").lower()
                        if email:
                            attendee_emails.append(email)


            external_attendees = [e for e in attendee_emails if e not in own_emails_lower]

            items.append(
                {
                    "type": "calendar",
                    "source": "calendar",
                    "title": ev.get("summary", "(no title)"),
                    "datetime": dt_naive.isoformat(),
                    "attendees": external_attendees,
                    "organizer": ev.get("organizer", ""),
                    "calendar": ev.get("calendarName", ""),
                    "is_tomorrow": dt_naive.date() > target_date.date(),
                }
            )

    log.info(f"Calendar: {len(items)} events today/tomorrow morning")
    return items


def collect_email_urgent(data: SBKData, target_date: datetime, hours: int = 24) -> list[dict]:
    ""
    items = []
    own_emails_lower = {e.lower() for e in OWN_EMAILS}

    cutoff = target_date - timedelta(hours=hours)
    cutoff_ts = pd.Timestamp(cutoff, tz="UTC")

    threads = data.threads

    recent = threads[threads["date_end"] >= cutoff_ts].copy()

    for _, row in recent.iterrows():
        participants_raw = row.get("participants", "") or ""
        participants = [p.strip().lower() for p in participants_raw.split(",") if p.strip()]


        has_own = any(p in own_emails_lower for p in participants)
        if not has_own:
            continue





        other_participants = [p for p in participants if p not in own_emails_lower]
        if not other_participants:
            continue

        subject = row.get("subject", "")
        thread_id = row.get("thread_id", "")
        date_end = row.get("date_end")

        items.append(
            {
                "type": "email",
                "source": "email",
                "title": subject,
                "thread_id": thread_id,
                "datetime": str(date_end),
                "participants": other_participants,
                "msg_count": int(row.get("msg_count", 0)),
                "account": row.get("account", ""),
                "labels": row.get("labels", ""),
            }
        )

    log.info(f"Email open loops: {len(items)} threads in last {hours}h")
    return items


def collect_slack_highlights(
    data: SBKData, target_date: datetime, hours: int = 24
) -> list[dict]:
    ""
    items = []
    cutoff = target_date - timedelta(hours=hours)

    try:
        slack = data.slack_interactions
    except Exception as e:
        log.warning(f"Failed to load Slack data: {e}")
        return items

    for _, row in slack.iterrows():
        ts_str = row.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            ts_naive = ts.replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        if ts_naive < cutoff:
            continue

        msg_type = row.get("message_type", "")
        from_user = row.get("from_user", "")
        channel = row.get("channel", "")


        if is_own_name(str(from_user)):
            continue


        is_dm = msg_type == "dm" or channel.startswith("dm-")
        is_mention = msg_type == "mention"
        is_reply = msg_type == "reply"

        if not (is_dm or is_mention or is_reply):
            continue

        items.append(
            {
                "type": "slack",
                "source": "slack",
                "title": f"{'DM' if is_dm else 'Mention'} from {from_user} in {channel}",
                "datetime": ts_naive.isoformat(),
                "from_user": from_user,
                "channel": channel,
                "message_type": msg_type,
            }
        )

    log.info(f"Slack highlights: {len(items)} items in last {hours}h")
    return items


def collect_decay_alerts(target_date: datetime) -> list[dict]:
    ""
    items = []
    date_str = target_date.strftime("%Y%m%d")
    alerts_file = DECAY_DIR / f"alerts-{date_str}.json"

    if not alerts_file.exists():
        log.debug("No decay alerts file found")
        return items

    try:
        alerts = json.loads(alerts_file.read_text())
        for alert in alerts[:3]:
            items.append(
                {
                    "type": "decay",
                    "source": "decay",
                    "title": alert.get("message", alert.get("name", "Relationship declining")),
                    "person": alert.get("name", ""),
                    "email": alert.get("email", ""),
                    "score_drop": alert.get("score_drop", 0),
                    "current_score": alert.get("current_score", 0),
                    "datetime": target_date.isoformat(),
                }
            )
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to load decay alerts: {e}")

    log.info(f"Decay alerts: {len(items)}")
    return items


def collect_followup_reminders(target_date: datetime, max_items: int = 5) -> list[dict]:
    ""
    items = []
    action_items_file = NLP_DIR / "action-items.parquet"
    state_file = NLP_DIR / "followup-state.json"

    if not action_items_file.exists():
        log.debug("No action-items.parquet found")
        return items

    try:
        df = pd.read_parquet(action_items_file)
    except Exception as e:
        log.warning(f"Failed to load action items: {e}")
        return items


    dismissed: set[str] = set()
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            dismissed = set(state.get("dismissed", []))
        except (json.JSONDecodeError, OSError):
            pass

    today = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming_cutoff = today + timedelta(days=2)


    try:
        import importlib.util

        followup_path = _THIS_DIR / "xs-l3-followup.py"
        spec = importlib.util.spec_from_file_location("xs_l3_followup", followup_path)
        followup_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(followup_mod)
        _parse_deadline = followup_mod.parse_deadline
    except (ImportError, AttributeError, FileNotFoundError) as e:
        log.debug(f"Could not import parse_deadline from xs-l3-followup: {e}")
        return items

    for _, row in df.iterrows():
        deadline_str = str(row.get("deadline", "") or "")
        if not deadline_str or deadline_str == "nan":
            continue

        meeting_date = str(row.get("date", "") or "")
        parsed = _parse_deadline(deadline_str, meeting_date if meeting_date else None)
        if parsed is None:
            continue


        if parsed.tzinfo is None and today.tzinfo is not None:
            from datetime import UTC

            parsed = parsed.replace(tzinfo=UTC)
        elif parsed.tzinfo is not None and today.tzinfo is None:
            parsed = parsed.replace(tzinfo=None)


        if parsed > upcoming_cutoff:
            continue

        item_id = f"{row.get('meeting_id', '')}|{row.get('action_text', '')[:50]}"
        if item_id in dismissed:
            continue

        is_overdue = parsed < today
        items.append(
            {
                "type": "followup",
                "source": "nlp",
                "title": str(row.get("action_text", ""))[:120],
                "datetime": parsed.isoformat(),
                "assignee": str(row.get("assignee", "") or row.get("speaker", "")),
                "meeting_title": str(row.get("meeting_title", "")),
                "deadline_raw": deadline_str,
                "is_overdue": is_overdue,
                "urgency": "overdue" if is_overdue else "upcoming",
            }
        )


    items.sort(key=lambda x: (not x["is_overdue"], x["datetime"]))
    items = items[:max_items]
    log.info(
        f"Follow-up reminders: {len(items)} items ({sum(1 for i in items if i['is_overdue'])} overdue)"
    )
    return items


def collect_pending_events(max_items: int = 5) -> list[dict]:
    ""
    items = []
    resolved_path = L3_DIR / "resolved-events.parquet"
    if not resolved_path.exists():
        log.debug("No resolved-events.parquet found")
        return items

    try:
        df = pd.read_parquet(resolved_path)
    except Exception as e:
        log.warning(f"Failed to load resolved events: {e}")
        return items

    pending = df[df["resolution_status"] == "pending"].head(max_items)
    for _, row in pending.iterrows():
        items.append(
            {
                "type": "pending_event",
                "source": "calendar",
                "title": f"Event without follow-up: {row.get('summary', '')}",
                "datetime": str(row.get("start_datetime", "")),
                "event_type": row.get("event_type", ""),
                "attendee_count": int(row.get("attendee_count", 0)),
                "attendee_emails": row.get("attendee_emails", ""),
            }
        )

    log.info(f"Pending events: {len(items)}")
    return items


def collect_deep_fact_deadlines(max_commitments: int = 15, max_deals: int = 10) -> str:
    ""




    if not DEEP_FACTS_FILE.exists():
        log.debug("No deep-facts.parquet found, skipping deep-fact deadlines")
        return ""

    try:
        deep_df = pd.read_parquet(DEEP_FACTS_FILE)
    except Exception as e:
        log.warning(f"Failed to load deep-facts.parquet: {e}")
        return ""

    if deep_df.empty:
        return ""

    sections = []


    commitments = deep_df[deep_df["category"] == "commitment"]
    if not commitments.empty and "timeline" in commitments.columns:
        with_timeline = commitments[commitments["timeline"].str.strip().str.len() > 0]
        if not with_timeline.empty:
            lines = ["\n### Commitments with deadline"]
            for _, c in with_timeline.head(max_commitments).iterrows():
                subject = str(c.get("subject", "")).strip()
                desc = str(c.get("object", "")).strip()
                timeline = str(c.get("timeline", "")).strip()
                amount = str(c.get("amount", "")).strip()
                currency = str(c.get("currency", "")).strip()
                amount_str = f" ({amount} {currency})" if amount and amount != "nan" else ""
                lines.append(f"- {subject}: {desc}{amount_str}, deadline: {timeline}")
            sections.append("\n".join(lines))
            log.info(f"Deep-fact commitments with deadline: {len(with_timeline)}")


    deals = deep_df[deep_df["category"] == "deal"]
    if not deals.empty and "timeline" in deals.columns:
        deals_with_timeline = deals[deals["timeline"].str.strip().str.len() > 0]
        if not deals_with_timeline.empty:
            lines = ["\n### Deals with timeline"]
            for _, d in deals_with_timeline.head(max_deals).iterrows():
                parties = str(d.get("subject", "")).strip()
                desc = str(d.get("object", "")).strip()
                timeline = str(d.get("timeline", "")).strip()
                lines.append(f"- {parties}: {desc}, {timeline}")
            sections.append("\n".join(lines))
            log.info(f"Deep-fact deals with timeline: {len(deals_with_timeline)}")

    return "\n".join(sections)


def collect_recent_decisions(
    target_date: datetime, days: int = 7, max_items: int = 5
) -> list[dict]:
    ""
    items = []
    decisions_file = NLP_DIR / "decisions.parquet"
    if not decisions_file.exists():
        log.debug("No decisions.parquet found")
        return items

    try:
        df = pd.read_parquet(decisions_file)
    except Exception as e:
        log.warning(f"Failed to load decisions: {e}")
        return items

    cutoff = (target_date - timedelta(days=days)).strftime("%Y-%m-%d")


    if "date" in df.columns:
        recent = df[df["date"].fillna("") >= cutoff].copy()
    else:
        recent = df.copy()


    if "extraction_method" in recent.columns:
        recent["_quality"] = recent["extraction_method"].map({"claude": 2, "regex": 1}).fillna(0)
        recent = recent.sort_values("_quality", ascending=False)

    for _, row in recent.head(max_items).iterrows():
        items.append(
            {
                "type": "decision",
                "source": "nlp",
                "title": str(row.get("decision_text", ""))[:120],
                "datetime": str(row.get("date", "")),
                "speaker": str(row.get("speaker", "")),
                "meeting_title": str(row.get("meeting_title", "")),
            }
        )

    log.info(f"Recent decisions: {len(items)} items (last {days} days)")
    return items


def collect_stale_threads(data: SBKData, target_date: datetime, days: int = 3) -> list[dict]:
    ""
    items = []
    own_emails_lower = {e.lower() for e in OWN_EMAILS}

    stale_cutoff = target_date - timedelta(days=days)
    recent_cutoff = target_date - timedelta(days=30)
    stale_ts = pd.Timestamp(stale_cutoff, tz="UTC")
    recent_ts = pd.Timestamp(recent_cutoff, tz="UTC")

    threads = data.threads
    stale = threads[(threads["date_end"] >= recent_ts) & (threads["date_end"] <= stale_ts)].copy()

    for _, row in stale.iterrows():
        participants_raw = row.get("participants", "") or ""
        participants = [p.strip().lower() for p in participants_raw.split(",") if p.strip()]

        has_own = any(p in own_emails_lower for p in participants)
        if not has_own:
            continue

        other_participants = [p for p in participants if p not in own_emails_lower]
        if not other_participants:
            continue

        items.append(
            {
                "type": "stale",
                "source": "email",
                "title": row.get("subject", ""),
                "thread_id": row.get("thread_id", ""),
                "datetime": str(row.get("date_end", "")),
                "participants": other_participants,
                "msg_count": int(row.get("msg_count", 0)),
                "days_stale": (target_date - stale_cutoff).days,
            }
        )

    log.info(f"Stale threads (>{days}d): {len(items)}")
    return items





def score_digest_item(item: dict, data: SBKData, all_items: list[dict]) -> int:
    ""
    score = 0


    person_score = _get_contact_score(item, data)
    if person_score >= 70:
        score += 30
    elif person_score >= 50:
        score += 20
    elif person_score >= 30:
        score += 10


    title = (item.get("title", "") or "").lower()
    labels = (item.get("labels", "") or "").lower()
    text_to_check = f"{title} {labels}"
    if any(kw in text_to_check for kw in URGENCY_KEYWORDS):
        score += 25


    dt_str = item.get("datetime", "")
    if dt_str:
        try:
            dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
            dt_naive = dt.replace(tzinfo=None)
            hours_ago = (datetime.now() - dt_naive).total_seconds() / 3600
            if hours_ago <= 2:
                score += 20
            elif hours_ago <= 6:
                score += 15
            elif hours_ago <= 12:
                score += 10
            elif hours_ago <= 24:
                score += 5
        except (ValueError, TypeError):
            pass


    item_person = _extract_person_key(item)
    if item_person:
        source_types = set()
        for other in all_items:
            other_person = _extract_person_key(other)
            if other_person and other_person == item_person:
                source_types.add(other.get("source", ""))
        if len(source_types) >= 2:
            score += 15


    if item.get("type") in ("email", "stale"):
        score += 10

    return min(score, 100)


def _get_contact_score(item: dict, data: SBKData) -> float:
    ""

    emails_to_try = []

    if item.get("email"):
        emails_to_try.append(item["email"])

    participants = item.get("participants", [])
    if isinstance(participants, list):
        emails_to_try.extend(participants[:3])

    attendees = item.get("attendees", [])
    if isinstance(attendees, list):
        emails_to_try.extend(attendees[:3])

    organizer = item.get("organizer", "")
    if organizer and "@" in organizer:
        emails_to_try.append(organizer)

    for email in emails_to_try:
        person = data.resolve_person(email)
        if person and person.get("score", 0) > 0:
            return person["score"]


    from_user = item.get("from_user", "")
    if from_user:
        person = data.resolve_person(from_user)
        if person and person.get("score", 0) > 0:
            return person["score"]

    return 0.0


def _extract_person_key(item: dict) -> str | None:
    ""
    if item.get("email"):
        return item["email"].lower()
    if item.get("from_user"):
        return item["from_user"].lower()
    participants = item.get("participants", [])
    if participants:
        return participants[0].lower()
    attendees = item.get("attendees", [])
    if attendees:
        return attendees[0].lower()
    organizer = item.get("organizer", "")
    if organizer and "@" in organizer:
        return organizer.lower()
    return None





def group_by_person(items: list[dict], data: SBKData) -> dict[str, list[dict]]:
    ""
    groups: dict[str, list[dict]] = {}

    for item in items:
        person_key = _extract_person_key(item)
        if not person_key:
            groups.setdefault("_no_person", []).append(item)
            continue


        resolved = data.resolve_person(person_key)
        if resolved:
            canonical = resolved.get("person_id") or resolved.get("name", person_key)

            item["_resolved_name"] = resolved.get("name", "")
            item["_resolved_score"] = resolved.get("score", 0)
            item["_resolved_org"] = resolved.get("organization", "")
        else:
            canonical = person_key
            item["_resolved_name"] = person_key

        groups.setdefault(str(canonical), []).append(item)

    return groups





def build_digest_prompt(
    grouped_items: dict[str, list[dict]],
    target_date: datetime,
    deep_fact_deadlines: str = "",
) -> str:
    ""

    sections = {
        "urgent": [],
        "today": [],
        "inbox": [],
        "relationships": [],
        "followup": [],
        "decisions": [],
        "open_items": [],
    }

    for person_key, items in grouped_items.items():
        for item in items:
            score = item.get("_priority_score", 0)
            item_type = item.get("type", "")

            if score >= 70:
                sections["urgent"].append(item)
            elif item_type == "calendar":
                sections["today"].append(item)
            elif item_type == "email":
                sections["inbox"].append(item)
            elif item_type == "decay":
                sections["relationships"].append(item)
            elif item_type == "followup" or item_type == "pending_event":
                sections["followup"].append(item)
            elif item_type == "decision":
                sections["decisions"].append(item)
            elif item_type == "stale":
                sections["open_items"].append(item)
            else:

                sections["inbox"].append(item)


    for key in sections:
        sections[key].sort(key=lambda x: x.get("_priority_score", 0), reverse=True)


    for key in sections:
        sections[key] = sections[key][:5]


    sections["urgent"] = sections["urgent"][:3]


    date_str = target_date.strftime("%A %d %B %Y")
    prompt_parts = []
    prompt_parts.append(f"Date: {date_str}")
    prompt_parts.append("")

    for section_name, section_items in sections.items():
        if not section_items:
            continue

        prompt_parts.append(f"=== {section_name.upper()} ===")
        for item in section_items:
            name = item.get("_resolved_name", "")
            org = item.get("_resolved_org", "")
            title = item.get("title", "")
            dt = item.get("datetime", "")
            score = item.get("_priority_score", 0)
            item_type = item.get("type", "")

            line = f"[{item_type}] {title}"
            if name:
                line += f" | {name}"
            if org:
                line += f" ({org})"
            if dt:
                try:
                    dt_parsed = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
                    line += f" | {dt_parsed.strftime('%H:%M')}"
                except (ValueError, TypeError):
                    pass
            line += f" | score:{score}"

            if item.get("attendees"):
                line += f" | with: {', '.join(item['attendees'][:3])}"
            if item.get("participants"):
                line += f" | from: {', '.join(item['participants'][:3])}"
            if item.get("msg_count"):
                line += f" | {item['msg_count']} msg"
            if item.get("is_tomorrow"):
                line += " | TOMORROW MORNING"
            if item.get("score_drop"):
                line += f" | drop: {item['score_drop']}"

            prompt_parts.append(f"  {line}")
        prompt_parts.append("")


    if deep_fact_deadlines:
        prompt_parts.append("=== DEEP FACTS: DEADLINES AND TIMELINE ===")
        prompt_parts.append(deep_fact_deadlines)
        prompt_parts.append("")

    return "\n".join(prompt_parts)


# Output language for the generated digest. Set to your preferred language.
DIGEST_LANG = "English"


def synthesize_digest(prompt_data: str, target_date: datetime) -> str:
    ""
    date_str = target_date.strftime("%d/%m/%Y")

    system = (
        f"You are the personal assistant of {OWNER_LABEL}. "
        f"Generate a concise, actionable morning digest in {DIGEST_LANG}. "
        "Use the PDB (Personal Daily Brief) format. "
        "Max 300 words total. Omit empty sections. "
        "Be direct, no fluff. Every item must have a clear action."
    )

    prompt = f"""Generate the morning digest for {date_str}.

Collected data:
{prompt_data}

Required format:
# Digest {date_str}

## TL;DR
(2-3 lines max: what you need to know right away)

## Urgent
(max 3 items with suggested action)

## Today
(calendar + priority)

## Inbox
(email open loops to handle)

## Follow-up
(action items with a deadline overdue or upcoming)

## Recent Decisions
(decisions made in the last 7 days, if any)

## Relationships
(decay alerts if any)

## Open Items
(stale threads > 3 days)

## Deadlines and Timeline
(commitments with a due date and deals with an active timeline, from deep facts, if any)

Rules:
1. Omit empty sections
2. Max 5 items per section
3. Each item: who, what, suggested action
4. Be concise, max 300 words total
5. Write everything in {DIGEST_LANG}"""

    return call_claude(prompt, system=system, max_tokens=1024, temperature=0.3)





def main():
    parser = argparse.ArgumentParser(description="SBK Morning Digest Generator")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show the items and send nothing (the default)"
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Send the items to Claude through the Anthropic API with your ANTHROPIC_API_KEY and write "
        "the digest. Off by default; brief.synthesis true in sbk.config.json turns it on",
    )
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-digest")

    import sbk_config

    wants_model = args.synthesize or sbk_config.user_cfg("brief.synthesis", False) is True
    model_note = ""
    if not args.dry_run and not wants_model:
        args.dry_run = True
        model_note = (
            "Nothing was sent to a model. --synthesize (or \"brief\": {\"synthesis\": true} in "
            "sbk.config.json) sends the digest data above to Claude through the Anthropic API with "
            "your ANTHROPIC_API_KEY."
        )
    elif not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        args.dry_run = True
        model_note = "No model summary: ANTHROPIC_API_KEY is not set, so nothing was sent."


    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            log.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)

    today_str = target_date.strftime("%Y-%m-%d")
    log.info(f"Generating digest for {today_str}")


    state = load_state()


    data = SBKData()



    all_items: list[dict] = []

    cal_items = collect_calendar_today(data, target_date)
    all_items.extend(cal_items)

    email_items = collect_email_urgent(data, target_date, hours=24)
    all_items.extend(email_items)

    slack_items = collect_slack_highlights(data, target_date, hours=24)
    all_items.extend(slack_items)

    decay_items = collect_decay_alerts(target_date)
    all_items.extend(decay_items)

    stale_items = collect_stale_threads(data, target_date, days=3)
    all_items.extend(stale_items)

    pending_event_items = collect_pending_events()
    all_items.extend(pending_event_items)

    followup_items = collect_followup_reminders(target_date)
    all_items.extend(followup_items)

    decision_items = collect_recent_decisions(target_date, days=7)
    all_items.extend(decision_items)


    deep_fact_deadlines = collect_deep_fact_deadlines()

    log.info(f"Total items collected: {len(all_items)}")

    if not all_items:
        log.info("No items to include in digest. Skipping generation.")
        return




    filtered_items = []
    for item in all_items:
        thread_id = item.get("thread_id")
        if thread_id and item.get("type") in ("email", "stale"):
            if should_show_open_loop(thread_id, state, today_str):
                if not args.dry_run:
                    record_shown(thread_id, state, today_str)
                filtered_items.append(item)
            else:
                log.debug(f"Skipping open loop (anti-fatigue): {item.get('title', '')[:60]}")
        else:
            filtered_items.append(item)

    log.info(f"Items after anti-fatigue filter: {len(filtered_items)} (from {len(all_items)})")
    all_items = filtered_items



    for item in all_items:
        item["_priority_score"] = score_digest_item(item, data, all_items)

    all_items.sort(key=lambda x: x["_priority_score"], reverse=True)



    grouped = group_by_person(all_items, data)
    log.info(f"Grouped into {len(grouped)} person clusters")



    prompt_data = build_digest_prompt(grouped, target_date, deep_fact_deadlines=deep_fact_deadlines)

    if args.dry_run:
        print("\n=== DRY RUN: Digest Data ===\n")
        print(prompt_data)
        print("\n=== Stats ===")
        print(f"  Calendar events: {len(cal_items)}")
        print(f"  Email open loops: {len(email_items)}")
        print(f"  Slack highlights: {len(slack_items)}")
        print(f"  Decay alerts: {len(decay_items)}")
        print(f"  Follow-up reminders: {len(followup_items)}")
        print(f"  Pending events: {len(pending_event_items)}")
        print(f"  Stale threads: {len(stale_items)}")
        print(f"  Total after filter: {len(all_items)}")
        print(f"  Deep-fact deadlines: {'yes' if deep_fact_deadlines else 'none'}")
        print(f"  Person groups: {len(grouped)}")

        print("\n=== Top 10 by Priority ===")
        for item in all_items[:10]:
            name = item.get("_resolved_name", "?")
            print(
                f"  [{item['_priority_score']:3d}] [{item['type']:8s}] {name}: {item.get('title', '')[:60]}"
            )

        if model_note:
            print("\n" + model_note)
        return



    log.info("Calling Claude for digest synthesis...")
    digest_md = synthesize_digest(prompt_data, target_date)



    date_slug = target_date.strftime("%Y%m%d")
    output_path = write_brief(digest_md, "digest", slug=date_slug)
    log.info(f"Digest written to: {output_path}")



    state["last_digest_date"] = today_str
    save_state(state)




    urgent_count = sum(1 for i in all_items if i.get("_priority_score", 0) >= 70)
    msg = f"{len(all_items)} items, {urgent_count} urgent"
    notify_macos(
        title="Morning Digest",
        message=msg,
        group="sbk-digest",
    )

    print(f"\nDigest generated: {output_path}")
    print(f"  {len(all_items)} items, {urgent_count} urgent, {len(grouped)} people")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-digest", source="l3-digest", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
