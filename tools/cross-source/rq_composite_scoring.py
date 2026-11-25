""












from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

log = logging.getLogger("rq.scoring")




DEFAULT_WEIGHTS = {
    "frequency": 0.30,
    "intensity": 0.30,
    "reciprocity": 0.25,
    "shared_context": 0.15,
}


DUNBAR_CIRCLES = [
    (8.0, 10.01, "inner_circle"),
    (5.0, 8.0, "sympathy_group"),
    (3.0, 5.0, "active_network"),
    (1.5, 3.0, "full_network"),
    (0.0, 1.5, "extended"),
]


TREND_STRENGTHEN_RATIO = 1.15
TREND_COOLING_RATIO = 0.85


def compute_composite_score(
    dims: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    ""








    w = weights or DEFAULT_WEIGHTS
    raw = sum(dims.get(k, 0.0) * w.get(k, 0.0) for k in w)
    return max(1.0, min(10.0, 1.0 + raw * 9.0))





def normalize_frequency(
    weighted_interaction_count: float,
    max_in_network: float,
) -> float:
    ""








    if max_in_network <= 0 or weighted_interaction_count <= 0:
        return 0.0
    freq_raw = math.log1p(weighted_interaction_count)
    freq_max = math.log1p(max_in_network)
    return min(1.0, freq_raw / freq_max) if freq_max > 0 else 0.0


def normalize_intensity(
    avg_meeting_duration_min: float = 0.0,
    avg_email_length_chars: float = 0.0,
    avg_thread_depth: float = 0.0,
    max_meeting_duration: float = 120.0,
    max_email_length: float = 2000.0,
    max_thread_depth: float = 20.0,
) -> float:
    ""






    norm_meeting = (
        min(1.0, avg_meeting_duration_min / max_meeting_duration)
        if max_meeting_duration > 0
        else 0.0
    )
    norm_email = (
        min(1.0, avg_email_length_chars / max_email_length) if max_email_length > 0 else 0.0
    )
    norm_thread = min(1.0, avg_thread_depth / max_thread_depth) if max_thread_depth > 0 else 0.0
    return 0.4 * norm_meeting + 0.3 * norm_email + 0.3 * norm_thread


def normalize_reciprocity(
    initiated: int,
    received: int,
    reciprocal_channels: int = 0,
) -> float:
    ""
















    total = initiated + received
    if total == 0:
        return 0.0


    ratio = (
        min(initiated, received) / max(initiated, received) if max(initiated, received) > 0 else 0.0
    )



    minority = min(initiated, received)
    volume_signal = min(1.0, minority / 50.0)

    return ratio * 0.5 + volume_signal * 0.5


def normalize_channel_diversity(
    active_channels: int,
    max_channels: int = 5,
) -> float:
    ""










    return min(1.0, active_channels / max_channels) if max_channels > 0 else 0.0


def normalize_shared_context(
    shared_recurring_meetings: int = 0,
    shared_email_threads: int = 0,
    shared_calls: int = 0,
    same_deal: bool = False,


    same_team: bool = False,
) -> float:
    ""







    context = 0.0


    if shared_recurring_meetings >= 10:
        context += 0.40
    elif shared_recurring_meetings >= 5:
        context += 0.35
    elif shared_recurring_meetings >= 3:
        context += 0.25
    elif shared_recurring_meetings >= 1:
        context += 0.15


    if shared_email_threads >= 50:
        context += 0.30
    elif shared_email_threads >= 20:
        context += 0.25
    elif shared_email_threads >= 10:
        context += 0.15
    elif shared_email_threads >= 3:
        context += 0.10


    if shared_calls >= 20:
        context += 0.25
    elif shared_calls >= 10:
        context += 0.20
    elif shared_calls >= 5:
        context += 0.15
    elif shared_calls >= 1:
        context += 0.05


    if same_deal:
        context += 0.05

    return min(1.0, context)





def detect_trend(
    current_score: float,
    score_30d_ago: float | None = None,
    score_60d_ago: float | None = None,
    score_90d_ago: float | None = None,
    state: str = "active",
) -> str:
    ""




    if state == "ended":
        return "ended"
    if state == "dormant":
        return "dormant"


    if score_30d_ago is not None and score_30d_ago > 0:
        ratio = current_score / score_30d_ago
        if ratio >= TREND_STRENGTHEN_RATIO:
            return "strengthening"
        if ratio <= TREND_COOLING_RATIO:
            return "cooling"


    if score_90d_ago is not None and score_90d_ago > 0:
        ratio_90 = current_score / score_90d_ago
        if abs(1.0 - ratio_90) < 0.15:
            return "stable"
        if ratio_90 >= TREND_STRENGTHEN_RATIO:
            return "strengthening"
        if ratio_90 <= TREND_COOLING_RATIO:
            return "cooling"

    return "stable"





def get_dunbar_circle(score: float) -> str:
    ""







    for low, high, circle in DUNBAR_CIRCLES:
        if low <= score < high:
            return circle
    return "extended"


def get_dunbar_label(circle: str) -> str:
    ""
    labels = {
        "inner_circle": "Collaboratore strettissimo",
        "sympathy_group": "Contatto importante",
        "active_network": "Contatto regolare",
        "full_network": "Conoscenza",
        "extended": "Sotto soglia",
    }
    return labels.get(circle, circle)





def score_relationship(
    weighted_interaction_count: float,
    max_in_network: float,
    avg_meeting_duration_min: float = 0.0,
    avg_email_length_chars: float = 0.0,
    avg_thread_depth: float = 0.0,
    initiated: int = 0,
    received: int = 0,
    reciprocal_channels: int = 0,
    active_channels: int = 0,
    same_team: bool = False,
    shared_recurring_meetings: int = 0,
    shared_email_threads: int = 0,
    shared_calls: int = 0,
    same_deal: bool = False,
    score_30d_ago: float | None = None,
    score_90d_ago: float | None = None,
    state: str = "active",
) -> dict:
    ""




    dims = {
        "frequency": normalize_frequency(weighted_interaction_count, max_in_network),
        "intensity": normalize_intensity(
            avg_meeting_duration_min, avg_email_length_chars, avg_thread_depth
        ),
        "reciprocity": normalize_reciprocity(initiated, received, reciprocal_channels),
        "channel_diversity": normalize_channel_diversity(active_channels),
        "shared_context": normalize_shared_context(
            shared_recurring_meetings=shared_recurring_meetings,
            shared_email_threads=shared_email_threads,
            shared_calls=shared_calls,
            same_deal=same_deal,
        ),
    }

    score = round(compute_composite_score(dims), 1)
    trend = detect_trend(score, score_30d_ago, score_90d_ago=score_90d_ago, state=state)
    circle = get_dunbar_circle(score)

    return {
        "score": score,
        "breakdown": {k: round(v, 3) for k, v in dims.items()},
        "trend": trend,
        "dunbar_circle": circle,
        "dunbar_label": get_dunbar_label(circle),
    }
