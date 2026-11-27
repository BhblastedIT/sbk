#!/usr/bin/env python3
"""Looks for pathologies across the entity folders of the knowledge base (empty folders, group names, company
duplicates...) and prints the worst cases.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

ENT = cfg.DATA_ROOT / "knowledge" / "entities"
CARTELLE = ("person", "organization", "org", "deal", "commitment")

_GRUPPO = re.compile(r"[,&/]|\s(?:e|and)\s|\[")


def nudo(s: str) -> str:
    ""











    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def chiave_azienda(s: str) -> str:
    ""
    try:
        return cfg.chiave_organizzazione(s)
    except Exception:  # pragma: no cover
        return nudo(s).replace(" ", "")


def scorri(cartella: str):
    d = ENT / cartella
    if not d.exists():
        return
    for f in sorted(d.glob("*.json")):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        yield f.stem, (e.get("canonical_name") or "").strip(), e.get("facts") or []


def esamina(cartella: str) -> dict:
    righe = list(scorri(cartella))
    patologie: collections.Counter = collections.Counter()
    per_nudo: dict[str, list] = collections.defaultdict(list)
    per_azienda: dict[str, list] = collections.defaultdict(list)
    for eid, nome, fatti in righe:
        n = len(fatti)
        k = nudo(nome)
        if k:
            per_nudo[k].append((nome, n, eid))
        ka = chiave_azienda(nome)
        if ka:
            per_azienda[ka].append((nome, n, eid))
        if _GRUPPO.search(nome):
            patologie["group-record"] += 1
        if "(" in nome:
            patologie["context parenthetical"] += 1
        if "@" in nome:
            patologie["the name is an address"] += 1
        if k and len(k.split()) == 1:
            patologie["single-word name"] += 1
        if nome.startswith(("person_", "org_", "organization_")):
            patologie["the name is the identifier"] += 1
    dup = {k: v for k, v in per_nudo.items() if len(v) > 1}
    dup_az = {k: v for k, v in per_azienda.items() if len(v) > 1}
    return {
        "cartella": cartella,
        "entita": len(righe),
        "fatti": sum(len(f) for _, _, f in righe),
        "patologie": dict(patologie),
        "duplicati": dup,
        "record_duplicati": sum(len(v) for v in dup.values()),
        "fatti_duplicati": sum(sum(n for _, n, _ in v) for v in dup.values()),
        "duplicati_azienda": dup_az,
        "record_duplicati_azienda": sum(len(v) for v in dup_az.values()),
        "fatti_duplicati_azienda": sum(sum(n for _, n, _ in v) for v in dup_az.values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="The pathologies across all entity folders")
    ap.add_argument("--cartella", default="", help="a single folder")
    ap.add_argument("--quanti", type=int, default=10)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    tutto = []
    for c in CARTELLE:
        if a.cartella and c != a.cartella:
            continue
        r = esamina(c)
        tutto.append(r)
        if not r["entita"]:
            print(f"\n── {c}/  ⚠️  EMPTY folder (CLAUDE.md marks it as a primary source)")
            continue
        print(f"\n── {c}/  {r['entita']} entities, {r['fatti']} facts")
        for k, v in sorted(r["patologie"].items(), key=lambda x: -x[1]):
            print(f"     {k:30} {v:5}  ({100 * v / r['entita']:4.1f}%)")
        if r["duplicati_azienda"] and c in ("organization", "org"):
            print(
                f"     {'even removing the ACRONYMS':30} {len(r['duplicati_azienda']):5} keys over "
                f"{r['record_duplicati_azienda']} records, {r['fatti_duplicati_azienda']} facts"
            )
            peggio = sorted(
                r["duplicati_azienda"].items(), key=lambda x: -sum(n for _, n, _ in x[1])
            )
            for k, v in peggio[:5]:
                print(f"        «{k[:26]:26}» {len(v):3} records, {sum(n for _, n, _ in v):6} facts")
        if r["duplicati"]:
            print(
                f"     {'DUPLICATE NAMES':30} {len(r['duplicati']):5} names over "
                f"{r['record_duplicati']} records, {r['fatti_duplicati']} facts"
            )
            peggio = sorted(r["duplicati"].items(), key=lambda x: -sum(n for _, n, _ in x[1]))
            for k, v in peggio[: a.quanti]:
                capi = sorted(v, key=lambda x: -x[1])
                print(
                    f"        «{k[:26]:26}» {len(v):3} records, {sum(n for _, n, _ in v):6} facts"
                    f"   the largest: {capi[0][1]}"
                )

    print("\n  ⚠️  No entity is touched. A merge between organizations is as irreversible")
    print("      as one between people, and the biggest name is not always the right one.")
    if a.json:
        Path(a.json).write_text(json.dumps(tutto, ensure_ascii=False, indent=1, default=str))
        print(f"\n  saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
