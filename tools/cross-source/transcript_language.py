""











from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("ti.language")


EXPECTED_LANGUAGES = {"it", "en", "es"}


_ACKS = {"si", "no", "ok", "yes", "yeah", "sure", "mhm", "certo", "grazie", "thanks"}


@dataclass
class SegmentLanguageInfo:
    ""

    chunk_start_idx: int
    chunk_end_idx: int
    detected_lang: str
    confidence: float
    matches_declared: bool
    status: str
    word_count: int = 0


@dataclass
class TranscriptLanguageReport:
    ""

    declared_lang: str = ""
    majority_lang: str = ""
    total_chunks: int = 0
    good_chunks: int = 0
    degraded_chunks: int = 0
    garbled_chunks: int = 0
    coherence_score: float = 1.0
    language_switch_detected: bool = False
    switch_point_idx: int = -1
    chunk_analysis: list[SegmentLanguageInfo] = field(default_factory=list)


def _is_garbled_text(text: str) -> bool:
    ""
    if not text or len(text.strip()) < 10:
        return False
    words = text.strip().lower().split()
    if len(words) < 3:
        return False

    for i in range(len(words) - 2):
        if words[i] == words[i + 1] == words[i + 2] and len(words[i]) > 1:
            return True
    return False


def analyze_transcript_language(
    segments: list[dict],
    declared_lang: str = "",
    chunk_size: int = 10,
    text_key: str = "transcript",
) -> TranscriptLanguageReport:
    ""










    if not segments:
        return TranscriptLanguageReport(declared_lang=declared_lang)


    texts = [str(s.get(text_key, s.get("text", s.get("content", "")))).strip() for s in segments]
    declared_base = declared_lang.split("-")[0].lower() if declared_lang else ""


    try:
        from langdetect import LangDetectException, detect_langs
    except ImportError:

        return TranscriptLanguageReport(
            declared_lang=declared_lang,
            majority_lang=declared_base or "unknown",
            total_chunks=1,
            good_chunks=1,
            coherence_score=1.0,
        )

    chunk_infos: list[SegmentLanguageInfo] = []

    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        combined = " ".join(t for t in chunk if t)
        word_count = len(combined.split())
        end_idx = min(i + chunk_size, len(texts))


        if _is_garbled_text(combined):
            chunk_infos.append(
                SegmentLanguageInfo(
                    chunk_start_idx=i,
                    chunk_end_idx=end_idx,
                    detected_lang="garbled",
                    confidence=0.0,
                    matches_declared=False,
                    status="garbled",
                    word_count=word_count,
                )
            )
            continue

        if len(combined) < 20:

            chunk_infos.append(
                SegmentLanguageInfo(
                    chunk_start_idx=i,
                    chunk_end_idx=end_idx,
                    detected_lang=declared_base or "unknown",
                    confidence=0.3,
                    matches_declared=True,
                    status="degraded",
                    word_count=word_count,
                )
            )
            continue

        try:
            probs = detect_langs(combined)
            det_lang = probs[0].lang
            det_conf = probs[0].prob
        except LangDetectException:
            chunk_infos.append(
                SegmentLanguageInfo(
                    chunk_start_idx=i,
                    chunk_end_idx=end_idx,
                    detected_lang="unknown",
                    confidence=0.3,
                    matches_declared=False,
                    status="degraded",
                    word_count=word_count,
                )
            )
            continue

        matches = det_lang == declared_base if declared_base else det_lang in EXPECTED_LANGUAGES


        if matches and det_conf >= 0.7:
            status = "good"
        elif matches or det_conf >= 0.5:
            status = "degraded"
        else:
            status = "garbled"

        chunk_infos.append(
            SegmentLanguageInfo(
                chunk_start_idx=i,
                chunk_end_idx=end_idx,
                detected_lang=det_lang,
                confidence=det_conf,
                matches_declared=matches,
                status=status,
                word_count=word_count,
            )
        )


    total = len(chunk_infos)
    good = sum(1 for c in chunk_infos if c.status == "good")
    degraded = sum(1 for c in chunk_infos if c.status == "degraded")
    garbled = sum(1 for c in chunk_infos if c.status == "garbled")
    coherence = good / max(1, total)


    from collections import Counter

    lang_counts = Counter(
        c.detected_lang for c in chunk_infos if c.detected_lang not in ("garbled", "unknown")
    )
    majority = lang_counts.most_common(1)[0][0] if lang_counts else declared_base or "unknown"


    switch_detected = False
    switch_idx = -1
    if len(chunk_infos) >= 2:
        for j in range(len(chunk_infos) - 1):
            if chunk_infos[j].status == "garbled" and chunk_infos[j + 1].status == "good":
                switch_detected = True
                switch_idx = chunk_infos[j + 1].chunk_start_idx
                break

    return TranscriptLanguageReport(
        declared_lang=declared_lang,
        majority_lang=majority,
        total_chunks=total,
        good_chunks=good,
        degraded_chunks=degraded,
        garbled_chunks=garbled,
        coherence_score=round(coherence, 4),
        language_switch_detected=switch_detected,
        switch_point_idx=switch_idx,
        chunk_analysis=chunk_infos,
    )


def get_processable_segments(
    report: TranscriptLanguageReport,
) -> tuple[list[int], list[int], list[int]]:
    ""







    good = []
    degraded = []
    garbled = []

    for chunk in report.chunk_analysis:
        indices = list(range(chunk.chunk_start_idx, chunk.chunk_end_idx))
        if chunk.status == "good":
            good.extend(indices)
        elif chunk.status == "degraded":
            degraded.extend(indices)
        else:
            garbled.extend(indices)

    return good, degraded, garbled
