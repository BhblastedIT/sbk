#!/usr/bin/env python3
""













from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import (
    L3_DIR,
    SBKData,
    call_claude,
    notify_macos,
    setup_logging,
    slugify,
    write_brief,
)

from sbk_config import DEEP_FACTS_FILE, OWN_EMAILS, OWNER_LABEL, acquire_pid_lock

log = logging.getLogger("sbk-l3-brief")



STATE_FILE = L3_DIR / "brief-state.json"


def _load_state() -> dict:
    ""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupted brief-state.json, starting fresh")
    return {}


def _save_state(state: dict):
    ""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _already_briefed(state: dict, event_id: str) -> bool:
    ""
    return event_id in state




INVESTOR_KEYWORDS = {
    "fundrais",
    "investor",
    "investitore",
    "round",
    "valuation",
    "term sheet",
    "due diligence",
    "pitch",
    "vc",
    "venture",
    "fund",
    "series",
}

LEGAL_KEYWORDS = {
    "legal",
    "legale",
    "avvocato",
    "lawyer",
    "contenzioso",
    "legal",
    "contratto",
    "nda",
    "tribunale",
}

SKIP_KEYWORDS = {
    "focus time",
    "ooo",
    "out of office",
    "block",
    "lunch",
    "pranzo",
}

# Investor/VC domains used to tag meetings. Load from user config; demo defaults below.
VC_DOMAINS = {
    "partner-ventures.example",
    "northstar-vc.example",
    "beacon-capital.example",
}


def classify_meeting_type(
    event: dict,
    attendee_contexts: list[dict],
) -> str:
    ""



    summary = (event.get("summary") or "").lower()


    if any(kw in summary for kw in SKIP_KEYWORDS):
        return "skip"

    attendees = event.get("attendees") or []
    non_own = [a for a in attendees if (a.get("email") or "").lower() not in OWN_EMAILS]
    if not non_own:
        return "skip"


    if any(kw in summary for kw in INVESTOR_KEYWORDS):
        return "investor"

    for ctx in attendee_contexts:
        email = ctx.get("email", "")
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain in VC_DOMAINS:
            return "investor"
        stage = str(ctx.get("attio_sourcing_stage") or "").lower()
        if "invest" in stage:
            return "investor"


    if any(kw in summary for kw in LEGAL_KEYWORDS):
        return "legal"


    all_attendees = event.get("attendees") or []
    if len(all_attendees) <= 2:
        internal_count = sum(1 for ctx in attendee_contexts if ctx.get("is_internal", False))
        if internal_count == len(attendee_contexts) and len(attendee_contexts) > 0:
            return "team_1on1"


    all_first = all(
        ctx.get("email_total_msgs", 0) == 0 and ctx.get("cal_events", 0) <= 1
        for ctx in attendee_contexts
        if ctx.get("found", False) and not ctx.get("is_internal", False)
    )
    external_ctxs = [
        c for c in attendee_contexts if c.get("found", False) and not c.get("is_internal", False)
    ]
    if all_first and external_ctxs:
        return "first_contact"


    return "investor"




TIMING_HOURS = {
    "investor": 2.0,
    "legal": 1.0,
    "first_contact": 1.0,
    "team_1on1": 0.25,
    "skip": 0.0,
}


def is_within_timing(event: dict, meeting_type: str, max_hours: float) -> bool:
    ""
    if meeting_type == "skip":
        return False
    type_hours = TIMING_HOURS.get(meeting_type, 2.0)
    effective_hours = min(type_hours, max_hours)
    now = datetime.now(UTC)
    cutoff = now + timedelta(hours=effective_hours)
    start_dt = event.get("_start_dt")
    if not start_dt:
        return False
    return now <= start_dt <= cutoff





def assemble_attendee_context(email: str, data: SBKData) -> dict:
    ""
    email_lower = email.strip().lower()
    if email_lower in OWN_EMAILS:
        return {"email": email_lower, "is_self": True, "found": False}
    return data.get_person_context(email_lower)


def get_attendee_emails(event: dict) -> list[str]:
    ""
    attendees = event.get("attendees") or []
    emails = []
    for a in attendees:
        email = (a.get("email") or "").strip().lower()
        if email and email not in OWN_EMAILS:
            emails.append(email)

    organizer = event.get("organizer", {})
    org_email = (organizer.get("email") or "").strip().lower()
    if org_email and org_email not in OWN_EMAILS and org_email not in emails:
        emails.append(org_email)
    return emails





