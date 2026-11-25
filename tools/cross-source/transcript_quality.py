""










from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("ti.quality")


_ACKS = {
    "si",
    "no",
    "ok",
    "yes",
    "yeah",
    "certo",
    "esatto",
    "giusto",
    "grazie",
    "thanks",
    "mhm",
    "uhm",
    "eh",
    "ah",
    "oh",
    "va bene",
    "perfetto",
    "capito",
    "sure",
    "right",
}


_GENERIC_SPEAKERS = re.compile(r"^speaker\s*\d*$|^unknown$|^$", re.IGNORECASE)


_SOURCE_BASELINES = {"attio": 0.90, "tactiq": 0.75, "plaud": 0.60}


@dataclass
class SegmentQuality:
    ""

    segment_idx: int
    language_detected: str = ""
    language_confidence: float = 1.0
    language_ok: bool = True
    speaker_identified: bool = True
    speaker_confidence: float = 1.0
    word_count: int = 0
    is_garbled: bool = False
    quality_score: float = 0.5


@dataclass
class TranscriptQualityReport:
    ""

    source: str
    meeting_id: str
    overall_score: float = 0.5
    language_coherence: float = 1.0
    speaker_coverage: float = 1.0
    word_density: float = 0.0
    garbled_ratio: float = 0.0
    segment_count: int = 0
    usable_segments: int = 0
    high_quality_segments: int = 0
    segment_qualities: list[SegmentQuality] = field(default_factory=list)





def is_garbled(text: str) -> bool:
    ""






    if not text or not text.strip():
        return True

    words = text.strip().lower().split()
    if not words:
        return True


    if len(words) < 3:
        joined = " ".join(words)
        if joined not in _ACKS and not any(w in _ACKS for w in words):
            return True


    if len(words) >= 3:
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2] and len(words[i]) > 1:
                return True

    return False





def detect_language_per_chunk(
    texts: list[str],
    chunk_size: int = 10,
    expected_lang: str = "",
) -> list[tuple[int, str, float, bool]]:
    ""









    try:
        from langdetect import LangDetectException, detect_langs
    except ImportError:
        return [(0, expected_lang or "unknown", 0.5, True)]

    results = []
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        combined = " ".join(t for t in chunk if t and t.strip())
        if len(combined) < 20:
            results.append((i, expected_lang or "unknown", 0.3, True))
            continue
        try:
            probs = detect_langs(combined)
            primary_lang = probs[0].lang
            confidence = probs[0].prob
            matches = primary_lang == expected_lang if expected_lang else True
            results.append((i, primary_lang, confidence, matches))
        except LangDetectException:
            results.append((i, "unknown", 0.3, False))

    return results





