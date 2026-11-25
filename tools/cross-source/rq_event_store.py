""


























from __future__ import annotations

import json
import logging
import sqlite3
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import RQ_DIR  # noqa: E402

log = logging.getLogger("rq.event_store")



DB_PATH = RQ_DIR / "events.db"



EVENT_WEIGHTS: dict[str, float] = {

    "meeting_1on1": 2.5,
    "call_1on1": 2.0,

    "email_reply_received": 1.3,
    "email_1to1_received": 1.0,
    "slack_dm": 0.90,

    "email_reply_sent": 0.70,
    "email_1to1_sent": 0.60,

    "meeting_group_small": 0.50,
    "call_group": 0.40,
    "slack_thread_reply": 0.40,
    "whatsapp_dm": 0.30,
    "email_small_group": 0.25,
    "slack_mention": 0.20,

    "meeting_group_large": 0.10,
    "email_cc": 0.05,
    "whatsapp_small_group": 0.03,
    "whatsapp_media": 0.08,
    "slack_channel_msg": 0.05,
    "email_newsletter": 0.00,

    "commitment_made": 0.05,
    "commitment_fulfilled": 0.30,
    "introduction_made": 0.50,
    "introduction_received": 0.20,
    "contract_signed": 0.70,
    "negative_event": 0.0,
}

EVENT_HALF_LIVES: dict[str, int] = {
    "email_1to1_sent": 30,
    "email_1to1_received": 30,
    "email_reply_sent": 30,
    "email_reply_received": 45,
    "email_small_group": 21,
    "email_cc": 14,
    "meeting_1on1": 90,
    "meeting_group_small": 45,
    "meeting_group_large": 30,
    "slack_dm": 21,
    "slack_mention": 14,
    "slack_thread_reply": 21,
    "slack_channel_msg": 14,
    "whatsapp_dm": 45,
    "whatsapp_small_group": 30,
    "call_1on1": 90,
    "call_group": 45,
    "introduction_made": 180,
    "introduction_received": 120,
    "contract_signed": 365,
    "commitment_made": 90,
    "commitment_fulfilled": 180,
}

