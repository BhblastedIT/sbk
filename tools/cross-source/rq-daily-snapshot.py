#!/usr/bin/env python3
"""Writes today's snapshot of the relationship scores from the event store, so the scores can be compared day by
day (--dry to only show the stats).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from rq_event_store import EventStore
from rq_scoring_v4 import score_all_v4, score_person_v4

from sbk_config import DATA_ROOT

log = logging.getLogger("rq.daily_snapshot")


def main() -> None:
    parser = argparse.ArgumentParser(description="RQV4 daily score snapshot")
    parser.add_argument(
        "--db", type=str, default=None, help="Path to DB (default: ~/.sbk-data/rq/events.db)"
    )
    parser.add_argument("--dry", action="store_true", help="Dry run: show stats but don't write")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )





    if not os.environ.get("SBK_CODA_RUN"):
        import un_run_alla_volta

        if chi := un_run_alla_volta.chi_gira():
            log.warning(
                "Snapshot skipped tonight: %s is already running (lock held). The rqv4_snapshot stage of the re-read does it.",
                ", ".join(chi),
            )
            return

    store = EventStore(db_path=args.db)


    if not store.db_path.exists():
        log.warning("Event store DB not found at %s — creating empty DB", store.db_path)
        store.create_db()


    stale = store.get_stale_person_ids()
    log.info("Found %d stale scores to recompute", len(stale))

    if stale and not args.dry:
        from rq_scoring_blocklist import is_blocked, load_blocklist

        blocklist = load_blocklist()
        for pid in stale:
            if is_blocked(pid, blocklist):
                continue
            result = score_person_v4(pid, store=store)
            store.update_cache(
                pid,
                {
                    "score": result.score,
                    "confidence": result.confidence,
                    "rel_type": result.rel_type,
                    "dunbar_circle": result.dunbar_circle,
                    "dims": result.dims,
                    "momentum": result.momentum,
                    "event_count": result.event_count,
                    "last_event_at": result.last_event_at,
                    "events_7d": result.events_7d,
                    "events_30d": result.events_30d,
                    "events_90d": result.events_90d,
                },
            )
        log.info("Recomputed %d stale scores", len(stale))


    all_pids = store.get_all_person_ids()
    cached = store.get_all_cached_scores()

    if len(all_pids) > 0 and len(cached) < len(all_pids) * 0.5:
        log.info(
            "Cache sparse (%d cached / %d total persons = %.0f%%), running full score_all_v4",
            len(cached),
            len(all_pids),
            len(cached) / len(all_pids) * 100 if all_pids else 0,
        )
        if not args.dry:
            score_all_v4(store=store, use_cache=False)
    else:
        log.info("Cache healthy: %d cached / %d total persons", len(cached), len(all_pids))


    if not args.dry:
        snapshot_count = store.snapshot_daily()
        log.info("Snapshot written: %d records", snapshot_count)
    else:
        log.info("[DRY RUN] Would snapshot %d cached scores", len(cached))


    if not args.dry:
        try:
            from rq_score_history import compute_score_diff

            current_df = store.get_all_cached_scores_df()
            if current_df is not None and not current_df.empty:
                history_path = DATA_ROOT / "rq" / "rq-score-history.parquet"
                diff = compute_score_diff(current_df, history_path)
                big_movers = (
                    diff[diff["rank_delta"].abs() > 20]
                    if "rank_delta" in diff.columns
                    else diff.head(0)
                )
                if len(big_movers) > 0:
                    log.warning(
                        "Score drift detected: %d people with rank change > 20",
                        len(big_movers),
                    )
                    for _, row in big_movers.head(5).iterrows():
                        log.warning(
                            "  %s: score %.1f→%.1f (rank %+d)",
                            row.get("person_id", "?"),
                            row.get("prev_score", 0),
                            row.get("curr_score", 0),
                            int(row.get("rank_delta", 0)),
                        )
        except Exception as e:
            log.debug("Score drift check skipped: %s", e)


    stats = store.stats()
    log.info(
        "Done. Events: %d, Cached scores: %d (%d stale), History entries: %d days",
        stats.get("total_events", 0),
        stats.get("cached_scores", 0),
        stats.get("stale_scores", 0),
        stats.get("history_days", 0),
    )


if __name__ == "__main__":
    main()
