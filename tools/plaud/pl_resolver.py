#!/usr/bin/env python3
""























from __future__ import annotations

import json
import sys
from collections import defaultdict
from math import exp, log
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


try:
    from tools.plaud.pl_types import (
        Candidate,
        Evidence,
        EvidenceDirection,
        EvidenceSource,
        Lane,
        Provenance,
        SpeakerResolution,
    )
except ImportError:  # pragma: no cover
    from pl_types import (  # type: ignore[no-redef]
        Candidate,
        Evidence,
        EvidenceDirection,
        EvidenceSource,
        Lane,
        Provenance,
        SpeakerResolution,
    )


try:
    from tools.plaud.pl_context_emit import OWNER_CLAIM_NAME
    from tools.plaud.pl_context_emit import emit_all as context_emit_all
    from tools.plaud.pl_context_emit import group_by_speaker as context_group_by_speaker
except ImportError:  # pragma: no cover
    from pl_context_emit import OWNER_CLAIM_NAME  # type: ignore[no-redef]
    from pl_context_emit import emit_all as context_emit_all  # type: ignore[no-redef]
    from pl_context_emit import (
        group_by_speaker as context_group_by_speaker,  # type: ignore[no-redef]
    )








PLAUD_LABEL_WEIGHT: float = 0.55



PRIOR_LOG_ODDS: float = -0.50




_LANE_THRESHOLD_AUTO: float = 0.82
_LANE_THRESHOLD_CONFIRM: float = 0.50



_CONTRADICTION_THRESHOLD: float = 0.30
















_DIRECT_IDENTITY_SIGNALS: frozenset[str] = frozenset(
    {"S1_addressing", "S2_self_intro", "S2_owner_self_intro", "voice_match"}
)





_CHALLENGER_MIN_DIRECT_LOGODDS: float = 1.20




_DISAGREE_MIN_CONFIDENCE: float = 0.55
_DISAGREE_MAX_CONTRADICTION: float = 0.60





_UNCORROBORATED_PENALTY: float = 0.5




_CORRELATED_SOURCES: frozenset[frozenset[EvidenceSource]] = frozenset(
    {
        frozenset({EvidenceSource.CALENDAR, EvidenceSource.GRAPH_COOCCURRENCE}),
    }
)







def _sigmoid(x: float) -> float:
    ""
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _to_log_odds(p: float) -> float:
    ""
    p = max(0.001, min(0.999, p))
    return log(p / (1.0 - p))


def _norm_name(s: str) -> str:
    ""




    return " ".join(s.lower().replace(".", " ").replace("_", " ").split())







def _emit_plaud_label_evidence(
    segments: list[dict[str, Any]],
) -> dict[str, list[Evidence]]:
    ""






    label_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for seg in segments:
        speaker = seg.get("speaker", "")
        orig = seg.get("original_speaker", speaker)
        if not orig:
            continue
        if speaker and speaker != orig:
            label_counts[orig][speaker] += 1

    evidences: dict[str, list[Evidence]] = {}
    for speaker_id, labels in label_counts.items():
        if not labels:
            continue

        best_label = max(labels, key=lambda lbl: labels[lbl])

        if best_label.startswith("Speaker ") or len(best_label) < 2:
            continue

        ev = Evidence(
            source=EvidenceSource.PLAUD_LABEL,
            claim=f"e' {best_label}",
            weight=_to_log_odds(PLAUD_LABEL_WEIGHT),
            direction=EvidenceDirection.SUPPORT,
            quote=f"Plaud label: {best_label}",
            meta={
                "plaud_label": best_label,
                "speaker_id": speaker_id,
                "count": labels[best_label],
            },
        )
        evidences[speaker_id] = [ev]

    return evidences







def _build_name_pool(name_index: Any | None) -> frozenset[str] | None:
    ""

    if name_index is None:
        return None
    keys: set[str] = set()
    for attr in ("full", "first", "alias"):
        bucket = getattr(name_index, attr, None)
        if isinstance(bucket, dict):
            keys.update(bucket.keys())
    return frozenset(keys) if keys else None


