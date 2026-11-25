#!/usr/bin/env python3
"""Microsoft 365 plugin: Graph items -> the kernel's existing slots.

No kernel file changes. Each row is shaped like the rows the Google plugins write,
so the kernel readers take it as it is:

- mail     -> <data root>/emails/<label>/messages.parquet (columns of
              tools/email/em-l0-download.py:parse_message, read by tools/email/em-l1-enrich.py)
- calendar -> <data root>/calendars/<label>/events.parquet (columns of
              tools/calendar/ca-l0-download.py:_riga_evento, read by tools/calendar/ca-l1-extract.py)
- contacts -> <data root>/contacts/contacts.parquet (columns read by
              tools/cross-source/xs-l1-contacts-enrich.py:load_contacts)

Two extra columns mark our rows: `source` ("microsoft365" / "microsoft365:<label>") and, in
mail, `folder_id`. The kernel readers ignore columns they do not know.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pandas as pd

BODY_TEXT_MAX_CHARS = 200_000  # same cap as tools/email/em-l0-download.py:61
SOURCE = "microsoft365"

MAIL_COLUMNS = [
    "id",
    "thread_id",
    "date",
    "from_addr",
    "to_addr",
    "cc",
    "bcc",
    "subject",
    "body_text",
    "body_truncated",
    "labels",
    "message_id",
    "in_reply_to",
    "snippet",
    "has_attachments",
    "attachment_count",
    "attachments_json",
    "list_unsubscribe",
    "list_id",
    "precedence",
    "auto_submitted",
    "folder_id",
    "web_link",
    "source",
]

EVENT_COLUMNS = [
    "id",
    "summary",
    "start_datetime",
    "end_datetime",
    "start_timezone",
    "location",
    "description",
    "organizer_email",
    "attendees",
    "attendee_count",
    "status",
    "calendar_name",
    "calendar_id",
    "conference_url",
    "event_type",
    "transparency",
    "color_id",
    "html_link",
    "recurring_event_id",
    "visibility",
    "end_timezone",
    "updated",
    "self_status",
    "organizer_self",
    "source",
]

CONTACT_COLUMNS = [
    "full_name",
    "first_name",
    "last_name",
    "primary_phone",
    "primary_email",
    "organization",
    "title",
    "all_phones",
    "all_emails",
    "birthday",
    "last_updated",
    "source",
    "source_id",
]

# Well-known Outlook folders -> the Gmail label the kernel already understands.
WELL_KNOWN_LABELS = {
    "inbox": "INBOX",
    "sentitems": "SENT",
    "drafts": "DRAFT",
    "archive": "ARCHIVE",
}
SKIPPED_WELL_KNOWN = ("junkemail", "deleteditems")

# Graph responseStatus.response -> Google responseStatus (what the calendar readers see).
RESPONSE_MAP = {
    "accepted": "accepted",
    "organizer": "accepted",
    "declined": "declined",
    "tentativelyAccepted": "tentative",
    "none": "needsAction",
    "notResponded": "needsAction",
}
SENSITIVITY_MAP = {
    "normal": "default",
    "personal": "private",
    "private": "private",
    "confidential": "confidential",
}


# --------------------------------------------------------------------------- text


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Strip()
    try:
        p.feed(html)
        text = "".join(p.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t\r\f\v]+", " ", text)).strip()


def body_text(body: dict | None) -> str:
    if not isinstance(body, dict):
        return ""
    content = body.get("content") or ""
    if str(body.get("contentType", "")).lower() == "html":
        return html_to_text(content)
    return content


def fmt_addr(recipient: dict | None) -> str:
    """A Graph recipient as an RFC 5322 header value: '"Name" <addr>' or 'addr'."""
    ea = (recipient or {}).get("emailAddress") or {}
    addr = (ea.get("address") or "").strip()
    name = (ea.get("name") or "").replace('"', "").strip()
    if not addr:
        return ""
    if name and name.lower() != addr.lower():
        return f'"{name}" <{addr}>'
    return addr


def fmt_addr_list(recipients: list | None) -> str:
    return ", ".join(a for a in (fmt_addr(r) for r in recipients or []) if a)


def _header(headers: list | None, name: str) -> str:
    for h in headers or []:
        if str(h.get("name", "")).lower() == name:
            return str(h.get("value", ""))
    return ""


# --------------------------------------------------------------------------- mail


def _labels(folder_label: str, draft: bool, unread: bool, categories: list) -> str:
    labels = [folder_label] if folder_label else []
    if draft and "DRAFT" not in labels:
        labels.append("DRAFT")
    if unread:
        labels.append("UNREAD")
    labels += [str(c) for c in categories or [] if c]
    return ",".join(labels)


def message_row(msg: dict, folder_id: str, folder_label: str) -> dict:
    received = msg.get("receivedDateTime") or msg.get("sentDateTime")
    date = pd.to_datetime(received, utc=True, errors="coerce") if received else pd.NaT
    text = body_text(msg.get("body"))
    headers = msg.get("internetMessageHeaders")
    return {
        "id": msg["id"],
        "thread_id": msg.get("conversationId") or "",
        "date": date,
        "from_addr": fmt_addr(msg.get("from") or msg.get("sender")),
        "to_addr": fmt_addr_list(msg.get("toRecipients")),
        "cc": fmt_addr_list(msg.get("ccRecipients")),
        "bcc": fmt_addr_list(msg.get("bccRecipients")),
        "subject": msg.get("subject") or "",
        "body_text": text[:BODY_TEXT_MAX_CHARS],
        "body_truncated": len(text) > BODY_TEXT_MAX_CHARS,
        "labels": _labels(
            folder_label,
            bool(msg.get("isDraft")),
            msg.get("isRead") is False,
            msg.get("categories"),
        ),
        "message_id": msg.get("internetMessageId") or "",
        "in_reply_to": _header(headers, "in-reply-to"),
        "snippet": msg.get("bodyPreview") or "",
        "has_attachments": bool(msg.get("hasAttachments")),
        # Attachments are not listed by this plugin: the count stays 0 (see README, Limits).
        "attachment_count": 0,
        "attachments_json": "",
        "list_unsubscribe": _header(headers, "list-unsubscribe")[:500],
        "list_id": _header(headers, "list-id")[:300],
        "precedence": _header(headers, "precedence")[:50],
        "auto_submitted": _header(headers, "auto-submitted")[:50],
        "folder_id": folder_id,
        "web_link": msg.get("webLink") or "",
        "source": SOURCE,
    }


# Graph property -> slot columns it fills. Used for updates that come back partial.
_PROP_COLUMNS = {
    "conversationId": ("thread_id",),
    "receivedDateTime": ("date",),
    "sentDateTime": ("date",),
    "from": ("from_addr",),
    "sender": ("from_addr",),
    "toRecipients": ("to_addr",),
    "ccRecipients": ("cc",),
    "bccRecipients": ("bcc",),
    "subject": ("subject",),
    "body": ("body_text", "body_truncated"),
    "bodyPreview": ("snippet",),
    "internetMessageId": ("message_id",),
    "hasAttachments": ("has_attachments",),
    "webLink": ("web_link",),
    "internetMessageHeaders": (
        "in_reply_to",
        "list_unsubscribe",
        "list_id",
        "precedence",
        "auto_submitted",
    ),
}
_CORE_PROPS = ("receivedDateTime", "subject", "toRecipients", "body")


def is_partial(msg: dict) -> bool:
    """True for a delta item that lacks properties the download always selects.

    Graph's delta contract: an updated item comes back with its id and *at least* the
    updated properties (https://learn.microsoft.com/en-us/graph/delta-query-overview).
    Writing such an item as a full row would blank subject, body and date.
    """
    return any(k not in msg for k in _CORE_PROPS)


def patch_message(old: dict, msg: dict, folder_id: str, folder_label: str) -> dict:
    """The old slot row with only the properties a partial delta item carries."""
    fresh = message_row(msg, folder_id, folder_label)
    row = {c: old.get(c, "") for c in MAIL_COLUMNS}
    for prop, cols in _PROP_COLUMNS.items():
        if prop in msg:
            for c in cols:
                if c == "date" and pd.isna(fresh["date"]):
                    continue
                row[c] = fresh[c]
    parts = [p for p in str(old.get("labels") or "").split(",") if p]
    rest = parts[1:]  # parts[0] is the folder label the row was written with
    row["labels"] = _labels(
        folder_label,
        bool(msg["isDraft"]) if "isDraft" in msg else "DRAFT" in rest,
        msg["isRead"] is False if "isRead" in msg else "UNREAD" in rest,
        msg.get("categories")
        if "categories" in msg
        else [p for p in rest if p not in ("DRAFT", "UNREAD")],
    )
    row.update(id=msg["id"], folder_id=folder_id, source=SOURCE)
    return row


def merge_messages(
    existing: pd.DataFrame | None, upserts: list[dict], removed: list[tuple[str, str]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """New slot table and the rows set aside.

    `removed` holds (folder_id, message_id) pairs from @removed delta entries: a row goes
    only if it still sits in that folder (a move shows up as removed in the old folder
    and as an upsert in the new one, with the same immutable id).
    """
    base = (
        existing if existing is not None and len(existing) else pd.DataFrame(columns=MAIL_COLUMNS)
    )
    new = (
        pd.DataFrame(upserts, columns=MAIL_COLUMNS)
        if upserts
        else pd.DataFrame(columns=MAIL_COLUMNS)
    )
    if len(new):
        new = new.drop_duplicates(subset=["id"], keep="last")
        base = base[~base["id"].isin(set(new["id"]))]
    aside = pd.DataFrame(columns=base.columns)
    if removed and len(base):
        pairs = set(removed)
        keys = list(
            zip(
                base.get("folder_id", pd.Series([""] * len(base))).astype(str),
                base["id"].astype(str),
                strict=False,
            )
        )
        mask = pd.Series([k in pairs for k in keys], index=base.index)
        aside = base[mask]
        base = base[~mask]
    frames = [f for f in (base, new) if len(f)]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MAIL_COLUMNS)
    if len(out):
        out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
        out = out.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)
    return out, aside.reset_index(drop=True)


# --------------------------------------------------------------------------- calendar


def _graph_dt(value: dict | None) -> datetime | None:
    if not isinstance(value, dict) or not value.get("dateTime"):
        return None
    raw = str(value["dateTime"])[:19]
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    tz = str(value.get("timeZone") or "UTC")
    if tz.upper() in ("UTC", "ETC/UTC", "COORDINATED UNIVERSAL TIME"):
        return dt.replace(tzinfo=UTC)
    try:
        return dt.replace(tzinfo=ZoneInfo(tz))
    except Exception:
        return dt  # naive: Windows zone names are not converted


def event_when(value: dict | None, all_day: bool, local_tz: ZoneInfo) -> str:
    """ISO string as Google writes it: a date for all-day events, else an aware datetime.

    The download asks Graph for UTC (Prefer: outlook.timezone="UTC"). Timed events are
    written in `local_tz` (microsoft365.timezone, else SBK_DISPLAY_TZ), so the first ten
    characters, which the calendar L1 reads as the day, are the local day. An all-day
    event starts at midnight in its own zone: a UTC midnight is taken as is, anything else
    is read in `local_tz`.
    """
    dt = _graph_dt(value)
    if dt is None:
        return ""
    if all_day:
        if dt.tzinfo is None or (dt.hour, dt.minute, dt.second) == (0, 0, 0):
            return dt.date().isoformat()
        return dt.astimezone(local_tz).date().isoformat()
    if dt.tzinfo is None:
        return dt.isoformat()
    return dt.astimezone(local_tz).isoformat()


def event_row(ev: dict, calendar: dict, local_tz: ZoneInfo) -> dict:
    all_day = bool(ev.get("isAllDay"))
    attendees = []
    for a in ev.get("attendees") or []:
        addr = ((a.get("emailAddress") or {}).get("address") or "").strip()
        if addr:
            resp = (a.get("status") or {}).get("response") or "none"
            attendees.append({"email": addr, "status": RESPONSE_MAP.get(resp, "needsAction")})
    organizer = ((ev.get("organizer") or {}).get("emailAddress") or {}).get("address") or ""
    online = ev.get("onlineMeeting") or {}
    show_as = ev.get("showAs") or ""
    self_resp = (ev.get("responseStatus") or {}).get("response") or ""
    return {
        "id": ev.get("id", ""),
        "summary": ev.get("subject") or "",
        "start_datetime": event_when(ev.get("start"), all_day, local_tz),
        "end_datetime": event_when(ev.get("end"), all_day, local_tz),
        "start_timezone": ev.get("originalStartTimeZone") or "",
        "location": (ev.get("location") or {}).get("displayName") or "",
        "description": body_text(ev.get("body")) or (ev.get("bodyPreview") or ""),
        "organizer_email": organizer,
        "attendees": json.dumps(attendees),
        "attendee_count": len(attendees),
        "status": "cancelled" if ev.get("isCancelled") else "confirmed",
        "calendar_name": calendar.get("name") or "",
        "calendar_id": calendar.get("id") or "",
        "conference_url": online.get("joinUrl") or ev.get("onlineMeetingUrl") or "",
        "event_type": "outOfOffice" if show_as == "oof" else "default",
        "transparency": "transparent" if show_as == "free" else "opaque",
        "color_id": "",
        "html_link": ev.get("webLink") or "",
        "recurring_event_id": ev.get("seriesMasterId") or "",
        "visibility": SENSITIVITY_MAP.get(ev.get("sensitivity") or "normal", "default"),
        "end_timezone": ev.get("originalEndTimeZone") or "",
        "updated": ev.get("lastModifiedDateTime") or "",
        "self_status": RESPONSE_MAP.get(self_resp, "") if self_resp else "",
        "organizer_self": "1" if ev.get("isOrganizer") else "",
        "source": SOURCE,
    }


def _aware(dt: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(dt)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _start_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str[:10], errors="coerce", utc=True)


def merge_events(
    existing: pd.DataFrame | None,
    fresh: list[dict],
    calendar_ids: set[str],
    window_start: datetime,
    window_end: datetime,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace, for the calendars just read, every row whose start date is in the window.

    Returns (slot table, cancelled rows set aside like tools/calendar/ca-l0-download.py).
    """
    base = (
        existing if existing is not None and len(existing) else pd.DataFrame(columns=EVENT_COLUMNS)
    )
    if len(base):
        starts = _start_utc(base["start_datetime"])
        lo = _aware(window_start).normalize()
        hi = _aware(window_end)
        in_window = starts.between(lo, hi) & base["calendar_id"].isin(calendar_ids)
        base = base[~in_window]
    new = (
        pd.DataFrame(fresh, columns=EVENT_COLUMNS) if fresh else pd.DataFrame(columns=EVENT_COLUMNS)
    )
    frames = [f for f in (base, new) if len(f)]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=EVENT_COLUMNS)
    if len(out):
        out = out.drop_duplicates(subset=["id"], keep="last")
    cancelled = out[out["status"] == "cancelled"] if len(out) else out
    out = out[out["status"] != "cancelled"] if len(out) else out
    return out.reset_index(drop=True), cancelled.reset_index(drop=True)


