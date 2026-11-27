#!/usr/bin/env python3
"""Cleans up the knowledge-base profiles whose name is just their id: gives them the best name found in their facts;
without one, profiles with useful facts are moved to an archive folder and empty ones are deleted (profiles in a
merge cluster are left alone). Dry run by default; --apply writes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config as cfg  # noqa: E402

log = logging.getLogger("sbk.cleanup-nameless")


def _looks_like_hash(name: str) -> bool:
    ""
    if len(name) < 40:
        return False
    clean = name.replace("person_", "").replace("org_", "")
    return len(clean) >= 40 and all(c in "0123456789abcdef" for c in clean[:40])


def _load_cluster_member_ids(knowledge_dir: Path) -> set[str]:
    ""
    cluster_path = knowledge_dir / "entity-clusters.json"
    if not cluster_path.exists():
        return set()
    try:
        data = json.loads(cluster_path.read_text())
    except (json.JSONDecodeError, OSError):
        return set()

    member_ids: set[str] = set()
    for cluster_info in data.get("clusters", {}).values():
        for member in cluster_info.get("members", []):
            eid = member.get("entity_id", "")
            if eid:
                member_ids.add(eid)
    return member_ids


def _best_identity_name(profile: dict) -> str | None:
    ""
    best_name = None
    best_conf = -1.0
    for fact in profile.get("facts", []):
        if fact.get("attribute") != "identity.name":
            continue
        if fact.get("expired_at"):
            continue
        val = fact.get("value", "")
        if not val or not isinstance(val, str) or _looks_like_hash(val):
            continue
        conf = fact.get("confidence", 0.0)
        if conf > best_conf:
            best_conf = conf
            best_name = val.strip()
    return best_name


def _has_useful_facts(profile: dict) -> bool:
    ""
    for fact in profile.get("facts", []):
        if fact.get("expired_at"):
            continue
        val = fact.get("value")
        if val is not None and str(val).strip():
            return True
    return False


def cleanup_nameless_profiles(
    knowledge_dir: Path | None = None,
    apply: bool = False,
) -> dict:
    ""



    knowledge_dir = knowledge_dir or cfg.KNOWLEDGE_DIR
    person_dir = knowledge_dir / "entities" / "person"
    archive_dir = knowledge_dir / ".nameless-archive"

    if not person_dir.exists():
        log.warning("Person directory not found: %s", person_dir)
        return {
            "fixed": 0,
            "archived": 0,
            "in_cluster_skipped": 0,
            "deleted": 0,
            "total_nameless": 0,
        }

    cluster_member_ids = _load_cluster_member_ids(knowledge_dir)

    counts = {
        "fixed": 0,
        "archived": 0,
        "in_cluster_skipped": 0,
        "deleted": 0,
        "total_nameless": 0,
    }

    for path in sorted(person_dir.iterdir()):
        if path.suffix != ".json":
            continue

        try:
            profile = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        entity_id = profile.get("entity_id", "")
        canonical_name = profile.get("canonical_name", "")


        if canonical_name != entity_id:
            continue

        counts["total_nameless"] += 1


        best_name = _best_identity_name(profile)
        if best_name:
            log.info("FIX: %s → %s", entity_id[:20], best_name)
            if apply:
                profile["canonical_name"] = best_name
                path.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
            counts["fixed"] += 1
            continue


        if entity_id in cluster_member_ids:
            log.info("SKIP (in cluster): %s", entity_id[:20])
            counts["in_cluster_skipped"] += 1
            continue


        if _has_useful_facts(profile):
            log.info("ARCHIVE: %s (%d facts)", entity_id[:20], len(profile.get("facts", [])))
            if apply:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / path.name
                shutil.move(str(path), str(dest))
            counts["archived"] += 1
        else:
            log.info("DELETE: %s (no useful facts)", entity_id[:20])
            if apply:
                os.remove(path)
            counts["deleted"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup nameless profiles (canonical_name == entity_id)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually write changes (default: dry-run)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    mode = "APPLY" if args.apply else "DRY-RUN"
    log.info("=== Nameless Profile Cleanup [%s] ===", mode)

    counts = cleanup_nameless_profiles(apply=args.apply)

    log.info("=== Summary ===")
    log.info("Total nameless: %d", counts["total_nameless"])
    log.info("  Fixed (identity.name found): %d", counts["fixed"])
    log.info("  In cluster (skipped): %d", counts["in_cluster_skipped"])
    log.info("  Archived: %d", counts["archived"])
    log.info("  Deleted: %d", counts["deleted"])

    if not args.apply and counts["total_nameless"] > 0:
        log.info("Run with --apply to execute changes.")


if __name__ == "__main__":
    main()
