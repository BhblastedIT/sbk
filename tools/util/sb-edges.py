#!/usr/bin/env python3
"""Census of the incoming edges of the knowledge store: what points to each fact and entity, read-only."""































































































from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from conteggio import Conteggio, FileIlleggibile  # noqa: E402

DEFAULT_STORE = Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()




MAX_SALTI_REDIRECT = 20




_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _pare_un_uuid(v: str) -> bool:
    return bool(_UUID.match(v))


def _adesso_iso() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017





@dataclass
class Sorgente:
    ""

    nome: str
    percorso: str
    riferimenti: int = 0
    diretti: int = 0
    redirect: int = 0
    morti: int = 0



    solo_archivio: int = 0

    saltati: dict = field(default_factory=dict)

    esempi_morti: list = field(default_factory=list)


    morti_id: set = field(default_factory=set)

    archiviati_id: set = field(default_factory=set)
    nota: str = ""

    def salta(self, motivo: str, quanti: int = 1) -> None:
        self.saltati[motivo] = self.saltati.get(motivo, 0) + quanti

    def registra(self, esito: str, fact_id: str, archivio=frozenset()) -> None:
        ""
        self.riferimenti += 1
        if esito == "diretto":
            self.diretti += 1
        elif esito == "redirect":
            self.redirect += 1
        else:
            self.morti += 1
            self.morti_id.add(fact_id)
            if fact_id in archivio:
                self.solo_archivio += 1
                self.archiviati_id.add(fact_id)
            if len(self.esempi_morti) < 5:
                self.esempi_morti.append(fact_id)

    @property
    def non_risolvono_direttamente(self) -> Conteggio:
        ""






        return Conteggio(self.redirect + self.morti, self.riferimenti, dict(self.saltati))

    @property
    def irrecuperabili(self) -> Conteggio:
        ""
        return Conteggio(self.morti, self.riferimenti, dict(self.saltati))

    @property
    def danno_netto(self) -> Conteggio:
        ""




        return Conteggio(self.morti - self.solo_archivio, self.riferimenti, dict(self.saltati))

    def come_dict(self) -> dict:
        return {
            "sorgente": self.nome,
            "percorso": self.percorso,
            "riferimenti": self.riferimenti,
            "diretti": self.diretti,
            "via_redirect": self.redirect,
            "morti": self.morti,
            "solo_in_archivio": self.solo_archivio,
            "non_risolvono_direttamente": self.non_risolvono_direttamente.come_dict(),
            "irrecuperabili": self.irrecuperabili.come_dict(),
            "danno_netto": self.danno_netto.come_dict(),
            "saltati": dict(self.saltati),
            "esempi_morti": list(self.esempi_morti),
            "nota": self.nota,
        }





def _leggi_json(path: Path, sorgente: Sorgente | None, tollera: bool):
    ""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        if not tollera:
            raise FileIlleggibile(
                f"{path} cannot be read ({exc}): the census would be incomplete without saying so. "
                f"Re-run with --tollera-illeggibili if you want to count the rest."
            ) from exc
        if sorgente is not None:
            sorgente.salta("unreadable json")
        return None


def _righe_jsonl(path: Path, sorgente: Sorgente, tollera: bool):
    ""
    try:
        fh = path.open(encoding="utf-8")
    except OSError as exc:
        if not tollera:
            raise FileIlleggibile(f"{path} cannot be opened ({exc})") from exc
        sorgente.salta("file cannot be opened")
        return
    with fh:
        for riga in fh:
            riga = riga.strip()
            if not riga:
                continue
            try:
                yield json.loads(riga)
            except ValueError:
                if not tollera:
                    raise FileIlleggibile(
                        f"{path}: a line is not JSON. The file is append-only: "
                        f"a broken line may hide an interrupted write."
                    ) from None
                sorgente.salta("unreadable jsonl line")


def _file_entita(store: Path):
    ""



    radice = store / "knowledge" / "entities"
    if not radice.is_dir():
        return
    for tipo in sorted(p for p in radice.iterdir() if p.is_dir()):
        yield from sorted(tipo.glob("*.json"))





@dataclass
class Censo:
    ""


    vivi: dict = field(default_factory=dict)

    doppi: dict = field(default_factory=dict)

    redirect: dict = field(default_factory=dict)



    archivio: set = field(default_factory=set)
    entita: int = 0
    fatti: int = 0
    file_illeggibili: int = 0
    archivio_file: int = 0

    def risolvi(self, fact_id: str) -> str:
        ""
        if fact_id in self.vivi:
            return "diretto"
        visti = {fact_id}
        corrente = fact_id
        for _ in range(MAX_SALTI_REDIRECT):
            corrente = self.redirect.get(corrente)
            if corrente is None or corrente in visti:
                return "morto"
            if corrente in self.vivi:
                return "redirect"
            visti.add(corrente)
        return "morto"


