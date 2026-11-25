#!/usr/bin/env python3
""






















































import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from name_variants import NameEquivalenceDB  # noqa: E402
from text_utils import normalize_gmail, normalize_phone, strip_accents  # noqa: E402

from sbk_config import (
    ATTIO_PROCESSED_DIR,
    CONFIDENZA_ALTA,
    DOCUSIGN_DIR,
    ENRICHED_DIR,
    INTERNAL_DOMAINS,
    IPHONE_DIR,
    LINKEDIN_DIR,
    NICKNAME_ALIASES,
    NOTION_DIR,
    OWN_EMAILS,
    OWN_ORG_NAMES,
    OWNER_FIRST_NAME,
    PERSONIO_DIR,
    PERSONIO_PROCESSED_DIR,
    SLACK_DIR,
    WHATSAPP_DIR,
    confidenza_almeno,
    is_own_name,
    safe_write_json,
    user_cfg,
)

ATTIO_DIR = ATTIO_PROCESSED_DIR

DECISIONS_FILE = ENRICHED_DIR / "entity-decisions.json"

log = logging.getLogger("entity-resolve")



# Other spellings of a domain -> the domain to use ("organisations.domain_aliases" in
# sbk.config.json), e.g. {"democo.co.example": "democo.example"}. Empty by default.
DOMAIN_ALIASES: dict[str, str] = {
    str(k).strip().lower(): str(v).strip().lower()
    for k, v in (user_cfg("organisations.domain_aliases", {}) or {}).items()
}




def load_persistent_decisions():
    ""




    if not DECISIONS_FILE.exists():
        log.info("No persistent decisions file found, skipping")
        return 0, 0

    with open(DECISIONS_FILE) as f:
        data = json.load(f)

    decisions = data.get("decisions", [])
    merge_count = 0
    reject_count = 0


    merge_uf = UnionFind()
    merge_names = {}

    for d in decisions:
        keys = d.get("keys", [])
        action = d.get("action", "")
        if len(keys) < 2:
            continue

        if action == "merge":
            merge_uf.union(keys[0], keys[1], check_rejects=False)
            merge_count += 1

            for k in keys:
                if k.startswith("nameonly:"):
                    parts = k.split(":", 2)
                    if len(parts) == 3:
                        merge_names[k] = parts[2].title()

        elif action == "reject":
            MANUAL_REJECTS.append(set(keys[:2]))
            reject_count += 1


    merge_clusters = merge_uf.clusters()
    for _root, cluster_keys in merge_clusters.items():
        if len(cluster_keys) < 2:
            continue
        keys_list = sorted(cluster_keys)
        canonical_name = ""
        for k in keys_list:
            if k in merge_names:
                canonical_name = merge_names[k]
                break
        MANUAL_MERGES.append(
            {
                "emails": keys_list,
                "canonical_name": canonical_name,
                "reason": "persistent_decision: auto/manual from entity-decisions.json",
            }
        )

    log.info(
        f"Persistent decisions loaded: {merge_count} merges "
        f"({len([c for c in merge_clusters.values() if len(c) >= 2])} clusters), "
        f"{reject_count} rejects"
    )
    return merge_count, reject_count





def backup_outputs(max_backups=3):
    ""



    entity_map_path = ENRICHED_DIR / "entity-map.json"
    review_path = ENRICHED_DIR / "entity-review.json"
    stats_path = ENRICHED_DIR / "entity-stats.json"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for f in [entity_map_path, review_path, stats_path]:
        if not f.exists():
            continue
        backup = f.with_suffix(f".{timestamp}.bak")
        shutil.copy2(f, backup)
        log.info(f"Backup: {f.name} -> {backup.name}")


        pattern = f"{f.stem}.*.bak"
        backups = sorted(f.parent.glob(pattern), key=lambda p: p.stat().st_mtime)
        if len(backups) > max_backups:
            for old_backup in backups[: len(backups) - max_backups]:
                old_backup.unlink()
                log.info(f"Cleanup: removed old backup {old_backup.name}")






NEGATIVE_CONSTRAINTS: set[frozenset] = set()


def build_negative_constraints():
    ""






    interactions_path = ENRICHED_DIR / "interactions.parquet"
    calendar_path = ENRICHED_DIR / "interactions-calendar.parquet"

    count = 0

    if interactions_path.exists():
        df = pd.read_parquet(interactions_path, columns=["from_email", "to_email"])
        for _, row in df.iterrows():
            from_email = str(row["from_email"]).strip().lower()
            to_email = str(row["to_email"]).strip().lower()
            if from_email and to_email and from_email != to_email:
                NEGATIVE_CONSTRAINTS.add(frozenset([from_email, to_email]))
        count += len(df)
        log.info(f"Negative constraints from interactions: {len(df)} pairs")

    if calendar_path.exists():
        df2 = pd.read_parquet(calendar_path, columns=["from_email", "to_email"])
        before = len(NEGATIVE_CONSTRAINTS)
        for _, row in df2.iterrows():
            from_email = str(row["from_email"]).strip().lower()
            to_email = str(row["to_email"]).strip().lower()
            if from_email and to_email and from_email != to_email:
                NEGATIVE_CONSTRAINTS.add(frozenset([from_email, to_email]))
        added = len(NEGATIVE_CONSTRAINTS) - before
        log.info(f"Negative constraints from calendar: {len(df2)} pairs ({added} new)")

    log.info(f"Total negative constraints: {len(NEGATIVE_CONSTRAINTS)}")
    return len(NEGATIVE_CONSTRAINTS)





MANUAL_MERGES: list[dict] = [
    # Manual identity merges; load from user config. Example format:
    # {
    #     "emails": ["sam.s@acme.example", "sam.taylor@example.com"],
    #     "canonical_name": "Sam Taylor",
    #     "reason": "manual_override: same person, two addresses",
    # },
]




# Manual name overrides keyed on email ({"address": "Name"}). Nothing is built in.
NAME_OVERRIDES: dict[str, str] = {}





MANUAL_REJECTS: list[set] = []



AMBIGUOUS_PREFIXES = {"samt", "miac", "alexr", "global"}


SHARED_INBOX_PREFIXES = {
    "info",
    "billing",
    "support",
    "marketing",
    "team",
    "hello",
    "hr",
    "recruiting",
    "admin",
    "sales",
    "newsletter",
    "contact",
    "administration",
    "global",
    "orders",
    "segreteria",
    "service",
    "noreply",
    "no-reply",

    "investors",
    "customer.success",
}


NAME_STRIP_SUFFIXES = [
    "inc",
    "inc 2",
    "facebook",
    "fb",
    "instagram",
    "ig",
    "linkedin",
    "whatsapp",
    "wa",
    "telegram",
    "tg",
    "work",
    "lavoro",
    "ufficio",
    "casa",
    "personal",
    "personale",
    "vecchio",
    "old",
    "new",
    "nuovo",
    "iphone",
    "phone",
    "tel",
    "mobile",
    "cell",
    # your own organisations' names ("organisations" in sbk.config.json), e.g. "Sam Demo Co"
    *sorted(OWN_ORG_NAMES),
]



COMMON_FIRST_NAMES = {
    "marco",
    "laura",
    "luca",
    "andrea",
    "francesco",
    "giuseppe",
    "giovanni",
    "maria",
    "anna",
    "carlo",
    "mario",
    "paolo",
    "sara",
    "alessandro",
    "stefano",
    "roberto",
    "antonio",
    "davide",
    "matteo",
    "simone",
    "federica",
    "giulia",
    "chiara",
    "valentina",
    "martina",
    "john",
    "david",
    "michael",
    "james",
    "robert",
    "daniel",
    "thomas",
    "mark",
    "peter",
    "paul",
    "chris",
    "alex",
    "max",
    "nick",
}



AMBIGUOUS_SINGLE_NAMES = {
    "marco",
    "andrea",
    "giuseppe",
    "giovanni",
    "francesco",
    "antonio",
    "luigi",
    "maria",
    "anna",
    "laura",
    "sara",
    "stefano",
    "alessandro",
    "roberto",
    "carlo",
}
# your own first name alone is ambiguous too (sbk.config.json "owner")
if OWNER_FIRST_NAME:
    AMBIGUOUS_SINGLE_NAMES.add(OWNER_FIRST_NAME)


COMPANY_NAME_KEYWORDS = {
    "agency",
    "model",
    "team",
    "holding",
    "group",
    "srl",
    "spa",
    "ltd",
    "inc",
    "gmbh",
    "llc",
    "consulting",
    "solutions",
    "services",
    "s.r.l",
    "s.p.a",
}


COMMON_SURNAMES = {

    "rossi",
    "russo",
    "ferrari",
    "esposito",
    "bianchi",
    "romano",
    "colombo",
    "ricci",
    "marino",
    "greco",
    "bruno",
    "gallo",
    "conti",
    "de luca",
    "costa",
    "giordano",
    "mancini",
    "rizzo",
    "lombardi",
    "moretti",
    "barbieri",
    "fontana",
    "santoro",
    "mariani",
    "rinaldi",
    "caruso",
    "ferrara",
    "galli",
    "martini",
    "leone",
    "longo",
    "gentile",
    "martinelli",
    "vitale",
    "lombardo",
    "serra",
    "coppola",
    "de santis",
    "d'angelo",
    "marchetti",
    "parisi",
    "villa",
    "conte",
    "ferraro",
    "ferri",
    "fabbri",
    "bianco",
    "marini",
    "grasso",
    "valentini",
    "sala",

    "smith",
    "johnson",
    "williams",
    "brown",
    "jones",
    "garcia",
    "martinez",
    "rodriguez",
    "wilson",
    "anderson",
    "taylor",
    "thomas",
    "jackson",
    "white",
    "harris",
    "martin",
    "thompson",
    "moore",
    "young",
    "allen",
    "king",
    "wright",
    "scott",
    "hill",
    "green",
    "adams",
    "baker",
    "nelson",
    "carter",
    "mitchell",
    "roberts",
    "turner",
    "phillips",

    "sharma",
    "kumar",
    "singh",
    "gupta",
    "patel",
    "agarwal",
    "jain",
    "das",
    "mukherjee",
    "chatterjee",
    "shah",
    "mehta",
    "verma",

    "mueller",
    "schmidt",
    "schneider",
    "fischer",
    "weber",
    "meyer",
    "lee",
    "kim",
    "park",
    "chen",
    "wang",
    "zhang",
    "liu",
    "yang",
    "nguyen",
    "tran",
}


def _is_common_surname(name_parts: list[str]) -> bool:
    ""




    if not name_parts:
        return False

    if name_parts[-1] in COMMON_SURNAMES:
        return True

    if len(name_parts) >= 3:
        compound = f"{name_parts[-2]} {name_parts[-1]}"
        if compound in COMMON_SURNAMES:
            return True

    if len(name_parts) >= 2 and name_parts[-1].startswith("d'"):
        if name_parts[-1] in COMMON_SURNAMES:
            return True
    return False





