#!/usr/bin/env python3
"""Table of the Plaud recordings with few voices to recognise: for each, the calendar event it matches and the
candidate names with their provenance; --md writes it as Markdown.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sbk_config as cfg  # noqa: E402

DEEP = cfg.DATA_ROOT / "l3" / "nlp" / "deep-facts.parquet"
PLAUD = cfg.DATA_ROOT / "plaud" / "raw"
CALENDARI = str(cfg.DATA_ROOT / "calendars" / "*" / "events.parquet")
PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"

_PREFISSO = re.compile(r"^\d{4}-\d{2}-\d{2}[_ ]+\d{2}-\d{2}\s*")


_ORARIO = re.compile(r"(\d{4}-\d{2}-\d{2})[ _](\d{2})[_:](\d{2})[_:](\d{2})")


# Event-title words treated as noise; extend or override from user config.
_BLOCCO = re.compile(
    r"^(office|standup|weekly|daily|go to|meet$|email|travel|check-?in)",
    re.I,
)
_RUMORE = re.compile(
    r"^(speaker|team|group|dept|client|customer|company|project|the |a |il |la )", re.I
)


def _con():
    import duckdb

    c = duckdb.connect()
    try:
        from sbk_resources import configure_duckdb

        configure_duckdb(c)
    except Exception:  # pragma: no cover
        c.execute("SET memory_limit='2GB'")
    return c


def _nomi_kb() -> set[str]:
    ""






    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sb_persone", Path(__file__).resolve().parent / "sb-persone.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sb_persone"] = mod
    spec.loader.exec_module(mod)

    out = set()
    for f in PERSON.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = (d.get("canonical_name") or "").strip()
        if not n or len(n.split()) < 2:
            continue
        v = mod.classifica(f.stem, n, d.get("facts") or [])
        if v.categoria in ("PERSONA", "NOME-SPORCO"):
            out.add(n.lower())
    return out


def raccogli(max_voci: int = 2) -> list[dict]:
    c = _con()
    testi = {f.stem: f for f in PLAUD.glob("*.txt")}





    voci_da_fatti: dict[str, set[str]] = collections.defaultdict(set)
    for sid, sub in c.execute(
        f"SELECT source_id, subject FROM '{DEEP}' WHERE subject LIKE 'Speaker %'"  # noqa: S608
    ).fetchall():
        voci_da_fatti[sid].add(sub)

    meta: dict[str, dict] = {}
    for sid, d, t in c.execute(
        f"""SELECT source_id, any_value(source_date), any_value(source_title)
            FROM '{DEEP}' WHERE subject LIKE 'Speaker %' GROUP BY source_id"""  # noqa: S608
    ).fetchall():
        meta[sid] = {
            "quando": str(d)[:10],
            "argomento": _PREFISSO.sub("", str(t or "")).replace("_", " ").strip(),
        }

    temi = collections.defaultdict(collections.Counter)
    for sid, cat in c.execute(f"SELECT source_id, category FROM '{DEEP}'").fetchall():  # noqa: S608
        if sid in meta and cat:
            temi[sid][cat] += 1

    nominati = collections.defaultdict(collections.Counter)
    for col in ("subject", "counterparty"):
        for sid, val in c.execute(
            f"SELECT source_id, {col} FROM '{DEEP}' WHERE {col} IS NOT NULL"  # noqa: S608
        ).fetchall():
            v = str(val).strip()
            if sid in meta and len(v) > 3 and not _RUMORE.match(v) and len(v.split()) <= 4:
                nominati[sid][v] += 1


    cal = collections.defaultdict(list)
    for f in glob.glob(CALENDARI):
        for s, sm, loc, att in c.execute(
            f"""SELECT substr(CAST(start_datetime AS VARCHAR),1,10), summary, location, attendees
                FROM '{f}'"""  # noqa: S608
        ).fetchall():
            if s:
                cal[s].append({"cosa": sm, "dove": loc, "chi": att})

    kb = _nomi_kb()


    per_battesimo: dict[str, set[str]] = collections.defaultdict(set)
    for n in kb:
        per_battesimo[n.split()[0]].add(n)

    righe = []
    for sid, m in meta.items():
        voci = len(voci_da_fatti.get(sid, ()))
        f = testi.get(sid) or next((v for k, v in testi.items() if k[:45] == str(sid)[:45]), None)
        etichettato = False
        if f:
            try:
                etichettato = bool(
                    re.search(r"\[Speaker \d+\]", f.read_text(encoding="utf-8", errors="replace"))
                )
            except OSError:  # pragma: no cover
                pass
        if max_voci and voci > max_voci:
            continue



        chiamati: list[str] = []
        if f:
            try:
                testo = f.read_text(encoding="utf-8", errors="replace")
                conteggio = collections.Counter(
                    w.lower() for w in re.findall(r"\b([A-ZÀ-Ü][a-zà-ÿ]{2,12})\b", testo)
                )
                chiamati = [
                    f"{w} ×{c}" for w, c in conteggio.most_common() if w in per_battesimo and c >= 2
                ][:4]
            except OSError:  # pragma: no cover
                pass
        persone = [n for n, _ in nominati[sid].most_common(6)]

        candidati = [p for p in persone if p.lower() in kb]
        righe.append(
            {
                **m,
                "registrazione": sid,
                "voci": voci,
                "rileggibile": etichettato,
                "temi": [t for t, _ in temi[sid].most_common(4)],
                "nominati": persone,
                "candidati_kb": candidati[:3],
                "chiamati": chiamati,
            }
        )
    righe.sort(key=lambda r: (r["voci"], r["quando"]))
    return righe


def calendario_provato(
    inizio, durata_s: int, testo: str, eventi: list[dict], noti: set[str]
) -> list[str]:
    ""










    from datetime import timedelta

    fine = inizio + timedelta(seconds=durata_s or 0)
    out = []
    for e in eventi:
        if not (e["a"] < fine and e["b"] > inizio):
            continue
        if (e["b"] - e["a"]).total_seconds() > 4 * 3600 or _BLOCCO.match(e["sm"].strip()):
            continue
        nomi = [w for w in re.findall(r"\b([A-ZÀ-Ü][a-zà-ÿ]{2,})\b", e["sm"]) if w.lower() in noti]
        detti = [w for w in nomi if re.search(rf"\b{re.escape(w)}\b", testo, re.I)]
        if detti:
            riga = f"{e['sm'][:44]} (in the minutes: {', '.join(sorted(set(detti)))})"
            if riga not in out:
                out.append(riga)
    return out


def markdown(righe: list[dict]) -> str:
    out = [
        "| # | when | voices | minutes | topic | themes | called by name in the minutes | people named | candidate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(righe, 1):
        out.append(
            f"| {i} | {r['quando']} | {r['voci'] or '?'} | "
            f"{'with labels' if r['rileggibile'] else 'continuous flow'} | {r['argomento'][:58]} | "
            f"{', '.join(r['temi']) or '—'} | **{', '.join(r['chiamati']) or '—'}** | "
            f"{', '.join(r['nominati'][:4]) or '—'} | {', '.join(r['candidati_kb']) or '—'} |"
        )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="The table of recordings to recognize")
    ap.add_argument("--voci", type=int, default=2, help="maximum distinct voices (0 = all)")
    ap.add_argument("--md", default="", help="where to write the table in markdown")
    a = ap.parse_args()
    righe = raccogli(a.voci)
    print(f"\n{len(righe)} recordings with at most {a.voci} voices\n")
    print(markdown(righe[:12]))
    print("\n  ⚠️  The candidate is a suggestion with its provenance, not a decision:")
    print(
        "      in a sample recording «Speaker 1» is the logistics guy, not the one recording."
    )
    if a.md:
        Path(a.md).write_text(markdown(righe))
        print(f"\n  full table in {a.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
