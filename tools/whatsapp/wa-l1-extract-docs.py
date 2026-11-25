#!/usr/bin/env python3
"""WhatsApp extra: extract the text of documents sent in your chats (PDF, DOCX, XLSX, XLS, PPTX, CSV).

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Input: <data root>/whatsapp/attachments-index.json, written only by
wa-l0-import-history.py --attachments-dir, plus the chat files, so each document keeps the messages
around it. Output: <data root>/whatsapp/documents/. Runs on your machine. The pipeline runs it, with
no options and after the WhatsApp L1, only when you ask: xs-pipeline-run.py --ingest --whatsapp-extras.

    uv run python tools/whatsapp/wa-l1-extract-docs.py --dry-run
    uv run python tools/whatsapp/wa-l1-extract-docs.py --top 100 --workers 4
"""





























from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow")
    sys.exit(1)

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step

from sbk_config import DATA_ROOT, ENRICHED_DIR



WHATSAPP_DATA_DIR = DATA_ROOT / "whatsapp"
DOCUMENTS_DIR = WHATSAPP_DATA_DIR / "documents"
PLAN_FILE = WHATSAPP_DATA_DIR / "document-extraction-plan.json"
INDEX_FILE = DOCUMENTS_DIR / "_docs-index.json"
ATTACHMENTS_INDEX_FILE = WHATSAPP_DATA_DIR / "attachments-index.json"
CHATS_DIR = WHATSAPP_DATA_DIR / "chats"
RQ_SCORES_FILE = DATA_ROOT / "rq" / "composite-scores-v3.parquet"
CONTACTS_MERGED_FILE = ENRICHED_DIR / "contacts-merged.parquet"
NAME_MATCHING_INDEX = DATA_ROOT / "rq" / "name-matching-index.json"

DOC_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".csv"}
MAX_FILE_SIZE_MB = 50
MAX_PDF_PAGES = 100
MAX_XLSX_ROWS = 50
MAX_CSV_ROWS = 100
CONTEXT_BEFORE = 5
CONTEXT_AFTER = 3


FILE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2} \d{2} \d{2})"
    r" - "
    r"(.+?)"
    r" - "
    r"[a-f0-9\-]+"
    r"\.\w+$",
    re.IGNORECASE,
)



DEFAULT_TOP = 0

DEFAULT_WORKERS = None
BLOCK_SIZE = 50


def _quanti_processi(chiesti: int | None) -> int:
    ""




    if chiesti:
        return chiesti
    try:
        from sbk_resources import cpu_workers

        return cpu_workers()
    except ImportError:  # pragma: no cover
        return 2


log = logging.getLogger("wa-extract-docs")





def slugify(name: str) -> str:
    ""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
    return slug or "unknown"


def normalize_for_match(name: str) -> str:
    ""
    name = name.lower().strip()
    name = re.sub(r"^whatsapp\s*-\s*", "", name)
    name = re.sub(r"[^a-z\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def fuzzy_name_match(folder_name: str, candidates: list[str]) -> str | None:
    ""



    norm_folder = normalize_for_match(folder_name)
    folder_tokens = set(norm_folder.split())

    best_match = None
    best_score = 0.0

    for candidate in candidates:
        norm_cand = normalize_for_match(candidate)
        cand_tokens = set(norm_cand.split())

        if not norm_cand or not norm_folder:
            continue


        if norm_folder == norm_cand:
            return candidate


        if norm_folder in norm_cand or norm_cand in norm_folder:
            score = min(len(norm_folder), len(norm_cand)) / max(len(norm_folder), len(norm_cand))
            if score > best_score:
                best_score = score
                best_match = candidate
            continue


        common = folder_tokens & cand_tokens
        if len(common) >= 2:
            score = len(common) / len(folder_tokens | cand_tokens)
            if score > best_score:
                best_score = score
                best_match = candidate

    if best_score >= 0.4:
        return best_match
    return None


def parse_timestamp_from_filename(filename: str) -> datetime | None:
    ""
    m = FILE_PATTERN.match(filename)
    if not m:
        return None
    ts_str = m.group(1)
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H %M %S")
    except ValueError:
        return None


def parse_sender_from_filename(filename: str) -> str | None:
    ""
    m = FILE_PATTERN.match(filename)
    if not m:
        return None
    return m.group(2)





def extract_pdf(path: Path) -> dict:
    ""
    text_pages: list[str] = []
    total_pages = 0


    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:MAX_PDF_PAGES]):
                page_text = page.extract_text() or ""
                text_pages.append(page_text)

        full_text = "\n\n".join(text_pages)
        if full_text.strip():
            return {
                "text": full_text,
                "pages": total_pages,
                "method": "pdfplumber",
            }
    except Exception as e:
        log.debug("pdfplumber failed for %s: %s, trying fitz", path.name, e)


    try:
        import fitz

        doc = fitz.open(str(path))
        total_pages = len(doc)
        text_pages = []
        for i, page in enumerate(doc):
            if i >= MAX_PDF_PAGES:
                break
            text_pages.append(page.get_text())
        doc.close()

        full_text = "\n\n".join(text_pages)
        return {
            "text": full_text,
            "pages": total_pages,
            "method": "pymupdf",
        }
    except Exception as e:
        log.debug("fitz also failed for %s: %s", path.name, e)
        return {"text": "", "pages": 0, "method": "failed", "error": str(e)}


