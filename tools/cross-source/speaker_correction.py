""














from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from dataclasses import dataclass, field

from sbk_config import OWNER_LABEL, is_owner_speaker  # noqa: E402

log = logging.getLogger("ti.speaker_correction")


OWNER_VOCABULARY: set[str] = set()  # load from user config


_GENERIC_RE = re.compile(r"^speaker\s*\d*$|^unknown$|^$", re.IGNORECASE)




@dataclass
class SpeakerCorrection:
    ""

    original_speaker: str
    corrected_speaker: str
    correction_source: str
    confidence: float
    is_owner: bool = False


@dataclass
class CorrectionReport:
    ""

    total_segments: int = 0
    corrected: int = 0
    already_named: int = 0
    unattributed: int = 0
    corrections_by_source: dict[str, int] = field(default_factory=dict)





def correct_from_calendar(
    segments: list[dict],
    attendees: list[str],
) -> list[SpeakerCorrection]:
    ""











    corrections = []

    other_attendees = [a for a in attendees if not is_owner_speaker(a)]


    if len(other_attendees) != 1:
        return [
            SpeakerCorrection(
                original_speaker=str(s.get("speaker", "")),
                corrected_speaker=str(s.get("speaker", "")),
                correction_source="none",
                confidence=0.5,
            )
            for s in segments
        ]

    other_name = other_attendees[0]

    for seg in segments:
        speaker = str(seg.get("speaker", "")).strip()
        text = str(seg.get("content", seg.get("text", ""))).lower()

        if not _GENERIC_RE.match(speaker) and not is_owner_speaker(speaker):

            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=speaker,
                    correction_source="none",
                    confidence=0.85,
                )
            )
            continue


        is_owner = _detect_owner_vocabulary(text)

        if is_owner:
            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=OWNER_LABEL,
                    correction_source="calendar",
                    confidence=0.75,
                    is_owner=True,
                )
            )
        else:
            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=other_name,
                    correction_source="calendar",
                    confidence=0.70,
                )
            )

    return corrections





def correct_from_cross_source(
    plaud_segments: list[dict],
    reference_segments: list[dict],
    time_tolerance_s: float = 10.0,
) -> list[SpeakerCorrection]:
    ""











    corrections = []

    for seg in plaud_segments:
        speaker = str(seg.get("speaker", "")).strip()
        start = float(seg.get("start_s", seg.get("start", 0)))

        if not _GENERIC_RE.match(speaker):

            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=speaker,
                    correction_source="none",
                    confidence=0.85,
                )
            )
            continue


        best_ref = None
        best_dist = time_tolerance_s + 1
        for ref in reference_segments:
            ref_start = float(ref.get("start_s", ref.get("start", 0)))
            dist = abs(start - ref_start)
            if dist < best_dist:
                best_dist = dist
                best_ref = ref

        if best_ref and best_dist <= time_tolerance_s:
            ref_speaker = str(best_ref.get("speaker", best_ref.get("speakerName", ""))).strip()
            if ref_speaker and not _GENERIC_RE.match(ref_speaker):
                corrections.append(
                    SpeakerCorrection(
                        original_speaker=speaker,
                        corrected_speaker=ref_speaker,
                        correction_source="cross_source",
                        confidence=0.80,
                        is_owner=is_owner_speaker(ref_speaker),
                    )
                )
                continue


        corrections.append(
            SpeakerCorrection(
                original_speaker=speaker,
                corrected_speaker=speaker,
                correction_source="none",
                confidence=0.4,
            )
        )

    return corrections





def _detect_owner_vocabulary(text: str) -> bool:
    ""



    text_lower = text.lower()
    matches = sum(1 for word in OWNER_VOCABULARY if word in text_lower)
    return matches >= 2


def correct_from_vocabulary(
    segments: list[dict],
) -> list[SpeakerCorrection]:
    ""




    corrections = []
    for seg in segments:
        speaker = str(seg.get("speaker", "")).strip()
        text = str(seg.get("content", seg.get("text", ""))).lower()

        if not _GENERIC_RE.match(speaker):
            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=speaker,
                    correction_source="none",
                    confidence=0.85,
                )
            )
            continue

        if _detect_owner_vocabulary(text):
            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=OWNER_LABEL,
                    correction_source="vocabulary",
                    confidence=0.70,
                    is_owner=True,
                )
            )
        else:
            corrections.append(
                SpeakerCorrection(
                    original_speaker=speaker,
                    corrected_speaker=speaker,
                    correction_source="none",
                    confidence=0.4,
                )
            )

    return corrections





def correct_from_context(
    segments: list[dict],
    meeting_title: str = "",
    meeting_type: str = "",
) -> list[SpeakerCorrection]:
    ""




    corrections = []
    for seg in segments:
        speaker = str(seg.get("speaker", "")).strip()
        corrections.append(
            SpeakerCorrection(
                original_speaker=speaker,
                corrected_speaker=speaker,
                correction_source="none" if not _GENERIC_RE.match(speaker) else "context",
                confidence=0.85 if not _GENERIC_RE.match(speaker) else 0.50,
            )
        )
    return corrections





def apply_corrections(
    segments: list[dict],
    attendees: list[str] | None = None,
    reference_segments: list[dict] | None = None,
    meeting_title: str = "",
    meeting_type: str = "",
) -> tuple[list[SpeakerCorrection], CorrectionReport]:
    ""






    n = len(segments)
    corrections = [None] * n
    report = CorrectionReport(total_segments=n)


    if attendees:
        cal_corrections = correct_from_calendar(segments, attendees)
        for i, c in enumerate(cal_corrections):
            if c.correction_source != "none":
                corrections[i] = c
                report.corrections_by_source["calendar"] = (
                    report.corrections_by_source.get("calendar", 0) + 1
                )


    if reference_segments:
        xsrc_corrections = correct_from_cross_source(segments, reference_segments)
        for i, c in enumerate(xsrc_corrections):
            if corrections[i] is None and c.correction_source != "none":
                corrections[i] = c
                report.corrections_by_source["cross_source"] = (
                    report.corrections_by_source.get("cross_source", 0) + 1
                )


    vocab_corrections = correct_from_vocabulary(segments)
    for i, c in enumerate(vocab_corrections):
        if corrections[i] is None and c.correction_source != "none":
            corrections[i] = c
            report.corrections_by_source["vocabulary"] = (
                report.corrections_by_source.get("vocabulary", 0) + 1
            )


    for i in range(n):
        if corrections[i] is None:
            speaker = str(segments[i].get("speaker", "")).strip()
            is_named = bool(speaker) and not _GENERIC_RE.match(speaker)
            corrections[i] = SpeakerCorrection(
                original_speaker=speaker,
                corrected_speaker=speaker,
                correction_source="none",
                confidence=0.85 if is_named else 0.40,
            )
            if is_named:
                report.already_named += 1
            else:
                report.unattributed += 1

    report.corrected = sum(1 for c in corrections if c.correction_source != "none")

    return corrections, report
