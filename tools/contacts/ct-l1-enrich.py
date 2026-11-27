#!/usr/bin/env python3
"""Contacts L1: your imported exports and Google Contacts -> the kernel's address-book slot.

Reads what ct-l0-import.py and ct-l0-download.py saved under <data root>/contacts/raw/ and
writes the rows tagged contacts:import:<label> and contacts:google:<label> into
<data root>/contacts/contacts.parquet, the file tools/cross-source/xs-l1-contacts-enrich.py
reads. Rows of every other origin (microsoft365, a parquet you made yourself) are kept. While
the slot holds only plugin rows, your iphone-contacts.json is copied in too (source
iphone-contacts-json), because the kernel stops reading that JSON as the address book once the
parquet exists.

Then it runs the kernel step tools/cross-source/xs-l1-contacts-enrich.py (which
xs-pipeline-run.py does not run by itself), so the merge sees the contacts; --no-kernel skips
it. No network.

    uv run python tools/contacts/ct-l1-enrich.py
    uv run python tools/contacts/ct-l1-enrich.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ct_book  # noqa: E402
import ct_google  # noqa: E402
from ct_book import ContactsError  # noqa: E402

KERNEL_STEP = HERE.parent / "cross-source" / "xs-l1-contacts-enrich.py"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Write your imported address book and Google Contacts into the kernel's "
        "address-book slot (contacts/contacts.parquet), then run the kernel contacts step."
    )
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    ap.add_argument(
        "--no-kernel",
        action="store_true",
        help="do not run tools/cross-source/xs-l1-contacts-enrich.py afterwards",
    )
    return ap.parse_args(argv)


def collect() -> tuple[list[dict], dict]:
    """Slot rows from every imported export and every Google label, with counts."""
    rows: list[dict] = []
    counts: dict = {}
    base = ct_book.imports_dir()
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        manifest = ct_book.read_json(d / "manifest.json", {})
        tag = f"{ct_book.SOURCE_PREFIX}import:{d.name}"
        n = 0
        for e in manifest.get("files", []):
            f = d / e.get("name", "")
            if not f.is_file():
                continue
            try:
                contacts = ct_book.read_export(f)
            except ContactsError as err:
                counts.setdefault("errors", []).append(f"{d.name}/{f.name}: {err}")
                continue
            rows += [ct_book.contact_row(c, tag) for c in contacts]
            n += len(contacts)
        counts[f"import:{d.name}"] = n
    gbase = ct_book.google_dir()
    for d in sorted(p for p in gbase.iterdir() if p.is_dir()) if gbase.is_dir() else []:
        people = ct_book.read_json(d / "people.json", {})
        if not isinstance(people, dict):
            continue
        tag = f"{ct_book.SOURCE_PREFIX}google:{d.name}"
        rows += [
            ct_book.contact_row(ct_google.person_to_contact(p), tag)
            for p in people.values()
            if isinstance(p, dict)
        ]
        counts[f"google:{d.name}"] = len(people)
    return rows, counts


def run_kernel_step() -> int:
    env = dict(os.environ, SBK_DATA_ROOT=str(ct_book.data_root()))
    r = subprocess.run([sys.executable, str(KERNEL_STEP)], env=env, cwd=str(HERE.parent.parent))
    return r.returncode


def cli(argv=None) -> int:
    args = parse_args(argv)
    try:
        rows, counts = collect()
        if not counts:
            print(
                f"contacts: nothing to enrich in {ct_book.raw_dir()}; import an export with "
                "tools/contacts/ct-l0-import.py or download with tools/contacts/ct-l0-download.py",
                file=sys.stderr,
            )
            return 1
        rows, dropped = ct_book.dedupe(rows)
        existing = ct_book.read_slot()
        merged, seeded = ct_book.merge_slot(existing, rows)
    except ContactsError as e:
        print(f"contacts: {e}", file=sys.stderr)
        return 2
    other = len(merged) - len(rows) - seeded
    detail = ", ".join(f"{k} {v}" for k, v in counts.items() if k != "errors")
    print(
        f"contacts: {len(rows)} contacts for the slot ({detail}; {dropped} duplicates or empty "
        f"left out), {other} rows of other sources kept"
        + (f", {seeded} copied from iphone-contacts.json" if seeded else "")
    )
    for err in counts.get("errors", []):
        print(f"contacts: skipped {err}", file=sys.stderr)
    if args.dry_run:
        return 0
    try:
        ct_book.write_slot(merged)
    except Exception as e:  # noqa: BLE001 - safe_write_parquet keeps the old file on failure
        print(
            f"contacts: {ct_book.slot_path()} was not written ({type(e).__name__}: {e}); "
            "the previous file is unchanged",
            file=sys.stderr,
        )
        return 2
    print(f"contacts: wrote {ct_book.slot_path()}")
    if args.no_kernel:
        return 0
    code = run_kernel_step()
    if code != 0:
        print(
            f"contacts: the kernel step {KERNEL_STEP.name} ended with code {code}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