def extract_docx(path: Path) -> dict:
    ""
    try:
        from docx import Document

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(paragraphs)
        return {"text": full_text, "pages": None, "method": "python-docx"}
    except Exception as e:
        return {"text": "", "pages": None, "method": "failed", "error": str(e)}


def extract_doc(path: Path) -> dict:
    ""

    import subprocess

    try:
        result = subprocess.run(
            ["antiword", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return {"text": result.stdout, "pages": None, "method": "antiword"}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


    try:
        from docx import Document

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(paragraphs)
        if full_text.strip():
            return {"text": full_text, "pages": None, "method": "python-docx-compat"}
    except Exception:
        pass

    return {
        "text": "",
        "pages": None,
        "method": "failed",
        "error": "No .doc reader available (install antiword: brew install antiword)",
    }


def extract_xlsx(path: Path) -> dict:
    ""
    try:
        import openpyxl

        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        sheets_text: list[str] = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows: list[str] = []
            rows.append(f"--- Sheet: {sheet_name} ---")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_XLSX_ROWS:
                    rows.append(f"... (truncated at {MAX_XLSX_ROWS} rows)")
                    break
                cells = [str(c) if c is not None else "" for c in row]
                row_text = " | ".join(cells)
                if row_text.strip(" |"):
                    rows.append(row_text)
            sheets_text.append("\n".join(rows))

        wb.close()
        full_text = "\n\n".join(sheets_text)
        return {
            "text": full_text,
            "pages": None,
            "sheets": len(wb.sheetnames),
            "method": "openpyxl",
        }
    except Exception as e:
        return {"text": "", "pages": None, "method": "failed", "error": str(e)}


def extract_xls(path: Path) -> dict:
    ""

    try:
        dfs = pd.read_excel(str(path), sheet_name=None, nrows=MAX_XLSX_ROWS)
        sheets_text: list[str] = []
        for sheet_name, df in dfs.items():
            lines = [f"--- Sheet: {sheet_name} ---"]
            lines.append(df.to_string(index=False, max_rows=MAX_XLSX_ROWS))
            sheets_text.append("\n".join(lines))
        full_text = "\n\n".join(sheets_text)
        return {
            "text": full_text,
            "pages": None,
            "sheets": len(dfs),
            "method": "pandas",
        }
    except Exception as e:
        return {"text": "", "pages": None, "method": "failed", "error": str(e)}


def extract_pptx(path: Path) -> dict:
    ""
    try:
        from pptx import Presentation

        prs = Presentation(str(path))
        slides_text: list[str] = []

        for i, slide in enumerate(prs.slides):
            texts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        text = paragraph.text.strip()
                        if text:
                            texts.append(text)
            if texts:
                slides_text.append(f"--- Slide {i + 1} ---\n" + "\n".join(texts))

        full_text = "\n\n".join(slides_text)
        return {
            "text": full_text,
            "pages": len(prs.slides),
            "method": "python-pptx",
        }
    except Exception as e:
        return {"text": "", "pages": None, "method": "failed", "error": str(e)}


def extract_csv(path: Path) -> dict:
    ""
    try:

        raw = path.read_bytes()
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

        reader = csv.reader(io.StringIO(text))
        rows: list[str] = []
        for i, row in enumerate(reader):
            if i >= MAX_CSV_ROWS:
                rows.append(f"... (truncated at {MAX_CSV_ROWS} rows)")
                break
            row_text = " | ".join(row)
            if row_text.strip(" |"):
                rows.append(row_text)

        full_text = "\n".join(rows)
        return {"text": full_text, "pages": None, "method": "csv-stdlib"}
    except Exception as e:
        return {"text": "", "pages": None, "method": "failed", "error": str(e)}


EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".doc": extract_doc,
    ".xlsx": extract_xlsx,
    ".xls": extract_xls,
    ".pptx": extract_pptx,
    ".csv": extract_csv,
}





def load_chat_messages(chat_slug: str) -> list[dict] | None:
    ""



    if not CHATS_DIR.exists():
        return None


    chat_file = CHATS_DIR / f"{chat_slug}.json"
    if chat_file.exists():
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
            return data.get("messages", []) if isinstance(data, dict) else data
        except Exception:
            return None

    return None


def find_chat_file_for_contact(contact_key: str) -> Path | None:
    ""




    if not CHATS_DIR.exists():
        return None


    direct = CHATS_DIR / f"{contact_key}.json"
    if direct.exists():
        return direct


    normalized = contact_key.replace(" ", "-")
    norm_file = CHATS_DIR / f"{normalized}.json"
    if norm_file.exists():
        return norm_file

    return None


def get_conversation_context(
    chat_file: Path | None,
    doc_timestamp: datetime | None,
) -> tuple[list[dict], list[dict]]:
    ""



    if chat_file is None or doc_timestamp is None:
        return [], []

    try:
        data = json.loads(chat_file.read_text(encoding="utf-8"))
        messages = data.get("messages", []) if isinstance(data, dict) else data
    except Exception:
        return [], []

    if not messages:
        return [], []


    doc_ts = doc_timestamp.isoformat()
    best_idx = None
    best_diff = float("inf")

    for i, msg in enumerate(messages):
        msg_ts = msg.get("timestamp", "")
        if not msg_ts:
            continue
        try:
            msg_dt = datetime.fromisoformat(msg_ts.replace("Z", "+00:00"))

            msg_naive = msg_dt.replace(tzinfo=None)
            doc_naive = doc_timestamp.replace(tzinfo=None)
            diff = abs((msg_naive - doc_naive).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        except (ValueError, TypeError):
            continue

    if best_idx is None:
        return [], []


    if best_diff > 300:
        return [], []


    before_start = max(0, best_idx - CONTEXT_BEFORE)
    after_end = min(len(messages), best_idx + CONTEXT_AFTER + 1)

    before = []
    for msg in messages[before_start:best_idx]:
        before.append(
            {
                "sender": msg.get("sender", ""),
                "text": (msg.get("text", "") or "")[:500],
                "time": msg.get("timestamp", ""),
            }
        )

    after = []
    for msg in messages[best_idx + 1 : after_end]:
        after.append(
            {
                "sender": msg.get("sender", ""),
                "text": (msg.get("text", "") or "")[:500],
                "time": msg.get("timestamp", ""),
            }
        )

    return before, after


def infer_topic_hint(before: list[dict], after: list[dict]) -> str:
    ""
    all_text = " ".join(m.get("text", "") for m in (before + after) if m.get("text"))
    if not all_text.strip():
        return ""

    return all_text.strip()[:200]





def build_pid_to_name_map() -> dict[str, str]:
    ""
    pid_map: dict[str, str] = {}

    if CONTACTS_MERGED_FILE.exists():
        try:
            cm = pd.read_parquet(CONTACTS_MERGED_FILE, columns=["person_id", "name"])
            for _, row in cm.iterrows():
                pid = row.get("person_id", "")
                name = row.get("name", "")
                if pid and name and isinstance(name, str) and len(name) > 1:
                    pid_map[pid] = name
        except Exception as e:
            log.warning("Failed to read contacts-merged: %s", e)

    if NAME_MATCHING_INDEX.exists():
        try:
            idx = json.loads(NAME_MATCHING_INDEX.read_text())
            matches = idx.get("matches", {})
            for name, info in matches.items():
                pid = info.get("person_id", "")
                if pid and pid not in pid_map:
                    pid_map[pid] = name
                elif pid and pid in pid_map:
                    if len(name) > len(pid_map[pid]):
                        pid_map[pid] = name
        except Exception as e:
            log.warning("Failed to read name-matching-index: %s", e)

    return pid_map


def load_top_contacts(top_n: int) -> list[str]:
    ""
    if not RQ_SCORES_FILE.exists():
        log.error("RQ scores not found: %s", RQ_SCORES_FILE)
        sys.exit(1)

    df = pd.read_parquet(RQ_SCORES_FILE)
    df = df[df["person"].str.len() > 2].copy()
    df = df.nlargest(top_n, "score_v3")

    pid_map = build_pid_to_name_map()

    names = []
    unresolved = 0
    for _, row in df.iterrows():
        pid = row["person"]
        if pid.startswith("p_"):
            resolved = pid_map.get(pid)
            if resolved:
                names.append(resolved)
            else:
                unresolved += 1
                log.debug("Unresolved person_id: %s (score=%.1f)", pid, row["score_v3"])
        else:
            names.append(pid)

    if unresolved:
        log.warning(
            "%d of top %d contacts could not be resolved to names (skipped)",
            unresolved,
            top_n,
        )

    log.info(
        "Loaded %d contacts from RQ scores (range: %.1f - %.1f)",
        len(names),
        df["score_v3"].min(),
        df["score_v3"].max(),
    )
    return names


def _gruppi_rumore() -> set[str]:
    try:
        import rumore

        return rumore.gruppi_rumore()
    except ImportError:  # pragma: no cover - fuori dal repo
        return set()


def discover_documents(
    top_contacts: list[str] | None,
    person_filter: str | None = None,
) -> dict[str, list[dict]]:
    ""








    if not ATTACHMENTS_INDEX_FILE.exists():
        log.error("Attachments index not found: %s", ATTACHMENTS_INDEX_FILE)
        sys.exit(1)

    att_index = json.loads(ATTACHMENTS_INDEX_FILE.read_text(encoding="utf-8"))
    log.info("Loaded attachments index: %d contacts", len(att_index))


    slug_to_name: dict[str, str] = {}
    for name in top_contacts or []:
        slug_to_name[slugify(name)] = name


    contact_to_person: dict[str, str] = {}
    unmatched: list[str] = []


    SUFFIX_PATTERN = re.compile(r"(---\d+|-privato|---privato)$")

    person_filter_slug = slugify(person_filter) if person_filter else None

    tutte = top_contacts is None and not person_filter
    att_tutti = att_index
    if tutte:

        rumorosi = _gruppi_rumore()
        contact_to_person = {k: k for k in att_index if f"{k}.json" not in rumorosi}
        att_index = {}
    for contact_key in att_index:
        key_slug = contact_key.lower().strip()

        if person_filter:

            pf_lower = person_filter.lower()
            if pf_lower not in contact_key.lower() and (
                person_filter_slug not in contact_key.lower() if person_filter_slug else True
            ):
                continue

            contact_to_person[contact_key] = person_filter
            continue


        matched = slug_to_name.get(key_slug)


        if not matched:
            stripped = SUFFIX_PATTERN.sub("", key_slug)
            if stripped != key_slug:
                matched = slug_to_name.get(stripped)


        if not matched:
            matched = fuzzy_name_match(contact_key, top_contacts or [])

        if matched:
            contact_to_person[contact_key] = matched
        else:
            unmatched.append(contact_key)

    att_index = att_tutti
    log.info(
        "Matched %d contacts (%s, %d unmatched)",
        len(contact_to_person),
        "tutte le chat, gruppi rumore fuori" if tutte else f"top {len(top_contacts or [])}",
        len(unmatched),
    )


    person_docs: dict[str, list[dict]] = defaultdict(list)
    total_scanned = 0
    total_docs = 0
    total_skipped_size = 0

    for contact_key, person_name in sorted(contact_to_person.items()):
        files = att_index[contact_key]
        for f in files:
            total_scanned += 1
            ext = f.get("ext", "").lower()
            if not ext.startswith("."):
                ext = "." + ext
            if ext not in DOC_EXTENSIONS:
                continue

            file_path = f.get("path", "")
            if not file_path or not Path(file_path).exists():
                log.debug("File not found: %s", file_path)
                continue

            size_bytes = f.get("size_bytes", 0)
            if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
                total_skipped_size += 1
                log.debug("Skipping large file (%.1f MB): %s", size_bytes / 1024 / 1024, file_path)
                continue


            fname = Path(file_path).name
            timestamp = parse_timestamp_from_filename(fname)
            sender = parse_sender_from_filename(fname) or f.get("sender", person_name)

            person_docs[person_name].append(
                {
                    "path": file_path,
                    "contact_key": contact_key,
                    "sender": sender,
                    "timestamp": timestamp.isoformat() if timestamp else f.get("timestamp"),
                    "timestamp_dt": timestamp,
                    "ext": ext,
                    "size_bytes": size_bytes,
                }
            )
            total_docs += 1


    for person_name in person_docs:
        person_docs[person_name].sort(key=lambda x: x.get("timestamp") or "")

    if total_skipped_size:
        log.info("Skipped %d files over %d MB size limit", total_skipped_size, MAX_FILE_SIZE_MB)

    log.info(
        "Found %d documents across %d people (scanned %d attachments)",
        total_docs,
        len(person_docs),
        total_scanned,
    )

    return dict(person_docs)





def create_plan(
    person_docs: dict[str, list[dict]],
    block_size: int = BLOCK_SIZE,
) -> dict:
    ""
    blocks = []
    block_id = 0

    for person in sorted(person_docs.keys()):
        docs = person_docs[person]
        for i in range(0, len(docs), block_size):
            chunk = docs[i : i + block_size]
            blocks.append(
                {
                    "id": block_id,
                    "person": person,
                    "files": [
                        {
                            "path": d["path"],
                            "contact_key": d["contact_key"],
                            "sender": d["sender"],
                            "timestamp": d["timestamp"],
                            "ext": d["ext"],
                            "size_bytes": d["size_bytes"],
                        }
                        for d in chunk
                    ],
                    "file_count": len(chunk),
                    "status": "pending",
                    "completed_at": None,
                    "error": None,
                }
            )
            block_id += 1

    total_files = sum(len(docs) for docs in person_docs.values())
    total_size_mb = sum(d["size_bytes"] for docs in person_docs.values() for d in docs) / (
        1024 * 1024
    )

    plan = {
        "created_at": datetime.now().isoformat(),
        "total_files": total_files,
        "total_blocks": len(blocks),
        "total_people": len(person_docs),
        "total_size_mb": round(total_size_mb, 1),
        "block_size": block_size,
        "blocks": blocks,
    }
    return plan


def save_plan(plan: dict) -> None:
    ""
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("Plan saved to %s", PLAN_FILE)


def load_plan() -> dict | None:
    ""
    if not PLAN_FILE.exists():
        return None
    try:
        return json.loads(PLAN_FILE.read_text())
    except Exception as e:
        log.error("Failed to load plan: %s", e)
        return None


def print_plan_summary(plan: dict) -> None:
    ""
    pending = sum(1 for b in plan["blocks"] if b["status"] == "pending")
    completed = sum(1 for b in plan["blocks"] if b["status"] == "completed")
    failed = sum(1 for b in plan["blocks"] if b["status"] == "failed")

    pending_files = sum(b["file_count"] for b in plan["blocks"] if b["status"] == "pending")
    completed_files = sum(b["file_count"] for b in plan["blocks"] if b["status"] == "completed")

    log.info("")
    log.info("=" * 70)
    log.info("DOCUMENT EXTRACTION PLAN")
    log.info("=" * 70)
    log.info("  People:      %d", plan["total_people"])
    log.info("  Total files: %d", plan["total_files"])
    log.info("  Total size:  %s MB", plan.get("total_size_mb", "?"))
    log.info("  Blocks:      %d (size=%d)", plan["total_blocks"], plan["block_size"])
    log.info("  Status:      %d completed, %d pending, %d failed", completed, pending, failed)
    log.info("  Files:       %d done, %d remaining", completed_files, pending_files)
    log.info("")


    person_blocks: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "pending": 0, "files": 0, "size_mb": 0.0}
    )
    for b in plan["blocks"]:
        p = person_blocks[b["person"]]
        p["total"] += 1
        p["files"] += b["file_count"]
        if b["status"] == "pending":
            p["pending"] += b["file_count"]
        p["size_mb"] += sum(f.get("size_bytes", 0) for f in b["files"]) / (1024 * 1024)


    ext_counts: dict[str, int] = defaultdict(int)
    for b in plan["blocks"]:
        for f in b["files"]:
            ext_counts[f.get("ext", "?")] += 1

    log.info("  %s %s", f"{'Type':<8}", f"{'Count':>6}")
    log.info("  %s", "-" * 16)
    for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
        log.info("  %s %6d", f"{ext:<8}", count)
    log.info("")

    log.info(
        "  %s %s %s %s %s",
        f"{'Person':<35}",
        f"{'Files':>6}",
        f"{'Pending':>8}",
        f"{'Size MB':>8}",
        f"{'Blocks':>7}",
    )
    log.info("  %s", "-" * 68)
    for person in sorted(person_blocks.keys()):
        info = person_blocks[person]
        log.info(
            "  %s %6d %8d %7.1f %7d",
            f"{person:<35}",
            info["files"],
            info["pending"],
            info["size_mb"],
            info["total"],
        )
    log.info("")





