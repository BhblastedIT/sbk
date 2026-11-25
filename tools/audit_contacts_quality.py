""














from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parent))

from sbk_config import DATA_ROOT  # noqa: E402

MERGED_FILE = DATA_ROOT / "enriched" / "contacts-merged.parquet"
IPHONE_FILE = DATA_ROOT / "contacts" / "processed" / "contacts-iphone.parquet"
ENTITY_MAP_FILE = DATA_ROOT / "enriched" / "entity-map.json"




def load_data():
    print("=" * 80)
    print("SBK CONTACT DATA QUALITY AUDIT")
    print("=" * 80)

    merged = pd.read_parquet(MERGED_FILE)
    print(f"\nLoaded contacts-merged.parquet: {len(merged)} rows, {len(merged.columns)} columns")

    iphone = None
    if IPHONE_FILE.exists():
        iphone = pd.read_parquet(IPHONE_FILE)
        print(f"Loaded contacts-iphone.parquet: {len(iphone)} rows")
    else:
        print("contacts-iphone.parquet: NOT FOUND")

    entity_map = {}
    if ENTITY_MAP_FILE.exists():
        with open(ENTITY_MAP_FILE) as f:
            entity_map = json.load(f)
        print(f"Loaded entity-map.json: {len(entity_map)} entries")
    else:
        print("entity-map.json: NOT FOUND")

    return merged, iphone, entity_map





def audit_dates(df: pd.DataFrame):
    print("\n" + "=" * 80)
    print("1. DATE VALIDATION")
    print("=" * 80)

    date_cols = [c for c in df.columns if df[c].dtype.kind == "M"]
    print(f"\nDatetime columns found: {date_cols}")

    issues_found = 0

    for col in date_cols:
        non_null_mask = df[col].notna()
        series = df.loc[non_null_mask, col]
        if series.empty:
            continue


        future_cutoff = pd.Timestamp.now(tz="UTC")
        future_mask = non_null_mask & (df[col] > future_cutoff)
        future = df[future_mask]
        if len(future) > 0:
            print(f"\n  [{col}] FUTURE DATES (after now): {len(future)} records")
            for _, row in future.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row.get('name', '?')}, {col}={row[col]}"
                )
            issues_found += len(future)


        old_cutoff = pd.Timestamp("1990-01-01", tz="UTC")
        if "first" in col or "last" in col:
            old_mask = non_null_mask & (df[col] < old_cutoff)
            old = df[old_mask]
            if len(old) > 0:
                print(f"\n  [{col}] SUSPICIOUSLY OLD DATES (before 1990): {len(old)} records")
                for _, row in old.iterrows():
                    print(
                        f"    person_id={row['person_id']}, name={row.get('name', '?')}, {col}={row[col]}"
                    )
                issues_found += len(old)


        epoch_start = pd.Timestamp("1969-12-31", tz="UTC")
        epoch_end = pd.Timestamp("1970-01-02", tz="UTC")
        epoch_mask = non_null_mask & (df[col] >= epoch_start) & (df[col] <= epoch_end)
        epoch = df[epoch_mask]
        if len(epoch) > 0:
            print(f"\n  [{col}] UNIX EPOCH DATES (1970-01-01 +/- 1 day): {len(epoch)} records")
            for _, row in epoch.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row.get('name', '?')}, {col}={row[col]}"
                )
            issues_found += len(epoch)


    if "org_last_verified" in df.columns:
        series = df["org_last_verified"].dropna()

        if len(series) > 0:
            unique_dates = series.dt.date.nunique()
            if unique_dates <= 3:
                print(
                    f"\n  [org_last_verified] Only {unique_dates} unique dates — possibly bulk-set:"
                )
                for d, cnt in series.dt.date.value_counts().items():
                    print(f"    {d}: {cnt} records")

    if issues_found == 0:
        print("\n  No date issues found.")
    else:
        print(f"\n  TOTAL DATE ISSUES: {issues_found}")





