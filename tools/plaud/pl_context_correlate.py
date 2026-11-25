#!/usr/bin/env python3
""


















from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_REPO_DIR = _TOOLS_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from tools.plaud.pl_calendar import (
    attendee_persons,
    events_overlapping,
    load_email_index,
    load_events,
)

try:
    from tools.knowledge_aliases import canonical as _alias_canonical
except Exception:  # pragma: no cover
    _alias_canonical = lambda raw: None  # noqa: E731

_DATA = Path.home() / ".sbk-data"
INDEX_PATH = _DATA / "plaud" / "raw" / "_file_index.json"
EMAILS_GLOB = _DATA / "emails"
SLACK_INTERACTIONS = _DATA / "slack" / "processed" / "interactions-slack.parquet"


MEETING_RE = re.compile(
    r"\b(call|meeting|riunion\w*|appuntament\w*|ci\s+(sentiamo|vediamo)|invit\w*|"
    r"zoom|meet\.google|teams|alle\s+\d{1,2}[:.]\d{2})\b",
    re.I,
)

EMAIL_WINDOW_BEFORE_H = 36
EMAIL_WINDOW_AFTER_H = 2
SLACK_WINDOW_H = 3


class _Ctx:
    ""

    def __init__(self):
        self._events = None
        self._email_index = None
        self._emails = None
        self._slack = None
        self._index = None

    @property
    def index(self) -> dict[str, dict]:
        if self._index is None:
            raw = json.loads(INDEX_PATH.read_text())
            self._index = {str(e["id"]): e for e in raw}
        return self._index

    @property
    def events(self):
        if self._events is None:


            cur = load_events()
            bak_glob = str(_DATA / "calendars.bak-example" / "*" / "events.parquet")
            try:
                bak = load_events(bak_glob)
            except Exception:
                bak = []
            seen = set()
            merged = []
            for ev in cur + bak:
                key = (
                    str(ev.get("start_datetime"))[:16],
                    str(ev.get("summary") or ev.get("title") or "")[:60],
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(ev)
            self._events = merged
        return self._events

    @property
    def email_index(self):
        if self._email_index is None:
            self._email_index = load_email_index()
        return self._email_index

    @property
    def emails(self) -> pd.DataFrame:
        if self._emails is None:
            frames = []
            for p in sorted(EMAILS_GLOB.glob("*/messages.parquet")):
                try:
                    df = pd.read_parquet(
                        p, columns=["date", "from_addr", "to_addr", "subject", "body_text"]
                    )
                    df["account"] = p.parent.name
                    frames.append(df)
                except Exception:
                    continue
            if not frames:
                self._emails = pd.DataFrame()
            else:
                em = pd.concat(frames, ignore_index=True)
                em["dt"] = pd.to_datetime(em["date"], errors="coerce", utc=True)
                self._emails = em.dropna(subset=["dt"])
        return self._emails

    @property
    def slack(self) -> pd.DataFrame:
        if self._slack is None:
            try:
                sl = pd.read_parquet(
                    SLACK_INTERACTIONS, columns=["from_user", "to_user", "channel", "timestamp"]
                )
                sl["dt"] = pd.to_datetime(sl["timestamp"], errors="coerce", utc=True)
                self._slack = sl.dropna(subset=["dt"])
            except Exception:
                self._slack = pd.DataFrame()
        return self._slack


_CTX = _Ctx()


try:
    from sbk_config import OWN_EMAILS, is_own_name, is_owner_speaker

    _OWN = {e.lower() for e in OWN_EMAILS}
except Exception:
    _OWN = set()

    def is_own_name(name: str) -> bool:  # type: ignore[misc]
        return False

    def is_owner_speaker(label: str) -> bool:  # type: ignore[misc]
        return False


def _is_owner_user(u: str) -> bool:
    """A Slack/WhatsApp sender that is you (sbk.config.json owner / own_names / own_emails)."""
    return bool(u) and (u.lower().strip() in _OWN or is_own_name(u) or is_owner_speaker(u))


def _resolve_email(addr: str) -> dict | None:
    ""




    if not addr:
        return None
    addr_l = addr.lower().strip()
    if addr_l in _OWN:
        return None
    hit = _CTX.email_index.get(addr_l)
    if hit and hit.get("name"):
        return {"name": hit["name"], "entity_id": hit.get("entity_id", ""), "email": addr.lower()}
    return None


def _emails_around(rec_start: datetime) -> list[dict]:
    em = _CTX.emails
    if em.empty:
        return []
    lo = rec_start - timedelta(hours=EMAIL_WINDOW_BEFORE_H)
    hi = rec_start + timedelta(hours=EMAIL_WINDOW_AFTER_H)
    win = em[(em["dt"] >= lo) & (em["dt"] <= hi)]
    hits = []
    for row in win.itertuples():
        subj = str(row.subject or "")
        body = str(row.body_text or "")[:2000]
        if not (MEETING_RE.search(subj) or MEETING_RE.search(body)):
            continue
        people = []
        for field in (row.from_addr, row.to_addr):
            for part in str(field or "").split(","):
                m = re.search(r"<([^>]+@[^>]+)>", part) or re.search(r"([\w.+-]+@[\w.-]+)", part)
                if m:
                    p = _resolve_email(m.group(1))
                    if p and p["name"] not in {x["name"] for x in people}:
                        people.append(p)
        if not people:
            continue
        quote = (
            subj
            if MEETING_RE.search(subj)
            else (
                MEETING_RE.search(body)
                and body[
                    max(0, MEETING_RE.search(body).start() - 60) : MEETING_RE.search(body).start()
                    + 120
                ]
            )
        )
        hits.append(
            {
                "when": row.dt.isoformat(),
                "subject": subj[:120],
                "people": people,
                "quote": (quote or "")[:180],
            }
        )
    return hits[:8]


def _slack_around(rec_start: datetime) -> list[dict]:
    sl = _CTX.slack
    if sl.empty:
        return []
    lo = rec_start - timedelta(hours=SLACK_WINDOW_H)
    hi = rec_start + timedelta(hours=SLACK_WINDOW_H)
    win = sl[(sl["dt"] >= lo) & (sl["dt"] <= hi)]
    if win.empty:
        return []
    counts: dict[tuple[str, str], int] = {}
    for row in win.itertuples():
        other = None
        fu, tu = str(row.from_user or ""), str(row.to_user or "")
        if _is_owner_user(fu):
            other = tu
        elif _is_owner_user(tu):
            other = fu
        if other and other.strip():
            key = (other.strip(), str(row.channel or ""))
            counts[key] = counts.get(key, 0) + 1
    out = [
        {"person": k[0], "channel": k[1], "messages": v}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return out[:6]


def correlate(file_id: str) -> dict:
    ""
    e = _CTX.index.get(str(file_id))
    if not e or not e.get("st"):
        return {}
    rec_start = datetime.fromtimestamp(e["st"] / 1000, tz=UTC)
    dur_min = float(e.get("duration_sec") or 0) / 60.0

    evs = events_overlapping(_CTX.events, rec_start, dur_min)



    def _ev_hours(ev):
        from tools.plaud.pl_calendar import _parse_dt

        es, ee = _parse_dt(ev.get("start_datetime")), _parse_dt(ev.get("end_datetime"))
        if not es or not ee:
            return 0.0
        return (ee - es).total_seconds() / 3600.0

    evs = [ev for ev in evs if 0.0 < _ev_hours(ev) <= 12.0]
    pool = attendee_persons(evs, _CTX.email_index)

    pool = [
        p
        for p in pool
        if not re.match(r"^person_[0-9a-f]+$", p.get("name", ""))
        and not is_own_name(p.get("name", ""))
    ]
    for p in pool:
        ali = _alias_canonical(p.get("name", ""))
        if ali:
            p["name"] = ali["name"]
            if ali["entity_id"]:
                p["entity_id"] = ali["entity_id"]
    cal = [
        {
            "title": str(ev.get("summary") or ev.get("title") or "")[:100],
            "start": str(ev.get("start_datetime") or "")[:16],
            "account": ev.get("account", ""),
            "has_link": bool(ev.get("hangout_link") or ev.get("conference_link")),
            "location": str(ev.get("location") or "")[:60],
        }
        for ev in evs
    ]
    return {
        "file_id": str(file_id),
        "when": rec_start.isoformat(),
        "duration_min": round(dur_min, 1),
        "calendar_events": cal,
        "attendee_pool": pool,
        "email_hits": _emails_around(rec_start),
        "slack_activity": _slack_around(rec_start),
    }


def main() -> int:
    ids = sys.argv[1:]
    if not ids:
        print("uso: pl_context_correlate.py <file_id> [file_id...]")
        return 2
    for fid in ids:
        c = correlate(fid)
        print(json.dumps(c, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
