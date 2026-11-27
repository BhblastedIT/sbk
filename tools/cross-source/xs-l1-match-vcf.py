"""Contact matcher (strict mode): matches the contacts of a CSV file against the merged contacts, the entity map,
Attio, LinkedIn and phone contacts, and writes a Markdown report.
"""

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from text_utils import normalize_name, normalize_phone  # noqa: E402

from sbk_config import DATA_ROOT



PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# The CSV is yours and always passed with --csv; the report goes to your data root.
CSV_PATH: Path | None = None
OUTPUT_PATH = DATA_ROOT / "contacts" / "contacts-match-report.md"

CONTACTS_MERGED = DATA_ROOT / "enriched" / "contacts-merged.parquet"
CONTACTS_PARQUET = DATA_ROOT / "enriched" / "contacts.parquet"
ENTITY_MAP = DATA_ROOT / "enriched" / "entity-map.json"


ATTIO_PEOPLE = DATA_ROOT / "attio" / "people.parquet"
LINKEDIN_DIR = DATA_ROOT / "linkedin" / "processed"
IPHONE_CONTACTS = DATA_ROOT / "contacts" / "contacts.json"
IPHONE_ENRICHED = DATA_ROOT / "contacts" / "enriched-with-phone.json"
IPHONE_MATCHED = DATA_ROOT / "contacts" / "iphone-contacts-matched.json"


def phone_variants(phone: str) -> set:
    ""
    if not phone:
        return set()

    norm = normalize_phone(phone)
    if not norm:
        return set()

    variants = {norm}
    digits_only = re.sub(r"[^\d]", "", norm)
    variants.add(digits_only)


    if norm.startswith("+39"):
        local = norm[3:]
        variants.add(local)
        variants.add("0" + local)
    elif digits_only.startswith("39") and len(digits_only) > 9:
        local = digits_only[2:]
        variants.add(local)
        variants.add("+39" + local)


    if len(digits_only) >= 9:
        variants.add(digits_only[-10:])
        variants.add(digits_only[-9:])

    return {v for v in variants if v and len(v) >= 7}





def is_uuid(s: str) -> bool:
    ""
    return bool(
        re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", str(s).strip())
    )


def strict_name_match(csv_first: str, csv_last: str, csv_full: str, db_name: str) -> tuple:
    ""








    search_name = normalize_name(csv_full or f"{csv_first} {csv_last}".strip())
    target_name = normalize_name(db_name)

    if not search_name or not target_name:
        return (0.0, "none")


    if len(target_name) < 2 or len(search_name) < 2:
        return (0.0, "none")

    search_tokens = search_name.split()
    target_tokens = target_name.split()


    if search_name == target_name:

        if len(search_tokens) == 1:
            return (0.40, "first_only_exact")
        return (1.0, "exact")

    csv_first_norm = normalize_name(csv_first)
    csv_last_norm = normalize_name(csv_last)


    if csv_first_norm and csv_last_norm:

        if csv_first_norm == csv_last_norm:
            if search_name == target_name:
                return (1.0, "exact")
            return (0.0, "none")



        last_tokens = csv_last_norm.split()
        core_last = last_tokens[-1] if last_tokens else csv_last_norm

        first_found = csv_first_norm in target_tokens
        last_found = csv_last_norm in target_tokens or core_last in target_tokens

        if first_found and last_found:
            return (0.95, "first_last_exact")


        if first_found:

            remaining_target = [t for t in target_tokens if t != csv_first_norm]

            remaining_str = " ".join(remaining_target)

            for t in remaining_target:
                if len(t) >= 3:


                    if len(core_last) >= 2 and t.startswith(core_last):
                        return (0.85, "first_exact_last_prefix")


                    ratio = SequenceMatcher(None, core_last, t).ratio()


                    min_ratio = 0.80 if len(core_last) >= 5 else 0.90
                    if ratio >= min_ratio and len(core_last) >= 4:
                        return (0.85, "first_exact_last_fuzzy")


            if len(last_tokens) > 1 and remaining_str:
                ratio = SequenceMatcher(None, csv_last_norm, remaining_str).ratio()
                if ratio >= 0.85:
                    return (0.85, "first_exact_last_fuzzy")


        if len(search_tokens) >= 2 and len(target_tokens) >= 2:
            ratio = SequenceMatcher(None, search_name, target_name).ratio()
            if ratio >= 0.94:
                return (0.80, "full_name_fuzzy")

        return (0.0, "none")





    if csv_first_norm and not csv_last_norm:
        if csv_first_norm in target_tokens:
            if len(target_tokens) == 1 and target_tokens[0] == csv_first_norm:
                return (0.40, "first_only_exact")
            return (0.30, "first_in_multi")

        return (0.0, "none")

    return (0.0, "none")