EVENT_DIM_CONTRIBUTIONS: dict[str, dict[str, float]] = {
    "email_1to1_sent": {
        "intimacy": 0.1,
        "interaction_quality": 0.8,
        "communication_quality": 0.5,
        "structural": 0.1,
        "trust": 0.1,
    },
    "email_1to1_received": {
        "intimacy": 0.1,
        "interaction_quality": 0.8,
        "communication_quality": 0.5,
        "structural": 0.1,
        "trust": 0.1,
    },
    "email_reply_sent": {
        "intimacy": 0.15,
        "interaction_quality": 0.9,
        "communication_quality": 0.6,
        "structural": 0.1,
        "trust": 0.15,
    },
    "email_reply_received": {
        "intimacy": 0.15,
        "interaction_quality": 0.9,
        "communication_quality": 0.6,
        "structural": 0.1,
        "trust": 0.15,
    },
    "email_small_group": {
        "intimacy": 0.0,
        "interaction_quality": 0.4,
        "communication_quality": 0.2,
        "structural": 0.3,
        "trust": 0.05,
    },
    "email_cc": {
        "intimacy": 0.0,
        "interaction_quality": 0.1,
        "communication_quality": 0.0,
        "structural": 0.5,
        "trust": 0.0,
    },
    "meeting_1on1": {
        "intimacy": 0.6,
        "interaction_quality": 0.7,
        "communication_quality": 0.8,
        "structural": 0.3,
        "trust": 0.5,
    },
    "meeting_group_small": {
        "intimacy": 0.2,
        "interaction_quality": 0.5,
        "communication_quality": 0.4,
        "structural": 0.5,
        "trust": 0.2,
    },
    "meeting_group_large": {
        "intimacy": 0.0,
        "interaction_quality": 0.2,
        "communication_quality": 0.1,
        "structural": 0.4,
        "trust": 0.1,
    },
    "slack_dm": {
        "intimacy": 0.5,
        "interaction_quality": 0.7,
        "communication_quality": 0.4,
        "structural": 0.1,
        "trust": 0.2,
    },
    "slack_mention": {
        "intimacy": 0.0,
        "interaction_quality": 0.3,
        "communication_quality": 0.1,
        "structural": 0.4,
        "trust": 0.1,
    },
    "slack_thread_reply": {
        "intimacy": 0.2,
        "interaction_quality": 0.6,
        "communication_quality": 0.3,
        "structural": 0.2,
        "trust": 0.15,
    },
    "slack_channel_msg": {
        "intimacy": 0.0,
        "interaction_quality": 0.2,
        "communication_quality": 0.1,
        "structural": 0.3,
        "trust": 0.05,
    },
    "whatsapp_dm": {
        "intimacy": 0.2,
        "interaction_quality": 0.3,
        "communication_quality": 0.1,
        "structural": 0.05,
        "trust": 0.05,
    },
    "whatsapp_small_group": {
        "intimacy": 0.05,
        "interaction_quality": 0.1,
        "communication_quality": 0.05,
        "structural": 0.15,
        "trust": 0.02,
    },
    "whatsapp_media": {
        "intimacy": 0.15,
        "interaction_quality": 0.1,
        "communication_quality": 0.05,
        "structural": 0.05,
        "trust": 0.05,
    },
    "call_1on1": {
        "intimacy": 0.6,
        "interaction_quality": 0.7,
        "communication_quality": 0.8,
        "structural": 0.3,
        "trust": 0.5,
    },
    "call_group": {
        "intimacy": 0.2,
        "interaction_quality": 0.5,
        "communication_quality": 0.4,
        "structural": 0.5,
        "trust": 0.2,
    },
    "introduction_made": {
        "intimacy": 0.1,
        "interaction_quality": 0.2,
        "communication_quality": 0.0,
        "structural": 0.9,
        "trust": 0.6,
    },
    "introduction_received": {
        "intimacy": 0.1,
        "interaction_quality": 0.2,
        "communication_quality": 0.0,
        "structural": 0.7,
        "trust": 0.3,
    },
    "contract_signed": {
        "intimacy": 0.0,
        "interaction_quality": 0.1,
        "communication_quality": 0.0,
        "structural": 0.3,
        "trust": 0.9,
    },
    "commitment_made": {
        "intimacy": 0.1,
        "interaction_quality": 0.1,
        "communication_quality": 0.0,
        "structural": 0.1,
        "trust": 0.7,
    },
    "commitment_fulfilled": {
        "intimacy": 0.1,
        "interaction_quality": 0.1,
        "communication_quality": 0.0,
        "structural": 0.1,
        "trust": 1.0,
    },
}

VALID_SOURCES = frozenset(
    {
        "gmail",
        "slack",
        "attio",
        "whatsapp",
        "calendar",
        "tactiq",
        "plaud",
        "notion",
        "knowledge",
    }
)



