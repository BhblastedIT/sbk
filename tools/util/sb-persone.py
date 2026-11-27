#!/usr/bin/env python3
"""Who in the person folder of the knowledge base is not a person: classifies every entity as person, dirty name,
non-person (company, role, mailbox), uncertain or mention, with the proof; --radice runs on a copy.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if str(Path(__file__).resolve().parent.parent / "cross-source") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cross-source"))

from conteggio import Conteggio  # noqa: E402
from knowledge_schema import e_pseudo_identita  # noqa: E402

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
BLOCKLIST = cfg.DATA_ROOT / "rq" / "non-person-blocklist.json"

_CASELLE: frozenset[str] | None = None


def e_casella(indirizzo: str) -> bool:
    ""







    global _CASELLE  # noqa: PLW0603
    if _CASELLE is None:
        pref: set[str] = set()
        try:
            d = json.loads(BLOCKLIST.read_text(encoding="utf-8"))
            pref = {str(x).rstrip("@").lower() for x in d.get("email_prefixes", [])}
        except (json.JSONDecodeError, OSError):  # pragma: no cover
            pass
        pref |= {"co-ceo", "ceo", "amministrazione", "segreteria", "office", "help", "press"}
        _CASELLE = frozenset(pref)
    return str(indirizzo).split("@")[0].strip().lower() in _CASELLE












PROVE_DI_PERSONA = (
    "employment.",
    "contact.email",
    "contact.phone",
    "personal.",
    "behavioral.",
    "identity.given_name",
    "identity.surname",

    "crm.attio_record_id",
    "crm.linkedin_url",
    "contact.linkedin_url",

    "relationship.linkedin_chat",
)


AZIENDA = re.compile(
    r"\b(srl|s\.r\.l|spa|s\.p\.a|ltd|llc|inc|gmbh|b\.?v\.?|sas|sagl|group|holding|"
    r"agency|consulting|capital|ventures|partners|labs?|technologies|solutions|systems|"
    r"software|media|academy|school|associati|societa|impresa|azienda|studio legale|"
    r"realty|estate|immobiliare|bank|insurance|fund|trust|sim|corporation|corp|company)\b",
    re.I,
)


RUOLO = re.compile(
    r"\b(customer|support|sales|admin|info|hr|people ops|finance|legal|product|project|"
    r"content|business|investment|operations|success|service|team|dept|department|"
    r"clienti|amministrazione|segreteria|contabilita|marketing)\b",
    re.I,
)


_ORGANIZZAZIONI: frozenset[str] | None = None


def nomi_di_organizzazione() -> frozenset[str]:
    ""














    global _ORGANIZZAZIONI  # noqa: PLW0603
    if _ORGANIZZAZIONI is None:
        out = set()
        for d in ("organization", "org"):
            cartella = PERSON.parent / d
            if not cartella.exists():
                continue
            for f in cartella.glob("*.json"):
                try:
                    x = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                n = norm(re.sub(r"\(.*?\)", " ", x.get("canonical_name") or ""))
                if n:
                    out.add(n)









                    out.add(n.replace(" ", ""))
        _ORGANIZZAZIONI = frozenset(out)
    return _ORGANIZZAZIONI


_BATTESIMO: frozenset[str] | None = None


def e_nome_di_battesimo(parola: str) -> bool:
    ""











    global _BATTESIMO  # noqa: PLW0603
    if _BATTESIMO is None:
        primi: collections.Counter = collections.Counter()
        for f in PERSON.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            n = (d.get("canonical_name") or "").strip()
            pezzi = re.sub(r"\(.*?\)", " ", n).split()
            if len(pezzi) >= 2 and all(x[:1].isupper() for x in pezzi[:2]):
                primi[pezzi[0].lower()] += 1







        marchi = set()
        org = PERSON.parent / "organization"
        if org.exists():
            for f in org.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                n = re.sub(r"\(.*?\)", " ", (d.get("canonical_name") or "")).split()
                if n:
                    marchi.add(n[0].lower())
        _BATTESIMO = frozenset(k for k, v in primi.items() if v >= 3 and k not in marchi)
    return str(parola).strip().lower() in _BATTESIMO


def norm(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def _partecipazione() -> dict:
    ""







    try:
        import knowledge_view as kv

        return kv._carica_partecipazione()
    except Exception:  # pragma: no cover
        return {}


def _episodi_di_contatto(conteggi: dict) -> int:
    ""









    try:
        import knowledge_view as kv

        return kv.episodi_di_contatto(conteggi)
    except Exception:  # pragma: no cover
        return 0









CATEGORIE = ("PERSONA", "NOME-SPORCO", "NON-PERSONA", "INCERTO", "MENZIONE")


@dataclass
class Verdetto:
    entity_id: str
    nome: str
    n_fatti: int
    categoria: str
    perche: list[str] = field(default_factory=list)
    canali: dict = field(default_factory=dict)


def _sporcizia(nome: str) -> list[str]:
    ""










    fuori = []
    nudo_ = re.sub(r"\(.*?\)", " ", nome).strip()
    if "@" not in nome and len(nudo_.split()) == 1 and nudo_[:1].isupper():
        fuori.append("is a mononym: the surname is missing, so it does not identify")
    dentro_parentesi = " ".join(re.findall(r"\((.*?)\)", nome))
    if "@" in nome:
        fuori.append("contains an email address")
    if dentro_parentesi and (AZIENDA.search(dentro_parentesi) or RUOLO.search(dentro_parentesi)):
        fuori.append(f"parenthetical with a role or a company: «{dentro_parentesi[:40]}»")
    if re.search(r"\d", nome) and not re.search(r"\d", re.sub(r"\(.*?\)", "", nome)):
        fuori.append("digits only inside the parenthetical")
    return fuori


def classifica(eid: str, nome: str, fatti: list[dict]) -> Verdetto:
    canali = collections.Counter((f.get("source") or {}).get("source_type") for f in fatti)
    perche: list[str] = []

    prove = []
    for f in fatti:
        a = str(f.get("attribute") or "")
        if not a.startswith(PROVE_DI_PERSONA):
            continue
        if a == "contact.email" and e_casella(f.get("value")):
            continue
        prove.append(a)
    nudo = re.sub(r"\(.*?\)", " ", nome).strip()
    sporco = _sporcizia(nome)


    if re.match(r"^speaker\b", nome.strip(), re.I):
        return Verdetto(
            eid,
            nome,
            len(fatti),
            "NON-PERSONA",
            ["«Speaker N» is a transcriber label, not a person"],
            dict(canali),
        )


    if re.match(r"^(the|a|an|il|lo|la|le|gli|i)\s", nome.strip(), re.I):
        return Verdetto(
            eid,
            nome,
            len(fatti),
            "NON-PERSONA",
            ["the name starts with an article: it is a reference, not a name"],
            dict(canali),
        )


    if "@" in nudo and not nudo.replace("@", "").strip().split():
        return Verdetto(
            eid, nome, len(fatti), "NON-PERSONA", ["the name is only an address"], dict(canali)
        )
    if nome.startswith("person_"):
        return Verdetto(
            eid, nome, len(fatti), "NON-PERSONA", ["the name is the identifier"], dict(canali)
        )




    societa = []




    if (
        norm(nudo) in nomi_di_organizzazione()
        or norm(nudo).replace(" ", "") in nomi_di_organizzazione()
    ):
        return Verdetto(
            eid,
            nome,
            len(fatti),
            "NON-PERSONA",
            ["an organization record with this name already exists"],
            dict(canali),
        )
    if AZIENDA.search(nudo):
        societa.append("the name carries a corporate form")
    if RUOLO.search(nudo):
        societa.append("the name is a role or a function")
    if societa:
        return Verdetto(eid, nome, len(fatti), "NON-PERSONA", societa, dict(canali))






    dentro = " ".join(re.findall(r"\((.*?)\)", nome))
    if (
        dentro
        and (AZIENDA.search(dentro) or RUOLO.search(dentro))
        and len(nudo.split()) < 2
        and not e_nome_di_battesimo(nudo)
    ):
        return Verdetto(
            eid,
            nome,
            len(fatti),
            "NON-PERSONA",
            [f"the parenthetical qualifies an organization: «{dentro[:38]}»"],
            dict(canali),
        )









    scambio = _episodi_di_contatto(_partecipazione().get(eid, {}))
    if scambio:
        perche.append(f"took part in {scambio} real episodes (spoke or was present)")

        return Verdetto(
            eid,
            nome,
            len(fatti),
            "NOME-SPORCO" if sporco else "PERSONA",
            perche + sporco,
            dict(canali),
        )

    if prove:
        perche.append(f"has {len(prove)} facts that only a person has ({prove[0]}…)")
        if sporco:
            return Verdetto(eid, nome, len(fatti), "NOME-SPORCO", perche + sporco, dict(canali))
        return Verdetto(eid, nome, len(fatti), "PERSONA", perche, dict(canali))


    if AZIENDA.search(nudo):
        perche.append("the name carries a corporate form")
    if RUOLO.search(nudo):
        perche.append("the name is a role or a function")
    if re.search(r"\d", nudo):
        perche.append("the name contains digits")
    if not re.match(r"^[A-ZÀ-Ü]", nome.strip()):
        perche.append("does not start with a capital letter")
    if perche:
        return Verdetto(eid, nome, len(fatti), "NON-PERSONA", perche, dict(canali))

    if sporco:
        return Verdetto(eid, nome, len(fatti), "NOME-SPORCO", sporco, dict(canali))







    sorgenti = {
        str(
            (f.get("source") or {}).get("record_id")
            or (f.get("source") or {}).get("source_file")
            or ""
        )
        for f in fatti
    }
    sorgenti.discard("")
    if len(sorgenti) <= 1 and len(canali) <= 1 and not scambio:
        return Verdetto(
            eid,
            nome,
            len(fatti),
            "MENZIONE",
            [
                f"named in a single source on a single channel ({', '.join(canali) or 'unknown'}), "
                "never a participant: it is a spoken name, not a known person"
            ],
            dict(canali),
        )


    return Verdetto(
        eid,
        nome,
        len(fatti),
        "INCERTO",
        [
            "the name is plausible but there is no fact that proves a person: "
            "it could be anyone who was merely named"
        ],
        dict(canali),
    )


def scorri(saltati: dict | None = None, fuori: dict | None = None, radice: Path | None = None):
    ""


















    if saltati is None:
        saltati = {}
    if fuori is None:
        fuori = {}
    saltati.setdefault("json illeggibile", 0)
    saltati.setdefault("senza canonical_name", 0)

    fuori.setdefault("pseudo-identità", 0)


    for f in sorted((radice or PERSON).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saltati["json illeggibile"] += 1
            continue
        nome = (d.get("canonical_name") or "").strip()
        if not nome:
            saltati["senza canonical_name"] += 1
            continue
        fatti = d.get("facts") or []





        if e_pseudo_identita(fatti):
            fuori["pseudo-identità"] += 1
            continue
        yield classifica(f.stem, nome, fatti)








SENZA_PROVA = ("INCERTO", "NON-PERSONA", "MENZIONE")


def misura(radice: Path | None = None) -> dict:
    ""









    conta: collections.Counter = collections.Counter()
    peso: collections.Counter = collections.Counter()
    saltati: dict = {}
    fuori: dict = {}
    for v in scorri(saltati, fuori, radice):
        conta[v.categoria] += 1
        peso[v.categoria] += v.n_fatti
    entita = sum(conta.values())
    fatti = sum(peso.values())
    senza = sum(conta[c] for c in SENZA_PROVA)
    fatti_senza = sum(peso[c] for c in SENZA_PROVA)
    pseudo = fuori.get("pseudo-identità", 0)
    return {
        "senza_prova": Conteggio(senza, entita, saltati),
        "non_persona": Conteggio(conta["NON-PERSONA"], entita, saltati),
        "fatti_senza_prova": Conteggio(fatti_senza, fatti, saltati),
        "per_categoria": {k: Conteggio(n, entita, saltati) for k, n in conta.items()},




        "pseudo_identita": Conteggio(pseudo, entita + pseudo, saltati),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Who in person/ is not a person")
    ap.add_argument("--categoria", default="", help="NON-PERSONA · NOME-SPORCO · INCERTO · PERSONA")
    ap.add_argument("--min-fatti", type=int, default=0, help="only above this threshold")
    ap.add_argument("--quanti", type=int, default=25)
    ap.add_argument("--json", default="")
    ap.add_argument("--radice", default="", help="a COPY of the store (default: the live data)")
    a = ap.parse_args()

    conta = collections.Counter()
    tenuti: list[Verdetto] = []
    peso = collections.Counter()
    saltati: dict = {}
    fuori: dict = {}
    for v in scorri(saltati, fuori, Path(a.radice) if a.radice else None):
        conta[v.categoria] += 1
        peso[v.categoria] += v.n_fatti
        if (not a.categoria or v.categoria == a.categoria) and v.n_fatti >= a.min_fatti:
            tenuti.append(v)

    tot = sum(conta.values())
    pseudo = fuori.get("pseudo-identità", 0)
    print(f"\nENTITIES IN person/: {tot + pseudo}")


    print(f"   of which pseudo-identities (placeholders, outside the census): {pseudo}")
    print(f"   population judged: {tot}\n")
    for k, n in conta.most_common():
        c = Conteggio(n, tot, saltati)
        print(f"   {k:14} {c!s:>22}  ({c.percentuale(1)}%)   {peso[k]:8} facts inside")
    senza = Conteggio(sum(conta[c] for c in SENZA_PROVA), tot, saltati)
    print(
        f"\n   {'without proof':14} {senza!s:>22}  ({senza.percentuale()}%)  "
        f"← INCERTO + NON-PERSONA + MENZIONE"
    )


    if any(saltati.values()):
        print(f"   ⚠️  skipped: {saltati}")

    tenuti.sort(key=lambda v: -v.n_fatti)
    if a.categoria:
        print(f"\n── {a.categoria}, the largest:\n")
        for v in tenuti[: a.quanti]:
            print(f"   {v.nome[:46]:46} {v.n_fatti:5} facts  {v.entity_id}")
            for p in v.perche[:2]:
                print(f"        {p}")

    print(
        "\n  ⚠️  This tool touches nothing: it lists. Deleting a «dirty name» "
        "would lose a real person."
    )
    if a.json:
        Path(a.json).write_text(
            json.dumps(
                {
                    "conteggi": dict(conta),
                    "fatti_per_categoria": dict(peso),
                    "elenco": [v.__dict__ for v in tenuti[:2000]],
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"  list saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