def _collect_context_evidence(
    segments: list[dict[str, Any]],
    name_pool: frozenset[str] | None = None,
) -> dict[str, list[Evidence]]:
    ""
    all_ev = context_emit_all(segments, name_pool)
    return context_group_by_speaker(all_ev)







def _collect_kb_evidence(
    names_mentioned: set[str],
    kb_resolver: Any | None,
    name_index: Any | None,
    context: dict[str, Any] | None = None,
) -> dict[str, list[Evidence]]:
    ""







    if kb_resolver is None:
        return {}

    resolve_fn = getattr(kb_resolver, "resolve_mention", None)
    if resolve_fn is None:
        return {}

    result: dict[str, list[Evidence]] = {}
    ctx = context or {}
    for name in names_mentioned:
        try:
            candidates = resolve_fn(name, ctx, name_index=name_index)
        except Exception:
            continue
        for cand in candidates:
            if cand.evidence:
                result.setdefault(_norm_name(name), []).extend(cand.evidence)

    return result







def _dedup_correlated(evidences: list[Evidence]) -> list[Evidence]:
    ""




    if len(evidences) < 2:
        return evidences

    sources_seen: set[EvidenceSource] = set()
    result: list[Evidence] = []

    for ev in evidences:
        is_correlated = False
        for pair in _CORRELATED_SOURCES:
            if ev.source in pair:
                other_sources = pair - {ev.source}
                if other_sources & sources_seen:
                    is_correlated = True
                    break

        if is_correlated:

            deduped = Evidence(
                source=ev.source,
                claim=ev.claim,
                weight=ev.weight * 0.5,
                direction=ev.direction,
                entity_id=ev.entity_id,
                quote=ev.quote,
                meta={**ev.meta, "dedup_correlated": True},
            )
            result.append(deduped)
        else:
            result.append(ev)

        sources_seen.add(ev.source)

    return result







def _fuse_candidate_evidence(
    claim_name: str,
    evidences: list[Evidence],
) -> Candidate:
    ""





    deduped = _dedup_correlated(evidences)


    total_log_odds = PRIOR_LOG_ODDS
    for ev in deduped:
        if ev.direction == EvidenceDirection.SUPPORT:
            total_log_odds += ev.weight
        else:
            total_log_odds -= abs(ev.weight)

    confidence = _sigmoid(total_log_odds)
    confidence = round(max(0.0, min(1.0, confidence)), 4)


    entity_id = None
    for ev in evidences:
        if ev.entity_id:
            entity_id = ev.entity_id
            break

    return Candidate(
        name=claim_name,
        entity_id=entity_id,
        confidence=confidence,
        evidence=list(evidences),
    )


def _compute_contradiction_score(candidates: list[Candidate]) -> float:
    ""







    if len(candidates) < 2:

        if candidates:
            n_contradict = sum(
                1 for e in candidates[0].evidence if e.direction == EvidenceDirection.CONTRADICT
            )
            return min(1.0, n_contradict * 0.25)
        return 0.0

    sorted_cands = sorted(candidates, key=lambda c: c.confidence, reverse=True)
    top1 = sorted_cands[0].confidence
    top2 = sorted_cands[1].confidence

    if top1 < 0.01:
        return 0.5

    gap = top1 - top2
    base_score = 1.0 - (gap / max(top1, 0.01))


    all_ev = []
    for c in candidates:
        all_ev.extend(c.evidence)
    n_contradict = sum(1 for e in all_ev if e.direction == EvidenceDirection.CONTRADICT)
    contradict_bonus = min(0.3, n_contradict * 0.10)

    return round(min(1.0, max(0.0, base_score + contradict_bonus)), 4)


def _direct_support_evidences(cand: Candidate) -> list[Evidence]:
    ""



    out: list[Evidence] = []
    for ev in cand.evidence:
        if ev.direction != EvidenceDirection.SUPPORT:
            continue
        if ev.meta.get("signal", "") in _DIRECT_IDENTITY_SIGNALS:
            out.append(ev)
    return out


