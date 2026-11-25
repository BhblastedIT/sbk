"""Plaud rules R2 (transcript text): who speaks, from names said aloud, greetings, introductions and people talked about in the third person."""





























from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.pl_context_emit import _NOT_NAMES  # noqa: E402
from tools.plaud.regole.nomi import (  # noqa: E402
    OWNER_CANONICO,
    OWNER_TOKENS,
    nome_intero,
    nomi_persona,
    norm,
)

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
RAW = DATA / "plaud" / "raw"
QUADRO = DATA / "plaud" / "quadro"
SEGNALI = QUADRO / "segnali" / "r2.jsonl"
CACHE = QUADRO / "cache" / "r2"
WRITE_HISTORY = DATA / "plaud" / "write_history.jsonl"
VERSIONE = "r2-v1"








REGOLE = {
    "R2-01": ("vocativo", 0.50, "vocativo"),
    "R2-02": ("vocativo", 0.50, "vocativo"),
    "R2-06": ("vocativo", 0.45, "vocativo"),


    "R2-09": ("vocativo all'owner", 0.35, "owner_testo"),


    "R2-11": ("presentazione", 0.50, "presentazione"),
    "R2-15": ("presentazione", 0.75, "owner_testo"),
    "R2-17": ("esclusione", 0.70, "chi_dice_il_nome"),
    "R2-18": ("esclusione", 0.80, "chi_dice_il_nome"),
    "R2-19": ("esclusione", 0.80, "chi_dice_il_nome"),
    "R2-20": ("esclusione", 0.75, "chi_dice_il_nome"),
    "R2-21": ("esclusione", 0.85, "terza_persona_assente"),
    "R2-22": ("genere", 0.90, "genere"),
    "R2-23": ("genere", 0.70, "genere"),
    "R2-26": ("registro", 0.60, "registro"),
    "R2-27": ("ruolo", 0.50, "ruolo_owner"),
    "R2-28": ("ruolo", 0.35, "ruolo_owner"),
    "R2-32": ("lessico", 0.60, "owner_testo"),
    "R2-33": ("struttura", 0.60, "file_spezzati"),
    "R2-34": ("lingua", 0.35, "lingua"),
}
FORZA_NOMI_OWNER = 0.3
RIPORTATO = 0.5

