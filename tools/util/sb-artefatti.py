#!/usr/bin/env python3
"""Who writes and who reads each file of the data root: lists the files nobody reads and the reads of files nobody writes."""



































from __future__ import annotations

import argparse
import ast
import functools
import json
import os
import re
import sys
from collections import defaultdict





from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODICE = REPO / "tools"
DATO = Path.home() / ".sbk-data"
RAPPORTO = REPO / "docs" / "sbk" / "audits" / "ARTEFATTI.json"


RUMORE = {"", ".", "..", "/", "*", "json", "parquet", "data", "tmp", "out", "test"}


_PERCORSO = re.compile(r"""["']([\w][\w./-]*\.(?:parquet|json|jsonl|db|duckdb|csv))["']""")
_CARTELLA = re.compile(
    r"""["']((?:knowledge|l3|l0|l1|l2|rq|events|epistemic|archive)/[\w./-]+)["']"""
)

SCRITTURA = ("write", "to_parquet", "to_csv", "dump", "safe_write", "mkdir", "open(")
LETTURA = ("read", "load", "glob", "iterdir", "listdir", "exists", "ParquetFile")


def _script_python() -> list[Path]:
    fuori = {"_deprecated", "__pycache__", ".venv", "node_modules"}



    return [p for p in CODICE.rglob("*.py") if not (fuori & set(p.parts))]


def _verso(riga: str) -> str | None:
    ""
    b = riga.lower()
    scrive = any(t in b for t in SCRITTURA)
    legge = any(t in b for t in LETTURA)
    if scrive and not legge:
        return "scrive"
    if legge and not scrive:
        return "legge"
    if scrive and legge:
        return "scrive" if re.search(r"""["'][wax]b?\+?["']""", riga) else "legge"
    return None


def _costanti(albero: ast.AST) -> dict[str, str]:
    ""






    fuori: dict[str, str] = {}
    for n in ast.walk(albero):
        if not isinstance(n, ast.Assign):
            continue
        nome_file = None
        if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            if m := _PERCORSO.search(f'"{n.value.value}"'):
                nome_file = m.group(1)
        elif isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Div):

            d = n.value.right
            if isinstance(d, ast.Constant) and isinstance(d.value, str):
                if m := _PERCORSO.search(f'"{d.value}"'):
                    nome_file = m.group(1)
        if nome_file:
            for t in n.targets:
                if isinstance(t, ast.Name):
                    fuori[t.id] = nome_file
    return fuori


def _costanti_condivise() -> dict[str, str]:
    ""




    cfg = CODICE / "sbk_config.py"
    if not cfg.exists():
        return {}
    try:
        return _costanti(ast.parse(cfg.read_text(encoding="utf-8")))
    except (OSError, SyntaxError):
        return {}


def censisci() -> dict[str, dict[str, list[str]]]:
    ""
    mappa: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"scrive": set(), "legge": set()})
    condivise = _costanti_condivise()
    for p in _script_python():
        try:
            testo = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nome = str(p.relative_to(REPO))
        try:
            costanti = {**condivise, **_costanti(ast.parse(testo))}
        except SyntaxError:
            costanti = dict(condivise)
        for riga in testo.splitlines():
            if riga.lstrip().startswith("#"):
                continue
            v = _verso(riga)
            if v is None:
                continue
            trovati = {m.group(1) for m in _PERCORSO.finditer(riga)}
            trovati |= {m.group(1) for m in _CARTELLA.finditer(riga)}
            for nome_cost, percorso in costanti.items():
                if re.search(rf"\b{re.escape(nome_cost)}\b", riga):
                    trovati.add(percorso)
            for a in trovati:
                if a.lower() not in RUMORE:
                    mappa[a][v].add(nome)
    return {a: {k: sorted(v) for k, v in d.items()} for a, d in sorted(mappa.items())}


