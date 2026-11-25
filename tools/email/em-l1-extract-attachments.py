#!/usr/bin/env python3
"""Extract text from the most relevant mail attachments (PDF, Office, CSV, text) into the extracted-attachments store."""


























from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from pipeline_decorator import pipeline_step  # noqa: E402

from sbk_config import EMAILS_DIR, ENRICHED_DIR, RQ_DIR, mail_labels  # noqa: E402

log = logging.getLogger("em-l1-extract-att")



OUTPUT_DIR = EMAILS_DIR / "extracted-attachments"
STATS_FILE = OUTPUT_DIR / "_stats.json"

# Mailboxes to scan: emails/accounts.json, email_accounts in sbk.config.json, emails/<label>/.
ACCOUNTS = mail_labels()

EXTRACTABLE_EXTS = {"pdf", "docx", "doc", "xlsx", "xls", "csv", "txt", "pptx"}
SKIP_EXTS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "heic",
    "webp",
    "bmp",
    "tiff",
    "svg",
    "mp4",
    "mp3",
    "wav",
    "m4a",
    "ogg",
    "ics",
    "p7s",
    "eml",
    "zip",
    "7z",
    "rar",
    "tar",
    "gz",
    "xml",
    "html",
    "htm",
}

DEFAULT_TOP = 150
DEFAULT_MAX_SIZE_MB = 50
MAX_PAGES = 100
MAX_TEXT_CHARS = 500_000
BODY_SNIPPET_LEN = 300





def extract_pdf(path: Path) -> tuple[str, int]:
    ""
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages[:MAX_PAGES]:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)[:MAX_TEXT_CHARS], min(page_count, MAX_PAGES)


def extract_docx(path: Path) -> tuple[str, int]:
    ""
    import docx

    doc = docx.Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)[:MAX_TEXT_CHARS]

    page_estimate = max(1, len(text) // 3000)
    return text, page_estimate


def extract_xlsx(path: Path) -> tuple[str, int]:
    ""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    sheet_count = len(wb.sheetnames)
    for sheet_name in wb.sheetnames[:10]:
        ws = wb[sheet_name]
        parts.append(f"[Sheet: {sheet_name}]")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 500:
                parts.append(f"... (truncated, {i} rows shown)")
                break
            cells = [str(c) if c is not None else "" for c in row]
            row_text = " | ".join(cells)
            if row_text.strip(" |"):
                parts.append(row_text)
    wb.close()
    return "\n".join(parts)[:MAX_TEXT_CHARS], sheet_count


def extract_pptx(path: Path) -> tuple[str, int]:
    ""
    from pptx import Presentation

    prs = Presentation(path)
    slides = []
    for i, slide in enumerate(prs.slides):
        texts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                texts.append(shape.text.strip())
        if texts:
            slides.append(f"[Slide {i + 1}]\n" + "\n".join(texts))
    return "\n\n".join(slides)[:MAX_TEXT_CHARS], len(prs.slides)


def extract_text_file(path: Path) -> tuple[str, int]:
    ""
    try:
        text = path.read_text(errors="replace")[:MAX_TEXT_CHARS]
    except Exception:
        text = path.read_bytes().decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
    return text, 0


EXTRACTORS: dict[str, callable] = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "doc": extract_docx,
    "xlsx": extract_xlsx,
    "xls": extract_xlsx,
    "csv": extract_text_file,
    "txt": extract_text_file,
    "pptx": extract_pptx,
}





def file_sha256(path: Path) -> str:
    ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(name: str) -> str:
    ""
    import re

    safe = re.sub(r"[^\w\s\-\.]", "_", name)
    return safe[:100]


