#!/usr/bin/env python3
""

















from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pandas as pd
from xs_l3_chunking import chunk_document_semantic, merge_extraction_results
from xs_l3_common import (
    call_claude,
    get_excluded_attio_meeting_ids,
    get_excluded_tactiq_meeting_ids,
    setup_logging,
)
from xs_l3_email_filter import filter_emails as email_prefilter
from xs_l3_routing import SmartRouter

from sbk_config import (
    ATTIO_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    ATTIO_TRANSCRIPTS_DIRS,
    CHATGPT_DIR,
    DATA_ROOT,
    ENRICHED_DIR,
    GDRIVE_DIR,
    NLP_DIR,
    NOTION_DIR,
    PLAUD_DIR,
    SLACK_DIR,
    STT_NAME_CORRECTIONS,
    TACTIQ_DIR,
    VOICE_MEMOS_PROCESSED_DIR,
    WHATSAPP_DIR,
    attio_transcript_files,
    safe_write_json,
    safe_write_parquet,
)

log = logging.getLogger("sbk-l3-extract")



DECISIONS_FILE = NLP_DIR / "decisions.parquet"
ACTION_ITEMS_FILE = NLP_DIR / "action-items.parquet"
FINANCIAL_MENTIONS_FILE = NLP_DIR / "financial-mentions.parquet"
TOPICS_FILE = NLP_DIR / "topics.json"
ENTITIES_FILE = NLP_DIR / "entities.parquet"
BATCH_RESPONSES_DIR = NLP_DIR / "batch-responses"





STOP_ENTITIES: set[str] = {

    "domani",
    "oggi",
    "ieri",
    "dopodomani",
    "ora",
    "adesso",
    "sempre",
    "mai",
    "lunedi",
    "lunedì",
    "martedi",
    "martedì",
    "mercoledi",
    "mercoledì",
    "giovedi",
    "giovedì",
    "venerdi",
    "venerdì",
    "sabato",
    "domenica",
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
    "stasera",
    "stamattina",
    "stanotte",
    "natale",
    "pasqua",
    "capodanno",

    "grazie",
    "ciao",
    "bravo",
    "bene",
    "male",
    "tutto",
    "niente",
    "cosa",
    "fatto",
    "detto",
    "tipo",
    "roba",
    "bomba",
    "top",

    "edo",
    "ale",
    "fra",
    "gio",
    "ste",
    "vale",
    "simo",
    "fede",
    "mila",
    "ludo",
    "nico",
    "teo",
    "leo",

    "speaker",
    "test",
    "demo",
    "example",
    "sample",
    "default",
    "admin",
    "user",
    "guest",
    "unknown",
    "none",
    "null",
    "n/a",
}





_ITALIAN_STOP_WORDS: set[str] = {

    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
    "un",
    "uno",
    "una",
    "di",
    "del",
    "dello",
    "della",
    "dei",
    "degli",
    "delle",
    "a",
    "al",
    "allo",
    "alla",
    "ai",
    "agli",
    "alle",
    "da",
    "dal",
    "dallo",
    "dalla",
    "dai",
    "dagli",
    "dalle",
    "in",
    "nel",
    "nello",
    "nella",
    "nei",
    "negli",
    "nelle",
    "con",
    "su",
    "sul",
    "sullo",
    "sulla",
    "sui",
    "sugli",
    "sulle",
    "per",
    "tra",
    "fra",

    "io",
    "tu",
    "lui",
    "lei",
    "noi",
    "voi",
    "loro",
    "mi",
    "ti",
    "ci",
    "vi",
    "si",
    "me",
    "te",
    "se",
    "che",
    "chi",
    "cui",
    "quale",
    "quali",
    "questo",
    "questa",
    "questi",
    "queste",
    "quello",
    "quella",
    "quelli",
    "quelle",
    "ne",
    "li",

    "ho",
    "hai",
    "ha",
    "abbiamo",
    "avete",
    "hanno",
    "sono",
    "sei",
    "è",
    "siamo",
    "siete",
    "era",
    "ero",
    "eri",
    "eravamo",
    "erano",
    "fatto",
    "fare",
    "fai",
    "fa",
    "fanno",
    "dire",
    "detto",
    "dice",
    "dici",
    "essere",
    "avere",
    "stare",
    "andare",
    "venire",
    "stato",
    "stata",
    "stati",
    "state",

    "e",
    "ed",
    "o",
    "ma",
    "però",
    "pero",
    "perché",
    "perche",
    "come",
    "quando",
    "dove",
    "non",
    "no",
    "sì",
    "già",
    "ancora",
    "qui",
    "qua",
    "lì",
    "là",
    "giù",
    "molto",
    "poco",
    "tanto",
    "quanto",
    "troppo",
    "più",
    "meno",
    "meglio",
    "peggio",
    "poi",
    "dopo",
    "prima",
    "anche",
    "solo",
    "proprio",
    "altro",
    "altri",
    "tutti",
    "tutte",

    "cioè",
    "cioe",
    "quindi",
    "allora",
    "comunque",
    "praticamente",
    "insomma",
    "ecco",
    "tipo",
    "adesso",
    "ok",
    "okay",
    "boh",
    "vabbe",
    "vabbè",
    "diciamo",
    "infatti",

    "oggi",
    "domani",
    "ieri",
    "stasera",
    "stamattina",
    "stanotte",
    "yesterday",
    "today",
    "tomorrow",
    "tonight",
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
    "natale",
    "pasqua",
    "capodanno",

    "roba",
    "cosa",
    "cose",
    "parte",
    "punto",
    "modo",
    "caso",
    "tempo",
    "anno",
    "mese",
    "giorno",
    "ora",
    "momento",
    "persona",
    "gente",
    "uomo",
    "donna",
    "ragazzo",
    "ragazza",
    "casa",
    "posto",
    "luogo",
    "mondo",
    "paese",
    "lavoro",
    "progetto",
    "problema",
    "soluzione",
    "volta",
    "vita",
    "senso",
    "mano",
    "idea",
    "fine",

    "the",
    "and",
    "but",
    "for",
    "not",
    "you",
    "all",
    "can",
    "her",
    "was",
    "one",
    "our",
    "out",
    "are",
    "has",
    "his",
    "how",
    "its",
    "may",
    "new",
    "now",
    "old",
    "see",
    "way",
    "who",
    "did",
    "get",
    "let",
    "say",
    "she",
    "too",
    "use",
    "just",
    "also",
    "very",
    "really",
    "actually",
    "basically",
    "like",
    "know",
    "think",
    "yeah",
    "yes",
    "about",
    "up",
    "into",
    "over",
    "after",
    "before",

    "speaker",
    "speakers",
    "speakerphone",
    "mr. speaker",
    "built-in speaker",

    "oh",
    "ah",
    "eh",
    "uh",
    "mm",
    "hmm",
    "mhm",
    "grazie",
    "ciao",
    "bravo",
    "niente",
}

STOP_ENTITIES = STOP_ENTITIES | _ITALIAN_STOP_WORDS



SHORT_ENTITY_ALLOWLIST: set[str] = {
    "uk",
    "us",
    "eu",
    "ai",
    "vc",
    "pe",
    "hr",
    "pr",
    "it",
}


_MAX_ENTITY_TYPES = 3



DECISION_PATTERNS = [
    re.compile(r"\b(abbiamo deciso)\b", re.IGNORECASE),
    re.compile(r"\b(la decisione è)\b", re.IGNORECASE),
    re.compile(r"\b(we decided)\b", re.IGNORECASE),
    re.compile(r"\b(decision:)", re.IGNORECASE),
    re.compile(r"\b(si è deciso)\b", re.IGNORECASE),
    re.compile(r"\b(ok facciamo)\b", re.IGNORECASE),
    re.compile(r"\b(andiamo con)\b", re.IGNORECASE),
    re.compile(r"\b(procediamo con)\b", re.IGNORECASE),
    re.compile(r"\b(abbiamo scelto)\b", re.IGNORECASE),
    re.compile(r"\b(la scelta è)\b", re.IGNORECASE),
    re.compile(r"\b(it's decided)\b", re.IGNORECASE),
    re.compile(r"\b(let's go with)\b", re.IGNORECASE),
]

ACTION_PATTERNS = [
    re.compile(r"\b(devi fare)\b", re.IGNORECASE),
    re.compile(r"\b(action item)", re.IGNORECASE),
    re.compile(r"\b(TODO:)", re.IGNORECASE),
    re.compile(r"\b(da fare:)", re.IGNORECASE),
    re.compile(r"\b(il prossimo passo)\b", re.IGNORECASE),
    re.compile(r"\b(next step)", re.IGNORECASE),
    re.compile(r"\b(mi occupo)\b", re.IGNORECASE),
    re.compile(r"\b(ti occupi)\b", re.IGNORECASE),
    re.compile(r"\b(facciamo così)\b", re.IGNORECASE),
    re.compile(r"\b(bisogna fare)\b", re.IGNORECASE),
    re.compile(r"\b(dobbiamo fare)\b", re.IGNORECASE),
    re.compile(r"\b(I'll take care)\b", re.IGNORECASE),
    re.compile(r"\b(you need to)\b", re.IGNORECASE),
    re.compile(r"\b(we need to)\b", re.IGNORECASE),
]

COMMITMENT_PATTERNS = [
    re.compile(r"\b(mi impegno)\b", re.IGNORECASE),
    re.compile(r"\b(entro\s+\w+)\b", re.IGNORECASE),
    re.compile(r"\b(deadline)", re.IGNORECASE),
    re.compile(r"\b(entro venerdì)\b", re.IGNORECASE),
    re.compile(r"\b(per lunedì)\b", re.IGNORECASE),
    re.compile(r"\b(I'll)\b", re.IGNORECASE),
    re.compile(r"\b(I will)\b", re.IGNORECASE),
    re.compile(r"\b(prometto)\b", re.IGNORECASE),
    re.compile(r"\b(entro fine)\b", re.IGNORECASE),
    re.compile(r"\b(by end of)\b", re.IGNORECASE),
    re.compile(r"\b(by friday)\b", re.IGNORECASE),
    re.compile(r"\b(by monday)\b", re.IGNORECASE),
]

