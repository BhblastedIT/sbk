#!/usr/bin/env python3
""




























from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import setup_logging

from sbk_config import (
    ATTIO_TRANSCRIPTS_DIR,
    COMPANY_SUFFIXES,
    DATA_ROOT,
    ENRICHED_DIR,
    GENERIC_NICKNAMES,
    IPHONE_DIR,
    L3_DIR,
    NICKNAME_ALIASES,
    NLP_DIR,
    OWN_NAMES_NORMALIZED,
    OWN_ORG_NAMES,
    OWNER_SPEAKER_LABELS,
    PLAUD_DIR,
    RELATIONSHIP_FACTS_FILE,
    SHADOW_FILTERS_FILE,
    STT_NAME_CORRECTIONS,
    TACTIQ_DIR,
    attio_transcript_path,
    is_bot_or_service,
)

log = logging.getLogger("sbk-l3-shadow")



SHADOW_CONTACTS_FILE = NLP_DIR / "shadow-contacts.parquet"
SHADOW_CHECKPOINT_FILE = L3_DIR / "shadow-checkpoint.json"


TACTIQ_RAW_DIR = DATA_ROOT / "tactiq" / "raw"
PLAUD_RAW_DIR = PLAUD_DIR





FAMOUS_PEOPLE: set[str] = {
    "elon musk",
    "mark zuckerberg",
    "jeff bezos",
    "steve jobs",
    "bill gates",
    "sam altman",
    "jensen huang",
    "sundar pichai",
    "tim cook",
    "satya nadella",
    "warren buffett",
    "larry page",
    "sergey brin",
    "jack dorsey",
    "steve wozniak",
    "phil schiller",
    "scott forstall",
    "eric schmidt",
    "jerry yang",
    "stan sigman",
    "reed hastings",
    "andy jassy",
    "lisa su",
    "sheryl sandberg",
    "mark cuban",
    "peter thiel",
    "reid hoffman",
    "marc andreessen",
    "brian chesky",
    "travis kalanick",
    "dara khosrowshahi",
    "daniel ek",
    "patrick collison",
    "john collison",
    "stewart butterfield",
    "drew houston",
    "kevin systrom",
    "jack ma",
    "masayoshi son",
}



OWN_NAMES: set[str] = set(OWNER_SPEAKER_LABELS) | OWN_NAMES_NORMALIZED



SPEAKER_PATTERN = re.compile(r"^speaker\s*\d*$", re.IGNORECASE)
SLACK_ID_PATTERN = re.compile(r"^U[A-Z0-9]{8,11}$")
BOT_ID_PATTERN = re.compile(r"^B[A-Z0-9]{8,}$")
NUMBER_PATTERN = re.compile(r"^\d+$")


COMMON_NOUNS: set[str] = {
    "the",
    "team",
    "client",
    "company",
    "ceo",
    "cto",
    "cfo",
    "coo",
    "vp",
    "manager",
    "director",
    "founder",
    "investor",
    "partner",
    "advisor",
    "consultant",
    "analyst",
    "developer",
    "designer",
    "engineer",
    "marketing",
    "sales",
    "product",
    "finance",
    "legal",
    "operations",
    "customer",
    "user",
    "admin",
    "support",
    "hr",
    "recruiting",
    "hiring",
    "someone",
    "everyone",
    "nobody",
    "person",
    "people",
    "group",
    "organization",
    "brand",
    "agency",
    "platform",
    "service",
    "system",
    "bot",
    "assistant",
    "ai",
    "unknown",
    "none",
    "n/a",
    "na",
    "null",
    "undefined",
    "other",
    "various",
    "multiple",
    "several",
    "all",
    "both",
    "each",
    "any",
    "some",
    "speaker",
    "host",
    "guest",
    "attendee",
    "participant",
    "caller",
    "interviewee",
    "interviewer",
    "candidate",
    "applicant",
    "colleague",
    "coworker",
    "employee",
    "contractor",
    "freelancer",
    "vendor",
    "supplier",
    "buyer",
    "seller",
    "agency",
    "apex",

    "father",
    "mother",
    "brother",
    "sister",
    "son",
    "daughter",
    "wife",
    "husband",
    "uncle",
    "aunt",
    "cousin",
    "nephew",
    "niece",
    "grandfather",
    "grandmother",
    "grandson",
    "granddaughter",
    "padre",
    "madre",
    "fratello",
    "sorella",
    "figlio",
    "figlia",
    "moglie",
    "marito",
    "zio",
    "zia",
    "cugino",
    "cugina",
    "nipote",
    "nonno",
    "nonna",
    "suocera",
    "suocero",
    "cognato",
    "cognata",
    "compagna",
    "compagno",
    "fidanzata",
    "fidanzato",

    "parent",
    "child",
    "sibling",
    "spouse",
    "relative",
    "family",

    "mentor",
    "mentee",
    "coach",
    "boss",
    "lawyer",
    "avvocato",
    "commercialista",
    "notaio",
    "assistente",
    "segretaria",
    "consulente",
    "accountant",

    "meta",
    "google",
    "amazon",
    "apple",
    "tesla",
    "shopify",
    "uber",
    "netflix",
    "spotify",
    "airbnb",
    "stripe",

    "london",
    "new york",
    "paris",
    "tokyo",

    "imprenditore",
    "signora",
    "signore",
    "target",
    "sender",
    "recipient",
    "author",
}
# Your own organisations' names are never a person either.
COMMON_NOUNS |= OWN_ORG_NAMES


