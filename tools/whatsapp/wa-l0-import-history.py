#!/usr/bin/env python3
"""WhatsApp import of a bulk text export: one .txt file per chat, all chats at once.

Status: TESTED. This is the import the author used for his whole WhatsApp history (a bulk export
of every chat, then this import); wa-l0l3-full.py is the other half of the same path, for the
chats you export one by one from the phone. Live reading of WhatsApp is not set up.
The WhatsApp app itself exports one chat at a time; a text export of every chat at once in the
layout below comes from a separate export tool on a computer, which SBK does not include.

Input: a folder of .txt files ("WhatsApp - <chat name>.txt" or any name ending in .txt), each
written in this layout (a line of dashes between messages):

    ----------------------------------------------------
    <chat name>
    <YYYY-MM-DD HH:MM:SS> from <name> (+<phone>) - Read      (or Delivered, Listened, Played, Received)

    <message text, one or more lines>
    ----------------------------------------------------
    <chat name>
    <YYYY-MM-DD HH:MM:SS> to <name> - Read                    (a message YOU sent)

    <message text>
    ----------------------------------------------------
    <chat name>
    <YYYY-MM-DD HH:MM:SS> notification                        (system line, skipped)

Messages "to ..." are written under your name ("owner" in sbk.config.json). Optional
--attachments-dir: one sub-folder per chat, files named "<YYYY-MM-DD HH MM SS> - <sender> - <name>".

Output (merged with what is already there, the same message is never written twice):
    <data root>/whatsapp/chats/<slug>.json           one file per chat
    <data root>/whatsapp/chats/chats-index.json      regenerated
    <data root>/whatsapp/attachments-index.json      only with --attachments-dir
    <data root>/whatsapp/_ricevute-import.jsonl      one receipt per run (what came in)

Everything runs on your machine; nothing is sent anywhere.

    uv run python tools/whatsapp/wa-l0-import-history.py --text-dir ~/Downloads/whatsapp-text --dry-run
    uv run python tools/whatsapp/wa-l0-import-history.py --text-dir ~/Downloads/whatsapp-text
    uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder> --attachments-dir <folder>
"""




































from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path





_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    OWN_NAMES_NORMALIZED,
    OWNER_NAME,
    WHATSAPP_CHATS_DIR,
    mark_last_run,
)


if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import wa_ricevuta  # noqa: E402





# You, as sbk.config.json says: "owner" plus every spelling in "own_names".
OWNER_CANONICAL = OWNER_NAME
OWNER_NAMES = {normalize_name(n) for n in OWN_NAMES_NORMALIZED} | {normalize_name(OWNER_NAME)}

CHATS_DIR = WHATSAPP_CHATS_DIR
ATTACHMENTS_INDEX_FILE = DATA_ROOT / "whatsapp" / "attachments-index.json"
CHATS_INDEX_FILE = CHATS_DIR / "chats-index.json"

RICEVUTA_DIR = DATA_ROOT / "whatsapp"







RE_HEADER_FROM = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+from\s+(.+?)\s+-\s+(?:Read|Delivered|Listened|Played|Received)$"
)
RE_HEADER_TO = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+to\s+(.+?)\s+-\s+(?:Read|Delivered|Listened|Played|Received)$"
)
RE_HEADER_NOTIFICATION = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+notification$")


RE_PHONE_IN_NAME = re.compile(r"\((\+[\d\s]+)\)\s*$")
RE_PHONE_ONLY = re.compile(r"^\+[\d\s()\-]+$")


RE_SEPARATOR = re.compile(r"^-{4,}$")


RE_ATTACHMENT = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+-\s+(.+?)\s+-\s+(.+)$"
)

log = logging.getLogger("wa-import-history")







def is_owner(name: str) -> bool:
    """True when `name` is you (sbk.config.json "owner" / "own_names")."""
    return normalize_name(name) in OWNER_NAMES


def sanitize_filename(name: str) -> str:
    ""

    name = re.sub(r"^WhatsApp\s*-\s*", "", name, flags=re.I)
    name = re.sub(r"^WhatsApp\s+Chat\s*-\s*", "", name, flags=re.I)

    name = re.sub(r"[^\w\s\-\+]", "", name)
    name = re.sub(r"\s+", "-", name.strip())
    name = name.lower().strip("-")
    return name if name else "unknown-chat"


def msg_hash(timestamp: str, sender: str, text: str) -> str:
    ""
    key = f"{timestamp}|{normalize_name(sender)}|{text.strip()[:200]}"
    return hashlib.md5(key.encode()).hexdigest()