def _format_attendee_for_prompt(ctx: dict) -> str:
    ""
    if not ctx.get("found", False):
        return f"- {ctx.get('email', 'unknown')}: NOT in SBK (no prior data)"

    lines = [f"- **{ctx.get('name', ctx.get('email', ''))}** ({ctx.get('email', '')})"]
    if ctx.get("organization"):
        lines.append(f"  Organization: {ctx['organization']}")
    if ctx.get("job_title"):
        lines.append(f"  Role: {ctx['job_title']}")
    if ctx.get("score"):
        lines.append(f"  Relationship score: {ctx['score']}")
    if ctx.get("source_count"):
        lines.append(f"  Present in {ctx['source_count']} data sources")
    if ctx.get("is_internal"):
        lines.append("  Internal (own organization)")


    msgs = ctx.get("email_total_msgs", 0)
    if msgs:
        lines.append(f"  Email messages: {msgs}")
    if ctx.get("last_contact"):
        lines.append(f"  Last contact: {ctx['last_contact']}")
    if ctx.get("last_thread_subject"):
        lines.append(
            f'  Last email thread: "{ctx["last_thread_subject"]}" ({ctx.get("last_thread_date", "")})'
        )


    cal = ctx.get("cal_events", 0)
    plaud = ctx.get("plaud_meetings", 0)
    tactiq = ctx.get("tactiq_meetings", 0)
    total_meetings = cal + plaud + tactiq
    if total_meetings:
        lines.append(
            f"  Total meetings: {total_meetings} (calendar: {cal}, plaud: {plaud}, tactiq: {tactiq})"
        )


    if ctx.get("attio_connection_strength"):
        lines.append(f"  Attio connection strength: {ctx['attio_connection_strength']}")
    if ctx.get("attio_sourcing_stage"):
        lines.append(f"  Attio sourcing stage: {ctx['attio_sourcing_stage']}")
    if ctx.get("attio_notes_count"):
        lines.append(f"  Attio notes: {ctx['attio_notes_count']}")


    if ctx.get("linkedin_url"):
        lines.append(f"  LinkedIn: {ctx['linkedin_url']}")


    if ctx.get("network_profile"):
        profile_text = ctx["network_profile"]

        if len(profile_text) > 500:
            profile_text = profile_text[:500] + "..."
        lines.append(f"  Network profile excerpt:\n    {profile_text}")


    rel_facts = ctx.get("relationship_facts", [])
    if rel_facts:
        lines.append("  Relationship insights:")
        for fact in rel_facts[:10]:
            pred = fact.get("predicate", "")
            obj = fact.get("object", "")
            ctx_text = fact.get("context", "")
            if pred and obj:
                line = f"    - {pred}: {obj}"
                if ctx_text:
                    line += f' ("{ctx_text}")'
                lines.append(line)


    annotations = ctx.get("annotations", {})
    if annotations:
        if annotations.get("birthday"):
            lines.append(f"  Birthday: {annotations['birthday']}")
        if annotations.get("location"):
            lines.append(f"  Location: {annotations['location']}")
        if annotations.get("tags"):
            lines.append(f"  Tags: {', '.join(annotations['tags'][:5])}")

    return "\n".join(lines)


def _gather_deep_facts_context(attendees_ctx: list[dict]) -> str:
    ""



    if not DEEP_FACTS_FILE.exists():
        return ""

    try:
        import pandas as pd

        deep_df = pd.read_parquet(DEEP_FACTS_FILE)
    except Exception:
        return ""

    if deep_df.empty:
        return ""


    participant_names = []
    for ctx in attendees_ctx:
        if ctx.get("is_self"):
            continue
        name = ctx.get("name", "")
        if name:
            participant_names.append(name)
        email = ctx.get("email", "")
        if email:
            participant_names.append(email)

    if not participant_names:
        return ""

    lines = []
    for participant_name in participant_names:
        name_lower = participant_name.strip().lower()

        mask = pd.Series(False, index=deep_df.index)
        for col in ("subject", "counterparty"):
            if col in deep_df.columns:
                mask = mask | (deep_df[col].str.lower().str.strip() == name_lower)
        person_facts = deep_df[mask]

        if person_facts.empty:
            continue

        for _, fact in person_facts.head(10).iterrows():
            category = str(fact.get("category", "")).strip()
            subject = str(fact.get("subject", "")).strip()
            predicate = str(fact.get("predicate", "")).strip()
            obj = str(fact.get("object", "")).strip()
            amount = str(fact.get("amount", "")).strip()
            currency = str(fact.get("currency", "")).strip()
            amount_str = f" ({amount} {currency})" if amount and amount != "nan" else ""
            lines.append(f"- [{category}] {subject} {predicate} {obj}{amount_str}")

    return "\n".join(lines)


