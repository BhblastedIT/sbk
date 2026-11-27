"""Daily task board: collects what needs you today (meetings to prepare, emails to answer, Slack threads, action
items, people to reconnect with, entity reviews, Notion milestones), scores and deduplicates them and sorts them
in the Eisenhower quadrants within a daily budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"
_XS_DIR = _TOOLS_DIR / "cross-source"

for p in (_TOOLS_DIR, _XS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env", override=True)

import pandas as pd
from xs_l3_common import SBKData

from sbk_config import (
    DATA_ROOT,
    DECAY_DIR,
    L3_DIR,
    NLP_DIR,
    OWN_EMAILS,
    TASKS_DIR,
    is_own_name,
    is_owner_speaker,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xs-l3-tasks")





@dataclass
class TaskItem:
    type: str = ""
    title: str = ""
    person: str = ""
    person_email: str = ""
    person_tier: str = "unknown"
    urgency: str = ""
    deadline: str = ""
    context: dict = field(default_factory=dict)
    what_unlocks: str = ""
    source: str = ""
    priority_score: int = 0
    quadrant: str = "Q4"
    status: str = "pending"
    external_id: str = ""





def _load_tier_map() -> dict[str, str]:
    ""
    tier_map: dict[str, str] = {}
    decay_path = DECAY_DIR / "decay-state.json"
    contacts_path = DATA_ROOT / "enriched" / "contacts-merged.parquet"


    pid_tier: dict[str, str] = {}
    if decay_path.exists():
        try:
            data = json.loads(decay_path.read_text())
            for pid, info in data.items():
                if isinstance(info, dict):
                    pid_tier[pid] = info.get("tier", "unknown")
        except (json.JSONDecodeError, KeyError):
            pass


    if contacts_path.exists():
        try:
            df = pd.read_parquet(contacts_path, columns=["email", "person_id"])
            for _, row in df.iterrows():
                email = str(row.get("email", "")).strip().lower()
                pid = str(row.get("person_id", ""))
                if email and pid:
                    tier_map[email] = pid_tier.get(pid, "unknown")
        except Exception:
            pass

    return tier_map





def _make_external_id(task_type: str, *keys: str) -> str:
    ""
    raw = f"{task_type}|{'|'.join(str(k) for k in keys)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]





def collect_calendar_prep(target_date: date) -> list[dict]:
    ""
    path = L3_DIR / "resolve" / "resolved-events.parquet"
    if not path.exists():
        log.debug("No resolved-events.parquet")
        return []

    try:
        df = pd.read_parquet(path)
    except Exception as e:
        log.warning("Error reading resolved-events: %s", e)
        return []

    items = []
    cutoff = datetime.combine(target_date, datetime.min.time()) + timedelta(hours=48)
    now = datetime.combine(target_date, datetime.min.time())

    for _, row in df.iterrows():
        status = str(row.get("status", "")).lower()
        if status not in ("pending", "future"):
            continue

        start = row.get("start_datetime") or row.get("start")
        if pd.isna(start):
            continue

        try:
            if isinstance(start, str):
                start_dt = pd.to_datetime(start)
            else:
                start_dt = pd.Timestamp(start)
            start_dt = start_dt.tz_localize(None) if start_dt.tzinfo else start_dt
        except Exception:
            continue

        if start_dt < pd.Timestamp(now) or start_dt > pd.Timestamp(cutoff):
            continue

        summary = str(row.get("summary", "Untitled event"))
        organizer = str(row.get("organizer", ""))

        items.append(
            {
                "type": "calendar_prep",
                "title": f"Prepare: {summary}",
                "person": organizer,
                "person_email": str(row.get("organizer_email", "")),
                "deadline": str(start_dt.date()),
                "urgency": "today" if start_dt.date() == target_date else "1-2gg",
                "context": {"event_id": str(row.get("event_id", "")), "start": str(start_dt)},
                "what_unlocks": f"Meeting prepared: {summary}",
                "source": "calendar",
                "external_id": _make_external_id(
                    "calendar_prep", str(row.get("event_id", "")), summary
                ),
            }
        )
        if len(items) >= 10:
            break

    return items


def collect_email_replies(target_date: date) -> list[dict]:
    ""
    data = SBKData()
    try:
        threads = data.email_threads
    except Exception:
        log.debug("No email_threads available")
        return []

    if threads.empty:
        return []

    items = []
    cutoff_24h = pd.Timestamp(
        datetime.combine(target_date, datetime.min.time()) - timedelta(hours=24)
    )

    for _, row in threads.iterrows():
        last_sender = str(row.get("last_sender", "")).strip().lower()
        if last_sender in OWN_EMAILS:
            continue

        last_date = row.get("last_date") or row.get("date")
        if pd.isna(last_date):
            continue

        try:
            last_ts = pd.Timestamp(last_date)
            last_ts = last_ts.tz_localize(None) if last_ts.tzinfo else last_ts
        except Exception:
            continue

        if last_ts > cutoff_24h:
            continue

        days_waiting = (pd.Timestamp(target_date) - last_ts).days
        subject = str(row.get("subject", "Email with no subject"))
        sender_name = str(row.get("last_sender_name", last_sender))

        urgency = "overdue" if days_waiting > 7 else "3-7gg" if days_waiting > 3 else "1-2gg"

        items.append(
            {
                "type": "email_reply",
                "title": f"Reply: {subject[:80]}",
                "person": sender_name,
                "person_email": last_sender,
                "deadline": "",
                "urgency": urgency,
                "context": {
                    "thread_id": str(row.get("thread_id", "")),
                    "days_waiting": days_waiting,
                },
                "what_unlocks": f"Thread closed with {sender_name}",
                "source": "email",
                "external_id": _make_external_id("email_reply", str(row.get("thread_id", ""))),
            }
        )
        if len(items) >= 20:
            break

    return items


def collect_slack_threads(target_date: date) -> list[dict]:
    ""
    path = DATA_ROOT / "slack" / "processed" / "interactions-slack.parquet"
    if not path.exists():
        log.debug("No interactions-slack.parquet")
        return []

    try:
        df = pd.read_parquet(path)
    except Exception:
        return []

    items = []
    cutoff_24h = pd.Timestamp(
        datetime.combine(target_date, datetime.min.time()) - timedelta(hours=24)
    )


    for _, row in df.iterrows():
        msg_date = row.get("date") or row.get("timestamp")
        if pd.isna(msg_date):
            continue

        try:
            ts = pd.Timestamp(msg_date)
            ts = ts.tz_localize(None) if ts.tzinfo else ts
        except Exception:
            continue

        if ts > cutoff_24h:
            continue

        sender = str(row.get("sender_name", row.get("sender", "")))
        sender_email = str(row.get("sender_email", ""))
        channel = str(row.get("channel", ""))
        text_preview = str(row.get("text", ""))[:80]

        items.append(
            {
                "type": "slack_thread",
                "title": f"Slack: {text_preview or channel}",
                "person": sender,
                "person_email": sender_email,
                "deadline": "",
                "urgency": "1-2gg",
                "context": {"channel": channel},
                "what_unlocks": f"Slack thread closed with {sender}",
                "source": "slack",
                "external_id": _make_external_id("slack_thread", channel, str(ts)),
            }
        )
        if len(items) >= 10:
            break

    return items


def collect_action_items(target_date: date) -> list[dict]:
    ""
    path = NLP_DIR / "action-items.parquet"
    if not path.exists():
        log.debug("No action-items.parquet")
        return []

    try:
        df = pd.read_parquet(path)
    except Exception:
        return []

    items = []
    import re

    speaker_re = re.compile(r"^speaker\s*\d+$", re.IGNORECASE)
    today = pd.Timestamp(target_date)

    for _, row in df.iterrows():
        deadline = row.get("deadline")
        if pd.isna(deadline):
            continue

        try:
            dl = pd.Timestamp(deadline)
            dl = dl.tz_localize(None) if dl.tzinfo else dl
        except Exception:
            continue

        days_delta = (dl - today).days
        if days_delta < -30 or days_delta > 14:
            continue


        assignee = str(row.get("assignee", "")).strip()
        if speaker_re.match(assignee):
            continue
        assignee_lower = assignee.lower()
        if (
            assignee_lower
            and not is_owner_speaker(assignee_lower)
            and assignee_lower not in ("", "nan", "none")
        ):
            continue

        text = str(row.get("action_text", row.get("text", "")))
        person = str(row.get("speaker", ""))

        if days_delta < 0:
            urgency = "overdue"
        elif days_delta == 0:
            urgency = "today"
        elif days_delta <= 2:
            urgency = "1-2gg"
        elif days_delta <= 7:
            urgency = "3-7gg"
        else:
            urgency = ">7gg"

        items.append(
            {
                "type": "action_item",
                "title": text[:100],
                "person": person,
                "person_email": str(row.get("speaker_email", "")),
                "deadline": str(dl.date()),
                "urgency": urgency,
                "context": {"meeting_id": str(row.get("meeting_id", "")), "days_delta": days_delta},
                "what_unlocks": "Action item completed",
                "source": "nlp",
                "external_id": _make_external_id(
                    "action_item", str(row.get("meeting_id", "")), text[:50]
                ),
            }
        )
        if len(items) >= 30:
            break

    return items


def collect_decay_reconnect(target_date: date) -> list[dict]:
    ""
    decay_path = DECAY_DIR / "decay-state.json"
    if not decay_path.exists():
        log.debug("No decay-state.json")
        return []

    try:
        data = json.loads(decay_path.read_text())
    except (json.JSONDecodeError, KeyError):
        return []


    alerts_dir = DATA_ROOT / "alerts"
    alert_emails: set[str] = set()
    if alerts_dir.exists():
        for f in alerts_dir.glob("alerts-*.json"):
            try:
                for alert in json.loads(f.read_text()):
                    if isinstance(alert, dict):
                        alert_emails.add(str(alert.get("email", "")).lower())
            except Exception:
                pass

    from sbk_config import INTERNAL_DOMAINS

    items = []
    for pid, info in data.items():
        if not isinstance(info, dict):
            continue

        tier = info.get("tier", "unknown")
        if tier in ("internal", "family", "unknown", "connection", "acquaintance"):
            continue

        decay_pct = info.get("decay_pct", 0)
        if isinstance(decay_pct, int | float) and decay_pct < 50:
            continue

        email = str(info.get("email", "")).strip().lower()
        name = str(info.get("name", pid))


        if email and "@" in email:
            domain = email.split("@")[-1]
            if domain in INTERNAL_DOMAINS:
                continue


        if is_own_name(name) or is_owner_speaker(name):
            continue

        days = info.get("days_since", info.get("days_since_contact", 0))

        items.append(
            {
                "type": "decay_reconnect",
                "title": f"Reconnect with {name}",
                "person": name,
                "person_email": email,
                "deadline": "",
                "urgency": "3-7gg",
                "context": {"decay_pct": decay_pct, "days_since": days, "tier": tier},
                "what_unlocks": f"Relationship with {name} refreshed",
                "source": "decay",
                "external_id": _make_external_id("decay_reconnect", email or pid),
            }
        )
        if len(items) >= 10:
            break

    return items


def collect_entity_review(target_date: date) -> list[dict]:
    ""
    db_path = L3_DIR / "queue" / "approval-queue.db"
    if not db_path.exists():
        log.debug("No approval-queue.db")
        return []

    import sqlite3

    items = []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM queue_items WHERE status = 'pending' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        for row in rows:
            items.append(
                {
                    "type": "entity_review",
                    "title": f"Review: {row['title'][:80]}",
                    "person": str(row["person_name"] or ""),
                    "person_email": str(row["person_email"] or ""),
                    "deadline": "",
                    "urgency": "3-7gg",
                    "context": {"queue_item_id": row["id"], "item_type": row["item_type"]},
                    "what_unlocks": "Entity review decided",
                    "source": "queue",
                    "external_id": _make_external_id("entity_review", str(row["id"])),
                }
            )
        conn.close()
    except Exception as e:
        log.warning("Error reading approval queue: %s", e)

    return items


def collect_notion_milestones(target_date: date) -> list[dict]:
    ""
    path = DATA_ROOT / "notion" / "processed" / "tasks-timeline.parquet"
    if not path.exists():
        log.debug("No tasks-timeline.parquet")
        return []

    try:
        df = pd.read_parquet(path)
    except Exception:
        return []

    items = []
    today = pd.Timestamp(target_date)

    for _, row in df.iterrows():
        status = str(row.get("status", "")).lower()
        if status in ("done", "completed", "cancelled"):
            continue

        due = row.get("due_date")
        if pd.isna(due):
            continue

        try:
            dl = pd.Timestamp(due)
            dl = dl.tz_localize(None) if dl.tzinfo else dl
        except Exception:
            continue

        days_delta = (dl - today).days
        if days_delta < -14 or days_delta > 14:
            continue

        title = str(row.get("title", row.get("name", "Notion task")))
        assignee = str(row.get("assignee", ""))

        if days_delta < 0:
            urgency = "overdue"
        elif days_delta == 0:
            urgency = "today"
        elif days_delta <= 2:
            urgency = "1-2gg"
        elif days_delta <= 7:
            urgency = "3-7gg"
        else:
            urgency = ">7gg"

        items.append(
            {
                "type": "notion_milestone",
                "title": title[:100],
                "person": assignee,
                "person_email": "",
                "deadline": str(dl.date()),
                "urgency": urgency,
                "context": {"status": status, "days_delta": days_delta},
                "what_unlocks": f"Milestone completed: {title[:50]}",
                "source": "notion",
                "external_id": _make_external_id("notion_milestone", title[:50], str(dl.date())),
            }
        )
        if len(items) >= 10:
            break

    return items




TIER_SCORES = {
    "inner": 30,
    "sympathy": 25,
    "affinity": 20,
    "active": 15,
    "connection": 10,
    "acquaintance": 5,
    "unknown": 0,
}

TYPE_SCORES = {
    "calendar_prep": 10,
    "email_reply": 8,
    "action_item": 7,
    "slack_thread": 6,
    "decay_reconnect": 5,
    "notion_milestone": 4,
    "entity_review": 3,
}


def compute_urgency_score(urgency: str) -> int:
    ""
    return {
        "overdue": 20,
        "today": 18,
        "1-2gg": 15,
        "3-7gg": 10,
        ">7gg": 5,
    }.get(urgency, 5)


def compute_deadline_score(deadline: str, target_date: date) -> int:
    ""
    if not deadline:
        return 0
    try:
        dl = date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return 0

    days = (dl - target_date).days
    if days <= 0:
        return 20
    if days <= 1:
        return 18
    if days <= 3:
        return 15
    if days <= 7:
        return 10
    return 5


def compute_multi_source_score(task: dict, all_tasks: list[dict]) -> int:
    ""
    email = task.get("person_email", "").strip().lower()
    if not email:
        return 8

    count = sum(1 for t in all_tasks if t.get("person_email", "").strip().lower() == email)
    if count >= 3:
        return 15
    if count >= 2:
        return 12
    return 8


def score_task(
    task: dict, all_tasks: list[dict], tier_map: dict[str, str], target_date: date
) -> int:
    ""

    email = task.get("person_email", "").strip().lower()
    tier = tier_map.get(email, task.get("person_tier", "unknown"))
    task["person_tier"] = tier
    tier_score = TIER_SCORES.get(tier, 0)


    urgency_score = compute_urgency_score(task.get("urgency", ""))


    deadline_score = compute_deadline_score(task.get("deadline", ""), target_date)


    multi_score = compute_multi_source_score(task, all_tasks)


    type_score = TYPE_SCORES.get(task.get("type", ""), 3)


    deferral_score = task.get("_deferral_bonus", 0)

    total = tier_score + urgency_score + deadline_score + multi_score + type_score + deferral_score
    return min(total, 100)





def classify_eisenhower(score: int, deadline: str, target_date: date) -> str:
    ""
    has_close_deadline = False
    if deadline:
        try:
            dl = date.fromisoformat(deadline)
            has_close_deadline = (dl - target_date).days <= 3
        except (ValueError, TypeError):
            pass

    if score >= 70 and has_close_deadline:
        return "Q1"
    if score >= 50 and not has_close_deadline:
        return "Q2"
    if score < 50 and has_close_deadline:
        return "Q3"


    if score >= 50 and has_close_deadline:
        return "Q1"
    return "Q4"




BUDGET = {"Q1": 3, "Q2": 5, "Q3": 5, "Q4": 2}
TOTAL_BUDGET = 15


def apply_budget(tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    ""
    by_q: dict[str, list[dict]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for t in tasks:
        by_q.setdefault(t["quadrant"], []).append(t)


    for q in by_q:
        by_q[q].sort(key=lambda t: t["priority_score"], reverse=True)

    budgeted = []
    overflow = []
    for q, limit in BUDGET.items():
        items = by_q.get(q, [])
        budgeted.extend(items[:limit])
        overflow.extend(items[limit:])


    if len(budgeted) > TOTAL_BUDGET:

        budgeted.sort(key=lambda t: t["priority_score"], reverse=True)
        overflow.extend(budgeted[TOTAL_BUDGET:])
        budgeted = budgeted[:TOTAL_BUDGET]

    return budgeted, overflow





def dedup_tasks(tasks: list[dict]) -> list[dict]:
    ""
    seen: set[str] = set()
    result = []
    for t in tasks:
        eid = t.get("external_id", "")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
        result.append(t)
    return result





def collect_all_tasks(target_date: date, verbose: bool = False) -> list[dict]:
    ""
    collectors = [
        ("calendar_prep", collect_calendar_prep),
        ("email_replies", collect_email_replies),
        ("slack_threads", collect_slack_threads),
        ("action_items", collect_action_items),
        ("decay_reconnect", collect_decay_reconnect),
        ("entity_review", collect_entity_review),
        ("notion_milestones", collect_notion_milestones),
    ]

    all_tasks = []
    for name, fn in collectors:
        try:
            items = fn(target_date)
            if verbose:
                log.info("Collector %s: %d items", name, len(items))
            all_tasks.extend(items)
        except Exception as e:
            log.warning("Collector %s failed: %s", name, e)

    return all_tasks


def build_daily_tasks(target_date: date, verbose: bool = False) -> dict:
    ""

    raw = collect_all_tasks(target_date, verbose=verbose)
    if verbose:
        log.info("Total raw tasks: %d", len(raw))


    tasks = dedup_tasks(raw)
    if verbose:
        log.info("After dedup: %d", len(tasks))


    tier_map = _load_tier_map()
    if verbose:
        log.info("Tier map: %d entries", len(tier_map))


    for t in tasks:
        t["priority_score"] = score_task(t, tasks, tier_map, target_date)


    for t in tasks:
        t["quadrant"] = classify_eisenhower(t["priority_score"], t.get("deadline", ""), target_date)


    tasks.sort(key=lambda t: t["priority_score"], reverse=True)


    budgeted, overflow = apply_budget(tasks)

    return {
        "date": str(target_date),
        "generated_at": datetime.now().isoformat(),
        "total_collected": len(raw),
        "total_deduped": len(tasks),
        "budgeted_count": len(budgeted),
        "overflow_count": len(overflow),
        "tasks": budgeted,
        "overflow": overflow,
        "stats": {
            "by_quadrant": {
                q: len([t for t in budgeted if t["quadrant"] == q])
                for q in ("Q1", "Q2", "Q3", "Q4")
            },
            "by_type": {},
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="SBK daily task board — collect & score daily tasks"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Collect and score but don't write file"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--date", type=str, default=None, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    log.info("Building daily tasks for %s", target_date)

    result = build_daily_tasks(target_date, verbose=args.verbose)


    by_type: dict[str, int] = {}
    for t in result["tasks"] + result["overflow"]:
        by_type[t["type"]] = by_type.get(t["type"], 0) + 1
    result["stats"]["by_type"] = by_type

    log.info(
        "Result: %d budgeted, %d overflow (Q1=%d Q2=%d Q3=%d Q4=%d)",
        result["budgeted_count"],
        result["overflow_count"],
        result["stats"]["by_quadrant"]["Q1"],
        result["stats"]["by_quadrant"]["Q2"],
        result["stats"]["by_quadrant"]["Q3"],
        result["stats"]["by_quadrant"]["Q4"],
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if not args.dry_run:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = TASKS_DIR / f"daily-tasks-{target_date}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        log.info("Written to %s", out_path)
    else:
        log.info("Dry run — no file written")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-tasks", source="l3-tasks", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
