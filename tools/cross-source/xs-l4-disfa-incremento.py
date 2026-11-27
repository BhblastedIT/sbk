#!/usr/bin/env python3
"""Undoes an incremental write to the knowledge base, operation by operation in reverse order (--id; --elenca lists
the increments on disk). Dry run by default; --apply executes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools" / "cross-source") not in sys.path:
    sys.path.insert(0, str(REPO / "tools" / "cross-source"))

import incremento as inc_mod  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Undo an increment, op by op, in reverse order")
    ap.add_argument("--id", help="incremento_id (the file name without .jsonl)")
    ap.add_argument("--elenca", action="store_true", help="the increments on disk")
    ap.add_argument("--apply", action="store_true", help="execute (without it, only says what it would do)")
    ap.add_argument(
        "--anche-interrotto",
        action="store_true",
        help="proceed even if the run lacks the `fine` seal",
    )
    ap.add_argument(
        "--radice", help="a root other than ~/.sbk-data/knowledge (tests on a copy)"
    )
    a = ap.parse_args()

    radice = Path(a.radice) if a.radice else None
    if a.elenca or not a.id:
        elenco = inc_mod.elenca(radice)
        if not elenco:
            print(f"no increment in {inc_mod.cartella_incrementi(radice)}")
            print("  (no run has written an increment journal here yet)")
            return 0
        for i in elenco:
            letto = inc_mod.leggi(i, radice)
            stato = "INTERRUPTED" if letto["interrotto"] else "closed"
            print(f"  {i}  {len(letto['op']):>7} op  {stato}")
        return 0

    rapporto = inc_mod.disfa(
        a.id,
        radice=radice,
        apply=a.apply,
        anche_interrotto=a.anche_interrotto,
    )
    print(json.dumps(rapporto, indent=2, ensure_ascii=False, default=str))
    return 0 if rapporto["esito"] in ("disfatto", "da_disfare") else 1


if __name__ == "__main__":
    raise SystemExit(main())