def load_csv_contacts():
    ""
    df = pd.read_csv(CSV_PATH)
    contacts = []
    for _, row in df.iterrows():
        contact = {
            "nome": str(row.get("Nome", "")).strip() if pd.notna(row.get("Nome")) else "",
            "cognome": str(row.get("Cognome", "")).strip() if pd.notna(row.get("Cognome")) else "",
            "nome_completo": str(row.get("Nome Completo", "")).strip()
            if pd.notna(row.get("Nome Completo"))
            else "",
            "telefono": str(row.get("Telefono", "")).strip()
            if pd.notna(row.get("Telefono"))
            else "",
            "email": str(row.get("Email", "")).strip() if pd.notna(row.get("Email")) else "",
            "azienda": str(row.get("Azienda", "")).strip() if pd.notna(row.get("Azienda")) else "",
            "note": str(row.get("Note", "")).strip() if pd.notna(row.get("Note")) else "",
            "categorie": str(row.get("Categorie", "")).strip()
            if pd.notna(row.get("Categorie"))
            else "",
        }
        contacts.append(contact)
    return contacts


def load_merged_contacts():
    ""
    dfs = {}
    if CONTACTS_MERGED.exists():
        dfs["merged"] = pd.read_parquet(CONTACTS_MERGED)
        print(f"  contacts-merged.parquet: {len(dfs['merged'])} rows")
    if CONTACTS_PARQUET.exists():
        dfs["contacts"] = pd.read_parquet(CONTACTS_PARQUET)
        print(f"  contacts.parquet: {len(dfs['contacts'])} rows")
    if ATTIO_PEOPLE.exists():
        dfs["attio"] = pd.read_parquet(ATTIO_PEOPLE)
        print(f"  attio/people.parquet: {len(dfs['attio'])} rows")
    return dfs


def load_entity_map():
    ""
    if ENTITY_MAP.exists():
        with open(ENTITY_MAP) as f:
            return json.load(f)
    return {}


def load_iphone_contacts():
    ""
    contacts = []
    for path in [IPHONE_CONTACTS, IPHONE_ENRICHED, IPHONE_MATCHED]:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    contacts.extend(data)
                elif isinstance(data, dict):
                    if "contacts" in data:
                        contacts.extend(data["contacts"])
                    elif "matched" in data:
                        contacts.extend(data["matched"])
                    else:
                        for v in data.values():
                            if isinstance(v, dict):
                                contacts.append(v)
                            elif isinstance(v, list):
                                contacts.extend(v)
            print(f"  {path.name}: loaded")
    return contacts


def load_linkedin_data():
    ""
    profiles = []
    if LINKEDIN_DIR.exists():
        for f in LINKEDIN_DIR.glob("*.parquet"):
            try:
                df = pd.read_parquet(f)
                profiles.append(df)
                print(f"  linkedin/{f.name}: {len(df)} rows")
            except Exception as e:
                print(f"  linkedin/{f.name}: error {e}")
        for f in LINKEDIN_DIR.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        profiles.append(pd.DataFrame(data))
                    print(f"  linkedin/{f.name}: loaded")
            except Exception as e:
                print(f"  linkedin/{f.name}: error {e}")
    return profiles





