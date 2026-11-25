#!/usr/bin/env python3
"""imap-caldav: store the personal credentials of one account in the Keychain.

  --imap     your mailbox's app-specific password          -> Keychain sbk-mailbox/<account>
  --caldav   your CalDAV app password                       -> Keychain sbk-caldav/<account>
  --ics      your calendar link (https:// or webcal://)     -> Keychain sbk-ics/<account>
  --xoauth2  Outlook.com: sign in once with the device code flow of your own app registration;
             the refresh token goes to Keychain sbk-imap-oauth/<account>

Secrets are typed at a hidden prompt (never on the command line, so not in shell history).
Without a Keychain (containers) set the env vars named in docs/CONNECTING.md instead.

Usage:
  uv run python tools/imap-caldav/ic-l0-auth.py --account demo --imap --caldav
  uv run python tools/imap-caldav/ic-l0-auth.py --account demo_outlook --xoauth2
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ic_common as icc  # noqa: E402

DEVICE_TIMEOUT_S = 900


def _store(service: str, account: str, value: str) -> None:
    import os

    if os.environ.get("SBK_CONTAINERIZED", "0") == "1":
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: no Keychain in container mode: set {icc.env_name(service, account)} "
            "in the environment instead"
        )
    icc.set_secret(service, account, value)
    print(f"stored in the Keychain as {service}/{account}")


def _prompt(label: str) -> str:
    value = getpass.getpass(f"{label}: ").strip()
    if not value:
        raise icc.SetupError(f"{icc.PLUGIN_ID}: nothing typed, nothing stored")
    return value


def device_code_login(acc: icc.Account, *, sleep=time.sleep, echo=print) -> str:
    """OAuth 2.0 device authorization grant against the consumers authority; returns the
    refresh token. Scope: IMAP.AccessAsUser.All + offline_access (delegated, your own mailbox)."""
    form = urllib.parse.urlencode(
        {"client_id": acc.oauth_client_id, "scope": icc.MS_IMAP_SCOPE}
    ).encode()
    status, _h, data, _u = icc.http_request(
        "POST", f"{icc.MS_AUTHORITY}/devicecode",
        {"Content-Type": "application/x-www-form-urlencoded"}, form,
    )  # fmt: skip
    try:
        dc = json.loads(data.decode("utf-8") or "{}")
    except ValueError:
        dc = {}
    if status != 200 or "device_code" not in dc:
        raise icc.SetupError(
            f"{icc.PLUGIN_ID}: device code request refused ({dc.get('error', f'HTTP {status}')}): "
            "check oauth_client_id and that 'Allow public client flows' is on in your app registration"
        )
    echo(
        dc.get("message")
        or f"Open {dc.get('verification_uri')} and enter the code {dc.get('user_code')}"
    )
    interval = int(dc.get("interval", 5) or 5)
    deadline = time.monotonic() + min(
        int(dc.get("expires_in", DEVICE_TIMEOUT_S) or DEVICE_TIMEOUT_S), DEVICE_TIMEOUT_S
    )
    while time.monotonic() < deadline:
        sleep(interval)
        form = urllib.parse.urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": acc.oauth_client_id,
                "device_code": dc["device_code"],
            }
        ).encode()
        status, _h, data, _u = icc.http_request(
            "POST", f"{icc.MS_AUTHORITY}/token",
            {"Content-Type": "application/x-www-form-urlencoded"}, form,
        )  # fmt: skip
        try:
            tok = json.loads(data.decode("utf-8") or "{}")
        except ValueError:
            tok = {}
        if status == 200 and tok.get("refresh_token"):
            return tok["refresh_token"]
        err = tok.get("error", f"HTTP {status}")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise icc.SetupError(f"{icc.PLUGIN_ID}: sign-in not completed ({err})")
    raise icc.SetupError(f"{icc.PLUGIN_ID}: sign-in not completed in time, run it again")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Store the personal credentials of one imap-caldav account."
    )
    ap.add_argument(
        "--account", required=True, help="account label from sbk.config.json imap_caldav.accounts"
    )
    ap.add_argument("--imap", action="store_true", help="ask for the mailbox app-specific password")
    ap.add_argument("--caldav", action="store_true", help="ask for the CalDAV app password")
    ap.add_argument(
        "--ics", action="store_true", help="ask for the calendar link (https or webcal)"
    )
    ap.add_argument(
        "--xoauth2", action="store_true", help="Outlook.com: sign in with the device code flow"
    )
    args = ap.parse_args(argv)
    if not (args.imap or args.caldav or args.ics or args.xoauth2):
        print(
            f"{icc.PLUGIN_ID}: say what to store: --imap, --caldav, --ics or --xoauth2",
            file=sys.stderr,
        )
        return 2
    try:
        accounts = {a.label: a for a in icc.load_accounts()}
        acc = accounts.get(args.account)
        if acc is None:
            raise icc.SetupError(
                f"{icc.PLUGIN_ID}: account '{args.account}' is not in sbk.config.json"
            )
        if args.imap:
            _store(
                "sbk-mailbox",
                acc.label,
                _prompt(f"App password for {acc.username} on {acc.imap_host}"),
            )
        if args.caldav:
            _store(
                "sbk-caldav",
                acc.label,
                _prompt(f"CalDAV app password for {acc.caldav_username or acc.username}"),
            )
        if args.ics:
            url = _prompt("Calendar link (input hidden)")
            if not url.lower().startswith(("https://", "webcal://")):
                raise icc.SetupError(
                    f"{icc.PLUGIN_ID}: the link must start with https:// or webcal://"
                )
            _store("sbk-ics", acc.label, url)
        if args.xoauth2:
            if not acc.oauth_client_id:
                raise icc.SetupError(
                    f"{icc.PLUGIN_ID}: set oauth_client_id for '{acc.label}' in sbk.config.json first"
                )
            _store("sbk-imap-oauth", acc.label, device_code_login(acc))
    except icc.SetupError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"next: uv run python tools/imap-caldav/ic-l0-download.py --account {acc.label} --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
