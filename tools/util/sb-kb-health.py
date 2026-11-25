#!/usr/bin/env python3
"""How far the knowledge layer can be trusted, measured on a sample of entities (or all of them with --full)."""






















































from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))

import sbk_config as cfg  # noqa: E402

KB = cfg.DATA_ROOT / "knowledge"
ENTITIES = KB / "entities"




SEME = 11



CAMPIONE = 2000



STORICO = KB / "meta" / "health-history.jsonl"


def _budget_ok(quante: int) -> tuple[bool, str]:
    ""
    try:
        from sbk_resources import budget
    except ImportError:
        return True, "sbk_resources not importable: proceeding with a reduced sample"
    try:
        b = budget()
        quota = b.job_bytes()



        if quota < 64 * 1024 * 1024:
            return False, f"job quota {quota / 1024**2:.0f} MB: too little even to read"
        return True, f"job quota {quota / 1024**3:.1f} GB"
    except Exception as exc:  # noqa: BLE001 — a meter does not die with what it measures
        return True, f"budget not queryable ({exc}): proceeding with a sample"


def _is_group_name(name: str) -> bool:
    ""







    import importlib.util

    p = PROJECT / "tools" / "cross-source" / "xs-l3-knows-query.py"
    if not p.exists():
        return False
    spec = importlib.util.spec_from_file_location("xs_l3_knows_query", p)
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return bool(mod._is_group_name(name))


