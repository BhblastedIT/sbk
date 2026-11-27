#!/usr/bin/env python3
"""Clusters the voice embeddings of the speaker slots across recordings: the same voice in different recordings ends
up in one cluster, anchored by the slots already named.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

RAW_DIR = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "raw"
)
EMB_PATH = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "embeddings"
    / "speaker-embeddings.json"
)
OUT_PATH = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "plaud"
    / "embeddings"
    / "voice-clusters.json"
)

GENERIC_RE = re.compile(r"^\s*(speaker|relatore|persona)\s*\d+\s*$", re.I)
SAME_VOICE = 0.80
MERGE_CENTROID = 0.90
FUSED_MEDIAN = 0.75


def _speech_seconds(date: str, generic_labels: list[str]) -> dict[str, float]:
    ""
    out: dict[str, float] = defaultdict(float)
    for p in RAW_DIR.glob(f"{date}_*.json"):
        try:
            segs = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(segs, list):
            continue
        labels_here = {
            str(s.get("speaker")).strip() for s in segs if isinstance(s, dict) and s.get("speaker")
        }
        if not set(generic_labels) & labels_here:
            continue
        for s in segs:
            if not isinstance(s, dict):
                continue
            sp = str(s.get("speaker") or "").strip()
            st, en = s.get("start_time"), s.get("end_time")
            if sp and isinstance(st, int | float) and isinstance(en, int | float) and en > st:
                out[sp] += (en - st) / 1000.0
        break
    return dict(out)


class UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-slot voice clustering (E1b)")
    ap.add_argument("--top", type=int, default=30, help="clusters in the report")
    ap.add_argument("--threshold", type=float, default=SAME_VOICE)
    args = ap.parse_args()

    data = json.loads(EMB_PATH.read_text())
    print(f"notes with embeddings: {len(data)}")


    items = []
    for fid, e in data.items():
        for label, vec in (e.get("speakers") or {}).items():
            items.append(
                (fid, label, bool(GENERIC_RE.match(label)), np.asarray(vec, dtype=np.float32))
            )
    if not items:
        print("no embeddings: run pl_fetch_embeddings first")
        return 1
    n = len(items)
    n_gen = sum(1 for it in items if it[2])
    print(f"slots with vector: {n} (generic {n_gen}, named anchors {n - n_gen})")


    M = np.stack([it[3] for it in items])
    M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    uf = UnionFind(n)
    B = 512
    thr = args.threshold
    for i0 in range(0, n, B):
        S = M[i0 : i0 + B] @ M.T
        idx = np.argwhere(thr <= S)
        for r, c in idx:
            a = i0 + int(r)
            b = int(c)
            if a < b:
                uf.union(a, b)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)


    roots = list(groups)
    cents = {r: M[groups[r]].mean(axis=0) for r in roots}
    for r in roots:
        cents[r] = cents[r] / (np.linalg.norm(cents[r]) + 1e-9)
    merged = True
    while merged:
        merged = False
        roots = [r for r in groups]
        for i in range(len(roots)):
            for j in range(i + 1, len(roots)):
                a, b = roots[i], roots[j]
                if a not in groups or b not in groups:
                    continue
                if float(cents[a] @ cents[b]) >= MERGE_CENTROID:
                    groups[a].extend(groups[b])
                    del groups[b]
                    v = M[groups[a]].mean(axis=0)
                    cents[a] = v / (np.linalg.norm(v) + 1e-9)
                    merged = True


    clusters = []
    speech_cache: dict[str, dict[str, float]] = {}
    for r, members in groups.items():
        cent = cents[r]
        sims = M[members] @ cent
        gen_members = [m for m in members if items[m][2]]
        anchor_names = defaultdict(int)
        for m in members:
            if not items[m][2]:
                anchor_names[items[m][1]] += 1
        notes = {items[m][0] for m in members}

        sec = 0.0
        for m in gen_members:
            fid, label = items[m][0], items[m][1]
            if fid not in speech_cache:
                e = data[fid]
                speech_cache[fid] = _speech_seconds(e["date"], e.get("generic") or [])
            sec += speech_cache[fid].get(label, 0.0)
        dates = sorted(data[items[m][0]]["date"] for m in members)
        clusters.append(
            {
                "size": len(members),
                "generic_slots": len(gen_members),
                "notes": len(notes),
                "speech_min": round(sec / 60, 1),
                "median_sim": round(float(np.median(sims)), 3),
                "suspected_fused": bool(np.median(sims) < FUSED_MEDIAN),
                "anchors": dict(sorted(anchor_names.items(), key=lambda kv: -kv[1])[:5]),
                "date_range": [dates[0], dates[-1]],
                "members": [
                    {"file_id": items[m][0], "label": items[m][1], "generic": items[m][2]}
                    for m in members
                ],
            }
        )
    clusters.sort(key=lambda c: -c["speech_min"])

    OUT_PATH.write_text(json.dumps({"threshold": thr, "clusters": clusters}))


    tot_gen = n_gen
    multi = [c for c in clusters if c["generic_slots"] >= 2]
    covered_top = sum(c["generic_slots"] for c in clusters[: args.top])
    covered_multi = sum(c["generic_slots"] for c in multi)
    print(f"\ntotal clusters: {len(clusters)} (multi-slot: {len(multi)})")
    print(
        f"CONCENTRATION: top-{args.top} clusters cover {covered_top}/{tot_gen} generic slots ({100 * covered_top / tot_gen:.0f}%)"
    )
    print(
        f"               multi-slot clusters cover {covered_multi}/{tot_gen} ({100 * covered_multi / tot_gen:.0f}%)"
    )
    print(f"\nTOP {min(args.top, len(clusters))} by speech:")
    print(
        f"{'#':>3} {'slot':>5} {'notes':>5} {'min':>7} {'sim':>6} {'fused?':>6}  anchors(named in cluster) · period"
    )
    for i, c in enumerate(clusters[: args.top], 1):
        anc = ", ".join(f"{k}×{v}" for k, v in c["anchors"].items()) or "—"
        fused = "⚠️" if c["suspected_fused"] else ""
        print(
            f"{i:>3} {c['generic_slots']:>5} {c['notes']:>5} {c['speech_min']:>7} {c['median_sim']:>6} {fused:>6}  {anc} · {c['date_range'][0]}→{c['date_range'][1]}"
        )
    print(f"\noutput: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
