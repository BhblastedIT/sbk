#!/usr/bin/env python3
"""L4, run by hand: compacts repeated readings of the same source row into one observation per fact (dry run unless --apply)."""





















































from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from knowledge_schema import (  # noqa: E402  (path bootstrap must precede import)
    FactObservation,
    FactSource,
    dict_to_fact,
    fact_to_dict,
)

from sbk_config import (  # noqa: E402
    KNOWLEDGE_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_META_DIR,
    safe_write_json,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xs-l4-compact")






MEGA_ORG_PLACEHOLDER_IDS: frozenset[str] = frozenset(
    {
        "person_00000000",
        "person_00000000",
        "person_00000000",
        "person_00000000",
        "person_00000000",
    }
)

DEFAULT_GATE0A_REGISTRY = KNOWLEDGE_DIR / "reclassification" / "gate0a-person-to-org.jsonl"




def normalize_value(value) -> str:
    ""
    return str(value).strip().lower() if value is not None else ""





def expand_observations(fact) -> list[FactObservation]:
    ""





    if fact.observations:
        return list(fact.observations)
    return [
        FactObservation(
            source_file=fact.source.source_file,
            record_id=fact.source.record_id,
            source_type=fact.source.source_type,
            valid_from=fact.valid_from,
            extracted_at=fact.source.extracted_at,
            confidence=fact.confidence,
            confidence_curve=[fact.confidence],
        )
    ]





@dataclass
class EntityStats:
    facts_before: int = 0
    facts_after: int = 0
    typeA_collapsed: int = 0
    typeB_observations: int = 0
    absorbed_fact_ids: int = 0
    passthrough_empty_rid: int = 0


@dataclass
class FoldResult:
    new_facts: list[dict]
    changed: bool
    stats: EntityStats
    sidecar: list[dict] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)


