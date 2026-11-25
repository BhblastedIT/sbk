#!/usr/bin/env python3
""





















from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, setup_logging

from sbk_config import (
    DEEP_FACTS_FILE,
    EXPORTS_DIR,
    GRAPH_DIR,
    OWN_EMAILS,
    OWN_NAMES_NORMALIZED,
    OWN_ORG_ALIASES,
    OWNER_GRAPH_ID,
    OWNER_LABEL,
    OWNER_SPEAKER_LABELS,
    RELATIONSHIP_FACTS_FILE,
    acquire_pid_lock,
    extract_name_from_email,
    is_non_human_node,
    release_pid_lock,
)

log = logging.getLogger("sbk-l3-graph")


GRAPH_FILE = GRAPH_DIR / "sbk-graph.gpickle"
COMMUNITIES_FILE = GRAPH_DIR / "communities.json"
CENTRALITY_FILE = GRAPH_DIR / "centrality.json"
NETWORK_GRAPH_FILE = EXPORTS_DIR / "network-graph.json"


RELATIONSHIP_WEIGHTS: dict[str, float] = {
    "PARTNER_OF": 10,
    "FAMILY_OF": 8,
    "INVESTED_IN": 6,
    "FRIEND_OF": 5,
    "ADVISOR_TO": 5,
    "REPORTS_TO": 4,
    "RECOMMENDED_BY": 3,
    "INTRODUCED_BY": 3,
    "WORKS_WITH": 2,
    "KNOWS_FROM": 2,
}


DEEP_FACT_WEIGHTS: dict[str, float] = {
    "financial": 7,
    "deal": 8,
    "commitment": 6,
    "negotiation": 5,
    "strategic": 4,
    "operational": 3,
}




# Other spellings of your own organisations -> one name ("organisations.aliases" in
# sbk.config.json, e.g. {"Demo Co S.r.l.": "Demo Co"}). Empty by default.
ORG_CANONICAL: dict[str, str] = dict(OWN_ORG_ALIASES)
















_CONF_NUM = {"high": 0.85, "medium": 0.60, "low": 0.35}

SOGLIA_CONF = 0.60


def _conf_ok(colonna):
    ""
    import pandas as pd

    numerica = pd.to_numeric(colonna, errors="coerce")

    return numerica.fillna(colonna.astype(str).str.lower().map(_CONF_NUM)).fillna(0) >= SOGLIA_CONF


def _conf_valore(v) -> float:
    ""
    if isinstance(v, int | float):
        return float(v)
    return _CONF_NUM.get(str(v).strip().lower(), 0.60)


def _build_name_lookup(contacts: pd.DataFrame) -> dict[str, str]:
    ""




    lookup: dict[str, str] = {}
    score_by_name: dict[str, float] = {}

    for _, row in contacts.iterrows():
        name = row.get("name")
        pid = row.get("person_id")
        score = row.get("score", 0) or 0
        if not name or not pid:
            continue
        norm = name.strip().lower()
        if norm in OWN_NAMES_NORMALIZED:
            continue
        if norm not in lookup or score > score_by_name.get(norm, 0):
            lookup[norm] = pid
            score_by_name[norm] = score

    return lookup


def _parse_tactiq_names(raw: str) -> list[str]:
    ""





    if not raw or pd.isna(raw):
        return []

    noise_tokens = {"notetaker", "meeting notes", "read.ai", "otter.ai", "fireflies"}
    names = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue

        if "|" in part:
            part = part.split("|")[0].strip()

        if any(tok in part.lower() for tok in noise_tokens):
            continue
        names.append(part)
    return names


def _resolve_name_to_pid(
    name: str,
    name_lookup: dict[str, str],
    entity_map: dict,
) -> str | None:
    ""
    norm = name.strip().lower()
    if norm in OWN_NAMES_NORMALIZED:
        return None


    if norm in name_lookup:
        return name_lookup[norm]


    for source in ("tactiq", "plaud", "slack", "linkedin", "iphone", "notion"):
        key = f"nameonly:{source}:{norm}"
        if key in entity_map:
            return entity_map[key].get("person_id")

    return None







def _add_relationship_edges(
    G: nx.Graph,
    data: SBKData,
    valid_pids: set[str],
    owner_aliases: set[str] | None = None,
) -> tuple[int, int]:
    ""











    if not RELATIONSHIP_FACTS_FILE.exists():
        log.info("No relationship-facts.parquet found, skipping relationship edges")
        return 0, 0

    facts = data.relationship_facts
    if facts.empty:
        return 0, 0

    facts = facts.copy()

    missing = []
    for col in ("subject_person_id", "subject", "object_person_id", "object"):
        if col not in facts.columns:
            facts[col] = ""
            missing.append(col)
    if missing:
        log.warning(
            "relationship_facts: auto-filled missing cols %s — upstream producer should enforce schema",
            missing,
        )

    owner_aliases = owner_aliases or set()
    OWNER_PID = OWNER_GRAPH_ID


    OWN_NAMES_LOWER = set(OWNER_SPEAKER_LABELS)
    owner_mask = facts["subject"].str.lower().isin(OWN_NAMES_LOWER)
    facts.loc[owner_mask & (facts["subject_person_id"].str.len() == 0), "subject_person_id"] = (
        OWNER_PID
    )
    owner_obj = facts["object"].str.lower().isin(OWN_NAMES_LOWER)
    facts.loc[owner_obj & (facts["object_person_id"].str.len() == 0), "object_person_id"] = (
        OWNER_PID
    )


    rel_facts = facts[
        (facts["fact_type"] == "relationship_fact")
        & (_conf_ok(facts["confidence"]))
        & (facts["subject_person_id"].str.len() > 0)
        & (facts["object_person_id"].str.len() > 0)
    ]


    half_resolved = facts[
        (facts["fact_type"] == "relationship_fact")
        & (_conf_ok(facts["confidence"]))
        & (
            (
                (facts["subject_person_id"].str.len() > 0)
                & (facts["object_person_id"].str.len() == 0)
            )
            | (
                (facts["subject_person_id"].str.len() == 0)
                & (facts["object_person_id"].str.len() > 0)
            )
        )
    ]
    if len(half_resolved) > 0:
        log.info(f"Half-resolved relationship facts (shadow candidates): {len(half_resolved)}")

    new_edges = 0
    merged_edges = 0

    for _, fact in rel_facts.iterrows():
        subj_pid = fact["subject_person_id"]
        obj_pid = fact["object_person_id"]
        predicate = str(fact.get("predicate", "")).upper()


        if subj_pid in owner_aliases:
            subj_pid = OWNER_PID
        if obj_pid in owner_aliases:
            obj_pid = OWNER_PID

        if subj_pid == obj_pid:
            continue
        if subj_pid not in valid_pids or obj_pid not in valid_pids:
            continue



        confidence_factor = 0.5 if _conf_valore(fact["confidence"]) < 0.85 else 1.0
        weight = RELATIONSHIP_WEIGHTS.get(predicate, 1) * confidence_factor
        rel_key = f"rel_{predicate.lower()}"

        edge_key = tuple(sorted([subj_pid, obj_pid]))
        if G.has_edge(*edge_key):
            existing = G.edges[edge_key]
            existing[rel_key] = existing.get(rel_key, 0) + 1
            existing["rel_weight"] = existing.get("rel_weight", 0) + weight
            merged_edges += 1
        else:
            G.add_edge(
                *edge_key,
                email_msgs=0,
                email_threads=0,
                email_co_msgs=0,
                email_co_threads=0,
                cal_events=0,
                tactiq_meetings=0,
                slack_msgs=0,
                rel_weight=weight,
                weight=0,
                edge_type="interaction",
                **{rel_key: 1},
            )
            new_edges += 1

    return new_edges, merged_edges


