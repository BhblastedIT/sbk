#!/usr/bin/env python3
"""Gmail bulk downloader (OAuth): lists message ids, downloads full messages in parallel chunks and merges them into a parquet."""











import argparse
import base64
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import (  # noqa: E402
    EMAILS_DIR,
    acquire_pid_lock,
    get_auto_since,
    mark_last_run,
    safe_write_parquet,
)

DATA_DIR = EMAILS_DIR
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PAGE_SIZE = 500
SAVE_EVERY = 500
MAX_RETRIES = 3
BODY_TEXT_MAX_CHARS = 200_000


SINGLE_BATCH = 20
SINGLE_DELAY = 1.5
MULTI_BATCH = 10
MULTI_DELAY = 2.0

log = logging.getLogger("gmail-dl")


_progress_lock = threading.Lock()
_progress = {"ok": 0, "err": 0, "total": 0, "t0": 0.0}


def _log_progress(worker_id: int):
    with _progress_lock:
        ok = _progress["ok"]
        err = _progress["err"]
        total = _progress["total"]
        elapsed = time.time() - _progress["t0"]
    rate = ok / elapsed if elapsed > 0 else 0
    done = ok + err
    left = (total - done) / rate / 60 if rate > 0 else 0
    log.info(
        f"[W{worker_id}] [{done}/{total}] {ok} ok, {err} err | {rate:.1f}/s, ~{left:.0f}m left"
    )





def load_accounts() -> dict:
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text())
    return {}


def build_creds(account_name: str) -> Credentials:
    ""







    accounts = load_accounts()
    if account_name not in accounts:
        print(f"Account '{account_name}' not found in {ACCOUNTS_FILE}")
        print(f"Available: {', '.join(accounts.keys()) or '(none)'}")
        print("Sign it in: uv run python tools/email/em-l0-auth.py <label>")
        sys.exit(1)

    acc = accounts[account_name]


    refresh_token = get_secret("sbk-gmail", account_name)
    if refresh_token:
        log.debug(f"Using refresh_token from Keychain for '{account_name}'")
    elif acc.get("refresh_token"):
        refresh_token = acc["refresh_token"]
        log.warning(
            f"Using refresh_token from accounts.json (plaintext) for '{account_name}'. "
            f"Sign in again to move it to the Keychain: uv run python tools/email/em-l0-auth.py {account_name}"
        )
    else:
        print(f"No refresh_token found for '{account_name}' (Keychain or accounts.json)")
        sys.exit(1)


    import google_oauth  # your OAuth client: .env or its JSON file

    client_id, client_secret = google_oauth.client_id_secret()
    client_id = client_id or acc.get("client_id", "")
    client_secret = client_secret or acc.get("client_secret", "")

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def new_service(account_name: str):
    ""
    return build("gmail", "v1", credentials=build_creds(account_name))







EXCLUDE_SPAM = "-in:spam"


def list_all_ids(service, query: str) -> list:
    ""
    ids = []
    page_token = None

    while True:
        params = {
            "userId": "me",
            "maxResults": PAGE_SIZE,
            "includeSpamTrash": True,
            "q": " ".join(x for x in (query, EXCLUDE_SPAM) if x),
        }
        if page_token:
            params["pageToken"] = page_token

        resp = service.users().messages().list(**params).execute()
        batch = resp.get("messages", [])
        ids.extend(m["id"] for m in batch)

        est = resp.get("resultSizeEstimate", "?")
        log.info(f"  Listed {len(ids)} IDs so far (estimate ~{est})")

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return ids





def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")


class _HTMLStripper(HTMLParser):
    ""

    _BLOCK_TAGS = frozenset(
        ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote")
    )
    _SKIP_TAGS = frozenset(("style", "script", "head"))

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip = True
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS:
            self._skip = False
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def handle_entityref(self, name):
        if not self._skip:
            from html import unescape

            self._parts.append(unescape(f"&{name};"))

    def handle_charref(self, name):
        if not self._skip:
            from html import unescape

            self._parts.append(unescape(f"&#{name};"))

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts)).strip()


def _strip_html(html: str) -> str:
    ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:

        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s{3,}", "\n\n", text).strip()


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


def extract_body(payload: dict) -> str:
    ""
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return _decode_b64(data) if data else ""

    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        return _strip_html(_decode_b64(data)) if data else ""

    plain, html = "", ""
    for part in payload.get("parts", []):
        pm = part.get("mimeType", "")
        if pm == "text/plain" and not plain:
            data = part.get("body", {}).get("data", "")
            if data:
                plain = _decode_b64(data)
        elif pm == "text/html" and not html:
            data = part.get("body", {}).get("data", "")
            if data:
                html = _decode_b64(data)
        elif pm.startswith("multipart/"):
            nested = extract_body(part)
            if nested and not plain:
                plain = nested

    return plain if plain else (_strip_html(html) if html else "")





