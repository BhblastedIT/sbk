"""Receipt of every WhatsApp import: what came in, when, and whether it was every chat of the phone.

Used by wa-l0l3-full.py, wa-l0-import-history.py and wa-l0-chatstorage.py. One JSON line per event in
<data root>/whatsapp/_ricevute-import.jsonl: a "start" event before the chats are touched, an "end" event
after the index is written. A "start" without its "end" is an import that stopped half way. Receipts
written by older versions use "inizio"/"fine" and "completo"/"chat"; readers accept both spellings.
"""











from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

NOME = "_ricevute-import.jsonl"


SOGLIA_CHAT = 200
SOGLIA_QUOTA = 0.5

# Event and kind names written in the receipt (English), with the older Italian spellings readers accept.
EVENTO_INIZIO = "start"
EVENTO_FINE = "end"
EVENTI_INIZIO = ("start", "inizio")
EVENTI_FINE = ("end", "fine")
COMPLETO = "complete"
CHAT = "chat-only"
TIPI_COMPLETO = ("complete", "completo")
_DICHIARAZIONI = {"complete": COMPLETO, "completo": COMPLETO, "chat-only": CHAT, "chat": CHAT}


def normalizza_dichiarato(valore: str | None) -> str | None:
    """Map --declare values (English, or the older Italian completo/chat) to complete / chat-only."""
    if valore is None:
        return None
    return _DICHIARAZIONI.get(str(valore).strip().lower(), str(valore))


def add_declare_argument(parser) -> None:
    """--declare complete|chat-only (the older --dichiara completo|chat is a hidden alias)."""
    import argparse

    parser.add_argument(
        "--declare",
        dest="dichiara",
        type=normalizza_dichiarato,
        choices=(COMPLETO, CHAT),
        default=None,
        help="Declare the import kind in the receipt: complete (every chat of the phone) or "
        "chat-only (only some chats)",
    )
    parser.add_argument(
        "--dichiara",
        dest="dichiara",
        type=normalizza_dichiarato,
        choices=(COMPLETO, CHAT),
        default=None,
        help=argparse.SUPPRESS,
    )


def classifica(viste: int, chat_prima: int, dichiarato: str | None = None) -> tuple[str, str]:
    ""




    dichiarato = normalizza_dichiarato(dichiarato)
    if dichiarato in (COMPLETO, CHAT):
        return dichiarato, "declared"
    if viste >= SOGLIA_CHAT:
        return COMPLETO, f"at least {SOGLIA_CHAT} chats"
    if viste and not chat_prima:
        return COMPLETO, "first import"
    if viste and viste >= SOGLIA_QUOTA * chat_prima:
        return COMPLETO, "more than half the chats already known"
    return CHAT, "few chats"


def _ora() -> str:

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _scrivi(radice: Path, riga: dict) -> None:
    radice.mkdir(parents=True, exist_ok=True)


    with open(radice / NOME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(riga, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def inizio(
    radice: Path, script: str, dichiarato: str | None = None, cartelle: list[str] | None = None
) -> str:
    ""
    rid = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    _scrivi(
        radice,
        {
            "v": 1,
            "evento": EVENTO_INIZIO,
            "id": rid,
            "ora": _ora(),
            "script": script,
            "pid": os.getpid(),
            "dichiarato": normalizza_dichiarato(dichiarato),
            "cartelle": cartelle or [],
        },
    )
    return rid


def fine(
    radice: Path,
    rid: str,
    script: str,
    *,
    viste: int,
    nuove: int,
    aggiornate: int,
    uguali: int,
    errori: int,
    chat_prima: int,
    chat_dopo: int,
    dati_fino_al: str | None,
    dichiarato: str | None = None,
    esito: str = "ok",
    **altro,
) -> dict:
    ""



    tipo, perche = classifica(viste, chat_prima, dichiarato)
    adesso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if dati_fino_al and str(dati_fino_al)[:19] > adesso:
        dati_fino_al = None
    riga = {
        "v": 1,
        "evento": EVENTO_FINE,
        "id": rid,
        "ora": _ora(),
        "script": script,
        "esito": esito,
        "tipo": tipo,
        "perche": perche,
        "viste": viste,
        "nuove": nuove,
        "aggiornate": aggiornate,
        "uguali": uguali,
        "errori": errori,
        "chat_prima": chat_prima,
        "chat_dopo": chat_dopo,
        "dati_fino_al": dati_fino_al,
        **altro,
    }
    _scrivi(radice, riga)
    return riga
