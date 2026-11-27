#!/usr/bin/env python3
"""Read-only census: for attributes with competing facts, which fact would be promoted and why (nothing is applied)."""
























from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import knowledge_rango as kr  # noqa: E402
import knowledge_taxonomy as kt  # noqa: E402
from conteggio import Conteggio  # noqa: E402

ENTITA = (
    Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
    / "knowledge"
    / "entities"
)


def _budget() -> str:
    ""
    try:
        sys.path.insert(0, str(REPO / "tools"))
        import sbk_resources as res  # noqa: PLC0415

        stato = res.shared_state()
        return f"quota for this job: {stato.quota_bytes / 1e9:.1f} GB"
    except Exception as e:  # pragma: no cover - diagnostics
        return f"budget not queryable ({type(e).__name__}); reading in streaming anyway"


def scorri(radice=ENTITA):
    ""





    illeggibili = 0
    letti = 0
    for tipo in sorted(os.listdir(radice)):
        cartella = radice / tipo
        if not cartella.is_dir():
            continue
        for percorso in sorted(cartella.glob("*.json")):
            try:
                with open(percorso, encoding="utf-8") as fh:
                    dati = json.load(fh)
            except (OSError, ValueError):
                illeggibili += 1
                continue
            letti += 1
            yield dati, illeggibili
    yield None, illeggibili
    return letti


@functools.cache
def _giudizio_nome(nome, tipo):
    try:
        sys.path.insert(0, str(REPO / "tools" / "cross-source"))
        from confrontabile import confrontabile  # noqa: PLC0415
    except ImportError:  # pragma: no cover - outside the repo
        return True
    try:
        return bool(confrontabile(nome or "", tipo or "person")[0])
    except Exception:  # pragma: no cover - the judgment must not stop the measurement
        return True


def _nome_confrontabile(nome, tipo) -> bool:
    return _giudizio_nome(str(nome or ""), str(tipo or "person"))


def _margine(gruppo, verdetto) -> float | None:
    ""




    if verdetto.criterio == kr.CONFIDENZA:
        gara = [f for f in gruppo if kr.in_gara(f)]
        punti = sorted({float(f.get("confidence") or 0.0) for f in gara}, reverse=True)
        return round(punti[0] - punti[1], 4) if len(punti) > 1 else None
    if verdetto.criterio == kr.OSSERVAZIONI:
        gara = [f for f in gruppo if kr.in_gara(f)]
        punti = sorted({kr.fonti_indipendenti(f) for f in gara}, reverse=True)
        return float(punti[0] - punti[1]) if len(punti) > 1 else None
    return None


def _cambia_col_peso_fonte(gruppo, attributo, vincitore) -> bool:
    ""







    try:
        sys.path.insert(0, str(REPO / "tools" / "cross-source"))
        from xs_knowledge_conflict import get_source_weight  # noqa: PLC0415
    except ImportError:  # pragma: no cover - outside the repo
        return False
    gara = [f for f in gruppo if kr.in_gara(f)]
    pesi = [get_source_weight((f.get("source") or {}).get("source_type"), attributo) for f in gara]
    alto = max(pesi)
    testa = [f for f, p in zip(gara, pesi) if p == alto]
    valori = {kr._valore_normalizzato(f.get("value")) for f in testa}
    if len(valori) != 1:
        return False
    return next(iter(valori)) != kr._valore_normalizzato(vincitore.get("value"))