class UnionFind:
    ""







    def __init__(self):
        self.parent = {}
        self.rank = {}
        self._members = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self._members[x] = {x}
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def get_members(self, x):
        ""
        root = self.find(x)
        return self._members.get(root, {x})

    def union(self, x, y, check_rejects=True, check_negative=True):
        ""




        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return True

        if check_rejects and MANUAL_REJECTS:
            if is_rejected_pair(x, y) or is_rejected_pair(rx, ry):
                return False


        if check_negative and NEGATIVE_CONSTRAINTS:
            if self._violates_negative_constraint(rx, ry):
                return False


        if self._would_exceed_nameonly_limit(rx, ry, max_per_source=5):
            log.debug(
                f"Union blocked: cluster size guard — merging {x} + {y} "
                f"would exceed 5 nameonly entries from same source"
            )
            return False

        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

        self._members.setdefault(rx, {rx})
        self._members.setdefault(ry, {ry})
        self._members[rx] |= self._members[ry]
        del self._members[ry]
        return True

    def _violates_negative_constraint(self, rx, ry):
        ""





        emails_x = [k for k in self._members.get(rx, set()) if is_key_email(k)]
        emails_y = [k for k in self._members.get(ry, set()) if is_key_email(k)]

        for ex in emails_x:
            for ey in emails_y:
                if frozenset([ex, ey]) in NEGATIVE_CONSTRAINTS:
                    return True
        return False

    def _would_exceed_nameonly_limit(self, rx, ry, max_per_source=5):
        ""




        members_x = self._members.get(rx, set())
        members_y = self._members.get(ry, set())
        source_counts = defaultdict(int)
        for k in members_x | members_y:
            if k.startswith("nameonly:"):
                parts = k.split(":", 2)
                if len(parts) >= 2:
                    source_counts[parts[1]] += 1
        return any(c > max_per_source for c in source_counts.values())

    def clusters(self):
        groups = defaultdict(set)
        for x in self.parent:
            groups[self.find(x)].add(x)
        return dict(groups)





def normalize_name(name: str) -> str:
    ""
    if not name or not isinstance(name, str):
        return ""
    name = name.strip().lower()
    name = re.sub(r"\b(dr|dott|ing|prof|sig|sig\.ra)\b\.?\s*", "", name)

    name = re.sub(r"\bd[''\u2019]", "d'", name)
    return " ".join(name.split())


def normalize_name_v2(name: str) -> str:
    ""




    if not name or not isinstance(name, str):
        return ""
    name = name.strip()

    name = re.sub(r"\s+(?:from|at|presso|via|per)\s+\S.*$", "", name, flags=re.IGNORECASE)

    name = re.sub(r"\s*[\|]\s*.*$", "", name)

    name = strip_accents(name)
    name = name.lower()

    name = re.sub(r"\b(dr|dott|ing|prof|sig|sig\.ra|mr|mrs|ms)\b\.?\s*", "", name)

    name = re.sub(r"\bd[''\u2019]", "d'", name)

    for suffix in sorted(NAME_STRIP_SUFFIXES, key=len, reverse=True):

        pattern = r"[\s\-\(]*\b" + re.escape(suffix) + r"\b[\)\s]*$"
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)

    name = re.sub(r"\([^)]*\)", "", name)

    name = re.sub(r"\d+", "", name)

    name = re.sub(r"[^a-z '\-]", "", name)

    name = " ".join(name.split())
    return name.strip()


def is_shared_inbox(email: str) -> bool:
    ""
    if "@" not in email:
        return False
    local, domain = email.split("@", 1)
    if domain not in INTERNAL_DOMAINS:
        return False
    prefix = local.split(".")[0] if "." in local else local
    return prefix in SHARED_INBOX_PREFIXES


def extract_name_from_email(email: str) -> str:
    ""
    if "@" not in email:
        return ""
    local = email.split("@")[0]

    name = re.sub(r"\d+", "", local)

    parts = re.split(r"[._\-]", name)
    parts = [p for p in parts if len(p) > 1]
    if len(parts) >= 2:
        return " ".join(parts)
    return ""


def is_rejected_pair(key_a: str, key_b: str) -> bool:
    ""
    pair = frozenset([key_a, key_b])
    for reject in MANUAL_REJECTS:
        if pair == frozenset(reject):
            return True
    return False


def import_panel_decisions(decisions_path: str) -> tuple[list[dict], list[set], int, int]:
    ""













    path = Path(decisions_path)
    if not path.exists():
        log.error(f"Decisions file not found: {decisions_path}")
        return [], [], 0, 0

    with open(path) as f:
        decisions = json.load(f)

    merge_pairs = decisions.get("merge", [])
    reject_pairs = decisions.get("reject", [])




    merge_uf = UnionFind()
    for pair in merge_pairs:
        if len(pair) >= 2:
            for key in pair[1:]:
                merge_uf.union(pair[0], key)

    merge_clusters = merge_uf.clusters()
    new_merges = []
    for _root, keys in merge_clusters.items():
        if len(keys) < 2:
            continue
        keys_list = sorted(keys)

        canonical_name = ""
        for k in keys_list:
            if k.startswith("nameonly:"):

                parts = k.split(":", 2)
                if len(parts) == 3:
                    canonical_name = parts[2].title()
                    break
        new_merges.append(
            {
                "emails": keys_list,
                "canonical_name": canonical_name,
                "reason": "panel_import: manual review decision",
            }
        )


    new_rejects = []
    for pair in reject_pairs:
        if len(pair) >= 2:
            new_rejects.append(set(pair[:2]))

    log.info(
        f"Panel import: {len(new_merges)} merge groups "
        f"(from {len(merge_pairs)} pairs), "
        f"{len(new_rejects)} rejects"
    )
    return new_merges, new_rejects, len(merge_pairs), len(reject_pairs)


def cleanup_review_queue(review_path: Path, merge_pairs: list, reject_pairs: list) -> int:
    ""



    if not review_path.exists():
        log.warning(f"Review file not found: {review_path}")
        return 0

    with open(review_path) as f:
        review_queue = json.load(f)

    original_count = len(review_queue)


    decided_pairs = set()
    for pair in merge_pairs:
        if len(pair) >= 2:
            decided_pairs.add(frozenset(pair[:2]))
    for pair in reject_pairs:
        if len(pair) >= 2:
            decided_pairs.add(frozenset(pair[:2]))


    remaining = []
    for item in review_queue:

        item_keys = item.get("keys", item.get("emails", []))
        if len(item_keys) >= 2:
            item_pair = frozenset(item_keys[:2])
            if item_pair in decided_pairs:
                continue
        remaining.append(item)

    removed = original_count - len(remaining)


    safe_write_json(review_path, remaining)
    log.info(
        f"Review queue cleanup: {removed} decided items removed, "
        f"{len(remaining)} remaining (was {original_count})"
    )
    return removed


def append_decisions(new_decisions: list[dict]):
    ""




    if not new_decisions:
        return

    existing_data = {"decisions": []}
    if DECISIONS_FILE.exists():
        with open(DECISIONS_FILE) as f:
            existing_data = json.load(f)

    existing_data["decisions"].extend(new_decisions)
    safe_write_json(DECISIONS_FILE, existing_data)
    log.info(f"Appended {len(new_decisions)} decisions to {DECISIONS_FILE.name}")


def is_valid_person_name(name: str) -> bool:
    ""
    if not name or len(name) < 2:
        return False
    name_lower = name.strip().lower()

    skip_patterns = [
        # names that start with one of your own organisations ("organisations" in sbk.config.json)
        *([rf"^({'|'.join(re.escape(n) for n in sorted(OWN_ORG_NAMES))})"] if OWN_ORG_NAMES else []),
        r"(support|bot|admin|team|service|system|noreply|no-reply)",
        r"^[A-Z0-9]{2,}$",
        r"^\+?\d",

        r"\b(contratto|agreement|addendum|amendment|allegato|annex)\b",
        r"\b(services|servizi|consulting|maintenance|integration)\b",
        r"\b(form|modulo|appendix|schedule|exhibit)\b",
        r"\b(srl|spa|ltd|llc|inc|gmbh|s\.r\.l|s\.p\.a)\b",
        r"\b(aml|nda|sow|msa|dpa)\b",

        r"^the\s+.+\s+team$",
        r"\s+bot$",
        r"\b(customer\s+success|customer\s+support|account\s+management)\b",
        r"\b(agency|corporation|foundation|association|partnership)\b",
        r"\b(studio|laboratorio|agenzia|impresa|societa|società)\b",
        r"\b(recruitment|onboarding|payroll|helpdesk|newsletter)\b",
        r"@",
    ]
    for pattern in skip_patterns:
        if re.search(pattern, name_lower):
            return False

    if len(name) > 60:
        return False
    return True


def is_key_email(key: str) -> bool:
    ""
    return "@" in key and not key.startswith(("linkedin:", "phone:", "nameonly:"))


def is_key_synthetic(key: str) -> bool:
    ""
    return key.startswith(("linkedin:", "phone:", "nameonly:"))





def load_personio():
    ""








    parquet = PERSONIO_PROCESSED_DIR / "employees.parquet"
    if parquet.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(parquet)
            result = []
            for _, row in df.iterrows():
                email = str(row.get("email", "") or "").strip().lower()
                if not email or "@" not in email:
                    continue
                nome = str(row.get("name", "") or "").strip()
                first = str(row.get("first_name", "") or "").strip()
                last = str(row.get("last_name", "") or "").strip()
                if not first and nome:


                    pezzi = nome.split()
                    first, last = (pezzi[0], " ".join(pezzi[1:])) if pezzi else ("", "")
                result.append(
                    {
                        "email": email,
                        "first_name": first,
                        "last_name": last,
                        "name": nome or f"{first} {last}".strip(),
                        "status": str(row.get("status", "unknown") or "unknown"),
                        "position": str(row.get("position", "") or ""),
                    }
                )
            log.info("Personio: %d employees loaded (parquet L1, %s)", len(result), parquet.name)
            return result
        except Exception as e:  # noqa: BLE001 — log it and try the fallback
            log.warning("Personio: parquet unreadable (%s), trying the JSON", e)

    path = PERSONIO_DIR / "employees-parsed.json"
    if not path.exists():
        log.warning("No Personio data found")
        return []

    log.warning(
        "Personio: reading %s — it is the FALLBACK, and the file may no longer update: "
        "regenerate the parquet with pe-l1-enrich.py",
        path.name,
    )
    with open(path) as f:
        employees = json.load(f)

    result = []
    for emp in employees:
        email = emp.get("email", "").strip().lower()
        if not email or "@" not in email:
            continue
        result.append(
            {
                "email": email,
                "first_name": emp.get("first_name", ""),
                "last_name": emp.get("last_name", ""),
                "name": f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip(),
                "status": emp.get("status", "unknown"),
                "position": emp.get("position", ""),
            }
        )

    log.info(f"Personio: {len(result)} employees loaded")
    return result


