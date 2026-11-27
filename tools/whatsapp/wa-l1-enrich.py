#!/usr/bin/env python3
"""WhatsApp L1: from the imported chats to contacts, interactions and chat activity tables.

Status: TESTED, on a synthetic export, after the two imports of the author's path
(wa-l0l3-full.py for the phone's chat exports, wa-l0-import-history.py for a bulk text export).
The pipeline runs it for you (xs-pipeline-run.py --ingest); you can also run it alone.

Input:  <data root>/whatsapp/chats/*.json
Output: <data root>/whatsapp/processed/
  contacts-whatsapp.parquet       one row per person, with message counts and dates
  interactions-whatsapp.parquet   who wrote to whom; always you on one side (rows between
                                  two other people in a group are not written)
  chats-activity.parquet          one row per chat
  chat-texts.parquet              the text of each chat, for the later steps
  gruppi.parquet                  groups, with the "noise" verdict (big groups you never write in)
  _whatsapp_summary.json          totals

You are recognised through "owner" and "own_names" in sbk.config.json. Optional, in the same file:
  whatsapp.name_overrides         {"<name as in the export>": "<real name>"}
  whatsapp.group_name_exclusions  ["<group name>", ...] names that are groups, never people

Everything runs on your machine; nothing is sent anywhere.

    uv run python tools/whatsapp/wa-l1-enrich.py --dry-run   # totals only, writes nothing
    uv run python tools/whatsapp/wa-l1-enrich.py
"""
















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from text_utils import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    OWN_NAMES_NORMALIZED,
    OWNER_NAME,
    WHATSAPP_CHATS_DIR,
    WHATSAPP_DIR,
    safe_write_parquet,
    user_cfg,
)

CHATS_DIR = WHATSAPP_CHATS_DIR
PROCESSED_DIR = WHATSAPP_DIR

log = logging.getLogger("whatsapp-enrich")



# You, as sbk.config.json says: "owner" plus every spelling in "own_names". The imports already
# write your messages under "owner"; the other spellings are caught here too.
OWNER_CANONICAL = OWNER_NAME
OWNER_NAMES = {normalize_name(n) for n in OWN_NAMES_NORMALIZED} | {normalize_name(OWNER_NAME)}


# Group names that the export shows as a sender (never a person): sbk.config.json
# "whatsapp.group_name_exclusions". Empty = none.
_GROUP_NAME_EXCLUSIONS_RAW: list[str] = [
    str(n) for n in (user_cfg("whatsapp.group_name_exclusions", []) or []) if str(n).strip()
]


# A name as the export writes it -> the person's real name: sbk.config.json
# "whatsapp.name_overrides", e.g. {"Mom": "Maria Rossi"}. Empty = none.
_NAME_OVERRIDES_RAW: dict[str, str] = {
    str(k): str(v) for k, v in (user_cfg("whatsapp.name_overrides", {}) or {}).items() if str(v).strip()
}


GROUP_NAME_EXCLUSIONS: set[str] = set()
NAME_OVERRIDES: dict[str, str] = {}



SYSTEM_TEXTS = {
    "messages and calls are end-to-end encrypted. only people in this chat can read, listen to, or share them.",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "document omitted",
    "contact card omitted",
    "gif omitted",
    "location: ",
    "live location shared",
    "this message was deleted",
    "you deleted this message",
    "missed voice call",
    "missed video call",
}

SYSTEM_ACTION_PATTERNS = [
    re.compile(r"^.+ created group .+$"),
    re.compile(r"^.+ added .+$"),
    re.compile(r"^.+ removed .+$"),
    re.compile(r"^.+ left$"),
    re.compile(r"^.+ changed this group.+$"),
    re.compile(r"^.+ changed the subject .+$"),
    re.compile(r"^.+ changed the group description$"),
    re.compile(r"^you were added$", re.IGNORECASE),
    re.compile(r"^.+ turned on disappearing messages.+$"),
    re.compile(r"^.+ turned off disappearing messages.+$"),
    re.compile(r"^.+ pinned a message$"),
]


def is_system_message(text: str) -> bool:
    ""
    if not text:
        return True
    t = text.strip().lower()
    for sys_text in SYSTEM_TEXTS:
        if t.startswith(sys_text) or t == sys_text:
            return True

    if "<attached:" in t:
        return True
    for pat in SYSTEM_ACTION_PATTERNS:
        if pat.match(t):
            return True
    return False





