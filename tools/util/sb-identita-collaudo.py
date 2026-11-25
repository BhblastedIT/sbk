#!/usr/bin/env python3
""














































from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

SEME = 2026


def _modulo():
    spec = importlib.util.spec_from_file_location("sbi", REPO / "tools/util/sb-identita.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sbi"] = mod
    spec.loader.exec_module(mod)
    return mod


def norm(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def _personio() -> list[dict]:
    p = cfg.DATA_ROOT / "personio" / "employees-flat.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return d if isinstance(d, list) else (d.get("data") or d.get("employees") or [])


def _bucket(n: int) -> str:
    return (
        "1"
        if n <= 1
        else "2-9"
        if n < 10
        else "10-99"
        if n < 100
        else "100-999"
        if n < 1000
        else "1000+"
    )


def _forma(nome: str) -> str:
    if "(" in nome:
        return "con-parentesi"
    if any(ord(c) > 127 for c in nome):
        return "con-accenti"
    t = len(nome.split())
    return "1-token" if t == 1 else "2-token" if t == 2 else "3+-token"


def costruisci_casi(m, quanti: int, scala: int = 1) -> list[dict]:
    ""






    rnd = random.Random(SEME)
    ent = m._carica_entita()
    per_eid = {e["eid"]: e for e in ent}
    casi: list[dict] = []
    visti: set[str] = set()

    def agg(nome, fascia, atteso=None, extra=None):
        k = f"{fascia}|{norm(nome)}"
        if not nome or k in visti:
            return
        visti.add(k)
        casi.append({"nome": nome, "fascia": fascia, "atteso": atteso, **(extra or {})})


    for r in _personio():
        nome = (r.get("full_name") or f"{r.get('first_name', '')} {r.get('last_name', '')}").strip()
        agg(nome, "P1-personio", extra={"hr_email": norm(r.get("email"))})


    per_mail = collections.defaultdict(list)
    for e in ent:
        for x in e["email"]:
            per_mail[x].append(e["eid"])





    coppie = {k: v for k, v in per_mail.items() if len(v) > 1 and not m.e_casella_di_servizio(k)}
    for mail, eids in coppie.items():
        e0 = per_eid[eids[0]]
        agg(
            e0["nome"],
            "P2-email-condivisa",
            atteso="collega",
            extra={"gemelli": eids[1:], "mail": mail},
        )







    conflitti_tel: list[tuple[str, str, str]] = []
    rub = m.rubrica_whatsapp()
    per_tel = collections.defaultdict(set)
    for e in ent:
        for t_ in e.get("tel") or set():
            per_tel[t_].add(e["eid"])
        for t_ in rub.get(m.norm_nome(e["nome"]), set()):
            per_tel[t_].add(e["eid"])
    for numero, eids in per_tel.items():
        if len(eids) < 2:
            continue
        eids = sorted(eids)
        e0 = per_eid.get(eids[0])
        if not e0:
            continue










        compat = []
        for altro in eids[1:]:
            e1 = per_eid.get(altro)
            if not e1:
                continue
            ta, tb = set(m.norm_nome(e0["nome"]).split()), set(m.norm_nome(e1["nome"]).split())
            entrambi_kb = numero in (e0.get("tel") or set()) and numero in (e1.get("tel") or set())
            if (
                ta <= tb
                or tb <= ta
                or m._somiglia(m.norm_nome(e0["nome"]), m.norm_nome(e1["nome"]))
                or entrambi_kb
            ):
                compat.append(altro)
        if compat:
            agg(
                e0["nome"],
                "P9-telefono-condiviso",
                atteso="collega",
                extra={"gemelli": compat, "tel": numero},
            )
        elif len(eids) > 1:
            e1 = per_eid.get(eids[1])
            if e1:
                conflitti_tel.append((e0["nome"], e1["nome"], numero))





    parlati = {"plaud", "tactiq", "attio_call", "voice_memo"}
    crm = {"attio", "attio_notes"}
    for etichetta, ins in (("registrazione", parlati), ("crm", crm)):
        pop = [e for e in ent if e["canali"] and set(e["canali"]) <= ins]
        for e in rnd.sample(pop, min(60 * scala, len(pop))):
            agg(e["nome"], f"P10-{etichetta}")


    per_bucket = collections.defaultdict(list)
    for e in ent:
        per_bucket[_bucket(e["n"])].append(e)
    for b, gruppo in per_bucket.items():
        for e in rnd.sample(gruppo, min(45 * scala, len(gruppo))):
            agg(e["nome"], f"P3-fatti-{b}")


    per_canale = collections.defaultdict(list)
    for e in ent:
        for c in e["canali"]:
            per_canale[c].append(e)
    for c, gruppo in per_canale.items():
        for e in rnd.sample(gruppo, min(12 * scala, len(gruppo))):
            agg(e["nome"], f"P4-canale-{c}")


    per_forma = collections.defaultdict(list)
    for e in ent:
        per_forma[_forma(e["nome"])].append(e)
    for f, gruppo in per_forma.items():
        for e in rnd.sample(gruppo, min(45 * scala, len(gruppo))):
            agg(e["nome"], f"P5-forma-{f}")


    mono = [e for e in ent if len(e["canali"]) == 1]
    for e in rnd.sample(mono, min(90 * scala, len(mono))):
        agg(e["nome"], "P6-monocanale")


    gruppi = []
    for f in (cfg.DATA_ROOT / "knowledge/entities/person").glob("*.json"):
        if len(gruppi) >= 60 * scala:
            break
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n = (d.get("canonical_name") or "").strip()
        if n and m.e_gruppo(n):
            gruppi.append(n)
    for n in gruppi:
        agg(n, "P7-record-gruppo", atteso="niente")






    base = [
        e
        for e in ent
        if len(e["nome"].split()) == 2
        and e["n"] >= 20
        and all(len(x) > 2 and x[0].isupper() for x in e["nome"].split())
        and not re.search(
            r"team|group|srl|ltd|company|success|affiliate|world|customer|project|"
            r"business|product|content|investment|Globex",
            e["nome"],
            re.I,
        )
    ]
    for e in rnd.sample(base, min(30 * scala, len(base))):
        n = e["nome"]
        p, c = n.split()[0], n.split()[-1]
        agg(f"{c} {p}", "P8-invertito", atteso="collega")
        agg(f"{p[0]}. {c}", "P8-iniziale", atteso=None)
        agg(n.lower(), "P8-minuscolo", atteso="collega")
        agg(f"{n} (Head of Something)", "P8-con-ruolo", atteso="collega")

        if len(c) > 4:
            i = len(c) // 2
            agg(f"{p} {c[:i]}{'x' if c[i] != 'x' else 'y'}{c[i + 1 :]}", "P8-refuso", atteso=None)
    for i in range(30 * scala):
        agg(f"Zqx{i}vlm Wkjrt{i}pn", "P8-inventato", atteso="niente")

    if conflitti_tel:
        casi.append(
            {
                "nome": "__conflitti_telefono__",
                "fascia": "P11-conflitto-fonti",
                "atteso": None,
                "conflitti": conflitti_tel,
            }
        )
    rnd.shuffle(casi)
    return casi[:quanti] if quanti and quanti < len(casi) else casi


def esegui(m, casi: list[dict]) -> list[dict]:
    out = []
    for c in casi:
        if c["fascia"] == "P11-conflitto-fonti":
            out.append({"caso": c, "candidati": [], "riserve": ["voce di servizio, non una query"]})
            continue
        cand, ris = m.indaga(c["nome"], 15)
        out.append(
            {
                "caso": c,
                "candidati": [
                    {
                        "eid": x.entity_id,
                        "nome": x.nome,
                        "fatti": x.n_fatti,
                        "canali": x.canali,
                        "punteggio": x.punteggio,
                        "prove": [p.tipo for p in x.prove],
                    }
                    for x in cand
                ],
                "riserve": ris,
            }
        )
    return out












REGRESSIONI = [
    {
        "bug": "P18 · a service mailbox made two people come out as the same",
        "cerca": "Mia Conti",
        "non_deve": "Mia Conti",
        "perche": "they share only info@esempio.com, the domain of a third person",
    },
    {
        "bug": "P18 · «Name + initial» promised on any namesake",
        "cerca": "Sara L",
        "non_deve": None,
        "perche": "«Sara L» has two tokens but only one useful: any sara@ scored 60",
    },
    {
        "bug": "P17 · the HR proof was of the surname family, not the person",
        "cerca": "Sam Monroe",
        "non_deve": "Drew Monroe",
        "perche": "two different employees with different HR addresses",
    },
    {






        "bug": "P19 · «name + surname initial» collides between different people",
        "cerca": "Alex Rossi",
        "non_prova": ("Dana Neri", "local_part"),
        "perche": "danan@ is Neri's real address and is the short form of both",
    },
    {







        "bug": "P18 · a bare first name identifies no one",
        "cerca": "Angelo",
        "non_deve": None,
        "perche": "«angelo@» is the short form of any Angelo, and «D'Angelo» is not a surname «Angelo»",
    },
    {
        "bug": "P17 · the KB contradicted Personio and the KB won",
        "cerca": "Jordan Marsh",
        "non_deve": "Jordan Mason",
        "perche": "in the KB they share an address that in Personio belongs to only one",
    },
    {









        "bug": "P19 · a reversed, lowercase name must reach the person",
        "cerca": "mason jordan",
        "deve": "Jordan Mason",
        "perche": "it's how a chat writes it, and exact-string matching lost it",
    },
]


def regressioni(m) -> list[str]:
    ""
    rotti = []
    for r in REGRESSIONI:
        cand, _ = m.indaga(r["cerca"], 15)
        provati = [x for x in cand if x.punteggio >= 90]


        if r.get("non_prova"):
            chi, tipo = r["non_prova"]
            for x in cand:
                if norm(x.nome) == norm(chi) and any(p.tipo == tipo for p in x.prove):
                    rotti.append(
                        f"{r['bug']} — «{r['cerca']}» receives «{tipo}» from «{x.nome}» ({r['perche']})"
                    )
                    break
            continue
        if r.get("deve"):
            if not any(norm(x.nome) == norm(r["deve"]) for x in provati):
                rotti.append(f"{r['bug']} — «{r['cerca']}» no longer reaches «{r['deve']}»")
            continue
        if r.get("non_deve") is None:
            if provati:
                rotti.append(f"{r['bug']} — «{r['cerca']}» promotes «{provati[0].nome}»")
            continue
        for x in provati:
            if norm(x.nome) == norm(r["non_deve"]):
                rotti.append(f"{r['bug']} — «{r['cerca']}» → «{x.nome}» ({r['perche']})")
                break
    return rotti


def invarianti(m, ris: list[dict]) -> dict:  # noqa: C901
    ""
    hr = {}
    for r in _personio():
        n = norm(r.get("full_name") or f"{r.get('first_name', '')} {r.get('last_name', '')}")
        if n:
            hr[n] = norm(r.get("email"))
    rotti = collections.defaultdict(list)
    indice = {e["eid"]: e for e in m._carica_entita()}
    SOLO_NOME = {"nome_contenuto", "nome_simile"}

    for r in ris:
        c = r["caso"]
        nome = c["nome"]
        provati = [x for x in r["candidati"] if x["punteggio"] >= 90]

        for x in provati:
            if set(x["prove"]) <= SOLO_NOME:
                rotti["I1 · PROVATO only on name proofs"].append(f"{nome} → {x['nome']}")
            eb, ex = hr.get(norm(nome)), hr.get(norm(x["nome"]))
            if eb and ex and eb != ex:
                rotti["I2 · PROVATO across different HR emails"].append(
                    f"{nome} → {x['nome']} {x['prove']}"
                )
            if len(x["prove"]) != len(set(x["prove"])):
                rotti["I8 · proof type counted twice"].append(f"{nome} → {x['nome']}")











            if norm(x["nome"]) != norm(nome) and "local_part" in x["prove"]:
                suoi = indice.get(x["eid"], {}).get("email") or set()





                mie = {norm(r_.get("email")) for r_ in _personio() if r_.get("email")} & {
                    e2 for e2 in (indice.get(x["eid"], {}).get("email") or set())
                }
                nudo_b = norm(re.sub(r"\(.*?\)", " ", nome))





                ta_, tb_ = set(nudo_b.split()), set(norm(x["nome"]).split())
                if ta_ <= tb_ or tb_ <= ta_:
                    continue
                if any(
                    e_.split("@")[0] in m._iniziali(x["nome"])
                    and e_.split("@")[0] not in m._iniziali(nudo_b)
                    and e_ not in mie
                    for e_ in suoi
                ):
                    rotti[
                        "I9 · someone else's address inside a record (DATA contamination)"
                    ].append(f"{nome} → {x['nome']}")

        if c["fascia"] in ("P2-email-condivisa", "P9-telefono-condiviso"):
            gem = set(c.get("gemelli") or [])
            trovati = {x["eid"] for x in r["candidati"]}






            smentito_da_hr = any(
                hr.get(norm(nome))
                and hr.get(norm(x["nome"]))
                and hr[norm(nome)] != hr[norm(x["nome"])]
                for x in r["candidati"]
            )
            if gem and not (gem & trovati) and not smentito_da_hr:
                rotti["I3 · twins with the same address not linked"].append(
                    f"{nome} (mail {c.get('mail')})"
                )






        for s in r["riserve"]:
            mm = re.match(r"(\d+) candidati su (\d+) non hanno nessun indirizzo", s)
            if mm:
                atteso = sum(
                    1
                    for x in r["candidati"][: int(mm.group(2))]
                    if not indice.get(x["eid"], {}).get("email")
                )
                if int(mm.group(1)) != atteso:
                    rotti["I11 · a reserve declares a false number"].append(
                        f"{nome}: says {mm.group(1)}, they are {atteso}"
                    )



        if c.get("atteso") == "collega" and c["fascia"].startswith("P8-"):
            base = norm(re.sub(r"\(.*?\)", " ", nome))




            if not any(set(norm(x["nome"]).split()) & set(base.split()) for x in r["candidati"]):
                rotti["I13 · a «collega» adversary links nothing"].append(
                    f"{c['fascia']}: {nome}"
                )
        if c["fascia"] == "P11-conflitto-fonti":
            for a_, b_, n_ in c.get("conflitti") or []:
                rotti[
                    "I14 · address book and store assign the same number to two names (DATA)"
                ].append(f"{a_} ≠ {b_} — {n_}")
            continue
        if c["fascia"] == "P8-inventato" and provati:
            rotti["I4 · invented name with a PROVATO"].append(nome)
        if c["fascia"] == "P7-record-gruppo" and provati:
            rotti["I6 · group-record with a PROVATO"].append(nome)

        if c["fascia"] == "P11-conflitto-fonti":
            continue
        forte = any(p in ("personio", "email") for x in r["candidati"] for p in x["prove"])


        if not forte and not any(
            s_ in s
            for s in r["riserve"]
            for s_ in (
                "nessun indirizzo",
                "NON lega",
                "prova forte",
                "nessuna entità",
                "record-gruppo",
            )
        ):
            rotti["I5 · no strong proof and no reserve"].append(nome)

    return dict(rotti)


def negazioni(m, quanti: int = 400) -> list[str]:
    ""











    per_nome: dict[str, str] = {}
    for e in m._carica_entita():
        per_nome.setdefault(norm(e["nome"]), e["eid"])
    coppie: list[tuple[str, str]] = []
    for f in (cfg.DATA_ROOT / "knowledge/entities/person").glob("*.json"):
        if len(coppie) >= quanti * 6:
            break
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n = (d.get("canonical_name") or "").strip()
        if not n or not m.e_gruppo(n):
            continue
        pezzi = [x.strip() for x in re.split(r"[,&/]| e | and ", n) if x.strip()]

        risolti = [p_ for p_ in pezzi if len(p_.split()) >= 2 and norm(p_) in per_nome]
        for i in range(len(risolti)):
            for j in range(i + 1, len(risolti)):
                coppie.append((risolti[i], risolti[j]))
    rnd = random.Random(SEME + 4)
    rotti = []
    for a, b in rnd.sample(coppie, min(quanti, len(coppie))):
        if norm(a) == norm(b):
            continue
        cand, _ = m.indaga(a, 15)
        for x in cand:
            if norm(x.nome) == norm(b) and x.punteggio >= 90:
                rotti.append(f"«{a}» and «{b}» appear together in a group, but come out PROVATI")
                break
    return rotti


def transitivita(m, quanti: int = 40) -> list[str]:
    ""






    ent = m._carica_entita()
    per_eid = {e["eid"]: e for e in ent}
    padre: dict[str, str] = {}

    def trova(x):
        while padre.get(x, x) != x:
            padre[x] = padre.get(padre[x], padre[x])
            x = padre[x]
        return x

    per_mail = collections.defaultdict(list)
    for e in ent:
        for m_ in e["email"]:
            per_mail[m_].append(e["eid"])
    for eids in per_mail.values():
        for a in eids[1:]:
            padre[trova(a)] = trova(eids[0])
    comp = collections.defaultdict(set)
    for e in ent:
        if e["eid"] in padre or any(e["eid"] in v for v in per_mail.values()):
            comp[trova(e["eid"])].add(e["eid"])
    rnd = random.Random(SEME + 3)
    rotti = []
    grandi = [c for c in comp.values() if len(c) >= 3]
    for c in rnd.sample(grandi, min(quanti, len(grandi))):
        eids = sorted(c)
        a, z = per_eid.get(eids[0]), per_eid.get(eids[-1])
        if not a or not z or set(a["email"]) & set(z["email"]):
            continue
        cand, _ = m.indaga(a["nome"], 30)
        if z["eid"] not in {x.entity_id for x in cand}:
            rotti.append(f"«{a['nome']}» does not reach «{z['nome']}» (same address chain)")
    return rotti


def determinismo(m, casi: list[dict], quanti: int = 60) -> list[str]:
    rnd = random.Random(SEME + 1)
    rotti = []
    for c in rnd.sample(casi, min(quanti, len(casi))):
        a, _ = m.indaga(c["nome"], 15)
        b, _ = m.indaga(c["nome"], 15)
        if [(x.entity_id, x.punteggio) for x in a] != [(x.entity_id, x.punteggio) for x in b]:
            rotti.append(c["nome"])
    return rotti


def simmetria(m, ris: list[dict], quanti: int = 60) -> list[str]:
    ""










    rnd = random.Random(SEME + 2)
    coppie = []
    for r in ris:
        for x in r["candidati"]:
            if x["punteggio"] >= 90 and norm(x["nome"]) != norm(r["caso"]["nome"]):
                coppie.append((r["caso"]["nome"], x["nome"]))
    rotti = []
    for a, b in rnd.sample(coppie, min(quanti, len(coppie))):
        na, nb = norm(a), norm(b)
        ta, tb = set(na.split()), set(nb.split())
        if na in nb or nb in na or ta <= tb or tb <= ta:




            continue
        if m._somiglia(na, nb):







            continue
        cand, _ = m.indaga(b, 15)










        def _compatibile(nome_x: str) -> bool:
            tx = set(norm(nome_x).split())
            return (
                len(ta & tx) >= 2
                or ta <= tx
                or tx <= ta
                or norm(nome_x).replace(" ", "") == na.replace(" ", "")
            )

        if not any(x.punteggio >= 90 and _compatibile(x.nome) for x in cand):
            rotti.append(f"«{a}» → «{b}» but not the reverse")
    return rotti


def incroci(ris: list[dict]) -> dict:
    ""
    m_ = _modulo() if False else None  # noqa: F841
    tab = collections.defaultdict(lambda: collections.Counter())
    for r in ris:
        c = r["caso"]
        pr = [x for x in r["candidati"] if x["punteggio"] >= 90]
        ind = [x for x in r["candidati"] if 0 < x["punteggio"] < 90]
        esito = "PROVATO" if pr else ("indizi" if ind else "niente")
        tab["fascia"][(c["fascia"].split("-")[0], esito)] += 1
        if r["candidati"]:
            top = r["candidati"][0]
            tab["fatti"][(_bucket(top["fatti"]), esito)] += 1
            tab["canali"][(min(len(top["canali"]), 5), esito)] += 1
        tab["forma"][(_forma(c["nome"]), esito)] += 1
    return {k: dict(v) for k, v in tab.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Test bench for sb-identita")
    ap.add_argument("--casi", type=int, default=0, help="0 = all generated")
    ap.add_argument("--scala", type=int, default=1, help="multiply the quotas of each population")
    ap.add_argument("--json", type=str, default="", help="where to save the results")
    a = ap.parse_args()

    m = _modulo()
    casi = costruisci_casi(m, a.casi, a.scala)
    print(f"CASES: {len(casi)}")
    for f, n in collections.Counter(c["fascia"].split("-")[0] for c in casi).most_common():
        print(f"   {f}: {n}")

    ris = esegui(m, casi)
    rotti = invarianti(m, ris)
    det = determinismo(m, casi)
    sim = simmetria(m, ris)
    if det:
        rotti["I7 · same input, different output"] = det
    if sim:
        rotti["I10 · asymmetry"] = sim
    tra = transitivita(m)
    if tra:
        rotti["I3bis · address chain not closed"] = tra
    reg = regressioni(m)
    if reg:
        rotti["I15 · a defect already paid for is back"] = reg
    neg = negazioni(m)
    if neg:
        rotti["I12 · two people listed together come out as the same"] = neg





    salute = {k: v for k, v in rotti.items() if "DATA" in k}
    difetti = {k: v for k, v in rotti.items() if k not in salute}

    print("\n═══ TOOL INVARIANTS")
    if not difetti:
        print("   ✅ all green")
    for k in sorted(difetti):
        v = difetti[k]
        print(f"   ❌ {k}: {len(v)}")
        for x in v[:4]:
            print(f"        {x}")

    if salute:
        print("\n═══ DATA HEALTH (the tool reports, it does not err)")
        for k in sorted(salute):
            v = salute[k]
            print(f"   ⚠️  {k}: {len(v)}")
            for x in v[:6]:
                print(f"        {x}")

    print("\n═══ CROSS-TABS")
    for var, tab in incroci(ris).items():
        print(f"   ── {var}")
        chiavi = sorted({k[0] for k in tab})
        for k in chiavi:
            riga = {e: tab.get((k, e), 0) for e in ("PROVATO", "indizi", "niente")}
            tot = sum(riga.values()) or 1
            print(
                f"      {str(k):16} PROVATO {riga['PROVATO']:4} · indizi {riga['indizi']:4} · niente {riga['niente']:4}   (n={tot})"
            )

    if a.json:
        Path(a.json).write_text(
            json.dumps(
                {
                    "casi": len(casi),
                    "invarianti": rotti,
                    "incroci": {
                        k: {str(kk): vv for kk, vv in t.items()} for k, t in incroci(ris).items()
                    },
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"\nresults saved to {a.json}")
    return 1 if difetti else 0


if __name__ == "__main__":
    sys.exit(main())