def _add_deep_fact_edges(
    G: nx.Graph,
    valid_pids: set[str],
    entity_map: dict,
    contacts: pd.DataFrame,
) -> tuple[int, int]:
    ""






    if not DEEP_FACTS_FILE.exists():
        log.info("No deep-facts.parquet found, skipping deep-fact edges")
        return 0, 0

    try:
        deep_df = pd.read_parquet(DEEP_FACTS_FILE)
    except Exception as e:
        log.warning(f"Failed to load deep-facts.parquet: {e}")
        return 0, 0

    if deep_df.empty:
        return 0, 0


    name_to_pid: dict[str, str] = {}
    for _, row in contacts.iterrows():
        name = row.get("name")
        pid = row.get("person_id")
        if name and pid:
            name_to_pid[str(name).strip().lower()] = pid


    def _resolve_to_pid(name_str: str) -> str | None:
        if not name_str or not isinstance(name_str, str):
            return None
        norm = name_str.strip().lower()
        if norm in OWN_NAMES_NORMALIZED:
            return OWNER_GRAPH_ID
        if norm in name_to_pid:
            return name_to_pid[norm]

        for source in ("tactiq", "plaud", "slack", "linkedin", "iphone", "notion"):
            key = f"nameonly:{source}:{norm}"
            if key in entity_map:
                pid = entity_map[key].get("person_id")
                if pid:
                    return pid
        return None

    new_edges = 0
    merged_edges = 0

    for _, fact in deep_df.iterrows():
        subject = str(fact.get("subject", "")).strip()
        counterparty = str(fact.get("counterparty", "")).strip()
        category = str(fact.get("category", "")).strip().lower()

        subj_pid = _resolve_to_pid(subject)
        cpty_pid = _resolve_to_pid(counterparty)

        if not subj_pid or not cpty_pid:
            continue
        if subj_pid == cpty_pid:
            continue
        if subj_pid not in valid_pids or cpty_pid not in valid_pids:
            continue

        weight = DEEP_FACT_WEIGHTS.get(category, 2)
        deep_key = f"deep_{category}"

        edge_key = tuple(sorted([subj_pid, cpty_pid]))
        if G.has_edge(*edge_key):
            existing = G.edges[edge_key]
            existing[deep_key] = existing.get(deep_key, 0) + 1
            existing["deep_weight"] = existing.get("deep_weight", 0) + weight
            merged_edges += 1
        else:
            G.add_edge(
                *edge_key,
                email_msgs=0,
                email_threads=0,
                email_co_msgs=0,
                email_co_threads=0,
                cal_events=0,
                tactiq_meetings=0,
                slack_msgs=0,
                rel_weight=0,
                deep_weight=weight,
                weight=0,
                edge_type="interaction",
                **{deep_key: 1},
            )
            new_edges += 1

    log.info(f"Deep-fact edges: {new_edges} new, {merged_edges} merged")
    return new_edges, merged_edges


def _validate_birthday_value(value: str) -> str | None:
    ""




    import re as _re

    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    current_year = datetime.now(UTC).year


    m = _re.search(r"\b(\d{4})-\d{2}-\d{2}\b", value)
    if m:
        year = int(m.group(1))
        if year < 1900 or year > current_year:
            return None


    m = _re.search(r"\b(1[0-8]\d{2})\b", value)
    if m:
        year = int(m.group(1))
        if year < 1900:
            return None

    return value


def _enrich_person_nodes(
    G: nx.Graph,
    data: SBKData,
    valid_pids: set[str],
    owner_aliases: set[str] | None = None,
) -> int:
    ""










    facts = data.relationship_facts if RELATIONSHIP_FACTS_FILE.exists() else pd.DataFrame()

    if not facts.empty:
        facts = facts.copy()
        for col in ("subject_person_id", "subject", "object_person_id", "object"):
            if col not in facts.columns:
                facts[col] = ""

    owner_aliases = owner_aliases or set()
    OWNER_PID = OWNER_GRAPH_ID


    if not facts.empty:
        OWN_NAMES_LOWER = set(OWNER_SPEAKER_LABELS)
        owner_mask = facts["subject"].str.lower().isin(OWN_NAMES_LOWER)
        facts.loc[owner_mask & (facts["subject_person_id"].str.len() == 0), "subject_person_id"] = (
            OWNER_PID
        )


    person_details: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    if not facts.empty:

        detail_facts = facts[
            (facts["fact_type"] == "personal_detail")
            & (_conf_ok(facts["confidence"]))
            & (facts["subject_person_id"].str.len() > 0)
        ]

        for _, fact in detail_facts.iterrows():
            pid = fact["subject_person_id"]

            if pid in owner_aliases:
                pid = OWNER_PID
            if pid not in valid_pids:
                continue
            detail_type = str(fact.get("predicate", "")).lower()
            value = str(fact.get("object", "")).strip()
            if value:
                person_details[pid][detail_type].append(value)


        NEED_PREDICATE_MAP = {
            "WORKING_ON": "projects",
            "INTERESTED_IN": "interests",
            "STRUGGLING_WITH": "challenges",
            "LOOKING_FOR": "current_needs",
        }

        need_facts = facts[
            (facts["fact_type"] == "need")
            & (_conf_ok(facts["confidence"]))
            & (facts["subject_person_id"].str.len() > 0)
        ]

        for _, fact in need_facts.iterrows():
            pid = fact["subject_person_id"]

            if pid in owner_aliases:
                pid = OWNER_PID
            if pid not in valid_pids:
                continue
            value = str(fact.get("object", "")).strip()
            if value:
                predicate = str(fact.get("predicate", "")).upper()
                attr_key = NEED_PREDICATE_MAP.get(predicate, "current_needs")
                person_details[pid][attr_key].append(value)


        if not facts.empty:
            bg_facts = facts[
                (facts["fact_type"] == "personal_detail")
                & (_conf_ok(facts["confidence"]))
                & (facts["subject_person_id"].str.len() > 0)
                & (facts["predicate"].str.lower() == "background")
            ]
            for _, fact in bg_facts.iterrows():
                pid = fact["subject_person_id"]
                if pid in owner_aliases:
                    pid = OWNER_PID
                if pid not in valid_pids:
                    continue
                value = str(fact.get("object", "")).strip()
                if value:
                    person_details[pid]["background"].append(value)


        if not facts.empty:
            family_facts = facts[
                (facts["fact_type"] == "relationship_fact")
                & (_conf_ok(facts["confidence"]))
                & (facts["predicate"].str.upper() == "FAMILY_OF")
            ]
            for _, fact in family_facts.iterrows():
                subj_pid = fact["subject_person_id"]
                obj_pid = fact["object_person_id"]
                subj_name = str(fact.get("subject", "")).strip()
                obj_name = str(fact.get("object", "")).strip()

                if subj_pid in owner_aliases:
                    subj_pid = OWNER_PID
                if obj_pid in owner_aliases:
                    obj_pid = OWNER_PID

                if subj_pid and subj_pid in valid_pids and obj_name:
                    person_details[subj_pid]["family"].append(obj_name)
                if obj_pid and obj_pid in valid_pids and subj_name:
                    person_details[obj_pid]["family"].append(subj_name)


        if not facts.empty:
            invest_facts = facts[
                (facts["fact_type"] == "relationship_fact")
                & (_conf_ok(facts["confidence"]))
                & (facts["predicate"].str.upper() == "INVESTED_IN")
                & (facts["subject_person_id"].str.len() > 0)
            ]
            for _, fact in invest_facts.iterrows():
                pid = fact["subject_person_id"]
                if pid in owner_aliases:
                    pid = OWNER_PID
                if pid not in valid_pids:
                    continue
                value = str(fact.get("object", "")).strip()
                if value:
                    person_details[pid]["investments"].append(value)


    if DEEP_FACTS_FILE.exists():
        try:
            deep_df = pd.read_parquet(DEEP_FACTS_FILE)
            if not deep_df.empty:

                _name_to_pid: dict[str, str] = {}
                for _, c_row in data.contacts.iterrows():
                    c_name = c_row.get("name")
                    c_pid = c_row.get("person_id")
                    if c_name and c_pid:
                        _name_to_pid[str(c_name).strip().lower()] = c_pid

                def _resolve_deep_pid(name_str: str) -> str | None:
                    if not name_str or not isinstance(name_str, str):
                        return None
                    norm = name_str.strip().lower()
                    if norm in OWN_NAMES_NORMALIZED:
                        return OWNER_PID
                    return _name_to_pid.get(norm)

                for _, dfact in deep_df.iterrows():
                    category = str(dfact.get("category", "")).strip().lower()
                    subject = str(dfact.get("subject", "")).strip()
                    counterparty = str(dfact.get("counterparty", "")).strip()
                    obj = str(dfact.get("object", "")).strip()
                    amount = str(dfact.get("amount", "")).strip()
                    currency = str(dfact.get("currency", "")).strip()

                    amount_str = f" ({amount} {currency})" if amount and amount != "nan" else ""
                    fact_desc = f"{obj}{amount_str}"


                    for person_name in (subject, counterparty):
                        pid = _resolve_deep_pid(person_name)
                        if pid in owner_aliases:
                            pid = OWNER_PID
                        if not pid or pid not in valid_pids:
                            continue

                        if category in ("deal", "financial"):
                            person_details[pid]["financial_exposure"].append(fact_desc)
                        if category == "deal":
                            person_details[pid]["active_deals"].append(fact_desc)
                        if category == "commitment":
                            person_details[pid]["commitments"].append(fact_desc)
        except Exception as e:
            log.warning(f"Failed to enrich from deep-facts: {e}")


    enriched = 0
    for pid, details in person_details.items():
        if pid not in G:
            continue
        node = G.nodes[pid]
        if "birthday" in details:
            bday_val = _validate_birthday_value(details["birthday"][0])
            if bday_val:
                node["birthday"] = bday_val
        if "location" in details:
            node["location"] = details["location"][0]
        if "hobby" in details or "preference" in details:
            tags = list(set(details.get("hobby", []) + details.get("preference", [])))
            node["tags"] = tags[:15]
        if "current_needs" in details:
            node["current_needs"] = list(set(details["current_needs"]))[:15]
        if "projects" in details:
            node["projects"] = list(set(details["projects"]))[:15]
        if "background" in details:
            node["background"] = list(set(details["background"]))[:10]
        if "interests" in details:
            node["interests"] = list(set(details["interests"]))[:10]
        if "challenges" in details:
            node["challenges"] = list(set(details["challenges"]))[:5]
        if "family" in details:
            node["family"] = list(set(details["family"]))[:5]
        if "investments" in details:
            node["investments"] = list(set(details["investments"]))[:10]
        if "financial_exposure" in details:
            node["financial_exposure"] = list(set(details["financial_exposure"]))[:10]
        if "active_deals" in details:
            node["active_deals"] = len(set(details["active_deals"]))
        if "commitments" in details:
            node["commitments"] = len(set(details["commitments"]))
        enriched += 1


    annotations = data.person_annotations
    if annotations and isinstance(annotations, dict):
        for pid_or_name, ann_data in annotations.items():
            if not isinstance(ann_data, dict):
                continue

            target_pid = None
            if pid_or_name in G and pid_or_name in valid_pids:
                target_pid = pid_or_name
            else:

                for n, d in G.nodes(data=True):
                    if d.get("name", "").lower() == pid_or_name.lower() and n in valid_pids:
                        target_pid = n
                        break
            if not target_pid:
                continue

            node = G.nodes[target_pid]
            for key in ("birthday", "location"):
                if key in ann_data and key not in node:
                    val = ann_data[key]
                    if key == "birthday":
                        val = _validate_birthday_value(val)
                    if val:
                        node[key] = val
            if "tags" in ann_data and "tags" not in node:
                node["tags"] = ann_data["tags"][:10]

    return enriched







