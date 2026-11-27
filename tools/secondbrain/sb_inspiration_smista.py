""












from __future__ import annotations


ESITI = ("to do", "backlog", "roadmap", "in lavorazione", "tenuto", "scartato")

CON_TASK = ("to do", "backlog", "roadmap")
ESITI_PAROLE = {
    "to do": "something to do",
    "backlog": "to do, not now",
    "roadmap": "a roadmap feature",
    "in lavorazione": "to dig into here",
    "tenuto": "to keep as a reference",
    "scartato": "not needed",
}

TAG = {"to do": "to-do", "backlog": "backlog", "roadmap": "roadmap"}
ATTIVITA = (
    "prodotto",
    "marketing",
    "contenuti",
    "social",
    "sito",
    "ecommerce",
    "vendite",
    "operativo",
    "locale",
    "menu",
    "deal",
    "fondi",
    "altro",
)
CHI = ("team", "owner")


def _l(lista_id, *percorso):
    return {"lista_id": lista_id, "percorso": list(percorso)}


def _routing_config() -> dict:
    """"inspiration.clickup_lists" in sbk.config.json; empty when it is not set."""
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        from sbk_config import user_cfg
    except ImportError:
        return {}
    cfg = user_cfg("inspiration.clickup_lists", {}) or {}
    return cfg if isinstance(cfg, dict) else {}


# ClickUp routing map, from "inspiration.clickup_lists" in sbk.config.json:
# {"main": "<list id>", "groups": {"deal": "<list id>", "funds": "<list id>"},
#  "projects": {"<Project>": {"*": "<list id>", "<activity>": "<list id>", "roadmap": "<list id>"}}}
# Nothing is built in: an empty list id means no list, and creating the task stops with
# the "list not found" message.
_ROUTING = _routing_config()
_GROUP_LABELS = {"deal": "Deals", "fondi": "Fundraising"}
# English group names accepted in sbk.config.json; the internal code stays what the triage writes.
_GROUP_CONFIG_NAMES = {"fondi": "funds"}

MAIN = _l(str(_ROUTING.get("main") or ""), "Backlog", "Main")

_GROUPS = _ROUTING.get("groups") or {}
DEL_GRUPPO = {
    key: _l(str(_GROUPS.get(_GROUP_CONFIG_NAMES.get(key, key)) or _GROUPS.get(key) or ""), label)
    for key, label in _GROUP_LABELS.items()
}

TODO_TEAM: dict[str, dict] = {}
ROADMAP: dict[str, dict] = {}
for _progetto, _liste in (_ROUTING.get("projects") or {}).items():
    if not isinstance(_liste, dict):
        continue
    _regole = {
        _att: _l(str(_id), _progetto, "To Do" if _att == "*" else _att.capitalize())
        for _att, _id in _liste.items()
        if _att != "roadmap" and str(_id or "").strip()
    }
    if _regole:
        _regole.setdefault("*", next(iter(_regole.values())))
        TODO_TEAM[_progetto] = _regole
    if str(_liste.get("roadmap") or "").strip():
        ROADMAP[_progetto] = _l(str(_liste["roadmap"]), _progetto, "Roadmap")
TODO_TEAM.setdefault("SBK", {"*": MAIN})

ROADMAP_VICINA: set[str] = set()

FRASI = {
    "roadmap_vicina": "{progetto} has no roadmap list, I'm putting it in its backlog",
    "roadmap_manca": "{progetto} has no roadmap list, I'm putting it in your backlog. You decide whether to make one",
    "delicato": "It's a sensitive item, you decide where to put it",
    "senza_progetto": "the item doesn't have a project yet",
}


def _suggerita(progetto, attivita):
    ""
    regole = TODO_TEAM.get(progetto or "")
    if not regole:
        return ""
    lista = regole.get(attivita or "") or regole.get("*")
    if not lista or lista is MAIN:
        return ""
    return " / ".join(lista["percorso"])


def destinazione(esito, progetto, attivita="", chi="team", delicato=False):
    ""


    out = {
        "esito": esito,
        "crea_task": False,
        "lista_id": "",
        "percorso": [],
        "suggerita": "",
        "nota": "",
        "tag": [],
    }
    if esito not in CON_TASK:
        return out
    if delicato:
        out["nota"] = FRASI["delicato"]
        return out
    progetto = progetto or "altro"
    lista = None
    if esito == "backlog":
        lista = MAIN
        out["suggerita"] = _suggerita(progetto, attivita)
    elif esito == "roadmap":
        lista = ROADMAP.get(progetto)
        if lista is None:
            lista = MAIN
            out["suggerita"] = f"roadmap for {progetto}"
            out["nota"] = FRASI["roadmap_manca"].format(progetto=progetto)
        elif progetto in ROADMAP_VICINA:
            out["nota"] = FRASI["roadmap_vicina"].format(progetto=progetto)
    else:
        if attivita in DEL_GRUPPO:
            lista = DEL_GRUPPO[attivita]
        elif chi == "owner":
            lista = MAIN
        else:
            regole = TODO_TEAM.get(progetto)
            if regole:
                lista = regole.get(attivita or "") or regole["*"]
            else:
                lista = MAIN
                out["suggerita"] = f"to do for {progetto}"
    out.update(
        crea_task=True,
        lista_id=lista["lista_id"],
        percorso=list(lista["percorso"]),
        tag=["inspiration", TAG[esito]],
    )
    return out


def liste():
    ""
    viste = {}
    tutte = [MAIN, *ROADMAP.values(), *DEL_GRUPPO.values()]
    for regole in TODO_TEAM.values():
        tutte += list(regole.values())
    for lista in tutte:
        viste[lista["lista_id"]] = lista["percorso"]
    return viste
