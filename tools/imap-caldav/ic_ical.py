"""imap-caldav plugin: a small iCalendar (RFC 5545) reader that turns VEVENTs into rows with the
columns of the Google Calendar downloader (tools/calendar/ca-l0-download.py _riga_evento), so
tools/calendar/ca-l1-extract.py reads them unchanged.

Standard library only, plus dateutil.rrule for recurring events (python-dateutil is already in
uv.lock as a dependency of pandas; see the plugin report for the proposal to list it directly).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_INSTANCES = 1000  # per recurring series inside the window

EVENT_COLUMNS = [
    "id", "summary", "start_datetime", "end_datetime", "start_timezone", "location",
    "description", "organizer_email", "attendees", "attendee_count", "status", "calendar_name",
    "calendar_id", "conference_url", "event_type", "transparency", "color_id", "html_link",
    "recurring_event_id", "visibility", "end_timezone", "updated", "self_status",
    "organizer_self",
]  # fmt: skip

_PARTSTAT = {
    "ACCEPTED": "accepted",
    "DECLINED": "declined",
    "TENTATIVE": "tentative",
    "NEEDS-ACTION": "needsAction",
    "DELEGATED": "needsAction",
}
_STATUS = {"CONFIRMED": "confirmed", "TENTATIVE": "tentative", "CANCELLED": "cancelled"}
_CONF_PROPS = (
    "X-GOOGLE-CONFERENCE",
    "X-MICROSOFT-SKYPETEAMSMEETINGURL",
    "X-MICROSOFT-ONLINEMEETINGCONFLINK",
)
_MEETING_URL = re.compile(
    r"https://[^\s<>\"]*(?:zoom\.us/j/|meet\.google\.com/|teams\.microsoft\.com/l/meetup-join|"
    r"teams\.live\.com/meet/|whereby\.com/|meet\.jit\.si/)[^\s<>\"]*"
)


# --- Lexer ---------------------------------------------------------------------------------
@dataclass
class Prop:
    name: str
    params: dict
    value: str


@dataclass
class Component:
    name: str
    props: list[Prop] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def get(self, name: str) -> Prop | None:
        for p in self.props:
            if p.name == name:
                return p
        return None

    def all(self, name: str) -> list[Prop]:
        return [p for p in self.props if p.name == name]


def unfold(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line.strip():
            lines.append(line)
    return lines


def _split_unquoted(s: str, sep: str) -> list[str]:
    out, cur, q = [], [], False
    for ch in s:
        if ch == '"':
            q = not q
            cur.append(ch)
        elif ch == sep and not q:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_line(line: str) -> Prop:
    # NAME;PARAM=V;PARAM="V:x":VALUE  -> the first ':' outside quotes ends the parameters
    q = False
    cut = -1
    for i, ch in enumerate(line):
        if ch == '"':
            q = not q
        elif ch == ":" and not q:
            cut = i
            break
    head, value = (line, "") if cut < 0 else (line[:cut], line[cut + 1 :])
    parts = _split_unquoted(head, ";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return Prop(parts[0].upper(), params, value)


def parse_calendar(text: str) -> list[Component]:
    """Top-level components (normally one VCALENDAR)."""
    roots: list[Component] = []
    stack: list[Component] = []
    for line in unfold(text):
        p = parse_line(line)
        if p.name == "BEGIN":
            c = Component(p.value.upper())
            (stack[-1].children if stack else roots).append(c)
            stack.append(c)
        elif p.name == "END":
            if stack:
                stack.pop()
        elif stack:
            stack[-1].props.append(p)
    return roots


def unescape(v: str) -> str:
    return (
        v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
    ).replace("\\\\", "\\")


# --- Dates ---------------------------------------------------------------------------------
def _zone(tzid: str):
    if not tzid:
        return None
    try:
        return ZoneInfo(tzid.strip().strip("/"))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def parse_dt(prop: Prop | None):
    """-> (value, tzid). value is a date (all-day), an aware datetime, or a naive datetime
    (floating time, or a TZID this machine does not know, e.g. a Windows zone name)."""
    if prop is None or not prop.value:
        return None, ""
    v = prop.value.strip().split(",")[0]
    tzid = prop.params.get("TZID", "")
    if prop.params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return date(int(v[:4]), int(v[4:6]), int(v[6:8])), ""
    m = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", v)
    if not m:
        return None, tzid
    d, t, z = m.groups()
    naive = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), int(t[:2]), int(t[2:4]), int(t[4:6]))
    if z:
        return naive.replace(tzinfo=UTC), "UTC"
    zone = _zone(tzid)
    if zone is not None:
        return naive.replace(tzinfo=zone), tzid
    return naive, tzid


def parse_duration(s: str) -> timedelta | None:
    m = re.fullmatch(
        r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (s or "").strip()
    )
    if not m:
        return None
    sign, w, d, h, mi, se = m.groups()
    td = timedelta(
        weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0),
        seconds=int(se or 0),
    )  # fmt: skip
    return -td if sign == "-" else td


def iso(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    return v.isoformat()


def _utc_key(v) -> str:
    """Instance key used in ids, like Google's <id>_<YYYYMMDDTHHMMSSZ> (date: YYYYMMDD)."""
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            return v.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        return v.strftime("%Y%m%dT%H%M%S")
    return v.strftime("%Y%m%d")


