#!/usr/bin/env python3
"""Extract text from downloaded email attachments into a single parquet (L2)."""















from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from sbk_config import (  # noqa: E402
    EMAILS_DIR,
    ENRICHED_DIR,
    mail_labels,
    mark_last_run,
    safe_write_parquet,
)

log = logging.getLogger("em-l2-attachments")

OUTPUT_FILE = ENRICHED_DIR / "attachment-content.parquet"
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
# Mailboxes to read: emails/accounts.json, email_accounts in sbk.config.json, emails/<label>/.
ACCOUNTS = mail_labels()


EXTRACTABLE = {
    "pdf",
    "docx",
    "doc",
    "xlsx",
    "xls",
    "csv",
    "txt",
    "rtf",
    "ics",
    "json",
    "xml",
    "html",
    "htm",
    "md",
    "eml",
}


def extract_pdf(path: Path) -> str:
    ""
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:100]:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)[:MAX_TEXT_CHARS]


def extract_docx(path: Path) -> str:
    ""
    import docx

    doc = docx.Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)[:MAX_TEXT_CHARS]


def extract_xlsx(path: Path) -> str:
    ""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for sheet_name in wb.sheetnames[:10]:
        ws = wb[sheet_name]
        parts.append(f"[Sheet: {sheet_name}]")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 200:
                parts.append(f"... ({ws.max_row - 200} more rows)")
                break
            row_text = " | ".join(str(c) if c is not None else "" for c in row)
            if row_text.strip():
                parts.append(row_text)
    wb.close()
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def extract_text_file(path: Path) -> str:
    ""
    try:
        return path.read_text(errors="replace")[:MAX_TEXT_CHARS]
    except Exception:
        return path.read_bytes().decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]


def extract_ics(path: Path) -> str:
    ""
    text = path.read_text(errors="replace")
    parts = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(("SUMMARY:", "DESCRIPTION:", "DTSTART:", "DTEND:", "LOCATION:")):
            parts.append(line)
    return "\n".join(parts)[:MAX_TEXT_CHARS] if parts else text[:MAX_TEXT_CHARS]


EXTRACTORS = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "doc": extract_docx,
    "xlsx": extract_xlsx,
    "xls": extract_xlsx,
    "csv": extract_text_file,
    "txt": extract_text_file,
    "json": extract_text_file,
    "xml": extract_text_file,
    "html": extract_text_file,
    "htm": extract_text_file,
    "md": extract_text_file,
    "eml": extract_text_file,
    "rtf": extract_text_file,
    "ics": extract_ics,
}


def extract_one(path: Path, account: str) -> dict | None:
    ""
    ext = path.suffix.lstrip(".").lower()
    if ext not in EXTRACTORS:
        return None
    if path.stat().st_size > MAX_FILE_SIZE:
        return None

    extractor = EXTRACTORS[ext]
    try:
        content = extractor(path)
        if not content or len(content.strip()) < 10:
            return None
        return {
            "file_path": str(path),
            "filename": path.name,
            "mime_type": ext,
            "account": account,
            "content_text": content,
            "char_count": len(content),
            "extraction_method": ext,
        }
    except Exception as e:
        log.debug(f"Failed to extract {path.name}: {e}")
        return None


def collect_files(accounts: list[str]) -> list[tuple[Path, str]]:
    ""
    files = []
    for account in accounts:
        att_dir = EMAILS_DIR / account / "attachments"
        if not att_dir.exists():
            continue
        for f in att_dir.rglob("*"):
            if f.is_file() and f.suffix.lstrip(".").lower() in EXTRACTABLE:
                files.append((f, account))
    return files


def main():
    parser = argparse.ArgumentParser(description="Extract text from email attachments")
    parser.add_argument("--incremental", action="store_true", help="Skip already-extracted files")
    parser.add_argument("--dry-run", action="store_true", help="Count files without extracting")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers (default 6)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    files = collect_files(ACCOUNTS)
    log.info(f"Found {len(files)} extractable attachment files across {len(ACCOUNTS)} accounts")

    if args.dry_run:
        by_ext: dict[str, int] = {}
        for f, _ in files:
            ext = f.suffix.lstrip(".").lower()
            by_ext[ext] = by_ext.get(ext, 0) + 1
        for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
            log.info(f"  {ext}: {count} files")
        log.info(f"Total: {len(files)} files")
        return


    existing_paths: set[str] = set()
    if args.incremental and OUTPUT_FILE.exists():
        import pandas as pd

        existing_df = pd.read_parquet(OUTPUT_FILE)
        existing_paths = set(existing_df["file_path"].tolist())
        log.info(f"Incremental: {len(existing_paths)} files already extracted")
        files = [(f, a) for f, a in files if str(f) not in existing_paths]
        log.info(f"Remaining: {len(files)} files to extract")

    if not files:
        log.info("Nothing to extract")
        return

    t0 = time.time()
    records = []
    errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract_one, f, a): (f, a) for f, a in files}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                records.append(result)
            else:
                errors += 1
            if i % 500 == 0:
                log.info(f"  [{i}/{len(files)}] {len(records)} extracted, {errors} skipped")

    elapsed = time.time() - t0
    log.info(f"Extracted {len(records)} files in {elapsed:.1f}s ({errors} skipped/failed)")

    if not records:
        log.warning("No text extracted from any attachment")
        return

    import pandas as pd

    df = pd.DataFrame(records)


    if args.incremental and existing_paths:
        existing_df = pd.read_parquet(OUTPUT_FILE)
        df = pd.concat([existing_df, df], ignore_index=True)
        df = df.drop_duplicates(subset=["file_path"], keep="last")

    safe_write_parquet(df, OUTPUT_FILE)
    log.info(f"Saved {len(df)} records to {OUTPUT_FILE}")
    log.info(f"Total chars: {df['char_count'].sum():,}")
    mark_last_run("l2-email-attachments")

    log.info(f"Completed: l2-email-attachments ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
