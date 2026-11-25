#!/usr/bin/env python3
"""The piece shared by the tasks engine and the phone: the snapshot the Mac publishes and the queue of phone changes.

The engine (sb_attivita.py) stays the only place where a task changes; the phone only reads the snapshot and
queues changes, which the Mac applies one at a time.

Usage:
    sb_telefono.py fotografia [--taglio N]             print the snapshot (descriptions cut at N characters)
    sb_telefono.py giro --mezzo <folder> [--taglio N]  one round through a shared folder: apply the queued
                                                       changes, then publish a new snapshot
    sb_telefono.py prova --mezzo <folder> [--taglio N] the same round on a copy of the tasks, writing nothing
    sb_telefono.py stato --mezzo <folder>              last round, published snapshot and queue of the folder
    sb_telefono.py applica < changes.json              apply phone changes given as JSON on stdin
"""










































from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sb_attivita as A  # noqa: E402


DA = "telefono"

DESCR_MAX = 6000

MODELLO = 1

CAMPI = ("titolo", "stato", "priorita", "scadenza", "stima", "area", "pianificata")

CAMPI_NUOVA = ("descrizione", "priorita", "scadenza", "stato", "stima", "area", "pianificata")
ESITI = ("fatto", "gia_cosi", "gia_arrivato", "superato", "non_ce_piu", "rifiutato")

_PER_INTERO = re.compile(r"^\d{4}-\d{2}-\d{2}")

TESTI = {

    "esito_fatto": "Done.",
    "esito_gia_cosi": "It was already like this.",
    "esito_gia_arrivato": "It had already reached the Mac.",
    "esito_superato": "Not applied, on the Mac it had changed afterwards, {quando}.",
    "esito_superato_telefono": "Not applied, it had changed again from the phone afterwards, {quando}.",
    "esito_non_ce_piu": "This task no longer exists.",

    "perso": "From the phone {quando}, {cosa}. Not applied, on the Mac it had changed afterwards, {quando_dopo}.",
    "perso_senza_ora": "From the phone, {cosa}. Not applied, on the Mac it had changed afterwards, {quando_dopo}.",
    "perso_dal_telefono": "From the phone {quando}, {cosa}. Not applied, it had changed again from the phone afterwards, {quando_dopo}.",
    "perso_dal_telefono_senza_ora": "From the phone, {cosa}. Not applied, it had changed again from the phone afterwards, {quando_dopo}.",
    "alle": "at {ora}",
    "giorno_alle": "{giorno} at {ora}",
    "valore_titolo": "title «{valore}»",
    "valore_stato": "status {valore}",
    "valore_priorita": "priority {valore}",
    "valore_scadenza": "due date {valore}",
    "valore_scadenza_tolta": "due date removed",
    "valore_stima": "estimated time {valore}",
    "valore_stima_tolta": "estimated time removed",
    "valore_area": "area {valore}",
    "valore_area_tolta": "no area",
    "valore_pianificata": "start {valore}",
    "valore_pianificata_tolta": "removed from the calendar",
    "valore_elimina": "to delete",

    "rifiuto_verbo": "I don't know how to make this change.",
    "rifiuto_campo": "This field cannot be changed from the phone.",
    "rifiuto_descrizione": "From the phone the description is appended at the end, not rewritten.",
    "rifiuto_versione": "I don't know which version of the task you had, I won't delete it.",
    "rifiuto_data": "The date must be written in full: year, month and day.",
    "rifiuto_annulla": "I don't know which change to undo.",
    "rifiuto_task": "I don't know which task this is.",
    "rifiuto_vuoto": "The text is empty.",
}





