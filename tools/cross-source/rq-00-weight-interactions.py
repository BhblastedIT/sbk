#!/usr/bin/env python3
"""RQ-00: collects every interaction with every person (email, calendar, Slack, Plaud and Tactiq meetings, voice
memos, Attio calls, WhatsApp), classifies it and gives it a weight, into rq/interaction-weights.parquet, the input
of the relationship scores.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd
import pyarrow as pa
import pyarrow.parquet  # noqa: F401  (usato come pa.parquet.ParquetFile)

from sbk_config import (
    ATTIO_PROCESSED_DIR,
    CALENDARS_DIR,
    EMAILS_DIR,
    ENRICHED_DIR,
    OWN_EMAILS,
    RQ_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    WHATSAPP_DIR,
    safe_write_parquet,
)

# You as the sender of calendar and voice-memo interactions: your first own_emails
# address ("owner" when sbk.config.json has none).
_OWNER_ADDR = sorted(OWN_EMAILS)[0] if OWN_EMAILS else "owner"

log = logging.getLogger("rq-00")





_WA_BYTES_PER_ROW = 250


def _wa_batch_rows() -> int:
    try:
        from sbk_resources import budget

        return budget().batch_rows(bytes_per_row=_WA_BYTES_PER_ROW, safety=0.05)
    except Exception:  # noqa: BLE001 — modulo assente: fallback prudente
        return 500_000




def _load_sqi_noise_scores() -> dict[str, float]:
    ""
    sqi_path = ENRICHED_DIR / "signal-quality-index.json"
    if not sqi_path.exists():
        return {}
    try:
        data = json.loads(sqi_path.read_text(encoding="utf-8"))
        return data.get("email", {}).get("noise_scores", {})
    except (ValueError, OSError):
        return {}


def _load_channel_members() -> dict[str, int]:
    ""
    ch_path = SLACK_DIR / "channels-activity.parquet"
    if not ch_path.exists():
        return {}
    df = pd.read_parquet(ch_path, columns=["channel_id", "unique_users"])
    return dict(zip(df["channel_id"], df["unique_users"].fillna(0).astype(int)))




_CAMPI = (
    "source",
    "account",
    "interaction_id",
    "date",
    "from_addr",
    "to_addr",
    "interaction_type",
    "weight",
)

_BLOCCO_POSTA = 5_000


def _per_colonne() -> dict[str, list]:
    return {c: [] for c in _CAMPI}


def _aggiungi(colonne: dict[str, list], *valori) -> None:
    for c, v in zip(_CAMPI, valori, strict=True):
        colonne[c].append(v)


def _tabella(colonne: dict[str, list]) -> pd.DataFrame:
    ""
    return pd.DataFrame(colonne) if colonne["source"] else pd.DataFrame()


def _a_blocchi(percorso: Path, colonne: list[str], righe: int):
    ""
    for batch in pa.parquet.ParquetFile(percorso).iter_batches(batch_size=righe, columns=colonne):
        df = batch.to_pandas()
        yield [df[c].tolist() for c in colonne]


def process_emails() -> pd.DataFrame:
    ""
    import rumore
    from rq_interaction_weights import classify_email

    sqi_scores = _load_sqi_noise_scores()

    tipi = rumore.tipi_mittenti()
    if not tipi:
        log.warning(
            "Sender table missing: mail noise weighs as before (rerun the mail read)"
        )
    colonne = _per_colonne()

    account_dirs = sorted(EMAILS_DIR.glob("*/messages.parquet"))
    if not account_dirs:
        log.warning("No email data found in %s", EMAILS_DIR)
        return pd.DataFrame()

    lette = [
        "id",
        "date",
        "from_addr",
        "to_addr",
        "cc",
        "bcc",
        "in_reply_to",
        "body_text",
        "labels",
    ]
    for msg_file in account_dirs:
        account = msg_file.parent.name
        log.info("Processing emails: %s", account)

        for blocco in _a_blocchi(msg_file, lette, _BLOCCO_POSTA):
            for id_, date, from_addr, to_addr, cc, bcc, in_reply_to, body_text, labels in zip(
                *blocco, strict=True
            ):
                itype, weight = classify_email(
                    from_addr=str(from_addr) if pd.notna(from_addr) else "",
                    to_addr=str(to_addr) if pd.notna(to_addr) else None,
                    cc=str(cc) if pd.notna(cc) else None,
                    bcc=str(bcc) if pd.notna(bcc) else None,
                    in_reply_to=str(in_reply_to) if pd.notna(in_reply_to) else None,
                    body_text=str(body_text) if pd.notna(body_text) else None,
                    own_emails=OWN_EMAILS,
                    sqi_noise_scores=sqi_scores,
                    tipi_mittenti=tipi,
                    labels=str(labels) if pd.notna(labels) else None,
                )
                _aggiungi(
                    colonne,
                    "email",
                    account,
                    str(id_),
                    date,
                    str(from_addr) if pd.notna(from_addr) else "",
                    str(to_addr) if pd.notna(to_addr) else "",
                    itype,
                    weight,
                )

    return _tabella(colonne)


def process_calendar() -> pd.DataFrame:
    ""
    from rq_interaction_weights import classify_calendar_event

    colonne = _per_colonne()
    event_files = sorted(CALENDARS_DIR.glob("*/events.parquet"))
    if not event_files:
        log.warning("No calendar data found in %s", CALENDARS_DIR)
        return pd.DataFrame()

    for ev_file in event_files:
        account = ev_file.parent.name
        log.info("Processing calendar: %s", account)

        df = pd.read_parquet(
            ev_file, columns=["id", "start_datetime", "attendees", "attendee_count"]
        )

        for id_, start_datetime, attendees, attendee_count in zip(
            df["id"].tolist(),
            df["start_datetime"].tolist(),
            df["attendees"].tolist(),
            df["attendee_count"].tolist(),
            strict=True,
        ):
            att_count = int(attendee_count) if pd.notna(attendee_count) else 1
            event_id = str(id_) if pd.notna(id_) else ""

            itype, weight = classify_calendar_event(
                attendee_count=att_count,
                event_id=event_id,
            )


            attendees_str = str(attendees) if pd.notna(attendees) else ""
            attendee_emails = [
                e.strip().lower()
                for e in attendees_str.split(",")
                if e.strip() and e.strip().lower() not in OWN_EMAILS
            ]

            for att_email in attendee_emails:
                _aggiungi(
                    colonne,
                    "calendar",
                    account,
                    event_id,
                    start_datetime,
                    _OWNER_ADDR,
                    att_email,
                    itype,
                    weight,
                )

    return _tabella(colonne)


def process_slack() -> pd.DataFrame:
    ""
    from rq_interaction_weights import classify_slack_message

    slack_file = SLACK_DIR / "interactions-slack.parquet"
    if not slack_file.exists():
        log.warning("No Slack data found: %s", slack_file)
        return pd.DataFrame()

    log.info("Processing Slack interactions")

    channel_members = _load_channel_members()

    lette = ["message_type", "timestamp", "from_user", "to_user"]
    if "channel_id" in pa.parquet.read_schema(slack_file).names:
        lette.append("channel_id")
    df = pd.read_parquet(slack_file, columns=lette)
    colonne = _per_colonne()
    canali = df["channel_id"].tolist() if "channel_id" in df.columns else [None] * len(df)

    for message_type, timestamp, from_user, to_user, channel_id in zip(
        df["message_type"].tolist(),
        df["timestamp"].tolist(),
        df["from_user"].tolist(),
        df["to_user"].tolist(),
        canali,
        strict=True,
    ):
        ch_id = str(channel_id) if pd.notna(channel_id) else ""
        member_count = channel_members.get(ch_id)
        msg_type = str(message_type) if pd.notna(message_type) else ""

        itype, weight = classify_slack_message(
            message_type=msg_type,
            channel_member_count=member_count,
        )

        _aggiungi(
            colonne,
            "slack",
            "slack",
            f"{ch_id}_{timestamp}" if pd.notna(timestamp) else ch_id,
            timestamp if pd.notna(timestamp) else None,
            str(from_user) if pd.notna(from_user) else "",
            str(to_user) if pd.notna(to_user) else "",
            itype,
            weight,
        )

    return _tabella(colonne)


def process_plaud_tactiq() -> pd.DataFrame:
    ""
    from rq_interaction_weights import classify_call

    tactiq_file = TACTIQ_DIR / "interactions-tactiq.parquet"
    rows = []

    if tactiq_file.exists():
        log.info("Processing Tactiq interactions")
        df = pd.read_parquet(tactiq_file)

        for row in df.itertuples():


            meeting_count = int(row.meeting_count) if pd.notna(row.meeting_count) else 1
            itype, base_weight = classify_call(participant_count=2)

            rows.append(
                {
                    "source": "tactiq",
                    "account": "tactiq",
                    "interaction_id": f"tq_{row.speaker_1}_{row.speaker_2}",
                    "date": row.last_meeting_date if pd.notna(row.last_meeting_date) else None,
                    "from_addr": str(row.speaker_1) if pd.notna(row.speaker_1) else "",
                    "to_addr": str(row.speaker_2) if pd.notna(row.speaker_2) else "",
                    "interaction_type": itype,
                    "weight": base_weight,
                    "meeting_count": meeting_count,
                }
            )
    else:
        log.info("No Tactiq data found")

    return pd.DataFrame(rows)


def process_voice_memos() -> pd.DataFrame:
    ""




    from sbk_config import VOICE_MEMOS_PROCESSED_DIR

    vm_file = VOICE_MEMOS_PROCESSED_DIR / "recordings-index.parquet"
    if not vm_file.exists():
        log.warning("No voice memo data found: %s", vm_file)
        return pd.DataFrame()

    log.info("Processing voice memos")
    df = pd.read_parquet(vm_file)
    rows = []

    for row in df.itertuples():

        people = getattr(row, "entities_people", None)
        if not people or (isinstance(people, float) and pd.isna(people)):
            continue

        if isinstance(people, str):
            import json as _json

            try:
                people = _json.loads(people)
            except (ValueError, TypeError):
                people = [p.strip() for p in people.split(",") if p.strip()]

        if not isinstance(people, list) or not people:
            continue

        rec_id = str(getattr(row, "recording_id", ""))
        date = getattr(row, "date", None)

        for person_name in people:
            rows.append(
                {
                    "source": "voice_memo",
                    "account": "voice_memo",
                    "interaction_id": f"vm_{rec_id}_{person_name}",
                    "date": date if pd.notna(date) else None,
                    "from_addr": _OWNER_ADDR,
                    "to_addr": str(person_name).strip(),
                    "interaction_type": "voice_memo_mention",
                    "weight": 0.4,
                }
            )

    return pd.DataFrame(rows)


def process_attio() -> pd.DataFrame:
    ""
    from rq_interaction_weights import classify_attio

    calls_file = ATTIO_PROCESSED_DIR / "interactions-attio-calls.parquet"
    rows = []

    if calls_file.exists():
        log.info("Processing Attio calls")
        df = pd.read_parquet(calls_file)

        for row in df.itertuples():
            itype, weight = classify_attio(interaction_type="meeting")

            rows.append(
                {
                    "source": "attio",
                    "account": "attio",
                    "interaction_id": f"at_{row.from_name}_{row.to_name}",
                    "date": row.call_date if pd.notna(getattr(row, "call_date", None)) else None,
                    "from_addr": str(row.from_name) if pd.notna(row.from_name) else "",
                    "to_addr": str(row.to_name) if pd.notna(row.to_name) else "",
                    "interaction_type": itype,
                    "weight": weight,
                }
            )
    else:
        log.info("No Attio calls data found")

    return pd.DataFrame(rows)


def _clamp_l1_weight(raw) -> float:
    ""




    try:
        w = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(w) or w <= 0.0 or w > 1.0:
        return 1.0
    return w


def _derive_participant_count(l1_weight: float) -> int:
    ""
    return max(2, int(round(1.0 + 1.0 / l1_weight)))


def whatsapp_interaction_weight(
    is_group: bool,
    l1_weight_raw=None,
    participant_count=None,
) -> tuple[str, float]:
    ""





    from rq_interaction_weights import classify_whatsapp

    l1_w = _clamp_l1_weight(l1_weight_raw)

    if not is_group:
        n = 2
    elif participant_count is not None:
        try:
            n = max(2, int(participant_count))
        except (TypeError, ValueError):
            n = _derive_participant_count(l1_w)
    else:
        n = _derive_participant_count(l1_w)

    itype, base_weight = classify_whatsapp(is_group=is_group, participant_count=n)
    return itype, base_weight * l1_w


def _whatsapp_batch_to_frame(batch: pa.RecordBatch) -> pd.DataFrame:
    ""







    import numpy as np
    from rq_interaction_weights import load_interaction_weights

    wa_w = load_interaction_weights().get("whatsapp", {})
    W_DM = float(wa_w.get("wa_dm_1to1", 0.9))
    W_SMALL = float(wa_w.get("wa_small_group", 0.4))
    W_LARGE = float(wa_w.get("wa_large_group", 0.15))

    n_rows = batch.num_rows
    if n_rows == 0:
        return pd.DataFrame()

    def _col(name):
        return batch.column(name) if name in batch.schema.names else None


    c = _col("is_group")
    is_group = (
        np.asarray(c.fill_null(False).to_numpy(zero_copy_only=False), dtype=bool)
        if c is not None
        else np.zeros(n_rows, dtype=bool)
    )


    c = _col("weight")
    raw = (
        np.asarray(c.to_numpy(zero_copy_only=False), dtype="float64")
        if c is not None
        else np.full(n_rows, np.nan)
    )
    l1_w = np.where(np.isfinite(raw) & (raw > 0.0) & (raw <= 1.0), raw, 1.0)


    with np.errstate(divide="ignore", invalid="ignore"):
        derived = np.maximum(2, np.rint(1.0 + 1.0 / l1_w)).astype("int64")
    n_part = np.where(is_group, derived, 2)


    itype = np.where(
        ~is_group,
        "wa_dm_1to1",
        np.where(n_part <= 5, "wa_small_group", "wa_large_group"),
    )
    base = np.where(~is_group, W_DM, np.where(n_part <= 5, W_SMALL, W_LARGE))
    weight = base * l1_w


    def _str_col(name):
        col = _col(name)
        if col is None:
            return pd.array([""] * n_rows, dtype="string[pyarrow]")
        return pd.array(col.cast(pa.large_string()), dtype="string[pyarrow]")

    from_addr = pd.Series(_str_col("from_name")).fillna("")
    to_addr = pd.Series(_str_col("to_name")).fillna("")
    ts = pd.Series(_str_col("timestamp"))


    base_id = "wa_" + from_addr.astype(str) + "_" + to_addr.astype(str)
    with_ts = base_id + "_" + ts.fillna("").astype(str)
    interaction_id = with_ts.where(ts.notna(), base_id)

    return pd.DataFrame(
        {
            "source": pd.Categorical(["whatsapp"] * n_rows),
            "account": pd.Categorical(["whatsapp"] * n_rows),
            "interaction_id": pd.array(interaction_id, dtype="string[pyarrow]"),
            "date": ts,
            "from_addr": from_addr,
            "to_addr": to_addr,
            "interaction_type": pd.Categorical(
                itype, categories=["wa_dm_1to1", "wa_small_group", "wa_large_group"]
            ),
            "weight": weight.astype("float32"),
        }
    )


def process_whatsapp() -> pd.DataFrame:
    ""






    wa_file = WHATSAPP_DIR / "interactions-whatsapp.parquet"
    if not wa_file.exists():
        log.warning("No WhatsApp data found: %s", wa_file)
        return pd.DataFrame()

    pf = pa.parquet.ParquetFile(wa_file)
    total = pf.metadata.num_rows
    log.info("Processing WhatsApp interactions (%s rows, read in batches)", f"{total:,}")

    frames = []
    done = 0
    _WA_BATCH_ROWS = _wa_batch_rows()  # asked when the step runs, not at import
    for batch in pf.iter_batches(batch_size=_WA_BATCH_ROWS):
        frames.append(_whatsapp_batch_to_frame(batch))
        done += batch.num_rows
        if done % (_WA_BATCH_ROWS * 10) == 0:
            log.info(
                "  whatsapp %s/%s rows (%.0f%%)", f"{done:,}", f"{total:,}", 100 * done / total
            )

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    del frames
    return out


_SOURCE_PROCESSORS = {
    "email": process_emails,
    "calendar": process_calendar,
    "slack": process_slack,
    "plaud_tactiq": process_plaud_tactiq,
    "attio": process_attio,
    "whatsapp": process_whatsapp,
    "voice_memos": process_voice_memos,
}


def main():
    parser = argparse.ArgumentParser(description="RQ-00: Classify and weight all interactions")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument(
        "--source",
        choices=[
            "email",
            "calendar",
            "slack",
            "plaud_tactiq",
            "attio",
            "whatsapp",
            "voice_memos",
            "all",
        ],
        default="all",
        help="Process specific source or all (default: all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    sources = list(_SOURCE_PROCESSORS.keys()) if args.source == "all" else [args.source]
    all_frames = []

    for source in sources:
        processor = _SOURCE_PROCESSORS[source]
        df = processor()
        if len(df) > 0:
            log.info("[%s] %d interactions classified", source, len(df))
            all_frames.append(df)
        else:
            log.info("[%s] No interactions found", source)

    if not all_frames and not (RQ_DIR / "interaction-weights.parquet").exists():
        # A first install whose sources carry no interactions these lanes read (yet): nothing to
        # weigh and no earlier weights to protect. The scores come once there are interactions.
        log.info(
            "No interactions yet in any source (%s): nothing to weigh, no weights written",
            ", ".join(sources),
        )
        return
    if not all_frames:
        # Weights from an earlier run exist: an empty result now means an input went missing.
        log.error(
            "No interactions found across any source (%s): nothing to write, exiting with error.",
            ", ".join(sources),
        )
        sys.exit(1)

    result = pd.concat(all_frames, ignore_index=True)


    import re

    def _extract_single_email(raw: str) -> str:
        ""
        raw = raw.strip()
        m = re.search(r"<([^>]+)>", raw)
        if m:
            return m.group(1).lower().strip()
        if "@" in raw:
            return raw.lower().strip()
        return raw

    def _split_recipients(raw):
        ""
        if not isinstance(raw, str) or not raw.strip():
            return [raw]
        raw = raw.strip()
        if "," not in raw:
            return [_extract_single_email(raw)]

        parts = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            extracted = _extract_single_email(part)
            if extracted:
                parts.append(extracted)
        return parts if parts else [raw]


    pre_explode = len(result)







    _to = result["to_addr"]
    _is_str = _to.map(type).eq(str) if _to.dtype == object else _to.notna()
    _s = _to.astype(str)
    _needs_fn = _is_str & (_s.str.contains(",", regex=False) | _s.str.contains("<", regex=False))
    _has_at = _is_str & ~_needs_fn & _s.str.contains("@", regex=False)
    _blank = _is_str & _s.str.strip().eq("")

    _simple = _s.where(~_has_at, _s.str.lower().str.strip())

    _simple = _simple.where(_is_str & ~_blank, _to)

    n_fn = int(_needs_fn.sum())
    log.info(
        "Explode: %s rows out of %s need the split (%.2f%%)",
        f"{n_fn:,}",
        f"{pre_explode:,}",
        100 * n_fn / max(pre_explode, 1),
    )

    if n_fn:
        _out = _simple.astype(object)
        _out.loc[_needs_fn] = _to[_needs_fn].apply(_split_recipients)
        result["to_addr"] = _out
        result = result.explode("to_addr", ignore_index=True)
    else:


        result["to_addr"] = _simple
    del _to, _is_str, _s, _needs_fn, _has_at, _blank, _simple
    result["to_addr"] = result["to_addr"].astype(str)
    log.info("Exploded multi-recipient: %d -> %d rows", pre_explode, len(result))


    pre_dedup = len(result)
    result = result.drop_duplicates(subset=["source", "interaction_id", "to_addr"], keep="first")
    if len(result) < pre_dedup:
        log.info("SQ-09: dropped %d duplicate rows", pre_dedup - len(result))


    own_lower = {e.lower() for e in OWN_EMAILS}
    result = result[~result["to_addr"].str.lower().isin(own_lower)].reset_index(drop=True)


    import json as _json

    _cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if _cm_path.exists():
        _cm = pd.read_parquet(_cm_path, columns=["person_id", "name", "email", "all_emails"])
        _email_map: dict[str, str] = {}
        _name_map: dict[str, str] = {}
        for _, _row in _cm.iterrows():
            _pid = _row["person_id"]
            if pd.notna(_row.get("email")):
                _email_map[str(_row["email"]).lower().strip()] = _pid
            _all = _row.get("all_emails")
            if pd.notna(_all):
                if isinstance(_all, str):
                    try:
                        _all = _json.loads(_all)
                    except (ValueError, TypeError):
                        _all = [_all]
                if isinstance(_all, list):
                    for _e in _all:
                        _email_map[str(_e).lower().strip()] = _pid

            if pd.notna(_row.get("name")):
                _name = str(_row["name"]).strip()
                if _name and _name not in _name_map:
                    _name_map[_name] = _pid



        _fullname_map: dict[str, str] = {}
        _lastname_map: dict[str, str] = {}
        _lastname_counts: dict[str, int] = {}
        for _name_key, _pid_val in _name_map.items():

            _norm = _name_key.strip().lower()
            if _norm and _norm not in _fullname_map:
                _fullname_map[_norm] = _pid_val
            parts = _name_key.strip().split()
            if len(parts) >= 2:
                last = parts[-1].lower()
                _lastname_counts[last] = _lastname_counts.get(last, 0) + 1
                _lastname_map[last] = _pid_val

        _unique_lastnames = {
            k: v for k, v in _lastname_map.items() if _lastname_counts.get(k, 0) == 1
        }

        _unmapped_warnings: dict[str, int] = {}

        def _map_to_person(x):
            x_str = str(x).strip()
            if not x_str:
                return x

            mapped = _email_map.get(x_str.lower())
            if mapped:
                return mapped

            mapped = _name_map.get(x_str)
            if mapped:
                return mapped

            mapped = _fullname_map.get(x_str.lower())
            if mapped:
                return mapped

            parts = x_str.split()
            if len(parts) >= 2:
                last = parts[-1].lower()
                mapped = _unique_lastnames.get(last)
                if mapped:
                    return mapped

            _unmapped_warnings[x_str] = _unmapped_warnings.get(x_str, 0) + 1
            return x





        _counts = result["to_addr"].value_counts(dropna=False)
        log.info(
            "Person mapping: %s distinct values over %s rows",
            f"{len(_counts):,}",
            f"{len(result):,}",
        )
        _lookup: dict = {}
        for _val, _n in _counts.items():
            _before = len(_unmapped_warnings)
            _res = _map_to_person(_val)
            _lookup[_val] = _res

            if len(_unmapped_warnings) > _before or (
                isinstance(_val, str) and _val.strip() in _unmapped_warnings
            ):
                _key = str(_val).strip()
                if _key in _unmapped_warnings:
                    _unmapped_warnings[_key] += int(_n) - 1
        result["to_addr"] = result["to_addr"].map(_lookup)
        del _counts, _lookup
        mapped = result["to_addr"].str.startswith("p_").sum()
        log.info("Mapped %d/%d interactions to person_id", mapped, len(result))


        if _unmapped_warnings:
            top_unmapped = sorted(_unmapped_warnings.items(), key=lambda x: -x[1])[:10]
            log.warning(
                "SQ-V2: %d unmapped contacts (top: %s)",
                len(_unmapped_warnings),
                ", ".join(f"{n}({c})" for n, c in top_unmapped),
            )


    log.info("=" * 60)
    log.info("TOTAL: %d interactions classified", len(result))
    log.info("")
    type_dist = result.groupby(["source", "interaction_type"])["weight"].agg(["count", "mean"])
    for (src, itype), row in type_dist.iterrows():
        log.info(
            "  [%s] %-30s  count=%5d  avg_weight=%.3f", src, itype, int(row["count"]), row["mean"]
        )
    log.info("")
    source_dist = result.groupby("source")["weight"].agg(["count", "sum", "mean"])
    for src, row in source_dist.iterrows():
        log.info(
            "  [%s] total=%d  weighted_sum=%.1f  avg=%.3f",
            src,
            int(row["count"]),
            row["sum"],
            row["mean"],
        )

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return

    RQ_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RQ_DIR / "interaction-weights.parquet"

    if "date" in result.columns:
        result["date"] = result["date"].astype(str)
    safe_write_parquet(result, output_path)
    log.info("Written: %s (%d rows)", output_path, len(result))


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-00-weight-interactions", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
