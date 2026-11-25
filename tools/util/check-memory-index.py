#!/usr/bin/env python3
""





























from __future__ import annotations

import re
import sys
from pathlib import Path

# Claude Code keeps a project's memory under ~/.claude/projects/<path with "-" for "/" and ".">.
INDICE = (
    Path.home()
    / ".claude/projects"
    / re.sub(r"[^A-Za-z0-9]", "-", str(Path.home() / "Projects" / "other-org"))
    / "memory/MEMORY.md"
)


TETTO_BYTE = 24_986

PREAVVISO_BYTE = 23_000

MAX_CARATTERI_VOCE = 200


MIN_VOCI_ATTESE = 10


def voci(testo: str) -> list[tuple[int, str]]:
    ""
    return [
        (n, riga) for n, riga in enumerate(testo.split("\n"), start=1) if riga.startswith("- **")
    ]


def main() -> int:
    if not INDICE.is_file():
        print(f"✗ index not found: {INDICE}", file=sys.stderr)
        print(
            "  A check that can't find the file to check is NOT green: it's blind.",
            file=sys.stderr,
        )
        return 1

    testo = INDICE.read_text(encoding="utf8")
    peso = len(testo.encode("utf8"))
    elenco = voci(testo)

    if len(elenco) < MIN_VOCI_ATTESE:
        print(
            f"✗ only {len(elenco)} entries read (expected ≥ {MIN_VOCI_ATTESE}): the index format"
            " has changed and this check is measuring nothing.",
            file=sys.stderr,
        )
        return 1

    lunghe = sorted(
        ((n, len(r), r) for n, r in elenco if len(r) > MAX_CARATTERI_VOCE),
        key=lambda x: -x[1],
    )

    print(
        f"MEMORY.md — {peso:,} bytes · {len(elenco)} entries · {len(lunghe)} over {MAX_CARATTERI_VOCE} characters"
    )

    if peso > TETTO_BYTE:
        print(
            f"\n✗ OVER THE CAP by {peso - TETTO_BYTE:,} bytes ({peso:,} > {TETTO_BYTE:,}).",
            file=sys.stderr,
        )
        print(
            "  Part of the index is NOT loaded: those entries don't exist for the session.",
            file=sys.stderr,
        )
        print("\n  The longest entries, a good place to start:", file=sys.stderr)
        for n, lung, riga in lunghe[:8]:
            print(f"    line {n:>3}  {lung:>4} chars  {riga[6:76]}…", file=sys.stderr)
        print(
            "\n  ⚠️ BEFORE shortening an entry: open the file it links and check that the fact you"
            "\n     are about to remove really exists. If it lives only in the index, MOVE it — don't cut it.",
            file=sys.stderr,
        )
        return 1

    if peso > PREAVVISO_BYTE:
        print(
            f"\n⚠️  {TETTO_BYTE - peso:,} bytes to the cap: better to compress now, not when it truncates."
        )
        for n, lung, riga in lunghe[:5]:
            print(f"    line {n:>3}  {lung:>4} chars  {riga[6:76]}…")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
