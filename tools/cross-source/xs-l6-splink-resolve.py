#!/usr/bin/env python3
"""Probabilistic entity resolution with Splink over the people universe: trains a model on names, emails, phones
and companies, clusters the records and writes the merge suggestions (auto-merge only above 0.95).
"""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from jellyfish import metaphone as _metaphone



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from name_variants import NameEquivalenceDB  # noqa: E402

from sbk_config import DATA_ROOT, ENRICHED_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("splink-resolve")

PEOPLE_UNIVERSE = ENRICHED_DIR / "people-universe.parquet"
CLUSTERS_OUT = ENRICHED_DIR / "entity-clusters-splink.json"
SUGGESTIONS_OUT = ENRICHED_DIR / "merge-suggestions-splink.json"
MODEL_OUT = ENRICHED_DIR / "splink-model.json"

AUTO_MERGE_THRESHOLD = 0.95
REVIEW_THRESHOLD = 0.75



_ORG_PATTERN = re.compile(
    r"\b("
    r"s\.r\.l|s\.p\.a|srl|spa|sagl|gmbh|ltd|inc|corp|llc|ag|plc|"
    r"team|group|holding|partners|capital|ventures|fund|foundation|"
    r"university|studio|agency|consulting|association|committee|"
    r"department|division|board|council|commission"
    r")\b",
    re.IGNORECASE,
)

_CONCEPT_PATTERN = re.compile(
    r"^(the |a |an )?"
    r"(clients?|users?|customers?|employees?|members?|vendors?|"
    r"overspending|underspending|direction|direzione|"
    r"budget|revenue|cost|expense|market|industry|sector)s?\b",
    re.IGNORECASE,
)


def is_likely_person(row: pd.Series) -> bool:
    ""
    name = str(row.get("canonical_name", "")).strip()
    if not name or len(name) < 2:
        return False
    if _ORG_PATTERN.search(name):
        return False
    if _CONCEPT_PATTERN.match(name):
        return False

    parts = name.split()
    if len(parts) == 1 and len(name) <= 2:
        return False

    if "," in name and len(parts) > 3:
        return False
    return True





def safe_metaphone(s: str) -> str | None:
    ""
    if not s or len(s) < 2:
        return None
    try:
        return _metaphone(s)
    except Exception:
        return None


def split_name(name: str) -> tuple[str, str]:
    ""
    parts = name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def extract_primary_email(emails_str: str) -> str | None:
    ""
    if not emails_str or pd.isna(emails_str) or not emails_str.strip():
        return None
    for sep in ["|", ",", ";"]:
        if sep in emails_str:
            e = emails_str.split(sep)[0].strip().lower()
            return e if "@" in e else None
    e = emails_str.strip().lower()
    return e if "@" in e else None


def extract_company(context: str) -> str | None:
    ""
    if not context or pd.isna(context):
        return None

    skip = {
        "participant",
        "speaker",
        "subject in relationship facts",
        "object in relationship facts",
    }



    parts = context.split("|")
    for part in parts:
        part = part.strip()
        if part.lower() in skip:
            continue

        if "," in part:
            segments = [s.strip() for s in part.split(",")]
            if len(segments) >= 2:
                company = segments[-1].strip()
                if company.lower() not in skip and len(company) > 2:
                    return company.lower()

        elif len(part) > 2 and part.lower() not in skip:
            return part.lower()
    return None


def _load_phone_lookup() -> dict[str, str]:
    ""
    phones: dict[str, str] = {}
    iphone_path = DATA_ROOT / "contacts" / "processed" / "contacts-iphone.parquet"
    if iphone_path.exists():
        df = pd.read_parquet(iphone_path)
        for _, row in df.iterrows():
            name = str(row.get("name_normalized") or row.get("name", "")).strip().lower()
            phone = str(row.get("phone_primary", "")).strip()
            if name and phone and len(phone) >= 7:
                phones[name] = phone
    log.info(f"Phone lookup: {len(phones)} entries from iPhone contacts")
    return phones


