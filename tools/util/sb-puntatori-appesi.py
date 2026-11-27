#!/usr/bin/env python3
"""Finds who holds an id that no longer exists in the knowledge store, and where it would point once resolved (read-only)."""









































from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import knowledge_resolve as kr  # noqa: E402
from conteggio import Conteggio  # noqa: E402

BRIDGE = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "rq"
    / "entity-bridge.json"
)


PREFISSI_KNOWLEDGE = ("person_", "org_", "organization_", "deal_", "commitment_")


def esamina(bridge: dict, idx: kr.Indice) -> dict:
    per_voce: Counter = Counter()
    ids_appesi: dict[str, kr.Risoluzione] = {}
    ids_vivi_archiviati: set[str] = set()
    esiti: Counter = Counter()
    esempi: list[dict] = []

    for chiave, valore in bridge.items():
        if not isinstance(valore, str):
            per_voce["non-textual value"] += 1
            continue
        if not valore.startswith(PREFISSI_KNOWLEDGE):
            per_voce["outside the knowledge space"] += 1
            continue
        per_voce["knowledge"] += 1
        r = idx.risolvi(valore, tollera_anomalie=True)
        esiti[r.esito] += 1
        if r.esito == "vivo":
            per_voce["alive"] += 1
        elif r.esito == "vivo_e_archiviato":
            per_voce["alive, but with a tombstone"] += 1
            ids_vivi_archiviati.add(valore)
        elif r.esito == "sconosciuto":
            per_voce["dangling without tombstone"] += 1
            ids_appesi[valore] = r
        else:
            per_voce["dangling, resolvable"] += 1
            if valore not in ids_appesi and len(esempi) < 25:
                esempi.append({"chiave": chiave, **r.come_dict()})
            ids_appesi[valore] = r


    chiavi_id = {k for k in bridge if isinstance(k, str) and k.startswith(PREFISSI_KNOWLEDGE)}
    chiavi_appese = {k for k in chiavi_id if k not in idx.vivi}
    chiavi_appese_con_lapide = {k for k in chiavi_appese if k in idx.lapidi}

    valori_id = {
        v for v in bridge.values() if isinstance(v, str) and v.startswith(PREFISSI_KNOWLEDGE)
    }

    riparabili = {i for i, r in ids_appesi.items() if r.redirige}
    ambigui = {i for i, r in ids_appesi.items() if not r.redirige}

    return {
        "voci": dict(per_voce),
        "esiti": dict(esiti),
        "popolazione_valori": Conteggio(
            len({v for v in valori_id if v not in idx.vivi}), len(valori_id), {}
        ).come_dict(),
        "popolazione_chiavi": Conteggio(len(chiavi_appese), len(chiavi_id), {}).come_dict(),
        "chiavi_appese_con_lapide": len(chiavi_appese_con_lapide),
        "id_distinti_appesi": len(ids_appesi),
        "id_riparabili_una_destinazione": len(riparabili),
        "id_non_riparabili": {
            "totale": len(ambigui),
            "per_esito": dict(Counter(ids_appesi[i].esito for i in ambigui)),
        },
        "id_vivi_con_lapide_toccati": len(ids_vivi_archiviati),
        "salti": dict(Counter(r.salti for r in ids_appesi.values())),
        "esempi": esempi,
    }


def stampa(rapporto: dict, idx: kr.Indice) -> None:
    d = idx.diagnosi()
    print(f"store: {d['vivi']} alive · {d['id_archiviati']} archived · {d['lapidi']} tombstones")
    print(
        f"  ⚠️ alive AND archived: {d['vivi_e_archiviati']} "
        f"({' · '.join(f'{k} {v}' for k, v in d['vivi_e_archiviati_per_archivio'].items() if v)})"
    )
    print(f"  id in multiple archives: {d['id_in_piu_archivi']} · self-pointers: {d['auto_puntatori']}")
    print(f"  index built in {d['costruito_in_s']}s (from cache: {d['da_cache']})")
    print()
    print("bridge, by entry:")
    for k, v in sorted(rapporto["voci"].items(), key=lambda kv: -kv[1]):
        print(f"  {v:>7}  {k}")
    pv = rapporto["popolazione_valori"]
    pk = rapporto["popolazione_chiavi"]
    print()
    print(
        f"dangling on distinct VALUES:  {pv['valore']} / {pv['su']}  ({pv['valore'] / pv['su']:.2%})"
    )
    print(
        f"dangling on distinct KEYS:    {pk['valore']} / {pk['su']}  ({pk['valore'] / pk['su']:.2%})"
    )
    print(f"  of which with tombstone (resolvable): {rapporto['chiavi_appese_con_lapide']}")
    print()
    print(f"distinct dangling ids found from values: {rapporto['id_distinti_appesi']}")
    print(f"  repairable (ONE live target): {rapporto['id_riparabili_una_destinazione']}")
    print(f"  NOT repairable: {rapporto['id_non_riparabili']}")
    print(
        f"  alive-with-tombstone ids that a naive redirect would have moved: "
        f"{rapporto['id_vivi_con_lapide_toccati']}"
    )
    print(f"  hops needed: {rapporto['salti']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bridge", default=str(BRIDGE), help="the file to examine (read-only)")
    ap.add_argument("--store", default=None, help="knowledge store root")
    ap.add_argument("--cache", default=None, help="index seed (optional)")
    ap.add_argument("--rapporto", default=None, help="where to write the report JSON")
    args = ap.parse_args()

    try:
        idx = kr.Indice.costruisci(args.store, cache=args.cache)
    except kr.MacchinaPiena as e:
        print(f"⏸  {e}", file=sys.stderr)
        return 75

    percorso = Path(args.bridge)
    if not percorso.exists():
        print(f"{percorso} does not exist", file=sys.stderr)
        return 2
    bridge = json.loads(percorso.read_bytes())
    if not isinstance(bridge, dict):
        print(f"{percorso} is not a map", file=sys.stderr)
        return 2

    rapporto = esamina(bridge, idx)
    rapporto["sorgente"] = str(percorso)
    rapporto["generato"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    rapporto["store"] = idx.diagnosi()
    stampa(rapporto, idx)

    if args.rapporto:
        p = Path(args.rapporto)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rapporto, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nreport → {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