def compact_entity(entity_id: str, fact_dicts: list[dict], want_samples: int = 0) -> FoldResult:
    ""




    stats = EntityStats(facts_before=len(fact_dicts))


    passthrough: list[dict] = []
    eligible: list[tuple] = []
    for fd in fact_dicts:
        src = fd.get("source") or {}
        rid = src.get("record_id", "") or ""
        if not rid:

            passthrough.append(fd)
            stats.passthrough_empty_rid += 1
            continue
        fact = dict_to_fact(fd)
        eligible.append((fact, fd, list(fd.get("merged_fact_ids", []))))








    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for fact, fd, em in eligible:
        groups[(fact.entity_id, fact.attribute, normalize_value(fact.value))].append((fact, fd, em))

    out: list[dict] = list(passthrough)
    sidecar: list[dict] = []
    samples: list[dict] = []

    for (eid_g, attr, nval), members in groups.items():

        for fact, _fd, _em in members:
            assert fact.entity_id == eid_g, (
                f"cross-entity merge blocked: {fact.entity_id} != {eid_g}"
            )
            assert fact.attribute == attr, "cross-attribute merge blocked"
            assert normalize_value(fact.value) == nval, "cross-value merge blocked"




        l1: dict[tuple, list[FactObservation]] = defaultdict(list)
        for fact, _fd, _em in members:
            for obs in expand_observations(fact):


                assert obs.record_id, (
                    f"observation with empty record_id on an anchored fact "
                    f"({entity_id}/{attr}) — NULL invariant violated"
                )
                l1[(obs.source_file, obs.record_id)].append(obs)

        observations: list[FactObservation] = []
        collapsed_reads = 0
        for (sf, rid), obss in l1.items():

            assert all(o.source_file == sf and o.record_id == rid for o in obss)
            rep = max(obss, key=lambda o: o.confidence)
            curve = sorted(c for o in obss for c in (o.confidence_curve or [o.confidence]))
            collapsed_reads += len(obss) - 1
            observations.append(
                FactObservation(
                    source_file=sf,
                    record_id=rid,
                    source_type=rep.source_type,
                    valid_from=rep.valid_from,
                    extracted_at=rep.extracted_at,
                    confidence=rep.confidence,
                    confidence_curve=curve,
                )
            )


        members_sorted = sorted(members, key=lambda m: (m[0].created_at or "", m[0].fact_id))
        base_fact, base_fd, _base_em = members_sorted[0]
        survivor_id = base_fact.fact_id



        merged: set[str] = set()
        for fact, _fd, em in members:
            merged.update(em)
            if fact.fact_id != survivor_id:
                merged.add(fact.fact_id)
        merged.discard(survivor_id)

        had_observations = any(m[1].get("observations") for m in members)
        is_trivial = (
            len(members) == 1
            and len(observations) == 1
            and len(observations[0].confidence_curve) <= 1
            and not merged
            and not had_observations
        )
        if is_trivial:

            out.append(base_fd)
            continue

        stats.typeA_collapsed += collapsed_reads
        if len(observations) > 1:
            stats.typeB_observations += len(observations)



        rep_obs = max(observations, key=lambda o: o.confidence)
        survivor = dict_to_fact(base_fd)
        survivor.observations = observations
        survivor.confidence = rep_obs.confidence
        survivor.valid_from = rep_obs.valid_from





        _src_base = survivor.source
        survivor.source = FactSource(
            source_type=rep_obs.source_type,
            source_file=rep_obs.source_file,
            record_id=rep_obs.record_id,
            extracted_at=rep_obs.extracted_at,
            attio_record_id=_src_base.attio_record_id if _src_base else None,
            attio_web_url=_src_base.attio_web_url if _src_base else None,
        )
        sd = fact_to_dict(survivor)
        if merged:
            sd["merged_fact_ids"] = sorted(merged)
            stats.absorbed_fact_ids += len(merged)
        out.append(sd)

        for fact, _fd, _em in members:
            if fact.fact_id != survivor_id:
                sidecar.append({"old_fact_id": fact.fact_id, "surviving_fact_id": survivor_id})

        if want_samples and len(samples) < want_samples:
            samples.append(
                {
                    "entity_id": entity_id,
                    "attribute": attr,
                    "norm_value": nval,
                    "before": [fact_to_dict(m[0]) for m in members],
                    "after": sd,
                }
            )

    stats.facts_after = len(out)



    old_norm = json.dumps(
        sorted(fact_dicts, key=lambda x: x.get("fact_id", "")),
        sort_keys=True,
        default=str,
    )
    new_norm = json.dumps(
        sorted(out, key=lambda x: x.get("fact_id", "")), sort_keys=True, default=str
    )
    changed = old_norm != new_norm

    return FoldResult(new_facts=out, changed=changed, stats=stats, sidecar=sidecar, samples=samples)





def load_skip_set(registry_path: Path) -> set[str]:
    ""
    skip: set[str] = set(MEGA_ORG_PLACEHOLDER_IDS)
    if registry_path and registry_path.exists():
        with open(registry_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("person_id") or row.get("entity_id")
                if pid:
                    skip.add(pid)
    return skip


def process_file(path: Path, skip: set[str], apply: bool, want_samples: int) -> FoldResult | None:
    ""



    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)

    entity_id = profile.get("entity_id") or path.stem
    if entity_id in skip:
        return None

    fact_dicts = profile.get("facts", [])
    if not fact_dicts:
        return None

    result = compact_entity(entity_id, fact_dicts, want_samples=want_samples)

    if apply and result.changed:

        profile["facts"] = sorted(result.new_facts, key=lambda x: x.get("fact_id", ""))
        safe_write_json(path, profile, backup=True)

    return result


