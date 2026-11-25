#!/usr/bin/env python3
""






























from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from sbk_config import (
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    NLP_DIR,
    PLAUD_PROCESSED_DIR,
    RQ_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    WHATSAPP_DIR,
)

log = logging.getLogger("sbk-l2-person-deep-context")


falliti: list[tuple[str, str]] = []



OUTPUT_DIR = ENRICHED_DIR / "person-deep-context"





def _ts(val) -> str | None:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    if isinstance(val, datetime):
        return val.isoformat()
    s = str(val)
    if s in ("NaT", "nan", "None", ""):
        return None
    return s


def _safe_int(val, default=0) -> int:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0) -> float:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return default


def _parse_json_col(val) -> list | dict | None:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, list | dict):
        return val
    try:
        return json.loads(str(val))
    except (json.JSONDecodeError, TypeError):
        return None


def _normalize_name(name: str) -> str:
    ""
    if not name:
        return ""
    return " ".join(name.lower().strip().split())





class DataStore:
    ""

    def __init__(self):
        self._cache = {}

    def _load_parquet(self, key: str, path: Path) -> pd.DataFrame:
        if key not in self._cache:
            if path.exists():
                log.debug("Loading %s from %s", key, path)
                self._cache[key] = pd.read_parquet(path)
            else:
                log.warning("Missing file: %s", path)
                self._cache[key] = pd.DataFrame()
        return self._cache[key]

    def _load_json(self, key: str, path: Path) -> dict | list:
        if key not in self._cache:
            if path.exists():
                log.debug("Loading %s from %s", key, path)
                self._cache[key] = json.loads(path.read_text(encoding="utf-8"))
            else:
                log.warning("Missing file: %s", path)
                self._cache[key] = {} if key != "top_people" else []
        return self._cache[key]

    @property
    def contacts_merged(self) -> pd.DataFrame:
        return self._load_parquet("contacts_merged", ENRICHED_DIR / "contacts-merged.parquet")

    @property
    def composite_scores(self) -> pd.DataFrame:
        return self._load_parquet("composite_scores", RQ_DIR / "composite-scores-v3.parquet")

    @property
    def top_people(self) -> list[dict]:
        return self._load_json("top_people", RQ_DIR / "top-150-people.json")

    @property
    def interactions(self) -> pd.DataFrame:
        return self._load_parquet("interactions", ENRICHED_DIR / "interactions.parquet")

    @property
    def threads(self) -> pd.DataFrame:
        return self._load_parquet("threads", ENRICHED_DIR / "threads.parquet")

    @property
    def contacts_calendar(self) -> pd.DataFrame:
        return self._load_parquet("contacts_calendar", ENRICHED_DIR / "contacts-calendar.parquet")

    @property
    def interactions_calendar(self) -> pd.DataFrame:
        return self._load_parquet(
            "interactions_calendar", ENRICHED_DIR / "interactions-calendar.parquet"
        )

    @property
    def contacts_whatsapp(self) -> pd.DataFrame:
        return self._load_parquet("contacts_whatsapp", WHATSAPP_DIR / "contacts-whatsapp.parquet")

    @property
    def chats_activity(self) -> pd.DataFrame:
        return self._load_parquet("chats_activity", WHATSAPP_DIR / "chats-activity.parquet")

    @property
    def contacts_slack(self) -> pd.DataFrame:
        return self._load_parquet("contacts_slack", SLACK_DIR / "contacts-slack.parquet")

    @property
    def interactions_slack(self) -> pd.DataFrame:
        return self._load_parquet("interactions_slack", SLACK_DIR / "interactions-slack.parquet")

    @property
    def contacts_tactiq(self) -> pd.DataFrame:
        return self._load_parquet("contacts_tactiq", TACTIQ_DIR / "contacts-tactiq.parquet")

    @property
    def attachment_summary(self) -> pd.DataFrame:
        return self._load_parquet("attachment_summary", ENRICHED_DIR / "attachment_summary.parquet")

    @property
    def entity_map(self) -> dict:
        return self._load_json("entity_map", ENRICHED_DIR / "entity-map.json")

    @property
    def plaud_results(self) -> list[dict]:
        return self._load_json("plaud_results", PLAUD_PROCESSED_DIR / "_full_results_v2.json")

    @property
    def relationship_facts(self) -> pd.DataFrame:
        return self._load_parquet("relationship_facts", NLP_DIR / "relationship-facts.parquet")

    @property
    def deep_facts(self) -> pd.DataFrame:
        return self._load_parquet("deep_facts", NLP_DIR / "deep-facts.parquet")





