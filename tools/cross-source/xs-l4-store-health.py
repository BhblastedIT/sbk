#!/usr/bin/env python3
"""Read-only health check of the knowledge store: entities and facts by type, empty and partial values, dual-homed
entities, compared with a baseline; --assert-clean exits non-zero on a regression.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from sbk_config import KNOWLEDGE_ENTITIES_DIR
except Exception:  # pragma: no cover - fallback if config not importable
    KNOWLEDGE_ENTITIES_DIR = (
        Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "knowledge"
        / "entities"
    )


from knowledge_schema import (  # noqa: E402
    FORZA_DEBOLE,
    FORZA_FORTE,
    FORZA_NESSUNA,
    identificatori_di,
    solo_il_nome,
)







_E_CASELLA = None
_E_CASELLA_ERRORE = ""


def _carica_e_casella():
    ""






    global _E_CASELLA, _E_CASELLA_ERRORE  # noqa: PLW0603
    if _E_CASELLA is not None or _E_CASELLA_ERRORE:
        return _E_CASELLA
    try:
        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        from confrontabile import _sb_persone

        _E_CASELLA = _sb_persone().e_casella
    except Exception as exc:  # pragma: no cover - depends on disk
        _E_CASELLA_ERRORE = f"{type(exc).__name__}: {exc}"
    return _E_CASELLA




STORE_SUBDIRS = ("person", "organization", "org", "deal", "commitment")
TOP_N = 20


_WORKER_TOP = 64





def norm_value(value: object) -> str:
    ""
    if value is None:
        return ""
    return str(value).strip().lower()





def _blank_partial() -> dict:
    return {
        "n_files": 0,
        "n_facts": 0,
        "n_read_errors": 0,
        "empty_recordid": 0,
        "obs_populated": 0,

        "st_stats": defaultdict(lambda: [0, 0, 0]),

        "dup5_groups": 0,
        "dup5_redundant_rows": 0,

        "group_size_hist": Counter(),

        "redundant_rows": 0,

        "month_stats": defaultdict(lambda: [0, 0]),

        "top_entities": [],

        "ident_livelli": defaultdict(Counter),

        "chiavi_forti": defaultdict(lambda: defaultdict(list)),
        "senza_filtro_casella": 0,
    }


def _tipo_da_percorso(path: str) -> str:
    ""





    return os.path.basename(os.path.dirname(path)) or "person"


def _process_files(paths: list[str]) -> dict:
    p = _blank_partial()
    st_stats = p["st_stats"]
    month_stats = p["month_stats"]
    gsh = p["group_size_hist"]
    livelli = p["ident_livelli"]
    chiavi = p["chiavi_forti"]
    e_casella = _carica_e_casella()
    if e_casella is None:
        p["senza_filtro_casella"] = 1
    top: list[tuple[int, str, str]] = []

    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                entity = json.load(fh)
        except Exception:
            p["n_read_errors"] += 1
            continue

        facts = entity.get("facts") or []
        eid = entity.get("entity_id") or os.path.basename(path)[:-5]
        name = entity.get("canonical_name") or ""

        p["n_files"] += 1
        p["n_facts"] += len(facts)
        top.append((len(facts), eid, name))


        tipo = entity.get("entity_type") or _tipo_da_percorso(path)
        ident = identificatori_di(facts, tipo, escludi=e_casella)
        if ident[FORZA_FORTE]:
            livello = FORZA_FORTE
        elif ident[FORZA_DEBOLE]:
            livello = "solo_nome" if solo_il_nome(facts, tipo) else FORZA_DEBOLE
        else:
            livello = FORZA_NESSUNA
        livelli[tipo][livello] += 1
        if ident["identificatore_di_un_altro"]:
            livelli[tipo]["porta_la_chiave_di_un_altro"] += 1
        for valore in ident[FORZA_FORTE]:
            chiavi[tipo][valore].append(eid)


        five_tuple: Counter = Counter()
        tcount: Counter = Counter()

        for f in facts:
            src = f.get("source") or {}
            rid = src.get("record_id") or ""
            st = src.get("source_type") or "(unknown)"
            attr = f.get("attribute") or ""
            nv = norm_value(f.get("value"))

            row = st_stats[st]
            row[0] += 1


            if rid == "":
                p["empty_recordid"] += 1
                row[1] += 1


            created = f.get("created_at") or ""
            ym = created[:7] if len(created) >= 7 else "(unknown)"
            ms = month_stats[ym]
            ms[0] += 1
            if rid == "":
                ms[1] += 1


            if f.get("observations"):
                p["obs_populated"] += 1


            if rid != "":
                five_tuple[(attr, nv, src.get("source_file") or "", rid)] += 1



            three = (attr, nv)
            if tcount[three]:
                p["redundant_rows"] += 1
                row[2] += 1
            tcount[three] += 1


        for cnt in five_tuple.values():
            if cnt > 1:
                p["dup5_groups"] += 1
                p["dup5_redundant_rows"] += cnt - 1


        for size in tcount.values():
            gsh[size] += 1


    top.sort(reverse=True)
    p["top_entities"] = top[:_WORKER_TOP]


    p["st_stats"] = {k: v for k, v in st_stats.items()}
    p["month_stats"] = {k: v for k, v in month_stats.items()}
    p["group_size_hist"] = dict(gsh)
    p["ident_livelli"] = {k: dict(v) for k, v in livelli.items()}
    p["chiavi_forti"] = {k: dict(v) for k, v in chiavi.items()}
    return p





def _merge(partials: list[dict]) -> dict:
    agg = _blank_partial()
    st_stats = agg["st_stats"]
    month_stats = agg["month_stats"]
    gsh = agg["group_size_hist"]
    all_top: list[tuple[int, str, str]] = []

    livelli = agg["ident_livelli"]
    chiavi = agg["chiavi_forti"]

    for p in partials:
        for k in (
            "n_files",
            "n_facts",
            "n_read_errors",
            "empty_recordid",
            "obs_populated",
            "dup5_groups",
            "dup5_redundant_rows",
            "redundant_rows",
            "senza_filtro_casella",
        ):
            agg[k] += p[k]
        for tipo, cnt in p["ident_livelli"].items():
            livelli[tipo].update(cnt)
        for tipo, mappa in p["chiavi_forti"].items():
            dest = chiavi[tipo]
            for valore, eids in mappa.items():
                dest[valore].extend(eids)
        for st, (t, e, r) in p["st_stats"].items():
            row = st_stats[st]
            row[0] += t
            row[1] += e
            row[2] += r
        for ym, (t, e) in p["month_stats"].items():
            row = month_stats[ym]
            row[0] += t
            row[1] += e
        gsh.update(p["group_size_hist"])
        all_top.extend(p["top_entities"])

    all_top.sort(reverse=True)
    agg["top_entities"] = all_top[:TOP_N]
    agg["st_stats"] = {k: v for k, v in st_stats.items()}
    agg["month_stats"] = {k: v for k, v in month_stats.items()}
    agg["group_size_hist"] = dict(gsh)
    agg["ident_livelli"] = {k: dict(v) for k, v in livelli.items()}
    agg["chiavi_forti"] = {k: dict(v) for k, v in chiavi.items()}
    return agg





def _pct_from_hist(hist: dict[int, int], p: float) -> int:
    total = sum(hist.values())
    if total == 0:
        return 0
    target = p / 100.0 * total
    cum = 0
    for size in sorted(hist):
        cum += hist[size]
        if cum >= target:
            return size
    return max(hist)





def _dual_homed(store: Path) -> tuple[int, list[str]]:
    person = (
        {f.name for f in (store / "person").glob("*.json")}
        if (store / "person").is_dir()
        else set()
    )
    org = (
        {f.name for f in (store / "organization").glob("*.json")}
        if (store / "organization").is_dir()
        else set()
    )
    shared = sorted(person & org)
    return len(shared), shared





def _iter_entity_files(store: Path) -> list[str]:
    files: list[str] = []
    for sub in STORE_SUBDIRS:
        d = store / sub
        if d.is_dir():
            files.extend(str(f) for f in d.glob("*.json"))
    return files





def build_snapshot(store: Path, workers: int) -> dict:
    files = _iter_entity_files(store)
    n_files = len(files)

    if n_files == 0:
        agg = _blank_partial()
        agg["st_stats"] = {}
        agg["month_stats"] = {}
        agg["group_size_hist"] = {}
        agg["top_entities"] = []
        agg["ident_livelli"] = {}
        agg["chiavi_forti"] = {}
    else:

        workers = max(1, min(workers, n_files))
        chunk = max(1, (n_files + workers - 1) // workers)
        blocks = [files[i : i + chunk] for i in range(0, n_files, chunk)]
        if workers == 1 or len(blocks) == 1:
            partials = [_process_files(b) for b in blocks]
        else:
            with Pool(processes=workers) as pool:
                partials = pool.map(_process_files, blocks)
        agg = _merge(partials)

    dual_count, dual_list = _dual_homed(store)

    n_facts = agg["n_facts"]
    empty = agg["empty_recordid"]
    redundant = agg["redundant_rows"]
    gsh = {int(k): v for k, v in agg["group_size_hist"].items()}


    st_report = {}
    for st, (t, e, r) in sorted(agg["st_stats"].items(), key=lambda x: -x[1][0]):
        st_report[st] = {
            "total": t,
            "empty_recordid": e,
            "empty_recordid_pct": round(100.0 * e / t, 2) if t else 0.0,
            "redundant_rows": r,
            "redundant_pct": round(100.0 * r / t, 2) if t else 0.0,
        }


    month_report = {}
    for ym in sorted(agg["month_stats"]):
        t, e = agg["month_stats"][ym]
        month_report[ym] = {
            "total": t,
            "empty_recordid": e,
            "empty_recordid_pct": round(100.0 * e / t, 2) if t else 0.0,
        }


    ident_report = {}
    for tipo, cnt in sorted(agg["ident_livelli"].items()):
        n = sum(v for k, v in cnt.items() if k != "porta_la_chiave_di_un_altro")
        mappa = agg["chiavi_forti"].get(tipo, {})
        condivise = {v: sorted(set(e)) for v, e in mappa.items() if len(set(e)) > 1}
        ident_report[tipo] = {
            "n_entita": n,
            "chiave_forte": cnt.get(FORZA_FORTE, 0),
            "chiave_forte_pct": round(100.0 * cnt.get(FORZA_FORTE, 0) / n, 2) if n else 0.0,
            "debole_un_canale": cnt.get(FORZA_DEBOLE, 0),
            "debole_solo_nome": cnt.get("solo_nome", 0),
            "nessun_identificatore": cnt.get(FORZA_NESSUNA, 0),
            "porta_la_chiave_di_un_altro": cnt.get("porta_la_chiave_di_un_altro", 0),
            "chiavi_distinte": len(mappa),
            "chiavi_condivise": len(condivise),
            "entita_in_chiavi_condivise": len({e for eids in condivise.values() for e in eids}),
            "esempi_condivise": [
                {"chiave": v, "entita": e}
                for v, e in sorted(condivise.items(), key=lambda x: (-len(x[1]), x[0]))[:10]
            ],
        }

    snapshot = {
        "store": str(store),
        "generated_at": _now_iso(),
        "workers": workers,
        "inventory": {
            "n_entities": agg["n_files"],
            "n_facts": n_facts,
            "n_read_errors": agg["n_read_errors"],
            "top_entities_by_facts": [
                {"entity_id": eid, "canonical_name": nm, "n_facts": nf}
                for (nf, eid, nm) in agg["top_entities"]
            ],
        },
        "deanchored": {
            "empty_recordid": empty,
            "empty_recordid_pct": round(100.0 * empty / n_facts, 2) if n_facts else 0.0,
            "by_source_type": st_report,
            "trend_by_month": month_report,
        },
        "dual_homed": {
            "count": dual_count,
            "entities": dual_list,
        },
        "dup_five_tuple": {
            "groups_gt1": agg["dup5_groups"],
            "redundant_rows": agg["dup5_redundant_rows"],
        },
        "redundancy_three_tuple": {
            "redundant_rows": redundant,
            "redundant_pct": round(100.0 * redundant / n_facts, 2) if n_facts else 0.0,
            "by_source_type": {
                st: {"redundant_rows": v["redundant_rows"], "redundant_pct": v["redundant_pct"]}
                for st, v in st_report.items()
            },
        },
        "copies_per_group": {
            "n_groups": sum(gsh.values()),
            "max": max(gsh) if gsh else 0,
            "p50": _pct_from_hist(gsh, 50),
            "p95": _pct_from_hist(gsh, 95),
            "histogram": {str(k): gsh[k] for k in sorted(gsh)},
        },
        "observations": {
            "populated": agg["obs_populated"],
            "populated_pct": round(100.0 * agg["obs_populated"] / n_facts, 2) if n_facts else 0.0,
        },
        "identita": {
            "per_tipo": ident_report,
            "filtro_casella_di_servizio": agg["senza_filtro_casella"] == 0,
            "filtro_casella_errore": _E_CASELLA_ERRORE,
            "riferimento_attio": {
                "persone": 1000,
                "chiave_forte_pct": 70.0,
                "email_o_linkedin_pct": 95.0,
                "fonte": "",
            },
        },
    }
    return snapshot


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()





def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def render_report(s: dict) -> str:
    L = []
    inv = s["inventory"]
    da = s["deanchored"]
    dup = s["dup_five_tuple"]
    red = s["redundancy_three_tuple"]
    cpg = s["copies_per_group"]
    obs = s["observations"]

    L.append("=" * 74)
    L.append("KNOWLEDGE STORE — HEALTH CHECK (read-only)")
    L.append("=" * 74)
    L.append(f"store:        {s['store']}")
    L.append(f"generated:    {s['generated_at']}  (workers={s['workers']})")
    L.append("")
    L.append("INVENTORY")
    L.append(f"  entities:            {_fmt_int(inv['n_entities'])}")
    L.append(f"  total facts:         {_fmt_int(inv['n_facts'])}")
    if inv["n_read_errors"]:
        L.append(f"  unreadable files:    {_fmt_int(inv['n_read_errors'])}")
    L.append("")
    L.append("1) DE-ANCHORED (empty record_id)")
    L.append(
        f"  global:              {_fmt_int(da['empty_recordid'])}  ({da['empty_recordid_pct']}%)"
    )
    L.append("  by source_type:")
    for st, v in da["by_source_type"].items():
        L.append(
            f"    {st:<20} {v['empty_recordid_pct']:>6}%  "
            f"({_fmt_int(v['empty_recordid'])}/{_fmt_int(v['total'])})"
        )
    L.append("")
    L.append("2) DUAL-HOMED (entity_id in person/ AND organization/)")
    dh = s["dual_homed"]
    L.append(f"  count:               {dh['count']}   (expected: stable, never growing)")
    L.append("")
    L.append("3) 5-TUPLE DUPLICATES (entity_id, attribute, norm_value, source_file, record_id)")
    L.append(
        f"  groups count>1:      {_fmt_int(dup['groups_gt1'])}   (expected 0 after compaction)"
    )
    L.append(f"  redundant rows:      {_fmt_int(dup['redundant_rows'])}")
    L.append("  (empty record_id = NULL sentinel, excluded from grouping — GATE 0 B1b)")
    L.append("")
    L.append("4) 3-TUPLE REDUNDANCY (entity_id, attribute, norm_value)")
    L.append(f"  redundant rows:      {_fmt_int(red['redundant_rows'])}  ({red['redundant_pct']}%)")
    L.append("  by source_type:")
    for st, v in red["by_source_type"].items():
        L.append(f"    {st:<20} {v['redundant_pct']:>6}%  ({_fmt_int(v['redundant_rows'])})")
    L.append("")
    L.append("5) COPIES PER GROUP (3-tuple group size)")
    L.append(f"  n. groups:           {_fmt_int(cpg['n_groups'])}")
    L.append(f"  max:                 {cpg['max']}   p50: {cpg['p50']}   p95: {cpg['p95']}")
    L.append("")
    L.append("6) TOP-20 ENTITIES BY N_FACTS (surfaces company-entities in person/)")
    for i, e in enumerate(inv["top_entities_by_facts"], 1):
        nm = (e["canonical_name"] or "")[:38]
        L.append(f"  {i:>2}. {_fmt_int(e['n_facts']):>8}  {e['entity_id']:<26} {nm}")
    L.append("")
    L.append("7) OBSERVATIONS[] POPULATED (field B1b)")
    L.append(f"  facts with obs:      {_fmt_int(obs['populated'])}  ({obs['populated_pct']}%)")
    L.append("")
    idt = s.get("identita") or {}
    rif = idt.get("riferimento_attio", {})
    L.append("8) IDENTITY (16) — who can be merged and who can't")
    L.append(
        f"   reference: Attio, {_fmt_int(rif.get('persone', 0))} people curated over years "
        f"→ strong key {rif.get('chiave_forte_pct')}%. The target is not 100%."
    )
    if not idt.get("filtro_casella_di_servizio", True):
        L.append(
            f"   ⚠️ service mailbox filter NOT active ({idt.get('filtro_casella_errore')}): "
            "the strong keys below include `info@` and similar, and are overestimated."
        )
    for tipo, v in (idt.get("per_tipo") or {}).items():
        L.append(f"   {tipo}  ({_fmt_int(v['n_entita'])} entities)")
        L.append(
            f"     strong key (MERGES):       {_fmt_int(v['chiave_forte']):>8}  "
            f"({v['chiave_forte_pct']}%)"
        )
        L.append(f"     weak, one channel:         {_fmt_int(v['debole_un_canale']):>8}")
        L.append(f"     weak, name only:           {_fmt_int(v['debole_solo_nome']):>8}")
        L.append(f"     no identifier:             {_fmt_int(v['nessun_identificatore']):>8}")
        if v["porta_la_chiave_di_un_altro"]:
            L.append(
                f"     ⚠️ carries SOMEONE ELSE's key: {_fmt_int(v['porta_la_chiave_di_un_altro']):>3}"
                "  (boss's email: not theirs)"
            )
        L.append(
            f"     keys shared by 2+:         {_fmt_int(v['chiavi_condivise']):>8}"
            f"  → {_fmt_int(v['entita_in_chiavi_condivise'])} entities that the key says"
            " are the same person"
        )
    L.append("=" * 74)
    return "\n".join(L)





def assert_clean(snapshot: dict, baseline: dict | None) -> tuple[bool, list[str]]:
    ""






    v: list[str] = []
    if snapshot["dup_five_tuple"]["groups_gt1"] > 0:
        v.append(
            f"5-tuple dup: {snapshot['dup_five_tuple']['groups_gt1']} groups count>1 (expected 0)"
        )
    if baseline is not None:
        b_dh = baseline.get("dual_homed", {}).get("count", 0)
        s_dh = snapshot["dual_homed"]["count"]
        if s_dh > b_dh:
            v.append(f"dual-homed growing: {s_dh} > baseline {b_dh}")
        b_da = baseline.get("deanchored", {}).get("empty_recordid_pct", 0.0)
        s_da = snapshot["deanchored"]["empty_recordid_pct"]
        if s_da > b_da:
            v.append(f"de-anchored growing: {s_da}% > baseline {b_da}%")


        b_id = (baseline.get("identita") or {}).get("per_tipo") or {}
        s_id = (snapshot.get("identita") or {}).get("per_tipo") or {}
        for tipo, b_v in b_id.items():
            s_v = s_id.get(tipo)
            if s_v is None:
                continue
            if s_v["chiave_forte"] < b_v.get("chiave_forte", 0):
                v.append(
                    f"strong keys dropping on {tipo}: {s_v['chiave_forte']} "
                    f"< baseline {b_v.get('chiave_forte', 0)}"
                )
    return (len(v) == 0, v)





def main() -> int:
    ap = argparse.ArgumentParser(
        description="READ-ONLY health check of the knowledge store (anti-regression guard)."
    )
    ap.add_argument(
        "--store",
        type=Path,
        default=KNOWLEDGE_ENTITIES_DIR,
        help="Store entities directory (default: from sbk_config).",
    )
    ap.add_argument("--json", action="store_true", help="Output JSON machine-readable.")
    ap.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of reader workers (default: n. CPU).",
    )
    ap.add_argument(
        "--assert-clean",
        action="store_true",
        help="Exit!=0 if it finds 5-tuple dups (or growth vs --baseline).",
    )
    ap.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Previous JSON snapshot for the growth comparison (dual-homed, de-anchored).",
    )
    args = ap.parse_args()

    store = args.store
    if not store.is_dir():
        print(f"ERROR: store not found: {store}", file=sys.stderr)
        return 2

    snapshot = build_snapshot(store, args.workers)

    baseline = None
    if args.baseline is not None:
        try:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR: baseline unreadable ({args.baseline}): {exc}", file=sys.stderr)
            return 2

    exit_code = 0
    if args.assert_clean:
        ok, violations = assert_clean(snapshot, baseline)
        snapshot["assert_clean"] = {"ok": ok, "violations": violations}
        if not ok:
            exit_code = 1

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(render_report(snapshot))
        if args.assert_clean:
            ac = snapshot["assert_clean"]
            if ac["ok"]:
                print("\nassert-clean: OK")
            else:
                print("\nassert-clean: FAIL")
                for msg in ac["violations"]:
                    print(f"  - {msg}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
