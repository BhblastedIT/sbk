#!/usr/bin/env python3
"""Large validation of sb-who: about 2,400 cases by variable and invariant (--veloce runs about 600)."""











































from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))

from knowledge_view import classe_attributo, is_group_name  # noqa: E402

import sbk_config as cfg  # noqa: E402

_spec = importlib.util.spec_from_file_location("sb_who", PROJECT / "tools/util/sb-who.py")
sbwho = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sbwho)

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
SEME = 11




AFFERMATIVI = {"CHIUSO", "DENTRO", "STALE", "APERTO-NON-VERIFICABILE"}







def _righe(p: Path) -> list:
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return []
    if isinstance(d, list):
        return d
    for k in ("employees", "members", "users", "people", "rows"):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def popolazioni(veloce: bool) -> dict[str, list[dict]]:
    ""
    n_store = 800 if veloce else 10000
    out: dict[str, list[dict]] = {}

    out["personio"] = [
        {
            "nome": " ".join(str(x) for x in (r.get("first_name"), r.get("last_name")) if x),
            "atteso": "uscito"
            if str(r.get("status", "")).lower() not in ("active", "attivo")
            else "attivo",
        }
        for r in _righe(cfg.DATA_ROOT / "personio" / "employees-flat.json")
    ]
    out["clickup"] = [
        {"nome": str(r.get("username") or r.get("name") or ""), "atteso": "non-chiuso"}
        for r in _righe(cfg.DATA_ROOT / "clickup-members-cache.json")
    ]
    out["relevant"] = [
        {"nome": str(r.get("name") or ""), "atteso": None}
        for r in _righe(cfg.DATA_ROOT / "rq" / "top-150-people.json")
    ]

    rnd = random.Random(SEME)
    nomi = os.listdir(PERSON)
    store, alias, forme = [], [], []
    for f in rnd.sample(nomi, min(n_store, len(nomi))):
        d = sbwho._carica(f)
        if not d or not d.get("canonical_name"):
            continue
        cn = d["canonical_name"]
        store.append({"nome": cn, "atteso": None, "_d": d, "_forma": "canonical"})




        if len(alias) < n_store // 2:
            for fa in d.get("facts") or []:
                if (
                    isinstance(fa, dict)
                    and fa.get("attribute") == "identity.name"
                    and str(fa.get("value") or "").strip()
                    and str(fa.get("value")).strip() != cn
                ):
                    alias.append(
                        {
                            "nome": str(fa["value"]).strip(),
                            "atteso": None,
                            "_d": d,
                            "_forma": "alias",
                            "_canonico": cn,
                        }
                    )
                    break




        if len(forme) < n_store and not is_group_name(cn) and len(cn.split()) == 2:
            nome_p, cognome = cn.split()





            refuso = (
                cognome[:-1] + ("i" if not cognome.endswith("i") else "o")
                if len(cognome) > 3
                else cognome
            )
            for q, et in (
                (cn.lower(), "lowercase"),
                (f"  {cn}  ", "spaces"),
                (cognome, "last name only"),
                (nome_p, "first name only"),
                (f"{cognome} {nome_p}", "inverted name"),
                (f"{nome_p[0]}. {cognome}", "dotted initial"),
                (f"{nome_p} {refuso}", "typo in last name"),
            ):
                forme.append({"nome": q, "atteso": None, "_d": d, "_forma": et, "_canonico": cn})

    out["store"] = store
    out["alias"] = alias
    out["forms"] = forme




    orgs = []
    for cartella in ("organization", "org"):
        d_org = cfg.DATA_ROOT / "knowledge" / "entities" / cartella
        if not d_org.is_dir():
            continue
        for f in sorted(os.listdir(d_org))[: n_store // 4]:
            try:
                d = json.loads((d_org / f).read_text())
            except Exception:  # noqa: BLE001
                continue
            if d.get("canonical_name"):
                orgs.append({"nome": d["canonical_name"], "atteso": "mai-persona", "_forma": "org"})
    out["org"] = orgs

    for k in out:
        out[k] = [r for r in out[k] if r["nome"]]
    return out






_AZIENDA = re.compile(
    r"(?i)\b(s\.?r\.?l|s\.?p\.?a|gmbh|ltd|inc|llc|holding|group|agency|studio|co\.)\b"
)


def variabili(nome: str, d: dict | None, r: dict) -> dict[str, str]:
    ""
    fatti = (d or {}).get("facts") or []
    n = len(fatti)

    if is_group_name(nome):
        forma = "group"
    elif "@" in nome:
        forma = "email"
    elif _AZIENDA.search(nome):
        forma = "company"
    elif len(nome.split()) == 1:
        forma = "single-name"
    elif len(nome.split()) >= 4:
        forma = "long-name"
    else:
        forma = "normal-name"

    ricchezza = (
        "empty (0)"
        if n == 0
        else "sparse (1-2)"
        if n <= 2
        else "medium (3-19)"
        if n < 20
        else "rich (20-99)"
        if n < 100
        else "very rich (100+)"
    )


    date_f = [
        str(f.get("valid_from") or f.get("created_at") or "")[:10]
        for f in fatti
        if isinstance(f, dict)
    ]
    date_f = [x for x in date_f if len(x) == 10]
    if not date_f:
        eta = "no dates"
    else:
        try:
            gg = (date.today() - date.fromisoformat(max(date_f))).days
            eta = (
                "≤30 d"
                if gg <= 30
                else "≤90 d"
                if gg <= 90
                else "≤180 d"
                if gg <= 180
                else "≤365 d"
                if gg <= 365
                else "over a year"
            )
        except ValueError:
            eta = "unreadable date"

    canale = r.get("fonte") or "—"
    conf = r.get("confidenza")
    fascia_conf = (
        "—"
        if conf is None
        else "high (≥0.9)"
        if conf >= 0.9
        else "medium (0.7-0.9)"
        if conf >= 0.7
        else "low (<0.7)"
    )


    cl = classe_attributo(r.get("claim") or "") if r.get("claim") else "—"




    canali = {
        (f.get("source") or {}).get("source_type")
        for f in fatti
        if isinstance(f, dict) and (f.get("source") or {}).get("source_type")
    }
    n_canali = (
        "none"
        if not canali
        else "a single source"
        if len(canali) == 1
        else "2-3 sources"
        if len(canali) <= 3
        else "4+ sources"
    )

    return {
        "name shape": forma,
        "record richness": ricchezza,
        "age of last fact": eta,
        "independent sources": n_canali,
        "claim channel": canale,
        "claim confidence": fascia_conf,
        "attribute class": cl,
    }







def invarianti(nome: str, r: dict) -> list[str]:
    ""
    v = r.get("verdetto")
    ko = []

    if not v:
        ko.append("verdict missing")
        return ko

    if not (r.get("non_so") or []):
        ko.append("the «don't know» row is empty: the reader would believe we know everything")

    if v == "CHIUSO" and not r.get("quando"):
        ko.append("CHIUSO without a date: closing without saying when is a bare assertion")

    if v in AFFERMATIVI and not r.get("claim"):
        ko.append(f"{v} without a claim: asserts without saying about what")

    if v in AFFERMATIVI and not r.get("fonte"):
        ko.append(f"{v} without a source: cannot trace back who said it")

    if v == "DENTRO" and r.get("giorni") is None:
        ko.append("DENTRO without the fact age: «inside» when, exactly?")

    if is_group_name(nome) and v in ("CHIUSO", "DENTRO", "STALE"):
        ko.append(f"a name that contains several people received «{v}», which holds for one only")

    if v == "IGNOTO" and r.get("claim"):
        ko.append("IGNOTO but with a claim: either it is known or it is not")

    conf = r.get("confidenza")
    if conf is not None and not (0 <= conf <= 1):
        ko.append(f"confidence out of scale: {conf}")

    return ko


def stabilita_di_forma(canonico: str, idx: dict) -> list[str]:
    ""





    varianti = [
        canonico,
        canonico.lower(),
        canonico.upper(),
        f"  {canonico}  ",
        canonico.replace(" ", "  "),
    ]
    esiti = {}
    for q in varianti:
        try:
            esiti[q] = sbwho.chiedi(q, idx)["verdetto"]
        except Exception as exc:  # noqa: BLE001
            return [f"«{q[:40]}» raises {type(exc).__name__}"]
    distinti = set(esiti.values())
    if len(distinti) > 1:
        det = " · ".join(f"«{q[:24]}»→{v}" for q, v in esiti.items())
        return [f"the same person written in {len(distinti)} ways gives different verdicts: {det}"]
    return []


def coerenza_alias(alias: str, canonico: str, idx: dict) -> list[str]:
    ""
    try:
        a = sbwho.chiedi(alias, idx)
        c = sbwho.chiedi(canonico, idx)
    except Exception as exc:  # noqa: BLE001
        return [f"exception: {type(exc).__name__}"]


    if a["verdetto"] in AFFERMATIVI and c["verdetto"] in AFFERMATIVI:
        if a["verdetto"] != c["verdetto"]:
            return [
                f"«{alias[:30]}» → {a['verdetto']} but «{canonico[:30]}» → {c['verdetto']}: "
                "two different assertions about the same person"
            ]
    return []


def org_mai_persona(nome: str, idx: dict) -> list[str]:
    ""
    try:
        r = sbwho.chiedi(nome, idx)
    except Exception as exc:  # noqa: BLE001
        return [f"exception on an organization: {type(exc).__name__}"]
    if r["verdetto"] in ("DENTRO", "STALE", "CHIUSO"):
        return [f"«{nome[:40]}» is an organization and receives «{r['verdetto']}»"]
    return []


def prove_temporali(nome: str, idx: dict) -> list[str]:
    ""
    ko = []
    oggi = sbwho.chiedi(nome, idx)
    passato = sbwho.chiedi(nome, idx, as_of=date.today() - timedelta(days=365))

    if oggi["verdetto"] == "CHIUSO" and passato["verdetto"] == "CHIUSO":
        q_oggi, q_ieri = oggi.get("quando"), passato.get("quando")
        if q_oggi and q_ieri and q_ieri > q_oggi:
            ko.append("closed at a date in the FUTURE relative to today")


    if (
        passato.get("quando")
        and passato["quando"] > (date.today() - timedelta(days=365)).isoformat()
    ):
        if passato["verdetto"] in AFFERMATIVI:
            ko.append(
                f"with --as-of one year ago it asserts «{passato['verdetto']}» about a fact "
                f"from {passato['quando']}, which did not exist then"
            )
    return ko


def determinismo(nome: str, idx: dict) -> list[str]:
    ""
    a = sbwho.chiedi(nome, idx)
    b = sbwho.chiedi(nome, idx)
    if a.get("verdetto") != b.get("verdetto"):
        return [f"two identical calls give {a.get('verdetto')} and {b.get('verdetto')}"]
    return []






AVVERSARIALI = [
    ("", "empty string"),
    ("   ", "only spaces"),
    ("a", "one character"),
    ("'; DROP TABLE persone; --", "injection"),
    ("../../etc/passwd", "traversal"),
    ("%s%s%s%n", "format string"),
    ("Zxqwerty Nonesisteaffatto", "invented name"),
    ("María José Ñuñez-Öztürk", "unicode and accents"),
    ("李 明", "non-Latin characters"),
    ("Mario " + "Rossi " * 60, "very long name"),
    ("MARIO ROSSI", "all uppercase"),
    ("mario   rossi", "multiple spaces"),
    ("\n\tMario\tRossi\n", "strange whitespace"),
    ("Mario Rossi <u4d1267@example.com>", "name with email"),
    ("👋 Mario", "emoji"),
]


def avversariali(idx: dict) -> list[tuple[str, str, str]]:
    ""
    out = []
    for testo, desc in AVVERSARIALI:
        try:
            r = sbwho.chiedi(testo, idx)
            v = r.get("verdetto")
            if v in ("CHIUSO", "DENTRO"):
                out.append((desc, f"asserts «{v}» on an input like this", "🔴"))
            elif not v:
                out.append((desc, "no verdict", "🔴"))
            elif invarianti(testo, r):
                out.append((desc, f"{v}, but the response is malformed", "🟠"))
        except Exception as exc:  # noqa: BLE001
            out.append((desc, f"EXCEPTION: {type(exc).__name__}: {exc}", "🔴"))
    return out







def _stampa_incrocio(titolo: str, tab: dict[str, dict[str, int]], soglia: int = 5) -> None:
    print(f"\n  ── {titolo} ──")
    for chiave in sorted(tab, key=lambda k: -sum(tab[k].values())):
        tot = sum(tab[chiave].values())
        if tot < soglia:
            continue
        parti = sorted(tab[chiave].items(), key=lambda x: -x[1])

        dom, n_dom = parti[0]
        marchio = " ⚠️ monocolore" if n_dom / tot > 0.85 and tot >= 20 else ""
        riga = " · ".join(f"{v} {c}" for v, c in parti[:4])
        print(f"    {chiave:24} ({tot:4}) {riga}{marchio}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--veloce", action="store_true", help="~600 cases instead of ~2,400")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not PERSON.is_dir():
        print(f"knowledge store missing: {PERSON}", file=sys.stderr)
        return 2

    idx = sbwho.carica_indice()
    pop = popolazioni(a.veloce)
    n_tot = sum(len(v) for v in pop.values())
    print(f"── big acceptance test: {n_tot} cases from {len(pop)} populations ──")


    incroci: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    per_pop: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    viol_inv: list[tuple[str, str]] = []
    errori_duri: list[tuple[str, str, str]] = []

    for etichetta, righe in pop.items():
        for r0 in righe:
            nome = r0["nome"]
            try:
                cand_n = len(sbwho.risolvi(nome, idx))
                r = sbwho.chiedi(nome, idx)
            except Exception as exc:  # noqa: BLE001
                errori_duri.append((etichetta, nome, f"{type(exc).__name__}: {exc}"))
                continue
            v = r.get("verdetto") or "?"
            per_pop[etichetta][v] += 1







            d_ris = r0.get("_d")
            if d_ris is None and r.get("entity_id"):
                for f in sbwho.risolvi(nome, idx)[:6]:
                    c = sbwho._carica(f)
                    if c and c.get("entity_id") == r["entity_id"]:
                        d_ris = c
                        break

            vv = variabili(nome, d_ris, r)
            vv["question shape"] = r0.get("_forma") or "direct"
            vv["candidates from the index"] = (
                "0"
                if not cand_n
                else "1"
                if cand_n == 1
                else "2-5"
                if cand_n <= 5
                else "6-20"
                if cand_n <= 20
                else "over 20"
            )
            for var, fascia in vv.items():
                incroci[var][fascia][v] += 1

            for x in invarianti(nome, r):
                viol_inv.append((nome, x))


            atteso = r0.get("atteso")
            if atteso == "attivo" and v == "CHIUSO":
                errori_duri.append((etichetta, nome, "ACTIVE declared CHIUSO"))
            elif atteso == "uscito" and v == "DENTRO":
                errori_duri.append((etichetta, nome, "departed per HR, declared DENTRO"))
            elif atteso == "non-chiuso" and v == "CHIUSO":
                errori_duri.append((etichetta, nome, "in ClickUp now, declared CHIUSO"))
            elif atteso == "mai-persona" and v in ("DENTRO", "STALE", "CHIUSO"):
                errori_duri.append(
                    (etichetta, nome, f"organization with a person verdict ({v})")
                )

    print("\n  [A] COVERAGE — the verdict per population")
    for etichetta in pop:
        tot = sum(per_pop[etichetta].values())
        if not tot:
            continue
        parti = " · ".join(
            f"{v} {c} ({100 * c / tot:.0f}%)"
            for v, c in sorted(per_pop[etichetta].items(), key=lambda x: -x[1])[:5]
        )
        print(f"    {etichetta:12} ({tot:4}) {parti}")

    print("\n  [B] CROSS-TABS — where the error pockets hide")
    for var in incroci:
        _stampa_incrocio(var, incroci[var])

    print(f"\n  [C] INVARIANTS — properties that must hold on every input ({n_tot} responses)")
    if viol_inv:
        agg: dict[str, int] = defaultdict(int)
        for _n, x in viol_inv:
            agg[x] += 1
        print(f"    🔴 {len(viol_inv)} violations, {len(agg)} types:")
        for x, c in sorted(agg.items(), key=lambda y: -y[1]):
            esempio = next(n for n, y in viol_inv if y == x)
            print(f"       {c:5}× {x}")
            print(f"             e.g. «{esempio[:60]}»")
    else:
        print("    ✅ no violations")


    rnd = random.Random(SEME)
    campione_t = rnd.sample(pop["store"], min(120, len(pop["store"])))
    ko_t, ko_d = [], []
    for r0 in campione_t:
        ko_t += [(r0["nome"], x) for x in prove_temporali(r0["nome"], idx)]
        ko_d += [(r0["nome"], x) for x in determinismo(r0["nome"], idx)]
    print(f"\n    temporal consistency (--as-of, {len(campione_t)} cases): ", end="")
    print(f"🔴 {len(ko_t)} violations" if ko_t else "✅ none")
    for n, x in ko_t[:4]:
        print(f"       · {n[:44]}: {x}")
    print(f"    determinism ({len(campione_t)} cases): ", end="")
    print(f"🔴 {len(ko_d)} violations" if ko_d else "✅ same question, same answer")


    campione_f = rnd.sample(pop["store"], min(200, len(pop["store"])))
    ko_f = []
    for r0 in campione_f:
        ko_f += [(r0["nome"], x) for x in stabilita_di_forma(r0["nome"], idx)]
    print(f"    form stability ({len(campione_f)} people × 5 spellings): ", end="")
    print(f"🔴 {len(ko_f)} violations" if ko_f else "✅ uppercase and spaces do not change the verdict")
    for n_, x in ko_f[:4]:
        print(f"       · {n_[:40]}: {x[:100]}")


    ko_a = []
    for r0 in pop.get("alias", [])[:400]:
        ko_a += [(r0["nome"], x) for x in coerenza_alias(r0["nome"], r0["_canonico"], idx)]
    print(f"    alias↔canonical consistency ({min(400, len(pop.get('alias', [])))} cases): ", end="")
    print(f"🔴 {len(ko_a)} violations" if ko_a else "✅ same person, same verdict")
    for n_, x in ko_a[:4]:
        print(f"       · {x[:120]}")


    ko_o = []
    for r0 in pop.get("org", []):
        ko_o += [(r0["nome"], x) for x in org_mai_persona(r0["nome"], idx)]
    print(f"    organizations ({len(pop.get('org', []))}): ", end="")
    print(
        f"🔴 {len(ko_o)} with a person verdict"
        if ko_o
        else "✅ none receives a person verdict"
    )
    for n_, x in ko_o[:4]:
        print(f"       · {x[:120]}")

    ko_t = ko_t + ko_f + ko_a + ko_o

    print("\n  [D] ADVERSARIAL TESTS")
    av = avversariali(idx)
    if av:
        for desc, cosa, grav in av:
            print(f"    {grav} {desc:24} {cosa}")
    else:
        print(
            f"    ✅ {len(AVVERSARIALI)} hostile inputs, none produces an assertion or an error"
        )

    print("\n  [E] HARD TRUTH — where someone knows the right answer")
    if errori_duri:
        agg2: dict[str, int] = defaultdict(int)
        for _e, _n, x in errori_duri:
            agg2[x] += 1
        for x, c in sorted(agg2.items(), key=lambda y: -y[1]):
            print(f"    🔴 {c}× {x}")
            for e, n, y in errori_duri:
                if y == x:
                    print(f"          · {n} ({e})")
                    break
    else:
        print("    ✅ no error against the sources that know the answer")

    gravi = (
        len(errori_duri)
        + len(viol_inv)
        + len(ko_t)
        + len(ko_d)
        + sum(1 for _d, _c, g in av if g == "🔴")
    )
    print(f"\n  ── {n_tot} cases · {gravi} serious problems ──")
    if a.json:
        print(
            json.dumps(
                {
                    "casi": n_tot,
                    "per_popolazione": {k: dict(v) for k, v in per_pop.items()},
                    "incroci": {k: {f: dict(c) for f, c in v.items()} for k, v in incroci.items()},
                    "violazioni_invarianti": len(viol_inv),
                    "errori_duri": len(errori_duri),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 1 if gravi else 0


if __name__ == "__main__":
    raise SystemExit(main())
