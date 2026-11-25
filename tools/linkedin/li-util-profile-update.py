#!/usr/bin/env python3
"""Update LinkedIn contacts with scraped profile data."""















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
from sbk_config import (  # noqa: E402
    ENRICHED_DIR,
    LINKEDIN_DIR,
    LINKEDIN_RAW_DIR,
    safe_write_parquet,
)



RAW_DIR = LINKEDIN_RAW_DIR

PROFILES_ENRICHED = RAW_DIR / "profiles-enriched.json"
CONTACTS_LINKEDIN = LINKEDIN_DIR / "contacts-linkedin.parquet"
CONTACTS_MERGED = ENRICHED_DIR / "contacts-merged.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("linkedin-update")




def load_enriched_profiles():
    ""
    if not PROFILES_ENRICHED.exists():
        log.error(f"Enriched profiles not found: {PROFILES_ENRICHED}")
        log.error("Run first: node tools/linkedin-profile-scraper.js")
        sys.exit(1)

    with open(PROFILES_ENRICHED) as f:
        data = json.load(f)

    profiles = data.get("profiles", [])
    log.info(f"Loaded {len(profiles)} enriched profiles from {PROFILES_ENRICHED}")


    by_id = {}
    for p in profiles:
        lid = p.get("linkedin_id", "")
        if lid and lid not in by_id:
            by_id[lid] = p

    log.info(f"Unique linkedin_ids: {len(by_id)}")
    return by_id, data.get("stats", {})





def update_contacts_linkedin(profiles_by_id, dry_run=False):
    ""
    if not CONTACTS_LINKEDIN.exists():
        log.error(f"Contacts file not found: {CONTACTS_LINKEDIN}")
        return 0

    df = pd.read_parquet(CONTACTS_LINKEDIN)
    log.info(f"Loaded contacts-linkedin.parquet: {len(df)} rows")


    for col in [
        "location",
        "about",
        "vanity_url",
        "public_profile_url",
        "profile_picture_url",
        "industry",
        "degree",
        "enriched_at",
    ]:
        if col not in df.columns:
            df[col] = ""

    updated = 0
    for idx, row in df.iterrows():
        lid = str(row.get("linkedin_id", ""))
        if not lid or lid not in profiles_by_id:
            continue

        p = profiles_by_id[lid]


        changed = False


        if p.get("headline") and (not row.get("headline") or row["headline"] == ""):
            df.at[idx, "headline"] = p["headline"]
            changed = True


        if p.get("company") and (not row.get("company") or row["company"] == ""):
            df.at[idx, "company"] = p["company"]
            changed = True


        if p.get("location"):
            df.at[idx, "location"] = p["location"]
            changed = True


        if p.get("about"):
            df.at[idx, "about"] = p["about"][:500]
            changed = True


        if p.get("vanity_url"):
            df.at[idx, "vanity_url"] = p["vanity_url"]

            if p.get("public_profile_url"):
                df.at[idx, "public_profile_url"] = p["public_profile_url"]
            changed = True


        if p.get("profile_picture_url"):
            df.at[idx, "profile_picture_url"] = p["profile_picture_url"]
            changed = True


        if p.get("industry"):
            df.at[idx, "industry"] = p["industry"]
            changed = True


        if p.get("degree"):
            df.at[idx, "degree"] = p["degree"]
            changed = True

        if changed:
            df.at[idx, "enriched_at"] = datetime.now(UTC).isoformat()
            updated += 1

    log.info(f"Updated {updated} contacts in contacts-linkedin.parquet")

    if not dry_run and updated > 0:

        backup = CONTACTS_LINKEDIN.with_suffix(".parquet.bak")
        if CONTACTS_LINKEDIN.exists():
            import shutil

            shutil.copy2(CONTACTS_LINKEDIN, backup)
            log.info(f"Backup saved to {backup}")

        safe_write_parquet(df, CONTACTS_LINKEDIN, index=False)
        log.info(f"Saved updated contacts-linkedin.parquet ({len(df)} rows)")

    return updated





def update_contacts_merged(profiles_by_id, dry_run=False):
    ""
    if not CONTACTS_MERGED.exists():
        log.warning(f"Merged contacts not found: {CONTACTS_MERGED}")
        log.warning("Run cross-source-merge.py after this for full update.")
        return 0

    df = pd.read_parquet(CONTACTS_MERGED)
    log.info(f"Loaded contacts-merged.parquet: {len(df)} rows, {len(df.columns)} cols")


    url_to_profile = {}
    for lid, p in profiles_by_id.items():

        if p.get("original_url"):
            url_to_profile[p["original_url"]] = p

        if p.get("public_profile_url"):
            url_to_profile[p["public_profile_url"]] = p

    updated = 0
    for idx, row in df.iterrows():
        li_url = str(row.get("linkedin_url", "") or "")
        if not li_url:
            continue


        p = url_to_profile.get(li_url)


        if not p and "ACoAA" in li_url:
            import re

            match = re.search(r"(ACoAA[A-Za-z0-9_-]+)", li_url)
            if match:
                p = profiles_by_id.get(match.group(1))

        if not p:
            continue

        changed = False


        if p.get("headline"):
            current = str(row.get("linkedin_headline", "") or "")
            if not current:
                df.at[idx, "linkedin_headline"] = p["headline"]
                changed = True


        if p.get("company"):
            current = str(row.get("organization", "") or "")
            if not current:
                df.at[idx, "organization"] = p["company"]
                changed = True


        if p.get("public_profile_url") and "ACoAA" in li_url:
            df.at[idx, "linkedin_url"] = p["public_profile_url"]
            changed = True

        if changed:
            updated += 1

    log.info(f"Updated {updated} contacts in contacts-merged.parquet")

    if not dry_run and updated > 0:

        backup = CONTACTS_MERGED.with_suffix(".parquet.bak")
        import shutil

        shutil.copy2(CONTACTS_MERGED, backup)
        log.info(f"Backup saved to {backup}")

        safe_write_parquet(df, CONTACTS_MERGED, index=False)
        log.info(f"Saved updated contacts-merged.parquet ({len(df)} rows)")

    return updated