def extract_person_info_from_row(row, source: str) -> dict:
    ""
    info = {"source": source}


    for col in [
        "name",
        "full_name",
        "display_name",
        "nome_completo",
        "first_name",
        "nome",
        "person_name",
    ]:
        val = row.get(col)
        if val and pd.notna(val):
            info["name"] = str(val).strip()
            break

    if "name" not in info:
        first = ""
        last = ""
        for col in ["first_name", "nome", "firstName", "given_name"]:
            val = row.get(col)
            if val and pd.notna(val):
                first = str(val).strip()
                break
        for col in ["last_name", "cognome", "lastName", "family_name", "surname"]:
            val = row.get(col)
            if val and pd.notna(val):
                last = str(val).strip()
                break
        if first or last:
            info["name"] = f"{first} {last}".strip()


    for col in [
        "email",
        "email_address",
        "primary_email",
        "emails",
        "email_addresses",
        "emailAddresses",
        "email_1",
    ]:
        val = row.get(col)
        if val and pd.notna(val):
            val_str = str(val).strip()
            if "@" in val_str:

                emails_found = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", val_str)
                if emails_found:
                    info["email"] = emails_found[0].lower()
                break


    for col in ["company", "organization", "org", "azienda", "company_name", "current_company"]:
        val = row.get(col)
        if val and pd.notna(val):
            val_str = str(val).strip()
            if not is_uuid(val_str) and len(val_str) > 1:
                info["company"] = val_str
                break


    if "company" not in info:
        for col in ["attio_company", "related_company"]:
            val = row.get(col)
            if val and pd.notna(val):
                val_str = str(val).strip()
                if not is_uuid(val_str) and len(val_str) > 1:
                    info["company"] = val_str
                    break


    for col in [
        "linkedin",
        "linkedin_url",
        "linkedin_profile",
        "linkedIn",
        "profile_url",
        "linkedin_profile_url",
        "attio_linkedin",
    ]:
        val = row.get(col)
        if val and pd.notna(val):
            val_str = str(val).strip()
            if "linkedin" in val_str.lower() or val_str.startswith("http"):
                info["linkedin"] = val_str
                break


    for col in [
        "phone",
        "phone_number",
        "mobile",
        "telefono",
        "phones",
        "phone_numbers",
        "phoneNumbers",
        "phone_primary",
    ]:
        val = row.get(col)
        if val and pd.notna(val):
            val_str = str(val).strip()
            if val_str and val_str.lower() not in ("true", "false", "0", "1", "nan"):
                info["phone"] = val_str
                break


    for col in [
        "title",
        "job_title",
        "headline",
        "role",
        "position",
        "attio_job_title",
        "role_title",
        "linkedin_headline",
    ]:
        val = row.get(col)
        if val and pd.notna(val):
            val_str = str(val).strip()
            if len(val_str) > 1 and not is_uuid(val_str):
                info["title"] = val_str
                break


    for col in ["score", "total_score", "match_score", "relationship_score"]:
        val = row.get(col)
        if val and pd.notna(val):
            try:
                info["score"] = float(val)
            except (ValueError, TypeError):
                pass
            break


    for col in ["source_count", "num_sources", "n_sources"]:
        val = row.get(col)
        if val and pd.notna(val):
            try:
                info["source_count"] = int(val)
            except (ValueError, TypeError):
                pass
            break


    for col in ["organization"]:
        val = row.get(col)
        if val and pd.notna(val) and "company" not in info:
            val_str = str(val).strip()
            if not is_uuid(val_str) and len(val_str) > 1:
                info["company"] = val_str


    val = row.get("all_emails")
    if val and pd.notna(val):
        info["all_emails"] = str(val).strip()

    return info





