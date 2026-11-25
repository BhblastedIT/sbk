#!/usr/bin/env python3
""






































from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
PLAUD = cfg.DATA_ROOT / "plaud" / "raw"

_NOME = re.compile(r"\b([A-ZÀ-Ü][a-zà-ÿ']{2,14})\s+([A-ZÀ-Ü][a-zà-ÿ']{2,16})\b")


_MAI_PERSONA = re.compile(
    r"^(new|san|hong|las|los|buenos|estados|real|google|tik|cloud|wear|beauty|mar|media|"
    r"private|project|creative|account|black|print|sud|nord|est|ovest|via|piazza|corso|"
    r"studio|gruppo|team|holding|group|capital|partner|agency|lab|hub)$",
    re.I,
)


def norm(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def _vocabolario() -> tuple[set[str], set[str], set[str]]:
    ""
    primi: collections.Counter = collections.Counter()
    ultimi: set[str] = set()
    kb: set[str] = set()
    for f in PERSON.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = (d.get("canonical_name") or "").strip()
        if not n:
            continue
        kb.add(norm(n))
        t = norm(re.sub(r"\(.*?\)", " ", n)).split()
        if len(t) >= 2:
            primi[t[0]] += 1
            ultimi.add(t[-1])

    return {k for k, v in primi.items() if v >= 3}, ultimi, kb


def cerca(minimo: int = 3) -> list[dict]:
    battesimo, cognomi, kb = _vocabolario()
    conta: collections.Counter = collections.Counter()
    dove: dict[str, set[str]] = collections.defaultdict(set)
    for f in PLAUD.glob("*.txt"):
        try:
            testo = f.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover
            continue
        for a, b in _NOME.findall(testo):
            na, nb = norm(a), norm(b)
            if na not in battesimo or nb not in cognomi:
                continue
            if _MAI_PERSONA.match(na) or _MAI_PERSONA.match(nb):
                continue
            chiave = f"{a} {b}"
            conta[chiave] += 1
            dove[chiave].add(f.stem[:44])
    out = []
    for nome, n in conta.most_common():
        if n < minimo or norm(nome) in kb:
            continue
        out.append(
            {
                "nome": nome,
                "menzioni": n,
                "verbali": sorted(dove[nome])[:3],
                "n_verbali": len(dove[nome]),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="People named in the transcripts and absent from the KB")
    ap.add_argument("--minimo", type=int, default=3, help="minimum mentions")
    ap.add_argument("--quanti", type=int, default=25)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    righe = cerca(a.minimo)
    print(f"\npeople named in the transcripts and ABSENT from the KB: {len(righe)}")
    print(f"total mentions: {sum(r['menzioni'] for r in righe)}\n")
    for r in righe[: a.quanti]:
        print(f"   {r['nome'][:30]:30} {r['menzioni']:4} times in {r['n_verbali']} transcripts")
        print(f"        e.g.: {r['verbali'][0][:60]}")

    print("\n  ⚠️  No entity is created. Some noise remains («Media Buying»): this is a")
    print("      list to read, and creating an entity is a decision.")
    if a.json:
        Path(a.json).write_text(json.dumps(righe, ensure_ascii=False, indent=1))
        print(f"\n  saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
