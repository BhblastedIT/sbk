#!/usr/bin/env python3
""
































from __future__ import annotations

import argparse
import glob
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import pandas as pd  # noqa: E402
from episode_schema import (  # noqa: E402
    EPISODE_SOURCE_TYPES,
    Participant,
    episode_id_for,
    episode_to_dict,
    make_episode,
)

from sbk_config import DATA_ROOT, KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk.episodes")
KNOWLEDGE_DIR = KNOWLEDGE_ENTITIES_DIR.parent
EPISODES_DIR = KNOWLEDGE_DIR / "episodes"

L3_PARQUETS = [
    DATA_ROOT / "l3" / "nlp" / "deep-facts.parquet",
    DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet",
]


def _s(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in ("nan", "None", "NaT") else s


def build_episodes_from_parquets(parquets: list[Path] | None = None) -> dict:
    ""





    parquets = parquets or L3_PARQUETS
    episodes: dict = {}
    ep_speakers: dict = defaultdict(set)
    ep_subjects: dict = defaultdict(set)
    factid2ep: dict = {}

    for pq in parquets:
        if not pq.exists():
            continue
        df = pd.read_parquet(pq)
        cols = set(df.columns)
        if "source_id" not in cols or "source_type" not in cols:
            log.warning("%s: missing source_id/source_type — skip", pq.name)
            continue
        for row in df.itertuples(index=False):
            r = row._asdict()
            st = _s(r.get("source_type"))
            sid = _s(r.get("source_id"))
            if not sid or st not in EPISODE_SOURCE_TYPES:
                continue
            ep_id = episode_id_for(st, sid)
            ep = episodes.get(ep_id)
            if ep is None:
                ep = make_episode(
                    st,
                    sid,
                    source_file=pq.name,
                    occurred_at=_s(r.get("source_date")) or None,
                    title=_s(r.get("source_title")) or sid,
                )
                episodes[ep_id] = ep
            ep.n_facts += 1
            spk = _s(r.get("speaker"))
            if spk:
                ep_speakers[ep_id].add(spk)
            subj = _s(r.get("subject"))
            if subj:
                ep_subjects[ep_id].add(subj)
            fid = _s(r.get("fact_id"))
            if fid:
                factid2ep[fid] = ep_id


    for ep_id, ep in episodes.items():
        ep.participants = [
            Participant(person_id=None, name=n, attendance="spoke", resolved=False)
            for n in sorted(ep_speakers[ep_id])
        ]
        ep.subjects = sorted(ep_subjects[ep_id])
    return {"episodes": episodes, "factid2ep": factid2ep}


import re  # noqa: E402


_SPEAKER_NOISE = re.compile(
    r"^(both|multiple|unknown|system|guest|support|team|"
    r"(dm|both|conversation|meeting|call|group|multiple)\s*participants?|participants?|"
    r"speaker\s*\d+|attendee\s*\d*|user\s*\d*|"
    r"\+?\d[\d\s\-().]{5,}|\d{4,}(\s*\(.*\))?|u0[a-z0-9]{6,}|b0[a-z0-9]{6,})$",
    re.I,
)


def _is_speaker_noise(name: str) -> bool:
    n = (name or "").strip()
    return not n or bool(_SPEAKER_NOISE.match(n))


def enrich_speakers(episodes: dict, dedup_index=None) -> dict:
    ""





    if dedup_index is None:
        try:
            from entity_dedup_index import EntityDedupIndex

            dedup_index = EntityDedupIndex()
        except Exception as e:  # noqa: BLE001
            log.warning("EntityDedupIndex not available: %s — speakers not resolved", e)
            dedup_index = False
    stats = {"speakers_total": 0, "resolved": 0, "noise_dropped": 0, "unresolved": 0}

    distinct = {
        p.name for ep in episodes.values() for p in ep.participants if not _is_speaker_noise(p.name)
    }
    name2pid: dict = {}
    if dedup_index and dedup_index is not False:
        for name in distinct:
            res = dedup_index.find_existing_entity(name)
            name2pid[name] = res[0] if res else None
    for ep in episodes.values():
        by_key: dict = {}
        for p in ep.participants:
            stats["speakers_total"] += 1
            if _is_speaker_noise(p.name):
                stats["noise_dropped"] += 1
                continue
            pid = name2pid.get(p.name)
            if pid:
                p.person_id = pid
                p.resolved = True
                stats["resolved"] += 1
                key = pid
            else:
                stats["unresolved"] += 1
                key = "name:" + p.name.strip().lower()

            prev = by_key.get(key)
            if prev is None or len(p.name) > len(prev.name):
                by_key[key] = p
        ep.participants = list(by_key.values())
    return stats


def link_store_facts(entities_dir: Path, etypes: list[str], factid2ep: dict) -> dict:
    ""



    fact_patch: dict = defaultdict(lambda: defaultdict(list))
    for et in etypes:
        d = entities_dir / et
        if not d.is_dir():
            continue
        for fp in glob.glob(str(d / "*.json")):
            try:
                data = json.loads(Path(fp).read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for i, fact in enumerate(data.get("facts", [])):
                found: set[str] = set()

                src = fact.get("source") or {}
                for rid in [src.get("record_id")] + [
                    o.get("record_id") for o in (fact.get("observations") or [])
                ]:
                    if rid and rid in factid2ep:
                        found.add(factid2ep[rid])
                if found:
                    fact_patch[fp][i] = sorted(found)
    return fact_patch


def _togli_le_copie_di_prima(episode_id: str, anno_giusto: str) -> int:
    ""




















    tolti = 0
    for anno in _dove_stanno_gli_episodi().get(episode_id, ()):
        if anno != anno_giusto:
            (EPISODES_DIR / anno / f"{episode_id}.json").unlink(missing_ok=True)
            tolti += 1
    return tolti









_INDICE: dict[str, list[str]] | None = None


def _dove_stanno_gli_episodi() -> dict[str, list[str]]:
    global _INDICE
    if _INDICE is None:
        _INDICE = {}
        for anno_dir in EPISODES_DIR.iterdir():
            if not anno_dir.is_dir():
                continue
            for f in anno_dir.iterdir():
                if f.name.startswith("ep_") and f.name.endswith(".json"):
                    _INDICE.setdefault(f.stem, []).append(anno_dir.name)
    return _INDICE


def _pretendi_una_rete() -> None:
    ""











    import importlib.util
    import time

    perc = Path(__file__).resolve().parents[1] / "util" / "sb-kb-ripara.py"
    try:
        spec = importlib.util.spec_from_file_location("sb_kb_ripara_episodi", perc)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tar = mod.tar_piu_recente()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"cannot verify the store tar ({type(e).__name__}: {e}). "
            "This step rewrites thousands of KB files: without a safety net it does not start. "
            "uv run python tools/cross-source/xs-l0-refresh.py --copia-del-cervello"
        ) from e
    if tar is None:
        raise SystemExit(
            "no store tar: this step rewrites thousands of KB files "
            "and without a way back it does not start.\n"
            "  uv run python tools/cross-source/xs-l0-refresh.py --copia-del-cervello"
        )
    giorni = (time.time() - tar.stat().st_mtime) / 86400
    if giorni > 7:
        raise SystemExit(
            f"the most recent store tar is {giorni:.0f} days old ({tar}). "
            "For a mass mutation it is too old: redo it.\n"
            "  uv run python tools/cross-source/xs-l0-refresh.py --copia-del-cervello"
        )
    log.info("safety net: tar from %.1f days ago (%s)", giorni, tar.name)


def _year_of(ep) -> str:
    if ep.occurred_at and len(ep.occurred_at) >= 4 and ep.occurred_at[:4].isdigit():
        return ep.occurred_at[:4]
    return "unknown"


def write_all(episodes: dict, fact_patch: dict, apply: bool) -> dict:
    stats = {"episodes": len(episodes), "facts_patched": 0, "files_patched": 0, "spostati": 0}
    if not apply:
        return stats



    _pretendi_una_rete()
    for ep in episodes.values():
        anno = _year_of(ep)
        ydir = EPISODES_DIR / anno
        ydir.mkdir(parents=True, exist_ok=True)
        safe_write_json(ydir / f"{ep.episode_id}.json", episode_to_dict(ep))
        stats["spostati"] += _togli_le_copie_di_prima(ep.episode_id, anno)
    for fp, idx_map in fact_patch.items():
        try:
            data = json.loads(Path(fp).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        changed = False
        for i, ep_ids in idx_map.items():
            if i < len(data.get("facts", [])):
                cur = set(data["facts"][i].get("episode_ids", []))
                new = cur | set(ep_ids)
                if new != cur:
                    data["facts"][i]["episode_ids"] = sorted(new)
                    stats["facts_patched"] += 1
                    changed = True
        if changed:






            safe_write_json(Path(fp), data, backup=False)
            stats["files_patched"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Builds Episode nodes (Phase 1, source-anchored)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Writes episodes/ + patches episode_ids (default: dry-run)",
    )
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--etypes", default="person,organization")
    ap.add_argument("--entities-dir", type=Path, default=KNOWLEDGE_ENTITIES_DIR)
    args = ap.parse_args()


    from sbk_config import acquire_pid_lock

    if not acquire_pid_lock("l2-episodes", logger=log):
        log.warning("l2-episodes: lock held by another instance, exit 75")
        sys.exit(75)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    log.info("Mode=%s  building episodes from L3 parquet ...", "APPLY" if args.apply else "DRY-RUN")
    built = build_episodes_from_parquets()
    episodes, factid2ep = built["episodes"], built["factid2ep"]
    log.info("Episodes: %d · resolving speaker→person_id (identity chain) ...", len(episodes))
    spk_stats = enrich_speakers(episodes)
    log.info(
        "Speakers: %d total · %d resolved · %d noise dropped · %d unresolved",
        spk_stats["speakers_total"],
        spk_stats["resolved"],
        spk_stats["noise_dropped"],
        spk_stats["unresolved"],
    )
    etypes = [e.strip() for e in args.etypes.split(",") if e.strip()]
    log.info("Link store facts (fact_id→episode) ...")
    fact_patch = link_store_facts(args.entities_dir, etypes, factid2ep)

    by_type: dict = defaultdict(int)
    by_src: dict = defaultdict(int)
    psizes = []
    ssizes = []
    for ep in episodes.values():
        by_type[ep.episode_type] += 1
        by_src[ep.source_type] += 1
        psizes.append(len(ep.participants))
        ssizes.append(len(ep.subjects))
    facts_linked = sum(len(v) for v in fact_patch.values())

    print("=" * 68)
    print(f"  EPISODE BUILD (source-anchored) — {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 68)
    print(f"  Episodes (distinct documents)     : {len(episodes):,}")
    print(f"  Store facts linkable to episodes  : {facts_linked:,} (via deep-facts fact_id)")
    print("  By type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"    {t:<16} {n:,}")
    print("  By source:")
    for s, n in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"    {s:<16} {n:,}")
    if psizes:
        psizes.sort()
        ssizes.sort()
        print(
            f"  Speakers/episode : mean {sum(psizes) / len(psizes):.1f} · p50 {psizes[len(psizes) // 2]} · max {psizes[-1]}"
        )
        print(
            f"  Subjects/episode : mean {sum(ssizes) / len(ssizes):.1f} · p50 {ssizes[len(ssizes) // 2]} · max {ssizes[-1]}"
        )
    if args.sample:
        print("  Sample:")
        for ep in sorted(episodes.values(), key=lambda e: -e.n_facts)[: args.sample]:
            spk = ", ".join(p.name for p in ep.participants[:4])
            print(
                f"    [{ep.episode_type}] {ep.title[:44]!r} · {ep.n_facts}f · speakers: {spk[:60]}"
            )

    stats = write_all(episodes, fact_patch, args.apply)
    if args.apply:
        print(
            f"  WRITTEN: {stats['episodes']:,} episodes · {stats['facts_patched']:,} facts patched · {stats['files_patched']:,} files"
        )
    else:
        print("  (dry-run: no writes. --apply to create episodes/ + patch)")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
