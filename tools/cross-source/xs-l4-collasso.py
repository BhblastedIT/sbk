#!/usr/bin/env python3
""


























































































































from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

_QUI = Path(__file__).resolve().parent
if str(_QUI) not in sys.path:
    sys.path.insert(0, str(_QUI))
if str(_QUI.parent) not in sys.path:
    sys.path.insert(0, str(_QUI.parent))

from freno_massa import TroppoDiMassa, verifica_quota  # noqa: E402
from knowledge_schema import (  # noqa: E402
    FactObservation,
    assertion_hash_del_dict,
    fact_observation_to_dict,
    normalize_value,
)

from sbk_config import KNOWLEDGE_DIR, KNOWLEDGE_ENTITIES_DIR, safe_write_json  # noqa: E402

TIPI_ENTITA = ("person", "organization", "org", "deal", "commitment")



MEGA_ORG_PLACEHOLDER_IDS: frozenset[str] = frozenset(
    {
        "person_00000000",
        "person_00000000",
        "person_00000000",
        "person_00000000",
        "person_00000000",
    }
)


def _adesso() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def carica_skip(radice_knowledge: Path) -> set[str]:
    ""
    skip = set(MEGA_ORG_PLACEHOLDER_IDS)
    reg = radice_knowledge / "reclassification" / "gate0a-person-to-org.jsonl"
    if reg.exists():
        for riga in reg.read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if not riga:
                continue
            try:
                eid = json.loads(riga).get("entity_id")
            except json.JSONDecodeError:
                continue
            if eid:
                skip.add(eid)
    return skip





def e_ancorato(fatto: dict) -> bool:
    ""
    src = fatto.get("source") or {}
    return bool((src.get("record_id") or "").strip())


def osservazioni_di(fatto: dict) -> list[dict]:
    ""








    esistenti = fatto.get("observations") or []
    if esistenti:
        return [dict(o) for o in esistenti]
    src = fatto.get("source") or {}
    obs = FactObservation(
        source_file=src.get("source_file", ""),
        record_id=src.get("record_id", ""),
        source_type=src.get("source_type", ""),
        valid_from=fatto.get("valid_from"),
        extracted_at=src.get("extracted_at"),
        confidence=fatto.get("confidence", 0.0),
        confidence_curve=[fatto.get("confidence", 0.0)],
        speaker=src.get("speaker"),
        evidence_quote=src.get("evidence_quote"),
        char_start=src.get("char_start"),
        char_end=src.get("char_end"),
    )
    d = fact_observation_to_dict(obs)
    if fatto.get("record") is not None:
        d["record"] = dict(fatto["record"])
    return [d]


def unita_di_evidenza(fatto: dict) -> int:
    ""






    return max(1, len(fatto.get("observations") or []))





@dataclass
class Esito:
    fatti: list[dict]
    cambiato: bool
    conta: Counter
    sidecar: list[dict] = field(default_factory=list)
    campioni: list[dict] = field(default_factory=list)


def _fondi(membri: list[dict], conta: Counter, atteso: str | None = None) -> tuple[dict, list[str]]:
    ""






    ordinati = sorted(membri, key=lambda d: (d.get("created_at") or "", d.get("fact_id") or ""))
    base = ordinati[0]
    superstite = dict(base)
    id_superstite = base.get("fact_id")

    osservazioni: list[dict] = []
    for m in ordinati:
        osservazioni.extend(osservazioni_di(m))
    superstite["observations"] = osservazioni






    conf_base = base.get("confidence")
    conf_max = max(
        (m.get("confidence") for m in membri if m.get("confidence") is not None), default=conf_base
    )
    if conf_max is not None and conf_base is not None and conf_max > conf_base:
        conta["confidenza_alzata"] += 1
        conta["confidenza_delta_millesimi"] += int(round((conf_max - conf_base) * 1000))
    superstite["confidence"] = conf_max




    assorbiti: list[str] = []
    merged: set[str] = set()
    for m in membri:
        merged.update(m.get("merged_fact_ids") or [])
        fid = m.get("fact_id")
        if fid and fid != id_superstite:
            merged.add(fid)
            assorbiti.append(fid)
            if (m.get("source") or {}).get("evidence_quote") is not None:
                conta["quote_salvate"] += 1
            if (m.get("source") or {}).get("speaker") is not None:
                conta["speaker_salvati"] += 1
            if not e_ancorato(m):
                conta["deancorati_assorbiti"] += 1
    merged.discard(id_superstite)
    if merged:
        superstite["merged_fact_ids"] = sorted(merged)




    chiavi = Counter(
        (o.get("source_file"), o.get("record_id"), o.get("extracted_at")) for o in osservazioni
    )
    conta["osservazioni_indistinguibili"] += sum(n - 1 for n in chiavi.values() if n > 1)








    chiave = atteso if atteso is not None else assertion_hash_del_dict(base)
    for m in membri:
        if assertion_hash_del_dict(m) != chiave:
            raise AssertionError(
                f"member {m.get('fact_id')} doesn't carry the group's fingerprint: "
                "the grouping is merging different assertions"
            )
    if assertion_hash_del_dict(superstite) != chiave:
        raise AssertionError(
            f"the collapse changed the survivor's fingerprint {id_superstite}: "
            "a field inside the hash was rewritten"
        )
    return superstite, assorbiti


