#!/usr/bin/env python3
"""Organization entities from employment facts: creates or completes the organizations people work for, normalising
the names of your own organisations. Dry run by default; --apply writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("sbk.org-enrich")


# Alias -> canonical name of your own organisations ("organisations.aliases" in
# sbk.config.json, e.g. {"dco": "Demo Co Ltd"}). Empty by default.
COMPANY_ALIASES: dict[str, str] = {k.lower(): v for k, v in cfg.OWN_ORG_ALIASES.items()}


def _normalize_company_name(name: str) -> str:
    ""
    clean = name.strip()
    if not clean:
        return ""
    lower = clean.lower()
    if lower in COMPANY_ALIASES:
        return COMPANY_ALIASES[lower]
    return clean


def _generate_org_entity_id(name: str) -> str:
    ""
    h = hashlib.sha256(name.lower().strip().encode()).hexdigest()[:16]
    return f"org_{h}"


def _load_existing_org_profiles(knowledge_dir: Path) -> dict[str, dict]:
    ""
    org_dir = knowledge_dir / "entities" / "organization"
    profiles: dict[str, dict] = {}
    if not org_dir.exists():
        return profiles
    for path in org_dir.iterdir():
        if path.suffix != ".json":
            continue
        try:
            profile = json.loads(path.read_text())
            name = profile.get("canonical_name", "").lower().strip()
            if name:
                profiles[name] = profile
        except (json.JSONDecodeError, OSError):
            continue
    return profiles


def _make_fact(entity_id: str, attribute: str, value, confidence: float = 0.6) -> dict:
    ""
    now = datetime.now(UTC).isoformat()
    return {
        "fact_id": f"f:org-enrich:{uuid.uuid4().hex[:12]}",
        "entity_id": entity_id,
        "entity_type": "organization",
        "attribute": attribute,
        "value": value,
        "confidence": confidence,
        "valid_from": now,
        "valid_to": None,
        "created_at": now,
        "expired_at": None,
        "source": {
            "source_type": "org_enrichment",
            "source_file": "xs-l2-org-enrich.py",
            "record_id": "",
            "extracted_at": now,
        },
        "superseded_by": None,
    }


def scan_employment_facts(knowledge_dir: Path) -> dict[str, dict]:
    ""






    person_dir = knowledge_dir / "entities" / "person"
    if not person_dir.exists():
        return {}

    companies: dict[str, dict] = defaultdict(
        lambda: {"members": [], "sources": set(), "entity_ids": []}
    )

    for path in person_dir.iterdir():
        if path.suffix != ".json":
            continue
        try:
            profile = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        person_name = profile.get("canonical_name", "")
        person_id = profile.get("entity_id", "")

        for fact in profile.get("facts", []):
            if fact.get("expired_at"):
                continue
            attr = fact.get("attribute", "")
            if attr not in ("employment.company", "employment.subcompany"):
                continue
            val = fact.get("value", "")
            if not val or not isinstance(val, str):
                continue

            normalized = _normalize_company_name(val)
            if not normalized:
                continue

            key = normalized.lower()
            info = companies[key]
            info["canonical_name"] = normalized

            if person_name and person_name not in info["members"]:
                info["members"].append(person_name)
            if person_id and person_id not in info["entity_ids"]:
                info["entity_ids"].append(person_id)

            source_type = fact.get("source", {}).get("source_type", "")
            if source_type:
                info["sources"].add(source_type)

    return dict(companies)


def enrich_organizations(
    knowledge_dir: Path | None = None,
    apply: bool = False,
) -> dict:
    ""



    knowledge_dir = knowledge_dir or cfg.KNOWLEDGE_DIR
    org_dir = knowledge_dir / "entities" / "organization"


    companies = scan_employment_facts(knowledge_dir)
    if not companies:
        log.info("No employment facts found.")
        return {"created": 0, "enriched": 0, "skipped": 0}


    existing = _load_existing_org_profiles(knowledge_dir)

    counts = {"created": 0, "enriched": 0, "skipped": 0}

    for company_key, info in sorted(companies.items()):
        canonical_name = info.get("canonical_name", company_key)
        members = info.get("members", [])
        sources = info.get("sources", set())

        if company_key in existing:

            profile = existing[company_key]
            entity_id = profile.get("entity_id", "")
            existing_attrs = {
                f.get("attribute") for f in profile.get("facts", []) if not f.get("expired_at")
            }

            new_facts = []
            if "organization.team_size" not in existing_attrs:
                new_facts.append(_make_fact(entity_id, "organization.team_size", len(members)))
            if "organization.team_members" not in existing_attrs and members:
                new_facts.append(_make_fact(entity_id, "organization.team_members", members[:20]))
            if "organization.sources" not in existing_attrs and sources:
                new_facts.append(_make_fact(entity_id, "organization.sources", sorted(sources)))

            if not new_facts:
                counts["skipped"] += 1
                continue

            log.info("ENRICH: %s (+%d facts)", canonical_name, len(new_facts))
            if apply:
                profile["facts"].extend(new_facts)
                profile["updated_at"] = datetime.now(UTC).isoformat()
                profile["version"] = profile.get("version", 1) + 1
                path = org_dir / f"{entity_id}.json"
                path.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
            counts["enriched"] += 1
        else:

            entity_id = _generate_org_entity_id(canonical_name)
            now = datetime.now(UTC).isoformat()

            facts = [
                _make_fact(entity_id, "identity.name", canonical_name, confidence=0.9),
                _make_fact(entity_id, "organization.team_size", len(members)),
            ]
            if members:
                facts.append(_make_fact(entity_id, "organization.team_members", members[:20]))
            if sources:
                facts.append(_make_fact(entity_id, "organization.sources", sorted(sources)))

            profile = {
                "entity_id": entity_id,
                "entity_type": "organization",
                "canonical_name": canonical_name,
                "facts": facts,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }

            log.info(
                "CREATE: %s (team_size=%d, sources=%s)",
                canonical_name,
                len(members),
                sorted(sources),
            )
            if apply:
                org_dir.mkdir(parents=True, exist_ok=True)
                path = org_dir / f"{entity_id}.json"
                path.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
            counts["created"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Enrich organization entities from employment facts"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually write changes (default: dry-run)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    mode = "APPLY" if args.apply else "DRY-RUN"
    log.info("=== Organization Enrichment [%s] ===", mode)

    counts = enrich_organizations(apply=args.apply)

    log.info("=== Summary ===")
    log.info("  Created: %d", counts["created"])
    log.info("  Enriched: %d", counts["enriched"])
    log.info("  Skipped: %d", counts["skipped"])

    if not args.apply and (counts["created"] + counts["enriched"]) > 0:
        log.info("Run with --apply to execute changes.")


if __name__ == "__main__":
    main()