def _init_name_lookups():
    ""
    global GROUP_NAME_EXCLUSIONS, NAME_OVERRIDES
    if not GROUP_NAME_EXCLUSIONS:
        GROUP_NAME_EXCLUSIONS = {normalize_name(n) for n in _GROUP_NAME_EXCLUSIONS_RAW}
    if not NAME_OVERRIDES:
        NAME_OVERRIDES = {normalize_name(k): v for k, v in _NAME_OVERRIDES_RAW.items()}


def _is_group_name(name: str) -> bool:
    ""
    _init_name_lookups()
    n = normalize_name(name)
    if not n:
        return False
    for gn in GROUP_NAME_EXCLUSIONS:
        if gn in n or n in gn:
            return True
    return False


def is_owner(name: str) -> bool:
    """True when `name` is you (sbk.config.json "owner" / "own_names")."""
    return normalize_name(name) in OWNER_NAMES


def is_own_name(name: str) -> bool:
    """Same test as is_owner; kept under this name for the ego checks below."""
    return is_owner(name)


def clean_sender_name(name: str) -> str:
    ""








    if not name:
        return ""
    _init_name_lookups()


    name = name.strip()
    if name.startswith("~"):
        name = name[1:].strip()

    name = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", name)
    name = name.strip()


    if is_owner(name):
        return OWNER_CANONICAL


    n_lower = normalize_name(name)
    if n_lower in NAME_OVERRIDES:
        name = NAME_OVERRIDES[n_lower]


    if _is_group_name(name):
        return ""

    return name


def is_phone_number(name: str) -> bool:
    ""
    cleaned = re.sub(r"[\s\-\+\(\)]", "", name)
    return cleaned.isdigit() and len(cleaned) >= 7


def is_group_label(sender: str, chat_name: str) -> bool:
    ""
    if not sender or not chat_name:
        return False

    clean_chat = chat_name.replace("WhatsApp Chat - ", "").strip()
    return sender.strip() == clean_chat





def parse_timestamp(msg: dict, date_format_hint: str = "") -> datetime | None:
    ""









    now = datetime.now()


    ts = msg.get("timestamp")
    if ts and isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)

            if dt > now and dt.month != dt.day and dt.month <= 12 and dt.day <= 12:
                try:
                    dt_swap = dt.replace(month=dt.day, day=dt.month)
                    if dt_swap <= now:
                        return dt_swap
                except ValueError:
                    pass
            return dt
        except ValueError:
            pass



    date_str = msg.get("date")
    time_str = msg.get("time")
    if date_str and time_str:

        if date_format_hint == "mdy":
            fmts = (
                "%m/%d/%y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%d/%m/%y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
            )
        else:
            fmts = (
                "%d/%m/%y %H:%M:%S",
                "%m/%d/%y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
            )
        for fmt in fmts:
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                if dt > now:
                    continue
                return dt
            except ValueError:
                continue

        for fmt in fmts:
            try:
                return datetime.strptime(f"{date_str} {time_str}", fmt)
            except ValueError:
                continue
    return None


def _extract_phone_from_chat_name(chat_name: str) -> str:
    ""
    if not chat_name:
        return ""
    cn = chat_name.replace("WhatsApp Chat - ", "").strip()

    cn = re.sub(r"\s*\(\d+\)\s*$", "", cn).strip()

    cn_digits = re.sub(r"[\s\-\(\)\u00a0]", "", cn)
    if cn_digits.startswith("+") and cn_digits[1:].isdigit() and len(cn_digits) >= 8:
        return cn
    return ""


