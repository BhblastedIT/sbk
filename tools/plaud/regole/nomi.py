""









from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

DATA = Path(os.environ.get("SBK_DATA", Path.home() / ".sbk-data"))
NAME_INDEX = DATA / "plaud" / "pl-name-index.json"
PERSONE = DATA / "knowledge" / "entities" / "person"



def norm(s: str | None) -> str:
    ""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


# You, from sbk.config.json (owner, own_names): the full name and the other
# labels a recording can use for you (first name, nicknames, initials).
_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sbk_config import OWNER_NAME, OWNER_SPEAKER_LABELS  # noqa: E402

OWNER_CANONICO = norm(OWNER_NAME)
OWNER_PRIMO = OWNER_CANONICO.split()[0] if OWNER_CANONICO else ""
OWNER_TOKENS = frozenset(norm(x) for x in OWNER_SPEAKER_LABELS) - {OWNER_CANONICO, ""}




DIMINUTIVI: dict[str, str] = {
    "peppe": "giuseppe", "peppino": "giuseppe", "pino": "giuseppe", "beppe": "giuseppe", "pippo": "giuseppe",
    "gigi": "luigi", "gino": "luigi",
    "enzo": "vincenzo", "vince": "vincenzo", "vincy": "vincenzo", "lello": "raffaele",
    "gianni": "giovanni", "nanni": "giovanni", "tonino": "antonio", "toni": "antonio", "tony": "antonio",
    "max": "massimiliano", "mimmo": "domenico", "nino": "antonino", "franco": "francesco", "ciccio": "francesco",
    "checco": "francesco", "teo": "matteo", "ste": "stefano", "stefi": "stefania", "fede": "federico",
    "vale": "valentina", "manu": "emanuele", "lele": "emanuele", "gabri": "gabriele", "ricky": "riccardo",
    "dani": "daniele", "andre": "andrea", "ale": "alessandro", "sandro": "alessandro", "michi": "michele",
    "nico": "nicola", "titti": "concetta",
}
DIMINUTIVI.update({t: OWNER_PRIMO for t in OWNER_TOKENS if OWNER_PRIMO and " " not in t and t != OWNER_PRIMO})

