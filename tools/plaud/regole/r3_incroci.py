#!/usr/bin/env python3
"""Plaud rules R3 (across recordings): who speaks, from topic, people seen on nearby days, same day, city, title words and the same voice in other recordings."""

























from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.regole.nomi import OWNER_CANONICO, norm  # noqa: E402

DATA = Path(
    os.environ.get("SBK_DATA") or os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data"
).expanduser()
QUADRO = DATA / "plaud" / "quadro"
SEGNALI = QUADRO / "segnali"
CACHE = QUADRO / "cache" / "r3"
CALENDARI = DATA / "calendars"



FORZA = {
    "R3-10-tema": 0.37,
    "R3-07-rete-14g": 0.30,
    "R3-06-spezzati": 0.33,
    "R3-06-entro-3-ore": 0.27,
    "R3-15-gemella": 0.27,
    "R3-01-coppia": 0.37,
    "R3-01-gruppo": 0.29,
    "R3-18-citta-rara": 0.26,
    "R3-03-titolo-quasi-uguale": 0.33,
    "R3-V2-fuori-finestra": 0.60,
    "R3-14-quota-parlato": 0.05,
    "R3-12-stessa-voce": 0.30,
}

STOP = frozenset(
    """della delle dello degli nella nelle negli sulla sulle questo questa questi queste quello quella quelli quelle
    perche anche sono siamo hanno abbiamo avere essere fare fatto molto tutto tutti tutte cosa cose come quando dove
    allora quindi pero ancora sempre adesso oggi domani ieri prima dopo poi solo altro altra altri altre ogni proprio
    vuoi voglio vogliamo devo dobbiamo posso possiamo puoi stato stata stai stiamo sarebbe sara poco tanto
    niente nulla qualcosa qualche qualcuno parte modo tipo cioe comunque infatti magari praticamente diciamo esatto
    perfetto okay bene vabbe senti guarda capito dire detto dice dico dici fammi facciamo fanno faccio
    call meeting riunione discussione analisi gestione strategia piano progetto aggiornamento revisione definizione
    incontro sessione organizzazione sviluppo""".split()  # noqa: SIM905
)
GIORNO = 86400.0





def segnale(
    file_id: str,
    regola: str,
    *,
    slot: str | None = None,
    tipo: str = "roster",
    nome: str | None = None,
    direzione: str = "a_favore",
    famiglia: str,
    sottotipo: str,
    gruppo: str,
    prova: str,
    punteggio: float | None = None,
    rango: int | None = None,
    attributo: dict | None = None,
) -> dict:
    ""

    return {
        "file_id": file_id,
        "slot": slot,
        "tipo": tipo,
        "nome": nome,
        "solo_nome": bool(nome) and len(nome.split()) == 1,
        "attributo": attributo,
        "direzione": direzione,
        "regola": regola,
        "famiglia": famiglia,
        "sottotipo": sottotipo,
        "forza": FORZA[regola],
        "gruppo": gruppo,
        "prova": prova[:200],
        "punteggio": None if punteggio is None else round(float(punteggio), 4),
        "rango": rango,
    }


def migliori(sc: dict[str, float], k: int) -> list[tuple[str, float, int]]:
    ""
    ordine = sorted(((n, v) for n, v in sc.items() if v > 0), key=lambda x: (-x[1], x[0]))[:k]
    return [(n, v, r + 1) for r, (n, v) in enumerate(ordine)]


def quanti(reg: dict) -> int:
    return min(8, len(reg["voci"]) + 2)





class Indici:
    ""

    def __init__(self, regs: list[dict]):
        self.regs = regs
        self.p2r: dict[str, set[int]] = defaultdict(set)
        self.r2p: dict[int, set[str]] = defaultdict(set)
        for i, r in enumerate(regs):
            for v in r["voci"]:
                n = v.get("nome") or ""
                if n and n != OWNER_CANONICO:
                    self.p2r[n].add(i)
                    self.r2p[i].add(n)
        self.persone = sorted(self.p2r)
        self.ordine_tempo = sorted((r["st"], i) for i, r in enumerate(regs) if r["st"])

    def altre(self, p: str, i: int) -> set[int]:
        return self.p2r[p] - {i}

    def vicine(self, i: int, giorni: float) -> Iterable[int]:
        ""
        st = self.regs[i]["st"]
        if not st:
            return []
        import bisect

        a = bisect.bisect_left(self.ordine_tempo, (st - giorni * GIORNO, -1))
        b = bisect.bisect_right(self.ordine_tempo, (st + giorni * GIORNO, 1 << 30))
        return [k for _, k in self.ordine_tempo[a:b] if k != i and self.r2p[k]]