def fotografia(taglio: int = DESCR_MAX, eventi: list[dict] | None = None) -> dict:
    ""



    taglio = max(int(taglio), 1)
    ev = A._eventi() if eventi is None else eventi
    imp = A._imp()
    tutte = A._carica(ev)
    aree = A._aree(ev, imp)
    versione: dict[str, int] = {}
    for i, e in enumerate(ev):
        x = e.get("id")
        if x.__class__ is str:
            versione[A._pulito(x)] = i
    righe = [
        _task_fuori(t, imp, aree, taglio, versione.get(t["id"]))
        for t in tutte.values()
        if not t.get("eliminata")
    ]
    stati = [
        {
            "id": s["id"],
            "nome": s.get("nome") or s["id"],
            "tipo": s.get("tipo"),
            "colore": s.get("colore") or "grigio",
            "segno": s.get("segno"),
        }
        for s in A._stati_in_ordine(imp)
    ]
    u = imp.get("urgenti") or {}
    return {
        "modello": MODELLO,
        "serie": len(ev),
        "serie_impostazioni": len(A._righe_impostazioni()),
        "quando": A._ora(),
        "taglio": taglio,
        "stati": stati,
        "predefinito": A._predefinito(imp),
        "aree": [{"id": d["id"], "nome": d["nome"]} for d in aree.visibili()],

        "urgenti": {
            "p1": bool(u.get("p1", True)),
            "prima": int(u.get("giorni_prima", 6)),
            "dopo": int(u.get("giorni_dopo", 7)),
        },
        "task": righe,
    }


def _task_fuori(t: dict, imp: dict, aree, taglio: int, versione: int | None) -> dict:
    d = A._mostrata(t).strip()
    area = aree.finale(t.get("area"))
    o = t.get("origine") if isinstance(t.get("origine"), dict) else {}
    stima = t.get("stima")
    return {
        "id": t["id"],
        "titolo": t.get("titolo") or "",
        "stato": t.get("stato"),
        "chiusa": bool(A._chiuso(imp, t.get("stato"))),
        "priorita": t.get("priorita") if t.get("priorita") in A.PRIORITA else 2,
        "scadenza": t.get("scadenza"),
        "pianificata": t.get("pianificata"),
        "stima": stima if type(stima) is int and stima > 0 else None,
        "area": None if area == A.SENZA_AREA else area,
        "area_nome": None if area == A.SENZA_AREA else aree.nome(area),
        "creata": t.get("creata"),
        "cambiata": t.get("cambiata"),
        "chiusa_il": t.get("chiusa"),
        "link": o.get("url") if A._link_buono(o.get("url")) else None,
        "descrizione": d if len(d) <= taglio else d[: taglio - 1].rstrip() + "…",
        "descrizione_intera": len(d) <= taglio,
        "versione": versione,
    }


def _firma(taglio: int) -> tuple:
    ""
    return (MODELLO, len(A._eventi()), len(A._righe_impostazioni()), max(int(taglio), 1))


def _firma_di(foto: dict | None) -> tuple | None:
    if not isinstance(foto, dict):
        return None
    return tuple(foto.get(k) for k in ("modello", "serie", "serie_impostazioni", "taglio"))





def _esito(g, esito: str, frase: str | None = None, **altro) -> dict:
    return {
        "chiave": g.get("chiave") if isinstance(g, dict) else None,
        "esito": esito,
        "frase": frase if frase is not None else TESTI[f"esito_{esito}"],
        "quando": A._ora(),
        **altro,
    }


def _frase(e: A.Errore) -> str:
    ""
    chiave = e.chiave
    if e.altro.get("n") == 1 and chiave + "_una" in A.TESTI:
        chiave += "_una"
    testo = A.TESTI.get(chiave) or TESTI.get(chiave) or A.TESTI["errore_valore"]
    try:
        return testo.format(**{k: A.numero(v) if type(v) is int else v for k, v in e.altro.items()})
    except (KeyError, IndexError, ValueError):
        return testo


def _ms_telefono() -> int | None:
    ""
    ms = A._FUORI[0].get("ms") if A._FUORI else None
    return ms if type(ms) is int else None


def _istante(e: dict) -> int | None:
    ""
    f = e.get("fuori")
    if isinstance(f, dict) and type(f.get("ms")) is int:
        return f["ms"]
    quando = A._momento(e.get("t"))
    return A._ms_evento(e, quando) if quando else None


