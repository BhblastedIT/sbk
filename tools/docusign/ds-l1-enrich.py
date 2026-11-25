#!/usr/bin/env python3
"""DocuSign enrichment pipeline (L1)."""


















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import DOCUSIGN_DIR, DOCUSIGN_RAW_DIR, OWN_EMAILS, OWNER_NAME, safe_write_parquet



RAW_DIR = DOCUSIGN_RAW_DIR
PROCESSED_DIR = DOCUSIGN_DIR
RAW_FILE = RAW_DIR / "contracts-metadata.json"



DETAILS_FILE = RAW_DIR / "raw" / "contract-details.json"

RUOLI_VECCHI = {"carbonCopie": "carbonCopy", "certifiedDeliverie": "certifiedDelivery"}

log = logging.getLogger("docusign-enrich")




CONTRACT_TYPE_RULES = [

    (r"(?i)\b(NDA|non[\s-]*disclosure|confidentiality|riservatezza)\b", "NDA"),

    (
        r"(?i)\b(employment|assunzione|lettera[\s_]*di[\s_]*assunzione|proroga[\s_]*a[\s_]*tempo|contratto[\s_]*di[\s_]*lavoro|co\.?co\.?co|collaborazione[\s_]*autonoma|collaborazione[\s_]*coordinata|tirocinio|stage|internship|amendment[\s_]*collaboration)\b",
        "EMPLOYMENT",
    ),

    (
        r"(?i)\b(investment|investimento|term[\s_]*sheet|SAFE|convertible|share[\s_]*purchase|SPA|SHA|shareholders|cap[\s_]*table|round|fundrais|lettera[\s_]*di[\s_]*intenti|LOI)\b",
        "INVESTMENT",
    ),

    (
        r"(?i)\b(partnership|joint[\s_]*venture|JV|accordo[\s_]*di[\s_]*partnership|memorandum|MOU)\b",
        "PARTNERSHIP",
    ),

    (
        r"(?i)\b(servizi|service|appalto|contratto[\s_]*di[\s_]*servizi|order[\s_]*form|SLA|statement[\s_]*of[\s_]*work|SOW|consulenza)\b",
        "SERVICE",
    ),

    (r"(?i)\b(logistic[ao]?|contratto[\s_]*logistic[ao]|warehousing|magazzino)\b", "LOGISTICS"),

    (r"(?i)\b(produzione|production|contratto[\s_]*produzione|manufacturing)\b", "PRODUCTION"),

    (r"(?i)\b(lease|affitto|locazione|immobile|real[\s_]*estate)\b", "LEASE"),
]



# load from user config; maps a raw legal name to its display name
KNOWN_COMPANIES = {
    "example srl": "Example",
}







# Sender name -> address when the envelope has no address; you are filled in
# from sbk.config.json (owner, own_emails).
KNOWN_SENDER_EMAILS: dict[str, str] = (
    {OWNER_NAME: sorted(OWN_EMAILS)[0]} if OWNER_NAME and OWN_EMAILS else {}
)





def clean_contract_title(name: str) -> str:
    ""






    if not name:
        return ""

    name = re.sub(r"^Completa con Docusign:\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^Complete with Docusign:\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\[Docusign\]\s*Request for eSignatures:\s*", "", name, flags=re.IGNORECASE)

    name = re.sub(r"\.(pdf|docx|doc|xlsx)(\s*\(\d+\))?$", "", name, flags=re.IGNORECASE)

    name = re.sub(r"\.{2,}$", "", name)
    name = name.strip()
    return name


def is_garbage_entry(name: str) -> bool:
    ""



    if not name or not name.strip():
        return True
    garbage_exact = {"send a document"}
    if name.strip().lower() in garbage_exact:
        return True
    return False


