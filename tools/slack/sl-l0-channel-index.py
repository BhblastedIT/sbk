#!/usr/bin/env python3
"""Build the Slack channel index (L0) of your workspace and flag the channels you excluded.

One user token reads one workspace: the one your personal Slack app is installed in
(auth.test says which). The index lists its public and private channels, marks the
ones you are a member of, and flags with "is_excluded" the channels whose name
matches slack.exclude_channel_patterns or whose id is in slack.exclude_channel_ids
(sbk.config.json). The download and every later step skip the excluded channels.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
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
    SLACK_EXCLUDE_CHANNEL_PATTERNS,
    safe_write_json,
)

CHANNEL_INDEX_FILE = DATA_ROOT / "slack" / "channel-index.json"

API_DELAY = 1.3
LIST_PAGE_SIZE = 200
MAX_RETRIES = 3
RETRY_BACKOFF = 5

log = logging.getLogger("slack-idx")


def get_user_token() -> str | None:
    """Your user token (xoxp-): Keychain sbk-slack/user-token, then SLACK_USER_TOKEN."""
    token = get_secret("sbk-slack", "user-token")
    if token and token.startswith("xoxp-"):
        log.debug("Using user-token from Keychain")
        return token

    token = os.environ.get("SBK_SLACK_USER_TOKEN") or os.environ.get("SLACK_USER_TOKEN")
    if token and token.startswith("xoxp-"):
        log.debug("Using user token from env")
        return token

    return None


def slack_api(
    method: str,
    token: str,
    params: dict | None = None,
    retry: int = 0,
) -> dict | None:
    """Call a Slack Web API method, with retries on rate limits and server errors."""
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
            log.warning(f"Slack API {method} error '{error}', retry {retry + 1}/{MAX_RETRIES}")
            time.sleep(wait)
            return slack_api(method, token, params, retry=retry + 1)

        return {"ok": False, "error": error}

    except requests.exceptions.Timeout:
        if retry < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * (retry + 1))
            return slack_api(method, token, params, retry=retry + 1)
        log.error(f"Slack API {method} timed out after {MAX_RETRIES} retries")
        return None
    except Exception as e:
        if retry < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * (retry + 1))
            return slack_api(method, token, params, retry=retry + 1)
        log.error(f"Slack API {method} failed: {e}")
        return None


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    """The exclusion patterns of sbk.config.json; a broken one stops the run."""
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p))
        except re.error as e:
            log.error(f"slack.exclude_channel_patterns: invalid regular expression {p!r} ({e})")
            sys.exit(2)
    return compiled


def is_excludable(cid: str, name: str, patterns: list[re.Pattern], excluded_ids: frozenset[str]) -> bool:
    """True if you excluded this channel, by name pattern or by id."""
    return cid in excluded_ids or any(p.search(name or "") for p in patterns)


def _list_paged(method: str, token: str, conv_type: str) -> list[dict] | None:
    """Every page of conversations.list or users.conversations for one type."""
    out: list[dict] = []
    cursor = None
    while True:
        params = {
            "types": conv_type,
            "limit": str(LIST_PAGE_SIZE),
            "exclude_archived": "false",
        }
        if cursor:
            params["cursor"] = cursor

        result = slack_api(method, token, params)
        if not result or not result.get("ok"):
            err = result.get("error", "no response") if result else "no response"
            log.warning(f"  {method}({conv_type}) error: {err}")
            return out if out else None

        out.extend(result.get("channels", []))

        cursor = result.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return out
        time.sleep(API_DELAY)


def list_workspace_channels(token: str) -> tuple[list[dict], set[str]]:
    """Public and private channels of the workspace, and the ids you are a member of."""
    channels: list[dict] = []
    member_ids: set[str] = set()
    for conv_type in ("public_channel", "private_channel"):
        channels.extend(_list_paged("conversations.list", token, conv_type) or [])
        member_ids.update(c["id"] for c in _list_paged("users.conversations", token, conv_type) or [] if c.get("id"))
    return channels, member_ids


def build_channel_record(
    ch: dict,
    team_id: str,
    ws_name: str,
    is_member: bool,
    patterns: list[re.Pattern],
    excluded_ids: frozenset[str],
) -> dict:
    """One entry of channel-index.json."""
    cid = ch.get("id", "")
    name = ch.get("name", ch.get("name_normalized", ""))

    return {
        "id": cid,
        "name": name,
        "workspace_id": team_id,
        "workspace_name": ws_name,
        "is_member": is_member,
        "is_private": ch.get("is_private", False),
        "is_archived": ch.get("is_archived", False),
        "is_shared": ch.get("is_shared", False) or ch.get("is_ext_shared", False),
        "is_excluded": is_excludable(cid, name, patterns, excluded_ids),
        "topic": (ch.get("topic") or {}).get("value", ""),
        "purpose": (ch.get("purpose") or {}).get("value", ""),
        "num_members": ch.get("num_members", 0),
        "creator": ch.get("creator", ""),
        "created": ch.get("created", 0),
        "updated": ch.get("updated", 0),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Slack channel index of the workspace your user token belongs to"
    )
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't save")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    patterns = compile_patterns(SLACK_EXCLUDE_CHANNEL_PATTERNS)

    token = get_user_token()
    if not token:
        log.error(
            "No Slack user token (xoxp-) found. Copy the User OAuth Token of your Slack app into "
            "the Keychain (service sbk-slack, account user-token) or into .env as SLACK_USER_TOKEN."
        )
        sys.exit(1)

    auth = slack_api("auth.test", token)
    if not auth or not auth.get("ok"):
        err = auth.get("error", "no response") if auth else "no response"
        log.error(f"auth.test failed ({err}): the token is invalid or was revoked.")
        sys.exit(1)
    team_id = auth.get("team_id", "")
    ws_name = auth.get("team", team_id)
    log.info(f"Slack channel index: workspace {ws_name} ({team_id}), user {auth.get('user', '?')}")

    channels, member_ids = list_workspace_channels(token)

    all_channels: dict[str, dict] = {}
    for ch in channels:
        cid = ch.get("id", "")
        if not cid or cid in all_channels:
            continue
        all_channels[cid] = build_channel_record(
            ch, team_id, ws_name, cid in member_ids, patterns, SLACK_EXCLUDE_CHANNEL_IDS
        )

    total = len(all_channels)
    member_total = sum(1 for c in all_channels.values() if c["is_member"])
    private_total = sum(1 for c in all_channels.values() if c["is_private"])
    archived_total = sum(1 for c in all_channels.values() if c["is_archived"])
    excluded_total = sum(1 for c in all_channels.values() if c.get("is_excluded"))
    downloadable = sum(
        1
        for c in all_channels.values()
        if c["is_member"] and not c.get("is_excluded") and not c["is_archived"]
    )

    log.info(f"\n{'=' * 60}")
    log.info(f"TOTAL: {total} channels")
    log.info(f"  Member of:    {member_total}")
    log.info(f"  Private:      {private_total}")
    log.info(f"  Archived:     {archived_total}")
    log.info(f"  Excluded:     {excluded_total} (slack.exclude_channel_* in sbk.config.json)")
    log.info(f"  Downloadable: {downloadable} (member + not excluded + not archived)")

    if args.dry_run:
        log.info("Dry run — not saving.")
        return

    index = {
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace_id": team_id,
        "workspace_name": ws_name,
        "source": "conversations.list",
        "total_channels": total,
        "total_member": member_total,
        "total_excluded": excluded_total,
        "total_downloadable": downloadable,
        "channels": sorted(all_channels.values(), key=lambda c: c["name"]),
        "lookup": {c["name"]: c["id"] for c in all_channels.values()},
    }

    safe_write_json(CHANNEL_INDEX_FILE, index)

    log.info(f"Saved to {CHANNEL_INDEX_FILE}")
    log.info(f"Lookup: {len(index['lookup'])} name->id mappings")


from pipeline_decorator import pipeline_step  # noqa: E402


@pipeline_step(name="l0-slack-channel-index", source="slack", stage="l0")
def run():
    main()


if __name__ == "__main__":
    run()
