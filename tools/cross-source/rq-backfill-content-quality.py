#!/usr/bin/env python3
""





















from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import DATA_ROOT

log = logging.getLogger("rq.backfill_content_quality")



RQ_DIR = DATA_ROOT / "rq"
EVENTS_DB = RQ_DIR / "events.db"
NLP_DIR = DATA_ROOT / "l3" / "nlp"
ENRICHED_DIR = DATA_ROOT / "enriched"
PLAUD_QUALITY_INDEX = DATA_ROOT / "plaud" / "processed" / "_quality_index.json"
ENTITY_BRIDGE_PATH = RQ_DIR / "entity-bridge.json"





def load_relationship_facts() -> pd.DataFrame:
    ""
    path = NLP_DIR / "relationship-facts.parquet"
    if not path.exists():
        log.warning("relationship-facts.parquet not found at %s", path)
        return pd.DataFrame(columns=["subject_person_id", "fact_type"])
    import pyarrow.parquet as pq

    schema_names = pq.read_schema(path).names
    if "subject_person_id" not in schema_names:
        log.warning(
            "relationship-facts.parquet missing subject_person_id column (schema=%s) — skipping load",
            schema_names,
        )
        return pd.DataFrame(columns=["subject_person_id", "fact_type"])
    df = pd.read_parquet(path, columns=["subject_person_id", "fact_type"])

    df = df[df["subject_person_id"].str.startswith("p_", na=False)]
    return df


def load_deep_facts() -> pd.DataFrame:
    ""
    path = NLP_DIR / "deep-facts.parquet"
    if not path.exists():
        log.warning("deep-facts.parquet not found at %s", path)
        return pd.DataFrame(columns=["subject_person_id", "category"])
    df = pd.read_parquet(path, columns=["subject_person_id", "category"])

    df = df[df["subject_person_id"].str.startswith("p_", na=False)]
    return df


def load_signals() -> pd.DataFrame:
    ""
    path = RQ_DIR / "signals.parquet"
    if not path.exists():
        log.warning("signals.parquet not found at %s", path)
        return pd.DataFrame()
    cols = [
        "person_id",
        "personal_topic_count",
        "topic_breadth",
        "meeting_warmth_score",
        "self_disclosure_count",
        "personal_topic_in_meeting",
        "emotional_word_density",
        "linguistic_style_matching",
    ]
    df = pd.read_parquet(path, columns=cols)
    df = df[df["person_id"].str.startswith("p_", na=False)]
    return df.set_index("person_id")


def load_source_counts() -> dict[str, int]:
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        log.warning("contacts-merged.parquet not found at %s", path)
        return {}
    df = pd.read_parquet(path, columns=["person_id", "source_count"])
    return dict(zip(df["person_id"], df["source_count"].astype(int)))


def load_plaud_quality_by_person(bridge: dict[str, str]) -> dict[str, float]:
    ""





    if not PLAUD_QUALITY_INDEX.exists():
        log.warning("Plaud quality index not found at %s", PLAUD_QUALITY_INDEX)
        return {}
    with open(PLAUD_QUALITY_INDEX, encoding="utf-8") as f:
        quality_data = json.load(f)





    log.info(
        "Plaud quality index has %d recordings (skipping per-recording mapping, "
        "using other signals for per-person quality)",
        len(quality_data),
    )
    return {}




























import math


def compute_rel_facts_scores(
    rel_facts: pd.DataFrame,
) -> dict[str, float]:
    ""









    if rel_facts.empty:
        return {}

    grouped = rel_facts.groupby("subject_person_id")
    scores: dict[str, float] = {}
    for pid, group in grouped:
        personal = len(group[group["fact_type"] == "personal_detail"])
        if personal == 0:
            continue


        scores[pid] = min(1.0, math.log1p(personal) / math.log1p(200))
    return scores


def compute_deep_facts_scores(
    deep_facts: pd.DataFrame,
) -> dict[str, float]:
    ""





    if deep_facts.empty:
        return {}

    grouped = deep_facts.groupby("subject_person_id")
    scores: dict[str, float] = {}
    for pid, group in grouped:
        total = len(group)
        if total == 0:
            continue


        scores[pid] = min(1.0, math.log1p(total) / math.log1p(500))
    return scores