def audit_phones(df: pd.DataFrame, iphone: pd.DataFrame | None):
    print("\n" + "=" * 80)
    print("2. PHONE NUMBER VALIDATION")
    print("=" * 80)


    phone_col = "phone_primary"
    if phone_col not in df.columns:
        print(f"\n  Column '{phone_col}' not found in merged contacts.")
        return

    phones = df[[phone_col, "person_id", "name"]].dropna(subset=[phone_col])
    phones = phones[phones[phone_col].str.strip() != ""]
    print(f"\n  Contacts with phone_primary: {len(phones)} / {len(df)}")


    phone_to_persons = defaultdict(list)
    for _, row in phones.iterrows():
        phone_to_persons[row[phone_col].strip()].append((row["person_id"], row.get("name", "?")))

    dups = {k: v for k, v in phone_to_persons.items() if len(v) > 1}
    if dups:
        print(f"\n  DUPLICATE PHONE NUMBERS (same phone, different person_ids): {len(dups)}")
        for phone, persons in sorted(dups.items()):
            print(f"    Phone: {phone}")
            for pid, name in persons:
                print(f"      -> person_id={pid}, name={name}")
    else:
        print("\n  No duplicate phone numbers found in merged contacts.")


    malformed = []
    too_short = []
    too_long = []
    for _, row in phones.iterrows():
        p = row[phone_col].strip()

        digits_only = re.sub(r"[^\d]", "", p)


        if len(digits_only) < 7:
            too_short.append((row["person_id"], row.get("name", "?"), p))


        if len(digits_only) > 15:
            too_long.append((row["person_id"], row.get("name", "?"), p))


        if re.search(r"[a-zA-Z]", p):
            malformed.append((row["person_id"], row.get("name", "?"), p))

    if malformed:
        print(f"\n  MALFORMED PHONE NUMBERS (contains letters): {len(malformed)}")
        for pid, name, phone in malformed:
            print(f"    person_id={pid}, name={name}, phone={phone}")

    if too_short:
        print(f"\n  TOO SHORT PHONE NUMBERS (<7 digits): {len(too_short)}")
        for pid, name, phone in too_short:
            print(f"    person_id={pid}, name={name}, phone={phone}")

    if too_long:
        print(f"\n  TOO LONG PHONE NUMBERS (>15 digits): {len(too_long)}")
        for pid, name, phone in too_long:
            print(f"    person_id={pid}, name={name}, phone={phone}")


    if iphone is not None and "phone_numbers" in iphone.columns:
        print("\n  --- iPhone Contacts Phone Analysis ---")
        iphone_phone_map = defaultdict(list)
        for _, row in iphone.iterrows():
            pns = row.get("phone_numbers")
            if pns is None:
                continue

            try:
                phone_list = list(pns)
            except Exception:
                phone_list = [str(pns)]
            for p in phone_list:
                if p and str(p).strip():
                    iphone_phone_map[str(p).strip()].append(row.get("name", "?"))

        iphone_dups = {k: v for k, v in iphone_phone_map.items() if len(v) > 1}
        if iphone_dups:
            print(
                f"  iPhone DUPLICATE PHONES (same number, different contacts): {len(iphone_dups)}"
            )
            for phone, names in sorted(iphone_dups.items()):
                print(f"    Phone: {phone} -> {names}")
        else:
            print("  No duplicate phones in iPhone contacts.")

    if not malformed and not too_short and not too_long and not dups:
        print("\n  No phone issues found.")





