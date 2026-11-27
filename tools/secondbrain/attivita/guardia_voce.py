#!/usr/bin/env python3
"""Guard of the voice-task session: a Claude Code PreToolUse hook that decides whether a tool call may run.

It reads the tool call from stdin and lets through only the task engine command
(.venv/bin/python tools/secondbrain/sb-motore.py cose <verb> ...) on the tasks of the current request, within
limits on how many tasks it touches, deletes and how many views it creates or changes (SB_VOCE_* variables),
plus writing ESITO.json in the request folder. Anything else is blocked (exit 2), and every decision is logged
in guardia.log in that folder. sb_attivita_voce.py installs it; it is not meant to be run by hand.

Usage: guardia_voce.py --cartella <request folder> --richiesta <id> --attivita <tasks folder> < event.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PYTHON = {".venv/bin/python", str(ROOT / ".venv" / "bin" / "python")}
MOTORE = {"tools/secondbrain/sb-motore.py", str(ROOT / "tools" / "secondbrain" / "sb-motore.py")}


ARGOMENTI = {
    "fatta": 1,
    "riapri": 1,
    "elimina": 1,
    "ripristina": 1,
    "stato": 2,
    "priorita": 2,
    "data": 2,
    "scadenza": 2,
    "stima": 2,
    "titolo": 2,
    "descrizione": 2,
    "descrizione-aggiungi": 2,
    "area": 2,

    "pianifica": 2,
    "commenta": 2,
}
SU_TASK = set(ARGOMENTI)

LETTURE = {
    "commenti": (1, 1),
    "storia": (1, 1),

    "descrizione-leggi": (1, 1),
    "settimana": (0, 1),
    "buchi": (1, 1),
    "durata": (1, 1),
}

VISTE = {"vista-nuova": (1, 2), "vista-imposta": (3, 3)}

CAMPI_VISTA = (
    "filtro",
    "gruppo",
    "gruppi_chiusi",
    "ordine",
    "fatte",
    "modo",
    "scala",
    "calendari_nascosti",
    "rifiutati",
)

MODI = ("tabella", "foglio", "bacheca", "calendario")


IN_FONDO = {
    "pianifica": {"--durata": True},
    "buchi": {"--durata": True, "--da": True},
    "settimana": {"--giorno": False},
}

IMPOSTAZIONI = ("stato-", "stati-", "area-", "aree-", "imposta", "impostazioni")


CAMPO = {
    "fatta": "stato",
    "riapri": "stato",
    "stato": "stato",
    "data": "scadenza",
    "scadenza": "scadenza",
    "priorita": "priorita",
    "stima": "stima",
    "titolo": "titolo",
    "area": "area",
    "descrizione": "descrizione",
    "descrizione-aggiungi": "descrizione",
    "elimina": "elimina",
    "ripristina": "ripristina",
    "nuova": "nuova",
    "pianifica": "pianificata",
    "commenta": "commenti",
}

ID = re.compile(r"[0-9a-f]{1,32}(?:,[0-9a-f]{1,32})*")

ID_VISTA = re.compile(r"[a-z][a-z0-9-]{0,39}")

CHIAVE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


CHIAVI_NUOVA = ("stato", "area", "priorita", "scadenza", "stima", "pianificata")

OPZIONI = re.compile(r"--[A-Za-z]")


SPECIALI = set("#$`;&|<>(){}*?[]~!\\^")

SPECIALI_DOPPIE = set("$`\\!")


class Fermo(Exception):
    ""


def _soglia() -> int:
    ""
    return int(os.environ.get("SB_VOCE_SOGLIA") or 5)


def _elimina_max() -> int:
    ""
    return int(os.environ.get("SB_VOCE_ELIMINA_MAX") or 10)


def _viste_nuove_max() -> int:
    ""
    return int(os.environ.get("SB_VOCE_VISTE_NUOVE_MAX") or 1)


def _viste_cambi_max() -> int:
    ""

    return int(os.environ.get("SB_VOCE_VISTE_CAMBI_MAX") or 4)


def _no(perche: str) -> int:
    print(perche, file=sys.stderr)
    return 2





def _vietato_ovunque(c: str) -> bool:
    ""
    return unicodedata.category(c) in ("Cc", "Cs")


def _vietato_fuori(c: str) -> bool:
    ""

    if c in SPECIALI or c in "\"'":
        return True
    if c != " " and (
        c.isspace() or unicodedata.category(c) in ("Cf", "Zs", "Zl", "Zp", "Co", "Cn")
    ):
        return True
    return False


def _leggi(comando: str) -> list[str]:
    ""



    if not isinstance(comando, str):
        raise Fermo("The command cannot be read.")
    for c in comando:
        if _vietato_ovunque(c):
            raise Fermo(
                "One command at a time, on a single line, with no line breaks, tabs or control characters."
            )
    parole: list[str] = []
    i, n = 0, len(comando)
    while i < n:
        while i < n and comando[i] == " ":
            i += 1
        if i >= n:
            break
        parola, uguali, dentro_parola = [], 0, []
        while i < n and comando[i] != " ":
            c = comando[i]
            if c == '"':
                fine = comando.find('"', i + 1)
                if fine < 0:
                    raise Fermo("The command cannot be read, check the double quotes.")
                pezzo = comando[i + 1 : fine]
                if any(x in SPECIALI_DOPPIE for x in pezzo):
                    raise Fermo(
                        "Inside double quotes do not put $, backticks, backslashes or exclamation marks. "
                        "Write them out in words, or put that piece inside single quotes."
                    )
                parola.append(pezzo)
                i = fine + 1
                continue
            if c == "'":
                fine = comando.find("'", i + 1)
                if fine < 0:
                    raise Fermo("The command cannot be read, check the single quotes.")
                pezzo = comando[i + 1 : fine]
                if not pezzo or (fine + 1 < n and comando[fine + 1] == "'"):

                    raise Fermo(
                        "Two single quotes in a row are not read the same everywhere. Rewrite it."
                    )
                parola.append(pezzo)
                i = fine + 1
                continue
            if _vietato_fuori(c):
                raise Fermo(
                    "One command at a time, without ; & | redirect, $, backticks, # or other shell characters "
                    "outside the quotes. Texts go inside quotes."
                )
            if c == "=":

                prima = "".join(dentro_parola)
                if uguali or len(parola) != len(dentro_parola) or not CHIAVE.fullmatch(prima):
                    raise Fermo(
                        "An equals sign outside quotes is used only as key=value. Rewrite it."
                    )
                uguali += 1
            parola.append(c)
            dentro_parola.append(c)
            i += 1
        parole.append("".join(parola))
    return parole





def _eventi(attivita: Path) -> list[dict]:
    ""

    try:
        righe = (
            (attivita / "eventi.jsonl").read_text(encoding="utf-8", errors="replace").split("\n")
        )
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            e = json.loads(r)
        except (ValueError, RecursionError):
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _applica(task: dict, e: dict) -> None:
    ""
    tid, tipo = e.get("id"), e.get("tipo")
    if tipo == "crea":
        task[tid] = {"id": tid, "eliminata": False, **e["campi"]}
    elif tid in task and tipo == "cambia":
        task[tid].update(e["campi"])
    elif tid in task and tipo in ("elimina", "ripristina"):
        task[tid]["eliminata"] = tipo == "elimina"


def _task(eventi: list[dict]) -> dict:
    task: dict = {}
    for e in eventi:
        try:
            _applica(task, e)
        except Exception:  # noqa: BLE001 like the engine, a bad row is skipped
            continue
    return task


def _chiave(x) -> str:
    ""
    return x if isinstance(x, str) else "\x00" + json.dumps(x, sort_keys=True, default=str)


def _della_richiesta(eventi: list[dict], richiesta: str) -> tuple[set, int, int]:
    ""
    toccate, eliminate, create = set(), 0, 0
    for e in eventi:
        if e.get("da") != richiesta:
            continue
        toccate.add(_chiave(e.get("id")))
        eliminate += e.get("tipo") == "elimina"
        create += e.get("tipo") == "crea"
    return toccate, eliminate, create


def _piena(task: dict, tid: str) -> bool:
    d = (task.get(tid) or {}).get("descrizione")
    if d is None:
        return False
    return bool(d.strip()) if isinstance(d, str) else bool(d)


def _confermate(cartella: Path) -> dict | None:
    try:
        d = json.loads((cartella / "CONFERMATE.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return None
    return d if isinstance(d, dict) else None


def _permessi(si: dict) -> tuple[dict[str, set], dict[str, set]]:
    ""
    campi: dict[str, set] = {}
    verbi: dict[str, set] = {}
    righe = si.get("proposta")
    for r in righe if isinstance(righe, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"]:
            continue
        verbo = r.get("verbo")
        if not isinstance(verbo, str) and r.get("campo") == "descrizione":
            verbo = "descrizione"
        if verbo not in SU_TASK:
            continue
        campi.setdefault(r["id"], set()).add(CAMPO[verbo])
        verbi.setdefault(r["id"], set()).add(verbo)
    return campi, verbi


def _da_proporre(n: int) -> str:
    return (
        f"This request would touch {n} tasks, more than {_soglia()}. Do not act. Write ESITO.json with status "
        "«da_confermare», in «proposta» one row per task with what you would change and the verb you will use, and in «risposta» "
        "the question for the user. It restarts on its own after their yes."
    )


def _giudica_esito(dentro: dict) -> int | None:
    ""
    try:
        esito = json.loads(dentro.get("content") or "")
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(esito, dict) or esito.get("stato") != "da_confermare":
        return None
    righe = esito.get("proposta")
    for r in righe if isinstance(righe, list) else []:
        if not isinstance(r, dict):
            continue
        verbo, tid = r.get("verbo"), r.get("id") or ""
        giusta = (
            (verbo == "nuova" and not tid)
            or (verbo in SU_TASK and isinstance(tid, str) and ID.fullmatch(tid) and "," not in tid)

            or (verbo == "vista-imposta" and isinstance(tid, str) and ID_VISTA.fullmatch(tid))
        )
        if not giusta:
            return _no(
                "Each proposal row states «verbo», the engine verb you will use on that task (for example "
                "«data», «fatta», «elimina», «descrizione-aggiungi», or «nuova» with an empty id), and «id», the id of a "
                "single task. After the user's yes only that verb goes through. Rewrite ESITO.json."
            )
    return None


def _giudica_write(dentro: dict, cartella: Path) -> int:
    fp = dentro.get("file_path")
    giusto = cartella / "ESITO.json"
    if isinstance(fp, str) and fp and "\x00" not in fp and os.path.isabs(fp):
        uguale = os.path.normpath(fp) == os.path.normpath(str(giusto))
        risolto = os.path.realpath(fp) == os.path.realpath(str(giusto))
        if uguale and risolto and not os.path.islink(giusto):
            esito = _giudica_esito(dentro)
            return 0 if esito is None else esito
    return _no(f"You can only write {giusto}.")


def giudica(evento: dict, cartella: Path, richiesta: str, attivita: Path) -> int:
    if not isinstance(evento, dict):
        return _no("The guard did not understand the gesture.")
    attrezzo = evento.get("tool_name") or ""
    dentro = evento.get("tool_input")
    if not isinstance(dentro, dict):
        return _no("The guard did not understand the gesture.")
    if attrezzo == "Write":
        return _giudica_write(dentro, cartella)
    if attrezzo != "Bash":
        return _no(
            f"Here {attrezzo} is not used. You only have the task engine command and ESITO.json."
        )
    comando = dentro.get("command")
    if not isinstance(comando, str):
        return _no("The command cannot be read.")
    try:
        pezzi = _leggi(comando)
    except Fermo as e:
        return _no(str(e))
    soglia, elimina_max = (
        _soglia(),
        _elimina_max(),
    )
    if len(pezzi) < 3 or pezzi[0] not in PYTHON or pezzi[1] not in MOTORE or pezzi[2] != "cose":
        return _no(
            "You can only use .venv/bin/python tools/secondbrain/sb-motore.py cose <verb> from the repo folder."
        )
    resto = pezzi[3:]
    if not resto or resto == ["--rileggi"]:
        return 0
    verbo, argomenti = resto[0], resto[1:]
    if isinstance(verbo, str) and verbo.startswith(IMPOSTAZIONI):
        return _no(
            "Statuses, areas and settings are not changed by voice; the user changes them from the settings sheet. Say so in the "
            "reply."
        )
    if verbo not in SU_TASK and verbo != "nuova" and verbo not in LETTURE and verbo not in VISTE:
        return _no(f"The verb «{verbo}» is not used here.")
    if "--testo-file" in argomenti or "--era-file" in argomenti:

        return _no("Texts are written in the command, not from a file.")
    argomenti = _togli_in_fondo(verbo, argomenti)
    if argomenti is None:
        return _no("An option at the end of the command is written only once, with its value.")
    if any(OPZIONI.match(a) for a in argomenti):
        return _no(
            "The engine options are not used here. Write only the verb, the ids and the value. Rewrite a text that "
            "starts with two dashes."
        )
    if verbo in LETTURE or verbo in VISTE:
        esito = _giudica_altro(verbo, argomenti)
        if esito or verbo in LETTURE:
            return esito
        return _giudica_vista(verbo, argomenti, cartella)
    ids: set[str] = set()
    if verbo == "nuova":
        if not argomenti:
            return _no("A new task needs the title in quotes.")
        if any(a.partition("=")[0] not in CHIAVI_NUOVA or "=" not in a for a in argomenti[1:]):
            return _no(
                "A new task is written with the title in quotes and then only key=value, with the keys stato, "
                "area, priorita, scadenza, stima, pianificata. A title with spaces all in quotes."
            )
    else:
        if len(argomenti) != ARGOMENTI[verbo]:
            quanti = "the id" if ARGOMENTI[verbo] == 1 else "the id and a value"
            return _no(
                f"With «{verbo}» you write {quanti}, nothing else. A text with spaces goes in quotes."
            )
        if not ID.fullmatch(argomenti[0]):
            return _no(
                "In place of the id go only task ids, separated by commas, with no spaces or other characters."
            )
        ids = set(argomenti[0].split(","))
    eventi = _eventi(attivita)
    toccate, eliminate, create = _della_richiesta(eventi, richiesta)
    task = _task(eventi)
    si = _confermate(cartella)
    if si is not None:
        return _col_si(si, verbo, ids, create, task)
    nuove = 1 if verbo == "nuova" else 0
    dopo = len(toccate | ids) + nuove
    if dopo > soglia:
        return _no(_da_proporre(dopo))
    if verbo == "elimina" and eliminate + len(ids) > elimina_max:
        return _no(
            f"In a single request you cannot delete more than {elimina_max} tasks without the user's yes."
        )
    if verbo == "descrizione" and any(_piena(task, tid) for tid in ids):
        return _no(
            "This description already exists and you would replace it. To add, use descrizione-aggiungi, which "
            "appends. To really replace it, propose it in ESITO.json with status «da_confermare» and verb «descrizione», "
            "so the user sees what is lost and decides."
        )
    return 0


def _togli_in_fondo(verbo: str, argomenti: list[str]) -> list[str] | None:
    ""

    ammesse = IN_FONDO.get(verbo) or {}
    viste: set[str] = set()
    while argomenti:
        if len(argomenti) >= 1 and argomenti[-1] in ammesse and not ammesse[argomenti[-1]]:
            chiave, argomenti = argomenti[-1], argomenti[:-1]
        elif len(argomenti) >= 2 and argomenti[-2] in ammesse and ammesse[argomenti[-2]]:
            if OPZIONI.match(argomenti[-1]):
                return None
            chiave, argomenti = argomenti[-2], argomenti[:-2]
        else:
            break
        if chiave in viste:
            return None
        viste.add(chiave)
    return argomenti


def _giudica_altro(verbo: str, argomenti: list[str]) -> int:
    ""
    poco, tanto = LETTURE.get(verbo) or VISTE[verbo]
    if not poco <= len(argomenti) <= tanto:
        return _no(
            f"With «{verbo}» the arguments are not right. A text with spaces goes in quotes."
        )
    if verbo in ("commenti", "storia", "buchi", "descrizione-leggi") and not (
        ID.fullmatch(argomenti[0]) and "," not in argomenti[0]
    ):
        return _no("In place of the id goes the id of a single task, with no spaces or other characters.")
    if verbo == "vista-nuova" and argomenti[0] not in MODI:
        return _no("A new view is a tabella, foglio, bacheca or calendario.")
    if verbo == "vista-imposta":
        if argomenti[1] not in CAMPI_VISTA:
            return _no(
                "By voice, only filters, groups, order, done and display of a view can be changed."
            )
        try:

            json.loads(argomenti[2])
        except (ValueError, RecursionError):
            return _no(
                "A view's value is JSON, all in single quotes. For example '[\"scadenza\"]'."
            )
    return 0


def _righe_viste(cartella: Path) -> list[dict]:
    ""

    try:
        righe = (cartella / "VISTE.jsonl").read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            d = json.loads(r)
        except (ValueError, RecursionError):
            continue
        if isinstance(d, dict) and isinstance(d.get("gesto"), list) and d["gesto"]:
            out.append(d)
    return out


def _vista_aperta(cartella: Path) -> str:
    ""
    try:
        r = json.loads((cartella / "RICHIESTA.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return ""
    v = r.get("vista") if isinstance(r, dict) else None
    return v if isinstance(v, str) else ""


def _giudica_vista(verbo: str, argomenti: list[str], cartella: Path) -> int:
    ""


    righe = _righe_viste(cartella)
    if verbo == "vista-nuova":
        nuove = sum(r["gesto"][0] == "vista-nuova" for r in righe)
        if nuove >= _viste_nuove_max():
            return _no(
                "In one request you make at most one new view. If the user needs more, tell them in the reply."
            )
        return 0
    vid = argomenti[0]
    si = _confermate(cartella)
    confermate = set()
    for r in (si.get("proposta") if si else None) or []:
        if (
            isinstance(r, dict)
            and r.get("verbo") == "vista-imposta"
            and isinstance(r.get("id"), str)
        ):
            confermate.add(r["id"])
    if vid in confermate:
        return 0
    sue = {r.get("id") for r in righe if r["gesto"][0] == "vista-nuova"} | {_vista_aperta(cartella)}
    sue.discard("")
    if vid not in sue:
        return _no(
            "This view is not the one the user has open nor one you made in this request. To change it, "
            "propose it in ESITO.json with status «da_confermare» and a row with verb «vista-imposta» and the view id, "
            "so the user decides."
        )
    cambi = sum(r["gesto"][0] == "vista-imposta" and r.get("id") not in confermate for r in righe)
    if cambi >= _viste_cambi_max():
        return _no(
            f"In one request you make at most {_viste_cambi_max()} changes to views without the user's yes. Propose the rest "
            "in ESITO.json with status «da_confermare»."
        )
    return 0


def _col_si(si: dict, verbo: str, ids: set, create: int, task: dict) -> int:
    ""
    nuove = si.get("nuove")
    if verbo == "nuova":
        if not isinstance(nuove, int) or create >= nuove:
            return _no("The user confirmed a specific proposal and this new task was not in it.")
        return 0
    campi, verbi = _permessi(si)
    fuori = [tid for tid in ids if CAMPO[verbo] not in campi.get(tid, set())]
    if fuori:
        return _no(
            "The user confirmed a specific proposal and for these tasks it did not say this gesture. Do only what "
            "it said, write the rest in ESITO.json as a question."
        )
    if verbo == "descrizione" and any(
        _piena(task, tid) and "descrizione" not in verbi.get(tid, set()) for tid in ids
    ):
        return _no(
            "The user confirmed adding, not replacing. Use descrizione-aggiungi, which removes nothing."
        )
    return 0


def _registra(cartella: Path, evento, esito: int, perche: str) -> None:
    ""
    try:
        dentro = evento.get("tool_input") if isinstance(evento, dict) else None
        dentro = dentro if isinstance(dentro, dict) else {}
        cosa = dentro.get("command") or dentro.get("file_path") or ""
        riga = {
            "t": datetime.now().isoformat(timespec="seconds"),
            "attrezzo": evento.get("tool_name") if isinstance(evento, dict) else None,
            "cosa": str(cosa)[:300],
            "passa": esito == 0,
            "perche": perche.strip(),
        }
        with open(cartella / "guardia.log", "a", encoding="utf-8", errors="replace") as fh:
            fh.write(json.dumps(riga, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 the log decides nothing
        pass


def _argomenti(argv: list[str]) -> dict:
    ""
    out = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i] in ("--cartella", "--richiesta", "--attivita"):
            out[argv[i][2:]] = argv[i + 1]
    if len(argv) != 6 or set(out) != {"cartella", "richiesta", "attivita"}:
        raise ValueError("arguments")
    return out


def _decidi(argv: list[str]) -> int:
    a = _argomenti(argv)
    cartella = Path(a["cartella"])
    try:
        evento = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (ValueError, RecursionError):
        evento = None
    perche: list[str] = []
    stderr = sys.stderr

    class _Raccogli:
        def write(self, s):
            perche.append(s)

        def flush(self):
            pass

    sys.stderr = _Raccogli()
    try:
        if evento is None:
            esito = _no("The guard did not understand the gesture.")
        else:
            esito = giudica(evento, cartella, a["richiesta"], Path(a["attivita"]))
    finally:
        sys.stderr = stderr
    testo = "".join(perche)
    print(testo, end="", file=sys.stderr)
    _registra(cartella, evento, esito, testo)
    return esito if esito in (0, 2) else 2


def main(argv: list[str] | None = None) -> int:
    """Exit 0 lets the tool call run, exit 2 blocks it; on any error the call is blocked."""
    if (sys.argv[1:] if argv is None else argv)[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    try:
        return _decidi(sys.argv[1:] if argv is None else argv)
    except BaseException:  # noqa: BLE001 whatever goes wrong, the gesture does not start
        try:
            print(
                "The guard could not decide and the gesture does not start. Write in ESITO.json what you wanted to do.",
                file=sys.stderr,
            )
        except BaseException:  # noqa: BLE001
            pass
        return 2


if __name__ == "__main__":
    try:
        codice = main()
    except BaseException:  # noqa: BLE001
        codice = 2

    for flusso in (sys.stderr, sys.stdout):
        try:
            flusso.flush()
        except BaseException:  # noqa: BLE001, S110
            pass
    os._exit(codice if codice in (0, 2) else 2)
