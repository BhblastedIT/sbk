#!/usr/bin/env python3
"""Mirrors the SecondBrain tasks into a list in Apple Reminders, and brings back what you did on the phone.

The tasks engine (sb_attivita.py) stays the source. The Swift helper promemoria/SBPromemoria.swift reads and
writes Reminders (it holds the macOS permission); this module decides. Checking a reminder closes the task,
unchecking reopens it, a new reminder in the list becomes a new task; everything else follows the engine.

Usage (the Swift helper calls it; by hand only to look), JSON on stdin:
    sb_promemoria.py piano < reminders.json     apply your phone changes, print the operations that realign the list
    sb_promemoria.py prova < reminders.json     the same plan, writing nothing
    sb_promemoria.py registra < written.json    save the ids of what the helper wrote
"""






















from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb_attivita as A  # noqa: E402

LISTA = "SBK"
URL = "secondbrain://attivita/"
DA = "promemoria"
NOTE_MAX = 600



PRIORITA_EK = {0: 1, 1: 1, 2: 5, 3: 9}


def _classe(p) -> int:
    ""
    try:
        p = int(p or 0)
    except (TypeError, ValueError):
        return 0
    return 0 if p <= 0 else 1 if p <= 4 else 2 if p == 5 else 3


PREFISSO = re.compile(r"^\s*[Pp]\s*([0-3])\s*[·.:\-–—]?\s*")


def _file_stato() -> Path:
    return A.CARTELLA / "promemoria.json"


def _leggi_stato() -> dict:
    try:
        d = json.loads(_file_stato().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("task"), dict) else {"task": {}}
    except (OSError, ValueError):
        return {"task": {}}