def load_chat(path: Path) -> dict | None:
    ""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot parse {path.name}: {e}")
        return None

    chat_name = data.get("chat_name", "")

    if not chat_name:
        phone = data.get("phone", "")
        if phone:
            chat_name = f"WhatsApp Chat - {phone}"
        else:
            chat_name = f"WhatsApp Chat - {path.stem}"



    chat_phone = data.get("phone", "").strip()

    if not chat_phone:
        chat_phone = _extract_phone_from_chat_name(chat_name)


    participants_raw = data.get("participants", {})
    if isinstance(participants_raw, dict):
        participant_names = list(participants_raw.keys())
    elif isinstance(participants_raw, list):
        participant_names = list(participants_raw)
    else:
        participant_names = []




    participants_clean = []
    for p in participant_names:
        cleaned = clean_sender_name(p)
        if cleaned:
            participants_clean.append(cleaned)

    participants_clean = list(dict.fromkeys(participants_clean))




    if chat_name and len(participants_clean) > 2:
        group_label = chat_name.replace("WhatsApp Chat - ", "").strip()
        group_label_clean = clean_sender_name(group_label)


        to_remove = set()
        for p in participants_clean:
            p_norm = normalize_name(p)
            label_norm = normalize_name(group_label_clean)
            if not p_norm:
                continue

            if (
                p_norm == label_norm
                or label_norm.startswith(p_norm)
                or p_norm.startswith(label_norm)
            ):

                raw_count = (
                    participants_raw.get(
                        [
                            k
                            for k in (
                                participants_raw.keys()
                                if isinstance(participants_raw, dict)
                                else []
                            )
                            if clean_sender_name(k) == p
                        ][0],
                        0,
                    )
                    if isinstance(participants_raw, dict)
                    else 0
                )
                if raw_count <= 5:
                    to_remove.add(p)

        for p in to_remove:
            participants_clean.remove(p)


    date_fmt_hint = data.get("date_format_detected", "")
    raw_messages = data.get("messages", [])
    messages = []
    for msg in raw_messages:
        sender_raw = msg.get("sender", "")
        text = msg.get("text", "")
        ts = parse_timestamp(msg, date_format_hint=date_fmt_hint)

        if not sender_raw or not ts:
            continue

        sender = clean_sender_name(sender_raw)
        if not sender:
            continue


        if is_system_message(text):
            continue

        messages.append(
            {
                "sender": sender,
                "text": text,
                "timestamp": ts,
                "chars": len(text) if text else 0,
                "words": len(text.split()) if text else 0,
            }
        )


    messages.sort(key=lambda m: m["timestamp"])


    real_participants = [p for p in participants_clean if p]
    is_group = len(real_participants) > 2




    phone_participants: dict[str, str] = {}
    if chat_phone and not is_group:
        non_owner = [p for p in real_participants if p != OWNER_CANONICAL]
        if len(non_owner) == 1:
            phone_participants[non_owner[0]] = chat_phone
            log.debug(f"  Phone mapped: {non_owner[0]} -> {chat_phone}")


    for p in real_participants:
        if is_phone_number(p) and p not in phone_participants.values():
            phone_participants[p] = p

    return {
        "file_name": path.name,
        "chat_name": chat_name,
        "participants": real_participants,
        "is_group": is_group,
        "messages": messages,
        "total_messages": len(messages),
        "first_message": messages[0]["timestamp"] if messages else None,
        "last_message": messages[-1]["timestamp"] if messages else None,
        "phone_participants": phone_participants,
    }





def _build_text_fingerprints(chat: dict, n: int = 50) -> set:
    ""
    fps = set()
    for m in chat["messages"][:n]:
        text = m["text"][:80].strip() if m["text"] else ""
        if text and len(text) > 10:
            fps.add(text)
    return fps


def deduplicate_chats(chats: list[dict]) -> list[dict]:
    ""








    by_participants = defaultdict(list)
    for chat in chats:
        key = tuple(sorted(chat["participants"]))
        by_participants[key].append(chat)

    pass1_result = []
    dropped = 0
    for key, group in by_participants.items():
        if len(group) == 1:
            pass1_result.append(group[0])
            continue


        group.sort(key=lambda c: c["total_messages"], reverse=True)
        best = group[0]
        pass1_result.append(best)

        best_fingerprints = _build_text_fingerprints(best)

        for other in group[1:]:
            if not best_fingerprints or not other["messages"]:
                pass1_result.append(other)
                continue

            other_fps = _build_text_fingerprints(other, n=20)
            if not other_fps:
                pass1_result.append(other)
                continue

            match_count = len(other_fps & best_fingerprints)
            overlap_ratio = match_count / len(other_fps)

            if overlap_ratio > 0.5:
                log.info(
                    f"  Dropping duplicate (same participants): {other['file_name']} "
                    f"({other['total_messages']} msgs, {overlap_ratio:.0%} overlap with {best['file_name']})"
                )
                dropped += 1
            else:
                pass1_result.append(other)



    pass1_result.sort(key=lambda c: c["total_messages"], reverse=True)
    kept = []
    kept_fingerprints = []

    for chat in pass1_result:
        chat_fps = _build_text_fingerprints(chat, n=30)
        if not chat_fps or len(chat_fps) < 5:

            kept.append(chat)
            kept_fingerprints.append(chat_fps)
            continue

        is_dupe = False
        for i, existing_fps in enumerate(kept_fingerprints):
            if not existing_fps:
                continue
            match_count = len(chat_fps & existing_fps)
            overlap_ratio = match_count / len(chat_fps)
            if overlap_ratio > 0.5:
                log.info(
                    f"  Dropping duplicate (cross-group): {chat['file_name']} "
                    f"({chat['total_messages']} msgs, {overlap_ratio:.0%} overlap with {kept[i]['file_name']})"
                )
                dropped += 1
                is_dupe = True
                break

        if not is_dupe:
            kept.append(chat)
            kept_fingerprints.append(chat_fps)

    if dropped:
        log.info(f"Deduplication: dropped {dropped} total duplicate chats")
    return kept





