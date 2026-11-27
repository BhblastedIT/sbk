#!/usr/bin/env python3
"""Plaud check batch: pick voices for you to confirm (--new) and record your answer to one of them (--answer N TEXT)."""


























from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.plaud.regole.nomi import OWNER_CANONICO  # noqa: E402

DATA = Path(
    os.environ.get("SBK_DATA") or os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data"
).expanduser()
RAW = DATA / "plaud" / "raw"
QUADRO = DATA / "plaud" / "quadro"
LOTTO = QUADRO / "lotto-verifiche.json"
CONFERME = QUADRO / "conferme-owner.jsonl"
PROPOSTE = QUADRO / "proposte.json"

# You, from sbk.config.json "owner" (normalised like the Plaud rules do).
OWNER = OWNER_CANONICO


MINUTI_MAX_REGISTRAZIONE = 180
MINUTI_MIN_VOCE = 0.5
SLOT_OK = re.compile(r"^Speaker \d+$")


BLOCCHI = [
    ("tua voce", 20, "Is this your voice?"),
    ("seconda voce", 4, "Is this also your voice? You are already on another voice in the recording"),
    ("altre persone", 20, "Who is speaking? Pick 1, 2 or 3, or type the name"),
    ("etichetta Plaud", 6, "Plaud says it is this person. Is that right?"),
]

SI = re.compile(r"^(si|sì|ok|giusto|esatto|corretto|è lui|è lei|e' lui|e' lei)\b", re.I)
NON_SO = re.compile(r"^(non so|non lo so|boh|forse|non ricordo|non saprei)\b", re.I)
NON_CERA = re.compile(r"non (c'era|c’era|era presente|era li|era lì)", re.I)
MISTA = re.compile(
    r"(voce mista|più persone|piu' persone|piu persone|parlano in due|due persone)", re.I
)
NO_E = re.compile(r"^(no[,.]?\s*)?(è|e'|é)\s+(.+)$", re.I)



PROVA = {
    "fisso": "is the name the voice already has",
    "R1:calendario-titolo": "their name is in the event title",
    "R1:calendario": "was invited to the event at that time",
    "R1:email-invito": "email invite at that time",
    "R1:gemello": "the call also recorded by Tactiq, Attio or Meet places them on this voice",
    "R1:slack": "Slack messages shortly before",
    "R1:titolo": "the name is in the recording title",
    "R1:wa-chiamata": "WhatsApp call at the same time",
    "R1:wa-messaggi": "WhatsApp messages shortly before or after",
    "R2:vocativo": "is called by name",
    "R2:presentazione": "introduces themselves by name",
    "R2:owner_testo": "your phrases, or someone calls you by name",
    "R2:ruolo_owner": "asks more questions and talks more",
    "R2:file_spezzati": "same conversation split into two files",
    "R3:quota": "talks as much as this person usually does",
    "R3:tema": "their topics are being discussed",
    "R3:rete": "you heard them in the previous 14 days",
    "R3:copresenza": "often appears with the people in this recording",
    "R3:stesso-giorno": "is in another recording from the same day",
    "R3:luogo": "you were in the same city",
    "R3:titolo": "title almost identical to another recording with them",
}


def prova(spinta: dict) -> str:
    g = spinta.get("gruppo") or ""
    return PROVA.get(g if g == "fisso" else g.rsplit(":", 1)[0], "")


def bello(nome: str | None) -> str:
    return " ".join(p.capitalize() for p in (nome or "").split())


def mappa_json() -> dict[str, Path]:
    out = {}
    for t in RAW.glob("*.txt"):
        m = re.search(r"# ID:\s*(\S+)", t.open(errors="ignore").read(400))
        if m and t.with_suffix(".json").exists():
            out[m.group(1)] = t.with_suffix(".json")
    return out


def prima_frase(segs: list[dict], slot: str) -> tuple[str, str]:
    ""
    primo = None
    for s in segs:
        if (s.get("original_speaker") or s.get("speaker")) != slot:
            continue
        testo = (s.get("content") or "").strip()
        if primo is None:
            primo = s
        if len(testo.split()) >= 8:
            primo = s
            break
    if not primo:
        return "", ""
    ms = int(primo.get("start_time") or 0)
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}", (primo.get("content") or "").strip()[:220]


def _scrivi(p: Path, doc: dict) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    tmp.replace(p)


