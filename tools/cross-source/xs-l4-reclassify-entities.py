#!/usr/bin/env python3
""




















































from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import KNOWLEDGE_DIR, KNOWLEDGE_ENTITIES_DIR  # noqa: E402

log = logging.getLogger("sbk-l4-reclassify")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ORG_DIR = KNOWLEDGE_ENTITIES_DIR / "organization"
RECLASS_DIR = KNOWLEDGE_DIR / "reclassification"
REGISTRY_PATH = RECLASS_DIR / "gate0a-person-to-org.jsonl"
CANDIDATE_PATH = RECLASS_DIR / "gate0a-person-to-org.candidate.jsonl"











ACTIONABLE_TIERS = {"T1", "T1b", "dual-homed"}

DOCUMENTED_TIERS = {"T2", "T3", "compound-split", "placeholder"}






def _legal_suffixes() -> frozenset[str]:
    ""










    try:
        import sbk_config as _cfg

        return frozenset(_cfg.sigle_societarie())
    except Exception as e:  # pragma: no cover
        log.warning("vocabolario sigle non caricato (%s): resto sul presidio minimo", e)
        return frozenset({"srl", "llc", "gmbh", "spa", "bv", "llp", "ou", "ltd", "benefit"})


LEGAL_SUFFIXES: frozenset[str] = _legal_suffixes()


ORG_KEYWORDS: frozenset[str] = frozenset(
    {
        "group",
        "holding",
        "ventures",
        "capital",
        "studio",
        "agency",
        "media",
        "consulting",
        "software",
        "labs",
        "partners",
    }
)



_PLACEHOLDER_WORDS = (
    "company",
    "team",
    "speaker",
    "persona",
    "person",
    "participant",
    "unknown",
    "group",
    "contact",
    "guest",
    "caller",
    "host",
    "attendee",
    "user",
    "member",
    "interlocutor",
    "moderator",
    "azienda",
    "sconosciuto",
)
_PLACEHOLDER_RE = re.compile(r"^(?:" + "|".join(_PLACEHOLDER_WORDS) + r")\s*\d*$", re.IGNORECASE)
_COMPOUND_RE = re.compile(r"\s/\s")
_NUMERIC_RE = re.compile(r"^\d+$")





def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def alnum_key(name: str) -> str:
    ""






    if not name:
        return ""
    return "".join(ch for ch in _strip_accents(name.lower()) if ch.isalnum())


def _tokens(name: str) -> list[str]:
    ""
    no_dots = _strip_accents(name.lower()).replace(".", "")
    return [t for t in re.split(r"[^a-z0-9]+", no_dots) if t]





def is_compound(name: str) -> bool:
    return bool(_COMPOUND_RE.search(name))


def is_placeholder(name: str) -> bool:
    stripped = name.strip()
    if not stripped:
        return True
    if _NUMERIC_RE.match(stripped):
        return True
    return bool(_PLACEHOLDER_RE.match(stripped))


def detect_legal_suffix(name: str) -> str | None:
    ""




    toks = _tokens(name)
    if not toks:
        return None
    if toks[-1] in LEGAL_SUFFIXES:
        return toks[-1]
    if len(toks) >= 2 and toks[-2] in LEGAL_SUFFIXES:
        return toks[-2]
    return None


def detect_org_keyword(name: str) -> str | None:
    for t in _tokens(name):
        if t in ORG_KEYWORDS:
            return t
    return None


def classify(
    entity_id: str,
    canonical_name: str,
    n_facts: int,
    real_index: dict[str, str],
    contaminated_index: dict[str, str],
) -> dict | None:
    ""



    name = canonical_name or ""


    if is_compound(name):
        return _row(entity_id, None, "compound-split", name, n_facts, {"reason": "compound"})
    if is_placeholder(name):
        return _row(entity_id, None, "placeholder", name, n_facts, {"reason": "placeholder"})

    key = alnum_key(name)
    if key:
        target = real_index.get(key)
        if target is not None:
            return _row(
                entity_id,
                target,
                "T1",
                name,
                n_facts,
                {"match": "exact_alnum", "target_kind": "real_org"},
            )
        cont = contaminated_index.get(key)
        if cont is not None:
            return _row(
                entity_id,
                cont,
                "T1b",
                name,
                n_facts,
                {"match": "exact_alnum", "target_kind": "contaminated_person_in_org"},
            )

    suffix = detect_legal_suffix(name)
    if suffix is not None:
        return _row(
            entity_id,
            None,
            "T2",
            name,
            n_facts,
            {"legal_suffix": suffix, "target_kind": "to_coin"},
        )

    kw = detect_org_keyword(name)
    if kw is not None:
        return _row(
            entity_id,
            None,
            "T3",
            name,
            n_facts,
            {"org_keyword": kw, "status": "suspended_pending_decision"},
        )

    return None