def _add_shadow_nodes(
    G: nx.Graph,
    data: SBKData,
    valid_pids: set[str],
    min_shadow_score: float = 10.0,
) -> tuple[int, int]:
    ""










    shadows = data.shadow_contacts
    if shadows.empty:
        log.info("No shadow contacts found, skipping shadow nodes")
        return 0, 0


    shadows = shadows[shadows["shadow_score"] >= min_shadow_score]
    if shadows.empty:
        log.info(f"No shadow contacts above score threshold {min_shadow_score}")
        return 0, 0

    new_nodes = 0
    new_edges = 0

    for _, row in shadows.iterrows():
        shadow_id = row["shadow_id"]


        if shadow_id in G:
            continue


        try:
            mentioned_by_pids = json.loads(row.get("mentioned_by_pids", "[]"))
        except (json.JSONDecodeError, TypeError):
            mentioned_by_pids = []


        try:
            facts_json = row.get("facts_json", "[]")
            meetings_json = row.get("meetings_json", "[]")
        except Exception:
            facts_json = "[]"
            meetings_json = "[]"


        G.add_node(
            shadow_id,
            name=row.get("display_name", row.get("canonical_name", "")),
            node_type="shadow_person",
            shadow_score=float(row.get("shadow_score", 0)),
            confidence_score=float(row.get("confidence_score", 0)),
            mention_count=int(row.get("mention_count", 0)),
            source_diversity=int(row.get("source_diversity", 0)),
            inferred_company=row.get("inferred_company", "") or "",
            inferred_role=row.get("inferred_role", "") or "",
            intro_via_pid=row.get("intro_via_pid", "") or "",
            intro_via_name=row.get("intro_via_name", "") or "",
            first_seen=row.get("first_seen", "") or "",
            last_seen=row.get("last_seen", "") or "",
            facts_json=facts_json,
            meetings_json=meetings_json,
            score=0,
            email="",
            organization=row.get("inferred_company", "") or "",
            domain="",
            is_internal=False,
            source_count=0,
        )
        valid_pids.add(shadow_id)
        new_nodes += 1


        for mentioner_pid in mentioned_by_pids:
            if mentioner_pid not in valid_pids:
                continue
            if mentioner_pid == shadow_id:
                continue

            edge_key = tuple(sorted([shadow_id, mentioner_pid]))
            if not G.has_edge(*edge_key):
                G.add_edge(
                    *edge_key,
                    email_msgs=0,
                    email_threads=0,
                    email_co_msgs=0,
                    email_co_threads=0,
                    cal_events=0,
                    tactiq_meetings=0,
                    slack_msgs=0,
                    rel_weight=0,
                    weight=2,
                    edge_type="mentioned_by",
                )
                new_edges += 1

    log.info(f"Shadow nodes: {new_nodes} added, {new_edges} MENTIONED_BY edges")
    return new_nodes, new_edges







def _enrich_org_nodes(G: nx.Graph, data: SBKData) -> int:
    ""







    try:
        attio_companies = data.attio_companies
    except Exception:
        log.debug("No attio_companies data available, skipping org enrichment")
        return 0

    if attio_companies.empty:
        return 0


    company_lookup: dict[str, dict] = {}
    for _, row in attio_companies.iterrows():
        name = str(row.get("company_name", "")).strip()
        if name:
            company_lookup[name.lower()] = row.to_dict()
        domain = str(row.get("domain", "")).strip().lower()
        if domain and domain not in ("nan", "none", ""):
            company_lookup[f"domain:{domain}"] = row.to_dict()

    enriched = 0
    attio_fields = (
        "description",
        "investor_type",
        "tier",
        "fund_size_aum",
        "thesis_fit",
        "stage_fit",
        "geographic_focus",
    )

    for org_id, attrs in G.nodes(data=True):
        if attrs.get("node_type") != "organization":
            continue
        org_name = attrs.get("name", "").strip().lower()
        if not org_name:
            continue

        match = company_lookup.get(org_name)
        if not match:
            continue

        for field in attio_fields:
            val = match.get(field)
            if val and str(val).lower() not in ("nan", "none", ""):
                attrs[field] = str(val)

        enriched += 1

    log.info(f"Enriched org nodes from Attio: {enriched}")
    return enriched







