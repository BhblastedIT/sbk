#!/usr/bin/env python3
"""Plaud speaker judgement: combine the R1-R3 rule signals, learned weights and your confirmations into one calibrated name proposal per voice (writes proposte.json)."""




































from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.pl_types import (  # noqa: E402
    Candidate,
    Evidence,
    EvidenceDirection,
    EvidenceSource,
    Lane,
    Provenance,
    SpeakerResolution,
)
from tools.plaud.regole.nomi import OWNER_CANONICO, OWNER_TOKENS, genere_nome, nome_intero, norm  # noqa: E402

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
QUADRO = DATA / "plaud" / "quadro"

# Labelled calibration window for the shipped example weights (YYYY-MM).
# Set these to your own dataset's date range via env.
CAL_START = os.environ.get("SBK_CAL_START", "2026-01")
CAL_TRAIN_END = os.environ.get("SBK_CAL_TRAIN_END", "2026-05")
CAL_TEST_START = os.environ.get("SBK_CAL_TEST_START", "2026-06")
CAL_END = os.environ.get("SBK_CAL_END", "2026-08")
SEGNALI = QUADRO / "segnali"
PESI = QUADRO / "pesi-regole.json"
PROPOSTE = QUADRO / "proposte.json"

SOGLIA_AUTO = 0.95
SOGLIA_CHIEDI = 0.50
FORTE = 1.0
PESO_CONFERMA = 10.0
PENALITA_SECONDA_VOCE = math.log(10)



COSTO_NESSUNO = -math.log(0.01)
INF = 1e6

FISSI_PARTENZA = {"etichetta_attuale": 1.0, "stessa_voce_confermata": 1.0}



ESCLUSIONI_DURE = frozenset({"R1-cal-rifiutato", "R1-cal-owner-rifiutato"})

FAMIGLIE_NON_NUOVE = frozenset({"plaud", "owner", ""})



CLASSE_GRUPPO = {
    "R1:calendario": "calendario",
    "R1:calendario-titolo": "calendario",
    "R1:email-invito": "calendario",
    "R1:email-rifiuto": "calendario",
    "R1:calendario-rifiuto": "calendario",
    "R1:wa-chiamata": "messaggi",
    "R1:wa-messaggi": "messaggi",
    "R1:wa-durante": "messaggi",
    "R1:slack": "messaggi",
    "R1:gemello": "gemello",
    "R1:titolo": "titolo",
    "R3:tema": "incroci",
    "R3:rete": "incroci",
    "R3:stesso-giorno": "incroci",
    "R3:copresenza": "incroci",
    "R3:luogo": "incroci",
    "R3:titolo": "incroci",
    "R3:finestra": "incroci",
    "R3:quota": "",
    "R3:stessa-voce": "voce",
    "fisso:etichetta_attuale": "plaud",
    "fisso:stessa_voce_confermata": "voce",
}


def classe(colonna: str) -> str:
    ""
    fronte, gruppo = colonna.split(":")[:2]
    if fronte == "R2":
        return "testo"
    return CLASSE_GRUPPO.get(f"{fronte}:{gruppo}", f"{fronte}:{gruppo}")


def fronte_di(regola: str) -> str:
    return regola.split("-")[0] if regola[:2] in ("R1", "R2", "R3") else "R?"





def carica_segnali(cartella: Path = SEGNALI) -> dict[str, dict]:
    ""
    out: dict[str, dict] = defaultdict(
        lambda: {"roster": [], "voce": defaultdict(list), "attr": defaultdict(list)}
    )
    for nome in ("r1.jsonl", "r2.jsonl", "r3.jsonl"):
        p = cartella / nome
        if not p.exists():
            continue
        with p.open() as fh:
            for line in fh:
                try:
                    s = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = out[s["file_id"]]
                if s.get("tipo") == "attributo":
                    d["attr"][s.get("slot")].append(s)
                elif s.get("slot"):
                    d["voce"][s["slot"]].append(s)
                else:
                    d["roster"].append(s)
    return out


def fronti_presenti(cartella: Path = SEGNALI) -> list[str]:
    return [n[:2].upper() for n in ("r1.jsonl", "r2.jsonl", "r3.jsonl") if (cartella / n).exists()]


def carica_conferme() -> dict[tuple[str, str], dict]:
    p = QUADRO / "conferme-owner.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            if c.get("nome_vero") and not c.get("nome"):
                c["nome"] = c[
                    "nome_vero"
                ]
            if c.get("non_so"):
                continue
            out[(c["file_id"], c["slot"])] = c
    return out


def assenti_da(conferme: dict | None, file_id: str) -> set[str]:
    ""
    return {
        norm(c["non_c_era"])
        for (f, _), c in (conferme or {}).items()
        if f == file_id and c.get("non_c_era")
    }


def canon_map(etichette: Counter) -> dict[str, str]:
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


def carica_regs() -> tuple[list[dict], dict[str, str]]:
    q = json.loads((QUADRO / "quadro.json").read_text())
    et = Counter(
        norm(v["etichetta"]) for r in q["registrazioni"] for v in r["voci"] if v["classe"] == "nome"
    )
    cmap = canon_map(et)
    regs = []
    for r in q["registrazioni"]:
        voci = []
        for v in r["voci"]:
            nome = (
                OWNER_CANONICO
                if v["classe"] == "owner"
                else cmap.get(norm(v["etichetta"]), "")
                if v["classe"] == "nome"
                else ""
            )
            voci.append(
                {
                    "slot": v["voce"],
                    "etichetta": v["etichetta"],
                    "classe": v["classe"],
                    "prov": v["provenienza"],
                    "livello": v["livello"],
                    "min": float(v["minuti"]),
                    "nome": nome,
                }
            )
        regs.append({"id": r["id"], "data": r["data"], "titolo": r["titolo"], "voci": voci})
    return regs, cmap