def build_pid_email_index(entity_map: dict) -> dict[str, set[str]]:
    ""
    idx: dict[str, set[str]] = {}
    for email, info in entity_map.items():
        pid = info.get("person_id")
        if pid:
            idx.setdefault(pid, set()).add(email.lower())
    return idx





def build_name_index(contacts_merged: pd.DataFrame) -> dict[str, str]:
    ""
    idx: dict[str, str] = {}
    if contacts_merged.empty:
        return idx
    for _, row in contacts_merged.iterrows():
        pid = row.get("person_id")
        name = row.get("name", "")
        if pid and name:
            norm = _normalize_name(name)
            if norm:
                idx[norm] = pid
    return idx





def build_person_profile(
    person_id: str,
    data: DataStore,
    pid_emails: dict[str, set[str]],
    name_index: dict[str, str],
) -> dict:
    ""
    profile: dict = {
        "person_id": person_id,
        "name": None,
        "emails": [],
        "phones": [],
        "rq_score": None,
        "rq_rank": None,
        "relationship_type": None,
        "dunbar_circle": None,
        "organization": None,
        "job_title": None,
        "is_internal": False,
        "communication_summary": {},
        "email_detail": {},
        "calendar_detail": {},
        "whatsapp_detail": {},
        "slack_detail": {},
        "tactiq_detail": {},
        "plaud_detail": {},
        "documents_shared": {},
        "groups_shared": [],
        "key_facts": [],
        "relationship_facts": [],
        "deep_facts_summary": {},
        "source_flags": {},
        "last_updated": datetime.now(UTC).isoformat(),
    }

    emails = pid_emails.get(person_id, set())


    cm = data.contacts_merged
    cm_row = None
    if not cm.empty and "person_id" in cm.columns:
        matches = cm[cm["person_id"] == person_id]
        if not matches.empty:
            cm_row = matches.iloc[0]

    if cm_row is not None:
        profile["name"] = cm_row.get("name") or None

        raw_emails = _parse_json_col(cm_row.get("all_emails"))
        if isinstance(raw_emails, list):
            emails = emails | {e.lower() for e in raw_emails if e}
        if cm_row.get("email"):
            emails.add(str(cm_row["email"]).lower())

        real_emails = {e for e in emails if "@" in e and not e.startswith("nameonly:")}
        profile["emails"] = sorted(real_emails)

        phone = cm_row.get("phone_primary")
        if phone and not pd.isna(phone):
            profile["phones"] = [str(phone)]

        profile["organization"] = cm_row.get("organization") or cm_row.get("attio_company") or None
        profile["job_title"] = (
            cm_row.get("attio_job_title") or cm_row.get("personio_position") or None
        )
        profile["is_internal"] = bool(cm_row.get("is_internal", False))


        flag_cols = [c for c in cm.columns if c.startswith("has_")]
        for fc in flag_cols:
            val = cm_row.get(fc)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                profile["source_flags"][fc] = bool(val)


        profile["communication_summary"] = {
            "email_msgs_sent": _safe_int(cm_row.get("email_msgs_sent")),
            "email_msgs_recv": _safe_int(cm_row.get("email_msgs_recv")),
            "email_total_msgs": _safe_int(cm_row.get("email_total_msgs")),
            "email_thread_count": _safe_int(cm_row.get("email_thread_count")),
            "cal_events": _safe_int(cm_row.get("cal_events")),
            "plaud_meetings": _safe_int(cm_row.get("plaud_meetings")),
            "plaud_total_minutes": _safe_float(cm_row.get("plaud_total_minutes")),
            "tactiq_meetings": _safe_int(cm_row.get("tactiq_meetings")),
            "tactiq_total_minutes": _safe_float(cm_row.get("tactiq_total_minutes")),
            "linkedin_messages": _safe_int(cm_row.get("linkedin_messages")),
            "slack_messages": _safe_int(cm_row.get("slack_messages")),
            "whatsapp_messages": _safe_int(cm_row.get("whatsapp_messages")),
            "docusign_contracts": _safe_int(cm_row.get("docusign_contracts")),
            "first_contact": _ts(cm_row.get("first_contact")),
            "last_contact": _ts(cm_row.get("last_contact")),
            "last_contact_source": cm_row.get("last_contact_source") or None,
            "source_count": _safe_int(cm_row.get("source_count")),
        }


        total = (
            _safe_int(cm_row.get("email_total_msgs"))
            + _safe_int(cm_row.get("cal_events"))
            + _safe_int(cm_row.get("slack_messages"))
            + _safe_int(cm_row.get("whatsapp_messages"))
            + _safe_int(cm_row.get("tactiq_meetings"))
            + _safe_int(cm_row.get("plaud_meetings"))
            + _safe_int(cm_row.get("linkedin_messages"))
        )
        profile["communication_summary"]["total_interactions"] = total


        channels = []
        if _safe_int(cm_row.get("email_total_msgs")) > 0:
            channels.append("email")
        if _safe_int(cm_row.get("cal_events")) > 0:
            channels.append("calendar")
        if _safe_int(cm_row.get("slack_messages")) > 0:
            channels.append("slack")
        if _safe_int(cm_row.get("whatsapp_messages")) > 0:
            channels.append("whatsapp")
        if _safe_int(cm_row.get("tactiq_meetings")) > 0:
            channels.append("tactiq")
        if _safe_int(cm_row.get("plaud_meetings")) > 0:
            channels.append("plaud")
        if _safe_int(cm_row.get("linkedin_messages")) > 0:
            channels.append("linkedin")
        if _safe_int(cm_row.get("docusign_contracts")) > 0:
            channels.append("docusign")
        profile["communication_summary"]["channels"] = channels
    else:
        profile["emails"] = sorted(emails)



    person_name = profile["name"]
    cs = data.composite_scores
    if not cs.empty and person_name:
        norm_target = _normalize_name(person_name)

        match = cs[
            cs["person"].apply(lambda x: _normalize_name(str(x)) == norm_target if x else False)
        ]
        if not match.empty:
            cs_row = match.iloc[0]
            profile["rq_score"] = _safe_float(cs_row.get("score_v3"))
            profile["relationship_type"] = cs_row.get("relationship_type") or None
            profile["dunbar_circle"] = (
                cs_row.get("dunbar_label") or cs_row.get("dunbar_circle") or None
            )
            profile["communication_summary"]["trend"] = cs_row.get("trend_v3") or None
            profile["communication_summary"]["confidence"] = _safe_float(cs_row.get("confidence"))


    for entry in data.top_people:
        if entry.get("person_id") == person_id:
            profile["rq_rank"] = entry.get("rank")

            if profile["rq_score"] is None:
                profile["rq_score"] = _safe_float(entry.get("score"))
            if profile["relationship_type"] is None:
                profile["relationship_type"] = entry.get("type")
            break


    if emails:
        _build_email_detail(profile, data, emails)


    if emails:
        _build_calendar_detail(profile, data, emails)


    _build_whatsapp_detail(profile, data, name_index, person_name)


    _build_slack_detail(profile, data, emails, cm_row)


    _build_tactiq_detail(profile, data, emails, person_name)


    _build_plaud_detail(profile, data, person_name)


    _build_attachment_detail(profile, data, emails)


    _build_knowledge_facts(profile, person_id)


    _build_nlp_facts(profile, data, person_name, emails)




    return profile





