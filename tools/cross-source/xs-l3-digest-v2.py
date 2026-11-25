#!/usr/bin/env python3
""




















from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    BRIEFS_DIR,
    DECAY_DIR,
    EMAILS_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    L3_DIR,
    NLP_DIR,
    OWN_EMAILS,
    OWNER_LABEL,
    OWNER_SPEAKER_LABELS,
    SLACK_CONVERSATIONS_DIR,
    WHATSAPP_CHATS_DIR,
)

log = logging.getLogger("sbk-l3-digest-v2")



STATE_FILE = L3_DIR / "digest-v2-state.json"

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


_SELF_SLACK_NAMES = set(OWNER_SPEAKER_LABELS)
_SELF_SLACK_IDS: set[str] = set()





@dataclass
class DigestItem:
    ""

    type: str
    source: str
    title: str
    content: str = ""
    datetime_str: str = ""
    persons: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class PersonContext:
    ""

    identifier: str
    name: str = ""
    organization: str = ""
    job_title: str = ""
    score: float = 0.0
    tier: str = ""
    decay_days: int = -1
    decay_alert: bool = False
    source_count: int = 0


@dataclass
class Story:
    ""

    title: str
    items: list[DigestItem] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    person_contexts: list[PersonContext] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    priority_score: int = 0
    research_context: str = ""
    story_hash: str = ""







def collect_calendar(data: SBKData, target_date: datetime) -> list[DigestItem]:
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

        if not (today_start <= dt_naive < tomorrow_noon):
            continue

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

        external = [e for e in attendee_emails if e not in own_emails_lower]
        summary = ev.get("summary", "(no title)")
        is_tomorrow = dt_naive.date() > target_date.date()


        event_type = _classify_event(summary, external)

        items.append(
            DigestItem(
                type="calendar",
                source="calendar",
                title=summary,
                content=f"Event: {summary}. {len(external)} external attendees.",
                datetime_str=dt_naive.isoformat(),
                persons=external,
                metadata={
                    "calendar": ev.get("calendarName", ""),
                    "is_tomorrow": is_tomorrow,
                    "event_type": event_type,
                    "attendee_count": len(external),
                },
            )
        )

    log.info(f"Calendar: {len(items)} events")
    return items


def _classify_event(summary: str, attendees: list[str]) -> str:
    ""
    s = summary.lower()
    if any(kw in s for kw in ("investor", "investitor", "fundrais", "round", "due diligence")):
        return "investor"
    if any(kw in s for kw in ("standup", "sync", "weekly", "team", "all hands")):
        return "team"
    if any(kw in s for kw in ("intro", "introduz", "presentaz")):
        return "intro"
    if any(kw in s for kw in ("board", "consiglio", "cda")):
        return "board"
    if any(kw in s for kw in ("legal", "legale", "avvocato", "lawyer", "contratto")):
        return "legal"
    if len(attendees) <= 1:
        return "1on1"
    return "meeting"


def collect_email(data: SBKData, target_date: datetime, hours: int = 24) -> list[DigestItem]:
    ""
    items = []
    own_emails_lower = {e.lower() for e in OWN_EMAILS}
    cutoff = target_date - timedelta(hours=hours)
    cutoff_ts = pd.Timestamp(cutoff, tz="UTC")

    threads = data.threads
    recent = threads[threads["date_end"] >= cutoff_ts].copy()


    thread_bodies = _load_email_bodies(recent)

    for _, row in recent.iterrows():
        participants_raw = row.get("participants", "") or ""
        participants = [p.strip().lower() for p in participants_raw.split(",") if p.strip()]

        has_own = any(p in own_emails_lower for p in participants)
        if not has_own:
            continue

        other_participants = [p for p in participants if p not in own_emails_lower]
        if not other_participants:
            continue

        subject = str(row.get("subject", ""))
        thread_id = str(row.get("thread_id", ""))


        body = thread_bodies.get(thread_id, "")
        content = body[:500] if body else f"Subject: {subject}"

        items.append(
            DigestItem(
                type="email",
                source="email",
                title=subject,
                content=content,
                datetime_str=str(row.get("date_end", "")),
                persons=other_participants,
                metadata={
                    "thread_id": thread_id,
                    "msg_count": int(row.get("msg_count", 0)),
                    "account": str(row.get("account", "")),
                    "labels": str(row.get("labels", "")),
                    "thread_count": len(participants),
                },
            )
        )

    log.info(f"Email: {len(items)} threads in last {hours}h")
    return items