def colonna(s: dict) -> str:
    return f"{fronte_di(s['regola'])}:{s.get('gruppo') or s['regola']}:{s['direzione']}"


def valore(s: dict) -> float:
    f = float(s.get("forza") or 0.0)
    p = s.get("punteggio")
    return f * (float(p) if p is not None else 1.0)


def risolvi_nome(nome: str, pool: set[str], cmap: dict[str, str]) -> list[str]:
    ""

    n = norm(nome)
    if not n:
        return []
    if len(n.split()) >= 2 or n == OWNER_CANONICO:
        return [n]
    if n in OWNER_TOKENS and OWNER_CANONICO:
        return [OWNER_CANONICO]
    primo = nome_intero(n)
    m = sorted(p for p in pool if p.split()[0] in (n, primo))
    if m:
        return m
    for k in (n, primo):
        if cmap.get(k):
            return [cmap[k]]
    return []


def candidati(
    reg: dict,
    slot: str,
    sig: dict,
    cmap: dict[str, str],
    *,
    con_etichetta: bool,
    freddo: bool = False,
    conferma: dict | None = None,
    conferme: dict | None = None,
    esclusioni: str = "morbido",
) -> dict[str, dict]:
    ""


    voce = next(v for v in reg["voci"] if v["slot"] == slot)
    righe = [s for s in sig.get("roster", [])] + list(sig.get("voce", {}).get(slot, []))
    attr = list(sig.get("attr", {}).get(slot, [])) + list(sig.get("attr", {}).get(None, []))
    if freddo:
        righe = [s for s in righe if not s["regola"].startswith("R3-01")]
    pool_interi = {
        norm(s["nome"]) for s in righe if s.get("nome") and len(norm(s["nome"]).split()) >= 2
    }
    out: dict[str, dict] = {}

    def prendi(n: str) -> dict:
        return out.setdefault(n, {"col": {}, "fissi": {}})

    esclusi: set[str] = set()
    contro: list[tuple[str, dict, float]] = []
    for s in righe:
        ns = risolvi_nome(s.get("nome") or "", pool_interi, cmap)
        if s["direzione"] == "esclude":
            if esclusioni == "nessuna":
                continue
            if esclusioni == "duro" or s["regola"] in ESCLUSIONI_DURE:
                esclusi.update(ns)
            else:
                contro.extend((n, s, 1.0 / len(ns)) for n in ns)
            continue
        for n in ns:
            if s["direzione"] == "contro":
                contro.append((n, s, 1.0 / len(ns)))
                continue

            pres, val = 1.0 / len(ns), valore(s) / len(ns)
            c = prendi(n)["col"]
            k = colonna(s)
            if k not in c or val > c[k][1]:
                c[k] = (pres, val, s)
    prendi(OWNER_CANONICO)
    if con_etichetta and voce["nome"]:
        prendi(voce["nome"])["fissi"]["etichetta_attuale"] = 1.0
    genere, genere_s = "", None
    for a in attr:
        at = a.get("attributo") or {}
        if at.get("non_owner") and esclusioni != "nessuna":
            if esclusioni == "duro":
                esclusi.add(OWNER_CANONICO)
            else:
                contro.append((OWNER_CANONICO, a, 1.0))
        if at.get("e_owner"):
            c = prendi(OWNER_CANONICO)["col"]
            k = colonna(a)
            if k not in c or valore(a) > c[k][1]:
                c[k] = (1.0, valore(a), a)
        if at.get("genere") and (genere_s is None or valore(a) > valore(genere_s)):
            genere, genere_s = at["genere"], a
        for altra in at.get("stessa_voce_di") or []:

            c2 = (conferme or {}).get((altra.get("file_id"), altra.get("slot")))
            if c2 and c2.get("nome"):
                prendi(norm(c2["nome"]))["fissi"]["stessa_voce_confermata"] = 1.0
    if genere and esclusioni != "nessuna":
        altro = {n for n in out if genere_nome(n) and genere_nome(n) != genere}
        if esclusioni == "duro":
            esclusi |= altro
        else:
            contro.extend((n, genere_s, 1.0) for n in altro)
    for n, s, quota in contro:
        if n in out:
            k = colonna(s)
            c = out[n]["col"]
            if k not in c or valore(s) * quota > c[k][1]:
                c[k] = (quota, valore(s) * quota, s)
    no = {norm(conferma["non_e"])} if conferma and conferma.get("non_e") else set()
    no |= assenti_da(conferme, reg["id"])
    for x in no:
        esclusi.add(x)
        if len(x.split()) == 1:
            esclusi.update(risolvi_nome(x, set(out), {}))
    return {n: v for n, v in out.items() if n not in esclusi}


def colonne_da(cands: list[dict[str, dict]]) -> list[str]:
    cols = set()
    for cs in cands:
        for v in cs.values():
            cols |= set(v["col"])
    return sorted(cols)


