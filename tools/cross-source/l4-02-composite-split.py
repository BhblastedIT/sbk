#!/usr/bin/env python3
""






















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from entity_dedup_index import EntityDedupIndex, is_composite, normalize_name  # noqa: E402
from knowledge_schema import generate_entity_id  # noqa: E402

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    KNOWLEDGE_ENTITIES_DIR,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

log = logging.getLogger("sbk-l4-02-composite-split")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ARCHIVE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "split"
RUN_LOG = QUALITY_METRICS_DIR / "l4-02-run-log.jsonl"
COMPANY_LISTS_FILE = DATA_ROOT / "common" / "company-lists.json"



_COMPANY_WORDS_FALLBACK = {
    "srl",
    "s.r.l",
    "spa",
    "s.p.a",
    "ltd",
    "inc",
    "llc",
    "gmbh",
    "ag",
    "team",
    "group",
    "holding",
    "partners",
    "capital",
    "ventures",
    "fund",
    "consortium",
    "sector",
    "industry",
    "finance",
}


def _load_company_words() -> set[str]:
    ""
    if COMPANY_LISTS_FILE.exists():
        try:
            data = json.loads(COMPANY_LISTS_FILE.read_text(encoding="utf-8"))
            return set(data.get("company_names", [])) | set(data.get("company_suffixes", []))
        except (json.JSONDecodeError, OSError):
            pass
    return _COMPANY_WORDS_FALLBACK


_COMPANY_WORDS = _load_company_words()

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")




_ROLE_WORDS = {
    "management",
    "operations",
    "consultants",
    "consultant",
    "notary",
    "support",
    "sales",
    "marketing",
    "finance",
    "legal",
    "admin",
    "administration",
    "staff",
    "client",
    "clients",
    "supplier",
    "suppliers",
    "vendor",
    "vendors",
    "agency",
    "hr",
    "cx",
    "it",
    "ceo",
    "cfo",
    "cao",
    "cto",
    "coo",
    "director",
    "directors",
    "assistant",
    "board",
    "committee",
    "partners",
    "investors",
    "advisors",
    "team",
    "teams",
    "department",
    "office",
    "reception",
    "security",
}
_ROLE_FILLERS = {
    "the",
    "a",
    "an",
    "new",
    "potential",
    "external",
    "internal",
    "of",
    "and",
    "&",
    "commercial",
    "senior",
    "junior",
}


def _e_solo_ruolo(part: str) -> bool:
    words = [w for w in re.split(r"[\s/&,-]+", part.lower()) if w]
    if not words:
        return False
    sostanza = [w for w in words if w not in _ROLE_FILLERS]
    return bool(sostanza) and all(w in _ROLE_WORDS for w in sostanza)


def is_likely_company_or_noise(name: str) -> bool:
    ""
    lower = name.strip().lower()
    if not lower or len(lower) < 2:
        return True
    if _EMAIL_RE.search(lower):
        return True
    if lower.startswith("(") or lower.startswith("unnamed"):
        return True
    words = set(lower.split())
    if words & _COMPANY_WORDS:
        return True

    if name.strip().isupper() and len(name.strip()) > 3:
        return True
    if _e_solo_ruolo(name):
        return True
    return False





_SPLIT_PATTERNS = [
    re.compile(r"\s*,\s*"),
    re.compile(r"\s*/\s*"),
    re.compile(r"\s+&\s+"),
    re.compile(r"\s+and\s+", re.I),
    re.compile(r"\s+e\s+(?=[A-Z])"),
]





CLASSI_OSTILI = {"NON-PERSONA", "NOME-SPORCO"}


def classe_entita(data: dict) -> str | None:
    ""


    for fact in data.get("facts", []):
        if (fact.get("attribute") or fact.get("predicate")) == "identity.classe":
            return fact.get("value") or fact.get("object")
    return None


def split_composite_name(name: str) -> list[str]:
    ""








    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", name)
    if m and any(pat.search(m.group(2)) for pat in _SPLIT_PATTERNS):
        name = f"{m.group(1)}, {m.group(2)}" if m.group(1).strip() else m.group(2)


    for pattern in _SPLIT_PATTERNS:
        if pattern.search(name):
            parts = pattern.split(name)
            break
    else:
        return [name]


    candidates = []
    for part in parts:
        part = part.strip()

        part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()

        if part.count("(") != part.count(")"):
            part = part.replace("(", " ").replace(")", " ").strip()
            part = re.sub(r"\s{2,}", " ", part)
        if not part:
            continue
        if is_likely_company_or_noise(part):
            continue
        candidates.append(part)

    return candidates