def _build_email_detail(profile: dict, data: DataStore, emails: set[str]) -> None:
    ""
    interactions = data.interactions
    if interactions.empty:
        return

    emails_lower = {e.lower() for e in emails}


    mask = interactions["from_email"].str.lower().isin(emails_lower) | interactions[
        "to_email"
    ].str.lower().isin(emails_lower)
    person_interactions = interactions[mask]

    if person_interactions.empty:
        return


    subjects_sample = []
    for _, row in person_interactions.head(20).iterrows():
        sample = row.get("subjects_sample")
        if sample and not pd.isna(sample):
            parsed = _parse_json_col(sample)
            if isinstance(parsed, list):
                subjects_sample.extend(parsed[:3])
            elif isinstance(parsed, str):
                subjects_sample.append(parsed)


    seen = set()
    unique_subjects = []
    for s in subjects_sample:
        s_norm = s.strip().lower() if isinstance(s, str) else ""
        if s_norm and s_norm not in seen:
            seen.add(s_norm)
            unique_subjects.append(s.strip())

    profile["email_detail"] = {
        "interaction_pairs": len(person_interactions),
        "total_messages": int(person_interactions["msg_count"].sum()),
        "total_threads": int(person_interactions["thread_count"].sum()),
        "first_email": _ts(person_interactions["first_date"].min()),
        "last_email": _ts(person_interactions["last_date"].max()),
        "sample_subjects": unique_subjects[:15],
    }


    threads = data.threads
    if not threads.empty and "participants" in threads.columns:

        def _person_in_thread(participants_val):
            if participants_val is None or (
                isinstance(participants_val, float) and pd.isna(participants_val)
            ):
                return False
            parsed = _parse_json_col(participants_val)
            if isinstance(parsed, list):
                return any(p.lower() in emails_lower for p in parsed if isinstance(p, str))
            s = str(participants_val).lower()
            return any(e in s for e in emails_lower)

        thread_mask = threads["participants"].apply(_person_in_thread)
        person_threads = threads[thread_mask]
        if not person_threads.empty:
            profile["email_detail"]["thread_count_direct"] = len(person_threads)

            top_threads = person_threads.nlargest(min(10, len(person_threads)), "msg_count")
            profile["email_detail"]["top_threads"] = [
                {
                    "subject": row.get("subject", ""),
                    "messages": _safe_int(row.get("msg_count")),
                    "start": _ts(row.get("date_start")),
                    "end": _ts(row.get("date_end")),
                }
                for _, row in top_threads.iterrows()
            ]


