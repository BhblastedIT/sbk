#!/usr/bin/env python3
"""LinkedIn enrichment pipeline (L1)."""
























from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from text_utils import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    LINKEDIN_DIR,
    LINKEDIN_RAW_DIR,
    OWNER_LABEL,
    mark_last_run,
    safe_write_parquet,
)



# Everything is read from the data root: the export that li-l0-import-export.py imports
# (<data root>/linkedin/raw/export-*.parquet) and, if you ran them, the browser scripts' JSON files
# in the same folder. Nothing is read from or written into the repo.
RAW_LINKEDIN_DIR = LINKEDIN_RAW_DIR
PROCESSED_DIR = LINKEDIN_DIR

log = logging.getLogger("linkedin-enrich")

RAW_CONVERSATIONS_FULL = RAW_LINKEDIN_DIR / "linkedin-conversations-full.json"






# Your name in the interactions, from sbk.config.json "owner".
OWNER_NOME = OWNER_LABEL





def parse_iso_date(s: str) -> str | None:
    ""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def parse_iso_datetime(s: str) -> datetime | None:
    ""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def load_json(path: Path) -> dict | list | None:
    ""
    if not path.exists():
        # The conversation files come from the optional browser scripts: the export path has none.
        log.info(f"{path.name}: not there (optional, only the browser scripts write it)")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot load {path.name}: {e}")
        return None


def extract_linkedin_id(url: str) -> str:
    ""
    if not url:
        return ""

    m = re.search(r"(ACoAA[A-Za-z0-9_-]+)", url)
    return m.group(1) if m else url


