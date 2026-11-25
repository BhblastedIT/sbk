#!/usr/bin/env python3
""














import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


NOTION_TOKEN = os.environ.get("NOTION_TOKEN")


def _richiedi_token() -> None:
    # Checked after argument parsing, so --help works without a token.
    if not NOTION_TOKEN:
        sys.exit(
            "NOTION_TOKEN env var not set: put your Notion integration token in .env and export it "
            "(set -a && source .env && set +a), see docs/CONNECTING.md#notion. Nothing downloaded."
        )


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import DATA_ROOT, get_last_run, mark_last_run  # noqa: E402

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"
OUTPUT_DIR = DATA_ROOT / "notion"
INDEX_PATH = (
    Path(__file__).resolve().parent.parent.parent / "sbk" / "raw" / "misc" / "notion-index.json"
)


SKIP_DB_IDS = {
    "00000000-0000-0000-0000-000000000000",
}


REQUEST_DELAY = 0.4
REQUEST_TIMEOUT_SECS = 30
BACKOFF_MULTIPLIER = 2
MAX_RETRIES = 5
MAX_BLOCK_DEPTH = 3
MAX_BLOCKS_PER_PAGE = 500


EDIT_TRACKER_PATH = OUTPUT_DIR / "edit-tracker.json"


_rate_semaphore = None
_rate_lock = threading.Lock()


log = logging.getLogger("notion-dl")


def _configura_log() -> None:
    # Set up after argument parsing, so --help neither needs nor creates the data folder.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(OUTPUT_DIR / "download.log")],
    )


stats = {
    "databases_downloaded": 0,
    "databases_skipped": 0,
    "pages_downloaded": 0,
    "blocks_downloaded": 0,
    "comments_downloaded": 0,
    "errors": 0,
    "total_rows": 0,
    "start_time": None,
}

_last_request_time = 0


