#!/usr/bin/env python3
"""People universe: every person named anywhere (contacts, CRM, graph, HR directory, transcripts, Notion, Slack,
LinkedIn, DocuSign, relationship facts), clustered by name, with when they were first and last seen, into
enriched/people-universe.parquet.
"""

from __future__ import annotations

import argparse
import json
import logging
import re


import sys as _sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sbk_config import (
    DATA_ROOT,
    ENRICHED_DIR,
    ENTITIES_FILE,
    check_inputs_changed,
    mark_last_run,
    safe_write_parquet,
    save_input_checkpoint,
)

OUTPUT_PATH = DATA_ROOT / "enriched" / "people-universe.parquet"

log = logging.getLogger("sbk.people-universe")


EXCLUDE_NAMES = frozenset(
    {
        "",
        "unknown",
        "sconosciuto",
        "speaker",
        "host",
        "guest",
        "partecipant",
        "participant",
        "moderator",
        "organizer",
        "bot",
        "system",
        "ai",
        "assistant",
        "chatgpt",
        "claude",
        "google meet",
        "zoom",
        "teams",
        "google calendar",
        "slackbot",
        "notion",
        "automated",
    }
)


MIN_NAME_LENGTH = 2


FUZZY_THRESHOLD = 88

LAST_NAME_THRESHOLD = 80





@dataclass
class PersonMention:
    ""

    name: str
    email: str = ""
    source_type: str = ""
    source_id: str = ""
    context: str = ""
    date: str = ""


def _normalize_name(raw: str) -> str:
    ""
    if not raw:
        return ""

    name = raw.strip().strip("\"'")

    if "@" in name and " " not in name:
        return ""

    for prefix in ("dr.", "dr ", "prof.", "prof ", "ing.", "ing ", "avv.", "avv "):
        if name.lower().startswith(prefix):
            name = name[len(prefix) :].strip()

    name = " ".join(w.capitalize() if w.islower() else w for w in name.split())

    name = re.sub(r"\s+", " ", name).strip()
    return name


def _is_valid_name(name: str) -> bool:
    ""
    if not name or len(name) < MIN_NAME_LENGTH:
        return False
    if name.lower() in EXCLUDE_NAMES:
        return False

    if name.replace(" ", "").isdigit():
        return False

    if re.match(r"^speaker\s*\d+$", name, re.IGNORECASE):
        return False
    return True





def extract_contacts_merged() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "enriched" / "contacts-merged.parquet"
    if not path.exists():
        log.warning("contacts-merged.parquet not found")
        return []
    cols = ["name", "email", "person_id", "last_contact", "first_contact"]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        df = pd.read_parquet(path, columns=["name", "email", "person_id"])
    mentions = []
    for _, row in df.iterrows():
        name = _normalize_name(str(row.get("name", "")))
        if _is_valid_name(name):
            date_str = ""
            last_contact = row.get("last_contact")
            if pd.notna(last_contact):
                try:
                    date_str = str(last_contact)[:10]
                except Exception:
                    pass
            mentions.append(
                PersonMention(
                    name=name,
                    email=str(row.get("email", "")).lower().strip(),
                    source_type="contacts-merged",
                    source_id=str(row.get("person_id", "")),
                    date=date_str,
                )
            )
    log.info(f"contacts-merged: {len(mentions)} people")
    return mentions


def extract_attio_people() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "attio" / "people-raw.json"
    if not path.exists():
        log.warning("attio/people-raw.json not found")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    mentions = []
    for record in data:
        values = record.get("values", {})

        name_entries = values.get("name", [])
        name = ""
        if name_entries:
            first = name_entries[0] if isinstance(name_entries, list) else name_entries
            if isinstance(first, dict):
                name = first.get("full_name", "") or first.get("value", "")
            else:
                name = str(first)
        name = _normalize_name(name)
        if not _is_valid_name(name):
            continue

        email_entries = values.get("email_addresses", [])
        email = ""
        if email_entries and isinstance(email_entries, list):
            for e in email_entries:
                addr = ""
                if isinstance(e, dict):
                    addr = e.get("email_address", "") or e.get("value", "")
                elif isinstance(e, str):
                    addr = e
                if addr and "@" in addr:
                    email = addr.lower().strip()
                    break

        ctx_parts = []
        for field_name in ("job_title", "primary_location"):
            entries = values.get(field_name, [])
            if entries:
                val = entries[0] if isinstance(entries, list) else entries
                if isinstance(val, dict):
                    val = val.get("value", "")
                if val:
                    ctx_parts.append(str(val))
        mentions.append(
            PersonMention(
                name=name,
                email=email,
                source_type="attio",
                source_id=record.get("id", {}).get("record_id", ""),
                context=", ".join(ctx_parts) if ctx_parts else "",
            )
        )
    log.info(f"attio: {len(mentions)} people")
    return mentions


