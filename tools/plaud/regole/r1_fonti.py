#!/usr/bin/env python3
"""Plaud rules R1 (other sources): who speaks in each recording, from calendar events, email, Slack, WhatsApp and titles that line up with it in time."""
























from __future__ import annotations

import argparse
import bisect
import datetime as dt
import hashlib
import json
import os
import pickle
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[3]
for _p in (_REPO, _REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.plaud.pl_quadro import PAROLE_COMUNI, norm  # noqa: E402
from tools.plaud.regole.nomi import OWNER_CANONICO, OWNER_TOKENS  # noqa: E402

try:
    from sbk_config import OWN_EMAILS  # noqa: E402

    _OWN = {e.lower() for e in OWN_EMAILS}
except Exception:  # pragma: no cover - config absent in isolated tests
    _OWN = set()

# You (sbk.config.json owner / own_names / own_emails): names, and the local
# parts of your addresses ("alex.demo" in alex.demo@...).
_OWNER_NOMI = set(OWNER_TOKENS) | ({OWNER_CANONICO} if OWNER_CANONICO else set())
_OWNER_LOCALI = {e.split("@")[0] for e in _OWN if "@" in e}

DATA = Path(
    os.environ.get("SBK_DATA") or os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data"
).expanduser()
QUADRO = DATA / "plaud" / "quadro"
OUT = QUADRO / "segnali" / "r1.jsonl"
CACHE = QUADRO / "cache" / "r1"
ROME = ZoneInfo("UTC")
APPLE_EPOCH = 978307200





REGOLE: dict[str, dict] = {
    "R1-gemello-unico": {
        "famiglia": "trascritto gemello",
        "sottotipo": "same words at the same moment, one name for a single voice, people only",
        "tipo": "voce",
        "direzione": "a_favore",
        "forza": 0.88,
        "caso": None,
        "gruppo": "gemello",
    },
    "R1-gemello-stanza": {
        "famiglia": "trascritto gemello",
        "sottotipo": "same twin name across multiple voices (room account)",
        "tipo": "voce",
        "direzione": "contro",
        "forza": 0.82,
        "caso": None,
        "gruppo": "gemello",
    },
    "R1-gemello-owner": {
        "famiglia": "trascritto gemello",
        "sottotipo": "the voice says the words the twin attributes to you",
        "tipo": "attributo",
        "direzione": "a_favore",
        "forza": 0.80,
        "caso": None,
        "gruppo": "gemello",
    },
    "R1-gemello-roster": {
        "famiglia": "trascritto gemello",
        "sottotipo": "speakers of the aligned twin (same words)",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.20,
        "caso": None,
        "gruppo": "gemello",
    },
    "R1-wa-a-due": {
        "famiglia": "whatsapp",
        "sottotipo": "call of similar duration + two voices, one yours",
        "tipo": "voce",
        "direzione": "a_favore",
        "forza": 0.74,
        "caso": None,
        "gruppo": "wa-chiamata",
    },
    "R1-wa-durata-simile": {
        "famiglia": "whatsapp",
        "sottotipo": "one-to-one call of similar duration (0.6-1.6x), date = start",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.56,
        "caso": 7.8,
        "gruppo": "wa-chiamata",
    },
    "R1-wa-chiamata": {
        "famiglia": "whatsapp",
        "sottotipo": "one-to-one call of at least 1 minute overlapping, date = start",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.23,
        "caso": 3.3,
        "gruppo": "wa-chiamata",
    },
    "R1-wa-gruppo": {
        "famiglia": "whatsapp",
        "sottotipo": "overlapping group call, date = start",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.19,
        "caso": None,
        "gruppo": "wa-chiamata",
    },
    "R1-wa-arrivo": {
        "famiglia": "whatsapp",
        "sottotipo": "'I've arrived / I'm downstairs / coming' from 40 min before to 15 after",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.19,
        "caso": None,
        "gruppo": "wa-messaggi",
    },
    "R1-wa-fissa": {
        "famiglia": "whatsapp",
        "sottotipo": "time (±45 min) + meeting word in the 36 h before",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.10,
        "caso": 4.4,
        "gruppo": "wa-messaggi",
    },
    "R1-wa-dopo": {
        "famiglia": "whatsapp",
        "sottotipo": "thanks or 'as said' within 6 h of the end",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.09,
        "caso": None,
        "gruppo": "wa-messaggi",
    },
    "R1-wa-attivo-prima": {
        "famiglia": "whatsapp",
        "sottotipo": "at least 2 messages in the half hour before",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.04,
        "caso": 1.8,
        "gruppo": "wa-messaggi",
    },
    "R1-wa-durante": {
        "famiglia": "whatsapp",
        "sottotipo": "at least 3 messages with the person while recording",
        "tipo": "roster",
        "direzione": "contro",
        "forza": 0.46,
        "caso": 0.5,
        "gruppo": "wa-durante",
    },
    "R1-cal-stretto": {
        "famiglia": "calendario",
        "sottotipo": "invitee, tight overlap (start within the event, half in common)",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.15,
        "caso": 1.7,
        "gruppo": "calendario",
    },
    "R1-cal-sovrapposto": {
        "famiglia": "calendario",
        "sottotipo": "invitee, real but not tight overlap",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.11,
        "caso": 2.4,
        "gruppo": "calendario",
    },
    "R1-cal-singolo": {
        "famiglia": "calendario",
        "sottotipo": "invitee of a single event (not of a series)",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.19,
        "caso": 2.4,
        "gruppo": "calendario",
    },
    "R1-cal-un-invitato": {
        "famiglia": "calendario",
        "sottotipo": "the only invitee besides you",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.11,
        "caso": 4.6,
        "gruppo": "calendario",
    },
    "R1-cal-luogo-fisico": {
        "famiglia": "calendario",
        "sottotipo": "invitee of an event with a physical location",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.17,
        "caso": 4.8,
        "gruppo": "calendario",
    },
    "R1-cal-owner-accettato": {
        "famiglia": "calendario",
        "sottotipo": "invitee of an event accepted by you or yours",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.23,
        "caso": 3.3,
        "gruppo": "calendario",
    },
    "R1-cal-a-due": {
        "famiglia": "calendario",
        "sottotipo": "one invitee + two voices, one yours",
        "tipo": "voce",
        "direzione": "a_favore",
        "forza": 0.55,
        "caso": None,
        "gruppo": "calendario",
    },
    "R1-cal-titolo": {
        "famiglia": "calendario",
        "sottotipo": "proper name in the event title",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.08,
        "caso": 6.8,
        "gruppo": "calendario-titolo",
    },
    "R1-cal-rifiutato": {
        "famiglia": "calendario",
        "sottotipo": "invitee who declined",
        "tipo": "roster",
        "direzione": "esclude",
        "forza": 0.90,
        "caso": None,
        "gruppo": "calendario-rifiuto",
    },
    "R1-cal-owner-rifiutato": {
        "famiglia": "calendario",
        "sottotipo": "you declined or maybe: your invitees are not here",
        "tipo": "roster",
        "direzione": "esclude",
        "forza": 0.30,
        "caso": None,
        "gruppo": "calendario-rifiuto",
    },
    "R1-email-invito": {
        "famiglia": "email",
        "sottotipo": "invitation with day, month and time of the recording in the subject",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.12,
        "caso": 1.7,
        "gruppo": "email-invito",
    },
    "R1-email-accettato": {
        "famiglia": "email",
        "sottotipo": "'Accepted' reply for that time",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.14,
        "caso": None,
        "gruppo": "email-invito",
    },
    "R1-email-rifiutato": {
        "famiglia": "email",
        "sottotipo": "'Declined' or canceled reply for that time",
        "tipo": "roster",
        "direzione": "contro",
        "forza": 0.68,
        "caso": None,
        "gruppo": "email-rifiuto",
    },
    "R1-slack-nomi": {
        "famiglia": "slack",
        "sottotipo": "names mentioned in the message with the time, consistent day",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.06,
        "caso": None,
        "gruppo": "slack",
    },
    "R1-slack-avvio": {
        "famiglia": "slack",
        "sottotipo": "'call/meet/I'll call you' in the 15 minutes before",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.05,
        "caso": 3.4,
        "gruppo": "slack",
    },
    "R1-slack-attivo-prima": {
        "famiglia": "slack",
        "sottotipo": "at least 2 DMs in the half hour before",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.06,
        "caso": 3.4,
        "gruppo": "slack",
    },
    "R1-titolo-mano": {
        "famiglia": "dettagli plaud",
        "sottotipo": "name in the hand-written title",
        "tipo": "roster",
        "direzione": "a_favore",
        "forza": 0.16,
        "caso": None,
        "gruppo": "titolo",
    },
    "R1-titolo-a-due": {
        "famiglia": "dettagli plaud",
        "sottotipo": "a name in the title + two voices, one yours",
        "tipo": "voce",
        "direzione": "a_favore",
        "forza": 0.19,
        "caso": None,
        "gruppo": "titolo",
    },
}

STOP = set(PAROLE_COMUNI) | {t for n in _OWNER_NOMI for t in n.split()} | {
    "speaker",
    "privato",
    "privata",
    "personale",
    "ufficio",
    "work",
    "lavoro",
    "new",
    "old",
    "numero",
    "cell",
    "mobile",
    "nuovo",
    "business",
}
WORD = re.compile(r"[a-zàèéìòù]{4,}")
MIN_RARE = 15





def toks(s) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", norm(s)) if len(t) >= 3 and t not in STOP]


def words(s) -> list[str]:
    return WORD.findall((s or "").lower())


def is_owner_email(em: str) -> bool:
    em = (em or "").lower().strip()
    local = em.split("@")[0]
    return bool(em) and (em in _OWN or local == "owner" or local in _OWNER_LOCALI)


def is_owner_name(n: str) -> bool:
    n = norm(n)
    return bool(n) and (
        n in _OWNER_NOMI or n == "me" or bool(OWNER_CANONICO and n.startswith(OWNER_CANONICO))
    )


def bad_email(em: str) -> bool:
    em = (em or "").lower()
    return (
        not em
        or "@" not in em
        or "resource.calendar" in em
        or em.startswith("group")
        or any(
            x in em
            for x in ("noreply", "no-reply", "calendar-notification", "notifications", "donotreply")
        )
    )


def nome_persona(n: str | None) -> str | None:
    ""
    if not n or not re.search(r"[A-Za-zÀ-ÿ]", n) or sum(c.isdigit() for c in n) >= 4:
        return None
    x = norm(re.sub(r"[^\w\s'.-]", " ", n))
    x = re.sub(r"\s+", " ", x).strip()
    if not x or is_owner_name(x) or not toks(x):
        return None
    return x


def segnale(
    file_id: str,
    regola: str,
    nome: str | None,
    prova: str,
    slot: str | None = None,
    attributo: dict | None = None,
) -> dict:
    r = REGOLE[regola]
    nome = norm(nome) if nome else None
    return {
        "file_id": file_id,
        "slot": slot,
        "tipo": r["tipo"],
        "nome": nome,
        "solo_nome": bool(nome) and len(nome.split()) == 1,
        "attributo": attributo,
        "direzione": r["direzione"],
        "regola": regola,
        "famiglia": r["famiglia"],
        "sottotipo": r["sottotipo"],
        "forza": r["forza"],
        "volte_il_caso": r["caso"],
        "gruppo": r["gruppo"],
        "prova": pulisci_prova(prova),
    }


_EMAIL_RX = re.compile(r"[\w.+'-]+@[\w-]+\.[\w.-]+")
_URL_RX = re.compile(r"https?://\S+")
_NUM_RX = re.compile(r"\+?\d[\d ./-]{6,}\d")


def pulisci_prova(p: str) -> str:
    ""
    p = _EMAIL_RX.sub("<email>", p or "")
    p = _URL_RX.sub("<link>", p)
    p = _NUM_RX.sub("<number>", p)
    return re.sub(r"\s+", " ", p).strip()[:200]


def a_due_slot(voci: list[dict]) -> str | None:
    ""
    big = [v for v in voci if (v.get("min") or 0) >= 1.0]
    ego = [v for v in big if v.get("classe") == "owner"]
    if len(big) != 2 or len(ego) != 1:
        return None
    return next(v["slot"] for v in big if v is not ego[0])


def overlap_quality(ea: float, eb: float, a: float, b: float) -> str | None:
    ""

    ov = max(0.0, min(eb, b) - max(ea, a))
    if ov <= 0:
        return None
    shorter = max(60.0, min(eb - ea, max(60.0, b - a)))
    if ea - 600 <= a <= eb and ov / shorter >= 0.5:
        return "stretto"
    return "sovrapposto"


def align(
    segs: list[dict], st: float, parole: list[tuple], toll: float = 25.0
) -> tuple[dict, int, int | None]:
    ""

    by_word: dict[str, list[float]] = defaultdict(list)
    for tt, _spk, w in parole:
        if len(w) >= 6:
            by_word[w].append(tt)
    diffs: Counter = Counter()
    for s in segs:
        ts = st + (s.get("start_time") or 0) / 1000
        for w in set(words(s.get("content"))):
            lst = by_word.get(w)
            if len(w) < 6 or not lst or len(lst) > 8:
                continue
            for tt in lst:
                d = tt - ts
                if abs(d) <= 900:
                    diffs[round(d / 5) * 5] += 1
    if not diffs:
        return {}, 0, None
    off, n = max(
        ((k, diffs[k] + diffs.get(k - 5, 0) + diffs.get(k + 5, 0)) for k in sorted(diffs)),
        key=lambda x: x[1],
    )
    if n < MIN_RARE:
        return {}, n, off
    idx: dict[str, list[tuple]] = defaultdict(list)
    for tt, spk, w in parole:
        idx[w].append((tt, spk))
    votes: dict[str, Counter] = defaultdict(Counter)
    for s in segs:
        slot = s.get("original_speaker") or s.get("speaker")
        t0 = st + (s.get("start_time") or 0) / 1000 + off
        t1 = st + (s.get("end_time") or 0) / 1000 + off
        for w in words(s.get("content")):
            for tt, spk in idx.get(w, ()):
                if t0 - toll <= tt <= t1 + toll and spk:
                    votes[slot][spk] += 1
    return dict(votes), n, off


def segnali_gemello(
    fid: str,
    votes: dict,
    n: int,
    fonte: str,
    titolo: str,
    parlanti: list[str],
    pool: frozenset,
    quota: float = 0.6,
    minimo: int = 10,
) -> list[dict]:
    ""
    if n < MIN_RARE:
        return []
    out = []
    scelti = []
    for slot, c in votes.items():
        tot = sum(c.values())
        spk, k = c.most_common(1)[0]
        if k < minimo or k / tot < quota:
            continue
        if is_owner_name(spk):
            out.append(
                segnale(
                    fid,
                    "R1-gemello-owner",
                    None,
                    f"{fonte} «{titolo[:60]}»: {k}/{tot} words of this voice said by you",
                    slot=slot,
                    attributo={"e_owner": True},
                )
            )
            continue
        scelti.append((slot, spk, k, tot))
    cnt = Counter(spk for _, spk, _, _ in scelti)
    for slot, spk, k, tot in scelti:
        nome = nome_persona(spk)
        if not nome:
            continue
        if cnt[spk] >= 2:
            out.append(
                segnale(
                    fid,
                    "R1-gemello-stanza",
                    nome,
                    f"{fonte} «{titolo[:60]}»: «{spk}» talks with {cnt[spk]} Plaud voices, it's a room account",
                    slot=slot,
                )
            )
        elif nome.split()[0] in pool:
            out.append(
                segnale(
                    fid,
                    "R1-gemello-unico",
                    nome,
                    f"{fonte} «{titolo[:60]}»: {k}/{tot} words of this voice said by «{spk}» at the same instant",
                    slot=slot,
                )
            )
    for p in sorted(set(parlanti)):
        nome = nome_persona(p)
        if nome:
            out.append(
                segnale(
                    fid,
                    "R1-gemello-roster",
                    nome,
                    f"speaks in the aligned {fonte} transcript «{titolo[:60]}»",
                )
            )
    return out


ORA_RX = re.compile(
    r"\b(?:alle|ore|at|@|per le|verso le|dalle)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b", re.I
)
ORA_NUDA = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b", re.I)
INCONTRO_WA = re.compile(
    r"\b(ci vediamo|ci sentiamo|ci becchiamo|ti chiamo|chiamami|mi chiami|call|meet|zoom|appuntamento|incontro|riunione|passo da|vengo da|da te|da me)\b",
    re.I,
)
INCONTRO = re.compile(
    r"\b(call|meet|meeting|riunion\w*|ci\s+(?:sentiamo|vediamo)|ci\s+becchiamo|appuntament\w*|incontr\w*|zoom|huddle|chiamat\w*|ti chiamo|chiamami)\b",
    re.I,
)
ARRIVO = re.compile(
    r"\b(sono arrivat[oa]|sto arrivando|arrivo|sono qui|sono sotto|sono giù|sono giu|scendo|sono fuori|ti aspetto|sono dentro|sono al|sono in reception|eccomi|i'?m here|on my way)\b",
    re.I,
)
DOPO = re.compile(
    r"\b(grazie per (la|il) (call|chiamata|tempo|incontro|pranzo|cena|caff[eè])|piacere di averti|bella chiacchierata|come detto|come d'accordo|come ci siamo detti|great to meet|nice to meet|thanks for (the|your) (call|time))\b",
    re.I,
)
INVITO = re.compile(
    r"^\s*(invito|invitation|updated invitation|invito aggiornato|nuovo evento|new event|evento aggiornato|event updated|rescheduled)\b",
    re.I,
)
ACCETTA = re.compile(
    r"^\s*(accettato|accepted|accettato provvisoriamente|tentatively accepted)\b", re.I
)
RIFIUTA = re.compile(
    r"^\s*(rifiutato|declined|canceled event|evento annullato|cancelled|annullato)\b", re.I
)
MESI = {
    1: "gen|jan|gennaio|january",
    2: "feb|febbraio|february",
    3: "mar|marzo|march",
    4: "apr|aprile|april",
    5: "mag|may|maggio",
    6: "giu|jun|giugno|june",
    7: "lug|jul|luglio|july",
    8: "ago|aug|agosto|august",
    9: "set|sep|settembre|september|sept",
    10: "ott|oct|ottobre|october",
    11: "nov|novembre|november",
    12: "dic|dec|dicembre|december",
}
GIORNI = {
    0: ("lunedi", "monday"),
    1: ("martedi", "tuesday"),
    2: ("mercoledi", "wednesday"),
    3: ("giovedi", "thursday"),
    4: ("venerdi", "friday"),
    5: ("sabato", "saturday"),
    6: ("domenica", "sunday"),
}
NOME_RX = re.compile(
    r"\b([A-ZÀ-Ý][a-zà-ÿ']{2,})(?:\s+(?:[Dd][ei]\s+|[Dd]ella\s+|[Dd]'|[Dd]el\s+)?([A-ZÀ-Ý][a-zà-ÿ']{2,}))?"
)


def ora_combacia(text: str, st: float, rx: re.Pattern = ORA_RX, toll_min: int = 45) -> bool:
    h = dt.datetime.fromtimestamp(st, ROME)
    for hh, mm, ap in rx.findall(text or ""):
        try:
            hh = int(hh)
            if ap and ap.lower() == "pm" and hh < 12:
                hh += 12
            x = h.replace(hour=hh % 24, minute=int(mm or 0))
        except ValueError:
            continue
        if abs((x - h).total_seconds()) <= toll_min * 60:
            return True
    return False


def data_combacia(text: str, st: float) -> bool:
    ""
    d = dt.datetime.fromtimestamp(st, ROME)
    t = (text or "").lower()
    m = MESI[d.month]
    pats = [
        rf"\b0?{d.day}\s+(?:{m})\b",
        rf"\b(?:{m})\.?\s+0?{d.day}\b",
        rf"\b0?{d.day}[/.]0?{d.month}\b",
        rf"{d.year}-{d.month:02d}-{d.day:02d}",
    ]
    return any(re.search(p, t) for p in pats)


def giorno_ok(text: str, msg_t: float, st: float) -> bool:
    ""
    m = dt.datetime.fromtimestamp(msg_t, ROME).date()
    r = dt.datetime.fromtimestamp(st, ROME).date()
    t = norm(text)
    if re.search(r"\bdopodomani\b", t):
        return (r - m).days == 2
    if re.search(r"\b(domani|tomorrow)\b", t):
        return (r - m).days == 1
    if re.search(r"\b(oggi|today|stasera|stamattina|tonight)\b", t):
        return r == m
    for wd, names in GIORNI.items():
        if any(re.search(rf"\b{n}\b", t) for n in names):
            return r.weekday() == wd
    return True


def nomi_nel_testo(text: str, pool: frozenset) -> list[str]:
    out = []
    for a, b in NOME_RX.findall(text or ""):
        if norm(a) in pool and not is_owner_name(a):
            out.append(f"{a} {b}".strip() if b and norm(b) not in STOP else a)
    return out


AI_TIT = re.compile(
    r":|riunione|analisi|strategi|discussione|consulenza|meeting|sintesi|aggiornamento|riepilogo|revisione|piano|gestione|conversazione|incontro|valutazione",
    re.I,
)


def titolo_a_mano(titolo: str) -> bool:
    t = re.sub(r"^\d\d-\d\d\s*", "", titolo or "")
    return bool(t) and not AI_TIT.search(t) and len(t.split()) <= 5


def nomi_titolo(titolo: str, pool: frozenset, cognomi: set) -> list[str]:
    tk = toks(re.sub(r"^\d\d-\d\d\s*", "", titolo or ""))
    out, i = [], 0
    while i < len(tk):
        x = tk[i]
        if x in pool:
            nxt = tk[i + 1] if i + 1 < len(tk) and tk[i + 1] in cognomi else None
            out.append(f"{x} {nxt}" if nxt else x)
            i += 2 if nxt else 1
            continue
        if x in cognomi and len(x) >= 5:
            out.append(x)
        i += 1
    return out





def regole_calendario(
    r: dict, events: list[dict], starts: list[float], en: dict, pool: frozenset
) -> list[dict]:
    if not r["st"]:
        return []
    a, b = r["st"], r["st"] + r["dur"]
    i = bisect.bisect_right(starts, b)
    out = []
    for e in events[max(0, i - 400) : i]:
        q = overlap_quality(e["a"], e["b"], a, b)
        if not q:
            continue
        hhmm = dt.datetime.fromtimestamp(e["a"], ROME).strftime("%H:%M")
        tit = f"«{e['titolo'][:60]}» {hhmm}"
        inv = e["invitati"]
        owner_no = e["owner_status"] in ("declined", "tentative")
        for em, stx in inv.items():
            nome = nome_persona(en.get(em)) or nome_persona(
                em.split("@")[0] if re.search(r"[._-]", em.split("@")[0]) else None
            )
            if not nome:
                continue
            if owner_no:
                out.append(
                    segnale(
                        r["id"],
                        "R1-cal-owner-rifiutato",
                        nome,
                        f"event {tit}: you replied {e['owner_status']}",
                    )
                )
                continue
            if stx == "declined":
                out.append(
                    segnale(
                        r["id"], "R1-cal-rifiutato", nome, f"event {tit}: declined the invitation"
                    )
                )
                continue
            if stx == "tentative":
                continue
            out.append(
                segnale(
                    r["id"],
                    "R1-cal-stretto" if q == "stretto" else "R1-cal-sovrapposto",
                    nome,
                    f"invited ({stx}) to event {tit}",
                )
            )
            if not e["ricorrente"]:
                out.append(
                    segnale(r["id"], "R1-cal-singolo", nome, f"invited to the single event {tit}")
                )
            if len(inv) == 1:
                out.append(
                    segnale(
                        r["id"],
                        "R1-cal-un-invitato",
                        nome,
                        f"only invitee besides you at event {tit}",
                    )
                )
            if e["luogo"] and not e["call"] and not e["luogo"].startswith("http"):
                out.append(
                    segnale(
                        r["id"], "R1-cal-luogo-fisico", nome, f"event {tit} at «{e['luogo'][:50]}»"
                    )
                )
            if e["owner_status"] in (None, "accepted"):
                out.append(
                    segnale(
                        r["id"],
                        "R1-cal-owner-accettato",
                        nome,
                        f"event {tit} accepted by you or yours",
                    )
                )
            if q == "stretto" and len(inv) == 1:
                slot = a_due_slot(r["voci"])
                if slot:
                    out.append(
                        segnale(
                            r["id"],
                            "R1-cal-a-due",
                            nome,
                            f"two-person event {tit}: you and only one voice besides you",
                            slot=slot,
                        )
                    )
        if not owner_no:
            for t in toks(e["titolo"]):
                if t in pool:
                    out.append(
                        segnale(r["id"], "R1-cal-titolo", t, f"name in the event title {tit}")
                    )
    return out


def regole_wa_chiamate(r: dict, calls: list[dict]) -> list[dict]:
    if not r["st"]:
        return []
    a, b = r["st"], r["st"] + r["dur"]
    out = []
    simili = set()
    for c in calls:
        if c["t"] > b:
            break
        if c["durata"] < 60:
            continue
        ca, cb = c["t"], c["t"] + c["durata"]
        ov = min(b, cb) - max(a, ca)
        if ov <= 0 or ov < 0.3 * min(b - a, cb - ca):
            continue
        hh = dt.datetime.fromtimestamp(ca, ROME).strftime("%H:%M")
        prova = f"WhatsApp call at {hh}, {round(c['durata'] / 60)} min"
        for n in c["nomi"]:
            nome = nome_persona(n)
            if not nome:
                continue
            if c["gruppo"]:
                out.append(segnale(r["id"], "R1-wa-gruppo", nome, prova + " (group)"))
                continue
            out.append(segnale(r["id"], "R1-wa-chiamata", nome, prova))
            if 0.6 <= (b - a) / max(1, cb - ca) <= 1.6:
                out.append(
                    segnale(
                        r["id"],
                        "R1-wa-durata-simile",
                        nome,
                        prova + ", duration similar to the recording",
                    )
                )
                simili.add(nome)
    if len(simili) == 1:
        slot = a_due_slot(r["voci"])
        if slot:
            nome = next(iter(simili))
            out.append(
                segnale(
                    r["id"],
                    "R1-wa-a-due",
                    nome,
                    "two-person WhatsApp call of similar duration, the other voice is yours",
                    slot=slot,
                )
            )
    return out


def _between(items: list, times: list[float], t0: float, t1: float) -> list:
    return items[bisect.bisect_left(times, t0) : bisect.bisect_right(times, t1)]


def regole_wa_messaggi(r: dict, msgs: list[tuple], times: list[float]) -> list[dict]:
    ""
    if not r["st"]:
        return []
    st, en = r["st"], r["st"] + r["dur"]
    out, visti = [], set()

    def add(regola, partner, prova):
        nome = nome_persona(partner)
        if nome and (regola, nome) not in visti:
            visti.add((regola, nome))
            out.append(segnale(r["id"], regola, nome, prova))

    for t, me, grp, partner, text in _between(msgs, times, st - 36 * 3600, st + 600):
        if not grp and ora_combacia(text, st) and INCONTRO_WA.search(text):
            add("R1-wa-fissa", partner, "WhatsApp message setting the time: " + text[:120])
    for t, me, grp, partner, text in _between(msgs, times, st - 40 * 60, st + 15 * 60):
        if not grp and not me and ARRIVO.search(text):
            add("R1-wa-arrivo", partner, "WhatsApp arrival message: " + text[:120])
    for t, me, grp, partner, text in _between(msgs, times, en, en + 6 * 3600):
        if not grp and DOPO.search(text):
            add("R1-wa-dopo", partner, "WhatsApp message after the meeting: " + text[:120])
    prima = Counter(p for t, me, grp, p, _ in _between(msgs, times, st - 1800, st) if not grp and p)
    for p, k in prima.items():
        if k >= 2:
            add("R1-wa-attivo-prima", p, f"{k} WhatsApp messages in the half hour before")
    durante = Counter(
        p for t, me, grp, p, _ in _between(msgs, times, st + 120, en - 120) if not grp and p
    )
    for p, k in durante.items():
        if k >= 3:
            add("R1-wa-durante", p, f"{k} WhatsApp messages exchanged while recording")
    return out


def regole_email(r: dict, mails: list[tuple], times: list[float]) -> list[dict]:
    ""
    if not r["st"]:
        return []
    st = r["st"]
    out, visti = [], set()
    for t, owner, fr, to, subj in _between(mails, times, st - 30 * 86400, st + 3600):
        if not (data_combacia(subj, st) and ora_combacia(subj, st, ORA_NUDA)):
            continue
        if INVITO.search(subj):
            regola, gente = "R1-email-invito", fr + to
        elif ACCETTA.search(subj):
            regola, gente = "R1-email-accettato", fr
        elif RIFIUTA.search(subj):
            regola, gente = "R1-email-rifiutato", fr
        else:
            continue
        for nm, _em in gente:
            nome = nome_persona(nm)
            if nome and (regola, nome) not in visti:
                visti.add((regola, nome))
                out.append(segnale(r["id"], regola, nome, "email «" + subj[:150] + "»"))
    return out


def regole_slack(r: dict, msgs: list[tuple], times: list[float], pool: frozenset) -> list[dict]:
    ""
    if not r["st"]:
        return []
    st = r["st"]
    out, visti = [], set()

    def add(regola, n, prova):
        nome = nome_persona(n)
        if nome and (regola, nome) not in visti:
            visti.add((regola, nome))
            out.append(segnale(r["id"], regola, nome, prova))

    for t, owner, tp, cc, text in _between(msgs, times, st - 36 * 3600, st + 600):
        if ora_combacia(text, st) and INCONTRO.search(text) and giorno_ok(text, t, st):
            for n in nomi_nel_testo(text, pool):
                add("R1-slack-nomi", n, "Slack message: " + text[:140])
    for t, owner, tp, cc, text in _between(msgs, times, st - 900, st + 300):
        if INCONTRO.search(text):
            for n in cc:
                add("R1-slack-avvio", n, "Slack shortly before: " + text[:140])
    c = Counter(
        n for t, owner, tp, cc, _ in _between(msgs, times, st - 1800, st) if tp == "dm" for n in cc
    )
    for n, k in c.items():
        if k >= 2:
            add("R1-slack-attivo-prima", n, f"{k} Slack DMs in the half hour before")
    return out


def regole_titolo(r: dict, pool: frozenset, cognomi: set) -> list[dict]:
    out = []
    nomi = nomi_titolo(r["titolo"], pool, cognomi)
    if titolo_a_mano(r["titolo"]):
        for n in dict.fromkeys(nomi):
            out.append(
                segnale(r["id"], "R1-titolo-mano", n, f"note title «{r['titolo'][:80]}»")
            )
    if len(nomi) == 1:
        slot = a_due_slot(r["voci"])
        if slot:
            out.append(
                segnale(
                    r["id"],
                    "R1-titolo-a-due",
                    nomi[0],
                    f"a single name in the title «{r['titolo'][:80]}» and two voices, one yours",
                    slot=slot,
                )
            )
    return out





def _firma(paths: list[Path]) -> str:
    h = hashlib.sha1()
    for p in sorted(paths):
        try:
            s = p.stat()
            h.update(f"{p}|{s.st_mtime_ns}|{s.st_size}".encode())
        except OSError:
            continue
    return h.hexdigest()


def _cache(nome: str, paths: list[Path], build, usa: bool):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{nome}.pkl"
    firma = _firma(paths)
    if usa and p.exists():
        try:
            d = pickle.loads(p.read_bytes())
            if d.get("firma") == firma:
                return d["dati"]
        except Exception:  # noqa: BLE001 - broken cache: it is rebuilt
            pass
    dati = build()
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps({"firma": firma, "dati": dati}))
    tmp.replace(p)
    return dati


