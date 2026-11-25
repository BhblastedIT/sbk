""










from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

log = logging.getLogger("rq.severity")


@dataclass
class NegativeEvent:
    ""

    event_type: str
    category: str
    severity: int
    intentionality: str
    intentionality_mult: float
    source: str
    evidence: str
    date: str | None = None




SEVERITY_SCALE = {
    0: {"label": "Friction", "base_penalty": 0.05},
    1: {"label": "Tension", "base_penalty": 0.15},
    2: {"label": "Breach", "base_penalty": 0.30},
    3: {"label": "Betrayal", "base_penalty": 0.50},
    4: {"label": "Adversarial", "base_penalty": 0.75},
    5: {"label": "Hostile", "base_penalty": 0.90},
}



INTENTIONALITY_MULT = {
    "disruption": 0.7,
    "incongruence": 0.85,
    "negligence": 1.0,
    "reneging": 1.3,
    "premeditation": 1.5,
}









TERMINATION_MAP = {
    "employee-quit": ("departure_clean", 0, "negligence"),
    "quit": ("departure_clean", 0, "negligence"),
    "contract-expired": ("departure_clean", 0, "disruption"),
    "contract_expired": ("departure_clean", 0, "disruption"),
    "termination-agreement": ("departure_tense", 1, "incongruence"),
    "agreement": ("departure_tense", 1, "incongruence"),
    "settlement-agreement": ("departure_tense", 1, "incongruence"),
    "settlement_agreement": ("departure_tense", 1, "incongruence"),
    "fired": ("departure_hostile", 2, "negligence"),
    "irrevocable-suspension": ("departure_hostile", 2, "reneging"),
    "irrevocable_suspension": ("departure_hostile", 2, "reneging"),
    "court-settlement": ("departure_legal", 3, "reneging"),
    "court_settlement": ("departure_legal", 3, "reneging"),
}


_ESCALATION_KEYWORDS = {
    "theft",
    "stolen",
    "legal",
    "competitor",
    "fraud",
    "violation",
    "breach",
    "sabotage",
    "lawsuit",
}





def classify_departure(
    person_id: str,
    personio_enrichment: dict | None = None,
) -> NegativeEvent | None:
    ""









    if not personio_enrichment:
        return None

    term_type = personio_enrichment.get("termination_type")
    if not term_type:
        return None

    term_type = str(term_type).strip().lower()
    mapping = TERMINATION_MAP.get(term_type)

    if mapping is None:

        event_type, severity, intent = "departure_tense", 1, "negligence"
    else:
        event_type, severity, intent = mapping


    term_reason = personio_enrichment.get("termination_reason", "") or ""
    term_reason_lower = str(term_reason).lower()
    if any(kw in term_reason_lower for kw in _ESCALATION_KEYWORDS):
        severity = min(5, severity + 1)

    return NegativeEvent(
        event_type=event_type,
        category="departure",
        severity=severity,
        intentionality=intent,
        intentionality_mult=INTENTIONALITY_MULT[intent],
        source="personio",
        evidence=f"termination_type={term_type}"
        + (f", reason={term_reason}" if term_reason else ""),
        date=personio_enrichment.get("termination_date"),
    )


def classify_rejections(
    person_id: str,
    rejection_count: int,
) -> NegativeEvent | None:
    ""






    if rejection_count <= 0:
        return None




    import math

    severity = min(3, max(1, math.ceil(rejection_count / 3)))

    return NegativeEvent(
        event_type="rejection",
        category="professional",
        severity=severity,
        intentionality="negligence",
        intentionality_mult=1.0,
        source="relationship_facts",
        evidence=f"{rejection_count} REJECTION predicates",
    )


def detect_ghosting(
    person_id: str,
    one_sided_ratio: float = 0.0,
    ghosting_score: float = 0.0,
    **kwargs,
) -> NegativeEvent | None:
    ""









    has_ever_replied = kwargs.get("has_ever_replied", True)
    if not has_ever_replied:
        return None


    total_interactions = kwargs.get("total_interactions", 100)
    if total_interactions < 10:
        return None


    if one_sided_ratio > 0.9 or ghosting_score >= 0.3:
        severity = 2 if ghosting_score >= 0.7 or one_sided_ratio > 0.95 else 1
        return NegativeEvent(
            event_type="ghosting",
            category="communication",
            severity=severity,
            intentionality="negligence",
            intentionality_mult=1.0,
            source="interaction_patterns",
            evidence=f"one_sided_ratio={one_sided_ratio:.2f}, ghosting_score={ghosting_score:.2f}",
        )
    return None





def aggregate_severity(events: list[NegativeEvent]) -> tuple[int, float]:
    ""











    if not events:
        return (0, 0.0)

    severity_max = max(e.severity for e in events)
    same_level_count = sum(1 for e in events if e.severity == severity_max)
    compounding = min(1.0, (same_level_count - 1) * 0.5)
    effective_severity_raw = severity_max + compounding
    effective_severity = min(5, int(effective_severity_raw))


    base_low = SEVERITY_SCALE[effective_severity]["base_penalty"]
    if effective_severity_raw > effective_severity and effective_severity < 5:
        base_high = SEVERITY_SCALE[effective_severity + 1]["base_penalty"]
        frac = effective_severity_raw - effective_severity
        base_penalty = base_low + frac * (base_high - base_low)
    else:
        base_penalty = base_low

    intent_mult = max(e.intentionality_mult for e in events)
    penalty = min(1.0, base_penalty * intent_mult)

    return (effective_severity, round(penalty, 4))


def compute_penalty(severity: int, intentionality_mult: float = 1.0) -> float:
    ""








    severity = max(0, min(5, severity))
    base = SEVERITY_SCALE[severity]["base_penalty"]
    return min(1.0, round(base * intentionality_mult, 4))


def classify_all_events(
    person_id: str,
    rejection_count: int = 0,
    is_ex_employee: bool = False,
    personio_enrichment: dict | None = None,
    one_sided_ratio: float = 0.0,
    ghosting_score: float = 0.0,
    has_ever_replied: bool = True,
) -> list[NegativeEvent]:
    ""






    events: list[NegativeEvent] = []


    if is_ex_employee or (personio_enrichment and personio_enrichment.get("termination_type")):
        dep_event = classify_departure(person_id, personio_enrichment)
        if dep_event:
            events.append(dep_event)
        elif is_ex_employee:

            events.append(
                NegativeEvent(
                    event_type="departure_clean",
                    category="departure",
                    severity=0,
                    intentionality="negligence",
                    intentionality_mult=1.0,
                    source="personio",
                    evidence="is_ex_employee=True, no termination_type available",
                )
            )


    rej_event = classify_rejections(person_id, rejection_count)
    if rej_event:
        events.append(rej_event)


    ghost_event = detect_ghosting(
        person_id, one_sided_ratio, ghosting_score, has_ever_replied=has_ever_replied
    )
    if ghost_event:
        events.append(ghost_event)

    return events


def events_to_dicts(events: list[NegativeEvent]) -> list[dict]:
    ""
    return [asdict(e) for e in events]