def load_all_chats() -> list[dict]:
    ""
    log.info("Phase 1: Loading WhatsApp chat JSONs...")
    t0 = time.time()

    json_files = sorted(CHATS_DIR.glob("*.json"))

    json_files = [
        f for f in json_files if not f.name.startswith("_") and f.name != "chats-index.json"
    ]

    chats = []
    total_msgs = 0
    errors = 0

    for jf in json_files:
        chat = load_chat(jf)
        if chat is None:
            errors += 1
            continue
        if chat["total_messages"] == 0:
            log.warning(f"  Skipping {jf.name}: 0 messages after filtering")
            continue
        chats.append(chat)
        total_msgs += chat["total_messages"]


    chats = deduplicate_chats(chats)

    elapsed = time.time() - t0
    log.info(f"Loaded {len(chats)} chats, {total_msgs} messages in {elapsed:.1f}s")
    if errors:
        log.warning(f"  Parse errors: {errors}")
    return chats





def build_contacts(chats: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 2: Building contacts-whatsapp.parquet...")


    phone_lookup: dict[str, str] = {}
    for chat in chats:
        for contact_name, phone in chat.get("phone_participants", {}).items():
            if contact_name and phone:
                existing = phone_lookup.get(contact_name, "")
                if not existing:
                    phone_lookup[contact_name] = phone
    if phone_lookup:
        log.info(f"  Phone lookup built: {len(phone_lookup)} contacts with phone numbers")
        for name, phone in phone_lookup.items():
            log.info(f"    {name} -> {phone}")

    contact_stats = defaultdict(
        lambda: {
            "chats": [],
            "messages_sent": 0,
            "messages_received": 0,
            "chars_sent": 0,
            "words_sent": 0,
            "first_message": None,
            "last_message": None,
            "response_times": [],
            "is_group_participant": False,
            "is_1to1_participant": False,
        }
    )

    for chat in chats:
        participants = chat["participants"]
        is_group = chat["is_group"]


        sender_counts = Counter(m["sender"] for m in chat["messages"])

        for p in participants:
            stats = contact_stats[p]
            stats["chats"].append(chat["chat_name"])
            if is_group:
                stats["is_group_participant"] = True
            else:
                stats["is_1to1_participant"] = True


        prev_msg = None
        for msg in chat["messages"]:
            sender = msg["sender"]
            ts = msg["timestamp"]


            contact_stats[sender]["messages_sent"] += 1
            contact_stats[sender]["chars_sent"] += msg["chars"]
            contact_stats[sender]["words_sent"] += msg["words"]


            if (
                contact_stats[sender]["first_message"] is None
                or ts < contact_stats[sender]["first_message"]
            ):
                contact_stats[sender]["first_message"] = ts
            if (
                contact_stats[sender]["last_message"] is None
                or ts > contact_stats[sender]["last_message"]
            ):
                contact_stats[sender]["last_message"] = ts


            if not is_group and len(participants) == 2:
                other = [p for p in participants if p != sender]
                if other:
                    contact_stats[other[0]]["messages_received"] += 1


            if prev_msg and prev_msg["sender"] != sender and not is_group:
                delta_hours = (ts - prev_msg["timestamp"]).total_seconds() / 3600

                if 0 < delta_hours < 48:
                    contact_stats[sender]["response_times"].append(delta_hours)

            prev_msg = msg


    rows = []
    for name, stats in contact_stats.items():
        response_times = stats["response_times"]
        avg_response_hours = (
            round(sum(response_times) / len(response_times), 2) if response_times else None
        )


        phone = phone_lookup.get(name, "")
        if not phone and is_phone_number(name):
            phone = name

        rows.append(
            {
                "name": name,
                "phone": phone,
                "chat_count": len(set(stats["chats"])),
                "chat_names": " ||| ".join(sorted(set(stats["chats"]))),
                "message_count": stats["messages_sent"] + stats["messages_received"],
                "messages_sent": stats["messages_sent"],
                "messages_received": stats["messages_received"],
                "chars_sent": stats["chars_sent"],
                "words_sent": stats["words_sent"],
                "first_message": stats["first_message"].isoformat()
                if stats["first_message"]
                else "",
                "last_message": stats["last_message"].isoformat() if stats["last_message"] else "",
                "is_group_participant": stats["is_group_participant"],
                "is_1to1_participant": stats["is_1to1_participant"],
                "response_time_avg_hours": avg_response_hours,
            }
        )

    df = pd.DataFrame(rows)


    before = len(df)
    df = df[~df["name"].apply(_is_group_name)].copy()
    dropped_groups = before - len(df)
    if dropped_groups:
        log.info(f"  Removed {dropped_groups} group-name entries from contacts")

    df.sort_values("messages_sent", ascending=False, inplace=True)

    owner_rows = df[df["name"] == OWNER_CANONICAL]
    others = df[df["name"] != OWNER_CANONICAL]
    log.info(
        f"Contacts: {len(df)} total, you sent {owner_rows['messages_sent'].sum() if len(owner_rows) else 0} msgs"
    )
    log.info(f"  Top 5 by sent: {', '.join(others.head(5)['name'].tolist())}")
    return df




_INTERACTION_COLUMNS = [
    "from_name",
    "to_name",
    "chat_name",
    "timestamp",
    "is_group",
    "weight",
    "source",
]




INTERACTION_EGO_STATS: dict[str, int] = {}


def build_interactions(chats: list[dict]) -> pd.DataFrame:
    ""



















































    log.info("Phase 3: Building interactions-whatsapp.parquet (I-WA invariant: egocentric)...")

    rows = []
    soppressi = 0
    chat_senza_ego = 0
    righe_chat_senza_ego = 0

    for chat in chats:
        is_group = chat["is_group"]
        participants = chat["participants"]



        if not any(is_own_name(p) for p in participants):
            chat_senza_ego += 1
            for msg in chat["messages"]:
                n_others = len([p for p in participants if p != msg["sender"]])
                righe_chat_senza_ego += n_others if is_group else min(n_others, 1)
            continue

        for msg in chat["messages"]:
            sender = msg["sender"]
            ts = msg["timestamp"]






            sender_norm = normalize_name(sender)
            others = [p for p in participants if normalize_name(p) != sender_norm]

            if not is_group:






                if is_own_name(sender):
                    destinatario = others[0] if others else None
                else:
                    ego_presenti = [p for p in others if is_own_name(p)]
                    destinatario = ego_presenti[0] if ego_presenti else None
                if destinatario:
                    rows.append(
                        {
                            "from_name": sender,
                            "to_name": destinatario,
                            "chat_name": chat["chat_name"],
                            "timestamp": ts.isoformat(),
                            "is_group": False,
                            "weight": 1.0,
                            "source": "whatsapp",
                        }
                    )
            else:

                n_others = len(others)
                w = round(1.0 / n_others, 4) if n_others > 0 else 1.0

                if is_own_name(sender):

                    destinatari = others
                else:



                    destinatari = [p for p in others if is_own_name(p)]
                    soppressi += n_others - len(destinatari)

                for other in destinatari:
                    rows.append(
                        {
                            "from_name": sender,
                            "to_name": other,
                            "chat_name": chat["chat_name"],
                            "timestamp": ts.isoformat(),
                            "is_group": True,
                            "weight": w,
                            "source": "whatsapp",
                        }
                    )

    INTERACTION_EGO_STATS.clear()
    INTERACTION_EGO_STATS.update(
        {
            "righe_emesse": len(rows),
            "righe_fra_terzi_soppresse": soppressi,
            "chat_senza_ego": chat_senza_ego,
            "righe_chat_senza_ego": righe_chat_senza_ego,
        }
    )

    df = pd.DataFrame(rows, columns=_INTERACTION_COLUMNS)
    total_weight = df["weight"].sum() if len(df) else 0
    log.info(
        f"Interactions: {len(df)} edges (weight sum: {total_weight:.1f}), "
        f"{df[~df['is_group']].shape[0]} 1:1, {df[df['is_group']].shape[0]} group"
    )
    log.info(
        "  I-WA: %s rows between third parties suppressed; %s chats without ego (%s rows not produced)",
        f"{soppressi:,}",
        f"{chat_senza_ego:,}",
        f"{righe_chat_senza_ego:,}",
    )
    if chat_senza_ego:
        log.warning(
            "  I-WA: %d chats don't contain the ego among the participants. If the number "
            "grows, a spelling of your name is missing from own_names in sbk.config.json.",
            chat_senza_ego,
        )
    return df


def verifica_invariante_iwa(df: pd.DataFrame) -> None:
    ""









    if df.empty:
        return

    f = df["from_name"].astype(str).str.strip().str.lower()
    t = df["to_name"].astype(str).str.strip().str.lower()

    fuori_ego = ~(df["from_name"].map(is_owner) | df["to_name"].map(is_owner))
    if fuori_ego.any():
        esempi = df.loc[fuori_ego, ["from_name", "to_name", "chat_name"]].head(3)
        raise RuntimeError(
            f"I-WA1 violated: {int(fuori_ego.sum()):,} rows don't touch the ego. "
            f"Examples: {esempi.to_dict('records')}"
        )

    self_edge = f == t
    if self_edge.any():
        esempi = df.loc[self_edge, ["from_name", "to_name", "chat_name"]].head(3)
        raise RuntimeError(
            f"I-WA3 violated: {int(self_edge.sum()):,} self-edges. "
            f"Examples: {esempi.to_dict('records')}"
        )





def _marchi_di_lavoro() -> set[str]:
    ""

    from sbk_config import ATTIO_PROCESSED_DIR, INTERNAL_DOMAINS

    marchi = {d.split(".")[0].lower() for d in INTERNAL_DOMAINS}
    try:
        aziende = pd.read_parquet(ATTIO_PROCESSED_DIR / "companies-attio.parquet", columns=["name"])
        marchi |= {str(n).strip().lower() for n in aziende["name"].dropna()}
    except (OSError, ValueError, KeyError):
        pass
    return {m for m in marchi if len(m) >= 5}


def build_gruppi(chats: list[dict], adesso: datetime | None = None) -> pd.DataFrame:
    ""







    import rumore

    adesso = adesso or datetime.now()
    corr = rumore.correzioni()
    marchi = _marchi_di_lavoro()
    righe = []
    for chat in chats:
        if not chat["is_group"]:
            continue
        msgs = chat["messages"]
        tuoi = [m["timestamp"] for m in msgs if m["sender"] == OWNER_CANONICAL]
        ultimo = max(tuoi) if tuoi else None
        mesi = (adesso - ultimo).days / 30.44 if ultimo is not None else None
        nome = normalize_name(chat["chat_name"]).lower()
        di_lavoro = any(re.search(rf"\b{re.escape(m)}\b", nome) for m in marchi)
        calcolato = rumore.classifica_gruppo(
            membri=len(chat["participants"]),
            messaggi=len(msgs),
            tuoi=len(tuoi),
            mesi_dall_ultimo_tuo=mesi,
            di_lavoro=di_lavoro,
        )
        tipo, perche = rumore.tipo_gruppo_finale(chat["file_name"], calcolato, corr)
        chat["tipo_gruppo"] = tipo
        righe.append(
            {
                "chiave": chat["file_name"],
                "nome": chat["chat_name"],
                "membri": len(chat["participants"]),
                "messaggi": len(msgs),
                "tuoi": len(tuoi),
                "ultimo_tuo": ultimo.isoformat() if ultimo is not None else "",
                "di_lavoro": di_lavoro,
                "calcolato": calcolato,
                "tipo": tipo,
                "perche": perche,
            }
        )
    # the columns are named even with no group at all (a parquet without columns has no schema)
    colonne = [
        "chiave",
        "nome",
        "membri",
        "messaggi",
        "tuoi",
        "ultimo_tuo",
        "di_lavoro",
        "calcolato",
        "tipo",
        "perche",
    ]
    df = pd.DataFrame(righe, columns=colonne)
    if not df.empty:
        log.info(
            "Groups: %d, noise %d (%d messages), doubts %d",
            len(df),
            int((df["tipo"] == "rumore").sum()),
            int(df.loc[df["tipo"] == "rumore", "messaggi"].sum()),
            int((df["tipo"] == "dubbio").sum()),
        )
    return df


def build_chats_activity(chats: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 4: Building chats-activity.parquet...")

    rows = []
    for chat in chats:
        messages = chat["messages"]
        if not messages:
            continue

        first = messages[0]["timestamp"]
        last = messages[-1]["timestamp"]
        duration_weeks = max((last - first).total_seconds() / (7 * 86400), 1)


        sender_counts = Counter(m["sender"] for m in messages)
        top_sender = sender_counts.most_common(1)[0][0] if sender_counts else ""

        rows.append(
            {
                "chat_name": chat["chat_name"],
                "chat_type": "group" if chat["is_group"] else "1to1",
                "participants": " ||| ".join(chat["participants"]),
                "participant_count": len(chat["participants"]),
                "total_messages": chat["total_messages"],
                "first_message": first.isoformat(),
                "last_message": last.isoformat(),
                "duration_days": round((last - first).total_seconds() / 86400, 1),
                "messages_per_week": round(chat["total_messages"] / duration_weeks, 1),
                "top_sender": top_sender,
                "top_sender_messages": sender_counts.get(top_sender, 0),
                "source_file": chat["file_name"],
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("total_messages", ascending=False, inplace=True)
    log.info(
        f"Chat activity: {len(df)} chats ({df[df['chat_type'] == '1to1'].shape[0]} 1:1, "
        f"{df[df['chat_type'] == 'group'].shape[0]} group)"
    )
    return df





def build_summary(
    chats: list[dict],
    contacts_df: pd.DataFrame,
    interactions_df: pd.DataFrame,
    activity_df: pd.DataFrame,
) -> dict:
    ""
    log.info("Phase 5: Building summary...")

    total_msgs = sum(c["total_messages"] for c in chats)
    all_participants = set()
    for c in chats:
        all_participants.update(c["participants"])


    all_dates = []
    for c in chats:
        if c["first_message"]:
            all_dates.append(c["first_message"])
        if c["last_message"]:
            all_dates.append(c["last_message"])


    others = contacts_df[contacts_df["name"] != OWNER_CANONICAL].copy()
    top_contacts = others.head(10)[
        ["name", "messages_sent", "chat_count", "first_message", "last_message"]
    ].to_dict("records")


    owner_rows = contacts_df[contacts_df["name"] == OWNER_CANONICAL]
    owner_sent = int(owner_rows["messages_sent"].sum()) if len(owner_rows) else 0
    owner_chars = int(owner_rows["chars_sent"].sum()) if len(owner_rows) else 0


    groups = [c for c in chats if c["is_group"]]
    one_to_one = [c for c in chats if not c["is_group"]]

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "whatsapp-enrich-v1",
        "totals": {
            "chats": len(chats),
            "chats_1to1": len(one_to_one),
            "chats_group": len(groups),
            "messages": total_msgs,
            "unique_participants": len(all_participants),
            "contacts_not_you": len(others),
            "interaction_edges": len(interactions_df),
        },
        "date_range": {
            "min": min(all_dates).isoformat() if all_dates else "",
            "max": max(all_dates).isoformat() if all_dates else "",
        },
        "owner": {
            "messages_sent": owner_sent,
            "chars_sent": owner_chars,
            "chats_participated": int(owner_rows["chat_count"].sum()) if len(owner_rows) else 0,
        },
        "top_contacts": top_contacts,
        "top_chats_by_messages": (
            activity_df.head(10)[
                ["chat_name", "chat_type", "total_messages", "messages_per_week"]
            ].to_dict("records")
        ),
    }

    return summary





def build_chat_texts(chats: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 5b: Building chat texts...")
    t0 = time.time()

    rows = []
    for chat in chats:
        msgs = chat["messages"]
        if not msgs:
            continue

        lines = []
        for m in msgs:
            ts = m["timestamp"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)[:16]
            lines.append(f"[{ts_str}] {m['sender']}: {m['text']}")

        chat_text = "\n".join(lines)[:50000]

        rows.append(
            {
                "chat_name": chat["chat_name"],
                "is_group": chat["is_group"],
                "participants": ", ".join(chat["participants"]),
                "message_count": len(msgs),
                "date_start": msgs[0]["timestamp"].isoformat()
                if hasattr(msgs[0]["timestamp"], "isoformat")
                else str(msgs[0]["timestamp"]),
                "date_end": msgs[-1]["timestamp"].isoformat()
                if hasattr(msgs[-1]["timestamp"], "isoformat")
                else str(msgs[-1]["timestamp"]),
                "chat_text": chat_text,
            }
        )

    df = pd.DataFrame(rows)
    elapsed = time.time() - t0
    non_empty = (df["chat_text"].str.len() > 0).sum() if len(df) > 0 else 0
    log.info(f"  Chat texts: {len(df)} chats ({non_empty} with text) [{elapsed:.1f}s]")
    return df





def main():
    parser = argparse.ArgumentParser(description="WhatsApp enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed, mark_last_run

        if not check_inputs_changed("wa-l1", [CHATS_DIR]):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("wa-l1")
            return

    if not CHATS_DIR.exists():
        log.error(f"Chats directory not found: {CHATS_DIR}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    chats = load_all_chats()
    if not chats:
        log.error("No chats loaded. Check directory.")
        sys.exit(1)


    gruppi_df = build_gruppi(chats)
    if not args.dry_run:
        out = PROCESSED_DIR / "gruppi.parquet"
        safe_write_parquet(gruppi_df, out, index=False)
        log.info(f"  Saved -> {out}")
    tutte = chats
    chats = [c for c in chats if c.get("tipo_gruppo") != "rumore"]


    contacts_df = build_contacts(chats)
    if not args.dry_run:
        out = PROCESSED_DIR / "contacts-whatsapp.parquet"
        safe_write_parquet(contacts_df, out, index=False)
        log.info(f"  Saved -> {out}")


    interactions_df = build_interactions(chats)
    verifica_invariante_iwa(interactions_df)
    if not args.dry_run:
        out = PROCESSED_DIR / "interactions-whatsapp.parquet"
        safe_write_parquet(interactions_df, out, index=False)
        log.info(f"  Saved -> {out}")


    activity_df = build_chats_activity(chats)
    if not args.dry_run:
        out = PROCESSED_DIR / "chats-activity.parquet"
        safe_write_parquet(activity_df, out, index=False)
        log.info(f"  Saved -> {out}")


    chat_texts_df = build_chat_texts(chats)
    if not args.dry_run:
        out = PROCESSED_DIR / "chat-texts.parquet"
        safe_write_parquet(chat_texts_df, out, index=False)
        log.info(f"  Saved -> {out}")


    summary = build_summary(chats, contacts_df, interactions_df, activity_df)
    summary["gruppi_rumore"] = {
        "gruppi": len(tutte) - len(chats),
        "messaggi": sum(c["total_messages"] for c in tutte if c.get("tipo_gruppo") == "rumore"),
    }


    summary["ego_invariant"] = dict(INTERACTION_EGO_STATS)
    if args.dry_run:
        log.info("\n=== DRY RUN — Summary ===")
        log.info(json.dumps(summary, indent=2, default=str))
    else:
        out = PROCESSED_DIR / "_whatsapp_summary.json"
        out.write_text(json.dumps(summary, indent=2, default=str))
        log.info(f"  Saved -> {out}")

    if not args.dry_run:
        from sbk_config import mark_last_run, save_input_checkpoint

        save_input_checkpoint("wa-l1", [CHATS_DIR])
        mark_last_run("wa-l1")


    log.info("\n" + "=" * 60)
    log.info("WHATSAPP ENRICHMENT COMPLETE")
    log.info("=" * 60)
    log.info(f"  Chats:        {len(chats)}")
    log.info(f"  Contacts:     {len(contacts_df)}")
    log.info(f"  Interactions: {len(interactions_df)} edges")
    log.info(f"  Chat activity:{len(activity_df)} chats")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-whatsapp-enrich", source="wa-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