def _duck():
    import duckdb

    con = duckdb.connect()
    con.execute("set memory_limit='2GB'; set threads=2")
    return con


def carica_registrazioni() -> list[dict]:
    q = json.loads((QUADRO / "quadro.json").read_text())
    idx = {
        x["id"]: x for x in json.loads((DATA / "plaud" / "raw" / "_file_index.json").read_text())
    }
    regs = []
    for r in q["registrazioni"]:
        m = idx.get(r["id"], {})
        regs.append(
            {
                "id": r["id"],
                "titolo": r.get("titolo") or "",
                "data": r.get("data") or "",
                "st": (m.get("st") or 0) / 1000,
                "dur": float(m.get("duration_sec") or 0),
                "voci": [
                    {"slot": v["voce"], "classe": v["classe"], "min": v["minuti"]}
                    for v in r["voci"]
                ],
            }
        )
    return regs


def _attio_dirs() -> list[Path]:
    """Every Attio workspace folder: attio/ (primary) and attio-<label>/ (attio.extra_workspaces)."""
    return [DATA / "attio", *sorted(p for p in DATA.glob("attio-*") if p.is_dir())]


def carica_email_nomi(usa: bool) -> dict[str, str]:
    attio_people = [d / "people.parquet" for d in _attio_dirs()]
    contacts = DATA / "contacts" / "contacts.parquet"
    email_index = DATA / "plaud" / "_email_index.json"
    files = [
        *attio_people,
        contacts,
        email_index,
        *sorted((DATA / "emails").glob("*/messages.parquet")),
    ]

    def build():
        con = _duck()
        out: dict[str, Counter] = defaultdict(Counter)

        def add(em, name, w):
            em = (em or "").strip().lower().strip("<>\"' ")
            name = (name or "").strip().strip("\"'")
            if (
                em
                and "@" in em
                and name
                and "@" not in name
                and not re.match(r"^person_[0-9a-f]+$", name)
                and toks(name)
            ):
                out[em][name] += w

        for f in attio_people:
            if f.exists():
                for name, ems in con.execute(f"select name, email_addresses from '{f}'").fetchall():
                    for em in re.findall(r"[\w.+'-]+@[\w.-]+", str(ems or "")):
                        add(em, name, 5)
        if contacts.exists():
            for name, e1, ea in con.execute(
                f"select full_name, primary_email, all_emails from '{contacts}'"
            ).fetchall():
                for em in set(re.findall(r"[\w.+'-]+@[\w.-]+", f"{e1} {ea}")):
                    add(em, name, 4)
        if email_index.exists():
            for em, x in json.loads(email_index.read_text()).items():
                add(em, (x or {}).get("name"), 3)
        rx = re.compile(r"\s*\"?([^\"<>,]{2,60}?)\"?\s*<([^<>@\s]+@[^<>\s]+)>")
        for row in con.execute(
            f"select from_addr, to_addr, cc from read_parquet('{DATA}/emails/*/messages.parquet', union_by_name=true)"
        ).fetchall():
            for field in row:
                for name, em in rx.findall(str(field or "")):
                    add(em, name, 1)
        return {em: c.most_common(1)[0][0] for em, c in out.items()}

    return _cache("email_nomi", files, build, usa)