def parole(testo: str, nomi_token: frozenset[str]) -> list[str]:
    return [
        w for w in re.findall(r"[a-z]{4,}", norm(testo)) if w not in STOP and w not in nomi_token
    ]


def tfidf(docs: list[list[str]]) -> list[tuple[np.ndarray, np.ndarray]]:
    ""
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    tetto = max(2, int(0.3 * n))
    voc = {t: k for k, t in enumerate(sorted(t for t, c in df.items() if 2 <= c <= tetto))}
    out = []
    for d in docs:
        tf = Counter(t for t in d if t in voc)
        if not tf:
            out.append((np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)))
            continue
        idx = np.fromiter((voc[t] for t in tf), dtype=np.int64, count=len(tf))
        val = np.fromiter(
            ((1 + math.log(c)) * (math.log((1 + n) / (1 + df[t])) + 1) for t, c in tf.items()),
            dtype=np.float32,
            count=len(tf),
        )
        val /= np.linalg.norm(val) or 1.0
        out.append((idx, val))
    tfidf.dimensione = len(voc)  # type: ignore[attr-defined]
    return out


def segnali_tema(
    regs: list[dict], ix: Indici, vettori: list[tuple[np.ndarray, np.ndarray]]
) -> list[dict]:
    V = getattr(tfidf, "dimensione", 0)
    if not V or not ix.persone:
        return []
    P = np.zeros((len(ix.persone), V), dtype=np.float32)
    for k, p in enumerate(ix.persone):
        for i in ix.p2r[p]:
            idx, val = vettori[i]
            P[k, idx] += val
    n2 = (P * P).sum(axis=1)
    out = []
    for i, r in enumerate(regs):
        idx, val = vettori[i]
        if not len(idx):
            continue
        dots = P[:, idx] @ val
        sc = {}
        for k, p in enumerate(ix.persone):
            d, q = float(dots[k]), float(n2[k])
            if i in ix.p2r[p]:
                q = q - 2 * d + 1.0
                d -= 1.0
            if d > 1e-6 and q > 1e-6:
                sc[p] = d / math.sqrt(q)
        for nome, v, rk in migliori(sc, quanti(r)):
            out.append(
                segnale(
                    r["id"],
                    "R3-10-tema",
                    nome=nome,
                    famiglia="argomento vs persona",
                    sottotipo="tema delle sue altre registrazioni",
                    gruppo="tema",
                    punteggio=v,
                    rango=rk,
                    prova=f"somiglianza del trascritto {v:.2f} con le sue altre {len(ix.altre(nome, i))} registrazioni",
                )
            )
    return out





def segnali_rete(regs: list[dict], ix: Indici, giorni: float = 14) -> list[dict]:
    out = []
    for i, r in enumerate(regs):
        sc: Counter = Counter()
        for k in ix.vicine(i, giorni):
            d = abs(regs[k]["st"] - r["st"]) / GIORNO
            for y in ix.r2p[k]:
                sc[y] += 1 / (1 + d)
        tot = sum(sc.values())
        for nome, v, rk in migliori(sc, quanti(r)):
            out.append(
                segnale(
                    r["id"],
                    "R3-07-rete-14g",
                    nome=nome,
                    famiglia="rete",
                    sottotipo="visti entro 14 giorni",
                    gruppo="rete",
                    punteggio=v / tot,
                    rango=rk,
                    prova=f"ha un nome in registrazioni entro {int(giorni)} giorni (peso {v:.2f})",
                )
            )
    return out