def build_phone_index(dfs, iphone_contacts):
    ""
    phone_index = {}

    for source_name, df in dfs.items():
        phone_cols = [
            c for c in df.columns if any(p in c.lower() for p in ["phone", "mobile", "telefono"])
        ]

        phone_cols = [c for c in phone_cols if df[c].dtype != "bool"]

        for _, row in df.iterrows():
            person_info = extract_person_info_from_row(row, source_name)
            for col in phone_cols:
                val = row.get(col)
                if val and pd.notna(val):
                    val_str = str(val).strip()
                    if val_str.lower() in ("true", "false", "0", "1", "nan"):
                        continue
                    for variant in phone_variants(val_str):
                        if variant not in phone_index:
                            phone_index[variant] = []
                        phone_index[variant].append(person_info)


    for c in iphone_contacts:
        if isinstance(c, dict):
            phones = []
            for key in ["phone", "phones", "telefono", "mobile", "phoneNumbers"]:
                val = c.get(key)
                if val:
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict):
                                phones.extend([str(v) for v in item.values() if v])
                            else:
                                phones.append(str(item))
                    elif isinstance(val, dict):
                        phones.extend([str(v) for v in val.values() if v])
                    else:
                        phones.append(str(val))

            name = ""
            for key in ["name", "displayName", "full_name", "fullName"]:
                if c.get(key):
                    name = str(c[key])
                    break
            if not name:
                first = c.get("firstName", c.get("first_name", ""))
                last = c.get("lastName", c.get("last_name", ""))
                name = f"{first} {last}".strip()

            email = ""
            for key in ["email", "emails", "emailAddresses"]:
                val = c.get(key)
                if val:
                    if isinstance(val, list) and val:
                        item = val[0]
                        email = str(item.get("value", item) if isinstance(item, dict) else item)
                    elif isinstance(val, str) and "@" in val:
                        email = val
                    break

            company = c.get("company", c.get("organization", ""))

            person_info = {
                "name": name,
                "email": email if "@" in str(email) else "",
                "company": str(company) if company and not is_uuid(str(company)) else "",
                "source": "iphone",
            }

            for p in phones:
                for variant in phone_variants(p):
                    if variant not in phone_index:
                        phone_index[variant] = []
                    phone_index[variant].append(person_info)

    print(f"  Phone index: {len(phone_index)} entries")
    return phone_index


def build_name_records(dfs):
    ""
    records = []

    for source_name, df in dfs.items():
        for _, row in df.iterrows():
            person_info = extract_person_info_from_row(row, source_name)
            name = person_info.get("name", "")
            if name and len(normalize_name(name)) >= 2:
                records.append((name, person_info))

    print(f"  Name records: {len(records)} entries")
    return records


def build_email_index(dfs):
    ""
    email_index = {}

    for source_name, df in dfs.items():
        email_cols = [c for c in df.columns if "email" in c.lower() or "mail" in c.lower()]

        for _, row in df.iterrows():
            person_info = extract_person_info_from_row(row, source_name)
            for col in email_cols:
                val = row.get(col)
                if val and pd.notna(val):
                    email_str = str(val).strip().lower()
                    for email in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", email_str):
                        if email not in email_index:
                            email_index[email] = []
                        email_index[email].append(person_info)

    print(f"  Email index: {len(email_index)} entries")
    return email_index





