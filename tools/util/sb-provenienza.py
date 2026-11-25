#!/usr/bin/env python3
"""Tripwire: record-level fields such as extracted_at must not come back as fact keys; compares the code with a ratchet baseline."""







































from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
BASELINE = RADICE / "docs" / "sbk" / "audits" / "PROVENIENZA-13.json"










MODULI_SENSIBILI = (
    "tools/cross-source/xs_knowledge_conflict.py",
    "tools/cross-source/xs-l2-knowledge-extract.py",
    "tools/cross-source/xs-l4-compact-observations.py",
    "tools/cross-source/xs-l4-reanchor-facts.py",
    "tools/cross-source/l4-05-confidence-recal.py",
    "tools/knowledge_view.py",
)












LETTURA_EA = re.compile(r"""extracted_at""")
CONTESTO_LECITO = re.compile(
    r"""record\s*(?:\.\s*extracted_at
        |\[\s*["']extracted_at["']\s*\]
        |\.\s*get\(\s*["']extracted_at["'])""",
    re.VERBOSE,
)




LETTURA_CREATED_AT = re.compile(
    r"""(?:f|fact|ef|other|fatto)\s*(?:\.get\(\s*|\[\s*)["']created_at["']"""
)


def solo_codice(sorgente: str) -> list[str]:
    ""















    righe = sorgente.splitlines()
    pulite = list(righe)

    def sbianca(r1: int, c1: int, r2: int, c2: int) -> None:
        for r in range(r1, r2 + 1):
            i = r - 1
            if i >= len(pulite):
                return
            a = c1 if r == r1 else 0
            b = c2 if r == r2 else len(pulite[i])
            pulite[i] = pulite[i][:a] + " " * max(0, b - a) + pulite[i][b:]

    try:
        for tok in tokenize.generate_tokens(io.StringIO(sorgente).readline):
            if tok.type == tokenize.COMMENT:
                sbianca(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
        albero = ast.parse(sorgente)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return righe
    for nodo in ast.walk(albero):
        corpo = getattr(nodo, "body", None)

        if not isinstance(corpo, list):
            continue
        for figlio in corpo:
            if (
                isinstance(figlio, ast.Expr)
                and isinstance(figlio.value, ast.Constant)
                and isinstance(figlio.value.value, str)
            ):
                v = figlio.value
                sbianca(v.lineno, v.col_offset, v.end_lineno or v.lineno, v.end_col_offset or 0)
    return pulite


def scandisci() -> dict:
    trovate: dict[str, list] = {}
    for rel in MODULI_SENSIBILI:
        p = RADICE / rel
        if not p.is_file():
            trovate.setdefault("__mancanti__", []).append(rel)
            continue
        sorgente = p.read_text(encoding="utf-8")
        originali = sorgente.splitlines()
        for n, riga in enumerate(solo_codice(sorgente), 1):
            nudo = originali[n - 1].strip()















            if any(
                "prov13: discrimina" in originali[k]
                for k in range(max(0, n - 4), min(len(originali), n + 2))
            ):
                continue
            senza_lecito = CONTESTO_LECITO.sub(" ", riga)
            if LETTURA_EA.search(senza_lecito):
                trovate.setdefault(rel, []).append([n, "extracted_at", nudo[:110]])
            elif LETTURA_CREATED_AT.search(riga):
                trovate.setdefault(rel, []).append([n, "created_at (shadow)", nudo[:110]])
    return trovate


def conta(trovate: dict) -> int:
    return sum(len(v) for k, v in trovate.items() if k != "__mancanti__")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--controlla", action="store_true", help="compare with the ratchet")
    ap.add_argument("--scrivi-baseline", action="store_true", help="set the ratchet to today")
    a = ap.parse_args()

    trovate = scandisci()
    n = conta(trovate)

    if a.scrivi_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(
                {
                    "invariante": "no record field in identity, dedup, anchor, conflict",
                    "fissato_il": datetime.now(timezone.utc).date().isoformat(),  # noqa: UP017
                    "letture": n,
                    "dettaglio": trovate,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"ratchet set to {n} reads → {BASELINE.relative_to(RADICE)}")
        return 0

    if not a.controlla:
        for rel, righe in sorted(trovate.items()):
            if rel == "__mancanti__":
                continue
            print(rel)
            for ln, tipo, testo in righe:
                print(f"  {ln:>5}  [{tipo}]  {testo}")
        print(f"\ntotal record-side reads in the sensitive modules: {n}")
        return 0

    if not BASELINE.is_file():
        print(f"ratchet missing: run --scrivi-baseline ({BASELINE})", file=sys.stderr)
        return 1
    atteso = json.loads(BASELINE.read_text()).get("letture", 0)
    if n > atteso:
        print(
            f"INVARIANT WORSENED: {n} record-side reads against {atteso} in the ratchet.\n"
            "  A RECORD field came back where an identity, a key, "
            "an anchor or a conflict is decided.\n"
            "  The record changes on every run without the world changing: it is the mechanism "
            "of mass de-anchoring of the facts.\n"
            "  See the rows with: uv run python tools/util/sb-provenienza.py",
            file=sys.stderr,
        )
        return 1
    if n < atteso:
        print(
            f"improved: {n} reads against {atteso}. Lower the ratchet again with "
            "--scrivi-baseline."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
