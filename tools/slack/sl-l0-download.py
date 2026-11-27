#!/usr/bin/env python3
"""Download Slack channel messages and thread replies into L0.

Only the conversations you are a member of (users.conversations): your channels, private
channels, DMs and group DMs. Public channels you never joined are not read. Archived
conversations are skipped unless you pass --include-archived.
"""





















from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from datetime import UTC

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import (  # noqa: E402
    SLACK_CHANNEL_INDEX_FILE,
    SLACK_CHANNELS_FILE,
    SLACK_CONVERSATIONS_DIR,
    load_conversations_cache,
    mark_last_run,
    safe_write_json,
    save_conversations_cache,
)

SLACK_USERS_FILE = SLACK_CONVERSATIONS_DIR.parent / "slack-users.json"


_SKIP_THREADS = False


FINESTRA_GIORNI = 30





# One user token reads one workspace: the one your Slack app is installed in.
# Its id and name come from auth.test at the start of the run (used in logs only).
WORKSPACE_NAMES: dict[str, str] = {}


API_DELAY = 1.5
HISTORY_PAGE_SIZE = 200
LIST_PAGE_SIZE = 200
MAX_RETRIES = 3
RETRY_BACKOFF = 5

log = logging.getLogger("slack-dl")





class RateLimiter:
    ""





    def __init__(self, min_interval: float = API_DELAY):
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        ""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()



_rate_limiter = RateLimiter()

_ULTIMO_ERRORE = threading.local()



FUORI_DAL_TOKEN = frozenset({"channel_not_found", "team_access_not_granted", "not_in_channel"})

FUORI = "outside token scope: "





