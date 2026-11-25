#!/usr/bin/env python3
""













from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    KNOWLEDGE_RELATIONSHIPS_DIR,
    PERSONIO_DIR,
    RQ_DIR,
)

log = logging.getLogger("rq-07")


def _load_interaction_dates(rq_dir: Path) -> dict[str, list[datetime]]:
    ""
    weights_file = rq_dir / "interaction-weights.parquet"
    if not weights_file.exists():
        return {}

    df = pd.read_parquet(weights_file)
    if "date" not in df.columns or "to_addr" not in df.columns:
        return {}

    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    result: dict[str, list[datetime]] = {}
    for person, group in df.groupby("to_addr"):
        dates = group["date_parsed"].dropna().tolist()
        if dates:
            result[str(person)] = sorted(dates)

    return result


def _load_previous_snapshots(rq_dir: Path) -> dict[str, dict]:
    ""
    snapshot_file = rq_dir / "deep-analysis-snapshot.json"
    if not snapshot_file.exists():
        return {}
    try:
        return json.loads(snapshot_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_snapshots(rq_dir: Path, snapshots: dict[str, dict]) -> None:
    ""
    snapshot_file = rq_dir / "deep-analysis-snapshot.json"
    snapshot_file.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="RQ-07: Deep relationship analysis")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--person", type=str, help="Analyze single person")
    parser.add_argument("--events-only", action="store_true", help="Skip interruption analysis")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rq_deep_analysis import analyze_interruption, build_timeline, detect_events
    from rq_type_detection import load_personio_index


    personio_index = load_personio_index(PERSONIO_DIR)
    interaction_dates = _load_interaction_dates(RQ_DIR)
    previous_snapshots = _load_previous_snapshots(RQ_DIR)


    if not KNOWLEDGE_RELATIONSHIPS_DIR.exists():
        log.warning("No relationship details found")
        return

    detail_files = sorted(KNOWLEDGE_RELATIONSHIPS_DIR.glob("*.json"))
    detail_files = [f for f in detail_files if f.name != "third-party-index.json"]

    log.info(
        "Loaded: %d relationships, %d previous snapshots, %d personio",
        len(detail_files),
        len(previous_snapshots),
        len(personio_index),
    )

    results = []
    cause_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    current_snapshots: dict[str, dict] = {}

    for detail_file in detail_files:
        person_id = detail_file.stem
        if args.person and args.person != person_id:
            continue

        try:
            rel = json.loads(detail_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        person_email = rel.get("person", person_id)
        dates = interaction_dates.get(person_email, [])
        previous = previous_snapshots.get(person_id)


        interruption = None
        if not args.events_only:
            interruption = analyze_interruption(
                person_email=person_email,
                relationship=rel,
                personio_index=personio_index,
                interaction_dates=dates,
            )
            cause = interruption.get("cause")
            if cause:
                cause_counts[cause] = cause_counts.get(cause, 0) + 1


        events = detect_events(rel, previous)
        for event in events:
            etype = event["type"]
            event_counts[etype] = event_counts.get(etype, 0) + 1


        timeline = build_timeline(rel, events, dates)

        results.append(
            {
                "person_id": person_id,
                "interruption": interruption,
                "events": events,
                "timeline": timeline,
            }
        )


        current_snapshots[person_id] = {
            "score": rel.get("score"),
            "state": rel.get("state"),
            "breakdown": rel.get("breakdown"),
            "relationship_type": rel.get("relationship_type"),
            "type_confidence": rel.get("type_confidence"),
        }

    if not results:
        log.warning("No results")
        return


    log.info("=" * 60)
    log.info("TOTAL: %d relationships analyzed", len(results))

    if cause_counts:
        log.info("")
        log.info("Interruption causes:")
        for cause, count in sorted(cause_counts.items(), key=lambda x: -x[1]):
            log.info("  %-25s %5d", cause, count)

    if event_counts:
        log.info("")
        log.info("Events detected:")
        for etype, count in sorted(event_counts.items(), key=lambda x: -x[1]):
            log.info("  %-25s %5d", etype, count)

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return


    KNOWLEDGE_RELATIONSHIPS_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    for result in results:
        person_id = result["person_id"]
        detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{person_id}.json"
        detail = {}
        if detail_file.exists():
            try:
                detail = json.loads(detail_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        if result["interruption"] and result["interruption"].get("cause"):
            detail["interruption"] = result["interruption"]

        if result["events"]:
            detail["events"] = result["events"]

        if result["timeline"]:
            detail["milestones"] = result["timeline"]

        detail["deep_analysis_at"] = datetime.now(UTC).isoformat()
        detail_file.write_text(json.dumps(detail, indent=2), encoding="utf-8")
        updated += 1

    log.info("Updated %d relationship detail JSONs", updated)


    RQ_DIR.mkdir(parents=True, exist_ok=True)
    _save_snapshots(RQ_DIR, current_snapshots)
    log.info("Saved %d snapshots for next run comparison", len(current_snapshots))


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-07-deep-analysis", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