def build_graph(data: SBKData) -> nx.Graph:
    ""
    G = nx.Graph()


    today_cap = datetime.now(UTC).date().isoformat()

    contacts = data.contacts
    entity_map = data.entity_map


    email_to_pid: dict[str, str] = {}
    for email_key, entry in entity_map.items():
        if "@" in email_key:
            pid = entry.get("person_id")
            if pid:
                email_to_pid[email_key.lower()] = pid


    for _, row in contacts.iterrows():
        email = row.get("email")
        pid = row.get("person_id")
        if email and pid and "@" in str(email):
            email_to_pid[str(email).lower()] = pid

        all_emails = row.get("all_emails")
        if all_emails and pid:
            if isinstance(all_emails, str):
                for e in all_emails.split(","):
                    e = e.strip().lower()
                    if "@" in e:
                        email_to_pid[e] = pid
            elif isinstance(all_emails, list):
                for e in all_emails:
                    if isinstance(e, str) and "@" in e:
                        email_to_pid[e.strip().lower()] = pid


    OWNER_PID = OWNER_GRAPH_ID
    _owner_email = sorted(OWN_EMAILS)[0] if OWN_EMAILS else ""
    for own_email in OWN_EMAILS:
        email_to_pid[own_email.lower()] = OWNER_PID


    name_lookup = _build_name_lookup(contacts)


    valid_pids: set[str] = set()
    pid_to_attrs: dict[str, dict] = {}


    G.add_node(
        OWNER_PID,
        name=OWNER_LABEL,
        email=_owner_email,
        score=100.0,
        organization="",
        domain=_owner_email.split("@")[-1] if _owner_email else "",
        is_internal=True,
        source_count=16,
        node_type="person",
    )
    valid_pids.add(OWNER_PID)
    pid_to_attrs[OWNER_PID] = G.nodes[OWNER_PID]

    non_human_filtered = 0
    name_recovered = 0
    for _, row in contacts.iterrows():
        pid = row.get("person_id")
        if not pid:
            continue
        if row.get("is_automated"):
            continue
        score = row.get("score", 0)
        if not score or score <= 0:
            continue

        contact_name = str(row.get("name", "")).strip()
        contact_email = str(row.get("email", "")).strip()



        if is_non_human_node(contact_name, email=contact_email, score=float(score)):

            if "@" in contact_name and contact_email:
                recovered_name = extract_name_from_email(contact_email)
                if recovered_name:
                    contact_name = recovered_name
                    name_recovered += 1
                    log.debug(f"Recovered name from email: {contact_email!r} -> {recovered_name!r}")
                else:
                    non_human_filtered += 1
                    log.debug(f"Filtered email-as-name (no recovery): {contact_name!r} (pid={pid})")
                    continue
            else:
                non_human_filtered += 1
                log.debug(f"Filtered non-human entity: {contact_name!r} (pid={pid})")
                continue

        attrs = {
            "name": contact_name,
            "email": contact_email,
            "score": float(score),
            "organization": row.get("organization") or row.get("attio_company") or "",
            "domain": row.get("domain", ""),
            "is_internal": bool(row.get("is_internal", False)),
            "source_count": int(row.get("source_count", 0)),
            "node_type": "person",
        }
        G.add_node(pid, **attrs)
        valid_pids.add(pid)
        pid_to_attrs[pid] = attrs

    log.info(
        f"Person nodes: {len(valid_pids)} "
        f"(filtered {non_human_filtered} non-human, recovered {name_recovered} from email)"
    )


    email_direct_edges = 0
    email_co_edges = 0
    interactions = data.interactions


    has_relation_type = "relation_type" in interactions.columns

    for _, row in interactions.iterrows():
        from_email = str(row.get("from_email", "")).lower()
        to_email = str(row.get("to_email", "")).lower()

        from_pid = email_to_pid.get(from_email)
        to_pid = email_to_pid.get(to_email)

        if not from_pid or not to_pid:
            continue
        if from_pid == to_pid:
            continue
        if from_pid not in valid_pids or to_pid not in valid_pids:
            continue

        relation_type = str(row.get("relation_type", "direct")) if has_relation_type else "direct"
        is_co_recipient = relation_type == "co_recipient"

        msg_count = int(row.get("msg_count", 0))
        thread_count = int(row.get("thread_count", 0))
        first_date = str(row.get("first_date", ""))
        last_date = str(row.get("last_date", ""))


        msg_key = "email_co_msgs" if is_co_recipient else "email_msgs"
        thread_key = "email_co_threads" if is_co_recipient else "email_threads"

        edge_key = tuple(sorted([from_pid, to_pid]))
        if G.has_edge(*edge_key):
            existing = G.edges[edge_key]
            existing[msg_key] = existing.get(msg_key, 0) + msg_count
            existing[thread_key] = existing.get(thread_key, 0) + thread_count
            if first_date and first_date < existing.get("email_first", "9999"):
                existing["email_first"] = first_date
            if last_date and last_date > existing.get("email_last", ""):
                existing["email_last"] = last_date
        else:
            G.add_edge(
                *edge_key,
                email_msgs=msg_count if not is_co_recipient else 0,
                email_threads=thread_count if not is_co_recipient else 0,
                email_co_msgs=msg_count if is_co_recipient else 0,
                email_co_threads=thread_count if is_co_recipient else 0,
                email_first=first_date,
                email_last=last_date,
                cal_events=0,
                tactiq_meetings=0,
                weight=0,
                edge_type="interaction",
            )
            if is_co_recipient:
                email_co_edges += 1
            else:
                email_direct_edges += 1

    log.info(
        f"EMAILED edges: {email_direct_edges} direct + {email_co_edges} co-recipient"
        f" = {email_direct_edges + email_co_edges} new"
    )


    cal_edges_new = 0
    cal_edges_merged = 0
    cal_interactions = data.calendar_interactions

    for _, row in cal_interactions.iterrows():
        from_email = str(row.get("from_email", "")).lower()
        to_email = str(row.get("to_email", "")).lower()

        from_pid = email_to_pid.get(from_email)
        to_pid = email_to_pid.get(to_email)

        if not from_pid or not to_pid:
            continue
        if from_pid == to_pid:
            continue
        if from_pid not in valid_pids or to_pid not in valid_pids:
            continue

        event_count = int(row.get("event_count", 0))
        first_date = str(row.get("first_date", ""))
        last_date = str(row.get("last_date", ""))


        if last_date > today_cap:
            last_date = today_cap

        edge_key = tuple(sorted([from_pid, to_pid]))
        if G.has_edge(*edge_key):
            existing = G.edges[edge_key]
            existing["cal_events"] = existing.get("cal_events", 0) + event_count
            if first_date and first_date < existing.get("cal_first", "9999"):
                existing["cal_first"] = first_date
            if last_date and last_date > existing.get("cal_last", ""):
                existing["cal_last"] = last_date
            cal_edges_merged += 1
        else:
            G.add_edge(
                *edge_key,
                email_msgs=0,
                email_threads=0,
                cal_events=event_count,
                cal_first=first_date,
                cal_last=last_date,
                tactiq_meetings=0,
                weight=0,
                edge_type="interaction",
            )
            cal_edges_new += 1

    log.info(f"Calendar edges: {cal_edges_new} new, {cal_edges_merged} merged")


    tactiq_edges_new = 0
    tactiq_edges_merged = 0

    try:
        tactiq = data.tactiq_meetings
        for _, meeting in tactiq.iterrows():

            raw_speakers = meeting.get("speakers", "")
            raw_participants = meeting.get("participants", "")
            names = _parse_tactiq_names(raw_speakers) or _parse_tactiq_names(raw_participants)


            pids_in_meeting = set()
            for name in names:
                pid = _resolve_name_to_pid(name, name_lookup, entity_map)
                if pid and pid in valid_pids:
                    pids_in_meeting.add(pid)


            for pid_a, pid_b in combinations(sorted(pids_in_meeting), 2):
                edge_key = (pid_a, pid_b)
                if G.has_edge(*edge_key):
                    G.edges[edge_key]["tactiq_meetings"] = (
                        G.edges[edge_key].get("tactiq_meetings", 0) + 1
                    )
                    tactiq_edges_merged += 1
                else:
                    G.add_edge(
                        *edge_key,
                        email_msgs=0,
                        email_threads=0,
                        cal_events=0,
                        tactiq_meetings=1,
                        weight=0,
                        edge_type="interaction",
                    )
                    tactiq_edges_new += 1
    except Exception as e:
        log.warning(f"Tactiq processing failed: {e}")

    log.info(f"Tactiq edges: {tactiq_edges_new} new, {tactiq_edges_merged} merged")


    slack_edges_new = 0
    slack_edges_merged = 0

    try:
        slack_interactions = data.slack_interactions


        slack_pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for _, sl_row in slack_interactions.iterrows():
            from_name = str(sl_row.get("from_user", "")).strip()
            to_name = str(sl_row.get("to_user", "")).strip()
            if not from_name or not to_name or from_name == to_name:
                continue

            from_norm = from_name.lower()
            to_norm = to_name.lower()

            if from_norm in OWN_NAMES_NORMALIZED:
                from_pid = OWNER_PID
            else:
                from_pid = _resolve_name_to_pid(from_name, name_lookup, entity_map)

            if to_norm in OWN_NAMES_NORMALIZED:
                to_pid = OWNER_PID
            else:
                to_pid = _resolve_name_to_pid(to_name, name_lookup, entity_map)

            if not from_pid or not to_pid or from_pid == to_pid:
                continue

            pair_key = tuple(sorted([from_pid, to_pid]))
            slack_pair_counts[pair_key] += 1

        for (pid_a, pid_b), msg_count in slack_pair_counts.items():
            if pid_a not in valid_pids or pid_b not in valid_pids:
                continue

            edge_key = (pid_a, pid_b)
            if G.has_edge(*edge_key):
                G.edges[edge_key]["slack_msgs"] = G.edges[edge_key].get("slack_msgs", 0) + msg_count
                slack_edges_merged += 1
            else:
                G.add_edge(
                    *edge_key,
                    email_msgs=0,
                    email_threads=0,
                    email_co_msgs=0,
                    email_co_threads=0,
                    cal_events=0,
                    tactiq_meetings=0,
                    slack_msgs=msg_count,
                    weight=0,
                    edge_type="interaction",
                )
                slack_edges_new += 1

    except Exception as e:
        log.warning(f"Slack processing failed: {e}")

    log.info(f"SLACK edges: {slack_edges_new} new, {slack_edges_merged} merged")


    org_nodes = 0
    works_at_edges = 0
    org_set: set[str] = set()

    for pid in valid_pids:
        attrs = pid_to_attrs.get(pid, {})
        org_raw = attrs.get("organization", "")
        org = str(org_raw).strip() if org_raw and str(org_raw) != "nan" else ""
        if not org:
            continue


        org = ORG_CANONICAL.get(org, org)

        org_id = f"org:{org.lower()}"
        if org_id not in org_set:
            G.add_node(org_id, name=org, node_type="organization")
            org_set.add(org_id)
            org_nodes += 1

        if not G.has_edge(pid, org_id):
            G.add_edge(pid, org_id, edge_type="works_at", weight=1)
            works_at_edges += 1

    log.info(f"Organization nodes: {org_nodes}, WORKS_AT edges: {works_at_edges}")





    owner_aliases: set[str] = set()
    for em_key, em_entry in entity_map.items():
        em_pid = em_entry.get("person_id", "")
        if not em_pid or em_pid == OWNER_PID:
            continue

        if "@" in em_key and em_key.lower() in OWN_EMAILS:
            owner_aliases.add(em_pid)

        if em_key.startswith("nameonly:") and em_key.split(":")[-1] in OWN_NAMES_NORMALIZED:
            owner_aliases.add(em_pid)
    if owner_aliases:
        log.info(f"Owner aliases found in entity-map: {owner_aliases}")


    rel_edges_new, rel_edges_merged = _add_relationship_edges(
        G, data, valid_pids, owner_aliases=owner_aliases
    )
    log.info(f"Relationship edges: {rel_edges_new} new, {rel_edges_merged} merged")


    deep_edges_new, deep_edges_merged = _add_deep_fact_edges(G, valid_pids, entity_map, contacts)
    log.info(f"Deep-fact edges: {deep_edges_new} new, {deep_edges_merged} merged")


    enriched_count = _enrich_person_nodes(G, data, valid_pids, owner_aliases=owner_aliases)
    log.info(f"Enriched person nodes: {enriched_count}")


    shadow_nodes, shadow_edges = _add_shadow_nodes(G, data, valid_pids)


    org_enriched = _enrich_org_nodes(G, data)
    log.info(f"Enriched org nodes: {org_enriched}")





    for u, v, data_edge in G.edges(data=True):
        if data_edge.get("edge_type") in ("works_at", "mentioned_by"):
            continue
        email_w = data_edge.get("email_msgs", 0)
        email_co_w = data_edge.get("email_co_msgs", 0) * 0.3
        cal_w = data_edge.get("cal_events", 0) * 3
        tactiq_w = data_edge.get("tactiq_meetings", 0) * 5
        slack_w = data_edge.get("slack_msgs", 0) * 0.5
        rel_w = data_edge.get("rel_weight", 0)
        deep_w = data_edge.get("deep_weight", 0)
        data_edge["weight"] = email_w + email_co_w + cal_w + tactiq_w + slack_w + rel_w + deep_w

    log.info(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    return G







def run_leiden_communities(G: nx.Graph) -> dict[str, int]:
    ""



    try:
        import igraph as ig
        import leidenalg
    except ImportError:
        log.warning(
            "igraph/leidenalg not installed. Install with: "
            "pip install python-igraph leidenalg. "
            "Falling back to NetworkX greedy modularity."
        )
        return _fallback_communities(G)


    person_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "person"]
    person_subgraph = G.subgraph(person_nodes).copy()


    isolates = list(nx.isolates(person_subgraph))
    person_subgraph.remove_nodes_from(isolates)

    if person_subgraph.number_of_nodes() == 0:
        log.warning("No connected person nodes for community detection")
        return {}


    node_list = list(person_subgraph.nodes())
    node_idx = {n: i for i, n in enumerate(node_list)}

    ig_edges = []
    ig_weights = []
    for u, v, d in person_subgraph.edges(data=True):
        if d.get("edge_type") == "works_at":
            continue
        ig_edges.append((node_idx[u], node_idx[v]))
        ig_weights.append(max(d.get("weight", 1), 1))

    ig_graph = ig.Graph(n=len(node_list), edges=ig_edges, directed=False)
    ig_graph.es["weight"] = ig_weights


    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.RBConfigurationVertexPartition,
        weights="weight",
        resolution_parameter=0.8,
    )

    communities: dict[str, int] = {}
    for comm_id, members in enumerate(partition):
        for idx in members:
            communities[node_list[idx]] = comm_id


    for node in isolates:
        communities[node] = -1

    log.info(
        f"Leiden: {len(partition)} communities, "
        f"modularity={partition.modularity:.3f}, "
        f"{len(isolates)} isolated"
    )

    return communities


