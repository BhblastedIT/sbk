#!/usr/bin/env python3
""


































from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

DEEP = cfg.DATA_ROOT / "l3" / "nlp" / "deep-facts.parquet"
REL = cfg.DATA_ROOT / "l3" / "nlp" / "relationship-facts.parquet"
PLAUD = cfg.DATA_ROOT / "plaud" / "raw"


_PREFISSO = re.compile(r"^\d{4}-\d{2}-\d{2}[_ ]+\d{2}-\d{2}\s*")


def _con():
    import duckdb

    c = duckdb.connect()
    try:
        from sbk_resources import configure_duckdb

        configure_duckdb(c)
    except Exception:  # pragma: no cover
        c.execute("SET memory_limit='2GB'")
    return c


def registrazioni(quale: str = "") -> list[dict]:
    ""
    c = _con()
    filtro = f"AND subject = '{quale}'" if quale else "AND subject LIKE 'Speaker %'"
    righe = c.execute(
        f"""SELECT source_id, any_value(source_date) d, any_value(source_title) t,
                   subject, count(*) n
            FROM '{DEEP}' WHERE subject LIKE 'Speaker %' {filtro}
            GROUP BY source_id, subject ORDER BY n DESC"""  # noqa: S608
    ).fetchall()


    presenti: dict[str, set[str]] = collections.defaultdict(set)
    for sid, sub in c.execute(
        f"""SELECT source_id, subject FROM '{DEEP}'
            WHERE subject NOT LIKE 'Speaker %' AND length(subject) > 3"""  # noqa: S608
    ).fetchall():
        presenti[sid].add(sub)
    for sid, sub in c.execute(
        f"""SELECT source_id, counterparty FROM '{DEEP}'
            WHERE counterparty IS NOT NULL AND length(counterparty) > 3
              AND counterparty NOT LIKE 'Speaker %'"""  # noqa: S608
    ).fetchall():
        presenti[sid].add(sub)

    out = []
    for sid, data, titolo, chi, n in righe:

        detti = (
            c.execute(
                f"""SELECT category, predicate, object FROM '{DEEP}'
                WHERE source_id = ? AND subject = ? AND length(object) > 4 LIMIT 6""",  # noqa: S608
                [sid, chi],
            ).fetchall()
            if sid
            else []
        )
        out.append(
            {
                "registrazione": sid,
                "quando": str(data)[:10],
                "argomento": _PREFISSO.sub("", str(titolo or "")).replace("_", " ").strip(),
                "speaker": chi,
                "fatti": n,
                "altri_presenti": sorted(presenti.get(sid, set()))[:8],
                "ha_detto": [f"{p}: {str(o)[:70]}" for _, p, o in detti],
            }
        )
    return out


def prime_righe(source_id: str, chi: str, quante: int = 3) -> list[str]:
    ""





    if not PLAUD.exists():
        return []
    atteso = str(source_id).strip()
    for f in PLAUD.glob("*.txt"):
        if atteso[:40] in f.name or f.stem[:40] in atteso:
            try:
                testo = f.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover
                return []
            battute = re.findall(rf"\[{re.escape(chi)}\]\s*(.{{20,220}})", testo)
            return [" ".join(b.split()) for b in battute[:quante]]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Who the «Speaker N» were, recording by recording"
    )
    ap.add_argument("--quale", default="", help="Speaker 1 · Speaker 2 · Speaker 3")
    ap.add_argument("--quante", type=int, default=10)
    ap.add_argument("--con-testo", action="store_true", help="also the first lines from the transcript")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    regs = registrazioni(a.quale)
    tot = sum(r["fatti"] for r in regs)
    print(f"\n{len(regs)} recordings with a «Speaker N» · {tot} facts at stake")
    date = [r["quando"] for r in regs if r["quando"]]
    if date:
        print(f"from {min(date)} to {max(date)}\n")

    for r in regs[: a.quante]:
        print(f"── {r['quando']}  ·  {r['speaker']}  ·  {r['fatti']} facts")
        print(f"   topic     : {r['argomento'][:96]}")
        if r["altri_presenti"]:
            print(f"   with      : {', '.join(r['altri_presenti'][:6])}")
        else:
            print("   with      : no other name in the same recording")
        for d in r["ha_detto"][:3]:
            print(f"   said      : {d}")
        if a.con_testo:
            for b in prime_righe(r["registrazione"], r["speaker"]):
                print(f"   speaks    : «{b[:110]}»")
        print()

    print("  ⚠️  No identity is assigned: «Speaker 1» is a RELATIVE label to the single")
    print("      recording, so two «Speaker 1» from two different days are not the same")
    print("      person. And it is not whoever records. Recognition is up to those who were there.")
    if a.json:
        Path(a.json).write_text(json.dumps(regs, ensure_ascii=False, indent=1))
        print(f"\n  dossier saved to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