def carica_eventi(usa: bool) -> list[dict]:
    files = sorted((DATA / "calendars").glob("*/events.parquet"))

    def build():
        con = _duck()
        rows = con.execute(
            "select id, summary, start_datetime, end_datetime, location, description, organizer_email, attendees, status, conference_url, recurring_event_id "
            f"from read_parquet('{DATA}/calendars/*/events.parquet', union_by_name=true) where length(start_datetime) > 10"
        ).fetchall()
        by: dict[str, dict] = {}
        for eid, summ, s, e, loc, desc, org, att, status, conf, rec in rows:
            if status == "cancelled":
                continue
            try:
                a = dt.datetime.fromisoformat(s).timestamp()
                b = dt.datetime.fromisoformat(e).timestamp() if e else a + 1800
            except ValueError:
                continue
            if b <= a or b - a > 12 * 3600:
                continue
            try:
                lst = json.loads(att or "[]")
            except (json.JSONDecodeError, TypeError):
                lst = []
            inv, owner_status = {}, None
            for x in lst if isinstance(lst, list) else []:
                em, stx = (x.get("email") or "").lower(), x.get("status")
                if is_owner_email(em):
                    owner_status = stx if owner_status in (None, "needsAction") else owner_status
                elif not bad_email(em):
                    inv[em] = stx
            key = eid or f"{s}|{summ}"
            ev = by.get(key)
            if ev is None:
                by[key] = {
                    "a": a,
                    "b": b,
                    "titolo": summ or "",
                    "luogo": (loc or "").strip(),
                    "call": bool(conf)
                    or bool(
                        re.search(
                            r"meet\.google|zoom\.us|teams\.microsoft|whereby|webex",
                            f"{loc} {desc}",
                            re.I,
                        )
                    ),
                    "ricorrente": bool(rec) or bool(re.search(r"_\d{8}(T\d{6}Z?)?$", eid or "")),
                    "invitati": inv,
                    "owner_status": owner_status,
                }
            else:
                for em, stx in inv.items():
                    if ev["invitati"].get(em) in (None, "needsAction"):
                        ev["invitati"][em] = stx
                if owner_status and ev["owner_status"] in (None, "needsAction"):
                    ev["owner_status"] = owner_status
        return sorted(by.values(), key=lambda x: x["a"])

    return _cache("eventi", files, build, usa)


