#!/usr/bin/env python3
"""Looks for duplicate people in the knowledge base (knowledge/entities/person).

Finds exact email clusters, fuzzy name clusters, composite entities ("A, B" or "A & B") and skeletons with
almost no facts, prints the estimated merge potential and saves knowledge/entity-dedup-report.json.
It changes no entity.
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from rapidfuzz import fuzz

from sbk_config import KNOWLEDGE_DIR, KNOWLEDGE_ENTITIES_DIR, safe_write_json




ENTITY_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
REPORT_PATH = KNOWLEDGE_DIR / "entity-dedup-report.json"

NAME_SIM_THRESHOLD = 90
SKELETON_FACT_LIMIT = 3


COMPOSITE_PATTERNS = re.compile(
    r"""
    ,                   # comma separator
    | \s/\s             # slash with spaces
    | \s&\s             # ampersand with spaces
    | \sand\s            # " and "
    """,
    re.VERBOSE | re.IGNORECASE,
)


def load_entities() -> list[dict]:
    ""
    entities = []
    total = 0
    archived = 0

    files = sorted(ENTITY_DIR.glob("person_*.json"))
    print(f"Loading {len(files)} entity files...")

    for fp in files:
        total += 1
        try:
            with open(fp) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: Failed to load {fp.name}: {e}", file=sys.stderr)
            continue

        canonical_name = data.get("canonical_name", "")
        entity_id = data.get("entity_id", fp.stem)
        facts = data.get("facts", [])

        if canonical_name.startswith("ARCHIVED:"):
            archived += 1
            continue


        emails = set()
        for fact in facts:
            attr = fact.get("attribute", "")
            val = str(fact.get("value", ""))
            if attr == "contact.email" and "@" in val:
                emails.add(val.strip().lower())

        entities.append(
            {
                "id": entity_id,
                "name": canonical_name,
                "facts": len(facts),
                "emails": list(emails),
                "file": fp.name,
            }
        )

    print(f"  Total files: {total}, archived: {archived}, active: {len(entities)}")
    return entities, total, archived


def find_email_clusters(entities: list[dict]) -> list[dict]:
    ""
    email_to_entities: dict[str, list[dict]] = defaultdict(list)

    for ent in entities:
        for email in ent["emails"]:
            email_to_entities[email].append(
                {"id": ent["id"], "name": ent["name"], "facts": ent["facts"]}
            )

    clusters = []
    for email, ents in sorted(email_to_entities.items()):
        if len(ents) >= 2:

            seen_ids = set()
            unique_ents = []
            for e in ents:
                if e["id"] not in seen_ids:
                    seen_ids.add(e["id"])
                    unique_ents.append(e)
            if len(unique_ents) >= 2:
                clusters.append({"email": email, "entities": unique_ents})

    return clusters


def find_name_clusters(entities: list[dict]) -> list[dict]:
    ""

    blocks: dict[str, list[dict]] = defaultdict(list)
    for ent in entities:
        name = ent["name"].strip()
        if not name:
            continue

        key = re.sub(r"[^a-z]", "", name.lower()[:3])
        if len(key) >= 2:
            blocks[key].append(ent)


    for ent in entities:
        name = ent["name"].strip()
        if not name:
            continue
        words = name.split()
        if len(words) > 1:
            last_key = re.sub(r"[^a-z]", "", words[-1].lower()[:3])
            if len(last_key) >= 2 and last_key != re.sub(r"[^a-z]", "", name.lower()[:3]):
                blocks[last_key].append(ent)

    print(f"  Name blocking: {len(blocks)} blocks, sizes: ", end="")
    sizes = [len(v) for v in blocks.values()] or [0]
    print(
        f"min={min(sizes)}, max={max(sizes)}, "
        f"avg={sum(sizes) / len(sizes):.1f}, "
        f"blocks>50={sum(1 for s in sizes if s > 50)}"
    )



    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pair_scores: dict[tuple, int] = {}
    comparisons = 0

    for block_key, block_ents in blocks.items():
        if len(block_ents) > 500:

            continue
        for i in range(len(block_ents)):
            for j in range(i + 1, len(block_ents)):
                a, b = block_ents[i], block_ents[j]
                if a["id"] == b["id"]:
                    continue
                key = tuple(sorted([a["id"], b["id"]]))
                if key in pair_scores:
                    continue

                comparisons += 1
                score = fuzz.token_sort_ratio(a["name"], b["name"])
                pair_scores[key] = score

                if score >= NAME_SIM_THRESHOLD:
                    union(a["id"], b["id"])

    print(f"  Pairwise comparisons: {comparisons:,}")


    cluster_map: dict[str, list] = defaultdict(list)
    entity_by_id = {e["id"]: e for e in entities}


    matched_ids = set()
    for (id_a, id_b), score in pair_scores.items():
        if score >= NAME_SIM_THRESHOLD:
            matched_ids.add(id_a)
            matched_ids.add(id_b)

    for eid in matched_ids:
        root = find(eid)
        cluster_map[root].append(eid)

    clusters = []
    for root, member_ids in sorted(cluster_map.items(), key=lambda x: -len(x[1])):
        if len(member_ids) < 2:
            continue
        members = []
        for mid in sorted(member_ids):
            ent = entity_by_id.get(mid)
            if ent:
                members.append({"id": ent["id"], "name": ent["name"], "facts": ent["facts"]})

        scores = []
        for i in range(len(member_ids)):
            for j in range(i + 1, len(member_ids)):
                key = tuple(sorted([member_ids[i], member_ids[j]]))
                if key in pair_scores:
                    scores.append(pair_scores[key])
        avg_score = sum(scores) / len(scores) if scores else 0


        best = max(members, key=lambda m: m["facts"])
        clusters.append(
            {
                "cluster_name": best["name"],
                "avg_score": round(avg_score, 1),
                "entity_count": len(members),
                "entities": members,
            }
        )

    clusters.sort(key=lambda c: -c["entity_count"])
    return clusters


def find_composite_entities(entities: list[dict]) -> list[dict]:
    ""
    results = []
    for ent in entities:
        name = ent["name"]
        if COMPOSITE_PATTERNS.search(name):
            results.append({"id": ent["id"], "name": name, "facts": ent["facts"]})
    results.sort(key=lambda e: -e["facts"])
    return results


def find_skeleton_entities(entities: list[dict]) -> list[dict]:
    ""
    results = []
    for ent in entities:
        if ent["facts"] <= SKELETON_FACT_LIMIT:
            results.append({"id": ent["id"], "name": ent["name"], "facts": ent["facts"]})
    results.sort(key=lambda e: (e["facts"], e["name"]))
    return results


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    if not any(ENTITY_DIR.glob("person_*.json")):
        print(f"No person entities yet in {ENTITY_DIR}. Run the pipeline first.", file=sys.stderr)
        sys.exit(1)
    t0 = time.time()
    print("=" * 70)
    print("SBK Entity Deduplication Analysis")
    print("=" * 70)
    print()


    entities, total_files, archived_count = load_entities()
    active_count = len(entities)
    with_email = sum(1 for e in entities if e["emails"])

    print()
    print("-" * 70)
    print("Level 1: Exact email match (CERTAIN duplicates)")
    print("-" * 70)
    email_clusters = find_email_clusters(entities)
    email_ent_count = sum(len(c["entities"]) for c in email_clusters)
    print(f"  Found {len(email_clusters)} email clusters involving {email_ent_count} entities")
    if email_clusters:
        print("  Top 10 email clusters:")
        for c in email_clusters[:10]:
            names = [e["name"] for e in c["entities"]]
            print(f"    {c['email']}: {names}")

    print()
    print("-" * 70)
    print("Level 2: High name similarity (TSR >= 90, with blocking)")
    print("-" * 70)
    name_clusters = find_name_clusters(entities)
    name_ent_count = sum(c["entity_count"] for c in name_clusters)
    print(f"  Found {len(name_clusters)} name clusters involving {name_ent_count} entities")

    print()
    print("-" * 70)
    print("Level 3: Composite/group entities")
    print("-" * 70)
    composites = find_composite_entities(entities)
    print(f"  Found {len(composites)} composite entities")
    if composites:
        print("  Top 20:")
        for c in composites[:20]:
            print(f"    [{c['facts']:3d} facts] {c['name']}")

    print()
    print("-" * 70)
    print("Level 4: Skeleton entities (<=3 facts)")
    print("-" * 70)
    skeletons = find_skeleton_entities(entities)
    print(f"  Found {len(skeletons)} skeleton entities out of {active_count} active")

    dist = defaultdict(int)
    for s in skeletons:
        dist[s["facts"]] += 1
    for k in sorted(dist):
        print(f"    {k} facts: {dist[k]} entities")


    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stats": {
            "total_entities": total_files,
            "archived": archived_count,
            "active": active_count,
            "with_email": with_email,
            "email_clusters": len(email_clusters),
            "email_cluster_entities": email_ent_count,
            "name_clusters": len(name_clusters),
            "name_cluster_entities": name_ent_count,
            "composite_names": len(composites),
            "skeleton_entities": len(skeletons),
        },
        "email_clusters": email_clusters,
        "name_clusters": name_clusters,
        "composite_entities": composites,
        "skeleton_entities": skeletons,
    }


    safe_write_json(REPORT_PATH, report)
    print(f"\nReport saved to: {REPORT_PATH}")

    elapsed = time.time() - t0


    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total entity files:    {total_files:>8,}")
    print(f"  Archived:              {archived_count:>8,}")
    print(f"  Active:                {active_count:>8,}")
    print(f"  With email:            {with_email:>8,}")
    print()
    print(f"  Email clusters:        {len(email_clusters):>8,}  ({email_ent_count:,} entities)")
    print(f"  Name clusters:         {len(name_clusters):>8,}  ({name_ent_count:,} entities)")
    print(f"  Composite entities:    {len(composites):>8,}")
    print(f"  Skeleton entities:     {len(skeletons):>8,}")
    print()


    email_ids = set()
    for c in email_clusters:
        for e in c["entities"]:
            email_ids.add(e["id"])
    name_ids = set()
    for c in name_clusters:
        for e in c["entities"]:
            name_ids.add(e["id"])
    composite_ids = {c["id"] for c in composites}
    skeleton_ids = {s["id"] for s in skeletons}

    overlap_email_name = email_ids & name_ids
    overlap_any = email_ids | name_ids | composite_ids | skeleton_ids
    print(f"  Overlap email+name:    {len(overlap_email_name):>8,}")
    print(f"  Unique entities in ANY problem bucket: {len(overlap_any):,}")
    print(f"  Clean entities:        {active_count - len(overlap_any):>8,}")
    print()

    if name_clusters:
        print("  TOP 20 LARGEST NAME CLUSTERS:")
        for i, c in enumerate(name_clusters[:20], 1):
            names = [e["name"] for e in c["entities"][:5]]
            extra = f" (+{c['entity_count'] - 5} more)" if c["entity_count"] > 5 else ""
            print(
                f"    {i:2d}. [{c['entity_count']:3d} entities, "
                f"avg_score={c['avg_score']}] "
                f"{', '.join(names)}{extra}"
            )

    print()

    dedup_from_email = email_ent_count - len(email_clusters)
    dedup_from_name = name_ent_count - len(name_clusters)
    print("  ESTIMATED DEDUP POTENTIAL:")
    print(f"    From email clusters:   ~{dedup_from_email:,} entities to merge")
    print(f"    From name clusters:    ~{dedup_from_name:,} entities to merge")
    print(f"    Composite to split:    ~{len(composites):,} entities")
    print(f"    Skeletons to review:   ~{len(skeletons):,} entities")

    print(f"\n  Analysis completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