@functools.lru_cache(maxsize=1)
def _indice_del_dato() -> dict[str, Path]:
    ""






    indice: dict[str, Path] = {}
    for radice, _, files in os.walk(DATO):
        r = Path(radice)
        for n in files:
            indice.setdefault(n, r / n)
    return indice


def _su_disco(artefatto: str) -> tuple[bool, float | None, int | None]:
    ""
    adesso = datetime.now().timestamp()
    for c in (DATO / artefatto, DATO / Path(artefatto).name):
        if c.exists():
            st = c.stat()
            return True, round((adesso - st.st_mtime) / 86400, 1), st.st_size
    trovato = _indice_del_dato().get(Path(artefatto).name)
    if trovato:
        try:
            st = trovato.stat()
        except FileNotFoundError:


            return False, None, None
        return True, round((adesso - st.st_mtime) / 86400, 1), st.st_size
    return False, None, None


def analizza() -> dict:
    mappa = censisci()
    orfani, fantasmi, vivi = [], [], []
    for a, d in mappa.items():
        esiste, eta, peso = _su_disco(a)
        voce = {
            "artefatto": a,
            "scritto_da": d["scrive"],
            "letto_da": d["legge"],
            "esiste": esiste,
            "giorni": eta,
            "byte": peso,
        }
        if d["scrive"] and not d["legge"]:
            orfani.append(voce)
        elif d["legge"] and not d["scrive"]:
            fantasmi.append(voce)
        else:
            vivi.append(voce)
    orfani.sort(key=lambda v: -(v["byte"] or 0))
    fantasmi.sort(key=lambda v: v["artefatto"])
    return {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "artefatti": len(mappa),
        "orfani": orfani,
        "fantasmi": fantasmi,
        "collegati": len(vivi),
    }


def _stampa(r: dict) -> None:
    print(
        f"\n  {r['artefatti']} artifacts cited in the code · {r['collegati']} with at least one reader and one writer\n"
    )
    o = [v for v in r["orfani"] if v["esiste"]]
    print(
        f"  ORPHANS — written and never re-read: {len(o)} exist on disk (out of {len(r['orfani'])} cited)\n"
    )
    for v in o[:15]:
        p = f"{v['byte'] / 1e6:.1f} MB" if v["byte"] else "?"
        print(f"    {v['artefatto'][:52]:<52} {p:>9}  idle for {v['giorni']:>5.0f} d")
        print(f"      written by: {', '.join(Path(s).name for s in v['scritto_da'][:3])}")
    f = [v for v in r["fantasmi"] if not v["esiste"]]
    print(
        f"\n  GHOSTS — no writer found: {len(r['fantasmi'])}, of which {len(f)} do not exist"
    )
    print("  ⚠️ CIRCUMSTANTIAL category: a writer that builds the name at runtime is invisible")
    print(
        "     to static analysis. Only the non-existent ones mean anything, and must be opened by hand.\n"
    )
    for v in f[:8]:
        print(f"    {v['artefatto'][:52]:<52} read by: {Path(v['letto_da'][0]).name}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", action="store_true", help="print the raw report")
    ap.add_argument(
        "--controlla",
        action="store_true",
        help="exit 1 if there are new orphans vs the report",
    )
    a = ap.parse_args()

    r = analizza()
    if a.controlla:
        if not RAPPORTO.exists():
            print("no previous report: run it once without --controlla")
            return 0
        prima = {v["artefatto"] for v in json.loads(RAPPORTO.read_text(encoding="utf-8"))["orfani"]}
        nuovi = sorted({v["artefatto"] for v in r["orfani"] if v["esiste"]} - prima)
        if nuovi:
            print("new artifacts that nobody re-reads:")
            for n in nuovi:
                print(f"  {n}")
            print("\nif intended, regenerate the report; if not, a reader is missing.")
            return 1
        return 0

    RAPPORTO.parent.mkdir(parents=True, exist_ok=True)
    RAPPORTO.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=2, ensure_ascii=False)) if a.json else _stampa(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