def _direct_identity_logodds(cand: Candidate) -> float:
    ""
    return sum(ev.weight for ev in _direct_support_evidences(cand))






_SOURCE_GROUP: dict[EvidenceSource, str] = {
    EvidenceSource.TRANSCRIPT_CONTEXT: "TEXT",
    EvidenceSource.KNOWLEDGE_BASE: "TEXT",
    EvidenceSource.GRAPH_COOCCURRENCE: "GRAPH",
    EvidenceSource.VOICE_EMBEDDING: "VOICE",
    EvidenceSource.CALENDAR: "CALENDAR",
    EvidenceSource.PLAUD_LABEL: "PLAUD",
    EvidenceSource.MANUAL_OVERRIDE: "MANUAL",
}



_STRONG_GROUPS: frozenset[str] = frozenset({"VOICE", "CALENDAR", "MANUAL"})


def _independent_support_groups(cand: Candidate) -> set[str]:
    ""

    groups: set[str] = set()
    for ev in cand.evidence:
        if ev.direction != EvidenceDirection.SUPPORT:
            continue
        g = _SOURCE_GROUP.get(ev.source)
        if g:
            groups.add(g)
    return groups


def _has_confident_voice(cand: Candidate) -> bool:
    ""

    for ev in cand.evidence:
        if (
            ev.source == EvidenceSource.VOICE_EMBEDDING
            and ev.direction == EvidenceDirection.SUPPORT
            and ev.meta.get("confident")
        ):
            return True
    return False


def _decide_proposal(
    best: Candidate | None,
    plaud_label: str | None,
    confirms_plaud: bool,
) -> tuple[str | None, bool]:
    ""








    if best is None:
        return None, False
    if confirms_plaud:

        return None, True
    groups = _independent_support_groups(best)
    confident_voice = _has_confident_voice(best)
    corroborated = len(groups) >= 2 or confident_voice
    if not corroborated:
        return None, False
    if plaud_label and _norm_name(best.name) != _norm_name(plaud_label):

        if confident_voice or (_STRONG_GROUPS & groups):
            return best.name, True
        return None, False

    return best.name, True


def _is_serious_challenger(cand: Candidate) -> bool:
    ""


    return _direct_identity_logodds(cand) >= _CHALLENGER_MIN_DIRECT_LOGODDS


def _should_disagree(
    best: Candidate | None,
    plaud_label: str | None,
    confirms_plaud: bool,
    contradiction: float,
) -> bool:
    ""









    if not plaud_label or best is None or confirms_plaud:
        return False
    if _norm_name(plaud_label) == _norm_name(best.name):
        return False
    return (
        _is_serious_challenger(best)
        and best.entity_id is not None
        and best.confidence >= _DISAGREE_MIN_CONFIDENCE
        and contradiction < _DISAGREE_MAX_CONTRADICTION
    )


def _assign_lane(
    posterior: float,
    contradiction_score: float,
    confirms_plaud: bool = False,
    _calibrated: bool = False,
) -> Lane:
    ""











    safe_confirm = confirms_plaud and contradiction_score < _CONTRADICTION_THRESHOLD
    if safe_confirm:
        return Lane.AUTO if _calibrated else Lane.CONFIRM

    if posterior >= _LANE_THRESHOLD_CONFIRM and contradiction_score < _CONTRADICTION_THRESHOLD:
        return Lane.CONFIRM
    return Lane.CONTEXT







def _extract_mentioned_names(
    context_evidence: dict[str, list[Evidence]],
    plaud_evidence: dict[str, list[Evidence]],
) -> set[str]:
    ""


    names: set[str] = set()
    for evs in context_evidence.values():
        for ev in evs:
            for key in ("addressed_name", "self_name", "mentioned_name"):
                n = ev.meta.get(key)
                if n and len(n) >= 2:
                    names.add(n)

            if ev.claim.startswith("e' ") and ev.claim != f"e' {OWNER_CLAIM_NAME}":
                names.add(ev.claim[3:].lower())

    for evs in plaud_evidence.values():
        for ev in evs:
            label = ev.meta.get("plaud_label", "")
            if label and len(label) >= 2 and not label.startswith("Speaker "):
                names.add(_norm_name(label))

    return names







