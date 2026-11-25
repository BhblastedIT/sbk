#!/usr/bin/env python3
"""Gmail L1 enrichment: contacts, interactions, threads, attachment indexes and sender table built from the L0 messages."""



















import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    EMAILS_DIR,
    ENRICHED_DIR,
    acquire_pid_lock,
    mark_last_run,
    safe_write_parquet,
)

DATA_DIR = EMAILS_DIR

log = logging.getLogger("gmail-enrich")





def parse_email_addr(raw: str) -> str:
    ""
    if not raw or not isinstance(raw, str):
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return (m.group(1) if m else raw).strip().lower()


def parse_email_name(raw: str) -> str:
    ""
    if not raw or not isinstance(raw, str):
        return ""
    if "<" in raw:
        name = raw[: raw.index("<")].strip().strip('"').strip("'")
        return name if name else ""
    return ""


def parse_email_list(raw: str) -> list:
    ""
    if not raw or not isinstance(raw, str):
        return []
    parts = re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", raw)
    return [parse_email_addr(p) for p in parts if parse_email_addr(p)]


def parse_email_list_with_names(raw: str) -> list:
    ""
    if not raw or not isinstance(raw, str):
        return []
    parts = re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", raw)
    results = []
    for p in parts:
        email = parse_email_addr(p)
        if email:
            name = normalize_name(parse_email_name(p), email)
            results.append((email, name))
    return results


def normalize_name(name: str, email: str) -> str:
    ""
    if not name:
        return ""

    name = name.strip().strip('"').strip("'").strip()

    name = re.sub(r"\s+", " ", name)

    local_part = email.split("@")[0] if "@" in email else ""
    if name.lower() == local_part.lower():

        return re.sub(r"[._]+", " ", local_part).strip().title()
    return name


def load_all_messages(account: str = None) -> pd.DataFrame:
    ""
    frames = []

    if account:
        accounts = [account]
    else:
        accounts = [
            d.name for d in DATA_DIR.iterdir() if d.is_dir() and (d / "messages.parquet").exists()
        ]

    for acc in accounts:
        pq = DATA_DIR / acc / "messages.parquet"
        if not pq.exists():
            log.warning(f"No messages.parquet for account '{acc}', skipping")
            continue
        df = pd.read_parquet(pq)
        df["account"] = acc
        frames.append(df)
        log.info(f"Loaded {len(df)} messages from '{acc}'")

    if not frames:
        log.error("No messages found")
        sys.exit(1)

    return pd.concat(frames, ignore_index=True)





def build_contacts(msgs: pd.DataFrame) -> pd.DataFrame:
    ""



    log.info("Building contacts...")
    t0 = time.time()


    records = []

    for _, row in msgs.iterrows():
        dt = row["date"]


        from_email = parse_email_addr(row.get("from_addr", ""))
        from_name = normalize_name(parse_email_name(row.get("from_addr", "")), from_email)
        if from_email:
            records.append(
                {
                    "email": from_email,
                    "name": from_name,
                    "date": dt,
                    "direction": "from",
                }
            )


        for email, name in parse_email_list_with_names(row.get("to_addr", "")):
            records.append({"email": email, "name": name, "date": dt, "direction": "to"})


        for email, name in parse_email_list_with_names(row.get("cc", "")):
            records.append({"email": email, "name": name, "date": dt, "direction": "cc"})


        for email, name in parse_email_list_with_names(row.get("bcc", "")):
            records.append({"email": email, "name": name, "date": dt, "direction": "bcc"})

    if not records:
        log.warning("No contacts found")
        return pd.DataFrame()

    rdf = pd.DataFrame(records)


    contacts = (
        rdf.groupby("email")
        .agg(
            name=("name", lambda x: next((n for n in x if n), "")),
            first_seen=("date", "min"),
            last_seen=("date", "max"),
            msg_count_from=("direction", lambda x: (x == "from").sum()),
            msg_count_to=("direction", lambda x: (x == "to").sum()),
            msg_count_cc=("direction", lambda x: (x == "cc").sum()),
            msg_count_bcc=("direction", lambda x: (x == "bcc").sum()),
            total_mentions=("direction", "count"),
        )
        .reset_index()
    )


    contacts["domain"] = contacts["email"].str.split("@").str[1]


    contacts.sort_values("total_mentions", ascending=False, inplace=True)

    elapsed = time.time() - t0
    log.info(f"Contacts: {len(contacts)} unique emails in {elapsed:.1f}s")
    return contacts