def extract_one_document(args: tuple[str, str, str, str, str, str]) -> dict:
    ""




    file_path_str, contact_key, person_name, sender, timestamp_str, ext = args
    file_path = Path(file_path_str)
    chat_slug = slugify(person_name)
    out_dir = DOCUMENTS_DIR / chat_slug
    out_json = out_dir / f"{file_path.stem}.json"


    if out_json.exists():
        try:
            existing = json.loads(out_json.read_text())
            if existing.get("text") is not None:
                return {
                    "path": file_path_str,
                    "status": "skipped",
                    "word_count": existing.get("word_count", 0),
                }
        except Exception:
            pass

    if not file_path.exists():
        return {"path": file_path_str, "status": "file_not_found"}

    t0 = time.time()


    extractor = EXTRACTORS.get(ext)
    if not extractor:
        return {"path": file_path_str, "status": "unsupported_ext", "ext": ext}

    try:
        result = extractor(file_path)
    except Exception as e:
        return {"path": file_path_str, "status": "extraction_error", "error": str(e)[:300]}

    text = result.get("text", "")
    word_count = len(text.split()) if text.strip() else 0


    timestamp_dt = None
    if timestamp_str:
        try:
            timestamp_dt = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            pass

    chat_file = find_chat_file_for_contact(contact_key)
    before, after = get_conversation_context(chat_file, timestamp_dt)
    topic_hint = infer_topic_hint(before, after)

    elapsed = time.time() - t0


    doc_output = {
        "source_file": file_path_str,
        "chat": person_name,
        "sender": sender,
        "timestamp": timestamp_str,
        "type": ext.lstrip("."),
        "pages": result.get("pages"),
        "sheets": result.get("sheets"),
        "word_count": word_count,
        "extraction_method": result.get("method", "unknown"),
        "text": text,
        "conversation_before": before,
        "conversation_after": after,
        "topic_hint": topic_hint,
        "extracted_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
    }

    if result.get("error"):
        doc_output["extraction_error"] = result["error"]


    out_dir.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(doc_output, indent=2, ensure_ascii=False))

    return {
        "path": file_path_str,
        "status": "done",
        "word_count": word_count,
        "ext": ext,
        "method": result.get("method", "?"),
        "elapsed": round(elapsed, 2),
        "has_context": len(before) > 0 or len(after) > 0,
    }


