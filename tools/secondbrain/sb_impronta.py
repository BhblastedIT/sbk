""







from __future__ import annotations

import hashlib
from pathlib import Path


DENTRO = ("Package.swift", "Sources", "SBK.icon")
FUORI = frozenset({".build", ".DS_Store"})


def _righe_che_contano(p: Path) -> bytes:
    ""
    if p.suffix != ".swift":
        return p.read_bytes()
    righe = p.read_text(encoding="utf-8", errors="replace").splitlines()
    tenute = (r.rstrip() for r in righe if r.strip() and not r.lstrip().startswith("//"))
    return "\n".join(tenute).encode("utf-8")


def contenuto_app(pacchetto: Path) -> str:
    ""
    h = hashlib.sha256()
    trovati = 0
    for nome in DENTRO:
        base = pacchetto / nome
        if base.is_file():
            file = [base]
        elif base.is_dir():
            file = sorted(
                p
                for p in base.rglob("*")
                if p.is_file() and not set(p.relative_to(pacchetto).parts) & FUORI
            )
        else:
            continue
        for p in file:
            h.update(p.relative_to(pacchetto).as_posix().encode("utf-8") + b"\0")
            h.update(_righe_che_contano(p) + b"\0")
            trovati += 1
    return h.hexdigest()[:12] if trovati else ""
