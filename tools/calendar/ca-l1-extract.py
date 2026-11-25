#!/usr/bin/env python3
""







import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sbk_config import (
    CALENDARS_DIR,
    EMAILS_DIR,
    ENRICHED_DIR,
    OWN_EMAILS,
    mark_last_run,
    safe_write_parquet,
    user_cfg,
)


EXCLUDE_SYSTEM_PATTERNS = [
    "group.calendar.google.com",
    "resource.calendar.google.com",
    "unknownorganizer@calendar.google.com",
]



# Your own addresses (sbk.config.json "own_emails") are never a contact.
EXCLUDE_OWNER = set(OWN_EMAILS)

# Shared team and list addresses that are never a contact ("calendar.exclude_addresses"
# in sbk.config.json, e.g. ["team@yourcompany.example"]). Empty by default.
EXCLUDE_TEAM_LISTS = {
    str(a).strip().lower() for a in (user_cfg("calendar.exclude_addresses", []) or []) if str(a).strip()
}


def should_exclude(email: str) -> bool:
    email_lower = email.lower().strip()
    if email_lower in EXCLUDE_OWNER:
        return True
    if email_lower in EXCLUDE_TEAM_LISTS:
        return True
    for pattern in EXCLUDE_SYSTEM_PATTERNS:
        if pattern in email_lower:
            return True
    return False


def parse_attendees(attendees_str: str) -> list[str]:
    ""




    if not attendees_str or attendees_str.strip() == "":
        return []

    stripped = attendees_str.strip()

    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            emails = []
            for item in parsed:
                if isinstance(item, dict):
                    email = item.get("email", "")
                    if email:
                        emails.append(email)
                elif isinstance(item, str) and item:
                    emails.append(item)
            return emails
        except (json.JSONDecodeError, TypeError):
            pass


    return [e.strip() for e in stripped.split(",") if e.strip()]


def get_event_date(row: pd.Series) -> str | None:
    ""
    dt_str = row.get("start_datetime", "")
    if not dt_str:
        return None

    return dt_str[:10]