def _cmp(v):
    """Comparable UTC datetime for window checks (naive and dates taken as UTC)."""
    if isinstance(v, datetime):
        return v.astimezone(UTC) if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime(v.year, v.month, v.day, tzinfo=UTC)


# --- Recurrence (dateutil) -------------------------------------------------------------------
def _rrule_text(rule: str, start) -> str:
    """Make UNTIL agree with DTSTART, as dateutil requires (aware <-> UTC, naive <-> naive)."""
    aware = isinstance(start, datetime) and start.tzinfo is not None

    def fix(m):
        v = m.group(1)
        if aware:
            if len(v) == 8:
                return f"UNTIL={v}T235959Z"
            return f"UNTIL={v if v.endswith('Z') else v + 'Z'}"
        if len(v) > 8 and not isinstance(start, datetime):
            return f"UNTIL={v[:8]}"
        return f"UNTIL={v.rstrip('Z')}"

    return re.sub(r"UNTIL=([0-9TZ]+)", fix, rule)


def expand(master: Component, start, window: tuple[datetime, datetime]) -> list:
    """Start values of the instances of a recurring master inside the window."""
    from dateutil.rrule import rruleset, rrulestr

    is_date = not isinstance(start, datetime)
    dt0 = datetime(start.year, start.month, start.day) if is_date else start
    rs = rruleset()
    for p in master.all("RRULE"):
        rs.rrule(rrulestr(_rrule_text(p.value, start), dtstart=dt0))
    for name, add in (("RDATE", rs.rdate), ("EXDATE", rs.exdate)):
        for p in master.all(name):
            for part in p.value.split(","):
                v, _tz = parse_dt(Prop(name, p.params, part))
                if v is None:
                    continue
                if isinstance(v, date) and not isinstance(v, datetime):
                    v = datetime(v.year, v.month, v.day)
                if isinstance(dt0, datetime) and dt0.tzinfo is not None and v.tzinfo is None:
                    v = v.replace(tzinfo=dt0.tzinfo)
                elif dt0.tzinfo is None and v.tzinfo is not None:
                    v = v.astimezone(UTC).replace(tzinfo=None)
                add(v)
    lo, hi = window
    if dt0.tzinfo is None:
        lo, hi = lo.replace(tzinfo=None), hi.replace(tzinfo=None)
    out = []
    for v in rs.between(lo, hi, inc=True):
        out.append(v.date() if is_date else v)
        if len(out) >= MAX_INSTANCES:
            break
    return out


# --- Rows ----------------------------------------------------------------------------------
def _mailto(v: str) -> str:
    v = (v or "").strip()
    return v[7:] if v.lower().startswith("mailto:") else ("" if ":" in v else v)


def _hash(*parts: str, n: int = 20) -> str:
    return hashlib.sha1("\x00".join(parts).encode("utf-8", "replace")).hexdigest()[:n]


