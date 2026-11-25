#!/usr/bin/env python3
"""Enrich Slack L0 conversations into L1."""


















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import (  # noqa: E402
    DATA_ROOT,
    NICKNAME_ALIASES,
    PERSONIO_PROCESSED_DIR,
    SLACK_CHANNEL_INDEX_FILE,
    SLACK_CHANNELS_FILE,
    SLACK_CONVERSATIONS_DIR,
    SLACK_DIR,
    SLACK_USER_NAMES,
    is_own_name,
    mark_last_run,
    safe_write_json,
    safe_write_parquet,
)

RAW_DIR = SLACK_CONVERSATIONS_DIR
CHANNELS_FILE = SLACK_CHANNELS_FILE
PROCESSED_DIR = SLACK_DIR
PERSONIO_FILE = PERSONIO_PROCESSED_DIR / "employees.parquet"
SLACK_USERS_FILE = DATA_ROOT / "slack" / "slack-users.json"

log = logging.getLogger("slack-enrich")


USER_ID_RE = re.compile(r"^[UB][A-Z0-9]{7,}$")


MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)>")


SYSTEM_PATTERNS = [
    "has joined the channel",
    "has left the channel",
    "set the channel topic:",
    "set the channel purpose:",
    "set the channel description:",
    "was added to this channel",
    "has renamed the channel",
    "added an integration to this channel",
    "removed an integration from this channel",
    "uploaded a file:",
    "pinned a message to this channel",
    "This content can't be displayed",
    "archived the channel",
    "unarchived the channel",
]


BOT_INDICATORS = {
    "slackbot",
    "google calendar",
    "google drive",
    "zapier",
    "zendesk",
    "akiflow",
    "clickup",
    "loom",
    "perplexity bot",
    "simple poll",
    "translate",
    "mcp-claude",
}


BOT_NAME_PATTERNS = re.compile(
    r"(?:"
    r"bot$"
    r"|^wf_bot_"
    r"|customer.importer"
    r")",
    re.IGNORECASE,
)


DEACTIVATED_RE = re.compile(r"^deactivateduser\d*$", re.IGNORECASE)








# Fixed names for ids Slack no longer resolves: sbk.config.json "slack.user_names".
VERIFIED_UID_NAMES: dict[str, str] = dict(SLACK_USER_NAMES)



DEACTIVATED_LABEL = "Deactivated User"





def is_system_message(text: str) -> bool:
    ""
    if not text:
        return True
    for pattern in SYSTEM_PATTERNS:
        if pattern in text:
            return True
    return False


def is_deactivated_user(user_key: str) -> bool:
    ""





    if not user_key:
        return False
    return bool(DEACTIVATED_RE.match(user_key.strip()))


def is_bot_user(user_key: str) -> bool:
    ""




    lower = user_key.lower()
    if lower in BOT_INDICATORS:
        return True

    if USER_ID_RE.match(user_key) and user_key.startswith("B"):
        return True

    if BOT_NAME_PATTERNS.search(lower):
        return True
    return False


def ts_to_datetime(ts_str: str) -> datetime | None:
    ""
    try:
        ts_float = float(ts_str)
        return datetime.fromtimestamp(ts_float, tz=UTC)
    except (ValueError, TypeError, OSError):
        return None


def ts_to_date(ts_str: str) -> str:
    ""
    dt = ts_to_datetime(ts_str)
    return dt.strftime("%Y-%m-%d") if dt else ""


def ts_to_iso(ts_str: str) -> str:
    ""
    dt = ts_to_datetime(ts_str)
    return dt.isoformat() if dt else ""


def load_json(path: Path) -> dict | None:
    ""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot parse {path.name}: {e}")
        return None





def load_personio_email_map() -> tuple[dict[str, str], dict[str, str]]:
    ""






















    if not PERSONIO_FILE.exists():
        log.warning(f"Personio file not found: {PERSONIO_FILE}")
        return {}, {}

    try:
        df = pd.read_parquet(PERSONIO_FILE)
    except Exception as e:
        log.warning(f"Cannot read Personio file: {e}")
        return {}, {}

    local_to_name: dict[str, str] = {}
    name_to_email: dict[str, str] = {}


    stato_vincitore: dict[str, str] = {}
    stato_vincitore_nome: dict[str, str] = {}
    contesi: dict[str, list[str]] = {}
    contesi_nome: dict[str, list[str]] = {}

    def _assegna(
        chiave: str,
        valore: str,
        etichetta: str,
        status: str,
        mappa: dict[str, str],
        stato: dict[str, str],
        registro: dict[str, list[str]],
    ) -> None:
        ""
        if chiave in mappa:
            registro.setdefault(chiave, [f"{mappa[chiave]} ({stato[chiave]})"]).append(
                f"{etichetta} ({status})"
            )
            if stato[chiave] == "active" and status != "active":
                return
        mappa[chiave] = valore
        stato[chiave] = status

    for _, row in df.iterrows():
        email = str(row.get("email", "")).strip()
        name = str(row.get("name", "")).strip()
        if email and "@" in email and name:



            status = str(row.get("status", "")).strip().lower()
            local = email.split("@")[0].lower()
            _assegna(local, name, name, status, local_to_name, stato_vincitore, contesi)
            _assegna(
                name,
                email.lower(),
                email.lower(),
                status,
                name_to_email,
                stato_vincitore_nome,
                contesi_nome,
            )

    for local in sorted(contesi):
        log.warning(
            "Personio: duplicate local-part '%s' among %s -> winner '%s'",
            local,
            ", ".join(contesi[local]),
            local_to_name[local],
        )
    for nome in sorted(contesi_nome):
        log.warning(
            "Personio: homonyms '%s' among %s -> winner '%s'",
            nome,
            ", ".join(contesi_nome[nome]),
            name_to_email[nome],
        )

    log.info(
        f"Personio: loaded {len(local_to_name)} email -> name mappings "
        f"({len(contesi)} contested local-parts, {len(contesi_nome)} homonyms)"
    )
    return local_to_name, name_to_email


