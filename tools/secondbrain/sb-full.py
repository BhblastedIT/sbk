#!/usr/bin/env python3
"""Full run started from the SBK app: download every source in parallel lanes, then run the pipeline in ingest or complete mode, with logs in a run folder."""






































from __future__ import annotations

import argparse
import importlib.util
import os
import re
import signal
import sys
import time
from pathlib import Path

ROOT =Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
for _p in (TOOLS, TOOLS / "cross-source"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import impostazioni_pipeline as IMP  # noqa: E402

PY = ["uv", "run", "python"]

RILETTURA = "tools/cross-source/xs-pipeline-run.py"

ORCHESTRATORE = TOOLS / "cross-source" / "xs-pipeline-run.py"



TETTO_S = {"ingest": 24 * 3600, "tutto": 36 * 3600}

# "l3_x (not chosen)" in the outcome line; older logs wrote the internal code, "l3_x (non_scelto)".
_RE_SALTO = re.compile(r"(\w+) \(([^)]+)\)")
_SOLO_NON_SCELTI = {"not chosen", "non_scelto"}


def _carica(nome: str, percorso: Path):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod



CORSIE = _carica("sb_corsie", Path(__file__).with_name("sb_corsie.py"))

RIPRESA = sys.modules.get("sb_ripresa") or _carica(
    "sb_ripresa", Path(__file__).with_name("sb_ripresa.py")
)


def _carica_giro():
    ""
    return CORSIE.carica_giro()


def _chiuso(log: Path, inizio: int) -> bool:
    ""





    testo = log.read_bytes()[inizio:].decode("utf-8", errors="replace")
    # The runner writes English; "Esito:/INCOMPLETA/spariti/saltati:/avvisi:" are older logs.
    esiti = [r for r in testo.splitlines() if "Outcome:" in r or "Esito:" in r]
    if not esiti:
        return False
    ultima = esiti[-1]
    if not any(x in ultima for x in ("INCOMPLETE", "INCOMPLETA")) or any(
        x in ultima for x in ("vanished", "spariti")
    ):
        return False
    chiave = next((x for x in ("skipped:", "saltati:") if x in ultima), None)
    if chiave is None:
        return True
    salti = ultima.split(chiave, 1)[1].split(", warnings:", 1)[0].split(", avvisi:", 1)[0]
    motivi = {motivo for _id, motivo in _RE_SALTO.findall(salti)}
    return bool(motivi) and motivi <= _SOLO_NON_SCELTI


def _una_volta(nome: str, cmd: list[str], timeout_s: int, cartella: Path, L0R) -> bool:
    ""
    log = cartella / "log" / f"{nome}.log"
    esiti = cartella / "esiti.tsv"
    t0 = time.time()
    inizio = log.stat().st_size if log.exists() else 0
    with log.open("a", encoding="utf-8") as f:
        f.write(L0R.tentativo_testa(1, cmd))
        f.flush()
        rc = L0R._lancia(cmd, f, timeout_s)
    nota = ""
    if rc == 2 and not _chiuso(log, inizio):
        nota = (
            "rc 2 but the outcome is not only warnings or unchosen steps (stages vanished or seriously skipped)"
        )
        if "(cancello_spesa)" in log.read_bytes()[inizio:].decode("utf-8", errors="replace"):

            nota = "paid steps stopped: before did not close everything"
    L0R._esito(esiti, nome, L0R.tentativo_campo(1), f"rc={rc}", f"{int(time.time() - t0)}s", nota)
    if rc == 2 and (ferme := L0R.fonti_non_chiuse(log, inizio)):
        L0R._esito(esiti, nome, "sources not closed", ferme)
    if rc in (0, 2) and not nota:
        return True
    L0R._esito(esiti, nome, "NOT CLOSED AFTER 1 ATTEMPT")
    return False


def _stadi_dopo_la_l1(modo: str) -> list[tuple[str, str]]:
    ""
    xpr = _carica("xs_pipeline_run_ripresa", ORCHESTRATORE)
    return [(p.id, p.nome) for p in xpr.perimetro(modo) if p.strato != "L1"]


def _ripresa_automatica(modo: str):
    ""





    def _stadio(log: Path) -> str | None:
        if not RIPRESA.orchestratore_sa_riprendere(ORCHESTRATORE):
            return None
        return RIPRESA.punto_di_ripresa(log, _stadi_dopo_la_l1(modo))

    return _stadio


def main() -> int:
    ap = argparse.ArgumentParser(
        description=((__doc__ or "").strip().splitlines() or ["Full run started from the SBK app"])[0]
    )
    ap.add_argument(
        "--dir", type=Path, required=True, help="run folder: diary and step logs"
    )
    ap.add_argument("--modo", choices=("ingest", "tutto"))
    ap.add_argument(
        "--solo-scarico",
        action="store_true",
        help="download only, without brain copy and reread",
    )
    ap.add_argument(
        "--solo",
        default="",
        help="with --solo-scarico: the sources, registry ids comma-separated",
    )
    ap.add_argument("--consenti-spesa", action="store_true")
    ap.add_argument("--in-fila", action="store_true", help="download one at a time, without lanes")
    ap.add_argument(
        "--riprendi",
        type=Path,
        help="folder of a stopped or unclosed full run: the download steps it had closed are skipped",
    )
    args = ap.parse_args()
    if bool(args.modo) == args.solo_scarico:
        print("⛔ needs --modo ingest|tutto or --solo-scarico, one of the two")
        return 2
    if args.solo and not args.solo_scarico:
        print("⛔ --solo only applies with --solo-scarico: a full run downloads all sources")
        return 2
    if args.solo_scarico and args.riprendi:
        print("⛔ a download is not resumed: you relaunch, and files already fetched are skipped on their own")
        return 2
    if args.modo == "tutto" and not args.consenti_spesa:
        print(
            "⛔ the complete full run spends: needs --consenti-spesa (the app passes it after your confirmation)"
        )
        return 2

    L0R = _carica_giro()
    mancanti = L0R.controlla_copertura()
    if mancanti:
        print(f"⛔ live sources outside the run and not declared manual: {', '.join(mancanti)}")
        return 2


    signal.signal(signal.SIGTERM, lambda _s, _f: (_ for _ in ()).throw(KeyboardInterrupt()))

    cartella = args.dir

    piano = IMP.applica_al_piano(L0R.PIANO)
    if args.solo:
        solo = {s.strip() for s in args.solo.split(",") if s.strip()}
        ignote = solo - {p.sorgente for p in piano}
        if ignote:
            print(f"⛔ sources not in the run: {', '.join(sorted(ignote))}")
            return 2
        piano = [p for p in piano if p.sorgente in solo]
    nomi = [p.nome for p in piano]
    vecchio = None
    if args.riprendi:


        vecchio = RIPRESA.leggi_giro(args.riprendi, nomi, args.modo)
        if not vecchio.trovato:
            print(f"⛔ cannot find the diary of the run to resume: {args.riprendi / 'esiti.tsv'}")
            return 2
        if vecchio.forse_vivo():
            print(
                f"⛔ the run to resume wrote {int(vecchio.ultimo_segno_s or 0)} s ago and has no end line: "
                "maybe it is still running. Stop it, or try again in a few minutes."
            )
            return 75
    (cartella / "log").mkdir(parents=True, exist_ok=True)
    esiti = cartella / "esiti.tsv"
    riprende = [f"resumes {args.riprendi.name}"] if vecchio else []

    dopo = (
        L0R.DIARIO_SOLO_L0
        if args.solo_scarico
        else (L0R.DIARIO_POI_TUTTO if args.modo == "tutto" else L0R.DIARIO_POI_INGEST)
    )
    L0R._esito(esiti, L0R.DIARIO_INIZIO, f"{len(piano)} steps", dopo, *riprende)
    if any(p.sorgente == "gdrive" for p in piano):
        L0R._esito(esiti, "impostazioni", "drive", IMP.frase("drive"))
    if not args.solo_scarico:
        L0R._esito(esiti, "impostazioni", "guardiano", IMP.frase("guardiano"))
    for sid, perche in L0R.MANUALI.items():
        L0R._esito(esiti, f"manuale:{sid}", "outside the run", perche)
    if args.modo == "tutto":
        L0R._esito(esiti, "spesa", "chosen steps", os.environ.get("SBK_SPESA_STADI", "all"))

    da_fare = piano
    if vecchio:


        for p in piano:
            if p.nome in vecchio.chiusi:
                L0R._esito(
                    esiti,
                    p.nome,
                    L0R.DIARIO_RIPRESO,
                    f"closed in run {args.riprendi.name}, {vecchio.chiusi[p.nome]}",
                )
        da_fare = vecchio.da_rifare(piano)
        if not da_fare and vecchio.finale_chiuso:
            L0R._esito(
                esiti,
                "ripresa",
                "nothing to redo",
                f"run {args.riprendi.name} had closed everything",
            )
            L0R._esito(esiti, L0R.DIARIO_FINE, "not closed: none")
            print(f"diary: {esiti}")
            return 0

    non_chiusi: list[str] = []
    try:
        if args.in_fila:
            L0R._esito(esiti, "corsie", "spente", "download one at a time (--in-fila)")
            for p in da_fare:
                RIPRESA.aspetta_se_in_pausa(cartella, p.nome, L0R._esito)
                if not L0R.esegui(p.nome, [*PY, *p.args], p.timeout_s, cartella):
                    non_chiusi.append(p.nome)
        elif da_fare:
            non_chiusi += CORSIE.scarica(
                L0R, cartella, da_fare, py=PY, cwd=ROOT, ammetti=CORSIE.ammetti_lease_o_pressione
            )
        if args.solo_scarico:
            L0R._esito(esiti, L0R.DIARIO_FINE, "not closed: " + (", ".join(non_chiusi) or "none"))
            RIPRESA.file_pausa(cartella).unlink(missing_ok=True)
            print(f"diary: {esiti}")
            return 1 if non_chiusi else 0

        RIPRESA.aspetta_se_in_pausa(cartella, "backup-kb", L0R._esito)

        with CORSIE.fonti_ferme(L0R, cartella):

            if not RIPRESA.copia_del_cervello(L0R, cartella):
                non_chiusi.append("backup-kb")
                L0R._esito(esiti, args.modo, "NOT LAUNCHED: KB backup failed")
            else:

                RIPRESA.aspetta_se_in_pausa(cartella, args.modo, L0R._esito)
                os.environ["SBK_L1_SEQUENZIALE"] = "1"
                rilettura = [*PY, RILETTURA, f"--{args.modo}"]
                if non_chiusi:


                    rilettura += ["--scarico-non-chiuso", ",".join(non_chiusi)]


                if (
                    vecchio
                    and not da_fare
                    and vecchio.modo == args.modo
                    and not vecchio.finale_chiuso
                    and RIPRESA.orchestratore_sa_riprendere(ORCHESTRATORE)
                ):
                    stadio = RIPRESA.punto_di_ripresa(
                        args.riprendi / "log" / f"{args.modo}.log", _stadi_dopo_la_l1(args.modo)
                    )
                    if stadio:
                        rilettura += ["--riprendi-da", stadio]
                        L0R._esito(esiti, "ripresa", f"reread from {stadio}", "L1 had closed")
                if args.modo == "tutto":
                    ok = _una_volta(
                        "tutto", [*rilettura, "--consenti-spesa"], TETTO_S["tutto"], cartella, L0R
                    )
                else:


                    ok = L0R.esegui(
                        "ingest",
                        rilettura,
                        TETTO_S["ingest"],
                        cartella,
                        rc_ok=(0, 2),
                        riprendi=_ripresa_automatica(args.modo),
                    )
                if not ok:
                    non_chiusi.append(args.modo)
    except KeyboardInterrupt:

        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)


        giro = RIPRESA.leggi_giro(cartella, nomi, args.modo)
        rimasti = giro.non_chiusi(nomi, args.modo)
        L0R._esito(
            esiti,
            L0R.DIARIO_FINE,
            L0R.DIARIO_FERMATO,
            "not closed: " + (", ".join(rimasti) or "none"),
        )

        RIPRESA.file_pausa(cartella).unlink(missing_ok=True)
        print(f"diary: {esiti}")
        return 130

    L0R._esito(esiti, L0R.DIARIO_FINE, "not closed: " + (", ".join(non_chiusi) or "none"))
    RIPRESA.file_pausa(cartella).unlink(missing_ok=True)
    print(f"diary: {esiti}")
    return 1 if non_chiusi else 0


if __name__ == "__main__":
    sys.exit(main())