def extract_network_graph() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "exports" / "network-graph.json"
    if not path.exists():
        log.warning("exports/network-graph.json not found")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    mentions = []
    for node in nodes:
        name = _normalize_name(node.get("name", ""))
        if _is_valid_name(name):
            mentions.append(
                PersonMention(
                    name=name,
                    email=str(node.get("email", "")).lower().strip(),
                    source_type="network-graph",
                    source_id=node.get("email", ""),
                )
            )
    log.info(f"network-graph: {len(mentions)} people")
    return mentions


def extract_personio() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "personio" / "processed" / "employees.parquet"
    if not path.exists():
        log.warning("personio/processed/employees.parquet not found")
        return []
    cols = ["name", "email", "employee_id", "department", "team", "position", "status", "hire_date"]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        df = pd.read_parquet(path)
    mentions = []
    for _, row in df.iterrows():
        name = _normalize_name(str(row.get("name", "")))
        if _is_valid_name(name):
            ctx_parts = []
            for c in ("position", "department", "team", "status"):
                v = row.get(c, "")
                if v and str(v) != "nan":
                    ctx_parts.append(str(v))
            date_str = ""
            hire = row.get("hire_date", "")
            if hire and str(hire) != "nan":
                date_str = str(hire)[:10]
            mentions.append(
                PersonMention(
                    name=name,
                    email=str(row.get("email", "")).lower().strip(),
                    source_type="personio",
                    source_id=str(row.get("employee_id", "")),
                    context=", ".join(ctx_parts) if ctx_parts else "",
                    date=date_str,
                )
            )
    log.info(f"personio: {len(mentions)} people")
    return mentions


def extract_plaud_speakers() -> list[PersonMention]:
    ""
    overrides_path = DATA_ROOT / "plaud" / "processed" / "_speaker_overrides.json"
    results_path = DATA_ROOT / "plaud" / "processed" / "_full_results_v2.json"
    mentions = []
    seen_names: set[str] = set()


    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        for filename, speakers in overrides.items():
            for speaker_key, speaker_name in speakers.items():
                name = _normalize_name(speaker_name)
                if _is_valid_name(name) and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="plaud",
                            source_id=filename,
                            context=f"speaker in recording ({speaker_key})",
                        )
                    )


    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        for entry in results:

            for speaker_name in entry.get("named_speakers", []):
                name = _normalize_name(speaker_name)
                if _is_valid_name(name) and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    title = entry.get("title", "")[:80]
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="plaud",
                            source_id=entry.get("source_file", ""),
                            context=f"speaker: {title}" if title else "speaker",
                        )
                    )

            smap = entry.get("speaker_map", {})
            for _, speaker_val in smap.items():
                if isinstance(speaker_val, dict):
                    speaker_name = speaker_val.get("identity", "")
                elif isinstance(speaker_val, str):
                    speaker_name = speaker_val
                else:
                    continue
                name = _normalize_name(speaker_name)
                if _is_valid_name(name) and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="plaud",
                            source_id=entry.get("source_file", ""),
                        )
                    )

    log.info(f"plaud: {len(mentions)} people")
    return mentions


def extract_tactiq_participants() -> list[PersonMention]:
    ""
    raw_dir = DATA_ROOT / "tactiq" / "raw"
    if not raw_dir.exists():
        log.warning("tactiq/raw/ not found")
        return []
    mentions = []
    seen_names: set[str] = set()
    for fpath in sorted(raw_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fpath.name)
        date = date_match.group(1) if date_match else ""
        participants = data.get("participants", [])
        if not isinstance(participants, list):
            continue
        for p in participants:
            pname = p.get("name", "") if isinstance(p, dict) else str(p)
            name = _normalize_name(pname)
            if _is_valid_name(name) and name.lower() not in seen_names:
                seen_names.add(name.lower())
                title = data.get("title", "")[:80]
                mentions.append(
                    PersonMention(
                        name=name,
                        source_type="tactiq",
                        source_id=fpath.name,
                        context=f"participant: {title}" if title else "meeting participant",
                        date=date,
                    )
                )
    log.info(f"tactiq: {len(mentions)} people")
    return mentions


