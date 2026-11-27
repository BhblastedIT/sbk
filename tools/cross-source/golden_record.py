""












import json
import logging
import os
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from rapidfuzz import fuzz

log = logging.getLogger("golden-record")



from sbk_config import KNOWLEDGE_DIR as _DEFAULT_KNOWLEDGE_DIR

_DEFAULT_CLUSTER_INDEX = _DEFAULT_KNOWLEDGE_DIR / "entity-clusters.json"




SOURCE_PRIORITY = [
    "attio",
    "linkedin",
    "personio",
    "email",
    "contacts-merged",
    "plaud",
    "tactiq",
    "slack",
    "calendar",
    "whatsapp",
    "docusign",
    "notion",
    "relationship-facts",
    "deep_facts",
    "network-graph",
]

SURVIVORSHIP_RULES = {
    "canonical_name": {"strategy": "priority_source"},
    "identity.name": {"strategy": "priority_source"},
    "identity.email": {"strategy": "union"},
    "identity.phone": {"strategy": "priority_source"},
    "identity.title": {"strategy": "priority_source"},
    "identity.company": {"strategy": "priority_source"},
    "identity.linkedin_url": {"strategy": "first_non_null"},
}


DEFAULT_RULE = {"strategy": "merge_all"}





def load_cluster_index(path: Path | None = None) -> dict:
    ""
    path = path or _DEFAULT_CLUSTER_INDEX
    if not path.exists():
        return {"version": 2, "clusters": {}, "decisions": []}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Corrupt cluster index at {path}: {e}")
        return {"version": 2, "clusters": {}, "decisions": []}


def save_cluster_index(data: dict, path: Path | None = None):
    ""
    path = path or _DEFAULT_CLUSTER_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{path}.tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    log.info(f"Saved cluster index: {len(data.get('clusters', {}))} clusters → {path}")


def build_inverse_index(clusters: dict) -> dict[str, str]:
    ""
    inverse = {}
    for cluster_id, cluster_info in clusters.items():
        for member in cluster_info.get("members", []):
            eid = member.get("entity_id", "")
            if eid:
                inverse[eid] = cluster_id
    return inverse





def load_entity_profile(entity_id: str, knowledge_dir: Path | None = None) -> dict | None:
    ""
    knowledge_dir = knowledge_dir or _DEFAULT_KNOWLEDGE_DIR

    for entity_type in ["person", "organization", "deal", "commitment"]:
        path = knowledge_dir / "entities" / entity_type / f"{entity_id}.json"
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Corrupt entity profile at {path}: {e}")
                return None
    return None





def _source_rank(source_type: str) -> int:
    ""
    try:
        return SOURCE_PRIORITY.index(source_type)
    except ValueError:
        return len(SOURCE_PRIORITY)


def _get_fact_source_type(fact: dict) -> str:
    ""
    source = fact.get("source", {})
    if isinstance(source, dict):
        return source.get("source_type", "")
    return ""


def apply_survivorship_canonical_name(profiles: list[dict]) -> str:
    ""
    candidates = []
    for p in profiles:
        name = p.get("canonical_name", "")
        if not name:
            continue

        source_types = set()
        for fact in p.get("facts", []):
            st = _get_fact_source_type(fact)
            if st:
                source_types.add(st)
        best_rank = min((_source_rank(s) for s in source_types), default=999)
        candidates.append((best_rank, len(name), name))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: (x[0], -x[1]))
    return candidates[0][2]


def apply_survivorship_priority(all_facts: list[dict], attribute: str) -> dict | None:
    ""
    matching = [f for f in all_facts if f.get("attribute") == attribute]
    if not matching:
        return None
    matching.sort(key=lambda f: _source_rank(_get_fact_source_type(f)))
    return matching[0]


def apply_survivorship_union(all_facts: list[dict], attribute: str) -> list[dict]:
    ""
    matching = [f for f in all_facts if f.get("attribute") == attribute]
    seen_values = set()
    unique = []
    for fact in matching:
        val = str(fact.get("value", "")).strip().lower()
        if val and val not in seen_values:
            seen_values.add(val)
            unique.append(fact)
    return unique


def apply_survivorship_first_non_null(all_facts: list[dict], attribute: str) -> dict | None:
    ""
    for fact in all_facts:
        if fact.get("attribute") == attribute and fact.get("value"):
            return fact
    return None


