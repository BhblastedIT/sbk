#!/usr/bin/env python3
"""The six knowledge-store numbers, recomputed by a command instead of quoted (--scrivi updates docs/sbk/audits/SEI-NUMERI.json)."""




































































from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

from conteggio import Conteggio  # noqa: E402




SEI_NUMERI = REPO / "docs" / "sbk" / "audits" / "SEI-NUMERI.json"

UTIL = REPO / "tools" / "util"






def _adesso_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017


def _importa(nome_file: str, alias: str):
    ""



    import importlib.util as il

    percorso = UTIL / nome_file
    spec = il.spec_from_file_location(alias, percorso)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"{percorso} non importabile")
    mod = il.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _voce(c: Conteggio, cosa: str, come: str, nota: str = "") -> dict:
    ""
    d = c.come_dict()
    d["percentuale"] = c.percentuale()
    d["cosa"] = cosa
    d["come"] = come
    if nota:
        d["nota"] = nota
    return d


def _vuoto(cosa: str, perche: str) -> dict:
    ""




    return _voce(Conteggio(0, 0), cosa, "— (da costruire)", perche)





def numero_1_identita() -> dict:
    p = _importa("sb-persone.py", "sb_persone_sei")
    m = p.misura()
    return {
        "titolo": "① identity — who in `person/` is not provably a person",
        "senza_prova": _voce(
            m["senza_prova"],
            "`person/` entities without a fact proving a person (UNCERTAIN + NON-PERSON + MENTION)",
            "uv run python tools/util/sb-persone.py",
        ),
        "non_persona": _voce(
            m["non_persona"],
            "`person/` entities that are provably NOT people",
            "uv run python tools/util/sb-persone.py",
        ),
        "fatti_senza_prova": _voce(
            m["fatti_senza_prova"],
            "facts that live inside those entities",
            "uv run python tools/util/sb-persone.py",
        ),






        "pseudo_identita": _voce(
            m["pseudo_identita"],
            "transcript placeholders («Speaker 1 @ …»): declared at coinage, "
            "outside the people census",
            "uv run python tools/util/sb-pseudo.py --verifica",
        ),
        "per_categoria": {k: _voce(c, k, "same") for k, c in m["per_categoria"].items()},
    }





def numero_2_provenienza(numeri_ratchet: dict, archi: dict) -> dict:
    r = archi["risposte"]
    return {
        "titolo": "② provenance — a fact knows where it comes from, and the pointers resolve",
        "anello_1_ha_record_id": _voce(
            Conteggio.da_dict(numeri_ratchet["ha_puntatore"]),
            "facts with a populated `record_id` (the easiest of the three links)",
            "uv run python tools/util/sb-ratchet.py",
            "link 1 of 3. Links 2 (the record_id opens a row) and 3 (the row opens a "
            "message) require opening the pointed-to parquets: see below.",
        ),
        "anello_2_apre_una_riga": _vuoto(
            "the `record_id` really opens a row of the pointed-to parquet",
            "the executable definition does not exist: the figure cited in the reports comes from a "
            "scratchpad script that was never versioned, to be redone.",
        ),
        "anello_3_apre_un_messaggio": _vuoto(
            "the pointed-to row opens a human-readable message",
            "same, to be redone. ⚠️ A figure that ran before is withdrawn: duplicate `fact_id`s "
            "in relationship-facts.parquet inflated the join.",
        ),
        "archi_non_vivi": _voce(
            Conteggio.da_dict(r["riferimenti_che_non_risolvono_direttamente"]),
            "edges toward a `fact_id` that is not a live fact today",
            "uv run python tools/util/sb-edges.py",
            "NAIVE READING. Cite it only together with the row below: most of these are "
            "`merged_fact_ids`, and no longer being live is their job.",
        ),
        "archi_irrecuperabili": _voce(
            Conteggio.da_dict(r["riferimenti_irrecuperabili"]),
            "edges that do not reach a live fact even by following redirects",
            "uv run python tools/util/sb-edges.py",
            "a small fraction of the full denominator: FORBIDDEN to cite it alone.",
        ),
        "archi_irrecuperabili_su_chi_puo_rompersi": _voce(
            Conteggio.da_dict(r["irrecuperabili_su_chi_puo_rompersi"]),
            "the same, on the true denominator (all edges minus the `merged_fact_ids`)",
            "uv run python tools/util/sb-edges.py",
            "this is the figure to cite.",
        ),
        "danno_netto_fact_id": _voce(
            Conteggio.da_dict(r["danno_netto_fact_id"]),
            "dead `fact_id`s of which not even a copy remains in `archive/`",
            "uv run python tools/util/sb-edges.py",
            "the operational figure: opening the reference finds nothing anywhere.",
        ),
        "coda_con_fatto_irrecuperabile": _voce(
            Conteggio.da_dict(r["conflitti_con_almeno_un_fatto_morto"]),
            "queued conflicts that cite at least one unrecoverable fact",
            "uv run python tools/util/sb-edges.py",
            "⛔ a high percentage ran here: withdrawn because not reproducible on any "
            "partition of the queue.",
        ),
        "fact_id_in_due_entita": _voce(
            Conteggio.da_dict(r["fact_id_in_due_entita"]),
            "`fact_id`s that are in two different entities",
            "uv run python tools/util/sb-edges.py",
        ),
    }





