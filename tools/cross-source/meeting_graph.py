""










from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("ti.meeting_graph")


MATCH_THRESHOLD = 0.55
TITLE_STRIP_RE = re.compile(r"\d{1,2}[/.\-]\d{1,2}([/.\-]\d{2,4})?|\s+")


@dataclass
class MeetingSource:
    ""

    source_type: str
    source_id: str
    title: str
    date: str
    start_time: str = ""
    duration_s: float = 0.0
    word_count: int = 0
    speakers: list[str] = field(default_factory=list)
    file_path: str = ""


@dataclass
class UnifiedMeeting:
    ""

    meeting_id: str
    canonical_date: str
    canonical_title: str
    sources: dict[str, MeetingSource] = field(default_factory=dict)
    match_confidence: float = 0.0
    attendees: list[str] = field(default_factory=list)





def _normalize_title(title: str) -> str:
    ""
    t = title.lower().strip()
    t = re.sub(r"\d{1,2}[/.\-]\d{1,2}([/.\-]\d{2,4})?", "", t)
    t = re.sub(r"#\d+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def compute_date_proximity(date_a: str, date_b: str) -> float:
    ""
    try:
        from datetime import datetime

        da = datetime.strptime(date_a[:10], "%Y-%m-%d")
        db = datetime.strptime(date_b[:10], "%Y-%m-%d")
        diff = abs((da - db).days)
    except (ValueError, TypeError):
        return 0.0
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.5
    if diff == 2:
        return 0.2
    return 0.0


def compute_title_similarity(title_a: str, title_b: str) -> float:
    ""
    a = _normalize_title(title_a)
    b = _normalize_title(title_b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def compute_duration_alignment(dur_a: float, dur_b: float) -> float:
    ""
    if dur_a <= 0 or dur_b <= 0:
        return 0.5
    max_dur = max(dur_a, dur_b)
    diff_pct = abs(dur_a - dur_b) / max_dur
    if diff_pct <= 0.15:
        return 1.0
    if diff_pct <= 0.30:
        return 0.7
    if diff_pct <= 0.50:
        return 0.4
    return 0.1


def compute_speaker_overlap(speakers_a: list[str], speakers_b: list[str]) -> float:
    ""
    if not speakers_a or not speakers_b:
        return 0.5
    set_a = {s.lower().strip() for s in speakers_a if s}
    set_b = {s.lower().strip() for s in speakers_b if s}
    if not set_a or not set_b:
        return 0.5
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def compute_match_score(a: MeetingSource, b: MeetingSource) -> float:
    ""







    date_score = compute_date_proximity(a.date, b.date)
    title_score = compute_title_similarity(a.title, b.title)
    duration_score = compute_duration_alignment(a.duration_s, b.duration_s)
    speaker_score = compute_speaker_overlap(a.speakers, b.speakers)

    return 0.35 * date_score + 0.25 * title_score + 0.20 * duration_score + 0.20 * speaker_score





def load_tactiq_sources(tactiq_dir: Path) -> list[MeetingSource]:
    ""
    meetings_pq = tactiq_dir / "processed" / "meetings.parquet"
    if not meetings_pq.exists():
        return []
    import pandas as pd

    df = pd.read_parquet(meetings_pq)
    sources = []
    for _, row in df.iterrows():
        speakers = []
        if "speakers" in row and pd.notna(row.get("speakers")):
            try:
                sp = (
                    json.loads(row["speakers"])
                    if isinstance(row["speakers"], str)
                    else row["speakers"]
                )
                if isinstance(sp, list):
                    speakers = [str(s) for s in sp]
            except (json.JSONDecodeError, TypeError):
                pass
        sources.append(
            MeetingSource(
                source_type="tactiq",
                source_id=str(row.get("meeting_id", "")),
                title=str(row.get("title", "")),
                date=str(row.get("created_date", ""))[:10],
                duration_s=float(row.get("duration_s", row.get("duration_min", 0) * 60) or 0),
                word_count=int(row.get("word_count", 0) or 0),
                speakers=speakers,
            )
        )
    return sources


def load_attio_sources(attio_dir: Path) -> list[MeetingSource]:
    ""
    transcripts_dir = attio_dir / "transcripts"
    if not transcripts_dir.exists():
        return []
    sources = []
    for jf in sorted(transcripts_dir.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        segments = data.get("segments", [])
        speakers = list({str(s.get("speaker", "")).strip() for s in segments if s.get("speaker")})
        word_count = sum(len(str(s.get("text", "")).split()) for s in segments)
        date = str(data.get("meeting_date", ""))[:10]
        duration = float(segments[-1].get("end", 0)) if segments else 0.0

        sources.append(
            MeetingSource(
                source_type="attio",
                source_id=data.get("meeting_id", jf.stem),
                title=str(data.get("meeting_title", "")),
                date=date,
                duration_s=duration,
                word_count=word_count,
                speakers=speakers,
                file_path=str(jf),
            )
        )
    return sources


def load_plaud_calendar_matches(crossref_path: Path) -> list[tuple[MeetingSource, list[str]]]:
    ""
    if not crossref_path.exists():
        return []
    try:
        data = json.loads(crossref_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    results = []
    for match in data.get("matches", []):
        attendees = match.get("attendees", [])
        source = MeetingSource(
            source_type="plaud",
            source_id=match.get("plaud_id", ""),
            title=match.get("calendar_event", ""),
            date=match.get("plaud_date", "")[:10],
            duration_s=float(match.get("plaud_duration_sec", 0) or 0),
            speakers=[],
        )
        results.append((source, attendees))
    return results





def _make_meeting_id(date: str, title: str) -> str:
    ""
    h = hashlib.md5(f"{date}:{_normalize_title(title)}".encode()).hexdigest()[:12]
    return f"mtg-{date}-{h}"


def build_meeting_graph(
    tactiq_dir: Path | None = None,
    attio_dir: Path | None = None,
    plaud_crossref: Path | None = None,
) -> list[UnifiedMeeting]:
    ""








    from sbk_config import DATA_ROOT

    if tactiq_dir is None:
        tactiq_dir = DATA_ROOT / "tactiq"
    if attio_dir is None:
        attio_dir = DATA_ROOT / "attio"
    if plaud_crossref is None:
        plaud_crossref = DATA_ROOT / "plaud" / "raw" / "_calendar_crossref.json"

    meetings: list[UnifiedMeeting] = []
    used_tactiq: set[str] = set()
    used_attio: set[str] = set()
    used_plaud: set[str] = set()


    tactiq_sources = load_tactiq_sources(tactiq_dir)
    attio_sources = load_attio_sources(attio_dir)
    plaud_matches = load_plaud_calendar_matches(plaud_crossref)

    log.info(
        "Sources loaded: %d Tactiq, %d Attio, %d Plaud (calendar-matched)",
        len(tactiq_sources),
        len(attio_sources),
        len(plaud_matches),
    )


    for plaud_src, attendees in plaud_matches:
        if not plaud_src.source_id:
            continue
        mid = _make_meeting_id(plaud_src.date, plaud_src.title)
        um = UnifiedMeeting(
            meeting_id=mid,
            canonical_date=plaud_src.date,
            canonical_title=plaud_src.title,
            sources={"plaud": plaud_src},
            match_confidence=0.70,
            attendees=attendees,
        )


        best_score = 0.0
        best_tactiq = None
        for tq in tactiq_sources:
            if tq.source_id in used_tactiq:
                continue
            score = compute_match_score(plaud_src, tq)
            if score > best_score and score >= MATCH_THRESHOLD:
                best_score = score
                best_tactiq = tq
        if best_tactiq:
            um.sources["tactiq"] = best_tactiq
            um.match_confidence = max(um.match_confidence, best_score)
            used_tactiq.add(best_tactiq.source_id)

        meetings.append(um)
        used_plaud.add(plaud_src.source_id)

    log.info(
        "Phase 1 (Plaud-Calendar): %d meetings, %d linked to Tactiq",
        len(meetings),
        sum(1 for m in meetings if "tactiq" in m.sources),
    )


    attio_matched = 0
    for at in attio_sources:
        if at.source_id in used_attio:
            continue
        best_score = 0.0
        best_tactiq = None
        for tq in tactiq_sources:
            if tq.source_id in used_tactiq:
                continue
            score = compute_match_score(at, tq)
            if score > best_score and score >= MATCH_THRESHOLD:
                best_score = score
                best_tactiq = tq

        if best_tactiq:
            mid = _make_meeting_id(at.date, at.title)
            um = UnifiedMeeting(
                meeting_id=mid,
                canonical_date=at.date,
                canonical_title=at.title or best_tactiq.title,
                sources={"attio": at, "tactiq": best_tactiq},
                match_confidence=best_score,
            )
            meetings.append(um)
            used_attio.add(at.source_id)
            used_tactiq.add(best_tactiq.source_id)
            attio_matched += 1
        else:

            mid = _make_meeting_id(at.date, at.title)
            meetings.append(
                UnifiedMeeting(
                    meeting_id=mid,
                    canonical_date=at.date,
                    canonical_title=at.title,
                    sources={"attio": at},
                    match_confidence=1.0,
                )
            )
            used_attio.add(at.source_id)

    log.info(
        "Phase 2 (Attio-Tactiq): %d matched, %d Attio orphans",
        attio_matched,
        len(attio_sources) - attio_matched,
    )


    for tq in tactiq_sources:
        if tq.source_id in used_tactiq:
            continue
        mid = _make_meeting_id(tq.date, tq.title)
        meetings.append(
            UnifiedMeeting(
                meeting_id=mid,
                canonical_date=tq.date,
                canonical_title=tq.title,
                sources={"tactiq": tq},
                match_confidence=1.0,
            )
        )


    meetings.sort(key=lambda m: m.canonical_date, reverse=True)


    multi_source = sum(1 for m in meetings if len(m.sources) >= 2)
    log.info(
        "Meeting graph: %d total, %d multi-source, %d single-source",
        len(meetings),
        multi_source,
        len(meetings) - multi_source,
    )

    return meetings


def meeting_graph_to_json(meetings: list[UnifiedMeeting]) -> dict:
    ""
    entries = []
    for m in meetings:
        sources_dict = {}
        for src_type, src in m.sources.items():
            sources_dict[src_type] = {
                "source_id": src.source_id,
                "title": src.title,
                "date": src.date,
                "duration_s": src.duration_s,
                "word_count": src.word_count,
                "speakers": src.speakers,
            }
        entries.append(
            {
                "meeting_id": m.meeting_id,
                "canonical_date": m.canonical_date,
                "canonical_title": m.canonical_title,
                "sources": sources_dict,
                "source_count": len(m.sources),
                "match_confidence": round(m.match_confidence, 4),
                "attendees": m.attendees,
            }
        )

    multi = sum(1 for e in entries if e["source_count"] >= 2)
    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "total_meetings": len(entries),
        "multi_source": multi,
        "single_source": len(entries) - multi,
        "meetings": entries,
    }
