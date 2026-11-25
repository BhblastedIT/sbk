#!/usr/bin/env python3
""











































































































































from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone  # noqa: UP017
from itertools import combinations
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_TOOLS / "cross-source") not in sys.path:
    sys.path.insert(0, str(_TOOLS / "cross-source"))

from conteggio import Conteggio  # noqa: E402









CANCELLO_HUB = 50





CANCELLO_GENERICO = 100






ORIGINE_INFERENZA = "inferenza_di_modello"


ORIGINE_ATTO_UMANO = "atto_volontario_di_persona"







SORGENTI_ATTO_UMANO: frozenset[str] = frozenset()


class VistaVuotaPerCostruzione(RuntimeError):
    ""













@dataclass(frozen=True)
class Prova:
    ""






    episodio: str
    quando: str | None = None
    tipo: str = ""
    accesso: str = ""


@dataclass(frozen=True)
class Arco:
    ""

    chi: str
    quanti: int
    prove: tuple[Prova, ...] = ()

    origine: str = ORIGINE_INFERENZA

    def come_dict(self) -> dict:
        return {
            "chi": self.chi,
            "quanti": self.quanti,
            "origine": self.origine,
            "prove": [
                {"episodio": p.episodio, "quando": p.quando, "tipo": p.tipo, "accesso": p.accesso}
                for p in self.prove
            ],
        }


@dataclass(frozen=True)
class Ponte:
    ""

    chi: str



    episodi_del_ponte: int = 0


@dataclass(frozen=True)
class DueSalti:
    chi: str
    ponti: tuple[Ponte, ...] = ()


@dataclass(frozen=True)
class Vista:
    ""

    chi: str
    un_salto: tuple[Arco, ...] = ()
    due_salti: tuple[DueSalti, ...] = ()

    fermata_da: str | None = None
    ponti_scartati: tuple[str, ...] = ()
    esclusi: int = 0
    ms: float = 0.0

    def come_dict(self) -> dict:
        return {
            "chi": self.chi,
            "un_salto": [a.come_dict() for a in self.un_salto],
            "due_salti": [
                {
                    "chi": d.chi,
                    "ponti": [
                        {"chi": p.chi, "episodi_del_ponte": p.episodi_del_ponte} for p in d.ponti
                    ],
                }
                for d in self.due_salti
            ],
            "fermata_da": self.fermata_da,
            "ponti_scartati": list(self.ponti_scartati),
            "esclusi": self.esclusi,
            "ms": round(self.ms, 3),
        }







@dataclass
class Sorgente:
    ""






    nome: str
    occorrenze: list = field(default_factory=list)
    saltati: dict = field(default_factory=dict)


def _knows_parquet() -> Path:
    import sbk_config as cfg

    return cfg.DATA_ROOT / "knowledge" / "epistemic" / "knows.parquet"


def da_knows(percorso: Path | None = None) -> Sorgente:
    ""






    import pyarrow.parquet as pq

    p = percorso or _knows_parquet()
    saltati = {"parquet missing": 0}
    if not p.exists():
        saltati["parquet missing"] = 1
        return Sorgente("knows", [], saltati)
    t = pq.read_table(
        p, columns=["person_id", "episode_id", "episode_type", "access_type", "occurred_at"]
    )
    col = {n: t.column(n).to_pylist() for n in t.column_names}
    occ = [
        (
            col["person_id"][i],
            col["episode_id"][i],
            Prova(
                episodio=col["episode_id"][i],
                quando=col["occurred_at"][i],
                tipo=col["episode_type"][i] or "",
                accesso=col["access_type"][i] or "",
            ),
        )
        for i in range(t.num_rows)
    ]
    return Sorgente("knows", occ, saltati)












def attendees_produzione(grezzo: str) -> list[str]:
    ""





    from rq_third_party import _is_owner_email, _normalize_email

    return [
        _normalize_email(e)
        for e in str(grezzo).split(",")
        if e.strip() and not _is_owner_email(e.strip()) and "@" in e
    ]






# Addresses of yours missing from "own_emails"; with a complete
# sbk.config.json there are none, so the set stays empty.
ALIAS_DI_OWNER_NON_DICHIARATI: frozenset[str] = frozenset()


def attendees_json(grezzo: str, alias_completi: bool = False) -> list[str]:
    ""










    from rq_third_party import _is_owner_email, _normalize_email

    testo = str(grezzo or "").strip()
    if not testo:
        return []
    fuori: list[str] = []
    if testo.startswith("["):
        try:
            for voce in json.loads(testo):
                mail = voce.get("email") if isinstance(voce, dict) else voce
                if not mail or "@" not in str(mail):
                    continue
                pulito = _normalize_email(str(mail))
                if _is_owner_email(pulito):
                    continue
                if alias_completi and pulito in ALIAS_DI_OWNER_NON_DICHIARATI:
                    continue
                fuori.append(pulito)
            return fuori
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    return attendees_produzione(testo)


