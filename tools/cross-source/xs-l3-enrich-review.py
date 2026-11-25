#!/usr/bin/env python3
""











import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json


DATA_DIR = DATA_ROOT
INPUT_FILE = DATA_DIR / "enriched" / "entity-review.json"
OUTPUT_FILE = DATA_DIR / "enriched" / "entity-review-enriched.json"
ENTITY_MAP_FILE = DATA_DIR / "enriched" / "entity-map.json"

PARQUET_FILES = {
    "email": DATA_DIR / "enriched" / "contacts.parquet",
    "merged": DATA_DIR / "enriched" / "contacts-merged.parquet",
    "linkedin": DATA_DIR / "linkedin" / "processed" / "contacts-linkedin.parquet",
    "slack": DATA_DIR / "slack" / "processed" / "contacts-slack.parquet",
    "iphone": DATA_DIR / "contacts" / "processed" / "contacts-iphone.parquet",
    "attio": DATA_DIR / "attio" / "processed" / "contacts-attio.parquet",
    "docusign": DATA_DIR / "docusign" / "processed" / "contacts-docusign.parquet",
    "whatsapp": DATA_DIR / "whatsapp" / "processed" / "contacts-whatsapp.parquet",
}


def load_data():
    ""
    print("Loading data...")


    with open(INPUT_FILE) as f:
        review_items = json.load(f)
    print(f"  entity-review.json: {len(review_items)} items")


    with open(ENTITY_MAP_FILE) as f:
        entity_map = json.load(f)
    print(f"  entity-map.json: {len(entity_map)} keys")


    dfs = {}
    for name, path in PARQUET_FILES.items():
        if path.exists():
            dfs[name] = pd.read_parquet(path)
            print(f"  {name}: {len(dfs[name])} rows")
        else:
            print(f"  {name}: FILE NOT FOUND - {path}")
            dfs[name] = pd.DataFrame()

    return review_items, entity_map, dfs


def build_lookups(dfs):
    ""
    lookups = {}


    email_lookup = {}
    if not dfs["email"].empty:
        for _, row in dfs["email"].iterrows():
            email = str(row.get("email", "")).lower().strip()
            if email:
                email_lookup[email] = {
                    "name": row.get("name"),
                    "domain": row.get("domain"),
                    "msg_count_from": int(row.get("msg_count_from", 0) or 0),
                    "msg_count_to": int(row.get("msg_count_to", 0) or 0),
                    "msg_count_cc": int(row.get("msg_count_cc", 0) or 0),
                    "total_mentions": int(row.get("total_mentions", 0) or 0),
                    "first_seen": _ts(row.get("first_seen")),
                    "last_seen": _ts(row.get("last_seen")),
                }
    lookups["email"] = email_lookup
    print(f"  Email lookup: {len(email_lookup)} entries")


    merged_by_email = {}
    merged_by_name = {}
    if not dfs["merged"].empty:
        for _, row in dfs["merged"].iterrows():
            primary_email = str(row.get("email", "")).lower().strip()
            if primary_email:
                merged_by_email[primary_email] = row

            all_emails_raw = row.get("all_emails", "")
            if isinstance(all_emails_raw, str) and all_emails_raw.startswith("["):
                try:
                    all_emails = json.loads(all_emails_raw)
                    for em in all_emails:
                        em_lower = em.lower().strip()
                        if em_lower and em_lower not in merged_by_email:
                            merged_by_email[em_lower] = row
                except json.JSONDecodeError:
                    pass

            name = str(row.get("name", "")).strip().lower()
            if name and name != "nan":
                merged_by_name[name] = row
    lookups["merged_by_email"] = merged_by_email
    lookups["merged_by_name"] = merged_by_name
    print(f"  Merged lookup: {len(merged_by_email)} by email, {len(merged_by_name)} by name")


    linkedin_by_name = {}
    if not dfs["linkedin"].empty:
        for _, row in dfs["linkedin"].iterrows():
            name = str(row.get("name", "")).strip().lower()
            if name and name != "nan" and name != "linkedin member":
                linkedin_by_name[name] = {
                    "name": row.get("name"),
                    "linkedin_url": row.get("linkedin_url"),
                    "headline": row.get("headline"),
                    "company": row.get("company"),
                    "total_messages": int(row.get("total_messages", 0) or 0),
                    "first_message_date": _date(row.get("first_message_date")),
                    "last_message_date": _date(row.get("last_message_date")),
                    "connection_date": _date(row.get("connection_date")),
                }
    lookups["linkedin_by_name"] = linkedin_by_name
    print(f"  LinkedIn lookup: {len(linkedin_by_name)} by name")


    slack_by_name = {}
    if not dfs["slack"].empty:
        for _, row in dfs["slack"].iterrows():
            for name_col in ["real_name", "display_name"]:
                name = str(row.get(name_col, "")).strip().lower()
                if name and name != "nan":
                    slack_by_name[name] = {
                        "name": row.get("real_name") or row.get("display_name"),
                        "message_count": int(row.get("message_count", 0) or 0),
                        "channels_active": int(row.get("channels_active", 0) or 0),
                        "first_seen": _ts(row.get("first_seen")),
                        "last_seen": _ts(row.get("last_seen")),
                        "is_bot": bool(row.get("is_bot", False)),
                    }
    lookups["slack_by_name"] = slack_by_name
    print(f"  Slack lookup: {len(slack_by_name)} by name")


    iphone_by_name = {}
    if not dfs["iphone"].empty:
        for _, row in dfs["iphone"].iterrows():
            name = str(row.get("name", "")).strip().lower()
            if name and name != "nan":
                iphone_by_name[name] = {
                    "name": row.get("name"),
                    "phone_primary": row.get("phone_primary"),
                    "organization": row.get("organization")
                    if pd.notna(row.get("organization"))
                    else None,
                    "email": row.get("email") if pd.notna(row.get("email")) else None,
                }
    lookups["iphone_by_name"] = iphone_by_name
    print(f"  iPhone lookup: {len(iphone_by_name)} by name")


    attio_by_email = {}
    attio_by_name = {}
    if not dfs["attio"].empty:
        for _, row in dfs["attio"].iterrows():
            email = str(row.get("email", "")).lower().strip()
            if email and email != "nan":
                entry = {
                    "name": row.get("name"),
                    "email": email,
                    "company_name": row.get("company_name")
                    if pd.notna(row.get("company_name"))
                    else None,
                    "job_title": row.get("job_title") if pd.notna(row.get("job_title")) else None,
                    "location": row.get("location") if pd.notna(row.get("location")) else None,
                    "linkedin": row.get("linkedin") if pd.notna(row.get("linkedin")) else None,
                    "relationship_score": row.get("attio_relationship_score")
                    if pd.notna(row.get("attio_relationship_score"))
                    else None,
                    "connection_strength": row.get("attio_connection_strength")
                    if pd.notna(row.get("attio_connection_strength"))
                    else None,
                    "sourcing_stage": row.get("attio_sourcing_stage")
                    if pd.notna(row.get("attio_sourcing_stage"))
                    else None,
                    "notes_count": int(row.get("attio_notes_count", 0) or 0),
                    "meetings_count": int(row.get("attio_meetings_count", 0) or 0),
                    "last_interaction": _ts(row.get("attio_last_interaction")),
                }
                attio_by_email[email] = entry

                all_e = row.get("all_emails")
                if isinstance(all_e, str) and "@" in all_e:
                    for ae in [
                        x.strip()
                        for x in all_e.replace("[", "").replace("]", "").replace('"', "").split(",")
                    ]:
                        ae_lower = ae.lower().strip()
                        if ae_lower and ae_lower not in attio_by_email:
                            attio_by_email[ae_lower] = entry

            name = str(row.get("name", "")).strip().lower()
            if name and name != "nan":
                attio_by_name[name] = (
                    entry
                    if email
                    else {
                        "name": row.get("name"),
                        "company_name": row.get("company_name")
                        if pd.notna(row.get("company_name"))
                        else None,
                        "job_title": row.get("job_title")
                        if pd.notna(row.get("job_title"))
                        else None,
                    }
                )
    lookups["attio_by_email"] = attio_by_email
    lookups["attio_by_name"] = attio_by_name
    print(f"  Attio lookup: {len(attio_by_email)} by email, {len(attio_by_name)} by name")


    docusign_by_email = {}
    docusign_by_name = {}
    if not dfs["docusign"].empty:
        for _, row in dfs["docusign"].iterrows():
            email = str(row.get("email", "")).lower().strip()
            name = str(row.get("name", "")).strip().lower()
            entry = {
                "name": row.get("name"),
                "email": email if email and email != "nan" else None,
                "role": row.get("role"),
                "contract_count": int(row.get("contract_count", 0) or 0),
                "last_contract": _date(row.get("last_contract")),
            }
            if email and email != "nan":
                docusign_by_email[email] = entry
            if name and name != "nan":
                docusign_by_name[name] = entry
    lookups["docusign_by_email"] = docusign_by_email
    lookups["docusign_by_name"] = docusign_by_name
    print(f"  DocuSign lookup: {len(docusign_by_email)} by email, {len(docusign_by_name)} by name")


    whatsapp_by_name = {}
    whatsapp_by_phone = {}
    if not dfs["whatsapp"].empty:
        for _, row in dfs["whatsapp"].iterrows():
            name = str(row.get("name", "")).strip().lower()
            phone = str(row.get("phone", "")).strip()
            entry = {
                "name": row.get("name"),
                "phone": phone if phone and phone != "nan" else None,
                "message_count": int(row.get("message_count", 0) or 0),
                "last_message": _date(row.get("last_message")),
            }
            if name and name != "nan":
                whatsapp_by_name[name] = entry
            if phone and phone != "nan":
                whatsapp_by_phone[phone] = entry
    lookups["whatsapp_by_name"] = whatsapp_by_name
    lookups["whatsapp_by_phone"] = whatsapp_by_phone
    print(f"  WhatsApp lookup: {len(whatsapp_by_name)} by name")

    return lookups


