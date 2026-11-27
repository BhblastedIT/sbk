#!/usr/bin/env python3
"""Review report of recent Plaud recordings as an HTML page: for each one the speakers, who talks how much, people
introducing themselves, and whether the naming looks right or needs review.
"""

from __future__ import annotations

import html
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "dashboard"))

from app.core.plaud_engine_adapter import _get_name_index, _load_raw_segments  # noqa: E402
from pl_calendar import (  # noqa: E402
    attendee_persons,
    emit_calendar_evidence,
    events_overlapping,
    load_email_index,
    load_events,
)
from pl_resolver import _independent_support_groups, resolve_speakers  # noqa: E402
from pl_voice_match import build_clean_registry, emit_voice_evidence, match_speakers  # noqa: E402
from pl_write import _http, get_auth  # noqa: E402

_RAW = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "raw"
)
_GIORNI = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_SELF_RE = re.compile(r"\b(?:sono|mi chiamo|io sono)\s+([A-Za-zÀ-ÿ]{3,})", re.IGNORECASE)

_SELF_STOP = frozenset(
    {
        "vecchio",
        "entrato",
        "qui",
        "sicuro",
        "contento",
        "stato",
        "andato",
        "stanco",
        "pronto",
        "convinto",
        "felice",
        "d",
        "un",
        "una",
        "il",
        "molto",
        "sempre",
        "ancora",
    }
)


def _file_id(sf: str) -> str | None:
    txt = _RAW / (sf[:-5] + ".txt")
    if not txt.exists():
        return None
    m = re.search(r"# ID:\s*([0-9a-f]+)", txt.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def _fascia(h: int) -> str:
    if h < 6:
        return "night"
    if h < 12:
        return "morning"
    if h < 14:
        return "lunchtime"
    if h < 18:
        return "afternoon"
    return "evening"


def _self_quote(segs: list[dict], speaker_id: str) -> str:
    for s in segs:
        if (s.get("original_speaker") or s.get("speaker")) != speaker_id:
            continue
        m = _SELF_RE.search(s.get("content", ""))


        if m and m.group(1)[0].isupper() and m.group(1).lower() not in _SELF_STOP:
            return s["content"][:140]
    return ""


def _talk_pct(segs: list[dict], speaker_id: str) -> int:
    tot = sum(1 for s in segs if (s.get("original_speaker") or s.get("speaker")))
    mine = sum(1 for s in segs if (s.get("original_speaker") or s.get("speaker")) == speaker_id)
    return round(100 * mine / tot) if tot else 0


def analyze(sf: str, ctx: dict[str, Any]) -> dict[str, Any]:
    ""
    segs = _load_raw_segments(sf)
    fid = _file_id(sf)
    voice_ev = cal_ev = None
    scene = {"title": sf[:-5], "when": sf[:10], "attendees": [], "event": None}
    if fid:
        try:
            data = (_http("GET", ctx["api"], f"/file/detail/{fid}", ctx["wt"])).get("data") or {}
            st = data.get("start_time")
            emb = data.get("embeddings", {})
            voice_ev = emit_voice_evidence(match_speakers(emb, ctx["clean"]))
            scene["title"] = data.get("file_name") or scene["title"]
            spk_ids = sorted(
                {
                    (s.get("original_speaker") or s.get("speaker") or "")
                    for s in segs
                    if (s.get("original_speaker") or s.get("speaker"))
                }
            )
            if st:
                dt = datetime.fromtimestamp(int(st) / 1000, tz=UTC)
                durmin = (int(data.get("duration", 0)) / 1000 / 60) or 30
                scene["dt"] = dt
                scene["durmin"] = round(durmin)
                ov = events_overlapping(ctx["events"], dt, durmin)
                persons = attendee_persons(ov, ctx["eidx"])
                scene["attendees"] = [p["name"] for p in persons]
                if ov:
                    scene["event"] = str(ov[0].get("summary") or "")[:50]
                cal_ev = emit_calendar_evidence(spk_ids, persons)
        except Exception as e:  # noqa: BLE001
            scene["err"] = str(e)[:60]
    res = resolve_speakers(
        segs, name_index=ctx["ni"], voice_evidence=voice_ev, calendar_evidence=cal_ev
    )


    identified = []
    speakers = []
    for sid in sorted(res):
        r = res[sid]
        confirms = bool(r.plaud_label and r.best and _norm(r.best.name) == _norm(r.plaud_label))
        status = "OK" if (r.proposed_name or confirms) else "RIVEDERE"
        who = r.proposed_name or (r.plaud_label if confirms else None)
        if who:
            identified.append(who)



        cands = []
        if r.best and status == "RIVEDERE":
            scored = []
            for c in r.candidates:
                srcs = {e.source.value for e in c.evidence}
                reliable = ("voice_embedding" in srcs) or ("calendar" in srcs)
                if reliable or c.entity_id:
                    rank = 0 if "voice_embedding" in srcs else (1 if "calendar" in srcs else 2)
                    scored.append((rank, -c.confidence, c))
            scored.sort(key=lambda t: (t[0], t[1]))
            for _, _, c in scored[:3]:
                cands.append({"name": c.name, "why": _badges(c)})
        speakers.append(
            {
                "id": sid,
                "status": status,
                "plaud": r.plaud_label,
                "best": r.best.name if r.best else None,
                "proposed": r.proposed_name,
                "groups": sorted(_independent_support_groups(r.best)) if r.best else [],
                "quote": _self_quote(segs, sid),
                "talk": _talk_pct(segs, sid),
                "candidates": cands,
            }
        )

    identified = list(dict.fromkeys(identified))
    return {"sf": sf, "scene": scene, "speakers": speakers, "identified": identified}


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace(".", " ").replace("_", " ").split())


