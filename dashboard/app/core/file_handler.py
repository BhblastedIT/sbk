""





from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sbk_config import DATA_ROOT

logger = logging.getLogger("dashboard.chat")

UPLOAD_DIR = DATA_ROOT / "chat-uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024

ALLOWED_TYPES = {

    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",

    "application/pdf",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
}

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


_upload_meta: dict[str, dict[str, Any]] = {}


async def process_upload(file, conv_id: str) -> dict:
    ""



    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    size = len(content)

    if size > MAX_FILE_SIZE:
        mb = MAX_FILE_SIZE // 1024 // 1024
        return {"error": f"File too large ({size // 1024 // 1024}MB). Max {mb}MB."}

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_TYPES:
        return {"error": f"Unsupported file type: {content_type}"}

    file_id = str(uuid.uuid4())
    conv_dir = UPLOAD_DIR / conv_id
    conv_dir.mkdir(parents=True, exist_ok=True)


    safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in (file.filename or "file"))
    file_path = conv_dir / f"{file_id}_{safe_name}"
    file_path.write_bytes(content)

    meta = {
        "id": file_id,
        "filename": file.filename or safe_name,
        "content_type": content_type,
        "size": size,
        "path": str(file_path),
        "conv_id": conv_id,
        "created": datetime.now(UTC).isoformat(),
    }
    _upload_meta[file_id] = meta

    return {
        "id": file_id,
        "filename": meta["filename"],
        "content_type": content_type,
        "size": size,
    }


def get_content_blocks(attachment_ids: list[str]) -> list[dict]:
    ""




    blocks: list[dict] = []
    for aid in attachment_ids:
        meta = _upload_meta.get(aid)
        if not meta:
            continue

        file_path = Path(meta["path"])
        if not file_path.exists():
            continue

        content_type = meta["content_type"]
        filename = meta["filename"]

        if content_type in IMAGE_TYPES:
            raw = file_path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": b64,
                    },
                }
            )
        elif content_type == "application/pdf":
            text = _extract_pdf_text(file_path)
            if text:
                blocks.append({"type": "text", "text": f"--- Attachment: {filename} ---\n{text}"})
            else:
                blocks.append(
                    {
                        "type": "text",
                        "text": f"--- Attachment: {filename} (empty or unreadable PDF) ---",
                    }
                )
        else:

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                blocks.append({"type": "text", "text": f"--- Attachment: {filename} ---\n{text}"})
            except Exception:
                blocks.append(
                    {
                        "type": "text",
                        "text": f"--- Attachment: {filename} (unreadable) ---",
                    }
                )

    return blocks


def _extract_pdf_text(path: Path) -> str:
    ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("pypdf not installed. PDF text extraction unavailable.")
        return "[pypdf not installed -- install with: pip install pypdf]"
    except Exception as e:
        logger.warning("PDF extraction error %s: %s", path, e)
        return ""


def cleanup_old_uploads(max_age_hours: int = 24) -> int:
    ""
    if not UPLOAD_DIR.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    removed = 0

    for conv_dir in UPLOAD_DIR.iterdir():
        if not conv_dir.is_dir():
            continue
        for fp in conv_dir.iterdir():
            if fp.is_file():
                try:
                    mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=UTC)
                    if mtime < cutoff:
                        fp.unlink()
                        removed += 1
                except OSError:
                    continue

        try:
            if not any(conv_dir.iterdir()):
                conv_dir.rmdir()
        except OSError:
            pass


    stale_ids = [aid for aid, m in _upload_meta.items() if not Path(m["path"]).exists()]
    for aid in stale_ids:
        del _upload_meta[aid]

    return removed