def resolve_speakers(
    segments: list[dict[str, Any]],
    file_ctx: dict[str, Any] | None = None,
    name_index: Any | None = None,
    kb_resolver: Any | None = None,
    calibrated: bool = False,
    voice_evidence: dict[str, list[Evidence]] | None = None,
    calendar_evidence: dict[str, list[Evidence]] | None = None,
) -> dict[str, SpeakerResolution]:
    ""















    file_ctx = file_ctx or {}


    all_speaker_ids: set[str] = set()
    plaud_labels: dict[str, str] = {}
    for seg in segments:
        orig = seg.get("original_speaker") or seg.get("speaker") or ""
        speaker = seg.get("speaker", "")
        if orig:
            all_speaker_ids.add(orig)
        if speaker and speaker != orig and len(speaker) >= 2:
            plaud_labels[orig] = speaker

    if not all_speaker_ids:
        return {}


    plaud_ev = _emit_plaud_label_evidence(segments)



    name_pool = _build_name_pool(name_index)
    context_ev = _collect_context_evidence(segments, name_pool)


    mentioned_names = _extract_mentioned_names(context_ev, plaud_ev)
    kb_ev = _collect_kb_evidence(mentioned_names, kb_resolver, name_index, context=file_ctx)


    resolutions: dict[str, SpeakerResolution] = {}

    for speaker_id in sorted(all_speaker_ids):

        all_evidence: list[Evidence] = []


        if speaker_id in plaud_ev:
            all_evidence.extend(plaud_ev[speaker_id])


        if speaker_id in context_ev:
            all_evidence.extend(context_ev[speaker_id])


        if voice_evidence and speaker_id in voice_evidence:
            all_evidence.extend(voice_evidence[speaker_id])




        if calendar_evidence and speaker_id in calendar_evidence:
            all_evidence.extend(calendar_evidence[speaker_id])



        speaker_context_names = set()
        if speaker_id in context_ev:
            for ev in context_ev[speaker_id]:
                for key in ("addressed_name", "self_name"):
                    n = ev.meta.get(key)
                    if n:
                        speaker_context_names.add(n)
        if speaker_id in plaud_ev:
            for ev in plaud_ev[speaker_id]:
                label = ev.meta.get("plaud_label", "")
                if label:
                    speaker_context_names.add(_norm_name(label))

        for name_key in speaker_context_names:
            if name_key in kb_ev:
                all_evidence.extend(kb_ev[name_key])


        candidate_evidence: dict[str, list[Evidence]] = defaultdict(list)
        for ev in all_evidence:

            claim_name = ""
            if ev.claim.startswith("e' "):
                claim_name = ev.claim[3:]
            elif ev.claim.startswith("NON e' "):

                claim_name = ev.claim[7:]
            elif ev.meta.get("plaud_label"):
                claim_name = ev.meta["plaud_label"]
            elif ev.claim.startswith("nel meeting si menziona "):

                continue
            elif ev.claim.startswith("ha ruolo "):

                continue
            else:

                continue

            if claim_name:
                candidate_evidence[_norm_name(claim_name)].append(ev)


        candidates: list[Candidate] = []
        for cname, evs in candidate_evidence.items():
            cand = _fuse_candidate_evidence(cname, evs)
            candidates.append(cand)






        plaud_name_norm = (
            _norm_name(plaud_labels[speaker_id]) if speaker_id in plaud_labels else None
        )
        for cand in candidates:
            n_direct = len(_direct_support_evidences(cand))
            matches_plaud = plaud_name_norm is not None and cand.name == plaud_name_norm
            if n_direct <= 1 and not matches_plaud and cand.entity_id is None:
                cand.confidence = round(cand.confidence * _UNCORROBORATED_PENALTY, 4)

        candidates.sort(key=lambda c: c.confidence, reverse=True)


        best = candidates[0] if candidates else None
        posterior = best.confidence if best else 0.0
        contradiction = _compute_contradiction_score(candidates)
        plaud_label = plaud_labels.get(speaker_id)


        confirms_plaud = bool(
            plaud_label and best and _norm_name(best.name) == _norm_name(plaud_label)
        )
        lane = _assign_lane(
            posterior, contradiction, confirms_plaud=confirms_plaud, _calibrated=calibrated
        )










        plaud_disagree = _should_disagree(best, plaud_label, confirms_plaud, contradiction)



        proposed_name, corroborated = _decide_proposal(best, plaud_label, confirms_plaud)

        resolutions[speaker_id] = SpeakerResolution(
            speaker_id=speaker_id,
            candidates=candidates,
            posterior=posterior,
            contradiction_score=contradiction,
            plaud_label=plaud_label,
            plaud_disagree=plaud_disagree,
            lane=lane,
            provenance=Provenance.PLAUD_NATIVE,
            proposed_name=proposed_name,
            corroborated=corroborated,
        )

    return resolutions







