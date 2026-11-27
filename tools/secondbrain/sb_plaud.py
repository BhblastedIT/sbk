#!/usr/bin/env python3
"""Plaud section of the SecondBrain app: who speaks in your recordings, how solid each name is, which recordings
still need names and which are outside the knowledge base, read from <data root>/plaud/quadro/quadro.json
(written by tools/plaud/pl_quadro.py).

Usage: uv run python tools/secondbrain/sb_plaud.py json   (prints the state the app shows)
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path


QUADRO = Path(
    os.environ.get("SB_PLAUD_QUADRO")
    or Path(
        os.environ.get("SBK_DATA") or os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data"
    ).expanduser()
    / "plaud"
    / "quadro"
    / "quadro.json"
)


LINK_NOTA = "https://web.plaud.ai/file/{id}"

MESI = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MESI_INTERI = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


LIVELLI = ("confermato", "solido", "una prova", "solo nome", "sospetto", "smentito", "senza nome")

TESTI = {
    "titolo": "Plaud",
    "sottotitolo": "The names of who speaks in your recordings, how solid they are and where naming starts.",

    "modulo_quadro": "Overview",
    "modulo_metodo": "The method",
    "modulo_da_nominare": "To name",
    "modulo_fuori": "Outside the base",
    "modulo_perche": "Why",
    "modulo_attivita": "Activity",
    "aiuto_modulo_quadro": "The project's numbers, the solidity levels, month by month and the measurement rounds.",
    "aiuto_modulo_metodo": "How names are given, step by step, with your words from when you said it.",
    "aiuto_modulo_da_nominare": "The recordings with speakers still unnamed, from the longest to name.",
    "aiuto_modulo_fuori": "The recordings the knowledge base has not read yet.",
    "aiuto_modulo_perche": "Why Plaud no longer adds names, with the evidence.",
    "aiuto_modulo_attivita": "The project's work plan and how far along each step is.",

    "obiettivo": "The goal",
    "metodo": "How you get there",
    "numeri": "Where we are",
    "livelli": "How solid the names are",
    "aiuto_livelli": "Every speaker in a recording has a level. The bar is made of the minutes spoken.",
    "per_mese": "Month by month",
    "aiuto_per_mese": "For each month the share of minutes still unnamed and the share with a solid name.",
    "serie_senza_nome": "unnamed",
    "serie_solidi": "solid",
    "indizi": "The judgment rules",
    "aiuto_indizi": "Each clue starts from a weight decided beforehand and is corrected by the cases you verified.",
    "col_indizio": "Clue",
    "col_partenza": "Starting weight",
    "col_giusti": "Right",
    "col_sbagliati": "Wrong",
    "col_peso": "Current weight",
    "fiducia": "How sure we are of the names",
    "aiuto_fiducia": "The speakers that have a name, split by how much we trust the name summing all the clues.",
    "storia": "The measurement rounds",
    "aiuto_storia": "Every time the measures are redone a row stays. That way you see if we improve.",
    "col_quando": "Round",
    "col_senza_nome": "Unnamed",
    "col_solidi": "Solid",
    "col_sospetti": "Suspect",
    "col_verificate": "Verified by you",
    "col_fuori": "Outside the base",

    "metodo_in_breve": "In short",
    "passi": "The steps",
    "aiuto_passi": "Each step with your words and the dates you said it.",
    "scoperte": "What we found",
    "aiuto_scoperte": "The things found re-reading the sources while reconstructing the method.",

    "da_nominare": "To name",
    "cerca": "Search title, event, word",
    "con_indizi": "Only with clues",
    "aiuto_con_indizi": "Only the recordings with calendar invitees or with names in the text, the ones to start from.",
    "apri": "Open in Plaud",
    "aiuto_apri": "Opens the note in Plaud in the browser, with the speakers to name.",
    "mostra_altre": "Show more",
    "nessuna": "No recording with these filters.",
    "nel_testo": "In the text",
    "aiuto_nel_testo": "Proper names found in the recording's text. They are clues to look at, not confirmations.",
    "senza_contesto": "No calendar event at that time",
    "una_voce_sola": "Everything on a single speaker, the voices must be split first",
    "aiuto_una_voce_sola": "Plaud put all the speech on a single speaker. Before giving a name you must split who "
    "speaks.",
    "piano": "Where to start",
    "aiuto_piano": "The unnamed speakers split by the evidence we have, in the order naming begins.",
    "col_gruppo": "Group",
    "col_come": "What it's based on",
    "col_voci": "Speakers",
    "col_ore": "Hours",
    "totale": "In all",

    "piu_lunghe_fuori": "The longest outside the base",
    "aiuto_piu_lunghe_fuori": "The longest recordings the knowledge base has no fact for yet.",

    "in_breve": "In short",
    "fatti": "The facts",
    "prova": "Evidence",
    "aperto": "What stays open",
    "conseguenza": "What it means",

    "attivita": "The work plan",
    "aiuto_attivita": "The project's steps, with what is already done and what is waiting for you.",

    "rileggi": "Re-read",
    "aiuto_rileggi": "Re-reads the Plaud measures from the last round.",
}


STATI_ATTIVITA = {
    "fatto": ("done", "verde"),
    "in corso": ("in progress", "blu"),
    "da fare": ("to do", "grigio"),
    "aspetta te": ("waiting for you", "arancio"),
}

AIUTO_LIVELLI = {
    "confermato": "You said who it is.",
    "solido": "At least two independent pieces of evidence, calendar, text or voice, and no signal against.",
    "una prova": "A single piece of evidence and no signal against.",
    "solo nome": "The name is there but no evidence supports it.",
    "sospetto": "At least one signal against, for example the same name on several speakers or the text calling that "
    "speaker another way.",
    "smentito": "You said that speaker is someone else.",
    "senza nome": "Still «Speaker 1, 2, 3», no name.",
}

TIPI = {
    "registratore": "recorder",
    "app": "from the phone or Mac",
    "audio importato": "imported audio",
    "esempio di Plaud": "Plaud example",
}





def _n(x: float | int | None) -> str:
    ""
    return f"{round(x or 0):,}".replace(",", ".")


def _pct(x: float | int | None) -> str:
    return f"{_n(x)}%"


def _durata(minuti: float | None) -> str:
    m = round(minuti or 0)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def _giorno(iso: str | None) -> str:
    ""
    try:
        d = datetime.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return iso or ""
    return d.strftime("%d/%m/%Y")


def _ora(iso: str | None) -> str:
    ""
    if not iso or "T" not in iso:
        return ""
    try:
        t = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{t.hour}:{t.minute:02d}"


def _quando_giro(iso: str | None, oggi: datetime.date | None = None) -> str:
    ""
    try:
        t = datetime.datetime.fromisoformat(iso or "")
    except ValueError:
        return iso or ""
    oggi = oggi or datetime.date.today()
    ora = f"{t.hour}:{t.minute:02d}"
    if t.date() == oggi:
        return f"today at {ora}"
    if t.date() == oggi - datetime.timedelta(days=1):
        return f"yesterday at {ora}"
    return f"on {t.day}/{t.month:02d} at {ora}"


def _mese(chiave: str, intero: bool = False) -> str:
    ""
    try:
        anno, mese = chiave.split("-")
        i = int(mese) - 1
        return f"{MESI_INTERI[i]} {anno}" if intero else f"{MESI[i]} {anno[2:]}"
    except (ValueError, IndexError):
        return chiave


_TESTA_TITOLO = re.compile(r"^(\d\d)-(\d\d)\s+")


def _titolo(titolo: str | None, data: str | None) -> str:
    ""
    t = (titolo or "").strip()
    m = _TESTA_TITOLO.match(t)
    if m and data and data[5:7] == m.group(1) and data[8:10] == m.group(2):
        t = t[m.end() :]
    return t or "Untitled recording"


def _contesto(c: dict | None) -> str:
    ""
    c = c or {}
    pezzi = []
    eventi = []
    for e in c.get("eventi") or []:
        e = (e or "").strip()
        if e and e not in eventi:
            eventi.append(e)
    if eventi:
        dentro = ", ".join(f"«{e}»" for e in eventi[:3])
        altri = len(eventi) - 3
        pezzi.append(f"In calendar {dentro}" + (f" and {altri} more" if altri > 0 else ""))
    invitati = c.get("invitati") or 0
    if invitati:
        pezzi.append("1 invitee" if invitati == 1 else f"{invitati} invitees")
    luoghi = [x.strip() for x in c.get("luogo") or [] if x and x.strip()]
    if luoghi:
        luogo = luoghi[0]
        pezzi.append(luogo if len(luogo) <= 70 else luogo[:68].rstrip(" ,") + "…")
    if c.get("call"):
        pezzi.append("on a call")
    return " · ".join(pezzi)


def _link(id_: str) -> str:
    return LINK_NOTA.format(id=id_)





def _numeri(q: dict) -> list[dict]:
    tot = q.get("totali") or {}
    nomi = q.get("nomi") or {}
    sol = q.get("solidita") or {}
    ver = q.get("veridicita") or {}
    kb = q.get("kb") or {}
    mesi = q.get("per_mese") or []
    dal = f" since {_mese(mesi[0]['mese'], intero=True)}" if mesi else ""
    giuste, verificate = ver.get("giuste") or 0, ver.get("voci_verificate_da_owner") or 0
    return [
        {
            "id": "registrazioni",
            "cifra": _n(tot.get("registrazioni")),
            "parola": "recordings",
            "aiuto": f"All the Plaud recordings read on the Mac{dal}.",
        },
        {
            "id": "ore",
            "cifra": _n(tot.get("ore")),
            "parola": "hours recorded",
            "aiuto": f"{_n(tot.get('minuti_parlato'))} minutes of speech in all.",
        },
        {
            "id": "minuti_senza_nome",
            "cifra": _pct(nomi.get("pct_minuti_senza_nome")),
            "parola": "of the minutes unnamed",
            "aiuto": f"{_n(nomi.get('minuti_senza_nome'))} minutes of {_n(tot.get('minuti_parlato'))} still have "
            "«Speaker 1, 2, 3».",
        },
        {
            "id": "voci_senza_nome",
            "cifra": _n(nomi.get("voci_senza_nome")),
            "parola": "unnamed speakers",
            "aiuto": f"The «Speaker 1, 2, 3» still unnamed. There are {_n(nomi.get('voci_senza_nome'))} of "
            f"{_n(tot.get('voci'))}, and {_n(nomi.get('registrazioni_senza_nessun_nome'))} recordings have "
            "no name at all.",
        },
        {
            "id": "solidi",
            "cifra": _pct(sol.get("pct_solidi_sui_nominati")),
            "parola": "of the names is solid",
            "aiuto": "Minutes with a name confirmed by you or supported by two independent pieces of evidence, out of "
            "the minutes that have a name.",
        },
        {
            "id": "sospetti",
            "cifra": _pct(sol.get("pct_sospetti_sui_nominati")),
            "parola": "of the names is suspect",
            "aiuto": "Minutes with a name that has at least one signal against, or that you denied, out of the minutes "
            "that have a name.",
        },
        {
            "id": "veridicita",
            "cifra": f"{giuste} of {verificate}",
            "parola": "right among the speakers you verified",
            "aiuto": f"Only where you said who it is, {verificate} speakers. Below 50 verifications it is a signal and "
            "not a measure.",
            "segnale": True,
        },
        {
            "id": "fuori_kb",
            "cifra": _n(kb.get("registrazioni_fuori")),
            "parola": "outside the knowledge base",
            "aiuto": f"{_n(kb.get('ore_fuori'))} hours of recordings the knowledge base has no facts for. "
            f"The last entry is from {_giorno(kb.get('ultima_registrazione_nel_kb'))}.",
        },
    ]


def _indizi(q: dict) -> list[dict]:
    ""
    out = []
    for i, x in enumerate(q.get("indizi") or []):
        giusti, sbagliati = x.get("giusti") or 0, x.get("sbagliati") or 0
        out.append(
            {
                "id": x.get("chiave") or str(i),
                "indizio": x.get("indizio") or "",
                "perche": x.get("perche_partenza") or "",
                "partenza": _pct(100 * (x.get("partenza") or 0)),
                "giusti": _n(giusti),
                "sbagliati": _n(sbagliati),
                "peso": _pct(100 * (x.get("punteggio") or 0)),
                "valore": x.get("punteggio") or 0,
                "verificato": bool(giusti or sbagliati),
            }
        )
    return out


def _fiducia(q: dict) -> list[dict]:
    ""
    f = q.get("fiducia_nomi") or {}
    totale = sum(v or 0 for v in f.values()) or 1
    return [
        {
            "id": str(i),
            "fascia": k,
            "speaker": f"{_n(v)} speaker",
            "frazione": round((v or 0) / totale, 4),
            "livello": i,
        }
        for i, (k, v) in enumerate(f.items())
    ]


def _livelli(q: dict) -> list[dict]:
    lv = (q.get("solidita") or {}).get("livelli") or {}
    totale = sum((lv.get(k) or {}).get("minuti") or 0 for k in LIVELLI) or 1
    out = []
    for k in LIVELLI:
        v = lv.get(k) or {}
        minuti = v.get("minuti") or 0
        voci = v.get("voci") or 0
        out.append(
            {
                "id": k.replace(" ", "_"),
                "nome": k,
                "minuti": minuti,
                "voci": voci,
                "frazione": round(minuti / totale, 4),
                "cifre": f"{_n(minuti)} min · {_n(voci)} speaker",
                "pct": _pct(100 * minuti / totale)
                if minuti / totale >= 0.01 or not minuti
                else "less than 1%",
                "aiuto": AIUTO_LIVELLI[k],
            }
        )
    return out


def _mesi(q: dict) -> list[dict]:
    out = []
    for m in q.get("per_mese") or []:
        out.append(
            {
                "id": m["mese"],
                "etichetta": _mese(m["mese"]),
                "pct_senza_nome": m.get("pct_senza_nome") or 0,
                "pct_solidi": m.get("pct_solidi") or 0,
                "aiuto": f"{_mese(m['mese'], intero=True).capitalize()}. {_n(m.get('registrazioni'))} recordings, "
                f"{_n(m.get('ore'))} hours. Unnamed {_pct(m.get('pct_senza_nome'))} of the minutes, solid "
                f"{_pct(m.get('pct_solidi'))}.",
            }
        )
    return out


def _storia(q: dict, oggi: datetime.date | None = None) -> list[dict]:
    giri = list(q.get("storia") or [])
    out = []
    for i, g in enumerate(giri):
        prima = giri[i - 1] if i > 0 else None
        if prima is None:
            confronto = "First round, the starting point."
        else:

            pezzi = []
            for chiave, nome in (
                ("pct_minuti_senza_nome", "the unnamed minutes"),
                ("pct_solidi_sui_nominati", "the solid ones"),
                ("pct_sospetti_sui_nominati", "the suspect ones"),
            ):
                a, b = prima.get(chiave), g.get(chiave)
                if a is not None and b is not None and a != b:
                    pezzi.append(f"{nome} are {_pct(b)}, were {_pct(a)}")
            a, b = prima.get("verificate_da_owner"), g.get("verificate_da_owner")
            if a is not None and b is not None and a != b:
                pezzi.append(f"the ones verified by you are {_n(b)}, were {_n(a)}")

            a, b = prima.get("registrazioni_fuori_kb"), g.get("registrazioni_fuori_kb")
            if a is not None and b is not None and a != b:
                pezzi.append(f"the recordings outside the base are {_n(b)}, were {_n(a)}")
            if pezzi:
                frasi = [f"Compared to the previous round {pezzi[0]}."] + [
                    x[0].upper() + x[1:] + "." for x in pezzi[1:]
                ]
                confronto = " ".join(frasi)
            else:
                confronto = UGUALE
        out.append(
            {
                "id": g.get("quando") or str(i),
                "quando": _quando_giro(g.get("quando"), oggi),
                "senza_nome": _pct(g.get("pct_minuti_senza_nome")),
                "solidi": _pct(g.get("pct_solidi_sui_nominati")),
                "sospetti": _pct(g.get("pct_sospetti_sui_nominati")),
                "verificate": _n(g.get("verificate_da_owner")),
                "fuori": _n(g.get("registrazioni_fuori_kb")),
                "confronto": confronto,
            }
        )

    return list(reversed(out))


UGUALE = "Same as the previous round."


def _storia_app(q: dict, oggi: datetime.date | None) -> dict:
    storia = _storia(q, oggi)
    tenuti, altri = _storia_breve(storia)
    return {"storia": tenuti, "storia_giri": len(storia), "storia_altri": altri}


def _storia_breve(storia: list[dict]) -> tuple[list[dict], str]:
    ""
    tenuti = [
        g for i, g in enumerate(storia) if i in (0, len(storia) - 1) or g["confronto"] != UGUALE
    ]
    altri = len(storia) - len(tenuti)
    if not altri:
        return tenuti, ""
    return tenuti, "And one more identical round." if altri == 1 else f"And {altri} more identical rounds."


def _riga_registrazione(r: dict) -> dict:
    voci, senza = r.get("voci") or 0, r.get("voci_senza_nome") or 0
    indizi = [x for x in r.get("indizi") or [] if x]
    contesto = r.get("contesto") or {}
    numeri = f"{_n(r.get('minuti_senza_nome'))} min unnamed · {senza} speakers of {voci}"
    ora = _ora(r.get("inizio"))
    return {
        "id": r["id"],
        "titolo": _titolo(r.get("titolo"), r.get("data")),
        "data": _giorno(r.get("data")) + (f" at {ora}" if ora else ""),
        "giorno": (r.get("data") or "")[:10],
        "durata": _durata(r.get("durata_min")),
        "minuti_senza_nome": round(r.get("minuti_senza_nome") or 0),
        "numeri": numeri,
        "contesto": _contesto(contesto),
        "indizi": ", ".join(indizi),

        "con_indizi": bool(contesto.get("invitati") or indizi),

        "una_voce_sola": bool(r.get("una_voce_sola")),
        "fonte": TIPI.get(r.get("tipo") or "", "altro"),
        "link": _link(r["id"]),
    }


def _da_nominare(q: dict) -> dict:
    righe = [_riga_registrazione(r) for r in q.get("mancano") or [] if r.get("id")]
    righe.sort(key=lambda r: (-r["minuti_senza_nome"], r["giorno"]), reverse=False)
    con_indizi = sum(1 for r in righe if r["con_indizi"])
    tot = (q.get("totali") or {}).get("registrazioni") or 0
    c = q.get("contesto") or {}
    nomi = q.get("nomi") or {}
    una_sola = nomi.get("registrazioni_una_voce_sola")
    frase = (
        f"{_n(len(righe))} recordings have at least one unnamed speaker, {_n(con_indizi)} with a clue to start "
        "from. At the top the ones with the most minutes to name."
    )
    if una_sola:
        frase += (
            f" In {_n(una_sola)} recordings, {_n(nomi.get('ore_una_voce_sola'))} hours, Plaud put everything on a "
            "single speaker."
        )
    gruppi = q.get("piano_nomi") or []
    piano = [
        {
            "id": str(i),
            "gruppo": g.get("gruppo") or "",
            "come": g.get("come") or "",
            "voci": _n(g.get("voci")),
            "ore": _n(g.get("ore")),
        }
        for i, g in enumerate(gruppi)
    ]
    piano_totale = {
        "voci": _n(sum(g.get("voci") or 0 for g in gruppi)),
        "ore": _n(sum(g.get("ore") or 0 for g in gruppi)),
    }
    return {
        "piano": piano,
        "piano_totale": piano_totale,
        "totale": len(righe),
        "con_indizi": con_indizi,
        "frase": frase,
        "contesto": f"The context reconstructed over the {_n(tot)} recordings. {_n(c.get('con_evento'))} have a "
        f"calendar event at that time, {_n(c.get('con_invitati'))} have invitees, {_n(c.get('con_luogo'))} a "
        f"location, {_n(c.get('in_call'))} were on a call.",
        "righe": righe,
    }


def _fuori(q: dict) -> dict:
    kb = q.get("kb") or {}
    righe = []
    for r in kb.get("piu_lunghe_fuori") or []:
        if not r.get("id"):
            continue
        righe.append(
            {
                "id": r["id"],
                "titolo": _titolo(r.get("titolo"), r.get("data")),
                "data": _giorno(r.get("data")),
                "durata": _durata(r.get("durata_min")),
                "numeri": f"{_n(r.get('minuti_senza_nome'))} min unnamed",
                "contesto": _contesto(r.get("contesto")),
                "link": _link(r["id"]),
            }
        )
    return {
        "numeri": [
            {
                "id": "dentro",
                "cifra": _n(kb.get("registrazioni_con_fatti")),
                "parola": "recordings with facts in the base",
                "aiuto": "Recordings the knowledge base has already pulled at least one fact from.",
            },
            {
                "id": "fuori",
                "cifra": _n(kb.get("registrazioni_fuori")),
                "parola": "recordings outside",
                "aiuto": "Recordings the knowledge base has no fact for.",
            },
            {
                "id": "ore_fuori",
                "cifra": _n(kb.get("ore_fuori")),
                "parola": "hours outside",
                "aiuto": "The hours of recording the knowledge base has not read yet.",
            },
            {
                "id": "ultima",
                "cifra": _giorno(kb.get("ultima_registrazione_nel_kb")),
                "parola": "the last entry in the base",
                "aiuto": "The most recent recording that has facts in the knowledge base. The later ones stay outside "
                "until the base's stages run.",
            },
        ],
        "frase": f"The knowledge base has the facts of {_n(kb.get('registrazioni_con_fatti'))} recordings. The other "
        f"{_n(kb.get('registrazioni_fuori'))} stay outside, and the last entry is from "
        f"{_giorno(kb.get('ultima_registrazione_nel_kb'))}.",
        "righe": righe,
    }


def _perche(q: dict) -> dict:
    p = q.get("perche") or {}
    agg = p.get("aggiornato")
    return {
        "aggiornato": f"Updated on {_giorno(agg)}" if agg else "",
        "in_breve": p.get("in_breve") or "",
        "fatti": [
            {"cosa": f.get("cosa") or "", "prova": f.get("prova") or ""}
            for f in p.get("fatti") or []
            if f.get("cosa")
        ],
        "aperto": [x for x in p.get("cosa_resta_aperto") or [] if x],
        "conseguenza": p.get("conseguenza") or "",
    }


def _metodo(q: dict) -> dict:
    ""
    m = q.get("metodo") or {}
    passi = []
    for i, x in enumerate(m.get("passi") or []):
        parole = (x.get("parole") or "").strip()
        if parole and not parole.startswith("«"):
            parole = f"«{parole}»"
        passi.append(
            {
                "id": str(x.get("n") or i + 1),
                "n": x.get("n") or i + 1,
                "passo": x.get("passo") or "",
                "parole": parole,
                "quando": x.get("quando") or "",
            }
        )
    agg = m.get("aggiornato")
    return {
        "aggiornato": f"Updated on {_giorno(agg)}" if agg else "",
        "in_breve": m.get("in_breve") or "",
        "passi": passi,
        "scoperte": [x for x in m.get("scoperte") or [] if x],
    }


def _attivita(q: dict) -> list[dict]:
    out = []
    for a in q.get("attivita") or []:
        stato = (a.get("stato") or "da fare").strip()
        parola, tinta = STATI_ATTIVITA.get(stato, (stato, "grigio"))
        out.append(
            {
                "id": str(a.get("n") or len(out) + 1),
                "n": a.get("n") or len(out) + 1,
                "cosa": a.get("cosa") or "",
                "stato": parola,
                "tinta": tinta,
                "quando": _giorno(a.get("quando")) if a.get("quando") else "",
                "esito": a.get("esito") or "",
            }
        )
    return out


def stato(oggi: datetime.date | None = None) -> dict:
    ""
    try:
        q = json.loads(QUADRO.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "ok": False,
            "errore": "The Plaud measures do not exist yet. They are born with the first measurement round.",
            "testi": TESTI,
        }
    except (OSError, ValueError) as e:

        print(f"sb_plaud: the overview cannot be read, {type(e).__name__}: {e}", file=sys.stderr)
        return {
            "ok": False,
            "errore": "The Plaud measures cannot be read. Try again with Re-read.",
            "testi": TESTI,
        }
    ob = q.get("obiettivo") or {}
    da_nominare = _da_nominare(q)
    fuori = _fuori(q)
    attivita = _attivita(q)
    return {
        "ok": True,
        "generato": q.get("generato") or "",
        "letto": f"Measures from {_quando_giro(q.get('generato'), oggi)}" if q.get("generato") else "",
        "obiettivo": {
            "frase": ob.get("frase") or "",
            "parole_di_owner": ob.get("parole_di_owner") or "",
            "metodo": ob.get("metodo") or "",
        },
        "moduli": [
            {
                "id": "quadro",
                "nome": TESTI["modulo_quadro"],
                "conteggio": "",
                "aiuto": TESTI["aiuto_modulo_quadro"],
            },
            {
                "id": "metodo",
                "nome": TESTI["modulo_metodo"],
                "conteggio": "",
                "aiuto": TESTI["aiuto_modulo_metodo"],
            },
            {
                "id": "da_nominare",
                "nome": TESTI["modulo_da_nominare"],
                "conteggio": _n(da_nominare["totale"]),
                "aiuto": TESTI["aiuto_modulo_da_nominare"],
            },
            {
                "id": "fuori",
                "nome": TESTI["modulo_fuori"],
                "conteggio": _n((q.get("kb") or {}).get("registrazioni_fuori")),
                "aiuto": TESTI["aiuto_modulo_fuori"],
            },
            {
                "id": "perche",
                "nome": TESTI["modulo_perche"],
                "conteggio": "",
                "aiuto": TESTI["aiuto_modulo_perche"],
            },
            {
                "id": "attivita",
                "nome": TESTI["modulo_attivita"],
                "conteggio": _n(len(attivita)),
                "aiuto": TESTI["aiuto_modulo_attivita"],
            },
        ],
        "numeri": _numeri(q),
        "livelli": _livelli(q),
        "indizi": _indizi(q),
        "fiducia": _fiducia(q),
        "mesi": _mesi(q),
        **_storia_app(q, oggi),
        "da_nominare": da_nominare,
        "fuori": fuori,
        "perche": _perche(q),
        "metodo": _metodo(q),
        "attivita": attivita,
        "testi": TESTI,
    }


def per_app() -> dict:
    return stato()


def main(argv: list[str]) -> int:
    if argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if argv[1:2] == ["json"]:
        print(json.dumps(stato(), ensure_ascii=False))
        return 0
    print("usage: sb_plaud.py json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