NAME = r"([A-ZÀ-Ý][a-zà-ÿ']+)"
VOC = [
    ("saluto", None, re.compile(r"\b(?:[Cc]iao|[Bb]uongiorno|[Bb]uonasera|[Ss]alve|[Hh]ey|[Hh]i|[Hh]ello|[Ee]hi|[Bb]entornat[oa]|[Bb]envenut[oa]|[Aa]rrivederci|[Bb]uona giornata|[Bb]uona serata)\s*,?\s+" + NAME + r"\b")),
    ("grazie", None, re.compile(r"\b(?:[Gg]razie|[Tt]hank you|[Tt]hanks)(?:\s+(?:mille|tante|ancora|davvero|di tutto|infinite|a te))?\s*,?\s+" + NAME + r"\b")),
    ("verbo", "R2-01", re.compile(r"\b(?:[Ss]enti|[Dd]immi|[Ss]cusa|[Ss]cusami|[Gg]uarda|[Aa]scolta|[Aa]spetta|[Vv]ieni|[Ss]enta|[Gg]uardi|[Ss]cusi|[Mm]i dica|[Dd]ai|[Ll]isten|[Ll]ook)\s*,?\s+" + NAME + r"\b")),
    ("domanda_testa", "R2-06", re.compile(r"^\s*" + NAME + r"\s*,[^?]*\?")),
    ("domanda_coda", None, re.compile(r",\s*" + NAME + r"\s*\?")),
    ("coda", None, re.compile(r",\s*" + NAME + r"\s*[.!]?\s*$")),
    ("testa", "R2-02", re.compile(r"^\s*" + NAME + r"\s*[,!]")),
]
PRES = [
    ("pronto_sono", "R2-11", re.compile(r"\b(?:[Pp]ronto|[Cc]iao|[Ss]alve|[Bb]uongiorno|[Bb]uonasera)\s*[,.]?\s*(?:sono|so'|son)\s+" + NAME + r"\b")),
    ("sono", None, re.compile(r"\b(?:[Ii]o sono|[Ss]ono)\s+" + NAME + r"\b")),
]
TERZA = [
    ("da_contattare", "R2-19", re.compile(r"\b(?:devo|dobbiamo|deve|devi|bisogna|dovrei|dovremmo)\s+(?:ri)?(?:chiamare|sentire|scrivere a|parlare con|dire a|chiedere a|mandare a|girare a|scrivere|contattare)\s+" + NAME + r"\b")),
    ("da_contattare", "R2-19", re.compile(r"\b(?:chiamo|sento|richiamo|scrivo a|lo dico a|glielo dico a|chiedo a|giro a|mando a|lo chiedo a|contatto)\s+" + NAME + r"\b")),
    ("riferito", "R2-18", re.compile(r"\b" + NAME + r"\s+(?:mi ha detto|mi ha scritto|mi ha chiamato|mi ha mandato|mi diceva|ha detto|dice che|diceva|mi dice|aveva detto|mi ha chiesto|mi ha fatto|mi ha girato)\b")),
    ("riferito", "R2-18", re.compile(r"\b(?:ho parlato con|ho sentito|ho chiamato|ho chiesto a|ho visto|parlavo con|ho scritto a|secondo|tramite|da parte di|ho incontrato|sono stato da|sono stata da|ero con)\s+" + NAME + r"\b")),
    ("pronome", "R2-18", re.compile(r"\b" + NAME + r"\s*,?\s+(?:lui|lei)\s+(?:è|ha|fa|dice|vuole|sta|era|aveva)\b")),
]
# Your first name and nicknames (sbk.config.json owner / own_names); never matches when unset.
_OWN = (
    "(?i:" + "|".join(re.escape(t) for t in sorted(OWNER_TOKENS, key=len, reverse=True)) + ")"
    if OWNER_TOKENS
    else r"(?!x)x"
)
OWNER_SELF = re.compile(
    r"\b(?:[Ii]o sono|[Ss]ono|[Mm]i chiamo|[Ii]o|I'm|[Tt]his is|[Pp]iacere)\s*,?\s*" + _OWN + r"\b"
)
OWNER_VOC = re.compile(r"(?:^\s*" + _OWN + r"\s*[,!?]|,\s*" + _OWN + r"\s*[,.!?]|\b(?:[Cc]iao|[Gg]razie|[Ss]enti|[Dd]immi|[Ss]cusa|[Gg]uarda|[Bb]uongiorno|[Bb]uonasera|[Ss]alve|[Ss]cusi|[Ss]enta)\s*,?\s+" + _OWN + r"\b)")
RIP = re.compile(r"\b(?:gli ho detto|le ho detto|ho detto|mi ha detto|mi fa|gli faccio|dice|diceva|dicendo|mi dice|ha detto|ha scritto|mi scrive|mi ha scritto|fa:)\b|[\"«“:]", re.I)

STEMI = [
    "content",
    "stanc",
    "sicur",
    "pront",
    "convint",
    "arrivat",
    "andat",
    "partit",
    "stat",
    "nat",
    "tornat",
    "rimast",
    "uscit",
    "venut",
    "preoccupat",
    "stuf",
    "abituat",
    "innamorat",
    "incazzat",
    "dispiaciut",
    "sposat",
    "fidanzat",
    "impegnat",
    "bloccat",
    "occupat",
    "curios",
    "sorpres",
    "emozionat",
    "ammalat",
    "malat",
    "stressat",
    "distrutt",
    "sedut",
    "costrett",
    "obbligat",
    "entrat",
    "salit",
    "trovat",
    "sentit",
    "accort",
    "informat",
    "iscritt",
    "fermat",
    "dimenticat",
    "separat",
    "divorziat",
    "laureat",
    "diplomat",
    "nervos",
    "agitat",
    "tranquill",
    "onest",
    "sincer",
    "rilassat",
    "spaventat",
    "incuriosit",
    "convocat",
    "esaurit",
    "ubriac",
    "contrari",
    "attent",
    "capit",
    "gelos",
]
_ADV = r"(?:(?:molto|così|un po'|proprio|troppo|super|tanto|già|anche|sempre|mai|più|ancora|appena|veramente|davvero|abbastanza|stat[oa])\s+)?"
_STEM = "(" + "|".join(sorted(set(STEMI), key=len, reverse=True)) + ")"
G_SE = re.compile(r"\b(?:[Ii]o\s+)?(?:[Ss]ono|[Ee]ro|[Ss]arei|[Ss]on|[Mm]i sono|[Mm]i ero)\s+" + _ADV + _STEM + r"([oa])\b")
G_INCINTA = re.compile(r"\b(?:sono|ero) incinta\b", re.I)

