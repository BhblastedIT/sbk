""
























from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any






class EvidenceSource(str, Enum):
    ""



    PLAUD_LABEL = "plaud_label"
    TRANSCRIPT_CONTEXT = "transcript_context"
    CALENDAR = "calendar"
    KNOWLEDGE_BASE = "knowledge_base"
    GRAPH_COOCCURRENCE = "graph_cooccurrence"
    VOICE_EMBEDDING = "voice_embedding"
    MANUAL_OVERRIDE = "manual_override"


class EvidenceDirection(str, Enum):
    ""


    SUPPORT = "support"
    CONTRADICT = "contradict"


class Lane(str, Enum):
    ""

    AUTO = "AUTO"
    CONFIRM = "CONFERMA"
    CONTEXT = "CONTESTO"


class Provenance(str, Enum):
    ""

    PLAUD_NATIVE = "PLAUD_NATIVE"
    MACHINE_WRITTEN = "MACHINE_WRITTEN"
    OWNER_REVIEWED = "OWNER_REVIEWED"
    UNKNOWN = "UNKNOWN"







@dataclass(frozen=True)
class WriteLimits:
    ""



    max_writes_per_day: int = 40
    min_seconds_between_writes: float = 20.0
    stop_after_consecutive_errors: int = 3
    stop_hours_on_rate_limit: int = 24
    serialize_batches: bool = True


WRITE_LIMITS = WriteLimits()







@dataclass
class Evidence:
    ""





    source: EvidenceSource
    claim: str
    weight: float
    direction: EvidenceDirection = EvidenceDirection.SUPPORT
    entity_id: str | None = None
    quote: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "claim": self.claim,
            "weight": self.weight,
            "direction": self.direction.value,
            "entity_id": self.entity_id,
            "quote": self.quote,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Evidence:
        return cls(
            source=EvidenceSource(d["source"]),
            claim=d.get("claim", ""),
            weight=float(d.get("weight", 0.0)),
            direction=EvidenceDirection(d.get("direction", "support")),
            entity_id=d.get("entity_id"),
            quote=d.get("quote", ""),
            meta=d.get("meta", {}) or {},
        )


@dataclass
class Candidate:
    ""

    name: str
    entity_id: str | None = None
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def sources(self) -> set[EvidenceSource]:
        return {e.source for e in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entity_id": self.entity_id,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Candidate:
        return cls(
            name=d["name"],
            entity_id=d.get("entity_id"),
            confidence=float(d.get("confidence", 0.0)),
            evidence=[Evidence.from_dict(e) for e in d.get("evidence", [])],
        )


@dataclass
class SpeakerResolution:
    ""





    speaker_id: str
    candidates: list[Candidate] = field(default_factory=list)
    posterior: float = 0.0
    contradiction_score: float = 0.0
    plaud_label: str | None = None
    plaud_disagree: bool = False
    lane: Lane = Lane.CONTEXT
    provenance: Provenance = Provenance.UNKNOWN




    proposed_name: str | None = None
    corroborated: bool = False

    @property
    def best(self) -> Candidate | None:
        return max(self.candidates, key=lambda c: c.confidence, default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "candidates": [c.to_dict() for c in self.candidates],
            "posterior": self.posterior,
            "contradiction_score": self.contradiction_score,
            "plaud_label": self.plaud_label,
            "plaud_disagree": self.plaud_disagree,
            "lane": self.lane.value,
            "provenance": self.provenance.value,
            "proposed_name": self.proposed_name,
            "corroborated": self.corroborated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SpeakerResolution:
        return cls(
            speaker_id=d["speaker_id"],
            candidates=[Candidate.from_dict(c) for c in d.get("candidates", [])],
            posterior=float(d.get("posterior", 0.0)),
            contradiction_score=float(d.get("contradiction_score", 0.0)),
            plaud_label=d.get("plaud_label"),
            plaud_disagree=bool(d.get("plaud_disagree", False)),
            lane=Lane(d.get("lane", "CONTESTO")),
            provenance=Provenance(d.get("provenance", "UNKNOWN")),
            proposed_name=d.get("proposed_name"),
            corroborated=bool(d.get("corroborated", False)),
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        ""

        b = self.best
        return {
            "identity": b.name if b else "",
            "confidence": self.posterior,
            "source": (b.evidence[0].source.value if b and b.evidence else "unknown"),
        }
