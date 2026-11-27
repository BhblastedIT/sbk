#!/usr/bin/env python3
"""Relationship fact extraction: reads your conversations and documents from every source (meetings, calls,
WhatsApp, Slack, CRM notes, ChatGPT, Notion, Drive, email, voice memos) and asks a model for facts about the
people in them and their relationships, with the quote they come from. --dry-run counts the documents and
estimates the cost; the text is sent to the model provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


from trascrizioni import testo_leggibile  # noqa: E402
from xs_l3_common import SBKData, call_claude, setup_logging
from xs_l3_email_filter import filter_emails as email_prefilter
from xs_l3_routing import SmartRouter

from sbk_config import (
    ATTIO_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    ATTIO_TRANSCRIPTS_DIRS,
    CHATGPT_DIR,
    DATA_ROOT,
    EMAILS_DIR,
    GDRIVE_DIR,
    NOTION_DIR,
    OWNER_LABEL,
    OWNER_NAME,
    OWNER_SPEAKER_LABELS,
    PLAUD_DIR,
    RELATIONSHIP_FACTS_FILE,
    RELATIONSHIP_RESPONSES_DIR,
    SLACK_CONVERSATIONS_DIR,
    TACTIQ_RAW_DIR,
    VOICE_MEMOS_TRANSCRIPTS_DIR,
    WHATSAPP_CHATS_DIR,
    acquire_pid_lock,
    attio_transcript_files,
    safe_write_parquet,
    scrivi_sidecar_schema,
)

log = logging.getLogger("sbk-rel-extract")

# Who "I" and "my" are: you, from sbk.config.json (owner, own_names).
_OWNER_ALIASES = sorted(a for a in OWNER_SPEAKER_LABELS if a != OWNER_NAME.lower())
_OWNER_WHO = (
    f'"{OWNER_NAME}"' + (" (aliases: " + ", ".join(f'"{a}"' for a in _OWNER_ALIASES) + ")" if _OWNER_ALIASES else "")
    if OWNER_NAME
    else "the person whose data this is"
)
_OWNER_RULE = (
    f'- The primary user is {_OWNER_WHO}. When "my" or "I" is used by a speaker, '
    "try to identify if they are the primary user based on participant labels."
)














SCHEMA_RELATIONSHIP_FACTS = "2026-08-23"


def _dichiara_schema(df) -> None:
    ""





    try:
        scrivi_sidecar_schema(
            RELATIONSHIP_FACTS_FILE,
            SCHEMA_RELATIONSHIP_FACTS,
            righe=int(len(df)),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Schema sidecar not written (%s): the file will have an unknown version", e)



_CONF_MAP = {"high": 0.85, "medium": 0.60, "low": 0.35}


def _conf_to_float(raw: str | float | None) -> float:
    ""
    if isinstance(raw, int | float):
        return float(raw)
    s = str(raw or "medium").strip().lower()
    return _CONF_MAP.get(s, 0.60)


def _taglia(testo: str, limite: int) -> str:
    ""








    testo = str(testo or "").strip()
    if len(testo) <= limite:
        return testo
    tagliato = testo[:limite]
    spazio = tagliato.rfind(" ")
    if spazio >= limite // 2:
        tagliato = tagliato[:spazio]
    return tagliato.rstrip()


def _citazione(item: dict, limite: int) -> tuple[str, str, str]:
    ""

















    quote = _taglia(item.get("quote"), limite)
    summary = _taglia(item.get("summary"), limite)
    if not quote and not summary:
        summary = _taglia(item.get("context"), limite)
    return quote, summary, (quote or summary)


HAIKU_MODEL = "claude-haiku-4-5-20251001"


_PROVIDER = "anthropic"

SOURCES = [
    "plaud",
    "tactiq",
    "whatsapp",
    "slack",
    "slack_dm",
    "attio_notes",
    "attio_call",
    "chatgpt",
    "notion",
    "gdrive",
    "email",
    "voice_memo",
]


MAX_TEXT_LENGTH = 80_000


def get_fact_limits(doc_length: int) -> tuple[int, int]:
    ""




    if doc_length < 500:
        return (5, 150)
    elif doc_length < 2000:
        return (10, 200)
    elif doc_length < 5000:
        return (15, 250)
    elif doc_length < 15000:
        return (25, 250)
    else:
        return (35, 300)




SYSTEM_PROMPT = """You are a relationship intelligence analyst extracting facts from conversations.

CRITICAL: Return ONLY a raw JSON object. No markdown, no code blocks, no explanation, no text before or after the JSON. Start your response with { and end with }.

Extract these 6 types of facts:

1. relationship_facts: Personal/professional connections between people.
   Professional predicates: WORKS_AT, WORKS_WITH, REPORTS_TO, MANAGES, FOUNDED, ADVISES, PARTNER_OF, CLIENT_OF, PROVIDES_SERVICE_TO
   Financial predicates: INVESTOR_IN, OWNS_EQUITY_IN, LENDS_TO, BORROWS_FROM, PAYS, PAID_BY
   Personal predicates: FAMILY_OF, FRIEND_OF, LIVES_IN
   Connection predicates: KNOWS, INTRODUCED_BY, MEMBER_OF
   Each: {subject, predicate, object, quote, summary, confidence, speaker}
   Examples:
   - "Person A works at Company X" -> WORKS_AT
   - "Person B provides consulting to Company X" -> PROVIDES_SERVICE_TO
   - "Person C owns 40% of Company Y" -> OWNS_EQUITY_IN (include percentage in object)
   - "Company Y pays Person D 1K/month" -> PAYS (include amount in object)
   - "Person E lives in City Z" -> LIVES_IN

2. personal_details: Facts about individuals.
   Types: birthday, family, preference, hobby, location, background
   Each: {person, detail_type, value, quote, summary, speaker}

3. introductions: Who introduced whom to whom.
   Each: {introduced, introduced_by, introduced_to, quote, summary, date_hint}

4. needs_and_interests: What someone is looking for or working on.
   Types: looking_for, interested_in, working_on, struggling_with
   Each: {person, need_type, description, quote, summary}

5. financial_facts: Financial information discussed.
   Each: {person_or_entity, fact_type, value, currency, quote, summary, confidence}
   Types: investment_amount, valuation, equity_stake, revenue, debt, collateral, fund_structure, fee_structure
   CRITICAL: ALWAYS extract exact numbers. "30 milioni" -> value: "30M", currency: "EUR"

6. deal_terms: Deal structures and negotiation positions.
   Each: {parties: [str], term_type, description, value, conditions, quote, summary, confidence}
   Types: offer, counter_offer, condition, deadline, commitment, rejection, acceptance

