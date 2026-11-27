#!/usr/bin/env python3
"""WhatsApp: read a copy of the iPhone's chat database (ChatStorage.sqlite) into the imported chats.

Status: NOT SET UP OR TESTED BY THE AUTHOR as a way in for you. The WhatsApp path the author
uses is the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up. This script ran once, on a one-off
copy of the author's own phone database; SBK has no step that gets that copy from a phone for
you, and the script has not been tried on any other phone or WhatsApp version.
It stays in the repo because wa-l0l3-full.py borrows its message-by-message merge.

What it does: opens the copy read-only, reads text messages, links and attachment lines (not system
events), and adds to each chat file in <data root>/whatsapp/chats/ only the messages that are not there
yet (same sender at the same time, or same sender and same text, allowing for the time-zone shift
between the export and the database). Every chat it touches is copied first to
chats/_prima-chatstorage-<date>/; the index is rebuilt; a receipt goes to _ricevute-import.jsonl.
Without --apply it is a dry run.

    uv run python tools/whatsapp/wa-l0-chatstorage.py --db <path>/ChatStorage.sqlite            # dry run
    uv run python tools/whatsapp/wa-l0-chatstorage.py --db <path>/ChatStorage.sqlite --apply    # writes
"""






























from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from text_utils import normalize_name  # noqa: E402

from sbk_config import DATA_ROOT  # noqa: E402

COPIA = DATA_ROOT / "whatsapp" / "iphone-chatstorage" / "ChatStorage.sqlite"

EPOCA_APPLE = 978307200

FUSO = ZoneInfo("UTC")

CHAT_VERE = (0, 1)

TESTO = (0, 7)

SENZA_NOME = {
    1: "image omitted",
    2: "video omitted",
    3: "audio omitted",
    4: "contact card omitted",
    8: "document omitted",
    11: "GIF omitted",
    15: "sticker omitted",
}

MAX_FUSO = timedelta(hours=14)

RE_RISPOSTA = re.compile(r"^➜ Replying to .*?»\s*", re.S)
INVISIBILI = dict.fromkeys(map(ord, "‪‬‎‏⁨⁩"), None)

TRATTINI = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
SCONOSCIUTO = "?"

NUMERI_DAL_TELEFONO = "numeri_dal_telefono"