def build_interactions(msgs: pd.DataFrame) -> pd.DataFrame:
    ""






    log.info("Building interactions...")
    t0 = time.time()

    edges = []
    co_recipient_edges = []

    for _, row in msgs.iterrows():
        from_email = parse_email_addr(row.get("from_addr", ""))
        if not from_email:
            continue

        dt = row["date"]
        subject = row.get("subject", "")
        thread_id = row.get("thread_id", "")


        all_recipients = set()


        for to_email in parse_email_list(row.get("to_addr", "")):
            if to_email != from_email:
                edges.append(
                    {
                        "from_email": from_email,
                        "to_email": to_email,
                        "date": dt,
                        "subject": subject,
                        "thread_id": thread_id,
                        "relation_type": "direct",
                    }
                )
                all_recipients.add(to_email)


        for cc_email in parse_email_list(row.get("cc", "")):
            if cc_email != from_email:
                edges.append(
                    {
                        "from_email": from_email,
                        "to_email": cc_email,
                        "date": dt,
                        "subject": subject,
                        "thread_id": thread_id,
                        "relation_type": "direct",
                    }
                )
                all_recipients.add(cc_email)


        if len(all_recipients) >= 2:
            for a, b in combinations(sorted(all_recipients), 2):
                co_recipient_edges.append(
                    {
                        "from_email": a,
                        "to_email": b,
                        "date": dt,
                        "subject": subject,
                        "thread_id": thread_id,
                        "relation_type": "co_recipient",
                    }
                )

    if not edges and not co_recipient_edges:
        log.warning("No interactions found")
        return pd.DataFrame()

    all_edges = edges + co_recipient_edges
    edf = pd.DataFrame(all_edges)

    log.info(
        f"Raw edges: {len(edges)} direct + {len(co_recipient_edges)} co-recipient"
        f" = {len(all_edges)} total"
    )

    interactions = (
        edf.groupby(["from_email", "to_email", "relation_type"])
        .agg(
            msg_count=("date", "count"),
            thread_count=("thread_id", "nunique"),
            first_date=("date", "min"),
            last_date=("date", "max"),
            subjects_sample=("subject", lambda x: " ||| ".join(x.dropna().unique()[:5])),
        )
        .reset_index()
    )


    interactions.sort_values("msg_count", ascending=False, inplace=True)

    direct_count = len(interactions[interactions["relation_type"] == "direct"])
    co_count = len(interactions[interactions["relation_type"] == "co_recipient"])
    elapsed = time.time() - t0
    log.info(
        f"Interactions: {len(interactions)} edges ({direct_count} direct + {co_count} co-recipient)"
        f" in {elapsed:.1f}s"
    )
    return interactions





def build_threads(msgs: pd.DataFrame) -> pd.DataFrame:
    ""


    log.info("Building threads...")
    t0 = time.time()

    def _participants(group):
        all_emails = set()
        for _, row in group.iterrows():
            f = parse_email_addr(row.get("from_addr", ""))
            if f:
                all_emails.add(f)
            for e in parse_email_list(row.get("to_addr", "")):
                all_emails.add(e)
        return ",".join(sorted(all_emails))

    def _first_subject(group):
        sorted_g = group.sort_values("date")
        return sorted_g.iloc[0].get("subject", "")

    threads = (
        msgs.groupby("thread_id")
        .agg(
            subject=("subject", lambda x: x.dropna().iloc[0] if len(x.dropna()) > 0 else ""),
            msg_count=("id", "count"),
            date_start=("date", "min"),
            date_end=("date", "max"),
            account=("account", "first"),
            participants=(
                "from_addr",
                lambda x: ",".join(sorted(set(parse_email_addr(e) for e in x if e))),
            ),
            labels=(
                "labels",
                lambda x: ",".join(
                    sorted(set(l for labels_str in x.dropna() for l in labels_str.split(",") if l))
                ),
            ),
        )
        .reset_index()
    )


    threads["duration_h"] = (
        (threads["date_end"] - threads["date_start"]).dt.total_seconds() / 3600
    ).round(1)

    threads.sort_values("date_end", ascending=False, inplace=True)

    elapsed = time.time() - t0
    log.info(f"Threads: {len(threads)} threads in {elapsed:.1f}s")
    return threads






_ATTACHMENT_INDEX_CACHE: dict[int, pd.DataFrame] = {}