def _safe_int(val, default=0):
    ""
    if val is None:
        return default
    try:
        if isinstance(val, float) and pd.isna(val):
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


def _ts(val):
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        if not val or val == "NaT" or val == "None":
            return None

        try:
            return val[:10]
        except Exception:
            return None
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return None


def _date(val):
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, str):
        if not val or val == "NaT" or val == "None" or val == "nan":
            return None
        return val[:10] if len(val) >= 10 else val
    return _ts(val)


def parse_key(key):
    ""






    if key.startswith("nameonly:"):
        parts = key.split(":", 2)
        if len(parts) == 3:
            return {"type": "nameonly", "source_hint": parts[1], "value": parts[2]}
        return {"type": "nameonly", "source_hint": "unknown", "value": key}
    else:
        return {"type": "email", "source_hint": "email", "value": key}


def enrich_person(key, name, lookups, entity_map):
    ""
    parsed = parse_key(key)
    person = {
        "key": key,
        "name": name,
        "sources": [],
        "email_count": 0,
        "domain": None,
        "organization": None,
        "phone": None,
        "linkedin_url": None,
        "last_seen": None,
        "interaction_summary": None,
    }

    interaction_parts = []
    dates_seen = []
    name_lower = (name or "").strip().lower()
    email_lower = None
    all_emails_for_lookup = []

    if parsed["type"] == "email":
        email_lower = parsed["value"].lower()
        all_emails_for_lookup.append(email_lower)
        person["domain"] = email_lower.split("@")[1] if "@" in email_lower else None


        emap_entry = entity_map.get(email_lower)
        if emap_entry and isinstance(emap_entry, dict):
            extra_emails = emap_entry.get("all_emails", [])
            for em in extra_emails:
                if em.lower() not in all_emails_for_lookup:
                    all_emails_for_lookup.append(em.lower())


    total_email_count = 0
    for em in all_emails_for_lookup:
        ec = lookups["email"].get(em)
        if ec:
            if "email" not in person["sources"]:
                person["sources"].append("email")
            total_email_count += ec["total_mentions"]
            if ec["last_seen"]:
                dates_seen.append(ec["last_seen"])
            if not person["domain"] and ec["domain"]:
                person["domain"] = ec["domain"]

    if total_email_count > 0:
        person["email_count"] = total_email_count
        interaction_parts.append(f"{total_email_count} email")


    merged = None
    for em in all_emails_for_lookup:
        merged = lookups["merged_by_email"].get(em)
        if merged is not None:
            break
    if merged is None and name_lower:
        merged = lookups["merged_by_name"].get(name_lower)

    if merged is not None:
        row = merged

        for org_col in ["organization", "attio_company"]:
            val = row.get(org_col)
            if val and pd.notna(val) and str(val).strip() and str(val).strip().lower() != "nan":
                person["organization"] = str(val).strip()
                break

        phone_val = row.get("phone_primary")
        if (
            phone_val
            and pd.notna(phone_val)
            and str(phone_val).strip()
            and str(phone_val).strip().lower() != "nan"
        ):
            person["phone"] = str(phone_val).strip()

        li_val = row.get("linkedin_url")
        if (
            li_val
            and pd.notna(li_val)
            and str(li_val).strip()
            and str(li_val).strip().lower() != "nan"
        ):
            person["linkedin_url"] = str(li_val).strip()

        if not person["domain"]:
            d = row.get("domain")
            if d and pd.notna(d) and str(d).strip().lower() != "nan":
                person["domain"] = str(d).strip()


        source_flag_map = {
            "has_calendar": "calendar",
            "has_plaud": "plaud",
            "has_tactiq": "tactiq",
            "has_attio": "attio",
            "has_personio": "personio",
            "has_linkedin": "linkedin",
            "has_slack": "slack",
            "has_whatsapp": "whatsapp",
            "has_docusign": "docusign",
            "has_iphone": "iphone",
            "has_notion": "notion",
        }
        for flag, src_name in source_flag_map.items():
            if bool(row.get(flag, False)):
                if src_name not in person["sources"]:
                    person["sources"].append(src_name)


        cal_events = _safe_int(row.get("cal_events"))
        if cal_events > 0:
            interaction_parts.append(f"{cal_events} cal events")
        tactiq_m = _safe_int(row.get("tactiq_meetings"))
        if tactiq_m > 0:
            interaction_parts.append(f"{tactiq_m} tactiq meetings")
        plaud_m = _safe_int(row.get("plaud_meetings"))
        if plaud_m > 0:
            interaction_parts.append(f"{plaud_m} plaud meetings")
        slack_m = _safe_int(row.get("slack_messages"))
        if slack_m > 0:
            interaction_parts.append(f"{slack_m} slack msgs")
        li_m = _safe_int(row.get("linkedin_messages"))
        if li_m > 0:
            interaction_parts.append(f"{li_m} linkedin msgs")
        wa_m = _safe_int(row.get("whatsapp_messages"))
        if wa_m > 0:
            interaction_parts.append(f"{wa_m} whatsapp msgs")
        docu_c = _safe_int(row.get("docusign_contracts"))
        if docu_c > 0:
            interaction_parts.append(f"{docu_c} docusign contracts")


        for date_col in [
            "last_contact",
            "email_last_seen",
            "cal_last_seen",
            "tactiq_last_seen",
            "attio_last_interaction",
        ]:
            d = _ts(row.get(date_col))
            if d:
                dates_seen.append(d)



    if name_lower:
        li = lookups["linkedin_by_name"].get(name_lower)
        if li:
            if "linkedin" not in person["sources"]:
                person["sources"].append("linkedin")
            if not person["linkedin_url"] and li.get("linkedin_url"):
                person["linkedin_url"] = li["linkedin_url"]
            if not person["organization"] and li.get("company"):
                person["organization"] = li["company"]
            if li.get("total_messages", 0) > 0 and not any(
                "linkedin" in p for p in interaction_parts
            ):
                interaction_parts.append(f"{li['total_messages']} linkedin msgs")
            if li.get("last_message_date"):
                dates_seen.append(li["last_message_date"])


    if name_lower:
        sl = lookups["slack_by_name"].get(name_lower)
        if sl and not sl.get("is_bot"):
            if "slack" not in person["sources"]:
                person["sources"].append("slack")
            if sl.get("message_count", 0) > 0 and not any("slack" in p for p in interaction_parts):
                interaction_parts.append(f"{sl['message_count']} slack msgs")
            if sl.get("last_seen"):
                dates_seen.append(sl["last_seen"])


    if name_lower:
        ip = lookups["iphone_by_name"].get(name_lower)
        if ip:
            if "iphone" not in person["sources"]:
                person["sources"].append("iphone")
            if not person["phone"] and ip.get("phone_primary"):
                person["phone"] = ip["phone_primary"]
            if not person["organization"] and ip.get("organization"):
                person["organization"] = ip["organization"]


    attio = None
    for em in all_emails_for_lookup:
        attio = lookups["attio_by_email"].get(em)
        if attio:
            break
    if not attio and name_lower:
        attio = lookups["attio_by_name"].get(name_lower)
    if attio:
        if "attio" not in person["sources"]:
            person["sources"].append("attio")
        if not person["organization"] and attio.get("company_name"):
            person["organization"] = attio["company_name"]
        if not person["linkedin_url"] and attio.get("linkedin"):
            person["linkedin_url"] = attio["linkedin"]
        if attio.get("last_interaction"):
            dates_seen.append(attio["last_interaction"])

        if attio.get("notes_count", 0) > 0:
            interaction_parts.append(f"{attio['notes_count']} attio notes")
        if attio.get("meetings_count", 0) > 0 and not any(
            "attio" in p and "meeting" in p for p in interaction_parts
        ):
            interaction_parts.append(f"{attio['meetings_count']} attio meetings")


    docu = None
    for em in all_emails_for_lookup:
        docu = lookups["docusign_by_email"].get(em)
        if docu:
            break
    if not docu and name_lower:
        docu = lookups["docusign_by_name"].get(name_lower)
    if docu:
        if "docusign" not in person["sources"]:
            person["sources"].append("docusign")
        if docu.get("contract_count", 0) > 0 and not any(
            "docusign" in p for p in interaction_parts
        ):
            interaction_parts.append(f"{docu['contract_count']} docusign contracts")
        if docu.get("last_contract"):
            dates_seen.append(docu["last_contract"])


    if name_lower:
        wa = lookups["whatsapp_by_name"].get(name_lower)
        if wa:
            if "whatsapp" not in person["sources"]:
                person["sources"].append("whatsapp")
            if not person["phone"] and wa.get("phone"):
                person["phone"] = wa["phone"]
            if wa.get("message_count", 0) > 0 and not any(
                "whatsapp" in p for p in interaction_parts
            ):
                interaction_parts.append(f"{wa['message_count']} whatsapp msgs")
            if wa.get("last_message"):
                dates_seen.append(wa["last_message"])


    if not person["sources"] and parsed["source_hint"] != "email":
        person["sources"].append(parsed["source_hint"])
    elif not person["sources"] and parsed["type"] == "email":
        person["sources"].append("email")



    valid_dates = [d for d in dates_seen if d and d != "None"]
    if valid_dates:
        person["last_seen"] = max(valid_dates)


    if interaction_parts:
        person["interaction_summary"] = ", ".join(interaction_parts)
    else:
        person["interaction_summary"] = "no recorded interaction"


    if person["organization"] and person["organization"].strip().lower() in ("", "nan", "none"):
        person["organization"] = None

    return person