def tipo_vicinanza(a: dict, b: dict) -> str | None:
    ""
    if not a["st"] or not b["st"] or a["data"] != b["data"]:
        return None
    a0, a1 = a["st"], a["st"] + a["dur"] * 60
    b0, b1 = b["st"], b["st"] + b["dur"] * 60
    ov = min(a1, b1) - max(a0, b0)
    if ov > 0 and ov >= 0.5 * min(a1 - a0, b1 - b0):
        return "gemella"
    gap = max(b0 - a1, a0 - b1, 0)
    if gap <= 20 * 60:
        return "spezzati"
    if gap <= 3 * 3600:
        return "3ore"
    return None


def segnali_stesso_giorno(regs: list[dict], ix: Indici) -> list[dict]:
    regola = {"gemella": "R3-15-gemella", "spezzati": "R3-06-spezzati", "3ore": "R3-06-entro-3-ore"}
    sotto = {
        "gemella": "registrazione gemella (stessa ora, altro apparecchio)",
        "spezzati": "file spezzati (entro 20 minuti)",
        "3ore": "stesso giorno entro 3 ore",
    }
    out = []
    for i, r in enumerate(regs):
        per_tipo: dict[str, Counter] = defaultdict(Counter)
        for k in ix.vicine(i, 1):
            t = tipo_vicinanza(r, regs[k])
            if t:
                for y in ix.r2p[k]:
                    per_tipo[t][y] += 1
        for t, sc in per_tipo.items():
            for nome, v, rk in migliori(sc, quanti(r)):
                out.append(
                    segnale(
                        r["id"],
                        regola[t],
                        nome=nome,
                        famiglia="stesso giorno",
                        sottotipo=sotto[t],
                        gruppo="stesso-giorno",
                        punteggio=1.0,
                        rango=rk,
                        prova=f"nome in {int(v)} registrazioni: {sotto[t]}",
                    )
                )
    return out





def segnali_copresenza(regs: list[dict], ix: Indici) -> list[dict]:
    ""

    out = []
    for i, r in enumerate(regs):
        for v in r["voci"]:
            ctx = {
                w.get("nome")
                for w in r["voci"]
                if w is not v and w.get("nome") and w.get("nome") != OWNER_CANONICO
            }
            if not ctx:
                continue
            sc: Counter = Counter()
            for x in ctx:
                rx = ix.altre(x, i)
                for k in rx:
                    for y in ix.r2p[k]:
                        if y not in ctx:
                            sc[y] += 1 / len(rx) / len(ctx)
            regola = "R3-01-coppia" if len(ctx) == 1 else "R3-01-gruppo"
            for nome, val, rk in migliori(sc, quanti(r)):
                out.append(
                    segnale(
                        r["id"],
                        regola,
                        slot=v["slot"],
                        tipo="voce",
                        nome=nome,
                        famiglia="co-presenza",
                        sottotipo="coppia (1 nome noto)"
                        if len(ctx) == 1
                        else "gruppo (2+ nomi noti)",
                        gruppo="copresenza",
                        punteggio=val,
                        rango=rk,
                        prova=f"compare di solito con {', '.join(sorted(ctx))[:120]}",
                    )
                )
    return out





def citta(luogo: str) -> str:
    ""
    n = norm(luogo)
    m = re.findall(r"\d{5}\s+([a-z' ]+?)(?:\s+[a-z]{2})?(?:,|$)", n)
    if m:
        return m[-1].strip()
    parti = [p.strip() for p in n.split(",") if p.strip() and not re.search(r"\d", p)]
    if len(parti) >= 2 and parti[-1] in ("italia", "italy"):
        return parti[-2]
    return parti[-1] if parti else ""


def luogo_fisico(loc: str) -> bool:
    ll = (loc or "").lower()
    return "," in ll and not any(
        w in ll for w in ("http", "meet", "teams", "zoom", "skype", "link", "webex", "call")
    )


