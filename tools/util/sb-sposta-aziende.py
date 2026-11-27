#!/usr/bin/env python3
"""Moves into the organization folder the person entities the reclassification registry proved to be companies.
Dry run by default; --esegui writes, with a journal.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

ENT = cfg.DATA_ROOT / "knowledge" / "entities"
PERSON = ENT / "person"
ORG = ENT / "organization"
REGISTRO = cfg.DATA_ROOT / "knowledge" / "reclassification" / "gate0a-person-to-org.jsonl"
JOURNAL = cfg.DATA_ROOT / "knowledge" / "meta" / "sposta-aziende-journal.jsonl"


TIER_AMMESSI = {"T1", "T1b", "dual-homed"}


def _righe() -> list[dict]:
    if not REGISTRO.exists():
        return []
    return [json.loads(x) for x in REGISTRO.read_text(encoding="utf-8").splitlines() if x.strip()]


def pianifica() -> dict:
    ""
    p = {
        "sposta": [],
        "fonde": [],
        "gia_fatto": 0,
        "assenti": 0,
        "tier_scartati": collections.Counter(),
    }
    for r in _righe():
        if r.get("tier") not in TIER_AMMESSI:
            p["tier_scartati"][r.get("tier")] += 1
            continue
        f = PERSON / f"{r['person_id']}.json"
        if not f.exists():
            p["gia_fatto" if (ORG / f"{r['person_id']}.json").exists() else "assenti"] += 1
            continue
        dest = ORG / f"{r['person_id']}.json"
        (p["fonde"] if dest.exists() else p["sposta"]).append(
            {
                "eid": r["person_id"],
                "nome": r.get("matched_name"),
                "fatti": r.get("n_facts", 0),
                "tier": r["tier"],
            }
        )
    return p


def esegui(dry: bool = True) -> dict:
    esito = collections.Counter()
    journal = []
    for r in _righe():
        if r.get("tier") not in TIER_AMMESSI:
            continue
        src = PERSON / f"{r['person_id']}.json"
        if not src.exists():
            continue
        try:
            d = json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # pragma: no cover
            esito["illeggibili"] += 1
            continue

        fatti = d.get("facts") or []
        d["entity_type"] = "organization"
        d.setdefault("facts", []).append(
            {
                "fact_id": f"gate0a-{r['person_id']}",
                "entity_id": r["person_id"],
                "entity_type": "organization",
                "attribute": "identity.entity_type",
                "value": "organization",
                "confidence": 0.95,
                "valid_from": datetime.now(UTC).date().isoformat(),
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": {
                    "source_type": "manual_input",
                    "source_file": f"gate0a-{r['tier']}",
                    "record_id": str(r.get("matched_name") or "")[:60],
                    "extracted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            }
        )

        dest = ORG / f"{r['person_id']}.json"
        op = "fonde" if dest.exists() else "sposta"
        if not dry:
            if op == "fonde":



                try:
                    vecchio = json.loads(dest.read_text(encoding="utf-8"))
                    visti = {json.dumps(x, sort_keys=True) for x in (vecchio.get("facts") or [])}
                    vecchio["facts"] = (vecchio.get("facts") or []) + [
                        x for x in d["facts"] if json.dumps(x, sort_keys=True) not in visti
                    ]
                    d = vecchio
                except (json.JSONDecodeError, OSError):  # pragma: no cover
                    pass
            dest.write_text(json.dumps(d, ensure_ascii=False, indent=1))
            src.unlink()

        esito[op] += 1
        esito["fatti"] += len(fatti)
        journal.append(
            {
                "op": op,
                "da": f"person/{r['person_id']}",
                "a": f"organization/{r['person_id']}",
                "tier": r["tier"],
                "nome": r.get("matched_name"),
                "fatti": len(fatti),
                "fact_id": [str(x.get("fact_id") or "") for x in fatti],
            }
        )

    if not dry and journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            for x in journal:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    return dict(esito)


def main() -> int:
    ap = argparse.ArgumentParser(description="Move into organization/ the entities that are companies")
    ap.add_argument("--esegui", action="store_true", help="without this it touches nothing")
    a = ap.parse_args()

    p = pianifica()
    print(
        f"\nto move     : {len(p['sposta'])} entities, {sum(x['fatti'] for x in p['sposta'])} facts"
    )
    print(
        f"to merge    : {len(p['fonde'])} (dual-homed: the id already exists in organization/), "
        f"{sum(x['fatti'] for x in p['fonde'])} facts"
    )
    print(f"already done: {p['gia_fatto']}   ·   not found: {p['assenti']}")
    if p["tier_scartati"]:
        print(f"tiers discarded (no proof): {dict(p['tier_scartati'])}")
    print("\nthe biggest ones:")
    for x in sorted(p["sposta"] + p["fonde"], key=lambda y: -y["fatti"])[:10]:
        print(f"   [{x['tier']:11}] {str(x['nome'])[:36]:36} {x['fatti']:6} facts")

    if not a.esegui:
        print("\n  dry run: nothing was touched. With --esegui it writes.")
        return 0

    print("\nRUNNING…")
    r = esegui(dry=False)
    print(
        f"   moved: {r.get('sposta', 0)}   merged: {r.get('fonde', 0)}   facts: {r.get('fatti', 0)}"
    )
    print(f"   journal : {JOURNAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