def _badges(cand: Any) -> list[str]:
    out = []
    srcs = {e.source.value for e in cand.evidence}
    if "voice_embedding" in srcs:
        cos = next(
            (e.meta.get("cosine") for e in cand.evidence if e.source.value == "voice_embedding"),
            None,
        )
        out.append(f"similar voice{f' ({cos:.2f})' if cos else ''}")
    if "calendar" in srcs:
        out.append("was in your calendar")
    if "transcript_context" in srcs:
        out.append("mentioned in the conversation")
    return out


def _scene_sentence(scene: dict) -> str:
    dt = scene.get("dt")
    when = scene["when"]
    if dt:
        g = _GIORNI[dt.weekday()]
        when = f"{g} {dt.strftime('%d/%m')} {_fascia(dt.hour)} ({dt.strftime('%H:%M')})"
    dur = f" · ~{scene['durmin']}min" if scene.get("durmin") else ""
    if scene.get("event"):
        loc = f" · you were at «{html.escape(scene['event'])}»"
    else:
        loc = " · not on calendar"
    topic = html.escape(str(scene["title"])[:60])
    return f"{when}{dur}{loc} · «{topic}»"


def render_html(reports: list[dict], n_ok: int, n_rev: int) -> str:
    css = """
    body{font-family:-apple-system,sans-serif;background:#0f1115;color:#e5e7eb;margin:0;padding:24px;}
    .wrap{max-width:820px;margin:0 auto;}
    h1{font-size:20px;} .sub{color:#9ca3af;font-size:13px;margin-bottom:20px;}
    .rec{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:16px;margin-bottom:16px;}
    .scene{font-size:13px;color:#cbd5e1;margin-bottom:4px;}
    .who{font-size:12px;color:#9ca3af;margin-bottom:10px;}
    .chip{display:inline-block;background:#232833;border-radius:10px;padding:1px 8px;margin:2px;font-size:11px;}
    .spk{border-top:1px solid #232833;padding:8px 0;}
    .ok{color:#34d399;} .rev{color:#fbbf24;}
    .cand{font-size:12px;margin:3px 0 3px 14px;}
    .badge{color:#7dd3fc;font-size:11px;}
    .quote{font-style:italic;color:#94a3b8;font-size:12px;margin:2px 0 2px 14px;}
    .gr{font-family:monospace;font-size:10px;color:#64748b;}
    """
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Plaud — Review of 10 conversations</title>",
        f"<style>{css}</style></head><body><div class='wrap'>",
        "<h1>⚡ Plaud — Conversation review</h1>",
        f"<div class='sub'>{len(reports)} conversations · {n_ok} speakers OK (confirmed by voice/label) · "
        f"{n_rev} to review. Writable proposals have 2 independent matches.</div>",
    ]
    for rep in reports:
        parts.append("<div class='rec'>")
        parts.append(f"<div class='scene'>{_scene_sentence(rep['scene'])}</div>")
        others = [html.escape(x) for x in rep["identified"]]
        att = [
            html.escape(x) for x in rep["scene"].get("attendees", []) if x not in rep["identified"]
        ]
        who = "".join(f"<span class='chip'>{o}</span>" for o in others)
        who += "".join(f"<span class='chip'>📅 {a}</span>" for a in att[:6])
        if who:
            parts.append(f"<div class='who'>with you: {who}</div>")
        for sp in rep["speakers"]:
            cls = "ok" if sp["status"] == "OK" else "rev"
            head = f"<b>{sp['id']}</b> "
            if sp["status"] == "OK":
                nm = sp["proposed"] or sp["plaud"]
                head += f"<span class='ok'>✓ {html.escape(str(nm))}</span>"
            else:
                head += f"<span class='rev'>? to review</span> <span class='gr'>speaks {sp['talk']}%</span>"
            parts.append(
                f"<div class='spk'>{head} <span class='gr'>[{'+'.join(sp['groups'])}]</span>"
            )
            if sp["status"] != "OK":
                if sp["quote"]:
                    parts.append(f"<div class='quote'>« {html.escape(sp['quote'])} »</div>")
                for c in sp["candidates"]:
                    why = " · ".join(html.escape(w) for w in c["why"])
                    parts.append(
                        f"<div class='cand'>◦ {html.escape(c['name'])} <span class='badge'>{why}</span></div>"
                    )
                if not sp["candidates"]:
                    parts.append(
                        "<div class='cand gr'>no reliable candidate — your context is needed</div>"
                    )
            parts.append("</div>")
        parts.append("</div>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default=str(Path.home() / "plaud-review.html"))
    args = ap.parse_args()

    files = sorted(
        (f for f in os.listdir(_RAW) if f.endswith(".json") and f[:4].isdigit()), reverse=True
    )[: args.n]
    import json

    reg = json.loads((_RAW.parent / "_speaker_registry.json").read_text())
    ctx = {
        "ni": _get_name_index(),
        "clean": build_clean_registry(reg),
        "events": load_events(),
        "eidx": load_email_index(),
    }
    ctx["wt"], ctx["api"] = get_auth()

    reports = []
    n_ok = n_rev = 0
    for i, sf in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {sf[:50]}")
        rep = analyze(sf, ctx)
        for sp in rep["speakers"]:
            if sp["status"] == "OK":
                n_ok += 1
            else:
                n_rev += 1
        reports.append(rep)

    Path(args.out).write_text(render_html(reports, n_ok, n_rev), encoding="utf-8")
    print(f"\nReport: {args.out}  ({n_ok} OK, {n_rev} to review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
