#!/usr/bin/env python3
""




























































from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
PERSONIO = cfg.DATA_ROOT / "personio" / "employees-flat.json"


BLOCKLIST = cfg.DATA_ROOT / "rq" / "non-person-blocklist.json"



WHATSAPP = cfg.DATA_ROOT / "whatsapp" / "chats"
BRIDGE = cfg.DATA_ROOT / "rq" / "entity-bridge.json"




PESI = {
    "personio": 100,
    "email": 90,



    "telefono": 88,
    "local_part": 60,








    "nome_identico": 50,
    "nome_contenuto": 30,
    "nome_simile": 25,
    "attio": 55,
}


def norm(s: object) -> str:
    ""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9@. ]", " ", s.lower()).split())


def norm_nome(s: object) -> str:
    ""












    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace("\u2019", "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def e_gruppo(nome: str) -> bool:
    ""
    return bool(re.search(r"[,&/]|\s(?:e|and)\s|\[", nome or ""))


def _somiglia(a: str, b: str) -> bool:
    ""





    ta, tb = a.split(), b.split()
    if len(ta) != len(tb) or not ta:
        return False
    diverse = 0
    for x, y in zip(ta, tb):
        if x == y:
            continue
        diverse += 1
        if diverse > 1 or abs(len(x) - len(y)) > 2 or x[:3] != y[:3]:
            return False

        corta, lunga = (x, y) if len(x) < len(y) else (y, x)
        if not lunga.startswith(corta[:-1]):
            return False
    return diverse == 1


@dataclass
class Prova:
    tipo: str
    dettaglio: str
    peso: int






















IDENTIFICATORI = frozenset({"personio", "email", "telefono"})




SOGLIA = 90


@dataclass
class Candidato:
    entity_id: str
    nome: str
    n_fatti: int
    canali: dict
    prove: list[Prova] = field(default_factory=list)


    solo_omonimia: bool = False

    @property
    def punteggio(self) -> int:
        return sum(p.peso for p in self.prove)

    @property
    def verdetto(self) -> str:
        ""












        ident = {p.tipo for p in self.prove} & IDENTIFICATORI
        if ident and not self.solo_omonimia:
            return "PROVEN"
        if self.punteggio >= SOGLIA:
            return "TO-CONFIRM"
        return "CLUES" if self.punteggio else "name only"


_INDICE: list[dict] | None = None


def _carica_entita() -> list[dict]:
    ""






    global _INDICE  # noqa: PLW0603
    if _INDICE is not None:
        return _INDICE
    out = []
    for f in PERSON.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        nome = (d.get("canonical_name") or "").strip()
        if not nome or e_gruppo(nome):
            continue
        fatti = d.get("facts") or []
        out.append(
            {
                "eid": f.stem,
                "nome": nome,
                "n": len(fatti),
                "email": {
                    norm(x.get("value"))



                    for x in fatti
                    if str(x.get("attribute") or "") in ("contact.email", "identity.email")
                    and "@" in str(x.get("value") or "")
                },
                "tel": {
                    n
                    for n in (
                        norm_tel(x.get("value"))
                        for x in fatti
                        if "phone" in str(x.get("attribute") or "")
                        or "mobile" in str(x.get("attribute") or "")
                    )
                    if n
                },
                "canali": Counter((x.get("source") or {}).get("source_type") for x in fatti),
            }
        )
    _INDICE = out
    return out


def norm_tel(t: object) -> str:
    ""





    d = re.sub(r"\D", "", str(t or ""))
    if d.startswith("00"):
        d = d[2:]
    return "+" + d if 8 <= len(d) <= 13 else ""


_RUBRICA: dict[str, set[str]] | None = None


def rubrica_whatsapp() -> dict[str, set[str]]:
    ""





    global _RUBRICA  # noqa: PLW0603
    if _RUBRICA is not None:
        return _RUBRICA
    out: dict[str, set[str]] = {}
    if WHATSAPP.exists():
        for f in WHATSAPP.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if (d.get("participant_count") or len(d.get("participants") or [])) > 2:
                continue
            altri = [p for p in (d.get("participants") or []) if not cfg.is_own_name(str(p))]
            numeri = {n for n in (norm_tel(x) for x in (d.get("phone_numbers") or [])) if n}
            if altri and numeri and len(str(altri[0]).split()) >= 2:
                out.setdefault(norm_nome(altri[0]), set()).update(numeri)
    _RUBRICA = out
    return out


_CASELLE: frozenset[str] | None = None


def e_casella_di_servizio(indirizzo: str) -> bool:
    ""










    global _CASELLE  # noqa: PLW0603
    if _CASELLE is None:
        pref: set[str] = set()
        try:
            d = json.loads(BLOCKLIST.read_text(encoding="utf-8"))
            pref = {str(x).rstrip("@").lower() for x in d.get("email_prefixes", [])}
        except (json.JSONDecodeError, OSError):  # pragma: no cover
            pass


        pref |= {"ceo", "amministrazione", "segreteria", "office", "help", "press"}
        _CASELLE = frozenset(pref)
    return str(indirizzo).split("@")[0].strip().lower() in _CASELLE


def _personio() -> list[dict]:
    if not PERSONIO.exists():
        return []
    try:
        d = json.loads(PERSONIO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return d if isinstance(d, list) else (d.get("data") or d.get("employees") or [])


def _iniziali(nome: str) -> set[str]:
    ""





    pezzi = [p for p in norm(nome).split() if len(p) > 1]
    if len(pezzi) < 2:
        return {pezzi[0]} if pezzi else set()
    primo, ultimo = pezzi[0], pezzi[-1]
    return {
        f"{primo}{ultimo[0]}",
        f"{primo[0]}{ultimo}",
        f"{primo}.{ultimo}",
        f"{primo}{ultimo}",
        f"{ultimo}{primo[0]}",
    }


def indaga(nome_cercato: str, limite: int = 12) -> tuple[list[Candidato], list[str]]:
    bersaglio = norm_nome(nome_cercato)
    token = set(bersaglio.split())






    if e_gruppo(nome_cercato):
        return [], [
            f"«{nome_cercato}» names several people: it's a group record, not a person",
            "ask one at a time — on a group any answer would be about just one of the names",
        ]

    entita = _carica_entita()






    compatto = bersaglio.replace(" ", "")
    grezzi = [
        e
        for e in entita
        if (token & set(norm_nome(e["nome"]).split()))
        or (len(compatto) >= 8 and norm_nome(e["nome"]).replace(" ", "") == compatto)
    ]






    mail_di_partenza = {m for e in grezzi if norm_nome(e["nome"]) == bersaglio for m in e["email"]}
    if mail_di_partenza:
        gia = {e["eid"] for e in grezzi}
        grezzi += [
            e for e in entita if e["eid"] not in gia and (set(e["email"]) & mail_di_partenza)
        ]

    if not grezzi:
        return [], [f"no entity carries a piece of «{nome_cercato}»"]

    riserve: list[str] = []
    cand = {
        e["eid"]: Candidato(e["eid"], e["nome"], e["n"], dict(e["canali"].most_common(5)))
        for e in grezzi
    }
    per_eid = {e["eid"]: e for e in grezzi}


    dip = _personio()





    nudo = norm_nome(re.sub(r"\(.*?\)", " ", str(nome_cercato)))
    cognome = (nudo or bersaglio).split()[-1] if (nudo or bersaglio).split() else ""





    def _nome_hr(r: dict) -> str:
        return norm_nome(
            r.get("full_name") or f"{r.get('first_name', '')} {r.get('last_name', '')}"
        )











    capi = [x for x in ((nudo or bersaglio).split() or [""]) if x]
    capi = {capi[-1], capi[0]} if capi else set()
    righe = [
        r for r in dip if capi and _nome_hr(r).split()[-1:][0:1] and _nome_hr(r).split()[-1] in capi
    ]










    tok_bersaglio = set(bersaglio.split())

    def _e_del_bersaglio(r: dict) -> bool:



        tok_hr = set(_nome_hr(r).split())
        if tok_bersaglio and (tok_bersaglio <= tok_hr or tok_hr <= tok_bersaglio):
            return True
        em = norm(r.get("email"))
        return bool(em) and em.split("@")[0] in _iniziali(bersaglio)




    hr_per_mail = {norm(r.get("email")): _nome_hr(r) for r in dip if r.get("email")}
    righe_bersaglio = [r for r in righe if _e_del_bersaglio(r)]
    mail_hr = {norm(r.get("email")) for r in righe_bersaglio if r.get("email")}
    if righe and not righe_bersaglio:
        riserve.append(
            f"no Personio row matches «{nome_cercato}»: "
            "the surname is there, the person isn't — the strong proof is unavailable"
        )
    if righe:
        nomi_hr = ", ".join(
            (r.get("full_name") or f"{r.get('first_name', '')} {r.get('last_name', '')}").strip()
            + (f" <{r.get('email')}>" if r.get("email") else "")
            for r in righe[:4]
        )
        riserve.append(
            f"Personio knows {len(righe)} person(s) with «{cognome}» out of {len(dip)}: {nomi_hr}"
            + ("  → the surname is UNIQUE in the company" if len(righe) == 1 else "")
        )


    tutte_mail: dict[str, list[str]] = defaultdict(list)
    for eid, e in per_eid.items():
        for m in e["email"]:
            tutte_mail[m].append(eid)









    mail_bersaglio = set(mail_hr)
    tel_bersaglio: set[str] = set()
    for e in per_eid.values():
        if norm_nome(e["nome"]) == bersaglio:
            mail_bersaglio |= set(e["email"])
            tel_bersaglio |= set(e.get("tel") or set())





    tel_bersaglio |= rubrica_whatsapp().get(nudo or bersaglio, set())

    bridge = {}
    if BRIDGE.exists():
        try:
            bridge = json.loads(BRIDGE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            riserve.append("entity-bridge.json unreadable: the «same Attio contact» proof is missing")

    omonimi = sum(1 for e in per_eid.values() if norm_nome(e["nome"]) == bersaglio)









    bersaglio_e_mononimo = len([x for x in bersaglio.split() if len(x) > 1]) < 2

    for eid, c in cand.items():
        e = per_eid[eid]
        for m in e["email"]:
            if m in mail_hr:
                c.prove.append(
                    Prova("personio", f"same email as the HR record: {m}", PESI["personio"])
                )





            altri = [x for x in tutte_mail[m] if x != eid]
            if (
                altri
                and not e_casella_di_servizio(m)
                and (m in mail_bersaglio or m.split("@")[0] in _iniziali(bersaglio))
            ):
                c.prove.append(
                    Prova("email", f"{m} shared with {len(altri)} other entity/entities", PESI["email"])
                )
            local = m.split("@")[0]











            padrone = hr_per_mail.get(m)
            if padrone and not (tok_bersaglio and tok_bersaglio <= set(padrone.split())):
                if m not in mail_hr:
                    continue










            suo = norm_nome(e["nome"]) != bersaglio and local in _iniziali(e["nome"])








            utili = [x for x in (nudo or bersaglio).split() if len(x) > 1]
            if not suo and len(utili) >= 2 and local in _iniziali(nudo or bersaglio):
                c.prove.append(
                    Prova("local_part", f"«{local}@» is the short form of the name", PESI["local_part"])
                )







        if not any(p.tipo == "local_part" for p in c.prove):
            for mb in mail_hr:
                if mb.split("@")[0] in _iniziali(e["nome"]):
                    c.prove.append(
                        Prova(
                            "local_part",
                            f"the target's address «{mb}» encodes «{e['nome']}»",
                            PESI["local_part"],
                        )
                    )
                    break
        for tp in e.get("tel") or set():
            if tp in tel_bersaglio:
                c.prove.append(Prova("telefono", f"same number {tp}", PESI["telefono"]))
                break
        else:

            suoi_rub = rubrica_whatsapp().get(norm_nome(e["nome"]), set())
            if suoi_rub & tel_bersaglio:
                c.prove.append(
                    Prova(
                        "telefono",
                        f"same number in the address book {sorted(suoi_rub & tel_bersaglio)[0]}",
                        PESI["telefono"],
                    )
                )

        n = norm_nome(e["nome"])
        if n == bersaglio and omonimi > 1 and len(bersaglio.split()) >= 2:
            c.prove.append(
                Prova(
                    "nome_identico",
                    f"{omonimi} records carry exactly this name",
                    PESI["nome_identico"],
                )
            )






        tn, tb = set(n.split()), set(bersaglio.split())
        stesso_compatto = len(compatto) >= 8 and n.replace(" ", "") == compatto and n != bersaglio
        if n != bersaglio and (
            bersaglio in n or n in bersaglio or tn <= tb or tb <= tn or stesso_compatto
        ):
            c.prove.append(
                Prova(
                    "nome_contenuto",
                    f"«{e['nome']}» contains or is contained",
                    PESI["nome_contenuto"],
                )
            )
        elif n != bersaglio and _somiglia(n, bersaglio):






            c.prove.append(
                Prova("nome_simile", f"«{e['nome']}» is very similar (typo?)", PESI["nome_simile"])
            )







    ancore = {
        bridge.get(eid)
        for eid, c in cand.items()
        if any(p.tipo in ("personio", "email") for p in c.prove)
    }
    ancore.discard(None)
    for eid, c in cand.items():
        pid = bridge.get(eid)
        if not pid or str(pid).startswith("person_") or pid not in ancore:
            continue
        if any(p.tipo == "attio" for p in c.prove):
            continue
        c.prove.append(
            Prova("attio", f"same Attio contact ({pid}) as a proven candidate", PESI["attio"])
        )




    for c in cand.values():
        visti_tipo: set[str] = set()
        uniche = []
        for pr in c.prove:
            if pr.tipo in visti_tipo:
                continue
            visti_tipo.add(pr.tipo)
            uniche.append(pr)
        c.prove = uniche











    hr_per_nome = {_nome_hr(r): norm(r.get("email")) for r in dip if r.get("email")}

    def _hr_di(nome_qualsiasi: str) -> str | None:
        chiave = norm_nome(re.sub(r"\(.*?\)", " ", nome_qualsiasi))
        if chiave in hr_per_nome:
            return hr_per_nome[chiave]
        tk = set(chiave.split())
        if len(tk) < 2:
            return None
        for nome_hr, em in hr_per_nome.items():
            th = set(nome_hr.split())
            if tk == th or tk <= th or th <= tk:
                return em
        return None

    mia = _hr_di(bersaglio)
    if mia:
        for eid, c in cand.items():
            sua = _hr_di(c.nome)
            if sua and sua != mia and c.prove:
                riserve.append(
                    f"«{c.nome}» is a different person according to Personio ({sua} vs {mia}): "
                    "the proofs that linked them come from wrong data in the store"
                )
                c.prove = []





    if bersaglio_e_mononimo:
        for c in cand.values():
            if norm_nome(c.nome) != bersaglio:
                c.solo_omonimia = True

    ordinati = sorted(cand.values(), key=lambda c: (-c.punteggio, -c.n_fatti, c.entity_id))[:limite]












    senza_prova = [c for c in ordinati if not any(p.tipo in ("email", "personio") for p in c.prove)]
    senza_indirizzo = [c for c in senza_prova if not per_eid.get(c.entity_id, {}).get("email")]
    con_indirizzo = len(senza_prova) - len(senza_indirizzo)
    if senza_indirizzo:
        riserve.append(
            f"{len(senza_indirizzo)} candidates out of {len(ordinati)} have no address: "
            "for them the strong proof can't exist, only the name remains"
        )
    if con_indirizzo:
        riserve.append(
            f"{con_indirizzo} candidates have an address that does NOT link to the target: "
            "the address is there, but it belongs to another person or can't be traced to the searched name"
        )
    canali = Counter()
    for c in ordinati:
        canali.update(c.canali)
    monocanale = [c for c in ordinati if len(c.canali) == 1]
    if monocanale:
        riserve.append(
            f"{len(monocanale)} candidates live on ONE channel only "
            f"({', '.join(sorted({list(c.canali)[0] for c in monocanale}))}): "
            "it's the signature of «one entity per channel instead of per person»"
        )
    riserve.append("this tool merges NOTHING: a merge is irreversible and goes through the user")
    return ordinati, riserve


def stampa(nome: str, cand: list[Candidato], riserve: list[str]) -> None:
    print(f"\n«{nome}» — {len(cand)} candidates, sorted by strength of proof\n")
    for c in cand:


        margine = c.punteggio - SOGLIA
        segno = f"+{margine}" if margine > 0 else str(margine)
        print(
            f"  {c.entity_id}  «{c.nome}»  ({c.n_fatti} facts)  → {c.verdetto}  [{c.punteggio}, {segno} from the threshold]"
        )
        print(f"      channels: {c.canali}")
        for p in c.prove:
            print(f"      ✓ {p.dettaglio}")
        if not c.prove:
            print("      — no proof beyond the name: not enough to say it's the same person")
        print()
    print("  to know:")
    for r in riserve:
        print(f"    · {r}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Who is the same person, and with what proof")
    ap.add_argument("nome", help="the name to investigate, even partial")
    ap.add_argument("--limite", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cand, riserve = indaga(a.nome, a.limite)
    if a.json:
        print(
            json.dumps(
                {
                    "cercato": a.nome,
                    "candidati": [
                        {
                            "entity_id": c.entity_id,
                            "nome": c.nome,
                            "fatti": c.n_fatti,
                            "canali": c.canali,
                            "punteggio": c.punteggio,
                            "prove": [p.__dict__ for p in c.prove],
                        }
                        for c in cand
                    ],
                    "riserve": riserve,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        stampa(a.nome, cand, riserve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
