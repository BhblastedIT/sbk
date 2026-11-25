#!/usr/bin/env python3
"""Backfill attachment metadata columns on existing L0 messages parquet files."""













import argparse
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

BATCH_SIZE = 20
BATCH_DELAY = 1.5
MAX_RETRIES = 3

log = logging.getLogger("att-backfill")


def new_service(account_name: str):
    accounts = json.loads(ACCOUNTS_FILE.read_text())
    acc = accounts.get(account_name, {})

    refresh_token = get_secret("sbk-gmail", account_name)
    if not refresh_token:
        refresh_token = acc.get("refresh_token", "")

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


def extract_attachments(payload: dict) -> list:
    ""
    atts = []
    for part in payload.get("parts", []):
        fn = part.get("filename", "")
        if fn:
            atts.append(
                {
                    "filename": fn,
                    "mime_type": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                    "attachment_id": part.get("body", {}).get("attachmentId", ""),
                }
            )
        if "parts" in part:
            atts.extend(extract_attachments(part))
    return atts


def backfill_account(account_name: str, dry_run: bool = False, num_workers: int = 6):
    ""
    pq_path = DATA_DIR / account_name / "messages.parquet"
    if not pq_path.exists():
        log.warning(f"No messages.parquet for '{account_name}'")
        return

    df = pd.read_parquet(pq_path)
    log.info(f"[{account_name}] Loaded {len(df)} messages")


    if "has_attachments" in df.columns:
        filled = df["has_attachments"].notna().sum()
        log.info(f"[{account_name}] Already has attachment columns ({filled}/{len(df)} filled)")
        if filled == len(df):
            log.info(f"[{account_name}] Fully backfilled, skipping")
            return

    msg_ids = df["id"].tolist()
    log.info(
        f"[{account_name}] Fetching attachment metadata for {len(msg_ids)} messages with {num_workers} workers..."
    )

    if dry_run:
        log.info(f"[{account_name}] --dry-run, would fetch {len(msg_ids)} messages")
        return


    att_map = {}
    _lock = threading.Lock()
    _stats = {"ok": 0, "err": 0}
    t0 = time.time()
    total = len(msg_ids)

    def _worker_fn(worker_id, ids_chunk):
        worker_svc = new_service(account_name)
        time.sleep(worker_id * 0.5)

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
                    worker_svc.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="full",
                        fields="id,payload(mimeType,parts(filename,mimeType,body(size,attachmentId),parts))",
                    ),
                    callback=make_cb(mid),
                    request_id=mid,
                )

            try:
                batch.execute()
            except HttpError as e:
                if e.resp.status == 429:
                    time.sleep(30)
                    try:
                        batch.execute()
                    except Exception:
                        with _lock:
                            _stats["err"] += len(batch_ids)
                        continue
                else:
                    with _lock:
                        _stats["err"] += len(batch_ids)
                    continue
            except Exception:
                with _lock:
                    _stats["err"] += len(batch_ids)
                continue

            with _lock:
                for mid, resp in results.items():
                    att_map[mid] = extract_attachments(resp.get("payload", {}))
                    _stats["ok"] += 1
                _stats["err"] += len(batch_ids) - len(results)

                done = _stats["ok"] + _stats["err"]
                if done % 400 == 0 and done > 0:
                    elapsed = time.time() - t0
                    rate = _stats["ok"] / elapsed if elapsed > 0 else 0
                    left = (total - done) / rate / 60 if rate > 0 else 0
                    log.info(
                        f"  [{done}/{total}] {_stats['ok']} ok, {_stats['err']} err | "
                        f"{rate:.1f}/s, ~{left:.0f}m left"
                    )

            time.sleep(BATCH_DELAY)


    worker_chunks = [[] for _ in range(num_workers)]
    for idx, mid in enumerate(msg_ids):
        worker_chunks[idx % num_workers].append(mid)

    log.info(f"[{account_name}] Launching {num_workers} workers...")
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(_worker_fn, w, worker_chunks[w]): w for w in range(num_workers)}
        for future in as_completed(futures):
            w = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"Worker {w} crashed: {e}")

    elapsed = time.time() - t0
    log.info(
        f"[{account_name}] Fetched {_stats['ok']} messages in {elapsed / 60:.1f} min ({_stats['err']} errors)"
    )


    df["has_attachments"] = df["id"].map(lambda mid: len(att_map.get(mid, [])) > 0)
    df["attachment_count"] = df["id"].map(lambda mid: len(att_map.get(mid, [])))
    df["attachments_json"] = df["id"].map(
        lambda mid: json.dumps(att_map.get(mid, []), ensure_ascii=False) if att_map.get(mid) else ""
    )


    with_atts = df["has_attachments"].sum()
    total_atts = df["attachment_count"].sum()
    log.info(
        f"[{account_name}] {with_atts} messages with attachments, {total_atts} total attachments"
    )


    safe_write_parquet(df, pq_path, index=False)
    log.info(
        f"[{account_name}] Saved updated messages.parquet ({len(df)} rows, {len(df.columns)} columns)"
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill attachment metadata — SBK")
    parser.add_argument("--account", help="Single account to backfill")
    parser.add_argument("--all", action="store_true", help="Backfill all accounts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers (default 6)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.account and not args.all:
        parser.error("Specify --account NAME or --all")

    if args.all:
        accounts = [
            d.name for d in DATA_DIR.iterdir() if d.is_dir() and (d / "messages.parquet").exists()
        ]
        log.info(f"Backfilling {len(accounts)} accounts: {', '.join(accounts)}")
    else:
        accounts = [args.account]

    for acc in accounts:
        backfill_account(acc, dry_run=args.dry_run, num_workers=args.workers)

    log.info("Backfill complete.")


if __name__ == "__main__":
    main()
