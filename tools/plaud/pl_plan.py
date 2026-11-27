#!/usr/bin/env python3
"""Write-back plan for one Plaud transcript: resolves each speaker and applies the write policy, and prints what
would be written and what needs review. It writes nothing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / "tools"
_DASH = _REPO_ROOT / "dashboard"
for _p in (str(_REPO_ROOT), str(_TOOLS_DIR), str(_TOOLS_DIR / "plaud"), str(_DASH)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tools.plaud.pl_resolver import resolve_speakers
    from tools.plaud.pl_write_policy import WriteAction, WriteDecision, decide_all, summarize
except ImportError:  # pragma: no cover
    from pl_resolver import resolve_speakers  # type: ignore[no-redef]
    from pl_write_policy import (  # type: ignore[no-redef]
        WriteAction,
        WriteDecision,
        decide_all,
        summarize,
    )


def _enforce_name_uniqueness(decisions: dict[str, WriteDecision]) -> None:
    ""



    from collections import Counter

    def norm(n: str) -> str:
        return " ".join((n or "").lower().split())

    counts: Counter = Counter()
    for d in decisions.values():
        if d.writes_transcript and d.write_name:
            counts[norm(d.write_name)] += 1
    for sid, d in list(decisions.items()):
        if d.writes_transcript and d.write_name and counts[norm(d.write_name)] > 1:
            decisions[sid] = WriteDecision(
                speaker_id=sid,
                action=WriteAction.SKIP_NO_EVIDENCE,
                write_name=None,
                enroll=False,
                certain=False,
                reason=f"ambiguous name: '{d.write_name}' given to more than one speaker in the note, not writing",
            )


def _load_name_index() -> Any:
    ""
    try:
        from tools.plaud.pl_name_index import load_or_build

        return load_or_build()
    except Exception:  # noqa: BLE001 - il motore accetta name_index=None
        return None


def build_plan(
    segments: list[dict[str, Any]],
    *,
    name_index: Any | None = None,
    voice_evidence: dict[str, list] | None = None,
    calendar_evidence: dict[str, list] | None = None,
    calibrated: bool = False,
    file_id: str | None = None,
) -> dict[str, Any]:
    ""






    res = resolve_speakers(
        segments,
        name_index=name_index,
        voice_evidence=voice_evidence,
        calendar_evidence=calendar_evidence,
        calibrated=calibrated,
    )
    decisions = decide_all(res)
    _enforce_name_uniqueness(decisions)

    writes, review, noops = [], [], []
    rename_ops_certain: dict[str, str] = {}
    rename_ops_suggested: dict[str, str] = {}
    enroll_ids: list[str] = []
    for sid, d in decisions.items():
        r = res[sid]
        row = {
            **d.to_dict(),
            "plaud_label": r.plaud_label,
            "posterior": round(r.posterior, 3),
            "corroborated": r.corroborated,
            "plaud_disagree": r.plaud_disagree,
        }
        if d.action is WriteAction.WRITE_CERTAIN:
            writes.append(row)
            rename_ops_certain[sid] = d.write_name  # type: ignore[assignment]
            if d.enroll:
                enroll_ids.append(sid)
        elif d.action is WriteAction.WRITE_SUGGESTED:
            writes.append(row)
            rename_ops_suggested[sid] = d.write_name  # type: ignore[assignment]
        elif d.action is WriteAction.REVIEW_CONFLICT:
            review.append(row)
        else:
            noops.append(row)

    return {
        "file_id": file_id,
        "n_speakers": len(res),
        "summary": summarize(decisions),
        "rename_ops_certain": rename_ops_certain,
        "rename_ops_suggested": rename_ops_suggested,
        "enroll_speaker_ids": enroll_ids,
        "writes": writes,
        "review": review,
        "noops": noops,
    }


def _load_raw_segments(source_file: str) -> list[dict[str, Any]]:
    ""

    try:
        from app.core.plaud_engine_adapter import _load_raw_segments as _ld

        return _ld(source_file)
    except Exception:  # noqa: BLE001
        raw_dir = (
            Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
            / "plaud"
            / "raw"
        )
        p = Path(source_file)
        if not p.is_absolute():
            p = raw_dir / source_file
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return data
        return data.get("segments") or data.get("trans_result") or data.get("transcript") or []


def plan_from_file(source_file: str, **kw) -> dict[str, Any]:
    ""
    segs = _load_raw_segments(source_file)
    kw.setdefault("name_index", _load_name_index())
    return build_plan(segs, **kw)


def _print_plan(plan: dict[str, Any]) -> None:
    print(f"File: {plan.get('file_id') or '?'}  speaker: {plan['n_speakers']}  {plan['summary']}")
    if plan["writes"]:
        print("\nSCRIVIAMO (raw+polish):")
        for w in plan["writes"]:
            tag = "CERTO+voce" if w["enroll"] else "suggerito"
            print(
                f"  {w['speaker_id']:12} '{w['plaud_label']}' -> '{w['write_name']}'  [{tag}]  {w['reason']}"
            )
    if plan["review"]:
        print("\nDA RIVEDERE (conflitto su nome Plaud, mai auto-overwrite):")
        for w in plan["review"]:
            print(f"  {w['speaker_id']:12} {w['reason']}")
    if plan["noops"]:
        print("\nNO WRITE:")
        for w in plan["noops"]:
            print(f"  {w['speaker_id']:12} {w['action']:16} {w['reason']}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Plaud write-back plan (resolve + policy, no write)")
    ap.add_argument(
        "source_file", help="raw file name in <data root>/plaud/raw/, or an absolute path"
    )
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    ap.add_argument("--calibrated", action="store_true", help="enable the calibrated AUTO lane")
    args = ap.parse_args()
    plan = plan_from_file(args.source_file, calibrated=args.calibrated)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        _print_plan(plan)