def _fallback_communities(G: nx.Graph) -> dict[str, int]:
    ""
    person_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "person"]
    person_subgraph = G.subgraph(person_nodes).copy()


    org_edges = [
        (u, v) for u, v, d in person_subgraph.edges(data=True) if d.get("edge_type") == "works_at"
    ]
    person_subgraph.remove_edges_from(org_edges)

    isolates = list(nx.isolates(person_subgraph))
    person_subgraph.remove_nodes_from(isolates)

    if person_subgraph.number_of_nodes() == 0:
        return {}

    from networkx.algorithms.community import greedy_modularity_communities

    comm_sets = greedy_modularity_communities(person_subgraph, weight="weight", resolution=0.8)
    communities: dict[str, int] = {}
    for comm_id, members in enumerate(comm_sets):
        for node in members:
            communities[node] = comm_id

    for node in isolates:
        communities[node] = -1

    log.info(
        f"Fallback communities: {len(set(c for c in communities.values() if c >= 0))} "
        f"communities, {len(isolates)} isolated"
    )
    return communities







def compute_centrality(G: nx.Graph) -> dict[str, dict]:
    ""



    person_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "person"]
    person_subgraph = G.subgraph(person_nodes).copy()


    org_edges = [
        (u, v) for u, v, d in person_subgraph.edges(data=True) if d.get("edge_type") == "works_at"
    ]
    person_subgraph.remove_edges_from(org_edges)

    if person_subgraph.number_of_nodes() == 0:
        return {}


    log.debug("Computing PageRank...")
    pagerank = nx.pagerank(person_subgraph, weight="weight", max_iter=200)


    log.debug("Computing betweenness centrality...")
    betweenness = nx.betweenness_centrality(person_subgraph, weight="weight")


    log.debug("Computing eigenvector centrality...")
    try:
        eigenvector = nx.eigenvector_centrality(
            person_subgraph, weight="weight", max_iter=500, tol=1e-4
        )
    except nx.PowerIterationFailedConvergence:
        log.warning("Eigenvector centrality failed to converge, using degree centrality")
        eigenvector = nx.degree_centrality(person_subgraph)


    def _normalize(values: dict[str, float]) -> dict[str, float]:
        if not values:
            return values
        max_v = max(values.values())
        if max_v == 0:
            return dict.fromkeys(values, 0.0)
        return {k: v / max_v for k, v in values.items()}

    pr_norm = _normalize(pagerank)
    bt_norm = _normalize(betweenness)
    ev_norm = _normalize(eigenvector)


    centrality: dict[str, dict] = {}
    for pid in person_nodes:
        pr = pr_norm.get(pid, 0.0)
        bt = bt_norm.get(pid, 0.0)
        ev = ev_norm.get(pid, 0.0)
        composite = 0.4 * pr + 0.3 * bt + 0.3 * ev

        centrality[pid] = {
            "pagerank": round(pr, 6),
            "betweenness": round(bt, 6),
            "eigenvector": round(ev, 6),
            "composite": round(composite, 6),
        }

    log.info(f"Centrality computed for {len(centrality)} nodes")


    top = sorted(centrality.items(), key=lambda x: x[1]["composite"], reverse=True)[:10]
    for pid, scores in top:
        name = G.nodes[pid].get("name", pid)
        log.info(f"  {name}: composite={scores['composite']:.4f}")

    return centrality