def attribute_fact(fact: dict, candidates: list[str]) -> str | None:
    ""



    value = str(fact.get("value", "")).lower()
    attribute = fact.get("attribute", "")


    if attribute.startswith("identity."):
        for c in candidates:
            if normalize_name(c) in normalize_name(value):
                return c
        return None


    if attribute.startswith("contact."):
        for c in candidates:

            first = c.split()[0].lower() if c.split() else ""
            if first and first in value:
                return c
        return None


    for c in candidates:
        c_lower = normalize_name(c)
        first_name = c_lower.split()[0] if c_lower.split() else ""
        if first_name and len(first_name) >= 3 and first_name in value.lower():
            return c


    return None





def process_composite(
    entity_data: dict,
    entity_path: Path,
    dedup_index: EntityDedupIndex,
    dry_run: bool = True,
    rename_only: bool = False,
) -> dict | None:
    ""




    if not entity_path.exists():
        return None

    name = entity_data.get("canonical_name", "")
    entity_id = entity_data.get("entity_id", "")
    facts = entity_data.get("facts", [])

    candidates = split_composite_name(name)


    if len(candidates) < 1:
        return None


    if len(candidates) == 1:
        if not dry_run:
            entity_data["canonical_name"] = candidates[0]
            safe_write_json(entity_path, entity_data)
        return {
            "action": "rename",
            "original_name": name,
            "new_name": candidates[0],
            "entity_id": entity_id,
            "facts_count": len(facts),
        }


    if rename_only:
        return {"action": "skipped-split", "original_name": name, "entity_id": entity_id}
    attribution = {c: [] for c in candidates}
    unresolved = []

    for fact in facts:
        target = attribute_fact(fact, candidates)
        if target and target in attribution:
            attribution[target].append(fact)
        else:

            unresolved.append(fact)


    target_entities = {}
    for c in candidates:
        result = dedup_index.find_existing_entity(c)
        if result:
            target_entities[c] = result[0]
        else:
            target_entities[c] = generate_entity_id("person", c)

    if dry_run:
        return {
            "action": "split",
            "original_name": name,
            "original_id": entity_id,
            "candidates": candidates,
            "target_ids": target_entities,
            "facts_attributed": {c: len(fs) for c, fs in attribution.items()},
            "facts_unresolved": len(unresolved),
            "total_facts": len(facts),
            "dry_run": True,
        }


    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for c in candidates:
        target_id = target_entities[c]
        target_path = PERSON_DIR / f"{target_id}.json"


        if target_path.exists():
            target_data = json.loads(target_path.read_text(encoding="utf-8"))
        else:
            target_data = {
                "entity_id": target_id,
                "entity_type": "person",
                "canonical_name": c,
                "facts": [],
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": "l4-02-composite-split",
            }


        existing_keys = {
            (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
            for f in target_data.get("facts", [])
        }
        added = 0
        for fact in attribution[c] + unresolved:
            key = (fact.get("attribute", ""), str(fact.get("value", "")).strip().lower())
            if key not in existing_keys:




                moved = {**fact, "entity_id": target_id, "source_entity_id": fact.get("entity_id")}
                if fact in unresolved:
                    moved["shared"] = True
                target_data["facts"].append(moved)
                existing_keys.add(key)
                added += 1

        safe_write_json(target_path, target_data)


    archive_data = {
        **entity_data,
        "status": "split",
        "split_into": list(target_entities.values()),
        "split_date": datetime.now(UTC).isoformat(),
        "split_by": "l4-02-composite-split",
        "split_candidates": candidates,
    }
    safe_write_json(ARCHIVE_DIR / entity_path.name, archive_data)


    entity_path.unlink(missing_ok=True)

    return {
        "action": "split",
        "original_name": name,
        "original_id": entity_id,
        "candidates": candidates,
        "target_ids": target_entities,
        "facts_attributed": {c: len(fs) for c, fs in attribution.items()},
        "facts_unresolved": len(unresolved),
        "total_facts": len(facts),
        "dry_run": False,
    }





def main():
    parser = argparse.ArgumentParser(description="L4-02: Composite Entity Split")
    parser.add_argument("--apply", action="store_true", help="Execute splits (default: dry-run)")
    parser.add_argument(
        "--limit", type=int, default=0, help="Process only first N composites (pilot)"
    )
    parser.add_argument("--stats", action="store_true", help="Show composite stats only")
    parser.add_argument(
        "--rename-only",
        action="store_true",
        help="Only rename the single-candidate ones (Stage 1, zero split/copies)",
    )
    parser.add_argument(
        "--senza-dedup",
        action="store_true",
        help=(
            "do NOT run l4-03 on the renamed names. ⚠️ Use it only knowing that "
            "there remain namesakes to merge by hand: see the block below."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    dry_run = not args.apply

    log.info("=" * 60)
    log.info("L4-02 Composite Split — %s", "DRY RUN" if dry_run else "LIVE")
    if args.limit:
        log.info("  Limit: %d entities (pilot)", args.limit)
    log.info("=" * 60)


    log.info("Scanning for composite entities...")
    composites = []
    skip_classe = 0
    for f in sorted(PERSON_DIR.iterdir()):
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("canonical_name", "")
            if not is_composite(name):
                continue



            if classe_entita(data) in CLASSI_OSTILI:
                skip_classe += 1
                continue
            composites.append((f, data))
        except (json.JSONDecodeError, OSError):
            continue

    log.info(
        "Found %d composite entities (excluded %d marked NON-PERSONA/NOME-SPORCO)",
        len(composites),
        skip_classe,
    )

    if args.stats:

        from collections import Counter

        patterns = Counter()
        for _, data in composites:
            name = data.get("canonical_name", "")
            candidates = split_composite_name(name)
            person_candidates = [c for c in candidates if not is_likely_company_or_noise(c)]
            if len(person_candidates) >= 2:
                patterns["2+ persons"] += 1
            elif len(person_candidates) == 1:
                patterns["1 person (rename)"] += 1
            else:
                patterns["0 persons (skip)"] += 1

        for p, c in patterns.most_common():
            log.info("  %s: %d", p, c)
        return

    if args.limit:
        composites = composites[: args.limit]


    dedup_index = EntityDedupIndex()


    results = []
    splits = 0
    renames = 0
    skipped = 0

    for entity_path, entity_data in composites:
        result = process_composite(
            entity_data, entity_path, dedup_index, dry_run=dry_run, rename_only=args.rename_only
        )
        if result is None:
            skipped += 1
            continue
        results.append(result)
        if result["action"] == "split":
            splits += 1
        elif result["action"] == "rename":
            renames += 1


    if results and not dry_run:
        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            for r in results:
                r["timestamp"] = datetime.now(UTC).isoformat()
                r["module"] = "l4-02-composite-split"
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


    total_facts_unresolved = sum(
        r.get("facts_unresolved", 0) for r in results if r.get("action") == "split"
    )
    total_facts = sum(r.get("total_facts", 0) for r in results)

    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Composites processed: %d", len(results))
    log.info("  Splits: %d", splits)
    log.info("  Renames: %d", renames)
    log.info("  Skipped: %d", skipped)
    log.info("  Total facts processed: %d", total_facts)
    log.info("  Unresolved facts (shared): %d", total_facts_unresolved)
    if dry_run:
        log.info("")
        log.info("  Run with --apply to execute. Use --limit 200 for pilot.")
    log.info("=" * 60)









    if renames and not dry_run:
        nomi = sorted(
            {
                normalize_name(r.get("new_name", ""))
                for r in results
                if r.get("action") == "rename" and r.get("new_name")
            }
        )
        if args.senza_dedup:
            log.warning(
                "⚠️  %d renames applied and dedup NOT run (--senza-dedup): up to "
                "%d names remain with more than one entity. Close by hand with:\n"
                "    uv run python tools/cross-source/l4-03-exact-dedup.py --apply --nomi <list.json>",
                renames,
                len(nomi),
            )
            return
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(nomi, fh)
            elenco = fh.name
        log.info("")
        log.info("=" * 60)
        log.info("L4-03 on the %d renamed names (the single block, per the spec)", len(nomi))
        log.info("=" * 60)
        esito = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "l4-03-exact-dedup.py"),
                "--apply",
                "--nomi",
                elenco,
            ],
            check=False,
        )
        Path(elenco).unlink(missing_ok=True)
        if esito.returncode != 0:
            log.error(
                "l4-03 exited with %d: the renames are applied but the namesakes are NOT "
                "merged. Do not leave the store this way: rerun l4-03 --apply --nomi",
                esito.returncode,
            )
            sys.exit(esito.returncode)


if __name__ == "__main__":
    main()
