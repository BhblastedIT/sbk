#!/usr/bin/env python3
"""Versions of the SecondBrain app: the release manifest tools/secondbrain/versioni.json (current version and
history), and the proposal for the next version from the commits that touched the app since the last release.

Usage: uv run python tools/secondbrain/sb_versioni.py [--bump]   (prints the manifest, or the proposed bump)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
MANIFEST = QUI / "versioni.json"

AREA_APP = "tools/secondbrain/app"
AREA_BACKEND = ("tools/secondbrain/sb-app.py", "tools/secondbrain/sb_")


def _git(args: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def leggi() -> dict:
    ""
    try:
        d = json.loads(MANIFEST.read_text())
        if isinstance(d, dict) and "corrente" in d and isinstance(d.get("storia"), list):
            return d
    except Exception:
        pass
    return {"corrente": "0.0.0", "storia": []}


def _scrivi(d: dict) -> None:
    ""
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, MANIFEST)


def corrente() -> str:
    ""
    return str(leggi().get("corrente") or "0.0.0")


def storia() -> list[dict]:
    return list(leggi().get("storia") or [])


def trova_per_impronta(contenuto: str) -> dict | None:
    ""

    if not contenuto:
        return None
    for e in storia():
        if e.get("contenuto") == contenuto:
            return e
    return None


def _ver_tuple(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)  # type: ignore[return-value]


def _commit_app_corrente() -> str:
    ""
    return _git(["log", "-1", "--format=%h", "--", AREA_APP])


def proponi_bump(da_commit: str | None = None) -> dict:
    ""



    base = leggi()
    attuale = str(base.get("corrente") or "0.0.0")
    ma, mi, pa = _ver_tuple(attuale)

    if not da_commit:
        st = base.get("storia") or []
        da_commit = (st[0].get("commit") if st else "") or ""
    intervallo = f"{da_commit}..HEAD" if da_commit else "HEAD"
    grezzo = _git(["log", intervallo, "--format=%h%x09%s", "--", AREA_APP])
    righe = [r for r in grezzo.splitlines() if "\t" in r]
    soggetti = [r.split("\t", 1)[1].strip() for r in righe]
    novita = [_pulisci_soggetto(s) for s in soggetti]
    novita = [n for n in novita if n]
    if any(re.match(r"^feat(\(|:|!)", s) for s in soggetti):
        livello, prossima = "minor", f"{ma}.{mi + 1}.0"
    elif soggetti:
        livello, prossima = "patch", f"{ma}.{mi}.{pa + 1}"
    else:
        livello, prossima = "patch", f"{ma}.{mi}.{pa + 1}"
    return {
        "prossima": prossima,
        "livello": livello,
        "novita": novita,
        "commit": _commit_app_corrente(),
    }


_TIPO = re.compile(r"^(feat|fix|refactor|perf|chore|docs|content|style|test)(\([^)]*\))?(!)?:\s*")


def _pulisci_soggetto(s: str) -> str:
    ""

    s = _TIPO.sub("", s).strip()
    return s[:1].upper() + s[1:] if s else s


def aggiungi_rilascio(
    versione: str,
    commit: str,
    contenuto: str,
    firma: str,
    canale: str,
    novita: list[str],
    data: str | None = None,
) -> dict:
    ""

    import datetime

    d = leggi()
    st = d.get("storia") or []
    if st and st[0].get("contenuto") == contenuto and st[0].get("canale") == canale:
        return d
    entry = {
        "versione": versione,
        "data": data or datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": commit,
        "contenuto": contenuto,
        "firma": firma,
        "canale": canale,
        "novita": list(novita or []),
    }
    d["storia"] = [entry, *st]
    if canale == "swift":
        d["corrente"] = versione
    _scrivi(d)
    return d


if __name__ == "__main__":
    import argparse

    _ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ap.add_argument("--bump", action="store_true", help="propose the next version from the commits since the last")
    if _ap.parse_args().bump:
        print(json.dumps(proponi_bump(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(leggi(), ensure_ascii=False, indent=2))