M_IN_A = frozenset(
    [
        "andrea",
        "battista",
        "elia",
        "enea",
        "evangelista",
        "geremia",
        "gianluca",
        "giosue",
        "isaia",
        "joshua",
        "luca",
        "mattia",
        "nicola",
        "noa",
        "tobia",
        "zaccaria",
    ]
)
F_ALTRO = frozenset(
    [
        "adele",
        "agnese",
        "alice",
        "allison",
        "beatrice",
        "berenice",
        "carmen",
        "clarice",
        "deborah",
        "desiree",
        "elisabeth",
        "elizabeth",
        "ester",
        "esther",
        "greta",
        "ingrid",
        "irene",
        "iris",
        "jennifer",
        "karen",
        "kate",
        "matilde",
        "michelle",
        "miriam",
        "nicole",
        "nives",
        "noemi",
        "rachel",
        "rachele",
        "rebecca",
        "ruth",
        "sarah",
    ]
)
M_ALTRO = frozenset(
    [
        "achille",
        "adam",
        "adriano",
        "ahmed",
        "alessandro",
        "alex",
        "ali",
        "angelo",
        "antonio",
        "ben",
        "brendan",
        "carlo",
        "carmine",
        "cesare",
        "chris",
        "christian",
        "claudio",
        "crescenzo",
        "cristian",
        "dan",
        "daniele",
        "david",
        "davide",
        "dmitri",
        "domenico",
        "edoardo",
        "emanuele",
        "emilio",
        "enrico",
        "ercole",
        "ernesto",
        "ettore",
        "fabio",
        "federico",
        "felice",
        "filippo",
        "francesco",
        "fulvio",
        "gabriele",
        "giacomo",
        "giammarco",
        "gianni",
        "giorgio",
        "giovanni",
        "giuliano",
        "giuseppe",
        "hans",
        "igor",
        "ivan",
        "james",
        "jan",
        "jean",
        "john",
        "jordan",
        "josh",
        "karim",
        "kevin",
        "lars",
        "leonardo",
        "lorenzo",
        "luigi",
        "marcello",
        "marco",
        "mario",
        "mark",
        "massimo",
        "matt",
        "matteo",
        "michael",
        "michele",
        "mohamed",
        "nick",
        "oleg",
        "omar",
        "paolo",
        "pasquale",
        "paul",
        "peter",
        "pierre",
        "pietro",
        "raffaele",
        "riccardo",
        "roberto",
        "ryan",
        "sam",
        "sandro",
        "sergei",
        "sergio",
        "simone",
        "stefano",
        "steve",
        "sven",
        "tom",
        "tommaso",
        "umberto",
        "valentino",
        "vincenzo",
        "yuri",
    ]
)
NOMI_ITALIANI = frozenset(
    [
        "adriano",
        "alessandra",
        "alessandro",
        "alessia",
        "alex",
        "alfonso",
        "alice",
        "andrea",
        "angela",
        "angelo",
        "aniello",
        "anna",
        "antonella",
        "antonio",
        "arturo",
        "barbara",
        "beatrice",
        "biagio",
        "bruno",
        "camilla",
        "carlo",
        "carmela",
        "carmine",
        "chiara",
        "christian",
        "ciro",
        "claudia",
        "claudio",
        "concetta",
        "corrado",
        "cosimo",
        "crescenzo",
        "cristian",
        "cristina",
        "dalila",
        "dana",
        "daniela",
        "daniele",
        "dario",
        "davide",
        "dino",
        "domenica",
        "domenico",
        "edoardo",
        "egidio",
        "elena",
        "eleonora",
        "elio",
        "elisa",
        "emanuele",
        "emilio",
        "emma",
        "enrico",
        "ernesto",
        "ettore",
        "fabio",
        "fabrizio",
        "federica",
        "federico",
        "felice",
        "filippo",
        "flavio",
        "francesca",
        "francesco",
        "franco",
        "fulvio",
        "gabriele",
        "gaetano",
        "gennaro",
        "gerardo",
        "giacomo",
        "giammarco",
        "gianluca",
        "gianni",
        "giorgia",
        "giorgio",
        "giovanna",
        "giovanni",
        "giulia",
        "giuliano",
        "giuseppe",
        "guido",
        "ilaria",
        "irene",
        "ivan",
        "jacopo",
        "laura",
        "leonardo",
        "lino",
        "loredana",
        "lorena",
        "lorenzo",
        "luca",
        "lucia",
        "luciano",
        "ludovica",
        "luigi",
        "manlio",
        "manuela",
        "mara",
        "marcello",
        "marco",
        "maria",
        "marina",
        "mario",
        "marta",
        "martina",
        "massimo",
        "matilde",
        "matteo",
        "mattia",
        "maurizio",
        "mauro",
        "michela",
        "michele",
        "monica",
        "nadia",
        "nello",
        "nicola",
        "nicoletta",
        "nicolo",
        "noemi",
        "nunzio",
        "orazio",
        "ornella",
        "paola",
        "paolo",
        "pasquale",
        "patrizia",
        "piero",
        "pietro",
        "raffaele",
        "raffaella",
        "renato",
        "renzo",
        "riccardo",
        "rino",
        "rita",
        "roberta",
        "roberto",
        "rocco",
        "rosa",
        "rosario",
        "sabato",
        "sabrina",
        "sandro",
        "sara",
        "sebastiano",
        "serena",
        "sergio",
        "silvia",
        "silvio",
        "simona",
        "simone",
        "sonia",
        "stefania",
        "stefano",
        "teresa",
        "tiziana",
        "tiziano",
        "tommaso",
        "ugo",
        "umberto",
        "valentina",
        "valentino",
        "valeria",
        "vanessa",
        "veronica",
        "vincenzo",
        "vittorio",
        "viviana",
        "walter",
    ]
)
EXTRA_PERSONA = frozenset(
    [
        "agostino",
        "alessio",
        "amedeo",
        "anita",
        "annalisa",
        "arnaldo",
        "assunta",
        "bartolomeo",
        "benedetto",
        "brendan",
        "camillo",
        "carla",
        "carlos",
        "carmen",
        "carolina",
        "cristiano",
        "dana",
        "denis",
        "diego",
        "dimitri",
        "emma",
        "eugenio",
        "ezio",
        "fausto",
        "ferdinando",
        "fernando",
        "filomena",
        "flavia",
        "frank",
        "franz",
        "gaia",
        "george",
        "giada",
        "giancarlo",
        "gianfranco",
        "gianmarco",
        "gianpaolo",
        "gilberto",
        "gioele",
        "girolamo",
        "giulio",
        "graziano",
        "guglielmo",
        "ignazio",
        "immacolata",
        "italo",
        "ivano",
        "jason",
        "jose",
        "juan",
        "leo",
        "luana",
        "luciana",
        "lucio",
        "luis",
        "manuel",
        "marcantonio",
        "marisa",
        "mark",
        "mary",
        "milena",
        "mirella",
        "miriam",
        "mirko",
        "natalia",
        "nicole",
        "nunzia",
        "oscar",
        "ottavio",
        "patrick",
        "pedro",
        "pierluigi",
        "raimondo",
        "remo",
        "richard",
        "robert",
        "romano",
        "rossella",
        "samuele",
        "santino",
        "santo",
        "saverio",
        "sean",
        "severino",
        "silvano",
        "stella",
        "steve",
        "tullio",
        "valerio",
        "victor",
        "vito",
        "william",
    ]
)

