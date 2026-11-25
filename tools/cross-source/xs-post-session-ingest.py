#!/usr/bin/env python3
""

















from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT

log = logging.getLogger("post-session-ingest")

PENDING_DIR = DATA_ROOT / "manual-ingestion" / "pending"
DONE_DIR = DATA_ROOT / "manual-ingestion" / "done"


@dataclass
class IngestReport:
    ""

    files_processed: int = 0
    files_skipped: int = 0
    total_entities: int = 0
    new_contacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_fact_file(path: Path) -> tuple[bool, str]:
    ""



    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        return False, f"Invalid JSON: {e}"

    if not isinstance(data, dict):
        return False, "Root must be a dict"

    if "entities" not in data:
        return False, "Missing 'entities' key"

    entities = data["entities"]
    if not isinstance(entities, list):
        return False, "'entities' must be a list"

    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            return False, f"Entity {i} must be a dict"
        if "name" not in entity and "canonical_name" not in entity:
            return False, f"Entity {i} missing 'name'"
        if "facts" not in entity or not entity["facts"]:
            return False, f"Entity {i} missing 'facts' or empty"

    return True, ""


def count_entities(path: Path) -> int:
    ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data.get("entities", []))
    except (ValueError, OSError):
        return 0


def process_pending(
    pending_dir: Path | None = None,
    done_dir: Path | None = None,
    dry_run: bool = True,
    single_file: Path | None = None,
) -> IngestReport:
    ""










    if pending_dir is None:
        pending_dir = PENDING_DIR
    if done_dir is None:
        done_dir = DONE_DIR

    report = IngestReport()

    if single_file:
        files = [single_file] if single_file.exists() else []
    else:
        if not pending_dir.exists():
            return report
        files = sorted(pending_dir.glob("*.json"))

    if not files:
        log.info("No pending files to process")
        return report

    log.info("Found %d pending file(s)", len(files))

    for fpath in files:
        log.info("Processing: %s", fpath.name)


        is_valid, error = validate_fact_file(fpath)
        if not is_valid:
            log.warning("Skipping %s: %s", fpath.name, error)
            report.files_skipped += 1
            report.errors.append(f"{fpath.name}: {error}")
            continue


        n_entities = count_entities(fpath)
        report.total_entities += n_entities

        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            for entity in data.get("entities", []):
                name = entity.get("name", entity.get("canonical_name", "unknown"))
                report.new_contacts.append(name)
        except (ValueError, OSError):
            pass

        if dry_run:
            log.info("  [DRY RUN] Would ingest %d entities from %s", n_entities, fpath.name)
            report.files_processed += 1
            continue


        try:
            from xs_manual_knowledge_ingest import ingest_fact_file

            ingest_fact_file(fpath)
            report.files_processed += 1
            log.info("  Ingested %d entities from %s", n_entities, fpath.name)


            done_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            dest = done_dir / f"{fpath.stem}--{ts}.json"
            shutil.move(str(fpath), str(dest))
            log.info("  Moved to: %s", dest.name)
        except ImportError:

            import subprocess

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "xs-manual-knowledge-ingest.py"),
                    str(fpath),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                report.files_processed += 1
                log.info("  Ingested via CLI: %s", fpath.name)
            else:
                report.errors.append(f"{fpath.name}: CLI failed: {result.stderr[:200]}")
                report.files_skipped += 1
        except Exception as e:
            report.errors.append(f"{fpath.name}: {e}")
            report.files_skipped += 1
            log.warning("  Error ingesting %s: %s", fpath.name, e)

    return report


def main():
    parser = argparse.ArgumentParser(description="Post-session contact ingestion")
    parser.add_argument(
        "--execute", action="store_true", help="Execute ingestion (default is dry-run)"
    )
    parser.add_argument("--file", type=str, help="Process a specific file")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    single = Path(args.file) if args.file else None
    dry_run = not args.execute

    if dry_run:
        log.info("DRY RUN mode (use --execute to ingest)")

    report = process_pending(dry_run=dry_run, single_file=single)

    log.info("=" * 50)
    log.info("Report:")
    log.info("  Files processed: %d", report.files_processed)
    log.info("  Files skipped:   %d", report.files_skipped)
    log.info("  Total entities:  %d", report.total_entities)
    if report.new_contacts:
        log.info("  Contacts: %s", ", ".join(report.new_contacts[:20]))
    if report.errors:
        log.info("  Errors:")
        for err in report.errors:
            log.info("    - %s", err)


if __name__ == "__main__":
    main()
