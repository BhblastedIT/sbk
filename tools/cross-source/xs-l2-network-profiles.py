#!/usr/bin/env python3
"""Network profiles: one Markdown profile per person listed in "network_profiles.people" in sbk.config.json, from
email scores, calendar contacts, Plaud mentions and the raw data, plus an index.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas required. Install with: pip3 install pandas pyarrow")
    sys.exit(1)

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, NETWORK_DIR, NOTES_DIR, user_cfg

# Profiles are personal data: they go under the data root (<data root>/network/<tier>/<id>.md),
# never into the repo. Paths in the output are shown relative to the data root.
SBK_DIR = DATA_ROOT
INDEX_FILE = NETWORK_DIR / "_index.md"
RAW_DIR = NOTES_DIR

DATA_DIR = DATA_ROOT
SCORES_FILE = DATA_DIR / "exports" / "relationship-scores.parquet"
CALENDAR_FILE = DATA_DIR / "enriched" / "contacts-calendar.parquet"
PLAUD_CROSSREF = DATA_DIR / "plaud" / "raw" / "_calendar_crossref.json"

TODAY = datetime.now().strftime("%Y-%m-%d")







# The people to profile come from "network_profiles.people" in sbk.config.json:
# {"<id>": {"name": ..., "tier": "tier_1|tier_2|tier_3", "search_names": [...],
#           "known_emails": [...], and optional trust, reliability, strategic_value,
#           emotional_closeness, momentum, role, base, relationship, what_does,
#           open_loops, style, energy, reciprocity}}.
# sbk.config.example.json has one filled-in example. Empty by default: nothing is profiled.
_TIERS = ("tier_1", "tier_2", "tier_3")


def _load_people() -> dict[str, dict]:
    raw = user_cfg("network_profiles.people", {}) or {}
    people: dict[str, dict] = {}
    for pid, pdata in raw.items():
        if not isinstance(pdata, dict):
            continue
        name = str(pdata.get("name") or pid).strip()
        person = dict(pdata)
        person["name"] = name
        person["tier"] = pdata.get("tier") if pdata.get("tier") in _TIERS else "tier_3"
        person["search_names"] = list(pdata.get("search_names") or [name])
        person["known_emails"] = list(pdata.get("known_emails") or [])
        for field in ("role", "base", "relationship"):
            person[field] = str(pdata.get(field) or "N/D")
        people[str(pid).strip()] = person
    return people


PEOPLE: dict[str, dict] = _load_people()


def load_email_scores():
    ""
    if not SCORES_FILE.exists():
        print(f"WARNING: {SCORES_FILE} not found")
        return pd.DataFrame()
    return pd.read_parquet(SCORES_FILE)


def load_calendar_contacts():
    ""
    if not CALENDAR_FILE.exists():
        print(f"WARNING: {CALENDAR_FILE} not found")
        return pd.DataFrame()
    return pd.read_parquet(CALENDAR_FILE)


def load_plaud_crossref():
    ""
    if not PLAUD_CROSSREF.exists():
        print(f"WARNING: {PLAUD_CROSSREF} not found")
        return []
    with open(PLAUD_CROSSREF) as f:
        data = json.load(f)
    return data.get("matches", [])


def search_raw_mentions(name_variants, raw_dir):
    ""
    if not raw_dir.exists():
        return 0, []
    files_with_mentions = []
    total_mentions = 0
    for md_file in sorted(raw_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        count = 0
        for name in name_variants:
            count += content.lower().count(name.lower())
        if count > 0:
            files_with_mentions.append(md_file.name)
            total_mentions += count
    return total_mentions, files_with_mentions


def get_email_data(person, df_scores):
    ""
    if df_scores.empty:
        return {"score": "N/D", "total_msgs": "N/D", "last_date": "N/D", "primary_email": "N/D"}

    emails = person.get("known_emails", [])
    if not emails:
        return {"score": "N/D", "total_msgs": "N/D", "last_date": "N/D", "primary_email": "N/D"}

    matches = df_scores[df_scores["email"].isin(emails)]
    if matches.empty:

        for sn in person["search_names"]:
            m = df_scores[df_scores["name"].str.contains(sn, case=False, na=False)]
            if not m.empty:
                matches = m
                break

    if matches.empty:
        return {"score": "N/D", "total_msgs": "N/D", "last_date": "N/D", "primary_email": "N/D"}


    best = matches.loc[matches["score"].idxmax()]
    total_msgs = (
        int(matches["email_total_msgs"].sum()) if "email_total_msgs" in matches.columns else 0
    )
    last_date = (
        str(matches["last_contact"].max())[:10] if "last_contact" in matches.columns else "N/D"
    )

    return {
        "score": round(float(best["score"]), 1),
        "total_msgs": total_msgs,
        "last_date": last_date,
        "primary_email": best["email"],
    }


def get_calendar_data(person, df_cal):
    ""
    if df_cal.empty:
        return {"total_events": "N/D", "first_seen": "N/D", "last_seen": "N/D"}

    emails = person.get("known_emails", [])
    matches = pd.DataFrame()

    if emails:
        matches = df_cal[df_cal["email"].isin(emails)]

    if matches.empty:

        for sn in person["search_names"]:
            m = df_cal[
                df_cal["name"].str.contains(sn, case=False, na=False)
                | df_cal["email"].str.contains(sn.lower().replace(" ", ""), case=False, na=False)
            ]
            if not m.empty:
                matches = m
                break

    if matches.empty:
        return {"total_events": "N/D", "first_seen": "N/D", "last_seen": "N/D"}

    total_events = int(matches["total_events"].sum())
    first_seen = str(matches["first_seen"].min())[:10]
    last_seen = str(matches["last_seen"].max())[:10]

    return {"total_events": total_events, "first_seen": first_seen, "last_seen": last_seen}


def get_plaud_count(person, plaud_matches):
    ""
    if not plaud_matches:
        return 0

    count = 0
    search_terms = [s.lower() for s in person["search_names"]] + [
        e.lower() for e in person.get("known_emails", [])
    ]

    for match in plaud_matches:
        attendees_str = " ".join(match.get("attendees", [])).lower()
        cal_event = match.get("calendar_event", "").lower()
        for term in search_terms:
            if term in attendees_str or term in cal_event:
                count += 1
                break
    return count


def generate_profile(person_id, person, email_data, cal_data, plaud_count, raw_mentions, raw_files):
    ""
    name = person["name"]
    tier = person["tier"].upper()
    tier_label = {
        "TIER_1": "inner circle",
        "TIER_2": "active network",
        "TIER_3": "wider network",
    }.get(tier, "")

    trust = person.get("trust", "N/D")
    reliability = person.get("reliability", "N/D")
    strategic = person.get("strategic_value", "N/D")
    emotional = person.get("emotional_closeness", "N/D")


    email_score_display = f"{email_data['score']}/100" if email_data["score"] != "N/D" else "N/D"
    total_msgs_display = (
        str(email_data["total_msgs"]) if email_data["total_msgs"] != "N/D" else "N/D"
    )
    last_date_display = str(email_data["last_date"]) if email_data["last_date"] != "N/D" else "N/D"
    cal_events_display = (
        str(cal_data["total_events"]) if cal_data["total_events"] != "N/D" else "N/D"
    )
    plaud_display = str(plaud_count) if plaud_count > 0 else "0"

    lines = []
    lines.append(f"# {name} — {tier.title()}")
    lines.append("")
    lines.append(f"> Tier: {tier} ({tier_label})")
    lines.append(f"> Last update: {TODAY}")
    lines.append(
        f"> Trust: {trust} | Reliability: {reliability} | Strategic Value: {strategic} | Emotional Closeness: {emotional}"
    )
    lines.append("")
    lines.append("## Who")
    lines.append("")
    lines.append(f"- **Role**: {person['role']}")
    lines.append(f"- **Base**: {person['base']}")
    lines.append(f"- **Relationship**: {person['relationship']}")
    lines.append("")
    lines.append("## Quantitative data")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---------|--------|")
    lines.append(f"| Email score | {email_score_display} |")
    lines.append(f"| Total emails | {total_msgs_display} |")
    lines.append(f"| Last email contact | {last_date_display} |")
    lines.append(f"| Calendar events | {cal_events_display} |")
    lines.append(f"| Recorded meetings | {plaud_display} |")
    lines.append(f"| Mentions in raw analysis | {raw_mentions} (in {len(raw_files)} files) |")
    lines.append("")
    lines.append("## What they do")
    lines.append("")
    for item in person.get("what_does", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Open loops")
    lines.append("")
    for i, item in enumerate(person.get("open_loops", []), 1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("## Communication style")
    lines.append("")
    for item in person.get("style", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append(f"## Energy exchange: {person.get('energy', 'N/D')}")
    lines.append(f"## Reciprocity: {person.get('reciprocity', 'N/D')}")
    lines.append(f"## Momentum: {person.get('momentum', 'N/D')}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate network profiles from cross-referenced data"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument(
        "--tier",
        choices=["tier_1", "tier_2", "tier_3", "all"],
        default="all",
        help="Filter by tier (default: all)",
    )
    args = parser.parse_args()

    print("=== Network Profile Generator ===")
    print(f"Date: {TODAY}")
    print(f"Tier filter: {args.tier}")
    print(f"Dry run: {args.dry_run}")
    print()


    print("Loading data sources...")
    df_scores = load_email_scores()
    print(f"  Email scores: {len(df_scores)} rows")

    df_cal = load_calendar_contacts()
    print(f"  Calendar contacts: {len(df_cal)} rows")

    plaud_matches = load_plaud_crossref()
    print(f"  Plaud crossref: {len(plaud_matches)} matches")
    print()


    people_to_process = {}
    for pid, pdata in PEOPLE.items():
        if args.tier == "all" or pdata["tier"] == args.tier:
            people_to_process[pid] = pdata

    if not PEOPLE:
        print(
            "No people configured: add network_profiles.people to sbk.config.json "
            "(see sbk.config.example.json). Nothing to do."
        )
    print(f"People to process: {len(people_to_process)}")
    print()

    created = 0
    skipped = 0

    for person_id, person in people_to_process.items():
        tier_dir = person["tier"]
        filepath = NETWORK_DIR / tier_dir / f"{person_id}.md"


        if filepath.exists():
            print(f"  SKIP (exists): {filepath.relative_to(SBK_DIR)}")
            skipped += 1
            continue


        email_data = get_email_data(person, df_scores)
        cal_data = get_calendar_data(person, df_cal)
        plaud_count = get_plaud_count(person, plaud_matches)
        raw_mentions, raw_files = search_raw_mentions(person["search_names"], RAW_DIR)


        content = generate_profile(
            person_id, person, email_data, cal_data, plaud_count, raw_mentions, raw_files
        )

        if args.dry_run:
            print(f"  WOULD CREATE: {filepath.relative_to(SBK_DIR)}")
            print(
                f"    Email score: {email_data['score']}, Msgs: {email_data['total_msgs']}, "
                f"Cal: {cal_data['total_events']}, Plaud: {plaud_count}, Raw: {raw_mentions}"
            )
        else:

            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            print(f"  CREATED: {filepath.relative_to(SBK_DIR)}")
            print(
                f"    Email score: {email_data['score']}, Msgs: {email_data['total_msgs']}, "
                f"Cal: {cal_data['total_events']}, Plaud: {plaud_count}, Raw: {raw_mentions}"
            )
            created += 1

    print()
    print("=== Summary ===")
    print(f"Created: {created}")
    print(f"Skipped (existing): {skipped}")
    print(f"Total profiles now: {skipped + created}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-network-profiles", source="l2-network-profiles", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