def _da_fuori(e: dict) -> bool:
    return isinstance(e.get("fuori"), dict)


def _scrive(e: dict, tid: str, campo: str | None) -> bool:
    ""
    if e.get("id") != tid:
        return False
    if campo is None:
        return e.get("tipo") in ("cambia", "elimina", "ripristina")
    campi = e.get("campi") if isinstance(e.get("campi"), dict) else {}
    return e.get("tipo") == "crea" or (e.get("tipo") == "cambia" and campo in campi)


def _ultimo_cambio(ev: list[dict], tid: str, campo: str) -> tuple[int | None, bool]:
    ""
    for e in reversed(ev):
        if _scrive(e, tid, campo):
            return _istante(e), _da_fuori(e)
    return None, False


def _cambi_del_mac_dopo(ev: list[dict], tid: str, versione: int, campo: str | None) -> list[int]:
    ""
    return [
        i
        for i in range(max(versione + 1, 0), len(ev))
        if _scrive(ev[i], tid, campo) and ev[i].get("tipo") != "crea" and not _da_fuori(ev[i])
    ]


def _alle(ms: int, oggi: datetime) -> str:
    ""
    d = A.C._da_ms(ms)
    ora = f"{d.hour}:{d.minute:02d}"
    if d.date() == oggi.date():
        return TESTI["alle"].format(ora=ora)
    return TESTI["giorno_alle"].format(giorno=A.C._il(d, oggi), ora=ora)


def _testo(v) -> str:
    return unicodedata.normalize("NFC", str(v if v is not None else ""))


def _normale(campo: str, v, imp: dict):
    ""

    if campo == "titolo":
        testo = _testo(v)
        if A._vuoto(testo):
            raise A.Errore("errore_titolo")
        return testo.strip()
    if campo == "stato":
        sid = A._risolvi_stato(imp, _testo(v))
        if sid is None:
            raise A.Errore("errore_stato", elenco=A._elenco_stati(imp))
        return sid
    if campo == "priorita":
        if isinstance(v, bool) or v is None:
            raise A.Errore("errore_valore")

        return A._leggi_priorita(str(v))
    if campo == "scadenza":
        if v is None or v in ("", "togli"):
            return None
        if not isinstance(v, str) or not A._data_buona(v.strip()):
            raise A.Errore("rifiuto_data")
        return v.strip()
    if campo == "stima":
        if isinstance(v, bool):
            raise A.Errore("errore_durata")
        if v is None or v in ("", "togli", 0):
            return None
        if type(v) is int:
            if v < 0:
                raise A.Errore("errore_durata_negativa")
            if v > A.STIMA_MAX:
                raise A.Errore("errore_durata_troppo")
            return v
        if isinstance(v, bool) or not isinstance(v, str):
            raise A.Errore("errore_durata")
        return A.leggi_durata(v)
    if campo == "area":
        if v is None:
            return None
        if not isinstance(v, str):
            raise A.Errore("errore_valore")
        testo = _testo(v).strip()
        if A._vuoto(testo) or testo == A.SENZA_AREA:
            return None
        if testo.casefold() == A.TESTI["senza_area"].casefold():
            return None
        return A._nome_area(testo)
    if campo == "pianificata":
        if v is None or v in ("", "togli"):
            return None
        if not isinstance(v, str) or not _PER_INTERO.match(v.strip()):
            raise A.Errore("rifiuto_data")
        return A.leggi_pianificata(v)
    raise A.Errore("rifiuto_campo")


def _area_finale(aree, v) -> str | tuple:
    ""

    if v is None:
        return A.SENZA_AREA
    trovata = aree.cerca(v)
    if trovata is None:
        return ("nuova", A._chiave_area(v))
    return aree.finale(trovata)


def _attuale(campo: str, t: dict, aree):
    return aree.finale(t.get("area")) if campo == "area" else t.get(campo)