def extract_phone_from_sender(sender_raw: str) -> tuple[str, str | None]:
    ""







    m = RE_PHONE_IN_NAME.search(sender_raw)
    if m:
        phone_raw = m.group(1).strip()
        name = sender_raw[: m.start()].strip()
        phone = re.sub(r"[\s\-()]", "", phone_raw)
        return name, phone


    if RE_PHONE_ONLY.match(sender_raw.strip()):
        phone = re.sub(r"[\s\-()]", "", sender_raw.strip())
        return sender_raw.strip(), phone

    return sender_raw.strip(), None


def extract_chat_name_from_filename(filename: str) -> str:
    ""
    name = filename
    if name.endswith(".txt"):
        name = name[:-4]
    name = re.sub(r"^WhatsApp\s*-\s*", "", name).strip()
    return name







def parse_single_file(filepath: Path) -> dict:
    ""




    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            raw = filepath.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        log.warning("Cannot decode %s, skipping", filepath.name)
        return {}

    chat_name_from_file = extract_chat_name_from_filename(filepath.name)





    raw_lines = raw.split("\n")
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in raw_lines:
        if RE_SEPARATOR.match(line.strip()):
            if current_block:
                blocks.append(current_block)
            current_block = []
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    messages: list[dict] = []
    participants: Counter = Counter()
    phone_numbers: dict[str, str] = {}
    chat_name_detected = None

    for block_lines in blocks:

        while block_lines and block_lines[0].strip() == "":
            block_lines = block_lines[1:]
        while block_lines and block_lines[-1].strip() == "":
            block_lines = block_lines[:-1]

        if len(block_lines) < 2:
            continue

        lines = block_lines


        block_chat_name = lines[0].strip()
        if not chat_name_detected and block_chat_name:
            chat_name_detected = block_chat_name


        header_line = lines[1].strip()


        body_lines = lines[2:]

        if body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]
        text = "\n".join(body_lines).strip()


        m_from = RE_HEADER_FROM.match(header_line)
        m_to = RE_HEADER_TO.match(header_line)
        m_notif = RE_HEADER_NOTIFICATION.match(header_line)

        if m_from:
            ts_str = m_from.group(1)
            sender_raw = m_from.group(2)
            name, phone = extract_phone_from_sender(sender_raw)

            if phone:
                phone_numbers[phone] = name


            if is_owner(name):
                name = OWNER_CANONICAL

            messages.append(
                {
                    "timestamp": ts_str.replace(" ", "T"),
                    "sender": name,
                    "text": text,
                }
            )
            participants[name] += 1

        elif m_to:
            ts_str = m_to.group(1)
            recipient_raw = m_to.group(2).strip()


            messages.append(
                {
                    "timestamp": ts_str.replace(" ", "T"),
                    "sender": OWNER_CANONICAL,
                    "text": text,
                }
            )
            participants[OWNER_CANONICAL] += 1

        elif m_notif:

            continue
        else:

            continue


    final_chat_name = chat_name_detected or chat_name_from_file


    messages.sort(key=lambda m: m["timestamp"])

    return {
        "chat_name": final_chat_name,
        "source_file": filepath.name,
        "participants": dict(participants),
        "phone_numbers": phone_numbers,
        "messages": messages,
    }


def parse_all_files(text_dir: Path) -> list[dict]:
    ""



    txt_files = sorted(text_dir.glob("*.txt"))
    if not txt_files:
        log.error("No .txt files found in %s", text_dir)
        return []

    log.info("Found %d .txt files to parse", len(txt_files))

    results = []
    for i, fpath in enumerate(txt_files, 1):
        if i % 100 == 0:
            log.info("  Parsed %d / %d files...", i, len(txt_files))

        chat = parse_single_file(fpath)
        if chat and chat.get("messages"):
            results.append(chat)
        elif chat:
            log.debug("No messages in %s, skipping", fpath.name)

    log.info("Parsed %d files with messages out of %d total", len(results), len(txt_files))
    return results







