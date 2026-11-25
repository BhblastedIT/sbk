#!/usr/bin/env python3
"""Download Slack DMs and group DMs into L0."""






















from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    SLACK_EXCLUDE_CHANNEL_IDS,
    acquire_pid_lock,
    mark_last_run,
    safe_write_json,
)

SLACK_DM_DIR = DATA_ROOT / "slack" / "dm"
DM_INDEX_FILE = SLACK_DM_DIR / "_dm_index.json"


SEARCH_API_DELAY = 2.0

USER_INFO_DELAY = 0.6

HISTORY_API_DELAY = 2.0
SEARCH_PAGE_SIZE = 100
MAX_RETRIES = 3
RETRY_BACKOFF = 5

log = logging.getLogger("slack-dm-dl")





def get_user_token() -> str | None:
    """Your user token (xoxp-): Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""
    token = get_secret("sbk-slack", "user-token")
    if token and token.startswith("xoxp-"):
        log.info("User token loaded from Keychain (sbk-slack/user-token)")
        return token
    if token:
        log.warning(f"Keychain token is not xoxp- type: {token[:5]}...")
    for var in ("SBK_SLACK_USER_TOKEN", "SLACK_USER_TOKEN"):
        token = os.environ.get(var)
        if token and token.startswith("xoxp-"):
            log.info(f"User token loaded from {var}")
            return token
    return None





def load_user_cache_from_file() -> dict[str, str]:
    ""




    users_file = DATA_ROOT / "slack" / "slack-users.json"
    if not users_file.exists():
        return {}

    try:
        with open(users_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    cache: dict[str, str] = {}
    for user_id, info in data.items():
        name = info.get("real_name") or info.get("display_name") or info.get("name") or user_id
        if name:
            cache[user_id] = name

    log.info(f"Pre-loaded {len(cache)} user names from slack-users.json")
    return cache





def list_dm_conversations(user_token: str) -> list[dict] | None:
    ""





    all_channels: list[dict] = []
    cursor = None

    while True:
        params: dict = {"types": "im", "limit": "200"}
        if cursor:
            params["cursor"] = cursor

        result = slack_api("conversations.list", user_token, params)
        if not result:
            return None

        channels = result.get("channels", [])
        all_channels.extend(channels)

        cursor = result.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
        time.sleep(HISTORY_API_DELAY)

    return all_channels


def fetch_dm_history(
    user_token: str,
    channel_id: str,
    oldest: str | None = None,
    limit: int = 200,
) -> list[dict] | None:
    ""






    all_messages: list[dict] = []
    cursor = None

    while True:
        params: dict = {"channel": channel_id, "limit": str(limit)}
        if oldest:
            params["oldest"] = oldest
        if cursor:
            params["cursor"] = cursor

        result = slack_api("conversations.history", user_token, params)
        if not result:


            if all_messages:
                return None
            break

        messages = result.get("messages", [])
        all_messages.extend(messages)

        if not result.get("has_more", False):
            break

        cursor = result.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
        time.sleep(HISTORY_API_DELAY)

    return all_messages





def slack_api(
    method: str,
    token: str,
    params: dict | None = None,
    retry: int = 0,
) -> dict | None:
    ""






    if params is None:
        params = {}

    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.post(url, data=params, headers=headers, timeout=30)


        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            log.warning(f"Rate limited on {method}, waiting {retry_after}s")
            time.sleep(retry_after)
            return slack_api(method, token, params, retry=retry + 1)

        result = resp.json()

        if result.get("ok"):
            return result

        error = result.get("error", "unknown")


        if error in ("ratelimited", "internal_error", "fatal_error") and retry < MAX_RETRIES:
            wait = RETRY_BACKOFF * (retry + 1)
            log.warning(
                f"Slack API {method} error '{error}', retry {retry + 1}/{MAX_RETRIES} in {wait}s"
            )
            time.sleep(wait)
            return slack_api(method, token, params, retry=retry + 1)

        log.warning(f"Slack API {method} error: {error}")
        return None

    except requests.exceptions.Timeout:
        if retry < MAX_RETRIES:
            wait = RETRY_BACKOFF * (retry + 1)
            log.warning(f"Slack API {method} timeout, retry {retry + 1}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
            return slack_api(method, token, params, retry=retry + 1)
        log.error(f"Slack API {method} timed out after {MAX_RETRIES} retries")
        return None
    except Exception as e:
        if retry < MAX_RETRIES:
            wait = RETRY_BACKOFF * (retry + 1)
            log.warning(
                f"Slack API {method} failed: {e}, retry {retry + 1}/{MAX_RETRIES} in {wait}s"
            )
            time.sleep(wait)
            return slack_api(method, token, params, retry=retry + 1)
        log.error(f"Slack API {method} failed after {MAX_RETRIES} retries: {e}")
        return None





def search_dm_messages(
    user_token: str,
    after_ts: str | None = None,
) -> list[dict]:
    ""











    all_matches: list[dict] = []
    page = 1
    total_pages = None


    query = "is:dm"
    if after_ts:


        try:
            ts_float = float(after_ts)
            import datetime

            dt = datetime.datetime.fromtimestamp(ts_float, tz=datetime.UTC)
            date_str = dt.strftime("%Y-%m-%d")
            query = f"is:dm after:{date_str}"
            log.info(f"Incremental search query: {query}")
        except (ValueError, OSError):
            log.warning(f"Invalid timestamp '{after_ts}', searching all DMs")

    while True:
        params = {
            "query": query,
            "count": str(SEARCH_PAGE_SIZE),
            "page": str(page),
            "sort": "timestamp",
            "sort_dir": "asc",
        }

        result = slack_api("search.messages", user_token, params)
        if not result:
            log.error(f"search.messages failed at page {page}")
            break

        messages_data = result.get("messages", {})
        matches = messages_data.get("matches", [])
        paging = messages_data.get("paging", {})

        if total_pages is None:
            total_count = paging.get("total", 0)
            total_pages = paging.get("pages", 1)
            log.info(f"Search returned {total_count} total DM messages across {total_pages} pages")

        all_matches.extend(matches)

        log.info(
            f"  Page {page}/{total_pages}: {len(matches)} matches (cumulative: {len(all_matches)})"
        )

        if page >= (total_pages or 1):
            break

        page += 1
        time.sleep(SEARCH_API_DELAY)

    return all_matches





def resolve_user_name(token: str, user_id: str, cache: dict) -> str:
    ""











    if user_id in cache:
        return cache[user_id]

    result = slack_api("users.info", token, {"user": user_id})
    if result:
        user_info = result.get("user", {})
        profile = user_info.get("profile", {})
        name = (
            user_info.get("real_name")
            or profile.get("real_name")
            or profile.get("display_name")
            or user_info.get("name")
            or user_id
        )
        cache[user_id] = name
        time.sleep(USER_INFO_DELAY)
    else:
        log.warning(f"Could not resolve user {user_id}")
        cache[user_id] = user_id

    return cache[user_id]





def group_by_conversation(matches: list[dict]) -> dict[str, list[dict]]:
    ""










    conversations: dict[str, list[dict]] = {}

    for match in matches:
        channel = match.get("channel", {})
        channel_id = channel.get("id", "")
        if not channel_id:
            continue

        msg = {
            "ts": match.get("ts", ""),
            "user": match.get("user", match.get("username", "")),
            "text": match.get("text", ""),
            "type": match.get("type", "message"),
            "thread_ts": match.get("thread_ts", ""),
            "reply_count": match.get("reply_count", 0),
            "reactions": [
                {"name": r.get("name", ""), "count": r.get("count", 0), "users": r.get("users", [])}
                for r in match.get("reactions", [])
            ],
        }

        if channel_id not in conversations:
            conversations[channel_id] = []
        conversations[channel_id].append(msg)

    return conversations


def identify_dm_partner(
    channel_id: str,
    messages: list[dict],
    my_user_id: str,
) -> str | None:
    ""











    user_ids = {m.get("user", "") for m in messages if m.get("user")}
    other_users = user_ids - {my_user_id, ""}

    if len(other_users) == 1:
        return other_users.pop()
    if len(other_users) > 1:

        from collections import Counter

        user_counts = Counter(
            m.get("user", "") for m in messages if m.get("user") and m.get("user") != my_user_id
        )
        if user_counts:
            return user_counts.most_common(1)[0][0]



    return None





def load_existing_conversation(user_id: str) -> dict | None:
    ""



    filepath = SLACK_DM_DIR / f"{user_id}.json"
    if not filepath.exists():
        return None
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not load {filepath.name}: {e}")
        return None


def get_latest_ts_from_index() -> str:
    ""






    if not DM_INDEX_FILE.exists():
        return "0"
    try:
        with open(DM_INDEX_FILE, encoding="utf-8") as f:
            index = json.load(f)
        if not index:
            return "0"
        return max(
            (entry.get("last_ts", "0") for entry in index.values()),
            default="0",
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return "0"


def save_conversation(
    user_id: str,
    user_name: str,
    messages: list[dict],
    merge: bool = True,
) -> int:
    ""













    SLACK_DM_DIR.mkdir(parents=True, exist_ok=True)
    filepath = SLACK_DM_DIR / f"{user_id}.json"

    if merge and filepath.exists():
        existing = load_existing_conversation(user_id)
        if existing:
            existing_ts = {m.get("ts") for m in existing.get("messages", [])}
            new_msgs = [m for m in messages if m.get("ts") not in existing_ts]
            if not new_msgs:
                return 0

            all_msgs = existing.get("messages", []) + new_msgs
            all_msgs.sort(key=lambda m: m.get("ts", "0"))

            data = {
                "user_id": user_id,
                "user_name": user_name,
                "messages": all_msgs,
            }
            safe_write_json(filepath, data)
            return len(new_msgs)


    messages.sort(key=lambda m: m.get("ts", "0"))
    data = {
        "user_id": user_id,
        "user_name": user_name,
        "messages": messages,
    }
    safe_write_json(filepath, data)
    return len(messages)


def save_dm_index(
    conversations: dict[str, dict],
) -> None:
    ""




    SLACK_DM_DIR.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    for user_id, conv_data in conversations.items():
        msgs = conv_data.get("messages", [])
        timestamps = [m.get("ts", "0") for m in msgs if m.get("ts")]

        index[user_id] = {
            "user_id": user_id,
            "user_name": conv_data.get("user_name", user_id),
            "message_count": len(msgs),
            "first_ts": min(timestamps) if timestamps else "",
            "last_ts": max(timestamps) if timestamps else "",
        }

    safe_write_json(DM_INDEX_FILE, index)
    log.info(f"Saved DM index ({len(index)} conversations) -> {DM_INDEX_FILE}")


def build_full_index() -> dict[str, dict]:
    ""






    index: dict[str, dict] = {}
    if not SLACK_DM_DIR.exists():
        return index

    for jf in SLACK_DM_DIR.glob("*.json"):
        if jf.name.startswith("_"):
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            user_id = data.get("user_id", jf.stem)
            msgs = data.get("messages", [])
            timestamps = [m.get("ts", "0") for m in msgs if m.get("ts")]

            index[user_id] = {
                "user_id": user_id,
                "user_name": data.get("user_name", user_id),
                "message_count": len(msgs),
                "first_ts": min(timestamps) if timestamps else "",
                "last_ts": max(timestamps) if timestamps else "",
            }
        except (json.JSONDecodeError, OSError):
            continue

    return index





def main():
    if not acquire_pid_lock("sl-l0-download-dm", logger=log):



        log.warning("Another instance is running, exiting")
        sys.exit(75)

    parser = argparse.ArgumentParser(description="Slack L0 Download DM -- SBK")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count messages only, do not save anything",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full download (default: incremental)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()


    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_file = SLACK_DM_DIR.parent / "dm-download.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )

    log.info("=" * 60)
    log.info("SBK Slack L0 Download DM")
    log.info("=" * 60)


    user_token = get_user_token()
    if not user_token:
        log.error(
            "No Slack user token (xoxp-) found. Copy the User OAuth Token of your Slack app into "
            "the Keychain (service sbk-slack, account user-token) or into .env as SLACK_USER_TOKEN."
        )
        sys.exit(1)

    # Names of DM partners are resolved with your own token (scope users:read).
    name_token = user_token


    auth_result = slack_api("auth.test", user_token)
    if not auth_result:
        log.error("auth.test failed for user token. Token may be invalid or expired.")
        sys.exit(1)
    my_user_id = auth_result.get("user_id", "")
    log.info(
        f"Authenticated as: {auth_result.get('user', '?')} "
        f"({my_user_id}) in team {auth_result.get('team', '?')}"
    )


    after_ts: str | None = None
    if args.full:
        log.info("Mode: full (--full flag)")
    else:
        after_ts = get_latest_ts_from_index()
        if after_ts and after_ts != "0":
            log.info(f"Mode: incremental (default) — messages after ts={after_ts}")
        else:
            log.info("Mode: incremental (default) — no previous data, doing full download")
            after_ts = None


    user_name_cache: dict[str, str] = load_user_cache_from_file()


    t0 = time.time()
    use_fast_path = False
    dm_channels: list[dict] | None = None

    log.info("Attempting fast path: conversations.list(types=im)...")
    dm_channels = list_dm_conversations(user_token)
    if dm_channels:
        dm_channels = [c for c in dm_channels if c.get("id") not in SLACK_EXCLUDE_CHANNEL_IDS]

    if dm_channels is not None:
        log.info(
            f"Fast path available: {len(dm_channels)} DM conversations found "
            f"(conversations.history will be ~10x faster than search)"
        )
        use_fast_path = True
    else:
        log.info("Fast path unavailable (im:read scope missing?), falling back to search.messages")

    dm_interrotti: list[str] = []
    if use_fast_path and dm_channels is not None:

        conversations_data: dict[str, dict] = {}
        total_new = 0
        total_msgs = 0

        for i, ch in enumerate(dm_channels, 1):
            ch_id = ch.get("id", "")
            partner_id = ch.get("user", "")
            if not partner_id or not ch_id:
                continue


            ch_oldest: str | None = None
            if after_ts and after_ts != "0":

                existing = load_existing_conversation(partner_id)
                if existing:
                    existing_msgs = existing.get("messages", [])
                    if existing_msgs:
                        ch_oldest = max(m.get("ts", "0") for m in existing_msgs)


            messages = fetch_dm_history(user_token, ch_id, oldest=ch_oldest)
            if messages is None:
                dm_interrotti.append(ch_id)
                log.error(
                    f"  {ch_id}: history interrupted midway, DM not saved (will retry on the next run)"
                )
                continue
            if not messages:
                continue


            normalized = []
            for msg in messages:
                normalized.append(
                    {
                        "ts": msg.get("ts", ""),
                        "user": msg.get("user", ""),
                        "text": msg.get("text", ""),
                        "type": msg.get("type", "message"),
                        "thread_ts": msg.get("thread_ts", ""),
                        "reply_count": msg.get("reply_count", 0),
                        "reactions": [
                            {
                                "name": r.get("name", ""),
                                "count": r.get("count", 0),
                                "users": r.get("users", []),
                            }
                            for r in msg.get("reactions", [])
                        ],
                    }
                )


            if partner_id in user_name_cache:
                partner_name = user_name_cache[partner_id]
            else:
                partner_name = resolve_user_name(name_token, partner_id, user_name_cache)

            total_msgs += len(normalized)

            if args.dry_run:
                log.info(f"  [{i}/{len(dm_channels)}] {partner_name}: {len(normalized)} messages")
                continue


            new_count = save_conversation(
                user_id=partner_id,
                user_name=partner_name,
                messages=normalized,
                merge=True,
            )
            total_new += new_count

            if new_count > 0:
                log.info(
                    f"  [{i}/{len(dm_channels)}] {partner_name}: "
                    f"{new_count} new / {len(normalized)} total"
                )

            conversations_data[partner_id] = {
                "user_name": partner_name,
                "messages": normalized,
            }

        fetch_elapsed = time.time() - t0

        if args.dry_run:
            log.info("")
            log.info("=" * 60)
            log.info("DRY RUN -- Summary (fast path)")
            log.info("=" * 60)
            log.info(f"DM conversations: {len(dm_channels)}")
            log.info(f"Total messages:   {total_msgs}")
            log.info(f"Elapsed:          {fetch_elapsed:.1f}s")
            sys.exit(0)

    else:

        log.info("Searching DM messages (slow path)...")
        matches = search_dm_messages(user_token, after_ts=after_ts)
        search_elapsed = time.time() - t0

        if not matches:
            log.info("No DM messages found.")
            sys.exit(0)

        log.info(f"Search completed in {search_elapsed:.1f}s: {len(matches)} matches")


        grouped = group_by_conversation(matches)
        log.info(f"Grouped into {len(grouped)} DM conversations")

        if args.dry_run:
            log.info("")
            log.info("=" * 60)
            log.info("DRY RUN -- Summary (search path)")
            log.info("=" * 60)
            log.info(f"Total DM messages: {len(matches)}")
            log.info(f"DM conversations:  {len(grouped)}")
            sys.exit(0)


        conversations_data = {}
        total_new = 0

        for conv_idx, (ch_id, messages) in enumerate(grouped.items(), 1):
            partner_id = identify_dm_partner(ch_id, messages, my_user_id)

            if not partner_id:
                log.warning(f"Could not identify DM partner for channel {ch_id}, skipping")
                continue
            if ch_id in SLACK_EXCLUDE_CHANNEL_IDS:
                continue


            if partner_id in user_name_cache:
                partner_name = user_name_cache[partner_id]
            else:
                partner_name = resolve_user_name(name_token, partner_id, user_name_cache)

            log.info(
                f"[{conv_idx}/{len(grouped)}] {partner_name} ({partner_id}): "
                f"{len(messages)} messages"
            )


            new_count = save_conversation(
                user_id=partner_id,
                user_name=partner_name,
                messages=messages,
                merge=True,
            )
            total_new += new_count


            existing = load_existing_conversation(partner_id)
            conversations_data[partner_id] = {
                "user_name": partner_name,
                "messages": existing.get("messages", []) if existing else messages,
            }


    full_index_data = build_full_index()

    for uid, cdata in conversations_data.items():
        if uid not in full_index_data:
            msgs = cdata.get("messages", [])
            timestamps = [m.get("ts", "0") for m in msgs if m.get("ts")]
            full_index_data[uid] = {
                "user_id": uid,
                "user_name": cdata.get("user_name", uid),
                "message_count": len(msgs),
                "first_ts": min(timestamps) if timestamps else "",
                "last_ts": max(timestamps) if timestamps else "",
            }


    safe_write_json(DM_INDEX_FILE, full_index_data)
    log.info(f"Saved DM index ({len(full_index_data)} conversations) -> {DM_INDEX_FILE}")


    elapsed = time.time() - t0
    log.info("")
    log.info("=" * 60)
    log.info("Summary")
    log.info("=" * 60)
    log.info(
        f"Mode:                  {'fast path (conversations.history)' if use_fast_path else 'search.messages'}"
    )
    log.info(f"DM conversations:      {len(conversations_data)}")
    log.info(f"New messages saved:    {total_new}")
    log.info(f"Index entries:         {len(full_index_data)}")
    log.info(f"Elapsed:               {elapsed:.1f}s ({elapsed / 60:.1f}m)")


    log.info("")
    log.info("Top 10 conversations by message count:")
    by_volume = sorted(
        full_index_data.values(),
        key=lambda x: x.get("message_count", 0),
        reverse=True,
    )
    for i, entry in enumerate(by_volume[:10], 1):
        log.info(
            f"  {i:2d}. {entry.get('user_name', '?')} "
            f"({entry.get('user_id', '?')}): "
            f"{entry.get('message_count', 0)} messages"
        )

    log.info("=" * 60)


    try:
        from event_bus import EventBus

        EventBus.emit("slack", "l0", dm_conversations=len(full_index_data))
    except Exception as e:
        log.warning(f"EventBus emit failed: {e}")

    if dm_interrotti:
        log.error(
            f"slack-dm: {len(dm_interrotti)} DMs with interrupted history, run NOT complete, exit 1"
        )
        sys.exit(1)
    mark_last_run("slack-dm")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-slack-download-dm", source="slack", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
