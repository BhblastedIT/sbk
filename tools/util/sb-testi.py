#!/usr/bin/env python3
""













from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


FORMULE = {
    r"\bnon solo\b.{0,60}\bma anche\b": "say the thing, without the double lever",
    r"\bin (sintesi|conclusione|definitiva|sostanza)\b": "cut it, the sentence stands on its own",
    r"\b(è|e'|risulta) (importante|fondamentale|cruciale|essenziale) (notare|sottolineare|ricordare)\b": "state the fact",
    r"\b(fondamentale|cruciale|imprescindibile)\b": "say why it matters, with a fact",
    r"\ba 360 gradi\b|\bsenza soluzione di continuit[aà]\b|\bin un'ottica di\b": "cliché",
    r"\b(potente|robust[oa]|innovativ[oa]|all'avanguardia|rivoluzionari[oa]|semplice ed efficace)\b": "empty adjective: put the number or cut it",
    r"\b(sfrutta(re)?|sblocca(re)?|eleva(re)?|potenzia(re)?) (il|la|le|i|tutto il) (potenziale|potere|valore)\b": "brochure phrase",
    r"\b(tuffiamoci|scopriamo insieme|ecco (come|cosa|perch[eé])|vediamo insieme)\b": "generated-article opening",
    r"\b(in questo (contesto|scenario|panorama)|nel panorama (attuale|odierno))\b": "filler",
    r"\b(un vero e proprio|a tutti gli effetti|di fatto|sostanzialmente|essenzialmente)\b": "filler",
    r"\b(garantisce|assicura|offre) (un'esperienza|una gestione|una soluzione)\b": "say what it does",
    r"\bspero (che )?(questo|ti) (aiuti|sia utile)\b|\bfammi sapere se\b": "assistant closing",
    r"\b(ottim[oa] domanda|certamente|assolutamente s[iì])\b": "assistant opening",
}

GENERICI = r"\b(cose|roba|elementi|contenuti|varie|altro|gestione|generale|informazioni|dati|oggetti|risorse)\b"

CHIAVE_NOME = re.compile(r"^(titolo|nome|voce|gruppo_|sezione|etichetta|pulsante)")
INTERNI = {
    r"\b[A-Z]{1,6}-\d{1,3}[a-z]?\b": "internal code",
    r"\b[\w-]+\.(py|json|md|swift|sh|parquet)\b": "file name",
    r"(?<!\w)--[a-z][\w-]+": "command-line option",
    r"\b[a-z]+_[a-z_]+\b": "field or function name",
}
ORA = re.compile(r"\b\d{1,2}:\d{2}\b")

# Opinionated style checks, off by default. A user can enable the ones from
# their own style profile; shipping them on would impose one author's rules.
# Known keys: "em_dash", "colon", "non_ma", "internal_codes".
STILE_OPZIONALE: frozenset[str] = frozenset()


def controlla(testo: str, chiave: str = "") -> list[str]:
    ""
    out = []
    pulito = re.sub(r"\{[a-z_]+\}", "", testo)
    if "em_dash" in STILE_OPZIONALE and ("—" in pulito or "–" in pulito):
        out.append("em dash")
    if "colon" in STILE_OPZIONALE and ":" in ORA.sub("", pulito):
        out.append("colon")
    if "non_ma" in STILE_OPZIONALE and len(re.findall(r"\bnon\b[^.;!?]{1,60}[,;]\s*ma\b", pulito, re.I)) > 1:
        out.append("«not X, but Y» more than once")
    for modello, rimedio in FORMULE.items():
        m = re.search(modello, pulito, re.I)
        if m:
            out.append(f"«{m.group(0)}» · {rimedio}")
    if "internal_codes" in STILE_OPZIONALE:
        for modello, cosa in INTERNI.items():
            m = re.search(modello, pulito)
            if m:
                out.append(f"«{m.group(0)}» · {cosa} in plain sight")
    corto = len(pulito.split()) <= 4
    if (CHIAVE_NOME.match(chiave) or (not chiave and corto)) and corto:
        m = re.search(GENERICI, pulito, re.I)
        if m:
            out.append(
                f"generic name «{m.group(0)}» · prefer the term the user uses"
            )
    if re.search(r"(?:^|[.!?]\s)(Inoltre|Infine|Pertanto|Dunque|Tuttavia),", pulito):
        out.append("essay connective at the start of the sentence")
    return out


def _da_modulo(spec: str) -> dict[str, str]:
    ""
    percorso, _, nome = spec.partition(":")
    albero = ast.parse(Path(percorso).read_text(encoding="utf-8"))
    for nodo in ast.walk(albero):
        bersagli = []
        if isinstance(nodo, ast.Assign):
            bersagli = nodo.targets
        elif isinstance(nodo, ast.AnnAssign):
            bersagli = [nodo.target]
        if any(isinstance(b, ast.Name) and b.id == nome for b in bersagli) and isinstance(
            nodo.value, ast.Dict
        ):
            out = {}
            for k, v in zip(nodo.value.keys, nodo.value.values):  # noqa: B905 gira anche col python3 di sistema
                try:
                    out[str(ast.literal_eval(k))] = str(ast.literal_eval(v))
                except (ValueError, TypeError):
                    continue
            return out
    raise SystemExit(f"in {percorso} I can't find a dictionary {nome}")


def main(argv: list[str]) -> int:
    solo_nomi = "--nomi" in argv
    argv = [a for a in argv if a != "--nomi"]
    pezzi: list[tuple[str, str, str]] = []
    if "--modulo" in argv:
        spec = argv[argv.index("--modulo") + 1]
        pezzi += [
            (spec, k, v) for k, v in _da_modulo(spec).items() if not k.startswith("commento_")
        ]
    else:
        for nome in argv or ["-"]:
            grezzo = (
                sys.stdin.read()
                if nome == "-"
                else Path(nome).read_text(encoding="utf-8", errors="replace")
            )
            grezzo = re.sub(r"<(script|style)\b.*?</\1>", " ", grezzo, flags=re.S | re.I)
            grezzo = re.sub(r"<[^>]+>", " ", grezzo)
            for i, riga in enumerate(grezzo.splitlines(), 1):
                if riga.strip() and not riga.lstrip().startswith(("```", "|--", "    ")):
                    pezzi.append((nome, f"line {i}", riga.strip()))
    trovati = 0
    for dove, chiave, testo in pezzi:
        rilievi = controlla(testo, "" if chiave.startswith("line ") else chiave)
        if solo_nomi:
            rilievi = [r for r in rilievi if r.startswith("generic name")]
        for r in rilievi:
            trovati += 1
            print(f"{dove} · {chiave} · {r}\n    {testo[:110]}")
    print(
        f"\n{trovati} findings across {len(pezzi)} pieces" if trovati else f"clean ({len(pezzi)} pieces)"
    )
    return 1 if trovati else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