def censisci(radice=ENTITA):
    ""
    entita = 0
    fatti = 0
    illeggibili = 0

    con_attributo = Counter()
    con_un_fatto = Counter()





    gruppi = []
    gruppi_pieni = []
    for dati, illeggibili in scorri(radice):
        if dati is None:
            break
        entita += 1
        per_attributo = defaultdict(list)
        for f in dati.get("facts") or []:
            if isinstance(f, dict):
                fatti += 1
                per_attributo[str(f.get("attribute") or "").strip()].append(f)
        eid = dati.get("entity_id") or ""
        nome = dati.get("canonical_name") or ""
        dati_tipo = dati.get("entity_type") or "person"
        for attributo, gruppo in per_attributo.items():
            con_attributo[attributo] += 1
            if len(gruppo) == 1:
                con_un_fatto[attributo] += 1
            valori = {kr._valore_normalizzato(f.get("value")) for f in gruppo}
            if len(valori) >= 2:
                gruppi.append((attributo,))
                if kt.e_funzionale(attributo):
                    gruppi_pieni.append((eid, nome, attributo, gruppo))



    euristica = {a for a, n in con_attributo.items() if n and con_un_fatto.get(a, 0) / n >= 0.90}
    g_euristica = [g for g in gruppi if g[0] in euristica]
    g_dichiarata = gruppi_pieni

    promozioni = []
    astensioni = Counter()
    for eid, nome, attributo, gruppo in g_dichiarata:
        v = kr.arbitra(gruppo)
        if not v:
            astensioni[v.motivo] += 1
            continue
        vincitore = v.vincitore
        promozioni.append(
            {
                "entity_id": eid,
                "canonical_name": nome,
                "attribute": attributo,
                "fact_id": vincitore.get("fact_id"),
                "valore": vincitore.get("value"),
                "criterio": v.criterio,
                "prova": {
                    "valid_from": vincitore.get("valid_from"),
                    "confidence": vincitore.get("confidence"),
                    "fonti_indipendenti": kr.fonti_indipendenti(vincitore),
                    "source_type": (vincitore.get("source") or {}).get("source_type"),
                },




                "margine": _margine(gruppo, v),
                "cambia_col_peso_fonte": _cambia_col_peso_fonte(gruppo, attributo, vincitore),





                "nome_non_confrontabile": not _nome_confrontabile(nome, dati_tipo),
                "gemelli_stesso_valore": sum(
                    1
                    for f in gruppo
                    if kr.in_gara(f)
                    and kr._valore_normalizzato(f.get("value"))
                    == kr._valore_normalizzato(vincitore.get("value"))
                )
                - 1,
                "batte": [
                    {
                        "fact_id": p.get("fact_id"),
                        "valore": p.get("value"),
                        "confidence": p.get("confidence"),
                        "valid_from": p.get("valid_from"),
                        "fonti_indipendenti": kr.fonti_indipendenti(p),
                    }
                    for p in v.perdenti
                ],
            }
        )

    saltati = {"json illeggibile": illeggibili}
    return {
        "entita": Conteggio(entita, entita + illeggibili, saltati),
        "fatti": Conteggio(fatti, entita, saltati),
        "attributi": len(con_attributo),
        "gruppi_divergenti": Conteggio(len(gruppi), fatti, saltati),
        "euristica_quota": Conteggio(len(g_euristica), len(gruppi), saltati),
        "dichiarata_quota": Conteggio(len(g_dichiarata), len(gruppi), saltati),
        "promozioni": promozioni,
        "astensioni": astensioni,
        "attributi_euristica": len(euristica),
        "gruppi_euristica": g_euristica,
        "gruppi_dichiarata": g_dichiarata,
    }


def _confronto(c) -> list:
    ""
    righe = Counter()
    for (attributo,) in c["gruppi_euristica"]:
        righe[(kt.cardinalita(attributo), attributo)] += 1
    return sorted(righe.items(), key=lambda x: -x[1])


def _tronca(v, n: int) -> str:
    t = str(v or "").replace("\n", " ").replace("|", "/")
    return t if len(t) <= n else t[: n - 1] + "…"


