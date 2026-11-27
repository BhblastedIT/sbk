#!/usr/bin/env python3
"""Decides whether a name can be compared for deduplication: one person's name, as opposed to initials, a
composite ("A / B"), a role or an organization. Uncertain names are marked UNSURE so no merge touches them.
--nome judges one name; without it, it measures the whole knowledge base.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from conteggio import Conteggio  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))




from entity_dedup_index import _COMPANY_ALLOWLIST, _COMPOSITE_RE, is_composite  # noqa: E402

__all__ = [
    "UNSURE",
    "CONFRONTABILE",
    "Giudizio",
    "blocca_attivo",
    "confrontabile",
    "giudica",
    "misura",
]




CONFRONTABILE = "CONFRONTABILE"
UNSURE = "UNSURE"





ENV_BLOCCA = "SBK_CONFRONTABILE_BLOCCA"


def blocca_attivo() -> bool:
    ""
    return os.environ.get(ENV_BLOCCA, "").strip().lower() in ("1", "true", "yes", "si")




_SBP = None


def _sb_persone():
    ""






    global _SBP  # noqa: PLW0603
    if _SBP is None:
        perc = _TOOLS_DIR / "util" / "sb-persone.py"
        spec = importlib.util.spec_from_file_location("sb_persone_confrontabile", perc)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["sb_persone_confrontabile"] = mod
        spec.loader.exec_module(mod)
        _SBP = mod
    return _SBP















_COMPOSITO_IN_PIU = re.compile(r"[/;]|(?<=\S)&(?=\S)|\s[+]\s|\bcon\b\s+[A-Z]", re.I)





_TRASCRIZIONE = re.compile(r"\b(speaker|participants?|unknown|attendees?|relatore)\b", re.I)




_HA_LETTERE = re.compile(r"[^\W\d_]", re.UNICODE)







_UTILE = re.compile(r"[^\W_]", re.UNICODE)



_PERSONA = ("person", "persona", "people")
_ORGANIZZAZIONE = ("organization", "organisation", "org", "company", "azienda")








_TITOLI_MISTI = frozenset(
    {
        "PhD",
        "MSc",
        "BSc",
        "MBA",
        "EMBA",
        "MEng",
        "BEng",
        "MPhil",
        "MSt",
        "LLM",
        "LLB",
        "MD",
        "JD",
        "Esq",
        "Jr",
        "Sr",
        "MA",
        "BA",
        "MPA",
        "MPH",
    }
)


def _e_sigla(pezzo: str, sbp) -> bool:
    ""
























    secco = re.sub(r"[.\s]", "", pezzo)
    if not (2 <= len(secco) <= 8) or not secco.isalpha():
        return False
    if secco in _TITOLI_MISTI:
        return True
    if not secco.isupper():
        return False
    return not _e_organizzazione_nota(pezzo, sbp)


def _una_persona_sola(nudo: str, sbp) -> bool:
    ""






















    if re.search(r"[/&;]|\s[+]\s", nudo):
        return False
    pezzi = [p.strip() for p in nudo.split(",") if p.strip()]
    if len(pezzi) < 2:
        return False
    while len(pezzi) > 1 and _e_sigla(pezzi[-1], sbp):
        pezzi.pop()
    if len(pezzi) == 1:
        return True
    if len(pezzi) != 2:
        return False
    primo, secondo = pezzi[0].split(), pezzi[1].split()
    if not primo or not secondo or len(primo) > 2 or len(secondo) > 2:
        return False
    if not all(sbp.e_nome_di_battesimo(p) for p in secondo):
        return False
    if sbp.e_nome_di_battesimo(primo[0]):
        return False



    return not _e_organizzazione_nota(pezzi[0], sbp)






CODICI = (
    "nome_vuoto",
    "nome_e_identificativo",
    "nessuna_lettera",
    "indirizzo_email",
    "composito",
    "troppo_corto",
    "etichetta_trascrizione",
    "forma_societaria",
    "ruolo_o_funzione",
    "parentetica_organizzazione",
    "gia_organizzazione",
    "tipo_sconosciuto",
)


def _separatore_composito(nome: str, nudo: str, sbp) -> str:
    ""













    if _una_persona_sola(nudo, sbp):
        return ""
    if is_composite(nome):







        m = _COMPOSITE_RE.search(nome)
        return re.sub(r"\s*[A-Z]$", "", m.group(0).strip()) if m else ","
    if nome.strip().lower() in _COMPANY_ALLOWLIST:
        return ""
    m = _COMPOSITO_IN_PIU.search(nudo)
    return m.group(0).strip() if m else ""


@dataclass(frozen=True)
class Giudizio:
    ""










    nome: str
    tipo: str
    esito: str
    ragioni: tuple[str, ...]
    codici: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.esito == CONFRONTABILE

    def __str__(self) -> str:
        if self.ok:
            return f"CONFRONTABILE «{self.nome}»"
        return f"UNSURE «{self.nome}» — " + " · ".join(self.ragioni)


def giudica(nome: str, tipo: str = "person", *, entity_id: str = "") -> Giudizio:
    ""





    n = str(nome or "").strip()
    t = str(tipo or "").strip().lower()

    fuori: list[tuple[str, str]] = []

    def _chiudi() -> Giudizio:
        if not fuori:
            return Giudizio(n, t, CONFRONTABILE, (), ())
        return Giudizio(n, t, UNSURE, tuple(f for _, f in fuori), tuple(c for c, _ in fuori))




    if not n:
        fuori.append(("nome_vuoto", "the name is empty: there is nothing to compare"))
        return _chiudi()
    if entity_id and n == entity_id:
        fuori.append(
            ("nome_e_identificativo", "the name is the entity identifier, not a name")
        )
        return _chiudi()
    if re.match(r"^(person|org|organization|deal|commitment)_[0-9a-f]{6,}$", n, re.I):
        fuori.append(("nome_e_identificativo", "the name is a coined identifier, not a name"))
        return _chiudi()

    if not _HA_LETTERE.search(n):
        fuori.append(
            ("nessuna_lettera", "no letter in the name: it is a number or a symbol, not a name")
        )





    nudo = re.sub(r"\(.*?\)", " ", n).strip()
    dentro = " ".join(re.findall(r"\((.*?)\)", n))

    sbp = _sb_persone()

    if "@" in n:
        fuori.append(("indirizzo_email", "the name is (or contains) an email address, not a name"))

    sep = _separatore_composito(n, nudo, sbp)
    if sep:
        fuori.append(
            ("composito", f"composite name: two parts in a single name (separator «{sep}»)")
        )



    utile = "".join(_UTILE.findall(nudo))
    if len(utile) <= 2:
        fuori.append(
            ("troppo_corto", f"too short ({len(utile)} useful characters): identifies no one")
        )

    if _TRASCRIZIONE.search(n):
        fuori.append(
            (
                "etichetta_trascrizione",
                "transcript label (Speaker/Participant/Unknown), not a name",
            )
        )

    if t in _PERSONA:




        if sbp.AZIENDA.search(nudo):
            fuori.append(
                (
                    "forma_societaria",
                    "company form inside a person name (sb-persone.AZIENDA)",
                )
            )
        if sbp.RUOLO.search(nudo):
            fuori.append(
                ("ruolo_o_funzione", "the name is a role or a function, not who holds it")
            )
        elif (
            dentro
            and sbp.RUOLO.search(dentro)
            and len(nudo.split()) < 2
            and not sbp.e_nome_di_battesimo(nudo)
        ):







            fuori.append(
                (
                    "parentetica_organizzazione",
                    f"the parenthetical qualifies an organization: «{dentro[:38]}»",
                )
            )
        if _e_organizzazione_nota(nudo, sbp):
            fuori.append(
                ("gia_organizzazione", "an organization record with this name already exists")
            )
    elif t not in _ORGANIZZAZIONE:
        fuori.append(
            (
                "tipo_sconosciuto",
                f"unknown type «{tipo}»: I don't know by what measure to judge this name",
            )
        )

    return _chiudi()


def _e_organizzazione_nota(nudo: str, sbp) -> bool:
    ""






    try:
        noti = sbp.nomi_di_organizzazione()
    except Exception:  # pragma: no cover — store assente o illeggibile
        return False
    if not noti:
        return False
    k = sbp.norm(nudo)
    return bool(k) and (k in noti or k.replace(" ", "") in noti)


def confrontabile(nome: str, tipo: str = "person") -> tuple[bool, list[str]]:
    ""












    g = giudica(nome, tipo)
    return g.ok, list(g.ragioni)





def censisci(nomi, tipo: str = "person") -> tuple[Conteggio, list[Giudizio]]:
    ""







    fuori: list[Giudizio] = []
    su = 0
    for x in nomi:
        su += 1
        eid, nome = ("", x) if isinstance(x, str) else (x[0], x[1])
        g = giudica(nome, tipo, entity_id=eid)
        if not g.ok:
            fuori.append(g)
    return Conteggio(len(fuori), su, {"unreadable name": 0}), fuori


def _archivio_fusioni() -> Path:
    import sbk_config as cfg

    return cfg.KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "deduped"


def misura(cartella: Path | None = None) -> dict:
    ""








    d = Path(cartella) if cartella else _archivio_fusioni()
    sbp = _sb_persone()
    try:
        contro_prova = len(sbp.nomi_di_organizzazione())
    except Exception:  # pragma: no cover
        contro_prova = 0

    saltati = {"unreadable json": 0, "missing canonical_name": 0}
    su = 0
    fermate: list[Giudizio] = []
    per_ragione: dict[str, int] = {}
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                dati = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                saltati["unreadable json"] += 1
                continue
            if (dati.get("merged_by") or "") != "l4-03-exact-dedup":
                continue
            nome = (dati.get("canonical_name") or "").strip()
            if not nome:
                saltati["missing canonical_name"] += 1
                continue
            su += 1
            g = giudica(nome, "person", entity_id=dati.get("entity_id") or "")
            if not g.ok:
                fermate.append(g)
                for c in g.codici:
                    per_ragione[c] = per_ragione.get(c, 0) + 1
    if not contro_prova:


        saltati["organization cross-check unavailable"] = 1

    return {
        "fermate": Conteggio(len(fermate), su, saltati),
        "per_ragione": per_ragione,
        "campioni": fermate[:20],
        "organizzazioni_note": contro_prova,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Is this name comparable?")
    ap.add_argument("--nome", default="", help="judge a single name and exit")
    ap.add_argument("--tipo", default="person", help="person · organization")
    ap.add_argument("--quanti", type=int, default=15, help="how many samples to print")
    a = ap.parse_args()

    if a.nome:
        print(giudica(a.nome, a.tipo))
        return 0

    m = misura()
    c = m["fermate"]
    print("\nMERGES ALREADY PERFORMED by l4-03 that this guard would send to UNSURE\n")
    print(f"   {c!s}   ({c.percentuale(1)}%)")
    print(f"   cross-check: {m['organizzazioni_note']} organization names in the store\n")
    for k, n in sorted(m["per_ragione"].items(), key=lambda x: -x[1]):
        print(f"   {n:5}  {k}")
    print("\n── samples:\n")
    for g in m["campioni"][: a.quanti]:
        print(f"   {g}")
    print(
        "\n  ⚠️  UNSURE does not mean «discarded»: it means counted and named. "
        f"Blocking only with {ENV_BLOCCA}=1 (now: "
        f"{'ON' if blocca_attivo() else 'OFF'})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
