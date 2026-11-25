#!/usr/bin/env python3
""















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_name, normalize_phone  # noqa: E402

from sbk_config import CONTACTS_DIR, IPHONE_DIR, safe_write_parquet



CONTACTS_PARQUET = CONTACTS_DIR / "contacts.parquet"
CONTACTS_JSON = (
    Path(__file__).resolve().parent.parent.parent
    / "sbk"
    / "raw"
    / "contacts"
    / "iphone-contacts.json"
)
CONTACTS_JSON_ALT = CONTACTS_DIR / "iphone-contacts.json"
PROCESSED_DIR = IPHONE_DIR

log = logging.getLogger("contacts-enrich")





_BUSINESS_PATTERNS = re.compile(
    r"\b("
    # generic business keywords; extend from user config if needed
    r"restaurant|hotel|pharmacy|clinic|shop\b|store\b|bank\b|taxi"
    r")\b",
    re.IGNORECASE,
)


def is_business_contact(name: str, organization: str = "") -> bool:
    ""
    text = f"{name} {organization}".strip()
    return bool(_BUSINESS_PATTERNS.search(text))


def validate_birthday(value: str) -> str | None:
    ""






    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    current_year = datetime.now(UTC).year


    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if 1900 <= dt.year <= current_year:
                return value
            log.warning(f"Birthday out of range ({dt.year}): {value}")
            return None
        except ValueError:
            continue


    log.warning(f"Birthday unparseable: {value}")
    return None


def extract_name_parts(full_name: str) -> tuple[str, str]:
    ""
    if not full_name or not isinstance(full_name, str):
        return "", ""
    parts = full_name.strip().split()
    if len(parts) == 0:
        return "", ""
    elif len(parts) == 1:
        return parts[0], ""
    else:
        return parts[0], " ".join(parts[1:])





def load_contacts() -> list[dict]:
    ""





    log.info("Phase 1: Loading contacts...")

    contacts = []


    if CONTACTS_PARQUET.exists():
        df = pd.read_parquet(CONTACTS_PARQUET)
        log.info(f"  Parquet: {len(df)} contacts")


        json_data = {}
        json_path = CONTACTS_JSON if CONTACTS_JSON.exists() else CONTACTS_JSON_ALT
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                raw = json.load(f)
            contacts_list = raw.get("contacts", []) if isinstance(raw, dict) else raw
            for c in contacts_list:
                json_data[c.get("name", "")] = c
            log.info(f"  JSON: {len(json_data)} contacts loaded for enrichment")

        for _, row in df.iterrows():
            full_name = str(row.get("full_name", "")).strip()
            first_name = str(row.get("first_name", "")).strip()
            last_name = str(row.get("last_name", "")).strip()
            primary_phone = str(row.get("primary_phone", "")).strip()
            primary_email = str(row.get("primary_email", "")).strip()
            organization = str(row.get("organization", "")).strip()
            title = str(row.get("title", "")).strip()
            all_phones_str = str(row.get("all_phones", "")).strip()
            all_emails_str = str(row.get("all_emails", "")).strip()


            json_contact = json_data.get(full_name, {})
            phones_list = json_contact.get("phones", [])
            emails_list = json_contact.get("emails", [])
            last_updated = json_contact.get("last_updated", "")
            birthday_raw = json_contact.get("birthday", "")


            if not phones_list and all_phones_str:
                phones_list = [p.strip() for p in re.split(r"[;,]", all_phones_str) if p.strip()]
            if not emails_list and all_emails_str:
                emails_list = [e.strip() for e in re.split(r"[;,]", all_emails_str) if e.strip()]


            if primary_phone and primary_phone not in phones_list:
                phones_list.insert(0, primary_phone)

            if primary_email and "@" in primary_email and primary_email not in emails_list:
                emails_list.insert(0, primary_email)


            birthday = validate_birthday(birthday_raw)


            is_biz = is_business_contact(full_name, organization)

            contacts.append(
                {
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "primary_phone": primary_phone,
                    "primary_email": primary_email,
                    "organization": organization,
                    "title": title,
                    "phones_list": phones_list,
                    "emails_list": emails_list,
                    "last_updated": last_updated,
                    "birthday": birthday,
                    "is_business": is_biz,
                }
            )
    else:

        json_path = CONTACTS_JSON if CONTACTS_JSON.exists() else CONTACTS_JSON_ALT
        if not json_path.exists():
            log.error("No contacts source found!")
            return []

        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)

        contacts_list = raw.get("contacts", []) if isinstance(raw, dict) else raw
        for c in contacts_list:
            name = c.get("name", "")
            first_name, last_name = extract_name_parts(name)
            phones = c.get("phones", [])
            emails = c.get("emails", [])
            org = c.get("organization", "")

            contacts.append(
                {
                    "full_name": name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "primary_phone": phones[0] if phones else "",
                    "primary_email": emails[0] if emails else "",
                    "organization": org,
                    "title": "",
                    "phones_list": phones,
                    "emails_list": emails,
                    "last_updated": c.get("last_updated", ""),
                    "birthday": validate_birthday(c.get("birthday", "")),
                    "is_business": is_business_contact(name, org),
                }
            )

        log.info(f"  JSON-only: {len(contacts)} contacts")

    log.info(f"Total contacts loaded: {len(contacts)}")
    return contacts





