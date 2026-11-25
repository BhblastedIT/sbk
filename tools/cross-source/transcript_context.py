""












from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import DATA_ROOT

log = logging.getLogger("ti.context")


@dataclass
class ParticipantContext:
    ""

    name: str
    person_id: str = ""
    role: str = ""
    company: str = ""
    relationship_type: str = ""
    relationship_score: float = 0.0
    key_facts: list[str] = field(default_factory=list)
    last_interaction_date: str = ""


@dataclass
class MeetingContext:
    ""

    meeting_id: str = ""
    meeting_date: str = ""
    meeting_title: str = ""
    meeting_type: str = ""

    participants: list[ParticipantContext] = field(default_factory=list)
    email_subjects: list[str] = field(default_factory=list)
    slack_snippets: list[str] = field(default_factory=list)
    previous_meetings: list[str] = field(default_factory=list)
    calendar_description: str = ""
    recurring_context: str = ""





def _load_contacts_merged() -> pd.DataFrame:
    ""
    path = DATA_ROOT / "enriched" / "contacts-merged.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(
        path,
        columns=[
            "person_id",
            "name",
            "email",
            "organization",
            "domain",
        ],
    )


def _load_rq_scores() -> dict[str, float]:
    ""
    path = DATA_ROOT / "rq" / "composite-scores-v2.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path, columns=["person", "score_v2"])
    return dict(zip(df["person"], df["score_v2"]))


def _load_knowledge_facts(person_id: str, max_facts: int = 3) -> list[str]:
    ""
    person_dir = DATA_ROOT / "knowledge" / "entities" / "person"

    for pattern in [f"{person_id}.json", f"person_{person_id.replace('p_', '')}.json"]:
        path = person_dir / pattern
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                facts = data.get("facts", [])

                sorted_facts = sorted(
                    facts,
                    key=lambda f: (f.get("confidence", 0), f.get("created_at", "")),
                    reverse=True,
                )
                result = []
                for f in sorted_facts[:max_facts]:
                    attr = f.get("attribute", "")
                    val = f.get("value", "")
                    if attr and val:
                        result.append(f"{attr}: {val}")
                return result
            except (ValueError, OSError):
                pass
    return []


def enrich_participants(
    speaker_names: list[str],
    attendee_emails: list[str] | None = None,
) -> list[ParticipantContext]:
    ""




    contacts = _load_contacts_merged()
    scores = _load_rq_scores()

    participants = []
    seen_pids: set[str] = set()


    name_to_pid: dict[str, str] = {}
    email_to_pid: dict[str, str] = {}
    pid_to_info: dict[str, dict] = {}

    if not contacts.empty:
        for _, row in contacts.iterrows():
            pid = str(row.get("person_id", ""))
            name = str(row.get("name", ""))
            email = str(row.get("email", "")).lower()
            org = str(row.get("organization", "")) if pd.notna(row.get("organization")) else ""

            if pid:
                pid_to_info[pid] = {"name": name, "email": email, "organization": org}
                if name:
                    name_to_pid[name.lower()] = pid
                if email and "@" in email:
                    email_to_pid[email] = pid


    for speaker in speaker_names:
        if not speaker or not speaker.strip():
            continue
        speaker_lower = speaker.strip().lower()
        pid = name_to_pid.get(speaker_lower, "")
        info = pid_to_info.get(pid, {})

        if pid and pid in seen_pids:
            continue
        seen_pids.add(pid or speaker)

        key_facts = _load_knowledge_facts(pid) if pid else []
        score = scores.get(pid, 0.0)

        participants.append(
            ParticipantContext(
                name=speaker.strip(),
                person_id=pid,
                role="",
                company=info.get("organization", ""),
                relationship_score=score,
                key_facts=key_facts,
            )
        )


    if attendee_emails:
        for email in attendee_emails:
            email_lower = email.strip().lower()
            pid = email_to_pid.get(email_lower, "")
            if pid and pid in seen_pids:
                continue
            seen_pids.add(pid or email_lower)
            info = pid_to_info.get(pid, {})
            key_facts = _load_knowledge_facts(pid) if pid else []
            score = scores.get(pid, 0.0)

            participants.append(
                ParticipantContext(
                    name=info.get("name", email),
                    person_id=pid,
                    company=info.get("organization", ""),
                    relationship_score=score,
                    key_facts=key_facts,
                )
            )

    return participants





def detect_meeting_type(
    participant_count: int,
    title: str = "",
    attendee_domains: list[str] | None = None,
) -> str:
    ""



    if participant_count <= 2:
        return "1:1"


    title_lower = title.lower()
    if any(kw in title_lower for kw in ["1:1", "one on one", "1-on-1"]):
        return "1:1"
    if any(kw in title_lower for kw in ["team", "standup", "sprint", "retro", "all hands"]):
        return "team"
    if any(kw in title_lower for kw in ["intro", "partner", "investor", "client", "external"]):
        return "external"

    if participant_count <= 5:
        return "small_group"


    from sbk_config import INTERNAL_DOMAINS

    internal_lower = {d.lower() for d in INTERNAL_DOMAINS}
    if attendee_domains:
        external = [d for d in attendee_domains if d.lower() not in internal_lower]
        if not external:
            return "team"
        return "external"

    return "unknown"





def build_meeting_context(
    meeting_id: str = "",
    meeting_date: str = "",
    meeting_title: str = "",
    speaker_names: list[str] | None = None,
    attendee_emails: list[str] | None = None,
    calendar_description: str = "",
) -> MeetingContext:
    ""



    speakers = speaker_names or []
    emails = attendee_emails or []


    participants = enrich_participants(speakers, emails)


    participant_count = len(participants) + 1
    attendee_domains = [e.split("@")[1] for e in emails if "@" in e]
    meeting_type = detect_meeting_type(participant_count, meeting_title, attendee_domains)

    return MeetingContext(
        meeting_id=meeting_id,
        meeting_date=meeting_date,
        meeting_title=meeting_title,
        meeting_type=meeting_type,
        participants=participants,
        calendar_description=calendar_description,
    )


def format_context_for_prompt(ctx: MeetingContext, max_chars: int = 1000) -> str:
    ""



    lines = []
    lines.append(f"Meeting type: {ctx.meeting_type}")

    if ctx.participants:
        lines.append("Participants:")
        for p in ctx.participants[:8]:
            parts = [f"  - {p.name}"]
            if p.company:
                parts.append(f"({p.company})")
            if p.relationship_score > 3.0:
                parts.append(f"[score {p.relationship_score:.1f}]")
            line = " ".join(parts)
            if p.key_facts:
                line += f"\n    Facts: {'; '.join(p.key_facts[:2])}"
            lines.append(line)

    if ctx.email_subjects:
        lines.append(f"Recent emails: {'; '.join(ctx.email_subjects[:3])}")

    if ctx.slack_snippets:
        lines.append(f"Recent Slack: {'; '.join(ctx.slack_snippets[:2])}")

    if ctx.previous_meetings:
        lines.append(f"Previous meetings: {'; '.join(ctx.previous_meetings[:3])}")

    if ctx.calendar_description:
        lines.append(f"Calendar notes: {ctx.calendar_description[:200]}")

    if ctx.recurring_context:
        lines.append(f"Recurring: {ctx.recurring_context}")

    text = "\n".join(lines)
    return text[:max_chars]
