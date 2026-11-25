""













from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

log = logging.getLogger("rq.deep")





INTERRUPTION_CAUSES = {
    "exit_company": {"label": "Uscita dall'azienda", "default_confidence": "certain"},
    "project_ended": {"label": "Fine progetto", "default_confidence": "high"},
    "role_change": {"label": "Cambio ruolo", "default_confidence": "high"},
    "natural_decline": {"label": "Diradamento naturale", "default_confidence": "medium"},
    "out_of_scope": {"label": "Fuori contesto", "default_confidence": "medium"},
    "unknown": {"label": "Causa non determinata", "default_confidence": "low"},
}


def analyze_interruption(
    person_email: str,
    relationship: dict,
    personio_index: dict[str, dict] | None = None,
    interaction_dates: list[datetime] | None = None,
) -> dict:
    ""












    state = relationship.get("state", "active")
    if state == "active":
        return {
            "cause": None,
            "confidence": None,
            "evidence": "Relationship is active, no interruption to analyze",
            "date_of_change": None,
        }

    personio_index = personio_index or {}


    emp = personio_index.get(person_email.lower().strip())
    if emp:
        status = str(emp.get("status", "")).lower()
        if status in ("inactive", "terminated", "offboarded"):
            term_date = emp.get("termination_date") or emp.get("end_date")
            return {
                "cause": "exit_company",
                "confidence": "certain",
                "evidence": f"Personio status: {status}",
                "date_of_change": str(term_date) if term_date else None,
            }


    if interaction_dates and len(interaction_dates) >= 5:
        cause = _check_project_pattern(interaction_dates)
        if cause:
            return cause


    if interaction_dates and len(interaction_dates) >= 10:
        cause = _check_gradual_decline(interaction_dates)
        if cause:
            return cause


    return {
        "cause": "unknown",
        "confidence": "low",
        "evidence": "No clear cause detected from available data",
        "date_of_change": None,
    }


def _check_project_pattern(dates: list[datetime]) -> dict | None:
    ""




    if len(dates) < 5:
        return None

    sorted_dates = sorted(dates)


    gaps = []
    for i in range(len(sorted_dates) - 1):
        gap_days = (sorted_dates[i + 1] - sorted_dates[i]).total_seconds() / 86400.0
        gaps.append((i, gap_days))

    if not gaps:
        return None


    gaps.sort(key=lambda g: g[1], reverse=True)
    largest_gap_idx, largest_gap_days = gaps[0]

    if largest_gap_days < 60:
        return None


    burst_dates = sorted_dates[largest_gap_idx + 1 :]
    if len(burst_dates) < 5:
        return None

    burst_span = (burst_dates[-1] - burst_dates[0]).total_seconds() / 86400.0
    if burst_span > 180:
        return None

    return {
        "cause": "project_ended",
        "confidence": "high",
        "evidence": (
            f"Concentrated burst of {len(burst_dates)} interactions "
            f"over {burst_span:.0f} days, preceded by {largest_gap_days:.0f} day gap"
        ),
        "date_of_change": str(burst_dates[-1]),
    }


def _check_gradual_decline(dates: list[datetime]) -> dict | None:
    ""
    sorted_dates = sorted(dates)
    if len(sorted_dates) < 10:
        return None


    n = len(sorted_dates)
    third = n // 3

    first_third = sorted_dates[:third]
    last_third = sorted_dates[-third:]


    def avg_gap(subset):
        if len(subset) < 2:
            return float("inf")
        gaps = [
            (subset[i + 1] - subset[i]).total_seconds() / 86400.0 for i in range(len(subset) - 1)
        ]
        return sum(gaps) / len(gaps) if gaps else float("inf")

    first_gap = avg_gap(first_third)
    last_gap = avg_gap(last_third)


    if first_gap > 0 and last_gap / first_gap >= 3.0:
        return {
            "cause": "natural_decline",
            "confidence": "medium",
            "evidence": (
                f"Average gap increased from {first_gap:.0f} to {last_gap:.0f} days "
                f"(first vs last third of interaction history)"
            ),
            "date_of_change": None,
        }

    return None





