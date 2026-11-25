#!/usr/bin/env python3
""






































from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


NOSTRI = [
    "tools/knowledge_view.py",
    "tools/sbk_config.py",
    "tools/util/sb-identita.py",
    "tools/util/sb-identita-collaudo.py",
    "tools/util/sb-persone.py",
    "tools/util/sb-entita.py",
    "tools/util/sb-mononimi.py",
    "tools/util/sb-nomi-mancanti.py",
    "tools/util/sb-rinomina.py",
    "tools/util/sb-split-speaker.py",
    "tools/util/sb-sposta-aziende.py",
    "tools/util/sb-speaker.py",
    "tools/util/sb-speaker-tabella.py",
    "tools/util/sb-vocabolario.py",
    "tools/cross-source/xs-l2-knowledge-extract.py",
    "tools/cross-source/entity_dedup_index.py",
    "tools/cross-source/l4-06-partial-name-resolve.py",
    "tools/cross-source/xs-l4-reclassify-entities.py",
]


SEGNI_DI_VITA = (
    "glob",
    "read_text",
    "json.load",
    "json.loads",
    "open",
    "iterdir",
    "DATA_ROOT",
    "execute",
    "fetchall",
    "read_parquet",
    "environ",
)




MEMORIA = {"REGRESSIONI", "SEME", "_MAI_PERSONA", "MEMORIA", "NOSTRI", "SEGNI_DI_VITA"}





def _e_percorso(sorgente: str, nome: str) -> bool:
    return (
        "Path(" in sorgente
        or '/ "' in sorgente
        or nome.endswith(("_DIR", "_PATH", "_FILE", "ROOT"))
        or sorgente.strip().startswith(("DATA_ROOT", "REPO", "PROJECT", "KNOWLEDGE"))
    )





def _e_grammatica(nodo: ast.AST) -> bool:
    return (
        isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr == "compile"
    )





def _e_marcatore(nodo: ast.AST) -> bool:
    return isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)





def _chiama_funzione_viva(nodo: ast.AST, albero: ast.Module, corpo: str) -> bool:
    if not isinstance(nodo, ast.Call):
        return False
    nome = nodo.func.id if isinstance(nodo.func, ast.Name) else getattr(nodo.func, "attr", "")
    if not nome:
        return False
    for f in ast.walk(albero):
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef) and f.name == nome:
            seg = ast.get_source_segment(corpo, f) or ""


            if any(s in seg for s in SEGNI_DI_VITA) or any(v in seg for v in VIVE_ALTROVE):
                return True


    return nome in VIVE_ALTROVE




VIVE_ALTROVE = {"sigle_societarie", "chiave_organizzazione"}





def _e_collezione(nodo: ast.AST) -> bool:
    if isinstance(nodo, ast.Set | ast.List | ast.Tuple | ast.Dict):
        return True
    if isinstance(nodo, ast.Call):
        nome = getattr(nodo.func, "id", "") or getattr(nodo.func, "attr", "")
        if nome in {"frozenset", "set", "list", "tuple", "dict"} and nodo.args:
            return _e_collezione(nodo.args[0]) or isinstance(nodo.args[0], ast.Constant)
    return False




def _e_composizione(nodo: ast.AST) -> bool:
    elementi = getattr(nodo, "elts", None)
    return bool(elementi) and all(isinstance(e, ast.Name) for e in elementi)


def esamina(percorso: Path) -> list[dict]:
    ""
    try:
        albero = ast.parse(percorso.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):  # pragma: no cover
        return []
    testo = percorso.read_text(encoding="utf-8").splitlines()
    out = []
    for nodo in albero.body:
        if not isinstance(nodo, ast.Assign | ast.AnnAssign):
            continue
        bersagli = [nodo.target] if isinstance(nodo, ast.AnnAssign) else nodo.targets
        for b in bersagli:
            if not isinstance(b, ast.Name) or not b.id.lstrip("_").isupper():
                continue
            if nodo.value is None:
                continue
            sorgente = ast.get_source_segment("\n".join(testo), nodo.value) or ""
            vivo = any(s in sorgente for s in SEGNI_DI_VITA)



            corpo = "\n".join(testo)
            superata = False
            for f in ast.walk(albero):
                if isinstance(f, ast.FunctionDef):
                    seg = ast.get_source_segment(corpo, f) or ""
                    if b.id in seg and any(s in seg for s in SEGNI_DI_VITA):
                        superata = True
                        break
            vivo = vivo or _chiama_funzione_viva(nodo.value, albero, corpo)
            tipo = (
                "percorso"
                if _e_percorso(sorgente, b.id)
                else "memoria"
                if b.id in MEMORIA
                else "vivo"
                if vivo
                else "grammatica"
                if _e_grammatica(nodo.value)
                else "marcatore"
                if _e_marcatore(nodo.value)
                else "composizione"
                if _e_composizione(nodo.value)
                else "valore"
                if not _e_collezione(nodo.value)
                else "presidio"
                if superata
                else "soglia"
                if isinstance(nodo.value, ast.Constant)
                and isinstance(getattr(nodo.value, "value", None), int | float)
                else "ELENCO MORTO"
            )
            out.append(
                {
                    "nome": b.id,
                    "riga": nodo.lineno,
                    "tipo": tipo,
                    "valore": sorgente[:60].replace("\n", " "),
                }
            )
    return out




def _ordine(conta: collections.Counter) -> list[str]:
    peso = {"ELENCO MORTO": 0, "soglia": 1}
    return sorted(conta, key=lambda t: (peso.get(t, 2), -conta[t], t))


def main() -> int:
    ap = argparse.ArgumentParser(description="What will go stale, among what we wrote")
    ap.add_argument("--tipo", default="", help="ELENCO MORTO · soglia · presidio · vivo · memoria")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    conta: collections.Counter = collections.Counter()
    tutto = []
    for f in NOSTRI:
        p = REPO / f
        if not p.exists():
            continue
        for c in esamina(p):
            c["file"] = f
            tutto.append(c)
            conta[c["tipo"]] += 1

    print(f"\nconstants in the {len(NOSTRI)} files touched: {len(tutto)}\n")


    for t in _ordine(conta):
        print(f"   {t:14} {conta[t]:4}")

    print()
    for t in ("ELENCO MORTO", "soglia", "presidio", "vivo", "memoria", "percorso"):
        if a.tipo and t != a.tipo:
            continue
        righe = [c for c in tutto if c["tipo"] == t]
        if not righe:
            continue
        print(f"── {t}")
        for c in sorted(righe, key=lambda x: x["file"]):
            print(f"     {c['file'].split('/')[-1]:32} {c['nome']:26} r.{c['riga']}")
        print()

    print(
        "  An ELENCO MORTO is a piece of the world written into the code: the world changes, not the list."
    )
    print("  A soglia with no one to re-measure it decides on its own: cases tend to")
    print("  pile up exactly on the threshold value.")
    if a.json:
        Path(a.json).write_text(json.dumps(tutto, ensure_ascii=False, indent=1))
        print(f"\n  saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
