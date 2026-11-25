""

















from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any





_THIS = Path(__file__).resolve()

_REPO_ROOT = _THIS.parents[3]
_TOOLS_DIR = _REPO_ROOT / "tools"
_PLAUD_DIR = _TOOLS_DIR / "plaud"
for _p in (str(_REPO_ROOT), str(_TOOLS_DIR), str(_PLAUD_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tools.plaud.pl_name_index import load_or_build as _load_name_index
    from tools.plaud.pl_resolver import resolve_speakers
    from tools.plaud.pl_types import SpeakerResolution
except ImportError:  # pragma: no cover - fallback when tools/ is directly on the path
    from pl_name_index import load_or_build as _load_name_index  # type: ignore[no-redef]
    from pl_resolver import resolve_speakers  # type: ignore[no-redef]
    from pl_types import SpeakerResolution  # type: ignore[no-redef]






try:
    from sbk_config import PLAUD_DIR as _DEFAULT_RAW_DIR
except Exception:  # pragma: no cover - fallback outside the project path
    _DEFAULT_RAW_DIR = Path.home() / ".sbk-data" / "plaud" / "raw"




LANE_ORDER: tuple[str, ...] = ("AUTO", "CONFERMA", "CONTESTO")


LANE_LABELS: dict[str, dict[str, str]] = {
    "AUTO": {
        "title": "AUTO",
        "hint": "high confidence, accept in bulk",
        "badge": "badge-success",
    },
    "CONFERMA": {
        "title": "CONFIRM",
        "hint": "medium confidence, confirm in under 10s",
        "badge": "badge-warning",
    },
    "CONTESTO": {
        "title": "CONTEXT",
        "hint": "low confidence, give context by voice",
        "badge": "badge-error",
    },
}






_NAME_INDEX_CACHE: Any | None = None
_NAME_INDEX_TRIED = False


def _get_name_index() -> Any | None:
    ""



    global _NAME_INDEX_CACHE, _NAME_INDEX_TRIED
    if _NAME_INDEX_TRIED:
        return _NAME_INDEX_CACHE
    _NAME_INDEX_TRIED = True
    try:
        _NAME_INDEX_CACHE = _load_name_index()
    except Exception:  # noqa: BLE001 - silent fallback by design
        _NAME_INDEX_CACHE = None
    return _NAME_INDEX_CACHE


def reset_name_index_cache() -> None:
    ""
    global _NAME_INDEX_CACHE, _NAME_INDEX_TRIED
    _NAME_INDEX_CACHE = None
    _NAME_INDEX_TRIED = False






_CLEAN_REGISTRY_CACHE: Any | None = None
_CLEAN_REGISTRY_TRIED = False
_VOICE_ID_RE = re.compile(r"#\s*ID:\s*([0-9a-f]{6,})", re.IGNORECASE)


def _get_clean_registry() -> Any | None:
    ""
    global _CLEAN_REGISTRY_CACHE, _CLEAN_REGISTRY_TRIED
    if _CLEAN_REGISTRY_TRIED:
        return _CLEAN_REGISTRY_CACHE
    _CLEAN_REGISTRY_TRIED = True
    try:
        from tools.plaud.pl_voice_match import build_clean_registry

        reg_path = Path(_DEFAULT_RAW_DIR).parent / "_speaker_registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        _CLEAN_REGISTRY_CACHE = build_clean_registry(reg) or None
    except Exception:  # noqa: BLE001 - best-effort: no registry, no voice
        _CLEAN_REGISTRY_CACHE = None
    return _CLEAN_REGISTRY_CACHE


_CAL_EVENTS_CACHE: Any | None = None
_CAL_DATA_TRIED = False
_EMAIL_INDEX_CACHE: Any | None = None


def _get_calendar_data() -> tuple[Any | None, Any | None]:
    ""
    global _CAL_EVENTS_CACHE, _CAL_DATA_TRIED, _EMAIL_INDEX_CACHE
    if _CAL_DATA_TRIED:
        return _CAL_EVENTS_CACHE, _EMAIL_INDEX_CACHE
    _CAL_DATA_TRIED = True
    try:
        from tools.plaud.pl_calendar import load_email_index, load_events

        _CAL_EVENTS_CACHE = load_events() or None
        _EMAIL_INDEX_CACHE = load_email_index() or None
    except Exception:  # noqa: BLE001
        _CAL_EVENTS_CACHE = None
        _EMAIL_INDEX_CACHE = None
    return _CAL_EVENTS_CACHE, _EMAIL_INDEX_CACHE


def _get_detail_evidence(
    source_file: str, speaker_ids: list[str]
) -> tuple[dict[str, list[Any]] | None, dict[str, list[Any]] | None]:
    ""


    voice_ev: dict[str, list[Any]] | None = None
    cal_ev: dict[str, list[Any]] | None = None
    try:
        from tools.plaud.pl_write import _http, get_auth

        stem = source_file[:-5] if source_file.endswith(".json") else source_file
        txt = Path(_DEFAULT_RAW_DIR) / f"{stem}.txt"
        if not txt.exists():
            return None, None
        m = _VOICE_ID_RE.search(txt.read_text(encoding="utf-8", errors="replace"))
        if not m:
            return None, None
        wt, api = get_auth()
        detail = _http("GET", api, f"/file/detail/{m.group(1)}", wt)
        data = detail.get("data") or detail


        clean = _get_clean_registry()
        if clean:
            from tools.plaud.pl_voice_match import emit_voice_evidence, match_speakers

            emb = data.get("embeddings", {})
            voice_ev = emit_voice_evidence(match_speakers(emb, clean)) or None


        events, eidx = _get_calendar_data()
        st = data.get("start_time")
        if events and eidx and speaker_ids and st:
            from datetime import UTC, datetime

            from tools.plaud.pl_calendar import (
                attendee_persons,
                emit_calendar_evidence,
                events_overlapping,
            )

            rec_dt = datetime.fromtimestamp(int(st) / 1000, tz=UTC)
            dur = data.get("duration")
            dur_min = (int(dur) / 1000 / 60) if dur else 30.0
            ov = events_overlapping(events, rec_dt, dur_min)
            persons = attendee_persons(ov, eidx)
            cal_ev = emit_calendar_evidence(list(speaker_ids), persons) or None
    except Exception:  # noqa: BLE001 - best-effort, never block the cockpit
        return voice_ev, cal_ev
    return voice_ev, cal_ev







def _load_raw_segments(source_file: str, raw_dir: Path | str | None = None) -> list[dict[str, Any]]:
    ""



    base = Path(raw_dir) if raw_dir is not None else _DEFAULT_RAW_DIR
    path = base / source_file
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        segs = data.get("segments") or data.get("transcript") or []
    else:
        segs = data
    return list(segs)







def resolution_to_ui(res: SpeakerResolution) -> dict[str, Any]:
    ""



    best = res.best

    evidence: list[dict[str, Any]] = []
    if best is not None:
        for ev in best.evidence:
            evidence.append(
                {
                    "source": ev.source.value,
                    "claim": ev.claim,
                    "quote": ev.quote,
                    "weight": round(ev.weight, 3),
                    "direction": ev.direction.value,
                    "entity_id": ev.entity_id,
                }
            )

    candidates: list[dict[str, Any]] = [
        {
            "name": c.name,
            "entity_id": c.entity_id,
            "confidence": round(c.confidence, 4),
            "confidence_pct": round(c.confidence * 100),
            "sources": sorted(s.value for s in c.sources),

            "why": _candidate_why(c),
        }
        for c in res.candidates
    ]

    return {
        "speaker_id": res.speaker_id,
        "plaud_label": res.plaud_label,
        "best_name": best.name if best is not None else None,
        "best_entity_id": best.entity_id if best is not None else None,



        "proposed_name": res.proposed_name,
        "corroborated": bool(res.corroborated),
        "confidence": round(res.posterior, 4),
        "confidence_pct": round(res.posterior * 100),
        "lane": res.lane.value,
        "plaud_disagree": bool(res.plaud_disagree),
        "contradiction": round(res.contradiction_score, 4),
        "contradiction_pct": round(res.contradiction_score * 100),
        "provenance": res.provenance.value,
        "candidates": candidates,
        "evidence": evidence,
        "n_candidates": len(candidates),
    }


def _sort_key(s: dict[str, Any]) -> tuple[Any, ...]:
    ""

    return (not s["plaud_disagree"], -s["confidence"], s["speaker_id"])


def _candidate_why(cand: Any) -> list[str]:
    ""

    why: list[str] = []
    for ev in cand.evidence:
        s = ev.source.value
        if s == "voice_embedding":
            cos = ev.meta.get("cosine")
            why.append(
                f"voice similar to your recorded voice of {cand.name}"
                + (f" ({cos:.2f})" if cos else "")
            )
        elif s == "calendar":
            why.append("was on your calendar (invited to the meeting)")
        elif s == "transcript_context":
            q = (ev.quote or ev.claim or "").strip()[:70]
            why.append(f"in the transcript: «{q}»" if q else "mentioned in the transcript")
        elif s == "plaud_label":
            why.append("is the current Plaud label")
    return list(dict.fromkeys(why))


def _speaker_extracts(
    segments: list[dict[str, Any]] | None, speaker_id: str, k: int = 5
) -> list[dict[str, Any]]:
    ""

    if not segments:
        return []
    out: list[dict[str, Any]] = []
    for seg in segments:
        sid = seg.get("original_speaker") or seg.get("speaker")
        if sid != speaker_id:
            continue
        c = (seg.get("content") or "").strip()
        if len(c) > 15:
            out.append(
                {"text": c[:200], "start": seg.get("start_time"), "end": seg.get("end_time")}
            )
        if len(out) >= k:
            break
    return out


def build_cockpit_payload(
    resolutions: dict[str, SpeakerResolution],
    source_file: str | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ""



    speakers = [resolution_to_ui(res) for res in resolutions.values()]
    for sp in speakers:
        sp["extracts"] = _speaker_extracts(segments, sp["speaker_id"])

    lanes: dict[str, list[dict[str, Any]]] = {ln: [] for ln in LANE_ORDER}
    for sp in speakers:
        lanes.setdefault(sp["lane"], []).append(sp)
    for ln in lanes:
        lanes[ln].sort(key=_sort_key)

    counts = {ln: len(lanes.get(ln, [])) for ln in LANE_ORDER}
    n_disagree = sum(1 for sp in speakers if sp["plaud_disagree"])

    return {
        "source_file": source_file,
        "speakers": speakers,
        "lanes": lanes,
        "lane_order": list(LANE_ORDER),
        "lane_labels": LANE_LABELS,
        "counts": counts,
        "n_speakers": len(speakers),
        "n_disagree": n_disagree,
    }






_UNSET = object()


def resolve_source_file(
    source_file: str,
    raw_dir: Path | str | None = None,
    name_index: Any = _UNSET,
    calibrated: bool = False,
) -> dict[str, Any]:
    ""











    segments = _load_raw_segments(source_file, raw_dir=raw_dir)

    idx = _get_name_index() if name_index is _UNSET else name_index



    voice_ev: dict[str, list[Any]] | None = None
    cal_ev: dict[str, list[Any]] | None = None
    if raw_dir is None:
        speaker_ids = sorted(
            {
                (s.get("original_speaker") or s.get("speaker") or "")
                for s in segments
                if (s.get("original_speaker") or s.get("speaker"))
            }
        )
        voice_ev, cal_ev = _get_detail_evidence(source_file, speaker_ids)

    resolutions = resolve_speakers(
        segments,
        file_ctx={"filename": source_file},
        name_index=idx,
        calibrated=calibrated,
        voice_evidence=voice_ev,
        calendar_evidence=cal_ev,
    )
    payload = build_cockpit_payload(resolutions, source_file=source_file, segments=segments)

    try:
        stem = source_file[:-5] if source_file.endswith(".json") else source_file
        txt = Path(_DEFAULT_RAW_DIR) / f"{stem}.txt"
        if txt.exists():
            m = _VOICE_ID_RE.search(txt.read_text(encoding="utf-8", errors="replace"))
            payload["plaud_file_id"] = m.group(1) if m else None
    except Exception:  # noqa: BLE001
        payload["plaud_file_id"] = None
    return payload