_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    signal_weight REAL NOT NULL DEFAULT 1.0,
    dim_intimacy REAL DEFAULT 0.0,
    dim_interaction_quality REAL DEFAULT 0.0,
    dim_communication_quality REAL DEFAULT 0.0,
    dim_structural REAL DEFAULT 0.0,
    dim_trust REAL DEFAULT 0.0,
    content_quality REAL,
    is_negative INTEGER DEFAULT 0,
    severity_level INTEGER DEFAULT 0,
    raw_metadata TEXT,
    source_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_events_person ON events(person_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

CREATE TABLE IF NOT EXISTS score_cache (
    person_id TEXT PRIMARY KEY,
    score REAL NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    rel_type TEXT,
    dunbar_circle TEXT,
    dims_json TEXT,
    momentum TEXT,
    computed_at TEXT NOT NULL,
    stale INTEGER DEFAULT 0,
    event_count INTEGER,
    last_event_at TEXT,
    events_7d INTEGER DEFAULT 0,
    events_30d INTEGER DEFAULT 0,
    events_90d INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cache_stale ON score_cache(stale);
CREATE INDEX IF NOT EXISTS idx_cache_circle ON score_cache(dunbar_circle);

CREATE TABLE IF NOT EXISTS score_history (
    person_id TEXT NOT NULL,
    date TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL,
    dunbar_circle TEXT,
    event_count_30d INTEGER,
    event_count_90d INTEGER,
    PRIMARY KEY (person_id, date)
);
"""

_PRAGMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA cache_size=-20000;
"""





class EventStore:
    ""

    def __init__(self, db_path: str | Path | None = None) -> None:
        ""





        self.db_path = Path(db_path) if db_path else DB_PATH

    @contextmanager
    def _conn(self, *, readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
        ""




        conn = sqlite3.connect(
            f"file:{self.db_path}{'?mode=ro' if readonly else ''}",
            uri=True,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size=-20000")
        try:
            yield conn
        finally:
            conn.close()



    def create_db(self) -> None:
        ""




        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.executescript(_PRAGMA_SQL)
            conn.commit()

        log.info("Event store initialized at %s", self.db_path)



    def write_events(self, events: list[dict[str, Any]]) -> int:
        ""












        if not events:
            return 0

        inserted = 0
        with self._conn() as conn:
            for ev in events:

                source_id = ev.get("source_id") or (
                    f"{ev['person_id']}_{ev['timestamp']}_{ev['event_type']}"
                )


                raw_meta = ev.get("raw_metadata")
                if isinstance(raw_meta, dict):
                    raw_meta = json.dumps(raw_meta, ensure_ascii=False)

                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO events (
                            person_id, timestamp, event_type, source,
                            signal_weight,
                            dim_intimacy, dim_interaction_quality,
                            dim_communication_quality, dim_structural, dim_trust,
                            content_quality, is_negative, severity_level,
                            raw_metadata, source_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ev["person_id"],
                            ev["timestamp"],
                            ev["event_type"],
                            ev["source"],
                            ev.get("signal_weight", EVENT_WEIGHTS.get(ev["event_type"], 1.0)),
                            ev.get("dim_intimacy", 0.0),
                            ev.get("dim_interaction_quality", 0.0),
                            ev.get("dim_communication_quality", 0.0),
                            ev.get("dim_structural", 0.0),
                            ev.get("dim_trust", 0.0),
                            ev.get("content_quality"),
                            1 if ev.get("is_negative") else 0,
                            ev.get("severity_level", 0),
                            raw_meta,
                            source_id,
                        ),
                    )
                    if conn.total_changes > 0:

                        inserted += 1
                except sqlite3.IntegrityError:

                    pass

            conn.commit()




        actual_inserted = self._count_inserted(events)
        log.info("Wrote %d/%d events (duplicates skipped)", actual_inserted, len(events))
        return actual_inserted

    def _count_inserted(self, events: list[dict[str, Any]]) -> int:
        ""





        source_ids = []
        for ev in events:
            sid = ev.get("source_id") or (f"{ev['person_id']}_{ev['timestamp']}_{ev['event_type']}")
            source_ids.append(sid)

        with self._conn(readonly=True) as conn:
            placeholders = ",".join("?" for _ in source_ids)
            cur = conn.execute(
                f"SELECT COUNT(*) FROM events WHERE source_id IN ({placeholders})",  # noqa: S608
                source_ids,
            )
            return cur.fetchone()[0]



    def get_events(
        self,
        person_id: str,
        since: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        ""









        query = "SELECT * FROM events WHERE person_id = ?"
        params: list[Any] = [person_id]

        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY timestamp DESC"

        with self._conn(readonly=True) as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_all_person_ids(self) -> list[str]:
        ""




        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT person_id FROM events ORDER BY person_id"
            ).fetchall()
            return [row["person_id"] for row in rows]

    def count_events(self, person_id: str, days: int | None = None) -> int:
        ""








        if days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            with self._conn(readonly=True) as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE person_id = ? AND timestamp >= ?",
                    (person_id, cutoff),
                )
                return cur.fetchone()[0]
        else:
            with self._conn(readonly=True) as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE person_id = ?",
                    (person_id,),
                )
                return cur.fetchone()[0]



    def mark_cache_stale(self, person_id: str) -> None:
        ""



        with self._conn() as conn:
            conn.execute(
                "UPDATE score_cache SET stale = 1 WHERE person_id = ?",
                (person_id,),
            )
            conn.commit()

    def mark_all_stale(self) -> None:
        ""




        with self._conn() as conn:
            conn.execute("UPDATE score_cache SET stale = 1")
            conn.commit()
        log.info("All cached scores marked stale")

    def get_cached_score(self, person_id: str) -> dict[str, Any] | None:
        ""









        with self._conn(readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM score_cache WHERE person_id = ? AND stale = 0",
                (person_id,),
            ).fetchone()

            if row is None:
                return None

            result = dict(row)

            if result.get("dims_json"):
                try:
                    result["dims"] = json.loads(result["dims_json"])
                except (json.JSONDecodeError, TypeError):
                    result["dims"] = {}
            else:
                result["dims"] = {}
            return result

    def update_cache(self, person_id: str, result: dict[str, Any]) -> None:
        ""







        dims_json = json.dumps(result.get("dims", {}), ensure_ascii=False)
        computed_at = datetime.now(UTC).isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO score_cache (
                    person_id, score, confidence, rel_type, dunbar_circle,
                    dims_json, momentum, computed_at, stale,
                    event_count, last_event_at,
                    events_7d, events_30d, events_90d
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                ON CONFLICT(person_id) DO UPDATE SET
                    score = excluded.score,
                    confidence = excluded.confidence,
                    rel_type = excluded.rel_type,
                    dunbar_circle = excluded.dunbar_circle,
                    dims_json = excluded.dims_json,
                    momentum = excluded.momentum,
                    computed_at = excluded.computed_at,
                    stale = 0,
                    event_count = excluded.event_count,
                    last_event_at = excluded.last_event_at,
                    events_7d = excluded.events_7d,
                    events_30d = excluded.events_30d,
                    events_90d = excluded.events_90d
                """,
                (
                    person_id,
                    result["score"],
                    result.get("confidence", 0.0),
                    result.get("rel_type"),
                    result.get("dunbar_circle"),
                    dims_json,
                    result.get("momentum"),
                    computed_at,
                    result.get("event_count", 0),
                    result.get("last_event_at"),
                    result.get("events_7d", 0),
                    result.get("events_30d", 0),
                    result.get("events_90d", 0),
                ),
            )
            conn.commit()

    def get_stale_person_ids(self) -> list[str]:
        ""




        with self._conn(readonly=True) as conn:
            rows = conn.execute("SELECT person_id FROM score_cache WHERE stale = 1").fetchall()
            return [row["person_id"] for row in rows]

    def get_all_cached_scores(self, min_score: float = 0.0) -> list[dict[str, Any]]:
        ""







        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM score_cache
                WHERE score >= ? AND stale = 0
                ORDER BY score DESC
                """,
                (min_score,),
            ).fetchall()

            results = []
            for row in rows:
                d = dict(row)
                if d.get("dims_json"):
                    try:
                        d["dims"] = json.loads(d["dims_json"])
                    except (json.JSONDecodeError, TypeError):
                        d["dims"] = {}
                else:
                    d["dims"] = {}
                results.append(d)
            return results



    def snapshot_daily(self) -> int:
        ""







        today = datetime.now(UTC).strftime("%Y-%m-%d")
        count = 0

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT person_id, score, confidence, dunbar_circle, events_30d, events_90d "
                "FROM score_cache WHERE stale = 0"
            ).fetchall()

            for row in rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO score_history (
                        person_id, date, score, confidence, dunbar_circle,
                        event_count_30d, event_count_90d
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["person_id"],
                        today,
                        row["score"],
                        row["confidence"],
                        row["dunbar_circle"],
                        row["events_30d"],
                        row["events_90d"],
                    ),
                )
                count += 1

            conn.commit()

        log.info("Snapshot: wrote %d score_history records for %s", count, today)
        return count

    def get_score_history(
        self,
        person_id: str,
        days: int = 365,
    ) -> list[dict[str, Any]]:
        ""








        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

        with self._conn(readonly=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM score_history
                WHERE person_id = ? AND date >= ?
                ORDER BY date ASC
                """,
                (person_id, cutoff),
            ).fetchall()
            return [dict(row) for row in rows]



    def stats(self) -> dict[str, Any]:
        ""






        with self._conn(readonly=True) as conn:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            persons = conn.execute("SELECT COUNT(DISTINCT person_id) FROM events").fetchone()[0]

            type_counts = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM events "
                "GROUP BY event_type ORDER BY cnt DESC"
            ).fetchall()

            source_counts = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM events GROUP BY source ORDER BY cnt DESC"
            ).fetchall()

            cached = conn.execute("SELECT COUNT(*) FROM score_cache WHERE stale = 0").fetchone()[0]
            stale = conn.execute("SELECT COUNT(*) FROM score_cache WHERE stale = 1").fetchone()[0]

            history_days = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM score_history"
            ).fetchone()[0]

            oldest = conn.execute("SELECT MIN(timestamp) FROM events").fetchone()[0]
            newest = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]


        db_size_mb = 0.0
        if self.db_path.exists():
            db_size_mb = self.db_path.stat().st_size / (1024 * 1024)

        return {
            "total_events": total,
            "unique_persons": persons,
            "event_types": {row["event_type"]: row["cnt"] for row in type_counts},
            "sources": {row["source"]: row["cnt"] for row in source_counts},
            "cached_scores": cached,
            "stale_scores": stale,
            "history_days": history_days,
            "oldest_event": oldest,
            "newest_event": newest,
            "db_size_mb": round(db_size_mb, 2),
        }




if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="RQV4 Event Store management")
    parser.add_argument(
        "--db", type=str, default=None, help="Path to DB (default: ~/.sbk-data/rq/events.db)"
    )
    parser.add_argument("--create", action="store_true", help="Create/initialize the database")
    parser.add_argument("--stats", action="store_true", help="Print store statistics")
    parser.add_argument(
        "--mark-all-stale", action="store_true", help="Mark all cached scores as stale"
    )
    parser.add_argument("--snapshot", action="store_true", help="Write daily score snapshot")
    args = parser.parse_args()

    store = EventStore(db_path=args.db)

    if args.create:
        store.create_db()
        print(f"Database created at {store.db_path}")

    if args.mark_all_stale:
        store.mark_all_stale()
        print("All cached scores marked stale")

    if args.snapshot:
        n = store.snapshot_daily()
        print(f"Snapshot: {n} records written")

    if args.stats or not any([args.create, args.mark_all_stale, args.snapshot]):

        if not store.db_path.exists():
            store.create_db()
            print(f"Database created at {store.db_path}")

        s = store.stats()
        print(f"\n{'=' * 50}")
        print(f"  RQV4 Event Store — {store.db_path}")
        print(f"{'=' * 50}")
        print(f"  Events:           {s['total_events']:,}")
        print(f"  Unique persons:   {s['unique_persons']:,}")
        print(f"  Cached scores:    {s['cached_scores']:,} ({s['stale_scores']} stale)")
        print(f"  History days:     {s['history_days']}")
        print(f"  Oldest event:     {s['oldest_event'] or 'n/a'}")
        print(f"  Newest event:     {s['newest_event'] or 'n/a'}")
        print(f"  DB size:          {s['db_size_mb']:.2f} MB")

        if s["sources"]:
            print("\n  Sources:")
            for src, cnt in s["sources"].items():
                print(f"    {src:20s} {cnt:>8,}")

        if s["event_types"]:
            print("\n  Event types:")
            for et, cnt in s["event_types"].items():
                print(f"    {et:30s} {cnt:>8,}")

        print()
