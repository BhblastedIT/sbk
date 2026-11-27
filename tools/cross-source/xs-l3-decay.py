#!/usr/bin/env python3
"""Relationship decay tracker: for each person, the contact timeline across sources, a score that decays with the
time since the last contact, the tier (inner, sympathy, affinity, active) and alerts when a relationship is
fading.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, notify_macos, setup_logging

from sbk_config import (
    DATA_ROOT,
    DECAY_DIR,
    LINKEDIN_DIR,
    OWN_EMAILS,
    OWN_NAMES_NORMALIZED,
    SLACK_DIR,
    WHATSAPP_DIR,
    is_bot_or_service,
    utc_now,
)

log = logging.getLogger("sbk-l3-decay")



TIERS = {
    "inner": {"min_score": 70, "capacity": 5, "half_life_days": 139},
    "sympathy": {"min_score": 50, "capacity": 15, "half_life_days": 69},
    "affinity": {"min_score": 30, "capacity": 50, "half_life_days": 35},
    "active": {"min_score": 15, "capacity": 150, "half_life_days": 14},
}

TIER_ORDER = ["inner", "sympathy", "affinity", "active"]

EWMA_ALPHA = 0.3
ALERT_COOLDOWN_DAYS = 14
DEFAULT_BUDGET = 5
DECAY_THRESHOLD = 0.70





def _apply_decay_settings():
    ""
    global TIERS, EWMA_ALPHA, ALERT_COOLDOWN_DAYS, DEFAULT_BUDGET, DECAY_THRESHOLD

    import json as _json

    settings_path = DATA_ROOT / "sbk-settings.json"
    if not settings_path.exists():
        return

    try:
        data = _json.loads(settings_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return

    decay = data.get("decay")
    if not isinstance(decay, dict):
        return







    if "ewma_alpha" in decay:
        EWMA_ALPHA = float(decay["ewma_alpha"])
    if "alert_cooldown_days" in decay:
        ALERT_COOLDOWN_DAYS = int(decay["alert_cooldown_days"])
    if "budget" in decay:
        DEFAULT_BUDGET = int(decay["budget"])
    if "threshold" in decay:
        DECAY_THRESHOLD = float(decay["threshold"])


_apply_decay_settings()



MIN_GAP_SAMPLES = 3


DEFAULT_GAP_BY_TIER = {
    "inner": 14,
    "sympathy": 30,
    "affinity": 60,
    "active": 90,
}


MIN_EXPECTED_GAP = 3
MAX_EXPECTED_GAP = 365




STATE_FILE = DECAY_DIR / "decay-state.json"
COOLDOWN_FILE = DECAY_DIR / "cooldown.json"


def alerts_file_for_today() -> Path:
    return DECAY_DIR / f"alerts-{utc_now().strftime('%Y%m%d')}.json"





def cleanup_state(state: dict, valid_pids: set) -> tuple[dict, dict]:
    ""



    cleaned = {}
    stats = {"orphaned": 0, "dead": 0, "total_before": len(state)}

    for pid, entry in state.items():

        if pid not in valid_pids:
            stats["orphaned"] += 1
            continue

        if entry.get("decayed_score", 0) == 0 and entry.get("days_since", 0) > 365:
            stats["dead"] += 1
            continue
        cleaned[pid] = entry

    stats["total_after"] = len(cleaned)
    stats["removed"] = stats["total_before"] - stats["total_after"]
    return cleaned, stats


def cleanup_cooldowns(cooldowns: dict[str, str]) -> tuple[dict[str, str], int]:
    ""



    today_str = str(date.today())
    cleaned = {pid: d for pid, d in cooldowns.items() if d >= today_str}
    removed = len(cooldowns) - len(cleaned)
    return cleaned, removed





def assign_tier(score: float) -> str | None:
    ""
    for tier_name in TIER_ORDER:
        if score >= TIERS[tier_name]["min_score"]:
            return tier_name
    return None





def compute_lambda(half_life_days: float) -> float:
    ""
    return np.log(2) / half_life_days


def compute_decayed_score(baseline: float, lambda_val: float, days_elapsed: float) -> float:
    ""
    return baseline * np.exp(-lambda_val * days_elapsed)





def compute_ewma(gaps: list[float], tier: str | None = None, alpha: float = EWMA_ALPHA) -> float:
    ""






    if len(gaps) < MIN_GAP_SAMPLES:

        raw = float(DEFAULT_GAP_BY_TIER.get(tier or "active", 90))
    else:
        raw = gaps[0]
        for g in gaps[1:]:
            raw = alpha * g + (1 - alpha) * raw


    return max(MIN_EXPECTED_GAP, min(MAX_EXPECTED_GAP, raw))





def load_state() -> dict:
    ""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load decay state: {e}")
    return {}


def save_state(state: dict):
    ""
    DECAY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    log.info(f"State saved: {STATE_FILE} ({len(state)} people)")


def load_cooldowns() -> dict[str, str]:
    ""
    if COOLDOWN_FILE.exists():
        try:
            return json.loads(COOLDOWN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cooldowns(cooldowns: dict[str, str]):
    ""
    DECAY_DIR.mkdir(parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(json.dumps(cooldowns, indent=2))


def save_alerts(alerts: list[dict]):
    ""
    DECAY_DIR.mkdir(parents=True, exist_ok=True)
    path = alerts_file_for_today()
    path.write_text(json.dumps(alerts, indent=2, default=str))
    log.info(f"Alerts saved: {path} ({len(alerts)} alerts)")





def _safe_date_str(value, today_str: str) -> str | None:
    ""
    if pd.isna(value):
        return None
    s = str(value)[:10]

    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    if s > today_str:
        return None
    return s


def _add_dates_to_timeline(
    timelines: dict[str, list[str]],
    pid: str,
    dates: list,
    today_str: str,
):
    ""
    for d in dates:
        ds = _safe_date_str(d, today_str)
        if ds:
            if pid not in timelines:
                timelines[pid] = []
            timelines[pid].append(ds)


def _build_slack_timeline(
    timelines: dict[str, list[str]],
    contacts_df: pd.DataFrame,
    today_str: str,
):
    ""





    for _, row in contacts_df.iterrows():
        pid = str(row.get("person_id", ""))
        if not pid:
            continue
        _add_dates_to_timeline(
            timelines,
            pid,
            [row.get("slack_first_seen"), row.get("slack_last_seen")],
            today_str,
        )


    slack_interactions_file = SLACK_DIR / "interactions-slack.parquet"
    if not slack_interactions_file.exists():
        return

    try:
        slack_df = pd.read_parquet(slack_interactions_file)
    except Exception as e:
        log.warning(f"Failed to load Slack interactions: {e}")
        return

    if slack_df.empty:
        return


    slack_contacts_file = SLACK_DIR / "contacts-slack.parquet"
    if not slack_contacts_file.exists():
        return

    try:
        slack_contacts = pd.read_parquet(slack_contacts_file)
    except Exception:
        return


    email_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        email = str(row.get("email", "")).strip().lower()
        pid = str(row.get("person_id", ""))
        if email and pid:
            email_to_pid[email] = pid


    slack_name_to_pid: dict[str, str] = {}
    for _, sc in slack_contacts.iterrows():
        sc_email = str(sc.get("email", "")).strip().lower()
        sc_name = str(sc.get("real_name", "")).strip()
        sc_display = str(sc.get("display_name", "")).strip()
        pid = email_to_pid.get(sc_email)
        if pid:
            if sc_name:
                slack_name_to_pid[sc_name] = pid
            if sc_display:
                slack_name_to_pid[sc_display] = pid


    own_names = set(OWN_NAMES_NORMALIZED)
    for _, row in slack_df.iterrows():
        from_user = str(row.get("from_user", "")).strip()
        to_user = str(row.get("to_user", "")).strip()


        other = None
        if from_user in own_names or from_user.lower() in own_names:
            other = to_user
        elif to_user in own_names or to_user.lower() in own_names:
            other = from_user
        else:
            continue

        pid = slack_name_to_pid.get(other)
        if not pid:
            continue

        ts = row.get("timestamp")
        ds = _safe_date_str(ts, today_str)
        if ds:
            if pid not in timelines:
                timelines[pid] = []
            timelines[pid].append(ds)


def _build_whatsapp_timeline(
    timelines: dict[str, list[str]],
    contacts_df: pd.DataFrame,
    today_str: str,
):
    ""





    for _, row in contacts_df.iterrows():
        pid = str(row.get("person_id", ""))
        if not pid:
            continue
        _add_dates_to_timeline(
            timelines,
            pid,
            [row.get("wa_first_message"), row.get("wa_last_message")],
            today_str,
        )




    wa_interactions_file = WHATSAPP_DIR / "interactions-whatsapp.parquet"
    if not wa_interactions_file.exists():
        return


    name_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        name = str(row.get("name", "")).strip().lower()
        pid = str(row.get("person_id", ""))
        if name and pid:
            name_to_pid[name] = pid

    own_names_lower = set(OWN_NAMES_NORMALIZED)
    try:
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(wa_interactions_file)
        for batch in pf.iter_batches(
            batch_size=500_000, columns=["from_name", "to_name", "timestamp"]
        ):
            from_names = batch.column("from_name").to_pylist()
            to_names = batch.column("to_name").to_pylist()
            timestamps = batch.column("timestamp").to_pylist()
            for from_name, to_name, ts in zip(from_names, to_names, timestamps):
                fn = (from_name or "").strip()
                tn = (to_name or "").strip()

                if fn.lower() in own_names_lower:
                    other = tn
                elif tn.lower() in own_names_lower:
                    other = fn
                else:
                    continue

                pid = name_to_pid.get(other.lower())
                if not pid:
                    continue

                ds = _safe_date_str(ts, today_str)
                if ds:
                    timelines.setdefault(pid, []).append(ds)
    except Exception as e:
        log.warning(f"Failed to stream WhatsApp interactions: {e}")
        return


def _build_linkedin_timeline(
    timelines: dict[str, list[str]],
    contacts_df: pd.DataFrame,
    today_str: str,
):
    ""





    for _, row in contacts_df.iterrows():
        pid = str(row.get("person_id", ""))
        if not pid:
            continue
        _add_dates_to_timeline(
            timelines,
            pid,
            [row.get("li_first_message_date"), row.get("li_last_message_date")],
            today_str,
        )


    li_interactions_file = LINKEDIN_DIR / "interactions-linkedin.parquet"
    if not li_interactions_file.exists():
        return

    try:
        li_df = pd.read_parquet(li_interactions_file)
    except Exception as e:
        log.warning(f"Failed to load LinkedIn interactions: {e}")
        return

    if li_df.empty:
        return


    name_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        name = str(row.get("name", "")).strip().lower()
        pid = str(row.get("person_id", ""))
        if name and pid:
            name_to_pid[name] = pid

    own_names_lower = set(OWN_NAMES_NORMALIZED)
    for _, row in li_df.iterrows():
        from_name = str(row.get("from_name", "")).strip()
        to_name = str(row.get("to_name", "")).strip()

        other = None
        if from_name.lower() in own_names_lower:
            other = to_name
        elif to_name.lower() in own_names_lower:
            other = from_name
        else:
            continue

        pid = name_to_pid.get(other.lower())
        if not pid:
            continue


        ts = row.get("date") or row.get("timestamp")
        ds = _safe_date_str(ts, today_str)
        if ds:
            if pid not in timelines:
                timelines[pid] = []
            timelines[pid].append(ds)


def _build_tactiq_timeline(
    timelines: dict[str, list[str]],
    contacts_df: pd.DataFrame,
    today_str: str,
):
    ""





    for _, row in contacts_df.iterrows():
        pid = str(row.get("person_id", ""))
        if not pid:
            continue
        _add_dates_to_timeline(
            timelines,
            pid,
            [row.get("tactiq_first_seen"), row.get("tactiq_last_seen")],
            today_str,
        )


def build_contact_timeline(data: SBKData) -> dict[str, list[str]]:
    ""





    contacts_df = data.contacts
    interactions_df = data.interactions
    calendar_df = data.calendar_interactions


    email_to_pid: dict[str, str] = {}
    for _, row in contacts_df.iterrows():
        email = str(row.get("email", "")).strip().lower()
        pid = str(row.get("person_id", ""))
        if email and pid:
            email_to_pid[email] = pid

    timelines: dict[str, list[str]] = {}
    today_str = datetime.now(UTC).date().isoformat()


    for _, row in interactions_df.iterrows():
        from_email = str(row.get("from_email", "")).strip().lower()
        to_email = str(row.get("to_email", "")).strip().lower()

        other_email = None
        if from_email in OWN_EMAILS:
            other_email = to_email
        elif to_email in OWN_EMAILS:
            other_email = from_email
        else:
            continue

        pid = email_to_pid.get(other_email)
        if not pid:
            continue

        _add_dates_to_timeline(
            timelines,
            pid,
            [row.get("first_date"), row.get("last_date")],
            today_str,
        )


    if not calendar_df.empty:
        for _, row in calendar_df.iterrows():
            email_a = str(row.get("email_a", "")).strip().lower()
            email_b = str(row.get("email_b", "")).strip().lower()

            other_email = None
            if email_a in OWN_EMAILS:
                other_email = email_b
            elif email_b in OWN_EMAILS:
                other_email = email_a
            else:
                continue

            pid = email_to_pid.get(other_email)
            if not pid:
                continue

            _add_dates_to_timeline(
                timelines,
                pid,
                [row.get("first_date"), row.get("last_date")],
                today_str,
            )


    log.debug("Adding Slack timeline data...")
    _build_slack_timeline(timelines, contacts_df, today_str)


    log.debug("Adding WhatsApp timeline data...")
    _build_whatsapp_timeline(timelines, contacts_df, today_str)


    log.debug("Adding LinkedIn timeline data...")
    _build_linkedin_timeline(timelines, contacts_df, today_str)


    log.debug("Adding Tactiq timeline data...")
    _build_tactiq_timeline(timelines, contacts_df, today_str)


    for pid in timelines:
        timelines[pid] = sorted(set(timelines[pid]))

    return timelines


def compute_inter_contact_gaps(dates: list[str]) -> list[float]:
    ""
    if len(dates) < 2:
        return []

    gaps = []
    for i in range(1, len(dates)):
        try:
            d1 = datetime.strptime(dates[i - 1], "%Y-%m-%d")
            d2 = datetime.strptime(dates[i], "%Y-%m-%d")
            gap = (d2 - d1).days
            if gap > 0:
                gaps.append(float(gap))
        except ValueError:
            continue
    return gaps





def run_decay_analysis(
    data: SBKData,
    budget: int = DEFAULT_BUDGET,
    dry_run: bool = False,
    full_report: bool = False,
) -> list[dict]:
    ""

    today = datetime.now(UTC).date()
    today_str = today.isoformat()

    contacts_df = data.contacts.copy()
    if contacts_df.empty or "person_id" not in contacts_df.columns:
        log.warning("No merged contacts yet (enriched/contacts-merged.parquet): nothing to analyse")
        return []


    valid_pids = set(contacts_df["person_id"].dropna().astype(str))


    if "is_automated" in contacts_df.columns:
        contacts_df = contacts_df[contacts_df["is_automated"] != True]  # noqa: E712
    contacts_df = contacts_df[contacts_df["score"].fillna(0) > 0]
    if contacts_df.empty:
        # e.g. an address book alone: its people have no interaction to score yet
        log.info("No contact with a relationship score yet: nothing to analyse")
        return []


    if "name" in contacts_df.columns:
        human_mask = ~contacts_df["name"].fillna("").apply(is_bot_or_service).astype(bool)
        non_human_count = int((~human_mask).sum())
        if non_human_count > 0:
            log.info(f"Filtered {non_human_count} non-human entities (bots/services)")
        contacts_df = contacts_df[human_mask]

    log.info(f"Eligible contacts: {len(contacts_df)}")


    state = load_state()
    cooldowns = load_cooldowns()


    state_before = len(state)
    state, cleanup_stats = cleanup_state(state, valid_pids)
    if cleanup_stats["removed"] > 0:
        log.info(
            f"State cleanup: removed {cleanup_stats['removed']} entries "
            f"({cleanup_stats['orphaned']} orphaned, {cleanup_stats['dead']} dead). "
            f"{state_before} -> {len(state)}"
        )

    cooldowns_before = len(cooldowns)
    cooldowns, cooldowns_removed = cleanup_cooldowns(cooldowns)
    if cooldowns_removed > 0:
        log.info(
            f"Cooldown cleanup: removed {cooldowns_removed} expired. "
            f"{cooldowns_before} -> {len(cooldowns)}"
        )


    log.info("Building multi-channel contact timelines...")
    timelines = build_contact_timeline(data)
    log.info(f"Timelines built for {len(timelines)} people")


    candidates: list[dict] = []
    report_rows: list[dict] = []

    for _, row in contacts_df.iterrows():
        pid = str(row.get("person_id", ""))
        if not pid:
            continue

        score = float(row.get("score", 0))
        tier = assign_tier(score)
        if tier is None:
            continue

        name = str(row.get("name", "")).strip() or "Unknown"
        email = str(row.get("email", "")).strip()


        last_contact = row.get("last_contact")
        if pd.isna(last_contact):
            continue

        last_contact_str = str(last_contact)[:10]
        try:
            last_contact_date = datetime.strptime(last_contact_str, "%Y-%m-%d").date()
        except ValueError:
            continue


        if last_contact_date > today:
            last_contact_date = today
            last_contact_str = today.isoformat()


        timeline = timelines.get(pid, [])
        if timeline:
            try:
                timeline_last = datetime.strptime(timeline[-1], "%Y-%m-%d").date()
                if timeline_last > today:
                    timeline_last = today
                if timeline_last > last_contact_date:
                    last_contact_date = timeline_last
                    last_contact_str = timeline_last.isoformat()
            except ValueError:
                pass

        days_since = (today - last_contact_date).days


        tier_cfg = TIERS[tier]
        lambda_val = compute_lambda(tier_cfg["half_life_days"])


        person_state = state.get(pid, {})
        baseline_score = person_state.get("baseline", score)



        if score > baseline_score:
            baseline_score = score


        stored_gaps = person_state.get("gaps", [])
        timeline = timelines.get(pid, [])
        new_gaps = compute_inter_contact_gaps(timeline)


        if new_gaps:
            all_gaps = new_gaps
        else:
            all_gaps = stored_gaps


        expected_gap = compute_ewma(all_gaps, tier=tier)


        decayed_score = compute_decayed_score(baseline_score, lambda_val, days_since)
        decay_pct = decayed_score / baseline_score if baseline_score > 0 else 1.0


        gap_sample_count = len(all_gaps)


        state[pid] = {
            "baseline": baseline_score,
            "last_score": score,
            "decayed_score": round(decayed_score, 2),
            "tier": tier,
            "expected_gap": round(expected_gap, 1),
            "gap_samples": gap_sample_count,
            "gaps": all_gaps[-20:],
            "last_contact": last_contact_str,
            "days_since": days_since,
            "last_updated": today_str,
        }


        report_row = {
            "person_id": pid,
            "name": name,
            "email": email,
            "score": round(score, 1),
            "tier": tier,
            "baseline": round(baseline_score, 1),
            "decayed_score": round(decayed_score, 1),
            "decay_pct": round(decay_pct, 3),
            "days_since_contact": days_since,
            "expected_gap": round(expected_gap, 1),
            "gap_ratio": round(days_since / expected_gap, 1) if expected_gap > 0 else 0,
            "gap_samples": gap_sample_count,
        }
        report_rows.append(report_row)


        should_alert = False
        reason = ""

        if decay_pct < DECAY_THRESHOLD:
            should_alert = True
            reason = f"Decayed to {decay_pct:.0%} of baseline ({baseline_score:.0f} -> {decayed_score:.0f})"

        if expected_gap > 0 and days_since > 2 * expected_gap:
            gap_ratio = days_since / expected_gap
            should_alert = True
            if reason:
                reason += f"; also contact gap {gap_ratio:.1f}x normal rhythm"
            else:
                reason = f"Contact gap {gap_ratio:.1f}x normal rhythm ({days_since}d vs {expected_gap:.0f}d expected)"

        if not should_alert:
            continue


        last_alert = cooldowns.get(pid)
        if last_alert:
            try:
                last_alert_date = datetime.strptime(last_alert, "%Y-%m-%d").date()
                if (today - last_alert_date).days < ALERT_COOLDOWN_DAYS:
                    log.debug(f"Skipping {name} (cooldown until {last_alert_date})")
                    continue
            except ValueError:
                pass

        candidates.append(
            {
                "person_id": pid,
                "name": name,
                "email": email,
                "score": round(score, 1),
                "tier": tier,
                "days_since_contact": days_since,
                "expected_gap": round(expected_gap, 1),
                "decay_pct": round(decay_pct, 3),
                "reason": reason,

                "_sort_key": (TIER_ORDER.index(tier), decay_pct),
            }
        )


    candidates.sort(key=lambda c: c["_sort_key"])


    alerts = candidates[:budget]


    for a in alerts:
        del a["_sort_key"]


    if full_report:
        report_rows.sort(key=lambda r: r["decay_pct"])
        log.info("DECAY FULL REPORT — %s — %d tracked people", today_str, len(report_rows))
        log.info(
            "%-30s %-10s %6s %6s %8s %7s %5s %7s %6s %5s",
            "Name",
            "Tier",
            "Score",
            "Base",
            "Decayed",
            "Decay%",
            "Days",
            "ExpGap",
            "Ratio",
            "Gaps",
        )
        for r in report_rows:
            flag = " *" if r["decay_pct"] < DECAY_THRESHOLD or r["gap_ratio"] > 2 else "  "
            log.info(
                "%s",
                f"{r['name'][:29]:<30} {r['tier']:<10} {r['score']:>6.1f} "
                f"{r['baseline']:>6.1f} {r['decayed_score']:>8.1f} "
                f"{r['decay_pct']:>6.1%} {r['days_since_contact']:>5} "
                f"{r['expected_gap']:>7.1f} {r['gap_ratio']:>5.1f}x "
                f"{r['gap_samples']:>4}{flag}",
            )
        log.info(
            "* = alert candidate (decay < %s or gap > 2x expected)",
            f"{DECAY_THRESHOLD:.0%}",
        )
        log.info("Total alert candidates (pre-budget): %d", len(candidates))


    if alerts:
        log.info(
            "DECAY ALERTS — %s — %d of %d candidates (budget: %d)",
            today_str,
            len(alerts),
            len(candidates),
            budget,
        )
        for i, a in enumerate(alerts, 1):
            log.info(
                "  [%d] %s (%s) — Score: %s | Days since contact: %s | "
                "Expected gap: %sd | Decay: %s | Reason: %s",
                i,
                a["name"],
                a["tier"],
                a["score"],
                a["days_since_contact"],
                a["expected_gap"],
                f"{a['decay_pct']:.1%}",
                a["reason"],
            )
    else:
        log.info("No decay alerts for %s. All relationships within expected rhythm.", today_str)


    if not dry_run:
        save_state(state)


        for a in alerts:
            cooldowns[a["person_id"]] = today_str
        save_cooldowns(cooldowns)

        save_alerts(alerts)


        if alerts:
            top = alerts[0]
            notify_macos(
                title="SBK Decay Alert",
                message=f"{len(alerts)} relationships need attention. Top: {top['name']} ({top['tier']})",
                group="sbk-decay",
            )
    else:
        log.info("Dry run: state and alerts not written")


    tier_counts = {}
    for r in report_rows:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1


    gap_dist = {"0": 0, "1-2": 0, "3+": 0}
    for r in report_rows:
        gs = r["gap_samples"]
        if gs == 0:
            gap_dist["0"] += 1
        elif gs < MIN_GAP_SAMPLES:
            gap_dist["1-2"] += 1
        else:
            gap_dist["3+"] += 1

    tier_summary = " | ".join(f"{t}: {tier_counts.get(t, 0)}" for t in TIER_ORDER)
    log.info("Summary: %d tracked | %s", len(report_rows), tier_summary)
    log.info(
        "Alert candidates: %d | Alerts sent: %d (budget: %d)", len(candidates), len(alerts), budget
    )
    log.info(
        "Gap samples: %d reliable (3+) | %d insufficient (1-2, using tier default) | "
        "%d no data (using tier default)",
        gap_dist["3+"],
        gap_dist["1-2"],
        gap_dist["0"],
    )
    if cleanup_stats["removed"] > 0:
        log.info(
            "Cleanup: %d orphans + %d dead purged from state",
            cleanup_stats["orphaned"],
            cleanup_stats["dead"],
        )

    return alerts





def main():
    parser = argparse.ArgumentParser(
        description="SBK L3 — Relationship Decay Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute without writing state/alerts"
    )
    parser.add_argument(
        "--full-report", action="store_true", help="Show all tracked people with scores"
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"Max alerts per day (default: {DEFAULT_BUDGET})",
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-decay")

    if args.incremental:
        from sbk_config import ENRICHED_DIR, check_inputs_changed, mark_last_run

        if not check_inputs_changed(
            "l3-decay",
            [ENRICHED_DIR / "contacts-merged.parquet", ENRICHED_DIR / "interactions.parquet"],
        ):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("l3-decay")
            return 0

    log.info("Loading SBK data...")
    data = SBKData()

    alerts = run_decay_analysis(
        data=data,
        budget=args.budget,
        dry_run=args.dry_run,
        full_report=args.full_report,
    )

    if not args.dry_run:
        from sbk_config import ENRICHED_DIR as _ENRICHED
        from sbk_config import mark_last_run, save_input_checkpoint

        save_input_checkpoint(
            "l3-decay", [_ENRICHED / "contacts-merged.parquet", _ENRICHED / "interactions.parquet"]
        )
        mark_last_run("l3-decay")

    return 0 if alerts is not None else 1


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-decay", source="l3-decay", stage="l3", mark_run=False)
def _pipeline_run():
    sys.exit(main())


if __name__ == "__main__":
    _pipeline_run()
