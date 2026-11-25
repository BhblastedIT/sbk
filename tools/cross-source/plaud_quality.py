""














from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class TranscriptQuality:
    ""

    source_id: str
    quality_score: float
    speaker_score: float
    confidence_score: float
    diarization_score: float
    calendar_bonus: float
    segment_score: float
    category: str
    total_segments: int
    needs_review: bool





def _speaker_score(result: dict) -> float:
    ""



    named = result.get("named_speakers", [])
    generic = result.get("generic_speakers", [])
    total_speakers = len(named) + len(generic)

    if total_speakers == 0:
        return 0.1

    return max(0.3, len(named) / total_speakers)


def _confidence_score(result: dict) -> float:
    ""



    return result.get("stats", {}).get("avg_confidence", 0.2)


def _diarization_score(result: dict) -> float:
    ""



    category = result.get("category", "")
    if category == "monologue":
        return 1.0

    speakers = result.get("speakers_plaud", [])
    n_speakers = len(speakers) if isinstance(speakers, list) else speakers
    if n_speakers <= 2:
        return 1.0
    if n_speakers == 3:
        return 0.85
    return 0.7


def _calendar_bonus(result: dict) -> float:
    ""



    cal = result.get("calendar_match", {})
    if cal.get("event"):
        return 0.1
    return 0.0


def _segment_score(result: dict) -> float:
    ""



    stats = result.get("stats", {})
    total = (
        stats.get("owner_segments", 0)
        + stats.get("other_segments", 0)
        + stats.get("uncertain_segments", 0)
    )
    if total == 0:
        return 0.1

    uncertain_ratio = stats.get("uncertain_segments", 0) / total

    return max(0.2, 1.0 - uncertain_ratio * 0.8)


def compute_transcript_quality(result: dict) -> TranscriptQuality:
    ""







    source_file = result.get("source_file", "")
    source_id = source_file.replace(".json", "")

    sp_score = _speaker_score(result)
    conf_score = _confidence_score(result)
    diar_score = _diarization_score(result)
    cal_bonus = _calendar_bonus(result)
    seg_score = _segment_score(result)




    composite = (
        0.40 * sp_score + 0.20 * conf_score + 0.15 * diar_score + 0.25 * seg_score + cal_bonus
    )

    composite = max(0.1, min(1.0, composite))

    return TranscriptQuality(
        source_id=source_id,
        quality_score=round(composite, 3),
        speaker_score=round(sp_score, 3),
        confidence_score=round(conf_score, 3),
        diarization_score=round(diar_score, 3),
        calendar_bonus=round(cal_bonus, 3),
        segment_score=round(seg_score, 3),
        category=result.get("category", ""),
        total_segments=result.get("total_segments", 0),
        needs_review=result.get("stats", {}).get("needs_review", False),
    )




_INDEX_FILENAME = "_quality_index.json"


def build_quality_index(proc_dir: Path) -> dict[str, TranscriptQuality]:
    ""







    results_file = proc_dir / "_full_results_v2.json"
    if not results_file.exists():
        log.warning("No processed results found at %s", results_file)
        return {}

    results = json.loads(results_file.read_text(encoding="utf-8"))
    index: dict[str, TranscriptQuality] = {}

    for result in results:
        quality = compute_transcript_quality(result)
        index[quality.source_id] = quality


    index_path = proc_dir / _INDEX_FILENAME
    serialized = {k: asdict(v) for k, v in index.items()}
    index_path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Built quality index: %d transcripts, avg score %.3f", len(index), _avg_score(index))

    return index


def load_quality_index(proc_dir: Path) -> dict[str, float]:
    ""









    index_path = proc_dir / _INDEX_FILENAME
    if not index_path.exists():
        log.warning("Quality index not found at %s — using default scores", index_path)
        return {}

    raw = json.loads(index_path.read_text(encoding="utf-8"))
    return {k: v["quality_score"] for k, v in raw.items()}


def get_quality_score(source_id: str, quality_index: dict[str, float]) -> float:
    ""








    return quality_index.get(source_id, 0.5)


def _avg_score(index: dict[str, TranscriptQuality]) -> float:
    if not index:
        return 0.0
    return sum(q.quality_score for q in index.values()) / len(index)
