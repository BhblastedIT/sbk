#!/usr/bin/env python3
"""Splits the "Speaker N" chimeras of the knowledge base (one entity collecting the generic speaker of many
recordings) into one pseudo-identity per recording. Dry run by default; --esegui writes, with a journal.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_CROSS = Path(__file__).resolve().parent.parent / "cross-source"
if str(_CROSS) not in sys.path:
    sys.path.insert(0, str(_CROSS))

from knowledge_schema import e_pseudo_identita, fatto_marchio_pseudo  # noqa: E402

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"

JOURNAL = cfg.DATA_ROOT / "knowledge" / "meta" / "split-speaker-journal.jsonl"

_ETICHETTA = re.compile(r"^(speaker|persona|participant)[\s_]*\d*\b", re.IGNORECASE)


def e_chimera(nome: str) -> bool:
    return bool(_ETICHETTA.match((nome or "").strip()))


def gia_divisa(fatti) -> bool:
    ""












    return e_pseudo_identita(fatti)


def _id(chiave: str) -> str:
    return "person_" + hashlib.sha256(chiave.encode()).hexdigest()[:8]


_MAPPA: dict[str, str] | None = None


def _mappa_fatto_registrazione() -> dict[str, str]:
    ""










    global _MAPPA  # noqa: PLW0603
    if _MAPPA is not None:
        return _MAPPA
    _MAPPA = {}
    f = cfg.DATA_ROOT / "l3" / "nlp" / "deep-facts.parquet"
    if not f.exists():  # pragma: no cover
        return _MAPPA
    try:
        import duckdb

        c = duckdb.connect()
        c.execute("SET memory_limit='2GB'")
        for fid, sid in c.execute(f"SELECT fact_id, source_id FROM '{f}'").fetchall():  # noqa: S608
            if fid and sid:
                _MAPPA[str(fid)] = str(sid)
        c.close()
    except Exception:  # pragma: no cover
        pass
    return _MAPPA


def _registrazione(fatto: dict) -> str:
    ""






    s = fatto.get("source") or {}
    rid = str(s.get("record_id") or "").strip()
    return _mappa_fatto_registrazione().get(rid, "") if rid else ""


def pianifica() -> dict:
    ""
    piano = {
        "entita": [],
        "fatti_totali": 0,
        "fatti_senza_ancora": 0,
        "pseudo": set(),


        "gia_pseudo": 0,
    }
    for f in sorted(PERSON.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        nome = (d.get("canonical_name") or "").strip()
        if not e_chimera(nome):
            continue
        if gia_divisa(d.get("facts") or []):
            piano["gia_pseudo"] += 1
            continue
        gruppi: dict[str, int] = collections.Counter()
        orfani = 0
        for x in d.get("facts") or []:
            r = _registrazione(x)
            if r:
                gruppi[r] += 1
            else:
                orfani += 1
        if not gruppi:
            continue
        piano["entita"].append(
            {
                "eid": f.stem,
                "nome": nome,
                "fatti": len(d.get("facts") or []),
                "registrazioni": len(gruppi),
                "orfani": orfani,
            }
        )
        piano["fatti_totali"] += sum(gruppi.values())
        piano["fatti_senza_ancora"] += orfani
        for r in gruppi:
            piano["pseudo"].add(f"{r}|{nome}")
    piano["pseudo"] = len(piano["pseudo"])
    return piano



_FONTE_MARCHIO = "tools/util/sb-split-speaker.py"


def esegui(dry: bool = True) -> dict:
    esito = {
        "entita_divise": 0,
        "pseudo_create": 0,
        "fatti_spostati": 0,
        "fatti_rimasti": 0,


        "marchi_scritti": 0,

        "gia_pseudo": 0,
    }
    righe_journal = []
    for f in sorted(PERSON.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        nome = (d.get("canonical_name") or "").strip()
        if not e_chimera(nome):
            continue
        if gia_divisa(d.get("facts") or []):
            esito["gia_pseudo"] += 1
            continue
        per_reg: dict[str, list] = collections.defaultdict(list)
        rimasti = []
        for x in d.get("facts") or []:
            r = _registrazione(x)
            (per_reg[r].append(x) if r else rimasti.append(x))
        if not per_reg:
            continue

        esito["entita_divise"] += 1
        for reg, fatti in per_reg.items():
            eid = _id(f"{reg}|{nome}")






            data = reg[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", reg) else "no-date"
            breve = f"{data} #{eid[-4:]}"
            nuovo = {
                "entity_id": eid,
                "entity_type": "person",
                "canonical_name": f"{nome} @ {breve}",
                "facts": [{**x, "entity_id": eid} for x in fatti],
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": 1,
            }
            esito["pseudo_create"] += 1
            esito["fatti_spostati"] += len(fatti)





            righe_journal.append(
                {
                    "op": "split",
                    "da": f.stem,
                    "a": eid,
                    "registrazione": reg,
                    "fatti": len(fatti),
                    "fact_id": [str(x.get("fact_id") or "") for x in fatti],
                }
            )
            if not dry:
                p = PERSON / f"{eid}.json"
                if p.exists():

                    try:
                        vecchio = json.loads(p.read_text(encoding="utf-8"))
                        visti = {json.dumps(y, sort_keys=True) for y in vecchio.get("facts") or []}
                        nuovo["facts"] = (vecchio.get("facts") or []) + [
                            y for y in nuovo["facts"] if json.dumps(y, sort_keys=True) not in visti
                        ]
                    except (json.JSONDecodeError, OSError):  # pragma: no cover
                        pass







                if not e_pseudo_identita(nuovo["facts"]):
                    nuovo["facts"].append(fatto_marchio_pseudo(eid, fonte=_FONTE_MARCHIO))
                    esito["marchi_scritti"] += 1
                p.write_text(json.dumps(nuovo, ensure_ascii=False, indent=1))

        esito["fatti_rimasti"] += len(rimasti)
        if not dry:

            d["facts"] = rimasti
            d["canonical_name"] = f"{nome} (chimera emptied by the split)"
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1))

    if not dry and righe_journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            for r in righe_journal:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(description="Splits the «Speaker N» chimeras by recording")
    ap.add_argument("--esegui", action="store_true", help="without this, it touches nothing")
    a = ap.parse_args()

    p = pianifica()
    print(f"\nchimeras found: {len(p['entita'])}")
    print(f"already pseudo-identities (not re-split): {p['gia_pseudo']}")
    print(f"pseudo-identities that would be created: {p['pseudo']}")
    print(f"facts with an anchor to the recording: {p['fatti_totali']}")
    print(f"facts WITHOUT an anchor (stay where they are): {p['fatti_senza_ancora']}")
    print("\nthe biggest:")
    for e in sorted(p["entita"], key=lambda x: -x["fatti"])[:8]:
        print(
            f"   {e['nome'][:34]:34} {e['fatti']:5} facts → {e['registrazioni']:3} recordings"
            + (f"  ({e['orfani']} without anchor)" if e["orfani"] else "")
        )

    if not a.esegui:
        print("\n  dry run: nothing was touched. With --esegui it writes.")
        return 0

    print("\nRUNNING…")
    r = esegui(dry=False)
    print(f"   entities split     : {r['entita_divise']}")
    print(f"   pseudo-identities  : {r['pseudo_create']}")
    print(f"   facts moved        : {r['fatti_spostati']}")
    print(f"   facts remaining    : {r['fatti_rimasti']} (no anchor to the recording)")
    print(f"   marks written      : {r['marchi_scritti']} (outside the people census)")
    print(f"   already pseudo     : {r['gia_pseudo']} (not re-split)")
    print(f"   journal            : {JOURNAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