def collassa_entita(
    fatti: list[dict],
    *,
    modo_deancorati: str,
    salta: bool = False,
    campioni_voluti: int = 0,
) -> Esito:
    ""


    conta: Counter = Counter()
    conta["fatti_prima"] = len(fatti)
    conta["E_prima"] = sum(unita_di_evidenza(f) for f in fatti)

    if salta:
        conta["fatti_dopo"] = len(fatti)
        conta["E_dopo"] = conta["E_prima"]
        conta["entita_saltate_invariante_d"] = 1
        conta["fatti_saltati_invariante_d"] = len(fatti)
        return Esito(fatti=fatti, cambiato=False, conta=conta)

    gruppi: dict[str, list[dict]] = defaultdict(list)
    ordine: list[str] = []
    for f in fatti:
        h = assertion_hash_del_dict(f)
        if h not in gruppi:
            ordine.append(h)
        gruppi[h].append(f)



    per_natkey: dict[tuple, set[str]] = defaultdict(set)
    for f in fatti:
        per_natkey[(f.get("entity_id"), f.get("attribute"), normalize_value(f.get("value")))].add(
            assertion_hash_del_dict(f)
        )
    for _k, hs in per_natkey.items():
        if len(hs) > 1:
            conta["natkey_uguale_hash_diverso"] += 1



    for f in fatti:
        for o in f.get("observations") or []:
            if o.get("valid_from") != f.get("valid_from"):
                conta["gia_compattati_vf_divergenti"] += 1
                break

    fuori: list[dict] = []
    sidecar: list[dict] = []
    campioni: list[dict] = []

    for h in ordine:
        membri = gruppi[h]
        conta["gruppi"] += 1
        if len(membri) == 1:
            fuori.append(membri[0])
            continue
        conta["gruppi_multipli"] += 1

        if modo_deancorati == "escludi":


            ancorati = [m for m in membri if e_ancorato(m)]
            deancorati = [m for m in membri if not e_ancorato(m)]
            conta["deancorati_passthrough"] += len(deancorati)
            fuori.extend(deancorati)
            fondibili = ancorati
        elif modo_deancorati == "collassa":
            fondibili = membri
        else:
            raise ValueError(f"unknown modo_deancorati: {modo_deancorati!r}")

        if len(fondibili) <= 1:
            fuori.extend(fondibili)
            continue

        superstite, assorbiti = _fondi(fondibili, conta, atteso=h)
        conta["gruppi_fusi"] += 1
        fuori.append(superstite)
        conta["fatti_assorbiti"] += len(assorbiti)
        for fid in assorbiti:
            sidecar.append({"old_fact_id": fid, "surviving_fact_id": superstite.get("fact_id")})
        if campioni_voluti and len(campioni) < campioni_voluti:
            campioni.append(
                {
                    "entity_id": superstite.get("entity_id"),
                    "attribute": superstite.get("attribute"),
                    "assertion_hash": h,
                    "prima": fondibili,
                    "dopo": superstite,
                }
            )

    conta["fatti_dopo"] = len(fuori)
    conta["E_dopo"] = sum(unita_di_evidenza(f) for f in fuori)



    if conta["E_dopo"] != conta["E_prima"]:
        raise AssertionError(
            f"I1 violated on {fatti[0].get('entity_id') if fatti else '?'}: "
            f"E {conta['E_prima']} → {conta['E_dopo']}"
        )

    cambiato = conta["fatti_dopo"] != conta["fatti_prima"]
    return Esito(fatti=fuori, cambiato=cambiato, conta=conta, sidecar=sidecar, campioni=campioni)