def _uguali(campo: str, attuale, nuovo, aree) -> bool:
    if campo == "area":
        return attuale == _area_finale(aree, nuovo)
    if campo == "pianificata":
        return A._pianificata_locale(attuale) == A._pianificata_locale(nuovo)
    return attuale == nuovo


def _nella_fotografia(campo: str, v):
    ""
    if campo == "area":
        return None if v == A.SENZA_AREA or isinstance(v, tuple) else v
    return v


def _era_torna(g: dict, campo: str, t: dict, attuale, imp: dict, aree) -> bool | None:
    ""

    if "era" not in g:
        return None
    try:
        if campo == "stato":
            return A._era_torna("stato", t, _testo(g["era"]), imp)
        if campo == "titolo":
            return _testo(g["era"]) == t.get("titolo")
        return _uguali(campo, attuale, _normale(campo, g["era"], imp), aree)
    except A.Errore:
        return False


def _parole(campo: str, v, imp: dict, aree, oggi: datetime) -> str:
    ""
    if campo == "titolo":
        return TESTI["valore_titolo"].format(valore=v)
    if campo == "stato":
        return TESTI["valore_stato"].format(valore=A._stato_di(imp, v)["nome"])
    if campo == "priorita":
        return TESTI["valore_priorita"].format(valore=A.PRIORITA.get(v, v))
    if v is None:
        return TESTI[f"valore_{campo}_tolta"]
    if campo == "scadenza":
        giorno = A.C._il(datetime.strptime(v, "%Y-%m-%d"), oggi)
        return TESTI["valore_scadenza"].format(valore=giorno)
    if campo == "stima":
        return TESTI["valore_stima"].format(valore=A.stima_frase(v))
    if campo == "area":
        finale = _area_finale(aree, v)
        return TESTI["valore_area"].format(
            valore=v if isinstance(finale, tuple) else aree.nome(finale)
        )
    giorno, ora = A._pianificata_locale(v)
    quando = A.C._il(datetime.strptime(giorno, "%Y-%m-%d"), oggi)
    if ora:
        quando = TESTI["giorno_alle"].format(giorno=quando, ora=A._ora_corta(ora))
    return TESTI["valore_pianificata"].format(valore=quando)


def _commento_perso(tid: str, cosa: str, quando_dopo: int, dal_telefono: bool = False) -> str:
    ""

    oggi = A.C._adesso()
    ms = _ms_telefono()
    chiave = "perso_dal_telefono" if dal_telefono else "perso"
    dopo = _alle(quando_dopo, oggi)
    if ms is None:
        testo = TESTI[chiave + "_senza_ora"].format(cosa=cosa, quando_dopo=dopo)
    else:
        testo = TESTI[chiave].format(quando=_alle(ms, oggi), cosa=cosa, quando_dopo=dopo)
    return A._scrivi(
        {"t": A._ora(), "id": tid, "tipo": "commento", "da": DA, "testo": testo, "via": "testo"}
    )


def _la_task(g: dict, ev: list[dict]) -> tuple[dict, dict | None]:
    tid = g.get("id")
    if not isinstance(tid, str) or not tid:
        raise A.Errore("rifiuto_task")
    tutte = A._carica_di([tid], ev)
    return tutte, tutte.get(tid)