def _iso(s) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def carica_gemelli(regs: list[dict], usa: bool) -> list[dict]:
    ""
    tactiq = sorted((DATA / "tactiq" / "raw").glob("*.json"))
    gem = sorted(p for p in (DATA / "gdrive").rglob("*.md") if "Gemini" in p.name)
    attio = [d / "call-recordings.parquet" for d in _attio_dirs()]
    finestre = sorted((r["st"], r["st"] + r["dur"]) for r in regs if r["st"])
    starts = [a for a, _ in finestre]

    def tocca(a, b):
        i = bisect.bisect_right(starts, b)
        return any(fb >= a for _, fb in finestre[max(0, i - 50) : i])

    def build():
        out = []
        for f in tactiq:
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(d, dict) or not d.get("created"):
                continue
            st = d["created"] / 1000
            if not tocca(st, st + float(d.get("duration") or 0) + 600):
                continue
            ws = []
            for bl in ((d.get("transcript") or {}).get("blocks")) or []:
                if not bl.get("isDeleted"):
                    for w in words(bl.get("transcript")):
                        ws.append(
                            ((bl.get("timestamp") or 0) / 1000, bl.get("speakerName") or "", w)
                        )
            if ws:
                out.append(
                    {
                        "fonte": "Tactiq",
                        "a": st,
                        "b": max(st + float(d.get("duration") or 0), ws[-1][0]),
                        "titolo": d.get("title") or "",
                        "parlanti": sorted(
                            {x[1] for x in ws if x[1]}
                            | {p.get("name") for p in d.get("participants") or [] if p.get("name")}
                        ),
                        "parole": ws,
                        "toll": 25.0,
                    }
                )
        con = _duck()
        visti = set()
        for cr in attio:
            if not cr.exists():
                continue
            for title, created, file in con.execute(
                f"select meeting_title, created_at, file from '{cr}'"
            ).fetchall():
                st = _iso(created)
                fp = cr.parent / "transcripts" / (file or "")
                if not st or not file or not fp.exists() or not tocca(st, st + 4 * 3600):
                    continue
                k = (round(st / 600), (title or "")[:40])
                if k in visti:
                    continue
                visti.add(k)
                try:
                    segs = json.loads(fp.read_text()).get("segments") or []
                except (OSError, json.JSONDecodeError, AttributeError):
                    continue
                ws = [
                    (st + float(s.get("start") or 0), s.get("speaker") or "", w)
                    for s in segs
                    for w in words(s.get("text"))
                ]
                if ws:
                    out.append(
                        {
                            "fonte": "Attio",
                            "a": st,
                            "b": ws[-1][0],
                            "titolo": title or "",
                            "parlanti": sorted({x[1] for x in ws if x[1]}),
                            "parole": ws,
                            "toll": 25.0,
                        }
                    )
        tz = {
            "CEST": 2,
            "CET": 1,
            "IST": 1,
            "BST": 1,
            "GMT": 0,
            "UTC": 0,
            "EST": -5,
            "EDT": -4,
            "CST": -6,
            "CDT": -5,
            "PST": -8,
            "PDT": -7,
        }
        rx = re.compile(r"(\d{4})_(\d{2})_(\d{2}) (\d{2})_(\d{2}) ([A-Z]{2,5})")
        visti = set()
        for f in gem:
            m = rx.search(f.name)
            if not m or m.group(6) not in tz:
                continue
            y, mo, da, hh, mi, z = m.groups()
            st = dt.datetime(
                int(y),
                int(mo),
                int(da),
                int(hh),
                int(mi),
                tzinfo=dt.timezone(dt.timedelta(hours=tz[z])),
            ).timestamp()
            k = (round(st / 60), f.name[:40])
            if k in visti or not tocca(st - 900, st + 4 * 3600):
                continue
            visti.add(k)
            try:
                txt = f.read_text(errors="ignore")
            except OSError:
                continue
            ws, blocco, cur = [], [], 0.0

            def scarica(bl, t0, t1, st=st, ws=ws):
                for j, (spk, testo) in enumerate(bl):
                    for w in words(testo):
                        ws.append((st + t0 + (t1 - t0) * j / max(1, len(bl)), spk, w))

            for line in txt[max(txt.find("📖"), 0) :].splitlines():
                mt = re.match(r"^\s*(\d{2}):(\d{2}):(\d{2})\s*$", line)
                if mt:
                    nuovo = int(mt.group(1)) * 3600 + int(mt.group(2)) * 60 + int(mt.group(3))
                    scarica(blocco, cur, nuovo)
                    blocco, cur = [], float(nuovo)
                    continue
                ms = re.match(r"^([A-ZÀ-Ý][^:]{1,40}):\s+(.+)$", line)
                if ms:
                    blocco.append((ms.group(1).strip(), ms.group(2)))
            scarica(blocco, cur, cur + 300)
            if ws:
                out.append(
                    {
                        "fonte": "Google Meet",
                        "a": st,
                        "b": max(x[0] for x in ws) + 60,
                        "titolo": f.name[:60],
                        "parlanti": sorted({x[1] for x in ws if x[1]}),
                        "parole": ws,
                        "toll": 120.0,
                    }
                )
        return sorted(out, key=lambda x: x["a"])

    return _cache("gemelli", tactiq + gem + attio + [QUADRO / "quadro.json"], build, usa)