NUMBER_PATTERNS = [
    re.compile(r"[€$]\s?\d[\d.,]+", re.IGNORECASE),
    re.compile(r"\d[\d.,]+\s?(?:EUR|USD|euro|dollari)", re.IGNORECASE),
    re.compile(r"\d+(?:[.,]\d+)?%", re.IGNORECASE),
    re.compile(r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b"),
]





def load_plaud_transcripts() -> list[dict]:
    ""



    transcripts = []
    json_files = sorted(PLAUD_DIR.glob("*.json"))
    log.info(f"Found {len(json_files)} Plaud JSON files")

    for f in json_files:
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, list) or len(data) == 0:
                continue


            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
            date_str = date_match.group(1) if date_match else ""


            title = re.sub(r"^\d{4}-\d{2}-\d{2}_+", "", f.stem)
            title = title.replace("_", " ").strip()

            transcripts.append(
                {
                    "source": "plaud",
                    "file": f.name,
                    "title": title,
                    "date": date_str,
                    "meeting_id": f.stem,
                    "utterances": data,
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load {f.name}: {e}")

    log.info(f"Loaded {len(transcripts)} Plaud transcripts")
    return transcripts


def load_tactiq_transcripts() -> list[dict]:
    ""



    transcripts = []
    raw_dir = TACTIQ_DIR.parent / "raw"
    json_files = sorted(raw_dir.glob("*.json"))
    log.info(f"Found {len(json_files)} Tactiq JSON files")

    for f in json_files:
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, dict):
                continue

            meeting_id = data.get("id", f.stem)
            title = data.get("title", f.stem)
            created_ms = data.get("created", 0)
            date_str = ""
            if created_ms:
                dt = datetime.fromtimestamp(created_ms / 1000, tz=UTC)
                date_str = dt.strftime("%Y-%m-%d")


            transcript_obj = data.get("transcript", {})
            blocks = transcript_obj.get("blocks", [])
            if not blocks:
                continue


            utterances = []
            for block in blocks:
                if block.get("isDeleted"):
                    continue
                utterances.append(
                    {
                        "content": block.get("transcript", ""),
                        "speaker": block.get("speakerName"),
                        "start_time": block.get("timestamp", 0),
                        "end_time": block.get("timestamp", 0),
                    }
                )

            if not utterances:
                continue

            transcripts.append(
                {
                    "source": "tactiq",
                    "file": f.name,
                    "title": title,
                    "date": date_str,
                    "meeting_id": meeting_id,
                    "utterances": utterances,
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load {f.name}: {e}")

    log.info(f"Loaded {len(transcripts)} Tactiq transcripts")


    excluded_ids = get_excluded_tactiq_meeting_ids()
    if excluded_ids:
        before = len(transcripts)
        transcripts = [t for t in transcripts if t["meeting_id"] not in excluded_ids]
        filtered = before - len(transcripts)
        if filtered:
            log.info(
                f"Tactiq dedup: filtered {filtered} meetings (Attio won), {len(transcripts)} remaining"
            )

    return transcripts


def get_full_text(transcript: dict) -> str:
    ""
    parts = []
    for u in transcript["utterances"]:
        speaker = u.get("speaker") or "Unknown"
        content = u.get("content", "").strip()
        if content:
            parts.append(f"{speaker}: {content}")
    return "\n".join(parts)


def get_context_window(utterances: list[dict], idx: int, window: int = 3) -> str:
    ""
    start = max(0, idx - window)
    end = min(len(utterances), idx + window + 1)
    lines = []
    for i in range(start, end):
        u = utterances[i]
        speaker = u.get("speaker") or "Unknown"
        content = u.get("content", "").strip()
        marker = ">>>" if i == idx else "   "
        lines.append(f"{marker} {speaker}: {content}")
    return "\n".join(lines)





def _text_to_utterances(text: str, max_chunk: int = 2000) -> list[dict]:
    ""



    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    utterances = []
    for para in paragraphs:
        if len(para) <= max_chunk:
            utterances.append({"content": para, "speaker": "", "start_time": 0, "end_time": 0})
        else:

            for i in range(0, len(para), max_chunk):
                chunk = para[i : i + max_chunk]
                utterances.append({"content": chunk, "speaker": "", "start_time": 0, "end_time": 0})
    return utterances


def load_email_texts() -> list[dict]:
    ""
    path = ENRICHED_DIR / "processed" / "messages-with-body.parquet"
    if not path.exists():
        log.warning(f"Email body file not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "body_text" not in df.columns:
        log.warning("No body_text column in email parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("body_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        subject = str(row.get("subject", "")) if "subject" in df.columns else ""
        date_val = row.get("date", "")
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10] if date_val else ""
        msg_id = row.get("message_id") or row.get("id") or f"email_{_}"
        from_addr = str(row.get("from_addr", "") or "")
        full_text = f"Subject: {subject}\n\n{text}" if subject else text
        docs.append(
            {
                "source": "email",
                "file": str(msg_id),
                "title": subject[:100] if subject else "Email",
                "date": date_str,
                "meeting_id": str(msg_id),
                "from_addr": from_addr,
                "utterances": _text_to_utterances(full_text),
            }
        )

    log.info(f"Loaded {len(docs)} email documents with body text")
    return docs


def load_slack_channel_texts() -> list[dict]:
    ""
    path = SLACK_DIR / "channel-texts.parquet"
    if not path.exists():
        log.warning(f"Slack channel texts not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "channel_text" not in df.columns:
        log.warning("No channel_text column in slack parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("channel_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        name = str(row.get("channel_name", "")) if "channel_name" in df.columns else ""
        ch_id = row.get("channel_id") or row.get("id") or f"slack_ch_{_}"
        docs.append(
            {
                "source": "slack",
                "file": str(ch_id),
                "title": f"#{name}" if name else "Slack Channel",
                "date": "",
                "meeting_id": str(ch_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} Slack channel texts")
    return docs


def load_slack_dm_texts() -> list[dict]:
    ""
    dm_dir = DATA_ROOT / "slack" / "dm"
    if not dm_dir.exists():
        log.warning(f"Slack DM dir not found: {dm_dir}")
        return []

    docs = []
    for f in sorted(dm_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            user_name = data.get("user_name", f.stem)
            messages = data.get("messages", [])
            if not messages:
                continue

            utterances = []
            for m in messages:
                text = m.get("text", "").strip()
                if len(text) < 10:
                    continue
                utterances.append(
                    {
                        "content": text,
                        "speaker": m.get("user", ""),
                        "start_time": float(m.get("ts", 0)),
                        "end_time": 0,
                    }
                )

            if not utterances:
                continue

            docs.append(
                {
                    "source": "slack_dm",
                    "file": f.name,
                    "title": f"DM with {user_name}",
                    "date": "",
                    "meeting_id": f"slack_dm_{f.stem}",
                    "utterances": utterances,
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load DM {f.name}: {e}")

    log.info(f"Loaded {len(docs)} Slack DM conversations")
    return docs


def load_whatsapp_texts() -> list[dict]:
    ""
    path = WHATSAPP_DIR / "chat-texts.parquet"
    if not path.exists():
        log.warning(f"WhatsApp texts not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "chat_text" not in df.columns:
        log.warning("No chat_text column in whatsapp parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("chat_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        chat_name = str(row.get("chat_name", "")) if "chat_name" in df.columns else ""
        chat_id = row.get("chat_id") or f"wa_{_}"
        docs.append(
            {
                "source": "whatsapp",
                "file": str(chat_id),
                "title": chat_name or "WhatsApp Chat",
                "date": "",
                "meeting_id": str(chat_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} WhatsApp chat texts")
    return docs


def load_chatgpt_texts() -> list[dict]:
    ""
    path = CHATGPT_DIR / "conversations-classified.parquet"
    if not path.exists():
        log.warning(f"ChatGPT texts not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "full_text" not in df.columns:
        log.warning("No full_text column in chatgpt parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("full_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        title = str(row.get("title", "")) if "title" in df.columns else ""
        conv_id = row.get("id") or row.get("conversation_id") or f"chatgpt_{_}"
        date_val = row.get("create_time") or row.get("date", "")
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10] if date_val else ""
        docs.append(
            {
                "source": "chatgpt",
                "file": str(conv_id),
                "title": title[:100] if title else "ChatGPT",
                "date": date_str,
                "meeting_id": str(conv_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} ChatGPT conversations")
    return docs


def load_notion_texts() -> list[dict]:
    ""
    path = NOTION_DIR / "pages-text.parquet"
    if not path.exists():
        log.warning(f"Notion texts not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "page_text" not in df.columns:
        log.warning("No page_text column in notion parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("page_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        title = str(row.get("title", "")) if "title" in df.columns else ""
        page_id = row.get("page_id") or row.get("id") or f"notion_{_}"
        docs.append(
            {
                "source": "notion",
                "file": str(page_id),
                "title": title[:100] if title else "Notion Page",
                "date": "",
                "meeting_id": str(page_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} Notion pages")
    return docs


def load_gdrive_texts() -> list[dict]:
    ""
    path = GDRIVE_DIR / "documents.parquet"
    if not path.exists():
        log.warning(f"GDrive documents not found: {path}")
        return []

    df = pd.read_parquet(path)
    if "content_text" not in df.columns:
        log.warning("No content_text column in gdrive parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get("content_text", "")
        if not text or not isinstance(text, str) or len(text) < 50:
            continue
        name = str(row.get("name", "")) if "name" in df.columns else ""
        file_id = row.get("file_id") or row.get("id") or f"gdrive_{_}"
        date_val = row.get("modified") or row.get("modifiedTime", "")
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10] if date_val else ""
        docs.append(
            {
                "source": "gdrive",
                "file": str(file_id),
                "title": name[:100] if name else "GDrive Doc",
                "date": date_str,
                "meeting_id": str(file_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} GDrive documents with text")
    return docs


def load_attio_notes_texts() -> list[dict]:
    ""
    path = ATTIO_DIR / "notes.parquet"
    if not path.exists():
        log.warning(f"Attio notes not found: {path}")
        return []

    df = pd.read_parquet(path)
    text_col = "content_plaintext" if "content_plaintext" in df.columns else None
    if not text_col:
        log.warning("No content_plaintext column in attio notes parquet")
        return []

    docs = []
    for _, row in df.iterrows():
        text = row.get(text_col, "")
        if not text or not isinstance(text, str) or len(text) < 30:
            continue
        title = str(row.get("title", "")) if "title" in df.columns else ""
        note_id = row.get("note_id") or f"attio_note_{_}"
        docs.append(
            {
                "source": "attio_notes",
                "file": str(note_id),
                "title": title[:100] if title else "Attio Note",
                "date": "",
                "meeting_id": str(note_id),
                "utterances": _text_to_utterances(text),
            }
        )

    log.info(f"Loaded {len(docs)} Attio notes")
    return docs


def load_voice_memo_texts() -> list[dict]:
    ""
    segments_file = VOICE_MEMOS_PROCESSED_DIR / "speech-segments.parquet"
    index_file = VOICE_MEMOS_PROCESSED_DIR / "recordings-index.parquet"
    if not segments_file.exists():
        log.warning(f"Voice memo segments not found: {segments_file}")
        return []

    seg_df = pd.read_parquet(segments_file)
    idx_df = pd.read_parquet(index_file) if index_file.exists() else pd.DataFrame()


    title_map = {}
    date_map = {}
    if not idx_df.empty:
        for _, row in idx_df.iterrows():
            rid = row.get("recording_id", "")
            title_map[rid] = str(row.get("title", ""))
            d = row.get("date", "")
            date_map[rid] = str(d)[:10] if d else ""

    docs = []
    for rid, grp in seg_df.groupby("recording_id"):
        utterances = []
        for _, row in grp.iterrows():
            text = row.get("text", "")
            if not text or not isinstance(text, str) or len(text) < 5:
                continue
            utterances.append(
                {
                    "content": text,
                    "speaker": row.get("speaker_resolved") or row.get("speaker", ""),
                    "start_time": float(row.get("start_time", 0)),
                    "end_time": float(row.get("end_time", 0)),
                }
            )
        if not utterances:
            continue
        docs.append(
            {
                "source": "voice_memo",
                "file": str(rid),
                "title": title_map.get(rid, str(rid))[:100],
                "date": date_map.get(rid, ""),
                "meeting_id": str(rid),
                "utterances": utterances,
            }
        )

    log.info(f"Loaded {len(docs)} voice memo transcripts")
    return docs


def load_attio_call_texts() -> list[dict]:
    ""







    json_files = attio_transcript_files(ATTIO_TRANSCRIPTS_DIR)
    if not json_files:
        log.warning(f"Attio transcripts not found in {ATTIO_TRANSCRIPTS_DIRS}")
        return []
    log.info(f"Found {len(json_files)} Attio call transcript files")

    docs = []
    for f in json_files:
        try:
            data = json.loads(f.read_text())
            if not isinstance(data, dict):
                continue

            meeting_id = data.get("meeting_id", f.stem)
            title = (data.get("meeting_title") or f.stem).strip()
            meeting_date = data.get("meeting_date", "")
            date_str = ""
            if meeting_date:

                date_str = str(meeting_date)[:10]

            segments = data.get("segments", [])
            if not segments:

                raw = data.get("raw_transcript", "")
                if raw and len(raw) >= 50:
                    docs.append(
                        {
                            "source": "attio_call",
                            "file": f.name,
                            "title": title[:100],
                            "date": date_str,
                            "meeting_id": str(meeting_id),
                            "utterances": _text_to_utterances(raw),
                        }
                    )
                continue


            utterances = []
            for seg in segments:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                utterances.append(
                    {
                        "content": text,
                        "speaker": seg.get("speaker", ""),
                        "start_time": float(seg.get("start", 0)),
                        "end_time": float(seg.get("end", 0)),
                    }
                )

            if not utterances:
                continue

            docs.append(
                {
                    "source": "attio_call",
                    "file": f.name,
                    "title": title[:100],
                    "date": date_str,
                    "meeting_id": str(meeting_id),
                    "utterances": utterances,
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load Attio call {f.name}: {e}")

    log.info(f"Loaded {len(docs)} Attio call transcripts")


    excluded_ids = get_excluded_attio_meeting_ids()
    if excluded_ids:
        before = len(docs)
        docs = [d for d in docs if d["meeting_id"] not in excluded_ids]
        filtered = before - len(docs)
        if filtered:
            log.info(
                f"Attio dedup: filtered {filtered} meetings (Tactiq won), {len(docs)} remaining"
            )

    return docs




ALL_SOURCES = [
    "plaud",
    "tactiq",
    "email",
    "slack",
    "slack_dm",
    "whatsapp",
    "chatgpt",
    "notion",
    "gdrive",
    "attio_notes",
    "attio_call",
    "voice_memo",
]


MEETING_SOURCES = {"plaud", "tactiq", "voice_memo", "slack", "slack_dm", "whatsapp", "attio_call"}

_SOURCE_LOADERS = {
    "plaud": load_plaud_transcripts,
    "tactiq": load_tactiq_transcripts,
    "email": load_email_texts,
    "slack": load_slack_channel_texts,
    "slack_dm": load_slack_dm_texts,
    "whatsapp": load_whatsapp_texts,
    "chatgpt": load_chatgpt_texts,
    "notion": load_notion_texts,
    "gdrive": load_gdrive_texts,
    "attio_notes": load_attio_notes_texts,
    "attio_call": load_attio_call_texts,
    "voice_memo": load_voice_memo_texts,
}


def load_sources(sources: list[str]) -> list[dict]:
    ""
    docs = []
    for src in sources:
        loader = _SOURCE_LOADERS.get(src)
        if loader:
            docs.extend(loader())
        else:
            log.warning(f"Unknown source: {src}")
    return docs





def extract_regex(transcripts: list[dict], verbose: bool = False) -> tuple[list[dict], list[dict]]:
    ""



    decisions = []
    action_items = []
    total_decisions = 0
    total_actions = 0

    for t_idx, transcript in enumerate(transcripts):
        utterances = transcript["utterances"]
        t_decisions = 0
        t_actions = 0

        for u_idx, u in enumerate(utterances):
            content = u.get("content", "")
            if not content:
                continue

            speaker = u.get("speaker") or "Unknown"
            context = get_context_window(utterances, u_idx)


            for pattern in DECISION_PATTERNS:
                if pattern.search(content):
                    decisions.append(
                        {
                            "date": transcript["date"],
                            "meeting_id": transcript["meeting_id"],
                            "meeting_title": transcript["title"],
                            "speaker": speaker,
                            "decision_text": content.strip(),
                            "context": context,
                            "extraction_method": "regex",
                            "pattern_matched": pattern.pattern,
                            "source": transcript["source"],
                        }
                    )
                    t_decisions += 1
                    break


            for pattern in ACTION_PATTERNS:
                if pattern.search(content):

                    assignee = _extract_assignee(content, speaker)
                    deadline = _extract_deadline(content)

                    action_items.append(
                        {
                            "date": transcript["date"],
                            "meeting_id": transcript["meeting_id"],
                            "meeting_title": transcript["title"],
                            "speaker": speaker,
                            "assignee": assignee,
                            "action_text": content.strip(),
                            "deadline": deadline,
                            "context": context,
                            "extraction_method": "regex",
                            "pattern_matched": pattern.pattern,
                            "source": transcript["source"],
                        }
                    )
                    t_actions += 1
                    break


            for pattern in COMMITMENT_PATTERNS:
                if pattern.search(content):

                    already_matched = any(
                        a["meeting_id"] == transcript["meeting_id"]
                        and a["action_text"] == content.strip()
                        for a in action_items[-10:]
                    )
                    if not already_matched:
                        action_items.append(
                            {
                                "date": transcript["date"],
                                "meeting_id": transcript["meeting_id"],
                                "meeting_title": transcript["title"],
                                "speaker": speaker,
                                "assignee": speaker,
                                "action_text": content.strip(),
                                "deadline": _extract_deadline(content),
                                "context": context,
                                "extraction_method": "regex_commitment",
                                "pattern_matched": pattern.pattern,
                                "source": transcript["source"],
                            }
                        )
                        t_actions += 1
                    break

        total_decisions += t_decisions
        total_actions += t_actions

        if verbose and (t_decisions > 0 or t_actions > 0):
            log.debug(
                f"  [{transcript['source']}] {transcript['title'][:60]}: "
                f"{t_decisions} decisions, {t_actions} actions"
            )

        if (t_idx + 1) % 100 == 0:
            log.info(f"  Processed {t_idx + 1}/{len(transcripts)} transcripts...")

    log.info(
        f"Regex extraction complete: {total_decisions} decisions, "
        f"{total_actions} action items from {len(transcripts)} transcripts"
    )
    return decisions, action_items


def _extract_assignee(text: str, speaker: str) -> str:
    ""
    text_lower = text.lower()
    if any(p in text_lower for p in ["mi occupo", "me ne occupo", "i'll", "i will", "mi impegno"]):
        return speaker
    if any(p in text_lower for p in ["ti occupi", "devi fare", "you need to"]):
        return ""
    return ""


def _extract_deadline(text: str) -> str:
    ""

    day_patterns = [
        (r"entro\s+(lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)", re.IGNORECASE),
        (r"per\s+(lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)", re.IGNORECASE),
        (r"entro\s+(fine\s+\w+)", re.IGNORECASE),
        (r"by\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", re.IGNORECASE),
        (r"by\s+(end\s+of\s+\w+)", re.IGNORECASE),
        (r"entro\s+il\s+(\d{1,2}[/\-]\d{1,2}(?:[/\-]\d{2,4})?)", re.IGNORECASE),
        (r"deadline:?\s*(\S+(?:\s+\S+)?)", re.IGNORECASE),
    ]
    for pattern, flags in day_patterns:
        m = re.search(pattern, text, flags)
        if m:
            return m.group(1).strip()
    return ""




HAIKU_MODEL = "claude-haiku-4-5-20251001"



_PROVIDER = "anthropic"

EXTRACTION_SYSTEM_PROMPT = """You are an expert meeting analyst. Extract structured information from meeting transcripts.

Output ONLY valid JSON with these arrays:
- decisions: [{text, speaker, confidence}] — Explicit decisions made during the meeting
- action_items: [{text, assignee, deadline, speaker}] — Tasks assigned or committed to
- key_topics: [string] — Main topics discussed (3-10 topics)
- entities_mentioned: [{name, type}] — People, companies, products mentioned (type: person/org/product/location)
- financial_mentions: [{amount, currency, context, entity, type}]
  Types: investment, revenue, valuation, equity, debt, salary, fee
  NEVER skip numbers. Every amount mentioned MUST be extracted.

Rules:
- Only extract EXPLICIT decisions and action items, not general discussion
- Confidence: high (explicitly stated), medium (implied), low (inferred)
- If no deadline is mentioned, set deadline to null
- If assignee is unclear, set to null
- For entities, focus on proper nouns (people names, company names)
- Respond in the same language as the transcript
- Keep text concise but preserve meaning"""

EXTRACTION_USER_PROMPT = """Meeting: {title}
Date: {date}
Source: {source}

Transcript:
{text}

Extract decisions, action items, key topics, and entities. Respond with JSON only."""


def estimate_batch_cost(
    transcripts: list[dict], provider: str = "anthropic", model: str | None = None
) -> dict:
    ""




    from xs_l3_common import PRICING, PROVIDER_CONFIG, PROVIDER_PRICING

    total_chars = 0
    total_utterances = 0
    for t in transcripts:
        text = get_full_text(t)
        total_chars += len(text)
        total_utterances += len(t["utterances"])


    est_input_tokens = total_chars / 4

    est_output_tokens = len(transcripts) * 500


    config = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["anthropic"])
    model = model or config["default_model"]
    pricing = PRICING.get(model, PROVIDER_PRICING.get(provider, {"input": 0.80, "output": 4.0}))
    est_cost = (
        est_input_tokens * pricing["input"] + est_output_tokens * pricing["output"]
    ) / 1_000_000

    return {
        "transcripts": len(transcripts),
        "total_chars": total_chars,
        "total_utterances": total_utterances,
        "est_input_tokens": int(est_input_tokens),
        "est_output_tokens": int(est_output_tokens),
        "est_cost_usd": round(est_cost, 2),
    }


def _process_single_transcript(transcript: dict) -> dict:
    ""



    response_file = BATCH_RESPONSES_DIR / f"{transcript['source']}_{transcript['meeting_id']}.json"


    if response_file.exists():
        try:
            parsed = json.loads(response_file.read_text())
            return {"transcript": transcript, "parsed": parsed, "cached": True}
        except (json.JSONDecodeError, OSError):
            pass

    full_text = get_full_text(transcript)
    if len(full_text) < 100:
        return {"transcript": transcript, "skipped": True}


    chunks = chunk_document_semantic(full_text, max_chars=100_000, overlap_chars=3000)

    if len(chunks) > 1:
        chunk_results = []
        for chunk in chunks:
            chunk_response_file = (
                BATCH_RESPONSES_DIR
                / f"{transcript['source']}_{transcript['meeting_id']}_chunk_{chunk.chunk_idx}.json"
            )
            if chunk_response_file.exists():
                try:
                    parsed = json.loads(chunk_response_file.read_text())
                    chunk_results.append(parsed)
                    continue
                except (json.JSONDecodeError, OSError):
                    pass

            chunk_prompt = EXTRACTION_USER_PROMPT.format(
                title=transcript["title"],
                date=transcript["date"],
                source=transcript["source"],
                text=chunk.text,
            )
            try:
                response = call_claude(
                    prompt=chunk_prompt,
                    system=EXTRACTION_SYSTEM_PROMPT,
                    model=HAIKU_MODEL,
                    max_tokens=4096,
                    temperature=0.1,
                    provider=transcript.get("_provider", _PROVIDER),
                )
                parsed = _parse_claude_response(response)
                if parsed:
                    chunk_response_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
                    chunk_results.append(parsed)
            except Exception as e:
                log.warning(f"Chunk {chunk.chunk_idx} failed for {transcript['meeting_id']}: {e}")

        if chunk_results:
            merged = merge_extraction_results(chunk_results)
            response_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
            return {"transcript": transcript, "parsed": merged}
        else:
            return {"transcript": transcript, "error": "all_chunks_failed"}


    full_text = chunks[0].text if chunks else full_text

    prompt = EXTRACTION_USER_PROMPT.format(
        title=transcript["title"],
        date=transcript["date"],
        source=transcript["source"],
        text=full_text,
    )

    try:
        response = call_claude(
            prompt=prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            model=HAIKU_MODEL,
            max_tokens=4096,
            temperature=0.1,
            provider=transcript.get("_provider", _PROVIDER),
        )

        parsed = _parse_claude_response(response)
        if parsed:
            response_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
            return {"transcript": transcript, "parsed": parsed}
        else:
            return {"transcript": transcript, "error": "parse_failure"}

    except Exception as e:
        return {"transcript": transcript, "error": str(e)}


def run_batch_extraction(
    transcripts: list[dict],
    verbose: bool = False,
    workers: int = 1,
) -> tuple[list[dict], list[dict], list[dict]]:
    ""






    BATCH_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    decisions = []
    action_items = []
    financial_mentions = []
    errors = 0
    completed = 0
    lock = threading.Lock()

    effective_workers = max(1, workers)
    log.info(f"Running batch extraction with {effective_workers} workers")

    def collect_result(result: dict):
        nonlocal errors, completed
        transcript = result["transcript"]

        if result.get("skipped"):
            return

        if result.get("error"):
            if result["error"] == "parse_failure":
                log.warning(f"Failed to parse response for: {transcript['title'][:60]}")
            else:
                log.error(f"API error for {transcript['title'][:60]}: {result['error']}")
            with lock:
                errors += 1
            return

        parsed = result.get("parsed")
        if parsed:
            with lock:
                _collect_claude_results(
                    parsed, transcript, decisions, action_items, financial_mentions
                )

    if effective_workers == 1:

        for t_idx, transcript in enumerate(transcripts):
            result = _process_single_transcript(transcript)
            collect_result(result)
            completed += 1

            if (t_idx + 1) % 10 == 0:
                log.info(f"  Processed {t_idx + 1}/{len(transcripts)} transcripts...")
            if not result.get("cached") and not result.get("skipped"):
                time.sleep(0.3)
    else:

        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = {
                executor.submit(_process_single_transcript, t): i for i, t in enumerate(transcripts)
            }
            for future in as_completed(futures):
                result = future.result()
                collect_result(result)
                with lock:
                    completed += 1
                    if completed % 20 == 0:
                        log.info(
                            f"  Processed {completed}/{len(transcripts)} "
                            f"({errors} errors so far)..."
                        )

    log.info(
        f"Claude extraction complete: {len(decisions)} decisions, "
        f"{len(action_items)} action items, {len(financial_mentions)} financial mentions, "
        f"{errors} errors"
    )
    return decisions, action_items, financial_mentions


def _parse_claude_response(response: str) -> dict | None:
    ""
    text = response.strip()

    if text.startswith("```"):
        lines = text.split("\n")

        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _collect_claude_results(
    parsed: dict,
    transcript: dict,
    decisions: list[dict],
    action_items: list[dict],
    financial_mentions: list[dict] | None = None,
):
    ""
    for d in parsed.get("decisions", []):
        decisions.append(
            {
                "date": transcript["date"],
                "meeting_id": transcript["meeting_id"],
                "meeting_title": transcript["title"],
                "speaker": d.get("speaker", ""),
                "decision_text": d.get("text", ""),
                "context": "",
                "extraction_method": "claude",
                "source": transcript["source"],
            }
        )

    for a in parsed.get("action_items", []):
        action_items.append(
            {
                "date": transcript["date"],
                "meeting_id": transcript["meeting_id"],
                "meeting_title": transcript["title"],
                "speaker": a.get("speaker", ""),
                "assignee": a.get("assignee", ""),
                "action_text": a.get("text", ""),
                "deadline": a.get("deadline") or "",
                "context": "",
                "extraction_method": "claude",
                "source": transcript["source"],
            }
        )

    if financial_mentions is not None:
        for fm in parsed.get("financial_mentions", []):
            financial_mentions.append(
                {
                    "date": transcript["date"],
                    "meeting_id": transcript["meeting_id"],
                    "meeting_title": transcript["title"],
                    "amount": fm.get("amount", ""),
                    "currency": fm.get("currency", ""),
                    "context": fm.get("context", ""),
                    "entity": fm.get("entity", ""),
                    "type": fm.get("type", ""),
                    "source": transcript["source"],
                }
            )





def _build_italian_stop_words() -> set[str]:
    ""
    italian = {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "uno",
        "una",
        "di",
        "del",
        "dello",
        "della",
        "dei",
        "degli",
        "delle",
        "a",
        "al",
        "allo",
        "alla",
        "ai",
        "agli",
        "alle",
        "da",
        "dal",
        "dallo",
        "dalla",
        "dai",
        "dagli",
        "dalle",
        "in",
        "nel",
        "nello",
        "nella",
        "nei",
        "negli",
        "nelle",
        "su",
        "sul",
        "sullo",
        "sulla",
        "sui",
        "sugli",
        "sulle",
        "con",
        "per",
        "tra",
        "fra",
        "e",
        "ed",
        "o",
        "ma",
        "che",
        "chi",
        "cui",
        "non",
        "se",
        "come",
        "quando",
        "dove",
        "perche",
        "perché",
        "anche",
        "ancora",
        "questo",
        "questa",
        "questi",
        "queste",
        "quello",
        "quella",
        "quelli",
        "quelle",
        "sono",
        "è",
        "era",
        "sei",
        "siamo",
        "siete",
        "stato",
        "stata",
        "ho",
        "ha",
        "hai",
        "abbiamo",
        "avete",
        "hanno",
        "avere",
        "essere",
        "fare",
        "fatto",
        "dire",
        "detto",
        "cosa",
        "cose",
        "ci",
        "ne",
        "mi",
        "ti",
        "vi",
        "li",
        "poi",
        "dopo",
        "prima",
        "ora",
        "qui",
        "già",
        "più",
        "meno",
        "tutto",
        "tutti",
        "tutte",
        "molto",
        "tanto",
        "poco",
        "sempre",
        "mai",
        "solo",
        "proprio",
        "altro",
        "altri",
        "bene",
        "ok",
        "sì",
        "no",
        "allora",
        "quindi",
        "pero",
        "però",
        "comunque",
        "infatti",
        "praticamente",
        "diciamo",
        "cioè",
        "cioe",
        "ecco",
        "tipo",
        "vabbe",
        "vabbè",
        "niente",
        "insomma",
    }
    english = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "it",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "from",
        "by",
        "as",
        "and",
        "or",
        "but",
        "not",
        "if",
        "so",
        "then",
        "than",
        "what",
        "which",
        "who",
        "when",
        "where",
        "how",
        "why",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "just",
        "also",
        "very",
        "really",
        "actually",
        "basically",
        "like",
        "know",
        "think",
        "yeah",
        "yes",
        "no",
        "ok",
        "okay",
        "about",
        "up",
        "out",
        "into",
        "over",
        "after",
        "before",
    }
    return italian | english


def run_topic_modeling(transcripts: list[dict], verbose: bool = False) -> dict:
    ""







    try:
        from bertopic import BERTopic
    except ImportError:
        log.error(
            "BERTopic not installed. Install with: pip install bertopic\n"
            "  Also needs: pip install sentence-transformers"
        )
        return {}

    log.info("Building document corpus for topic modeling...")
    docs = []
    doc_metadata = []
    for t in transcripts:
        text = get_full_text(t)
        if len(text) < 50:
            continue
        docs.append(text)
        doc_metadata.append(
            {
                "meeting_id": t["meeting_id"],
                "title": t["title"],
                "date": t["date"],
                "source": t["source"],
            }
        )

    if len(docs) < 10:
        log.warning(f"Only {len(docs)} documents, need at least 10 for topic modeling")
        return {}

    log.info(f"Running BERTopic on {len(docs)} documents...")


    from sklearn.feature_extraction.text import CountVectorizer

    stop_words = list(_build_italian_stop_words())
    vectorizer = CountVectorizer(
        stop_words=stop_words,
        ngram_range=(1, 2),
        min_df=1,
    )


    min_topic = max(3, min(8, len(docs) // 50))


    from umap import UMAP

    umap_model = UMAP(
        n_neighbors=15,
        n_components=5,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )

    topic_model = BERTopic(
        language="multilingual",
        nr_topics="auto",
        min_topic_size=min_topic,
        vectorizer_model=vectorizer,
        umap_model=umap_model,
        verbose=verbose,
    )

    topics, probs = topic_model.fit_transform(docs)


    outlier_count = sum(1 for t in topics if t == -1)
    if outlier_count > len(docs) * 0.3:
        log.info(f"High outlier rate ({outlier_count}/{len(docs)}), reducing outliers...")
        topics = topic_model.reduce_outliers(docs, topics, strategy="distributions")
        topic_model.update_topics(docs, topics=topics, vectorizer_model=vectorizer)


    topic_info = topic_model.get_topic_info()
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "num_documents": len(docs),
        "num_topics": len(topic_info) - 1,
        "topics": [],
    }

    for _, row in topic_info.iterrows():
        topic_id = row["Topic"]
        if topic_id == -1:
            continue
        topic_words = topic_model.get_topic(topic_id)
        representative_docs = topic_model.get_representative_docs(topic_id)


        topic_meetings = []
        for i, t in enumerate(topics):
            if t == topic_id:
                topic_meetings.append(doc_metadata[i])

        result["topics"].append(
            {
                "topic_id": topic_id,
                "label": row.get("Name", f"Topic_{topic_id}"),
                "count": int(row["Count"]),
                "words": [{"word": w, "weight": round(s, 4)} for w, s in topic_words[:10]],
                "representative_docs": [d[:200] for d in (representative_docs or [])[:3]],
                "meetings": topic_meetings[:10],
            }
        )

    log.info(f"Topic modeling complete: {result['num_topics']} topics found")
    return result

































def _ner_collect_utterances(
    transcript: dict, min_chars: int = 10
) -> tuple[list[str], list[str], list[int], list[int]]:
    ""










    texts: list[str] = []
    speakers: list[str] = []
    utt_indices: list[int] = []
    leads: list[int] = []
    for u_idx, u in enumerate(transcript.get("utterances") or []):
        raw = u.get("content", "") or ""
        content = raw.strip()
        if len(content) < min_chars:
            continue
        texts.append(content)
        speakers.append(u.get("speaker") or "")
        utt_indices.append(u_idx)
        leads.append(len(raw) - len(raw.lstrip()))
    return texts, speakers, utt_indices, leads


def _ner_entity_row(
    pred: dict,
    transcript: dict,
    speaker: str,
    utterance_idx: int,
    lead: int,
) -> dict:
    ""





    start = pred.get("start")
    end = pred.get("end")
    return {
        "entity_text": pred["text"],
        "entity_type": pred["label"],
        "meeting_id": transcript["meeting_id"],
        "meeting_title": transcript["title"],
        "speaker": speaker,
        "date": transcript["date"],
        "source": transcript["source"],
        "confidence": round(pred["score"], 3),
        "char_start": None if start is None else start + lead,
        "char_end": None if end is None else end + lead,
        "utterance_idx": utterance_idx,
    }


def _ner_worker(args: tuple) -> list[dict]:
    ""
    from gliner import GLiNER

    worker_id, transcripts_chunk, verbose = args
    model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
    entity_labels = ["person", "organization", "location", "date", "product", "money"]
    entities = []
    _BATCH_SIZE = 16
    _CHUNK_SIZE = 256

    for t_idx, transcript in enumerate(transcripts_chunk):

        texts, speakers, utt_indices, leads = _ner_collect_utterances(transcript)

        if not texts:
            continue


        for chunk_start in range(0, len(texts), _CHUNK_SIZE):
            chunk_texts = texts[chunk_start : chunk_start + _CHUNK_SIZE]
            chunk_speakers = speakers[chunk_start : chunk_start + _CHUNK_SIZE]
            chunk_utt_indices = utt_indices[chunk_start : chunk_start + _CHUNK_SIZE]
            chunk_leads = leads[chunk_start : chunk_start + _CHUNK_SIZE]
            try:
                batch_results = model.inference(
                    chunk_texts,
                    entity_labels,
                    batch_size=_BATCH_SIZE,
                    threshold=0.5,
                )
                for i, preds in enumerate(batch_results):
                    for pred in preds:
                        entities.append(
                            _ner_entity_row(
                                pred,
                                transcript,
                                chunk_speakers[i],
                                chunk_utt_indices[i],
                                chunk_leads[i],
                            )
                        )
            except Exception as e:
                log.error(
                    f"[Worker {worker_id}] Error chunk {chunk_start}: {e}",
                )

        if (t_idx + 1) % 25 == 0:
            log.info(
                f"[Worker {worker_id}] NER processed {t_idx + 1}/{len(transcripts_chunk)}",
            )

    log.info(
        f"[Worker {worker_id}] Done: {len(entities)} entities from "
        f"{len(transcripts_chunk)} transcripts",
    )
    return entities


def _transcript_fingerprint(transcript: dict) -> str:
    ""
    text = " ".join(u.get("content", "") for u in transcript.get("utterances", []))
    sample = text[:4000]
    return hashlib.sha256(sample.encode("utf-8")).hexdigest()[:16]


def run_ner(transcripts: list[dict], verbose: bool = False, workers: int = 1) -> list[dict]:
    ""
    try:
        from gliner import GLiNER  # noqa: F401
    except ImportError:
        log.error("GLiNER not installed. Install with: pip install gliner")
        return []


    checkpoint_file = NLP_DIR / "ner-checkpoint.json"
    processed_ids: set[str] = set()
    content_hashes: dict[str, str] = {}
    existing_entities: list[dict] = []

    if checkpoint_file.exists():
        try:
            cp = json.loads(checkpoint_file.read_text())
            processed_ids = set(cp.get("processed_ids", []))
            content_hashes = cp.get("content_hashes", {})
            partial_file = NLP_DIR / "entities-partial.parquet"
            if partial_file.exists():
                df = pd.read_parquet(partial_file)
                existing_entities = df.to_dict("records")
            log.info(
                f"Resuming NER from checkpoint: {len(processed_ids)} transcripts done, "
                f"{len(existing_entities)} entities so far"
            )
        except Exception as e:
            log.warning(f"Could not load NER checkpoint: {e}")
            processed_ids = set()
            content_hashes = {}
            existing_entities = []

    if workers > 1:
        remaining = [
            t
            for t in transcripts
            if t["meeting_id"] not in processed_ids
            or _transcript_fingerprint(t) != content_hashes.get(t["meeting_id"])
        ]
        log.info(f"Parallel NER: {len(remaining)} remaining of {len(transcripts)} total")
        new_entities = _run_ner_parallel(remaining, verbose=verbose, workers=workers)
        return existing_entities + new_entities


    entities = existing_entities

    log.info("Loading GLiNER model...")
    model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")

    entity_labels = ["person", "organization", "location", "date", "product", "money"]

    for t_idx, transcript in enumerate(transcripts):
        fp = _transcript_fingerprint(transcript)
        if transcript["meeting_id"] in processed_ids and fp == content_hashes.get(
            transcript["meeting_id"]
        ):
            continue

        if transcript["meeting_id"] in processed_ids:
            entities = [e for e in entities if e.get("meeting_id") != transcript["meeting_id"]]



        texts, speakers, utt_indices, leads = _ner_collect_utterances(transcript)

        if texts:
            _BATCH_SIZE = 16
            _CHUNK_SIZE = 256
            for chunk_start in range(0, len(texts), _CHUNK_SIZE):
                chunk_texts = texts[chunk_start : chunk_start + _CHUNK_SIZE]
                chunk_speakers = speakers[chunk_start : chunk_start + _CHUNK_SIZE]
                chunk_utt_indices = utt_indices[chunk_start : chunk_start + _CHUNK_SIZE]
                chunk_leads = leads[chunk_start : chunk_start + _CHUNK_SIZE]
                try:
                    batch_results = model.inference(
                        chunk_texts,
                        entity_labels,
                        batch_size=_BATCH_SIZE,
                        threshold=0.5,
                    )
                    for i, preds in enumerate(batch_results):
                        for pred in preds:
                            entities.append(
                                _ner_entity_row(
                                    pred,
                                    transcript,
                                    chunk_speakers[i],
                                    chunk_utt_indices[i],
                                    chunk_leads[i],
                                )
                            )
                except Exception as e:
                    if verbose:
                        log.debug(f"GLiNER error on transcript {transcript['meeting_id']}: {e}")

        processed_ids.add(transcript["meeting_id"])
        content_hashes[transcript["meeting_id"]] = fp

        if (t_idx + 1) % 50 == 0:
            log.info(f"  NER processed {t_idx + 1}/{len(transcripts)} transcripts...")

        if len(processed_ids) % 100 == 0:
            _save_ner_checkpoint(checkpoint_file, processed_ids, entities, content_hashes)

    if checkpoint_file.exists():
        checkpoint_file.unlink()
    partial_file = NLP_DIR / "entities-partial.parquet"
    if partial_file.exists():
        partial_file.unlink()

    log.info(f"NER complete: {len(entities)} entities extracted")
    return entities


def _run_ner_parallel(
    transcripts: list[dict], verbose: bool = False, workers: int = 4
) -> list[dict]:
    ""
    import multiprocessing as mp

    log.info(f"Starting parallel NER with {workers} workers on {len(transcripts)} transcripts")


    chunks: list[list[dict]] = [[] for _ in range(workers)]
    for i, t in enumerate(transcripts):
        chunks[i % workers].append(t)

    for i, chunk in enumerate(chunks):
        utterance_count = sum(len(t["utterances"]) for t in chunk)
        log.info(f"  Worker {i}: {len(chunk)} transcripts, {utterance_count:,} utterances")

    worker_args = [(i, chunk, verbose) for i, chunk in enumerate(chunks)]

    with mp.Pool(processes=workers) as pool:
        results = pool.map(_ner_worker, worker_args)

    entities = []
    for r in results:
        entities.extend(r)

    log.info(f"NER complete: {len(entities)} entities extracted ({workers} workers)")
    return entities


def _save_ner_checkpoint(
    checkpoint_file: Path, processed_ids: set, entities: list, content_hashes: dict | None = None
):
    ""
    cp_data = {"processed_ids": list(processed_ids)}
    if content_hashes:
        cp_data["content_hashes"] = content_hashes
    safe_write_json(checkpoint_file, cp_data)
    if entities:
        df = pd.DataFrame(entities)
        partial_file = checkpoint_file.parent / "entities-partial.parquet"
        safe_write_parquet(df, partial_file, index=False)
    log.info(f"  NER checkpoint: {len(processed_ids)} transcripts, {len(entities)} entities")





def save_decisions(decisions: list[dict]):
    ""
    NLP_DIR.mkdir(parents=True, exist_ok=True)

    df_new = pd.DataFrame(decisions)
    if df_new.empty:
        log.info("No decisions to save")
        return

    if DECISIONS_FILE.exists():
        df_existing = pd.read_parquet(DECISIONS_FILE)

        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(
            subset=["meeting_id", "decision_text"], keep="last"
        )
    else:
        df_combined = df_new

    safe_write_parquet(df_combined, DECISIONS_FILE, index=False)
    log.info(f"Saved {len(df_combined)} decisions to {DECISIONS_FILE}")


def save_action_items(action_items: list[dict]):
    ""
    NLP_DIR.mkdir(parents=True, exist_ok=True)

    df_new = pd.DataFrame(action_items)
    if df_new.empty:
        log.info("No action items to save")
        return

    if ACTION_ITEMS_FILE.exists():
        df_existing = pd.read_parquet(ACTION_ITEMS_FILE)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["meeting_id", "action_text"], keep="last")
    else:
        df_combined = df_new

    safe_write_parquet(df_combined, ACTION_ITEMS_FILE, index=False)
    log.info(f"Saved {len(df_combined)} action items to {ACTION_ITEMS_FILE}")


def save_financial_mentions(financial_mentions: list[dict]):
    ""
    NLP_DIR.mkdir(parents=True, exist_ok=True)

    df_new = pd.DataFrame(financial_mentions)
    if df_new.empty:
        log.info("No financial mentions to save")
        return


    if "amount" in df_new.columns:
        df_new["amount"] = df_new["amount"].astype(str)

    if FINANCIAL_MENTIONS_FILE.exists():
        df_existing = pd.read_parquet(FINANCIAL_MENTIONS_FILE)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(
            subset=["meeting_id", "amount", "entity", "type"], keep="last"
        )
    else:
        df_combined = df_new

    safe_write_parquet(df_combined, FINANCIAL_MENTIONS_FILE, index=False)
    log.info(f"Saved {len(df_combined)} financial mentions to {FINANCIAL_MENTIONS_FILE}")


def save_topics(topics: dict):
    ""
    NLP_DIR.mkdir(parents=True, exist_ok=True)
    if not topics:
        log.info("No topics to save")
        return

    safe_write_json(TOPICS_FILE, topics)
    log.info(f"Saved {topics.get('num_topics', 0)} topics to {TOPICS_FILE}")


def filter_stop_entities(df: pd.DataFrame) -> pd.DataFrame:
    ""
    if df.empty:
        return df
    if "entity_text_normalized" not in df.columns:
        df["entity_text_normalized"] = (
            df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
        )
    before = len(df)
    mask = ~df["entity_text_normalized"].isin(STOP_ENTITIES)
    df = df[mask].copy()
    removed = before - len(df)
    if removed:
        log.info(f"Stop-entity filter: removed {removed} rows ({before} -> {len(df)})")
    return df


def filter_ambiguous_entities(df: pd.DataFrame) -> pd.DataFrame:
    ""
    if df.empty:
        return df
    if "entity_text_normalized" not in df.columns:
        df["entity_text_normalized"] = (
            df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
        )
    type_counts = df.groupby("entity_text_normalized")["entity_type"].nunique()
    ambiguous = set(type_counts[type_counts >= _MAX_ENTITY_TYPES].index)
    if not ambiguous:
        return df


    ambig_df = df[df["entity_text_normalized"].isin(ambiguous)]
    dominant = (
        ambig_df.groupby(["entity_text_normalized", "entity_type"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .drop_duplicates(subset=["entity_text_normalized"], keep="first")
        .set_index("entity_text_normalized")["entity_type"]
        .to_dict()
    )


    before = len(df)
    keep_mask = ~df["entity_text_normalized"].isin(ambiguous) | (
        df.apply(
            lambda r: r["entity_type"] == dominant.get(r["entity_text_normalized"]),
            axis=1,
        )
    )
    df = df[keep_mask].copy()
    removed = before - len(df)
    if removed:
        log.info(
            f"Ambiguity filter: {len(ambiguous)} entities had {_MAX_ENTITY_TYPES}+ types, "
            f"removed {removed} minority-type rows ({before} -> {len(df)})"
        )
    return df


def filter_short_entities(df: pd.DataFrame) -> pd.DataFrame:
    ""
    if df.empty:
        return df
    if "entity_text_normalized" not in df.columns:
        df["entity_text_normalized"] = (
            df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
        )
    before = len(df)
    lengths = df["entity_text_normalized"].str.len()
    mask = (lengths > 2) | df["entity_text_normalized"].str.lower().isin(SHORT_ENTITY_ALLOWLIST)
    df = df[mask].copy()
    removed = before - len(df)
    if removed:
        log.info(
            f"Short-entity filter: removed {removed} rows with 1-2 chars ({before} -> {len(df)})"
        )
    return df


def disambiguate_entity_types(df: pd.DataFrame) -> pd.DataFrame:
    ""






    if df.empty:
        return df
    if "entity_text_normalized" not in df.columns:
        df["entity_text_normalized"] = (
            df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
        )


    type_counts = df.groupby("entity_text_normalized")["entity_type"].nunique()
    multi_type = set(type_counts[type_counts >= 2].index)
    if not multi_type:
        return df


    freq = (
        df[df["entity_text_normalized"].isin(multi_type)]
        .groupby(["entity_text_normalized", "entity_type"])
        .size()
        .reset_index(name="count")
    )

    majority = freq.loc[freq.groupby("entity_text_normalized")["count"].idxmax()]
    majority_map = dict(zip(majority["entity_text_normalized"], majority["entity_type"]))


    before_types = df[df["entity_text_normalized"].isin(multi_type)]["entity_type"].nunique()
    mask = df["entity_text_normalized"].isin(multi_type)
    df.loc[mask, "entity_type"] = df.loc[mask, "entity_text_normalized"].map(majority_map)
    after_types = df[df["entity_text_normalized"].isin(multi_type)]["entity_type"].nunique()

    log.info(
        f"Majority-vote disambiguation: {len(multi_type)} entities had 2+ types, "
        f"reassigned to majority type (type diversity {before_types} -> {after_types})"
    )
    return df


def save_entities(entities: list[dict]):
    ""



    NLP_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(entities)
    if df.empty:
        log.info("No entities to save")
        return


    df["entity_text_normalized"] = (
        df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
    )

    if ENTITIES_FILE.exists():
        df_existing = pd.read_parquet(ENTITIES_FILE)
        if "entity_text_normalized" not in df_existing.columns:
            df_existing["entity_text_normalized"] = (
                df_existing["entity_text"]
                .str.lower()
                .str.strip()
                .str.replace(r"\s+", " ", regex=True)
            )
        df_combined = pd.concat([df_existing, df], ignore_index=True)
        df_combined = df_combined.drop_duplicates(
            subset=["entity_text_normalized", "entity_type", "meeting_id"], keep="last"
        )
    else:
        df_combined = df.drop_duplicates(
            subset=["entity_text_normalized", "entity_type", "meeting_id"], keep="last"
        )


    df_combined = filter_stop_entities(df_combined)
    df_combined = filter_short_entities(df_combined)
    df_combined = disambiguate_entity_types(df_combined)
    df_combined = filter_ambiguous_entities(df_combined)





    for col in ("char_start", "char_end", "utterance_idx"):
        if col in df_combined.columns:
            df_combined[col] = df_combined[col].astype("Int64")

    safe_write_parquet(df_combined, ENTITIES_FILE, index=False)
    log.info(f"Saved {len(df_combined)} entities to {ENTITIES_FILE}")





def normalize_ner(verbose: bool = False) -> None:
    ""






    from rapidfuzz import fuzz
    from rapidfuzz.process import cdist

    if not ENTITIES_FILE.exists():
        log.error(f"Entities file not found: {ENTITIES_FILE}")
        return

    df = pd.read_parquet(ENTITIES_FILE)
    log.info(f"Loaded {len(df)} raw entities")


    if "entity_text_normalized" not in df.columns:
        df["entity_text_normalized"] = (
            df["entity_text"].str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
        )


    df = filter_stop_entities(df)
    df = filter_short_entities(df)
    df = disambiguate_entity_types(df)
    df = filter_ambiguous_entities(df)







    _testo_pre_stt = df["entity_text"].copy()
    stt_fixed = 0
    for wrong, correct in STT_NAME_CORRECTIONS.items():
        mask = df["entity_text_normalized"] == wrong
        if mask.any():
            stt_fixed += mask.sum()
            df.loc[mask, "entity_text_normalized"] = correct
            df.loc[mask, "entity_text"] = correct.title()

    for wrong, correct in STT_NAME_CORRECTIONS.items():
        mask = df["entity_text_normalized"].str.contains(wrong, na=False, regex=False)
        if mask.any():
            stt_fixed += mask.sum()
            df.loc[mask, "entity_text_normalized"] = df.loc[
                mask, "entity_text_normalized"
            ].str.replace(wrong, correct, regex=False)
    if stt_fixed and verbose:
        log.info(f"  STT corrections applied: {stt_fixed} entities fixed")

    _riscritte = df["entity_text"] != _testo_pre_stt
    if _riscritte.any():
        for _col in ("char_start", "char_end", "utterance_idx"):
            if _col in df.columns:
                df[_col] = df[_col].astype("Int64")
                df.loc[_riscritte, _col] = pd.NA
        log.info(f"  anchor cleared on {int(_riscritte.sum())} rows rewritten by STT")


    df["canonical_text"] = df["entity_text"]

    for etype in df["entity_type"].unique():
        mask = df["entity_type"] == etype
        unique_texts = df.loc[mask, "entity_text_normalized"].unique().tolist()

        if len(unique_texts) <= 1:
            continue


        parent: dict[str, str] = {t: t for t in unique_texts}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x


        batch_size = 5000
        for i in range(0, len(unique_texts), batch_size):
            batch = unique_texts[i : i + batch_size]
            scores = cdist(batch, batch, scorer=fuzz.ratio, score_cutoff=90)
            for r in range(len(batch)):
                for c in range(r + 1, len(batch)):
                    if scores[r][c] >= 90:
                        ra, ca = find(batch[r]), find(batch[c])
                        if ra != ca:
                            parent[ca] = ra


        clusters: dict[str, list[str]] = {}
        for t in unique_texts:
            root = find(t)
            clusters.setdefault(root, []).append(t)


        canon_map: dict[str, str] = {}
        for members in clusters.values():
            longest = max(members, key=len)

            orig = df.loc[(mask) & (df["entity_text_normalized"] == longest), "entity_text"].iloc[0]
            for m in members:
                canon_map[m] = orig

        df.loc[mask, "canonical_text"] = df.loc[mask, "entity_text_normalized"].map(canon_map)

        merged_count = sum(1 for v in clusters.values() if len(v) > 1)
        if merged_count and verbose:
            log.info(f"  {etype}: {len(unique_texts)} unique -> {len(clusters)} clusters")


    contacts_file = ENRICHED_DIR / "contacts-merged.parquet"
    df["resolved_person_id"] = None

    if contacts_file.exists():
        contacts = pd.read_parquet(contacts_file, columns=["name", "person_id"])
        contacts = contacts.dropna(subset=["name", "person_id"])
        contacts["name_norm"] = contacts["name"].str.lower().str.strip()


        name_to_pid = dict(zip(contacts["name_norm"], contacts["person_id"]))
        person_mask = df["entity_type"] == "person"
        df.loc[person_mask, "resolved_person_id"] = df.loc[
            person_mask, "entity_text_normalized"
        ].map(name_to_pid)


        unresolved = df[person_mask & df["resolved_person_id"].isna()]
        if len(unresolved) > 0:
            unresolved_names = unresolved["entity_text_normalized"].unique().tolist()
            contact_names = contacts["name_norm"].tolist()
            contact_pids = contacts["person_id"].tolist()

            fuzzy_map: dict[str, str] = {}
            for name in unresolved_names:
                best_score = 0
                best_pid = None
                for cn, cp in zip(contact_names, contact_pids):
                    score = fuzz.token_sort_ratio(name, cn)
                    if score >= 90 and score > best_score:
                        best_score = score
                        best_pid = cp
                if best_pid:
                    fuzzy_map[name] = best_pid

            if fuzzy_map:
                still_unresolved = df[person_mask & df["resolved_person_id"].isna()]
                df.loc[still_unresolved.index, "resolved_person_id"] = still_unresolved[
                    "entity_text_normalized"
                ].map(fuzzy_map)

        resolved = df[person_mask & df["resolved_person_id"].notna()]
        log.info(
            f"PERSON resolution: {len(resolved)}/{person_mask.sum()} resolved "
            f"({len(resolved) / max(1, person_mask.sum()) * 100:.0f}%)"
        )
    else:
        log.warning(f"Contacts file not found: {contacts_file}")


    companies_file = ATTIO_DIR / "companies.parquet"
    df["resolved_org_id"] = None

    if companies_file.exists():
        companies = pd.read_parquet(companies_file)
        name_col = "name" if "name" in companies.columns else companies.columns[0]
        id_col = "id" if "id" in companies.columns else "record_id"

        if id_col in companies.columns:
            companies = companies.dropna(subset=[name_col])
            companies["name_norm"] = companies[name_col].str.lower().str.strip()
            org_name_to_id = dict(zip(companies["name_norm"], companies[id_col]))

            org_mask = df["entity_type"] == "organization"
            df.loc[org_mask, "resolved_org_id"] = df.loc[org_mask, "entity_text_normalized"].map(
                org_name_to_id
            )


            unresolved_orgs = df[org_mask & df["resolved_org_id"].isna()]
            if len(unresolved_orgs) > 0:
                unresolved_org_names = unresolved_orgs["entity_text_normalized"].unique().tolist()
                company_names = companies["name_norm"].tolist()
                company_ids = companies[id_col].tolist()

                fuzzy_org_map: dict[str, str] = {}
                for name in unresolved_org_names:
                    best_score = 0
                    best_id = None
                    for cn, cid in zip(company_names, company_ids):
                        score = fuzz.token_sort_ratio(name, cn)
                        if score >= 85 and score > best_score:
                            best_score = score
                            best_id = cid
                    if best_id:
                        fuzzy_org_map[name] = best_id

                if fuzzy_org_map:
                    still_unresolved = df[org_mask & df["resolved_org_id"].isna()]
                    df.loc[still_unresolved.index, "resolved_org_id"] = still_unresolved[
                        "entity_text_normalized"
                    ].map(fuzzy_org_map)

            resolved_orgs = df[org_mask & df["resolved_org_id"].notna()]
            log.info(
                f"ORG resolution: {len(resolved_orgs)}/{org_mask.sum()} resolved "
                f"({len(resolved_orgs) / max(1, org_mask.sum()) * 100:.0f}%)"
            )
    else:
        log.warning(f"Companies file not found: {companies_file}")


    before = len(df)
    df = df.drop_duplicates(subset=["canonical_text", "entity_type", "meeting_id"], keep="first")
    log.info(f"Dedup: {before} -> {len(df)} entities ({before - len(df)} removed)")

    safe_write_parquet(df, ENTITIES_FILE, index=False)
    log.info(f"Saved normalized entities to {ENTITIES_FILE}")





def load_email_threads(max_threads: int = 0) -> list[dict]:
    ""



    threads_file = ENRICHED_DIR / "threads.parquet"
    if not threads_file.exists():
        log.error(f"Threads file not found: {threads_file}")
        return []

    df = pd.read_parquet(threads_file)
    log.info(f"Loaded {len(df)} email threads")

    docs = []
    for _, row in df.iterrows():
        body = row.get("body") or row.get("text") or row.get("snippet") or ""
        if len(str(body)) < 50:
            continue

        subject = row.get("subject", "")
        date_val = row.get("date", "")
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10] if date_val else ""

        participants = []
        for col in ["from_email", "to", "cc"]:
            val = row.get(col)
            if val and str(val) != "nan":
                participants.append(str(val))

        docs.append(
            {
                "doc_id": row.get("thread_id") or row.get("message_id") or f"email_{_}",
                "text": f"Subject: {subject}\n\n{body}",
                "date": date_str,
                "participants": participants,
                "subject": subject,
                "source": "email",
            }
        )

        if max_threads and len(docs) >= max_threads:
            break

    log.info(f"Prepared {len(docs)} email threads for NLP")
    return docs





SUMMARY_SYSTEM_PROMPT = """You are an expert analyst of business meetings.
Write a concise summary (200-300 words) of the meeting.

The summary must include:
1. Main topics discussed
2. Decisions made
3. Agreed actions (who does what)
4. Next steps

Respond in the same language as the transcript. Be direct and concrete."""

SUMMARY_USER_PROMPT = """Meeting: {title}
Date: {date}
Participants: {participants}

Transcript:
{text}

Write the summary."""


def run_summarization(
    transcripts: list[dict],
    verbose: bool = False,
) -> list[dict]:
    ""



    summaries_cache_dir = NLP_DIR / "summary-responses"
    summaries_cache_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    skipped = 0
    errors = 0

    for t_idx, transcript in enumerate(transcripts):
        cache_file = summaries_cache_dir / f"{transcript['source']}_{transcript['meeting_id']}.txt"


        if cache_file.exists():
            summary_text = cache_file.read_text().strip()
            if summary_text:
                summaries.append(
                    {
                        "meeting_id": transcript["meeting_id"],
                        "meeting_title": transcript["title"],
                        "date": transcript["date"],
                        "source": transcript["source"],
                        "summary": summary_text,
                    }
                )
                continue

        full_text = get_full_text(transcript)
        if len(full_text) < 200:
            skipped += 1
            continue


        speakers = set()
        for u in transcript["utterances"]:
            s = u.get("speaker")
            if s:
                speakers.add(s)

        participants_str = ", ".join(sorted(speakers)) if speakers else "N/A"


        chunks = chunk_document_semantic(full_text, max_chars=80_000, overlap_chars=2000)

        try:
            if len(chunks) == 1:

                prompt = SUMMARY_USER_PROMPT.format(
                    title=transcript["title"],
                    date=transcript["date"],
                    participants=participants_str,
                    text=chunks[0].text,
                )
                response = call_claude(
                    prompt=prompt,
                    system=SUMMARY_SYSTEM_PROMPT,
                    model=HAIKU_MODEL,
                    max_tokens=1024,
                    temperature=0.2,
                    provider=_PROVIDER,
                )
            else:

                chunk_summaries = []
                for chunk in chunks:
                    chunk_prompt = SUMMARY_USER_PROMPT.format(
                        title=f"{transcript['title']} (part {chunk.chunk_idx + 1}/{chunk.total_chunks})",
                        date=transcript["date"],
                        participants=participants_str,
                        text=chunk.text,
                    )
                    chunk_resp = call_claude(
                        prompt=chunk_prompt,
                        system=SUMMARY_SYSTEM_PROMPT,
                        model=HAIKU_MODEL,
                        max_tokens=1024,
                        temperature=0.2,
                        provider=_PROVIDER,
                    )
                    chunk_summaries.append(chunk_resp)
                    time.sleep(0.2)


                meta_prompt = (
                    f"Meeting: {transcript['title']}\nDate: {transcript['date']}\n"
                    f"Participants: {participants_str}\n\n"
                    f"Below are summaries of {len(chunks)} parts of this meeting. "
                    f"Merge them into ONE cohesive summary:\n\n" + "\n---\n".join(chunk_summaries)
                )
                response = call_claude(
                    prompt=meta_prompt,
                    system=SUMMARY_SYSTEM_PROMPT,
                    model=HAIKU_MODEL,
                    max_tokens=1024,
                    temperature=0.2,
                    provider=_PROVIDER,
                )

            cache_file.write_text(response)
            summaries.append(
                {
                    "meeting_id": transcript["meeting_id"],
                    "meeting_title": transcript["title"],
                    "date": transcript["date"],
                    "source": transcript["source"],
                    "summary": response,
                }
            )
        except Exception as e:
            log.error(f"Summarization error for {transcript['title'][:50]}: {e}")
            errors += 1

        if (t_idx + 1) % 10 == 0:
            log.info(f"  Summarized {t_idx + 1}/{len(transcripts)}...")

        time.sleep(0.3)

    log.info(
        f"Summarization complete: {len(summaries)} summaries, {skipped} skipped, {errors} errors"
    )
    return summaries


def save_summaries(summaries: list[dict]) -> None:
    ""
    if not summaries:
        log.info("No summaries to save")
        return

    NLP_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(summaries)
    out_file = NLP_DIR / "summaries.parquet"

    if out_file.exists():
        df_existing = pd.read_parquet(out_file)
        df = pd.concat([df_existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["meeting_id"], keep="last")

    safe_write_parquet(df, out_file, index=False)
    log.info(f"Saved {len(df)} summaries to {out_file}")





def _richieste_batch(uncached: list[dict], model: str):
    ""


    from xs_batch_api import BatchRequest, id_stabile

    seen_ids: set[str] = set()

    for t in uncached:
        full_text = get_full_text(t)
        if len(full_text) < 100:
            continue

        chunks = chunk_document_semantic(full_text, max_chars=100_000, overlap_chars=3000)

        for chunk in chunks:

            if len(chunks) > 1:
                chunk_file = (
                    BATCH_RESPONSES_DIR
                    / f"{t['source']}_{t['meeting_id']}_chunk_{chunk.chunk_idx}.json"
                )
                if chunk_file.exists():
                    continue


            custom_id = id_stabile(t["source"], str(t["meeting_id"]), chunk.chunk_idx)
            doppio = 1
            while custom_id in seen_ids:
                custom_id = id_stabile(t["source"], f"{t['meeting_id']}#{doppio}", chunk.chunk_idx)
                doppio += 1
            seen_ids.add(custom_id)
            prompt = EXTRACTION_USER_PROMPT.format(
                title=t["title"],
                date=t["date"],
                source=t["source"],
                text=chunk.text,
            )
            yield (
                BatchRequest(
                    custom_id=custom_id,
                    user_content=prompt,
                    system_prompt=EXTRACTION_SYSTEM_PROMPT,
                    model=model,
                    max_tokens=4096,
                    temperature=0.1,
                ),
                t,
                chunk.chunk_idx,
                len(chunks),
            )


def run_batch_api_extraction(
    transcripts: list[dict],
    model: str = "claude-sonnet-4-5-20250929",
) -> tuple[list[dict], list[dict], list[dict]]:
    ""




    from xs_batch_api import chiudi_stato, run_batch_pipeline

    decisions = []
    action_items = []
    financial_mentions = []


    uncached = []
    for t in transcripts:
        response_file = BATCH_RESPONSES_DIR / f"{t['source']}_{t['meeting_id']}.json"
        if response_file.exists():
            try:
                parsed = json.loads(response_file.read_text())
                _collect_claude_results(parsed, t, decisions, action_items, financial_mentions)
                continue
            except (json.JSONDecodeError, OSError):
                pass
        uncached.append(t)

    log.info(
        f"Batch API: {len(transcripts)} total, {len(transcripts) - len(uncached)} cached, {len(uncached)} to process"
    )

    if not uncached:
        log.info("All transcripts cached — nothing to submit")
        return decisions, action_items, financial_mentions


    batch_requests = []
    request_map: dict[str, tuple[dict, int, int]] = {}
    for richiesta, t, chunk_idx, n_chunks in _richieste_batch(uncached, model):
        batch_requests.append(richiesta)
        request_map[richiesta.custom_id] = (t, chunk_idx, n_chunks)

    log.info(f"Built {len(batch_requests)} batch requests for {len(uncached)} transcripts")

    if not batch_requests:
        return decisions, action_items, financial_mentions


    results = run_batch_pipeline(
        batch_requests,
        label="extract",
        poll_interval=30,
        state_dir=BATCH_RESPONSES_DIR,
        tieni_stato=True,
    )


    transcript_chunks: dict[str, dict[int, dict]] = {}
    transcript_lookup: dict[str, dict] = {}
    for custom_id, result in results.items():
        if custom_id not in request_map:
            continue
        t, chunk_idx, total_chunks = request_map[custom_id]
        key = f"{t['source']}/{t['meeting_id']}"
        if key not in transcript_chunks:
            transcript_chunks[key] = {}
        transcript_chunks[key][chunk_idx] = result
        transcript_lookup[key] = t

    BATCH_RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0
    errors = 0

    for key, chunk_results_map in transcript_chunks.items():
        t = transcript_lookup.get(key)
        if not t:
            continue

        parsed_chunks = []
        for chunk_idx in sorted(chunk_results_map.keys()):
            result = chunk_results_map[chunk_idx]
            if result.get("error"):
                errors += 1
                continue
            parsed = _parse_claude_response(result.get("text", ""))
            if parsed:

                if len(chunk_results_map) > 1:
                    chunk_file = (
                        BATCH_RESPONSES_DIR
                        / f"{t['source']}_{t['meeting_id']}_chunk_{chunk_idx}.json"
                    )
                    chunk_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
                parsed_chunks.append(parsed)

        if not parsed_chunks:
            errors += 1
            continue


        if len(parsed_chunks) > 1:
            merged = merge_extraction_results(parsed_chunks)
        else:
            merged = parsed_chunks[0]


        response_file = BATCH_RESPONSES_DIR / f"{t['source']}_{t['meeting_id']}.json"
        response_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

        _collect_claude_results(merged, t, decisions, action_items, financial_mentions)
        processed += 1


    chiudi_stato("extract", BATCH_RESPONSES_DIR)
    log.info(
        f"Batch API complete: {processed} transcripts, {errors} errors, "
        f"{len(decisions)} decisions, {len(action_items)} actions, "
        f"{len(financial_mentions)} financial mentions"
    )
    return decisions, action_items, financial_mentions





def _chiave_checkpoint(args) -> str:
    ""


    return "l3-extract-ner" if getattr(args, "ner_only", False) else "l3-extract"


def main():
    parser = argparse.ArgumentParser(description="NLP extraction pipeline for meeting transcripts")
    parser.add_argument(
        "--regex-only", action="store_true", help="Only run regex extraction (step 1, free)"
    )
    parser.add_argument(
        "--batch", action="store_true", help="Run sync batch extraction with ThreadPool (step 2)"
    )
    parser.add_argument(
        "--batch-api",
        action="store_true",
        help="Use Anthropic Message Batches API (50%% discount, ~1h, Sonnet quality)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model override (default: Haiku for --batch, Sonnet for --batch-api)",
    )
    parser.add_argument("--topics", action="store_true", help="Run BERTopic + GLiNER (step 3)")
    parser.add_argument("--topics-only", action="store_true", help="Run only BERTopic (no GLiNER)")
    parser.add_argument("--ner-only", action="store_true", help="Run only GLiNER NER (no BERTopic)")
    parser.add_argument(
        "--normalize-ner",
        action="store_true",
        help="Normalize NER: fuzzy dedup + resolve against contacts/companies",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize meeting transcripts with Claude Haiku",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count transcripts and estimate cost"
    )
    parser.add_argument(
        "--source",
        choices=ALL_SOURCES,
        action="append",
        help="Process specific source(s). Can be repeated: --source email --source slack",
    )
    parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        metavar="SRC",
        help="Exclude a source from the run (repeatable): "
        "e.g. --exclude-source gdrive --exclude-source plaud",
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Process ALL text sources (not just plaud+tactiq)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for batch mode (default: 1, max recommended: 8)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
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


    global _PROVIDER
    _PROVIDER = args.provider


    if not any(
        [
            args.regex_only,
            args.batch,
            args.batch_api,
            args.topics,
            args.topics_only,
            args.ner_only,
            args.normalize_ner,
            args.summarize,
            args.dry_run,
        ]
    ):
        parser.print_help()
        print(
            "\nSpecify at least one step: --regex-only, --batch, --topics, "
            "--topics-only, --ner-only, --normalize-ner, --summarize, or --dry-run"
        )
        sys.exit(1)

    setup_logging(verbose=args.verbose, name="sbk-l3-extract")

    if args.incremental:
        from sbk_config import VOICE_MEMOS_PROCESSED_DIR as _VM_DIR
        from sbk_config import check_inputs_changed, mark_last_run

        _extract_inputs = [
            PLAUD_DIR,
            TACTIQ_DIR,
            SLACK_DIR,
            DATA_ROOT / "slack" / "conversations",
            WHATSAPP_DIR,
            CHATGPT_DIR,
            NOTION_DIR,
            GDRIVE_DIR,
            ATTIO_DIR / "processed",
            *ATTIO_TRANSCRIPTS_DIRS,
            _VM_DIR,



            ENRICHED_DIR / "processed",
            DATA_ROOT / "slack" / "dm",
        ]



        if not check_inputs_changed(_chiave_checkpoint(args), _extract_inputs):
            log.info("Incremental: inputs unchanged — skipping")
            if args.dry_run:


                print("\nInputs unchanged since the last real run: the stage would be skipped.")
                print("Batch progress: 0/0 processed, 0 remaining")
                print("  Est. batch cost: $0.00 (inputs unchanged, nothing to send)")
                return
            mark_last_run(_chiave_checkpoint(args))
            return


    if args.normalize_ner:
        log.info("=== NER normalization ===")
        normalize_ner(verbose=args.verbose)
        if not any(
            [
                args.regex_only,
                args.batch,
                args.topics,
                args.topics_only,
                args.ner_only,
                args.summarize,
                args.dry_run,
            ]
        ):
            return


    _excl = set(args.exclude_source or [])
    if args.all_sources:
        sources_to_load = ALL_SOURCES
    elif args.source:
        sources_to_load = args.source
    else:

        sources_to_load = ["plaud", "tactiq"]
    if _excl:
        sources_to_load = [x for x in sources_to_load if x not in _excl]
        log.info(f"Sources EXCLUDED from run: {sorted(_excl)} -> {len(sources_to_load)} remaining")


    transcripts = load_sources(sources_to_load)

    if not transcripts:
        log.error(f"No documents found for sources: {sources_to_load}")
        sys.exit(1)


    if not args.no_email_filter and any(t.get("source") == "email" for t in transcripts):
        email_docs = [t for t in transcripts if t.get("source") == "email"]
        other_docs = [t for t in transcripts if t.get("source") != "email"]
        kept_emails, filter_stats = email_prefilter(email_docs)
        log.info(
            f"Email pre-filter: {filter_stats['total']} -> {filter_stats['kept']} "
            f"({filter_stats['removal_pct']}% removed)"
        )
        transcripts = other_docs + kept_emails


    if args.smart_route:
        router = SmartRouter(
            quality_provider=args.quality_provider,
            economy_provider=args.economy_provider,
        )
        for t in transcripts:

            doc_for_routing = {
                "source": t.get("source", ""),
                "title": t.get("title", ""),
                "text": " ".join(u.get("content", "") for u in t.get("utterances", []))[:1000],
                "participants": t.get("participants", ""),
            }
            t["_provider"] = router.route(doc_for_routing)
        router.log_stats()


    source_counts = {}
    for t in transcripts:
        source_counts[t["source"]] = source_counts.get(t["source"], 0) + 1
    log.info(f"Total documents loaded: {len(transcripts)} from {len(source_counts)} sources")
    for src, cnt in sorted(source_counts.items()):
        log.info(f"  {src}: {cnt}")


    if args.dry_run:
        print(f"\nDocuments: {len(transcripts)}")
        for src, cnt in sorted(source_counts.items()):
            print(f"  {src}: {cnt}")

        total_utterances = sum(len(t["utterances"]) for t in transcripts)
        total_chars = sum(
            sum(len(u.get("content", "")) for u in t["utterances"]) for t in transcripts
        )
        print(f"\nTotal utterances/chunks: {total_utterances:,}")
        print(f"Total chars: {total_chars:,}")

        dry_model = (args.model or "claude-sonnet-4-5-20250929") if args.batch_api else None
        if args.batch_api:



            from xs_batch_api import stima_costo_richieste, uscita_media

            senza_risposta = [
                t
                for t in transcripts
                if not (BATCH_RESPONSES_DIR / f"{t['source']}_{t['meeting_id']}.json").exists()
            ]
            da_leggere: set[tuple[str, str]] = set()

            def _richieste():
                for richiesta, t, _pezzo, _pezzi in _richieste_batch(senza_risposta, dry_model):
                    da_leggere.add((t["source"], str(t["meeting_id"])))
                    yield richiesta


            media = uscita_media(BATCH_RESPONSES_DIR)
            stima = stima_costo_richieste(_richieste(), uscita_token=media)
            print(f"\nBatch extraction estimate (model={dry_model}):")
            print(f"  Requests:      {stima['richieste']:,}")
            print(f"  Input tokens:  ~{stima['est_input_tokens']:,}")
            print(
                f"  Output tokens: ~{stima['est_output_tokens']:,} "
                + (
                    f"({media} per request, from the answers already saved)"
                    if media
                    else "(a quarter of max_tokens)"
                )
            )
            print(f"  Estimated cost: ${stima['est_cost_usd_sync']:.2f}")
            print(
                f"  Est. batch cost: ${stima['est_cost_usd_batch']:.2f} (Batch API, 50% discount)"
            )
            print(
                f"\nBatch progress: {len(transcripts) - len(da_leggere)}/{len(transcripts)} processed, "
                f"{len(da_leggere)} remaining"
            )
        else:
            estimate = estimate_batch_cost(transcripts, provider=args.provider)
            print(f"\nBatch extraction estimate (provider={args.provider}):")
            print(f"  Input tokens:  ~{estimate['est_input_tokens']:,}")
            print(f"  Output tokens: ~{estimate['est_output_tokens']:,}")
            print(f"  Estimated cost: ${estimate['est_cost_usd']:.2f}")


        print("\nExisting outputs:")
        for name, path in [
            ("Decisions", DECISIONS_FILE),
            ("Action Items", ACTION_ITEMS_FILE),
            ("Financial Mentions", FINANCIAL_MENTIONS_FILE),
            ("Topics", TOPICS_FILE),
            ("Entities", ENTITIES_FILE),
        ]:
            if path.exists():
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)

                    if "source" in df.columns:
                        src_breakdown = df["source"].value_counts().to_dict()
                        print(f"  {name}: {len(df)} rows {src_breakdown}")
                    else:
                        print(f"  {name}: {len(df)} rows")
                else:
                    data = json.loads(path.read_text())
                    print(f"  {name}: {len(data.get('topics', []))} topics")
            else:
                print(f"  {name}: not yet created")

        return


    if args.regex_only:
        log.info("=== Step 1: Regex extraction ===")

        meeting_docs = [t for t in transcripts if t["source"] in MEETING_SOURCES]
        if meeting_docs:
            log.info(
                f"Running regex on {len(meeting_docs)} meeting-like docs "
                f"(skipping {len(transcripts) - len(meeting_docs)} non-meeting docs)"
            )
            decisions, action_items = extract_regex(meeting_docs, verbose=args.verbose)
            save_decisions(decisions)
            save_action_items(action_items)
            log.info("Regex extraction complete:")
            log.info(f"  Decisions:    {len(decisions)}")
            log.info(f"  Action items: {len(action_items)}")
        else:
            log.info("No meeting-like sources in selection, skipping regex extraction")


    if args.batch_api:
        model = args.model or "claude-sonnet-4-5-20250929"
        log.info(f"=== Step 2: Batch API extraction ({model}) ===")
        decisions, action_items, financial_mentions = run_batch_api_extraction(
            transcripts, model=model
        )
        save_decisions(decisions)
        save_action_items(action_items)
        save_financial_mentions(financial_mentions)
        log.info("Batch API extraction complete:")
        log.info(f"  Decisions:           {len(decisions)}")
        log.info(f"  Action items:        {len(action_items)}")
        log.info(f"  Financial mentions:  {len(financial_mentions)}")
    elif args.batch:
        log.info(f"=== Step 2: Sync batch extraction (provider={args.provider}) ===")
        estimate = estimate_batch_cost(transcripts, provider=args.provider)
        log.info(f"Estimated cost: ${estimate['est_cost_usd']:.2f}")

        decisions, action_items, financial_mentions = run_batch_extraction(
            transcripts, verbose=args.verbose, workers=args.workers
        )
        save_decisions(decisions)
        save_action_items(action_items)
        save_financial_mentions(financial_mentions)
        log.info("Claude extraction complete:")
        log.info(f"  Decisions:           {len(decisions)}")
        log.info(f"  Action items:        {len(action_items)}")
        log.info(f"  Financial mentions:  {len(financial_mentions)}")


    if args.topics or args.topics_only:
        log.info("=== Step 3a: Topic modeling ===")
        topics = run_topic_modeling(transcripts, verbose=args.verbose)
        save_topics(topics)

    if args.topics or args.ner_only:
        log.info("=== Step 3b: NER (GLiNER) ===")
        entities = run_ner(transcripts, verbose=args.verbose, workers=args.workers)
        save_entities(entities)

        log.info(f"NER complete: {len(entities)} entities")


    if args.summarize:
        log.info("=== Step 4: Meeting summarization (Claude Haiku) ===")
        summaries = run_summarization(transcripts, verbose=args.verbose)
        save_summaries(summaries)
        log.info(f"Summarization complete: {len(summaries)} summaries")

    if not args.dry_run:
        from sbk_config import VOICE_MEMOS_PROCESSED_DIR as _VM_DIR
        from sbk_config import mark_last_run, save_input_checkpoint

        _extract_inputs = [
            PLAUD_DIR,
            TACTIQ_DIR,
            SLACK_DIR,
            DATA_ROOT / "slack" / "conversations",
            WHATSAPP_DIR,
            CHATGPT_DIR,
            NOTION_DIR,
            GDRIVE_DIR,
            ATTIO_DIR / "processed",
            *ATTIO_TRANSCRIPTS_DIRS,
            _VM_DIR,



            ENRICHED_DIR / "processed",
            DATA_ROOT / "slack" / "dm",
        ]
        save_input_checkpoint(_chiave_checkpoint(args), _extract_inputs)
        mark_last_run(_chiave_checkpoint(args))


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-extract", source="l3-extract", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
