#!/usr/bin/env python3
""



















from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_REPO_DIR = _TOOLS_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

EMB_DIR = Path.home() / ".sbk-data" / "plaud" / "embeddings"
OUT_PATH = EMB_DIR / "raw-polish-map.json"
TOL_S = 1.5


def _fetch_json(url: str) -> list | dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _segments(payload) -> list[dict]:
    ""
    if isinstance(payload, list):
        return [s for s in payload if isinstance(s, dict)]
    if isinstance(payload, dict):
        for k in ("trans_result", "segments", "data", "content"):
            v = payload.get(k)
            if isinstance(v, list):
                return [s for s in v if isinstance(s, dict)]
    return []


def align_note(fid: str, ctx, wt) -> dict | None:
    ""
    from tools.plaud.pl_write import _http

    d = _http("GET", ctx["api_domain"], f"/file/detail/{fid}", wt)
    data = d.get("data") or d
    links = {}
    for c in data.get("content_list", []):
        dt = c.get("data_type")
        if dt in ("transaction", "transaction_polish") and c.get("data_link"):
            links[dt] = c["data_link"]
    if "transaction" not in links or "transaction_polish" not in links:
        return None
    raw_segs = _segments(_fetch_json(links["transaction"]))
    pol_segs = _segments(_fetch_json(links["transaction_polish"]))
    if not raw_segs or not pol_segs:
        return None

    pol_by_start = sorted(
        (
            (s.get("start_time", 0) / 1000.0, str(s.get("speaker") or "").strip())
            for s in pol_segs
            if s.get("speaker")
        ),
    )
    votes: dict[str, Counter] = defaultdict(Counter)
    import bisect

    starts = [t for t, _ in pol_by_start]
    for s in raw_segs:
        lab = str(s.get("speaker") or "").strip()
        if not lab:
            continue
        st = s.get("start_time", 0) / 1000.0
        i = bisect.bisect_left(starts, st)
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(starts) and abs(starts[j] - st) <= TOL_S:
                votes[lab][pol_by_start[j][1]] += 1
                break
    mapping = {lab: cnt.most_common(1)[0][0] for lab, cnt in votes.items() if cnt}
    return {
        "map": mapping,
        "polish_labels": sorted({p for _, p in pol_by_start}),
        "fetched_at": datetime.now(tz=UTC).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mappa label raw->polished per nota")
    ap.add_argument("--fid", nargs="*", default=[])
    ap.add_argument(
        "--cluster-notes", action="store_true", help="tutte le note dei cluster battesimo"
    )
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    fids = list(args.fid)
    if args.cluster_notes:
        from tools.plaud.pl_baptism_queue import build_queue

        for q in build_queue(min_slots=2):
            fids.extend(m["file_id"] for m in q["members"])
    fids = sorted(set(fids))
    if not fids:
        print("nessun fid")
        return 2

    from tools.plaud.pl_auth_refresh import build_context, load_saved_wt, load_store_py

    wt = load_saved_wt()
    if not wt:
        print("nessun WT: pl_auth_refresh --refresh")
        return 1
    ctx = build_context(load_store_py())

    out = {}
    if OUT_PATH.exists():
        try:
            out = json.loads(OUT_PATH.read_text())
        except Exception:
            out = {}
    done = err = 0
    for i, fid in enumerate(fids, 1):
        try:
            r = align_note(fid, ctx, wt)
            if r:
                out[fid] = r
                done += 1
            else:
                err += 1
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  [{i}/{len(fids)}] {fid[:8]}… ERR {str(e)[:80]}")
        time.sleep(args.sleep)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False))
    tmp.rename(OUT_PATH)
    print(f"mappe: {done} ok, {err} err → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