def _extract_notion_text(prop: object) -> str:
    ""
    if isinstance(prop, str):
        return prop
    if not isinstance(prop, dict):
        return ""

    for key in ("title", "rich_text"):
        arr = prop.get(key)
        if isinstance(arr, list):
            parts = []
            for item in arr:
                if isinstance(item, dict):
                    text_obj = item.get("text", {})
                    if isinstance(text_obj, dict):
                        parts.append(text_obj.get("content", ""))
                    elif isinstance(item.get("plain_text"), str):
                        parts.append(item["plain_text"])
            return " ".join(parts).strip()

    for key in ("name", "value", "plain_text", "content"):
        v = prop.get(key)
        if isinstance(v, str):
            return v
    return ""


def extract_notion_people() -> list[PersonMention]:
    ""
    db_dir = DATA_ROOT / "notion" / "databases"
    if not db_dir.exists():
        log.warning("notion/databases/ not found")
        return []
    mentions = []
    seen: set[str] = set()

    name_pattern = re.compile(r"(?:^|\b)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\b|$)")
    for fpath in sorted(db_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        rows = data.get("rows", [])
        for row in rows:
            props = row.get("properties", {})
            if not isinstance(props, dict):
                continue

            for field_name in (
                "Assignee",
                "Owner",
                "Person",
                "Responsabile",
                "Assegnato",
                "Created by",
                "Assigned to",
            ):
                val = props.get(field_name)
                if val is None:
                    continue
                text = _extract_notion_text(val)
                name = _normalize_name(text)
                if _is_valid_name(name) and name.lower() not in seen:
                    seen.add(name.lower())
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="notion",
                            source_id=fpath.stem,
                        )
                    )

            title_prop = props.get("Name")
            if title_prop is None:
                continue
            title_text = _extract_notion_text(title_prop)
            if title_text:

                for match in name_pattern.finditer(title_text):
                    candidate = match.group(1).strip()
                    name = _normalize_name(candidate)
                    if _is_valid_name(name) and name.lower() not in seen:
                        seen.add(name.lower())
                        mentions.append(
                            PersonMention(
                                name=name,
                                source_type="notion",
                                source_id=fpath.stem,
                                context=title_text[:100],
                            )
                        )
    log.info(f"notion: {len(mentions)} people")
    return mentions


def extract_slack_users() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "slack" / "slack-users.json"
    if not path.exists():
        log.warning("slack/slack-users.json not found")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    mentions = []
    users = data.values() if isinstance(data, dict) else data
    for user in users:
        if not isinstance(user, dict):
            continue
        if user.get("is_bot") or user.get("deleted"):
            continue
        name = _normalize_name(
            user.get("real_name", "") or user.get("display_name", "") or user.get("name", "")
        )
        if _is_valid_name(name):
            mentions.append(
                PersonMention(
                    name=name,
                    source_type="slack",
                    source_id=user.get("user_id", ""),
                )
            )
    log.info(f"slack: {len(mentions)} people")
    return mentions


def extract_linkedin() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "linkedin" / "processed" / "contacts-linkedin.parquet"
    if not path.exists():
        log.warning("linkedin/processed/contacts-linkedin.parquet not found")
        return []
    try:
        df = pd.read_parquet(path, columns=["name", "email", "headline", "company"])
    except Exception:
        df = pd.read_parquet(path)
    mentions = []
    for _, row in df.iterrows():
        name = _normalize_name(str(row.get("name", "")))
        if _is_valid_name(name):
            ctx_parts = []
            for c in ("headline", "company"):
                v = row.get(c, "")
                if v and str(v) != "nan":
                    ctx_parts.append(str(v)[:80])
            mentions.append(
                PersonMention(
                    name=name,
                    email=str(row.get("email", "")).lower().strip() if row.get("email") else "",
                    source_type="linkedin",
                    context=", ".join(ctx_parts) if ctx_parts else "",
                )
            )
    log.info(f"linkedin: {len(mentions)} people")
    return mentions