def assess_tactiq_transcript(
    blocks: list[dict],
    declared_lang: str = "",
    duration_s: float = 0.0,
) -> TranscriptQualityReport:
    ""






    if not blocks:
        return TranscriptQualityReport(source="tactiq", meeting_id="", overall_score=0.1)

    active_blocks = [b for b in blocks if not b.get("isDeleted", False)]
    texts = [str(b.get("transcript", "")).strip() for b in active_blocks]
    speakers = [str(b.get("speakerName", "")).strip() for b in active_blocks]


    lang_base = declared_lang.split("-")[0] if declared_lang else ""
    lang_results = detect_language_per_chunk(texts, chunk_size=10, expected_lang=lang_base)
    lang_ok_count = sum(1 for _, _, _, ok in lang_results if ok)
    lang_coherence = lang_ok_count / max(1, len(lang_results))


    seg_qualities = []
    for idx, (text, speaker) in enumerate(zip(texts, speakers)):
        wc = len(text.split()) if text else 0
        garbled = is_garbled(text)
        speaker_id = bool(speaker) and not _GENERIC_SPEAKERS.match(speaker)


        chunk_idx = idx // 10
        lang_info = (
            lang_results[min(chunk_idx, len(lang_results) - 1)]
            if lang_results
            else (0, "", 0.5, True)
        )
        _, det_lang, lang_conf, lang_match = lang_info


        lang_score = 1.0 if lang_match else 0.3
        speaker_score = 0.9 if speaker_id else 0.5
        content_score = min(1.0, wc / 15.0) if not garbled else 0.1
        source_base = _SOURCE_BASELINES["tactiq"]

        quality = (
            0.30 * lang_score + 0.25 * speaker_score + 0.25 * content_score + 0.20 * source_base
        )
        if garbled:
            quality *= 0.5

        seg_qualities.append(
            SegmentQuality(
                segment_idx=idx,
                language_detected=det_lang,
                language_confidence=lang_conf,
                language_ok=lang_match,
                speaker_identified=speaker_id,
                speaker_confidence=0.85 if speaker_id else 0.5,
                word_count=wc,
                is_garbled=garbled,
                quality_score=round(quality, 4),
            )
        )


    total = len(seg_qualities)
    garbled_count = sum(1 for s in seg_qualities if s.is_garbled)
    speaker_id_count = sum(1 for s in seg_qualities if s.speaker_identified)
    usable = sum(1 for s in seg_qualities if s.quality_score >= 0.3)
    high_q = sum(1 for s in seg_qualities if s.quality_score >= 0.7)
    total_words = sum(s.word_count for s in seg_qualities)


    if duration_s > 120:
        word_density = total_words / (duration_s / 60.0)
    else:
        word_density = 0.0


    avg_quality = sum(s.quality_score for s in seg_qualities) / max(1, total)
    overall = round(avg_quality, 4)

    return TranscriptQualityReport(
        source="tactiq",
        meeting_id="",
        overall_score=overall,
        language_coherence=round(lang_coherence, 4),
        speaker_coverage=round(speaker_id_count / max(1, total), 4),
        word_density=round(word_density, 1),
        garbled_ratio=round(garbled_count / max(1, total), 4),
        segment_count=total,
        usable_segments=usable,
        high_quality_segments=high_q,
        segment_qualities=seg_qualities,
    )





def assess_attio_transcript(
    segments: list[dict],
    duration_s: float = 0.0,
) -> TranscriptQualityReport:
    ""








    if not segments:
        return TranscriptQualityReport(source="attio", meeting_id="", overall_score=0.1)


    utterances: list[dict] = []
    current_speaker = None
    current_words: list[str] = []
    current_start = 0.0

    for seg in segments:
        speaker = str(seg.get("speaker", "")).strip()
        text = str(seg.get("text", "")).strip()
        start = float(seg.get("start", 0))
        if not text:
            continue
        if speaker == current_speaker:
            current_words.append(text)
        else:
            if current_speaker and current_words:
                utterances.append(
                    {
                        "speaker": current_speaker,
                        "text": " ".join(current_words),
                        "start": current_start,
                    }
                )
            current_speaker = speaker
            current_words = [text]
            current_start = start

    if current_speaker and current_words:
        utterances.append(
            {
                "speaker": current_speaker,
                "text": " ".join(current_words),
                "start": current_start,
            }
        )

    if not utterances:
        return TranscriptQualityReport(source="attio", meeting_id="", overall_score=0.1)


    seg_qualities = []
    for idx, utt in enumerate(utterances):
        text = utt["text"]
        speaker = utt["speaker"]
        wc = len(text.split())
        garbled = is_garbled(text)
        speaker_id = bool(speaker) and not _GENERIC_SPEAKERS.match(speaker)


        quality = (
            0.30 * 1.0
            + 0.25 * (0.9 if speaker_id else 0.5)
            + 0.25 * min(1.0, wc / 15.0)
            + 0.20 * _SOURCE_BASELINES["attio"]
        )
        if garbled:
            quality *= 0.5

        seg_qualities.append(
            SegmentQuality(
                segment_idx=idx,
                language_detected="",
                language_confidence=1.0,
                language_ok=True,
                speaker_identified=speaker_id,
                speaker_confidence=0.90 if speaker_id else 0.5,
                word_count=wc,
                is_garbled=garbled,
                quality_score=round(quality, 4),
            )
        )

    total = len(seg_qualities)
    garbled_count = sum(1 for s in seg_qualities if s.is_garbled)
    speaker_id_count = sum(1 for s in seg_qualities if s.speaker_identified)
    usable = sum(1 for s in seg_qualities if s.quality_score >= 0.3)
    high_q = sum(1 for s in seg_qualities if s.quality_score >= 0.7)
    total_words = sum(s.word_count for s in seg_qualities)


    if duration_s > 0 and segments:
        last_time = max(float(s.get("start", 0)) for s in segments if s.get("start"))
        coverage = min(1.0, last_time / duration_s) if duration_s > 0 else 1.0
    else:
        coverage = 1.0

    if duration_s > 120:
        word_density = total_words / (duration_s / 60.0)
    else:
        word_density = 0.0

    avg_quality = sum(s.quality_score for s in seg_qualities) / max(1, total)

    coverage_mult = min(1.0, coverage + 0.3) if duration_s > 0 else 1.0
    overall = round(avg_quality * coverage_mult, 4)

    return TranscriptQualityReport(
        source="attio",
        meeting_id="",
        overall_score=overall,
        language_coherence=1.0,
        speaker_coverage=round(speaker_id_count / max(1, total), 4),
        word_density=round(word_density, 1),
        garbled_ratio=round(garbled_count / max(1, total), 4),
        segment_count=total,
        usable_segments=usable,
        high_quality_segments=high_q,
        segment_qualities=seg_qualities,
    )





