#!/usr/bin/env python3
"""Import a LinkedIn data export into L0."""



































from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import LINKEDIN_RAW_DIR, mark_last_run, safe_write_parquet  # noqa: E402

log = logging.getLogger("li-l0-import-export")

OUTPUT_DIR = LINKEDIN_RAW_DIR


def detect_header_row(filepath: Path, max_scan: int = 10) -> int:
    ""



    with open(filepath, encoding="utf-8") as f:
        for i in range(max_scan):
            line = f.readline()
            if not line:
                break

            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith(("Notes:", '"When ', '"You will')):
                continue

            if "," in stripped and not stripped.startswith('"'):
                return i

            if stripped.startswith('"') and '","' in stripped:
                return i

            if "," in stripped:
                return i
    return 0


def import_csv(filepath: Path, output_name: str, dry_run: bool = False) -> int:
    ""



    if not filepath.exists():
        log.warning(f"  File not found: {filepath.name}")
        return -1

    skip_rows = detect_header_row(filepath)
    try:
        df = pd.read_csv(filepath, skiprows=skip_rows, encoding="utf-8")
    except Exception as e:
        log.error(f"  Failed to parse {filepath.name}: {e}")
        return -1


    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    row_count = len(df)
    col_info = ", ".join(df.columns[:6])
    if len(df.columns) > 6:
        col_info += f" (+{len(df.columns) - 6} more)"

    log.info(f"  {filepath.name}: {row_count} rows, cols=[{col_info}]")

    if not dry_run:
        out_path = OUTPUT_DIR / f"{output_name}.parquet"
        safe_write_parquet(df, out_path, index=False)
        log.info(f"    -> {out_path}")

    return row_count


def import_connections(source_dir: Path, dry_run: bool = False) -> int:
    ""
    filepath = source_dir / "Connections.csv"
    if not filepath.exists():
        log.warning(f"  File not found: {filepath.name}")
        return -1



    header_row = 0
    with open(filepath, encoding="utf-8") as f:
        for i, line in enumerate(f):
            stripped = line.strip()
            if stripped.startswith("First Name,") or stripped.startswith('"First Name"'):
                header_row = i
                break

    try:
        df = pd.read_csv(filepath, skiprows=header_row, encoding="utf-8")
    except Exception as e:
        log.error(f"  Failed to parse {filepath.name}: {e}")
        return -1

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]


    if "first_name" in df.columns and "last_name" in df.columns:
        df["name"] = (
            df["first_name"].fillna("").str.strip() + " " + df["last_name"].fillna("").str.strip()
        ).str.strip()


    if "url" in df.columns:
        df.rename(columns={"url": "linkedin_url"}, inplace=True)

    row_count = len(df)
    email_count = df["email_address"].notna().sum() if "email_address" in df.columns else 0
    log.info(f"  Connections.csv: {row_count} connections, {email_count} with email addresses")

    if not dry_run:
        out_path = OUTPUT_DIR / "export-connections.parquet"
        safe_write_parquet(df, out_path, index=False)
        log.info(f"    -> {out_path}")

    return row_count


def import_invitations(source_dir: Path, dry_run: bool = False) -> int:
    ""
    filepath = source_dir / "Invitations.csv"
    if not filepath.exists():
        log.warning(f"  File not found: {filepath.name}")
        return -1

    try:
        df = pd.read_csv(filepath, encoding="utf-8")
    except Exception as e:
        log.error(f"  Failed to parse {filepath.name}: {e}")
        return -1

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]


    renames = {}
    if "inviterprofileurl" in df.columns:
        renames["inviterprofileurl"] = "inviter_url"
    if "inviteeprofileurl" in df.columns:
        renames["inviteeprofileurl"] = "invitee_url"
    if "sent_at" in df.columns:
        renames["sent_at"] = "sent_at"
    if renames:
        df.rename(columns=renames, inplace=True)



    def get_other_url(row):
        if row.get("direction") == "OUTGOING":
            return row.get("invitee_url", "")
        return row.get("inviter_url", "")

    def get_other_name(row):
        if row.get("direction") == "OUTGOING":
            return row.get("to", "")
        return row.get("from", "")

    df["person_url"] = df.apply(get_other_url, axis=1)
    df["person_name"] = df.apply(get_other_name, axis=1)


    outgoing = (df["direction"] == "OUTGOING").sum() if "direction" in df.columns else 0
    incoming = (df["direction"] == "INCOMING").sum() if "direction" in df.columns else 0
    with_msg = df["message"].notna().sum() if "message" in df.columns else 0

    row_count = len(df)
    log.info(
        f"  Invitations.csv: {row_count} invitations "
        f"({outgoing} outgoing, {incoming} incoming, {with_msg} with message)"
    )

    if not dry_run:
        out_path = OUTPUT_DIR / "export-invitations.parquet"
        safe_write_parquet(df, out_path, index=False)
        log.info(f"    -> {out_path}")

    return row_count


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Export Import — SBK L0")
    parser.add_argument(
        "--source",
        default="export-part1",
        help="Source directory name (default: export-part1)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    source_dir = LINKEDIN_RAW_DIR / args.source
    if not source_dir.exists():
        log.error(f"Source directory not found: {source_dir}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info(f"LINKEDIN EXPORT IMPORT — {args.source}")
    log.info(f"Source: {source_dir}")
    log.info("=" * 60)

    t0 = time.time()
    totals = {}


    totals["connections"] = import_connections(source_dir, args.dry_run)


    totals["invitations"] = import_invitations(source_dir, args.dry_run)


    totals["endorsements_received"] = import_csv(
        source_dir / "Endorsement_Received_Info.csv",
        "export-endorsements-received",
        args.dry_run,
    )
    totals["endorsements_given"] = import_csv(
        source_dir / "Endorsement_Given_Info.csv",
        "export-endorsements-given",
        args.dry_run,
    )


    totals["company_follows"] = import_csv(
        source_dir / "Company Follows.csv",
        "export-company-follows",
        args.dry_run,
    )


    totals["positions"] = import_csv(
        source_dir / "Positions.csv",
        "export-positions",
        args.dry_run,
    )


    totals["skills"] = import_csv(
        source_dir / "Skills.csv",
        "export-skills",
        args.dry_run,
    )


    totals["profile"] = import_csv(
        source_dir / "Profile.csv",
        "export-profile",
        args.dry_run,
    )

    elapsed = time.time() - t0
    log.info("")
    log.info("=" * 60)
    log.info("IMPORT COMPLETE")
    log.info("=" * 60)
    for name, count in totals.items():
        status = f"{count} rows" if count >= 0 else "MISSING"
        log.info(f"  {name:25s}: {status}")
    total_rows = sum(c for c in totals.values() if c >= 0)
    log.info(f"  {'TOTAL':25s}: {total_rows} rows in {elapsed:.1f}s")

    mark_last_run("linkedin-export")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-linkedin-import", source="linkedin", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
