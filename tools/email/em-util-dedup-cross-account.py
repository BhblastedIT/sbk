#!/usr/bin/env python3
"""Cross-account dedup: drop copies of origin-mailbox messages from secondary mailboxes.

A message is removed from a secondary account only if it exists in the origin
mailbox and no longer exists in the secondary one. The default is a dry-run plan;
pass --apply to write.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from googleapiclient.errors import HttpError

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
import google_oauth  # noqa: E402

from sbk_config import EMAILS_DIR  # noqa: E402


def service(label: str):
    """Gmail client of one of your mailboxes, from its own login (em-l0-auth.py)."""
    return google_oauth.gmail_service(label)


def exists(svc, mid: str) -> str:
    """Return "yes", "no" or "error:<reason>" for a message id."""
    for attempt in range(3):
        try:
            svc.users().messages().get(userId="me", id=mid, format="minimal").execute()
            return "yes"
        except HttpError as e:
            if e.resp.status == 404:
                return "no"
            if e.resp.status in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return f"error:{e.resp.status}"
        except Exception as e:  # noqa: BLE001
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return f"error:{type(e).__name__}"
    return "error:retries"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--origin", required=True, help="label of the origin mailbox")
    ap.add_argument("--apply", action="store_true", help="actually write (default: plan only)")
    ap.add_argument("--log", type=Path, help="row-by-row TSV log (default: next to the data)")
    args = ap.parse_args()

    accounts = json.loads((EMAILS_DIR / "accounts.json").read_text(encoding="utf-8"))
    ORIGIN = args.origin
    origin_pq = EMAILS_DIR / ORIGIN / "messages.parquet"
    origin_df = pd.read_parquet(origin_pq)
    origin_ids = set(origin_df["id"])
    origin_svc = service(ORIGIN)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = args.log or (EMAILS_DIR / f"_dedup-cross-account-{stamp}.tsv")
    log_rows = []
    total_outcome = {}
    origin_cache: dict[str, str] = {}

    for account in accounts:
        if account == ORIGIN:
            continue
        pq = EMAILS_DIR / account / "messages.parquet"
        if not pq.exists():
            continue
        df = pd.read_parquet(pq)
        suspects = sorted(set(df["id"]) & origin_ids)
        if not suspects:
            continue
        svc = service(account)
        to_remove = []
        for i, mid in enumerate(suspects, 1):
            if mid not in origin_cache:
                origin_cache[mid] = exists(origin_svc, mid)
            in_origin = origin_cache[mid]
            in_mailbox = exists(svc, mid)
            remove = in_origin == "yes" and in_mailbox == "no"
            reason = (
                "copy: exists only in the origin mailbox"
                if remove
                else f"keep: origin={in_origin}, mailbox={in_mailbox}"
            )
            log_rows.append((account, mid, in_origin, in_mailbox, remove, reason))
            if remove:
                to_remove.append(mid)
            if i % 100 == 0:
                print(f"  [{account}] {i}/{len(suspects)} checked", flush=True)
        total_outcome[account] = {
            "rows": len(df),
            "suspects": len(suspects),
            "to_remove": len(to_remove),
            "kept": len(suspects) - len(to_remove),
        }
        print(f"[{account}] {total_outcome[account]}", flush=True)

        if args.apply and to_remove:
            backup = pq.parent / ".backup" / f"messages.parquet.{stamp}-pre-dedup"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(pq.read_bytes())
            keep = df[~df["id"].isin(set(to_remove))]
            assert len(keep) == len(df) - len(to_remove)
            keep.to_parquet(pq)
            print(f"[{account}] written: {len(df)} -> {len(keep)} rows (backup {backup.name})")

    pd.DataFrame(
        log_rows,
        columns=["mailbox", "id", "in_origin", "in_mailbox", "to_remove", "reason"],
    ).to_csv(log_path, sep="\t", index=False)
    print(f"log: {log_path}")
    print(json.dumps(total_outcome, indent=1))
    if not args.apply:
        print("plan only: nothing written (use --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