def generate_match_explanation(reason, item):
    ""
    score_match = re.search(r"score=([0-9.]+)", reason)
    score_str = f"{float(score_match.group(1)):.0f}" if score_match else "?"

    keys = item.get("keys", item.get("emails", []))

    if reason.startswith("same_domain_uncertain"):

        domains = set()
        for k in keys:
            if "@" in k:
                domains.add(k.split("@")[1])
        domain_str = ", ".join(sorted(domains)) if domains else "?"
        return f"Same email domain ({domain_str}), similar but not identical names"

    elif reason.startswith("fuzzy_name_new_sources_uncertain"):

        sources = []
        for k in keys:
            parsed = parse_key(k)
            sources.append(parsed["source_hint"])
        unique_sources = list(dict.fromkeys(sources))
        src_str = (
            " and ".join(unique_sources) if len(unique_sources) <= 3 else ", ".join(unique_sources)
        )
        return f"Similar names (score {score_str}%) from different sources ({src_str})"

    elif reason.startswith("fuzzy_name_uncertain"):
        return f"Very similar names (score {score_str}%), found in different sources"

    elif reason.startswith("single_word_name_partial"):
        return "Partial name (single word) matches"

    else:
        return f"Automatic match: {reason}"


def derive_primary_source(key):
    ""









    if key.startswith("nameonly:"):
        parts = key.split(":", 2)
        if len(parts) >= 2:
            return parts[1]
        return "unknown"
    if "@" in key:
        return "email"
    return "unknown"


def _normalize_name(name):
    ""
    if not name:
        return ""

    cleaned = re.sub(r"\s*[\|]\s*.*$", "", name)

    cleaned = re.sub(r"\s+(?:from|at|da|di)\s+\S.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _split_name_parts(name):
    ""


    normalized = _normalize_name(name)
    parts = normalized.lower().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[-1])


def levenshtein(a, b):
    ""
    if len(a) < len(b):
        return levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (ca != cb)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]