def _pb(b: bytes) -> list[tuple]:
    ""
    i, out = 0, []
    while i < len(b):
        try:
            k, s = 0, 0
            while True:
                c = b[i]
                i += 1
                k |= (c & 0x7F) << s
                s += 7
                if not c & 0x80:
                    break
        except IndexError:
            break
        f, w = k >> 3, k & 7
        if w == 0:
            v, s = 0, 0
            while i < len(b):
                c = b[i]
                i += 1
                v |= (c & 0x7F) << s
                s += 7
                if not c & 0x80:
                    break
            out.append((f, v))
        elif w == 2:
            n, s = 0, 0
            while i < len(b):
                c = b[i]
                i += 1
                n |= (c & 0x7F) << s
                s += 7
                if not c & 0x80:
                    break
            out.append((f, b[i : i + n]))
            i += n
        elif w == 1:
            i += 8
        elif w == 5:
            i += 4
        else:
            break
    return out


def chiamata_da_metadato(md: bytes) -> tuple[int | None, int, list[str]]:
    ""
    esito, durata, parts = None, 0, []
    for f, v in _pb(md or b""):
        if f == 87 and isinstance(v, bytes):
            for f2, v2 in _pb(v):
                if f2 == 1 and isinstance(v2, bytes):
                    for f3, v3 in _pb(v2):
                        if f3 == 2 and isinstance(v3, int):
                            esito = v3
                        elif f3 == 3 and isinstance(v3, int):
                            durata = v3
                        elif f3 == 5 and isinstance(v3, bytes):
                            for f4, v4 in _pb(v3):
                                if f4 == 1 and isinstance(v4, bytes):
                                    parts.append(v4.decode("utf-8", "ignore"))
    return esito, durata, parts


