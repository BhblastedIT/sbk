#!/usr/bin/env python3
"""Notion L1: from the Notion download, the database schemas, the people and companies in your databases, the task
timeline, the page text and the mentions, as parquet files with a summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import DATA_ROOT, safe_write_json, safe_write_parquet, user_cfg



DATA_DIR = DATA_ROOT / "notion"
DB_DIR = DATA_DIR / "databases"
PAGES_DIR = DATA_DIR / "pages"
BLOCKS_DIR = DATA_DIR / "blocks"
PROCESSED_DIR = DATA_DIR / "processed"


SKIP_DB_IDS = {
    "00000000-0000-0000-0000-000000000000",
}


TASK_DB_KEYWORDS = {"task", "to do", "todo"}


STATUS_NORMALIZE: dict[str, str] = {
    "not started": "not_started",
    "not yet started": "not_started",
    "to do": "not_started",
    "todo": "not_started",
    "backlog": "not_started",
    "in progress": "in_progress",
    "in corso": "in_progress",
    "doing": "in_progress",
    "started": "in_progress",
    "done": "done",
    "completed": "done",
    "completato": "done",
    "finished": "done",
    "closed": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "annullato": "cancelled",
    "blocked": "blocked",
    "on hold": "on_hold",
    "in attesa": "on_hold",
    "waiting": "on_hold",
    "review": "in_review",
    "in review": "in_review",
}


PERSON_PROPERTY_TYPES = {"people", "person"}
def _env_set(name: str) -> set[str]:
    # extra values loaded from user config (comma-separated, case-insensitive)
    return {s.strip().lower() for s in os.environ.get(name, "").split(",") if s.strip()}


# Generic Notion person-property names; extend via user config.
PERSON_PROPERTY_NAMES = {
    "assignee",
    "assign",
    "person",
    "owner",
    "delegate",
    "added by",
    "collaborators",
    "project manager",
} | _env_set("SBK_NOTION_PERSON_PROPERTIES")


PERSON_NAME_PROPERTIES = {
    "name",
    "nome",
    "project manager",
} | _env_set("SBK_NOTION_PERSON_NAME_PROPERTIES")


# Notion database titles to classify, loaded from user config; empty default.
CONTACT_DB_TITLES = _env_set("SBK_NOTION_CONTACT_DB_TITLES")


COMPANY_DB_TITLES = _env_set("SBK_NOTION_COMPANY_DB_TITLES")

log = logging.getLogger("notion-enrich")





def load_json(path: Path) -> dict | None:
    ""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot parse {path.name}: {e}")
        return None


def extract_title(title_list: list) -> str:
    ""
    if not title_list:
        return ""
    return "".join(t.get("plain_text", "") for t in title_list).strip()


def extract_rich_text(rt_list: list) -> str:
    ""
    if not rt_list:
        return ""
    return "".join(t.get("plain_text", "") for t in rt_list).strip()


def extract_property_value(prop: dict) -> Any:
    ""



    ptype = prop.get("type", "")

    if ptype == "title":
        return extract_title(prop.get("title", []))
    elif ptype == "rich_text":
        return extract_rich_text(prop.get("rich_text", []))
    elif ptype == "number":
        return prop.get("number")
    elif ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else None
    elif ptype == "multi_select":
        return [s.get("name", "") for s in prop.get("multi_select", [])]
    elif ptype == "status":
        st = prop.get("status")
        return st.get("name", "") if st else None
    elif ptype == "date":
        d = prop.get("date")
        if d:
            return d.get("start")
        return None
    elif ptype == "checkbox":
        return prop.get("checkbox", False)
    elif ptype == "url":
        return prop.get("url")
    elif ptype == "email":
        return prop.get("email")
    elif ptype == "phone_number":
        return prop.get("phone_number")
    elif ptype == "people":
        people = prop.get("people", [])
        return [p.get("name", p.get("id", "")) for p in people]
    elif ptype == "created_time":
        return prop.get("created_time")
    elif ptype == "last_edited_time":
        return prop.get("last_edited_time")
    elif ptype == "created_by":
        cb = prop.get("created_by", {})
        return cb.get("name", cb.get("id", ""))
    elif ptype == "last_edited_by":
        eb = prop.get("last_edited_by", {})
        return eb.get("name", eb.get("id", ""))
    elif ptype == "relation":
        return [r.get("id", "") for r in prop.get("relation", [])]
    elif ptype == "rollup":
        rollup = prop.get("rollup", {})
        rtype = rollup.get("type", "")
        if rtype == "number":
            return rollup.get("number")
        elif rtype == "array":
            return len(rollup.get("array", []))
        return None
    elif ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type", "")
        return formula.get(ftype)
    elif ptype == "files":
        files = prop.get("files", [])
        return [f.get("name", "") for f in files]
    elif ptype == "unique_id":
        uid = prop.get("unique_id", {})
        prefix = uid.get("prefix", "")
        number = uid.get("number", "")
        return f"{prefix}-{number}" if prefix else str(number)
    else:
        return None


def get_db_title(schema: dict) -> str:
    ""
    title_arr = schema.get("title", [])
    return extract_title(title_arr)


def is_task_db(title: str) -> bool:
    ""
    t = title.lower().strip()
    for kw in TASK_DB_KEYWORDS:
        if kw in t:
            return True
    return False


def parse_iso_date(dt_str: str | None) -> str | None:
    ""
    if not dt_str:
        return None
    try:

        if "T" in dt_str:
            return dt_str[:10]
        return dt_str[:10]
    except Exception:
        return None





def build_database_schemas() -> list[dict]:
    ""



    log.info("Phase 1: Building database schemas...")
    t0 = time.time()

    schemas = []
    db_files = sorted(DB_DIR.glob("*.json"))

    for db_file in db_files:
        db_id = db_file.stem
        if db_id in SKIP_DB_IDS:
            log.info(f"  SKIP {db_id} (sensitive)")
            continue

        data = load_json(db_file)
        if data is None:
            continue

        schema = data.get("schema", {})
        title = get_db_title(schema)
        row_count = data.get("row_count", 0)


        props = schema.get("properties", {})
        properties_list = []
        for pname, pdata in props.items():
            properties_list.append(
                {
                    "name": pname,
                    "type": pdata.get("type", "unknown"),
                }
            )

        created = parse_iso_date(schema.get("created_time"))
        last_edited = parse_iso_date(schema.get("last_edited_time"))

        schemas.append(
            {
                "db_id": db_id,
                "db_title": title,
                "row_count": row_count,
                "properties": json.dumps(properties_list, ensure_ascii=False),
                "property_count": len(properties_list),
                "created": created,
                "last_edited": last_edited,
            }
        )

    elapsed = time.time() - t0
    log.info(f"  {len(schemas)} databases parsed in {elapsed:.1f}s")
    return schemas





def extract_entities_from_databases() -> list[dict]:
    ""


    log.info("Phase 2: Extracting entities from databases...")
    t0 = time.time()

    entities = []
    entity_tracker = defaultdict(
        lambda: {
            "mention_count": 0,
            "first_seen": None,
            "last_seen": None,
            "sources": set(),
            "contexts": [],
        }
    )

    db_files = sorted(DB_DIR.glob("*.json"))

    for db_file in db_files:
        db_id = db_file.stem
        if db_id in SKIP_DB_IDS:
            continue

        data = load_json(db_file)
        if data is None:
            continue

        schema = data.get("schema", {})
        db_title = get_db_title(schema)
        db_title_lower = db_title.lower().strip()
        rows = data.get("rows", [])


        is_contact_db = db_title_lower in CONTACT_DB_TITLES
        is_company_db = db_title_lower in COMPANY_DB_TITLES


        prop_schema = schema.get("properties", {})

        for row in rows:
            props = row.get("properties", {})
            created = parse_iso_date(row.get("created_time"))
            last_edited = parse_iso_date(row.get("last_edited_time"))


            row_name = ""
            for pname, pdata in props.items():
                if pdata.get("type") == "title":
                    row_name = extract_title(pdata.get("title", []))
                    break

            if not row_name:
                continue


            if is_contact_db:
                _register_entity(
                    entity_tracker,
                    row_name,
                    "person",
                    db_title,
                    None,
                    created,
                    last_edited,
                    context=_build_contact_context(props),
                )
            elif is_company_db:
                etype = "brand" if "brand" in db_title_lower else "company"
                _register_entity(
                    entity_tracker,
                    row_name,
                    etype,
                    db_title,
                    None,
                    created,
                    last_edited,
                    context=_build_company_context(props),
                )


            for pname, pdata in props.items():
                ptype = pdata.get("type", "")
                pname_lower = pname.lower().strip()

                if ptype == "people":
                    people = pdata.get("people", [])
                    for person in people:
                        person_name = person.get("name", "")
                        if person_name:
                            _register_entity(
                                entity_tracker,
                                person_name,
                                "person",
                                db_title,
                                None,
                                created,
                                last_edited,
                                context=f"assigned/mentioned in: {row_name[:80]}",
                            )


                elif ptype == "rich_text" and pname_lower in {"delegate", "referente / note"}:
                    text = extract_rich_text(pdata.get("rich_text", []))
                    if text and len(text) < 60 and not any(c in text for c in ".@/"):

                        _register_entity(
                            entity_tracker,
                            text,
                            "person",
                            db_title,
                            None,
                            created,
                            last_edited,
                            context=f"{pname} for: {row_name[:80]}",
                        )


            for pname, pdata in props.items():
                if pdata.get("type") == "multi_select" and pname.lower() in {
                    "progetto",
                    "project",
                    "tags",
                }:
                    for sel in pdata.get("multi_select", []):
                        proj_name = sel.get("name", "")
                        if proj_name and len(proj_name) > 2:
                            _register_entity(
                                entity_tracker,
                                proj_name,
                                "project",
                                db_title,
                                None,
                                created,
                                last_edited,
                                context=f"tagged on: {row_name[:80]}",
                            )


    log.info("  Scanning standalone pages for entities...")
    page_files = sorted(PAGES_DIR.glob("*.json"))
    for pf in page_files:
        page = load_json(pf)
        if page is None:
            continue
        page_title = ""
        for pname, pdata in page.get("properties", {}).items():
            if pdata.get("type") == "title":
                page_title = extract_title(pdata.get("title", []))
                break
        if not page_title:
            continue

        created = parse_iso_date(page.get("created_time"))
        last_edited = parse_iso_date(page.get("last_edited_time"))


        if len(page_title) > 3:
            _register_entity(
                entity_tracker,
                page_title,
                "page",
                None,
                pf.stem,
                created,
                last_edited,
                context="standalone page",
            )


    log.info("  Scanning blocks for person mentions...")
    _extract_mentions_from_blocks(entity_tracker)


    final_entities = []
    # Text that marks template pages, e.g. a placeholder domain ("notion.exclude_context_terms"
    # in sbk.config.json). Entities whose context contains one are dropped. Empty by default.
    exclude_terms = [
        str(t).strip().lower() for t in (user_cfg("notion.exclude_context_terms", []) or []) if str(t).strip()
    ]
    template_dropped = 0
    for (name, etype), info in entity_tracker.items():

        context_str = "; ".join(info["contexts"][:5])
        if exclude_terms and any(t in context_str.lower() for t in exclude_terms):
            template_dropped += 1
            continue

        final_entities.append(
            {
                "entity_name": name,
                "entity_type": etype,
                "source_db": "; ".join(
                    sorted(s for s in info["sources"] if s and not s.startswith("page:"))
                ),
                "source_page": "; ".join(
                    sorted(
                        s.replace("page:", "")
                        for s in info["sources"]
                        if s and s.startswith("page:")
                    )
                ),
                "first_seen": info["first_seen"],
                "last_seen": info["last_seen"],
                "mention_count": info["mention_count"],
                "context": context_str,
            }
        )

    if template_dropped:
        log.info(f"  Filtered out {template_dropped} template entities (notion.exclude_context_terms)")

    elapsed = time.time() - t0
    log.info(f"  {len(final_entities)} entities extracted in {elapsed:.1f}s")
    return final_entities


def _register_entity(
    tracker: dict,
    name: str,
    entity_type: str,
    source_db: str | None,
    source_page: str | None,
    created: str | None,
    last_edited: str | None,
    context: str = "",
):
    ""
    name = name.strip()
    if not name or len(name) < 2:
        return

    key = (name, entity_type)
    info = tracker[key]
    info["mention_count"] += 1

    source = source_db if source_db else f"page:{source_page}" if source_page else ""
    if source:
        info["sources"].add(source)

    if created:
        if info["first_seen"] is None or created < info["first_seen"]:
            info["first_seen"] = created
    if last_edited:
        if info["last_seen"] is None or last_edited > info["last_seen"]:
            info["last_seen"] = last_edited

    if context and context not in info["contexts"]:
        info["contexts"].append(context)


def _build_contact_context(props: dict) -> str:
    ""
    parts = []
    for pname in ("Role", "Position", "Job Title", "Company", "Team", "Department"):
        if pname in props:
            val = extract_property_value(props[pname])
            if val and val not in ([], None, False, ""):
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                parts.append(f"{pname}: {val}")

    for pname in ("Email", "Email Address"):
        if pname in props:
            val = extract_property_value(props[pname])
            if val:
                parts.append(f"email: {val}")
    return "; ".join(parts) if parts else ""


def _build_company_context(props: dict) -> str:
    ""
    parts = []
    for pname in ("Niche", "Business Type", "City", "Mother Company", "Status"):
        if pname in props:
            val = extract_property_value(props[pname])
            if val and val not in ([], None, False, ""):
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                parts.append(f"{pname}: {val}")

    for pname in ("URL", "website", "Website"):
        if pname in props:
            val = extract_property_value(props[pname])
            if val:
                parts.append(f"url: {val}")
    return "; ".join(parts) if parts else ""


def _extract_mentions_from_blocks(tracker: dict):
    ""



    block_files = sorted(BLOCKS_DIR.glob("*.json"))
    mention_count = 0

    for bf in block_files:
        data = load_json(bf)
        if data is None:
            continue

        blocks = data.get("blocks", [])
        page_title = data.get("title", "")

        for block in blocks:
            btype = block.get("type", "")
            block_data = block.get(btype, {})
            rich_text = block_data.get("rich_text", [])

            for rt in rich_text:

                if rt.get("type") == "mention":
                    mention = rt.get("mention", {})
                    if mention.get("type") == "user":
                        user = mention.get("user", {})
                        user_name = user.get("name", "")
                        if user_name:
                            created = parse_iso_date(block.get("created_time"))
                            last_edited = parse_iso_date(block.get("last_edited_time"))
                            _register_entity(
                                tracker,
                                user_name,
                                "person",
                                None,
                                bf.stem,
                                created,
                                last_edited,
                                context=f"@mentioned in: {page_title[:60]}",
                            )
                            mention_count += 1

    log.info(f"    {mention_count} @mentions found in blocks")





def extract_tasks_timeline() -> list[dict]:
    ""


    log.info("Phase 3: Extracting tasks timeline...")
    t0 = time.time()

    tasks = []
    db_files = sorted(DB_DIR.glob("*.json"))

    for db_file in db_files:
        db_id = db_file.stem
        if db_id in SKIP_DB_IDS:
            continue

        data = load_json(db_file)
        if data is None:
            continue

        schema = data.get("schema", {})
        db_title = get_db_title(schema)


        if not is_task_db(db_title):

            prop_names = {p.lower() for p in schema.get("properties", {}).keys()}
            has_status = any(k in prop_names for k in {"status", "stato"})
            has_task_name = any(k in prop_names for k in {"task name", "task", "name"})
            has_due = any(k in prop_names for k in {"due", "due date", "deadline", "scadenza"})
            if not (has_status and has_task_name and has_due):

                if "task" not in db_title.lower() and "tracker" not in db_title.lower():
                    continue

        rows = data.get("rows", [])
        for row in rows:
            props = row.get("properties", {})
            task = _extract_task_record(props, row, db_title)
            if task:
                tasks.append(task)

    elapsed = time.time() - t0
    log.info(f"  {len(tasks)} tasks extracted in {elapsed:.1f}s")
    return tasks


def _extract_task_record(props: dict, row: dict, db_name: str) -> dict | None:
    ""

    title = ""
    for pname, pdata in props.items():
        if pdata.get("type") == "title":
            title = extract_title(pdata.get("title", []))
            break

    if not title:
        return None


    status = None
    status_raw = None
    for pname in ("Status", "Stato", "status"):
        if pname in props:
            status_raw = extract_property_value(props[pname])
            break
    if status_raw and isinstance(status_raw, str):
        status = STATUS_NORMALIZE.get(
            status_raw.strip().lower(), status_raw.strip().lower().replace(" ", "_")
        )
    elif status_raw:
        status = status_raw


    assignee = None
    for pname in ("Assignee", "Assign", "Person", "Owner", "Project Manager"):
        if pname in props:
            val = extract_property_value(props[pname])
            if isinstance(val, list) and val:
                assignee = ", ".join(str(v) for v in val if v)
            elif val:
                assignee = str(val)
            if assignee:
                break


    if not assignee:
        if "Delegate" in props:
            assignee = extract_property_value(props["Delegate"])


    due_date = None
    for pname in ("Due", "Due date", "Due Date", "Deadline", "Scadenza"):
        if pname in props:
            due_date = extract_property_value(props[pname])
            if due_date:
                due_date = parse_iso_date(due_date)
                break


    priority = None
    for pname in ("Priority", "priority"):
        if pname in props:
            priority = extract_property_value(props[pname])
            break


    completed_date = None
    for pname in ("Completed on", "Completed"):
        if pname in props:
            completed_date = extract_property_value(props[pname])
            if completed_date:
                completed_date = parse_iso_date(completed_date)
                break


    created = parse_iso_date(row.get("created_time"))

    return {
        "task_id": row.get("id", ""),
        "title": title,
        "status": status,
        "assignee": assignee,
        "created": created,
        "due_date": due_date,
        "completed_date": completed_date,
        "db_name": db_name,
        "priority": priority,
    }





def extract_brands_database() -> list[dict]:
    ""


    log.info("Phase 4: Extracting brands database...")
    t0 = time.time()

    brands = []
    db_files = sorted(DB_DIR.glob("*.json"))


    target_db = None
    for db_file in db_files:
        data = load_json(db_file)
        if data is None:
            continue
        schema = data.get("schema", {})
        title = get_db_title(schema)
        if title.lower().strip() == "lista brand":
            target_db = data
            break

    if target_db is None:
        log.warning("  'Lista brand' database not found!")
        return []

    rows = target_db.get("rows", [])
    for row in rows:
        props = row.get("properties", {})
        brand = {
            "brand_name": "",
            "status": None,
            "email": None,
            "url": None,
            "note": None,
            "date": None,
            "niche": None,
            "created": parse_iso_date(row.get("created_time")),
            "last_edited": parse_iso_date(row.get("last_edited_time")),
            "notion_id": row.get("id", ""),
        }

        for pname, pdata in props.items():
            pname_lower = pname.lower().strip()
            val = extract_property_value(pdata)

            if pdata.get("type") == "title":
                brand["brand_name"] = val or ""
            elif pname_lower == "status":
                brand["status"] = val
            elif pname_lower == "email":
                brand["email"] = val
            elif pname_lower == "url":
                brand["url"] = val
            elif pname_lower == "note":
                brand["note"] = val
            elif pname_lower == "date":
                brand["date"] = parse_iso_date(val) if val else None
            elif pname_lower == "niche":
                brand["niche"] = ", ".join(val) if isinstance(val, list) else val

        if brand["brand_name"]:
            brands.append(brand)

    elapsed = time.time() - t0
    log.info(f"  {len(brands)} brands extracted in {elapsed:.1f}s")
    return brands





_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "callout",
    "quote",
    "code",
}


def _block_to_text(block: dict) -> str:
    ""
    btype = block.get("type", "")
    if btype not in _TEXT_BLOCK_TYPES:
        return ""

    data = block.get(btype, {})
    rich = data.get("rich_text", [])
    text = extract_rich_text(rich)

    if btype == "heading_1":
        return f"# {text}"
    if btype == "heading_2":
        return f"## {text}"
    if btype == "heading_3":
        return f"### {text}"
    if btype in ("bulleted_list_item", "toggle"):
        return f"- {text}"
    if btype == "numbered_list_item":
        return f"1. {text}"
    if btype == "to_do":
        checked = data.get("checked", False)
        mark = "[x]" if checked else "[ ]"
        return f"- {mark} {text}"
    if btype == "quote":
        return f"> {text}"
    if btype == "callout":
        icon = block.get("callout", {}).get("icon", {})
        emoji = icon.get("emoji", "") if icon else ""
        prefix = f"{emoji} " if emoji else ""
        return f"{prefix}{text}"
    if btype == "code":
        lang = data.get("language", "")
        return f"```{lang}\n{text}\n```"

    return text


def build_pages_text() -> list[dict]:
    ""
    t0 = time.time()
    log.info("Phase 5: Extracting page text from blocks...")

    if not BLOCKS_DIR.exists():
        log.warning(f"  Blocks directory not found: {BLOCKS_DIR}")
        return []

    max_chars = 30_000
    results = []

    for block_file in sorted(BLOCKS_DIR.glob("*.json")):
        page_id = block_file.stem
        data = load_json(block_file)
        if not data:
            continue

        blocks = data.get("blocks", data.get("results", []))
        if isinstance(data, list):
            blocks = data
        if not blocks:
            continue

        lines = []
        for b in blocks:
            line = _block_to_text(b)
            if line:
                lines.append(line)

        page_text = "\n".join(lines)
        if not page_text.strip():
            continue


        if len(page_text) > max_chars:
            page_text = page_text[:max_chars] + "\n[TRUNCATED]"


        title = data.get("title", "") if isinstance(data, dict) else ""

        results.append(
            {
                "page_id": page_id,
                "title": title,
                "block_count": len(blocks),
                "char_count": len(page_text),
                "page_text": page_text,
                "downloaded_at": datetime.now(UTC).isoformat(),
            }
        )

    elapsed = time.time() - t0
    non_empty = len(results)
    total_chars = sum(r["char_count"] for r in results)
    avg_chars = round(total_chars / non_empty) if non_empty else 0
    log.info(
        f"  {non_empty} pages with text, {total_chars:,} total chars, avg {avg_chars:,} char/page in {elapsed:.1f}s"
    )
    return results





def build_summary(
    schemas: list[dict],
    entities: list[dict],
    tasks: list[dict],
    brands: list[dict],
    page_count: int,
    block_count: int,
    elapsed: float,
) -> dict:
    ""

    entity_types = Counter(e["entity_type"] for e in entities)


    task_statuses = Counter(t["status"] for t in tasks if t.get("status"))


    all_dates = []
    for s in schemas:
        if s.get("created"):
            all_dates.append(s["created"])
        if s.get("last_edited"):
            all_dates.append(s["last_edited"])
    for t in tasks:
        if t.get("created"):
            all_dates.append(t["created"])
    for e in entities:
        if e.get("first_seen"):
            all_dates.append(e["first_seen"])
        if e.get("last_seen"):
            all_dates.append(e["last_seen"])

    date_range = {}
    if all_dates:
        all_dates_sorted = sorted(d for d in all_dates if d)
        if all_dates_sorted:
            date_range = {
                "earliest": all_dates_sorted[0],
                "latest": all_dates_sorted[-1],
            }


    brand_statuses = Counter(b["status"] for b in brands if b.get("status"))


    top_dbs = sorted(schemas, key=lambda x: x["row_count"], reverse=True)[:10]

    summary = {
        "databases_processed": len(schemas),
        "pages_scanned": page_count,
        "blocks_scanned": block_count,
        "total_rows": sum(s["row_count"] for s in schemas),
        "entities_extracted": len(entities),
        "entity_types": dict(entity_types),
        "tasks_extracted": len(tasks),
        "task_statuses": dict(task_statuses),
        "brands_extracted": len(brands),
        "brand_statuses": dict(brand_statuses),
        "timeline_range": date_range,
        "top_databases": [{"title": d["db_title"], "rows": d["row_count"]} for d in top_dbs],
        "elapsed_seconds": round(elapsed, 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }

    return summary





STEPS = ["schema", "entities", "tasks", "brands", "text", "summary"]


def run_pipeline(dry_run: bool = False, step: str | None = None):
    ""
    t0 = time.time()


    if not DB_DIR.exists():
        log.error(f"Database directory not found: {DB_DIR}")
        sys.exit(1)

    run_all = step is None
    steps_to_run = STEPS if run_all else [step]


    page_count = len(list(PAGES_DIR.glob("*.json"))) if PAGES_DIR.exists() else 0
    block_count = len(list(BLOCKS_DIR.glob("*.json"))) if BLOCKS_DIR.exists() else 0

    log.info("Notion Enrichment Pipeline")
    log.info(f"  Databases: {len(list(DB_DIR.glob('*.json')))} files")
    log.info(f"  Pages: {page_count} files")
    log.info(f"  Blocks: {block_count} files")
    log.info(f"  Dry run: {dry_run}")
    log.info(f"  Steps: {', '.join(steps_to_run)}")
    log.info("")

    schemas = []
    entities = []
    tasks = []
    brands = []


    if "schema" in steps_to_run or run_all:
        schemas = build_database_schemas()
        if not dry_run:
            _save_parquet(schemas, PROCESSED_DIR / "databases-schema.parquet", "databases-schema")


    if "entities" in steps_to_run or run_all:
        entities = extract_entities_from_databases()
        if not dry_run:
            _save_parquet(entities, PROCESSED_DIR / "entities-notion.parquet", "entities-notion")


    if "tasks" in steps_to_run or run_all:
        tasks = extract_tasks_timeline()
        if not dry_run:
            _save_parquet(tasks, PROCESSED_DIR / "tasks-timeline.parquet", "tasks-timeline")


    if "brands" in steps_to_run or run_all:
        brands = extract_brands_database()
        if not dry_run:
            _save_parquet(brands, PROCESSED_DIR / "brands-database.parquet", "brands-database")


    pages_text = []
    if "text" in steps_to_run or run_all:
        pages_text = build_pages_text()
        if not dry_run:
            _save_parquet(pages_text, PROCESSED_DIR / "pages-text.parquet", "pages-text")


    elapsed = time.time() - t0
    if "summary" in steps_to_run or run_all:
        summary = build_summary(schemas, entities, tasks, brands, page_count, block_count, elapsed)
        log.info("")
        log.info("=== Summary ===")
        for k, v in summary.items():
            if isinstance(v, dict):
                log.info(f"  {k}:")
                for kk, vv in v.items():
                    log.info(f"    {kk}: {vv}")
            elif isinstance(v, list):
                log.info(f"  {k}:")
                for item in v:
                    log.info(f"    {item}")
            else:
                log.info(f"  {k}: {v}")

        if not dry_run:
            summary_path = PROCESSED_DIR / "_notion_summary.json"
            safe_write_json(summary_path, summary)
            log.info(f"\n  Summary saved to {summary_path}")

    if not dry_run:
        from sbk_config import mark_last_run, save_input_checkpoint

        save_input_checkpoint("notion-l1", [DB_DIR, PAGES_DIR, BLOCKS_DIR])
        mark_last_run("notion-l1")

    total_elapsed = time.time() - t0
    log.info(f"\nPipeline completed in {total_elapsed:.1f}s")


def _save_parquet(records: list[dict], path: Path, label: str):
    ""
    path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        log.warning(f"  No records for {label}, skipping parquet write")
        return

    df = pd.DataFrame(records)
    safe_write_parquet(df, path, index=False, engine="pyarrow")
    log.info(f"  Saved {label}: {len(df)} rows -> {path}")
    log.info(f"    Columns: {list(df.columns)}")





def main():
    parser = argparse.ArgumentParser(description="Notion Enrichment Pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing files")
    parser.add_argument(
        "--step",
        choices=STEPS,
        default=None,
        help="Run only a specific step",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("notion-l1", [DB_DIR, PAGES_DIR, BLOCKS_DIR]):
            log.info("Incremental: inputs unchanged — skipping")
            from sbk_config import mark_last_run

            mark_last_run("notion-l1")
            return

    run_pipeline(dry_run=args.dry_run, step=args.step)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-notion-enrich", source="notion-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
