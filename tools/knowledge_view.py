""













































from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))

import knowledge_ritiro as _kr  # noqa: E402
import knowledge_taxonomy as _kt  # noqa: E402

import sbk_config as cfg  # noqa: E402

KB = cfg.DATA_ROOT / "knowledge"
ENTITIES = KB / "entities"


















PREFISSI_STATO = _kt.PREFISSI_STATO
PREFISSI_EVENTO = _kt.PREFISSI_EVENTO


















PREFISSI_FINE = (
    "employment.termination_date",
    "employment.end_date",
    "employment.last_day",
    "employment.exit_date",
    "legal.contract_end",
)


def e_fatto_di_fine(attr: str) -> bool:
    ""
    a = (attr or "").lower()
    if a.startswith("relationship."):
        return False
    return a.startswith(PREFISSI_FINE) or (
        a.startswith(("employment.", "legal."))
        and any(k in a for k in ("termination_date", "end_date", "last_day", "offboard"))
    )






METADATI_RAPPORTO = (
    "employment.past_role",
    "employment.previous_role",
    "employment.hire_date",
    "employment.manager_email",
    "employment.manager_name",
    "employment.department",
    "employment.subcompany",
    "employment.employment_type",
    "employment.office",
    "employment.weekly_hours",
    "employment.probation",
    "employment.contract_type",
)










_DISPOSIZIONI_FILE = cfg.DATA_ROOT / "knowledge" / "meta" / "copertura-disposizioni.json"
_DISPOSIZIONI: dict[str, str] | None = None


def disposizioni_attributi() -> dict[str, str]:
    global _DISPOSIZIONI
    if _DISPOSIZIONI is None:
        try:
            _DISPOSIZIONI = (
                json.loads(_DISPOSIZIONI_FILE.read_text(encoding="utf-8")).get("attributo") or {}
            )
        except (OSError, ValueError):
            _DISPOSIZIONI = {}
    return _DISPOSIZIONI


def classe_attributo(attr: str) -> str:
    ""











    a = attr or ""
    presidio = _kt.classe_lessicale(a)
    if presidio:
        return presidio


    d = disposizioni_attributi().get(a)
    if d in ("stato", "evento", "identita"):
        return d
    return "altro"












_USCITA = re.compile(
    r"""(?ix)
    \b(
        terminated | ex[-\s]?employee | ex[-\s]?dipendente | offboard\w* |
        dimission\w* | dimess[oaie] | resign\w* | licenzia\w* | esoner\w* |
        (?:non\s+(?:è|e')\s+(?:più|piu')|non\s+fa\s+(?:più|piu')\s+parte|not\s+(?:any\s*more|longer)) |
        no\s+longer\s+(?:with|at|part\s+of|employed) |
        (?:ha\s+lasciat[oa]|left\s+the\s+(?:company|team|organization)) |
        former\s+(?:employee|member|cto|ceo|cfo|coo|manager|head|director|colleague) |
        (?:has\s+)?quit | laid\s+off | made\s+redundant | severance |
        fine\s+rapporto | cessazione | risoluzione\s+(?:del\s+)?contratto |
        uscit[ao]\s+(?:da|dal|dall) | fuoriuscit\w*
    )(?!\w)
    """
)









_NON_USCITA = re.compile(
    r"""(?ix)
    non\s+(?:è|e')\s+(?:più|piu')\s+(?:junior|stagista|intern|responsabile\s+di|solo|
                              disponibile|in\s+copia|necessario|urgente) |
    ha\s+lasciat[oa]\s+(?:un|il|la|i|le|dei|delle|questo|quella)\s+ |
    left\s+(?:a|the|his|her|their)\s+
        (?:message|note|comment|feedback|review|voicemail|reply|card) |
    (?:quit|left)\s+(?:the\s+)?(?:call|meeting|chat|channel|group|thread) |
    dimission\w*\s+(?:respint|ritirat|non\s+accett)
    """
)







_ULTIMO_GIORNO = re.compile(
    r"""(?ix)
    (?:last\s+day|ultimo\s+giorno)
    (?:\s+\w+){0,4}?\s+
    (?:in|at|presso|con|per)?\s*
    (?:azienda|societ|ufficio|lavoro|team|company|office|work|job)
    """
)