def build_brief_prompt(
    event: dict,
    attendees_ctx: list[dict],
    meeting_type: str,
) -> tuple[str, str]:
    ""



    start_dt = event.get("_start_dt")
    start_str = start_dt.strftime("%Y-%m-%d %H:%M %Z") if start_dt else "unknown"
    end = event.get("end", {})
    end_str = end.get("dateTime") or end.get("date", "")

    brief_language = os.environ.get("SBK_BRIEF_LANGUAGE", "English")
    system_prompt = (
        f"You are SBK, a personal intelligence system for {OWNER_LABEL}. "
        f"You generate concise, actionable pre-meeting briefs in {brief_language}. "
        "Be direct, no filler, no fluff. Use data, not speculation. "
        "If information is missing, say so clearly rather than guessing."
    )


    attendees_section = "\n".join(
        _format_attendee_for_prompt(ctx) for ctx in attendees_ctx if not ctx.get("is_self", False)
    )


    deep_facts_context = _gather_deep_facts_context(attendees_ctx)
    deep_facts_section = ""
    if deep_facts_context:
        deep_facts_section = f"""

## Deep Facts (financial, deal, commitment intelligence)
{deep_facts_context}
"""

    user_prompt = f"""Generate a pre-meeting brief for the following meeting.

## Meeting details
- Title: {event.get("summary", "No title")}
- Time: {start_str}
- End: {end_str}
- Type: {meeting_type}
- Calendar: {event.get("calendarName", "")}
- Organizer: {event.get("organizer", {}).get("email", "")}

## Attendees (cross-source data)
{attendees_section}
{deep_facts_section}
## Output format (in Italian)

Generate a markdown brief with these sections:

### Meeting header
Title, time, type classification.

### Partecipanti
For each attendee: who they are, role, company, relationship score. One paragraph each.

### Storico interazioni
Past interactions summary: email threads, meetings count, last contact date. Highlight any gaps or recent activity.

### Contesto chiave
Key context from network profile (if available), Attio CRM notes, relevant business context. What {OWNER_LABEL} should know going in.

### Spunti per la conversazione
3 to 5 suggested talking points based on the data. Be specific, not generic.

### Thread aperti
Any pending threads, recent email subjects, or open items that might come up.

### Deep facts
If deep facts are available (financial, deal, commitment data), include a concise section highlighting relevant business intelligence: active deals, financial exposure, pending commitments with deadlines.

Keep the brief under 800 words. Focus on actionable intelligence, not filler."""

    return system_prompt, user_prompt





def generate_brief(
    event: dict,
    data: SBKData,
    dry_run: bool = False,
) -> Path | None:
    ""



    summary = event.get("summary", "No title")
    event_id = event.get("id", "")
    start_dt = event.get("_start_dt")
    log.info(f'Processing: "{summary}" at {start_dt}')


    emails = get_attendee_emails(event)
    if not emails:
        log.info(f'  Skipping "{summary}": no external attendees')
        return None


    attendees_ctx = []
    for email in emails:
        ctx = assemble_attendee_context(email, data)
        attendees_ctx.append(ctx)
        found = ctx.get("found", False)
        name = ctx.get("name", email)
        log.debug(f"  Attendee {email}: found={found}, name={name}")


    meeting_type = classify_meeting_type(event, attendees_ctx)
    log.info(f"  Type: {meeting_type}")

    if meeting_type == "skip":
        log.info(f'  Skipping "{summary}": classified as skip')
        return None

    if dry_run:
        log.info(f'  [DRY RUN] Would generate brief for "{summary}" ({meeting_type})')
        for ctx in attendees_ctx:
            if not ctx.get("is_self", False):
                name = ctx.get("name", ctx.get("email", ""))
                score = ctx.get("score", 0)
                msgs = ctx.get("email_total_msgs", 0)
                log.info(f"    Attendee: {name} (score={score}, emails={msgs})")
        return None


    system_prompt, user_prompt = build_brief_prompt(event, attendees_ctx, meeting_type)
    log.info("  Calling Claude Sonnet for brief...")
    brief_content = call_claude(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=2048,
        temperature=0.3,
    )


    slug = slugify(summary)
    path = write_brief(brief_content, "meeting", slug=slug)


    time_str = start_dt.strftime("%H:%M") if start_dt else ""
    notify_macos(
        title=f"Brief: {summary}",
        message=f"{meeting_type} @ {time_str}",
        subtitle="SBK L3",
        group="sbk-brief",
    )

    log.info(f"  Brief written: {path}")
    return path