def load_attio_multi_emails():
    ""
    path = ATTIO_DIR / "contacts-attio.parquet"
    if not path.exists():
        log.warning("No Attio contacts found")
        return []

    df = pd.read_parquet(path)
    multi = df[df["all_emails"].str.contains("\\|\\|\\|", na=False)]

    result = []
    for _, row in multi.iterrows():
        emails = [e.strip().lower() for e in row["all_emails"].split("|||") if e.strip()]
        name = row.get("name", "")
        if len(emails) >= 2:
            result.append({"emails": emails, "name": name})

    log.info(f"Attio multi-email: {len(result)} contacts with 2+ emails")
    return result


def load_merged_contacts():
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        log.error("contacts-merged.parquet not found — run cross-source-merge.py first")
        return None

    df = pd.read_parquet(path)
    log.info(f"Merged contacts: {len(df)} loaded")
    return df


def load_linkedin_contacts():
    ""
    path = LINKEDIN_DIR / "contacts-linkedin.parquet"
    if not path.exists():
        log.warning("No LinkedIn contacts found")
        return []

    df = pd.read_parquet(path)
    result = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        linkedin_url = str(row.get("linkedin_url", "")).strip()
        email = str(row.get("email", "")).strip().lower()
        if not name or name == "LinkedIn Member" or not is_valid_person_name(name):
            continue
        result.append(
            {
                "name": name,
                "linkedin_url": linkedin_url if linkedin_url and linkedin_url != "nan" else "",
                "email": email if email and "@" in email and email != "nan" else "",
                "source": "linkedin",
            }
        )

    log.info(f"LinkedIn: {len(result)} contacts loaded (of {len(df)} total)")
    return result


def load_whatsapp_contacts():
    ""
    path = WHATSAPP_DIR / "contacts-whatsapp.parquet"
    if not path.exists():
        log.warning("No WhatsApp contacts found")
        return []

    df = pd.read_parquet(path)
    result = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        phone = str(row.get("phone", "")).strip()
        if not name or not is_valid_person_name(name):
            continue

        if is_own_name(name):
            continue
        result.append(
            {
                "name": name,
                "phone": normalize_phone(phone) if phone and phone != "nan" else "",
                "source": "whatsapp",
            }
        )

    log.info(f"WhatsApp: {len(result)} contacts loaded")
    return result


def load_iphone_contacts():
    ""
    path = IPHONE_DIR / "contacts-iphone.parquet"
    if not path.exists():
        log.warning("No iPhone contacts found")
        return []

    df = pd.read_parquet(path)
    result = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        phone = normalize_phone(str(row.get("phone_primary", "")))
        email = str(row.get("email", "")).strip().lower()
        if not name or not is_valid_person_name(name):
            continue
        result.append(
            {
                "name": name,
                "phone": phone,
                "email": email if email and "@" in email and email != "nan" else "",
                "source": "iphone",
            }
        )

    log.info(f"iPhone: {len(result)} contacts loaded")
    return result


def load_slack_contacts():
    ""
    path = SLACK_DIR / "contacts-slack.parquet"
    if not path.exists():
        log.warning("No Slack contacts found")
        return []

    df = pd.read_parquet(path)
    result = []
    for _, row in df.iterrows():
        real_name = str(row.get("real_name", "")).strip()
        display_name = str(row.get("display_name", "")).strip()
        is_bot = row.get("is_bot", False)
        email = str(row.get("email", "")).strip().lower()
        name = real_name or display_name
        if not name or is_bot or not is_valid_person_name(name):
            continue
        result.append(
            {
                "name": name,
                "email": email if email and "@" in email and email != "nan" else "",
                "source": "slack",
            }
        )

    log.info(f"Slack: {len(result)} contacts loaded")
    return result


def load_docusign_contacts():
    ""
    path = DOCUSIGN_DIR / "contacts-docusign.parquet"
    if not path.exists():
        log.warning("No DocuSign contacts found")
        return []

    df = pd.read_parquet(path)

    persons = df[~df["is_company"]] if "is_company" in df.columns else df
    result = []
    for _, row in persons.iterrows():
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip().lower()


        name_words = name.split()
        if len(name_words) > 5 or len(name_words) < 2:
            continue
        if not name or not is_valid_person_name(name):
            continue
        result.append(
            {
                "name": name,
                "email": email if email and "@" in email and email != "nan" else "",
                "source": "docusign",
            }
        )

    log.info(f"DocuSign: {len(result)} contacts loaded (persons only)")
    return result


def load_notion_contacts():
    ""
    path = NOTION_DIR / "entities-notion.parquet"
    if not path.exists():
        log.warning("No Notion entities found")
        return []

    df = pd.read_parquet(path)
    persons = df[df["entity_type"] == "person"]
    result = []
    for _, row in persons.iterrows():
        name = str(row.get("entity_name", "")).strip()
        if not name or not is_valid_person_name(name):
            continue

        if " e " in name.lower() and len(name.split(" e ")) == 2:
            continue
        result.append(
            {
                "name": name,
                "source": "notion",
            }
        )

    log.info(f"Notion: {len(result)} person entities loaded")
    return result





def level0_manual_overrides(uf, contact_emails):
    ""








    matches = []

    for entry in MANUAL_MERGES:

        all_keys = entry["emails"]
        merge_keys = []

        for key in all_keys:
            if is_key_synthetic(key):

                merge_keys.append(key)
            elif key in contact_emails or key in uf.parent:
                merge_keys.append(key)


        seen = set()
        unique_keys = []
        for k in merge_keys:
            if k not in seen:
                seen.add(k)
                unique_keys.append(k)
        merge_keys = unique_keys

        if len(merge_keys) >= 2:
            for key in merge_keys[1:]:

                uf.union(merge_keys[0], key, check_rejects=False, check_negative=False)
            matches.append(
                {
                    "emails": sorted(merge_keys),
                    "name": entry["canonical_name"],
                    "confidence": 1.0,
                    "level": 0,
                    "reason": entry["reason"],
                }
            )
            log.info(
                f"  Level 0: merged {len(merge_keys)} keys for "
                f"{entry['canonical_name']}: {sorted(merge_keys)}"
            )
        elif len(merge_keys) == 1:
            log.warning(
                f"  Level 0: only 1 key found for {entry['canonical_name']}: "
                f"{merge_keys} (expected {all_keys})"
            )
        else:
            log.warning(
                f"  Level 0: no keys found for {entry['canonical_name']} (expected {all_keys})"
            )

    log.info(f"Level 0: {len(matches)} manual override merges applied")
    return matches





def _compute_ambiguous_prefixes(contact_emails, contact_names):
    ""
    prefix_names = defaultdict(dict)
    for email in contact_emails:
        if "@" not in email or is_shared_inbox(email):
            continue
        local, domain = email.split("@", 1)
        if domain not in INTERNAL_DOMAINS:
            continue
        name = contact_names.get(email, "")
        if name and len(name) > 3:
            prefix_names[local][email] = name

    ambiguous = set()
    for prefix, email_names in prefix_names.items():
        if len(email_names) < 2:
            continue
        names = list(email_names.values())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                score = fuzz.token_sort_ratio(
                    normalize_name(names[i]),
                    normalize_name(names[j]),
                )
                if score < 75:
                    ambiguous.add(prefix)
                    break
            if prefix in ambiguous:
                break

    result = ambiguous | AMBIGUOUS_PREFIXES
    if ambiguous - AMBIGUOUS_PREFIXES:
        log.info(f"Dynamic ambiguous prefixes discovered: {ambiguous - AMBIGUOUS_PREFIXES}")
    return result


def level1_deterministic(uf, personio_employees, attio_multi, contact_emails, contact_names):
    ""
    matches = []


    all_ambiguous = _compute_ambiguous_prefixes(contact_emails, contact_names)


    personio_by_prefix = defaultdict(list)
    for emp in personio_employees:
        local = emp["email"].split("@")[0]
        personio_by_prefix[local].append(emp)

    for prefix, emps in personio_by_prefix.items():
        if prefix in all_ambiguous:
            continue

        matching_emails = set()
        for emp in emps:
            matching_emails.add(emp["email"])

        for contact_email in contact_emails:
            if is_shared_inbox(contact_email):
                continue
            if "@" not in contact_email:
                continue
            c_local, c_domain = contact_email.split("@", 1)
            if c_domain in INTERNAL_DOMAINS and c_local == prefix:
                matching_emails.add(contact_email)

        if len(matching_emails) >= 2:
            emails_list = sorted(matching_emails)
            for email in emails_list[1:]:



                uf.union(emails_list[0], email, check_negative=False)
            matches.append(
                {
                    "emails": emails_list,
                    "name": emps[0]["name"],
                    "confidence": 0.95,
                    "level": 1,
                    "reason": "personio_prefix_match",
                }
            )


    prefix_to_emails = defaultdict(set)
    for contact_email in contact_emails:
        if "@" not in contact_email or is_shared_inbox(contact_email):
            continue
        local, domain = contact_email.split("@", 1)
        if domain in INTERNAL_DOMAINS and local not in all_ambiguous:
            prefix_to_emails[local].add(contact_email)

    for prefix, emails in prefix_to_emails.items():
        if len(emails) < 2 or prefix in personio_by_prefix:
            continue
        emails_list = sorted(emails)
        for email in emails_list[1:]:



            uf.union(emails_list[0], email, check_negative=False)
        cluster_name = ""
        for e in emails_list:
            name = contact_names.get(e, "")
            if name and len(name) > len(cluster_name):
                cluster_name = name
        matches.append(
            {
                "emails": emails_list,
                "name": cluster_name,
                "confidence": 0.90,
                "level": 1,
                "reason": "internal_prefix_match",
            }
        )


    for entry in attio_multi:
        emails = [e for e in entry["emails"] if e in contact_emails and not is_shared_inbox(e)]
        if len(emails) >= 2:
            for email in emails[1:]:
                uf.union(emails[0], email)
            matches.append(
                {
                    "emails": sorted(emails),
                    "name": entry["name"],
                    "confidence": 0.92,
                    "level": 1,
                    "reason": "attio_multi_email",
                }
            )


    gmail_groups = defaultdict(set)
    for email in contact_emails:
        if "@gmail.com" in email:
            normalized = normalize_gmail(email)
            gmail_groups[normalized].add(email)

    for norm_email, emails in gmail_groups.items():
        if len(emails) >= 2:
            emails_list = sorted(emails)
            for email in emails_list[1:]:
                uf.union(emails_list[0], email)
            cluster_name = ""
            for e in emails_list:
                name = contact_names.get(e, "")
                if name and len(name) > len(cluster_name):
                    cluster_name = name
            matches.append(
                {
                    "emails": emails_list,
                    "name": cluster_name,
                    "confidence": 0.95,
                    "level": 1,
                    "reason": "gmail_dot_equivalence",
                }
            )

    log.info(f"Level 1: {len(matches)} deterministic matches")
    return matches