def _storico():
    nome = "wa_l0_import_history_cs"
    spec = importlib.util.spec_from_file_location(
        nome, _TOOLS / "whatsapp" / "wa-l0-import-history.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


def apri(percorso: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{percorso}?mode=ro&immutable=1", uri=True)


def telefono(jid: str | None) -> str:
    ""
    if not jid or "@s.whatsapp.net" not in jid:
        return ""
    cifre = jid.split("@")[0]
    return f"+{cifre}" if cifre.isdigit() else ""


def nome_chat(nome: str | None, jid: str | None) -> str:
    ""
    pulito = (nome or "").translate(INVISIBILI).replace("\xa0", " ").strip()
    if pulito and re.fullmatch(r"\+?[\d\s\-().]+", pulito.translate(TRATTINI)):
        return "+" + "".join(c for c in pulito if c.isdigit())
    return pulito or telefono(jid)


def ora_locale(secondi_apple: float) -> datetime:
    return (
        datetime.fromtimestamp(secondi_apple + EPOCA_APPLE, UTC)
        .astimezone(FUSO)
        .replace(tzinfo=None)
    )


def testo_di(tipo: int, testo: str | None, percorso: str | None, titolo: str | None) -> str | None:
    ""
    testo = (testo or "").strip()
    if tipo in TESTO:
        return testo or None
    if tipo in SENZA_NOME:
        nome = ""
        if titolo and "." in titolo[-6:]:
            nome = titolo.strip()
        elif percorso:
            nome = Path(percorso).name
        segno = f"<attached: {nome}>" if nome else SENZA_NOME[tipo]
        didascalia = testo if testo and testo != nome else ""
        return f"{segno}\n{didascalia}" if didascalia else segno
    return None


def pulisci(testo: str | None) -> str:
    ""
    t = (testo or "").translate(INVISIBILI).strip()
    t = RE_RISPOSTA.sub("", t, count=1).strip()
    t = re.sub(r"\s*<This message was edited>$", "", t)
    return t[:200]


class Esistenti:
    ""

    def __init__(self, chat: dict | None):
        self.ore: set[tuple[str, datetime]] = set()
        self.testi: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        self.scarti: set[timedelta] = {timedelta(0)}
        for m in (chat or {}).get("messages", []) or []:
            try:
                ora = datetime.fromisoformat(str(m["timestamp"])[:19])
            except (KeyError, ValueError):
                continue
            chi = normalize_name(m.get("sender", ""))
            for c in (chi, SCONOSCIUTO):
                self.ore.add((c, ora))
                self.testi[(c, pulisci(m.get("text")))].append(ora)

    @staticmethod
    def _di_fuso(delta: timedelta) -> bool:
        return abs(delta) <= MAX_FUSO and delta.total_seconds() % 1800 == 0

    def misura_scarti(self, messaggi: list[dict]) -> None:
        ""
        conti: Counter = Counter()
        for m in messaggi:
            ora = datetime.fromisoformat(m["timestamp"])
            chi = normalize_name(m["sender"]) if m.get("_sicuro", True) else SCONOSCIUTO
            for altra in self.testi.get((chi, pulisci(m["text"])), ()):
                if self._di_fuso(ora - altra):
                    conti[ora - altra] += 1
                    break
        self.scarti |= {d for d, n in conti.items() if n >= 2}

    def c_e(
        self, mittente: str, testo: str, ora: datetime, sicuro: bool = True
    ) -> timedelta | None:
        ""
        chi = normalize_name(mittente) if sicuro and mittente != SCONOSCIUTO else SCONOSCIUTO
        for d in sorted(self.scarti, key=abs):
            if (chi, ora - d) in self.ore:
                return d
        for altra in self.testi.get((chi, pulisci(testo)), ()):
            if self._di_fuso(ora - altra):
                return ora - altra
        return None


def _ora(m: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(m["timestamp"])[:19])
    except (KeyError, ValueError):
        return None


def appaia(
    dal_db: list[dict], dal_file: list[dict], scarti: set[timedelta]
) -> tuple[list[dict], list[dict]]:
    ""


    liberi = [f for f in dal_file if _ora(f) is not None]
    soli = sorted(dal_db, key=lambda m: m["timestamp"])
    for per_testo in (False, True):
        restano = []
        for m in soli:
            ora = datetime.fromisoformat(m["timestamp"])
            chi = (
                normalize_name(m["sender"])
                if m.get("_sicuro", True) and m["sender"] != SCONOSCIUTO
                else SCONOSCIUTO
            )
            testo = pulisci(m["text"])
            trovato = None
            for i, f in enumerate(liberi):
                if chi != SCONOSCIUTO and normalize_name(f.get("sender", "")) != chi:
                    continue
                delta = ora - _ora(f)
                if (not per_testo and delta in scarti) or (
                    per_testo and pulisci(f.get("text")) == testo and Esistenti._di_fuso(delta)
                ):
                    trovato = i
                    break
            if trovato is None:
                restano.append(m)
            else:
                liberi.pop(trovato)
        soli = restano
    return soli, liberi


def dai_giorni_coperti(
    in_attesa: dict[str, list[dict]],
    messaggi: list[dict],
    esistente: dict | None,
    scarti_chat: set[timedelta],
    scarto: timedelta,
) -> tuple[list[dict], int]:
    ""




    dal_file = (esistente or {}).get("messages") or []
    per_giorno: dict[str, list[dict]] = defaultdict(list)
    for m in messaggi:
        per_giorno[m["timestamp"][:10]].append(m)
    entrano: list[dict] = []
    fuori = 0
    for giorno, attesa in sorted(in_attesa.items()):
        inizio = datetime.fromisoformat(giorno)
        vicini = [
            f
            for f in dal_file
            if _ora(f) is not None
            and inizio - MAX_FUSO <= _ora(f) < inizio + timedelta(days=1) + MAX_FUSO
        ]
        soli, liberi = appaia(per_giorno[giorno], vicini, scarti_chat)
        if any((_ora(f) + scarto).strftime("%Y-%m-%d") == giorno for f in liberi):
            fuori += len(attesa)
            continue
        da_aspettare = {id(m) for m in attesa}
        ok = [m for m in soli if id(m) in da_aspettare]
        entrano.extend(ok)
        fuori += len(attesa) - len(ok)
    return entrano, fuori


def leggi_copia(con: sqlite3.Connection, owner: str) -> dict[int, dict]:
    ""
    sessioni = {
        pk: {"nome": nome_chat(nome, jid), "jid": jid or "", "tipo": tipo, "messaggi": []}
        for pk, nome, jid, tipo in con.execute(
            "SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID, ZSESSIONTYPE FROM ZWACHATSESSION"
        )
        if tipo in CHAT_VERE
    }

    pubblici = {
        jid: (nome or "").translate(INVISIBILI).strip()
        for jid, nome in con.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME")
    }



    membri: dict[int, tuple[str, bool]] = {}
    for pk, contatto, nome, jid in con.execute(
        "SELECT Z_PK, ZCONTACTNAME, ZFIRSTNAME, ZMEMBERJID FROM ZWAGROUPMEMBER"
    ):
        sicuro = (contatto or nome or "").translate(INVISIBILI).strip()
        if sicuro:
            membri[pk] = (sicuro, True)
        elif pubblici.get(jid):
            membri[pk] = (f"~ {pubblici[jid]}", False)
        elif telefono(jid):
            membri[pk] = (telefono(jid), False)
    media = {
        pk: (percorso, titolo)
        for pk, percorso, titolo in con.execute(
            "SELECT Z_PK, ZMEDIALOCALPATH, ZTITLE FROM ZWAMEDIAITEM"
        )
    }
    righe = con.execute(
        "SELECT ZCHATSESSION, ZMESSAGEDATE, ZISFROMME, ZMESSAGETYPE, ZTEXT, ZGROUPMEMBER, ZMEDIAITEM "
        "FROM ZWAMESSAGE ORDER BY ZCHATSESSION, ZMESSAGEDATE"
    )
    for sess, data, mio, tipo, testo, membro, item in righe:
        s = sessioni.get(sess)
        if s is None or data is None:
            continue
        percorso, titolo = media.get(item, (None, None))
        t = testo_di(int(tipo or 0), testo, percorso, titolo)
        if t is None:
            continue
        if mio:
            chi, sicuro = owner, True
        elif s["tipo"] == 0:
            chi, sicuro = (s["nome"], True) if s["nome"] else (SCONOSCIUTO, False)
        else:
            chi, sicuro = membri.get(membro, (SCONOSCIUTO, False))
        s["messaggi"].append(
            {
                "timestamp": ora_locale(data).isoformat(timespec="seconds"),
                "sender": chi,
                "text": t,
                "_sicuro": sicuro,
            }
        )
    return {pk: s for pk, s in sessioni.items() if s["messaggi"]}


def numero_di(s: dict) -> str:
    ""
    if s["tipo"] != 0:
        return ""
    return telefono(s["jid"]) or (s["nome"] if re.fullmatch(r"\+\d{7,}", s["nome"] or "") else "")


def indice_telefoni(chats_dir: Path) -> dict[str, str]:
    ""









    trovati: dict[str, set[str]] = defaultdict(set)
    registrati: dict[str, set[str]] = defaultdict(set)
    for p in sorted(chats_dir.glob("*.json")):
        if p.name == "chats-index.json":
            continue
        if re.fullmatch(r"\+[\d\-]+", p.stem):
            trovati["+" + "".join(c for c in p.stem if c.isdigit())].add(p.stem)
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        for numero in d.get(NUMERI_DAL_TELEFONO) or []:
            registrati[str(numero)].add(p.stem)
        if int(d.get("participant_count") or 0) > 2:
            continue
        rubrica = d.get("phone_numbers") or {}
        for voce in rubrica.items() if isinstance(rubrica, dict) else ():
            for x in voce:
                cifre = "".join(c for c in str(x) if c.isdigit())
                if len(cifre) >= 7:
                    trovati[f"+{cifre}"].add(p.stem)
    unici = {numero: next(iter(file)) for numero, file in trovati.items() if len(file) == 1}
    unici.update(
        {numero: next(iter(file)) for numero, file in registrati.items() if len(file) == 1}
    )
    return unici


def giorni_coperti(chat: dict | None) -> set[str]:
    ""
    fuori: set[str] = set()
    for m in (chat or {}).get("messages", []) or []:
        try:
            giorno = datetime.fromisoformat(str(m["timestamp"])[:10])
        except (KeyError, ValueError):
            continue
        for d in (-1, 0, 1):
            fuori.add((giorno + timedelta(days=d)).strftime("%Y-%m-%d"))
    return fuori


def _parole(slug: str) -> set[str]:
    return {w for w in re.split(r"[-_\s]+", slug.lower()) if len(w) > 2}


def gruppo_rinominato(s: dict, st, slugs: list[str]) -> str | None:
    ""


    parole = _parole(st.sanitize_filename(s["nome"]))
    migliore = None
    for e in slugs:
        if not parole or len(parole & _parole(e)) < 0.5 * len(parole):
            continue
        chat = st.load_existing_chat(e)
        if not chat or not chat.get("date_start"):
            continue
        da, a = str(chat["date_start"])[:19], str(chat.get("date_end") or "")[:19]
        nel_periodo = [m for m in s["messaggi"] if da <= m["timestamp"] <= a]
        if len(nel_periodo) < 10:
            continue
        gia = Esistenti(chat)
        gia.misura_scarti(nel_periodo)
        comuni = sum(
            1
            for m in nel_periodo
            if gia.c_e(m["sender"], m["text"], datetime.fromisoformat(m["timestamp"]), m["_sicuro"])
            is not None
        )
        if (
            comuni >= 10
            and comuni >= 0.6 * len(nel_periodo)
            and (not migliore or comuni > migliore[1])
        ):
            migliore = (e, comuni)
    return migliore[0] if migliore else None


def nuovi_per(
    esistente: dict | None, messaggi: list[dict], presi: list[dict] = ()
) -> tuple[list[dict], Counter, Counter]:
    ""





    conti: Counter = Counter()
    scarti: Counter = Counter()
    gia = Esistenti({"messages": [*((esistente or {}).get("messages") or []), *presi]})
    gia.misura_scarti(messaggi)
    fine = str(esistente.get("date_end") or "")[:19] if esistente else ""
    giorni = giorni_coperti(esistente)
    nuovi = []
    in_attesa: dict[str, list[dict]] = defaultdict(list)
    scarti_qui: Counter = Counter()
    for m in messaggi:
        d = gia.c_e(
            m["sender"],
            m["text"],
            datetime.fromisoformat(str(m["timestamp"])[:19]),
            m.get("_sicuro", True),
        )
        if d is not None:
            conti["gia_presenti"] += 1
            scarti[round(d.total_seconds() / 3600, 1)] += 1
            scarti_qui[d] += 1
            continue
        if fine and str(m["timestamp"])[:19] <= fine:
            if str(m["timestamp"])[:10] in giorni:
                in_attesa[str(m["timestamp"])[:10]].append(m)
                continue
            conti["buchi_recuperati"] += 1
        nuovi.append(m)
    if in_attesa:
        scarto = scarti_qui.most_common(1)[0][0] if scarti_qui else timedelta(0)
        entrano, restano = dai_giorni_coperti(in_attesa, messaggi, esistente, gia.scarti, scarto)
        nuovi.extend(entrano)
        conti["buchi_recuperati_nei_giorni_coperti"] += len(entrano)
        conti["buchi_in_giorni_coperti"] += restano
    return nuovi, conti, scarti


def piano(chat_db: dict[int, dict], st, chats_dir: Path) -> tuple[list, Counter, Counter]:
    ""





    telefoni: dict[str, str] | None = None
    slugs = [p.stem for p in chats_dir.glob("*.json") if p.name != "chats-index.json"]
    conti: Counter = Counter()
    scarti: Counter = Counter()

    per_file: dict[str, list] = {}
    for s in chat_db.values():
        slug = st.sanitize_filename(s["nome"]) if s["nome"] else ""
        esistente = st.load_existing_chat(slug) if slug else None
        messaggi = s["messaggi"]
        if esistente is None and numero_di(s):
            if telefoni is None:
                telefoni = indice_telefoni(chats_dir)
            altro = telefoni.get(numero_di(s))
            if altro:
                conti["chat_trovate_per_numero"] += 1
                slug, esistente = altro, st.load_existing_chat(altro)



                messaggi = [
                    m if m["sender"] == st.OWNER_CANONICAL else {**m, "_sicuro": False}
                    for m in messaggi
                ]
        if esistente is None and s["tipo"] == 1 and slug:
            altro = gruppo_rinominato(s, st, slugs)
            if altro:
                conti["gruppi_rinominati"] += 1
                slug, esistente = altro, st.load_existing_chat(altro)
        if not slug:
            conti["chat_senza_nome"] += 1
            continue
        presi = per_file[slug][2] if slug in per_file else []
        nuovi, conti_qui, scarti_qui = nuovi_per(esistente, messaggi, presi)
        conti.update(conti_qui)
        scarti.update(scarti_qui)
        conti["messaggi_nuovi"] += len(nuovi)
        conti["mittente_sconosciuto"] += sum(1 for m in nuovi if m["sender"] == SCONOSCIUTO)
        conti["mittente_senza_rubrica"] += sum(1 for m in nuovi if not m["_sicuro"])
        if nuovi:
            voce = per_file.setdefault(slug, [esistente, [], []])
            voce[1].append(s)
            voce[2].extend(nuovi)
    fuori = []
    for slug, (esistente, sessioni, nuovi) in per_file.items():
        conti["chat_aggiornate" if esistente else "chat_nuove"] += 1
        conti["file_con_piu_chat_del_telefono"] += len(sessioni) > 1
        nuovi = [{k: v for k, v in m.items() if k != "_sicuro"} for m in nuovi]
        fuori.append((slug, esistente, sessioni, sorted(nuovi, key=lambda m: m["timestamp"])))
    return fuori, conti, scarti


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply", action="store_true", dest="esegui", help="writes the chats (without: dry run)"
    )
    ap.add_argument("--db", default=str(COPIA), dest="copia", metavar="PATH", help="the database copy to read")
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--esegui", action="store_true", dest="esegui", help=argparse.SUPPRESS)
    ap.add_argument("--copia", dest="copia", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not Path(args.copia).is_file():
        print(f"No database copy at {args.copia}: pass --db <path>/ChatStorage.sqlite. Nothing read.")
        return 1

    st = _storico()
    chats_dir: Path = st.CHATS_DIR
    con = apri(Path(args.copia))
    chat_db = leggi_copia(con, st.OWNER_CANONICAL)
    con.close()
    da_scrivere, conti, scarti = piano(chat_db, st, chats_dir)

    print(f"chats in the database: {len(chat_db)}")
    for k in (
        "chat_aggiornate",
        "chat_nuove",
        "messaggi_nuovi",
        "gia_presenti",
        "buchi_recuperati",
        "buchi_recuperati_nei_giorni_coperti",
        "buchi_in_giorni_coperti",
        "mittente_sconosciuto",
        "mittente_senza_rubrica",
        "chat_trovate_per_numero",
        "file_con_piu_chat_del_telefono",
        "gruppi_rinominati",
        "chat_senza_nome",
    ):
        print(f"  {k}: {conti[k]}")
    print("  already present, discarded, by hour:", dict(sorted(scarti.items())))
    if not args.esegui:
        print("dry run: nothing written. To write, add --apply")
        return 0

    import wa_ricevuta

    prima = len([p for p in chats_dir.glob("*.json") if p.name != "chats-index.json"])
    rid = wa_ricevuta.inizio(
        st.RICEVUTA_DIR, "wa-l0-chatstorage.py", dichiarato="chat", cartelle=[str(args.copia)]
    )

    copia_dir = chats_dir / f"_prima-chatstorage-{datetime.now():%Y%m%d-%H%M%S}"
    copia_dir.mkdir(parents=True, exist_ok=True)
    ultimo = ""
    for slug, esistente, sessioni, nuovi in da_scrivere:
        file = chats_dir / f"{slug}.json"
        if file.exists():
            shutil.copy2(file, copia_dir / file.name)
        nuovo = {
            "chat_name": sessioni[0]["nome"],
            "source_file": "ChatStorage.sqlite",
            "messages": nuovi,
            "participants": dict(Counter(m["sender"] for m in nuovi)),

            "phone_numbers": {numero_di(s): s["nome"] for s in sessioni if numero_di(s)},
        }
        if esistente:
            unita, _, _ = st.merge_chats(esistente, nuovo)
        else:
            unita = nuovo
        unita[NUMERI_DAL_TELEFONO] = sorted(
            {*((esistente or {}).get(NUMERI_DAL_TELEFONO) or []), *nuovo["phone_numbers"]}
        )
        st.write_chat(slug, unita)
        ultimo = max(ultimo, nuovi[-1]["timestamp"])
    st.regenerate_index()
    dopo = len([p for p in chats_dir.glob("*.json") if p.name != "chats-index.json"])
    wa_ricevuta.fine(
        st.RICEVUTA_DIR,
        rid,
        "wa-l0-chatstorage.py",
        viste=len(chat_db),
        nuove=conti["chat_nuove"],
        aggiornate=conti["chat_aggiornate"],
        uguali=len(chat_db) - sum(len(sessioni) for _, _, sessioni, _ in da_scrivere),
        errori=0,
        chat_prima=prima,
        chat_dopo=dopo,
        dati_fino_al=ultimo or None,
        dichiarato="chat",
        messaggi_nuovi=conti["messaggi_nuovi"],
        gia_presenti=conti["gia_presenti"],
    )
    print(
        f"✅ wrote {len(da_scrivere)} chats ({conti['messaggi_nuovi']} messages); previous copy in {copia_dir.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
