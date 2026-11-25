""











from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CoachingNote:
    ""

    meeting_id: str = ""
    category: str = (
        ""
    )
    severity: str = "info"
    message: str = ""
    data: dict = field(default_factory=dict)


def generate_coaching_notes(
    meeting_id: str = "",
    owner_speaking_pct: float = 0.0,
    balance_score: float = 1.0,
    speakers: list[dict] | None = None,
    stuck_blockers: list[str] | None = None,
) -> list[CoachingNote]:
    ""











    notes = []
    speaker_list = speakers or []


    if owner_speaking_pct > 0.50:
        notes.append(
            CoachingNote(
                meeting_id=meeting_id,
                category="dominance",
                severity="warning",
                message=f"Speaking {owner_speaking_pct:.0%} of the time. Consider asking more questions and listening.",
                data={"owner_pct": owner_speaking_pct},
            )
        )


    if len(speaker_list) >= 3:
        for s in speaker_list:
            name = s.get("speaker", "")
            pct = s.get("speaking_pct", 0)
            if pct < 0.10 and not s.get("is_owner", False):
                notes.append(
                    CoachingNote(
                        meeting_id=meeting_id,
                        category="silent_attendee",
                        severity="action",
                        message=f"{name} spoke only {pct:.0%}. Consider a follow-up 1:1.",
                        data={"speaker": name, "pct": pct},
                    )
                )


    if stuck_blockers:
        for blocker in stuck_blockers[:3]:
            notes.append(
                CoachingNote(
                    meeting_id=meeting_id,
                    category="stuck_blocker",
                    severity="warning",
                    message=f'Recurring topic (3+ meetings): "{blocker[:80]}"',
                    data={"blocker": blocker},
                )
            )


    if balance_score >= 0.7 and len(speaker_list) >= 2:
        notes.append(
            CoachingNote(
                meeting_id=meeting_id,
                category="balance",
                severity="info",
                message=f"Good conversation balance ({balance_score:.0%}). Well-moderated discussion.",
                data={"balance": balance_score},
            )
        )


    owner_questions = 0.0
    for s in speaker_list:
        if s.get("is_owner"):
            owner_questions = s.get("question_ratio", 0)
            break
    if owner_questions < 0.1 and owner_speaking_pct > 0.30 and len(speaker_list) >= 2:
        notes.append(
            CoachingNote(
                meeting_id=meeting_id,
                category="question_ratio",
                severity="info",
                message="Low question ratio. Try opening with questions before stating positions.",
                data={"question_ratio": owner_questions},
            )
        )

    return notes
