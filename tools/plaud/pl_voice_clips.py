#!/usr/bin/env python3
"""Short audio clips of each unnamed voice, so you can listen and give it a name.

Writes one .m4a per voice of the naming queue (pl_baptism_queue) into <data root>/plaud/voice-clips/.
Needs ffmpeg and a Plaud web token (pl_auth_refresh --refresh).
"""




















from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_REPO_DIR = _TOOLS_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from sbk_config import DATA_ROOT  # noqa: E402

RAW_DIR = DATA_ROOT / "plaud" / "raw"
EMB_DIR = DATA_ROOT / "plaud" / "embeddings"
OUT_DIR = DATA_ROOT / "plaud" / "voice-clips"
CACHE_DIR = Path(os.environ.get("SBK_SCRATCH", str(OUT_DIR / "_cache")))

MIN_SEG_S = 6.0
MAX_SEG_S = 25.0
CLIPS_PER_VOICE = 3


def _segments_of(date: str, label: str) -> list[tuple[float, float, str]]:
    ""
    for p in RAW_DIR.glob(f"{date}_*.json"):
        try:
            segs = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(segs, list):
            continue
        labels_here = {str(s.get("speaker") or "").strip() for s in segs if isinstance(s, dict)}
        if label not in labels_here:
            continue
        out = []
        for s in segs:
            if not isinstance(s, dict) or str(s.get("speaker") or "").strip() != label:
                continue
            st, en = s.get("start_time"), s.get("end_time")
            if isinstance(st, int | float) and isinstance(en, int | float) and en > st:
                out.append((st / 1000.0, en / 1000.0, str(s.get("content") or "")[:80]))
        out.sort(key=lambda t: -(t[1] - t[0]))
        return out
    return []


def _audio_for(fid: str) -> Path | None:
    ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{fid}.ogg"
    if cached.exists() and cached.stat().st_size > 10_000:
        return cached
    from tools.plaud.pl_auth_refresh import build_context, load_saved_wt, load_store_py
    from tools.plaud.pl_write import _http

    wt = load_saved_wt()
    if not wt:
        print("no Plaud web token: run pl_auth_refresh --refresh")
        return None
    ctx = build_context(load_store_py())
    r = _http("GET", ctx["api_domain"], f"/file/temp-url/{fid}", wt)
    url = (r.get("data") or r).get("temp_url") if isinstance(r, dict) else None
    if not url:
        print(f"  no temp-url for {fid[:8]}…")
        return None
    proc = subprocess.run(
        ["curl", "-sS", "-f", "-o", str(cached), url], capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0 or not cached.exists():
        print(f"  download failed {fid[:8]}…: {proc.stderr[:120]}")
        return None
    return cached


def make_clip(voice_n: int, members: list[dict], emb: dict, out_path: Path) -> bool:
    ""

    best = None
    for m in members:
        e = emb.get(m["file_id"]) or {}
        segs = _segments_of(e.get("date", ""), m["label"])
        tot = sum(en - st for st, en, _ in segs)
        if segs and (best is None or tot > best[0]):
            best = (tot, m["file_id"], m["label"], segs)
    if not best:
        print(f"voice {voice_n}: no segment found")
        return False
    _, fid, label, segs = best
    picks = []
    for st, en, txt in segs:
        dur = en - st
        if dur < MIN_SEG_S:
            continue
        picks.append((st, min(en, st + MAX_SEG_S), txt))
        if len(picks) >= CLIPS_PER_VOICE:
            break
    if not picks:
        picks = [(st, en, tx) for st, en, tx in segs[:CLIPS_PER_VOICE]]
    audio = _audio_for(fid)
    if not audio:
        return False



    pr = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(audio),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        audio_dur = float(pr.stdout.strip())
    except ValueError:
        audio_dur = 0.0
    if audio_dur > 5:
        picks = [(st, en, tx) for st, en, tx in picks if en <= audio_dur - 1]
        if not picks:
            picks = [
                (st, min(en, st + MAX_SEG_S), tx)
                for st, en, tx in segs
                if en <= audio_dur - 1 and (en - st) >= 3
            ][:CLIPS_PER_VOICE]
    if not picks:
        print(f"voice {voice_n}: nothing said inside the available audio ({audio_dur:.0f}s)")
        return False
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for i, (st, en, _tx) in enumerate(picks):
            part = Path(td) / f"p{i}.m4a"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{st:.2f}",
                    "-t",
                    f"{en - st:.2f}",
                    "-i",
                    str(audio),
                    "-ac",
                    "1",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-y",
                    str(part),
                ],
                check=True,
                capture_output=True,
                timeout=300,
            )
            if not part.exists() or part.stat().st_size < 2000:
                continue
            parts.append(part)
        parts = [p for p in parts if p.exists() and p.stat().st_size >= 2000]
        if not parts:
            print(f"voice {voice_n}: no usable part")
            return False
        listfile = Path(td) / "list.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listfile),
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-y",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    return out_path.exists()


def main() -> int:
    ap = argparse.ArgumentParser(description="Audio clips of the voices to name")
    ap.add_argument("--voice", type=int, nargs="*", help="voice numbers (default: all)")
    ap.add_argument("--min-slots", type=int, default=2)
    args = ap.parse_args()

    from tools.plaud.pl_baptism_queue import build_queue

    queue = build_queue(min_slots=args.min_slots)
    emb = json.loads((EMB_DIR / "speaker-embeddings.json").read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = set(args.voice or range(1, len(queue) + 1))
    done = 0
    for n, q in enumerate(queue, 1):
        if n not in wanted:
            continue
        out = OUT_DIR / f"voce-{n:02d}.m4a"
        ok = make_clip(n, q["members"], emb, out)
        if ok:
            size = out.stat().st_size / 1024
            print(f"voice #{n}: {out} ({size:.0f} KB)")
            done += 1
    print(f"\n{done} clips in {OUT_DIR}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
