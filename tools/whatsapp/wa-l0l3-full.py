#!/usr/bin/env python3
"""WhatsApp import of the chats you export from the phone, then a local analysis.

Status: TESTED. This is one of the two import scripts of the path the author uses (export the
chats from the phone, then import them); the other is wa-l0-import-history.py. Live reading of
WhatsApp is not set up.

What it reads, from <data root>/whatsapp/raw/ and <data root>/whatsapp/raw-exports/ (more folders
with --zip-dir, searched recursively):
  - iPhone:  "WhatsApp Chat - <name>.zip" (with "_chat.txt" inside), or the same name as .txt
  - Android: "WhatsApp Chat with <name>.zip" or "WhatsApp Chat with <name>.txt"
Lines with a 24-hour or a 12-hour (AM/PM) clock, dates with "/", "." or "-", day/month or
month/day (worked out from the file). Your own messages are recognised through "owner" and
"own_names" in sbk.config.json and written under the "owner" name.

Phases:
  1 extract  find the exports, keep the largest when the same chat was exported twice
  2 parse    one JSON per chat in <data root>/whatsapp/chats/, merged message by message with what
             is already there (nothing is removed; the previous file is kept in chats/_superseded/)
  3 analysis per-chat statistics in <data root>/whatsapp/analysis/ (skip with --skip-analysis)
  4 phones   phone numbers matched to names from the contacts you already imported

Everything runs on your machine; nothing is sent anywhere.

    uv run python tools/whatsapp/wa-l0l3-full.py --list            # dry run: which exports it found
    uv run python tools/whatsapp/wa-l0l3-full.py --skip-analysis   # import
    uv run python tools/whatsapp/wa-l0l3-full.py --zip-dir ~/Downloads/whatsapp --skip-analysis
"""























from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import shutil
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path





_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
PROJECT_DIR = _TOOLS_DIR
from text_utils import normalize_name, normalize_phone  # noqa: E402

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    OWN_NAMES_NORMALIZED,
    OWNER_NAME,
    safe_write_json,
    user_cfg,
)


if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import wa_ricevuta  # noqa: E402

SBK_DATA = DATA_ROOT



ZIP_FOLDERS = [
    SBK_DATA / "whatsapp" / "raw",
    SBK_DATA / "whatsapp" / "raw-exports",
]



_DEDUP_SUFFIX_RE = re.compile(
    r"(\s*\(\d+\)|[\s-]+\d|[\s-]+new|[\s-]+copia|[\s-]+copy)+$", re.IGNORECASE
)


def dedup_key(chat_name: str) -> str:
    """The chat's key without the export prefix and the "(1)", "copy" suffixes of a re-export."""

    base = re.sub(r"^WhatsApp Chat\s*-\s*", "", chat_name).strip()
    base = _DEDUP_SUFFIX_RE.sub("", base).strip()
    return sanitize_filename(base)


# File names of the phone's own export: iPhone "WhatsApp Chat - <name>", Android
# "WhatsApp Chat with <name>"; a .zip (with media, or the iPhone default) or a bare .txt.
EXPORT_GLOBS = (
    "WhatsApp Chat - *.zip",
    "WhatsApp Chat with *.zip",
    "WhatsApp Chat - *.txt",
    "WhatsApp Chat with *.txt",
)
_ANDROID_PREFIX_RE = re.compile(r"^WhatsApp Chat with\s+", re.IGNORECASE)


def chat_name_from_file(path: Path) -> str:
    """'WhatsApp Chat - <name>' for both phones, so every later step sees one form."""
    return _ANDROID_PREFIX_RE.sub("WhatsApp Chat - ", path.stem).strip()


def find_zips(
    folders: list[Path], recursive_extra: list[Path] | None = None
) -> list[tuple[Path, Path]]:
    """(folder, file) for every chat export (.zip or .txt) in the drop folders."""
    out: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for folder, recursive in [(f, False) for f in folders] + [
        (f, True) for f in (recursive_extra or [])
    ]:
        if not folder.exists():
            # the two default folders are optional; a folder you passed with --zip-dir is not
            (log.warning if recursive else log.info)(f"  Folder not found: {folder}")
            continue
        for pattern in EXPORT_GLOBS:
            hits = folder.rglob(pattern) if recursive else folder.glob(pattern)
            for z in sorted(hits):
                if z not in seen and not z.name.startswith("._"):
                    seen.add(z)
                    out.append((folder, z))
    return out


CHATS_DIR = SBK_DATA / "whatsapp" / "chats"
ANALYSIS_DIR = SBK_DATA / "whatsapp" / "analysis"

RICEVUTA_DIR = SBK_DATA / "whatsapp"
ULTIMO_GIRO: dict = {}


IPHONE_CONTACTS = SBK_DATA / "contacts" / "processed" / "contacts-iphone.parquet"
ENTITY_MAP = SBK_DATA / "enriched" / "entity-map.json"

log = logging.getLogger("whatsapp-pipeline")





# You, as sbk.config.json says: "owner" plus every spelling in "own_names".
OWNER_CANONICAL = OWNER_NAME
OWNER_NAMES = {normalize_name(n) for n in OWN_NAMES_NORMALIZED} | {normalize_name(OWNER_NAME)}






# A line of the export starts with the date and the time. iPhone: "[14/03/2025, 21:05:12] Name: text"
# (or "[3/14/25, 9:05:12 PM] ..."); Android: "14/03/2025, 21:05 - Name: text" (or "3/14/25, 9:05 PM - ...").
# Groups: date, time, a/p of AM/PM (or None), then sender and text, or the system text.
_DATE = r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
_TIME = r"\d{1,2}[:.]\d{2}(?:[:.]\d{2})?"
_AMPM = r"(?:[\s  ]*([AaPp])\.?\s?[Mm]\.?)?"

MSG_PATTERN_BRACKET = re.compile(
    rf"^\[({_DATE}),?\s+({_TIME}){_AMPM}\]\s+(.+?):\s(.*)", re.DOTALL
)


MSG_PATTERN_NOBRACKET = re.compile(
    rf"^({_DATE}),?\s+({_TIME}){_AMPM}\s+-\s+(.+?):\s(.*)", re.DOTALL
)


SYS_PATTERN_BRACKET = re.compile(rf"^\[({_DATE}),?\s+({_TIME}){_AMPM}\]\s+(.+)", re.DOTALL)


# Android system line (no sender): "14/03/2025, 21:05 - Mia Conti added Leo Park".
SYS_PATTERN_NOBRACKET = re.compile(rf"^({_DATE}),?\s+({_TIME}){_AMPM}\s+-\s+(.+)", re.DOTALL)


SYSTEM_TEXTS = {
    "messages and calls are end-to-end encrypted",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "document omitted",
    "contact card omitted",
    "gif omitted",
    "location:",
    "live location shared",
    "this message was deleted",
    "you deleted this message",
    "missed voice call",
    "missed video call",
    "null",
    "<media omitted>",
}

SYSTEM_ACTION_RE = [
    re.compile(r"^.+ created group .+$"),
    re.compile(r"^.+ added .+$"),
    re.compile(r"^.+ removed .+$"),
    re.compile(r"^.+ left$"),
    re.compile(r"^.+ changed this group.+$"),
    re.compile(r"^.+ changed the subject .+$"),
    re.compile(r"^.+ changed the group description$"),
    re.compile(r"^you were added$", re.IGNORECASE),
    re.compile(r"^.+ turned on disappearing messages.+$"),
    re.compile(r"^.+ turned off disappearing messages.+$"),
    re.compile(r"^.+ pinned a message$"),
]