FORMALE = [re.compile(p) for p in (
    r"\b[Mm]i dica\b", r"\b[Ss]i figuri\b", r"\b[Ss]i accomodi\b", r"\b[Ss]cusi\b", r"\b[Gg]uardi\b", r"^\s*[Ss]enta\b",
    r"\b[Cc]ome sta\s*\?", r"\b[Ll]a ringrazio\b", r"\b[Ll]ei (?:ha|è|sa|può|vuole|deve|pensa|mi|non|ci)\b",
    r"\b[Ll]e (?:dico|chiedo|mando|mostro|spiego|faccio|posso|devo|giro)\b", r"\b[Mm]i permetta\b",
    r"\b[Aa]bbia pazienza\b", r"\b[Mm]i scusi\b", r"\b[Vv]enga\b", r"\b[Ss]ignor[ae]?\b", r"\b[Dd]ottor(?:e|essa)?\b",
)]
INFORMALE = [re.compile(p) for p in (
    r"\b[Dd]immi\b", r"\b[Ss]enti\b", r"\b[Ss]cusa\b", r"\b[Cc]ome stai\b",
    r"\b[Tt]i (?:dico|chiedo|mando|faccio|spiego|posso|devo|giro)\b", r"\b[Tt]u (?:sei|hai|sai|puoi|vuoi|devi|pensi|non)\b",
    r"\b[Hh]ai (?:visto|capito|fatto|sentito|ragione)\b", r"\b[Ff]igurati\b", r"\b[Ss]tai tranquill[oa]\b", r"\b[Vv]ieni\b",
)]
EN_SW = frozenset(
    [
        "the",
        "and",
        "is",
        "are",
        "you",
        "we",
        "they",
        "this",
        "that",
        "what",
        "with",
        "have",
        "has",
        "was",
        "were",
        "will",
        "would",
        "can",
        "could",
        "should",
        "there",
        "here",
        "it's",
        "i'm",
        "don't",
        "of",
        "to",
        "in",
        "for",
        "on",
    ]
)
IT_SW = frozenset(
    [
        "il",
        "lo",
        "la",
        "gli",
        "le",
        "che",
        "non",
        "è",
        "sono",
        "per",
        "con",
        "una",
        "un",
        "del",
        "della",
        "di",
        "da",
        "questo",
        "quello",
        "perché",
        "però",
        "anche",
        "come",
        "cosa",
        "allora",
        "quindi",
        "abbiamo",
        "hanno",
        "sei",
        "ho",
    ]
)

# Owner voice phrases, loaded from user config (owner_phrases).
# A couple of neutral examples; the real list is personal and stays out of the repo.
FRASI_OWNER = ()
GENERICO = re.compile(r"^speaker\s*\d+$", re.I)
NON_NOMI_ETICHETTA = {
    "r",
    "rumore",
    "varie",
    "demo",
    "speaker",
    "unknown",
    "sconosciuto",
}
# Your name and aliases (sbk.config.json owner / own_names).
OWNER_ETICHETTE = set(OWNER_TOKENS) | ({OWNER_CANONICO} if OWNER_CANONICO else set())





def segmenti(segs: list) -> list[dict]:
    out = []
    for s in segs or []:
        if not isinstance(s, dict):
            continue
        try:
            a = int(s.get("start_time") or 0)
            b = int(s.get("end_time") or a)
        except (TypeError, ValueError):
            a = b = 0
        out.append(
            {
                "slot": s.get("original_speaker") or s.get("speaker") or "?",
                "label": s.get("speaker") or "",
                "t": (s.get("content") or "").strip(),
                "a": a,
                "b": b,
            }
        )
    return out