def prepare_splink_frame(df: pd.DataFrame, nickname_db: NameEquivalenceDB) -> pd.DataFrame:
    ""
    mask = df.apply(is_likely_person, axis=1)
    sdf = df[mask].copy().reset_index(drop=True)
    log.info(f"Filtered to {len(sdf)} likely-person entries (from {len(df)} total)")


    sdf["unique_id"] = range(len(sdf))


    name_parts = sdf["canonical_name"].apply(split_name)
    sdf["first_name"] = name_parts.apply(lambda x: x[0])
    sdf["surname"] = name_parts.apply(lambda x: x[1])


    sdf["first_name_normalized"] = sdf["first_name"].str.lower().str.strip()
    sdf["surname_normalized"] = sdf["surname"].str.lower().str.strip()


    sdf["email"] = sdf["emails"].apply(extract_primary_email)
    sdf["email_username"] = sdf["email"].apply(
        lambda e: e.split("@")[0] if isinstance(e, str) and "@" in e else None
    )


    sdf["company_normalized"] = sdf["context"].apply(extract_company)


    phone_lookup = _load_phone_lookup()
    sdf["phone"] = sdf["canonical_name"].str.lower().str.strip().map(phone_lookup)
    sdf["phone_last7"] = sdf["phone"].apply(
        lambda p: p[-7:] if isinstance(p, str) and len(p) >= 7 else None
    )


    sdf["first_name_metaphone"] = sdf["first_name_normalized"].apply(safe_metaphone)
    sdf["surname_metaphone"] = sdf["surname_normalized"].apply(safe_metaphone)
    sdf["first_name_2char"] = sdf["first_name_normalized"].apply(
        lambda n: n[:2] if n and len(n) >= 2 else None
    )
    sdf["surname_2char"] = sdf["surname_normalized"].apply(
        lambda n: n[:2] if n and len(n) >= 2 else None
    )
    sdf["surname_first_char"] = sdf["surname_normalized"].apply(lambda n: n[:1] if n else None)


    sdf["nickname_cluster_id"] = sdf["first_name_normalized"].apply(
        lambda n: nickname_db.get_canonical(n) or n if n else None
    )


    has_email = sdf["email"].notna().sum()
    has_company = sdf["company_normalized"].notna().sum()
    has_surname = (sdf["surname_normalized"].str.len() > 0).sum()
    has_phone = sdf["phone"].notna().sum()
    log.info(
        f"  With email: {has_email}, with company: {has_company}, "
        f"with surname: {has_surname}, with phone: {has_phone}"
    )

    return sdf





def build_splink_settings():
    ""
    import splink.comparison_level_library as cll
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[

            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("email"),
                    cll.ExactMatchLevel("email"),
                    cll.ExactMatchLevel("email_username"),
                    cll.ElseLevel(),
                ],
                output_column_name="email",
            ),

            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("first_name_normalized"),
                    cll.ExactMatchLevel("first_name_normalized"),
                    cll.ExactMatchLevel("nickname_cluster_id"),
                    cll.JaroWinklerLevel("first_name_normalized", 0.92),
                    cll.JaroWinklerLevel("first_name_normalized", 0.80),
                    cll.ElseLevel(),
                ],
                output_column_name="first_name",
            ),

            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("surname_normalized"),
                    cll.ExactMatchLevel("surname_normalized"),
                    cll.JaroWinklerLevel("surname_normalized", 0.92),
                    cll.JaroWinklerLevel("surname_normalized", 0.80),
                    cll.ElseLevel(),
                ],
                output_column_name="surname",
            ),

            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("company_normalized"),
                    cll.ExactMatchLevel("company_normalized"),
                    cll.ElseLevel(),
                ],
                output_column_name="company",
            ),

            cl.CustomComparison(
                comparison_levels=[
                    cll.NullLevel("phone"),
                    cll.ExactMatchLevel("phone"),
                    cll.ExactMatchLevel("phone_last7"),
                    cll.ElseLevel(),
                ],
                output_column_name="phone",
            ),
        ],
        blocking_rules_to_generate_predictions=[

            block_on("email"),
            block_on("email_username"),
            block_on("phone_last7"),
            block_on("surname_metaphone", "first_name_2char"),
            block_on("first_name_metaphone", "surname_2char"),
            block_on("nickname_cluster_id", "surname_first_char"),
        ],
    )
    return settings