STATI_CHIUSI = {
    "inactive",
    "inattivo",
    "terminated",
    "terminato",
    "cessato",
    "left",
    "former",
    "offboarded",
    "resigned",
    "dimesso",
    "dimessa",
    "not active",
    "non attivo",
}


def stato_chiuso(valore: str) -> bool:
    ""
    return " ".join(str(valore or "").lower().split()) in STATI_CHIUSI


def dice_uscita(testo: str, classe: str = "stato") -> bool:
    ""





    if classe != "stato":
        return False
    t = str(testo or "")
    if not t:
        return False
    if stato_chiuso(t):
        return True
    if _NON_USCITA.search(t):
        return False
    return bool(_USCITA.search(t) or _ULTIMO_GIORNO.search(t))







def _data(v) -> date | None:
    if not v:
        return None
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def fatto_valido_oggi(fatto: dict, as_of: date | None = None) -> tuple[bool, str]:
    ""













































































    oggi = as_of or date.today()




    presente = as_of is None or as_of >= date.today()














    r = fatto.get("ritiro")
    if isinstance(r, dict) and r.get("motivo"):
        tipo = r.get("tipo") or r.get("motivo")
        verso = r.get("verso") or ""
        coda = f" → {verso}" if verso else ""
        if r.get("effetto") == _kr.DROP:



            return False, f"discarded ({r.get('motivo')}): was never true{coda}"
        quando = _data(r.get("quando"))
        if quando is None:



            return False, f"retracted WITHOUT A DATE ({tipo}): not reconstructible"
        if quando <= oggi:
            return False, f"{tipo} on {quando.isoformat()}{coda}"




    if fatto.get("superseded_by"):
        quando = _data(fatto.get("superseded_at"))
        if quando is not None:

            if quando <= oggi:
                return (
                    False,
                    f"superseded on {quando.isoformat()} by {fatto['superseded_by']}",
                )
        elif presente:

            return False, f"superseded by {fatto['superseded_by']}"

    d = _data(fatto.get("expired_at"))
    if d and d <= oggi:
        return False, f"expired on {d.isoformat()}"

    d = _data(fatto.get("valid_to"))
    if d and d <= oggi:
        return False, f"closed on {d.isoformat()}"

    d = _data(fatto.get("valid_from"))
    if d and d > oggi:
        return False, f"not valid yet (from {d.isoformat()})"




    if presente and dice_uscita(fatto.get("value"), classe_attributo(fatto.get("attribute", ""))):
        return False, "the fact text declares a departure"

    return True, "open"


def last_seen(fatto: dict) -> str:
    ""













































    date_viste = [
        str(o.get("extracted_at") or "")
        for o in (fatto.get("observations") or [])
        if isinstance(o, dict)
    ]
    date_viste.append(str((fatto.get("source") or {}).get("extracted_at") or ""))
    valide = [d for d in date_viste if d]
    return max(valide) if valide else ""










CACHE_CHIUSURE = cfg.DATA_ROOT / "cache" / "kb-closure-rates.json"





N_MINIMO = 20

_CLOSURE_CACHE: dict[str, dict] | None = None


def _wilson_inf(successi: int, n: int, z: float = 1.96) -> float:
    ""







    if n <= 0:
        return 0.0
    p = successi / n
    d = 1 + z * z / n
    centro = p + z * z / (2 * n)
    meta = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centro - meta) / d)


def _misura_chiusure(campione: int | None = None) -> dict[str, dict]:
    ""






    import random

    pdir = ENTITIES / "person"
    conta: dict[str, list] = defaultdict(lambda: [0, 0, ""])
    if not pdir.is_dir():
        return {}
    nomi = os.listdir(pdir)
    if campione:
        nomi = random.Random(11).sample(nomi, min(campione, len(nomi)))
    for n in nomi:
        try:
            e = json.loads((pdir / n).read_text())
        except Exception:  # noqa: BLE001
            continue
        for f in e.get("facts") or []:
            if not isinstance(f, dict):
                continue
            src = (f.get("source") or {}).get("source_type") or "?"
            r = conta[src]
            r[0] += 1
            if f.get("valid_to") or f.get("expired_at") or f.get("superseded_by"):
                r[1] += 1
            q = str(f.get("created_at") or f.get("valid_from") or "")[:10]
            if len(q) == 10 and q > r[2]:
                r[2] = q
    return {
        k: {
            "fatti": v[0],
            "chiusi": v[1],
            "grezzo": round(v[1] / v[0], 4) if v[0] else 0.0,
            "wilson": round(_wilson_inf(v[1], v[0]), 4),
            "ultimo_fatto": v[2] or None,
        }
        for k, v in conta.items()
    }