def segnali_citta(
    regs: list[dict], ix: Indici, citta_giorno: dict[str, str], rara: int = 10
) -> list[dict]:
    giorni_per_citta = Counter(citta_giorno.values())
    out = []
    for i, r in enumerate(regs):
        c = citta_giorno.get(r["data"])
        if not c or giorni_per_citta[c] > rara:
            continue
        sc: Counter = Counter()
        for k in ix.vicine(i, 120):
            if citta_giorno.get(regs[k]["data"]) == c:
                for y in ix.r2p[k]:
                    sc[y] += 1
        tot = sum(sc.values())
        for nome, v, rk in migliori(sc, quanti(r)):
            out.append(
                segnale(
                    r["id"],
                    "R3-18-citta-rara",
                    nome=nome,
                    famiglia="dove era l'owner",
                    sottotipo="citta' rara",
                    gruppo="luogo",
                    punteggio=v / tot,
                    rango=rk,
                    prova=f"quel giorno eri a {c}; ha un nome in {int(v)} registrazioni dei giorni a {c}",
                )
            )
    return out





def parole_titolo(t: str, nomi_token: frozenset[str]) -> set[str]:
    t = re.sub(r"^\d\d-\d\d\s*", "", t or "")
    return {w for w in re.findall(r"[a-z]{4,}", norm(t)) if w not in STOP and w not in nomi_token}


def segnali_titolo(
    regs: list[dict], ix: Indici, nomi_token: frozenset[str], soglia: float = 0.6
) -> list[dict]:
    tit = [parole_titolo(r["titolo"], nomi_token) for r in regs]
    per_parola: dict[str, set[int]] = defaultdict(set)
    for k, t in enumerate(tit):
        if ix.r2p[k]:
            for w in t:
                per_parola[w].add(k)
    out = []
    for i, t in enumerate(tit):
        if len(t) < 2:
            continue
        sc: Counter = Counter()
        for k in set().union(*(per_parola[w] for w in t)) - {i}:
            j = len(t & tit[k]) / len(t | tit[k])
            if j >= soglia:
                for y in ix.r2p[k]:
                    sc[y] += j
        for nome, v, rk in migliori(sc, quanti(regs[i])):
            out.append(
                segnale(
                    regs[i]["id"],
                    "R3-03-titolo-quasi-uguale",
                    nome=nome,
                    famiglia="riunioni ricorrenti",
                    sottotipo="titolo quasi uguale",
                    gruppo="titolo",
                    punteggio=min(1.0, v),
                    rango=rk,
                    prova=f"titolo quasi uguale a registrazioni dove ha un nome ({' '.join(sorted(t))[:100]})",
                )
            )
    return out





def segnali_finestra(
    regs: list[dict], ix: Indici, proposti: dict[int, set[str]], margine: float = 60
) -> list[dict]:
    ""

    out = []
    for i, nomi in proposti.items():
        st = regs[i]["st"]
        if not st:
            continue
        for p in sorted(nomi):
            ds = [regs[k]["st"] for k in ix.altre(p, i) if regs[k]["st"]]
            if not ds:
                continue
            a, b = min(ds) - margine * GIORNO, max(ds) + margine * GIORNO
            if a <= st <= b:
                continue
            dist = (a - st if st < a else st - b) / GIORNO
            out.append(
                segnale(
                    regs[i]["id"],
                    "R3-V2-fuori-finestra",
                    nome=p,
                    direzione="contro",
                    famiglia="vincoli",
                    sottotipo="fuori dal periodo in cui compare",
                    gruppo="finestra",
                    punteggio=min(1.0, dist / 180),
                    prova=f"compare fra {dt.date.fromtimestamp(min(ds))} e {dt.date.fromtimestamp(max(ds))}, questa e' {int(dist)} giorni oltre il margine",
                )
            )
    return out





