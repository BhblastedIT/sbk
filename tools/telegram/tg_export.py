"""Telegram plugin core: your own chats from the Telegram Desktop data export.

Import only. You export your data yourself in Telegram Desktop (Settings > Advanced >
Export Telegram data, format "Machine-readable JSON"), and SBK reads the `result.json`
the export writes. There is no Telegram login here: no MTProto session, no API id, no
bot token, nothing goes to the network.

Vendor facts this module relies on (checked on Telegram's official pages and on the
official Telegram Desktop source code, 2026-11-25):
- Where the export is, the folder layout, and the JSON schema (Result, PersonalInformation,
  Contacts/Contact, Chats/LeftChats, Chat.type values, Message fields `id`, `type`
  (message|service), `date`, `date_unixtime`, `from`, `from_id` as <type><id>, `text` as
  a string or an array of strings and entities, `media_type`, `action`, `members`):
  https://core.telegram.org/import-export
- "To export all chats, use Settings > Advanced > Export Telegram Data", single chats from
  the chat's menu, and the 24-hour wait after a fresh login unless confirmed from another
  device: https://bugs.telegram.org/c/60
- The writer itself (official repository of Telegram Desktop): `date` is the message time
  converted to the exporting computer's local time, written without an offset
  (QDateTime::fromSecsSinceEpoch(...).toString(Qt::ISODate)), `date_unixtime` the same moment
  in seconds; a personal chat's `id` is the other person's user id; the contacts list carries
  `user_id` when Telegram knows the account; chat type "verification_codes" also exists:
  https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/export/output/export_output_json.cpp
- Menu and option names ("Export Telegram data", "Advanced", "Machine-readable JSON",
  "Personal chats", "Private groups", "Only my messages", "Contacts list"):
  https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/Resources/langs/lang.strings
- Groups: under "Private groups" the sub-option "Only my messages" is ticked by default
  (Settings::DefaultFullChats() is PersonalChats | BotChats, and the checkbox is
  `(fullChats & types) != types`), so a default export holds only YOUR messages in groups.
  Chats you have left (`left_chats`) are always exported with your messages only
  (FinalizeDialogsInfo sets onlyMyMessages = true for them). Call service messages use the
  action "phone_call" or "conference_call":
  https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/export/export_settings.h
  https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/export/view/export_view_settings.cpp
  https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/export/data/export_data_types.cpp
- The app: https://desktop.telegram.org/

Data layout (all under <data root>/telegram/, constants of this module, not of sbk_config):
    exports/                  where you may drop export folders (searched when no path is given)
    raw/chats/<key>.json      one file per chat, messages merged across imports by message id
    raw/contacts.json         the contacts list of the export(s), merged
    raw/me.json               your Telegram user id and name (from the export)
    raw/state.json            the exports already imported (fingerprint -> when, what)
    download-summary.json     what the last import did
    processed/plugin-contacts.parquet, processed/plugin-interactions.parquet  (tg-l1-enrich.py)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_phone  # noqa: E402

import sbk_config  # noqa: E402

SOURCE = "telegram"
MULTI_SEP = "|||"
SETUP_HINT = "see docs/CONNECTING.md#telegram"
EXPORT_FILE = "result.json"
HTML_FILES = ("export_results.html", "messages.html")

# Chat types of the export (core.telegram.org/import-export, Chat.type, plus
# "verification_codes" written by Telegram Desktop) and the peer prefix of their id.
PEER_PREFIX = {
    "personal_chat": "user",
    "bot_chat": "user",
    "saved_messages": "user",
    "replies": "user",
    "verification_codes": "user",
    "private_group": "chat",
    "private_supergroup": "channel",
    "public_supergroup": "channel",
    "private_channel": "channel",
    "public_channel": "channel",
}
GROUP_TYPES = frozenset({"private_group", "private_supergroup", "public_supergroup"})
# Read by default: conversations with people. Bots, saved messages, channels and public
# groups are left out unless telegram.chat_types lists them.
DEFAULT_CHAT_TYPES = ("personal_chat", "private_group", "private_supergroup")
# Service messages read as calls (export_output_json.cpp writes "conference_call" for a
# call with a conference id, "phone_call" otherwise, "group_call" for a group voice chat).
CALL_ACTIONS = frozenset({"phone_call", "conference_call", "group_call"})

CONTACT_COLUMNS = [
    "source",
    "name",
    "email",
    "phone",
    "company",
    "title",
    "first_seen",
    "last_seen",
    "interactions",
    "url",
]
INTERACTION_COLUMNS = [
    "source",
    "ts",
    "kind",
    "title",
    "text",
    "participants",
    "owner_role",
    "due",
    "url",
    "status",
]

# Message fields kept in raw/chats/*.json. Media files are never copied: only their kind.
_KEEP = (
    "id",
    "type",
    "date",
    "date_unixtime",
    "edited_unixtime",
    "from",
    "from_id",
    "actor",
    "actor_id",
    "action",
    "members",
    "media_type",
    "forwarded_from",
    "reply_to_message_id",
    "duration_seconds",
    "discard_reason",
)


class TelegramError(Exception):
    """A Telegram problem worth one clear line to the user."""


# --- paths (inside this plugin, not in sbk_config) ------------------------------------


def telegram_dir() -> Path:
    return Path(sbk_config.DATA_ROOT) / "telegram"


def exports_dir() -> Path:
    return telegram_dir() / "exports"


def raw_dir() -> Path:
    return telegram_dir() / "raw"


def chats_dir() -> Path:
    return raw_dir() / "chats"


def contacts_raw_path() -> Path:
    return raw_dir() / "contacts.json"


def me_path() -> Path:
    return raw_dir() / "me.json"


def state_path() -> Path:
    return raw_dir() / "state.json"


def summary_path() -> Path:
    return telegram_dir() / "download-summary.json"


def processed_dir() -> Path:
    return telegram_dir() / "processed"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


# --- settings (sbk.config.json "telegram" section) ------------------------------------


def cfg(key: str, default):
    return sbk_config.user_cfg(f"telegram.{key}", default)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    sbk_config.safe_write_json(path, data)


# --- reading an export ----------------------------------------------------------------


def find_exports(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """(result.json files, folders that hold only an HTML export) under the given paths.

    A path may be the result.json itself or any folder above it (searched with its
    sub-folders, so the parent folder of several exports works too).
    """
    found: list[Path] = []
    html_only: list[Path] = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_file():
            if p.name.lower().endswith(".json"):
                found.append(p)
            continue
        if not p.is_dir():
            continue
        results = sorted(p.rglob(EXPORT_FILE))
        found.extend(results)
        if not results:
            for name in HTML_FILES:
                html_only.extend(sorted(x.parent for x in p.rglob(name)))
    out, seen = [], set()
    for f in found:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            out.append(f)
    return out, sorted(set(html_only))


def fingerprint(path: Path) -> str:
    """sha256 of the file (read in blocks): the same export is never imported twice."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_export(path: Path) -> dict:
    """The parsed result.json, or TelegramError with one clear reason."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except UnicodeDecodeError as e:
        raise TelegramError(f"{path.name} is not UTF-8 text ({e.reason})") from None
    except json.JSONDecodeError as e:
        raise TelegramError(
            f"{path.name} is not valid JSON (line {e.lineno}); was the export finished?"
        ) from None
    except OSError as e:
        raise TelegramError(f"cannot read {path}: {e.strerror or e}") from None
    if not isinstance(data, dict):
        raise TelegramError(f"{path.name} is not a Telegram export (top level is not an object)")
    if "messages" not in data and "chats" not in data and "contacts" not in data:
        raise TelegramError(
            f"{path.name} has no chats, contacts or messages: not a Telegram Desktop JSON export"
        )
    return data


def export_chats(data: dict) -> list[tuple[dict, bool]]:
    """(chat, left) pairs: a full export's chats and left_chats, or a single-chat export."""
    if isinstance(data.get("messages"), list):
        return [(data, False)]
    out: list[tuple[dict, bool]] = []
    for key, left in (("chats", False), ("left_chats", True)):
        block = data.get(key)
        items = block.get("list") if isinstance(block, dict) else None
        for chat in items or []:
            if isinstance(chat, dict):
                out.append((chat, left))
    return out


