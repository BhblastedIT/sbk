#!/usr/bin/env python3
"""Signal quality index: how much each email correspondent, Slack conversation, Plaud and Tactiq meeting is real
two-way communication (reply rate, asymmetry, entropy, threads), so the scores can discount noise.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    EMAILS_DIR,
    ENRICHED_DIR,
    OWN_EMAILS,
    PLAUD_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    safe_write_json,
    user_cfg,
)

log = logging.getLogger("xs-l2-sqi")




DEFAULT_MIN_MSGS = 5


EMAIL_W_REPLY_RATE = 0.35
EMAIL_W_ASYMMETRY = 0.25
EMAIL_W_ENTROPY = 0.20
EMAIL_W_THREAD = 0.10
EMAIL_W_NAME_PATTERN = 0.10


SLACK_W_HUMAN_RATIO = 0.30
SLACK_W_DIVERSITY = 0.20
SLACK_W_DEPTH = 0.20
SLACK_W_OWNER_PARTICIPATION = 0.00
SLACK_W_RECENCY = 0.10


PLAUD_W_ATTRIBUTION = 0.40
PLAUD_W_DENSITY = 0.35
PLAUD_W_TEMPORAL = 0.25


TACTIQ_W_ATTRIBUTION = 0.65
TACTIQ_W_DENSITY = 0.35
TACTIQ_W_BLOCK_PENALTY = -0.30


_NOISE_LOCAL_PATTERNS = {
    "noreply": 1.0,
    "no-reply": 1.0,
    "donotreply": 1.0,
    "mailer-daemon": 1.0,
    "postmaster": 1.0,
    "info": 0.3,
    "support": 0.3,
    "admin": 0.3,
    "hello": 0.7,
    "news": 0.7,
    "newsletter": 1.0,
    "marketing": 0.7,
    "notifications": 1.0,
    "notification": 1.0,
    "growth": 0.7,
    "team": 0.3,
    "awards": 0.7,
    "sales": 0.7,
}


# Your own Slack user id: slack.own_user_id in sbk.config.json (the same key the monitor
# and tools/slack_auth.py read). Empty = your participation in channels is not scored.
# This step stays offline, so it does not ask Slack (auth.test) when the key is empty.
_own_slack = user_cfg("slack.own_user_id", "") or ""
OWNER_SLACK_IDS = {
    str(s).strip().lower()
    for s in (_own_slack if isinstance(_own_slack, list) else [_own_slack])
    if str(s).strip()
}





def _compute_name_pattern_score(email: str) -> float:
    ""
    if "@" not in email:
        return 0.0
    local = email.split("@")[0].lower().strip()
    return _NOISE_LOCAL_PATTERNS.get(local, 0.0)


def _compute_reply_rate(from_count: int, to_count: int) -> float:
    ""








    total = from_count + to_count
    if total == 0:
        return 0.0
    if to_count == 0:
        return 1.0
    from_ratio = from_count / total
    if from_ratio >= 0.91:
        return 0.8
    if from_ratio >= 0.77:
        return 0.5
    if from_ratio >= 0.67:
        return 0.2
    return 0.0


def _compute_asymmetry(from_count: int, to_count: int, reply_rate: float) -> float:
    ""




    if reply_rate == 0.0:
        return 0
    if reply_rate == 1.0:
        return 1.0
    total = from_count + to_count
    if total == 0:
        return 0
    from_ratio = from_count / total
    raw = max(0.0, (from_ratio - 2 / 3) * 3)
    return round(min(1.0, raw), 2)


def _compute_entropy_score(
    sender: str,
    sender_msgs: pd.DataFrame,
) -> float:
    ""











    if len(sender_msgs) == 0:
        return 0.0

    subjects = sender_msgs["subject"].dropna()
    if len(subjects) == 0:
        return 0.0

    unique_subjects = subjects.nunique()
    total = len(subjects)
    if total <= 1:
        return 0.0


    ratio = unique_subjects / total


    all_text = " ".join(subjects.astype(str).str.lower())
    if len(all_text) < 10:
        return 0.0

    char_freq = Counter(all_text)
    total_chars = sum(char_freq.values())
    entropy = -sum((c / total_chars) * math.log2(c / total_chars) for c in char_freq.values())


    norm_entropy = min(1.0, entropy / 5.0)


    if total <= 20 and ratio > 0.8 and norm_entropy > 0.7:
        return 0.9
    if total <= 50 and ratio > 0.6 and norm_entropy > 0.6:
        return 0.5
    if ratio > 0.5 and norm_entropy > 0.5:
        return 0.2
    return 0.0


def _compute_thread_score(sender_msgs: pd.DataFrame) -> float:
    ""









    if len(sender_msgs) == 0:
        return 0.3

    has_reply = sender_msgs["in_reply_to"].notna()
    reply_pct = has_reply.mean()

    unique_threads = sender_msgs["thread_id"].nunique()
    total = len(sender_msgs)
    thread_ratio = unique_threads / total if total > 0 else 0


    if reply_pct > 0.5 or (thread_ratio < 0.5 and reply_pct > 0.3):
        return 0.8

    if reply_pct < 0.1 and total > 5:
        return 0.0
    return 0.3


def score_email(min_msgs: int = DEFAULT_MIN_MSGS) -> dict:
    ""








    own_lower = {e.lower() for e in OWN_EMAILS}


    contacts_path = ENRICHED_DIR / "contacts.parquet"
    if not contacts_path.exists():
        log.warning("No contacts.parquet found at %s — cannot score email", contacts_path)
        return {"noise_scores": {}, "details": {}, "_manca": "contacts.parquet missing"}

    contacts = pd.read_parquet(
        contacts_path,
        columns=["email", "msg_count_from", "msg_count_to"],
    )
    contacts["email"] = contacts["email"].str.lower().str.strip()
    contacts["msg_count_from"] = contacts["msg_count_from"].fillna(0).astype(int)
    contacts["msg_count_to"] = contacts["msg_count_to"].fillna(0).astype(int)
    contacts["total"] = contacts["msg_count_from"] + contacts["msg_count_to"]


    contacts = contacts[~contacts["email"].isin(own_lower)]
    contacts = contacts[contacts["total"] >= min_msgs]

    log.info("Loaded %d qualifying senders from contacts.parquet", len(contacts))


    all_dfs = []
    for msg_file in sorted(EMAILS_DIR.glob("*/messages.parquet")):
        try:
            df = pd.read_parquet(
                msg_file,
                columns=["from_addr", "subject", "thread_id", "in_reply_to"],
            )
            all_dfs.append(df)
        except Exception as e:
            log.warning("Skipping %s: %s", msg_file, e)

    if all_dfs:
        emails = pd.concat(all_dfs, ignore_index=True)
        emails["from_addr"] = emails["from_addr"].str.lower().str.strip()
        log.info("Loaded %d raw email messages for entropy/thread analysis", len(emails))
    else:
        emails = pd.DataFrame(columns=["from_addr", "subject", "thread_id", "in_reply_to"])
        log.warning("No raw email data for entropy/thread — using defaults")

    noise_scores = {}
    details = {}

    for _, row in contacts.iterrows():
        sender = row["email"]
        from_c = int(row["msg_count_from"])
        to_c = int(row["msg_count_to"])
        total = int(row["total"])


        reply_rate = _compute_reply_rate(from_c, to_c)
        asymmetry = _compute_asymmetry(from_c, to_c, reply_rate)
        name_pattern = _compute_name_pattern_score(sender)


        sender_msgs = emails[emails["from_addr"] == sender]
        entropy = _compute_entropy_score(sender, sender_msgs)
        thread = _compute_thread_score(sender_msgs)


        noise = (
            EMAIL_W_REPLY_RATE * reply_rate
            + EMAIL_W_ASYMMETRY * asymmetry
            + EMAIL_W_ENTROPY * entropy
            + EMAIL_W_THREAD * thread
            + EMAIL_W_NAME_PATTERN * name_pattern
        )
        noise = round(max(0.0, min(1.0, noise)), 4)

        noise_scores[sender] = noise
        details[sender] = {
            "reply_rate": reply_rate,
            "asymmetry": asymmetry,
            "entropy": entropy,
            "thread": thread,
            "name_pattern": name_pattern,
            "total_msgs": total,
            "from": from_c,
            "to": to_c,
        }

    log.info(
        "Email SQI: %d senders scored, %d noisy (>= 0.75)",
        len(noise_scores),
        sum(1 for v in noise_scores.values() if v >= 0.75),
    )

    return {"noise_scores": noise_scores, "details": details}





def _load_slack_conversations() -> dict[str, list[dict]]:
    ""
    conv_dir = SLACK_DIR.parent / "conversations"
    if not conv_dir.exists():
        return {}

    conversations = {}
    for f in sorted(conv_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):

                conversations[f.stem] = data
        except (ValueError, OSError):
            continue
    return conversations


def _compute_slack_channel_features(
    channel_name: str,
    channel_id: str,
    channel_type: str,
    activity_row: pd.Series | None,
    messages: list[dict] | None,
) -> dict | None:
    ""




    if channel_type == "dm" and not messages:
        return None

    total_msgs = 0
    unique_users_count = 0

    if activity_row is not None:
        total_msgs = int(activity_row.get("total_messages", 0))
        unique_users_count = int(activity_row.get("unique_users", 0))


    if messages:
        total_msgs = max(total_msgs, len(messages))


        bot_count = sum(
            1
            for m in messages
            if m.get("bot_id")
            or m.get("app_id")
            or m.get("subtype") in ("bot_message", "bot_add", "channel_join", "channel_leave")
        )
        human_ratio = round(1.0 - (bot_count / len(messages)) if len(messages) > 0 else 0.0, 1)


        users = {m.get("user", "") for m in messages if m.get("user")}
        unique_users_count = max(unique_users_count, len(users))


        threaded = sum(
            1 for m in messages if m.get("thread_ts") and m.get("thread_ts") != m.get("ts")
        )
        depth = round(min(1.0, threaded / len(messages)) if len(messages) > 0 else 0.0, 2)


        owner_active = any(m.get("user", "").lower() in OWNER_SLACK_IDS for m in messages)
        owner_participation = 1.0 if owner_active else 0.0


        try:
            timestamps = [float(m.get("ts", 0)) for m in messages if m.get("ts")]
            if timestamps:
                latest = max(timestamps)
                days_ago = (datetime.now(UTC).timestamp() - latest) / 86400
                recency = round(max(0.0, min(1.0, 1.0 - (days_ago / 365))), 1)
            else:
                recency = 0.0
        except (ValueError, TypeError):
            recency = 0.0
    else:

        if total_msgs == 0:
            return None

        human_ratio = 1.0
        depth = 0.0


        owner_participation = 0.0


        if activity_row is not None and pd.notna(activity_row.get("last_message")):
            try:
                last = pd.Timestamp(activity_row["last_message"])
                if last.tzinfo is None:
                    last = last.tz_localize(UTC)
                days_ago = (datetime.now(UTC) - last.to_pydatetime()).days
                recency = round(max(0.0, min(1.0, 1.0 - (days_ago / 365))), 1)
            except (ValueError, TypeError):
                recency = 0.0
        else:
            recency = 0.0


    if unique_users_count >= 15:
        diversity = 1.0
    elif unique_users_count >= 8:
        diversity = 0.7
    elif unique_users_count >= 4:
        diversity = 0.4
    elif unique_users_count >= 2:
        diversity = 0.2
    else:
        diversity = 0.0

    return {
        "human_ratio": round(human_ratio, 1),
        "diversity": round(diversity, 1),
        "depth": round(depth, 2),
        "owner_participation": round(owner_participation, 1),
        "recency": round(recency, 1),
        "total_msgs": total_msgs,
        "unique_users": unique_users_count,
    }


def score_slack() -> dict:
    ""






    activity_path = SLACK_DIR / "channels-activity.parquet"
    if activity_path.exists():
        activity = pd.read_parquet(activity_path)
        activity_by_name = {row["channel_name"]: row for _, row in activity.iterrows()}
        activity_by_id = {row["channel_id"]: row for _, row in activity.iterrows()}
    else:
        log.warning("No channels-activity.parquet found")
        activity_by_name = {}
        activity_by_id = {}
    manca = "" if activity_path.exists() else "channels-activity.parquet missing"


    ch_index_path = SLACK_DIR.parent / "channel-index.json"
    channel_info = {}
    if ch_index_path.exists():
        try:
            idx = json.loads(ch_index_path.read_text(encoding="utf-8"))
            for ch in idx.get("channels", []):
                channel_info[ch["id"]] = ch
                channel_info[ch["name"]] = ch
        except (ValueError, OSError):
            pass


    slack_channels_path = SLACK_DIR.parent / "slack-channels.json"
    if slack_channels_path.exists():
        try:
            channels_list = json.loads(slack_channels_path.read_text(encoding="utf-8"))
            for ch in channels_list:
                ch_id = ch.get("id", "")
                ch_name = ch.get("name", "")
                if ch_id and ch_id not in channel_info:
                    channel_info[ch_id] = ch
                if ch_name and ch_name not in channel_info:
                    channel_info[ch_name] = ch
        except (ValueError, OSError):
            pass


    conversations = _load_slack_conversations()

    scores = {}
    details = {}


    all_channel_names = set(activity_by_name.keys())


    for conv_key in conversations:
        all_channel_names.add(conv_key)

    for ch_name in sorted(all_channel_names):
        activity_row = activity_by_name.get(ch_name)
        ch_id = ""
        ch_type = "unknown"

        if activity_row is not None:
            ch_id = activity_row.get("channel_id", "")
            ch_type = activity_row.get("channel_type", "unknown")


        messages = conversations.get(ch_name) or conversations.get(ch_id)

        features = _compute_slack_channel_features(ch_name, ch_id, ch_type, activity_row, messages)

        if features is None:

            scores[ch_name] = 0.0
            continue


        score = (
            SLACK_W_HUMAN_RATIO * features["human_ratio"]
            + SLACK_W_DIVERSITY * features["diversity"]
            + SLACK_W_DEPTH * features["depth"]
            + SLACK_W_OWNER_PARTICIPATION * features["owner_participation"]
            + SLACK_W_RECENCY * features["recency"]
        )
        score = round(max(0.0, min(1.0, score)), 4)

        scores[ch_name] = score
        details[ch_name] = features


        if ch_id and ch_name + "-" + ch_id not in scores:

            same_name = [k for k in activity_by_name if k == ch_name]
            if len(same_name) > 0 and ch_id:
                composite_key = f"{ch_name}-{ch_id}"
                scores[composite_key] = score
                details[composite_key] = features

    log.info(
        "Slack SQI: %d channels scored, %d with details, %d high signal (>= 0.5)",
        len(scores),
        len(details),
        sum(1 for v in scores.values() if v >= 0.5),
    )

    return {"scores": scores, "details": details, **({"_manca": manca} if manca else {})}





def score_plaud() -> dict:
    ""





    if not PLAUD_DIR.exists():
        log.warning("No Plaud data directory: %s", PLAUD_DIR)
        return {"scores": {}, "details": {}, "_manca": "Plaud folder missing"}

    scores = {}
    details = {}
    special_keys = set()

    for json_file in sorted(PLAUD_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        recording_key = json_file.stem


        if recording_key.startswith("_"):
            special_keys.add(recording_key)
            scores[recording_key] = 0.0
            continue


        if isinstance(data, list):
            utterances = data
        elif isinstance(data, dict):
            utterances = data.get("utterances", data.get("segments", []))
            if not isinstance(utterances, list):
                utterances = []
        else:
            utterances = []

        if not utterances:
            scores[recording_key] = 0.0
            continue


        speakers = set()
        named_count = 0
        for u in utterances:
            speaker = u.get("speaker", u.get("original_speaker", ""))
            if speaker:
                speakers.add(speaker)

                if not re.match(r"^(Speaker|SPEAKER|Sprecher|Intervenante)\s*\d+$", speaker, re.I):
                    named_count += 1

        total_utterances = len(utterances)
        named_ratio = named_count / total_utterances if total_utterances > 0 else 0.0
        attribution = round(min(1.0, named_ratio), 2)


        total_chars = sum(len(u.get("content", u.get("text", ""))) for u in utterances)
        avg_chars = total_chars / total_utterances if total_utterances > 0 else 0

        if avg_chars >= 100:
            density = 1.0
        elif avg_chars >= 50:
            density = 0.7
        elif avg_chars >= 20:
            density = 0.4
        else:
            density = 0.1


        has_timestamps = sum(
            1
            for u in utterances
            if u.get("start_time") is not None or u.get("end_time") is not None
        )
        timestamp_ratio = has_timestamps / total_utterances if total_utterances > 0 else 0

        if timestamp_ratio > 0.9:
            temporal = 1.0
        elif timestamp_ratio > 0.5:
            temporal = 0.5
        else:
            temporal = 0.0


        score = (
            PLAUD_W_ATTRIBUTION * attribution
            + PLAUD_W_DENSITY * density
            + PLAUD_W_TEMPORAL * temporal
        )
        score = round(max(0.0, min(1.0, score)), 3)

        scores[recording_key] = score
        details[recording_key] = {
            "attribution": round(attribution, 2),
            "density": round(density, 1),
            "temporal": round(temporal, 1),
            "utterances": total_utterances,
            "speakers": len(speakers),
            "named_ratio": round(named_ratio, 2),
        }

    log.info(
        "Plaud SQI: %d recordings scored, %d with details",
        len(scores),
        len(details),
    )

    return {"scores": scores, "details": details}





def score_tactiq() -> dict:
    ""






    tactiq_raw_dir = TACTIQ_DIR.parent / "raw"
    if not tactiq_raw_dir.exists():
        log.warning("No Tactiq raw directory: %s", tactiq_raw_dir)
        return {"scores": {}, "details": {}, "_manca": "Tactiq folder missing"}

    scores = {}
    details = {}

    for json_file in sorted(tactiq_raw_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        meeting_key = json_file.stem


        transcript = data.get("transcript", [])
        if not isinstance(transcript, list) or not transcript:
            scores[meeting_key] = 0.0
            details[meeting_key] = {
                "attribution": 0.0,
                "density": 0.0,
                "block_penalty": 0.0,
                "blocks": 0,
                "total_chars": 0,
                "named_ratio": 0.0,
            }
            continue

        blocks = transcript
        total_blocks = len(blocks)
        total_chars = sum(len(b.get("text", b.get("content", ""))) for b in blocks)


        named_count = 0
        speakers = set()
        for b in blocks:
            speaker = b.get("speakerName", b.get("speaker", ""))
            if speaker:
                speakers.add(speaker)
                if not re.match(
                    r"^(Speaker|SPEAKER|Participant|Unknown|Sprecher)\s*\d*$",
                    speaker,
                    re.I,
                ):
                    named_count += 1

        named_ratio = named_count / total_blocks if total_blocks > 0 else 0.0
        attribution = round(min(1.0, named_ratio), 2)


        avg_chars = total_chars / total_blocks if total_blocks > 0 else 0

        if avg_chars >= 50:
            density = 1.0
        elif avg_chars >= 30:
            density = 0.7
        elif avg_chars >= 15:
            density = 0.4
        else:
            density = 0.1



        if total_blocks < 10:
            block_penalty = 0.5
        elif total_chars < 500:
            block_penalty = 0.3
        else:
            block_penalty = 0.0


        score = (
            TACTIQ_W_ATTRIBUTION * attribution
            + TACTIQ_W_DENSITY * density
            + TACTIQ_W_BLOCK_PENALTY * block_penalty
        )
        score = round(max(0.0, min(1.0, score)), 2)

        scores[meeting_key] = score
        details[meeting_key] = {
            "attribution": round(attribution, 2),
            "density": round(density, 1),
            "block_penalty": round(block_penalty, 1),
            "blocks": total_blocks,
            "total_chars": total_chars,
            "named_ratio": round(named_ratio, 2),
        }

    log.info(
        "Tactiq SQI: %d meetings scored, %d with details",
        len(scores),
        len(details),
    )

    return {"scores": scores, "details": details}





def main():
    parser = argparse.ArgumentParser(
        description="XS-L2: Generate Signal Quality Index for SBK data sources"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument(
        "--source",
        choices=["email", "slack", "plaud", "tactiq", "all"],
        default="all",
        help="Process specific source or all (default: all)",
    )
    parser.add_argument(
        "--min-msgs",
        type=int,
        default=DEFAULT_MIN_MSGS,
        help=f"Minimum messages per sender for email SQI (default: {DEFAULT_MIN_MSGS})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    output_path = ENRICHED_DIR / "signal-quality-index.json"

    def _ha_voti(voce) -> bool:
        # An earlier run that really scored this source (not an empty placeholder).
        return isinstance(voce, dict) and any(
            isinstance(voce.get(k), dict) and voce.get(k) for k in ("scores", "noise_scores")
        )

    try:
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        existing = {}

    sources_to_process = (
        ["email", "slack", "plaud", "tactiq"] if args.source == "all" else [args.source]
    )

    result = {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "version": 1,
        }
    }


    for src in ["email", "slack", "plaud", "tactiq"]:
        if src not in sources_to_process and src in existing:
            result[src] = existing[src]


    if "email" in sources_to_process:
        result["email"] = score_email(min_msgs=args.min_msgs)

    if "slack" in sources_to_process:
        result["slack"] = score_slack()

    if "plaud" in sources_to_process:
        result["plaud"] = score_plaud()

    if "tactiq" in sources_to_process:
        result["tactiq"] = score_tactiq()




    mancanti = {}
    for src in sources_to_process:
        manca = result[src].pop("_manca", "")
        if not manca:
            continue
        if _ha_voti(existing.get(src)):
            # Only these are "scores from an earlier run": the note of the pipeline says so.
            mancanti[src] = manca
            result[src] = existing[src]
            log.warning("  %s: %s, keeping the previous run's scores", src, manca)
        else:
            # Never scored (not connected, or a first install): nothing old to report.
            log.info("  %s: %s and no previous score, staying without scores", src, manca)
    if mancanti:
        result["_meta"]["fonti_mancanti"] = mancanti


    log.info("=" * 60)
    log.info("Signal Quality Index Summary:")
    if "email" in result:
        ns = result["email"].get("noise_scores", {})
        noisy = sum(1 for v in ns.values() if v >= 0.75)
        log.info("  Email: %d senders (%d noisy)", len(ns), noisy)
    if "slack" in result:
        ss = result["slack"].get("scores", {})
        high = sum(1 for v in ss.values() if v >= 0.5)
        log.info("  Slack: %d channels (%d high signal)", len(ss), high)
    if "plaud" in result:
        ps = result["plaud"].get("scores", {})
        log.info("  Plaud: %d recordings", len(ps))
    if "tactiq" in result:
        ts = result["tactiq"].get("scores", {})
        log.info("  Tactiq: %d meetings", len(ts))

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return



    safe_write_json(output_path, result, indent=None, ensure_ascii=False)
    log.info("Written: %s", output_path)


from pipeline_decorator import pipeline_step

main = pipeline_step(name="xs-l2-signal-quality", source="cross-source", stage="l2")(main)

if __name__ == "__main__":
    main()
