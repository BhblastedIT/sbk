#!/usr/bin/env python3
"""Download Gmail attachments (filtered by extension, size and date) into per-account folders with an index."""









import argparse
import base64
import hashlib
import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import EMAILS_DIR, safe_write_parquet  # noqa: E402

DATA_DIR = EMAILS_DIR
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


DEFAULT_MONTHS = 24
MAX_SIZE = 25 * 1024 * 1024
ALLOWED_EXTS = {

    "pdf",
    "docx",
    "doc",
    "xlsx",
    "xls",
    "pptx",
    "ppt",
    "csv",
    "txt",
    "rtf",
    "odt",
    "ods",
    "odp",

    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "bmp",
    "tiff",
    "tif",
    "svg",
    "heic",

    "zip",
    "rar",
    "7z",
    "tar",
    "gz",

    "json",
    "xml",
    "html",
    "eml",
    "msg",
    "ics",
}
BATCH_SIZE = 20
BATCH_DELAY = 1.5

log = logging.getLogger("gmail-att")


def new_service(account_name: str):
    accounts = json.loads(ACCOUNTS_FILE.read_text())
    acc = accounts.get(account_name, {})


    refresh_token = get_secret("sbk-gmail", account_name)
    if not refresh_token:
        refresh_token = acc.get("refresh_token", "")
        if refresh_token:
            log.warning(
                f"Using plaintext refresh_token for '{account_name}'. "
                f"Sign in again to move it to the Keychain: uv run python tools/email/em-l0-auth.py {account_name}"
            )


    import google_oauth  # your OAuth client: .env or its JSON file

    client_id, client_secret = google_oauth.client_id_secret()
    client_id = client_id or acc.get("client_id", "")
    client_secret = client_secret or acc.get("client_secret", "")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


def list_ids_with_attachments(svc, query: str) -> list:
    ids = []
    page_token = None
    while True:
        params = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        resp = svc.users().messages().list(**params).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def get_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def dedup_key(filename: str, size: int) -> str:
    return hashlib.md5(f"{filename.lower()}:{size}".encode()).hexdigest()


def scan_parts(payload: dict, depth: int = 0) -> list:
    ""
    atts = []
    for part in payload.get("parts", []):
        fn = part.get("filename", "")
        if fn:
            ext = get_ext(fn)
            size = part.get("body", {}).get("size", 0)
            att_id = part.get("body", {}).get("attachmentId", "")
            atts.append(
                {
                    "filename": fn,
                    "ext": ext,
                    "size": size,
                    "attachment_id": att_id,
                    "mime": part.get("mimeType", ""),
                }
            )
        if "parts" in part:
            atts.extend(scan_parts(part, depth + 1))
    return atts


def download_attachment(svc, msg_id: str, att_id: str) -> bytes:
    ""
    for attempt in range(3):
        try:
            resp = (
                svc.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=att_id)
                .execute()
            )
            data = resp.get("data", "")
            return base64.urlsafe_b64decode(data + "==")
        except HttpError as e:
            if e.resp.status == 429 and attempt < 2:
                wait = 10 * (2**attempt)
                log.warning(f"429, waiting {wait}s")
                time.sleep(wait)
            else:
                raise