def find_warm_intros(
    G: nx.Graph,
    source: str,
    target: str,
    top_k: int = 5,
    email_to_pid: dict[str, str] | None = None,
) -> list[dict]:
    ""










    if email_to_pid is None:
        email_to_pid = {}


    def _resolve(identifier: str) -> str | None:
        if identifier in G:
            return identifier
        lower = identifier.lower()
        if lower in email_to_pid and email_to_pid[lower] in G:
            return email_to_pid[lower]

        for n, d in G.nodes(data=True):
            if d.get("name", "").lower() == lower:
                return n
        return None

    src_pid = _resolve(source)
    tgt_pid = _resolve(target)

    if not src_pid:
        log.error(f"Source not found in graph: {source}")
        return []
    if not tgt_pid:
        log.error(f"Target not found in graph: {target}")
        return []


    person_nodes = [
        n for n, d in G.nodes(data=True) if d.get("node_type") in ("person", "shadow_person")
    ]
    person_subgraph = G.subgraph(person_nodes).copy()

    if src_pid not in person_subgraph or tgt_pid not in person_subgraph:
        log.error("Source or target not in person subgraph")
        return []


    max_score = max(
        (d.get("score", 1) for _, d in person_subgraph.nodes(data=True)),
        default=1,
    )
    if max_score == 0:
        max_score = 1


    path_graph = person_subgraph.copy()
    for u, v, d in path_graph.edges(data=True):
        if d.get("edge_type") == "works_at":
            d["path_weight"] = 100
            continue
        if d.get("edge_type") == "mentioned_by":
            d["path_weight"] = 50
            continue

        u_score = path_graph.nodes[u].get("score", 0) / max_score
        v_score = path_graph.nodes[v].get("score", 0) / max_score
        edge_w = d.get("weight", 1)
        trust = ((u_score + v_score) / 2) * (1 + min(edge_w, 100) / 100)
        d["path_weight"] = 1.0 / max(trust, 0.01)


    results = []
    try:

        path = nx.dijkstra_path(path_graph, src_pid, tgt_pid, weight="path_weight")
        path_cost = nx.dijkstra_path_length(path_graph, src_pid, tgt_pid, weight="path_weight")
        results.append(_format_path(G, path, path_cost))


        if top_k > 1:
            try:
                path_iter = nx.shortest_simple_paths(
                    path_graph, src_pid, tgt_pid, weight="path_weight"
                )
                count = 0
                for p in path_iter:
                    count += 1
                    if count == 1:
                        continue
                    if count > top_k:
                        break
                    cost = sum(
                        path_graph.edges[p[i], p[i + 1]].get("path_weight", 1)
                        for i in range(len(p) - 1)
                    )
                    results.append(_format_path(G, p, cost))
            except (nx.NetworkXNoPath, StopIteration):
                pass

    except nx.NetworkXNoPath:
        log.warning(f"No path between {source} and {target}")

    return results


def _format_path(G: nx.Graph, path: list[str], cost: float) -> dict:
    ""
    nodes = []
    for pid in path:
        data = G.nodes.get(pid, {})
        nodes.append(
            {
                "person_id": pid,
                "name": data.get("name", pid),
                "email": data.get("email", ""),
                "score": data.get("score", 0),
                "organization": data.get("organization", ""),
            }
        )


    edges = []
    for i in range(len(path) - 1):
        edge_data = G.edges.get((path[i], path[i + 1]), {})
        if not edge_data:
            edge_data = G.edges.get((path[i + 1], path[i]), {})
        edges.append(
            {
                "from": G.nodes.get(path[i], {}).get("name", path[i]),
                "to": G.nodes.get(path[i + 1], {}).get("name", path[i + 1]),
                "email_msgs": edge_data.get("email_msgs", 0),
                "email_co_msgs": edge_data.get("email_co_msgs", 0),
                "cal_events": edge_data.get("cal_events", 0),
                "tactiq_meetings": edge_data.get("tactiq_meetings", 0),
                "slack_msgs": edge_data.get("slack_msgs", 0),
            }
        )

    return {
        "path_length": len(path) - 1,
        "path_cost": round(cost, 4),
        "nodes": nodes,
        "edges": edges,
        "intermediaries": [n["name"] for n in nodes[1:-1]],
    }