def elenca_profili(sorgente: Path, entity_id: str | None, limite: int | None):
    n = 0
    for tipo in TIPI_ENTITA:
        d = sorgente / tipo
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if entity_id and p.stem != entity_id:
                continue
            yield tipo, p
            n += 1
            if limite and n >= limite:
                return


def passata(
    sorgente: Path,
    *,
    modo_deancorati: str,
    skip_ids: set[str],
    entity_id: str | None = None,
    limite: int | None = None,
    destinazione: Path | None = None,
    campioni_voluti: int = 0,
) -> tuple[Counter, list[dict], list[dict]]:
    ""
    tot: Counter = Counter()
    sidecar: list[dict] = []
    campioni: list[dict] = []
    for tipo, p in elenca_profili(sorgente, entity_id, limite):
        profilo = json.loads(p.read_text(encoding="utf-8"))
        fatti = profilo.get("facts") or []
        pid = profilo.get("entity_id") or p.stem
        esito = collassa_entita(
            fatti,
            modo_deancorati=modo_deancorati,
            salta=pid in skip_ids,
            campioni_voluti=max(0, campioni_voluti - len(campioni)),
        )
        tot.update(esito.conta)
        tot["file"] += 1
        sidecar.extend(esito.sidecar)
        campioni.extend(esito.campioni)
        if destinazione is not None:
            fuori = destinazione / tipo / p.name
            if esito.cambiato:
                profilo["facts"] = esito.fatti
                profilo["updated_at"] = _adesso()
                safe_write_json(fuori, profilo, backup=False)
                tot["file_riscritti"] += 1
            elif fuori.resolve() != p.resolve():




                fuori.parent.mkdir(parents=True, exist_ok=True)
                fuori.write_bytes(p.read_bytes())
    return tot, sidecar, campioni





def _tutti_i_fatti(radice: Path):
    for tipo in TIPI_ENTITA:
        d = radice / tipo
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            yield from json.loads(p.read_text(encoding="utf-8")).get("facts") or []


def confronta(sorgente: Path, ombra: Path) -> dict:
    ""




    E_a = 0
    impronte_a: set[str] = set()
    id_a: set[str] = set()
    quote_a = speaker_a = 0
    for f in _tutti_i_fatti(sorgente):
        E_a += unita_di_evidenza(f)
        impronte_a.add(assertion_hash_del_dict(f))
        id_a.add(f.get("fact_id"))
        src = f.get("source") or {}
        quote_a += 1 if src.get("evidence_quote") is not None else 0
        speaker_a += 1 if src.get("speaker") is not None else 0
        for o in f.get("observations") or []:
            quote_a += 1 if o.get("evidence_quote") is not None else 0
            speaker_a += 1 if o.get("speaker") is not None else 0

    E_b = 0
    impronte_b: set[str] = set()
    risolvibili: set[str] = set()
    quote_b = speaker_b = 0
    for f in _tutti_i_fatti(ombra):
        E_b += unita_di_evidenza(f)
        impronte_b.add(assertion_hash_del_dict(f))
        risolvibili.add(f.get("fact_id"))
        risolvibili.update(f.get("merged_fact_ids") or [])
        src = f.get("source") or {}
        quote_b += 1 if src.get("evidence_quote") is not None else 0
        speaker_b += 1 if src.get("speaker") is not None else 0
        for o in f.get("observations") or []:
            quote_b += 1 if o.get("evidence_quote") is not None else 0
            speaker_b += 1 if o.get("speaker") is not None else 0

    return {
        "E_prima": E_a,
        "E_dopo": E_b,
        "impronte_prima": len(impronte_a),
        "impronte_dopo": len(impronte_b),
        "impronte_perse": len(impronte_a - impronte_b),
        "impronte_nuove": len(impronte_b - impronte_a),
        "fact_id_prima": len(id_a),
        "fact_id_orfani": len(id_a - risolvibili),
        "quote_prima": quote_a,
        "quote_dopo": quote_b,
        "speaker_prima": speaker_a,
        "speaker_dopo": speaker_b,
    }





def _n(x: int) -> str:
    ""
    return f"{x:,}".replace(",", ".")


def _pct(a: int, b: int) -> str:
    return f"{(a / b * 100):.2f}%".replace(".", ",") if b else "n/d"


