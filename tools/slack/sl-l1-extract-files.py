#!/usr/bin/env python3
"""Extract text from files shared in Slack (L1)."""











from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-sl-l1-extract-files")

CONVERSATIONS_DIR = DATA_ROOT / "slack" / "conversations"
DM_DIR = DATA_ROOT / "slack" / "dm"
OUTPUT_DIR = DATA_ROOT / "slack" / "extracted-files"


EXTRACTABLE_MIMES = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _get_slack_token() -> str | None:
    """Your user token (scope files:read): Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""
    import os

    from dotenv import load_dotenv
    from secrets_adapter import get_secret

    load_dotenv(_TOOLS_DIR.parent / ".env", override=True)
    token = get_secret("sbk-slack", "user-token")
    if token and token.startswith("xoxp-"):
        return token
    for var in ("SBK_SLACK_USER_TOKEN", "SLACK_USER_TOKEN"):
        token = os.environ.get(var)
        if token and token.startswith("xoxp-"):
            return token
    return None


def scan_file_references() -> list[dict]:
    ""
    files: list[dict] = []
    seen_ids: set[str] = set()

    from slack_esclusi import IndiceAssente, esclusi

    try:
        fuori = esclusi()
    except IndiceAssente as e:
        log.error(str(e))
        sys.exit(2)

    for d in [CONVERSATIONS_DIR, DM_DIR]:
        if not d.exists():
            continue
        source = "channel" if d == CONVERSATIONS_DIR else "dm"
        for conv_path in sorted(d.glob("*.json")):
            try:
                data = json.loads(conv_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if isinstance(data, dict) and data.get("channel_id") in fuori:
                continue
            msgs = data if isinstance(data, list) else data.get("messages", [])
            channel = conv_path.stem

            for msg in msgs:
                for file_ref in msg.get("files", []):
                    fid = file_ref.get("id", "")
                    if not fid or fid in seen_ids:
                        continue
                    seen_ids.add(fid)

                    mime = file_ref.get("mimetype", "")
                    files.append(
                        {
                            "file_id": fid,
                            "name": file_ref.get("name", ""),
                            "mimetype": mime,
                            "size": file_ref.get("size", 0),
                            "url": file_ref.get("url", "")
                            or file_ref.get("url_private_download", ""),
                            "channel": channel,
                            "source": source,
                            "sender": msg.get("user", ""),
                            "timestamp": msg.get("ts", ""),
                            "thread_ts": msg.get("thread_ts", ""),
                            "extractable": mime in EXTRACTABLE_MIMES,
                        }
                    )

    return files


def download_and_extract(file_ref: dict, token: str, tmp_dir: Path) -> dict | None:
    ""
    import requests

    url = file_ref["url"]
    if not url:
        return None

    fid = file_ref["file_id"]
    fname = file_ref["name"]
    mime = file_ref["mimetype"]


    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("Failed to download %s: HTTP %d", fname, resp.status_code)
            return None
    except Exception as e:
        log.warning("Failed to download %s: %s", fname, e)
        return None


    tmp_file = tmp_dir / f"{fid}_{fname}"
    tmp_file.write_bytes(resp.content)


    text = ""
    try:
        if mime == "application/pdf":
            import pdfplumber

            with pdfplumber.open(tmp_file) as pdf:
                parts = []
                for page in pdf.pages[:30]:
                    t = page.extract_text()
                    if t:
                        parts.append(t)
                text = "\n\n".join(parts)

        elif mime in ("text/plain", "text/csv"):
            text = tmp_file.read_text(encoding="utf-8", errors="replace")

        elif "wordprocessingml" in mime:
            from docx import Document

            doc = Document(str(tmp_file))
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

        elif "spreadsheetml" in mime:
            from openpyxl import load_workbook

            wb = load_workbook(str(tmp_file), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:3]:
                rows = []
                for row in ws.iter_rows(max_row=100, values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    rows.append(" | ".join(cells))
                parts.append(f"Sheet: {ws.title}\n" + "\n".join(rows))
            wb.close()
            text = "\n\n".join(parts)

    except Exception as e:
        log.warning("Failed to extract %s: %s", fname, e)


    tmp_file.unlink(missing_ok=True)

    if not text or len(text) < 10:
        return None

    return {
        "file_id": fid,
        "filename": fname,
        "mimetype": mime,
        "size": file_ref["size"],
        "channel": file_ref["channel"],
        "source": file_ref["source"],
        "sender": file_ref["sender"],
        "timestamp": file_ref["timestamp"],
        "text": text,
        "text_length": len(text),
    }


def main():
    parser = argparse.ArgumentParser(description="DPI-08: Slack Files Extract")
    parser.add_argument(
        "--download", action="store_true", help="Download and extract (default: dry-run)"
    )
    parser.add_argument("--max-files", type=int, default=None, help="Max files to process")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


    all_files = scan_file_references()
    extractable = [f for f in all_files if f["extractable"]]

    log.info("Total file references: %d", len(all_files))
    log.info("Extractable (text): %d", len(extractable))

    from collections import Counter

    mimes = Counter(f["mimetype"] for f in all_files)
    for m, c in mimes.most_common(10):
        log.info("  %s: %d", m or "(empty)", c)

    if not args.download:
        log.info("Dry run complete. Use --download to fetch and extract.")
        return


    token = _get_slack_token()
    if not token:
        log.error(
            "No Slack user token (xoxp-) found. Copy the User OAuth Token of your Slack app into "
            "the Keychain (service sbk-slack, account user-token) or into .env as SLACK_USER_TOKEN."
        )
        return

    if args.max_files:
        extractable = extractable[: args.max_files]


    import tempfile

    tmp_dir = Path(tempfile.mkdtemp(prefix="slack-files-"))
    log.info("Downloading %d files...", len(extractable))

    results: list[dict] = []
    for i, fref in enumerate(extractable):
        result = download_and_extract(fref, token, tmp_dir)
        if result:
            results.append(result)

            channel_dir = OUTPUT_DIR / fref["channel"]
            channel_dir.mkdir(parents=True, exist_ok=True)
            safe_write_json(channel_dir / f"{fref['file_id']}.json", result)

        if (i + 1) % 10 == 0:
            log.info("  Progress: %d/%d", i + 1, len(extractable))
            time.sleep(1.2)


    import shutil

    shutil.rmtree(tmp_dir, ignore_errors=True)


    safe_write_json(
        OUTPUT_DIR / "_extract-stats.json",
        {
            "total_references": len(all_files),
            "extractable": len(extractable),
            "extracted": len(results),
            "total_text_chars": sum(r["text_length"] for r in results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )

    log.info(
        "Done: %d files extracted, %d chars total",
        len(results),
        sum(r["text_length"] for r in results),
    )


if __name__ == "__main__":
    main()
