#!/usr/bin/env python3
""












from __future__ import annotations

import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd



sys.path.insert(0, str(Path(__file__).resolve().parent))

from sbk_config import DATA_ROOT  # noqa: E402

ENRICHED = DATA_ROOT / "enriched"
L3 = DATA_ROOT / "l3"

CONTACTS_MERGED = ENRICHED / "contacts-merged.parquet"
ENTITY_MAP = ENRICHED / "entity-map.json"
ENTITY_DECISIONS = ENRICHED / "entity-decisions.json"
PERSON_ANNOTATIONS = ENRICHED / "person-annotations.json"
CONTACTS_RAW = ENRICHED / "contacts.parquet"
CONTACTS_CALENDAR = ENRICHED / "contacts-calendar.parquet"
INTERACTIONS = ENRICHED / "interactions.parquet"
THREADS = ENRICHED / "threads.parquet"

GRAPH_PICKLE = L3 / "graph" / "sbk-graph.gpickle"
CENTRALITY = L3 / "graph" / "centrality.json"
COMMUNITIES = L3 / "graph" / "communities.json"
DECAY_STATE = L3 / "decay" / "decay-state.json"
RELATIONSHIP_FACTS = L3 / "nlp" / "relationship-facts.parquet"
ENTITIES_NLP = L3 / "nlp" / "entities.parquet"

SEPARATOR = "=" * 80
SUB_SEP = "-" * 60


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def subsection(title: str) -> None:
    print(f"\n{SUB_SEP}")
    print(f"  {title}")
    print(SUB_SEP)


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        print(f"  [MISSING] {path}")
        return None
    with open(path) as f:
        return json.load(f)


