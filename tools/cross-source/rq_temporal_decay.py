""







from __future__ import annotations

import logging
import math
import sys
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import compute_expected_cadence, get_half_life, load_decay_config

log = logging.getLogger("rq.decay")


STATE_ACTIVE = "active"
STATE_COOLING = "cooling"
STATE_DORMANT = "dormant"
STATE_ENDED = "ended"


def compute_decay(
    score_at_last_interaction: float,
    days_since_last: float,
    half_life_days: int,
) -> float:
    ""











    if half_life_days <= 0 or days_since_last <= 0:
        return score_at_last_interaction
    lambda_decay = math.log(2) / half_life_days
    return score_at_last_interaction * math.exp(-lambda_decay * days_since_last)


def determine_state(
    days_since_last: float,
    expected_cadence: float,
    has_explicit_end: bool = False,
    previous_state: str | None = None,
    recent_interaction_count: int = 0,
    reactivation_window_days: int = 30,
    reactivation_min_interactions: int = 3,
) -> tuple[str, bool]:
    ""













    config = load_decay_config()
    thresholds = config.get("state_thresholds", {})
    active_mult = thresholds.get("active_max_gap_multiplier", 2.0)
    cooling_mult = thresholds.get("cooling_max_gap_multiplier", 5.0)


    if has_explicit_end:

        if (
            previous_state == STATE_ENDED
            and recent_interaction_count >= reactivation_min_interactions
        ):
            return STATE_ACTIVE, True
        return STATE_ENDED, False


    if previous_state in (STATE_DORMANT, STATE_ENDED):
        if recent_interaction_count >= reactivation_min_interactions:
            return STATE_ACTIVE, True


    if expected_cadence == float("inf"):
        if days_since_last > 90:
            return STATE_DORMANT, False
        if days_since_last > 30:
            return STATE_COOLING, False
        return STATE_ACTIVE, False


    gap_ratio = days_since_last / expected_cadence if expected_cadence > 0 else float("inf")

    if gap_ratio <= active_mult:
        return STATE_ACTIVE, False
    if gap_ratio <= cooling_mult:
        return STATE_COOLING, False
    return STATE_DORMANT, False


def compute_relationship_decay(
    score_at_last_interaction: float,
    last_interaction_date: datetime,
    now: datetime,
    relationship_type: str = "default",
    interaction_dates: list[datetime] | None = None,
    has_explicit_end: bool = False,
    previous_state: str | None = None,
    recent_interaction_count: int = 0,
) -> dict:
    ""














    config = load_decay_config()

    days_since_last = max(0.0, (now - last_interaction_date).total_seconds() / 86400.0)
    half_life = get_half_life(relationship_type)
    decayed_score = compute_decay(score_at_last_interaction, days_since_last, half_life)


    cadence = float("inf")
    if interaction_dates and len(interaction_dates) >= 2:
        cadence = compute_expected_cadence(interaction_dates)


    state, is_reactivation = determine_state(
        days_since_last=days_since_last,
        expected_cadence=cadence,
        has_explicit_end=has_explicit_end,
        previous_state=previous_state,
        recent_interaction_count=recent_interaction_count,
        reactivation_window_days=config.get("reactivation_window_days", 30),
        reactivation_min_interactions=config.get("reactivation_min_interactions", 3),
    )

    return {
        "decayed_score": round(decayed_score, 4),
        "state": state,
        "is_reactivation": is_reactivation,
        "days_since_last": round(days_since_last, 1),
        "half_life_days": half_life,
        "expected_cadence_days": round(cadence, 1) if cadence != float("inf") else None,
        "relationship_type": relationship_type,
    }