def resolve_nickname(nickname: str, personio_map: dict[str, str]) -> str:
    ""







    if not nickname:
        return nickname

    lower = nickname.lower()


    if lower in personio_map:
        return personio_map[lower]


    stripped = re.sub(r"\d+$", "", lower)
    if stripped and stripped != lower and stripped in personio_map:
        return personio_map[stripped]


    if lower.startswith("deactivateduser"):
        return f"[{DEACTIVATED_LABEL}] {nickname}"


    return nickname


def resolve_display_name(name: str, personio_map: dict[str, str]) -> str:
    ""






    if not name:
        return name


    if " " in name and name != name.lower():
        return name


    if USER_ID_RE.match(name):
        return f"Unknown ({name})"


    resolved = resolve_nickname(name, personio_map)
    if resolved != name:
        return resolved



    if name == name.lower() and " " not in name and len(name) > 2:

        if name.startswith("deactivateduser"):
            return f"[{DEACTIVATED_LABEL}] {name}"
        return name.title()

    return name


def load_channels_metadata() -> dict:
    ""



    if not CHANNELS_FILE.exists():
        log.warning(f"Channels file not found: {CHANNELS_FILE}")
        return {}

    data = load_json(CHANNELS_FILE)
    if not data or not isinstance(data, list):
        return {}

    channels = {}
    for c in data:
        cid = c.get("id", "")
        if cid:
            channels[cid] = {
                "channel_id": cid,
                "channel_name": c.get("name", ""),
                "is_private": c.get("p", False),
                "is_im": c.get("im", False),
                "is_mpim": c.get("mp", False),
                "purpose": c.get("pu", ""),
            }

    log.info(f"Loaded {len(channels)} channels from metadata")
    return channels


def classify_channel(channel_name: str, channel_meta: dict | None) -> str:
    ""
    if channel_meta:
        if channel_meta.get("is_im"):
            return "dm"
        if channel_meta.get("is_mpim"):
            return "group_dm"
        if channel_meta.get("is_private"):
            return "private"
        return "public"


    if channel_name.startswith("dm-"):
        return "dm"
    if channel_name.startswith("mpdm-"):
        return "group_dm"
    return "unknown"


def build_user_lookup(conversations: list[dict], personio_map: dict[str, str]) -> tuple[dict, dict]:
    ""











    uid_to_name = {}
    name_to_uid = {}


    for uid, name in VERIFIED_UID_NAMES.items():
        uid_to_name[uid] = name
        name_to_uid[name] = uid


    if SLACK_USERS_FILE.exists():
        try:
            su_data = json.loads(SLACK_USERS_FILE.read_text(encoding="utf-8"))
            su_users = su_data.values() if isinstance(su_data, dict) else su_data
            su_count = 0
            for u in su_users:
                uid = u.get("id", "")
                real_name = u.get("real_name") or u.get("name", "")
                if uid and real_name and uid not in uid_to_name:
                    uid_to_name[uid] = real_name
                    if real_name not in name_to_uid:
                        name_to_uid[real_name] = uid
                    su_count += 1
            log.info("Loaded %d user mappings from slack-users.json", su_count)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load slack-users.json: %s", e)


    join_patterns = [
        "has joined the channel",
        "has joined the conversation",
        "è entrato/a nel canale",
        "ist dem Channel beigetreten",
        "se ha unido al canal",
    ]


    for conv in conversations:
        messages = conv.get("messages", [])

        for msg in messages:
            user = msg.get("user", "")
            text = msg.get("text", "")

            if not user:
                continue


            if not USER_ID_RE.match(user):

                is_join = any(p in text for p in join_patterns)
                if is_join:
                    uid_match = MENTION_RE.search(text)
                    if uid_match:
                        uid = uid_match.group(1)

                        if uid not in uid_to_name or USER_ID_RE.match(uid_to_name.get(uid, "")):
                            uid_to_name[uid] = user
                            name_to_uid[user] = uid




    _resolve_mpdm_slugs(conversations, uid_to_name, name_to_uid, personio_map)



    for uid in list(uid_to_name.keys()):
        name = uid_to_name[uid]
        if name and not USER_ID_RE.match(name):
            resolved = resolve_nickname(name, personio_map)
            if resolved != name:
                uid_to_name[uid] = resolved
                name_to_uid[resolved] = uid





    _resolve_dm_slugs_to_uid(conversations, uid_to_name, name_to_uid, personio_map)

    log.info(f"User lookup: {len(uid_to_name)} user_id -> name mappings")
    return uid_to_name, name_to_uid