def markdown(c) -> str:
    ""


    P = c["promozioni"]
    r = []
    r.append(f"# the {len(P)} promotions, with their reason — IN SHADOW, not applied\n")
    r.append(
        "Generated by `uv run python tools/util/sb-rango.py --markdown`, read-\n"
        "only on `~/.sbk-data/knowledge/entities`. ⛔ **No writes**: by default the store "
        "has **0 facts with a rank**,\n"
        "and it is a test (`tests/test_rango.py::test_controllo_positivo_lo_store_oggi_non_ha_nessun_rango`).\n"
    )
    r.append("## How to read it\n")
    r.append(
        'Each row is **one write**: `rank: "preferred"` on a fact. It closes nothing, it\n'
        "deletes nothing, it is undone by removing the key. The losers stay in the store, readable,\n"
        "exactly as they are now: they only leave the **default view**.\n"
    )
    r.append(
        "Four marks say where to look first:\n\n"
        "| mark | what it means | how many |\n|---|---|---:|\n"
        "| **source** | the winner would change if the criterion were the source weight instead of world time. These are the only truly contested rows | {} |\n"
        "| **near tie** | the confidence margin is ≤ 0.05: the winner wins by a hair | {} |\n"
        "| **chimera** | the record has a name that `confrontabile()` cannot compare — it is arbitrating inside an entity that may not be a single person | {} |\n"
        "| **twins** | the winning value is carried by several identical facts: only one is promoted, the others stay `normal` and go to the collapse | {} |\n".format(
            sum(1 for p in P if p["cambia_col_peso_fonte"]),
            sum(1 for p in P if p["margine"] is not None and p["margine"] <= 0.05),
            sum(1 for p in P if p["nome_non_confrontabile"]),
            sum(1 for p in P if p["gemelli_stesso_valore"] > 0),
        )
    )
    r.append("\n## The numbers\n")
    r.append("| | |\n|---|---:|")
    r.append(
        "| groups (entity, attribute) with more values | {} |".format(
            "{:,}".format(c["gruppi_divergenti"].valore).replace(",", ".")
        )
    )
    r.append(
        "| of which on attributes **declared functional** | **{}** |".format(
            c["dichiarata_quota"].valore
        )
    )
    r.append("| (the report heuristic gave) | {} |".format(c["euristica_quota"].valore))
    r.append(f"| **promotions** | **{len(P)}** |")
    r.append("| abstentions | {} |".format(sum(c["astensioni"].values())))
    for motivo, quanti in c["astensioni"].most_common():
        r.append(f"| — {motivo} | {quanti} |")
    r.append(f"\n## The {len(P)} rows\n")
    r.append("| # | record | attribute | ⬆ promoted | beats | criterion | margin | ⚠️ |")
    r.append("|---:|---|---|---|---|---|---:|---|")
    for i, p in enumerate(
        sorted(P, key=lambda x: (x["attribute"], str(x["canonical_name"] or ""))), 1
    ):
        perdenti = []
        for b in p["batte"]:
            v = _tronca(b["valore"], 34)
            if v not in perdenti:
                perdenti.append(v)
        flag = []
        if p["cambia_col_peso_fonte"]:
            flag.append("**source**")
        if p["margine"] is not None and p["margine"] <= 0.05:
            flag.append("near tie")
        if p["nome_non_confrontabile"]:
            flag.append("chimera")
        if p["gemelli_stesso_valore"] > 0:
            flag.append("{} twins".format(p["gemelli_stesso_valore"]))
        r.append(
            "| {} | {} | `{}` | **{}** | {} | {} | {} | {} |".format(
                i,
                _tronca(p["canonical_name"], 26),
                p["attribute"],
                _tronca(p["valore"], 46),
                " · ".join(perdenti),
                p["criterio"],
                "" if p["margine"] is None else "{:.3f}".format(p["margine"]),
                " + ".join(flag),
            )
        )
    r.append("\n## What is NOT in this list, and why\n")
    r.append(
        "- **The «nested values» groups** — e.g. «acme» / «acme team», «Globex» / «Globex Inc».\n"
        "  **All re-read by hand, one by one: they are the same thing written twice.**\n"
        "  Promoting one spelling would cement a normalization defect inside a decision.\n"
        "  **They go to the collapse**, not to the rank.\n"
        "- **The groups in a true tie** — same source, same confidence, no date. The typical\n"
        "  case is `crm.company` with two companies of the group (Acme / Globex Partner):\n"
        "  nothing in the data says which is the current one, and the module says so instead of guessing.\n"
        "- **The groups the report heuristic included** but the declared cardinality did not —\n"
        "  some on multi-value attributes (mostly `contact.email`), others on attributes that\n"
        "  no one has classified yet. There is no competition to arbitrate there.\n"
        "- **The facts that stay `normal`** are the vast majority. The default is\n"
        "  abstention: a mature knowledge base like Wikidata keeps almost everything at `normal`.\n"
    )
    r.append("## What it takes to apply them\n")
    r.append(
        "1. **the user's approval of this list**: it is not destructive and it undoes, but it is a judgment on\n"
        "   real people;\n"
        "2. an open `Incremento` — `knowledge_rango.promuovi()` without a registry **raises**;\n"
        "3. the single re-run pass, so the `rank` field flows through the A.4 merge (the field\n"
        "   is already in the schema: without it, it would disappear at the first extraction that touches the entity).\n"
    )
    return "\n".join(r)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--elenco", action="store_true", help="print the promotions, one per row")
    ap.add_argument("--confronta", action="store_true", help="heuristic vs declared")
    ap.add_argument("--scrivi", metavar="PERCORSO", help="write the list in JSON")
    ap.add_argument("--markdown", metavar="PERCORSO", help="write the readable list in Markdown")
    a = ap.parse_args(argv)

    print("── the rank census — read-only ──")
    print("  " + _budget())
    c = censisci()
    print("  entities: {}".format(c["entita"]))
    print("  facts   : {}".format(c["fatti"]))
    print("  distinct attributes: {}".format(c["attributi"]))
    print("  groups (entity,attribute) with >=2 distinct values: {}".format(c["gruppi_divergenti"]))
    print()
    print("  THE POPULATION — two criteria, and the difference is the result")
    print(
        "    report heuristic (>=90% of entities with A SINGLE FACT): {}"
        "  [{} attributes]".format(c["euristica_quota"], c["attributi_euristica"])
    )
    print(
        "    DECLARED cardinality (knowledge_taxonomy.FUNZIONALI):      {}".format(
            c["dichiarata_quota"]
        )
    )
    print()
    print("  THE OUTCOME — abstention is an outcome, not a gap")
    print("    promotions : {}".format(len(c["promozioni"])))
    for motivo, quanti in c["astensioni"].most_common():
        print(f"    abstention : {quanti:4d}  {motivo}")
    print()
    print("  per attributo: ", dict(Counter(p["attribute"] for p in c["promozioni"])))
    print("  per criterio : ", dict(Counter(p["criterio"] for p in c["promozioni"])))

    if a.confronta:
        print()
        print("  THE HEURISTIC GROUPS, by declared cardinality")
        for (card, attributo), quanti in _confronto(c):
            print(f"    {quanti:4d}  [{card:14s}] {attributo}")

    if a.elenco:
        print()
        print("  THE PROMOTIONS, one per row")
        for p in c["promozioni"]:
            print(
                "    {:24s} {:26s} → {!r:48s} [{}] batte {}".format(
                    p["attribute"],
                    str(p["canonical_name"])[:24],
                    str(p["valore"])[:44],
                    p["criterio"],
                    len(p["batte"]),
                )
            )

    if a.scrivi:
        percorso = Path(a.scrivi)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(
            json.dumps(
                {
                    "misurato": "read-only, no application",
                    "entita": c["entita"].valore,
                    "fatti": c["fatti"].valore,
                    "gruppi_divergenti": c["gruppi_divergenti"].valore,
                    "euristica_quota": c["euristica_quota"].valore,
                    "dichiarata_quota": c["dichiarata_quota"].valore,
                    "astensioni": dict(c["astensioni"]),
                    "promozioni": c["promozioni"],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print()
        print(f"  list written to {percorso}")

    if a.markdown:
        percorso = Path(a.markdown)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(markdown(c), encoding="utf-8")
        print()
        print(f"  readable list written to {percorso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