def is_contract_title_not_person(name: str) -> bool:
    ""



    if not name:
        return True

    if len(name) > 60:
        return True

    title_starts = [
        r"^contratto\b",
        r"^agreement\b",
        r"^NDA\b",
        r"^order\s+form\b",
        r"^lettera\b",
        r"^proroga\b",
        r"^cessione\b",
        r"^CONFIDENTIALITY\b",
        r"^amendment\b",
        r"^service\b",
        r"^commercial\b",
        r"^repayment\b",
        r"^advisory\b",
        r"^term\s+sheet\b",
        r"^SAFE\b",
        r"^proposta\b",
        r"^addendum\b",
    ]
    for pat in title_starts:
        if re.match(pat, name, re.IGNORECASE):
            return True

    if re.match(r"^\d{2}\.\d{4}\b", name):
        return True

    generic_words = {"co", "partners", "società benefit"}
    if name.strip().lower() in generic_words:
        return True
    return False


def load_raw() -> list[dict]:
    ""
    if not RAW_FILE.exists():
        log.error(f"Raw file not found: {RAW_FILE}")
        sys.exit(1)
    with open(RAW_FILE, encoding="utf-8") as f:
        data = json.load(f)

    before = len(data)
    data = [d for d in data if not is_garbage_entry(d.get("name", ""))]
    filtered = before - len(data)
    if filtered:
        log.info(f"Filtered {filtered} garbage entries (e.g. 'Send a Document')")
    log.info(f"Loaded {len(data)} raw contracts from {RAW_FILE.name}")
    return data


def load_details() -> dict[str, dict]:
    ""
    if not DETAILS_FILE.exists():
        log.warning(f"Details file not found: {DETAILS_FILE} (recipients from titles only)")
        return {}
    with open(DETAILS_FILE, encoding="utf-8") as f:
        dettagli = json.load(f)
    per_id = {d["envelopeId"]: d for d in dettagli if d.get("envelopeId")}
    log.info(f"Loaded {len(per_id)} envelope details from {DETAILS_FILE.name}")
    return per_id


def destinatari_veri(dettaglio: dict | None) -> list[dict]:
    ""
    fuori = []
    for r in (dettaglio or {}).get("recipients") or []:
        nome = (r.get("name") or "").strip()
        email = (r.get("email") or "").strip().lower()
        if not nome and not email:
            continue
        ruolo = r.get("role") or ""
        fuori.append(
            {
                "name": nome,
                "email": email,
                "role": RUOLI_VECCHI.get(ruolo, ruolo),
                "status": r.get("status") or "",
                "signed": (r.get("signedDateTime") or "")[:10],
            }
        )
    return fuori


def classify_contract(name: str) -> str:
    ""
    if not name:
        return "OTHER"
    for pattern, ctype in CONTRACT_TYPE_RULES:
        if re.search(pattern, name):
            return ctype
    return "OTHER"


def parse_date(date_str: str) -> str | None:
    ""
    if not date_str or not date_str.strip():
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:

        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%m-%d-%Y"]:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def normalize_sender(from_field: str) -> tuple[str, bool]:
    ""



    if not from_field or not from_field.strip():
        return ("", False)

    name = from_field.strip()
    name_lower = name.lower()


    for key, canonical in KNOWN_COMPANIES.items():
        if key in name_lower:
            return (canonical, True)


    if re.search(r"(?i)\b(srl|s\.r\.l|ltd|gmbh|inc|llc|spa|s\.p\.a|sarl|sas)\b", name):
        return (name, True)


    return (name, False)


def _clean_party_name(name: str) -> str:
    ""
    if not name:
        return ""


    for _ in range(3):
        name = re.sub(r"\s*\(\d+\)\s*$", "", name)
        name = re.sub(r"\.(pdf|docx|doc|xlsx)$", "", name, flags=re.IGNORECASE)
    name = name.strip()
    return name


def extract_parties_from_name(contract_name: str) -> list[str]:
    ""



    parties = []


    if "_" in contract_name:
        after_underscore = contract_name.rsplit("_", 1)[-1]

        after_underscore = _clean_party_name(after_underscore)
        if after_underscore:

            parts = [_clean_party_name(p) for p in after_underscore.split(" - ") if p.strip()]
            parties.extend([p for p in parts if p])




    return parties





