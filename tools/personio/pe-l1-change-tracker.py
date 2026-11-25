#!/usr/bin/env python3
""














from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from sbk_config import DATA_ROOT, mark_last_run  # noqa: E402

log = logging.getLogger("pe-change-tracker")

PERSONIO_DIR = DATA_ROOT / "personio"
PROCESSED_DIR = PERSONIO_DIR / "processed"
EMPLOYEES_FILE = PERSONIO_DIR / "employees-raw.json"
HASH_FILE = PROCESSED_DIR / "_employee_hashes.json"
EVENTS_FILE = PROCESSED_DIR / "change-events.json"

TRACKED_FIELDS = [
    "status",
    "position",
    "department",
    "fix_salary",
    "supervisor",
    "office",
    "team",
    "subcompany",
]


def _hash_employee(emp: dict) -> str:
    ""
    tracked = {k: str(emp.get(k, "")) for k in TRACKED_FIELDS}
    raw = json.dumps(tracked, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_id(emp: dict) -> str:
    ""
    attrs = emp.get("attributes", {})
    eid = attrs.get("id", {}).get("value", "")
    return str(eid)


def _extract_flat(emp: dict) -> dict:
    ""
    attrs = emp.get("attributes", {})
    flat = {}
    for key in TRACKED_FIELDS + ["first_name", "last_name", "email"]:
        val = attrs.get(key, {})
        if isinstance(val, dict):
            flat[key] = str(val.get("value", ""))
        else:
            flat[key] = str(val)
    flat["name"] = f"{flat.get('first_name', '')} {flat.get('last_name', '')}".strip()
    return flat


def detect_changes(dry_run: bool = False) -> list[dict]:
    ""
    if not EMPLOYEES_FILE.exists():
        log.error(f"Not found: {EMPLOYEES_FILE}")
        return []

    with open(EMPLOYEES_FILE) as f:
        raw = json.load(f)

    employees = raw if isinstance(raw, list) else raw.get("data", [])
    log.info(f"Loaded {len(employees)} employee records")


    old_hashes: dict[str, str] = {}
    old_data: dict[str, dict] = {}
    if HASH_FILE.exists():
        saved = json.loads(HASH_FILE.read_text())
        old_hashes = saved.get("hashes", {})
        old_data = saved.get("data", {})
        log.info(f"Loaded {len(old_hashes)} previous hashes")
    else:
        log.info("No previous hashes — first run, will establish baseline")


    current_hashes: dict[str, str] = {}
    current_data: dict[str, dict] = {}
    events: list[dict] = []
    now = datetime.now(UTC).isoformat()

    for emp in employees:
        eid = _extract_id(emp)
        if not eid:
            continue
        flat = _extract_flat(emp)
        h = _hash_employee(flat)
        current_hashes[eid] = h
        current_data[eid] = flat

        if eid not in old_hashes:

            if old_hashes:
                events.append(
                    {
                        "timestamp": now,
                        "employee_id": eid,
                        "name": flat.get("name", ""),
                        "event_type": "new_hire",
                        "details": {
                            "department": flat.get("department", ""),
                            "position": flat.get("position", ""),
                        },
                    }
                )
        elif h != old_hashes[eid]:

            old_flat = old_data.get(eid, {})
            for field in TRACKED_FIELDS:
                old_val = old_flat.get(field, "")
                new_val = flat.get(field, "")
                if old_val != new_val:
                    event_type = f"{field}_change"
                    if field == "status" and new_val.lower() == "inactive":
                        event_type = "departure"
                    elif field == "status" and old_val.lower() == "inactive":
                        event_type = "rehire"
                    events.append(
                        {
                            "timestamp": now,
                            "employee_id": eid,
                            "name": flat.get("name", ""),
                            "event_type": event_type,
                            "field": field,
                            "old_value": old_val,
                            "new_value": new_val,
                        }
                    )


    for eid in old_hashes:
        if eid not in current_hashes:
            events.append(
                {
                    "timestamp": now,
                    "employee_id": eid,
                    "name": old_data.get(eid, {}).get("name", ""),
                    "event_type": "removed_from_system",
                }
            )

    log.info(f"Detected {len(events)} change events")
    for ev in events:
        log.info(f"  {ev['event_type']}: {ev.get('name', '')} {ev.get('field', '')}")

    if not dry_run:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


        HASH_FILE.write_text(
            json.dumps(
                {
                    "generated_at": now,
                    "hashes": current_hashes,
                    "data": current_data,
                },
                indent=2,
            )
        )


        existing_events = []
        if EVENTS_FILE.exists():
            existing_events = json.loads(EVENTS_FILE.read_text())
        existing_events.extend(events)
        EVENTS_FILE.write_text(json.dumps(existing_events, indent=2, default=str))

        log.info(f"Saved {len(events)} events → {EVENTS_FILE}")
        log.info(f"Saved hashes → {HASH_FILE}")
        mark_last_run("l1-personio-change-tracker")

    return events


def main():
    parser = argparse.ArgumentParser(description="Personio employee change tracker")
    parser.add_argument("--dry-run", action="store_true", help="Detect changes without saving")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    detect_changes(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
