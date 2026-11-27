#!/usr/bin/env python3
"""Birthdays, birth dates and name days on the knowledge-base profiles: collects the dates found in your sources,
decides which are reliable, adds the name day from the saints calendar, and writes them as facts (--apply; dry
run by default). --check is the guard that the stage is registered and deletes nothing; --test-rules and
--self-test test the rules and the guard.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import os
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS = _THIS_DIR.parent
for _p in (str(_TOOLS), str(_THIS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sbk_config import (  # noqa: E402
    DATA_ROOT,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_LAST_EXTRACTION_FILE,
    KNOWLEDGE_META_DIR,
)

STADIO = "l2_ricorrenze"
STADIO_CALENDARIO = "l3_calendario_ricorrenze"
RUNNER = _THIS_DIR / "xs-pipeline-run.py"
CALENDARIO = _THIS_DIR / "xs-l3-birthday-calendar.py"
SANTI = _THIS_DIR / "onomastici-it.json"
VERIFICATE = KNOWLEDGE_META_DIR / "ricorrenze-verificate.json"
USCITA = KNOWLEDGE_META_DIR / "ricorrenze.json"
RAPPORTO = KNOWLEDGE_META_DIR / "ricorrenze-stadio.json"
RAPPORTO_CALENDARIO = KNOWLEDGE_META_DIR / "ricorrenze-calendario-stadio.json"


PERSONIO_COME_FONTE = False

GIORNI_SILENZIO = 14

SCHEDA_TROPPO_GRANDE = 50 * 1024 * 1024
OWNER = "person_00000000"

SOURCE_TYPE = "ricorrenze"
ATTR_NASCITA = (
    "relationship.birthday",
    "identity.date_of_birth",
    "personal.date_of_birth",
    "identity.birth_date",
)
ATTR_ONOMASTICO = "relationship.onomastico"
CONF = {"sicura": 0.95, "quasi sicura": 0.8, "da confermare": 0.5}

NOSTRI = re.compile(r"knowledge/meta/ricorrenze|manual-ingestion/compleanni", re.I)



MESI: dict[str, int] = {}
for _i, _nomi in enumerate(
    [
        "gennaio january enero jan gen",
        "febbraio february febrero feb",
        "marzo march mar",
        "aprile april abril apr",
        "maggio may mayo mag",
        "giugno june junio jun giu",
        "luglio july julio jul lug",
        "agosto august aug ago",
        "settembre september septiembre sep sept set",
        "ottobre october octubre oct ott",
        "novembre november noviembre nov",
        "dicembre december diciembre dec dic",
    ],
    start=1,
):
    for _n in _nomi.split():
        MESI[_n] = _i
_MRE = r"(" + "|".join(sorted(MESI, key=len, reverse=True)) + r")\.?"
_ONO = re.compile(r"onomastic|name ?day|\bsan(ta|to|t')?\s|\bsaint\b", re.I)
_APPROX = re.compile(
    r"approx|around|circa|about|early|mid-|late|\bor\b|\bo\b|between|\bfra\b|\btra\b|implied|"
    r"next week|relative|soon|week after|after|before|ritardo|scorso|ieri|yesterday|tomorrow|domani|"
    r"alrededor|antes|specific date not|not specified|non specificat",
    re.I,
)
_ETA = re.compile(
    r"\b\d{1,3}\s*(years?\s*old|anni|años|enne)\b|\bage\s*\d+|\bturn(ing|ed|s)\s*\d+|"
    r"\b\d+(st|nd|rd|th)\s*birthday|compie\s*\d+|cumple\s*\d+|^\d{1,2}$",
    re.I,
)
_RANGE = re.compile(_MRE + r"\s+\d{1,2}\s*-\s*\d{1,2}\b", re.I)
_RELATIVO = re.compile(
    r"\bieri\b|yesterday|\bdomani\b|tomorrow|in ritardo|\blate\b|belated|scorso|last week|ago\b|fa\b|mañana|ayer",
    re.I,
)
_ONOQ = re.compile(r"onomastic|name ?day", re.I)
FESTE = {"12-25", "12-26", "01-01", "12-31", "08-15", "11-01", "03-08", "02-14"}
# The user's own key month-day dates; reminders on these are suppressed.
# This is a synthetic placeholder: replace with your own, or set to set() to
# disable (the self-test in `prova()` relies on it being non-empty).
DATE_DI_OWNER = {"04-20"}
# Date windows to exclude (YYYY-MM-DD start/end); dates inside a window are not
# treated as birthdays. Replace with your own, or set both equal to disable.
EXCLUDED_DATE_WINDOW = ("2025-01-01", "2025-01-01")


def _valida(mese: int, giorno: int) -> bool:
    try:
        date(2000, mese, giorno)
        return True
    except ValueError:
        return False


def normalizza(valore, valid_from=None) -> dict:
    ""




    s = str(valore or "").strip()
    out = {
        "cat": "rumore",
        "mmdd": None,
        "anno": None,
        "approx": bool(_APPROX.search(s) or _RANGE.search(s)),
    }
    anno_msg = (
        int(str(valid_from)[:4]) if valid_from and re.match(r"\d{4}", str(valid_from)) else None
    )
    mese = giorno = anno = None
    m = re.search(r"\b(19\d\d|20\d\d)-(\d\d)-(\d\d)\b", s)
    if m:
        anno, mese, giorno = int(m[1]), int(m[2]), int(m[3])
    elif m := re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b", s):
        giorno, mese, anno = int(m[1]), int(m[2]), int(m[3])
        if anno < 100:
            anno += 1900 if anno > 30 else 2000
    elif m := re.fullmatch(r"(\d\d)-(\d\d)", s):
        mese, giorno = int(m[1]), int(m[2])
    elif m := re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+)?" + _MRE + r"(?:,?\s+(?:de\s+)?(\d{4}))?\b",
        s,
        re.I,
    ):
        giorno, mese, anno = int(m[1]), MESI[m[2].lower()], (int(m[3]) if m[3] else None)
    elif (
        m := re.search(_MRE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", s, re.I)
    ) and not re.match(r"\d{4}", m[2] or ""):
        mese, giorno, anno = MESI[m[1].lower()], int(m[2]), (int(m[3]) if m[3] else None)
    elif m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", s):
        giorno, mese = int(m[1]), int(m[2])
    if mese and giorno and _valida(mese, giorno):
        out["mmdd"] = f"{mese:02d}-{giorno:02d}"
        if _ONO.search(s):
            out["cat"] = "onomastico"
        elif anno:
            out["anno"] = anno
            vicino = (anno_msg and abs(anno - anno_msg) <= 1) or anno >= 2014
            out["cat"] = "data_evento" if vicino else "data_nascita"
        else:
            out["cat"] = "giorno_mese"
        return out
    if _ONO.search(s):
        out["cat"] = "onomastico"
    elif _ETA.search(s):
        out["cat"] = "eta"
    elif (m := re.search(r"\b(19[2-9]\d|200\d)\b", s)) and re.search(
        r"born|nat[oa]|^\s*\d{4}\s*$", s, re.I
    ):
        out["cat"], out["anno"] = "solo_anno", int(m[1])
    elif re.search(r"\b" + _MRE + r"\b", s, re.I):
        out["cat"] = "solo_mese"
    return out





def _vicini(mmdd: str) -> set[str]:
    d = date(2000, int(mmdd[:2]), int(mmdd[3:]))
    return {(d + timedelta(days=k)).strftime("%m-%d") for k in (-1, 1)}


def peso(f: dict) -> tuple[str | None, float]:
    ""
    if f["a"] in ("identity.date_of_birth", "personal.date_of_birth", "identity.birth_date"):
        if f["s"] == "personio":
            return ("P", 10.0) if PERSONIO_COME_FONTE else (None, 0.0)
        return ("D", 5.0)
    if f["cat"] == "data_nascita":
        return ("D", 3.0)
    if f["cat"] == "giorno_mese":
        w = 1.0
    elif f["cat"] == "data_evento":
        w = 0.8
    else:
        return (None, 0.0)
    if f["approx"] or _RELATIVO.search(f.get("q") or ""):
        w *= 0.3
    return ("G", w)


def decidi(
    fatti: list[dict],
    date_onomastico: set[str],
    *,
    scheda_di_owner: bool = False,
    rifiutate=(),
    condivise=frozenset(),
) -> dict:
    ""




    cand: dict[str, list] = collections.defaultdict(list)
    scarti: collections.Counter = collections.Counter()
    for f in fatti:
        md = f.get("mmdd")
        if not md:
            continue
        if md in rifiutate:
            scarti["rejected"] += 1
            continue
        if f["cat"] == "onomastico" or _ONOQ.search(f.get("q") or ""):
            scarti["declared name day"] += 1
            continue
        if md in DATE_DI_OWNER and not scheda_di_owner:
            scarti["the owner's own date"] += 1
            continue
        if (
            md in date_onomastico
            and f["cat"] != "data_nascita"
            and f["a"] == "relationship.birthday"
        ):
            scarti["name day of the first name"] += 1
            continue
        vf = (f.get("vf") or "")[:10]
        if vf and EXCLUDED_DATE_WINDOW[0] <= vf <= EXCLUDED_DATE_WINDOW[1] and f["cat"] != "data_nascita":
            scarti["excluded window"] += 1
            continue
        if (md, f.get("anno")) in condivise and f["cat"] == "data_nascita":
            scarti["birth date shared by several people"] += 1
            continue
        if md == "01-01" or (md in FESTE and f["cat"] != "data_nascita"):
            scarti["public holiday"] += 1
            continue
        if scheda_di_owner and f["s"] not in ("manual_input", "personio", "gdrive", "docusign"):
            scarti["chat on the owner's own card"] += 1
            continue
        tipo, w = peso(f)
        if not tipo:
            continue
        cand[md].append((tipo, w, f["s"], (f.get("vf") or "")[:4]))
    if not cand:
        return {"data": None, "livello": None, "scarti": dict(scarti)}
    punti = {
        md: sum(x[1] for x in lst) + 0.5 * sum(x[1] for v in _vicini(md) for x in cand.get(v, []))
        for md, lst in cand.items()
    }
    best = max(punti, key=lambda m: (punti[m], sum(x[1] for x in cand[m])))
    s1 = punti[best]
    s2 = max((s for m, s in punti.items() if m != best and m not in _vicini(best)), default=0.0)
    gruppo = cand[best] + [x for v in _vicini(best) for x in cand.get(v, [])]
    tipi = {x[0] for x in gruppo}
    indipendenti = {(x[2], x[3]) for x in gruppo}
    anni = collections.Counter(
        f["anno"]
        for f in fatti
        if f.get("mmdd") == best and f["cat"] == "data_nascita" and f.get("anno")
    )
    if s1 >= 5 and s1 >= 3 * s2 and (tipi & {"P", "D"} or len(indipendenti) >= 3):
        livello = "sicura"
    elif s1 >= 2 and s1 >= 2 * s2 and len(indipendenti) >= 2:
        livello = "quasi sicura"
    else:
        livello = "da confermare"
    return {
        "data": best,
        "livello": livello,
        "anno": anni.most_common(1)[0][0] if anni else None,
        "punti": round(s1, 2),
        "rivale": round(s2, 2),
        "scarti": dict(scarti),
    }




_TITOLI = {
    "zia",
    "zio",
    "nonna",
    "nonno",
    "mamma",
    "papà",
    "papa",
    "dott",
    "dr",
    "avv",
    "ing",
    "sig",
    "sig.ra",
}


def carica_santi(path: Path = SANTI) -> dict:
    return json.loads(path.read_text())


def onomastico_del_nome(nome: str, santi: dict) -> dict | None:
    ""
    tokens = [t for t in re.split(r"[\s,/()]+", (nome or "").lower()) if t and t not in _TITOLI]
    if not tokens:
        return None
    primo = tokens[0]
    sop = santi["soprannomi"].get(primo)
    if sop:
        if sop["ambiguo"] or len(sop["nomi"]) != 1:
            return None
        primo = sop["nomi"][0].lower()
    voce = santi["santi"].get(primo)
    if not voce or voce.get("certezza") != "alta":
        return None
    return voce


def date_onomastico(nome: str, santi: dict) -> set[str]:
    ""
    out: set[str] = set()
    for t in re.split(r"[\s,/()]+", (nome or "").lower()):
        nomi = santi["soprannomi"].get(t, {}).get("nomi", [t])
        for n in nomi:
            v = santi["santi"].get(n.lower())
            if v:
                out.add(v["mmdd"])
                out.update(v.get("alternative", []))
    return out





def _token_nome(n: str) -> frozenset | None:
    t = [x for x in re.split(r"[\s,]+", re.sub(r"\(.*?\)|/.*$", "", (n or "").lower())) if x]
    return frozenset(t) if len(t) >= 2 else None


def leggi_kb(entities_dir: Path = KNOWLEDGE_ENTITIES_DIR / "person") -> tuple[dict, dict, dict]:
    ""
    schede: dict[str, dict] = {}
    per_nome: dict[frozenset, list] = collections.defaultdict(list)
    conta = collections.Counter()
    for p in entities_dir.glob("person_*.json"):
        conta["schede_lette"] += 1
        try:
            if p.stat().st_size > SCHEDA_TROPPO_GRANDE:
                conta["saltate_troppo_grandi"] += 1
                continue
            testo = p.read_text()
        except OSError:
            conta["illeggibili"] += 1
            continue
        nome_rapido = re.search(r'"canonical_name":\s*"((?:[^"\\]|\\.)*)"', testo)
        nome = json.loads(f'"{nome_rapido[1]}"') if nome_rapido else ""
        eid = p.stem
        tk = _token_nome(nome)
        if tk:
            per_nome[tk].append(eid)
        if not any(a in testo for a in (*ATTR_NASCITA, ATTR_ONOMASTICO)):
            continue
        try:
            d = json.loads(testo)
        except ValueError:
            conta["illeggibili"] += 1
            continue
        fatti = []
        for f in d.get("facts", []):
            if f.get("attribute") not in (*ATTR_NASCITA, ATTR_ONOMASTICO):
                continue
            src = f.get("source") or {}
            fatti.append(
                {
                    "a": f["attribute"],
                    "v": f.get("value"),
                    "s": src.get("source_type") or "",
                    "sf": src.get("source_file") or "",
                    "q": src.get("evidence_quote") or "",
                    "vf": f.get("valid_from"),
                    "chiuso": bool(
                        f.get("expired_at") or f.get("superseded_by") or f.get("valid_to")
                    ),
                }
            )
        schede[eid] = {
            "nome": d.get("canonical_name") or nome,
            "n_fatti": len(d.get("facts", [])),
            "fatti": fatti,
        }
        conta["schede_con_fatti"] += 1
    return schede, per_nome, conta


def _chiave(attr: str, valore) -> tuple:
    return (attr, str(valore).strip().lower())





def date_condivise(schede: dict) -> frozenset:
    ""
    chi: dict[tuple, set] = collections.defaultdict(set)
    for eid, sc in schede.items():
        persona = _token_nome(sc["nome"]) or eid
        for f in sc["fatti"]:
            if f["chiuso"] or NOSTRI.search(f["sf"]) or f["s"] == SOURCE_TYPE:
                continue
            n = normalizza(f["v"], f["vf"])
            if n["cat"] == "data_nascita" and n["anno"]:
                chi[(n["mmdd"], n["anno"])].add(persona)
    return frozenset(k for k, v in chi.items() if len(v) > 1)


def calcola(schede: dict, per_nome: dict, verificate: dict, santi: dict, esistono) -> dict:
    ""
    conta = collections.Counter()
    condivise = date_condivise(schede)
    conta["date_di_nascita_su_piu_persone"] = len(condivise)
    categorie = collections.Counter()
    ver = {p["entity_id"]: p for p in verificate.get("persone", [])}
    for c in verificate.get("correzioni_da_calendario", []):
        p = ver.get(c.get("entity_id"))
        if p and c.get("campo") in ("compleanno", "onomastico"):
            vecchia = p.get(c["campo"])
            p[c["campo"]] = c["nuova"]
            if c["campo"] == "compleanno" and vecchia and vecchia != c["nuova"]:
                p.setdefault("rifiutate", []).append(vecchia)
    esclusi = {n.lower() for n in verificate.get("esclusi_da_owner", [])}
    persone, proposte = [], []
    scrivere: dict[str, list] = collections.defaultdict(list)
    chiudere: dict[str, list] = collections.defaultdict(list)

    def presenti(eid):
        return {_chiave(f["a"], f["v"]): f for f in schede.get(eid, {}).get("fatti", [])}

    for eid, p in ver.items():
        if not esistono(eid):
            conta["verificate_senza_scheda"] += 1
            continue
        have = presenti(eid)
        liv = p.get("certezza", "sicura")
        voluti = [("relationship.birthday", p["compleanno"], CONF[liv])]
        if p.get("anno"):
            voluti.append(("identity.date_of_birth", f"{p['anno']}-{p['compleanno']}", CONF[liv]))
        if p.get("onomastico"):
            voluti.append(
                (
                    ATTR_ONOMASTICO,
                    f"{p['onomastico']} ({p.get('santo', '')})".replace(" ()", ""),
                    0.9,
                )
            )
        for a, v, c in voluti:
            if _chiave(a, v) not in have:
                scrivere[eid].append(
                    {"attribute": a, "value": v, "confidence": c, "perche": "verificata"}
                )
        rif = set(p.get("rifiutate", []))
        for f in schede.get(eid, {}).get("fatti", []):
            if (
                f["a"] == "relationship.birthday"
                and not f["chiuso"]
                and normalizza(f["v"], f["vf"])["mmdd"] in rif
            ):
                chiudere[eid].append({"attribute": f["a"], "value": f["v"]})
        persone.append(
            {
                "entity_id": eid,
                "nome": p["nome"],
                "compleanno": p["compleanno"],
                "anno": p.get("anno"),
                "livello": liv,
                "fonte": "verificata",
                "onomastico": p.get("onomastico"),
                "santo": p.get("santo"),
                "calendario": bool(p.get("calendario")),
            }
        )
        conta["verificate"] += 1


    gruppo_di: dict[str, list] = {}
    for ids in per_nome.values():
        if len(ids) > 1:
            for i in ids:
                gruppo_di[i] = ids
    visti: set[str] = set(ver)
    for eid in sorted(schede):
        if eid in visti:
            continue
        gruppo = [i for i in gruppo_di.get(eid, [eid]) if i in schede]
        visti.update(gruppo)
        if any(i in ver for i in gruppo_di.get(eid, [])):
            continue
        principale = max((i for i in gruppo if i in schede), key=lambda i: schede[i]["n_fatti"])
        nome = schede[principale]["nome"]
        fatti, rifiutate = [], set()
        for i in gruppo:
            for f in schede.get(i, {}).get("fatti", []):
                if f["a"] == ATTR_ONOMASTICO:
                    continue
                n = normalizza(f["v"], f["vf"])
                categorie[n["cat"]] += 1
                if f["chiuso"]:
                    if n["mmdd"]:
                        rifiutate.add(n["mmdd"])
                    continue
                if NOSTRI.search(f["sf"]) or f["s"] == SOURCE_TYPE:
                    continue
                fatti.append({**f, **n})
        r = decidi(
            fatti,
            date_onomastico(nome, santi),
            scheda_di_owner=principale == OWNER,
            rifiutate=rifiutate,
            condivise=condivise,
        )
        if not r["data"]:
            conta["senza_data"] += 1
            continue
        conta[f"livello {r['livello']}"] += 1
        escluso = nome.lower() in esclusi
        if r["livello"] == "da confermare":
            if not escluso:
                proposte.append(
                    {"entity_id": principale, "nome": nome, "data": r["data"], "punti": r["punti"]}
                )
            continue
        if not esistono(principale):
            continue
        have = presenti(principale)
        if _chiave("relationship.birthday", r["data"]) not in have:
            scrivere[principale].append(
                {
                    "attribute": "relationship.birthday",
                    "value": r["data"],
                    "confidence": CONF[r["livello"]],
                    "perche": f"voto {r['punti']} contro {r['rivale']}, livello {r['livello']}",
                }
            )
        ono = onomastico_del_nome(nome, santi)
        ha_ono = any(
            f["a"] == ATTR_ONOMASTICO and not f["chiuso"] for f in schede[principale]["fatti"]
        )
        valore_ono = f"{ono['mmdd']} ({ono['santo']})" if ono else None
        if ono and not ha_ono and _chiave(ATTR_ONOMASTICO, valore_ono) not in have:
            scrivere[principale].append(
                {
                    "attribute": ATTR_ONOMASTICO,
                    "value": valore_ono,
                    "confidence": 0.8,
                    "perche": "dal nome",
                }
            )
        persone.append(
            {
                "entity_id": principale,
                "nome": nome,
                "compleanno": r["data"],
                "anno": r.get("anno"),
                "livello": r["livello"],
                "fonte": "automatica",
                "onomastico": ono["mmdd"] if ono else None,
                "santo": ono["santo"] if ono else None,
                "calendario": False,
                "escluso_da_owner": escluso,
            }
        )
    conta["proposte"] = len(proposte)
    return {
        "persone": persone,
        "proposte": sorted(proposte, key=lambda x: -x["punti"]),
        "scrivere": dict(scrivere),
        "chiudere": dict(chiudere),
        "conta": conta,
        "categorie": categorie,
    }





def _lock_vivo(nome: str) -> bool:
    p = DATA_ROOT / f"{nome}.pid"
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def scrivi(scrivere: dict, chiudere: dict) -> tuple[int, int, list[str]]:
    ""
    import importlib.util
    import uuid

    from knowledge_schema import Fact, FactSource

    spec = importlib.util.spec_from_file_location(
        "xs_l2_knowledge_extract", _THIS_DIR / "xs-l2-knowledge-extract.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    adesso = datetime.now(UTC).isoformat()
    oggi = adesso[:10]
    fatti = []
    for eid, lista in scrivere.items():
        for f in lista:
            fatti.append(
                Fact(
                    fact_id=str(uuid.uuid4()),
                    entity_id=eid,
                    entity_type="person",
                    attribute=f["attribute"],
                    value=f["value"],
                    confidence=f["confidence"],
                    valid_from=None,
                    valid_to=None,
                    created_at=adesso,
                    expired_at=None,
                    source=FactSource(
                        source_type=SOURCE_TYPE,
                        source_file="knowledge/meta/ricorrenze",
                        record_id=f"ricorrenze-{oggi}",
                        extracted_at=adesso,
                        evidence_quote=f["perche"],
                    ),
                )
            )
    for eid, lista in chiudere.items():
        for f in lista:
            fatti.append(
                Fact(
                    fact_id=str(uuid.uuid4()),
                    entity_id=eid,
                    entity_type="person",
                    attribute=f["attribute"],
                    value=f["value"],
                    confidence=0.1,
                    valid_from=None,
                    valid_to=None,
                    created_at=adesso,
                    expired_at=oggi,
                    source=FactSource(
                        source_type=SOURCE_TYPE,
                        source_file="knowledge/meta/ricorrenze",
                        record_id=f"ricorrenze-rifiutata-{oggi}",
                        extracted_at=adesso,
                        evidence_quote="data rifiutata nel file verificato",
                    ),
                )
            )
    if fatti:
        mod.write_profiles(fatti, dry_run=False)
    mancanti = []
    for eid in set(scrivere) | set(chiudere):
        d = json.loads((KNOWLEDGE_ENTITIES_DIR / "person" / f"{eid}.json").read_text())
        have = {_chiave(f["attribute"], f["value"]): f for f in d.get("facts", [])}
        for f in scrivere.get(eid, []):
            if _chiave(f["attribute"], f["value"]) not in have:
                mancanti.append(f"{eid} {f['attribute']}={f['value']}")
        for f in chiudere.get(eid, []):
            x = have.get(_chiave(f["attribute"], f["value"]))
            if not x or not x.get("expired_at"):
                mancanti.append(f"{eid} {f['attribute']}={f['value']} non chiuso")
    n_s = sum(len(v) for v in scrivere.values())
    n_c = sum(len(v) for v in chiudere.values())
    return n_s, n_c, mancanti


def esegui(apply: bool) -> int:
    t0 = time.time()
    if apply and _lock_vivo("knowledge-extract"):
        print(
            "Knowledge Extract is writing the KB: I won't write alongside it. Retry once extraction is done."
        )
        return 1
    santi = carica_santi()
    verificate = json.loads(VERIFICATE.read_text()) if VERIFICATE.exists() else {"persone": []}
    schede, per_nome, conta_kb = leggi_kb()
    persona_dir = KNOWLEDGE_ENTITIES_DIR / "person"
    r = calcola(
        schede, per_nome, verificate, santi, lambda eid: (persona_dir / f"{eid}.json").exists()
    )
    n_s = sum(len(v) for v in r["scrivere"].values())
    n_c = sum(len(v) for v in r["chiudere"].values())
    print(
        f"profiles read {conta_kb['schede_lette']}, with birth facts {conta_kb['schede_con_fatti']}"
    )
    print(
        f"people {len(r['persone'])} ({r['conta']['verificate']} verified), proposals to confirm {len(r['proposte'])}"
    )
    print(f"to write {n_s} facts across {len(r['scrivere'])} profiles, to close {n_c}")
    mancanti: list[str] = []
    if apply:
        n_s, n_c, mancanti = scrivi(r["scrivere"], r["chiudere"])
        for m in mancanti:
            print("DID NOT ARRIVE:", m)
    else:
        for eid, lista in list(r["scrivere"].items())[:20]:
            print("  would write", eid, [f"{f['attribute']}={f['value']}" for f in lista])
        print("(dry-run: --apply to write)")
        return 0
    try:
        estrazione = json.loads(KNOWLEDGE_LAST_EXTRACTION_FILE.read_text()).get("last_extraction")
    except (OSError, ValueError):
        estrazione = None
    quando = datetime.now(UTC).isoformat()
    from sbk_config import safe_write_json

    safe_write_json(
        USCITA,
        {"quando": quando, "persone": r["persone"], "proposte": r["proposte"]},
        indent=1,
    )
    safe_write_json(
        RAPPORTO,
        {
            "quando": quando,
            "estrazione_vista": estrazione,
            "durata_s": round(time.time() - t0, 1),
            "kb": dict(conta_kb),
            "categorie_valori": dict(r["categorie"]),
            "conta": dict(r["conta"]),
            "scritti_nuovi": n_s,
            "chiusi": n_c,
            "non_arrivati": mancanti,
            "personio_come_fonte": PERSONIO_COME_FONTE,
        },
        indent=1,
    )
    print(f"written {n_s}, closed {n_c}, did not arrive {len(mancanti)}. Report {RAPPORTO}")
    return 1 if mancanti else 0





def _passi_registrati(testo: str) -> dict[str, set[str]]:
    ""
    albero = ast.parse(testo)
    out = {"SCRIPTS": set(), "CATENA": set(), "_esegui": set(), "pagati": set(), "strato": {}}
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SCRIPTS" for t in nodo.targets
        ):
            if isinstance(nodo.value, ast.Dict):
                out["SCRIPTS"] |= {k.value for k in nodo.value.keys if isinstance(k, ast.Constant)}
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", None) == "Passo":
            kw = {k.arg: k.value for k in nodo.keywords}
            if isinstance(kw.get("id"), ast.Constant):
                pid = kw["id"].value
                out["CATENA"].add(pid)
                if isinstance(kw.get("tipo"), ast.Constant) and kw["tipo"].value == "pagato":
                    out["pagati"].add(pid)
                if isinstance(kw.get("strato"), ast.Constant):
                    out["strato"][pid] = kw["strato"].value
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "run_pipeline":
            for n in ast.walk(nodo):
                if (
                    isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == "_esegui"
                    and n.args
                    and isinstance(n.args[0], ast.Constant)
                ):
                    out["_esegui"].add(n.args[0].value)
    return out


def controlla_registrazione(testo: str) -> list[str]:
    reg = _passi_registrati(testo)
    rossi = []
    for pid in (STADIO, STADIO_CALENDARIO):
        for dove in ("SCRIPTS", "CATENA", "_esegui"):
            if pid not in reg[dove]:
                rossi.append(
                    f"{pid} missing from {dove} in xs-pipeline-run.py: the stage would never run"
                )
        if pid in reg["pagati"]:
            rossi.append(f"{pid} is marked paid: it would drop out of --propaga and --ingest")
    if reg["strato"].get(STADIO) not in (None, "L2"):
        rossi.append(f"{STADIO} must be in L2, not in {reg['strato'].get(STADIO)}")
    return rossi


def controlla_santi(santi: dict) -> list[str]:
    rossi = []
    for nome, v in santi.get("santi", {}).items():
        for md in [v.get("mmdd", "")] + v.get("alternative", []):
            if not re.fullmatch(r"\d\d-\d\d", md or "") or not _valida(int(md[:2]), int(md[3:])):
                rossi.append(f"onomastici-it.json: {nome} has an invalid date «{md}»")
        if v.get("certezza") not in ("alta", "media"):
            rossi.append(f"onomastici-it.json: {nome} without high or medium certainty")
    if len(santi.get("santi", {})) < 50:
        rossi.append("onomastici-it.json: fewer than 50 names, was the file emptied?")
    return rossi


def controlla_nessuna_cancellazione(testo: str) -> list[str]:
    for n in ast.walk(ast.parse(testo)):
        if isinstance(n, ast.Attribute) and n.attr in ("delete", "clear"):
            return [
                "xs-l3-birthday-calendar.py calls a deletion: the stage never deletes an event of yours"
            ]
    return []


def prova(santi: dict | None = None) -> list[str]:
    ""
    santi = santi or carica_santi()
    err = []
    attesi = {
        "June 15": ("giorno_mese", "06-15"),
        "15/06/1990": ("data_nascita", "06-15"),
        "1990-03-15": ("data_nascita", "03-15"),
        "30 years old": ("eta", None),
        "celebrated during conversation": ("rumore", None),
        "October 18th (San Luca)": ("onomastico", "10-18"),
        "05-15": ("giorno_mese", "05-15"),
        "15 de noviembre, cumple 30 años": ("giorno_mese", "11-15"),
    }
    for v, (cat, md) in attesi.items():
        n = normalizza(v, "2024-01-01")
        if (n["cat"], n["mmdd"]) != (cat, md):
            err.append(f"normalizza({v!r}) = {n['cat']} {n['mmdd']}, expected {cat} {md}")

    def f(v, s="whatsapp", vf="2024-01-01", q="", a="relationship.birthday"):
        return {"a": a, "v": v, "s": s, "vf": vf, "q": q, "chiuso": False, **normalizza(v, vf)}

    def doc_finti(v):
        return [f(v, s=s, vf=vf) for s, vf in (("gdrive", "2020-01-01"), ("email", "2021-01-01"))]


    r = decidi([f("October 18"), f("18/10", vf="2023-10-18")], date_onomastico("Luca Rossi", santi))
    if r["data"] == "10-18":
        err.append("a birthday wish on 10/18 to a Luca became a birthday")

    if decidi([f("April 20"), f("20 aprile", vf="2022-04-20")], set())["data"] == "04-20":
        err.append("a date in DATE_DI_OWNER ended up on another profile")

    r = decidi([f("1990-05-05", s="personio", a="identity.date_of_birth")], set())
    if not PERSONIO_COME_FONTE and r["data"]:
        err.append("Personio created a birthday with PERSONIO_COME_FONTE off")

    r = decidi(
        [f("15/03/1990", s="gdrive", vf="2020-02-01"), f("15/03/1990", s="email", vf="2021-05-01")],
        set(),
    )
    if (r["data"], r["livello"]) != ("03-15", "sicura"):
        err.append(
            f"two documents with 15/03/1990 give {r['data']} {r['livello']}, expected 03-15 sicura"
        )

    due = {
        "person_a": {
            "nome": "Paolo Finto",
            "n_fatti": 4,
            "fatti": [{**x, "sf": ""} for x in doc_finti("15/07/1990")],
        },
        "person_b": {
            "nome": "Carla Finta",
            "n_fatti": 4,
            "fatti": [{**x, "sf": ""} for x in doc_finti("15/07/1990")],
        },
    }
    if calcola(due, {}, {"persone": []}, santi, lambda e: True)["persone"]:
        err.append("a birth date shared by two people ended up on a profile")

    if decidi([f("1979-01-01", s="gdrive"), f("01/01/1979", s="email")], set())["data"] == "01-01":
        err.append("January 1st passed as a birthday")

    if decidi([f("May 15")], set())["livello"] != "da confermare":
        err.append("a single chat fact rose above «da confermare»")

    if (
        decidi([f("15 maggio"), f("May 15", vf="2023-05-15")], set(), rifiutate={"05-15"})["data"]
        == "05-15"
    ):
        err.append("a rejected date came back written in another form")

    scheda = {
        "nome": "Mario Finto",
        "n_fatti": 3,
        "fatti": [{**f("07-10"), "sf": "", "chiuso": False}],
    }
    ver = {
        "persone": [
            {
                "entity_id": "person_finto",
                "nome": "Mario Finto",
                "compleanno": "07-11",
                "certezza": "sicura",
                "rifiutate": ["07-10"],
                "calendario": True,
            }
        ]
    }
    r = calcola({"person_finto": scheda}, {}, ver, santi, lambda e: True)
    scritti = [x["value"] for x in r["scrivere"].get("person_finto", [])]
    chiusi = [x["value"] for x in r["chiudere"].get("person_finto", [])]
    if "07-11" not in scritti or "07-10" not in chiusi:
        err.append(f"the verified one doesn't win: written {scritti}, closed {chiusi}")

    doc = [
        {**f("15/04/1990", s=s, vf=vf), "sf": "", "chiuso": False}
        for s, vf in (("gdrive", "2020-01-01"), ("email", "2021-01-01"))
    ]
    r = calcola(
        {"person_finta2": {"nome": "Teresa Finta", "n_fatti": 5, "fatti": doc}},
        {},
        {"persone": []},
        santi,
        lambda e: True,
    )
    if [p["livello"] for p in r["persone"]] != ["sicura"]:
        err.append(
            f"two documents for Teresa Finta give {[p['livello'] for p in r['persone']]}, expected one sicura person"
        )
    if any(p["calendario"] for p in r["persone"]):
        err.append("an automatic date ended up in the calendar")
    if [
        x["value"]
        for x in r["scrivere"].get("person_finta2", [])
        if x["attribute"] == ATTR_ONOMASTICO
    ] != ["10-15 (Santa Teresa d'Avila)"]:
        err.append("Teresa's automatic name-day was not proposed for the profile")

    if onomastico_del_nome("Enzo Finto", santi):
        err.append("Enzo (ambiguous) got an automatic name-day")
    if not onomastico_del_nome("Giuseppe Finto", santi):
        err.append("Giuseppe didn't get the name-day")
    return err


def controlla() -> int:
    rossi, gialli = [], []
    try:
        rossi += controlla_registrazione(RUNNER.read_text())
    except (OSError, SyntaxError) as e:
        rossi.append(f"cannot read {RUNNER.name}: {e}")
    try:
        santi = carica_santi()
        rossi += controlla_santi(santi)
        rossi += [f"broken rule: {e}" for e in prova(santi)]
    except (OSError, ValueError, KeyError) as e:
        rossi.append(f"onomastici-it.json unreadable: {e}")
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("xs_l3_birthday_calendar", CALENDARIO)
        cal_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cal_mod)
        rossi += cal_mod.prova()
    except Exception as e:  # noqa: BLE001 — a guard that doesn't latch on is red, not green
        rossi.append(f"the calendar self-test won't run: {type(e).__name__}: {e}")
    try:
        rossi += controlla_nessuna_cancellazione(CALENDARIO.read_text())
    except (OSError, SyntaxError) as e:
        rossi.append(f"cannot read {CALENDARIO.name}: {e}")

    if KNOWLEDGE_META_DIR.exists():
        try:
            rap = json.loads(RAPPORTO.read_text())
        except (OSError, ValueError):
            rap = None
        try:
            estr = json.loads(KNOWLEDGE_LAST_EXTRACTION_FILE.read_text()).get("last_extraction")
        except (OSError, ValueError):
            estr = None
        rimedio = "uv run python tools/cross-source/xs-l2-birthdays.py --apply"
        if rap is None:
            rossi.append(
                f"report {RAPPORTO.name} missing: the stage has never run. Fix: {rimedio}"
            )
        else:
            if estr and estr > (rap.get("quando") or ""):
                rossi.append(
                    f"Knowledge Extract ran ({estr[:16]}) after the last birthdays run "
                    f"({(rap.get('quando') or '')[:16]}): the stage was skipped. Fix: {rimedio}"
                )
            if rap.get("non_arrivati"):
                rossi.append(
                    f"{len(rap['non_arrivati'])} facts written and not found again on profiles: {rap['non_arrivati'][:3]}"
                )
            eta = (datetime.now(UTC) - datetime.fromisoformat(rap["quando"])).days
            if eta > GIORNI_SILENZIO:
                gialli.append(
                    f"birthdays: last run {eta} days ago (hasn't the pipeline run since?)"
                )
            if rap.get("conta", {}).get("verificate_senza_scheda"):
                gialli.append(
                    f"birthdays: {rap['conta']['verificate_senza_scheda']} verified people without a profile in the KB"
                )
        try:
            cal = json.loads(RAPPORTO_CALENDARIO.read_text())
            for k in (
                "toccati_da_owner",
                "cancellati_da_owner",
                "solo_calendario",
                "errori",
                "frenato",
            ):
                if cal.get(k):
                    gialli.append(
                        f"calendars: {k} = {cal[k] if not isinstance(cal[k], list) else len(cal[k])}"
                    )
        except (OSError, ValueError):
            gialli.append("calendars: the calendars stage has no report yet")
    for g in gialli:
        print("🟡", g)
    for r in rossi:
        print("🔴", r)
    if not rossi:
        print(
            "✅ recurrences: stages in the chain, rules and saints table in order, report more recent than the extraction"
        )
    return 1 if rossi else 0


def sabota() -> int:
    ""
    testo = RUNNER.read_text()
    falliti = []
    if not controlla_registrazione(testo.replace(f'_esegui("{STADIO}"', '_esegui_finto("x"')):
        falliti.append("stage removed from run_pipeline and the guard doesn't notice")
    if not controlla_registrazione(testo.replace(f'id="{STADIO_CALENDARIO}"', 'id="altro"')):
        falliti.append("calendar stage removed from CATENA and the guard doesn't notice")
    if not controlla_nessuna_cancellazione("svc.events().delete(calendarId=1, eventId=2)"):
        falliti.append("a delete in the calendar code gets through")
    santi = carica_santi()
    rotto = json.loads(json.dumps(santi))
    rotto["santi"]["giuseppe"]["mmdd"] = "02-30"
    if not controlla_santi(rotto):
        falliti.append("an impossible date in the saints table gets through")
    global DATE_DI_OWNER
    salvate, DATE_DI_OWNER = DATE_DI_OWNER, set()
    try:
        if not prova(santi):
            falliti.append("emptying DATE_DI_OWNER doesn't turn the self-test red")
    finally:
        DATE_DI_OWNER = salvate
    for f in falliti:
        print("🔴 sabotage not caught:", f)
    if not falliti:
        print("✅ sabotages: 5 of 5 caught")
    return 1 if falliti else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Birthdays, birth dates and name-days on KB profiles")
    ap.add_argument("--apply", action="store_true", help="write to profiles (default: dry-run)")
    ap.add_argument("--check", dest="controlla", action="store_true", help="pre-commit guard")
    ap.add_argument("--test-rules", dest="prova", action="store_true", help="rules on fake cases")
    ap.add_argument(
        "--self-test", dest="sabota", action="store_true", help="test the guard by breaking it on purpose"
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--controlla", dest="controlla", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--prova", dest="prova", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--sabota", dest="sabota", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.controlla:
        return controlla()
    if a.sabota:
        return sabota()
    if a.prova:
        err = prova()
        for e in err:
            print("🔴", e)
        print("✅ self-test passed" if not err else f"{len(err)} broken rules")
        return 1 if err else 0
    return esegui(a.apply)


if __name__ == "__main__":
    sys.exit(main())
