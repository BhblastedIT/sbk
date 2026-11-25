#!/usr/bin/env python3
""














from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]




INNOCUI: dict[str, list[str]] = {
    "xs-l2-knowledge-extract.py": ["--source", "personio", "--dry-run"],
    "l4-01-email-anchor.py": [],
    "l4-03-exact-dedup.py": [],
    "l4-04-fuzzy-merge.py": ["--help"],
    "l4-06-partial-name-resolve.py": ["--phase", "1"],
    "xs-l4-reclassify-entities.py": ["--help"],
    "xs-l4-store-health.py": ["--json"],
    "xs-l3-riancora-relazioni.py": [],
    "xs-l3-rigenera-relazioni.py": ["--sorgente", "voice_memo"],
    "xs-l3-confronta-relazioni.py": ["--help"],
    "xs-l4-disfa-fusione.py": ["--entita", "person_inesistente"],
    "sb-copertura.py": ["--presidio", "episodio"],
    "sb-vocabolario.py": ["--help"],
    "sb-stale-check.py": ["--tipo", "vivo"],
    "sb-persone.py": ["--help"],
    "sb-identita.py": ["--help"],
    "sb-entita.py": ["--help"],
    "sb-mononimi.py": ["--help"],
    "sb-rinomina.py": ["--help"],
}


def _trova(nome: str) -> Path | None:
    for p in (REPO / "tools").rglob(nome):
        if "_deprecated" not in p.parts:
            return p
    return None


def _toccati(giorni: int) -> set[str]:
    ""
    try:
        fuori = subprocess.run(  # noqa: S603
            ["git", "log", f"--since={giorni}.days", "--name-only", "--format="],  # noqa: S607
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return set()
    return {Path(r).name for r in fuori.splitlines() if r.strip().endswith(".py")}


def prova(nome: str, argomenti: list[str], timeout: int = 900) -> dict:
    percorso = _trova(nome)
    if percorso is None:
        return {"script": nome, "esito": "NON TROVATO"}
    t = time.time()
    try:
        r = subprocess.run(  # noqa: S603
            [sys.executable, str(percorso), *argomenti],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO / "tools")},
        )
    except subprocess.TimeoutExpired:
        return {"script": nome, "esito": f"TIMEOUT ({timeout}s)"}
    durata = time.time() - t



    coda = (r.stderr or "")[-2000:]
    rotto = "Traceback (most recent call last)" in coda
    return {
        "script": nome,
        "esito": "ROTTO" if rotto else ("ok" if r.returncode == 0 else f"exit {r.returncode}"),
        "secondi": round(durata, 1),
        "errore": [x for x in coda.splitlines() if x.strip()][-1][:120] if rotto else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Every touched script must at least start")
    ap.add_argument("--da", type=int, default=0, help="only those touched in the last N days")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    da_provare = dict(INNOCUI)
    if a.da:
        recenti = _toccati(a.da)
        da_provare = {k: v for k, v in INNOCUI.items() if k in recenti}
        print(
            f"touched in the last {a.da} days: {len(da_provare)} of {len(INNOCUI)} watched"
        )

    rotti = []
    for nome, argomenti in da_provare.items():
        r = prova(nome, argomenti, a.timeout)
        segno = "❌" if r["esito"] in ("ROTTO", "NON TROVATO") or "TIMEOUT" in r["esito"] else "  "
        print(f"{segno} {nome:38} {r['esito']:12} {r.get('secondi', '')}s")
        if r.get("errore"):
            print(f"     {r['errore']}")
        if segno == "❌":
            rotti.append(nome)

    print()
    if rotti:
        print(f"❌ {len(rotti)} scripts do not start: {', '.join(rotti)}")
        return 1
    print(f"✅ all {len(da_provare)} start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