def build_message_attachments(msgs: pd.DataFrame) -> pd.DataFrame:
    ""

    if id(msgs) not in _ATTACHMENT_INDEX_CACHE:
        _ATTACHMENT_INDEX_CACHE.clear()
        _ATTACHMENT_INDEX_CACHE[id(msgs)] = _attachment_index(msgs)
    return _ATTACHMENT_INDEX_CACHE[id(msgs)]


def build_attachment_summary(msgs: pd.DataFrame) -> pd.DataFrame:
    ""



    log.info("Building attachment summary...")
    t0 = time.time()
    att_df = build_message_attachments(msgs)
    if len(att_df) == 0:
        return pd.DataFrame()


    def _summarize(group):
        ext_counts = Counter(group["ext"])
        return pd.Series(
            {
                "total_attachments": len(group),
                "total_size_bytes": group["size"].sum(),
                "unique_filenames": group["filename"].nunique(),
                "by_type": json.dumps(dict(ext_counts.most_common(10)), ensure_ascii=False),
                "first_attachment": group["date"].min(),
                "last_attachment": group["date"].max(),
            }
        )

    summary = att_df.groupby("email").apply(_summarize, include_groups=False).reset_index()
    summary.sort_values("total_attachments", ascending=False, inplace=True)

    elapsed = time.time() - t0
    log.info(
        f"Attachment summary: {len(summary)} senders, {len(att_df)} total attachments in {elapsed:.1f}s"
    )
    return summary


def _attachment_index(msgs: pd.DataFrame) -> pd.DataFrame:
    ""
    if "attachments_json" not in msgs.columns or "has_attachments" not in msgs.columns:
        log.warning("No attachment columns in L0 data — run em-l0-download.py first")
        return pd.DataFrame()

    att_msgs = msgs[msgs["has_attachments"] == True].copy()  # noqa: E712
    if len(att_msgs) == 0:
        log.info("No messages with attachments found")
        return pd.DataFrame()

    records = []
    for _, row in att_msgs.iterrows():
        raw = row.get("attachments_json", "")
        if not raw:
            continue
        try:
            atts = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        sender = parse_email_addr(row.get("from_addr", ""))
        if not sender:
            continue

        for att in atts:
            ext = (
                att.get("filename", "").rsplit(".", 1)[-1].lower()
                if "." in att.get("filename", "")
                else ""
            )
            records.append(
                {
                    "email": sender,
                    "msg_id": row.get("id", ""),
                    "date": row.get("date"),
                    "filename": att.get("filename", ""),
                    "mime_type": att.get("mime_type", ""),
                    "size": att.get("size", 0),
                    "ext": ext,
                    "attachment_id": att.get("attachment_id", ""),
                }
            )

    if not records:
        log.info("No attachment records extracted")
        return pd.DataFrame()
    return pd.DataFrame(records)





def build_senders(msgs: pd.DataFrame) -> pd.DataFrame:
    ""





    import rumore

    from sbk_config import INTERNAL_DOMAINS, OWN_EMAILS

    t0 = time.time()
    tab = rumore.tabella_mittenti(
        msgs,
        OWN_EMAILS,
        INTERNAL_DOMAINS,
        altrove=rumore.altrove_da_merge(),
        corrette=rumore.correzioni().get("posta"),
    )
    if not tab.empty:
        per_tipo = (
            tab.groupby("tipo")["n"].agg(["count", "sum"]).sort_values("sum", ascending=False)
        )
        log.info(
            "Senders: %d in %.1fs, %s",
            len(tab),
            time.time() - t0,
            ", ".join(
                f"{t} {int(r['count'])} ({int(r['sum'])} mail)" for t, r in per_tipo.iterrows()
            ),
        )
    return tab


STEPS = {
    "contacts": build_contacts,
    "interactions": build_interactions,
    "threads": build_threads,
    "message_attachments": build_message_attachments,
    "attachment_summary": build_attachment_summary,
    "mittenti-posta": build_senders,
}






READ_IDS_FILE = "email-l1-ids.parquet"


def _read_ids() -> set[str]:
    try:
        return set(pd.read_parquet(ENRICHED_DIR / READ_IDS_FILE, columns=["id"])["id"].astype(str))
    except (OSError, ValueError, KeyError):
        return set()


def _save_read_ids(msgs: pd.DataFrame) -> None:
    ids = pd.DataFrame({"id": msgs["id"].astype(str).drop_duplicates()})
    safe_write_parquet(ids, ENRICHED_DIR / READ_IDS_FILE, index=False)


