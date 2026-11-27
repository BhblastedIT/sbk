#!/usr/bin/env python3
"""Clinical ingest: copies a clinical document you add (PDF or image of a blood test, visit, vaccination, allergy,
medication, ECG or imaging) into <data root>/clinical/ with its metadata, ready for cl-l1-parse.py.
"""

import argparse
import base64
import json
import logging
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path

from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import (  # noqa: E402
    CLINICAL_INCOMING_DIR,
    CLINICAL_ORIGINALS_DIR,
    OWNER_SUBJECT,
    mark_last_run,
)

log = logging.getLogger("cl-l0")

VALID_TYPES = {"blood_test", "visit", "vaccination", "allergy", "medication", "ecg", "imaging"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".bmp"}
PDF_EXTENSIONS = {".pdf"}


def extract_text_from_pdf(pdf_path: Path) -> str:
    ""
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except ImportError:
        log.warning("pdfplumber not installed, trying PyMuPDF...")
        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            text_parts = [page.get_text() for page in doc]
            doc.close()
            return "\n\n".join(text_parts)
        except ImportError:
            log.error(
                "Neither pdfplumber nor PyMuPDF installed. Install: uv pip install pdfplumber"
            )
            return ""


def encode_image_base64(image_path: Path) -> str:
    ""
    data = image_path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def get_image_media_type(image_path: Path) -> str:
    ""
    ext = image_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }
    return mime_map.get(ext, "image/jpeg")


def archive_original(
    file_path: Path, record_type: str, record_date: date, originals_dir: Path | None = None
) -> Path:
    ""



    out_dir = originals_dir or CLINICAL_ORIGINALS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid.uuid4().hex[:8]
    ext = file_path.suffix.lower()
    archive_name = f"{record_date.isoformat()}_{record_type}_{uid}{ext}"
    archive_path = out_dir / archive_name

    shutil.copy2(str(file_path), str(archive_path))
    log.info("Archived: %s -> %s", file_path.name, archive_name)
    return archive_path


def prepare_metadata(
    file_path: Path | None,
    record_type: str,
    record_date: date,
    source_format: str,
    raw_text: str = "",
    image_b64: str = "",
    media_type: str = "",
    manual_data: dict | None = None,
    archive_path: Path | None = None,
    incoming_dir: Path | None = None,
    subject: str = OWNER_SUBJECT,
) -> Path:
    ""



    inc_dir = incoming_dir or CLINICAL_INCOMING_DIR
    inc_dir.mkdir(parents=True, exist_ok=True)

    record_id = str(uuid.uuid4())
    meta = {
        "record_id": record_id,
        "date": record_date.isoformat(),
        "type": record_type,
        "source_format": source_format,
        "source_file": str(archive_path) if archive_path else None,
        "original_filename": file_path.name if file_path else None,
        "raw_text": raw_text,
        "image_b64": image_b64,
        "media_type": media_type,
        "manual_data": manual_data,
        "subject": subject,
    }

    meta_path = inc_dir / f"{record_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    log.info("Metadata saved: %s", meta_path.name)
    return meta_path


def ingest_file(
    file_path: Path,
    record_type: str,
    record_date: date | None = None,
    originals_dir: Path | None = None,
    incoming_dir: Path | None = None,
    subject: str = OWNER_SUBJECT,
) -> Path:
    ""



    if record_type not in VALID_TYPES:
        raise ValueError(f"Invalid record type: {record_type}. Must be one of {VALID_TYPES}")

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    rec_date = record_date or date.today()


    archive_path = archive_original(file_path, record_type, rec_date, originals_dir)


    if ext in PDF_EXTENSIONS:
        raw_text = extract_text_from_pdf(file_path)
        return prepare_metadata(
            file_path,
            record_type,
            rec_date,
            "pdf",
            raw_text=raw_text,
            archive_path=archive_path,
            incoming_dir=incoming_dir,
            subject=subject,
        )
    elif ext in IMAGE_EXTENSIONS:
        image_b64 = encode_image_base64(file_path)
        media_type = get_image_media_type(file_path)
        return prepare_metadata(
            file_path,
            record_type,
            rec_date,
            "image",
            image_b64=image_b64,
            media_type=media_type,
            archive_path=archive_path,
            incoming_dir=incoming_dir,
            subject=subject,
        )
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def ingest_manual(
    record_type: str,
    manual_data: dict,
    record_date: date | None = None,
    incoming_dir: Path | None = None,
    subject: str = OWNER_SUBJECT,
) -> Path:
    ""



    if record_type not in VALID_TYPES:
        raise ValueError(f"Invalid record type: {record_type}")

    rec_date = record_date or date.today()
    return prepare_metadata(
        None,
        record_type,
        rec_date,
        "manual",
        manual_data=manual_data,
        incoming_dir=incoming_dir,
        subject=subject,
    )


def main():
    parser = argparse.ArgumentParser(description="Clinical records ingestion — SBK")
    parser.add_argument("--file", type=str, help="Path to PDF or image file")
    parser.add_argument(
        "--type", type=str, required=True, choices=sorted(VALID_TYPES), help="Record type"
    )
    parser.add_argument("--date", type=str, help="Record date (YYYY-MM-DD)")
    parser.add_argument("--manual", action="store_true", help="Manual input mode")
    parser.add_argument("--batch", type=str, help="Process all files in directory")
    parser.add_argument(
        "--subject",
        type=str,
        default=OWNER_SUBJECT or None,
        required=not OWNER_SUBJECT,
        help="Whose documents these are (default: your \"owner\" from sbk.config.json, lower case)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    rec_date = date.fromisoformat(args.date) if args.date else None

    if args.manual:
        print(f"Manual input for {args.type}:")
        data = {}
        if args.type == "allergy":
            data["allergen"] = input("  Allergen: ").strip()
            data["severity"] = input("  Severity (mild/moderate/severe): ").strip()
            data["diagnosis_date"] = input("  Diagnosis date (YYYY-MM-DD): ").strip()
        elif args.type == "medication":
            data["medication"] = input("  Medication name: ").strip()
            data["dosage"] = input("  Dosage: ").strip()
            data["start_date"] = input("  Start date (YYYY-MM-DD): ").strip()
            data["end_date"] = input("  End date (YYYY-MM-DD, empty if ongoing): ").strip() or None
        elif args.type == "vaccination":
            data["vaccine"] = input("  Vaccine name: ").strip()
            data["lot"] = input("  Lot number: ").strip()
            data["dose"] = input("  Dose number: ").strip()
        else:
            data["notes"] = input("  Notes: ").strip()

        meta_path = ingest_manual(args.type, data, rec_date, subject=args.subject)
        print(f"Saved: {meta_path}")
    elif args.batch:
        batch_dir = Path(args.batch)
        count = 0
        for f in sorted(batch_dir.iterdir()):
            if f.suffix.lower() in PDF_EXTENSIONS | IMAGE_EXTENSIONS:
                try:
                    ingest_file(f, args.type, rec_date, subject=args.subject)
                    count += 1
                except Exception as e:
                    log.error("Failed to ingest %s: %s", f.name, e)
        print(f"Batch complete: {count} files ingested")
    elif args.file:
        meta_path = ingest_file(Path(args.file), args.type, rec_date, subject=args.subject)
        print(f"Ingested: {meta_path}")
    else:
        parser.print_help()
        sys.exit(1)

    mark_last_run("clinical")


if __name__ == "__main__":
    main()
