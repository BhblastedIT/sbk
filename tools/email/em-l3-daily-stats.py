#!/usr/bin/env python3
"""Aggregate email daily stats (counts, threads, response time, sentiment) from the L0/L1 messages (L3)."""


















import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step  # noqa: E402

from sbk_config import (  # noqa: E402
    EMAILS_DIR,
    OWN_EMAILS,
    is_noise_domain,
    safe_write_parquet,
)

log = logging.getLogger("em-l3-daily-stats")



RESPONSE_TIME_CAP_MIN = 10080

INT_COLS = [
    "email_sent_count",
    "email_received_count",
    "email_total_count",
    "email_thread_count",
    "email_new_thread_count",
    "email_reply_count",
    "email_unique_contacts",
    "email_attachment_count",
]





def parse_email_addr(raw: str) -> str:
    ""
    if not raw or not isinstance(raw, str):
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return (m.group(1) if m else raw).strip().lower()


def parse_email_list(raw: str) -> list[str]:
    ""
    if not raw or not isinstance(raw, str):
        return []
    addrs = []
    for part in raw.split(","):
        addr = parse_email_addr(part.strip())
        if addr and "@" in addr:
            addrs.append(addr)
    return addrs


def extract_external_contacts(row) -> set[str]:
    ""
    contacts = set()
    for field in ["from_addr", "to_addr", "cc"]:
        val = row.get(field, "")
        for addr in parse_email_list(val):
            if addr not in OWN_EMAILS and not is_noise_domain(addr.split("@")[-1]):
                contacts.add(addr)
    return contacts


_POS_WORDS = frozenset(
    {
        "thank",
        "thanks",
        "great",
        "happy",
        "pleased",
        "excellent",
        "perfect",
        "awesome",
        "congrats",
        "congratulations",
        "well done",
        "appreciate",
        "wonderful",
        "fantastic",
        "grazie",
        "ottimo",
        "perfetto",
        "contento",
        "fantastico",
        "bravo",
        "complimenti",
        "eccellente",
        "benissimo",
    }
)
_NEG_WORDS = frozenset(
    {
        "sorry",
        "unfortunately",
        "issue",
        "problem",
        "complaint",
        "urgent",
        "mistake",
        "error",
        "delay",
        "disappointed",
        "fail",
        "wrong",
        "broken",
        "concerned",
        "scusa",
        "purtroppo",
        "problema",
        "urgente",
        "errore",
        "ritardo",
        "sbagliato",
        "deluso",
        "preoccupato",
    }
)


def _compute_sentiment(text: str) -> float:
    ""
    if not text or len(text) < 20:
        return 0.0
    text_lower = text.lower()
    pos = sum(1 for w in _POS_WORDS if w in text_lower)
    neg = sum(1 for w in _NEG_WORDS if w in text_lower)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 2)