DIMINUTIVES = {
    "ale": ["alessandro", "alessandra"],
    "gio": ["giovanni", "giorgio", "giovanna"],
    "fra": ["francesco", "francesca"],
    "fede": ["federico", "federica"],
    "vale": ["valentina", "valentino", "valerio", "valeria"],
    "michi": ["michele", "michela"],
    "simo": ["simone", "simona"],
    "anto": ["antonio", "antonella", "antonino"],
    "nello": ["antonello", "aniello"],
    "luca": ["gianluca"],
    "edo": ["edoardo"],
    "beppe": ["giuseppe"],
    "peppe": ["giuseppe"],
    "peppo": ["giuseppe"],
    "ste": ["stefano", "stefania"],
    "matte": ["matteo"],
    "dani": ["daniele", "daniela"],
    "cri": ["cristiano", "cristiana", "cristina"],
    "roby": ["roberto", "roberta"],
    "eli": ["elisabetta", "eliana"],
    "gabri": ["gabriele", "gabriella"],
    "max": ["massimiliano", "massimo"],
    "manu": ["emanuele", "emanuela", "manuel"],
    "tom": ["tommaso"],
    "lele": ["emanuele", "gabriele"],
    "ricky": ["riccardo", "enrico"],
    "chicco": ["enrico", "federico"],
    "lory": ["lorenzo", "lorena"],
    "pat": ["patrizia", "patrizio"],
    "ila": ["ilaria"],
    "cla": ["claudia", "claudio"],
    "andre": ["andrea"],
    "dave": ["davide"],
    "miky": ["michele"],
    "bea": ["beatrice"],
    "gi": ["giovanni"],
    "toni": ["antonio"],
    "lello": ["raffaele"],
    "pino": ["giuseppe"],
}


_REVERSE_DIMINUTIVES = defaultdict(list)
for _dim, _fulls in DIMINUTIVES.items():
    for _full in _fulls:
        _REVERSE_DIMINUTIVES[_full].append(_dim)


def check_diminutive(name_a_lower, name_b_lower):
    ""



    if name_a_lower in DIMINUTIVES:
        if name_b_lower in DIMINUTIVES[name_a_lower]:
            return True, f"Possible diminutive: {name_a_lower} = {name_b_lower}"

    if name_b_lower in DIMINUTIVES:
        if name_a_lower in DIMINUTIVES[name_b_lower]:
            return True, f"Possible diminutive: {name_b_lower} = {name_a_lower}"

    fulls_a = DIMINUTIVES.get(name_a_lower, [])
    fulls_b = DIMINUTIVES.get(name_b_lower, [])
    if fulls_a and fulls_b:
        common = set(fulls_a) & set(fulls_b)
        if common:
            return (
                True,
                f"Possibly the same diminutive: {name_a_lower} and {name_b_lower} = {list(common)[0]}",
            )


    dims_a = _REVERSE_DIMINUTIVES.get(name_a_lower, [])
    dims_b = _REVERSE_DIMINUTIVES.get(name_b_lower, [])

    return False, None


def analyze_email_pattern(email_local, other_first, other_last):
    ""









    if not email_local or not other_first or not other_last:
        return False, None
    if len(other_first) < 2 or len(other_last) < 2:
        return False, None

    local = email_local.lower().strip()
    first = other_first.lower().strip()
    last = other_last.lower().strip()


    for sep in [".", "_", "-"]:
        if sep in local:
            parts = local.split(sep, 1)
            if len(parts) == 2:
                lp_first, lp_last = parts
                if lp_first == first and lp_last == last:
                    return True, f"Email {local} = {first}.{last} pattern"

                if lp_first == last and lp_last == first:
                    return True, f"Email {local} = {last}.{first} pattern"


    if len(local) >= 2:
        if local[0] == first[0] and local[1:] == last:
            return True, f"Email {local} = {first[0]}+{last} pattern"


    if len(local) >= 2:
        if local[-1] == first[0] and local[:-1] == last:
            return True, f"Email {local} = {last}+{first[0]} pattern"


    if len(local) >= 2:
        if local[-1] == last[0] and local[:-1] == first:
            return True, f"Email {local} = {first}+{last[0]} pattern"


    if local == first + last:
        return True, f"Email {local} = {first}{last} pattern"
    if local == last + first:
        return True, f"Email {local} = {last}{first} pattern"

    return False, None


def _jaro_similarity(s1, s2):
    ""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3


def _jaro_winkler(s1, s2, p=0.1):
    ""
    jaro = _jaro_similarity(s1, s2)
    prefix_len = 0
    for i in range(min(len(s1), len(s2), 4)):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break
    return jaro + prefix_len * p * (1 - jaro)


def _parse_date_safe(date_str):
    ""
    if not date_str or date_str in ("None", "NaT", "nan"):
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _email_local_part(key):
    ""
    if "@" in key:
        return key.split("@")[0].lower()
    return None


def compute_signals(item):
    ""






    persons = item.get("persons", [])
    if len(persons) < 2:
        return [], "Single person, no comparison"

    signals = []


    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            pa, pb = persons[i], persons[j]
            _compute_pair_signals(pa, pb, signals)


    verdict = _generate_verdict(signals, persons)

    return signals, verdict