Rules:
- confidence: high (explicitly stated), medium (strongly implied), low (inferred)
- quote: the EXACT words from the source, copied character by character, IN THE LANGUAGE THEY WERE SPOKEN OR WRITTEN. NEVER translate it. NEVER rephrase, shorten, clean up or fix the grammar: disfluencies, repetitions, false starts and typos stay exactly as they are. First person ("I", "my", "we") is ALLOWED and expected here, because it is what the person actually said. Copy one contiguous passage, do not stitch together pieces taken from different parts of the text. Max {max_context} chars (up to 250 for financial/equity/deal facts). If no single passage in the source supports the fact, set quote to "" — an invented or translated quote is worse than no quote.
- summary: your own restatement of the fact, third person, no first person ("I", "my"), max {max_context} chars. This is a paraphrase and never a proof, and it is the ONLY field where you may translate or rephrase.
- speaker: who said this (if identifiable)
- Skip generic/obvious facts (e.g. "works at Company X" if that's the meeting context)
- Focus on PERSONAL knowledge: family, partners, hobbies, introductions, needs
- Return empty arrays if no facts found
- Respond in the language of the source text
- For FAMILY_OF: Only extract when a SPECIFIC PERSON NAME is mentioned as family member.
  GOOD: "my brother Noah works in Springfield" -> subject="Noah", predicate=FAMILY_OF, object="Speaker"
  BAD: "hey brother, how are you?" -> This is a greeting, NOT a family relationship. Skip it.
  BAD: "my father helped me" -> No name given. Skip generic family references without names.
- For "ex" references: "ex colleague", "ex employee", "former partner" are PROFESSIONAL relationships (WORKS_WITH), not FAMILY_OF.
- Do NOT extract generic role words as person names: "the lawyer", "my mentor", "the accountant" are roles, not names. Only extract if a proper name follows (e.g., "my lawyer Giovanni").
- Brand/company names are NOT people: "Brand X Labs" (if it's a brand/project), "Team Finance" are organizations, not person names.
<<OWNER_RULE>>
- Maximum {max_facts} facts per document. Prioritize high-confidence, specific facts over generic ones.
- ALWAYS use ENGLISH predicate names exactly as listed above (WORKS_AT, PARTNER_OF, etc.). The "quote" field MUST stay in the language of the source — English predicate names do not make English quotes.
- Do NOT extract descriptions or phrases as person names. Names must be actual proper names (first name, last name, or both). Examples of what NOT to extract as names: "the team", "my colleague", "head of growth", "someone from marketing".
- The third-person rule applies to "summary" ONLY. Never rewrite a "quote" into third person, and never translate it: a quote that has been made grammatical, or turned into English, is no longer a quote."""
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("<<OWNER_RULE>>", _OWNER_RULE)

USER_PROMPT_TEMPLATE = """Analyze this {source_type} and extract relationship facts.

Source: {source_label}
Date: {date}
Participants: {participants}

--- TEXT ---
{text}
--- END ---

Return JSON with exactly these 6 keys:
{{"relationship_facts": [...], "personal_details": [...], "introductions": [...], "needs_and_interests": [...], "financial_facts": [...], "deal_terms": [...]}}"""


def build_system_prompt(doc_length: int) -> str:
    ""
    max_facts, max_context = get_fact_limits(doc_length)
    return SYSTEM_PROMPT.replace("{max_facts}", str(max_facts)).replace(
        "{max_context}", str(max_context)
    )





def load_plaud_documents() -> list[dict]:
    ""





    docs = []
    if not PLAUD_DIR.exists():
        log.warning(f"Plaud dir not found: {PLAUD_DIR}")
        return docs
    for f in sorted(PLAUD_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())

            if isinstance(data, list):
                utterances = data
            elif isinstance(data, dict):
                utterances = data.get("utterances", [])
            else:
                continue
            if not utterances:
                continue
            text_parts = []
            speakers = set()
            for u in utterances:
                speaker = u.get("speaker") or "Speaker"
                speakers.add(speaker)
                text_parts.append(f"{speaker}: {u.get('content', '')}")
            text = "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue

            date_str = ""
            fname = f.stem
            if len(fname) >= 10 and fname[4] == "-" and fname[7] == "-":
                date_str = fname[:10]
            elif isinstance(data, dict):
                date_str = data.get("date", "")
                if not date_str:
                    for key in ("created_at", "timestamp", "start_time"):
                        if data.get(key):
                            date_str = str(data[key])[:10]
                            break
            title = fname[11:] if len(fname) > 11 and date_str else fname
            docs.append(
                {
                    "source": "plaud",
                    "source_id": f.stem,
                    "title": title if title else f.stem,
                    "date": date_str,
                    "participants": ", ".join(sorted(speakers)),
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Plaud file {f.name}: {e}")
    return docs


def load_tactiq_documents() -> list[dict]:
    ""





    docs = []
    if not TACTIQ_RAW_DIR.exists():
        log.warning(f"Tactiq dir not found: {TACTIQ_RAW_DIR}")
        return docs
    for f in sorted(TACTIQ_RAW_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, dict):
                continue


            transcript_obj = data.get("transcript", {})
            if isinstance(transcript_obj, dict):
                blocks = transcript_obj.get("blocks", [])
            elif isinstance(transcript_obj, list):
                blocks = transcript_obj
            else:
                blocks = data.get("blocks", [])

            if not blocks or not isinstance(blocks, list):
                continue

            text_parts = []
            speakers = set()
            for b in blocks:
                if not isinstance(b, dict):
                    continue

                speaker = (
                    b.get("speakerName") or b.get("personName") or b.get("speaker") or "Speaker"
                )
                speakers.add(speaker)
                content = b.get("transcript") or b.get("text") or b.get("content") or ""
                if content:
                    text_parts.append(f"{speaker}: {content}")
            text = "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue

            date_str = ""
            ts = data.get("created") or data.get("meetingTimestamp") or data.get("createdTimestamp")
            if ts:
                try:
                    if isinstance(ts, int | float):
                        date_str = datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")
                    else:
                        date_str = str(ts)[:10]
                except (ValueError, OSError):
                    pass
            if not date_str:
                fname = f.stem
                if len(fname) >= 10 and fname[4] == "-" and fname[7] == "-":
                    date_str = fname[:10]
            docs.append(
                {
                    "source": "tactiq",
                    "source_id": f.stem,
                    "title": data.get("title", data.get("meetingTitle", f.stem)),
                    "date": date_str,
                    "participants": ", ".join(sorted(speakers)),
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Tactiq file {f.name}: {e}")
    return docs


def load_whatsapp_documents() -> list[dict]:
    ""
    docs = []
    if not WHATSAPP_CHATS_DIR.exists():
        log.warning(f"WhatsApp chats dir not found: {WHATSAPP_CHATS_DIR}")
        return docs
    for f in sorted(WHATSAPP_CHATS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            messages = data.get("messages", [])
            if not messages:
                continue
            text_parts = []
            for msg in messages:
                sender = msg.get("sender", "Unknown")
                text_content = msg.get("text", "")
                if text_content and len(text_content.strip()) > 1:
                    text_parts.append(f"{sender}: {text_content}")
            text = "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue
            participants = data.get("participants", {})
            if isinstance(participants, dict):
                participant_names = ", ".join(sorted(participants.keys()))
            elif isinstance(participants, list):
                participant_names = ", ".join(sorted(str(p) for p in participants))
            else:
                participant_names = ""
            docs.append(
                {
                    "source": "whatsapp",
                    "source_id": f.stem,
                    "title": data.get("chat_name", f.stem),
                    "date": data.get("date_start", "")[:10] if data.get("date_start") else "",
                    "participants": participant_names,
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load WhatsApp file {f.name}: {e}")
    return docs


def load_slack_documents() -> list[dict]:
    ""
    docs = []
    if not SLACK_CONVERSATIONS_DIR.exists():
        log.warning(f"Slack conversations dir not found: {SLACK_CONVERSATIONS_DIR}")
        return docs

    from slack_esclusi import e_escluso, esclusi

    fuori = esclusi()
    for f in sorted(SLACK_CONVERSATIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if e_escluso(data, fuori):
                continue
            messages = data.get("messages", [])
            if not messages:
                continue
            text_parts = []
            speakers = set()
            for msg in messages:
                user = msg.get("user", "Unknown")
                speakers.add(user)
                text_content = msg.get("text", "")
                if text_content and len(text_content.strip()) > 1:
                    text_parts.append(f"{user}: {text_content}")
            text = "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue

            date_str = ""
            if messages:
                try:
                    first_ts = float(messages[0].get("ts", 0))
                    if first_ts > 0:
                        date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass
            docs.append(
                {
                    "source": "slack",
                    "source_id": data.get("channel_id", f.stem),
                    "title": data.get("channel", f.stem),
                    "date": date_str,
                    "participants": ", ".join(sorted(speakers)),
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Slack file {f.name}: {e}")
    return docs


def load_attio_notes_documents() -> list[dict]:
    ""
    docs = []
    notes_file = ATTIO_DIR / "notes.parquet"
    if not notes_file.exists():
        log.warning(f"Attio notes not found: {notes_file}")
        return docs
    try:
        df = pd.read_parquet(notes_file)
        for _, row in df.iterrows():

            text = str(row.get("content_plaintext", "") or "")
            if len(text.strip()) < 20:
                text = str(row.get("content_markdown", "") or "")
            if len(text.strip()) < 20:
                continue
            date_str = ""
            created = row.get("created_at", "")
            if created:
                date_str = str(created)[:10]
            docs.append(
                {
                    "source": "attio_notes",
                    "source_id": str(row.get("note_id", "")),
                    "title": str(row.get("title", "")),
                    "date": date_str,
                    "participants": str(row.get("parent_object", ""))
                    + ":"
                    + str(row.get("parent_record_id", "")),
                    "text": text,
                    "file": str(notes_file),
                }
            )
    except Exception as e:
        log.warning(f"Failed to load Attio notes: {e}")
    return docs


def load_attio_call_documents() -> list[dict]:
    ""




    docs = []

    for f in attio_transcript_files(ATTIO_TRANSCRIPTS_DIR):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text())
            segments = data.get("segments", [])
            if not segments:
                continue
            text_parts = []
            speakers = set()
            segments_norm = []
            for s in segments:
                if not isinstance(s, dict):
                    continue
                speaker = s.get("speaker") or "Speaker"


                if isinstance(speaker, dict):
                    speaker = (
                        speaker.get("name")
                        or speaker.get("displayName")
                        or speaker.get("id")
                        or "Speaker"
                    )
                speaker = str(speaker)
                speakers.add(speaker)
                text = s.get("text", "")
                if text:
                    text_parts.append(f"{speaker}: {text}")
                    segments_norm.append({**s, "speaker": speaker})













            text = testo_leggibile({**data, "segments": segments_norm}) or "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue
            date_str = ""
            meeting_date = data.get("meeting_date", "")
            if meeting_date:
                date_str = str(meeting_date)[:10]
            docs.append(
                {
                    "source": "attio_call",
                    "source_id": data.get("meeting_id", f.stem),
                    "title": data.get("meeting_title", f.stem),
                    "date": date_str,
                    "participants": ", ".join(sorted(speakers)),
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Attio transcript {f.name}: {e}")
    return docs


def load_slack_dm_documents() -> list[dict]:
    ""
    docs = []
    dm_dir = DATA_ROOT / "slack" / "dm"
    if not dm_dir.exists():
        log.warning(f"Slack DM dir not found: {dm_dir}")
        return docs
    for f in sorted(dm_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            user_name = data.get("user_name", f.stem)
            messages = data.get("messages", [])
            if not messages:
                continue
            text_parts = []
            speakers = set()
            for m in messages:
                user = m.get("user") or "Unknown"
                speakers.add(user)
                text_content = m.get("text", "")
                if text_content and len(text_content.strip()) > 1:
                    text_parts.append(f"{user}: {text_content}")
            text = "\n".join(text_parts)
            if len(text.strip()) < 50:
                continue
            date_str = ""
            if messages:
                try:
                    first_ts = float(messages[0].get("ts", 0))
                    if first_ts > 0:
                        date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass
            docs.append(
                {
                    "source": "slack_dm",
                    "source_id": f"slack_dm_{f.stem}",
                    "title": f"DM with {user_name}",
                    "date": date_str,
                    "participants": ", ".join(sorted(s for s in speakers if s)),
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Slack DM {f.name}: {e}")
    return docs


def load_chatgpt_documents() -> list[dict]:
    ""
    docs = []
    path = CHATGPT_DIR / "conversations-classified.parquet"
    if not path.exists():
        log.warning(f"ChatGPT file not found: {path}")
        return docs
    try:
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            text = str(row.get("full_text", "") or "")
            if len(text.strip()) < 100:
                continue
            title = str(row.get("title", ""))
            conv_id = str(row.get("id") or row.get("conversation_id") or "")
            date_val = row.get("create_time") or row.get("date", "")
            date_str = ""
            if hasattr(date_val, "strftime"):
                date_str = date_val.strftime("%Y-%m-%d")
            elif date_val:
                date_str = str(date_val)[:10]
            docs.append(
                {
                    "source": "chatgpt",
                    "source_id": conv_id or f"chatgpt_{_}",
                    "title": title[:100] if title else "ChatGPT",
                    "date": date_str,
                    "participants": f"{OWNER_LABEL}, ChatGPT",
                    "text": text,
                    "file": str(path),
                }
            )
    except Exception as e:
        log.warning(f"Failed to load ChatGPT conversations: {e}")
    return docs


def load_notion_documents() -> list[dict]:
    ""
    docs = []
    path = NOTION_DIR / "pages-text.parquet"
    if not path.exists():
        log.warning(f"Notion file not found: {path}")
        return docs
    try:
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            text = str(row.get("page_text", "") or "")
            if len(text.strip()) < 100:
                continue
            title = str(row.get("title", ""))
            page_id = str(row.get("page_id") or row.get("id") or "")
            docs.append(
                {
                    "source": "notion",
                    "source_id": page_id or f"notion_{_}",
                    "title": title[:100] if title else "Notion Page",
                    "date": "",
                    "participants": "",
                    "text": text,
                    "file": str(path),
                }
            )
    except Exception as e:
        log.warning(f"Failed to load Notion pages: {e}")
    return docs


def load_gdrive_documents() -> list[dict]:
    ""
    docs = []
    path = GDRIVE_DIR / "documents.parquet"
    if not path.exists():
        log.warning(f"GDrive file not found: {path}")
        return docs
    try:
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            text = str(row.get("content_text", "") or "")
            if len(text.strip()) < 100:
                continue
            name = str(row.get("name", ""))
            file_id = str(row.get("file_id") or row.get("id") or "")
            date_val = row.get("modified") or row.get("modifiedTime", "")
            date_str = ""
            if hasattr(date_val, "strftime"):
                date_str = date_val.strftime("%Y-%m-%d")
            elif date_val:
                date_str = str(date_val)[:10]
            docs.append(
                {
                    "source": "gdrive",
                    "source_id": file_id or f"gdrive_{_}",
                    "title": name[:100] if name else "GDrive Doc",
                    "date": date_str,
                    "participants": "",
                    "text": text,
                    "file": str(path),
                }
            )
    except Exception as e:
        log.warning(f"Failed to load GDrive documents: {e}")
    return docs


def load_email_documents() -> list[dict]:
    ""
    docs = []
    if not EMAILS_DIR.exists():
        log.warning(f"Emails dir not found: {EMAILS_DIR}")
        return docs
    for account_dir in sorted(EMAILS_DIR.iterdir()):
        if not account_dir.is_dir():
            continue
        parquet_file = account_dir / "messages.parquet"
        if not parquet_file.exists():
            continue
        try:
            df = pd.read_parquet(parquet_file)
            for _, row in df.iterrows():
                body = str(row.get("body_text", "") or "")
                if len(body.strip()) < 50:
                    continue
                subject = str(row.get("subject", "") or "")
                sender = str(row.get("from_addr", "") or "")
                recipients = str(row.get("to_addr", "") or "")
                msg_id = str(row.get("message_id", "") or row.get("id", "") or "")
                date_val = row.get("date", "")
                date_str = ""
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                elif date_val:
                    date_str = str(date_val)[:10]

                text_parts = []
                if sender:
                    text_parts.append(f"From: {sender}")
                if recipients:
                    text_parts.append(f"To: {recipients}")
                if subject:
                    text_parts.append(f"Subject: {subject}")
                text_parts.append("")
                text_parts.append(body)
                text = "\n".join(text_parts)
                docs.append(
                    {
                        "source": "email",
                        "source_id": msg_id or f"email_{account_dir.name}_{_}",
                        "title": subject[:100] if subject else f"Email {account_dir.name}",
                        "date": date_str,
                        "participants": f"{sender}, {recipients}" if sender else recipients,
                        "text": text,
                        "file": str(parquet_file),
                    }
                )
        except Exception as e:
            log.warning(f"Failed to load emails from {account_dir.name}: {e}")
    return docs


def load_voice_memo_documents() -> list[dict]:
    ""
    docs = []
    if not VOICE_MEMOS_TRANSCRIPTS_DIR.exists():
        log.warning(f"Voice memos transcripts dir not found: {VOICE_MEMOS_TRANSCRIPTS_DIR}")
        return docs
    for f in sorted(VOICE_MEMOS_TRANSCRIPTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())








            text = ""
            if isinstance(data, dict):
                text = testo_leggibile(data)
                if not text:
                    text = str(data.get("text") or data.get("transcript") or "")
            elif isinstance(data, str):
                text = data
            if len(text.strip()) < 50:
                continue
            date_str = ""
            if isinstance(data, dict):
                date_val = data.get("date", data.get("created_at", ""))
                if date_val:
                    date_str = str(date_val)[:10]
            if not date_str:

                fname = f.stem
                if len(fname) >= 10 and fname[4] == "-" and fname[7] == "-":
                    date_str = fname[:10]
            title = ""
            if isinstance(data, dict):
                title = data.get("filename", "") or data.get("title", "") or ""
            docs.append(
                {
                    "source": "voice_memo",
                    "source_id": f.stem,
                    "title": title or f.stem,
                    "date": date_str,
                    "participants": OWNER_LABEL,
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load voice memo {f.name}: {e}")
    return docs


LOADERS = {
    "plaud": load_plaud_documents,
    "tactiq": load_tactiq_documents,
    "whatsapp": load_whatsapp_documents,
    "slack": load_slack_documents,
    "slack_dm": load_slack_dm_documents,
    "attio_notes": load_attio_notes_documents,
    "attio_call": load_attio_call_documents,
    "chatgpt": load_chatgpt_documents,
    "notion": load_notion_documents,
    "gdrive": load_gdrive_documents,
    "email": load_email_documents,
    "voice_memo": load_voice_memo_documents,
}





# A short list of widely known public figures, used to avoid treating them as
# the user's personal contacts. Extend it or load it from your own config.
FAMOUS_PEOPLE: set[str] = {
    "steve jobs",
    "tim cook",
    "mark zuckerberg",
    "elon musk",
    "jeff bezos",
    "bill gates",
    "sam altman",
    "satya nadella",
    "sundar pichai",
    "larry page",
    "sergey brin",
    "jensen huang",
}

SPEAKER_PATTERN = re.compile(r"^speaker\s*\d*$", re.IGNORECASE)
SLACK_ID_PATTERN = re.compile(r"^U[A-Z0-9]{8,}$")
BOT_ID_PATTERN = re.compile(r"^B[A-Z0-9]{8,}$")


PREDICATE_NORMALIZE: dict[str, str] = {
    "FAMILY": "FAMILY_OF",
    "WORKED_WITH": "WORKS_WITH",
    "FOUNDED": "FOUNDER_OF",

    "INTEREST": "INTERESTED_IN",
    "ROLE": "BACKGROUND",
    "HEALTH_CONDITION": "HEALTH",
    "HEALTH_ISSUE": "HEALTH",
    "HEALTH_CONCERN": "HEALTH",
    "HEALTH_EVENT": "HEALTH",
    "HEALTH_INTEREST": "HEALTH",
    "MEDICAL_CONDITION": "HEALTH",
    "MEDICAL_SYMPTOM": "HEALTH",
    "MEDICAL_STATUS": "HEALTH",
    "MEDICAL_HISTORY": "HEALTH",
    "MEDICATION": "HEALTH",
    "MARRIED_TO": "FAMILY_OF",
    "WORK_STYLE": "PREFERENCE",
    "WORKING_STYLE": "PREFERENCE",
    "WORKING_PATTERN": "PREFERENCE",
    "LOOKING_TO_WORK_WITH": "LOOKING_FOR",

    "EMPLOYED_AT": "WORKS_AT",
    "EMPLOYED_BY": "WORKS_AT",
    "WORKS_FOR": "WORKS_AT",
    "HIRED_BY": "WORKS_AT",
    "MANAGES_TEAM": "MANAGES",
    "LEADS": "MANAGES",
    "SUPERVISES": "MANAGES",
    "FOUNDED_BY": "FOUNDED",
    "CO_FOUNDED": "FOUNDED",
    "COFOUNDED": "FOUNDED",
    "CONSULTS_FOR": "ADVISES",
    "ADVISOR_TO": "ADVISES",
    "CONSULTING_FOR": "ADVISES",
    "PROVIDES_TO": "PROVIDES_SERVICE_TO",
    "SUPPLIER_OF": "PROVIDES_SERVICE_TO",
    "VENDOR_OF": "PROVIDES_SERVICE_TO",
    "INVESTED_IN": "INVESTOR_IN",
    "INVESTS_IN": "INVESTOR_IN",
    "OWNS": "OWNS_EQUITY_IN",
    "SHAREHOLDER_OF": "OWNS_EQUITY_IN",
    "EQUITY_IN": "OWNS_EQUITY_IN",
    "LENT_TO": "LENDS_TO",
    "LOANED_TO": "LENDS_TO",
    "BORROWED_FROM": "BORROWS_FROM",
    "COMPENSATES": "PAYS",
    "PAID": "PAID_BY",
    "RECEIVES_FROM": "PAID_BY",
    "FRIEND": "FRIEND_OF",
    "FRIENDS_WITH": "FRIEND_OF",
    "RESIDES_IN": "LIVES_IN",
    "BASED_IN": "LIVES_IN",
    "LOCATED_IN": "LIVES_IN",
    "KNOWS_FROM": "KNOWS",
    "MET_AT": "KNOWS",
    "RECOMMENDED_BY": "INTRODUCED_BY",
    "REFERRED_BY": "INTRODUCED_BY",
}


def cleanup_facts(df: pd.DataFrame) -> pd.DataFrame:
    ""













    if df.empty:
        return df

    original_len = len(df)
    step_counts: dict[str, int] = {}


    df = df.copy()
    df["subject"] = df["subject"].fillna("").astype(str)
    df["object"] = df["object"].fillna("").astype(str)
    df["predicate"] = df["predicate"].fillna("").astype(str)


    before = len(df)
    df["_subj_norm"] = df["subject"].str.lower().str.strip()
    df["_obj_norm"] = df["object"].str.lower().str.strip()
    df = df.drop_duplicates(subset=["_subj_norm", "predicate", "_obj_norm"], keep="first")
    df = df.drop(columns=["_subj_norm", "_obj_norm"])
    step_counts["exact_duplicates"] = before - len(df)


    before = len(df)
    famous_mask = df["subject"].str.lower().isin(FAMOUS_PEOPLE) | df["object"].str.lower().isin(
        FAMOUS_PEOPLE
    )
    df = df[~famous_mask]
    step_counts["famous_people"] = before - len(df)


    before = len(df)
    df = df[df["subject"].str.lower().str.strip() != df["object"].str.lower().str.strip()]
    step_counts["self_referential"] = before - len(df)


    before = len(df)
    df = df[df["subject"].notna() & df["object"].notna() & df["predicate"].notna()]
    df = df[df["subject"].str.strip() != ""]
    df = df[df["object"].str.strip() != ""]
    df = df[df["subject"].str.lower() != "none"]
    df = df[df["object"].str.lower() != "none"]
    df = df[df["subject"].str.lower() != "unknown"]
    df = df[df["object"].str.lower() != "unknown"]
    step_counts["null_empty"] = before - len(df)


    before = len(df)
    speaker_mask = df["subject"].str.match(SPEAKER_PATTERN, na=False) | df["object"].str.match(
        SPEAKER_PATTERN, na=False
    )
    df = df[~speaker_mask]
    step_counts["speaker_patterns"] = before - len(df)


    before = len(df)
    slack_mask = df["subject"].str.match(SLACK_ID_PATTERN, na=False) | df["object"].str.match(
        SLACK_ID_PATTERN, na=False
    )
    df = df[~slack_mask]
    step_counts["slack_ids"] = before - len(df)


    before = len(df)
    deactivated_mask = df["subject"].str.startswith("deactivateduser", na=False) | df[
        "object"
    ].str.startswith("deactivateduser", na=False)
    df = df[~deactivated_mask]
    step_counts["deactivated_users"] = before - len(df)


    before = len(df)
    bot_mask = df["subject"].str.match(BOT_ID_PATTERN, na=False) | df["object"].str.match(
        BOT_ID_PATTERN, na=False
    )
    df = df[~bot_mask]
    step_counts["bot_ids"] = before - len(df)


    before = len(df)
    short_mask = (df["subject"].str.len() <= 2) | (df["object"].str.len() <= 2)
    df = df[~short_mask]
    step_counts["short_values"] = before - len(df)


    df = df.copy()
    df["predicate"] = df["predicate"].replace(PREDICATE_NORMALIZE)


    before = len(df)
    df = df.drop_duplicates(subset=["subject", "predicate", "object"], keep="first")
    step_counts["post_normalize_dedup"] = before - len(df)


    _GENERIC_RELATIONSHIP_WORDS: set[str] = {
        "father",
        "mother",
        "brother",
        "sister",
        "son",
        "daughter",
        "wife",
        "husband",
        "uncle",
        "aunt",
        "cousin",
        "padre",
        "madre",
        "fratello",
        "sorella",
        "figlio",
        "figlia",
        "moglie",
        "marito",
        "zio",
        "zia",
        "cugino",
        "cugina",
        "nipote",
        "nonno",
        "nonna",
        "compagna",
        "compagno",
        "fidanzata",
        "fidanzato",
        "suocera",
        "suocero",
        "parent",
        "child",
        "sibling",
        "spouse",
        "relative",
        "mentor",
        "lawyer",
        "avvocato",
        "boss",
    }
    before = len(df)
    subj_lower = df["subject"].str.lower().str.strip()
    obj_lower = df["object"].str.lower().str.strip()
    generic_mask = subj_lower.isin(_GENERIC_RELATIONSHIP_WORDS) | obj_lower.isin(
        _GENERIC_RELATIONSHIP_WORDS
    )
    df = df[~generic_mask]
    step_counts["generic_relationship_words"] = before - len(df)


    _EX_PROFESSIONAL_PATTERN = re.compile(
        r"^(?:ex|former|previous)\s+(?:colleague|employee|company|manager|"
        r"socio|soci|collaborator[ei]?|collega)",
        re.IGNORECASE,
    )
    before = len(df)
    ex_mask = df["subject"].str.match(_EX_PROFESSIONAL_PATTERN, na=False) | df["object"].str.match(
        _EX_PROFESSIONAL_PATTERN, na=False
    )
    df = df[~ex_mask]
    step_counts["ex_professional"] = before - len(df)


    _GENERIC_SUBJECTS: set[str] = {
        "team",
        "organization",
        "company",
        "client",
        "user",
        "target",
        "sender",
        "recipient",
        "author",
        "organization/team",
        "team/organization",
        "team/company",
    }
    before = len(df)
    subj_low = df["subject"].str.lower().str.strip()
    obj_low = df["object"].str.lower().str.strip()
    generic_subj_mask = subj_low.isin(_GENERIC_SUBJECTS) | obj_low.isin(_GENERIC_SUBJECTS)
    df = df[~generic_subj_mask]
    step_counts["generic_subjects"] = before - len(df)


    _PRONOUNS: set[str] = {
        "he",
        "she",
        "i",
        "me",
        "him",
        "her",
        "they",
        "them",
        "we",
        "us",
        "his",
        "hers",
        "their",
        "my",
        "your",
        "its",
        "lui",
        "lei",
        "io",
        "noi",
        "loro",
        "il",
        "la",
        "lo",
        "gli",
        "le",
        "the",
        "a",
        "an",
        "un",
        "una",
        "uno",
    }
    before = len(df)
    pron_mask = subj_low.isin(_PRONOUNS) | obj_low.isin(_PRONOUNS)
    df = df[~pron_mask]
    step_counts["pronouns_articles"] = before - len(df)

    total_removed = original_len - len(df)
    log.info(f"Facts cleanup: {original_len} -> {len(df)} ({total_removed} removed)")
    for step, count in step_counts.items():
        if count > 0:
            log.info(f"  {step}: -{count}")

    return df.reset_index(drop=True)





def make_fact_id(source_id: str, subject: str, predicate: str, obj: str) -> str:
    ""
    raw = f"{source_id}|{subject.lower().strip()}|{predicate}|{obj.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _riconoscitore_composti():
    ""








    _dir = str(Path(__file__).resolve().parent)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    try:
        from entity_dedup_index import is_composite
    except ImportError:  # pragma: no cover
        return None
    return is_composite


def soggetti_composti(righe) -> list[str]:
    ""










    fn = _riconoscitore_composti()
    if fn is None:
        return []
    if hasattr(righe, "columns"):
        if "subject" not in righe.columns:
            return []
        valori = righe["subject"].fillna("").astype(str).tolist()
    else:
        valori = [str((r or {}).get("subject") or "") for r in righe]
    return [v for v in valori if v and fn(v)]





def parse_claude_response(response: str) -> dict | None:
    ""
    text = response.strip()
    _EXPECTED_KEYS = {
        "relationship_facts",
        "personal_details",
        "introductions",
        "needs_and_interests",
        "financial_facts",
        "deal_terms",
    }

    if "```" in text:

        parts = text.split("```")

        if len(parts) >= 3:
            inner = parts[1]

            if inner.startswith(("json", "JSON")):
                inner = inner[4:].lstrip()
            text = inner
        elif len(parts) == 2:
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:].lstrip()
            text = inner


    try:
        parsed = json.loads(text)
        if not any(k in parsed for k in _EXPECTED_KEYS):
            return None
        return parsed
    except json.JSONDecodeError:
        pass


    start = text.find("{")
    if start >= 0:

        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                parsed = json.loads(text[start:end])
                if not any(k in parsed for k in _EXPECTED_KEYS):
                    return None
                return parsed
            except json.JSONDecodeError:
                pass


        remainder = text[start:]
        for suffix in ["]}}", "]}", "}", "]}]}}", '"]}}', '"]}']:
            try:
                parsed = json.loads(remainder + suffix)
                if not any(k in parsed for k in _EXPECTED_KEYS):
                    continue
                return parsed
            except json.JSONDecodeError:
                continue

    return None


def extract_facts_from_parsed(
    parsed: dict, doc: dict, data: SBKData | None = None
) -> list[dict]:
    ""
    facts = []
    source = doc["source"]
    source_id = doc["source_id"]
    source_date = doc.get("date", "")
    now_iso = datetime.now(UTC).isoformat()


    for rf in parsed.get("relationship_facts", []):
        subject = str(rf.get("subject") or "").strip()
        predicate = str(rf.get("predicate") or "").strip().upper()
        obj = str(rf.get("object") or "").strip()
        if not subject or not predicate or not obj:
            continue
        fact_id = make_fact_id(source_id, subject, predicate, obj)

        subject_pid = None
        object_pid = None
        if data:
            subject_pid = data.resolve_person_by_name(subject)
            object_pid = data.resolve_person_by_name(obj)
        _quote, _summary, _context = _citazione(rf, 100)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "relationship_fact",
                "subject": subject,
                "subject_person_id": subject_pid or "",
                "predicate": predicate,
                "object": obj,
                "object_person_id": object_pid or "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": str(rf.get("speaker") or ""),
                "confidence": _conf_to_float(rf.get("confidence")),
                "extracted_at": now_iso,
            }
        )


    for pd_item in parsed.get("personal_details", []):
        person = str(pd_item.get("person") or "").strip()
        detail_type = str(pd_item.get("detail_type") or "").strip().lower()
        value = str(pd_item.get("value") or "").strip()
        if not person or not value:
            continue
        fact_id = make_fact_id(source_id, person, detail_type, value)
        person_pid = data.resolve_person_by_name(person) if data else None
        _quote, _summary, _context = _citazione(pd_item, 100)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "personal_detail",
                "subject": person,
                "subject_person_id": person_pid or "",
                "predicate": detail_type.upper(),
                "object": value,
                "object_person_id": "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": str(pd_item.get("speaker") or ""),
                "confidence": _conf_to_float(pd_item.get("confidence")),
                "extracted_at": now_iso,
            }
        )


    for intro in parsed.get("introductions", []):
        introduced = str(intro.get("introduced") or "").strip()
        introduced_by = str(intro.get("introduced_by") or "").strip()
        introduced_to = str(intro.get("introduced_to") or "").strip()
        if not introduced or not introduced_by:
            continue
        fact_id = make_fact_id(source_id, introduced, "INTRODUCED_BY", introduced_by)
        intro_pid = data.resolve_person_by_name(introduced) if data else None
        by_pid = data.resolve_person_by_name(introduced_by) if data else None
        _quote, _summary, _context = _citazione(intro, 100)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "introduction",
                "subject": introduced,
                "subject_person_id": intro_pid or "",
                "predicate": "INTRODUCED_BY",
                "object": introduced_by,
                "object_person_id": by_pid or "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": "",
                "confidence": 0.85,
                "extracted_at": now_iso,
            }
        )

        if introduced_to:
            to_pid = data.resolve_person_by_name(introduced_to) if data else None
            fact_id2 = make_fact_id(source_id, introduced, "INTRODUCED_TO", introduced_to)
            facts.append(
                {
                    "fact_id": fact_id2,
                    "source_type": source,
                    "source_id": source_id,
                    "source_date": source_date,
                    "fact_type": "introduction",
                    "subject": introduced,
                    "subject_person_id": intro_pid or "",
                    "predicate": "INTRODUCED_TO",
                    "object": introduced_to,
                    "object_person_id": to_pid or "",
                    "quote": _quote,
                    "summary": _summary,
                    "context": _context,
                    "speaker": "",
                    "confidence": 0.85,
                    "extracted_at": now_iso,
                }
            )


    for need in parsed.get("needs_and_interests", []):
        person = str(need.get("person") or "").strip()
        need_type = str(need.get("need_type") or "").strip().lower()
        description = str(need.get("description") or "").strip()
        if not person or not description:
            continue
        fact_id = make_fact_id(source_id, person, need_type, description)
        person_pid = data.resolve_person_by_name(person) if data else None
        _quote, _summary, _context = _citazione(need, 100)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "need",
                "subject": person,
                "subject_person_id": person_pid or "",
                "predicate": need_type.upper(),
                "object": description,
                "object_person_id": "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": "",
                "confidence": _conf_to_float(need.get("confidence")),
                "extracted_at": now_iso,
            }
        )


    for ff in parsed.get("financial_facts", []):
        entity = str(ff.get("person_or_entity") or "").strip()
        fact_type = str(ff.get("fact_type") or "").strip().lower()
        value = str(ff.get("value") or "").strip()
        if not entity or not value:
            continue
        currency = str(ff.get("currency") or "").strip()
        obj_str = f"{value} {currency}".strip() if currency else value
        fact_id = make_fact_id(source_id, entity, fact_type, obj_str)
        entity_pid = data.resolve_person_by_name(entity) if data else None
        _quote, _summary, _context = _citazione(ff, 250)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "financial_fact",
                "subject": entity,
                "subject_person_id": entity_pid or "",
                "predicate": fact_type.upper(),
                "object": obj_str,
                "object_person_id": "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": "",
                "confidence": _conf_to_float(ff.get("confidence")),
                "extracted_at": now_iso,
            }
        )


    for dt in parsed.get("deal_terms", []):
















        parties = dt.get("parties", [])
        if isinstance(parties, list):
            parties = [p for p in (str(x).strip() for x in parties) if p]
            subject = parties[0] if parties else ""
            counterparty = ", ".join(parties[1:])
        else:
            subject = str(parties or "").strip()
            counterparty = ""
        parties_key = ", ".join(parties) if isinstance(parties, list) else subject
        term_type = str(dt.get("term_type") or "").strip().lower()
        description = str(dt.get("description") or "").strip()
        if not subject or not description:
            continue
        value = str(dt.get("value") or "").strip()
        conditions = str(dt.get("conditions") or "").strip()
        obj_str = description
        if value:
            obj_str = f"{description} [{value}]"
        if conditions:
            obj_str = f"{obj_str} (if: {conditions})"









        fact_id = make_fact_id(source_id, parties_key, term_type, obj_str)
        party_pid = data.resolve_person_by_name(subject) if data else None
        _quote, _summary, _context = _citazione(dt, 250)
        facts.append(
            {
                "fact_id": fact_id,
                "source_type": source,
                "source_id": source_id,
                "source_date": source_date,
                "fact_type": "deal_term",
                "subject": subject,
                "subject_person_id": party_pid or "",
                "counterparty": counterparty,
                "predicate": term_type.upper(),
                "object": obj_str[:500],
                "object_person_id": "",
                "quote": _quote,
                "summary": _summary,
                "context": _context,
                "speaker": "",
                "confidence": _conf_to_float(dt.get("confidence")),
                "extracted_at": now_iso,
            }
        )

    return facts





def estimate_cost(docs: list[dict], provider: str = "anthropic", model: str | None = None) -> dict:
    ""


    from xs_l3_common import PRICING, PROVIDER_CONFIG, PROVIDER_PRICING

    total_chars = sum(len(d["text"][:MAX_TEXT_LENGTH]) for d in docs)

    est_input_tokens = total_chars // 4 + len(docs) * 500
    est_output_tokens = len(docs) * 800

    config = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["anthropic"])
    model = model or config["default_model"]
    pricing = PRICING.get(model, PROVIDER_PRICING.get(provider, {"input": 0.80, "output": 4.0}))
    cost = (est_input_tokens * pricing["input"] + est_output_tokens * pricing["output"]) / 1_000_000
    return {
        "documents": len(docs),
        "total_chars": total_chars,
        "est_input_tokens": est_input_tokens,
        "est_output_tokens": est_output_tokens,
        "est_cost_usd": round(cost, 2),
    }


def _process_single_document(doc: dict) -> dict:
    ""
    source = doc["source"]
    source_id = doc["source_id"]


    cache_dir = RELATIONSHIP_RESPONSES_DIR / source
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{source_id}.json"

    if cache_file.exists():
        try:
            parsed = json.loads(cache_file.read_text())
            return {"doc": doc, "parsed": parsed, "cached": True, "error": None}
        except (json.JSONDecodeError, OSError):
            pass

    from xs_l3_chunking import chunk_document_semantic, merge_relationship_results

    text = doc["text"]
    chunks = chunk_document_semantic(text, max_chars=MAX_TEXT_LENGTH, overlap_chars=2000)

    if len(chunks) > 1:

        chunk_results = []
        for chunk in chunks:
            chunk_cache_file = cache_dir / f"{source_id}_chunk_{chunk.chunk_idx}.json"
            if chunk_cache_file.exists():
                try:
                    parsed = json.loads(chunk_cache_file.read_text())
                    chunk_results.append(parsed)
                    continue
                except (json.JSONDecodeError, OSError):
                    pass

            chunk_prompt = USER_PROMPT_TEMPLATE.format(
                source_type=source.replace("_", " ").title(),
                source_label=doc.get("title", source_id),
                date=doc.get("date", "unknown"),
                participants=doc.get("participants", "unknown"),
                text=chunk.text,
            )
            doc_provider = doc.get("_provider", _PROVIDER)
            try:
                response = call_claude(
                    prompt=chunk_prompt,
                    system=build_system_prompt(len(chunk.text)),
                    model=HAIKU_MODEL,
                    max_tokens=8192,
                    temperature=0.1,
                    provider=doc_provider,
                )
                parsed = parse_claude_response(response)
                if parsed:
                    chunk_cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
                    chunk_results.append(parsed)
            except Exception as e:
                log.warning(f"Chunk {chunk.chunk_idx} failed for {source}/{source_id}: {e}")

        if chunk_results:
            merged = merge_relationship_results(chunk_results)

            cache_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
            return {"doc": doc, "parsed": merged, "cached": False, "error": None}
        else:
            return {"doc": doc, "parsed": None, "cached": False, "error": "All chunks failed"}


    chunk_text = chunks[0].text


    prompt = USER_PROMPT_TEMPLATE.format(
        source_type=source.replace("_", " ").title(),
        source_label=doc.get("title", source_id),
        date=doc.get("date", "unknown"),
        participants=doc.get("participants", "unknown"),
        text=chunk_text,
    )

    doc_provider = doc.get("_provider", _PROVIDER)
    try:
        for _attempt in range(2):
            response = call_claude(
                prompt=prompt,
                system=build_system_prompt(len(chunk_text)),
                model=HAIKU_MODEL,
                max_tokens=8192,
                temperature=0.1 if _attempt == 0 else 0.0,
                provider=doc_provider,
            )
            parsed = parse_claude_response(response)
            if parsed is not None:
                break
        if parsed is None:
            return {
                "doc": doc,
                "parsed": None,
                "cached": False,
                "error": "Failed to parse response after 2 attempts",
            }


        cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
        return {"doc": doc, "parsed": parsed, "cached": False, "error": None}

    except Exception as e:
        return {"doc": doc, "parsed": None, "cached": False, "error": str(e)}





_BATCH_SYSTEM_PROMPT_TEMPLATE = """You are a relationship intelligence analyst extracting facts from conversations.

CRITICAL: You are processing {n} documents. Return ONLY a raw JSON ARRAY of {n} objects. No markdown, no code blocks, no explanation, no text before or after the JSON. Start your response with [ and end with ].

Each object in the array corresponds to one document (in the same order as provided) and must have exactly these 6 keys:
{{"relationship_facts": [...], "personal_details": [...], "introductions": [...], "needs_and_interests": [...], "financial_facts": [...], "deal_terms": [...]}}

Extract these 6 types of facts per document:

1. relationship_facts: Personal/professional connections between people.
   Professional predicates: WORKS_AT, WORKS_WITH, REPORTS_TO, MANAGES, FOUNDED, ADVISES, PARTNER_OF, CLIENT_OF, PROVIDES_SERVICE_TO
   Financial predicates: INVESTOR_IN, OWNS_EQUITY_IN, LENDS_TO, BORROWS_FROM, PAYS, PAID_BY
   Personal predicates: FAMILY_OF, FRIEND_OF, LIVES_IN
   Connection predicates: KNOWS, INTRODUCED_BY, MEMBER_OF
   Each: {{subject, predicate, object, quote, summary, confidence, speaker}}

2. personal_details: Facts about individuals.
   Types: birthday, family, preference, hobby, location, background
   Each: {{person, detail_type, value, quote, summary, speaker}}

3. introductions: Who introduced whom to whom.
   Each: {{introduced, introduced_by, introduced_to, quote, summary, date_hint}}

4. needs_and_interests: What someone is looking for or working on.
   Types: looking_for, interested_in, working_on, struggling_with
   Each: {{person, need_type, description, quote, summary}}

5. financial_facts: Financial information discussed.
   Each: {{person_or_entity, fact_type, value, currency, quote, summary, confidence}}
   Types: investment_amount, valuation, equity_stake, revenue, debt, collateral, fund_structure, fee_structure
   CRITICAL: ALWAYS extract exact numbers. "30 milioni" -> value: "30M", currency: "EUR"

6. deal_terms: Deal structures and negotiation positions.
   Each: {{parties: [str], term_type, description, value, conditions, quote, summary, confidence}}
   Types: offer, counter_offer, condition, deadline, commitment, rejection, acceptance

Rules:
- confidence: high (explicitly stated), medium (strongly implied), low (inferred)
- quote: the EXACT words from the source, copied character by character, IN THE LANGUAGE THEY WERE SPOKEN OR WRITTEN. NEVER translate it. NEVER rephrase, shorten, clean up or fix the grammar: disfluencies, repetitions, false starts and typos stay exactly as they are. First person ("I", "my", "we") is ALLOWED and expected here, because it is what the person actually said. Copy one contiguous passage, do not stitch together pieces taken from different parts of the text. Max 200 chars (up to 250 for financial/equity/deal facts). If no single passage in the source supports the fact, set quote to "" — an invented or translated quote is worse than no quote.
- summary: your own restatement of the fact, third person, no first person ("I", "my"), max 200 chars. This is a paraphrase and never a proof, and it is the ONLY field where you may translate or rephrase.
- speaker: who said this (if identifiable)
- Skip generic/obvious facts (e.g. "works at Company X" if that's the meeting context)
- Focus on PERSONAL knowledge: family, partners, hobbies, introductions, needs
- Return empty arrays if no facts found for a document
- Respond in the language of the source text
- For FAMILY_OF: Only extract when a SPECIFIC PERSON NAME is mentioned as family member.
  GOOD: "my brother Noah works in Springfield" -> subject="Noah", predicate=FAMILY_OF, object="Speaker"
  BAD: "hey brother, how are you?" -> This is a greeting, NOT a family relationship. Skip it.
  BAD: "my father helped me" -> No name given. Skip generic family references without names.
- For "ex" references: "ex colleague", "ex employee", "former partner" are PROFESSIONAL relationships (WORKS_WITH), not FAMILY_OF.
- Do NOT extract generic role words as person names: "the lawyer", "my mentor", "the accountant" are roles, not names. Only extract if a proper name follows (e.g., "my lawyer Giovanni").
- Brand/company names are NOT people: "Brand X Labs" (if it's a brand/project), "Team Finance" are organizations, not person names.
<<OWNER_RULE>>
- Maximum {max_facts} facts per document. Prioritize high-confidence, specific facts over generic ones.
- ALWAYS use ENGLISH predicate names exactly as listed above (WORKS_AT, PARTNER_OF, etc.). The "quote" field MUST stay in the language of the source — English predicate names do not make English quotes.
- Do NOT extract descriptions or phrases as person names. Names must be actual proper names (first name, last name, or both). Examples of what NOT to extract as names: "the team", "my colleague", "head of growth", "someone from marketing".
- The third-person rule applies to "summary" ONLY. Never rewrite a "quote" into third person, and never translate it: a quote that has been made grammatical, or turned into English, is no longer a quote."""
_BATCH_SYSTEM_PROMPT_TEMPLATE = _BATCH_SYSTEM_PROMPT_TEMPLATE.replace(
    "<<OWNER_RULE>>", _OWNER_RULE.replace("{", "{{").replace("}", "}}")
)


def _process_document_batch(docs: list[dict]) -> list[dict]:
    ""





    results = []
    uncached_docs = []
    uncached_indices = []


    for i, doc in enumerate(docs):
        source = doc["source"]
        source_id = doc["source_id"]
        cache_dir = RELATIONSHIP_RESPONSES_DIR / source
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{source_id}.json"

        if cache_file.exists():
            try:
                parsed = json.loads(cache_file.read_text())
                results.append({"doc": doc, "parsed": parsed, "cached": True, "error": None})
                continue
            except (json.JSONDecodeError, OSError):
                pass

        uncached_docs.append(doc)
        uncached_indices.append(i)

        results.append(None)


    if not uncached_docs:
        return results


    doc_sections = []
    for idx, doc in enumerate(uncached_docs):
        text = doc["text"][:MAX_TEXT_LENGTH]
        doc_sections.append(
            f"--- DOCUMENT {idx + 1} ---\n"
            f"Source: {doc.get('title', doc['source_id'])}\n"
            f"Date: {doc.get('date', 'unknown')}\n"
            f"Participants: {doc.get('participants', 'unknown')}\n\n"
            f"{text}\n"
            f"--- END DOCUMENT {idx + 1} ---"
        )

    n = len(uncached_docs)
    combined_prompt = (
        f"Analyze these {n} documents and extract relationship facts from each one.\n\n"
        + "\n\n".join(doc_sections)
        + f"\n\nReturn a JSON ARRAY of {n} objects, one per document in order. "
        f"Each object has exactly these 6 keys: "
        f'{{"relationship_facts": [...], "personal_details": [...], "introductions": [...], '
        f'"needs_and_interests": [...], "financial_facts": [...], "deal_terms": [...]}}'
    )

    max_facts = max(get_fact_limits(len(d["text"]))[0] for d in uncached_docs)
    batch_system = _BATCH_SYSTEM_PROMPT_TEMPLATE.format(n=n, max_facts=max_facts)


    batch_provider = uncached_docs[0].get("_provider", _PROVIDER) if uncached_docs else _PROVIDER
    try:
        response = call_claude(
            prompt=combined_prompt,
            system=batch_system,
            model=HAIKU_MODEL,
            max_tokens=4096 * n,
            temperature=0.1,
            provider=batch_provider,
        )


        parsed_array = _parse_batch_response(response, n)

        if parsed_array is None:

            for pos, orig_idx in enumerate(uncached_indices):
                doc = uncached_docs[pos]
                results[orig_idx] = {
                    "doc": doc,
                    "parsed": None,
                    "cached": False,
                    "error": "Batch response parse failed",
                }
            return results


        for pos, orig_idx in enumerate(uncached_indices):
            doc = uncached_docs[pos]
            parsed = parsed_array[pos] if pos < len(parsed_array) else None

            if parsed is not None:
                cache_dir = RELATIONSHIP_RESPONSES_DIR / doc["source"]
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = cache_dir / f"{doc['source_id']}.json"
                cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))

            results[orig_idx] = {
                "doc": doc,
                "parsed": parsed,
                "cached": False,
                "error": None if parsed is not None else "Missing from batch response",
            }

    except Exception as e:

        for pos, orig_idx in enumerate(uncached_indices):
            doc = uncached_docs[pos]
            results[orig_idx] = {
                "doc": doc,
                "parsed": None,
                "cached": False,
                "error": f"Batch API error: {e}",
            }

    return results


def _parse_batch_response(response: str, expected_n: int) -> list[dict] | None:
    ""
    text = response.strip()

    _EXPECTED_KEYS = {
        "relationship_facts",
        "personal_details",
        "introductions",
        "needs_and_interests",
        "financial_facts",
        "deal_terms",
    }


    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:].lstrip()
            text = inner


    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == expected_n:
            if all(
                isinstance(item, dict) and any(k in item for k in _EXPECTED_KEYS) for item in parsed
            ):
                return parsed
    except json.JSONDecodeError:
        pass


    start = text.find("[")
    if start >= 0:
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, list) and len(parsed) == expected_n:
                    if all(
                        isinstance(item, dict) and any(k in item for k in _EXPECTED_KEYS)
                        for item in parsed
                    ):
                        return parsed
            except json.JSONDecodeError:
                pass



    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end])
            if isinstance(parsed, list) and len(parsed) == expected_n:
                return parsed
        except json.JSONDecodeError:
            pass

    log.warning(f"Batch response parse failed: expected array of {expected_n} objects")
    return None


def _collect_batch_results(
    batch_results: list[dict],
    data: SBKData | None,
    counters: dict,
    all_facts: list[dict],
    total_docs: int,
    start_time: float,
) -> list[dict]:
    ""



    failed_docs = []
    for result in batch_results:
        counters["processed"] += 1
        if result["cached"]:
            counters["cached"] += 1
        if result["error"]:
            counters["errors"] += 1
            doc = result["doc"]
            log.warning(f"Error on {doc['source']}/{doc['source_id']}: {result['error']}")
            failed_docs.append(doc)
        elif result["parsed"]:
            facts = extract_facts_from_parsed(result["parsed"], result["doc"], data)
            all_facts.extend(facts)
        if counters["processed"] % 50 == 0:
            elapsed = time.time() - start_time
            log.info(
                f"Progress: {counters['processed']}/{total_docs} docs, "
                f"{len(all_facts)} facts, {counters['cached']} cached, "
                f"{counters['errors']} errors ({elapsed:.0f}s)"
            )
    return failed_docs


def run_batch(
    docs: list[dict],
    data: SBKData | None = None,
    workers: int = 1,
    verbose: bool = False,
    batch_size: int = 1,
) -> list[dict]:
    ""








    all_facts: list[dict] = []
    counters = {"processed": 0, "cached": 0, "errors": 0}
    start_time = time.time()

    if batch_size <= 1:

        if workers <= 1:
            for doc in docs:
                result = _process_single_document(doc)
                _collect_batch_results([result], data, counters, all_facts, len(docs), start_time)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_process_single_document, doc): doc for doc in docs}
                for future in as_completed(futures):
                    result = future.result()
                    _collect_batch_results(
                        [result], data, counters, all_facts, len(docs), start_time
                    )
    else:


        batches = [docs[i : i + batch_size] for i in range(0, len(docs), batch_size)]
        log.info(
            f"Multi-doc batching: {len(docs)} docs in {len(batches)} batches "
            f"(batch_size={batch_size}, workers={workers})"
        )

        failed_docs: list[dict] = []

        if workers <= 1:
            for batch in batches:
                batch_results = _process_document_batch(batch)
                batch_failed = _collect_batch_results(
                    batch_results, data, counters, all_facts, len(docs), start_time
                )
                failed_docs.extend(batch_failed)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_document_batch, batch): batch for batch in batches
                }
                for future in as_completed(futures):
                    batch_results = future.result()
                    batch_failed = _collect_batch_results(
                        batch_results, data, counters, all_facts, len(docs), start_time
                    )
                    failed_docs.extend(batch_failed)


        if failed_docs:
            log.info(f"Retrying {len(failed_docs)} failed docs from batch mode individually...")
            retry_counters = {"processed": 0, "cached": 0, "errors": 0}
            if workers <= 1:
                for doc in failed_docs:
                    result = _process_single_document(doc)
                    counters["processed"] += 1
                    retry_counters["processed"] += 1
                    if result["cached"]:
                        counters["cached"] += 1
                    if result["error"]:
                        counters["errors"] += 1
                        log.warning(
                            f"Retry failed: {doc['source']}/{doc['source_id']}: {result['error']}"
                        )
                    elif result["parsed"]:

                        counters["errors"] -= 1
                        facts = extract_facts_from_parsed(result["parsed"], doc, data)
                        all_facts.extend(facts)
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(_process_single_document, doc): doc for doc in failed_docs
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        counters["processed"] += 1
                        retry_counters["processed"] += 1
                        if result["cached"]:
                            counters["cached"] += 1
                        if result["error"]:
                            counters["errors"] += 1
                            doc = result["doc"]
                            log.warning(
                                f"Retry failed: {doc['source']}/{doc['source_id']}: "
                                f"{result['error']}"
                            )
                        elif result["parsed"]:
                            counters["errors"] -= 1
                            facts = extract_facts_from_parsed(result["parsed"], result["doc"], data)
                            all_facts.extend(facts)
            log.info(
                f"Retry done: {retry_counters['processed']} docs, "
                f"{retry_counters['processed'] - (counters['errors'] - (len(failed_docs) - retry_counters['processed']))} recovered"
            )

    elapsed = time.time() - start_time
    log.info(
        f"DONE: {counters['processed']} docs processed, {len(all_facts)} facts extracted, "
        f"{counters['cached']} from cache, {counters['errors']} errors ({elapsed:.0f}s)"
    )
    return all_facts





def save_facts(facts: list[dict]) -> Path:
    ""



    if not facts:
        log.warning("No facts to save")
        return RELATIONSHIP_FACTS_FILE

    new_df = pd.DataFrame(facts)


    new_df = new_df.drop_duplicates(subset=["fact_id"], keep="last")


    if RELATIONSHIP_FACTS_FILE.exists():
        existing = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["fact_id"], keep="last")
    else:
        combined = new_df


    combined = cleanup_facts(combined)





    for _nuova in ("quote", "summary"):
        if _nuova in combined.columns:
            combined[_nuova] = combined[_nuova].fillna("").astype(str)
        else:
            combined[_nuova] = ""





    _anchor_cols = {"fact_id", "source_date"}
    _missing = _anchor_cols - set(combined.columns)
    if _missing:
        raise RuntimeError(
            f"GATE 0b: refusing to write relationship-facts.parquet without {sorted(_missing)} "
            f"(columns: {list(combined.columns)}). The healthy path emits both — "
            f"this indicates a regression in the extraction flow."
        )







    for col in combined.columns:
        if combined[col].dtype == object:
            combined[col] = combined[col].fillna("").astype(str)




    _sporchi = soggetti_composti(combined)
    if _sporchi:
        log.warning(
            "I-M1: %d rows out of %d have a composite `subject` (examples: %s). "
            "If they are deal_term it is a join regression: the subject is parties[0].",
            len(_sporchi),
            len(combined),
            "; ".join(_sporchi[:3]),
        )


    RELATIONSHIP_FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(combined, RELATIONSHIP_FACTS_FILE, index=False)
    log.info(f"Saved {len(combined)} facts to {RELATIONSHIP_FACTS_FILE}")
    _dichiara_schema(combined)


    for ft, count in combined["fact_type"].value_counts().items():
        log.info(f"  {ft}: {count}")

    return RELATIONSHIP_FACTS_FILE





def _richieste_batch(uncached_docs: list[dict], model: str):
    ""

    from xs_batch_api import BatchRequest, id_stabile
    from xs_l3_chunking import chunk_document_semantic

    seen_ids: set[str] = set()

    for doc in uncached_docs:
        source = doc["source"]
        source_id = doc["source_id"]
        text = doc["text"]
        chunks = chunk_document_semantic(text, max_chars=MAX_TEXT_LENGTH, overlap_chars=2000)

        for chunk in chunks:

            if len(chunks) > 1:
                chunk_cache = (
                    RELATIONSHIP_RESPONSES_DIR
                    / source
                    / f"{source_id}_chunk_{chunk.chunk_idx}.json"
                )
                if chunk_cache.exists():
                    continue




            custom_id = id_stabile(source, source_id, chunk.chunk_idx)
            doppio = 1
            while custom_id in seen_ids:
                custom_id = id_stabile(source, f"{source_id}#{doppio}", chunk.chunk_idx)
                doppio += 1
            seen_ids.add(custom_id)
            prompt = USER_PROMPT_TEMPLATE.format(
                source_type=source.replace("_", " ").title(),
                source_label=doc.get("title", source_id),
                date=doc.get("date", "unknown"),
                participants=doc.get("participants", "unknown"),
                text=chunk.text,
            )
            yield (
                BatchRequest(
                    custom_id=custom_id,
                    user_content=prompt,
                    system_prompt=build_system_prompt(len(chunk.text)),
                    model=model,
                    max_tokens=8192,
                    temperature=0.1,
                ),
                doc,
                chunk.chunk_idx,
                len(chunks),
            )


def run_batch_api(
    docs: list[dict],
    data: SBKData | None = None,
    model: str = "claude-sonnet-4-5-20250929",
) -> list[dict]:
    ""




    from xs_batch_api import chiudi_stato, run_batch_pipeline
    from xs_l3_chunking import merge_relationship_results


    uncached_docs = []
    cached_facts = []
    for doc in docs:
        cache_file = RELATIONSHIP_RESPONSES_DIR / doc["source"] / f"{doc['source_id']}.json"
        if cache_file.exists():
            try:
                parsed = json.loads(cache_file.read_text())
                facts = extract_facts_from_parsed(parsed, doc, data)
                cached_facts.extend(facts)
                continue
            except (json.JSONDecodeError, OSError):
                pass
        uncached_docs.append(doc)

    log.info(
        f"Batch API: {len(docs)} total, {len(docs) - len(uncached_docs)} cached, {len(uncached_docs)} to process"
    )

    if not uncached_docs:
        log.info("All documents cached — nothing to submit")
        return cached_facts


    batch_requests = []

    request_map: dict[str, tuple[dict, int, int]] = {}
    for richiesta, doc, chunk_idx, n_chunks in _richieste_batch(uncached_docs, model):
        batch_requests.append(richiesta)
        request_map[richiesta.custom_id] = (doc, chunk_idx, n_chunks)

    log.info(
        f"Built {len(batch_requests)} batch requests ({len(uncached_docs)} docs, multi-chunk included)"
    )

    if not batch_requests:
        log.info("All chunks cached — nothing to submit")
        return cached_facts


    results = run_batch_pipeline(
        batch_requests,
        label="extract-rel",
        poll_interval=30,
        state_dir=RELATIONSHIP_RESPONSES_DIR,
        tieni_stato=True,
    )



    doc_chunks: dict[tuple[str, str], dict[int, dict]] = {}
    for custom_id, result in results.items():
        if custom_id not in request_map:
            continue
        doc, chunk_idx, total_chunks = request_map[custom_id]
        key = (doc["source"], doc["source_id"])
        if key not in doc_chunks:
            doc_chunks[key] = {}
        doc_chunks[key][chunk_idx] = result

    all_facts = list(cached_facts)
    processed = 0
    errors = 0

    for (source, source_id), chunk_results_map in doc_chunks.items():

        doc = next(
            (d for d in uncached_docs if d["source"] == source and d["source_id"] == source_id),
            None,
        )
        if not doc:
            continue

        cache_dir = RELATIONSHIP_RESPONSES_DIR / source
        cache_dir.mkdir(parents=True, exist_ok=True)


        parsed_chunks = []
        for chunk_idx in sorted(chunk_results_map.keys()):
            result = chunk_results_map[chunk_idx]
            if result.get("error"):
                log.warning(f"Error on {source}/{source_id} chunk {chunk_idx}: {result['error']}")
                errors += 1
                continue

            text = result.get("text", "")
            parsed = parse_claude_response(text)
            if parsed:

                chunk_cache = cache_dir / f"{source_id}_chunk_{chunk_idx}.json"
                chunk_cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
                parsed_chunks.append(parsed)

        if not parsed_chunks:
            errors += 1
            continue


        if len(parsed_chunks) > 1:
            merged = merge_relationship_results(parsed_chunks)
        else:
            merged = parsed_chunks[0]


        main_cache = cache_dir / f"{source_id}.json"
        main_cache.write_text(json.dumps(merged, ensure_ascii=False, indent=2))


        facts = extract_facts_from_parsed(merged, doc, data)
        all_facts.extend(facts)
        processed += 1

        if processed % 500 == 0:
            log.info(f"Post-processing: {processed}/{len(doc_chunks)} docs, {len(all_facts)} facts")


    chiudi_stato("extract-rel", RELATIONSHIP_RESPONSES_DIR)
    log.info(
        f"Batch API complete: {processed} docs processed, {errors} errors, "
        f"{len(all_facts)} total facts (including {len(cached_facts)} from cache)"
    )
    return all_facts





def main():
    parser = argparse.ArgumentParser(description="SBK Relationship Fact Extraction")
    parser.add_argument("--dry-run", action="store_true", help="Count documents only, no API calls")
    parser.add_argument(
        "--source",
        choices=SOURCES,
        help="Process single source only",
    )
    parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        metavar="SRC",
        help="Exclude one source from the run (repeatable). Lowers cost for gate (c)",
    )
    parser.add_argument(
        "--batch", action="store_true", help="Run sync batch extraction (ThreadPool)"
    )
    parser.add_argument(
        "--batch-api",
        action="store_true",
        help="Use Anthropic Message Batches API (50%% discount, Sonnet quality)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model override (default: Haiku for --batch, Sonnet for --batch-api)",
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel workers for --batch mode (default=1)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Documents per API call (default=1, use 10 for Gemini multi-doc batching)",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Run cleanup on existing relationship-facts.parquet without re-extracting",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument(
        "--no-email-filter",
        action="store_true",
        help="Disable email pre-filter (send all emails to LLM)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--smart-route",
        action="store_true",
        help="Route docs to quality/economy providers based on sensitivity",
    )
    parser.add_argument(
        "--quality-provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="anthropic",
        help="Quality provider for smart routing (default: anthropic)",
    )
    parser.add_argument(
        "--economy-provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="deepseek",
        help="Economy provider for smart routing (default: deepseek)",
    )
    args = parser.parse_args()
    # Take the lock only after the arguments are parsed, so --help writes nothing.
    _acquire_lock()


    global _PROVIDER
    _PROVIDER = args.provider

    setup_logging(verbose=args.verbose, name="sbk-rel-extract")

    if args.incremental:
        from sbk_config import check_inputs_changed, mark_last_run

        _rel_inputs = [
            PLAUD_DIR,
            TACTIQ_RAW_DIR,
            WHATSAPP_CHATS_DIR,
            SLACK_CONVERSATIONS_DIR,
            ATTIO_DIR / "notes",
            *ATTIO_TRANSCRIPTS_DIRS,
            CHATGPT_DIR,
            NOTION_DIR,
            GDRIVE_DIR,



            EMAILS_DIR,
            DATA_ROOT / "slack" / "dm",
            DATA_ROOT / "voice-memos" / "transcripts",
        ]
        if not check_inputs_changed("l3-extract-rel", _rel_inputs):
            log.info("Incremental: inputs unchanged — skipping")
            if args.dry_run:

                print("\nInputs unchanged since the last real run: the stage would be skipped.")
                print("  New to process:  0")
                print("  Est. batch cost: $0.00 (inputs unchanged, nothing to send)")
                return
            mark_last_run("l3-extract-rel")
            return


    if args.cleanup_only:
        if not RELATIONSHIP_FACTS_FILE.exists():
            log.error(f"No existing facts file: {RELATIONSHIP_FACTS_FILE}")
            sys.exit(1)
        df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
        log.info(f"Loaded {len(df)} existing facts from {RELATIONSHIP_FACTS_FILE}")
        df = cleanup_facts(df)
        safe_write_parquet(df, RELATIONSHIP_FACTS_FILE, index=False)
        log.info(f"Saved {len(df)} cleaned facts to {RELATIONSHIP_FACTS_FILE}")
        _dichiara_schema(df)
        for ft, count in df["fact_type"].value_counts().items():
            log.info(f"  {ft}: {count}")
        return


    sources_to_process = [args.source] if args.source else SOURCES
    _excl = set(args.exclude_source or [])
    if _excl:
        sources_to_process = [x for x in sources_to_process if x not in _excl]
        log.info(f"Sources EXCLUDED from the run: {sorted(_excl)} -> {len(sources_to_process)} remaining")
    all_docs = []
    for source in sources_to_process:
        loader = LOADERS[source]
        docs = loader()
        log.info(f"  {source}: {len(docs)} documents")
        all_docs.extend(docs)

    log.info(f"Total: {len(all_docs)} documents from {len(sources_to_process)} sources")


    if not args.no_email_filter and any(d.get("source") == "email" for d in all_docs):
        email_docs = [d for d in all_docs if d.get("source") == "email"]
        other_docs = [d for d in all_docs if d.get("source") != "email"]
        kept_emails, filter_stats = email_prefilter(email_docs)
        log.info(
            f"Email pre-filter: {filter_stats['total']} -> {filter_stats['kept']} "
            f"({filter_stats['removal_pct']}% removed)"
        )
        all_docs = other_docs + kept_emails


    if args.smart_route:
        router = SmartRouter(
            quality_provider=args.quality_provider,
            economy_provider=args.economy_provider,
        )
        for doc in all_docs:
            doc["_provider"] = router.route(doc)
        router.log_stats()

    if args.dry_run:

        senza_risposta = [
            doc
            for doc in all_docs
            if not (
                RELATIONSHIP_RESPONSES_DIR / doc["source"] / f"{doc['source_id']}.json"
            ).exists()
        ]
        cached_count = len(all_docs) - len(senza_risposta)
        new_count = len(senza_risposta)
        dry_model = (args.model or "claude-sonnet-4-5-20250929") if args.batch_api else None
        if args.batch_api:



            from xs_batch_api import stima_costo_richieste, uscita_media


            media = uscita_media(RELATIONSHIP_RESPONSES_DIR)
            st = stima_costo_richieste(
                (r for r, _d, _i, _n in _richieste_batch(senza_risposta, dry_model)),
                uscita_token=media,
            )
            print(
                f"  Output per request: ~{media or 'max_tokens/4'} tokens"
                + (" (from the answers already saved)" if media else "")
            )
            est = {
                "est_cost_usd": st["est_cost_usd_sync"],
                "est_cost_usd_batch": st["est_cost_usd_batch"],
                "richieste": st["richieste"],
            }
        else:
            est = estimate_cost(senza_risposta, provider=args.provider, model=dry_model)
        print(f"\n{'=' * 60}")
        print("DRY RUN SUMMARY")
        print(f"{'=' * 60}")
        for source in sources_to_process:
            count = sum(1 for d in all_docs if d["source"] == source)
            source_cached = sum(
                1
                for d in all_docs
                if d["source"] == source
                and (RELATIONSHIP_RESPONSES_DIR / source / f"{d['source_id']}.json").exists()
            )
            print(
                f"  {source:15s}: {count:5d} total, {source_cached:5d} cached, {count - source_cached:5d} new"
            )
        print(f"{'=' * 60}")
        print(f"  Total:           {len(all_docs):5d} documents")
        print(f"  Cached:          {cached_count:5d}")
        print(f"  New to process:  {new_count:5d}")
        print(
            f"  Est. cost:       ${est['est_cost_usd']:.2f}"
            + (f"  (model={dry_model})" if dry_model else "")
        )
        if args.batch_api:
            print(f"  Requests:        {est['richieste']:5d}")
            print(f"  Est. batch cost: ${est['est_cost_usd_batch']:.2f} (Batch API, 50% discount)")
        print(f"{'=' * 60}")
        return

    if args.batch_api:

        model = args.model or "claude-sonnet-4-5-20250929"
        log.info(f"Using Batch API with model: {model}")
        data = SBKData()
        facts = run_batch_api(all_docs, data=data, model=model)
        save_facts(facts)
    elif args.batch:

        data = SBKData()
        facts = run_batch(
            all_docs,
            data=data,
            workers=args.workers,
            verbose=args.verbose,
            batch_size=args.batch_size,
        )
        save_facts(facts)
    else:
        parser.print_help()
        print(
            "\nUse --batch-api (recommended) or --batch to run extraction, --dry-run to estimate cost."
        )

    if not args.dry_run:
        from sbk_config import mark_last_run, save_input_checkpoint

        _rel_inputs = [
            PLAUD_DIR,
            TACTIQ_RAW_DIR,
            WHATSAPP_CHATS_DIR,
            SLACK_CONVERSATIONS_DIR,
            ATTIO_DIR / "notes",
            *ATTIO_TRANSCRIPTS_DIRS,
            CHATGPT_DIR,
            NOTION_DIR,
            GDRIVE_DIR,



            EMAILS_DIR,
            DATA_ROOT / "slack" / "dm",
            DATA_ROOT / "voice-memos" / "transcripts",
        ]
        save_input_checkpoint("l3-extract-rel", _rel_inputs)
        mark_last_run("l3-extract-rel")


def _acquire_lock():
    ""
    if not acquire_pid_lock("extract-relationships", logger=log):


        log.warning("extract-relationships: lock held by another instance, exit 75")
        sys.exit(75)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-extract-relationships", source="l3-extract-rel", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