def _resolve_dm_slugs_to_uid(
    conversations: list[dict],
    uid_to_name: dict,
    name_to_uid: dict,
    personio_map: dict[str, str],
) -> None:
    ""







    for conv in conversations:
        dm_with = conv.get("dm_with", "")
        if not dm_with or USER_ID_RE.match(dm_with):
            continue

        if dm_with in name_to_uid:
            continue

        messages = conv.get("messages", [])
        if not messages:
            continue


        msg_uids = set()
        for msg in messages:
            u = msg.get("user", "")
            if u and USER_ID_RE.match(u):
                msg_uids.add(u)


        unknown_uids = {u for u in msg_uids if u not in uid_to_name}


        if len(unknown_uids) == 1:
            uid = list(unknown_uids)[0]

            resolved = resolve_nickname(dm_with, personio_map)
            name = resolved if resolved != dm_with else dm_with
            uid_to_name[uid] = name
            name_to_uid[name] = uid
            if name != dm_with:
                name_to_uid[dm_with] = uid
            log.debug(f"DM slug resolved: {dm_with} -> {uid} ({name})")


def _resolve_mpdm_slugs(
    conversations: list[dict],
    uid_to_name: dict,
    name_to_uid: dict,
    personio_map: dict[str, str],
) -> None:
    ""








    known_slugs = {}



    # Handles you declared in sbk.config.json "nickname_aliases" (e.g. {"samd": "sam demo"});
    # nothing is built in. The Personio map below adds the rest.
    known_slugs.update({k: v.title() for k, v in NICKNAME_ALIASES.items() if " " not in k})


    for local, name in personio_map.items():
        if local not in known_slugs:
            known_slugs[local] = name

    for conv in conversations:
        channel = conv.get("channel", "")
        if not channel.startswith("mpdm-"):
            continue

        messages = conv.get("messages", [])


        all_users = set()
        for msg in messages:
            u = msg.get("user", "")
            if u:
                all_users.add(u)


        unresolved_ids = {u for u in all_users if USER_ID_RE.match(u) and u not in uid_to_name}
        resolved_names = {u for u in all_users if not USER_ID_RE.match(u)}

        if not unresolved_ids:
            continue


        parts = channel[5:]
        parts = re.sub(r"-\d+$", "", parts)
        slugs = parts.split("--")


        resolved_name_slugs = set()
        for rn in resolved_names:

            for s in slugs:
                if s in known_slugs and known_slugs[s] == rn:
                    resolved_name_slugs.add(s)


        for uid in all_users:
            if uid in uid_to_name:
                name = uid_to_name[uid]
                for s in slugs:
                    if s in known_slugs and known_slugs[s] == name:
                        resolved_name_slugs.add(s)

        unmatched_slugs = [
            s for s in slugs if s not in resolved_name_slugs and s not in known_slugs
        ]


        if len(unresolved_ids) == 1 and len(unmatched_slugs) == 1:
            uid = list(unresolved_ids)[0]
            slug = unmatched_slugs[0]

            name = personio_map.get(slug, slug.replace(".", " ").replace("-", " ").title())
            uid_to_name[uid] = name
            name_to_uid[name] = uid
            log.debug(f"MPDM resolved: {uid} -> {name} (slug={slug}, channel={channel})")





def canali_cliente_esclusi() -> set[str]:
    ""






    from slack_esclusi import esclusi

    return set(esclusi(SLACK_CHANNEL_INDEX_FILE))