def get_slack_token() -> str | None:
    """Your user token (xoxp-): Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""








    token = get_secret("sbk-slack", "user-token")
    if token and token.startswith(("xoxp-", "xoxe.xoxp-")):
        log.info("Using user-token from Keychain")
        return token

    for var in ("SBK_SLACK_USER_TOKEN", "SLACK_USER_TOKEN"):
        token = os.environ.get(var)
        if token and token.startswith(("xoxp-", "xoxe.xoxp-")):
            log.info(f"Using {var} from environment")
            return token

    return None


def load_exclusion_set() -> set[str]:
    ""








    from slack_esclusi import IndiceAssente, esclusi

    try:
        excluded = set(esclusi(SLACK_CHANNEL_INDEX_FILE))
    except IndiceAssente as e:
        log.error(str(e))
        sys.exit(2)
    log.info(f"Exclusion filter (sbk.config.json): {len(excluded)} excluded conversations")
    return excluded


def token_workspace(auth: dict) -> list[str]:
    """The workspace of your token, as auth.test reports it."""
    tid = auth.get("team_id", "") or ""
    WORKSPACE_NAMES[tid] = auth.get("team", "") or tid or "workspace"
    log.info(f"Workspace: {WORKSPACE_NAMES[tid]} ({tid or 'id not reported'})")
    return [tid]


def load_channel_index() -> dict | None:
    ""
    if not SLACK_CHANNEL_INDEX_FILE.exists():
        return None
    try:
        with open(SLACK_CHANNEL_INDEX_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None





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


    data = params
    headers = {"Authorization": f"Bearer {token}"}

    try:

        _rate_limiter.wait()

        resp = requests.post(url, data=data, headers=headers, timeout=30)


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
        _ULTIMO_ERRORE.codice = error
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





def list_all_conversations(token: str, team_ids: list[str] | None = None) -> list[dict]:
    """The conversations you are a member of (users.conversations), archived ones included.

    users.conversations returns only the channels, private channels, DMs and group DMs your
    own account is in, never the public channels of the workspace you did not join.
    Archived conversations are kept in the list (and in the cache) and dropped later by
    keep_your_conversations() unless you ask for them with --include-archived.
    """
    if team_ids is None:
        team_ids = [""]

    all_channels: dict[str, dict] = {}

    for team_id in team_ids:
        ws_name = WORKSPACE_NAMES.get(team_id, team_id) or "workspace"
        ws_count = 0

        for conv_type in ("public_channel", "private_channel", "mpim", "im"):
            cursor = None
            page = 0
            while True:
                params = {
                    "types": conv_type,
                    "limit": str(LIST_PAGE_SIZE),


                    "exclude_archived": "false",
                }
                if cursor:
                    params["cursor"] = cursor

                result = slack_api("users.conversations", token, params)
                if not result:
                    if page == 0 and conv_type == "public_channel":
                        log.warning(
                            f"  [{ws_name}] users.conversations failed for type={conv_type}"
                        )
                    break

                channels = result.get("channels", [])
                for ch in channels:
                    cid = ch.get("id", "")
                    if cid and cid not in all_channels:
                        all_channels[cid] = ch
                        ws_count += 1
                page += 1

                next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
                if not next_cursor:
                    break
                cursor = next_cursor
                time.sleep(API_DELAY)

        log.info(f"  [{ws_name}] {ws_count} conversations")

    result_list = list(all_channels.values())
    log.info(
        f"Total conversations discovered: {len(result_list)} across {len(team_ids)} workspace(s)"
    )
    return result_list


def keep_your_conversations(channels: list[dict], include_archived: bool = False) -> list[dict]:
    """Keep only the conversations you are a member of; archived ones only on request.

    A conversation whose is_member is False is dropped: that is a public channel you never
    joined, as an older cache built from conversations.list could still hold. DMs and group
    DMs carry no is_member field and are always yours. Archived conversations are dropped
    unless include_archived is True (--include-archived).
    """
    kept: list[dict] = []
    not_member = archived = 0
    for ch in channels:
        if ch.get("is_member") is False:
            not_member += 1
            continue
        if ch.get("is_archived") and not include_archived:
            archived += 1
            continue
        kept.append(ch)
    if not_member:
        log.info(f"Left out {not_member} channels you are not a member of")
    if archived:
        log.info(f"Left out {archived} archived conversations (--include-archived to read them)")
    return kept


def _channel_type(ch: dict) -> str:
    ""
    if ch.get("is_im"):
        return "im"
    if ch.get("is_mpim"):
        return "mpim"
    if ch.get("is_private"):
        return "private_channel"
    return "public_channel"





def fetch_all_users(token: str, team_ids: list[str] | None = None) -> dict[str, dict]:
    ""







    if team_ids is None:
        team_ids = [""]

    users = {}

    for team_id in team_ids:
        ws_name = WORKSPACE_NAMES.get(team_id, team_id) or "workspace"
        cursor = None
        page = 0
        ws_count = 0

        while True:
            params = {"limit": "200"}
            if cursor:
                params["cursor"] = cursor

            result = slack_api("users.list", token, params)
            if not result:
                log.warning(f"  [{ws_name}] users.list failed at page {page}")
                break

            if not result.get("ok"):
                err = result.get("error", "unknown")
                if page == 0:
                    log.warning(f"  [{ws_name}] users.list error: {err}")
                break

            for member in result.get("members", []):
                uid = member.get("id", "")
                if not uid or uid in users:
                    continue

                profile = member.get("profile", {})
                users[uid] = {
                    "user_id": uid,
                    "name": member.get("name", ""),
                    "real_name": member.get("real_name", profile.get("real_name", "")),
                    "display_name": profile.get("display_name", ""),
                    "is_bot": member.get("is_bot", False),
                    "deleted": member.get("deleted", False),
                    "team_id": member.get("team_id", ""),
                    "title": profile.get("title", ""),
                    "email": profile.get("email", ""),
                    "phone": profile.get("phone", ""),
                    "tz": member.get("tz", ""),
                }
                ws_count += 1

            page += 1
            next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor
            time.sleep(API_DELAY)

        if ws_count > 0:
            log.info(f"  [{ws_name}] {ws_count} users")

    log.info(f"Fetched {len(users)} users ({sum(1 for u in users.values() if u['is_bot'])} bots)")
    return users


def save_users(users: dict[str, dict]) -> None:
    ""
    safe_write_json(SLACK_USERS_FILE, users)
    log.info(f"Saved {len(users)} users -> {SLACK_USERS_FILE}")





def save_channels_metadata(channels: list[dict], users: dict[str, dict]) -> None:
    ""





    metadata = []
    for ch in channels:
        ch_id = ch.get("id", "")
        name = ch.get("name", "")


        if ch.get("is_im"):
            other_user = ch.get("user", "")
            if other_user and other_user in users:
                user_info = users[other_user]
                name = user_info.get("real_name") or user_info.get("name") or other_user
            elif other_user:
                name = other_user

        metadata.append(
            {
                "id": ch_id,
                "name": name,
                "p": ch.get("is_private", False),
                "im": ch.get("is_im", False),
                "mp": ch.get("is_mpim", False),
                "m": ch.get("num_members", 0),
                "pu": ch.get("purpose", {}).get("value", "")
                if isinstance(ch.get("purpose"), dict)
                else "",
            }
        )

    safe_write_json(SLACK_CHANNELS_FILE, metadata)
    log.info(f"Saved {len(metadata)} channels -> {SLACK_CHANNELS_FILE}")





def fetch_channel_history(
    token: str,
    channel_id: str,
    oldest: str = "0",
) -> list[dict] | None:
    ""









    messages = []
    cursor = None
    page = 0

    while True:
        params = {
            "channel": channel_id,
            "limit": str(HISTORY_PAGE_SIZE),
        }
        if oldest and oldest != "0":
            params["oldest"] = oldest
        if cursor:
            params["cursor"] = cursor

        result = slack_api("conversations.history", token, params)
        if not result:



            log.warning(f"  conversations.history failed for {channel_id} (page {page})")
            return None

        batch = result.get("messages", [])
        messages.extend(batch)
        page += 1

        if not result.get("has_more", False):
            break

        next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
        if not next_cursor:
            break
        cursor = next_cursor


    return messages


def fetch_thread_replies(
    token: str,
    channel_id: str,
    thread_ts: str,
) -> list[dict]:
    ""
    replies = []
    cursor = None

    while True:
        params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": "200",
        }
        if cursor:
            params["cursor"] = cursor

        result = slack_api("conversations.replies", token, params)
        if not result:
            break

        batch = result.get("messages", [])
        replies.extend(batch)

        if not result.get("has_more", False):
            break
        next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
        if not next_cursor:
            break
        cursor = next_cursor

    return replies


def parse_message(msg: dict) -> dict:
    ""




    return {
        "user": msg.get("user", msg.get("bot_id", "")),
        "text": msg.get("text", ""),
        "ts": msg.get("ts", ""),
        "thread_ts": msg.get("thread_ts", ""),
        "reply_count": msg.get("reply_count", 0),


        "latest_reply": msg.get("latest_reply", ""),
        "edited": (msg.get("edited") or {}).get("ts", ""),
        "subtype": msg.get("subtype", ""),
        "reactions": [
            {"name": r.get("name", ""), "count": r.get("count", 0), "users": r.get("users", [])}
            for r in msg.get("reactions", [])
        ],
        "files": [
            {
                "id": f.get("id", ""),
                "name": f.get("name", ""),
                "mimetype": f.get("mimetype", ""),
                "size": f.get("size", 0),
                "url": f.get("url_private", ""),
            }
            for f in msg.get("files", [])
        ],
    }



CAMPI_CHE_CAMBIANO = (
    "text",
    "reply_count",
    "latest_reply",
    "reactions",
    "edited",
    "files",
    "subtype",
)


def aggiorna_messaggio(vecchio: dict, nuovo: dict) -> dict:
    ""

    fuori = dict(vecchio)
    for campo in CAMPI_CHE_CAMBIANO:
        if campo in nuovo and nuovo[campo] not in ("", None) and nuovo[campo] != vecchio.get(campo):
            fuori[campo] = nuovo[campo]
    if fuori.get("text") != vecchio.get("text") and vecchio.get("text"):
        fuori["versioni"] = [
            *vecchio.get("versioni", []),
            {"text": vecchio["text"], "edited": vecchio.get("edited", "")},
        ]
    return fuori


def stato_thread(messages: list[dict]) -> dict[str, tuple[str, int]]:
    ""
    risposte: dict[str, list[str]] = {}
    radici: dict[str, str] = {}
    for m in messages:
        ts, tts = m.get("ts", ""), m.get("thread_ts", "")
        if tts and ts != tts:
            risposte.setdefault(tts, []).append(ts)
        elif int(m.get("reply_count") or 0) > 0:
            radici[ts] = m.get("latest_reply", "")
    return {
        r: (ultima or max(risposte.get(r, ["0"])), len(risposte.get(r, [])))
        for r, ultima in radici.items()
    }


def thread_da_riaprire(roots: list[dict], gia: dict[str, tuple[str, int]]) -> list[dict]:
    ""

    fuori = []
    for r in roots:
        ts = r.get("ts")
        if not ts or int(r.get("reply_count") or 0) <= 0:
            continue
        noto = gia.get(ts)
        if (
            noto is None
            or (r.get("latest_reply") and r.get("latest_reply") != noto[0])
            or noto[1] < int(r.get("reply_count") or 0)
        ):
            fuori.append(r)
    return fuori





def build_channel_index() -> dict[str, Path]:
    ""
    index = {}
    if not SLACK_CONVERSATIONS_DIR.exists():
        return index


    for jf in sorted(SLACK_CONVERSATIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            ch_id = data.get("channel_id", "")
            if ch_id:
                index[ch_id] = jf
        except (json.JSONDecodeError, OSError):
            continue
    return index


def get_latest_ts(filepath: Path) -> str:
    ""
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        messages = data.get("messages", [])
        if not messages:
            return "0"
        return max(m.get("ts", "0") for m in messages)
    except (json.JSONDecodeError, OSError, ValueError):
        return "0"


def save_channel_messages(
    channel_id: str,
    channel_name: str,
    messages: list[dict],
    channel_meta: dict | None = None,
) -> int:
    ""




    if not messages:
        return 0

    SLACK_CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    channel_index = build_channel_index()

    parsed = [parse_message(m) for m in messages]
    json_path = channel_index.get(channel_id)

    if json_path and json_path.exists():

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Cannot read {json_path.name}: {e}, creating new")
            data = {
                "channel": channel_name,
                "channel_id": channel_id,
                "total_messages": 0,
                "messages": [],
            }



        per_ts = {m.get("ts"): m for m in data.get("messages", [])}
        nuovi = cambiati = 0
        for m in parsed:
            vecchio = per_ts.get(m["ts"])
            if vecchio is None:
                per_ts[m["ts"]] = m
                nuovi += 1
                continue
            aggiornato = aggiorna_messaggio(vecchio, m)
            if aggiornato != vecchio:
                per_ts[m["ts"]] = aggiornato
                cambiati += 1

        if not nuovi and not cambiati:
            return 0

        data["messages"] = sorted(per_ts.values(), key=lambda m: m.get("ts", "0"))
        data["total_messages"] = len(data["messages"])

        safe_write_json(json_path, data)
        return nuovi

    else:

        is_dm = channel_meta and (channel_meta.get("is_im") or channel_meta.get("is_mpim"))
        if is_dm:
            safe_name = channel_name.replace("/", "-").replace(" ", "-").lower()
            filename = f"dm-{safe_name}.json"
        else:
            safe_name = channel_name.replace("/", "-").replace(" ", "-").lower()
            filename = f"{safe_name}.json"


        target = SLACK_CONVERSATIONS_DIR / filename
        if target.exists():
            stem = target.stem
            filename = f"{stem}-{channel_id}.json"

        parsed.sort(key=lambda m: m.get("ts", "0"))
        new_data = {
            "channel": channel_name,
            "channel_id": channel_id,
            "total_messages": len(parsed),
            "messages": parsed,
        }

        target = SLACK_CONVERSATIONS_DIR / filename
        safe_write_json(target, new_data)
        return len(parsed)





def _resolve_channel_name(ch: dict, users: dict[str, dict]) -> str:
    ""
    ch_name = ch.get("name", ch.get("id", ""))
    if ch.get("is_im"):
        other_user = ch.get("user", "")
        if other_user in users:
            user_info = users[other_user]
            ch_name = user_info.get("real_name") or user_info.get("name") or other_user
    return ch_name


def _download_single_channel(
    token: str,
    ch: dict,
    ch_name: str,
    oldest: str = "0",
    gia: dict[str, tuple[str, int]] | None = None,
) -> tuple[str, int, int, str | None]:
    ""




    ch_id = ch.get("id", "")
    try:
        _ULTIMO_ERRORE.codice = None
        messages = fetch_channel_history(token, ch_id, oldest=oldest)
        if messages is None:
            codice = getattr(_ULTIMO_ERRORE, "codice", None)
            if codice in FUORI_DAL_TOKEN:
                return ch_id, 0, 0, f"{FUORI}{codice}"
            return ch_id, 0, 0, "fetch failed"


        if messages and not _SKIP_THREADS:
            threaded = [m for m in messages if m.get("reply_count", 0) > 0 and m.get("ts")]
            if gia is not None:
                threaded = thread_da_riaprire(threaded, gia)
            for parent in threaded:
                replies = fetch_thread_replies(token, ch_id, parent["ts"])
                for reply in replies:
                    if reply.get("ts") != parent["ts"]:
                        reply["_is_reply"] = True
                        reply["_parent_ts"] = parent["ts"]
                        messages.append(reply)

        if messages:
            new_count = save_channel_messages(ch_id, ch_name, messages, channel_meta=ch)
            return ch_id, len(messages), new_count, None
        return ch_id, 0, 0, None
    except Exception as e:
        return ch_id, 0, 0, str(e)


def download_all(
    token: str,
    channels: list[dict],
    users: dict[str, dict],
    dry_run: bool = False,
    filter_channel_id: str | None = None,
    workers: int = 1,
) -> dict:
    ""





    stats = {
        "channels_processed": 0,
        "channels_skipped": 0,
        "messages_total": 0,
        "messages_new": 0,
        "errors": 0,
    }


    if filter_channel_id:
        channels = [c for c in channels if c.get("id") == filter_channel_id]
        if not channels:
            log.error(f"Channel {filter_channel_id} not found in conversation list")
            return stats

    total = len(channels)
    t0 = time.time()

    if dry_run or workers <= 1:

        for i, ch in enumerate(channels, 1):
            ch_id = ch.get("id", "")
            ch_name = _resolve_channel_name(ch, users)

            elapsed = time.time() - t0
            rate = stats["channels_processed"] / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0

            log.info(
                f"[{i}/{total}] {ch_name} ({ch_id}) | "
                f"{stats['messages_new']} new msgs so far | "
                f"~{remaining:.0f}m left"
            )

            if dry_run:
                result = slack_api("conversations.history", token, {"channel": ch_id, "limit": "1"})
                if result:
                    stats["channels_processed"] += 1
                else:
                    stats["channels_skipped"] += 1
                continue

            _, msg_total, msg_new, err = _download_single_channel(token, ch, ch_name)
            if err and err.startswith(FUORI):
                stats["fuori_dal_token"] = stats.get("fuori_dal_token", 0) + 1
                log.info(f"  -> chat not visible to the token ({err[len(FUORI) :]})")
            elif err:
                stats["errors"] += 1
                log.warning(f"  -> ERROR: {err}")
            else:
                stats["channels_processed"] += 1
                stats["messages_total"] += msg_total
                stats["messages_new"] += msg_new
                if msg_total > 0:
                    log.info(f"  -> {msg_total} messages fetched, {msg_new} new")

    else:

        log.info(
            f"Parallel download: {workers} workers, shared rate limiter at {1 / API_DELAY:.0f} req/min"
        )
        stats_lock = threading.Lock()
        counter = {"done": 0}

        def _worker(ch: dict) -> None:
            ch_id = ch.get("id", "")
            ch_name = _resolve_channel_name(ch, users)

            _, msg_total, msg_new, err = _download_single_channel(token, ch, ch_name)

            with stats_lock:
                counter["done"] += 1
                done = counter["done"]

                if err and err.startswith(FUORI):
                    stats["fuori_dal_token"] = stats.get("fuori_dal_token", 0) + 1
                elif err:
                    stats["errors"] += 1
                    log.warning(f"[{done}/{total}] {ch_name} -> ERROR: {err}")
                else:
                    stats["channels_processed"] += 1
                    stats["messages_total"] += msg_total
                    stats["messages_new"] += msg_new

                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    remaining = (total - done) / rate / 60 if rate > 0 else 0

                    if msg_total > 0:
                        log.info(
                            f"[{done}/{total}] {ch_name} -> {msg_total} msgs, {msg_new} new "
                            f"| total new: {stats['messages_new']} | ~{remaining:.0f}m left"
                        )
                    elif done % 50 == 0:
                        log.info(
                            f"[{done}/{total}] progress | "
                            f"{stats['messages_new']} new | ~{remaining:.0f}m left"
                        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, ch) for ch in channels]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    log.error(f"Worker exception: {e}")

    elapsed = time.time() - t0
    log.info(
        f"Download complete in {elapsed / 60:.1f}m: "
        f"{stats['channels_processed']}/{total} channels, "
        f"{stats['messages_new']} new messages"
    )
    return stats


def _inizio(existing_path: Path | None) -> tuple[str, dict[str, tuple[str, int]] | None]:
    ""

    if not existing_path:
        return "0", None
    try:
        messages = json.loads(existing_path.read_text(encoding="utf-8")).get("messages", [])
    except (OSError, ValueError):
        return "0", None
    if not messages:
        return "0", {}
    ultimo = max(m.get("ts", "0") for m in messages)
    inizio = ultimo
    if FINESTRA_GIORNI > 0:
        finestra = time.time() - FINESTRA_GIORNI * 86400
        if float(ultimo or 0) > finestra:
            inizio = f"{finestra:.6f}"
    return inizio, stato_thread(messages)


def recupera_thread(
    token: str,
    file_index: dict[str, Path],
    esclusi: set[str],
    raggiungibili: set[str] | None = None,
) -> dict:
    ""






    stats = {
        "canali": 0,
        "radici": 0,
        "risposte_nuove": 0,
        "errori": 0,
        "chat_fuori_dal_token": 0,
        "radici_fuori_dal_token": 0,
    }
    for ch_id, path in sorted(file_index.items()):
        if ch_id in esclusi:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        messages = data.get("messages", [])
        gia = stato_thread(messages)
        radici = [
            m
            for m in messages
            if (not m.get("thread_ts") or m.get("thread_ts") == m.get("ts"))
            and int(m.get("reply_count") or 0) > gia.get(m.get("ts"), ("", 0))[1]
        ]
        if not radici:
            continue
        if raggiungibili is not None and ch_id not in raggiungibili:
            stats["chat_fuori_dal_token"] += 1
            stats["radici_fuori_dal_token"] += len(radici)
            log.info(
                f"  {data.get('channel', ch_id)}: {len(radici)} threads in a chat not visible to the token, skipped"
            )
            continue
        raccolte: list[dict] = []
        for r in radici:
            try:
                arrivate = fetch_thread_replies(token, ch_id, r["ts"])
            except Exception as e:  # noqa: BLE001 - one failing root must not stop the others
                stats["errori"] += 1
                log.warning(f"  {ch_id} {r.get('ts')}: {e}")
                continue
            if not arrivate:
                stats["errori"] += 1
                continue
            raccolte.extend(arrivate)
        stats["canali"] += 1
        stats["radici"] += len(radici)
        nuove = save_channel_messages(ch_id, data.get("channel", ch_id), raccolte)
        stats["risposte_nuove"] += nuove
        log.info(
            f"  {data.get('channel', ch_id)}: {len(radici)} threads reopened, {nuove} new replies"
        )
    return stats


def thread_con_risposte_recenti(token: str, team_ids: list[str], giorni: int) -> dict:
    ""


    from datetime import datetime, timedelta
    from urllib.parse import parse_qs, urlparse

    dopo = (datetime.now(UTC) - timedelta(days=giorni)).strftime("%Y-%m-%d")
    trovati: dict[str, dict[str, set[str]]] = {"_errori": {}}
    for team in team_ids:
        pagina = 1
        while True:
            r = slack_api(
                "search.messages",
                token,
                {
                    "query": f"is:thread after:{dopo}",
                    "count": "100",
                    "page": str(pagina),
                    "sort": "timestamp",
                    "sort_dir": "desc",
                },
            )
            if not r:
                trovati["_errori"].setdefault(team, set()).add(str(pagina))
                break
            risultati = r.get("messages", {})
            for x in risultati.get("matches", []):
                canale = (x.get("channel") or {}).get("id")
                radice = parse_qs(urlparse(x.get("permalink", "")).query).get("thread_ts", [""])[0]
                if canale and radice and x.get("ts") and x["ts"] != radice:
                    trovati.setdefault(canale, {}).setdefault(radice, set()).add(x["ts"])
            if pagina >= int(risultati.get("paging", {}).get("pages") or 1):
                break
            pagina += 1
    return trovati


def risposte_tardive(
    token: str,
    team_ids: list[str],
    esclusi: set[str],
    raggiungibili: set[str] | None = None,
) -> dict:
    ""



    stats = {"thread_tardivi": 0, "risposte_tardive": 0, "ricerca_errori": 0}
    if FINESTRA_GIORNI <= 0:
        return stats
    trovati = thread_con_risposte_recenti(token, team_ids, FINESTRA_GIORNI)
    stats["ricerca_errori"] = sum(len(v) for v in trovati.pop("_errori").values())
    inizio_finestra = time.time() - FINESTRA_GIORNI * 86400
    file_index = build_channel_index()
    for canale, radici in sorted(trovati.items()):
        path = file_index.get(canale)
        if (
            not path
            or canale in esclusi
            or (raggiungibili is not None and canale not in raggiungibili)
        ):
            continue
        vecchie = {r: ts for r, ts in radici.items() if float(r) < inizio_finestra}
        if not vecchie:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        salvati = {m.get("ts") for m in data.get("messages", [])}
        raccolte: list[dict] = []
        for radice, risposte in sorted(vecchie.items()):
            if risposte <= salvati:
                continue
            try:
                arrivate = fetch_thread_replies(token, canale, radice)
            except Exception as e:  # noqa: BLE001 - one failing thread must not stop the others
                stats["ricerca_errori"] += 1
                log.warning(f"  {canale} {radice}: {e}")
                continue
            raccolte.extend(arrivate or [])
            stats["thread_tardivi"] += 1
        if raccolte:
            nuove = save_channel_messages(canale, data.get("channel", canale), raccolte)
            stats["risposte_tardive"] += nuove
            log.info(
                f"  {data.get('channel', canale)}: late replies to old threads, {nuove} new"
            )
    return stats


def download_incremental(
    token: str,
    channels: list[dict],
    users: dict[str, dict],
    dry_run: bool = False,
    filter_channel_id: str | None = None,
    workers: int = 1,
) -> dict:
    ""





    stats = {
        "channels_processed": 0,
        "channels_skipped": 0,
        "messages_new": 0,
        "errors": 0,
        "fuori_dal_token": 0,
    }

    file_index = build_channel_index()


    if filter_channel_id:
        channels = [c for c in channels if c.get("id") == filter_channel_id]
        if not channels:
            log.error(f"Channel {filter_channel_id} not found in conversation list")
            return stats

    total = len(channels)
    t0 = time.time()

    if dry_run or workers <= 1:
        for i, ch in enumerate(channels, 1):
            ch_id = ch.get("id", "")
            ch_name = _resolve_channel_name(ch, users)

            existing_path = file_index.get(ch_id)
            latest_ts, gia = _inizio(existing_path)

            if dry_run:
                label = f"from ts={latest_ts}" if latest_ts != "0" else "full (new channel)"
                log.info(f"[{i}/{total}] {ch_name} ({ch_id}) -> would fetch {label}")
                stats["channels_processed"] += 1
                continue

            log.info(
                f"[{i}/{total}] {ch_name} ({ch_id}) "
                f"{'incremental from ' + latest_ts if latest_ts != '0' else 'full (new channel)'}"
            )

            _, _, msg_new, err = _download_single_channel(
                token, ch, ch_name, oldest=latest_ts, gia=gia
            )
            if err and err.startswith(FUORI):
                stats["fuori_dal_token"] += 1
                log.info(f"  -> chat not visible to the token ({err[len(FUORI) :]})")
            elif err:
                stats["errors"] += 1
            else:
                stats["channels_processed"] += 1
                stats["messages_new"] += msg_new
                if msg_new > 0:
                    log.info(f"  -> {msg_new} new messages")

    else:
        log.info(f"Parallel incremental: {workers} workers")
        stats_lock = threading.Lock()
        counter = {"done": 0}

        def _worker(ch: dict) -> None:
            ch_id = ch.get("id", "")
            ch_name = _resolve_channel_name(ch, users)
            existing_path = file_index.get(ch_id)
            latest_ts, gia = _inizio(existing_path)

            _, _, msg_new, err = _download_single_channel(
                token, ch, ch_name, oldest=latest_ts, gia=gia
            )

            with stats_lock:
                counter["done"] += 1
                done = counter["done"]
                if err and err.startswith(FUORI):
                    stats["fuori_dal_token"] += 1
                elif err:
                    stats["errors"] += 1
                else:
                    stats["channels_processed"] += 1
                    stats["messages_new"] += msg_new
                    if msg_new > 0:
                        log.info(f"[{done}/{total}] {ch_name} -> {msg_new} new msgs")
                    elif done % 50 == 0:
                        elapsed = time.time() - t0
                        rate = done / elapsed if elapsed > 0 else 0
                        remaining = (total - done) / rate / 60 if rate > 0 else 0
                        log.info(f"[{done}/{total}] progress | ~{remaining:.0f}m left")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_worker, ch) for ch in channels]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    log.error(f"Worker exception: {e}")

    elapsed = time.time() - t0
    log.info(
        f"Incremental download complete in {elapsed / 60:.1f}m: "
        f"{stats['channels_processed']}/{total} channels, "
        f"{stats['messages_new']} new messages"
    )
    return stats





def main():
    global _SKIP_THREADS, FINESTRA_GIORNI  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="Slack L0 Download -- SBK")
    parser.add_argument("--full", action="store_true", help="Full download (default: incremental)")
    parser.add_argument(
        "--refresh-channels",
        action="store_true",
        help="Force refresh conversations list cache",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count conversations without downloading"
    )
    parser.add_argument(
        "--channel", default=None, help="Download single channel by ID (e.g. C0123456789)"
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Skip users.list fetch (use existing slack-users.json)",
    )
    parser.add_argument(
        "--no-threads",
        action="store_true",
        help="Skip fetching thread replies (faster, no conversations.replies calls)",
    )
    parser.add_argument(
        "--include-excluded",
        "--include-clients",
        dest="include_clients",
        action="store_true",
        help="Also download the channels excluded in sbk.config.json (default: skip them)",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Also read the archived conversations you are a member of (default: skip them)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel download workers (default: 1, recommended: 3-5)",
    )
    parser.add_argument(
        "--thread-window",
        type=int,
        default=FINESTRA_GIORNI,
        dest="finestra_thread",
        metavar="DAYS",
        help=f"days to re-read for new thread replies (default {FINESTRA_GIORNI}, 0 = off)",
    )
    parser.add_argument(
        "--missing-replies",
        action="store_true",
        dest="thread_mancanti",
        help="one-off: fetch the replies missing from already saved threads, then exit",
    )
    # Older Italian names, kept as hidden aliases.
    parser.add_argument("--finestra-thread", type=int, dest="finestra_thread", help=argparse.SUPPRESS)
    parser.add_argument("--thread-mancanti", action="store_true", dest="thread_mancanti", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()


    _SKIP_THREADS = args.no_threads
    FINESTRA_GIORNI = args.finestra_thread


    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_file = SLACK_CONVERSATIONS_DIR.parent / "download.log"
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
    log.info("SBK Slack L0 Download")
    log.info("=" * 60)


    token = get_slack_token()
    if not token:
        log.error(
            "No Slack token found. Copy the User OAuth Token (xoxp-) of your Slack app into "
            "the Keychain (service sbk-slack, account user-token) or into .env as SLACK_USER_TOKEN."
        )
        sys.exit(1)

    log.info("Token type: user token (xoxp)")


    auth_result = slack_api("auth.test", token)
    if not auth_result:
        log.error("auth.test failed. Token may be invalid or expired.")
        sys.exit(1)
    log.info(
        f"Authenticated as: {auth_result.get('user', '?')} in team {auth_result.get('team', '?')}"
    )




    team_ids = token_workspace(auth_result)


    users = {}
    if args.skip_users and SLACK_USERS_FILE.exists():
        try:
            with open(SLACK_USERS_FILE, encoding="utf-8") as f:
                users = json.load(f)
            log.info(f"Loaded {len(users)} users from {SLACK_USERS_FILE.name}")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load {SLACK_USERS_FILE.name}: {e}, fetching from API")
            users = {}

    if not users:
        log.info("Fetching user directory...")
        users = fetch_all_users(token, team_ids=team_ids)
        if users and not args.dry_run:
            save_users(users)


    excluded_ids = set()
    if not args.include_clients:
        excluded_ids = load_exclusion_set()


    channels = None
    if not args.refresh_channels and not args.full:
        cache = load_conversations_cache()
        if cache:
            channels = cache.get("channels", [])
            cached_at = cache.get("cached_at", "")
            age_hours = 0.0
            if cached_at:
                from datetime import datetime

                try:
                    age_hours = (
                        datetime.now(UTC) - datetime.fromisoformat(cached_at).replace(tzinfo=UTC)
                    ).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass
            log.info(f"Conversations: using cache ({len(channels)} channels, {age_hours:.1f}h old)")

    if channels is None:
        log.info("Conversations: fetching from API...")
        channels = list_all_conversations(token, team_ids=team_ids)
        if channels and not args.dry_run:
            save_conversations_cache(channels)

    if not channels:
        log.error(
            "No conversations found. Check token permissions (channels:read, groups:read, im:read, mpim:read)"
        )
        sys.exit(1)

    # Only what your own account is in; archived conversations only with --include-archived.
    channels = keep_your_conversations(channels, include_archived=args.include_archived)

    if excluded_ids:
        before = len(channels)
        channels = [c for c in channels if c.get("id", "") not in excluded_ids]
        skipped = before - len(channels)
        if skipped > 0:
            log.info(
                f"Excluded {skipped} channels listed in sbk.config.json ({len(channels)} remaining)"
            )


    if not args.dry_run:
        save_channels_metadata(channels, users)


    channel_index = build_channel_index()
    log.info(f"Existing L0 files: {len(channel_index)}")

    if args.thread_mancanti:
        log.info("Mode: replies missing from already saved threads (--missing-replies)")
        stats = recupera_thread(
            token, channel_index, excluded_ids, raggiungibili={c.get("id") for c in channels}
        )
        for k, v in stats.items():
            log.info(f"  {k}: {v}")
        return


    if args.full:
        log.info("Mode: full (--full flag)")
        stats = download_all(
            token,
            channels,
            users,
            dry_run=args.dry_run,
            filter_channel_id=args.channel,
            workers=args.workers,
        )
    else:
        log.info("Mode: incremental (default)")
        stats = download_incremental(
            token,
            channels,
            users,
            dry_run=args.dry_run,
            filter_channel_id=args.channel,
            workers=args.workers,
        )
        if not args.dry_run and not args.channel and not _SKIP_THREADS:
            log.info("Late replies to threads older than the window (search.messages)")
            stats.update(
                risposte_tardive(
                    token, team_ids, excluded_ids, raggiungibili={c.get("id") for c in channels}
                )
            )


    log.info("=" * 60)
    log.info("Summary:")
    for k, v in stats.items():
        log.info(f"  {k}: {v}")


    if not args.dry_run:
        final_index = build_channel_index()
        log.info(f"L0 files: {len(channel_index)} -> {len(final_index)}")


        try:
            from event_bus import EventBus

            EventBus.emit("slack", "l0", channels=len(final_index))
        except Exception as e:
            log.warning(f"EventBus emit failed: {e}")

        mark_last_run("slack-channels")
    log.info("=" * 60)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-slack-download", source="slack", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
