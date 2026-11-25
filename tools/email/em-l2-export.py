#!/usr/bin/env python3
"""Export the email network (relationship scores, contacts summary, graph) from the L1 contacts and interactions."""













import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import ENRICHED_DIR, EXPORTS_DIR, NOISE_DOMAINS, OWN_EMAILS, safe_write_parquet

log = logging.getLogger("sbk-export")


def is_noise(email: str) -> bool:
    ""
    if not email:
        return True
    if email in OWN_EMAILS:
        return True
    domain = email.split("@")[1] if "@" in email else ""
    if any(noise in domain for noise in NOISE_DOMAINS):
        return True
    if email.startswith(
        (
            "noreply",
            "no-reply",
            "notifications",
            "mailer-daemon",
            "postmaster",
            "info@m.",
            "drive-shares",
            "comments-noreply",
            "calendar-notification",
        )
    ):
        return True

    if "docusign" in email:
        return True
    return False


def compute_relationship_score(row) -> float:
    ""






    now = datetime.now(UTC)


    freq = min(row.get("total_msgs", 0), 500) / 500 * 40


    last = row.get("last_date")
    if pd.notna(last):
        days_ago = (now - last).days
        recency = max(0, 1 - days_ago / 730) * 30
    else:
        recency = 0


    sent = row.get("msgs_sent", 0)
    recv = row.get("msgs_recv", 0)
    if sent + recv > 0:
        balance = min(sent, recv) / max(sent, recv) if max(sent, recv) > 0 else 0
        bidir = balance * 20
    else:
        bidir = 0


    threads = min(row.get("thread_count", 0), 200) / 200 * 10

    return round(freq + recency + bidir + threads, 1)


def export_network(top_n: int = 100):
    ""
    contacts_path = ENRICHED_DIR / "contacts.parquet"
    interactions_path = ENRICHED_DIR / "interactions.parquet"

    if not contacts_path.exists() or not interactions_path.exists():
        log.error("Run gmail-enrich.py first to generate contacts and interactions")
        return

    contacts = pd.read_parquet(contacts_path)
    interactions = pd.read_parquet(interactions_path)


    contacts = contacts[~contacts["email"].apply(is_noise)].copy()



    out_from_owner = (
        interactions[
            interactions["from_email"].isin(OWN_EMAILS) & ~interactions["to_email"].apply(is_noise)
        ]
        .groupby("to_email")
        .agg(
            msgs_sent=("msg_count", "sum"),
            threads_sent=("thread_count", "sum"),
            last_sent=("last_date", "max"),
        )
        .reset_index()
        .rename(columns={"to_email": "email"})
    )


    in_to_owner = (
        interactions[
            interactions["to_email"].isin(OWN_EMAILS) & ~interactions["from_email"].apply(is_noise)
        ]
        .groupby("from_email")
        .agg(
            msgs_recv=("msg_count", "sum"),
            threads_recv=("thread_count", "sum"),
            last_recv=("last_date", "max"),
        )
        .reset_index()
        .rename(columns={"from_email": "email"})
    )


    rel = contacts[["email", "name", "domain", "first_seen", "last_seen"]].copy()
    rel = rel.merge(out_from_owner, on="email", how="left")
    rel = rel.merge(in_to_owner, on="email", how="left")

    rel["msgs_sent"] = rel["msgs_sent"].fillna(0).astype(int)
    rel["msgs_recv"] = rel["msgs_recv"].fillna(0).astype(int)
    rel["total_msgs"] = rel["msgs_sent"] + rel["msgs_recv"]
    rel["thread_count"] = (
        rel.get("threads_sent", pd.Series(0)).fillna(0)
        + rel.get("threads_recv", pd.Series(0)).fillna(0)
    ).astype(int)


    rel["last_date"] = rel[["last_sent", "last_recv"]].max(axis=1)


    rel = rel[rel["total_msgs"] > 0].copy()


    rel["score"] = rel.apply(compute_relationship_score, axis=1)
    rel.sort_values("score", ascending=False, inplace=True)


    score_cols = [
        "email",
        "name",
        "domain",
        "first_seen",
        "last_seen",
        "msgs_sent",
        "msgs_recv",
        "total_msgs",
        "thread_count",
        "last_date",
        "score",
    ]
    safe_write_parquet(rel[score_cols], EXPORTS_DIR / "relationship-scores.parquet", index=False)
    log.info(f"Saved {len(rel)} relationship scores")


    top = rel.head(top_n)
    graph = {
        "generated": datetime.now(UTC).isoformat(),
        "total_contacts": len(rel),
        "nodes": [],
        "summary": {
            "top_10": top.head(10)[["email", "name", "score"]].to_dict("records"),
            "dormant_30d": int(
                (rel["last_date"] < (datetime.now(UTC) - pd.Timedelta(days=30))).sum()
            ),
            "active_7d": int(
                (rel["last_date"] >= (datetime.now(UTC) - pd.Timedelta(days=7))).sum()
            ),
        },
    }

    for _, r in top.iterrows():
        graph["nodes"].append(
            {
                "email": r["email"],
                "name": r["name"],
                "domain": r["domain"],
                "score": r["score"],
                "msgs_sent": int(r["msgs_sent"]),
                "msgs_recv": int(r["msgs_recv"]),
                "first_seen": r["first_seen"].isoformat() if pd.notna(r["first_seen"]) else None,
                "last_date": r["last_date"].isoformat() if pd.notna(r["last_date"]) else None,
            }
        )


    graph_path = EXPORTS_DIR / "email-contacts-summary.json"
    graph_path.write_text(json.dumps(graph, indent=2, default=str))
    log.info(f"Saved email contacts summary: {len(graph['nodes'])} nodes → {graph_path}")


def main():
    parser = argparse.ArgumentParser(description="SBK network export")
    parser.add_argument("--top", type=int, default=100, help="Top N contacts in graph")
    args = parser.parse_args()

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    export_network(args.top)
    log.info("Export complete.")


if __name__ == "__main__":
    main()
