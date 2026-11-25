#!/usr/bin/env python3
""














from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    ATTIO_DIR,
    DATA_ROOT,
    EMAILS_DIR,
    ENRICHED_DIR,
    NOTION_DIR,
    SLACK_CONVERSATIONS_DIR,
    WHATSAPP_DIR,
)

log = logging.getLogger("xs-l2-attachment-discovery")



OUTPUT_FILE = ENRICHED_DIR / "person-attachments-index.json"
WA_ATTACHMENTS_INDEX = DATA_ROOT / "whatsapp" / "attachments-index.json"
WA_CONTACTS_FILE = WHATSAPP_DIR / "contacts-whatsapp.parquet"
CONTACTS_MERGED_FILE = ENRICHED_DIR / "contacts-merged.parquet"
ENTITY_MAP_FILE = ENRICHED_DIR / "entity-map.json"
GDRIVE_INDEX_FILE = DATA_ROOT / "gdrive" / "gdrive-index.json"
SLACK_USERS_FILE = DATA_ROOT / "slack" / "slack-users.json"
SLACK_DM_DIR = DATA_ROOT / "slack" / "dm"
ATTIO_NOTES_FILE = ATTIO_DIR / "notes.parquet"
ATTIO_PEOPLE_FILE = ATTIO_DIR / "people.parquet"
NOTION_PAGES_FILE = NOTION_DIR / "pages-text.parquet"
COMPOSITE_SCORES_FILE = DATA_ROOT / "rq" / "composite-scores-v3.parquet"

from sbk_config import EMAIL_ACCOUNTS


EXT_CATEGORIES = {

    "pdf": "pdf",
    "doc": "docx",
    "docx": "docx",
    "pptx": "pptx",
    "ppt": "pptx",
    "xlsx": "xlsx",
    "xls": "xlsx",
    "csv": "csv",
    "txt": "txt",
    "rtf": "docx",
    "odt": "docx",
    "ods": "xlsx",
    "odp": "pptx",

    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "heic": "image",
    "svg": "image",
    "bmp": "image",
    "tiff": "image",
    "tif": "image",

    "opus": "audio",
    "mp3": "audio",
    "m4a": "audio",
    "wav": "audio",
    "ogg": "audio",
    "aac": "audio",

    "mp4": "video",
    "mov": "video",
    "avi": "video",
    "mkv": "video",
    "webm": "video",

    "ics": "calendar",

    "zip": "archive",
    "7z": "archive",
    "rar": "archive",
    "tar": "archive",
    "gz": "archive",

    "json": "data",
    "xml": "data",
    "html": "data",
    "eml": "email",

    "url": "link",
    "webloc": "link",
}


def _categorize_ext(ext: str) -> str:
    ""
    ext = (ext or "").lower().strip(".")
    return EXT_CATEGORIES.get(ext, "other")


def _categorize_mime(mime: str) -> str:
    ""
    mime = (mime or "").lower()
    if "image" in mime:
        return "image"
    if "audio" in mime:
        return "audio"
    if "video" in mime:
        return "video"
    if "pdf" in mime:
        return "pdf"
    if "spreadsheet" in mime or "excel" in mime:
        return "xlsx"
    if "presentation" in mime or "powerpoint" in mime:
        return "pptx"
    if "document" in mime or "word" in mime:
        return "docx"
    if "text" in mime:
        return "txt"
    if "calendar" in mime:
        return "calendar"
    if "zip" in mime or "archive" in mime or "compressed" in mime:
        return "archive"
    return "other"





def _load_top_people(top_n: int, person_filter: str | None) -> pd.DataFrame:
    ""



    contacts = pd.read_parquet(CONTACTS_MERGED_FILE)

    if person_filter:

        pattern = person_filter.lower()
        mask = contacts["name"].str.lower().str.contains(pattern, na=False)
        result = contacts[mask].copy()
        if result.empty:
            log.warning("No person matching '%s' found in contacts-merged", person_filter)
            return pd.DataFrame(columns=["person_id", "name", "all_emails", "phone_primary"])
        log.info("Filtered to %d people matching '%s'", len(result), person_filter)
    else:

        if COMPOSITE_SCORES_FILE.exists():
            scores = pd.read_parquet(COMPOSITE_SCORES_FILE)
            top_pids = (
                scores.sort_values("score_v3", ascending=False).head(top_n)["person"].tolist()
            )

            result = contacts[contacts["person_id"].isin(top_pids)].copy()

            missing = set(top_pids) - set(result["person_id"].tolist())
            if missing:
                log.info("%d top people not in contacts-merged (pid only)", len(missing))
        else:
            log.warning("No composite-scores-v3.parquet found, using top %d by source_count", top_n)
            result = contacts.sort_values("source_count", ascending=False).head(top_n).copy()

    cols = ["person_id", "name", "all_emails", "phone_primary"]
    for c in cols:
        if c not in result.columns:
            result[c] = None

    return result[cols].reset_index(drop=True)


