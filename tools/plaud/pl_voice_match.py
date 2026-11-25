#!/usr/bin/env python3
""















from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from tools.plaud.pl_types import Evidence, EvidenceDirection, EvidenceSource
except ImportError:  # pragma: no cover
    from pl_types import Evidence, EvidenceDirection, EvidenceSource  # type: ignore[no-redef]


VOICE_MIN_COSINE: float = 0.82

VOICE_TOP_K: int = 4

VOICE_MAX_LOGODDS: float = 1.6



VOICE_CONFIDENT_COSINE: float = 0.90
VOICE_CONFIDENT_MARGIN: float = 0.06


VOICE_STRONG_COSINE: float = 0.95


def cosine(a: list[float], b: list[float]) -> float:
    ""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _is_plausible_person(name: str, entity_ids: list[str] | None) -> bool:
    ""

    n = (name or "").strip()
    if len(n) < 3:
        return False
    if entity_ids:
        return True

    return len(n.split()) >= 2 or len(n) >= 4


def build_clean_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    ""



    index_by_id = {}
    for m in registry.get("index", []):
        if m.get("speaker_id"):
            index_by_id[m["speaker_id"]] = m
    clean: list[dict[str, Any]] = []
    for sp in registry.get("speakers", []):
        vec = (sp.get("embeddings") or {}).get("auto")
        if not isinstance(vec, list) or not vec:
            continue
        name = sp.get("speaker_name") or ""
        meta = index_by_id.get(sp.get("speaker_id"), {})
        eids = meta.get("entity_ids") or []
        if not _is_plausible_person(name, eids):
            continue
        clean.append({"name": name, "entity_id": eids[0] if eids else None, "vec": vec})
    return clean


def match_speakers(
    file_embeddings: dict[str, list[float]],
    clean_registry: list[dict[str, Any]],
    min_cosine: float = VOICE_MIN_COSINE,
    top_k: int = VOICE_TOP_K,
) -> dict[str, list[dict[str, Any]]]:
    ""



    out: dict[str, list[dict[str, Any]]] = {}
    for spk, vec in file_embeddings.items():
        if not isinstance(vec, list) or not vec:
            continue




        best_by_person: dict[str, dict[str, Any]] = {}
        for rv in clean_registry:
            score = cosine(vec, rv["vec"])
            if score < min_cosine:
                continue
            key = rv["entity_id"] or (
                "name:" + " ".join(rv["name"].lower().replace(".", " ").split())
            )
            prev = best_by_person.get(key)
            if prev is None or score > prev["score"]:
                best_by_person[key] = {
                    "name": rv["name"],
                    "entity_id": rv["entity_id"],
                    "score": score,
                }
        ranked = sorted(best_by_person.values(), key=lambda m: m["score"], reverse=True)[:top_k]


        for j, m in enumerate(ranked):
            second = ranked[1]["score"] if len(ranked) > 1 else 0.0
            m["confident"] = j == 0 and (
                m["score"] >= VOICE_STRONG_COSINE
                or (
                    m["score"] >= VOICE_CONFIDENT_COSINE
                    and (m["score"] - second) >= VOICE_CONFIDENT_MARGIN
                )
            )
        if ranked:
            out[spk] = ranked
    return out


def emit_voice_evidence(
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
                    quote=f"voce simile a {m['name']} (coseno {score:.2f})",
                    meta={
                        "signal": "voice_match",
                        "cosine": round(score, 4),
                        "voice_name": m["name"],
                        "confident": bool(m.get("confident")),
                    },
                )
            )
        if evs:
            out[spk] = evs
    return out