# --------------------------------------------------------------------------- contacts


def contact_row(c: dict, label: str) -> dict:
    emails = []
    for e in c.get("emailAddresses") or []:
        addr = (e.get("address") or "").strip()
        if addr and addr not in emails:
            emails.append(addr)
    phones = []
    for p in (
        [c.get("mobilePhone")]
        + list(c.get("businessPhones") or [])
        + list(c.get("homePhones") or [])
    ):
        p = (p or "").strip()
        if p and p not in phones:
            phones.append(p)
    first = c.get("givenName") or ""
    last = c.get("surname") or ""
    full = c.get("displayName") or " ".join(x for x in (first, last) if x)
    return {
        "full_name": full.strip(),
        "first_name": first,
        "last_name": last,
        "primary_phone": phones[0] if phones else "",
        "primary_email": emails[0] if emails else "",
        "organization": c.get("companyName") or "",
        "title": c.get("jobTitle") or "",
        "all_phones": "; ".join(phones),
        "all_emails": "; ".join(emails),
        "birthday": str(c.get("birthday") or "")[:10],
        "last_updated": c.get("lastModifiedDateTime") or "",
        "source": f"{SOURCE}:{label}",
        "source_id": c.get("id", ""),
    }


def merge_contacts(existing: pd.DataFrame | None, ours: list[dict], label: str) -> pd.DataFrame:
    """Keep every row of other origins, replace only the rows of this mailbox."""
    tag = f"{SOURCE}:{label}"
    new = (
        pd.DataFrame(ours, columns=CONTACT_COLUMNS)
        if ours
        else pd.DataFrame(columns=CONTACT_COLUMNS)
    )
    if len(new):
        new = new[
            (new["full_name"] != "") | (new["primary_email"] != "") | (new["primary_phone"] != "")
        ]
        new = new.drop_duplicates(subset=["source_id"], keep="last")
    if existing is None or not len(existing):
        return new.reset_index(drop=True)
    base = existing.copy()
    if "source" not in base.columns:
        base["source"] = ""
    base["source"] = base["source"].fillna("").astype(str)
    base = base[base["source"] != tag]
    out = pd.concat([base, new], ignore_index=True)
    # The reader does str(row.get(col)): a NaN from a column one side lacks would read "nan".
    # Only text columns are filled: an "" in a bool or number column of someone else's rows
    # would make the parquet write fail.
    for c in out.columns:
        values = out[c].dropna()
        if c in CONTACT_COLUMNS or (
            out[c].dtype == object and values.map(lambda v: isinstance(v, str)).all()
        ):
            out[c] = out[c].where(out[c].notna(), "")
    return out


