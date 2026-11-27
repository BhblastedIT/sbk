"""Deduplication index of the people in the knowledge base (LinkedIn slug, normalized name) and the promotion of
second-class contacts into entities. Dry run by default; --promuovi --apply writes a reversible journal.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

from rapidfuzz import fuzz

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_schema import (  # noqa: E402
    ATTR_CLASSE,
    ATTR_RISCONTRO,
    attio_record_id_di,
    chiavi_forti_di,
    e_seconda_classe,
    nome_senza_discriminante,
)

log = logging.getLogger("sbk.entity-dedup-index")




_ATTR_LINKEDIN = ("contact.linkedin_url",)

_SLUG_RE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)


def slug_linkedin(url: str) -> str:
    ""




    m = _SLUG_RE.search(str(url or "").strip())
    if not m:
        return ""
    return m.group(1).rstrip("/").lower()





_TITLES = {
    "dr",
    "dr.",
    "prof",
    "prof.",
    "ing",
    "ing.",
    "avv",
    "avv.",
    "dott",
    "dott.",
    "sig",
    "sig.",
    "mr",
    "mr.",
    "mrs",
    "mrs.",
    "ms",
    "ms.",
    "sir",
    "dame",
    "rev",
    "rev.",
}


_COMPOSITE_RE = re.compile(
    r"""
    ,\s*[A-Z]           |  # comma + capital: "Sam, Drew"
    \s+/\s+             |  # slash: "Mario / Dana"
    \s+&\s+             |  # ampersand: "Sam & Drew"
    \band\b(?=\s+[A-Z]) |  # English "and" + capital
    \be\b(?=\s+[A-Z])      # Italian "e" + capital
    """,
    re.VERBOSE,
)


_COMPANY_ALLOWLIST = {
    "johnson & johnson",
    "dolce & gabbana",
    "procter & gamble",
    "smith & wesson",
    "marks & spencer",
    "simon & schuster",
    "tiffany & co",
    "barnes & noble",
    "ben & jerry",
    "abercrombie & fitch",
    "kraft heinz",
    "ernst & young",
}





def normalize_name(name: str) -> str:
    ""






    if not name:
        return ""

    name = name.lower().strip()

    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))

    parts = name.split()
    parts = [p for p in parts if p.rstrip(".") not in _TITLES]

    return " ".join(parts).strip()


def is_composite(name: str) -> bool:
    ""
    if not name:
        return False

    if name.strip().lower() in _COMPANY_ALLOWLIST:
        return False
    return bool(_COMPOSITE_RE.search(name))












_DIVARIO_ANAGRAMMA = 30


def _epoch(iso) -> float:
    ""
    if not iso:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


class EntityDedupIndex:
    ""

    def __init__(self, entities_dir: Path | None = None, *, escludi_valore=None):
        self._loaded = False
        self._entities_dir = entities_dir






        self._escludi_valore = escludi_valore



        self._con_chiave_forte: set[str] = set()





        self._name_to_id: dict[str, str] = {}
        self._name_rango: dict[str, tuple] = {}

        self._email_to_id: dict[str, str] = {}

        self._all_names: dict[str, str] = {}




        self._linkedin_to_id: dict[str, str] = {}
        self._stats = {"total": 0, "with_email": 0, "with_linkedin": 0}

    def _ensure_loaded(self):
        ""
        if self._loaded:
            return
        self._load_all_person_entities()
        self._loaded = True

    def _load_all_person_entities(self):
        ""
        from sbk_config import KNOWLEDGE_ENTITIES_DIR

        person_dir = self._entities_dir or (KNOWLEDGE_ENTITIES_DIR / "person")
        if not person_dir.exists():
            log.warning("Person entity directory not found: %s", person_dir)
            return

        count = 0
        for f in person_dir.iterdir():
            if not f.name.endswith(".json") or f.name.startswith("_"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entity_id = data.get("entity_id", "")
                canonical = data.get("canonical_name", "")
                if not entity_id or not canonical:
                    continue

                facts = data.get("facts", [])
                seconda = e_seconda_classe(facts)



                forte = bool(chiavi_forti_di(facts, "person", escludi=self._escludi_valore))
                if forte:
                    self._con_chiave_forte.add(entity_id)


                normalized = normalize_name(canonical)
                if normalized:
                    rango = (forte, len(facts), -_epoch(data.get("created_at")))
                    prec = self._name_rango.get(normalized)
                    if prec is None or rango > prec:
                        self._name_rango[normalized] = rango
                        self._name_to_id[normalized] = entity_id


                self._all_names[entity_id] = normalized


                for fact in facts:
                    attr = fact.get("attribute", "")
                    if (
                        attr in ("contact.email", "identity.email")
                        and fact.get("confidence", 0) >= 0.7
                    ):
                        email = str(fact.get("value", "")).strip().lower()
                        if email and "@" in email and email not in self._email_to_id:
                            self._email_to_id[email] = entity_id
                            self._stats["with_email"] += 1
                    elif attr in _ATTR_LINKEDIN and not seconda:
                        slug = slug_linkedin(fact.get("value", ""))




                        if slug and slug not in self._linkedin_to_id:
                            self._linkedin_to_id[slug] = entity_id
                            self._stats["with_linkedin"] += 1

                count += 1
            except (json.JSONDecodeError, OSError):
                continue

        self._stats["total"] = count
        log.info(
            "EntityDedupIndex loaded: %d entities, %d unique names, %d emails, %d linkedin",
            count,
            len(self._name_to_id),
            len(self._email_to_id),
            len(self._linkedin_to_id),
        )

    def trova_per_nome_esatto(self, nome: str) -> str:
        ""












        self._ensure_loaded()
        n = normalize_name(nome or "")
        return self._name_to_id.get(n, "") if n else ""

    def ha_chiave_forte(self, entity_id: str) -> bool:
        ""







        self._ensure_loaded()
        return str(entity_id or "") in self._con_chiave_forte

    def trova_per_linkedin(self, url_o_slug: str):
        ""





        self._ensure_loaded()
        s = str(url_o_slug or "").strip()
        slug = slug_linkedin(s) or (s.lower() if "/" not in s and " " not in s else "")
        if not slug:
            return None
        return self._linkedin_to_id.get(slug)

    def find_existing_entity(
        self,
        name: str,
        email: str | None = None,
        linkedin: str | None = None,
    ) -> tuple[str, float, str] | None:
        ""

















        self._ensure_loaded()
        del linkedin


        if is_composite(name):
            log.debug("COMPOSITE BLOCKED: '%s'", name)
            return None

        normalized = normalize_name(name)
        if not normalized:
            return None


        if normalized in self._name_to_id:
            return (self._name_to_id[normalized], 1.0, "exact_name")


        if email:
            email_lower = email.strip().lower()
            if email_lower in self._email_to_id:
                return (self._email_to_id[email_lower], 0.95, "email_exact")


        if len(self._all_names) > 0:
            threshold = self._get_dynamic_threshold(normalized)
            best_match = None
            best_score = 0

            for eid, existing_name in self._all_names.items():
                if not existing_name:
                    continue
                score = fuzz.token_sort_ratio(normalized, existing_name)
                if score >= threshold and score > best_score:











                    if score - fuzz.ratio(
                        normalized, existing_name
                    ) >= _DIVARIO_ANAGRAMMA and sorted(normalized.split()) != sorted(
                        existing_name.split()
                    ):
                        continue
                    best_score = score
                    best_match = eid

            if best_match:
                confidence = round(best_score / 100.0, 3)
                return (best_match, confidence, "fuzzy_name")


        if " " not in normalized and len(normalized) >= 3:
            first_name_matches = []
            for eid, existing_name in self._all_names.items():
                if not existing_name:
                    continue

                parts = existing_name.split()
                if parts and parts[0] == normalized:
                    first_name_matches.append((eid, existing_name))
            if len(first_name_matches) == 1:
                eid, full_name = first_name_matches[0]
                log.debug("FIRST-NAME UNIVOCAL: '%s' -> '%s' (%s)", name, full_name, eid)
                return (eid, 0.75, "first_name_univocal")

        return None

    @staticmethod
    def _get_dynamic_threshold(name: str) -> float:
        ""
        char_count = len(name.replace(" ", ""))
        if char_count <= 8:
            return 95
        if char_count <= 15:
            return 90
        return 88

























def _leggi_entita(percorso: Path) -> dict | None:
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("unreadable profile, SKIPPED: %s (%s)", percorso, e)
        return None


def _slug_di(dati: dict) -> str:
    for f in dati.get("facts", []):
        if f.get("attribute", "") in _ATTR_LINKEDIN:
            slug = slug_linkedin(f.get("value", ""))
            if slug:
                return slug
    return ""


def proposte_di_promozione(person_dir: Path | None = None) -> list[dict]:
    ""




    from sbk_config import KNOWLEDGE_ENTITIES_DIR

    pdir = person_dir or (KNOWLEDGE_ENTITIES_DIR / "person")
    if not pdir.exists():
        log.warning("Person entity directory not found: %s", pdir)
        return []

    seconde: list[tuple[Path, dict]] = []

    per_chiave: dict[tuple, list[str]] = {}
    percorsi: dict[str, Path] = {}

    for f in sorted(pdir.iterdir()):
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        dati = _leggi_entita(f)
        if not dati or not dati.get("entity_id"):
            continue
        if e_seconda_classe(dati.get("facts", [])):
            seconde.append((f, dati))
            continue
        slug = _slug_di(dati)
        nome = normalize_name(dati.get("canonical_name", ""))
        if slug and nome:
            per_chiave.setdefault((slug, nome), []).append(dati["entity_id"])
        percorsi[dati["entity_id"]] = f

    proposte = []
    for percorso, dati in seconde:
        slug = _slug_di(dati)
        nome = normalize_name(nome_senza_discriminante(dati.get("canonical_name", "")))
        if not slug or not nome:
            continue
        bersagli = per_chiave.get((slug, nome), [])
        if len(bersagli) != 1:


            continue
        proposte.append(
            {
                "seconda_classe": dati["entity_id"],
                "nome": dati.get("canonical_name", ""),
                "attio_record_id": attio_record_id_di(dati.get("facts", [])),
                "prima_classe": bersagli[0],
                "slug": slug,
                "percorso_seconda": percorso,
                "percorso_prima": percorsi[bersagli[0]],
                "fatti": len(dati.get("facts", [])),
            }
        )
    return proposte


def promuovi(
    person_dir: Path | None = None,
    *,
    applica: bool = False,
    cartella_journal: Path | None = None,
) -> list[dict]:
    ""








    from journal_fusioni import Journal

    from sbk_config import KNOWLEDGE_ENTITIES_DIR, safe_write_json

    pdir = person_dir or (KNOWLEDGE_ENTITIES_DIR / "person")
    proposte = proposte_di_promozione(pdir)
    if not proposte:
        return []

    archivio = pdir.parent.parent / "archive" / "promosse"
    adesso = datetime.now(timezone.utc).isoformat()  # noqa: UP017

    with Journal("promozione-seconda-classe", attivo=applica, cartella=cartella_journal) as j:
        for prop in proposte:
            canonico = _leggi_entita(prop["percorso_prima"])
            fusa = _leggi_entita(prop["percorso_seconda"])
            if canonico is None or fusa is None:
                continue

            j.fusione(
                prop["prima_classe"],
                prop["seconda_classe"],
                motivo=f"second-class promotion: LinkedIn slug AND name ({prop['slug']})",
                punteggi={
                    "attio_record_id": prop["attio_record_id"],
                    "fatti_fusa": prop["fatti"],
                },
            )

            chiavi = {
                (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
                for f in canonico.get("facts", [])
            }
            guadagnati = 0
            for fatto in fusa.get("facts", []):
                if fatto.get("attribute", "") in (ATTR_CLASSE, ATTR_RISCONTRO):








                    j.fatto_scartato(
                        fatto, da=prop["seconda_classe"], perche="entity marker, does not migrate"
                    )
                    continue
                chiave = (fatto.get("attribute", ""), str(fatto.get("value", "")).strip().lower())
                if chiave in chiavi:
                    j.fatto_scartato(
                        fatto, da=prop["seconda_classe"], perche="duplicate (attribute,value)"
                    )
                    continue
                j.fatto(fatto, da=prop["seconda_classe"], a=prop["prima_classe"])
                canonico.setdefault("facts", []).append(
                    {
                        **fatto,
                        "entity_id": prop["prima_classe"],
                        "source_entity_id": fatto.get("entity_id"),
                    }
                )
                chiavi.add(chiave)
                guadagnati += 1

            prop["fatti_guadagnati"] = guadagnati
            if not applica:
                continue

            canonico["updated_at"] = adesso
            canonico["version"] = int(canonico.get("version", 1)) + 1
            safe_write_json(prop["percorso_prima"], canonico, indent=2, fsync=True)

            archivio.mkdir(parents=True, exist_ok=True)
            safe_write_json(
                archivio / prop["percorso_seconda"].name,
                {
                    **fusa,
                    "status": "promossa",
                    "merged_into": prop["prima_classe"],
                    "merged_date": adesso,
                    "merged_by": "entity_dedup_index --promuovi",
                },
                indent=2,
            )
            prop["percorso_seconda"].unlink(missing_ok=True)

        if j.percorso:
            log.info("merge journal: %s", j.percorso)
            log.info(
                "to roll back: xs-l4-disfa-fusione.py --journal %s --apply",
                j.percorso.name,
            )

    for prop in proposte:
        prop.pop("percorso_prima", None)
        prop.pop("percorso_seconda", None)
    return proposte


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dedup index + second-class promotion (dry-run by default)"
    )
    ap.add_argument(
        "--promuovi",
        action="store_true",
        help="promotes second classes with matching LinkedIn slug AND name",
    )
    ap.add_argument("--apply", action="store_true", help="actually runs (default: dry-run)")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not a.promuovi:
        ap.print_help()
        return 0

    fatte = promuovi(applica=a.apply)
    if not fatte:
        print(
            "no promotion: no second class with a PROVEN target "
            "(criterion: LinkedIn slug AND name, unique target)"
        )
        return 0

    print(f"{'PROMOTED' if a.apply else 'TO PROMOTE (dry-run)'}: {len(fatte)}")
    for p in fatte:
        print(
            f"  {p['seconda_classe']}  «{p['nome'][:44]}»  attio:{(p['attio_record_id'] or '?')[:8]}"
            f"  →  {p['prima_classe']}   [{p['slug']}]  +{p.get('fatti_guadagnati', 0)} facts"
        )
    if not a.apply:
        print("\nto run: --promuovi --apply   (writes the journal, reversible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