def assess_plaud_transcript(
    segments: list[dict],
    plaud_quality_score: float = 0.5,
) -> TranscriptQualityReport:
    ""








    if not segments:
        return TranscriptQualityReport(source="plaud", meeting_id="", overall_score=0.1)

    seg_qualities = []
    for idx, seg in enumerate(segments):
        text = str(seg.get("content", seg.get("text", ""))).strip()
        speaker = str(seg.get("speaker", "")).strip()
        attr_conf = float(seg.get("confidence", 0.5))
        wc = len(text.split()) if text else 0
        garbled = is_garbled(text)
        speaker_id = bool(speaker) and not _GENERIC_SPEAKERS.match(speaker)


        speaker_conf = attr_conf if attr_conf > 0 else (0.7 if speaker_id else 0.3)

        content_score = min(1.0, wc / 15.0) if not garbled else 0.2
        quality = (
            0.30 * 1.0
            + 0.30 * speaker_conf
            + 0.20 * content_score
            + 0.20 * _SOURCE_BASELINES["plaud"]
        )

        seg_qualities.append(
            SegmentQuality(
                segment_idx=idx,
                language_detected="",
                language_confidence=1.0,
                language_ok=True,
                speaker_identified=speaker_id,
                speaker_confidence=round(speaker_conf, 4),
                word_count=wc,
                is_garbled=garbled,
                quality_score=round(quality, 4),
            )
        )

    total = len(seg_qualities)
    garbled_count = sum(1 for s in seg_qualities if s.is_garbled)
    speaker_id_count = sum(1 for s in seg_qualities if s.speaker_identified)
    usable = sum(1 for s in seg_qualities if s.quality_score >= 0.3)
    high_q = sum(1 for s in seg_qualities if s.quality_score >= 0.7)


    avg_segment = sum(s.quality_score for s in seg_qualities) / max(1, total)
    overall = round(0.6 * avg_segment + 0.4 * plaud_quality_score, 4)

    return TranscriptQualityReport(
        source="plaud",
        meeting_id="",
        overall_score=overall,
        language_coherence=1.0,
        speaker_coverage=round(speaker_id_count / max(1, total), 4),
        word_density=0.0,
        garbled_ratio=round(garbled_count / max(1, total), 4),
        segment_count=total,
        usable_segments=usable,
        high_quality_segments=high_q,
        segment_qualities=seg_qualities,
    )
