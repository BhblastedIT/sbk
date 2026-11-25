#!/usr/bin/env python3
"""LinkedIn email enrichment (L2)."""



































from __future__ import annotations

import argparse
import json
import logging
import smtplib
import sys
import time
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_name  # noqa: E402

from sbk_config import ENRICHED_DIR, LINKEDIN_DIR, safe_write_parquet  # noqa: E402

try:
    import dns.resolver  # type: ignore[import-untyped]
except ImportError:
    dns = None  # type: ignore[assignment]



LINKEDIN_CONTACTS_FILE = LINKEDIN_DIR / "contacts-linkedin.parquet"
MERGED_CONTACTS_FILE = ENRICHED_DIR / "contacts-merged.parquet"
ENRICHED_OUT_DIR = LINKEDIN_DIR.parent / "enriched"

log = logging.getLogger("li-l2-email-enrich")


GENERIC_EMAIL_DOMAINS: set[str] = {
    "gmail.com",
    "yahoo.com",
    "yahoo.it",
    "hotmail.com",
    "hotmail.it",
    "outlook.com",
    "live.com",
    "live.it",
    "icloud.com",
    "me.com",
    "ymail.com",
    "libero.it",
    "virgilio.it",
    "tiscali.it",
    "alice.it",
    "fastwebnet.it",
    "tin.it",
    "email.it",
    "pec.it",
    "aruba.it",
    "protonmail.com",
    "proton.me",
    "mail.com",
    "aol.com",
    "msn.com",
    "gmx.com",
    "gmx.de",
    "web.de",
    "zoho.com",
    "tutanota.com",
    "tuta.io",
}


SMTP_TIMEOUT = 10


_mx_cache: dict[str, list[str] | None] = {}





def normalize_for_email(name: str) -> str:
    ""



    if not name or not isinstance(name, str):
        return ""

    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))

    s = s.lower()
    s = "".join(c if c.isalpha() or c == " " else " " for c in s)
    return " ".join(s.split())


def split_name(normalized_name: str) -> tuple[str, str]:
    ""




    parts = normalized_name.split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], "".join(parts[1:]))


def generate_email_candidates(firstname: str, lastname: str, domain: str) -> list[str]:
    ""
















    if not firstname or not lastname or not domain:
        return []

    candidates = [
        f"{firstname}.{lastname}@{domain}",
        f"{firstname}@{domain}",
        f"{firstname[0]}.{lastname}@{domain}",
        f"{firstname[0]}{lastname}@{domain}",
        f"{lastname}@{domain}",
    ]


    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return unique





def build_org_domain_map(merged_df: pd.DataFrame) -> dict[str, str]:
    ""







    if "organization" not in merged_df.columns or "domain" not in merged_df.columns:
        log.warning("contacts-merged.parquet missing organization/domain columns")
        return {}

    org_domain = merged_df[["organization", "domain"]].copy()
    org_domain = org_domain.dropna()
    org_domain["organization"] = org_domain["organization"].astype(str).str.strip()
    org_domain["domain"] = org_domain["domain"].astype(str).str.strip().str.lower()


    org_domain = org_domain[
        (org_domain["organization"] != "")
        & (org_domain["domain"] != "")
        & (~org_domain["domain"].isin(GENERIC_EMAIL_DOMAINS))
    ]

    if org_domain.empty:
        return {}


    org_groups = org_domain.groupby("organization")["domain"].agg(
        lambda x: Counter(x).most_common(1)[0][0] if len(x) > 0 else ""
    )


    result: dict[str, str] = {}
    for org, domain in org_groups.items():
        result[str(org).strip().lower()] = domain

    log.info(f"Org->domain map: {len(result)} organizations with corporate domains")
    return result





