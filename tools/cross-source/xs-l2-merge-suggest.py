#!/usr/bin/env python3
"""Merge suggestions: pairs of contacts that are probably the same person (similar names, shared domains), above a
fuzzy score, into enriched/merge-suggestions.json for review.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
_THIS_DIR = Path(__file__).resolve().parent
for p in (_TOOLS_DIR, _THIS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sbk_config import ENRICHED_DIR

log = logging.getLogger("sbk-merge-suggest")

OUTPUT_FILE = ENRICHED_DIR / "merge-suggestions.json"


MIN_NAME_LEN = 4

MIN_NAME_WORDS = 2


def normalize_name(name: str) -> str:
    ""
    if not name or not isinstance(name, str):
        return ""
    return " ".join(name.strip().lower().split())


def extract_domain(email: str) -> str:
    ""
    if not email or "@" not in str(email):
        return ""
    return str(email).split("@")[1].lower().strip()


def run(dry_run: bool = False, min_score: int = 75) -> list[dict]:
    ""



    try:
        from rapidfuzz import fuzz
    except ImportError:
        log.error("rapidfuzz not installed. Run: uv pip install rapidfuzz")
        return []

    contacts_file = ENRICHED_DIR / "contacts-merged.parquet"
    if not contacts_file.exists():
        log.error("contacts-merged.parquet not found")
        return []

    log.info("Loading contacts...")
    df = pd.read_parquet(contacts_file)
    log.info("Loaded %d contacts", len(df))


    df["_name_norm"] = df["name"].apply(normalize_name)
    df["_domain"] = df["email"].apply(extract_domain)
    df["_org_norm"] = df["organization"].fillna("").str.strip().str.lower()
    df["_name_words"] = df["_name_norm"].str.split().str.len().fillna(0).astype(int)


    candidates = df[
        (df["_name_words"] >= MIN_NAME_WORDS) & (df["_name_norm"].str.len() >= MIN_NAME_LEN)
    ].copy()
    log.info("Candidates for matching: %d (filtered from %d)", len(candidates), len(df))

    suggestions: list[dict] = []
    seen_pairs: set[tuple] = set()


    single_source = candidates[candidates["source_count"] == 1]
    multi_source = candidates[candidates["source_count"] > 1]
    log.info(
        "Strategy 1: %d single-source vs %d multi-source contacts",
        len(single_source),
        len(multi_source),
    )

    for _, s_row in single_source.iterrows():
        s_name = s_row["_name_norm"]
        s_pid = str(s_row.get("person_id", ""))
        if not s_name or not s_pid:
            continue

        for _, m_row in multi_source.iterrows():
            m_name = m_row["_name_norm"]
            m_pid = str(m_row.get("person_id", ""))
            if not m_name or not m_pid or s_pid == m_pid:
                continue

            pair = tuple(sorted([s_pid, m_pid]))
            if pair in seen_pairs:
                continue

            score = fuzz.token_sort_ratio(s_name, m_name)
            if score >= 80:
                seen_pairs.add(pair)
                suggestions.append(
                    {
                        "person_id_a": s_pid,
                        "person_id_b": m_pid,
                        "name_a": str(s_row.get("name", "")),
                        "name_b": str(m_row.get("name", "")),
                        "email_a": str(s_row.get("email", "")),
                        "email_b": str(m_row.get("email", "")),
                        "org_a": str(s_row.get("organization", "")),
                        "org_b": str(m_row.get("organization", "")),
                        "score": score,
                        "reasons": ["fuzzy_name_match"],
                        "strategy": "single_source_fuzzy",
                    }
                )

    log.info("Strategy 1: %d suggestions", len(suggestions))
    s1_count = len(suggestions)


    domains = candidates.groupby("_domain").filter(lambda x: len(x) >= 2)
    if not domains.empty:
        for domain, group in domains.groupby("_domain"):
            if not domain or domain in (
                "gmail.com",
                "yahoo.com",
                "hotmail.com",
                "outlook.com",
                "icloud.com",
            ):
                continue
            names = group[["person_id", "_name_norm", "name", "email", "organization"]].to_dict(
                "records"
            )
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pid_a = str(names[i]["person_id"])
                    pid_b = str(names[j]["person_id"])
                    pair = tuple(sorted([pid_a, pid_b]))
                    if pair in seen_pairs:
                        continue
                    name_a = names[i]["_name_norm"]
                    name_b = names[j]["_name_norm"]
                    if not name_a or not name_b:
                        continue
                    score = fuzz.token_sort_ratio(name_a, name_b)
                    if score >= min_score:
                        seen_pairs.add(pair)
                        suggestions.append(
                            {
                                "person_id_a": pid_a,
                                "person_id_b": pid_b,
                                "name_a": str(names[i]["name"]),
                                "name_b": str(names[j]["name"]),
                                "email_a": str(names[i]["email"]),
                                "email_b": str(names[j]["email"]),
                                "org_a": str(names[i].get("organization", "")),
                                "org_b": str(names[j].get("organization", "")),
                                "score": score,
                                "reasons": [f"same_domain:{domain}", "fuzzy_name_match"],
                                "strategy": "same_domain",
                            }
                        )

    log.info("Strategy 2: %d new suggestions", len(suggestions) - s1_count)
    s2_count = len(suggestions)


    orgs = (
        candidates[candidates["_org_norm"] != ""].groupby("_org_norm").filter(lambda x: len(x) >= 2)
    )
    if not orgs.empty:
        for org, group in orgs.groupby("_org_norm"):
            if not org or len(org) < 3:
                continue
            names = group[["person_id", "_name_norm", "name", "email", "organization"]].to_dict(
                "records"
            )
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pid_a = str(names[i]["person_id"])
                    pid_b = str(names[j]["person_id"])
                    pair = tuple(sorted([pid_a, pid_b]))
                    if pair in seen_pairs:
                        continue
                    name_a = names[i]["_name_norm"]
                    name_b = names[j]["_name_norm"]
                    if not name_a or not name_b:
                        continue
                    score = fuzz.token_sort_ratio(name_a, name_b)
                    if score >= 70:
                        seen_pairs.add(pair)
                        suggestions.append(
                            {
                                "person_id_a": pid_a,
                                "person_id_b": pid_b,
                                "name_a": str(names[i]["name"]),
                                "name_b": str(names[j]["name"]),
                                "email_a": str(names[i]["email"]),
                                "email_b": str(names[j]["email"]),
                                "org_a": str(names[i].get("organization", "")),
                                "org_b": str(names[j].get("organization", "")),
                                "score": score,
                                "reasons": [f"same_org:{org}", "fuzzy_name_match"],
                                "strategy": "same_org",
                            }
                        )

    log.info("Strategy 3: %d new suggestions", len(suggestions) - s2_count)


    suggestions.sort(key=lambda s: s["score"], reverse=True)

    log.info("Total suggestions: %d", len(suggestions))

    if not dry_run:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps(suggestions, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("Written to %s", OUTPUT_FILE)

    return suggestions


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-merge-suggest", source="l2-merge-suggest", stage="l2")
def _pipeline_run():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SBK Merge Suggestion Generator")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output file")
    parser.add_argument(
        "--min-score", type=int, default=75, help="Minimum fuzzy score (default 75)"
    )
    args = parser.parse_args()

    start = time.time()
    results = run(dry_run=args.dry_run, min_score=args.min_score)
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Total suggestions: {len(results)}")
    if results:
        by_strategy = {}
        for s in results:
            by_strategy[s["strategy"]] = by_strategy.get(s["strategy"], 0) + 1
        for strat, count in sorted(by_strategy.items()):
            print(f"  {strat}: {count}")
        print("\nTop 5:")
        for s in results[:5]:
            print(f"  [{s['score']}] {s['name_a']} <-> {s['name_b']} ({', '.join(s['reasons'])})")


if __name__ == "__main__":
    _pipeline_run()
