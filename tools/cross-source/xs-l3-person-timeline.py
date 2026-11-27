#!/usr/bin/env python3
"""Person timeline: every interaction with each of your top people across email, calendar, WhatsApp, Slack,
meetings, CRM notes and calls, Plaud and knowledge facts, in date order, one file per person in
cross-source/person-timeline/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    ATTIO_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    CALENDARS_DIR,
    DATA_ROOT,
    EMAILS_DIR,
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    OWN_EMAILS,
    RQ_DIR,
    TACTIQ_DIR,
    WHATSAPP_CHATS_DIR,
    attio_transcript_files,
    is_own_name,
    is_owner_speaker,
    safe_write_json,
    utc_now,
)

log = logging.getLogger("xs.person-timeline")



TIMELINE_OUTPUT_DIR = DATA_ROOT / "cross-source" / "person-timeline"




def _truncate(text: str | None, max_len: int = 100) -> str:
    ""
    if not text:
        return ""
    text = str(text).strip().replace("\n", " ").replace("\r", "")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _parse_ts(val) -> str | None:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.isoformat()
    if isinstance(val, datetime):
        return val.isoformat()
    s = str(val).strip()
    if not s or s.lower() in ("nat", "none", "null", ""):
        return None

    try:
        return pd.Timestamp(s).isoformat()
    except Exception:
        return None


def _ts_sort_key(event: dict) -> str:
    ""
    ts = event.get("timestamp", "")
    return ts if ts else "9999-12-31T23:59:59"


def _classify_email_direction(from_addr: str) -> str:
    ""
    if not from_addr:
        return "bidirectional"
    from_lower = from_addr.lower()
    for own in OWN_EMAILS:
        if own in from_lower:
            return "outbound"
    return "inbound"


def _map_interaction_type(itype: str) -> str:
    ""
    itype_lower = itype.lower() if itype else ""
    if "wa_" in itype_lower or "whatsapp" in itype_lower:
        return "message"
    if "meeting" in itype_lower or "call" in itype_lower:
        return "meeting"
    if "dm" in itype_lower or "direct" in itype_lower:
        return "message"
    if "thread" in itype_lower or "mention" in itype_lower or "channel" in itype_lower:
        return "message"
    if (
        "cc_" in itype_lower
        or "bcc" in itype_lower
        or "reply" in itype_lower
        or "mass" in itype_lower
    ):
        return "message"
    if "note" in itype_lower:
        return "note"
    if "recording" in itype_lower:
        return "call"
    return "message"


def _map_interaction_direction(itype: str, from_addr: str) -> str:
    ""
    itype_lower = itype.lower() if itype else ""

    if "meeting" in itype_lower or "call" in itype_lower:
        return "bidirectional"

    if "wa_" in itype_lower:
        if from_addr and (is_owner_speaker(from_addr) or any(e in from_addr.lower() for e in OWN_EMAILS)):
            return "outbound"
        return "inbound"

    return _classify_email_direction(from_addr)





def load_top_people(top_n: int, person_filter: str | None = None) -> list[dict]:
    ""




    top_file = RQ_DIR / "top-150-people.json"
    if top_file.exists():
        data = json.loads(top_file.read_text(encoding="utf-8"))
        log.info("Loaded %d people from %s", len(data), top_file)
    else:

        for fname in (
            "composite-scores-v3.parquet",
            "composite-scores-v2.parquet",
            "composite-scores.parquet",
        ):
            fpath = RQ_DIR / fname
            if fpath.exists():
                df = pd.read_parquet(fpath)
                df = df.sort_values(
                    "score_v3" if "score_v3" in df.columns else "score", ascending=False
                )
                data = []
                for i, (_, row) in enumerate(df.head(top_n).iterrows()):
                    data.append(
                        {
                            "rank": i + 1,
                            "name": str(row.get("person", row.get("name", ""))),
                            "score": float(row.get("score_v3", row.get("score", 0))),
                            "type": str(row.get("relationship_type", "")),
                            "person_id": str(row.get("person_id", "")),
                        }
                    )
                log.info("Loaded %d people from %s", len(data), fpath)
                break
        else:
            log.error("No RQ score file found in %s", RQ_DIR)
            return []


    if person_filter:
        pf = person_filter.lower()
        data = [p for p in data if pf in p.get("name", "").lower()]
        log.info("Filtered to %d people matching '%s'", len(data), person_filter)
        return data

    return data[:top_n]





def _load_entity_bridge() -> dict[str, str]:
    ""
    bridge_path = RQ_DIR / "entity-bridge.json"
    if bridge_path.exists():
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        log.info("Loaded entity bridge: %d mappings", len(bridge))
        return bridge
    log.warning("Entity bridge not found at %s, building...", bridge_path)
    try:
        from rq_entity_bridge import build_entity_bridge, save_bridge

        bridge = build_entity_bridge()
        save_bridge(bridge)
        return bridge
    except Exception as exc:
        log.error("Failed to build entity bridge: %s", exc)
        return {}


def _build_target_lookup(bridge: dict[str, str], target_pids: set[str]) -> dict[str, str]:
    ""





    lookup: dict[str, str] = {}
    for key, pid in bridge.items():
        if key.startswith("__"):
            continue
        if pid in target_pids:
            lookup[key] = pid

            key_lower = key.lower().strip()
            if key_lower not in lookup:
                lookup[key_lower] = pid
    log.info("Built target lookup: %d entries for %d target pids", len(lookup), len(target_pids))
    return lookup


def _resolve_pid(lookup: dict[str, str], identifier: str) -> str | None:
    ""



    if not identifier:
        return None
    if identifier in lookup:
        return lookup[identifier]
    lower = identifier.lower().strip()
    if lower in lookup:
        return lookup[lower]
    return None







def _load_email_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    account_dirs = sorted(EMAILS_DIR.glob("*/messages.parquet"))
    if not account_dirs:
        log.info("No email data found")
        return events


    email_to_pid: dict[str, str] = {}
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if cm_path.exists():
        cm = pd.read_parquet(cm_path, columns=["person_id", "email", "all_emails"])
        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in target_pids:
                continue
            email = str(row.get("email", "")) if pd.notna(row.get("email")) else ""
            if email:
                email_to_pid[email.lower()] = pid
            all_emails_raw = row.get("all_emails")
            if pd.notna(all_emails_raw):
                try:
                    elist = (
                        json.loads(all_emails_raw)
                        if isinstance(all_emails_raw, str)
                        else all_emails_raw
                    )
                    for e in elist if isinstance(elist, list) else []:
                        email_to_pid[str(e).lower()] = pid
                except (json.JSONDecodeError, TypeError):
                    pass

    total = 0
    for msg_file in account_dirs:
        account = msg_file.parent.name
        if account.startswith("."):
            continue
        try:
            df = pd.read_parquet(
                msg_file,
                columns=["id", "date", "from_addr", "to_addr", "cc", "subject", "snippet"],
            )
        except Exception as exc:
            log.warning("Failed to read %s: %s", msg_file, exc)
            continue

        for _, row in df.iterrows():
            from_addr = str(row.get("from_addr", "")) if pd.notna(row.get("from_addr")) else ""
            to_addr = str(row.get("to_addr", "")) if pd.notna(row.get("to_addr")) else ""
            cc = str(row.get("cc", "")) if pd.notna(row.get("cc")) else ""
            subject = str(row.get("subject", "")) if pd.notna(row.get("subject")) else ""
            snippet = str(row.get("snippet", "")) if pd.notna(row.get("snippet")) else ""
            ts = _parse_ts(row.get("date"))
            if not ts:
                continue


            all_addrs = f"{from_addr} {to_addr} {cc}".lower()
            matched_pids = set()
            for email_key, pid in email_to_pid.items():
                if email_key in all_addrs:
                    matched_pids.add(pid)

            direction = _classify_email_direction(from_addr)

            for pid in matched_pids:
                event = {
                    "timestamp": ts,
                    "source": "email",
                    "source_account": account,
                    "type": "message",
                    "direction": direction,
                    "summary": _truncate(subject or snippet),
                    "metadata": {
                        "message_id": str(row.get("id", "")),
                        "subject": _truncate(subject, 200),
                    },
                }
                events.setdefault(pid, []).append(event)
                total += 1

    log.info("Email: loaded %d events for %d people", total, len(events))
    return events


def _load_calendar_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}


    email_to_pid: dict[str, str] = {}
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if cm_path.exists():
        cm = pd.read_parquet(cm_path, columns=["person_id", "email", "all_emails"])
        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in target_pids:
                continue
            email = str(row.get("email", "")) if pd.notna(row.get("email")) else ""
            if email:
                email_to_pid[email.lower()] = pid
            all_emails_raw = row.get("all_emails")
            if pd.notna(all_emails_raw):
                try:
                    elist = (
                        json.loads(all_emails_raw)
                        if isinstance(all_emails_raw, str)
                        else all_emails_raw
                    )
                    for e in elist if isinstance(elist, list) else []:
                        email_to_pid[str(e).lower()] = pid
                except (json.JSONDecodeError, TypeError):
                    pass

    total = 0
    seen_event_ids: set[str] = set()
    cal_dirs = sorted(CALENDARS_DIR.iterdir()) if CALENDARS_DIR.exists() else []

    for cal_dir in cal_dirs:
        events_file = cal_dir / "events.parquet"
        if not events_file.exists():
            continue
        account = cal_dir.name
        try:
            df = pd.read_parquet(events_file)
        except Exception as exc:
            log.warning("Failed to read %s: %s", events_file, exc)
            continue

        for _, row in df.iterrows():
            event_id = str(row.get("id", ""))

            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

            summary = str(row.get("summary", "")) if pd.notna(row.get("summary")) else ""
            ts = _parse_ts(row.get("start_datetime"))
            if not ts:
                continue


            attendees_raw = row.get("attendees")
            if pd.isna(attendees_raw) if isinstance(attendees_raw, float) else not attendees_raw:
                continue
            try:
                attendees = (
                    json.loads(attendees_raw) if isinstance(attendees_raw, str) else attendees_raw
                )
            except (json.JSONDecodeError, TypeError):
                continue

            if not isinstance(attendees, list):
                continue


            matched_pids = set()
            for att in attendees:
                att_email = att.get("email", "").lower() if isinstance(att, dict) else ""
                if att_email in email_to_pid:
                    matched_pids.add(email_to_pid[att_email])

            for pid in matched_pids:
                event = {
                    "timestamp": ts,
                    "source": "calendar",
                    "source_account": account,
                    "type": "meeting",
                    "direction": "bidirectional",
                    "summary": _truncate(summary),
                    "metadata": {
                        "event_id": event_id,
                        "attendee_count": len(attendees),
                    },
                }
                events.setdefault(pid, []).append(event)
                total += 1

    log.info("Calendar: loaded %d events for %d people", total, len(events))
    return events


def _load_whatsapp_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""




    events: dict[str, list[dict]] = {}
    if not WHATSAPP_CHATS_DIR.exists():
        log.info("WhatsApp chats directory not found")
        return events


    name_to_pids: dict[str, str] = {}
    for k, v in bridge.items():
        if (
            k.startswith("__")
            or "@" in k
            or k.startswith("p_")
            or k.startswith("person_")
            or k.startswith("pu_")
        ):
            continue
        if v in target_pids:
            name_to_pids[k] = v

    total = 0
    chat_files = sorted(WHATSAPP_CHATS_DIR.glob("*.json"))
    log.info("WhatsApp: scanning %d chat files", len(chat_files))

    for chat_file in chat_files:
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        participants = data.get("participants", [])
        chat_name = data.get("chat_name", "")
        messages = data.get("messages", [])
        if not messages:
            continue


        chat_pids: dict[str, str] = {}
        for p in participants:
            p_lower = p.lower().strip() if isinstance(p, str) else ""
            if p_lower in name_to_pids:
                chat_pids[p] = name_to_pids[p_lower]
            else:

                resolved = _resolve_pid(bridge, p)
                if resolved and resolved in target_pids:
                    chat_pids[p] = resolved

        if not chat_pids:
            continue


        step = max(1, len(messages) // 500)
        sampled = messages[::step] if step > 1 else messages

        for msg in sampled:
            ts = _parse_ts(msg.get("timestamp"))
            if not ts:
                continue
            sender = msg.get("sender", "")
            text = msg.get("text", "")




            sender_lower = sender.lower().strip() if sender else ""
            is_owner = is_own_name(sender_lower)

            if is_owner:

                for p_name, pid in chat_pids.items():
                    event = {
                        "timestamp": ts,
                        "source": "whatsapp",
                        "type": "message",
                        "direction": "outbound",
                        "summary": _truncate(text),
                        "metadata": {
                            "chat_name": _truncate(chat_name, 80),
                        },
                    }
                    events.setdefault(pid, []).append(event)
                    total += 1
            elif sender in chat_pids:
                pid = chat_pids[sender]
                event = {
                    "timestamp": ts,
                    "source": "whatsapp",
                    "type": "message",
                    "direction": "inbound",
                    "summary": _truncate(text),
                    "metadata": {
                        "chat_name": _truncate(chat_name, 80),
                    },
                }
                events.setdefault(pid, []).append(event)
                total += 1
            else:

                for p_name, pid in chat_pids.items():
                    event = {
                        "timestamp": ts,
                        "source": "whatsapp",
                        "type": "message",
                        "direction": "bidirectional",
                        "summary": _truncate(text),
                        "metadata": {
                            "chat_name": _truncate(chat_name, 80),
                            "sender": _truncate(sender, 60),
                        },
                    }
                    events.setdefault(pid, []).append(event)
                    total += 1

    log.info("WhatsApp: loaded %d events for %d people", total, len(events))
    return events


def _load_slack_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    dm_dir = DATA_ROOT / "slack" / "dm"
    if not dm_dir.exists():
        log.info("Slack DM directory not found")
        return events


    users_file = DATA_ROOT / "slack" / "slack-users.json"
    user_map: dict[str, dict] = {}
    if users_file.exists():
        try:
            user_map = json.loads(users_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass


    uid_to_pid: dict[str, str] = {}
    for uid, info in user_map.items():

        email = info.get("email", "").lower()
        if email:
            resolved = _resolve_pid(bridge, email)
            if resolved and resolved in target_pids:
                uid_to_pid[uid] = resolved
                continue

        real_name = info.get("real_name", "")
        if real_name:
            resolved = _resolve_pid(bridge, real_name)
            if resolved and resolved in target_pids:
                uid_to_pid[uid] = resolved

    total = 0
    for dm_file in sorted(dm_dir.glob("*.json")):
        try:
            data = json.loads(dm_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        user_id = data.get("user_id", dm_file.stem)
        user_name = data.get("user_name", "")
        messages = data.get("messages", [])

        pid = uid_to_pid.get(user_id)
        if not pid:

            pid = uid_to_pid.get(dm_file.stem)
        if not pid:
            continue

        for msg in messages:
            ts_raw = msg.get("ts", "")
            if not ts_raw:
                continue

            try:
                ts_float = float(ts_raw)
                ts = datetime.fromtimestamp(ts_float, tz=UTC).isoformat()
            except (ValueError, OSError):
                continue

            text = msg.get("text", "")
            msg_user = msg.get("user", "")


            if msg_user == user_id:
                direction = "inbound"
            else:
                direction = "outbound"

            event = {
                "timestamp": ts,
                "source": "slack",
                "type": "message",
                "direction": direction,
                "summary": _truncate(text),
                "metadata": {
                    "user_name": user_name,
                    "channel_type": "dm",
                },
            }
            events.setdefault(pid, []).append(event)
            total += 1

    log.info("Slack DM: loaded %d events for %d people", total, len(events))
    return events


def _load_tactiq_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}


    meetings_file = TACTIQ_DIR / "meetings.parquet"
    if not meetings_file.exists():
        log.info("Tactiq meetings parquet not found")
        return events

    try:
        df = pd.read_parquet(meetings_file)
    except Exception as exc:
        log.warning("Failed to read %s: %s", meetings_file, exc)
        return events

    total = 0
    for _, row in df.iterrows():
        title = str(row.get("title", "")) if pd.notna(row.get("title")) else ""
        ts = _parse_ts(row.get("created_date"))
        if not ts:

            created_ms = row.get("created_ms")
            if pd.notna(created_ms) and created_ms:
                try:
                    ts = datetime.fromtimestamp(int(created_ms) / 1000, tz=UTC).isoformat()
                except (ValueError, OSError):
                    continue
        if not ts:
            continue

        participants_raw = (
            str(row.get("participants", "")) if pd.notna(row.get("participants")) else ""
        )
        participant_names = [p.strip() for p in participants_raw.split(",") if p.strip()]


        matched_pids = set()
        for p in participant_names:
            p_lower = p.lower().strip()

            if is_own_name(p_lower):
                continue
            resolved = _resolve_pid(bridge, p)
            if resolved and resolved in target_pids:
                matched_pids.add(resolved)

        for pid in matched_pids:
            event = {
                "timestamp": ts,
                "source": "tactiq",
                "type": "meeting",
                "direction": "bidirectional",
                "summary": _truncate(title),
                "metadata": {
                    "meeting_id": str(row.get("meeting_id", "")),
                    "platform": str(row.get("platform", ""))
                    if pd.notna(row.get("platform"))
                    else "",
                    "duration_min": float(row.get("duration_min", 0))
                    if pd.notna(row.get("duration_min"))
                    else 0,
                    "participant_count": int(row.get("participant_count", 0))
                    if pd.notna(row.get("participant_count"))
                    else 0,
                },
            }
            events.setdefault(pid, []).append(event)
            total += 1

    log.info("Tactiq: loaded %d events for %d people", total, len(events))
    return events


def _load_attio_notes(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    notes_file = ATTIO_DIR / "notes.parquet"
    if not notes_file.exists():
        log.info("Attio notes parquet not found")
        return events


    record_to_pid: dict[str, str] = {}
    people_file = ATTIO_DIR / "people.parquet"
    if people_file.exists():
        try:
            people = pd.read_parquet(people_file, columns=["record_id", "name", "email_addresses"])
            for _, row in people.iterrows():
                record_id = str(row.get("record_id", ""))
                name = str(row.get("name", "")) if pd.notna(row.get("name")) else ""
                if name:
                    resolved = _resolve_pid(bridge, name)
                    if resolved and resolved in target_pids:
                        record_to_pid[record_id] = resolved
                        continue

                emails_raw = row.get("email_addresses")
                if pd.notna(emails_raw):
                    emails_str = str(emails_raw)

                    try:
                        elist = (
                            json.loads(emails_str)
                            if emails_str.startswith("[")
                            else emails_str.split("|||")
                        )
                    except (json.JSONDecodeError, TypeError):
                        elist = [emails_str]
                    for e in elist:
                        e_clean = str(e).strip().strip('"').lower()
                        if e_clean:
                            resolved = _resolve_pid(bridge, e_clean)
                            if resolved and resolved in target_pids:
                                record_to_pid[record_id] = resolved
                                break
        except Exception as exc:
            log.warning("Failed to load Attio people: %s", exc)

    try:
        df = pd.read_parquet(notes_file)
    except Exception as exc:
        log.warning("Failed to read Attio notes: %s", exc)
        return events

    total = 0
    for _, row in df.iterrows():
        parent_obj = str(row.get("parent_object", ""))
        if parent_obj != "people":
            continue

        record_id = str(row.get("parent_record_id", ""))
        pid = record_to_pid.get(record_id)
        if not pid:
            continue

        ts = _parse_ts(row.get("created_at"))
        if not ts:
            continue

        title = str(row.get("title", "")) if pd.notna(row.get("title")) else ""
        content = (
            str(row.get("content_plaintext", "")) if pd.notna(row.get("content_plaintext")) else ""
        )

        event = {
            "timestamp": ts,
            "source": "attio",
            "type": "note",
            "direction": "outbound",
            "summary": _truncate(title or content),
            "metadata": {
                "note_id": str(row.get("note_id", "")),
            },
        }
        events.setdefault(pid, []).append(event)
        total += 1

    log.info("Attio notes: loaded %d events for %d people", total, len(events))
    return events


def _load_attio_meetings(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    meetings_file = ATTIO_DIR / "meetings.parquet"
    if not meetings_file.exists():
        log.info("Attio meetings parquet not found")
        return events


    email_to_pid: dict[str, str] = {}
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if cm_path.exists():
        cm = pd.read_parquet(cm_path, columns=["person_id", "email", "all_emails"])
        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            if pid not in target_pids:
                continue
            email = str(row.get("email", "")) if pd.notna(row.get("email")) else ""
            if email:
                email_to_pid[email.lower()] = pid
            all_emails_raw = row.get("all_emails")
            if pd.notna(all_emails_raw):
                try:
                    elist = (
                        json.loads(all_emails_raw)
                        if isinstance(all_emails_raw, str)
                        else all_emails_raw
                    )
                    for e in elist if isinstance(elist, list) else []:
                        email_to_pid[str(e).lower()] = pid
                except (json.JSONDecodeError, TypeError):
                    pass

    try:
        df = pd.read_parquet(meetings_file)
    except Exception as exc:
        log.warning("Failed to read Attio meetings: %s", exc)
        return events

    total = 0
    for _, row in df.iterrows():
        ts = _parse_ts(row.get("start_dt"))
        if not ts:
            continue

        title = str(row.get("title", "")) if pd.notna(row.get("title")) else ""
        participants_raw = (
            str(row.get("participants", "")) if pd.notna(row.get("participants")) else ""
        )


        participant_emails = [p.strip().lower() for p in participants_raw.split("|||") if p.strip()]
        matched_pids = set()
        for email in participant_emails:
            if email in email_to_pid:
                matched_pids.add(email_to_pid[email])

        for pid in matched_pids:
            event = {
                "timestamp": ts,
                "source": "attio",
                "type": "meeting",
                "direction": "bidirectional",
                "summary": _truncate(title),
                "metadata": {
                    "meeting_id": str(row.get("meeting_id", "")),
                    "participant_count": int(row.get("participant_count", 0))
                    if pd.notna(row.get("participant_count"))
                    else 0,
                },
            }
            events.setdefault(pid, []).append(event)
            total += 1

    log.info("Attio meetings: loaded %d events for %d people", total, len(events))
    return events


def _load_attio_transcripts(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}

    files = attio_transcript_files(ATTIO_TRANSCRIPTS_DIR)
    if not files:
        log.info("Attio transcripts not found")
        return events

    total = 0
    for tf in files:
        try:
            data = json.loads(tf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        ts = _parse_ts(data.get("meeting_date"))
        if not ts:
            continue

        title = data.get("meeting_title", "")
        meeting_id = data.get("meeting_id", tf.stem)







    log.info("Attio transcripts: skipped (covered by Attio meetings loader)")
    return events


def _load_plaud_events(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    proc_dir = DATA_ROOT / "plaud" / "processed"
    results_file = proc_dir / "_full_results_v2.json"
    if not results_file.exists():
        log.info("Plaud processed results not found")
        return events

    try:
        data = json.loads(results_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read Plaud results: %s", exc)
        return events

    total = 0
    for entry in data:
        title = entry.get("title", "")
        category = entry.get("category", "")
        named_speakers = entry.get("named_speakers", [])
        duration_min = entry.get("duration_min", 0)


        ts = None
        if title and len(title) >= 10:
            date_prefix = title[:10]
            try:
                ts = datetime.strptime(date_prefix, "%Y-%m-%d").replace(tzinfo=UTC).isoformat()
            except ValueError:
                pass


        cal_match = entry.get("calendar_match")
        if not ts and isinstance(cal_match, dict):
            ts = _parse_ts(cal_match.get("start_datetime"))

        if not ts:
            continue


        matched_pids = set()
        for speaker in named_speakers:
            speaker_lower = speaker.lower().strip() if isinstance(speaker, str) else ""
            if is_own_name(speaker_lower):
                continue
            resolved = _resolve_pid(bridge, speaker)
            if resolved and resolved in target_pids:
                matched_pids.add(resolved)


        speaker_map = entry.get("speaker_map", {})
        if isinstance(speaker_map, dict):
            for plaud_name, real_name in speaker_map.items():
                if (
                    isinstance(real_name, str)
                    and real_name.lower().strip() not in ("unknown", "")
                    and not is_own_name(real_name)
                ):
                    resolved = _resolve_pid(bridge, real_name)
                    if resolved and resolved in target_pids:
                        matched_pids.add(resolved)

        for pid in matched_pids:
            event = {
                "timestamp": ts,
                "source": "plaud",
                "type": "call",
                "direction": "bidirectional",
                "summary": _truncate(title),
                "metadata": {
                    "category": category,
                    "duration_min": round(duration_min, 1) if duration_min else 0,
                    "speaker_count": len(named_speakers),
                },
            }
            events.setdefault(pid, []).append(event)
            total += 1

    log.info("Plaud: loaded %d events for %d people", total, len(events))
    return events


def _load_knowledge_facts(target_pids: set[str], bridge: dict[str, str]) -> dict[str, list[dict]]:
    ""
    events: dict[str, list[dict]] = {}
    person_dir = KNOWLEDGE_ENTITIES_DIR / "person"
    if not person_dir.exists():
        log.info("Knowledge person directory not found")
        return events


    entity_to_pid: dict[str, str] = {}
    for k, v in bridge.items():
        if k.startswith("person_") and v in target_pids:
            entity_to_pid[k] = v

    total = 0
    for ef in sorted(person_dir.glob("*.json")):
        entity_id = ef.stem
        pid = entity_to_pid.get(entity_id)
        if not pid:

            if entity_id in target_pids:
                pid = entity_id
            else:
                continue

        try:
            data = json.loads(ef.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        facts = data.get("facts", [])
        for fact in facts:
            ts = _parse_ts(fact.get("valid_from") or fact.get("created_at"))
            if not ts:
                continue

            attribute = fact.get("attribute", "")
            value = fact.get("value", "")
            source_raw = fact.get("source", "")

            if isinstance(source_raw, dict):
                source_label = source_raw.get("source_type", "")
            else:
                source_label = str(source_raw) if source_raw else ""


            if attribute in ("contact.email", "contact.phone", "contact.linkedin"):
                continue

            event = {
                "timestamp": ts,
                "source": f"knowledge:{source_label}" if source_label else "knowledge",
                "type": "note",
                "direction": "bidirectional",
                "summary": _truncate(f"{attribute}: {value}"),
                "metadata": {
                    "fact_id": fact.get("fact_id", ""),
                    "attribute": attribute,
                    "confidence": fact.get("confidence", 1.0),
                },
            }
            events.setdefault(pid, []).append(event)
            total += 1

    log.info("Knowledge: loaded %d fact-events for %d people", total, len(events))
    return events





def _load_interaction_weights(target_pids: set[str]) -> dict[str, list[dict]]:
    ""




    events: dict[str, list[dict]] = {}
    iw_file = RQ_DIR / "interaction-weights.parquet"
    if not iw_file.exists():
        log.info("Interaction weights file not found")
        return events

    try:
        df = pd.read_parquet(iw_file)
    except Exception as exc:
        log.warning("Failed to read interaction weights: %s", exc)
        return events


    mask = df["to_addr"].isin(target_pids)
    filtered = df[mask]
    log.info("Interaction weights: %d/%d rows match target pids", len(filtered), len(df))

    total = 0
    for _, row in filtered.iterrows():
        pid = str(row["to_addr"])
        ts = _parse_ts(row.get("date"))
        if not ts:
            continue

        source = str(row.get("source", ""))
        account = str(row.get("account", "")) if pd.notna(row.get("account")) else ""
        itype = str(row.get("interaction_type", ""))
        from_addr = str(row.get("from_addr", "")) if pd.notna(row.get("from_addr")) else ""

        event = {
            "timestamp": ts,
            "source": source,
            "source_account": account if account else None,
            "type": _map_interaction_type(itype),
            "direction": _map_interaction_direction(itype, from_addr),
            "summary": "",
            "metadata": {
                "interaction_type": itype,
                "weight": float(row.get("weight", 0)),
            },
        }
        events.setdefault(pid, []).append(event)
        total += 1

    log.info("Interaction weights: loaded %d events for %d people", total, len(events))
    return events





def merge_events(
    iw_events: dict[str, list[dict]],
    rich_sources: list[dict[str, list[dict]]],
) -> dict[str, list[dict]]:
    ""





    merged: dict[str, list[dict]] = {}


    all_pids = set(iw_events.keys())
    for src in rich_sources:
        all_pids.update(src.keys())

    for pid in all_pids:

        rich_events: list[dict] = []
        rich_keys: set[tuple[str, str]] = set()

        for src in rich_sources:
            for ev in src.get(pid, []):
                rich_events.append(ev)
                ts_key = (ev.get("timestamp", "")[:16], ev.get("source", ""))
                rich_keys.add(ts_key)


        iw_only: list[dict] = []
        for ev in iw_events.get(pid, []):
            ts_key = (ev.get("timestamp", "")[:16], ev.get("source", ""))
            if ts_key not in rich_keys:
                iw_only.append(ev)

        all_events = rich_events + iw_only

        all_events.sort(key=_ts_sort_key)
        merged[pid] = all_events

    return merged





def build_person_timeline(
    person: dict,
    events: list[dict],
    compact: bool = False,
) -> dict:
    ""

    source_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for ev in events:
        src = ev.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        t = ev.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
        d = ev.get("direction", "unknown")
        direction_counts[d] = direction_counts.get(d, 0) + 1


    timestamps = [ev.get("timestamp", "") for ev in events if ev.get("timestamp")]
    first_event = min(timestamps) if timestamps else None
    last_event = max(timestamps) if timestamps else None


    out_events = []
    for ev in events:
        out_ev = {
            "timestamp": ev.get("timestamp"),
            "source": ev.get("source"),
            "type": ev.get("type"),
            "direction": ev.get("direction"),
        }
        if not compact:
            out_ev["summary"] = ev.get("summary", "")
            if ev.get("source_account"):
                out_ev["source_account"] = ev["source_account"]
            if ev.get("metadata"):
                out_ev["metadata"] = ev["metadata"]

        out_events.append(out_ev)

    timeline = {
        "person_id": person.get("person_id", ""),
        "name": person.get("name", ""),
        "rq_rank": person.get("rank"),
        "rq_score": person.get("score"),
        "rq_type": person.get("type", ""),
        "generated_at": utc_now().isoformat(),
        "stats": {
            "total_events": len(events),
            "by_source": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
            "by_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "by_direction": dict(sorted(direction_counts.items(), key=lambda x: -x[1])),
            "first_event": first_event,
            "last_event": last_event,
        },
        "events": out_events,
    }
    return timeline





def main():
    parser = argparse.ArgumentParser(
        description="E3 — Cross-source Person Timeline. Aggregates all interaction events per person.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count events per person without writing files",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=150,
        help="Number of top people to process (default: 150)",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Process only this person (name substring match)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Smaller output: no content_preview, no metadata",
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="Skip rich source loading (use only interaction-weights.parquet)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    t0 = time.monotonic()


    people = load_top_people(args.top, args.person)
    if not people:
        log.error("No people loaded. Check RQ scores.")
        sys.exit(1)
    log.info("Processing %d people", len(people))

    target_pids = {p["person_id"] for p in people if p.get("person_id")}
    log.info("Target person_ids: %d", len(target_pids))


    bridge = _load_entity_bridge()
    lookup = _build_target_lookup(bridge, target_pids)


    iw_events = _load_interaction_weights(target_pids)


    rich_sources: list[dict[str, list[dict]]] = []
    if not args.no_rich:
        log.info("Loading rich sources...")
        rich_sources.append(_load_email_events(target_pids, lookup))
        rich_sources.append(_load_calendar_events(target_pids, lookup))
        rich_sources.append(_load_whatsapp_events(target_pids, lookup))
        rich_sources.append(_load_slack_events(target_pids, lookup))
        rich_sources.append(_load_tactiq_events(target_pids, lookup))
        rich_sources.append(_load_attio_notes(target_pids, lookup))
        rich_sources.append(_load_attio_meetings(target_pids, lookup))
        rich_sources.append(_load_plaud_events(target_pids, lookup))
        rich_sources.append(_load_knowledge_facts(target_pids, lookup))


    merged = merge_events(iw_events, rich_sources)


    elapsed_load = time.monotonic() - t0

    if args.dry_run:
        log.info("=" * 60)
        log.info("  DRY RUN — Event counts per person")
        log.info("=" * 60)
        sorted_people = sorted(
            people, key=lambda p: len(merged.get(p["person_id"], [])), reverse=True
        )
        for person in sorted_people:
            pid = person["person_id"]
            evts = merged.get(pid, [])
            if not evts:
                continue

            src_counts = {}
            for e in evts:
                s = e.get("source", "?")
                src_counts[s] = src_counts.get(s, 0) + 1
            src_str = ", ".join(
                f"{k}:{v}" for k, v in sorted(src_counts.items(), key=lambda x: -x[1])
            )
            log.info(
                "  #%d %s (%s): %d events [%s]",
                person.get("rank", 0),
                person.get("name", ""),
                pid,
                len(evts),
                src_str,
            )
        total_events = sum(len(v) for v in merged.values())
        log.info("=" * 60)
        log.info("  Total: %d events across %d people", total_events, len(merged))
        log.info("  Load time: %.1fs", elapsed_load)
        log.info("=" * 60)
    else:
        TIMELINE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        for person in people:
            pid = person["person_id"]
            evts = merged.get(pid, [])
            if not evts:
                log.debug("Skipping %s (%s): no events", person.get("name"), pid)
                continue

            timeline = build_person_timeline(person, evts, compact=args.compact)
            out_path = TIMELINE_OUTPUT_DIR / f"{pid}.json"
            safe_write_json(out_path, timeline)
            written += 1

        elapsed_total = time.monotonic() - t0
        total_events = sum(len(v) for v in merged.values())
        log.info("=" * 60)
        log.info("  Person Timeline — Complete")
        log.info("  Written: %d files to %s", written, TIMELINE_OUTPUT_DIR)
        log.info("  Total events: %d", total_events)
        log.info("  Time: %.1fs", elapsed_total)
        log.info("=" * 60)


if __name__ == "__main__":
    main()
