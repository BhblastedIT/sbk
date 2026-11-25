""









from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

log = logging.getLogger("ti.recurring")


MIN_SERIES_LENGTH = 3


TITLE_SIMILARITY = 0.60


@dataclass
class RecurringInstance:
    ""

    meeting_id: str = ""
    date: str = ""
    title: str = ""
    topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass
class RecurringSeries:
    ""

    series_id: str = ""
    canonical_title: str = ""
    frequency: str = ""
    instance_count: int = 0
    instances: list[RecurringInstance] = field(default_factory=list)

    persistent_topics: list[str] = field(default_factory=list)
    new_topics: list[str] = field(default_factory=list)
    stuck_blockers: list[str] = field(default_factory=list)


def _normalize_title(title: str) -> str:
    ""
    import re

    t = title.lower().strip()
    t = re.sub(r"\d{1,2}[/.\-]\d{1,2}([/.\-]\d{2,4})?", "", t)
    t = re.sub(r"#\d+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def detect_recurring_series(
    meetings: list[dict],
    min_length: int = MIN_SERIES_LENGTH,
) -> list[RecurringSeries]:
    ""











    if not meetings:
        return []


    groups: list[list[dict]] = []
    used = set()

    sorted_meetings = sorted(meetings, key=lambda m: m.get("date", ""))

    for i, meeting in enumerate(sorted_meetings):
        if i in used:
            continue
        title_i = _normalize_title(meeting.get("title", ""))
        if not title_i:
            continue

        group = [meeting]
        used.add(i)

        for j in range(i + 1, len(sorted_meetings)):
            if j in used:
                continue
            title_j = _normalize_title(sorted_meetings[j].get("title", ""))
            if not title_j:
                continue
            if SequenceMatcher(None, title_i, title_j).ratio() >= TITLE_SIMILARITY:
                group.append(sorted_meetings[j])
                used.add(j)

        if len(group) >= min_length:
            groups.append(group)


    series_list = []
    for idx, group in enumerate(groups):
        instances = []
        for m in group:
            instances.append(
                RecurringInstance(
                    meeting_id=m.get("meeting_id", ""),
                    date=m.get("date", ""),
                    title=m.get("title", ""),
                    topics=m.get("topics", []),
                    decisions=m.get("decisions", []),
                    action_items=m.get("action_items", []),
                )
            )


        frequency = _detect_frequency(group)

        series = RecurringSeries(
            series_id=f"series-{idx:03d}",
            canonical_title=group[0].get("title", ""),
            frequency=frequency,
            instance_count=len(instances),
            instances=instances,
        )


        _track_evolution(series)

        series_list.append(series)

    series_list.sort(key=lambda s: s.instance_count, reverse=True)
    return series_list


def _detect_frequency(meetings: list[dict]) -> str:
    ""
    dates = sorted(m.get("date", "")[:10] for m in meetings if m.get("date"))
    if len(dates) < 2:
        return "irregular"

    from datetime import datetime

    try:
        parsed = [datetime.strptime(d, "%Y-%m-%d") for d in dates if len(d) >= 10]
    except ValueError:
        return "irregular"

    if len(parsed) < 2:
        return "irregular"

    gaps = [(parsed[i + 1] - parsed[i]).days for i in range(len(parsed) - 1)]
    avg_gap = sum(gaps) / len(gaps)

    if 5 <= avg_gap <= 9:
        return "weekly"
    if 12 <= avg_gap <= 16:
        return "biweekly"
    if 25 <= avg_gap <= 35:
        return "monthly"
    return "irregular"


def _track_evolution(series: RecurringSeries) -> None:
    ""
    if len(series.instances) < 2:
        return


    all_topics: list[list[str]] = [i.topics for i in series.instances]
    all_decisions: list[list[str]] = [i.decisions for i in series.instances]


    topic_counts: Counter[str] = Counter()
    for topics in all_topics:
        for t in topics:
            topic_counts[t.lower().strip()] += 1

    threshold = len(series.instances) * 0.5
    series.persistent_topics = [t for t, c in topic_counts.items() if c >= threshold]


    if all_topics and all_topics[-1]:
        prev_topics = set()
        for topics in all_topics[:-1]:
            prev_topics.update(t.lower().strip() for t in topics)
        series.new_topics = [t for t in all_topics[-1] if t.lower().strip() not in prev_topics]


    decision_counts: Counter[str] = Counter()
    for decisions in all_decisions:
        for d in decisions:
            decision_counts[d.lower().strip()] += 1
    series.stuck_blockers = [d for d, c in decision_counts.items() if c >= 3]