def load_top_persons(top_n: int, person_filter: str | None = None) -> dict[str, str]:
    ""







    import pandas as pd

    scores_file = RQ_DIR / "composite-scores-v3.parquet"
    if not scores_file.exists():
        log.warning("RQ V3 scores not found, falling back to V2")
        scores_file = RQ_DIR / "composite-scores-v2.parquet"

    df = pd.read_parquet(scores_file)
    score_col = "score_v3" if "score_v3" in df.columns else "score_v2"

    if person_filter:

        mask = df["person"].str.lower().str.contains(person_filter.lower(), na=False)
        df = df[mask]
        log.info(f"Filtered to {len(df)} persons matching '{person_filter}'")
    else:
        df = df.nlargest(top_n, score_col)


    pid_to_name: dict[str, str] = {}
    contacts_file = ENRICHED_DIR / "contacts-merged.parquet"
    if contacts_file.exists():
        cm = pd.read_parquet(contacts_file, columns=["person_id", "name"])
        for _, row in cm.iterrows():
            pid = str(row.get("person_id", ""))
            name = str(row.get("name", ""))
            if pid and name:
                pid_to_name[pid] = name

    result: dict[str, str] = {}
    for _, row in df.iterrows():
        person_val = str(row["person"])
        if person_val.startswith("p_"):

            pid = person_val
            name = pid_to_name.get(pid, pid)
        else:

            name = person_val
            pid = ""
            for p, n in pid_to_name.items():
                if n == name:
                    pid = p
                    break
            if not pid:
                pid = name
        result[pid] = name

    return result


def load_attachment_index() -> dict:
    ""
    idx_file = ENRICHED_DIR / "person-attachments-index.json"
    if not idx_file.exists():
        log.error(f"Person attachments index not found: {idx_file}")
        return {}
    return json.loads(idx_file.read_text(encoding="utf-8"))


def load_msg_index(account: str) -> dict[str, str]:
    ""
    idx_file = EMAILS_DIR / account / "attachments" / "index.parquet"
    if not idx_file.exists():
        return {}
    import pandas as pd

    df = pd.read_parquet(idx_file)
    return dict(zip(df["path"].astype(str), df["msg_id"].astype(str)))


def load_messages(account: str) -> dict[str, dict]:
    ""
    msg_file = EMAILS_DIR / account / "messages.parquet"
    if not msg_file.exists():
        return {}
    import pandas as pd

    df = pd.read_parquet(msg_file)
    result = {}
    for _, row in df.iterrows():
        msg_id = str(row.get("id", ""))
        if not msg_id:
            continue
        body = str(row.get("body_text", "") or "")
        result[msg_id] = {
            "subject": str(row.get("subject", "") or ""),
            "from_addr": str(row.get("from_addr", "") or ""),
            "to_addr": str(row.get("to_addr", "") or ""),
            "cc": str(row.get("cc", "") or ""),
            "date": str(row.get("date", "") or ""),
            "body_snippet": body[:BODY_SNIPPET_LEN] if body else "",
        }
    return result


def output_path_for(account: str, msg_id: str, filename: str) -> Path:
    ""
    safe_fn = safe_filename(Path(filename).stem) + ".json"
    return OUTPUT_DIR / account / f"{msg_id}_{safe_fn}"





def extract_one_attachment(
    att: dict,
    msg_indexes: dict[str, dict[str, str]],
    msg_stores: dict[str, dict[str, dict]],
    max_size_bytes: int,
    seen_hashes: set[str],
) -> dict | None:
    ""
    file_path = Path(att["path"])
    ext = att.get("ext", "").lower()
    account = att.get("account", "")


    if ext not in EXTRACTORS:
        return None
    if not file_path.exists():
        log.debug(f"File not found: {file_path}")
        return None

    try:
        file_size = file_path.stat().st_size
    except OSError:
        return None

    if file_size > max_size_bytes:
        log.debug(f"Skipping large file ({file_size / 1e6:.1f} MB): {file_path.name}")
        return None
    if file_size == 0:
        return None


    sha = file_sha256(file_path)
    if sha in seen_hashes:
        return None
    seen_hashes.add(sha)


    msg_id = ""
    path_str = str(file_path)
    if account in msg_indexes:
        msg_id = msg_indexes[account].get(path_str, "")


    if msg_id:
        out_path = output_path_for(account, msg_id, att.get("filename", file_path.name))
        if out_path.exists():
            return None


    try:
        extractor = EXTRACTORS[ext]
        text, pages = extractor(file_path)
    except Exception as e:
        error_type = type(e).__name__

        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            return {
                "_status": "failed",
                "error": "password_protected",
                "file_path": path_str,
            }
        log.debug(f"Extraction failed for {file_path.name}: {error_type}: {e}")
        return {
            "_status": "failed",
            "error": f"{error_type}: {str(e)[:200]}",
            "file_path": path_str,
        }

    if not text or len(text.strip()) < 10:
        return None

    word_count = len(text.split())


    email_context = {}
    if msg_id and account in msg_stores:
        email_context = msg_stores[account].get(msg_id, {})


    if not email_context:
        email_context = {
            "subject": att.get("context", ""),
            "from_addr": att.get("sender", ""),
            "to_addr": "",
            "date": att.get("timestamp", ""),
            "body_snippet": "",
        }

    result = {
        "message_id": msg_id,
        "filename": att.get("filename", file_path.name),
        "mime_type": ext,
        "file_size_bytes": file_size,
        "file_sha256": sha,
        "text": text,
        "pages": pages,
        "word_count": word_count,
        "extraction_method": ext,
        "email_context": {
            "subject": email_context.get("subject", ""),
            "sender": email_context.get("from_addr", att.get("sender", "")),
            "to": email_context.get("to_addr", ""),
            "date": email_context.get("date", att.get("timestamp", "")),
            "body_snippet": email_context.get("body_snippet", ""),
        },
        "person_ids": [],
        "account": account,
        "source_file": path_str,
        "extracted_at": datetime.now(UTC).isoformat(),
    }
    return result





