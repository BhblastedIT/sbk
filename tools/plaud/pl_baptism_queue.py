#!/usr/bin/env python3
"""Voice naming queue: from the voice clusters, the voices worth naming first (how many recordings they cover),
with sample quotes and guesses from the slots already named; --dossier writes full cards.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from sbk_config import is_own_name, is_owner_speaker  # noqa: E402

RAW_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "raw"
)
EMB_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "embeddings"
)
CLUSTERS_PATH = EMB_DIR / "voice-clusters.json"
EMB_PATH = EMB_DIR / "speaker-embeddings.json"


def raw_path_for(fid: str, index: dict | None = None) -> Path | None:
    ""




    if index is None:
        index = {str(e["id"]): e for e in json.loads((RAW_DIR / "_file_index.json").read_text())}
    e = index.get(str(fid))
    if not e:
        return None
    fn = e.get("filename") or ""
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in fn)[:100]
    base = f"{e.get('date', 'unknown')}_{safe}.json"


    import unicodedata

    for form in ("NFC", "NFD"):
        path = RAW_DIR / unicodedata.normalize(form, base)
        if path.exists():
            return path
    return None


def _segments_from(path: Path, label: str) -> list[tuple[float, float, str]]:
    ""
    try:
        segs = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(segs, list):
        return []
    out = []
    for sg in segs:
        if not isinstance(sg, dict) or str(sg.get("speaker") or "").strip() != label:
            continue
        st, en = sg.get("start_time"), sg.get("end_time")
        if isinstance(st, int | float) and isinstance(en, int | float) and en > st:
            out.append((st / 1000.0, (en - st) / 1000.0, str(sg.get("content") or "")))
    out.sort(key=lambda t: -t[1])
    return out


def _quotes_for(date: str, label: str, n: int = 2, min_len: int = 60) -> list[str]:
    ""
    best: list[str] = []
    for p in RAW_DIR.glob(f"{date}_*.json"):
        try:
            segs = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(segs, list):
            continue
        texts = [
            str(s.get("content") or "").strip()
            for s in segs
            if isinstance(s, dict) and str(s.get("speaker") or "").strip() == label
        ]
        cands = sorted((t for t in texts if len(t) >= min_len), key=len, reverse=True)
        if cands:
            best = cands[:n]
            break
    return [t[:220] + ("…" if len(t) > 220 else "") for t in best]


def build_queue(min_slots: int = 2, quotes: int = 2) -> list[dict]:
    clusters = json.loads(CLUSTERS_PATH.read_text())["clusters"]
    emb = json.loads(EMB_PATH.read_text())
    queue = []
    for i, c in enumerate(clusters):
        if c["generic_slots"] < min_slots or c.get("suspected_fused"):
            continue
        gen = [m for m in c["members"] if m["generic"]]

        sample = gen[0]
        e = emb.get(sample["file_id"]) or {}
        qs = _quotes_for(e.get("date", ""), sample["label"], n=quotes)
        queue.append(
            {
                "cluster_idx": i,
                "slots": c["generic_slots"],
                "notes": c["notes"],
                "speech_min": c["speech_min"],
                "median_sim": c["median_sim"],
                "date_range": c["date_range"],
                "anchors": c.get("anchors") or {},
                "quotes": qs,
                "members": gen,
            }
        )
    return queue


def _label_seconds(date: str, label: str) -> float:
    ""
    for p in RAW_DIR.glob(f"{date}_*.json"):
        try:
            segs = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(segs, list):
            continue
        tot = 0.0
        seen = False
        for sg in segs:
            if not isinstance(sg, dict):
                continue
            if str(sg.get("speaker") or "").strip() != label:
                continue
            seen = True
            st, en = sg.get("start_time"), sg.get("end_time")
            if isinstance(st, int | float) and isinstance(en, int | float) and en > st:
                tot += (en - st) / 1000.0
        if seen:
            return tot
    return 0.0


def build_dossier(queue: list[dict], max_notes: int = 5) -> str:
    ""


    from tools.plaud.pl_context_correlate import correlate

    emb = json.loads(EMB_PATH.read_text())
    index = {str(e["id"]): e for e in json.loads((RAW_DIR / "_file_index.json").read_text())}
    out = ["# Voice naming queue, dossier cards", ""]
    out.append(
        f"{len(queue)} voices · {sum(q['slots'] for q in queue)} slots · naming a voice = resolving ALL its notes\n"
    )
    for n, q in enumerate(queue, 1):
        out.append(
            f"## Voice #{n}, {q['slots']} slots in {q['notes']} notes · {q['speech_min']} min · {q['date_range'][0]} → {q['date_range'][1]}"
        )
        anc = ", ".join(f"{k}×{v}" for k, v in q["anchors"].items())
        if anc:
            out.append(f"Guesses from the named slots in the cluster: **{anc}**")
        for quote in q["quotes"]:
            out.append(f'> "{quote}"')
        out.append("")

        label_by_fid = {m["file_id"]: m["label"] for m in q["members"]}
        fids = sorted(
            label_by_fid,
            key=lambda f: -_label_seconds((emb.get(f) or {}).get("date", ""), label_by_fid[f]),
        )
        for fid in fids[:max_notes]:
            ix = index.get(fid) or {}
            e = emb.get(fid) or {}
            title = (ix.get("filename") or "?")[:70]
            dur = (ix.get("duration_sec") or 0) / 60
            ctx = correlate(fid)
            when = ctx.get("when", "")[:16].replace("T", " ")
            named_list = [
                x
                for x in (e.get("named") or [])
                if not (is_own_name(x) or is_owner_speaker(x)) and not re.match(r"^U[A-Z0-9]{8,}$", x)
            ]
            named = ", ".join(named_list[:4]) or "—"
            out.append(f"- **{when}** ({dur:.0f}m) «{title}» · with (already named): {named}")
            for ev in (ctx.get("calendar_events") or [])[:2]:
                out.append(
                    f"  - 📅 «{ev['title']}»"
                    + (f" @ {ev['location']}" if ev.get("location") else "")
                    + (" [call-link]" if ev.get("has_link") else "")
                )
            for pp in (ctx.get("attendee_pool") or [])[:4]:
                out.append(f"  - 👤 invitee: {pp['name']}")
            for h in (ctx.get("email_hits") or [])[:2]:
                ppl = ", ".join(x["name"] for x in h["people"][:3])
                out.append(f"  - ✉️ {h['when'][11:16]} «{h['subject'][:60]}» ({ppl})")
            sl_shown = 0
            for sl in ctx.get("slack_activity") or []:
                if re.match(r"^U[A-Z0-9]{8,}$", sl["person"]) or sl_shown >= 2:
                    continue
                out.append(f"  - 💬 slack with {sl['person']} ({sl['messages']} msg ±3h)")
                sl_shown += 1
        if len(fids) > max_notes:
            out.append(f"- … and {len(fids) - max_notes} more notes")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice naming queue from the voice clusters")
    ap.add_argument("--min-slots", type=int, default=2)
    ap.add_argument("--quotes", type=int, default=2)
    ap.add_argument("--json", action="store_true", help="JSON output (for the UI card)")
    ap.add_argument("--dossier", help="write the full dossier cards to this file")
    args = ap.parse_args()

    queue = build_queue(min_slots=args.min_slots, quotes=args.quotes)
    if args.dossier:
        md = build_dossier(queue)
        Path(args.dossier).write_text(md)
        print(f"dossier written: {args.dossier} ({len(queue)} voices)")
        return 0
    if args.json:
        print(json.dumps(queue, ensure_ascii=False, indent=1))
        return 0

    tot_slots = sum(q["slots"] for q in queue)
    print(f"VOICE NAMING QUEUE: {len(queue)} voices, {tot_slots} covered slots to name\n")
    for n, q in enumerate(queue, 1):
        anc = ", ".join(f"{k}×{v}" for k, v in q["anchors"].items()) or "none"
        print(
            f"── voice #{n} · {q['slots']} slots in {q['notes']} notes · {q['speech_min']} min of speech · {q['date_range'][0]}→{q['date_range'][1]} (sim {q['median_sim']})"
        )
        print(f"   guesses from the named slots in the cluster: {anc}")
        for quote in q["quotes"]:
            print(f'   » "{quote}"')
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