def _build_calendar_detail(profile: dict, data: DataStore, emails: set[str]) -> None:
    ""
    cc = data.contacts_calendar
    if cc.empty:
        return

    emails_lower = {e.lower() for e in emails}


    if "email" in cc.columns:
        match = cc[cc["email"].str.lower().isin(emails_lower)]
        if not match.empty:
            row = match.iloc[0]
            calendars = _parse_json_col(row.get("calendars"))
            profile["calendar_detail"] = {
                "total_events": _safe_int(row.get("total_events")),
                "as_organizer": _safe_int(row.get("as_organizer")),
                "as_attendee": _safe_int(row.get("as_attendee")),
                "first_seen": _ts(row.get("first_seen")),
                "last_seen": _ts(row.get("last_seen")),
                "calendars": calendars if isinstance(calendars, list) else [],
            }


    ic = data.interactions_calendar
    if not ic.empty:
        mask = ic["from_email"].str.lower().isin(emails_lower) | ic["to_email"].str.lower().isin(
            emails_lower
        )
        cal_ints = ic[mask]
        if not cal_ints.empty:
            profile["calendar_detail"]["co_attendance_pairs"] = len(cal_ints)
            profile["calendar_detail"]["total_co_events"] = int(cal_ints["event_count"].sum())


def _build_whatsapp_detail(
    profile: dict,
    data: DataStore,
    name_index: dict[str, str],
    person_name: str | None,
) -> None:
    ""
    wa = data.contacts_whatsapp
    if wa.empty or not person_name:
        return

    norm_name = _normalize_name(person_name)
    if not norm_name:
        return


    match = wa[wa["name"].apply(lambda x: _normalize_name(str(x)) == norm_name if x else False)]
    if match.empty:

        parts = norm_name.split()
        if len(parts) >= 2:
            match = wa[
                wa["name"].apply(
                    lambda x: (
                        (
                            _normalize_name(str(x)).startswith(parts[0])
                            and parts[-1] in _normalize_name(str(x))
                        )
                        if x
                        else False
                    )
                )
            ]

    if match.empty:
        return

    row = match.iloc[0]
    chat_names = _parse_json_col(row.get("chat_names"))

    profile["whatsapp_detail"] = {
        "message_count": _safe_int(row.get("message_count")),
        "messages_sent": _safe_int(row.get("messages_sent")),
        "messages_received": _safe_int(row.get("messages_received")),
        "words_sent": _safe_int(row.get("words_sent")),
        "first_message": _ts(row.get("first_message")),
        "last_message": _ts(row.get("last_message")),
        "chat_count": _safe_int(row.get("chat_count")),
        "chat_names": chat_names if isinstance(chat_names, list) else [],
        "is_group_participant": bool(row.get("is_group_participant", False)),
        "is_1to1_participant": bool(row.get("is_1to1_participant", False)),
        "response_time_avg_hours": _safe_float(row.get("response_time_avg_hours")),
    }


    phone = row.get("phone")
    if phone and not pd.isna(phone) and str(phone) not in profile.get("phones", []):
        profile.setdefault("phones", []).append(str(phone))


    if isinstance(chat_names, list):
        for cn in chat_names:
            if cn and cn not in profile["groups_shared"]:
                profile["groups_shared"].append(cn)


    ca = data.chats_activity
    if not ca.empty and "participants" in ca.columns:
        wa_name = str(row.get("name", ""))

        def _in_participants(p):
            if not p or (isinstance(p, float) and pd.isna(p)):
                return False
            s = str(p)
            return wa_name.lower() in s.lower()

        group_mask = ca["participants"].apply(_in_participants) & (ca["chat_type"] == "group")
        groups = ca[group_mask]
        for _, g in groups.iterrows():
            gname = g.get("chat_name", "")
            if gname and gname not in profile["groups_shared"]:
                profile["groups_shared"].append(gname)


