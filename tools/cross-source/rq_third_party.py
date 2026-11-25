""












from __future__ import annotations

import logging
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import OWN_EMAILS  # noqa: E402

log = logging.getLogger("rq.third_party")


SIGNAL_WEIGHTS = {
    "same_team": 0.95,
    "same_company": 0.80,
    "co_meeting": 0.70,
    "shared_threads": 0.60,
    "cc_pattern": 0.50,
}


SIGNAL_MIN_COUNT = {
    "same_team": 1,
    "same_company": 1,
    "co_meeting": 3,
    "shared_threads": 3,
    "cc_pattern": 2,
}


# Your own addresses, from sbk.config.json "own_emails".
OWNER_EMAILS = {e.strip().lower() for e in OWN_EMAILS}


def _normalize_email(email: str) -> str:
    ""
    return email.lower().strip()


def _is_owner_email(email: str) -> bool:
    ""
    return _normalize_email(email) in OWNER_EMAILS


def _pair_key(a: str, b: str) -> tuple[str, str]:
    ""
    na, nb = _normalize_email(a), _normalize_email(b)
    return (na, nb) if na <= nb else (nb, na)





def build_meeting_pairs(
    calendar_events: list[dict],
) -> dict[tuple[str, str], int]:
    ""








    pair_counts: dict[tuple[str, str], int] = defaultdict(int)

    for event in calendar_events:
        attendees_str = event.get("attendees", "")
        if not attendees_str:
            continue

        attendees = [
            _normalize_email(e)
            for e in str(attendees_str).split(",")
            if e.strip() and not _is_owner_email(e.strip()) and "@" in e
        ]


        for a, b in combinations(set(attendees), 2):
            pair_counts[_pair_key(a, b)] += 1

    return dict(pair_counts)