def attendees_json_owner_completo(grezzo: str) -> list[str]:
    ""
    return attendees_json(grezzo, alias_completi=True)


def da_calendario(
    parser=attendees_json,
    cartella: Path | None = None,
    unifica_eventi: bool = False,
) -> Sorgente:
    ""





















    import pandas as pd

    import sbk_config as cfg

    base = cartella or cfg.CALENDARS_DIR
    occ: list = []
    saltati = {"parquet unreadable": 0, "no attendees": 0}
    for f in sorted(Path(base).glob("*/events.parquet")):
        try:
            df = pd.read_parquet(f, columns=["id", "attendees", "attendee_count", "start_datetime"])
        except (OSError, ValueError, KeyError):
            saltati["parquet unreadable"] += 1
            continue
        for n_riga, (_, riga) in enumerate(df.iterrows()):
            n = riga.get("attendee_count") or 0
            if not n or int(n) <= 1:
                continue
            grezzo = riga.get("attendees", "")
            if not grezzo:
                saltati["no attendees"] += 1
                continue
            ev = str(riga.get("id") or "")
            contenitore = ev if unifica_eventi else f"{f.parent.name}:{n_riga}"
            quando = riga.get("start_datetime")
            prova = Prova(
                episodio=ev,
                quando=str(quando) if quando is not None else None,
                tipo="calendar",
                accesso="invited",
            )
            for mail in parser(grezzo):
                occ.append((mail, contenitore, prova))
    return Sorgente("calendario", occ, saltati)







