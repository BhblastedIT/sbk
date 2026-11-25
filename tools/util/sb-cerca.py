#!/usr/bin/env python3
"""Searches everything you said, wrote and received (mail, chats, transcripts, knowledge base), with secrets masked.

Usage:
    python tools/util/sb-cerca.py "your question" [--source S] [--after YYYY-MM-DD] [--person NAME] [--top N]
                                  [--no-synthesis]
    python tools/util/sb-cerca.py --prova       self-test of the masking

It runs tools/cross-source/xs-l3-search.py and masks passwords, tokens and API keys in every line it prints.
"""












from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

MOTORE = Path(__file__).resolve().parent.parent / "cross-source" / "xs-l3-search.py"
CREDENZIALI = Path(__file__).resolve().parent.parent / "security" / "credentials_loader.py"





_ETICHETTA = re.compile(
    r"(?i)\b(password|passwd|pwd|pass|passcode|passphrase|parola\s+d['’]?ordine|parola\s+chiave|pin|"
    r"secret|segreto|token|api[\s_-]?key|chiave(?:\s+api)?)(\s*[:=]\s*|\s+[eè]['’]?\s+|\s+is\s+)(\S+)"
)


def _formati_noti() -> tuple[re.Pattern[str], ...]:
    try:
        spec = importlib.util.spec_from_file_location("_credenziali", CREDENZIALI)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return tuple(p for _, p in mod._SECRET_PATTERNS)
    except Exception:

        return ()


_FORMATI = _formati_noti()


def oscura(testo: str) -> str:
    testo = _ETICHETTA.sub(lambda m: f"{m.group(1)}{m.group(2)}[OSCURATO]", testo)
    for pat in _FORMATI:
        testo = pat.sub("[OSCURATO]", testo)
    return testo


def _prova() -> int:
    casi = {
        "Username: mario  Password: Abc!12345": "Password: [OSCURATO]",
        "la password e' q9#Lm2": "",
        "pwd=xyz123 resto": "pwd=[OSCURATO]",
        "chiave api: sk-abcdefghijklmnopqrstuvwxyz": "[OSCURATO]",
        "Bearer abcdefghijklmnopqrstuvwxyz0123": "[OSCURATO]",
        "nessun segreto qui, solo una frase sul passaggio di consegne": None,
    }
    sbagli = 0
    for entrata, atteso in casi.items():
        uscita = oscura(entrata)
        if atteso is None:
            ok = uscita == entrata
        elif atteso == "":
            ok = "q9#Lm2" not in uscita
        else:
            ok = atteso in uscita
        print(("OK  " if ok else "NO  ") + uscita)
        sbagli += 0 if ok else 1
    print(f"prova: {len(casi) - sbagli} su {len(casi)}")
    return 1 if sbagli else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] == "--prova":
        return _prova()


    tradotti = {
        "--fonte": "--source",
        "--dal": "--after",
        "--persona": "--person",
        "--quanti": "--top",
        "--grezzo": "--no-synthesis",
    }
    argomenti = [tradotti.get(a, a) for a in sys.argv[1:]]

    cmd = [sys.executable, str(MOTORE), *argomenti]



    with open(os.devnull, "w") as nulla:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=nulla, text=True, bufsize=1)
        assert proc.stdout is not None
        for riga in proc.stdout:
            sys.stdout.write(oscura(riga))
            sys.stdout.flush()
        return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