def compute_signal_scores(
    signals: pd.DataFrame,
) -> dict[str, float]:
    ""









    if signals.empty:
        return {}

    scores: dict[str, float] = {}
    for pid, s in signals.iterrows():
        weighted_sum = 0.0
        total_weight = 0.0


        ptc = s.get("personal_topic_count", 0) or 0
        val = min(1.0, ptc / 15)
        weighted_sum += val * 0.30
        total_weight += 0.30


        sd = s.get("self_disclosure_count", 0) or 0
        val = min(1.0, sd / 5)
        weighted_sum += val * 0.25
        total_weight += 0.25


        mw = s.get("meeting_warmth_score", 0) or 0
        val = min(1.0, mw / 0.35)
        weighted_sum += val * 0.25
        total_weight += 0.25


        ptm = s.get("personal_topic_in_meeting", 0) or 0
        val = min(1.0, ptm / 0.08)
        weighted_sum += val * 0.20
        total_weight += 0.20

        if total_weight > 0:
            score = weighted_sum / total_weight
            if score > 0.01:
                scores[pid] = score

    return scores


def compute_diversity_scores(
    source_counts: dict[str, int],
) -> dict[str, float]:
    ""




    scores: dict[str, float] = {}
    for pid, count in source_counts.items():
        if count > 1:
            scores[pid] = min(1.0, (count - 1) / 7)
    return scores


def compute_person_content_quality(
    person_id: str,
    rel_scores: dict[str, float],
    deep_scores: dict[str, float],
    sig_scores: dict[str, float],
    div_scores: dict[str, float],
) -> float:
    ""







    personal_depth = rel_scores.get(person_id, 0.0)
    signal_quality = sig_scores.get(person_id, 0.0)
    interaction_volume = deep_scores.get(person_id, 0.0)
    diversity = div_scores.get(person_id, 0.0)


    substance_components = []
    if personal_depth > 0:
        substance_components.append((personal_depth, 0.60))
    if signal_quality > 0:
        substance_components.append((signal_quality, 0.40))

    if substance_components:
        total_w = sum(w for _, w in substance_components)
        substance = sum(v * w for v, w in substance_components) / total_w
    else:
        substance = 0.0


    structure_components = []
    if interaction_volume > 0:
        structure_components.append((interaction_volume, 0.60))
    if diversity > 0:
        structure_components.append((diversity, 0.40))

    if structure_components:
        total_w = sum(w for _, w in structure_components)
        structure = sum(v * w for v, w in structure_components) / total_w
    else:
        structure = 0.0


    if substance > 0:
        combined = substance * 0.80 + structure * 0.20
    elif structure > 0:

        combined = structure * 0.40
    else:
        return 0.05

    return round(min(1.0, max(0.05, combined)), 4)