def extract_blocks(
    plan: dict,
    workers: int | None = DEFAULT_WORKERS,
    block_filter: int | None = None,
) -> None:
    ""
    workers = _quanti_processi(workers)
    pending_blocks = [
        b
        for b in plan["blocks"]
        if b["status"] == "pending" and (block_filter is None or b["id"] == block_filter)
    ]

    if not pending_blocks:
        log.info("No pending blocks to extract.")
        return

    total_files = sum(b["file_count"] for b in pending_blocks)
    log.info(
        "Extracting %d blocks (%d files) with %d workers",
        len(pending_blocks),
        total_files,
        workers,
    )

    global_done = 0
    global_skipped = 0
    global_errors = 0
    global_words = 0
    global_with_context = 0
    global_t0 = time.time()

    for block in pending_blocks:
        block_id = block["id"]
        person = block["person"]
        files = block["files"]

        log.info("Block %d: %s (%d files)", block_id, person, len(files))

        block_results = []
        block_errors = 0


        work_items = [
            (
                f["path"],
                f["contact_key"],
                person,
                f["sender"],
                f["timestamp"],
                f["ext"],
            )
            for f in files
        ]

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(extract_one_document, item): item[0] for item in work_items}
            for future in as_completed(futures):
                fname = Path(futures[future]).name
                try:
                    result = future.result()
                    status = result.get("status", "?")
                    if status == "skipped":
                        global_skipped += 1
                        log.debug("  %s: skipped (already done)", fname)
                    elif status == "done":
                        global_done += 1
                        global_words += result.get("word_count", 0)
                        if result.get("has_context"):
                            global_with_context += 1
                        log.info(
                            "  [%d/%d] %s: %d words, %s, %.1fs%s",
                            global_done + global_skipped,
                            total_files,
                            fname[:50],
                            result.get("word_count", 0),
                            result.get("method", "?"),
                            result.get("elapsed", 0),
                            " +ctx" if result.get("has_context") else "",
                        )
                    else:
                        global_errors += 1
                        block_errors += 1
                        log.error(
                            "  %s: %s — %s",
                            fname,
                            status,
                            result.get("error", "")[:100],
                        )
                    block_results.append(result)
                except Exception as e:
                    global_errors += 1
                    block_errors += 1
                    log.error("  %s: worker exception: %s", fname, e)


        if block_errors == 0:
            block["status"] = "completed"
            block["completed_at"] = datetime.now().isoformat()
        elif block_errors < len(files):
            block["status"] = "completed"
            block["completed_at"] = datetime.now().isoformat()
            block["error"] = f"{block_errors} files failed"
        else:
            block["status"] = "failed"
            block["error"] = f"All {block_errors} files failed"


        save_plan(plan)
        log.info(
            "Block %d: %s (%d done, %d skipped, %d errors)",
            block_id,
            block["status"],
            len([r for r in block_results if r.get("status") == "done"]),
            len([r for r in block_results if r.get("status") == "skipped"]),
            block_errors,
        )

    elapsed = time.time() - global_t0
    log.info(
        "All done in %.0fs: %d extracted, %d skipped, %d errors, %d total words, %d with context",
        elapsed,
        global_done,
        global_skipped,
        global_errors,
        global_words,
        global_with_context,
    )