def api_request(method, endpoint, body=None):
    ""
    global _last_request_time

    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES):

        if _rate_semaphore:
            _rate_semaphore.acquire()
        try:
            with _rate_lock:
                elapsed = time.time() - _last_request_time
                if elapsed < REQUEST_DELAY:
                    time.sleep(REQUEST_DELAY - elapsed)
                _last_request_time = time.time()

            req = Request(url, method=method, headers=headers)
            if body:
                req.data = json.dumps(body).encode()

            with urlopen(req, timeout=REQUEST_TIMEOUT_SECS) as resp:
                return json.loads(resp.read())

        except HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", BACKOFF_MULTIPLIER * (attempt + 1)))
                log.warning(f"Rate limited, waiting {retry_after}s (attempt {attempt + 1})")
                time.sleep(retry_after)
            elif e.code == 404:
                log.warning(f"Not found: {endpoint}")
                return None
            elif e.code == 403:
                log.warning(f"Forbidden: {endpoint}")
                return None
            elif e.code >= 500:
                wait = BACKOFF_MULTIPLIER * (attempt + 1)
                log.warning(f"Server error {e.code}, waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
            else:
                log.error(f"HTTP {e.code} for {endpoint}: {e.read().decode()[:200]}")
                return None
        except Exception as e:
            wait = 2 * (attempt + 1)
            log.warning(f"Request error: {e}, waiting {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
        finally:
            if _rate_semaphore:
                _rate_semaphore.release()

    log.error(f"Failed after {MAX_RETRIES} retries: {endpoint}")
    _inc_stat("errors")
    return None


def load_edit_tracker():
    ""
    if EDIT_TRACKER_PATH.exists():
        try:
            data = json.loads(EDIT_TRACKER_PATH.read_text())
            data.setdefault("pages", {})
            data.setdefault("databases", {})
            return data
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt edit tracker, starting fresh")
    return {"pages": {}, "databases": {}}


def save_edit_tracker(tracker):
    ""
    EDIT_TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDIT_TRACKER_PATH.write_text(json.dumps(tracker, indent=1))


def get_changed_ids_from_search(tracker):
    ""





    changed_ids = set()
    has_more = True
    start_cursor = None
    seen_unchanged = 0
    UNCHANGED_THRESHOLD = 5

    while has_more:
        body = {
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor

        result = api_request("POST", "/search", body)
        if not result:
            break

        for item in result.get("results", []):
            obj_id = item["id"]
            obj_type = item["object"]
            last_edited = item.get("last_edited_time", "")

            tracker_key = "databases" if obj_type == "database" else "pages"
            tracked_time = tracker.get(tracker_key, {}).get(obj_id)

            if tracked_time and tracked_time == last_edited:
                seen_unchanged += 1
                if seen_unchanged >= UNCHANGED_THRESHOLD:
                    log.info(
                        f"Edit tracker: {seen_unchanged} consecutive unchanged, stopping search "
                        f"({len(changed_ids)} changed found)"
                    )
                    return changed_ids
            else:
                seen_unchanged = 0
                changed_ids.add(obj_id)

        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")

    log.info(f"Edit tracker: {len(changed_ids)} changed resources found via search")
    return changed_ids


FORCE_REFRESH = False
_edit_tracker = None
_changed_ids = None
_stats_lock = threading.Lock()


def _should_skip_by_tracker(resource_id):
    ""
    if FORCE_REFRESH or _changed_ids is None:
        return False
    return resource_id not in _changed_ids


def _update_tracker(resource_type, resource_id, last_edited_time):
    ""
    if _edit_tracker is not None and last_edited_time:
        with _stats_lock:
            _edit_tracker[resource_type][resource_id] = last_edited_time


def _inc_stat(key, amount=1):
    ""
    with _stats_lock:
        stats[key] += amount


def download_database(db_id, db_title):
    ""
    if db_id in SKIP_DB_IDS:
        log.info(f"SKIP (sensitive): {db_title}")
        _inc_stat("databases_skipped")
        return

    if _should_skip_by_tracker(db_id):
        log.info(f"SKIP (unchanged): {db_title}")
        _inc_stat("databases_skipped")
        return

    out_path = OUTPUT_DIR / "databases" / f"{db_id}.json"
    if out_path.exists() and not FORCE_REFRESH:
        log.info(f"SKIP (exists): {db_title}")
        return


    schema = api_request("GET", f"/databases/{db_id}")
    if not schema:
        log.error(f"Failed to get schema: {db_title} ({db_id})")
        return


    _update_tracker("databases", db_id, schema.get("last_edited_time"))


    rows = []
    has_more = True
    start_cursor = None

    while has_more:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor

        result = api_request("POST", f"/databases/{db_id}/query", body)
        if not result:
            break

        rows.extend(result.get("results", []))
        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")


    data = {
        "schema": schema,
        "rows": rows,
        "row_count": len(rows),
        "downloaded_at": datetime.now().isoformat(),
    }

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    _inc_stat("databases_downloaded")
    _inc_stat("total_rows", len(rows))
    log.info(f"DB: {db_title} — {len(rows)} rows")


def download_page_properties(page_id, page_title):
    ""
    if _should_skip_by_tracker(page_id):
        return

    out_path = OUTPUT_DIR / "pages" / f"{page_id}.json"
    if out_path.exists() and not FORCE_REFRESH:
        return

    result = api_request("GET", f"/pages/{page_id}")
    if result:
        _update_tracker("pages", page_id, result.get("last_edited_time"))
        result["_downloaded_at"] = datetime.now().isoformat()
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        _inc_stat("pages_downloaded")


_block_counter_local = threading.local()


def download_blocks_recursive(block_id, depth=0):
    ""
    if depth > MAX_BLOCK_DEPTH:
        return []

    blocks = []
    has_more = True
    start_cursor = None

    while has_more:
        counter = getattr(_block_counter_local, "count", 0)
        if counter >= MAX_BLOCKS_PER_PAGE:
            log.warning(f"Block cap reached ({MAX_BLOCKS_PER_PAGE}), stopping recursion")
            break

        endpoint = f"/blocks/{block_id}/children?page_size=100"
        if start_cursor:
            endpoint += f"&start_cursor={start_cursor}"

        result = api_request("GET", endpoint)
        if not result:
            break

        for block in result.get("results", []):
            _block_counter_local.count = getattr(_block_counter_local, "count", 0) + 1
            blocks.append(block)

            btype = block.get("type", "")
            if block.get("has_children", False) and btype not in ("child_page", "child_database"):
                children = download_blocks_recursive(block["id"], depth + 1)
                block["_children"] = children

        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")

    return blocks


def download_page_blocks(page_id, page_title):
    ""
    if _should_skip_by_tracker(page_id):
        return

    out_path = OUTPUT_DIR / "blocks" / f"{page_id}.json"
    if out_path.exists() and not FORCE_REFRESH:
        return

    _block_counter_local.count = 0
    blocks = download_blocks_recursive(page_id)

    data = {
        "page_id": page_id,
        "title": page_title,
        "blocks": blocks,
        "block_count": len(blocks),
        "downloaded_at": datetime.now().isoformat(),
    }

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    _inc_stat("blocks_downloaded")
    final_count = getattr(_block_counter_local, "count", 0)
    if final_count > 50:
        log.info(f"  -> {final_count} blocks downloaded")


def download_page_comments(page_id, page_title):
    ""
    out_path = OUTPUT_DIR / "comments" / f"{page_id}.json"
    if out_path.exists() and not FORCE_REFRESH:
        return

    comments = []
    has_more = True
    start_cursor = None

    while has_more:
        params = f"?block_id={page_id}&page_size=100"
        if start_cursor:
            params += f"&start_cursor={start_cursor}"
        result = api_request("GET", f"/comments{params}")
        if not result:
            break
        comments.extend(result.get("results", []))
        has_more = result.get("has_more", False)
        start_cursor = result.get("next_cursor")

    if comments:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "page_id": page_id,
            "title": page_title,
            "comments": comments,
            "comment_count": len(comments),
            "downloaded_at": datetime.now().isoformat(),
        }
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        stats["comments_downloaded"] += len(comments)


def _download_standalone_page(page):
    ""
    download_page_properties(page["id"], page["title"])
    download_page_blocks(page["id"], page["title"])
    download_page_comments(page["id"], page.get("title", ""))


def main():
    global FORCE_REFRESH, _rate_semaphore, _edit_tracker, _changed_ids
    parser = argparse.ArgumentParser(description="Notion L0 downloader")
    parser.add_argument(
        "--force", action="store_true", help="Re-download everything (ignore edit tracker + exists)"
    )
    parser.add_argument(
        "--incremental", action="store_true", help="Skip if last run was less than 1 hour ago"
    )
    parser.add_argument(
        "--workers", type=int, default=3, help="Parallel download workers (default 3)"
    )
    args = parser.parse_args()
    _richiedi_token()
    _configura_log()
    FORCE_REFRESH = args.force

    if args.incremental and not args.force:
        last = get_last_run("notion")
        if last:
            age_hours = (datetime.now(UTC) - last.replace(tzinfo=UTC)).total_seconds() / 3600
            if age_hours < 1:
                log.info(f"Incremental: last run {age_hours:.1f}h ago (< 1h) — skipping")
                return


    _rate_semaphore = threading.Semaphore(3)

    stats["start_time"] = time.time()


    _edit_tracker = load_edit_tracker()
    if not args.force and (_edit_tracker["pages"] or _edit_tracker["databases"]):
        log.info(
            f"Edit tracker loaded: {len(_edit_tracker['pages'])} pages, "
            f"{len(_edit_tracker['databases'])} databases tracked"
        )
        _changed_ids = get_changed_ids_from_search(_edit_tracker)
    else:
        _changed_ids = None
        if args.force:
            log.info("Force mode: ignoring edit tracker")
        else:
            log.info("No edit tracker history: downloading everything")


    with open(INDEX_PATH) as f:
        index = json.load(f)

    databases = index["databases"]
    pages_in_db = index["pages_in_db"]
    pages_standalone = index["pages_standalone"]
    pages_subpage = index["pages_subpage"]

    total = len(databases) + len(pages_standalone) + len(pages_subpage)
    log.info(
        f"Starting download: {len(databases)} DBs, {len(pages_standalone)} standalone, "
        f"{len(pages_subpage)} subpages ({args.workers} workers)"
    )
    log.info("(Pages in DBs are downloaded with their database, not separately)")


    log.info("=" * 60)
    log.info("PHASE 1: Downloading databases...")
    log.info("=" * 60)

    for i, db in enumerate(databases):
        log.info(f"[{i + 1}/{len(databases)}] {db['title']}")
        download_database(db["id"], db["title"])

    log.info(
        f"Databases done: {stats['databases_downloaded']} downloaded, "
        f"{stats['databases_skipped']} skipped, {stats['total_rows']} total rows"
    )


    log.info("=" * 60)
    log.info(f"PHASE 2: Downloading standalone pages ({args.workers} workers)...")
    log.info("=" * 60)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_download_standalone_page, page): page for page in pages_standalone
        }
        for i, future in enumerate(as_completed(futures)):
            page = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"Error downloading page {page['title']}: {e}")
                _inc_stat("errors")
            if (i + 1) % 25 == 0:
                log.info(f"  Phase 2 progress: {i + 1}/{len(pages_standalone)}")

    log.info(
        f"Standalone pages done: {stats['pages_downloaded']} props, {stats['blocks_downloaded']} blocks"
    )


    log.info("=" * 60)
    log.info(f"PHASE 3: Downloading sub-page blocks ({args.workers} workers)...")
    log.info("=" * 60)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(download_page_blocks, page["id"], page.get("title", "Untitled")): page
            for page in pages_subpage
        }
        for i, future in enumerate(as_completed(futures)):
            page = futures[future]
            try:
                future.result()
            except Exception as e:
                log.error(f"Error downloading subpage {page.get('title', 'Untitled')}: {e}")
                _inc_stat("errors")
            if (i + 1) % 50 == 0:
                log.info(
                    f"  Phase 3 progress: {i + 1}/{len(pages_subpage)} "
                    f"({stats['blocks_downloaded']} blocks so far)"
                )


    save_edit_tracker(_edit_tracker)
    log.info(
        f"Edit tracker saved: {len(_edit_tracker['pages'])} pages, "
        f"{len(_edit_tracker['databases'])} databases"
    )


    elapsed = time.time() - stats["start_time"]
    log.info("=" * 60)
    log.info("DOWNLOAD COMPLETE")
    log.info(f"  Databases: {stats['databases_downloaded']} ({stats['total_rows']} rows)")
    log.info(f"  Pages (props): {stats['pages_downloaded']}")
    log.info(f"  Pages (blocks): {stats['blocks_downloaded']}")
    log.info(f"  Errors: {stats['errors']}")
    log.info(f"  Time: {elapsed / 60:.1f} minutes")
    if _changed_ids is not None:
        log.info(f"  Changed resources detected: {len(_changed_ids)}")
    log.info("=" * 60)


    summary = {
        **stats,
        "elapsed_seconds": elapsed,
        "completed_at": datetime.now().isoformat(),
    }
    (OUTPUT_DIR / "download-summary.json").write_text(json.dumps(summary, indent=2))

    mark_last_run("notion")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-notion-download", source="notion", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