COMMON_PHRASES: set[str] = {
    "legal team",
    "family office",
    "family business",
    "has a family",
    "consulente esterno",
    "consulente del lavoro",
    "board member",
    "board of directors",
}



_RELATIONSHIP_PREFIX_PATTERN = re.compile(
    r"^(?:brother|sister|father|mother|uncle|aunt|cousin|son|daughter|"
    r"fratello|sorella|padre|madre|zio|zia|cugino|cugina|figlio|figlia|"
    r"nipote|nonno|nonna|mentor|avvocato|lawyer|husband|wife|"
    r"cognato|cognata|suocero|suocera|compagno|compagna|fidanzato|fidanzata|ex|"
    r"unknown|unnamed|unnamed male|unnamed female)\b",
    re.IGNORECASE,
)




_KNOWN_COMPANIES_CACHE: set[str] | None = None


# Your own organisations ("organisations" in sbk.config.json) and the counterparties in
# shadow-filters.json "company_map", used to filter the shadow extractor. Empty by default.
_ORG_ECOSYSTEM: set[str] = set(OWN_ORG_NAMES)


if SHADOW_FILTERS_FILE.exists():
    try:
        _sf_data = json.loads(SHADOW_FILTERS_FILE.read_text())
        COMMON_PHRASES.update(_sf_data.get("noise_patterns", []))
        _ORG_ECOSYSTEM.update(_sf_data.get("company_map", []))
    except (json.JSONDecodeError, OSError):
        pass


def _get_known_companies() -> set[str]:
    ""






    global _KNOWN_COMPANIES_CACHE
    if _KNOWN_COMPANIES_CACHE is not None:
        return _KNOWN_COMPANIES_CACHE

    companies: set[str] = set(_ORG_ECOSYSTEM)


    company_names_json = DATA_ROOT / "attio" / "lookups" / "company-names.json"
    if company_names_json.exists():
        try:
            data = json.loads(company_names_json.read_text())
            if isinstance(data, list):
                for name in data:
                    if isinstance(name, str) and name.strip():
                        companies.add(name.strip().lower())
            elif isinstance(data, dict):
                for name in data.values():
                    if isinstance(name, str) and name.strip():
                        companies.add(name.strip().lower())
        except (json.JSONDecodeError, OSError):
            pass


    companies_parquet = DATA_ROOT / "attio" / "processed" / "companies-attio.parquet"
    if companies_parquet.exists():
        try:
            df = pd.read_parquet(companies_parquet)
            if "company_name" in df.columns:
                for name in df["company_name"].dropna():
                    name_str = str(name).strip()
                    if name_str:
                        companies.add(name_str.lower())
        except Exception:
            pass

    _KNOWN_COMPANIES_CACHE = companies
    log.info(f"Loaded {len(companies)} known company names for filtering")
    return companies


def is_company_name(name: str) -> bool:
    ""
    n = name.strip().lower()
    if not n:
        return False

    known = _get_known_companies()


    if n in known:
        return True


    words = n.split()
    stripped_words = [w for w in words if w.strip(".") not in COMPANY_SUFFIXES]
    if stripped_words and len(stripped_words) < len(words):
        stripped = " ".join(stripped_words)
        if stripped in known:
            return True

    return False





def is_noise_name(name: str) -> bool:
    ""
    if not name or not name.strip():
        return True

    n = name.strip().lower()


    if len(n) < 3:
        return True


    if NUMBER_PATTERN.match(n):
        return True


    if n in OWN_NAMES:
        return True


    if n in FAMOUS_PEOPLE:
        return True


    if SPEAKER_PATTERN.match(n):
        return True


    if SLACK_ID_PATTERN.match(n):
        return True


    if BOT_ID_PATTERN.match(n):
        return True


    if n.startswith("deactivateduser"):
        return True


    if " " not in n and n in COMMON_NOUNS:
        return True


    if n in COMMON_PHRASES:
        return True


    if _RELATIONSHIP_PREFIX_PATTERN.match(n):
        return True


    if "@" in n:
        return True


    if n.startswith(("http://", "https://", "www.")):
        return True


    if is_bot_or_service(name):
        return True


    words = n.split()
    word_count = len(words)


    if word_count > 5:
        return True


    if len(n) > 40 and word_count > 3:
        return True


    name_words = words
    if any(w.strip(".") in COMPANY_SUFFIXES for w in name_words):
        return True


    if is_company_name(n):
        return True


    if re.match(
        r"^(?:unknown|unnamed|unspecified|anonymous|team member|speaker)\b", n, re.IGNORECASE
    ):
        return True


    if re.match(r"^\+?\d[\d\s\-\.\/]{5,}$", n):
        return True
    if re.match(r"^\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}$", n):
        return True


    if re.match(
        r"^(?:head of|director of|chief|lead|senior|junior|managing|"
        r"principal|associate|assistant)\s+\w+",
        n,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"^.+\s+(?:specialist|manager|director|lead|coordinator|analyst|strategist|officer)$",
        n,
        re.IGNORECASE,
    ):
        return True


    if re.match(
        r"^(?:works?\s+(?:at|with|for)|worked?\s+(?:at|with|for)|"
        r"ceo\s+(?:of|at|di|e\s)|cto\s+(?:of|at|di)|cfo\s+(?:of|at|di)|"
        r"founder\s+(?:of|di|and|&)|co-?founder\s+(?:of|di)|"
        r"employee\s+(?:at|of|di)|"
        r"espansione\s+di|hates?\s+)",
        n,
        re.IGNORECASE,
    ):
        return True


    if "/" in n:
        return True


    if "'s " in n or "\u2019s " in n:
        return True


    if word_count >= 4 and re.search(r"\b(?:and|e)\b", n):
        return True


    for brand in (*sorted(OWN_ORG_NAMES), "agency"):
        if brand in n and n != brand:
            return True

    return False