MEDIA_PATTERNS = {
    "image": re.compile(r"(image omitted|<attached:.*\.(jpg|jpeg|png|gif|webp)>)", re.I),
    "video": re.compile(r"(video omitted|<attached:.*\.(mp4|mov|avi|3gp)>)", re.I),
    "audio": re.compile(r"(audio omitted|<attached:.*\.(opus|ogg|m4a|mp3|wav)>)", re.I),
    "document": re.compile(
        r"(document omitted|<attached:.*\.(pdf|doc|docx|xls|xlsx|ppt|csv)>)", re.I
    ),
    "sticker": re.compile(r"sticker omitted", re.I),
}


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


MONEY_RE = re.compile(
    r"(?:€|EUR|USD|\$|£)\s*[\d,.]+[kKmM]?"
    r"|[\d,.]+\s*(?:€|EUR|USD|\$|£|euro|euros|dollari|dollars)"
    r"|[\d,.]+[kKmM]\s*(?:€|EUR|USD|\$|£)?",
    re.I,
)



# Company names counted in the analysis: "whatsapp.company_keywords" in sbk.config.json (empty = none).
COMPANY_KEYWORDS: list[str] = [
    str(k) for k in (user_cfg("whatsapp.company_keywords", []) or []) if str(k).strip()
]


TOPIC_KEYWORDS = {
    "fundraising": [
        "fundraising",
        "investor",
        "investitori",
        "round",
        "valuation",
        "safe",
        "cap table",
        "bridge",
        "serie a",
        "pitch",
        "deck",
        "data room",
    ],
    "business_ops": [
        "revenue",
        "fatturato",
        "ebitda",
        "p&l",
        "budget",
        "costi",
        "hiring",
        "team",
        "assunzione",
        "licenziamento",
        "onboarding",
    ],
    "product": [
        "platform",
        "piattaforma",
        "feature",
        "release",
        "bug",
        "deploy",
        "api",
        "dashboard",
        "tool",
        "software",
        "app",
    ],
    "legal": [
        "contratto",
        "contract",
        "nda",
        "avvocato",
        "lawyer",
        "causa",
        "legal",
        "tribunale",
        "court",
        "dispute",
    ],
    "real_estate": [
        "immobile",
        "casa",
        "affitto",
        "rent",
        "yield",
        "appartamento",
        "ristrutturazione",
        "renovation",
    ],
    "health": ["health", "salute", "grant"],
    "deals_ma": [
        "acquisition",
        "acquisizione",
        "deal",
        "m&a",
        "merger",
        "due diligence",
        "dd",
        "loi",
        "term sheet",
    ],
    "finance": [
        "banca",
        "bank",
        "conto",
        "account",
        "pagamento",
        "payment",
        "fattura",
        "invoice",
        "bonifico",
        "transfer",
    ],
    "travel": [
        "volo",
        "flight",
        "hotel",
        "airport",
        "aeroporto",
        "conferenza",
        "conference",
    ],
    "personal": [
        "matrimonio",
        "wedding",
        "compleanno",
        "birthday",
        "vacanza",
        "holiday",
        "cena",
        "dinner",
        "pranzo",
        "lunch",
    ],
}







def is_owner(name: str) -> bool:
    """True when `name` is you (sbk.config.json "owner" / "own_names")."""
    return normalize_name(name) in OWNER_NAMES


def sanitize_filename(name: str) -> str:
    """The file name of a chat: lower case, dashes, no export prefix."""
    name = re.sub(r"^WhatsApp Chat\s*-\s*", "", name)
    name = _ANDROID_PREFIX_RE.sub("", name)
    name = re.sub(r"[^\w\s\-\+]", "", name)
    name = re.sub(r"\s+", "-", name.strip())
    name = name.lower().strip("-")
    return name if name else "unknown-chat"


def is_system_message(text: str) -> bool:
    if not text:
        return True
    t = text.strip().lower()
    for sys_text in SYSTEM_TEXTS:
        if t.startswith(sys_text) or t == sys_text:
            return True
    if "<attached:" in t:
        return True
    for pat in SYSTEM_ACTION_RE:
        if pat.match(t):
            return True
    return False


def detect_date_format(lines: list[str], max_check: int = 200) -> str:
    ""












    dmy_evidence = 0
    mdy_evidence = 0


    date_tuples = []

    for line in lines:
        m = re.match(r"^\[?(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", line)
        if m:
            first, second, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if year < 100:
                year += 2000
            if first > 12:
                dmy_evidence += 1
            if second > 12:
                mdy_evidence += 1
            date_tuples.append((first, second, year))


    if dmy_evidence > 0 and mdy_evidence == 0:
        return "dmy"
    if mdy_evidence > 0 and dmy_evidence == 0:
        return "mdy"



    now = datetime.now()
    future_dmy = 0
    future_mdy = 0
    for first, second, year in date_tuples:

        try:
            dt_dmy = datetime(year, second, first)
            if dt_dmy > now:
                future_dmy += 1
        except ValueError:
            future_dmy += 1


        try:
            dt_mdy = datetime(year, first, second)
            if dt_mdy > now:
                future_mdy += 1
        except ValueError:
            future_mdy += 1


    if future_dmy < future_mdy:
        return "dmy"
    if future_mdy < future_dmy:
        return "mdy"


    return "dmy"