def _build_email_to_person(contacts: pd.DataFrame, entity_map: dict) -> dict[str, tuple[str, str]]:
    ""



    email_map: dict[str, tuple[str, str]] = {}


    for _, row in contacts.iterrows():
        pid = row.get("person_id", "")
        name = row.get("name", "")
        emails = row.get("all_emails")
        if isinstance(emails, str):
            try:
                emails = json.loads(emails)
            except (json.JSONDecodeError, TypeError):
                emails = [e.strip() for e in emails.split(",") if e.strip()]
        if isinstance(emails, list):
            for e in emails:
                if isinstance(e, str) and e:
                    email_map[e.lower()] = (pid, name)


    for email_key, info in entity_map.items():
        email_lower = email_key.lower()
        if email_lower not in email_map:
            pid = info.get("person_id", "")
            cname = info.get("canonical_name", "")
            if pid:
                email_map[email_lower] = (pid, cname)

    return email_map


def _build_phone_to_person() -> dict[str, tuple[str, str]]:
    ""




    phone_map: dict[str, tuple[str, str]] = {}

    if not CONTACTS_MERGED_FILE.exists():
        return phone_map

    all_contacts = pd.read_parquet(
        CONTACTS_MERGED_FILE, columns=["person_id", "name", "phone_primary"]
    )
    for _, row in all_contacts.iterrows():
        pid = row.get("person_id", "")
        name = row.get("name", "")
        phone = row.get("phone_primary")
        if pd.notna(phone) and phone:
            normalized = re.sub(r"[^\d+]", "", str(phone))
            if normalized:
                phone_map[normalized] = (pid, name)

    return phone_map


def _build_wa_phone_to_name() -> dict[str, str]:
    ""
    if not WA_CONTACTS_FILE.exists():
        return {}
    wa = pd.read_parquet(WA_CONTACTS_FILE)
    result = {}
    for _, row in wa.iterrows():
        phone = str(row.get("phone", ""))
        name = str(row.get("name", ""))
        if phone and name:
            result[phone] = name
    return result


def _build_slack_user_map() -> dict[str, tuple[str, str]]:
    ""
    if not SLACK_USERS_FILE.exists():
        return {}
    users = json.loads(SLACK_USERS_FILE.read_text(encoding="utf-8"))
    result = {}
    for uid, info in users.items():
        real_name = info.get("real_name", info.get("name", uid))
        email = info.get("email", "")
        result[uid] = (real_name, email)
    return result


def _normalize_phone(phone: str) -> str:
    ""
    return re.sub(r"[^\d+]", "", str(phone))


def _extract_email_from_header(header: str) -> str:
    ""
    match = re.search(r"<([^>]+)>", header or "")
    if match:
        return match.group(1).lower()

    cleaned = (header or "").strip().lower()
    if "@" in cleaned:
        return cleaned
    return ""





def _build_wa_phone_to_chat_name() -> dict[str, str]:
    ""




    chats_dir = DATA_ROOT / "whatsapp" / "chats"
    if not chats_dir.exists():
        return {}

    result = {}
    for json_file in chats_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        participant_count = data.get("participant_count", 0)
        if participant_count > 2:
            continue

        chat_name = data.get("chat_name", "")

        clean_name = re.sub(r"^WhatsApp Chat\s*-\s*", "", chat_name).strip()

        if clean_name and not clean_name.startswith("+") and not clean_name[0].isdigit():
            phone_key = json_file.stem
            result[phone_key] = clean_name

    return result