def load_known_names() -> tuple[set[str], dict[str, str]]:
    ""





    known_names: set[str] = set()
    first_name_counts: dict[str, list[str]] = defaultdict(list)


    people_universe = ENRICHED_DIR / "people-universe.parquet"
    if people_universe.exists():
        try:
            df = pd.read_parquet(people_universe)
            for _, row in df.iterrows():
                cn = str(row.get("canonical_name", "")).strip().lower()
                if cn and len(cn) >= 3:
                    known_names.add(cn)
                    parts = cn.split()
                    if len(parts) >= 2:
                        first_name_counts[parts[0]].append(cn)

                aliases_str = str(row.get("aliases", "")).strip()
                if aliases_str and aliases_str != "nan":
                    for alias in aliases_str.split("|"):
                        alias = alias.strip().lower()
                        if alias and len(alias) >= 3:
                            known_names.add(alias)
        except Exception as e:
            log.warning(f"Could not load people-universe: {e}")


    entity_map_file = ENRICHED_DIR / "entity-map.json"
    if entity_map_file.exists():
        try:
            data = json.loads(entity_map_file.read_text())
            for key, value in data.items():
                if key.startswith("nameonly:"):
                    cn = (
                        str(value.get("canonical_name", "") if isinstance(value, dict) else value)
                        .strip()
                        .lower()
                    )
                    if cn and len(cn) >= 3:
                        known_names.add(cn)
                        parts = cn.split()
                        if len(parts) >= 2:
                            first_name_counts[parts[0]].append(cn)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load entity-map: {e}")


    contacts_file = ENRICHED_DIR / "contacts-merged.parquet"
    if contacts_file.exists():
        try:
            df = pd.read_parquet(contacts_file)
            if "name" in df.columns:
                for name in df["name"].dropna():
                    n = str(name).strip().lower()
                    if n and len(n) >= 3:
                        known_names.add(n)
                        parts = n.split()
                        if len(parts) >= 2:
                            first_name_counts[parts[0]].append(n)
        except Exception as e:
            log.warning(f"Could not load contacts-merged: {e}")


    iphone_file = IPHONE_DIR / "contacts-iphone.parquet"
    if iphone_file.exists():
        try:
            df = pd.read_parquet(iphone_file)
            if "name" in df.columns:
                for name in df["name"].dropna():
                    n = str(name).strip().lower()
                    if n and len(n) >= 3:
                        known_names.add(n)
                        parts = n.split()
                        if len(parts) >= 2:
                            first_name_counts[parts[0]].append(n)
        except Exception as e:
            log.warning(f"Could not load contacts-iphone: {e}")


    known_first_to_full: dict[str, str] = {}
    for first, fulls in first_name_counts.items():
        unique_fulls = list(set(fulls))
        if len(unique_fulls) == 1:
            known_first_to_full[first] = unique_fulls[0]

    log.info(
        f"Loaded {len(known_names)} known names, "
        f"{len(known_first_to_full)} unique first-name mappings"
    )
    return known_names, known_first_to_full


def filter_known_contacts(
    shadows: list[dict],
    known_names: set[str],
    known_first_to_full: dict[str, str],
) -> list[dict]:
    ""







    from rapidfuzz import fuzz


    known_multi = [n for n in known_names if 1 < len(n.split()) <= 3]

    removed_exact = 0
    removed_nickname = 0
    removed_first = 0
    removed_fuzzy = 0
    kept: list[dict] = []

    for shadow in shadows:
        cn = shadow["canonical_name"]


        if cn in known_names:
            removed_exact += 1
            continue


        if cn in NICKNAME_ALIASES:
            removed_nickname += 1
            continue


        for alias in NICKNAME_ALIASES:
            if cn.startswith(alias) and len(cn) <= len(alias) + 2:
                removed_nickname += 1
                cn = None
                break
        if cn is None:
            continue


        parts = cn.split()
        if len(parts) == 1 and cn in known_first_to_full:
            removed_first += 1
            continue

        # Generic nickname of a known contact: "bob smith" for a known "robert smith",
        # "bob" when the only Robert you know is one person.
        given = GENERIC_NICKNAMES.get(parts[0]) if parts else None
        if given and (
            " ".join([given, *parts[1:]]) in known_names
            or (len(parts) == 1 and given in known_first_to_full)
        ):
            removed_nickname += 1
            continue


        if 2 <= len(parts) <= 3:
            matched = False
            for known in known_multi:
                score = fuzz.token_sort_ratio(cn, known)
                if score >= 90:
                    matched = True
                    break
            if matched:
                removed_fuzzy += 1
                continue

        kept.append(shadow)

    total_removed = removed_exact + removed_nickname + removed_first + removed_fuzzy
    log.info(
        f"Known contacts filter: {len(shadows)} -> {len(kept)} shadows "
        f"({total_removed} removed: {removed_exact} exact, {removed_nickname} nickname, "
        f"{removed_first} first-name, {removed_fuzzy} fuzzy)"
    )
    return kept





