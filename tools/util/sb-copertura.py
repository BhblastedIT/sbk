#!/usr/bin/env python3
""






























from __future__ import annotations

import argparse
import collections
import json
import re as _re
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

STORE = cfg.DATA_ROOT / "knowledge"
DISPOSIZIONI = STORE / "meta" / "copertura-disposizioni.json"
RAPPORTO = STORE / "meta" / "copertura.json"






SOGLIA_RUMORE = 10











_CENSIMENTO: tuple[collections.Counter, collections.Counter] | None = None


def _censimento_store() -> tuple[collections.Counter, collections.Counter]:
    ""




    global _CENSIMENTO
    if _CENSIMENTO is not None:
        return _CENSIMENTO
    attributi: collections.Counter = collections.Counter()
    sorgenti: collections.Counter = collections.Counter()
    radice = STORE / "entities"
    if radice.exists():
        for cartella in sorted(radice.iterdir()):
            if not cartella.is_dir():
                continue
            for f in cartella.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for fatto in d.get("facts") or []:
                    a = (fatto.get("attribute") or "").strip()
                    if a:
                        attributi[a] += 1
                    s = ((fatto.get("source") or {}).get("source_type") or "").strip()
                    if s:
                        sorgenti[s] += 1
                del d
    _CENSIMENTO = (attributi, sorgenti)
    return _CENSIMENTO


def _mondo_attributi() -> collections.Counter:
    return _censimento_store()[0]


def _mondo_sorgenti() -> collections.Counter:
    return _censimento_store()[1]


def _da_parquet(percorso: Path, colonna: str) -> collections.Counter:
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        return collections.Counter()
    if not percorso.exists():
        return collections.Counter()
    con = duckdb.connect()
    try:
        from sbk_resources import configure_duckdb

        configure_duckdb(con)
    except Exception:  # pragma: no cover - il tetto è un di più, non un requisito
        pass
    try:
        righe = con.execute(
            f"select {colonna}, count(*) from read_parquet('{percorso}') group by 1"  # noqa: S608
        ).fetchall()
    except Exception:  # pragma: no cover
        return collections.Counter()
    finally:
        con.close()
    return collections.Counter({str(v): int(n) for v, n in righe if v is not None})


def _mondo_episodi() -> collections.Counter:
    return _da_parquet(STORE / "epistemic" / "knows.parquet", "episode_type")


def _mondo_accessi() -> collections.Counter:
    return _da_parquet(STORE / "epistemic" / "knows.parquet", "access_type")



















def _mondo_rete() -> collections.Counter:
    ""
    conta: collections.Counter = collections.Counter()
    radice = STORE / "entities"
    if not radice.exists():
        return conta
    for c in sorted(radice.iterdir()):
        if c.is_dir():
            for f in c.glob("*.json"):
                conta[f.stem] = 1
    return conta


def _dispone_rete() -> dict[str, str]:
    ""
    fuori: dict[str, str] = {}

    kp = STORE / "epistemic" / "knows.parquet"
    if kp.exists():
        try:
            import duckdb

            con = duckdb.connect()
            try:
                from sbk_resources import configure_duckdb

                configure_duckdb(con)
            except Exception:  # pragma: no cover
                pass
            for (pid,) in con.execute(
                f"select distinct person_id from read_parquet('{kp}')"  # noqa: S608
            ).fetchall():
                if pid:
                    fuori[pid] = "collegata:partecipazione"
            con.close()
        except Exception:  # pragma: no cover
            pass

    ep: dict[str, set] = collections.defaultdict(set)
    radice = STORE / "entities"
    if radice.exists():
        for c in sorted(radice.iterdir()):
            if not c.is_dir():
                continue
            for f in c.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for x in d.get("facts") or []:
                    for e in x.get("episode_ids") or []:
                        ep[e].add(d.get("entity_id"))
                del d
    for insieme in ep.values():
        if len(insieme) > 1:
            for e in insieme:
                fuori.setdefault(e, "collegata:co-occorrenza")
    return fuori











_REGOLE = REPO / "docs" / "sbk" / "rules" / "ORGANIZATION-RULES.md"


