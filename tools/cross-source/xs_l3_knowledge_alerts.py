""











from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import ENRICHED_DIR, SLACK_CONVERSATIONS_DIR

log = logging.getLogger("sbk-knowledge-alerts")




CRITICAL_ATTRIBUTES = {
    "employment.status",
    "deal.last_activity",
    "deal.contract_end_date",
    "commitment.deadline",
}


def should_alert(
    entity_id: str,
    entity_name: str,
    change: dict,
    days: int = 3,
) -> bool:
    ""




    attribute = change.get("attribute", "")


    if attribute == "employment.status":
        old = str(change.get("old_value", "")).lower()
        new = str(change.get("value", "")).lower()
        if old == "active" and new == "terminated":
            return not _owner_has_recent_interaction(entity_name, days)


    if attribute == "deal.last_activity":
        val = change.get("value", "")
        if _is_date_older_than(val, days=14):
            return not _owner_has_recent_interaction(entity_name, days)


    if attribute == "deal.contract_end_date":
        val = change.get("value", "")
        if _is_date_within(val, days=30):
            return not _owner_has_recent_interaction(entity_name, days)


    if attribute == "commitment.deadline":
        val = change.get("value", "")
        if _is_date_older_than(val, days=3):
            return not _owner_has_recent_interaction(entity_name, days)

    return False


def filter_changes_for_digest(changes: list[dict]) -> list[dict]:
    ""
    if not changes:
        return []
    result = []
    for ch in changes:
        eid = ch.get("entity_id", "")
        ename = ch.get("entity", ch.get("entity_name", ""))
        if should_alert(eid, ename, ch):
            result.append(ch)
    return result





def _owner_has_recent_interaction(name: str, days: int = 3) -> bool:
    ""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return (
        _check_email_interaction(name, cutoff)
        or _check_calendar_interaction(name, cutoff)
        or _check_slack_interaction(name, cutoff)
    )


def _check_email_interaction(name: str, cutoff: datetime) -> bool:
    ""
    path = ENRICHED_DIR / "email-enriched.parquet"
    if not path.exists():
        return False
    try:
        df = pd.read_parquet(path, columns=["sender_name", "date"])
        name_lower = name.lower()
        mask = df["sender_name"].str.lower().str.contains(name_lower, na=False)
        if not mask.any():
            return False
        recent = df.loc[mask, "date"].max()
        if pd.isna(recent):
            return False
        return pd.Timestamp(recent).to_pydatetime().replace(tzinfo=None) >= cutoff
    except Exception:
        return False


def _check_calendar_interaction(name: str, cutoff: datetime) -> bool:
    ""
    path = ENRICHED_DIR / "calendar-enriched.parquet"
    if not path.exists():
        return False
    try:
        df = pd.read_parquet(path, columns=["attendees", "start_datetime"])
        name_lower = name.lower()
        mask = df["attendees"].astype(str).str.lower().str.contains(name_lower, na=False)
        if not mask.any():
            return False
        recent = df.loc[mask, "start_datetime"].max()
        if pd.isna(recent):
            return False
        return pd.Timestamp(recent).to_pydatetime().replace(tzinfo=None) >= cutoff
    except Exception:
        return False


def _check_slack_interaction(name: str, cutoff: datetime) -> bool:
    ""
    if not SLACK_CONVERSATIONS_DIR.exists():
        return False
    name_lower = name.lower()

    from slack_esclusi import e_escluso, esclusi

    # Slack never downloaded: nothing to read, so the channel index is not needed.
    fuori = esclusi() if SLACK_CONVERSATIONS_DIR.exists() else frozenset()
    try:
        for jf in SLACK_CONVERSATIONS_DIR.glob("*.json"):
            try:
                data = json.loads(jf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if e_escluso(data, fuori):
                continue
            messages = data if isinstance(data, list) else data.get("messages", [])
            for msg in messages[-50:]:
                ts = msg.get("ts", "")
                text = str(msg.get("text", "")).lower()
                if name_lower in text:
                    try:
                        msg_dt = datetime.fromtimestamp(float(ts))
                        if msg_dt >= cutoff:
                            return True
                    except (ValueError, TypeError, OSError):
                        continue
    except Exception:
        pass
    return False





def _is_date_older_than(value: str, days: int) -> bool:
    ""
    try:
        dt = _parse_date(value)
        return dt < datetime.now(UTC) - timedelta(days=days)
    except Exception:
        return False


def _is_date_within(value: str, days: int) -> bool:
    ""
    try:
        dt = _parse_date(value)
        now = datetime.now(UTC)
        return now <= dt <= now + timedelta(days=days)
    except Exception:
        return False


def _parse_date(value: str) -> datetime:
    ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(str(value).strip()[:26], fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value}")
