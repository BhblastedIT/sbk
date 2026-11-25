#!/usr/bin/env python3
""





























from __future__ import annotations

import argparse
import glob
import json
import logging
import sys
from collections import Counter
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import pandas as pd  # noqa: E402

from sbk_config import KNOWLEDGE_ENTITIES_DIR  # noqa: E402

log = logging.getLogger("sbk.knows")
KNOWLEDGE_DIR = KNOWLEDGE_ENTITIES_DIR.parent
EPISODES_DIR = KNOWLEDGE_DIR / "episodes"
EPISTEMIC_DIR = KNOWLEDGE_DIR / "epistemic"


def build_knows(episodes_dir: Path | None = None) -> pd.DataFrame:
    ""
    episodes_dir = episodes_dir or EPISODES_DIR
    rows: list[dict] = []
    n_ep = 0
    for fp in glob.glob(str(episodes_dir / "**" / "ep_*.json"), recursive=True):
        try:
            ep = json.loads(Path(fp).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        n_ep += 1
        eid = ep.get("episode_id")
        occ = ep.get("occurred_at")
        etype = ep.get("episode_type")
        for p in ep.get("participants", []):
            pid = p.get("person_id")
            if not pid or not p.get("resolved"):
                continue
            rows.append(
                {
                    "person_id": pid,
                    "episode_id": eid,
                    "episode_type": etype,
                    "access_type": p.get("attendance", "mentioned"),
                    "occurred_at": occ,
                }
            )
    df = (
        pd.DataFrame(rows).drop_duplicates(subset=["person_id", "episode_id"])
        if rows
        else pd.DataFrame(
            columns=["person_id", "episode_id", "episode_type", "access_type", "occurred_at"]
        )
    )
    df.attrs["n_episodes"] = n_ep
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description="Epistemic view KNOWS (Phase 2)")
    ap.add_argument(
        "--apply", action="store_true", help="Writes epistemic/knows.parquet (default: dry-run)"
    )
    ap.add_argument("--episodes-dir", type=Path, default=EPISODES_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.episodes_dir.exists():
        log.error("episodes/ doesn't exist — run xs-l2-episodes.py --apply first")
        return 1

    log.info("Building KNOWS from %s ...", args.episodes_dir)
    df = build_knows(args.episodes_dir)
    n_people = df["person_id"].nunique() if len(df) else 0
    n_ep = df.attrs.get("n_episodes", 0)
    per_person = Counter(df["person_id"]) if len(df) else Counter()
    top = per_person.most_common(8)

    print("=" * 64)
    print(f"  KNOWS (who-had-access) — {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 64)
    print(f"  Episodes read          : {n_ep:,}")
    print(f"  Knows rows (accesses)  : {len(df):,}")
    print(f"  People with access      : {n_people:,}")
    if len(df):
        print(f"  By access_type: {dict(Counter(df['access_type']))}")
        print("  Top people by # episodes with access:")
        for pid, n in top:
            print(f"    {pid}: {n:,} episodes")
    if args.apply:
        EPISTEMIC_DIR.mkdir(parents=True, exist_ok=True)
        out = EPISTEMIC_DIR / "knows.parquet"
        df.to_parquet(out, index=False)
        print(f"  WROTE: {out} ({len(df):,} rows)")
    else:
        print("  (dry-run: no write. --apply to write epistemic/knows.parquet)")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