def _scrivi_campo(g: dict, ev: list[dict], tutte: dict, t: dict, campo: str, nuovo) -> dict:
    ""

    imp = A._imp()

    aree = A.Aree(imp, A._valori_area(ev)) if campo == "area" else None
    tid = t["id"]
    attuale = _attuale(campo, t, aree)
    if _uguali(campo, attuale, nuovo, aree):
        return _esito(g, "gia_cosi", id=tid, attuale=_nella_fotografia(campo, attuale))
    versione = g.get("versione")
    era = _era_torna(g, campo, t, attuale, imp, aree)
    cambiata = era is False or (
        type(versione) is int and bool(_cambi_del_mac_dopo(ev, tid, versione, campo))
    )
    if era is None and type(versione) is not int:

        cambiata = True
    sopra = None
    if cambiata:
        quando_dopo, dal_telefono = _ultimo_cambio(ev, tid, campo)
        ms = _ms_telefono()
        if quando_dopo is not None and (ms is None or quando_dopo >= ms):

            oggi = A.C._adesso()
            cosa = _parole(campo, nuovo, imp, aree, oggi)
            eid = _commento_perso(tid, cosa, quando_dopo, dal_telefono)
            frase = TESTI["esito_superato_telefono" if dal_telefono else "esito_superato"]
            return _esito(
                g,
                "superato",
                frase.format(quando=_alle(quando_dopo, oggi)),
                id=tid,
                attuale=_nella_fotografia(campo, attuale),
                cambiata_dopo=A.C._da_ms(quando_dopo).isoformat(timespec="seconds"),
                eventi=[eid],
            )
        if not dal_telefono:
            sopra = quando_dopo
    if campo == "area":
        nuovo = A._area_da_scrivere(nuovo, valori=A._valori_area(ev))[0] if nuovo else None
    _, eid = A._cambia_dentro(tutte, tid, {campo: nuovo}, DA, None)
    out = _esito(g, "fatto", id=tid, eventi=[eid] if eid else [])
    if sopra is not None:

        out["sopra_il_mac"] = A.C._da_ms(sopra).isoformat(timespec="seconds")
    return out


def _cambia(g: dict, ev: list[dict]) -> dict:
    campo = g.get("campo")
    if campo == "descrizione":
        return _esito(g, "rifiutato", TESTI["rifiuto_descrizione"])
    if campo not in CAMPI:
        return _esito(g, "rifiutato", TESTI["rifiuto_campo"])
    tutte, t = _la_task(g, ev)
    if t is None or t["eliminata"]:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    nuovo = _normale(campo, g.get("valore"), A._imp())
    return _scrivi_campo(g, ev, tutte, t, campo, nuovo)


def _fatta(g: dict, ev: list[dict]) -> dict:
    tutte, t = _la_task(g, ev)
    if t is None or t["eliminata"]:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    return _scrivi_campo(g, ev, tutte, t, "stato", A._stato_fatta(A._imp()))


def _riapri(g: dict, ev: list[dict]) -> dict:
    ""
    tutte, t = _la_task(g, ev)
    if t is None or t["eliminata"]:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    imp = A._imp()
    if not A._chiuso(imp, t.get("stato")):
        return _esito(g, "gia_cosi", id=t["id"], attuale=t.get("stato"))
    return _scrivi_campo(g, ev, tutte, t, "stato", A._predefinito(imp))


def _aggiungi(g: dict, ev: list[dict]) -> dict:
    ""
    testo = _testo(g.get("testo")).strip()
    if A._vuoto(testo):
        return _esito(g, "rifiutato", TESTI["rifiuto_vuoto"])
    tutte, t = _la_task(g, ev)
    if t is None or t["eliminata"]:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    vecchia = t.get("descrizione") or ""
    nuova = f"{vecchia.rstrip()}\n\n{testo}" if vecchia.strip() else testo
    _, eid = A._cambia_dentro(tutte, t["id"], {"descrizione": nuova}, DA, None)
    return _esito(g, "fatto", id=t["id"], eventi=[eid] if eid else [])


def _commenta(g: dict, ev: list[dict]) -> dict:
    testo = _testo(g.get("testo")).strip()
    if A._vuoto(testo):
        raise A.Errore("errore_commento_vuoto")
    tutte, t = _la_task(g, ev)
    if t is None or t["eliminata"]:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    eid = A._scrivi(
        {"t": A._ora(), "id": t["id"], "tipo": "commento", "da": DA, "testo": testo, "via": "testo"}
    )
    return _esito(g, "fatto", id=t["id"], eventi=[eid])


