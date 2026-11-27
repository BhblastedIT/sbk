#!/usr/bin/env python3
""
















from __future__ import annotations

import glob
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_types import Evidence, EvidenceDirection, EvidenceSource
except ImportError:  # pragma: no cover
    from pl_types import Evidence, EvidenceDirection, EvidenceSource  # type: ignore[no-redef]

_DATA = Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
_CAL_GLOB = str(_DATA / "calendars" / "*" / "events.parquet")
_KB_PERSON_DIR = _DATA / "knowledge" / "entities" / "person"
_EMAIL_INDEX_PATH = _DATA / "plaud" / "_email_index.json"



MATCH_TOLERANCE_MIN: float = 20.0



CALENDAR_LOGODDS: float = 0.3


MAX_ATTENDEES: int = 6


# Your own addresses (sbk.config.json "own_emails") are never a speaker candidate.
try:
    from sbk_config import OWN_EMAILS as _OWN_EMAILS
except Exception:  # pragma: no cover - config absent in isolated tests
    _OWN_EMAILS = set()
_EXCLUDE_EXACT: frozenset[str] = frozenset(e.lower() for e in _OWN_EMAILS)
_EXCLUDE_SUBSTR: tuple[str, ...] = (
    "noreply",
    "no-reply",
    "calendar",
    "resource.calendar",
    "group.",
)


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _parse_attendees(raw: Any) -> list[str]:
    ""
    if raw is None:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [e.strip() for e in raw.split(",") if "@" in e]
    emails: list[str] = []
    if isinstance(data, list):
        for a in data:
            if isinstance(a, dict) and a.get("email"):
                emails.append(str(a["email"]).lower())
            elif isinstance(a, str) and "@" in a:
                emails.append(a.lower())
    return emails


def _is_excluded(email: str) -> bool:
    e = email.lower().strip()
    if e in _EXCLUDE_EXACT:
        return True
    return any(sub in e for sub in _EXCLUDE_SUBSTR)


def load_events(cal_glob: str = _CAL_GLOB) -> list[dict[str, Any]]:
    ""
    try:
        import pandas as pd
    except Exception:  # pragma: no cover
        return []
    out: list[dict[str, Any]] = []
    for f in glob.glob(cal_glob):
        try:
            df = pd.read_parquet(f)
        except Exception:  # noqa: BLE001
            continue
        for rec in df.to_dict("records"):
            out.append(rec)
    return out


def build_email_index(
    person_dir: Path = _KB_PERSON_DIR, cache: Path = _EMAIL_INDEX_PATH
) -> dict[str, dict[str, str]]:
    ""



    index: dict[str, dict[str, str]] = {}

    def _emails(obj: Any, acc: set[str]) -> None:
        if isinstance(obj, str):
            if "@" in obj and "." in obj and " " not in obj.strip():
                acc.add(obj.strip().lower())
        elif isinstance(obj, dict):
            for v in obj.values():
                _emails(v, acc)
        elif isinstance(obj, list):
            for v in obj:
                _emails(v, acc)

    for f in glob.glob(str(person_dir / "*.json")):
        try:
            e = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = e.get("name") or e.get("canonical_name") or e.get("display_name")
        if not name and isinstance(e.get("identity"), dict):
            name = e["identity"].get("name")
        eid = e.get("entity_id") or e.get("id") or Path(f).stem
        ems: set[str] = set()
        _emails(e, ems)
        for em in ems:
            if em not in index:
                index[em] = {"entity_id": str(eid), "name": str(name or "")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return index


def load_email_index(cache: Path = _EMAIL_INDEX_PATH) -> dict[str, dict[str, str]]:
    ""
    if not cache.exists():
        return {}
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def events_overlapping(
    events: list[dict[str, Any]],
    rec_start: datetime,
    rec_duration_min: float,
    tol_min: float = MATCH_TOLERANCE_MIN,
) -> list[dict[str, Any]]:
    ""
    rec_end = rec_start + timedelta(minutes=max(1.0, rec_duration_min))
    tol = timedelta(minutes=tol_min)
    out: list[dict[str, Any]] = []
    for ev in events:
        es = _parse_dt(ev.get("start_datetime"))
        ee = _parse_dt(ev.get("end_datetime")) or (es + timedelta(minutes=30) if es else None)
        if es is None or ee is None:
            continue

        if es - tol <= rec_end and ee + tol >= rec_start:
            out.append(ev)
    return out


def attendee_persons(
    events: list[dict[str, Any]],
    email_index: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    ""



    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for ev in events:
        emails = _parse_attendees(ev.get("attendees"))

        if len(emails) > MAX_ATTENDEES:
            continue
        for em in emails:
            if _is_excluded(em):
                continue
            person = email_index.get(em)
            if not person or not person.get("name"):
                continue
            key = person["entity_id"]
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": person["name"], "entity_id": person["entity_id"], "email": em})
    return out


def emit_calendar_evidence(
    speaker_ids: list[str],
    persons: list[dict[str, str]],
) -> dict[str, list[Evidence]]:
    ""




    if not persons or not speaker_ids:
        return {}
    proto = [
        Evidence(
            source=EvidenceSource.CALENDAR,
            claim=f"e' {p['name']}",
            weight=CALENDAR_LOGODDS,
            direction=EvidenceDirection.SUPPORT,
            entity_id=p.get("entity_id") or None,
            quote=f"attendee del meeting a calendario: {p['name']}",
            meta={"signal": "calendar_attendee", "email": p.get("email", "")},
        )
        for p in persons
    ]
    return {spk: [Evidence.from_dict(e.to_dict()) for e in proto] for spk in speaker_ids}