def merge_all_facts(profiles: list[dict]) -> list[dict]:
    ""
    all_facts = []
    seen = set()
    for profile in profiles:
        for fact in profile.get("facts", []):

            key = (
                fact.get("attribute", ""),
                str(fact.get("value", ""))[:100],
                _get_fact_source_type(fact),
            )
            if key not in seen:
                seen.add(key)
                all_facts.append(fact)
    return all_facts





def detect_conflicts(all_facts: list[dict], attribute: str) -> list[dict]:
    ""






    matching = [f for f in all_facts if f.get("attribute") == attribute and f.get("value")]
    if len(matching) < 2:
        return []

    conflicts = []
    for fact_a, fact_b in combinations(matching, 2):
        val_a = str(fact_a["value"]).strip()
        val_b = str(fact_b["value"]).strip()

        if val_a == val_b:
            continue


        if val_a.lower() in val_b.lower() or val_b.lower() in val_a.lower():
            continue

        similarity = fuzz.ratio(val_a, val_b)
        if similarity < 70:
            conflicts.append(
                {
                    "attribute": attribute,
                    "source_a": _get_fact_source_type(fact_a),
                    "value_a": val_a,
                    "source_b": _get_fact_source_type(fact_b),
                    "value_b": val_b,
                    "similarity": similarity,
                }
            )
    return conflicts


def detect_all_conflicts(all_facts: list[dict]) -> list[dict]:
    ""
    attributes = set(f.get("attribute", "") for f in all_facts)
    conflicts = []
    for attr in sorted(attributes):
        conflicts.extend(detect_conflicts(all_facts, attr))
    return conflicts





