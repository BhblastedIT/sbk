#!/usr/bin/env python3
"""RQ-05: fills the relationship event store (rq/events.db) from the existing data: emails, calendar, Slack, calls,
WhatsApp and knowledge facts, incremental with watermarks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    EMAILS_DIR,
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    OWN_EMAILS,
    OWNER_SPEAKER_LABELS,
    RQ_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    WHATSAPP_DIR,
)

_CROSS_DIR = Path(__file__).resolve().parent
if str(_CROSS_DIR) not in sys.path:
    sys.path.insert(0, str(_CROSS_DIR))

from rq_entity_bridge import build_entity_bridge, load_bridge, resolve, save_bridge
from rq_event_store import EVENT_DIM_CONTRIBUTIONS, EVENT_WEIGHTS, EventStore
from rq_scoring_blocklist import is_blocked, load_blocklist

log = logging.getLogger("rq.backfill")



BATCH_SIZE = 5000











WATERMARK_PATH = RQ_DIR / ".backfill-watermarks.json"




_SOURCE_DB_NAME = {
    "email": "gmail",
    "calendar": "calendar",
    "slack": "slack",
    "calls": "tactiq",
    "whatsapp": "whatsapp",
    "knowledge": "knowledge",
}


def _gather_source_files(source: str) -> list[Path]:
    ""
    if source == "email":
        if not EMAILS_DIR.exists():
            return []
        return [
            d / "messages.parquet"
            for d in sorted(EMAILS_DIR.iterdir())
            if d.is_dir() and (d / "messages.parquet").exists()
        ]
    if source == "calendar":
        return [ENRICHED_DIR / "interactions-calendar.parquet"]
    if source == "slack":
        return [SLACK_DIR / "channel-texts.parquet"]
    if source == "calls":
        return [TACTIQ_DIR / "meetings.parquet"]
    if source == "whatsapp":
        return [WHATSAPP_DIR / "interactions-whatsapp.parquet"]
    if source == "knowledge":
        kdir = KNOWLEDGE_ENTITIES_DIR / "person"
        return sorted(kdir.glob("*.json")) if kdir.exists() else []
    return []


def _source_fingerprint(source: str) -> str | None:
    ""



    files = [f for f in _gather_source_files(source) if f.exists()]
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        st = f.stat()
        h.update(f"{f.name}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return h.hexdigest()


def _load_watermarks() -> dict[str, str]:
    if not WATERMARK_PATH.exists():
        return {}
    try:
        data = json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_watermarks(wm: dict[str, str]) -> None:
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK_PATH.write_text(json.dumps(wm, indent=2), encoding="utf-8")











_L2_PERSON_IDS: set[str] | None = None


def _load_l2_gate() -> set[str]:
    ""





    global _L2_PERSON_IDS
    if _L2_PERSON_IDS is not None:
        return _L2_PERSON_IDS

    import pandas as pd

    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if not cm_path.exists():
        log.warning("contacts-merged.parquet not found — L2 gate disabled")
        _L2_PERSON_IDS = set()
        return _L2_PERSON_IDS

    cm = pd.read_parquet(cm_path, columns=["person_id"])
    _L2_PERSON_IDS = set(cm["person_id"].dropna().astype(str))


    override_path = RQ_DIR / "entity-overrides.json"
    if override_path.exists():
        try:
            import json

            raw = json.loads(override_path.read_text(encoding="utf-8"))
            override_data = raw.get("overrides", raw) if isinstance(raw, dict) else {}
            override_pids = {
                v for v in override_data.values() if isinstance(v, str) and v.startswith("p_")
            }
            new_pids = override_pids - _L2_PERSON_IDS
            if new_pids:
                _L2_PERSON_IDS |= new_pids
                log.info(
                    "L2 gate: added %d override p_IDs not in contacts-merged: %s",
                    len(new_pids),
                    new_pids,
                )
        except Exception as exc:
            log.warning("Failed to load entity overrides for L2 gate: %s", exc)

    log.info("L2 gate loaded: %d valid person_ids", len(_L2_PERSON_IDS))
    return _L2_PERSON_IDS


def is_valid_person(person_id: str) -> bool:
    ""




    if not person_id:
        return False
    l2 = _load_l2_gate()
    if not l2:
        return True
    return person_id in l2



_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")





def _extract_email(from_addr: str) -> str:
    ""
    if not from_addr:
        return ""
    match = _EMAIL_RE.search(from_addr)
    return match.group(0).lower() if match else from_addr.strip().lower()


def _is_owner_email(email: str) -> bool:
    ""
    return email.strip().lower() in OWN_EMAILS


def _make_event(
    person_id: str,
    timestamp: str,
    event_type: str,
    source: str,
    source_id: str,
    metadata: dict | None = None,
) -> dict | None:
    ""



    if not is_valid_person(person_id):
        return None
    dims = EVENT_DIM_CONTRIBUTIONS.get(event_type, {})
    return {
        "person_id": person_id,
        "timestamp": str(timestamp),
        "event_type": event_type,
        "source": source,
        "signal_weight": EVENT_WEIGHTS.get(event_type, 0.5),
        "dim_intimacy": dims.get("intimacy", 0.0),
        "dim_interaction_quality": dims.get("interaction_quality", 0.0),
        "dim_communication_quality": dims.get("communication_quality", 0.0),
        "dim_structural": dims.get("structural", 0.0),
        "dim_trust": dims.get("trust", 0.0),
        "source_id": source_id,
        "raw_metadata": metadata,
    }


def _write_batch(store: EventStore, events: list[dict | None], dry_run: bool) -> int:
    ""



    clean = [e for e in events if e is not None]
    if dry_run or not clean:
        return len(clean)
    return store.write_events(clean)





def backfill_emails(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""







    import pandas as pd

    total_events = 0
    account_dirs = sorted(EMAILS_DIR.iterdir()) if EMAILS_DIR.is_dir() else []

    for account_dir in account_dirs:
        parquet_path = account_dir / "messages.parquet"
        if not parquet_path.exists():
            continue

        account_name = account_dir.name
        log.info("Processing emails from account: %s", account_name)

        df = pd.read_parquet(
            parquet_path,
            columns=["date", "from_addr", "to_addr", "cc", "bcc", "message_id", "in_reply_to"],
        )

        events: list[dict] = []

        for _, row in df.iterrows():
            from_email = _extract_email(str(row.get("from_addr", "") or ""))
            date = str(row.get("date", ""))
            message_id = str(row.get("message_id", "") or "")
            in_reply_to = str(row.get("in_reply_to", "") or "")
            to_addr = str(row.get("to_addr", "") or "")
            cc = str(row.get("cc", "") or "")
            bcc = str(row.get("bcc", "") or "")

            if not from_email or not date:
                continue


            all_recipients_raw = f"{to_addr},{cc},{bcc}"
            all_recipient_emails = [
                e.lower() for e in _EMAIL_RE.findall(all_recipients_raw) if e.lower() != from_email
            ]


            all_recipient_emails = list(dict.fromkeys(all_recipient_emails))


            non_owner_recipients = [e for e in all_recipient_emails if not _is_owner_email(e)]
            total_recipients = len(non_owner_recipients)

            owner_sent = _is_owner_email(from_email)


            has_reply = bool(in_reply_to and in_reply_to.strip() and in_reply_to != "nan")

            if owner_sent:

                if has_reply:
                    event_type = "email_reply_sent"
                elif total_recipients == 1:
                    event_type = "email_1to1_sent"
                elif total_recipients <= 5:
                    event_type = "email_small_group"
                else:
                    event_type = "email_cc"

                for recip_email in non_owner_recipients:
                    if is_blocked(recip_email, blocklist):
                        continue
                    pid = resolve(bridge, recip_email)
                    if not pid:
                        continue

                    events.append(
                        _make_event(
                            person_id=pid,
                            timestamp=date,
                            event_type=event_type,
                            source="gmail",
                            source_id=f"email_{message_id}_{pid}",
                            metadata={"account": account_name, "from": from_email},
                        )
                    )
            else:

                if is_blocked(from_email, blocklist):
                    continue


                if not any(_is_owner_email(e) for e in all_recipient_emails + [from_email]):

                    to_emails = [e.lower() for e in _EMAIL_RE.findall(to_addr)]
                    if not any(_is_owner_email(e) for e in to_emails):
                        continue

                pid = resolve(bridge, from_email)
                if not pid:
                    continue

                if has_reply:
                    event_type = "email_reply_received"
                elif total_recipients == 0:

                    event_type = "email_1to1_received"
                elif total_recipients <= 4:
                    event_type = "email_small_group"
                else:
                    event_type = "email_cc"

                events.append(
                    _make_event(
                        person_id=pid,
                        timestamp=date,
                        event_type=event_type,
                        source="gmail",
                        source_id=f"email_{message_id}_{pid}",
                        metadata={"account": account_name, "from": from_email},
                    )
                )


            if len(events) >= BATCH_SIZE:
                n = _write_batch(store, events, dry_run)
                total_events += n
                events.clear()


        if events:
            n = _write_batch(store, events, dry_run)
            total_events += n

        log.info(
            "  %s: %d events from %d messages",
            account_name,
            total_events,
            len(df),
        )

    log.info("Email backfill complete: %d total events", total_events)
    return total_events





def backfill_calendar(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""








    import pandas as pd

    cal_path = ENRICHED_DIR / "interactions-calendar.parquet"
    if not cal_path.exists():
        log.warning("Calendar data not found at %s", cal_path)
        return 0

    df = pd.read_parquet(cal_path)
    log.info("Processing %d calendar interaction pairs", len(df))











    date_participants: dict[str, set[str]] = {}
    owner_partner_events: list[
        tuple[str, str, int, str, str]
    ] = []

    for _, row in df.iterrows():
        from_email = str(row.get("from_email", "")).lower()
        to_email = str(row.get("to_email", "")).lower()
        event_count = int(row.get("event_count", 1))
        first_date = str(row.get("first_date", ""))
        last_date = str(row.get("last_date", ""))

        owner_side = None
        partner_email = None
        if _is_owner_email(from_email):
            owner_side = from_email
            partner_email = to_email
        elif _is_owner_email(to_email):
            owner_side = to_email
            partner_email = from_email
        else:
            continue

        if not partner_email or is_blocked(partner_email, blocklist):
            continue

        pid = resolve(bridge, partner_email)
        if not pid:
            continue


        if first_date:
            date_participants.setdefault(first_date, set()).add(partner_email)

        owner_partner_events.append((partner_email, pid, event_count, first_date, last_date))


    events: list[dict] = []
    total_events = 0

    for partner_email, pid, event_count, first_date, last_date in owner_partner_events:

        n_participants = len(date_participants.get(first_date, set()))

        if n_participants <= 1:
            event_type = "meeting_1on1"
        elif n_participants <= 5:
            event_type = "meeting_group_small"
        else:
            event_type = "meeting_group_large"



        ts = f"{first_date}T09:00:00Z" if first_date else "2025-01-01T00:00:00Z"
        source_id = f"cal_{partner_email}_{first_date}"

        events.append(
            _make_event(
                person_id=pid,
                timestamp=ts,
                event_type=event_type,
                source="calendar",
                source_id=source_id,
                metadata={
                    "partner_email": partner_email,
                    "event_count": event_count,
                    "n_participants_on_date": n_participants,
                },
            )
        )

        if len(events) >= BATCH_SIZE:
            n = _write_batch(store, events, dry_run)
            total_events += n
            events.clear()

    if events:
        n = _write_batch(store, events, dry_run)
        total_events += n

    log.info("Calendar backfill complete: %d events", total_events)
    return total_events





def backfill_slack(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""





    import pandas as pd

    slack_path = SLACK_DIR / "channel-texts.parquet"
    if not slack_path.exists():
        log.warning("Slack data not found at %s", slack_path)
        return 0

    df = pd.read_parquet(
        slack_path,
        columns=[
            "channel_name",
            "channel_id",
            "channel_type",
            "dm_with",
            "message_count",
            "date_start",
            "date_end",
        ],
    )
    log.info("Processing %d Slack channels", len(df))

    events: list[dict] = []
    total_events = 0

    for _, row in df.iterrows():
        channel_type = str(row.get("channel_type", ""))
        dm_with = str(row.get("dm_with", "") or "").strip()
        channel_id = str(row.get("channel_id", ""))
        channel_name = str(row.get("channel_name", ""))
        message_count = int(row.get("message_count", 0) or 0)
        date_start = str(row.get("date_start", ""))
        date_end = str(row.get("date_end", ""))

        if message_count < 1:
            continue


        if channel_type == "dm" and dm_with and dm_with != "nan":

            if is_blocked(dm_with, blocklist):
                continue

            pid = resolve(bridge, dm_with)
            if not pid:
                continue

            event_type = "slack_dm"
            ts = str(date_start) if date_start and date_start != "nan" else "2025-01-01T00:00:00Z"
            source_id = f"slack_dm_{channel_id}"

            events.append(
                _make_event(
                    person_id=pid,
                    timestamp=ts,
                    event_type=event_type,
                    source="slack",
                    source_id=source_id,
                    metadata={
                        "channel_name": channel_name,
                        "message_count": message_count,
                        "date_start": date_start,
                        "date_end": date_end,
                    },
                )
            )

        elif channel_type == "group_dm" and dm_with and dm_with != "nan":

            if is_blocked(dm_with, blocklist):
                continue

            pid = resolve(bridge, dm_with)
            if not pid:
                continue

            event_type = "slack_channel_msg"
            ts = str(date_start) if date_start and date_start != "nan" else "2025-01-01T00:00:00Z"
            source_id = f"slack_group_{channel_id}"

            events.append(
                _make_event(
                    person_id=pid,
                    timestamp=ts,
                    event_type=event_type,
                    source="slack",
                    source_id=source_id,
                    metadata={
                        "channel_name": channel_name,
                        "channel_type": channel_type,
                        "message_count": message_count,
                    },
                )
            )




        if len(events) >= BATCH_SIZE:
            n = _write_batch(store, events, dry_run)
            total_events += n
            events.clear()

    if events:
        n = _write_batch(store, events, dry_run)
        total_events += n

    log.info("Slack backfill complete: %d events", total_events)
    return total_events





def backfill_calls(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""




    import pandas as pd

    tactiq_path = TACTIQ_DIR / "meetings.parquet"
    if not tactiq_path.exists():
        log.warning("Tactiq data not found at %s", tactiq_path)
        return 0

    df = pd.read_parquet(
        tactiq_path,
        columns=[
            "meeting_id",
            "title",
            "created_date",
            "participant_count",
            "participants",
        ],
    )
    log.info("Processing %d Tactiq meetings", len(df))

    events: list[dict] = []
    total_events = 0

    owner_names = set(OWNER_SPEAKER_LABELS) | {"_owner_"}

    for _, row in df.iterrows():
        meeting_id = str(row.get("meeting_id", ""))
        title = str(row.get("title", ""))
        created_date = str(row.get("created_date", ""))
        participant_count = int(row.get("participant_count", 0) or 0)
        participants_raw = str(row.get("participants", "") or "")

        if not created_date or created_date == "nan":
            continue

        ts = f"{created_date}T00:00:00Z" if "T" not in created_date else created_date


        participants = [p.strip() for p in participants_raw.split(",") if p.strip()]
        non_owner_participants = [p for p in participants if p.strip().lower() not in owner_names]

        if not non_owner_participants:
            continue


        n_others = len(non_owner_participants)
        if n_others == 1:
            event_type = "call_1on1"
        else:
            event_type = "call_group"

        for participant_name in non_owner_participants:
            if is_blocked(participant_name, blocklist):
                continue

            pid = resolve(bridge, participant_name)
            if not pid:
                continue

            source_id = f"tactiq_{meeting_id}_{pid}"
            events.append(
                _make_event(
                    person_id=pid,
                    timestamp=ts,
                    event_type=event_type,
                    source="tactiq",
                    source_id=source_id,
                    metadata={
                        "meeting_id": meeting_id,
                        "title": title,
                        "participant_count": participant_count,
                    },
                )
            )

        if len(events) >= BATCH_SIZE:
            n = _write_batch(store, events, dry_run)
            total_events += n
            events.clear()

    if events:
        n = _write_batch(store, events, dry_run)
        total_events += n

    log.info("Calls backfill complete: %d events", total_events)
    return total_events





def backfill_whatsapp(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""




    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    wa_path = WHATSAPP_DIR / "interactions-whatsapp.parquet"
    if not wa_path.exists():
        log.warning("WhatsApp data not found at %s", wa_path)
        return 0

    owner_names = set(OWNER_SPEAKER_LABELS)







    tbl = pq.read_table(wa_path, columns=["from_name", "to_name", "timestamp", "is_group"])
    total_rows = tbl.num_rows
    owner_set = pa.array(sorted(owner_names), type=pa.string())
    from_l = pc.utf8_lower(pc.utf8_trim_whitespace(tbl["from_name"].cast(pa.string())))
    to_l = pc.utf8_lower(pc.utf8_trim_whitespace(tbl["to_name"].cast(pa.string())))
    mask = pc.or_(pc.is_in(from_l, value_set=owner_set), pc.is_in(to_l, value_set=owner_set))
    df = tbl.filter(mask).to_pandas()
    del tbl, from_l, to_l, mask
    log.info(
        "Processing %d WhatsApp interactions involving you (pre-filtered from %d)",
        len(df),
        total_rows,
    )

    events: list[dict] = []
    total_events = 0





    resolve_cache: dict[str, str | None] = {}

    def _resolve_counterpart(name: str) -> str | None:
        if name not in resolve_cache:
            resolve_cache[name] = None if is_blocked(name, blocklist) else resolve(bridge, name)
        return resolve_cache[name]

    for from_name, to_name, ts, is_grp in zip(
        df["from_name"].astype(str),
        df["to_name"].astype(str),
        df["timestamp"].astype(str),
        df["is_group"],
        strict=False,
    ):
        from_name = from_name.strip()
        to_name = to_name.strip()
        timestamp = ts

        if not timestamp or timestamp == "nan":
            continue


        if from_name.lower() in owner_names:
            counterpart = to_name
        elif to_name.lower() in owner_names:
            counterpart = from_name
        else:
            continue

        if not counterpart:
            continue

        pid = _resolve_counterpart(counterpart)
        if not pid:
            continue

        is_group = bool(is_grp)
        event_type = "whatsapp_small_group" if is_group else "whatsapp_dm"


        source_id = f"wa_{timestamp}_{pid}"

        events.append(
            _make_event(
                person_id=pid,
                timestamp=timestamp,
                event_type=event_type,
                source="whatsapp",
                source_id=source_id,
                metadata={"from": from_name, "to": to_name, "is_group": is_group},
            )
        )

        if len(events) >= BATCH_SIZE:
            n = _write_batch(store, events, dry_run)
            total_events += n
            events.clear()

    if events:
        n = _write_batch(store, events, dry_run)
        total_events += n

    log.info("WhatsApp backfill complete: %d events", total_events)
    return total_events





def backfill_knowledge_facts(
    store: EventStore,
    bridge: dict[str, str],
    blocklist: dict,
    dry_run: bool = False,
) -> int:
    ""





    knowledge_dir = KNOWLEDGE_ENTITIES_DIR / "person"
    if not knowledge_dir.exists():
        log.warning("Knowledge entities not found at %s", knowledge_dir)
        return 0

    entity_files = sorted(knowledge_dir.glob("*.json"))
    log.info("Scanning %d knowledge entity files for facts", len(entity_files))

    events: list[dict] = []
    total_events = 0

    for ef in entity_files:
        try:
            data = json.loads(ef.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        entity_id = data.get("entity_id", "")
        canonical_name = data.get("canonical_name", "")
        if not entity_id:
            continue

        if canonical_name and is_blocked(canonical_name, blocklist):
            continue


        pid = resolve(bridge, entity_id)
        if not pid:
            pid = resolve(bridge, canonical_name) if canonical_name else None
        if not pid:
            continue

        for fact in data.get("facts", []):
            attr = str(fact.get("attribute", "")).lower()
            fact_id = fact.get("fact_id", "")
            valid_from = fact.get("valid_from", "")
            confidence = fact.get("confidence", 0.5)


            if isinstance(confidence, int | float) and confidence < 0.3:
                continue

            ts = valid_from if valid_from and valid_from != "null" else None
            if not ts:
                continue


            if "T" not in ts:
                ts = f"{ts}T00:00:00Z"

            event_type = None

            if "introduction" in attr:

                value = str(fact.get("value", "")).lower()
                if "introduced" in value or "intro" in value:

                    event_type = "introduction_made"
                else:
                    event_type = "introduction_received"

            elif "commitment" in attr:
                value = str(fact.get("value", "")).lower()
                if any(
                    kw in value
                    for kw in ("fulfilled", "completed", "delivered", "done", "finished")
                ):
                    event_type = "commitment_fulfilled"
                else:
                    event_type = "commitment_made"

            if not event_type:
                continue

            source_id = f"knowledge_{fact_id}" if fact_id else f"knowledge_{entity_id}_{attr}"

            events.append(
                _make_event(
                    person_id=pid,
                    timestamp=ts,
                    event_type=event_type,
                    source="knowledge",
                    source_id=source_id,
                    metadata={
                        "entity_id": entity_id,
                        "attribute": attr,
                        "confidence": confidence,
                    },
                )
            )

        if len(events) >= BATCH_SIZE:
            n = _write_batch(store, events, dry_run)
            total_events += n
            events.clear()

    if events:
        n = _write_batch(store, events, dry_run)
        total_events += n

    log.info("Knowledge facts backfill complete: %d events", total_events)
    return total_events





def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill RQV4 event store from existing SBK data files.",
    )
    parser.add_argument(
        "--source",
        choices=["all", "email", "calendar", "slack", "calls", "whatsapp", "knowledge"],
        default="all",
        help="Which data source(s) to backfill (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count events without writing to DB",
    )
    parser.add_argument(
        "--rebuild-bridge",
        action="store_true",
        help="Rebuild entity bridge before backfill (slower but more complete)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Skip sources whose input files are unchanged since the last successful "
            "backfill (fingerprint watermark). Changed sources are re-run in full; "
            "INSERT OR IGNORE dedups, so the DB is never wiped. Big speedup on reruns."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()


    from sbk_config import acquire_pid_lock

    if not acquire_pid_lock("rq-backfill-events", logger=log):
        log.warning("rq-backfill-events: lock held by another instance, exit 75")
        sys.exit(75)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-20s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.monotonic()


    store = EventStore()
    store.create_db()


    if args.rebuild_bridge:
        log.info("Rebuilding entity bridge...")
        bridge = build_entity_bridge()
        save_bridge(bridge)
    else:
        bridge = load_bridge()
        if len(bridge) < 10:
            log.info("Bridge too small or missing, rebuilding...")
            bridge = build_entity_bridge()
            save_bridge(bridge)

    log.info("Entity bridge loaded: %d entries", len(bridge))


    blocklist = load_blocklist()


    source = args.source
    sources_to_run = (
        ["email", "calendar", "slack", "calls", "whatsapp", "knowledge"]
        if source == "all"
        else [source]
    )
    backfill_fns = {
        "email": backfill_emails,
        "calendar": backfill_calendar,
        "slack": backfill_slack,
        "calls": backfill_calls,
        "whatsapp": backfill_whatsapp,
        "knowledge": backfill_knowledge_facts,
    }

    results: dict[str, int] = {}
    skipped: list[str] = []

    watermarks = _load_watermarks() if args.incremental else {}


    db_sources: set[str] = set()
    if args.incremental and not args.dry_run:
        try:
            db_sources = set(store.stats().get("sources", {}))
        except Exception:
            db_sources = set()

    for src in sources_to_run:
        fp = _source_fingerprint(src) if args.incremental else None
        if (
            args.incremental
            and not args.dry_run
            and fp is not None
            and watermarks.get(src) == fp
            and _SOURCE_DB_NAME.get(src) in db_sources
        ):
            log.info("[incremental] %s unchanged since last backfill — skipped", src)
            skipped.append(src)
            continue

        results[src] = backfill_fns[src](store, bridge, blocklist, args.dry_run)




        if args.incremental and not args.dry_run and fp is not None:
            watermarks[src] = fp
            _save_watermarks(watermarks)

    elapsed = time.monotonic() - t0


    print(f"\n{'=' * 60}")
    print(f"  RQ Backfill {'(DRY RUN) ' if args.dry_run else ''}Complete")
    print(f"  Time: {elapsed:.1f}s")
    print(f"{'=' * 60}")
    print()

    total = 0
    for src, count in results.items():
        print(f"  {src:20s} {count:>8,} events")
        total += count
    for src in skipped:
        print(f"  {src:20s} {'(unchanged, skipped)':>18}")
    print(f"  {'─' * 30}")
    print(f"  {'TOTAL':20s} {total:>8,} events")

    if not args.dry_run:
        print()
        stats = store.stats()
        print(f"  DB total events:    {stats['total_events']:,}")
        print(f"  DB unique persons:  {stats['unique_persons']:,}")
        print(f"  DB size:            {stats['db_size_mb']:.2f} MB")
        print(f"  Oldest event:       {stats.get('oldest_event', 'n/a')}")
        print(f"  Newest event:       {stats.get('newest_event', 'n/a')}")

        if stats.get("sources"):
            print("\n  Events by source:")
            for src, cnt in stats["sources"].items():
                print(f"    {src:20s} {cnt:>8,}")

        if stats.get("event_types"):
            print("\n  Events by type:")
            for et, cnt in stats["event_types"].items():
                print(f"    {et:30s} {cnt:>8,}")

    print()


if __name__ == "__main__":
    main()