def extract_docusign() -> list[PersonMention]:
    ""
    path = DATA_ROOT / "docusign" / "contracts-metadata.json"
    if not path.exists():
        log.warning("docusign/contracts-metadata.json not found")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    mentions = []
    seen: set[str] = set()
    name_pattern = re.compile(r"(?:^|\b)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\b|$)")
    for contract in data:
        from_val = contract.get("from", "")
        if from_val:
            name = _normalize_name(from_val)
            if _is_valid_name(name) and name.lower() not in seen:
                seen.add(name.lower())
                mentions.append(
                    PersonMention(
                        name=name,
                        source_type="docusign",
                        source_id=contract.get("name", ""),
                        context="contract party",
                    )
                )

        cname = contract.get("name", "")
        if cname:
            for match in name_pattern.finditer(cname):
                candidate = match.group(1).strip()
                name = _normalize_name(candidate)
                if _is_valid_name(name) and name.lower() not in seen:
                    seen.add(name.lower())
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="docusign",
                            source_id=cname[:80],
                            context="mentioned in contract",
                        )
                    )
    log.info(f"docusign: {len(mentions)} people")
    return mentions


def _looks_like_person_name(text: str) -> bool:
    ""
    words = text.split()
    if len(words) < 2 or len(words) > 4:
        return False

    if not all(w[0].isupper() for w in words if w):
        return False

    if len(text) > 40:
        return False

    non_name = {
        "team",
        "project",
        "company",
        "meeting",
        "office",
        "group",
        "department",
        "campaign",
        "strategy",
        "process",
        "system",
        "management",
        "development",
    }
    if any(w.lower() in non_name for w in words):
        return False
    return True


def extract_relationship_facts() -> list[PersonMention]:
    ""




    path = DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"
    if not path.exists():
        log.warning("l3/nlp/relationship-facts.parquet not found")
        return []
    df = pd.read_parquet(path, columns=["subject", "object", "predicate", "fact_type"])
    mentions = []
    seen: set[str] = set()


    for subj in df["subject"].unique():
        name = _normalize_name(str(subj))
        if _is_valid_name(name) and _looks_like_person_name(name) and name.lower() not in seen:
            seen.add(name.lower())
            mentions.append(
                PersonMention(
                    name=name,
                    source_type="relationship-facts",
                    context="subject in relationship facts",
                )
            )


    person_fact_types = {"introduction", "relationship_fact"}
    person_facts = df[df["fact_type"].isin(person_fact_types)]
    for obj in person_facts["object"].unique():
        name = _normalize_name(str(obj))
        if _is_valid_name(name) and _looks_like_person_name(name) and name.lower() not in seen:
            seen.add(name.lower())
            mentions.append(
                PersonMention(
                    name=name,
                    source_type="relationship-facts",
                    context="object in relationship facts",
                )
            )

    log.info(f"relationship-facts: {len(mentions)} people")
    return mentions