def _nuova(g: dict, ev: list[dict]) -> dict:
    ""
    c_era = A._task_dell_origine(ev, DA, g["chiave"])
    if c_era is not None:
        return _esito(g, "gia_arrivato", id=c_era["id"])
    imp = A._imp()
    pieni: dict = {"titolo": _normale("titolo", g.get("titolo"), imp)}
    campi = g.get("campi") or {}
    if not isinstance(campi, dict) or set(campi) - set(CAMPI_NUOVA):
        return _esito(g, "rifiutato", TESTI["rifiuto_campo"])
    for k, v in campi.items():
        pieni[k] = _testo(v).strip() if k == "descrizione" else _normale(k, v, imp)
    if pieni.get("area"):
        pieni["area"] = A._area_da_scrivere(pieni["area"], valori=A._valori_area(ev))[0]
    pieni["origine"] = {"fonte": DA, "id": g["chiave"]}
    tid, eid = A._crea_dentro(pieni, DA)
    return _esito(g, "fatto", id=tid, eventi=[eid])


def _elimina(g: dict, ev: list[dict]) -> dict:
    ""

    tutte, t = _la_task(g, ev)
    if t is None:
        return _esito(g, "non_ce_piu", id=g.get("id"))
    if t["eliminata"]:
        return _esito(g, "gia_cosi", id=t["id"])
    versione = g.get("versione")
    if type(versione) is not int:
        return _esito(g, "rifiutato", TESTI["rifiuto_versione"])
    dopo = _cambi_del_mac_dopo(ev, t["id"], versione, None)
    if dopo:
        quando_mac = _istante(ev[dopo[-1]]) or A._adesso_ms()
        eid = _commento_perso(t["id"], TESTI["valore_elimina"], quando_mac)
        oggi = A.C._adesso()
        return _esito(
            g,
            "superato",
            TESTI["esito_superato"].format(quando=_alle(quando_mac, oggi)),
            id=t["id"],
            cambiata_dopo=A.C._da_ms(quando_mac).isoformat(timespec="seconds"),
            eventi=[eid],
        )
    eid = A._segna_dentro(tutte, t["id"], "elimina", DA)
    return _esito(g, "fatto", id=t["id"], eventi=[eid] if eid else [])


def _annulla(g: dict, ev: list[dict]) -> dict:
    ""

    di = g.get("di")
    if not isinstance(di, str) or not di:
        return _esito(g, "rifiutato", TESTI["rifiuto_annulla"])
    per_eid = {e.get("eid"): e for e in ev if isinstance(e.get("eid"), str)}
    eids = [
        x
        for x in A._attivi_del_gruppo(di)
        if (per_eid.get(x, {}).get("fuori") or {}).get("da") == DA
    ]
    if not eids:
        return _esito(g, "gia_cosi")
    try:
        r = A._annulla_dentro(eids, DA)
    except A.Errore as e:
        if e.chiave.startswith("errore_cambiata_"):
            return _esito(g, "superato", A.TESTI[e.chiave])
        if e.chiave == "errore_sparita":
            return _esito(g, "non_ce_piu")
        raise
    return _esito(g, "fatto", eventi=r["eventi"], ids=r["ids"])


_FARE = {
    "cambia": _cambia,
    "fatta": _fatta,
    "riapri": _riapri,
    "aggiungi": _aggiungi,
    "commenta": _commenta,
    "nuova": _nuova,
    "elimina": _elimina,
    "annulla": _annulla,
}


def _lavoro(g: dict, eventi: list[dict]) -> dict:
    ""

    fare = _FARE.get(g.get("verbo"))
    if fare is None:
        return _esito(g, "rifiutato", TESTI["rifiuto_verbo"])
    try:
        return fare(g, eventi)
    except A.Errore as e:
        if A._CODA:

            raise
        return _esito(g, "rifiutato", _frase(e))


