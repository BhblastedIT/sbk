#!/usr/bin/env python3
"""L4, run by hand: fills in place the source record id of facts that were stored without one (dry run unless --apply)."""




























































from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd  # noqa: E402
from knowledge_schema import (  # noqa: E402  (path bootstrap must precede import)
    FactObservation,
    fact_observation_to_dict,
    generate_entity_id,
    normalize_value,
)

from sbk_config import (  # noqa: E402
    DEEP_FACTS_FILE,
    ENRICHED_DIR,
    KNOWLEDGE_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_META_DIR,
    safe_write_json,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xs-l4-reanchor")



SF_CONTACTS_MERGED = "enriched/contacts-merged.parquet"
SF_CONTACTS_CALENDAR = "enriched/contacts-calendar.parquet"
SF_DEEP_FACTS = "l3/nlp/deep-facts.parquet"
SF_RELATIONSHIP = "l3/nlp/relationship-facts.parquet"



ANCHORABLE_BUCKETS = ("C2", "C5", "C3")
DEFERRED_BUCKETS = (
    "relationship-deferred",
    "deep-nonidentity-deferred",
    "other-deferred",
)

_UNSET = object()





def _s(v) -> str | None:
    ""
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    if s in ("", "nan", "NaN", "None", "NaT"):
        return None
    return s


def _email_key(v) -> str | None:
    ""
    s = _s(v)
    return s.lower() if s else None





@dataclass
class Indices:

    email2pid: dict[str, str]
    nameeid2pids: dict[str, set[str]]

    cal_eid2emails: dict[str, set[str]]
    cal_emaillower2email: dict[str, str]

    subjnorm2rows: dict[
        str, list[tuple[str, str | None]]
    ]


def build_indices(enriched_dir: Path, deep_facts_file: Path) -> Indices:
    t0 = time.time()


    cm_path = enriched_dir / "contacts-merged.parquet"
    email2pid: dict[str, str] = {}
    email_ambig: set[str] = set()
    nameeid2pids: dict[str, set[str]] = defaultdict(set)
    if cm_path.exists():
        cm = pd.read_parquet(cm_path, columns=["person_id", "name", "email"])
        for pid_raw, name_raw, email_raw in zip(
            cm["person_id"], cm["name"], cm["email"], strict=False
        ):
            pid = _s(pid_raw)
            if not pid:
                continue
            ek = _email_key(email_raw)
            if ek:
                if ek in email2pid and email2pid[ek] != pid:
                    email_ambig.add(ek)
                else:
                    email2pid[ek] = pid
            name = _s(name_raw)
            if name:
                nameeid2pids[generate_entity_id("person", name)].add(pid)
        for ek in email_ambig:
            email2pid.pop(ek, None)
    else:
        log.warning("contacts-merged.parquet not found — bucket C2 not anchorable")


    cal_path = enriched_dir / "contacts-calendar.parquet"
    cal_eid2emails: dict[str, set[str]] = defaultdict(set)
    cal_emaillower2email: dict[str, str] = {}
    cal_email_ambig: set[str] = set()
    if cal_path.exists():
        cal = pd.read_parquet(cal_path, columns=["name", "email"])
        for name_raw, email_raw in zip(cal["name"], cal["email"], strict=False):
            name = _s(name_raw)
            email = _s(email_raw)
            key = name or email
            if not key:
                continue
            eid = generate_entity_id("person", key)
            rid = email or ""
            if rid:
                cal_eid2emails[eid].add(rid)
                ek = rid.lower()
                if ek in cal_emaillower2email and cal_emaillower2email[ek] != rid:
                    cal_email_ambig.add(ek)
                else:
                    cal_emaillower2email[ek] = rid
        for ek in cal_email_ambig:
            cal_emaillower2email.pop(ek, None)
    else:
        log.warning("contacts-calendar.parquet not found — bucket C5 not anchorable")


    subjnorm2rows: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    if deep_facts_file.exists():
        dfc = pd.read_parquet(deep_facts_file, columns=["fact_id", "subject", "source_date"])
        for fid_raw, subj_raw, sdate_raw in zip(
            dfc["fact_id"], dfc["subject"], dfc["source_date"], strict=False
        ):
            fid = _s(fid_raw)
            subj = _s(subj_raw)
            if not fid or not subj:
                continue
            subjnorm2rows[normalize_value(subj)].append((fid, _s(sdate_raw)))
    else:
        log.warning("deep-facts.parquet not found — bucket C3 not anchorable")

    log.info(
        "Indices: cm-email=%d cm-nameeid=%d cal-eid=%d cal-email=%d deep-subj=%d  (%.1fs)",
        len(email2pid),
        len(nameeid2pids),
        len(cal_eid2emails),
        len(cal_emaillower2email),
        len(subjnorm2rows),
        time.time() - t0,
    )
    return Indices(
        email2pid=dict(email2pid),
        nameeid2pids=dict(nameeid2pids),
        cal_eid2emails=dict(cal_eid2emails),
        cal_emaillower2email=dict(cal_emaillower2email),
        subjnorm2rows=dict(subjnorm2rows),
    )





def classify(source_file: str, attribute: str) -> str:
    if source_file == SF_CONTACTS_MERGED:
        return "C2"
    if source_file == SF_CONTACTS_CALENDAR:
        return "C5"
    if source_file == SF_DEEP_FACTS:
        return "C3" if attribute == "identity.name" else "deep-nonidentity-deferred"
    if source_file == SF_RELATIONSHIP:
        return "relationship-deferred"
    return "other-deferred"





def resolve_c2(entity_id: str, canonical: str, facts: list[dict], idx: Indices):
    ""

    a_pids: set[str] = set()
    for f in facts:
        if f.get("attribute") == "contact.email":
            ek = _email_key(f.get("value"))
            if ek and ek in idx.email2pid:
                a_pids.add(idx.email2pid[ek])
    if len(a_pids) > 1:
        return None, "ambiguous-email"
    a_pid = next(iter(a_pids)) if a_pids else None


    b_pid = None
    b_ambig = False
    if canonical and canonical != entity_id:
        b_pids = idx.nameeid2pids.get(generate_entity_id("person", canonical), set())
        if len(b_pids) == 1:
            b_pid = next(iter(b_pids))
        elif len(b_pids) > 1:
            b_ambig = True


    if a_pid and b_pid and a_pid != b_pid:
        return None, "ambiguous-a-vs-b"
    resolved = a_pid or b_pid
    if resolved:
        return resolved, None
    if b_ambig:
        return None, "ambiguous-recomputed"
    return None, "absent"


def resolve_c5(entity_id: str, facts: list[dict], idx: Indices):
    ""

    prim = idx.cal_eid2emails.get(entity_id, set())
    p_email = next(iter(prim)) if len(prim) == 1 else None
    p_ambig = len(prim) > 1


    x_emails: set[str] = set()
    for f in facts:
        if f.get("attribute") == "contact.email":
            ek = _email_key(f.get("value"))
            if ek and ek in idx.cal_emaillower2email:
                x_emails.add(idx.cal_emaillower2email[ek])
    x_email = next(iter(x_emails)) if len(x_emails) == 1 else None
    x_ambig = len(x_emails) > 1

    if p_email and x_email and p_email != x_email:
        return None, "ambiguous-a-vs-b"
    resolved = p_email or x_email
    if resolved:
        return resolved, None
    if p_ambig or x_ambig:
        return None, "ambiguous"
    return None, "absent"


def anchor_c3(fact: dict, idx: Indices):
    ""
    nval = normalize_value(fact.get("value"))
    rows = idx.subjnorm2rows.get(nval)
    if not rows:
        return None

    sdate_by_fid: dict[str, str | None] = {}
    for fid, sdate in rows:
        if fid not in sdate_by_fid:
            sdate_by_fid[fid] = sdate
    fids = sorted(sdate_by_fid)
    new_rid = fids[0]
    src = fact.get("source") or {}
    extracted_at = src.get("extracted_at") or ""
    conf = fact.get("confidence")
    observations = [
        fact_observation_to_dict(
            FactObservation(
                source_file=SF_DEEP_FACTS,
                record_id=fid,
                source_type="deep_facts",
                valid_from=sdate_by_fid[fid],
                extracted_at=extracted_at,
                confidence=conf,
                confidence_curve=[conf] if conf is not None else [],
            )
        )
        for fid in fids
    ]
    return new_rid, observations





@dataclass
class ProfileStats:
    deanchored: Counter = field(default_factory=Counter)
    matched: Counter = field(default_factory=Counter)
    residual: dict = field(default_factory=lambda: defaultdict(Counter))
    deferred: Counter = field(default_factory=Counter)
    c3_obs_total: int = 0
    c3_obs_max: int = 0


@dataclass
class ProfileResult:
    profile: dict
    changed: bool
    stats: ProfileStats
    sidecar: list[dict] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)


