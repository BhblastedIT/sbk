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


def norm(s: object) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def _moduli():
    def carica(nome, path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(nome, Path(__file__).resolve().parent / path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[nome] = mod
        spec.loader.exec_module(mod)
        return mod

    return carica("sb_persone", "sb-persone.py"), carica("sb_identita", "sb-identita.py")


def contesto(eid: str, nome: str, fatti: list[dict], indice: dict) -> dict:
    ""
    nn = norm(nome)
    accanto: collections.Counter = collections.Counter()
    temi: collections.Counter = collections.Counter()
    canali: collections.Counter = collections.Counter()
    date = []

    for f in fatti:
        canali[(f.get("source") or {}).get("source_type")] += 1
        d = str(f.get("valid_from") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            date.append(d)
        a = str(f.get("attribute") or "")
        if a:
            temi[a.split(".")[0]] += 1

        v = str(f.get("value") or "")
        for parola in re.findall(r"\b([A-ZÀ-Ü][a-zà-ÿ]{2,15})\b", v[:200]):
            p = norm(parola)
            if p and p != nn and p in indice:
                accanto[parola] += 1

    return {
        "con_chi": [n for n, _ in accanto.most_common(6)],
        "temi": [t for t, _ in temi.most_common(4)],
        "canali": dict(canali.most_common(4)),
        "dal": min(date) if date else None,
        "al": max(date) if date else None,
    }


def esamina(quanti: int = 40) -> list[dict]:
    classificatore, identita = _moduli()

    indice = set()
    per_nome: dict[str, list[str]] = collections.defaultdict(list)
    mono: list[tuple] = []
    for f in PERSON.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = (d.get("canonical_name") or "").strip()
        if not n:
            continue
        nn = norm(n)
        v = classificatore.classifica(f.stem, n, d.get("facts") or [])
        if v.categoria in ("PERSONA", "NOME-SPORCO"):
            if len(nn.split()) >= 2:
                indice.add(nn.split()[0])
                per_nome[nn.split()[0]].append(n)
            elif nn and "@" not in n:
                mono.append((len(d.get("facts") or []), n, f.stem, d.get("facts") or []))
    mono.sort(reverse=True)

    out = []
    for nf, nome, eid, fatti in mono[:quanti]:
        cand, _ = identita.indaga(nome, 8)
        propri = [c for c in cand if norm(c.nome) != norm(nome)]
        provati = [c for c in propri if c.verdetto == "PROVATO"]
        ctx = contesto(eid, nome, fatti, indice)

        if len(provati) == 1:
            classe = "RISOLVIBILE"
        elif propri and len(per_nome.get(norm(nome), [])) <= 3 and ctx["con_chi"]:
            classe = "DA CHIEDERE"
        else:
            classe = "DA LASCIARE"
        out.append(
            {
                "nome": nome,
                "eid": eid,
                "fatti": nf,
                "classe": classe,
                "omonimi_nello_store": len(per_nome.get(norm(nome), [])),
                "candidati": [
                    {"nome": c.nome, "verdetto": c.verdetto, "prove": [p.tipo for p in c.prove]}
                    for c in propri[:3]
                ],
                **ctx,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="The context of mononyms, and how to handle them")
    ap.add_argument("--quanti", type=int, default=40)
    ap.add_argument("--classe", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    righe = esamina(a.quanti)
    c = collections.Counter(r["classe"] for r in righe)
    print(f"\nmononyms examined: {len(righe)}  ({sum(r['fatti'] for r in righe)} facts)\n")
    for k in ("RISOLVIBILE", "DA CHIEDERE", "DA LASCIARE"):
        if c[k]:
            f = sum(r["fatti"] for r in righe if r["classe"] == k)
            print(f"   {k:14} {c[k]:4}  ({f} facts)")

    print()
    for r in righe:
        if a.classe and r["classe"] != a.classe:
            continue
        print(
            f"── «{r['nome']}»  {r['fatti']} facts  ·  {r['classe']}"
            f"  ·  {r['omonimi_nello_store']} people with this name"
        )
        if r["con_chi"]:
            print(f"     with whom : {', '.join(r['con_chi'][:5])}")
        print(
            f"     about     : {', '.join(r['temi'])}   ·   from {r['dal'] or '?'} to {r['al'] or '?'}"
        )
        for k in r["candidati"][:2]:
            print(f"     candidate : {k['nome'][:32]:32} {k['verdetto']:14} {k['prove']}")
        print()

    print("  ⚠️  No merge is done. «DA LASCIARE» is not a failure: it is the right answer")
    print("      when the name leads to no one, and it should be written instead of forced.")
    if a.json:
        Path(a.json).write_text(json.dumps(righe, ensure_ascii=False, indent=1))
        print(f"\n  saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