def applica_uno(g) -> dict:
    ""

    if not isinstance(g, dict):
        return _esito({}, "rifiutato", TESTI["rifiuto_verbo"])
    ms = g.get("ms") if type(g.get("ms")) is int else None
    try:
        r = A.da_fuori(g.get("chiave"), DA, ms, lambda ev: _lavoro(g, ev))
    except A.Errore as e:
        return _esito(g, "rifiutato", _frase(e))
    if r.get("esito") != "gia_arrivato":
        return r
    primo = r.get("primo")
    if isinstance(primo, dict):
        return _esito(g, "gia_arrivato", primo=primo, id=primo.get("id"))

    return _esito(g, "gia_arrivato", primo=None, eventi=r.get("eventi", []), ids=r.get("ids", []))


def _ordine(g) -> tuple:
    ""
    if not isinstance(g, dict):
        return (float("inf"), "")
    ms = g.get("ms")
    return (ms if type(ms) is int else float("inf"), str(g.get("chiave") or ""))


def applica(cambi: list) -> dict:
    ""

    esiti, fermo = [], None
    for g in sorted(cambi, key=_ordine):
        try:
            esiti.append(applica_uno(g))
        except Exception as e:  # noqa: BLE001 a failure is not an outcome: we say where it stopped
            fermo = {
                "chiave": g.get("chiave") if isinstance(g, dict) else None,
                "guasto": type(e).__name__,
            }
            break
    return {"esiti": esiti, "fermo": fermo}





def _scrivi_json(p: Path, dati: dict) -> None:
    ""

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(A.json_per_app(dati))
    os.replace(tmp, p)


