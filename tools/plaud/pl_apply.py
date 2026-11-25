#!/usr/bin/env python3
""

















from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _p in (
    str(_REPO),
    str(_REPO / "tools"),
    str(_REPO / "tools" / "plaud"),
    str(_REPO / "dashboard"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.plaud import pl_plan, pl_write, pl_write_history
from tools.plaud.pl_calendar import (
    attendee_persons,
    emit_calendar_evidence,
    events_overlapping,
    load_email_index,
    load_events,
)
from tools.plaud.pl_voice_match import (
    build_clean_registry,
    emit_voice_evidence,
    match_speakers,
)
from tools.plaud.pl_voice_registry import load_registry
from tools.plaud.pl_write_policy import WriteAction


def _detail(file_id: str, wt: str, api: str) -> dict[str, Any]:
    d = pl_write._http("GET", api, f"/file/detail/{file_id}", wt)
    return (d.get("data") or d) if isinstance(d, dict) else {}


def evidence_for_note(
    file_id: str,
    segs: list[dict],
    wt: str,
    api: str,
    clean_registry: list[dict],
    events: Any,
    eidx: Any,
) -> tuple[dict, dict, dict]:
    ""
    detail = _detail(file_id, wt, api)
    voice_ev: dict = {}
    cal_ev: dict = {}
    emb = detail.get("embeddings") or {}
    if emb and clean_registry:
        voice_ev = emit_voice_evidence(match_speakers(emb, clean_registry))
    st = detail.get("start_time")
    spk_ids = sorted(
        {
            (s.get("original_speaker") or s.get("speaker"))
            for s in segs
            if (s.get("original_speaker") or s.get("speaker"))
        }
    )
    persons = []
    if st and events is not None:
        dt = datetime.fromtimestamp(int(st) / 1000, tz=UTC)
        durmin = (int(detail.get("duration", 0)) / 1000 / 60) or 30
        ov = events_overlapping(events, dt, durmin)
        persons = attendee_persons(ov, eidx)
        cal_ev = emit_calendar_evidence(spk_ids, persons)
    meta = {
        "title": detail.get("file_name"),
        "n_emb": len(emb),
        "attendees": [p.get("name") for p in persons],
    }
    return voice_ev, cal_ev, meta


def plan_note(
    file_id: str,
    raw_file: str,
    wt: str,
    api: str,
    *,
    name_index: Any,
    clean_registry: list[dict],
    events: Any,
    eidx: Any,
) -> dict[str, Any]:



    try:
        segs = pl_write.read_segments(file_id, wt, api)
    except Exception:  # noqa: BLE001
        segs = pl_plan._load_raw_segments(raw_file) if raw_file else []
    if not segs and raw_file:
        segs = pl_plan._load_raw_segments(raw_file)
    voice_ev, cal_ev, meta = evidence_for_note(file_id, segs, wt, api, clean_registry, events, eidx)
    plan = pl_plan.build_plan(
        segs,
        name_index=name_index,
        voice_evidence=voice_ev,
        calendar_evidence=cal_ev,
        file_id=file_id,
    )
    plan["meta"] = meta
    plan["_segs_labels"] = {
        (s.get("original_speaker") or s.get("speaker")): s.get("speaker") for s in segs
    }
    return plan


def build_history_ops(plan: dict[str, Any]) -> dict[str, dict[str, str]]:
    ""
    labels = plan.get("_segs_labels", {})
    ops = {}
    for sid, new in plan.get("rename_ops_certain", {}).items():
        ops[sid] = {"old": labels.get(sid, sid), "new": new}
    return ops


def apply_note(
    file_id: str,
    raw_file: str,
    *,
    apply: bool,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    ""
    wt, api = ctx["wt"], ctx["api"]
    plan = plan_note(
        file_id,
        raw_file,
        wt,
        api,
        name_index=ctx["ni"],
        clean_registry=ctx["clean"],
        events=ctx["events"],
        eidx=ctx["eidx"],
    )
    certain = plan["rename_ops_certain"]
    result = {
        "file_id": file_id,
        "plan_summary": plan["summary"],
        "certain": certain,
        "meta": plan.get("meta"),
    }
    if not certain:
        result["applied"] = False
        result["note"] = "nessun WRITE_CERTAIN"
        return result
    if not apply:
        result["applied"] = False
        result["dry_run"] = True
        return result
    rename_ops = [pl_write.RenameOp(speaker_id=sid, new_name=name) for sid, name in certain.items()]
    try:
        res = pl_write.do_apply_both(file_id, rename_ops, apply=True)
    except pl_write.WriteError as e:

        result["applied"] = False
        result["aborted"] = str(e)
        return result


    ops = build_history_ops(plan)
    pl_write_history.record_write(
        file_id, ops, ["raw", "polish"], note_title=(plan.get("meta") or {}).get("title")
    )
    result["applied"] = True
    result["write_result"] = res
    return result


def build_ctx() -> dict[str, Any]:
    ""
    wt, api = pl_write.get_auth()
    ctx: dict[str, Any] = {"wt": wt, "api": api}
    ctx["ni"] = pl_plan._load_name_index()
    ctx["clean"] = build_clean_registry(load_registry())
    try:
        ctx["events"] = load_events()
        ctx["eidx"] = load_email_index()
    except Exception:  # noqa: BLE001
        ctx["events"] = None
        ctx["eidx"] = None
    return ctx


def scan(candidates: dict[str, str], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    ""
    hits = []
    for fid, rf in candidates.items():
        try:
            plan = plan_note(
                fid,
                rf,
                ctx["wt"],
                ctx["api"],
                name_index=ctx["ni"],
                clean_registry=ctx["clean"],
                events=ctx["events"],
                eidx=ctx["eidx"],
            )
        except Exception as e:  # noqa: BLE001
            hits.append({"file_id": fid, "error": str(e)[:120]})
            continue
        if plan["rename_ops_certain"]:
            hits.append(
                {
                    "file_id": fid,
                    "title": (plan.get("meta") or {}).get("title"),
                    "certain": plan["rename_ops_certain"],
                    "writes": [
                        w for w in plan["writes"] if w["action"] == WriteAction.WRITE_CERTAIN.value
                    ],
                }
            )
    return hits


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Auto-write Plaud end-to-end (headless)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("candidates_json")
    pp = sub.add_parser("plan")
    pp.add_argument("file_id")
    pp.add_argument("raw_file")
    pa = sub.add_parser("apply")
    pa.add_argument("file_id")
    pa.add_argument("raw_file")
    pa.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ctx = build_ctx()
    if args.cmd == "scan":
        cands = json.loads(Path(args.candidates_json).read_text())

        cmap = {k: (v.get("file") if isinstance(v, dict) else v) for k, v in cands.items()}
        hits = scan(cmap, ctx)
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    elif args.cmd == "plan":
        plan = plan_note(
            args.file_id,
            args.raw_file,
            ctx["wt"],
            ctx["api"],
            name_index=ctx["ni"],
            clean_registry=ctx["clean"],
            events=ctx["events"],
            eidx=ctx["eidx"],
        )
        pl_plan._print_plan(plan)
    elif args.cmd == "apply":
        print(
            json.dumps(
                apply_note(args.file_id, args.raw_file, apply=args.apply, ctx=ctx),
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
