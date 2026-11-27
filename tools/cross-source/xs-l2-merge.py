#!/usr/bin/env python3
"""Cross-source merge: builds the single contact book (enriched/contacts-merged.parquet) from every source (email,
calendar, Plaud, Tactiq, Attio, the HR directory, LinkedIn, Slack, WhatsApp, iPhone and the generic plugin intake),
leaving out automated senders and noise, with the top contacts for the graph. Incremental with --incremental.
"""

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import plugin_intake  # noqa: E402
import rumore  # noqa: E402
from text_utils import (  # noqa: E402
    normalize_email,
    normalize_name_case,
    normalize_name_for_match,
    normalize_phone,
    phone_country_code,
)

from sbk_config import (
    ATTIO_PROCESSED_DIR as ATTIO_DIR,
)
from sbk_config import (
    CHATGPT_DIR,
    DATA_ROOT,
    DOCUSIGN_DIR,
    ENRICHED_DIR,
    EXPORTS_DIR,
    GDRIVE_DIR,
    INTERNAL_DOMAINS,
    IPHONE_DIR,
    LINKEDIN_DIR,
    NOISE_DOMAINS,
    NOISE_EMAIL_PREFIXES,
    NOISE_NAMES_PATTERNS,
    NOISE_NAMES_REGEX,
    NOISE_PREFIXES,
    NOISE_PREFIXES_PER_DOMAIN,
    NOTION_DIR,
    OWN_EMAILS,
    OWN_NAMES_NORMALIZED,
    PERSONIO_DIR,
    PERSONIO_PROCESSED_DIR,
    PLAUD_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    WHATSAPP_DIR,
    is_gibberish_name,
    safe_write_json,
    safe_write_parquet,
)

log = logging.getLogger("cross-merge")



MERGE_CHECKPOINT_FILE = ENRICHED_DIR / "merge-checkpoint.json"

DA_VERIFICARE_FILE = ENRICHED_DIR / "merge-da-verificare.jsonl"

VERIFICHE_FILE = DATA_ROOT / "system" / "merge-verifiche.json"



MERGE_SOURCE_FILES: dict[str, list[Path]] = {
    "email_contacts": [ENRICHED_DIR / "contacts.parquet"],
    "email_interactions": [ENRICHED_DIR / "interactions.parquet"],
    "calendar": [ENRICHED_DIR / "contacts-calendar.parquet"],
    "plaud": [PLAUD_DIR / "_calendar_crossref.json"],
    "tactiq": [TACTIQ_DIR / "contacts-tactiq.parquet"],
    "attio": [ATTIO_DIR / "contacts-attio.parquet"],




    "personio": [PERSONIO_PROCESSED_DIR / "employees.parquet"],
    "linkedin": [LINKEDIN_DIR / "contacts-linkedin.parquet"],
    "slack": [SLACK_DIR / "contacts-slack.parquet"],
    "whatsapp": [WHATSAPP_DIR / "contacts-whatsapp.parquet"],
    "docusign": [DOCUSIGN_DIR / "contacts-docusign.parquet"],
    "iphone": [IPHONE_DIR / "contacts-iphone.parquet"],
    "notion": [NOTION_DIR / "entities-notion.parquet"],
    "chatgpt": [CHATGPT_DIR / "conversations-classified.parquet"],
    "gdrive": [GDRIVE_DIR / "contacts-gdrive.parquet"],
    "entity_map": [ENRICHED_DIR / "entity-map.json"],

    "verifiche": [VERIFICHE_FILE],
    # Generic intake: every $DATA_ROOT/<plugin>/processed/plugin-*.parquet
    "plugins": plugin_intake.contact_files(DATA_ROOT) + plugin_intake.interaction_files(DATA_ROOT),
}


def _file_hash(path: Path) -> str:
    ""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_source_hashes() -> dict[str, str]:
    ""
    from concurrent.futures import ThreadPoolExecutor

    def _hash_source(item: tuple[str, list[Path]]) -> tuple[str, str]:
        name, paths = item
        combined = ""
        for p in paths:
            combined += _file_hash(p)
        return name, hashlib.sha256(combined.encode()).hexdigest() if combined else ""

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = pool.map(_hash_source, MERGE_SOURCE_FILES.items())
    return dict(results)


def _load_merge_checkpoint() -> dict:
    ""
    if MERGE_CHECKPOINT_FILE.exists():
        try:
            return json.loads(MERGE_CHECKPOINT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_merge_checkpoint(hashes: dict[str, str]):
    ""
    checkpoint = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source_hashes": hashes,
    }
    safe_write_json(MERGE_CHECKPOINT_FILE, checkpoint)
    log.info(f"Merge checkpoint saved: {MERGE_CHECKPOINT_FILE}")


def check_sources_changed() -> tuple[bool, list[str]]:
    ""



    checkpoint = _load_merge_checkpoint()
    prev_hashes = checkpoint.get("source_hashes", {})

    if not prev_hashes:
        return True, ["(no previous checkpoint)"]

    current_hashes = _compute_source_hashes()
    changed = []
    for name, h in current_hashes.items():
        if h != prev_hashes.get(name, ""):
            changed.append(name)

    return len(changed) > 0, changed





def is_automated_email(email: str) -> bool:
    ""















    if not email or not isinstance(email, str) or "@" not in email:
        return False



    tipo = rumore.tipi_mittenti().get(email.strip().lower())
    if tipo in rumore.TIPI_RAPPORTO:
        return False
    if tipo is not None and not rumore.conta_nei_punteggi(email):
        return True

    local = email.split("@")[0].lower()
    domain = email.split("@")[1].lower()


    if domain in INTERNAL_DOMAINS:
        return False



    if domain.startswith("noreply.") or local == "noreply":
        return True

    if domain.startswith("notification.") or local == "notification" or local == "notifications":
        return True

    if local.endswith("-noreply") or local.endswith("-no-reply"):
        return True

    if local in (
        "no-reply",
        "noreply",
        "do-not-reply",
        "donotreply",
        "do_not_reply",
        "do-not-respond",
    ):
        return True

    if "noreply" in local or "no-reply" in local or "no_reply" in local:
        return True


    if local == "newsletter" or local == "newsletters":
        return True


    if local == "billing":
        return True


    if local.startswith("mailer-daemon") or local == "mailer-daemon":
        return True

    return False


def is_exchange_artifact(email: str) -> bool:
    ""





    if not email:
        return False
    email_lower = email.lower()
    return any(
        pattern in email_lower
        for pattern in (
            "exchangelabs.com",
            "eurprd01.prod",
            "imceaex-",
            "imcea",
            ".prod.outlook.com",
        )
    )


def is_noise(email: str) -> bool:
    ""















    if not email or not isinstance(email, str):
        return True
    if email in OWN_EMAILS:
        return True

    local = email.split("@")[0] if "@" in email else ""
    domain = email.split("@")[1] if "@" in email else ""







    tipo = rumore.tipi_mittenti().get(email.strip().lower())
    if tipo in rumore.TIPI_RAPPORTO:
        return False
    if tipo in rumore.TIPI_RUMORE:
        return True



    if any(
        domain == noise or domain.endswith("." + noise) or ("." not in noise and noise in domain)
        for noise in NOISE_DOMAINS
    ):
        return True


    if domain in INTERNAL_DOMAINS:
        prefix = local.split(".")[0] if "." in local else local
        if prefix in NOISE_PREFIXES:
            return True


    if domain not in INTERNAL_DOMAINS and local in NOISE_EMAIL_PREFIXES:
        return True


    domain_prefixes = NOISE_PREFIXES_PER_DOMAIN.get(domain)
    if domain_prefixes and local in domain_prefixes:
        return True


    if local.startswith(
        (
            "noreply",
            "no-reply",
            "no_reply",
            "no.reply",
            "notifications",
            "mailer-daemon",
            "postmaster",
            "drive-shares",
            "comments-noreply",
            "calendar-notification",
        )
    ):
        return True
    if "docusign" in email:
        return True


    if any(
        pattern in domain for pattern in ("exchangelabs.com", "eurprd01.prod", ".prod.outlook.com")
    ):
        return True


    if local.startswith("imcea"):
        return True


    if len(local) > 40:
        return True
    if "unsubscribe" in local:
        return True


    if "=" in local:
        after_eq = local.split("=", 1)[1]
        if "." in after_eq:
            return True

    return False


def is_noise_name(name: str) -> bool:
    ""







    if not name or not isinstance(name, str):
        return False
    name_lower = name.strip().lower()
    if not name_lower:
        return False


    if any(pattern in name_lower for pattern in NOISE_NAMES_PATTERNS):
        return True


    if any(rx.search(name_lower) for rx in NOISE_NAMES_REGEX):
        return True


    if "@" in name_lower:
        return True


    if is_gibberish_name(name):
        return True

    return False


def is_own_name(name: str) -> bool:
    ""
    nn = normalize_name_for_match(name)
    return nn in OWN_NAMES_NORMALIZED


def clean_contacts_email(df):
    ""
    df = df.copy()
    if df.empty:
        # an empty object mask would select columns, not rows, and drop them all
        return df
    df["email"] = df["email"].apply(normalize_email)
    df = df[~df["email"].apply(is_noise)]
    return df


def clean_contacts_name(df):
    ""
    if df.empty:
        return df.copy()
    return df[~df["name"].apply(is_noise_name)].copy()





def build_linkedin_url_map(attio_df):
    ""





    url_map = {}
    if attio_df is None or "attio_linkedin" not in attio_df.columns:
        return url_map

    for _, row in attio_df.iterrows():
        li_url = str(row.get("attio_linkedin", "") or "").strip()
        email = str(row.get("email", "") or "").strip().lower()
        if li_url and email and "@" in email:

            norm_url = _normalize_linkedin_url(li_url)
            if norm_url and norm_url not in url_map:
                url_map[norm_url] = email

    log.info(f"LinkedIn URL map: {len(url_map)} Attio contacts with LinkedIn URL")
    return url_map


def _normalize_linkedin_url(url: str) -> str:
    ""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip().lower()

    url = url.split("?")[0]

    url = url.rstrip("/")

    url = re.sub(r"^https?://", "", url)

    url = re.sub(r"^www\.", "", url)
    return url




_GENERIC_EMAIL_PREFIXES = {
    "info",
    "admin",
    "support",
    "noreply",
    "no-reply",
    "no.reply",
    "contact",
    "hello",
    "help",
    "sales",
    "marketing",
    "billing",
    "office",
    "team",
    "staff",
    "hr",
    "jobs",
    "careers",
    "press",
    "media",
    "legal",
    "compliance",
    "security",
    "abuse",
    "postmaster",
    "webmaster",
    "notification",
    "notifications",
    "alert",
    "alerts",
    "news",
    "newsletter",
    "updates",
    "service",
    "services",
    "accounts",
    "account",
    "payments",
    "orders",
    "booking",
    "bookings",
    "reservations",
    "feedback",
    "enquiries",
    "inquiries",
    "ciao",
    "contatti",
    "segreteria",
    "amministrazione",
    "fatturazione",
    "comunicazione",
    "redazione",
    "direzione",
    "presidenza",
}


def extract_name_from_email(email: str) -> str:
    ""




    if not email or "@" not in str(email):
        return ""
    local = str(email).split("@")[0].lower().strip()
    if local in _GENERIC_EMAIL_PREFIXES:
        return ""
    if re.match(r"^\d+$", local):
        return ""
    parts = re.split(r"[.\-_]", local)
    parts = [p for p in parts if p and not re.match(r"^\d+$", p)]
    if not parts:
        return ""

    if len(parts) == 1:
        word = re.sub(r"\d+$", "", parts[0])
        if len(word) < 4:
            return ""
        return word.capitalize()

    name_parts = []
    for p in parts:
        p_clean = re.sub(r"\d+$", "", p)
        if len(p_clean) >= 2:
            name_parts.append(p_clean.capitalize())
    if len(name_parts) >= 2:
        return " ".join(name_parts)
    if len(name_parts) == 1 and len(name_parts[0]) >= 4:
        return name_parts[0]
    return ""


def build_phone_map(merged):
    ""



    phone_map = {}
    for _, row in merged.iterrows():
        phone = str(row.get("phone_primary", "") or "").strip()
        email = str(row.get("email", "") or "").strip().lower()
        if phone and email and "@" in email:
            norm = normalize_phone(phone)
            if norm and norm not in phone_map:
                phone_map[norm] = email
    return phone_map





def load_email_data():
    ""
    contacts_path = ENRICHED_DIR / "contacts.parquet"
    interactions_path = ENRICHED_DIR / "interactions.parquet"

    if not contacts_path.exists():
        log.warning("No email contacts found")
        return None, None

    contacts = clean_contacts_email(pd.read_parquet(contacts_path))

    interactions = None
    if interactions_path.exists():
        interactions = pd.read_parquet(interactions_path)
        interactions["from_email"] = interactions["from_email"].apply(normalize_email)
        interactions["to_email"] = interactions["to_email"].apply(normalize_email)

    log.info(f"Email: {len(contacts)} contacts loaded")
    return contacts, interactions


def load_calendar_data():
    ""
    cal_path = ENRICHED_DIR / "contacts-calendar.parquet"

    if not cal_path.exists():
        log.warning("No calendar contacts found")
        return None

    cal = clean_contacts_email(pd.read_parquet(cal_path))

    log.info(f"Calendar: {len(cal)} contacts loaded")
    return cal


def load_plaud_data():
    ""
    crossref_path = PLAUD_DIR / "_calendar_crossref.json"

    if not crossref_path.exists():
        log.warning("No Plaud crossref found")
        return None

    with open(crossref_path) as f:
        data = json.load(f)

    matches = data.get("matches", [])
    log.info(f"Plaud: {len(matches)} matched meetings loaded")


    email_meetings = {}
    for match in matches:
        attendees = match.get("attendees", [])
        duration = match.get("plaud_duration_sec", 0)
        event_name = match.get("calendar_event", "")

        for att in attendees:

            email = _extract_email(att)
            if email and not is_noise(email) and email not in OWN_EMAILS:
                if email not in email_meetings:
                    email_meetings[email] = {
                        "plaud_meetings": 0,
                        "plaud_total_minutes": 0,
                        "plaud_events": [],
                    }
                email_meetings[email]["plaud_meetings"] += 1
                email_meetings[email]["plaud_total_minutes"] += duration / 60
                if event_name and event_name not in email_meetings[email]["plaud_events"]:
                    email_meetings[email]["plaud_events"].append(event_name)

    plaud_df = pd.DataFrame(
        [
            {
                "email": email,
                "plaud_meetings": info["plaud_meetings"],
                "plaud_total_minutes": round(info["plaud_total_minutes"], 1),
            }
            for email, info in email_meetings.items()
        ]
    )

    log.info(f"Plaud: {len(plaud_df)} unique contacts with recorded meetings")
    return plaud_df


def load_tactiq_data():
    ""
    tactiq_path = TACTIQ_DIR / "contacts-tactiq.parquet"

    if not tactiq_path.exists():
        log.warning("No Tactiq contacts found (run tactiq-enrich.py first)")
        return None

    df = pd.read_parquet(tactiq_path)

    df = df[df["email"].str.len() > 0].copy()
    df = clean_contacts_email(df)


    df = (
        df.groupby("email")
        .agg(
            tactiq_meetings=("tactiq_meetings", "sum"),
            tactiq_total_minutes=("tactiq_total_minutes", "sum"),
            tactiq_first_seen=("tactiq_first_seen", "min"),
            tactiq_last_seen=("tactiq_last_seen", "max"),
        )
        .reset_index()
    )


    for col in ["tactiq_first_seen", "tactiq_last_seen"]:
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    log.info(f"Tactiq: {len(df)} contacts with resolved email")
    return df


