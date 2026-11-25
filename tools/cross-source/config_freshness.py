""






from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("rq.config_freshness")

CONFIG_FILES = {
    "scoring-config-v3.json": 90,
    "content-quality-dictionaries.json": 180,
}


def check_config_freshness(
    config_dir: Path | None = None,
    metadata_path: Path | None = None,
) -> list[dict]:
    ""



    if config_dir is None:
        config_dir = Path(__file__).resolve().parent


    meta = {}
    if metadata_path and metadata_path.exists():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    alerts = []
    now = datetime.now()

    for filename, threshold_days in CONFIG_FILES.items():
        filepath = config_dir / filename
        if not filepath.exists():
            continue


        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        days_old = (now - mtime).days


        file_meta = meta.get(filename, {})
        if "last_validated" in file_meta:
            try:
                validated = datetime.fromisoformat(file_meta["last_validated"])
                days_old = min(days_old, (now - validated).days)
            except Exception:
                pass

        alerts.append(
            {
                "file": filename,
                "days_old": days_old,
                "threshold": threshold_days,
                "is_stale": days_old > threshold_days,
            }
        )

    return alerts


def get_stale_configs(config_dir: Path | None = None) -> list[str]:
    ""
    alerts = check_config_freshness(config_dir)
    return [a["file"] for a in alerts if a["is_stale"]]