def match_contact(contact, phone_index, name_records, email_index):
    ""





    phone_matches = []
    email_matches = []
    name_matches = []


    if contact["telefono"]:
        variants = phone_variants(contact["telefono"])
        seen_names = set()
        for variant in variants:
            if variant in phone_index:
                for person in phone_index[variant]:
                    pname = person.get("name", "")
                    if pname and pname not in seen_names:
                        seen_names.add(pname)
                        phone_matches.append(person)


    if contact["email"]:
        email_lower = contact["email"].strip().lower()
        if email_lower in email_index:
            for person in email_index[email_lower]:
                email_matches.append(person)


    csv_first = contact["nome"]
    csv_last = contact["cognome"]
    csv_full = contact["nome_completo"]

    best_name_score = 0.0
    best_name_type = "none"
    best_name_persons = []

    for db_name, person_info in name_records:
        score, match_type = strict_name_match(csv_first, csv_last, csv_full, db_name)
        if score > best_name_score:
            best_name_score = score
            best_name_type = match_type
            best_name_persons = [person_info]
        elif score == best_name_score and score > 0 and match_type == best_name_type:
            best_name_persons.append(person_info)


    result = None
    match_methods = []


    if phone_matches:
        result = merge_persons(phone_matches)
        match_methods.append("phone")


        if best_name_score >= 0.40:
            for p in best_name_persons[:3]:
                if _names_compatible(result.get("name", ""), p.get("name", "")):
                    result = merge_single_person(result, p)


    elif email_matches:
        result = merge_persons(email_matches)
        match_methods.append("email")

        if best_name_score >= 0.80:
            for p in best_name_persons[:3]:
                result = merge_single_person(result, p)


    elif best_name_score >= 0.80 and best_name_persons:

        unique_names = set()
        for p in best_name_persons:
            unique_names.add(normalize_name(p.get("name", "")))
        unique_names.discard("")


        if len(unique_names) <= 3:
            result = merge_persons(best_name_persons)
            match_methods.append(f"name({best_name_score:.2f},{best_name_type})")
        else:

            pass





    if result:
        result["match_methods"] = match_methods
        result["match_score"] = best_name_score if "name" in str(match_methods) else 1.0
        return result

    return None


def _names_compatible(name1: str, name2: str) -> bool:
    ""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return True
    t1 = set(n1.split())
    t2 = set(n2.split())

    return bool(t1 & t2)


def merge_persons(persons: list) -> dict:
    ""
    result = {
        "name": "",
        "email": "",
        "company": "",
        "linkedin": "",
        "phone": "",
        "title": "",
        "score": None,
        "source_count": None,
        "sources": set(),
        "all_emails": "",
    }

    for person in persons:
        for field in ["name", "email", "company", "linkedin", "phone", "title", "all_emails"]:
            val = person.get(field, "")
            if val and isinstance(val, str):

                if is_uuid(val):
                    continue
                if not result[field] or len(val) > len(result[field]):
                    result[field] = val

        if person.get("score") is not None:
            if result["score"] is None or person["score"] > result["score"]:
                result["score"] = person["score"]

        if person.get("source_count") is not None:
            if result["source_count"] is None or person["source_count"] > result["source_count"]:
                result["source_count"] = person["source_count"]

        result["sources"].add(person.get("source", ""))

    result["sources"] = sorted([s for s in result["sources"] if s])
    return result


def merge_single_person(base: dict, extra: dict) -> dict:
    ""
    for field in ["name", "email", "company", "linkedin", "phone", "title", "all_emails"]:
        val = extra.get(field, "")
        if val and isinstance(val, str) and not is_uuid(val):
            if not base.get(field) or len(val) > len(base.get(field, "")):
                base[field] = val

    if extra.get("score") is not None:
        if base.get("score") is None or extra["score"] > base["score"]:
            base["score"] = extra["score"]

    if extra.get("source_count") is not None:
        if base.get("source_count") is None or extra["source_count"] > base["source_count"]:
            base["source_count"] = extra["source_count"]

    if isinstance(base.get("sources"), list):
        src = extra.get("source", "")
        if src and src not in base["sources"]:
            base["sources"].append(src)

    return base





def clean_field(val: str) -> str:
    ""
    if not val:
        return ""
    if is_uuid(val):
        return ""

    return val.strip()