def _impronta_store() -> dict:
    ""
    try:
        n, mx = 0, 0.0
        for f in os.scandir(ENTITIES / "person"):
            n += 1
            m = f.stat().st_mtime
            if m > mx:
                mx = m
        return {"n_file": n, "max_mtime": round(mx, 3)}
    except OSError:
        return {}


def _carica_chiusure(rifai: bool = False) -> dict[str, dict]:
    ""









    global _CLOSURE_CACHE
    if _CLOSURE_CACHE is not None and not rifai:
        return _CLOSURE_CACHE
    impronta = _impronta_store()
    if not rifai and CACHE_CHIUSURE.exists():
        try:
            d = json.loads(CACHE_CHIUSURE.read_text())
            if d.get("_impronta") == impronta:
                _CLOSURE_CACHE = d.get("_dati") or {}
                return _CLOSURE_CACHE
        except Exception:  # noqa: BLE001
            pass
        if not os.environ.get("SB_KV_MISURA"):


            _CLOSURE_CACHE = {}
            return _CLOSURE_CACHE
    if not rifai and not os.environ.get("SB_KV_MISURA") and not CACHE_CHIUSURE.exists():
        _CLOSURE_CACHE = {}
        return _CLOSURE_CACHE


    _CLOSURE_CACHE = _misura_chiusure()
    try:
        CACHE_CHIUSURE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_CHIUSURE.write_text(
            json.dumps({"_impronta": impronta, "_dati": _CLOSURE_CACHE}, ensure_ascii=False)
        )
    except OSError:
        pass
    return _CLOSURE_CACHE


def closure_rate(canale: str | None = None) -> dict | float:
    ""






    d = _carica_chiusure()
    if canale is None:
        return {k: v["wilson"] for k, v in d.items()}
    v = d.get(canale)
    if not v or v["fatti"] < N_MINIMO:
        return 0.0
    return v["wilson"]


def canale_vivo(canale: str, giorni: int = 45) -> tuple[bool, str | None]:
    ""






    d = _carica_chiusure().get(canale) or {}
    ultimo = d.get("ultimo_fatto")
    if not ultimo:
        return False, None
    try:
        gg = (date.today() - date.fromisoformat(ultimo)).days
    except ValueError:
        return False, ultimo
    return gg <= giorni, ultimo









SOGLIA_CHIUSURA = 0.20





GIORNI_STALE = 180


@dataclass
class Verdetto:
    esito: str
    claim: str | None = None
    valore: str | None = None
    quando: str | None = None
    giorni: int | None = None
    fonte: str | None = None
    confidenza: float | None = None





    visto: str | None = None
    non_so: list[str] = field(default_factory=list)
    ripara: list[str] = field(default_factory=list)
    gruppi: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()





        if not d["non_so"]:
            d["non_so"] = [
                "no reason to doubt this fact: it is recent, "
                "on a channel that knows how to close and that is still ingesting"
            ]
        return d