def _codici_dichiarati() -> tuple[set[str], set[str]]:
    ""
    fonti: set[str] = set()
    stage: set[str] = set()
    try:
        righe = _REGOLE.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover
        return fonti, stage
    sezione = ""
    for r in righe:
        if r.startswith("#"):
            b = r.lower()
            if "fonte" in b or "source" in b:
                sezione = "fonte"
            elif "stage" in b:
                sezione = "stage"
            elif r.startswith("##"):
                sezione = ""
            continue

        m = _re.match(r"\|\s*`([a-z0-9]{2,4})`\s*\|", r)
        if not m:
            continue
        if sezione == "fonte":
            fonti.add(m.group(1))
        elif sezione == "stage":
            stage.add(m.group(1))
    return fonti, stage







def _codici_osservati() -> dict[str, str]:
    ""
    d = REPO / "tools"
    if not d.exists():
        return {}
    visti: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for f in d.rglob("*.py"):
        if any(x in f.parts for x in (".venv", "__pycache__")) or "-" not in f.stem:
            continue
        codice = f.stem.split("-")[0]
        if 2 <= len(codice) <= 4:
            visti[codice][f.parent.name] += 1


    return {c: v.most_common(1)[0][0] for c, v in visti.items() if sum(v.values()) >= 2}


def _mondo_nomi() -> collections.Counter:
    ""
    conta: collections.Counter = collections.Counter()
    d = REPO / "tools"
    if not d.exists():
        return conta
    for f in d.rglob("*.py"):
        if any(x in f.parts for x in (".venv", "__pycache__", "node_modules")):
            continue

        if "-" not in f.stem:
            continue
        conta[f.stem] = 1
    return conta








def _dispone_nomi() -> dict[str, str]:
    fonti, stage = _codici_dichiarati()
    osservati = _codici_osservati()
    fuori: dict[str, str] = {}
    for nome in _mondo_nomi():
        parti = nome.split("-")
        if len(parti) < 3:
            continue


        numerato = len(parti[1]) == 2 and parti[1].isdigit()
        if parti[1] not in stage and not numerato:
            continue
        if parti[0] in fonti:
            fuori[nome] = f"conforme:{parti[0]}-{parti[1]}"
        elif parti[0] in osservati:

            fuori[nome] = f"da-documentare:{parti[0]}→tools/{osservati[parti[0]]}"
    return fuori










def _mondo_relazioni() -> collections.Counter:
    conta: collections.Counter = collections.Counter()
    cartella = STORE / "relationships"
    if not cartella.exists():
        return conta
    for f in cartella.glob("*.json"):
        conta[f.stem] = 1
    return conta


def _indice_email() -> dict[str, str]:
    ""
    fuori: dict[str, str] = {}
    radice = STORE / "entities"
    if not radice.exists():
        return fuori
    for cartella in sorted(radice.iterdir()):
        if not cartella.is_dir():
            continue
        for f in cartella.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            eid = d.get("entity_id")
            for fatto in d.get("facts") or []:
                a = (fatto.get("attribute") or "").lower()
                v = fatto.get("value")
                if isinstance(v, str) and "@" in v and ("email" in a or "contact" in a):
                    fuori.setdefault(v.strip().lower(), eid)
            del d
    return fuori





_DENTRO = _re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _dispone_relazioni() -> dict[str, str]:
    ""
    indice = _indice_email()
    fuori: dict[str, str] = {}
    for chiave in _mondo_relazioni():
        eid = indice.get(chiave.lower())
        if eid:
            fuori[chiave] = f"riconducibile:{eid}"
            continue
        dentro = _DENTRO.search(chiave)
        if dentro and (alt := indice.get(dentro.group(0).lower())):
            fuori[chiave] = f"riparabile:{alt}"
    return fuori











_ATTRIBUTI_AZIENDA = ("employment.company", "employment.employer", "crm.company")


def _indice_organizzazioni() -> dict[str, str]:
    ""
    fuori: dict[str, str] = {}
    for sub in ("organization", "org"):
        d = STORE / "entities" / sub
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                o = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            nomi = [o.get("canonical_name")]
            nomi += [
                x.get("value")
                for x in o.get("facts") or []
                if (x.get("attribute") or "").startswith(("identity.name", "identity.alias"))
            ]
            for n in nomi:
                if isinstance(n, str) and n.strip():
                    fuori.setdefault(cfg.chiave_organizzazione(n), o.get("entity_id"))
    return fuori