def matrice(cs: dict[str, dict], cols: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    ""
    nomi = sorted(cs)
    ix = {c: k for k, c in enumerate(cols)}
    X = np.zeros((len(nomi), 2 * len(cols) + 1), dtype=np.float64)
    F = np.zeros((len(nomi), len(FISSI_PARTENZA)), dtype=np.float64)
    fk = list(FISSI_PARTENZA)
    for r, n in enumerate(nomi):
        for c, (pres, val, _) in cs[n]["col"].items():
            if c in ix:
                X[r, 2 * ix[c]] = pres
                X[r, 2 * ix[c] + 1] = val
        X[r, -1] = 1.0 if n == OWNER_CANONICO else 0.0
        for k, v in cs[n]["fissi"].items():
            F[r, fk.index(k)] = v
    return nomi, X, F





def pesi_iniziali(cols: list[str], forze: dict[str, float]) -> np.ndarray:
    w = np.zeros(2 * len(cols) + 1)
    for k, c in enumerate(cols):
        f = forze.get(c, 0.3)
        w[2 * k] = (-2.0 if c.endswith((":contro", ":esclude")) else 2.0) * f
    return w


def impara(
    esempi: list[tuple[np.ndarray, np.ndarray, int, float]],
    cols: list[str],
    forze: dict[str, float],
    fissi: dict[str, float],
    *,
    lam: float = 1.0,
    passi: int = 600,
    lr: float = 0.05,
) -> tuple[np.ndarray, float]:
    ""
    w0 = pesi_iniziali(cols, forze)
    w = w0.copy()
    b = 0.0
    fv = np.array([fissi.get(k, v) for k, v in FISSI_PARTENZA.items()])
    m_w = np.zeros_like(w)
    v_w = np.zeros_like(w)
    m_b = v_b = 0.0
    if not esempi:
        return w, b
    Xs = (
        np.vstack([e[0] for e in esempi])
        if any(len(e[0]) for e in esempi)
        else np.zeros((0, len(w)))
    )
    Fs = (
        np.vstack([e[1] for e in esempi])
        if any(len(e[1]) for e in esempi)
        else np.zeros((0, len(fv)))
    )
    off = Fs @ fv if len(Fs) else np.zeros(0)
    gruppi = np.repeat(np.arange(len(esempi)), [len(e[0]) for e in esempi])
    inizio = np.concatenate([[0], np.cumsum([len(e[0]) for e in esempi])[:-1]])
    vero_riga = np.zeros(len(Xs))
    vero_nessuno = np.zeros(len(esempi))
    pesi = np.array([e[3] for e in esempi])
    for g, e in enumerate(esempi):
        if e[2] >= 0:
            vero_riga[inizio[g] + e[2]] = 1.0
        else:
            vero_nessuno[g] = 1.0
    for t in range(1, passi + 1):
        z = Xs @ w + off
        mx = np.full(len(esempi), b)
        np.maximum.at(mx, gruppi, z)
        ez = np.exp(z - mx[gruppi])
        en = np.exp(b - mx)
        den = en.copy()
        np.add.at(den, gruppi, ez)
        p = ez / den[gruppi]
        pn = en / den
        gr = (p - vero_riga) * pesi[gruppi]
        g_w = Xs.T @ gr + 2 * lam * (w - w0)
        g_b = float(((pn - vero_nessuno) * pesi).sum())
        m_w = 0.9 * m_w + 0.1 * g_w
        v_w = 0.999 * v_w + 0.001 * g_w**2
        m_b = 0.9 * m_b + 0.1 * g_b
        v_b = 0.999 * v_b + 0.001 * g_b**2
        w -= lr * (m_w / (1 - 0.9**t)) / (np.sqrt(v_w / (1 - 0.999**t)) + 1e-8)
        b -= lr * (m_b / (1 - 0.9**t)) / (math.sqrt(v_b / (1 - 0.999**t)) + 1e-8)
    return w, b


def probabilita(
    X: np.ndarray, F: np.ndarray, w: np.ndarray, b: float, fissi: dict[str, float]
) -> tuple[np.ndarray, float]:
    fv = np.array([fissi.get(k, v) for k, v in FISSI_PARTENZA.items()])
    z = X @ w + (F @ fv if len(F) else 0.0)
    m = max(float(z.max()) if len(z) else b, b)
    ez = np.exp(z - m)
    en = math.exp(b - m)
    den = ez.sum() + en
    return ez / den, en / den





def ungherese(costo: np.ndarray) -> list[int]:
    ""
    n, m = costo.shape
    if n == 0:
        return []
    if n > m:
        raise ValueError("need at least as many columns as rows")
    u = np.zeros(n + 1)
    v = np.zeros(m + 1)
    p = np.zeros(m + 1, dtype=int)
    way = np.zeros(m + 1, dtype=int)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(m + 1, np.inf)
        usato = np.zeros(m + 1, dtype=bool)
        while True:
            usato[j0] = True
            i0 = p[j0]
            delta = np.inf
            j1 = 0
            for j in range(1, m + 1):
                if not usato[j]:
                    cur = costo[i0 - 1, j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(m + 1):
                if usato[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def corta(voce: dict, tot: float) -> bool:
    return voce["min"] < 1.0 or voce["min"] < 0.08 * tot


def assegna(
    voci: list[dict], probs: list[tuple[list[str], np.ndarray, float]], fissati: dict[int, str]
) -> list[str | None]:
    ""

    tot = sum(v["min"] for v in voci) or 1.0
    nomi = sorted({n for ns, _, _ in probs for n in ns} | set(fissati.values()))
    n = len(voci)
    cols = len(nomi) * 2 + n
    C = np.full((n, cols), INF)
    presi = set(
        fissati.values()
    )
    for r, (ns, p, pn) in enumerate(probs):
        if r in fissati:
            C[r, 2 * len(nomi) + r] = (
                0.0
            )
            continue
        pm = dict(zip(ns, p))
        for k, nome in enumerate(nomi):
            if nome in pm and pm[nome] > 0:
                c = -math.log(max(pm[nome], 1e-12))
                if nome not in presi:
                    C[r, k] = c
                if corta(voci[r], tot):
                    C[r, len(nomi) + k] = c + PENALITA_SECONDA_VOCE
        C[r, 2 * len(nomi) + r] = COSTO_NESSUNO
    scelta = ungherese(C)
    out: list[str | None] = []
    for r, j in enumerate(scelta):
        if r in fissati:
            out.append(fissati[r])
        elif C[r, j] >= INF:
            out.append(None)
        elif j < len(nomi):
            out.append(nomi[j])
        elif j < 2 * len(nomi):
            out.append(nomi[j - len(nomi)])
        else:
            out.append(None)
    return out





def spiega(
    cs: dict, nome: str, w: np.ndarray, cols: list[str], fissi: dict[str, float]
) -> tuple[list[dict], list[dict], list[str]]:
    ""
    spinte, frena, classi = [], [], set()
    ix = {c: k for k, c in enumerate(cols)}
    for c, (pres, val, s) in cs[nome]["col"].items():
        if c not in ix:
            continue
        k = ix[c]
        contr = float(w[2 * k] * pres + w[2 * k + 1] * val)
        riga = {
            "regola": s["regola"],
            "gruppo": c,
            "contributo": round(contr, 2),
            "prova": s.get("prova", "")[:200],
        }
        if contr >= 0.3:
            spinte.append(riga)
        elif contr <= -0.3:
            frena.append(riga)
        if contr >= FORTE and classe(c):
            classi.add(classe(c))
    for k, v in cs[nome]["fissi"].items():
        contr = fissi.get(k, FISSI_PARTENZA[k]) * v
        if contr >= 0.3:
            spinte.append(
                {"regola": k, "gruppo": f"fisso:{k}", "contributo": round(contr, 2), "prova": ""}
            )
        if contr >= FORTE:
            classi.add(classe(f"fisso:{k}"))
    spinte.sort(key=lambda x: -x["contributo"])
    frena.sort(key=lambda x: x["contributo"])
    return spinte, frena, sorted(classi)


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def platt(xs: list[float], ys: list[int], passi: int = 3000) -> dict:
    ""
    if len(xs) < 10 or len(set(ys)) < 2:
        return {
            "a": 1.0,
            "b": 0.0,
            "n": len(xs),
            "giuste": int(sum(ys)),
            "nota": "too few cases, identity",
        }
    z = np.array([_logit(x) for x in xs])
    y = np.array(ys, dtype=float)
    a, b = 1.0, 0.0
    for _ in range(passi):
        p = 1 / (1 + np.exp(-(a * z + b)))
        g = p - y
        a -= 0.05 * (float((g * z).mean()) + 1e-3 * (a - 1.0))
        b -= 0.05 * float(g.mean())
    return {"a": round(a, 4), "b": round(b, 4), "n": len(xs), "giuste": int(sum(ys))}


def tipo_nome(nome: str | None) -> str:
    return "owner" if nome == OWNER_CANONICO else "altri"


def tara(p: float, tipo: str, taratura: dict | None) -> float:
    t = (taratura or {}).get(tipo)
    if not t or p <= 0:
        return p
    return 1 / (1 + math.exp(-(t["a"] * _logit(p) + t["b"])))


def corsia(
    fiducia: float, classi: list[str], confermato: bool = False, nome_nuovo: bool = False
) -> str:
    ""

    if confermato:
        return Lane.AUTO.value
    valide = [c for c in classi if c not in FAMIGLIE_NON_NUOVE] if nome_nuovo else classi
    if fiducia >= SOGLIA_AUTO and len(valide) >= 2:
        return Lane.AUTO.value
    if fiducia >= SOGLIA_CHIEDI:
        return Lane.CONFIRM.value
    return Lane.CONTEXT.value





def _corsia_voce(fid, classi, confermato, nome_nuovo, scelto, conf) -> str:
    if not scelto:
        return Lane.CONTEXT.value
    lane = corsia(fid, classi, confermato, nome_nuovo)
    if conf and conf.get("voce_mista") and lane == Lane.AUTO.value:
        return Lane.CONFIRM.value
    return lane


def giudica_registrazione(
    reg: dict,
    sig: dict,
    cmap: dict[str, str],
    pesi: dict,
    conferme: dict,
    *,
    nascondi: set[str] = frozenset(),
    freddo: bool = False,
) -> list[dict]:
    ""
    cols, w, b, fissi = (
        pesi["colonne"],
        np.array(pesi["w"]),
        float(pesi["b_nessuno"]),
        pesi["fissi"],
    )
    esclusioni = pesi.get("esclusioni", "morbido")
    taratura = pesi.get("taratura")
    voci = reg["voci"]
    css, probs, fissati = [], [], {}
    for r, v in enumerate(voci):
        conf = conferme.get((reg["id"], v["slot"]))
        cs = candidati(
            reg,
            v["slot"],
            sig,
            cmap,
            con_etichetta=v["slot"] not in nascondi and not freddo,
            freddo=freddo,
            conferma=conf,
            conferme=conferme,
            esclusioni=esclusioni,
        )
        if conf and conf.get("nome") and v["slot"] not in nascondi:
            n = norm(conf["nome"])
            if (
                len(n.split()) == 1
            ):
                m = risolvi_nome(n, set(cs), cmap)
                n = m[0] if len(m) == 1 else n
            fissati[r] = n
            cs.setdefault(fissati[r], {"col": {}, "fissi": {}})
        nomi, X, F = matrice(cs, cols)
        p, pn = probabilita(X, F, w, b, fissi) if nomi else (np.zeros(0), 1.0)
        css.append(cs)
        probs.append((nomi, p, pn))
    scelte = assegna(voci, probs, fissati)
    out = []
    for r, v in enumerate(voci):
        nomi, p, pn = probs[r]
        pm = dict(zip(nomi, p.tolist()))
        ordine = sorted(pm, key=lambda n: -pm[n])
        scelto = scelte[r]
        confermato = r in fissati
        grezza = 1.0 if confermato else (pm.get(scelto, 0.0) if scelto else 0.0)
        fid = 1.0 if confermato else tara(grezza, tipo_nome(scelto), taratura)
        altri = [n for n in ordine if n != scelto]
        secondo = altri[0] if altri else None
        fid2 = tara(pm[secondo], tipo_nome(secondo), taratura) if secondo else 0.0
        nome_nuovo = not v["nome"] or v["slot"] in nascondi or freddo
        spinte, frena, classi = spiega(css[r], scelto, w, cols, fissi) if scelto else ([], [], [])
        if confermato:
            classi = sorted(set(classi) | {"owner"})
        attuale = v["nome"] or None
        out.append(
            {
                "file_id": reg["id"],
                "slot": v["slot"],
                "etichetta": v["etichetta"],
                "classe": v["classe"],
                "provenienza": v["prov"],
                "minuti": v["min"],
                "proposta": {
                    "nome": scelto,
                    "fiducia": round(fid, 3),
                    "fiducia_grezza": round(grezza, 3),
                    "nessuno": round(pn, 3),
                    "spinte": spinte[:6],
                    "contro": frena[:4],
                    "secondo": {"nome": secondo, "fiducia": round(fid2, 3)} if secondo else None,
                    "distacco": round(fid - fid2, 3),
                    "famiglie_forti": classi,
                    "candidati": len(nomi),
                    "primi": [{"nome": x, "grezza": round(pm[x], 3)} for x in ordine[:4]],
                    "cambiata_dall_assegnazione": bool(scelto and ordine and scelto != ordine[0]),
                },
                "lane": _corsia_voce(
                    fid,
                    classi,
                    confermato,
                    nome_nuovo,
                    scelto,
                    conferme.get((reg["id"], v["slot"])),
                ),
                "nome_nuovo": nome_nuovo,
                "confermato_da_owner": confermato,
                "concorda_con_etichetta": (attuale == scelto) if attuale else None,
            }
        )
    return out





def argento(regs: list[dict]) -> list[tuple[int, int]]:
    ""
    return [
        (i, j)
        for i, r in enumerate(regs)
        for j, v in enumerate(r["voci"])
        if v["prov"] == "Plaud o il proprietario"
        and v["nome"]
        and v["classe"] in ("nome", "owner")
        and CAL_START <= r["data"][:7] <= CAL_END
    ]


def stesso(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    return ta[0] == tb[0] and (len(ta) == 1 or len(tb) == 1)


def esempi_da(
    regs,
    voci_idx,
    sigs,
    cmap,
    cols=None,
    freddo=False,
    conferme=None,
    peso=1.0,
    esclusioni="morbido",
) -> tuple[list, list[dict], list[str]]:
    ""
    grezzi = []
    for i, j in voci_idx:
        r = regs[i]
        v = r["voci"][j]
        cs = candidati(
            r,
            v["slot"],
            sigs.get(r["id"], {}),
            cmap,
            con_etichetta=False,
            freddo=freddo,
            esclusioni=esclusioni,
        )
        vero = v["nome"]
        if conferme and conferme.get((r["id"], v["slot"]), {}).get("nome"):
            vero = norm(conferme[(r["id"], v["slot"])]["nome"])
        grezzi.append((cs, vero, peso))
    if cols is None:
        cols = colonne_da([g[0] for g in grezzi])
    es = []
    for cs, vero, pw in grezzi:
        nomi, X, F = matrice(cs, cols)
        t = next((k for k, n in enumerate(nomi) if stesso(n, vero)), -1)
        es.append((X, F, t, pw))
    return es, [g[0] for g in grezzi], cols


def forze_da(sigs: dict) -> dict[str, float]:
    f: dict[str, list[float]] = defaultdict(list)
    for d in sigs.values():
        for s in (
            d["roster"]
            + [x for xs in d["voce"].values() for x in xs]
            + [x for xs in d["attr"].values() for x in xs]
        ):
            f[colonna(s)].append(float(s.get("forza") or 0.0))
    return {k: max(v) for k, v in f.items()}


def impara_pesi(
    regs, sigs, cmap, conferme, *, solo_train: bool = True, esclusioni: str = "morbido"
) -> dict:
    arg = argento(regs)
    tr = [(i, j) for i, j in arg if regs[i]["data"][:7] <= CAL_TRAIN_END] if solo_train else arg
    es, _, cols = esempi_da(regs, tr, sigs, cmap, esclusioni=esclusioni)
    id2i = {r["id"]: i for i, r in enumerate(regs)}
    oro = []
    for (fid, slot), c in conferme.items():
        if c.get("nome") and fid in id2i:
            j = next((k for k, v in enumerate(regs[id2i[fid]]["voci"]) if v["slot"] == slot), None)
            if j is not None:
                oro.append((id2i[fid], j))
    if oro:
        es_oro, _, _ = esempi_da(
            regs,
            oro,
            sigs,
            cmap,
            cols=cols,
            conferme=conferme,
            peso=PESO_CONFERMA,
            esclusioni=esclusioni,
        )
        es += es_oro
    forze = forze_da(sigs)
    fissi = dict(FISSI_PARTENZA)
    w, b = impara(es, cols, forze, fissi)
    uso = Counter()
    for X, _, _, _ in es:
        for k in range(len(cols)):
            if len(X) and X[:, 2 * k].any():
                uso[cols[k]] += 1
    return {
        "colonne": cols,
        "w": [round(float(x), 5) for x in w],
        "b_nessuno": round(float(b), 5),
        "fissi": fissi,
        "esclusioni": esclusioni,
        "pesi_leggibili": {
            c: {
                "presenza": round(float(w[2 * k]), 3),
                "valore": round(float(w[2 * k + 1]), 3),
                "voci_di_addestramento": uso[c],
            }
            for k, c in enumerate(cols)
        }
        | {"e_owner": {"presenza": round(float(w[-1]), 3)}},
        "addestramento": {
            "voci_argento": len(tr),
            "periodo": f"{CAL_START}..{CAL_TRAIN_END}" if solo_train else f"{CAL_START}..{CAL_END}",
            "conferme_owner": len(oro),
            "peso_conferme": PESO_CONFERMA,
            "fronti": fronti_presenti(),
        },
    }


FASCE = [
    (0.95, 1.01, "0.95-1"),
    (0.9, 0.95, "0.90-0.95"),
    (0.7, 0.9, "0.70-0.90"),
    (0.5, 0.7, "0.50-0.70"),
    (0.0, 0.5, "below 0.50"),
]


def _test(regs) -> dict[int, list[int]]:
    per_reg: dict[int, list[int]] = defaultdict(list)
    for i, j in argento(regs):
        if regs[i]["data"][:7] >= CAL_TEST_START:
            per_reg[i].append(j)
    return per_reg


def raccogli(regs, sigs, cmap, pesi, per_reg) -> list[dict]:
    ""
    grezzi = {k: v for k, v in pesi.items() if k != "taratura"}
    out = []
    for i, js in per_reg.items():
        r = regs[i]
        sig = sigs.get(r["id"], {})
        fredde = giudica_registrazione(
            r, sig, cmap, grezzi, {}, nascondi={v["slot"] for v in r["voci"]}, freddo=True
        )
        for j in js:
            calda = giudica_registrazione(
                r, sig, cmap, grezzi, {}, nascondi={r["voci"][j]["slot"]}
            )[j]
            for caso, p in (("caldo", calda), ("freddo", fredde[j])):
                vero = r["voci"][j]["nome"]
                out.append(
                    {
                        "caso": caso,
                        "i": i,
                        "nome": p["proposta"]["nome"],
                        "tipo": tipo_nome(p["proposta"]["nome"]),
                        "tipo_vero": tipo_nome(vero),
                        "grezza": p["proposta"]["fiducia_grezza"],
                        "ok": int(stesso(p["proposta"]["nome"], vero)),
                        "classi": p["proposta"]["famiglie_forti"],
                    }
                )
    return out


def taratura_da(recs: list[dict]) -> dict:
    t = {}
    for tipo in ("owner", "altri"):
        rr = [x for x in recs if x["nome"] and x["tipo"] == tipo]
        t[tipo] = platt([x["grezza"] for x in rr], [x["ok"] for x in rr])
    return t


def taratura_incrociata(recs: list[dict]) -> None:
    ""
    for meta in (0, 1):
        t = taratura_da([x for x in recs if x["i"] % 2 != meta])
        for x in recs:
            if x["i"] % 2 == meta:
                x["tarata"] = tara(x["grezza"], x["tipo"], t) if x["nome"] else 0.0


def fasce(recs: list[dict], chiave: str) -> dict:
    out: dict = {}
    for tipo in ("owner", "altri"):
        out[tipo] = {}
        for lo, hi, nome in FASCE:
            rr = [x for x in recs if x["nome"] and x["tipo"] == tipo and lo <= x[chiave] < hi]
            out[tipo][nome] = {
                "proposte": len(rr),
                "giuste": sum(x["ok"] for x in rr),
                "pct": round(100 * sum(x["ok"] for x in rr) / len(rr)) if rr else None,
                "fiducia_media": round(100 * float(np.mean([x[chiave] for x in rr])))
                if rr
                else None,
            }
    return out


def top1(recs: list[dict]) -> dict:
    out = {}
    for caso in ("caldo", "freddo"):
        rr = [x for x in recs if x["caso"] == caso]
        out[caso] = {"tutte": [sum(x["ok"] for x in rr), len(rr)]}
        for t in ("owner", "altri"):
            q = [x for x in rr if x["tipo_vero"] == t]
            out[caso][t] = [sum(x["ok"] for x in q), len(q)]
    return out


def nomi_persi(regs, sigs, cmap, per_reg) -> dict:
    ""
    out = {"duro": Counter(), "morbido": Counter()}
    for i, js in per_reg.items():
        r = regs[i]
        for j in js:
            v = r["voci"][j]
            args = (r, v["slot"], sigs.get(r["id"], {}), cmap)
            base = candidati(*args, con_etichetta=False, freddo=True, esclusioni="nessuna")
            if not any(stesso(n, v["nome"]) for n in base):
                continue
            for modo in out:
                cs = candidati(*args, con_etichetta=False, freddo=True, esclusioni=modo)
                if not any(stesso(n, v["nome"]) for n in cs):
                    out[modo][tipo_nome(v["nome"])] += 1
    return {k: {"voci": sum(c.values()), **dict(c)} for k, c in out.items()}


def auto_nomi_nuovi(recs: list[dict], chiave: str) -> dict:
    out = {}
    for caso in ("caldo", "freddo"):
        rr = [
            x
            for x in recs
            if x["caso"] == caso
            and x["nome"]
            and x[chiave] >= SOGLIA_AUTO
            and len([c for c in x["classi"] if c not in FAMIGLIE_NON_NUOVE]) >= 2
        ]
        out[caso] = {
            "auto": len(rr),
            "giuste": sum(x["ok"] for x in rr),
            "di_cui_owner": sum(1 for x in rr if x["tipo"] == "owner"),
        }
    return out


def misura(regs, sigs, cmap, conferme) -> dict:
    ""



    per_reg = _test(regs)
    res: dict = {
        "test_registrazioni": len(per_reg),
        "test_voci": sum(len(v) for v in per_reg.values()),
        "fronti": fronti_presenti(),
    }
    pesi1 = impara_pesi(regs, sigs, cmap, {}, solo_train=True, esclusioni="duro")
    r1 = raccogli(regs, sigs, cmap, pesi1, per_reg)
    pesi2 = impara_pesi(regs, sigs, cmap, {}, solo_train=True, esclusioni="morbido")
    r2 = raccogli(regs, sigs, cmap, pesi2, per_reg)
    taratura_incrociata(r2)
    finale = taratura_da(r2)
    res["giro1"] = {
        "top1": top1(r1),
        "fasce_grezze": fasce(r1, "grezza"),
        "auto_nomi_nuovi": auto_nomi_nuovi(r1, "grezza"),
    }
    res["giro2"] = {
        "top1": top1(r2),
        "fasce_grezze": fasce(r2, "grezza"),
        "fasce_tarate_incrociate": fasce(r2, "tarata"),
        "auto_nomi_nuovi_tarata": auto_nomi_nuovi(r2, "tarata"),
        "taratura_su_tutto_il_test": finale,
    }
    res["nomi_persi_freddo"] = nomi_persi(regs, sigs, cmap, per_reg)
    pesi2["taratura"] = finale
    res["oro"] = misura_oro(regs, sigs, cmap, pesi2, conferme)
    res["pesi_giro2"] = pesi2["pesi_leggibili"]
    return res


def _indipendente(r, j, sigs, cmap, pesi, freddo):
    v = r["voci"][j]
    cs = candidati(
        r,
        v["slot"],
        sigs.get(r["id"], {}),
        cmap,
        con_etichetta=False,
        freddo=freddo,
        esclusioni=pesi.get("esclusioni", "morbido"),
    )
    nomi, X, F = matrice(cs, pesi["colonne"])
    if not nomi:
        return False
    p, pn = probabilita(X, F, np.array(pesi["w"]), pesi["b_nessuno"], pesi["fissi"])
    return stesso(nomi[int(np.argmax(p))], v["nome"])


def misura_oro(regs, sigs, cmap, pesi, conferme) -> list[dict]:
    id2i = {r["id"]: i for i, r in enumerate(regs)}
    out = []
    for (fid, slot), c in conferme.items():
        i = id2i.get(fid)
        if i is None:
            continue
        r = regs[i]
        j = next((k for k, v in enumerate(r["voci"]) if v["slot"] == slot), None)
        if j is None:
            continue
        p = giudica_registrazione(r, sigs.get(fid, {}), cmap, pesi, {}, nascondi={slot})[j]
        riga = {
            "file_id": fid[:8],
            "slot": slot,
            "proposta": p["proposta"]["nome"],
            "fiducia": p["proposta"]["fiducia"],
            "lane": p["lane"],
        }
        cs = candidati(
            r,
            slot,
            sigs.get(fid, {}),
            cmap,
            con_etichetta=False,
            esclusioni=pesi.get("esclusioni", "morbido"),
        )
        nomi, X, F = matrice(cs, pesi["colonne"])
        pr, _ = (
            probabilita(X, F, np.array(pesi["w"]), pesi["b_nessuno"], pesi["fissi"])
            if nomi
            else (np.zeros(0), 1)
        )
        ordine = [nomi[k] for k in np.argsort(-pr)] if nomi else []
        if c.get("nome"):
            riga["vero"] = norm(c["nome"])
            riga["rango"] = next(
                (k + 1 for k, n in enumerate(ordine) if stesso(n, riga["vero"])), None
            )
        else:
            riga["non_e"] = norm(c["non_e"])
            riga["proposto"] = stesso(p["proposta"]["nome"], riga["non_e"])
        out.append(riga)
    return out





def leggi_pesi() -> dict | None:
    if PESI.exists():
        try:
            return json.loads(PESI.read_text())
        except json.JSONDecodeError:
            return None
    return None


def salva_pesi(nuovi: dict, origine: str) -> dict:
    vecchi = leggi_pesi() or {}
    storia = vecchi.get("storia", [])
    versione = (vecchi.get("versione") or 0) + 1
    adesso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    storia.append(
        {
            "versione": versione,
            "quando": adesso,
            "origine": origine,
            **nuovi["addestramento"],
            "esclusioni": nuovi.get("esclusioni"),
            "taratura": nuovi.get("taratura"),
            "pesi_leggibili": nuovi["pesi_leggibili"],
        }
    )
    out = {"versione": versione, "aggiornato": adesso, **nuovi, "storia": storia}
    tmp = PESI.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    tmp.replace(PESI)
    return out


def proposte_tutte(regs, sigs, cmap, pesi, conferme) -> list[dict]:
    out = []
    for r in regs:
        for p in giudica_registrazione(r, sigs.get(r["id"], {}), cmap, pesi, conferme):
            if p["classe"] in ("generico", "non-nome") or p["provenienza"] in (
                "Plaud o il proprietario",
                "noi",
                "il proprietario",
                "-",
            ):
                out.append(p)
    return out


def scrivi_proposte(voci: list[dict], pesi: dict) -> Path:
    corsie = Counter(v["lane"] for v in voci)
    senza = [v for v in voci if v["classe"] in ("generico", "non-nome")]
    doc = {
        "generato": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "pesi_versione": pesi.get("versione"),
        "fronti": fronti_presenti(),
        "soglie": {
            "auto": SOGLIA_AUTO,
            "chiedi": SOGLIA_CHIEDI,
            "famiglie_indipendenti_per_auto": 2,
            "spinta_forte_logodds": FORTE,
        },
        "riepilogo": {
            "voci": len(voci),
            "corsie": dict(corsie),
            "senza_nome": len(senza),
            "senza_nome_con_proposta": sum(1 for v in senza if v["proposta"]["nome"]),
            "senza_nome_per_corsia": dict(
                Counter(v["lane"] for v in senza if v["proposta"]["nome"])
            ),
            "nomi_nuovi_in_auto": sum(
                1
                for v in voci
                if v["lane"] == "AUTO" and v.get("nome_nuovo") and not v["confermato_da_owner"]
            ),
            "nome_attuale_diverso_dalla_proposta": sum(
                1 for v in voci if v["concorda_con_etichetta"] is False
            ),
        },
        "voci": voci,
    }
    tmp = PROPOSTE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False))
    tmp.replace(PROPOSTE)
    return PROPOSTE




_SORGENTE = {
    "R1": EvidenceSource.CALENDAR,
    "R2": EvidenceSource.TRANSCRIPT_CONTEXT,
    "R3": EvidenceSource.GRAPH_COOCCURRENCE,
}
_PROV = {
    "noi": Provenance.MACHINE_WRITTEN,
    "il proprietario": Provenance.OWNER_REVIEWED,
    "Plaud o il proprietario": Provenance.PLAUD_NATIVE,
}


def _sorgente(regola: str, gruppo: str) -> EvidenceSource:
    if "stessa-voce" in gruppo or "stessa_voce" in regola:
        return EvidenceSource.VOICE_EMBEDDING
    if regola == "etichetta_attuale":
        return EvidenceSource.PLAUD_LABEL
    if gruppo.startswith("R1:wa") or gruppo.startswith("R1:slack"):
        return EvidenceSource.GRAPH_COOCCURRENCE
    return _SORGENTE.get(regola[:2], EvidenceSource.KNOWLEDGE_BASE)


def a_risoluzione(p: dict) -> SpeakerResolution:
    ""

    pr = p["proposta"]
    cands = []
    if pr["nome"]:
        ev = [
            Evidence(
                source=EvidenceSource.MANUAL_OVERRIDE
                if p.get("confermato_da_owner")
                else _sorgente(s["regola"], s["gruppo"]),
                claim=f"e' {pr['nome']}",
                weight=float(s["contributo"]),
                direction=EvidenceDirection.SUPPORT,
                quote=s.get("prova", ""),
                meta={"regola": s["regola"], "gruppo": s["gruppo"]},
            )
            for s in pr["spinte"]
        ] + [
            Evidence(
                source=_sorgente(s["regola"], s["gruppo"]),
                claim=f"non e' {pr['nome']}",
                weight=abs(float(s["contributo"])),
                direction=EvidenceDirection.CONTRADICT,
                quote=s.get("prova", ""),
                meta={"regola": s["regola"], "gruppo": s["gruppo"]},
            )
            for s in pr["contro"]
        ]
        cands.append(Candidate(name=pr["nome"], confidence=pr["fiducia"], evidence=ev))
    if pr.get("secondo"):
        cands.append(Candidate(name=pr["secondo"]["nome"], confidence=pr["secondo"]["fiducia"]))
    etichetta = p["etichetta"] if p["classe"] in ("nome", "owner") else None
    auto = p["lane"] == Lane.AUTO.value
    return SpeakerResolution(
        speaker_id=p["slot"],
        candidates=cands,
        posterior=pr["fiducia"],
        contradiction_score=round(max(0.0, 1.0 - pr["distacco"]) if pr["nome"] else 0.0, 3),
        plaud_label=etichetta,
        plaud_disagree=bool(
            etichetta
            and pr["nome"]
            and p["concorda_con_etichetta"] is False
            and pr["fiducia"] >= SOGLIA_CHIEDI
        ),
        lane=Lane(p["lane"]),
        provenance=_PROV.get(p["provenienza"], Provenance.UNKNOWN),
        proposed_name=pr["nome"] if auto else None,
        corroborated=auto,
    )


def risoluzioni(file_id: str, proposte: dict | None = None) -> dict[str, SpeakerResolution]:
    ""
    doc = proposte if proposte is not None else json.loads(PROPOSTE.read_text())
    return {p["slot"]: a_risoluzione(p) for p in doc["voci"] if p["file_id"] == file_id}





def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud speaker judgement"])[0]
    )
    ap.add_argument(
        "--impara",
        action="store_true",
        help="redo the weights from the labelled training window as a new version",
    )
    ap.add_argument(
        "--misura", action="store_true", help="measure warm/cold/gold and print, without writing"
    )
    args = ap.parse_args()
    regs, cmap = carica_regs()
    sigs = carica_segnali()
    conf = carica_conferme()
    if args.misura:
        print(json.dumps(misura(regs, sigs, cmap, conf), ensure_ascii=False, indent=1))
        return 0
    pesi = leggi_pesi()
    if args.impara or not pesi or pesi.get("addestramento", {}).get("fronti") != fronti_presenti():
        nuovi = impara_pesi(regs, sigs, cmap, conf)
        nuovi["taratura"] = taratura_da(raccogli(regs, sigs, cmap, nuovi, _test(regs))) | {
            "come": "Platt on the logit of the raw confidence, separated for proposals of you and of other people, on the held-out silver items "
            "of the test window, warm and cold case together"
        }
        pesi = salva_pesi(
            nuovi, "training-window silver + your confirmations; soft exclusions; calibrated confidence"
        )
        print(
            f"weights version {pesi['versione']} ({len(pesi['colonne'])} groups, fronts {pesi['addestramento']['fronti']})"
        )
    voci = proposte_tutte(regs, sigs, cmap, pesi, conf)
    p = scrivi_proposte(voci, pesi)
    doc = json.loads(p.read_text())
    print(json.dumps(doc["riepilogo"], ensure_ascii=False))
    print(f"written {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
