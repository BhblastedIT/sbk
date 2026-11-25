#!/usr/bin/env python3
""
























from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, EMAILS_DIR, OWNER_LABEL, is_own_email

log = logging.getLogger("xs-temporal-analysis")

ATTIO_DIR = DATA_ROOT / "attio"
INSIGHTS_DIR = DATA_ROOT / "insights"
SLACK_DIR = DATA_ROOT / "slack"
CALENDAR_DIR = DATA_ROOT / "calendar"

_EMAIL_RE = re.compile(r"<([^>]+)>")


def _extract_email(addr: str) -> str:
    if not addr:
        return ""
    m = _EMAIL_RE.search(addr)
    return m.group(1).strip().lower() if m else addr.strip().lower()





def load_emails(lookback_days: int = 30) -> pd.DataFrame:
    ""
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    frames = []

    if not EMAILS_DIR.exists():
        return pd.DataFrame()

    for acct_dir in EMAILS_DIR.iterdir():
        if not acct_dir.is_dir():
            continue
        msg_file = acct_dir / "messages.parquet"
        if not msg_file.exists():
            continue
        try:
            df = pd.read_parquet(msg_file)
            df["_account"] = acct_dir.name
            df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[df["date"] >= cutoff]
            frames.append(df)
        except Exception as e:
            log.warning("Error reading %s: %s", msg_file, e)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_slack_messages(lookback_days: int = 30) -> int:
    ""
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    total = 0

    if not SLACK_DIR.exists():
        return 0

    for subdir in SLACK_DIR.iterdir():
        if not subdir.is_dir():
            continue
        for pq_file in subdir.glob("*.parquet"):
            try:
                df = pd.read_parquet(pq_file)
                if "ts" in df.columns:
                    df["ts_dt"] = pd.to_datetime(df["ts"].astype(float), unit="s", utc=True)
                    total += len(df[df["ts_dt"] >= cutoff])
                elif "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
                    total += len(df[df["date"] >= cutoff])
            except Exception:
                pass

    return total


def load_calendar_events(lookback_days: int = 30) -> int:
    ""
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    total = 0

    if not CALENDAR_DIR.exists():
        return 0

    for pq_file in CALENDAR_DIR.glob("**/*.parquet"):
        try:
            df = pd.read_parquet(pq_file)
            date_col = (
                "start" if "start" in df.columns else "date" if "date" in df.columns else None
            )
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], utc=True, errors="coerce")
                total += len(df[df[date_col] >= cutoff])
        except Exception:
            pass

    return total


def load_deals() -> pd.DataFrame:
    ""
    deals_path = ATTIO_DIR / "deals.parquet"
    if not deals_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(deals_path)
    except Exception:
        return pd.DataFrame()





def analyze_productivity(emails_df: pd.DataFrame) -> dict:
    ""



    if emails_df.empty:
        return {
            "hourly_distribution": {},
            "daily_distribution": {},
            "peak_hours": [],
            "peak_day": None,
        }


    sent = emails_df[emails_df["from_addr"].apply(lambda x: is_own_email(_extract_email(str(x))))]

    if sent.empty:
        return {
            "hourly_distribution": {},
            "daily_distribution": {},
            "peak_hours": [],
            "peak_day": None,
        }


    hours = sent["date"].dt.hour
    hourly = hours.value_counts().sort_index()
    hourly_dict = {str(h): int(c) for h, c in hourly.items()}


    peak_hours = hourly.nlargest(2).index.tolist()


    days = sent["date"].dt.dayofweek
    daily = days.value_counts().sort_index()
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    daily_dict = {day_names[d]: int(c) for d, c in daily.items()}

    peak_day_idx = daily.idxmax() if not daily.empty else None
    peak_day = day_names[peak_day_idx] if peak_day_idx is not None else None


    total_sent = len(sent)
    peak_count = sum(hourly.get(h, 0) for h in peak_hours)
    pct_in_peak = round(peak_count / total_sent, 2) if total_sent > 0 else 0

    return {
        "hourly_distribution": hourly_dict,
        "daily_distribution": daily_dict,
        "peak_hours": peak_hours,
        "peak_day": peak_day,
        "total_sent": total_sent,
        "total_received": len(emails_df) - total_sent,
        "pct_in_peak_hours": pct_in_peak,
    }