def train_model(linker):
    ""
    from splink import block_on


    log.info("Estimating u-parameters (random sampling)...")
    linker.training.estimate_u_using_random_sampling(max_pairs=5e6)


    log.info("EM training on surname_metaphone blocks...")
    try:
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("surname_metaphone"),
            fix_u_probabilities=True,
        )
    except Exception as e:
        log.warning(f"EM on surname_metaphone failed: {e}")


    log.info("EM training on first_name_metaphone blocks...")
    try:
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("first_name_metaphone"),
            fix_u_probabilities=True,
        )
    except Exception as e:
        log.warning(f"EM on first_name_metaphone failed: {e}")


    log.info("EM training on email_username blocks...")
    try:
        linker.training.estimate_parameters_using_expectation_maximisation(
            block_on("email_username"),
            fix_u_probabilities=True,
        )
    except Exception as e:
        log.warning(f"EM on email_username failed (expected if few shared usernames): {e}")

    log.info("Training complete")





def classify_predictions(predictions_df: pd.DataFrame):
    ""
    auto_merge = predictions_df[predictions_df["match_probability"] >= AUTO_MERGE_THRESHOLD].copy()
    review = predictions_df[
        (predictions_df["match_probability"] >= REVIEW_THRESHOLD)
        & (predictions_df["match_probability"] < AUTO_MERGE_THRESHOLD)
    ].copy()
    reject = predictions_df[predictions_df["match_probability"] < REVIEW_THRESHOLD].copy()

    log.info(
        f"Three-band: {len(auto_merge)} auto-merge, {len(review)} review, {len(reject)} reject"
    )
    return auto_merge, review, reject


