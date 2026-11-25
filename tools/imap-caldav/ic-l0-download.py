#!/usr/bin/env python3
"""imap-caldav L0: your mailboxes over IMAP (TLS) and your calendars over CalDAV or an ICS link.

Writes into the kernel's existing slots, so the kernel's own L1 reads them unchanged:
  <data root>/emails/<account>/messages.parquet   -> tools/email/em-l1-enrich.py   (stage "email")
  <data root>/calendars/<account>/events.parquet  -> tools/calendar/ca-l1-extract.py (stage "calendar")
Own files: <data root>/imap-caldav/ (state per account, uid map, raw calendar objects,
download-summary.json).

Incremental: IMAP by UIDVALIDITY + last UID per folder (and MODSEQ for flag changes when the
server offers CONDSTORE); CalDAV by calendar ctag, then object ETag; ICS by ETag/Last-Modified.
Read-only on the server: EXAMINE + BODY.PEEK (nothing is marked as read), PROPFIND/REPORT/GET.

Usage:
  uv run python tools/imap-caldav/ic-l0-download.py               # every account in sbk.config.json
  uv run python tools/imap-caldav/ic-l0-download.py --account demo --mail-only
  uv run python tools/imap-caldav/ic-l0-download.py --check       # sign in and list, download nothing
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:  # same .env as the other plugins; values already in the environment win
    from dotenv import load_dotenv

    load_dotenv(_HERE.parent.parent / ".env", override=False)
except ImportError:  # pragma: no cover
    pass

import ic_common as icc  # noqa: E402

log = logging.getLogger("imap-caldav")


def _missing_credentials(acc: icc.Account, want_mail: bool, want_cal: bool) -> list[str]:
    errs = []
    try:
        if want_mail and acc.mail:
            if acc.auth == "password":
                icc.require_secret("sbk-mailbox", acc, "mailbox password")
            elif not icc.get_secret("sbk-imap-oauth", acc.label):
                errs.append(
                    f"{icc.PLUGIN_ID}: no Outlook.com sign-in for '{acc.label}' (Keychain "
                    f"sbk-imap-oauth/{acc.label} or env {icc.env_name('sbk-imap-oauth', acc.label)}); "
                    f"run tools/imap-caldav/ic-l0-auth.py --account {acc.label} --xoauth2"
                )
        if want_cal and acc.calendar == "caldav":
            icc.require_secret("sbk-caldav", acc, "CalDAV app password")
        if want_cal and acc.calendar == "ics":
            icc.require_secret("sbk-ics", acc, "calendar link")
    except icc.SetupError as e:
        errs.append(str(e))
    return errs


def run_account(acc: icc.Account, args) -> dict:
    import ic_caldav
    import ic_imap

    out: dict = {}
    state = icc.load_state(acc.label)
    if not args.calendar_only and acc.mail:
        t0 = time.monotonic()
        log.info(f"{acc.label}: mail ({acc.imap_host})")
        try:
            res = ic_imap.sync_account(
                acc, state, since=args.since or acc.mail_since, force=args.force, log=log
            )
            res["seconds"] = round(time.monotonic() - t0, 1)
            out["mail"] = res
        except icc.SetupError as e:
            out["mail"] = {"error": str(e)}
            log.error(str(e))
        except Exception as e:  # noqa: BLE001 - one mailbox never stops the others
            msg = f"{icc.PLUGIN_ID}: '{acc.label}' mail failed: {type(e).__name__}: {e}"
            out["mail"] = {"error": msg}
            log.error(msg)
    if not args.mail_only and acc.calendar != "none":
        t0 = time.monotonic()
        log.info(f"{acc.label}: calendar ({acc.calendar})")
        try:
            if acc.calendar == "caldav":
                res = ic_caldav.sync_caldav(acc, state, force=args.force, log=log)
            else:
                res = ic_caldav.sync_ics(acc, state, force=args.force, log=log)
            res.update(ic_caldav.rebuild_events(acc, log))
            res["seconds"] = round(time.monotonic() - t0, 1)
            out["calendar"] = res
            log.info(f"  events in the slot: {res['events']}")
        except icc.SetupError as e:
            out["calendar"] = {"error": str(e)}
            log.error(str(e))
        except Exception as e:  # noqa: BLE001
            msg = f"{icc.PLUGIN_ID}: '{acc.label}' calendar failed: {type(e).__name__}: {e}"
            out["calendar"] = {"error": msg}
            log.error(msg)
    return out


def check_account(acc: icc.Account, args) -> dict:
    """Sign in and list folders / calendars; nothing is downloaded or written to the slots."""
    import ic_caldav
    import ic_imap

    out: dict = {}
    if not args.calendar_only and acc.mail:
        pw = icc.get_secret("sbk-mailbox", acc.label) if acc.auth == "password" else None
        conn, caps = ic_imap.connect(acc, pw)
        try:
            folders = ic_imap.list_folders(conn)
            chosen = ic_imap.choose_folders(folders, acc.folders)
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        out["mail"] = {
            "folders": len(folders),
            "would_read": [f["name"] for f in chosen],
            "condstore": "CONDSTORE" in caps,
        }
        print(f"{acc.label}: IMAP ok, {len(folders)} folders, would read: "
              + ", ".join(f["name"] for f in chosen))  # fmt: skip
    if not args.mail_only and acc.calendar == "caldav":
        pw = icc.get_secret("sbk-caldav", acc.label) or ""
        dav = ic_caldav.CalDav(acc.caldav_url, acc.caldav_username or acc.username or acc.email, pw)
        cals = dav.discover()
        out["calendar"] = {"calendars": [c["name"] for c in cals]}
        print(
            f"{acc.label}: CalDAV ok, calendars: " + ", ".join(c["name"] or c["href"] for c in cals)
        )
    elif not args.mail_only and acc.calendar == "ics":
        print(f"{acc.label}: calendar link stored (it is read at the next download)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="imap-caldav L0: IMAP mail and CalDAV/ICS calendars into the mail and calendar slots."
    )
    ap.add_argument("--account", action="append", help="only this account label (repeatable)")
    ap.add_argument("--mail-only", action="store_true", help="skip calendars")
    ap.add_argument("--calendar-only", action="store_true", help="skip mail")
    ap.add_argument("--since", help="YYYY-MM-DD, first mail run only (default: account mail_since)")
    ap.add_argument(
        "--force", action="store_true", help="re-check every folder and calendar object"
    )
    ap.add_argument("--check", action="store_true", help="sign in and list, download nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )
    for noisy in ("sbk_config", "sbk", "sbk.secrets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.mail_only and args.calendar_only:
        print(
            f"{icc.PLUGIN_ID}: --mail-only and --calendar-only exclude each other", file=sys.stderr
        )
        return 2

    try:
        accounts = icc.load_accounts()
    except icc.SetupError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.account:
        wanted = set(args.account)
        unknown = wanted - {a.label for a in accounts}
        if unknown:
            print(f"{icc.PLUGIN_ID}: unknown account {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        accounts = [a for a in accounts if a.label in wanted]

    ready, errors = [], []
    for acc in accounts:
        errs = _missing_credentials(acc, not args.calendar_only, not args.mail_only)
        (errors.extend(errs) if errs else ready.append(acc))
    for e in errors:
        print(e, file=sys.stderr)
    if not ready:
        return 2

    if args.check:
        rc = 0
        for acc in ready:
            try:
                check_account(acc, args)
            except Exception as e:  # noqa: BLE001
                print(
                    f"{icc.PLUGIN_ID}: '{acc.label}' check failed: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                rc = 1
        return rc

    cfg = icc.cfg
    cfg.DATA_ROOT.mkdir(parents=True, exist_ok=True)  # a fresh install has no data root yet
    if not cfg.acquire_pid_lock("ic-l0-download", logger=log):
        return 1
    started = datetime.now(UTC).isoformat(timespec="seconds")
    results: dict = {}
    try:
        for acc in ready:
            results[acc.label] = run_account(acc, args)
    finally:
        release = getattr(cfg, "release_pid_lock", None)
        if release:
            try:
                release("ic-l0-download")
            except Exception:  # noqa: BLE001
                pass
    failed = sorted(
        f"{label}/{part}" for label, r in results.items() for part, v in r.items() if "error" in v
    )
    summary = {
        "plugin": icc.PLUGIN_ID,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "accounts": results,
        "missing_credentials": errors,
        "failed": failed,
        "slots": {
            "mail": str(cfg.EMAILS_DIR / "<account>" / "messages.parquet"),
            "calendar": str(cfg.CALENDARS_DIR / "<account>" / "events.parquet"),
        },
    }
    icc.write_json(icc.summary_path(), summary)
    if not failed and not errors:
        cfg.mark_last_run(icc.PLUGIN_ID)
    log.info(f"summary: {icc.summary_path()}")
    return 1 if (failed or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
