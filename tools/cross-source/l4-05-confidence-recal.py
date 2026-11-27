#!/usr/bin/env python3
"""L4-05: recalibrates the confidence of every fact in the knowledge base: boosts facts confirmed by independent
sources, detects contradictions (written to knowledge/conflicts/), applies source-tier floors and caps and the
decay of old facts. Dry run by default; --apply writes.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    KNOWLEDGE_ENTITIES_DIR,
    OWN_ORG_ALIASES,
    OWN_ORG_NAMES,
    QUALITY_METRICS_DIR,
    acquire_pid_lock,
    safe_write_json,
)

log = logging.getLogger("sbk-l4-05-confidence-recal")



PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
CONFLICTS_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "conflicts"
RUN_LOG = QUALITY_METRICS_DIR / "l4-05-run-log.jsonl"
LAST_RUN_FILE = KNOWLEDGE_ENTITIES_DIR.parent / ".recal-last-run"



SOURCE_TIER: dict[str, int] = {

    "linkedin": 1,
    "personio": 1,
    "docusign": 1,
    "manual_input": 1,
    "manual_merge": 1,

    "email": 2,
    "whatsapp": 2,
    "slack": 2,
    "attio": 2,
    "plaud": 2,
    "calendar": 2,
    "static_import": 2,

    "tactiq": 3,
    "notion": 3,
    "chatgpt": 3,
    "gdrive": 3,
    "deep_facts": 3,
    "relationship_facts": 3,

    "inferred": 4,
    "unknown": 4,
    "static": 4,
}

DEFAULT_TIER = 4



UNIQUE_ATTRS: set[str] = {
    "employment.company",
    "employment.subcompany",
    "employment.manager_email",
    "relationship.role",
    "relationship.title",
    "contact.linkedin_url",
}



_COMPANY_LISTS_FILE = DATA_ROOT / "common" / "company-lists.json"


# Your own group of companies and their abbreviations: "organisations" in sbk.config.json
# (names, aliases), unless <data root>/common/company-lists.json lists them. Empty by default.
_OWN_GROUP_FALLBACK: set[str] = set(OWN_ORG_NAMES)

_ABBREVIATION_MAP_FALLBACK: dict[str, str] = {
    k.lower(): v.lower() for k, v in OWN_ORG_ALIASES.items()
} | {v.lower(): v.lower() for v in OWN_ORG_ALIASES.values()}


def _load_conflict_config() -> tuple[set[str], dict[str, str]]:
    ""
    if _COMPANY_LISTS_FILE.exists():
        try:
            data = json.loads(_COMPANY_LISTS_FILE.read_text(encoding="utf-8"))
            group = set(data.get("own_group", []))
            abbrev_raw = data.get("abbreviation_map", {})

            abbrev: dict[str, str] = {}
            for k, v in abbrev_raw.items():
                abbrev[k.lower()] = v.lower()
                abbrev[v.lower()] = v.lower()
            return (
                group if group else _OWN_GROUP_FALLBACK,
                abbrev if abbrev else _ABBREVIATION_MAP_FALLBACK,
            )
        except (json.JSONDecodeError, OSError):
            pass
    return _OWN_GROUP_FALLBACK, _ABBREVIATION_MAP_FALLBACK


OWN_GROUP, _ABBREVIATION_MAP = _load_conflict_config()



_COMPANY_SUFFIXES = {
    "capital",
    "ventures",
    "vc",
    "partners",
    "sgr",
    "fund",
    "consulting",
    "pro",
    "group",
    "holding",
    "inc",
    "ltd",
    "llc",
    "gmbh",
    "s.r.l.",
    "srl",
    "s.p.a.",
    "spa",
    "ag",
}

_NON_COMPANY_LABELS: set[str] = {
    "angel investor",
    "freelance",
    "freelancer",
    "consultant",
    "self-employed",
    "independent",
    "n/a",
    "none",
    "unknown",
}



DECAY_MONTHS = 6



_WS_RE = re.compile(r"\s+")


def normalize_value(v: str) -> str:
    ""
    if v is None or isinstance(v, list | dict):
        return ""
    return _WS_RE.sub(" ", str(v).strip().lower())


def normalize_company_value(v: str) -> str:
    ""




    s = normalize_value(v)
    if not s:
        return s


    if s in _NON_COMPANY_LABELS:
        return ""


    s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s).strip()


    for sep in (" -- ", " — "):
        if sep in s:
            s = s.split(sep)[0].strip()


    if s in _ABBREVIATION_MAP:
        s = _ABBREVIATION_MAP[s]


    words = s.split()
    if len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        s = " ".join(words[:-1])

    return s


def _is_same_company_group(nv1: str, nv2: str) -> bool:
    ""
    c1 = normalize_company_value(nv1)
    c2 = normalize_company_value(nv2)
    return c1 in OWN_GROUP and c2 in OWN_GROUP


def _is_equivalent_company(nv1: str, nv2: str) -> bool:
    ""
    c1 = normalize_company_value(nv1)
    c2 = normalize_company_value(nv2)
    if not c1 or not c2:
        return True
    if c1 == c2:
        return True

    if c1.replace(" ", "") == c2.replace(" ", ""):
        return True
    return False


def get_source_type(fact: dict) -> str:
    ""
    src = fact.get("source")
    if isinstance(src, dict):
        raw = src.get("source_type") or "unknown"
    elif isinstance(src, str):
        raw = src
    else:
        raw = "unknown"
    return raw.lower()


def get_tier(fact: dict) -> int:
    ""
    return SOURCE_TIER.get(get_source_type(fact), DEFAULT_TIER)


def _parse_dt(s: str | None) -> datetime | None:
    ""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def is_expired(fact: dict) -> bool:
    ""
    return fact.get("expired_at") is not None





def dedup_facts(facts: list[dict]) -> list[dict]:
    ""




    expired = [f for f in facts if is_expired(f)]
    live = [f for f in facts if not is_expired(f)]

    best: dict[tuple[str, str, str], dict] = {}
    for f in live:
        key = (
            f.get("attribute", ""),
            normalize_value(f.get("value", "")),
            get_source_type(f),
        )
        existing = best.get(key)
        if existing is None or f.get("confidence", 0) > existing.get("confidence", 0):
            best[key] = f

    return list(best.values()) + expired





def group_facts(facts: list[dict]) -> dict[tuple[str, str], list[dict]]:
    ""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in facts:
        if is_expired(f):
            continue
        key = (f.get("attribute", ""), normalize_value(f.get("value", "")))
        groups[key].append(f)
    return dict(groups)





def count_independent_sources(facts: list[dict]) -> int:
    ""








    provs: set[tuple] = set()
    has_obs = False
    for f in facts:
        obs = f.get("observations") or []
        if obs:
            has_obs = True
            for o in obs:
                rid = o.get("record_id")
                if rid:
                    provs.add((o.get("source_file"), rid))
    if has_obs:
        return max(1, len(provs))
    return len({get_source_type(f) for f in facts})


def apply_confirmation_boost(facts: list[dict]) -> list[dict]:
    ""




    n_sources = count_independent_sources(facts)
    result = []
    for f in facts:
        conf = f.get("confidence", 0.5)
        if n_sources >= 3:

            conf = min(0.95, conf + 0.15)
        elif n_sources == 2:

            conf = min(0.90, conf + 0.10)
        result.append({**f, "confidence": round(conf, 2)})
    return result





def detect_contradictions(
    entity_id: str,
    entity_name: str,
    facts: list[dict],
) -> tuple[list[dict], list[dict]]:
    ""




    by_attr: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        if is_expired(f):
            continue
        by_attr[f.get("attribute", "")].append(f)

    conflict_entries: list[dict] = []
    penalised_fact_ids: set[str] = set()

    for attr, attr_facts in by_attr.items():
        if attr not in UNIQUE_ATTRS:
            continue


        is_company_attr = attr in ("employment.company", "employment.subcompany")
        by_value: dict[str, list[dict]] = defaultdict(list)
        for f in attr_facts:
            nv = normalize_value(f.get("value", ""))
            if not nv:
                continue
            by_value[nv].append(f)

        if len(by_value) < 2:
            continue


        values_list = list(by_value.keys())
        for i in range(len(values_list)):
            for j in range(i + 1, len(values_list)):
                v1, v2 = values_list[i], values_list[j]


                if is_company_attr:
                    if _is_same_company_group(v1, v2):
                        continue
                    if _is_equivalent_company(v1, v2):
                        continue

                for f in by_value[v1] + by_value[v2]:
                    penalised_fact_ids.add(f.get("fact_id", ""))

                hint = _compute_hint(by_value[v1], by_value[v2], v1, v2)
                conflict_entries.append(
                    {
                        "entity_id": entity_id,
                        "entity_name": entity_name,
                        "attribute": attr,
                        "values": [
                            _conflict_value_entry(by_value[v1]),
                            _conflict_value_entry(by_value[v2]),
                        ],
                        "hint": hint,
                    }
                )


    updated = []
    for f in facts:
        if f.get("fact_id", "") in penalised_fact_ids:
            conf = max(0.1, f.get("confidence", 0.5) - 0.2)
            updated.append({**f, "confidence": round(conf, 2), "conflict": True})
        else:
            updated.append(f)

    return updated, conflict_entries


def _conflict_value_entry(facts: list[dict]) -> dict:
    ""

    best = max(facts, key=lambda f: f.get("confidence", 0))
    return {
        "value": best.get("value", ""),
        "source_type": get_source_type(best),
        "confidence": best.get("confidence", 0.5),
        "created_at": best.get("created_at", ""),
    }


def _compute_hint(facts_a: list[dict], facts_b: list[dict], nv_a: str, nv_b: str) -> str:
    ""

    dates_a = [_parse_dt(f.get("created_at")) for f in facts_a]
    dates_b = [_parse_dt(f.get("created_at")) for f in facts_b]
    dates_a = [d for d in dates_a if d is not None]
    dates_b = [d for d in dates_b if d is not None]

    if dates_a and dates_b:
        earliest_a = min(dates_a)
        latest_b = max(dates_b)
        earliest_b = min(dates_b)
        latest_a = max(dates_a)
        gap = max(abs((latest_a - earliest_b).days), abs((latest_b - earliest_a).days))
        if gap > 180:
            return "possible_job_change"


    tiers_a = {get_tier(f) for f in facts_a}
    tiers_b = {get_tier(f) for f in facts_b}
    if (1 in tiers_a and 4 in tiers_b) or (1 in tiers_b and 4 in tiers_a):
        return "likely_outdated"


    try:
        from rapidfuzz import fuzz

        if fuzz.ratio(nv_a, nv_b) >= 80:
            return "possible_typo"
    except ImportError:
        pass

    return "needs_review"





def apply_tier_floor_cap(facts: list[dict], confirmation_counts: dict[str, int]) -> list[dict]:
    ""




    result = []
    for f in facts:
        if is_expired(f):
            result.append(f)
            continue

        tier = get_tier(f)
        conf = f.get("confidence", 0.5)
        fid = f.get("fact_id", "")
        n_sources = confirmation_counts.get(fid, 1)

        if tier == 1:
            conf = max(0.7, conf)
        elif tier == 2:
            conf = max(0.5, conf)
        elif tier == 3:
            conf = max(0.3, conf)
        elif tier == 4:
            if n_sources <= 1:
                conf = min(0.5, conf)

        result.append({**f, "confidence": round(conf, 2)})
    return result





def apply_temporal_decay(facts: list[dict], now: datetime | None = None) -> list[dict]:
    ""




    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(days=DECAY_MONTHS * 30)


    confirm_map: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    for f in facts:
        if is_expired(f):
            continue
        dt = _parse_dt(f.get("created_at"))
        if dt:
            key = (f.get("attribute", ""), normalize_value(f.get("value", "")))
            confirm_map[key].append((dt, get_source_type(f)))

    result = []
    for f in facts:
        if is_expired(f):
            result.append(f)
            continue

        dt = _parse_dt(f.get("created_at"))
        if dt is None or dt >= cutoff:

            result.append(f)
            continue


        key = (f.get("attribute", ""), normalize_value(f.get("value", "")))
        src_type = get_source_type(f)
        has_recent = any(
            cdt >= cutoff and csrc != src_type for cdt, csrc in confirm_map.get(key, [])
        )
        if has_recent:
            result.append(f)
            continue


        conf = f.get("confidence", 0.5) * 0.7
        conf = max(0.1, round(conf, 2))
        result.append({**f, "confidence": conf})

    return result





def load_entity(path: Path) -> dict | None:
    ""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", path.name, exc)
        return None


def get_entity_paths(full: bool = False) -> list[Path]:
    ""
    if not PERSON_DIR.exists():
        return []

    all_paths = sorted(
        p for p in PERSON_DIR.iterdir() if p.name.endswith(".json") and not p.name.startswith("_")
    )

    if full or not LAST_RUN_FILE.exists():
        return all_paths

    last_run_ts = LAST_RUN_FILE.stat().st_mtime
    return [p for p in all_paths if p.stat().st_mtime > last_run_ts]


def recalibrate_entity(
    data: dict,
    *,
    dry_run: bool = True,
    conflicts_only: bool = False,
) -> tuple[dict, list[dict], dict]:
    ""



    entity_id = data.get("entity_id", "unknown")
    entity_name = data.get("canonical_name", "unknown")
    original_facts = data.get("facts", [])
    stats: dict = {
        "entity_id": entity_id,
        "facts_before": len(original_facts),
        "deduped": 0,
        "boosted": 0,
        "penalised": 0,
        "decayed": 0,
        "tier_adjusted": 0,
        "conflicts": 0,
    }


    expired = [f for f in original_facts if is_expired(f)]
    live = [f for f in original_facts if not is_expired(f)]


    deduped = dedup_facts(live)
    stats["deduped"] = len(live) - len(deduped)

    if conflicts_only:

        _, conflict_entries = detect_contradictions(entity_id, entity_name, deduped)
        stats["conflicts"] = len(conflict_entries)
        return data, conflict_entries, stats


    groups = group_facts(deduped)
    boosted_facts: list[dict] = []
    confirmation_counts: dict[str, int] = {}
    expired_from_dedup = [f for f in deduped if is_expired(f)]

    for (_attr, _nv), group_facts_list in groups.items():
        n_sources = count_independent_sources(group_facts_list)
        boosted = apply_confirmation_boost(group_facts_list)
        for orig, new in zip(group_facts_list, boosted):
            if new.get("confidence", 0) > orig.get("confidence", 0):
                stats["boosted"] += 1
            confirmation_counts[new.get("fact_id", "")] = n_sources
        boosted_facts.extend(boosted)


    boosted_facts.extend(expired_from_dedup)


    post_conflict, conflict_entries = detect_contradictions(entity_id, entity_name, boosted_facts)
    stats["conflicts"] = len(conflict_entries)
    stats["penalised"] = sum(1 for f in post_conflict if f.get("conflict"))


    post_tier = apply_tier_floor_cap(post_conflict, confirmation_counts)
    for orig, new in zip(post_conflict, post_tier):
        if new.get("confidence", 0) != orig.get("confidence", 0):
            stats["tier_adjusted"] += 1


    post_decay = apply_temporal_decay(post_tier)
    for orig, new in zip(post_tier, post_decay):
        if new.get("confidence", 0) < orig.get("confidence", 0):
            stats["decayed"] += 1


    final_facts = post_decay + expired

    stats["facts_after"] = len(final_facts)

    updated = {
        **data,
        "facts": final_facts,
        "updated_at": datetime.now(UTC).isoformat(),
        "version": data.get("version", 1) + 1,
    }

    return updated, conflict_entries, stats


def recalibrate_entity_stepped(
    data: dict,
    *,
    dry_run: bool = True,
    step: str = "all",
) -> tuple[dict, list[dict], dict]:
    ""



    if step == "all":
        return recalibrate_entity(data, dry_run=dry_run, conflicts_only=False)
    if step == "conflicts":
        return recalibrate_entity(data, dry_run=dry_run, conflicts_only=True)

    entity_id = data.get("entity_id", "unknown")
    entity_name = data.get("canonical_name", "unknown")
    original_facts = data.get("facts", [])
    expired = [f for f in original_facts if is_expired(f)]
    live = [f for f in original_facts if not is_expired(f)]
    stats: dict = {
        "entity_id": entity_id,
        "facts_before": len(original_facts),
        "deduped": 0,
        "boosted": 0,
        "penalised": 0,
        "decayed": 0,
        "tier_adjusted": 0,
        "conflicts": 0,
    }

    if step == "dedup":
        deduped = dedup_facts(live)
        stats["deduped"] = len(live) - len(deduped)
        final_facts = deduped + expired
    elif step == "boost_tier":

        groups = group_facts(live)
        boosted_facts: list[dict] = []
        confirmation_counts: dict[str, int] = {}
        for (_attr, _nv), gfl in groups.items():
            n_src = count_independent_sources(gfl)
            boosted = apply_confirmation_boost(gfl)
            for orig, new in zip(gfl, boosted):
                if new.get("confidence", 0) > orig.get("confidence", 0):
                    stats["boosted"] += 1
                confirmation_counts[new.get("fact_id", "")] = n_src
            boosted_facts.extend(boosted)
        post_tier = apply_tier_floor_cap(boosted_facts, confirmation_counts)
        for orig, new in zip(boosted_facts, post_tier):
            if new.get("confidence", 0) != orig.get("confidence", 0):
                stats["tier_adjusted"] += 1
        final_facts = post_tier + expired
    else:
        return data, [], stats

    stats["facts_after"] = len(final_facts)
    updated = {
        **data,
        "facts": final_facts,
        "updated_at": datetime.now(UTC).isoformat(),
        "version": data.get("version", 1) + 1,
    }
    return updated, [], stats


def run(
    *,
    full: bool = False,
    dry_run: bool = True,
    conflicts_only: bool = False,
    verbose: bool = False,
    step: str = "all",
    limit: int | None = None,
) -> dict:
    ""



    if not dry_run and not acquire_pid_lock("l4-05-recal", logger=log):
        log.error("Another instance is already running. Aborting.")
        return {"error": "pid_lock_failed"}

    paths = get_entity_paths(full=full)
    if limit is not None and limit > 0:
        paths = paths[:limit]
    total = len(paths)
    log.info("Entities to process: %d (%s mode)", total, "full" if full else "incremental")

    all_conflicts: list[dict] = []
    agg: dict = {
        "entities_processed": 0,
        "entities_modified": 0,
        "total_deduped": 0,
        "total_boosted": 0,
        "total_penalised": 0,
        "total_decayed": 0,
        "total_tier_adjusted": 0,
        "total_conflicts": 0,
    }

    for i, path in enumerate(paths):
        data = load_entity(path)
        if data is None:
            continue

        if step != "all" and not conflicts_only:
            updated, conflicts, stats = recalibrate_entity_stepped(data, dry_run=dry_run, step=step)
        else:
            updated, conflicts, stats = recalibrate_entity(
                data, dry_run=dry_run, conflicts_only=conflicts_only
            )
        agg["entities_processed"] += 1
        agg["total_deduped"] += stats["deduped"]
        agg["total_boosted"] += stats["boosted"]
        agg["total_penalised"] += stats["penalised"]
        agg["total_decayed"] += stats["decayed"]
        agg["total_tier_adjusted"] += stats["tier_adjusted"]
        agg["total_conflicts"] += stats["conflicts"]

        if conflicts:
            all_conflicts.extend(conflicts)

        entity_modified = (
            stats["deduped"] > 0
            or stats["boosted"] > 0
            or stats["penalised"] > 0
            or stats["decayed"] > 0
            or stats["tier_adjusted"] > 0
        )
        if entity_modified:
            agg["entities_modified"] += 1

        if not dry_run and not conflicts_only and entity_modified:
            safe_write_json(path, updated, backup=True)

        if verbose and entity_modified:
            log.info(
                "  %s: dedup=%d boost=%d penalty=%d decay=%d tier=%d conflicts=%d",
                data.get("canonical_name", data.get("entity_id", "?")),
                stats["deduped"],
                stats["boosted"],
                stats["penalised"],
                stats["decayed"],
                stats["tier_adjusted"],
                stats["conflicts"],
            )

        if (i + 1) % 5000 == 0:
            log.info("  Progress: %d/%d entities", i + 1, total)


    if all_conflicts:
        CONFLICTS_DIR.mkdir(parents=True, exist_ok=True)
        conflict_data = {
            "generated": datetime.now(UTC).isoformat(),
            "conflicts": all_conflicts,
        }
        if not dry_run:
            safe_write_json(CONFLICTS_DIR / "recal-conflicts.json", conflict_data)
        log.info("Conflicts detected: %d", len(all_conflicts))


    if not dry_run and not conflicts_only:
        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        run_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "module": "l4-05-confidence-recal",
            "mode": "full" if full else "incremental",
            **agg,
        }
        with open(RUN_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(run_entry, ensure_ascii=False) + "\n")


        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")

    return agg





def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="L4-05: Confidence Recalibration with multi-source cross-validation"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Process ALL entities (default: incremental since last run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show changes without writing (default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (disables dry-run)",
    )
    parser.add_argument(
        "--conflicts-only",
        action="store_true",
        help="Only detect and log conflicts, don't recalibrate",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose per-entity logging",
    )
    parser.add_argument(
        "--step",
        choices=["dedup", "boost_tier", "conflicts", "all"],
        default="all",
        help="Run only a specific step (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N entities",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    dry_run = not args.apply
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )



























    _PASSI_CHE_SCRIVONO = {"dedup", "boost_tier", "decay", "all", None, ""}
    if args.apply and not args.conflicts_only and args.step in _PASSI_CHE_SCRIVONO:
        log.error(
            "ABORT: «%s» rewrites the confidence, which belongs to score() "
            "in the extractor, and is not reversible (the journal counts the facts, it does "
            "not name them: a past mass deletion is tracked only by a count).\n"
            "  Open: --step conflicts (does not touch the entities).\n"
            "  To reopen it you need: a journal with the fact_ids, and a single owner "
            "of the confidence.",
            args.step or "all steps",
        )
        raise SystemExit(2)

    mode = "DRY RUN" if dry_run else "LIVE"
    if args.conflicts_only:
        mode += " (conflicts only)"
    log.info("=" * 60)
    log.info("L4-05 Confidence Recalibration -- %s", mode)
    log.info("=" * 60)

    agg = run(
        full=args.full,
        dry_run=dry_run,
        conflicts_only=args.conflicts_only,
        verbose=args.verbose,
        step=args.step,
        limit=args.limit,
    )

    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Entities processed:  %d", agg["entities_processed"])
    log.info("  Entities modified:   %d", agg["entities_modified"])
    log.info("  Facts deduped:       %d", agg["total_deduped"])
    log.info("  Facts boosted:       %d", agg["total_boosted"])
    log.info("  Facts penalised:     %d", agg["total_penalised"])
    log.info("  Facts decayed:       %d", agg["total_decayed"])
    log.info("  Tier adjustments:    %d", agg["total_tier_adjusted"])
    log.info("  Conflicts detected:  %d", agg["total_conflicts"])
    if dry_run:
        log.info("  Run with --apply to execute.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