def audit_scores(df: pd.DataFrame):
    print("\n" + "=" * 80)
    print("3. SCORE ANOMALIES")
    print("=" * 80)

    if "score" not in df.columns:
        print("\n  Column 'score' not found.")
        return


    interaction_cols = [
        "email_total_msgs",
        "cal_events",
        "plaud_meetings",
        "tactiq_meetings",
        "linkedin_messages",
        "slack_messages",
        "whatsapp_messages",
        "docusign_contracts",
        "notion_mentions",
        "chatgpt_mentions",
    ]
    existing_cols = [c for c in interaction_cols if c in df.columns]
    df_work = df.copy()
    df_work["_total_interactions"] = df_work[existing_cols].fillna(0).sum(axis=1)


    zero_score_high = df_work[(df_work["score"] == 0) & (df_work["_total_interactions"] >= 10)]
    if len(zero_score_high) > 0:
        print(f"\n  SCORE=0 but >=10 total interactions: {len(zero_score_high)} records")
        for _, row in zero_score_high.sort_values(
            "_total_interactions", ascending=False
        ).iterrows():
            print(
                f"    person_id={row['person_id']}, name={row.get('name', '?')}, "
                f"score={row['score']}, interactions={int(row['_total_interactions'])}, "
                f"sources={row.get('source_count', '?')}"
            )
    else:
        print("\n  No score=0 contacts with >=10 interactions.")


    high_score_zero = df_work[(df_work["score"] > 90) & (df_work["_total_interactions"] == 0)]
    if len(high_score_zero) > 0:
        print(f"\n  SCORE>90 but 0 interactions: {len(high_score_zero)} records")
        for _, row in high_score_zero.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row.get('name', '?')}, "
                f"score={row['score']}, sources={row.get('source_count', '?')}"
            )
    else:
        print("\n  No score>90 contacts with 0 interactions.")


    high_score_low = df_work[
        (df_work["score"] > 90)
        & (df_work["_total_interactions"] > 0)
        & (df_work["_total_interactions"] <= 5)
    ]
    if len(high_score_low) > 0:
        print(f"\n  SCORE>90 but only 1-5 interactions: {len(high_score_low)} records")
        for _, row in high_score_low.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row.get('name', '?')}, "
                f"score={row['score']}, interactions={int(row['_total_interactions'])}, "
                f"sources={row.get('source_count', '?')}"
            )


    nan_scores = df_work[df_work["score"].isna()]
    if len(nan_scores) > 0:
        print(f"\n  NULL/NaN SCORES: {len(nan_scores)} records")
        for _, row in nan_scores.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row.get('name', '?')}, "
                f"interactions={int(row['_total_interactions'])}, sources={row.get('source_count', '?')}"
            )


    neg_scores = df_work[df_work["score"] < 0]
    if len(neg_scores) > 0:
        print(f"\n  NEGATIVE SCORES: {len(neg_scores)} records")
        for _, row in neg_scores.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row.get('name', '?')}, "
                f"score={row['score']}"
            )


    print("\n  Score distribution:")
    print(f"    Min: {df_work['score'].min():.1f}")
    print(f"    Max: {df_work['score'].max():.1f}")
    print(f"    Mean: {df_work['score'].mean():.1f}")
    print(f"    Median: {df_work['score'].median():.1f}")
    print(f"    Std: {df_work['score'].std():.1f}")
    print(f"    NaN count: {df_work['score'].isna().sum()}")
    bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    hist = pd.cut(df_work["score"].dropna(), bins=bins, right=True).value_counts().sort_index()
    for bucket, count in hist.items():
        print(f"    {bucket}: {count}")





