#!/usr/bin/env python3
""






















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


import importlib.util  # noqa: E402

from sbk_config import OWN_PERSON_ID, OWNER_NAME  # noqa: E402

_KQ_PATH = Path(__file__).resolve().parent / "xs-l3-knows-query.py"
_spec = importlib.util.spec_from_file_location("xs_l3_knows_query", _KQ_PATH)
kq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kq)

log = logging.getLogger("sbk-xs-l3-router")




_EP_INTENTS = [

    (
        "who_attended",
        [
            r"\bchi\s+(?:c'?\s*era|era(?:no)?|ha partecipato|erano present[ei])\b.*\b(?:riunione|meeting|call|episodio|ep_)\b",
            r"\bpartecipant[ei]\b.*\bep_\w+",
        ],
    ),

    (
        "who_knows",
        [
            r"\bchi\s+(?:sa|conosce|e'?\s+a\s+conoscenza)\b.*\b(?:di|del|della|dei|delle|sul|sulla)\b",
            r"\bchi\s+ha\s+(?:avuto\s+)?accesso\b",
            r"\bchi\s+(?:e'?\s+)?(?:informato|al corrente)\b",
        ],
    ),

    (
        "co_participation",
        [
            r"\bcon\s+chi\b.*\b(?:mi\s+(?:vedo|incontro)|ho\s+(?:piu'?\s+)?(?:meeting|riunion|incontr|interazion))\b",
            r"\bcome\s+(?:ho\s+)?conosc\w+\b",
            r"\bprimo\s+(?:incontro|meeting|episodio)\s+con\b",
        ],
    ),

    (
        "person_episodes",
        [
            r"\b(?:quali|che)\s+(?:meeting|riunion\w+|episod\w+|incontr\w+)\b.*\bcon\b",
            r"\b(?:meeting|riunion\w+|episod\w+|incontr\w+)\s+(?:con|avut[oi]\s+con)\b",
            r"\bcosa\s+ho\s+fatto\s+con\b",
        ],
    ),
]


def _load_query_preprocessor():
    try:
        _p = Path(__file__).resolve().parent / "query_preprocessor.py"
        spec = importlib.util.spec_from_file_location("query_preprocessor", _p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:  # noqa: BLE001
        return None


def _extract_ep_id(query: str) -> str | None:
    m = re.search(r"\bep_[0-9a-f]{6,}\b", query)
    return m.group(0) if m else None


def _extract_subject(query: str) -> str:
    ""
    m = re.search(
        r"\b(?:di|del|della|dei|delle|sul|sulla|sui|sulle|su|riguardo)\s+(.+?)[\?\.!]*$",
        query,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _resolve_person_in_query(query: str, qp) -> str | None:
    ""
    if qp is not None:
        try:
            res = qp.QueryPipeline().process(query)
            if res.person and res.person.resolved_name:
                pid = kq.resolve_person(res.person.resolved_name)
                if pid:
                    return pid
        except Exception:  # noqa: BLE001
            pass

    for cand in re.findall(r"[A-ZÀ-Þ][\wÀ-ÿ'-]+(?:\s+[A-ZÀ-Þ][\wÀ-ÿ'-]+)*", query):
        pid = kq.resolve_person(cand)
        if pid:
            return pid
    return None


def _date_filter(query: str, qp) -> dict:
    if qp is not None:
        try:
            df = qp.extract_date_filter(query)
            if df:
                return df
        except Exception:  # noqa: BLE001
            pass
    return {}


def route(query: str) -> dict:
    ""
    q = query.strip()
    ql = q.lower()
    qp = _load_query_preprocessor()

    matched = None
    for name, patterns in _EP_INTENTS:
        if any(re.search(p, ql) for p in patterns):
            matched = name
            break

    if matched == "who_attended":
        ep = _extract_ep_id(q)
        if ep:
            return {"route": "structured", "intent": "who_attended", "result": kq.who_attended(ep)}
        return {
            "route": "structured",
            "intent": "who_attended",
            "error": "no episode_id (ep_...) in the query",
        }

    if matched == "who_knows":
        subj = _extract_subject(q)
        if len(subj) >= 2:
            return {
                "route": "structured",
                "intent": "who_knows",
                "result": kq.who_knows_subject(subj),
            }
        return {"route": "structured", "intent": "who_knows", "error": "topic not extracted"}

    if matched == "co_participation":
        pid = (
            _resolve_person_in_query(q, qp)
            or OWN_PERSON_ID
            or (kq.resolve_person(OWNER_NAME) if OWNER_NAME else None)
        )
        if pid:
            return {
                "route": "structured",
                "intent": "co_participation",
                "person_id": pid,
                "result": kq.co_participation(pid),
            }
        return {"route": "structured", "intent": "co_participation", "error": "person not resolved"}

    if matched == "person_episodes":
        pid = _resolve_person_in_query(q, qp)
        if pid:
            df = _date_filter(q, qp)
            return {
                "route": "structured",
                "intent": "person_episodes",
                "person_id": pid,
                "result": kq.person_episodes(pid, after=df.get("after"), before=df.get("before")),
            }
        return {"route": "structured", "intent": "person_episodes", "error": "person not resolved"}


    pid = _resolve_person_in_query(q, qp)
    df = _date_filter(q, qp)
    hint = {"tool": "xs-l3-search.py", "query": q}
    if pid:
        hint["person_id"] = pid
    if df:
        hint.update(df)
    return {"route": "semantic", "intent": "content_search", "hint": hint}


def main() -> None:
    ap = argparse.ArgumentParser(description="Router Phase 5: structured vs semantic")
    ap.add_argument("query")
    ap.add_argument("--json", action="store_true", help="full JSON output")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    res = route(args.query)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return

    print(f"route={res['route']} · intent={res['intent']}")
    if res.get("error"):
        print(f"  error: {res['error']}")
    elif res["route"] == "semantic":
        print(f"  → RAG: {json.dumps(res['hint'], ensure_ascii=False)}")
    else:
        r = res.get("result", {})
        for k in ("n_episodes", "n_people", "n_participants", "n_co"):
            if k in r:
                print(f"  {k}={r[k]}")
        for row in (r.get("people") or r.get("participants") or r.get("episodes") or [])[:8]:
            print(f"    {json.dumps(row, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