def _build_slack_detail(
    profile: dict,
    data: DataStore,
    emails: set[str],
    cm_row,
) -> None:
    ""
    sc = data.contacts_slack
    if sc.empty:
        return


    slack_row = None
    emails_lower = {e.lower() for e in emails}

    if "email" in sc.columns:
        match = sc[sc["email"].str.lower().isin(emails_lower)]
        if not match.empty:
            slack_row = match.iloc[0]

    if slack_row is None and cm_row is not None:
        slack_uid = cm_row.get("slack_user_id")
        if slack_uid and not pd.isna(slack_uid) and "user_id" in sc.columns:
            match = sc[sc["user_id"] == slack_uid]
            if not match.empty:
                slack_row = match.iloc[0]

    if slack_row is None:
        return

    slack_user_id = slack_row.get("user_id", "")

    profile["slack_detail"] = {
        "user_id": str(slack_user_id),
        "display_name": slack_row.get("display_name") or slack_row.get("real_name") or None,
        "message_count": _safe_int(slack_row.get("message_count")),
        "channels_active": _safe_int(slack_row.get("channels_active")),
        "first_seen": _ts(slack_row.get("first_seen")),
        "last_seen": _ts(slack_row.get("last_seen")),
        "is_bot": bool(slack_row.get("is_bot", False)),
    }


    si = data.interactions_slack
    if not si.empty and slack_user_id:
        user_mask = (si["from_user"] == slack_user_id) | (si["to_user"] == slack_user_id)
        user_ints = si[user_mask]
        if not user_ints.empty:
            channels = user_ints["channel"].unique().tolist()
            profile["slack_detail"]["channels"] = channels[:50]
            profile["slack_detail"]["interaction_count"] = len(user_ints)


            for ch in channels:
                tag = f"slack:{ch}"
                if tag not in profile["groups_shared"]:
                    profile["groups_shared"].append(tag)