def detect_events(
    current: dict,
    previous: dict | None = None,
) -> list[dict]:
    ""








    events = []

    if previous is None:
        return events

    prev_state = previous.get("state", "active")
    curr_state = current.get("state", "active")
    prev_score = previous.get("score", 0.0)
    curr_score = current.get("score", 0.0)


    if prev_state in ("dormant", "ended") and curr_state == "active":
        events.append(
            {
                "type": "reactivation",
                "detail": f"Reactivated from {prev_state} to active",
                "significance": "high",
            }
        )


    if (
        prev_score is not None
        and prev_score > 0
        and curr_score is not None
        and curr_score < prev_score * 0.7
    ):
        events.append(
            {
                "type": "sudden_cooling",
                "detail": f"Score dropped {prev_score:.1f} -> {curr_score:.1f} ({(1 - curr_score / prev_score) * 100:.0f}% decrease)",
                "significance": "medium",
            }
        )


    prev_intensity = (previous.get("breakdown") or {}).get("intensity", 0.0)
    curr_intensity = (current.get("breakdown") or {}).get("intensity", 0.0)
    if prev_intensity > 0 and curr_intensity > prev_intensity * 1.5:
        events.append(
            {
                "type": "intensity_spike",
                "detail": f"Intensity surged {prev_intensity:.2f} -> {curr_intensity:.2f}",
                "significance": "medium",
            }
        )


    prev_type = previous.get("relationship_type", "")
    curr_type = current.get("relationship_type", "")
    curr_type_conf = current.get("type_confidence", "")
    if (
        prev_type
        and curr_type
        and prev_type != curr_type
        and curr_type_conf
        in (
            "certain",
            "probable",
        )
    ):
        events.append(
            {
                "type": "type_change",
                "detail": f"Type changed: {prev_type} -> {curr_type}",
                "significance": "high",
            }
        )


    prev_reciprocity = (previous.get("breakdown") or {}).get("reciprocity", 0.5)
    curr_reciprocity = current.get("breakdown", {}).get("reciprocity", 0.5)
    if prev_reciprocity > 0.6 and curr_reciprocity < 0.3:
        events.append(
            {
                "type": "reciprocity_flip",
                "detail": f"Reciprocity dropped {prev_reciprocity:.2f} -> {curr_reciprocity:.2f}",
                "significance": "medium",
            }
        )

    return events





def build_timeline(
    relationship: dict,
    events: list[dict] | None = None,
    interaction_dates: list[datetime] | None = None,
) -> list[dict]:
    ""









    timeline = []


    first_date = relationship.get("first_interaction")
    if first_date:
        timeline.append(
            {
                "date": str(first_date),
                "event": "Prima interazione",
                "source": "data",
            }
        )


    if interaction_dates and len(interaction_dates) >= 5:
        peak = _detect_peak_period(interaction_dates)
        if peak:
            timeline.append(
                {
                    "date": str(peak["start"]),
                    "event": f"Periodo di picco ({peak['count']} interazioni in {peak['span_days']:.0f}gg)",
                    "source": "detected",
                }
            )


    state = relationship.get("state", "active")
    if state in ("dormant", "ended"):
        last_date = relationship.get("last_interaction")
        if last_date:
            label = "Relazione conclusa" if state == "ended" else "Relazione dormiente"
            timeline.append(
                {
                    "date": str(last_date),
                    "event": label,
                    "source": "data",
                }
            )


    if events:
        for event in events:
            timeline.append(
                {
                    "date": event.get("date", ""),
                    "event": event["detail"],
                    "source": "detected",
                }
            )


    timeline.sort(key=lambda e: str(e.get("date", "")))
    return timeline


def _detect_peak_period(dates: list[datetime]) -> dict | None:
    ""



    if len(dates) < 5:
        return None

    sorted_dates = sorted(dates)
    best_count = 0
    best_start = None
    best_end = None

    for i, start_date in enumerate(sorted_dates):

        count = 0
        for j in range(i, len(sorted_dates)):
            gap = (sorted_dates[j] - start_date).total_seconds() / 86400.0
            if gap <= 30:
                count += 1
            else:
                break

        if count > best_count:
            best_count = count
            best_start = start_date

            for j in range(i, len(sorted_dates)):
                gap = (sorted_dates[j] - start_date).total_seconds() / 86400.0
                if gap <= 30:
                    best_end = sorted_dates[j]
                else:
                    break

    if best_count >= 5 and best_start and best_end:
        span = (best_end - best_start).total_seconds() / 86400.0
        return {
            "start": best_start,
            "end": best_end,
            "count": best_count,
            "span_days": span,
        }

    return None





def get_cause_label(cause: str) -> str:
    ""
    info = INTERRUPTION_CAUSES.get(cause)
    return info["label"] if info else cause
