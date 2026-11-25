#!/usr/bin/env python3
""





















from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from entity_dedup_index import normalize_name  # noqa: E402
from knowledge_schema import (  # noqa: E402
    attio_record_id_di,
    e_seconda_classe,
    generate_entity_id,
)

from sbk_config import (  # noqa: E402
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_FACTS_DIR,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from confrontabile import ENV_BLOCCA, blocca_attivo, giudica  # noqa: E402
from freno_massa import verifica_quota  # noqa: E402
from journal_fusioni import Journal  # noqa: E402

log = logging.getLogger("sbk-l4-03-exact-dedup")

PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
FACTS_PERSON_DIR = KNOWLEDGE_FACTS_DIR / "person"
ARCHIVE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "deduped"
RUN_LOG = QUALITY_METRICS_DIR / "l4-03-run-log.jsonl"







_ATTR_CHIAVE = ("contact.email", "identity.email", "contact.email_work", "contact.email_personal")
_ATTR_ATTIO = ("crm.attio_record_id", "source.attio_record_id")


_MARCATORI = ("identity.classe", "identity.riscontro")


def _token_nome(nome: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", normalize_name(nome)) if len(t) >= 3}


def _email_coerente(email: str, nome: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return any(t in local for t in _token_nome(nome))


def chiavi_di(fatti: list[dict], nome: str) -> tuple[set[str], set[str]]:
    ""
    coerenti: set[str] = set()
    tutte: set[str] = set()
    for f in fatti:
        attr = f.get("attribute", "")
        val = str(f.get("value", "")).strip().lower()
        if not val:
            continue
        if attr in _ATTR_ATTIO:
            coerenti.add(val)
            tutte.add(val)
        elif attr in _ATTR_CHIAVE and "@" in val:
            tutte.add(val)
            if _email_coerente(val, nome):
                coerenti.add(val)
    return coerenti, tutte









SKIP_NAMES = {
    "client",
    "team",
    "disclosers",
    "unknown",
    "user",
    "admin",
    "system",
    "bot",
    "automated",
    "notification",
    "support",
}


def scan_exact_duplicates() -> tuple[dict[str, list[dict]], list[dict], int]:
    ""




















    name_groups: dict[str, list[dict]] = defaultdict(list)
    seconde: list[dict] = []
    popolazione = 0

    for f in sorted(PERSON_DIR.iterdir()):
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            popolazione += 1
            fatti = data.get("facts", [])
            if e_seconda_classe(fatti):
                seconde.append(
                    {
                        "entity_id": data.get("entity_id", ""),
                        "canonical_name": data.get("canonical_name", ""),
                        "attio_record_id": attio_record_id_di(fatti),
                        "fact_count": len(fatti),
                    }
                )
                continue
            name = normalize_name(data.get("canonical_name", ""))
            if not name or name in SKIP_NAMES:
                continue

            if any(w in name for w in ("srl", "spa", "ltd", "llc", "gmbh", "team", "group")):
                continue
            canonical_name = data.get("canonical_name", "")
            entity_id = data.get("entity_id", "")
            coerenti, tutte = chiavi_di(fatti, canonical_name)
            name_groups[name].append(
                {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "fact_count": len(fatti),
                    "high_conf_facts": sum(1 for ff in fatti if ff.get("confidence", 0) >= 0.7),
                    "file_path": str(f),
                    "chiavi": coerenti,
                    "chiavi_tutte": tutte,


                    "id_del_nome": entity_id == generate_entity_id("person", canonical_name),
                    "created_at": str(data.get("created_at", "")),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    return {n: es for n, es in name_groups.items() if len(es) > 1}, seconde, popolazione


def censisci_non_confrontabili(groups: dict[str, list[dict]]) -> tuple[dict, dict, list[str]]:
    ""















    per_gruppo: dict[str, list[str]] = {}
    per_codice: dict[str, int] = {}
    righe: list[str] = []
    for chiave, entita in sorted(groups.items()):
        ragioni: list[str] = []
        codici: set[str] = set()
        for e in entita:
            g = giudica(e.get("canonical_name", ""), "person", entity_id=e.get("entity_id", ""))
            if not g.ok:
                for r, c in zip(g.ragioni, g.codici):
                    if c not in codici:
                        codici.add(c)
                        ragioni.append(r)
        if not ragioni:
            continue
        per_gruppo[chiave] = ragioni
        for c in codici:
            per_codice[c] = per_codice.get(c, 0) + 1
        righe.append(
            f"  · «{entita[0].get('canonical_name', '')[:44]}» "
            f"[{len(entita)} entita', {sum(e.get('fact_count', 0) for e in entita)} fatti]  "
            + " · ".join(ragioni)
        )
    return per_gruppo, per_codice, righe


def scegli_canonico(entities: list[dict]) -> dict:
    ""






    return max(
        entities,
        key=lambda e: (
            bool(e.get("chiavi")),
            bool(e.get("id_del_nome")),
            e["high_conf_facts"],
            e["fact_count"],
            e["entity_id"],
        ),
    )


def chiavi_disgiunte(entities: list[dict]) -> bool:
    ""
    con = [e["chiavi"] for e in entities if e.get("chiavi")]
    if len(con) < 2:
        return False

    for i, c in enumerate(con):
        altri = set().union(*(x for j, x in enumerate(con) if j != i))
        if not (c & altri):
            return True
    return False


def merge_group(name: str, entities: list[dict], dry_run: bool = True, journal=None) -> dict | None:
    ""
    if chiavi_disgiunte(entities):
        return {
            "name": name,
            "saltato": "chiavi_disgiunte",
            "entity_ids": [e["entity_id"] for e in entities],
        }
    canonical = scegli_canonico(entities)
    non_canonical = [e for e in entities if e["entity_id"] != canonical["entity_id"]]
    if not non_canonical:
        return None

    canonical_path = Path(canonical["file_path"])
    if not canonical_path.exists():
        return None

    canonical_data = json.loads(canonical_path.read_text(encoding="utf-8"))
    original_facts = len(canonical_data.get("facts", []))


    existing_keys = {
        (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
        for f in canonical_data.get("facts", [])
    }

    facts_gained = 0
    merged_ids = []

    for nc in non_canonical:
        nc_path = Path(nc["file_path"])
        if not nc_path.exists():
            continue

        nc_data = json.loads(nc_path.read_text(encoding="utf-8"))



        if journal is not None:
            journal.fusione(
                canonical["entity_id"],
                nc["entity_id"],
                motivo=f"same normalized name: {name}",
                punteggi={
                    "canonico_fatti": canonical.get("fact_count"),
                    "fuso_fatti": nc.get("fact_count"),
                },
            )


        for fact in nc_data.get("facts", []):
            if fact.get("attribute", "") in _MARCATORI:

                if journal is not None:
                    journal.fatto_scartato(fact, da=nc["entity_id"], perche="marker of the merged entity")
                continue
            key = (fact.get("attribute", ""), str(fact.get("value", "")).strip().lower())
            if key not in existing_keys:



                merged_fact = {
                    **fact,
                    "entity_id": canonical["entity_id"],
                    "source_entity_id": fact.get("entity_id"),
                }
                canonical_data["facts"].append(merged_fact)
                existing_keys.add(key)
                facts_gained += 1
                if journal is not None:
                    journal.fatto(fact, da=nc["entity_id"], a=canonical["entity_id"])
            elif journal is not None:



                journal.fatto_scartato(
                    fact, da=nc["entity_id"], perche="duplicate (attribute,value)"
                )



        merged_ids.append(nc["entity_id"])

        if not dry_run:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            archive_data = {
                **nc_data,
                "status": "deduped",
                "merged_into": canonical["entity_id"],
                "merged_date": datetime.now(UTC).isoformat(),
                "merged_by": "l4-03-exact-dedup",
            }


            lapide = ARCHIVE_DIR / nc_path.name
            if lapide.exists():
                lapide = (
                    ARCHIVE_DIR
                    / f"{nc_path.stem}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
                )
            safe_write_json(lapide, archive_data)
            jl = FACTS_PERSON_DIR / f"{nc['entity_id']}.jsonl"
            if jl.exists():
                shutil.move(str(jl), str(ARCHIVE_DIR / jl.name))
            nc_path.unlink(missing_ok=True)

    if not dry_run:
        safe_write_json(canonical_path, canonical_data, backup=True)

    return {
        "name": name,
        "canonical_id": canonical["entity_id"],
        "merged_ids": merged_ids,
        "facts_before": original_facts,
        "facts_after": len(canonical_data.get("facts", [])),
        "facts_gained": facts_gained,
    }


def main():
    parser = argparse.ArgumentParser(description="L4-03: Exact Name Deduplication")
    parser.add_argument("--apply", action="store_true", help="Execute (default: dry-run)")
    parser.add_argument(
        "--nomi",
        help="JSON file with the list of normalized names to merge (scope); without it, all",
    )
    parser.add_argument(
        "--min-token",
        type=int,
        default=2,
        help="names with fewer tokens are left out (default 2: single names («Marco») "
        "are often different people under the same name)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    dry_run = not args.apply
    log.info("=" * 60)
    log.info("L4-03 Exact Name Dedup — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)

    log.info("Scanning for exact-name duplicates...")
    groups, seconde, popolazione = scan_exact_duplicates()
    total_entities = sum(len(es) for es in groups.values())
    log.info(
        "Found %d duplicate groups with %d entities (population %d)",
        len(groups),
        total_entities,
        popolazione,
    )
    if args.nomi:
        voluti = {normalize_name(n) for n in json.loads(Path(args.nomi).read_text())}
        groups = {k: v for k, v in groups.items() if k in voluti}
        log.info("Scope --nomi: %d groups out of %d requested", len(groups), len(voluti))
    mononimi = {k for k in groups if len(k.split()) < args.min_token}
    if mononimi:
        log.info(
            "Single names OUT (min-token %d): %d groups — %s",
            args.min_token,
            len(mononimi),
            ", ".join(sorted(mononimi)[:12]) + (" …" if len(mononimi) > 12 else ""),
        )
        groups = {k: v for k, v in groups.items() if k not in mononimi}



    if seconde:
        log.info(
            "Second class: %d entities present and NOT mergeable "
            "(id derived from attio_record_id)",
            len(seconde),
        )
        for e in sorted(seconde, key=lambda x: -x["fact_count"])[:10]:
            log.info(
                "  · %s  «%s»  attio:%s  [%d facts]",
                e["entity_id"],
                e["canonical_name"][:48],
                (e["attio_record_id"] or "?")[:8],
                e["fact_count"],
            )
        if len(seconde) > 10:
            log.info("  ... and %d more", len(seconde) - 10)
    else:
        log.info("Second class: no entities in the store")






    _unsure, _per_codice, _righe = censisci_non_confrontabili(groups)
    if _unsure:
        _entita_dentro = sum(len(groups[k]) for k in _unsure)
        log.info(
            "Non-comparable name: %d groups out of %d (%d entities) — %s",
            len(_unsure),
            len(groups),
            _entita_dentro,
            "BLOCKED" if blocca_attivo() else "RECORDED, not blocked",
        )
        for codice, quanti in sorted(_per_codice.items(), key=lambda x: -x[1]):
            log.info("    %5d  %s", quanti, codice)
        for riga in _righe[:10]:
            log.info("%s", riga)
        if len(_righe) > 10:
            log.info("  ... and %d more", len(_righe) - 10)
        if blocca_attivo():
            groups = {k: v for k, v in groups.items() if k not in _unsure}
            total_entities = sum(len(es) for es in groups.values())
        else:
            log.info("  to actually block them: %s=1  (now: off)", ENV_BLOCCA)
    else:
        log.info("Non-comparable name: no group")

    results = []
    total_merged = 0
    total_facts_gained = 0






    _da_toccare = sum(len(e) - 1 for e in groups.values())


    verifica_quota(_da_toccare, popolazione or 1, "l4-03 dedup by name")

    saltati_chiavi: list[dict] = []
    with Journal("l4-03-exact-dedup", attivo=not dry_run) as journal:
        for name, entities in sorted(groups.items(), key=lambda x: -len(x[1])):
            result = merge_group(name, entities, dry_run=dry_run, journal=journal)
            if result and result.get("saltato"):
                saltati_chiavi.append(result)
                continue
            if result:
                results.append(result)
                total_merged += len(result["merged_ids"])
                total_facts_gained += result["facts_gained"]
                if len(entities) >= 5:
                    log.info(
                        '%s: "%s" [%d entities] → %s (+%d facts)',
                        "DRY" if dry_run else "MERGED",
                        result["name"],
                        len(entities),
                        result["canonical_id"],
                        result["facts_gained"],
                    )

        if journal.percorso:
            log.info("merge journal: %s", journal.percorso)
            log.info(
                "to roll back: xs-l4-disfa-fusione.py --journal %s --apply",
                journal.percorso.name,
            )

    if results and not dry_run:
        QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            for r in results:
                r["timestamp"] = datetime.now(UTC).isoformat()
                r["module"] = "l4-03-exact-dedup"
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    if saltati_chiavi:
        log.info(
            "  Groups SKIPPED due to disjoint strong keys (review by hand): %d — %s",
            len(saltati_chiavi),
            ", ".join(s["name"] for s in saltati_chiavi[:10]),
        )
    log.info("  Groups processed: %d", len(results))
    log.info("  Entities merged: %d", total_merged)
    log.info("  Facts gained: %d", total_facts_gained)
    if dry_run:
        log.info("  Run with --apply to execute.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