def _vicino(S: list[dict], i: int, verso: int, finestra: int = 5) -> str:
    slot = S[i]["slot"]
    j, passi = i + verso, 0
    while 0 <= j < len(S) and passi < finestra:
        if S[j]["slot"] != slot:
            return S[j]["slot"]
        j += verso
        passi += 1
    return ""


def _prova(t: str, pos: int, extra: str = "") -> str:
    a = max(0, pos - 60)
    s = ("…" if a else "") + t[a : a + 160]
    return ((extra + " · ") if extra else "") + s[: 200 - (len(extra) + 3 if extra else 0)]


def _riportato(t: str, pos: int) -> bool:
    return bool(RIP.search(t[:pos]))


def _sig(
    fid, slot, tipo, regola, sottotipo, direzione, prova, nome=None, attributo=None, forza=None
):
    fam, f0, gruppo = REGOLE[regola]
    n = norm(nome) if nome else None
    return {
        "file_id": fid,
        "slot": slot,
        "tipo": tipo,
        "nome": n,
        "solo_nome": bool(n) and len(n.split()) == 1,
        "attributo": attributo,
        "direzione": direzione,
        "regola": regola,
        "famiglia": fam,
        "sottotipo": sottotipo,
        "forza": round(f0 if forza is None else forza, 3),
        "gruppo": gruppo,
        "prova": (prova or "")[:200],
    }


def _nome_ok(tok: str, pool: frozenset[str]) -> str:
    n = norm(tok).strip("'")
    return n if n in pool and n not in _NOT_NAMES else ""


