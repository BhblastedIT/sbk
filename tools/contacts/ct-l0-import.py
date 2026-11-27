#!/usr/bin/env python3
"""Contacts L0 (exports): copy your address-book export into the plugin's raw folder.

Takes .vcf files (vCard 2.1, 3.0 or 4.0: macOS Contacts, iCloud.com, the iPhone Contacts app,
Google Contacts, Outlook desktop) and .csv files (Google Contacts, Outlook, Outlook.com), or a
folder holding them, and keeps a copy under <data root>/contacts/raw/imports/<label>/.

An export is a full snapshot: a new import replaces the previous copy of the same label, which
is moved to raw/imports/<label>/previous/ (one generation kept). An export identical to the one
already imported is not copied again. Every file is parsed first: if none of them yields a
contact, nothing is replaced.

Then run tools/contacts/ct-l1-enrich.py, which writes the address-book slot.

    uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone
    uv run python tools/contacts/ct-l0-import.py ~/Downloads/outlook-export/ --label outlook

Setup: docs/CONNECTING.md#contacts
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct_book  # noqa: E402
from ct_book import ContactsError  # noqa: E402

DEFAULT_LABEL = "export"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Import an address-book export (.vcf or .csv, or a folder of them) "
        "into the contacts plugin (see docs/CONNECTING.md#contacts)."
    )
    ap.add_argument("paths", nargs="*", help=".vcf / .csv files or folders")
    ap.add_argument(
        "--label",
        default=DEFAULT_LABEL,
        help=f"a short name for this export, e.g. phone, outlook (default: {DEFAULT_LABEL})",
    )
    return ap.parse_args(argv)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_import(paths: list[Path], label: str) -> dict:
    label = ct_book.check_label(label)
    files = ct_book.export_files(paths)
    if not files:
        raise ContactsError("no .vcf or .csv file found in what you named")
    stats: dict = {}
    parsed = 0
    entries = []
    names_seen: set[str] = set()
    for f in files:
        n = len(ct_book.read_export(f, stats))
        parsed += n
        name = f.name
        k = 2
        while name in names_seen:  # two files with the same name from different folders
            name = f"{f.stem}-{k}{f.suffix}"
            k += 1
        names_seen.add(name)
        entries.append(
            {
                "name": name,
                "from": f,
                "sha256": _sha256(f),
                "bytes": f.stat().st_size,
                "contacts": n,
            }
        )
    if parsed == 0:
        raise ContactsError("no contact found in the export; nothing was replaced")

    dest = ct_book.imports_dir(label)
    manifest_path = dest / "manifest.json"
    old = ct_book.read_json(manifest_path, {})
    old_set = sorted((e.get("name"), e.get("sha256")) for e in old.get("files", []))
    new_set = sorted((e["name"], e["sha256"]) for e in entries)
    # "unchanged" also needs the copies to be on disk: a manifest whose files were removed
    # would otherwise keep pointing at nothing and the label would silently lose its contacts.
    unchanged = (
        bool(old) and old_set == new_set and all((dest / e["name"]).is_file() for e in entries)
    )
    now = datetime.now(UTC).isoformat()
    if not unchanged:
        if old.get("files"):
            prev = dest / "previous"
            if prev.exists():
                shutil.rmtree(prev)  # the plugin's own older copy; one generation is kept
            prev.mkdir(parents=True)
            for e in old["files"]:
                src = dest / e["name"]
                if src.exists():
                    os.replace(src, prev / e["name"])
            if manifest_path.exists():
                os.replace(manifest_path, prev / "manifest.json")
        dest.mkdir(parents=True, exist_ok=True)
        for e in entries:
            target = dest / e["name"]
            shutil.copyfile(e["from"], target)
            os.chmod(target, 0o600)
        ct_book.write_json(
            manifest_path,
            {
                "label": label,
                "imported_at": now,
                "files": [{k: v for k, v in e.items() if k != "from"} for e in entries],
                "contacts_parsed": parsed,
            },
        )
    summary = {
        "kind": "import",
        "label": label,
        "files": len(entries),
        "contacts_parsed": parsed,
        "birthdays_unparsed": stats.get("birthdays_unparsed", 0),
        "unchanged": unchanged,
        "completed_at": now,
    }
    ct_book.update_summary(f"import:{label}", summary)
    return summary


def cli(argv=None) -> int:
    args = parse_args(argv)
    if not args.paths:
        print(
            "contacts: name the export to import, e.g. "
            "uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone",
            file=sys.stderr,
        )
        return 2
    try:
        s = run_import([Path(p) for p in args.paths], args.label)
    except ContactsError as e:
        print(f"contacts: {e}", file=sys.stderr)
        return 2
    try:
        import sbk_config

        sbk_config.mark_last_run(ct_book.SOURCE)
    except Exception:  # noqa: BLE001 - the timestamp is a convenience
        pass
    state = "unchanged, nothing copied" if s["unchanged"] else "copied"
    print(
        f"contacts: import '{s['label']}': {s['files']} file(s), {s['contacts_parsed']} contacts "
        f"({state}). Next: uv run python tools/contacts/ct-l1-enrich.py"
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli())
