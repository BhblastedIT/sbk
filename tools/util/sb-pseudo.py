#!/usr/bin/env python3
""






































































from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, datetime  # noqa: UP017
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
for _p in (_TOOLS, _TOOLS / "cross-source"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from knowledge_schema import (  # noqa: E402
    CLASSE_PSEUDO,
    classi_dichiarate,
    e_pseudo_identita,
    fatto_marchio_pseudo,
)

import sbk_config as cfg  # noqa: E402

PERSON = cfg.DATA_ROOT / "knowledge" / "entities" / "person"
L3 = cfg.DATA_ROOT / "l3" / "nlp"
JOURNAL = cfg.DATA_ROOT / "knowledge" / "meta" / "pseudo-journal.jsonl"


def _importa(nome_file: str, alias: str):
    ""
    for cartella in ("cross-source", "util"):
        percorso = _TOOLS / cartella / nome_file
        if percorso.exists():
            spec = importlib.util.spec_from_file_location(alias, percorso)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[alias] = mod
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(nome_file)



_XS = _importa("xs-l2-knowledge-extract.py", "xs_l2_per_pseudo")
_SPLIT = _importa("sb-split-speaker.py", "sb_split_per_pseudo")

e_etichetta = _XS.e_etichetta_di_trascrizione
id_estrattore = _XS._id_pseudo_identita
id_split = _SPLIT._id



e_chimera_split = _SPLIT.e_chimera




_SEPARATORE = " @ "


def _forma_pseudo(nome: str) -> bool:
    n = (nome or "").strip()
    if _SEPARATORE in n:
        return bool(e_etichetta(n.split(_SEPARATORE)[0]))
    return bool(e_etichetta(n))


def _scoperta_del_conio(nome: str) -> bool:
    ""



























    n = (nome or "").strip()
    if _SEPARATORE not in n:
        return False
    return bool(e_chimera_split(n)) and not e_etichetta(n.split(_SEPARATORE)[0])


def _ora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _profili(radice: Path):
    for f in sorted(radice.glob("*.json")):
        try:
            yield f, json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def dalla_fonte() -> tuple[set[str], set[str], list[tuple[str, str]]]:
    ""









    import duckdb
    from sbk_resources import configure_duckdb

    fonti = [L3 / "deep-facts.parquet", L3 / "relationship-facts.parquet"]
    se = set()
    ss = set()
    if not any(f.exists() for f in fonti):
        return se, ss, None
    con = duckdb.connect()
    configure_duckdb(con)
    coppie: set[tuple[str, str]] = set()
    try:
        for f in fonti:
            if not f.exists():
                continue
            righe = con.execute(
                f"SELECT DISTINCT subject, source_id FROM '{f}'"  # noqa: S608
            ).fetchall()
            for subj, sid in righe:
                if subj and e_etichetta(str(subj)):
                    coppie.add((str(subj), str(sid or "")))
    finally:
        con.close()
    fuori = []
    for etich, sid in sorted(coppie):
        a = id_estrattore(etich, sid)[0]
        b = id_split(f"{sid}|{etich}")
        se.add(a)
        ss.add(b)
        fuori.append((a, b))
    return se, ss, fuori


def censisci(radice: Path, fonte=None) -> dict:
    ""




    se, ss, coppie = fonte if fonte is not None else dalla_fonte()
    rigenerati = se | ss
    esito = {
        "coppie_nella_fonte": None if coppie is None else len(coppie),
        "id_conio_estrattore": len(se),
        "id_conio_split": len(ss),
        "id_in_comune_fra_i_due_coni": len(se & ss),
        "sul_disco": 0,
        "da_rigenerazione": 0,
        "residuo_solo_forma": 0,
        "gia_marcate": 0,
        "da_marcare": 0,
        "marchio_ereditato_da_fusione": 0,
        "doppioni_stessa_coppia": 0,
        "fatti_sotto": 0,
        "residuo": [],
        "bersagli": [],

        "scoperti_dal_conio": 0,
        "fatti_scoperti": 0,
        "scoperti": [],
    }








    su_disco: set[str] = set()
    for f, d in _profili(radice):
        esito["sul_disco"] += 1
        eid = f.stem
        su_disco.add(eid)
        nome = d.get("canonical_name") or ""
        fatti = d.get("facts") or []
        da_fonte = eid in rigenerati
        da_forma = _forma_pseudo(nome)
        if not (da_fonte or da_forma):
            if _scoperta_del_conio(nome):
                esito["scoperti_dal_conio"] += 1
                esito["fatti_scoperti"] += len(fatti)
                esito["scoperti"].append((eid, nome, len(fatti)))


            if CLASSE_PSEUDO in classi_dichiarate(fatti):
                esito["marchio_ereditato_da_fusione"] += 1
            continue
        if da_fonte:
            esito["da_rigenerazione"] += 1
        else:
            esito["residuo_solo_forma"] += 1
            esito["residuo"].append((eid, nome, len(fatti)))
        esito["fatti_sotto"] += len(fatti)
        if e_pseudo_identita(fatti):
            esito["gia_marcate"] += 1
        else:
            esito["da_marcare"] += 1
            esito["bersagli"].append(eid)




    esito["doppioni_stessa_coppia"] = sum(
        1 for a, b in (coppie or ()) if a in su_disco and b in su_disco
    )
    return esito



_FONTE = "tools/util/sb-pseudo.py (M7: migration of pseudo-identities minted before the mark)"


def _fatto_marchio(eid: str) -> dict:
    ""








    return fatto_marchio_pseudo(eid, fonte=_FONTE, quando=_ora())


def _journal_di(radice: Path) -> Path:
    ""








    if radice == PERSON:
        return JOURNAL
    return radice.parent / "pseudo-journal.jsonl"


def marca(radice: Path, bersagli: list[str], applica: bool) -> dict:
    ""
    esito = {"toccati": 0, "gia_a_posto": 0, "illeggibili": 0}
    righe = []
    for eid in bersagli:
        p = radice / f"{eid}.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            esito["illeggibili"] += 1
            continue
        fatti = d.get("facts") or []
        if e_pseudo_identita(fatti):
            esito["gia_a_posto"] += 1
            continue
        esito["toccati"] += 1
        if not applica:
            continue
        d["facts"] = [*fatti, _fatto_marchio(eid)]
        d["updated_at"] = _ora()
        p.write_text(json.dumps(d, ensure_ascii=True, indent=2), encoding="utf-8")
        righe.append({"op": "marca", "eid": eid, "quando": _ora()})
    if applica and righe:
        journal = _journal_di(radice)
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as fh:
            for r in righe:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return esito


def verifica(radice: Path, fonte=None) -> tuple[dict, list[str]]:
    ""
    c = censisci(radice, fonte)
    guai = []
    if c["da_marcare"]:
        guai.append(f"{c['da_marcare']} pseudo-identities without a mark: counted among people")
    if c["coppie_nella_fonte"] is None:
        guai.append("the L3 parquets are not there: the population was NOT regenerated from the source")
    if c["doppioni_stessa_coppia"]:
        guai.append(
            f"{c['doppioni_stessa_coppia']} pairs (recording, label) minted TWICE: "
            "two live entities for the same speaker"
        )
    if c["scoperti_dal_conio"]:
        guai.append(
            f"{c['scoperti_dal_conio']} placeholders that the split recognizes and the minting does not "
            f"({c['fatti_scoperti']} facts): at the next run they are reborn as people"
        )
    return c, guai


def main() -> int:
    ap = argparse.ArgumentParser(description="The pseudo-identities in person/")
    ap.add_argument("--radice", default="", help="a COPY of the store (default: the live data)")
    ap.add_argument("--marca", action="store_true", help="writes the mark on the unmarked ones")
    ap.add_argument("--applica", action="store_true", help="actually writes (default: dry)")
    ap.add_argument(
        "--verifica", action="store_true", help="the guard: exit 1 if there is a violation"
    )
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    radice = Path(a.radice).expanduser() if a.radice else PERSON
    if not radice.exists():
        print(f"⛔ does not exist: {radice}")
        return 2
    if a.applica and radice == PERSON:
        print("⛔ --applica on live data: pass --radice with a COPY.")
        return 2

    c, guai = verifica(radice)
    print(f"\nPSEUDO-IDENTITIES in {radice}\n")
    print(f"   pairs (label, recording) in the source        : {c['coppie_nella_fonte']}")
    print(f"   ids from the extractor minting                : {c['id_conio_estrattore']}")
    print(f"   ids from the split minting                    : {c['id_conio_split']}")
    print(f"   ids shared between the two mintings           : {c['id_in_comune_fra_i_due_coni']}")
    print(f"   entities in the folder                        : {c['sul_disco']}")
    print(f"   reproduced by the regeneration                : {c['da_rigenerazione']}")
    print(f"   residue seen only from the name shape         : {c['residuo_solo_forma']}")
    print(f"   already marked                                : {c['gia_marcate']}")
    print(f"   to mark                                       : {c['da_marcare']}")
    print(f"   mark inherited from a merge (does not count)  : {c['marchio_ereditato_da_fusione']}")
    print(f"   pairs minted TWICE                            : {c['doppioni_stessa_coppia']}")
    print(f"   facts under the pseudo-identities             : {c['fatti_sotto']}")

    print(
        f"   discovered by the minting recognizer          : {c['scoperti_dal_conio']}"
        f"  ({c['fatti_scoperti']} facts)"
    )
    if c["residuo"]:
        print("\n   the residue, one by one (regeneration does not cover it):")
        for eid, nome, n in sorted(c["residuo"], key=lambda t: -t[2])[:25]:
            print(f"      {eid}  {nome[:48]:48} {n:5} facts")
    if c["scoperti"]:
        print("\n   discovered by the minting (the split divided them, the minting will make them people again):")
        for eid, nome, n in sorted(c["scoperti"], key=lambda t: -t[2])[:15]:
            print(f"      {eid}  {nome[:48]:48} {n:5} facts")

    if a.marca:
        e = marca(radice, c["bersagli"], a.applica)
        modo = "APPLIED" if a.applica else "dry-run (no writes)"
        print(f"\n   mark — {modo}: {e}")

    if a.json:
        Path(a.json).write_text(
            json.dumps(
                {k: v for k, v in c.items() if k != "bersagli"},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    if a.verifica:
        if guai:
            print("\n⛔ GUARD RED")
            for g in guai:
                print(f"   · {g}")
            return 1
        print("\n✅ guard green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
