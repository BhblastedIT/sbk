""











from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("ti.review_queue")


@dataclass
class ReviewItem:
    ""

    meeting_id: str
    title: str = ""
    date: str = ""
    source: str = ""
    priority_score: float = 0.0
    avg_quality: float = 0.0
    speaker_uncertain_pct: float = 0.0
    total_segments: int = 0
    potential_facts: int = 0
    participant_names: list[str] = field(default_factory=list)
    review_status: str = "pending"
    reviewed_at: str = ""
    notes: str = ""


def compute_priority(
    participant_importance: float = 1.0,
    avg_quality: float = 1.0,
    total_segments: int = 0,
) -> float:
    ""












    import math

    quality_gain = max(0.0, 1.0 - avg_quality)
    segment_factor = math.log1p(total_segments) / math.log1p(100)
    return round(participant_importance * quality_gain * segment_factor, 4)


def build_review_queue(
    items: list[dict],
    min_priority: float = 0.1,
    max_items: int = 50,
) -> list[ReviewItem]:
    ""











    queue = []
    for item in items:
        priority = compute_priority(
            participant_importance=item.get("participant_importance", 1.0),
            avg_quality=item.get("avg_quality", 0.5),
            total_segments=item.get("total_segments", 0),
        )

        if priority < min_priority:
            continue

        queue.append(
            ReviewItem(
                meeting_id=item.get("meeting_id", ""),
                title=item.get("title", ""),
                date=item.get("date", ""),
                source=item.get("source", ""),
                priority_score=priority,
                avg_quality=item.get("avg_quality", 0.5),
                speaker_uncertain_pct=item.get("speaker_uncertain_pct", 0.0),
                total_segments=item.get("total_segments", 0),
                potential_facts=item.get("potential_facts", 0),
                participant_names=item.get("participant_names", []),
            )
        )


    queue.sort(key=lambda r: r.priority_score, reverse=True)
    return queue[:max_items]


def mark_reviewed(
    queue: list[ReviewItem],
    meeting_id: str,
    notes: str = "",
) -> bool:
    ""



    for item in queue:
        if item.meeting_id == meeting_id:
            item.review_status = "reviewed"
            item.reviewed_at = datetime.now(UTC).isoformat()
            item.notes = notes
            return True
    return False


def mark_skipped(
    queue: list[ReviewItem],
    meeting_id: str,
) -> bool:
    ""
    for item in queue:
        if item.meeting_id == meeting_id:
            item.review_status = "skipped"
            return True
    return False


def get_pending_reviews(queue: list[ReviewItem]) -> list[ReviewItem]:
    ""
    return [item for item in queue if item.review_status == "pending"]


def save_review_queue(queue: list[ReviewItem], path: Path) -> None:
    ""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(queue),
        "pending": sum(1 for i in queue if i.review_status == "pending"),
        "reviewed": sum(1 for i in queue if i.review_status == "reviewed"),
        "skipped": sum(1 for i in queue if i.review_status == "skipped"),
        "items": [asdict(item) for item in queue],
    }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_review_queue(path: Path) -> list[ReviewItem]:
    ""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [ReviewItem(**item) for item in data.get("items", [])]
    except (ValueError, OSError, TypeError):
        return []