def segnali_registrazione(fid: str, segs: list, pool: frozenset[str]) -> list[dict]:
    ""
    S = segmenti(segs)
    if not S:
        return []
    fine = max(s["b"] for s in S)
    out: list[dict] = []
    pv: dict[str, Counter] = defaultdict(Counter)

    def forza_mod(regola: str, rip: bool) -> tuple[float, str]:
        f = REGOLE[regola][1]
        return (f * RIPORTATO, "+riportato") if rip else (f, "")

    def dim(n: str) -> tuple[str, str]:
        pieno = nome_intero(n)
        return (pieno, f"«{n}» = {pieno}") if pieno != n else (n, "")

    for i, s in enumerate(S):
        t, slot = s["t"], s["slot"]
        c = pv[slot]
        c["seg"] += 1
        c["ms"] += max(0, s["b"] - s["a"])
        c["q"] += t.count("?")
        N, P = _vicino(S, i, 1), _vicino(S, i, -1)
        pos_reg = (
            "apertura"
            if (s["a"] < 180000 or i < 6)
            else ("chiusura" if s["a"] > fine - 180000 else "meta")
        )
        visti: set[str] = set()
        owner_voc_fatto = False


        for sub, rid, pat in VOC:
            for m in pat.finditer(t):
                n = _nome_ok(m.group(1), pool)
                if not n or n in visti:
                    continue
                visti.add(n)

                if re.search(
                    r"\b(?:sono|mi chiamo|io sono)\s+" + re.escape(m.group(1)) + r"\b", t, re.I
                ):
                    continue
                rip = _riportato(t, m.start())
                if n in OWNER_TOKENS:
                    chiude = sub == "saluto" and pos_reg == "chiusura"
                    bers, dove = (P, "voce prima") if chiude else (N, "voce dopo")
                    if not OWNER_SELF.search(t) and not owner_voc_fatto and bers:
                        f, suf = forza_mod("R2-09", rip)
                        out.append(_sig(fid, bers, "attributo", "R2-09", f"vocativo all'owner {sub}, {dove}{suf}", "a_favore",
                                        _prova(t, m.start()), attributo={"e_owner": True}, forza=f))
                        owner_voc_fatto = True

                    if not OWNER_SELF.search(t):
                        out.append(_sig(fid, slot, "attributo", "R2-17", "vocativo, nome dell'owner", "esclude",
                                        _prova(t, m.start()), attributo={"non_owner": True}, forza=FORZA_NOMI_OWNER))
                    continue
                pieno, nota = dim(n)
                if rid is not None:
                    regola, bers, st = rid, N, f"{sub}, voce dopo"
                    if bers:
                        f, suf = forza_mod(regola, rip)
                        out.append(_sig(fid, bers, "voce", regola, st + suf, "a_favore", _prova(t, m.start(), nota),
                                        nome=pieno, forza=f))
                f, suf = forza_mod("R2-17", rip)
                out.append(_sig(fid, slot, "voce", "R2-17", f"vocativo {sub}{suf}", "esclude", _prova(t, m.start(), nota),
                                nome=pieno, forza=f))
        if not owner_voc_fatto and N:
            m = OWNER_VOC.search(t)
            if m and not OWNER_SELF.search(t):
                rip = _riportato(t, m.start())
                f, suf = forza_mod("R2-09", rip)
                out.append(_sig(fid, N, "attributo", "R2-09", f"vocativo all'owner, voce dopo{suf}", "a_favore",
                                _prova(t, m.start()), attributo={"e_owner": True}, forza=f))
                out.append(_sig(fid, slot, "attributo", "R2-17", "vocativo, nome dell'owner", "esclude",
                                _prova(t, m.start()), attributo={"non_owner": True}, forza=FORZA_NOMI_OWNER))

        m = OWNER_SELF.search(t)
        if m:
            f, suf = forza_mod("R2-15", _riportato(t, m.start()))
            out.append(_sig(fid, slot, "attributo", "R2-15", "sono l'owner" + suf, "a_favore", _prova(t, m.start()),
                            attributo={"e_owner": True}, forza=f))
        visti_p: set[str] = set()
        for sub, rid, pat in PRES:
            for m in pat.finditer(t):
                n = _nome_ok(m.group(1), pool)
                if not n or n in visti_p or n in OWNER_TOKENS:
                    continue
                visti_p.add(n)
                if rid is None:
                    continue
                pieno, nota = dim(n)
                f, suf = forza_mod(rid, _riportato(t, m.start()))
                out.append(_sig(fid, slot, "voce", rid, sub + suf, "a_favore", _prova(t, m.start(), nota), nome=pieno,
                                forza=f))

        visti_t: set[str] = set()
        for sub, rid, pat in TERZA:
            for m in pat.finditer(t):
                n = _nome_ok(m.group(1), pool)
                if not n or n in OWNER_TOKENS or n in visti_t or n in visti or n in visti_p:
                    continue
                visti_t.add(n)
                pieno, nota = dim(n)
                rip = _riportato(t, m.start())
                f, suf = forza_mod(rid, rip)
                out.append(_sig(fid, slot, "voce", rid, sub + suf, "esclude", _prova(t, m.start(), nota), nome=pieno,
                                forza=f))
                if sub in ("riferito", "da_contattare"):
                    f, suf = forza_mod("R2-21", rip)
                    out.append(_sig(fid, None, "roster", "R2-21", sub + suf, "esclude", _prova(t, m.start(), nota),
                                    nome=pieno, forza=f))

        for m in re.finditer(r"\b" + NAME, t):
            n = _nome_ok(m.group(1), pool)
            if not n or n in OWNER_TOKENS or n in visti or n in visti_p or n in visti_t:
                continue
            prima = t[: m.start()].rstrip()
            if not prima or prima[-1] in ".!?":
                continue
            visti_t.add(n)
            pieno, nota = dim(n)
            f, suf = forza_mod("R2-20", _riportato(t, m.start()))
            out.append(_sig(fid, slot, "voce", "R2-20", "menzione" + suf, "esclude", _prova(t, m.start(), nota),
                            nome=pieno, forza=f))

        for m in G_SE.finditer(t):
            c["g_m" if m.group(2) == "o" else "g_f"] += 1
        if G_INCINTA.search(t):
            c["g_f"] += 1
        c["formale"] += sum(1 for p in FORMALE if p.search(t))
        c["informale"] += sum(1 for p in INFORMALE if p.search(t))
        w = re.findall(r"[a-zà-ÿ']+", t.lower())
        en = sum(1 for x in w if x in EN_SW)
        it = sum(1 for x in w if x in IT_SW)
        if en >= 3 and en > it:
            c["en"] += 1
        elif it >= 2:
            c["it"] += 1
        tl = t.lower()
        for ph in FRASI_OWNER:
            if ph in tl:
                c["frasi"] += 1
                c["frase_" + ph] += 1
                break


    for slot, c in pv.items():
        m, f = c.get("g_m", 0), c.get("g_f", 0)
        if max(m, f) >= 1 and m != f and not (min(m, f) and max(m, f) < 2 * min(m, f)):
            g = "m" if m > f else "f"
            rid = "R2-22" if max(m, f) >= 2 else "R2-23"
            out.append(_sig(fid, slot, "attributo", rid, f"genere di sé, {max(m, f)} frasi", "esclude",
                            f"maschile {m}, femminile {f}", attributo={"genere": g}))
        fo, inf = c.get("formale", 0), c.get("informale", 0)
        if fo >= 2 and fo > inf:
            out.append(_sig(fid, slot, "attributo", "R2-26", "dà del lei", "esclude",
                            f"formule di cortesia {fo}, informali {inf}", attributo={"non_owner": True}))
        en, it = c.get("en", 0), c.get("it", 0)
        if en + it >= 3 and en / (en + it) >= 0.6:
            out.append(_sig(fid, slot, "attributo", "R2-34", "parla inglese", "a_favore",
                            f"segmenti inglesi {en}, italiani {it}", attributo={"lingua": "en"}))
        if c.get("frasi"):
            frasi = [k[6:] for k in c if k.startswith("frase_")]
            out.append(_sig(fid, slot, "attributo", "R2-32", "frasi dell'owner", "a_favore",
                            f"{c['frasi']} volte: " + ", ".join(sorted(frasi))[:170], attributo={"e_owner": True}))
    grandi = [(s, c) for s, c in pv.items() if c["ms"] >= 60000]
    if len(grandi) >= 3:
        qs = sorted(grandi, key=lambda z: -z[1]["q"])
        if qs[0][1]["q"] > 0 and qs[0][1]["q"] > qs[1][1]["q"]:
            out.append(_sig(fid, qs[0][0], "attributo", "R2-27", f"più domande con {len(grandi)} voci", "a_favore",
                            f"{qs[0][1]['q']} domande contro {qs[1][1]['q']}", attributo={"e_owner": True}))
        ms = sorted(grandi, key=lambda z: -z[1]["ms"])
        if ms[0][1]["ms"] > ms[1][1]["ms"]:
            out.append(_sig(fid, ms[0][0], "attributo", "R2-28", f"parla di più con {len(grandi)} voci", "a_favore",
                            f"{round(ms[0][1]['ms'] / 60000, 1)} min contro {round(ms[1][1]['ms'] / 60000, 1)}",
                            attributo={"e_owner": True}))
    return accorpa(out)


