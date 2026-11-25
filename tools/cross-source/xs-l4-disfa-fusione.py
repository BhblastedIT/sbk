#!/usr/bin/env python3
""









































from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("disfa")

STORE = cfg.DATA_ROOT / "knowledge"
ARCHIVI = ("merged", "deduped", "split", "partial-resolved")


def trova_archiviata(eid: str) -> tuple[Path, dict] | None:
    for sub in ARCHIVI:
        p = STORE / "archive" / sub / f"{eid}.json"
        if p.exists():
            try:
                return p, json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # pragma: no cover
                return None
    return None


def _cartella_entita(tipo: str) -> Path:
    return STORE / "entities" / (tipo or "person")


def disfa(eid: str, *, apply: bool = False) -> dict:
    trovata = trova_archiviata(eid)
    if not trovata:
        log.error("%s is not in archive/: it was not merged, or the archive is missing", eid)
        return {"entita": eid, "esito": "non trovata"}
    percorso_arch, dati = trovata
    canonico = dati.get("merged_into") or ""
    tipo = dati.get("entity_type") or "person"
    destinazione = _cartella_entita(tipo) / f"{eid}.json"

    esito = {
        "entita": eid,
        "canonico": canonico,
        "fusa_da": dati.get("merged_by"),
        "quando": dati.get("merged_date"),
        "motivo": dati.get("merge_reason"),
        "fatti_da_ripristinare": len(dati.get("facts") or []),
        "gia_presente": destinazione.exists(),
    }




    da_togliere = 0
    senza_marchio = False
    canonico_path = _cartella_entita(tipo) / f"{canonico}.json"
    if canonico and canonico_path.exists():
        try:
            cdati = json.loads(canonico_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover
            cdati = {}
        fatti = cdati.get("facts") or []
        da_togliere = sum(1 for f in fatti if f.get("source_entity_id") == eid)
        if da_togliere == 0 and fatti:
            senza_marchio = True
    esito["fatti_da_togliere_dal_canonico"] = da_togliere
    esito["senza_source_entity_id"] = senza_marchio

    if not apply:
        log.info("(dry run only: --apply to execute)")
        return esito

    if destinazione.exists():
        log.error("%s already exists in %s: not overwriting it", eid, destinazione.parent)
        esito["esito"] = "già presente, non toccata"
        return esito

    ripulita = {k: v for k, v in dati.items() if k not in ("status", "merged_into", "merged_date")}
    ripulita["disfatta_da"] = "xs-l4-disfa-fusione"
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text(json.dumps(ripulita, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("restored %s (%s facts)", eid, esito["fatti_da_ripristinare"])

    if da_togliere:
        cdati["facts"] = [f for f in cdati.get("facts") or [] if f.get("source_entity_id") != eid]
        canonico_path.write_text(json.dumps(cdati, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("removed %s facts from the canonical %s", da_togliere, canonico)
    elif senza_marchio:
        log.warning(
            "the canonical %s has no facts marked with source_entity_id: merge predating"
            " source_entity_id tracking. PARTIAL restore — the entity returns, its facts also remain on the"
            " canonical (duplicated, not lost).",
            canonico,
        )
    esito["esito"] = "ripristinata"
    return esito


def da_journal(percorso: Path, *, apply: bool = False) -> list[dict]:
    fuori = []
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(riga)
        except ValueError:  # pragma: no cover
            continue
        if r.get("tipo") == "fusione" and r.get("fuso"):
            fuori.append(disfa(r["fuso"], apply=apply))
    return fuori


def main() -> int:
    ap = argparse.ArgumentParser(description="Undo an entity merge")
    ap.add_argument("--entita", help="entity_id to bring back to life")
    ap.add_argument("--journal", help="undo all merges in a journal")
    ap.add_argument("--apply", action="store_true", help="execute (without it, only says what it would do)")
    a = ap.parse_args()

    if a.journal:
        p = Path(a.journal)
        if not p.is_absolute():
            p = STORE / "meta" / a.journal
        esiti = da_journal(p, apply=a.apply)
        log.info("merges in the journal: %s", len(esiti))
    elif a.entita:
        esiti = [disfa(a.entita, apply=a.apply)]
    else:
        ap.error("--entita or --journal required")
        return 2

    for e in esiti[:20]:
        for k, v in e.items():
            log.info("  %-32s %s", k, v)
        log.info("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