def verdetto_stato(
    fatti: list[dict],
    as_of: date | None = None,
    org: str | None = None,
) -> Verdetto:
    ""










    oggi = as_of or date.today()
    stato = [
        f
        for f in fatti
        if isinstance(f, dict) and classe_attributo(f.get("attribute", "")) == "stato"
    ]
    if org:
        chiave = " ".join(str(org).lower().split())
        stato = [f for f in stato if chiave in str(f.get("value") or "").lower()]
        fatti = [
            f
            for f in fatti
            if isinstance(f, dict)
            and (
                chiave in str(f.get("value") or "").lower()
                or classe_attributo(f.get("attribute", "")) != "stato"
            )
        ]
        if not stato:
            return Verdetto(
                esito="IGNOTO",
                non_so=[
                    f"no status fact naming «{org}» on this person",
                    "it does not mean they do not work there: it means the KB does not link it",
                ],
                ripara=[f"xs-manual-knowledge-ingest.py to link the person to «{org}»"],
            )

    if not stato:
        return Verdetto(
            esito="IGNOTO",
            non_so=[
                "no status fact (employment/legal/role) on this person",
                "it does not mean they are out: it means the KB does not know",







                "for the people you actually work with this can happen often",
            ],
            ripara=["xs-manual-knowledge-ingest.py to add a membership fact"],
        )





    for f in fatti:
        if not isinstance(f, dict) or not e_fatto_di_fine(f.get("attribute", "")):
            continue




        d = _data(f.get("value"))
        if not d or d > oggi:
            continue






        rientri = [
            g
            for g in fatti
            if isinstance(g, dict)
            and classe_attributo(g.get("attribute", "")) == "stato"
            and not e_fatto_di_fine(g.get("attribute", ""))
            and (_data(g.get("valid_from")) or date.min) > d
            and fatto_valido_oggi(g, oggi)[0]
        ]
        if rientri:
            continue
        if True:
            return Verdetto(
                esito="CHIUSO",
                claim=f.get("attribute"),
                valore=str(f.get("value"))[:120],
                quando=d.isoformat(),
                giorni=(oggi - d).days,
                fonte=(f.get("source") or {}).get("source_type"),
                confidenza=f.get("confidence"),
                visto=last_seen(f)[:10] or None,
                non_so=[
                    "closed by a fact that declares an end date, "
                    "not by `valid_to` (which is never written on this store)"
                ],
                ripara=[],
            )

    chiusi = []
    aperti = []
    for f in stato:
        if e_fatto_di_fine(f.get("attribute", "")):
            continue
        ok, perche = fatto_valido_oggi(f, oggi)
        (aperti if ok else chiusi).append((f, perche))











    aperti_portanti = [
        (f, p_) for f, p_ in aperti if not f.get("attribute", "").startswith(METADATI_RAPPORTO)
    ]
    if chiusi and not aperti_portanti:
        aperti = []
















    dichiarazioni = [
        (f, p_)
        for f, p_ in chiusi
        if "declares a departure" in p_
        or stato_chiuso(f.get("value"))
        or f.get("valid_to")
        or f.get("expired_at")
        or f.get("superseded_by")
    ]
    if dichiarazioni:
        aperti = []
        chiusi = dichiarazioni + [c for c in chiusi if c not in dichiarazioni]

    if chiusi and not aperti:
        f, perche = max(chiusi, key=lambda x: str(x[0].get("valid_from") or ""))





        fine = str(f.get("valid_to") or f.get("expired_at") or "")[:10]
        if not fine:
            for g, _p in chiusi:
                d_fine = _data(g.get("value")) if e_fatto_di_fine(g.get("attribute", "")) else None
                if d_fine:
                    fine = d_fine.isoformat()
                    break
        return Verdetto(
            esito="CHIUSO",
            claim=f.get("attribute"),
            valore=str(f.get("value"))[:120],
            quando=fine or None,
            fonte=(f.get("source") or {}).get("source_type"),
            confidenza=f.get("confidence"),
            visto=last_seen(f)[:10] or None,
            non_so=[perche],
            ripara=[],
        )

    if not aperti:
        return Verdetto(esito="IGNOTO", non_so=["no readable status fact"])









    portanti = [
        (g, p_) for g, p_ in aperti if not g.get("attribute", "").startswith(METADATI_RAPPORTO)
    ] or aperti
    f, _ = max(
        portanti, key=lambda x: (str(x[0].get("valid_from") or ""), x[0].get("confidence") or 0)
    )
    src = (f.get("source") or {}).get("source_type") or "?"
    cr = closure_rate(src)
    d_from = _data(f.get("valid_from"))
    gg = (oggi - d_from).days if d_from else None

    vivo, ultimo_canale = canale_vivo(src)

    non_so: list[str] = []
    if cr < SOGLIA_CHIUSURA:
        tot = "has never closed a fact" if cr == 0 else f"closes at most {cr:.1%} of facts (lower bound)"
        non_so.append(
            f"channel «{src}»: {tot} across the whole life of the store — "
            f"here «open» does not prove «still true»"
        )
    if not vivo:
        non_so.append(
            f"channel «{src}» idle since {ultimo_canale or '?'}: no more confirmations "
            f"or refutations arrive, so silence is not news"
        )
    if gg is not None and gg > GIORNI_STALE:
        non_so.append(
            f"never reconfirmed for {gg} days; separations are ~3%/month, "
            f"so an employment open for {gg // 30} months is false in 25-35% of cases"
        )

    if gg is not None and gg > GIORNI_STALE:
        esito = "STALE"
    elif not vivo:


        esito = "APERTO-NON-VERIFICABILE"
    elif gg is None:




        esito = "APERTO-NON-VERIFICABILE"
        non_so.append("the fact has no date: we do not even know what it refers to")
    elif cr < SOGLIA_CHIUSURA:
        esito = "APERTO-NON-VERIFICABILE"
    else:
        esito = "DENTRO"

    return Verdetto(
        esito=esito,
        claim=f.get("attribute"),
        valore=str(f.get("value"))[:120],
        quando=str(f.get("valid_from") or "")[:10],
        giorni=gg,
        fonte=src,
        confidenza=f.get("confidence"),
        visto=last_seen(f)[:10] or None,
        non_so=non_so,
        ripara=["xs-manual-knowledge-ingest.py --dry-run to reconfirm or close"],
    )


