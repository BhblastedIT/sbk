#!/usr/bin/env python3
""


























from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("confronta")

NLP = cfg.DATA_ROOT / "l3" / "nlp"
IN_USO = NLP / "relationship-facts.parquet"
RIGENERATO = NLP / "relationship-facts-rigenerato.parquet"


def _pieni(df) -> int:
    return int(
        (
            (df.get("predicate", "").fillna("").astype(str).str.strip() != "")
            & (df.get("object", "").fillna("").astype(str).str.strip() != "")
        ).sum()
    )


def confronta(a: Path = IN_USO, b: Path = RIGENERATO) -> dict:
    import pandas as pd

    if not a.exists() or not b.exists():
        log.error("missing files: %s %s", a.exists(), b.exists())
        return {}
    vecchio = pd.read_parquet(a)
    nuovo = pd.read_parquet(b)

    log.info("in use      %8s rows · %s columns", f"{len(vecchio):,}", len(vecchio.columns))
    log.info("regenerated %8s rows · %s columns", f"{len(nuovo):,}", len(nuovo.columns))
    log.info("columns recovered: %s", sorted(set(nuovo.columns) - set(vecchio.columns)))
    log.info(
        "columns lost:      %s", sorted(set(vecchio.columns) - set(nuovo.columns)) or "none"
    )














    identita = ["source_id", "predicate", "object"]
    kv = set(map(tuple, vecchio[identita].fillna("").astype(str).values))
    kn = set(map(tuple, nuovo[identita].fillna("").astype(str).values))
    solo_vecchio = kv - kn
    solo_nuovo = kn - kv




    def _soggetti_per_identita(df):
        d = {}
        for k, s in zip(
            map(tuple, df[identita].fillna("").astype(str).values),
            df.get("subject", "").fillna("").astype(str),
            strict=False,
        ):
            d.setdefault(k, set()).add(s)
        return d

    sv, sn = _soggetti_per_identita(vecchio), _soggetti_per_identita(nuovo)
    curati = sum(1 for k in kv & kn if sv.get(k) != sn.get(k))
    log.info(
        "facts present in both with the SUBJECT changed: %s "
        "(not losses: the fix that bit)",
        f"{curati:,}",
    )

    esito = {
        "righe_in_uso": len(vecchio),
        "righe_rigenerato": len(nuovo),
        "pieni_in_uso": _pieni(vecchio),
        "pieni_rigenerato": _pieni(nuovo),
        "solo_nel_vecchio": len(solo_vecchio),
        "solo_nel_nuovo": len(solo_nuovo),
        "in_comune": len(kv & kn),
        "soggetto_curato": curati,
    }
    if "subject_person_id" in nuovo.columns:
        esito["archi_nel_nuovo"] = int(
            (
                (nuovo["subject_person_id"].fillna("") != "")
                & (nuovo["object_person_id"].fillna("") != "")
            ).sum()
        )




    vuote = vecchio[
        (vecchio.get("predicate", "").fillna("").astype(str).str.strip() == "")
        & (vecchio.get("object", "").fillna("").astype(str).str.strip() == "")
    ]
    esito["perse_ma_erano_vuote"] = len(vuote)



    con_contenuto = vecchio[~vecchio.index.isin(vuote.index)]
    manca = ~con_contenuto[identita].fillna("").astype(str).apply(tuple, axis=1).isin(kn)
    esito["perse_con_contenuto"] = int(manca.sum())



    mancanti = con_contenuto[manca]
    if len(mancanti):
        meta = (
            (mancanti.get("predicate", "").fillna("").astype(str).str.strip() == "")
            | (mancanti.get("object", "").fillna("").astype(str).str.strip() == "")
        ).sum()
        esito["di cui monche (una colonna sola)"] = int(meta)
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare the in-use parquet with the regenerated one")
    ap.add_argument("--a", type=Path, default=IN_USO)
    ap.add_argument("--b", type=Path, default=RIGENERATO)
    a = ap.parse_args()
    esito = confronta(a.a, a.b)
    log.info("")
    for k, v in esito.items():
        log.info("  %-24s %s", k, f"{v:,}" if isinstance(v, int) else v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