def reanchor_profile(profile: dict, idx: Indices, want_samples: int = 0) -> ProfileResult:
    entity_id = profile.get("entity_id") or ""
    canonical = profile.get("canonical_name") or ""
    facts = profile.get("facts", [])
    st = ProfileStats()
    sidecar: list[dict] = []
    samples: list[dict] = []
    changed = False

    c2_res = _UNSET
    c5_res = _UNSET

    for fact in facts:
        src = fact.get("source")
        if not isinstance(src, dict):

            st.deanchored["other-deferred"] += 1
            st.deferred["other-deferred"] += 1
            continue
        if src.get("record_id"):
            continue

        attr = fact.get("attribute", "")
        bucket = classify(src.get("source_file", ""), attr)
        st.deanchored[bucket] += 1

        if bucket == "C2":
            if c2_res is _UNSET:
                c2_res = resolve_c2(entity_id, canonical, facts, idx)
            pid, reason = c2_res
            if pid:
                src["record_id"] = pid
                changed = True
                st.matched["C2"] += 1
                sidecar.append(
                    {
                        "entity_id": entity_id,
                        "fact_id": fact.get("fact_id"),
                        "old_record_id": "",
                        "new_record_id": pid,
                        "bucket": "C2",
                    }
                )
                if want_samples and len(samples) < want_samples:
                    samples.append(_mk_sample(entity_id, fact, "C2", pid))
            else:
                st.residual["C2"][reason] += 1

        elif bucket == "C5":
            if c5_res is _UNSET:
                c5_res = resolve_c5(entity_id, facts, idx)
            email, reason = c5_res
            if email:
                src["record_id"] = email
                changed = True
                st.matched["C5"] += 1
                sidecar.append(
                    {
                        "entity_id": entity_id,
                        "fact_id": fact.get("fact_id"),
                        "old_record_id": "",
                        "new_record_id": email,
                        "bucket": "C5",
                    }
                )
                if want_samples and len(samples) < want_samples:
                    samples.append(_mk_sample(entity_id, fact, "C5", email))
            else:
                st.residual["C5"][reason] += 1

        elif bucket == "C3":
            res = anchor_c3(fact, idx)
            if res:
                new_rid, obs = res
                src["record_id"] = new_rid
                fact["observations"] = obs
                changed = True
                st.matched["C3"] += 1
                st.c3_obs_total += len(obs)
                st.c3_obs_max = max(st.c3_obs_max, len(obs))
                sidecar.append(
                    {
                        "entity_id": entity_id,
                        "fact_id": fact.get("fact_id"),
                        "old_record_id": "",
                        "new_record_id": new_rid,
                        "bucket": "C3",
                    }
                )
                if want_samples and len(samples) < want_samples:
                    samples.append(_mk_sample(entity_id, fact, "C3", new_rid, n_obs=len(obs)))
            else:
                st.residual["C3"]["parent-missing"] += 1

        else:

            st.deferred[bucket] += 1

    return ProfileResult(
        profile=profile, changed=changed, stats=st, sidecar=sidecar, samples=samples
    )