def level2_probabilistic(uf, personio_employees, contact_emails, contact_names):
    ""
    matches = []
    review_queue = []


    all_ambiguous = _compute_ambiguous_prefixes(contact_emails, contact_names)


    personio_by_prefix = defaultdict(list)
    for emp in personio_employees:
        local = emp["email"].split("@")[0]
        if local in all_ambiguous:
            personio_by_prefix[local].append(emp)

    for prefix in all_ambiguous:
        candidate_emails = []
        for contact_email in contact_emails:
            if "@" not in contact_email or is_shared_inbox(contact_email):
                continue
            c_local, c_domain = contact_email.split("@", 1)
            if c_domain in INTERNAL_DOMAINS and c_local == prefix:
                candidate_emails.append(contact_email)

        if not candidate_emails:
            continue

        emps = personio_by_prefix.get(prefix, [])

        if emps:

            for candidate in candidate_emails:
                candidate_name = contact_names.get(candidate, "")
                if not candidate_name:
                    continue

                best_match = None
                best_score = 0
                for emp in emps:
                    score = fuzz.token_sort_ratio(
                        normalize_name(candidate_name),
                        normalize_name(emp["name"]),
                    )
                    if score > best_score:
                        best_score = score
                        best_match = emp

                if best_score >= 85 and best_match:


                    uf.union(candidate, best_match["email"], check_negative=False)
                    matches.append(
                        {
                            "emails": sorted([candidate, best_match["email"]]),
                            "names": [candidate_name, best_match["name"]],
                            "confidence": min(0.9, best_score / 100),
                            "level": 2,
                            "reason": f"ambiguous_prefix_fuzzy (score={best_score})",
                        }
                    )
                elif best_score >= 70 and best_match:
                    review_queue.append(
                        {
                            "emails": sorted([candidate, best_match["email"]]),
                            "names": [candidate_name, best_match["name"]],
                            "confidence": best_score / 100,
                            "reason": f"ambiguous_prefix_uncertain (score={best_score})",
                        }
                    )
        else:

            for i in range(len(candidate_emails)):
                for j in range(i + 1, len(candidate_emails)):
                    name_i = contact_names.get(candidate_emails[i], "")
                    name_j = contact_names.get(candidate_emails[j], "")
                    if not name_i or not name_j:
                        continue
                    score = fuzz.token_sort_ratio(
                        normalize_name(name_i),
                        normalize_name(name_j),
                    )
                    if score >= 85:

                        uf.union(
                            candidate_emails[i],
                            candidate_emails[j],
                            check_negative=False,
                        )
                        matches.append(
                            {
                                "emails": sorted([candidate_emails[i], candidate_emails[j]]),
                                "names": [name_i, name_j],
                                "confidence": min(0.85, score / 100),
                                "level": 2,
                                "reason": f"ambiguous_prefix_name_match (score={score})",
                            }
                        )
                    elif score >= 70:
                        review_queue.append(
                            {
                                "emails": sorted([candidate_emails[i], candidate_emails[j]]),
                                "names": [name_i, name_j],
                                "confidence": score / 100,
                                "reason": f"ambiguous_prefix_uncertain (score={score})",
                            }
                        )


    domain_contacts = defaultdict(list)
    for email in contact_emails:
        if "@" not in email:
            continue
        local, domain = email.split("@", 1)
        if domain in INTERNAL_DOMAINS:
            continue
        name = contact_names.get(email, "")

        if name and len(name) > 5 and len(name.split()) >= 2:
            domain_contacts[domain].append((email, name))

    for domain, contacts in domain_contacts.items():

        if len(contacts) < 2 or len(contacts) >= 10:
            continue
        for i in range(len(contacts)):
            for j in range(i + 1, len(contacts)):
                email_i, name_i = contacts[i]
                email_j, name_j = contacts[j]
                if uf.find(email_i) == uf.find(email_j):
                    continue
                score = fuzz.token_sort_ratio(
                    normalize_name(name_i),
                    normalize_name(name_j),
                )
                if score >= 90:
                    uf.union(email_i, email_j)
                    matches.append(
                        {
                            "emails": sorted([email_i, email_j]),
                            "names": [name_i, name_j],
                            "confidence": min(0.85, score / 100),
                            "level": 2,
                            "reason": f"same_domain_fuzzy (score={score})",
                        }
                    )
                elif score >= 75:
                    review_queue.append(
                        {
                            "emails": sorted([email_i, email_j]),
                            "names": [name_i, name_j],
                            "confidence": score / 100,
                            "reason": f"same_domain_uncertain (score={score})",
                        }
                    )


    name_to_emails = defaultdict(list)
    for email in contact_emails:
        if "@" not in email or is_shared_inbox(email):
            continue
        name = contact_names.get(email, "")

        if not name or "@" in name or len(name.split()) < 2:
            extracted = extract_name_from_email(email)
            if extracted and len(extracted) > 5 and len(extracted.split()) >= 2:
                name = extracted
        if name and len(name) > 5 and len(name.split()) >= 2:
            name_key = normalize_name(name)
            name_to_emails[name_key].append((email, name))

    for name_key, entries in name_to_emails.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                email_i, name_i = entries[i]
                email_j, name_j = entries[j]
                if uf.find(email_i) == uf.find(email_j):
                    continue
                score = fuzz.token_set_ratio(
                    normalize_name(name_i),
                    normalize_name(name_j),
                )
                if score >= 92:
                    uf.union(email_i, email_j)
                    matches.append(
                        {
                            "emails": sorted([email_i, email_j]),
                            "names": [name_i, name_j],
                            "confidence": min(0.8, score / 100),
                            "level": 2,
                            "reason": f"cross_domain_fuzzy (score={score})",
                        }
                    )
                elif score >= 80:
                    review_queue.append(
                        {
                            "emails": sorted([email_i, email_j]),
                            "names": [name_i, name_j],
                            "confidence": score / 100,
                            "reason": f"cross_domain_uncertain (score={score})",
                        }
                    )

    log.info(f"Level 2: {len(matches)} probabilistic matches, {len(review_queue)} for review")
    return matches, review_queue





def level3_deterministic_crosssource(uf, contact_emails, contact_names, new_source_contacts):
    ""




    matches = []
    review_queue = []



    email_name_index = {}
    for email, name in contact_names.items():
        if name and is_valid_person_name(name):
            normed = normalize_name_v2(name)
            if normed and len(normed) > 1:
                email_name_index[email] = normed


    name_to_email_keys = defaultdict(set)
    for email, normed in email_name_index.items():
        name_to_email_keys[normed].add(email)


    phone_to_email = {}
    for source, contacts in new_source_contacts.items():
        for c in contacts:
            email = c.get("email", "")
            phone = c.get("phone", "")
            if email and "@" in email and email in contact_emails and phone:
                phone_to_email[phone] = email



    all_new_contacts = {}
    source_stats = defaultdict(lambda: {"total": 0, "matched": 0, "review": 0})

    for source, contacts in new_source_contacts.items():
        for c in contacts:
            name = c["name"]
            source_tag = c["source"]
            email = c.get("email", "")
            linkedin_url = c.get("linkedin_url", "")
            phone = c.get("phone", "")



            if email and email in contact_emails:
                continue

            source_stats[source_tag]["total"] += 1

            normed_name = normalize_name_v2(name)
            if not normed_name:
                continue


            syn_key = f"nameonly:{source_tag}:{normed_name}"

            if syn_key in all_new_contacts:

                existing = all_new_contacts[syn_key]
                if len(linkedin_url) > len(existing.get("linkedin_url", "")):
                    all_new_contacts[syn_key]["linkedin_url"] = linkedin_url
                if len(phone) > len(existing.get("phone", "")):
                    all_new_contacts[syn_key]["phone"] = phone
                continue

            all_new_contacts[syn_key] = {
                "name": name,
                "normed_name": normed_name,
                "source": source_tag,
                "email": email,
                "linkedin_url": linkedin_url,
                "phone": phone,
                "syn_key": syn_key,
            }

    log.info(f"New source contacts to resolve: {len(all_new_contacts)}")


    linkedin_index = defaultdict(list)
    for syn_key, c in all_new_contacts.items():
        url = c.get("linkedin_url", "")
        if url:
            linkedin_index[url].append(syn_key)

    for url, keys in linkedin_index.items():
        if len(keys) >= 2:

            safe_to_merge = []
            needs_review = []
            base_key = keys[0]
            base_name = normalize_name_v2(all_new_contacts[base_key]["name"])

            for k in keys[1:]:
                other_name = normalize_name_v2(all_new_contacts[k]["name"])
                if base_name and other_name:
                    name_score = fuzz.token_sort_ratio(base_name, other_name)
                else:
                    name_score = 100

                if name_score >= 70:
                    safe_to_merge.append(k)
                else:
                    needs_review.append(k)


            if safe_to_merge:
                for k in safe_to_merge:
                    uf.union(base_key, k)
                all_merged = [base_key] + safe_to_merge
                matches.append(
                    {
                        "keys": sorted(all_merged),
                        "names": [all_new_contacts[k]["name"] for k in all_merged],
                        "confidence": 0.95,
                        "level": 3,
                        "reason": "linkedin_url_match",
                    }
                )
                for k in all_merged:
                    source_stats[all_new_contacts[k]["source"]]["matched"] += 1


            for k in needs_review:
                review_queue.append(
                    {
                        "keys": sorted([base_key, k]),
                        "names": [all_new_contacts[base_key]["name"], all_new_contacts[k]["name"]],
                        "confidence": 0.70,
                        "reason": f"linkedin_url_match_name_mismatch (url={url})",
                    }
                )
                source_stats[all_new_contacts[k]["source"]]["review"] += 1


    phone_index = defaultdict(list)
    for syn_key, c in all_new_contacts.items():
        phone = c.get("phone", "")
        if phone:
            phone_index[phone].append(syn_key)


    for phone, email in phone_to_email.items():
        if phone in phone_index:
            phone_index[phone].append(email)

    for phone, keys in phone_index.items():
        if len(keys) >= 2:
            for k in keys[1:]:
                uf.union(keys[0], k)
            key_names = []
            for k in keys:
                if is_key_email(k):
                    key_names.append(contact_names.get(k, k))
                else:
                    key_names.append(all_new_contacts.get(k, {}).get("name", k))
            matches.append(
                {
                    "keys": sorted(keys),
                    "names": key_names,
                    "confidence": 0.93,
                    "level": 3,
                    "reason": f"phone_match ({phone})",
                }
            )
            for k in keys:
                if is_key_synthetic(k):
                    source_stats[all_new_contacts[k]["source"]]["matched"] += 1



    for syn_key, c in all_new_contacts.items():
        normed = c["normed_name"]
        name_parts = normed.split()


        if len(name_parts) < 2:
            continue


        matching_emails = name_to_email_keys.get(normed, set())
        if matching_emails:

            target_email = sorted(matching_emails)[0]


            if _is_common_surname(name_parts):
                email_name_normed = normalize_name_v2(contact_names.get(target_email, ""))
                email_parts = email_name_normed.split()
                if email_parts and name_parts:
                    if name_parts[0] != email_parts[0]:

                        continue

            uf.union(syn_key, target_email)
            matches.append(
                {
                    "keys": sorted([syn_key, target_email]),
                    "names": [c["name"], contact_names.get(target_email, "")],
                    "confidence": 0.92,
                    "level": 3,
                    "reason": "exact_name_match_cross_source",
                }
            )
            source_stats[c["source"]]["matched"] += 1



    name_groups = defaultdict(list)
    for syn_key, c in all_new_contacts.items():
        normed = c["normed_name"]
        if len(normed.split()) >= 2:
            name_groups[normed].append(syn_key)

    for normed, keys in name_groups.items():
        if len(keys) < 2:
            continue


        normed_parts = normed.split()
        if _is_common_surname(normed_parts) and len(normed_parts) >= 2:

            first_name_groups = defaultdict(list)
            for k in keys:
                fn = all_new_contacts[k]["normed_name"].split()[0]
                first_name_groups[fn].append(k)
            sub_groups = list(first_name_groups.values())
        else:
            sub_groups = [keys]

        for sub_keys in sub_groups:
            if len(sub_keys) < 2:
                continue

            sources_seen = set()
            mergeable = []
            for k in sub_keys:
                src = all_new_contacts[k]["source"]
                if src not in sources_seen:
                    sources_seen.add(src)
                    mergeable.append(k)
            if len(mergeable) >= 2:
                for k in mergeable[1:]:
                    uf.union(mergeable[0], k)
                matches.append(
                    {
                        "keys": sorted(mergeable),
                        "names": [all_new_contacts[k]["name"] for k in mergeable],
                        "confidence": 0.90,
                        "level": 3,
                        "reason": "exact_name_match_new_sources",
                    }
                )
            for k in mergeable:
                source_stats[all_new_contacts[k]["source"]]["matched"] += 1

    log.info(f"Level 3: {len(matches)} deterministic cross-source matches")
    for src, st in sorted(source_stats.items()):
        log.info(f"  {src}: {st['total']} total, {st['matched']} matched")

    return matches, review_queue, all_new_contacts, source_stats