def chat_key(chat: dict) -> str:
    """'user123' / 'chat123' / 'channel123': the chat id with its peer kind."""
    prefix = PEER_PREFIX.get(str(chat.get("type") or ""), "peer")
    cid = re.sub(r"[^0-9-]", "", str(chat.get("id") or ""))
    return f"{prefix}{cid}" if cid else ""


def flatten_text(value) -> str:
    """`text` as a string: plain strings and the `text` of every entity, in order."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(value)


def slim_message(msg: dict) -> dict | None:
    """The fields SBK keeps of one exported message (text flattened, media reduced to a kind)."""
    if not isinstance(msg, dict) or msg.get("id") is None:
        return None
    out = {k: msg[k] for k in _KEEP if k in msg and msg[k] not in (None, "", [])}
    text = flatten_text(msg.get("text"))
    if text:
        out["text"] = text
    if "media_type" not in out:
        if msg.get("photo"):
            out["media_type"] = "photo"
        elif msg.get("file"):
            out["media_type"] = "file"
        elif msg.get("location_information"):
            out["media_type"] = "location"
        elif msg.get("contact_information"):
            out["media_type"] = "contact"
        elif msg.get("poll"):
            out["media_type"] = "poll"
    return out


def _msg_id(m: dict):
    try:
        return int(m.get("id"))
    except (TypeError, ValueError):
        return str(m.get("id"))


def _edited_at(m: dict) -> int:
    try:
        return int(m.get("edited_unixtime") or 0)
    except (TypeError, ValueError):
        return 0


def merge_messages(old: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """(merged list sorted by id, how many were new, how many changed). Never drops a message.

    A message that differs replaces the stored one unless the stored one was edited later
    (an older export imported after a newer one never rolls an edit back).
    """
    by_id = {_msg_id(m): m for m in old if isinstance(m, dict) and m.get("id") is not None}
    added = changed = 0
    for m in new:
        k = _msg_id(m)
        cur = by_id.get(k)
        if cur is None:
            added += 1
            by_id[k] = m
        elif cur != m and _edited_at(m) >= _edited_at(cur):
            changed += 1
            by_id[k] = m
    merged = sorted(by_id.values(), key=lambda m: (isinstance(_msg_id(m), str), _msg_id(m)))
    return merged, added, changed


def phone_digits(phone) -> str:
    """Digits of the number after the shared normaliser (phone_country_code applied)."""
    raw = str(phone or "")
    return re.sub(r"\D", "", normalize_phone(raw) or raw)


def contact_key(c: dict) -> str:
    uid = str(c.get("user_id") or "").strip()
    if uid:
        return f"u:{uid}"
    digits = phone_digits(c.get("phone_number"))
    if digits:
        return f"p:{digits}"
    name = " ".join(f"{c.get('first_name') or ''} {c.get('last_name') or ''}".split()).lower()
    return f"n:{name}" if name else ""


def export_contacts(data: dict) -> list[dict]:
    block = data.get("contacts")
    items = block.get("list") if isinstance(block, dict) else None
    out = []
    for c in items or []:
        if not isinstance(c, dict):
            continue
        row = {
            k: str(c.get(k) or "").strip()
            for k in ("user_id", "first_name", "last_name", "phone_number", "date_unixtime")
        }
        if row["first_name"] or row["last_name"] or row["phone_number"]:
            out.append(row)
    return out


def full_name(first, last) -> str:
    return " ".join(f"{first or ''} {last or ''}".split())


# --- time ------------------------------------------------------------------------------


def message_ts(msg: dict) -> str:
    """ISO 8601 UTC of a message: date_unixtime when present, else `date` read as local time.

    `date` is written in the exporting computer's local time without an offset; older exports
    have only `date`. telegram.timezone (an IANA name) says which zone that was; empty = this
    computer's zone.
    """
    raw = str(msg.get("date_unixtime") or "").strip()
    if raw.lstrip("-").isdigit():
        return datetime.fromtimestamp(int(raw), UTC).isoformat()
    d = str(msg.get("date") or "").strip()
    if not d:
        return ""
    try:
        dt = datetime.fromisoformat(d)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        tz_name = str(cfg("timezone", "") or "").strip()
        if tz_name:
            from zoneinfo import ZoneInfo

            try:
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
            except Exception:  # noqa: BLE001 - a bad zone name falls back to this computer's
                dt = dt.astimezone()
        else:
            dt = dt.astimezone()
    return dt.astimezone(UTC).isoformat()


def message_day(msg: dict) -> str:
    """The calendar day of a message as you lived it: the local `date` of the export."""
    d = str(msg.get("date") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    ts = message_ts(msg)
    return ts[:10] if ts else ""


# --- promises in messages -------------------------------------------------------------

# First-person promises, English and Italian. Conservative on purpose: a promise needs a
# verb of doing (send, call, check...). Replace them with telegram.promise_patterns.
DEFAULT_PROMISE_PATTERNS: tuple[str, ...] = (
    r"\bI(?:'ll| will| shall)\s+(?:\w+\s+){0,2}?(?:send|call|check|get back|let you know|share|"
    r"write|forward|follow up|look into|email|text|book|pay|transfer|prepare|review|confirm|"
    r"sort|handle|fix|update|ping|bring|organi[sz]e|arrange|reply|answer)\b",
    r"\bI(?:'m| am) going to\s+(?:send|call|check|share|write|forward|follow up|email|book|"
    r"pay|prepare|review|confirm)\b",
    r"\bI promise\b",
    r"\bwill do\b",
    r"\blet me (?:check|get back to you|look into it|find out)\b",
    r"\b(?:ti|vi|te lo|te la|ve lo|ve la|glielo|gliela)\s+(?:mando|invio|giro|inoltro|passo|"
    r"chiamo|richiamo|scrivo|faccio sapere|aggiorno|preparo|porto|confermo)\b",
    r"\b(?:lo|la|li|le)\s+(?:mando|invio|giro|preparo|controllo|verifico|sistemo)\b",
    r"\bprometto\b",
    r"\bci penso io\b",
    r"\bme ne occupo io\b",
)

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "lunedi": 0,
    "lunedì": 0,
    "martedi": 1,
    "martedì": 1,
    "mercoledi": 2,
    "mercoledì": 2,
    "giovedi": 3,
    "giovedì": 3,
    "venerdi": 4,
    "venerdì": 4,
    "sabato": 5,
    "domenica": 6,
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def promise_patterns() -> list[re.Pattern]:
    raw = cfg("promise_patterns", None)
    if isinstance(raw, str):
        raw = [raw]
    pats = list(raw) if raw else list(DEFAULT_PROMISE_PATTERNS)
    out = []
    for p in pats:
        try:
            out.append(re.compile(str(p), re.IGNORECASE))
        except re.error as e:
            raise TelegramError(f"telegram.promise_patterns: bad pattern {p!r} ({e})") from None
    return out


def find_promise(text: str, patterns: list[re.Pattern]) -> str:
    """The first sentence of `text` that matches a promise pattern, or ''."""
    for sentence in _SENTENCE_SPLIT.split(str(text or "")):
        s = sentence.strip()
        if s and any(p.search(s) for p in patterns):
            return s
    return ""


def due_from_text(sentence: str, day: str) -> str:
    """A due date (YYYY-MM-DD) said in the sentence, relative to the message day, or ''.

    Understood: an ISO date; today / tonight / oggi / stasera; tomorrow / domani; the day
    after tomorrow / dopodomani; a weekday name (the next one after the message day); next
    week / la settimana prossima (seven days later). Anything else gives no due date.
    """
    s = str(sentence or "").lower()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", s)
    if m:
        try:
            return date.fromisoformat(m.group(1)).isoformat()
        except ValueError:
            pass
    try:
        d0 = date.fromisoformat(str(day)[:10])
    except ValueError:
        return ""
    if re.search(r"\b(?:day after tomorrow|dopodomani)\b", s):
        return (d0 + timedelta(days=2)).isoformat()
    if re.search(r"\b(?:tomorrow|domani)\b", s):
        return (d0 + timedelta(days=1)).isoformat()
    if re.search(r"\b(?:today|tonight|this evening|oggi|stasera|stamattina)\b", s):
        return d0.isoformat()
    if re.search(r"\b(?:next week|settimana prossima|prossima settimana)\b", s):
        return (d0 + timedelta(days=7)).isoformat()
    for name, wd in _WEEKDAYS.items():
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", s):
            ahead = (wd - d0.weekday()) % 7 or 7
            return (d0 + timedelta(days=ahead)).isoformat()
    return ""