def carica_whatsapp(usa: bool) -> tuple[list[dict], list[tuple]]:
    dbs = sorted((DATA / "whatsapp").glob("chatstorage-*/ChatStorage.sqlite"))
    chats = sorted((DATA / "whatsapp" / "chats").glob("*.json"))

    def build():
        calls, msgs, fine_db = [], [], 0.0
        for db in dbs:
            con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
            jid = {}
            for q in (
                "select ZCONTACTJID, ZPARTNERNAME from ZWACHATSESSION where ZSESSIONTYPE=0",
                "select ZMEMBERJID, ZCONTACTNAME from ZWAGROUPMEMBER",
                "select ZJID, ZPUSHNAME from ZWAPROFILEPUSHNAME",
            ):
                for j, n in con.execute(q):
                    if j and n:
                        jid.setdefault(j, n)
            for date, stype, partner, md in con.execute(
                "select m.ZMESSAGEDATE, s.ZSESSIONTYPE, s.ZPARTNERNAME, mi.ZMETADATA from ZWAMESSAGE m join ZWACHATSESSION s on s.Z_PK=m.ZCHATSESSION "
                "join ZWAMEDIAITEM mi on mi.Z_PK=m.ZMEDIAITEM where m.ZMESSAGETYPE=59"
            ):
                if md is None or date is None:
                    continue
                _esito, durata, parts = chiamata_da_metadato(md)
                nomi = [partner] if stype == 0 and partner else [jid[j] for j in parts if j in jid]
                calls.append(
                    {
                        "t": date + APPLE_EPOCH,
                        "durata": durata,
                        "gruppo": stype != 0,
                        "nomi": [n for n in nomi if not is_owner_name(n)],
                    }
                )
            for date, me, stype, partner, text in con.execute(
                "select m.ZMESSAGEDATE, m.ZISFROMME, s.ZSESSIONTYPE, s.ZPARTNERNAME, m.ZTEXT from ZWAMESSAGE m join ZWACHATSESSION s on s.Z_PK=m.ZCHATSESSION "
                "where m.ZMESSAGETYPE=0 and m.ZTEXT is not null"
            ):
                t = date + APPLE_EPOCH
                fine_db = max(fine_db, t)
                msgs.append((t, bool(me), stype != 0, partner or "", text))
            con.close()
        for f in chats:
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(d, dict):
                continue
            try:
                group = int(d.get("participant_count") or 0) > 2
            except ValueError:
                group = True
            partner = d.get("chat_name") or ""
            for m in d.get("messages") or []:
                try:
                    t = (
                        dt.datetime.fromisoformat(m.get("timestamp") or "")
                        .replace(tzinfo=ROME)
                        .timestamp()
                    )
                except ValueError:
                    continue
                if t <= fine_db:
                    continue
                msgs.append(
                    (
                        t,
                        is_owner_name(m.get("sender") or ""),
                        group,
                        (m.get("sender") or "") if group else partner,
                        m.get("text") or "",
                    )
                )
        calls.sort(key=lambda x: x["t"])
        msgs.sort(key=lambda x: x[0])
        return calls, msgs

    return _cache("whatsapp", dbs + chats, build, usa)