def _conference(ev: Component, description: str, location: str) -> str:
    for name in _CONF_PROPS:
        p = ev.get(name)
        if p and p.value:
            return p.value.strip()
    for text in (location, description, (ev.get("URL").value if ev.get("URL") else "")):
        m = _MEETING_URL.search(text or "")
        if m:
            return m.group(0)
    return ""


def event_row(
    ev: Component,
    *,
    start,
    tzid: str,
    end,
    end_tzid: str,
    event_id: str,
    recurring_id: str,
    calendar_name: str,
    calendar_id: str,
    own: set[str],
) -> dict:
    summary = unescape(ev.get("SUMMARY").value) if ev.get("SUMMARY") else ""
    location = unescape(ev.get("LOCATION").value) if ev.get("LOCATION") else ""
    description = unescape(ev.get("DESCRIPTION").value) if ev.get("DESCRIPTION") else ""
    org = ev.get("ORGANIZER")
    organizer = _mailto(org.value) if org else ""
    attendees, self_status = [], ""
    for a in ev.all("ATTENDEE"):
        email = _mailto(a.value)
        if not email:
            continue
        status = _PARTSTAT.get(a.params.get("PARTSTAT", "").upper(), "")
        rec = {"email": email, "status": status}
        if a.params.get("CN"):
            rec["name"] = a.params["CN"]
        attendees.append(rec)
        if email.lower() in own and not self_status:
            self_status = status
    upd = ev.get("LAST-MODIFIED") or ev.get("DTSTAMP")
    updated, _ = parse_dt(upd)
    url = ev.get("URL").value.strip() if ev.get("URL") else ""
    return {
        "id": event_id,
        "summary": summary,
        "start_datetime": iso(start),
        "end_datetime": iso(end),
        "start_timezone": tzid,
        "location": location,
        "description": description,
        "organizer_email": organizer,
        "attendees": json.dumps(attendees, ensure_ascii=False),
        "attendee_count": len(attendees),
        "status": _STATUS.get(
            (ev.get("STATUS").value if ev.get("STATUS") else "").upper(), "confirmed"
        ),
        "calendar_name": calendar_name,
        "calendar_id": calendar_id,
        "conference_url": _conference(ev, description, location),
        "event_type": "default",
        "transparency": (ev.get("TRANSP").value.lower() if ev.get("TRANSP") else ""),
        "color_id": "",
        "html_link": url if url.startswith("https://") else "",
        "recurring_event_id": recurring_id,
        "visibility": (ev.get("CLASS").value.lower() if ev.get("CLASS") else ""),
        "end_timezone": end_tzid,
        "updated": iso(updated) if updated else "",
        "self_status": self_status,
        "organizer_self": "1" if organizer and organizer.lower() in own else "",
    }


def _like(start, end):
    """`end` turned into the same kind as `start` (date, naive or aware datetime), so that
    end - start never raises on a feed that mixes them."""
    if end is None:
        return None
    s_dt, e_dt = isinstance(start, datetime), isinstance(end, datetime)
    if not s_dt:
        return end.date() if e_dt else end
    if not e_dt:
        return datetime(end.year, end.month, end.day, tzinfo=start.tzinfo)
    if start.tzinfo is not None and end.tzinfo is None:
        return end.replace(tzinfo=start.tzinfo)
    if start.tzinfo is None and end.tzinfo is not None:
        return end.replace(tzinfo=None)
    return end


def _end_of(ev: Component, start, start_tz: str):
    end, end_tz = parse_dt(ev.get("DTEND"))
    end = _like(start, end)
    if end is None:
        dur = parse_duration(ev.get("DURATION").value) if ev.get("DURATION") else None
        if dur is not None:
            end, end_tz = start + dur, start_tz
        elif isinstance(start, datetime):
            end, end_tz = start, start_tz
        else:
            end, end_tz = start + timedelta(days=1), ""
    return end, end_tz