class GoldenRecordEngine:
    ""

    def __init__(
        self,
        cluster_index_path: Path | None = None,
        knowledge_dir: Path | None = None,
    ):
        self.knowledge_dir = knowledge_dir or _DEFAULT_KNOWLEDGE_DIR
        self._cluster_data = load_cluster_index(cluster_index_path)
        self._clusters = self._cluster_data.get("clusters", {})
        self._decisions = self._cluster_data.get("decisions", [])
        self._inverse = build_inverse_index(self._clusters)
        self._cluster_index_path = cluster_index_path or _DEFAULT_CLUSTER_INDEX

    def find_cluster(self, entity_id: str) -> dict | None:
        ""
        cluster_id = self._inverse.get(entity_id)
        if cluster_id:
            return self._clusters.get(cluster_id)
        return None

    def get_golden_record(self, entity_id: str) -> dict:
        ""




        cluster = self.find_cluster(entity_id)

        if not cluster:
            profile = load_entity_profile(entity_id, self.knowledge_dir)
            if not profile:
                return {"entity_id": entity_id, "error": "profile_not_found"}
            profile["_cluster_size"] = 1
            profile["_conflicts"] = []
            return profile


        profiles = []
        for member in cluster.get("members", []):
            mid = member.get("entity_id", "")
            p = load_entity_profile(mid, self.knowledge_dir)
            if p:
                profiles.append(p)

        if not profiles:
            return {"entity_id": entity_id, "error": "no_member_profiles_found"}

        if len(profiles) == 1:
            profiles[0]["_cluster_size"] = len(cluster.get("members", []))
            profiles[0]["_conflicts"] = []
            return profiles[0]

        return self._build_golden(entity_id, profiles, cluster)

    def _build_golden(self, entity_id: str, profiles: list[dict], cluster: dict) -> dict:
        ""

        canonical_name = apply_survivorship_canonical_name(profiles)


        all_facts = merge_all_facts(profiles)


        surviving_facts = []
        processed_attrs = set()

        for attr, rule in SURVIVORSHIP_RULES.items():
            strategy = rule["strategy"]
            if strategy == "priority_source":
                fact = apply_survivorship_priority(all_facts, attr)
                if fact:
                    surviving_facts.append(fact)
                processed_attrs.add(attr)
            elif strategy == "union":
                facts = apply_survivorship_union(all_facts, attr)
                surviving_facts.extend(facts)
                processed_attrs.add(attr)
            elif strategy == "first_non_null":
                fact = apply_survivorship_first_non_null(all_facts, attr)
                if fact:
                    surviving_facts.append(fact)
                processed_attrs.add(attr)


        for fact in all_facts:
            attr = fact.get("attribute", "")
            if attr not in processed_attrs:
                surviving_facts.append(fact)


        conflicts = detect_all_conflicts(all_facts)


        golden = {
            "entity_id": entity_id,
            "entity_type": profiles[0].get("entity_type", "person"),
            "canonical_name": canonical_name,
            "facts": surviving_facts,
            "created_at": min((p.get("created_at", "") for p in profiles), default=""),
            "updated_at": max((p.get("updated_at", "") for p in profiles), default=""),
            "version": max((p.get("version", 1) for p in profiles), default=1),
            "_cluster_size": len(cluster.get("members", [])),
            "_member_ids": [m.get("entity_id") for m in cluster.get("members", [])],
            "_conflicts": conflicts,
        }
        return golden

    def get_golden_record_by_name(self, name: str) -> dict | None:
        ""
        name_lower = name.lower()
        for entity_type in ["person", "organization"]:
            etype_dir = self.knowledge_dir / "entities" / entity_type
            if not etype_dir.exists():
                continue
            for path in etype_dir.iterdir():
                if path.suffix != ".json":
                    continue
                try:
                    with open(path) as f:
                        profile = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue
                if name_lower in profile.get("canonical_name", "").lower():
                    return self.get_golden_record(profile["entity_id"])
        return None



    def undo_merge(self, entity_id_a: str, entity_id_b: str) -> bool:
        ""





        decision = self._find_decision(entity_id_a, entity_id_b)
        if not decision:
            log.warning(f"No merge decision found for {entity_id_a} + {entity_id_b}")
            return False

        now = datetime.now(UTC).isoformat()


        decision["status"] = "retracted"
        decision["retracted_at"] = now


        self._decisions.append(
            {
                "id": f"dec-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
                "action": "reject",
                "entity_ids": [entity_id_a, entity_id_b],
                "retracted_decision_id": decision["id"],
                "timestamp": now,
                "status": "active",
            }
        )


        self._split_cluster(entity_id_a, entity_id_b)


        self._inverse = build_inverse_index(self._clusters)


        self._cluster_data["clusters"] = self._clusters
        self._cluster_data["decisions"] = self._decisions
        save_cluster_index(self._cluster_data, self._cluster_index_path)

        log.info(f"Undone merge: {entity_id_a} / {entity_id_b}")
        return True

    def _find_decision(self, entity_id_a: str, entity_id_b: str) -> dict | None:
        ""
        for dec in reversed(self._decisions):
            if dec.get("status") != "active" or dec.get("action") != "merge":
                continue
            eids = set(dec.get("entity_ids", []))
            if entity_id_a in eids and entity_id_b in eids:
                return dec
        return None

    def _split_cluster(self, entity_id_a: str, entity_id_b: str):
        ""
        cluster_id = self._inverse.get(entity_id_a)
        if not cluster_id:
            return

        cluster = self._clusters.get(cluster_id)
        if not cluster:
            return

        members = cluster.get("members", [])
        remaining = [m for m in members if m.get("entity_id") != entity_id_b]
        removed = [m for m in members if m.get("entity_id") == entity_id_b]

        if len(remaining) >= 2:
            cluster["members"] = remaining
        elif len(remaining) == 1:

            del self._clusters[cluster_id]
        else:
            del self._clusters[cluster_id]


        if removed:

            pass





