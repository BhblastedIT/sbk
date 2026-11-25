#!/usr/bin/env python3
""


















































from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

VOCABOLARIO = cfg.DATA_ROOT / "knowledge" / "meta" / "vocabolario-sigle.json"
ORG = cfg.DATA_ROOT / "knowledge" / "entities"
ATTIO = cfg.DATA_ROOT / "attio" / "companies.parquet"



SOGLIA_PROVA = 0.40



MINIMO_OCCORRENZE = 5


def _tok(s: object) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s).replace(".", "")
    return re.sub(r"[^a-z0-9 ]", " ", s).split()


def _nomi() -> list[list[str]]:
    ""
    out: list[list[str]] = []
    for cartella in ("organization", "org"):
        d = ORG / cartella
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            t = _tok(e.get("canonical_name"))
            if t:
                out.append(t)
    if ATTIO.exists():
        try:
            import duckdb

            con = duckdb.connect()
            con.execute("SET memory_limit='2GB'")
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{ATTIO}'").fetchall()]  # noqa: S608
            nc = next((c for c in cols if "name" in c.lower()), None)
            if nc:
                for (n,) in con.execute(f"SELECT \"{nc}\" FROM '{ATTIO}'").fetchall():  # noqa: S608
                    t = _tok(n)
                    if t:
                        out.append(t)
            con.close()
        except Exception:  # pragma: no cover
            pass
    return out


def impara() -> dict:
    ""
    nomi = _nomi()
    esistenti = {" ".join(t) for t in nomi}
    prove: collections.Counter = collections.Counter()
    totali: collections.Counter = collections.Counter()
    for t in nomi:
        if len(t) < 2:
            continue
        coda, base = t[-1], " ".join(t[:-1])
        totali[coda] += 1
        if base in esistenti:
            prove[coda] += 1

        if len(t) >= 3:
            coppia, base2 = " ".join(t[-2:]), " ".join(t[:-2])
            totali[coppia] += 1
            if base2 in esistenti:
                prove[coppia] += 1

    imparate = {}
    for parola, n in totali.items():
        if n < MINIMO_OCCORRENZE or len(parola) > 20:
            continue
        rapporto = prove[parola] / n
        if rapporto >= SOGLIA_PROVA:
            imparate[parola] = {"conferme": prove[parola], "su": n, "rapporto": round(rapporto, 2)}
    return {
        "imparate": imparate,
        "nomi_esaminati": len(nomi),
        "soglia": SOGLIA_PROVA,
        "minimo": MINIMO_OCCORRENZE,
    }


def _precedente() -> dict:
    if not VOCABOLARIO.exists():
        return {}
    try:
        return json.loads(VOCABOLARIO.read_text(encoding="utf-8")).get("imparate", {})
    except (json.JSONDecodeError, OSError):  # pragma: no cover
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Learn company abbreviations from the data")
    ap.add_argument("--scrivi", action="store_true", help="update the vocabulary on disk")
    ap.add_argument("--quando", default="", help="label for the run (e.g. the date)")
    a = ap.parse_args()

    r = impara()
    prima = _precedente()
    nuove = sorted(set(r["imparate"]) - set(prima))
    cadute = sorted(set(prima) - set(r["imparate"]))

    print(f"\norganization names examined: {r['nomi_esaminati']}")
    print(
        f"abbreviations learned: {len(r['imparate'])}  (threshold {SOGLIA_PROVA}, minimum {MINIMO_OCCORRENZE} occurrences)\n"
    )
    for p, d in sorted(r["imparate"].items(), key=lambda x: -x[1]["rapporto"]):
        print(f"   {p:18} {d['conferme']:4}/{d['su']:<4} ({d['rapporto']:.0%})")


    cablate = {x.replace(".", "").replace(" ", "") for x in cfg.COMPANY_SUFFIXES}
    solo_imparate = sorted(p for p in r["imparate"] if p.replace(" ", "") not in cablate)
    solo_cablate = sorted(
        x for x in cablate if x not in {p.replace(" ", "") for p in r["imparate"]}
    )
    print(f"\n   learned and NOT in the hardcoded set: {solo_imparate or '—'}")
    print(
        f"   in the hardcoded set but not learned (insufficient data): {len(solo_cablate)} "
        f"— {solo_cablate[:8]}"
    )

    if nuove or cadute:
        print(
            f"\n   ── changed from the previous run: +{len(nuove)} {nuove[:6]}  −{len(cadute)} {cadute[:6]}"
        )
    elif prima:
        print("\n   ── no change from the previous run")

    if a.scrivi:
        VOCABOLARIO.parent.mkdir(parents=True, exist_ok=True)
        VOCABOLARIO.write_text(
            json.dumps(
                {**r, "quando": a.quando or "no date", "nuove": nuove, "cadute": cadute},
                ensure_ascii=False,
                indent=1,
            )
        )
        print(f"\n   wrote {VOCABOLARIO}")
    else:
        print("\n  dry run: the vocabulary on disk was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