def _row(
    person_id: str,
    target_org_id: str | None,
    tier: str,
    matched_name: str,
    n_facts: int,
    evidence: dict,
) -> dict:
    return {
        "person_id": person_id,
        "target_org_id": target_org_id,
        "tier": tier,
        "matched_name": matched_name,
        "n_facts": n_facts,
        "decided_at": datetime.now(UTC).isoformat(),
        "evidence": evidence,
    }





def _load_head(path: Path) -> dict | None:
    ""



    try:
        with path.open(encoding="utf-8") as fh:
            d = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    facts = d.get("facts")
    return {
        "entity_id": d.get("entity_id") or path.stem,
        "canonical_name": d.get("canonical_name", ""),
        "entity_type": d.get("entity_type", ""),
        "n_facts": len(facts) if isinstance(facts, list) else 0,
    }


def build_real_org_index(org_dir: Path) -> dict[str, str]:
    ""
    index: dict[str, str] = {}
    for p in sorted(org_dir.glob("*.json")):
        if p.name.startswith("person_"):
            continue
        head = _load_head(p)
        if head is None:
            continue
        key = alnum_key(head["canonical_name"])
        if key and key not in index:
            index[key] = head["entity_id"]
    return index


def build_contaminated_index(org_dir: Path) -> tuple[dict[str, str], list[dict]]:
    ""



    index: dict[str, str] = {}
    meta: list[dict] = []
    for p in sorted(org_dir.glob("person_*.json")):
        head = _load_head(p)
        if head is None:
            continue
        pid = head["entity_id"]
        key = alnum_key(head["canonical_name"])
        if key and key not in index:
            index[key] = pid
        meta.append(
            {
                "entity_id": pid,
                "canonical_name": head["canonical_name"],
                "n_facts": head["n_facts"],
            }
        )
    return index, meta




_G_REAL: dict[str, str] = {}
_G_CONT: dict[str, str] = {}
_G_DUAL: set[str] = set()


def _init_worker(real_index: dict, cont_index: dict, dual_set: set) -> None:
    global _G_REAL, _G_CONT, _G_DUAL
    _G_REAL = real_index
    _G_CONT = cont_index
    _G_DUAL = dual_set


def _process_chunk(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for sp in paths:
        p = Path(sp)
        head = _load_head(p)
        if head is None:
            continue
        eid = head["entity_id"]


        if eid in _G_DUAL:
            continue
        row = classify(eid, head["canonical_name"], head["n_facts"], _G_REAL, _G_CONT)
        if row is not None:
            rows.append(row)
    return rows


def _chunked(seq: list, n: int) -> list[list]:
    if n <= 1:
        return [seq]
    size = (len(seq) + n - 1) // n
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def scan_person_dir(
    person_dir: Path,
    real_index: dict[str, str],
    cont_index: dict[str, str],
    dual_set: set[str],
    workers: int,
) -> list[dict]:
    files = [str(p) for p in sorted(person_dir.glob("person_*.json"))]
    if not files:
        return []
    if workers <= 1:
        _init_worker(real_index, cont_index, dual_set)
        return _process_chunk(files)

    rows: list[dict] = []

    chunks = _chunked(files, workers * 8)
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(real_index, cont_index, dual_set),
    ) as ex:
        for part in ex.map(_process_chunk, chunks):
            rows.extend(part)
    return rows





def build_dual_homed_rows(cont_meta: list[dict], person_dir: Path) -> list[dict]:
    ""





    rows: list[dict] = []
    for m in cont_meta:
        pid = m["entity_id"]
        also_in_person = (person_dir / f"{pid}.json").exists()
        rows.append(
            _row(
                pid,
                pid,
                "dual-homed",
                m["canonical_name"],
                m["n_facts"],
                {
                    "location": "organization/",
                    "also_in_person": also_in_person,
                    "shadowed": also_in_person,
                },
            )
        )
    return rows





