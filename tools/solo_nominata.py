#!/usr/bin/env python3
"""Counts the knowledge-base entities that exist only by name: no contact, communication or CRM fact and no human
source, and no participation in an episode. It writes nothing.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_TOOLS / "cross-source") not in sys.path:
    sys.path.insert(0, str(_TOOLS / "cross-source"))

from conteggio import Conteggio  # noqa: E402
from knowledge_schema import (  # noqa: E402
    ATTR_RISCONTRO,
    RISCONTRO_SOLO_NOMINATA,
    riscontri_dichiarati,
)








PREFISSI_CANALE = (
    "contact.",
    "communication.",
    "crm.",
)






SORGENTI_UMANE = frozenset(
    {
        "manual_input",
        "static_import",
        "attio",
        "personio",
        "clickup",
        "org_enrichment",
    }
)




MASSIMO_RECORD = 1





























MINIMO_EPISODI = 1





















CONTEGGIO_RECORD = ("etichettato", "stretto")


@dataclass(frozen=True)
class Giudizio:
    ""





    entita: str
    nome: str
    solo_nominata: bool
    n_fatti: int
    canali: tuple[str, ...] = ()
    sorgenti_umane: tuple[str, ...] = ()
    record_distinti: int = 0



    episodi: int = 0

    gia_marcata: bool = False
    perche: tuple[str, ...] = ()

    def come_dict(self) -> dict:
        return {
            "entita": self.entita,
            "nome": self.nome,
            "solo_nominata": self.solo_nominata,
            "n_fatti": self.n_fatti,
            "canali": list(self.canali),
            "sorgenti_umane": list(self.sorgenti_umane),
            "record_distinti": self.record_distinti,
            "episodi": self.episodi,
            "gia_marcata": self.gia_marcata,
            "perche": list(self.perche),
        }


def _record_di(fatto: dict, come: str = "etichettato") -> set:
    ""










    if come not in CONTEGGIO_RECORD:
        raise ValueError(f"unknown record count: {come!r} (allowed: {CONTEGGIO_RECORD})")
    fuori = set()
    posti = [fatto.get("source") or {}]
    posti += [o for o in (fatto.get("observations") or ()) if isinstance(o, dict)]
    for s in posti:
        rid = str(s.get("record_id") or "").strip()
        if come == "etichettato":


            if rid:
                fuori.add((str(s.get("source_type") or "").strip(), rid))
        else:
            r = rid or str(s.get("source_file") or "").strip()
            if r:
                fuori.add(r)
    return fuori


def giudica(
    entita: str,
    nome: str,
    fatti: list,
    conteggio_record: str = "etichettato",
    episodi: int = 0,
) -> Giudizio:
    ""







    canali: set = set()
    umane: set = set()
    record: set = set()
    for f in fatti or ():
        attr = str(f.get("attribute") or "")
        if attr.startswith(PREFISSI_CANALE):
            canali.add(attr)
        s = f.get("source") or {}
        tipo = str(s.get("source_type") or "").strip().lower()
        if tipo in SORGENTI_UMANE:
            umane.add(tipo)
        for o in f.get("observations") or ():
            if isinstance(o, dict):
                t2 = str(o.get("source_type") or "").strip().lower()
                if t2 in SORGENTI_UMANE:
                    umane.add(t2)
        record |= _record_di(f, conteggio_record)

    perche: list = []
    if canali:
        perche.append(f"has a channel of its own ({sorted(canali)[0]})")
    if umane:
        perche.append(f"asserted by a human or registry source ({sorted(umane)[0]})")
    if len(record) > MASSIMO_RECORD:
        perche.append(f"comes from {len(record)} distinct source records")
    if episodi >= MINIMO_EPISODI:
        perche.append(f"acted in {episodi} real episodes (spoke or was present)")

    solo = not canali and not umane and len(record) <= MASSIMO_RECORD and episodi < MINIMO_EPISODI
    if solo:
        perche = [
            "no channel of its own: we never wrote to it and it never wrote to us",
            "no human and no registry asserted it",
            f"coined from {len(record)} distinct source records (threshold: {MASSIMO_RECORD})",
            "never spoke nor took part in a real episode",
        ]
    return Giudizio(
        entita=entita,
        nome=nome,
        solo_nominata=solo,
        n_fatti=len(fatti or ()),
        canali=tuple(sorted(canali)[:5]),
        sorgenti_umane=tuple(sorted(umane)),
        record_distinti=len(record),
        episodi=episodi,
        gia_marcata=RISCONTRO_SOLO_NOMINATA in riscontri_dichiarati(fatti),
        perche=tuple(perche),
    )


def marchio() -> dict:
    ""











    return {"attribute": ATTR_RISCONTRO, "value": RISCONTRO_SOLO_NOMINATA}







def _cartelle(radice: Path) -> list:
    return [d for d in sorted(radice.iterdir()) if d.is_dir()] if radice.exists() else []


def _partecipazione() -> dict:
    ""






    try:
        import knowledge_view as kv

        crudi = kv._carica_partecipazione()
        return {eid: kv.episodi_di_contatto(c) for eid, c in crudi.items()}
    except Exception:  # pragma: no cover
        return {}


def scorri(
    radice: Path | None = None,
    solo: str | None = None,
    conteggio_record: str = "etichettato",
    partecipazione: dict | None = None,
):
    ""







    import sbk_config as cfg

    base = radice or (cfg.DATA_ROOT / "knowledge" / "entities")
    episodi_di = _partecipazione() if partecipazione is None else partecipazione
    saltati = {
        "unreadable json": 0,
        "without canonical_name": 0,
        "without participation (4th piece not applied)": 0,
    }
    for cartella in _cartelle(Path(base)):
        if solo and cartella.name != solo:
            continue
        for f in sorted(cartella.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                saltati["unreadable json"] += 1
                continue
            nome = (d.get("canonical_name") or "").strip()
            if not nome:
                saltati["without canonical_name"] += 1
            if not episodi_di:
                saltati["without participation (4th piece not applied)"] += 1
            yield (
                cartella.name,
                giudica(
                    f.stem,
                    nome,
                    d.get("facts") or [],
                    conteggio_record,
                    episodi_di.get(f.stem, 0),
                ),
                saltati,
            )


def censisci(
    radice: Path | None = None,
    solo: str | None = None,
    conteggio_record: str = "etichettato",
    partecipazione: dict | None = None,
) -> dict:
    ""






    tot = 0
    marcabili = 0
    fatti_tot = 0
    fatti_marcabili = 0
    salvate = 0
    per_tipo: collections.Counter = collections.Counter()
    per_tipo_marcabili: collections.Counter = collections.Counter()
    gia = 0
    saltati: dict = {}
    for tipo, g, saltati in scorri(radice, solo, conteggio_record, partecipazione):
        tot += 1
        fatti_tot += g.n_fatti
        per_tipo[tipo] += 1
        if g.gia_marcata:
            gia += 1
        if g.solo_nominata:
            marcabili += 1
            fatti_marcabili += g.n_fatti
            per_tipo_marcabili[tipo] += 1
        elif not g.canali and not g.sorgenti_umane and g.record_distinti <= MASSIMO_RECORD:

            salvate += 1
    return {
        "entita": Conteggio(tot, tot, saltati),
        "solo_nominate": Conteggio(marcabili, tot, saltati),
        "salvate_dalla_partecipazione": Conteggio(salvate, tot, saltati),
        "fatti": Conteggio(fatti_tot, fatti_tot, saltati),
        "fatti_delle_solo_nominate": Conteggio(fatti_marcabili, fatti_tot, saltati),
        "gia_marcate_sullo_store": Conteggio(gia, tot, saltati),
        "per_tipo": dict(per_tipo),
        "per_tipo_solo_nominate": dict(per_tipo_marcabili),
    }


def insieme_da_escludere(
    radice: Path | None = None,
    solo: str = "person",
    conteggio_record: str = "etichettato",
    partecipazione: dict | None = None,
) -> frozenset:
    ""





    return frozenset(
        g.entita
        for _, g, _ in scorri(radice, solo, conteggio_record, partecipazione)
        if g.solo_nominata
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The only-NAMED entities — writes nothing")
    ap.add_argument("--tipo", default=None, help="a single folder (e.g. person)")
    ap.add_argument("--esempi", type=int, default=0, help="print N real examples")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--record",
        choices=CONTEGGIO_RECORD,
        default="etichettato",
        help="how a distinct source record is counted",
    )
    a = ap.parse_args(argv)

    m = censisci(solo=a.tipo, conteggio_record=a.record)
    if a.json:
        print(
            json.dumps(
                {k: (v.come_dict() if isinstance(v, Conteggio) else v) for k, v in m.items()},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"entities examined        : {m['entita']}")
        print(
            f"ONLY NAMED               : {m['solo_nominate']} ({m['solo_nominate'].percentuale()}%)"
        )
        print(f"saved by participation   : {m['salvate_dalla_partecipazione']}")
        print(f"total facts              : {m['fatti']}")
        print(
            f"facts of the only-named  : {m['fatti_delle_solo_nominate']} "
            f"({m['fatti_delle_solo_nominate'].percentuale()}%)"
        )
        print(f"already marked in store   : {m['gia_marcate_sullo_store']}")
        print(f"per type                 : {m['per_tipo']}")
        print(f"  of which only named    : {m['per_tipo_solo_nominate']}")
    if a.esempi:
        print("\nreal examples (name · facts · distinct records):")
        n = 0
        for _tipo, g, _s in scorri(solo=a.tipo, conteggio_record=a.record):
            if not g.solo_nominata:
                continue
            print(f"  {g.entita}  {g.nome[:44]:46} {g.n_fatti:4} facts  {g.record_distinti} records")
            n += 1
            if n >= a.esempi:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