def _get_surname_block_keys(surname):
    ""





    keys = []
    if surname:
        keys.append(("exact", surname))
        try:
            import jellyfish

            mph = jellyfish.metaphone(surname)
            if mph and len(mph) >= 2:
                keys.append(("metaphone", mph))
        except ImportError:
            pass


        if len(surname) >= 4:
            keys.append(("surname_prefix", surname[:3]))
    return keys


def level4_probabilistic_name(
    uf, contact_emails, contact_names, all_new_contacts, source_stats, nickname_db=None
):
    ""
    matches = []
    review_queue = []



    email_name_list = []
    for email, name in contact_names.items():
        if not name or not is_valid_person_name(name):
            continue
        normed = normalize_name_v2(name)
        parts = normed.split()
        if len(parts) >= 2:
            email_name_list.append((email, name, normed, parts[-1]))


    new_name_list = []
    for syn_key, c in all_new_contacts.items():
        normed = c["normed_name"]
        parts = normed.split()
        if len(parts) >= 2:
            new_name_list.append((syn_key, c["name"], normed, parts[-1]))
        elif len(parts) == 1 and normed not in COMMON_FIRST_NAMES:
            pass



    email_by_block = defaultdict(list)
    for item in email_name_list:
        surname = item[3]
        for block_key in _get_surname_block_keys(surname):
            email_by_block[block_key].append(item)

    new_by_block = defaultdict(list)
    for item in new_name_list:
        surname = item[3]
        for block_key in _get_surname_block_keys(surname):
            new_by_block[block_key].append(item)

    log.info(
        f"Level 4 blocking: {len(email_by_block)} email blocks, "
        f"{len(new_by_block)} new-source blocks "
        f"(exact surname + Metaphone)"
    )



    roots_with_email = set()
    for k in uf.parent:
        if is_key_email(k):
            roots_with_email.add(uf.find(k))



    seen_pairs_4a = set()
    for block_key in new_by_block:
        if block_key not in email_by_block:
            continue

        is_fuzzy_block = block_key[0] in ("metaphone", "surname_prefix")
        new_items = new_by_block[block_key]
        email_items = email_by_block[block_key]

        for syn_key, new_name, new_normed, new_surname in new_items:

            root = uf.find(syn_key)
            if root in roots_with_email:
                continue

            best_score = 0
            best_email = None
            best_email_name = ""

            for email, email_name, email_normed, email_surname in email_items:
                pair_id = (syn_key, email) if syn_key < email else (email, syn_key)
                if pair_id in seen_pairs_4a:
                    continue

                if uf.find(email) == uf.find(syn_key):
                    continue

                if is_fuzzy_block and new_surname and email_surname:
                    sd = sum(1 for a, b in zip(new_surname, email_surname) if a != b) + abs(
                        len(new_surname) - len(email_surname)
                    )
                    if sd > 2:
                        continue
                score = fuzz.token_sort_ratio(new_normed, email_normed)

                if nickname_db and score < 88:
                    _nf = new_normed.split()[0] if new_normed else ""
                    _ef = email_normed.split()[0] if email_normed else ""
                    if _nf and _ef and nickname_db.are_equivalent(_nf, _ef):
                        import jellyfish as _jf

                        _jw = _jf.jaro_winkler_similarity(new_surname, email_surname)
                        if _jw >= 0.85:
                            score = max(score, 96)
                if score > best_score:
                    best_score = score
                    best_email = email
                    best_email_name = email_name

            if best_email:
                pair_id = (syn_key, best_email) if syn_key < best_email else (best_email, syn_key)
                seen_pairs_4a.add(pair_id)


            new_parts = new_normed.split()
            threshold_4a = 95 if _is_common_surname(new_parts) else 88


            if best_score >= threshold_4a and best_email and syn_key.startswith("nameonly:"):
                new_first = new_normed.split()[0] if new_normed.split() else ""
                best_email_normed = normalize_name_v2(best_email_name)
                email_first = best_email_normed.split()[0] if best_email_normed.split() else ""
                if new_first and email_first:
                    first_name_score = fuzz.ratio(new_first, email_first)
                    if first_name_score < 80:

                        log.debug(
                            f"Level 4A: blocked {syn_key} + {best_email} — "
                            f"first name mismatch ({new_first} vs {email_first}, "
                            f"score={first_name_score})"
                        )
                        review_queue.append(
                            {
                                "keys": sorted([syn_key, best_email]),
                                "names": [new_name, best_email_name],
                                "confidence": best_score / 100,
                                "reason": (
                                    f"fuzzy_name_first_name_blocked "
                                    f"(full={best_score}, first={first_name_score})"
                                ),
                            }
                        )
                        src = all_new_contacts[syn_key]["source"]
                        source_stats[src]["review"] += 1
                        best_email = None
            if best_score >= threshold_4a and best_email:
                uf.union(syn_key, best_email)
                matches.append(
                    {
                        "keys": sorted([syn_key, best_email]),
                        "names": [new_name, best_email_name],
                        "confidence": min(0.85, best_score / 100),
                        "level": 4,
                        "reason": f"fuzzy_name_cross_source (score={best_score})",
                    }
                )
                src = all_new_contacts[syn_key]["source"]
                source_stats[src]["matched"] += 1
            elif best_score >= 75 and best_email:
                review_queue.append(
                    {
                        "keys": sorted([syn_key, best_email]),
                        "names": [new_name, best_email_name],
                        "confidence": best_score / 100,
                        "reason": f"fuzzy_name_uncertain (score={best_score})",
                    }
                )
                src = all_new_contacts[syn_key]["source"]
                source_stats[src]["review"] += 1



    seen_pairs_4b = set()
    for block_key, items in new_by_block.items():
        if len(items) < 2:
            continue
        is_fuzzy_block = block_key[0] in ("metaphone", "surname_prefix")
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                key_i, name_i, normed_i, surname_i = items[i]
                key_j, name_j, normed_j, surname_j = items[j]
                pair_id = (key_i, key_j) if key_i < key_j else (key_j, key_i)
                if pair_id in seen_pairs_4b:
                    continue
                seen_pairs_4b.add(pair_id)

                src_i = all_new_contacts[key_i]["source"]
                src_j = all_new_contacts[key_j]["source"]
                if src_i == src_j:
                    continue
                if uf.find(key_i) == uf.find(key_j):
                    continue

                if is_fuzzy_block and surname_i and surname_j:
                    sd = sum(1 for a, b in zip(surname_i, surname_j) if a != b) + abs(
                        len(surname_i) - len(surname_j)
                    )
                    if sd > 2:
                        continue
                score = fuzz.token_sort_ratio(normed_i, normed_j)

                if nickname_db and score < 88:
                    _fi = normed_i.split()[0] if normed_i else ""
                    _fj = normed_j.split()[0] if normed_j else ""
                    if _fi and _fj and nickname_db.are_equivalent(_fi, _fj):
                        import jellyfish as _jf

                        _jw = _jf.jaro_winkler_similarity(surname_i, surname_j)
                        if _jw >= 0.85:
                            score = max(score, 96)

                parts_i = normed_i.split()
                threshold_4b = 95 if _is_common_surname(parts_i) else 88

                first_name_ok = True
                if score >= threshold_4b:
                    first_i = normed_i.split()[0] if normed_i.split() else ""
                    first_j = normed_j.split()[0] if normed_j.split() else ""
                    if first_i and first_j:
                        fn_score = fuzz.ratio(first_i, first_j)
                        if fn_score < 80:
                            first_name_ok = False
                            log.debug(
                                f"Level 4B: blocked {key_i} + {key_j} — "
                                f"first name mismatch ({first_i} vs {first_j}, "
                                f"score={fn_score})"
                            )
                            review_queue.append(
                                {
                                    "keys": sorted([key_i, key_j]),
                                    "names": [name_i, name_j],
                                    "confidence": score / 100,
                                    "reason": (
                                        f"fuzzy_name_first_name_blocked "
                                        f"(full={score}, first={fn_score})"
                                    ),
                                }
                            )
                if score >= threshold_4b and first_name_ok:
                    uf.union(key_i, key_j)
                    matches.append(
                        {
                            "keys": sorted([key_i, key_j]),
                            "names": [name_i, name_j],
                            "confidence": min(0.82, score / 100),
                            "level": 4,
                            "reason": f"fuzzy_name_new_sources (score={score})",
                        }
                    )
                elif score >= 75 and first_name_ok:
                    review_queue.append(
                        {
                            "keys": sorted([key_i, key_j]),
                            "names": [name_i, name_j],
                            "confidence": score / 100,
                            "reason": f"fuzzy_name_new_sources_uncertain (score={score})",
                        }
                    )


    for syn_key, c in all_new_contacts.items():
        normed = c["normed_name"]
        parts = normed.split()
        if len(parts) != 1:
            continue
        if normed in COMMON_FIRST_NAMES:
            continue

        best_score = 0
        best_email = None
        best_email_name = ""
        for email, name in contact_names.items():
            if not name or len(name.split()) < 2:
                continue
            email_normed = normalize_name_v2(name)

            email_parts = email_normed.split()
            for part in email_parts:
                score = fuzz.ratio(normed, part)
                if score >= 90 and score > best_score:
                    best_score = score
                    best_email = email
                    best_email_name = name

        if best_score >= 90 and best_email:
            review_queue.append(
                {
                    "keys": sorted([syn_key, best_email]),
                    "names": [c["name"], best_email_name],
                    "confidence": 0.5,
                    "reason": f"single_word_name_partial (score={best_score}, "
                    f"name='{normed}' in '{normalize_name_v2(best_email_name)}')",
                }
            )
            source_stats[c["source"]]["review"] += 1

    log.info(f"Level 4: {len(matches)} probabilistic name matches, {len(review_queue)} for review")
    return matches, review_queue