def _gruppo_riconoscitore():
    ""
    try:
        import importlib.util

        p = PROJECT / "tools" / "cross-source" / "xs-l3-knows-query.py"
        spec = importlib.util.spec_from_file_location("xs_l3_knows_query", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._is_group_name, f"from {p.relative_to(PROJECT)}:142"
    except Exception as exc:  # noqa: BLE001
        return None, f"NOT available ({exc}): the group-record % is not measured"


def _chiuso(fatto: dict) -> bool:
    ""





    return bool(fatto.get("valid_to") or fatto.get("expired_at") or fatto.get("superseded_by"))


def _misura(camp_max: int, seme: int, tutto: bool) -> dict:
    out: dict = {
        "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tipi": {},
        "canali": {},
        "freschezza": {},
        "gruppi": {},
        "org": {},
        "code": {},
        "note": [],
    }


    for d in sorted(ENTITIES.iterdir()) if ENTITIES.exists() else []:
        if not d.is_dir():
            continue
        nomi = os.listdir(d)
        out["tipi"][d.name] = {
            "file": len(nomi),
            "prefissi": {
                p: sum(1 for n in nomi if n.startswith(p + "_"))
                for p in ("person", "org", "organization", "deal", "commitment")
                if any(n.startswith(p + "_") for n in nomi)
            },
        }


    o1 = out["tipi"].get("org", {}).get("file", 0)
    o2 = out["tipi"].get("organization", {}).get("file", 0)
    fuori_posto = out["tipi"].get("organization", {}).get("prefissi", {}).get("person", 0)
    out["org"] = {
        "in_org": o1,
        "in_organization": o2,
        "person_fuori_posto": fuori_posto,
        "split_brain": o1 > 0 and o2 > 0,
    }
    if out["org"]["split_brain"]:
        vis = 100 * o1 / max(o1 + o2, 1)
        out["note"].append(
            f"split-brain org: whoever follows CLAUDE.md sees {o1} organizations out of {o1 + o2} "
            f"({vis:.1f}%); {fuori_posto} person_* are stored in organization/"
        )







    for nome in ("review-queue", "conflicts", "reclassification"):
        d = KB / nome
        if not d.is_dir():
            out["code"][nome] = None
            continue
        voci = 0
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            try:
                if f.suffix == ".jsonl":
                    with f.open() as fh:
                        voci += sum(1 for r in fh if r.strip())
                elif f.suffix == ".json":
                    j = json.loads(f.read_text())
                    voci += (
                        len(j)
                        if isinstance(j, list)
                        else len(j.get("conflicts") or j.get("items") or j)
                    )
                else:
                    voci += 1
            except Exception:  # noqa: BLE001 — a broken file counts as one
                voci += 1
        out["code"][nome] = voci


    pdir = ENTITIES / "person"
    if not pdir.is_dir():
        out["note"].append("entities/person absent: nothing to sample")
        return out

    nomi = os.listdir(pdir)
    if tutto:
        camp = nomi
    else:
        rnd = random.Random(seme)
        camp = rnd.sample(nomi, min(camp_max, len(nomi)))

    is_group, nota_group = _gruppo_riconoscitore()
    if is_group is None:
        out["note"].append(nota_group)

    canali: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    fresco: dict[str, str] = {}
    n_ent = 0
    n_gruppi = 0
    n_fatti = 0
    fatti_in_gruppi = 0

    for n in camp:
        try:
            d = json.loads((pdir / n).read_text())
        except Exception:  # noqa: BLE001 — a broken file is counted, it does not stop the measurement
            out["note"].append(f"unreadable entity: {n}")
            continue
        n_ent += 1
        nome = d.get("canonical_name") or ""
        e_gruppo = bool(is_group and is_group(nome))
        if e_gruppo:
            n_gruppi += 1

        for fa in d.get("facts") or []:
            if not isinstance(fa, dict):
                continue
            n_fatti += 1
            if e_gruppo:
                fatti_in_gruppi += 1
            src = (fa.get("source") or {}).get("source_type") or "?"
            canali[src][0] += 1
            if _chiuso(fa):
                canali[src][1] += 1


            q = fa.get("created_at") or ""
            if q and (src not in fresco or q > fresco[src]):
                fresco[src] = q

    out["canali"] = {
        k: {"fatti": v[0], "chiusi": v[1], "quota_chiusi": round(v[1] / v[0], 4) if v[0] else None}
        for k, v in sorted(canali.items(), key=lambda x: -x[1][0])
    }
    oggi = date.today()
    out["freschezza"] = {
        k: {
            "ultimo_fatto": v[:10],
            "giorni": (oggi - date.fromisoformat(v[:10])).days if len(v) >= 10 else None,
        }
        for k, v in sorted(fresco.items(), key=lambda x: x[1], reverse=True)
    }
    out["gruppi"] = {
        "entita_campione": n_ent,
        "record_gruppo": n_gruppi,
        "quota": round(n_gruppi / n_ent, 4) if n_ent else None,
        "fatti_campione": n_fatti,
        "fatti_su_gruppi": fatti_in_gruppi,
        "quota_fatti_su_gruppi": round(fatti_in_gruppi / n_fatti, 4) if n_fatti else None,
        "riconoscitore": nota_group,
    }
    out["campione"] = {"entita": n_ent, "su": len(nomi), "seme": None if tutto else seme}
    return out


def _stampa(m: dict) -> None:
    print("── KB health ──────────────────────────────────────────────────────")
    c = m.get("campione") or {}
    if c:
        s = (
            "ALL"
            if c.get("seme") is None
            else f"sample {c['entita']}/{c['su']} (seed {c['seme']})"
        )
        print(f"  measured on {s}")
    print()

    print("  THE SHAPE")
    for t, d in m["tipi"].items():
        print(f"    {t:16} {d['file']:6} files")
    o = m["org"]
    if o.get("split_brain"):
        print(
            f"    ⚠️  org visible following CLAUDE.md: {o['in_org']} out of "
            f"{o['in_org'] + o['in_organization']} · {o['person_fuori_posto']} person_* "
            f"stored in organization/"
        )
    print()

    print("  FACT CLOSURE, BY CHANNEL  (open ≠ still true)")
    vivi = [(k, v) for k, v in m["canali"].items() if v["fatti"] >= 10]
    for k, v in vivi[:14]:
        q = v["quota_chiusi"]
        segno = "✅" if q and q > 0.2 else ("🟡" if q else "🔴")
        print(f"    {segno} {k:24} {v['fatti']:7} facts  {v['chiusi']:6} closed  {(q or 0):6.1%}")
    zero = [k for k, v in vivi if not v["chiusi"]]
    if zero:
        print(f"    → {len(zero)} channels out of {len(vivi)} have not closed a SINGLE fact")
    print()

    g = m["gruppi"]
    if g.get("quota") is not None:
        print("  GROUP-RECORD  (a name with several people inside: facts go to a ghost)")
        print(f"    entities: {g['record_gruppo']}/{g['entita_campione']} = {g['quota']:.1%}")
        print(
            f"    facts attached to a group: {g['fatti_su_gruppi']}/{g['fatti_campione']} = "
            f"{g['quota_fatti_su_gruppi']:.1%}"
        )
        print()

    print("  DATA FRESHNESS  (date of the last FACT, not of the rewrite)")
    for k, v in list(m["freschezza"].items())[:12]:
        gg = v["giorni"]
        segno = (
            "✅" if gg is not None and gg <= 3 else ("🟡" if gg is not None and gg <= 14 else "🔴")
        )
        print(f"    {segno} {k:24} {v['ultimo_fatto']}  ({gg} days ago)")
    print()

    print("  QUEUES  (a queue that grows and nobody empties is a postponed decision)")
    for k, v in m["code"].items():
        print(f"    {k:20} {'absent' if v is None else f'{v} entries'}")

    if m["note"]:
        print()
        print("  NOTES")
        for n in m["note"][:8]:
            print(f"    · {n}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="all entities, not a sample")
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--salva", action="store_true", help="appends the measurement to the history")
    ap.add_argument("--seme", type=int, default=SEME)
    ap.add_argument("--campione", type=int, default=CAMPIONE)
    a = ap.parse_args()

    if not KB.is_dir():
        print(f"knowledge store absent: {KB}", file=sys.stderr)
        return 2

    ok, nota = _budget_ok(a.campione)
    if not ok:
        print(f"⛔ not measuring now: {nota}", file=sys.stderr)
        print(
            "   (the budget is shared between sessions and jobs: retry when there is quota)",
            file=sys.stderr,
        )
        return 75

    m = _misura(a.campione, a.seme, a.full)
    m["budget"] = nota

    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        _stampa(m)

    if a.salva:
        STORICO.parent.mkdir(parents=True, exist_ok=True)
        with STORICO.open("a") as f:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
        print(f"\n  measurement appended to {STORICO.relative_to(Path.home())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