def _compute_pair_signals(pa, pb, signals):
    ""
    name_a = pa.get("name", "")
    name_b = pb.get("name", "")
    key_a = pa.get("key", "")
    key_b = pb.get("key", "")




    first_a, last_a = _split_name_parts(name_a)
    first_b, last_b = _split_name_parts(name_b)


    norm_a = _normalize_name(name_a).lower()
    norm_b = _normalize_name(name_b).lower()
    if norm_a and len(norm_a.split()) == 1:
        signals.append(
            {
                "type": "neutral",
                "category": "name",
                "text": f"Single-word name: {_normalize_name(name_a)}",
                "weight": 0.3,
            }
        )
    if norm_b and len(norm_b.split()) == 1:
        signals.append(
            {
                "type": "neutral",
                "category": "name",
                "text": f"Single-word name: {_normalize_name(name_b)}",
                "weight": 0.3,
            }
        )


    surname_analysis = None
    if last_a and last_b:
        surname_edit_dist = levenshtein(last_a, last_b)
        surname_contained = (last_a in last_b or last_b in last_a) and last_a != last_b

        if surname_edit_dist == 0:
            surname_analysis = {
                "surnameA": last_a.title(),
                "surnameB": last_b.title(),
                "edit_distance": 0,
                "assessment": "identici",
            }
        elif surname_contained:
            shorter = last_a if len(last_a) <= len(last_b) else last_b
            longer = last_b if len(last_a) <= len(last_b) else last_a
            surname_analysis = {
                "surnameA": last_a.title(),
                "surnameB": last_b.title(),
                "edit_distance": surname_edit_dist,
                "assessment": f"contenuto ({shorter.title()} in {longer.title()})",
            }
        elif surname_edit_dist == 1:
            surname_analysis = {
                "surnameA": last_a.title(),
                "surnameB": last_b.title(),
                "edit_distance": 1,
                "assessment": "quasi_identico",
            }
        elif surname_edit_dist == 2:
            surname_analysis = {
                "surnameA": last_a.title(),
                "surnameB": last_b.title(),
                "edit_distance": 2,
                "assessment": "simile",
            }
        else:
            surname_analysis = {
                "surnameA": last_a.title(),
                "surnameB": last_b.title(),
                "edit_distance": surname_edit_dist,
                "assessment": "diversi",
            }


    pa["_surname_analysis"] = surname_analysis

    if first_a and first_b:

        if norm_a == norm_b:
            signals.append(
                {
                    "type": "positive",
                    "category": "name",
                    "text": f"Identical name: {_normalize_name(name_a)}",
                    "weight": 1.0,
                }
            )
        else:

            if first_a == first_b:
                if last_a and last_b:
                    surname_ed = levenshtein(last_a, last_b)
                    surname_contained = (last_a in last_b or last_b in last_a) and last_a != last_b

                    if surname_ed == 0:
                        signals.append(
                            {
                                "type": "positive",
                                "category": "name",
                                "text": f"Same exact surname: {first_a.title()} {last_a.title()}",
                                "weight": 0.8,
                            }
                        )
                    elif surname_ed == 1:
                        signals.append(
                            {
                                "type": "positive",
                                "category": "name",
                                "text": f"Nearly identical surname (1 different letter): {last_a.title()} vs {last_b.title()}",
                                "weight": 0.7,
                            }
                        )
                    elif surname_ed == 2:
                        signals.append(
                            {
                                "type": "neutral",
                                "category": "name",
                                "text": f"Similar surname (2 different letters): {last_a.title()} vs {last_b.title()}",
                                "weight": 0.5,
                            }
                        )
                    elif surname_contained:
                        shorter = last_a if len(last_a) <= len(last_b) else last_b
                        longer = last_b if len(last_a) <= len(last_b) else last_a
                        signals.append(
                            {
                                "type": "positive",
                                "category": "name",
                                "text": f"Surname contained: {shorter.title()} in {longer.title()}",
                                "weight": 0.6,
                            }
                        )
                    else:
                        signals.append(
                            {
                                "type": "negative",
                                "category": "name",
                                "text": f"Same first name ({first_a.title()}), different surname: {last_a.title()} vs {last_b.title()} (edit dist={surname_ed})",
                                "weight": 0.6,
                            }
                        )
                else:
                    signals.append(
                        {
                            "type": "positive",
                            "category": "name",
                            "text": f"Same first name: {first_a.title()}",
                            "weight": 0.6,
                        }
                    )

            elif last_a and last_b and last_a == last_b and first_a != first_b:
                signals.append(
                    {
                        "type": "positive",
                        "category": "name",
                        "text": f"Same surname: {last_a.title()}",
                        "weight": 0.5,
                    }
                )
                signals.append(
                    {
                        "type": "negative",
                        "category": "name",
                        "text": f"Different first names: {first_a.title()} vs {first_b.title()}",
                        "weight": 0.6,
                    }
                )

            elif last_a and last_b and first_a != first_b:
                surname_ed = levenshtein(last_a, last_b)
                surname_contained = (last_a in last_b or last_b in last_a) and last_a != last_b

                if surname_ed <= 1:
                    signals.append(
                        {
                            "type": "neutral",
                            "category": "name",
                            "text": f"Nearly identical surname ({last_a.title()} vs {last_b.title()}) but different first names ({first_a.title()} vs {first_b.title()})",
                            "weight": 0.4,
                        }
                    )
                elif surname_contained:
                    signals.append(
                        {
                            "type": "neutral",
                            "category": "name",
                            "text": f"Surname contained ({last_a.title()}/{last_b.title()}) but different first names ({first_a.title()} vs {first_b.title()})",
                            "weight": 0.3,
                        }
                    )
                else:
                    signals.append(
                        {
                            "type": "negative",
                            "category": "name",
                            "text": f"Completely different names: {_normalize_name(name_a)} vs {_normalize_name(name_b)}",
                            "weight": 0.8,
                        }
                    )


            if norm_a and norm_b and norm_a != norm_b:
                if norm_a in norm_b or norm_b in norm_a:
                    short = (
                        _normalize_name(name_a)
                        if len(norm_a) <= len(norm_b)
                        else _normalize_name(name_b)
                    )
                    long_name = (
                        _normalize_name(name_b)
                        if len(norm_a) <= len(norm_b)
                        else _normalize_name(name_a)
                    )
                    signals.append(
                        {
                            "type": "positive",
                            "category": "name",
                            "text": f"Name contained: {short} in {long_name}",
                            "weight": 0.7,
                        }
                    )


    if first_a and first_b and first_a != first_b:
        is_dim, dim_desc = check_diminutive(first_a, first_b)
        if is_dim:
            signals.append(
                {
                    "type": "positive",
                    "category": "name",
                    "text": dim_desc,
                    "weight": 0.5,
                }
            )


    local_a = _email_local_part(key_a)
    local_b = _email_local_part(key_b)

    if local_a and last_b and len(last_b) >= 3 and last_b in local_a:
        signals.append(
            {
                "type": "positive",
                "category": "name",
                "text": f"Email contains surname: {local_a} contains {last_b.title()}",
                "weight": 0.6,
            }
        )
    if local_b and last_a and len(last_a) >= 3 and last_a in local_b:
        signals.append(
            {
                "type": "positive",
                "category": "name",
                "text": f"Email contains surname: {local_b} contains {last_a.title()}",
                "weight": 0.6,
            }
        )


    if local_a and first_b and len(first_b) >= 3 and first_b in local_a:
        signals.append(
            {
                "type": "neutral",
                "category": "name",
                "text": f"Email contains first name: {local_a} contains {first_b.title()}",
                "weight": 0.4,
            }
        )
    if local_b and first_a and len(first_a) >= 3 and first_a in local_b:
        signals.append(
            {
                "type": "neutral",
                "category": "name",
                "text": f"Email contains first name: {local_b} contains {first_a.title()}",
                "weight": 0.4,
            }
        )



    if local_a and first_b and last_b:
        ep_match, ep_desc = analyze_email_pattern(local_a, first_b, last_b)
        if ep_match:
            signals.append(
                {
                    "type": "positive",
                    "category": "email_pattern",
                    "text": f"Email {local_a} matches the name pattern of {_normalize_name(name_b)}: {ep_desc}",
                    "weight": 0.7,
                }
            )

    if local_b and first_a and last_a:
        ep_match, ep_desc = analyze_email_pattern(local_b, first_a, last_a)
        if ep_match:
            signals.append(
                {
                    "type": "positive",
                    "category": "email_pattern",
                    "text": f"Email {local_b} matches the name pattern of {_normalize_name(name_a)}: {ep_desc}",
                    "weight": 0.7,
                }
            )




    domain_a = pa.get("domain")
    domain_b = pb.get("domain")

    if domain_a and domain_b:
        if domain_a == domain_b:
            signals.append(
                {
                    "type": "positive",
                    "category": "email",
                    "text": f"Same domain: {domain_a}",
                    "weight": 0.7,
                }
            )
        else:
            signals.append(
                {
                    "type": "negative",
                    "category": "email",
                    "text": f"Different domains: {domain_a} vs {domain_b}",
                    "weight": 0.5,
                }
            )


    if local_a and local_b:
        sim = _jaro_winkler(local_a, local_b)
        if sim >= 0.9:
            signals.append(
                {
                    "type": "positive",
                    "category": "email",
                    "text": f"Email local parts very similar: {local_a} ~ {local_b} (JW={sim:.2f})",
                    "weight": 0.7,
                }
            )
        elif sim >= 0.8:
            signals.append(
                {
                    "type": "neutral",
                    "category": "email",
                    "text": f"Email local parts similar: {local_a} ~ {local_b} (JW={sim:.2f})",
                    "weight": 0.4,
                }
            )


    has_email_a = "@" in key_a
    has_email_b = "@" in key_b
    if has_email_a != has_email_b:
        who_has = _normalize_name(name_a) if has_email_a else _normalize_name(name_b)
        who_no = _normalize_name(name_b) if has_email_a else _normalize_name(name_a)
        signals.append(
            {
                "type": "neutral",
                "category": "email",
                "text": f"Only {who_has} has email, {who_no} has only a name key",
                "weight": 0.3,
            }
        )




    phone_a = pa.get("phone")
    phone_b = pb.get("phone")
    li_a = pa.get("linkedin_url")
    li_b = pb.get("linkedin_url")


    if phone_a and phone_b:
        if phone_a == phone_b:
            signals.append(
                {
                    "type": "positive",
                    "category": "identity",
                    "text": f"Same phone: {phone_a}",
                    "weight": 0.9,
                }
            )

            if first_a and first_b and first_a != first_b:
                signals.append(
                    {
                        "type": "neutral",
                        "category": "identity",
                        "text": f"Same phone but different names: {_normalize_name(name_a)} vs {_normalize_name(name_b)}",
                        "weight": 0.5,
                    }
                )
        else:
            signals.append(
                {
                    "type": "negative",
                    "category": "identity",
                    "text": f"Different phones: {phone_a} vs {phone_b}",
                    "weight": 0.6,
                }
            )


    if li_a and li_b:

        li_a_clean = li_a.rstrip("/").lower()
        li_b_clean = li_b.rstrip("/").lower()
        if li_a_clean == li_b_clean:
            signals.append(
                {
                    "type": "positive",
                    "category": "identity",
                    "text": "Same LinkedIn profile",
                    "weight": 1.0,
                }
            )
        else:
            signals.append(
                {
                    "type": "negative",
                    "category": "identity",
                    "text": "Different LinkedIn profiles",
                    "weight": 0.85,
                }
            )




    org_a = pa.get("organization")
    org_b = pb.get("organization")

    if org_a and org_b:
        if org_a.lower().strip() == org_b.lower().strip():
            signals.append(
                {
                    "type": "positive",
                    "category": "organization",
                    "text": f"Same company: {org_a}",
                    "weight": 0.6,
                }
            )
        else:
            signals.append(
                {
                    "type": "negative",
                    "category": "organization",
                    "text": f"Different companies: {org_a} vs {org_b}",
                    "weight": 0.5,
                }
            )
    elif org_a or org_b:
        org_present = org_a or org_b
        who_has = _normalize_name(name_a) if org_a else _normalize_name(name_b)
        signals.append(
            {
                "type": "neutral",
                "category": "organization",
                "text": f"Only {who_has} has a company: {org_present}",
                "weight": 0.2,
            }
        )


    if domain_a and org_b:
        org_b_clean = re.sub(r"[^a-z0-9]", "", org_b.lower())
        domain_a_base = domain_a.split(".")[0].lower()
        if (
            org_b_clean
            and domain_a_base
            and (org_b_clean in domain_a_base or domain_a_base in org_b_clean)
        ):
            signals.append(
                {
                    "type": "positive",
                    "category": "organization",
                    "text": f"Email domain {domain_a} matches company {org_b}",
                    "weight": 0.5,
                }
            )
    if domain_b and org_a:
        org_a_clean = re.sub(r"[^a-z0-9]", "", org_a.lower())
        domain_b_base = domain_b.split(".")[0].lower()
        if (
            org_a_clean
            and domain_b_base
            and (org_a_clean in domain_b_base or domain_b_base in org_a_clean)
        ):
            signals.append(
                {
                    "type": "positive",
                    "category": "organization",
                    "text": f"Email domain {domain_b} matches company {org_a}",
                    "weight": 0.5,
                }
            )




    last_a = _parse_date_safe(pa.get("last_seen"))
    last_b = _parse_date_safe(pb.get("last_seen"))

    if last_a and last_b:
        delta_days = abs((last_a - last_b).days)
        if delta_days <= 30:
            signals.append(
                {
                    "type": "positive",
                    "category": "temporal",
                    "text": f"Last contact close together: {delta_days}d apart",
                    "weight": 0.4,
                }
            )
        elif delta_days <= 180:
            signals.append(
                {
                    "type": "neutral",
                    "category": "temporal",
                    "text": f"Last contact within 6 months: {delta_days}d apart",
                    "weight": 0.2,
                }
            )
        elif delta_days > 365:
            years = delta_days / 365
            signals.append(
                {
                    "type": "negative",
                    "category": "temporal",
                    "text": f"Last contact far apart: {years:.1f} years apart",
                    "weight": 0.4,
                }
            )
    elif (last_a is None) != (last_b is None):

        who = _normalize_name(name_a) if last_a else _normalize_name(name_b)
        signals.append(
            {
                "type": "neutral",
                "category": "temporal",
                "text": f"Only {who} has a last-contact date",
                "weight": 0.1,
            }
        )




    email_count_a = pa.get("email_count", 0) or 0
    email_count_b = pb.get("email_count", 0) or 0
    interaction_a = pa.get("interaction_summary", "")
    interaction_b = pb.get("interaction_summary", "")
    no_interaction_a = not interaction_a or interaction_a == "no recorded interaction"
    no_interaction_b = not interaction_b or interaction_b == "no recorded interaction"

    if no_interaction_a and not no_interaction_b:
        signals.append(
            {
                "type": "neutral",
                "category": "interaction",
                "text": f"No interaction for {_normalize_name(name_a)}",
                "weight": 0.3,
            }
        )
    elif no_interaction_b and not no_interaction_a:
        signals.append(
            {
                "type": "neutral",
                "category": "interaction",
                "text": f"No interaction for {_normalize_name(name_b)}",
                "weight": 0.3,
            }
        )

    total_interactions_a = email_count_a
    total_interactions_b = email_count_b

    for part in (interaction_a or "").split(", "):
        m = re.match(r"(\d+)\s", part)
        if m:
            total_interactions_a += int(m.group(1))
    for part in (interaction_b or "").split(", "):
        m = re.match(r"(\d+)\s", part)
        if m:
            total_interactions_b += int(m.group(1))

    if total_interactions_a > 10 and total_interactions_b > 10:
        signals.append(
            {
                "type": "neutral",
                "category": "interaction",
                "text": f"Both with significant interactions ({total_interactions_a} and {total_interactions_b})",
                "weight": 0.3,
            }
        )


    sources_a = set(pa.get("sources", []))
    sources_b = set(pb.get("sources", []))
    shared_sources = sources_a & sources_b
    if shared_sources:
        signals.append(
            {
                "type": "positive",
                "category": "interaction",
                "text": f"Both present in: {', '.join(sorted(shared_sources))}",
                "weight": min(0.3 + len(shared_sources) * 0.1, 0.7),
            }
        )