def _build_tactiq_detail(
    profile: dict,
    data: DataStore,
    emails: set[str],
    person_name: str | None,
) -> None:
    ""
    tc = data.contacts_tactiq
    if tc.empty:
        return

    tactiq_row = None
    emails_lower = {e.lower() for e in emails}


    if "email" in tc.columns:
        match = tc[tc["email"].str.lower().isin(emails_lower)]
        if not match.empty:
            tactiq_row = match.iloc[0]


    if tactiq_row is None and person_name and "speaker_name" in tc.columns:
        norm = _normalize_name(person_name)
        match = tc[
            tc["speaker_name"].apply(lambda x: _normalize_name(str(x)) == norm if x else False)
        ]
        if not match.empty:
            tactiq_row = match.iloc[0]

    if tactiq_row is None:
        return

    profile["tactiq_detail"] = {
        "meetings": _safe_int(tactiq_row.get("tactiq_meetings")),
        "total_minutes": _safe_float(tactiq_row.get("tactiq_total_minutes")),
        "first_seen": _ts(tactiq_row.get("tactiq_first_seen")),
        "last_seen": _ts(tactiq_row.get("tactiq_last_seen")),
        "speaker_name": tactiq_row.get("speaker_name") or None,
    }


def _build_plaud_detail(profile: dict, data: DataStore, person_name: str | None) -> None:
    ""
    results = data.plaud_results
    if not results or not person_name:
        return

    norm_name = _normalize_name(person_name)
    if not norm_name:
        return


    matching_recordings = []
    total_minutes = 0.0

    for rec in results:
        speakers = rec.get("speaker_map", {})
        named_speakers = rec.get("named_speakers", [])


        found = False
        for sp_key, sp_name in speakers.items():
            if _normalize_name(str(sp_name)) == norm_name:
                found = True
                break

        if not found:
            for sp in named_speakers:
                if _normalize_name(str(sp)) == norm_name:
                    found = True
                    break

        if found:
            matching_recordings.append(
                {
                    "title": rec.get("title", ""),
                    "duration_min": _safe_float(rec.get("duration_min")),
                    "date": rec.get("calendar_match", {}).get("date")
                    if isinstance(rec.get("calendar_match"), dict)
                    else None,
                }
            )
            total_minutes += _safe_float(rec.get("duration_min"))

    if matching_recordings:
        profile["plaud_detail"] = {
            "recordings": len(matching_recordings),
            "total_minutes": round(total_minutes, 1),
            "recent": sorted(
                matching_recordings,
                key=lambda x: x.get("date") or "",
                reverse=True,
            )[:10],
        }


def _build_attachment_detail(profile: dict, data: DataStore, emails: set[str]) -> None:
    ""
    att = data.attachment_summary
    if att.empty or not emails:
        return

    emails_lower = {e.lower() for e in emails}
    if "email" not in att.columns:
        return

    match = att[att["email"].str.lower().isin(emails_lower)]
    if match.empty:
        return


    total_attachments = int(match["total_attachments"].sum())
    total_size = int(match["total_size_bytes"].sum())


    merged_types: dict[str, int] = {}
    for _, row in match.iterrows():
        by_type = _parse_json_col(row.get("by_type"))
        if isinstance(by_type, dict):
            for ext, count in by_type.items():
                merged_types[ext] = merged_types.get(ext, 0) + int(count)

    profile["documents_shared"] = {
        "total_attachments": total_attachments,
        "total_size_bytes": total_size,
        "by_type": dict(sorted(merged_types.items(), key=lambda x: -x[1])),
        "first_attachment": _ts(match["first_attachment"].min()),
        "last_attachment": _ts(match["last_attachment"].max()),
    }