def build_attachment_index(attachments_dir: Path, chat_names: dict[str, str]) -> dict:
    ""








    if not attachments_dir.exists():
        log.warning("Attachments directory not found: %s", attachments_dir)
        return {}

    index: dict[str, list[dict]] = {}
    total_files = 0


    name_to_slug: dict[str, str] = {}
    for slug, cname in chat_names.items():
        name_to_slug[cname.lower()] = slug

        clean = re.sub(r"^whatsapp\s*-\s*", "", cname.lower()).strip()
        name_to_slug[clean] = slug

    for subdir in sorted(attachments_dir.iterdir()):
        if not subdir.is_dir():
            continue

        dirname = subdir.name

        dirname_lower = dirname.lower()
        slug = name_to_slug.get(dirname_lower)
        if not slug:

            slug = sanitize_filename(dirname)

        attachments = []
        for fpath in sorted(subdir.iterdir()):
            if fpath.is_dir():
                continue

            m = RE_ATTACHMENT.match(fpath.name)
            if m:
                date_str = m.group(1)
                h, mi, s = m.group(2), m.group(3), m.group(4)
                sender = m.group(5)
                rest = m.group(6)
                ext = fpath.suffix.lstrip(".")
                ts = f"{date_str}T{h}:{mi}:{s}"
            else:

                sender = "unknown"
                ext = fpath.suffix.lstrip(".")
                ts = None


            ext_lower = ext.lower()
            if ext_lower in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
                att_type = "image"
            elif ext_lower in ("mp4", "mov", "avi", "3gp"):
                att_type = "video"
            elif ext_lower in ("opus", "ogg", "m4a", "mp3", "wav", "aac"):
                att_type = "audio"
            elif ext_lower in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv"):
                att_type = "document"
            else:
                att_type = "other"

            attachments.append(
                {
                    "type": att_type,
                    "path": str(fpath),
                    "sender": sender,
                    "timestamp": ts,
                    "ext": ext_lower,
                    "size_bytes": fpath.stat().st_size,
                }
            )
            total_files += 1

        if attachments:
            index[slug] = attachments

    log.info("Indexed %d attachment files across %d chats", total_files, len(index))
    return index