def parse_date(date_str: str, time_str: str, date_format: str, ampm: str | None = None) -> str:
    """ISO timestamp from the export's date and time; `ampm` is "a"/"p" for a 12-hour clock."""
    parts = re.split(r"[/.\-]", date_str)
    if date_format == "dmy":
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
    if year < 100:
        year += 2000
    time_parts = re.split(r"[:.]", time_str)
    hour, minute = int(time_parts[0]), int(time_parts[1])
    second = int(time_parts[2]) if len(time_parts) > 2 else 0
    if ampm:
        if ampm.lower() == "p" and hour < 12:
            hour += 12
        elif ampm.lower() == "a" and hour == 12:
            hour = 0
    now = datetime.now()
    try:
        dt = datetime(year, month, day, hour, minute, second)

        if dt > now and month != day and month <= 12 and day <= 12:
            try:
                dt_swap = datetime(year, day, month, hour, minute, second)
                if dt_swap <= now:
                    return dt_swap.isoformat()
            except ValueError:
                pass
        return dt.isoformat()
    except ValueError:
        try:
            dt = datetime(year, day, month, hour, minute, second)
            return dt.isoformat()
        except ValueError:
            return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def read_chat_file(filepath: str | Path) -> str:
    ""
    for enc in ["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            with open(filepath, encoding=enc, errors="replace") as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(filepath, encoding="utf-8", errors="replace") as f:
        return f.read()


def is_phone_number(name: str) -> bool:
    cleaned = re.sub(r"[\s\-\+\(\)]", "", name)
    return cleaned.isdigit() and len(cleaned) >= 7







def phase1_extract(
    skip: bool = False, extra_dirs: list[Path] | None = None, list_only: bool = False
) -> list[dict]:
    ""





    if skip:
        log.info("Phase 1: SKIPPED (--skip-extract)")
        return []

    log.info("=" * 70)
    log.info("PHASE 1: Extract WhatsApp chat files")
    log.info("=" * 70)

    found = []
    temp_dir = Path(tempfile.mkdtemp(prefix="whatsapp_extract_"))
    log.info(f"  Temp dir: {temp_dir}")


    pairs = find_zips(ZIP_FOLDERS, extra_dirs)
    per_folder: dict[Path, int] = defaultdict(int)
    for folder, _ in pairs:
        per_folder[folder] += 1
    for folder, n in per_folder.items():
        log.info(f"  Folder: {str(folder)!r} -> {n} exports")

    if True:
        for folder, zp in pairs:
            chat_name = chat_name_from_file(zp)
            zip_size = zp.stat().st_size

            if zp.suffix.lower() == ".txt":
                # Android "without media", or any export saved as a bare text file
                txt_size = zip_size
                log.info(f"    {chat_name} (.txt) -> {txt_size / 1024:.1f} KB")
                found.append(
                    {
                        "chat_name": chat_name,
                        "chat_key": dedup_key(chat_name),
                        "txt_path": str(zp),
                        "source_folder": str(folder),
                        "source_zip": None,
                        "zip_size": 0,
                        "txt_size": txt_size,
                        "is_zip": False,
                    }
                )
                continue

            try:
                with zipfile.ZipFile(zp, "r") as zf:

                    txt_candidates = [
                        n
                        for n in zf.namelist()
                        if n.endswith(".txt") and not n.startswith("__MACOSX")
                    ]
                    if not txt_candidates:
                        log.warning(f"    SKIP {zp.name}: no .txt in ZIP")
                        continue


                    txt_name = next(
                        (n for n in txt_candidates if "_chat.txt" in n), txt_candidates[0]
                    )


                    safe_name = sanitize_filename(chat_name)
                    extract_path = temp_dir / f"{safe_name}.txt"
                    if list_only:
                        txt_size = zf.getinfo(txt_name).file_size
                    else:
                        with zf.open(txt_name) as src, open(extract_path, "wb") as dst:
                            dst.write(src.read())
                        txt_size = extract_path.stat().st_size
                    log.info(f"    {chat_name} -> {txt_size / 1024:.1f} KB")

                    found.append(
                        {
                            "chat_name": chat_name,
                            "chat_key": dedup_key(chat_name),
                            "txt_path": str(extract_path),
                            "source_folder": str(folder),
                            "source_zip": str(zp),
                            "zip_size": zip_size,
                            "txt_size": txt_size,
                            "is_zip": True,
                        }
                    )

            except zipfile.BadZipFile:
                log.error(f"    ERROR: Bad ZIP file: {zp.name}")
            except Exception as e:
                log.error(f"    ERROR extracting {zp.name}: {e}")



    by_name: dict[str, list[dict]] = defaultdict(list)
    for item in found:

        key = dedup_key(item["chat_name"])
        by_name[key].append(item)

    deduped = []
    for key, items in by_name.items():
        if len(items) == 1:
            deduped.append(items[0])
        else:

            items.sort(key=lambda x: x["txt_size"], reverse=True)
            best = items[0]
            for other in items[1:]:
                log.info(
                    f"  DEDUP: Keeping {Path(best['source_folder']).name}/{best['chat_name']} "
                    f"({best['txt_size']}B) over {Path(other['source_folder']).name}/{other['chat_name']} "
                    f"({other['txt_size']}B)"
                )
            deduped.append(best)

    log.info(f"\nPhase 1 result: {len(deduped)} unique chats extracted (from {len(found)} total)")
    return deduped







def parse_chat(filepath: str, chat_name: str) -> dict | None:
    ""
    content = read_chat_file(filepath)
    lines = content.split("\n")

    if not lines:
        return None


    uses_brackets = any(line.startswith("[") for line in lines[:30])


    lines = [line.lstrip("\u200e\u200f\u202a\u202c\ufeff") for line in lines]

    date_format = detect_date_format(lines)

    messages = []
    current_msg = None
    system_messages = []

    for line in lines:
        if not line.strip():
            if current_msg is not None:
                current_msg["text"] += "\n"
            continue

        matched = False

        if uses_brackets:
            m = MSG_PATTERN_BRACKET.match(line)
            if m:
                if current_msg is not None:
                    messages.append(current_msg)

                date_str, time_str, ampm, sender, text = m.groups()
                timestamp = parse_date(date_str, time_str, date_format, ampm)
                sender = sender.strip("\u200e\u200f\u202a\u202c\ufeff ")
                if is_owner(sender):
                    sender = OWNER_CANONICAL
                text = text.strip("\u200e\u200f\u202a\u202c\ufeff")

                current_msg = {"timestamp": timestamp, "sender": sender, "text": text}
                matched = True
            else:
                sm = SYS_PATTERN_BRACKET.match(line)
                if sm:
                    date_str, time_str, ampm, rest = sm.groups()
                    if rest.startswith("\u200e") or ": " not in rest.split("\n")[0]:
                        if current_msg is not None:
                            messages.append(current_msg)
                            current_msg = None
                        system_messages.append(
                            {
                                "timestamp": parse_date(date_str, time_str, date_format, ampm),
                                "text": rest.strip("\u200e\u200f\u202a\u202c\ufeff "),
                            }
                        )
                        matched = True
        else:
            m = MSG_PATTERN_NOBRACKET.match(line)
            if m:
                if current_msg is not None:
                    messages.append(current_msg)

                date_str, time_str, ampm, sender, text = m.groups()
                timestamp = parse_date(date_str, time_str, date_format, ampm)
                sender = sender.strip("\u200e\u200f\u202a\u202c\ufeff ")
                if is_owner(sender):
                    sender = OWNER_CANONICAL
                text = text.strip("\u200e\u200f\u202a\u202c\ufeff")

                current_msg = {"timestamp": timestamp, "sender": sender, "text": text}
                matched = True
            else:
                sm = SYS_PATTERN_NOBRACKET.match(line)
                if sm:
                    # a dated line without "Name: " is a system line (encryption notice, added, left)
                    date_str, time_str, ampm, rest = sm.groups()
                    if current_msg is not None:
                        messages.append(current_msg)
                        current_msg = None
                    system_messages.append(
                        {
                            "timestamp": parse_date(date_str, time_str, date_format, ampm),
                            "text": rest.strip("\u200e\u200f\u202a\u202c\ufeff "),
                        }
                    )
                    matched = True

        if not matched and current_msg is not None:
            current_msg["text"] += "\n" + line

    if current_msg is not None:
        messages.append(current_msg)

    # blank lines are kept inside a message, not at its end
    for msg in messages:
        msg["text"] = msg["text"].rstrip("\n")

    if not messages:
        return None


    participants = Counter()
    for msg in messages:
        participants[msg["sender"]] += 1

    date_start = messages[0]["timestamp"] if messages else None
    date_end = messages[-1]["timestamp"] if messages else None

    return {
        "chat_name": chat_name,
        "source_file": filepath,
        "date_format_detected": date_format,
        "participants": dict(participants),
        "participant_count": len(participants),
        "message_count": len(messages),
        "date_start": date_start,
        "date_end": date_end,
        "system_messages": system_messages,
        "messages": messages,
    }


def _vecchi_export(existing_index: dict, sanitized: str) -> list[str]:
    ""

    return [
        sn
        for sn, entry in existing_index.items()
        if sn != sanitized
        and dedup_key(sn) == sanitized
        and str(entry.get("source_path", "")).lower().endswith(".zip")
    ]


_UNIONE = None


def _unione():
    ""
    global _UNIONE
    if _UNIONE is None:
        nome = "wa_l0_chatstorage_unione"
        spec = importlib.util.spec_from_file_location(
            nome, Path(__file__).resolve().parent / "wa-l0-chatstorage.py"
        )
        _UNIONE = importlib.util.module_from_spec(spec)
        sys.modules[nome] = _UNIONE
        spec.loader.exec_module(_UNIONE)
    return _UNIONE


def _unisci_alla_chat(vecchio: dict, letto: dict) -> tuple[dict, int]:
    ""

    cs = _unione()
    nuovi, _, _ = cs.nuovi_per(vecchio, letto.get("messages") or [])
    if not nuovi:
        return vecchio, 0
    nuovi = [{k: v for k, v in m.items() if k != "_sicuro"} for m in nuovi]
    unita, aggiunti, _ = cs._storico().merge_chats(
        vecchio,
        {
            "messages": nuovi,
            "participants": dict(Counter(m.get("sender", "") for m in nuovi)),
            "phone_numbers": letto.get("phone_numbers") or {},
            "source_file": letto.get("source_file") or "",
        },
    )
    unita["participant_count"] = len(unita.get("participants") or {})
    unita.setdefault("date_format_detected", letto.get("date_format_detected", ""))
    unita.setdefault("chat_name", letto.get("chat_name", ""))
    return unita, aggiunti


def phase2_parse(extracted: list[dict]) -> list[dict]:
    ""



    log.info("\n" + "=" * 70)
    log.info("PHASE 2: Parse chat files")
    log.info("=" * 70)

    CHATS_DIR.mkdir(parents=True, exist_ok=True)


    existing_index = {}
    index_path = CHATS_DIR / "chats-index.json"
    if index_path.exists():
        try:
            idx = json.loads(index_path.read_text())
            for chat in idx.get("chats", []):
                sn = chat.get("sanitized_name", "")
                existing_index[sn] = chat
        except Exception:
            pass
    chat_prima = len(existing_index)
    fini_scritte: list[str] = []

    new_parsed = 0
    updated = 0
    skipped = 0
    errors = 0
    all_index_entries = []
    all_parsed = []


    used_names: dict[str, int] = {}

    for item in extracted:
        chat_name = item["chat_name"]
        txt_path = item["txt_path"]
        txt_size = item["txt_size"]


        sanitized = item.get("chat_key") or sanitize_filename(chat_name)


        if sanitized in used_names:
            used_names[sanitized] += 1
            sanitized = f"{sanitized}-{used_names[sanitized]}"
        else:
            used_names[sanitized] = 1


        existing = existing_index.get(sanitized)
        output_file = CHATS_DIR / f"{sanitized}.json"

        if (
            existing
            and output_file.exists()
            and txt_size == existing.get("source_file_size_bytes")
            and str(existing.get("source_path", "")) == str(item.get("source_zip") or txt_path)
        ):
            try:
                data = json.loads(output_file.read_text())
                all_parsed.append(data)
                all_index_entries.append(existing)
                log.info(f"  SKIP (same zip, already read): {sanitized}")
                skipped += 1
                continue
            except Exception as e:
                log.warning("  Corrupted JSON for %s (%s), forcing re-parse", sanitized, e)


        try:
            result = parse_chat(txt_path, chat_name)

            if result is None:
                log.warning(f"  ERROR: No messages parsed from {chat_name}")
                errors += 1
                continue



            aggiunti = None
            if output_file.exists():
                try:
                    vecchio = json.loads(output_file.read_text())
                except (OSError, ValueError) as e:
                    log.error(
                        f"  ERROR: previous chat unreadable, not touching it: {output_file.name} ({e})"
                    )
                    errors += 1
                    continue
                result, aggiunti = _unisci_alla_chat(vecchio, result)
            for old_sn in _vecchi_export(existing_index, sanitized):
                old_file = CHATS_DIR / f"{old_sn}.json"
                if old_file.exists():
                    try:
                        result, piu = _unisci_alla_chat(result, json.loads(old_file.read_text()))
                        aggiunti = (aggiunti or 0) + piu
                    except (OSError, ValueError) as e:
                        log.warning(
                            f"  old export unreadable, stays where it is: {old_file.name} ({e})"
                        )
            if aggiunti == 0 and output_file.exists() and existing:
                all_parsed.append(result)
                all_index_entries.append(existing)
                log.info(f"  SKIP (the zip adds no messages): {sanitized}")
                skipped += 1
                continue


            if output_file.exists():
                superseded_dir = CHATS_DIR / "_superseded"
                superseded_dir.mkdir(exist_ok=True)
                shutil.copy2(
                    output_file,
                    superseded_dir / f"{sanitized}.prima-{datetime.now():%Y%m%d-%H%M%S}.json",
                )
            safe_write_json(output_file, result)
            if result.get("date_end"):
                fini_scritte.append(result["date_end"])

            output_size = output_file.stat().st_size

            log.info(
                f"  {'UPDATE' if existing else 'NEW'}: {sanitized} "
                f"-> {result['message_count']} msgs, "
                f"{result['participant_count']} participants, "
                f"{result['date_start'][:10] if result['date_start'] else '?'} to "
                f"{result['date_end'][:10] if result['date_end'] else '?'}"
            )

            index_entry = {
                "chat_name": chat_name,
                "sanitized_name": sanitized,
                "source_path": item.get("source_zip") or txt_path,
                "source_file": txt_path,
                "source_file_size_bytes": txt_size,
                "output_file": str(output_file),
                "output_file_size_bytes": output_size,
                "date_format_detected": result["date_format_detected"],
                "participants": result["participants"],
                "participant_count": result["participant_count"],
                "message_count": result["message_count"],
                "date_start": result["date_start"],
                "date_end": result["date_end"],
            }
            all_index_entries.append(index_entry)
            all_parsed.append(result)



            for old_sn in _vecchi_export(existing_index, sanitized):
                old_file = CHATS_DIR / f"{old_sn}.json"
                if old_file.exists():
                    superseded_dir = CHATS_DIR / "_superseded"
                    superseded_dir.mkdir(exist_ok=True)
                    old_file.rename(superseded_dir / old_file.name)
                    log.info(
                        f"  SUPERSEDED: {old_sn} -> _superseded/ (re-export of the same chat: {sanitized})"
                    )
                existing_index.pop(old_sn, None)
                all_index_entries[:] = [
                    e for e in all_index_entries if e.get("sanitized_name") != old_sn
                ]
                all_parsed[:] = [
                    c for c in all_parsed if sanitize_filename(c.get("chat_name", "")) != old_sn
                ]

            if existing:
                updated += 1
            else:
                new_parsed += 1

        except Exception as e:
            log.error(f"  ERROR parsing {chat_name}: {e}")
            errors += 1


    existing_jsons = sorted(CHATS_DIR.glob("*.json"))
    loaded_sanitized = {e["sanitized_name"] for e in all_index_entries}

    for jf in existing_jsons:
        if jf.name.startswith("_") or jf.name == "chats-index.json":
            continue
        sn = jf.stem
        if sn in loaded_sanitized:
            continue

        try:
            data = json.loads(jf.read_text())
            all_parsed.append(data)

            ie = {
                "chat_name": data.get("chat_name", ""),
                "sanitized_name": sn,
                "source_path": data.get("source_file", ""),
                "source_file": data.get("source_file", ""),
                "source_file_size_bytes": 0,
                "output_file": str(jf),
                "output_file_size_bytes": jf.stat().st_size,
                "date_format_detected": data.get("date_format_detected", ""),
                "participants": data.get("participants", {}),
                "participant_count": data.get("participant_count", 0),
                "message_count": data.get("message_count", 0),
                "date_start": data.get("date_start"),
                "date_end": data.get("date_end"),
            }
            all_index_entries.append(ie)
            log.info(f"  EXISTING: {sn} ({data.get('message_count', 0)} msgs)")
        except Exception as e:
            log.warning(f"  Cannot load existing {jf.name}: {e}")


    all_index_entries.sort(key=lambda x: x.get("date_start") or "")
    total_msgs = sum(c.get("message_count", 0) for c in all_index_entries)
    all_participants = set()
    for c in all_index_entries:
        pdict = c.get("participants", {})
        if isinstance(pdict, dict):
            all_participants.update(pdict.keys())

    index_data = {
        "generated_at": datetime.now().isoformat(),
        "total_chats": len(all_index_entries),
        "total_messages": total_msgs,
        "total_participants": len(all_participants),
        "chats": all_index_entries,
    }
    safe_write_json(index_path, index_data)

    log.info(
        f"\nPhase 2 result: {new_parsed} new, {updated} updated, {skipped} skipped, {errors} errors"
    )
    log.info(
        f"  Total: {len(all_parsed)} chats, {total_msgs} messages, {len(all_participants)} participants"
    )

    ULTIMO_GIRO.clear()
    ULTIMO_GIRO.update(
        nuove=new_parsed,
        aggiornate=updated,
        uguali=skipped,
        errori=errors,
        chat_prima=chat_prima,
        chat_dopo=len(all_index_entries),

        dati_fino_al=max(
            (f for f in fini_scritte if f <= datetime.now().isoformat()), default=None
        ),
    )
    return all_parsed







def detect_language(texts: list[str]) -> str:
    ""
    sample = " ".join(texts[:500]).lower()
    it_words = [
        "che",
        "non",
        "per",
        "con",
        "sono",
        "come",
        "anche",
        "una",
        "questo",
        "pero",
        "tutto",
        "dalla",
        "alla",
        "nella",
        "fare",
    ]
    en_words = [
        "the",
        "and",
        "for",
        "you",
        "that",
        "with",
        "this",
        "have",
        "from",
        "but",
        "they",
        "what",
        "about",
        "been",
        "would",
    ]
    es_words = [
        "que",
        "para",
        "con",
        "por",
        "los",
        "las",
        "una",
        "pero",
        "como",
        "esta",
        "todo",
        "puede",
        "tiene",
        "desde",
    ]

    it_count = sum(1 for w in it_words if f" {w} " in sample)
    en_count = sum(1 for w in en_words if f" {w} " in sample)
    es_count = sum(1 for w in es_words if f" {w} " in sample)

    if it_count >= en_count and it_count >= es_count:
        return "it"
    elif es_count > en_count:
        return "es"
    return "en"


def extract_topics(messages: list[dict]) -> dict[str, int]:
    ""
    topic_counts: dict[str, int] = defaultdict(int)
    all_text = " ".join(m.get("text", "") for m in messages).lower()

    for category, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            count = all_text.count(kw.lower())
            if count > 0:
                topic_counts[category] += count

    return dict(sorted(topic_counts.items(), key=lambda x: -x[1]))


def extract_entities(messages: list[dict]) -> dict:
    ""
    all_text_parts = [m.get("text", "") for m in messages]
    all_text = "\n".join(all_text_parts)


    companies_found: dict[str, int] = defaultdict(int)
    text_lower = all_text.lower()
    for company in COMPANY_KEYWORDS:
        count = text_lower.count(company.lower())
        if count > 0:
            companies_found[company] = count


    money_mentions = MONEY_RE.findall(all_text)


    urls = URL_RE.findall(all_text)
    url_domains: dict[str, int] = defaultdict(int)
    for url in urls:
        try:
            domain = url.split("/")[2] if "//" in url else url.split("/")[0]
            url_domains[domain] += 1
        except IndexError:
            pass

    return {
        "companies_mentioned": dict(sorted(companies_found.items(), key=lambda x: -x[1])),
        "money_amounts": money_mentions[:50],
        "urls_count": len(urls),
        "url_domains": dict(sorted(url_domains.items(), key=lambda x: -x[1])[:20]),
    }


def analyze_relationship_signals(messages: list[dict], participants: list[str]) -> dict:
    ""
    if not messages or len(participants) < 2:
        return {}


    initiations: dict[str, int] = defaultdict(int)
    prev_ts = None
    for msg in messages:
        try:
            ts = datetime.fromisoformat(msg["timestamp"])
        except (ValueError, KeyError):
            continue
        if prev_ts and (ts - prev_ts).total_seconds() > 4 * 3600:
            initiations[msg["sender"]] += 1
        prev_ts = ts


    response_times: dict[str, list[float]] = defaultdict(list)
    prev_msg = None
    for msg in messages:
        try:
            ts = datetime.fromisoformat(msg["timestamp"])
        except (ValueError, KeyError):
            continue
        if prev_msg and prev_msg["sender"] != msg["sender"]:
            delta_min = (ts - prev_msg["_ts"]).total_seconds() / 60
            if 0 < delta_min < 48 * 60:
                response_times[msg["sender"]].append(delta_min)
        prev_msg = {"sender": msg["sender"], "_ts": ts}

    avg_response: dict[str, float] = {}
    for name, times in response_times.items():
        if times:
            avg_response[name] = round(sum(times) / len(times), 1)


    msg_lengths: dict[str, list[int]] = defaultdict(list)
    for msg in messages:
        text = msg.get("text", "")
        if text and not is_system_message(text):
            msg_lengths[msg["sender"]].append(len(text))

    avg_msg_length: dict[str, float] = {}
    for name, lengths in msg_lengths.items():
        if lengths:
            avg_msg_length[name] = round(sum(lengths) / len(lengths), 1)


    all_text = " ".join(m.get("text", "") for m in messages).lower()
    informal_markers = sum(
        1
        for m in ["haha", "lol", "ahah", "ciao", ":)", ":-)", "bro", "fra", "zio"]
        if m in all_text
    )
    formal_markers = sum(
        1
        for m in [
            "cordiali saluti",
            "distinti saluti",
            "gentile",
            "in allegato",
            "le invio",
            "la prego",
        ]
        if m in all_text
    )

    tone = "formal" if formal_markers > informal_markers else "informal"
    if informal_markers == 0 and formal_markers == 0:
        tone = "neutral"

    return {
        "initiations": dict(initiations),
        "avg_response_minutes": avg_response,
        "avg_message_length_chars": avg_msg_length,
        "tone": tone,
        "informal_marker_count": informal_markers,
        "formal_marker_count": formal_markers,
    }


def analyze_activity_patterns(messages: list[dict]) -> dict:
    ""
    hours: list[int] = []
    weekdays: list[int] = []
    monthly: dict[str, int] = defaultdict(int)

    for msg in messages:
        try:
            ts = datetime.fromisoformat(msg["timestamp"])
            hours.append(ts.hour)
            weekdays.append(ts.weekday())
            monthly[ts.strftime("%Y-%m")] += 1
        except (ValueError, KeyError):
            continue

    hour_dist = Counter(hours)
    weekday_dist = Counter(weekdays)


    peak_hour = hour_dist.most_common(1)[0][0] if hour_dist else None

    late_night = sum(hour_dist.get(h, 0) for h in range(6))
    late_night_pct = round(late_night / len(hours) * 100, 1) if hours else 0

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    peak_day = weekday_names[weekday_dist.most_common(1)[0][0]] if weekday_dist else None

    return {
        "peak_hour": peak_hour,
        "late_night_pct": late_night_pct,
        "peak_day": peak_day,
        "hour_distribution": {str(h): hour_dist.get(h, 0) for h in range(24)},
        "weekday_distribution": {weekday_names[d]: weekday_dist.get(d, 0) for d in range(7)},
        "monthly_activity": dict(sorted(monthly.items())),
        "total_active_months": len(monthly),
    }


def extract_media_stats(messages: list[dict]) -> dict:
    ""
    stats: dict[str, int] = defaultdict(int)
    for msg in messages:
        text = msg.get("text", "")
        for media_type, pattern in MEDIA_PATTERNS.items():
            if pattern.search(text):
                stats[media_type] += 1
    return dict(stats)


def extract_action_items(messages: list[dict], max_items: int = 30) -> list[dict]:
    ""
    action_patterns = [
        re.compile(
            r"(devi|dovresti|puoi|potresti|fammi|mandami|inviami|scrivi|chiama|organizza|prepara|fai)\s",
            re.I,
        ),
        re.compile(r"(ti mando|ti invio|ti giro|ti scrivo|ti chiamo|facciamo|proviamo)\s", re.I),
        re.compile(r"(entro domani|entro luned|entro venerd|urgente|asap|prima possibile)", re.I),
        re.compile(r"(da fare|to do|action item|follow up|reminder)", re.I),
        re.compile(r"(ricordami|non dimenticare|segna|appunta)", re.I),
    ]

    items = []
    for msg in messages:
        text = msg.get("text", "")
        if not text or len(text) < 15:
            continue
        for pat in action_patterns:
            if pat.search(text):
                items.append(
                    {
                        "timestamp": msg.get("timestamp", ""),
                        "sender": msg.get("sender", ""),
                        "text": text[:300],
                    }
                )
                break


    return items[-max_items:]


def analyze_single_chat(chat_data: dict) -> dict:
    ""
    messages = chat_data.get("messages", [])
    participants_raw = chat_data.get("participants", {})
    chat_name = chat_data.get("chat_name", "")


    if isinstance(participants_raw, dict):
        participants_dict = participants_raw
        participant_names = list(participants_dict.keys())
    elif isinstance(participants_raw, list):

        msg_counts = Counter(m.get("sender", "") for m in messages if m.get("sender"))
        participants_dict = {p: msg_counts.get(p, 0) for p in participants_raw}
        participant_names = participants_raw
    else:
        participants_dict = {}
        participant_names = []


    for msg in messages:
        if "timestamp" not in msg and "date" in msg and "time" in msg:

            try:
                date_str = msg["date"]
                time_str = msg["time"]

                for fmt in (
                    "%m/%d/%y %H:%M:%S",
                    "%d/%m/%y %H:%M:%S",
                    "%m/%d/%Y %H:%M:%S",
                    "%d/%m/%Y %H:%M:%S",
                ):
                    try:
                        dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                        msg["timestamp"] = dt.isoformat()
                        break
                    except ValueError:
                        continue
                if "timestamp" not in msg:
                    msg["timestamp"] = f"{date_str}T{time_str}"
            except Exception:
                msg["timestamp"] = ""


    real_messages = [m for m in messages if not is_system_message(m.get("text", ""))]
    texts = [m.get("text", "") for m in real_messages if m.get("text")]


    non_system_participants = [p for p in participant_names if not is_system_message(p)]
    is_group = len(non_system_participants) > 2


    participant_stats = []
    for name, count in sorted(participants_dict.items(), key=lambda x: -x[1]):
        msgs = [m for m in real_messages if m["sender"] == name]
        chars = sum(len(m.get("text", "")) for m in msgs)
        first_ts = msgs[0]["timestamp"] if msgs else None
        last_ts = msgs[-1]["timestamp"] if msgs else None

        participant_stats.append(
            {
                "name": name,
                "message_count": count,
                "char_count": chars,
                "avg_msg_length": round(chars / count, 1) if count else 0,
                "first_message": first_ts,
                "last_message": last_ts,
                "is_owner": is_owner(name),
                "is_phone_number": is_phone_number(name),
            }
        )


    topics = extract_topics(real_messages)


    entities = extract_entities(real_messages)


    relationship = analyze_relationship_signals(real_messages, non_system_participants)


    activity = analyze_activity_patterns(real_messages)


    language = detect_language(texts)


    media = extract_media_stats(messages)


    action_items = extract_action_items(real_messages)


    date_start = chat_data.get("date_start")
    date_end = chat_data.get("date_end")
    if date_start and date_end:
        try:
            ds = datetime.fromisoformat(date_start)
            de = datetime.fromisoformat(date_end)
            duration_days = (de - ds).days
        except ValueError:
            duration_days = 0
    else:
        duration_days = 0

    return {
        "chat_name": chat_name,
        "sanitized_name": sanitize_filename(chat_name),
        "chat_type": "group" if is_group else "1to1",
        "language": language,
        "message_count": len(messages),
        "real_message_count": len(real_messages),
        "participant_count": len(non_system_participants),
        "date_start": date_start,
        "date_end": date_end,
        "duration_days": duration_days,
        "participants": participant_stats,
        "topics": topics,
        "entities": entities,
        "relationship_signals": relationship,
        "activity_patterns": activity,
        "media_stats": media,
        "action_items_count": len(action_items),
        "action_items": action_items,
        "analyzed_at": datetime.now().isoformat(),
    }


def phase3_analysis(all_parsed: list[dict], skip: bool = False) -> dict:
    ""



    if skip:
        log.info("\nPhase 3: SKIPPED (--skip-analysis)")
        return {}

    log.info("\n" + "=" * 70)
    log.info("PHASE 3: Deep Analysis")
    log.info("=" * 70)

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    analyses = []
    total_real_msgs = 0

    for chat_data in all_parsed:
        chat_name = chat_data.get("chat_name", "unknown")
        msg_count = chat_data.get("message_count", 0)

        if msg_count == 0:
            log.info(f"  SKIP (0 msgs): {chat_name}")
            continue

        try:
            analysis = analyze_single_chat(chat_data)
            analyses.append(analysis)
            total_real_msgs += analysis["real_message_count"]


            safe_name = analysis["sanitized_name"]
            out_path = ANALYSIS_DIR / f"{safe_name}-analysis.json"
            safe_write_json(out_path, analysis)

            log.info(
                f"  {chat_name}: {analysis['real_message_count']} real msgs, "
                f"{analysis['chat_type']}, {analysis['language']}, "
                f"{len(analysis['topics'])} topic categories"
            )
        except Exception as e:
            log.error(f"  ERROR analyzing {chat_name}: {e}")
            import traceback

            traceback.print_exc()


    log.info("\nBuilding overall analysis summary...")


    total_topics: dict[str, int] = defaultdict(int)
    for a in analyses:
        for topic, count in a.get("topics", {}).items():
            total_topics[topic] += count


    total_companies: dict[str, int] = defaultdict(int)
    for a in analyses:
        for company, count in a.get("entities", {}).get("companies_mentioned", {}).items():
            total_companies[company] += count


    chats_by_msgs = sorted(analyses, key=lambda x: x["real_message_count"], reverse=True)


    participant_totals: dict[str, dict] = defaultdict(
        lambda: {"messages": 0, "chats": 0, "chars": 0}
    )
    for a in analyses:
        for p in a.get("participants", []):
            name = p["name"]
            if is_owner(name):
                continue
            participant_totals[name]["messages"] += p["message_count"]
            participant_totals[name]["chars"] += p["char_count"]
            participant_totals[name]["chats"] += 1

    top_contacts = sorted(participant_totals.items(), key=lambda x: x[1]["messages"], reverse=True)[
        :30
    ]


    all_money = []
    for a in analyses:
        money = a.get("entities", {}).get("money_amounts", [])
        if money:
            all_money.extend([(a["chat_name"], m) for m in money])


    all_actions = []
    for a in analyses:
        for item in a.get("action_items", []):
            all_actions.append(
                {
                    "chat": a["chat_name"],
                    **item,
                }
            )

    all_actions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)


    lang_dist = Counter(a.get("language", "unknown") for a in analyses)


    one_to_one = [a for a in analyses if a["chat_type"] == "1to1"]
    groups = [a for a in analyses if a["chat_type"] == "group"]


    owner_msgs = 0
    owner_chars = 0
    for a in analyses:
        for p in a.get("participants", []):
            if is_owner(p["name"]):
                owner_msgs += p["message_count"]
                owner_chars += p["char_count"]


    all_starts = [a["date_start"] for a in analyses if a.get("date_start")]
    all_ends = [a["date_end"] for a in analyses if a.get("date_end")]

    overall = {
        "generated_at": datetime.now().isoformat(),
        "pipeline": "whatsapp-full-pipeline-v1",
        "totals": {
            "chats_analyzed": len(analyses),
            "chats_1to1": len(one_to_one),
            "chats_group": len(groups),
            "total_messages": sum(a["message_count"] for a in analyses),
            "real_messages": total_real_msgs,
            "unique_participants": len(participant_totals) + 1,
            "date_range_start": min(all_starts) if all_starts else None,
            "date_range_end": max(all_ends) if all_ends else None,
        },
        "owner": {
            "messages_sent": owner_msgs,
            "chars_sent": owner_chars,
            "chats_participated": len(analyses),
        },
        "language_distribution": dict(lang_dist),
        "topics_aggregate": dict(sorted(total_topics.items(), key=lambda x: -x[1])),
        "companies_mentioned": dict(sorted(total_companies.items(), key=lambda x: -x[1])),
        "top_contacts": [{"name": name, **stats} for name, stats in top_contacts],
        "top_chats_by_messages": [
            {
                "chat_name": a["chat_name"],
                "type": a["chat_type"],
                "messages": a["real_message_count"],
                "participants": a["participant_count"],
                "duration_days": a["duration_days"],
            }
            for a in chats_by_msgs[:20]
        ],
        "money_mentions": all_money[:50],
        "recent_action_items": all_actions[:50],
        "per_chat_summaries": [
            {
                "chat_name": a["chat_name"],
                "type": a["chat_type"],
                "language": a["language"],
                "messages": a["real_message_count"],
                "participants": a["participant_count"],
                "duration_days": a["duration_days"],
                "top_topics": list(a.get("topics", {}).keys())[:5],
                "tone": a.get("relationship_signals", {}).get("tone", ""),
                "late_night_pct": a.get("activity_patterns", {}).get("late_night_pct", 0),
            }
            for a in chats_by_msgs
        ],
    }


    overall_path = ANALYSIS_DIR / "_whatsapp-deep-analysis.json"
    safe_write_json(overall_path, overall)
    log.info(f"  Saved overall analysis -> {overall_path}")

    log.info(f"\nPhase 3 result: {len(analyses)} chats analyzed")
    log.info(f"  {total_real_msgs} real messages across all chats")
    log.info(f"  Top topics: {', '.join(list(total_topics.keys())[:5])}")
    log.info(f"  Top contacts: {', '.join(n for n, _ in top_contacts[:5])}")

    return overall







