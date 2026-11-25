""













from __future__ import annotations

import logging
import re

log = logging.getLogger("kb.quality_scaler")


SPEAKER_MULTIPLIERS = {
    "named": 1.0,
    "generic": 0.80,
    "unknown": 0.60,
    "unattributed": 0.40,
}


_GENERIC_SPEAKER_RE = re.compile(r"^speaker\s*\d*$|^unknown$", re.IGNORECASE)


CONFIDENCE_FLOOR = 0.05


def classify_speaker_type(speaker: str | None) -> str:
    ""



    if not speaker or not speaker.strip():
        return "unattributed"
    s = speaker.strip()
    if _GENERIC_SPEAKER_RE.match(s):
        return "generic"
    if len(s) < 3:
        return "unknown"
    return "named"


def scale_fact_confidence(
    base_confidence: float,
    source_reliability: float = 0.70,
    segment_quality: float = 1.0,
    speaker_type: str = "named",
) -> tuple[float, str]:
    ""












    speaker_mult = SPEAKER_MULTIPLIERS.get(speaker_type, 0.60)


    confidence = base_confidence * source_reliability * segment_quality * speaker_mult


    confidence = max(CONFIDENCE_FLOOR, min(1.0, confidence))


    if speaker_type == "named" and confidence >= 0.50:
        category = "attributed"
    elif speaker_type in ("generic", "unknown") and confidence >= 0.30:
        category = "partially_attributed"
    else:
        category = "unattributed_conversation"

    return round(confidence, 4), category


def scale_facts_batch(
    facts: list[dict],
    source_reliability: float = 0.70,
    segment_quality: float = 1.0,
) -> list[dict]:
    ""












    for fact in facts:
        base_conf = fact.get("confidence", 0.60)
        if isinstance(base_conf, str):
            base_conf = {"high": 0.85, "medium": 0.60, "low": 0.35}.get(base_conf.lower(), 0.60)

        speaker = fact.get("speaker", "")
        speaker_type = classify_speaker_type(speaker)

        scaled, category = scale_fact_confidence(
            base_confidence=base_conf,
            source_reliability=source_reliability,
            segment_quality=segment_quality,
            speaker_type=speaker_type,
        )

        fact["scaled_confidence"] = scaled
        fact["fact_category"] = category
        fact["speaker_type"] = speaker_type

    return facts


def should_attribute_to_person(fact_category: str) -> bool:
    ""




    return fact_category != "unattributed_conversation"