def _leggi_json(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


class Cartella:
    ""




    def __init__(self, radice) -> None:
        self.radice = Path(radice)

    def in_attesa(self) -> tuple[list[tuple[str, dict]], int]:
        ""
        coda = self.radice / "coda"
        out, illeggibili = [], 0
        if not coda.is_dir():
            return out, 0
        for p in sorted(coda.glob("*.json")):
            if (self.radice / "esiti" / p.name).is_file():
                continue
            g = _leggi_json(p)
            if g is None:
                illeggibili += 1
                continue
            out.append((p.name, g))
        return out, illeggibili

    def scrivi_esito(self, nome: str, esito: dict) -> None:
        _scrivi_json(self.radice / "esiti" / Path(nome).name, esito)

    def pubblicata(self) -> dict | None:
        return _leggi_json(self.radice / "fotografia.json")

    def pubblica(self, foto: dict) -> None:
        _scrivi_json(self.radice / "fotografia.json", foto)

    def ultimo_giro(self) -> dict | None:
        return _leggi_json(self.radice / "giro.json")

    def segna_giro(self, numeri: dict) -> None:
        _scrivi_json(self.radice / "giro.json", numeri)





def _file_registro() -> Path:
    ""
    return A.CARTELLA.parent / "logs" / "telefono.log"


@contextlib.contextmanager
def _lucchetto_giro():
    ""

    A.CARTELLA.mkdir(parents=True, exist_ok=True)
    fh = open(A.CARTELLA / ".lucchetto-telefono", "a+")  # noqa: SIM115 closed just below
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def _riga_registro(numeri: dict) -> None:
    p = _file_registro()
    p.parent.mkdir(parents=True, exist_ok=True)
    A._scrivi_righe(p, [numeri])


def giro(mezzo: Cartella, taglio: int = DESCR_MAX) -> dict:
    ""


    t0 = time.perf_counter()
    with _lucchetto_giro() as preso:
        if not preso:
            numeri = {"t": A._ora(), "saltato": 1}
            _riga_registro(numeri)
            return numeri
        numeri = {"t": None, "coda": 0, **dict.fromkeys(ESITI, 0), "illeggibili": 0, "errori": 0,
                  "righe": 0, "serie": None, "fotografia": 0, "ms": None}
        try:
            attesa, numeri["illeggibili"] = mezzo.in_attesa()
            numeri["coda"] = len(attesa)
            serie_prima = len(A._eventi())
            for nome, g in sorted(attesa, key=lambda x: _ordine(x[1])):


                e = applica_uno(g)
                mezzo.scrivi_esito(nome, e)
                numeri[e["esito"]] = numeri.get(e["esito"], 0) + 1
            firma = _firma(taglio)
            numeri["serie"], numeri["righe"] = firma[1], firma[1] - serie_prima
            if _firma_di(mezzo.pubblicata()) != firma:
                mezzo.pubblica(fotografia(taglio))
                numeri["fotografia"] = 1
        except Exception as ex:  # noqa: BLE001 the run stops, but its line is there: with the failure name, never a message
            numeri["errori"] = 1
            numeri["guasto"] = type(ex).__name__
        finally:
            numeri["t"] = A._ora()
            numeri["ms"] = round((time.perf_counter() - t0) * 1000)
            with contextlib.suppress(Exception):
                mezzo.segna_giro(numeri)
            _riga_registro(numeri)
        return numeri


def prova(mezzo: Cartella, taglio: int = DESCR_MAX) -> dict:
    ""


    attesa, illeggibili = mezzo.in_attesa()
    vera = A.CARTELLA
    copia = Path(tempfile.mkdtemp(prefix="sb-telefono-prova-"))
    try:
        with A._Lucchetto():
            for nome in ("eventi.jsonl", "impostazioni.jsonl", "fuori.jsonl"):
                if (vera / nome).is_file():
                    shutil.copy2(vera / nome, copia / nome)
        A.CARTELLA = copia
        A._IMP_CACHE.clear()
        esiti = {nome: applica_uno(g) for nome, g in sorted(attesa, key=lambda x: _ordine(x[1]))}
        foto = fotografia(taglio)
    finally:
        A.CARTELLA = vera
        A._IMP_CACHE.clear()
        shutil.rmtree(copia, ignore_errors=True)
    conti = dict.fromkeys(ESITI, 0)
    for e in esiti.values():
        conti[e["esito"]] = conti.get(e["esito"], 0) + 1
    return {
        "esiti": esiti,
        "coda": len(attesa),
        **conti,
        "illeggibili": illeggibili,
        "task": len(foto["task"]),
        "serie": foto["serie"],
    }


def stato(mezzo: Cartella) -> dict:
    ""

    ultima = None
    with contextlib.suppress(OSError):
        for riga in reversed(_file_registro().read_text(encoding="utf-8").splitlines()):
            with contextlib.suppress(ValueError):
                ultima = json.loads(riga)
                break
    foto = mezzo.pubblicata()
    attesa, illeggibili = mezzo.in_attesa()
    return {
        "ultimo_giro": ultima,
        "giro_nel_mezzo": mezzo.ultimo_giro(),
        "fotografia": {
            "quando": foto.get("quando"),
            "serie": foto.get("serie"),
            "task": len(foto.get("task") or []),
        }
        if foto
        else None,
        "in_attesa": len(attesa),
        "illeggibili": illeggibili,
    }





def _opzione(argv: list[str], nome: str) -> str | None:
    if nome in argv:
        i = argv.index(nome)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main(argv: list[str]) -> int:
    verbo = argv[1] if len(argv) > 1 else ""
    if verbo in ("-h", "--help"):
        print(__doc__)
        return 0
    taglio = int(_opzione(argv, "--taglio") or DESCR_MAX)
    if verbo == "fotografia":
        r = fotografia(taglio)
    elif verbo in ("giro", "prova", "stato"):
        cartella = _opzione(argv, "--mezzo")
        if not cartella:
            print(__doc__)
            return 2
        mezzo = Cartella(cartella)
        if verbo == "giro":
            r = giro(mezzo, taglio)
        elif verbo == "prova":
            r = prova(mezzo, taglio)
        else:
            r = stato(mezzo)
    elif verbo == "applica":
        cambi = json.loads(sys.stdin.read() or "[]")
        r = applica(cambi if isinstance(cambi, list) else [cambi])
    else:
        print(__doc__)
        return 2
    sys.stdout.buffer.write(A.json_per_app(r) + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