def _gia_confermate() -> set[tuple[str, str]]:
    gia = set()
    if CONFERME.exists():
        for line in CONFERME.read_text().splitlines():
            try:
                c = json.loads(line)
                gia.add((c["file_id"], c["slot"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return gia


def _fascia(f: float, lo: float, hi: float) -> bool:
    return lo <= f < hi


def scegli(
    proposte: list[dict], regs: dict[str, dict], gia: set, quante: int, seme: str
) -> list[tuple[str, dict]]:
    ""
    rnd = random.Random(seme)
    scala = quante / 50

    def ok(v: dict) -> bool:
        r = regs.get(v["file_id"])
        return (
            r is not None
            and (r.get("durata_min") or 0) < MINUTI_MAX_REGISTRAZIONE
            and len(r.get("voci") or []) >= 2
            and SLOT_OK.match(v["slot"] or "") is not None
            and (v.get("minuti") or 0) >= MINUTI_MIN_VOCE
            and (v["file_id"], v["slot"]) not in gia
            and not v.get("confermato_da_owner")
        )

    vv = [v for v in proposte if ok(v) and (v.get("proposta") or {}).get("nome")]
    senza = [v for v in vv if v["classe"] in ("generico", "non-nome")]
    owner_su: dict[str, int] = {}
    for v in proposte:
        if (v.get("proposta") or {}).get("nome") == OWNER or v["classe"] == "owner":
            owner_su[v["file_id"]] = owner_su.get(v["file_id"], 0) + 1

    presi: list[tuple[str, dict]] = []
    visti: set[tuple[str, str]] = set()

    def metti(blocco: str, lista: list[dict], n: int) -> None:
        lista = [v for v in lista if (v["file_id"], v["slot"]) not in visti]
        rnd.shuffle(lista)
        for v in lista[: max(0, round(n))]:
            visti.add((v["file_id"], v["slot"]))
            presi.append((blocco, v))

    f = lambda v: v["proposta"]["fiducia"]  # noqa: E731
    owner = [v for v in senza if v["proposta"]["nome"] == OWNER]
    owner_unico = [v for v in owner if owner_su.get(v["file_id"], 0) <= 1]

    auto_owner = [v for v in owner_unico if v["lane"] == "AUTO"]
    metti("tua voce", auto_owner, min(len(auto_owner), 11 * scala))
    resto = 20 * scala - len(presi)
    for lo, hi in ((0.9, 1.01), (0.8, 0.9), (0.5, 0.8)):
        metti(
            "tua voce",
            [v for v in owner_unico if v["lane"] != "AUTO" and _fascia(f(v), lo, hi)],
            resto / 3,
        )

    metti("seconda voce", [v for v in owner if owner_su.get(v["file_id"], 0) >= 2], 4 * scala)

    altri = [v for v in vv if v["proposta"]["nome"] != OWNER]
    n0 = len(presi)
    metti(
        "altre persone",
        [v for v in altri if v["lane"] == "AUTO" and v.get("concorda_con_etichetta") is not True],
        5 * scala,
    )
    altri_senza = [v for v in altri if v["classe"] in ("generico", "non-nome")]
    resto = 20 * scala - (len(presi) - n0)
    for lo, hi, peso in ((0.7, 1.01, 0.47), (0.5, 0.7, 0.33), (0.0, 0.5, 0.2)):
        metti(
            "altre persone",
            [v for v in altri_senza if v["lane"] != "AUTO" and _fascia(f(v), lo, hi)],
            resto * peso,
        )

    metti(
        "etichetta Plaud",
        [
            v
            for v in vv
            if v["classe"] == "nome"
            and v.get("provenienza") == "Plaud o il proprietario"
            and (v.get("minuti") or 0) >= 1
        ],
        6 * scala,
    )
    while (
        len(presi) > quante
    ):
        i = max(i for i, (b, _) in enumerate(presi) if b == "tua voce")
        presi.pop(i)
    return presi


def nuovo(quante: int) -> None:
    q = json.loads((QUADRO / "quadro.json").read_text())
    regs = {r["id"]: r for r in q["registrazioni"]}
    doc = json.loads(PROPOSTE.read_text())
    if LOTTO.exists():
        vecchio = json.loads(LOTTO.read_text())
        LOTTO.with_name(
            f"lotto-verifiche-{(vecchio.get('creato') or 'vecchio')[:10]}-{len(vecchio.get('voci', []))}.json"
        ).write_text(LOTTO.read_text())
    oggi = dt.date.today().isoformat()
    presi = scegli(doc["voci"], regs, _gia_confermate(), quante, oggi)
    id2 = mappa_json()
    domande = {b: d for b, _, d in BLOCCHI}
    ordine = {b: i for i, (b, _, _) in enumerate(BLOCCHI)}
    presi.sort(key=lambda x: (ordine[x[0]], -x[1]["proposta"]["fiducia"]))
    voci = []
    for blocco, v in presi:
        r = regs[v["file_id"]]
        minuto, frase = ("", "")
        if v["file_id"] in id2:
            minuto, frase = prima_frase(json.loads(id2[v["file_id"]].read_text()), v["slot"])
        p = v["proposta"]
        nome = v["etichetta"] if blocco == "etichetta Plaud" else p["nome"]
        scelte = []
        if blocco == "altre persone":
            scelte = [bello(x["nome"]) for x in p.get("primi") or [] if x["nome"] != OWNER][:3]
            if bello(p["nome"]) not in scelte:
                scelte = [bello(p["nome"])] + scelte[:2]
        prove = list(dict.fromkeys(x for x in (prova(sp) for sp in p.get("spinte") or []) if x))[:2]
        voci.append(
            {
                "n": len(voci) + 1,
                "blocco": blocco,
                "domanda": domande[blocco],
                "file_id": v["file_id"],
                "slot": v["slot"],
                "nome_proposto": bello(nome),
                "nome_proposto_norm": p["nome"] if blocco != "etichetta Plaud" else nome,
                "scelte": scelte,
                "fiducia": p["fiducia"],
                "corsia": v["lane"],
                "etichetta_attuale": v.get("etichetta") or "",
                "perche_scelta": f"{blocco}, lane {v['lane'].lower()}, confidence {round(100 * p['fiducia'])}%",
                "prove": [x for x in prove if x],
                "titolo": r["titolo"],
                "inizio": r.get("inizio") or r.get("data"),
                "durata_min": r["durata_min"],
                "minuti_voce": v["minuti"],
                "minuto": minuto,
                "frase": frase,
                "contesto": r.get("contesto") or {},
                "link": f"https://web.plaud.ai/file/{v['file_id']}",
                "risposta": None,
            }
        )
    _scrivi(
        LOTTO,
        {
            "creato": dt.datetime.now().isoformat(timespec="minutes"),
            "da": "judgment proposals",
            "voci": voci,
        },
    )
    from collections import Counter

    print(f"batch of {len(voci)} items in {LOTTO}", dict(Counter(x["blocco"] for x in voci)))


def interpreta(v: dict, testo: str) -> dict | None:
    ""
    t = testo.strip()
    proposto = v.get("nome_proposto_norm") or v["nome_proposto"]
    if NON_SO.match(t):
        return {"non_so": True}
    if MISTA.search(t):
        return {"voce_mista": True}
    if NON_CERA.search(t):
        return {"non_e": proposto, "non_c_era": proposto}
    if re.fullmatch(r"[123]", t) and v.get("scelte"):
        i = int(t) - 1
        return {"nome": v["scelte"][i]} if i < len(v["scelte"]) else None
    if SI.match(t):
        return {"nome": proposto}
    m = NO_E.match(t)
    if m:
        altro = m.group(3).strip(" .,")
        return {"non_e": proposto, "nome": altro} if altro else {"non_e": proposto}
    if re.fullmatch(r"no[.!]?", t, re.I):
        return {"non_e": proposto}
    return None


def risposta(n: int, testo: str) -> dict | None:
    lotto = json.loads(LOTTO.read_text())
    v = next(x for x in lotto["voci"] if x["n"] == n)
    conf = interpreta(v, testo)
    if conf is None:
        print(f"I don't understand «{testo}» for item {n}: nothing recorded")
        return None
    riga = {
        "file_id": v["file_id"],
        "slot": v["slot"],
        **conf,
        "quando": dt.date.today().isoformat(),
        "fonte": f"you, verification batch of {lotto['creato'][:10]}, item {n} ({v.get('blocco', '')}): «{testo.strip()}»",
    }
    with CONFERME.open("a") as f:
        f.write(json.dumps(riga, ensure_ascii=False) + "\n")
    v["risposta"] = testo.strip()
    _scrivi(LOTTO, lotto)
    print("recorded", riga)
    return riga


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Plaud check batch"])[0]
    )
    ap.add_argument(
        "--new", dest="nuovo", action="store_true", help="pick a new batch of voices to confirm"
    )
    ap.add_argument(
        "--count",
        dest="quante",
        metavar="N",
        type=int,
        default=50,
        help="how many voices in the batch (default 50)",
    )
    ap.add_argument(
        "--answer",
        dest="risposta",
        nargs=2,
        metavar=("N", "TEXT"),
        help="record your answer to voice N of the batch",
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--nuovo", dest="nuovo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--quante", dest="quante", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--risposta", dest="risposta", nargs=2, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.nuovo:
        nuovo(a.quante)
    if a.risposta:
        risposta(int(a.risposta[0]), a.risposta[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