def build_contracts(raw_data: list[dict], details: dict[str, dict] | None = None) -> pd.DataFrame:
    ""




    log.info("Phase 1: Building contracts.parquet...")
    t0 = time.time()
    details = details or {}

    rows = []
    for i, contract in enumerate(raw_data):
        name_raw = contract.get("name", "").strip()
        from_field = contract.get("from", "").strip()
        status_raw = contract.get("status", "").strip()
        date_raw = contract.get("date", "")
        page = contract.get("page", 0)


        name = clean_contract_title(name_raw)


        date_parsed = parse_date(date_raw)


        status = status_raw.lower() if status_raw else "unknown"
        if status == "sent":
            status = "pending"


        contract_type = classify_contract(name_raw)


        sender_name, sender_is_company = normalize_sender(from_field)


        parties = extract_parties_from_name(name)
        dettaglio = details.get(contract.get("envelopeId") or "")
        veri = destinatari_veri(dettaglio)


        companies = set()
        if sender_is_company and sender_name:
            companies.add(sender_name)
        for party in parties:
            norm_party_lower = party.lower()
            for key, canonical in KNOWN_COMPANIES.items():
                if key in norm_party_lower:
                    companies.add(canonical)
                    break
            else:

                if re.search(
                    r"(?i)\b(srl|s\.r\.l|ltd|gmbh|inc|llc|spa|s\.p\.a|sarl|sas|srls|s\.r\.l\.s)\b",
                    party,
                ):
                    companies.add(party.strip())


        sender_email = ""
        if not sender_is_company and sender_name:
            sender_email = ((dettaglio or {}).get("sender") or {}).get(
                "email", ""
            ).strip().lower() or KNOWN_SENDER_EMAILS.get(sender_name, "")
        nomi_veri = list(dict.fromkeys(r["name"] or r["email"] for r in veri))

        rows.append(
            {
                "contract_id": f"DS-{i + 1:04d}",
                "title": name,
                "title_raw": name_raw,
                "status": status,
                "sender_name": sender_name if not sender_is_company else "",
                "sender_email": sender_email,
                "sender_company": sender_name if sender_is_company else "",
                "recipients": ", ".join(nomi_veri or parties),
                "recipient_emails": ", ".join(
                    dict.fromkeys(r["email"] for r in veri if r["email"])
                ),
                "recipients_detail": json.dumps(veri, ensure_ascii=False) if veri else "",
                "envelope_id": contract.get("envelopeId") or "",
                "created_date": date_parsed or "",
                "completed_date": date_parsed if status == "completed" else "",
                "contract_type": contract_type,
                "company_mentioned": ", ".join(sorted(companies)) if companies else "",
                "page": page,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("created_date", ascending=False, na_position="last", inplace=True)

    elapsed = time.time() - t0
    log.info(f"Contracts: {len(df)} records in {elapsed:.1f}s")


    type_counts = df["contract_type"].value_counts().to_dict()
    status_counts = df["status"].value_counts().to_dict()
    log.info(f"  Types: {type_counts}")
    log.info(f"  Statuses: {status_counts}")

    return df





_RE_SOCIETA = r"(?i)\b(srl|s\.r\.l|ltd|gmbh|inc|llc|spa|s\.p\.a|sarl|sas|srls|s\.r\.l\.s)\b"


def build_contacts(contracts_df: pd.DataFrame) -> pd.DataFrame:
    ""










    log.info("Phase 2: Building contacts-docusign.parquet...")

    contact_agg = defaultdict(
        lambda: {
            "names": defaultdict(int),
            "email": "",
            "roles": set(),
            "contract_count": 0,
            "first_contract": "",
            "last_contract": "",
            "contract_types": set(),
            "is_company": False,
        }
    )

    def conta(nome: str, email: str, ruolo: str, date: str, ctype: str, societa: bool) -> None:
        agg = contact_agg[email or nome]
        if nome:
            agg["names"][nome] += 1
        agg["email"] = email
        agg["roles"].add(ruolo)
        agg["contract_count"] += 1
        agg["contract_types"].add(ctype)
        agg["is_company"] = agg["is_company"] or societa
        if not agg["first_contract"] or (date and date < agg["first_contract"]):
            agg["first_contract"] = date
        if not agg["last_contract"] or (date and date > agg["last_contract"]):
            agg["last_contract"] = date

    for _, row in contracts_df.iterrows():
        date = row["created_date"]
        ctype = row["contract_type"]


        sender = row.get("sender_name", "").strip()
        if sender:
            conta(sender, row.get("sender_email", "") or "", "sender", date, ctype, False)


        sender_co = row.get("sender_company", "").strip()
        if sender_co:
            conta(sender_co, "", "sender", date, ctype, True)


        veri = json.loads(row.get("recipients_detail") or "[]")
        if veri:
            for r in veri:
                nome = r["name"]
                conta(
                    nome, r["email"], "recipient", date, ctype, bool(re.search(_RE_SOCIETA, nome))
                )
            continue
        recipients = row.get("recipients", "")
        if recipients:
            for r in recipients.split(", "):
                r = _clean_party_name(r.strip())
                if not r:
                    continue
                conta(r, "", "recipient", date, ctype, bool(re.search(_RE_SOCIETA, r)))

    rows = []
    filtered_titles = 0
    for chiave, agg in contact_agg.items():
        nomi = agg["names"]
        name = max(nomi, key=nomi.get) if nomi else chiave
        if not name:
            continue
        email = agg["email"]


        if not email and is_contract_title_not_person(name):
            filtered_titles += 1
            continue

        if not email and agg["is_company"] and len(name) > 50:
            filtered_titles += 1
            continue
        rows.append(
            {
                "name": name,
                "email": email or KNOWN_SENDER_EMAILS.get(name, ""),
                "role": ", ".join(sorted(agg["roles"])),
                "is_company": agg["is_company"],
                "contract_count": agg["contract_count"],
                "first_contract": agg["first_contract"],
                "last_contract": agg["last_contract"],
                "contract_types": ", ".join(sorted(agg["contract_types"])),
            }
        )

    if filtered_titles:
        log.info(f"  Filtered {filtered_titles} contract-title entries from contacts")

    df = pd.DataFrame(rows)
    df.sort_values("contract_count", ascending=False, inplace=True)

    companies = df["is_company"].sum()
    people = len(df) - companies
    with_email = (df["email"] != "").sum()
    log.info(
        f"Contacts: {len(df)} unique ({people} people, {companies} companies, {with_email} with email)"
    )

    return df





def build_timeline(contracts_df: pd.DataFrame) -> pd.DataFrame:
    ""
    log.info("Phase 3: Building timeline-docusign.parquet...")

    rows = []
    for _, row in contracts_df.iterrows():
        date = row["created_date"]
        if not date:
            continue

        contract_id = row["contract_id"]
        title = row["title"]
        status = row["status"]
        sender = row["sender_name"] or row["sender_company"] or ""
        recipients = row["recipients"]
        ctype = row["contract_type"]


        parties_list = []
        if sender:
            parties_list.append(sender)
        if recipients:
            parties_list.extend([r.strip() for r in recipients.split(", ") if r.strip()])
        parties = ", ".join(parties_list)


        if status == "completed":
            event_type = "contract_completed"
            description = f"[{ctype}] {title[:120]} — Completed"
        elif status == "voided":
            event_type = "contract_voided"
            description = f"[{ctype}] {title[:120]} — Voided"
        elif status == "pending":
            event_type = "contract_sent"
            description = f"[{ctype}] {title[:120]} — Pending"
        else:
            event_type = "contract_unknown"
            description = f"[{ctype}] {title[:120]} — {status}"

        rows.append(
            {
                "date": date,
                "event_type": event_type,
                "contract_id": contract_id,
                "parties": parties,
                "description": description,
                "contract_type": ctype,
                "status": status,
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("date", ascending=False, inplace=True)

    log.info(f"Timeline: {len(df)} events")


    if len(df) > 0:
        log.info(f"  Range: {df['date'].min()} → {df['date'].max()}")

    return df





def build_summary(
    contracts_df: pd.DataFrame, contacts_df: pd.DataFrame, timeline_df: pd.DataFrame
) -> dict:
    ""
    log.info("Phase 4: Building summary...")


    dates = [d for d in contracts_df["created_date"] if d]
    date_range = {"min": min(dates) if dates else "", "max": max(dates) if dates else ""}


    status_counts = contracts_df["status"].value_counts().to_dict()


    type_counts = contracts_df["contract_type"].value_counts().to_dict()


    sender_company_counts = (
        contracts_df[contracts_df["sender_company"] != ""]["sender_company"]
        .value_counts()
        .head(10)
        .to_dict()
    )


    top_contacts = contacts_df.head(15)[
        ["name", "role", "is_company", "contract_count", "contract_types"]
    ].to_dict("records")


    monthly = defaultdict(int)
    for d in contracts_df["created_date"]:
        if d:
            monthly[d[:7]] += 1

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "docusign-enrich-v2",
        "totals": {
            "contracts": len(contracts_df),
            "unique_contacts": len(contacts_df),
            "companies": int(contacts_df["is_company"].sum()),
            "people": int(len(contacts_df) - contacts_df["is_company"].sum()),
            "timeline_events": len(timeline_df),
        },
        "date_range": date_range,
        "status_distribution": status_counts,
        "type_distribution": type_counts,
        "top_sender_companies": sender_company_counts,
        "monthly_volume": dict(sorted(monthly.items(), reverse=True)),
        "top_contacts": top_contacts,
    }

    return summary




STEP_NAMES = ["contracts", "contacts", "timeline", "summary"]


def main():
    parser = argparse.ArgumentParser(description="DocuSign enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--step", default=None, choices=STEP_NAMES, help="Run single step (default: all)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not RAW_FILE.exists():
        log.error(f"Raw file not found: {RAW_FILE}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    raw_data = load_raw()
    details = load_details()

    if not raw_data:
        log.error("No contracts found in raw file.")
        sys.exit(1)

    steps_to_run = [args.step] if args.step else STEP_NAMES

    contracts_df = None
    contacts_df = None
    timeline_df = None


    if "contracts" in steps_to_run or any(
        s in steps_to_run for s in ["contacts", "timeline", "summary"]
    ):
        contracts_df = build_contracts(raw_data, details)
        if "contracts" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "contracts.parquet"
            safe_write_parquet(contracts_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "contacts" in steps_to_run or "summary" in steps_to_run:
        if contracts_df is None:
            contracts_df = build_contracts(raw_data, details)
        contacts_df = build_contacts(contracts_df)
        if "contacts" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "contacts-docusign.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "timeline" in steps_to_run or "summary" in steps_to_run:
        if contracts_df is None:
            contracts_df = build_contracts(raw_data, details)
        timeline_df = build_timeline(contracts_df)
        if "timeline" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "timeline-docusign.parquet"
            safe_write_parquet(timeline_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "summary" in steps_to_run:
        if contracts_df is None:
            contracts_df = build_contracts(raw_data, details)
        if contacts_df is None:
            contacts_df = build_contacts(contracts_df)
        if timeline_df is None:
            timeline_df = build_timeline(contracts_df)

        summary = build_summary(contracts_df, contacts_df, timeline_df)

        if args.dry_run:
            log.info("\n=== DRY RUN — Summary ===")
            log.info(json.dumps(summary, indent=2))
        else:
            out = PROCESSED_DIR / "_docusign_summary.json"
            out.write_text(json.dumps(summary, indent=2, default=str))
            log.info(f"  Saved → {out}")


    log.info("\n" + "=" * 60)
    log.info("DOCUSIGN ENRICHMENT COMPLETE")
    log.info("=" * 60)
    if contracts_df is not None:
        log.info(f"  Contracts:  {len(contracts_df)}")
    if contacts_df is not None:
        log.info(f"  Contacts:   {len(contacts_df)}")
    if timeline_df is not None:
        log.info(f"  Timeline:   {len(timeline_df)} events")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-docusign-enrich", source="docusign-l1", stage="l1")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