def rows_from_ics(
    text: str,
    *,
    account: str,
    calendar_name: str,
    calendar_id: str,
    own: set[str],
    window: tuple[datetime, datetime],
    warn=None,
) -> list[dict]:
    """Every VEVENT of one iCalendar object (or feed) as rows; recurring series are expanded
    inside the window, overrides (RECURRENCE-ID) replace their instance."""
    events: list[Component] = []
    for root in parse_calendar(text):
        stack = [root]
        while stack:
            c = stack.pop()
            if c.name == "VEVENT":
                events.append(c)
            stack.extend(c.children)
    by_uid: dict[str, dict] = {}
    for ev in events:
        uid = ev.get("UID").value.strip() if ev.get("UID") else ""
        if not uid:
            uid = "nouid-" + _hash(
                calendar_id, ev.get("DTSTART").value if ev.get("DTSTART") else ""
            )
        slot = by_uid.setdefault(uid, {"master": None, "overrides": {}})
        rid = ev.get("RECURRENCE-ID")
        if rid is not None:
            v, _tz = parse_dt(rid)
            if v is not None:
                slot["overrides"][_utc_key(v)] = ev
        else:
            slot["master"] = ev

    rows: list[dict] = []
    for uid, slot in by_uid.items():
        try:
            rows.extend(
                _rows_of_series(
                    uid, slot, account=account, calendar_name=calendar_name,
                    calendar_id=calendar_id, own=own, window=window, warn=warn,
                )
            )  # fmt: skip
        except Exception as e:  # noqa: BLE001 - one broken event never stops the calendar
            if warn:
                warn(f"one event not read ({type(e).__name__})")
    return rows


def _rows_of_series(
    uid: str,
    slot: dict,
    *,
    account: str,
    calendar_name: str,
    calendar_id: str,
    own: set[str],
    window: tuple[datetime, datetime],
    warn=None,
) -> list[dict]:
    rows: list[dict] = []
    base_id = "ic-" + _hash(account, calendar_id, uid)
    master = slot["master"]
    overrides = dict(slot["overrides"])
    if master is not None:
        start, tz = parse_dt(master.get("DTSTART"))
        if start is None:
            return rows
        end, end_tz = _end_of(master, start, tz)
        length = end - start
        if master.get("RRULE") or master.get("RDATE"):
            try:
                starts = expand(master, start, window)
            except Exception as e:  # noqa: BLE001 - a broken rule keeps the first instance
                if warn:
                    warn(f"recurrence not expanded ({type(e).__name__}); first instance kept")
                starts = [start]
            for s in starts:
                key = _utc_key(s)
                ov = overrides.pop(key, None)
                if ov is not None:
                    o_start, o_tz = parse_dt(ov.get("DTSTART"))
                    o_start = o_start or s
                    o_end, o_end_tz = _end_of(ov, o_start, o_tz or tz)
                    rows.append(
                        event_row(
                            ov, start=o_start, tzid=o_tz or tz, end=o_end, end_tzid=o_end_tz,
                            event_id=f"{base_id}_{key}", recurring_id=base_id,
                            calendar_name=calendar_name, calendar_id=calendar_id, own=own,
                        )
                    )  # fmt: skip
                    continue
                rows.append(
                    event_row(
                        master, start=s, tzid=tz, end=s + length, end_tzid=end_tz,
                        event_id=f"{base_id}_{key}", recurring_id=base_id,
                        calendar_name=calendar_name, calendar_id=calendar_id, own=own,
                    )
                )  # fmt: skip
        else:
            rows.append(
                event_row(
                    master, start=start, tzid=tz, end=end, end_tzid=end_tz, event_id=base_id,
                    recurring_id="", calendar_name=calendar_name, calendar_id=calendar_id,
                    own=own,
                )
            )  # fmt: skip
    # Overrides whose instance is outside the window or moved there from elsewhere.
    lo, hi = window
    for key, ov in overrides.items():
        o_start, o_tz = parse_dt(ov.get("DTSTART"))
        if o_start is None or not (lo <= _cmp(o_start) <= hi):
            continue
        o_end, o_end_tz = _end_of(ov, o_start, o_tz)
        rows.append(
            event_row(
                ov, start=o_start, tzid=o_tz, end=o_end, end_tzid=o_end_tz,
                event_id=f"{base_id}_{key}", recurring_id=base_id,
                calendar_name=calendar_name, calendar_id=calendar_id, own=own,
            )
        )  # fmt: skip
    return rows