def migrate_from_splink_clusters(
    splink_path: Path | None = None,
    output_path: Path | None = None,
    knowledge_dir: Path | None = None,
) -> dict:
    ""




    from pathlib import Path as _P

    knowledge_dir = knowledge_dir or _DEFAULT_KNOWLEDGE_DIR
    splink_path = splink_path or (
        _P(os.environ.get("SBK_DATA_ROOT") or _P.home() / ".sbk-data").expanduser()
        / "enriched"
        / "entity-clusters-splink.json"
    )
    output_path = output_path or _DEFAULT_CLUSTER_INDEX

    if not splink_path.exists():
        log.warning(f"Splink clusters not found: {splink_path}")
        return {"version": 2, "clusters": {}, "decisions": []}

    with open(splink_path) as f:
        splink_data = json.load(f)

    splink_clusters = splink_data.get("clusters", {})


    name_to_eids: dict[str, list[str]] = defaultdict(list)
    person_dir = knowledge_dir / "entities" / "person"
    if person_dir.exists():
        for path in person_dir.iterdir():
            if path.suffix != ".json":
                continue
            try:
                with open(path) as f:
                    profile = json.load(f)
                name = profile.get("canonical_name", "").lower().strip()
                if name:
                    name_to_eids[name].append(profile["entity_id"])
            except Exception:
                continue

    now = datetime.now(UTC).isoformat()
    clusters = {}
    decisions = []

    for cluster_id, cluster_info in splink_clusters.items():
        members_raw = cluster_info.get("members", [])
        if len(members_raw) < 2:
            continue


        members = []
        unmapped = 0
        for m in members_raw:
            name = m.get("name", "").lower().strip()
            eids = name_to_eids.get(name, [])
            if eids:
                for eid in eids:
                    members.append(
                        {
                            "entity_id": eid,
                            "confidence": m.get("confidence", 0.9),
                            "method": m.get("method", "splink_auto"),
                            "merged_at": now,
                        }
                    )
            else:
                unmapped += 1
                log.debug("Splink member '%s' not found in knowledge store", m.get("name"))

        if len(members) < 2 and len(members_raw) >= 2:
            log.warning(
                "Splink cluster %s dropped: %d/%d members unmapped",
                cluster_id,
                unmapped,
                len(members_raw),
            )

        if len(members) >= 2:

            cid = members[0]["entity_id"]
            clusters[cid] = {"members": members}
            decisions.append(
                {
                    "id": f"dec-splink-{cluster_id}",
                    "action": "merge",
                    "cluster_id": cid,
                    "entity_ids": [m["entity_id"] for m in members],
                    "confidence": members[0]["confidence"],
                    "method": "splink_auto",
                    "timestamp": now,
                    "status": "active",
                }
            )

    result = {
        "version": 2,
        "created": now,
        "clusters": clusters,
        "decisions": decisions,
    }

    save_cluster_index(result, output_path)
    log.info(f"Migration complete: {len(clusters)} clusters, {len(decisions)} decisions")
    return result





