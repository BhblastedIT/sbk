#!/usr/bin/env python3
"""Read-only, run by hand: finds where credentials sit in your downloaded spreadsheets (.csv, .xlsx, .xls), never what they contain."""































from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("scova-segreti")



SEGNALI: dict[str, tuple[str, ...]] = {
    "password": ("password", "passwd", "pwd", "parola d'ordine", "psw"),
    "credenziali": ("credenzial", "accessi", "login", "utenza", "utenze"),
    "chiave_api": ("api key", "api_key", "apikey", "secret key", "client secret", "token"),
    "pec": ("pec", "posta certificata", "legalmail"),
    "banca": ("iban", "bic", "swift", "carta di credito", "cvv", "num carta", "pan"),



    "cripto": ("seed phrase", "seed wallet", "private key", "mnemonic", "passphrase"),
    "identita": ("codice fiscale", "partita iva", "documento", "passaporto"),
    "otp": ("otp", "2fa", "mfa", "codice di verifica", "recovery code"),
}



DEBOLI = ("user", "username", "utente", "account", "email", "mail", "sito", "url", "portale")

MAX_BYTE = 20 * 1024 * 1024








CORTI = {"pec", "otp", "pin", "2fa", "mfa", "pwd", "psw", "bic", "pan", "iban", "cvv", "seed"}


def _conta(testo: str, parola: str) -> int:
    ""












    if " " in parola:

        return testo.count(parola)
    return len(re.findall(rf"\b{re.escape(parola)}\b", testo))


def _tipi_in(testo: str) -> dict[str, int]:
    ""
    t = testo.lower()
    fuori = {}
    for k, pat in SEGNALI.items():
        n = sum(_conta(t, p) for p in pat)
        if n:
            fuori[k] = n
    return fuori


def _righe_csv(percorso: Path) -> tuple[list[str], int]:
    ""
    try:
        with percorso.open(encoding="utf-8", errors="replace", newline="") as f:
            r = csv.reader(f)
            intest = next(r, [])
            n = sum(1 for _ in r)
        return [str(x) for x in intest], n
    except (OSError, csv.Error):
        return [], 0


def _righe_excel(percorso: Path) -> tuple[list[str], int]:
    ""











    try:
        import pandas as pd

        fogli = pd.read_excel(percorso, sheet_name=None, nrows=0)
    except Exception:  # noqa: BLE001
        return [], 0

    intest: list[str] = []
    for nome, d in fogli.items():


        intest.append(str(nome))
        intest.extend(str(c) for c in d.columns)

    n = 0
    try:
        for d in pd.read_excel(percorso, sheet_name=None, usecols=[0]).values():
            n += len(d)
    except Exception:  # noqa: BLE001
        n = 0
    return intest, n


def esamina(percorso: Path) -> dict | None:
    ""
    try:
        peso = percorso.stat().st_size
    except OSError:
        return None
    if peso > MAX_BYTE:
        return {"percorso": str(percorso), "saltato": f"{peso / 1e6:.0f} MB, over the limit"}

    if percorso.suffix.lower() in (".xlsx", ".xls"):
        intest, n_righe = _righe_excel(percorso)
        corpo = ""
    else:
        intest, n_righe = _righe_csv(percorso)


        try:
            corpo = percorso.read_text(encoding="utf-8", errors="replace")[:2_000_000]
        except OSError:
            corpo = ""

    testo_intest = " | ".join(intest)
    tipi = _tipi_in(testo_intest)


    tipi_corpo = _tipi_in(corpo) if corpo else {}
    solo_corpo = {k: v for k, v in tipi_corpo.items() if k not in tipi}

    if not tipi and not solo_corpo:
        return None



    forti = {k for k in (*tipi, *solo_corpo) if k != "identita"}
    if not forti:
        return None

    return {
        "percorso": str(percorso),
        "nome": percorso.name,
        "kb": round(peso / 1024),
        "righe": n_righe,
        "colonne": len(intest),
        "tipi_nelle_intestazioni": sorted(tipi),
        "tipi_solo_nel_corpo": sorted(solo_corpo),
        "ha_identificativi": bool([d for d in DEBOLI if d in testo_intest.lower()]),
        "modificato": datetime.fromtimestamp(percorso.stat().st_mtime, UTC).strftime("%Y-%m-%d"),
    }


def scova(dove: Path) -> dict:
    fogli = [
        p for p in dove.rglob("*") if p.is_file() and p.suffix.lower() in (".csv", ".xlsx", ".xls")
    ]
    trovati, saltati = [], []
    for p in fogli:
        v = esamina(p)
        if v is None:
            continue
        (saltati if "saltato" in v else trovati).append(v)


    trovati.sort(key=lambda v: (-len(v["tipi_nelle_intestazioni"]), -v["righe"]))
    return {"esaminati": len(fogli), "trovati": trovati, "saltati": saltati}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dove", default=str(cfg.DATA_ROOT / "gdrive"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    e = scova(Path(a.dove).expanduser())
    log.info("  sheets examined: %s", f"{e['esaminati']:,}")
    log.info("  with credential signals: %s", len(e["trovati"]))
    if e["saltati"]:
        log.info("  skipped because too large: %s", len(e["saltati"]))

    log.info("\n  ══ the sheets that DECLARE a credential in a header ══")
    caveau = [v for v in e["trovati"] if v["tipi_nelle_intestazioni"]]
    for v in caveau[:25]:
        log.info(
            "    %-46s %5s rows  %s",
            v["nome"][:46],
            f"{v['righe']:,}",
            ", ".join(v["tipi_nelle_intestazioni"]),
        )
    if not caveau:
        log.info("    (none)")
    log.info(
        "\n  other %s sheets mention credentials only in the body", len(e["trovati"]) - len(caveau)
    )

    if a.json:
        Path(a.json).write_text(json.dumps(e, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("\n  report in %s (paths and types, NEVER values)", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