def import_from_csv(
    csv_path: Path,
    linkedin_df: pd.DataFrame,
) -> list[dict]:
    ""












    log.info(f"CSV import: reading {csv_path}")

    if not csv_path.exists():
        log.error(f"CSV file not found: {csv_path}")
        return []



    skip = 0
    try:
        with open(csv_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if "First Name" in line:
                    skip = i
                    break
    except UnicodeDecodeError:
        pass

    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            csv_df = pd.read_csv(csv_path, encoding=encoding, skiprows=skip)
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    else:
        log.error(f"Cannot read CSV file with any encoding: {csv_path}")
        return []

    log.info(f"CSV loaded: {len(csv_df)} rows, columns: {list(csv_df.columns)}")


    col_map: dict[str, str] = {}
    for col in csv_df.columns:
        cl = col.strip().lower()
        if "first" in cl and "name" in cl:
            col_map[col] = "first_name"
        elif "last" in cl and "name" in cl:
            col_map[col] = "last_name"
        elif "email" in cl:
            col_map[col] = "email"
        elif "company" in cl:
            col_map[col] = "company"
        elif "position" in cl:
            col_map[col] = "position"
        elif "connected" in cl:
            col_map[col] = "connected_on"

    csv_df = csv_df.rename(columns=col_map)

    if "email" not in csv_df.columns:
        log.error("CSV file has no email column")
        return []

    if "first_name" not in csv_df.columns or "last_name" not in csv_df.columns:
        log.error("CSV file missing first_name/last_name columns")
        return []


    li_lookup: dict[str, dict] = {}
    for _, row in linkedin_df.iterrows():
        norm = normalize_name(str(row.get("name", "")))
        if norm:
            li_lookup[norm] = {
                "name": str(row.get("name", "")),
                "linkedin_id": str(row.get("linkedin_id", "")),
                "linkedin_url": str(row.get("linkedin_url", "")),
            }

    results: list[dict] = []
    matched = 0
    no_email = 0
    no_match = 0

    for _, row in csv_df.iterrows():
        first = str(row.get("first_name", "")).strip()
        last = str(row.get("last_name", "")).strip()
        email = str(row.get("email", "")).strip().lower()

        if not first or not last:
            continue

        full_name = f"{first} {last}"
        norm = normalize_name(full_name)

        if not email or email == "nan" or "@" not in email:
            no_email += 1
            continue


        li_contact = li_lookup.get(norm)
        if not li_contact:

            no_match += 1
            continue

        matched += 1
        results.append(
            {
                "linkedin_id": li_contact["linkedin_id"],
                "linkedin_url": li_contact["linkedin_url"],
                "name": li_contact["name"],
                "email": email,
                "method": "csv_import",
                "confidence": "high",
                "verified": True,
                "domain": email.split("@")[1] if "@" in email else "",
            }
        )

    log.info(
        f"CSV import: {matched} matched with email, "
        f"{no_email} had no email in CSV, "
        f"{no_match} could not match to LinkedIn contacts"
    )
    return results





def guess_emails(
    linkedin_df: pd.DataFrame,
    org_domain_map: dict[str, str],
    merged_df: pd.DataFrame | None = None,
    limit: int | None = None,
) -> list[dict]:
    ""
















    log.info("Pattern guessing: generating email candidates...")
    t0 = time.time()


    name_org_lookup: dict[str, str] = {}
    if merged_df is not None and "organization" in merged_df.columns:
        for _, mrow in merged_df.iterrows():
            mname = normalize_name(str(mrow.get("name", "")))
            morg = str(mrow.get("organization", "")).strip()
            if mname and morg:
                name_org_lookup[mname] = morg
        log.info(f"Name->org lookup from contacts-merged: {len(name_org_lookup)} entries")

    results: list[dict] = []
    stats = Counter(
        {
            "processed": 0,
            "no_org": 0,
            "no_domain": 0,
            "candidates_generated": 0,
            "org_from_merged": 0,
        }
    )

    for idx, row in linkedin_df.iterrows():
        if limit and stats["processed"] >= limit:
            break

        stats["processed"] += 1
        name = str(row.get("name", "")).strip()
        if not name:
            continue


        company = str(row.get("company", "")).strip()
        headline = str(row.get("headline", "")).strip()

        org = company if company else ""


        if not org and headline:
            org = _extract_org_from_headline(headline)


        if not org and name_org_lookup:
            norm_name = normalize_name(name)
            org = name_org_lookup.get(norm_name, "")
            if org:
                stats["org_from_merged"] += 1

        if not org:
            stats["no_org"] += 1
            continue


        org_lower = org.lower().strip()
        domain = org_domain_map.get(org_lower)

        if not domain:

            domain = _fuzzy_domain_lookup(org_lower, org_domain_map)

        if not domain:
            stats["no_domain"] += 1
            continue


        normalized = normalize_for_email(name)
        firstname, lastname = split_name(normalized)

        if not firstname or not lastname:
            continue

        candidates = generate_email_candidates(firstname, lastname, domain)
        if not candidates:
            continue

        stats["candidates_generated"] += 1

        results.append(
            {
                "linkedin_id": str(row.get("linkedin_id", "")),
                "linkedin_url": str(row.get("linkedin_url", "")),
                "name": name,
                "organization": org,
                "domain": domain,
                "candidates": candidates,
                "email": candidates[0],
                "method": "pattern_guess",
                "confidence": "medium",
                "verified": False,
            }
        )

    elapsed = time.time() - t0
    log.info(
        f"Pattern guessing: {stats['candidates_generated']} contacts with candidates "
        f"({stats['no_org']} no org, {stats['no_domain']} no domain match), "
        f"processed {stats['processed']} in {elapsed:.1f}s"
    )
    return results


def _extract_org_from_headline(headline: str) -> str:
    ""



    import re

    if not headline:
        return ""


    m = re.search(r"@\s*([A-Z][^\|@\n,]+)", headline)
    if m:
        return m.group(1).strip().rstrip(" |")


    m = re.search(r"\bat\b\s+([A-Z][^\|@\n,]+)", headline)
    if m:
        return m.group(1).strip().rstrip(" |")


    m = re.search(r"\bpresso\b\s+([A-Z][^\|@\n,]+)", headline, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(" |")


    if "|" in headline:
        parts = headline.split("|")
        last = parts[-1].strip()
        if last and len(last) > 2:
            return last

    return ""


def _fuzzy_domain_lookup(org_lower: str, org_domain_map: dict[str, str]) -> str | None:
    ""









    for key, domain in org_domain_map.items():
        if len(org_lower) >= 3 and len(key) >= 3:
            if org_lower in key or key in org_lower:
                return domain


    org_first = org_lower.split()[0] if org_lower.split() else ""
    if org_first and len(org_first) >= 4:
        for key, domain in org_domain_map.items():
            key_first = key.split()[0] if key.split() else ""
            if key_first == org_first:
                return domain

    return None





def verify_mx(domain: str) -> bool:
    ""









    if dns is None:
        log.warning("dnspython not installed, skipping MX verification (pip install dnspython)")
        return False

    if domain in _mx_cache:
        return _mx_cache[domain] is not None

    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_hosts = [str(r.exchange).rstrip(".") for r in answers]
        _mx_cache[domain] = mx_hosts
        return True
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.resolver.Timeout,
        Exception,
    ):
        _mx_cache[domain] = None
        return False


def verify_smtp(email: str, domain: str) -> bool:
    ""














    mx_hosts = _mx_cache.get(domain)
    if not mx_hosts:
        return False

    mx_host = mx_hosts[0]

    try:
        server = smtplib.SMTP(timeout=SMTP_TIMEOUT)
        server.connect(mx_host, 25)
        server.ehlo("sbk.local")
        server.mail("verify@sbk.local")
        code, _ = server.rcpt(email)
        server.quit()

        return code == 250
    except (
        smtplib.SMTPException,
        TimeoutError,
        OSError,
    ):
        return False


def verify_candidates(
    results: list[dict],
    use_smtp: bool = False,
) -> list[dict]:
    ""













    if dns is None:
        log.warning("dnspython not installed. Install with: uv pip install dnspython")
        log.warning("Skipping verification step.")
        return results

    log.info(f"Verifying candidates (SMTP={'ON' if use_smtp else 'OFF'})...")
    t0 = time.time()

    stats = Counter({"checked": 0, "mx_valid": 0, "mx_invalid": 0, "smtp_valid": 0})

    for rec in results:
        if rec.get("method") != "pattern_guess":
            continue

        domain = rec.get("domain", "")
        if not domain:
            continue

        stats["checked"] += 1


        has_mx = verify_mx(domain)
        rec["mx_valid"] = has_mx

        if not has_mx:
            stats["mx_invalid"] += 1
            rec["confidence"] = "low"
            rec["verified"] = False
            continue

        stats["mx_valid"] += 1


        if use_smtp:
            candidates = rec.get("candidates", [])
            smtp_verified: list[str] = []

            for candidate in candidates:
                if verify_smtp(candidate, domain):
                    smtp_verified.append(candidate)
                    stats["smtp_valid"] += 1
                    break


                time.sleep(0.5)

            if smtp_verified:
                rec["email"] = smtp_verified[0]
                rec["confidence"] = "high"
                rec["verified"] = True
                rec["smtp_verified"] = smtp_verified
            else:
                rec["confidence"] = "medium"
                rec["verified"] = False
        else:

            rec["confidence"] = "medium"
            rec["verified"] = False

    elapsed = time.time() - t0
    log.info(
        f"Verification: {stats['checked']} checked, "
        f"{stats['mx_valid']} MX valid, {stats['mx_invalid']} MX invalid"
        + (f", {stats['smtp_valid']} SMTP verified" if use_smtp else "")
        + f" in {elapsed:.1f}s"
    )
    return results





def save_results(
    results: list[dict],
    dry_run: bool = False,
) -> None:
    ""





    if not results:
        log.info("No results to save.")
        return


    methods = Counter(r["method"] for r in results)
    confidence = Counter(r["confidence"] for r in results)
    verified = sum(1 for r in results if r.get("verified"))

    log.info("\n" + "=" * 60)
    log.info("ENRICHMENT SUMMARY")
    log.info("=" * 60)
    log.info(f"  Total results:      {len(results)}")
    log.info(f"  Via CSV import:     {methods.get('csv_import', 0)}")
    log.info(f"  Via pattern guess:  {methods.get('pattern_guess', 0)}")
    log.info(f"  Verified:           {verified}")
    log.info(f"  High confidence:    {confidence.get('high', 0)}")
    log.info(f"  Medium confidence:  {confidence.get('medium', 0)}")
    log.info(f"  Low confidence:     {confidence.get('low', 0)}")

    if dry_run:
        log.info("\n[DRY RUN] No files written.")

        log.info("\nSample results (first 10):")
        for r in results[:10]:
            log.info(
                f"  {r['name']} -> {r['email']} "
                f"({r['method']}, {r['confidence']}"
                + (", verified" if r.get("verified") else "")
                + ")"
            )
        return

    ENRICHED_OUT_DIR.mkdir(parents=True, exist_ok=True)


    json_path = ENRICHED_OUT_DIR / "email-enrichment.json"

    json_results = []
    for r in results:
        jr = dict(r)

        for k, v in jr.items():
            if isinstance(v, set):
                jr[k] = list(v)
        json_results.append(jr)

    output = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline": "li-l2-email-enrich",
        "total_results": len(results),
        "methods": dict(methods),
        "confidence_distribution": dict(confidence),
        "verified_count": verified,
        "results": json_results,
    }

    json_path.write_text(json.dumps(output, indent=2, default=str, ensure_ascii=False))
    log.info(f"  Saved -> {json_path}")


    parquet_rows = []
    for r in results:
        parquet_rows.append(
            {
                "linkedin_id": r.get("linkedin_id", ""),
                "linkedin_url": r.get("linkedin_url", ""),
                "name": r.get("name", ""),
                "email": r.get("email", ""),
                "method": r.get("method", ""),
                "confidence": r.get("confidence", ""),
                "verified": r.get("verified", False),
                "domain": r.get("domain", ""),
                "organization": r.get("organization", ""),
            }
        )

    parquet_df = pd.DataFrame(parquet_rows)
    parquet_path = ENRICHED_OUT_DIR / "email-enrichment.parquet"
    safe_write_parquet(parquet_df, parquet_path, index=False)
    log.info(f"  Saved -> {parquet_path}")