def main():
    parser = argparse.ArgumentParser(description="Gmail attachment downloader — SBK")
    parser.add_argument("--account", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Scan only, don't download")
    parser.add_argument(
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help=f"Lookback period in months (default {DEFAULT_MONTHS})",
    )
    parser.add_argument("--since", default=None, help="Start date YYYY-MM-DD (overrides --months)")
    parser.add_argument(
        "--all-time", action="store_true", help="Download all attachments (no date filter)"
    )
    parser.add_argument(
        "--workers", type=int, default=6, help="Parallel download workers (default 6)"
    )
    args = parser.parse_args()

    att_dir = DATA_DIR / args.account / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    svc = new_service(args.account)
    now = datetime.now(UTC)


    if args.all_time:
        query = "has:attachment"
        log.info("Listing ALL messages with attachments (no date filter)...")
    elif args.since:
        cutoff_str = args.since.replace("-", "/")
        query = f"has:attachment after:{cutoff_str}"
        log.info(f"Listing messages with attachments (after {cutoff_str})...")
    else:
        cutoff = now - pd.Timedelta(days=args.months * 30)
        cutoff_str = cutoff.strftime("%Y/%m/%d")
        query = f"has:attachment after:{cutoff_str}"
        log.info(f"Listing messages with attachments (after {cutoff_str})...")

    all_ids = list_ids_with_attachments(svc, query)
    log.info(f"Total messages to scan: {len(all_ids)}")


    num_workers = min(max(args.workers, 1), 10)
    log.info(f"Scanning for matching attachments with {num_workers} workers...")

    _scan_lock = threading.Lock()
    _scan_results = []
    _scan_keys = set()
    _scan_stats = {"scanned": 0}

    def _scan_worker(worker_id, ids_chunk):
        worker_svc = new_service(args.account)
        time.sleep(worker_id * 0.3)
        local_results = []

        for i in range(0, len(ids_chunk), BATCH_SIZE):
            batch_ids = ids_chunk[i : i + BATCH_SIZE]
            results = {}

            def make_cb(mid):
                def cb(rid, resp, exc):
                    if not exc:
                        results[mid] = resp

                return cb

            batch = worker_svc.new_batch_http_request()
            for mid in batch_ids:
                batch.add(
                    worker_svc.users().messages().get(userId="me", id=mid, format="full"),
                    callback=make_cb(mid),
                    request_id=mid,
                )
            try:
                batch.execute()
            except Exception:
                time.sleep(5)
                try:
                    batch.execute()
                except Exception:
                    continue

            for mid, resp in results.items():
                ts_ms = int(resp.get("internalDate", 0))
                msg_date = datetime.fromtimestamp(ts_ms / 1000, tz=UTC) if ts_ms else None

                for att in scan_parts(resp.get("payload", {})):
                    ext = att["ext"]
                    size = att["size"]
                    if ext not in ALLOWED_EXTS:
                        continue
                    if size > MAX_SIZE:
                        continue
                    dk = dedup_key(att["filename"], size)
                    with _scan_lock:
                        if dk in _scan_keys:
                            continue
                        _scan_keys.add(dk)
                    if att["attachment_id"]:
                        local_results.append((mid, att, msg_date))

            with _scan_lock:
                _scan_stats["scanned"] += len(batch_ids)
                done = _scan_stats["scanned"]
                if done % 200 == 0 and done > 0:
                    log.info(
                        f"  Scanned {done}/{len(all_ids)}, found {len(_scan_results) + len(local_results)} so far"
                    )

            time.sleep(max(0.2, BATCH_DELAY / num_workers))

        with _scan_lock:
            _scan_results.extend(local_results)

    scan_chunks = [[] for _ in range(num_workers)]
    for idx, mid in enumerate(all_ids):
        scan_chunks[idx % num_workers].append(mid)

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_scan_worker, w, scan_chunks[w]): w for w in range(num_workers)}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log.error(f"Scan worker crashed: {e}")

    to_download = _scan_results
    log.info(f"Scan complete: {len(to_download)} attachments found")


    total_size = sum(a["size"] for _, a, _ in to_download)
    by_ext = {}
    for _, a, _ in to_download:
        e = a["ext"]
        by_ext.setdefault(e, {"count": 0, "bytes": 0})
        by_ext[e]["count"] += 1
        by_ext[e]["bytes"] += a["size"]

    log.info(f"\nAttachments to download: {len(to_download)}")
    log.info(f"Total size: {total_size / 1e6:.0f} MB")
    for ext, v in sorted(by_ext.items(), key=lambda x: -x[1]["bytes"]):
        log.info(f"  {ext}: {v['count']} files, {v['bytes'] / 1e6:.0f} MB")

    if args.dry_run:
        log.info("--dry-run, stopping")
        return


    num_workers = min(max(args.workers, 1), 10)
    log.info(f"\nDownloading {len(to_download)} attachments with {num_workers} workers...")


    needed_exts = {att["ext"] for _, att, _ in to_download}
    for ext in needed_exts:
        (att_dir / ext).mkdir(exist_ok=True)


    _lock = threading.Lock()
    _stats = {"ok": 0, "err": 0, "skipped": 0}
    index_rows = []
    t0 = time.time()

    def _download_one(item, worker_svc):
        msg_id, att, msg_date = item
        ext = att["ext"]
        fn = att["filename"]
        safe_fn = re.sub(r"[^\w\s\-\.]", "_", fn)[:100]
        date_prefix = msg_date.strftime("%Y%m%d") if msg_date else "nodate"
        dest = att_dir / ext / f"{date_prefix}_{safe_fn}"

        row = {
            "msg_id": msg_id,
            "filename": fn,
            "ext": ext,
            "size": att["size"],
            "date": msg_date,
            "path": str(dest),
        }


        if dest.exists() and dest.stat().st_size > 0:
            with _lock:
                _stats["skipped"] += 1
                _stats["ok"] += 1
                index_rows.append(row)
            return

        try:
            data = download_attachment(worker_svc, msg_id, att["attachment_id"])
            dest.write_bytes(data)
            row["size"] = len(data)
            with _lock:
                _stats["ok"] += 1
                index_rows.append(row)
        except Exception as e:
            with _lock:
                _stats["err"] += 1
            log.warning(f"Failed {fn}: {e}")


    def _worker_fn(worker_id, items):
        worker_svc = new_service(args.account)
        time.sleep(worker_id * 0.3)
        for item in items:
            _download_one(item, worker_svc)
            time.sleep(0.15)

            with _lock:
                done = _stats["ok"] + _stats["err"]
            if done % 100 == 0 and done > 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                left = (len(to_download) - done) / rate / 60 if rate > 0 else 0
                log.info(
                    f"  [{done}/{len(to_download)}] {_stats['ok']} ok "
                    f"({_stats['skipped']} cached), {_stats['err']} err | "
                    f"{rate:.1f}/s, ~{left:.0f}m left"
                )


    worker_items = [[] for _ in range(num_workers)]
    for idx, item in enumerate(to_download):
        worker_items[idx % num_workers].append(item)

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_worker_fn, w, worker_items[w]): w for w in range(num_workers)}
        for future in as_completed(futures):
            w = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"Worker {w} crashed: {e}")

    elapsed = time.time() - t0
    log.info(
        f"Done: {_stats['ok']} downloaded ({_stats['skipped']} cached), "
        f"{_stats['err']} errors, {elapsed / 60:.1f} min"
    )


    if index_rows:
        idx_df = pd.DataFrame(index_rows)
        idx_path = att_dir / "index.parquet"
        safe_write_parquet(idx_df, idx_path, index=False)
        log.info(f"Index saved: {len(idx_df)} rows -> {idx_path}")


    total_disk = sum(
        f.stat().st_size for f in att_dir.rglob("*") if f.is_file() and f.name != "index.parquet"
    )
    log.info(f"Total on disk: {total_disk / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