def generate_index() -> dict:
    ""
    if not DOCUMENTS_DIR.exists():
        return {}

    docs: list[dict] = []
    person_stats: dict[str, dict] = defaultdict(
        lambda: {
            "files": 0,
            "total_words": 0,
            "types": defaultdict(int),
            "with_context": 0,
            "earliest": None,
            "latest": None,
        }
    )

    for chat_dir in sorted(DOCUMENTS_DIR.iterdir()):
        if not chat_dir.is_dir():
            continue
        if chat_dir.name.startswith("_"):
            continue

        for json_file in sorted(chat_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
            except Exception:
                continue

            person = data.get("chat", chat_dir.name)
            stats = person_stats[person]
            stats["files"] += 1
            stats["total_words"] += data.get("word_count", 0)
            doc_type = data.get("type", "unknown")
            stats["types"][doc_type] += 1

            if data.get("conversation_before") or data.get("conversation_after"):
                stats["with_context"] += 1

            ts = data.get("timestamp")
            if ts:
                if stats["earliest"] is None or ts < stats["earliest"]:
                    stats["earliest"] = ts
                if stats["latest"] is None or ts > stats["latest"]:
                    stats["latest"] = ts

            docs.append(
                {
                    "file": str(json_file),
                    "source_file": data.get("source_file", ""),
                    "chat": person,
                    "sender": data.get("sender", ""),
                    "timestamp": ts,
                    "type": doc_type,
                    "word_count": data.get("word_count", 0),
                    "has_context": bool(
                        data.get("conversation_before") or data.get("conversation_after")
                    ),
                }
            )


    for person in person_stats:
        person_stats[person]["types"] = dict(person_stats[person]["types"])


    total_words = sum(d["word_count"] for d in docs)
    type_counts: dict[str, int] = defaultdict(int)
    for d in docs:
        type_counts[d["type"]] += 1

    index = {
        "generated_at": datetime.now().isoformat(),
        "total_documents": len(docs),
        "total_words": total_words,
        "total_people": len(person_stats),
        "with_context": sum(1 for d in docs if d["has_context"]),
        "type_breakdown": dict(type_counts),
        "people": dict(person_stats),
        "documents": docs,
    }

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    log.info("Index saved to %s (%d documents, %d words)", INDEX_FILE, len(docs), total_words)

    return index


def print_summary(index: dict) -> None:
    ""
    log.info("")
    log.info("=" * 70)
    log.info("DOCUMENT EXTRACTION SUMMARY")
    log.info("=" * 70)
    log.info("  Total documents: %d", index.get("total_documents", 0))
    log.info("  Total words:     %s", f"{index.get('total_words', 0):,}")
    log.info("  Total people:    %d", index.get("total_people", 0))
    log.info("  With context:    %d", index.get("with_context", 0))
    log.info("")

    type_breakdown = index.get("type_breakdown", {})
    if type_breakdown:
        log.info("  %s %s", f"{'Type':<8}", f"{'Count':>6}")
        log.info("  %s", "-" * 16)
        for doc_type, count in sorted(type_breakdown.items(), key=lambda x: -x[1]):
            log.info("  %s %6d", f"{doc_type:<8}", count)
        log.info("")

    people = index.get("people", {})
    if people:
        log.info(
            "  %s %s %s %s %s",
            f"{'Person':<35}",
            f"{'Files':>6}",
            f"{'Words':>8}",
            f"{'Context':>8}",
            "Types",
        )
        log.info("  %s", "-" * 75)
        for person in sorted(people.keys()):
            stats = people[person]
            types_str = ", ".join(f"{t}:{c}" for t, c in sorted(stats.get("types", {}).items()))
            log.info(
                "  %s %6d %8d %8d %s",
                f"{person:<35}",
                stats["files"],
                stats["total_words"],
                stats["with_context"],
                types_str,
            )
    log.info("")





@pipeline_step(name="wa-l1-extract-docs", source="wa-l1-docs", stage="l1")
def main():
    parser = argparse.ArgumentParser(description="Extract text from WhatsApp document attachments")
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Number of top contacts to process (default: {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Parallel workers for extraction (default: from the machine budget, sbk_resources.cpu_workers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show extraction plan without executing",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from saved extraction plan",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Only process documents for this person (substring match)",
    )
    parser.add_argument(
        "--block",
        type=int,
        default=None,
        help="Only process this block ID",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only regenerate the index/summary",
    )

    args = parser.parse_args()

    if args.summary_only:
        index = generate_index()
        print_summary(index)
        return

    if args.resume:
        plan = load_plan()
        if not plan:
            log.error("No saved plan found at %s", PLAN_FILE)
            sys.exit(1)
        log.info("Resuming from saved plan")
        print_plan_summary(plan)
        if args.dry_run:
            return
        extract_blocks(plan, workers=args.workers, block_filter=args.block)
        index = generate_index()
        print_summary(index)
        return


    top_contacts = load_top_contacts(args.top) if args.top > 0 else None
    person_docs = discover_documents(top_contacts, person_filter=args.person)

    if not person_docs:
        log.info("No documents found matching criteria.")
        return


    plan = create_plan(person_docs, block_size=BLOCK_SIZE)
    save_plan(plan)
    print_plan_summary(plan)

    if args.dry_run:
        log.info("Dry run complete. Plan saved to %s", PLAN_FILE)
        return


    extract_blocks(plan, workers=args.workers, block_filter=args.block)


    index = generate_index()
    print_summary(index)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    main()
