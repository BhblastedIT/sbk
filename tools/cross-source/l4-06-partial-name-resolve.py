#!/usr/bin/env python3
"""L4-06: resolves person entities known only by a first name: to the full person through email, Slack, the CRM
or a name that is unique in the store, or reclassifies them as companies. Dry run by default; --apply merges.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd  # noqa: E402
from entity_dedup_index import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    ENRICHED_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    OWN_ORG_NAMES,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from journal_fusioni import Journal  # noqa: E402

log = logging.getLogger("sbk-l4-06")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ORG_DIR = KNOWLEDGE_ENTITIES_DIR / "organization"
ARCHIVE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "partial-resolved"
RUN_LOG = QUALITY_METRICS_DIR / "l4-06-run-log.jsonl"

ENTITY_MAP_FILE = ENRICHED_DIR / "entity-map.json"
CONTACTS_FILE = ENRICHED_DIR / "contacts-merged.parquet"
SLACK_USERS_FILE = DATA_ROOT / "slack" / "slack-users.json"
COMPANY_LISTS_FILE = DATA_ROOT / "common" / "company-lists.json"


# Minimal fallback set: public vendors plus your own organisations ("organisations" in
# sbk.config.json). Real company names are loaded from COMPANY_LISTS_FILE when it exists.
_KNOWN_COMPANIES_FALLBACK = set(OWN_ORG_NAMES) | {
    # public vendors
    "meta",
    "google",
    "facebook",
    "apple",
    "amazon",
    "microsoft",
    "tiktok",
    "shopify",
    "clickup",
    "docusign",
    "personio",
    "salesforce",
    "hubspot",
    "slack",
    "notion",
    "canva",
    "stripe",
    "paypal",
    "mailchimp",
}


def _load_company_names() -> set[str]:
    ""
    if COMPANY_LISTS_FILE.exists():
        try:
            data = json.loads(COMPANY_LISTS_FILE.read_text(encoding="utf-8"))
            return set(data.get("company_names", []))
        except (json.JSONDecodeError, OSError):
            pass
    return _KNOWN_COMPANIES_FALLBACK


KNOWN_COMPANIES = _load_company_names()





def load_entity_map() -> dict:
    ""
    if not ENTITY_MAP_FILE.exists():
        return {}
    return json.loads(ENTITY_MAP_FILE.read_text(encoding="utf-8"))


def load_contacts_merged() -> pd.DataFrame:
    ""
    if not CONTACTS_FILE.exists():
        return pd.DataFrame()
    return pd.read_parquet(CONTACTS_FILE)


def load_slack_users() -> dict[str, dict]:
    ""
    if not SLACK_USERS_FILE.exists():
        return {}
    data = json.loads(SLACK_USERS_FILE.read_text(encoding="utf-8"))
    result = {}
    users = data.values() if isinstance(data, dict) else data
    for u in users:
        display = (u.get("display_name") or u.get("name") or "").lower().strip()
        real_name = u.get("real_name") or u.get("name", "")
        email = u.get("email", "")
        if display:
            result[display] = {"real_name": real_name, "email": email}
    return result


_PID_TO_EID_CACHE: dict[str, tuple[str, str, Path]] | None = None


def build_pid_to_eid_index() -> dict[str, tuple[str, str, Path]]:
    ""




    global _PID_TO_EID_CACHE  # noqa: PLW0603
    if _PID_TO_EID_CACHE is not None:
        return _PID_TO_EID_CACHE


    name_to_entity: dict[str, tuple[str, str, Path]] = {}
    for f in PERSON_DIR.iterdir():
        if not f.name.endswith(".json") or f.name.startswith(("_", ".")):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            name = normalize_name(d.get("canonical_name", ""))
            if name:
                name_to_entity[name] = (d.get("entity_id", ""), d.get("canonical_name", ""), f)
        except (json.JSONDecodeError, OSError):
            continue


    entity_map = load_entity_map()
    pid_to_eid: dict[str, tuple[str, str, Path]] = {}
    for _key, entry in entity_map.items():
        pid = entry.get("person_id", "")
        name = normalize_name(entry.get("canonical_name", ""))
        if pid and name and name in name_to_entity:
            pid_to_eid[pid] = name_to_entity[name]

    log.info(
        "PID-to-EID index built: %d mappings from %d entity-map entries",
        len(pid_to_eid),
        len(entity_map),
    )
    _PID_TO_EID_CACHE = pid_to_eid
    return pid_to_eid


def find_entity_by_person_id(person_id: str) -> tuple[str, str] | None:
    ""
    index = build_pid_to_eid_index()
    if person_id in index:
        eid, name, _path = index[person_id]
        return (eid, name)
    return None


def find_entity_by_email(email: str) -> tuple[str, str, Path] | None:
    ""
    email_lower = email.strip().lower()
    entity_map = load_entity_map()


    if email_lower in entity_map:
        pid = entity_map[email_lower].get("person_id", "")
        name = entity_map[email_lower].get("canonical_name", "")
        result = find_entity_by_person_id(pid)
        if result:
            eid, ename = result
            path = PERSON_DIR / f"{eid}.json"
            if path.exists():
                return (eid, ename or name, path)

    return None


_NAME_TO_ENTITY_CACHE: dict[str, tuple[str, str, Path]] | None = None


def _build_name_index() -> dict[str, tuple[str, str, Path]]:
    ""
    global _NAME_TO_ENTITY_CACHE  # noqa: PLW0603
    if _NAME_TO_ENTITY_CACHE is not None:
        return _NAME_TO_ENTITY_CACHE

    index: dict[str, tuple[str, str, Path]] = {}
    for f in PERSON_DIR.iterdir():
        if not f.name.endswith(".json") or f.name.startswith(("_", ".")):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            name = normalize_name(d.get("canonical_name", ""))
            if name:
                index[name] = (d.get("entity_id", ""), d.get("canonical_name", ""), f)
        except (json.JSONDecodeError, OSError):
            continue

    _NAME_TO_ENTITY_CACHE = index
    return index


def find_entity_by_name(full_name: str) -> tuple[str, str, Path] | None:
    ""
    normalized = normalize_name(full_name)
    index = _build_name_index()
    return index.get(normalized)





def scan_single_word_entities() -> list[dict]:
    ""
    results = []
    for f in sorted(PERSON_DIR.iterdir()):
        if not f.name.endswith(".json") or f.name.startswith(("_", ".")):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("canonical_name", "").strip()
            if not name or " " in name:
                continue
            if name.startswith("person_"):
                continue

            facts = data.get("facts", [])
            emails = []
            source_types = set()
            for fact in facts:
                attr = fact.get("attribute", "")
                if attr in ("contact.email", "identity.email"):
                    emails.append(str(fact.get("value", "")).strip().lower())
                src = fact.get("source", {})
                if isinstance(src, dict):
                    st = src.get("source_type", "")
                    if st:
                        source_types.add(st)

            results.append(
                {
                    "entity_id": data.get("entity_id", ""),
                    "canonical_name": name,
                    "fact_count": len(facts),
                    "emails": list(set(e for e in emails if "@" in e)),
                    "source_types": list(source_types),
                    "is_lowercase": name == name.lower(),
                    "file_path": str(f),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    return results





def resolve_by_email(entity: dict, dry_run: bool) -> dict | None:
    ""
    if not entity["emails"]:
        return None

    for email in entity["emails"]:
        target = find_entity_by_email(email)
        if target:
            target_eid, target_name, target_path = target
            if target_eid == entity["entity_id"]:
                continue


            partial = normalize_name(entity["canonical_name"])
            full = normalize_name(target_name)
            if partial not in full:

                log.debug(
                    "SKIP email match: '%s' email=%s -> '%s' (name mismatch)",
                    entity["canonical_name"],
                    email,
                    target_name,
                )
                continue

            return {
                "method": "email_anchor",
                "source_entity": entity["entity_id"],
                "source_name": entity["canonical_name"],
                "target_entity": target_eid,
                "target_name": target_name,
                "signal": email,
                "confidence": 0.99,
            }
    return None


def resolve_by_slack(entity: dict, slack_users: dict, dry_run: bool) -> dict | None:
    ""
    if not entity["is_lowercase"]:
        return None
    if not any("slack" in st for st in entity["source_types"]):
        return None

    handle = entity["canonical_name"].lower()
    if handle not in slack_users:
        return None

    user = slack_users[handle]
    real_name = user.get("real_name", "")
    email = user.get("email", "")

    if not real_name or len(real_name) < 3:
        return None


    target = find_entity_by_name(real_name)
    if not target:
        if email:
            target = find_entity_by_email(email)
    if not target:
        return None

    target_eid, target_name, _ = target
    if target_eid == entity["entity_id"]:
        return None

    return {
        "method": "slack_handle",
        "source_entity": entity["entity_id"],
        "source_name": entity["canonical_name"],
        "target_entity": target_eid,
        "target_name": target_name,
        "signal": f"{handle} → {real_name} ({email})",
        "confidence": 0.98,
    }


def classify_as_company(entity: dict) -> dict | None:
    ""
    name_lower = entity["canonical_name"].lower()
    if name_lower in KNOWN_COMPANIES:
        return {
            "method": "company_reclassify",
            "source_entity": entity["entity_id"],
            "source_name": entity["canonical_name"],
            "target_entity": None,
            "target_name": None,
            "signal": "known_company",
            "confidence": 1.0,
        }
    return None





_CONTACTS_INDEX: dict[str, list[dict]] | None = None


def _build_contacts_index(contacts_df: pd.DataFrame) -> dict[str, list[dict]]:
    ""
    global _CONTACTS_INDEX  # noqa: PLW0603
    if _CONTACTS_INDEX is not None:
        return _CONTACTS_INDEX

    index: dict[str, list[dict]] = defaultdict(list)
    for _, row in contacts_df.iterrows():
        full = str(row.get("name", ""))
        if not full:
            continue
        full_norm = normalize_name(full)
        words = full_norm.split()
        pid = row.get("person_id", "")
        entry = {"name": full, "person_id": pid}
        for w in words:
            if len(w) >= 3:
                index[w].append(entry)

    log.info("Contacts index built: %d unique words from %d contacts", len(index), len(contacts_df))
    _CONTACTS_INDEX = dict(index)
    return _CONTACTS_INDEX










_COGNOMI_PER_NOME: dict[str, set[str]] | None = None


def _cognomi_nello_store(primo_nome: str) -> set[str]:
    ""





    global _COGNOMI_PER_NOME  # noqa: PLW0603
    if _COGNOMI_PER_NOME is None:
        acc: dict[str, set[str]] = {}
        for nome_norm in _build_name_index():


            if re.search(r"[,&/]|\s(?:e|and)\s", nome_norm):
                continue
            pezzi = re.sub(r"\(.*?\)", " ", nome_norm).split()
            if len(pezzi) < 2:
                continue



            acc.setdefault(pezzi[0], set()).add(pezzi[-1])
        _COGNOMI_PER_NOME = acc
    return _COGNOMI_PER_NOME.get(primo_nome, set())


def match_nome_atteso(m: dict) -> str:
    ""
    return str(m.get("name") or "?")


def resolve_by_crm(entity: dict, contacts_index: dict[str, list[dict]]) -> dict | None:
    ""
    if entity["emails"]:
        return None

    partial = normalize_name(entity["canonical_name"])
    if len(partial) < 3 or partial not in contacts_index:
        return None

    matches = contacts_index[partial]

    first_name_matches = [m for m in matches if normalize_name(m["name"]).split()[0] == partial]

    if len(first_name_matches) != 1:
        return None






    cognomi = _cognomi_nello_store(partial)
    if len(cognomi) > 1:
        log.warning(
            "'%s' NOT linked to '%s': the store has %d surnames for this first name (%s)",
            partial,
            match_nome_atteso(first_name_matches[0]),
            len(cognomi),
            ", ".join(sorted(cognomi)[:4]),
        )
        return None

    match = first_name_matches[0]
    result = find_entity_by_person_id(match["person_id"])
    if not result:
        target = find_entity_by_name(match["name"])
        if target:
            target_eid, target_name, _ = target
        else:
            return None
    else:
        target_eid, target_name = result

    if target_eid == entity["entity_id"]:
        return None

    return {
        "method": "crm_crossref",
        "source_entity": entity["entity_id"],
        "source_name": entity["canonical_name"],
        "target_entity": target_eid,
        "target_name": target_name,
        "signal": f"CRM match: '{partial}' in '{match['name']}'",
        "confidence": 0.90,
    }


def resolve_by_univocal_name(entity: dict, contacts_index: dict[str, list[dict]]) -> dict | None:
    ""
    partial = normalize_name(entity["canonical_name"])
    if len(partial) < 3 or partial not in contacts_index:
        return None


    matches = [
        m for m in contacts_index[partial] if normalize_name(m["name"]).split()[0] == partial
    ]

    if len(matches) == 1:
        target = find_entity_by_name(matches[0]["name"])
        if target:
            target_eid, target_name, _ = target
            if target_eid != entity["entity_id"]:
                return {
                    "method": "univocal_name",
                    "source_entity": entity["entity_id"],
                    "source_name": entity["canonical_name"],
                    "target_entity": target_eid,
                    "target_name": target_name,
                    "signal": f"univocal first-name '{partial}'",
                    "confidence": 0.95,
                }

    return None





def execute_merge(resolution: dict, dry_run: bool, journal=None) -> bool:
    ""
    if dry_run:
        return True

    src_path = PERSON_DIR / f"{resolution['source_entity']}.json"
    if not src_path.exists():
        return False

    src_data = json.loads(src_path.read_text(encoding="utf-8"))

    if resolution["method"] == "company_reclassify":

        ORG_DIR.mkdir(parents=True, exist_ok=True)
        src_data["entity_type"] = "organization"
        safe_write_json(ORG_DIR / src_path.name, src_data)
        src_path.unlink(missing_ok=True)
        return True


    target_path = PERSON_DIR / f"{resolution['target_entity']}.json"
    if not target_path.exists():
        return False

    target_data = json.loads(target_path.read_text(encoding="utf-8"))


    existing_keys = {
        (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
        for f in target_data.get("facts", [])
    }
    added = 0
    _tgt_id = target_data.get("entity_id", "")

    if journal is not None:
        journal.fusione(
            _tgt_id,
            resolution["source_entity"],
            motivo=f"{resolution['method']}: {resolution['signal']}",
            punteggi={"confidence": resolution.get("confidence")},
        )
    for fact in src_data.get("facts", []):
        key = (fact.get("attribute", ""), str(fact.get("value", "")).strip().lower())
        if key not in existing_keys:

            target_data["facts"].append(
                {**fact, "entity_id": _tgt_id, "source_entity_id": fact.get("entity_id")}
            )
            existing_keys.add(key)
            added += 1
            if journal is not None:
                journal.fatto(fact, da=resolution["source_entity"], a=_tgt_id)
        elif journal is not None:
            journal.fatto_scartato(
                fact, da=resolution["source_entity"], perche="duplicate (attribute,value)"
            )

    safe_write_json(target_path, target_data, backup=True)


    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive = {
        **src_data,
        "status": "resolved",
        "merged_into": resolution["target_entity"],
        "merged_date": datetime.now(UTC).isoformat(),
        "merged_by": f"l4-06-{resolution['method']}",
        "merge_signal": resolution["signal"],
        "merge_confidence": resolution["confidence"],
    }
    safe_write_json(ARCHIVE_DIR / src_path.name, archive)
    src_path.unlink(missing_ok=True)

    return True





def main():
    parser = argparse.ArgumentParser(description="L4-06: Partial Name Resolution")
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2],
        help="Phase to run (1=deterministic, 2=high confidence)",
    )
    parser.add_argument("--apply", action="store_true", help="Execute (default: dry-run)")
    parser.add_argument("--stats", action="store_true", help="Show category stats only")
    parser.add_argument("--sample", type=int, default=20, help="Show N sample resolutions")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    dry_run = not args.apply

    log.info("Scanning single-word entities...")
    entities = scan_single_word_entities()
    log.info("Found %d single-word entities", len(entities))

    if args.stats:
        has_email = sum(1 for e in entities if e["emails"])
        is_slack = sum(
            1
            for e in entities
            if e["is_lowercase"] and any("slack" in s for s in e["source_types"])
        )
        is_company = sum(1 for e in entities if e["canonical_name"].lower() in KNOWN_COMPANIES)
        log.info("  With email: %d", has_email)
        log.info("  Slack handle: %d", is_slack)
        log.info("  Company/brand: %d", is_company)
        log.info("  Other: %d", len(entities) - has_email - is_slack - is_company)
        return

    if not args.phase:
        log.error("Specify --phase 1 or --phase 2")
        return

    slack_users = load_slack_users() if args.phase == 1 else {}
    contacts_index: dict[str, list[dict]] = {}
    if args.phase == 2:
        contacts_df = load_contacts_merged()
        if not contacts_df.empty:
            contacts_index = _build_contacts_index(contacts_df)

    log.info("=" * 70)
    log.info("L4-06 Phase %d — %s", args.phase, "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 70)

    resolutions = []
    ambigui = 0

    for entity in entities:
        result = None

        if args.phase == 1:
            result = resolve_by_email(entity, dry_run)
            if not result:
                result = resolve_by_slack(entity, slack_users, dry_run)
            if not result:
                result = classify_as_company(entity)

        elif args.phase == 2:







            cognomi = _cognomi_nello_store(normalize_name(entity["canonical_name"]))
            if len(cognomi) > 1:
                log.warning(
                    "'%s' NOT resolved: the store has %d surnames for this first name (%s)",
                    entity["canonical_name"],
                    len(cognomi),
                    ", ".join(sorted(cognomi)[:4]),
                )
                ambigui += 1
                continue
            result = resolve_by_crm(entity, contacts_index)
            if not result:
                result = resolve_by_univocal_name(entity, contacts_index)

        if result:
            resolutions.append(result)


    log.info("Resolutions found: %d", len(resolutions))
    if ambigui:
        log.info(
            "Stopped at the gate (several surnames for the same first name): %d. Not a failure,"
            " it is the difference between a name and a person",
            ambigui,
        )
    for _shown_idx, r in enumerate(resolutions[: args.sample]):
        if r["method"] == "company_reclassify":
            log.info(
                '  RECLASSIFY: "%s" → organization (%s)',
                r["source_name"],
                r["signal"],
            )
        else:
            log.info(
                '  %s: "%s" → "%s" [%s] (conf=%.2f)',
                r["method"].upper(),
                r["source_name"],
                r["target_name"],
                r["signal"][:50],
                r["confidence"],
            )

    if len(resolutions) > args.sample:
        log.info("  ... and %d more", len(resolutions) - args.sample)


    if not dry_run:
        executed = 0

        with Journal("l4-06-partial-name-resolve") as journal:
            for r in resolutions:
                if execute_merge(r, dry_run=False, journal=journal):
                    executed += 1
            log.info("Executed: %d/%d", executed, len(resolutions))
            if journal.percorso:
                log.info("merge journal: %s", journal.percorso)
                log.info(
                    "to undo: xs-l4-disfa-fusione.py --journal %s --apply",
                    journal.percorso.name,
                )


        merged_eids = {
            r["source_entity"] for r in resolutions if r.get("method") != "company_reclassify"
        }
        if merged_eids and ENTITY_MAP_FILE.exists():
            em = json.loads(ENTITY_MAP_FILE.read_text(encoding="utf-8"))
            before = len(em)

            pid_to_eid = build_pid_to_eid_index()
            merged_pids = set()
            for pid, (eid, _name, _path) in pid_to_eid.items():
                if eid in merged_eids:
                    merged_pids.add(pid)

            cleaned = {k: v for k, v in em.items() if v.get("person_id") not in merged_pids}
            removed = before - len(cleaned)
            if removed > 0:
                safe_write_json(ENTITY_MAP_FILE, cleaned, backup=True)
                log.info("Entity-map cleanup: removed %d orphaned entries", removed)


        global _PID_TO_EID_CACHE, _NAME_TO_ENTITY_CACHE  # noqa: PLW0603
        _PID_TO_EID_CACHE = None
        _NAME_TO_ENTITY_CACHE = None


        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            for r in resolutions:
                r["timestamp"] = datetime.now(UTC).isoformat()
                r["module"] = f"l4-06-phase{args.phase}"
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


    by_method = defaultdict(int)
    for r in resolutions:
        by_method[r["method"]] += 1

    log.info("")
    log.info("=" * 70)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    for method, count in sorted(by_method.items()):
        log.info("  %s: %d", method, count)
    log.info("  Total: %d resolutions", len(resolutions))
    if dry_run:
        log.info("  Run with --apply to execute.")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
