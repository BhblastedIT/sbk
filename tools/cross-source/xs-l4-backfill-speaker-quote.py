#!/usr/bin/env python3
"""Backfills the speaker and the evidence quote of older facts in the knowledge base from the relationship and deep
fact tables and the episodes. Dry run by default; --apply writes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from episode_schema import episode_id_for  # noqa: E402

from sbk_config import DATA_ROOT, KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-xs-l4-backfill-speaker-quote")

REL_PARQUET = DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"
DEEP_PARQUET = DATA_ROOT / "l3" / "nlp" / "deep-facts.parquet"
EPISODES_DIR = DATA_ROOT / "knowledge" / "episodes"


_BAD_FILES: list[str] = []


def _existing_episode_ids() -> set[str]:
    ""
    ids: set[str] = set()
    if not EPISODES_DIR.exists():
        return ids
    for y in EPISODES_DIR.iterdir():
        if y.is_dir():
            ids.update(f.stem for f in y.glob("ep_*.json"))
    return ids


def _s(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("none", "nan", "null") else s


def _norm(v) -> str:
    return _s(v).lower()



_SPEAKER_NOISE = {
    "context",
    "meeting context",
    "multiple",
    "multiple participants",
    "multiple speakers",
    "participants",
    "system",
    "team",
    "group",
    "unknown",
    "unknown speaker",
    "speaker",
    "various",
    "n/a",
    "the context",
}
import re as _re  # noqa: E402

_SPEAKER_NOISE_RE = _re.compile(r"^(speaker|persona|participant)[\s_]*\d+$", _re.IGNORECASE)


_SPEAKER_NOISE_SUBSTR = (
    "participant",
    "group chat",
    "group context",
    "both partie",
    "both speaker",
    "multiple part",
    "multiple speaker",
    "various speaker",
    "unknown speaker",
)


def _is_noise_speaker(s: str) -> bool:
    sl = s.strip().lower()
    if (not sl) or sl in _SPEAKER_NOISE or _SPEAKER_NOISE_RE.match(sl):
        return True
    if sl.startswith("team ") or sl.startswith("group ") or sl.startswith("both "):
        return True
    if any(sub in sl for sub in _SPEAKER_NOISE_SUBSTR):
        return True

    return bool(_re.search(r"\((speaker\s*\d+|multiple|group|team)\b", sl))



_WANTED = (
    "subject",
    "object",
    "predicate",
    "fact_type",
    "speaker",
    "context",
    "source_type",
    "source_id",
    "category",
    "subcategory",
    "counterparty",
)


def build_provenance_map(
    valid_episodes: set[str] | None = None,
) -> tuple[dict[tuple, tuple[str | None, str | None]], dict[tuple, list[str]]]:
    ""











    spk_sets: dict[tuple, set] = defaultdict(set)
    quote_best: dict[tuple, str] = {}
    ep_sets: dict[tuple, set] = defaultdict(set)

    def _offer(
        subject: str, attr: str, value: str, speaker: str, quote: str, episode_id: str | None
    ) -> None:
        key = (_norm(subject), attr, _norm(value))
        if speaker and not _is_noise_speaker(speaker):
            spk_sets[key].add(speaker.strip())
        if quote:

            prev = quote_best.get(key, "")
            if len(quote) > len(prev):
                quote_best[key] = quote
        if episode_id and (valid_episodes is None or episode_id in valid_episodes):
            ep_sets[key].add(episode_id)

    def _cols(t) -> tuple[dict[str, list], int]:
        ""
        n = t.num_rows
        names = set(t.column_names)
        empty = [None] * n
        return ({c: (t.column(c).to_pylist() if c in names else empty) for c in _WANTED}, n)


    if REL_PARQUET.exists():
        c, n = _cols(pq.read_table(REL_PARQUET))
        for i in range(n):
            subject = _s(c["subject"][i])
            obj = _s(c["object"][i])
            if not subject or not obj:
                continue
            predicate = _s(c["predicate"][i]) or _s(c["fact_type"][i])
            if not predicate:
                continue
            attr = f"relationship.{predicate.lower().replace(' ', '_')}"
            stype = _s(c["source_type"][i])
            sid = _s(c["source_id"][i])
            eid = episode_id_for(stype, sid) if (stype and sid) else None
            _offer(subject, attr, obj, _s(c["speaker"][i]), _s(c["context"][i]), eid)
        log.info("relationship-facts: %d rows processed", n)


    if DEEP_PARQUET.exists():
        c, n = _cols(pq.read_table(DEEP_PARQUET))
        for i in range(n):
            subject = _s(c["subject"][i])
            predicate = _s(c["predicate"][i])
            obj = _s(c["object"][i])
            if not subject or not predicate or not obj:
                continue
            category = _s(c["category"][i]) or "general"
            subcategory = _s(c["subcategory"][i])
            attr = f"deep.{category.lower().replace(' ', '_')}"
            if subcategory:
                attr += f".{subcategory.lower().replace(' ', '_')}"
            value = f"{predicate}: {obj}"
            counterparty = _s(c["counterparty"][i])
            if counterparty:
                value += f" (with {counterparty})"
            stype = _s(c["source_type"][i])
            sid = _s(c["source_id"][i])
            eid = episode_id_for(stype, sid) if (stype and sid) else None

            _offer(subject, attr, value, "", _s(c["context"][i]), eid)
        log.info("deep-facts: %d rows processed", n)

    sq_map: dict[tuple, tuple[str | None, str | None]] = {}
    for k in set(spk_sets) | set(quote_best):
        s = spk_sets.get(k)

        spk = next(iter(s)) if s and len(s) == 1 else None
        sq_map[k] = (spk, quote_best.get(k))
    ep_map = {k: sorted(v) for k, v in ep_sets.items()}
    return sq_map, ep_map


def _is_composite_name(nm: str) -> bool:
    ""
    s = (nm or "").strip()
    if not s:
        return True
    low = s.lower()
    return (
        "," in s
        or " and " in low
        or " & " in s
        or "/" in s
        or " e " in f" {low} "
        and s.count(" ") >= 3
    )


def _owned_names(data: dict, shared_names: frozenset[str]) -> set[str]:
    ""








    canon = _norm(data.get("canonical_name"))



    if _is_composite_name(canon):
        return set()
    cand = {canon}
    for f in data.get("facts", []):
        if f.get("attribute") == "identity.name":
            cand.add(_norm(f.get("value")))
    cand.discard("")
    owned = set()
    for nm in cand:
        if _is_composite_name(nm):
            continue
        if nm in shared_names and nm != canon:
            continue
        owned.add(nm)
    return owned


def _process_file(
    path: Path, sq_map: dict, ep_map: dict, shared_names: frozenset[str], dry_run: bool
) -> tuple[int, int, int, int]:
    ""





    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _BAD_FILES.append(str(path))
        return (0, 0, 0, 0)

    names = _owned_names(data, shared_names)

    touched = filled_spk = filled_q = filled_ep = 0
    changed = False
    for fact in data.get("facts", []):
        attr = fact.get("attribute", "")
        if attr == "identity.name":
            continue
        nval = _norm(fact.get("value"))
        src = fact.get("source")
        if not isinstance(src, dict):
            continue
        touched_this = False


        spk_candidates: set[str] = set()
        quote_best = ""
        for nm in names:
            sq = sq_map.get((nm, attr, nval))
            if not sq:
                continue
            if sq[0]:
                spk_candidates.add(sq[0])
            if sq[1] and len(sq[1]) > len(quote_best):
                quote_best = sq[1]
        spk = next(iter(spk_candidates)) if len(spk_candidates) == 1 else None
        if spk and not src.get("speaker"):
            src["speaker"] = spk
            filled_spk += 1
            touched_this = True
        if quote_best and not src.get("evidence_quote"):
            src["evidence_quote"] = quote_best
            filled_q += 1
            touched_this = True


        ep_ids: set[str] = set()
        for nm in names:
            ep_ids.update(ep_map.get((nm, attr, nval), ()))
        if ep_ids:
            existing = fact.get("episode_ids") or []
            merged = sorted(set(existing) | ep_ids)
            if merged != sorted(existing):
                fact["episode_ids"] = merged
                filled_ep += 1
                touched_this = True

        if touched_this:
            touched += 1
            changed = True

    if changed and not dry_run:


        safe_write_json(path, data, backup=False)
    return (touched, filled_spk, filled_q, filled_ep)


def _entity_files() -> list[Path]:
    out: list[Path] = []
    for type_dir in KNOWLEDGE_ENTITIES_DIR.iterdir():
        if type_dir.is_dir():
            out.extend(
                f
                for f in type_dir.iterdir()
                if f.name.endswith(".json") and not f.name.startswith("_")
            )
    return out


def _build_shared_names(files: list[Path]) -> frozenset[str]:
    ""



    counts: dict[str, int] = defaultdict(int)
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        seen: set[str] = set()
        canon = _norm(d.get("canonical_name"))
        if canon:
            seen.add(canon)
        for fact in d.get("facts", []):
            if fact.get("attribute") == "identity.name":
                nm = _norm(fact.get("value"))
                if nm:
                    seen.add(nm)
        for nm in seen:
            counts[nm] += 1
    return frozenset(nm for nm, c in counts.items() if c > 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill speaker/evidence_quote in historical facts")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    dry_run = not args.apply

    log.info("=" * 60)
    log.info("xs-l4-backfill-speaker-quote — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)

    valid_eps = _existing_episode_ids()
    log.info("Episodes materialised (for the stage-2 bridge): %d", len(valid_eps))
    sq_map, ep_map = build_provenance_map(valid_episodes=valid_eps)
    n_spk = sum(1 for v in sq_map.values() if v[0])
    n_q = sum(1 for v in sq_map.values() if v[1])
    log.info(
        "Maps: sq %d keys (speaker %d, quote %d) · ep %d keys (subject-aware)",
        len(sq_map),
        n_spk,
        n_q,
        len(ep_map),
    )

    files = _entity_files()
    log.info("Scansiono %d file entità...", len(files))
    shared_names = _build_shared_names(files)
    log.info("Nomi condivisi da >1 entità (ambigui): %d", len(shared_names))

    tot_touched = tot_spk = tot_q = tot_ep = files_changed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(_process_file, f, sq_map, ep_map, shared_names, dry_run): f for f in files
        }
        for fut in as_completed(futs):
            t, s, q, e = fut.result()
            tot_touched += t
            tot_spk += s
            tot_q += q
            tot_ep += e
            if t:
                files_changed += 1

    log.info("")
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Fatti arricchiti:        %d", tot_touched)
    log.info("  ...speaker riempiti:     %d", tot_spk)
    log.info("  ...evidence_quote:       %d", tot_q)
    log.info("  ...episode_ids agganciati:%d", tot_ep)
    log.info("  File modificati:         %d", files_changed)
    if _BAD_FILES:
        log.warning("  Files NOT parsable (skipped): %d, e.g. %s", len(_BAD_FILES), _BAD_FILES[:3])
    if dry_run:
        log.info("  Run with --apply.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
