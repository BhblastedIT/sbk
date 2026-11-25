""














from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT

log = logging.getLogger("ti.enhanced_extraction")


@dataclass
class EnrichedTranscript:
    ""

    meeting_id: str = ""
    title: str = ""
    date: str = ""
    source: str = ""
    text: str = ""
    context_block: str = ""
    avg_quality: float = 1.0
    speaker_coverage: float = 1.0
    is_merged: bool = False
    segment_count: int = 0


def load_plaud_with_attribution(plaud_dir: Path | None = None) -> list[dict]:
    ""






    if plaud_dir is None:
        plaud_dir = DATA_ROOT / "plaud"

    processed = plaud_dir / "processed" / "_full_results_v2.json"
    raw_dir = plaud_dir / "raw"


    if processed.exists():
        try:
            data = json.loads(processed.read_text(encoding="utf-8"))
            if isinstance(data, list):
                log.info("Loaded %d Plaud transcripts with attribution overlay", len(data))
                return data
        except (ValueError, OSError):
            pass


    transcripts = []
    if raw_dir.exists():
        for jf in sorted(raw_dir.glob("*.json")):
            if jf.name.startswith("_"):
                continue
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    transcripts.append(
                        {
                            "source_file": jf.name,
                            "segments": [
                                {
                                    "content": s.get("content", ""),
                                    "speaker": s.get("speaker", ""),
                                    "confidence": 0.5,
                                }
                                for s in raw
                            ],
                        }
                    )
            except (ValueError, OSError):
                continue
        log.info("Loaded %d Plaud transcripts from raw (no attribution)", len(transcripts))

    return transcripts


def prepare_enriched_prompt(
    title: str,
    date: str,
    transcript_text: str,
    context_block: str = "",
    max_context_chars: int = 1000,
) -> str:
    ""
















    parts = [f"Title: {title}", f"Date: {date}"]

    if context_block:
        trimmed = context_block[:max_context_chars]
        parts.append(f"\n## Meeting Context\n{trimmed}")

    parts.append(f"\n## Transcript\n{transcript_text}")

    return "\n".join(parts)


def compute_quality_inheritance(
    base_confidence: float,
    segment_quality: float = 1.0,
    gap_filled: bool = False,
    speaker_type: str = "named",
) -> float:
    ""









    from kb_quality_scaler import CONFIDENCE_FLOOR, SPEAKER_MULTIPLIERS


    conf = base_confidence


    conf *= segment_quality


    if gap_filled:
        conf *= 0.85


    speaker_mult = SPEAKER_MULTIPLIERS.get(speaker_type, 0.60)
    conf *= speaker_mult

    return max(CONFIDENCE_FLOOR, min(1.0, round(conf, 4)))


def enrich_transcript_for_extraction(
    meeting_id: str = "",
    title: str = "",
    date: str = "",
    source: str = "",
    transcript_text: str = "",
    speaker_names: list[str] | None = None,
    attendee_emails: list[str] | None = None,
) -> EnrichedTranscript:
    ""



    from transcript_context import build_meeting_context, format_context_for_prompt


    ctx = build_meeting_context(
        meeting_id=meeting_id,
        meeting_date=date,
        meeting_title=title,
        speaker_names=speaker_names,
        attendee_emails=attendee_emails,
    )
    context_block = format_context_for_prompt(ctx)

    return EnrichedTranscript(
        meeting_id=meeting_id,
        title=title,
        date=date,
        source=source,
        text=transcript_text,
        context_block=context_block,
        is_merged=False,
        segment_count=len(transcript_text.split("\n")) if transcript_text else 0,
    )