def export_network_graph(
    G: nx.Graph,
    communities: dict[str, int],
    centrality: dict[str, dict],
) -> None:
    ""

    person_nodes = []
    shadow_nodes = []
    for pid, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type", "")
        if node_type == "shadow_person":
            shadow_nodes.append(
                {
                    "person_id": pid,
                    "name": attrs.get("name", ""),
                    "node_type": "shadow_person",
                    "shadow_score": attrs.get("shadow_score", 0),
                    "confidence_score": attrs.get("confidence_score", 0),
                    "mention_count": attrs.get("mention_count", 0),
                    "source_diversity": attrs.get("source_diversity", 0),
                    "inferred_company": attrs.get("inferred_company", ""),
                    "inferred_role": attrs.get("inferred_role", ""),
                    "intro_via_pid": attrs.get("intro_via_pid", ""),
                    "intro_via_name": attrs.get("intro_via_name", ""),
                    "first_seen": attrs.get("first_seen", ""),
                    "last_seen": attrs.get("last_seen", ""),
                    "facts_json": attrs.get("facts_json", "[]"),
                    "meetings_json": attrs.get("meetings_json", "[]"),
                }
            )
            continue
        if node_type != "person":
            continue
        node = {
            "person_id": pid,
            "email": attrs.get("email", ""),
            "name": attrs.get("name", ""),
            "domain": attrs.get("domain", ""),
            "score": attrs.get("score", 0),
            "source_count": attrs.get("source_count", 0),
            "organization": attrs.get("organization", ""),
            "is_internal": attrs.get("is_internal", False),
            "community": communities.get(pid, -1),
        }

        if pid in centrality:
            node["centrality"] = centrality[pid]

        for attr_key in (
            "birthday",
            "location",
            "tags",
            "current_needs",
            "projects",
            "background",
            "interests",
            "challenges",
            "family",
            "investments",
            "financial_exposure",
            "active_deals",
            "commitments",
        ):
            val = attrs.get(attr_key)
            if val:
                node[attr_key] = val

        person_nodes.append(node)

    person_nodes.sort(key=lambda x: x["score"], reverse=True)
    shadow_nodes.sort(key=lambda x: x["shadow_score"], reverse=True)


    shadow_pids = {n["person_id"] for n in shadow_nodes}
    person_pids = {n["person_id"] for n in person_nodes}
    all_pids = person_pids | shadow_pids
    edges = []
    shadow_edges = []
    for u, v, data_edge in G.edges(data=True):
        if data_edge.get("edge_type") == "works_at":
            continue
        if u not in all_pids or v not in all_pids:
            continue

        edge = {
            "source": u,
            "target": v,
            "weight": data_edge.get("weight", 0),
            "email_msgs": data_edge.get("email_msgs", 0),
            "email_threads": data_edge.get("email_threads", 0),
            "email_co_msgs": data_edge.get("email_co_msgs", 0),
            "email_co_threads": data_edge.get("email_co_threads", 0),
            "cal_events": data_edge.get("cal_events", 0),
            "tactiq_meetings": data_edge.get("tactiq_meetings", 0),
            "slack_msgs": data_edge.get("slack_msgs", 0),
        }

        rel_weight = data_edge.get("rel_weight", 0)
        if rel_weight > 0:
            edge["rel_weight"] = rel_weight
            for key, val in data_edge.items():
                if key.startswith("rel_") and key != "rel_weight" and val:
                    edge[key] = val


        deep_weight = data_edge.get("deep_weight", 0)
        if deep_weight > 0:
            edge["deep_weight"] = deep_weight
            for key, val in data_edge.items():
                if key.startswith("deep_") and key != "deep_weight" and val:
                    edge[key] = val


        if data_edge.get("edge_type") == "mentioned_by":
            edge["edge_type"] = "mentioned_by"
            shadow_edges.append(edge)
        else:
            edges.append(edge)

    edges.sort(key=lambda x: x["weight"], reverse=True)


    org_nodes = []
    org_edges = []
    for org_id, attrs in G.nodes(data=True):
        if attrs.get("node_type") != "organization":
            continue

        members = []
        for u, v, d in G.edges(org_id, data=True):
            if d.get("edge_type") != "works_at":
                continue
            neighbor = v if u == org_id else u
            if neighbor in person_pids:

                node_data = G.nodes.get(neighbor, {})
                members.append(
                    {
                        "person_id": neighbor,
                        "name": node_data.get("name", neighbor),
                        "score": node_data.get("score", 0),
                    }
                )
        if not members:
            continue
        members.sort(key=lambda x: x["score"], reverse=True)
        org_node = {
            "org_id": org_id,
            "name": attrs.get("name", org_id),
            "node_type": "organization",
            "member_count": len(members),
            "top_members": [m["name"] for m in members[:5]],
        }

        for attio_key in (
            "description",
            "investor_type",
            "tier",
            "fund_size_aum",
            "thesis_fit",
            "stage_fit",
            "geographic_focus",
        ):
            val = attrs.get(attio_key)
            if val:
                org_node[attio_key] = val
        org_nodes.append(org_node)
        for m in members:
            org_edges.append({"source": m["person_id"], "target": org_id})

    org_nodes.sort(key=lambda x: x["member_count"], reverse=True)

    output = {
        "generated": datetime.now(UTC).isoformat(),
        "graph_version": "l3-v3",
        "total_nodes": len(person_nodes),
        "total_edges": len(edges),
        "total_org_nodes": len(org_nodes),
        "total_org_edges": len(org_edges),
        "total_shadow_nodes": len(shadow_nodes),
        "total_shadow_edges": len(shadow_edges),
        "communities": len(set(c for c in communities.values() if c >= 0)),
        "nodes": person_nodes,
        "edges": edges,
        "org_nodes": org_nodes,
        "org_edges": org_edges,
        "shadow_nodes": shadow_nodes,
        "shadow_edges": shadow_edges,
    }

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    NETWORK_GRAPH_FILE.write_text(
        json.dumps(output, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(
        f"Exported network-graph.json: {len(person_nodes)} person nodes, "
        f"{len(edges)} edges, {len(org_nodes)} org nodes, {len(org_edges)} org edges, "
        f"{len(shadow_nodes)} shadow nodes, {len(shadow_edges)} shadow edges"
    )


def save_graph(G: nx.Graph) -> None:
    ""
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_FILE, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    log.info(f"Graph saved: {GRAPH_FILE}")


def _generate_community_label(members: list[dict], top_orgs: list[str], comm_id: int) -> str:
    ""






    if comm_id < 0:
        return "Isolati"


    org_counts: dict[str, int] = {}
    members_with_org = 0
    for m in members:
        org = m.get("organization", "")
        if org and str(org).lower() not in ("nan", "none", ""):
            members_with_org += 1
            org_counts[org] = org_counts.get(org, 0) + 1

    if org_counts and members_with_org >= 2:
        dominant_org, dominant_count = max(org_counts.items(), key=lambda x: x[1])
        if dominant_count >= members_with_org * 0.5:
            return f"Team {dominant_org}"


    person_names = [m["name"] for m in members[:3] if m.get("name")]
    if person_names:
        return ", ".join(person_names)

    return f"Community {comm_id}"


def save_communities(communities: dict[str, int], G: nx.Graph) -> None:
    ""
    by_comm: dict[int, list[dict]] = defaultdict(list)
    for pid, comm_id in communities.items():
        node_data = G.nodes.get(pid, {})
        by_comm[comm_id].append(
            {
                "person_id": pid,
                "name": node_data.get("name", pid),
                "score": node_data.get("score", 0),
                "organization": node_data.get("organization", ""),
            }
        )


    output = {}
    for comm_id in sorted(by_comm.keys()):
        members = sorted(by_comm[comm_id], key=lambda x: x["score"], reverse=True)
        top_members = [m["name"] for m in members[:5]]
        top_orgs = list(
            {
                m["organization"]
                for m in members
                if m["organization"] and str(m["organization"]).lower() not in ("nan", "none")
            }
        )[:5]


        label = _generate_community_label(members, top_orgs, comm_id)

        output[str(comm_id)] = {
            "size": len(members),
            "label": label,
            "top_members": top_members,
            "top_orgs": top_orgs,
            "members": members,
        }

    result = {
        "generated": datetime.now(UTC).isoformat(),
        "total_communities": len([k for k in output if k != "-1"]),
        "total_assigned": sum(1 for v in communities.values() if v >= 0),
        "total_isolated": sum(1 for v in communities.values() if v < 0),
        "communities": output,
    }

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    COMMUNITIES_FILE.write_text(
        json.dumps(result, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(f"Communities saved: {COMMUNITIES_FILE}")


def save_centrality(centrality: dict[str, dict], G: nx.Graph) -> None:
    ""
    ranked = sorted(centrality.items(), key=lambda x: x[1]["composite"], reverse=True)

    entries = []
    for rank, (pid, scores) in enumerate(ranked, 1):
        node_data = G.nodes.get(pid, {})
        entries.append(
            {
                "rank": rank,
                "person_id": pid,
                "name": node_data.get("name", pid),
                "email": node_data.get("email", ""),
                "organization": node_data.get("organization", ""),
                "score": node_data.get("score", 0),
                **scores,
            }
        )

    result = {
        "generated": datetime.now(UTC).isoformat(),
        "total": len(entries),
        "top_20": entries[:20],
        "all": entries,
    }

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    CENTRALITY_FILE.write_text(
        json.dumps(result, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(f"Centrality saved: {CENTRALITY_FILE}")







def show_stats(G: nx.Graph, communities: dict, centrality: dict) -> None:
    ""
    person_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "person"]
    org_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "organization"]

    interaction_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("edge_type") != "works_at"
    ]
    works_at_edges = [
        (u, v, d) for u, v, d in G.edges(data=True) if d.get("edge_type") == "works_at"
    ]

    log.info("=== SBK Knowledge Graph Stats ===")
    log.info(f"Person nodes:       {len(person_nodes)}")
    log.info(f"Organization nodes: {len(org_nodes)}")
    log.info(f"Interaction edges:  {len(interaction_edges)}")
    log.info(f"WORKS_AT edges:     {len(works_at_edges)}")
    log.info(f"Total nodes:        {G.number_of_nodes()}")
    log.info(f"Total edges:        {G.number_of_edges()}")

    if interaction_edges:
        weights = [d.get("weight", 0) for _, _, d in interaction_edges]
        log.info("Edge weight stats:")
        log.info(f"  Max:    {max(weights)}")
        log.info(f"  Mean:   {sum(weights) / len(weights):.1f}")
        log.info(f"  Median: {sorted(weights)[len(weights) // 2]}")


        email_direct = sum(1 for _, _, d in interaction_edges if d.get("email_msgs", 0) > 0)
        email_co = sum(1 for _, _, d in interaction_edges if d.get("email_co_msgs", 0) > 0)
        cal_only = sum(1 for _, _, d in interaction_edges if d.get("cal_events", 0) > 0)
        tactiq_only = sum(1 for _, _, d in interaction_edges if d.get("tactiq_meetings", 0) > 0)
        slack_only = sum(1 for _, _, d in interaction_edges if d.get("slack_msgs", 0) > 0)
        rel_only = sum(1 for _, _, d in interaction_edges if d.get("rel_weight", 0) > 0)
        deep_only = sum(1 for _, _, d in interaction_edges if d.get("deep_weight", 0) > 0)
        log.info(f"Edges with email direct:      {email_direct}")
        log.info(f"Edges with email co-recipient: {email_co}")
        log.info(f"Edges with cal data:           {cal_only}")
        log.info(f"Edges with tactiq data:        {tactiq_only}")
        log.info(f"Edges with slack data:         {slack_only}")
        log.info(f"Edges with relationship data:  {rel_only}")
        log.info(f"Edges with deep-fact data:     {deep_only}")


        if rel_only > 0:
            rel_type_counts: dict[str, int] = defaultdict(int)
            for _, _, d in interaction_edges:
                for key, val in d.items():
                    if key.startswith("rel_") and key != "rel_weight" and val:
                        rel_type_counts[key] += int(val)
            if rel_type_counts:
                log.info("Relationship type breakdown:")
                for rtype, count in sorted(rel_type_counts.items(), key=lambda x: -x[1]):
                    log.info(f"  {rtype}: {count}")


    with_birthday = sum(1 for n in person_nodes if G.nodes[n].get("birthday"))
    with_location = sum(1 for n in person_nodes if G.nodes[n].get("location"))
    with_tags = sum(1 for n in person_nodes if G.nodes[n].get("tags"))
    with_needs = sum(1 for n in person_nodes if G.nodes[n].get("current_needs"))
    if any([with_birthday, with_location, with_tags, with_needs]):
        log.info(f"Nodes with birthday:       {with_birthday}")
        log.info(f"Nodes with location:       {with_location}")
        log.info(f"Nodes with tags:           {with_tags}")
        log.info(f"Nodes with current_needs:  {with_needs}")


    person_subgraph = G.subgraph(person_nodes)
    connected = nx.is_connected(person_subgraph) if person_subgraph.number_of_nodes() > 0 else False
    isolates = list(nx.isolates(person_subgraph))
    log.info(f"Connected:    {connected}")
    log.info(f"Isolated:     {len(isolates)}")
    if not connected and person_subgraph.number_of_nodes() > 0:
        components = list(nx.connected_components(person_subgraph))
        log.info(f"Components:   {len(components)}")
        sizes = sorted([len(c) for c in components], reverse=True)
        log.info(f"Largest:      {sizes[0] if sizes else 0}")
        if len(sizes) > 1:
            log.info(f"Top 5 sizes:  {sizes[:5]}")

    if communities:
        n_comm = len(set(c for c in communities.values() if c >= 0))
        log.info(f"Communities:  {n_comm}")

    if centrality:
        top5 = sorted(centrality.items(), key=lambda x: x[1]["composite"], reverse=True)[:5]
        log.info("Top 5 by centrality:")
        for pid, scores in top5:
            name = G.nodes.get(pid, {}).get("name", pid)
            log.info(f"  {name}: {scores['composite']:.4f}")


def show_communities(communities: dict[str, int], G: nx.Graph) -> None:
    ""
    by_comm: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for pid, comm_id in communities.items():
        score = G.nodes.get(pid, {}).get("score", 0)
        name = G.nodes.get(pid, {}).get("name", pid)
        by_comm[comm_id].append((name, score))

    log.info("=== Communities ===")
    for comm_id in sorted(by_comm.keys()):
        if comm_id < 0:
            continue
        members = sorted(by_comm[comm_id], key=lambda x: x[1], reverse=True)
        orgs = set()
        for pid, _ in [(p, s) for p, s in by_comm[comm_id]]:
            for node_id, data in G.nodes(data=True):
                if data.get("name") == pid:
                    org = data.get("organization", "")
                    if org:
                        orgs.add(org)
                    break

        log.info(f"Community {comm_id} ({len(members)} members):")
        for name, score in members[:8]:
            log.info(f"  {name} (score: {score:.1f})")
        if len(members) > 8:
            log.info(f"  ... and {len(members) - 8} more")

    isolated = by_comm.get(-1, [])
    if isolated:
        log.info(f"Isolated: {len(isolated)} nodes (no interaction edges)")







def main():
    parser = argparse.ArgumentParser(
        description="SBK Knowledge Graph Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="Build graph but don't save")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    parser.add_argument("--warm-intro", type=str, help="Find warm intro path to target email")
    parser.add_argument("--community", action="store_true", help="Show community details")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-graph")


    if not args.dry_run:
        if not acquire_pid_lock("l3-graph", logger=log):


            log.warning("l3-graph: lock tenuto da un'altra istanza, exit 75")
            sys.exit(75)

    try:
        _main_inner(args)
    finally:
        if not args.dry_run:
            release_pid_lock("l3-graph")


def _main_inner(args):
    if args.incremental:
        from sbk_config import ENRICHED_DIR, check_inputs_changed, mark_last_run
        from sbk_config import RELATIONSHIP_FACTS_FILE as _REL_FACTS

        inputs = [
            ENRICHED_DIR / "contacts-merged.parquet",
            ENRICHED_DIR / "interactions.parquet",
            _REL_FACTS,
        ]
        if not check_inputs_changed("l3-graph", inputs):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("l3-graph")
            return


    log.info("Loading SBK data...")
    data = SBKData()


    log.info("Building knowledge graph...")
    G = build_graph(data)


    log.info("Running community detection...")
    communities = run_leiden_communities(G)


    for pid, comm_id in communities.items():
        if pid in G:
            G.nodes[pid]["community"] = comm_id


    log.info("Computing centrality metrics...")
    centrality = compute_centrality(G)


    for pid, scores in centrality.items():
        if pid in G:
            G.nodes[pid]["centrality"] = scores


    if args.warm_intro:

        e2p: dict[str, str] = {}
        for n, d in G.nodes(data=True):
            email = d.get("email", "")
            if email and "@" in email:
                e2p[email.lower()] = n


        source_pid = None
        for own_email in OWN_EMAILS:
            if own_email.lower() in e2p:
                source_pid = e2p[own_email.lower()]
                break

        if not source_pid:

            for n, d in G.nodes(data=True):
                if d.get("name", "").lower() in OWN_NAMES_NORMALIZED:
                    source_pid = n
                    break

        if not source_pid:
            log.error("You are not in the graph (check owner and own_emails in sbk.config.json). Cannot compute warm intros.")
            sys.exit(1)

        paths = find_warm_intros(G, source_pid, args.warm_intro, top_k=5, email_to_pid=e2p)
        if not paths:
            log.info(f"No path found to {args.warm_intro}")
        else:
            log.info(f"=== Warm Intro Paths to {args.warm_intro} ===")
            for i, p in enumerate(paths, 1):
                log.info(f"Path {i} (hops: {p['path_length']}, cost: {p['path_cost']}):")
                chain = " -> ".join(n["name"] or n["email"] for n in p["nodes"])
                log.info(f"  {chain}")
                if p["intermediaries"]:
                    log.info(f"  Intermediaries: {', '.join(p['intermediaries'])}")
                for edge in p["edges"]:
                    parts = []
                    if edge["email_msgs"]:
                        parts.append(f"{edge['email_msgs']} emails")
                    if edge.get("email_co_msgs"):
                        parts.append(f"{edge['email_co_msgs']} co-recipient")
                    if edge["cal_events"]:
                        parts.append(f"{edge['cal_events']} cal events")
                    if edge["tactiq_meetings"]:
                        parts.append(f"{edge['tactiq_meetings']} meetings")
                    if edge.get("slack_msgs"):
                        parts.append(f"{edge['slack_msgs']} slack msgs")
                    log.info(
                        f"    {edge['from']} <-> {edge['to']}: {', '.join(parts) or 'no data'}"
                    )

    if args.community:
        show_communities(communities, G)

    if args.stats:
        show_stats(G, communities, centrality)


    if not args.dry_run:
        save_graph(G)
        save_communities(communities, G)
        save_centrality(centrality, G)
        export_network_graph(G, communities, centrality)
        log.info("All outputs saved.")
    else:
        log.info("Dry run: no files saved.")


    person_count = sum(1 for _, d in G.nodes(data=True) if d.get("node_type") == "person")
    edge_count = sum(1 for _, _, d in G.edges(data=True) if d.get("edge_type") != "works_at")
    n_comm = len(set(c for c in communities.values() if c >= 0))

    log.info(f"Graph: {person_count} persons, {edge_count} interaction edges, {n_comm} communities")

    if not args.dry_run:
        from sbk_config import ENRICHED_DIR, mark_last_run, save_input_checkpoint
        from sbk_config import RELATIONSHIP_FACTS_FILE as _REL_FACTS

        inputs = [
            ENRICHED_DIR / "contacts-merged.parquet",
            ENRICHED_DIR / "interactions.parquet",
            _REL_FACTS,
        ]
        save_input_checkpoint("l3-graph", inputs)
        mark_last_run("l3-graph")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-graph", source="l3-graph", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
