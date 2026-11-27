#!/usr/bin/env python3
"""Email pre-filter before extraction: drops automated senders (noreply, notifications, alerts), automated subjects
(out of office, delivery failures, newsletters) and the noise domains you list, from the emails of your
mailboxes, so the extraction stages read only real correspondence.
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import EMAILS_DIR, mail_labels, safe_write_parquet  # noqa: E402

log = logging.getLogger("email-filter")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# Noise senders to drop (notifications, newsletters, SaaS alerts).
# Default empty with a couple of generic examples; load the real list from user config.
NOISE_DOMAINS = {
    "support.example",
    "noreply.example",
    "mailer-daemon.example",
}


NOREPLY_PATTERN = r"(noreply|no-reply|donotreply|do-not-reply|notification|notifications|alert|alerts|automated|autoreply)"


AUTOMATED_SUBJECT_PATTERN = r"(backup|out of office|ooo|undeliverable|delivery.*failure|newsletter|news digest|weekly|daily|automated alert|system alert|calendar invitation)"




def _load_all_emails() -> pd.DataFrame:
    ""
    # your mailboxes: emails/accounts.json, email_accounts in sbk.config.json, emails/<label>/
    email_accounts = mail_labels()
    dfs = []

    for account in email_accounts:
        parquet_path = EMAILS_DIR / account / "messages.parquet"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
            df["_account"] = account
            dfs.append(df)
            log.info(f"Loaded {account}: {len(df)} emails")
        else:
            log.warning(f"Not found: {parquet_path}")

    if not dfs:
        raise FileNotFoundError(f"No email parquet files found in {EMAILS_DIR}")

    return pd.concat(dfs, ignore_index=True)


def _apply_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    ""
    total = len(df)
    stats = {"total": total}


    layer1_mask = df["from_addr"].str.contains("|".join(NOISE_DOMAINS), case=False, na=False)
    layer1_count = layer1_mask.sum()
    stats["layer1_noise_domains"] = layer1_count
    log.info(f"Layer 1 (noise domains): {layer1_count} emails ({100 * layer1_count / total:.1f}%)")


    layer2_mask = df["from_addr"].str.contains(NOREPLY_PATTERN, case=False, na=False, regex=True)
    layer2_count = layer2_mask.sum()
    stats["layer2_noreply"] = layer2_count
    log.info(
        f"Layer 2 (noreply patterns): {layer2_count} emails ({100 * layer2_count / total:.1f}%)"
    )


    layer3_mask = df["subject"].str.contains(
        AUTOMATED_SUBJECT_PATTERN, case=False, na=False, regex=True
    )
    layer3_count = layer3_mask.sum()
    stats["layer3_automated_subject"] = layer3_count
    log.info(
        f"Layer 3 (automated subjects): {layer3_count} emails ({100 * layer3_count / total:.1f}%)"
    )


    body_length = df["body_text"].str.len().fillna(0)
    layer4_mask = body_length < 50
    layer4_count = layer4_mask.sum()
    stats["layer4_body_short"] = layer4_count
    log.info(
        f"Layer 4 (body < 50 chars): {layer4_count} emails ({100 * layer4_count / total:.1f}%)"
    )


    combined_mask = layer1_mask | layer2_mask | layer3_mask | layer4_mask
    filtered_count = combined_mask.sum()
    stats["filtered_total"] = filtered_count
    stats["kept"] = total - filtered_count
    stats["percent_filtered"] = 100 * filtered_count / total

    log.info("\n=== FILTER RESULTS ===")
    log.info(f"Total emails: {total}")
    log.info(f"Filtered out: {filtered_count} ({stats['percent_filtered']:.1f}%)")
    log.info(f"Kept: {stats['kept']} ({100 * (stats['kept'] / total):.1f}%)")


    kept_df = df[~combined_mask].copy()
    return kept_df, stats


def main():
    parser = argparse.ArgumentParser(
        description="Email pre-filter for SBK — remove noise before extraction"
    )
    parser.add_argument(
        "--output",
        default="filtered-messages.parquet",
        help="Output parquet filename (relative to EMAILS_DIR, default: filtered-messages.parquet)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze filters without saving",
    )
    args = parser.parse_args()

    log.info("Loading all email accounts...")
    df = _load_all_emails()

    log.info("\nApplying 4-layer filter...")
    filtered_df, stats = _apply_filters(df)

    if args.dry_run:
        log.info("(DRY-RUN: Not saving)")
    else:
        output_path = EMAILS_DIR / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_parquet(filtered_df, output_path, index=False)
        log.info(f"\nSaved filtered emails to: {output_path}")
        log.info(f"File size: {output_path.stat().st_size / 1e6:.1f} MB")


    log.info("\n=== PER-ACCOUNT BREAKDOWN ===")
    for account in filtered_df["_account"].unique():
        account_count = len(filtered_df[filtered_df["_account"] == account])
        log.info(f"{account}: {account_count} emails kept")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-email-filter", source="l3-email-filter", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
