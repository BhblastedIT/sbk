#!/usr/bin/env python3
"""L4, run by hand: moves person profiles created by mistake (composites, non-people) to the archive deposit (dry run unless --apply)."""























from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import shutil
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (  # noqa: E402
    KNOWLEDGE_DIR,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_FACTS_DIR,
    safe_write_json,
)

log = logging.getLogger("sbk-l4-deposita-nati")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
FACTS_PERSON_DIR = KNOWLEDGE_FACTS_DIR / "person"
ARCHIVE_DIR = KNOWLEDGE_DIR / "archive" / "deposito"
CHIAVI_FORTI = ("identity.email", "crm.attio_record_id", "identity.linkedin_url")


def _chiavi_forti(profilo: dict) -> list[str]:
    return sorted(
        {
            f.get("attribute", "")
            for f in profilo.get("facts", [])
            if f.get("attribute", "") in CHIAVI_FORTI
        }
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--ids", required=True, help="JSON file with the list of entity_id")
    ap.add_argument(
        "--motivo", required=True, help="why they go to the deposit (ends up in every row)"
    )
    ap.add_argument("--apply", action="store_true", help="actually writes; without it, dry run")
    ap.add_argument("--campione", type=int, default=15, help="how many names to print")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ids = json.loads(Path(a.ids).read_text())
    if not isinstance(ids, list) or not ids:
        log.error("the id list is empty or not a list")
        return 2

    from deposito import Deposito, Riga

    run_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
    dep = Deposito(store=KNOWLEDGE_DIR, run_id=run_id) if a.apply else None

    da_fare: list[tuple[str, dict, Path]] = []
    saltati: dict[str, list[str]] = {"assente": [], "chiave_forte": []}
    for eid in ids:
        p = PERSON_DIR / f"{eid}.json"
        if not p.exists():
            saltati["assente"].append(eid)
            continue
        profilo = json.loads(p.read_text())
        chiavi = _chiavi_forti(profilo)
        if chiavi:
            saltati["chiave_forte"].append(f"{eid} «{profilo.get('canonical_name', '')}» {chiavi}")
            continue
        da_fare.append((eid, profilo, p))

    n_fatti = sum(len(pr.get("facts", [])) for _, pr, _ in da_fare)
    print(f"\n{'APPLY' if a.apply else 'DRY RUN'} — run {run_id}")
    print(f"  ids in list            : {len(ids)}")
    print(f"  to deposit             : {len(da_fare)}  ({n_fatti} facts)")
    print(f"  skipped, profile absent : {len(saltati['assente'])}")
    print(f"  skipped, strong key    : {len(saltati['chiave_forte'])}")
    for s in saltati["chiave_forte"]:
        print(f"      ⚠️ {s}")
    print(f"  sample ({min(a.campione, len(da_fare))}):")
    for eid, pr, _ in da_fare[: a.campione]:
        print(
            f"      {eid}  «{pr.get('canonical_name', '')[:60]}»  {len(pr.get('facts', []))} facts"
        )

    if not a.apply:
        print("\n  (no writes: add --apply)")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    fatti_dep = 0
    for eid, profilo, p in da_fare:
        riga = Riga(
            nome=profilo.get("canonical_name") or eid,
            regola="manuale",
            motivo=a.motivo,
            fatti=list(profilo.get("facts", [])),
            entity_id_evitato=eid,
            source_file="xs-l4-deposita-nati",
        )
        d = dep.deposita(riga)
        fatti_dep += int(d["n_fatti"])
        lapide = {
            **profilo,
            "status": "deposito",
            "deposito_date": _dt.datetime.now(_dt.timezone.utc).isoformat(),  # noqa: UP017
            "deposito_by": "xs-l4-deposita-nati",
            "deposito_run_id": run_id,
            "deposito_motivo": a.motivo,
        }
        safe_write_json(ARCHIVE_DIR / p.name, lapide)
        jl = FACTS_PERSON_DIR / f"{eid}.jsonl"
        if jl.exists():
            shutil.move(str(jl), str(ARCHIVE_DIR / jl.name))
        p.unlink()
    print(f"\n  deposited {len(da_fare)} profiles, {fatti_dep} facts → {dep.percorso}")
    print(f"  archived in {ARCHIVE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
