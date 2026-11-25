""











from __future__ import annotations

import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from dataclasses import dataclass, field

from sbk_config import is_owner_speaker  # noqa: E402


_QUESTION_RE = re.compile(
    r"\?|"
    r"\bcome\b.*\?|\bquando\b|\bperch[eé]\b|\bdove\b|\bchi\b|\bquanto\b|"
    r"\bhow\b|\bwhen\b|\bwhy\b|\bwhere\b|\bwho\b|\bwhat\b|\bwhich\b",
    re.IGNORECASE,
)


@dataclass
class SpeakerEngagement:
    ""

    speaker: str
    word_count: int = 0
    speaking_pct: float = 0.0
    turn_count: int = 0
    question_count: int = 0
    question_ratio: float = 0.0
    avg_turn_length: float = 0.0
    is_owner: bool = False


@dataclass
class MeetingEngagement:
    ""

    meeting_id: str = ""
    total_words: int = 0
    total_turns: int = 0
    speaker_count: int = 0
    balance_score: float = 0.0
    owner_speaking_pct: float = 0.0
    speakers: list[SpeakerEngagement] = field(default_factory=list)


def _is_question(text: str) -> bool:
    ""
    return bool(_QUESTION_RE.search(text))


def _is_owner(speaker: str) -> bool:
    ""
    return is_owner_speaker(speaker)


def compute_engagement(
    segments: list[dict],
    meeting_id: str = "",
    text_key: str = "text",
    speaker_key: str = "speaker",
) -> MeetingEngagement:
    ""










    if not segments:
        return MeetingEngagement(meeting_id=meeting_id)


    speaker_data: dict[str, dict] = {}

    for seg in segments:
        speaker = str(seg.get(speaker_key, "")).strip()
        text = str(seg.get(text_key, seg.get("transcript", seg.get("content", "")))).strip()

        if not speaker or not text:
            continue

        if speaker not in speaker_data:
            speaker_data[speaker] = {"words": 0, "turns": 0, "questions": 0}

        words = len(text.split())
        speaker_data[speaker]["words"] += words
        speaker_data[speaker]["turns"] += 1
        if _is_question(text):
            speaker_data[speaker]["questions"] += 1

    if not speaker_data:
        return MeetingEngagement(meeting_id=meeting_id)

    total_words = sum(d["words"] for d in speaker_data.values())
    total_turns = sum(d["turns"] for d in speaker_data.values())


    speakers = []
    owner_pct = 0.0

    for speaker, data in sorted(speaker_data.items(), key=lambda x: x[1]["words"], reverse=True):
        pct = data["words"] / total_words if total_words > 0 else 0.0
        q_ratio = data["questions"] / data["turns"] if data["turns"] > 0 else 0.0
        avg_len = data["words"] / data["turns"] if data["turns"] > 0 else 0.0
        is_owner = _is_owner(speaker)

        if is_owner:
            owner_pct = pct

        speakers.append(
            SpeakerEngagement(
                speaker=speaker,
                word_count=data["words"],
                speaking_pct=round(pct, 4),
                turn_count=data["turns"],
                question_count=data["questions"],
                question_ratio=round(q_ratio, 4),
                avg_turn_length=round(avg_len, 1),
                is_owner=is_owner,
            )
        )


    n = len(speakers)
    if n <= 1:
        balance = 0.0
    else:
        ideal_pct = 1.0 / n
        deviations = [abs(s.speaking_pct - ideal_pct) for s in speakers]
        max_deviation = 1.0 - ideal_pct
        avg_deviation = sum(deviations) / n
        balance = (
            round(max(0.0, 1.0 - avg_deviation / max_deviation), 4) if max_deviation > 0 else 1.0
        )

    return MeetingEngagement(
        meeting_id=meeting_id,
        total_words=total_words,
        total_turns=total_turns,
        speaker_count=n,
        balance_score=balance,
        owner_speaking_pct=round(owner_pct, 4),
        speakers=speakers,
    )


def format_recap_email(
    summary: str,
    decisions: list[str],
    follow_ups: list[dict],
    meeting_title: str = "",
    meeting_date: str = "",
) -> str:
    ""



    lines = []
    if meeting_title:
        lines.append(f"**{meeting_title}** — {meeting_date}")
        lines.append("")

    if summary:
        lines.append(summary)
        lines.append("")

    if decisions:
        lines.append("**Decisioni:**")
        for d in decisions:
            lines.append(f"- {d}")
        lines.append("")

    if follow_ups:
        lines.append("**Next steps:**")
        for fu in follow_ups:
            task = fu.get("task", "")
            owner = fu.get("owner", "")
            deadline = fu.get("deadline", "")
            line = f"- {task}"
            if owner:
                line += f" (@{owner})"
            if deadline:
                line += f" — entro {deadline}"
            lines.append(line)

    return "\n".join(lines)