def process_upcoming(
    data: SBKData,
    hours: float,
    dry_run: bool = False,
    event_id: str | None = None,
) -> list[Path]:
    ""



    state = _load_state()
    briefs = []

    if event_id:

        matches = [ev for ev in data.calendar_events if ev.get("id") == event_id]
        if not matches:
            log.error(f"Event not found: {event_id}")
            return []
        events = matches

        for ev in events:
            start = ev.get("start", {})
            start_str = start.get("dateTime") or start.get("date", "")
            if start_str and "T" in start_str:
                try:
                    ev["_start_dt"] = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
    else:
        events = data.get_upcoming_events(hours=hours)

    log.info(f"Found {len(events)} upcoming event(s) within {hours}h window")

    for ev in events:
        ev_id = ev.get("id", "")


        if not event_id and _already_briefed(state, ev_id):
            log.debug(f'  Already briefed: "{ev.get("summary", "")}"')
            continue


        emails = get_attendee_emails(ev)
        attendees_ctx = [assemble_attendee_context(e, data) for e in emails]
        meeting_type = classify_meeting_type(ev, attendees_ctx)


        if not event_id and not is_within_timing(ev, meeting_type, hours):
            log.debug(f'  Outside timing window for {meeting_type}: "{ev.get("summary", "")}"')
            continue


        path = generate_brief(ev, data, dry_run=dry_run)

        if path:
            briefs.append(path)
            state[ev_id] = datetime.now(UTC).isoformat()
            _save_state(state)

    return briefs


def watch_loop(data: SBKData, hours: float, dry_run: bool = False):
    ""
    poll_interval = 15 * 60


    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info("Received shutdown signal, stopping watch loop...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log.info(f"Watch mode started. Polling every {poll_interval // 60} min, window={hours}h")

    while running:
        try:


            if "calendar_events" in data.__dict__:
                del data.__dict__["calendar_events"]

            briefs = process_upcoming(data, hours=hours, dry_run=dry_run)
            if briefs:
                log.info(f"Generated {len(briefs)} brief(s) this cycle")
            else:
                log.debug("No new briefs this cycle")
        except Exception:
            log.exception("Error in watch cycle")


        log.debug(f"Next poll in {poll_interval // 60} min")
        for _ in range(poll_interval):
            if not running:
                break
            time.sleep(1)

    log.info("Watch mode stopped")





def main():
    if not acquire_pid_lock("xs-l3-brief", logger=log):
        log.warning("Another instance is running, exiting")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="SBK L3 — Pre-meeting brief generator",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=2.0,
        help="Look-ahead window in hours (default: 2)",
    )
    parser.add_argument(
        "--event-id",
        type=str,
        default=None,
        help="Generate brief for a specific event ID",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll every 15 min for new meetings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without calling Claude",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-brief")

    log.info("SBK L3 Brief Generator starting")
    data = SBKData()

    if args.watch:
        watch_loop(data, hours=args.hours, dry_run=args.dry_run)
    else:
        briefs = process_upcoming(
            data,
            hours=args.hours,
            dry_run=args.dry_run,
            event_id=args.event_id,
        )
        if briefs:
            log.info(f"Done. Generated {len(briefs)} brief(s):")
            for p in briefs:
                log.info(f"  {p}")
        else:
            log.info("No briefs generated (no matching events or all already briefed)")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-brief", source="l3-brief", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