def parse_message(raw: dict) -> dict:
    ""
    headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
    labels = raw.get("labelIds", [])
    ts_ms = int(raw.get("internalDate", 0))
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC) if ts_ms else None

    payload = raw.get("payload", {})
    atts = extract_attachments(payload)

    return {
        "id": raw["id"],
        "thread_id": raw.get("threadId", ""),
        "date": dt,
        "from_addr": headers.get("from", ""),
        "to_addr": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "bcc": headers.get("bcc", ""),
        "subject": headers.get("subject", ""),
        "body_text": (body := extract_body(payload))[:BODY_TEXT_MAX_CHARS],
        "body_truncated": len(body) > BODY_TEXT_MAX_CHARS,
        "labels": ",".join(labels),
        "message_id": headers.get("message-id", ""),
        "in_reply_to": headers.get("in-reply-to", ""),
        "snippet": raw.get("snippet", ""),
        "has_attachments": len(atts) > 0,
        "attachment_count": len(atts),
        "attachments_json": json.dumps(atts, ensure_ascii=False) if atts else "",


        "list_unsubscribe": headers.get("list-unsubscribe", "")[:500],
        "list_id": headers.get("list-id", "")[:300],
        "precedence": headers.get("precedence", "")[:50],
        "auto_submitted": headers.get("auto-submitted", "")[:50],
    }





def load_done_ids(account_dir: Path) -> set:
    ""
    done = set()

    corrupted_files = []
    main_pq = account_dir / "messages.parquet"
    if main_pq.exists():
        try:
            done.update(pd.read_parquet(main_pq, columns=["id"])["id"].tolist())
        except Exception as e:
            log.warning(
                "Corrupted Parquet (will re-download affected messages): %s: %s", main_pq, e
            )
            corrupted_files.append(str(main_pq))

    chunks_dir = account_dir / "chunks"
    if chunks_dir.exists():
        for f in sorted(chunks_dir.glob("*.parquet")):
            try:
                done.update(pd.read_parquet(f, columns=["id"])["id"].tolist())
            except Exception as e:
                log.warning("Corrupted chunk Parquet: %s: %s", f, e)
                corrupted_files.append(str(f))

    if corrupted_files:
        log.warning("Found %d corrupted Parquet file(s) in %s", len(corrupted_files), account_dir)
    return done


def merge_chunks(account_dir: Path):
    ""
    chunks_dir = account_dir / "chunks"
    main_pq = account_dir / "messages.parquet"

    parts = []
    if main_pq.exists():
        parts.append(pd.read_parquet(main_pq))

    if chunks_dir.exists():
        for f in sorted(chunks_dir.glob("*.parquet")):
            parts.append(pd.read_parquet(f))

    if not parts:
        return

    merged = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["id"])
    merged.sort_values("date", ascending=False, inplace=True)
    safe_write_parquet(merged, main_pq, index=False)
    log.info(f"Merged {len(merged)} messages → {main_pq}")

    if chunks_dir.exists():
        for f in chunks_dir.glob("*.parquet"):
            f.unlink()
        try:
            chunks_dir.rmdir()
        except OSError:
            pass





