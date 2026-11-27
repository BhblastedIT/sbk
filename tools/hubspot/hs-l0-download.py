#!/usr/bin/env python3
"""L0 HubSpot: download your contacts, companies, deals, notes and tasks.

Uses the login stored by hs-l0-auth.py (your own user-level app). By default it reads the
records you own (hubspot_owner_id = you); --all-visible reads everything your HubSpot user
can see. Incremental: each object type continues from the last complete run, minus
hubspot.overlap_hours. Writes under ~/.sbk-data/hubspot/ (or $SBK_DATA_ROOT/hubspot/):

  raw/{contacts,companies,deals,notes,tasks,pipelines,me}.json
  state.json                 watermarks and records whose links are still to read
  download-summary.json      what this run did

Read-only: GET, plus POST to the search and batch-read endpoints only.

    uv run python tools/hubspot/hs-l0-download.py
    uv run python tools/hubspot/hs-l1-enrich.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hs_api  # noqa: E402

ALL_TYPES = ("contacts", *hs_api.ITEM_TYPES)


def _types(value: str) -> tuple[str, ...]:
    wanted = tuple(x.strip() for x in value.split(",") if x.strip())
    bad = [x for x in wanted if x not in ALL_TYPES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown type(s) {', '.join(bad)}; use {','.join(ALL_TYPES)}"
        )
    return wanted


def connect(label: str):
    """(client, me) for the stored login. Raises HubSpotError with a one-line message."""
    cid, secret = hs_api.client_id(), hs_api.client_secret()
    if not cid or not secret:
        raise hs_api.HubSpotError(hs_api.no_app_message())
    refresh, _where = hs_api.load_refresh_token(label)
    if not refresh:
        raise hs_api.AuthError(
            f"HubSpot: not signed in; run tools/hubspot/hs-l0-auth.py first ({hs_api.SETUP_HINT})"
        )
    holder = {"refresh": refresh}
    notes: list[str] = []  # becomes client.warnings, copied into download-summary.json

    def new_access() -> str:
        tok = hs_api.refresh_access(cid, secret, holder["refresh"])
        newer = tok.get("refresh_token") or ""
        if newer and newer != holder["refresh"]:
            holder["refresh"] = newer
            if not hs_api.save_refresh_token(newer, label):
                # container mode without HUBSPOT_TOKEN_FILE: nowhere to keep it
                msg = (
                    "HubSpot issued a new refresh token that could not be stored (no Keychain "
                    f"and no {hs_api.ENV_TOKEN_FILE}); if the old one stops working, set "
                    f"{hs_api.ENV_TOKEN_FILE} and sign in again with hs-l0-auth.py"
                )
                if msg not in notes:
                    notes.append(msg)
        if not tok.get("access_token"):
            raise hs_api.AuthError(
                "HubSpot: no access token in the answer; run hs-l0-auth.py again"
            )
        return tok["access_token"]

    access = new_access()
    me = hs_api.describe_token(hs_api.introspect(cid, secret, access))
    hs_api.check_user_level(me)
    client = hs_api.HubSpotClient(access, refresher=new_access)
    client.warnings = notes
    return client, me


def _int_cfg(key: str, default: int) -> int:
    """An integer setting from sbk.config.json; a value that is not a number keeps the default."""
    try:
        return int(hs_api.cfg(key, default))
    except (TypeError, ValueError):
        print(f"HubSpot: hubspot.{key} in sbk.config.json is not a number, using {default}")
        return default


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Download your HubSpot contacts, companies, deals, notes and tasks "
        "(read-only, your own user-level app)."
    )
    ap.add_argument("--label", default=hs_api.DEFAULT_LABEL, help="login name (default: default)")
    ap.add_argument(
        "--full", action="store_true", help="ignore the saved state and read everything again"
    )
    ap.add_argument(
        "--all-visible",
        action="store_true",
        help="read every record your HubSpot user can see, not only the ones you own",
    )
    ap.add_argument(
        "--types",
        type=_types,
        default=ALL_TYPES,
        help=f"comma-separated subset of {','.join(ALL_TYPES)} (default: all)",
    )
    ap.add_argument(
        "--max-details",
        type=int,
        default=None,
        help="at most this many single-record reads (links to contacts/companies) per run; "
        "the rest waits for the next run (default: hubspot.max_details or 2000)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    only_mine = bool(hs_api.cfg("only_mine", True)) and not args.all_visible
    try:
        client, me = connect(args.label)
        stats = hs_api.run_download(
            client,
            me,
            types=args.types,
            full=args.full,
            only_mine=only_mine,
            max_details=(
                args.max_details if args.max_details is not None else _int_cfg("max_details", 2000)
            ),
            overlap_hours=_int_cfg("overlap_hours", 24),
            history_days=_int_cfg("history_days", 0),
        )
    except hs_api.HubSpotError as e:
        msg = str(e)
        print(msg if msg.startswith("HubSpot") else f"HubSpot: {msg}", file=sys.stderr)
        return 1

    if not args.quiet:
        for k in ("contacts_found", "deals_found", "tasks_found", "notes_found"):
            if k in stats:
                print(f"  {k:<28} {stats[k]}")
        for k, v in sorted(stats.items()):
            if k.endswith("_left_for_next_run") and v:
                print(f"  {k:<28} {v}")
        print(f"  only mine applied            {stats.get('only_mine_applied')}")
        print(f"  api requests                 {stats.get('api_requests')}")
        for w in stats.get("warnings", []):
            print(f"  warning: {w}")
        print(f"  summary: {hs_api.summary_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