def parse_all_conversations() -> tuple[list[dict], dict]:
    ""







    log.info("Phase 1: Parsing raw Slack JSONs...")
    t0 = time.time()

    channels_meta = load_channels_metadata()
    esclusi = canali_cliente_esclusi()
    chat_cliente_saltate = 0




    json_files = sorted(RAW_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    visti: set[str] = set()
    doppi_saltati = 0

    conversations = []
    total_messages = 0
    parse_errors = 0
    empty_dms_skipped = 0
    empty_group_dms_skipped = 0
    bot_dms_skipped = 0

    for jf in json_files:
        data = load_json(jf)
        if data is None:
            parse_errors += 1
            continue

        if not isinstance(data, dict) or not data.get("channel_id"):
            continue
        channel = data.get("channel", jf.stem)
        channel_id = data.get("channel_id", "")
        dm_with = data.get("dm_with", "")
        messages = data.get("messages", [])

        if channel_id in visti:
            doppi_saltati += 1
            continue
        visti.add(channel_id)

        if channel_id in esclusi:
            chat_cliente_saltate += 1
            continue



        if dm_with and not messages:
            empty_dms_skipped += 1
            continue


        if channel.startswith("mpdm-") and not messages:
            empty_group_dms_skipped += 1
            continue


        if dm_with and is_bot_user(dm_with):
            bot_dms_skipped += 1

        total_messages += len(messages)

        conversations.append(
            {
                "channel": channel,
                "channel_id": channel_id,
                "dm_with": dm_with,
                "messages": messages,
                "source_file": jf.name,
                "channel_meta": channels_meta.get(channel_id),
            }
        )

    elapsed = time.time() - t0
    log.info(
        f"Parsed {len(conversations)} conversations, "
        f"{total_messages} total messages in {elapsed:.1f}s"
    )
    if parse_errors:
        log.warning(f"  Parse errors: {parse_errors}")
    if empty_dms_skipped:
        log.info(f"  Empty DMs skipped: {empty_dms_skipped}")
    if empty_group_dms_skipped:
        log.info(f"  Empty group DMs skipped: {empty_group_dms_skipped}")
    if bot_dms_skipped:
        log.info(f"  Bot DMs flagged: {bot_dms_skipped}")
    if doppi_saltati:
        log.info(f"  Older copies of the same channel read once: {doppi_saltati}")
    if chat_cliente_saltate:
        log.info(
            f"  Excluded conversations skipped (files stay on disk): {chat_cliente_saltate}"
        )

    return conversations, channels_meta





def build_contacts(
    conversations: list[dict],
    uid_lookup: dict,
    name_to_uid: dict,
    personio_map: dict[str, str],
    personio_name_to_email: dict[str, str] | None = None,
) -> pd.DataFrame:
    ""









    log.info("Phase 2: Building contacts-slack.parquet...")


    user_stats: dict[str, dict] = defaultdict(
        lambda: {
            "display_name": "",
            "user_id": "",
            "slack_username": "",
            "message_count": 0,
            "channels_active": set(),
            "first_seen_ts": "",
            "last_seen_ts": "",
            "is_bot": False,
            "is_deactivated": False,
        }
    )

    for conv in conversations:
        channel = conv["channel"]
        dm_with = conv.get("dm_with", "")

        for msg in conv["messages"]:
            user = msg.get("user", "")
            ts = msg.get("ts", "")
            text = msg.get("text", "")

            if not user:
                continue


            if is_system_message(text):
                continue


            if USER_ID_RE.match(user):
                key = uid_lookup.get(user, user)
                uid = user
            else:
                uid = name_to_uid.get(user, "")


                if uid and uid in uid_lookup:
                    key = uid_lookup[uid]
                else:
                    key = user

            stats = user_stats[key]
            stats["message_count"] += 1
            stats["channels_active"].add(channel)

            if not stats["display_name"] and not USER_ID_RE.match(key):
                stats["display_name"] = key
            if uid and not stats["user_id"]:
                stats["user_id"] = uid
            if not USER_ID_RE.match(key):
                stats["display_name"] = key


            if user != key and not USER_ID_RE.match(user):
                stats["slack_username"] = user


            if ts:
                if not stats["first_seen_ts"] or ts < stats["first_seen_ts"]:
                    stats["first_seen_ts"] = ts
                if not stats["last_seen_ts"] or ts > stats["last_seen_ts"]:
                    stats["last_seen_ts"] = ts


            if is_bot_user(user):
                stats["is_bot"] = True
            if is_deactivated_user(user):
                stats["is_deactivated"] = True


        if dm_with and not USER_ID_RE.match(dm_with):
            dm_key = dm_with
            if dm_with in name_to_uid:
                uid = name_to_uid[dm_with]
                if uid in uid_lookup:
                    dm_key = uid_lookup[uid]
            if dm_key in user_stats and not user_stats[dm_key]["slack_username"]:
                if dm_with == dm_with.lower() and " " not in dm_with:
                    user_stats[dm_key]["slack_username"] = dm_with


    for key, stats in user_stats.items():
        if is_bot_user(key):
            stats["is_bot"] = True
        if is_deactivated_user(key) or key.startswith(DEACTIVATED_LABEL):
            stats["is_deactivated"] = True


    rows = []
    resolved_count = 0
    nickname_count = 0

    for key, stats in user_stats.items():
        display_name = stats["display_name"] if stats["display_name"] else key
        user_id = stats["user_id"]


        if USER_ID_RE.match(key) and not user_id:
            user_id = key
            display_name = ""


        if not user_id and display_name and display_name in name_to_uid:
            user_id = name_to_uid[display_name]


        if not user_id and key in name_to_uid:
            user_id = name_to_uid[key]


        original_name = display_name
        display_name = resolve_display_name(display_name, personio_map)

        if display_name != original_name:
            if USER_ID_RE.match(original_name):
                resolved_count += 1
            else:
                nickname_count += 1


        is_unknown = bool(
            display_name.startswith("Unknown (") or (USER_ID_RE.match(key) and not display_name)
        )


        real_name = ""
        if display_name and not USER_ID_RE.match(display_name):
            if not display_name.startswith("Unknown (") and not display_name.startswith(
                f"[{DEACTIVATED_LABEL}]"
            ):
                real_name = display_name


        email = ""
        _name_to_email = personio_name_to_email or {}
        if display_name in _name_to_email:
            email = _name_to_email[display_name]
        else:
            for local, pname in personio_map.items():
                if pname == display_name:
                    email = local
                break


        is_bot = stats["is_bot"]
        if not is_bot and display_name and is_bot_user(display_name):
            is_bot = True


        is_deactivated = stats["is_deactivated"]
        if not is_deactivated and display_name:
            if is_deactivated_user(display_name) or display_name.startswith(
                f"[{DEACTIVATED_LABEL}]"
            ):
                is_deactivated = True


        if is_deactivated and not display_name.startswith(f"[{DEACTIVATED_LABEL}]"):
            if DEACTIVATED_RE.match(display_name):
                display_name = f"[{DEACTIVATED_LABEL}] {display_name}"

        rows.append(
            {
                "user_id": user_id,
                "slack_username": stats["slack_username"],
                "display_name": display_name,
                "real_name": real_name,
                "email": email,
                "message_count": stats["message_count"],
                "channels_active": len(stats["channels_active"]),
                "first_seen": ts_to_iso(stats["first_seen_ts"]),
                "last_seen": ts_to_iso(stats["last_seen_ts"]),
                "is_bot": is_bot,
                "is_deactivated": is_deactivated,
                "is_unknown": is_unknown,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("message_count", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)


    uid_re_check = df["display_name"].apply(lambda x: bool(USER_ID_RE.match(str(x))) if x else True)
    unknown_check = df["display_name"].apply(lambda x: str(x).startswith("Unknown ("))
    deactivated_count = int(df["is_deactivated"].sum())
    still_raw = int(uid_re_check.sum())
    unknown_labeled = int(unknown_check.sum())

    log.info(
        f"Contacts: {len(df)} unique users "
        f"({df['is_bot'].sum()} bots, {deactivated_count} deactivated, "
        f"{unknown_labeled} unknown), "
        f"resolved {resolved_count} UIDs + {nickname_count} nicknames via Personio, "
        f"remaining raw IDs: {still_raw}"
    )
    return df





def build_interactions(
    conversations: list[dict],
    uid_lookup: dict,
    name_to_uid: dict | None = None,
    personio_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    ""








    log.info("Phase 3: Building interactions-slack.parquet...")



    _name_to_uid = name_to_uid or {}
    _personio_map = personio_map or {}
    nickname_to_canonical = {}
    for name, uid in _name_to_uid.items():
        if uid in uid_lookup:
            canonical = uid_lookup[uid]
            if canonical != name:
                nickname_to_canonical[name] = canonical



    for slug, full_name in _personio_map.items():
        if slug not in nickname_to_canonical:
            nickname_to_canonical[slug] = full_name




    for conv in conversations:
        dw = conv.get("dm_with", "")
        if not dw or dw in nickname_to_canonical or USER_ID_RE.match(dw):
            continue

        resolved = resolve_display_name(dw, _personio_map)
        if resolved != dw:
            nickname_to_canonical[dw] = resolved

    interactions = []

    for conv in conversations:
        channel = conv["channel"]
        channel_id = conv["channel_id"]
        dm_with_raw = conv.get("dm_with", "")
        messages = conv["messages"]


        dm_with = _resolve_user(dm_with_raw, uid_lookup, nickname_to_canonical)


        thread_parents = {}
        for msg in messages:
            ts = msg.get("ts", "")
            thread_ts = msg.get("thread_ts", "")
            reply_count = msg.get("reply_count", 0)


            if thread_ts == ts and reply_count > 0:
                user = msg.get("user", "")
                thread_parents[ts] = _resolve_user(user, uid_lookup, nickname_to_canonical)

        for msg in messages:
            user = msg.get("user", "")
            text = msg.get("text", "")
            ts = msg.get("ts", "")
            thread_ts = msg.get("thread_ts", "")

            if not user or is_system_message(text):
                continue

            from_user = _resolve_user(user, uid_lookup, nickname_to_canonical)


            if thread_ts and thread_ts != ts and thread_ts in thread_parents:
                parent_user = thread_parents[thread_ts]
                if parent_user and parent_user != from_user:
                    interactions.append(
                        {
                            "from_user": from_user,
                            "to_user": parent_user,
                            "channel": channel,
                            "channel_id": channel_id,
                            "timestamp": ts_to_iso(ts),
                            "message_type": "reply",
                            "source": "slack",
                        }
                    )


            mentioned_uids = MENTION_RE.findall(text)
            for uid in mentioned_uids:
                to_user = _resolve_user(uid, uid_lookup, nickname_to_canonical)
                if to_user and to_user != from_user:
                    interactions.append(
                        {
                            "from_user": from_user,
                            "to_user": to_user,
                            "channel": channel,
                            "channel_id": channel_id,
                            "timestamp": ts_to_iso(ts),
                            "message_type": "mention",
                            "source": "slack",
                        }
                    )


            if dm_with and not is_system_message(text):
                to_user = dm_with
                if to_user != from_user:
                    interactions.append(
                        {
                            "from_user": from_user,
                            "to_user": to_user,
                            "channel": channel,
                            "channel_id": channel_id,
                            "timestamp": ts_to_iso(ts),
                            "message_type": "dm",
                            "source": "slack",
                        }
                    )


            for reaction in msg.get("reactions", []):
                if not isinstance(reaction, dict):
                    continue
                for reactor_id in reaction.get("users", []):
                    reactor = _resolve_user(reactor_id, uid_lookup, nickname_to_canonical)
                    if reactor and reactor != from_user:
                        interactions.append(
                            {
                                "from_user": reactor,
                                "to_user": from_user,
                                "channel": channel,
                                "channel_id": channel_id,
                                "timestamp": ts_to_iso(ts),
                                "message_type": "reaction",
                                "source": "slack",
                            }
                        )

    df = pd.DataFrame(interactions)
    if len(df) > 0:
        df.sort_values("timestamp", ascending=False, inplace=True)
        df.reset_index(drop=True, inplace=True)

    type_counts = df["message_type"].value_counts().to_dict() if len(df) > 0 else {}
    log.info(
        f"Interactions: {len(df)} edges "
        f"({type_counts.get('mention', 0)} mentions, "
        f"{type_counts.get('reply', 0)} replies, "
        f"{type_counts.get('dm', 0)} DMs, "
        f"{type_counts.get('reaction', 0)} reactions)"
    )
    return df


def _resolve_user(
    user: str,
    uid_lookup: dict,
    nickname_to_canonical: dict | None = None,
) -> str:
    ""






    if not user:
        return ""
    if USER_ID_RE.match(user):
        return uid_lookup.get(user, user)

    if nickname_to_canonical and user in nickname_to_canonical:
        return nickname_to_canonical[user]
    return user





def build_channels_activity(
    conversations: list[dict],
    channels_meta: dict,
) -> pd.DataFrame:
    ""
    log.info("Phase 4: Building channels-activity.parquet...")

    rows = []
    for conv in conversations:
        channel = conv["channel"]
        channel_id = conv["channel_id"]
        meta = conv.get("channel_meta") or channels_meta.get(channel_id, {})
        messages = conv["messages"]


        real_messages = [m for m in messages if not is_system_message(m.get("text", ""))]

        if not messages:
            continue


        channel_type = classify_channel(channel, meta)


        unique_users = set()
        timestamps = []
        for m in real_messages:
            u = m.get("user", "")
            if u:
                unique_users.add(u)
            ts = m.get("ts", "")
            if ts:
                timestamps.append(ts)


        first_msg_ts = min(timestamps) if timestamps else ""
        last_msg_ts = max(timestamps) if timestamps else ""


        msgs_per_week = 0.0
        if first_msg_ts and last_msg_ts:
            first_dt = ts_to_datetime(first_msg_ts)
            last_dt = ts_to_datetime(last_msg_ts)
            if first_dt and last_dt:
                days_span = (last_dt - first_dt).total_seconds() / 86400
                weeks = max(days_span / 7.0, 1.0)
                msgs_per_week = round(len(real_messages) / weeks, 1)

        rows.append(
            {
                "channel_id": channel_id,
                "channel_name": channel,
                "channel_type": channel_type,
                "total_messages": len(real_messages),
                "unique_users": len(unique_users),
                "first_message": ts_to_iso(first_msg_ts),
                "last_message": ts_to_iso(last_msg_ts),
                "messages_per_week": msgs_per_week,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("total_messages", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    log.info(f"Channels: {len(df)} ({df['channel_type'].value_counts().to_dict()})")
    return df





def build_channel_texts(
    conversations: list[dict],
    uid_lookup: dict,
    channels_meta: dict,
) -> pd.DataFrame:
    ""
    log.info("Phase 4b: Building channel-texts.parquet...")

    max_chars = 50_000
    rows = []

    for conv in conversations:
        channel = conv["channel"]
        channel_id = conv["channel_id"]
        meta = conv.get("channel_meta") or channels_meta.get(channel_id, {})
        messages = conv["messages"]


        real_messages = [m for m in messages if not is_system_message(m.get("text", ""))]
        if not real_messages:
            continue

        channel_type = classify_channel(channel, meta)


        dm_with = ""
        if channel_type == "dm":
            users_in_conv = {m.get("user", "") for m in real_messages if m.get("user")}
            others = [u for u in users_in_conv if not is_own_name(str(uid_lookup.get(u, u)))]
            if others:
                dm_with = uid_lookup.get(others[0], others[0])


        lines = []
        timestamps = []
        for m in sorted(real_messages, key=lambda x: x.get("ts", "0")):
            ts = m.get("ts", "")
            text = m.get("text", "")
            if not text:
                continue


            user_id = m.get("user", "")
            user_name = uid_lookup.get(user_id, user_id) if user_id else "unknown"


            clean_text = MENTION_RE.sub(
                lambda match: uid_lookup.get(match.group(1), match.group(1)),
                text,
            )


            dt = ts_to_datetime(ts)
            ts_str = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
            lines.append(f"[{ts_str}] {user_name}: {clean_text}")

            if ts:
                timestamps.append(ts)

        channel_text = "\n".join(lines)
        if not channel_text.strip():
            continue


        if len(channel_text) > max_chars:
            channel_text = channel_text[:max_chars] + "\n[TRUNCATED]"

        date_start = ts_to_iso(min(timestamps)) if timestamps else ""
        date_end = ts_to_iso(max(timestamps)) if timestamps else ""

        rows.append(
            {
                "channel_name": channel,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "dm_with": dm_with,
                "message_count": len(real_messages),
                "date_start": date_start,
                "date_end": date_end,
                "channel_text": channel_text,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("message_count", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    total_chars = df["channel_text"].str.len().sum() if len(df) > 0 else 0
    non_empty = (df["channel_text"].str.len() > 0).sum() if len(df) > 0 else 0
    log.info(f"  Channel texts: {len(df)} rows, {non_empty} non-empty, {total_chars:,} total chars")
    return df





def build_summary(
    contacts_df: pd.DataFrame,
    interactions_df: pd.DataFrame,
    channels_df: pd.DataFrame,
    conversations: list[dict],
) -> dict:
    ""
    log.info("Phase 5: Building _slack_summary.json...")

    total_msgs = sum(
        len([m for m in c["messages"] if not is_system_message(m.get("text", ""))])
        for c in conversations
    )


    active_mask = ~contacts_df["is_bot"]
    if "is_deactivated" in contacts_df.columns:
        active_mask = active_mask & ~contacts_df["is_deactivated"]
    top_users = (
        contacts_df[active_mask]
        .nlargest(20, "message_count")[["display_name", "message_count", "channels_active"]]
        .to_dict("records")
    )


    top_channels = channels_df.nlargest(20, "total_messages")[
        ["channel_name", "channel_type", "total_messages", "unique_users", "messages_per_week"]
    ].to_dict("records")


    interaction_types = {}
    if len(interactions_df) > 0:
        interaction_types = interactions_df["message_type"].value_counts().to_dict()


        pair_counts = (
            interactions_df.groupby(["from_user", "to_user"])
            .size()
            .reset_index(name="count")
            .nlargest(20, "count")
            .to_dict("records")
        )
    else:
        pair_counts = []


    all_timestamps = []
    for c in conversations:
        for m in c["messages"]:
            ts = m.get("ts", "")
            if ts:
                all_timestamps.append(ts)

    first_date = ts_to_date(min(all_timestamps)) if all_timestamps else ""
    last_date = ts_to_date(max(all_timestamps)) if all_timestamps else ""

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "slack",
        "total_conversations": len(conversations),
        "total_messages_raw": sum(len(c["messages"]) for c in conversations),
        "total_messages_real": total_msgs,
        "total_contacts": len(contacts_df),
        "total_contacts_human": int((~contacts_df["is_bot"]).sum()),
        "total_contacts_bot": int(contacts_df["is_bot"].sum()),
        "total_contacts_deactivated": int(
            contacts_df["is_deactivated"].sum() if "is_deactivated" in contacts_df.columns else 0
        ),
        "total_contacts_unknown": int(
            contacts_df["is_unknown"].sum() if "is_unknown" in contacts_df.columns else 0
        ),
        "total_interactions": len(interactions_df),
        "interaction_types": interaction_types,
        "date_range": {"first": first_date, "last": last_date},
        "channel_types": channels_df["channel_type"].value_counts().to_dict(),
        "top_users": top_users,
        "top_channels": top_channels,
        "top_interaction_pairs": pair_counts,
    }

    return summary





STEPS = ["contacts", "interactions", "channels", "channel_texts", "summary"]


def run_pipeline(dry_run: bool = False, step: str | None = None):
    ""
    t_start = time.time()


    personio_map, personio_name_to_email = load_personio_email_map()


    conversations, channels_meta = parse_all_conversations()

    if not conversations:
        log.error("No conversations found. Exiting.")
        sys.exit(1)


    uid_lookup, name_to_uid = build_user_lookup(conversations, personio_map)


    if not dry_run:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    contacts_df = None
    if not step or step == "contacts":
        contacts_df = build_contacts(
            conversations, uid_lookup, name_to_uid, personio_map, personio_name_to_email
        )
        if not dry_run:
            out = PROCESSED_DIR / "contacts-slack.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"  -> {out} ({len(contacts_df)} rows)")


    interactions_df = None
    if not step or step == "interactions":
        interactions_df = build_interactions(conversations, uid_lookup, name_to_uid, personio_map)
        if not dry_run:
            out = PROCESSED_DIR / "interactions-slack.parquet"
            safe_write_parquet(interactions_df, out, index=False)
            log.info(f"  -> {out} ({len(interactions_df)} rows)")


    channels_df = None
    if not step or step == "channels":
        channels_df = build_channels_activity(conversations, channels_meta)
        if not dry_run:
            out = PROCESSED_DIR / "channels-activity.parquet"
            safe_write_parquet(channels_df, out, index=False)
            log.info(f"  -> {out} ({len(channels_df)} rows)")


    channel_texts_df = None
    if not step or step == "channel_texts":
        channel_texts_df = build_channel_texts(conversations, uid_lookup, channels_meta)
        if not dry_run:
            out = PROCESSED_DIR / "channel-texts.parquet"
            safe_write_parquet(channel_texts_df, out, index=False)
            log.info(f"  -> {out} ({len(channel_texts_df)} rows)")


    if not step or step == "summary":

        if contacts_df is None:
            contacts_df = build_contacts(
                conversations, uid_lookup, name_to_uid, personio_map, personio_name_to_email
            )
        if interactions_df is None:
            interactions_df = build_interactions(
                conversations, uid_lookup, name_to_uid, personio_map
            )
        if channels_df is None:
            channels_df = build_channels_activity(conversations, channels_meta)

        summary = build_summary(contacts_df, interactions_df, channels_df, conversations)

        if not dry_run:
            out = PROCESSED_DIR / "_slack_summary.json"
            safe_write_json(out, summary)
            log.info(f"  -> {out}")
        else:

            print("\n=== SUMMARY ===")
            print(json.dumps(summary, indent=2, ensure_ascii=False))

    elapsed = time.time() - t_start
    log.info(f"Pipeline completed in {elapsed:.1f}s")





def _load_slack_watermark() -> dict[str, float]:
    ""
    wm_path = PROCESSED_DIR / "_slack-l1-watermark.json"
    if wm_path.exists():
        try:
            return json.loads(wm_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_slack_watermark(watermark: dict[str, float]) -> None:
    ""
    wm_path = PROCESSED_DIR / "_slack-l1-watermark.json"
    safe_write_json(wm_path, watermark)


def _incremental_merge_slack_contacts(
    new_contacts: pd.DataFrame, existing_path: Path
) -> pd.DataFrame:
    ""
    if not existing_path.exists() or len(new_contacts) == 0:
        return new_contacts

    existing = pd.read_parquet(existing_path)

    combined = pd.concat([existing, new_contacts], ignore_index=True)

    if "user_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["user_id"], keep="last")
    combined.sort_values(
        "msg_count" if "msg_count" in combined.columns else combined.columns[0],
        ascending=False,
        inplace=True,
    )
    return combined


def _incremental_merge_slack_interactions(
    new_interactions: pd.DataFrame, existing_path: Path
) -> pd.DataFrame:
    ""
    if not existing_path.exists() or len(new_interactions) == 0:
        return new_interactions

    existing = pd.read_parquet(existing_path)
    combined = pd.concat([existing, new_interactions], ignore_index=True)

    group_cols = []
    for col in ["from_id", "to_id", "type"]:
        if col in combined.columns:
            group_cols.append(col)

    if not group_cols:
        return combined

    agg_dict = {}
    if "count" in combined.columns:
        agg_dict["count"] = ("count", "sum")
    if "first_date" in combined.columns:
        agg_dict["first_date"] = ("first_date", "min")
    if "last_date" in combined.columns:
        agg_dict["last_date"] = ("last_date", "max")

    if agg_dict:
        merged = combined.groupby(group_cols).agg(**agg_dict).reset_index()
        merged.sort_values(
            "count" if "count" in merged.columns else merged.columns[0],
            ascending=False,
            inplace=True,
        )
        return merged

    return combined


def main():
    parser = argparse.ArgumentParser(description="Slack L0 -> L1 enrichment pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Stats only, no file output")
    parser.add_argument(
        "--step",
        choices=STEPS,
        default=None,
        help="Run only a specific step",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Incremental mode: process only changed conversation files",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=" * 60)
    log.info("Slack Enrichment Pipeline — SBK L1")
    log.info(f"  RAW_DIR:       {RAW_DIR}")
    log.info(f"  CHANNELS_FILE: {CHANNELS_FILE}")
    log.info(f"  PROCESSED_DIR: {PROCESSED_DIR}")
    log.info(f"  dry_run={args.dry_run}, step={args.step}, incremental={args.incremental}")
    log.info("=" * 60)


    if args.incremental and not args.dry_run:
        watermark = _load_slack_watermark()
        changed_files = []
        current_mtimes = {}

        if RAW_DIR.exists():
            for f in RAW_DIR.glob("*.json"):
                current_mtime = f.stat().st_mtime
                current_mtimes[f.name] = current_mtime
                prev_mtime = watermark.get(f.name, 0)
                if current_mtime > prev_mtime:
                    changed_files.append(f.name)

        if not changed_files:
            log.info("Incremental: no conversation files changed — skipping enrichment")
            try:
                from event_bus import EventBus

                EventBus.emit("slack", "l1", output_changed=False)
            except Exception as e:
                log.warning(f"EventBus emit failed: {e}")
            return

        log.info(f"Incremental: {len(changed_files)} of {len(current_mtimes)} files changed")

    run_pipeline(dry_run=args.dry_run, step=args.step)


    if not args.dry_run:
        try:
            from event_bus import EventBus
            from l1_checkpoint import L1Checkpoint

            ckpt = L1Checkpoint("slack")
            has_changed = ckpt.has_output_changed()
            ckpt.save()
            EventBus.emit("slack", "l1", output_changed=has_changed)
        except Exception as e:
            log.warning(f"EventBus emit failed: {e}")


    if args.incremental and not args.dry_run and RAW_DIR.exists():
        new_watermark = {}
        for f in RAW_DIR.glob("*.json"):
            new_watermark[f.name] = f.stat().st_mtime
        _save_slack_watermark(new_watermark)

    if not args.dry_run:
        mark_last_run("slack-l1")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-slack-enrich", source="slack-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