def apply_name_only_guard(
    auto_merge_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ""




    if auto_merge_df.empty:
        return auto_merge_df, pd.DataFrame()



    email_col = [c for c in auto_merge_df.columns if c.startswith("gamma_email")]
    company_col = [c for c in auto_merge_df.columns if c.startswith("gamma_company")]
    phone_col = [c for c in auto_merge_df.columns if c.startswith("gamma_phone")]

    if not email_col or not company_col:

        return auto_merge_df, pd.DataFrame()

    email_gamma = email_col[0]
    company_gamma = company_col[0]




    no_email = auto_merge_df[email_gamma] <= 0
    no_company = auto_merge_df[company_gamma] <= 0
    if phone_col:
        no_phone = auto_merge_df[phone_col[0]] <= 0
        name_only_mask = no_email & no_company & no_phone
    else:
        name_only_mask = no_email & no_company

    downgraded = auto_merge_df[name_only_mask].copy()
    kept = auto_merge_df[~name_only_mask].copy()

    if len(downgraded) > 0:
        log.info(f"Name-only guard: downgraded {len(downgraded)} auto-merge → review")

    return kept, downgraded





def build_clusters(auto_merge_df: pd.DataFrame, sdf: pd.DataFrame) -> dict:
    ""
    if auto_merge_df.empty:
        return {"clusters": {}, "metadata": _metadata(sdf, 0, 0, 0)}


    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb


    uid_to_pid = dict(zip(sdf["unique_id"], sdf["person_id"]))
    uid_to_name = dict(zip(sdf["unique_id"], sdf["canonical_name"]))

    for _, row in auto_merge_df.iterrows():
        uid_l = row["unique_id_l"]
        uid_r = row["unique_id_r"]
        union(uid_l, uid_r)


    from collections import defaultdict

    cluster_groups = defaultdict(list)
    all_uids = set(auto_merge_df["unique_id_l"]) | set(auto_merge_df["unique_id_r"])
    for uid in all_uids:
        root = find(uid)
        cluster_groups[root].append(uid)

    clusters = {}
    for i, (root, members) in enumerate(sorted(cluster_groups.items(), key=lambda x: -len(x[1]))):
        canonical_id = uid_to_pid.get(members[0], f"unknown_{members[0]}")
        cluster_id = f"splink_cluster_{i:04d}"


        member_info = []
        for uid in members:
            pid = uid_to_pid.get(uid, f"unknown_{uid}")
            name = uid_to_name.get(uid, "?")

            mask = (auto_merge_df["unique_id_l"] == uid) | (auto_merge_df["unique_id_r"] == uid)
            best_prob = auto_merge_df.loc[mask, "match_probability"].max() if mask.any() else 0.0
            member_info.append(
                {
                    "person_id": pid,
                    "name": name,
                    "confidence": round(float(best_prob), 4),
                    "method": "splink_auto",
                }
            )

        clusters[cluster_id] = {
            "canonical_id": canonical_id,
            "members": member_info,
            "size": len(members),
        }

    return clusters


def build_suggestions(review_df: pd.DataFrame, sdf: pd.DataFrame) -> list[dict]:
    ""
    if review_df.empty:
        return []

    uid_to_pid = dict(zip(sdf["unique_id"], sdf["person_id"]))
    uid_to_name = dict(zip(sdf["unique_id"], sdf["canonical_name"]))


    gamma_cols = [c for c in review_df.columns if c.startswith("gamma_")]
    bf_cols = [c for c in review_df.columns if c.startswith("bf_")]

    suggestions = []
    for _, row in review_df.iterrows():
        uid_l = row["unique_id_l"]
        uid_r = row["unique_id_r"]

        field_scores = {}
        for gc in gamma_cols:
            field_name = gc.replace("gamma_", "")
            bf_col = f"bf_{field_name}"
            gamma_val = int(row[gc]) if pd.notna(row[gc]) else -1
            bf_val = (
                float(row[bf_col]) if bf_col in row.index and pd.notna(row.get(bf_col)) else 0.0
            )
            field_scores[field_name] = {
                "gamma": gamma_val,
                "bayes_factor": round(bf_val, 4),
            }

        suggestions.append(
            {
                "id_left": uid_to_pid.get(uid_l, f"unknown_{uid_l}"),
                "id_right": uid_to_pid.get(uid_r, f"unknown_{uid_r}"),
                "names": [
                    uid_to_name.get(uid_l, "?"),
                    uid_to_name.get(uid_r, "?"),
                ],
                "match_probability": round(float(row["match_probability"]), 4),
                "match_weight": round(float(row["match_weight"]), 4),
                "field_scores": field_scores,
                "recommendation": "review",
            }
        )


    suggestions.sort(key=lambda x: -x["match_probability"])
    return suggestions


def _metadata(sdf, auto_count, review_count, reject_count):
    return {
        "total_records": len(sdf),
        "auto_merged": auto_count,
        "review_queue": review_count,
        "rejected": reject_count,
        "timestamp": datetime.now().isoformat(),
        "thresholds": {
            "auto_merge": AUTO_MERGE_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
    }





def run_splink(dry_run: bool = False, score_only: bool = False):
    ""
    from splink import DuckDBAPI, Linker

    if not PEOPLE_UNIVERSE.exists():
        log.error(f"Input not found: {PEOPLE_UNIVERSE}")
        return


    log.info(f"Loading {PEOPLE_UNIVERSE}")
    df = pd.read_parquet(PEOPLE_UNIVERSE)
    log.info(f"Loaded {len(df)} records")


    learned_path = DATA_ROOT / "learned-name-variants.json"
    nickname_db = NameEquivalenceDB(learned_path=learned_path)
    log.info(f"NameEquivalenceDB: {len(nickname_db._clusters)} clusters")


    sdf = prepare_splink_frame(df, nickname_db)

    if len(sdf) < 10:
        log.error(f"Too few records after filtering ({len(sdf)}). Aborting.")
        return


    splink_cols = [
        "unique_id",
        "first_name_normalized",
        "surname_normalized",
        "email",
        "email_username",
        "company_normalized",
        "nickname_cluster_id",
        "surname_metaphone",
        "first_name_metaphone",
        "first_name_2char",
        "surname_2char",
        "surname_first_char",
    ]
    splink_df = sdf[splink_cols].copy()


    db_api = DuckDBAPI()
    splink_sdf = db_api.register(splink_df, "people_universe")
    log.info("Registered DataFrame with DuckDB")


    settings = build_splink_settings()


    linker = Linker(splink_sdf, settings)
    log.info("Linker created")


    for i, rule in enumerate(settings.blocking_rules_to_generate_predictions):
        try:
            count = linker.count_num_comparisons_from_blocking_rule(str(rule))
            log.info(f"  Blocking rule {i}: {count:,} pairs — {rule}")
        except Exception:
            log.info(f"  Blocking rule {i}: (count unavailable) — {rule}")


    train_model(linker)


    if not dry_run:
        linker.save_model_to_json(str(MODEL_OUT))
        log.info(f"Model saved → {MODEL_OUT}")


    log.info("Running predictions...")
    predictions = linker.inference.predict(threshold_match_probability=REVIEW_THRESHOLD)
    pred_df = predictions.as_pandas_dataframe()
    log.info(f"Predictions: {len(pred_df)} pairs above {REVIEW_THRESHOLD}")

    if pred_df.empty:
        log.info("No matches found above threshold.")
        if not dry_run:
            _write_empty_output(sdf)
        return


    auto_merge, review, reject = classify_predictions(pred_df)


    auto_merge, guard_downgraded = apply_name_only_guard(auto_merge)
    review = pd.concat([review, guard_downgraded], ignore_index=True)

    if score_only:
        log.info("\n── Score-only mode: top 20 predictions ──")
        top = pred_df.nlargest(20, "match_probability")
        uid_to_name = dict(zip(sdf["unique_id"], sdf["canonical_name"]))
        for _, row in top.iterrows():
            name_l = uid_to_name.get(row["unique_id_l"], "?")
            name_r = uid_to_name.get(row["unique_id_r"], "?")
            log.info(
                f"  {name_l} ↔ {name_r}: "
                f"prob={row['match_probability']:.4f} weight={row['match_weight']:.2f}"
            )
        return


    clusters = build_clusters(auto_merge, sdf)
    suggestions = build_suggestions(review, sdf)


    metadata = _metadata(sdf, len(auto_merge), len(review), len(reject))
    output = {"clusters": clusters, "metadata": metadata}

    log.info("\n=== Splink Resolution Summary ===")
    log.info(f"Input records: {len(sdf)}")
    log.info(f"Predictions above {REVIEW_THRESHOLD}: {len(pred_df)}")
    log.info(f"Auto-merge: {len(auto_merge)} pairs → {len(clusters)} clusters")
    log.info(f"Review: {len(suggestions)} pairs")
    log.info(f"Rejected: {len(reject)} pairs")

    if dry_run:
        log.info("\n── Dry run: would write ──")
        log.info(f"  {CLUSTERS_OUT}: {len(clusters)} clusters")
        log.info(f"  {SUGGESTIONS_OUT}: {len(suggestions)} suggestions")

        uid_to_name = dict(zip(sdf["unique_id"], sdf["canonical_name"]))
        if clusters:
            log.info("\n── Top 10 auto-merge clusters ──")
            for cid, cinfo in list(clusters.items())[:10]:
                names = [m["name"] for m in cinfo["members"]]
                log.info(f"  {cid}: {names}")

        if suggestions:
            log.info("\n── Top 10 review suggestions ──")
            for s in suggestions[:10]:
                log.info(f"  {s['names'][0]} ↔ {s['names'][1]}: prob={s['match_probability']:.4f}")
        return


    safe_write_json(CLUSTERS_OUT, output)
    log.info(f"Saved clusters → {CLUSTERS_OUT}")

    safe_write_json(SUGGESTIONS_OUT, suggestions)
    log.info(f"Saved suggestions → {SUGGESTIONS_OUT}")


def _write_empty_output(sdf):
    ""
    metadata = _metadata(sdf, 0, 0, 0)
    output = {"clusters": {}, "metadata": metadata}
    safe_write_json(CLUSTERS_OUT, output)
    safe_write_json(SUGGESTIONS_OUT, [])
    log.info("Wrote empty output files (no matches)")


def main():
    parser = argparse.ArgumentParser(
        description="EQ-03 — Splink Layer 7: Probabilistic Entity Resolution"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show results without writing files",
    )
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="Only show top predictions, don't classify or write",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    run_splink(dry_run=args.dry_run, score_only=args.score_only)


if __name__ == "__main__":
    main()