class KnowledgeQueryRouter:
    ""





    def __init__(
        self,
        knowledge_dir: Path | None = None,
        cluster_index_path: Path | None = None,
    ):
        self.knowledge_dir = knowledge_dir or _DEFAULT_KNOWLEDGE_DIR
        self._cluster_path = cluster_index_path or _DEFAULT_CLUSTER_INDEX
        self._engine: GoldenRecordEngine | None = None
        self.sources = self._discover_sources()

    def _discover_sources(self) -> list[str]:
        ""
        available = []
        if (self.knowledge_dir / "entities").exists():
            available.append("knowledge_store")
        if self._cluster_path.exists():
            available.append("golden_record")
            self._engine = GoldenRecordEngine(self._cluster_path, self.knowledge_dir)
        return available

    def query_person(self, name_or_id: str) -> dict | None:
        ""




        if name_or_id.startswith("person_") or name_or_id.startswith("org_"):
            if self._engine:
                golden = self._engine.get_golden_record(name_or_id)
                if not golden.get("error"):
                    return golden
            return load_entity_profile(name_or_id, self.knowledge_dir)


        if self._engine:
            golden = self._engine.get_golden_record_by_name(name_or_id)
            if golden:
                return golden


        return self._search_by_name(name_or_id)

    def query_company_team(self, company: str) -> list[dict]:
        ""




        person_dir = self.knowledge_dir / "entities" / "person"
        if not person_dir.exists():
            return []

        company_lower = company.lower().strip()
        members = []
        seen_ids = set()

        for path in person_dir.iterdir():
            if path.suffix != ".json":
                continue
            try:
                with open(path) as f:
                    profile = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            entity_id = profile.get("entity_id", "")


            if entity_id in seen_ids:
                continue


            for fact in profile.get("facts", []):
                attr = fact.get("attribute", "")
                val = str(fact.get("value", "")).lower()
                if attr.startswith("employment.") and company_lower in val:

                    if self._engine:
                        golden = self._engine.get_golden_record(entity_id)
                        if not golden.get("error"):
                            profile = golden

                            for mid in golden.get("_member_ids", [entity_id]):
                                seen_ids.add(mid)

                    members.append(
                        {
                            "entity_id": entity_id,
                            "name": profile.get("canonical_name", ""),
                            "cluster_size": profile.get("_cluster_size", 1),
                            "facts": profile.get("facts", []),
                        }
                    )
                    seen_ids.add(entity_id)
                    break

        return members

    def query_organization(self, name_or_id: str) -> dict | None:
        ""



        org_dir = self.knowledge_dir / "entities" / "organization"
        if not org_dir.exists():
            return None


        if name_or_id.startswith("org_") or name_or_id.startswith("organization_"):
            if self._engine:
                golden = self._engine.get_golden_record(name_or_id)
                if not golden.get("error"):
                    return golden
            return load_entity_profile(name_or_id, self.knowledge_dir)


        name_lower = name_or_id.lower()
        for path in org_dir.iterdir():
            if path.suffix != ".json":
                continue
            try:
                with open(path) as f:
                    profile = json.load(f)
                if name_lower in profile.get("canonical_name", "").lower():
                    entity_id = profile.get("entity_id", "")
                    if self._engine:
                        golden = self._engine.get_golden_record(entity_id)
                        if not golden.get("error"):
                            return golden
                    return profile
            except (json.JSONDecodeError, OSError):
                continue
        return None

    def query_entity(self, name_or_id: str) -> dict | None:
        ""





        result = self.query_person(name_or_id)
        if result:
            return result


        result = self.query_organization(name_or_id)
        if result:
            return result


        for etype in ("deal", "commitment"):
            etype_dir = self.knowledge_dir / "entities" / etype
            if not etype_dir.exists():
                continue

            if name_or_id.startswith(f"{etype}_"):
                return load_entity_profile(name_or_id, self.knowledge_dir)

            name_lower = name_or_id.lower()
            for path in etype_dir.iterdir():
                if path.suffix != ".json":
                    continue
                try:
                    with open(path) as f:
                        profile = json.load(f)
                    if name_lower in profile.get("canonical_name", "").lower():
                        return profile
                except (json.JSONDecodeError, OSError):
                    continue

        return None

    def query_relationships(self, entity_name: str) -> list[dict]:
        ""
        person_dir = self.knowledge_dir / "entities" / "person"
        if not person_dir.exists():
            return []

        name_lower = entity_name.lower().strip()
        relationships = []

        for path in person_dir.iterdir():
            if path.suffix != ".json":
                continue
            try:
                with open(path) as f:
                    profile = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            for fact in profile.get("facts", []):
                val = str(fact.get("value", "")).lower()
                attr = fact.get("attribute", "")
                if name_lower in val and attr.startswith(("relationship.", "deep.")):
                    relationships.append(
                        {
                            "entity": profile.get("canonical_name", ""),
                            "entity_id": profile.get("entity_id", ""),
                            "attribute": attr,
                            "value": fact.get("value", ""),
                            "confidence": fact.get("confidence", 0),
                        }
                    )

        return relationships

    def _search_by_name(self, name: str) -> dict | None:
        ""
        name_lower = name.lower()
        for entity_type in ("person", "organization", "deal", "commitment"):
            etype_dir = self.knowledge_dir / "entities" / entity_type
            if not etype_dir.exists():
                continue
            for path in etype_dir.iterdir():
                if path.suffix != ".json":
                    continue
                try:
                    with open(path) as f:
                        profile = json.load(f)
                    if name_lower in profile.get("canonical_name", "").lower():
                        return profile
                except (json.JSONDecodeError, OSError):
                    continue
        return None





def collect_golden_record_changes(
    since: datetime, cluster_index_path: Path | None = None
) -> list[dict]:
    ""



    path = cluster_index_path or _DEFAULT_CLUSTER_INDEX
    if not path.exists():
        return []

    data = load_cluster_index(path)
    decisions = data.get("decisions", [])
    since_iso = since.isoformat()
    changes = []

    for dec in decisions:
        ts = dec.get("timestamp", "")
        if ts < since_iso or dec.get("status") != "active":
            continue

        action = dec.get("action", "")
        if action == "merge":
            changes.append(
                {
                    "type": "new_merge",
                    "entities": dec.get("entity_ids", []),
                    "confidence": dec.get("confidence", 0),
                    "method": dec.get("method", ""),
                }
            )
        elif action == "reject":
            changes.append(
                {
                    "type": "merge_retracted",
                    "entities": dec.get("entity_ids", []),
                    "retracted_id": dec.get("retracted_decision_id", ""),
                }
            )

    return changes