def _looks_like_username(name: str):
    ""





    if not name or " " in name or len(name) < 4:
        return None
    if name != name.lower():
        return None

    candidate_name = name[:-1]
    candidate_initial = name[-1]

    if len(candidate_name) < 3:
        return None

    if not candidate_initial.isalpha():
        return None
    return (candidate_name, candidate_initial)


def level4_5_single_word_auto(
    uf, contact_names, all_new_contacts, source_stats, review_queue, dry_run=False
):
    ""












    matches = []
    rejects = []
    new_decisions = []
    items_to_remove = set()

    timestamp = datetime.now().isoformat()

    for idx, item in enumerate(review_queue):
        reason = item.get("reason", "")
        if "single_word_name_partial" not in reason:
            continue

        keys = item.get("keys", item.get("emails", []))
        names = item.get("names", [])
        if len(keys) < 2 or len(names) < 2:
            continue


        single_key = None
        full_key = None
        single_name = None
        full_name = None

        for i, k in enumerate(keys):
            normed = normalize_name_v2(names[i])
            parts = normed.split()
            if len(parts) == 1:
                single_key = k
                single_name = normed
            elif len(parts) >= 2:
                full_key = k
                full_name = normed

        if not single_key or not full_key or not single_name or not full_name:
            continue

        full_parts = full_name.split()


        full_name_lower = full_name.lower()
        is_company = any(
            re.search(r"\b" + re.escape(kw) + r"\b", full_name_lower)
            for kw in COMPANY_NAME_KEYWORDS
        )
        if is_company:
            rejects.append(
                {
                    "keys": sorted([single_key, full_key]),
                    "names": names,
                    "confidence": 0.95,
                    "level": 4.5,
                    "reason": f"auto_reject_company_name ('{single_name}' vs '{full_name}')",
                }
            )
            MANUAL_REJECTS.append({single_key, full_key})
            new_decisions.append(
                {
                    "action": "reject",
                    "keys": sorted([single_key, full_key]),
                    "reason": f"level4.5_auto_reject_company: '{single_name}' vs '{full_name}'",
                    "timestamp": timestamp,
                }
            )
            items_to_remove.add(idx)
            log.info(f"  Level 4.5: auto-reject company match: '{single_name}' vs '{full_name}'")
            continue


        username_parts = _looks_like_username(single_name)
        if username_parts:
            uname, uinitial = username_parts


            first_token = full_parts[0]
            last_token = full_parts[-1]
            if first_token.startswith(uname) and last_token.startswith(uinitial):

                single_source = ""
                full_source = ""
                if single_key in all_new_contacts:
                    single_source = all_new_contacts[single_key].get("source", "")
                if full_key in all_new_contacts:
                    full_source = all_new_contacts[full_key].get("source", "")

                if single_source != full_source or not single_source:
                    uf.union(single_key, full_key)
                    matches.append(
                        {
                            "keys": sorted([single_key, full_key]),
                            "names": names,
                            "confidence": 0.82,
                            "level": 4.5,
                            "reason": (
                                f"username_resolution ('{single_name}' -> "
                                f"'{uname}' + '{uinitial}' matches '{full_name}')"
                            ),
                        }
                    )
                    new_decisions.append(
                        {
                            "action": "merge",
                            "keys": sorted([single_key, full_key]),
                            "reason": (
                                f"level4.5_username_resolution: '{single_name}' -> "
                                f"'{uname}'+'{uinitial}' matches '{full_name}'"
                            ),
                            "timestamp": timestamp,
                        }
                    )
                    items_to_remove.add(idx)
                    if single_key in all_new_contacts:
                        source_stats[all_new_contacts[single_key]["source"]]["matched"] += 1
                    log.info(f"  Level 4.5: username merge: '{single_name}' -> '{full_name}'")
                    continue



        if single_name == full_parts[0] and len(full_parts) >= 2:

            if single_name in AMBIGUOUS_SINGLE_NAMES:
                log.debug(
                    f"  Level 4.5: skip ambiguous single name: '{single_name}' vs '{full_name}'"
                )
                continue


            single_source = ""
            full_source = ""
            if single_key in all_new_contacts:
                single_source = all_new_contacts[single_key].get("source", "")
            if full_key in all_new_contacts:
                full_source = all_new_contacts[full_key].get("source", "")

            if is_key_email(single_key):
                single_source = "email"
            if is_key_email(full_key):
                full_source = "email"

            if single_source != full_source or not single_source:
                uf.union(single_key, full_key)
                matches.append(
                    {
                        "keys": sorted([single_key, full_key]),
                        "names": names,
                        "confidence": 0.85,
                        "level": 4.5,
                        "reason": (
                            f"first_name_auto_merge ('{single_name}' == "
                            f"first token of '{full_name}')"
                        ),
                    }
                )
                new_decisions.append(
                    {
                        "action": "merge",
                        "keys": sorted([single_key, full_key]),
                        "reason": (
                            f"level4.5_first_name_auto: '{single_name}' == "
                            f"first token of '{full_name}'"
                        ),
                        "timestamp": timestamp,
                    }
                )
                items_to_remove.add(idx)
                if single_key in all_new_contacts:
                    source_stats[all_new_contacts[single_key]["source"]]["matched"] += 1
                log.info(f"  Level 4.5: first-name merge: '{single_name}' -> '{full_name}'")


    filtered_review = [item for idx, item in enumerate(review_queue) if idx not in items_to_remove]


    if new_decisions and not dry_run:
        append_decisions(new_decisions)

    log.info(
        f"Level 4.5: {len(matches)} auto-merges, {len(rejects)} auto-rejects, "
        f"{len(items_to_remove)} items removed from review queue"
    )
    return matches, rejects, filtered_review





def level6_relationship_fact_resolution(uf, entity_map_partial, contact_names, all_new_contacts):
    ""






    from sbk_config import RELATIONSHIP_FACTS_FILE

    if not RELATIONSHIP_FACTS_FILE.exists():
        log.info("Level 6: No relationship-facts.parquet found, skipping")
        return []

    try:
        facts_df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
    except Exception as e:
        log.warning(f"Level 6: Failed to load relationship facts: {e}")
        return []

    if facts_df.empty:
        return []

    matches = []

    name_to_pid: dict[str, str] = {}
    for email, name in contact_names.items():
        if not name:
            continue
        entry = uf.find(email)
        name_to_pid[name.lower()] = entry




    high_facts = facts_df[confidenza_almeno(facts_df["confidence"], CONFIDENZA_ALTA)]
    for _, fact in high_facts.iterrows():
        subject = str(fact.get("subject", "")).strip()
        obj = str(fact.get("object", "")).strip()
        subject_pid = str(fact.get("subject_person_id", ""))
        object_pid = str(fact.get("object_person_id", ""))

        if not subject or not obj:
            continue


        subj_lower = subject.lower()
        obj_lower = obj.lower()


        if subject_pid:
            for key, info in all_new_contacts.items():
                if not key.startswith("nameonly:"):
                    continue
                key_name = info.get("name", "").lower()
                if key_name == obj_lower:

                    if obj_lower in name_to_pid:
                        email_key = name_to_pid[obj_lower]
                        if uf.union(key, email_key):
                            matches.append(
                                {
                                    "keys": [key, email_key],
                                    "confidence": 0.80,
                                    "reason": f"relationship_fact: {subject} → {fact.get('predicate', '')} → {obj}",
                                }
                            )

    log.info(f"Level 6 (relationship facts): {len(matches)} merges")
    return matches


def auto_resolve_clearly_different(review_queue, dry_run=False):
    ""









    RESOLVABLE_REASONS = {
        "same_domain_uncertain",
        "fuzzy_name_uncertain",
        "fuzzy_name_new_sources_uncertain",
    }

    rejects = []
    new_decisions = []
    items_to_remove = set()
    timestamp = datetime.now().isoformat()

    for idx, item in enumerate(review_queue):
        reason = item.get("reason", "")
        if not any(r in reason for r in RESOLVABLE_REASONS):
            continue

        names = item.get("names", [])
        if len(names) < 2:
            continue

        n1 = normalize_name_v2(names[0])
        n2 = normalize_name_v2(names[1])


        for sep in [" at ", " | ", " from ", " - "]:
            if sep in n1.lower():
                n1 = n1[: n1.lower().index(sep)]
            if sep in n2.lower():
                n2 = n2[: n2.lower().index(sep)]

        parts1 = n1.lower().split()
        parts2 = n2.lower().split()

        is_different = False

        if len(parts1) >= 2 and len(parts2) >= 2:
            same_first = parts1[0] == parts2[0]
            same_last = parts1[-1] == parts2[-1]
            if not same_first and not same_last:
                is_different = True
            elif same_first and not same_last:
                is_different = True
            elif not same_first and same_last:
                is_different = True


        if not is_different and len(parts1) >= 1 and len(parts2) >= 1:
            first_ratio = fuzz.ratio(parts1[0], parts2[0])
            if first_ratio < 70:
                is_different = True

        if is_different:
            keys = item.get("keys", item.get("emails", []))
            rejects.append(item)
            new_decisions.append(
                {
                    "action": "reject",
                    "keys": sorted(keys) if keys else [],
                    "reason": f"auto_reject_different_names: '{names[0]}' vs '{names[1]}'",
                    "timestamp": timestamp,
                }
            )
            items_to_remove.add(idx)

    filtered_review = [item for idx, item in enumerate(review_queue) if idx not in items_to_remove]

    if new_decisions and not dry_run:
        append_decisions(new_decisions)

    log.info(
        f"Auto-resolve different names: {len(rejects)} auto-rejects, "
        f"review queue {len(review_queue)} -> {len(filtered_review)}"
    )
    return filtered_review