def accorpa(sig: list[dict]) -> list[dict]:
    ""
    per: dict[tuple, dict] = {}
    volte: Counter = Counter()
    for s in sig:
        k = (s["slot"], s["tipo"], s["regola"], s["sottotipo"], s["nome"],
             json.dumps(s["attributo"], sort_keys=True), s["direzione"])
        volte[k] += 1
        per.setdefault(k, s)
    out = []
    for k, s in per.items():
        if volte[k] > 1:
            s = {**s, "prova": f"{volte[k]} volte · {s['prova']}"[:200]}
        out.append(s)
    return out


def etichette_nome(segs: list, nostre: dict[str, str]) -> list[str]:
    ""
    peso: dict[str, Counter] = defaultdict(Counter)
    for s in segmenti(segs):
        peso[s["slot"]][s["label"]] += max(1, s["b"] - s["a"])
    out = []
    for slot, c in peso.items():
        lab = c.most_common(1)[0][0]
        n = norm(lab)
        if (
            not n
            or GENERICO.match(n)
            or n in NON_NOMI_ETICHETTA
            or len(n) <= 1
            or n.startswith("misto")
        ):
            continue
        if n in OWNER_ETICHETTE or (OWNER_CANONICO and n.startswith(OWNER_CANONICO)):
            continue
        if nostre.get(slot) and norm(nostre[slot]) == n:
            continue
        out.append(n)
    return sorted(set(out))


