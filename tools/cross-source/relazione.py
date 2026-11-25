""

































































from __future__ import annotations

import os
import re
from dataclasses import dataclass

__all__ = [
    "ENV_MODALITA",
    "PERCORSO_DIARIO",
    "PERCORSO_SPEGNIMENTO",
    "Decisione",
    "Giudizio",
    "Sentinella",
    "giudica",
    "spezza",
]





_SEPARATORI = re.compile(r"\s*(?:,|/|&|\+|;|\||\band\b|\be\b|\bcon\b)\s*", re.I)



_PAREN = re.compile(r"\(.*?\)|\[.*?\]")



PERCORSO_SPEGNIMENTO = "meta/relazione-OFF"


PERCORSO_DIARIO = "resolutions/relazioni.jsonl"


ENV_MODALITA = "SBK_RELAZIONE"


def spezza(nome: str) -> list[str]:
    ""
    nudo = _PAREN.sub(" ", str(nome or ""))
    return [p for p in (x.strip(" .;-–—_'\"") for x in _SEPARATORI.split(nudo)) if p]


@dataclass(frozen=True)
class Giudizio:
    ""





    nome: str
    parti: tuple
    entita: tuple
    motivo: str

    @property
    def coppia(self) -> str:
        return " ↔ ".join(self.entita)


def _e_composito(nome: str) -> bool:
    ""





    try:
        import confrontabile as _c

        return "composito" in _c.giudica(str(nome or ""), "person").codici
    except Exception:  # noqa: BLE001 - pragma: no cover
        return False


def giudica(
    nome: str,
    *,
    risolvi,
    ha_chiave_forte,
    chiave_propria: str = "",
) -> Giudizio | None:
    ""












    testo = str(nome or "").strip()
    if not testo:
        return None
    if str(chiave_propria or "").strip():
        return None
    if not _e_composito(testo):
        return None

    parti = spezza(testo)
    if len(parti) < 2:
        return None

    ids = []
    for p in parti:
        eid = risolvi(p) or ""
        if not eid:
            return None
        ids.append(eid)

    if len(set(ids)) != len(ids):
        return None

    forti = [bool(ha_chiave_forte(e)) for e in ids]
    if not any(forti):
        return None
    for p, f in zip(parti, forti):
        if not f and len(p.split()) < 2:
            return None

    return Giudizio(
        nome=testo,
        parti=tuple(parti),
        entita=tuple(ids),
        motivo=(
            f"the {len(parti)} parts resolve to entities that already exist "
            f"({', '.join(ids)}): it is a relationship, not an entity"
        ),
    )





@dataclass(frozen=True)
class Decisione:
    ""

    nome: str
    azione: str
    avrebbe: str
    entity_id: str = ""
    giudizio: Giudizio | None = None
    motivo: str = ""

    def come_riga(self, run_id: str = "") -> dict:
        import datetime as _dt

        g = self.giudizio
        return {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),  # noqa: UP017
            "run_id": run_id,
            "nome": self.nome,
            "azione": self.azione,
            "avrebbe": self.avrebbe,
            "entity_id_evitato": self.entity_id,
            "parti": list(g.parti) if g else [],
            "entita": list(g.entita) if g else [],
            "motivo": self.motivo,
        }