class Indice:
    ""







    def __init__(self, sorgente: Sorgente):
        self.sorgente = sorgente.nome
        self.saltati = dict(sorgente.saltati)
        self._per_contenitore: dict[str, set[str]] = defaultdict(set)
        self._per_persona: dict[str, set[str]] = defaultdict(set)
        self._prove: dict[tuple[str, str], Prova] = {}
        for persona, contenitore, prova in sorgente.occorrenze:
            if not persona or not contenitore:
                continue
            self._per_contenitore[contenitore].add(persona)
            self._per_persona[persona].add(contenitore)
            self._prove[(persona, contenitore)] = prova
        self._vicini_cache: dict[str, dict[str, list[str]]] = {}


    def persone(self) -> list[str]:
        return list(self._per_persona)

    def episodi_di(self, chi: str) -> int:
        return len(self._per_persona.get(chi, ()))

    def vicini(self, chi: str) -> dict[str, list[str]]:
        ""
        gia = self._vicini_cache.get(chi)
        if gia is not None:
            return gia
        fuori: dict[str, list[str]] = defaultdict(list)
        for c in self._per_persona.get(chi, ()):
            for altro in self._per_contenitore[c]:
                if altro != chi:
                    fuori[altro].append(c)
        fuori = dict(fuori)
        self._vicini_cache[chi] = fuori
        return fuori

    def grado(self, chi: str) -> int:
        return len(self.vicini(chi))


    def vista(
        self,
        chi: str,
        cancelli: bool = True,
        escludi: frozenset[str] = frozenset(),
        max_prove: int = 5,
        solo_atti_umani: bool = False,
    ) -> Vista:
        ""







        if solo_atti_umani and not SORGENTI_ATTO_UMANO:
            raise VistaVuotaPerCostruzione(
                "none of the co-occurrence sources is a person's voluntary act: in some "
                "external sources a human writes the link, whereas here a model infers "
                "it. A view of only human-made edges would be empty by construction, "
                "not strict. See SORGENTI_ATTO_UMANO."
            )
        t0 = time.perf_counter()
        v1 = {altro: cont for altro, cont in self.vicini(chi).items() if altro not in escludi}
        esclusi = len(self.vicini(chi)) - len(v1)

        un_salto = tuple(
            Arco(
                chi=altro,
                quanti=len(cont),
                prove=tuple(
                    self._prove[(altro, c)]
                    for c in sorted(cont)[:max_prove]
                    if (altro, c) in self._prove
                ),
            )
            for altro, cont in sorted(v1.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        )

        if cancelli and len(v1) >= CANCELLO_HUB:
            return Vista(
                chi=chi,
                un_salto=un_salto,
                due_salti=(),
                fermata_da=f"hub (degree {len(v1)} >= {CANCELLO_HUB})",
                esclusi=esclusi,
                ms=(time.perf_counter() - t0) * 1000,
            )

        ponti_scartati: list[str] = []
        accumulo: dict[str, list[Ponte]] = defaultdict(list)
        for ponte in v1:
            n_ep = self.episodi_di(ponte)
            if cancelli and n_ep > CANCELLO_GENERICO:
                ponti_scartati.append(ponte)
                continue
            for lontano in self.vicini(ponte):
                if lontano == chi or lontano in v1 or lontano in escludi:
                    continue
                accumulo[lontano].append(Ponte(chi=ponte, episodi_del_ponte=n_ep))

        due = tuple(
            DueSalti(chi=k, ponti=tuple(sorted(vs, key=lambda p: p.chi)))
            for k, vs in sorted(accumulo.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        )
        return Vista(
            chi=chi,
            un_salto=un_salto,
            due_salti=due,
            fermata_da=None,
            ponti_scartati=tuple(sorted(ponti_scartati)),
            esclusi=esclusi,
            ms=(time.perf_counter() - t0) * 1000,
        )


    def coppie(self, escludi: frozenset[str] = frozenset()) -> dict:
        ""





        fuori: dict[tuple[str, str], int] = defaultdict(int)
        for contenitore, presenti in self._per_contenitore.items():
            gente = sorted(p for p in presenti if p not in escludi)
            if len(gente) < 2:
                continue
            for a, b in combinations(gente, 2):
                fuori[(a, b) if a <= b else (b, a)] += 1
        return dict(fuori)

    def come_indice(
        self,
        company_pairs: dict | None = None,
        team_pairs: dict | None = None,
        thread_pairs: dict | None = None,
        cc_pairs: dict | None = None,
        escludi: frozenset[str] = frozenset(),
    ) -> dict:
        ""











        from rq_third_party import aggregate_signals, compute_third_party_strength

        segnali = aggregate_signals(
            self.coppie(escludi=escludi),
            thread_pairs or {},
            cc_pairs or {},
            company_pairs or {},
            team_pairs or {},
        )
        pairs = [
            {
                "person_a": a,
                "person_b": b,
                "strength": round(compute_third_party_strength(s), 3),
                "signals": [
                    {"type": x["type"], "count": x["count"], "confidence": x["confidence"]}
                    for x in s
                ],
            }
            for (a, b), s in segnali.items()
        ]
        return {
            "pairs_count": len(pairs),
            "warm_intros_count": 0,
            "pairs": pairs,
            "warm_intros": {},
            "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            "vista": True,
            "sorgente": self.sorgente,
        }







def misura(indice: Indice) -> dict:
    ""
    persone = indice.persone()
    gradi = {p: indice.grado(p) for p in persone}
    fermati = sum(1 for g in gradi.values() if g >= CANCELLO_HUB)
    archi = sum(gradi.values()) // 2
    return {
        "sorgente": indice.sorgente,
        "persone": Conteggio(len(persone), len(persone), indice.saltati),
        "contenitori": len(indice._per_contenitore),
        "archi_1hop": Conteggio(archi, archi, indice.saltati),
        "fermati_da_hub": Conteggio(fermati, len(persone), indice.saltati),
        "grado_zero": Conteggio(
            sum(1 for g in gradi.values() if g == 0), len(persone), indice.saltati
        ),
    }


def _nomi() -> dict:
    ""
    import sbk_config as cfg

    cartella = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
    fuori: dict[str, str] = {}
    if not cartella.exists():
        return fuori
    for f in cartella.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = (d.get("canonical_name") or "").strip()
        if n:
            fuori[f.stem] = n
    return fuori


def equivalenza() -> int:
    ""







    from rq_third_party import build_meeting_pairs

    import sbk_config as cfg

    print("A · equivalence — the view against the production pipeline")
    import pandas as pd

    eventi = []
    for f in sorted(cfg.CALENDARS_DIR.glob("*/events.parquet")):
        df = pd.read_parquet(f, columns=["attendees", "attendee_count"])
        for _, r in df.iterrows():
            if (r.get("attendee_count", 0) or 0) > 1:
                eventi.append({"attendees": str(r.get("attendees", ""))})
    t0 = time.perf_counter()
    produzione = build_meeting_pairs(eventi)
    t_prod = time.perf_counter() - t0

    t0 = time.perf_counter()
    idx_prod = Indice(da_calendario(parser=attendees_produzione))
    vista = idx_prod.coppie()
    t_vista = time.perf_counter() - t0

    uguali = produzione == vista
    print(f"    production : {len(produzione):>7,} pairs in {t_prod:.2f} s")
    print(f"    view       : {len(vista):>7,} pairs in {t_vista:.2f} s")
    print(f"    IDENTICAL pair-by-pair and count-by-count: {uguali}")
    if not uguali:
        solo_p = set(produzione) - set(vista)
        solo_v = set(vista) - set(produzione)
        div = {k for k in set(produzione) & set(vista) if produzione[k] != vista[k]}
        print(
            f"    ⛔ only production {len(solo_p)} · only view {len(solo_v)} · different {len(div)}"
        )

    print("\nB · drift — the materialized file against today's view")
    f = cfg.DATA_ROOT / "knowledge" / "relationships" / "third-party-index.json"
    if not f.exists():
        print("    the file is not there: nothing to compare")
    else:
        d = json.loads(f.read_text(encoding="utf-8"))
        del_file = {}
        for pr in d["pairs"]:
            for s in pr["signals"]:
                if s["type"] == "co_meeting":
                    a_, b_ = pr["person_a"], pr["person_b"]
                    del_file[(a_, b_) if a_ <= b_ else (b_, a_)] = s["count"]
        from rq_third_party import SIGNAL_MIN_COUNT

        oggi = {k: v for k, v in vista.items() if v >= SIGNAL_MIN_COUNT["co_meeting"]}
        comuni = set(del_file) & set(oggi)
        cambiate = sum(1 for k in comuni if del_file[k] != oggi[k])
        print(f"    file  {d['generated_at']} — {len(del_file):,} co_meeting pairs")
        print(f"    today {len(oggi):,} pairs above threshold")
        print(
            f"    from file found again: {len(comuni):,} = {100 * len(comuni) / len(del_file):.1f}%"
        )
        print(
            f"    with a different count: {cambiate:,} = {100 * cambiate / max(1, len(comuni)):.1f}%"
        )
        print(f"    pairs the file does NOT have: {len(set(oggi) - set(del_file)):,}")

    print("\nC · defect — the nodes that do not exist")
    n_prod = len({x for k in vista for x in k})
    idx_json = Indice(da_calendario(parser=attendees_json))
    n_json = len({x for k in idx_json.coppie() for x in k})
    idx_owner = Indice(da_calendario(parser=attendees_json_owner_completo))
    n_owner = len({x for k in idx_owner.coppie() for x in k})
    print(f"    production parser               : {n_prod:,} nodes in a pair")
    print(f"    + json.loads                    : {n_json:,}  (−{n_prod - n_json:,})")
    print(f"    + complete owner aliases        : {n_owner:,}  (−{n_json - n_owner:,})")
    print(
        f"    nodes that do not exist         : {n_prod - n_owner:,} = "
        f"{100 * (n_prod - n_owner) / n_prod:.1f}%"
    )
    return 0 if uguali else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Co-occurrence as a computed view")
    ap.add_argument("--sorgente", choices=("knows", "calendario"), default="knows")
    ap.add_argument("--chi", help="person_id or email: print the view")
    ap.add_argument("--senza-cancelli", action="store_true")
    ap.add_argument("--misura", action="store_true", help="the population numbers")
    ap.add_argument(
        "--equivalenza",
        action="store_true",
        help="the A-B-C proof: the view gives the same result as the file, and what the file costs",
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.equivalenza:
        return equivalenza()

    t0 = time.perf_counter()
    sorg = da_knows() if a.sorgente == "knows" else da_calendario()
    idx = Indice(sorg)
    costruzione = (time.perf_counter() - t0) * 1000

    if a.misura or not a.chi:
        m = misura(idx)
        print(f"source          : {m['sorgente']}")
        print(f"build           : {costruzione:.1f} ms (cold, process just started)")
        print(f"people          : {m['persone']}")
        print(f"containers      : {m['contenitori']:,}")
        print(f"edges 1hop      : {m['archi_1hop']}")
        print(f"stopped by hub  : {m['fermati_da_hub']} ({m['fermati_da_hub'].percentuale()}%)")
        print(f"degree zero     : {m['grado_zero']} ({m['grado_zero'].percentuale()}%)")
        if not a.chi:
            return 0

    v = idx.vista(a.chi, cancelli=not a.senza_cancelli)
    if a.json:
        print(json.dumps(v.come_dict(), ensure_ascii=False, indent=2))
        return 0
    nomi = _nomi() if a.sorgente == "knows" else {}
    print(f"\n{a.chi} — {nomi.get(a.chi, '')}")
    print(f"  1 hop   : {len(v.un_salto)}")
    print(f"  2 hops  : {len(v.due_salti)}")
    print(f"  stop    : {v.fermata_da or 'no'}")
    print(f"  bridges discarded (generic): {len(v.ponti_scartati)}")
    print(f"  time    : {v.ms:.2f} ms")
    for arco in v.un_salto[:10]:
        p = arco.prove[0] if arco.prove else None
        prova = f"{p.episodio} · {p.quando} · {p.tipo}" if p else "—"
        print(f"    {arco.chi:20} {nomi.get(arco.chi, '')[:28]:30} x{arco.quanti:<4} {prova}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