def compute_daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    ""







    if df.empty:
        return pd.DataFrame(
            columns=["date"]
            + INT_COLS
            + [
                "email_avg_response_min",
                "email_median_response_min",
                "email_avg_sentiment",
            ]
        )


    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df["day"] = df["date"].dt.date


    df["is_sent"] = df["labels"].str.contains("SENT", na=False)


    sent = df[df["is_sent"]].groupby("day").agg(email_sent_count=("id", "count"))


    received = df[~df["is_sent"]].groupby("day").agg(email_received_count=("id", "count"))


    all_daily = df.groupby("day").agg(
        email_total_count=("id", "count"),
        email_thread_count=("thread_id", "nunique"),
        email_reply_count=("in_reply_to", lambda x: x.notna().sum() & (x.str.len() > 0).sum()),
        email_attachment_count=("attachment_count", "sum"),
    )


    reply_counts = df.groupby("day").apply(
        lambda g: ((g["in_reply_to"].notna()) & (g["in_reply_to"].str.len() > 0)).sum()
    )
    reply_counts.name = "email_reply_count"
    all_daily["email_reply_count"] = reply_counts


    thread_first_date = df.groupby("thread_id")["date"].min().dt.date
    new_threads_daily = thread_first_date.value_counts().sort_index()
    new_threads_daily.name = "email_new_thread_count"



    has_msg_id = df["message_id"].notna() & (df["message_id"].str.len() > 0)
    msg_df = df.loc[has_msg_id, ["message_id", "date", "is_sent"]].drop_duplicates(
        subset=["message_id"], keep="first"
    )
    msg_lookup = msg_df.set_index("message_id")[["date", "is_sent"]].to_dict("index")


    sent_replies = df[
        (df["is_sent"]) & (df["in_reply_to"].notna()) & (df["in_reply_to"].str.len() > 0)
    ]

    response_times = []
    for _, row in sent_replies.iterrows():
        parent = msg_lookup.get(row["in_reply_to"])
        if parent and not parent["is_sent"]:
            delta = (row["date"] - parent["date"]).total_seconds() / 60
            if 0 < delta < RESPONSE_TIME_CAP_MIN:
                response_times.append(
                    {
                        "day": row["day"],
                        "response_min": delta,
                    }
                )

    if response_times:
        rt_df = pd.DataFrame(response_times)
        rt_daily = rt_df.groupby("day")["response_min"].agg(
            email_avg_response_min="mean",
            email_median_response_min="median",
        )
    else:
        rt_daily = pd.DataFrame(
            columns=["email_avg_response_min", "email_median_response_min"],
            dtype=float,
        )
        rt_daily.index.name = "day"


    daily_contacts = df.groupby("day").apply(
        lambda g: len(set().union(*g.apply(extract_external_contacts, axis=1)))
    )
    daily_contacts.name = "email_unique_contacts"


    daily_stats = (
        sent.join(received, how="outer")
        .join(
            all_daily[
                [
                    "email_total_count",
                    "email_thread_count",
                    "email_reply_count",
                    "email_attachment_count",
                ]
            ],
            how="outer",
        )
        .join(rt_daily, how="outer")
        .join(new_threads_daily, how="outer")
        .join(daily_contacts, how="outer")
    )


    fill_zeros = {col: 0 for col in INT_COLS}
    daily_stats = daily_stats.fillna(fill_zeros)
    daily_stats[INT_COLS] = daily_stats[INT_COLS].astype(int)


    if "body_text" in df.columns:
        df["_sentiment"] = df["body_text"].fillna("").apply(_compute_sentiment)
        sentiment_daily = df.groupby("day")["_sentiment"].mean()
        daily_stats = daily_stats.join(sentiment_daily.rename("email_avg_sentiment"), how="left")
        daily_stats["email_avg_sentiment"] = daily_stats["email_avg_sentiment"].fillna(0.0)
    else:
        daily_stats["email_avg_sentiment"] = 0.0


    daily_stats = daily_stats.reset_index().rename(columns={"day": "date"})
    daily_stats = daily_stats.sort_values("date").reset_index(drop=True)

    return daily_stats





def main():
    parser = argparse.ArgumentParser(description="Email daily-stats aggregator")
    parser.add_argument("--input", default=None, help="Override input parquet path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute stats but don't write output"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


    input_path = Path(args.input) if args.input else EMAILS_DIR / "filtered-messages.parquet"
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    log.info("Loading %s", input_path)
    df = pd.read_parquet(input_path)
    log.info("Loaded %d messages", len(df))


    daily_stats = compute_daily_stats(df)
    log.info(
        "Computed daily stats: %d dates, %d columns", len(daily_stats), len(daily_stats.columns)
    )


    if not daily_stats.empty:
        log.info(
            "Totals — sent: %d, received: %d, dates: %d",
            daily_stats["email_sent_count"].sum(),
            daily_stats["email_received_count"].sum(),
            len(daily_stats),
        )

    if args.dry_run:
        log.info("[DRY RUN] Would write to %s", EMAILS_DIR / "daily-stats.parquet")
        print(daily_stats.describe().to_string())
        return


    out_path = EMAILS_DIR / "daily-stats.parquet"
    safe_write_parquet(daily_stats, out_path)
    log.info("Written %d rows to %s", len(daily_stats), out_path)


@pipeline_step(name="l3-email-daily-stats", source="email-daily-stats", stage="l3")
def run():
    main()


if __name__ == "__main__":
    run()