def _build_knowledge_facts(profile: dict, person_id: str) -> None:
    ""





    person_name = profile.get("name")
    if not person_name:
        return

    knowledge_dir = KNOWLEDGE_ENTITIES_DIR / "person"
    if not knowledge_dir.exists():
        return

    name_lower = person_name.lower()

    name_parts = name_lower.split()
    if not name_parts:
        return


    if not hasattr(_build_knowledge_facts, "_name_cache"):
        log.debug("Building Knowledge Layer name cache (one-time)...")
        cache: dict[str, list[tuple[str, dict]]] = {}
        for f in knowledge_dir.iterdir():
            if not f.name.endswith(".json"):
                continue
            try:
                entity = json.loads(f.read_text(encoding="utf-8"))
                cn = (entity.get("canonical_name") or "").lower()
                for word in cn.split():

                    clean = word.strip(",.:;()[]")
                    if len(clean) > 2:
                        cache.setdefault(clean, []).append((f.name, entity))
            except Exception:
                continue
        _build_knowledge_facts._name_cache = cache
        log.debug("  Cached %d unique words from knowledge entities", len(cache))

    cache = _build_knowledge_facts._name_cache



    last_name = name_parts[-1].strip(",.:;()[]")
    candidates = cache.get(last_name, [])

    matched_facts = []
    seen_entities = set()

    for fname, entity in candidates:
        if fname in seen_entities:
            continue
        cn_lower = (entity.get("canonical_name") or "").lower()

        if all(part in cn_lower for part in name_parts):
            seen_entities.add(fname)
            for fact in entity.get("facts", []):
                if fact.get("expired_at"):
                    continue
                matched_facts.append(
                    {
                        "attribute": fact.get("attribute", ""),
                        "value": fact.get("value", ""),
                        "confidence": _safe_float(fact.get("confidence")),
                        "source": fact.get("source", ""),
                        "valid_from": fact.get("valid_from"),
                        "entity_id": entity.get("entity_id", ""),
                    }
                )

    if matched_facts:

        matched_facts.sort(key=lambda x: -x.get("confidence", 0))
        seen_av = set()
        deduped = []
        for f in matched_facts:
            key = (f["attribute"], f["value"])
            if key not in seen_av:
                seen_av.add(key)
                deduped.append(f)
        profile["key_facts"] = deduped[:100]


def _build_nlp_facts(
    profile: dict,
    data: DataStore,
    person_name: str | None,
    emails: set[str],
) -> None:
    ""
    if not person_name:
        return

    name_lower = person_name.lower()


    rf = data.relationship_facts
    if not rf.empty:
        search_cols = [c for c in ["subject", "object", "context", "speaker"] if c in rf.columns]
        if search_cols:
            mask = pd.Series(False, index=rf.index)
            for col in search_cols:
                try:
                    mask = mask | rf[col].astype(str).str.lower().str.contains(name_lower, na=False)
                except Exception:
                    continue

            matches = rf[mask]
            if not matches.empty:

                if "source_date" in matches.columns:
                    try:
                        matches = matches.sort_values("source_date", ascending=False)
                    except Exception:
                        pass
                profile["relationship_facts"] = [
                    row.to_dict() for _, row in matches.head(20).iterrows()
                ]

                for fact in profile["relationship_facts"]:
                    for k, v in list(fact.items()):
                        if isinstance(v, float) and pd.isna(v):
                            fact[k] = None
                        elif isinstance(v, pd.Timestamp):
                            fact[k] = v.isoformat()


    df = data.deep_facts
    if not df.empty:
        search_cols = [
            c
            for c in ["subject", "object", "context", "speaker", "fact_type", "predicate"]
            if c in df.columns and df[c].dtype == "object"
        ]
        if not search_cols:

            search_cols = [c for c in df.columns if df[c].dtype == "object"][:6]
        if search_cols:
            mask = pd.Series(False, index=df.index)
            for col in search_cols:
                try:
                    mask = mask | df[col].astype(str).str.lower().str.contains(name_lower, na=False)
                except Exception:
                    continue

            matches = df[mask]
            if not matches.empty:
                profile["deep_facts_summary"] = {
                    "total_facts": len(matches),
                    "sample": [
                        {
                            k: (
                                v.isoformat()
                                if isinstance(v, pd.Timestamp)
                                else None
                                if isinstance(v, float) and pd.isna(v)
                                else v
                            )
                            for k, v in row.items()
                        }
                        for _, row in matches.head(10).iterrows()
                    ],
                }