def numero_3_tempo(numeri_ratchet: dict) -> dict:
    return {
        "titolo": "③ time — facts don't need closing, they need weighting",
        "fatti_di_stato": _voce(
            Conteggio.da_dict(numeri_ratchet["fatti_di_stato"]),
            "facts whose attribute class is STATE (the rest are mostly events)",
            "uv run python tools/util/sb-ratchet.py",
            "an event is not reconfirmed: declaring it `stale` is the defect that filled the queue.",
        ),
    }





def numero_4_reversibilita() -> dict:
    ""





    import sbk_config as cfg

    K = cfg.DATA_ROOT / "knowledge"
    archiviati = 0
    archivio = K / "archive"
    if archivio.is_dir():
        for cartella in archivio.iterdir():
            if cartella.is_dir():
                archiviati += sum(1 for _ in cartella.glob("*.json"))
    meta = K / "meta"
    journal = len(list(meta.glob("fusioni-*.jsonl"))) if meta.is_dir() else 0
    backup = sum(1 for p in K.rglob(".backup") if p.is_dir())
    cartella_inc = K / "increments"
    incrementi = len(list(cartella_inc.glob("*.jsonl"))) if cartella_inc.is_dir() else 0
    return {
        "titolo": "④ reversibility — a repair can be undone",
        "journal_di_fusione": _voce(
            Conteggio(journal, archiviati),
            "`meta/fusioni-*.jsonl` files produced, over the profiles a merge has archived",
            "ls ~/.sbk-data/knowledge/meta/fusioni-*.jsonl",
            "`journal_fusioni.Journal` exists and is imported by four `l4-*` scripts: "
            "it has produced zero files in its entire life.",
        ),
        "incrementi": _voce(
            Conteggio(incrementi, archiviati),
            "increments in `knowledge/increments/` (the new form: list, before, author, "
            "seal), over the profiles a merge has archived",
            "ls ~/.sbk-data/knowledge/increments/*.jsonl",
            "the form exists as of today (`tools/cross-source/incremento.py`) and the full round "
            "is tested at every commit (`sb-incremento-vivo`), but NO real script is yet "
            "wired in: the zero is declared in `docs/sbk/audits/INCREMENTO.json` (`attivato_il`), "
            "it is not a silent guard. When that field has a date, a zero here turns red.",
        ),
        "directory_backup": _voce(
            Conteggio(backup, archiviati),
            "`.backup` directories in the store, over the same archived profiles",
            "find ~/.sbk-data/knowledge -type d -name .backup",
            "`backup=True` ran on many files in the past and left "
            "nothing, because `_backup_file` swallowed the `OSError` with a bare "
            "`return`. Now every failure is counted (`sbk_config.backup_falliti()`) and "
            "reported; the historical zero stays zero, but from now on a new failure is not silent.",
        ),
    }





def numero_5_rete(archi: dict) -> dict:
    return {
        "titolo": "⑤ network — zero entity→entity edges",
        "archi_dichiarati": _vuoto(
            "DECLARED entity→entity edges (not inferred from co-occurrence)",
            "the count lives in no tool, and the numerator is zero by construction: "
            "a declared edge cannot even be written today. To be built with the perimeter "
            "of the roadmap.",
        ),
        "fact_id_condivisi": _voce(
            Conteggio.da_dict(archi["risposte"]["fact_id_in_due_entita"]),
            "`fact_id`s present in two entities — co-occurrence, NOT an edge",
            "uv run python tools/util/sb-edges.py",
            "it is here because it is the only network signal measured today, and it is important "
            "that it not be mistaken for the missing edge.",
        ),
    }