def segnali_quota(
    regs: list[dict], ix: Indici, proposti: dict[int, set[str]], banda: float = 0.08
) -> list[dict]:
    quote: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, r in enumerate(regs):
        tot = sum(v["min"] for v in r["voci"]) or 1.0
        for v in r["voci"]:
            if v.get("nome"):
                quote[v["nome"]].append((i, v["min"] / tot))
    out = []
    for i, nomi in proposti.items():
        r = regs[i]
        tot = sum(v["min"] for v in r["voci"]) or 1.0
        cand = sorted(nomi | {OWNER_CANONICO})
        for v in r["voci"]:
            s = v["min"] / tot
            dens = {}
            for p in cand:
                q = np.array([x for k, x in quote.get(p, []) if k != i])
                if len(q) >= 3:
                    dens[p] = float(np.mean(np.exp(-((q - s) ** 2) / (2 * banda**2))))
            m = max(dens.values(), default=0.0)
            if m <= 1e-6:
                continue
            for p, d in sorted(dens.items()):
                if d / m >= 0.25:
                    out.append(
                        segnale(
                            r["id"],
                            "R3-14-quota-parlato",
                            slot=v["slot"],
                            tipo="voce",
                            nome=p,
                            famiglia="abitudini della persona",
                            sottotipo="quota di parlato abituale",
                            gruppo="quota",
                            punteggio=d / m,
                            prova=f"voce al {100 * s:.0f}% del parlato, quota abituale per la persona",
                        )
                    )
    return out





def segnali_stessa_voce(regs: list[dict]) -> list[dict]:
    per_chiave: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in regs:
        for v in r["voci"]:
            for k in v.get("emb", [])[:1]:
                per_chiave[k].append((r["id"], v["slot"]))
    out = []
    for r in regs:
        for v in r["voci"]:
            for k in v.get("emb", [])[:1]:
                altre = [{"file_id": f, "slot": s} for f, s in per_chiave[k] if f != r["id"]][:10]
                if altre:
                    out.append(
                        segnale(
                            r["id"],
                            "R3-12-stessa-voce",
                            slot=v["slot"],
                            tipo="attributo",
                            famiglia="voce",
                            sottotipo="stessa impronta Plaud (embeddingKey)",
                            gruppo="stessa-voce",
                            attributo={"stessa_voce_di": altre},
                            prova=f"stessa impronta Plaud di {len(per_chiave[k]) - 1} altre voci",
                        )
                    )
    return out





def calcola(
    regs: list[dict],
    testi: list[str] | None = None,
    citta_giorno: dict[str, str] | None = None,
) -> list[dict]:
    ""
    ix = Indici(regs)
    nomi_token = frozenset(t for p in ix.persone for t in p.split() if len(t) >= 3)
    out: list[dict] = []
    if testi is not None:
        out += segnali_tema(regs, ix, tfidf([parole(t, nomi_token) for t in testi]))
    out += segnali_rete(regs, ix)
    out += segnali_stesso_giorno(regs, ix)
    out += segnali_copresenza(regs, ix)
    out += segnali_citta(regs, ix, citta_giorno or {})
    out += segnali_titolo(regs, ix, nomi_token)
    proposti: dict[int, set[str]] = defaultdict(set)
    id2i = {r["id"]: i for i, r in enumerate(regs)}
    for s in out:
        if s["nome"]:
            proposti[id2i[s["file_id"]]].add(s["nome"])
    out += segnali_finestra(regs, ix, proposti)
    out += segnali_quota(regs, ix, proposti)
    out += segnali_stessa_voce(regs)
    return out





def canon_map(etichette: Counter) -> dict[str, str]:
    ""

    primo: dict[str, Counter] = defaultdict(Counter)
    for k, c in etichette.items():
        if len(k.split()) >= 2:
            primo[k.split()[0]][k] += c
    out = {}
    for k in etichette:
        if len(k.split()) >= 2:
            out[k] = k
        elif primo.get(k):
            top, n = primo[k].most_common(1)[0]
            if n / sum(primo[k].values()) >= 0.8:
                out[k] = top
    return out


def conferme() -> dict[tuple[str, str], dict]:
    p = QUADRO / "conferme-owner.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[(c["file_id"], c["slot"])] = c
    return out