@pipeline_step(name="l1-email-attachment-extract", source="email-attachments", stage="l1")
def main():
    parser = argparse.ArgumentParser(
        description="Extract text from email attachments for top persons"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Top N persons by RQ score (default {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Filter to a specific person name (substring match)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without extracting")
    parser.add_argument(
        "--workers", type=int, default=4, help="Parallel extraction workers (default 4)"
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=DEFAULT_MAX_SIZE_MB,
        help=f"Max file size in MB (default {DEFAULT_MAX_SIZE_MB})",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-extract even if output already exists"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    max_size_bytes = args.max_size_mb * 1024 * 1024


    log.info(f"Loading top {args.top} persons by RQ score...")
    top_persons = load_top_persons(args.top, args.person)
    log.info(f"Selected {len(top_persons)} persons")


    att_index = load_attachment_index()
    if not att_index:
        log.error("No attachment index available. Run em-util-backfill-attachments.py first.")
        sys.exit(1)


    pai_by_pid: dict[str, str] = {}
    for pai_name, pai_entry in att_index.items():
        pid = pai_entry.get("person_id", "")
        if pid:
            pai_by_pid[pid] = pai_name



    attachments_to_process: list[tuple[dict, str, str]] = []

    matched_persons = 0
    for pid, display_name in top_persons.items():

        pai_name = pai_by_pid.get(pid) or (display_name if display_name in att_index else None)
        if not pai_name:
            continue

        entry = att_index[pai_name]
        matched_persons += 1
        effective_pid = pid if pid.startswith("p_") else entry.get("person_id", pid)

        for source_key, att_list in entry.get("sources", {}).items():
            if source_key != "email":
                continue
            for att in att_list:
                ext = (att.get("ext") or "").lower()
                if ext in EXTRACTABLE_EXTS and att.get("path"):
                    attachments_to_process.append((att, display_name, effective_pid))

    log.info(f"Matched {matched_persons}/{len(top_persons)} persons in attachment index")

    log.info(
        f"Found {len(attachments_to_process)} extractable attachments "
        f"across {len(top_persons)} persons"
    )


    by_type: dict[str, int] = {}
    by_person: dict[str, int] = {}
    total_size = 0
    for att, pname, _ in attachments_to_process:
        ext = att.get("ext", "").lower()
        by_type[ext] = by_type.get(ext, 0) + 1
        by_person[pname] = by_person.get(pname, 0) + 1
        total_size += att.get("size_bytes", 0)

    log.info("By type:")
    for ext, count in sorted(by_type.items(), key=lambda x: -x[1]):
        log.info(f"  {ext}: {count}")
    log.info(f"Total size: {total_size / 1e6:.0f} MB")
    log.info(f"Persons with attachments: {len(by_person)}")

    if args.dry_run:
        log.info("--- DRY RUN ---")
        log.info("Top persons by attachment count:")
        for pname, count in sorted(by_person.items(), key=lambda x: -x[1])[:20]:
            log.info(f"  {pname}: {count}")
        return


    log.info("Loading message indexes...")
    msg_indexes: dict[str, dict[str, str]] = {}
    msg_stores: dict[str, dict[str, dict]] = {}
    for account in ACCOUNTS:
        msg_indexes[account] = load_msg_index(account)
        msg_stores[account] = load_messages(account)
        log.info(
            f"  {account}: {len(msg_indexes[account])} attachment paths, "
            f"{len(msg_stores[account])} messages"
        )


    for account in ACCOUNTS:
        (OUTPUT_DIR / account).mkdir(parents=True, exist_ok=True)


    seen_hashes: set[str] = set()
    stats = {
        "extracted": 0,
        "skipped_exists": 0,
        "skipped_dedup": 0,
        "skipped_size": 0,
        "failed": 0,
        "failed_password": 0,
        "total_words": 0,
        "total_chars": 0,
        "by_type": {},
        "by_person": {},
    }

    t0 = time.time()
    total = len(attachments_to_process)


    person_atts: dict[str, list[tuple[dict, str]]] = {}
    for att, pname, pid in attachments_to_process:
        key = att.get("path", "")
        if key not in person_atts:
            person_atts[key] = []
        person_atts[key].append((pname, pid))

    def process_one(item: tuple[dict, str, str]) -> dict | None:
        att, pname, pid = item
        return extract_one_attachment(att, msg_indexes, msg_stores, max_size_bytes, seen_hashes)



    results = []
    for i, (att, pname, pid) in enumerate(attachments_to_process, 1):
        result = extract_one_attachment(att, msg_indexes, msg_stores, max_size_bytes, seen_hashes)

        if result is None:
            continue

        if result.get("_status") == "failed":
            stats["failed"] += 1
            if result.get("error") == "password_protected":
                stats["failed_password"] += 1
            continue


        path_key = att.get("path", "")
        person_ids = list({p[1] for p in person_atts.get(path_key, []) if p[1]})
        result["person_ids"] = person_ids


        account = result.get("account", att.get("account", "unknown"))
        msg_id = result.get("message_id", "no_msg_id")
        filename = result.get("filename", "unknown")
        out_path = output_path_for(account, msg_id, filename)
        out_path.parent.mkdir(parents=True, exist_ok=True)


        try:
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to save {out_path}: {e}")
            stats["failed"] += 1
            continue

        ext = result.get("mime_type", "")
        stats["extracted"] += 1
        stats["total_words"] += result.get("word_count", 0)
        stats["total_chars"] += len(result.get("text", ""))
        stats["by_type"][ext] = stats["by_type"].get(ext, 0) + 1
        stats["by_person"][pname] = stats["by_person"].get(pname, 0) + 1

        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = stats["extracted"] / elapsed if elapsed > 0 else 0
            log.info(
                f"  [{i}/{total}] extracted={stats['extracted']} "
                f"failed={stats['failed']} rate={rate:.1f}/s"
            )

    elapsed = time.time() - t0


    stats_out = {
        "run_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "top_n": args.top,
        "persons_selected": len(top_persons),
        "persons_with_attachments": len(stats["by_person"]),
        "total_candidates": total,
        "extracted": stats["extracted"],
        "failed": stats["failed"],
        "failed_password": stats["failed_password"],
        "total_words": stats["total_words"],
        "total_chars": stats["total_chars"],
        "by_type": stats["by_type"],
        "top_persons": dict(sorted(stats["by_person"].items(), key=lambda x: -x[1])[:30]),
    }
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats_out, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(f"\n{'=' * 60}")
    log.info("Attachment extraction complete")
    log.info(f"  Persons: {len(stats['by_person'])}/{len(top_persons)}")
    log.info(f"  Extracted: {stats['extracted']}")
    log.info(f"  Failed: {stats['failed']} (password: {stats['failed_password']})")
    log.info(f"  Words: {stats['total_words']:,}")
    log.info(f"  Time: {elapsed:.1f}s")
    log.info(f"  Output: {OUTPUT_DIR}")
    log.info(f"  Stats: {STATS_FILE}")


if __name__ == "__main__":
    main()