def scan_whatsapp(
    target_pids: set[str],
    phone_to_person: dict[str, tuple[str, str]],
    wa_phone_to_name: dict[str, str],
    contacts_df: pd.DataFrame,
) -> dict[str, list[dict]]:
    ""
    results: dict[str, list[dict]] = defaultdict(list)

    if not WA_ATTACHMENTS_INDEX.exists():
        log.warning("WhatsApp attachments-index.json not found")
        return results

    wa_index = json.loads(WA_ATTACHMENTS_INDEX.read_text(encoding="utf-8"))
    log.info("WhatsApp: scanning %d chat attachment groups", len(wa_index))


    wa_phone_to_chat_name = _build_wa_phone_to_chat_name()
    log.debug("WA chat-based phone->name: %d entries", len(wa_phone_to_chat_name))


    name_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        pid = row.get("person_id", "")
        name = str(row.get("name", ""))
        if pid in target_pids and name:
            name_to_pid[name.lower()] = pid

    matched = 0
    for chat_phone, attachments in wa_index.items():
        norm_phone = _normalize_phone(chat_phone)


        person_info = phone_to_person.get(norm_phone)


        if not person_info:
            chat_name = wa_phone_to_chat_name.get(chat_phone)
            if chat_name and chat_name.lower() in name_to_pid:
                pid = name_to_pid[chat_name.lower()]
                match_rows = contacts_df[contacts_df["person_id"] == pid]
                cname = match_rows.iloc[0]["name"] if not match_rows.empty else chat_name
                person_info = (pid, cname)


        if not person_info:
            wa_name = wa_phone_to_name.get(chat_phone)
            if not wa_name:
                for wp, wn in wa_phone_to_name.items():
                    if _normalize_phone(wp) == norm_phone:
                        wa_name = wn
                        break
            if wa_name and wa_name.lower() in name_to_pid:
                pid = name_to_pid[wa_name.lower()]
                match_rows = contacts_df[contacts_df["person_id"] == pid]
                cname = match_rows.iloc[0]["name"] if not match_rows.empty else wa_name
                person_info = (pid, cname)

        if not person_info:
            continue
        pid, person_name = person_info
        if pid not in target_pids:
            continue

        matched += 1
        for att in attachments:
            ext = (att.get("ext") or "").lower()
            category = _categorize_ext(ext) if ext else att.get("type", "other")

            if category in ("document",):
                category = _categorize_ext(ext) if ext else "docx"

            results[pid].append(
                {
                    "source": "whatsapp",
                    "type": category,
                    "ext": ext,
                    "path": att.get("path", ""),
                    "sender": att.get("sender", ""),
                    "timestamp": att.get("timestamp", ""),
                    "size_bytes": att.get("size_bytes", 0),
                    "context": "",
                }
            )

    log.info(
        "WhatsApp: matched %d chats, %d total attachments",
        matched,
        sum(len(v) for v in results.values()),
    )
    return results


def scan_emails(
    target_pids: set[str],
    email_to_person: dict[str, tuple[str, str]],
) -> dict[str, list[dict]]:
    ""
    results: dict[str, list[dict]] = defaultdict(list)

    for account in EMAIL_ACCOUNTS:
        index_file = EMAILS_DIR / account / "attachments" / "index.parquet"
        messages_file = EMAILS_DIR / account / "messages.parquet"

        if not index_file.exists():
            log.debug("Email %s: no attachment index", account)
            continue
        if not messages_file.exists():
            log.debug("Email %s: no messages parquet", account)
            continue

        att_df = pd.read_parquet(index_file)
        msg_df = pd.read_parquet(
            messages_file, columns=["id", "from_addr", "to_addr", "subject", "date"]
        )


        msg_map = {}
        for _, row in msg_df.iterrows():
            msg_id = row.get("id", "")
            from_addr = _extract_email_from_header(str(row.get("from_addr", "")))
            to_raw = str(row.get("to_addr", ""))
            to_addrs = [_extract_email_from_header(t.strip()) for t in to_raw.split(",")]
            to_addrs = [t for t in to_addrs if t]
            msg_map[msg_id] = {
                "from": from_addr,
                "to": to_addrs,
                "subject": str(row.get("subject", ""))[:100],
                "date": str(row.get("date", "")),
            }

        matched = 0
        for _, att_row in att_df.iterrows():
            msg_id = att_row.get("msg_id", "")
            msg_info = msg_map.get(msg_id)
            if not msg_info:
                continue


            all_emails = [msg_info["from"]] + msg_info["to"]
            matched_pid = None
            for email_addr in all_emails:
                info = email_to_person.get(email_addr)
                if info and info[0] in target_pids:
                    matched_pid = info[0]
                    break

            if not matched_pid:
                continue

            matched += 1
            ext = str(att_row.get("ext", "")).lower()
            filename = str(att_row.get("filename", ""))
            category = _categorize_ext(ext)

            results[matched_pid].append(
                {
                    "source": "email",
                    "type": category,
                    "ext": ext,
                    "path": str(att_row.get("path", "")),
                    "filename": filename,
                    "sender": msg_info["from"],
                    "timestamp": msg_info["date"],
                    "size_bytes": int(att_row.get("size", 0) or 0),
                    "context": msg_info["subject"],
                    "account": account,
                }
            )

        log.info("Email %s: %d attachment matches from %d total", account, matched, len(att_df))

    return results