def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn email enrichment — SBK L2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from LinkedIn CSV export
  python3 tools/linkedin/li-l2-email-enrich.py --csv ~/Downloads/Connections.csv

  # Guess emails for contacts with known orgs
  python3 tools/linkedin/li-l2-email-enrich.py --guess

  # Guess + DNS verification
  python3 tools/linkedin/li-l2-email-enrich.py --guess --verify

  # Full pipeline: CSV + guess + DNS + SMTP
  python3 tools/linkedin/li-l2-email-enrich.py --csv Connections.csv --guess --verify --smtp

  # Test with limit
  python3 tools/linkedin/li-l2-email-enrich.py --guess --dry-run --limit 20
        """,
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to LinkedIn Connections.csv export",
    )
    parser.add_argument(
        "--guess",
        action="store_true",
        help="Enable email pattern guessing from org + domain",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify candidates with DNS MX check",
    )
    parser.add_argument(
        "--smtp",
        action="store_true",
        help="Also verify with SMTP RCPT TO (requires --verify)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show results without writing files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max contacts to process (for testing)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    if not args.csv and not args.guess:
        parser.error("At least one of --csv or --guess is required")

    if args.smtp and not args.verify:
        parser.error("--smtp requires --verify")


    if not LINKEDIN_CONTACTS_FILE.exists():
        log.error(f"LinkedIn contacts not found: {LINKEDIN_CONTACTS_FILE}")
        log.error("Run li-l1-enrich.py first to generate contacts-linkedin.parquet")
        sys.exit(1)

    log.info("=" * 60)
    log.info("LINKEDIN EMAIL ENRICHMENT — SBK L2")
    log.info("=" * 60)

    linkedin_df = pd.read_parquet(LINKEDIN_CONTACTS_FILE)
    log.info(f"Loaded {len(linkedin_df)} LinkedIn contacts")


    email_col = linkedin_df["email"].astype(str).str.strip()
    has_email_mask = (email_col != "") & (email_col != "nan")
    already_have = has_email_mask.sum()
    if already_have > 0:
        log.info(
            f"  {already_have} already have email, {len(linkedin_df) - already_have} need enrichment"
        )

    all_results: list[dict] = []


    if args.csv:
        csv_results = import_from_csv(args.csv, linkedin_df)
        all_results.extend(csv_results)
        log.info(f"CSV import: {len(csv_results)} emails found")


    if args.guess:

        if not MERGED_CONTACTS_FILE.exists():
            log.error(f"Merged contacts not found: {MERGED_CONTACTS_FILE}")
            log.error("Run xs-l2-merge-contacts.py first")
            sys.exit(1)

        merged_df = pd.read_parquet(MERGED_CONTACTS_FILE)
        org_domain_map = build_org_domain_map(merged_df)


        csv_linkedin_ids = {r["linkedin_id"] for r in all_results}
        guess_df = linkedin_df[~linkedin_df["linkedin_id"].isin(csv_linkedin_ids)]

        guess_results = guess_emails(
            guess_df, org_domain_map, merged_df=merged_df, limit=args.limit
        )
        all_results.extend(guess_results)
        log.info(f"Pattern guess: {len(guess_results)} candidates generated")


    if args.verify:
        all_results = verify_candidates(all_results, use_smtp=args.smtp)


    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for r in all_results:
        lid = r.get("linkedin_id", "")
        if lid and lid not in seen_ids:
            seen_ids.add(lid)
            deduped.append(r)
    all_results = deduped


    save_results(all_results, dry_run=args.dry_run)

    log.info("\n" + "=" * 60)
    log.info("LINKEDIN EMAIL ENRICHMENT COMPLETE")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