def print_enrichment_stats(profiles_by_id):
    ""
    if not profiles_by_id:
        log.info("No enriched profiles to analyze.")
        return

    profiles = list(profiles_by_id.values())
    total = len(profiles)


    fields = {
        "headline": sum(1 for p in profiles if p.get("headline")),
        "company": sum(1 for p in profiles if p.get("company")),
        "location": sum(1 for p in profiles if p.get("location")),
        "about": sum(1 for p in profiles if p.get("about")),
        "vanity_url": sum(1 for p in profiles if p.get("vanity_url")),
        "profile_picture_url": sum(1 for p in profiles if p.get("profile_picture_url")),
        "industry": sum(1 for p in profiles if p.get("industry")),
    }

    log.info("=" * 60)
    log.info("  ENRICHMENT STATISTICS (%d profiles)", total)
    log.info("=" * 60)

    for field, count in fields.items():
        pct = (count / total * 100) if total > 0 else 0
        bar = "#" * int(pct / 2) + "." * (50 - int(pct / 2))
        log.info("  %s %5d/%d (%5.1f%%) [%s]", f"{field:25s}", count, total, pct, bar)


    api_sources = {}
    for p in profiles:
        src = p.get("source_api", "unknown")
        api_sources[src] = api_sources.get(src, 0) + 1

    log.info("  API sources:")
    for src, count in sorted(api_sources.items(), key=lambda x: -x[1]):
        log.info("    %s: %d", src, count)


    companies = {}
    for p in profiles:
        c = p.get("company", "").strip()
        if c:
            companies[c] = companies.get(c, 0) + 1

    log.info("  Top 15 companies:")
    for company, count in sorted(companies.items(), key=lambda x: -x[1])[:15]:
        log.info("    %s: %d", company, count)


    locations = {}
    for p in profiles:
        loc = p.get("location", "").strip()
        if loc:
            locations[loc] = locations.get(loc, 0) + 1

    log.info("  Top 15 locations:")
    for loc, count in sorted(locations.items(), key=lambda x: -x[1])[:15]:
        log.info("    %s: %d", loc, count)


    name_changes = 0
    for p in profiles:
        orig = (p.get("original_name") or "").lower().strip()
        curr = (p.get("name") or "").lower().strip()
        if orig and curr and orig != curr:

            orig_parts = set(orig.split())
            curr_parts = set(curr.split())
            overlap = len(orig_parts & curr_parts)
            if overlap < min(len(orig_parts), len(curr_parts)):
                name_changes += 1

    log.info("  Name mismatches (original vs current): %d", name_changes)
    log.info("=" * 60)





def main():
    parser = argparse.ArgumentParser(
        description="Update LinkedIn contacts with scraped profile data"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without saving"
    )
    parser.add_argument("--stats-only", action="store_true", help="Only show enrichment statistics")
    args = parser.parse_args()

    log.info("SBK — LinkedIn Profile Update")
    log.info("Merge enriched profiles into parquet files")

    profiles_by_id, scraper_stats = load_enriched_profiles()


    print_enrichment_stats(profiles_by_id)

    if args.stats_only:
        return

    if args.dry_run:
        log.info("[DRY RUN] No files will be modified.")


    log.info("─" * 60)
    log.info("Phase 1: Update contacts-linkedin.parquet")
    log.info("─" * 60)
    updated_linkedin = update_contacts_linkedin(profiles_by_id, dry_run=args.dry_run)


    log.info("─" * 60)
    log.info("Phase 2: Update contacts-merged.parquet")
    log.info("─" * 60)
    updated_merged = update_contacts_merged(profiles_by_id, dry_run=args.dry_run)


    log.info("=" * 60)
    log.info("UPDATE COMPLETE")
    log.info("=" * 60)
    log.info("contacts-linkedin.parquet: %d rows updated", updated_linkedin)
    log.info("contacts-merged.parquet:   %d rows updated", updated_merged)

    if args.dry_run:
        log.info("[DRY RUN] No files were modified.")
    else:
        log.info("Backups saved as .parquet.bak")
        log.info("NOTE: For full score recalculation, run: python3 tools/cross-source-merge.py")

    log.info("=" * 60)


if __name__ == "__main__":
    main()