def numero_6_antistale(artefatti: dict) -> dict:
    orfani_su_disco = sum(1 for v in artefatti["orfani"] if v["esiste"])
    censiti = artefatti["artefatti"]
    return {
        "titolo": "⑥ anti-stale — what no one re-reads stops being produced",
        "M1_fatti_stale": _vuoto(
            "live facts whose source row did not appear in the last closed generation",
            "requires `uploadId` per run and `last_seen_generation` on the fact: they do not exist.",
        ),
        "M2_regole_spente": _vuoto(
            "hand-written rules whose support has collapsed",
            "requires the rules registry (YAML `rule → where → how the support is counted`): "
            "it does not exist.",
        ),
        "M3_scadenze_non_onorate": _vuoto(
            "claims with a passed `recheck_by` and not re-verified",
            "extension of `sb-doc-check.py` not yet written: today it verifies the "
            "verifiable-now, it does not keep the list of the expired.",
        ),
        "M5_artefatti_orfani": _voce(
            Conteggio(orfani_su_disco, censiti),
            "artifacts written and never re-read, present on disk",
            "uv run python tools/util/sb-artefatti.py",
            "⚠️ the twin category «read-never-written» is CIRCUMSTANTIAL (names computed at "
            "runtime are invisible to static analysis) and never enters a gate.",
        ),
        "M6_omission_rate": _vuoto(
            "planted updates that the system misses, on a frozen bench",
            "the bench does not exist: v0 declared empty, never estimated.",
        ),
        "git_processi_che_ripartono": _vuoto(
            "commits that leave behind a process that restarts on its own",
            "the proxy over `git log` does not yet have an executable definition: until it does, "
            "it is declared, not estimated.",
        ),
    }





def m4_esche(artefatti: dict) -> dict:
    ""






    nome = SEI_NUMERI.name
    orfano = any(v["artefatto"].endswith(nome) for v in artefatti["orfani"])
    fantasma = any(v["artefatto"].endswith(nome) for v in artefatti["fantasmi"])
    scattate = []
    if orfano:
        scattate.append(f"{nome} is ORPHAN in the census: written and never re-read")
    if fantasma:
        scattate.append(f"{nome} is GHOST: read and never written")
    return {
        "titolo": "M4 · the traps — if one springs, the round's report is INVALID",



        "autoriferimento": _voce(
            Conteggio(len(scattate), 2),
            "self-reference conditions violated on SEI-NUMERI.json (orphan · ghost)",
            "included in the run — reads the sb-artefatti census",
            "rule 3 of the anti-stale metric: a report without a reader is the next orphan, "
            "and must flag itself instead of waiting for a periodic audit.",
        ),
        "esche_piantate_nel_dato": _vuoto(
            "traps planted in the DATA that the round did not detect (backdated fact, "
            "zero-support rule, yesterday's `recheck_by`)",
            "they come with M1-M3, which today are declared empty: without the measures there are no "
            "traps to plant. Declared, not estimated.",
        ),
        "scattate": scattate,
    }





def misura(con_archi: bool = True) -> dict:
    ""
    import time

    t0 = time.perf_counter()
    ratchet = _importa("sb-ratchet.py", "sb_ratchet_sei")
    artefatti_mod = _importa("sb-artefatti.py", "sb_artefatti_sei")



    numeri_ratchet = ratchet.misura(tollera_illeggibili=True)
    artefatti = artefatti_mod.analizza()
    if con_archi:
        edges = _importa("sb-edges.py", "sb_edges_sei")
        archi = edges.censisci(edges.DEFAULT_STORE, tollera=True)
    else:
        archi = {"risposte": {}}

    fuori = {
        "quando": _adesso_iso(),
        "secondi": round(time.perf_counter() - t0, 1),
        "M4": m4_esche(artefatti),
        "1_identita": numero_1_identita(),
        "3_tempo": numero_3_tempo(numeri_ratchet),
        "4_reversibilita": numero_4_reversibilita(),
        "6_antistale": numero_6_antistale(artefatti),
    }
    if con_archi:
        fuori["2_provenienza"] = numero_2_provenienza(numeri_ratchet, archi)
        fuori["5_rete"] = numero_5_rete(archi)
    return fuori