def _load_email_bodies(recent_threads: pd.DataFrame) -> dict[str, str]:
    ""



    bodies: dict[str, str] = {}
    target_tids = set(recent_threads["thread_id"].astype(str).tolist())

    if not EMAILS_DIR.exists() or not target_tids:
        return bodies

    for account_dir in sorted(EMAILS_DIR.iterdir()):
        msg_path = account_dir / "messages.parquet"
        if not msg_path.exists():
            continue
        try:
            msg_df = pd.read_parquet(
                msg_path,
                columns=["thread_id", "date", "from_addr", "body_text"],
            )
            msg_df["thread_id"] = msg_df["thread_id"].astype(str)
            relevant = msg_df[msg_df["thread_id"].isin(target_tids)].copy()
            if relevant.empty:
                continue


            relevant = relevant.dropna(subset=["body_text"])
            relevant["body_text"] = relevant["body_text"].astype(str).str.strip()
            relevant = relevant[relevant["body_text"].ne("") & relevant["body_text"].ne("nan")]
            if relevant.empty:
                continue


            relevant = relevant.sort_values("date", ascending=False)
            latest = relevant.groupby("thread_id").first().reset_index()
            for _, row in latest.iterrows():
                sender = str(row.get("from_addr", ""))
                body = str(row["body_text"])
                bodies[str(row["thread_id"])] = f"{sender}: {body}"
        except Exception as e:
            log.warning(f"Failed to load email bodies from {account_dir.name}: {e}")

    return bodies


def collect_slack(data: SBKData, target_date: datetime, hours: int = 24) -> list[DigestItem]:
    ""
    items = []
    cutoff = target_date - timedelta(hours=hours)

    if not SLACK_CONVERSATIONS_DIR.exists():
        return items

    cutoff_ts = cutoff.timestamp()

    from slack_esclusi import e_escluso, esclusi

    fuori = esclusi()

    for fpath in sorted(SLACK_CONVERSATIONS_DIR.glob("*.json")):
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(raw, dict) or e_escluso(raw, fuori):
            continue

        channel = raw.get("channel", fpath.stem)
        messages = raw.get("messages", [])

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            ts = float(msg.get("ts", "0") or 0)
            if ts < cutoff_ts:
                continue

            user_raw = str(msg.get("user", "unknown"))
            text = str(msg.get("text", "")).strip()
            if not text:
                continue


            user_profile = msg.get("user_profile") or {}
            display_name = (
                user_profile.get("real_name") or user_profile.get("display_name") or user_raw
            )


            if display_name.lower() in _SELF_SLACK_NAMES or user_raw in _SELF_SLACK_IDS:
                continue

            msg_text = text[:300]
            items.append(
                DigestItem(
                    type="slack",
                    source="slack",
                    title=f"Slack from {display_name} in #{channel}",
                    content=msg_text,
                    datetime_str=datetime.fromtimestamp(ts, tz=UTC).isoformat(),
                    persons=[display_name],
                    metadata={
                        "channel": channel,
                        "thread_ts": msg.get("thread_ts", ""),
                        "user_id": user_raw if user_raw != display_name else "",
                    },
                )
            )

    log.info(f"Slack: {len(items)} messages in last {hours}h")
    return items


def collect_whatsapp(target_date: datetime, hours: int = 24) -> list[DigestItem]:
    ""
    items = []
    if not WHATSAPP_CHATS_DIR.exists():
        return items

    cutoff = target_date - timedelta(hours=hours)

    for fpath in sorted(WHATSAPP_CHATS_DIR.glob("*.json")):
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        messages = raw if isinstance(raw, list) else raw.get("messages", [])
        chat_name = fpath.stem

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            date_str = str(msg.get("date", "") or msg.get("timestamp", ""))
            if not date_str:
                continue
            try:
                msg_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                msg_naive = msg_dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                continue

            if msg_naive < cutoff:
                continue

            sender = str(msg.get("sender", "") or msg.get("from", ""))
            text = str(msg.get("body", "") or msg.get("text", "")).strip()
            if not text or sender.strip().lower() in OWNER_SPEAKER_LABELS:
                continue

            items.append(
                DigestItem(
                    type="whatsapp",
                    source="whatsapp",
                    title=f"WhatsApp from {sender} ({chat_name})",
                    content=text[:300],
                    datetime_str=msg_naive.isoformat(),
                    persons=[sender],
                    metadata={"chat": chat_name},
                )
            )

    log.info(f"WhatsApp: {len(items)} messages in last {hours}h")
    return items