def audit_names(df: pd.DataFrame):
    print("\n" + "=" * 80)
    print("4. NAME ISSUES")
    print("=" * 80)


    no_name = df[df["name"].isna() | (df["name"].str.strip() == "")]
    if len(no_name) > 0:
        print(f"\n  NO NAME (empty or NaN): {len(no_name)} records")
        for _, row in no_name.iterrows():
            print(
                f"    person_id={row['person_id']}, email={row.get('email', '?')}, "
                f"score={row.get('score', '?')}, sources={row.get('source_count', '?')}"
            )
    else:
        print("\n  All contacts have a name.")


    at_in_name = df[df["name"].fillna("").str.contains("@", regex=False)]
    if len(at_in_name) > 0:
        print(f"\n  NAME CONTAINS '@' (email as name): {len(at_in_name)} records")
        for _, row in at_in_name.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"email={row.get('email', '?')}, score={row.get('score', '?')}"
            )
    else:
        print("\n  No names containing '@'.")


    name_eq_email = df[
        df["name"].fillna("").str.strip().str.lower()
        == df["email"].fillna("").str.strip().str.lower()
    ]

    name_eq_email = name_eq_email[name_eq_email["name"].fillna("").str.strip() != ""]
    if len(name_eq_email) > 0:
        print(f"\n  NAME = EMAIL (name is just the email address): {len(name_eq_email)} records")
        for _, row in name_eq_email.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"score={row.get('score', '?')}"
            )


    single_char = df[df["name"].fillna("").str.strip().str.len() == 1]
    if len(single_char) > 0:
        print(f"\n  SINGLE CHARACTER NAMES: {len(single_char)} records")
        for _, row in single_char.iterrows():
            print(
                f"    person_id={row['person_id']}, name='{row['name']}', "
                f"email={row.get('email', '?')}"
            )


    hash_names = df[df["name"].fillna("").str.match(r"^[A-Fa-f0-9]{8,}$")]
    if len(hash_names) > 0:
        print(f"\n  HASH/ID-LIKE NAMES: {len(hash_names)} records")
        for _, row in hash_names.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"email={row.get('email', '?')}"
            )


    digit_names = df[df["name"].fillna("").str.match(r"^\d+$")]
    if len(digit_names) > 0:
        print(f"\n  ALL-DIGIT NAMES: {len(digit_names)} records")
        for _, row in digit_names.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"email={row.get('email', '?')}"
            )


    long_names = df[df["name"].fillna("").str.len() > 60]
    if len(long_names) > 0:
        print(f"\n  VERY LONG NAMES (>60 chars): {len(long_names)} records")
        for _, row in long_names.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name'][:80]}..., "
                f"email={row.get('email', '?')}"
            )


    if "attio_name" in df.columns and "personio_name" in df.columns:
        has_both = df[
            df["attio_name"].notna()
            & df["personio_name"].notna()
            & (df["attio_name"].str.strip() != "")
            & (df["personio_name"].str.strip() != "")
        ]
        mismatched = has_both[
            has_both["attio_name"].str.strip().str.lower()
            != has_both["personio_name"].str.strip().str.lower()
        ]
        if len(mismatched) > 0:
            print(f"\n  NAME MISMATCH attio_name vs personio_name: {len(mismatched)} records")
            for _, row in mismatched.iterrows():
                print(
                    f"    person_id={row['person_id']}, canonical={row['name']}, "
                    f"attio={row['attio_name']}, personio={row['personio_name']}"
                )