class Sentinella:
    ""











    def __init__(
        self,
        *,
        risolvi,
        ha_chiave_forte,
        modalita: str = "ombra",
        store=None,
        diario=None,
        run_id: str = "",
    ):
        if modalita not in ("ombra", "blocco"):
            raise ValueError(f"unknown mode: {modalita!r}")
        import datetime as _dt
        from pathlib import Path as _P

        self.risolvi = risolvi
        self.ha_chiave_forte = ha_chiave_forte
        self.modalita = modalita
        self.store = _P(store) if store else None
        self.diario = _P(diario) if diario else None
        self.run_id = run_id or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        self.conteggi: dict = {
            "consultazioni": 0,
            "relazioni": 0,
            "non_coniati": 0,
            "spento": 0,
        }
        self._interruttore = (self.store / PERCORSO_SPEGNIMENTO) if self.store else None

    @property
    def spento(self) -> bool:
        return bool(self._interruttore and self._interruttore.exists())

    def al_conio(
        self,
        nome: str,
        *,
        email: str = "",
        entity_id: str = "",
    ) -> Decisione:
        ""
        self.conteggi["consultazioni"] += 1
        g = giudica(
            nome,
            risolvi=self.risolvi,
            ha_chiave_forte=self.ha_chiave_forte,
            chiave_propria=email or "",
        )
        if g is None:
            return Decisione(nome, "conia", "conia", entity_id, None, "not a relationship")

        self.conteggi["relazioni"] += 1
        if self.spento:
            self.conteggi["spento"] += 1
            d = Decisione(nome, "conia", "non_coniare", entity_id, g, g.motivo + " · KILL-SWITCH")
            self._diario(d)
            return d
        if self.modalita == "ombra":
            d = Decisione(nome, "conia", "non_coniare", entity_id, g, g.motivo)
            self._diario(d)
            return d
        self.conteggi["non_coniati"] += 1
        d = Decisione(nome, "non_coniare", "non_coniare", entity_id, g, g.motivo)
        self._diario(d)
        return d

    def _diario(self, d: Decisione) -> None:
        if not self.diario:
            return
        import json as _json

        self.diario.parent.mkdir(parents=True, exist_ok=True)
        with self.diario.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(d.come_riga(self.run_id), ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        return {"modalita": self.modalita, "run_id": self.run_id, **self.conteggi}


def modalita_da_ambiente() -> str:
    ""
    m = os.environ.get(ENV_MODALITA, "ombra").strip().lower()
    return m if m in ("ombra", "blocco") else "ombra"


def rileggi_diario(percorso) -> dict:
    ""





    import collections
    import json as _json
    from pathlib import Path as _P

    p = _P(percorso or PERCORSO_DIARIO)
    fuori = {
        "righe": 0,
        "illeggibili": 0,
        "nomi": collections.Counter(),
        "coppie": collections.Counter(),
        "entita_evitate": set(),
        "bloccati": 0,
    }
    if not _P(percorso or PERCORSO_DIARIO).exists():
        return fuori
    with p.open(encoding="utf-8") as fh:
        for riga in fh:
            riga = riga.strip()
            if not riga:
                continue
            fuori["righe"] += 1
            try:
                d = _json.loads(riga)
            except ValueError:
                fuori["illeggibili"] += 1
                continue
            fuori["nomi"][d.get("nome", "")] += 1
            fuori["coppie"][" ↔ ".join(d.get("entita") or [])] += 1
            if d.get("entity_id_evitato"):
                fuori["entita_evitate"].add(d["entity_id_evitato"])
            if d.get("azione") == "non_coniare":
                fuori["bloccati"] += 1
    return fuori


def main() -> int:
    import argparse
    from pathlib import Path as _P

    ap = argparse.ArgumentParser(description="I3: the composite name that is a relationship")
    ap.add_argument("--prova", nargs="+", help="judge one or more names against the live store")
    ap.add_argument("--diario", help="summarize a `resolutions/relazioni.jsonl`")
    a = ap.parse_args()

    if a.diario:
        d = rileggi_diario(_P(a.diario))
        print(f"\n  {a.diario}")
        print(f"  rows: {d['righe']:,} · unreadable: {d['illeggibili']}")
        print(f"  entities that would not have been created: {len(d['entita_evitate']):,}")
        print(f"  already blocked (block mode): {d['bloccati']:,}")
        print("\n  the twenty most frequent pairs:")
        for c, k in d["coppie"].most_common(20):
            print(f"    {k:>6}  {c}")
        return 0

    if a.prova:
        import sys

        sys.path.insert(0, str(_P(__file__).resolve().parent))
        from entity_dedup_index import EntityDedupIndex

        idx = EntityDedupIndex()
        for n in a.prova:
            g = giudica(
                n,
                risolvi=idx.trova_per_nome_esatto,
                ha_chiave_forte=idx.ha_chiave_forte,
            )
            esito = "RELATIONSHIP (not minted)" if g else "entity (minted)"
            print(f"  {esito:22s} «{n}»")
            if g:
                print(f"      {g.motivo}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