def backfill_content_quality(
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    ""



    t0 = time.time()


    log.info("Loading data sources...")
    rel_facts = load_relationship_facts()
    log.info("  relationship-facts: %d rows", len(rel_facts))

    deep_facts = load_deep_facts()
    log.info("  deep-facts: %d rows", len(deep_facts))

    signals = load_signals()
    log.info("  signals: %d persons", len(signals))

    source_counts = load_source_counts()
    log.info("  contacts-merged: %d persons with source_count", len(source_counts))


    log.info("Computing per-person sub-scores...")
    rel_scores = compute_rel_facts_scores(rel_facts)
    log.info("  rel_scores: %d persons", len(rel_scores))

    deep_scores = compute_deep_facts_scores(deep_facts)
    log.info("  deep_scores: %d persons", len(deep_scores))

    sig_scores = compute_signal_scores(signals)
    log.info("  sig_scores: %d persons", len(sig_scores))

    div_scores = compute_diversity_scores(source_counts)
    log.info("  div_scores: %d persons", len(div_scores))


    conn = sqlite3.connect(str(EVENTS_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.execute("SELECT DISTINCT person_id FROM events")
    all_person_ids = [row[0] for row in cursor.fetchall()]
    log.info("events.db: %d distinct persons", len(all_person_ids))


    stats = {
        "total_persons": len(all_person_ids),
        "persons_above_0.5": 0,
        "persons_above_0.3": 0,
        "persons_above_0.1": 0,
        "persons_at_floor": 0,
        "events_updated": 0,
    }

    updates: list[tuple[float, str]] = []
    quality_map: dict[str, float] = {}

    for pid in all_person_ids:
        quality = compute_person_content_quality(
            pid, rel_scores, deep_scores, sig_scores, div_scores
        )
        quality_map[pid] = quality
        updates.append((quality, pid))

        if quality > 0.5:
            stats["persons_above_0.5"] += 1
        if quality > 0.3:
            stats["persons_above_0.3"] += 1
        if quality > 0.1:
            stats["persons_above_0.1"] += 1
        if quality <= 0.05:
            stats["persons_at_floor"] += 1

    if dry_run:
        log.info("[DRY RUN] Would update %d persons", len(updates))
    else:

        log.info("Updating events.db content_quality for %d persons...", len(updates))
        cursor = conn.executemany(
            "UPDATE events SET content_quality = ? WHERE person_id = ?",
            updates,
        )
        stats["events_updated"] = cursor.rowcount
        conn.commit()


        cursor = conn.execute("SELECT COUNT(*) FROM events WHERE content_quality IS NOT NULL")
        verified = cursor.fetchone()[0]
        log.info("Verified: %d events now have content_quality", verified)
        stats["events_updated"] = verified

    conn.close()

    elapsed = time.time() - t0
    log.info("Done in %.1fs", elapsed)


    if verbose:
        bridge_path = ENTITY_BRIDGE_PATH
        bridge: dict[str, str] = {}
        if bridge_path.exists():
            with open(bridge_path, encoding="utf-8") as f:
                bridge = json.load(f)

        pid_to_name: dict[str, str] = {}
        for name, pid in bridge.items():
            if pid.startswith("p_") and pid not in pid_to_name:
                pid_to_name[pid] = name

        print("\n── Per-person content quality breakdown (top 30) ──")
        sorted_q = sorted(quality_map.items(), key=lambda x: x[1], reverse=True)
        for pid, q in sorted_q[:30]:
            name = pid_to_name.get(pid, pid)
            rel = rel_scores.get(pid, 0)
            deep = deep_scores.get(pid, 0)
            sig = sig_scores.get(pid, 0)
            div = div_scores.get(pid, 0)
            print(
                f"  {name[:35]:<35s}  quality={q:.3f}  "
                f"[rel={rel:.2f} deep={deep:.2f} sig={sig:.2f} div={div:.2f}]"
            )


        # Optional spot-check: map a few {name: person_id} to verify from local config.
        key_persons: dict[str, str] = {}
        print("\n── Key persons validation ──")
        for name, pid in key_persons.items():
            q = quality_map.get(pid, -1)
            rel = rel_scores.get(pid, 0)
            deep = deep_scores.get(pid, 0)
            sig = sig_scores.get(pid, 0)
            div = div_scores.get(pid, 0)
            print(
                f"  {name:<25s}  quality={q:.3f}  "
                f"[rel={rel:.2f} deep={deep:.2f} sig={sig:.2f} div={div:.2f}]"
            )

    return stats





def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill content_quality in events.db from existing data sources"
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-person breakdown")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    stats = backfill_content_quality(dry_run=args.dry_run, verbose=args.verbose)

    print("\n── Summary ──")
    print(f"  Total persons:     {stats['total_persons']}")
    print(f"  Quality > 0.5:     {stats['persons_above_0.5']}")
    print(f"  Quality > 0.3:     {stats['persons_above_0.3']}")
    print(f"  Quality > 0.1:     {stats['persons_above_0.1']}")
    print(f"  At floor (0.05):   {stats['persons_at_floor']}")
    print(f"  Events updated:    {stats['events_updated']}")


if __name__ == "__main__":
    main()
