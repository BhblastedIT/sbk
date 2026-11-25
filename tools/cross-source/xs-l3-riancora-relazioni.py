#!/usr/bin/env python3
""



























































from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "cross-source"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("riancora")

SORGENTE = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"
DESTINAZIONE = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-facts-riancorato.parquet"



ANCORAGGIO = ("fact_id", "source_date", "subject_person_id", "object_person_id")


def fact_id(source_id: str, subject: str, predicate: str, obj: str) -> str:
    ""






    raw = f"{source_id}|{subject.lower().strip()}|{predicate}|{obj.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]  # noqa: S324















def _indice_esatto() -> dict[str, str]:
    ""
    import unicodedata

    def chiave(n: str) -> str:
        s = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode()
        return " ".join(s.lower().split())

    fuori: dict[str, str] = {}
    ambigui: set[str] = set()
    radice = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
    if not radice.exists():
        return fuori
    import json

    for f in radice.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        eid = d.get("entity_id")
        nomi = {d.get("canonical_name")}
        nomi |= {
            x.get("value")
            for x in d.get("facts") or []
            if (x.get("attribute") or "").startswith(("identity.name", "identity.alias"))
        }
        for n in nomi:
            if not isinstance(n, str) or not n.strip():
                continue
            k = chiave(n)
            if not k or len(k) < 3:
                continue
            if k in fuori and fuori[k] != eid:



                ambigui.add(k)
            else:
                fuori[k] = eid
        del d
    for k in ambigui:
        fuori.pop(k, None)
    log.info(
        "name index: %s unique, %s discarded as namesakes",
        f"{len(fuori):,}",
        f"{len(ambigui):,}",
    )
    return fuori


def riancora(scrivi: bool = False, sorgente: Path | None = None) -> dict:
    import pandas as pd

    origine = sorgente or SORGENTE
    if not origine.exists():
        log.error("cannot find %s", origine)
        return {}
    df = pd.read_parquet(origine)
    log.info("rows: %s   columns present: %s", f"{len(df):,}", list(df.columns))
    manca = [c for c in ANCORAGGIO if c not in df.columns]



















    def _copertura(colonna: str) -> tuple[int, int]:
        if colonna not in df.columns:
            return 0, len(df)
        pieni = int((df[colonna].fillna("").astype(str).str.strip() != "").sum())
        return pieni, len(df)

    prima = {c: _copertura(c) for c in ("subject_person_id", "object_person_id")}
    for c, (pieni, tot) in prima.items():
        log.info(
            "  %s before: %s of %s (%.1f%%)", c, f"{pieni:,}", f"{tot:,}", 100 * pieni / max(tot, 1)
        )
    if manca:
        log.info("missing entirely: %s", manca)










    piena = (df.get("predicate", "").fillna("").astype(str).str.strip() != "") & (
        df.get("object", "").fillna("").astype(str).str.strip() != ""
    )
    gia_ancorato = (
        "fact_id" in df.columns and (df["fact_id"].fillna("").astype(str).str.strip() != "").any()
    )
    df["fact_id"] = (
        df["fact_id"]
        if gia_ancorato
        else [
            fact_id(str(s), str(su), str(p), str(o)) if ok else ""
            for s, su, p, o, ok in zip(
                df.get("source_id", ""),
                df.get("subject", ""),
                df.get("predicate", ""),
                df.get("object", ""),
                piena,
                strict=False,
            )
        ]
    )
    if gia_ancorato:
        log.info("fact_id already present: not recomputing them")
    ancorate = df["fact_id"] != ""
    doppi = int(df.loc[ancorate, "fact_id"].duplicated().sum())
    log.info(
        "anchorable: %s of %s (%.1f%%)   residual collisions: %s",
        f"{int(ancorate.sum()):,}",
        f"{len(df):,}",
        ancorate.sum() * 100 / max(1, len(df)),
        f"{doppi:,}",
    )
    log.info(
        "NOT anchorable: %s — predicate/object emptied by a previous rewrite."
        " For those you must regenerate from the cache (l3/nlp/relationship-responses/,"
        " already-paid responses): the parquet no longer contains them.",
        f"{int((~ancorate).sum()):,}",
    )



    import unicodedata

    def _k(n) -> str:
        s = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode()
        return " ".join(s.lower().split())

    indice = _indice_esatto()
    nomi = {_k(x) for x in df.get("subject", [])} | {_k(x) for x in df.get("object", [])}
    nomi.discard("")
    risolti = {n for n in nomi if n in indice}
    log.info(
        "distinct names: %s   uniquely resolved: %s (%.1f%%)",
        f"{len(nomi):,}",
        f"{len(risolti):,}",
        len(risolti) * 100 / max(1, len(nomi)),
    )
    df["subject_person_id"] = [indice.get(_k(x), "") for x in df.get("subject", "")]
    df["object_person_id"] = [indice.get(_k(x), "") for x in df.get("object", "")]


    if "source_date" not in df.columns:
        df["source_date"] = ""

    archi = int(((df["subject_person_id"] != "") & (df["object_person_id"] != "")).sum())
    log.info("person→person EDGES reconstructed: %s", f"{archi:,}")

    esito = {
        "righe": len(df),
        "ancorabili": int(ancorate.sum()),
        "non_ancorabili": int((~ancorate).sum()),
        "collisioni_residue": doppi,
        "archi": archi,
        "subject_risolti": int((df["subject_person_id"] != "").sum()),
        "object_risolti": int((df["object_person_id"] != "").sum()),


        "source_date_piene": int(
            (df.get("source_date", "").fillna("").astype(str).str.strip() != "").sum()
        ),
    }
    if scrivi:
        df.to_parquet(DESTINAZIONE, index=False)
        log.info("written %s", DESTINAZIONE)
        log.info("the original was NOT touched: compare, then decide on the replacement yourself")
    else:
        log.info("(measure only: --scrivi to produce the new file)")
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(description="Restores the anchoring columns, without API")
    ap.add_argument("--scrivi", action="store_true", help="write the new file (does not overwrite)")
    ap.add_argument("--sorgente", type=Path, default=None, help="parquet to re-anchor")
    a = ap.parse_args()
    esito = riancora(scrivi=a.scrivi, sorgente=a.sorgente)
    for k, v in esito.items():
        log.info("  %-20s %s", k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