def scan_slack(
    target_pids: set[str],
    email_to_person: dict[str, tuple[str, str]],
    slack_user_map: dict[str, tuple[str, str]],
) -> dict[str, list[dict]]:
    ""
    results: dict[str, list[dict]] = defaultdict(list)


    uid_to_pid: dict[str, str] = {}
    for uid, (real_name, email) in slack_user_map.items():
        if email:
            info = email_to_person.get(email.lower())
            if info and info[0] in target_pids:
                uid_to_pid[uid] = info[0]


    from slack_esclusi import e_escluso, esclusi

    fuori = esclusi()

    def _scan_dir(scan_dir: Path, label: str) -> int:
        count = 0
        if not scan_dir.exists():
            return count
        for json_file in sorted(scan_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if e_escluso(data, fuori):
                continue

            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("messages", [])
            else:
                continue

            channel_name = json_file.stem

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                if "files" not in msg:
                    continue

                user_id = msg.get("user", "")
                pid = uid_to_pid.get(user_id)
                if not pid:
                    continue

                ts = msg.get("ts", "")

                try:
                    ts_iso = datetime.fromtimestamp(float(ts)).isoformat() if ts else ""
                except (ValueError, OSError):
                    ts_iso = ts

                files_list = msg.get("files", [])
                for f in files_list:
                    if not isinstance(f, dict):
                        continue
                    fname = f.get("name", "")
                    mime = f.get("mimetype", "")
                    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    category = _categorize_ext(ext) if ext else _categorize_mime(mime)

                    results[pid].append(
                        {
                            "source": "slack",
                            "type": category,
                            "ext": ext,
                            "filename": fname,
                            "url": f.get("url", ""),
                            "sender": slack_user_map.get(user_id, (user_id, ""))[0],
                            "timestamp": ts_iso,
                            "size_bytes": int(f.get("size", 0) or 0),
                            "context": f"channel:{channel_name}",
                            "slack_file_id": f.get("id", ""),
                        }
                    )
                    count += 1

        return count

    count_conv = _scan_dir(SLACK_CONVERSATIONS_DIR, "conversations")
    count_dm = _scan_dir(SLACK_DM_DIR, "dm")
    log.info("Slack: %d files from conversations, %d from DMs", count_conv, count_dm)

    return results


def scan_gdrive(
    target_pids: set[str],
    email_to_person: dict[str, tuple[str, str]],
) -> dict[str, list[dict]]:
    ""
    results: dict[str, list[dict]] = defaultdict(list)

    if not GDRIVE_INDEX_FILE.exists():
        log.warning("GDrive index not found")
        return results

    gdrive_index = json.loads(GDRIVE_INDEX_FILE.read_text(encoding="utf-8"))
    log.info("GDrive: scanning %d files", len(gdrive_index))

    matched = 0
    for item in gdrive_index:
        owners = item.get("owners", [])
        matched_pid = None
        matched_owner = ""
        for owner_email in owners:
            info = email_to_person.get(owner_email.lower())
            if info and info[0] in target_pids:
                matched_pid = info[0]
                matched_owner = owner_email
                break

        if not matched_pid:
            continue

        matched += 1
        mime = item.get("mimeType", "")
        name = item.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""


        if "google-apps" in mime:
            if "spreadsheet" in mime:
                category = "xlsx"
            elif "presentation" in mime:
                category = "pptx"
            elif "document" in mime:
                category = "docx"
            elif "folder" in mime:
                continue
            elif "form" in mime:
                category = "data"
            else:
                category = "other"
        else:
            category = _categorize_ext(ext) if ext else _categorize_mime(mime)

        results[matched_pid].append(
            {
                "source": "gdrive",
                "type": category,
                "ext": ext or item.get("export_format", ""),
                "filename": name,
                "path": item.get("local_path", ""),
                "owner": matched_owner,
                "timestamp": item.get("modifiedTime", item.get("createdTime", "")),
                "size_bytes": int(item.get("size", 0) or 0),
                "url": item.get("webViewLink", ""),
                "folder": item.get("folder_path", ""),
            }
        )

    log.info("GDrive: %d files matched to target people", matched)
    return results


def scan_attio(
    target_pids: set[str],
    contacts_df: pd.DataFrame,
) -> dict[str, list[dict]]:
    ""




    results: dict[str, list[dict]] = defaultdict(list)

    if not ATTIO_NOTES_FILE.exists():
        log.warning("Attio notes.parquet not found")
        return results

    notes_df = pd.read_parquet(ATTIO_NOTES_FILE)



    attio_record_to_pid: dict[str, str] = {}
    if ATTIO_PEOPLE_FILE.exists():
        people_df = pd.read_parquet(ATTIO_PEOPLE_FILE)

        pid_by_name: dict[str, str] = {}
        for _, row in contacts_df.iterrows():
            pid = row.get("person_id", "")
            name = str(row.get("name", "")).lower()
            if pid in target_pids and name:
                pid_by_name[name] = pid


        for _, row in people_df.iterrows():
            record_id = str(row.get("record_id", row.get("id", "")))
            attio_name = str(row.get("name", "")).lower()
            if attio_name in pid_by_name:
                attio_record_to_pid[record_id] = pid_by_name[attio_name]


    people_notes = notes_df[notes_df["parent_object"] == "people"]
    matched = 0
    for _, note in people_notes.iterrows():
        record_id = str(note.get("parent_record_id", ""))
        pid = attio_record_to_pid.get(record_id)
        if not pid:
            continue

        matched += 1
        title = str(note.get("title", ""))
        content = str(note.get("content_plaintext", ""))[:200]
        created = str(note.get("created_at", ""))


        has_url = bool(re.search(r"https?://\S+", str(note.get("content_plaintext", ""))))

        results[pid].append(
            {
                "source": "attio",
                "type": "note",
                "title": title,
                "timestamp": created,
                "content_preview": content,
                "has_urls": has_url,
                "note_id": str(note.get("note_id", "")),
            }
        )

    log.info("Attio: %d notes matched to target people", matched)
    return results


def scan_notion(
    target_pids: set[str],
    contacts_df: pd.DataFrame,
) -> dict[str, list[dict]]:
    ""
    results: dict[str, list[dict]] = defaultdict(list)

    if not NOTION_PAGES_FILE.exists():
        log.warning("Notion pages-text.parquet not found")
        return results

    pages_df = pd.read_parquet(NOTION_PAGES_FILE)
    log.info("Notion: scanning %d pages for person mentions", len(pages_df))


    name_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        pid = row.get("person_id", "")
        name = str(row.get("name", ""))
        if pid in target_pids and name and len(name) > 2:
            name_to_pid[name.lower()] = pid

    matched = 0
    for _, page in pages_df.iterrows():
        title = str(page.get("title", ""))
        text = str(page.get("page_text", ""))
        combined = f"{title} {text}".lower()

        for person_name, pid in name_to_pid.items():
            if person_name in combined:
                matched += 1
                results[pid].append(
                    {
                        "source": "notion",
                        "type": "page_mention",
                        "title": title,
                        "page_id": str(page.get("page_id", "")),
                        "timestamp": str(page.get("downloaded_at", "")),
                        "mention_in_title": person_name in title.lower(),
                    }
                )

    log.info("Notion: %d page-person matches", matched)
    return results





def _compute_totals(attachments: list[dict]) -> dict[str, int]:
    ""
    totals: dict[str, int] = defaultdict(int)
    for att in attachments:
        cat = att.get("type", "other")
        totals[cat] += 1
    return dict(sorted(totals.items(), key=lambda x: -x[1]))


def _aggregate_results(
    contacts_df: pd.DataFrame,
    target_pids: set[str],
    *source_results: dict[str, list[dict]],
) -> dict:
    ""

    pid_to_name = {}
    for _, row in contacts_df.iterrows():
        pid_to_name[row["person_id"]] = str(row.get("name", ""))

    output = {}
    for pid in sorted(target_pids):
        name = pid_to_name.get(pid, pid)
        if not name or name == pid:
            continue

        all_attachments: dict[str, list[dict]] = defaultdict(list)
        for source_data in source_results:
            for att in source_data.get(pid, []):
                source_key = att.get("source", "unknown")
                all_attachments[source_key].append(att)

        total_count = sum(len(v) for v in all_attachments.values())
        if total_count == 0:
            continue


        all_flat = []
        for atts in all_attachments.values():
            all_flat.extend(atts)

        output[name] = {
            "person_id": pid,
            "sources": {k: v for k, v in sorted(all_attachments.items())},
            "totals": _compute_totals(all_flat),
            "total_count": total_count,
        }

    return output





def main():
    parser = argparse.ArgumentParser(
        description="Discover attachments/files across all sources for top people"
    )
    parser.add_argument(
        "--top", type=int, default=150, help="Number of top people to scan (default: 100)"
    )
    parser.add_argument(
        "--person", type=str, default=None, help="Filter to a specific person by name"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be scanned, don't write output"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=== Attachment Discovery — top %d people ===", args.top)


    contacts_df = _load_top_people(args.top, args.person)
    if contacts_df.empty:
        log.error("No target people found. Exiting.")
        sys.exit(1)

    target_pids = set(contacts_df["person_id"].tolist())
    log.info("Target people: %d", len(target_pids))

    if args.dry_run:
        log.info("[DRY RUN] Would scan for these people:")
        for _, row in contacts_df.head(20).iterrows():
            log.info("  %s (%s)", row["name"], row["person_id"])
        if len(contacts_df) > 20:
            log.info("  ... and %d more", len(contacts_df) - 20)


    log.info("Building lookup maps...")
    entity_map = {}
    if ENTITY_MAP_FILE.exists():
        entity_map = json.loads(ENTITY_MAP_FILE.read_text(encoding="utf-8"))
    email_to_person = _build_email_to_person(contacts_df, entity_map)
    phone_to_person = _build_phone_to_person()
    wa_phone_to_name = _build_wa_phone_to_name()
    slack_user_map = _build_slack_user_map()
    log.info(
        "Maps: %d email->person, %d phone->person, %d wa phones, %d slack users",
        len(email_to_person),
        len(phone_to_person),
        len(wa_phone_to_name),
        len(slack_user_map),
    )

    if args.dry_run:
        log.info(
            "[DRY RUN] Sources to scan: WhatsApp, Email (%d accounts), Slack, GDrive, Attio, Notion",
            len(EMAIL_ACCOUNTS),
        )
        log.info("[DRY RUN] No output file will be written.")
        return


    log.info("--- Scanning WhatsApp ---")
    wa_results = scan_whatsapp(target_pids, phone_to_person, wa_phone_to_name, contacts_df)

    log.info("--- Scanning Email (%d accounts) ---", len(EMAIL_ACCOUNTS))
    email_results = scan_emails(target_pids, email_to_person)

    log.info("--- Scanning Slack ---")
    slack_results = scan_slack(target_pids, email_to_person, slack_user_map)

    log.info("--- Scanning GDrive ---")
    gdrive_results = scan_gdrive(target_pids, email_to_person)

    log.info("--- Scanning Attio ---")
    attio_results = scan_attio(target_pids, contacts_df)

    log.info("--- Scanning Notion ---")
    notion_results = scan_notion(target_pids, contacts_df)


    log.info("--- Aggregating results ---")
    output = _aggregate_results(
        contacts_df,
        target_pids,
        wa_results,
        email_results,
        slack_results,
        gdrive_results,
        attio_results,
        notion_results,
    )


    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


    total_people = len(output)
    total_attachments = sum(v["total_count"] for v in output.values())
    source_totals: dict[str, int] = defaultdict(int)
    for person_data in output.values():
        for source_key, atts in person_data["sources"].items():
            source_totals[source_key] += len(atts)

    log.info("=== DONE ===")
    log.info("People with attachments: %d / %d target", total_people, len(target_pids))
    log.info("Total attachment records: %d", total_attachments)
    for src, cnt in sorted(source_totals.items(), key=lambda x: -x[1]):
        log.info("  %s: %d", src, cnt)
    log.info("Output: %s", OUTPUT_FILE)


    ranked = sorted(output.items(), key=lambda x: -x[1]["total_count"])[:10]
    if ranked:
        log.info("Top 10 by attachment count:")
        for name, data in ranked:
            log.info(
                "  %s: %d (%s)",
                name,
                data["total_count"],
                ", ".join(f"{k}={v}" for k, v in data["totals"].items()),
            )


from pipeline_decorator import pipeline_step

main = pipeline_step(name="xs-l2-attachment-discovery", source="cross-source", stage="l2")(main)

if __name__ == "__main__":
    main()