def _scrivi_stato(d: dict) -> None:
    p = _file_stato()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _data(v) -> str | None:
    s = str(v or "")[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def voluto(t: dict, imp: dict) -> dict:
    ""
    p = t.get("priorita")
    p = p if p in PRIORITA_EK else 3
    stato = A._stato_di(imp, t.get("stato"))
    righe = [" · ".join(x for x in (t.get("area"), stato.get("nome")) if x)]
    stima = t.get("stima")
    if isinstance(stima, int) and stima > 0:
        righe[0] += " · " + A.stima_frase(stima)
    desc = (t.get("descrizione") or "").strip()
    if desc:
        righe.append(desc if len(desc) <= NOTE_MAX else desc[: NOTE_MAX - 1].rstrip() + "…")
    return {
        "titolo": f"P{p} · {(t.get('titolo') or '').strip()}",
        "note": "\n\n".join(r for r in righe if r),
        "priorita": PRIORITA_EK[p],
        "scadenza": _data(t.get("scadenza")),
        "fatto": bool(A._chiuso(imp, t.get("stato"))),
    }


def _uguale(r: dict, v: dict) -> bool:
    return (
        (r.get("titolo") or "") == v["titolo"]
        and (r.get("note") or "") == v["note"]
        and _classe(r.get("priorita")) == _classe(v["priorita"])
        and (r.get("scadenza") or None) == v["scadenza"]
        and bool(r.get("fatto")) == v["fatto"]
    )


def _chiave_di(r: dict, per_est: dict, per_id: dict) -> str | None:
    url = r.get("url") or ""
    if url.startswith(URL):
        return url[len(URL) :] or None
    return per_est.get(r.get("est") or "") or per_id.get(r.get("id") or "")


def _titolo_dal_telefono(testo: str) -> tuple[str, int | None]:
    m = PREFISSO.match(testo or "")
    if m:
        return testo[m.end() :].strip(), int(m.group(1))
    return (testo or "").strip(), None


def piano(attuali: list[dict], scrivi: bool = True) -> dict:
    ""
    stato = _leggi_stato()
    mappa = stato["task"]
    per_est = {v.get("est"): k for k, v in mappa.items() if v.get("est")}
    per_id = {v.get("id"): k for k, v in mappa.items() if v.get("id")}
    imp = A._imp()
    tutte = A._carica()
    gesti, legati = [], {}

    for r in attuali:
        tid = _chiave_di(r, per_est, per_id)
        if tid is None:
            titolo, p = _titolo_dal_telefono(r.get("titolo") or "")
            if not titolo or r.get("fatto"):
                continue
            campi = {"titolo": titolo} if p is None else {"titolo": titolo, "priorita": p}
            if _data(r.get("scadenza")):
                campi["scadenza"] = _data(r.get("scadenza"))
            gesti.append({"gesto": "nuova", "titolo": titolo, "promemoria": r.get("id")})
            if scrivi:
                tid = A.crea(campi, da=DA)
                legati[tid] = r
            continue
        legati[tid] = r
        t = tutte.get(tid)
        if t is None or t.get("eliminata"):
            continue
        scritto = (mappa.get(tid) or {}).get("scritto") or {}
        if "fatto" not in scritto or bool(r.get("fatto")) == bool(scritto["fatto"]):
            continue
        chiusa = bool(A._chiuso(imp, t.get("stato")))
        if chiusa != bool(scritto["fatto"]):
            continue
        gesto = "fatta" if r.get("fatto") else "riapri"
        if gesto == "fatta" and chiusa or gesto == "riapri" and not chiusa:
            continue
        gesti.append({"gesto": gesto, "task": tid})
        if scrivi:
            (A._verbo_fatta if gesto == "fatta" else A._verbo_riapri)(tid)

    if scrivi and gesti:
        tutte = A._carica()
        imp = A._imp()
    per_id_attuale = {r.get("id"): r for r in attuali if r.get("id")}
    ops = []
    for tid, t in tutte.items():
        if t.get("eliminata"):
            continue
        chiusa = bool(A._chiuso(imp, t.get("stato")))
        r = legati.get(tid)
        if r is None:
            ricordato = mappa.get(tid) or {}
            r = per_id_attuale.get(ricordato.get("id"))
        if chiusa and r is None and tid not in mappa:
            continue
        v = voluto(t, imp)
        if r is not None and _uguale(r, v) and (r.get("url") or "") == URL + tid:
            continue
        ops.append(
            {"op": "metti", "id": r.get("id") if r else None, "chiave": tid, "url": URL + tid, **v}
        )
    vive = {tid for tid, t in tutte.items() if not t.get("eliminata")}
    for r in attuali:
        tid = _chiave_di(r, per_est, per_id) or next((k for k, x in legati.items() if x is r), None)
        if tid is not None and tid not in vive:
            ops.append({"op": "togli", "id": r.get("id"), "chiave": tid})
    return {"ops": ops, "gesti": gesti}


def registra(risultati: list[dict]) -> dict:
    ""
    stato = _leggi_stato()
    mappa = stato["task"]
    ok = 0
    for x in risultati:
        tid = x.get("chiave")
        if not tid or x.get("esito") != "ok":
            continue
        ok += 1
        if x.get("op") == "togli":
            mappa.pop(tid, None)
            continue
        mappa[tid] = {
            "id": x.get("id"),
            "est": x.get("est"),
            "scritto": {k: x.get(k) for k in ("titolo", "note", "priorita", "scadenza", "fatto")},
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    _scrivi_stato(stato)
    return {"registrati": ok, "abbinate": len(mappa)}


def allinea_letti(attuali: list[dict]) -> None:
    ""
    stato = _leggi_stato()
    mappa = stato["task"]
    cambiato = False
    for r in attuali:
        url = r.get("url") or ""
        if not url.startswith(URL):
            continue
        tid = url[len(URL) :]
        m = mappa.setdefault(tid, {})
        for k in ("id", "est"):
            if r.get(k) and m.get(k) != r.get(k):
                m[k] = r.get(k)
                cambiato = True
        if "scritto" not in m:
            m["scritto"] = {
                k: r.get(k) for k in ("titolo", "note", "priorita", "scadenza", "fatto")
            }
            cambiato = True
    if cambiato:
        _scrivi_stato(stato)


def main(argv: list[str]) -> int:
    verbo = argv[1] if len(argv) > 1 else ""
    if verbo in ("-h", "--help"):
        print(__doc__)
        return 0
    if verbo not in ("piano", "prova", "registra"):
        print(__doc__)
        return 2
    dati = json.loads(sys.stdin.read() or "[]")
    if verbo in ("piano", "prova"):
        allinea_letti(dati) if verbo == "piano" else None
        print(json.dumps(piano(dati, scrivi=verbo == "piano"), ensure_ascii=False))
        return 0
    if verbo == "registra":
        print(json.dumps(registra(dati), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    os.environ.setdefault("SB_ATTIVITA_DA", DA)
    sys.exit(main(sys.argv))
