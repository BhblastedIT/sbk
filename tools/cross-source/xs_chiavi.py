#!/usr/bin/env python3
"""Queue of model API keys (Anthropic): list them, import the key from .env into the Keychain, rename, re-enable or activate an archived one. With no subcommand it lists the queue."""





































from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from sbk_config import DATA_ROOT  # noqa: E402

SERVIZIO = "sbk-anthropic"
STATO = DATA_ROOT / "system" / "chiavi-anthropic.json"

PAUSA_DOPO_ERRORE_S = 24 * 3600



SENZA_SCADENZA = frozenset({"non autorizzata"})


def _in_pausa(ev: dict, adesso: float) -> bool:
    if not ev.get("errore_quando"):
        return False
    if ev.get("errore") in SENZA_SCADENZA:
        return True
    return adesso - ev["errore_quando"] < PAUSA_DOPO_ERRORE_S



ORIGINI = (
    ("sbk", _TOOLS.parent / ".env", ".env of the SBK repo"),
)
# Optional second secrets file: path from the SBK_SECRETS_FILE environment variable.
_extra_secrets = os.environ.get("SBK_SECRETS_FILE")
if _extra_secrets:
    ORIGINI = ORIGINI + (("extra", Path(_extra_secrets), "SBK_SECRETS_FILE"),)
_RE_RIGA = re.compile(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.+?)\s*$")


def _leggi_segreto(nome: str) -> str | None:
    from secrets_adapter import get_secret

    return get_secret(SERVIZIO, nome)


def _scrivi_segreto(nome: str, valore: str) -> None:
    from secrets_adapter import set_secret

    set_secret(SERVIZIO, nome, valore)