def audit_organizations(df: pd.DataFrame):
    print("\n" + "=" * 80)
    print("5. ORGANIZATION ANOMALIES")
    print("=" * 80)

    if "organization" not in df.columns:
        print("\n  Column 'organization' not found.")
        return

    has_org = df[df["organization"].notna() & (df["organization"].str.strip() != "")]
    print(f"\n  Contacts with organization: {len(has_org)} / {len(df)}")


    org_eq_name = has_org[
        has_org["organization"].str.strip().str.lower()
        == has_org["name"].fillna("").str.strip().str.lower()
    ]
    if len(org_eq_name) > 0:
        print(f"\n  ORGANIZATION = PERSON NAME: {len(org_eq_name)} records")
        for _, row in org_eq_name.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"org={row['organization']}, email={row.get('email', '?')}"
            )


    org_eq_domain = has_org[
        has_org["organization"].str.strip().str.lower()
        == has_org["domain"].fillna("").str.strip().str.lower()
    ]
    if len(org_eq_domain) > 0:
        print(f"\n  ORGANIZATION = EMAIL DOMAIN: {len(org_eq_domain)} records")
        for _, row in org_eq_domain.iterrows():
            print(
                f"    person_id={row['person_id']}, name={row['name']}, "
                f"org={row['organization']}, domain={row.get('domain', '?')}"
            )


    if "attio_company" in df.columns:
        has_both = df[
            df["attio_company"].notna()
            & df["organization"].notna()
            & (df["attio_company"].str.strip() != "")
            & (df["organization"].str.strip() != "")
        ]
        mismatch = has_both[
            has_both["attio_company"].str.strip().str.lower()
            != has_both["organization"].str.strip().str.lower()
        ]
        if len(mismatch) > 0:
            print(
                f"\n  ORGANIZATION MISMATCH (attio_company vs organization): {len(mismatch)} records"
            )
            for _, row in mismatch.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row['name']}, "
                    f"attio_company={row['attio_company']}, organization={row['organization']}"
                )


    company_suffixes = {
        "srl",
        "s.r.l.",
        "spa",
        "s.p.a.",
        "ltd",
        "inc",
        "llc",
        "gmbh",
        "sarl",
        "ag",
        "co",
        "corp",
        "group",
        "holding",
        "studio",
        "consulting",
        "partners",
        "capital",
        "ventures",
        "labs",
        "lab",
        "tech",
        "technologies",
        "digital",
        "media",
        "agency",
        "solutions",
    }
    person_like_orgs = []
    for _, row in has_org.iterrows():
        org = row["organization"].strip()
        words = org.split()
        if len(words) == 2:
            all_title = all(w[0].isupper() and w[1:].islower() for w in words if len(w) > 1)
            no_suffix = not any(w.lower().rstrip(".") in company_suffixes for w in words)
            if all_title and no_suffix:

                if org.lower() != str(row.get("name", "")).lower():
                    person_like_orgs.append(row)

    if person_like_orgs:
        print(
            f"\n  ORGANIZATION LOOKS LIKE A PERSON NAME (2 titlecase words, no company suffix): {len(person_like_orgs)} records"
        )
        for row in person_like_orgs[:50]:
            print(
                f"    person_id={row['person_id']}, name={row['name']}, org={row['organization']}"
            )
        if len(person_like_orgs) > 50:
            print(f"    ... and {len(person_like_orgs) - 50} more")





def audit_duplicates(df: pd.DataFrame, entity_map: dict):
    print("\n" + "=" * 80)
    print("6. DUPLICATE CONTACTS (entity resolution misses)")
    print("=" * 80)


    has_email = df[df["email"].notna() & (df["email"].str.strip() != "")]
    email_dups = has_email.groupby("email").filter(lambda x: len(x) > 1)
    if len(email_dups) > 0:
        print(f"\n  SAME EMAIL, DIFFERENT PERSON_ID: {len(email_dups)} records")
        for email, group in email_dups.groupby("email"):
            print(f"    Email: {email}")
            for _, row in group.iterrows():
                print(
                    f"      person_id={row['person_id']}, name={row['name']}, "
                    f"score={row.get('score', '?')}"
                )
    else:
        print("\n  No duplicate primary emails found.")


    print("\n  Checking all_emails for cross-person overlap...")
    email_to_pid = defaultdict(set)
    for _, row in df.iterrows():
        pid = row["person_id"]
        all_em = row.get("all_emails")
        if all_em is None:
            continue

        if isinstance(all_em, str):
            try:
                emails = json.loads(all_em.replace("'", '"'))
            except (json.JSONDecodeError, ValueError):
                emails = [e.strip().strip("[]'\"") for e in all_em.split(",")]
        elif isinstance(all_em, list):
            emails = all_em
        else:
            continue
        for em in emails:
            em = em.strip().lower()
            if em:
                email_to_pid[em].add(pid)

    cross_overlap = {em: pids for em, pids in email_to_pid.items() if len(pids) > 1}
    if cross_overlap:
        print(
            f"\n  ALL_EMAILS OVERLAP (same email in multiple person_ids): {len(cross_overlap)} emails"
        )
        for em, pids in sorted(cross_overlap.items()):
            names = []
            for pid in pids:
                match = df[df["person_id"] == pid]
                name = match.iloc[0]["name"] if len(match) > 0 else "?"
                names.append(f"{pid}({name})")
            print(f"    {em} -> {', '.join(names)}")
    else:
        print("  No all_emails overlap found.")


    pid_dups = df[df.duplicated(subset=["person_id"], keep=False)]
    if len(pid_dups) > 0:
        print(f"\n  DUPLICATE PERSON_IDs in merged contacts: {len(pid_dups)} records")
        for pid, group in pid_dups.groupby("person_id"):
            print(f"    person_id={pid}: {len(group)} rows")
            for _, row in group.iterrows():
                print(f"      name={row['name']}, email={row.get('email', '?')}")
    else:
        print("\n  No duplicate person_ids in merged contacts.")


    name_to_pids = defaultdict(list)
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip().lower()
        if name and name != "nan":
            name_to_pids[name].append((row["person_id"], row.get("email", "?")))

    name_dups = {n: pids for n, pids in name_to_pids.items() if len(pids) > 1}
    if name_dups:
        print(f"\n  SAME EXACT NAME, DIFFERENT PERSON_ID: {len(name_dups)} names")
        for name, pids in sorted(name_dups.items()):
            print(f"    Name: '{name}'")
            for pid, email in pids:
                print(f"      person_id={pid}, email={email}")
    else:
        print("\n  No exact-name duplicates found.")





