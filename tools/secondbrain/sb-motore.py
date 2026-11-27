#!/usr/bin/env python3
"""Entry point of the SecondBrain app's back end: the app runs it with a section and arguments (cose, pagine,
inspiration, plaud, agente) and gets JSON back; any other command goes to sb-app.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unicodedata
from pathlib import Path

QUI = Path(__file__).resolve().parent


def _veloce(argv: list[str]) -> int | None:
    ""
    if argv[1:2] == ["agente"]:


        sys.path.insert(0, str(QUI))
        import sb_agente

        testo = unicodedata.normalize("NFC", argv[2]) if len(argv) > 2 else ""
        print(json.dumps(sb_agente.apri(testo), ensure_ascii=False))
        return 0
    if argv[1:2] == ["pagine"]:
        sys.path.insert(0, str(QUI))
        import sb_pagine

        print(
            json.dumps(sb_pagine.per_app("--rileggi" in argv[2:]), ensure_ascii=False, default=str)
        )
        return 0
    if argv[1:2] == ["inspiration"]:
        sys.path.insert(0, str(QUI))
        if argv[2:]:

            import sb_inspiration_azioni




            argv = [unicodedata.normalize("NFC", a) for a in argv]

            print(
                json.dumps(sb_inspiration_azioni.esegui(argv[2:]), ensure_ascii=False, default=str)
            )
            return 0
        import sb_inspiration

        print(json.dumps(sb_inspiration.per_app(), ensure_ascii=False, default=str))
        return 0
    if argv[1:2] == ["plaud"]:

        sys.path.insert(0, str(QUI))
        import sb_plaud

        print(json.dumps(sb_plaud.per_app(), ensure_ascii=False, default=str))
        return 0
    if argv[1:2] == ["cose"]:



        argv = [unicodedata.normalize("NFC", a) for a in argv]

        sys.path.insert(0, str(QUI))



        import sb_attivita

        if argv[2:3] and argv[2].startswith("voce"):

            import sb_attivita_voce

            risposta = sb_attivita_voce.esegui(argv[2:])
        else:
            risposta = sb_attivita.esegui(argv[2:])
        sys.stdout.buffer.write(sb_attivita.json_per_app(risposta) + b"\n")
        sys.stdout.buffer.flush()
        return 0
    return None


def main() -> int:
    esito = _veloce(sys.argv)
    if esito is not None:
        return esito
    spec = importlib.util.spec_from_file_location("sb_app", QUI / "sb-app.py")
    mod = importlib.util.module_from_spec(spec)

    sys.modules["sb_app"] = mod
    spec.loader.exec_module(mod)
    return mod.main()


if __name__ == "__main__":
    sys.exit(main())