def level7_splink_clusters(uf, contact_names, all_new_contacts):
    ""






    clusters_path = ENRICHED_DIR / "entity-clusters-splink.json"
    if not clusters_path.exists():
        log.info("Level 7: No entity-clusters-splink.json found, skipping")
        log.info("  Run xs-l6-splink-resolve.py first to generate clusters")
        return []

    try:
        with open(clusters_path) as f:
            data = json.load(f)
    except Exception as e:
        log.warning(f"Level 7: Failed to load Splink clusters: {e}")
        return []

    clusters = data.get("clusters", {})
    if not clusters:
        log.info("Level 7: No clusters in Splink output")
        return []


    pid_to_keys: dict[str, list[str]] = {}
    for key, name in contact_names.items():
        if name:

            pid = f"pu_{name.lower().replace(' ', '_')}"
            pid_to_keys.setdefault(pid, []).append(key)
    for key, info in all_new_contacts.items():
        name = info.get("name", "")
        if name:
            pid = f"pu_{name.lower().replace(' ', '_')}"
            pid_to_keys.setdefault(pid, []).append(key)

    matches = []
    total = 0
    resolved = 0
    dropped = 0
    for _cluster_id, cluster_info in clusters.items():
        members = cluster_info.get("members", [])
        if len(members) < 2:
            continue
        total += 1


        member_keys = []
        for member in members:
            pid = member.get("person_id", "")
            keys = pid_to_keys.get(pid, [])
            if keys:
                member_keys.append(keys[0])
            else:
                log.debug(
                    f"Level 7: person_id {pid} not found in pid_to_keys ({len(pid_to_keys)} entries)"
                )


        if len(member_keys) >= 2:
            resolved += 1
            anchor = member_keys[0]
            for key in member_keys[1:]:
                if uf.union(anchor, key):
                    matches.append(
                        {
                            "keys": [anchor, key],
                            "confidence": 0.90,
                            "reason": f"splink_cluster: {[m.get('name', '?') for m in members]}",
                        }
                    )
        else:
            dropped += 1

    log.info(f"Level 7 (Splink clusters): {len(matches)} merges from {len(clusters)} clusters")
    log.info(
        f"Level 7: {resolved}/{total} members resolved, {dropped} clusters dropped (no matching keys)"
    )
    return matches





def build_entity_map_v2(uf, personio_employees, contact_names, contact_scores, all_new_contacts):
    ""




    clusters = uf.clusters()

    personio_by_email = {emp["email"]: emp for emp in personio_employees}

    entity_map = {}
    person_counter = 0
    name_only_entities = 0
    singleton_email_entities = 0

    for _root, keys in sorted(clusters.items()):

        email_keys = sorted(k for k in keys if is_key_email(k))
        synthetic_keys = sorted(k for k in keys if is_key_synthetic(k))





        person_counter += 1


        stable_key = "|".join(sorted(keys))
        person_id = "p_" + hashlib.sha256(stable_key.encode()).hexdigest()[:8]


        canonical_name = ""
        personio_status = None
        is_internal = False

        for email in email_keys:
            domain = email.split("@", 1)[1] if "@" in email else ""
            if domain in INTERNAL_DOMAINS:
                is_internal = True
            emp = personio_by_email.get(email)
            if emp:
                canonical_name = emp["name"]
                personio_status = emp["status"]


        for email in email_keys:
            emp = personio_by_email.get(email)
            if emp and emp["status"] == "active":
                canonical_name = emp["name"]
                personio_status = "active"
                break

        if not canonical_name:

            best_name = ""
            for email in email_keys:
                name = contact_names.get(email, "")
                if len(name) > len(best_name):
                    best_name = name
            canonical_name = best_name

        if not canonical_name:

            best_name = ""
            for sk in synthetic_keys:
                c = all_new_contacts.get(sk, {})
                name = c.get("name", "")
                if len(name) > len(best_name):
                    best_name = name
            canonical_name = best_name


        for email in email_keys:
            if email in NAME_OVERRIDES:
                canonical_name = NAME_OVERRIDES[email]
                break


        primary_email = ""
        if email_keys:
            primary_email = max(email_keys, key=lambda e: contact_scores.get(e, 0))


        if any(e in personio_by_email for e in email_keys):
            confidence = 0.95
        elif email_keys:
            confidence = 0.85
        else:
            confidence = 0.80


        sources = set()
        linkedin_urls = set()
        phones = set()
        for sk in synthetic_keys:
            c = all_new_contacts.get(sk, {})
            sources.add(c.get("source", ""))
            lu = c.get("linkedin_url", "")
            if lu:
                linkedin_urls.add(lu)
            ph = c.get("phone", "")
            if ph:
                phones.add(ph)

        entry = {
            "person_id": person_id,
            "all_emails": email_keys,
            "primary_email": primary_email,
            "canonical_name": canonical_name,
            "confidence": confidence,
            "is_internal": is_internal,
            "personio_status": personio_status,
        }


        if synthetic_keys:
            entry["name_sources"] = sorted(sources - {""})
            if linkedin_urls:
                entry["linkedin_urls"] = sorted(linkedin_urls)
            if phones:
                entry["phones"] = sorted(phones)


        for email in email_keys:
            entity_map[email] = entry


        for sk in synthetic_keys:
            entity_map[sk] = entry

        if not email_keys and synthetic_keys:
            name_only_entities += 1
        if len(keys) == 1 and email_keys:
            singleton_email_entities += 1

    log.info(
        f"Entity map: {person_counter} persons total, "
        f"{name_only_entities} name-only, "
        f"{singleton_email_entities} singleton-email"
    )
    return entity_map





def cleanup_entity_map(
    entity_map_path: Path | None = None, contacts_merged_path: Path | None = None
):
    ""












    if entity_map_path is None:
        entity_map_path = ENRICHED_DIR / "entity-map.json"
    if contacts_merged_path is None:
        contacts_merged_path = ENRICHED_DIR / "contacts-merged.parquet"

    if not entity_map_path.exists():
        log.warning(f"Entity map not found: {entity_map_path} — skipping cleanup")
        return 0, 0, 0

    if not contacts_merged_path.exists():
        log.warning(f"Contacts merged not found: {contacts_merged_path} — skipping cleanup")
        return 0, 0, 0


    with open(entity_map_path) as f:
        entity_map = json.load(f)


    df = pd.read_parquet(contacts_merged_path, columns=["person_id"])
    valid_pids = set(df["person_id"].dropna().unique())
    valid_pids.discard("")


    cleaned = {}
    removed = 0
    for key, info in entity_map.items():
        pid = info.get("person_id", "") if isinstance(info, dict) else ""
        if pid in valid_pids:
            cleaned[key] = info
        else:
            removed += 1

    original_count = len(entity_map)
    cleaned_count = len(cleaned)

    if removed > 0:

        safe_write_json(entity_map_path, cleaned, backup=True)
        log.info(
            f"Entity map cleanup: {original_count} -> {cleaned_count} "
            f"({removed} dangling references removed, "
            f"{removed / original_count * 100:.1f}%)"
        )
    else:
        log.info(f"Entity map cleanup: {original_count} entries, 0 dangling — no changes needed")

    return original_count, cleaned_count, removed





