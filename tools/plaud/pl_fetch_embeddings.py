#!/usr/bin/env python3
"""Downloads from Plaud the voice embedding of each generic speaker slot (Speaker 1, 2...) of your recordings, for
the voice clustering; --dry-run computes the set of recordings without network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_REPO_DIR = _TOOLS_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

RAW_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "raw"
)
INDEX_PATH = RAW_DIR / "_file_index.json"
OUT_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "embeddings"
)
OUT_PATH = OUT_DIR / "speaker-embeddings.json"

GENERIC_RE = re.compile(r"^\s*(speaker|relatore|persona)\s*\d+\s*$", re.I)


def note_speakers(file_stem_candidates: list[Path]) -> tuple[set[str], set[str]]:
    ""
    generic: set[str] = set()
    named: set[str] = set()
    for p in file_stem_candidates:
        try:
            segs = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(segs, list):
            continue
        for s in segs:
            if not isinstance(s, dict):
                continue
            sp = s.get("speaker")
            if not sp or not isinstance(sp, str) or not sp.strip():
                continue
            sp = sp.strip()
            (generic if GENERIC_RE.match(sp) else named).add(sp)
    return generic, named


def build_perimeter() -> list[dict]:
    ""
    index = json.loads(INDEX_PATH.read_text())

    perimeter = []
    for e in index:
        if not e.get("has_transcript"):
            continue
        date = e.get("date") or "unknown"
        fn = e.get("filename") or ""

        safe = re.sub(r"[^\w\s\-.]", "_", fn)[:80]
        cands = list(RAW_DIR.glob(f"{date}_{safe[:40]}*.json"))
        if not cands:
            cands = list(RAW_DIR.glob(f"{date}_*.json"))
            cands = [c for c in cands if c.stem.startswith(f"{date}_") and safe[:20] in c.stem][:1]
        if not cands:
            continue
        generic, named = note_speakers(cands[:1])
        if not generic:
            continue
        perimeter.append(
            {
                "id": e["id"],
                "date": date,
                "st": e.get("st"),
                "filename": fn,
                "generic": sorted(generic),
                "named": sorted(named),
            }
        )
    return perimeter


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch per-slot voice embeddings (E1)")
    ap.add_argument("--dry-run", action="store_true", help="perimeter only, no network")
    ap.add_argument("--limit", type=int, default=0, help="max notes to fetch (0=all)")
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between calls (s)")
    args = ap.parse_args()

    perimeter = build_perimeter()
    n_slots = sum(len(p["generic"]) for p in perimeter)
    print(f"perimeter: {len(perimeter)} notes with generic slots ({n_slots} slots)")

    if args.dry_run:
        by_year: dict[str, int] = {}
        for p in perimeter:
            by_year[p["date"][:4]] = by_year.get(p["date"][:4], 0) + 1
        print(f"by year: {dict(sorted(by_year.items()))}")
        return 0

    from tools.plaud.pl_auth_refresh import build_context, load_saved_wt, load_store_py
    from tools.plaud.pl_write import _http

    wt = load_saved_wt()
    if not wt:
        print("no valid WT: run pl_auth_refresh --refresh first")
        return 1
    ctx = build_context(load_store_py())
    api = ctx["api_domain"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict = {}
    if OUT_PATH.exists():
        try:
            result = json.loads(OUT_PATH.read_text())
        except Exception:
            result = {}

    todo = [p for p in perimeter if str(p["id"]) not in result]
    if args.limit:
        todo = todo[: args.limit]
    print(f"to fetch: {len(todo)} (already present: {len(result)})")

    def flush():
        tmp = OUT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(result))
        tmp.rename(OUT_PATH)

    errors = 0
    empty = 0
    for i, p in enumerate(todo, 1):
        fid = str(p["id"])
        try:
            d = _http("GET", api, f"/file/detail/{fid}", wt)
            data = d.get("data") or d
            emb = data.get("embeddings") or {}

            speakers = {
                k: v
                for k, v in emb.items()
                if isinstance(v, list)
                and len(v) >= 64
                and all(isinstance(x, int | float) for x in v[:8])
            }
            if not speakers:
                empty += 1
            result[fid] = {
                "st": p["st"],
                "date": p["date"],
                "generic": p["generic"],
                "named": p["named"],
                "speakers": speakers,
                "fetched_at": datetime.now(tz=UTC).isoformat(),
            }
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(todo)}] {fid[:8]}… ERR: {str(e)[:100]}")
            if errors > 20:
                print("too many consecutive errors possible: stopping (resume-safe)")
                flush()
                return 1
        if i % 25 == 0:
            flush()
            print(f"  [{i}/{len(todo)}] saved ({len(result)} total, {empty} without embeddings)")
        time.sleep(args.sleep)
    flush()
    print(f"DONE: {len(result)} notes in the file, {empty} without embeddings, {errors} errors")
    print(f"output: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
