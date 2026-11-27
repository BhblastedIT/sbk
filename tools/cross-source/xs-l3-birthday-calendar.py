#!/usr/bin/env python3
"""Writes the birthdays and name days of the knowledge base as events in two Google calendars of yours, aligned to
the recurring dates the L2 stage found. Dry run by default; --apply writes. Needs a Google login with write
access to your calendars (--login, your own OAuth client).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS = _THIS_DIR.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from sbk_config import KNOWLEDGE_META_DIR, safe_write_json  # noqa: E402

RICORRENZE = KNOWLEDGE_META_DIR / "ricorrenze.json"
VERIFICATE = KNOWLEDGE_META_DIR / "ricorrenze-verificate.json"
REGISTRO = KNOWLEDGE_META_DIR / "ricorrenze-calendario.json"
RAPPORTO = KNOWLEDGE_META_DIR / "ricorrenze-calendario-stadio.json"

# Your own Google login with write access to your calendars, stored in the
# Keychain as service "sbk-gcal-write" (account = label, default "default").
# The first time: --login opens the browser with your OAuth "Desktop app" client
# (tools/google_oauth.py).
KEYCHAIN_SERVICE = "sbk-gcal-write"
ACCOUNT_DEFAULT = "default"
SCOPE = ["https://www.googleapis.com/auth/calendar"]
FRENO = 20

CALENDARI = {
    "compleanni": {
        "nome": "Birthdays",
        "tag": "compleanni-sbk",
        "titolo": "🎂 {nome}",
        "promemoria": [0, 900],
        "data": "compleanno",
    },
    "onomastici": {
        "nome": "Name days",
        "tag": "onomastici-sbk",
        "titolo": "🕯️ Name day {nome}",
        "promemoria": [0],
        "data": "onomastico",
    },
}


def prossima(mmdd: str, oggi: date) -> date:
    m, d = int(mmdd[:2]), int(mmdd[3:])
    for anno in (oggi.year, oggi.year + 1, oggi.year + 2):
        try:
            x = date(anno, m, d)
        except ValueError:
            continue
        if x >= oggi:
            return x
    raise ValueError(mmdd)


def mmdd_evento(ev: dict) -> str | None:
    s = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
    return s[5:10] if s else None


def corpo(tipo: str, persona: dict, oggi: date) -> dict:
    c = CALENDARI[tipo]
    giorno = prossima(persona[c["data"]], oggi)
    out = {
        "summary": c["titolo"].format(nome=persona["nome"]),
        "start": {"dateTime": f"{giorno}T09:00:00", "timeZone": "UTC"},
        "end": {"dateTime": f"{giorno}T09:15:00", "timeZone": "UTC"},
        "recurrence": ["RRULE:FREQ=YEARLY"],
        "transparency": "transparent",
        "visibility": "private",
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in c["promemoria"]],
        },
        "extendedProperties": {"private": {"sbk": c["tag"], "chiave": persona["entity_id"]}},
    }
    if tipo == "onomastici" and persona.get("santo"):
        out["description"] = persona["santo"]
    return out


def piano(tipo: str, persone: list[dict], eventi: list[dict], registro: dict, oggi: date) -> dict:
    ""
    c = CALENDARI[tipo]
    per_nome = {p["nome"]: p["entity_id"] for p in persone}
    voluti = {p["entity_id"]: p for p in persone if p.get(c["data"])}
    reg = registro.setdefault(tipo, {})
    out = {
        "inserire": [],
        "aggiornare": [],
        "adottare": [],
        "toccati_da_owner": [],
        "cancellati_da_owner": [],
        "solo_calendario": [],
        "allineati": 0,
    }
    visti: set[str] = set()
    for ev in eventi:
        chiave = ((ev.get("extendedProperties") or {}).get("private") or {}).get("chiave", "")
        eid = chiave if chiave.startswith("person_") else per_nome.get(chiave)
        if not eid:
            if ev.get("status") != "cancelled":
                out["solo_calendario"].append(chiave)
            continue
        visti.add(eid)
        noto = reg.get(eid)
        if ev.get("status") == "cancelled":
            if eid in voluti:
                out["cancellati_da_owner"].append(eid)
            continue
        if eid not in voluti:
            out["solo_calendario"].append(eid)
            continue
        p = voluti[eid]
        data_cal, data_kb = mmdd_evento(ev), p[c["data"]]
        titolo = c["titolo"].format(nome=p["nome"])
        if noto is None:


            out["adottare"].append({"eid": eid, "id": ev["id"], "chiave_vecchia": chiave != eid})
            if data_cal != data_kb:
                out["toccati_da_owner"].append(
                    {"eid": eid, "ev": ev, "data_owner": data_cal, "data_kb": data_kb}
                )
            continue
        if ev.get("etag") != noto.get("etag"):
            if data_cal != noto.get("data") and data_cal != data_kb:
                out["toccati_da_owner"].append(
                    {"eid": eid, "ev": ev, "data_owner": data_cal, "data_kb": data_kb}
                )
                continue

        if data_cal != data_kb or ev.get("summary") != titolo:
            out["aggiornare"].append({"eid": eid, "id": ev["id"], "da": data_cal, "a": data_kb})
        else:
            out["allineati"] += 1
    for eid, p in voluti.items():
        if eid in visti:
            continue
        if reg.get(eid, {}).get("cancellato_da_owner"):
            continue
        out["inserire"].append(eid)
    return out


_ACCOUNT = {"nome": ACCOUNT_DEFAULT}


def login(nome: str) -> int:
    ""
    import google_oauth

    print(f"Authorizing write access to your calendars for '{nome}'.")
    google_oauth.browser_login(KEYCHAIN_SERVICE, nome, SCOPE)
    return 0


def _servizio():
    import google_oauth
    from googleapiclient.discovery import build

    nome = _ACCOUNT["nome"]
    creds = google_oauth.stored_credentials(KEYCHAIN_SERVICE, nome)
    if creds is None:
        raise RuntimeError(
            f"no calendar login for '{nome}': run "
            f"python3 tools/cross-source/xs-l3-birthday-calendar.py --login --account {nome}"
        )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _id_calendario(svc, tipo: str, registro: dict) -> str:
    ""
    ids = registro.setdefault("calendari", {})
    if ids.get(tipo):
        return ids[tipo]
    nome = CALENDARI[tipo]["nome"]
    trovati = [
        c["id"]
        for c in svc.calendarList().list().execute().get("items", [])
        if c.get("summary") == nome
    ]
    if len(trovati) != 1:
        raise RuntimeError(
            f"calendar «{nome}»: found {len(trovati)}, one needed. Create the calendar first."
        )
    ids[tipo] = trovati[0]
    return trovati[0]


def _eventi(svc, cid: str, tag: str) -> list[dict]:
    out, tok = [], None
    while True:
        r = (
            svc.events()
            .list(
                calendarId=cid,
                privateExtendedProperty=f"sbk={tag}",
                showDeleted=True,
                maxResults=250,
                pageToken=tok,
            )
            .execute()
        )
        out += r.get("items", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def _correggi_verificate(correzioni: list[dict]) -> None:
    ""
    if not correzioni:
        return
    doc = json.loads(VERIFICATE.read_text())
    gia = {
        (c["entity_id"], c["campo"], c["nuova"]) for c in doc.get("correzioni_da_calendario", [])
    }
    for c in correzioni:
        if (c["entity_id"], c["campo"], c["nuova"]) not in gia:
            doc.setdefault("correzioni_da_calendario", []).append(c)
    safe_write_json(VERIFICATE, doc, indent=1)


def esegui(applica: bool) -> int:
    import google_oauth

    if google_oauth.stored_credentials(KEYCHAIN_SERVICE, _ACCOUNT["nome"]) is None:
        # Never signed in: the two calendars are off. Not an error, nothing is written anywhere.
        print(
            f"No calendar login saved for '{_ACCOUNT['nome']}': the Birthdays and Name days calendars "
            "are off. To switch them on, sign in once: uv run python "
            f"tools/cross-source/xs-l3-birthday-calendar.py --login --account {_ACCOUNT['nome']}"
        )
        return 0
    oggi = date.today()
    if not RICORRENZE.exists():
        print(f"{RICORRENZE} not found: run the L3 stage that writes the recurring dates first.")
        return 1
    ric = json.loads(RICORRENZE.read_text())
    persone = [dict(p) for p in ric["persone"] if p.get("calendario")]


    per_eid = {p["entity_id"]: p for p in persone}
    if VERIFICATE.exists():
        for c in json.loads(VERIFICATE.read_text()).get("correzioni_da_calendario", []):
            if c.get("entity_id") in per_eid:
                per_eid[c["entity_id"]][c["campo"]] = c["nuova"]
    registro = json.loads(REGISTRO.read_text()) if REGISTRO.exists() else {}
    rapporto: dict = {"quando": datetime.now(UTC).isoformat(), "applicato": False, "errori": []}
    try:
        svc = _servizio()
        piani = {}
        for tipo in CALENDARI:
            cid = _id_calendario(svc, tipo, registro)
            piani[tipo] = (
                cid,
                piano(tipo, persone, _eventi(svc, cid, CALENDARI[tipo]["tag"]), registro, oggi),
            )
    except Exception as e:  # noqa: BLE001 — auth or network: we say it, we don't swallow it
        rapporto["errori"].append(f"{type(e).__name__}: {str(e)[:300]}")
        safe_write_json(RAPPORTO, rapporto, indent=1)
        print("ERROR calendars:", rapporto["errori"][0])
        return 1
    scritture = sum(len(p["inserire"]) + len(p["aggiornare"]) for _, p in piani.values())
    for tipo, (_, p) in piani.items():
        rapporto[tipo] = {k: (len(v) if isinstance(v, list) else v) for k, v in p.items()}
        print(tipo, rapporto[tipo])
    rapporto["toccati_da_owner"] = [
        {k: v for k, v in x.items() if k != "ev"}
        for _, p in piani.values()
        for x in p["toccati_da_owner"]
    ]
    rapporto["cancellati_da_owner"] = [x for _, p in piani.values() for x in p["cancellati_da_owner"]]
    rapporto["solo_calendario"] = [x for _, p in piani.values() for x in p["solo_calendario"]]
    if not applica:
        print("(dry-run: --apply to write)")
        return 0
    if scritture > FRENO:
        rapporto["frenato"] = (
            f"{scritture} writes in one run, over the brake of {FRENO}: not applied"
        )
        safe_write_json(RAPPORTO, rapporto, indent=1)
        print(rapporto["frenato"])
        return 0
    correzioni = []
    try:
        for tipo, (cid, p) in piani.items():
            reg = registro.setdefault(tipo, {})
            c = CALENDARI[tipo]

            def ricorda(eid, ev, reg=reg, c=c):
                reg[eid] = {"id": ev["id"], "etag": ev["etag"], "data": mmdd_evento(ev)}

            for x in p["adottare"]:
                ev = (
                    svc.events()
                    .patch(
                        calendarId=cid,
                        eventId=x["id"],
                        body={
                            "extendedProperties": {
                                "private": {"sbk": c["tag"], "chiave": x["eid"]}
                            }
                        },
                    )
                    .execute()
                )
                ricorda(x["eid"], ev)
            for eid in p["inserire"]:
                ricorda(
                    eid,
                    svc.events()
                    .insert(calendarId=cid, body=corpo(tipo, per_eid[eid], oggi))
                    .execute(),
                )
            for x in p["aggiornare"]:
                b = corpo(tipo, per_eid[x["eid"]], oggi)
                ev = (
                    svc.events()
                    .patch(
                        calendarId=cid,
                        eventId=x["id"],
                        body={k: b[k] for k in ("summary", "start", "end")},
                    )
                    .execute()
                )
                ricorda(x["eid"], ev)
            adottati = {x["eid"] for x in p["adottare"]}
            for x in p["toccati_da_owner"]:
                if (
                    x["eid"] not in adottati
                ):
                    ricorda(x["eid"], x["ev"])
                correzioni.append(
                    {
                        "entity_id": x["eid"],
                        "campo": c["data"],
                        "nuova": x["data_owner"],
                        "vecchia": x["data_kb"],
                        "quando": oggi.isoformat(),
                        "come": f"moved by you on calendar {c['nome']}",
                    }
                )
            for eid in p["cancellati_da_owner"]:
                reg.setdefault(eid, {})["cancellato_da_owner"] = oggi.isoformat()
    except Exception as e:  # noqa: BLE001
        rapporto["errori"].append(f"{type(e).__name__}: {str(e)[:300]}")
        print("ERROR during writing:", rapporto["errori"][-1])

    safe_write_json(REGISTRO, registro, indent=1)
    _correggi_verificate(correzioni)
    rapporto["applicato"] = not rapporto["errori"]
    rapporto["correzioni_registrate"] = len(correzioni)
    safe_write_json(RAPPORTO, rapporto, indent=1)
    return 1 if rapporto["errori"] else 0


def prova() -> list[str]:
    ""
    oggi = date(2026, 10, 18)
    persone = [
        {"entity_id": f"person_{x}", "nome": n, "compleanno": md, "calendario": True}
        for x, n, md in (
            ("a", "Anna", "03-09"),
            ("b", "Bruno", "05-05"),
            ("c", "Carla", "06-06"),
            ("d", "Dario", "07-07"),
            ("e", "Elio", "08-08"),
        )
    ]

    def ev(i, chiave, md, etag, status="confirmed", titolo=None):
        return {
            "id": i,
            "etag": etag,
            "status": status,
            "summary": titolo,
            "start": {"dateTime": f"2027-{md}T09:00:00"},
            "extendedProperties": {"private": {"chiave": chiave}},
        }

    eventi = [
        ev(
            "1", "Anna", "03-09", "e1", titolo="🎂 Anna"
        ),
        ev("2", "person_b", "05-06", "e2x", titolo="🎂 Bruno"),
        ev("3", "person_c", "06-06", "e3", status="cancelled"),
        ev("4", "person_d", "07-07", "e4", titolo="🎂 Dario"),
        ev("9", "person_z", "01-01", "e9", titolo="x"),
    ]
    registro = {
        "compleanni": {
            "person_b": {"etag": "e2", "data": "05-05"},
            "person_d": {"etag": "e4", "data": "07-07"},
        }
    }
    p = piano("compleanni", persone, eventi, registro, oggi)
    err = []
    if [x["eid"] for x in p["toccati_da_owner"]] != ["person_b"] or p["aggiornare"]:
        err.append("calendar: a date you moved would be rewritten")
    if p["cancellati_da_owner"] != ["person_c"] or "person_c" in p["inserire"]:
        err.append("calendar: an event you deleted would be reinserted")
    if p["inserire"] != ["person_e"] or p["allineati"] != 1 or p["solo_calendario"] != ["person_z"]:
        err.append(
            f"calendar: unexpected plan {p['inserire']} {p['allineati']} {p['solo_calendario']}"
        )
    if [x["eid"] for x in p["adottare"]] != ["person_a"]:
        err.append("calendar: an event written before the registry is not adopted")
    if prossima("02-29", oggi) != date(2028, 2, 29):
        err.append("calendar: Feb 29 does not fall on the next leap year")
    return err


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Birthdays and Name days calendars aligned to the KB's recurrences"
    )
    ap.add_argument(
        "--apply", action="store_true", help="writes to the calendars (default: dry-run)"
    )
    # Older Italian name, kept as a hidden alias.
    ap.add_argument("--applica", action="store_true", dest="apply", help=argparse.SUPPRESS)
    ap.add_argument(
        "--account",
        default=ACCOUNT_DEFAULT,
        help="label of your saved calendar login (default: %(default)s)",
    )
    ap.add_argument(
        "--login",
        action="store_true",
        help="opens the browser once to save your calendar login, then exits",
    )
    a = ap.parse_args()
    _ACCOUNT["nome"] = a.account
    if a.login:
        return login(a.account)
    return esegui(a.apply)


if __name__ == "__main__":
    sys.exit(main())