def extract_attio_transcripts() -> list[PersonMention]:
    ""
    transcript_dir = DATA_ROOT / "attio" / "transcripts"
    if not transcript_dir.exists():
        return []
    mentions = []
    seen: set[str] = set()
    name_pattern = re.compile(r"(?:^|\b)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\b|$)")
    for fpath in sorted(transcript_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        title = data.get("meeting_title", "") or data.get("title", "")
        date = data.get("meeting_date", "")
        if title:
            for match in name_pattern.finditer(title):
                candidate = match.group(1).strip()
                name = _normalize_name(candidate)
                if _is_valid_name(name) and name.lower() not in seen:
                    seen.add(name.lower())
                    mentions.append(
                        PersonMention(
                            name=name,
                            source_type="attio-transcript",
                            source_id=fpath.stem,
                            context=title[:100],
                            date=str(date)[:10] if date else "",
                        )
                    )
    log.info(f"attio-transcripts: {len(mentions)} people")
    return mentions





@dataclass
class PersonEntity:
    ""

    canonical_name: str
    aliases: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    contexts: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    mention_count: int = 0


def _get_last_name(name: str) -> str:
    ""
    parts = name.split()
    return parts[-1].lower() if parts else ""


def _names_match(name_a: str, name_b: str) -> bool:
    ""




    a_lower = name_a.lower()
    b_lower = name_b.lower()

    if a_lower == b_lower:
        return True

    if fuzz.token_sort_ratio(a_lower, b_lower) < FUZZY_THRESHOLD:
        return False

    a_parts = a_lower.split()
    b_parts = b_lower.split()
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        a_last = a_parts[-1]
        b_last = b_parts[-1]
        if fuzz.ratio(a_last, b_last) < LAST_NAME_THRESHOLD:
            return False
    return True


def cluster_mentions(all_mentions: list[PersonMention]) -> list[PersonEntity]:
    ""

    email_groups: dict[str, PersonEntity] = {}
    name_only: list[PersonMention] = []

    for m in all_mentions:
        if m.email and "@" in m.email and m.email != "nan":
            email_key = m.email.lower().strip()
            if email_key not in email_groups:
                email_groups[email_key] = PersonEntity(canonical_name=m.name)
            entity = email_groups[email_key]
            entity.emails.add(email_key)
            entity.aliases.add(m.name)
            entity.sources.add(m.source_id)
            entity.source_types.add(m.source_type)
            if m.context and len(entity.contexts) < 5:
                entity.contexts.append(m.context)
            entity.mention_count += 1
            if m.date:
                if not entity.first_seen or m.date < entity.first_seen:
                    entity.first_seen = m.date
                if not entity.last_seen or m.date > entity.last_seen:
                    entity.last_seen = m.date

            if len(m.name) > len(entity.canonical_name):
                entity.canonical_name = m.name
        else:
            name_only.append(m)


    remaining: list[PersonMention] = []
    for m in name_only:
        matched = False
        m_lower = m.name.lower()
        for entity in email_groups.values():
            for alias in entity.aliases:
                if _names_match(m.name, alias):
                    entity.aliases.add(m.name)
                    entity.sources.add(m.source_id)
                    entity.source_types.add(m.source_type)
                    if m.context and len(entity.contexts) < 5:
                        entity.contexts.append(m.context)
                    entity.mention_count += 1
                    if len(m.name) > len(entity.canonical_name):
                        entity.canonical_name = m.name
                    matched = True
                    break
            if matched:
                break
        if not matched:
            remaining.append(m)



    name_blocks: dict[str, list[PersonMention]] = {}
    for m in remaining:
        last = _get_last_name(m.name)
        key = last[0] if last else "?"
        name_blocks.setdefault(key, []).append(m)

    name_entities: list[PersonEntity] = []
    for _block_key, block_mentions in name_blocks.items():
        block_entities: list[PersonEntity] = []
        for m in block_mentions:
            matched = False
            m_lower = m.name.lower()
            for entity in block_entities:
                for alias in entity.aliases:
                    if fuzz.token_sort_ratio(m_lower, alias.lower()) >= FUZZY_THRESHOLD:
                        entity.aliases.add(m.name)
                        entity.sources.add(m.source_id)
                        entity.source_types.add(m.source_type)
                        if m.context and len(entity.contexts) < 5:
                            entity.contexts.append(m.context)
                        entity.mention_count += 1
                        if len(m.name) > len(entity.canonical_name):
                            entity.canonical_name = m.name
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                entity = PersonEntity(
                    canonical_name=m.name,
                    aliases={m.name},
                    sources={m.source_id} if m.source_id else set(),
                    source_types={m.source_type},
                    contexts=[m.context] if m.context else [],
                    mention_count=1,
                    first_seen=m.date,
                    last_seen=m.date,
                )
                block_entities.append(entity)
        name_entities.extend(block_entities)


    all_entities = list(email_groups.values()) + name_entities


    all_entities.sort(key=lambda e: e.mention_count, reverse=True)
    return all_entities





def build_dataframe(entities: list[PersonEntity]) -> pd.DataFrame:
    ""
    rows = []
    for i, e in enumerate(entities):

        pid = f"pu_{e.canonical_name.lower().replace(' ', '_')}"
        rows.append(
            {
                "person_id": pid,
                "canonical_name": e.canonical_name,
                "aliases": "|".join(sorted(e.aliases - {e.canonical_name})),
                "emails": "|".join(sorted(e.emails)),
                "source_types": "|".join(sorted(e.source_types)),
                "source_count": len(e.source_types),
                "mention_count": e.mention_count,
                "context": " | ".join(e.contexts[:3]),
                "first_seen": e.first_seen,
                "last_seen": e.last_seen,
            }
        )
    return pd.DataFrame(rows)


def enrich_temporal_data(df: pd.DataFrame) -> pd.DataFrame:
    ""




    merged_path = DATA_ROOT / "enriched" / "contacts-merged.parquet"
    if not merged_path.exists():
        log.info("contacts-merged not found, skipping temporal enrichment")
        return df

    try:
        cm = pd.read_parquet(
            merged_path,
            columns=["email", "last_contact", "first_contact"],
        )
    except Exception as exc:
        log.warning(f"Failed to read contacts-merged for temporal enrichment: {exc}")
        return df


    email_dates: dict[str, tuple[str, str]] = {}
    for _, row in cm.iterrows():
        email = str(row.get("email", "")).strip().lower()
        if not email or "@" not in email:
            continue
        last_c = row.get("last_contact")
        first_c = row.get("first_contact")
        last_str = str(last_c)[:10] if pd.notna(last_c) else ""
        first_str = str(first_c)[:10] if pd.notna(first_c) else ""
        if last_str or first_str:
            email_dates[email] = (last_str, first_str)

    enriched_count = 0
    for idx, row in df.iterrows():
        emails = str(row.get("emails", ""))
        if not emails:
            continue
        best_last = row.get("last_seen", "") or ""
        best_first = row.get("first_seen", "") or ""
        for em in emails.split("|"):
            em = em.strip().lower()
            if em in email_dates:
                cm_last, cm_first = email_dates[em]
                if cm_last and (not best_last or cm_last > best_last):
                    best_last = cm_last
                if cm_first and (not best_first or cm_first < best_first):
                    best_first = cm_first
        if best_last != (row.get("last_seen", "") or "") or best_first != (
            row.get("first_seen", "") or ""
        ):
            df.at[idx, "last_seen"] = best_last
            df.at[idx, "first_seen"] = best_first
            enriched_count += 1

    log.info(f"Temporal enrichment: {enriched_count} entities updated from contacts-merged")
    return df





def main() -> None:
    parser = argparse.ArgumentParser(description="Build People Universe Index")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--force", action="store_true", help="Bypass incremental guard")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    _guard_inputs = [
        ENRICHED_DIR / "contacts-merged.parquet",
        ENRICHED_DIR / "entity-map.json",
        ENTITIES_FILE,
    ]
    if not args.force and not check_inputs_changed("people-universe", _guard_inputs):
        log.info("Incremental: inputs unchanged, skipping")
        mark_last_run("people-universe")
        return

    log.info("Building People Universe Index...")
    t0 = time.time()


    all_mentions: list[PersonMention] = []
    extractors = [
        ("contacts-merged", extract_contacts_merged),
        ("attio", extract_attio_people),
        ("network-graph", extract_network_graph),
        ("personio", extract_personio),
        ("plaud", extract_plaud_speakers),
        ("tactiq", extract_tactiq_participants),
        ("notion", extract_notion_people),
        ("slack", extract_slack_users),
        ("linkedin", extract_linkedin),
        ("docusign", extract_docusign),
        ("relationship-facts", extract_relationship_facts),
        ("attio-transcripts", extract_attio_transcripts),
    ]

    for name, extractor in extractors:
        try:
            mentions = extractor()
            all_mentions.extend(mentions)
        except Exception as exc:
            log.error(f"Error extracting {name}: {exc}")

    log.info(f"Total mentions collected: {len(all_mentions)}")


    entities = cluster_mentions(all_mentions)
    log.info(f"Unique entities after clustering: {len(entities)}")


    df = build_dataframe(entities)


    df = enrich_temporal_data(df)


    with_email = len(df[df["emails"] != ""])
    multi_source = len(df[df["source_count"] > 1])
    elapsed = time.time() - t0

    log.info("Stats:")
    log.info(f"  Total people: {len(df)}")
    log.info(f"  With email: {with_email}")
    log.info(f"  Multi-source: {multi_source}")
    log.info("  Source distribution:")
    for src in sorted(
        df["source_types"].str.split("|").explode().value_counts().items(), key=lambda x: -x[1]
    ):
        log.info(f"    {src[0]}: {src[1]}")
    with_last_seen = len(df[df["last_seen"].astype(str).str.strip() != ""])
    log.info(f"  With last_seen: {with_last_seen} ({with_last_seen * 100 // max(len(df), 1)}%)")
    with_first_seen = len(df[df["first_seen"].astype(str).str.strip() != ""])
    log.info(f"  With first_seen: {with_first_seen} ({with_first_seen * 100 // max(len(df), 1)}%)")
    log.info(f"  Time: {elapsed:.1f}s")

    if args.dry_run:
        log.info("[DRY RUN] Would write to %s", OUTPUT_PATH)

        print("\n--- Sample (top 20) ---")
        print(df.head(20).to_string(index=False))
        return


    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(df, OUTPUT_PATH, index=False)
    save_input_checkpoint("people-universe", _guard_inputs)
    mark_last_run("people-universe")
    log.info(f"Written {len(df)} entities to {OUTPUT_PATH}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-people-universe", source="people-universe", stage="l2", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
