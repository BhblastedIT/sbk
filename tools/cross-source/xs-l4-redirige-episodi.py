#!/usr/bin/env python3
"""L4, run by hand: points the episode references to merged or archived people at their successor profiles (dry run unless --apply)."""



























from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import KNOWLEDGE_DIR, KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-l4-redirige-episodi")

EPISODI_DIR = KNOWLEDGE_DIR / "episodes"
ARCHIVE_DIR = KNOWLEDGE_DIR / "archive"
CAMPI_LISTA = ("referenced_entity_ids", "subject_entity_ids")
CAMPI_DICT = ("participants", "subjects_resolved")


def _vivi() -> set[str]:
    return {p.stem for p in (KNOWLEDGE_ENTITIES_DIR / "person").glob("person_*.json")}


def _successori(vivi: set[str]) -> dict[str, str]:
    ""




    grezzo: dict[str, object] = {}
    for cartella in sorted(ARCHIVE_DIR.iterdir()) if ARCHIVE_DIR.exists() else []:
        if not cartella.is_dir():
            continue
        for f in cartella.glob("person_*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            eid = d.get("entity_id")
            if not eid or eid in grezzo:
                continue
            grezzo[eid] = d.get("merged_into") or d.get("split_into") or d.get("deposito_by")
    mappa: dict[str, str] = {}
    for eid, tgt in grezzo.items():
        if eid in vivi:
            continue
        cur, visti = tgt, {eid}
        for _ in range(10):
            if isinstance(cur, list):
                figli = [c for c in cur if c in vivi]
                cur = figli[0] if len(figli) == 1 else None
            if not isinstance(cur, str) or cur in visti:
                break
            if cur in vivi:
                mappa[eid] = cur
                break
            visti.add(cur)
            cur = grezzo.get(cur)
    return mappa


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="write for real; without it, a dry run")
    ap.add_argument("--campione", type=int, default=10)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    vivi = _vivi()
    succ = _successori(vivi)
    log.info("%d live profiles · %d archived ids with a single successor", len(vivi), len(succ))

    episodi = sorted(EPISODI_DIR.rglob("*.json"))
    tocchi = Counter()
    rotti = Counter()
    file_toccati = 0
    campione: list[str] = []

    for f in episodi:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cambiato = False
        for campo in CAMPI_DICT:
            for p in d.get(campo) or []:
                if not isinstance(p, dict):
                    continue
                pid = p.get("person_id")
                if not isinstance(pid, str) or pid in vivi:
                    continue
                nuovo = succ.get(pid)
                if nuovo:
                    p["person_id"] = nuovo
                    tocchi[pid] += 1
                    cambiato = True
                else:
                    rotti[pid] += 1
        for campo in CAMPI_LISTA:
            v = d.get(campo)
            if not isinstance(v, list):
                continue
            nuova = []
            for pid in v:
                if isinstance(pid, str) and pid not in vivi and succ.get(pid):
                    nuova.append(succ[pid])
                    tocchi[pid] += 1
                    cambiato = True
                else:
                    if isinstance(pid, str) and pid.startswith("person_") and pid not in vivi:
                        rotti[pid] += 1
                    nuova.append(pid)
            d[campo] = nuova
        if not cambiato:
            continue
        file_toccati += 1
        if len(campione) < a.campione:
            campione.append(f"{f.parent.name}/{f.name}  ({d.get('title', '')[:40]})")
        if a.apply:
            safe_write_json(f, d)

    print(f"\n{'APPLY' if a.apply else 'DRY RUN'}")
    print(f"  episodes read            : {len(episodi):,}")
    print(f"  episodes to rewrite      : {file_toccati:,}")
    print(f"  pointers redirected      : {sum(tocchi.values()):,} ({len(tocchi)} distinct ids)")
    print(f"  pointers with no successor: {sum(rotti.values()):,} ({len(rotti)} ids), NOT touched")
    for pid, n in tocchi.most_common(5):
        print(f"      {pid} → {succ[pid]}  ({n:,} times)")
    for riga in campione:
        print(f"      example: {riga}")
    if not a.apply:
        print("\n  (nothing written: add --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