def _generate_verdict(signals, persons):
    ""
    if not signals:
        return "No signal computed"


    sorted_signals = sorted(signals, key=lambda s: s["weight"], reverse=True)


    top_parts = []
    seen_categories = set()
    for sig in sorted_signals:

        cat_key = (sig["category"], sig["type"])
        if len(top_parts) >= 4:
            break

        text = sig["text"]

        for prefix in ["Identical name: ", "Completely different names: "]:
            if text.startswith(prefix):
                break
        top_parts.append(text)
        seen_categories.add(cat_key)

    if not top_parts:
        return "No significant signal"

    return "; ".join(top_parts)


def compute_match_score(signals):
    ""







    raw = 50.0
    for sig in signals:
        if sig["type"] == "positive":
            raw += sig["weight"] * 10
        elif sig["type"] == "negative":
            raw -= sig["weight"] * 15
        elif sig["type"] == "neutral":
            raw += sig["weight"] * 2


    return max(0, min(100, round(raw)))


def compute_recommendation(match_score):
    ""
    if match_score >= 70:
        return "Probably the same person"
    elif match_score >= 40:
        return "Uncertain, to verify"
    else:
        return "Probably different people"


def compute_auto_decision(enriched_item):
    ""














    persons = enriched_item.get("persons", [])
    signals = enriched_item.get("signals", [])
    confidence = enriched_item.get("confidence", 0)

    if len(persons) < 2:
        return None, None

    has_negative = any(s["type"] == "negative" for s in signals)


    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            pa, pb = persons[i], persons[j]

            name_a = pa.get("name", "")
            name_b = pb.get("name", "")
            first_a, last_a = _split_name_parts(name_a)
            first_b, last_b = _split_name_parts(name_b)

            li_a = (pa.get("linkedin_url") or "").rstrip("/").lower()
            li_b = (pb.get("linkedin_url") or "").rstrip("/").lower()
            phone_a = pa.get("phone")
            phone_b = pb.get("phone")
            domain_a = pa.get("domain")
            domain_b = pb.get("domain")
            org_a = (pa.get("organization") or "").strip().lower()
            org_b = (pb.get("organization") or "").strip().lower()




            if li_a and li_b and li_a == li_b:
                return "merge", "Same LinkedIn profile"


            if phone_a and phone_b and phone_a == phone_b:
                if first_a and first_b and first_a == first_b:
                    return "merge", "Same phone and name"


            if domain_a and domain_b and domain_a == domain_b:
                if first_a and first_b and first_a == first_b:
                    if last_a and last_b:
                        surname_ed = levenshtein(last_a, last_b)
                        if surname_ed <= 1:
                            return "merge", "Same domain, nearly identical surname, same first name"


            if confidence >= 0.92 and not has_negative:
                return "merge", "Very high confidence, no conflict"




            if li_a and li_b and li_a != li_b:
                return "reject", "Different LinkedIn profiles"


            if first_a and first_b and last_a and last_b:
                first_ed = levenshtein(first_a, first_b)
                surname_ed = levenshtein(last_a, last_b)
                has_same_phone = phone_a and phone_b and phone_a == phone_b
                has_same_li = li_a and li_b and li_a == li_b
                if first_ed >= 4 and surname_ed >= 4 and not has_same_phone and not has_same_li:
                    return "reject", "Completely different names, no shared identifier"


            if org_a and org_b and org_a != org_b:
                if first_a and first_b and first_a != first_b:

                    is_dim, _ = check_diminutive(first_a, first_b)
                    if not is_dim:
                        return "reject", "Different companies and different names"

    return None, None