def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Demo: resolve the speakers of a Plaud transcript")
    ap.add_argument(
        "transcript",
        nargs="?",
        help="Path to the JSON transcript file (raw/*.json)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Also show the evidence for each candidate",
    )
    args = ap.parse_args()


    if not args.transcript:
        try:
            from sbk_config import PLAUD_DIR

            raw_dir = PLAUD_DIR
        except Exception:
            raw_dir = Path.home() / ".sbk-data" / "plaud" / "raw"

        candidates = sorted(raw_dir.glob("*.json"))

        for f in candidates:
            if "2026-" in f.name or "2025-" in f.name:
                args.transcript = str(f)
                break
        if not args.transcript and candidates:
            args.transcript = str(candidates[-1])
        if not args.transcript:
            print("No transcript found")
            return 1


    path = Path(args.transcript)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        segments = data.get("segments", data.get("transcript", []))
    else:
        segments = data

    print(f"File: {path.name}")
    print(f"Segments: {len(segments)}")



    name_index = None
    try:
        from pl_name_index import load_or_build

        name_index = load_or_build()
        print(f"Name index: {len(name_index)} names from the KB")
    except Exception as exc:  # noqa: BLE001
        print(f"Name index not available ({type(exc).__name__}), proceeding without KB")
    print()


    resolutions = resolve_speakers(
        segments,
        file_ctx={"filename": path.name},
        name_index=name_index,
    )


    for sid, res in resolutions.items():
        best = res.best
        marker = ""
        if res.plaud_disagree:
            marker = " ** PLAUD DISAGREE **"
        print(f"--- {sid} ---")
        print(f"  Plaud label:   {res.plaud_label or '(none)'}")
        print(
            f"  Best proposal: {best.name if best else '(none)'} "
            f"(confidence: {res.posterior:.2f})"
        )
        print(f"  Contradiction: {res.contradiction_score:.2f}")
        print(f"  Lane:          {res.lane.value}")
        print(f"  Disagree:      {res.plaud_disagree}{marker}")
        if args.all and res.candidates:
            for c in res.candidates:
                print(
                    f"    Candidate: {c.name} (conf={c.confidence:.3f}, "
                    f"sources={[e.source.value for e in c.evidence]})"
                )
                for e in c.evidence:
                    print(
                        f"      [{e.source.value}] {e.claim} "
                        f"(w={e.weight:.2f}, dir={e.direction.value}) "
                        f"quote={e.quote[:60]}..."
                    )
        print()


    n_disagree = sum(1 for r in resolutions.values() if r.plaud_disagree)
    n_labeled = sum(1 for r in resolutions.values() if r.plaud_label)
    print("=== Summary ===")
    print(f"Total speakers:    {len(resolutions)}")
    print(f"With Plaud label:  {n_labeled}")
    print(f"PLAUD DISAGREE:    {n_disagree}")
    print(f"Lane CONFERMA:     {sum(1 for r in resolutions.values() if r.lane == Lane.CONFIRM)}")
    print(f"Lane CONTESTO:     {sum(1 for r in resolutions.values() if r.lane == Lane.CONTEXT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