def audit_orphans(df: pd.DataFrame, entity_map: dict):
    print("\n" + "=" * 80)
    print("7. ORPHAN PERSON_IDs")
    print("=" * 80)

    merged_pids = set(df["person_id"].dropna().unique())


    em_pids = set()
    for key, val in entity_map.items():
        if isinstance(val, dict) and "person_id" in val:
            em_pids.add(val["person_id"])
        elif isinstance(val, str):
            em_pids.add(val)

    print(f"\n  Person IDs in contacts-merged: {len(merged_pids)}")
    print(f"  Person IDs in entity-map: {len(em_pids)}")


    in_merged_not_em = merged_pids - em_pids
    if in_merged_not_em:
        print(f"\n  IN MERGED BUT NOT IN ENTITY-MAP: {len(in_merged_not_em)} person_ids")
        for pid in sorted(in_merged_not_em):
            match = df[df["person_id"] == pid]
            if len(match) > 0:
                row = match.iloc[0]
                print(
                    f"    person_id={pid}, name={row.get('name', '?')}, "
                    f"email={row.get('email', '?')}, score={row.get('score', '?')}"
                )
    else:
        print("\n  All merged person_ids exist in entity-map.")


    in_em_not_merged = em_pids - merged_pids
    if in_em_not_merged:
        print(f"\n  IN ENTITY-MAP BUT NOT IN MERGED: {len(in_em_not_merged)} person_ids")

        count = 0
        for key, val in entity_map.items():
            if isinstance(val, dict):
                pid = val.get("person_id")
                if pid in in_em_not_merged:
                    print(
                        f"    person_id={pid}, email={key}, "
                        f"canonical_name={val.get('canonical_name', '?')}"
                    )
                    count += 1
            elif isinstance(val, str) and val in in_em_not_merged:
                print(f"    person_id={val}, email={key}")
                count += 1
            if count >= 200:
                remaining = len(in_em_not_merged) - count
                if remaining > 0:
                    print(f"    ... and {remaining} more")
                break
    else:
        print("\n  All entity-map person_ids exist in merged contacts.")