@contextmanager
def _stato_bloccato():
    ""
    STATO.parent.mkdir(parents=True, exist_ok=True)
    with (STATO.parent / ".chiavi-anthropic.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            stato = json.loads(STATO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stato = {"coda": [], "turno": 0, "eventi": {}}
        yield stato
        tmp = STATO.with_name(f"{STATO.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STATO)


def _leggi_stato() -> dict:
    try:
        return json.loads(STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"coda": [], "turno": 0, "eventi": {}}


def elenco() -> list[dict]:
    ""
    stato = _leggi_stato()
    coda = stato.get("coda", [])
    turno = stato.get("turno", 0) % len(coda) if coda else 0
    adesso = time.time()
    out = []
    for i, voce in enumerate(coda):
        ev = stato.get("eventi", {}).get(voce["nome"], {})
        errore_t = ev.get("errore_quando", 0)
        out.append(
            {
                "nome": voce["nome"],
                "origine": voce.get("origine", ""),
                "presente": _leggi_segreto(voce["nome"]) is not None,
                "di_turno": i == turno,
                "ultimo_uso": ev.get("uso_quando"),
                "errore": ev.get("errore") if _in_pausa(ev, adesso) else None,
                "errore_quando": errore_t or None,
            }
        )
    return out


def scegli(preferita: str | None = None) -> tuple[str, str] | None:
    ""




    adesso = time.time()
    with _stato_bloccato() as stato:
        coda = [v["nome"] for v in stato.get("coda", [])]
        if not coda:
            return None
        eventi = stato.setdefault("eventi", {})

        def utilizzabile(nome: str) -> bool:
            return not _in_pausa(eventi.get(nome, {}), adesso)

        candidati = []


        if preferita in coda and utilizzabile(preferita):
            candidati.append(preferita)
        inizio = stato.get("turno", 0) % len(coda)
        ordine = coda[inizio:] + coda[:inizio]
        candidati += [n for n in ordine if utilizzabile(n) and n not in candidati]

        candidati += [n for n in ordine if n not in candidati]
        for nome in candidati:
            valore = _leggi_segreto(nome)
            if not valore:
                continue
            if nome != preferita:
                stato["turno"] = (coda.index(nome) + 1) % len(coda)
            eventi.setdefault(nome, {})["uso_quando"] = adesso
            return nome, valore
    return None


def segna_errore(nome: str, tipo: str) -> None:
    ""
    if not nome:
        return
    with _stato_bloccato() as stato:
        ev = stato.setdefault("eventi", {}).setdefault(nome, {})
        ev["errore"] = tipo
        ev["errore_quando"] = time.time()


def prossima_dopo(nome: str) -> tuple[str, str] | None:
    ""
    stato = _leggi_stato()
    coda = [v["nome"] for v in stato.get("coda", [])]
    if nome not in coda or len(coda) < 2:
        return None
    i = coda.index(nome)
    for altro in coda[i + 1 :] + coda[:i]:
        valore = _leggi_segreto(altro)
        ev = stato.get("eventi", {}).get(altro, {})
        if valore and not _in_pausa(ev, time.time()):
            return altro, valore
    return None


def riabilita(nome: str) -> str:
    ""
    with _stato_bloccato() as stato:
        ev = stato.get("eventi", {}).get(nome)
        if not ev or not ev.get("errore"):
            return f"«{nome}» was not set aside"
        prima = ev.pop("errore")
        ev.pop("errore_quando", None)
    return f"«{nome}» returns to the rotation (was set aside: {prima})"


def importa() -> list[str]:
    ""



    righe = []
    visti: dict[str, str] = {}
    with _stato_bloccato() as stato:
        coda = stato.setdefault("coda", [])
        nomi = {v["nome"] for v in coda}
        for nome, file, origine in ORIGINI:
            if not file.exists():
                righe.append(f"{nome}: {origine} not found")
                continue
            valore = next(
                (
                    m.group(1).strip().strip('"').strip("'")
                    for r in file.read_text(errors="replace").splitlines()
                    if (m := _RE_RIGA.match(r))
                ),
                None,
            )
            if not valore:
                righe.append(f"{nome}: no key in {origine}")
                continue
            if valore in visti:
                righe.append(
                    f"{nome}: same key as «{visti[valore]}», not adding it twice"
                )
                continue
            visti[valore] = nome
            _scrivi_segreto(nome, valore)
            if nome not in nomi:
                coda.append(
                    {"nome": nome, "origine": origine, "aggiunta": time.strftime("%Y-%m-%d")}
                )
                nomi.add(nome)
            righe.append(f"{nome}: in the Keychain, from {origine}")
    return righe


def archivia(nome: str, valore: str, **dati: str) -> str:
    ""




    with _stato_bloccato() as stato:
        if nome in {v["nome"] for v in stato.get("coda", [])}:
            return f"«{nome}» is in the queue, not archiving it"
        _scrivi_segreto(nome, valore)
        archivio = stato.setdefault("archivio", [])
        voce = next((v for v in archivio if v["nome"] == nome), None)
        if voce is None:
            voce = {"nome": nome, "aggiunta": time.strftime("%Y-%m-%d")}
            archivio.append(voce)
        voce.update(dati)
    return f"«{nome}» in the archive, idle"


def elenco_archivio() -> list[dict]:
    ""
    return [
        {**voce, "presente": _leggi_segreto(voce["nome"]) is not None}
        for voce in _leggi_stato().get("archivio", [])
    ]


def attiva(nome: str) -> str:
    ""
    with _stato_bloccato() as stato:
        archivio = stato.get("archivio", [])
        voce = next((v for v in archivio if v["nome"] == nome), None)
        if voce is None:
            return f"«{nome}» is not in the archive"
        archivio.remove(voce)
        stato.setdefault("coda", []).append(
            {
                "nome": nome,
                "origine": f"archivio: {voce.get('org', '')}".strip(),
                "aggiunta": time.strftime("%Y-%m-%d"),
            }
        )
    return f"«{nome}» is now in the queue"


def rinomina(vecchio: str, nuovo: str) -> str:
    valore = _leggi_segreto(vecchio)
    if not valore:
        return f"«{vecchio}» not found in the Keychain"
    _scrivi_segreto(nuovo, valore)
    with _stato_bloccato() as stato:
        for v in stato.get("coda", []):
            if v["nome"] == vecchio:
                v["nome"] = nuovo
        ev = stato.get("eventi", {})
        if vecchio in ev:
            ev[nuovo] = ev.pop(vecchio)

    return f"«{vecchio}» is now called «{nuovo}». The old entry in the Keychain stays until it is explicitly removed."


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Queue of model API keys"])[0]
    )
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("elenco", help="list the keys in the queue (the default)")
    sub.add_parser("importa", help="copy ANTHROPIC_API_KEY from .env into the Keychain and the queue")
    sub.add_parser("archivio", help="list the archived keys, kept idle")
    at = sub.add_parser("attiva", help="move an archived key into the queue")
    at.add_argument("nome", metavar="NAME")
    ri = sub.add_parser("rinomina", help="rename a key")
    ri.add_argument("vecchio", metavar="OLD")
    ri.add_argument("nuovo", metavar="NEW")
    ra = sub.add_parser("riabilita", help="put a key that was set aside after an error back in rotation")
    ra.add_argument("nome", metavar="NAME")
    args = ap.parse_args()
    if args.cmd in (None, "elenco"):
        print(json.dumps(elenco(), ensure_ascii=False, indent=2))
    elif args.cmd == "importa":
        print("\n".join(importa()))
    elif args.cmd == "archivio":
        print(json.dumps(elenco_archivio(), ensure_ascii=False, indent=2))
    elif args.cmd == "attiva":
        print(attiva(args.nome))
    elif args.cmd == "riabilita":
        print(riabilita(args.nome))
    else:
        print(rinomina(args.vecchio, args.nuovo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