def _caselle_vive() -> set[str]:
    ""

    try:
        return set(json.loads((EMAILS_DIR / "accounts.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def eventi_senza_doppioni(
    parquet_files: list[tuple[str, Path]],
) -> list[tuple[str, pd.DataFrame]]:
    ""







    vive = _caselle_vive()
    parti, senza_id = [], []
    for ordine, (account, percorso) in enumerate(parquet_files):
        df = pd.read_parquet(percorso)
        if "id" not in df.columns:
            senza_id.append((ordine, account, df))
            continue
        vecchia = df["calendar_id"].isna() if "calendar_id" in df.columns else True
        parti.append(
            df.assign(
                _account=account, _vecchia=vecchia, _ferma=account not in vive, _ordine=ordine
            )
        )
    fuori: list[tuple[int, str, pd.DataFrame]] = list(senza_id)
    if parti:
        tutto = pd.concat(parti, ignore_index=True)
        con_id = tutto[tutto["id"].notna()].sort_values(
            ["_vecchia", "_ferma", "_ordine"], kind="stable"
        )
        tutto = pd.concat([con_id.drop_duplicates("id", keep="first"), tutto[tutto["id"].isna()]])
        for account, g in tutto.groupby("_account", sort=False):
            fuori.append(
                (
                    int(g["_ordine"].iloc[0]),
                    account,
                    g.drop(columns=["_account", "_vecchia", "_ferma", "_ordine"]),
                )
            )
    return [(account, df) for _, account, df in sorted(fuori, key=lambda t: t[0])]


def discover_parquet_files() -> list[tuple[str, Path]]:
    ""
    results = []
    if not CALENDARS_DIR.exists():
        return results
    for subdir in sorted(CALENDARS_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        pq = subdir / "events.parquet"
        if pq.exists():
            results.append((subdir.name, pq))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Calendar L1 — extract contacts and interactions from calendar parquet"
    )
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would run without writing"
    )
    args = parser.parse_args()


    parquet_files = discover_parquet_files()
    if not parquet_files:
        print(f"No events.parquet files found under {CALENDARS_DIR}/*/")
        return

    input_paths = [pq_path for _, pq_path in parquet_files]

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("calendar-l1", input_paths):
            print("Incremental: inputs unchanged — skipping")
            mark_last_run("calendar-l1")
            return


    contacts = defaultdict(
        lambda: {
            "names": defaultdict(int),
            "total_events": 0,
            "as_organizer": 0,
            "as_attendee": 0,
            "first_seen": None,
            "last_seen": None,
            "calendars": set(),
        }
    )

    total_events_processed = 0
    events_per_account = {}

    eventi = eventi_senza_doppioni(parquet_files)


    for account_name, df in eventi:
        print(f"Processing {account_name}...")
        events_per_account[account_name] = len(df)
        total_events_processed += len(df)

        for _, row in df.iterrows():
            event_date = get_event_date(row)
            calendar_name = row.get("calendar_name", account_name) or account_name


            seen_in_event = set()


            organizer_email = row.get("organizer_email", "") or ""
            if organizer_email and not should_exclude(organizer_email):
                email_lower = organizer_email.lower().strip()
                c = contacts[email_lower]
                c["as_organizer"] += 1
                c["calendars"].add(calendar_name)
                seen_in_event.add(email_lower)

                if event_date:
                    if c["first_seen"] is None or event_date < c["first_seen"]:
                        c["first_seen"] = event_date
                    if c["last_seen"] is None or event_date > c["last_seen"]:
                        c["last_seen"] = event_date


            attendee_emails = parse_attendees(row.get("attendees", "") or "")
            for att_email in attendee_emails:
                if not att_email or should_exclude(att_email):
                    continue

                email_lower = att_email.lower().strip()
                c = contacts[email_lower]
                c["as_attendee"] += 1
                c["calendars"].add(calendar_name)




                seen_in_event.add(email_lower)

                if event_date:
                    if c["first_seen"] is None or event_date < c["first_seen"]:
                        c["first_seen"] = event_date
                    if c["last_seen"] is None or event_date > c["last_seen"]:
                        c["last_seen"] = event_date


            for email_lower in seen_in_event:
                contacts[email_lower]["total_events"] += 1


    records = []
    for email, data in contacts.items():

        best_name = ""
        if data["names"]:
            best_name = max(data["names"].items(), key=lambda x: x[1])[0]

        domain = email.split("@")[1] if "@" in email else ""

        records.append(
            {
                "email": email,
                "name": best_name,
                "total_events": data["total_events"],
                "as_organizer": data["as_organizer"],
                "as_attendee": data["as_attendee"],
                "first_seen": data["first_seen"],
                "last_seen": data["last_seen"],
                "calendars": sorted(data["calendars"]),
                "domain": domain,
            }
        )


    records.sort(key=lambda x: x["total_events"], reverse=True)

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print("\nAccounts processed:")
    for account_name, count in events_per_account.items():
        print(f"  {account_name}: {count} events")
    print(f"  Total events processed: {total_events_processed}")

    print(f"\nTotal unique contacts: {len(records)}")

    print("\n--- Top 20 contacts by total_events ---")
    for i, rec in enumerate(records[:20], 1):
        print(
            f"  {i:3d}. {rec['email']:45s} | events={rec['total_events']:4d} | org={rec['as_organizer']:4d} | att={rec['as_attendee']:4d} | name={rec['name']}"
        )


    domain_counts = defaultdict(int)
    for rec in records:
        domain_counts[rec["domain"]] += 1
    domain_sorted = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)

    print("\n--- Top 20 domains by unique contacts ---")
    for i, (domain, count) in enumerate(domain_sorted[:20], 1):
        print(f"  {i:3d}. {domain:35s} | {count} contacts")


    today = datetime.now()
    cap_str = f"{today.year}-12-31"

    for rec in records:
        rec["source"] = "calendar"
        rec["calendars"] = json.dumps(rec["calendars"])

        if rec["last_seen"] and rec["last_seen"] > cap_str:
            rec["last_seen"] = cap_str

    df_contacts = pd.DataFrame(records)
    contacts_path = ENRICHED_DIR / "contacts-calendar.parquet"
    if not args.dry_run:
        safe_write_parquet(df_contacts, contacts_path, index=False)
    print(
        f"\n{'[DRY RUN] Would write' if args.dry_run else 'Parquet:'} {len(df_contacts)} contacts -> {contacts_path}"
    )


    interactions = []
    for account_name, df in eventi:
        for _, row in df.iterrows():
            event_date = get_event_date(row)
            calendar_name = row.get("calendar_name", account_name) or account_name
            emails_in_event = set()

            organizer_email = row.get("organizer_email", "") or ""
            if organizer_email and not should_exclude(organizer_email):
                emails_in_event.add(organizer_email.lower().strip())

            attendee_emails = parse_attendees(row.get("attendees", "") or "")
            for att_email in attendee_emails:
                if att_email and not should_exclude(att_email):
                    emails_in_event.add(att_email.lower().strip())

            emails_list = sorted(emails_in_event)
            for i, e1 in enumerate(emails_list):
                for e2 in emails_list[i + 1 :]:
                    interactions.append(
                        {
                            "from_email": e1,
                            "to_email": e2,
                            "event_date": event_date,
                            "calendar": calendar_name,
                        }
                    )

    if interactions:
        idf = pd.DataFrame(interactions)

        idf.loc[idf["event_date"] > cap_str, "event_date"] = cap_str

        agg = (
            idf.groupby(["from_email", "to_email"])
            .agg(
                event_count=("event_date", "count"),
                first_date=("event_date", "min"),
                last_date=("event_date", "max"),
                calendars=("calendar", lambda x: json.dumps(sorted(set(x)))),
            )
            .reset_index()
        )
        agg["source"] = "calendar"
        interactions_path = ENRICHED_DIR / "interactions-calendar.parquet"
        if not args.dry_run:
            safe_write_parquet(agg, interactions_path, index=False)
        print(
            f"{'[DRY RUN] Would write' if args.dry_run else 'Parquet:'} {len(agg)} interaction pairs -> {interactions_path}"
        )

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    from sbk_config import save_input_checkpoint

    save_input_checkpoint("calendar-l1", input_paths)
    mark_last_run("calendar-l1")


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-calendar-extract", source="calendar-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