def load_attio_data():
    ""
    attio_path = ATTIO_DIR / "contacts-attio.parquet"

    if not attio_path.exists():
        log.warning("No Attio contacts found (run attio-enrich.py first)")
        return None

    df = clean_contacts_email(pd.read_parquet(attio_path))


    keep_cols = [
        "email",
        "name",
        "company_name",
        "job_title",
        "linkedin",
        "attio_relationship_score",
        "attio_connection_strength",
        "attio_connection_strength_num",
        "attio_sourcing_stage",
        "attio_notes_count",
        "attio_meetings_count",
        "attio_first_interaction",
        "attio_last_interaction",




        "attio_record_id",
        "attio_web_url",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].copy()


    df = df.rename(
        columns={
            "name": "attio_name",
            "company_name": "attio_company",
            "job_title": "attio_job_title",
            "linkedin": "attio_linkedin",
        }
    )


    for col in ["attio_first_interaction", "attio_last_interaction"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    log.info(f"Attio: {len(df)} contacts loaded")
    return df


def load_personio_data():
    ""



    parquet_path = PERSONIO_PROCESSED_DIR / "employees.parquet"
    json_path = PERSONIO_DIR / "employees-parsed.json"

    if parquet_path.exists():
        log.info("Personio: reading from L1 enriched parquet")
        try:
            cols_to_read = [
                "email",
                "name",
                "position",
                "status",
                "subcompany",






                "business_unit",
                "last_working_day",
                "termination_date",
                "hire_date",
            ]
            df_raw = pd.read_parquet(parquet_path)
            available = [c for c in cols_to_read if c in df_raw.columns]
            df_raw = df_raw[available].copy()

            rows = []
            for _, row in df_raw.iterrows():
                email = str(row.get("email", "") or "").strip().lower()
                if not email or "@" not in email:
                    continue
                if is_noise(email):
                    continue

                subcompany_raw = str(row.get("subcompany", "") or "")
                subcompany_name = subcompany_raw
                if subcompany_raw and "'name':" in subcompany_raw:
                    m = re.search(r"'name':\s*'([^']+)'", subcompany_raw)
                    if m:
                        subcompany_name = m.group(1).strip()

                status = str(row.get("status", "unknown") or "unknown").strip().lower()
                if status not in ("active", "terminated", "inactive"):
                    status = "unknown"

                rows.append(
                    {
                        "email": email,
                        "personio_name": str(row.get("name", "") or "").strip(),
                        "personio_position": str(row.get("position", "") or "").strip(),
                        "personio_status": status,
                        "personio_subcompany": subcompany_name,
                        "personio_business_unit": str(row.get("business_unit", "") or "").strip(),



                        "personio_last_working_day": str(
                            row.get("last_working_day", "") or ""
                        ).strip(),
                        "termination_date": str(row.get("termination_date", "") or "").strip(),
                        "hire_date": str(row.get("hire_date", "") or "").strip(),
                    }
                )

            if rows:
                df = pd.DataFrame(rows)
                log.info(f"Personio (parquet): {len(df)} employees loaded")
                status_counts = df["personio_status"].value_counts().to_dict()
                log.info(f"  Status distribution: {status_counts}")
                return df
        except Exception as exc:
            log.warning(f"Failed to read Personio parquet, falling back to JSON: {exc}")


    if not json_path.exists():
        log.warning("No Personio data found")
        return None

    with open(json_path) as f:
        employees = json.load(f)

    rows = []
    for emp in employees:
        email = emp.get("email", "").strip().lower()
        if not email or "@" not in email:
            continue
        if is_noise(email):
            continue

        subcompany_raw = emp.get("subcompany", "") or ""
        subcompany_name = ""
        if subcompany_raw and "'name':" in str(subcompany_raw):
            m = re.search(r"'name':\s*'([^']+)'", str(subcompany_raw))
            if m:
                subcompany_name = m.group(1).strip()

        raw_status = emp.get("status", "").strip().lower()
        termination_date_raw = emp.get("termination_date", "")
        termination_date = ""
        if termination_date_raw and isinstance(termination_date_raw, str):
            termination_date = termination_date_raw.strip()[:10]

        if raw_status == "active":
            status = "active"
        elif raw_status == "inactive":
            status = "terminated" if termination_date else "inactive"
        else:
            status = raw_status or "unknown"

        hire_date_raw = emp.get("hire_date", "")
        hire_date = ""
        if hire_date_raw and isinstance(hire_date_raw, str):
            hire_date = hire_date_raw.strip()[:10]

        rows.append(
            {
                "email": email,
                "personio_name": f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip(),
                "personio_position": emp.get("position", ""),
                "personio_status": status,
                "personio_subcompany": subcompany_name,
                "termination_date": termination_date,
                "hire_date": hire_date,
            }
        )

    if not rows:
        return None

    df = pd.DataFrame(rows)
    log.info(f"Personio (JSON fallback): {len(df)} employees loaded")
    status_counts = df["personio_status"].value_counts().to_dict()
    log.info(f"  Status distribution: {status_counts}")
    return df


def _extract_email(raw: str) -> str:
    ""
    if not raw:
        return ""

    raw = re.sub(r"^\(organizer\)\s*", "", raw)

    m = re.search(r"<([^>]+)>", raw)
    if m:
        return normalize_email(m.group(1))

    if "@" in raw:
        return normalize_email(raw.strip())
    return ""





def load_linkedin_data():
    ""
    path = LINKEDIN_DIR / "contacts-linkedin.parquet"
    if not path.exists():
        log.warning("No LinkedIn contacts found")
        return None

    df = pd.read_parquet(path)

    df = df[df["name"].notna() & (df["name"] != "")].copy()
    df = clean_contacts_name(df)
    df = df[~df["name"].apply(is_own_name)].copy()


    df["name_normalized"] = df["name"].apply(normalize_name_for_match)

    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"LinkedIn: {len(df)} contacts loaded")
    return df


