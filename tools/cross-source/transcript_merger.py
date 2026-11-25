""










from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("ti.merger")


SOURCE_PRIORITY = {"attio": 1, "tactiq": 2, "plaud": 3}


GAP_FILL_DISCOUNT = 0.85
PLAUD_GENERIC_DISCOUNT = 0.70
PLAUD_NO_SPEAKER_DISCOUNT = 0.50


@dataclass
class NormalizedSegment:
    ""

    start_s: float
    end_s: float
    speaker: str
    text: str
    source: str
    quality: float = 1.0
    speaker_confidence: float = 1.0


@dataclass
class MergedSegment:
    ""

    start_s: float
    end_s: float
    speaker: str
    text: str
    source_primary: str
    source_backup: str | None = None
    gap_filled: bool = False
    quality_score: float = 1.0
    confidence_adjusted: float = 1.0


@dataclass
class MergeMetrics:
    ""

    total_segments: int = 0
    from_primary: int = 0
    from_gap_fill: int = 0
    gaps_detected: int = 0
    gaps_filled: int = 0
    conflicts_resolved: int = 0
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    confidence_weighted_avg: float = 0.0


@dataclass
class MergedTranscript:
    ""

    meeting_id: str = ""
    segments: list[MergedSegment] = field(default_factory=list)
    metrics: MergeMetrics = field(default_factory=MergeMetrics)





def detect_gaps(
    segments: list[NormalizedSegment],
    meeting_duration_s: float = 0.0,
) -> list[tuple[float, float]]:
    ""








    if not segments:
        if meeting_duration_s > 0:
            return [(0.0, meeting_duration_s)]
        return []


    sorted_segs = sorted(segments, key=lambda s: s.start_s)


    end = meeting_duration_s
    if end <= 0:
        end = max(s.end_s for s in sorted_segs) if sorted_segs else 0.0

    gaps = []


    if sorted_segs[0].start_s > 5.0:
        gaps.append((0.0, sorted_segs[0].start_s))


    for i in range(len(sorted_segs) - 1):
        gap_start = sorted_segs[i].end_s
        gap_end = sorted_segs[i + 1].start_s
        if gap_end - gap_start > 5.0:
            gaps.append((gap_start, gap_end))


    if end > 0 and sorted_segs[-1].end_s < end - 5.0:
        gaps.append((sorted_segs[-1].end_s, end))

    return gaps


def compute_coverage(segments: list[NormalizedSegment], duration_s: float) -> float:
    ""
    if duration_s <= 0 or not segments:
        return 0.0
    covered = sum(max(0, s.end_s - s.start_s) for s in segments)
    return min(1.0, covered / duration_s)





def fill_gaps(
    gaps: list[tuple[float, float]],
    backup_segments: list[NormalizedSegment],
) -> list[NormalizedSegment]:
    ""





    if not gaps or not backup_segments:
        return []

    fillers = []
    for gap_start, gap_end in gaps:
        for seg in backup_segments:

            overlap_start = max(seg.start_s, gap_start)
            overlap_end = min(seg.end_s, gap_end)
            if overlap_end - overlap_start > 1.0:
                fillers.append(
                    NormalizedSegment(
                        start_s=overlap_start,
                        end_s=overlap_end,
                        speaker=seg.speaker,
                        text=seg.text,
                        source=seg.source,
                        quality=seg.quality * GAP_FILL_DISCOUNT,
                        speaker_confidence=seg.speaker_confidence,
                    )
                )

    return fillers





def resolve_conflicts(
    primary: list[NormalizedSegment],
    backup: list[NormalizedSegment],
) -> list[NormalizedSegment]:
    ""






    if not backup:
        return list(primary)
    if not primary:
        return list(backup)

    result = list(primary)
    conflicts = 0

    for bseg in backup:
        overlaps = False
        for pseg in primary:

            if pseg.start_s < bseg.end_s and pseg.end_s > bseg.start_s:
                overlaps = True

                if pseg.quality < 0.3 and bseg.quality > pseg.quality:

                    result = [s for s in result if s is not pseg]
                    result.append(bseg)
                    conflicts += 1
                break

        if not overlaps:

            result.append(bseg)

    return sorted(result, key=lambda s: s.start_s)





