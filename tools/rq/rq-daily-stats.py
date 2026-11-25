#!/usr/bin/env python3
""
















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step  # noqa: E402

from sbk_config import (  # noqa: E402
    ENRICHED_DIR,
    OWN_EMAILS,
    RQ_DIR,
    safe_write_parquet,
)

log = logging.getLogger("rq-daily-stats")



PROACTIVE_WINDOW_HOURS = 48


def extract_email(raw: str) -> str:
    ""
    if not raw or not isinstance(raw, str):
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return (m.group(1) if m else raw).strip().lower()


def build_email_to_person_id(contacts_path: Path) -> dict[str, str]:
    ""




    if not contacts_path.exists():
        log.warning("contacts-merged not found: %s — skipping email->pid mapping", contacts_path)
        return {}

    cm = pd.read_parquet(contacts_path, columns=["person_id", "all_emails"])
    mapping: dict[str, str] = {}

    for row in cm.itertuples():
        pid = row.person_id
        raw = row.all_emails
        if not raw or not isinstance(raw, str):
            continue
        try:
            emails = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for email in emails:
            if isinstance(email, str) and email.strip():
                mapping[email.strip().lower()] = pid

    log.info(
        "Built email->person_id mapping: %d emails -> %d persons",
        len(mapping),
        cm["person_id"].nunique(),
    )
    return mapping





def compute_daily_stats(
    df: pd.DataFrame,
    email_to_pid: dict[str, str] | None = None,
) -> pd.DataFrame:
    ""












    output_cols = [
        "date",
        "proactive_outreach_count",
        "new_contacts_count",
        "relationship_maintenance_score",
    ]

    if df.empty:
        return pd.DataFrame(columns=output_cols)

    df = df.copy()


    df["datetime"] = pd.to_datetime(df["date"], format="ISO8601", utc=True)
    df["day"] = df["datetime"].dt.date


    df["from_email"] = df["from_addr"].apply(extract_email)


    df["is_owner_outbound"] = df["from_email"].isin(OWN_EMAILS)




    if email_to_pid is None:
        email_to_pid = {}

    def resolve_inbound_person(row) -> str:
        ""
        if row["is_owner_outbound"]:

            return row["to_addr"]
        else:

            email = row["from_email"]
            return email_to_pid.get(email, email)

    df["contact_id"] = df.apply(resolve_inbound_person, axis=1)




    outbound = df[df["is_owner_outbound"]].copy()
    inbound = df[~df["is_owner_outbound"]].copy()

    if outbound.empty:

        all_days = sorted(df["day"].unique())
        result = pd.DataFrame({"date": all_days})
        result["proactive_outreach_count"] = 0
        result["new_contacts_count"] = 0
        result["relationship_maintenance_score"] = np.nan
        return result


    inbound_times: dict[str, list[pd.Timestamp]] = {}
    for row in inbound.itertuples():
        cid = row.contact_id
        if cid not in inbound_times:
            inbound_times[cid] = []
        inbound_times[cid].append(row.datetime)


    for cid in inbound_times:
        inbound_times[cid].sort()

    window = pd.Timedelta(hours=PROACTIVE_WINDOW_HOURS)

    def is_proactive(row) -> bool:
        ""
        cid = row.contact_id
        if cid not in inbound_times:
            return True
        t = row.datetime
        cutoff = t - window

        times = inbound_times[cid]
        for it in times:
            if cutoff <= it < t:
                return False
        return True

    outbound["is_proactive"] = outbound.apply(is_proactive, axis=1)



    proactive_daily = (
        outbound[outbound["is_proactive"]]
        .groupby("day")["contact_id"]
        .nunique()
        .rename("proactive_outreach_count")
    )



    df_sorted = df.sort_values("datetime")
    first_seen = df_sorted.drop_duplicates(subset=["contact_id"], keep="first")[
        ["contact_id", "day"]
    ]
    new_contacts_daily = (
        first_seen.groupby("day")["contact_id"].count().rename("new_contacts_count")
    )


    all_days = sorted(df["day"].unique())
    result = pd.DataFrame({"date": all_days})
    result = result.set_index("date")
    result = result.join(proactive_daily, how="left")
    result = result.join(new_contacts_daily, how="left")
    result = result.fillna({"proactive_outreach_count": 0, "new_contacts_count": 0})
    result["proactive_outreach_count"] = result["proactive_outreach_count"].astype(int)
    result["new_contacts_count"] = result["new_contacts_count"].astype(int)
    result["relationship_maintenance_score"] = np.nan
    result = result.reset_index()
    result = result.sort_values("date").reset_index(drop=True)

    return result





def main():
    parser = argparse.ArgumentParser(description="RQ daily-stats aggregator")
    parser.add_argument("--input", default=None, help="Override input parquet path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute stats but don't write output"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


    input_path = Path(args.input) if args.input else RQ_DIR / "interaction-weights.parquet"
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    log.info("Loading %s", input_path)
    df = pd.read_parquet(input_path)
    log.info("Loaded %d interactions", len(df))


    contacts_path = ENRICHED_DIR / "contacts-merged.parquet"
    email_to_pid = build_email_to_person_id(contacts_path)


    daily_stats = compute_daily_stats(df, email_to_pid=email_to_pid)
    log.info(
        "Computed daily stats: %d dates, %d columns",
        len(daily_stats),
        len(daily_stats.columns),
    )


    if not daily_stats.empty:
        log.info(
            "Totals — proactive_outreach: %d, new_contacts: %d, dates: %d",
            daily_stats["proactive_outreach_count"].sum(),
            daily_stats["new_contacts_count"].sum(),
            len(daily_stats),
        )

    if args.dry_run:
        log.info("[DRY RUN] Would write to %s", RQ_DIR / "daily-stats.parquet")
        print(daily_stats.describe().to_string())
        return


    out_path = RQ_DIR / "daily-stats.parquet"
    safe_write_parquet(daily_stats, out_path)
    log.info("Written %d rows to %s", len(daily_stats), out_path)


@pipeline_step(name="rq-daily-stats", source="rq-daily-stats", stage="l3")
def run():
    main()


if __name__ == "__main__":
    run()