SEED_SOURCE = "iphone-contacts-json"


def plugin_only(existing: pd.DataFrame | None) -> bool:
    """True when the address-book parquet holds only rows this plugin wrote (its own
    microsoft365:<label> rows and the iPhone JSON seed), i.e. the parquet exists because of us."""
    if existing is None or not len(existing):
        return True
    if "source" not in existing.columns:
        return False
    src = existing["source"].fillna("").astype(str)
    return bool((src.str.startswith(SOURCE + ":") | (src == SEED_SOURCE)).all())


def replace_seed(existing: pd.DataFrame | None, seed: list[dict]) -> pd.DataFrame:
    """The parquet with its iPhone JSON seed rows replaced by `seed` (the JSON as it is now)."""
    fresh = pd.DataFrame(seed, columns=CONTACT_COLUMNS)
    if existing is None or not len(existing):
        return fresh
    keep = existing[existing.get("source", pd.Series("", index=existing.index)) != SEED_SOURCE]
    return pd.concat([keep, fresh], ignore_index=True)


def seed_from_iphone_json(path) -> list[dict]:
    """Rows for the contacts the kernel reads from iphone-contacts.json.

    tools/cross-source/xs-l1-contacts-enrich.py:load_contacts reads that JSON as the address
    book only while contacts.parquet is missing; once the parquet exists the JSON is only an
    enrichment keyed by name. Writing our parquet without these rows would drop them, and
    seeding them only once would hide contacts added to the JSON later: while the parquet
    holds only this plugin's rows, the download re-seeds them from the JSON at every run.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    items = raw.get("contacts", []) if isinstance(raw, dict) else raw
    rows = []
    for c in items or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        parts = name.split()
        phones = [str(p).strip() for p in c.get("phones") or [] if str(p).strip()]
        emails = [str(e).strip() for e in c.get("emails") or [] if str(e).strip()]
        rows.append(
            {
                "full_name": name,
                "first_name": parts[0] if parts else "",
                "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
                "primary_phone": phones[0] if phones else "",
                "primary_email": emails[0] if emails else "",
                "organization": str(c.get("organization") or ""),
                "title": "",
                "all_phones": "; ".join(phones),
                "all_emails": "; ".join(emails),
                "birthday": str(c.get("birthday") or ""),
                "last_updated": str(c.get("last_updated") or ""),
                "source": SEED_SOURCE,
                "source_id": "",
            }
        )
    return rows


# --------------------------------------------------------------------------- slot ownership


def foreign_rows(path) -> int:
    """How many rows of a slot parquet were written by something other than this plugin."""
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return 0
    try:
        df = pd.read_parquet(p)
    except Exception:  # noqa: BLE001 - unreadable file: treat as someone else's
        return 1
    if not len(df):
        return 0
    if "source" not in df.columns:
        return len(df)
    return int((df["source"].fillna("").astype(str) != SOURCE).sum())