def audit_additional(df: pd.DataFrame, iphone: pd.DataFrame | None):
    print("\n" + "=" * 80)
    print("8. ADDITIONAL CHECKS")
    print("=" * 80)


    if "is_automated" in df.columns:
        auto_high = df[(df["is_automated"] == True) & (df["score"] > 30)]  # noqa: E712
        if len(auto_high) > 0:
            print(f"\n  AUTOMATED BUT SCORE>30: {len(auto_high)} records")
            for _, row in auto_high.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row['name']}, "
                    f"score={row['score']:.1f}, email={row.get('email', '?')}"
                )
        else:
            print("\n  No automated contacts with score>30.")


    if "source_count" in df.columns:
        zero_sources = df[df["source_count"] == 0]
        if len(zero_sources) > 0:
            print(f"\n  SOURCE_COUNT=0: {len(zero_sources)} records")
            for _, row in zero_sources.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row['name']}, "
                    f"email={row.get('email', '?')}"
                )
        else:
            print("\n  All contacts have source_count >= 1.")


    noise_domains = {
        "mailchimp.com",
        "sendgrid.net",
        "hubspotemail.net",
        "mandrillapp.com",
        "mailgun.org",
        "amazonaws.com",
        "gtempaccount.com",
    }
    if "domain" in df.columns:
        noise_contacts = df[df["domain"].fillna("").str.lower().isin(noise_domains)]
        if len(noise_contacts) > 0:
            print(
                f"\n  CONTACTS WITH NOISE DOMAINS (should have been filtered): {len(noise_contacts)} records"
            )
            for _, row in noise_contacts.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row['name']}, "
                    f"domain={row['domain']}, email={row.get('email', '?')}, score={row.get('score', '?')}"
                )


    if "last_contact" in df.columns:
        future = df[df["last_contact"] > pd.Timestamp.now(tz="UTC")]
        if len(future) > 0:
            print(f"\n  LAST_CONTACT IN THE FUTURE (after today): {len(future)} records")
            for _, row in future.iterrows():
                print(
                    f"    person_id={row['person_id']}, name={row['name']}, "
                    f"last_contact={row['last_contact']}"
                )


    if iphone is not None:
        iphone_names = set(iphone["name"].dropna().str.strip().str.lower())
        merged_names = set(df["name"].dropna().str.strip().str.lower())
        unlinked = iphone_names - merged_names
        print(f"\n  iPhone contacts: {len(iphone_names)} unique names")
        print(f"  Merged contacts: {len(merged_names)} unique names")
        print(f"  iPhone names NOT in merged (exact match): {len(unlinked)}")

        if unlinked:
            for name in sorted(unlinked)[:30]:
                print(f"    {name}")
            if len(unlinked) > 30:
                print(f"    ... and {len(unlinked) - 30} more")


    print("\n  --- SUMMARY ---")
    print(f"  Total contacts: {len(df)}")
    print(f"  With email: {df['has_email'].sum()}")
    print(f"  With calendar: {df['has_calendar'].sum()}")
    print(f"  With Slack: {df['has_slack'].sum()}")
    print(f"  With LinkedIn: {df['has_linkedin'].sum()}")
    print(f"  With WhatsApp: {df['has_whatsapp'].sum()}")
    print(f"  With iPhone: {df['has_iphone'].sum()}")
    print(f"  With Attio: {df['has_attio'].sum()}")
    print(f"  With Personio: {df['has_personio'].sum()}")
    print(f"  Internal: {df['is_internal'].sum()}")
    print(f"  Automated: {df['is_automated'].sum()}")
    print(f"  Avg source count: {df['source_count'].mean():.1f}")
    print(f"  Max source count: {df['source_count'].max()}")
    print(f"  Avg score: {df['score'].mean():.1f}")
    print(f"  Contacts with score=0: {(df['score'] == 0).sum()}")
    print(f"  Contacts with phone: {df['phone_primary'].notna().sum()}")





def main():
    merged, iphone, entity_map = load_data()

    audit_dates(merged)
    audit_phones(merged, iphone)
    audit_scores(merged)
    audit_names(merged)
    audit_organizations(merged)
    audit_duplicates(merged, entity_map)
    audit_orphans(merged, entity_map)
    audit_additional(merged, iphone)

    print("\n" + "=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