def generate_report(contacts, results):
    ""
    matched = [(c, r) for c, r in zip(contacts, results) if r is not None]
    unmatched = [c for c, r in zip(contacts, results) if r is None]

    lines = []
    lines.append("# Contact Match Report")
    lines.append("")
    lines.append(
        "> Contacts from the import file matched against the SBK L2 database"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total contacts**: {len(contacts)}")
    lines.append(f"- **Matched**: {len(matched)} ({len(matched) / len(contacts) * 100:.0f}%)")
    lines.append(f"- **Unmatched**: {len(unmatched)} ({len(unmatched) / len(contacts) * 100:.0f}%)")
    lines.append("")


    method_counts = {}
    for c, r in matched:
        for m in r.get("match_methods", []):
            base = m.split("(")[0]
            method_counts[base] = method_counts.get(base, 0) + 1
    lines.append("### Match methods")
    lines.append("")
    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{method}**: {count}")
    lines.append("")


    lines.append("---")
    lines.append("")
    lines.append("## Matched Contacts")
    lines.append("")

    for i, (contact, result) in enumerate(matched, 1):
        display_name = contact["nome_completo"] or f"{contact['nome']} {contact['cognome']}".strip()
        lines.append(f"### {i}. {display_name}")
        lines.append("")


        lines.append("**CSV**:")
        if contact["telefono"]:
            lines.append(f"- Phone: `{contact['telefono']}`")
        if contact["email"]:
            lines.append(f"- Email: `{contact['email']}`")
        if contact["azienda"]:
            lines.append(f"- Company: {contact['azienda']}")
        if contact["note"]:
            lines.append(f"- Note: {contact['note']}")
        if contact["categorie"]:
            lines.append(f"- Category: {contact['categorie']}")
        lines.append("")


        lines.append("**SBK enrichment**:")
        methods_str = ", ".join(result.get("match_methods", []))
        lines.append(f"- Match: {methods_str}")

        enriched_name = clean_field(result.get("name", ""))
        if enriched_name and enriched_name.lower() != display_name.lower():
            lines.append(f"- Full name (DB): **{enriched_name}**")

        enriched_email = clean_field(result.get("email", ""))
        if enriched_email:
            if not contact["email"] or enriched_email.lower() != contact["email"].lower():
                lines.append(f"- Email: `{enriched_email}`")

        enriched_company = clean_field(result.get("company", ""))
        if enriched_company:
            lines.append(f"- Company: **{enriched_company}**")

        enriched_title = clean_field(result.get("title", ""))
        if enriched_title:
            lines.append(f"- Title: {enriched_title}")

        enriched_linkedin = clean_field(result.get("linkedin", ""))
        if enriched_linkedin:
            lines.append(f"- LinkedIn: {enriched_linkedin}")

        if result.get("score") is not None:
            lines.append(f"- Relationship score: {result['score']:.1f}")

        if result.get("source_count") is not None:
            lines.append(f"- Source count: {result['source_count']}")

        if result.get("sources"):
            lines.append(f"- Found in: {', '.join(result['sources'])}")

        all_emails = clean_field(result.get("all_emails", ""))
        if all_emails and all_emails != enriched_email:
            lines.append(f"- All emails: {all_emails}")


        enrichments = []
        if enriched_email and not contact["email"]:
            enrichments.append("email")
        if enriched_company and not contact["azienda"]:
            enrichments.append("company")
        if enriched_linkedin:
            enrichments.append("linkedin")
        if enriched_title:
            enrichments.append("title")
        if enriched_name and enriched_name.lower() != display_name.lower():
            enrichments.append("full_name")

        if enrichments:
            lines.append(f"- **New data**: {', '.join(enrichments)}")

        lines.append("")


    lines.append("---")
    lines.append("")
    lines.append("## Unmatched Contacts")
    lines.append("")
    lines.append("| # | Name | Phone | Company | Category | Note |")
    lines.append("|---|------|-------|---------|----------|------|")

    for i, contact in enumerate(unmatched, 1):
        display_name = contact["nome_completo"] or f"{contact['nome']} {contact['cognome']}".strip()
        phone = contact["telefono"] or ""
        company = contact["azienda"] or ""
        category = contact["categorie"] or ""
        note = contact["note"][:60] + "..." if len(contact["note"]) > 60 else contact["note"] or ""
        lines.append(f"| {i} | {display_name} | `{phone}` | {company} | {category} | {note} |")

    lines.append("")


    lines.append("---")
    lines.append("")
    lines.append("## Enrichment Summary")
    lines.append("")

    email_enriched = sum(
        1 for c, r in matched if clean_field(r.get("email", "")) and not c["email"]
    )
    company_enriched = sum(
        1 for c, r in matched if clean_field(r.get("company", "")) and not c["azienda"]
    )
    linkedin_found = sum(1 for c, r in matched if clean_field(r.get("linkedin", "")))
    title_found = sum(1 for c, r in matched if clean_field(r.get("title", "")))

    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Emails discovered | {email_enriched} |")
    lines.append(f"| Companies discovered | {company_enriched} |")
    lines.append(f"| LinkedIn URLs found | {linkedin_found} |")
    lines.append(f"| Titles/roles found | {title_found} |")
    lines.append(f"| Unmatched (no data) | {len(unmatched)} |")
    lines.append("")
    lines.append("### Next steps")
    lines.append("")
    lines.append(
        f"- {len(unmatched)} contacts not in SBK: consider adding to Attio or searching on LinkedIn"
    )
    no_last = sum(1 for c in contacts if not c["cognome"])
    no_email = sum(1 for c in contacts if not c["email"])
    lines.append(f"- {no_last} contacts missing last name")
    lines.append(f"- {no_email} contacts missing email")
    lines.append("")

    return "\n".join(lines)





def _parse_args(argv=None):
    import argparse

    p = argparse.ArgumentParser(
        description=(
            "Contact matcher (strict mode): matches the contacts of a CSV file against the merged "
            "contacts, the entity map, Attio, LinkedIn and phone contacts, and writes a Markdown report"
        )
    )
    p.add_argument("--csv", type=Path, required=True, help="the contacts CSV to match (required)")
    p.add_argument(
        "--report", type=Path, default=OUTPUT_PATH, help=f"where the report goes (default {OUTPUT_PATH})"
    )
    return p.parse_args(argv)


def main():
    global CSV_PATH, OUTPUT_PATH
    args = _parse_args()
    CSV_PATH, OUTPUT_PATH = args.csv, args.report
    if not CSV_PATH.exists():
        print(f"No contacts CSV at {CSV_PATH}: pass one with --csv. Nothing matched.")
        sys.exit(1)
    print("=== SBK Contact Matcher (strict mode) ===\n")

    print("1. Loading CSV contacts...")
    contacts = load_csv_contacts()
    print(f"   {len(contacts)} contacts loaded\n")

    print("2. Loading L2 cross-source data...")
    dfs = load_merged_contacts()
    print()

    print("3. Loading entity map...")
    entity_map = load_entity_map()
    print(f"   {len(entity_map)} entries\n")

    print("4. Loading iPhone contacts...")
    iphone_contacts = load_iphone_contacts()
    print()

    print("5. Loading LinkedIn data...")
    linkedin_dfs = load_linkedin_data()
    for ldf in linkedin_dfs:
        if isinstance(ldf, pd.DataFrame) and not ldf.empty:
            dfs[f"linkedin_{id(ldf)}"] = ldf
    print()

    print("6. Building search indexes...")
    phone_index = build_phone_index(dfs, iphone_contacts)
    name_records = build_name_records(dfs)
    email_index = build_email_index(dfs)
    print()

    print("7. Matching contacts...")
    results = []
    for contact in contacts:
        result = match_contact(contact, phone_index, name_records, email_index)
        results.append(result)

    matched_count = sum(1 for r in results if r is not None)
    unmatched_count = len(contacts) - matched_count
    print(f"   Matched: {matched_count}/{len(contacts)}")
    print(f"   Unmatched: {unmatched_count}\n")


    for contact, result in zip(contacts, results):
        display_name = contact["nome_completo"] or f"{contact['nome']} {contact['cognome']}".strip()
        if result:
            methods = ", ".join(result.get("match_methods", []))
            db_name = result.get("name", "")
            print(f"   OK  {display_name:30s} -> {db_name:30s} [{methods}]")
        else:
            print(f"   --  {display_name:30s} -> NO MATCH")

    print()

    print("8. Generating report...")
    report = generate_report(contacts, results)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(report)

    print(f"   Report saved to: {OUTPUT_PATH}\n")
    print("=== Done ===")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-match-vcf", source="contacts-vcf", stage="l1")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
