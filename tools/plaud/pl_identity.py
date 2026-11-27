#!/usr/bin/env python3
""


































from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_types import (
        Candidate,
        EvidenceDirection,
        EvidenceSource,
        SpeakerResolution,
    )
except ImportError:  # pragma: no cover
    from pl_types import (  # type: ignore[no-redef]
        Candidate,
        EvidenceDirection,
        EvidenceSource,
        SpeakerResolution,
    )


class IdentityState(str, Enum):
    VERIFIED = "VERIFIED"
    QUARANTINE = "QUARANTINE"
    ANONYMOUS = "ANONYMOUS"





_INDEPENDENT_STRONG = frozenset(
    {
        EvidenceSource.VOICE_EMBEDDING,
        EvidenceSource.CALENDAR,
        EvidenceSource.MANUAL_OVERRIDE,
    }
)



_DIRECT_TEXT_SIGNALS = frozenset({"addressed_name", "self_name", "addressing", "self_intro"})


@dataclass(frozen=True)
class IdentityVerdict:
    speaker_id: str
    state: IdentityState
    name: str | None
    confidence: float
    independent_sources: tuple[
        str, ...
    ]
    suspected_fused: bool
    reason: str
    kb_fact_grade: bool

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "state": self.state.value,
            "name": self.name,
            "confidence": round(self.confidence, 3),
            "independent_sources": list(self.independent_sources),
            "suspected_fused": self.suspected_fused,
            "reason": self.reason,
            "kb_fact_grade": self.kb_fact_grade,
        }


def _norm(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace(".", " ").split())


def _is_generic(label: str | None) -> bool:
    if not label or not label.strip():
        return True
    low = label.strip().lower()
    return low.startswith("speaker") or low.startswith("spk")


def _direct_text_support(cand: Candidate) -> bool:
    ""

    for ev in cand.evidence:
        if ev.source != EvidenceSource.TRANSCRIPT_CONTEXT:
            continue
        if ev.direction != EvidenceDirection.SUPPORT:
            continue
        sig = str(ev.meta.get("signal", "")).lower()
        if any(k in sig for k in _DIRECT_TEXT_SIGNALS) or any(
            k in ev.meta for k in _DIRECT_TEXT_SIGNALS
        ):
            return True
    return False


def _independent_sources_for(cand: Candidate, *, voice_registry_trusted: bool) -> set[str]:
    ""



    srcs: set[str] = set()
    for ev in cand.evidence:
        if ev.direction != EvidenceDirection.SUPPORT:
            continue
        if ev.source == EvidenceSource.VOICE_EMBEDDING:
            poisoned = bool(ev.meta.get("poisoned"))
            if (voice_registry_trusted or ev.meta.get("trusted")) and not poisoned:
                srcs.add("VOICE")
        elif ev.source in _INDEPENDENT_STRONG:
            srcs.add(ev.source.value.upper().split("_")[0])
    if _direct_text_support(cand):
        srcs.add("TEXT_DIRECT")
    return srcs


def _has_fusion_signature(res: SpeakerResolution) -> bool:
    ""


    support_names: set[str] = set()
    contradict_names: set[str] = set()
    for c in res.candidates:
        for ev in c.evidence:
            nm = _norm(ev.claim.replace("NON e'", "").replace("e'", "").strip()) or _norm(c.name)
            if ev.direction == EvidenceDirection.CONTRADICT:
                contradict_names.add(nm)
            elif ev.direction == EvidenceDirection.SUPPORT:
                support_names.add(nm)
    return len(support_names & contradict_names) > 0


def decide_identity(
    res: SpeakerResolution,
    *,
    voice_registry_trusted: bool = False,
) -> IdentityVerdict:
    ""



    sid = res.speaker_id
    label = res.plaud_label
    best = res.best
    fused = _has_fusion_signature(res)


    if fused:
        return IdentityVerdict(
            sid,
            IdentityState.QUARANTINE,
            name=(label if not _is_generic(label) else None),
            confidence=0.3,
            independent_sources=(),
            suspected_fused=True,
            kb_fact_grade=False,
            reason="merged-slot signature (SUPPORT+CONTRADICT on the same identity): no single attribution",
        )


    if best is not None:
        indep = _independent_sources_for(best, voice_registry_trusted=voice_registry_trusted)
        if indep:
            return IdentityVerdict(
                sid,
                IdentityState.VERIFIED,
                name=best.name,
                confidence=max(0.75, min(0.98, res.posterior)),
                independent_sources=tuple(sorted(indep)),
                suspected_fused=False,
                kb_fact_grade=True,
                reason=f"identity backed by an independent source: {', '.join(sorted(indep))}",
            )


    if not _is_generic(label):
        return IdentityVerdict(
            sid,
            IdentityState.QUARANTINE,
            name=label,
            confidence=min(0.55, res.posterior or 0.5),
            independent_sources=(),
            suspected_fused=False,
            kb_fact_grade=False,
            reason="name present only as a Plaud label, no independent source: not verified",
        )


    return IdentityVerdict(
        sid,
        IdentityState.ANONYMOUS,
        name=None,
        confidence=0.0,
        independent_sources=(),
        suspected_fused=False,
        kb_fact_grade=False,
        reason="no identity evidence: a distinct but anonymous speaker (Person X)",
    )


def decide_all(
    resolutions: dict[str, SpeakerResolution], *, voice_registry_trusted: bool = False
) -> dict[str, IdentityVerdict]:
    return {
        sid: decide_identity(r, voice_registry_trusted=voice_registry_trusted)
        for sid, r in resolutions.items()
    }