def segnali_spezzati(regs: list[dict], soglia_s: int = 600) -> list[dict]:
    ""

    rs = sorted((r for r in regs if r.get("st") and r.get("dur")), key=lambda r: r["st"])
    out = []
    for a, b in zip(rs, rs[1:], strict=False):
        gap = (b["st"] - (a["st"] + a["dur"] * 1000)) / 1000
        if not -60 <= gap <= soglia_s:
            continue
        for x, y, verso in ((a, b, "prima"), (b, a, "dopo")):
            for n in x.get("nomi", []):
                out.append(_sig(y["fid"], None, "roster", "R2-33", f"registrazione {verso} a {round(gap / 60, 1)} min",
                                "a_favore", f"etichetta «{n}» nella registrazione {x['fid'][:8]}", nome=n))
    return out





def _indice() -> dict[str, dict]:
    return {x["id"]: x for x in json.loads((RAW / "_file_index.json").read_text())}


def _id2json() -> dict[str, Path]:
    out = {}
    for t in RAW.glob("*.txt"):
        try:
            head = t.open(errors="ignore").read(400)
        except OSError:
            continue
        m = re.search(r"# ID:\s*(\S+)", head)
        j = t.with_suffix(".json")
        if m and j.exists():
            out[m.group(1)] = j
    return out


def _nostre() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    if WRITE_HISTORY.exists():
        for line in WRITE_HISTORY.read_text().splitlines():
            try:
                w = json.loads(line)
            except json.JSONDecodeError:
                continue
            for slot, op in (w.get("ops") or {}).items():
                if isinstance(op, dict) and op.get("new"):
                    out[w.get("file_id", "")][slot] = op["new"]
    return out


def registrazioni_valide():
    ""
    indice, id2 = _indice(), _id2json()
    for fid, meta in indice.items():
        if meta.get("is_trash") or fid not in id2:
            continue
        if (meta.get("date") or "") < "2024" or meta.get("scene") == 1000:
            continue
        yield fid, meta, id2[fid]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud rules R2, transcript text"])[0]
    )
    ap.add_argument("--da-zero", action="store_true", help="ignore the cache")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    SEGNALI.parent.mkdir(parents=True, exist_ok=True)
    nostre = _nostre()
    regs = list(registrazioni_valide())


    info: dict[str, dict] = {}
    for fid, meta, p in regs:
        chiave_raw = f"{meta.get('version_ms')}|{int(p.stat().st_mtime)}"
        cp = CACHE / f"{fid}.json"
        c = None
        if cp.exists() and not args.da_zero:
            try:
                c = json.loads(cp.read_text())
            except json.JSONDecodeError:
                c = None
        if c and c.get("raw") == chiave_raw and c.get("versione") == VERSIONE:
            info[fid] = c
            continue
        try:
            segs = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(segs, list):
            continue
        info[fid] = {
            "versione": VERSIONE,
            "raw": chiave_raw,
            "nomi": etichette_nome(segs, nostre.get(fid, {})),
        }
    pool = nomi_persona(n for c in info.values() for n in c["nomi"])
    pool_h = hashlib.sha1(",".join(sorted(pool)).encode()).hexdigest()[:12]

    tot: Counter = Counter()
    rifatte = 0
    tmp = SEGNALI.with_suffix(".jsonl.tmp")
    with tmp.open("w") as fh:
        for fid, meta, p in regs:
            c = info.get(fid)
            if c is None:
                continue
            if c.get("pool") != pool_h or "segnali" not in c:
                segs = json.loads(p.read_text())
                c = {**c, "pool": pool_h, "segnali": segnali_registrazione(fid, segs, pool)}
                (CACHE / f"{fid}.json").write_text(json.dumps(c, ensure_ascii=False))
                rifatte += 1
            for s in c["segnali"]:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
                tot[s["regola"]] += 1
        spezz = segnali_spezzati(
            [
                {
                    "fid": fid,
                    "st": meta.get("st"),
                    "dur": meta.get("duration_sec"),
                    "nomi": info[fid]["nomi"],
                }
                for fid, meta, _ in regs
                if fid in info
            ]
        )
        for s in spezz:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            tot[s["regola"]] += 1
    tmp.replace(SEGNALI)
    print(
        f"r2: {len(info)} recordings ({rifatte} recomputed), pool {len(pool)} names, "
        f"{sum(tot.values())} signals -> {SEGNALI}"
    )
    print(" ".join(f"{k}:{v}" for k, v in sorted(tot.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