def collect_decay_alerts(target_date: datetime) -> list[DigestItem]:
    ""
    items = []
    date_str = target_date.strftime("%Y%m%d")
    alerts_file = DECAY_DIR / f"alerts-{date_str}.json"

    if not alerts_file.exists():

        alert_files = sorted(DECAY_DIR.glob("alerts-*.json"))
        if alert_files:
            alerts_file = alert_files[-1]
        else:
            return items

    try:
        alerts = json.loads(alerts_file.read_text())
        for alert in alerts[:5]:
            name = alert.get("name", "")
            email = alert.get("email", "")
            items.append(
                DigestItem(
                    type="decay",
                    source="decay",
                    title=alert.get("message", f"Relationship cooling: {name}"),
                    content=f"Current score: {alert.get('current_score', 0)}, drop: {alert.get('score_drop', 0)}",
                    datetime_str=target_date.isoformat(),
                    persons=[email] if email else [name],
                    metadata={
                        "score_drop": alert.get("score_drop", 0),
                        "current_score": alert.get("current_score", 0),
                        "person_name": name,
                    },
                )
            )
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to load decay alerts: {e}")

    log.info(f"Decay alerts: {len(items)}")
    return items


def collect_followup_reminders(target_date: datetime, max_items: int = 5) -> list[DigestItem]:
    ""
    items = []
    action_items_file = NLP_DIR / "action-items.parquet"
    state_file = NLP_DIR / "followup-state.json"

    if not action_items_file.exists():
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
    except (ImportError, AttributeError, FileNotFoundError):
        return items

    for _, row in df.iterrows():
        deadline_str = str(row.get("deadline", "") or "")
        if not deadline_str or deadline_str == "nan":
            continue

        meeting_date = str(row.get("date", "") or "")
        parsed = _parse_deadline(deadline_str, meeting_date if meeting_date else None)
        if parsed is None:
            continue

        if parsed.tzinfo is None and upcoming_cutoff.tzinfo is not None:
            from datetime import UTC

            parsed = parsed.replace(tzinfo=UTC)
        elif parsed.tzinfo is not None and upcoming_cutoff.tzinfo is None:
            parsed = parsed.replace(tzinfo=None)
        if parsed > upcoming_cutoff:
            continue

        item_id = f"{row.get('meeting_id', '')}|{row.get('action_text', '')[:50]}"
        if item_id in dismissed:
            continue

        is_overdue = parsed < today
        action_text = str(row.get("action_text", ""))[:120]
        assignee = str(row.get("assignee", "") or row.get("speaker", ""))

        items.append(
            DigestItem(
                type="followup",
                source="nlp",
                title=action_text,
                content=f"{'OVERDUE' if is_overdue else 'Due soon'}: {action_text}",
                datetime_str=parsed.isoformat(),
                persons=[assignee] if assignee and assignee != "nan" else [],
                metadata={
                    "meeting_title": str(row.get("meeting_title", "")),
                    "deadline_raw": deadline_str,
                    "is_overdue": is_overdue,
                },
            )
        )

    items.sort(key=lambda x: (not x.metadata.get("is_overdue", False), x.datetime_str))
    items = items[:max_items]
    log.info(f"Follow-up: {len(items)} items")
    return items


def collect_recent_decisions(
    target_date: datetime, days: int = 7, max_items: int = 5
) -> list[DigestItem]:
    ""
    items = []
    decisions_file = NLP_DIR / "decisions.parquet"
    if not decisions_file.exists():
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
        text = str(row.get("decision_text", ""))[:120]
        speaker = str(row.get("speaker", ""))
        items.append(
            DigestItem(
                type="decision",
                source="nlp",
                title=text,
                content=text,
                datetime_str=str(row.get("date", "")),
                persons=[speaker] if speaker and speaker != "nan" else [],
                metadata={"meeting_title": str(row.get("meeting_title", ""))},
            )
        )

    log.info(f"Decisions: {len(items)} items")
    return items


def collect_pending_events(max_items: int = 5) -> list[DigestItem]:
    ""
    items = []
    resolved_path = L3_DIR / "resolved-events.parquet"
    if not resolved_path.exists():
        return items

    try:
        df = pd.read_parquet(resolved_path)
    except Exception as e:
        log.warning(f"Failed to load resolved events: {e}")
        return items

    pending = df[df["resolution_status"] == "pending"].head(max_items)
    for _, row in pending.iterrows():
        summary = str(row.get("summary", ""))
        items.append(
            DigestItem(
                type="pending_event",
                source="calendar",
                title=f"Event without follow-up: {summary}",
                content=f"Type: {row.get('event_type', '')}, {row.get('attendee_count', 0)} attendees",
                datetime_str=str(row.get("start_datetime", "")),
                persons=str(row.get("attendee_emails", "")).split(",")
                if row.get("attendee_emails")
                else [],
                metadata={
                    "event_type": str(row.get("event_type", "")),
                    "attendee_count": int(row.get("attendee_count", 0)),
                },
            )
        )

    log.info(f"Pending events: {len(items)}")
    return items