def load_parquet(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        print(f"  [MISSING] {path}")
        return None
    df = pd.read_parquet(path)
    return df




section("1. DATA FILE INVENTORY")

print("\n--- Enriched directory ---")
for f in sorted(ENRICHED.iterdir()):
    if f.name.startswith("."):
        continue
    size_kb = f.stat().st_size / 1024
    print(f"  {f.name:45s}  {size_kb:>10.1f} KB")

print("\n--- L3 directory (recursive) ---")
for f in sorted(L3.rglob("*")):
    if f.is_dir() or f.name.startswith("."):
        continue
    size_kb = f.stat().st_size / 1024
    rel = f.relative_to(L3)
    print(f"  {str(rel):45s}  {size_kb:>10.1f} KB")



section("2. LOADING DATA")

contacts_merged = load_parquet(CONTACTS_MERGED)
if contacts_merged is not None:
    print(
        f"  contacts-merged: {len(contacts_merged)} rows, columns: {list(contacts_merged.columns)}"
    )

entity_map_raw = load_json(ENTITY_MAP)
if entity_map_raw is not None:
    print(f"  entity-map: {len(entity_map_raw)} entries")

entity_decisions = load_json(ENTITY_DECISIONS)
if entity_decisions is not None:
    if isinstance(entity_decisions, dict | list):
        print(f"  entity-decisions: {len(entity_decisions)} entries")

person_annotations = load_json(PERSON_ANNOTATIONS)
if person_annotations is not None:
    print(f"  person-annotations: {len(person_annotations)} entries")

contacts_raw = load_parquet(CONTACTS_RAW)
if contacts_raw is not None:
    print(f"  contacts.parquet (raw): {len(contacts_raw)} rows")

contacts_calendar = load_parquet(CONTACTS_CALENDAR)
if contacts_calendar is not None:
    print(f"  contacts-calendar: {len(contacts_calendar)} rows")

interactions = load_parquet(INTERACTIONS)
if interactions is not None:
    print(f"  interactions: {len(interactions)} rows")

threads = load_parquet(THREADS)
if threads is not None:
    print(f"  threads: {len(threads)} rows")


graph_nodes = set()
graph_edges = 0
if GRAPH_PICKLE.exists():
    with open(GRAPH_PICKLE, "rb") as gf:
        G = pickle.load(gf)
    graph_nodes = set(G.nodes())
    graph_edges = G.number_of_edges()
    print(f"  graph: {len(graph_nodes)} nodes, {graph_edges} edges")
else:
    print(f"  [MISSING] {GRAPH_PICKLE}")

centrality_data = load_json(CENTRALITY)
if centrality_data is not None:
    print(f"  centrality: {len(centrality_data)} entries")

communities_data = load_json(COMMUNITIES)
if communities_data is not None:
    print(f"  communities: {len(communities_data)} entries")


decay_data = load_json(DECAY_STATE)
decay_person_ids = set()
if decay_data is not None:
    if isinstance(decay_data, dict):
        decay_person_ids = set(decay_data.keys())
    elif isinstance(decay_data, list):
        decay_person_ids = {d.get("person_id", d.get("id", "")) for d in decay_data}
    print(f"  decay-state: {len(decay_person_ids)} person_ids")


rel_facts = load_parquet(RELATIONSHIP_FACTS)
if rel_facts is not None:
    print(f"  relationship-facts: {len(rel_facts)} rows, columns: {list(rel_facts.columns)}")

entities_nlp = load_parquet(ENTITIES_NLP)
if entities_nlp is not None:
    print(f"  entities (NLP): {len(entities_nlp)} rows")




section("3. CROSS-SOURCE CONSISTENCY CHECKS")


pid_col = None
if contacts_merged is not None:
    for candidate in ["person_id", "id", "contact_id"]:
        if candidate in contacts_merged.columns:
            pid_col = candidate
            break
    if pid_col is None:
        print(f"  [WARN] Cannot find person_id column. Available: {list(contacts_merged.columns)}")
    else:
        print(f"  Using person_id column: '{pid_col}'")


merged_ids = set()
if contacts_merged is not None and pid_col:
    merged_ids = set(contacts_merged[pid_col].dropna().unique())
    print(f"  Unique person_ids in contacts-merged: {len(merged_ids)}")



entity_map_target_ids = set()
entity_map_source_keys = set()
entity_map_dict = {}

if entity_map_raw is not None:
    if isinstance(entity_map_raw, dict):
        entity_map_dict = entity_map_raw
        for k, v in entity_map_raw.items():
            entity_map_source_keys.add(k)
            if isinstance(v, str):
                entity_map_target_ids.add(v)
            elif isinstance(v, dict):
                target = v.get("person_id") or v.get("canonical_id") or v.get("id")
                if target:
                    entity_map_target_ids.add(target)
    elif isinstance(entity_map_raw, list):
        for entry in entity_map_raw:
            if isinstance(entry, dict):
                src = entry.get("source_id") or entry.get("alias")
                tgt = entry.get("person_id") or entry.get("canonical_id")
                if src:
                    entity_map_source_keys.add(src)
                if tgt:
                    entity_map_target_ids.add(tgt)

    print(f"  Entity-map source keys: {len(entity_map_source_keys)}")
    print(f"  Entity-map target person_ids: {len(entity_map_target_ids)}")




subsection("3a. Orphaned Entity Mappings (in entity-map but NOT in contacts-merged)")

if entity_map_target_ids and merged_ids:
    orphaned_mappings = entity_map_target_ids - merged_ids
    print(f"  Count: {len(orphaned_mappings)} orphaned target person_ids")
    if orphaned_mappings:
        for pid in sorted(orphaned_mappings)[:100]:

            sources_for_orphan = []
            if isinstance(entity_map_raw, dict):
                for k, v in entity_map_raw.items():
                    target = (
                        v
                        if isinstance(v, str)
                        else (
                            v.get("person_id") or v.get("canonical_id") or v.get("id")
                            if isinstance(v, dict)
                            else None
                        )
                    )
                    if target == pid:
                        sources_for_orphan.append(k)
            print(f"    {pid}  <-- mapped from: {sources_for_orphan[:5]}")
        if len(orphaned_mappings) > 100:
            print(f"    ... and {len(orphaned_mappings) - 100} more")
else:
    print("  [SKIP] Missing data")




subsection("3b. Unmapped Contacts (in contacts-merged but NOT in entity-map)")

if merged_ids and entity_map_target_ids:


    all_entity_refs = entity_map_target_ids | entity_map_source_keys
    unmapped = merged_ids - all_entity_refs
    print(f"  Count: {len(unmapped)} unmapped contacts")
    if unmapped and contacts_merged is not None:

        unmapped_df = contacts_merged[contacts_merged[pid_col].isin(unmapped)].head(50)
        name_col = None
        for c in ["name", "display_name", "full_name"]:
            if c in unmapped_df.columns:
                name_col = c
                break
        if name_col:
            for _, row in unmapped_df.iterrows():
                print(f"    {row[pid_col]:40s}  name={row.get(name_col, '?')}")
        else:
            for _, row in unmapped_df.iterrows():
                print(f"    {row[pid_col]}")
        if len(unmapped) > 50:
            print(f"    ... and {len(unmapped) - 50} more")
else:
    print("  [SKIP] Missing data")




subsection("3c. Contacts with Conflicting Organizations Across Sources")

if contacts_merged is not None and pid_col:
    org_col = None
    source_col = None
    for c in ["organization", "org", "company"]:
        if c in contacts_merged.columns:
            org_col = c
            break
    for c in ["source", "sources", "source_list"]:
        if c in contacts_merged.columns:
            source_col = c
            break


    if org_col:


        org_source_cols = [c for c in contacts_merged.columns if "org" in c.lower()]
        print(f"  Organization-related columns: {org_source_cols}")


        source_org_cols = [
            c
            for c in contacts_merged.columns
            if c.startswith("org_") or c.endswith("_org") or c.endswith("_organization")
        ]
        if source_org_cols:
            print(f"  Source-specific org columns: {source_org_cols}")


        if contacts_raw is not None:
            raw_org_col = None
            raw_source_col = None
            raw_pid_col = None
            for c in ["organization", "org", "company"]:
                if c in contacts_raw.columns:
                    raw_org_col = c
                    break
            for c in ["source", "data_source"]:
                if c in contacts_raw.columns:
                    raw_source_col = c
                    break
            for c in ["person_id", "id", "contact_id"]:
                if c in contacts_raw.columns:
                    raw_pid_col = c
                    break

            if raw_org_col and raw_source_col and raw_pid_col:
                print(
                    f"\n  Using contacts.parquet: pid={raw_pid_col}, org={raw_org_col}, source={raw_source_col}"
                )

                org_by_person = contacts_raw.groupby(raw_pid_col)[raw_org_col].apply(
                    lambda x: set(v for v in x.dropna().unique() if v and str(v).strip())
                )
                conflicts = {pid: orgs for pid, orgs in org_by_person.items() if len(orgs) > 1}
                print(f"  Contacts with multiple distinct orgs: {len(conflicts)}")
                for count, (pid, orgs) in enumerate(
                    sorted(conflicts.items(), key=lambda x: -len(x[1]))
                ):
                    if count >= 50:
                        print(f"    ... and {len(conflicts) - 50} more")
                        break
                    print(f"    {pid:40s}  orgs={orgs}")
            else:
                print(f"  contacts.parquet columns: {list(contacts_raw.columns)}")
        else:
            print("  [INFO] No contacts.parquet to check per-source orgs")
    else:
        print(f"  [WARN] No org column found. Columns: {list(contacts_merged.columns)}")




subsection("3d. Name Discrepancies Across Sources")

if contacts_raw is not None:
    raw_name_col = None
    raw_source_col = None
    raw_pid_col = None
    for c in ["name", "display_name", "full_name"]:
        if c in contacts_raw.columns:
            raw_name_col = c
            break
    for c in ["source", "data_source"]:
        if c in contacts_raw.columns:
            raw_source_col = c
            break
    for c in ["person_id", "id", "contact_id"]:
        if c in contacts_raw.columns:
            raw_pid_col = c
            break

    if raw_name_col and raw_pid_col:
        print(f"  Using contacts.parquet: pid={raw_pid_col}, name={raw_name_col}")


        from difflib import SequenceMatcher

        name_by_person = contacts_raw.groupby(raw_pid_col)[raw_name_col].apply(
            lambda x: list(set(v for v in x.dropna().unique() if v and str(v).strip()))
        )
        name_conflicts = {}
        for pid, names in name_by_person.items():
            if len(names) <= 1:
                continue

            names_lower = [n.lower().strip() for n in names]

            flagged = False
            for i in range(len(names_lower)):
                for j in range(i + 1, len(names_lower)):
                    ratio = SequenceMatcher(None, names_lower[i], names_lower[j]).ratio()
                    if ratio < 0.6:
                        flagged = True
                        break
                if flagged:
                    break
            if flagged:
                name_conflicts[pid] = names

        print(f"  Contacts with significantly different names: {len(name_conflicts)}")
        for count, (pid, names) in enumerate(sorted(name_conflicts.items())):
            if count >= 80:
                print(f"    ... and {len(name_conflicts) - 80} more")
                break
            print(f"    {pid:40s}  names={names}")
    else:
        print(
            f"  [WARN] Missing name/pid columns. contacts.parquet columns: {list(contacts_raw.columns)}"
        )
else:
    print("  [SKIP] No contacts.parquet available")




subsection(
    "3d-bis. Name Discrepancies Within contacts-merged (name vs attio_name vs personio_name)"
)

if contacts_merged is not None and pid_col:
    name_cols_available = []
    for c in ["name", "attio_name", "personio_name"]:
        if c in contacts_merged.columns:
            name_cols_available.append(c)

    if len(name_cols_available) >= 2:
        from difflib import SequenceMatcher as SM2

        discrepancy_count = 0
        print(f"  Comparing columns: {name_cols_available}")
        for _, row in contacts_merged.iterrows():
            names_for_row = {}
            for nc in name_cols_available:
                val = row.get(nc)
                if val and pd.notna(val) and str(val).strip():
                    names_for_row[nc] = str(val).strip()

            if len(names_for_row) < 2:
                continue

            keys = list(names_for_row.keys())
            flagged = False
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    ratio = SM2(
                        None, names_for_row[keys[i]].lower(), names_for_row[keys[j]].lower()
                    ).ratio()
                    if ratio < 0.5:
                        flagged = True
                        break
                if flagged:
                    break

            if flagged:
                discrepancy_count += 1
                if discrepancy_count <= 80:
                    pid = row[pid_col]
                    detail = ", ".join(f"{k}='{names_for_row[k]}'" for k in keys)
                    print(f"    {pid:40s}  {detail}")

        print(f"\n  Total name discrepancies: {discrepancy_count}")
    else:
        print(f"  [SKIP] Only {len(name_cols_available)} name columns found: {name_cols_available}")




subsection("3e. Contacts in Decay but NOT in contacts-merged")

if decay_person_ids and merged_ids:
    decay_not_merged = decay_person_ids - merged_ids
    print(f"  Decay person_ids not in contacts-merged: {len(decay_not_merged)}")
    if decay_not_merged:
        for pid in sorted(decay_not_merged)[:30]:

            info = ""
            if isinstance(decay_data, dict) and pid in decay_data:
                d = decay_data[pid]
                if isinstance(d, dict):
                    info = f"  name={d.get('name', '?')}, score={d.get('score', '?')}"
            print(f"    {pid:40s}{info}")
        if len(decay_not_merged) > 30:
            print(f"    ... and {len(decay_not_merged) - 30} more")


    merged_not_decay = merged_ids - decay_person_ids
    print(f"\n  Contacts-merged NOT in decay: {len(merged_not_decay)}")
    print("  (This is expected for low-interaction contacts)")
else:
    print("  [SKIP] Missing data")




subsection("3f. Contacts in Graph but NOT in contacts-merged")

if graph_nodes and merged_ids:
    graph_not_merged = graph_nodes - merged_ids

    graph_not_merged_filtered = {n for n in graph_not_merged if not n.startswith("__")}
    print(f"  Graph nodes not in contacts-merged: {len(graph_not_merged_filtered)}")
    if graph_not_merged_filtered:
        for pid in sorted(graph_not_merged_filtered)[:30]:

            attrs = G.nodes.get(pid, {})
            name = attrs.get("name", attrs.get("label", "?"))
            print(f"    {pid:40s}  name={name}")
        if len(graph_not_merged_filtered) > 30:
            print(f"    ... and {len(graph_not_merged_filtered) - 30} more")

    merged_not_graph = merged_ids - graph_nodes
    print(f"\n  Contacts-merged NOT in graph: {len(merged_not_graph)}")
else:
    print("  [SKIP] Missing data")




subsection("3g. Email Addresses Shared Across Different person_ids")

if contacts_merged is not None and pid_col:
    email_col = None
    email_list_col = None
    for c in contacts_merged.columns:
        if c in ("email", "primary_email"):
            email_col = c
            break
        if c in ("emails", "email_list", "all_emails"):
            email_list_col = c
            break

    email_to_pids: dict[str, set[str]] = defaultdict(set)

    if email_col:
        for _, row in contacts_merged.iterrows():
            pid = row[pid_col]
            email = row.get(email_col)
            if email and pd.notna(email) and str(email).strip():
                email_to_pids[str(email).strip().lower()].add(str(pid))

    if email_list_col:
        for _, row in contacts_merged.iterrows():
            pid = row[pid_col]
            emails = row.get(email_list_col)
            if emails and pd.notna(emails):
                if isinstance(emails, list):
                    for e in emails:
                        if e and str(e).strip():
                            email_to_pids[str(e).strip().lower()].add(str(pid))
                elif isinstance(emails, str):

                    for e in emails.split(","):
                        e = e.strip()
                        if e:
                            email_to_pids[e.lower()].add(str(pid))


    if contacts_raw is not None:
        raw_email_col = None
        raw_pid_col2 = None
        for c in contacts_raw.columns:
            if c in ("email", "primary_email"):
                raw_email_col = c
                break
        for c in ["person_id", "id", "contact_id"]:
            if c in contacts_raw.columns:
                raw_pid_col2 = c
                break
        if raw_email_col and raw_pid_col2:
            for _, row in contacts_raw.iterrows():
                pid = row[raw_pid_col2]
                email = row.get(raw_email_col)
                if email and pd.notna(email) and str(email).strip():
                    email_to_pids[str(email).strip().lower()].add(str(pid))

    shared_emails = {email: pids for email, pids in email_to_pids.items() if len(pids) > 1}
    print(f"  Emails appearing under multiple person_ids: {len(shared_emails)}")
    for email, pids in sorted(shared_emails.items(), key=lambda x: -len(x[1])):
        print(f"    {email:45s}  person_ids={pids}")
else:
    print("  [SKIP] Missing data")




subsection("3h. Phone Numbers Shared Across Different person_ids")

if contacts_merged is not None and pid_col:
    phone_col = None
    phone_list_col = None
    for c in contacts_merged.columns:
        if c in ("phone", "primary_phone", "phone_number"):
            phone_col = c
            break
        if c in ("phones", "phone_list", "all_phones", "phone_numbers"):
            phone_list_col = c
            break

    phone_to_pids: dict[str, set[str]] = defaultdict(set)

    if phone_col:
        for _, row in contacts_merged.iterrows():
            pid = row[pid_col]
            phone = row.get(phone_col)
            if phone and pd.notna(phone) and str(phone).strip():

                p = (
                    str(phone)
                    .strip()
                    .replace(" ", "")
                    .replace("-", "")
                    .replace("(", "")
                    .replace(")", "")
                )
                if len(p) >= 7:
                    phone_to_pids[p].add(str(pid))

    if phone_list_col:
        for _, row in contacts_merged.iterrows():
            pid = row[pid_col]
            phones = row.get(phone_list_col)
            if phones and pd.notna(phones):
                if isinstance(phones, list):
                    for p in phones:
                        if p and str(p).strip():
                            pn = (
                                str(p)
                                .strip()
                                .replace(" ", "")
                                .replace("-", "")
                                .replace("(", "")
                                .replace(")", "")
                            )
                            if len(pn) >= 7:
                                phone_to_pids[pn].add(str(pid))


    if contacts_raw is not None:
        raw_phone_col = None
        for c in contacts_raw.columns:
            if c in ("phone", "primary_phone", "phone_number"):
                raw_phone_col = c
                break
        if raw_phone_col and raw_pid_col2:
            for _, row in contacts_raw.iterrows():
                pid = row[raw_pid_col2]
                phone = row.get(raw_phone_col)
                if phone and pd.notna(phone) and str(phone).strip():
                    pn = (
                        str(phone)
                        .strip()
                        .replace(" ", "")
                        .replace("-", "")
                        .replace("(", "")
                        .replace(")", "")
                    )
                    if len(pn) >= 7:
                        phone_to_pids[pn].add(str(pid))

    shared_phones = {phone: pids for phone, pids in phone_to_pids.items() if len(pids) > 1}
    print(f"  Phones appearing under multiple person_ids: {len(shared_phones)}")
    for phone, pids in sorted(shared_phones.items(), key=lambda x: -len(x[1])):
        print(f"    {phone:30s}  person_ids={pids}")
else:
    print("  [SKIP] Missing data")




subsection("3i. Contact Counts per Source")

if contacts_merged is not None:
    source_col = None
    for c in ["source", "sources", "source_list", "data_source"]:
        if c in contacts_merged.columns:
            source_col = c
            break

    if source_col:

        source_counts: Counter = Counter()
        for _, row in contacts_merged.iterrows():
            src = row[source_col]
            if pd.isna(src):
                source_counts["<null>"] += 1
                continue
            if isinstance(src, list):
                for s in src:
                    source_counts[s] += 1
            elif isinstance(src, str):
                if "," in src:
                    for s in src.split(","):
                        source_counts[s.strip()] += 1
                else:
                    source_counts[src.strip()] += 1
            else:
                source_counts[str(src)] += 1

        total = len(contacts_merged)
        print(f"\n  Total contacts: {total}")
        print(f"  {'Source':<30s}  {'Count':>8s}  {'% of total':>10s}")
        print(f"  {'------':<30s}  {'-----':>8s}  {'----------':>10s}")
        for src, cnt in source_counts.most_common():
            pct = cnt / total * 100
            flag = ""
            if cnt < 5:
                flag = "  [VERY LOW]"
            elif cnt > total * 0.8:
                flag = "  [DOMINATES]"
            print(f"  {src:<30s}  {cnt:>8d}  {pct:>9.1f}%{flag}")
    else:

        has_cols = [c for c in contacts_merged.columns if c.startswith("has_")]
        if has_cols:
            total = len(contacts_merged)
            print(f"\n  Total contacts: {total}")
            print("  (Using has_* boolean columns as source indicators)")
            print(f"  {'Source (has_*)':<30s}  {'Count':>8s}  {'% of total':>10s}")
            print(f"  {'-------------':<30s}  {'-----':>8s}  {'----------':>10s}")
            for col in sorted(has_cols):
                cnt = int(contacts_merged[col].sum())
                pct = cnt / total * 100
                flag = ""
                if cnt < 5:
                    flag = "  [VERY LOW]"
                elif cnt > total * 0.8:
                    flag = "  [DOMINATES]"
                print(f"  {col:<30s}  {cnt:>8d}  {pct:>9.1f}%{flag}")


            if "source_count" in contacts_merged.columns:
                print("\n  source_count distribution:")
                for sc, cnt in contacts_merged["source_count"].value_counts().sort_index().items():
                    print(f"    {sc} sources:  {cnt:>6d} contacts ({cnt / total * 100:.1f}%)")
        else:
            print("  [WARN] No source or has_* columns found.")


if contacts_raw is not None:
    raw_source_col = None
    for c in ["source", "data_source"]:
        if c in contacts_raw.columns:
            raw_source_col = c
            break
    if raw_source_col:
        subsection("3i-bis. Contact Counts per Source (raw contacts.parquet)")
        raw_source_counts = contacts_raw[raw_source_col].value_counts()
        total_raw = len(contacts_raw)
        print(f"\n  Total raw contacts: {total_raw}")
        for src, cnt in raw_source_counts.items():
            pct = cnt / total_raw * 100
            flag = ""
            if cnt < 5:
                flag = "  [VERY LOW]"
            elif cnt > total_raw * 0.8:
                flag = "  [DOMINATES]"
            print(f"  {str(src):<30s}  {cnt:>8d}  {pct:>9.1f}%{flag}")




subsection("3j. Person Annotations Coverage")

if person_annotations is not None and merged_ids:
    annotation_ids = set()
    if isinstance(person_annotations, dict):
        annotation_ids = set(person_annotations.keys())
    elif isinstance(person_annotations, list):
        annotation_ids = {a.get("person_id", a.get("id", "")) for a in person_annotations}

    print(f"  Annotated persons: {len(annotation_ids)}")
    annotated_not_merged = annotation_ids - merged_ids
    print(f"  Annotated but NOT in contacts-merged: {len(annotated_not_merged)}")
    if annotated_not_merged:
        for pid in sorted(annotated_not_merged)[:20]:
            info = ""
            if isinstance(person_annotations, dict) and pid in person_annotations:
                a = person_annotations[pid]
                if isinstance(a, dict):
                    info = f"  name={a.get('name', '?')}"
            print(f"    {pid:40s}{info}")
        if len(annotated_not_merged) > 20:
            print(f"    ... and {len(annotated_not_merged) - 20} more")

    merged_not_annotated = merged_ids - annotation_ids
    print(
        f"  Contacts-merged NOT annotated: {len(merged_not_annotated)} ({len(merged_not_annotated) / len(merged_ids) * 100:.1f}%)"
    )
else:
    print("  [SKIP] Missing data")




subsection("3k. Relationship Facts Coverage")

if rel_facts is not None and merged_ids:

    rf_pid_cols = [
        c
        for c in rel_facts.columns
        if "person" in c.lower()
        or "id" in c.lower()
        or "subject" in c.lower()
        or "object" in c.lower()
    ]
    print(f"  Relationship facts columns: {list(rel_facts.columns)}")
    print(f"  Candidate ID columns: {rf_pid_cols}")


    rf_pids = set()
    for c in rf_pid_cols:
        vals = rel_facts[c].dropna().unique()
        rf_pids.update(str(v) for v in vals if v and str(v).strip())

    if rf_pids:
        rf_not_merged = rf_pids - merged_ids
        print(f"  Unique IDs in relationship facts: {len(rf_pids)}")
        print(f"  IDs in facts but NOT in contacts-merged: {len(rf_not_merged)}")


    rel_type_col = None
    for c in ["relation", "relationship", "type", "rel_type", "predicate"]:
        if c in rel_facts.columns:
            rel_type_col = c
            break
    if rel_type_col:
        print("\n  Relationship type distribution:")
        for rtype, cnt in rel_facts[rel_type_col].value_counts().items():
            print(f"    {str(rtype):<35s}  {cnt:>6d}")
else:
    print("  [SKIP] Missing data")




subsection("3l. Entity-Map Internal Consistency")

if entity_map_raw is not None and isinstance(entity_map_raw, dict):

    circular = []
    chains_over_2 = []

    for src, tgt in entity_map_raw.items():
        target = (
            tgt
            if isinstance(tgt, str)
            else (
                tgt.get("person_id") or tgt.get("canonical_id") if isinstance(tgt, dict) else None
            )
        )
        if not target:
            continue

        if target in entity_map_raw:
            tgt2_raw = entity_map_raw[target]
            tgt2 = (
                tgt2_raw
                if isinstance(tgt2_raw, str)
                else (
                    tgt2_raw.get("person_id") or tgt2_raw.get("canonical_id")
                    if isinstance(tgt2_raw, dict)
                    else None
                )
            )
            if tgt2 == src:
                circular.append((src, target))
            elif tgt2 and tgt2 != target:
                chains_over_2.append((src, target, tgt2))

    print(f"  Circular mappings (A->B->A): {len(circular)}")
    for a, b in circular[:20]:
        print(f"    {a} <-> {b}")

    print(f"  Transitive chains (A->B->C where B!=C): {len(chains_over_2)}")
    for a, b, c in chains_over_2[:20]:
        print(f"    {a} -> {b} -> {c}")
    if len(chains_over_2) > 20:
        print(f"    ... and {len(chains_over_2) - 20} more")


    target_counts: Counter = Counter()
    for src, tgt in entity_map_raw.items():
        target = (
            tgt
            if isinstance(tgt, str)
            else (
                tgt.get("person_id") or tgt.get("canonical_id") if isinstance(tgt, dict) else None
            )
        )
        if target:
            target_counts[target] += 1


    print("\n  Targets with most mappings (potential over-merging):")
    for target, cnt in target_counts.most_common(20):
        if cnt >= 3:

            name = "?"
            if contacts_merged is not None and pid_col:
                match = contacts_merged[contacts_merged[pid_col] == target]
                if len(match) > 0:
                    for nc in ["name", "display_name", "full_name"]:
                        if nc in match.columns:
                            name = match.iloc[0][nc]
                            break
            print(f"    {target:40s}  mappings={cnt}  name={name}")




section("SUMMARY")

print(f"""
  Data files:
    contacts-merged:    {len(contacts_merged) if contacts_merged is not None else "MISSING"} rows
    contacts (raw):     {len(contacts_raw) if contacts_raw is not None else "MISSING"} rows
    entity-map:         {len(entity_map_raw) if entity_map_raw is not None else "MISSING"} entries
    person-annotations: {len(person_annotations) if person_annotations is not None else "MISSING"} entries
    graph nodes:        {len(graph_nodes)} nodes, {graph_edges} edges
    decay tracking:     {len(decay_person_ids)} persons
    relationship facts: {len(rel_facts) if rel_facts is not None else "MISSING"} facts

  Consistency:
    Orphaned entity mappings:      {len(entity_map_target_ids - merged_ids) if entity_map_target_ids and merged_ids else "N/A"}
    Unmapped contacts:             {len(merged_ids - (entity_map_target_ids | entity_map_source_keys)) if merged_ids and entity_map_target_ids else "N/A"}
    Decay not in merged:           {len(decay_person_ids - merged_ids) if decay_person_ids and merged_ids else "N/A"}
    Graph not in merged:           {len(graph_nodes - merged_ids) if graph_nodes and merged_ids else "N/A"}
    Merged not in graph:           {len(merged_ids - graph_nodes) if graph_nodes and merged_ids else "N/A"}
    Merged not in decay:           {len(merged_ids - decay_person_ids) if decay_person_ids and merged_ids else "N/A"}
    Shared emails:                 {len(shared_emails) if "shared_emails" in dir() else "N/A"}
    Shared phones:                 {len(shared_phones) if "shared_phones" in dir() else "N/A"}
""")

print(f"\n{SEPARATOR}")
print("  AUDIT COMPLETE")
print(SEPARATOR)