def run(
    top_n: int = 100,
    person_id: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[dict]:
    ""

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=== Person Deep Context Builder ===")
    log.info("Top N: %d | Person: %s | Dry run: %s", top_n, person_id or "all", dry_run)

    data = DataStore()


    if person_id:
        target_pids = [person_id]
        log.info("Building profile for single person: %s", person_id)
    else:

        top_list = data.top_people
        if not top_list:
            log.error("No top-150-people.json found — cannot determine top people")
            sys.exit(1)
        target_pids = [p["person_id"] for p in top_list[:top_n] if p.get("person_id")]
        log.info("Building profiles for top %d people (%d with person_id)", top_n, len(target_pids))


    log.info("Building email -> person_id index...")
    pid_emails = build_pid_email_index(data.entity_map)
    log.info("  %d person_ids with email mappings", len(pid_emails))

    log.info("Building name -> person_id index...")
    name_index = build_name_index(data.contacts_merged)
    log.info("  %d names indexed", len(name_index))


    profiles = []


    falliti.clear()
    for i, pid in enumerate(target_pids, 1):
        log.info("[%d/%d] Building profile for %s...", i, len(target_pids), pid)
        try:
            profile = build_person_profile(pid, data, pid_emails, name_index)
            profiles.append(profile)
            log.info(
                "  -> %s | score=%.1f | %d channels | %d facts",
                profile.get("name") or "?",
                profile.get("rq_score") or 0,
                len(profile.get("communication_summary", {}).get("channels", [])),
                len(profile.get("key_facts", [])),
            )
        except Exception as e:
            log.error("  FAILED for %s: %s", pid, e, exc_info=verbose)
            falliti.append((pid, f"costruzione: {type(e).__name__}: {e}"))

    if dry_run:
        log.info("=== DRY RUN — not writing files ===")

        for p in profiles:
            total = p.get("communication_summary", {}).get("total_interactions", 0)
            log.info(
                "  %s (%s) — score=%.1f, type=%s, interactions=%d, facts=%d",
                p.get("name") or "?",
                p.get("person_id"),
                p.get("rq_score") or 0,
                p.get("relationship_type") or "?",
                total,
                len(p.get("key_facts", [])),
            )
    else:

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        for profile in profiles:
            pid = profile["person_id"]
            out_path = OUTPUT_DIR / f"{pid}.json"
            try:
                out_path.write_text(
                    json.dumps(profile, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
                written += 1
            except Exception as e:
                log.error("Failed to write %s: %s", out_path, e)
                falliti.append((pid, f"scrittura: {type(e).__name__}: {e}"))
        log.info("Wrote %d/%d profiles to %s", written, len(profiles), OUTPUT_DIR)


    log.info("=== Summary ===")
    log.info("Profiles built: %d", len(profiles))
    scores = [p.get("rq_score") or 0 for p in profiles]
    if scores:
        log.info(
            "Score range: %.1f - %.1f (avg %.1f)",
            min(scores),
            max(scores),
            sum(scores) / len(scores),
        )
    total_facts = sum(len(p.get("key_facts", [])) for p in profiles)
    log.info("Total facts: %d (avg %.1f/person)", total_facts, total_facts / max(len(profiles), 1))
    with_wa = sum(1 for p in profiles if p.get("whatsapp_detail"))
    with_slack = sum(1 for p in profiles if p.get("slack_detail"))
    with_tactiq = sum(1 for p in profiles if p.get("tactiq_detail"))
    with_plaud = sum(1 for p in profiles if p.get("plaud_detail"))
    log.info(
        "Source coverage: WA=%d, Slack=%d, Tactiq=%d, Plaud=%d",
        with_wa,
        with_slack,
        with_tactiq,
        with_plaud,
    )

    if falliti:
        log.error("Profili NON fatti: %d su %d", len(falliti), len(target_pids))
        for pid, perche in falliti:
            log.error("  %s — %s", pid, perche)

    return profiles





def main():
    parser = argparse.ArgumentParser(
        description="Build deep contextual profiles for top people",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--top",
        type=int,
        default=150,
        help="Number of top people to process (default: 100)",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Build profile for a single person_id (e.g., p_78de142e)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute profiles without writing to disk",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()


    from sbk_config import acquire_pid_lock

    if not acquire_pid_lock("person-deep-context", logger=log):
        log.warning("person-deep-context: lock tenuto da un'altra istanza, exit 75")
        sys.exit(75)
    run(top_n=args.top, person_id=args.person, dry_run=args.dry_run, verbose=args.verbose)
    if falliti:
        sys.exit(1)


if __name__ == "__main__":
    main()
