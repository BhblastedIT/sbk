#!/usr/bin/env python3
"""Pre-commit guard: real bank account numbers (IBANs whose check digit validates) must not enter the repo.

Usage:
    python tools/util/sb-pii.py <file> ...    check these files
    python tools/util/sb-pii.py --all         check every file tracked by git (--tutto is an alias)

A fake value for a fixture must NOT pass the check digit. A real one that has to stay is declared on its line
with `# pii-ok: <why>`.
"""








































from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path




IBAN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}[0-9]{2}[A-Z0-9]{11,30})(?![A-Z0-9])")



VIA_DUSCITA = re.compile(r"(?:#|<!--)\s*pii-ok:", re.I)







CARTELLE_GREZZE = ("materiali", "raw")



SALTA_SUFFISSI = {
    ".parquet",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".gz",
    ".db",
    ".sqlite",
    ".ico",
    ".woff",
    ".woff2",
    ".lock",
}


def _mod97(iban: str) -> int:
    ""

    ruotato = iban[4:] + iban[:4]
    cifre = "".join(str(int(c, 36)) for c in ruotato)
    resto = 0
    for c in cifre:
        resto = (resto * 10 + int(c)) % 97
    return resto


def e_un_conto_vero(candidato: str) -> bool:
    ""




    if not (15 <= len(candidato) <= 34):
        return False
    try:
        return _mod97(candidato) == 1
    except ValueError:
        return False


def trovati(percorso: Path) -> list[tuple[int, str]]:
    ""
    if percorso.suffix.lower() in SALTA_SUFFISSI or not percorso.is_file():
        return []
    if any(parte in CARTELLE_GREZZE for parte in percorso.parts[:-1]):
        return []
    try:
        testo = percorso.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    esiti: list[tuple[int, str]] = []
    for n, riga in enumerate(testo.splitlines(), 1):
        if VIA_DUSCITA.search(riga):
            continue
        for m in IBAN_RE.finditer(riga):
            if e_un_conto_vero(m.group(1)):
                esiti.append((n, m.group(1)))
    return esiti


def _tracciati() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=False).stdout
    return [Path(r) for r in out.splitlines() if r]


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--all" in argv or "--tutto" in argv:
        file = _tracciati()
    else:
        file = [Path(a) for a in argv if not a.startswith("-")]
    if not file:
        return 0

    guasti: list[str] = []
    for f in file:
        for n, iban in trovati(f):



            guasti.append(f"  {f}:{n} — {iban[:2]}…{iban[-4:]} ({len(iban)} characters)")

    if guasti:
        print("REAL bank account numbers inside files about to enter the repo:")
        print("\n".join(guasti))
        print()
        print("The check digit validates: it's an account that exists, not a made-up")
        print("value. The real data lives in ~/.sbk-data at 0600, outside the repo,")
        print("and git history is not cleaned up with a later commit.")
        print()
        print("If it's a fixture: replace it with a fake value (one that does NOT pass the")
        print("check, for example IT00X0000000000000000000000).")
        print("If it's really needed: declare it on the line with `# pii-ok: <why>`.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