def main():
    from sbk_config import acquire_pid_lock

    if not acquire_pid_lock("xs-l2-entity-resolve", logger=log):
        log.warning("Another entity-resolve instance running, exiting")
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Entity Resolution V2 — SBK")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument(
        "--import-decisions",
        type=str,
        metavar="FILE",
        help="Import merge/reject decisions from panel export JSON",
    )
    parser.add_argument(
        "--use-relationships",
        action="store_true",
        help="Enable Level 6: relationship-fact-based resolution",
    )
    parser.add_argument(
        "--use-splink",
        action="store_true",
        help="Enable Level 7: apply Splink probabilistic clusters",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed, mark_last_run

        if not check_inputs_changed("entity-resolve", [ENRICHED_DIR / "contacts-merged.parquet"]):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("entity-resolve")
            return


    persistent_merge_count, persistent_reject_count = load_persistent_decisions()
    if persistent_merge_count or persistent_reject_count:
        log.info(
            f"After persistent load: {len(MANUAL_MERGES)} total manual merges, "
            f"{len(MANUAL_REJECTS)} total manual rejects"
        )


    if not args.dry_run:
        backup_outputs()


    imported_merge_count = 0
    imported_reject_count = 0
    raw_merge_pairs = []
    raw_reject_pairs = []

    if args.import_decisions:
        log.info(f"Importing decisions from: {args.import_decisions}")

        decisions_path = Path(args.import_decisions)
        if decisions_path.exists():
            with open(decisions_path) as f:
                raw_decisions = json.load(f)
            raw_merge_pairs = raw_decisions.get("merge", [])
            raw_reject_pairs = raw_decisions.get("reject", [])

        new_merges, new_rejects, imported_merge_count, imported_reject_count = (
            import_panel_decisions(args.import_decisions)
        )


        MANUAL_MERGES.extend(new_merges)

        MANUAL_REJECTS.extend(new_rejects)

        log.info(
            f"After import: {len(MANUAL_MERGES)} total manual merges, "
            f"{len(MANUAL_REJECTS)} total manual rejects"
        )


    merged_df = load_merged_contacts()
    if merged_df is None:
        return

    personio = load_personio()
    attio_multi = load_attio_multi_emails()


    linkedin = load_linkedin_contacts()
    whatsapp = load_whatsapp_contacts()
    iphone = load_iphone_contacts()
    slack = load_slack_contacts()
    docusign = load_docusign_contacts()
    notion = load_notion_contacts()

    new_source_contacts = {
        "linkedin": linkedin,
        "whatsapp": whatsapp,
        "iphone": iphone,
        "slack": slack,
        "docusign": docusign,
        "notion": notion,
    }



    contact_emails = set()
    contact_names = {}
    for _, row in merged_df.iterrows():
        primary_email = str(row.get("email", "")).strip().lower()
        name = str(row.get("name", "")).strip()
        if primary_email and "@" in primary_email:
            contact_emails.add(primary_email)
            contact_names[primary_email] = name


        all_emails_str = row.get("all_emails", "")
        if all_emails_str and isinstance(all_emails_str, str):
            try:
                all_emails_list = json.loads(all_emails_str)
                for email in all_emails_list:
                    email = email.strip().lower()
                    if email and "@" in email:
                        contact_emails.add(email)
                        if email not in contact_names or not contact_names[email]:
                            contact_names[email] = name
            except (json.JSONDecodeError, TypeError):
                pass

    log.info(
        f"Expanded email identifiers: {len(contact_emails)} (from {len(merged_df)} merged rows)"
    )


    for emp in personio:
        contact_emails.add(emp["email"])
        if emp["email"] not in contact_names or not contact_names[emp["email"]]:
            contact_names[emp["email"]] = emp["name"]


    for source, contacts in new_source_contacts.items():
        for c in contacts:
            email = c.get("email", "")
            if email and "@" in email:
                contact_emails.add(email)
                if email not in contact_names or not contact_names[email]:
                    contact_names[email] = c["name"]

    contact_scores = {}
    if "score" in merged_df.columns:
        for _, row in merged_df.iterrows():
            score = row.get("score", 0) or 0
            primary_email = str(row.get("email", "")).strip().lower()
            if primary_email and "@" in primary_email:
                contact_scores[primary_email] = score

            all_emails_str = row.get("all_emails", "")
            if all_emails_str and isinstance(all_emails_str, str):
                try:
                    for email in json.loads(all_emails_str):
                        email = email.strip().lower()
                        if email and "@" in email:
                            contact_scores.setdefault(email, score)
                except (json.JSONDecodeError, TypeError):
                    pass


    neg_constraint_count = build_negative_constraints()
    log.info(f"Negative constraints: {neg_constraint_count} email pairs loaded")


    uf = UnionFind()




    for email in contact_emails:
        uf.find(email)
    log.info(f"Registered {len(contact_emails)} emails as UF singletons")




    own_emails_in_system = sorted(OWN_EMAILS & contact_emails)

    for email in OWN_EMAILS:
        uf.find(email)
    if len(own_emails_in_system) >= 2:
        anchor = own_emails_in_system[0]
        for email in own_emails_in_system[1:]:
            uf.union(anchor, email, check_rejects=False, check_negative=False)
        log.info(
            f"OWN_EMAILS: merged {len(own_emails_in_system)} emails into 1 identity "
            f"(anchor: {anchor})"
        )

    all_own = sorted(OWN_EMAILS)
    if len(all_own) >= 2:
        anchor = all_own[0]
        for email in all_own[1:]:
            uf.union(anchor, email, check_rejects=False, check_negative=False)


    from sbk_config import DATA_ROOT as _DR

    _learned_path = _DR / "learned-name-variants.json"
    nickname_db = NameEquivalenceDB(learned_path=_learned_path)
    log.info("EQ-02: NameEquivalenceDB loaded (%d static clusters)", len(nickname_db._clusters))


    l0_matches = level0_manual_overrides(uf, contact_emails)


    l1_matches = level1_deterministic(uf, personio, attio_multi, contact_emails, contact_names)


    l2_matches, l2_review = level2_probabilistic(uf, personio, contact_emails, contact_names)


    l3_matches, l3_review, all_new_contacts, source_stats = level3_deterministic_crosssource(
        uf, contact_emails, contact_names, new_source_contacts
    )


    l4_matches, l4_review = level4_probabilistic_name(
        uf, contact_emails, contact_names, all_new_contacts, source_stats, nickname_db
    )


    review_queue = l2_review + l3_review + l4_review


    l4_5_matches, l4_5_rejects, review_queue = level4_5_single_word_auto(
        uf,
        contact_names,
        all_new_contacts,
        source_stats,
        review_queue,
        dry_run=args.dry_run,
    )


    review_queue = auto_resolve_clearly_different(review_queue, dry_run=args.dry_run)


    l6_matches = []
    if args.use_relationships:
        l6_matches = level6_relationship_fact_resolution(uf, {}, contact_names, all_new_contacts)


    l7_matches = []
    if args.use_splink:
        l7_matches = level7_splink_clusters(uf, contact_names, all_new_contacts)


    entity_map = build_entity_map_v2(uf, personio, contact_names, contact_scores, all_new_contacts)


    clusters = uf.clusters()
    multi_clusters = {k: v for k, v in clusters.items() if len(v) >= 2}


    email_only_clusters = 0
    mixed_clusters = 0
    name_only_clusters = 0
    for _root, keys in multi_clusters.items():
        has_email = any(is_key_email(k) for k in keys)
        has_synthetic = any(is_key_synthetic(k) for k in keys)
        if has_email and has_synthetic:
            mixed_clusters += 1
        elif has_email:
            email_only_clusters += 1
        else:
            name_only_clusters += 1

    total_keys_resolved = sum(len(v) for v in multi_clusters.values())
    total_email_keys = sum(1 for k in uf.parent if is_key_email(k))
    total_synthetic_keys = sum(1 for k in uf.parent if is_key_synthetic(k))


    singleton_emails = sum(
        1 for k, v in clusters.items() if len(v) == 1 and is_key_email(list(v)[0])
    )
    singleton_synthetics = sum(
        1 for k, v in clusters.items() if len(v) == 1 and is_key_synthetic(list(v)[0])
    )


    unique_persons = len(set(v["person_id"] for v in entity_map.values()))

    stats = {
        "total_email_contacts": len(contact_emails),
        "total_new_source_contacts": len(all_new_contacts),
        "total_identifiers": total_email_keys + total_synthetic_keys,
        "multi_key_clusters": len(multi_clusters),
        "email_only_clusters": email_only_clusters,
        "mixed_clusters": mixed_clusters,
        "name_only_clusters": name_only_clusters,
        "keys_resolved": total_keys_resolved,
        "unique_persons_in_entity_map": unique_persons,
        "level0_matches": len(l0_matches),
        "level1_matches": len(l1_matches),
        "level2_matches": len(l2_matches),
        "level3_matches": len(l3_matches),
        "level4_matches": len(l4_matches),
        "level4_5_matches": len(l4_5_matches),
        "level4_5_rejects": len(l4_5_rejects),
        "level6_matches": len(l6_matches),
        "level7_matches": len(l7_matches),
        "review_queue_size": len(review_queue),
        "personio_employees": len(personio),
        "source_stats": {src: dict(st) for src, st in sorted(source_stats.items())},
    }


    def find_person(name_pattern):
        for key, info in entity_map.items():
            if name_pattern.lower() in info.get("canonical_name", "").lower():
                return info
        return None

    log.info("\n=== Entity Resolution V2 ===")
    log.info(f"Email contacts: {stats['total_email_contacts']}")
    log.info(f"New source contacts: {stats['total_new_source_contacts']}")
    log.info(f"Total identifiers tracked: {stats['total_identifiers']}")
    log.info(
        f"Multi-key clusters: {stats['multi_key_clusters']} "
        f"(email-only: {email_only_clusters}, "
        f"mixed: {mixed_clusters}, "
        f"name-only: {name_only_clusters})"
    )
    log.info(f"Keys resolved: {stats['keys_resolved']}")
    log.info(f"Unique persons in entity map: {stats['unique_persons_in_entity_map']}")
    log.info(f"Level 0 (manual overrides): {stats['level0_matches']}")
    log.info(f"Level 1 (det email): {stats['level1_matches']}")
    log.info(f"Level 2 (prob email): {stats['level2_matches']}")
    log.info(f"Level 3 (det cross-source): {stats['level3_matches']}")
    log.info(f"Level 4 (prob name): {stats['level4_matches']}")
    log.info(
        f"Level 4.5 (single-word auto): {stats['level4_5_matches']} merges, "
        f"{stats['level4_5_rejects']} rejects"
    )
    if args.use_relationships:
        log.info(f"Level 6 (relationship facts): {stats['level6_matches']}")
    if args.use_splink:
        log.info(f"Level 7 (Splink clusters): {stats['level7_matches']}")
    log.info(f"Review queue: {stats['review_queue_size']}")

    log.info("\n── Source Stats ──")
    for src, st in sorted(source_stats.items()):
        log.info(
            f"  {src:12s}: {st['total']:5d} total, "
            f"{st['matched']:4d} matched, "
            f"{st['review']:4d} review"
        )


    if args.import_decisions:
        log.info("\n── Import Decisions Summary ──")
        log.info(f"  Merges applied: {imported_merge_count} pairs")
        log.info(f"  Rejects applied: {imported_reject_count} pairs")
        log.info(f"  Total MANUAL_MERGES (incl. hardcoded): {len(MANUAL_MERGES)}")
        log.info(f"  Total MANUAL_REJECTS: {len(MANUAL_REJECTS)}")

    if args.dry_run:
        log.info("\n── Key Resolutions ──")
        # Spot check on the people you named in sbk.config.json "nickname_aliases".
        for name in sorted(set(NICKNAME_ALIASES.values())):
            info = find_person(name)
            if info:
                emails = info.get("all_emails", [])
                name_sources = info.get("name_sources", [])
                log.info(
                    f"  {info['canonical_name']}: {len(emails)} emails, sources={name_sources}"
                )
                for e in emails:
                    s = contact_scores.get(e, 0)
                    log.info(f"    {e:50s} score={s:.1f}")

        log.info("\n── Top 15 Largest Clusters ──")
        sorted_clusters = sorted(multi_clusters.items(), key=lambda x: -len(x[1]))
        for root, keys in sorted_clusters[:15]:
            info = entity_map.get(root, {})
            name = info.get("canonical_name", "?")
            email_count = sum(1 for k in keys if is_key_email(k))
            synth_count = sum(1 for k in keys if is_key_synthetic(k))
            log.info(f"  {name}: {len(keys)} keys ({email_count} emails, {synth_count} name-keys)")
            for k in sorted(keys):
                if is_key_email(k):
                    log.info(f"    {k}")
                else:
                    src_info = all_new_contacts.get(k, {})
                    log.info(f"    {k} [{src_info.get('source', '?')}]")

        if review_queue:
            log.info(f"\n── Review Queue ({len(review_queue)} items, first 20) ──")
            for item in review_queue[:20]:
                keys = item.get("keys", item.get("emails", []))
                log.info(f"  {keys}  names={item.get('names', [])}")
                log.info(f"    conf={item['confidence']:.2f}  ({item['reason']})")

        if args.import_decisions:
            log.info("\n── Dry Run: Import Decisions Would Apply ──")
            log.info(f"  Would merge {imported_merge_count} pairs")
            log.info(f"  Would reject {imported_reject_count} pairs")
            log.info("  Would clean up decided items from entity-review.json")

            review_path = ENRICHED_DIR / "entity-review.json"
            if review_path.exists():
                with open(review_path) as f:
                    existing_review = json.load(f)
                decided_pairs = set()
                for pair in raw_merge_pairs:
                    if len(pair) >= 2:
                        decided_pairs.add(frozenset(pair[:2]))
                for pair in raw_reject_pairs:
                    if len(pair) >= 2:
                        decided_pairs.add(frozenset(pair[:2]))
                would_remove = 0
                for item in existing_review:
                    item_keys = item.get("keys", item.get("emails", []))
                    if len(item_keys) >= 2 and frozenset(item_keys[:2]) in decided_pairs:
                        would_remove += 1
                log.info(
                    f"  Would remove {would_remove} of {len(existing_review)} "
                    f"items from entity-review.json"
                )

        return


    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)

    entity_map_path = ENRICHED_DIR / "entity-map.json"
    safe_write_json(entity_map_path, entity_map, backup=True)
    log.info(f"Saved entity map: {len(entity_map)} entries → {entity_map_path}")

    review_path = ENRICHED_DIR / "entity-review.json"
    safe_write_json(review_path, review_queue)
    log.info(f"Saved review queue: {len(review_queue)} items → {review_path}")

    stats_path = ENRICHED_DIR / "entity-stats.json"
    safe_write_json(stats_path, stats)
    log.info(f"Saved entity stats → {stats_path}")


    if args.import_decisions and (raw_merge_pairs or raw_reject_pairs):
        removed = cleanup_review_queue(review_path, raw_merge_pairs, raw_reject_pairs)
        log.info(f"Post-import cleanup: {removed} decided items removed from entity-review.json")

    log.info("\n=== Entity Resolution V2 complete ===")
    log.info(
        f"Resolved {stats['keys_resolved']} identifiers into "
        f"{stats['multi_key_clusters']} multi-key clusters"
    )
    log.info(f"Unique persons in entity map: {stats['unique_persons_in_entity_map']}")

    if not args.dry_run:
        from sbk_config import mark_last_run, save_input_checkpoint

        save_input_checkpoint("entity-resolve", [ENRICHED_DIR / "contacts-merged.parquet"])
        mark_last_run("entity-resolve")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-entity-resolve", source="entity-resolve", stage="l2", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
