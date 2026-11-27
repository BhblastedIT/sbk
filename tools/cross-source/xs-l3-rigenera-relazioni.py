#!/usr/bin/env python3
"""Regenerates the relationship-facts table from the cached model responses, without calling any API, one source or
all; --scrivi writes relationship-facts-rigenerato.parquet next to the one in use.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "cross-source"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("rigenera")

RISPOSTE = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-responses"
DESTINAZIONE = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-facts-rigenerato.parquet"
IN_USO = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"


def _estrattore():
    ""
    perc = Path(__file__).resolve().parent / "xs-l3-extract-relationships.py"
    spec = importlib.util.spec_from_file_location("xs_l3_extract_relationships_regen", perc)
    m = importlib.util.module_from_spec(spec)
    sys.modules["xs_l3_extract_relationships_regen"] = m
    spec.loader.exec_module(m)
    return m


def date_per_sorgente(mod, sorgente: str) -> dict[str, str]:
    ""
    loader = getattr(mod, f"load_{sorgente}_documents", None)
    if loader is None:
        return {}
    try:
        documenti = loader()
    except Exception as e:  # pragma: no cover
        log.warning("  dates not available for %s (%s)", sorgente, e)
        return {}
    fuori = {}
    for d in documenti:
        sid = str(d.get("source_id") or "")
        if sid:
            fuori[sid] = str(d.get("date") or "")
    del documenti
    return fuori


def rigenera(solo: str = "", scrivi: bool = False, unisci: bool = True) -> dict:
    import pandas as pd

    if not RISPOSTE.exists():
        log.error("cache not found: %s", RISPOSTE)
        return {}
    mod = _estrattore()

    sorgenti = sorted(d.name for d in RISPOSTE.iterdir() if d.is_dir())
    if solo:
        sorgenti = [s for s in sorgenti if s == solo]
    righe: list[dict] = []
    conta = collections.Counter()
    senza_data = 0

    for sorgente in sorgenti:
        cartella = RISPOSTE / sorgente
        file_cache = sorted(cartella.glob("*.json"))
        if not file_cache:
            continue
        date = date_per_sorgente(mod, sorgente)
        log.info(
            "%-14s %6s cached responses · %s dates recovered",
            sorgente,
            f"{len(file_cache):,}",
            f"{len(date):,}",
        )
        for f in file_cache:


            if "_chunk_" in f.stem:
                continue
            try:
                parsed = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                conta["unreadable responses"] += 1
                continue
            source_id = f.stem
            data = date.get(source_id, "")
            if not data:
                senza_data += 1
            doc = {"source": sorgente, "source_id": source_id, "date": data}
            try:




                fatti = mod.extract_facts_from_parsed(parsed, doc, None)
            except Exception as e:  # pragma: no cover
                conta["failed conversions"] += 1
                log.debug("  %s/%s: %s", sorgente, source_id, e)
                continue
            righe.extend(fatti)
            conta[f"from {sorgente}"] += len(fatti)
            del parsed
        del date

    if not righe:
        log.error("no fact reconstructed")
        return {"righe": 0}

    df = pd.DataFrame(righe)
    pieni = int(
        (
            (df.get("predicate", "").fillna("").astype(str).str.strip() != "")
            & (df.get("object", "").fillna("").astype(str).str.strip() != "")
        ).sum()
    )
    esito = {
        "rows_reconstructed": len(df),
        "with_predicate_and_object": pieni,
        "pct_full": round(pieni * 100 / max(1, len(df)), 1),
        "unique_fact_id": int(df["fact_id"].nunique()) if "fact_id" in df else 0,
        "without_source_date": senza_data,
        "columns": list(df.columns),
    }
    for k, v in conta.most_common():
        esito[k] = v







    if unisci and IN_USO.exists():
        vecchio = pd.read_parquet(IN_USO)
        pieno = (vecchio.get("predicate", "").fillna("").astype(str).str.strip() != "") & (
            vecchio.get("object", "").fillna("").astype(str).str.strip() != ""
        )
        vecchio = vecchio[pieno]





















        chiave = ["source_id", "predicate", "object"]
        gia = set(map(tuple, df[chiave].fillna("").astype(str).values))
        da_tenere = ~vecchio[chiave].fillna("").astype(str).apply(tuple, axis=1).isin(gia)
        recuperate = vecchio[da_tenere].copy()
        if len(recuperate):


            recuperate["fact_id"] = [
                mod.make_fact_id(str(s), str(su), str(pr), str(o))
                for s, su, pr, o in zip(
                    recuperate["source_id"],
                    recuperate["subject"],
                    recuperate["predicate"],
                    recuperate["object"],
                    strict=False,
                )
            ]






            for c in df.columns:
                if c not in recuperate.columns:
                    recuperate[c] = ""




            recuperate["confidence"] = [
                mod._conf_to_float(x) for x in recuperate.get("confidence", 0.0)
            ]
            df = pd.concat([df, recuperate[df.columns]], ignore_index=True)
        esito["recovered_from_in_use_file"] = int(len(recuperate))
        esito["rows_final"] = len(df)
        log.info(
            "merged %s rows with content the cache did not have (extractions after the cache)",
            f"{len(recuperate):,}",
        )

    if scrivi:





        cfg.safe_write_parquet(df, DESTINAZIONE, index=False)
        log.info("wrote %s", DESTINAZIONE)




        try:
            cfg.scrivi_sidecar_schema(
                DESTINAZIONE,
                _estrattore().SCHEMA_RELATIONSHIP_FACTS,
                righe=int(len(df)),
                riparazione="rigenera-relazioni",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("schema sidecar not written (%s)", e)




        try:
            cfg.registra_riparazione(
                "rigenera-relazioni",
                sintomo={"pct_pieni_rigenerato": esito.get("pct_full")},
                scritto=str(DESTINAZIONE),
                sostituzione="MANUAL: the in-use file was not touched",
                righe=int(len(df)),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("repair registry not updated (%s)", e)
        log.info("the original was NOT touched: compare, then decide the replacement")
    else:
        log.info("(measure only: --scrivi to produce the new file)")
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerates the relationships parquet from the cache")
    ap.add_argument("--sorgente", default="", help="a single source (e.g. plaud)")
    ap.add_argument("--scrivi", action="store_true")
    ap.add_argument(
        "--senza-unione",
        action="store_true",
        help="does not recover the rows of the in-use file (cache only)",
    )
    a = ap.parse_args()
    esito = rigenera(solo=a.sorgente, scrivi=a.scrivi, unisci=not a.senza_unione)
    log.info("")
    for k, v in esito.items():
        log.info("  %-26s %s", k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
