#!/usr/bin/env python3
"""Consolidates the commitments found by the deep extraction (email, Plaud, Slack) into one commitments file,
with normalised deadlines and stable ids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import COMMITMENTS_DIR, COMMITMENTS_FILE, DEEP_RESPONSES_DIR

log = logging.getLogger("xs-commitment-consolidate")





_RELATIVE_PATTERNS = [
    (
        re.compile(
            r"entro\s+(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)",
            re.I,
        ),
        "weekday",
    ),
    (
        re.compile(
            r"entro\s+(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)",
            re.I,
        ),
        "date_it",
    ),
    (
        re.compile(r"by\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", re.I),
        "weekday_en",
    ),
    (re.compile(r"immediately|immediatamente|subito", re.I), "immediate"),
    (re.compile(r"end\s+of\s+(day|week|month)", re.I), "end_of"),
    (re.compile(r"fine\s+(giornata|settimana|mese)", re.I), "end_of_it"),
]


_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def normalize_deadline(raw_deadline: str | None, doc_date: str = "") -> str | None:
    ""



    if not raw_deadline:
        return None

    dl = str(raw_deadline).strip()
    if dl.lower() in ("null", "n/a", "none", "", "immediately", "immediatamente", "subito"):
        return None


    m = _ISO_DATE_RE.search(dl)
    if m:
        return m.group(1)


    try:
        from dateutil import parser as dateutil_parser

        ref_date = None
        if doc_date:
            try:
                ref_date = dateutil_parser.parse(doc_date[:10])
            except (ValueError, TypeError):
                pass

        parsed = dateutil_parser.parse(dl, default=ref_date, fuzzy=True)
        if parsed:
            return parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError, ImportError):
        pass

    return None


def make_commitment_id(source_id: str, person: str, description: str) -> str:
    ""
    key = (
        f"{source_id}|{(person or '').lower().strip()}|{(description or '').lower().strip()[:100]}"
    )
    return f"com-{hashlib.sha256(key.encode()).hexdigest()[:12]}"





def scan_deep_responses(sources: list[str] | None = None) -> list[dict]:
    ""



    if not DEEP_RESPONSES_DIR.exists():
        log.warning(f"Deep responses dir not found: {DEEP_RESPONSES_DIR}")
        return []

    all_commitments = []
    source_dirs = sorted(DEEP_RESPONSES_DIR.iterdir())

    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        if sources and source_dir.name not in sources:
            continue

        src_count = 0
        for f in sorted(source_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                commits = data.get("commitment", [])
                if not isinstance(commits, list):
                    continue
                for c in commits:
                    if not isinstance(c, dict):
                        continue

                    c["_source_type"] = source_dir.name
                    c["_source_file"] = f.name
                    c["_source_id"] = f"{source_dir.name}/{f.stem}"


                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
                    c["_source_date"] = date_match.group(1) if date_match else ""

                    all_commitments.append(c)
                    src_count += 1
            except (json.JSONDecodeError, OSError) as e:
                log.debug(f"Skip {f.name}: {e}")

        if src_count:
            log.info(f"  {source_dir.name}: {src_count} commitments")

    return all_commitments


def consolidate(
    raw_commitments: list[dict],
    existing: list[dict] | None = None,
    incremental: bool = False,
) -> list[dict]:
    ""









    existing_ids = set()
    if existing and incremental:
        existing_ids = {c["commitment_id"] for c in existing}

    results = []
    skipped_dedup = 0

    for raw in raw_commitments:
        source_id = raw.get("_source_id", "")
        person = raw.get("person", "") or ""
        description = raw.get("description", "") or ""

        if not person and not description:
            continue

        cid = make_commitment_id(source_id, person, description)

        if cid in existing_ids:
            skipped_dedup += 1
            continue
        existing_ids.add(cid)


        raw_deadline = raw.get("deadline")
        source_date = raw.get("_source_date", "")
        deadline = normalize_deadline(raw_deadline, doc_date=source_date)

        record = {
            "commitment_id": cid,
            "who": person,
            "to_whom": raw.get("to_whom", "") or "",
            "what": description,
            "commitment_type": raw.get("commitment_type", "") or "",
            "deadline": deadline,
            "deadline_raw": str(raw_deadline) if raw_deadline else None,
            "status": "PENDING",
            "source_type": raw.get("_source_type", ""),
            "source_id": source_id,
            "source_date": source_date,
            "original_context": (raw.get("context", "") or "")[:500],
            "confidence": raw.get("confidence", "") or "",
            "amount": raw.get("amount"),
            "currency": raw.get("currency"),
            "conditions": raw.get("conditions"),
            "created_at": datetime.now(UTC).isoformat(),
            "notified_pre_deadline": False,
            "notified_at_deadline": False,
            "verified_at": None,
            "verification_evidence": None,
        }
        results.append(record)

    if skipped_dedup:
        log.info(f"Skipped {skipped_dedup} already-consolidated commitments")

    return results


def load_existing() -> list[dict]:
    ""
    if COMMITMENTS_FILE.exists():
        try:
            return json.loads(COMMITMENTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_commitments(commitments: list[dict]) -> None:
    ""
    COMMITMENTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COMMITMENTS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(commitments, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    tmp.rename(COMMITMENTS_FILE)


def show_stats(commitments: list[dict]) -> None:
    ""
    total = len(commitments)
    by_status = {}
    by_type = {}
    by_source = {}
    with_deadline = 0

    for c in commitments:
        status = c.get("status", "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
        ctype = c.get("commitment_type", "unknown")
        by_type[ctype] = by_type.get(ctype, 0) + 1
        src = c.get("source_type", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
        if c.get("deadline"):
            with_deadline += 1

    print(f"\nTotal commitments: {total}")
    print(f"With deadline: {with_deadline} ({100 * with_deadline / total:.0f}%)" if total else "")
    print("\nBy status:")
    for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n}")
    print("\nBy type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")
    print("\nBy source:")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n}")


def main():
    parser = argparse.ArgumentParser(description="Consolidate commitments from deep-responses")
    parser.add_argument("--source", action="append", help="Filter by source (email, plaud, slack)")
    parser.add_argument("--incremental", action="store_true", help="Skip already consolidated")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't write")
    parser.add_argument("--stats", action="store_true", help="Show stats from existing file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.stats:
        existing = load_existing()
        if not existing:
            print("No commitments file found.")
            return
        show_stats(existing)
        return

    log.info("Scanning deep-responses for commitments...")
    raw = scan_deep_responses(sources=args.source)
    log.info(f"Found {len(raw)} raw commitment extractions")

    existing = load_existing() if args.incremental else []
    new_commitments = consolidate(raw, existing=existing, incremental=args.incremental)
    log.info(f"New commitments to add: {len(new_commitments)}")

    if args.dry_run:
        log.info("Dry run — not writing")
        if new_commitments:
            show_stats(new_commitments)
        return

    if args.incremental and existing:
        all_commitments = existing + new_commitments
    else:
        all_commitments = new_commitments

    save_commitments(all_commitments)
    log.info(f"Saved {len(all_commitments)} commitments to {COMMITMENTS_FILE}")
    show_stats(all_commitments)


if __name__ == "__main__":
    main()
