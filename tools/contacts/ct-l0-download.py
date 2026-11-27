#!/usr/bin/env python3
"""Contacts L0 (Google): download your Google Contacts with the People API.

Reads people/me/connections (only the contacts you saved, READ_SOURCE_TYPE_CONTACT) with your
own login (ct-l0-auth.py) and keeps them in <data root>/contacts/raw/google/<label>/people.json.

Incremental: Google's sync token is saved in raw/google/<label>/state.json and the next run
reads only what changed (deleted contacts are removed). Google keeps a sync token for 7 days:
after that, or with --full, the whole list is read again and replaces the stored one.

    uv run python tools/contacts/ct-l0-download.py --account personal
    uv run python tools/contacts/ct-l0-download.py --all          # labels in contacts.google_accounts
    uv run python tools/contacts/ct-l1-enrich.py                 # then write the address-book slot

Setup: docs/CONNECTING.md#contacts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct_book  # noqa: E402
import ct_google  # noqa: E402
from ct_book import ContactsError  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your Google Contacts through the People API (read-only, your own "
        "Google app), see docs/CONNECTING.md#contacts."
    )
    ap.add_argument("--account", help="label of a Google account signed in with ct-l0-auth.py")
    ap.add_argument(
        "--all",
        action="store_true",
        help="every label in contacts.google_accounts (sbk.config.json); none listed = nothing to do",
    )
    ap.add_argument("--full", action="store_true", help="read the whole list again")
    return ap.parse_args(argv)


def run_one(label: str, full: bool = False, opener=None, sleep=None) -> dict:
    label = ct_book.check_label(label)
    client, _scope = ct_google.connect(label, opener=opener, sleep=sleep)
    summary = ct_google.run_download(label, client, full=full)
    ct_book.update_summary(f"google:{label}", summary)
    return summary


def cli(argv=None, opener=None, sleep=None) -> int:
    args = parse_args(argv)
    if args.all:
        labels = [str(x) for x in ct_book.cfg("google_accounts", []) or []]
        if not labels:
            print(
                "contacts: no Google account listed in contacts.google_accounts, nothing to "
                "download (exports are imported with ct-l0-import.py)"
            )
            return 0
    elif args.account:
        labels = [args.account]
    else:
        print(
            "contacts: name a Google account (--account <label>) or use --all; vCard and CSV "
            "exports are imported with tools/contacts/ct-l0-import.py",
            file=sys.stderr,
        )
        return 2
    code = 0
    for label in labels:
        try:
            s = run_one(label, full=args.full, opener=opener, sleep=sleep)
        except ContactsError as e:
            print(f"contacts: {label}: {e}", file=sys.stderr)
            code = 2
            continue
        print(
            f"contacts: Google '{s['label']}' {s['mode']}: {s['contacts_stored']} contacts "
            f"(+{s['added']} new, {s['changed']} changed, -{s['deleted']} removed). "
            "Next: uv run python tools/contacts/ct-l1-enrich.py"
        )
    if code == 0:
        try:
            import sbk_config

            sbk_config.mark_last_run(ct_book.SOURCE)
        except Exception:  # noqa: BLE001 - the timestamp is a convenience
            pass
    return code


if __name__ == "__main__":
    sys.exit(cli())