def build_contacts_parquet(contacts: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 2: Building contacts-iphone.parquet...")

    rows = []
    for c in contacts:
        name = c["full_name"]
        if not name:
            continue


        phones_normalized = [normalize_phone(p) for p in c["phones_list"] if normalize_phone(p)]
        phone_primary = normalize_phone(c["primary_phone"])
        if not phone_primary and phones_normalized:
            phone_primary = phones_normalized[0]


        email = c["primary_email"]
        if not email and c["emails_list"]:
            email = c["emails_list"][0]

        rows.append(
            {
                "name": name,
                "organization": c["organization"],
                "phone_numbers": phones_normalized,
                "email": email if email and "@" in email else "",
                "phone_primary": phone_primary,
                "name_normalized": normalize_name(name),
                "first_name": c["first_name"],
                "last_name": c["last_name"],
                "last_updated": c["last_updated"],
                "birthday": c.get("birthday") or "",
                "is_business": c.get("is_business", False),
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("name", inplace=True)
    log.info(f"Contacts parquet: {len(df)} records")
    return df





def build_summary(contacts: list[dict], df: pd.DataFrame) -> dict:
    ""
    log.info("Phase 3: Building summary...")


    orgs = [c["organization"] for c in contacts if c["organization"]]
    org_counts = Counter(orgs)


    has_phone = sum(1 for _, row in df.iterrows() if row["phone_primary"])
    has_email = sum(1 for _, row in df.iterrows() if row["email"])
    has_org = sum(1 for _, row in df.iterrows() if row["organization"])
    multi_phone = sum(1 for _, row in df.iterrows() if len(row["phone_numbers"]) > 1)



    CC_MAP = {
        "353": "IE",
        "351": "PT",
        "358": "FI",
        "359": "BG",
        "971": "AE",
        "972": "IL",
        "965": "KW",
        "960": "MV",
        "961": "LB",
        "966": "SA",
        "918": "IN",
        "521": "MX",
        "525": "MX",
        "523": "MX",
        "527": "MX",
        "529": "MX",
        "447": "UK",
        "407": "RO",
        "628": "ID",
        "620": "ID",
        "622": "ID",
        "623": "ID",
        "639": "PH",
        "821": "KR",
        "601": "MY",
        "614": "AU",
        "346": "ES",
        "491": "DE",
        "417": "CH",
        "316": "NL",
        "549": "AR",
        "336": "FR",
        "324": "BE",
        "507": "PA",
        "381": "RS",
        "387": "BA",
        "306": "GR",
        "216": "TN",
        "916": "IN",
        "668": "TH",
        "669": "TH",
        "660": "TH",
        "467": "SE",
        "39": "IT",
        "44": "UK",
        "49": "DE",
        "33": "FR",
        "34": "ES",
        "31": "NL",
        "41": "CH",
        "43": "AT",
        "32": "BE",
        "30": "GR",
        "36": "HU",
        "40": "RO",
        "45": "DK",
        "46": "SE",
        "47": "NO",
        "48": "PL",
        "52": "MX",
        "54": "AR",
        "55": "BR",
        "56": "CL",
        "57": "CO",
        "58": "VE",
        "60": "MY",
        "61": "AU",
        "62": "ID",
        "63": "PH",
        "65": "SG",
        "66": "TH",
        "81": "JP",
        "82": "KR",
        "86": "CN",
        "90": "TR",
        "91": "IN",
        "92": "PK",
        "93": "AF",
        "94": "LK",
        "95": "MM",
        "96": "IQ",
        "97": "AE",
        "98": "IR",
        "1": "US/CA",
        "7": "RU",
    }

    country_codes = Counter()
    for _, row in df.iterrows():
        phone = row["phone_primary"]
        if phone and phone.startswith("+"):
            digits = phone[1:]

            matched = False
            for prefix_len in (3, 2, 1):
                prefix = digits[:prefix_len]
                if prefix in CC_MAP:
                    cc_label = f"{CC_MAP[prefix]} (+{prefix})"
                    country_codes[cc_label] += 1
                    matched = True
                    break
            if not matched:
                country_codes[f"Other (+{digits[:3]})"] += 1
        elif phone:
            country_codes["No prefix"] += 1


    has_last = sum(1 for _, row in df.iterrows() if row["last_name"])

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "contacts-enrich-v1",
        "source": "iphone-contacts",
        "totals": {
            "contacts": len(df),
            "with_phone": has_phone,
            "with_email": has_email,
            "with_organization": has_org,
            "with_multiple_phones": multi_phone,
            "with_last_name": has_last,
        },
        "coverage": {
            "phone_rate": round(has_phone / len(df) * 100, 1) if df.shape[0] > 0 else 0,
            "email_rate": round(has_email / len(df) * 100, 1) if df.shape[0] > 0 else 0,
            "org_rate": round(has_org / len(df) * 100, 1) if df.shape[0] > 0 else 0,
        },
        "country_distribution": dict(country_codes.most_common()),
        "top_organizations": [
            {"org": org, "count": count} for org, count in org_counts.most_common(15)
        ],
    }

    return summary





def main():
    parser = argparse.ArgumentParser(description="iPhone contacts enrichment — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    contacts = load_contacts()
    if not contacts:
        log.error("No contacts loaded.")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    df = build_contacts_parquet(contacts)

    if not args.dry_run:
        out = PROCESSED_DIR / "contacts-iphone.parquet"
        safe_write_parquet(df, out, index=False)
        log.info(f"  Saved -> {out}")


    summary = build_summary(contacts, df)

    if args.dry_run:
        log.info("\n=== DRY RUN — Summary ===")
        log.info(json.dumps(summary, indent=2))
    else:
        out = PROCESSED_DIR / "_contacts_summary.json"
        out.write_text(json.dumps(summary, indent=2, default=str))
        log.info(f"  Saved -> {out}")


    log.info("\n" + "=" * 60)
    log.info("CONTACTS ENRICHMENT COMPLETE")
    log.info("=" * 60)
    log.info(f"  Total contacts:  {len(df)}")
    log.info(f"  With phone:      {summary['totals']['with_phone']}")
    log.info(f"  With email:      {summary['totals']['with_email']}")
    log.info(f"  With org:        {summary['totals']['with_organization']}")
    log.info(f"  Multi-phone:     {summary['totals']['with_multiple_phones']}")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-contacts-enrich", source="contacts-iphone", stage="l1")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