def determine_primary_source(sources: dict[str, list[NormalizedSegment]]) -> str:
    ""
    best_source = "tactiq"
    best_priority = 99

    for source, segments in sources.items():
        if not segments:
            continue
        priority = SOURCE_PRIORITY.get(source, 10)
        if priority < best_priority:
            best_priority = priority
            best_source = source

    return best_source


def merge_transcript(
    sources: dict[str, list[NormalizedSegment]],
    meeting_id: str = "",
    meeting_duration_s: float = 0.0,
) -> MergedTranscript:
    ""
















    if not sources or all(not segs for segs in sources.values()):
        return MergedTranscript(meeting_id=meeting_id)


    primary_source = determine_primary_source(sources)
    primary_segs = sources.get(primary_source, [])


    backup_sources = sorted(
        [(src, segs) for src, segs in sources.items() if src != primary_source and segs],
        key=lambda x: SOURCE_PRIORITY.get(x[0], 10),
    )


    gaps = detect_gaps(primary_segs, meeting_duration_s)
    coverage_before = (
        compute_coverage(primary_segs, meeting_duration_s) if meeting_duration_s > 0 else 0.0
    )


    gap_filled_segs: list[NormalizedSegment] = []
    for _src_name, backup_segs in backup_sources:
        filled = fill_gaps(gaps, backup_segs)
        gap_filled_segs.extend(filled)

        if filled:
            remaining_gaps = []
            for gap_start, gap_end in gaps:
                filled_in_gap = [f for f in filled if f.start_s >= gap_start and f.end_s <= gap_end]
                if not filled_in_gap:
                    remaining_gaps.append((gap_start, gap_end))
            gaps = remaining_gaps


    all_backup = []
    for _src_name, backup_segs in backup_sources:
        all_backup.extend(backup_segs)
    resolved = resolve_conflicts(primary_segs, gap_filled_segs)


    merged_segs = []
    primary_count = 0
    gap_fill_count = 0

    for seg in sorted(resolved, key=lambda s: s.start_s):
        is_gap_fill = seg.source != primary_source
        confidence = seg.quality
        if is_gap_fill:
            confidence *= GAP_FILL_DISCOUNT
            gap_fill_count += 1
        else:
            primary_count += 1

        merged_segs.append(
            MergedSegment(
                start_s=seg.start_s,
                end_s=seg.end_s,
                speaker=seg.speaker,
                text=seg.text,
                source_primary=seg.source,
                source_backup=primary_source if is_gap_fill else None,
                gap_filled=is_gap_fill,
                quality_score=seg.quality,
                confidence_adjusted=round(confidence, 4),
            )
        )


    all_merged_normalized = [
        NormalizedSegment(s.start_s, s.end_s, s.speaker, s.text, s.source_primary)
        for s in merged_segs
    ]
    coverage_after = (
        compute_coverage(all_merged_normalized, meeting_duration_s)
        if meeting_duration_s > 0
        else 0.0
    )


    if merged_segs:
        total_dur = sum(max(0, s.end_s - s.start_s) for s in merged_segs)
        if total_dur > 0:
            conf_avg = (
                sum(s.confidence_adjusted * max(0, s.end_s - s.start_s) for s in merged_segs)
                / total_dur
            )
        else:
            conf_avg = sum(s.confidence_adjusted for s in merged_segs) / len(merged_segs)
    else:
        conf_avg = 0.0

    metrics = MergeMetrics(
        total_segments=len(merged_segs),
        from_primary=primary_count,
        from_gap_fill=gap_fill_count,
        gaps_detected=len(detect_gaps(primary_segs, meeting_duration_s)),
        gaps_filled=gap_fill_count,
        coverage_before=round(coverage_before, 4),
        coverage_after=round(coverage_after, 4),
        confidence_weighted_avg=round(conf_avg, 4),
    )

    return MergedTranscript(
        meeting_id=meeting_id,
        segments=merged_segs,
        metrics=metrics,
    )
