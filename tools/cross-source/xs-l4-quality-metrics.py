#!/usr/bin/env python3
"""Quality metrics of the people in the knowledge base: duplicate, composite and skeleton rates, facts per entity,
confidence distribution, multi-source rate, review queue; saves a snapshot, shows the trend and raises alerts
above the thresholds.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

log = logging.getLogger("sbk-l4-quality-metrics")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ALERTS_FILE = QUALITY_METRICS_DIR / "alerts.jsonl"


_COMPOSITE_RE = re.compile(
    r"""
    ,\s*[A-Z]           |  # comma followed by capital letter
    \s+/\s+             |  # slash surrounded by spaces
    \s+&\s+             |  # ampersand surrounded by spaces
    \band\b             |  # word "and"
    \be\b(?=\s+[A-Z])      # Italian "e" followed by capital
    """,
    re.VERBOSE,
)


ALERT_RULES = [
    {
        "metric": "duplicate_rate",
        "op": ">",
        "threshold": 0.20,
        "severity": "critical",
        "msg": "Duplicate rate above 20%",
    },
    {
        "metric": "composite_rate",
        "op": ">",
        "threshold": 0.25,
        "severity": "warning",
        "msg": "Composite rate above 25%",
    },
    {
        "metric": "avg_facts",
        "op": "<",
        "threshold": 3.0,
        "severity": "warning",
        "msg": "Average facts per entity below 3",
    },
    {
        "metric": "review_queue_size",
        "op": ">",
        "threshold": 500,
        "severity": "warning",
        "msg": "Review queue has 500+ items",
    },
]





def load_person_entities() -> list[dict]:
    ""
    if not PERSON_DIR.exists():
        log.warning("Person entity directory not found: %s", PERSON_DIR)
        return []

    entities = []
    errors = 0
    for f in PERSON_DIR.iterdir():
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entities.append(data)
        except (json.JSONDecodeError, OSError) as e:
            errors += 1
            if errors <= 5:
                log.warning("Error loading %s: %s", f.name, e)

    if errors > 5:
        log.warning("... and %d more entity load errors", errors - 5)

    log.info("Loaded %d person entities (%d errors)", len(entities), errors)
    return entities





def calc_duplicate_rate(entities: list[dict]) -> tuple[float, int, int]:
    ""
    name_groups: dict[str, list[str]] = defaultdict(list)
    for e in entities:
        name = (e.get("canonical_name") or "").strip().lower()
        if name:
            name_groups[name].append(e.get("entity_id", ""))

    duplicates = sum(len(ids) - 1 for ids in name_groups.values() if len(ids) > 1)
    total = len(entities)
    rate = duplicates / total if total > 0 else 0.0
    return rate, duplicates, total


def calc_composite_rate(entities: list[dict]) -> tuple[float, int]:
    ""
    composites = 0
    for e in entities:
        name = e.get("canonical_name") or ""
        if _COMPOSITE_RE.search(name):
            composites += 1
    rate = composites / len(entities) if entities else 0.0
    return rate, composites


def calc_skeleton_rate(entities: list[dict]) -> tuple[float, int]:
    ""
    skeletons = sum(1 for e in entities if len(e.get("facts", [])) <= 1)
    rate = skeletons / len(entities) if entities else 0.0
    return rate, skeletons


def calc_avg_facts(entities: list[dict]) -> float:
    ""
    if not entities:
        return 0.0
    total_facts = sum(len(e.get("facts", [])) for e in entities)
    return total_facts / len(entities)


def calc_confidence_distribution(entities: list[dict]) -> dict[str, int]:
    ""
    buckets = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, "0.85-1.0": 0}
    for e in entities:
        for fact in e.get("facts", []):
            conf = fact.get("confidence", 0.5)
            if conf < 0.3:
                buckets["0.0-0.3"] += 1
            elif conf < 0.5:
                buckets["0.3-0.5"] += 1
            elif conf < 0.7:
                buckets["0.5-0.7"] += 1
            elif conf < 0.85:
                buckets["0.7-0.85"] += 1
            else:
                buckets["0.85-1.0"] += 1
    return buckets


def calc_multi_source_rate(entities: list[dict]) -> tuple[float, int]:
    ""
    multi = 0
    for e in entities:
        sources = {f.get("source_type") for f in e.get("facts", []) if f.get("source_type")}
        if len(sources) >= 2:
            multi += 1
    rate = multi / len(entities) if entities else 0.0
    return rate, multi


def calc_review_queue_size() -> int:
    ""
    review_file = ENRICHED_DIR / "entity-review.json"
    if not review_file.exists():
        return 0
    try:
        data = json.loads(review_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data.get("pending", data.get("items", [])))
    except (json.JSONDecodeError, OSError):
        pass
    return 0


def calc_entity_count_delta(prev_snapshot: dict | None, current_total: int) -> int:
    ""
    if not prev_snapshot:
        return 0
    prev_total = prev_snapshot.get("entity_count", current_total)
    return current_total - prev_total





def load_latest_snapshot() -> dict | None:
    ""
    latest = QUALITY_METRICS_DIR / "latest.json"
    if latest.exists():
        try:
            return json.loads(latest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_snapshot(metrics: dict, trigger: str = "") -> Path:
    ""
    QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    snapshot = {
        "timestamp": datetime.now(UTC).isoformat(),
        "trigger": trigger,
        **metrics,
    }


    ts_file = QUALITY_METRICS_DIR / f"quality-metrics-{ts}.json"
    safe_write_json(ts_file, snapshot)


    latest = QUALITY_METRICS_DIR / "latest.json"
    safe_write_json(latest, snapshot)

    log.info("Snapshot saved: %s", ts_file.name)
    return ts_file


def check_alerts(metrics: dict) -> list[dict]:
    ""
    alerts = []
    for rule in ALERT_RULES:
        value = metrics.get(rule["metric"])
        if value is None:
            continue

        fired = False
        if (
            rule["op"] == ">"
            and value > rule["threshold"]
            or rule["op"] == "<"
            and value < rule["threshold"]
        ):
            fired = True

        if fired:
            alert = {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": rule["severity"],
                "metric": rule["metric"],
                "value": round(value, 4),
                "threshold": rule["threshold"],
                "message": rule["msg"],
            }
            alerts.append(alert)
            log.warning(
                "ALERT [%s]: %s (value=%.4f, threshold=%.4f)",
                rule["severity"].upper(),
                rule["msg"],
                value,
                rule["threshold"],
            )

    if alerts:
        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_FILE, "a", encoding="utf-8") as f:
            for a in alerts:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")

    return alerts





def display_metrics(snapshot: dict):
    ""
    print(f"\n{'=' * 60}")
    print(f"  Entity Quality Metrics — {snapshot.get('timestamp', '?')[:19]}")
    if snapshot.get("trigger"):
        print(f"  Trigger: {snapshot['trigger']}")
    print(f"{'=' * 60}")
    print(f"  Entities:        {snapshot.get('entity_count', '?'):,}")
    print(f"  Total facts:     {snapshot.get('total_facts', '?'):,}")
    print(f"  Avg facts:       {snapshot.get('avg_facts', 0):.1f}")
    print()
    print(
        f"  Duplicate rate:  {snapshot.get('duplicate_rate', 0):.1%}  ({snapshot.get('duplicate_count', '?')} dupes)"
    )
    print(
        f"  Composite rate:  {snapshot.get('composite_rate', 0):.1%}  ({snapshot.get('composite_count', '?')} composites)"
    )
    print(
        f"  Skeleton rate:   {snapshot.get('skeleton_rate', 0):.1%}  ({snapshot.get('skeleton_count', '?')} skeletons)"
    )
    print(
        f"  Multi-source:    {snapshot.get('multi_source_rate', 0):.1%}  ({snapshot.get('multi_source_count', '?')} entities)"
    )
    print(f"  Review queue:    {snapshot.get('review_queue_size', 0)}")
    print(f"  Count delta:     {snapshot.get('entity_count_delta', 0):+d}")
    print()
    conf = snapshot.get("confidence_distribution", {})
    if conf:
        print("  Confidence distribution:")
        for bucket, count in conf.items():
            print(f"    {bucket}: {count:,}")
    print(f"{'=' * 60}\n")


def display_trend(days: int = 7):
    ""
    if not QUALITY_METRICS_DIR.exists():
        print("No snapshots found.")
        return

    snapshots = sorted(QUALITY_METRICS_DIR.glob("quality-metrics-*.json"))
    if not snapshots:
        print("No snapshots found.")
        return

    snapshots = snapshots[-days:]
    print(
        f"\n{'Timestamp':<22} {'Entities':>8} {'Dupes%':>7} {'Comp%':>7} {'Avg':>6} {'MultiSrc':>8}"
    )
    print("-" * 65)
    for sp in snapshots:
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            ts = data.get("timestamp", "?")[:19]
            ent = data.get("entity_count", 0)
            dup = data.get("duplicate_rate", 0)
            comp = data.get("composite_rate", 0)
            avg = data.get("avg_facts", 0)
            multi = data.get("multi_source_rate", 0)
            print(f"  {ts:<20} {ent:>8,} {dup:>6.1%} {comp:>6.1%} {avg:>6.1f} {multi:>7.1%}")
        except (json.JSONDecodeError, OSError):
            continue
    print()





def calculate_all_metrics(entities: list[dict], prev_snapshot: dict | None) -> dict:
    ""
    dup_rate, dup_count, total = calc_duplicate_rate(entities)
    comp_rate, comp_count = calc_composite_rate(entities)
    skel_rate, skel_count = calc_skeleton_rate(entities)
    avg = calc_avg_facts(entities)
    conf_dist = calc_confidence_distribution(entities)
    multi_rate, multi_count = calc_multi_source_rate(entities)
    review_size = calc_review_queue_size()
    total_facts = sum(len(e.get("facts", [])) for e in entities)
    delta = calc_entity_count_delta(prev_snapshot, total)

    return {
        "entity_count": total,
        "total_facts": total_facts,
        "duplicate_rate": round(dup_rate, 4),
        "duplicate_count": dup_count,
        "composite_rate": round(comp_rate, 4),
        "composite_count": comp_count,
        "skeleton_rate": round(skel_rate, 4),
        "skeleton_count": skel_count,
        "avg_facts": round(avg, 2),
        "confidence_distribution": conf_dist,
        "multi_source_rate": round(multi_rate, 4),
        "multi_source_count": multi_count,
        "review_queue_size": review_size,
        "entity_count_delta": delta,
    }


def main():
    parser = argparse.ArgumentParser(description="L4-MONITOR: Entity Quality Metrics")
    parser.add_argument("--show-latest", action="store_true", help="Display latest snapshot")
    parser.add_argument("--trend", type=int, metavar="N", help="Show trend from last N snapshots")
    parser.add_argument("--trigger", type=str, default="", help="Tag for this snapshot")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.show_latest:
        snapshot = load_latest_snapshot()
        if snapshot:
            display_metrics(snapshot)
        else:
            print("No snapshots found. Run without --show-latest first.")
        return

    if args.trend:
        display_trend(args.trend)
        return


    log.info("Loading person entities...")
    entities = load_person_entities()
    if not entities:
        log.error("No entities found. Cannot calculate metrics.")
        sys.exit(1)

    prev = load_latest_snapshot()
    log.info("Calculating metrics...")
    metrics = calculate_all_metrics(entities, prev)


    save_snapshot(metrics, trigger=args.trigger)


    alerts = check_alerts(metrics)


    display_metrics(
        {**metrics, "timestamp": datetime.now(UTC).isoformat(), "trigger": args.trigger}
    )

    if alerts:
        log.info("%d alert(s) fired", len(alerts))
    else:
        log.info("No alerts fired")


if __name__ == "__main__":
    main()