def _load_watermark() -> dict[str, str]:
    ""
    wm_path = ENRICHED_DIR / "email-l1-watermark.json"
    if wm_path.exists():
        try:
            return json.loads(wm_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_watermark(watermark: dict[str, str]) -> None:
    ""
    wm_path = ENRICHED_DIR / "email-l1-watermark.json"
    wm_path.write_text(json.dumps(watermark, indent=2, default=str))


def _save_messages_with_body(args, all_msgs: pd.DataFrame):
    ""
    t0 = time.time()
    out_dir = ENRICHED_DIR / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "messages-with-body.parquet"

    cols = ["id", "thread_id", "date", "from_addr", "to_addr", "subject", "body_text", "account"]
    cols = [c for c in cols if c in all_msgs.columns]
    df = all_msgs[cols].copy()

    if "body_text" not in df.columns:
        log.warning("body_text column missing from L0 — skipping body persistence")
        return


    def _clean_body(text):
        if not text or not isinstance(text, str):
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:10000]

    df["body_text"] = df["body_text"].apply(_clean_body)


    if args.incremental and out_path.exists():
        existing = pd.read_parquet(out_path)
        df = pd.concat([existing, df], ignore_index=True)
        df.drop_duplicates(subset=["id"], keep="last", inplace=True)

    safe_write_parquet(df, out_path, index=False)
    non_empty = (df["body_text"].str.len() > 0).sum()
    elapsed = time.time() - t0
    log.info(
        f"Body persistence: {len(df)} messages ({non_empty} with body) "
        f"-> {out_path} [{elapsed:.1f}s]"
    )


def main():
    parser = argparse.ArgumentParser(description="Gmail enrichment pipeline — SBK")
    parser.add_argument("--account", default=None, help="Account to process (default: all)")
    parser.add_argument(
        "--step",
        default=None,
        choices=list(STEPS.keys()),
        help="Run single step (default: all)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip if there are no new mails by id, otherwise redo everything on all mails",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would run without writing"
    )
    args = parser.parse_args()

    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )






    _lock_name = f"em-l1-enrich{'-' + args.account if args.account else ''}"
    if not acquire_pid_lock(_lock_name, logger=log):
        sys.exit(75)


    msgs = load_all_messages(args.account)
    log.info(f"Total messages loaded: {len(msgs)}")




    if args.incremental:
        read_ids = _read_ids()
        new_count = (
            int((~msgs["id"].astype(str).isin(read_ids)).sum()) if "id" in msgs.columns else len(msgs)
        )
        log.info(f"Incremental: {new_count} new messages by id (of {len(msgs)} total)")

        if new_count == 0:
            log.info("No new messages — skipping enrichment")

            try:
                from event_bus import EventBus

                EventBus.emit("email", "l1", account=args.account or "all", output_changed=False)
            except Exception as e:
                log.warning(f"EventBus emit failed: {e}")
            return


    if not args.dry_run:
        _save_messages_with_body(args, msgs)

    steps = [args.step] if args.step else list(STEPS.keys())

    for step_name in steps:
        result = STEPS[step_name](msgs)

        if result is not None and len(result) > 0:
            out_path = ENRICHED_DIR / f"{step_name}.parquet"
            if not args.dry_run:
                safe_write_parquet(result, out_path, index=False)
            log.info(
                f"{'[DRY RUN] Would save' if args.dry_run else 'Saved'} {step_name}: {len(result)} rows -> {out_path}"
            )

    log.info("Enrichment complete.")

    if args.dry_run:
        log.info("[DRY RUN] No files written.")
        return


    _save_read_ids(msgs)
    watermark = _load_watermark()
    if "date" in msgs.columns:
        date = pd.to_datetime(msgs["date"], utc=True, errors="coerce")
        accounts = msgs["account"] if "account" in msgs.columns else pd.Series(["all"] * len(msgs))
        for acc, max_date in date.groupby(accounts.values).max().items():
            if pd.notna(max_date):
                watermark[acc] = max_date.isoformat()
    _save_watermark(watermark)


    try:
        from event_bus import EventBus
        from l1_checkpoint import L1Checkpoint

        ckpt = L1Checkpoint("email")
        has_changed = ckpt.has_output_changed()
        ckpt.save()
        EventBus.emit("email", "l1", account=args.account or "all", output_changed=has_changed)
    except Exception as e:
        log.warning(f"EventBus/checkpoint failed: {e}")

    mark_last_run("email-l1")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-email-enrich", source="email-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