def carica_email(usa: bool) -> list[tuple]:
    files = sorted((DATA / "emails").glob("*/messages.parquet"))
    en = None

    def build():
        nonlocal en
        en = carica_email_nomi(True)
        con = _duck()
        rx = re.compile(
            r"\s*\"?([^\"<>,]{0,60}?)\"?\s*<([^<>@\s]+@[^<>\s,]+)>|([\w.+'-]+@[\w-]+\.[\w.-]+)"
        )

        def addrs(field):
            out = []
            for name, em, em2 in rx.findall(str(field or "")):
                em = (em or em2).lower().strip()
                if not is_owner_email(em) and not bad_email(em):
                    out.append((name.strip() or en.get(em) or "", em))
            return out

        rows = con.execute(
            "select epoch(cast(date as timestamptz)), from_addr, to_addr, cc, subject "
            f"from read_parquet('{DATA}/emails/*/messages.parquet', union_by_name=true) where subject is not null order by 1"
        ).fetchall()
        out, seen = [], set()
        for t, fr, to, cc, subj in rows:
            if not t or not (INVITO.search(subj) or ACCETTA.search(subj) or RIFIUTA.search(subj)):
                continue
            k = (int(t) // 60, subj[:60])
            if k in seen:
                continue
            seen.add(k)
            owner = any(
                is_owner_email(x) for x in re.findall(r"[\w.+'-]+@[\w-]+\.[\w.-]+", str(fr or ""))
            )
            out.append((float(t), owner, addrs(fr), addrs(to) + addrs(cc), subj))
        return out

    return _cache("email", files, build, usa)


def carica_slack(usa: bool) -> list[tuple]:
    s = DATA / "slack"
    files = [
        s / "slack-users.json",
        *sorted((s / "dm").glob("U*.json")),
        *sorted((s / "conversations").glob("mpdm-*.json")),
    ]

    def build():
        users = (
            json.loads((s / "slack-users.json").read_text())
            if (s / "slack-users.json").exists()
            else {}
        )
        name = {
            k: (v.get("real_name") or v.get("name") or "")
            for k, v in users.items()
            if isinstance(v, dict) and str(v.get("is_bot")) != "True"
        }
        owner = {
            k
            for k, v in users.items()
            if isinstance(v, dict)
            and (
                is_owner_name(v.get("real_name") or v.get("name") or "")
                or str((v.get("profile") or {}).get("email", "")).lower() in _OWN
            )
        }
        msgs = []
        for f in (s / "dm").glob("U*.json"):
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            other = d.get("user_id") or f.stem
            nm = name.get(other)
            if other in owner or not nm:
                continue
            for m in d.get("messages") or []:
                try:
                    msgs.append(
                        (
                            float(m.get("ts") or 0),
                            m.get("user") in owner,
                            "dm",
                            [nm],
                            m.get("text") or "",
                        )
                    )
                except ValueError:
                    continue
        for f in (s / "conversations").glob("*.json"):
            try:
                d = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(d, dict) or not str(d.get("channel") or f.stem).startswith("mpdm-"):
                continue
            ms = d.get("messages") or []
            autori = sorted(
                {
                    name.get(m.get("user"), "")
                    for m in ms
                    if m.get("user") and m.get("user") not in owner
                }
                - {""}
            )
            if len(autori) > 6:
                continue
            for m in ms:
                try:
                    msgs.append(
                        (
                            float(m.get("ts") or 0),
                            m.get("user") in owner,
                            "gruppo",
                            autori,
                            m.get("text") or "",
                        )
                    )
                except ValueError:
                    continue
        msgs.sort(key=lambda x: x[0])
        return msgs

    return _cache("slack", files, build, usa)


def segmenti_plaud() -> dict[str, Path]:
    out = {}
    for t in (DATA / "plaud" / "raw").glob("*.txt"):
        try:
            m = re.search(r"# ID:\s*(\S+)", t.open(errors="ignore").read(400))
        except OSError:
            continue
        if m and t.with_suffix(".json").exists():
            out[m.group(1)] = t.with_suffix(".json")
    return out


def pool_nomi() -> frozenset:
    ""
    from tools.plaud.pl_quadro import nomi_kb

    pool, _ = nomi_kb()
    return pool





def calcola(usa_cache: bool = True) -> tuple[list[dict], dict]:
    t0 = time.time()
    regs = carica_registrazioni()
    pool = pool_nomi()
    en = carica_email_nomi(usa_cache)

    cognomi = {t[-1] for t in (toks(n) for n in set(en.values())) if len(t) >= 2}
    events = carica_eventi(usa_cache)
    ev_starts = [e["a"] for e in events]
    gemelli = carica_gemelli(regs, usa_cache)
    calls, wa_msgs = carica_whatsapp(usa_cache)
    wa_t = [m[0] for m in wa_msgs]
    mails = carica_email(usa_cache)
    mail_t = [m[0] for m in mails]
    slack = carica_slack(usa_cache)
    slack_t = [m[0] for m in slack]
    id2json = segmenti_plaud()
    tempi = {"caricamento_s": round(time.time() - t0, 1)}

    out: list[dict] = []
    allineate = 0
    for r in regs:
        if not r["st"]:
            continue
        a, b = r["st"], r["st"] + r["dur"]
        tw = [
            t
            for t in gemelli
            if min(b, t["b"]) - max(a, t["a"]) >= max(60, 0.2 * min(b - a, t["b"] - t["a"]))
        ]
        if tw and r["id"] in id2json:
            try:
                segs = [s for s in json.loads(id2json[r["id"]].read_text()) if isinstance(s, dict)]
            except (OSError, json.JSONDecodeError, TypeError):
                segs = []
            for t in tw:
                votes, n, _off = align(segs, r["st"], t["parole"], t["toll"])
                if n >= MIN_RARE:
                    allineate += 1
                out += segnali_gemello(
                    r["id"], votes, n, t["fonte"], t["titolo"], t["parlanti"], pool
                )
        out += regole_wa_chiamate(r, calls)
        out += regole_wa_messaggi(r, wa_msgs, wa_t)
        out += regole_calendario(r, events, ev_starts, en, pool)
        out += regole_email(r, mails, mail_t)
        out += regole_slack(r, slack, slack_t, pool)
        out += regole_titolo(r, pool, cognomi)

    visti, uniq = set(), []
    for s in out:
        k = (
            s["file_id"],
            s["slot"],
            s["regola"],
            s["nome"],
            json.dumps(s["attributo"], sort_keys=True),
        )
        if k not in visti:
            visti.add(k)
            uniq.append(s)
    stat = {
        **tempi,
        "totale_s": round(time.time() - t0, 1),
        "registrazioni": len(regs),
        "gemelli_caricati": len(gemelli),
        "gemelli_allineati": allineate,
        "chiamate_wa": len(calls),
        "segnali": len(uniq),
        "per_regola": dict(Counter(s["regola"] for s in uniq).most_common()),
        "registrazioni_per_regola": {
            k: len({s["file_id"] for s in uniq if s["regola"] == k}) for k in REGOLE
        },
    }
    return uniq, stat


def scrivi(segnali: list[dict], path: Path = OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segnali))
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud rules R1, other sources"])[0]
    )
    ap.add_argument(
        "--no-cache",
        dest="senza_cache",
        action="store_true",
        help="rebuilds the intermediate caches",
    )
    # Older Italian name, kept as a hidden alias.
    ap.add_argument(
        "--senza-cache", dest="senza_cache", action="store_true", help=argparse.SUPPRESS
    )
    args = ap.parse_args()
    segnali, stat = calcola(not args.senza_cache)
    scrivi(segnali)
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "ultimo-giro.json").write_text(json.dumps(stat, ensure_ascii=False, indent=1))
    print(json.dumps(stat, ensure_ascii=False, indent=1))
    print(f"wrote {OUT} ({len(segnali)} signals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