def load_existing_chat(slug: str) -> dict | None:
    ""

    json_path = CHATS_DIR / f"{slug}.json"
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load %s: %s", json_path, e)


    dir_path = CHATS_DIR / slug
    if dir_path.is_dir():
        chat_json = dir_path / "chat.json"
        if chat_json.exists():
            try:
                return json.loads(chat_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load %s: %s", chat_json, e)

    return None


def merge_chats(existing: dict, new_data: dict) -> tuple[dict, int, int]:
    ""




    existing_hashes: set[str] = set()
    for msg in existing.get("messages", []):
        h = msg_hash(msg["timestamp"], msg["sender"], msg.get("text", ""))
        existing_hashes.add(h)

    new_msgs = []
    dedup_count = 0

    for msg in new_data.get("messages", []):
        h = msg_hash(msg["timestamp"], msg["sender"], msg.get("text", ""))
        if h in existing_hashes:
            dedup_count += 1
        else:
            new_msgs.append(msg)
            existing_hashes.add(h)


    all_messages = existing.get("messages", []) + new_msgs
    all_messages.sort(key=lambda m: m["timestamp"])


    merged_participants = dict(existing.get("participants", {}))
    for name, count in new_data.get("participants", {}).items():
        merged_participants[name] = merged_participants.get(name, 0) + count


    merged_phones = dict(existing.get("phone_numbers", {}))
    merged_phones.update(new_data.get("phone_numbers", {}))


    merged = dict(existing)
    merged["messages"] = all_messages
    merged["participants"] = merged_participants
    merged["phone_numbers"] = merged_phones
    merged["message_count"] = len(all_messages)
    if all_messages:
        merged["date_start"] = all_messages[0]["timestamp"]
        merged["date_end"] = all_messages[-1]["timestamp"]


    if new_data.get("source_file"):
        existing_source = merged.get("source_file", "")
        if new_data["source_file"] not in existing_source:
            merged["source_file"] = f"{existing_source}; {new_data['source_file']}".strip("; ")

    return merged, len(new_msgs), dedup_count







def write_chat(slug: str, chat_data: dict, dry_run: bool = False) -> Path:
    ""
    out_path = CHATS_DIR / f"{slug}.json"

    if dry_run:
        return out_path

    CHATS_DIR.mkdir(parents=True, exist_ok=True)


    output = {
        "chat_name": chat_data.get("chat_name", ""),
        "source_file": chat_data.get("source_file", ""),
        "date_format_detected": chat_data.get("date_format_detected", "iso"),
        "participants": chat_data.get("participants", {}),
        "participant_count": len(chat_data.get("participants", {})),
        "message_count": len(chat_data.get("messages", [])),
        "phone_numbers": chat_data.get("phone_numbers", {}),
        "date_start": chat_data["messages"][0]["timestamp"] if chat_data.get("messages") else None,
        "date_end": chat_data["messages"][-1]["timestamp"] if chat_data.get("messages") else None,
        "messages": chat_data.get("messages", []),
    }


    for key in chat_data:
        if key not in output:
            output[key] = chat_data[key]

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def regenerate_index(dry_run: bool = False) -> dict:
    ""
    chats_info = []
    total_messages = 0
    all_participants: set[str] = set()

    if not CHATS_DIR.exists():
        return {}

    for fpath in sorted(CHATS_DIR.glob("*.json")):
        if fpath.name == "chats-index.json":
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        msg_count = len(data.get("messages", []))
        participants = data.get("participants", {})
        total_messages += msg_count

        if isinstance(participants, dict):
            all_participants.update(participants.keys())
        elif isinstance(participants, list):
            all_participants.update(participants)

        chats_info.append(
            {
                "chat_name": data.get("chat_name", ""),
                "sanitized_name": fpath.stem,
                "source_path": "",
                "source_file": data.get("source_file", ""),
                "source_file_size_bytes": fpath.stat().st_size,
                "output_file": str(fpath),
                "output_file_size_bytes": fpath.stat().st_size,
                "date_format_detected": data.get("date_format_detected", ""),
                "participants": participants
                if isinstance(participants, dict)
                else dict.fromkeys(participants, 0),
                "participant_count": len(participants),
                "message_count": msg_count,
                "date_start": data.get("date_start"),
                "date_end": data.get("date_end"),
            }
        )

    index = {
        "generated_at": datetime.now().isoformat(),
        "total_chats": len(chats_info),
        "total_messages": total_messages,
        "total_participants": len(all_participants),
        "chats": chats_info,
    }

    if not dry_run:
        CHATS_INDEX_FILE.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Index written: %d chats, %d messages", len(chats_info), total_messages)

    return index







def run(
    text_dir: Path,
    attachments_dir: Path | None = None,
    dry_run: bool = False,
    skip_attachments: bool = False,
    dichiarato: str | None = None,
) -> dict:
    ""



    t0 = time.time()


    log.info("=" * 60)
    log.info("PHASE 1: Parsing .txt files from %s", text_dir)
    log.info("=" * 60)

    parsed_chats = parse_all_files(text_dir)
    if not parsed_chats:
        log.error("No chats parsed. Aborting.")
        return {"error": "No chats parsed"}

    total_messages_parsed = sum(len(c["messages"]) for c in parsed_chats)
    log.info("Parsed %d chats with %d messages total", len(parsed_chats), total_messages_parsed)


    attachment_index: dict = {}
    if attachments_dir and not skip_attachments:
        log.info("=" * 60)
        log.info("PHASE 2: Indexing attachments from %s", attachments_dir)
        log.info("=" * 60)


        chat_names = {}
        for chat in parsed_chats:
            slug = sanitize_filename(chat["chat_name"])
            chat_names[slug] = chat["chat_name"]

        attachment_index = build_attachment_index(attachments_dir, chat_names)
    else:
        log.info("Skipping attachment indexing")


    ricevuta = None
    if not dry_run:
        chat_prima = sum(1 for f in CHATS_DIR.glob("*.json") if f.name != CHATS_INDEX_FILE.name)
        ricevuta = wa_ricevuta.inizio(
            RICEVUTA_DIR, "wa-l0-import-history", dichiarato, [str(text_dir)]
        )


    log.info("=" * 60)
    log.info("PHASE 3: Merging with existing chats")
    log.info("=" * 60)

    stats = {
        "chats_new": 0,
        "chats_merged": 0,
        "chats_skipped": 0,
        "messages_new": 0,
        "messages_dedup": 0,
        "messages_total": 0,
        "attachments_indexed": sum(len(v) for v in attachment_index.values()),
        "attachment_chats": len(attachment_index),
    }


    slug_map: dict[str, list[dict]] = defaultdict(list)
    for chat in parsed_chats:
        slug = sanitize_filename(chat["chat_name"])
        slug_map[slug].append(chat)


    for slug, chat_list in sorted(slug_map.items()):

        combined = {
            "chat_name": chat_list[0]["chat_name"],
            "source_file": "; ".join(c["source_file"] for c in chat_list),
            "participants": {},
            "phone_numbers": {},
            "messages": [],
        }
        for chat in chat_list:
            combined["messages"].extend(chat["messages"])
            for name, count in chat["participants"].items():
                combined["participants"][name] = combined["participants"].get(name, 0) + count
            combined["phone_numbers"].update(chat.get("phone_numbers", {}))


        combined["messages"].sort(key=lambda m: m["timestamp"])


        existing = load_existing_chat(slug)

        if existing:
            merged, new_count, dedup_count = merge_chats(existing, combined)
            if new_count > 0:
                stats["chats_merged"] += 1
                stats["messages_new"] += new_count
                stats["messages_dedup"] += dedup_count
                if not dry_run:
                    write_chat(slug, merged, dry_run=dry_run)
                log.debug("Merged %s: +%d new, %d dedup", slug, new_count, dedup_count)
            else:
                stats["chats_skipped"] += 1
                stats["messages_dedup"] += dedup_count
                log.debug("No new messages for %s (%d dedup)", slug, dedup_count)
        else:
            stats["chats_new"] += 1
            stats["messages_new"] += len(combined["messages"])
            write_chat(slug, combined, dry_run=dry_run)
            log.debug("New chat %s: %d messages", slug, len(combined["messages"]))

    stats["messages_total"] = stats["messages_new"] + stats["messages_dedup"]


    log.info("=" * 60)
    log.info("PHASE 4: Writing output")
    log.info("=" * 60)


    if not dry_run:
        index = regenerate_index(dry_run=dry_run)
        stats["index_total_chats"] = index.get("total_chats", 0)
        stats["index_total_messages"] = index.get("total_messages", 0)
    else:
        log.info("[DRY RUN] Would regenerate chats-index.json")


    if attachment_index and not dry_run:
        ATTACHMENTS_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        ATTACHMENTS_INDEX_FILE.write_text(
            json.dumps(attachment_index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Attachment index written: %s", ATTACHMENTS_INDEX_FILE)
    elif attachment_index and dry_run:
        log.info("[DRY RUN] Would write attachment index with %d entries", len(attachment_index))


    elapsed = time.time() - t0
    stats["elapsed_seconds"] = round(elapsed, 1)

    log.info("=" * 60)
    log.info("IMPORT COMPLETE")
    log.info("=" * 60)
    log.info("  Chats new:          %d", stats["chats_new"])
    log.info("  Chats merged:       %d", stats["chats_merged"])
    log.info("  Chats skipped:      %d", stats["chats_skipped"])
    log.info("  Messages new:       %d", stats["messages_new"])
    log.info("  Messages dedup:     %d", stats["messages_dedup"])
    log.info(
        "  Attachments:        %d across %d chats",
        stats["attachments_indexed"],
        stats["attachment_chats"],
    )
    log.info("  Time:               %.1fs", elapsed)
    if dry_run:
        log.info("  *** DRY RUN — no files written ***")

    if ricevuta:
        adesso = datetime.now().isoformat()
        wa_ricevuta.fine(
            RICEVUTA_DIR,
            ricevuta,
            "wa-l0-import-history",
            viste=len(slug_map),
            nuove=stats["chats_new"],
            aggiornate=stats["chats_merged"],
            uguali=stats["chats_skipped"],
            errori=0,
            chat_prima=chat_prima,
            chat_dopo=stats.get("index_total_chats", 0),
            dati_fino_al=max(
                (
                    m["timestamp"]
                    for c in parsed_chats
                    for m in c["messages"]
                    if m["timestamp"] <= adesso
                ),
                default=None,
            ),
            dichiarato=dichiarato,
            messaggi_nuovi=stats["messages_new"],
        )

    return stats







def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import WhatsApp text export files into SBK pipeline"
    )
    p.add_argument(
        "--text-dir",
        type=Path,
        required=True,
        help="Directory containing .txt export files",
    )
    p.add_argument(
        "--attachments-dir",
        type=Path,
        default=None,
        help="Directory containing attachment subdirectories (optional)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing any files",
    )
    p.add_argument(
        "--skip-attachments",
        action="store_true",
        help="Skip attachment indexing even if --attachments-dir is set",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    wa_ricevuta.add_declare_argument(p)
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.text_dir.exists():
        log.error("Text directory not found: %s", args.text_dir)
        sys.exit(1)






    try:
        from ingestion.loud_fail import guard_zero_suspicious

        n_txt = len(list(args.text_dir.glob("*.txt")))
        guard_zero_suspicious(n_txt, min_expected=1, context=f"wa import {args.text_dir}")
    except ImportError:
        pass

    stats = run(
        text_dir=args.text_dir,
        attachments_dir=args.attachments_dir,
        dry_run=args.dry_run,
        skip_attachments=args.skip_attachments,
        dichiarato=args.dichiara,
    )

    if "error" in stats:
        sys.exit(1)





    if not args.dry_run:
        mark_last_run("whatsapp")






try:
    from pipeline_decorator import pipeline_step

    main = pipeline_step(
        name="l0-whatsapp-import-history", source="whatsapp", stage="l0", mark_run=False
    )(main)
except ImportError:
    pass

if __name__ == "__main__":
    main()
