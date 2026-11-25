#!/usr/bin/env python3
""
















from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_types import Evidence, EvidenceDirection, EvidenceSource
    from tools.plaud.pl_voice_match import (
        VOICE_MAX_LOGODDS,
        VOICE_MIN_COSINE,
        match_speakers,
    )
    from tools.plaud.pl_voice_seed_wa import load_clean_registry
except ImportError:  # pragma: no cover
    from pl_types import Evidence, EvidenceDirection, EvidenceSource  # type: ignore[no-redef]
    from pl_voice_match import (  # type: ignore[no-redef]
        VOICE_MAX_LOGODDS,
        VOICE_MIN_COSINE,
        match_speakers,
    )
    from pl_voice_seed_wa import load_clean_registry  # type: ignore[no-redef]


def clean_registry_as_matchlist(registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ""
    reg = registry if registry is not None else load_clean_registry()
    out: list[dict[str, Any]] = []
    for e in reg.get("entries", []):
        vec = e.get("vec")
        if isinstance(vec, list) and vec:
            out.append({"name": e["name"], "entity_id": e.get("entity_id"), "vec": vec})
    return out


def emit_trusted_voice_evidence(
    speaker_matches: dict[str, list[dict[str, Any]]],
) -> dict[str, list[Evidence]]:
    ""


    out: dict[str, list[Evidence]] = {}
    for spk, matches in speaker_matches.items():
        evs: list[Evidence] = []
        for m in matches:
            score = m["score"]
            frac = max(0.0, (score - VOICE_MIN_COSINE) / max(1e-6, 1.0 - VOICE_MIN_COSINE))
            weight = round(frac * VOICE_MAX_LOGODDS, 4)
            evs.append(
                Evidence(
                    source=EvidenceSource.VOICE_EMBEDDING,
                    claim=f"e' {m['name']}",
                    weight=weight,
                    direction=EvidenceDirection.SUPPORT,
                    entity_id=m.get("entity_id"),
                    quote=f"voce (registro pulito) simile a {m['name']} (coseno {score:.2f})",
                    meta={
                        "signal": "voice_match_clean",
                        "cosine": round(score, 4),
                        "voice_name": m["name"],
                        "confident": bool(m.get("confident")),
                        "trusted": True,
                    },
                )
            )
        if evs:
            out[spk] = evs
    return out


def match_against_clean(
    speaker_embeddings: dict[str, list[float]],
    *,
    registry: dict[str, Any] | None = None,
    min_cosine: float = VOICE_MIN_COSINE,
) -> dict[str, list[Evidence]]:
    ""



    matchlist = clean_registry_as_matchlist(registry)
    if not matchlist:
        return {}
    matches = match_speakers(speaker_embeddings, matchlist, min_cosine=min_cosine)
    return emit_trusted_voice_evidence(matches)


__all__ = [
    "clean_registry_as_matchlist",
    "emit_trusted_voice_evidence",
    "match_against_clean",
]