def parse_company_from_headline(headline: str) -> str:
    ""








    if not headline:
        return ""


    m = re.search(r"@\s*([A-Z][^\|@\n]+)", headline)
    if m:
        return m.group(1).strip().rstrip(" |")


    m = re.search(r"\bat\b\s+([A-Z][^\|@\n]+)", headline)
    if m:
        return m.group(1).strip().rstrip(" |")


    m = re.search(r"\bpresso\b\s+([A-Z][^\|@\n]+)", headline, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(" |")

    return ""


def build_profile_enrichment_map() -> dict[str, dict]:
    ""








    data = load_json(RAW_CONVERSATIONS_FULL)
    if not data:
        log.info("no linkedin-conversations-full.json: no headline enrichment")
        return {}

    enrichment: dict[str, dict] = {}


    sc_included = data.get("simpleConversations", {}).get("included", [])
    for item in sc_included:
        item_type = item.get("$type", "")
        if "Participant" not in item_type:
            continue

        member = item.get("participantType", {}).get("member", {})
        if not member:
            continue

        profile_url = member.get("profileUrl", "")
        lid = extract_linkedin_id(profile_url)
        if not lid:

            lid = extract_linkedin_id(item.get("hostIdentityUrn", ""))
        if not lid:
            continue

        headline_obj = member.get("headline", {})
        headline_text = ""
        if isinstance(headline_obj, dict):
            headline_text = headline_obj.get("text", "")
        elif isinstance(headline_obj, str):
            headline_text = headline_obj

        if headline_text:
            company = parse_company_from_headline(headline_text)
            enrichment[lid] = {
                "headline": headline_text,
                "company": company,
            }


    inv_included = data.get("invitations", {}).get("included", [])
    for item in inv_included:
        item_type = item.get("$type", "")
        if "MiniProfile" not in item_type:
            continue

        occupation = item.get("occupation", "")
        if not occupation:
            continue


        lid = extract_linkedin_id(item.get("dashEntityUrn", ""))
        if not lid:
            lid = extract_linkedin_id(item.get("objectUrn", ""))
        if not lid:
            continue


        if lid not in enrichment:
            company = parse_company_from_headline(occupation)
            enrichment[lid] = {
                "headline": occupation,
                "company": company,
            }

    log.info(
        f"Profile enrichment map: {len(enrichment)} profiles with headline "
        f"({sum(1 for e in enrichment.values() if e.get('company'))} with company parsed)"
    )
    return enrichment





def parse_threads_complete() -> list[dict]:
    ""
    path = RAW_LINKEDIN_DIR / "linkedin-threads-complete.json"
    data = load_json(path)
    if not data:
        if path.exists():
            log.warning("linkedin-threads-complete.json is empty or invalid")
        return []

    conversations = data.get("conversations", [])
    log.info(f"Phase 1a: Loaded {len(conversations)} conversations from threads-complete")
    return conversations


def parse_sales_navigator() -> list[dict]:
    ""
    path = RAW_LINKEDIN_DIR / "linkedin-threads-sales-navigator.json"
    data = load_json(path)
    if not data:
        if path.exists():
            log.warning("linkedin-threads-sales-navigator.json is empty or invalid")
        return []

    conversations = data.get("conversations", [])
    log.info(f"Phase 1b: Loaded {len(conversations)} conversations from Sales Navigator")
    return conversations


def parse_sent_notes() -> list[dict]:
    ""
    path = RAW_LINKEDIN_DIR / "linkedin-sent-notes.json"
    data = load_json(path)
    if not data or not isinstance(data, list):
        if path.exists():
            log.warning("linkedin-sent-notes.json is empty or invalid")
        return []

    log.info(f"Phase 1c: Loaded {len(data)} sent notes")
    return data


def load_export_connections() -> pd.DataFrame | None:
    ""
    path = LINKEDIN_RAW_DIR / "export-connections.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    log.info(f"Phase 1d: Loaded {len(df)} export connections")
    return df


def load_export_invitations() -> pd.DataFrame | None:
    ""
    path = LINKEDIN_RAW_DIR / "export-invitations.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    log.info(f"Phase 1e: Loaded {len(df)} export invitations")
    return df





def build_contacts(
    threads_complete: list[dict],
    sales_nav: list[dict],
    sent_notes: list[dict],
    profile_enrichment: dict[str, dict] | None = None,
    export_connections: pd.DataFrame | None = None,
    export_invitations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ""









    log.info("Phase 2: Building contacts-linkedin.parquet...")
    t0 = time.time()

    if profile_enrichment is None:
        profile_enrichment = {}


    contacts: dict[str, dict] = {}

    def get_or_create(name: str, linkedin_url: str) -> dict:
        lid = extract_linkedin_id(linkedin_url)
        if not lid:
            lid = normalize_name(name)
        if not lid:
            return None

        if lid not in contacts:
            contacts[lid] = {
                "name": name,
                "linkedin_url": linkedin_url or "",
                "linkedin_id": lid,
                "headline": "",
                "company": "",
                "email": "",
                "connection_date": None,
                "last_message_date": None,
                "first_message_date": None,
                "messages_sent": 0,
                "messages_received": 0,
                "has_connection_note": False,
                "categories": set(),
                "sources": set(),
            }
        return contacts[lid]


    for conv in threads_complete:
        participants = conv.get("participants", [])
        if not participants:
            continue

        p = participants[0]
        name = p.get("name", "")
        url = p.get("profileUrl", "")
        c = get_or_create(name, url)
        if c is None:
            continue

        c["sources"].add("threads-complete")
        conv_created = parse_iso_date(conv.get("createdAt", ""))


        for cat in conv.get("categories", []):
            c["categories"].add(cat)

        for msg in conv.get("messages", []):
            msg_date = parse_iso_date(msg.get("deliveredAt", ""))

            if msg.get("senderIsMe"):
                c["messages_sent"] += 1
            else:
                c["messages_received"] += 1

            if msg_date:
                if c["first_message_date"] is None or msg_date < c["first_message_date"]:
                    c["first_message_date"] = msg_date
                if c["last_message_date"] is None or msg_date > c["last_message_date"]:
                    c["last_message_date"] = msg_date


    for conv in sales_nav:
        participants = conv.get("participants", [])
        if not participants:
            continue

        p = participants[0]
        name = p.get("name", "")

        entity_urn = p.get("entityUrn", "")

        sn_id = extract_linkedin_id(entity_urn)


        existing_lid = None
        if sn_id:

            if sn_id in contacts:
                existing_lid = sn_id
            else:

                norm_name = normalize_name(name)
                for lid, cc in contacts.items():
                    if normalize_name(cc["name"]) == norm_name and norm_name:
                        existing_lid = lid
                        break

        if existing_lid:
            c = contacts[existing_lid]
        else:

            lid = sn_id or normalize_name(name)
            if not lid:
                continue
            if lid not in contacts:
                contacts[lid] = {
                    "name": name,
                    "linkedin_url": "",
                    "linkedin_id": lid,
                    "headline": "",
                    "company": "",
                    "email": "",
                    "connection_date": None,
                    "last_message_date": None,
                    "first_message_date": None,
                    "messages_sent": 0,
                    "messages_received": 0,
                    "has_connection_note": False,
                    "categories": set(),
                    "sources": set(),
                }
            c = contacts[lid]

        c["sources"].add("sales-navigator")

        for msg in conv.get("messages", []):
            msg_date = parse_iso_date(msg.get("deliveredAt", ""))
            msg_type = msg.get("type", "")

            if msg.get("senderIsMe"):

                if "threads-complete" not in c["sources"] or c["sources"] == {"sales-navigator"}:
                    c["messages_sent"] += 1
                if msg_type == "INVITATION":
                    c["has_connection_note"] = True
            else:
                if "threads-complete" not in c["sources"] or c["sources"] == {"sales-navigator"}:
                    c["messages_received"] += 1

            if msg_date:
                if c["first_message_date"] is None or msg_date < c["first_message_date"]:
                    c["first_message_date"] = msg_date
                if c["last_message_date"] is None or msg_date > c["last_message_date"]:
                    c["last_message_date"] = msg_date


    for note in sent_notes:
        name = note.get("to", "")
        url = note.get("toUrl", "")
        lid = extract_linkedin_id(url)

        if lid and lid in contacts:
            c = contacts[lid]
        elif lid:

            contacts[lid] = {
                "name": name,
                "linkedin_url": url or "",
                "linkedin_id": lid,
                "headline": "",
                "company": "",
                "email": "",
                "connection_date": None,
                "last_message_date": None,
                "first_message_date": None,
                "messages_sent": 0,
                "messages_received": 0,
                "has_connection_note": False,
                "categories": set(),
                "sources": set(),
            }
            c = contacts[lid]
        else:
            continue

        c["sources"].add("sent-notes")

        if note.get("isConnectionNote"):
            c["has_connection_note"] = True

            conn_date = parse_iso_date(note.get("conversationCreatedAt", ""))
            if conn_date:
                if c["connection_date"] is None or conn_date < c["connection_date"]:
                    c["connection_date"] = conn_date


    export_new = 0
    export_enriched = 0
    if export_connections is not None and len(export_connections) > 0:
        for _, row in export_connections.iterrows():
            name = str(row.get("name", "")).strip()
            url = str(row.get("linkedin_url", "")).strip()
            lid = extract_linkedin_id(url) or normalize_name(name)
            if not lid:
                continue

            if lid in contacts:
                c = contacts[lid]

                if not c["email"] and pd.notna(row.get("email_address")):
                    email = str(row["email_address"]).strip()
                    if email:
                        c["email"] = email
                        export_enriched += 1
                if not c["company"] and pd.notna(row.get("company")):
                    c["company"] = str(row["company"]).strip()
                if not c["connection_date"] and pd.notna(row.get("connected_on")):
                    c["connection_date"] = str(row["connected_on"]).strip()
                c["sources"].add("export-connections")
            else:

                company = (
                    str(row.get("company", "")).strip() if pd.notna(row.get("company")) else ""
                )
                email = (
                    str(row.get("email_address", "")).strip()
                    if pd.notna(row.get("email_address"))
                    else ""
                )
                position = (
                    str(row.get("position", "")).strip() if pd.notna(row.get("position")) else ""
                )
                connected_on = (
                    str(row.get("connected_on", "")).strip()
                    if pd.notna(row.get("connected_on"))
                    else ""
                )
                contacts[lid] = {
                    "name": name,
                    "linkedin_url": url,
                    "linkedin_id": lid,
                    "headline": position,
                    "company": company,
                    "email": email,
                    "connection_date": connected_on,
                    "last_message_date": None,
                    "first_message_date": None,
                    "messages_sent": 0,
                    "messages_received": 0,
                    "has_connection_note": False,
                    "categories": set(),
                    "sources": {"export-connections"},
                }
                export_new += 1

        log.info(
            f"  Export connections: {export_new} new contacts, "
            f"{export_enriched} enriched with email"
        )


    inv_new = 0
    inv_enriched = 0
    if export_invitations is not None and len(export_invitations) > 0:
        for _, row in export_invitations.iterrows():
            name = str(row.get("person_name", "")).strip()
            url = str(row.get("person_url", "")).strip()
            lid = extract_linkedin_id(url) or normalize_name(name)
            if not lid:
                continue

            if lid in contacts:
                c = contacts[lid]
                c["has_connection_note"] = True
                c["sources"].add("export-invitations")
                inv_enriched += 1
            else:
                contacts[lid] = {
                    "name": name,
                    "linkedin_url": url,
                    "linkedin_id": lid,
                    "headline": "",
                    "company": "",
                    "email": "",
                    "connection_date": None,
                    "last_message_date": None,
                    "first_message_date": None,
                    "messages_sent": 0,
                    "messages_received": 0,
                    "has_connection_note": True,
                    "categories": set(),
                    "sources": {"export-invitations"},
                }
                inv_new += 1

        log.info(f"  Export invitations: {inv_new} new contacts, {inv_enriched} existing enriched")


    enriched_count = 0
    company_count = 0
    for lid, c in contacts.items():
        if lid in profile_enrichment:
            enrich = profile_enrichment[lid]
            if enrich.get("headline") and not c["headline"]:
                c["headline"] = enrich["headline"]
                enriched_count += 1
            if enrich.get("company") and not c["company"]:
                c["company"] = enrich["company"]
                company_count += 1

    if enriched_count > 0:
        log.info(
            f"  Enriched {enriched_count} contacts with headline, "
            f"{company_count} with company (from conversations-full)"
        )


    rows = []
    for lid, c in contacts.items():
        rows.append(
            {
                "name": c["name"],
                "linkedin_url": c["linkedin_url"],
                "linkedin_id": c["linkedin_id"],
                "headline": c["headline"],
                "company": c["company"],
                "email": c["email"],
                "connection_date": c["connection_date"] or "",
                "first_message_date": c["first_message_date"] or "",
                "last_message_date": c["last_message_date"] or "",
                "messages_sent": c["messages_sent"],
                "messages_received": c["messages_received"],
                "total_messages": c["messages_sent"] + c["messages_received"],
                "has_connection_note": c["has_connection_note"],
                "categories": ", ".join(sorted(c["categories"])),
                "source": ", ".join(sorted(c["sources"])),
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("total_messages", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    elapsed = time.time() - t0
    log.info(
        f"Contacts: {len(df)} unique, "
        f"{df['messages_sent'].sum()} sent, {df['messages_received'].sum()} received, "
        f"{df['has_connection_note'].sum()} with connection notes, "
        f"built in {elapsed:.1f}s"
    )
    return df





def build_interactions(
    threads_complete: list[dict],
    sales_nav: list[dict],
    export_invitations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ""









    log.info("Phase 3: Building interactions-linkedin.parquet...")
    t0 = time.time()


    seen = set()
    rows = []


    for conv in threads_complete:
        participants = conv.get("participants", [])
        if not participants:
            continue

        p = participants[0]
        name = p.get("name", "")
        url = p.get("profileUrl", "")
        lid = extract_linkedin_id(url) or normalize_name(name)

        for msg in conv.get("messages", []):
            ts = msg.get("deliveredAt", "")
            is_sent = msg.get("senderIsMe", False)
            body = msg.get("body", "")

            dedup_key = (lid, ts, is_sent)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)


            msg_type = "sent" if is_sent else "received"

            rows.append(
                {
                    "from_name": OWNER_NOME if is_sent else name,
                    "to_name": name if is_sent else OWNER_NOME,
                    "timestamp": ts,
                    "date": parse_iso_date(ts) or "",
                    "message_type": msg_type,
                    "linkedin_url": url,
                    "linkedin_id": lid,
                    "message_text": body[:5000] if body else "",
                    "body_length": len(body) if body else 0,
                    "has_subject": bool(msg.get("subject")),
                    "source": "threads-complete",
                }
            )


    for conv in sales_nav:
        participants = conv.get("participants", [])
        if not participants:
            continue

        p = participants[0]
        name = p.get("name", "")
        entity_urn = p.get("entityUrn", "")
        sn_id = extract_linkedin_id(entity_urn) or normalize_name(name)

        for msg in conv.get("messages", []):
            ts = msg.get("deliveredAt", "")
            is_sent = msg.get("senderIsMe", False)
            body = msg.get("body", "")
            msg_li_type = msg.get("type", "MESSAGE")

            dedup_key = (sn_id, ts, is_sent)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)


            if msg_li_type == "INVITATION" and is_sent:
                msg_type = "connection_note"
            elif is_sent:
                msg_type = "sent"
            else:
                msg_type = "received"

            rows.append(
                {
                    "from_name": OWNER_NOME if is_sent else name,
                    "to_name": name if is_sent else OWNER_NOME,
                    "timestamp": ts,
                    "date": parse_iso_date(ts) or "",
                    "message_type": msg_type,
                    "linkedin_url": "",
                    "linkedin_id": sn_id,
                    "message_text": body[:5000] if body else "",
                    "body_length": len(body) if body else 0,
                    "has_subject": bool(msg.get("subject")),
                    "source": "sales-navigator",
                }
            )


    inv_added = 0
    if export_invitations is not None and len(export_invitations) > 0:
        for _, row in export_invitations.iterrows():
            name = str(row.get("person_name", "")).strip()
            url = str(row.get("person_url", "")).strip()
            lid = extract_linkedin_id(url) or normalize_name(name)
            direction = str(row.get("direction", "")).strip()
            is_sent = direction == "OUTGOING"
            ts = str(row.get("sent_at", "")).strip()
            msg = str(row.get("message", "")).strip() if pd.notna(row.get("message")) else ""

            dedup_key = (lid, ts, is_sent)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            rows.append(
                {
                    "from_name": OWNER_NOME if is_sent else name,
                    "to_name": name if is_sent else OWNER_NOME,
                    "timestamp": ts,
                    "date": parse_iso_date(ts) or "",
                    "message_type": "invitation",
                    "linkedin_url": url,
                    "linkedin_id": lid,
                    "message_text": msg[:5000] if msg else "",
                    "body_length": len(msg) if msg else 0,
                    "has_subject": False,
                    "source": "export-invitations",
                }
            )
            inv_added += 1

        log.info(f"  Export invitations: {inv_added} new interactions added")


    # A data export with connections only (no conversations, no invitations) gives no rows:
    # keep the columns, so the file is still written and readable.
    df = pd.DataFrame(
        rows,
        columns=[
            "from_name",
            "to_name",
            "timestamp",
            "date",
            "message_type",
            "linkedin_url",
            "linkedin_id",
            "message_text",
            "body_length",
            "has_subject",
            "source",
        ],
    )
    df.sort_values("timestamp", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    elapsed = time.time() - t0
    type_counts = df["message_type"].value_counts().to_dict() if len(df) > 0 else {}
    log.info(
        f"Interactions: {len(df)} messages "
        f"({type_counts.get('sent', 0)} sent, "
        f"{type_counts.get('received', 0)} received, "
        f"{type_counts.get('connection_note', 0)} connection notes, "
        f"{type_counts.get('invitation', 0)} invitations), "
        f"built in {elapsed:.1f}s"
    )
    return df





def build_summary(
    contacts_df: pd.DataFrame,
    interactions_df: pd.DataFrame,
    threads_complete: list[dict],
    sales_nav: list[dict],
) -> dict:
    ""
    log.info("Phase 5: Building _linkedin_summary.json...")


    msg_types = (
        interactions_df["message_type"].value_counts().to_dict() if len(interactions_df) > 0 else {}
    )


    dates = interactions_df[interactions_df["date"] != ""]["date"]
    date_range = {
        "min": str(dates.min()) if len(dates) > 0 else "",
        "max": str(dates.max()) if len(dates) > 0 else "",
    }


    top_contacts = (
        contacts_df.head(20)[
            [
                "name",
                "linkedin_url",
                "messages_sent",
                "messages_received",
                "total_messages",
                "has_connection_note",
                "last_message_date",
            ]
        ].to_dict("records")
        if len(contacts_df) > 0
        else []
    )


    conn_notes = (
        contacts_df[contacts_df["has_connection_note"]].shape[0] if len(contacts_df) > 0 else 0
    )


    source_counts = Counter()
    for s in contacts_df["source"]:
        for part in s.split(", "):
            source_counts[part] += 1


    category_counts = Counter()
    for cats in contacts_df["categories"]:
        for cat in cats.split(", "):
            if cat:
                category_counts[cat] += 1

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "linkedin-enrich-v1",
        "totals": {
            "contacts": len(contacts_df),
            "interactions": len(interactions_df),
            "threads_complete_conversations": len(threads_complete),
            "sales_nav_conversations": len(sales_nav),
        },
        "messages": {
            "total": len(interactions_df),
            "sent": msg_types.get("sent", 0),
            "received": msg_types.get("received", 0),
            "connection_notes": msg_types.get("connection_note", 0),
        },
        "date_range": date_range,
        "contacts": {
            "total_unique": len(contacts_df),
            "with_connection_notes": conn_notes,
            "with_linkedin_url": len(contacts_df[contacts_df["linkedin_url"] != ""])
            if len(contacts_df) > 0
            else 0,
            "with_headline": len(contacts_df[contacts_df["headline"] != ""])
            if len(contacts_df) > 0
            else 0,
            "with_company": len(contacts_df[contacts_df["company"] != ""])
            if len(contacts_df) > 0
            else 0,
            "messages_sent_total": int(contacts_df["messages_sent"].sum())
            if len(contacts_df) > 0
            else 0,
            "messages_received_total": int(contacts_df["messages_received"].sum())
            if len(contacts_df) > 0
            else 0,
        },
        "source_distribution": dict(source_counts.most_common()),
        "category_distribution": dict(category_counts.most_common()),
        "top_contacts": top_contacts,
    }

    return summary




STEP_NAMES = ["contacts", "interactions", "summary"]


def _li_inputs() -> list[Path]:
    """The folders this step reads: the conversation files and the imported data export."""
    return list(dict.fromkeys([RAW_LINKEDIN_DIR, LINKEDIN_RAW_DIR]))


def main():
    parser = argparse.ArgumentParser(description="LinkedIn enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--step", default=None, choices=STEP_NAMES, help="Run single step (default: all)"
    )
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("li-l1", _li_inputs()):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("li-l1")
            return


    if not any(d.exists() for d in _li_inputs()):
        # First run: nothing imported or downloaded yet. Nothing to do, not an error.
        log.info(f"LinkedIn: nothing imported yet in {LINKEDIN_RAW_DIR}, nothing to do")
        return

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    log.info("=" * 60)
    log.info("LINKEDIN ENRICHMENT PIPELINE — SBK L1")
    log.info("=" * 60)

    threads_complete = parse_threads_complete()
    sales_nav = parse_sales_navigator()
    sent_notes = parse_sent_notes()
    export_connections = load_export_connections()
    export_invitations = load_export_invitations()

    if not threads_complete and not sales_nav:
        if export_connections is None and export_invitations is None:
            log.info(
                "LinkedIn: no conversations and no imported data export yet "
                "(tools/linkedin/li-l0-import-export.py), nothing to do"
            )
            return
        log.info("LinkedIn: no conversation files, building from your data export only")


    profile_enrichment = build_profile_enrichment_map()


    steps_to_run = [args.step] if args.step else STEP_NAMES

    contacts_df = None
    interactions_df = None


    if "contacts" in steps_to_run:
        contacts_df = build_contacts(
            threads_complete,
            sales_nav,
            sent_notes,
            profile_enrichment,
            export_connections,
            export_invitations,
        )
        if not args.dry_run:
            out = PROCESSED_DIR / "contacts-linkedin.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"  Saved -> {out}")


    if "interactions" in steps_to_run:
        interactions_df = build_interactions(threads_complete, sales_nav, export_invitations)
        if not args.dry_run:
            out = PROCESSED_DIR / "interactions-linkedin.parquet"
            safe_write_parquet(interactions_df, out, index=False)
            log.info(f"  Saved -> {out}")


    if "summary" in steps_to_run:
        if contacts_df is None:
            contacts_df = build_contacts(
                threads_complete,
                sales_nav,
                sent_notes,
                profile_enrichment,
                export_connections,
                export_invitations,
            )
        if interactions_df is None:
            interactions_df = build_interactions(
                threads_complete,
                sales_nav,
                export_invitations,
            )

        summary = build_summary(
            contacts_df,
            interactions_df,
            threads_complete,
            sales_nav,
        )

        if args.dry_run:
            log.info("\n=== DRY RUN — Summary ===")
            log.info(json.dumps(summary, indent=2))
        else:
            out = PROCESSED_DIR / "_linkedin_summary.json"
            out.write_text(json.dumps(summary, indent=2, default=str))
            log.info(f"  Saved -> {out}")


    log.info("\n" + "=" * 60)
    log.info("LINKEDIN ENRICHMENT COMPLETE")
    log.info("=" * 60)
    if contacts_df is not None:
        log.info(f"  Contacts:     {len(contacts_df)}")
    if interactions_df is not None:
        log.info(f"  Interactions: {len(interactions_df)}")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")
        from sbk_config import save_input_checkpoint

        save_input_checkpoint("li-l1", _li_inputs())
        mark_last_run("li-l1")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-linkedin-enrich", source="li-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