def make_backup(ts: str) -> Path:
    ""



    backups_dir = KNOWLEDGE_DIR.parent / "backups-compaction"
    backups_dir.mkdir(parents=True, exist_ok=True)
    archive = backups_dir / f"knowledge-precompact-{ts}.tar.gz"
    log.info("Backup: tar of %s → %s", KNOWLEDGE_DIR, archive)
    tar = subprocess.run(
        [
            "tar",
            "-czf",
            str(archive),
            "-C",
            str(KNOWLEDGE_DIR.parent),
            KNOWLEDGE_DIR.name,
        ],
        capture_output=True,
        text=True,
    )
    if tar.returncode != 0:
        raise RuntimeError(f"tar failed: {(tar.stderr or '').strip()}")
    verify = subprocess.run(["gzip", "-t", str(archive)], capture_output=True, text=True)
    if verify.returncode != 0:
        raise RuntimeError(f"gzip -t FAILED on {archive}: {(verify.stderr or '').strip()} — abort")
    log.info("Backup verified (gzip -t OK): %s", archive)
    return archive


def iter_entity_files(entities_dir: Path, etypes: list[str], entity_id: str | None):
    ""
    if entity_id:
        for et in etypes:
            p = entities_dir / et / f"{entity_id}.json"
            if p.exists():
                yield p
                return

        for et in etypes:
            d = entities_dir / et
            if d.is_dir():
                for p in d.glob(f"{entity_id}.json"):
                    yield p
        return
    for et in etypes:
        d = entities_dir / et
        if not d.is_dir():
            continue
        yield from sorted(d.glob("*.json"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Mutates the store. DEFAULT off (dry-run). Requires a verified backup.",
    )
    ap.add_argument("--workers", type=int, default=6, help="Per-file parallelism.")
    ap.add_argument("--sample", type=int, default=0, help="Number of before/after diffs to dump.")
    ap.add_argument(
        "--sample-out",
        type=Path,
        default=None,
        help="File to write the samples to (default: <data root>/samples/compaction-sample-<time>.json).",
    )
    ap.add_argument(
        "--etypes",
        default="person",
        help="Entity subdirs (csv). Default 'person'. E.g. 'person,organization'.",
    )
    ap.add_argument("--entity-id", default=None, help="Compact a single profile (validation).")
    ap.add_argument(
        "--entities-dir",
        type=Path,
        default=KNOWLEDGE_ENTITIES_DIR,
        help="Entities root (default: real store).",
    )
    ap.add_argument(
        "--gate0a-registry",
        type=Path,
        default=DEFAULT_GATE0A_REGISTRY,
        help="GATE 0a person→org registry (entities to skip).",
    )
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N files.")
    ap.add_argument(
        "--include-megaorg",
        action="store_true",
        help="ALSO compact the mega-orgs (your largest organisations) that are normally skipped. "
        "Safe: grouping is by (entity_id,attribute,value), no identity merge; "
        "it does not affect GATE 0a reclassification (which concerns where the profile lives).",
    )
    args = ap.parse_args()

    etypes = [e.strip() for e in args.etypes.split(",") if e.strip()]
    skip = set() if args.include_megaorg else load_skip_set(args.gate0a_registry)
    log.info(
        "Mode=%s  etypes=%s  workers=%d  skip=%d entities",
        "APPLY" if args.apply else "DRY-RUN",
        etypes,
        args.workers,
        len(skip),
    )

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


    if args.apply:
        make_backup(ts)

    files = list(iter_entity_files(args.entities_dir, etypes, args.entity_id))
    if args.limit:
        files = files[: args.limit]
    log.info("Profiles to process: %d", len(files))


    tot = EntityStats()
    files_changed = 0
    files_skipped = 0
    errors: list[tuple[str, str]] = []
    entity_reduction: list[tuple[str, int]] = []
    collected_samples: list[dict] = []

    sidecar_path = KNOWLEDGE_META_DIR / f"compaction-map-{ts}.jsonl"
    sidecar_lock = threading.Lock()
    sidecar_fh = None
    if args.apply:
        KNOWLEDGE_META_DIR.mkdir(parents=True, exist_ok=True)
        sidecar_fh = open(sidecar_path, "a", encoding="utf-8")  # noqa: SIM115 (streaming append, closed in finally)

    want_samples = args.sample

    def handle(path: Path):
        try:
            return path, process_file(path, skip, args.apply, want_samples), None
        except Exception as e:  # noqa: BLE001 — report the offending file
            return path, None, f"{type(e).__name__}: {e}"

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futures = [ex.submit(handle, p) for p in files]
            for i, fut in enumerate(as_completed(futures), 1):
                path, result, err = fut.result()
                if err is not None:





                    errors.append((path.name, err))
                    continue
                if result is None:
                    files_skipped += 1
                    continue
                s = result.stats
                tot.facts_before += s.facts_before
                tot.facts_after += s.facts_after
                tot.typeA_collapsed += s.typeA_collapsed
                tot.typeB_observations += s.typeB_observations
                tot.absorbed_fact_ids += s.absorbed_fact_ids
                tot.passthrough_empty_rid += s.passthrough_empty_rid
                reduction = s.facts_before - s.facts_after
                if reduction > 0:
                    entity_reduction.append((path.stem, reduction))
                if result.changed:
                    files_changed += 1
                if args.apply and result.sidecar and sidecar_fh is not None:
                    with sidecar_lock:
                        for row in result.sidecar:
                            sidecar_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                if want_samples and len(collected_samples) < want_samples:
                    for sm in result.samples:
                        if len(collected_samples) >= want_samples:
                            break
                        collected_samples.append(sm)
                if i % 2000 == 0:
                    log.info(
                        "  … %d/%d file (before=%d after=%d)",
                        i,
                        len(files),
                        tot.facts_before,
                        tot.facts_after,
                    )
    finally:
        if sidecar_fh is not None:
            sidecar_fh.close()

    elapsed = time.time() - t0


    entity_reduction.sort(key=lambda x: x[1], reverse=True)
    reduction_pct = (
        100.0 * (tot.facts_before - tot.facts_after) / tot.facts_before if tot.facts_before else 0.0
    )
    print("\n" + "=" * 70)
    print(f"  COMPACTION REPORT — {'APPLY' if args.apply else 'DRY-RUN'}  ({ts})")
    print("=" * 70)
    print(f"  Profiles processed        : {len(files) - files_skipped}")
    print(f"  Profiles skipped (skip-set): {files_skipped}")
    print(f"  Profiles changed          : {files_changed}")
    print(f"  Facts BEFORE              : {tot.facts_before:,}")
    print(f"  Facts AFTER               : {tot.facts_after:,}")
    print(
        f"  Reduction                 : {tot.facts_before - tot.facts_after:,} "
        f"({reduction_pct:.1f}%)"
    )
    print(f"  Type A collapsed (re-reads): {tot.typeA_collapsed:,}")
    print(f"  Type B observations preserved: {tot.typeB_observations:,}")
    print(f"  UUIDs absorbed (merged_fact_ids): {tot.absorbed_fact_ids:,}")
    print(f"  Pass-through empty record_id: {tot.passthrough_empty_rid:,}")
    print(f"  Errors                    : {len(errors)}")
    print(f"  Time                      : {elapsed:.1f}s")
    print("\n  Top-20 entities by reduction:")
    for eid, red in entity_reduction[:20]:
        print(f"    {eid:<28} -{red:,}")
    if args.apply:
        print(f"\n  Sidecar compaction-map    : {sidecar_path}")
    print("=" * 70)

    if errors:
        print("\n  ⚠️  Files with errors (first 20):")
        for name, err in errors[:20]:
            print(f"    {name}: {err}")


    if want_samples:
        sample_out = args.sample_out or (
            KNOWLEDGE_DIR.parent / "samples" / f"compaction-sample-{ts}.json"
        )
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        sample_out.write_text(
            json.dumps(collected_samples, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\n  Diff sample ({len(collected_samples)}): {sample_out}")

    return 1 if errors and not args.apply else 0


if __name__ == "__main__":
    raise SystemExit(main())
