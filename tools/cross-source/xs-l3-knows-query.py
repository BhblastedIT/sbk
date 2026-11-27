#!/usr/bin/env python3
"""Queries over episodes and the KNOWS view: who attended an episode, the episodes of a person, who knows about a
subject, who met whom, and a person's summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT  # noqa: E402

log = logging.getLogger("sbk-xs-l3-knows-query")

KNOWLEDGE = DATA_ROOT / "knowledge"
EPISODES_DIR = KNOWLEDGE / "episodes"
KNOWS_PARQUET = KNOWLEDGE / "epistemic" / "knows.parquet"
SUBJECT_INDEX = KNOWLEDGE / "epistemic" / "subject_index.parquet"
PERSON_DIR = KNOWLEDGE / "entities" / "person"

_MAX_PLAUSIBLE_YEAR = 2035





@lru_cache(maxsize=1)
def _load_knows() -> list[dict]:
    if not KNOWS_PARQUET.exists():
        return []
    return pq.read_table(KNOWS_PARQUET).to_pylist()


@lru_cache(maxsize=1)
def _episode_index() -> dict[str, dict]:
    ""
    idx: dict[str, dict] = {}
    if not EPISODES_DIR.exists():
        return idx
    for y in EPISODES_DIR.iterdir():
        if not y.is_dir():
            continue
        for f in y.glob("ep_*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            idx[d.get("episode_id", f.stem)] = {
                "title": d.get("title", ""),
                "subjects": d.get("subjects", []),
                "participants": d.get("participants", []),
                "occurred_at": d.get("occurred_at"),
                "ingested_at": d.get("ingested_at"),
                "source_type": d.get("source_type", ""),
                "n_facts": d.get("n_facts", 0),
            }
    return idx


@lru_cache(maxsize=1)
def _pid_to_name() -> dict[str, str]:
    m: dict[str, str] = {}
    if not PERSON_DIR.exists():
        return m
    for f in PERSON_DIR.iterdir():
        if f.name.endswith(".json") and not f.name.startswith("_"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                m[d.get("entity_id", "")] = d.get("canonical_name", "")
            except (json.JSONDecodeError, OSError):
                continue
    return m


@lru_cache(maxsize=1)
def _name_to_pid() -> dict[str, str]:
    ""
    n2p: dict[str, str] = {}
    for pid, nm in _pid_to_name().items():
        key = (nm or "").strip().lower()
        if key and pid:
            n2p.setdefault(key, pid)
    return n2p


def resolve_person(name_or_pid: str) -> str | None:
    ""
    s = (name_or_pid or "").strip()
    if not s:
        return None
    if s.startswith("person_") and (PERSON_DIR / f"{s}.json").exists():
        return s
    n2p = _name_to_pid()
    sl = s.lower()
    if sl in n2p:
        return n2p[sl]

    hits = [pid for nm, pid in n2p.items() if sl in nm]
    return hits[0] if len(hits) == 1 else None


@lru_cache(maxsize=1)
def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _is_group_name(name: str) -> bool:
    ""










    s = " ".join(re.sub(r"\([^)]*\)", " ", name or "").split())
    if not s:
        return False
    low = f" {s.lower()} "
    return (
        ("," in s)
        or (" and " in low)
        or (" & " in s)
        or ("/" in s)
        or (" e " in low and s.count(" ") >= 3)
    )


def _valid_date(s) -> str | None:
    ""





    if not s or not isinstance(s, str) or len(s) < 4 or not s[:4].isdigit():
        return None
    if int(s[:4]) > _MAX_PLAUSIBLE_YEAR:
        return None
    return s if s[:10] <= _today() else None





def who_attended(episode_id: str) -> dict:
    ep = _episode_index().get(episode_id)
    if not ep:
        return {"episode_id": episode_id, "found": False}
    names = _pid_to_name()
    parts = [
        {
            "person_id": p.get("person_id"),
            "name": p.get("name") or names.get(p.get("person_id"), ""),
            "attendance": p.get("attendance"),
            "is_group": _is_group_name(p.get("name") or names.get(p.get("person_id"), "")),
        }
        for p in ep["participants"]
        if p.get("resolved") and p.get("person_id")
    ]
    return {
        "episode_id": episode_id,
        "found": True,
        "title": ep["title"],
        "source_type": ep["source_type"],
        "occurred_at": ep["occurred_at"],
        "n_participants": len(parts),
        "participants": parts,
        "subjects": ep["subjects"],
    }


def person_episodes(
    person_id: str,
    access_type: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> dict:
    rows = [r for r in _load_knows() if r["person_id"] == person_id]
    if access_type:
        rows = [r for r in rows if r["access_type"] == access_type]
    epidx = _episode_index()
    out = []
    dropped_unknown_date = 0
    for r in rows:
        d = _valid_date(r.get("occurred_at"))
        if after or before:
            if d is None:


                dropped_unknown_date += 1
            else:
                if after and d < after:
                    continue
                if before and d > before:
                    continue
        ep = epidx.get(r["episode_id"], {})
        out.append(
            {
                "episode_id": r["episode_id"],
                "access_type": r["access_type"],
                "occurred_at": d,
                "title": ep.get("title", ""),
                "source_type": ep.get("source_type", ""),
                "subjects": ep.get("subjects", [])[:8],
            }
        )

    out.sort(key=lambda x: (x["occurred_at"] is not None, x["occurred_at"] or ""), reverse=True)

    by_access = Counter(e["access_type"] for e in out)
    res = {
        "person_id": person_id,
        "name": _pid_to_name().get(person_id, ""),
        "n_episodes": len(out),
        "by_access": dict(by_access),
        "episodes": out,
    }
    if (after or before) and dropped_unknown_date:
        res["n_with_unknown_date"] = dropped_unknown_date
    return res


@lru_cache(maxsize=1)
def _load_subject_index() -> dict[str, list[str]]:
    if not SUBJECT_INDEX.exists():
        return {}
    t = pq.read_table(SUBJECT_INDEX).to_pylist()
    return {r["subject_lower"]: r["episode_ids"] for r in t}


def who_knows_subject(subject: str, fuzzy: bool = True) -> dict:
    idx = _load_subject_index()
    sl = subject.strip().lower()

    if len(sl) < 2:
        return {
            "subject": subject,
            "error": "subject too short (min 2 characters) to avoid matching the entire graph",
            "n_episodes": 0,
            "n_people": 0,
            "people": [],
        }
    ep_ids: set[str] = set(idx.get(sl, []))
    matched_subjects = {sl} if sl in idx else set()
    if fuzzy:
        for k, eps in idx.items():
            if sl in k and k != sl:
                ep_ids.update(eps)
                matched_subjects.add(k)
    ep_set = ep_ids
    names = _pid_to_name()

    per_person: dict[str, Counter] = defaultdict(Counter)
    for r in _load_knows():
        if r["episode_id"] in ep_set:
            per_person[r["person_id"]][r["access_type"]] += 1
    people = []
    n_groups = 0
    for pid, c in per_person.items():
        active = c.get("spoke", 0) + c.get("attended", 0)
        nm = names.get(pid, "")
        is_group = _is_group_name(nm)
        if is_group:
            n_groups += 1
        people.append(
            {
                "person_id": pid,
                "name": nm,
                "is_group": is_group,
                "n_active": active,
                "n_received": c.get("received", 0),
                "n_episodes": sum(c.values()),
                "access_types": sorted(c),
            }
        )

    people.sort(key=lambda x: (not x["is_group"], x["n_active"], x["n_episodes"]), reverse=True)
    return {
        "subject": subject,
        "matched_subjects": sorted(matched_subjects)[:10],
        "n_episodes": len(ep_ids),
        "n_people": len(people),
        "n_group_records": n_groups,
        "people": people[:50],
        "caveat": "n_active (spoke+attended)=discussed/was present; n_received (email/cc)=ACCESS, not certain knowledge; is_group=group record (several people, identity not resolved)",
    }



_COPRESENCE_TYPES = frozenset({"calendar_event", "tactiq", "plaud", "attio_call", "voice_memo"})


def co_participation(person_id: str, top: int = 20) -> dict:
    ""





    knows = _load_knows()
    my_eps = {r["episode_id"] for r in knows if r["person_id"] == person_id}
    epidx = _episode_index()
    shared_total: Counter = Counter()
    shared_copresence: Counter = Counter()
    first_together: dict[str, str] = {}
    for r in knows:
        if r["person_id"] == person_id or r["episode_id"] not in my_eps:
            continue
        other = r["person_id"]
        shared_total[other] += 1
        ep = epidx.get(r["episode_id"], {})
        if ep.get("source_type") in _COPRESENCE_TYPES or r.get("access_type") == "attended":
            shared_copresence[other] += 1
        d = _valid_date(ep.get("occurred_at"))
        if d and (other not in first_together or d < first_together[other]):
            first_together[other] = d
    names = _pid_to_name()

    ranked = sorted(
        shared_total,
        key=lambda pid: (
            not _is_group_name(names.get(pid, "")),
            shared_copresence.get(pid, 0),
            shared_total[pid],
        ),
        reverse=True,
    )[:top]
    people = [
        {
            "person_id": pid,
            "name": names.get(pid, ""),
            "is_group": _is_group_name(names.get(pid, "")),
            "shared_copresence": shared_copresence.get(pid, 0),
            "shared_total": shared_total[pid],
            "first_together": first_together.get(pid),
        }
        for pid in ranked
    ]
    return {
        "person_id": person_id,
        "name": names.get(person_id, ""),
        "n_co": len(shared_total),
        "people": people,
    }


def person_summary(person_id: str) -> dict:
    f = PERSON_DIR / f"{person_id}.json"
    if not f.exists():
        return {"person_id": person_id, "found": False}
    d = json.loads(f.read_text(encoding="utf-8"))
    facts = d.get("facts", [])
    by_attr: Counter = Counter(x.get("attribute", "") for x in facts)
    return {
        "person_id": person_id,
        "found": True,
        "canonical_name": d.get("canonical_name", ""),
        "n_facts": len(facts),
        "top_attributes": by_attr.most_common(12),
    }





def build_subject_index() -> int:
    ""
    idx: dict[str, set[str]] = defaultdict(set)
    for eid, ep in _episode_index().items():
        for s in ep.get("subjects", []):
            sl = str(s).strip().lower()
            if sl:
                idx[sl].add(eid)
    rows = [{"subject_lower": k, "episode_ids": sorted(v)} for k, v in idx.items()]
    if not rows and (not SUBJECT_INDEX.exists() or pq.read_metadata(SUBJECT_INDEX).num_rows == 0):
        # No episode subjects yet and no index with rows to protect (a first install): empty index.
        SUBJECT_INDEX.parent.mkdir(parents=True, exist_ok=True)
        schema = pa.schema([("subject_lower", pa.string()), ("episode_ids", pa.list_(pa.string()))])
        pq.write_table(pa.Table.from_pylist([], schema=schema), SUBJECT_INDEX)
        return 0
    if not rows:

        raise RuntimeError(
            "build_subject_index: 0 subjects from the episodes — refusing to overwrite the "
            "existing index. Check that EPISODES_DIR is not empty/moved."
        )
    SUBJECT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUBJECT_INDEX.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp)
    tmp.replace(SUBJECT_INDEX)
    return len(rows)





def main() -> None:
    ap = argparse.ArgumentParser(description="Query layer episodes/KNOWS (Phase 5 Wave 0)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("who-attended")
    p.add_argument("episode_id")

    p = sub.add_parser("person-episodes")
    p.add_argument("person_id")
    p.add_argument("--access", choices=["spoke", "received", "attended"])
    p.add_argument("--after")
    p.add_argument("--before")

    p = sub.add_parser("who-knows")
    p.add_argument("subject")
    p.add_argument("--exact", action="store_true", help="no fuzzy substring")

    p = sub.add_parser("co-participation")
    p.add_argument("person_id")
    p.add_argument("--top", type=int, default=20)

    p = sub.add_parser("person-summary")
    p.add_argument("person_id")

    sub.add_parser("build-index")

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "build-index":
        n = build_subject_index()
        log.info("subject_index.parquet written: %d distinct subjects", n)
        return
    if args.cmd == "who-attended":
        res = who_attended(args.episode_id)
    elif args.cmd == "person-episodes":
        res = person_episodes(args.person_id, args.access, args.after, args.before)
    elif args.cmd == "who-knows":
        res = who_knows_subject(args.subject, fuzzy=not args.exact)
    elif args.cmd == "co-participation":
        res = co_participation(args.person_id, args.top)
    elif args.cmd == "person-summary":
        res = person_summary(args.person_id)
    else:  # pragma: no cover
        ap.error("unknown command")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