def censisci_vivi(store: Path, tollera: bool, verboso: bool = False) -> Censo:
    ""
    c = Censo()
    t0 = time.perf_counter()
    for n, percorso in enumerate(_file_entita(store), 1):
        profilo = _leggi_json(percorso, None, tollera)
        if profilo is None:
            c.file_illeggibili += 1
            continue
        eid = sys.intern(str(profilo.get("entity_id") or percorso.stem))
        c.entita += 1
        for fatto in profilo.get("facts") or []:
            fid = fatto.get("fact_id")
            if not fid:
                continue
            c.fatti += 1
            gia = c.vivi.get(fid)
            if gia is None:
                c.vivi[fid] = eid
            elif gia != eid:
                c.doppi.setdefault(fid, {gia}).add(eid)

            for assorbito in fatto.get("merged_fact_ids") or []:
                c.redirect.setdefault(assorbito, fid)
        if verboso and n % 5000 == 0:
            print(f"    …{n} profili · {c.fatti:,} fatti", file=sys.stderr)
    if verboso:
        print(f"    passata 1: {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    return c


def censisci_archivio(store: Path, censo: Censo, tollera: bool) -> int:
    ""










    radice = store / "knowledge" / "archive"
    if not radice.is_dir():
        return 0
    finti = Sorgente("archive", "knowledge/archive/*/*.json")
    for cartella in sorted(x for x in radice.iterdir() if x.is_dir()):
        for percorso in sorted(cartella.glob("*.json")):
            censo.archivio_file += 1
            profilo = _leggi_json(percorso, finti, tollera)
            if profilo is None:
                continue
            for fatto in profilo.get("facts") or []:
                fid = fatto.get("fact_id")
                if fid:
                    censo.archivio.add(fid)
    return len(censo.archivio)


def aggiungi_redirect_dai_sidecar(store: Path, censo: Censo, tollera: bool) -> int:
    ""




    finti = Sorgente("redirect-sidecar", "meta/compaction-map-*.jsonl")
    aggiunti = 0
    for percorso in sorted((store / "knowledge" / "meta").glob("compaction-map-*.jsonl")):
        for riga in _righe_jsonl(percorso, finti, tollera):
            vecchio, nuovo = riga.get("old_fact_id"), riga.get("surviving_fact_id")
            if vecchio and nuovo and vecchio not in censo.redirect:
                censo.redirect[vecchio] = nuovo
                aggiunti += 1
    return aggiunti





def da_profili(store: Path, censo: Censo, tollera: bool) -> list:
    ""
    merged = Sorgente(
        "merged_fact_ids",
        "knowledge/entities/*/*.json",
        nota=(
            "ids absorbed by compaction: by construction they are NOT live facts. "
            "A 'morto' here means the path to the survivor has also been lost, "
            "i.e. the fact is no longer traceable."
        ),
    )
    superseduti = Sorgente(
        "superseded_by",
        "knowledge/entities/*/*.json",
        nota="must contain a fact_id, never an entity_id (contract in knowledge_schema).",
    )
    for percorso in _file_entita(store):
        profilo = _leggi_json(percorso, merged, tollera)
        if profilo is None:
            continue
        for fatto in profilo.get("facts") or []:
            for assorbito in fatto.get("merged_fact_ids") or []:
                merged.registra(censo.risolvi(assorbito), assorbito, censo.archivio)
            sup = fatto.get("superseded_by")
            if sup:
                if str(sup).startswith(("person_", "organization_", "org_", "deal_")):
                    superseduti.salta("it is an entity_id, not a fact_id")
                    superseduti.registra("morto", str(sup), censo.archivio)
                else:
                    superseduti.registra(censo.risolvi(str(sup)), str(sup), censo.archivio)
    return [merged, superseduti]


def _fatti_del_conflitto(voce: dict):
    ""
    for chiave in ("existing_fact", "new_fact"):
        f = voce.get(chiave)
        if isinstance(f, dict) and f.get("fact_id"):
            yield chiave, str(f["fact_id"])


def da_coda_conflitti(store: Path, censo: Censo, tollera: bool):
    ""




    s = Sorgente("conflict queue", "knowledge/conflicts/*")
    voci = 0
    con_morto = 0
    con_non_vivo = 0
    cartella = store / "knowledge" / "conflicts"

    def _voce(v: dict) -> None:
        nonlocal voci, con_morto, con_non_vivo
        voci += 1
        morto_qui = False
        non_vivo_qui = False
        visto = False
        for _chiave, fid in _fatti_del_conflitto(v):
            visto = True
            esito = censo.risolvi(fid)
            s.registra(esito, fid, censo.archivio)
            if esito == "morto":
                morto_qui = True
            if esito != "diretto":
                non_vivo_qui = True
        if not visto:
            s.salta("entry without any fact_id")
        if morto_qui:
            con_morto += 1
        if non_vivo_qui:
            con_non_vivo += 1

    vivo = cartella / "pending-review.json"
    if vivo.exists():
        dati = _leggi_json(vivo, s, tollera)
        for v in dati or []:
            if isinstance(v, dict):
                _voce(v)
    for percorso in sorted(cartella.glob("overflow-*.jsonl")):
        for v in _righe_jsonl(percorso, s, tollera):
            if isinstance(v, dict):
                _voce(v)

    s.nota = (
        f"{voci:,} entries in the queue (pending-review + overflow). "
        "pending-review alone is capped at MAX_QUEUE_DEPTH=500."
    )
    return (
        s,
        Conteggio(con_morto, voci, dict(s.saltati)),
        Conteggio(con_non_vivo, voci, dict(s.saltati)),
    )


def da_sidecar(store: Path, censo: Censo, tollera: bool) -> list:
    ""
    meta = store / "knowledge" / "meta"

    comp = Sorgente(
        "compaction sidecar",
        "knowledge/meta/compaction-map-*.jsonl",
        nota=(
            "the `old_fact_id` is dead by construction: what counts here is the "
            "`surviving_fact_id`, which if it does not resolve means "
            "compaction lost its own target."
        ),
    )
    for percorso in sorted(meta.glob("compaction-map-*.jsonl")):
        for riga in _righe_jsonl(percorso, comp, tollera):
            sopravvissuto = riga.get("surviving_fact_id")
            if sopravvissuto:
                comp.registra(censo.risolvi(str(sopravvissuto)), str(sopravvissuto), censo.archivio)
            else:
                comp.salta("line without surviving_fact_id")

    ric = Sorgente(
        "reanchor sidecar",
        "knowledge/meta/reanchor-map-*.jsonl",
        nota="each line says a fact changed anchor: if the fact is dead, the line can no longer be undone.",
    )
    for percorso in sorted(meta.glob("reanchor-map-*.jsonl")):
        for riga in _righe_jsonl(percorso, ric, tollera):
            fid = riga.get("fact_id")
            if fid:
                ric.registra(censo.risolvi(str(fid)), str(fid), censo.archivio)
            else:
                ric.salta("line without fact_id")

    return [comp, ric]


def da_events_db(store: Path) -> Sorgente:
    ""







    s = Sorgente("events.db", "rq/events.db")
    percorso = store / "rq" / "events.db"
    if not percorso.exists():
        s.salta("file absent")
        s.nota = "not found"
        return s
    con = sqlite3.connect(f"file:{percorso}?mode=ro", uri=True)
    try:
        colonne = [r[1] for r in con.execute("PRAGMA table_info(events)")]
        con_fact = [c for c in colonne if "fact" in c.lower()]
        righe = con.execute("SELECT count(*) FROM events").fetchone()[0]
        nel_metadata = con.execute(
            "SELECT count(*) FROM events WHERE raw_metadata LIKE '%fact_id%'"
        ).fetchone()[0]
    finally:
        con.close()
    for c in con_fact:
        s.salta(f"column {c} not read")







    if nel_metadata:
        s.salta("rows with 'fact_id' in raw_metadata, not extracted", nel_metadata)
    s.nota = (
        f"{righe:,} rows, columns {colonne}: no fact_id, "
        f"{nel_metadata} rows with 'fact_id' in raw_metadata. "
        "Carries ENTITY ids (p_*, RQ space), not fact ids."
    )
    return s


def da_entity_bridge(store: Path, censo: Censo, tollera: bool) -> Sorgente:
    ""




    s = Sorgente("entity-bridge.json", "rq/entity-bridge.json")
    percorso = store / "rq" / "entity-bridge.json"
    if not percorso.exists():
        s.salta("file absent")
        s.nota = "not found"
        return s
    dati = _leggi_json(percorso, s, tollera)
    if dati is None:
        return s
    valori = list(dati.values()) if isinstance(dati, dict) else list(dati)





    candidati = [v for v in valori if isinstance(v, str) and _pare_un_uuid(v)]
    for v in candidati:
        s.registra(censo.risolvi(v), v, censo.archivio)
    s.nota = (
        f"{len(valori):,} entries; values in the form of a fact_id (UUID): "
        f"{len(candidati)}. Maps key→p_* (entities), not facts."
    )
    return s





def censisci(store: Path, tollera: bool, verboso: bool = False) -> dict:
    t0 = time.perf_counter()
    censo = censisci_vivi(store, tollera, verboso)

    censisci_archivio(store, censo, tollera)
    dai_sidecar = aggiungi_redirect_dai_sidecar(store, censo, tollera)

    sorgenti = []
    sorgenti += da_profili(store, censo, tollera)
    coda, conflitti_con_morto, conflitti_con_non_vivo = da_coda_conflitti(store, censo, tollera)
    sorgenti.append(coda)
    sorgenti += da_sidecar(store, censo, tollera)
    sorgenti.append(da_events_db(store))
    sorgenti.append(da_entity_bridge(store, censo, tollera))

    tot_rif = sum(s.riferimenti for s in sorgenti)
    tot_morti = sum(s.morti for s in sorgenti)
    tot_non_diretti = sum(s.redirect + s.morti for s in sorgenti)
    tot_archiviati = sum(s.solo_archivio for s in sorgenti)



    per_costruzione = sum(s.riferimenti for s in sorgenti if s.nome == "merged_fact_ids")
    possono_rompersi = tot_rif - per_costruzione
    morti_distinti: set = set()
    archiviati_distinti: set = set()
    for s in sorgenti:
        morti_distinti |= s.morti_id
        archiviati_distinti |= s.archiviati_id
    saltati_tutti: dict = {}
    for s in sorgenti:
        for motivo, quanti in s.saltati.items():
            saltati_tutti[f"{s.nome}: {motivo}"] = (
                saltati_tutti.get(f"{s.nome}: {motivo}", 0) + quanti
            )
    if censo.file_illeggibili:
        saltati_tutti["unreadable profiles"] = censo.file_illeggibili

    return {
        "quando": _adesso_iso(),
        "store": str(store),
        "secondi": round(time.perf_counter() - t0, 1),
        "inventario": {
            "entita": censo.entita,
            "fatti": censo.fatti,
            "fact_id_distinti": len(censo.vivi),
            "profili_in_archivio": censo.archivio_file,
            "fact_id_in_archivio": len(censo.archivio),
            "redirect_distinti_dai_profili": len(censo.redirect) - dai_sidecar,
            "redirect_dai_sidecar": dai_sidecar,
            "profili_illeggibili": censo.file_illeggibili,
        },
        "sorgenti": [s.come_dict() for s in sorgenti],
        "risposte": {




            "riferimenti_che_non_risolvono_direttamente": Conteggio(
                tot_non_diretti, tot_rif, saltati_tutti
            ).come_dict(),


            "riferimenti_irrecuperabili": Conteggio(tot_morti, tot_rif, saltati_tutti).come_dict(),




            "irrecuperabili_su_chi_puo_rompersi": Conteggio(
                tot_morti, possono_rompersi, saltati_tutti
            ).come_dict(),


            "irrecuperabili_con_copia_in_archivio": Conteggio(
                tot_archiviati, tot_morti, saltati_tutti
            ).come_dict(),



            "danno_netto_occorrenze": Conteggio(
                tot_morti - tot_archiviati, possono_rompersi, saltati_tutti
            ).come_dict(),
            "danno_netto_fact_id": Conteggio(
                len(morti_distinti - archiviati_distinti), len(morti_distinti), saltati_tutti
            ).come_dict(),
            "fact_id_in_due_entita": Conteggio(
                len(censo.doppi), len(censo.vivi), {"unreadable profiles": censo.file_illeggibili}
            ).come_dict(),




            "conflitti_con_almeno_un_fatto_non_vivo": conflitti_con_non_vivo.come_dict(),

            "conflitti_con_almeno_un_fatto_morto": conflitti_con_morto.come_dict(),
        },
        "esempi_fact_id_in_due_entita": [
            {"fact_id": k, "entita": sorted(v)} for k, v in list(censo.doppi.items())[:5]
        ],
    }


def stampa(r: dict) -> None:
    inv = r["inventario"]
    print("── sb-edges · who points to a fact ──────────────────────────────────")
    print(f"  store   : {r['store']}")
    print(f"  when    : {r['quando']}  ({r['secondi']} s)")
    print(
        f"  live    : {inv['fatti']:,} facts across {inv['entita']:,} entities "
        f"({inv['fact_id_distinti']:,} distinct fact_id)"
    )
    print(
        f"  redirect: {inv['redirect_distinti_dai_profili']:,} distinct from merged_fact_ids + "
        f"{inv['redirect_dai_sidecar']:,} from sidecars"
    )
    if inv["profili_illeggibili"]:
        print(f"  ⚠️  unreadable profiles: {inv['profili_illeggibili']}")
    print()
    print(
        f"  {'source':<24} {'refs':>10} {'direct':>10} {'redirect':>10} "
        f"{'DEAD':>10} {'in arch.':>9}"
    )
    print(f"  {'-' * 24} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 9}")
    for s in r["sorgenti"]:
        print(
            f"  {s['sorgente']:<24} {s['riferimenti']:>10,} {s['diretti']:>10,} "
            f"{s['via_redirect']:>10,} {s['morti']:>10,} {s.get('solo_in_archivio', 0):>9,}"
        )
    print()
    for s in r["sorgenti"]:
        if s["nota"]:
            print(f"  · {s['sorgente']}: {s['nota']}")
        if any(s["saltati"].values()):
            print(f"    ⚠️  skipped: {s['saltati']}")
    print()
    print("  THE THREE QUESTIONS")
    for etichetta, chiave in (
        ("references that are not a live fact", "riferimenti_che_non_risolvono_direttamente"),
        ("  of which UNRECOVERABLE (not even via redirect)", "riferimenti_irrecuperabili"),
        ("  the same, on edges that CAN break", "irrecuperabili_su_chi_puo_rompersi"),
        ("  of which with a copy in archive/", "irrecuperabili_con_copia_in_archivio"),
        ("  NET DAMAGE (not even a copy), occurrences", "danno_netto_occorrenze"),
        ("  NET DAMAGE, distinct fact_id", "danno_netto_fact_id"),
        ("fact_id in TWO different entities", "fact_id_in_due_entita"),
        ("conflicts with a non-live fact", "conflitti_con_almeno_un_fatto_non_vivo"),
        ("  of which with an UNRECOVERABLE fact", "conflitti_con_almeno_un_fatto_morto"),
    ):
        c = Conteggio.da_dict(r["risposte"][chiave])
        pct = c.percentuale()
        coda = f"  ({pct}%)" if pct is not None else ""
        print(f"    {etichetta:<38} {c}{coda}")
    if r["esempi_fact_id_in_due_entita"]:
        print()
        print("  examples of fact_id shared between entities:")
        for e in r["esempi_fact_id_in_due_entita"]:
            print(f"    {e['fact_id']} → {', '.join(e['entita'])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--store", default=str(DEFAULT_STORE), help="data root (default ~/.sbk-data)"
    )
    ap.add_argument("--json", dest="uscita", help="also writes the report to this file")
    ap.add_argument(
        "--tollera-illeggibili",
        action="store_true",
        help="count the rest instead of raising when a file cannot be read (the skip is declared)",
    )
    ap.add_argument("-v", "--verboso", action="store_true", help="progress on stderr")
    args = ap.parse_args()



    try:
        import sbk_resources as risorse

        b = risorse.budget()
        if b.pressure.should_abort:
            print(
                f"machine under pressure ({b.pressure}): deferring instead of filling it",
                file=sys.stderr,
            )
            return risorse.EXIT_BUSY
        tetto = b.job_bytes
    except Exception as exc:  # noqa: BLE001 — without a budget we continue, declaring it
        print(f"budget unavailable ({exc}): continuing without a cap", file=sys.stderr)
        risorse, tetto = None, None

    store = Path(args.store).expanduser()
    if not (store / "knowledge" / "entities").is_dir():
        print(f"{store}/knowledge/entities does not exist: nothing to census", file=sys.stderr)
        return 2

    rapporto = censisci(store, args.tollera_illeggibili, args.verboso)

    if risorse is not None and tetto:
        mio = risorse.self_footprint()
        if mio:
            rapporto["footprint_bytes"] = mio
            rapporto["footprint_su_tetto"] = round(mio / tetto, 3)

    stampa(rapporto)
    if "footprint_bytes" in rapporto:
        print(
            f"\n  memory used: {rapporto['footprint_bytes'] / 1024**2:.0f} MB "
            f"({rapporto['footprint_su_tetto'] * 100:.0f}% of the requested cap)"
        )
    if args.uscita:


        Path(args.uscita).write_text(json.dumps(rapporto, indent=2, ensure_ascii=False) + "\n")
        print(f"\n  report: {args.uscita}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileIlleggibile as exc:
        print(f"\n⛔ {exc}", file=sys.stderr)
        sys.exit(1)