def fatti_validi(fatti: list[dict], as_of: date | None = None) -> list[dict]:
    ""
    return [f for f in fatti if isinstance(f, dict) and fatto_valido_oggi(f, as_of)[0]]


def is_group_name(nome: str) -> bool:
    ""




    fn = _riconoscitore_gruppi()
    return bool(fn(nome)) if fn else False


_FN_GRUPPO: object = None


def _riconoscitore_gruppi():
    ""








    global _FN_GRUPPO
    if _FN_GRUPPO is None:
        import importlib.util

        p = PROJECT / "tools" / "cross-source" / "xs-l3-knows-query.py"
        if not p.exists():
            _FN_GRUPPO = False
        else:
            try:
                spec = importlib.util.spec_from_file_location("xs_l3_knows_query", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _FN_GRUPPO = mod._is_group_name
            except Exception:  # noqa: BLE001
                _FN_GRUPPO = False
    return _FN_GRUPPO or None


































EPISODI_NON_DI_CONTATTO = frozenset({"chatgpt", "document"})





ACCESSI_DI_CONTATTO = frozenset({"spoke", "attended"})



FILE_BENCHMARK = "historical-session-extraction-v2-new-entities"


def episodi_di_contatto(conteggi: dict) -> int:
    ""















    n = 0
    for chiave, quante in (conteggi or {}).items():
        etype, _, atype = str(chiave).partition("|")
        if etype in EPISODI_NON_DI_CONTATTO:
            continue
        if atype in ACCESSI_DI_CONTATTO:
            n += quante
    return n


CACHE_PARTECIPAZIONE = cfg.DATA_ROOT / "cache" / "kb-partecipazione.json"

_PARTECIPAZIONE: dict[str, dict] | None = None


@dataclass
class Conoscenza:
    ""






    ruoli: list[str] = field(default_factory=list)
    prove: dict[str, str] = field(default_factory=dict)
    non_so: list[str] = field(default_factory=list)
    ripara: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if not d["ruoli"]:
            d["ruoli"] = ["INCERTO"]
        return d


def _carica_partecipazione(rifai: bool = False) -> dict[str, dict]:
    ""





    global _PARTECIPAZIONE
    if _PARTECIPAZIONE is not None and not rifai:
        return _PARTECIPAZIONE

    sorgente = cfg.DATA_ROOT / "knowledge" / "epistemic" / "knows.parquet"
    if not sorgente.exists():
        _PARTECIPAZIONE = {}
        return _PARTECIPAZIONE
    firma = str(int(sorgente.stat().st_mtime))

    if not rifai and CACHE_PARTECIPAZIONE.exists():
        try:
            d = json.loads(CACHE_PARTECIPAZIONE.read_text())
            if d.get("_firma") == firma:
                _PARTECIPAZIONE = d.get("_dati") or {}
                return _PARTECIPAZIONE
        except Exception:
            pass


        if not os.environ.get("SB_KV_MISURA"):
            _PARTECIPAZIONE = {}
            return _PARTECIPAZIONE
    if not rifai and not CACHE_PARTECIPAZIONE.exists() and not os.environ.get("SB_KV_MISURA"):
        _PARTECIPAZIONE = {}
        return _PARTECIPAZIONE

    try:
        import duckdb
    except ImportError:  # pragma: no cover
        _PARTECIPAZIONE = {}
        return _PARTECIPAZIONE

    con = duckdb.connect()
    try:
        from sbk_resources import configure_duckdb

        configure_duckdb(con)
    except Exception:  # pragma: no cover
        con.execute("SET memory_limit='2GB'")

    dati: dict[str, dict] = {}
    righe = con.execute(
        f"SELECT person_id, episode_type, access_type, count(*) "  # noqa: S608
        f"FROM '{sorgente}' GROUP BY 1,2,3"
    ).fetchall()
    for pid, etype, atype, n in righe:
        dati.setdefault(pid, {})[f"{etype}|{atype}"] = int(n)
    con.close()

    try:
        CACHE_PARTECIPAZIONE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PARTECIPAZIONE.write_text(json.dumps({"_firma": firma, "_dati": dati}))
    except Exception:  # pragma: no cover
        pass
    _PARTECIPAZIONE = dati
    return _PARTECIPAZIONE


def conoscenza(entity_id: str | None, fatti: list[dict]) -> Conoscenza:
    ""




    ruoli: list[str] = []
    prove: dict[str, str] = {}
    non_so: list[str] = []
    ripara: list[str] = []


    for f in fatti or []:
        src = f.get("source") or {}
        sf = str(src.get("source_file") or "")
        val = str(f.get("value") or "")
        if FILE_BENCHMARK in sf or "archetype reference" in val.lower():
            ruoli.append("BENCHMARK")
            prove["BENCHMARK"] = (
                f"work batch on the personal brand ({sf or 'archetype reference'})"
            )
            break


    part = _carica_partecipazione()
    conteggi = part.get(entity_id or "", {})
    scambio = ricevuto = 0
    scartati = 0
    for chiave, n in conteggi.items():
        etype, _, atype = chiave.partition("|")
        if etype in EPISODI_NON_DI_CONTATTO:
            scartati += n
            continue
        if atype in ACCESSI_DI_CONTATTO:
            scambio += n
        else:
            ricevuto += n
    if scambio:
        ruoli.append("CONTATTO")
        prove["CONTATTO"] = f"{scambio} real participations (email, call, chat)"
    elif ricevuto:
        ruoli.append("RAGGIUNTO")
        prove["RAGGIUNTO"] = f"{ricevuto} times only in copy: it passes through, it is not an exchange"
    if scartati and not scambio:
        non_so.append(
            f"{scartati} «participations» came from conversations with a model or from "
            "documents: it is you talking ABOUT this person, not WITH this person"
        )


    if "CONTATTO" not in ruoli:
        for f in fatti or []:
            a = str(f.get("attribute") or "")
            if a.startswith("relationship.interaction") or a.startswith("communication."):
                etichetta = "CONTATTO" if f.get("valid_from") else "RAGGIUNTO"
                if etichetta not in ruoli:
                    ruoli.append(etichetta)
                prove[etichetta] = f"fact «{a}» = {str(f.get('value'))[:60]}"
                if not f.get("valid_from"):
                    non_so.append(
                        f"«{a}» has no date: the only proof of contact is a sentence, "
                        "and no L0 source confirms it"
                    )
                    ripara.append(
                        "xs-manual-knowledge-ingest.py to date the interaction (valid_from)"
                    )
                break


    if not any(r in ruoli for r in ("CONTATTO", "RAGGIUNTO")) and fatti:
        canali = {str((f.get("source") or {}).get("source_type") or "") for f in fatti}
        if canali & {"chatgpt", "deep_facts", "relationship_facts", "gdrive", "notion"}:
            ruoli.append("RIFERIMENTO")
            prove["RIFERIMENTO"] = "facts extracted from texts that mention them, no participation"

    if not ruoli:
        non_so.append(
            "no signal: neither participation in an episode, nor interaction facts. "
            "It does not mean they do not know them: it means the KB does not know"
        )
        ripara.append("xs-l2-knows.py to rebuild participation, if the pipeline is stopped")
    if not part:
        non_so.append(
            "participation was not loaded (cache missing or parquet changed): "
            "the roles below look only at the facts"
        )

    return Conoscenza(ruoli=ruoli, prove=prove, non_so=non_so, ripara=ripara)


__all__ = [
    "Conoscenza",
    "GIORNI_STALE",
    "SOGLIA_CHIUSURA",
    "Verdetto",
    "classe_attributo",
    "closure_rate",
    "dice_uscita",
    "stato_chiuso",
    "conoscenza",
    "e_fatto_di_fine",
    "fatti_validi",
    "fatto_valido_oggi",
    "is_group_name",
    "last_seen",
    "verdetto_stato",
]