def build_report(rows: list[dict], n_person: int, n_real_org: int, n_cont: int) -> str:
    from collections import defaultdict

    by_tier_count: dict[str, int] = defaultdict(int)
    by_tier_facts: dict[str, int] = defaultdict(int)
    for r in rows:
        by_tier_count[r["tier"]] += 1
        by_tier_facts[r["tier"]] += r["n_facts"]

    dual = [r for r in rows if r["tier"] == "dual-homed"]
    dual_shadowed = sum(1 for r in dual if r["evidence"].get("shadowed"))

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("GATE 0a — Person→Org reclassification registry (DRY-RUN)")
    lines.append("=" * 72)
    lines.append(f"person/ scanned      : {n_person}")
    lines.append(f"real orgs (targets)  : {n_real_org}")
    lines.append(
        f"contaminated person_* in organization/: {n_cont} "
        f"(dual-homed {dual_shadowed} / org-only {len(dual) - dual_shadowed})"
    )
    lines.append("")
    lines.append("ACTIONABLE tiers (→ real registry):")
    for tier in ("T1", "T1b", "T2", "dual-homed"):
        lines.append(
            f"  {tier:<11}: {by_tier_count.get(tier, 0):>6} entities / "
            f"{by_tier_facts.get(tier, 0):>9,} facts"
        )
    lines.append("")
    lines.append("SUSPENDED (pending decision, listed only):")
    lines.append(
        f"  {'T3':<11}: {by_tier_count.get('T3', 0):>6} entities / "
        f"{by_tier_facts.get('T3', 0):>9,} facts"
    )
    lines.append("")
    lines.append("EXCLUDED (out of scope, marked):")
    for tier in ("placeholder", "compound-split"):
        lines.append(
            f"  {tier:<14}: {by_tier_count.get(tier, 0):>6} entities / "
            f"{by_tier_facts.get(tier, 0):>9,} facts"
        )
    lines.append("")


    ranked = sorted(
        (r for r in rows if r["tier"] in ACTIONABLE_TIERS or r["tier"] == "T3"),
        key=lambda r: r["n_facts"],
        reverse=True,
    )[:25]
    lines.append("TOP-25 candidates by n_facts (actionable + T3):")
    lines.append(f"  {'tier':<11} {'n_facts':>9}  {'entity_id':<22} {'target':<24} name")
    for r in ranked:
        target = r["target_org_id"] or "-"
        name = (r["matched_name"] or "")[:40]
        lines.append(
            f"  {r['tier']:<11} {r['n_facts']:>9,}  {r['person_id']:<22} {target:<24} {name}"
        )
    lines.append("=" * 72)
    return "\n".join(lines)





def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")





def run(
    person_dir: Path,
    org_dir: Path,
    workers: int,
    apply: bool,
    out_dir: Path | None = None,
) -> tuple[list[dict], str]:
    ""
    out_dir = out_dir or RECLASS_DIR
    log.info("building real-org target index from %s", org_dir)
    real_index = build_real_org_index(org_dir)
    cont_index, cont_meta = build_contaminated_index(org_dir)
    dual_set = {m["entity_id"] for m in cont_meta}
    log.info(
        "targets: %d real orgs, %d contaminated person_* files",
        len(real_index),
        len(cont_meta),
    )

    log.info("scanning %s with %d worker(s)…", person_dir, workers)
    person_rows = scan_person_dir(person_dir, real_index, cont_index, dual_set, workers)
    dual_rows = build_dual_homed_rows(cont_meta, person_dir)
    all_rows = person_rows + dual_rows

    n_person = sum(1 for _ in person_dir.glob("person_*.json"))
    report = build_report(all_rows, n_person, len(real_index), len(cont_meta))

    out_dir.mkdir(parents=True, exist_ok=True)
    if apply:
        registry_path = out_dir / REGISTRY_PATH.name
        actionable = [r for r in all_rows if r["tier"] in ACTIONABLE_TIERS]
        write_jsonl(actionable, registry_path)
        log.info("APPLY: wrote %d actionable rows → %s", len(actionable), registry_path)
    else:
        candidate_path = out_dir / CANDIDATE_PATH.name
        write_jsonl(all_rows, candidate_path)
        log.info("DRY-RUN: wrote %d candidate rows → %s", len(all_rows), candidate_path)

    return all_rows, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GATE 0a: build the person→org reclassification alias-registry."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Write the candidate registry + print report (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the REAL registry (actionable tiers). Requires explicit "
        "owner confirmation before running.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel workers for the person/ scan (default: 8).",
    )
    parser.add_argument(
        "--person-dir",
        type=Path,
        default=PERSON_DIR,
        help="Override person/ directory (tests).",
    )
    parser.add_argument(
        "--org-dir",
        type=Path,
        default=ORG_DIR,
        help="Override organization/ directory (tests).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    apply = bool(args.apply)
    _, report = run(args.person_dir, args.org_dir, max(1, args.workers), apply, RECLASS_DIR)
    print(report)


if __name__ == "__main__":
    main()