def carica() -> tuple[list[dict], list[str], dict[str, str]]:
    ""
    from tools.plaud.pl_quadro import mappa_id_json

    q = json.loads((QUADRO / "quadro.json").read_text())
    conf = conferme()
    et = Counter(
        norm(v["etichetta"]) for r in q["registrazioni"] for v in r["voci"] if v["classe"] == "nome"
    )
    cmap = canon_map(et)
    id2json = mappa_id_json()
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_p = CACHE / "testi.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    regs, testi, nuova = [], [], {}
    for r in q["registrazioni"]:
        p = id2json.get(r["id"])
        segs: list = []
        chiave = f"{p}:{p.stat().st_mtime_ns}" if p else ""
        emb: dict[str, Counter] = defaultdict(Counter)
        if p and cache.get(r["id"], {}).get("chiave") == chiave:
            testo = cache[r["id"]]["testo"]
            for slot, ks in cache[r["id"]]["emb"].items():
                emb[slot].update(dict.fromkeys(ks, 1))
        else:
            try:
                segs = json.loads(p.read_text()) if p else []
            except (OSError, json.JSONDecodeError):
                segs = []
            segs = [s for s in segs if isinstance(s, dict)] if isinstance(segs, list) else []
            testo = " ".join(s.get("content") or "" for s in segs)
            for s in segs:
                if s.get("embeddingKey"):
                    emb[s.get("original_speaker") or s.get("speaker") or "?"][
                        s["embeddingKey"]
                    ] += 1
        nuova[r["id"]] = {
            "chiave": chiave,
            "testo": testo,
            "emb": {k: [x for x, _ in c.most_common(3)] for k, c in emb.items()},
        }
        voci = []
        for v in r["voci"]:
            nome = ""
            if v["classe"] == "owner":
                nome = OWNER_CANONICO
            elif v["classe"] == "nome" and v["livello"] != "smentito":
                nome = cmap.get(norm(v["etichetta"]), "")
            c = conf.get((r["id"], v["voce"]))
            if c and c.get("nome"):
                nome = norm(c["nome"])
            elif c and c.get("non_e") and norm(c["non_e"]) == nome:
                nome = ""
            voci.append(
                {
                    "slot": v["voce"],
                    "nome": nome,
                    "min": float(v["minuti"]),
                    "emb": nuova[r["id"]]["emb"].get(v["voce"], []),
                }
            )
        st = dt.datetime.fromisoformat(r["inizio"]).timestamp() if r["inizio"] else 0.0
        regs.append(
            {
                "id": r["id"],
                "titolo": r["titolo"],
                "data": r["data"],
                "st": st,
                "dur": float(r["durata_min"]),
                "tipo": r["tipo"],
                "voci": voci,
            }
        )
        testi.append(testo)
    tmp = cache_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(nuova, ensure_ascii=False))
    tmp.replace(cache_p)
    return regs, testi, citta_del_giorno()


def citta_del_giorno() -> dict[str, str]:
    import duckdb

    from tools.sbk_resources import configure_duckdb

    con = duckdb.connect()
    configure_duckdb(con)
    righe = con.execute(
        "select start_datetime, location from "
        f"read_parquet('{CALENDARI}/*/events.parquet', union_by_name=true) "
        "where length(start_datetime) > 10 and coalesce(status,'') <> 'cancelled' and location is not null"
    ).fetchall()
    per: dict[str, Counter] = defaultdict(Counter)
    for s, loc in righe:
        if not luogo_fisico(loc):
            continue
        c = citta(loc)
        if c and c not in ("italia", "italy") and len(c) > 2:
            per[s[:10]][c] += 1
    return {d: c.most_common(1)[0][0] for d, c in per.items()}


def scrivi(righe: list[dict]) -> Path:
    SEGNALI.mkdir(parents=True, exist_ok=True)
    out = SEGNALI / "r3.jsonl"
    tmp = out.with_suffix(".tmp")
    with tmp.open("w") as fh:
        for r in righe:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud rules R3, across recordings"])[0]
    )
    ap.add_argument(
        "--print-only", dest="stampa", action="store_true", help="count the signals without writing"
    )
    # Older Italian name, kept as a hidden alias.
    ap.add_argument("--stampa", dest="stampa", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    regs, testi, cg = carica()
    righe = calcola(regs, testi, cg)
    conta = Counter(r["regola"] for r in righe)
    reg_con = Counter(r["regola"] for r in {(x["regola"], x["file_id"]): x for x in righe}.values())
    for k in sorted(conta):
        print(f"{k:28s} signals {conta[k]:6d}  recordings {reg_con[k]:5d}")
    if not args.stampa:
        p = scrivi(righe)
        print(f"written {p} ({len(righe)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