def _mondo_archi() -> collections.Counter:
    ""
    conta: collections.Counter = collections.Counter()
    d = STORE / "entities" / "person"
    if not d.exists():
        return conta
    for f in d.glob("*.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for x in p.get("facts") or []:
            if (x.get("attribute") or "").lower() in _ATTRIBUTI_AZIENDA:
                v = x.get("value")
                if isinstance(v, str) and v.strip():
                    conta[v.strip()] += 1
        del p
    return conta


def _dispone_archi() -> dict[str, str]:
    indice = _indice_organizzazioni()
    fuori: dict[str, str] = {}
    for nome in _mondo_archi():
        eid = indice.get(cfg.chiave_organizzazione(nome))
        if eid:
            fuori[nome] = f"arco:{eid}"
    return fuori








def _mondo_passi() -> collections.Counter:
    ""
    conta: collections.Counter = collections.Counter()
    cartella = REPO / "tools" / "cross-source"
    if not cartella.exists():
        return conta
    for f in sorted(cartella.glob("*.py")):
        if f.name.startswith(("_", "test")):
            continue




        try:
            testo = f.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover
            continue
        if '__name__ == "__main__"' not in testo and "__name__ == '__main__'" not in testo:
            continue
        conta[f.name] = 1
    return conta




PRESIDI: dict[str, dict] = {
    "episodio": {
        "store": True,
        "leggi": _mondo_episodi,
        "soglia": SOGLIA_RUMORE,
        "decide": "whether a participation counts as CONTACT (knowledge_view.conoscenza)",
    },
    "accesso": {
        "store": True,
        "leggi": _mondo_accessi,
        "soglia": SOGLIA_RUMORE,
        "decide": "whether there was a conversation or only reception (CONTACT vs REACHED)",
    },
    "attributo": {
        "store": True,
        "leggi": _mondo_attributi,
        "soglia": SOGLIA_RUMORE,
        "decide": "whether a fact is state, event, end, or invisible",
    },
    "sorgente": {
        "store": True,
        "leggi": _mondo_sorgenti,
        "soglia": SOGLIA_RUMORE,
        "decide": "where a fact comes from, and how much it is trusted",
    },
    "rete": {
        "store": True,
        "leggi": _mondo_rete,
        "dispone": _dispone_rete,
        "soglia": 1,
        "semina_default": False,
        "decide": "whether an entity is linked to something, or is a lone record",
    },
    "nome": {
        "leggi": _mondo_nomi,
        "dispone": _dispone_nomi,
        "soglia": 1,
        "semina_default": False,
        "decide": "whether a script's name tells what it does and where it is in the chain",
    },
    "arco": {
        "store": True,
        "leggi": _mondo_archi,
        "dispone": _dispone_archi,
        "soglia": SOGLIA_RUMORE,
        "semina_default": False,
        "decide": "whether a fact naming a company becomes a link in the network",
    },
    "relazione": {
        "store": True,
        "leggi": _mondo_relazioni,

        "dispone": _dispone_relazioni,
        "soglia": 1,
        "semina_default": False,
        "decide": "whether a relationship's owner is known, or it stays ownerless",
    },
    "passo": {
        "leggi": _mondo_passi,


        "soglia": 1,




        "semina_default": False,
        "decide": "whether a pipeline script ever runs, or ages in silence",
    },
}


def carica_disposizioni() -> dict[str, dict[str, str]]:
    if DISPOSIZIONI.exists():
        try:
            return json.loads(DISPOSIZIONI.read_text(encoding="utf-8"))
        except ValueError:  # pragma: no cover
            return {}
    return {}


def semina_da_codice() -> dict[str, dict[str, str]]:
    ""




    fuori: dict[str, dict[str, str]] = {
        "episodio": {},
        "accesso": {},
        "attributo": {},
        "passo": _raggiungibili(),
    }
    try:
        import knowledge_view as kv
    except Exception:  # pragma: no cover
        return fuori
    for e in getattr(kv, "EPISODI_NON_DI_CONTATTO", ()):
        fuori["episodio"][e] = "non-contatto"
    for a in getattr(kv, "ACCESSI_DI_CONTATTO", ()):
        fuori["accesso"][a] = "contatto"
    for p in getattr(kv, "PREFISSI_STATO", ()):
        fuori["attributo"][p] = "stato"
    for p in getattr(kv, "PREFISSI_EVENTO", ()):
        fuori["attributo"][p] = "evento"
    for p in getattr(kv, "PREFISSI_FINE", ()):
        fuori["attributo"][p] = "fine"
    for p in getattr(kv, "METADATI_RAPPORTO", ()):
        fuori["attributo"][p] = "metadato"
    return fuori


def _passi_del_runner() -> dict[str, str]:
    ""




    import ast

    fuori: dict[str, str] = {}
    sorgente = REPO / "tools" / "cross-source" / "xs-pipeline-run.py"
    if not sorgente.exists():
        return fuori
    try:
        albero = ast.parse(sorgente.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):  # pragma: no cover
        return fuori




    for nodo in ast.walk(albero):
        if (
            isinstance(nodo, ast.BinOp)
            and isinstance(nodo.op, ast.Div)
            and isinstance(nodo.right, ast.Constant)
            and isinstance(nodo.right.value, str)
            and nodo.right.value.endswith(".py")
        ):
            fuori[nodo.right.value] = "nel-runner"
    return fuori














def _citati(testo: str, candidati: set[str]) -> list[tuple[str, str]]:
    import ast

    fuori: list[tuple[str, str]] = []

    fuori.extend((nome, "raggiunto") for nome in candidati if nome in testo)

    try:
        albero = ast.parse(testo)
    except SyntaxError:  # pragma: no cover
        return fuori
    moduli: set[str] = set()
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            moduli.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            moduli.add(nodo.module.split(".")[0])
    fuori.extend((f"{m}.py", "importato") for m in moduli if f"{m}.py" in candidati)
    return fuori


def _raggiungibili() -> dict[str, str]:
    cartella = REPO / "tools" / "cross-source"
    if not cartella.exists():
        return {}
    testi: dict[str, str] = {}
    for f in cartella.glob("*.py"):
        try:
            testi[f.name] = f.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover
            continue
    fronte = set(_passi_del_runner()) | {"xs-pipeline-run.py"}
    visti: dict[str, str] = dict.fromkeys(fronte, "nel-runner")
    while fronte:
        nome = fronte.pop()
        testo = testi.get(nome)
        if not testo:
            continue
        for altro, come in _citati(testo, set(testi)):
            if altro not in visti:
                visti[altro] = f"{come} da {nome}"
                fronte.add(altro)
    return visti


def _disposizione(elemento: str, dispo: dict[str, str]) -> str | None:
    ""




    if elemento in dispo:
        return dispo[elemento]
    e = elemento.lower()
    migliore = None
    for chiave, valore in dispo.items():
        k = chiave.lower()
        if k.endswith(".") and e.startswith(k) or e == k or e.startswith(k + "."):
            if migliore is None or len(k) > len(migliore[0]):
                migliore = (k, valore)
    return migliore[1] if migliore else None




_CLASSI_APPLICATE = {"stato", "evento", "identita"}


def _adesso() -> str:








    from datetime import datetime, timezone  # noqa: UP017

    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _inerti(presidio: str, dispo: dict[str, str]) -> list[str]:
    ""
    if presidio != "attributo":
        return []
    return sorted(k for k, v in dispo.items() if v != DEFAULT and v not in _CLASSI_APPLICATE)


def misura(
    presidio: str,
    leggi: Callable[[], collections.Counter],
    dispo: dict[str, str],
    soglia: int = SOGLIA_RUMORE,
) -> dict:
    mondo = leggi()
    totale = sum(mondo.values())
    coperto = 0
    per_default = 0
    nuovi: list[dict] = []
    for elemento, n in mondo.items():
        d = _disposizione(elemento, dispo)
        if d is None:
            nuovi.append({"elemento": elemento, "fatti": n})
            continue
        coperto += n
        if d == DEFAULT:
            per_default += n
    nuovi.sort(key=lambda x: -x["fatti"])




    presenti = {e.lower() for e in mondo}
    spariti = [
        d
        for d in dispo
        if not d.endswith(".")
        and d.lower() not in presenti
        and not any(p.startswith(d.lower() + ".") for p in presenti)
    ]





    inerti = _inerti(presidio, dispo)
    guardie = sorted(d for d in spariti if dispo.get(d) != DEFAULT)
    morti = sorted(d for d in spariti if dispo.get(d) == DEFAULT)
    return {
        "soglia": soglia,
        "mondo": len(mondo),
        "fatti": totale,
        "per_default": per_default,
        "scelti": round((coperto - per_default) * 100 / totale, 1) if totale else 100.0,
        "copertura": round(coperto * 100 / totale, 1) if totale else 100.0,
        "nuovi": [n for n in nuovi if n["fatti"] >= soglia],
        "nuovi_in_coda": len([n for n in nuovi if n["fatti"] < soglia]),
        "fatti_scoperti": totale - coperto,
        "morti": morti,
        "guardie": guardie,
        "inerti": inerti,
    }






DEFAULT = "default-applicato"


def gira(solo_codice: bool = False) -> dict:
    dispo = carica_disposizioni()



    semi = semina_da_codice()
    da_scrivere = False
    for nome, spec in PRESIDI.items():



        if spec.get("dispone"):
            dispo[nome] = spec["dispone"]()
            continue
        if nome in dispo:
            continue
        da_scrivere = True
        corrente = dict(semi.get(nome, {}))


        if spec.get("semina_default", True):
            for elemento in spec["leggi"]():
                if _disposizione(elemento, corrente) is None:
                    corrente[elemento] = DEFAULT
        dispo[nome] = corrente
    if da_scrivere:

        salvabili = {k: v for k, v in dispo.items() if not PRESIDI.get(k, {}).get("dispone")}
        dispo_da_salvare = salvabili
        DISPOSIZIONI.parent.mkdir(parents=True, exist_ok=True)
        DISPOSIZIONI.write_text(
            json.dumps(dispo_da_salvare, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    fuori = {}
    for nome, spec in PRESIDI.items():




        if solo_codice and spec.get("store"):
            continue
        fuori[nome] = misura(
            nome, spec["leggi"], dispo.get(nome, {}), spec.get("soglia", SOGLIA_RUMORE)
        )
        fuori[nome]["decide"] = spec["decide"]
    return fuori


def _controlla_i_file(nomi: list[str]) -> int:
    ""
    interessanti = [
        n for n in nomi if n.endswith(".py") and "/cross-source/" in n and "_deprecated" not in n
    ]
    if not interessanti:
        return 0
    raggiungibili = _raggiungibili()
    fonti, stage = _codici_dichiarati()
    osservati = _codici_osservati()
    problemi: list[str] = []
    for n in interessanti:
        f = Path(n)
        try:
            testo = (REPO / n).read_text(encoding="utf-8")
        except OSError:
            continue

        lanciabile = "__main__" in testo





        dichiarato = any(
            s in testo.lower()
            for s in ("run manually", "on-demand", "one-shot", "not in pipeline")
        )
        if lanciabile and dichiarato:
            continue
        if lanciabile and f.name not in raggiungibili:
            problemi.append(
                f"  {f.name}: nobody calls it. Three ways: add it to SCRIPTS in"
                " xs-pipeline-run.py · have an already-reachable script call it · write in the"
                " docstring «run manually» (or «on-demand», «one-shot») and why."
            )
        parti = f.stem.split("-")
        numerato = len(parti) > 1 and len(parti[1]) == 2 and parti[1].isdigit()
        conforme = (
            len(parti) >= 3
            and (parti[1] in stage or numerato)
            and (parti[0] in fonti or parti[0] in osservati)
        )







        non_e_un_passo = any(
            s in testo.lower()
            for s in ("orchestrator", "not a step", "not a pipeline step")
        )
        if "-" in f.stem and not conforme and not non_e_un_passo:
            problemi.append(
                f"  {f.name}: the name doesn't say where it is in the chain."
                " Form: {fonte}-{stage}-{cosa}.py — ORGANIZATION-RULES.md §5.1"
            )
    if problemi:
        print("❌ commit check:")
        print("\n".join(problemi))
        print("\n   (now is the right moment to notice)")
        return 1
    print(f"✓ {len(interessanti)} pipeline files: reachable and with a readable name")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="How much of the world our lists cover")
    ap.add_argument("--json", default="")
    ap.add_argument("--presidio", default="")
    ap.add_argument(
        "nomi",
        nargs="*",
        help="the files in this commit: check ONLY those (this is the pre-commit mode)",
    )
    ap.add_argument(
        "--solo-codice",
        action="store_true",
        help="only the checks that do NOT read the store: they run in a second, fit in the pre-commit",
    )
    ap.add_argument(
        "--rosso-se-peggiora",
        action="store_true",
        help="exits !=0 if a code check has new elements never disposed (a new orphan "
        "script, a name out of convention): it's the gate that prevents creating more",
    )
    a = ap.parse_args()







    if a.nomi:
        return _controlla_i_file(a.nomi)

    tutto = gira(solo_codice=a.solo_codice)





    fuori = {k: v for k, v in tutto.items() if k == a.presidio} if a.presidio else tutto

    precedente = {}
    if RAPPORTO.exists():
        try:
            precedente = json.loads(RAPPORTO.read_text(encoding="utf-8")).get("presidi", {})
        except ValueError:  # pragma: no cover
            precedente = {}

    urla = 0
    for nome, r in fuori.items():
        prima = precedente.get(nome, {}).get("copertura")
        delta = f"  (was {prima}%)" if prima is not None and prima != r["copertura"] else ""
        print(f"\n── {nome}: coverage {r['copertura']}%{delta}")
        print(f"   decides: {r['decide']}")
        print(f"   the world has {r['mondo']:,} values, {r['fatti']:,} occurrences")
        if r["per_default"]:
            print(
                f"   {r['per_default']:,} occurrences ({100 - r['scelti']:.1f}%) go through the"
                " default branch: no one chose them"
            )
        if r["nuovi"]:
            urla += len(r["nuovi"])
            print(f"   ⚠️  {len(r['nuovi'])} NEVER DISPOSED (≥{r['soglia']} occurrences):")
            for n in r["nuovi"][:12]:
                print(f"        {n['fatti']:8,}  {n['elemento']}")
            if len(r["nuovi"]) > 12:
                print(f"        … and {len(r['nuovi']) - 12} more")
        if r["nuovi_in_coda"]:
            print(f"   {r['nuovi_in_coda']:,} in queue below threshold (noise)")
        if r.get("inerti"):
            print(
                f"   ⚠️  {len(r['inerti'])} chosen dispositions that change NOTHING:"
                " recorded, read and then discarded by the consumer"
            )
            print(f"        {', '.join(sorted(r['inerti'])[:6])}")
        if r["morti"]:
            print(
                f"   dead weight (default snapshotted, vanished from the world): {', '.join(r['morti'][:8])}"
            )
        if r["guardie"]:
            print(
                f"   {len(r['guardie'])} guards with no cases today (kept): {', '.join(r['guardie'][:5])}"
            )

    RAPPORTO.parent.mkdir(parents=True, exist_ok=True)







    precedenti = {}
    if RAPPORTO.exists():
        try:
            precedenti = json.loads(RAPPORTO.read_text(encoding="utf-8")).get("presidi", {})
        except (OSError, ValueError):  # pragma: no cover
            precedenti = {}
    adesso = _adesso()
    for v in tutto.values():
        v["misurato"] = adesso
    RAPPORTO.write_text(
        json.dumps(
            {"quando": adesso, "presidi": {**precedenti, **tutto}}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    if a.json:
        Path(a.json).write_text(json.dumps(fuori, ensure_ascii=False, indent=1), encoding="utf-8")

    if a.rosso_se_peggiora:
        nuovi = {n: [x["elemento"] for x in v["nuovi"]] for n, v in fuori.items() if v["nuovi"]}
        if nuovi:
            print(
                "\n❌ new elements no one disposed — if it's a just-added script,"
                "\n   either someone calls it, or say why not:"
            )
            for n, elenchi in nuovi.items():
                print(f"     {n}: {', '.join(elenchi[:8])}")
            return 1

    print(f"\ndispositions: {DISPOSIZIONI}")
    print(f"report:       {RAPPORTO}")
    if urla:
        print(
            f"\n⚠️  {urla} elements of the world have no disposition. Until they do,"
            "\n   the code treats them with the default branch — which no one chose for them."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