def _extract_surname_analysis(enriched_item):
    ""
    for p in enriched_item.get("persons", []):
        sa = p.get("_surname_analysis")
        if sa:
            return sa
    return None


def _clean_internal_fields(enriched_item):
    ""
    for p in enriched_item.get("persons", []):
        p.pop("_surname_analysis", None)


def enrich_all(review_items, entity_map, lookups):
    ""
    enriched = []
    stats = {
        "total": len(review_items),
        "with_organization": 0,
        "with_linkedin": 0,
        "with_phone": 0,
        "with_multi_source": 0,
        "with_email_count_gt0": 0,
        "with_interaction_data": 0,
        "sources_distribution": defaultdict(int),
        "persons_total": 0,
        "persons_with_org": 0,
        "persons_enriched_from_merged": 0,
        "signals_total": 0,
        "signals_positive": 0,
        "signals_negative": 0,
        "signals_neutral": 0,
        "signals_by_category": defaultdict(int),

        "auto_merge": 0,
        "auto_reject": 0,
        "auto_pending": 0,
        "score_histogram": {
            "0-20": 0,
            "20-40": 0,
            "40-60": 0,
            "60-80": 0,
            "80-100": 0,
        },
    }

    for i, item in enumerate(review_items):
        keys = item.get("keys", item.get("emails", []))
        names = item.get("names", [])


        enriched_item = {
            "emails": [k for k in keys if "@" in k],
            "keys": keys,
            "names": names,
            "confidence": item["confidence"],
            "reason": item["reason"],
            "match_explanation": generate_match_explanation(item["reason"], item),
            "persons": [],
        }

        item_has_org = False
        item_has_linkedin = False
        item_has_phone = False
        item_has_multi_source = False
        item_has_email_count = False
        item_has_interactions = False


        for idx in range(len(keys)):
            key = keys[idx]

            name = names[idx] if idx < len(names) else (names[-1] if names else "")

            person = enrich_person(key, name, lookups, entity_map)
            person["primary_source"] = derive_primary_source(key)
            enriched_item["persons"].append(person)
            stats["persons_total"] += 1


            if person.get("organization"):
                stats["persons_with_org"] += 1
                item_has_org = True
            if person.get("linkedin_url"):
                item_has_linkedin = True
            if person.get("phone"):
                item_has_phone = True
            if len(person.get("sources", [])) > 1:
                item_has_multi_source = True
            if person.get("email_count", 0) > 0:
                item_has_email_count = True
            if (
                person.get("interaction_summary")
                and person["interaction_summary"] != "no recorded interaction"
            ):
                item_has_interactions = True

            for src in person.get("sources", []):
                stats["sources_distribution"][src] += 1


        item_signals, verdict = compute_signals(enriched_item)
        enriched_item["signals"] = item_signals
        enriched_item["verdict_summary"] = verdict


        match_score = compute_match_score(item_signals)
        enriched_item["match_score"] = match_score
        enriched_item["recommendation"] = compute_recommendation(match_score)

        auto_decision, auto_reason = compute_auto_decision(enriched_item)
        enriched_item["auto_decision"] = auto_decision
        enriched_item["auto_reason"] = auto_reason


        enriched_item["surname_analysis"] = _extract_surname_analysis(enriched_item)


        _clean_internal_fields(enriched_item)


        if auto_decision == "merge":
            stats["auto_merge"] += 1
        elif auto_decision == "reject":
            stats["auto_reject"] += 1
        else:
            stats["auto_pending"] += 1


        if match_score < 20:
            stats["score_histogram"]["0-20"] += 1
        elif match_score < 40:
            stats["score_histogram"]["20-40"] += 1
        elif match_score < 60:
            stats["score_histogram"]["40-60"] += 1
        elif match_score < 80:
            stats["score_histogram"]["60-80"] += 1
        else:
            stats["score_histogram"]["80-100"] += 1


        stats["signals_total"] += len(item_signals)
        for sig in item_signals:
            if sig["type"] == "positive":
                stats["signals_positive"] += 1
            elif sig["type"] == "negative":
                stats["signals_negative"] += 1
            else:
                stats["signals_neutral"] += 1
            stats["signals_by_category"][sig["category"]] += 1

        enriched.append(enriched_item)

        if item_has_org:
            stats["with_organization"] += 1
        if item_has_linkedin:
            stats["with_linkedin"] += 1
        if item_has_phone:
            stats["with_phone"] += 1
        if item_has_multi_source:
            stats["with_multi_source"] += 1
        if item_has_email_count:
            stats["with_email_count_gt0"] += 1
        if item_has_interactions:
            stats["with_interaction_data"] += 1

    return enriched, stats