def load_slack_data():
    ""
    path = SLACK_DIR / "contacts-slack.parquet"
    if not path.exists():
        log.warning("No Slack contacts found")
        return None

    df = pd.read_parquet(path)

    if "is_bot" in df.columns:
        df = df[~df["is_bot"]].copy()

    df = df[df["real_name"].notna() & (df["real_name"] != "")].copy()
    df = df[~df["real_name"].apply(is_noise_name)].copy()
    df = df[~df["real_name"].apply(is_own_name)].copy()


    df["name_normalized"] = df["real_name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"Slack: {len(df)} contacts loaded (non-bot, non-self)")
    return df


def load_whatsapp_data():
    ""
    path = WHATSAPP_DIR / "contacts-whatsapp.parquet"
    if not path.exists():
        log.warning("No WhatsApp contacts found")
        return None

    df = pd.read_parquet(path)
    df = df[df["name"].notna() & (df["name"] != "")].copy()
    df = clean_contacts_name(df)
    df = df[~df["name"].apply(is_own_name)].copy()

    df["name_normalized"] = df["name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"WhatsApp: {len(df)} contacts loaded")
    return df


def load_docusign_data():
    ""

    path = DOCUSIGN_DIR / "contacts-docusign.parquet"
    if not path.exists():
        log.warning("No DocuSign contacts found")
        return None

    df = pd.read_parquet(path)
    df = df[df["name"].notna() & (df["name"] != "")].copy()

    if "is_company" in df.columns:
        df = df[~df["is_company"]].copy()
    df = clean_contacts_name(df)
    df = df[~df["name"].apply(is_own_name)].copy()

    df["name_normalized"] = df["name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"DocuSign: {len(df)} contacts loaded (persons only)")
    return df










from sbk_config import ATTIO_SECONDA_CLASSE_PARQUET as SECONDA_CLASSE_PARQUET  # noqa: E402,F401
from sbk_config import (  # noqa: E402
    ATTIO_SECONDA_CLASSE_PATH,
    ENV_ATTIO_SECONDA_CLASSE,  # noqa: F401
    attio_seconda_classe_attiva,  # noqa: F401
)


def load_attio_seconda_classe_data():
    ""














    if not attio_seconda_classe_attiva():
        return None






    path = ATTIO_SECONDA_CLASSE_PATH
    if not path.exists():
        log.warning(
            "Attio contacts without email: flag on but %s does not exist "
            "(run at-l1-enrich.py --contacts-without-email)",
            path,
        )
        return None

    df = pd.read_parquet(path)
    df = df[df["name"].notna() & (df["name"] != "")].copy()
    df = clean_contacts_name(df)
    df = df[~df["name"].apply(is_own_name)].copy()

    df["name_normalized"] = df["name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"Attio second class: {len(df)} contacts without email loaded")
    return df


def load_iphone_data():
    ""
    path = IPHONE_DIR / "contacts-iphone.parquet"
    if not path.exists():
        log.warning("No iPhone contacts found")
        return None

    df = pd.read_parquet(path)
    df = df[df["name"].notna() & (df["name"] != "")].copy()
    df = clean_contacts_name(df)
    df = df[~df["name"].apply(is_own_name)].copy()


    if "name_normalized" not in df.columns or df["name_normalized"].isna().all():
        df["name_normalized"] = df["name"].apply(normalize_name_for_match)
    else:

        df["name_normalized"] = df["name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"iPhone: {len(df)} contacts loaded")
    return df


def load_notion_data():
    ""
    path = NOTION_DIR / "entities-notion.parquet"
    if not path.exists():
        log.warning("No Notion entities found")
        return None

    df = pd.read_parquet(path)

    df = df[df["entity_type"] == "person"].copy()
    df = df[df["entity_name"].notna() & (df["entity_name"] != "")].copy()
    df = df[~df["entity_name"].apply(is_noise_name)].copy()
    df = df[~df["entity_name"].apply(is_own_name)].copy()

    df["name_normalized"] = df["entity_name"].apply(normalize_name_for_match)
    df = df[df["name_normalized"].str.len() > 1].copy()

    log.info(f"Notion: {len(df)} person entities loaded")
    return df


def load_chatgpt_data():
    ""
    path = CHATGPT_DIR / "conversations-classified.parquet"
    if not path.exists():
        log.warning("No ChatGPT conversations found")
        return None

    df = pd.read_parquet(path)


    entity_counts = defaultdict(int)
    for entities in df["entities_mentioned"]:
        if isinstance(entities, list) or hasattr(entities, "__iter__"):
            for e in entities:
                if isinstance(e, str) and len(e) > 1:
                    entity_counts[e] += 1

    if not entity_counts:
        log.info("ChatGPT: 0 entity mentions found (empty)")
        return None

    rows = [{"entity_name": k, "chatgpt_mentions": v} for k, v in entity_counts.items()]
    result = pd.DataFrame(rows)
    result["name_normalized"] = result["entity_name"].apply(normalize_name_for_match)
    result = result[result["name_normalized"].str.len() > 1].copy()
    result = result[~result["entity_name"].apply(is_noise_name)].copy()
    result = result[~result["entity_name"].apply(is_own_name)].copy()

    log.info(f"ChatGPT: {len(result)} unique entity mentions loaded")
    return result


def load_gdrive_data():
    ""
    path = GDRIVE_DIR / "contacts-gdrive.parquet"
    if not path.exists():
        log.warning("No Google Drive contacts found")
        return None

    df = pd.read_parquet(path)
    if df.empty:
        return None


    df = df[df["email"].str.len() > 3].copy()
    df["email"] = df["email"].str.strip().str.lower()

    log.info(f"Google Drive: {len(df)} file owners loaded")
    return df





def build_name_index(merged: pd.DataFrame) -> dict:
    ""



    index = defaultdict(list)
    for idx, row in merged.iterrows():
        name = row.get("name", "")
        email = row.get("email", "")
        if not name or not isinstance(name, str) or len(name) < 2:
            continue
        nn = normalize_name_for_match(name)
        if nn and len(nn) > 1:
            index[nn].append({"idx": idx, "email": email, "name": name})
    return dict(index)


def find_best_match(query_name: str, name_index: dict, threshold: int = 82):
    ""








    qn = normalize_name_for_match(query_name)
    if not qn or len(qn) < 2:
        return None


    if qn in name_index:
        entries = name_index[qn]
        if len(entries) == 1:
            e = entries[0]
            return (e["idx"], e["email"], e["name"], 100)
        elif len(entries) > 1:

            return None


    qn_parts = qn.split()
    is_short = len(qn_parts) <= 1


    if is_short and len(qn) < 4:
        return None

    effective_threshold = 90 if is_short else threshold

    best_match = None
    best_score = 0
    matches_at_best = 0

    for nn, entries in name_index.items():
        score = fuzz.token_sort_ratio(qn, nn)
        if score >= effective_threshold:
            if score > best_score:
                best_score = score
                best_match = entries[0]
                matches_at_best = 1
            elif score == best_score:
                matches_at_best += 1


    if matches_at_best > 1:
        log.debug(
            "Ambiguous fuzzy match for '%s': %d contacts at score %d",
            query_name,
            matches_at_best,
            best_score,
        )
        return None

    if best_match and best_score >= effective_threshold:
        return (best_match["idx"], best_match["email"], best_match["name"], best_score)

    return None











SICURO = 99


def valuta_nome(query_name: str, name_index: dict, threshold: int = 82) -> dict:
    ""






    nessuno = {"esito": "nessuno", "voci": [], "punteggio": 0.0, "motivo": ""}
    qn = normalize_name_for_match(query_name)
    if not qn or len(qn) < 2:
        return nessuno
    una_parola = len(qn.split()) <= 1
    if qn in name_index:
        voci = list(name_index[qn])
        if len(voci) > 1:
            motivo = f"{len(voci)} contacts have the same name"
        elif una_parola:
            motivo = "single-word name"
        else:
            return {
                "esito": "aggancio",
                "voci": voci,
                "punteggio": 100.0,
                "motivo": "identical full name",
            }
        return {"esito": "candidati", "voci": voci, "punteggio": 100.0, "motivo": motivo}
    if una_parola and len(qn) < 4:
        return nessuno
    soglia = 90 if una_parola else threshold
    chiavi = list(name_index)
    trovati = process.extract(
        qn, chiavi, scorer=fuzz.token_sort_ratio, processor=None, score_cutoff=soglia, limit=None
    )
    if not trovati:
        return nessuno
    migliore = max(punteggio for _, punteggio, _ in trovati)

    voci = [
        v
        for _, punteggio, i in sorted(trovati, key=lambda t: t[2])
        if punteggio == migliore
        for v in name_index[chiavi[i]]
    ]
    if len(voci) > 1:
        motivo = f"similarity {migliore:.0f} out of 100 with {len(voci)} contacts"
    elif una_parola:
        motivo = f"single-word name, similarity {migliore:.0f} out of 100"
    elif migliore >= SICURO:
        return {
            "esito": "aggancio",
            "voci": voci,
            "punteggio": migliore,
            "motivo": "the same words",
        }
    else:
        motivo = f"similarity {migliore:.0f} out of 100, below the rule's {SICURO}"
    return {"esito": "candidati", "voci": voci, "punteggio": migliore, "motivo": motivo}


def carica_verifiche(percorso: Path | None = None) -> dict[tuple[str, str], dict]:
    ""



    try:
        righe = json.loads((percorso or VERIFICHE_FILE).read_text(encoding="utf-8")).get(
            "verifiche", []
        )
    except (OSError, ValueError, AttributeError):
        return {}
    out: dict[tuple[str, str], dict] = {}
    for r in righe if isinstance(righe, list) else []:
        if (
            not isinstance(r, dict)
            or not r.get("fonte")
            or not r.get("chiave")
            or not r.get("email")
        ):
            continue
        voce = out.setdefault((str(r["fonte"]), str(r["chiave"])), {"si": None, "no": set()})
        email = str(r["email"]).strip().lower()
        if r.get("esito") == "si":
            voce["si"] = email
            voce["no"].discard(email)
        elif r.get("esito") == "no":
            voce["no"].add(email)
            if voce["si"] == email:
                voce["si"] = None
    return out


def scrivi_da_verificare(casi: list[dict], percorso: Path | None = None) -> None:
    ""
    percorso = percorso or DA_VERIFICARE_FILE
    tmp = percorso.with_name(percorso.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for caso in casi:
            f.write(json.dumps(caso, ensure_ascii=False, default=str) + "\n")
    tmp.replace(percorso)


def _chiave_nome(nome) -> str:
    return "nome:" + normalize_name_for_match(str(nome or ""))


def _chiave_telefono(valore) -> str:
    valore = str(valore or "").strip()
    return (normalize_phone(valore) or "") if valore else ""





def merge_contacts_phase1(
    email_contacts,
    email_interactions,
    cal_contacts,
    plaud_df,
    tactiq_df=None,
    attio_df=None,
    personio_df=None,
):
    ""
    log.info("Phase 1: Merging email-keyed contacts...")


    if email_contacts is not None:
        merged = email_contacts[["email", "name", "domain", "first_seen", "last_seen"]].copy()
        merged = merged.rename(
            columns={
                "first_seen": "email_first_seen",
                "last_seen": "email_last_seen",
            }
        )
    else:
        merged = pd.DataFrame(
            columns=["email", "name", "domain", "email_first_seen", "email_last_seen"]
        )




    if email_interactions is not None:
        has_relation_type = "relation_type" in email_interactions.columns
        if has_relation_type:
            direct_interactions = email_interactions[
                email_interactions["relation_type"] == "direct"
            ]
        else:
            direct_interactions = email_interactions


        out_from_owner = (
            direct_interactions[
                direct_interactions["from_email"].isin(OWN_EMAILS)
                & ~direct_interactions["to_email"].apply(is_noise)
            ]
            .groupby("to_email")
            .agg(
                email_msgs_sent=("msg_count", "sum"),
                email_threads_sent=("thread_count", "sum"),
                email_last_sent=("last_date", "max"),
            )
            .reset_index()
            .rename(columns={"to_email": "email"})
        )


        in_to_owner = (
            direct_interactions[
                direct_interactions["to_email"].isin(OWN_EMAILS)
                & ~direct_interactions["from_email"].apply(is_noise)
            ]
            .groupby("from_email")
            .agg(
                email_msgs_recv=("msg_count", "sum"),
                email_threads_recv=("thread_count", "sum"),
                email_last_recv=("last_date", "max"),
            )
            .reset_index()
            .rename(columns={"from_email": "email"})
        )

        merged = merged.merge(out_from_owner, on="email", how="left")
        merged = merged.merge(in_to_owner, on="email", how="left")
    else:
        for col in [
            "email_msgs_sent",
            "email_threads_sent",
            "email_last_sent",
            "email_msgs_recv",
            "email_threads_recv",
            "email_last_recv",
        ]:
            merged[col] = 0


    for col in ["email_msgs_sent", "email_threads_sent", "email_msgs_recv", "email_threads_recv"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype(int)


    if cal_contacts is not None:
        cal_slim = cal_contacts[
            ["email", "name", "total_events", "as_organizer", "first_seen", "last_seen"]
        ].copy()
        cal_slim = cal_slim.rename(
            columns={
                "name": "cal_name",
                "total_events": "cal_events",
                "as_organizer": "cal_as_organizer",
                "first_seen": "cal_first_seen",
                "last_seen": "cal_last_seen",
            }
        )


        merged = merged.merge(cal_slim, on="email", how="outer")


        merged["name"] = merged["name"].fillna(merged.get("cal_name", ""))
        if "cal_name" in merged.columns:
            merged.drop(columns=["cal_name"], inplace=True)
    else:
        merged["cal_events"] = 0
        merged["cal_as_organizer"] = 0


    for col in ["cal_events", "cal_as_organizer"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype(int)


    if plaud_df is not None and len(plaud_df) > 0:
        merged = merged.merge(plaud_df, on="email", how="left")
    else:
        merged["plaud_meetings"] = 0
        merged["plaud_total_minutes"] = 0


    for col in ["plaud_meetings", "plaud_total_minutes"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    merged["plaud_meetings"] = merged["plaud_meetings"].astype(int)


    if tactiq_df is not None and len(tactiq_df) > 0:
        merged = merged.merge(tactiq_df, on="email", how="outer")
    else:
        merged["tactiq_meetings"] = 0
        merged["tactiq_total_minutes"] = 0


    for col in ["tactiq_meetings", "tactiq_total_minutes"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    merged["tactiq_meetings"] = merged["tactiq_meetings"].astype(int)


    if attio_df is not None and len(attio_df) > 0:
        merged = merged.merge(attio_df, on="email", how="outer")


        if "attio_name" in merged.columns:
            merged["name"] = merged["name"].fillna(merged["attio_name"])
    else:
        merged["attio_notes_count"] = 0
        merged["attio_meetings_count"] = 0
        merged["attio_connection_strength_num"] = 0


    for col in ["attio_notes_count", "attio_meetings_count", "attio_connection_strength_num"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)
    if "attio_notes_count" in merged.columns:
        merged["attio_notes_count"] = merged["attio_notes_count"].astype(int)
    if "attio_meetings_count" in merged.columns:
        merged["attio_meetings_count"] = merged["attio_meetings_count"].astype(int)


    if personio_df is not None and len(personio_df) > 0:
        merged = merged.merge(personio_df, on="email", how="outer")


        if "personio_name" in merged.columns:
            mask = (merged["name"].isna() | (merged["name"] == "")) & merged[
                "personio_name"
            ].notna()
            merged.loc[mask, "name"] = merged.loc[mask, "personio_name"]
    else:
        merged["personio_position"] = ""
        merged["personio_status"] = ""
        merged["personio_subcompany"] = ""
        merged["termination_date"] = ""
        merged["hire_date"] = ""


    for col in [
        "personio_position",
        "personio_status",
        "personio_subcompany",
        "termination_date",
        "hire_date",
    ]:
        if col in merged.columns:
            merged[col] = merged[col].fillna("")


    name_recovered = 0
    if "attio_name" in merged.columns:
        mask = (merged["name"].isna() | (merged["name"] == "")) & (
            merged["attio_name"].notna() & (merged["attio_name"] != "")
        )
        merged.loc[mask, "name"] = merged.loc[mask, "attio_name"]
        name_recovered += mask.sum()
    if "personio_name" in merged.columns:
        mask = (merged["name"].isna() | (merged["name"] == "")) & (
            merged["personio_name"].notna() & (merged["personio_name"] != "")
        )
        merged.loc[mask, "name"] = merged.loc[mask, "personio_name"]
        name_recovered += mask.sum()
    if name_recovered > 0:
        log.info(f"Name recovery: {name_recovered} contacts got name from attio/personio")


    email_name_recovered = 0
    still_empty = (merged["name"].isna() | (merged["name"] == "")) & (
        merged["email"].notna() & (merged["email"] != "")
    )
    for idx in merged[still_empty].index:
        email_val = str(merged.at[idx, "email"])
        extracted = extract_name_from_email(email_val)
        if extracted:
            merged.at[idx, "name"] = extracted
            email_name_recovered += 1
    if email_name_recovered > 0:
        log.info(
            f"Name recovery from email: {email_name_recovered} contacts got name from email address"
        )


    merged["name"] = merged["name"].fillna("")
    if "domain" not in merged.columns or merged["domain"].isna().any():
        merged["domain"] = merged["email"].apply(lambda e: e.split("@")[1] if "@" in str(e) else "")


    merged["email_total_msgs"] = (
        merged.get("email_msgs_sent", pd.Series(0, index=merged.index)).fillna(0)
        + merged.get("email_msgs_recv", pd.Series(0, index=merged.index)).fillna(0)
    ).astype(int)

    merged["email_thread_count"] = (
        merged.get("email_threads_sent", pd.Series(0, index=merged.index)).fillna(0)
        + merged.get("email_threads_recv", pd.Series(0, index=merged.index)).fillna(0)
    ).astype(int)


    all_date_cols = [
        "email_last_sent",
        "email_last_recv",
        "cal_last_seen",
        "email_first_seen",
        "cal_first_seen",
        "tactiq_first_seen",
        "tactiq_last_seen",
        "attio_first_interaction",
        "attio_last_interaction",
    ]
    for dc in all_date_cols:
        if dc in merged.columns:
            merged[dc] = pd.to_datetime(merged[dc], errors="coerce", utc=True)


    today_cap = pd.Timestamp.now(tz="UTC")
    for dc in all_date_cols:
        if dc in merged.columns and "last" in dc:
            merged[dc] = merged[dc].clip(upper=today_cap)


    date_cols = [
        c
        for c in [
            "email_last_sent",
            "email_last_recv",
            "cal_last_seen",
            "tactiq_last_seen",
            "attio_last_interaction",
        ]
        if c in merged.columns
    ]
    if date_cols:
        merged["last_contact"] = merged[date_cols].max(axis=1)
    else:
        merged["last_contact"] = pd.NaT


    first_cols = [
        c
        for c in [
            "email_first_seen",
            "cal_first_seen",
            "tactiq_first_seen",
            "attio_first_interaction",
        ]
        if c in merged.columns
    ]
    if first_cols:
        merged["first_contact"] = merged[first_cols].min(axis=1)
    else:
        merged["first_contact"] = pd.NaT


    merged["has_email"] = merged["email_total_msgs"] > 0
    merged["has_calendar"] = merged["cal_events"] > 0
    merged["has_plaud"] = merged["plaud_meetings"] > 0
    merged["has_tactiq"] = merged["tactiq_meetings"] > 0
    merged["has_attio"] = (
        (merged["attio_notes_count"] > 0)
        | (merged["attio_meetings_count"] > 0)
        | (merged.get("attio_connection_strength_num", pd.Series(0, index=merged.index)) > 0)
    )
    merged["has_personio"] = merged["personio_status"].astype(str).str.len() > 0
    merged["is_internal"] = merged["domain"].apply(lambda d: d in INTERNAL_DOMAINS)


    for flag in [
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
    ]:
        merged[flag] = False


    merged["linkedin_url"] = ""
    merged["linkedin_headline"] = ""
    merged["linkedin_messages"] = 0
    merged["slack_user_id"] = ""
    merged["slack_messages"] = 0
    merged["whatsapp_messages"] = 0
    merged["docusign_contracts"] = 0
    merged["phone_primary"] = ""
    merged["organization"] = ""





    merged["has_attio_secondclass"] = False

    merged["attio_sc_record_ids"] = ""

    merged["attio_sc_web_url"] = ""







    if "personio_business_unit" in merged.columns:
        mask_bu = merged["personio_business_unit"].notna() & (
            merged["personio_business_unit"] != ""
        )
        merged.loc[mask_bu, "organization"] = merged.loc[mask_bu, "personio_business_unit"]
        if mask_bu.sum() > 0:
            log.info(f"Organization from Personio business unit: {mask_bu.sum()} contacts")
    else:
        mask_bu = pd.Series(False, index=merged.index)
    if "personio_subcompany" in merged.columns:
        mask = (
            merged["personio_subcompany"].notna() & (merged["personio_subcompany"] != "") & ~mask_bu
        )
        merged.loc[mask, "organization"] = merged.loc[mask, "personio_subcompany"]
        if mask.sum() > 0:
            log.info(f"Organization from Personio subcompany (no business unit): {mask.sum()}")

    merged["notion_mentions"] = 0
    merged["chatgpt_mentions"] = 0
    merged["gdrive_docs"] = 0


    _nat_series = pd.array([pd.NaT] * len(merged), dtype="datetime64[ns, UTC]")
    for col in [
        "slack_last_seen",
        "slack_first_seen",
        "wa_last_message",
        "wa_first_message",
        "li_last_message_date",
        "li_first_message_date",
        "ds_last_contract",
        "ds_first_contract",
        "gd_last_doc",
        "gd_first_doc",
    ]:
        merged[col] = _nat_series.copy()


    merged["is_automated"] = merged["email"].apply(is_automated_email)
    auto_count = merged["is_automated"].sum()
    if auto_count > 0:
        log.info(f"Flagged {auto_count} automated email addresses (score will be 0)")


    merged = merged[
        (merged["email_total_msgs"] > 0)
        | (merged["cal_events"] > 0)
        | (merged["plaud_meetings"] > 0)
        | (merged["tactiq_meetings"] > 0)
        | merged["has_attio"]
        | merged["has_personio"]
    ].copy()


    merged = clean_contacts_email(merged)
    merged = clean_contacts_name(merged)

    merged.sort_values("email_total_msgs", ascending=False, inplace=True)

    log.info(f"Phase 1 merged: {len(merged)} unique contacts")
    return merged





def load_plugin_data(root: Path | None = None):
    """Contacts from the generic plugin intake (tools/cross-source/plugin_intake.py).

    The rows of every $DATA_ROOT/<plugin>/processed/plugin-contacts.parquet, plus the
    participants of every plugin-interactions.parquet that the same plugin does not
    already list. None when no plugin wrote anything (no-op).
    """
    df = plugin_intake.load_people(root if root is not None else DATA_ROOT)
    if df is None or df.empty:
        log.info("Plugins (generic intake): no plugin-contacts / plugin-interactions files")
        return None
    log.info(
        f"Plugins (generic intake): {len(df)} contacts from "
        f"{df['source'].nunique()} plugin(s): {', '.join(sorted(df['source'].unique()))}"
    )
    return df


# Columns the generic intake adds to contacts-merged.parquet.
PLUGIN_COLUMNS_DEFAULTS: dict[str, object] = {
    "has_plugin": False,
    "plugin_sources": "",
    "plugin_interactions": 0,
    "plugin_title": "",
    "plugin_url": "",
    "plugin_email": "",
}
PLUGIN_DATE_COLUMNS = ("plugin_first_seen", "plugin_last_seen")


def _vuoto(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip() == "" or str(v).strip().lower() == "nan"


def _data_tenuta(vecchia, grezza, keep: str):
    """The date to keep between the current one and a new raw ISO value."""
    if _vuoto(grezza):
        return vecchia
    nuova = pd.to_datetime(str(grezza), errors="coerce", utc=True)
    if pd.isna(nuova):
        return vecchia
    if _vuoto(vecchia):
        return nuova
    if (keep == "max" and nuova > vecchia) or (keep == "min" and nuova < vecchia):
        return nuova
    return vecchia


def _riempi_da_plugin(get, put, row) -> None:
    """Fold one plugin contact into a merged row (get/put read and write that row)."""
    put("has_plugin", True)
    fonti = [s for s in str(get("plugin_sources") or "").split(plugin_intake.PARTICIPANT_SEP) if s]
    if row.source and row.source not in fonti:
        fonti.append(row.source)
    put("plugin_sources", plugin_intake.PARTICIPANT_SEP.join(fonti))
    put("plugin_interactions", int(get("plugin_interactions") or 0) + int(row.interactions or 0))
    for col, val in (
        ("name", row.name),
        ("organization", row.company),
        ("plugin_title", row.title),
        ("phone_primary", row.phone),
        ("plugin_url", row.url),
    ):
        if val and _vuoto(get(col)):
            put(col, val)
    if row.email and row.email != str(get("email") or "").lower() and _vuoto(get("plugin_email")):
        put("plugin_email", row.email)
    put("plugin_first_seen", _data_tenuta(get("plugin_first_seen"), row.first_seen, "min"))
    put("plugin_last_seen", _data_tenuta(get("plugin_last_seen"), row.last_seen, "max"))


def _riga_vuota(merged: pd.DataFrame) -> dict:
    """A new merged row with the neutral value of every column."""
    riga: dict = {}
    for col, dtype in merged.dtypes.items():
        if pd.api.types.is_bool_dtype(dtype):
            riga[col] = False
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            riga[col] = pd.NaT
        elif pd.api.types.is_numeric_dtype(dtype):
            riga[col] = 0
        else:
            riga[col] = ""
    return riga


# --- People who come without an email (WhatsApp, Telegram, the address book, plugins) -----------
# They become contacts keyed by their normalised phone ("tel:+12025550123" in contact_key), after
# every source is in, so the same phone found on an email-keyed person enriches that person
# instead. A WhatsApp one-to-one chat partner saved by name only (the phone's export writes the
# saved name, not the number) becomes a contact keyed by that name ("name:<name>"), unless a
# contact with exactly that name already exists. started_by says which source started the row.
NEW_CONTACT_COLUMNS: dict[str, object] = {"contact_key": "", "started_by": ""}


def _pendente(fonte, tel, telefono, nome, email, applica, solo_nome: bool = False) -> dict:
    """One person no source matched yet, kept for merge_phone_contacts()."""
    return {
        "fonte": fonte,
        "tel": tel or "",
        "telefono": str(telefono or "").strip(),
        "nome": str(nome or "").strip(),
        "email": email or "",
        "applica": applica,
        "solo_nome": solo_nome,
    }


def _applica_whatsapp(row):
    """Folds one WhatsApp contact into a row (get/put read and write that row)."""

    def applica(get, put):
        put("has_whatsapp", True)
        put(
            "whatsapp_messages",
            max(int(get("whatsapp_messages") or 0), int(row.get("message_count", 0) or 0)),
        )
        tel = str(row.get("phone", "") or "").strip()
        if tel and _vuoto(get("phone_primary")):
            put("phone_primary", tel)
        put("wa_last_message", _data_tenuta(get("wa_last_message"), row.get("last_message"), "max"))
        put(
            "wa_first_message", _data_tenuta(get("wa_first_message"), row.get("first_message"), "min")
        )

    return applica


def _applica_iphone(row):
    """Folds one address-book card into a row (get/put read and write that row)."""

    def applica(get, put):
        put("has_iphone", True)
        tel = str(row.get("phone_primary", "") or "").strip()
        if tel and _vuoto(get("phone_primary")):
            put("phone_primary", tel)
        org = str(row.get("organization", "") or "").strip()
        if org and _vuoto(get("organization")):
            put("organization", org)

    return applica


# The order merge_phone_contacts() takes the leftovers in, so the book is the same whatever
# order the sources came in: people with an email first (an email identity always wins over a
# phone one), then people with a phone, then WhatsApp names; within each, the address book first
# (the names you saved), then WhatsApp, then the plugins (Telegram, databases...). A row named
# only by a WhatsApp number takes the first real name that joins it, so the order changes who
# is in started_by, never who the person is; WhatsApp before the plugins keeps its message
# counts on the rows the Knowledge Extract reads (started_by whatsapp or iphone).
_ORDINE_FONTE = {"iphone": 0, "whatsapp": 1}


def _ordine_pendente(p: dict) -> tuple[int, int]:
    gruppo = 0 if p["email"] else (1 if p["tel"] else 2)
    return gruppo, _ORDINE_FONTE.get(p["fonte"], 2)


def _scheda_non_persona(row) -> bool:
    """True for an address-book card that is not a person (kind "org", "group", "location")."""
    return str(row.get("kind", "") or "").strip().lower() in ("org", "group", "location")


def _nome_e_un_numero(nome) -> bool:
    """True for an empty name or a name that is only a phone number (an unsaved WhatsApp chat)."""
    n = str(nome or "").strip()
    if not n or n.lower() == "nan":
        return True
    return not re.search(r"[^\W\d_]", n) and bool(normalize_phone(n))


def _diventa_email(get, put, email: str, nome: str) -> None:
    """A phone- or name-keyed row (get/put) becomes the email-keyed row of `email`.

    It keeps its phone, its sources and everything already folded in; the name becomes
    `nome` (the name that comes with the email, e.g. the address-book card) when there is one.
    """
    dominio = email.split("@", 1)[1] if "@" in email else ""
    put("email", email)
    put("domain", dominio)
    put("is_internal", dominio in INTERNAL_DOMAINS)
    put("is_automated", is_automated_email(email))
    put("contact_key", "")
    if nome and not _nome_e_un_numero(nome):
        put("name", nome)


def merge_phone_contacts(
    merged, pendenti, match_stats, email_gia_viste=frozenset(), telefoni_aziende=frozenset()
):
    """Adds the people no source matched by email or name: keyed by email, or by phone.

    `pendenti` holds what the WhatsApp, address-book and plugin steps left over (see
    _pendente). They are taken in a fixed order (_ordine_pendente: email first, then phone,
    then WhatsApp names; the address book before WhatsApp before the plugins), so the result
    does not depend on the order the sources arrived in. Each one enriches: the row with its
    email; the email-keyed row with the same normalised phone (the complete book, plugin
    rows included); a row already added here with the same phone or email; the only row
    with exactly the same name among the rows the name matching could not see yet (born in
    the plugin intake, whose emails are not in `email_gia_viste`, or added here) when that
    row has no other phone. A person with an email that lands on a row added here without
    one (phone- or name-keyed) turns it into the email-keyed row of that email, keeping the
    phone and the sources, with the name that came with the email. A row named only by a
    number (an unsaved WhatsApp chat) takes the first real name another source gives it.
    Otherwise it becomes a new row: email-keyed when it has an email, phone-keyed
    (contact_key "tel:...") when it has a phone, name-keyed ("name:...") for a WhatsApp chat
    partner saved by name only. A number nobody names except an address-book company card
    (`telefoni_aziende`) is that company and is not added as a person. Same inputs, same rows:
    every run rebuilds the same book.
    """
    for col, default in NEW_CONTACT_COLUMNS.items():
        if col not in merged.columns:
            merged[col] = default
    if not pendenti:
        return merged

    phone_map = build_phone_map(merged)
    email_index = {e.lower(): idx for idx, e in merged["email"].items() if isinstance(e, str) and e}
    nomi_non_visti: dict[str, list] = defaultdict(list)
    for idx, row in merged.iterrows():
        e = str(row.get("email") or "").strip().lower()
        if e and e not in email_gia_viste:
            k = normalize_name_for_match(str(row.get("name") or ""))
            if k:
                nomi_non_visti[k].append(idx)

    nuovi: list[dict] = []
    per_tel: dict[str, int] = {}
    per_email: dict[str, int] = {}
    per_nome: dict[str, list[int]] = defaultdict(list)
    conta = defaultdict(int)

    def _tel_di(get) -> str:
        return normalize_phone(str(get("phone_primary") or ""))

    for p in sorted(pendenti, key=_ordine_pendente):
        fonte, tel, email = p["fonte"], p["tel"], p["email"]
        chiave = normalize_name_for_match(p["nome"]) if p["nome"] else ""
        idx = pos = None
        if email and email in email_index:
            idx = email_index[email]
            conta["email"] += 1
        elif email and email in per_email:
            pos = per_email[email]
            conta["email"] += 1
        elif tel and tel in phone_map and phone_map[tel] in email_index:
            idx = email_index[phone_map[tel]]
            conta["phone"] += 1
        elif tel and tel in per_tel:
            pos = per_tel[tel]
            conta["phone"] += 1
        elif chiave:
            vecchi = [
                i
                for i in nomi_non_visti.get(chiave, [])
                if not tel or _tel_di(lambda c, _i=i: merged.at[_i, c]) in ("", tel)
            ]
            recenti = [
                j for j in per_nome.get(chiave, []) if not tel or _tel_di(nuovi[j].get) in ("", tel)
            ]
            if len(vecchi) + len(recenti) == 1:
                idx = vecchi[0] if vecchi else None
                pos = recenti[0] if recenti else None
                conta["name"] += 1

        if idx is not None:
            get = lambda c, _i=idx: merged.at[_i, c]  # noqa: E731
            put = lambda c, v, _i=idx: merged.at.__setitem__((_i, c), v)  # noqa: E731
        elif pos is not None:
            get, put = nuovi[pos].get, nuovi[pos].__setitem__
            if email and _vuoto(get("email")):
                # a person with an email met a row added without one: one email-keyed row
                _diventa_email(get, put, email, p["nome"])
                per_email.setdefault(email, pos)
                conta["upgraded"] += 1
        if idx is not None or pos is not None:
            p["applica"](get, put)
            if p["nome"] and not _nome_e_un_numero(p["nome"]) and _nome_e_un_numero(get("name")):
                put("name", p["nome"])
                if pos is not None and chiave and pos not in per_nome[chiave]:
                    per_nome[chiave].append(pos)
            if pos is not None and tel:
                per_tel.setdefault(tel, pos)
            match_stats[fonte]["matched"] += 1
            continue

        if (
            not email
            and tel in telefoni_aziende
            and (fonte == "whatsapp" or _nome_e_un_numero(p["nome"]))
        ):
            # a WhatsApp number (or an unnamed one) your address book has as a company card:
            # that company, not a person
            conta["company"] += 1
            match_stats[fonte]["unmatched"] += 1
            continue
        riga = _riga_vuota(merged)
        riga["name"] = p["nome"] or p["telefono"] or tel
        riga["phone_primary"] = p["telefono"] or tel
        riga["started_by"] = fonte
        if email:
            dominio = email.split("@", 1)[1] if "@" in email else ""
            riga.update(
                {
                    "email": email,
                    "domain": dominio,
                    "is_internal": dominio in INTERNAL_DOMAINS,
                    "is_automated": is_automated_email(email),
                }
            )
            conta["new_email"] += 1
        elif tel:
            riga["contact_key"] = f"tel:{tel}"
            conta["new_phone"] += 1
        else:
            riga["contact_key"] = f"name:{chiave}"
            conta["new_name"] += 1
        p["applica"](riga.get, riga.__setitem__)
        pos = len(nuovi)
        nuovi.append(riga)
        if tel:
            per_tel.setdefault(tel, pos)
        if email:
            per_email.setdefault(email, pos)
        if chiave:
            per_nome[chiave].append(pos)
        match_stats[fonte]["added"] = match_stats[fonte].get("added", 0) + 1

    if nuovi:
        nuove = pd.DataFrame(nuovi, columns=list(merged.columns))
        for col, dtype in merged.dtypes.items():
            if pd.api.types.is_datetime64_any_dtype(dtype):
                nuove[col] = pd.to_datetime(nuove[col], errors="coerce", utc=True)
            elif pd.api.types.is_bool_dtype(dtype):
                nuove[col] = nuove[col].fillna(False).astype(bool)
        merged = pd.concat([merged, nuove], ignore_index=True) if len(merged) else nuove
        # with no email-keyed contact at all the flag columns were born as objects: booleans again
        for col in merged.columns:
            if col.startswith("has_") or col in ("is_internal", "is_automated"):
                merged[col] = merged[col].map(lambda v: False if _vuoto(v) else bool(v)).astype(bool)
    log.info(
        f"  Without an email: {conta['email']} matched by email, {conta['phone']} by phone, "
        f"{conta['name']} by the same name ({conta['upgraded']} phone- or name-keyed rows became "
        f"email-keyed); new contacts: {conta['new_phone']} keyed by phone, "
        f"{conta['new_email']} by email, {conta['new_name']} by WhatsApp name, "
        f"{conta['company']} left out as company numbers (of {len(pendenti)})"
    )
    return merged


def merge_plugin_contacts(merged, plugin_df, per_email, per_nome, match_stats, pendenti=None):
    """Generic intake: match plugin contacts by email, then phone, then name.

    A match enriches the existing contact (has_plugin, plugin_* columns, and the
    name / organization / phone when they are empty). A contact that matches
    nothing becomes a new email-keyed row when it has an email (like the email-keyed
    sources of phase 1). Rows with an email go first, so a phone-only row of another
    plugin (Telegram, a vCard) finds the email-keyed person with the same phone.
    Without an email and with a phone, an unmatched contact is handed to `pendenti`
    (a list, when given): merge_phone_contacts() keys it by its normalised phone after
    every source is in. Without email and phone it is counted as unmatched and not
    added. Name matches go through the same rule and the same verification queue as
    the other sources (`per_nome`); a contact set aside for verification is not added.
    """
    for col, default in PLUGIN_COLUMNS_DEFAULTS.items():
        if col not in merged.columns:
            merged[col] = default
    for col in PLUGIN_DATE_COLUMNS:
        if col not in merged.columns:
            merged[col] = pd.array([pd.NaT] * len(merged), dtype="datetime64[ns, UTC]")
    if plugin_df is None or len(plugin_df) == 0:
        return merged

    # Rebuilt here: WhatsApp and iPhone may have filled phone_primary in this phase.
    phone_map = build_phone_map(merged)
    email_index = {e.lower(): idx for idx, e in merged["email"].items() if isinstance(e, str) and e}
    nuovi: dict[str, dict] = {}
    nuovi_per_tel: dict[str, str] = {}
    via = defaultdict(int)

    righe = list(plugin_df.itertuples(index=False))
    righe.sort(key=lambda r: not str(r.email or "").strip())  # stable: rows with an email first
    for row in righe:
        fonte = row.source or row.plugin
        email = (row.email or "").strip().lower()
        if email and (email in OWN_EMAILS or is_noise(email)):
            if email in OWN_EMAILS:
                continue
            email = ""
        nome = row.name or ""
        if nome and (is_own_name(nome) or is_noise_name(nome)):
            if is_own_name(nome):
                continue
            nome = ""
        tel = normalize_phone(row.phone) if row.phone else ""
        if not (email or nome or tel):
            continue
        row = row._replace(email=email, name=nome)

        idx, nuovo = None, None
        if email:
            idx = per_email(email)
            if idx is None and email in nuovi:
                nuovo = nuovi[email]
            if idx is not None or nuovo is not None:
                via["email"] += 1
        if idx is None and nuovo is None and tel:
            if tel in phone_map and phone_map[tel] in email_index:
                idx = email_index[phone_map[tel]]
            elif tel in nuovi_per_tel:
                nuovo = nuovi[nuovi_per_tel[tel]]
            if idx is not None or nuovo is not None:
                via["phone"] += 1
        in_coda_prima = match_stats[fonte]["da_verificare"]
        if idx is None and nuovo is None and nome:
            chiave = email or (tel and f"tel:{tel}") or _chiave_nome(nome)
            res = per_nome(
                fonte,
                chiave,
                nome,
                85,
                {
                    "interazioni": int(row.interactions or 0),
                    "azienda": row.company,
                    "ruolo": row.title,
                    "email": email,
                    "telefono": row.phone,
                    "profilo": row.url,
                },
            )
            if res:
                idx = res[0]
                via["name"] += 1

        if idx is not None:
            _riempi_da_plugin(
                lambda c, _i=idx: merged.at[_i, c],
                lambda c, v, _i=idx: merged.at.__setitem__((_i, c), v),
                row,
            )
            match_stats[fonte]["matched"] += 1
        elif nuovo is not None:
            _riempi_da_plugin(nuovo.get, nuovo.__setitem__, row)
            match_stats[fonte]["matched"] += 1
        elif email:
            nuovo = _riga_vuota(merged)
            dominio = email.split("@", 1)[1] if "@" in email else ""
            nuovo.update(
                {
                    "email": email,
                    "domain": dominio,
                    "is_internal": dominio in INTERNAL_DOMAINS,
                    "is_automated": is_automated_email(email),
                }
            )
            _riempi_da_plugin(nuovo.get, nuovo.__setitem__, row)
            if _vuoto(nuovo.get("name")):
                nuovo["name"] = extract_name_from_email(email) or ""
            nuovi[email] = nuovo
            if tel:
                nuovi_per_tel.setdefault(tel, email)
            via["new"] += 1
            match_stats[fonte]["added"] = match_stats[fonte].get("added", 0) + 1
        elif tel and pendenti is not None and match_stats[fonte]["da_verificare"] == in_coda_prima:
            # phone only, nobody matched: keyed by the phone once every source is in
            pendenti.append(
                _pendente(
                    fonte,
                    tel,
                    row.phone,
                    nome,
                    "",
                    lambda get, put, _r=row: _riempi_da_plugin(get, put, _r),
                )
            )
            via["phone_only"] += 1
        else:
            match_stats[fonte]["unmatched"] += 1

    if nuovi:
        nuove = pd.DataFrame(list(nuovi.values()), columns=list(merged.columns))
        for col, dtype in merged.dtypes.items():
            if pd.api.types.is_datetime64_any_dtype(dtype):
                nuove[col] = pd.to_datetime(nuove[col], errors="coerce", utc=True)
            elif pd.api.types.is_bool_dtype(dtype):
                nuove[col] = nuove[col].fillna(False).astype(bool)
        merged = pd.concat([merged, nuove], ignore_index=True)

    for fonte in sorted(set(plugin_df["source"])):
        s = match_stats[fonte]
        log.info(
            f"  Plugin {fonte}: {s['matched']} matched, {s.get('added', 0)} added as new "
            f"email-keyed contacts, {s['da_verificare']} to verify, {s['unmatched']} unmatched"
        )
    log.info(
        f"  Plugins: {via['email']} via email, {via['phone']} via phone, "
        f"{via['name']} via name, {via['new']} new, {via['phone_only']} phone only "
        f"(of {len(plugin_df)})"
    )
    return merged


def merge_contacts_phase2(
    merged,
    linkedin_df,
    slack_df,
    whatsapp_df,
    docusign_df,
    iphone_df,
    notion_df,
    chatgpt_df,
    linkedin_url_map=None,
    attio_sc_df=None,
    da_verificare: list | None = None,
    verifiche: dict | None = None,
    plugin_df=None,
):
    ""













    log.info("Phase 2: Name-matching new sources to existing contacts...")

    name_index = build_name_index(merged)
    match_stats = defaultdict(
        lambda: {"matched": 0, "unmatched": 0, "ambiguous": 0, "da_verificare": 0, "verificati": 0}
    )
    verifiche = verifiche or {}


    email_index = {e.lower(): idx for idx, e in merged["email"].items() if isinstance(e, str) and e}
    # People no source matched: keyed by phone (or email) at the end, see merge_phone_contacts().
    pendenti: list[dict] = []
    # phones of the address-book company cards (filled by the iPhone lane below)
    telefoni_aziende: set[str] = set()
    email_gia_viste = frozenset(email_index)


    phone_map = build_phone_map(merged)
    if phone_map:
        log.info(f"Phone map: {len(phone_map)} Phase 1 contacts with phone number")

    def _propagate_date(merged, idx, col_name, raw_value, keep="max"):
        ""
        if not raw_value or str(raw_value).strip() == "":
            return
        new_val = pd.to_datetime(str(raw_value), errors="coerce", utc=True)
        if pd.isna(new_val):
            return
        old_val = merged.at[idx, col_name]
        if (
            pd.isna(old_val)
            or (keep == "max" and new_val > old_val)
            or (keep == "min" and new_val < old_val)
        ):
            merged.at[idx, col_name] = new_val

    def _per_email(valore):
        ""
        e = str(valore or "").strip().lower()
        return email_index.get(e) if "@" in e else None

    def _per_nome(fonte: str, chiave: str, nome, soglia: int, segnali: dict):
        ""
        risposta = verifiche.get((fonte, chiave))
        if risposta and risposta["si"] in email_index:
            idx = email_index[risposta["si"]]
            match_stats[fonte]["verificati"] += 1
            return idx, risposta["si"], merged.at[idx, "name"], 100
        v = valuta_nome(nome, name_index, threshold=soglia)
        escluse = risposta["no"] if risposta else set()
        voci = [x for x in v["voci"] if str(x["email"]).strip().lower() not in escluse]
        if v["esito"] == "aggancio" and voci:
            return voci[0]["idx"], voci[0]["email"], voci[0]["name"], v["punteggio"]
        if v["esito"] == "candidati" and voci:
            match_stats[fonte]["da_verificare"] += 1
            if da_verificare is not None:
                da_verificare.append(
                    {
                        "fonte": fonte,
                        "chiave": chiave,
                        "nome": str(nome),
                        "candidati": [{"email": x["email"], "nome": x["name"]} for x in voci[:5]],
                        "altri_candidati": max(0, len(voci) - 5),
                        "punteggio": round(float(v["punteggio"]), 1),
                        "motivo": v["motivo"],
                        "segnali": segnali,
                    }
                )
        return None


    linkedin_url_matched = 0
    linkedin_email_matched = 0
    if linkedin_df is not None and len(linkedin_df) > 0:
        for _, row in linkedin_df.iterrows():
            idx = None
            li_url = str(row.get("linkedin_url", "") or "").strip()
            norm_url = _normalize_linkedin_url(li_url) if li_url else ""


            if linkedin_url_map and norm_url and norm_url in linkedin_url_map:
                attio_email = linkedin_url_map[norm_url]
                if attio_email in email_index:
                    idx = email_index[attio_email]
                    linkedin_url_matched += 1


            if idx is None:
                idx = _per_email(row.get("email"))
                if idx is not None:
                    linkedin_email_matched += 1


            if idx is None:
                result = _per_nome(
                    "linkedin",
                    norm_url or _chiave_nome(row["name"]),
                    row["name"],
                    82,
                    {
                        "messaggi": int(row.get("total_messages", 0) or 0),
                        "azienda": str(row.get("company", "") or "").strip(),
                        "ruolo": str(row.get("headline", "") or "").strip(),
                        "profilo": li_url,
                    },
                )
                idx = result[0] if result else None

            if idx is None:
                match_stats["linkedin"]["unmatched"] += 1
                continue
            merged.at[idx, "has_linkedin"] = True
            if not merged.at[idx, "linkedin_url"]:
                merged.at[idx, "linkedin_url"] = li_url
            headline = str(row.get("headline", "") or "").strip()
            if headline and not merged.at[idx, "linkedin_headline"]:
                merged.at[idx, "linkedin_headline"] = headline
            company = str(row.get("company", "") or "").strip()
            if company and not merged.at[idx, "organization"]:
                merged.at[idx, "organization"] = company
            merged.at[idx, "linkedin_messages"] = max(
                int(merged.at[idx, "linkedin_messages"]),
                int(row.get("total_messages", 0) or 0),
            )
            _propagate_date(
                merged, idx, "li_last_message_date", row.get("last_message_date"), "max"
            )
            _propagate_date(
                merged, idx, "li_first_message_date", row.get("first_message_date"), "min"
            )
            match_stats["linkedin"]["matched"] += 1
        per_nome = (
            match_stats["linkedin"]["matched"] - linkedin_url_matched - linkedin_email_matched
        )
        log.info(
            f"  LinkedIn: {match_stats['linkedin']['matched']} matched "
            f"({linkedin_url_matched} via URL, {linkedin_email_matched} via email, {per_nome} via name), "
            f"{match_stats['linkedin']['da_verificare']} to verify, "
            f"{match_stats['linkedin']['unmatched']} unmatched "
            f"(of {len(linkedin_df)})"
        )


    slack_email_matched = 0
    if slack_df is not None and len(slack_df) > 0:
        for _, row in slack_df.iterrows():


            idx = _per_email(row.get("email"))
            if idx is not None:
                slack_email_matched += 1
                result = (idx, "", "", 100)
            else:
                result = _per_nome(
                    "slack",
                    str(row.get("user_id", "") or "") or _chiave_nome(row["real_name"]),
                    row["real_name"],
                    85,
                    {"messaggi": int(row.get("message_count", 0) or 0)},
                )
            if result:
                idx, email, matched_name, score = result
                merged.at[idx, "has_slack"] = True
                if not merged.at[idx, "slack_user_id"]:
                    merged.at[idx, "slack_user_id"] = str(row.get("user_id", "") or "")
                merged.at[idx, "slack_messages"] = max(
                    int(merged.at[idx, "slack_messages"]), int(row.get("message_count", 0) or 0)
                )
                _propagate_date(merged, idx, "slack_last_seen", row.get("last_seen"), "max")
                _propagate_date(merged, idx, "slack_first_seen", row.get("first_seen"), "min")
                match_stats["slack"]["matched"] += 1
            else:
                match_stats["slack"]["unmatched"] += 1
        log.info(
            f"  Slack: {match_stats['slack']['matched']} matched ({slack_email_matched} via email), "
            f"{match_stats['slack']['da_verificare']} to verify, "
            f"{match_stats['slack']['unmatched']} unmatched "
            f"(of {len(slack_df)})"
        )


    whatsapp_phone_matched = 0
    if whatsapp_df is not None and len(whatsapp_df) > 0:
        # rebuilt here: the map of the start of phase 2 is empty (phase 1 has no phones)
        phone_map = build_phone_map(merged)
        for _, row in whatsapp_df.iterrows():
            matched = False


            if phone_map:
                phone = str(row.get("phone", "") or "").strip()
                if phone:
                    norm_phone = normalize_phone(phone)
                    if norm_phone and norm_phone in phone_map:
                        match_email = phone_map[norm_phone]
                        if match_email in email_index:
                            idx = email_index[match_email]
                            merged.at[idx, "has_whatsapp"] = True
                            merged.at[idx, "whatsapp_messages"] = max(
                                int(merged.at[idx, "whatsapp_messages"]),
                                int(row.get("message_count", 0) or 0),
                            )
                            if not merged.at[idx, "phone_primary"]:
                                merged.at[idx, "phone_primary"] = phone
                            _propagate_date(
                                merged, idx, "wa_last_message", row.get("last_message"), "max"
                            )
                            _propagate_date(
                                merged, idx, "wa_first_message", row.get("first_message"), "min"
                            )
                            match_stats["whatsapp"]["matched"] += 1
                            whatsapp_phone_matched += 1
                            matched = True


            if not matched:
                in_coda_prima = match_stats["whatsapp"]["da_verificare"]
                result = _per_nome(
                    "whatsapp",
                    _chiave_telefono(row.get("phone")) or _chiave_nome(row["name"]),
                    row["name"],
                    82,
                    {
                        "messaggi": int(row.get("message_count", 0) or 0),
                        "telefono": str(row.get("phone", "") or ""),
                    },
                )
                if result:
                    idx, email, matched_name, score = result
                    merged.at[idx, "has_whatsapp"] = True
                    merged.at[idx, "whatsapp_messages"] = max(
                        int(merged.at[idx, "whatsapp_messages"]),
                        int(row.get("message_count", 0) or 0),
                    )
                    phone = str(row.get("phone", "") or "")
                    if phone and not merged.at[idx, "phone_primary"]:
                        merged.at[idx, "phone_primary"] = phone
                    _propagate_date(merged, idx, "wa_last_message", row.get("last_message"), "max")
                    _propagate_date(
                        merged, idx, "wa_first_message", row.get("first_message"), "min"
                    )
                    match_stats["whatsapp"]["matched"] += 1
                elif match_stats["whatsapp"]["da_verificare"] == in_coda_prima and (
                    _chiave_telefono(row.get("phone")) or bool(row.get("is_1to1_participant"))
                ):
                    # with a phone, or your one-to-one chat partner: a contact of its own
                    tel = _chiave_telefono(row.get("phone"))
                    pendenti.append(
                        _pendente(
                            "whatsapp",
                            tel,
                            row.get("phone"),
                            row["name"],
                            "",
                            _applica_whatsapp(row),
                            solo_nome=not tel,
                        )
                    )
                else:
                    match_stats["whatsapp"]["unmatched"] += 1
        log.info(
            f"  WhatsApp: {match_stats['whatsapp']['matched']} matched "
            f"({whatsapp_phone_matched} via phone, "
            f"{match_stats['whatsapp']['matched'] - whatsapp_phone_matched} via name), "
            f"{match_stats['whatsapp']['da_verificare']} to verify, "
            f"{match_stats['whatsapp']['unmatched']} unmatched "
            f"(of {len(whatsapp_df)})"
        )


    if docusign_df is not None and len(docusign_df) > 0:
        for _, row in docusign_df.iterrows():


            ds_email = str(row.get("email", "") or "").strip().lower()
            if ds_email in email_index:
                result = (email_index[ds_email], ds_email, row["name"], 100)
            else:
                result = _per_nome(
                    "docusign",
                    ds_email or _chiave_nome(row["name"]),
                    row["name"],
                    85,
                    {"contratti": int(row.get("contract_count", 0) or 0)},
                )
            if result:
                idx, email, matched_name, score = result
                merged.at[idx, "has_docusign"] = True
                merged.at[idx, "docusign_contracts"] = max(
                    int(merged.at[idx, "docusign_contracts"]),
                    int(row.get("contract_count", 0) or 0),
                )
                _propagate_date(merged, idx, "ds_last_contract", row.get("last_contract"), "max")
                _propagate_date(merged, idx, "ds_first_contract", row.get("first_contract"), "min")
                match_stats["docusign"]["matched"] += 1
            else:
                match_stats["docusign"]["unmatched"] += 1
        log.info(
            f"  DocuSign: {match_stats['docusign']['matched']} matched, "
            f"{match_stats['docusign']['da_verificare']} to verify, "
            f"{match_stats['docusign']['unmatched']} unmatched "
            f"(of {len(docusign_df)})"
        )
























    if attio_sc_df is not None and len(attio_sc_df) > 0:
        for _, row in attio_sc_df.iterrows():
            rid = str(row.get("attio_record_id", "") or "").strip()
            result = find_best_match(row["name"], name_index, threshold=85)
            if result:
                idx, email, matched_name, score = result
                merged.at[idx, "has_attio_secondclass"] = True
                precedenti = [
                    r for r in str(merged.at[idx, "attio_sc_record_ids"] or "").split("|||") if r
                ]
                if rid and rid not in precedenti:
                    precedenti.append(rid)
                merged.at[idx, "attio_sc_record_ids"] = "|||".join(precedenti)
                if not merged.at[idx, "attio_sc_web_url"]:
                    merged.at[idx, "attio_sc_web_url"] = str(
                        row.get("attio_web_url", "") or ""
                    ).strip()
                match_stats["attio_seconda_classe"]["matched"] += 1
            else:
                match_stats["attio_seconda_classe"]["unmatched"] += 1
        log.info(
            f"  Attio second class: "
            f"{match_stats['attio_seconda_classe']['matched']} namesakes flagged "
            f"(NOT merged, no value copied), "
            f"{match_stats['attio_seconda_classe']['unmatched']} with no namesake "
            f"(of {len(attio_sc_df)}), no row added"
        )


    iphone_phone_matched = 0
    iphone_email_matched = 0
    iphone_aziende = 0
    if iphone_df is not None and len(iphone_df) > 0:
        # rebuilt here: WhatsApp may have filled phone_primary in this phase
        phone_map = build_phone_map(merged)
        for _, row in iphone_df.iterrows():
            matched = False
            if _scheda_non_persona(row):
                # a company card (or group / location): never a person, and an unsaved
                # number it names is that company, not someone to add (merge_phone_contacts)
                tel_azienda = _chiave_telefono(row.get("phone_primary"))
                if tel_azienda:
                    telefoni_aziende.add(tel_azienda)
                iphone_aziende += 1
                continue

            if phone_map:
                phone = str(row.get("phone_primary", "") or "").strip()
                if phone:
                    norm_phone = normalize_phone(phone)
                    if norm_phone and norm_phone in phone_map:
                        match_email = phone_map[norm_phone]
                        if match_email in email_index:
                            idx = email_index[match_email]
                            merged.at[idx, "has_iphone"] = True
                            if not merged.at[idx, "phone_primary"]:
                                merged.at[idx, "phone_primary"] = phone
                            org = str(row.get("organization", "") or "")
                            if org and not merged.at[idx, "organization"]:
                                merged.at[idx, "organization"] = org
                            match_stats["iphone"]["matched"] += 1
                            iphone_phone_matched += 1
                            matched = True


            if not matched:
                in_coda_prima = match_stats["iphone"]["da_verificare"]
                idx = _per_email(row.get("email"))
                if idx is not None:
                    iphone_email_matched += 1
                    result = (idx, "", "", 100)
                else:
                    result = _per_nome(
                        "iphone",
                        _chiave_telefono(row.get("phone_primary")) or _chiave_nome(row["name"]),
                        row["name"],
                        82,
                        {
                            "telefono": str(row.get("phone_primary", "") or ""),
                            "azienda": str(row.get("organization", "") or "").strip(),
                        },
                    )
                if result:
                    idx, email, matched_name, score = result
                    merged.at[idx, "has_iphone"] = True
                    phone = str(row.get("phone_primary", "") or "")
                    if phone and not merged.at[idx, "phone_primary"]:
                        merged.at[idx, "phone_primary"] = phone
                    org = str(row.get("organization", "") or "")
                    if org and not merged.at[idx, "organization"]:
                        merged.at[idx, "organization"] = org
                    match_stats["iphone"]["matched"] += 1
                else:
                    tel = _chiave_telefono(row.get("phone_primary"))
                    email = str(row.get("email", "") or "").strip().lower()
                    if email and ("@" not in email or is_noise(email)):
                        email = ""
                    if (
                        (tel or email)
                        and match_stats["iphone"]["da_verificare"] == in_coda_prima
                        and not bool(row.get("is_business"))
                    ):
                        pendenti.append(
                            _pendente(
                                "iphone",
                                tel,
                                row.get("phone_primary"),
                                row["name"],
                                email,
                                _applica_iphone(row),
                            )
                        )
                    else:
                        match_stats["iphone"]["unmatched"] += 1
        log.info(
            f"  iPhone: {match_stats['iphone']['matched']} matched "
            f"({iphone_phone_matched} via phone, {iphone_email_matched} via email, "
            f"{match_stats['iphone']['matched'] - iphone_phone_matched - iphone_email_matched} via name), "
            f"{match_stats['iphone']['da_verificare']} to verify, "
            f"{match_stats['iphone']['unmatched']} unmatched, "
            f"{iphone_aziende} company cards left out (not people) "
            f"(of {len(iphone_df)})"
        )


    if notion_df is not None and len(notion_df) > 0:
        for _, row in notion_df.iterrows():
            result = _per_nome(
                "notion",
                _chiave_nome(row["entity_name"]),
                row["entity_name"],
                85,
                {"menzioni": int(row.get("mention_count", 0) or 0)},
            )
            if result:
                idx, email, matched_name, score = result
                merged.at[idx, "has_notion"] = True
                merged.at[idx, "notion_mentions"] = max(
                    int(merged.at[idx, "notion_mentions"]), int(row.get("mention_count", 0) or 0)
                )
                match_stats["notion"]["matched"] += 1
            else:
                match_stats["notion"]["unmatched"] += 1
        log.info(
            f"  Notion: {match_stats['notion']['matched']} matched, "
            f"{match_stats['notion']['da_verificare']} to verify, "
            f"{match_stats['notion']['unmatched']} unmatched "
            f"(of {len(notion_df)})"
        )


    if chatgpt_df is not None and len(chatgpt_df) > 0:
        for _, row in chatgpt_df.iterrows():
            result = _per_nome(
                "chatgpt",
                _chiave_nome(row["entity_name"]),
                row["entity_name"],
                85,
                {"menzioni": int(row.get("chatgpt_mentions", 0) or 0)},
            )
            if result:
                idx, email, matched_name, score = result
                merged.at[idx, "has_chatgpt_mention"] = True
                merged.at[idx, "chatgpt_mentions"] = max(
                    int(merged.at[idx, "chatgpt_mentions"]),
                    int(row.get("chatgpt_mentions", 0) or 0),
                )
                match_stats["chatgpt"]["matched"] += 1
            else:
                match_stats["chatgpt"]["unmatched"] += 1
        log.info(
            f"  ChatGPT: {match_stats['chatgpt']['matched']} matched, "
            f"{match_stats['chatgpt']['da_verificare']} to verify, "
            f"{match_stats['chatgpt']['unmatched']} unmatched "
            f"(of {len(chatgpt_df)})"
        )


    gdrive_df = load_gdrive_data()
    if gdrive_df is not None and len(gdrive_df) > 0:
        email_index = {
            e.lower(): idx for idx, e in merged["email"].items() if isinstance(e, str) and e
        }
        for _, row in gdrive_df.iterrows():
            email = row.get("email", "").lower()
            if email in email_index:
                idx = email_index[email]
                merged.at[idx, "has_gdrive"] = True
                merged.at[idx, "gdrive_docs"] = int(row.get("doc_count", 0))
                _propagate_date(merged, idx, "gd_last_doc", row.get("last_doc"), "max")
                _propagate_date(merged, idx, "gd_first_doc", row.get("first_doc"), "min")
                match_stats["gdrive"]["matched"] += 1
            else:
                match_stats["gdrive"]["unmatched"] += 1
        log.info(
            f"  GDrive: {match_stats['gdrive']['matched']} matched, "
            f"{match_stats['gdrive']['unmatched']} unmatched "
            f"(of {len(gdrive_df)})"
        )

    # Generic plugin intake: email, then phone, then name (same rule and queue as above).
    merged = merge_plugin_contacts(
        merged, plugin_df, _per_email, _per_nome, match_stats, pendenti=pendenti
    )
    # People without an email that nobody matched: keyed by their phone (or email, or
    # WhatsApp name) now that every source is in, see merge_phone_contacts().
    merged = merge_phone_contacts(
        merged, pendenti, match_stats, email_gia_viste, telefoni_aziende=telefoni_aziende
    )


    try:
        from rq_manual_contacts import extract_manual_contacts

        manual_df = extract_manual_contacts()
        if manual_df is not None and len(manual_df) > 0:

            if "has_manual_input" not in merged.columns:
                merged["has_manual_input"] = False

            pid_col = "person_id" if "person_id" in merged.columns else None
            if pid_col:
                pid_index = {
                    str(pid): idx
                    for idx, pid in merged[pid_col].items()
                    if isinstance(pid, str) and pid
                }
            else:

                pid_index = {
                    str(e).lower(): idx
                    for idx, e in merged["email"].items()
                    if isinstance(e, str) and e
                }
            for _, row in manual_df.iterrows():
                pid = str(row.get("person_id", ""))
                if pid in pid_index:
                    idx = pid_index[pid]
                    merged.at[idx, "has_manual_input"] = True

                    for field in ["phone", "company", "role"]:
                        col = "phone_primary" if field == "phone" else field
                        if col not in merged.columns:
                            continue
                        current = merged.at[idx, col]
                        manual_val = row.get(field, "")
                        if (pd.isna(current) or current == "") and manual_val:
                            merged.at[idx, col] = manual_val
                    match_stats.setdefault("manual", {"matched": 0, "unmatched": 0})
                    match_stats["manual"]["matched"] += 1
                else:
                    match_stats.setdefault("manual", {"matched": 0, "unmatched": 0})
                    match_stats["manual"]["unmatched"] += 1
            log.info(
                f"  Manual: {match_stats.get('manual', {}).get('matched', 0)} matched, "
                f"{match_stats.get('manual', {}).get('unmatched', 0)} unmatched "
                f"(of {len(manual_df)})"
            )
    except ImportError:
        log.debug("rq_manual_contacts not available, skipping source 15")



    today_cap = pd.Timestamp.now(tz="UTC")
    all_last_cols = [
        c
        for c in [
            "email_last_sent",
            "email_last_recv",
            "cal_last_seen",
            "tactiq_last_seen",
            "attio_last_interaction",
            "slack_last_seen",
            "wa_last_message",
            "li_last_message_date",
            "ds_last_contract",
            "gd_last_doc",
            "plugin_last_seen",
        ]
        if c in merged.columns
    ]
    for dc in all_last_cols:
        merged[dc] = pd.to_datetime(merged[dc], errors="coerce", utc=True)
        merged[dc] = merged[dc].clip(upper=today_cap)

    merged["last_contact"] = merged[all_last_cols].max(axis=1) if all_last_cols else pd.NaT

    all_first_cols = [
        c
        for c in [
            "email_first_seen",
            "cal_first_seen",
            "tactiq_first_seen",
            "attio_first_interaction",
            "slack_first_seen",
            "wa_first_message",
            "li_first_message_date",
            "ds_first_contract",
            "gd_first_doc",
            "plugin_first_seen",
        ]
        if c in merged.columns
    ]
    for dc in all_first_cols:
        merged[dc] = pd.to_datetime(merged[dc], errors="coerce", utc=True)
    merged["first_contact"] = merged[all_first_cols].min(axis=1) if all_first_cols else pd.NaT


    _source_map = {
        "email_last_sent": "email",
        "email_last_recv": "email",
        "cal_last_seen": "calendar",
        "tactiq_last_seen": "tactiq",
        "attio_last_interaction": "attio",
        "slack_last_seen": "slack",
        "wa_last_message": "whatsapp",
        "li_last_message_date": "linkedin",
        "ds_last_contract": "docusign",
        "gd_last_doc": "gdrive",
        "plugin_last_seen": "plugin",
    }

    def _find_last_contact_source(row):
        lc = row.get("last_contact")
        if pd.isna(lc):
            return ""
        for col, src in _source_map.items():
            if col in row.index and pd.notna(row[col]) and row[col] == lc:
                if src == "plugin":
                    # the plugin id itself (first one listed for this contact)
                    return str(row.get("plugin_sources") or "plugin").split("|||")[0]
                return src
        return "unknown"

    merged["last_contact_source"] = merged.apply(_find_last_contact_source, axis=1)


    source_flags = [
        "has_email",
        "has_calendar",
        "has_plaud",
        "has_tactiq",
        "has_attio",
        "has_personio",
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "has_plugin",
    ]
    merged["source_count"] = sum(merged[c].astype(int) for c in source_flags if c in merged.columns)


    p2_flags = [
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "has_plugin",
    ]
    p2_any = merged[p2_flags].any(axis=1)
    log.info(f"Phase 2 enrichment: {p2_any.sum()} contacts enriched with name-matched data")
    for flag in p2_flags:
        count = merged[flag].sum()
        if count > 0:
            log.info(f"  {flag}: {count}")

    return merged, match_stats





def _person_id_di_ripiego(df) -> int:
    """A deterministic person_id for every row the entity map left without one (in place).

    "p_" + hash of the email, or of contact_key for a contact without an email (keyed by
    phone or WhatsApp name). Runs whether or not the entity map resolved anything, so an
    install with no email at all (Telegram or WhatsApp only) still gets stable ids.
    Returns how many rows got one.
    """
    n = 0
    for idx in df.index:
        if str(df.at[idx, "person_id"] or "").strip():
            continue
        email_val = str(df.at[idx, "email"] or "").strip()
        chiave = str(df.at[idx, "contact_key"] or "").strip() if "contact_key" in df.columns else ""
        if email_val and "@" in email_val:
            df.at[idx, "person_id"] = "p_" + hashlib.sha256(email_val.encode()).hexdigest()[:8]
            n += 1
        elif chiave:
            df.at[idx, "person_id"] = "p_" + hashlib.sha256(chiave.encode()).hexdigest()[:8]
            n += 1
    if n:
        log.info(
            f"Fallback person_id: {n} unresolved contacts got a deterministic person_id "
            "(hash of the email, or of contact_key when there is no email)"
        )
    return n


def apply_entity_resolution(merged):
    ""
    entity_map_path = ENRICHED_DIR / "entity-map.json"

    if not entity_map_path.exists():
        log.warning(
            "No entity-map.json found — skipping entity resolution (run entity-resolve.py first)"
        )
        merged["person_id"] = ""
        merged["all_emails"] = merged["email"].apply(lambda x: json.dumps([x] if x else []))
        _person_id_di_ripiego(merged)
        return merged

    with open(entity_map_path) as f:
        entity_map = json.load(f)

    log.info(f"Entity map: {len(entity_map)} entries loaded")


    merged["person_id"] = merged["email"].apply(
        lambda e: entity_map.get(e, {}).get("person_id", "") if e else ""
    )
    merged["all_emails"] = merged["email"].apply(
        lambda e: json.dumps(entity_map.get(e, {}).get("all_emails", [e]) if e else [])
    )


    resolved = merged[merged["person_id"] != ""].copy()
    unresolved = merged[merged["person_id"] == ""].copy()

    if len(resolved) == 0:
        log.info("No resolved entities to aggregate")
        _person_id_di_ripiego(merged)
        return merged

    log.info(f"Aggregating {len(resolved)} resolved emails...")


    pid_meta = {}
    for email, info in entity_map.items():
        pid = info.get("person_id", "")
        if pid and pid not in pid_meta:
            pid_meta[pid] = {
                "primary_email": info.get("primary_email", email),
                "canonical_name": info.get("canonical_name", ""),
                "is_internal": info.get("is_internal", False),
                "personio_status": info.get("personio_status", ""),
            }


    def _most_recent_value(group, value_col, date_col="email_last_seen"):
        ""
        valid = group[[value_col, date_col]].dropna(subset=[value_col])
        valid = valid[valid[value_col].astype(str).str.strip() != ""]
        valid = valid[valid[value_col].astype(str).str.lower() != "nan"]
        if valid.empty:
            return ""
        if date_col in valid.columns:
            valid_dates = valid[valid[date_col].notna()]
            if not valid_dates.empty:
                return valid_dates.sort_values(date_col, ascending=False).iloc[0][value_col]
        return valid.iloc[0][value_col]


    agg_rules = {

        "email_msgs_sent": "sum",
        "email_msgs_recv": "sum",
        "email_threads_sent": "sum",
        "email_threads_recv": "sum",
        "email_total_msgs": "sum",
        "email_thread_count": "sum",
        "cal_events": "sum",
        "cal_as_organizer": "sum",
        "plaud_meetings": "sum",
        "plaud_total_minutes": "sum",
        "tactiq_meetings": "sum",
        "tactiq_total_minutes": "sum",
        "linkedin_messages": "sum",
        "slack_messages": "sum",
        "whatsapp_messages": "sum",
        "docusign_contracts": "sum",
        "notion_mentions": "sum",
        "chatgpt_mentions": "sum",
        "plugin_interactions": "sum",
        "plugin_last_seen": "max",
        "plugin_first_seen": "min",
        "has_plugin": "any",
        "plugin_sources": lambda s: "|||".join(
            sorted({p for v in s.dropna() for p in str(v).split("|||") if p})
        ),
        "plugin_title": "first",
        "plugin_url": "first",
        "plugin_email": "first",

        "email_last_sent": "max",
        "email_last_recv": "max",
        "email_last_seen": "max",
        "cal_last_seen": "max",
        "tactiq_last_seen": "max",
        "attio_last_interaction": "max",
        "last_contact": "max",
        "slack_last_seen": "max",
        "wa_last_message": "max",
        "li_last_message_date": "max",
        "ds_last_contract": "max",
        "gd_last_doc": "max",
        "attio_notes_count": "max",
        "attio_meetings_count": "max",
        "attio_connection_strength_num": "max",

        "email_first_seen": "min",
        "cal_first_seen": "min",
        "tactiq_first_seen": "min",
        "attio_first_interaction": "min",
        "first_contact": "min",
        "slack_first_seen": "min",
        "wa_first_message": "min",
        "li_first_message_date": "min",
        "ds_first_contract": "min",
        "gd_first_doc": "min",

        "has_email": "any",
        "has_calendar": "any",
        "has_plaud": "any",
        "has_tactiq": "any",
        "has_attio": "any",
        "has_personio": "any",
        "has_linkedin": "any",
        "has_slack": "any",
        "has_whatsapp": "any",
        "has_docusign": "any",
        "has_iphone": "any",
        "has_notion": "any",
        "has_chatgpt_mention": "any",



        "has_attio_secondclass": "any",
        "has_gdrive": "any",
        "is_internal": "any",
        "is_automated": "all",

        "name": "first",
        "domain": "first",
        "all_emails": "first",
        "attio_name": "first",
        "attio_job_title": "first",
        "attio_relationship_score": "first",
        "attio_connection_strength": "first",
        "attio_sourcing_stage": "first",
        "personio_position": "first",
        "personio_status": "first",
        "personio_subcompany": "first",
        "termination_date": "first",
        "hire_date": "first",
        "linkedin_url": "first",
        "linkedin_headline": "first",
        "slack_user_id": "first",
        "phone_primary": "first",
        "last_contact_source": "first",
        "contact_key": lambda s: next((v for v in s if isinstance(v, str) and v), ""),
        "started_by": lambda s: next((v for v in s if isinstance(v, str) and v), ""),









        "attio_record_id": "first",
        "attio_web_url": "first",
        "attio_sc_record_ids": "first",
        "attio_sc_web_url": "first",
    }


    actual_agg = {k: v for k, v in agg_rules.items() if k in resolved.columns}



    priority_cols = ["attio_name", "linkedin_url", "phone_primary", "slack_user_id"]
    avail_cols = [c for c in priority_cols if c in resolved.columns]
    if avail_cols:
        resolved = resolved.assign(
            _data_richness=resolved[avail_cols].notna().sum(axis=1)
        ).sort_values(["person_id", "_data_richness"], ascending=[True, False])
        resolved = resolved.drop(columns=["_data_richness"])

    aggregated = resolved.groupby("person_id").agg(actual_agg).reset_index()


    for col in ("attio_company", "organization"):
        if col in resolved.columns:
            most_recent = resolved.groupby("person_id").apply(
                lambda g, c=col: _most_recent_value(g, c)
            )
            aggregated[col] = aggregated["person_id"].map(most_recent)
            aggregated[col] = aggregated[col].fillna("")


    aggregated["email"] = aggregated["person_id"].apply(
        lambda pid: pid_meta.get(pid, {}).get("primary_email", "")
    )

    canonical_names = aggregated["person_id"].apply(
        lambda pid: pid_meta.get(pid, {}).get("canonical_name", "")
    )
    has_canonical = canonical_names.notna() & (canonical_names != "")
    aggregated.loc[has_canonical, "name"] = canonical_names[has_canonical]





    if "attio_company" in aggregated.columns and "organization" in aggregated.columns:
        has_attio_co = (
            aggregated["attio_company"].notna()
            & (aggregated["attio_company"] != "")
            & (aggregated["attio_company"].str.lower() != "nan")
        )
        filled = has_attio_co.sum()
        overridden = (
            has_attio_co
            & aggregated["organization"].notna()
            & (aggregated["organization"] != "")
            & (aggregated["organization"] != aggregated["attio_company"])
        ).sum()
        aggregated.loc[has_attio_co, "organization"] = aggregated.loc[has_attio_co, "attio_company"]
        if filled > 0:
            log.info(
                f"Organization from Attio company: {filled} contacts"
                f" ({overridden} overriding Personio subcompany)"
            )


    aggregated["domain"] = aggregated["email"].apply(
        lambda e: e.split("@")[1] if "@" in str(e) else ""
    )


    source_cols = [
        "has_email",
        "has_calendar",
        "has_plaud",
        "has_tactiq",
        "has_attio",
        "has_personio",
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "has_plugin",
    ]
    aggregated["source_count"] = sum(
        aggregated[c].astype(int) for c in source_cols if c in aggregated.columns
    )


    if "is_internal" in aggregated.columns:
        aggregated["is_internal"] = aggregated["is_internal"].astype(bool)


    if "personio_status" in aggregated.columns and "is_internal" in aggregated.columns:
        ex_employees = aggregated["personio_status"].isin(["inactive", "terminated"])
        overridden = (ex_employees & aggregated["is_internal"]).sum()
        aggregated.loc[ex_employees, "is_internal"] = False
        if overridden > 0:
            log.info(f"is_internal override: {overridden} ex-employees set to non-internal")


    if "organization" in aggregated.columns:
        aggregated["org_potentially_stale"] = False
        internal_brands: set[str] = set()  # load from user config
        for idx, row in aggregated.iterrows():
            org = str(row.get("organization", ""))
            primary_domain = str(row.get("domain", ""))
            if not org or not primary_domain:
                continue
            org_lower = org.lower()
            if org_lower in internal_brands:
                if primary_domain not in INTERNAL_DOMAINS:
                    aggregated.at[idx, "org_potentially_stale"] = True
                    log.debug(
                        f"Stale org detected: {row.get('name', '')} org={org} domain={primary_domain}"
                    )
        stale_count = aggregated["org_potentially_stale"].sum()
        if stale_count > 0:
            log.info(f"Stale organization detected: {stale_count} contacts")


    if "organization" in aggregated.columns:
        org_verified = {}
        for pid, grp in resolved.groupby("person_id"):
            org_val = (
                grp["organization"].dropna().iloc[0]
                if not grp["organization"].dropna().empty
                else ""
            )
            if not org_val or str(org_val).lower() in ("nan", ""):
                continue
            if "email_last_seen" in grp.columns:
                dates = grp["email_last_seen"].dropna()
                if not dates.empty:
                    org_verified[pid] = dates.max()
        if org_verified:
            aggregated["org_last_verified"] = aggregated["person_id"].map(org_verified)




    _person_id_di_ripiego(unresolved)

    result = pd.concat([aggregated, unresolved], ignore_index=True)

    log.info(
        f"Entity resolution: {len(resolved)} emails -> "
        f"{len(aggregated)} persons "
        f"({len(resolved) - len(aggregated)} reduced)"
    )
    log.info(f"Total after resolution: {len(result)} contacts")

    return result


def propagate_entity_metadata(merged):
    ""











    entity_map_path = ENRICHED_DIR / "entity-map.json"

    if not entity_map_path.exists():
        log.info("No entity-map.json — skipping metadata propagation")
        return merged

    with open(entity_map_path) as f:
        entity_map = json.load(f)


    pid_metadata = {}
    for email_key, info in entity_map.items():
        pid = info.get("person_id", "")
        if not pid:
            continue

        if pid not in pid_metadata:
            pid_metadata[pid] = {
                "linkedin_urls": [],
                "phones": [],
                "name_sources": set(),
            }


        for url in info.get("linkedin_urls") or []:
            if url and url not in pid_metadata[pid]["linkedin_urls"]:
                pid_metadata[pid]["linkedin_urls"].append(url)


        for phone in info.get("phones") or []:
            if phone and phone not in pid_metadata[pid]["phones"]:
                pid_metadata[pid]["phones"].append(phone)


        for src in info.get("name_sources") or []:
            pid_metadata[pid]["name_sources"].add(src)


    source_to_flag = {
        "linkedin": "has_linkedin",
        "slack": "has_slack",
        "whatsapp": "has_whatsapp",
        "docusign": "has_docusign",
        "iphone": "has_iphone",
        "notion": "has_notion",
        "chatgpt": "has_chatgpt_mention",
        "gdrive": "has_gdrive",
    }

    propagated_linkedin = 0
    propagated_phone = 0
    propagated_flags = 0

    for idx, row in merged.iterrows():
        pid = row.get("person_id", "")
        if not pid or pid not in pid_metadata:
            continue

        meta = pid_metadata[pid]


        current_li = str(row.get("linkedin_url", "") or "").strip()
        if not current_li and meta["linkedin_urls"]:
            merged.at[idx, "linkedin_url"] = meta["linkedin_urls"][0]
            merged.at[idx, "has_linkedin"] = True
            propagated_linkedin += 1


        current_phone = str(row.get("phone_primary", "") or "").strip()
        if not current_phone and meta["phones"]:
            merged.at[idx, "phone_primary"] = meta["phones"][0]
            merged.at[idx, "has_iphone"] = True
            propagated_phone += 1


        for src_name, flag_col in source_to_flag.items():
            if src_name in meta["name_sources"] and flag_col in merged.columns:
                if not merged.at[idx, flag_col]:
                    merged.at[idx, flag_col] = True
                    propagated_flags += 1


    source_flags = [
        "has_email",
        "has_calendar",
        "has_plaud",
        "has_tactiq",
        "has_attio",
        "has_personio",
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "has_plugin",
    ]
    merged["source_count"] = sum(merged[c].astype(int) for c in source_flags if c in merged.columns)

    log.info(
        f"Metadata propagation from entity-map: "
        f"{propagated_linkedin} linkedin_url, "
        f"{propagated_phone} phone, "
        f"{propagated_flags} source flags updated"
    )

    return merged





def compute_cross_source_score(row) -> float:
    ""





















    if row.get("is_automated", False):
        return 0.0

    now = datetime.now(UTC)


    email_msgs = min(row.get("email_total_msgs", 0), 1000)
    email_freq = (math.log1p(email_msgs) / math.log1p(1000)) * 16 if email_msgs > 0 else 0


    cal_events = min(row.get("cal_events", 0), 300)
    cal_freq = (math.log1p(cal_events) / math.log1p(300)) * 14 if cal_events > 0 else 0


    plaud = min(row.get("plaud_meetings", 0), 20)
    plaud_score = (math.log1p(plaud) / math.log1p(20)) * 5 if plaud > 0 else 0


    tactiq = min(row.get("tactiq_meetings", 0), 50)
    tactiq_score = (math.log1p(tactiq) / math.log1p(50)) * 4 if tactiq > 0 else 0


    attio_notes = min(row.get("attio_notes_count", 0), 20)
    attio_meetings = min(row.get("attio_meetings_count", 0), 50)
    attio_conn = min(row.get("attio_connection_strength_num", 0), 100)
    attio_score = (attio_notes / 20) * 1.5 + (attio_meetings / 50) * 1.0 + (attio_conn / 100) * 1.5


    linkedin_msgs = min(row.get("linkedin_messages", 0), 100)
    has_li = bool(row.get("has_linkedin", False))
    linkedin_score = 0
    if has_li:
        linkedin_score = 1.0
        if linkedin_msgs > 0:
            linkedin_score += (math.log1p(linkedin_msgs) / math.log1p(100)) * 2.0


    slack_msgs = min(row.get("slack_messages", 0), 5000)
    slack_score = (math.log1p(slack_msgs) / math.log1p(5000)) * 3 if slack_msgs > 0 else 0


    wa_msgs = min(row.get("whatsapp_messages", 0), 5000)
    wa_score = (math.log1p(wa_msgs) / math.log1p(5000)) * 2 if wa_msgs > 0 else 0


    doc_contracts = min(row.get("docusign_contracts", 0), 20)
    doc_score = (math.log1p(doc_contracts) / math.log1p(20)) * 1 if doc_contracts > 0 else 0

    # Generic plugin intake (issues, PRs, meetings, records…): same weight as Slack.
    try:
        plugin_n = min(int(row.get("plugin_interactions", 0) or 0), 500)
    except (TypeError, ValueError):
        plugin_n = 0
    plugin_score = (math.log1p(plugin_n) / math.log1p(500)) * 3 if plugin_n > 0 else 0


    last = row.get("last_contact")
    if pd.notna(last):
        if hasattr(last, "tzinfo") and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        days_ago = max(0, (now - last).days)
        recency = math.exp(-days_ago / 365) * 20
    else:
        recency = 0


    sent = row.get("email_msgs_sent", 0)
    recv = row.get("email_msgs_recv", 0)
    if sent + recv > 0:
        balance = min(sent, recv) / max(sent, recv) if max(sent, recv) > 0 else 0
        bidir = balance * 9
    else:
        bidir = 0


    threads = min(row.get("email_thread_count", 0), 300)
    thread_score = (math.log1p(threads) / math.log1p(300)) * 5 if threads > 0 else 0




    multi_source = 0


    personio_status = str(row.get("personio_status", ""))
    if personio_status == "active":
        personio_bonus = 5
    elif personio_status in ("inactive", "onboarding"):
        personio_bonus = 3
    else:
        personio_bonus = 0

    total = (
        email_freq
        + cal_freq
        + plaud_score
        + tactiq_score
        + attio_score
        + linkedin_score
        + slack_score
        + wa_score
        + doc_score
        + plugin_score
        + recency
        + bidir
        + thread_score
        + multi_source
        + personio_bonus
    )
    return round(total, 1)





def export_results(merged: pd.DataFrame, top_n: int = 100):
    ""


    before_names = merged["name"].copy()
    merged["name"] = merged["name"].apply(normalize_name_case)
    normalized_count = (merged["name"] != before_names).sum()
    if normalized_count > 0:
        log.info(f"Name case normalization: {normalized_count} names fixed (ALL CAPS/lowercase)")


    merged["score"] = merged.apply(compute_cross_source_score, axis=1)


    null_scores = merged["score"].isna().sum()
    merged["score"] = merged["score"].fillna(0.0)
    if null_scores > 0:
        log.info(f"Score fix: {null_scores} NULL scores set to 0.0")

    merged.sort_values("score", ascending=False, inplace=True)


    merged_path = ENRICHED_DIR / "contacts-merged.parquet"
    safe_write_parquet(merged, merged_path, index=False)
    log.info(f"Saved contacts-merged: {len(merged)} rows -> {merged_path}")


    score_cols = [
        "email",
        "name",
        "domain",
        "person_id",
        "all_emails",
        "is_internal",
        "first_contact",
        "last_contact",
        "email_msgs_sent",
        "email_msgs_recv",
        "email_total_msgs",
        "email_thread_count",
        "cal_events",
        "plaud_meetings",
        "tactiq_meetings",
        "attio_notes_count",
        "attio_meetings_count",
        "linkedin_messages",
        "slack_messages",
        "whatsapp_messages",
        "docusign_contracts",
        "notion_mentions",
        "chatgpt_mentions",
        "has_email",
        "has_calendar",
        "has_plaud",
        "has_tactiq",
        "has_attio",
        "has_personio",
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "gdrive_docs",
        "slack_last_seen",
        "slack_first_seen",
        "wa_last_message",
        "wa_first_message",
        "li_last_message_date",
        "li_first_message_date",
        "ds_last_contract",
        "ds_first_contract",
        "gd_last_doc",
        "gd_first_doc",
        "has_plugin",
        "plugin_sources",
        "plugin_interactions",
        "plugin_first_seen",
        "plugin_last_seen",
        "plugin_title",
        "plugin_url",
        "last_contact_source",
        "personio_position",
        "personio_status",
        "personio_subcompany",
        "termination_date",
        "hire_date",
        "linkedin_url",
        "linkedin_headline",
        "slack_user_id",
        "phone_primary",
        "organization",
        "is_automated",
        "source_count",
        "score",
    ]

    score_cols = [c for c in score_cols if c in merged.columns]
    scores_path = EXPORTS_DIR / "relationship-scores.parquet"
    safe_write_parquet(merged[score_cols], scores_path, index=False)
    log.info(f"Saved relationship scores: {len(merged)} rows -> {scores_path}")


    top = merged.head(top_n)

    all_source_flags = [
        "has_email",
        "has_calendar",
        "has_plaud",
        "has_tactiq",
        "has_attio",
        "has_personio",
        "has_linkedin",
        "has_slack",
        "has_whatsapp",
        "has_docusign",
        "has_iphone",
        "has_notion",
        "has_chatgpt_mention",
        "has_gdrive",
        "has_plugin",
    ]

    graph = {
        "generated": datetime.now(UTC).isoformat(),
        "scoring_version": "cross-source-v5",
        "scoring_weights": {
            "email_frequency": 0.16,
            "calendar_frequency": 0.14,
            "plaud_meetings": 0.05,
            "tactiq_meetings": 0.04,
            "attio_crm": 0.04,
            "linkedin_engagement": 0.03,
            "slack_engagement": 0.03,
            "whatsapp_engagement": 0.02,
            "docusign_contracts": 0.01,
            "plugin_engagement": 0.03,
            "recency": 0.20,
            "bidirectionality": 0.09,
            "thread_depth": 0.05,
            "multi_source_bonus": 0.09,
            "personio_bonus": 0.05,
        },
        "total_contacts": len(merged),
        "sources": {},
        "nodes": [],
        "summary": {
            "top_10": [],
            "dormant_30d": 0,
            "active_7d": 0,
            "calendar_only_contacts": 0,
        },
    }


    source_labels = {
        "has_email": "email_contacts",
        "has_calendar": "calendar_contacts",
        "has_plaud": "plaud_contacts",
        "has_tactiq": "tactiq_contacts",
        "has_attio": "attio_contacts",
        "has_personio": "personio_contacts",
        "has_linkedin": "linkedin_contacts",
        "has_slack": "slack_contacts",
        "has_whatsapp": "whatsapp_contacts",
        "has_docusign": "docusign_contacts",
        "has_iphone": "iphone_contacts",
        "has_notion": "notion_contacts",
        "has_chatgpt_mention": "chatgpt_mentions",
        "has_gdrive": "gdrive_contacts",
        "has_plugin": "plugin_contacts",
    }
    for flag, label in source_labels.items():
        if flag in merged.columns:
            graph["sources"][label] = int(merged[flag].sum())
    graph["sources"]["multi_source"] = int((merged["source_count"] >= 2).sum())


    if "last_contact" in merged.columns:
        graph["summary"]["dormant_30d"] = int(
            (merged["last_contact"] < (datetime.now(UTC) - pd.Timedelta(days=30))).sum()
        )
        graph["summary"]["active_7d"] = int(
            (merged["last_contact"] >= (datetime.now(UTC) - pd.Timedelta(days=7))).sum()
        )
    graph["summary"]["calendar_only_contacts"] = int(
        (~merged["has_email"] & merged["has_calendar"]).sum()
    )

    for _, r in top.head(10).iterrows():
        graph["summary"]["top_10"].append(
            {
                "email": r["email"],
                "name": r["name"],
                "score": r["score"],
                "sources": int(r["source_count"]),
            }
        )

    for _, r in top.iterrows():

        def safe_int(val, default=0):
            try:
                return int(val) if pd.notna(val) else default
            except (ValueError, TypeError):
                return default

        def safe_str(val, default=""):
            try:
                return str(val) if pd.notna(val) and val else default
            except (ValueError, TypeError):
                return default

        node = {
            "email": r["email"],
            "name": r["name"],
            "domain": r.get("domain", ""),
            "score": r["score"],
            "email_msgs_sent": safe_int(r.get("email_msgs_sent", 0)),
            "email_msgs_recv": safe_int(r.get("email_msgs_recv", 0)),
            "cal_events": safe_int(r.get("cal_events", 0)),
            "plaud_meetings": safe_int(r.get("plaud_meetings", 0)),
            "tactiq_meetings": safe_int(r.get("tactiq_meetings", 0)),
            "attio_notes_count": safe_int(r.get("attio_notes_count", 0)),
            "attio_meetings_count": safe_int(r.get("attio_meetings_count", 0)),
            "linkedin_messages": safe_int(r.get("linkedin_messages", 0)),
            "slack_messages": safe_int(r.get("slack_messages", 0)),
            "whatsapp_messages": safe_int(r.get("whatsapp_messages", 0)),
            "plugin_interactions": safe_int(r.get("plugin_interactions", 0)),
            "docusign_contracts": safe_int(r.get("docusign_contracts", 0)),
            "source_count": safe_int(r["source_count"]),
            "linkedin_url": safe_str(r.get("linkedin_url")),
            "phone_primary": safe_str(r.get("phone_primary")),
            "first_contact": r["first_contact"].isoformat()
            if pd.notna(r.get("first_contact"))
            else None,
            "last_contact": r["last_contact"].isoformat()
            if pd.notna(r.get("last_contact"))
            else None,
        }
        graph["nodes"].append(node)


    graph_path = EXPORTS_DIR / "contacts-summary.json"
    safe_write_json(graph_path, graph)
    log.info(f"Saved contacts summary: {len(graph['nodes'])} nodes -> {graph_path}")

    return merged





def main():
    from sbk_config import acquire_pid_lock

    parser = argparse.ArgumentParser(description="Cross-source merge V5 — SBK")
    parser.add_argument(
        "--top", type=int, default=200, help="Top N contacts in graph (default: 200)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip merge if no source files changed since last run",
    )
    args = parser.parse_args()
    # Take the lock only after the arguments are parsed, so --help writes nothing.
    if not acquire_pid_lock("xs-l2-merge", logger=log):
        log.warning("Another merge instance running: lock held, exit 75")
        sys.exit(75)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Phones written without a country code get yours (SBK_PHONE_CC, else "phone_country_code"
    # in sbk.config.json): normalize_phone() reads it, here and in every other step.
    cc = phone_country_code()
    log.info(
        f"Phone country code: +{cc}"
        if cc
        else "Phone country code: none set (numbers compared as written)"
    )


    if args.incremental:
        changed, changed_sources = check_sources_changed()
        if not changed:
            log.info("All source files unchanged — skipping merge (incremental mode)")
            return
        log.info(f"Sources changed: {', '.join(changed_sources)} — running merge")


    email_contacts, email_interactions = load_email_data()
    cal_contacts = load_calendar_data()
    plaud_df = load_plaud_data()
    tactiq_df = load_tactiq_data()
    attio_df = load_attio_data()
    personio_df = load_personio_data()
    plugin_df = load_plugin_data()
    # WhatsApp and the address book start contacts too (keyed by phone when no email matches)
    whatsapp_df = load_whatsapp_data()
    iphone_df = load_iphone_data()
    nessuno = (
        email_contacts is None
        and cal_contacts is None
        and plugin_df is None
        and (whatsapp_df is None or len(whatsapp_df) == 0)
        and (iphone_df is None or len(iphone_df) == 0)
    )

    if nessuno and not (ENRICHED_DIR / "contacts-merged.parquet").exists():
        # A first install whose sources only enrich people (LinkedIn, Slack...): nobody
        # starts a contact yet, and there is no earlier book to protect.
        log.info(
            "Nothing to merge yet: no source that starts a contact has data (mail, calendar, "
            "WhatsApp, Telegram, the address book, or a plugin with people). LinkedIn, Slack "
            "and the other sources only enrich the people found there."
        )
        return
    if nessuno:
        log.error(
            "No data sources available. Run the email and/or calendar L1 first, "
            "or a plugin that writes processed/plugin-contacts.parquet."
        )
        sys.exit(1)


    merged = merge_contacts_phase1(
        email_contacts, email_interactions, cal_contacts, plaud_df, tactiq_df, attio_df, personio_df
    )
    phase1_count = len(merged)



    linkedin_url_map = build_linkedin_url_map(attio_df)


    linkedin_df = load_linkedin_data()
    slack_df = load_slack_data()
    docusign_df = load_docusign_data()
    attio_sc_df = load_attio_seconda_classe_data()
    notion_df = load_notion_data()
    chatgpt_df = load_chatgpt_data()

    da_verificare: list[dict] = []
    merged, match_stats = merge_contacts_phase2(
        merged,
        linkedin_df,
        slack_df,
        whatsapp_df,
        docusign_df,
        iphone_df,
        notion_df,
        chatgpt_df,
        linkedin_url_map=linkedin_url_map,
        attio_sc_df=attio_sc_df,
        da_verificare=da_verificare,
        verifiche=carica_verifiche(),
        plugin_df=plugin_df,
    )
    verificati = sum(s.get("verificati", 0) for s in match_stats.values())
    log.info(
        f"Phase 2: {len(da_verificare)} name matches set aside for verification and not applied "
        f"(), {verificati} matched because verified by you"
    )


    merged = apply_entity_resolution(merged)


    merged = propagate_entity_metadata(merged)

    # One number, one form: the book stores every phone the way normalize_phone() writes it
    # ("+447700900123"), whatever source wrote it first, so a later step that compares phones
    # as text agrees with the merge. A value that is not a number is kept as written.
    merged["phone_primary"] = merged["phone_primary"].map(
        lambda v: (normalize_phone(str(v)) or str(v).strip()) if not _vuoto(v) else ""
    )

    if args.dry_run:
        log.info("\n=== DRY RUN — No files written ===")
        log.info(f"Total unique contacts: {len(merged)}")
        log.info(f"Phase 1 contacts (email-keyed): {phase1_count}")


        log.info("\n── Phase 1 sources ──")
        log.info(
            f"Email-only: {(merged['has_email'] & ~merged['has_calendar'] & ~merged['has_plaud'] & ~merged['has_tactiq']).sum()}"
        )
        log.info(
            f"Calendar-only: {(~merged['has_email'] & merged['has_calendar'] & ~merged['has_plaud'] & ~merged['has_tactiq']).sum()}"
        )
        log.info(
            f"Tactiq-only: {(~merged['has_email'] & ~merged['has_calendar'] & ~merged['has_plaud'] & merged['has_tactiq'] & ~merged['has_attio']).sum()}"
        )
        log.info(
            f"Attio-only: {(~merged['has_email'] & ~merged['has_calendar'] & ~merged['has_plaud'] & ~merged['has_tactiq'] & merged['has_attio']).sum()}"
        )
        log.info(
            f"Personio-only: {(~merged['has_email'] & ~merged['has_calendar'] & ~merged['has_plaud'] & ~merged['has_tactiq'] & ~merged['has_attio'] & merged['has_personio']).sum()}"
        )


        log.info("\n── Phase 2 enrichment ──")
        for flag in [
            "has_linkedin",
            "has_slack",
            "has_whatsapp",
            "has_docusign",
            "has_iphone",
            "has_notion",
            "has_chatgpt_mention",
            "has_gdrive",
            "has_plugin",
        ]:
            log.info(f"  {flag}: {merged[flag].sum()}")

        log.info("\n── Overall ──")
        log.info(f"Multi-source (2+): {(merged['source_count'] >= 2).sum()}")
        log.info(f"Multi-source (5+): {(merged['source_count'] >= 5).sum()}")
        log.info(f"Max sources: {merged['source_count'].max()}")
        log.info(f"Entity-resolved: {(merged['person_id'].astype(str).str.len() > 0).sum()}")
        log.info(f"Internal (org): {merged['is_internal'].sum()}")
        log.info(f"Automated (score=0): {merged['is_automated'].sum()}")
        log.info(f"With phone: {(merged['phone_primary'].astype(str).str.len() > 2).sum()}")
        log.info(f"With LinkedIn URL: {(merged['linkedin_url'].astype(str).str.len() > 5).sum()}")


        before_names = merged["name"].copy()
        merged["name"] = merged["name"].apply(normalize_name_case)
        normalized_count = (merged["name"] != before_names).sum()
        if normalized_count > 0:
            log.info(
                f"Name case normalization: {normalized_count} names fixed (ALL CAPS/lowercase)"
            )


        merged["score"] = merged.apply(compute_cross_source_score, axis=1)
        merged["score"] = merged["score"].fillna(0.0)
        merged.sort_values("score", ascending=False, inplace=True)

        all_flags = [
            ("email", "has_email"),
            ("cal", "has_calendar"),
            ("plaud", "has_plaud"),
            ("tactiq", "has_tactiq"),
            ("attio", "has_attio"),
            ("personio", "has_personio"),
            ("linkedin", "has_linkedin"),
            ("slack", "has_slack"),
            ("whatsapp", "has_whatsapp"),
            ("docusign", "has_docusign"),
            ("iphone", "has_iphone"),
            ("notion", "has_notion"),
            ("chatgpt", "has_chatgpt_mention"),
            ("gdrive", "has_gdrive"),
            ("plugin", "has_plugin"),
        ]

        log.info("\nTop 30 by cross-source score (V5):")
        for i, (_, r) in enumerate(merged.head(30).iterrows()):
            sources = [label for label, flag in all_flags if r.get(flag)]
            pid = f"  pid={r['person_id']}" if r.get("person_id") else ""
            log.info(
                f"  {i + 1:2d}. {r['name'] or r['email']:40s} "
                f"score={r['score']:5.1f}  src={int(r['source_count']):2d}  "
                f"[{'+'.join(sources)}]{pid}"
            )


        log.info("\n--- Key people check ---")
        key_people: list[str] = []  # load from user config
        for name_check in key_people:
            matches = merged[merged["name"].str.contains(name_check, case=False, na=False)]
            for _, m in matches.head(3).iterrows():
                src_list = [label for label, flag in all_flags if m.get(flag)]
                log.info(
                    f"  {m['name']:35s} score={m['score']:5.1f}  "
                    f"emails={int(m.get('email_total_msgs', 0)):4d}  "
                    f"cal={int(m.get('cal_events', 0)):3d}  "
                    f"src={int(m['source_count'])}  [{'+'.join(src_list)}]"
                )
        return


    result = export_results(merged, top_n=args.top)
    scrivi_da_verificare(da_verificare)
    log.info(f"Cases to verify: {len(da_verificare)} in {DA_VERIFICARE_FILE}")


    old_scores_path = EXPORTS_DIR / "relationship-scores-email-only.parquet"
    if not old_scores_path.exists():
        old_path = EXPORTS_DIR / "relationship-scores.parquet"
        if old_path.exists():
            log.info("Note: old scores have been replaced with cross-source V5 scores")


    _save_merge_checkpoint(_compute_source_hashes())

    log.info("\n=== Cross-source merge V5 complete ===")
    log.info(f"Contacts merged: {len(result)}")
    log.info(f"Phase 1 (email-keyed): {phase1_count}")
    log.info(
        f"Phase 2 enriched: "
        f"{result[['has_linkedin', 'has_slack', 'has_whatsapp', 'has_docusign', 'has_iphone', 'has_notion', 'has_chatgpt_mention', 'has_plugin']].any(axis=1).sum()}"
    )
    if len(result):
        log.info(f"Top score: {result.iloc[0]['name']} ({result.iloc[0]['score']})")
    else:
        # e.g. only people that enrich contacts so far (LinkedIn connections, Slack members)
        log.info("No contact yet: the merged book is empty for now")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-merge", source="l2-merge", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