def analyze_relational(emails_df: pd.DataFrame, top_n: int = 10) -> dict:
    ""



    if emails_df.empty:
        return {"top_contacts": [], "dormant_contacts": []}


    contact_counts: Counter = Counter()
    contact_last_date: dict[str, datetime] = {}

    for _, row in emails_df.iterrows():
        from_email = _extract_email(str(row.get("from_addr", "")))
        to_emails_raw = str(row.get("to_addr", ""))
        msg_date = row["date"]

        if is_own_email(from_email):

            for part in to_emails_raw.split(","):
                e = _extract_email(part)
                if e and "@" in e and not is_own_email(e):
                    contact_counts[e] += 1
                    if e not in contact_last_date or msg_date > contact_last_date[e]:
                        contact_last_date[e] = msg_date
        else:

            if from_email and "@" in from_email:
                contact_counts[from_email] += 1
                if from_email not in contact_last_date or msg_date > contact_last_date[from_email]:
                    contact_last_date[from_email] = msg_date


    top_contacts = [
        {
            "email": email,
            "count": count,
            "last_date": contact_last_date.get(email, "").isoformat()
            if contact_last_date.get(email)
            else None,
        }
        for email, count in contact_counts.most_common(top_n)
    ]


    now = datetime.now(UTC)
    two_weeks_ago = now - timedelta(days=14)
    four_weeks_ago = now - timedelta(days=28)

    recent_emails = emails_df[emails_df["date"] >= two_weeks_ago]
    older_emails = emails_df[
        (emails_df["date"] >= four_weeks_ago) & (emails_df["date"] < two_weeks_ago)
    ]

    recent_contacts: set[str] = set()
    for _, row in recent_emails.iterrows():
        from_e = _extract_email(str(row.get("from_addr", "")))
        if not is_own_email(from_e) and from_e:
            recent_contacts.add(from_e)
        for part in str(row.get("to_addr", "")).split(","):
            e = _extract_email(part)
            if e and not is_own_email(e):
                recent_contacts.add(e)

    older_contact_counts: Counter = Counter()
    for _, row in older_emails.iterrows():
        from_e = _extract_email(str(row.get("from_addr", "")))
        if not is_own_email(from_e) and from_e:
            older_contact_counts[from_e] += 1
        for part in str(row.get("to_addr", "")).split(","):
            e = _extract_email(part)
            if e and not is_own_email(e):
                older_contact_counts[e] += 1

    dormant = []
    for email, old_count in older_contact_counts.items():
        if old_count >= 3 and email not in recent_contacts:
            last = contact_last_date.get(email)
            days_since = (now - last).days if last else None
            dormant.append(
                {
                    "email": email,
                    "previous_interactions": old_count,
                    "days_since_last": days_since,
                }
            )

    dormant.sort(key=lambda x: x.get("previous_interactions", 0), reverse=True)

    return {
        "top_contacts": top_contacts,
        "dormant_contacts": dormant[:10],
        "unique_contacts": len(contact_counts),
    }


def analyze_deals(deals_df: pd.DataFrame) -> dict:
    ""



    if deals_df.empty:
        return {"anomalies": [], "total_deals": 0}

    anomalies = []
    now = datetime.now(UTC)

    for _, deal in deals_df.iterrows():
        name = str(deal.get("name", "Unnamed"))
        stage = str(deal.get("stage", ""))
        updated_at = deal.get("updated_at") or deal.get("last_activity_date_roll_up")

        if not stage or not updated_at:
            continue

        try:
            updated = pd.to_datetime(updated_at, utc=True)
            days_in_stage = (now - updated).days
        except Exception:
            continue


        if days_in_stage > 14:
            anomalies.append(
                {
                    "deal_name": name,
                    "stage": stage,
                    "days_in_stage": days_in_stage,
                    "updated_at": updated.isoformat(),
                    "investor_type": str(deal.get("investor_type", "")),
                }
            )

    anomalies.sort(key=lambda x: x["days_in_stage"], reverse=True)

    return {
        "anomalies": anomalies,
        "total_deals": len(deals_df),
    }