def build_email_thread_pairs(
    emails: list[dict],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    ""








    thread_participants: dict[str, set[str]] = defaultdict(set)
    cc_pair_counts: dict[tuple[str, str], int] = defaultdict(int)

    for msg in emails:
        thread_id = msg.get("thread_id", "")
        from_addr = _normalize_email(str(msg.get("from_addr", "")))
        to_addr = _normalize_email(str(msg.get("to_addr", "")))
        cc_str = str(msg.get("cc", "") or "")


        if thread_id:
            for addr in [from_addr, to_addr]:
                if addr and "@" in addr and not _is_owner_email(addr):
                    thread_participants[thread_id].add(addr)


        if cc_str:
            cc_addrs = [
                _normalize_email(e) for e in cc_str.split(",") if e.strip() and "@" in e.strip()
            ]
            non_owner = [a for a in cc_addrs if not _is_owner_email(a)]
            sender = from_addr if not _is_owner_email(from_addr) else None


            if sender:
                for cc_addr in non_owner:
                    if cc_addr != sender:
                        cc_pair_counts[_pair_key(sender, cc_addr)] += 1


            for a, b in combinations(set(non_owner), 2):
                cc_pair_counts[_pair_key(a, b)] += 1


    thread_pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for participants in thread_participants.values():
        if len(participants) < 2:
            continue
        for a, b in combinations(participants, 2):
            thread_pair_counts[_pair_key(a, b)] += 1

    return dict(thread_pair_counts), dict(cc_pair_counts)


def build_company_pairs(
    personio_index: dict[str, dict],
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    ""









    company_groups: dict[str, list[str]] = defaultdict(list)
    team_groups: dict[str, list[str]] = defaultdict(list)

    for email, emp in personio_index.items():
        if _is_owner_email(email):
            continue
        status = str(emp.get("status", "")).lower()
        if status in ("inactive", "terminated", "offboarded"):
            continue

        company = str(emp.get("subcompany", "") or emp.get("company", "") or "").strip().lower()
        team = str(emp.get("team", "")).strip().lower()

        if company:
            company_groups[company].append(_normalize_email(email))
        if team:
            team_groups[team].append(_normalize_email(email))

    company_pairs: dict[tuple[str, str], str] = {}
    for company, members in company_groups.items():
        for a, b in combinations(set(members), 2):
            company_pairs[_pair_key(a, b)] = company

    team_pairs: dict[tuple[str, str], str] = {}
    for team, members in team_groups.items():
        for a, b in combinations(set(members), 2):
            team_pairs[_pair_key(a, b)] = team

    return company_pairs, team_pairs





def aggregate_signals(
    meeting_pairs: dict[tuple[str, str], int],
    thread_pairs: dict[tuple[str, str], int],
    cc_pairs: dict[tuple[str, str], int],
    company_pairs: dict[tuple[str, str], str],
    team_pairs: dict[tuple[str, str], str],
) -> dict[tuple[str, str], list[dict]]:
    ""




    all_pairs: set[tuple[str, str]] = set()
    all_pairs.update(meeting_pairs.keys())
    all_pairs.update(thread_pairs.keys())
    all_pairs.update(cc_pairs.keys())
    all_pairs.update(company_pairs.keys())
    all_pairs.update(team_pairs.keys())

    result: dict[tuple[str, str], list[dict]] = {}

    for pair in all_pairs:
        signals = []

        if pair in team_pairs:
            signals.append(
                {
                    "type": "same_team",
                    "count": 1,
                    "confidence": SIGNAL_WEIGHTS["same_team"],
                    "detail": team_pairs[pair],
                }
            )

        if pair in company_pairs and pair not in team_pairs:
            signals.append(
                {
                    "type": "same_company",
                    "count": 1,
                    "confidence": SIGNAL_WEIGHTS["same_company"],
                    "detail": company_pairs[pair],
                }
            )

        meeting_count = meeting_pairs.get(pair, 0)
        if meeting_count >= SIGNAL_MIN_COUNT["co_meeting"]:
            signals.append(
                {
                    "type": "co_meeting",
                    "count": meeting_count,
                    "confidence": SIGNAL_WEIGHTS["co_meeting"],
                }
            )

        thread_count = thread_pairs.get(pair, 0)
        if thread_count >= SIGNAL_MIN_COUNT["shared_threads"]:
            signals.append(
                {
                    "type": "shared_threads",
                    "count": thread_count,
                    "confidence": SIGNAL_WEIGHTS["shared_threads"],
                }
            )

        cc_count = cc_pairs.get(pair, 0)
        if cc_count >= SIGNAL_MIN_COUNT["cc_pattern"]:
            signals.append(
                {
                    "type": "cc_pattern",
                    "count": cc_count,
                    "confidence": SIGNAL_WEIGHTS["cc_pattern"],
                }
            )

        if signals:
            result[pair] = signals

    return result


def compute_third_party_strength(signals: list[dict]) -> float:
    ""









    if not signals:
        return 0.0

    total_weight = sum(s["confidence"] for s in signals)
    weighted_sum = sum(s["confidence"] ** 2 for s in signals)
    base = weighted_sum / total_weight if total_weight > 0 else 0.0


    bonus = min(0.3, (len(signals) - 1) * 0.10)
    return min(1.0, base + bonus)





def find_warm_intros(
    target_email: str,
    owner_relationships: dict[str, float],
    third_party_strengths: dict[tuple[str, str], float],
    third_party_signals: dict[tuple[str, str], list[dict]],
    min_bridge_score: float = 3.0,
    min_target_strength: float = 0.3,
    max_paths: int = 5,
) -> list[dict]:
    ""













    target_norm = _normalize_email(target_email)
    paths = []

    for bridge_email, owner_score in owner_relationships.items():
        if owner_score < min_bridge_score:
            continue

        bridge_norm = _normalize_email(bridge_email)
        if bridge_norm == target_norm:
            continue

        pair = _pair_key(bridge_norm, target_norm)
        strength = third_party_strengths.get(pair, 0.0)
        if strength < min_target_strength:
            continue

        signals = third_party_signals.get(pair, [])
        path_strength = min(owner_score / 10.0, strength)

        paths.append(
            {
                "bridge": bridge_email,
                "owner_to_bridge_score": owner_score,
                "bridge_to_target_strength": round(strength, 3),
                "path_strength": round(path_strength, 3),
                "evidence": [s["type"] for s in signals],
            }
        )

    paths.sort(key=lambda p: p["path_strength"], reverse=True)
    return paths[:max_paths]
