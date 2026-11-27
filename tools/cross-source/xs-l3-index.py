#!/usr/bin/env python3
"""Vector index builder: splits every source (email threads, transcripts, Slack, WhatsApp, documents, attachments,
CRM notes, ClickUp, DocuSign, ChatGPT, voice memos...) into chunks, embeds them locally and stores them in the
LanceDB table the search uses; --incremental indexes only what changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import (
    SBKData,
    build_transcript_selection_index,
    setup_logging,
)

from sbk_config import (
    OWNER_LABEL,
    ATTIO_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    ATTIO_TRANSCRIPTS_DIRS,
    CALENDARS_DIR,
    DATA_ROOT,
    EMAILS_DIR,
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    NETWORK_DIR,
    NOTES_DIR,
    NOTION_DIR,
    PLAUD_DIR,
    SBK_ANALYSES_DIR,
    SESSIONS_TEXT_DIR,
    SLACK_CONVERSATIONS_DIR,
    VECTOR_DB_DIR,
    VOICE_MEMOS_TRANSCRIPTS_DIR,
    WHATSAPP_CHATS_DIR,
    WHATSAPP_DOCUMENTS_DIR,
    acquire_pid_lock,
    attio_transcript_files,
    release_pid_lock,
    safe_write_json,
)

log = logging.getLogger("sbk-l3-index")



CHECKPOINT_FILE = VECTOR_DB_DIR / "index-checkpoint.json"
TABLE_NAME = "sbk_chunks"


TABLE_NAME_BGE = "sbk_chunks_bge"
CHECKPOINT_FILE_BGE = VECTOR_DB_DIR / "index-checkpoint-bge.json"


TABLE_NAME_QWEN = "sbk_chunks_qwen"
CHECKPOINT_FILE_QWEN = VECTOR_DB_DIR / "index-checkpoint-qwen.json"


MODEL_INFO_FILE = VECTOR_DB_DIR / "model-info.json"



FONTI_NON_INDICIZZATE = VECTOR_DB_DIR / "fonti-non-indicizzate.json"





EMBEDDING_MODELS = [
    "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ",
    "BAAI/bge-m3",
    "paraphrase-multilingual-MiniLM-L12-v2",
]


ALL_SOURCES = [
    "network",
    "notion",
    "raw",
    "voice_memo",
    "domain",
    "gdrive",
    "attio_notes",

    "docusign",
    "clickup",
    "session",
    "whatsapp",
    "wa_document",
    "wa_photo_ocr",
    "email_attachment",
    "calendar",
    "attio_call",
    "chatgpt",
    "slack_dm",
    "slack",
    "plaud",
    "knowledge",
    "email",

    "tactiq",
]



SOURCE_DIRS: dict[str, list[Path]] = {
    "email": [EMAILS_DIR],
    "plaud": [PLAUD_DIR],
    "tactiq": [DATA_ROOT / "tactiq" / "raw"],
    "slack": [SLACK_CONVERSATIONS_DIR],
    "slack_dm": [DATA_ROOT / "slack" / "dm"],
    "notion": [NOTION_DIR],
    "network": [],
    "raw": [],
    "whatsapp": [WHATSAPP_CHATS_DIR],
    "wa_document": [WHATSAPP_DOCUMENTS_DIR],
    "wa_photo_ocr": [DATA_ROOT / "whatsapp" / "photos"],

    "email_attachment": [
        DATA_ROOT / "emails" / "extracted-attachments",
        DATA_ROOT / "emails" / "processed",
    ],
    "attio_notes": [ATTIO_DIR],
    "clickup": [DATA_ROOT / "clickup" / "processed"],
    "docusign": [DATA_ROOT / "docusign" / "processed"],
    "attio_call": ATTIO_TRANSCRIPTS_DIRS,
    "chatgpt": [DATA_ROOT / "chatgpt"],
    "voice_memo": [VOICE_MEMOS_TRANSCRIPTS_DIR],



    "gdrive": [DATA_ROOT / "gdrive" / "processed"],
    "domain": [SBK_ANALYSES_DIR],
    "calendar": [CALENDARS_DIR],
    "knowledge": [KNOWLEDGE_ENTITIES_DIR],
    "session": [SESSIONS_TEXT_DIR],
}


SOURCE_DIRS["network"] = [NETWORK_DIR]
SOURCE_DIRS["raw"] = [NOTES_DIR]


def get_source_mtime(source: str) -> float:
    ""





    dirs = SOURCE_DIRS.get(source, [])
    max_mtime = 0.0

    for d in dirs:
        if not d or not d.exists():
            continue


        patterns = ["*.parquet", "*.json", "*.md", "*.txt"]
        for pattern in patterns:
            for f in d.rglob(pattern):
                try:
                    mt = f.stat().st_mtime
                    if mt > max_mtime:
                        max_mtime = mt
                except OSError:
                    continue

    return max_mtime



TOKEN_FACTOR = 1.3





def estimate_tokens(text: str) -> int:
    ""
    return int(len(text.split()) * TOKEN_FACTOR)


def _chunk_text_sliding_window(
    text: str,
    max_tokens: int = 500,
    overlap_tokens: int = 100,
    min_tokens: int = 15,
) -> list[str]:
    ""










    if not text or not text.strip():
        return []

    words = text.split()
    max_words = int(max_tokens / TOKEN_FACTOR)
    overlap_words = int(overlap_tokens / TOKEN_FACTOR)
    min_words = int(min_tokens / TOKEN_FACTOR)
    stride = max(1, max_words - overlap_words)

    if len(words) < min_words:
        return []


    if len(words) <= max_words:
        return [text.strip()]

    chunks = []
    for start in range(0, len(words), stride):
        window = words[start : start + max_words]
        if len(window) < min_words:
            break
        chunks.append(" ".join(window))

    return chunks







_PII_RESTRICTED = frozenset({"clinical", "personio", "whoop", "docusign", "apple_health"})
_PII_PUBLIC = frozenset({"network", "raw", "domain"})


def _get_pii_level(source_type: str) -> int:
    ""
    if source_type in _PII_RESTRICTED:
        return 2
    if source_type in _PII_PUBLIC:
        return 0
    return 1



SCHEMA_VERSION = 2
CHUNKER_VERSION = "v2"
DEFAULT_EMBEDDING_MODEL = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"


class Chunk:
    ""

    __slots__ = (
        "id",
        "text",
        "context",
        "context_summary",
        "source_type",
        "source_id",
        "date",
        "indexed_at",
        "participants",
        "person_ids",
        "embedding_model",
        "pii_level",
        "lang",
        "content_hash",
        "chunker_version",
        "schema_version",
    )

    def __init__(
        self,
        text: str,
        context: str,
        source_type: str,
        source_id: str,
        date: str = "",
        participants: str = "",
        person_ids: str = "",
        *,
        context_summary: str = "",
        lang: str = "mixed",
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ):
        self.text = text.strip()
        self.context = context.strip()
        self.context_summary = context_summary.strip()
        self.source_type = source_type
        self.source_id = source_id
        self.date = date
        self.participants = participants
        self.person_ids = person_ids

        raw_id = f"{source_type}:{source_id}:{hashlib.md5(text.encode()).hexdigest()[:12]}"
        self.id = raw_id

        self.indexed_at = datetime.now(UTC).isoformat()
        self.embedding_model = embedding_model
        self.pii_level = _get_pii_level(source_type)
        self.lang = lang

        self.content_hash = hashlib.md5(
            f"{self.context_summary}\n\n{self.text}".encode()
        ).hexdigest()
        self.chunker_version = CHUNKER_VERSION
        self.schema_version = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "context": self.context,
            "context_summary": self.context_summary,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "date": self.date,
            "indexed_at": self.indexed_at,
            "participants": self.participants,
            "person_ids": self.person_ids,
            "embedding_model": self.embedding_model,
            "pii_level": self.pii_level,
            "lang": self.lang,
            "content_hash": self.content_hash,
            "chunker_version": self.chunker_version,
            "schema_version": self.schema_version,
        }


def chunk_email_threads(data: SBKData) -> list[Chunk]:
    ""




    chunks = []
    threads = data.threads

    log.info(f"Chunking {len(threads)} email threads (with body text from L0)...")


    thread_messages: dict[str, list[dict]] = {}
    if EMAILS_DIR.exists():
        for account_dir in sorted(EMAILS_DIR.iterdir()):
            msg_path = account_dir / "messages.parquet"
            if not msg_path.exists():
                continue
            try:
                msg_df = pd.read_parquet(
                    msg_path,
                    columns=["thread_id", "date", "from_addr", "subject", "body_text"],
                )
                account_name = account_dir.name
                for _, mrow in msg_df.iterrows():
                    tid = str(mrow.get("thread_id", ""))
                    if not tid or tid == "nan":
                        continue
                    body = str(mrow.get("body_text", "")).strip()
                    if not body or body == "nan":
                        continue
                    thread_messages.setdefault(tid, []).append(
                        {
                            "date": str(mrow.get("date", "")),
                            "from_addr": str(mrow.get("from_addr", "")),
                            "body_text": body,
                            "account": account_name,
                        }
                    )
            except Exception as e:
                log.warning(f"Failed to load messages from {account_dir.name}: {e}")

    log.info(f"  Loaded body text for {len(thread_messages)} threads from L0")

    for _, row in threads.iterrows():
        thread_id = str(row.get("thread_id", ""))
        subject = str(row.get("subject", "")).strip()
        participants = str(row.get("participants", "")).strip()
        account = str(row.get("account", "")).strip()
        msg_count = row.get("msg_count", 0)
        date_start = str(row.get("date_start", ""))[:10]
        date_end = str(row.get("date_end", ""))[:10]

        if not subject or subject == "nan":
            continue


        msgs = thread_messages.get(thread_id, [])
        if not msgs:
            continue


        msgs.sort(key=lambda m: m["date"])


        text_lines = []
        for msg in msgs:
            sender = msg["from_addr"]
            msg_date = msg["date"][:16] if msg["date"] else ""
            header = f"[{sender} | {msg_date}]" if msg_date else f"[{sender}]"
            text_lines.append(f"{header}\n{msg['body_text']}")

        full_text = "\n\n".join(text_lines)


        if not account or account == "nan":
            account = msgs[0].get("account", "")


        text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
        if not text_chunks:
            continue

        date_range = f"{date_start} to {date_end}" if date_start != date_end else date_start
        if participants == "nan":
            participants = ""

        for i, chunk_text in enumerate(text_chunks):
            part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
            context = (
                f"This chunk is from an email thread on account '{account}' "
                f"dated {date_range} with subject '{subject}'. "
                f"Participants: {participants}. "
                f"{msg_count} messages in the thread.{part_label}"
            )

            chunks.append(
                Chunk(
                    text=chunk_text,
                    context=context,
                    source_type="email",
                    source_id=f"{thread_id}:{i}",
                    date=date_start,
                    participants=participants,
                )
            )

    log.info(f"  Email: {len(chunks)} chunks from {len(threads)} threads")
    return chunks


def chunk_plaud_transcripts() -> list[Chunk]:
    ""
    chunks = []
    plaud_dir = PLAUD_DIR
    json_files = sorted(plaud_dir.glob("*.json"))

    log.info(f"Chunking {len(json_files)} Plaud transcripts...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue

        if not isinstance(raw, list) or not raw:
            continue


        utterances = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "").strip()
            if content:
                utterances.append(
                    {
                        "content": content,
                        "speaker": item.get("speaker") or "unknown",
                        "start_time": item.get("start_time", 0),
                    }
                )

        if not utterances:
            continue


        fname = fpath.stem
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fname)
        file_date = date_match.group(1) if date_match else ""

        title = re.sub(r"^\d{4}-\d{2}-\d{2}__\s*", "", fname).replace("_", " ").strip()


        window_size = 7
        stride = 5

        for start_idx in range(0, len(utterances), stride):
            window = utterances[start_idx : start_idx + window_size]
            if not window:
                break


            text_lines = []
            speakers_in_window = set()
            for utt in window:
                speaker = utt["speaker"]
                speakers_in_window.add(speaker)
                content = re.sub(r"^\[.*?\]:\s*", "", utt["content"])
                text_lines.append(f"[{speaker}]: {content}")

            text = "\n".join(text_lines)


            if estimate_tokens(text) < 15:
                continue


            words = text.split()
            if len(words) > 385:
                text = " ".join(words[:385]) + "..."

            participants_str = ", ".join(sorted(speakers_in_window))

            context = (
                f"This chunk is from a Plaud audio recording titled '{title}' "
                f"dated {file_date}. "
                f"Speakers: {participants_str}. "
                f"Utterances {start_idx + 1}-{start_idx + len(window)} of {len(utterances)}."
            )

            source_id = f"plaud:{fpath.stem}:{start_idx}"

            chunks.append(
                Chunk(
                    text=text,
                    context=context,
                    source_type="plaud",
                    source_id=source_id,
                    date=file_date,
                    participants=participants_str,
                )
            )

    log.info(f"  Plaud: {len(chunks)} chunks from {len(json_files)} files")
    return chunks


def chunk_tactiq_meetings() -> list[Chunk]:
    ""
    chunks = []
    tactiq_raw_dir = DATA_ROOT / "tactiq" / "raw"
    json_files = sorted(tactiq_raw_dir.glob("*.json"))

    log.info(f"Chunking {len(json_files)} Tactiq transcripts...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue

        if not isinstance(raw, dict):
            continue

        title = raw.get("title", fpath.stem)
        created_ms = raw.get("created", 0)
        platform = raw.get("platform", "unknown")
        language = raw.get("languageCode", "")


        if created_ms:
            try:
                dt = datetime.fromtimestamp(created_ms / 1000, tz=UTC)
                file_date = dt.strftime("%Y-%m-%d")
            except (OSError, ValueError):
                file_date = ""
        else:
            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fpath.stem)
            file_date = date_match.group(1) if date_match else ""


        participants_list = raw.get("participants", [])
        participant_names = []
        for p in participants_list:
            if isinstance(p, dict):
                name = p.get("name", "")
                if name:
                    participant_names.append(name)
        participants_str = ", ".join(participant_names) if participant_names else ""


        transcript = raw.get("transcript", {})
        blocks = []
        if isinstance(transcript, dict):
            blocks = transcript.get("blocks", [])

        if not blocks:
            continue


        valid_blocks = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            text = b.get("transcript", "").strip()
            if text and not b.get("isDeleted", False):
                valid_blocks.append(
                    {
                        "speaker": b.get("speakerName", "unknown"),
                        "text": text,
                        "timestamp": b.get("timestamp", 0),
                    }
                )

        if not valid_blocks:
            continue


        window_size = 7
        stride = 5

        for start_idx in range(0, len(valid_blocks), stride):
            window = valid_blocks[start_idx : start_idx + window_size]
            if not window:
                break

            text_lines = []
            speakers_in_window = set()
            for block in window:
                speaker = block["speaker"]
                speakers_in_window.add(speaker)
                block_text = re.sub(r"^\[.*?\]:\s*", "", block["text"])
                text_lines.append(f"[{speaker}]: {block_text}")

            text = "\n".join(text_lines)

            if estimate_tokens(text) < 15:
                continue

            words = text.split()
            if len(words) > 385:
                text = " ".join(words[:385]) + "..."

            window_speakers = ", ".join(sorted(speakers_in_window))

            context = (
                f"This chunk is from a Tactiq meeting transcript titled '{title}' "
                f"on {platform}, dated {file_date}. "
                f"Language: {language}. "
                f"Speakers in this segment: {window_speakers}. "
                f"Blocks {start_idx + 1}-{start_idx + len(window)} of {len(valid_blocks)}."
            )

            meeting_id = raw.get("id", fpath.stem)
            source_id = f"tactiq:{meeting_id}:{start_idx}"

            chunks.append(
                Chunk(
                    text=text,
                    context=context,
                    source_type="tactiq",
                    source_id=source_id,
                    date=file_date,
                    participants=participants_str or window_speakers,
                )
            )

    log.info(f"  Tactiq: {len(chunks)} chunks from {len(json_files)} files")
    return chunks


def chunk_slack_interactions() -> list[Chunk]:
    ""





    chunks = []

    if not SLACK_CONVERSATIONS_DIR.exists():
        log.warning(f"Slack conversations dir not found: {SLACK_CONVERSATIONS_DIR}")
        return chunks

    json_files = sorted(SLACK_CONVERSATIONS_DIR.glob("*.json"))
    log.info(f"Chunking {len(json_files)} Slack conversation files...")

    from slack_esclusi import e_escluso, esclusi

    # Slack never downloaded: no files to chunk, so the channel index is not needed.
    fuori = esclusi() if json_files else frozenset()

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue

        if not isinstance(raw, dict) or e_escluso(raw, fuori):
            continue

        channel = raw.get("channel", fpath.stem)
        messages = raw.get("messages", [])
        if not messages:
            continue


        threads: dict[str, list[dict]] = {}
        standalone: list[dict] = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            user = str(msg.get("user", "unknown"))
            ts = msg.get("ts", "0")
            thread_ts = msg.get("thread_ts", "")

            entry = {"user": user, "text": text, "ts": float(ts) if ts else 0.0}

            if thread_ts:
                threads.setdefault(thread_ts, []).append(entry)
            else:
                standalone.append(entry)


        for thread_ts_key, thread_msgs in threads.items():
            thread_msgs.sort(key=lambda m: m["ts"])
            text_lines = [f"[{m['user']}]: {m['text']}" for m in thread_msgs]
            full_text = "\n".join(text_lines)

            text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
            if not text_chunks:
                continue

            users = sorted({m["user"] for m in thread_msgs})
            participants_str = ", ".join(users)
            first_ts = thread_msgs[0]["ts"]
            date_str = ""
            if first_ts > 0:
                try:
                    date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                except (OSError, ValueError):
                    pass

            for i, chunk_text in enumerate(text_chunks):
                part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                context = (
                    f"This chunk is from Slack channel '{channel}', thread dated {date_str}. "
                    f"{len(thread_msgs)} messages. "
                    f"Participants: {participants_str}.{part_label}"
                )

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        context=context,
                        source_type="slack",
                        source_id=f"slack:{channel}:t{thread_ts_key}:{i}",
                        date=date_str,
                        participants=participants_str,
                    )
                )


        if standalone:
            standalone.sort(key=lambda m: m["ts"])
            window_secs = 2 * 3600
            windows: list[list[dict]] = []
            current_window: list[dict] = []
            window_start = 0.0

            for msg in standalone:
                if not current_window:
                    current_window.append(msg)
                    window_start = msg["ts"]
                elif msg["ts"] - window_start <= window_secs:
                    current_window.append(msg)
                else:
                    windows.append(current_window)
                    current_window = [msg]
                    window_start = msg["ts"]
            if current_window:
                windows.append(current_window)

            for win_idx, win in enumerate(windows):
                text_lines = [f"[{m['user']}]: {m['text']}" for m in win]
                full_text = "\n".join(text_lines)

                text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
                if not text_chunks:
                    continue

                users = sorted({m["user"] for m in win})
                participants_str = ", ".join(users)
                first_ts = win[0]["ts"]
                date_str = ""
                if first_ts > 0:
                    try:
                        date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                    except (OSError, ValueError):
                        pass

                for i, chunk_text in enumerate(text_chunks):
                    part_label = (
                        f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                    )
                    context = (
                        f"This chunk is from Slack channel '{channel}' on {date_str}. "
                        f"{len(win)} messages. "
                        f"Participants: {participants_str}.{part_label}"
                    )

                    chunks.append(
                        Chunk(
                            text=chunk_text,
                            context=context,
                            source_type="slack",
                            source_id=f"slack:{channel}:s{date_str}:w{win_idx}:{i}",
                            date=date_str,
                            participants=participants_str,
                        )
                    )

    log.info(f"  Slack: {len(chunks)} chunks from {len(json_files)} conversation files")
    return chunks


def chunk_slack_dm_interactions() -> list[Chunk]:
    ""







    chunks: list[Chunk] = []

    dm_dir = DATA_ROOT / "slack" / "dm"
    if not dm_dir.exists():
        log.warning(f"Slack DM dir not found: {dm_dir}")
        return chunks

    json_files = sorted(dm_dir.glob("*.json"))
    log.info(f"Chunking {len(json_files)} Slack DM files...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read DM {fpath.name}: {e}")
            continue

        if not isinstance(raw, dict):
            continue

        user_name = raw.get("user_name", fpath.stem)
        messages = raw.get("messages", [])
        if not messages:
            continue


        threads: dict[str, list[dict]] = {}
        standalone: list[dict] = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            user = str(msg.get("user", "unknown"))
            ts = msg.get("ts", "0")
            thread_ts = msg.get("thread_ts", "")

            entry = {"user": user, "text": text, "ts": float(ts) if ts else 0.0}

            if thread_ts:
                threads.setdefault(thread_ts, []).append(entry)
            else:
                standalone.append(entry)


        for thread_ts_key, thread_msgs in threads.items():
            thread_msgs.sort(key=lambda m: m["ts"])
            text_lines = [f"[{m['user']}]: {m['text']}" for m in thread_msgs]
            full_text = "\n".join(text_lines)

            text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
            if not text_chunks:
                continue

            users = sorted({m["user"] for m in thread_msgs})
            participants_str = ", ".join(users)
            first_ts = thread_msgs[0]["ts"]
            date_str = ""
            if first_ts > 0:
                try:
                    date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                except (OSError, ValueError):
                    pass

            for i, chunk_text in enumerate(text_chunks):
                part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                context = (
                    f"This chunk is from a Slack DM with {user_name}, thread dated {date_str}. "
                    f"{len(thread_msgs)} messages. "
                    f"Participants: {participants_str}.{part_label}"
                )

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        context=context,
                        source_type="slack_dm",
                        source_id=f"slack_dm:{fpath.stem}:t{thread_ts_key}:{i}",
                        date=date_str,
                        participants=participants_str,
                    )
                )


        if standalone:
            standalone.sort(key=lambda m: m["ts"])
            window_secs = 2 * 3600
            windows: list[list[dict]] = []
            current_window: list[dict] = []
            window_start = 0.0

            for msg in standalone:
                if not current_window:
                    current_window.append(msg)
                    window_start = msg["ts"]
                elif msg["ts"] - window_start <= window_secs:
                    current_window.append(msg)
                else:
                    windows.append(current_window)
                    current_window = [msg]
                    window_start = msg["ts"]
            if current_window:
                windows.append(current_window)

            for win_idx, win in enumerate(windows):
                text_lines = [f"[{m['user']}]: {m['text']}" for m in win]
                full_text = "\n".join(text_lines)

                text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
                if not text_chunks:
                    continue

                users = sorted({m["user"] for m in win})
                participants_str = ", ".join(users)
                first_ts = win[0]["ts"]
                date_str = ""
                if first_ts > 0:
                    try:
                        date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                    except (OSError, ValueError):
                        pass

                for i, chunk_text in enumerate(text_chunks):
                    part_label = (
                        f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                    )
                    context = (
                        f"This chunk is from a Slack DM with {user_name} on {date_str}. "
                        f"{len(win)} messages. "
                        f"Participants: {participants_str}.{part_label}"
                    )

                    chunks.append(
                        Chunk(
                            text=chunk_text,
                            context=context,
                            source_type="slack_dm",
                            source_id=f"slack_dm:{fpath.stem}:s{date_str}:w{win_idx}:{i}",
                            date=date_str,
                            participants=participants_str,
                        )
                    )

    log.info(f"  Slack DM: {len(chunks)} chunks from {len(json_files)} DM files")
    return chunks


def chunk_notion_entities() -> list[Chunk]:
    ""
    chunks = []

    notion_path = NOTION_DIR / "entities-notion.parquet"
    if not notion_path.exists():
        log.warning(f"Notion entities not found: {notion_path}")
        return chunks

    df = pd.read_parquet(notion_path)
    log.info(f"Chunking {len(df)} Notion entities...")

    for _, row in df.iterrows():
        entity_name = str(row.get("entity_name", "")).strip()
        entity_type = str(row.get("entity_type", "")).strip()
        source_db = str(row.get("source_db", "")).strip()
        context_text = str(row.get("context", "")).strip()
        first_seen = str(row.get("first_seen", ""))[:10]
        last_seen = str(row.get("last_seen", ""))[:10]
        mention_count = row.get("mention_count", 0)

        if not entity_name or entity_name == "nan":
            continue

        text_parts = [f"Entity: {entity_name}"]
        if entity_type and entity_type != "nan":
            text_parts.append(f"Type: {entity_type}")
        if source_db and source_db != "nan":
            text_parts.append(f"Source: {source_db}")
        if context_text and context_text != "nan":
            text_parts.append(f"Context: {context_text}")
        if mention_count:
            text_parts.append(f"Mentions: {mention_count}")

        text = "\n".join(text_parts)

        if estimate_tokens(text) < 5:
            continue

        context = (
            f"This chunk is a Notion entity '{entity_name}' of type '{entity_type}' "
            f"from database '{source_db}'. "
            f"First seen: {first_seen}, last seen: {last_seen}. "
            f"Mentioned {mention_count} times."
        )

        source_id = f"notion:{entity_name}"

        chunks.append(
            Chunk(
                text=text,
                context=context,
                source_type="notion",
                source_id=source_id,
                date=last_seen,
                participants="",
            )
        )

    log.info(f"  Notion: {len(chunks)} chunks from {len(df)} entities")
    return chunks


def chunk_network_profiles() -> list[Chunk]:
    ""
    chunks = []

    network_dir = NETWORK_DIR
    if not network_dir.exists():
        log.info(f"No network profiles yet in {network_dir}: nothing to index")
        return chunks


    profile_files = []
    for subdir in sorted(network_dir.iterdir()):
        if subdir.is_dir():
            for f in sorted(subdir.glob("*.md")):
                profile_files.append(f)

    log.info(f"Chunking {len(profile_files)} network profiles...")

    for fpath in profile_files:
        try:
            content = fpath.read_text(encoding="utf-8").strip()
        except OSError as e:
            log.warning(f"Failed to read {fpath}: {e}")
            continue

        if not content or len(content) < 20:
            continue


        person_name = fpath.stem.replace("-", " ").title()


        category = fpath.parent.name


        words = content.split()
        if len(words) > 770:
            content = " ".join(words[:770]) + "..."

        context = (
            f"This chunk is a network profile for '{person_name}' "
            f"in category '{category}'. "
            f"Part of {OWNER_LABEL}'s personal network intelligence."
        )

        source_id = f"network:{fpath.stem}"

        chunks.append(
            Chunk(
                text=content,
                context=context,
                source_type="network",
                source_id=source_id,
                date="",
                participants=person_name,
            )
        )

    log.info(f"  Network: {len(chunks)} chunks from {len(profile_files)} profiles")
    return chunks


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    ""



    sections = []
    current_heading = ""
    current_body_lines = []

    for line in text.split("\n"):
        if line.startswith("## "):

            if current_body_lines:
                body = "\n".join(current_body_lines).strip()
                if body:
                    sections.append((current_heading, body))
            current_heading = line.lstrip("# ").strip()
            current_body_lines = []
        else:
            current_body_lines.append(line)


    if current_body_lines:
        body = "\n".join(current_body_lines).strip()
        if body:
            sections.append((current_heading, body))


    if not sections and text.strip():
        sections = [("", text.strip())]

    return sections


def chunk_raw_analysis() -> list[Chunk]:
    ""
    chunks = []

    raw_dir = NOTES_DIR
    if not raw_dir.exists():
        log.info(f"No notes yet in {raw_dir}: nothing to index")
        return chunks


    md_files = sorted(raw_dir.rglob("*.md"))


    md_files = [f for f in md_files if not f.name.startswith("secrets-")]

    log.info(f"Chunking {len(md_files)} raw analysis files...")

    for fpath in md_files:
        try:
            content = fpath.read_text(encoding="utf-8").strip()
        except OSError as e:
            log.warning(f"Failed to read {fpath}: {e}")
            continue

        if not content or len(content) < 30:
            continue


        rel_path = fpath.relative_to(raw_dir)
        doc_name = fpath.stem.replace("-", " ").replace("_", " ").title()

        sections = _split_markdown_sections(content)

        for sec_idx, (heading, body) in enumerate(sections):
            if estimate_tokens(body) < 10:
                continue


            words = body.split()
            if len(words) > 770:
                body = " ".join(words[:770]) + "..."

            section_label = f", section '{heading}'" if heading else ""
            context = (
                f"This chunk is from a raw analysis document '{doc_name}'{section_label}. "
                f"File: notes/{rel_path}. "
                f"Part of {OWNER_LABEL}'s SBK knowledge base."
            )

            source_id = f"raw:{rel_path}:{sec_idx}"

            chunks.append(
                Chunk(
                    text=body,
                    context=context,
                    source_type="raw",
                    source_id=source_id,
                    date="",
                    participants="",
                )
            )

    log.info(f"  Raw: {len(chunks)} chunks from {len(md_files)} files")
    return chunks


def chunk_whatsapp_chats() -> list[Chunk]:
    ""





    chunks = []

    if not WHATSAPP_CHATS_DIR.exists():
        log.warning(f"WhatsApp chats dir not found: {WHATSAPP_CHATS_DIR}")
        return chunks

    json_files = sorted(WHATSAPP_CHATS_DIR.glob("*.json"))
    log.info(f"Chunking {len(json_files)} WhatsApp chat files...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue

        if not isinstance(raw, dict):
            continue

        chat_name = raw.get("chat_name", fpath.stem)
        phone = raw.get("phone", "")
        messages = raw.get("messages", [])
        if not messages:
            continue


        valid_msgs = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue

            lower = text.lower()
            if "end-to-end encrypted" in lower or "messages and calls are end-to-end" in lower:
                continue
            sender = str(msg.get("sender", "unknown"))
            ts_raw = msg.get("timestamp", "")

            ts_epoch = 0.0
            if ts_raw:
                try:
                    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    ts_epoch = dt.timestamp()
                except (ValueError, TypeError):
                    pass
            valid_msgs.append({"sender": sender, "text": text, "ts": ts_epoch})

        if not valid_msgs:
            continue


        valid_msgs.sort(key=lambda m: m["ts"])
        window_secs = 2 * 3600
        windows: list[list[dict]] = []
        current_window: list[dict] = []
        window_start = 0.0

        for msg in valid_msgs:
            if not current_window:
                current_window.append(msg)
                window_start = msg["ts"]
            elif msg["ts"] - window_start <= window_secs:
                current_window.append(msg)
            else:
                windows.append(current_window)
                current_window = [msg]
                window_start = msg["ts"]
        if current_window:
            windows.append(current_window)

        for win_idx, win in enumerate(windows):
            text_lines = [f"[{m['sender']}]: {m['text']}" for m in win]
            full_text = "\n".join(text_lines)

            text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
            if not text_chunks:
                continue

            senders = sorted({m["sender"] for m in win})
            participants_str = ", ".join(senders)
            first_ts = win[0]["ts"]
            date_str = ""
            if first_ts > 0:
                try:
                    date_str = datetime.fromtimestamp(first_ts, tz=UTC).strftime("%Y-%m-%d")
                except (OSError, ValueError):
                    pass

            for i, chunk_text in enumerate(text_chunks):
                part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                context = (
                    f"This chunk is from a WhatsApp chat with '{chat_name}'"
                    f"{f' ({phone})' if phone else ''}. "
                    f"Date: {date_str}. "
                    f"Participants: {participants_str}.{part_label}"
                )

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        context=context,
                        source_type="whatsapp",
                        source_id=f"whatsapp:{fpath.stem}:{date_str}:w{win_idx}:{i}",
                        date=date_str,
                        participants=participants_str,
                    )
                )

    log.info(f"  WhatsApp: {len(chunks)} chunks from {len(json_files)} files")
    return chunks


def chunk_wa_documents() -> list[Chunk]:
    ""













    chunks = []
    seen_hashes: set[str] = set()

    if not WHATSAPP_DOCUMENTS_DIR.exists():
        log.warning(f"WhatsApp documents dir not found: {WHATSAPP_DOCUMENTS_DIR}")
        return chunks


    chat_dirs = sorted(d for d in WHATSAPP_DOCUMENTS_DIR.iterdir() if d.is_dir())
    total_docs = 0
    skipped_empty = 0
    skipped_dedup = 0

    for chat_dir in chat_dirs:
        chat_slug = chat_dir.name
        json_files = sorted(chat_dir.glob("*.json"))
        if not json_files:
            continue

        for fpath in json_files:
            try:
                doc = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Failed to read {fpath}: {e}")
                continue

            if not isinstance(doc, dict):
                continue

            text = str(doc.get("text", "")).strip()
            if not text:
                skipped_empty += 1
                continue


            content_hash = hashlib.md5(text.encode()).hexdigest()
            if content_hash in seen_hashes:
                skipped_dedup += 1
                continue
            seen_hashes.add(content_hash)

            total_docs += 1


            chat_name = str(doc.get("chat", chat_slug))
            sender = str(doc.get("sender", "unknown"))
            timestamp = str(doc.get("timestamp", ""))
            doc_type = str(doc.get("type", "unknown"))
            pages = doc.get("pages", None)
            word_count = doc.get("word_count", len(text.split()))
            source_file = str(doc.get("source_file", ""))
            filename = Path(source_file).name if source_file else fpath.stem


            date_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass


            conv_before = doc.get("conversation_before", [])
            conv_after = doc.get("conversation_after", [])
            conv_context_parts = []
            if conv_before:
                before_lines = []
                for msg in conv_before[-3:]:
                    s = msg.get("sender", "?")
                    t = msg.get("text", "")
                    if t:
                        before_lines.append(f"[{s}]: {t[:150]}")
                if before_lines:
                    conv_context_parts.append("Conversation before: " + " | ".join(before_lines))
            if conv_after:
                after_lines = []
                for msg in conv_after[:3]:
                    s = msg.get("sender", "?")
                    t = msg.get("text", "")
                    if t:
                        after_lines.append(f"[{s}]: {t[:150]}")
                if after_lines:
                    conv_context_parts.append("Conversation after: " + " | ".join(after_lines))
            conv_context = " ".join(conv_context_parts)


            source_id = f"wa_document:{chat_slug}/{fpath.stem}"


            page_info = f" ({pages} pages)" if pages else ""


            participants_parts = sorted({chat_name, sender} - {""})
            participants_str = ", ".join(participants_parts)


            if word_count < 500:

                full_text = text
                if conv_context:
                    full_text = f"{text}\n\n---\n{conv_context}"

                context = (
                    f"This chunk is from a {doc_type} document '{filename}'{page_info} "
                    f"shared in WhatsApp chat with '{chat_name}' by {sender}. "
                    f"Date: {date_str}."
                )

                chunks.append(
                    Chunk(
                        text=full_text,
                        context=context,
                        source_type="wa_document",
                        source_id=f"{source_id}:0",
                        date=date_str,
                        participants=participants_str,
                    )
                )
            else:


                text_chunks = _chunk_text_sliding_window(text, 520, 65)
                if not text_chunks:
                    continue

                for i, chunk_text in enumerate(text_chunks):

                    if i == 0 and conv_context:
                        chunk_text = f"{chunk_text}\n\n---\n{conv_context}"

                    part_label = (
                        f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                    )
                    context = (
                        f"This chunk is from a {doc_type} document '{filename}'{page_info} "
                        f"shared in WhatsApp chat with '{chat_name}' by {sender}. "
                        f"Date: {date_str}.{part_label}"
                    )

                    chunks.append(
                        Chunk(
                            text=chunk_text,
                            context=context,
                            source_type="wa_document",
                            source_id=f"{source_id}:{i}",
                            date=date_str,
                            participants=participants_str,
                        )
                    )

    log.info(
        f"  WA Documents: {len(chunks)} chunks from {total_docs} documents "
        f"({skipped_empty} empty, {skipped_dedup} dedup)"
    )
    return chunks


def chunk_wa_photo_ocr() -> list[Chunk]:
    ""





    photos_dir = DATA_ROOT / "whatsapp" / "photos"
    cls_file = photos_dir / "_photo-classification.json"
    if not cls_file.exists():
        log.info("  WA Photo OCR: no classification file found")
        return []

    cls_data = json.loads(cls_file.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []

    for chat_slug, photos in cls_data.items():
        for photo in photos:
            ocr_text = photo.get("ocr_text", "")
            if not ocr_text or len(ocr_text) < 20:
                continue

            timestamp = photo.get("timestamp", "")
            sender = photo.get("sender", "")
            context = photo.get("conversation_context", [])
            context_text = "\n".join(
                f"[{m.get('sender', '?')}]: {m.get('text', '')}" for m in context if m.get("text")
            )

            date_str = timestamp[:10] if timestamp else ""
            text = f"[OCR from photo by {sender}]\n{ocr_text}"
            if context_text:
                text = f"{context_text}\n\n{text}"

            chunks.append(
                Chunk(
                    text=text,
                    context=f"OCR text from a WhatsApp photo in chat '{chat_slug}'. Sender: {sender}.",
                    source_type="wa_photo_ocr",
                    source_id=f"wa_photo:{chat_slug}/{photo.get('filename', 'unknown')[:60]}",
                    date=date_str,
                    participants=f"{sender}, {OWNER_LABEL}",
                )
            )

    log.info(f"  WA Photo OCR: {len(chunks)} chunks with text")
    return chunks


def chunk_email_attachments() -> list[Chunk]:
    ""




    att_dir = DATA_ROOT / "emails" / "extracted-attachments"
    chunks: list[Chunk] = []
    seen: set[str] = set()
    if not att_dir.exists():

        log.info("  Email Attachments: directory not found")
        return _chunk_allegati_posta(seen)

    for account_dir in sorted(att_dir.iterdir()):
        if not account_dir.is_dir():
            continue
        for fpath in sorted(account_dir.glob("*.json")):
            try:
                doc = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            text = doc.get("text", "")
            if not text or len(text) < 30:
                continue


            text_hash = hashlib.sha256(text[:2000].encode()).hexdigest()[:16]
            if text_hash in seen:
                continue
            seen.add(text_hash)

            email_ctx = doc.get("email_context", {})
            subject = email_ctx.get("subject", "") if isinstance(email_ctx, dict) else ""
            from_addr = email_ctx.get("from_addr", "") if isinstance(email_ctx, dict) else ""
            date_str = (email_ctx.get("date", "") if isinstance(email_ctx, dict) else "")[:10]
            filename = doc.get("filename", fpath.stem)
            doc_type = doc.get("mime_type", "pdf")

            context = (
                f"Email attachment ({doc_type}): '{filename}'. "
                f"From: {from_addr}. Subject: {subject}. Date: {date_str}."
            )


            words = text.split()
            if len(words) <= 500:
                chunks.append(
                    Chunk(
                        text=text,
                        context=context,
                        source_type="email_attachment",
                        source_id=f"email_att:{account_dir.name}/{fpath.stem}",
                        date=date_str,
                        participants=from_addr,
                    )
                )
            else:
                chunk_size = 400
                overlap = 50
                for i in range(0, len(words), chunk_size - overlap):
                    chunk_words = words[i : i + chunk_size]
                    part = i // (chunk_size - overlap) + 1
                    chunks.append(
                        Chunk(
                            text=" ".join(chunk_words),
                            context=f"{context} (part {part})",
                            source_type="email_attachment",
                            source_id=f"email_att:{account_dir.name}/{fpath.stem}_p{part}",
                            date=date_str,
                            participants=from_addr,
                        )
                    )

    chunks.extend(_chunk_allegati_posta(seen))
    log.info(f"  Email Attachments: {len(chunks)} chunks")
    return chunks


def _chunk_allegati_posta(seen: set[str]) -> list[Chunk]:
    ""

    import pandas as pd

    percorso = DATA_ROOT / "emails" / "processed" / "allegati-posta.parquet"
    if not percorso.exists():
        return []
    colonne = ["casella", "msg_id", "nome", "data", "from_addr", "subject", "content_text"]
    try:
        df = pd.read_parquet(percorso, columns=colonne)
    except (OSError, ValueError, KeyError) as e:
        log.warning(f"  Mail attachments not read: {e}")
        return []
    chunks: list[Chunk] = []
    for casella, msg_id, nome, data, mittente, oggetto, testo in df.itertuples(
        index=False, name=None
    ):
        testo = (testo or "").strip()
        if len(testo) < 30:
            continue
        impronta = hashlib.sha256(testo[:2000].encode()).hexdigest()[:16]
        if impronta in seen:
            continue
        seen.add(impronta)
        giorno = str(data)[:10] if data is not None else ""
        contesto = f"Email attachment: '{nome}'. From: {mittente or ''}. Subject: {oggetto or ''}. Date: {giorno}."
        base = f"email_att:{casella}/{msg_id}:{hashlib.sha1(str(nome).encode()).hexdigest()[:10]}"
        parole = testo.split()
        passo = 400 - 50
        parti = range(0, len(parole), passo) if len(parole) > 500 else [0]
        for i in parti:
            pezzo = " ".join(parole[i : i + 400]) if len(parole) > 500 else testo
            n = i // passo + 1
            chunks.append(
                Chunk(
                    text=pezzo,
                    context=f"{contesto} (part {n})" if len(parole) > 500 else contesto,
                    source_type="email_attachment",
                    source_id=f"{base}_p{n}",
                    date=giorno,
                    participants=mittente or "",
                )
            )
    log.info(f"  Mail attachments: {len(chunks)} pieces from {len(seen)} texts")
    return chunks


def chunk_attio_notes() -> list[Chunk]:
    ""




    chunks = []

    notes_path = ATTIO_DIR / "notes.parquet"
    if not notes_path.exists():
        log.warning(f"Attio notes not found: {notes_path}")
        return chunks

    df = pd.read_parquet(notes_path)
    log.info(f"Chunking {len(df)} Attio notes...")


    parent_names: dict[str, str] = {}

    people_path = ATTIO_DIR / "people.parquet"
    if people_path.exists():
        try:
            people_df = pd.read_parquet(people_path)
            for _, row in people_df.iterrows():
                pid = str(row.get("record_id", row.get("id", "")))
                name = str(row.get("name", "")).strip()
                if pid and name and name != "nan" and name != "None":
                    parent_names[pid] = name
        except Exception as e:
            log.warning(f"Failed to load people for note enrichment: {e}")

    companies_path = ATTIO_DIR / "companies.parquet"
    if companies_path.exists():
        try:
            comp_df = pd.read_parquet(companies_path)
            for _, row in comp_df.iterrows():
                cid = str(row.get("record_id", row.get("id", "")))
                name = str(row.get("name", "")).strip()
                if cid and name and name != "nan" and name != "None":
                    parent_names[cid] = name
        except Exception as e:
            log.warning(f"Failed to load companies for note enrichment: {e}")

    log.info(f"  Parent name lookup: {len(parent_names)} entries")

    for _, row in df.iterrows():
        note_id = str(row.get("note_id", row.get("id", "")))
        title = str(row.get("title", "")).strip()

        content = str(row.get("content_plaintext", row.get("content", ""))).strip()
        parent_id = str(row.get("parent_record_id", ""))
        created = str(row.get("created_at", ""))[:10]

        if not content or content == "nan" or len(content) < 20:
            continue


        parent_name = parent_names.get(parent_id, "")


        text_chunks = _chunk_text_sliding_window(content, 500, 100)
        if not text_chunks:
            continue

        for i, chunk_text in enumerate(text_chunks):
            part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
            parent_label = f" about '{parent_name}'" if parent_name else ""
            title_label = f" titled '{title}'" if title and title != "nan" else ""
            context = (
                f"This chunk is from an Attio CRM note{title_label}{parent_label}, "
                f"dated {created}.{part_label}"
            )

            chunks.append(
                Chunk(
                    text=chunk_text,
                    context=context,
                    source_type="attio_notes",
                    source_id=f"attio_note:{note_id}:{i}",
                    date=created,
                    participants=parent_name,
                )
            )

    log.info(f"  Attio notes: {len(chunks)} chunks from {len(df)} notes")
    return chunks


def chunk_clickup_tasks() -> list[Chunk]:
    ""




    chunks: list[Chunk] = []
    percorso = DATA_ROOT / "clickup" / "processed" / "tasks.parquet"
    if not percorso.exists():
        log.warning(f"ClickUp tasks not found: {percorso}")
        return chunks
    df = pd.read_parquet(percorso)
    log.info(f"Chunking {len(df)} ClickUp tasks...")
    for r in df.to_dict("records"):
        nome = str(r.get("nome") or "").strip()
        testo = str(r.get("testo") or "").strip()
        commenti = str(r.get("commenti_testo") or "").strip()
        corpo = "\n\n".join(x for x in (testo, f"Commenti:\n{commenti}" if commenti else "") if x)
        if len(corpo) < 20:
            continue


        assegnatari = r.get("assegnatari")
        persone = [str(r.get("creatore_nome") or "")] + [
            str(a) for a in (list(assegnatari) if assegnatari is not None else [])
        ]
        partecipanti = ", ".join(dict.fromkeys(p for p in persone if p))
        data = str(r.get("aggiornato") or r.get("creato") or "")[:10]
        pezzi = _chunk_text_sliding_window(corpo, 500, 100)
        for i, pezzo in enumerate(pezzi):
            parte = f" (part {i + 1}/{len(pezzi)})" if len(pezzi) > 1 else ""
            contesto = (
                f"This chunk is from a ClickUp task '{nome}' in list '{r.get('lista') or ''}' "
                f"(space '{r.get('space') or ''}', status '{r.get('stato') or ''}'), updated {data}.{parte}"
            )
            chunks.append(
                Chunk(
                    text=pezzo,
                    context=contesto,
                    source_type="clickup",
                    source_id=f"clickup:{r.get('task_id')}:{i}",
                    date=data,
                    participants=partecipanti,
                )
            )
    log.info(f"  ClickUp: {len(chunks)} chunks from {len(df)} tasks")
    chunks.extend(_chunk_clickup_documenti())
    return chunks


def chunk_docusign_contratti() -> list[Chunk]:
    ""

    chunks: list[Chunk] = []
    contratti = DATA_ROOT / "docusign" / "processed" / "contratti-testo.parquet"
    if not contratti.exists():
        return chunks
    colonne = ["envelopeId", "status", "oggetto", "inviata", "partecipanti", "content_text"]
    df = pd.read_parquet(contratti, columns=colonne)
    df = df[df["content_text"].fillna("").str.len() >= 30]
    for eid, stato, oggetto, inviata, partecipanti, testo in df.itertuples(index=False, name=None):
        giorno = str(inviata or "")[:10]
        pezzi = _chunk_text_sliding_window(str(testo), 500, 100)
        for i, pezzo in enumerate(pezzi):
            parte = f" (part {i + 1}/{len(pezzi)})" if len(pezzi) > 1 else ""
            chunks.append(
                Chunk(
                    text=pezzo,
                    context=(
                        f"DocuSign contract '{oggetto or ''}', sent {giorno}, status {stato}, "
                        f"recipients: {partecipanti or ''}.{parte}"
                    ),
                    source_type="docusign",
                    source_id=f"docusign:{eid}:{i}",
                    date=giorno,
                    participants=str(partecipanti or ""),
                )
            )
    log.info(f"  DocuSign contracts: {len(chunks)} chunks from {len(df)} contracts")
    return chunks


def _chunk_clickup_documenti() -> list[Chunk]:
    ""

    chunks: list[Chunk] = []
    percorso = DATA_ROOT / "clickup" / "processed" / "documents.parquet"
    if not percorso.exists():
        return chunks
    df = pd.read_parquet(percorso)
    for r in df.to_dict("records"):
        testo = str(r.get("testo") or "").strip()
        if len(testo) < 20:
            continue
        nome = str(r.get("nome") or "").strip()
        data = str(r.get("aggiornato") or r.get("creato") or "")[:10]
        pezzi = _chunk_text_sliding_window(testo, 500, 100)
        for i, pezzo in enumerate(pezzi):
            parte = f" (part {i + 1}/{len(pezzi)})" if len(pezzi) > 1 else ""
            chunks.append(
                Chunk(
                    text=pezzo,
                    context=f"This chunk is from a ClickUp document '{nome}', updated {data}.{parte}",
                    source_type="clickup",
                    source_id=f"clickup_doc:{r.get('doc_id')}:{i}",
                    date=data,
                    participants="",
                )
            )
    log.info(f"  ClickUp documents: {len(chunks)} chunks from {len(df)} documents")
    return chunks


def chunk_chatgpt_conversations() -> list[Chunk]:
    ""





    chunks = []

    conv_path = DATA_ROOT / "chatgpt" / "conversations.json"
    if not conv_path.exists():
        log.warning(f"ChatGPT conversations not found: {conv_path}")
        return chunks

    try:
        conversations = json.loads(conv_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read ChatGPT conversations: {e}")
        return chunks

    if not isinstance(conversations, list):
        log.warning("ChatGPT conversations.json is not a list")
        return chunks

    log.info(f"Chunking {len(conversations)} ChatGPT conversations...")

    for conv in conversations:
        if not isinstance(conv, dict):
            continue

        title = conv.get("title", "Untitled")


        date_str = ""
        create_time_unix = conv.get("create_time_unix", 0)
        create_time_iso = conv.get("create_time", "")
        if create_time_unix:
            try:
                dt = datetime.fromtimestamp(float(create_time_unix), tz=UTC)
                date_str = dt.strftime("%Y-%m-%d")
            except (OSError, ValueError, TypeError):
                pass
        if not date_str and create_time_iso and isinstance(create_time_iso, str):
            date_str = create_time_iso[:10]


        raw_messages = conv.get("messages", [])
        if not isinstance(raw_messages, list):

            mapping = conv.get("mapping", {})
            if isinstance(mapping, dict):
                raw_messages = []
                for _node_id, node in mapping.items():
                    if not isinstance(node, dict):
                        continue
                    msg = node.get("message")
                    if isinstance(msg, dict):
                        author = msg.get("author", {})
                        role = author.get("role", "") if isinstance(author, dict) else ""
                        content = msg.get("content", {})
                        parts = content.get("parts", []) if isinstance(content, dict) else []
                        text = " ".join(
                            p.strip() for p in parts if isinstance(p, str) and p.strip()
                        )
                        if text and role:
                            raw_messages.append(
                                {
                                    "role": role,
                                    "text": text,
                                    "create_time": msg.get("create_time", ""),
                                }
                            )

        messages = []
        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).lower()
            if role not in ("user", "assistant"):
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue


            msg_ts = 0.0
            msg_ct = msg.get("create_time", "")
            if isinstance(msg_ct, int | float) and msg_ct > 0:
                msg_ts = float(msg_ct)
            elif isinstance(msg_ct, str) and msg_ct:
                try:
                    msg_ts = datetime.fromisoformat(msg_ct.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    pass

            role_label = "User" if role == "user" else "Assistant"
            messages.append({"role": role_label, "text": text, "ts": msg_ts})

        if not messages:
            continue


        messages.sort(key=lambda m: m["ts"])


        text_lines = [f"[{m['role']}]: {m['text']}" for m in messages]
        full_text = "\n\n".join(text_lines)

        text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
        if not text_chunks:
            continue

        conv_id = conv.get("id", conv.get("conversation_id", title))

        for i, chunk_text in enumerate(text_chunks):
            part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
            context = (
                f"This chunk is from a ChatGPT conversation titled '{title}', "
                f"dated {date_str}. "
                f"{len(messages)} messages.{part_label}"
            )

            chunks.append(
                Chunk(
                    text=chunk_text,
                    context=context,
                    source_type="chatgpt",
                    source_id=f"chatgpt:{conv_id}:{i}",
                    date=date_str,
                    participants=OWNER_LABEL,
                )
            )

    log.info(f"  ChatGPT: {len(chunks)} chunks from {len(conversations)} conversations")
    return chunks


def chunk_attio_call_transcripts() -> list[Chunk]:
    ""





    chunks = []


    json_files = attio_transcript_files(ATTIO_TRANSCRIPTS_DIR)
    if not json_files:
        log.warning(f"Attio transcripts not found in {ATTIO_TRANSCRIPTS_DIRS}")
        return chunks
    log.info(f"Chunking {len(json_files)} Attio call transcripts...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue


        segments = []
        if isinstance(raw, list):
            segments = raw
        elif isinstance(raw, dict):
            segments = raw.get("segments", raw.get("transcript", []))
            if isinstance(segments, str):

                text_chunks = _chunk_text_sliding_window(segments, 500, 100)
                if text_chunks:
                    date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fpath.stem)
                    file_date = date_match.group(1) if date_match else ""
                    for i, chunk_text in enumerate(text_chunks):
                        chunks.append(
                            Chunk(
                                text=chunk_text,
                                context=f"This chunk is from an Attio call transcript '{fpath.stem}', dated {file_date}.",
                                source_type="attio_call",
                                source_id=f"attio_call:{fpath.stem}:{i}",
                                date=file_date,
                                participants="",
                            )
                        )
                continue


        valid_segs = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text", seg.get("content", ""))).strip()
            if text and text != "nan":
                valid_segs.append(
                    {
                        "speaker": str(seg.get("speaker", "unknown")),
                        "text": text,
                        "start": seg.get("start", 0),
                    }
                )

        if not valid_segs:
            continue

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fpath.stem)
        file_date = date_match.group(1) if date_match else ""


        window_size = 7
        stride = 5

        for start_idx in range(0, len(valid_segs), stride):
            window = valid_segs[start_idx : start_idx + window_size]
            if not window:
                break

            text_lines = []
            speakers_in_window = set()
            for seg in window:
                speaker = seg["speaker"]
                speakers_in_window.add(speaker)
                seg_text = re.sub(r"^\[.*?\]:\s*", "", seg["text"])
                text_lines.append(f"[{speaker}]: {seg_text}")

            text = "\n".join(text_lines)
            if estimate_tokens(text) < 15:
                continue

            words = text.split()
            if len(words) > 385:
                text = " ".join(words[:385]) + "..."

            participants_str = ", ".join(sorted(speakers_in_window))
            context = (
                f"This chunk is from an Attio call transcript '{fpath.stem}', "
                f"dated {file_date}. "
                f"Speakers: {participants_str}. "
                f"Segments {start_idx + 1}-{start_idx + len(window)} of {len(valid_segs)}."
            )

            chunks.append(
                Chunk(
                    text=text,
                    context=context,
                    source_type="attio_call",
                    source_id=f"attio_call:{fpath.stem}:{start_idx}",
                    date=file_date,
                    participants=participants_str,
                )
            )

    log.info(f"  Attio calls: {len(chunks)} chunks from {len(json_files)} files")
    return chunks


def chunk_voice_memo_transcripts() -> list[Chunk]:
    ""




    chunks = []

    if not VOICE_MEMOS_TRANSCRIPTS_DIR.exists():
        log.warning(f"Voice memos dir not found: {VOICE_MEMOS_TRANSCRIPTS_DIR}")
        return chunks

    json_files = sorted(VOICE_MEMOS_TRANSCRIPTS_DIR.glob("*.json"))
    log.info(f"Chunking {len(json_files)} voice memo transcripts...")

    for fpath in json_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {fpath.name}: {e}")
            continue


        full_text = ""
        if isinstance(raw, list):
            parts = []
            for seg in raw:
                if isinstance(seg, dict):
                    text = str(seg.get("text", seg.get("content", ""))).strip()
                    if text and text != "nan":
                        parts.append(text)
                elif isinstance(seg, str) and seg.strip():
                    parts.append(seg.strip())
            full_text = " ".join(parts)
        elif isinstance(raw, dict):

            if "text" in raw:
                full_text = str(raw["text"]).strip()
            elif "segments" in raw:
                parts = []
                for seg in raw["segments"]:
                    if isinstance(seg, dict):
                        text = str(seg.get("text", "")).strip()
                        if text:
                            parts.append(text)
                full_text = " ".join(parts)
            elif "transcript" in raw and isinstance(raw["transcript"], str):
                full_text = raw["transcript"].strip()

        if not full_text or len(full_text) < 30:
            continue

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", fpath.stem)
        file_date = date_match.group(1) if date_match else ""
        title = re.sub(r"^\d{4}-\d{2}-\d{2}[_\s]*", "", fpath.stem).replace("_", " ").strip()

        text_chunks = _chunk_text_sliding_window(full_text, 500, 100)
        if not text_chunks:
            continue

        for i, chunk_text in enumerate(text_chunks):
            part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
            title_label = f" titled '{title}'" if title else ""
            context = (
                f"This chunk is from a voice memo{title_label} by {OWNER_LABEL}, "
                f"dated {file_date}.{part_label}"
            )

            chunks.append(
                Chunk(
                    text=chunk_text,
                    context=context,
                    source_type="voice_memo",
                    source_id=f"voice_memo:{fpath.stem}:{i}",
                    date=file_date,
                    participants=OWNER_LABEL,
                )
            )

    log.info(f"  Voice memos: {len(chunks)} chunks from {len(json_files)} files")
    return chunks


def _extract_text_from_file(fpath: Path) -> str:
    ""
    ext = fpath.suffix.lower()

    if ext in (".md", ".txt", ".text", ".log"):
        return fpath.read_text(encoding="utf-8", errors="replace").strip()

    if ext == ".csv":

        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[:51])

    if ext == ".pdf":
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(fpath) as pdf:
                for page in pdf.pages[:30]:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts)
        except Exception:
            return ""

    if ext == ".docx":
        try:
            from docx import Document

            doc = Document(str(fpath))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""

    if ext == ".xlsx":
        try:
            from openpyxl import load_workbook

            wb = load_workbook(str(fpath), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:3]:
                rows = []
                for row in ws.iter_rows(max_row=50, values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    rows.append(" | ".join(cells))
                parts.append(f"Sheet: {ws.title}\n" + "\n".join(rows))
            wb.close()
            return "\n\n".join(parts)
        except Exception:
            return ""

    return ""


def chunk_gdrive_documents(*, deep: bool = False) -> list[Chunk]:
    ""





    chunks: list[Chunk] = []
    seen: set[str] = set()

    if deep:

        index_file = DATA_ROOT / "gdrive" / "gdrive-index.json"
        if not index_file.exists():
            log.warning("gdrive-index.json not found")
            return chunks

        index = json.loads(index_file.read_text(encoding="utf-8"))
        textable_exts = {".md", ".txt", ".text", ".csv", ".pdf", ".docx", ".xlsx"}
        eligible = [
            f
            for f in index
            if f.get("local_path")
            and Path(f["local_path"]).exists()
            and Path(f["local_path"]).suffix.lower() in textable_exts
        ]
        log.info(f"GDrive deep: {len(eligible)} textable files from {len(index)} total")

        for entry in eligible:
            fpath = Path(entry["local_path"])
            try:
                content = _extract_text_from_file(fpath)
            except Exception as e:
                log.debug(f"Failed to extract {fpath.name}: {e}")
                continue

            if not content or len(content) < 30:
                continue


            text_hash = hashlib.sha256(content[:2000].encode()).hexdigest()[:16]
            if text_hash in seen:
                continue
            seen.add(text_hash)

            doc_name = entry.get("name", fpath.name)
            folder = entry.get("folder_path", "")


            words = content.split()
            if len(words) <= 500:
                context = f"Google Drive document: '{doc_name}'. Folder: {folder}."
                chunks.append(
                    Chunk(
                        text=content,
                        context=context,
                        source_type="gdrive",
                        source_id=f"gdrive:{fpath.stem}",
                        date="",
                        participants="",
                    )
                )
            else:
                chunk_size = 400
                overlap = 50
                for i in range(0, len(words), chunk_size - overlap):
                    chunk_words = words[i : i + chunk_size]
                    part = i // (chunk_size - overlap) + 1
                    context = (
                        f"Google Drive document: '{doc_name}' (part {part}). Folder: {folder}."
                    )
                    chunks.append(
                        Chunk(
                            text=" ".join(chunk_words),
                            context=context,
                            source_type="gdrive",
                            source_id=f"gdrive:{fpath.stem}_p{part}",
                            date="",
                            participants="",
                        )
                    )

        log.info(f"  GDrive deep: {len(chunks)} chunks from {len(eligible)} files")
        return chunks



    docs_path = DATA_ROOT / "gdrive" / "processed" / "documents.parquet"
    if not docs_path.exists():
        log.warning(f"GDrive L1 documents not found: {docs_path}")
        return chunks

    import pandas as pd

    docs = pd.read_parquet(
        docs_path, columns=["file_id", "name", "folder_path", "modified", "content_text"]
    )
    docs = docs[docs["content_text"].fillna("").str.len() >= 30]
    log.info(f"Chunking {len(docs)} GDrive documents with text (L1)...")

    for row in docs.itertuples(index=False):
        content = row.content_text.strip()
        text_hash = hashlib.sha256(content[:2000].encode()).hexdigest()[:16]
        if text_hash in seen:
            continue
        seen.add(text_hash)

        date = row.modified.strftime("%Y-%m-%d") if pd.notna(row.modified) else ""
        folder = row.folder_path or ""
        words = content.split()
        step = 400 - 50
        parts = range(0, len(words), step) if len(words) > 500 else [0]
        for i in parts:
            text = " ".join(words[i : i + 400]) if len(words) > 500 else content
            part = i // step + 1
            label = f" (part {part})" if len(words) > 500 else ""
            chunks.append(
                Chunk(
                    text=text,
                    context=f"Google Drive document: '{row.name}'{label}. Folder: {folder}.",
                    source_type="gdrive",
                    source_id=f"gdrive:{row.file_id}_p{part}",
                    date=date,
                    participants="",
                )
            )

    log.info(f"  GDrive: {len(chunks)} chunks from {len(seen)} documents")
    return chunks


def chunk_domain_documents() -> list[Chunk]:
    ""





    chunks = []


    all_files = []
    for src_dir in [SBK_ANALYSES_DIR]:
        if src_dir and src_dir.exists():
            all_files.extend(sorted(src_dir.rglob("*.md")))

    log.info(f"Chunking {len(all_files)} domain documents...")

    for fpath in all_files:
        try:
            content = fpath.read_text(encoding="utf-8").strip()
        except OSError as e:
            log.warning(f"Failed to read {fpath}: {e}")
            continue

        if not content or len(content) < 30:
            continue

        doc_name = fpath.stem.replace("-", " ").replace("_", " ").strip()

        domain_label = "analysis"

        sections = _split_markdown_sections(content)

        for sec_idx, (heading, body) in enumerate(sections):
            if estimate_tokens(body) < 10:
                continue

            words = body.split()
            if len(words) > 770:
                body = " ".join(words[:770]) + "..."

            section_label = f", section '{heading}'" if heading else ""
            context = (
                f"This chunk is from a domain document '{doc_name}' ({domain_label}){section_label}. "
                f"Part of {OWNER_LABEL}'s strategic intelligence."
            )

            chunks.append(
                Chunk(
                    text=body,
                    context=context,
                    source_type="domain",
                    source_id=f"domain:{fpath.stem}:{sec_idx}",
                    date="",
                    participants="",
                )
            )

    log.info(f"  Domain: {len(chunks)} chunks from {len(all_files)} files")
    return chunks




_email_to_name: dict[str, str] | None = None
_email_to_person_id: dict[str, str] | None = None


def _build_email_lookup() -> tuple[dict[str, str], dict[str, str]]:
    ""




    global _email_to_name, _email_to_person_id  # noqa: PLW0603
    if _email_to_name is not None:
        return _email_to_name, _email_to_person_id

    _email_to_name = {}
    _email_to_person_id = {}

    contacts_path = ENRICHED_DIR / "contacts-merged.parquet"
    if not contacts_path.exists():
        log.warning(
            f"contacts-merged.parquet not found at {contacts_path}, email resolution disabled"
        )
        return _email_to_name, _email_to_person_id

    try:
        df = pd.read_parquet(contacts_path, columns=["name", "person_id", "all_emails"])

        for _, row in df.iterrows():
            name = str(row.get("name", "")).strip()
            pid = str(row.get("person_id", "")).strip()
            raw_emails = row.get("all_emails", "")

            if not name or name == "nan" or not pid or pid == "nan":
                continue


            emails: list[str] = []
            if isinstance(raw_emails, list):
                emails = raw_emails
            elif isinstance(raw_emails, str) and raw_emails.startswith("["):
                try:
                    emails = json.loads(raw_emails)
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(raw_emails, str) and "@" in raw_emails:
                emails = [raw_emails]

            for email in emails:
                email = str(email).strip().lower()
                if email and email != "nan" and "@" in email:
                    _email_to_name[email] = name
                    _email_to_person_id[email] = pid

        log.info(
            f"Email lookup built: {len(_email_to_name)} emails → "
            f"{len(set(_email_to_name.values()))} names"
        )
    except Exception as e:
        log.warning(f"Failed to build email lookup: {e}")

    return _email_to_name, _email_to_person_id


def chunk_calendar_events() -> list[Chunk]:
    ""





    chunks = []

    if not CALENDARS_DIR.exists():
        log.warning(f"Calendars dir not found: {CALENDARS_DIR}")
        return chunks

    account_dirs = sorted(d for d in CALENDARS_DIR.iterdir() if d.is_dir())
    total_events = 0
    log.info(f"Chunking calendar events from {len(account_dirs)} accounts...")


    email_to_name, email_to_pid = _build_email_lookup()

    for account_dir in account_dirs:
        events_path = account_dir / "events.parquet"
        if not events_path.exists():
            continue

        account_name = account_dir.name
        try:
            df = pd.read_parquet(events_path)
        except Exception as e:
            log.warning(f"Failed to read calendar {account_name}: {e}")
            continue

        for _, row in df.iterrows():

            event_id = str(row.get("id", row.get("event_id", "")))
            summary = str(row.get("summary", "")).strip()
            description = str(row.get("description", "")).strip()
            location = str(row.get("location", "")).strip()
            start = str(row.get("start_datetime", row.get("start", "")))[:16]
            end = str(row.get("end_datetime", row.get("end", "")))[:16]
            organizer = str(row.get("organizer", row.get("organizer_email", ""))).strip()

            raw_attendees = row.get("attendees", "")
            if isinstance(raw_attendees, list):
                attendee_items = [str(a).strip() for a in raw_attendees if a]
            else:
                attendee_items = [a.strip() for a in str(raw_attendees).split(",") if a.strip()]

            resolved_attendees = []
            event_person_ids = []
            for att in attendee_items:
                att_lower = att.lower().strip()
                if not att_lower or att_lower == "nan":
                    continue
                if "@" in att_lower and att_lower in email_to_name:
                    resolved_attendees.append(f"{email_to_name[att_lower]} ({att})")
                    pid = email_to_pid.get(att_lower, "")
                    if pid:
                        event_person_ids.append(pid)
                else:
                    resolved_attendees.append(att)
            attendees = ", ".join(resolved_attendees)


            org_lower = organizer.lower() if organizer and organizer != "nan" else ""
            if org_lower and "@" in org_lower and org_lower in email_to_name:
                organizer_display = f"{email_to_name[org_lower]} ({organizer})"
                org_pid = email_to_pid.get(org_lower, "")
                if org_pid and org_pid not in event_person_ids:
                    event_person_ids.append(org_pid)
            else:
                organizer_display = organizer


            if not summary or summary == "nan":
                continue


            text_parts = [f"Event: {summary}"]
            if description and description != "nan":

                desc_words = description.split()
                if len(desc_words) > 300:
                    description = " ".join(desc_words[:300]) + "..."
                text_parts.append(f"Description: {description}")
            if location and location != "nan":
                text_parts.append(f"Location: {location}")
            if attendees and attendees != "nan":
                text_parts.append(f"Attendees: {attendees}")

            text = "\n".join(text_parts)

            if estimate_tokens(text) < 5:
                continue

            date_str = start[:10] if start else ""
            time_range = f"{start} to {end}" if start and end else start


            parts_list = []
            if org_lower and org_lower in email_to_name:
                parts_list.append(email_to_name[org_lower])
            elif organizer and organizer != "nan":
                parts_list.append(organizer)
            for att in resolved_attendees:
                name_part = att.split(" (")[0] if " (" in att else att
                if name_part not in parts_list:
                    parts_list.append(name_part)
            participants_str = ", ".join(parts_list)
            person_ids_str = ", ".join(event_person_ids)

            context = (
                f"This chunk is a calendar event from account '{account_name}' "
                f"on {time_range}. "
                f"Organizer: {organizer_display if organizer and organizer != 'nan' else 'unknown'}."
            )

            chunks.append(
                Chunk(
                    text=text,
                    context=context,
                    source_type="calendar",
                    source_id=f"calendar:{account_name}:{event_id}",
                    date=date_str,
                    participants=participants_str,
                    person_ids=person_ids_str,
                )
            )
            total_events += 1

    log.info(
        f"  Calendar: {len(chunks)} chunks from {total_events} events across {len(account_dirs)} accounts"
    )
    return chunks


def chunk_knowledge_entities() -> list[Chunk]:
    ""





    chunks = []

    if not KNOWLEDGE_ENTITIES_DIR.exists():
        log.warning(f"Knowledge entities dir not found: {KNOWLEDGE_ENTITIES_DIR}")
        return chunks


    entity_files = []
    for subdir_name in ("person", "organization"):
        subdir = KNOWLEDGE_ENTITIES_DIR / subdir_name
        if subdir.exists():
            entity_files.extend(sorted(subdir.glob("*.json")))

    log.info(f"Chunking {len(entity_files)} knowledge entity profiles...")

    skipped = 0
    for fpath in entity_files:
        try:
            entity = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read entity {fpath.name}: {e}")
            continue

        if not isinstance(entity, dict):
            continue

        entity_id = entity.get("entity_id", fpath.stem)
        entity_type = entity.get("entity_type", "unknown")
        canonical_name = entity.get("canonical_name", entity_id)
        updated_at = entity.get("updated_at", "")
        date_str = updated_at[:10] if updated_at else ""
        facts = entity.get("facts", [])

        if not isinstance(facts, list) or not facts:
            skipped += 1
            continue


        facts = [f for f in facts if isinstance(f, dict) and f.get("confidence", 0) >= 0.3]
        if not facts:
            skipped += 1
            continue


        category_groups: dict[str, list[dict]] = {}
        for fact in facts:
            attr = fact.get("attribute", "unknown")
            category = attr.split(".")[0] if "." in attr else attr
            category_groups.setdefault(category, []).append(fact)


        all_lines = []
        for fact in facts:
            all_lines.append(f"{fact.get('attribute', '?')}: {fact.get('value', '?')}")
        total_text = "\n".join(all_lines)
        if estimate_tokens(total_text) < 15:
            skipped += 1
            continue


        categories_in_entity = sorted(category_groups.keys())
        for category, cat_facts in category_groups.items():
            lines = []
            for fact in cat_facts:
                attr = fact.get("attribute", "?")
                value = fact.get("value", "?")
                conf = fact.get("confidence", 0)
                lines.append(f"{attr}: {value} (confidence: {conf:.2f})")

            group_text = "\n".join(lines)
            text_chunks = _chunk_text_sliding_window(group_text, 500, 100)
            if not text_chunks:
                continue

            for i, chunk_text in enumerate(text_chunks):
                part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                context = (
                    f"This chunk contains facts about {entity_type} '{canonical_name}' "
                    f"({entity_id}). "
                    f"Category: {category}. "
                    f"All categories: {', '.join(categories_in_entity)}. "
                    f"Updated: {date_str}.{part_label}"
                )

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        context=context,
                        source_type="knowledge",
                        source_id=f"knowledge:{entity_id}:{category}:{i}",
                        date=date_str,
                        participants=canonical_name,
                        person_ids=entity_id if entity_type == "person" else "",
                    )
                )

    log.info(
        f"  Knowledge: {len(chunks)} chunks from {len(entity_files)} entities ({skipped} skipped)"
    )
    return chunks


def chunk_session_texts() -> list[Chunk]:
    ""





    chunks = []

    if not SESSIONS_TEXT_DIR.exists():
        log.warning(f"Session text dir not found: {SESSIONS_TEXT_DIR}")
        return chunks

    block_files = sorted(SESSIONS_TEXT_DIR.glob("block-*.txt"))
    if not block_files:
        log.warning(f"No block files found in {SESSIONS_TEXT_DIR}")
        return chunks

    log.info(f"Chunking {len(block_files)} session text blocks...")

    total_sessions = 0
    for block_file in block_files:
        try:
            content = block_file.read_text(encoding="utf-8")
        except OSError as e:
            log.warning(f"Failed to read {block_file.name}: {e}")
            continue


        block_num = block_file.stem.replace("block-", "")



        session_pattern = re.compile(
            r"={10,}\nSESSION:\s*([a-f0-9-]+)\.jsonl\n={10,}\n",
            re.MULTILINE,
        )

        parts = session_pattern.split(content)




        for idx in range(1, len(parts) - 1, 2):
            session_uuid = parts[idx].strip()
            session_text = parts[idx + 1].strip() if idx + 1 < len(parts) else ""

            if not session_text:
                continue


            ts_match = re.search(r"\[(\d{4}-\d{2}-\d{2})T", session_text)
            date_str = ts_match.group(1) if ts_match else ""


            text_chunks = _chunk_text_sliding_window(session_text, 500, 100)
            if not text_chunks:
                continue

            total_sessions += 1
            date_part = f"dated {date_str}" if date_str else "with unknown date"
            for i, chunk_text in enumerate(text_chunks):
                part_label = f" (part {i + 1}/{len(text_chunks)})" if len(text_chunks) > 1 else ""
                context = (
                    f"This chunk is from a Claude Code session {date_part}. "
                    f"Participants: {OWNER_LABEL}, Claude. "
                    f"Block {block_num}, session {session_uuid[:8]}.{part_label}"
                )

                chunks.append(
                    Chunk(
                        text=chunk_text,
                        context=context,
                        source_type="session",
                        source_id=f"session:{session_uuid}:{i}",
                        date=date_str,
                        participants=f"{OWNER_LABEL}, Claude",
                    )
                )

    log.info(
        f"  Session: {len(chunks)} chunks from {total_sessions} sessions "
        f"across {len(block_files)} blocks"
    )
    return chunks





def _is_mlx_model(model_name: str) -> bool:
    ""
    return "mlx-community" in model_name


def load_embedding_model(
    model_name: str | None = None,
    device_override: str | None = None,
    use_fp16: bool = False,
):
    ""








    models_to_try = [model_name] if model_name else EMBEDDING_MODELS

    for mname in models_to_try:
        try:
            if _is_mlx_model(mname):

                log.info(f"Loading MLX embedding model: {mname}")
                from mlx_embedding_adapter import MLXEmbeddingModel

                model = MLXEmbeddingModel(mname)
                dim = model.dim
                log.info(f"MLX model loaded: {mname} (dim={dim})")
                return model, mname, dim
            else:

                import torch
                from sentence_transformers import SentenceTransformer

                if device_override and device_override != "auto":
                    device = device_override
                elif torch.backends.mps.is_available():
                    device = "mps"
                elif torch.cuda.is_available():
                    device = "cuda"
                else:
                    device = "cpu"

                log.info(f"Loading embedding model: {mname} (device={device})")
                model = SentenceTransformer(mname, device=device)

                if device in ("mps", "cuda"):
                    model.half()
                    log.info(f"FP16 auto-enabled for {mname} on {device}")

                test_emb = model.encode(["test"], show_progress_bar=False)
                dim = test_emb.shape[1]
                log.info(f"Model loaded: {mname} (dim={dim}, device={device})")
                return model, mname, dim
        except Exception as e:
            log.warning(f"Failed to load {mname}: {e}")
            continue

    raise RuntimeError(f"Could not load any embedding model. Tried: {models_to_try}")


def embed_chunks(
    model,
    chunks: list[Chunk],
    batch_size: int = 256,
) -> list[list[float]]:
    ""



    from tqdm import tqdm

    texts = [f"{c.context}\n\n{c.text}" for c in chunks]

    log.info(f"Embedding {len(texts)} chunks (batch_size={batch_size})...")

    all_embeddings = []
    for i in tqdm(
        range(0, len(texts), batch_size),
        desc="Embedding",
        unit="batch",
        disable=not sys.stderr.isatty(),
    ):
        batch = texts[i : i + batch_size]
        embs = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)

        if hasattr(embs, "tolist"):
            all_embeddings.extend(embs.tolist())
        else:
            all_embeddings.extend([list(e) for e in embs])

    return all_embeddings





def rebuild_table_indices(tbl) -> None:
    ""




    try:
        tbl.create_fts_index(
            "text",
            language="Italian",
            stem=True,
            ascii_folding=True,
            lower_case=True,
            remove_stop_words=True,
            replace=True,
        )
        log.info("FTS index created on 'text' column (Italian stemming, ascii_folding)")
    except Exception as e:
        log.warning(f"FTS index creation failed (non-critical): {e}")

    try:
        tbl.create_index(
            metric="cosine",
            index_type="IVF_HNSW_SQ",
            num_partitions=16,
            replace=True,
        )
        log.info("IVF_HNSW_SQ vector index created (16 partitions)")
    except Exception as e:
        log.warning(f"HNSW-SQ index creation failed (non-critical, brute force used): {e}")


def build_lancedb_table(
    chunks: list[Chunk],
    vectors: list[list[float]],
    incremental: bool = False,
    table_name: str = TABLE_NAME,
    force_rebuild: bool = False,
    rebuild_indices: bool = True,
):
    ""




    import lancedb
    import pyarrow as pa

    VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    db_path = str(VECTOR_DB_DIR)

    log.info(f"Opening LanceDB at {db_path}")
    db = lancedb.connect(db_path)


    seen_ids: set[str] = set()
    records = []
    dedup_count = 0
    for chunk, vector in zip(chunks, vectors):
        if chunk.id in seen_ids:
            dedup_count += 1
            continue
        seen_ids.add(chunk.id)
        rec = chunk.to_dict()
        rec["vector"] = vector
        records.append(rec)

    if dedup_count:
        log.warning(f"Deduped {dedup_count} chunks with duplicate IDs before LanceDB write")

    if not records:
        log.warning("No records to insert")
        return

    dim = len(vectors[0])
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("context", pa.string()),
            pa.field("context_summary", pa.string()),
            pa.field("source_type", pa.string()),
            pa.field("source_id", pa.string()),
            pa.field("date", pa.string()),
            pa.field("indexed_at", pa.string()),
            pa.field("participants", pa.string()),
            pa.field("person_ids", pa.string()),
            pa.field("embedding_model", pa.string()),
            pa.field("pii_level", pa.int8()),
            pa.field("lang", pa.string()),
            pa.field("content_hash", pa.string()),
            pa.field("chunker_version", pa.string()),
            pa.field("schema_version", pa.int32()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )


    existing_tbl = None
    try:
        existing_tbl = db.open_table(table_name)
        log.info(f"Existing table '{table_name}' found ({existing_tbl.count_rows()} rows)")
    except Exception:
        log.info(f"No existing table '{table_name}'")

    if existing_tbl is not None and incremental:
        log.info(f"Incremental upsert: {len(records)} records via merge_insert")



        new_data = pa.Table.from_pylist(records, schema=schema)
        try:
            existing_tbl.merge_insert(
                "id"
            ).when_matched_update_all().when_not_matched_insert_all().execute(new_data)
            tbl = existing_tbl
            log.info(f"merge_insert complete ({tbl.count_rows()} total rows)")
        except (AttributeError, TypeError) as e:

            log.warning("merge_insert not available (%s), using delete-then-add fallback", e)
            new_ids = [r["id"] for r in records]
            if len(new_ids) > 500:
                raise RuntimeError(
                    f"Cannot upsert {len(new_ids)} records without merge_insert. "
                    f"Upgrade lancedb or use --full-rebuild."
                ) from e
            id_filter = " OR ".join(f"id = '{id_}'" for id_ in new_ids)
            try:
                existing_tbl.delete(id_filter)
                log.info("Deleted %d existing records before re-add", len(new_ids))
            except Exception as del_err:
                log.error("Failed to delete records: %s — aborting to prevent duplicates", del_err)
                raise RuntimeError(f"Delete failed for table '{table_name}'") from del_err
            existing_tbl.add(new_data)
            tbl = existing_tbl
            log.info("delete-then-add fallback complete (%d total rows)", tbl.count_rows())
    else:

        existing_rows = existing_tbl.count_rows() if existing_tbl is not None else 0

        if existing_rows > 100_000 and len(records) < existing_rows * 0.5 and not force_rebuild:
            raise RuntimeError(
                f"SAFETY: refusing to drop table '{table_name}' with {existing_rows:,} rows "
                f"to replace with only {len(records):,} records. "
                f"Use --incremental to upsert, or pass --force-rebuild to override."
            )

        tmp_table_name = f"{table_name}__rebuild_tmp"
        tmp_lance_dir = VECTOR_DB_DIR / f"{tmp_table_name}.lance"
        target_lance_dir = VECTOR_DB_DIR / f"{table_name}.lance"


        if tmp_lance_dir.exists():
            log.warning(
                "Removing leftover temp table from previous failed rebuild: %s", tmp_lance_dir
            )
            try:
                db.drop_table(tmp_table_name)
            except Exception:
                pass
            if tmp_lance_dir.exists():
                shutil.rmtree(tmp_lance_dir)


        log.info("Creating temp table '%s' with %d records", tmp_table_name, len(records))
        tbl = db.create_table(tmp_table_name, data=records, schema=schema)


        new_rows = tbl.count_rows()
        if existing_rows > 0 and new_rows == 0:
            log.error(
                "ABORT: new table has 0 rows but old had %d. Keeping old table. "
                "Temp table '%s' left for inspection.",
                existing_rows,
                tmp_table_name,
            )
            raise RuntimeError("Full rebuild validation failed: 0 rows in new table")

        log.info("Temp table validated: %d rows (old: %d)", new_rows, existing_rows)


        if existing_tbl is not None:
            log.info("Dropping old table '%s' (%d rows)", table_name, existing_rows)
            db.drop_table(table_name)

        if target_lance_dir.exists():
            shutil.rmtree(target_lance_dir)
        tmp_lance_dir.rename(target_lance_dir)


        tbl = db.open_table(table_name)
        verify_rows = tbl.count_rows()
        log.info("Safe rebuild complete: '%s' has %d rows", table_name, verify_rows)




    if rebuild_indices:
        rebuild_table_indices(tbl)

    log.info(f"LanceDB table '{table_name}' ready: {len(records)} vectors (dim={dim})")
    return tbl





def load_checkpoint(checkpoint_file: Path = CHECKPOINT_FILE) -> dict:
    ""
    if checkpoint_file.exists():
        try:
            return json.loads(checkpoint_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_checkpoint(checkpoint: dict, checkpoint_file: Path = CHECKPOINT_FILE):
    ""
    safe_write_json(checkpoint_file, checkpoint)
    log.info(f"Checkpoint saved: {checkpoint_file}")


def update_checkpoint(checkpoint: dict, source: str, count: int, partial: bool = False):
    ""





    prev = checkpoint.get(source, {})
    if partial:

        prev_count = prev.get("partial_count", 0)
        checkpoint[source] = {
            **prev,
            "partial_count": prev_count + count,
            "partial_timestamp": datetime.now(UTC).isoformat(),
        }
    else:

        checkpoint[source] = {
            "count": count,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_mtime": get_source_mtime(source),
        }









def _get_existing_ids_for_source(table_name: str, source: str) -> set[str]:
    ""




    try:
        import lancedb

        db = lancedb.connect(str(VECTOR_DB_DIR))
        tbl = db.open_table(table_name)
    except Exception:
        return set()
    try:
        df = (
            tbl.search()
            .where(f"source_type = '{source}'")
            .select(["id"])
            .limit(10_000_000)
            .to_pandas()
        )
        ids = set(df["id"].tolist())
        return ids
    except Exception as e:
        log.warning(f"  [{source}] could not load existing ids ({e}), skipping pre-filter")
        return set()









def _dedup_attio_tactiq(all_chunks: list[Chunk]) -> list[Chunk]:
    ""









    selections = build_transcript_selection_index()


    exclude_tactiq: set[str] = set()
    exclude_attio: set[str] = set()

    for sel in selections:
        if sel.winner == "attio" and sel.tactiq:
            exclude_tactiq.add(sel.tactiq.meeting_id)
            log.debug(
                f"Dedup: keep attio, drop tactiq '{sel.title[:50]}' "
                f"({sel.reason}) [a={sel.attio_words}w, t={sel.tactiq_words}w]"
            )
        elif sel.winner == "tactiq" and sel.attio:
            exclude_attio.add(sel.attio.meeting_id)
            log.debug(
                f"Dedup: keep tactiq, drop attio '{sel.title[:50]}' "
                f"({sel.reason}) [a={sel.attio_words}w, t={sel.tactiq_words}w]"
            )
        elif sel.winner == "skip":
            if sel.tactiq:
                exclude_tactiq.add(sel.tactiq.meeting_id)
            if sel.attio:
                exclude_attio.add(sel.attio.meeting_id)

    if not exclude_tactiq and not exclude_attio:
        return all_chunks


    filtered = []
    removed_tactiq = 0
    removed_attio = 0

    for chunk in all_chunks:
        if chunk.source_type == "tactiq":

            parts = chunk.source_id.split(":")
            meeting_id = parts[1] if len(parts) >= 2 else ""
            if meeting_id in exclude_tactiq:
                removed_tactiq += 1
                continue
        elif chunk.source_type == "attio_call":

            parts = chunk.source_id.split(":")
            file_stem = parts[1] if len(parts) >= 2 else ""
            if file_stem in exclude_attio:
                removed_attio += 1
                continue
        filtered.append(chunk)

    log.info(
        f"  Dedup: removed {removed_tactiq} tactiq + {removed_attio} attio chunks "
        f"(excluded {len(exclude_tactiq)} tactiq + {len(exclude_attio)} attio meetings)"
    )
    return filtered





def collect_chunks(
    sources: list[str],
    data: SBKData,
    incremental: bool = False,
    checkpoint_file: Path = CHECKPOINT_FILE,
    *,
    deep_gdrive: bool = False,
    fallite: dict[str, str] | None = None,
) -> tuple[list[Chunk], list[str]]:
    ""










    all_chunks = []
    skipped_sources: list[str] = []
    checkpoint = load_checkpoint(checkpoint_file) if incremental else {}

    chunkers = {
        "email": lambda: chunk_email_threads(data),
        "plaud": chunk_plaud_transcripts,
        "tactiq": chunk_tactiq_meetings,
        "slack": chunk_slack_interactions,
        "slack_dm": chunk_slack_dm_interactions,
        "notion": chunk_notion_entities,
        "network": chunk_network_profiles,
        "raw": chunk_raw_analysis,
        "whatsapp": chunk_whatsapp_chats,
        "wa_document": chunk_wa_documents,
        "wa_photo_ocr": chunk_wa_photo_ocr,
        "email_attachment": chunk_email_attachments,
        "attio_notes": chunk_attio_notes,
        "clickup": chunk_clickup_tasks,
        "docusign": chunk_docusign_contratti,
        "chatgpt": chunk_chatgpt_conversations,
        "attio_call": chunk_attio_call_transcripts,
        "voice_memo": chunk_voice_memo_transcripts,
        "gdrive": lambda: chunk_gdrive_documents(deep=deep_gdrive),
        "domain": chunk_domain_documents,
        "calendar": chunk_calendar_events,
        "knowledge": chunk_knowledge_entities,
        "session": chunk_session_texts,
    }

    for source in sources:
        if source not in chunkers:
            log.warning(f"Unknown source: {source}")
            continue


        if incremental and source in checkpoint:
            prev = checkpoint[source]
            prev_mtime = prev.get("source_mtime", 0)
            current_mtime = get_source_mtime(source)
            if prev_mtime > 0 and current_mtime <= prev_mtime:
                log.info(
                    f"  {source}: SKIPPED (data unchanged, "
                    f"mtime {current_mtime:.0f} <= checkpoint {prev_mtime:.0f})"
                )
                skipped_sources.append(source)
                continue

        t0 = time.time()
        try:
            source_chunks = chunkers[source]()
            elapsed = time.time() - t0
            log.info(f"  {source}: {len(source_chunks)} chunks in {elapsed:.1f}s")
            all_chunks.extend(source_chunks)
        except Exception as e:
            log.error(f"  {source}: FAILED ({e})")
            if fallite is not None:
                fallite[source] = f"{type(e).__name__}: {e}"


    if "attio_call" in sources and "tactiq" in sources:
        pre_dedup = len(all_chunks)
        all_chunks = _dedup_attio_tactiq(all_chunks)
        if len(all_chunks) < pre_dedup:
            log.info(f"  Dedup total: {pre_dedup - len(all_chunks)} tactiq chunks removed")

    return all_chunks, skipped_sources


def _scrivi_fonti_non_indicizzate(sources: list[str], fallite: dict[str, str]) -> None:
    ""




    try:
        prima = json.loads(FONTI_NON_INDICIZZATE.read_text(encoding="utf-8")).get("fonti") or {}
    except (OSError, ValueError, AttributeError):
        prima = {}
    fonti = {k: v for k, v in prima.items() if k not in sources and k in ALL_SOURCES}
    fonti.update(fallite)
    safe_write_json(
        FONTI_NON_INDICIZZATE,
        {"quando": datetime.now(UTC).isoformat(), "fonti": fonti},
        indent=1,
    )


def _write_model_info(model_name: str, dim: int) -> None:
    ""



    backend = "mlx" if _is_mlx_model(model_name) else "sentence-transformers"
    info = {"model": model_name, "backend": backend, "dim": dim}
    safe_write_json(MODEL_INFO_FILE, info)
    log.info(f"  Wrote model-info.json: {model_name} ({backend}, dim={dim})")


def _auto_retention(table_name: str, older_than_hours: int = 72) -> None:
    ""





    from datetime import timedelta

    try:
        import lancedb

        db = lancedb.connect(str(VECTOR_DB_DIR))
        tbl = db.open_table(table_name)
        log.info(f"  Auto-retention: cleanup versions > {older_than_hours}h")
        tbl.cleanup_old_versions(older_than=timedelta(hours=older_than_hours))
        log.info("  Auto-retention: completed")
    except Exception as e:
        log.warning(f"  Auto-retention skipped (non-critical): {e}")


def _rebuild_ann_index() -> None:
    ""



    import lancedb

    db = lancedb.connect(str(VECTOR_DB_DIR))
    try:
        tbl = db.open_table(TABLE_NAME)
    except Exception:
        log.error(f"Table '{TABLE_NAME}' not found. Nothing to rebuild.")
        sys.exit(1)

    row_count = tbl.count_rows()
    log.info(f"Rebuilding ANN index for '{TABLE_NAME}' ({row_count:,} rows)")


    try:
        tbl.drop_index("vector_idx")
        log.info("  Dropped old vector index")
    except Exception:
        log.info("  No existing vector index to drop")


    if row_count > 10_000:
        num_partitions = min(64, max(16, int(row_count**0.5 / 4)))
        log.info(f"  Creating IVF_HNSW_SQ index (partitions={num_partitions})")
        tbl.create_index(
            metric="cosine",
            num_partitions=num_partitions,
            index_type="IVF_HNSW_SQ",
            replace=True,
        )
        log.info("  ANN index rebuilt successfully (IVF_HNSW_SQ)")
    else:
        log.info("  Table too small for HNSW-SQ, flat scan will be used")


def _do_swap_bge():
    ""








    import shutil

    import lancedb

    log.info("\n=== BGE-M3 Swap: sbk_chunks_bge -> sbk_chunks ===")

    db = lancedb.connect(str(VECTOR_DB_DIR))


    try:
        bge_tbl = db.open_table(TABLE_NAME_BGE)
        bge_rows = bge_tbl.count_rows()
        log.info(f"  BGE table found: {bge_rows} rows")
    except Exception:
        log.error(f"  BGE table '{TABLE_NAME_BGE}' not found. Run --bge-upgrade first.")
        sys.exit(1)

    if bge_rows == 0:
        log.error("  BGE table is empty. Build not complete.")
        sys.exit(1)


    bge_checkpoint = load_checkpoint(CHECKPOINT_FILE_BGE)
    indexed_sources = set(bge_checkpoint.keys())
    expected_sources = set(ALL_SOURCES)
    missing = expected_sources - indexed_sources
    if missing:
        log.error(f"  BGE checkpoint missing sources: {', '.join(sorted(missing))}")
        log.error("  Build not complete. Run --bge-upgrade --incremental to finish.")
        sys.exit(1)

    total_bge_chunks = sum(s.get("count", 0) for s in bge_checkpoint.values())
    log.info(f"  BGE checkpoint: {len(indexed_sources)} sources, {total_bge_chunks} total chunks")


    try:
        old_tbl = db.open_table(TABLE_NAME)
        old_rows = old_tbl.count_rows()
        log.info(f"  Dropping old table '{TABLE_NAME}' ({old_rows} rows, dim=384)")
        db.drop_table(TABLE_NAME)
    except Exception:
        log.info(f"  No old table '{TABLE_NAME}' to drop")


    bge_lance_dir = VECTOR_DB_DIR / f"{TABLE_NAME_BGE}.lance"
    target_lance_dir = VECTOR_DB_DIR / f"{TABLE_NAME}.lance"

    if target_lance_dir.exists():
        bak_dir = target_lance_dir.with_suffix(".lance.bak")
        log.info(f"  Backing up {target_lance_dir} -> {bak_dir}")
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
        target_lance_dir.rename(bak_dir)

    if bge_lance_dir.exists():
        log.info(f"  Renaming {bge_lance_dir.name} -> {target_lance_dir.name}")
        bge_lance_dir.rename(target_lance_dir)

        bak_dir = target_lance_dir.with_suffix(".lance.bak")
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
    else:
        log.warning(
            f"  BGE lance dir not found at {bge_lance_dir}, table may use different storage"
        )


    log.info(f"  Copying checkpoint: {CHECKPOINT_FILE_BGE.name} -> {CHECKPOINT_FILE.name}")
    shutil.copy2(CHECKPOINT_FILE_BGE, CHECKPOINT_FILE)


    try:
        new_tbl = db.open_table(TABLE_NAME)
        new_rows = new_tbl.count_rows()
        log.info("\n=== Swap Complete ===")
        log.info(f"  Table '{TABLE_NAME}': {new_rows} rows (dim=1024, BGE-M3)")
        log.info("  Old 384-dim index removed")
        log.info("  Search will auto-detect dim=1024 and use BGE-M3 model")
    except Exception as e:
        log.warning(f"  Post-swap verification failed: {e}")
        log.info("  The lance directory was renamed. You may need to re-open the DB.")


    _write_model_info("BAAI/bge-m3", 1024)


def _do_swap_qwen():
    ""








    import shutil

    import lancedb

    log.info("\n=== Qwen3 Swap: sbk_chunks_qwen -> sbk_chunks ===")

    db = lancedb.connect(str(VECTOR_DB_DIR))


    try:
        qwen_tbl = db.open_table(TABLE_NAME_QWEN)
        qwen_rows = qwen_tbl.count_rows()
        log.info(f"  Qwen table found: {qwen_rows} rows")
    except Exception:
        log.error(f"  Qwen table '{TABLE_NAME_QWEN}' not found. Run --qwen-upgrade first.")
        sys.exit(1)

    if qwen_rows == 0:
        log.error("  Qwen table is empty. Build not complete.")
        sys.exit(1)


    qwen_checkpoint = load_checkpoint(CHECKPOINT_FILE_QWEN)
    indexed_sources = set(qwen_checkpoint.keys())
    expected_sources = set(ALL_SOURCES)
    missing = expected_sources - indexed_sources
    if missing:
        log.error(f"  Qwen checkpoint missing sources: {', '.join(sorted(missing))}")
        log.error("  Build not complete. Run --qwen-upgrade --incremental to finish.")
        sys.exit(1)

    total_qwen_chunks = sum(s.get("count", 0) for s in qwen_checkpoint.values())
    log.info(f"  Qwen checkpoint: {len(indexed_sources)} sources, {total_qwen_chunks} total chunks")


    try:
        old_tbl = db.open_table(TABLE_NAME)
        old_rows = old_tbl.count_rows()
        log.info(f"  Dropping old table '{TABLE_NAME}' ({old_rows} rows)")
        db.drop_table(TABLE_NAME)
    except Exception:
        log.info(f"  No old table '{TABLE_NAME}' to drop")


    qwen_lance_dir = VECTOR_DB_DIR / f"{TABLE_NAME_QWEN}.lance"
    target_lance_dir = VECTOR_DB_DIR / f"{TABLE_NAME}.lance"

    if target_lance_dir.exists():
        bak_dir = target_lance_dir.with_suffix(".lance.bak")
        log.info(f"  Backing up {target_lance_dir} -> {bak_dir}")
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
        target_lance_dir.rename(bak_dir)

    if qwen_lance_dir.exists():
        log.info(f"  Renaming {qwen_lance_dir.name} -> {target_lance_dir.name}")
        qwen_lance_dir.rename(target_lance_dir)

        bak_dir = target_lance_dir.with_suffix(".lance.bak")
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
    else:
        log.warning(
            f"  Qwen lance dir not found at {qwen_lance_dir}, table may use different storage"
        )


    log.info(f"  Copying checkpoint: {CHECKPOINT_FILE_QWEN.name} -> {CHECKPOINT_FILE.name}")
    shutil.copy2(CHECKPOINT_FILE_QWEN, CHECKPOINT_FILE)


    try:
        new_tbl = db.open_table(TABLE_NAME)
        new_rows = new_tbl.count_rows()
        log.info("\n=== Swap Complete ===")
        log.info(f"  Table '{TABLE_NAME}': {new_rows} rows (dim=1024, Qwen3-Embedding via MLX)")
        log.info("  Old index removed")
        log.info("  Search will auto-detect dim=1024 and use Qwen3 MLX model")
    except Exception as e:
        log.warning(f"  Post-swap verification failed: {e}")
        log.info("  The lance directory was renamed. You may need to re-open the DB.")


    _write_model_info("mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ", 1024)


def main():
    parser = argparse.ArgumentParser(
        description="SBK L3 Vector Index Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process new data since last checkpoint",
    )
    parser.add_argument(
        "--source",
        choices=ALL_SOURCES,
        help="Process a single source type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count chunks without embedding or storing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="Embedding batch size (default: 256)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override embedding model name",
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["cpu", "mps", "cuda", "auto"],
        default="auto",
        help="Force device for embedding (default: auto-detect)",
    )
    parser.add_argument(
        "--bge-upgrade",
        action="store_true",
        help="Build BGE-M3 index in separate table (sbk_chunks_bge)",
    )
    parser.add_argument(
        "--fp16",
        action="store_true",
        help="Use FP16 for faster embedding (MPS/CUDA only)",
    )
    parser.add_argument(
        "--swap-bge",
        action="store_true",
        help="Swap sbk_chunks_bge -> sbk_chunks (after BGE build complete)",
    )
    parser.add_argument(
        "--qwen-upgrade",
        action="store_true",
        help="Build Qwen3 MLX index in separate table (sbk_chunks_qwen)",
    )
    parser.add_argument(
        "--swap-qwen",
        action="store_true",
        help="Swap sbk_chunks_qwen -> sbk_chunks (after Qwen3 build complete)",
    )
    parser.add_argument(
        "--rebuild-ann",
        action="store_true",
        help="Drop and rebuild ANN index on primary table (fix corrupted _indices/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--deep-gdrive",
        action="store_true",
        help="Index ALL GDrive files (PDF, DOCX, XLSX, CSV, TXT) not just recent .md",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force full table rebuild even if existing table has >100K rows",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-index")
    log.info("SBK L3 Vector Index Builder")
    log.info(f"  LanceDB path: {VECTOR_DB_DIR}")
    log.info(f"  Incremental: {args.incremental}")
    log.info(f"  Dry run: {args.dry_run}")


    if not args.dry_run and not args.swap_bge and not args.swap_qwen and not args.rebuild_ann:
        if not acquire_pid_lock("l3-index", logger=log):


            log.warning("l3-index: lock held by another instance, exit 75")
            sys.exit(75)

    try:
        _main_inner(args)
    finally:
        release_pid_lock("l3-index")


def _main_inner(args):
    t_start = time.time()


    if args.swap_bge:
        _do_swap_bge()
        return
    if args.swap_qwen:
        _do_swap_qwen()
        return
    if args.rebuild_ann:
        _rebuild_ann_index()
        return


    if args.qwen_upgrade:
        active_table = TABLE_NAME_QWEN
        active_checkpoint_file = CHECKPOINT_FILE_QWEN
        args.model = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"
        log.info("Qwen3 MLX upgrade mode: writing to separate table 'sbk_chunks_qwen'")

    elif args.bge_upgrade:
        active_table = TABLE_NAME_BGE
        active_checkpoint_file = CHECKPOINT_FILE_BGE

        args.model = "BAAI/bge-m3"
        log.info("BGE-M3 upgrade mode: writing to separate table 'sbk_chunks_bge'")
    else:
        active_table = TABLE_NAME
        active_checkpoint_file = CHECKPOINT_FILE


    sources = [args.source] if args.source else ALL_SOURCES
    log.info(f"  Sources: {', '.join(sources)}")


    data = SBKData()


    log.info("\n=== Chunking ===")
    fallite: dict[str, str] = {}
    all_chunks, skipped_sources = collect_chunks(
        sources,
        data,
        args.incremental,
        checkpoint_file=active_checkpoint_file,
        deep_gdrive=getattr(args, "deep_gdrive", False),
        fallite=fallite,
    )
    if fallite:
        log.error(f"  NOT indexed this run: {', '.join(sorted(fallite))}")

    if not args.dry_run and active_table == TABLE_NAME:
        _scrivi_fonti_non_indicizzate(sources, fallite)


    log.info("\n=== Chunk Summary ===")
    source_counts = {}
    total_tokens = 0
    for c in all_chunks:
        source_counts[c.source_type] = source_counts.get(c.source_type, 0) + 1
        total_tokens += estimate_tokens(c.text)

    for src, count in sorted(source_counts.items()):
        log.info(f"  {src}: {count} chunks")
    if skipped_sources:
        log.info(f"  SKIPPED (unchanged): {', '.join(skipped_sources)}")
    log.info(f"  TOTAL: {len(all_chunks)} chunks, ~{total_tokens:,} estimated tokens")

    if args.dry_run:
        log.info("\n=== Dry run complete (no embedding or storage) ===")
        elapsed = time.time() - t_start
        log.info(f"Elapsed: {elapsed:.1f}s")
        return

    if not all_chunks:
        if skipped_sources:
            log.info("All sources unchanged — nothing to re-index")
        else:
            log.warning("No chunks to process, exiting")
        return


    log.info("\n=== Loading Embedding Model ===")
    try:
        model, model_name, dim = load_embedding_model(
            args.model, device_override=args.device, use_fp16=args.fp16
        )
    except RuntimeError as e:
        # Usually a first run without network: the local model is downloaded once from Hugging Face.
        log.error(
            "%s. The search index needs a local embedding model: the first run downloads it from "
            "Hugging Face, so it needs the network once (or a model already in your Hugging Face cache).",
            e,
        )
        # EX_CONFIG: a setup problem, the pipeline does not retry it (xs-pipeline-run EXIT_CONFIGURAZIONE)
        sys.exit(78)



    total_embedded = 0
    indices_dirty = False
    checkpoint = load_checkpoint(active_checkpoint_file)




    try:
        import lancedb as _ldb

        _t = _ldb.connect(str(VECTOR_DB_DIR)).open_table(active_table)
        _last_rebuilt = checkpoint.get("_rebuild_state", {}).get("last_rebuilt_rows", 0)
        if _t.count_rows() > _last_rebuilt:
            log.info(
                f"  Stale indices detected (rows {_t.count_rows()} > last_rebuilt {_last_rebuilt}), "
                f"forcing rebuild at end of run"
            )
            indices_dirty = True
    except Exception:
        pass


    chunks_by_source = {}
    for c in all_chunks:
        chunks_by_source.setdefault(c.source_type, []).append(c)


    for src in sources:

        if src in skipped_sources:
            prev_count = checkpoint.get(src, {}).get("count", 0)
            total_embedded += prev_count
            continue






        src_chunks = chunks_by_source.get(src, [])
        if not src_chunks:
            continue


        partial_done = checkpoint.get(src, {}).get("partial_count", 0)
        if partial_done > 0 and partial_done < len(src_chunks):
            log.info(f"\n=== [{src}] Resuming from chunk {partial_done}/{len(src_chunks)} ===")
            src_chunks = src_chunks[partial_done:]
        elif partial_done > 0:
            log.info(
                f"\n=== [{src}] Partial checkpoint covers all {len(src_chunks)} chunks, re-embedding ==="
            )

            partial_done = 0






        if args.incremental:
            existing_ids = _get_existing_ids_for_source(active_table, src)
            if existing_ids:
                pre_filter_count = len(src_chunks)
                src_chunks = [c for c in src_chunks if c.id not in existing_ids]
                skipped_existing = pre_filter_count - len(src_chunks)
                log.info(
                    f"  [{src}] pre-filter (incremental): {pre_filter_count} computed, "
                    f"{skipped_existing} already indexed, {len(src_chunks)} new to embed"
                )
                if not src_chunks:
                    log.info(f"  [{src}] nothing new to index, advancing checkpoint")

                    update_checkpoint(checkpoint, src, pre_filter_count + partial_done)
                    save_checkpoint(checkpoint, active_checkpoint_file)
                    total_embedded += pre_filter_count
                    continue



        CHECKPOINT_BATCH_SIZE = 10_000
        use_batched = len(src_chunks) > CHECKPOINT_BATCH_SIZE

        log.info(
            f"\n=== [{src}] Embedding {len(src_chunks)} chunks {'(batched)' if use_batched else ''} ==="
        )
        t_src = time.time()

        if use_batched:

            for batch_start in range(0, len(src_chunks), CHECKPOINT_BATCH_SIZE):
                batch_end = min(batch_start + CHECKPOINT_BATCH_SIZE, len(src_chunks))
                batch_chunks = src_chunks[batch_start:batch_end]
                batch_num = batch_start // CHECKPOINT_BATCH_SIZE + 1
                total_batches = (
                    len(src_chunks) + CHECKPOINT_BATCH_SIZE - 1
                ) // CHECKPOINT_BATCH_SIZE

                log.info(
                    f"  [{src}] Batch {batch_num}/{total_batches}: embedding {len(batch_chunks)} chunks"
                )
                vectors = embed_chunks(model, batch_chunks, batch_size=args.batch_size)



                is_incremental = args.incremental or (total_embedded > 0) or args.source
                build_lancedb_table(
                    batch_chunks,
                    vectors,
                    incremental=is_incremental,
                    table_name=active_table,
                    force_rebuild=getattr(args, "force_rebuild", False),
                    rebuild_indices=False,
                )
                if vectors:
                    indices_dirty = True

                total_embedded += len(vectors)


                if batch_end < len(src_chunks):
                    update_checkpoint(checkpoint, src, len(batch_chunks), partial=True)
                    save_checkpoint(checkpoint, active_checkpoint_file)
                    log.info(
                        f"  [{src}] Partial checkpoint saved ({batch_end}/{len(src_chunks)} chunks)"
                    )

                del vectors
                import gc

                gc.collect()


            update_checkpoint(checkpoint, src, len(src_chunks) + partial_done)
            save_checkpoint(checkpoint, active_checkpoint_file)
        else:
            vectors = embed_chunks(model, src_chunks, batch_size=args.batch_size)
            log.info(f"  [{src}] Embedded {len(vectors)} chunks (dim={dim})")

            log.info(f"  [{src}] Writing to LanceDB...")
            is_incremental = args.incremental or (total_embedded > 0) or args.source
            build_lancedb_table(
                src_chunks,
                vectors,
                incremental=is_incremental,
                table_name=active_table,
                force_rebuild=getattr(args, "force_rebuild", False),
                rebuild_indices=False,
            )
            if vectors:
                indices_dirty = True

            total_embedded += len(vectors)
            update_checkpoint(checkpoint, src, len(src_chunks))
            save_checkpoint(checkpoint, active_checkpoint_file)

        elapsed_src = time.time() - t_src
        log.info(
            f"  [{src}] Done in {elapsed_src:.1f}s ({elapsed_src / 60:.1f}m). Total so far: {total_embedded}"
        )


        try:
            del vectors
        except UnboundLocalError:
            pass
        del src_chunks
        import gc

        gc.collect()
        if _is_mlx_model(model_name):
            try:
                import mlx.core as mx

                mx.clear_cache()
            except (AttributeError, Exception):
                try:
                    mx.metal.clear_cache()
                except Exception:
                    pass
        else:
            try:
                import torch

                torch.mps.empty_cache()
                torch.mps.synchronize()
            except Exception:
                pass


    if indices_dirty:
        log.info("\n=== Rebuild indices (deferred, A10) ===")
        t_idx = time.time()
        try:
            import lancedb

            db = lancedb.connect(str(VECTOR_DB_DIR))
            tbl = db.open_table(active_table)
            rebuild_table_indices(tbl)
            log.info(f"  Index rebuild completed in {time.time() - t_idx:.1f}s")

            checkpoint["_rebuild_state"] = {
                "last_rebuilt_rows": tbl.count_rows(),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            save_checkpoint(checkpoint, active_checkpoint_file)
        except Exception as e:
            log.warning(f"  Final index rebuild failed (non-critical): {e}")
    else:
        log.info("No new chunk written, skip index rebuild")


    if active_table == TABLE_NAME:
        _write_model_info(model_name, dim)





    if active_table == TABLE_NAME and total_embedded > 0:
        _auto_retention(active_table, older_than_hours=72)


    elapsed = time.time() - t_start
    log.info("\n=== Index Build Complete ===")
    log.info(f"  Total chunks: {total_embedded}")
    log.info(f"  Vector dimension: {dim}")
    log.info(f"  Model: {model_name}")
    log.info(f"  Table: {active_table}")
    log.info(f"  Elapsed: {elapsed:.1f}s ({elapsed / 60:.1f}m)")
    log.info(f"  DB path: {VECTOR_DB_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-index", source="l3-index", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