INSIGHT_PROMPT = """You are {owner}'s AI Chief of Staff. Generate 3-5 actionable insights from the week just passed.

WEEK DATA {week}:
- Emails sent: {sent}, received: {received}
- Slack messages: {slack_msgs}
- Meetings: {meetings}
- Unique contacts: {unique_contacts}

PRODUCTIVITY PATTERN:
- Peak hours: {peak_hours}
- Most productive day: {peak_day}
- % emails in peak: {pct_peak}%

DORMANT CONTACTS (were active, now 0 interactions for 14+ days):
{dormant_text}

DEAL ANOMALIES:
{deal_text}

TOP 5 CONTACTS (by interaction frequency):
{top_contacts_text}

Generate ONLY a JSON array of insights (no markdown, no backtick), each with:
{{"id": "ins_NNN", "type": "productivity|relational|deal", "severity": "info|warning|alert", "title": "short title", "content": "actionable insight in 1-2 sentences"}}

Rules:
- Max 5 insights, min 3
- Each insight must suggest a concrete ACTION
- Use specific data (numbers, names), not generalities
- Sort by severity (alert first)"""


def generate_insights(
    stats: dict,
    productivity: dict,
    relational: dict,
    deals: dict,
    week: str,
) -> list[dict]:
    ""

    dormant = relational.get("dormant_contacts", [])
    if dormant:
        dormant_text = "\n".join(
            f"- {d['email']} (was active with {d['previous_interactions']} interactions, silent for {d.get('days_since_last', '?')} days)"
            for d in dormant[:5]
        )
    else:
        dormant_text = "No dormant contact detected"


    anomalies = deals.get("anomalies", [])
    if anomalies:
        deal_text = "\n".join(
            f"- {a['deal_name']} in stage '{a['stage']}' for {a['days_in_stage']} days ({a.get('investor_type', 'N/A')})"
            for a in anomalies[:5]
        )
    else:
        deal_text = "No deal anomaly detected"


    top = relational.get("top_contacts", [])[:5]
    if top:
        top_contacts_text = "\n".join(f"- {t['email']} ({t['count']} interactions)" for t in top)
    else:
        top_contacts_text = "Insufficient data"

    prompt = INSIGHT_PROMPT.format(
        owner=OWNER_LABEL,
        week=week,
        sent=stats.get("emails_sent", 0),
        received=stats.get("emails_received", 0),
        slack_msgs=stats.get("slack_messages", 0),
        meetings=stats.get("meetings", 0),
        unique_contacts=relational.get("unique_contacts", 0),
        peak_hours=", ".join(f"{h}:00" for h in productivity.get("peak_hours", [])),
        peak_day=productivity.get("peak_day", "N/A"),
        pct_peak=round(productivity.get("pct_in_peak_hours", 0) * 100),
        dormant_text=dormant_text,
        deal_text=deal_text,
        top_contacts_text=top_contacts_text,
    )

    try:
        from xs_anthropic_client import get_client

        client = get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return json.loads(text)
    except Exception as e:
        log.error("AI insight generation failed: %s", e)
        return []





