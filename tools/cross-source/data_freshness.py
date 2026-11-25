""








from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("data.freshness")


FRESHNESS_THRESHOLDS = {
    "ok": 7,
    "stale": 14,
    "critical": 30,
}


SOURCE_FILES = {
    "email": "emails/filtered-messages.parquet",
    "slack": "slack/processed/interactions-slack.parquet",
    "calendar": "enriched/contacts-calendar.parquet",
    "attio": "attio/processed/contacts-attio.parquet",
    "tactiq": "tactiq/processed/meetings.parquet",
    "plaud": "plaud/processed/_full_results_v2.json",
    "personio": "personio/processed/employees.parquet",
    "linkedin": "linkedin/processed/contacts-linkedin.parquet",
    "docusign": "docusign/processed/contacts-docusign.parquet",
    "whatsapp": "whatsapp/processed/contacts-whatsapp.parquet",
    "notion": "notion/processed/entities-notion.parquet",
    "gdrive": "gdrive/processed/contacts-gdrive.parquet",
    "contacts_merged": "enriched/contacts-merged.parquet",
    "signals": "rq/signals.parquet",
    "scores_v2": "rq/composite-scores-v2.parquet",
    "knowledge": "knowledge/entities/person/",
}


def check_freshness(
    data_root: Path | None = None,
    thresholds: dict | None = None,
) -> list[dict]:
    ""




    if data_root is None:
        from sbk_config import DATA_ROOT

        data_root = DATA_ROOT
    if thresholds is None:
        thresholds = FRESHNESS_THRESHOLDS

    now = datetime.now(UTC)
    results = []

    for source, rel_path in SOURCE_FILES.items():
        full_path = data_root / rel_path
        if not full_path.exists():
            results.append(
                {
                    "source": source,
                    "path": str(rel_path),
                    "status": "missing",
                    "days_old": -1,
                    "last_modified": None,
                }
            )
            continue


        if full_path.is_dir():
            files = list(full_path.glob("*.json"))
            if not files:
                mtime = full_path.stat().st_mtime
            else:
                mtime = max(f.stat().st_mtime for f in files)
        else:
            mtime = full_path.stat().st_mtime

        last_mod = datetime.fromtimestamp(mtime, tz=UTC)
        days_old = (now - last_mod).days

        if days_old <= thresholds["ok"]:
            status = "ok"
        elif days_old <= thresholds["critical"]:
            status = "stale"
        else:
            status = "critical"

        results.append(
            {
                "source": source,
                "path": str(rel_path),
                "status": status,
                "days_old": days_old,
                "last_modified": last_mod.isoformat(),
            }
        )


    results.sort(key=lambda x: x["days_old"], reverse=True)
    return results


def generate_freshness_report(data_root: Path | None = None) -> dict:
    ""







    sources = check_freshness(data_root)
    summary = {"ok": 0, "stale": 0, "critical": 0, "missing": 0}
    for s in sources:
        summary[s["status"]] = summary.get(s["status"], 0) + 1

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "sources": sources,
        "summary": summary,
    }


def get_stale_alerts(data_root: Path | None = None) -> list[str]:
    ""



    sources = check_freshness(data_root)
    alerts = []
    for s in sources:
        if s["status"] == "critical":
            alerts.append(f"CRITICAL: {s['source']} — {s['days_old']} days old")
        elif s["status"] == "stale":
            alerts.append(f"STALE: {s['source']} — {s['days_old']} days old")
        elif s["status"] == "missing":
            alerts.append(f"MISSING: {s['source']} — file not found")
    return alerts