def scrivi_report(
    percorso: Path,
    *,
    piano_escludi: Counter,
    piano_collassa: Counter,
    modo: str,
    esito_freno: str,
    perche: str,
    durata: float,
    sorgente: Path,
    destinazione: Path | None,
    campioni: list[dict],
    verifiche: dict | None = None,
) -> None:
    tot = piano_collassa["fatti_prima"]
    ecc_e = piano_escludi["fatti_assorbiti"]
    ecc_c = piano_collassa["fatti_assorbiti"]
    r: list[str] = []
    r.append("# Run collapse — dry-run report")
    r.append("")
    r.append(f"> Generated on {_adesso()[:19]}Z · source `{sorgente}` · {durata:.1f} s")
    r.append("")
    r.append("## In two minutes")
    r.append("")
    r.append(f"- The store has **{_n(tot)} facts** in **{_n(piano_collassa['file'])} files**.")
    r.append(
        f"- Evidence units **E = {_n(piano_collassa['E_prima'])}**, "
        f"unchanged by the collapse on both paths (verified per entity and globally)."
    )
    r.append(
        f"- **Path A — the NULL sentinel stays**: **{_n(ecc_e)} facts "
        f"({_pct(ecc_e, tot)} of the store)** collapse. The brake doesn't trip."
    )
    r.append(
        f"- **Path B — the de-anchored ones collapse**: **{_n(ecc_c)} facts "
        f"({_pct(ecc_c, tot)} of the store)** collapse. The brake **trips** and a written override is needed."
    )
    r.append(f"- Path run this time: **{modo}**. Brake: **{esito_freno}**.")
    if perche:
        r.append(f"- Override reason: «{perche}»")
    if destinazione:
        r.append(f"- Written in **shadow** at `{destinazione}` — `entities/` was not touched.")
    else:
        r.append("- **No write**: only the plan.")
    r.append("")
    r.append("## The two paths, by the numbers")
    r.append("")
    r.append("| | path A · `escludi` | path B · `collassa` |")
    r.append("|---|---:|---:|")
    for etichetta, chiave in (
        ("facts collapsed", "fatti_assorbiti"),
        ("groups with more than one fact", "gruppi_multipli"),
        ("groups that actually collapse", "gruppi_fusi"),
        ("de-anchored absorbed", "deancorati_assorbiti"),
        ("de-anchored left single", "deancorati_passthrough"),
        ("quotes saved in the observation", "quote_salvate"),
        ("speakers saved in the observation", "speaker_salvati"),
        ("survivors with raised confidence", "confidenza_alzata"),
        ("indistinguishable observations", "osservazioni_indistinguibili"),
    ):
        r.append(f"| {etichetta} | {_n(piano_escludi[chiave])} | {_n(piano_collassa[chiave])} |")
    r.append(f"| **share seen by the brake** | **{_pct(ecc_e, tot)}** | **{_pct(ecc_c, tot)}** |")
    r.append("")
    r.append("## The I1 invariant (evidence units)")
    r.append("")
    r.append("| | before | after |")
    r.append("|---|---:|---:|")
    r.append(f"| path A | {_n(piano_escludi['E_prima'])} | {_n(piano_escludi['E_dopo'])} |")
    r.append(f"| path B | {_n(piano_collassa['E_prima'])} | {_n(piano_collassa['E_dopo'])} |")
    r.append("")
    r.append(
        "E = Σ max(1, len(observations)). The bare sum of observations grows by "
        "construction at every collapse and would not detect the loss of one of the facts "
        "without an array: that's why I1 counts evidence units and requires CONSERVATION, "
        "not growth."
    )
    r.append("")
    r.append("## The counters that must stay at zero (or say why they don't)")
    r.append("")
    r.append("| counter | path A | path B | what it means |")
    r.append("|---|---:|---:|---|")
    r.append(
        f"| `natkey_uguale_hash_diverso` | {_n(piano_escludi['natkey_uguale_hash_diverso'])} | "
        f"{_n(piano_collassa['natkey_uguale_hash_diverso'])} | groups the existing tool "
        "would merge but the fingerprint keeps apart (divergent `valid_from`): the measure of the "
        "difference between the old key and the new one |"
    )
    r.append(
        f"| `gia_compattati_vf_divergenti` | {_n(piano_escludi['gia_compattati_vf_divergenti'])} | "
        f"{_n(piano_collassa['gia_compattati_vf_divergenti'])} | facts already collapsed in a previous run "
        "with observations at a different `valid_from`: left untouched, still visible |"
    )
    r.append(
        f"| `entita_saltate_invariante_d` | {_n(piano_escludi['entita_saltate_invariante_d'])} | "
        f"{_n(piano_collassa['entita_saltate_invariante_d'])} | mega-org placeholders and the "
        "GATE 0a registry: the whole file passes through unchanged |"
    )
    r.append("")
    if campioni:
        r.append("## A sample, to see with your own eyes")
        r.append("")
        for c in campioni[:3]:
            r.append(f"### `{c['entity_id']}` · `{c['attribute']}`")
            r.append("")
            r.append(f"fingerprint `{c['assertion_hash'][:19]}…`")
            r.append("")
            r.append("| fact_id | confidence | valid_from | record_id | extracted_at |")
            r.append("|---|---:|---|---|---|")
            for m in c["prima"]:
                s = m.get("source") or {}
                r.append(
                    f"| `{(m.get('fact_id') or '')[:13]}…` | {m.get('confidence')} | "
                    f"{m.get('valid_from')} | `{s.get('record_id') or '(empty)'}` | "
                    f"{(s.get('extracted_at') or '')[:19]} |"
                )
            d = c["dopo"]
            r.append("")
            r.append(
                f"→ one fact `{(d.get('fact_id') or '')[:13]}…`, "
                f"{len(d.get('observations') or [])} observations, "
                f"confidence {d.get('confidence')}, "
                f"{len(d.get('merged_fact_ids') or [])} ids absorbed into `merged_fact_ids`."
            )
            r.append("")
    if verifiche:
        v = verifiche
        r.append("## The four checks, exact sums (no sampling)")
        r.append("")
        r.append("| check | before | after | result |")
        r.append("|---|---:|---:|---|")
        r.append(
            f"| **I1** · evidence units E | {_n(v['E_prima'])} | {_n(v['E_dopo'])} | "
            f"{'conserved' if v['E_prima'] == v['E_dopo'] else '**VIOLATED**'} |"
        )
        r.append(
            f"| **distinct assertions** | {_n(v['impronte_prima'])} | {_n(v['impronte_dopo'])} | "
            f"lost {_n(v['impronte_perse'])} · new {_n(v['impronte_nuove'])} |"
        )
        r.append(
            f"| **I2** · resolvable `fact_id` | {_n(v['fact_id_prima'])} | — | "
            f"orphans {_n(v['fact_id_orfani'])} |"
        )
        r.append(
            f"| quotes (`evidence_quote`) | {_n(v['quote_prima'])} | {_n(v['quote_dopo'])} | "
            f"{'none lost' if v['quote_dopo'] >= v['quote_prima'] else '**LOST**'} |"
        )
        r.append(
            f"| `speaker` | {_n(v['speaker_prima'])} | {_n(v['speaker_dopo'])} | "
            f"{'none lost' if v['speaker_dopo'] >= v['speaker_prima'] else '**LOST**'} |"
        )
        r.append("")
        r.append(
            "The collapse changes the MULTIPLICITY of the assertions, never their set: "
            "«lost 0 · new 0» is the strongest form of this statement. The quotes "
            "grow because the survivor keeps its own in `source` and finds it again in "
            "its own observation — none disappears, which is what counts."
        )
        r.append("")
    r.append("## What's needed to apply")
    r.append("")
    r.append(
        "1. the owner's sign-off on the path: the perimeter swings between "
        f"{_pct(ecc_e, tot)} and {_pct(ecc_c, tot)} of the store depending on the fate of the de-anchored ones;"
    )
    r.append(
        "2. the tar verified with `gzip -t` **right before** the apply — after the "
        "first subsequent write, the tar stops being a clean rollback;"
    )
    r.append('3. the written brake override (`--forza-freno --perche "..."`) if the path is B;')
    r.append("4. the apply is **the same code** as the shadow pointed at `entities/`.")
    r.append("")
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text("\n".join(r) + "\n", encoding="utf-8")