def normalize_name(name: str) -> str:
    ""
    n = name.strip().lower()

    n = re.sub(r"\s+", " ", n)

    n = re.sub(r"\s*\(.*$", "", n)

    n = re.sub(r"-external\b", "", n)

    n = n.strip(".,;:!?\"'()-")
    n = n.strip()

    if n in STT_NAME_CORRECTIONS:
        n = STT_NAME_CORRECTIONS[n]
    else:

        for wrong, correct in STT_NAME_CORRECTIONS.items():
            n = re.sub(r"\b" + re.escape(wrong) + r"\b", correct, n)
    return n


def make_shadow_id(canonical_name: str) -> str:
    ""
    h = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()[:6]
    return f"sh_{h}"





def _is_abbreviated(name: str) -> bool:
    ""
    parts = name.split()
    return len(parts) >= 2 and any(len(p.strip(".")) <= 1 for p in parts)


def fuzzy_cluster_names(names: list[str], threshold: int = 85) -> dict[str, str]:
    ""







    from rapidfuzz import fuzz



    clusters: list[list[str]] = []
    name_to_cluster: dict[str, int] = {}

    sorted_names = sorted(names)

    for name in sorted_names:
        matched_cluster = -1
        best_score = 0
        name_is_abbrev = _is_abbreviated(name)


        for idx, cluster in enumerate(clusters):
            rep = cluster[0]

            rep_is_abbrev = _is_abbreviated(rep)
            if name_is_abbrev != rep_is_abbrev:
                continue
            score = fuzz.token_sort_ratio(name, rep)
            if score >= threshold and score > best_score:
                best_score = score
                matched_cluster = idx

        if matched_cluster >= 0:
            clusters[matched_cluster].append(name)
            name_to_cluster[name] = matched_cluster
        else:

            name_to_cluster[name] = len(clusters)
            clusters.append([name])



    mapping: dict[str, str] = {}
    for cluster in clusters:

        freq: dict[str, int] = defaultdict(int)
        for n in cluster:
            freq[n] += 1

        canonical = sorted(freq.keys(), key=lambda x: (-freq[x], -len(x)))[0]
        for n in cluster:
            mapping[n] = canonical

    return mapping





def load_meeting_context(source_id: str, source_type: str) -> dict | None:
    ""




    if source_type == "tactiq":

        raw_file = TACTIQ_RAW_DIR / f"{source_id}.json"
        if raw_file.exists():
            try:
                data = json.loads(raw_file.read_text())
                if isinstance(data, dict):
                    return {
                        "title": data.get("title", data.get("meetingTitle", "")),
                        "date": str(data.get("created", data.get("meetingDate", "")))[:10],
                        "participants": data.get("participants", data.get("speakers", [])),
                        "source_type": "tactiq",
                    }
            except (json.JSONDecodeError, OSError):
                pass

        proc_file = TACTIQ_DIR / f"{source_id}.json"
        if proc_file.exists():
            try:
                data = json.loads(proc_file.read_text())
                if isinstance(data, dict):
                    return {
                        "title": data.get("title", ""),
                        "date": str(data.get("created", ""))[:10],
                        "participants": data.get("participants", []),
                        "source_type": "tactiq",
                    }
            except (json.JSONDecodeError, OSError):
                pass

    elif source_type == "plaud":



        raw_file = PLAUD_RAW_DIR / f"{source_id}.json"
        if raw_file.exists():
            try:
                data = json.loads(raw_file.read_text())
                speakers = set()
                if isinstance(data, list):
                    for seg in data:
                        if isinstance(seg, dict):
                            speaker = seg.get("speaker", "")
                            if speaker:
                                speakers.add(speaker)
                elif isinstance(data, dict):
                    speakers = set(data.get("speakers", []))

                date_str = ""
                if len(source_id) >= 10 and source_id[:4].isdigit():
                    date_str = source_id[:10]

                title = source_id
                if date_str and title.startswith(date_str):
                    title = title[11:].strip("_ ")
                return {
                    "title": title,
                    "date": date_str,
                    "participants": sorted(speakers),
                    "source_type": "plaud",
                }
            except (json.JSONDecodeError, OSError):
                pass

    elif source_type == "attio_call":

        raw_file = attio_transcript_path(source_id, ATTIO_TRANSCRIPTS_DIR)
        if raw_file.exists():
            try:
                data = json.loads(raw_file.read_text())
                speakers = set()
                for seg in data.get("segments", []):
                    speaker = seg.get("speaker")
                    if speaker:
                        speakers.add(speaker)
                return {
                    "title": data.get("meeting_title", ""),
                    "date": str(data.get("meeting_date", ""))[:10],
                    "participants": sorted(speakers),
                    "source_type": "attio_call",
                }
            except (json.JSONDecodeError, OSError):
                pass

    elif source_type in ("slack", "attio_notes", "whatsapp"):


        return None

    return None