def phase4_phone_resolution(all_parsed: list[dict]) -> dict:
    ""





    log.info("\n" + "=" * 70)
    log.info("PHASE 4: Phone Number Resolution")
    log.info("=" * 70)


    phone_participants: dict[str, dict] = {}

    for chat_data in all_parsed:
        chat_name = chat_data.get("chat_name", "")
        participants = chat_data.get("participants", {})
        if isinstance(participants, dict):
            for name, count in participants.items():
                if is_phone_number(name):
                    if name not in phone_participants:
                        phone_participants[name] = {"chats": [], "total_messages": 0}
                    phone_participants[name]["chats"].append(chat_name)
                    phone_participants[name]["total_messages"] += count


        clean_name = re.sub(r"^WhatsApp Chat\s*-\s*", "", chat_name).strip()
        clean_name = re.sub(r"\s*\(\d+\)\s*$", "", clean_name).strip()
        if is_phone_number(clean_name.replace("+", "").replace(" ", "").replace("-", "")):
            if clean_name not in phone_participants:
                phone_participants[clean_name] = {"chats": [chat_name], "total_messages": 0}

    log.info(f"  Found {len(phone_participants)} unique phone numbers to resolve")

    resolved: dict[str, dict] = {}


    if IPHONE_CONTACTS.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(IPHONE_CONTACTS)
            log.info(f"  iPhone contacts loaded: {len(df)} contacts")


            iphone_lookup: dict[str, str] = {}
            for _, row in df.iterrows():
                name = row.get("name", "")
                if not name:
                    continue


                phone_primary = str(row.get("phone_primary", "")).strip()
                if phone_primary and phone_primary != "nan":

                    normalized = normalize_phone(phone_primary)
                    if normalized:
                        iphone_lookup[normalized] = name


                phones_raw = row.get("phone_numbers", [])
                if isinstance(phones_raw, str):
                    try:
                        phones_raw = json.loads(phones_raw.replace("'", '"'))
                    except Exception:
                        phones_raw = [phones_raw]
                if isinstance(phones_raw, list):
                    for ph in phones_raw:
                        normalized = normalize_phone(str(ph))
                        if normalized:
                            iphone_lookup[normalized] = name

            log.info(f"  iPhone phone lookup: {len(iphone_lookup)} phone-to-name mappings")


            for phone in phone_participants:
                phone_normalized = normalize_phone(phone)
                if phone_normalized in iphone_lookup:
                    resolved[phone] = {
                        "resolved_name": iphone_lookup[phone_normalized],
                        "source": "iphone_contacts",
                        "confidence": 0.95,
                    }
                    log.info(f"    RESOLVED (iPhone): {phone} -> {iphone_lookup[phone_normalized]}")
                else:


                    digits = re.sub(r"[^\d]", "", phone)

                    for key, name in iphone_lookup.items():
                        key_digits = re.sub(r"[^\d]", "", key)
                        if len(digits) >= 9 and len(key_digits) >= 9:
                            if digits[-9:] == key_digits[-9:]:
                                resolved[phone] = {
                                    "resolved_name": name,
                                    "source": "iphone_contacts_fuzzy",
                                    "confidence": 0.85,
                                }
                                log.info(f"    RESOLVED (iPhone fuzzy): {phone} -> {name}")
                                break

        except ImportError:
            log.warning("  pandas not available, skipping iPhone contacts")
        except Exception as e:
            log.error(f"  Error loading iPhone contacts: {e}")
    else:
        log.info("  iPhone contacts file not found, skipping")


    if ENTITY_MAP.exists():
        try:
            entity_data = json.loads(ENTITY_MAP.read_text())
            log.info(f"  Entity map loaded: {len(entity_data)} entries")



            phone_to_person: dict[str, str] = {}
            for key, entry in entity_data.items():
                canonical = entry.get("canonical_name", "")
                if not canonical:
                    continue

                if key.startswith("+") or re.match(r"^\d{7,}", key):
                    phone_normalized = normalize_phone(key)
                    if phone_normalized:
                        phone_to_person[phone_normalized] = canonical

            for phone in phone_participants:
                if phone in resolved:
                    continue
                phone_normalized = normalize_phone(phone)
                if phone_normalized in phone_to_person:
                    resolved[phone] = {
                        "resolved_name": phone_to_person[phone_normalized],
                        "source": "entity_map",
                        "confidence": 0.90,
                    }
                    log.info(
                        f"    RESOLVED (entity map): {phone} -> {phone_to_person[phone_normalized]}"
                    )

        except Exception as e:
            log.error(f"  Error loading entity map: {e}")
    else:
        log.info("  Entity map file not found, skipping")




    for chat_data in all_parsed:
        chat_name = chat_data.get("chat_name", "")
        participants = chat_data.get("participants", {})
        if not isinstance(participants, dict):
            continue


        real_names = [
            n for n in participants.keys() if not is_owner(n) and not is_phone_number(n)
        ]
        phone_names = [n for n in participants.keys() if is_phone_number(n)]


        clean_chat = re.sub(r"^WhatsApp Chat\s*-\s*", "", chat_name).strip()
        if not is_phone_number(clean_chat.replace("+", "").replace(" ", "").replace("-", "")):

            if len(phone_names) == 1 and len(real_names) <= 1:
                phone = phone_names[0]
                if phone not in resolved:

                    if len(real_names) == 0:
                        resolved[phone] = {
                            "resolved_name": clean_chat,
                            "source": "chat_name_inference",
                            "confidence": 0.70,
                        }
                        log.info(f"    RESOLVED (chat name): {phone} -> {clean_chat}")


    resolution_output = {
        "generated_at": datetime.now().isoformat(),
        "total_phone_numbers": len(phone_participants),
        "total_resolved": len(resolved),
        "total_unresolved": len(phone_participants) - len(resolved),
        "resolved": {
            phone: {
                **info,
                "chats": phone_participants.get(phone, {}).get("chats", []),
                "total_messages": phone_participants.get(phone, {}).get("total_messages", 0),
            }
            for phone, info in resolved.items()
        },
        "unresolved": {
            phone: info for phone, info in phone_participants.items() if phone not in resolved
        },
    }

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANALYSIS_DIR / "_phone-resolution.json"
    safe_write_json(out_path, resolution_output)
    log.info(f"\n  Saved phone resolution -> {out_path}")
    log.info(f"  Resolved: {len(resolved)}/{len(phone_participants)}")
    for phone, info in resolved.items():
        log.info(f"    {phone} -> {info['resolved_name']} ({info['source']}, {info['confidence']})")

    unresolved = [p for p in phone_participants if p not in resolved]
    if unresolved:
        log.info(f"  Unresolved ({len(unresolved)}):")
        for phone in unresolved:
            info = phone_participants[phone]
            log.info(f"    {phone} ({info['total_messages']} msgs in {len(info['chats'])} chats)")

    return resolution_output







