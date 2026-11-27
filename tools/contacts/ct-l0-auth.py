#!/usr/bin/env python3
"""Contacts L0 (Google): sign one Google account in for the People API, once.

Uses your own Desktop-app OAuth client (tools/google_oauth.py, the same one as the other Google
plugins), asks only https://www.googleapis.com/auth/contacts.readonly, and stores the refresh
token in the Keychain as sbk-gcontacts/<label>. The People API must be enabled in the same
Google Cloud project.

    uv run python tools/contacts/ct-l0-auth.py --account personal
    uv run python tools/contacts/ct-l0-auth.py --account personal --check

Setup: docs/CONNECTING.md#contacts
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct_book  # noqa: E402
import ct_google  # noqa: E402
from ct_book import ContactsError  # noqa: E402

DEFAULT_LABEL = "google"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Sign a Google account in for Google Contacts (People API, read-only), "
        "see docs/CONNECTING.md#contacts."
    )
    ap.add_argument(
        "--account",
        default=DEFAULT_LABEL,
        help=f"a short label for this Google account (default: {DEFAULT_LABEL})",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not open the browser: test the stored login with one request",
    )
    return ap.parse_args(argv)


def check(label: str, opener=None, sleep=None) -> int:
    client, _scope = ct_google.connect(label, opener=opener, sleep=sleep)
    data = client._get(
        {
            "personFields": "names",
            "pageSize": 1,
            "sources": ct_google.READ_SOURCES,
        }
    )
    return int(data.get("totalItems") or 0)


def cli(argv=None, opener=None, login=None) -> int:
    args = parse_args(argv)
    try:
        label = ct_book.check_label(args.account)
        if not args.check and os.environ.get("SBK_CONTAINERIZED", "0") == "1":
            # secrets_adapter.set_secret does nothing in container mode: the browser login
            # would end with nothing stored.
            raise ContactsError(
                "container mode has no Keychain to store the login: run ct-l0-auth.py outside "
                f"the container, then give the container {ct_google.env_token_name(label)}"
            )
        if not args.check:
            do_login = login or (
                lambda: __import__("google_oauth").browser_login(
                    ct_google.KEYCHAIN_SERVICE, label, ct_google.SCOPES
                )
            )
            do_login()
        n = check(label, opener=opener)
    except ContactsError as e:
        print(f"contacts: {e}", file=sys.stderr)
        return 2
    print(f"contacts: Google login '{label}' works, {n} contacts readable")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