def _righe(rapporto: dict):
    ""
    for blocco, contenuto in rapporto.items():
        if not isinstance(contenuto, dict) or blocco == "M4":
            continue
        for k, v in contenuto.items():
            if isinstance(v, dict) and "valore" in v:
                yield f"{blocco}.{k}", v


def stampa(r: dict) -> None:
    print(f"\n── the six numbers · {r['quando']} ({r['secondi']} s) ──────────────────\n")
    for blocco, contenuto in r.items():
        if not isinstance(contenuto, dict) or "titolo" not in contenuto:
            continue
        print(f"  {contenuto['titolo']}")
        for k, v in contenuto.items():
            if not (isinstance(v, dict) and "valore" in v):
                continue
            c = Conteggio.da_dict(v)
            pct = "" if c.percentuale() is None else f"  ({c.percentuale()}%)"
            print(f"      {k:42} {c!s:>28}{pct}")
        print()
    scattate = r.get("M4", {}).get("scattate") or []
    if scattate:
        print("  ⛔ TRAPS SPRUNG — this round's report is INVALID:")
        for s in scattate:
            print(f"      {s}")
    else:
        print("  ✓ M4: no trap sprung, the report is valid")
    print()





def _dove() -> str:
    ""





    try:
        return str(SEI_NUMERI.relative_to(REPO))
    except ValueError:
        return str(SEI_NUMERI)


def controlla() -> int:
    ""









    if not SEI_NUMERI.exists():
        print(
            f"❌ no report: {_dove()} does not exist (and it is versioned).\n"
            "  uv run python tools/util/sb-sei-numeri.py --scrivi"
        )
        return 1
    try:
        r = json.loads(SEI_NUMERI.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"❌ {_dove()} cannot be read ({exc})")
        return 1
    scattate = r.get("M4", {}).get("scattate") or []
    if scattate:
        print("❌ M4: a trap sprang, the report is INVALID:")
        for s in scattate:
            print(f"     {s}")
        print("   repair, then: uv run python tools/util/sb-sei-numeri.py --scrivi")
        return 1


    estratto = _quando_ultima_estrazione()
    misurato = r.get("quando", "")
    if estratto and misurato and estratto > misurato:
        print(
            "❌ the six numbers are older than the last extraction:\n"
            f"     extraction  {estratto[:19]}\n"
            f"     measure     {misurato[:19]}\n"
            "   uv run python tools/util/sb-sei-numeri.py --scrivi"
        )
        return 1
    parziali = [k for k, v in _righe(r) if v.get("parziale")]
    print(
        f"✓ the six numbers of {misurato[:19]} — M4 clean"
        + (f", {len(parziali)} numbers declared partial" if parziali else "")
    )
    return 0


def _quando_ultima_estrazione() -> str:


    p = Path.home() / ".sbk-data" / "knowledge" / "meta" / "last-extraction.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("last_extraction", "")
    except (OSError, ValueError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--scrivi", action="store_true", help="update docs/sbk/audits/SEI-NUMERI.json"
    )
    ap.add_argument("--json", action="store_true", help="print the raw report")
    ap.add_argument(
        "--controlla",
        action="store_true",
        help="the gate: does NOT measure, reads the report (red if a trap sprang or if it is stale)",
    )
    ap.add_argument(
        "--senza-archi",
        action="store_true",
        help="skip the sb-edges pass: the report comes out without ② and ⑤",
    )
    a = ap.parse_args()

    if a.controlla:
        return controlla()





    if a.senza_archi and a.scrivi:
        print(
            "❌ --senza-archi produces a report without ② and ⑤: it is not written to the\n"
            "   versioned file. For a quick look: --senza-archi alone."
        )
        return 2

    r = misura(con_archi=not a.senza_archi)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        stampa(r)
    if a.scrivi:
        SEI_NUMERI.parent.mkdir(parents=True, exist_ok=True)
        SEI_NUMERI.write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"written {SEI_NUMERI.relative_to(REPO)} — the diff is the measurement")
    return 0


if __name__ == "__main__":
    sys.exit(main())
