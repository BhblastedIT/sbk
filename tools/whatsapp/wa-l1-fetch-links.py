#!/usr/bin/env python3
"""WhatsApp extra: list the links shared in your chats and, with --fetch, read each page's title and description.

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Without --fetch it only counts the links (no network). With --fetch it opens every link on the web,
one request every --rate-limit seconds. Output: <data root>/whatsapp/links/.

    uv run python tools/whatsapp/wa-l1-fetch-links.py                 # count only
    uv run python tools/whatsapp/wa-l1-fetch-links.py --fetch --max-urls 50
"""












from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-wa-l1-fetch-links")

CHATS_DIR = DATA_ROOT / "whatsapp" / "chats"
LINKS_DIR = DATA_ROOT / "whatsapp" / "links"

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


BLACKLIST_DOMAINS = {
    "bit.ly",
    "t.co",
    "goo.gl",
    "tinyurl.com",
    "instagram.com",
    "www.instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "wa.me",
    "web.whatsapp.com",
    "chat.whatsapp.com",
    "accounts.google.com",
    "login.microsoftonline.com",
    "open.spotify.com",
    "play.google.com",
    "apps.apple.com",
}

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def extract_urls_from_chat(chat_path: Path) -> list[dict]:
    ""
    try:
        data = json.loads(chat_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    messages = data.get("messages", [])
    chat_name = data.get("chat_name", chat_path.stem)
    seen: set[str] = set()
    urls: list[dict] = []

    for msg in messages:
        text = msg.get("text", "")
        if not text:
            continue
        for match in URL_RE.findall(text):

            url = match.rstrip(".,;:!?)")
            if url in seen:
                continue
            seen.add(url)

            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            domain = parsed.netloc.lower()
            if domain in BLACKLIST_DOMAINS:
                continue

            urls.append(
                {
                    "url": url,
                    "domain": domain,
                    "sender": msg.get("sender", ""),
                    "timestamp": msg.get("timestamp", ""),
                    "chat_name": chat_name,
                }
            )

    return urls


def fetch_url_metadata(url_entry: dict, timeout: int = 10) -> dict:
    ""
    import requests
    from bs4 import BeautifulSoup

    url = url_entry["url"]
    result = {
        **url_entry,
        "title": "",
        "description": "",
        "og_image": "",
        "first_paragraph": "",
        "status": "ok",
    }

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": BROWSER_UA},
            allow_redirects=True,
            verify=False,
        )
        result["status_code"] = resp.status_code

        if resp.status_code != 200:
            result["status"] = f"http_{resp.status_code}"
            return result

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            result["status"] = "not_html"
            return result

        soup = BeautifulSoup(resp.text[:50000], "lxml")


        if soup.title and soup.title.string:
            result["title"] = soup.title.string.strip()[:200]


        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            result["description"] = (og_desc.get("content", "") or "")[:500]
        else:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                result["description"] = (meta_desc.get("content", "") or "")[:500]

        og_img = soup.find("meta", property="og:image")
        if og_img:
            result["og_image"] = og_img.get("content", "")


        first_p = soup.find("p")
        if first_p and first_p.get_text():
            result["first_paragraph"] = first_p.get_text().strip()[:300]

    except Exception as e:
        result["status"] = f"error: {type(e).__name__}"

    return result


def main():
    parser = argparse.ArgumentParser(description="DPI-06: WhatsApp Link/URL Fetch")
    parser.add_argument(
        "--fetch", action="store_true", help="Fetch URL metadata (default: dry-run)"
    )
    parser.add_argument("--max-urls", type=int, default=None, help="Max URLs to fetch per chat")
    parser.add_argument(
        "--workers", type=int, default=4, help="Parallel fetch workers (default: 4)"
    )
    parser.add_argument(
        "--rate-limit", type=float, default=0.5, help="Seconds between requests (default: 0.5)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not CHATS_DIR.exists():
        log.error("WhatsApp chats directory not found: %s", CHATS_DIR)
        return


    chat_files = sorted(CHATS_DIR.glob("*.json"))
    log.info("Scanning %d chat files...", len(chat_files))

    all_urls: list[dict] = []
    for cf in chat_files:
        urls = extract_urls_from_chat(cf)
        all_urls.extend(urls)


    seen: set[str] = set()
    unique_urls: list[dict] = []
    for u in all_urls:
        if u["url"] not in seen:
            seen.add(u["url"])
            unique_urls.append(u)

    log.info(
        "Found %d unique URLs from %d chats (%d total before dedup)",
        len(unique_urls),
        len(chat_files),
        len(all_urls),
    )


    from collections import Counter

    domains = Counter(u["domain"] for u in unique_urls)
    log.info("Top domains:")
    for domain, cnt in domains.most_common(10):
        log.info("  %s: %d", domain, cnt)

    if not args.fetch:
        log.info("Dry run complete. Use --fetch to download metadata.")
        return


    if args.max_urls:
        unique_urls = unique_urls[: args.max_urls]
        log.info("Limited to %d URLs", len(unique_urls))


    log.info("Fetching metadata for %d URLs (workers=%d)...", len(unique_urls), args.workers)

    results: list[dict] = []
    errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for i, url_entry in enumerate(unique_urls):
            future = executor.submit(fetch_url_metadata, url_entry)
            futures[future] = url_entry

            if (i + 1) % args.workers == 0:
                time.sleep(args.rate_limit)

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result["status"] != "ok":
                errors += 1


    LINKS_DIR.mkdir(parents=True, exist_ok=True)
    by_chat: dict[str, list[dict]] = {}
    for r in results:
        chat = r.get("chat_name", "unknown")
        slug = re.sub(r"[^\w\-]", "_", chat)[:60]
        by_chat.setdefault(slug, []).append(r)

    for slug, chat_results in by_chat.items():
        safe_write_json(LINKS_DIR / f"{slug}.json", chat_results)


    safe_write_json(
        LINKS_DIR / "_fetch-stats.json",
        {
            "total_urls": len(unique_urls),
            "fetched": len(results),
            "errors": errors,
            "ok": len(results) - errors,
            "chats_with_links": len(by_chat),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )

    log.info("Done: %d fetched, %d errors, %d chats", len(results), errors, len(by_chat))


if __name__ == "__main__":
    main()
