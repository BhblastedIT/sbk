"""The deposit of homeless facts: facts the pipeline refused to attach to a new entity (unknown, relationship,
role...) are kept in deposito/fatti.jsonl instead of being lost. --riepilogo summarizes a deposit, --ripesca
fishes facts back out by name, rule or id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "PERCORSO",
    "REGOLE",
    "Deposito",
    "Riga",
    "esigi_fuori_da_entities",
    "rileggi",
    "ripesca",
]




PERCORSO = "deposito/fatti.jsonl"








REGOLE = ("ignoto", "relazione", "registro", "manuale", "designatore", "archivio")


class DepositoDentroEntities(RuntimeError):
    ""


def esigi_fuori_da_entities(percorso: Path | str, dove: str = "") -> None:
    ""






    p = Path(percorso).resolve()
    if any(parte == "entities" for parte in p.parts):
        raise DepositoDentroEntities(
            f"the deposit cannot live inside `entities/`: {p}" + (f" ({dove})" if dove else "")
        )


@dataclass(frozen=True)
class Riga:
    ""






    nome: str
    regola: str
    motivo: str
    fatti: list = field(default_factory=list)
    famiglia: str = ""
    entity_id_evitato: str = ""
    id_ignoto: str = ""
    ancora: str = ""
    source_file: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not self.motivo:
            raise ValueError("a deposit row without a reason is not reviewable")
        if self.regola not in REGOLE:
            raise ValueError(f"unknown rule: {self.regola!r} (expected: {REGOLE})")

    def come_dict(self, run_id: str = "") -> dict:
        import datetime as _dt

        return {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),  # noqa: UP017
            "run_id": run_id,
            "regola": self.regola,
            "famiglia": self.famiglia,
            "motivo": self.motivo,
            "nome": self.nome,
            "entity_id_evitato": self.entity_id_evitato,
            "id_ignoto": self.id_ignoto,
            "ancora": self.ancora,
            "source_file": self.source_file,
            "record_id": self.record_id,
            "n_fatti": len(self.fatti),
            "fatti": list(self.fatti),
        }


class Deposito:
    ""








    def __init__(self, store=None, *, percorso=None, run_id: str = ""):
        import datetime as _dt

        if percorso is None and store is None:
            raise ValueError("needs `store` (the root) or `percorso` (the file)")
        self.percorso = Path(percorso) if percorso else (Path(store) / PERCORSO)
        esigi_fuori_da_entities(self.percorso, "Deposito.__init__")
        self.run_id = run_id or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        self.conteggi: dict = {"righe": 0, "fatti": 0, "per_regola": {}}

    def deposita(self, riga: Riga) -> dict:
        ""




        d = riga.come_dict(self.run_id)
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        with self.percorso.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
        self.conteggi["righe"] += 1
        self.conteggi["fatti"] += d["n_fatti"]
        per = self.conteggi["per_regola"]
        per[riga.regola] = per.get(riga.regola, 0) + 1
        return d

    def stats(self) -> dict:
        return {"percorso": str(self.percorso), "run_id": self.run_id, **self.conteggi}


def _righe(percorso: Path | str):
    ""
    p = Path(percorso)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for riga in fh:
            riga = riga.strip()
            if not riga:
                continue
            try:
                yield json.loads(riga)
            except ValueError:
                yield {"_illeggibile": riga[:200]}


def rileggi(percorso: Path | str) -> dict:
    ""






    import collections

    fuori = {
        "righe": 0,
        "fatti": 0,
        "illeggibili": 0,
        "regole": collections.Counter(),
        "famiglie": collections.Counter(),
        "nomi": collections.Counter(),
        "fatti_per_nome": collections.Counter(),
        "entita_evitate": set(),
    }
    if not Path(percorso or PERCORSO).exists():
        return fuori
    for d in _righe(percorso):
        if "_illeggibile" in d:
            fuori["illeggibili"] += 1
            continue
        fuori["righe"] += 1
        n = int(d.get("n_fatti") or 0)
        fuori["fatti"] += n
        fuori["regole"][d.get("regola", "?")] += 1
        fuori["famiglie"][d.get("famiglia", "")] += 1
        fuori["nomi"][d.get("nome", "")] += 1
        fuori["fatti_per_nome"][d.get("nome", "")] += n
        if d.get("entity_id_evitato"):
            fuori["entita_evitate"].add(d["entity_id_evitato"])
    return fuori


def ripesca(
    percorso: Path | str,
    *,
    nome: str = "",
    regola: str = "",
    id_ignoto: str = "",
    entity_id_evitato: str = "",
):
    ""









    nome_l = (nome or "").strip().lower()
    for d in _righe(percorso):
        if "_illeggibile" in d:
            continue
        if nome_l and (d.get("nome", "") or "").strip().lower() != nome_l:
            continue
        if regola and d.get("regola") != regola:
            continue
        if id_ignoto and d.get("id_ignoto") != id_ignoto:
            continue
        if entity_id_evitato and d.get("entity_id_evitato") != entity_id_evitato:
            continue
        contesto = {k: v for k, v in d.items() if k != "fatti"}
        for f in d.get("fatti") or []:
            yield contesto, f


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="the deposit of homeless facts: inspect and fish back out")
    ap.add_argument("--riepilogo", help="summarize a deposit (fatti.jsonl)")
    ap.add_argument("--ripesca", help="the deposit to fish from")
    ap.add_argument("--nome", default="", help="filter: the rejected name")
    ap.add_argument("--regola", default="", help=f"filter: one of {REGOLE}")
    ap.add_argument("--id-ignoto", default="", help="filter: the unknown's id")
    ap.add_argument("--out", help="where to write the fished-out facts (JSONL); without it, to screen")
    a = ap.parse_args()

    if a.riepilogo:
        d = rileggi(a.riepilogo)
        print(f"\n  {a.riepilogo}")
        print(f"  rows (rejected coinages): {d['righe']:,} · unreadable: {d['illeggibili']}")
        print(f"  facts put to safety    : {d['fatti']:,}")
        print(f"  entities that were not born: {len(d['entita_evitate']):,}")
        print(f"  per rule    : {dict(d['regole'])}")
        print(f"  per family  : {dict(d['famiglie'])}")
        print("\n  the twenty names with the most facts in the deposit:")
        for n, k in d["fatti_per_nome"].most_common(20):
            print(f"    {k:>6} facts  «{n[:60]}»")
        return 0

    if a.ripesca:
        import contextlib

        n = 0
        with contextlib.ExitStack() as pila:
            fh = pila.enter_context(open(a.out, "w", encoding="utf-8")) if a.out else None
            for contesto, f in ripesca(
                a.ripesca, nome=a.nome, regola=a.regola, id_ignoto=a.id_ignoto
            ):
                n += 1
                riga = json.dumps({"da": contesto, "fatto": f}, ensure_ascii=False, default=str)
                if fh:
                    fh.write(riga + "\n")
                elif n <= 20:
                    print(riga[:300])
        print(f"\n  fished out {n:,} facts" + (f" → {a.out}" if a.out else ""))
        print("  ⚠️ which entity they belong to is decided by a human: the deposit does not guess.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