def compute_confidence_score(
    mention_count: int,
    source_diversity: int,
    high_confidence_ratio: float,
    last_seen: str,
) -> float:
    ""








    freq_score = min(mention_count, 10) / 10.0


    div_score = min(source_diversity, 4) / 4.0


    recency = 0.0
    if last_seen:
        try:
            last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:

                last_dt = datetime.strptime(last_seen[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            days_ago = (datetime.now(UTC) - last_dt).days
            if days_ago <= 90:
                recency = 1.0
            elif days_ago <= 365:
                recency = max(0.0, 1.0 - (days_ago - 90) / 275.0)
            else:
                recency = 0.0
        except (ValueError, TypeError):
            recency = 0.0

    score = freq_score * 0.30 + div_score * 0.25 + high_confidence_ratio * 0.25 + recency * 0.20
    return round(min(1.0, max(0.0, score)), 4)


def compute_shadow_score(confidence_score: float, mention_count: int) -> float:
    ""



    volume_boost = 0.5 + 0.5 * min(mention_count, 20) / 20.0
    return round(confidence_score * 100.0 * volume_boost, 2)





def load_checkpoint() -> dict:
    ""
    if SHADOW_CHECKPOINT_FILE.exists():
        try:
            return json.loads(SHADOW_CHECKPOINT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _ingressi() -> dict[str, float]:
    ""





    file = (
        RELATIONSHIP_FACTS_FILE,
        ENRICHED_DIR / "people-universe.parquet",
        ENRICHED_DIR / "entity-map.json",
        ENRICHED_DIR / "contacts-merged.parquet",
        IPHONE_DIR / "contacts-iphone.parquet",
    )
    return {f.name: f.stat().st_mtime for f in file if f.exists()}


def save_checkpoint(
    facts_mtime: float, num_shadows: int, ingressi: dict[str, float] | None = None
) -> None:
    ""
    SHADOW_CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "last_run": datetime.now(UTC).isoformat(),
        "facts_mtime": facts_mtime,
        "num_shadows": num_shadows,
        "ingressi": ingressi if ingressi is not None else _ingressi(),
    }
    SHADOW_CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


def should_skip(force: bool = False) -> bool:
    ""
    if force:
        return False
    if not RELATIONSHIP_FACTS_FILE.exists():
        log.warning(f"relationship-facts.parquet not found: {RELATIONSHIP_FACTS_FILE}")
        return True
    checkpoint = load_checkpoint()
    if not checkpoint:
        return False

    if checkpoint.get("ingressi") == _ingressi():
        log.info(
            "Checkpoint: relationship facts and known names unchanged since last run, skipping"
        )
        return True
    return False





def extract_shadow_candidates(df: pd.DataFrame) -> pd.DataFrame:
    ""



    candidates = []

    df = df.copy()

    missing = []
    for col in ("subject_person_id", "subject", "object_person_id", "object"):
        if col not in df.columns:
            df[col] = ""
            missing.append(col)
    if missing:
        log.warning(
            "extract_shadow_candidates: auto-filled missing cols %s — upstream producer should enforce schema",
            missing,
        )


    subject_mask = df["subject_person_id"].fillna("").astype(str).str.strip().eq("") & df[
        "subject"
    ].fillna("").astype(str).str.strip().ne("")
    for _, row in df[subject_mask].iterrows():
        candidates.append(
            {
                "name": str(row["subject"]).strip(),
                "role": "subject",
                "fact_type": str(row.get("fact_type", "")),
                "predicate": str(row.get("predicate", "")),
                "object_name": str(row.get("object", "")),
                "object_person_id": str(row.get("object_person_id", "")),
                "confidence": str(row.get("confidence", "medium")),
                "context": str(row.get("context", "")),
                "source_id": str(row.get("source_id", "")),
                "source_type": str(row.get("source_type", "")),
                "source_date": str(row.get("source_date", row.get("extracted_at", ""))),
                "extracted_at": str(row.get("extracted_at", "")),
            }
        )


    object_mask = df["object_person_id"].fillna("").astype(str).str.strip().eq("") & df[
        "object"
    ].fillna("").astype(str).str.strip().ne("")
    for _, row in df[object_mask].iterrows():
        candidates.append(
            {
                "name": str(row["object"]).strip(),
                "role": "object",
                "fact_type": str(row.get("fact_type", "")),
                "predicate": str(row.get("predicate", "")),
                "object_name": str(row.get("subject", "")),
                "object_person_id": str(row.get("subject_person_id", "")),
                "confidence": str(row.get("confidence", "medium")),
                "context": str(row.get("context", "")),
                "source_id": str(row.get("source_id", "")),
                "source_type": str(row.get("source_type", "")),
                "source_date": str(row.get("source_date", row.get("extracted_at", ""))),
                "extracted_at": str(row.get("extracted_at", "")),
            }
        )

    return pd.DataFrame(candidates)


def filter_noise(candidates: pd.DataFrame) -> pd.DataFrame:
    ""
    if candidates.empty:
        return candidates

    before = len(candidates)
    mask = candidates["name"].apply(lambda n: not is_noise_name(n))
    filtered = candidates[mask].copy()
    removed = before - len(filtered)
    log.info(f"Noise filter: {before} -> {len(filtered)} candidates ({removed} removed)")
    return filtered


def aggregate_shadows(
    candidates: pd.DataFrame,
) -> list[dict]:
    ""




    if candidates.empty:
        return []


    candidates = candidates.copy()
    candidates["norm_name"] = candidates["name"].apply(normalize_name)


    candidates = candidates[candidates["norm_name"].str.len() >= 3]


    candidates = candidates[~candidates["norm_name"].apply(is_noise_name)]


    unique_names = candidates["norm_name"].unique().tolist()
    log.info(f"Fuzzy clustering {len(unique_names)} unique normalized names...")
    name_clusters = fuzzy_cluster_names(unique_names, threshold=85)


    candidates["canonical_name"] = candidates["norm_name"].map(name_clusters)


    shadows = []
    grouped = candidates.groupby("canonical_name")

    for canonical, group in grouped:

        name_counts: dict[str, int] = defaultdict(int)
        for n in group["name"]:
            name_counts[n.strip()] += 1
        display_name = sorted(name_counts.keys(), key=lambda x: (-name_counts[x], -len(x)))[0]


        aliases = sorted(set(n.strip() for n in group["name"] if n.strip()))


        mention_count = len(group)


        source_types = sorted(set(st for st in group["source_type"] if st and st.strip()))
        source_diversity = len(source_types)


        fact_types = sorted(set(ft for ft in group["fact_type"] if ft and ft.strip()))


        mentioned_by_pids: set[str] = set()
        mentioned_by_names: set[str] = set()
        for _, row in group.iterrows():
            other_pid = str(row.get("object_person_id", "")).strip()
            other_name = str(row.get("object_name", "")).strip()
            if other_pid:
                mentioned_by_pids.add(other_pid)
            if other_name and not is_noise_name(other_name):
                mentioned_by_names.add(other_name)


        facts_list = []
        for _, row in group.iterrows():
            facts_list.append(
                {
                    "fact_type": row.get("fact_type", ""),
                    "predicate": row.get("predicate", ""),
                    "other_party": row.get("object_name", ""),
                    "confidence": row.get("confidence", "medium"),
                    "context": row.get("context", "")[:200],
                    "source_type": row.get("source_type", ""),
                    "source_id": row.get("source_id", ""),
                }
            )


        meetings_list = []
        seen_meetings: set[str] = set()
        for _, row in group.iterrows():
            sid = str(row.get("source_id", ""))
            stype = str(row.get("source_type", ""))
            meeting_key = f"{stype}:{sid}"
            if meeting_key in seen_meetings or not sid:
                continue
            seen_meetings.add(meeting_key)
            try:
                ctx = load_meeting_context(sid, stype)
            except Exception:
                ctx = None
            if ctx:
                participants = ctx.get("participants", [])
                if isinstance(participants, list):
                    participants = ", ".join(str(p) for p in participants)
                meetings_list.append(
                    {
                        "title": ctx.get("title", ""),
                        "date": ctx.get("date", ""),
                        "participants": participants,
                        "source_type": ctx.get("source_type", ""),
                    }
                )


        dates = []
        for d in group["source_date"]:
            d_str = str(d).strip()
            if d_str and len(d_str) >= 10 and d_str[:4].isdigit():
                dates.append(d_str[:10])

        for d in group["extracted_at"]:
            d_str = str(d).strip()
            if d_str and len(d_str) >= 10 and d_str[:4].isdigit():
                dates.append(d_str[:10])

        dates = sorted(set(d for d in dates if d))
        first_seen = dates[0] if dates else ""
        last_seen = dates[-1] if dates else ""


        confidences = [str(c).lower() for c in group["confidence"]]
        high_count = sum(1 for c in confidences if c == "high")
        high_confidence_ratio = high_count / max(len(confidences), 1)


        confidence_score = compute_confidence_score(
            mention_count=mention_count,
            source_diversity=source_diversity,
            high_confidence_ratio=high_confidence_ratio,
            last_seen=last_seen,
        )
        shadow_score = compute_shadow_score(confidence_score, mention_count)


        inferred_company = _infer_company(facts_list, group)
        inferred_role = _infer_role(facts_list, group)


        intro_via_pid = ""
        intro_via_name = ""
        if mentioned_by_pids:

            pid_counts: dict[str, int] = defaultdict(int)
            for _, row in group.iterrows():
                pid = str(row.get("object_person_id", "")).strip()
                if pid:
                    pid_counts[pid] += 1
            if pid_counts:
                intro_via_pid = sorted(pid_counts.keys(), key=lambda x: -pid_counts[x])[0]
        if mentioned_by_names:
            name_counts_intro: dict[str, int] = defaultdict(int)
            for _, row in group.iterrows():
                other = str(row.get("object_name", "")).strip()
                if other and not is_noise_name(other):
                    name_counts_intro[other] += 1
            if name_counts_intro:
                intro_via_name = sorted(
                    name_counts_intro.keys(), key=lambda x: -name_counts_intro[x]
                )[0]

        shadow = {
            "shadow_id": make_shadow_id(canonical),
            "canonical_name": canonical,
            "display_name": display_name,
            "aliases": json.dumps(aliases, ensure_ascii=False),
            "mention_count": mention_count,
            "source_types": json.dumps(source_types, ensure_ascii=False),
            "source_diversity": source_diversity,
            "fact_types": json.dumps(fact_types, ensure_ascii=False),
            "mentioned_by_pids": json.dumps(sorted(mentioned_by_pids), ensure_ascii=False),
            "mentioned_by_names": json.dumps(sorted(mentioned_by_names), ensure_ascii=False),
            "facts_json": json.dumps(facts_list, ensure_ascii=False),
            "meetings_json": json.dumps(meetings_list, ensure_ascii=False),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "confidence_score": confidence_score,
            "shadow_score": shadow_score,
            "inferred_company": inferred_company,
            "inferred_role": inferred_role,
            "intro_via_pid": intro_via_pid,
            "intro_via_name": intro_via_name,
            "extracted_at": datetime.now(UTC).isoformat(),
        }
        shadows.append(shadow)

    return shadows






_COMPANY_PREDICATES = {"WORKS_AT", "WORKS_WITH", "FOUNDER_OF", "CEO_OF", "CTO_OF", "LEADS"}


_ROLE_PREDICATES = {"REPORTS_TO", "LEADS", "MANAGES", "CEO_OF", "CTO_OF", "CFO_OF"}


_ROLE_KEYWORDS = re.compile(
    r"\b(ceo|cto|cfo|coo|cmo|vp|svp|evp|director|head of|manager|lead|founder|"
    r"co-founder|partner|principal|associate|analyst|consultant|engineer|"
    r"developer|designer|architect|scientist|researcher)\b",
    re.IGNORECASE,
)


_COMPANY_INDICATORS: set[str] = {
    "srl",
    "spa",
    "ltd",
    "inc",
    "gmbh",
    "llc",
    "group",
    "holding",
    "s.r.l.",
    "s.p.a.",
    "corp",
    "ag",
    "bv",
    "plc",
    "pty",
    "co",
}


def _looks_like_person_name(candidate: str) -> bool:
    ""
    words = candidate.split()
    if len(words) > 3:
        return False

    if any(w.lower() in _COMPANY_INDICATORS for w in words):
        return False

    if all(w[0].isupper() and w.isalpha() for w in words if w):
        return True
    return False


def _infer_company(facts_list: list[dict], group: pd.DataFrame) -> str:
    ""

    for fact in facts_list:
        pred = str(fact.get("predicate", "")).upper()
        if pred in _COMPANY_PREDICATES:
            other = str(fact.get("other_party", "")).strip()
            if other and len(other) > 2 and not is_noise_name(other):

                if _looks_like_person_name(other):
                    continue
                return other


    for fact in facts_list:
        ctx = str(fact.get("context", ""))

        at_match = re.search(
            r"\b(?:at|from)\s+([A-Z][A-Za-z0-9&]{1,30}(?:\s+[A-Z][A-Za-z0-9&]{1,30}){0,3})"
            r"(?=\s+(?:for|since|during|in|as|where|who|which|that|and|but|or|,|\.|$)|\s*$)",
            ctx,
        )
        if at_match:
            company = at_match.group(1).strip()
            if len(company) > 2 and len(company) < 50:

                if _looks_like_person_name(company):
                    continue
                return company

    return ""


def _infer_role(facts_list: list[dict], group: pd.DataFrame) -> str:
    ""

    for fact in facts_list:
        pred = str(fact.get("predicate", "")).upper()
        if pred in _ROLE_PREDICATES:

            role_map = {
                "CEO_OF": "CEO",
                "CTO_OF": "CTO",
                "CFO_OF": "CFO",
                "LEADS": "Lead",
                "MANAGES": "Manager",
            }
            if pred in role_map:
                return role_map[pred]


    for fact in facts_list:
        ctx = str(fact.get("context", ""))
        match = _ROLE_KEYWORDS.search(ctx)
        if match:
            return match.group(1).title()


    for fact in facts_list:
        if fact.get("fact_type") == "personal_detail":
            pred = str(fact.get("predicate", "")).upper()
            if pred in ("JOB_TITLE", "ROLE", "POSITION"):
                other = str(fact.get("other_party", "")).strip()
                if other:
                    return other

    return ""





def show_stats(shadows: list[dict]) -> None:
    ""
    if not shadows:
        log.info("No shadow contacts found")
        return

    df = pd.DataFrame(shadows)
    total = len(df)
    with_company = len(df[df["inferred_company"] != ""])
    with_role = len(df[df["inferred_role"] != ""])
    with_meetings = len(df[df["meetings_json"] != "[]"])

    log.info("SHADOW CONTACTS SUMMARY")
    log.info("  Total shadow contacts:     %d", total)
    log.info("  With inferred company:     %d", with_company)
    log.info("  With inferred role:        %d", with_role)
    log.info("  With meeting context:      %d", with_meetings)
    log.info("  Avg mention count:         %.1f", df["mention_count"].mean())
    log.info("  Avg confidence score:      %.3f", df["confidence_score"].mean())
    log.info("  Avg shadow score:          %.1f", df["shadow_score"].mean())
    log.info("  Max shadow score:          %.1f", df["shadow_score"].max())


    log.info("  Source diversity:")
    for d in sorted(df["source_diversity"].unique()):
        count = len(df[df["source_diversity"] == d])
        log.info("    %d source(s): %d shadows", d, count)


    log.info("  Top 10 by shadow_score:")
    top = df.nlargest(10, "shadow_score")
    for i, (_, row) in enumerate(top.iterrows(), 1):
        company_str = f" @ {row['inferred_company']}" if row["inferred_company"] else ""
        role_str = f" ({row['inferred_role']})" if row["inferred_role"] else ""
        log.info(
            "    %2d. %s%s%s  [score=%.1f, mentions=%d, sources=%d]",
            i,
            row["display_name"],
            role_str,
            company_str,
            row["shadow_score"],
            row["mention_count"],
            row["source_diversity"],
        )





SHADOW_SCHEMA = pa.schema(
    [
        ("shadow_id", pa.string()),
        ("canonical_name", pa.string()),
        ("display_name", pa.string()),
        ("aliases", pa.string()),
        ("mention_count", pa.int64()),
        ("source_types", pa.string()),
        ("source_diversity", pa.int64()),
        ("fact_types", pa.string()),
        ("mentioned_by_pids", pa.string()),
        ("mentioned_by_names", pa.string()),
        ("facts_json", pa.string()),
        ("meetings_json", pa.string()),
        ("first_seen", pa.string()),
        ("last_seen", pa.string()),
        ("confidence_score", pa.float64()),
        ("shadow_score", pa.float64()),
        ("inferred_company", pa.string()),
        ("inferred_role", pa.string()),
        ("intro_via_pid", pa.string()),
        ("intro_via_name", pa.string()),
        ("extracted_at", pa.string()),
    ]
)


def save_shadows(shadows: list[dict]) -> Path:
    ""
    SHADOW_CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)


    arrays = {}
    for field in SHADOW_SCHEMA:
        col_name = field.name
        values = [row.get(col_name, "") for row in shadows]
        if field.type == pa.int64():
            arrays[col_name] = pa.array([int(v) if v else 0 for v in values], type=pa.int64())
        elif field.type == pa.float64():
            arrays[col_name] = pa.array([float(v) if v else 0.0 for v in values], type=pa.float64())
        else:
            arrays[col_name] = pa.array([str(v) if v is not None else "" for v in values])

    table = pa.table(arrays, schema=SHADOW_SCHEMA)
    pq.write_table(table, SHADOW_CONTACTS_FILE)
    log.info(f"Saved {len(shadows)} shadow contacts to {SHADOW_CONTACTS_FILE}")
    return SHADOW_CONTACTS_FILE





def run(
    force: bool = False,
    stats_only: bool = False,
    min_score: float = 8.0,
    min_mentions: int = 2,
    min_sources: int = 1,
    verbose: bool = False,
) -> list[dict]:
    ""



    setup_logging(verbose=verbose, name="sbk-l3-shadow")

    log.info("=" * 60)
    log.info("SBK Shadow Contacts Extraction")
    log.info("=" * 60)


    if stats_only:
        if SHADOW_CONTACTS_FILE.exists():
            existing = pd.read_parquet(SHADOW_CONTACTS_FILE)
            shadows = existing.to_dict("records")
            show_stats(shadows)
        else:
            log.warning(f"No shadow contacts file found: {SHADOW_CONTACTS_FILE}")
        return []


    if should_skip(force=force):
        return []


    if not RELATIONSHIP_FACTS_FILE.exists():
        log.error(f"relationship-facts.parquet not found: {RELATIONSHIP_FACTS_FILE}")
        return []

    facts_mtime = RELATIONSHIP_FACTS_FILE.stat().st_mtime

    ingressi = _ingressi()
    log.info(f"Loading relationship facts from {RELATIONSHIP_FACTS_FILE}")
    df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
    log.info(f"Loaded {len(df)} facts")


    log.info("Extracting shadow candidates...")
    candidates = extract_shadow_candidates(df)
    log.info(f"Found {len(candidates)} candidate mentions")

    if candidates.empty:
        log.info("No shadow candidates found")
        return []


    log.info("Filtering noise names...")
    candidates = filter_noise(candidates)

    if candidates.empty:
        log.info("All candidates filtered as noise")
        return []


    log.info("Aggregating shadow contacts with fuzzy dedup...")
    shadows = aggregate_shadows(candidates)
    log.info(f"Aggregated into {len(shadows)} unique shadow contacts")


    log.info("Loading known contacts for cross-reference...")
    known_names, known_first_to_full = load_known_names()
    shadows = filter_known_contacts(shadows, known_names, known_first_to_full)


    before_mentions = len(shadows)
    shadows = [s for s in shadows if s["mention_count"] >= min_mentions]
    log.info(f"Min mentions filter (>={min_mentions}): {before_mentions} -> {len(shadows)} shadows")

    before_sources = len(shadows)
    shadows = [s for s in shadows if s["source_diversity"] >= min_sources]
    log.info(f"Min sources filter (>={min_sources}): {before_sources} -> {len(shadows)} shadows")


    before_filter = len(shadows)
    shadows = [s for s in shadows if s["shadow_score"] >= min_score]
    log.info(f"Score filter (min={min_score}): {before_filter} -> {len(shadows)} shadows")


    shadows.sort(key=lambda s: -s["shadow_score"])


    show_stats(shadows)


    if shadows:
        save_shadows(shadows)
    else:
        log.info("No shadows to save after filtering")


    save_checkpoint(facts_mtime, len(shadows), ingressi)
    log.info("Checkpoint saved")

    log.info("Shadow extraction complete")
    return shadows





def main():
    parser = argparse.ArgumentParser(
        description="SBK Shadow Contacts Extraction — "
        "Extract people mentioned in conversations who aren't in the main graph",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extraction even if checkpoint is fresh",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show stats only without extracting",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=8.0,
        help="Minimum shadow_score to include (default: 8.0)",
    )
    parser.add_argument(
        "--min-mentions",
        type=int,
        default=2,
        help="Minimum mention count to include (default: 2)",
    )
    parser.add_argument(
        "--min-sources",
        type=int,
        default=1,
        help="Minimum source diversity to include (default: 1)",
    )

    args = parser.parse_args()


    from sbk_config import acquire_pid_lock

    if not acquire_pid_lock("l3-shadow-extract", logger=log):
        log.warning("l3-shadow-extract: lock tenuto da un'altra istanza, exit 75")
        sys.exit(75)

    shadows = run(
        force=args.force,
        stats_only=args.stats,
        min_score=args.min_score,
        min_mentions=args.min_mentions,
        min_sources=args.min_sources,
        verbose=args.verbose,
    )

    if shadows:
        log.info(f"Done: {len(shadows)} shadow contacts extracted")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-shadow-extract", source="l3-shadow-extract", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