def run(
    use_ai: bool = True,
    dry_run: bool = False,
    lookback_days: int = 30,
) -> dict:
    ""
    now = datetime.now(UTC)
    week = now.strftime("%G-W%V")

    log.info("Temporal analysis for week %s (lookback: %d days)", week, lookback_days)


    emails_df = load_emails(lookback_days)
    slack_count = load_slack_messages(lookback_days)
    meetings_count = load_calendar_events(lookback_days)
    deals_df = load_deals()

    log.info(
        "Data loaded: %d emails, %d Slack msgs, %d meetings, %d deals",
        len(emails_df),
        slack_count,
        meetings_count,
        len(deals_df),
    )


    productivity = analyze_productivity(emails_df)
    relational = analyze_relational(emails_df)
    deals_analysis = analyze_deals(deals_df)

    log.info(
        "Productivity: peak hours %s, peak day %s, sent %d",
        productivity.get("peak_hours", []),
        productivity.get("peak_day"),
        productivity.get("total_sent", 0),
    )
    log.info(
        "Relational: %d unique contacts, %d dormant",
        relational.get("unique_contacts", 0),
        len(relational.get("dormant_contacts", [])),
    )
    log.info("Deals: %d anomalies", len(deals_analysis.get("anomalies", [])))


    stats = {
        "emails_sent": productivity.get("total_sent", 0),
        "emails_received": productivity.get("total_received", 0),
        "meetings": meetings_count,
        "slack_messages": slack_count,
        "unique_contacts": relational.get("unique_contacts", 0),
    }


    insights = []
    if use_ai and (stats["emails_sent"] + stats["emails_received"]) > 0:
        insights = generate_insights(stats, productivity, relational, deals_analysis, week)
        log.info("Generated %d insights", len(insights))
    elif not use_ai:
        log.info("AI skipped (--no-ai flag)")
    else:
        log.info("No email data, skipping insight generation")


    period_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    output = {
        "week": week,
        "generated_at": now.isoformat(),
        "period": {"start": period_start, "end": period_end},
        "stats": stats,
        "productivity": productivity,
        "relational": {
            "top_contacts": relational.get("top_contacts", []),
            "dormant_contacts": relational.get("dormant_contacts", []),
            "unique_contacts": relational.get("unique_contacts", 0),
        },
        "deals": deals_analysis,
        "insights": insights,
        "feedback": {},
    }

    if dry_run:
        log.info("Dry run — not saving")
        return output


    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INSIGHTS_DIR / f"weekly-{week}.json"
    out_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log.info("Saved weekly insights to %s", out_path)

    return output




if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="SBK Temporal Intelligence")
    parser.add_argument("--no-ai", action="store_true", help="Skip Claude AI analysis")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument(
        "--weeks", type=int, default=4, help="Lookback period in weeks (default: 4)"
    )
    args = parser.parse_args()

    result = run(
        use_ai=not args.no_ai,
        dry_run=args.dry_run,
        lookback_days=args.weeks * 7,
    )

    print(f"\n{'=' * 60}")
    print(f"Week: {result['week']}")
    print(f"Stats: {result['stats']}")

    prod = result.get("productivity", {})
    if prod.get("peak_hours"):
        print(f"Peak hours: {prod['peak_hours']}, day: {prod.get('peak_day')}")

    dormant = result.get("relational", {}).get("dormant_contacts", [])
    if dormant:
        print(f"\nDormant contacts ({len(dormant)}):")
        for d in dormant[:5]:
            print(
                f"  {d['email']} (was {d['previous_interactions']} interactions, silent {d.get('days_since_last', '?')}d)"
            )

    anomalies = result.get("deals", {}).get("anomalies", [])
    if anomalies:
        print(f"\nDeal anomalies ({len(anomalies)}):")
        for a in anomalies:
            print(f"  {a['deal_name']} in '{a['stage']}' for {a['days_in_stage']}d")

    insights = result.get("insights", [])
    if insights:
        print(f"\nInsights ({len(insights)}):")
        for ins in insights:
            sev = ins.get("severity", "")
            marker = "!!" if sev == "alert" else "!" if sev == "warning" else " "
            print(f"  {marker} [{ins.get('type', '')}] {ins.get('title', '')}")
            print(f"    {ins.get('content', '')}")