def main():
    print("=" * 60)
    print("ENTITY REVIEW ENRICHMENT V2 (with auto-decision)")
    print("=" * 60)

    review_items, entity_map, dfs = load_data()
    print()

    print("Building lookup tables...")
    lookups = build_lookups(dfs)
    print()

    print("Enriching...")
    enriched, stats = enrich_all(review_items, entity_map, lookups)
    print()


    print(f"Saving to {OUTPUT_FILE}...")
    safe_write_json(OUTPUT_FILE, enriched)
    file_size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"  Wrote: {file_size_mb:.1f} MB")
    print()


    print("=" * 60)
    print("ENRICHMENT STATISTICS")
    print("=" * 60)
    print(f"  Total items:                  {stats['total']}")
    print(f"  Total people:                 {stats['persons_total']}")
    print(f"  People with organization:     {stats['persons_with_org']}")
    print()
    print(
        f"  Items with organization:      {stats['with_organization']} ({100 * stats['with_organization'] / stats['total']:.1f}%)"
    )
    print(
        f"  Items with LinkedIn URL:      {stats['with_linkedin']} ({100 * stats['with_linkedin'] / stats['total']:.1f}%)"
    )
    print(
        f"  Items with phone:             {stats['with_phone']} ({100 * stats['with_phone'] / stats['total']:.1f}%)"
    )
    print(
        f"  Items with multi-source:      {stats['with_multi_source']} ({100 * stats['with_multi_source'] / stats['total']:.1f}%)"
    )
    print(
        f"  Items with email count > 0:   {stats['with_email_count_gt0']} ({100 * stats['with_email_count_gt0'] / stats['total']:.1f}%)"
    )
    print(
        f"  Items with interaction data:  {stats['with_interaction_data']} ({100 * stats['with_interaction_data'] / stats['total']:.1f}%)"
    )
    print()
    print("  Source distribution across people:")
    for src, count in sorted(stats["sources_distribution"].items(), key=lambda x: -x[1]):
        print(f"    {src:20s}: {count}")
    print()


    print("=" * 60)
    print("SIGNAL STATISTICS")
    print("=" * 60)
    print(f"  Total signals:      {stats['signals_total']}")
    print(f"  Positive:           {stats['signals_positive']}")
    print(f"  Negative:           {stats['signals_negative']}")
    print(f"  Neutral:            {stats['signals_neutral']}")
    avg_signals = stats["signals_total"] / stats["total"] if stats["total"] > 0 else 0
    print(f"  Average per item:   {avg_signals:.1f}")
    print()
    print("  Distribution by category:")
    for cat, count in sorted(stats["signals_by_category"].items(), key=lambda x: -x[1]):
        print(f"    {cat:20s}: {count}")
    print()


    print("=" * 60)
    print("AUTO-DECISION")
    print("=" * 60)
    print(f"  Auto-MERGE:   {stats['auto_merge']}")
    print(f"  Auto-REJECT:  {stats['auto_reject']}")
    print(f"  Pending:      {stats['auto_pending']}")
    print()


    print("  match_score distribution:")
    total = stats["total"]
    for bucket, count in stats["score_histogram"].items():
        bar = "#" * int(count / max(total, 1) * 60)
        pct = 100 * count / total if total > 0 else 0
        print(f"    {bucket:>8s}: {count:4d} ({pct:5.1f}%) {bar}")
    print()


    auto_merge_items = [it for it in enriched if it.get("auto_decision") == "merge"]
    print(f"  AUTO-MERGE examples ({len(auto_merge_items)} total, showing max 3):")
    for item in auto_merge_items[:3]:
        names_str = " vs ".join(item.get("names", []))
        print(f"    - [{item['match_score']}] {names_str}")
        print(f"      Reason: {item.get('auto_reason', '-')}")
        print(f"      Keys: {', '.join(item.get('keys', []))}")
        if item.get("surname_analysis"):
            sa = item["surname_analysis"]
            print(
                f"      Surname: {sa['surnameA']} vs {sa['surnameB']} (edit_dist={sa['edit_distance']}, {sa['assessment']})"
            )
    print()


    auto_reject_items = [it for it in enriched if it.get("auto_decision") == "reject"]
    print(f"  AUTO-REJECT examples ({len(auto_reject_items)} total, showing max 3):")
    for item in auto_reject_items[:3]:
        names_str = " vs ".join(item.get("names", []))
        print(f"    - [{item['match_score']}] {names_str}")
        print(f"      Reason: {item.get('auto_reason', '-')}")
        print(f"      Keys: {', '.join(item.get('keys', []))}")
        if item.get("surname_analysis"):
            sa = item["surname_analysis"]
            print(
                f"      Surname: {sa['surnameA']} vs {sa['surnameB']} (edit_dist={sa['edit_distance']}, {sa['assessment']})"
            )
    print()


    print("=" * 60)
    print("ENRICHED EXAMPLES")
    print("=" * 60)
    examples = [0, 1, 50, 100]
    for idx in examples:
        if idx < len(enriched):
            item = enriched[idx]
            decision_str = (
                f" | AUTO: {item.get('auto_decision', '-')}" if item.get("auto_decision") else ""
            )
            print(
                f"\n--- Item {idx} (confidence={item['confidence']:.2f}, score={item.get('match_score', '?')}{decision_str}) ---"
            )
            print(f"  Reason: {item['reason'][:60]}")
            print(f"  Explanation: {item['match_explanation']}")
            print(f"  Verdict: {item.get('verdict_summary', '-')}")
            print(f"  Recommendation: {item.get('recommendation', '-')}")
            if item.get("surname_analysis"):
                sa = item["surname_analysis"]
                print(
                    f"  Surname: {sa['surnameA']} vs {sa['surnameB']} (edit_dist={sa['edit_distance']}, {sa['assessment']})"
                )
            for p in item["persons"]:
                org_str = f" [{p['organization']}]" if p.get("organization") else ""
                li_str = " (LinkedIn)" if p.get("linkedin_url") else ""
                phone_str = f" tel:{p['phone']}" if p.get("phone") else ""
                src_label = f" [{p.get('primary_source', '?')}]"
                print(f"  -> {p['name']}{org_str}{li_str}{phone_str}{src_label}")
                print(f"     Sources: {', '.join(p['sources'])}")
                print(f"     {p.get('interaction_summary', '-')}")
                if p.get("last_seen"):
                    print(f"     Last contact: {p['last_seen']}")

            sigs = item.get("signals", [])
            if sigs:
                print(f"  Signals ({len(sigs)}):")
                for sig in sorted(sigs, key=lambda s: -s["weight"])[:6]:
                    icon = (
                        "+"
                        if sig["type"] == "positive"
                        else ("-" if sig["type"] == "negative" else "~")
                    )
                    print(f"    [{icon}] [{sig['category']}] {sig['text']} (w={sig['weight']:.1f})")

    print()
    print("Done.")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-enrich-review", source="l3-enrich-review", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
