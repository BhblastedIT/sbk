#!/usr/bin/env python3
""















































from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))

import sbk_config as cfg  # noqa: E402

KB = cfg.DATA_ROOT / "knowledge"
ENTITIES = KB / "entities"



MAX_LISTA = 20





def _riconoscitore_gruppo():
    ""
    try:
        import importlib.util

        p = PROJECT / "tools" / "cross-source" / "xs-l3-knows-query.py"
        spec = importlib.util.spec_from_file_location("xs_l3_knows_query", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._is_group_name, f"from {p.relative_to(PROJECT)}"
    except Exception as exc:  # noqa: BLE001
        return None, f"NOT available ({exc}): I2 not verifiable"


def _budget_ok() -> tuple[bool, str]:
    try:
        from sbk_resources import budget
    except ImportError:
        return True, "sbk_resources not importable: proceeding (streaming, one file at a time)"
    try:
        quota = budget().job_bytes()
        if quota < 64 * 1024 * 1024:
            return False, f"job quota {quota / 1024**2:.0f} MB: too little even to read"
        return True, f"job quota {quota / 1024**3:.1f} GB"
    except Exception as exc:  # noqa: BLE001
        return True, f"budget not queryable ({exc}): proceeding in streaming"


def _chiuso(fa: dict) -> str | None:
    ""



    if fa.get("valid_to"):
        return str(fa["valid_to"])[:10]
    if fa.get("expired_at"):
        return "exp:" + str(fa["expired_at"])[:10]
    if fa.get("superseded_by"):
        return "sup:" + str(fa["superseded_by"])[:12]
    return None





def _riga_entita(tipo: str, nome_file: str, path: Path, is_group) -> dict:
    st = path.stat()
    d = json.loads(path.read_text())
    nome = d.get("canonical_name") or ""
    fatti = [fa for fa in (d.get("facts") or []) if isinstance(fa, dict)]
    chiusi = {}
    ids = []
    for fa in fatti:
        fid = fa.get("fact_id") or ""
        ids.append(fid)
        m = _chiuso(fa)
        if m:
            chiusi[fid] = [fa.get("attribute") or "?", m]


    e_persona = nome_file.startswith("person_")
    return {
        "f": f"{tipo}/{nome_file}",
        "n": nome,
        "g": 1 if (e_persona and is_group and is_group(nome)) else 0,
        "nf": len(fatti),
        "fx": hashlib.sha1("\n".join(sorted(ids)).encode()).hexdigest()[:16],
        "fa": ids,
        "cl": chiusi,
        "sz": st.st_size,
        "mt": int(st.st_mtime),
    }


def snap(out: Path, base: Path | None) -> int:
    ok, nota = _budget_ok()
    if not ok:
        print(f"⛔ not taking a snapshot now: {nota}", file=sys.stderr)
        return 75

    is_group, nota_g = _riconoscitore_gruppo()
    if is_group is None:
        print(f"⚠️  {nota_g}", file=sys.stderr)


    riuso: dict[str, str] = {}
    if base and base.exists():
        with base.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if r.get("tipo") == "testata":
                    continue
                riuso[f"{r['f']}|{r['sz']}|{r['mt']}"] = line.rstrip("\n")

    tot = {"entita": 0, "gruppi": 0, "fatti": 0, "chiusi": 0, "riusate": 0, "illeggibili": 0}
    code = {
        nome: (len(os.listdir(KB / nome)) if (KB / nome).is_dir() else None)
        for nome in ("review-queue", "conflicts", "reclassification")
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    ids_path = out.with_suffix(out.suffix + ".ids")
    righe_tmp = out.with_suffix(out.suffix + ".tmp")

    with righe_tmp.open("w") as fo, ids_path.open("w") as fi:
        for tipo in sorted(p.name for p in ENTITIES.iterdir() if p.is_dir()):
            tdir = ENTITIES / tipo
            for nome_file in sorted(os.listdir(tdir)):
                if not nome_file.endswith(".json"):
                    continue
                p = tdir / nome_file
                st = p.stat()
                chiave = f"{tipo}/{nome_file}|{st.st_size}|{int(st.st_mtime)}"
                line = riuso.get(chiave)
                if line is not None:
                    r = json.loads(line)
                    tot["riusate"] += 1
                else:
                    try:
                        r = _riga_entita(tipo, nome_file, p, is_group)
                    except Exception:  # noqa: BLE001 — un file rotto si conta, non ferma la foto
                        tot["illeggibili"] += 1
                        r = {
                            "f": f"{tipo}/{nome_file}",
                            "n": "",
                            "g": 0,
                            "nf": 0,
                            "fx": "ILLEGGIBILE",
                            "fa": [],
                            "cl": {},
                            "sz": st.st_size,
                            "mt": int(st.st_mtime),
                        }
                    r.pop("_canali", None)
                    line = json.dumps(r, ensure_ascii=False)

                tot["entita"] += 1
                tot["gruppi"] += r["g"]
                tot["fatti"] += r["nf"]
                tot["chiusi"] += len(r["cl"])
                fo.write(line + "\n")
                for fid in r["fa"]:
                    fi.write(fid + "\n")





    testata = {
        "tipo": "testata",
        "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
        "store": str(ENTITIES),
        "totali": tot,
        "code": code,
        "riconoscitore": nota_g,
        "budget": nota,
    }
    with out.open("w") as fo:
        fo.write(json.dumps(testata, ensure_ascii=False) + "\n")
        with righe_tmp.open() as fi:
            for line in fi:
                fo.write(line)
    righe_tmp.unlink()



    subprocess.run(
        ["sort", "-u", "-o", str(ids_path), str(ids_path)],
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )

    print(
        f"snapshot: {tot['entita']} entities ({tot['gruppi']} groups) · {tot['fatti']} facts "
        f"({tot['chiusi']} closed) · reused {tot['riusate']} · unreadable {tot['illeggibili']}"
    )
    print(f"  → {out}  (+ {ids_path.name})")
    return 0





def _leggi(path: Path):
    ""
    with path.open() as f:
        prima = f.readline()
        testata = json.loads(prima) if prima else {}
        if testata.get("tipo") != "testata":
            raise SystemExit(f"{path}: missing header — not an sb-kb-diff manifest")
        for line in f:
            yield json.loads(line)


def _testata(path: Path) -> dict:
    with path.open() as f:
        return json.loads(f.readline())


def diff(pa: Path, pb: Path, json_out: bool, max_lista: int) -> int:
    ta, tb = _testata(pa), _testata(pb)
    v: dict[str, list] = {
        "I1_entita_sparite": [],
        "I2_gruppi_nuovi": [],
        "I3_fatti_spariti": [],
        "I4_chiusure_senza_data": [],
    }
    w: dict[str, list] = {
        "entita_nuove": [],
        "gruppi_risolti": [],
        "fatti_spostati": [],
        "chiusure_nuove": [],
        "riaperture": [],
        "illeggibili": [],
    }
    oggi = date.today().isoformat()

    ga = iter(_leggi(pa))
    gb = iter(_leggi(pb))
    ra = next(ga, None)
    rb = next(gb, None)
    candidati_persi: list[tuple[str, str]] = []

    def _confronta(a: dict, b: dict) -> None:
        if a["fx"] == "ILLEGGIBILE" or b["fx"] == "ILLEGGIBILE":
            w["illeggibili"].append(b["f"])
            return
        if not a["g"] and b["g"]:
            v["I2_gruppi_nuovi"].append(f"{b['f']} · «{b['n']}» (was «{a['n']}»)")
        if a["g"] and not b["g"]:
            w["gruppi_risolti"].append(f"{b['f']} · «{a['n']}» → «{b['n']}»")
        if a["fx"] != b["fx"]:
            dopo = set(b["fa"])
            for fid in a["fa"]:
                if fid not in dopo:
                    candidati_persi.append((fid, a["f"]))

        for fid, (attr, marca) in b["cl"].items():
            if fid not in a["cl"]:
                if marca.startswith(("sup:", "exp:")) or (marca[:10] <= oggi and len(marca) == 10):
                    w["chiusure_nuove"].append(f"{b['f']} · «{b['n']}» · {attr} → {marca}")
                else:
                    v["I4_chiusure_senza_data"].append(
                        f"{b['f']} · «{b['n']}» · {attr} → {marca!r}"
                    )
        for fid, (attr, marca) in a["cl"].items():
            if fid in set(b["fa"]) and fid not in b["cl"]:
                w["riaperture"].append(f"{b['f']} · «{b['n']}» · {attr} (was closed {marca})")

    while ra is not None or rb is not None:
        if rb is None or (ra is not None and ra["f"] < rb["f"]):
            v["I1_entita_sparite"].append(f"{ra['f']} · «{ra['n']}» ({ra['nf']} facts)")
            for fid in ra["fa"]:
                candidati_persi.append((fid, ra["f"]))
            ra = next(ga, None)
        elif ra is None or rb["f"] < ra["f"]:
            marca = " ⚠️GROUP" if rb["g"] else ""
            w["entita_nuove"].append(f"{rb['f']} · «{rb['n']}» ({rb['nf']} facts){marca}")
            if rb["g"]:
                v["I2_gruppi_nuovi"].append(f"{rb['f']} · «{rb['n']}» (NEW entity)")
            rb = next(gb, None)
        else:
            if ra["fx"] != rb["fx"] or ra["g"] != rb["g"] or ra["cl"] != rb["cl"]:
                _confronta(ra, rb)
            ra = next(ga, None)
            rb = next(gb, None)


    if candidati_persi:
        ids_b = pb.with_suffix(pb.suffix + ".ids")
        if ids_b.exists():
            with tempfile.NamedTemporaryFile("w", suffix=".ids", delete=False) as tf:
                for fid, _ in sorted(candidati_persi):
                    tf.write(fid + "\n")
                tmp = tf.name
            res = subprocess.run(
                ["comm", "-23", tmp, str(ids_b)],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "LC_ALL": "C"},
            )
            os.unlink(tmp)
            spariti = set(res.stdout.split())
            prov = dict((fid, ent) for fid, ent in candidati_persi)
            for fid in sorted(spariti):
                v["I3_fatti_spariti"].append(f"{fid} (was in {prov.get(fid, '?')})")
            for fid, ent in candidati_persi:
                if fid not in spariti:
                    w["fatti_spostati"].append(f"{fid} (gone from {ent}, exists elsewhere)")
        else:
            for fid, ent in candidati_persi:
                v["I3_fatti_spariti"].append(
                    f"{fid} (was in {ent}; .ids index absent: can't tell moved from vanished)"
                )

    violate = any(v.values())
    esito = {
        "prima": {"file": str(pa), "quando": ta.get("quando"), **ta.get("totali", {})},
        "dopo": {"file": str(pb), "quando": tb.get("quando"), **tb.get("totali", {})},
        "code_prima": ta.get("code"),
        "code_dopo": tb.get("code"),
        "violazioni": v,
        "segnalazioni": w,
        "esito": "VIOLATO" if violate else "OK",
    }

    if json_out:
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 1 if violate else 0

    A, B = ta.get("totali", {}), tb.get("totali", {})
    print("── sb-kb-diff ─────────────────────────────────────────────────────")
    print(f"  BEFORE {ta.get('quando', '?')} · AFTER {tb.get('quando', '?')}")
    print()
    print("  THE NUMBERS")
    for k, label in (
        ("entita", "entities"),
        ("gruppi", "group-records"),
        ("fatti", "facts"),
        ("chiusi", "closed facts"),
    ):
        a_, b_ = A.get(k, 0), B.get(k, 0)
        d_ = b_ - a_
        print(f"    {label:16} {a_:8} → {b_:8}   {'+' if d_ >= 0 else ''}{d_}")
    ca, cb = ta.get("code") or {}, tb.get("code") or {}
    for nome in ca:
        if ca.get(nome) != cb.get(nome):
            print(f"    queue {nome:12} {ca.get(nome)} → {cb.get(nome)}")
    print()

    print("  INVARIANTS")
    nomi = {
        "I1_entita_sparite": "I1 no entity vanishes",
        "I2_gruppi_nuovi": "I2 group-records do not increase",
        "I3_fatti_spariti": "I3 no fact vanishes from the store",
        "I4_chiusure_senza_data": "I4 no closure without a plausible date",
    }
    for k, label in nomi.items():
        lista = v[k]
        segno = "✅" if not lista else "⛔"
        print(f"    {segno} {label}" + (f" — {len(lista)} VIOLATIONS" if lista else ""))
        for voce in lista[:max_lista]:
            print(f"         {voce}")
        if len(lista) > max_lista:
            print(f"         … and {len(lista) - max_lista} more (--json for all)")
    print()

    print("  TO READ (allowed, but reviewed — I4/I5)")
    etichette = {
        "chiusure_nuove": "new closures (EVERY line must be acknowledged: it's the defense against false CLOSED)",
        "riaperture": "reopenings",
        "entita_nuove": "new entities",
        "gruppi_risolti": "groups resolved (fewer: good)",
        "fatti_spostati": "facts moved between entities",
        "illeggibili": "unreadable files",
    }
    for k, label in etichette.items():
        lista = w[k]
        if not lista:
            continue
        print(f"    · {label}: {len(lista)}")
        for voce in lista[:max_lista]:
            print(f"         {voce}")
        if len(lista) > max_lista:
            print(f"         … and {len(lista) - max_lista} more")
    print()
    if violate:
        print(
            "  ⛔ RESULT: INVARIANTS VIOLATED — restore from the tar and investigate, do not continue."
        )
    else:
        print("  ✅ RESULT: invariants OK. The semantic judgment is now up to the test:")
        print("     uv run python tools/util/sb-who-collaudo.py --veloce")
    return 1 if violate else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="snapshots and compares two states of the knowledge store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap", help="snapshots the store into a JSONL manifest")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--base", type=Path, help="previous manifest: reuses untouched files")
    d = sub.add_parser("diff", help="compares two manifests and checks the invariants")
    d.add_argument("prima", type=Path)
    d.add_argument("dopo", type=Path)
    d.add_argument("--json", action="store_true")
    d.add_argument("--max-lista", type=int, default=MAX_LISTA)
    a = ap.parse_args()

    if not ENTITIES.is_dir():
        print(f"knowledge store missing: {ENTITIES}", file=sys.stderr)
        return 2
    if a.cmd == "snap":
        return snap(a.out, a.base)
    return diff(a.prima, a.dopo, a.json, a.max_lista)


if __name__ == "__main__":
    raise SystemExit(main())