def main():
    parser = argparse.ArgumentParser(description="WhatsApp Full Pipeline — SBK")
    parser.add_argument(
        "--skip-extract", action="store_true", help="Skip Phase 1 (use existing parsed chats)"
    )
    parser.add_argument("--skip-analysis", action="store_true", help="Skip Phase 3 (deep analysis)")
    parser.add_argument(
        "--zip-dir",
        action="append",
        type=Path,
        default=[],
        help="Extra folder with chat exports ('WhatsApp Chat - *.zip', 'WhatsApp Chat with *.zip/.txt'; "
        "searched recursively; repeatable)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Dry run: list the exports found and the dedup verdicts, write nothing",
    )
    wa_ricevuta.add_declare_argument(parser)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.time()

    log.info("=" * 70)
    log.info("WHATSAPP FULL PIPELINE — SBK")
    log.info("=" * 70)


    extracted = phase1_extract(
        skip=args.skip_extract,
        extra_dirs=[d.expanduser() for d in args.zip_dir],
        list_only=args.list,
    )
    if args.list:
        log.info(f"\n--list: {len(extracted)} unique chats, no file written.")
        return


    if args.skip_extract:

        log.info("\nLoading existing parsed chats...")
        all_parsed = []
        for jf in sorted(CHATS_DIR.glob("*.json")):
            if jf.name.startswith("_") or jf.name == "chats-index.json":
                continue
            try:
                data = json.loads(jf.read_text())
                all_parsed.append(data)
            except Exception as e:
                log.warning(f"  Cannot load {jf.name}: {e}")
        log.info(f"  Loaded {len(all_parsed)} existing chats")
    else:

        dove = [str(f) for f in [*ZIP_FOLDERS, *args.zip_dir]]
        ricevuta = wa_ricevuta.inizio(RICEVUTA_DIR, "wa-l0l3-full", args.dichiara, dove)
        try:
            all_parsed = phase2_parse(extracted)
        except BaseException:
            wa_ricevuta.fine(
                RICEVUTA_DIR,
                ricevuta,
                "wa-l0l3-full",
                esito="errore",
                viste=len(extracted),
                nuove=0,
                aggiornate=0,
                uguali=0,
                errori=1,
                chat_prima=0,
                chat_dopo=0,
                dati_fino_al=None,
            )
            raise
        wa_ricevuta.fine(
            RICEVUTA_DIR,
            ricevuta,
            "wa-l0l3-full",
            viste=len(extracted),
            dichiarato=args.dichiara,
            **ULTIMO_GIRO,
        )


    import shutil
    import tempfile

    for d in Path(tempfile.gettempdir()).glob("whatsapp_extract_*"):
        shutil.rmtree(d, ignore_errors=True)

    if not all_parsed:
        log.error(
            "No chats available. Put the chat exports from your phone ('WhatsApp Chat - <name>.zip' "
            f"or 'WhatsApp Chat with <name>.zip/.txt') in {ZIP_FOLDERS[0]}, or pass --zip-dir <folder>."
        )
        sys.exit(1)


    overall = phase3_analysis(all_parsed, skip=args.skip_analysis)


    resolution = phase4_phone_resolution(all_parsed)


    elapsed = time.time() - t0
    total_msgs = sum(c.get("message_count", 0) for c in all_parsed)

    log.info("\n" + "=" * 70)
    log.info("PIPELINE COMPLETE")
    log.info("=" * 70)
    log.info(f"  Total chats:      {len(all_parsed)}")
    log.info(f"  Total messages:   {total_msgs}")
    log.info(
        f"  Phone resolved:   {resolution.get('total_resolved', 0)}/{resolution.get('total_phone_numbers', 0)}"
    )
    log.info(f"  Elapsed:          {elapsed:.1f}s")
    log.info(f"\n  Chats dir:    {CHATS_DIR}")
    log.info(f"  Analysis dir: {ANALYSIS_DIR}")


if __name__ == "__main__":
    main()
