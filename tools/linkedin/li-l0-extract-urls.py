#!/usr/bin/env python3
"""Extract LinkedIn profile URLs for scraping (L0)."""

































import argparse
import sys
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import LINKEDIN_DIR, LINKEDIN_RAW_DIR, safe_write_json  # noqa: E402





sys.path.insert(0, str(Path(__file__).resolve().parent))
import li_safety  # noqa: E402

RAW_DIR = LINKEDIN_RAW_DIR
OUTPUT_FILE = RAW_DIR / "profile-urls-to-scrape.json"
ENRICHED_FILE = RAW_DIR / "profiles-enriched.json"


DEFAULT_LIMIT = 50

LARGE_WORKLIST_THRESHOLD = 200


def _read_daily_calls_made() -> int:
    ""






    path = li_safety._daily_cap_path()
    if not path.exists():
        return 0
    try:
        import json

        return int(json.loads(path.read_text()).get("count", 0))
    except Exception:
        return 0


def _load_already_scraped_ids() -> set:
    ""





    if not ENRICHED_FILE.exists():
        return set()
    try:
        import json

        data = json.loads(ENRICHED_FILE.read_text())
        return {p.get("linkedin_id") for p in data.get("profiles", []) if p.get("linkedin_id")}
    except Exception as exc:
        print(f"WARNING: could not read {ENRICHED_FILE}: {exc} (not excluding scraped)")
        return set()


def main():
    parser = argparse.ArgumentParser(
        description="Extract LinkedIn profile URLs for scraping (safe-by-default on volume)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include already-enriched AND already-scraped profiles (default: fresh only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Limit number of URLs (default {DEFAULT_LIMIT}; 0 means use --no-cap)",
    )
    parser.add_argument(
        "--no-cap",
        action="store_true",
        help="Disable the worklist size cap (UNLIMITED). Explicit opt-in only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Write the worklist even if it is large (> {LARGE_WORKLIST_THRESHOLD} profiles).",
    )
    parser.add_argument(
        "--no-daily-clamp",
        action="store_true",
        help="Do not truncate the worklist to the remaining shared daily budget.",
    )
    args = parser.parse_args()

    contacts_path = LINKEDIN_DIR / "contacts-linkedin.parquet"
    if not contacts_path.exists():
        print(f"ERROR: {contacts_path} not found")
        return

    df = pd.read_parquet(contacts_path)
    print(f"Total contacts: {len(df)}")


    has_url = df[df["linkedin_url"].str.contains("ACoAA", na=False)].copy()
    print(f"With URN-based URL: {len(has_url)}")


    has_url = has_url[~has_url["name"].str.lower().str.contains("linkedin member", na=False)]
    print(f"After removing 'LinkedIn Member': {len(has_url)}")

    if not args.all:

        needs_enrichment = has_url[
            (has_url["headline"].fillna("") == "") | (has_url["company"].fillna("") == "")
        ]
        print(f"Need enrichment (no headline/company): {len(needs_enrichment)}")
        has_url = needs_enrichment




        scraped_ids = _load_already_scraped_ids()
        if scraped_ids:
            before = len(has_url)
            has_url = has_url[~has_url["linkedin_id"].isin(scraped_ids)]
            print(
                f"Excluded already-scraped (in profiles-enriched.json): "
                f"{before - len(has_url)} removed, {len(has_url)} remain"
            )


    has_url = has_url.sort_values("total_messages", ascending=False)





    if not args.no_daily_clamp:
        daily_cap = li_safety.DEFAULT_DAILY_CAP
        made_today = _read_daily_calls_made()
        remaining = max(daily_cap - made_today, 0)
        if remaining <= 0:
            print(
                f"Daily LinkedIn budget exhausted ({made_today}/{daily_cap} calls "
                f"made today). Worklist clamped to 0. Resume tomorrow."
            )
        else:
            print(
                f"Shared daily budget: {made_today}/{daily_cap} used today; "
                f"clamping worklist to remaining {remaining}."
            )
        if len(has_url) > remaining:
            has_url = has_url.head(remaining)




    if args.no_cap:
        print("WARNING: --no-cap set; worklist size NOT capped by --limit.")
    else:
        effective_limit = args.limit
        if effective_limit <= 0:


            print(
                f"--limit 0 without --no-cap is not allowed; using safe default "
                f"{DEFAULT_LIMIT}. Pass --no-cap for unlimited."
            )
            effective_limit = DEFAULT_LIMIT
        if len(has_url) > effective_limit:
            has_url = has_url.head(effective_limit)
            print(f"Limited to top {effective_limit}")





    if len(has_url) > LARGE_WORKLIST_THRESHOLD and not args.force:
        print(
            f"\nABORT: worklist is large ({len(has_url)} profiles > "
            f"{LARGE_WORKLIST_THRESHOLD}). The downstream scraper is intentionally "
            f"conservative (45-120s/req, daily cap {li_safety.DEFAULT_DAILY_CAP}); "
            f"a worklist this size would take many days/runs. "
            f"Re-run with --force to write it anyway, or narrow with --limit."
        )
        return


    profiles = []
    for _, row in has_url.iterrows():
        profiles.append(
            {
                "name": row["name"],
                "linkedin_url": row["linkedin_url"],
                "linkedin_id": row["linkedin_id"],
                "total_messages": int(row["total_messages"]),
                "existing_headline": row.get("headline") or "",
                "existing_company": row.get("company") or "",
            }
        )

    safe_write_json(
        OUTPUT_FILE,
        {
            "generated": pd.Timestamp.now(tz="UTC").isoformat(),
            "total_profiles": len(profiles),
            "profiles": profiles,
        },
    )

    print(f"\nSaved {len(profiles)} profile URLs to {OUTPUT_FILE}")
    print("Top 5 by message count:")
    for p in profiles[:5]:
        print(f"  {p['name']} ({p['total_messages']} msgs) — {p['linkedin_url'][:70]}...")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-linkedin-extract-urls", source="linkedin", stage="l0")
def run():
    main()


if __name__ == "__main__":
    run()