def _mk_sample(entity_id, fact, bucket, new_rid, n_obs=None):
    s = {
        "entity_id": entity_id,
        "bucket": bucket,
        "fact_id": fact.get("fact_id"),
        "attribute": fact.get("attribute"),
        "value": fact.get("value"),
        "before": {"record_id": ""},
        "after": {"record_id": new_rid},
    }
    if n_obs is not None:
        s["after"]["n_observations"] = n_obs
    return s





def make_backup(ts: str) -> Path:
    ""
    backups_dir = KNOWLEDGE_DIR.parent / "backups-reanchor"
    backups_dir.mkdir(parents=True, exist_ok=True)
    archive = backups_dir / f"knowledge-prereanchor-{ts}.tar.gz"
    log.info("Backup: tar of %s → %s", KNOWLEDGE_DIR, archive)
    tar = subprocess.run(
        ["tar", "-czf", str(archive), "-C", str(KNOWLEDGE_DIR.parent), KNOWLEDGE_DIR.name],
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
    if entity_id:
        for et in etypes:
            p = entities_dir / et / f"{entity_id}.json"
            if p.exists():
                yield p
                return
        return
    for et in etypes:
        d = entities_dir / et
        if not d.is_dir():
            continue
        yield from sorted(d.glob("*.json"))


def process_file(path: Path, idx: Indices, apply: bool, want_samples: int) -> ProfileResult | None:
    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)
    if not profile.get("facts"):
        return None
    result = reanchor_profile(profile, idx, want_samples=want_samples)
    if apply and result.changed:
        safe_write_json(path, profile, backup=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Mutates the store. DEFAULT off (dry-run). Requires a verified backup.",
    )
    ap.add_argument("--workers", type=int, default=6, help="Per-file parallelism.")
    ap.add_argument(
        "--sample", type=int, default=0, help="Number of (stratified) diffs to dump."
    )
    ap.add_argument("--sample-out", type=Path, default=None, help="Samples file.")
    ap.add_argument("--etypes", default="person", help="Entity subdirs (csv). Default 'person'.")
    ap.add_argument("--entity-id", default=None, help="Process a single profile (validation).")
    ap.add_argument(
        "--entities-dir", type=Path, default=KNOWLEDGE_ENTITIES_DIR, help="Entity root."
    )
    ap.add_argument(
        "--enriched-dir", type=Path, default=ENRICHED_DIR, help="Enriched parquet root."
    )
    ap.add_argument(
        "--deep-facts", type=Path, default=DEEP_FACTS_FILE, help="deep-facts.parquet (C3)."
    )
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N files.")
    args = ap.parse_args()

    etypes = [e.strip() for e in args.etypes.split(",") if e.strip()]
    log.info(
        "Mode=%s  etypes=%s  workers=%d", "APPLY" if args.apply else "DRY-RUN", etypes, args.workers
    )

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


    idx = build_indices(args.enriched_dir, args.deep_facts)

    if args.apply:
        make_backup(ts)

    files = list(iter_entity_files(args.entities_dir, etypes, args.entity_id))
    if args.limit:
        files = files[: args.limit]
    log.info("Profiles to process: %d", len(files))


    tot_deanchored: Counter = Counter()
    tot_matched: Counter = Counter()
    tot_residual: dict = defaultdict(Counter)
    tot_deferred: Counter = Counter()
    c3_obs_total = 0
    c3_obs_max = 0
    files_changed = 0
    files_skipped = 0
    errors: list[tuple[str, str]] = []

    sample_quota = max(0, args.sample)
    per_bucket_quota = {
        b: (sample_quota // 3 + (1 if i < sample_quota % 3 else 0))
        for i, b in enumerate(ANCHORABLE_BUCKETS)
    }
    collected_samples: dict[str, list] = {b: [] for b in ANCHORABLE_BUCKETS}

    sidecar_path = KNOWLEDGE_META_DIR / f"reanchor-map-{ts}.jsonl"
    sidecar_lock = threading.Lock()
    sidecar_fh = None
    if args.apply:
        KNOWLEDGE_META_DIR.mkdir(parents=True, exist_ok=True)
        sidecar_fh = open(sidecar_path, "a", encoding="utf-8")  # noqa: SIM115 (streaming append)

    want_samples = 1 if sample_quota else 0

    def handle(path: Path):
        try:
            return path, process_file(path, idx, args.apply, want_samples), None
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
                    if args.apply:
                        raise RuntimeError(f"{path.name}: {err}")
                    continue
                if result is None:
                    files_skipped += 1
                    continue
                s = result.stats
                tot_deanchored.update(s.deanchored)
                tot_matched.update(s.matched)
                for b, rc in s.residual.items():
                    tot_residual[b].update(rc)
                tot_deferred.update(s.deferred)
                c3_obs_total += s.c3_obs_total
                c3_obs_max = max(c3_obs_max, s.c3_obs_max)
                if result.changed:
                    files_changed += 1
                if args.apply and result.sidecar and sidecar_fh is not None:
                    with sidecar_lock:
                        for row in result.sidecar:
                            sidecar_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                if sample_quota:
                    for sm in result.samples:
                        b = sm["bucket"]
                        if len(collected_samples[b]) < per_bucket_quota.get(b, 0):
                            collected_samples[b].append(sm)
                if i % 5000 == 0:
                    log.info("  … %d/%d file", i, len(files))
    finally:
        if sidecar_fh is not None:
            sidecar_fh.close()

    elapsed = time.time() - t0


    total_deanchored = sum(tot_deanchored.values())
    total_matched = sum(tot_matched.values())
    total_residual = sum(sum(rc.values()) for rc in tot_residual.values())
    total_deferred = sum(tot_deferred.values())
    unmatched_unclassified = total_deanchored - (total_matched + total_residual + total_deferred)


    print("\n" + "=" * 74)
    print(f"  REANCHOR REPORT — {'APPLY' if args.apply else 'DRY-RUN'}  ({ts})")
    print("=" * 74)
    print(f"  Profiles processed        : {len(files) - files_skipped}")
    print(f"  Profiles without facts(skip): {files_skipped}")
    print(f"  Profiles changed          : {files_changed}")
    print(f"  Total de-anchored facts   : {total_deanchored:,}")
    print(f"  Time                      : {elapsed:.1f}s")
    print("-" * 74)
    print("  ANCHORABLE BUCKETS (record_id from real row ids):")
    for b in ANCHORABLE_BUCKETS:
        de = tot_deanchored.get(b, 0)
        ma = tot_matched.get(b, 0)
        res = tot_residual.get(b, Counter())
        ambiguous = sum(v for k, v in res.items() if k.startswith("ambiguous"))
        absent = res.get("absent", 0)
        parent_missing = res.get("parent-missing", 0)
        cov = 100.0 * ma / de if de else 0.0
        print(f"    {b}: de-anchored={de:,}  matched={ma:,}  coverage={cov:.1f}%")
        print(
            f"        residual → ambiguous={ambiguous:,}  absent={absent:,}"
            + (f"  parent-missing={parent_missing:,}" if b == "C3" else "")
        )

        if res:
            detail = "  ".join(f"{k}={v:,}" for k, v in sorted(res.items()))
            print(f"        [{detail}]")
    anchorable_de = sum(tot_deanchored.get(b, 0) for b in ANCHORABLE_BUCKETS)
    anchorable_ma = sum(tot_matched.get(b, 0) for b in ANCHORABLE_BUCKETS)
    overall_cov = 100.0 * anchorable_ma / anchorable_de if anchorable_de else 0.0
    print(
        f"    → ANCHORABLE TOTAL: de-anchored={anchorable_de:,}  "
        f"matched={anchorable_ma:,}  coverage={overall_cov:.1f}%"
    )
    print("-" * 74)
    print("  DEFERRED BUCKETS (typed, NOT anchored in v1):")
    for b in DEFERRED_BUCKETS:
        print(f"    {b}: {tot_deferred.get(b, 0):,}")
    print("-" * 74)
    print("  C3 observations telemetry:")
    print(f"    total observations written  : {c3_obs_total:,}")
    print(f"    max observations on a fact  : {c3_obs_max:,}")
    print("-" * 74)
    print("  INVARIANT (signal vs noise):")
    print(f"    de-anchored                 = {total_deanchored:,}")
    print(f"    matched                     = {total_matched:,}")
    print(f"    typed residual              = {total_residual:,}")
    print(f"    typed deferred              = {total_deferred:,}")
    print(f"    unmatched-NOT-classified    = {unmatched_unclassified:,}   (must be 0)")
    ok = unmatched_unclassified == 0
    print(f"    INVARIANT {'OK ✓' if ok else 'VIOLATED ✗'}")
    if args.apply:
        print(f"\n  Sidecar reanchor-map        : {sidecar_path}")
    print("=" * 74)

    if errors:
        print("\n  ⚠️  Files with errors (first 20):")
        for name, err in errors[:20]:
            print(f"    {name}: {err}")


    if sample_quota:
        flat = [sm for b in ANCHORABLE_BUCKETS for sm in collected_samples[b]]
        sample_out = args.sample_out or (
            KNOWLEDGE_DIR.parent / "samples" / f"reanchor-sample-{ts}.json"
        )
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        sample_out.write_text(
            json.dumps(flat, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"\n  Stratified sample ({len(flat)}): {sample_out}")


    return 0 if (ok and not (errors and not args.apply)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