def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run collapse (assertion_hash)")
    ap.add_argument("--sorgente", default=str(KNOWLEDGE_ENTITIES_DIR))
    ap.add_argument("--knowledge", default=str(KNOWLEDGE_DIR))
    ap.add_argument("--deancorati", choices=("escludi", "collassa"), default="escludi")
    ap.add_argument("--shadow", default=None, help="writes the collapse HERE, outside entities/")
    ap.add_argument("--apply", action="store_true", help="writes into --sorgente. Destructive.")
    ap.add_argument("--forza-freno", action="store_true")
    ap.add_argument("--perche", default="")
    ap.add_argument("--report", default=None)
    ap.add_argument("--sidecar", default=None)
    ap.add_argument("--campioni", type=int, default=3)
    ap.add_argument("--entity-id", default=None)
    ap.add_argument("--limite", type=int, default=None)
    a = ap.parse_args(argv)

    sorgente = Path(os.path.expanduser(a.sorgente))
    scrive = bool(a.shadow) or a.apply




    if scrive and (a.entity_id or a.limite):
        print(
            "REFUSED: --entity-id and --limite are PARTIAL perimeters and the brake is stateless.\n"
            "  With a stateless brake a partial perimeter is not safe. Whoever writes, writes the whole plan.",
            file=sys.stderr,
        )
        return 2
    if a.apply and a.shadow:
        print("REFUSED: --apply and --shadow together make no sense.", file=sys.stderr)
        return 2

    skip_ids = carica_skip(Path(os.path.expanduser(a.knowledge)))
    t0 = time.time()


    piani: dict[str, Counter] = {}
    campioni: list[dict] = []
    for modo in ("escludi", "collassa"):
        conta, _sc, camp = passata(
            sorgente,
            modo_deancorati=modo,
            skip_ids=skip_ids,
            entity_id=a.entity_id,
            limite=a.limite,
            destinazione=None,
            campioni_voluti=a.campioni if modo == a.deancorati else 0,
        )
        piani[modo] = conta
        if modo == a.deancorati:
            campioni = camp

    piano = piani[a.deancorati]
    tocca = piano["fatti_assorbiti"]
    totale = piano["fatti_prima"]


    esito_freno = "not tripped"
    try:
        frazione = verifica_quota(
            tocca,
            totale,
            f"assertion_hash collapse ⑫ (--deancorati {a.deancorati})",
            forza=a.forza_freno,
            perche=a.perche,
        )
        if a.forza_freno and totale >= 500 and frazione > 0.20:
            esito_freno = f"OVERRIDDEN with written exception ({frazione * 100:.2f}%)".replace(
                ".", ",", 1
            )
    except TroppoDiMassa as e:
        esito_freno = (
            f"TRIPPED ({tocca / totale * 100:.2f}%)".replace(".", ",", 1) if totale else "TRIPPED"
        )
        if scrive:
            print(f"\nBRAKE: {e}\n", file=sys.stderr)
            return 3
        print(f"\nBRAKE (the plan is computed anyway, nothing is written): {e}\n")


    destinazione = None
    if a.shadow:
        destinazione = Path(os.path.expanduser(a.shadow))
    elif a.apply:
        destinazione = sorgente
    sidecar: list[dict] = []
    verifiche: dict | None = None
    if destinazione is not None:
        conta2, sidecar, _c = passata(
            sorgente,
            modo_deancorati=a.deancorati,
            skip_ids=skip_ids,
            destinazione=destinazione,
        )
        if a.shadow:
            verifiche = confronta(sorgente, destinazione)
        if conta2["fatti_assorbiti"] != tocca:
            print(
                f"REFUSED: the plan said {tocca} absorbed, the execution {conta2['fatti_assorbiti']}.",
                file=sys.stderr,
            )
            return 4
        piano = conta2

    durata = time.time() - t0
    report = Path(
        os.path.expanduser(
            a.report
            or f"~/.sbk-data/knowledge/reports/collasso/report-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.md"  # noqa: UP017
        )
    )
    scrivi_report(
        report,
        piano_escludi=piani["escludi"],
        piano_collassa=piani["collassa"],
        modo=a.deancorati,
        esito_freno=esito_freno,
        perche=a.perche,
        durata=durata,
        sorgente=sorgente,
        destinazione=destinazione,
        campioni=campioni,
        verifiche=verifiche,
    )
    if a.sidecar and sidecar:
        sp = Path(os.path.expanduser(a.sidecar))
        sp.parent.mkdir(parents=True, exist_ok=True)
        with sp.open("w", encoding="utf-8") as fh:
            for riga in sidecar:
                fh.write(json.dumps(riga, ensure_ascii=False) + "\n")

    print(
        f"facts {piano['fatti_prima']:,} → {piano['fatti_dopo']:,} "
        f"(absorbed {piano['fatti_assorbiti']:,}) · E {piano['E_prima']:,} = {piano['E_dopo']:,} "
        f"· brake: {esito_freno} · {durata:.1f} s"
    )
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