def fetch_one(service, msg_id: str) -> dict:
    ""
    for attempt in range(MAX_RETRIES):
        try:
            return service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        except HttpError as e:
            if e.resp.status == 429 and attempt < MAX_RETRIES - 1:
                wait = 10 * (2**attempt)
                log.warning(f"429 on {msg_id}, waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
            else:
                raise
    return {}





def download_worker(
    worker_id: int,
    account_name: str,
    msg_ids: list,
    chunks_dir: Path,
    batch_size: int,
    batch_delay: float,
    run_tag: str = "",
) -> dict:
    ""






    tagp = f"{run_tag}_" if run_tag else ""
    service = new_service(account_name)
    tag = f"W{worker_id}"


    time.sleep(worker_id * 0.5)

    rows = []
    ok = 0
    failed = []
    chunk_num = 0
    total = len(msg_ids)

    log.info(f"[{tag}] Starting: {total} messages, batch={batch_size}")

    for i in range(0, total, batch_size):
        batch_ids = msg_ids[i : i + batch_size]
        results = {}
        errors = {}

        def make_cb(mid):
            def cb(request_id, response, exception):
                if exception:
                    errors[mid] = exception
                else:
                    results[mid] = response

            return cb

        batch_req = service.new_batch_http_request()
        for mid in batch_ids:
            batch_req.add(
                service.users().messages().get(userId="me", id=mid, format="full"),
                callback=make_cb(mid),
                request_id=mid,
            )

        try:
            batch_req.execute()
        except Exception as e:
            log.warning(f"[{tag}] Batch failed: {e} — sequential fallback")
            time.sleep(5)
            for mid in batch_ids:
                if mid in results:
                    continue
                try:
                    results[mid] = fetch_one(service, mid)
                    time.sleep(0.5)
                except Exception as ex:
                    errors[mid] = ex


        fail_before = len(failed)
        retry_ids = []
        for mid, exc in errors.items():
            if isinstance(exc, HttpError) and exc.resp.status == 429:
                retry_ids.append(mid)
            else:
                failed.append(mid)

        if retry_ids:
            time.sleep(5)
            for mid in retry_ids:
                try:
                    results[mid] = fetch_one(service, mid)
                    time.sleep(0.5)
                except Exception:
                    failed.append(mid)


        batch_ok = 0
        for mid, resp in results.items():
            try:
                rows.append(parse_message(resp))
                ok += 1
                batch_ok += 1
            except Exception:
                failed.append(mid)

        batch_err = len(failed) - fail_before
        with _progress_lock:
            _progress["ok"] += batch_ok
            _progress["err"] += batch_err

        if (i // batch_size) % 5 == 0:
            _log_progress(worker_id)


        if len(rows) >= SAVE_EVERY:
            p = chunks_dir / f"w{worker_id}_{tagp}{chunk_num:04d}.parquet"
            safe_write_parquet(pd.DataFrame(rows), p, index=False)
            log.info(f"[{tag}] Saved {len(rows)} → {p.name}")
            chunk_num += 1
            rows = []

        time.sleep(batch_delay)


    if rows:
        p = chunks_dir / f"w{worker_id}_{tagp}{chunk_num:04d}.parquet"
        safe_write_parquet(pd.DataFrame(rows), p, index=False)
        log.info(f"[{tag}] Saved {len(rows)} → {p.name}")
        chunk_num += 1


    if failed:
        log.info(f"[{tag}] Retrying {len(failed)} failed...")
        retry_rows = []
        still_failed = []
        for mid in failed:
            try:
                resp = fetch_one(service, mid)
                retry_rows.append(parse_message(resp))
                time.sleep(0.5)
            except Exception as e:
                log.warning("[%s] Retry failed for message %s: %s", tag, mid, e)
                still_failed.append(mid)
        if retry_rows:
            p = chunks_dir / f"w{worker_id}_{tagp}retry.parquet"
            safe_write_parquet(pd.DataFrame(retry_rows), p, index=False)
            ok += len(retry_rows)
            failed = failed[: -len(retry_rows)]

    log.info(f"[{tag}] Done: {ok} ok, {len(failed)} failed")
    return {"worker": worker_id, "ok": ok, "failed": len(failed)}





def download(account_name: str, ids: list, done: set, account_dir: Path, num_workers: int):
    todo = [mid for mid in ids if mid not in done]
    total = len(todo)
    log.info(f"{total} to download, {len(done)} already done")

    if not total:
        log.info("Nothing new to download!")
        return

    chunks_dir = account_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)


    if num_workers == 1:
        batch_size = SINGLE_BATCH
        batch_delay = SINGLE_DELAY
    else:
        batch_size = MULTI_BATCH
        batch_delay = MULTI_DELAY


    run_tag = f"{datetime.now():%Y%m%d%H%M%S}-{os.getpid()}"


    _progress["ok"] = 0
    _progress["err"] = 0
    _progress["total"] = total
    _progress["t0"] = time.time()


    worker_ids = [[] for _ in range(num_workers)]
    for idx, mid in enumerate(todo):
        worker_ids[idx % num_workers].append(mid)

    for w in range(num_workers):
        log.info(f"Worker {w}: {len(worker_ids[w])} messages")

    if num_workers == 1:

        download_worker(
            0, account_name, worker_ids[0], chunks_dir, batch_size, batch_delay, run_tag
        )
    else:

        log.info(f"Launching {num_workers} parallel workers...")
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {
                pool.submit(
                    download_worker,
                    w,
                    account_name,
                    worker_ids[w],
                    chunks_dir,
                    batch_size,
                    batch_delay,
                    run_tag,
                ): w
                for w in range(num_workers)
            }

            for future in as_completed(futures):
                w = futures[future]
                try:
                    result = future.result()
                    log.info(f"Worker {w} finished: {result}")
                except Exception as e:
                    log.error(f"Worker {w} crashed: {e}")

    elapsed = time.time() - _progress["t0"]
    log.info(f"All workers done in {elapsed / 60:.1f} min")


    log.info("Merging all chunks into messages.parquet...")
    merge_chunks(account_dir)





def main():
    parser = argparse.ArgumentParser(description="Gmail bulk downloader — SBK")
    parser.add_argument("--account", help="Label of one mailbox (e.g. work)")
    parser.add_argument(
        "--all", action="store_true", help="Every mailbox signed in (emails/accounts.json)"
    )
    parser.add_argument(
        "--since", default=None, help="Start date YYYY-MM-DD (default: auto from last run)"
    )
    parser.add_argument("--until", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--query", default="", help="Extra Gmail search filter")
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel workers (default 1, max 5)"
    )
    parser.add_argument("--force", action="store_true", help="Full refresh from 2020-01-01")
    parser.add_argument("--dry-run", action="store_true", help="List IDs only, don't download")
    args = parser.parse_args()
    # Take the lock only after the arguments are parsed, so --help writes nothing.
    if not acquire_pid_lock("em-l0-download", logger=log):
        log.warning("Another instance is running, exiting")
        sys.exit(75)
    if not args.account and not args.all:
        parser.error("give --account <label> or --all")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.all:
        download_account(args, args.account)
        return

    labels = list(load_accounts())
    if not labels:
        log.error(
            f"No mailbox signed in ({ACCOUNTS_FILE} is missing or empty). "
            "Sign one in: uv run python tools/email/em-l0-auth.py <label>. Nothing downloaded."
        )
        sys.exit(1)
    failed = []
    for label in labels:
        try:
            download_account(args, label)
        except SystemExit as e:
            if e.code not in (0, None):
                failed.append(label)
        except Exception as e:  # noqa: BLE001 -- one mailbox does not stop the others
            log.error(f"{label}: {type(e).__name__}: {e}")
            failed.append(label)
    if failed:
        log.error(f"Mailboxes with errors (not marked): {', '.join(failed)}")
        sys.exit(1)


def download_account(args, account: str):
    ""
    num_workers = min(max(args.workers, 1), 5)


    if args.since is not None:
        since = args.since
        since_label = f"Custom range: since {since}"
    elif args.force:
        since = "2020-01-01"
        since_label = "Full refresh: --force"
    else:
        since = get_auto_since(f"email-{account}")
        since_label = f"Incremental: since {since} (auto from last run)"


    account_dir = DATA_DIR / account
    account_dir.mkdir(parents=True, exist_ok=True)

    file_log = logging.FileHandler(account_dir / "download.log")
    file_log.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    logging.getLogger().addHandler(file_log)
    try:
        _download_account(args, account, account_dir, since, since_label, num_workers)
    finally:
        logging.getLogger().removeHandler(file_log)
        file_log.close()


def _download_account(args, account, account_dir, since, since_label, num_workers):
    log.info(since_label)


    q = f"after:{since.replace('-', '/')}"
    if args.until:
        q += f" before:{args.until.replace('-', '/')}"
    if args.query:
        q += f" {args.query}"

    log.info(f"Account: {account} | Workers: {num_workers} | Query: {q}")

    service = new_service(account)


    profile = service.users().getProfile(userId="me").execute()
    log.info(
        f"Connected: {profile['emailAddress']} | "
        f"Total messages: {profile.get('messagesTotal', '?')}"
    )



    expected = (load_accounts().get(account) or {}).get("email", "").lower()
    if expected and profile["emailAddress"].lower() != expected:
        log.error(
            f"Token for {profile['emailAddress']} stored under account '{account}' "
            f"(expected {expected}): stopping, nothing is written"
        )
        sys.exit(2)


    log.info("Listing message IDs...")
    ids = list_all_ids(service, q)
    log.info(f"Found {len(ids)} messages matching query")

    if args.dry_run:
        log.info("--dry-run mode, stopping here")
        return


    done = load_done_ids(account_dir)
    download(account, ids, done, account_dir, num_workers)


    rows = 0
    if (account_dir / "messages.parquet").exists():
        df = pd.read_parquet(account_dir / "messages.parquet")
        rows = len(df)
        log.info(f"Final Parquet: {rows} rows, {df.columns.tolist()}")
        log.info(f"Date range: {df['date'].min()} → {df['date'].max()}")


    try:
        from event_bus import EventBus

        EventBus.emit("email", "l0", account=account, rows=rows)
    except Exception as e:
        log.warning(f"EventBus emit failed: {e}")

    mark_last_run(f"email-{account}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-email-download", source="email", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