def collect_knowledge_changes(target_date: datetime) -> list[dict]:
    ""
    changes: list[dict] = []
    cutoff = target_date - timedelta(hours=24)
    cutoff_ts = cutoff.timestamp()

    for domain_dir in ("person", "organization", "deal", "commitment"):
        entity_dir = KNOWLEDGE_ENTITIES_DIR / domain_dir
        if not entity_dir.exists():
            continue
        for jf in entity_dir.glob("*.json"):
            if jf.stat().st_mtime < cutoff_ts:
                continue
            try:
                profile = json.loads(jf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            entity_name = profile.get("canonical_name", jf.stem)
            entity_id = profile.get("entity_id", jf.stem)
            all_facts = profile.get("facts", [])

            expired_by_attr: dict[str, list[dict]] = {}
            for f in all_facts:
                if f.get("expired_at"):
                    attr = f.get("attribute", "")
                    expired_by_attr.setdefault(attr, []).append(f)

            for fact in all_facts:
                expired = fact.get("expired_at")
                created = fact.get("created_at", "")

                if created and created[:10] >= cutoff.strftime("%Y-%m-%d"):
                    change: dict = {
                        "entity": entity_name,
                        "entity_id": entity_id,
                        "attribute": fact.get("attribute", ""),
                        "value": fact.get("value", ""),
                        "change_type": "new",
                    }

                    attr = fact.get("attribute", "")
                    for ef in expired_by_attr.get(attr, []):
                        change["old_value"] = ef.get("value", "")
                        break
                    changes.append(change)

                elif expired and expired[:10] >= cutoff.strftime("%Y-%m-%d"):
                    changes.append(
                        {
                            "entity": entity_name,
                            "entity_id": entity_id,
                            "attribute": fact.get("attribute", ""),
                            "value": fact.get("value", ""),
                            "change_type": "expired",
                        }
                    )

    log.info(f"Knowledge changes: {len(changes)}")
    return changes







def enrich_persons(all_items: list[DigestItem], data: SBKData) -> dict[str, PersonContext]:
    ""
    person_cache: dict[str, PersonContext] = {}


    all_persons: set[str] = set()
    for item in all_items:
        for p in item.persons:
            if p and p.strip():
                all_persons.add(p.strip().lower())

    log.info(f"Enriching {len(all_persons)} unique persons...")


    decay_data = _load_decay_data()

    for identifier in all_persons:
        if identifier in person_cache:
            continue

        resolved = data.resolve_person(identifier)
        if resolved:
            name = resolved.get("name", identifier)
            email = resolved.get("email", identifier)
            score = resolved.get("score", 0)


            person_id = str(resolved.get("person_id", "")).lower()
            decay_info = (
                decay_data.get(email, {})
                or decay_data.get(name.lower(), {})
                or decay_data.get(person_id, {})
            )
            tier = str(decay_info.get("tier", ""))
            days_since = int(decay_info.get("days_since_contact", -1))
            has_alert = decay_info.get("has_alert", False)

            person_cache[identifier] = PersonContext(
                identifier=email if "@" in str(email) else identifier,
                name=name,
                organization=str(
                    resolved.get("organization") or resolved.get("attio_company") or ""
                ),
                job_title=str(
                    resolved.get("attio_job_title") or resolved.get("linkedin_headline") or ""
                ),
                score=float(score) if score else 0.0,
                tier=tier,
                decay_days=days_since,
                decay_alert=has_alert,
                source_count=int(resolved.get("source_count", 0)),
            )
        else:
            person_cache[identifier] = PersonContext(
                identifier=identifier,
                name=identifier,
            )

    log.info(
        f"Enriched {len(person_cache)} persons ({sum(1 for p in person_cache.values() if p.score > 0)} with score)"
    )
    return person_cache


def _load_decay_data() -> dict[str, dict]:
    ""



    result: dict[str, dict] = {}
    decay_state_file = DECAY_DIR / "decay-state.json"

    if not decay_state_file.exists():
        return result

    try:
        state = json.loads(decay_state_file.read_text())
        for pid, entry in state.items():
            if not isinstance(entry, dict):
                continue
            days_since = entry.get("days_since", 0)
            expected_gap = entry.get("expected_gap", 999)
            info = {
                "tier": entry.get("tier", ""),
                "days_since_contact": int(days_since) if days_since else -1,
                "has_alert": (
                    days_since > expected_gap * 1.5 if days_since and expected_gap else False
                ),
            }
            result[pid.lower()] = info
    except (json.JSONDecodeError, OSError):
        pass

    return result







class _UnionFind:
    ""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def correlate_stories(
    all_items: list[DigestItem],
    person_cache: dict[str, PersonContext],
) -> list[Story]:
    ""




    if not all_items:
        return []

    n = len(all_items)
    uf = _UnionFind(n)


    item_persons: list[set[str]] = []
    for item in all_items:
        normalized = set()
        for p in item.persons:
            p_lower = p.strip().lower()
            if p_lower:

                ctx = person_cache.get(p_lower)
                if ctx and ctx.name:
                    normalized.add(ctx.name.lower())
                normalized.add(p_lower)
        item_persons.append(normalized)


    for i in range(n):
        for j in range(i + 1, n):

            if item_persons[i] & item_persons[j]:
                uf.union(i, j)
                continue


            if _time_proximity(all_items[i], all_items[j], hours=4):
                keywords_i = _extract_keywords(all_items[i])
                keywords_j = _extract_keywords(all_items[j])
                if keywords_i & keywords_j:
                    uf.union(i, j)


    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    stories: list[Story] = []
    for cluster_indices in clusters.values():
        cluster_items = [all_items[idx] for idx in cluster_indices]


        cluster_persons_set: set[str] = set()
        for idx in cluster_indices:
            cluster_persons_set |= item_persons[idx]

        story_persons = sorted(cluster_persons_set - {"unknown", ""})
        story_sources = sorted({item.source for item in cluster_items})

        title = _generate_story_title(cluster_items, story_persons, person_cache)
        priority = score_story(cluster_items, story_persons, story_sources, person_cache)

        hash_input = (
            "|".join(sorted(story_persons))
            + "|"
            + "|".join(sorted(_extract_topic_keywords(cluster_items)))
        )
        story_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

        pcontexts = []
        for p in story_persons:
            ctx = person_cache.get(p.lower())
            if ctx:
                pcontexts.append(ctx)

        stories.append(
            Story(
                title=title,
                items=cluster_items,
                persons=story_persons,
                person_contexts=pcontexts,
                sources=story_sources,
                priority_score=priority,
                story_hash=story_hash,
            )
        )


    stories.sort(key=lambda s: s.priority_score, reverse=True)
    log.info(f"Correlated into {len(stories)} stories")
    return stories


def _time_proximity(a: DigestItem, b: DigestItem, hours: int = 4) -> bool:
    ""
    try:
        dt_a = datetime.fromisoformat(a.datetime_str.replace("Z", "+00:00")).replace(tzinfo=None)
        dt_b = datetime.fromisoformat(b.datetime_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return abs((dt_a - dt_b).total_seconds()) < hours * 3600
    except (ValueError, TypeError, AttributeError):
        return False


def _extract_keywords(item: DigestItem) -> set[str]:
    ""
    text = f"{item.title} {item.content}".lower()

    stop = {
        "il",
        "la",
        "lo",
        "le",
        "un",
        "una",
        "di",
        "da",
        "in",
        "con",
        "su",
        "per",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "with",
        "on",
        "at",
        "che",
        "non",
        "ho",
        "ha",
        "sono",
        "e",
        "is",
        "re",
        "fwd",
    }
    words = set(re.findall(r"\b[a-zA-Z\u00C0-\u024F]{3,}\b", text))
    return words - stop


def _extract_topic_keywords(items: list[DigestItem]) -> set[str]:
    ""
    all_kw: set[str] = set()
    for item in items:
        all_kw |= _extract_keywords(item)

    return set(sorted(all_kw, key=len, reverse=True)[:5])


def _generate_story_title(
    items: list[DigestItem],
    persons: list[str],
    person_cache: dict[str, PersonContext],
) -> str:
    ""

    types = {item.type for item in items}
    sources = {item.source for item in items}


    primary_name = ""
    if persons:
        ctx = person_cache.get(persons[0].lower())
        if ctx and ctx.name:
            primary_name = ctx.name


    if types == {"calendar"} and len(items) == 1:
        return items[0].title


    if "calendar" in types and "email" in types:
        topic = items[0].title[:40]
        if primary_name:
            return f"{topic} with {primary_name}"
        return topic


    if types == {"decay"}:
        if primary_name:
            return f"Relationship {primary_name}"
        return "Relationship alert"


    if types == {"followup"}:
        return f"Follow-up: {items[0].title[:50]}"


    title = items[0].title[:40]
    if primary_name and primary_name.lower() not in title.lower():
        title += f" ({primary_name})"
    if len(sources) > 1:
        title += f" [{'+'.join(sorted(sources))}]"
    return title





def score_story(
    items: list[DigestItem],
    persons: list[str],
    sources: list[str],
    person_cache: dict[str, PersonContext],
) -> int:
    ""
    score = 0


    max_person_score = 0.0
    for p in persons:
        ctx = person_cache.get(p.lower())
        if ctx and ctx.score > max_person_score:
            max_person_score = ctx.score
    if max_person_score >= 70:
        score += 35
    elif max_person_score >= 50:
        score += 25
    elif max_person_score >= 30:
        score += 15


    score += min(25, len(sources) * 10)


    for item in items:
        try:
            dt = datetime.fromisoformat(item.datetime_str.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
            hours_away = (dt - datetime.now()).total_seconds() / 3600
            if 0 <= hours_away <= 2:
                score += 20
                break
            elif -2 <= hours_away < 0:
                score += 10
                break
            elif 0 < hours_away <= 48:
                score += 15
                break
        except (ValueError, TypeError, AttributeError):
            continue


    for p in persons:
        ctx = person_cache.get(p.lower())
        if ctx and ctx.decay_alert:
            score += 10
            break


    for item in items:
        text = f"{item.title} {item.content}".lower()
        if any(kw in text for kw in URGENCY_KEYWORDS):
            score += 10
            break

    return min(score, 100)







def research_stories(stories: list[Story], max_stories: int = 10) -> list[Story]:
    ""
    try:
        import importlib.util

        search_path = _THIS_DIR / "xs-l3-search.py"
        spec = importlib.util.spec_from_file_location("xs_l3_search", search_path)
        search_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(search_mod)
    except Exception as e:
        log.warning(f"Search module unavailable, skipping research: {e}")
        return stories

    try:
        table = search_mod.open_lancedb()
    except Exception as e:
        log.warning(f"LanceDB unavailable, skipping research: {e}")
        return stories

    for story in stories[:max_stories]:

        query_parts = [story.title]
        for p in story.persons[:3]:
            query_parts.append(p)
        query = " ".join(query_parts)

        try:
            query_vector = list(search_mod.embed_query(query))
            results = search_mod.hybrid_search(
                table=table,
                query=query,
                query_vector=query_vector,
                top_k=3,
                rerank=False,
            )
            if results:
                context_parts = []
                for r in results:
                    source = r.get("source_type", "")
                    date = r.get("date", "")
                    text = r.get("text", "")[:200]
                    context_parts.append(f"[{source} {date}] {text}")
                story.research_context = "\n".join(context_parts)
        except Exception as e:
            log.debug(f"Research failed for story '{story.title[:30]}': {e}")

    researched_count = sum(1 for s in stories if s.research_context)
    log.info(f"Research: {researched_count}/{min(len(stories), max_stories)} stories enriched")
    return stories







def build_synthesis_prompt(
    stories: list[Story],
    target_date: datetime,
    knowledge_changes: list[dict] | None = None,
) -> str:
    ""
    date_str = target_date.strftime("%A %d %B %Y")
    parts = [f"Date: {date_str}\n"]

    for i, story in enumerate(stories[:15], 1):
        parts.append(f"--- STORY {i}: {story.title} (priority: {story.priority_score}) ---")
        parts.append(f"Sources: {', '.join(story.sources)}")


        if story.person_contexts:
            person_lines = []
            for pc in story.person_contexts[:5]:
                line = f"  {pc.name}"
                if pc.organization:
                    line += f" ({pc.organization})"
                if pc.job_title:
                    line += f" - {pc.job_title}"
                if pc.score > 0:
                    line += f" [score: {pc.score:.0f}]"
                if pc.tier:
                    line += f" [tier: {pc.tier}]"
                if pc.decay_alert:
                    line += f" [DECAY ALERT, {pc.decay_days}d]"
                person_lines.append(line)
            parts.append("People:\n" + "\n".join(person_lines))


        content_lines = []
        for item in story.items[:5]:
            content_lines.append(f"  [{item.type}] {item.content[:300]}")
        parts.append("Content:\n" + "\n".join(content_lines))


        if story.research_context:
            parts.append(f"Historical context:\n  {story.research_context[:500]}")

        parts.append("")

    if knowledge_changes:
        parts.append("--- KNOWLEDGE CHANGES ---")
        for kc in knowledge_changes[:5]:
            parts.append(
                f"  {kc['entity']}: {kc['attribute']} = {kc['value']} ({kc['change_type']})"
            )
        parts.append("")

    return "\n".join(parts)


def synthesize_digest(prompt_data: str, target_date: datetime) -> str:
    ""
    date_str = target_date.strftime("%d/%m/%Y")

    system = (
        f"You are the personal intelligence assistant of {OWNER_LABEL}. "
        "Generate a morning digest based on real STORIES, not notifications. "
        "Each story has full context: email/Slack/WhatsApp content, people profiles, history. "
        "Your job is to give ACTIONABLE INTELLIGENCE: what is happening, why it matters, what to do."
    )

    prompt = f"""Generate the intelligence digest for {date_str}.

{prompt_data}

Required format:
# Digest {date_str}

## TL;DR
3-5 lines with the key stories and WHY they matter. Do not list, synthesize.

## Urgent
Max 3 stories that require immediate action.
For each story: full context + specific action + suggested deadline.

## Today's Stories
For each story: title, context, action, deadline.
Ordered by priority.

## Follow-up
Overdue or due-soon action items with context.

## Relationships
Decay alerts with person context and a suggested action.

## Knowledge Updates
If there are entity resolution changes (merges) or important fact updates,
include a brief section with max 3-4 bullet points.

Rules:
1. Omit empty sections
2. For each item: who, what, WHY it matters, specific action
3. Write everything in English
4. Be direct, no fluff
5. Max 500 words total"""

    return call_claude(prompt, system=system, max_tokens=1500, temperature=0.3)







def load_state() -> dict:
    ""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"stories_shown": {}, "last_digest_date": None}


def save_state(state: dict):
    ""
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    shown = state.get("stories_shown", {})
    state["stories_shown"] = {
        h: dates for h, dates in shown.items() if any(d >= cutoff for d in dates)
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def should_show_story(story_hash: str, state: dict, today: str) -> bool:
    ""
    shown_dates = state.get("stories_shown", {}).get(story_hash, [])
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


def record_story_shown(story_hash: str, state: dict, today: str):
    ""
    shown = state.setdefault("stories_shown", {})
    dates = shown.setdefault(story_hash, [])
    if today not in dates:
        dates.append(today)







def write_outputs(
    digest_md: str,
    stories: list[Story],
    target_date: datetime,
    cost_usd: float,
    elapsed_sec: float,
    knowledge_changes: list[dict] | None = None,
) -> tuple[Path, Path]:
    ""
    date_slug = target_date.strftime("%Y%m%d")


    md_path = write_brief(digest_md, "digest-v2")


    json_data = {
        "date": target_date.strftime("%Y-%m-%d"),
        "generated_at": datetime.now(UTC).isoformat(),
        "stats": {
            "story_count": len(stories),
            "source_types": sorted({s for st in stories for s in st.sources}),
            "person_count": len({p for st in stories for p in st.persons}),
            "cost_usd": round(cost_usd, 4),
            "elapsed_sec": round(elapsed_sec, 1),
        },
        "stories": [],
    }

    for story in stories:
        json_data["stories"].append(
            {
                "title": story.title,
                "priority_score": story.priority_score,
                "story_hash": story.story_hash,
                "persons": story.persons,
                "sources": story.sources,
                "item_count": len(story.items),
                "person_contexts": [
                    {
                        "name": pc.name,
                        "organization": pc.organization,
                        "score": pc.score,
                        "tier": pc.tier,
                        "decay_alert": pc.decay_alert,
                    }
                    for pc in story.person_contexts
                ],
                "items": [
                    {
                        "type": item.type,
                        "source": item.source,
                        "title": item.title,
                        "content": item.content[:200],
                        "datetime": item.datetime_str,
                    }
                    for item in story.items
                ],
            }
        )

    if knowledge_changes:
        json_data["knowledge_changes"] = knowledge_changes

    json_path = BRIEFS_DIR / f"digest-v2-{date_slug}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False, default=str))

    log.info(f"Outputs: {md_path.name} + {json_path.name}")
    return md_path, json_path







def main():
    parser = argparse.ArgumentParser(description="SBK Digest V2: Intelligence Engine")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show stories without Claude synthesis"
    )
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--no-research", action="store_true", help="Skip vector search for historical context"
    )
    parser.add_argument("--force", action="store_true", help="Bypass today-already-run guard")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-digest-v2")
    t0 = time.time()


    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            log.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)

    today_str = target_date.strftime("%Y-%m-%d")
    log.info(f"=== Digest V2 for {today_str} ===")


    state = load_state()


    if not args.force and not args.dry_run and state.get("last_digest_date") == today_str:
        log.info(f"Digest already run today ({today_str}), skipping. Use --force to override.")
        return


    log.info("Phase 1: COLLECT")
    data = SBKData()

    all_items: list[DigestItem] = []
    all_items.extend(collect_calendar(data, target_date))
    all_items.extend(collect_email(data, target_date, hours=24))
    all_items.extend(collect_slack(data, target_date, hours=24))
    all_items.extend(collect_whatsapp(target_date, hours=24))
    all_items.extend(collect_decay_alerts(target_date))
    all_items.extend(collect_followup_reminders(target_date))
    all_items.extend(collect_recent_decisions(target_date, days=7))
    all_items.extend(collect_pending_events())


    knowledge_changes = collect_knowledge_changes(target_date)
    try:
        from xs_l3_knowledge_alerts import filter_changes_for_digest

        knowledge_changes = filter_changes_for_digest(knowledge_changes)
    except ImportError:
        log.debug("xs_l3_knowledge_alerts not available, keeping all changes")


    try:
        from golden_record import collect_golden_record_changes

        gr_changes = collect_golden_record_changes(since=target_date - timedelta(hours=24))
        if gr_changes:
            knowledge_changes.extend(
                {
                    "entity": ", ".join(c.get("entities", [])[:3]),
                    "entity_id": c.get("entities", [""])[0],
                    "attribute": "entity_resolution",
                    "value": f"{c['type']} ({c.get('method', '')})"
                    if c["type"] == "new_merge"
                    else c["type"],
                    "change_type": c["type"],
                }
                for c in gr_changes
            )
            log.info(f"  Golden record changes: {len(gr_changes)}")
    except ImportError:
        log.debug("golden_record not available, skipping golden record changes")

    log.info(f"  Total items collected: {len(all_items)}")

    if not all_items:
        log.info("No items to include. Skipping.")
        return


    log.info("Phase 2: ENRICH")
    person_cache = enrich_persons(all_items, data)


    log.info("Phase 3: CORRELATE")
    stories = correlate_stories(all_items, person_cache)


    if not args.dry_run:
        filtered_stories = []
        for story in stories:
            if should_show_story(story.story_hash, state, today_str):
                record_story_shown(story.story_hash, state, today_str)
                filtered_stories.append(story)
            else:
                log.debug(f"Skipping story (anti-fatigue): {story.title[:40]}")
        stories = filtered_stories


    if not args.no_research:
        log.info("Phase 4: RESEARCH")
        stories = research_stories(stories, max_stories=10)
    else:
        log.info("Phase 4: RESEARCH (skipped: --no-research)")


    if args.dry_run:
        print("\n=== DRY RUN: Digest V2 Stories ===\n")
        for i, story in enumerate(stories, 1):
            print(f"{i}. [{story.priority_score:3d}] {story.title}")
            print(
                f"   Sources: {', '.join(story.sources)} | Persons: {', '.join(story.persons[:3])}"
            )
            for item in story.items[:3]:
                print(f"   [{item.type}] {item.content[:80]}")
            if story.research_context:
                print(f"   Research: {story.research_context[:100]}...")
            print()

        print("=== Stats ===")
        print(f"  Items: {len(all_items)}")
        print(f"  Stories: {len(stories)}")
        print(f"  Persons: {len(person_cache)}")
        print(f"  Sources: {sorted({i.source for i in all_items})}")
        print(f"  Elapsed: {time.time() - t0:.1f}s")
        return


    log.info("Phase 5: SYNTHESIZE")
    prompt_data = build_synthesis_prompt(stories, target_date, knowledge_changes)
    digest_md = synthesize_digest(prompt_data, target_date)

    elapsed = time.time() - t0


    prompt_tokens = len(prompt_data) // 4
    output_tokens = len(digest_md) // 4
    cost = (prompt_tokens * 3.0 + output_tokens * 15.0) / 1_000_000


    md_path, json_path = write_outputs(
        digest_md, stories, target_date, cost, elapsed, knowledge_changes
    )


    state["last_digest_date"] = today_str
    save_state(state)


    urgent_count = sum(1 for s in stories if s.priority_score >= 70)
    msg = f"{len(stories)} stories, {urgent_count} urgent"
    notify_macos(title="Digest V2", message=msg, group="sbk-digest-v2")

    print(f"\nDigest V2 generated: {md_path}")
    print(f"  {len(stories)} stories, {urgent_count} urgent, {len(person_cache)} people")
    print(f"  JSON: {json_path}")
    print(f"  Time: {elapsed:.1f}s, Cost: ~${cost:.4f}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-digest-v2", source="l3-digest-v2", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
