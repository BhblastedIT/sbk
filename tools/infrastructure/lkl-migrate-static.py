#!/usr/bin/env python3
""










from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

ARCHIVE_HEADER = """\
> **ARCHIVE** -- For up-to-date data, the system uses the Knowledge Store
> (`~/.sbk-data/knowledge/entities/`). This file is kept as a
> historical reference and must NOT be used as a primary source for factual data.
> For current information on people, companies, teams, deals: use `get_entity_profile`
> or `get_company_team` in the chat, or the Knowledge Health dashboard.

---

"""

ARCHIVE_MARKER = "**ARCHIVE**"


def find_target_files() -> list[Path]:
    ""
    targets = []


    network_dir = PROJECT_ROOT / "sbk" / "network"
    if network_dir.exists():
        for f in sorted(network_dir.rglob("*.md")):
            targets.append(f)


    companies_dir = PROJECT_ROOT / "sbk" / "companies"
    if companies_dir.exists():
        for f in sorted(companies_dir.rglob("state.md")):
            targets.append(f)

    return targets


def needs_header(filepath: Path) -> bool:
    ""
    try:
        content = filepath.read_text(encoding="utf-8")
        return ARCHIVE_MARKER not in content[:500]
    except OSError:
        return False


def apply_header(filepath: Path, *, dry_run: bool = True) -> bool:
    ""
    if not needs_header(filepath):
        return False

    if dry_run:
        return True

    try:
        content = filepath.read_text(encoding="utf-8")
        filepath.write_text(ARCHIVE_HEADER + content, encoding="utf-8")
        return True
    except OSError as e:
        print(f"  ERROR: {filepath}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Add archive header to static knowledge files")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run)")
    args = parser.parse_args()

    targets = find_target_files()
    print(f"Found {len(targets)} target files")

    modified = 0
    skipped = 0

    for f in targets:
        rel = f.relative_to(PROJECT_ROOT)
        if apply_header(f, dry_run=not args.apply):
            modified += 1
            action = "WOULD ADD" if not args.apply else "ADDED"
            print(f"  {action} header: {rel}")
        else:
            skipped += 1
            print(f"  SKIP (already has header): {rel}")

    print(f"\nSummary: {modified} modified, {skipped} skipped")
    if not args.apply and modified > 0:
        print("Run with --apply to actually modify files")


if __name__ == "__main__":
    main()