NON_NOMI = frozenset(
    [
        "speaker",
        "rumore",
        "varie",
        "demo",
        "unknown",
        "sconosciuto",
        "misto",
        "voce",
        "partner",
        "partnership",
        "team",
        "ceo",
        "cfo",
        "cto",
        "ufficio",
        "studio",
        "the",
        "and",
        "di",
        "de",
        "da",
        "la",
        "le",
        "lo",
        "il",
        "del",
        "della",
        "dei",
        "per",
        "con",
        "non",
        "che",
    ]
)


def genere_nome(primo: str | None) -> str:
    ""

    t = norm(primo).split()
    if not t:
        return ""
    p = DIMINUTIVI.get(t[0], t[0])
    if p in M_IN_A or p in M_ALTRO:
        return "m"
    if p in F_ALTRO:
        return "f"
    if len(p) >= 3 and p.endswith("a"):
        return "f"
    if len(p) >= 3 and p.endswith("o"):
        return "m"
    return ""


def e_italiano(primo: str | None) -> bool | None:
    t = norm(primo).split()
    if not t:
        return None
    return DIMINUTIVI.get(t[0], t[0]) in NOMI_ITALIANI


def nome_intero(token: str) -> str:
    ""
    n = norm(token)
    return DIMINUTIVI.get(n, alias_kb().get(n, n))


def e_owner(nome: str | None) -> bool:
    n = norm(nome)
    if not n:
        return False
    return n in OWNER_TOKENS or bool(OWNER_CANONICO and n.startswith(OWNER_CANONICO))


@lru_cache(maxsize=1)
def alias_kb() -> dict[str, str]:
    ""




    if not NAME_INDEX.exists():
        return {}
    try:
        alias = json.loads(NAME_INDEX.read_text()).get("alias") or {}
    except (OSError, json.JSONDecodeError):
        return {}
    base = (
        NOMI_ITALIANI | M_ALTRO | F_ALTRO | M_IN_A | EXTRA_PERSONA | frozenset(DIMINUTIVI.values())
    )
    out: dict[str, str] = {}
    for a, ids in alias.items():
        a = norm(a)
        if (
            " " in a
            or not a.isalpha()
            or len(a) < 3
            or a in NON_NOMI
            or a in base
            or a in DIMINUTIVI
        ):
            continue
        primi = set()
        for pid in ids[:5]:
            p = PERSONE / f"{pid}.json"
            try:


                with p.open(errors="ignore") as fh:
                    testa = fh.read(2000)
            except OSError:
                continue
            m = re.search(r'"canonical_name":\s*"((?:[^"\\]|\\.)*)"', testa)
            t = norm(json.loads(f'"{m.group(1)}"') if m else "").split()
            if t:
                primi.add(t[0])

        primi = {
            f
            for f in primi
            if f in base and f[:2] == a[:2] and len(a) < len(f) and not a.startswith(f)
        }
        if len(primi) == 1:
            out[a] = primi.pop()
    return out


def nomi_persona(etichette: Iterable[str] | None = None, con_alias: bool = True) -> frozenset[str]:
    ""

    base = set(NOMI_ITALIANI | M_ALTRO | F_ALTRO | M_IN_A | EXTRA_PERSONA | OWNER_TOKENS)
    base |= set(DIMINUTIVI) | set(DIMINUTIVI.values())
    if con_alias:
        base |= set(alias_kb())
    for e in etichette or ():
        t = norm(e).split()
        if t and t[0].isalpha() and len(t[0]) >= 3 and t[0] not in NON_NOMI:
            base.add(t[0])
    return frozenset(base - NON_NOMI)


def corrisponde(nome: str, etichetta: str) -> bool:
    ""
    n = norm(nome)
    if not n:
        return False
    if (
        len(n.split()) > 1
    ):
        primo, resto = n.split()[0], set(n.split()[1:])
        toks = norm(etichetta).split()
        if e_owner(n):
            return e_owner(etichetta)
        return corrisponde(primo, etichetta) and (len(toks) == 1 or bool(resto & set(toks[1:])))
    if e_owner(etichetta):
        return e_owner(n) or bool(OWNER_PRIMO and nome_intero(n) == OWNER_PRIMO)
    toks = norm(etichetta).split()
    pieni = {nome_intero(t) for t in toks}
    return n in toks or nome_intero(n) in toks or nome_intero(n) in pieni
