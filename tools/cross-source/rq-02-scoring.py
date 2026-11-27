#!/usr/bin/env python3
"""RQ-02: composite relationship score for each person, from the decayed interactions plus email and calendar
intensity, team membership, recurring meetings, shared threads and calls and two-way exchanges, with the circle
each person falls in.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import (
    CALENDARS_DIR,
    EMAILS_DIR,
    ENRICHED_DIR,
    KNOWLEDGE_RELATIONSHIPS_DIR,
    OWN_EMAILS,
    PERSONIO_DIR,
    RQ_DIR,
    RQ_SCORES_V2_FILE,
    RQ_SIGNALS_FILE,
    TACTIQ_DIR,
    is_owner_speaker,
    safe_write_json,
    safe_write_parquet,
)

log = logging.getLogger("rq-02")

# Your own addresses (sbk.config.json "own_emails") as one regex, plus the "owner"
# placeholder rq-00 writes when own_emails is empty.
_OWN_ADDR_RE = "|".join([r"^owner$"] + [re.escape(e) for e in sorted(OWN_EMAILS)])


def _recalc_circle(score: float) -> str:
    ""
    circles = [
        (8.0, 10.01, "inner_circle"),
        (5.0, 8.0, "sympathy_group"),
        (3.0, 5.0, "active_network"),
        (1.5, 3.0, "full_network"),
        (0.0, 1.5, "extended"),
    ]
    for low, high, circle in circles:
        if low <= score < high:
            return circle
    return "extended"


def _get_circle_label(circle: str) -> str:
    ""
    labels = {
        "inner_circle": "Collaboratore strettissimo",
        "sympathy_group": "Contatto importante",
        "active_network": "Contatto regolare",
        "full_network": "Conoscenza",
        "extended": "Sotto soglia",
    }
    return labels.get(circle, circle)


def _load_rq_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    ""
    weights_file = RQ_DIR / "interaction-weights.parquet"
    decay_file = RQ_DIR / "decay-state.parquet"




    weights_cols = ["date", "weight", "to_addr", "source", "from_addr"]
    weights = (
        pd.read_parquet(weights_file, columns=weights_cols)
        if weights_file.exists()
        else pd.DataFrame()
    )
    decay = pd.read_parquet(decay_file) if decay_file.exists() else pd.DataFrame()
    return weights, decay


def _build_person_email_map() -> dict[str, set[str]]:
    ""
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if not cm_path.exists():
        return {}
    cm = pd.read_parquet(cm_path, columns=["person_id", "email", "all_emails"])
    result: dict[str, set[str]] = {}
    for _, row in cm.iterrows():
        pid = row["person_id"]
        emails: set[str] = set()
        if pd.notna(row.get("email")):
            emails.add(str(row["email"]).lower().strip())
        all_e = row.get("all_emails")
        if pd.notna(all_e):
            if isinstance(all_e, str):
                try:
                    all_e = json.loads(all_e)
                except (ValueError, TypeError):
                    all_e = [all_e]
            if isinstance(all_e, list):
                for e in all_e:
                    emails.add(str(e).lower().strip())
        if emails:
            result[pid] = emails
    return result


def normalize_person_key(raw: str, email_to_pid: dict[str, str]) -> str | None:
    ""









    raw = raw.strip()
    if "," in raw:
        return None
    if raw.startswith("p_") and "@" not in raw:
        return raw
    if "<" in raw and ">" in raw:
        raw = raw[raw.index("<") + 1 : raw.index(">")].strip()
    if not raw or len(raw) > 200 or any(c in raw for c in '/"<>\\'):
        return None
    if "@" not in raw:
        return None
    email = raw.lower()
    return email_to_pid.get(email, email)


def _build_person_name_map() -> dict[str, str]:
    ""
    cm_path = ENRICHED_DIR / "contacts-merged.parquet"
    if not cm_path.exists():
        return {}
    cm = pd.read_parquet(cm_path, columns=["person_id", "name"])
    result: dict[str, str] = {}
    for _, row in cm.iterrows():
        pid = row["person_id"]
        name = str(row.get("name", "")) if pd.notna(row.get("name")) else ""
        if name:
            result[pid] = name
    return result


def _extract_emails_from_field(raw: str) -> list[str]:
    ""
    import re

    if not raw or not raw.strip():
        return []
    emails = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"<([^>]+@[^>]+)>", part)
        if m:
            emails.append(m.group(1).lower().strip())
        elif "@" in part:

            emails.append(part.lower().strip())
    return emails


def _load_email_intensity() -> dict[str, tuple[float, float]]:
    ""




    import numpy as np

    email_stats: dict[str, list[tuple[int, int]]] = {}
    own_lower = {e.lower() for e in OWN_EMAILS}

    for msg_file in sorted(EMAILS_DIR.glob("*/messages.parquet")):
        try:
            df = pd.read_parquet(
                msg_file,
                columns=["from_addr", "to_addr", "body_text", "in_reply_to"],
            )
        except Exception:
            continue

        for row in df.itertuples():
            from_emails = _extract_emails_from_field(
                str(row.from_addr) if pd.notna(row.from_addr) else ""
            )
            to_emails = _extract_emails_from_field(
                str(row.to_addr) if pd.notna(row.to_addr) else ""
            )
            body_len = len(str(row.body_text)) if pd.notna(row.body_text) else 0
            has_reply = 1 if pd.notna(row.in_reply_to) and str(row.in_reply_to).strip() else 0

            from_is_owner = any(e in own_lower for e in from_emails)
            to_is_owner = any(e in own_lower for e in to_emails)


            others: set[str] = set()
            if from_is_owner:
                others.update(e for e in to_emails if e not in own_lower)
            elif to_is_owner:
                others.update(e for e in from_emails if e not in own_lower)

            for other in others:
                email_stats.setdefault(other, []).append((body_len, has_reply))

    result = {}
    for email, pairs in email_stats.items():
        if not pairs:
            continue
        lengths = [p[0] for p in pairs]
        replies = [p[1] for p in pairs]
        avg_len = float(np.mean(lengths)) if lengths else 0.0

        thread_depth = float(np.mean(replies)) * 10.0
        result[email] = (avg_len, thread_depth)

    return result


def _load_calendar_intensity() -> dict[str, float]:
    ""




    attendee_durations: dict[str, list[float]] = {}
    own_lower = {e.lower() for e in OWN_EMAILS}

    for ev_file in sorted(CALENDARS_DIR.glob("*/events.parquet")):
        try:
            df = pd.read_parquet(
                ev_file,
                columns=["start_datetime", "end_datetime", "attendees"],
            )
        except Exception:
            continue

        for row in df.itertuples():
            if pd.isna(row.start_datetime) or pd.isna(row.end_datetime):
                continue
            try:
                start = pd.Timestamp(row.start_datetime)
                end = pd.Timestamp(row.end_datetime)
                duration_min = (end - start).total_seconds() / 60.0
            except Exception:
                continue
            if duration_min <= 0 or duration_min > 480:
                continue

            attendees_str = str(row.attendees) if pd.notna(row.attendees) else ""
            for att in attendees_str.split(","):
                att = att.strip().lower()
                if att and "@" in att and att not in own_lower:
                    attendee_durations.setdefault(att, []).append(duration_min)

    import numpy as np

    return {
        email: float(np.mean(durations))
        for email, durations in attendee_durations.items()
        if durations
    }


def _load_team_membership() -> set[str]:
    ""




    emp_file = PERSONIO_DIR / "processed" / "employees.parquet"
    if not emp_file.exists():
        return set()
    try:
        df = pd.read_parquet(emp_file, columns=["email", "status"])
    except Exception:
        return set()

    own_lower = {e.lower() for e in OWN_EMAILS}
    team_emails = set()
    for _, row in df.iterrows():
        status = str(row.get("status", "")).lower()
        if status == "terminated":
            continue
        if pd.notna(row.get("email")):
            email = str(row["email"]).lower().strip()
            if email not in own_lower:
                team_emails.add(email)

    return team_emails


def _load_recurring_meetings() -> dict[str, int]:
    ""







    import re

    own_lower = {e.lower() for e in OWN_EMAILS}

    meeting_counts: dict[tuple[str, str], int] = {}

    def _normalize_title(title: str) -> str:
        ""
        title = title.lower().strip()

        title = re.sub(r"\d{1,2}[/.\-]\d{1,2}([/.\-]\d{2,4})?", "", title)
        title = re.sub(r"#\d+", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title

    for ev_file in sorted(CALENDARS_DIR.glob("*/events.parquet")):
        try:
            df = pd.read_parquet(ev_file, columns=["summary", "attendees"])
        except Exception:
            continue

        for row in df.itertuples():
            summary = str(row.summary) if pd.notna(row.summary) else ""
            if not summary.strip():
                continue
            norm_title = _normalize_title(summary)
            if len(norm_title) < 3:
                continue

            attendees_str = str(row.attendees) if pd.notna(row.attendees) else ""
            for att in attendees_str.split(","):
                att = att.strip().lower()
                if att and "@" in att and att not in own_lower:
                    meeting_counts[(att, norm_title)] = meeting_counts.get((att, norm_title), 0) + 1


    result: dict[str, int] = {}
    for (email, _title), count in meeting_counts.items():
        if count >= 3:
            result[email] = result.get(email, 0) + 1

    return result


def _load_terminated_employees() -> set[str]:
    ""
    emp_file = PERSONIO_DIR / "processed" / "employees.parquet"
    if not emp_file.exists():
        return set()
    try:
        df = pd.read_parquet(emp_file, columns=["email", "status"])
    except Exception:
        return set()

    terminated = set()
    for _, row in df.iterrows():
        if pd.notna(row.get("status")) and str(row["status"]).lower() == "terminated":
            if pd.notna(row.get("email")):
                terminated.add(str(row["email"]).lower().strip())

    return terminated


def _load_shared_email_threads() -> dict[str, int]:
    ""




    own_lower = {e.lower() for e in OWN_EMAILS}

    threads: dict[str, set[str]] = {}

    for msg_file in sorted(EMAILS_DIR.glob("*/messages.parquet")):
        try:
            df = pd.read_parquet(msg_file, columns=["thread_id", "from_addr", "to_addr"])
        except Exception:
            continue

        for row in df.itertuples():
            tid = str(row.thread_id) if pd.notna(row.thread_id) else None
            if not tid:
                continue
            from_emails = _extract_emails_from_field(
                str(row.from_addr) if pd.notna(row.from_addr) else ""
            )
            to_emails = _extract_emails_from_field(
                str(row.to_addr) if pd.notna(row.to_addr) else ""
            )
            threads.setdefault(tid, set())
            threads[tid].update(from_emails)
            threads[tid].update(to_emails)


    result: dict[str, int] = {}
    for _tid, participants in threads.items():
        owner_in = any(e in own_lower for e in participants)
        if not owner_in:
            continue
        for p in participants:
            if p not in own_lower and "@" in p:
                result[p] = result.get(p, 0) + 1

    return result


def _load_shared_calls() -> dict[str, int]:
    ""








    result: dict[str, int] = {}
    tactiq_file = TACTIQ_DIR / "interactions-tactiq.parquet"
    if not tactiq_file.exists():
        return result

    try:
        df = pd.read_parquet(tactiq_file)
    except Exception:
        return result

    for row in df.itertuples():
        s1 = str(row.speaker_1).strip() if pd.notna(row.speaker_1) else ""
        s2 = str(row.speaker_2).strip() if pd.notna(row.speaker_2) else ""
        count = int(row.meeting_count) if pd.notna(row.meeting_count) else 1


        owner_marker = "_OWNER_"
        if s1 == owner_marker and s2 and s2 != owner_marker:
            result[s2] = result.get(s2, 0) + count
            result[s2.lower()] = result.get(s2.lower(), 0) + count
        elif s2 == owner_marker and s1 and s1 != owner_marker:
            result[s1] = result.get(s1, 0) + count
            result[s1.lower()] = result.get(s1.lower(), 0) + count

    return result


def _load_bidirectional_counts() -> dict[str, tuple[int, int]]:
    ""








    from sbk_config import SLACK_DIR

    own_lower = {e.lower() for e in OWN_EMAILS}

    counts: dict[str, list[int]] = {}


    for msg_file in sorted(EMAILS_DIR.glob("*/messages.parquet")):
        try:
            df = pd.read_parquet(msg_file, columns=["from_addr", "to_addr"])
        except Exception:
            continue

        for row in df.itertuples():
            from_emails = _extract_emails_from_field(
                str(row.from_addr) if pd.notna(row.from_addr) else ""
            )
            to_emails = _extract_emails_from_field(
                str(row.to_addr) if pd.notna(row.to_addr) else ""
            )

            from_is_owner = any(e in own_lower for e in from_emails)
            to_is_owner = any(e in own_lower for e in to_emails)

            if from_is_owner and not to_is_owner:

                for e in to_emails:
                    if e not in own_lower:
                        counts.setdefault(e, [0, 0])[0] += 1
            elif to_is_owner and not from_is_owner:

                for e in from_emails:
                    if e not in own_lower:
                        counts.setdefault(e, [0, 0])[1] += 1


    slack_file = SLACK_DIR / "interactions-slack.parquet"
    if slack_file.exists():
        try:
            sdf = pd.read_parquet(slack_file)
            for row in sdf.itertuples():
                from_u = str(row.from_user) if pd.notna(row.from_user) else ""
                to_u = str(row.to_user) if pd.notna(row.to_user) else ""
                msg_type = str(row.message_type) if pd.notna(row.message_type) else ""
                if msg_type != "dm_1to1":
                    continue
                from_is_owner = from_u.lower() in own_lower or is_owner_speaker(from_u)
                to_is_owner = to_u.lower() in own_lower or is_owner_speaker(to_u)
                if from_is_owner and not to_is_owner:
                    counts.setdefault(to_u, [0, 0])[0] += 1
                elif to_is_owner and not from_is_owner:
                    counts.setdefault(from_u, [0, 0])[1] += 1
        except Exception:
            pass

    return {email: (c[0], c[1]) for email, c in counts.items()}


def main():
    parser = argparse.ArgumentParser(description="RQ-02: Composite relationship scoring")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--person", type=str, help="Score single person (to_addr or entity_id)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rq_composite_scoring import score_relationship

    weights, decay = _load_rq_data()
    if weights.empty:
        log.warning("No RQ-00 data found. Run rq-00-weight-interactions.py first.")
        return


    log.info("Loading enrichment data...")
    person_email_map = _build_person_email_map()
    person_name_map = _build_person_name_map()
    email_intensity = _load_email_intensity()
    calendar_intensity = _load_calendar_intensity()
    team_emails = _load_team_membership()
    shared_threads = _load_shared_email_threads()
    recurring_meetings = _load_recurring_meetings()
    shared_calls = _load_shared_calls()
    terminated_emails = _load_terminated_employees()
    bidir_counts = _load_bidirectional_counts()
    log.info(
        "Enrichment: %d email intensity, %d calendar intensity, %d team, %d threads, %d recurring, %d calls, %d terminated, %d bidir",
        len(email_intensity),
        len(calendar_intensity),
        len(team_emails),
        len(shared_threads),
        len(recurring_meetings),
        len(shared_calls),
        len(terminated_emails),
        len(bidir_counts),
    )


    def _resolve_emails(person_key: str) -> set[str]:
        ""
        if person_key.startswith("p_"):
            return person_email_map.get(person_key, set())
        if "@" in person_key:
            return {person_key.lower().strip()}
        return set()



    import numpy as np

    now = pd.Timestamp.now(tz="UTC")
    weights["dt"] = pd.to_datetime(weights["date"], errors="coerce", utc=True)
    weights["days_ago"] = (now - weights["dt"]).dt.total_seconds() / 86400.0
    weights["days_ago"] = weights["days_ago"].clip(lower=0).fillna(365)
    weights["recency_factor"] = np.power(0.5, weights["days_ago"] / 180.0)
    weights["recency_weight"] = weights["weight"] * weights["recency_factor"]


    person_groups = weights.groupby("to_addr")
    max_recency_weighted = person_groups["recency_weight"].sum().max()

    log.info(
        "Scoring %d contacts (max recency-weighted: %.1f)",
        len(person_groups),
        max_recency_weighted,
    )

    results = []
    enriched_count = 0
    ex_employee_count = 0
    for person, group in person_groups:
        if args.person and args.person != str(person):
            continue


        recency_weighted_sum = group["recency_weight"].sum()
        raw_weighted_sum = group["weight"].sum()


        recent_mask = group["days_ago"] <= 365
        recent_group = group[recent_mask]
        source_counts = (
            recent_group.groupby("source")["weight"].count()
            if len(recent_group) > 0
            else pd.Series(dtype=int)
        )
        active_channels = sum(1 for cnt in source_counts.values if cnt >= 3)







        person_emails = _resolve_emails(str(person))


        owner_mask = group["from_addr"].str.contains(_OWN_ADDR_RE, case=False, na=False, regex=True)
        base_initiated = group.loc[owner_mask, "weight"].sum()
        base_received = group.loc[~owner_mask, "weight"].sum()



        email_received_supplement = 0
        for email in person_emails:
            if email in bidir_counts:
                _i, r = bidir_counts[email]
                email_received_supplement += r

        if email_received_supplement == 0 and str(person) in bidir_counts:
            _i, r = bidir_counts[str(person)]
            email_received_supplement += r

        initiated = int(round(base_initiated))
        received = int(round(base_received)) + email_received_supplement


        state = "active"
        if not decay.empty and "person" in decay.columns:
            person_decay = decay[decay["person"] == str(person)]
            if not person_decay.empty:
                state = str(person_decay.iloc[0].get("state", "active"))


        avg_email_len = 0.0
        avg_thread_depth = 0.0
        avg_meeting_dur = 0.0
        for email in person_emails:
            if email in email_intensity:
                el, td = email_intensity[email]
                avg_email_len = max(avg_email_len, el)
                avg_thread_depth = max(avg_thread_depth, td)
            if email in calendar_intensity:
                avg_meeting_dur = max(avg_meeting_dur, calendar_intensity[email])


        shared_thread_count = max((shared_threads.get(e, 0) for e in person_emails), default=0)
        recurring_meeting_count = max(
            (recurring_meetings.get(e, 0) for e in person_emails), default=0
        )

        shared_call_count = max((shared_calls.get(e, 0) for e in person_emails), default=0)
        if shared_call_count == 0:

            person_name = person_name_map.get(str(person), "")
            if person_name:
                shared_call_count = shared_calls.get(person_name, 0)
                if shared_call_count == 0:
                    shared_call_count = shared_calls.get(person_name.lower(), 0)

        has_enrichment = (
            avg_email_len > 0
            or avg_meeting_dur > 0
            or shared_thread_count > 0
            or recurring_meeting_count > 0
            or shared_call_count > 0
        )
        if has_enrichment:
            enriched_count += 1

        result = score_relationship(
            weighted_interaction_count=recency_weighted_sum,
            max_in_network=max_recency_weighted,
            initiated=initiated,
            received=received,
            active_channels=active_channels,
            avg_meeting_duration_min=avg_meeting_dur,
            avg_email_length_chars=avg_email_len,
            avg_thread_depth=avg_thread_depth,
            shared_recurring_meetings=recurring_meeting_count,
            shared_email_threads=shared_thread_count,
            shared_calls=shared_call_count,
            state=state,
        )


        recent_30d = len(group[group["days_ago"] <= 30])
        recent_90d = len(group[group["days_ago"] <= 90])
        if recent_30d >= 5 or recent_90d >= 10:
            result["trend"] = "stable"
        elif recent_90d >= 1:
            result["trend"] = "cooling"
        elif recent_90d == 0 and len(group) > 0:
            result["trend"] = "dormant"


        is_ex_employee = bool(person_emails & terminated_emails)
        if is_ex_employee:
            result["score"] = round(max(1.0, result["score"] * 0.65), 1)
            result["dunbar_circle"] = _recalc_circle(result["score"])
            result["dunbar_label"] = _get_circle_label(result["dunbar_circle"])
            ex_employee_count += 1

        result["person"] = str(person)
        result["weighted_sum"] = round(raw_weighted_sum, 2)
        result["recency_weighted_sum"] = round(recency_weighted_sum, 2)
        result["interaction_count"] = len(group)
        result["is_ex_employee"] = is_ex_employee
        results.append(result)

    log.info("Enriched %d/%d contacts with intensity/context data", enriched_count, len(results))
    log.info("Applied ex-employee penalty to %d contacts", ex_employee_count)

    if not results:
        log.warning("No results")
        return


    log.info("=" * 60)
    log.info("TOTAL: %d contacts scored", len(results))


    circle_counts = {}
    for r in results:
        c = r["dunbar_circle"]
        circle_counts[c] = circle_counts.get(c, 0) + 1
    for circle in ["inner_circle", "sympathy_group", "active_network", "full_network", "extended"]:
        log.info("  %-20s %5d", circle, circle_counts.get(circle, 0))


    v2_df = pd.DataFrame()
    if RQ_SIGNALS_FILE.exists():
        from rq_scoring_v2 import score_all_v2

        log.info("V2: Scoring from signals.parquet...")
        v2_df = score_all_v2()
        log.info(
            "V2: %d persons scored (max %.1f)",
            len(v2_df),
            v2_df["score_v2"].max() if len(v2_df) > 0 else 0,
        )
    else:
        log.info("V2: No signals.parquet found, skipping V2 scoring")


    v3_flag = RQ_DIR / "rq-v3-enabled.flag"
    v3_df = pd.DataFrame()
    if v3_flag.exists() and RQ_SIGNALS_FILE.exists():
        from rq_scoring_v3 import score_all_v3

        log.info("V3: Scoring from signals.parquet (V3 flag enabled)...")
        v3_df = score_all_v3()
        log.info(
            "V3: %d persons scored (max %.1f, mean %.2f)",
            len(v3_df),
            v3_df["score_v3"].max() if len(v3_df) > 0 else 0,
            v3_df["score_v3"].mean() if len(v3_df) > 0 else 0,
        )
    elif not v3_flag.exists():
        log.info("V3: Flag not set (%s), skipping V3 scoring", v3_flag)

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return


    RQ_DIR.mkdir(parents=True, exist_ok=True)
    flat = []
    for r in results:
        row = {
            "person": r["person"],
            "score": r["score"],
            "trend": r["trend"],
            "dunbar_circle": r["dunbar_circle"],
            "weighted_sum": r["weighted_sum"],
            "interaction_count": r["interaction_count"],
            "is_ex_employee": r.get("is_ex_employee", False),
        }
        for dim, val in r["breakdown"].items():
            row[f"dim_{dim}"] = val
        flat.append(row)

    df_out = pd.DataFrame(flat)


    if "person" in df_out.columns:
        n_total = len(df_out)
        n_unique = df_out["person"].nunique()
        if n_total != n_unique:
            log.warning(
                "SQ-08: %d duplicate person_ids in scoring output (%d total, %d unique)",
                n_total - n_unique,
                n_total,
                n_unique,
            )
            df_out = df_out.drop_duplicates(subset=["person"], keep="first")
            log.info("SQ-08: deduplicated to %d rows", len(df_out))

    safe_write_parquet(df_out, RQ_DIR / "composite-scores.parquet")
    log.info("Written: %s (%d rows)", RQ_DIR / "composite-scores.parquet", len(df_out))


    KNOWLEDGE_RELATIONSHIPS_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0




    email_to_pid: dict[str, str] = {}
    for _pid, _emails in person_email_map.items():
        for _e in _emails:
            email_to_pid.setdefault(_e, _pid)

    for r in results:
        person_id = normalize_person_key(r["person"], email_to_pid)
        if not person_id:
            skipped += 1
            continue
        detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{person_id}.json"
        detail = {
            "person": r["person"],
            "score": r["score"],
            "breakdown": r["breakdown"],
            "trend": r["trend"],
            "dunbar_circle": r["dunbar_circle"],
            "last_scored": datetime.now(UTC).isoformat(),
        }
        safe_write_json(detail_file, detail)
        written += 1

    log.info("Written %d relationship detail JSONs (skipped %d malformed)", written, skipped)


    if not v2_df.empty:
        safe_write_parquet(v2_df, RQ_SCORES_V2_FILE)
        log.info("V2: Written %s (%d rows)", RQ_SCORES_V2_FILE, len(v2_df))


        v2_by_pid = v2_df.set_index("person")
        augmented = 0
        for pid, emails in person_email_map.items():
            if pid not in v2_by_pid.index:
                continue
            v2_row = v2_by_pid.loc[pid]
            for email in emails:
                detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{email}.json"
                if detail_file.exists():
                    try:
                        data = json.loads(detail_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
                    data["score_v2"] = float(v2_row["score_v2"])
                    data["breakdown_v2"] = {
                        k.replace("dim_", ""): round(float(v2_row[k]), 4)
                        for k in v2_row.index
                        if k.startswith("dim_")
                    }
                    data["dunbar_circle_v2"] = v2_row["dunbar_circle"]
                    data["confidence_v2"] = round(float(v2_row["confidence"]), 3)
                    data["trend_v2"] = v2_row["trend"]
                    safe_write_json(detail_file, data)
                    augmented += 1
                    break
        v2_total = len(v2_df)
        v2_in_map = sum(1 for pid in v2_by_pid.index if pid in person_email_map)
        log.info(
            "V2: %d scored, %d in person_email_map, %d augmented", v2_total, v2_in_map, augmented
        )


    if not v3_df.empty:
        v3_scores_file = RQ_DIR / "composite-scores-v3.parquet"
        safe_write_parquet(v3_df, v3_scores_file)
        log.info("V3: Written %s (%d rows)", v3_scores_file, len(v3_df))


        v3_by_pid = v3_df.set_index("person")
        augmented_v3 = 0
        for pid, emails in person_email_map.items():
            if pid not in v3_by_pid.index:
                continue
            v3_row = v3_by_pid.loc[pid]
            for email in emails:
                detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{email}.json"
                if detail_file.exists():
                    try:
                        data = json.loads(detail_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
                    data["score_v3"] = float(v3_row["score_v3"])
                    data["confidence_v3"] = round(float(v3_row["confidence"]), 3)
                    data["relationship_type"] = str(v3_row["relationship_type"])
                    data["severity_level"] = int(v3_row["severity_level"])
                    data["dunbar_circle_v3"] = str(v3_row["dunbar_circle"])
                    data["breakdown_v3"] = {
                        k.replace("dim_", ""): round(float(v3_row[k]), 4)
                        for k in v3_row.index
                        if k.startswith("dim_") and not k.startswith("raw_dim_")
                    }
                    safe_write_json(detail_file, data)
                    augmented_v3 += 1
                    break
        log.info("V3: %d augmented detail JSONs", augmented_v3)


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-02-scoring", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
