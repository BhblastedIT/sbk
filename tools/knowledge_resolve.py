""




























































































































































from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path




ARCHIVI = ("merged", "deduped", "split", "partial-resolved")




SEG_LIMITE_SCANSIONE = 0.80

MAX_SALTI = 50


class RisoluzioneImpossibile(RuntimeError):
    ""


class VivoEArchiviato(RisoluzioneImpossibile):
    ""


class ArbitratoImpossibile(RisoluzioneImpossibile):
    ""


class MacchinaPiena(RuntimeError):
    ""






@dataclass(frozen=True)
class Lapide:
    ""

    entity_id: str
    archivio: str
    genere: str
    verso: tuple[str, ...]
    quando: str
    nome: str
    motivo: str

    @property
    def chiave_ordine(self) -> tuple[str, int]:

        return (self.quando, -ARCHIVI.index(self.archivio))


@dataclass(frozen=True)
class Anello:
    ""



    da: str
    a: str
    archivio: str
    genere: str
    quando: str
    contesa: tuple[str, ...] = ()

    def __str__(self) -> str:
        c = f" [contested: {'+'.join(self.contesa)}]" if self.contesa else ""
        return f"{self.da} --{self.genere}/{self.archivio}--> {self.a}{c}"


@dataclass(frozen=True)
class Risoluzione:
    ""

    id_iniziale: str
    esito: str
    catena: tuple[Anello, ...] = ()
    destinazioni: tuple[str, ...] = ()
    avvisi: tuple[str, ...] = ()

    @property
    def redirige(self) -> bool:
        ""
        return len(self.destinazioni) == 1 and self.destinazioni[0] != self.id_iniziale

    @property
    def destinazione(self) -> str | None:
        ""

        return self.destinazioni[0] if self.redirige else None

    @property
    def salti(self) -> int:
        return len(self.catena)

    def __str__(self) -> str:
        p = " · ".join(str(a) for a in self.catena) or "(no hop)"
        return f"{self.id_iniziale} → {self.esito}: {p}"

    def come_dict(self) -> dict:
        return {
            "id_iniziale": self.id_iniziale,
            "esito": self.esito,
            "salti": self.salti,
            "catena": [
                {
                    "da": a.da,
                    "a": a.a,
                    "archivio": a.archivio,
                    "genere": a.genere,
                    "quando": a.quando,
                    "contesa": list(a.contesa),
                }
                for a in self.catena
            ],
            "destinazioni": list(self.destinazioni),
            "avvisi": list(self.avvisi),
        }



ESITI = (
    "vivo",
    "vivo_e_archiviato",
    "risolto",
    "biforcato",
    "ciclo",
    "nel_nulla",
    "sconosciuto",
)





@dataclass
class Indice:
    ""

    vivi: dict[str, str] = field(default_factory=dict)
    lapidi: dict[str, dict[str, Lapide]] = field(default_factory=dict)
    costruito_in: float = 0.0
    da_cache: bool = False
    store: Path | None = None



    @classmethod
    def costruisci(
        cls,
        store: Path | str | None = None,
        *,
        cache: Path | str | None = None,
        controlla_pressione: bool = True,
    ) -> Indice:
        ""





        store = Path(store) if store else _store_predefinito()
        if controlla_pressione:
            _guardia_memoria()

        t0 = time.perf_counter()
        firma = _firma(store)
        if cache:
            letto = _da_cache(Path(cache), firma, store)
            if letto is not None:
                letto.costruito_in = time.perf_counter() - t0
                return letto

        vivi: dict[str, str] = {}
        radice = store / "entities"
        if radice.is_dir():
            for tipo in sorted(radice.iterdir()):
                if not tipo.is_dir():
                    continue


                for f in os.scandir(tipo):
                    if f.name.endswith(".json"):
                        vivi[f.name[:-5]] = tipo.name

        lapidi: dict[str, dict[str, Lapide]] = {}
        for sub in ARCHIVI:
            d = store / "archive" / sub
            if not d.is_dir():
                continue
            for f in os.scandir(d):
                if not f.name.endswith(".json"):
                    continue
                lap = _leggi_lapide(Path(f.path), f.name[:-5], sub)
                if lap is not None:
                    lapidi.setdefault(lap.entity_id, {})[sub] = lap

        idx = cls(
            vivi=vivi,
            lapidi=lapidi,
            costruito_in=time.perf_counter() - t0,
            store=store,
        )
        if cache:
            idx.scrivi_cache(Path(cache), firma)
        return idx



    def scelta(self, eid: str, *, tollera_anomalie: bool = False) -> Lapide | None:
        ""



        gruppo = self.lapidi.get(eid)
        if not gruppo:
            return None
        if len(gruppo) == 1:
            return next(iter(gruppo.values()))
        ordinate = sorted(gruppo.values(), key=lambda x: x.chiave_ordine, reverse=True)
        prima = ordinate[0]
        pari = [x for x in ordinate if x.quando == prima.quando]
        if len(pari) > 1 and len({x.verso for x in pari}) > 1:
            msg = (
                f"{eid}: {len(pari)} tombstones with the same instant {prima.quando} "
                f"and different destinations ({', '.join(x.archivio for x in pari)}). "
                "The data does not decide."
            )
            if not tollera_anomalie:
                raise ArbitratoImpossibile(msg)
        return prima



    def risolvi(
        self,
        entity_id: str,
        *,
        tollera_anomalie: bool = False,
        max_salti: int = MAX_SALTI,
    ) -> Risoluzione:
        ""











        avvisi: list[str] = []
        vivo = entity_id in self.vivi
        lapide = self.scelta(entity_id, tollera_anomalie=tollera_anomalie)

        if vivo and lapide is not None:

            msg = (
                f"{entity_id} is ALIVE in entities/{self.vivi[entity_id]}/ and has a "
                f"tombstone in archive/{lapide.archivio}/ ({lapide.genere} of "
                f"{lapide.quando[:10]} toward {', '.join(lapide.verso) or '∅'}). "
                "Not redirecting it: it is an anomaly to declare."
            )
            if not tollera_anomalie:
                raise VivoEArchiviato(msg)
            return Risoluzione(entity_id, "vivo_e_archiviato", (), (entity_id,), (msg,))

        if vivo:
            return Risoluzione(entity_id, "vivo", (), (entity_id,), ())

        if lapide is None:
            return Risoluzione(
                entity_id,
                "sconosciuto",
                (),
                (),
                (f"{entity_id}: neither in entities/ nor in archive/.",),
            )

        return self._cammina(entity_id, lapide, max_salti, avvisi, tollera_anomalie)



    def _cammina(
        self,
        partenza: str,
        lapide: Lapide,
        max_salti: int,
        avvisi: list[str],
        tollera: bool,
    ) -> Risoluzione:
        catena: list[Anello] = []
        visti = {partenza}
        fronte = [(partenza, lapide)]
        arrivi: list[str] = []
        esito = "risolto"

        while fronte:
            if len(catena) >= max_salti:
                avvisi.append(f"cap of {max_salti} hops reached: chain truncated.")
                esito = "ciclo"
                break
            corrente, lap = fronte.pop(0)
            gruppo = self.lapidi.get(corrente) or {}
            contesa = tuple(sorted(gruppo)) if len(gruppo) > 1 else ()
            if contesa:
                avvisi.append(
                    f"{corrente}: tombstones in {len(gruppo)} archives ({'+'.join(contesa)}); "
                    f"the most recent wins, {lap.archivio} of {lap.quando[:10]}."
                )
            if not lap.verso:
                avvisi.append(f"{corrente}: tombstone {lap.archivio} with no destination.")
                arrivi.append(corrente)
                continue

            for t in lap.verso:
                catena.append(Anello(corrente, t, lap.archivio, lap.genere, lap.quando, contesa))
                if t in visti:
                    avvisi.append(
                        f"cycle: {t} is already in the chain ({' → '.join(dict.fromkeys([partenza] + [a.a for a in catena]))}). Truncated."
                    )
                    esito = "ciclo"
                    fronte = []
                    arrivi = []
                    break
                visti.add(t)
                if t in self.vivi:
                    arrivi.append(t)
                    if t in self.lapidi:
                        arrivi_lap = self.scelta(t, tollera_anomalie=True)
                        avvisi.append(
                            f"⚠️ the destination {t} is ALIVE and has a tombstone "
                            f"({arrivi_lap.archivio if arrivi_lap else '?'}): "
                            "anomaly on the destination, the chain stops here anyway."
                        )
                    continue
                prossima = self.scelta(t, tollera_anomalie=tollera)
                if prossima is None:
                    avvisi.append(f"{t}: neither alive nor archived — the chain ends in nothing.")
                    esito = "nel_nulla"
                    arrivi.append(t)
                    continue
                fronte.append((t, prossima))
            else:
                continue
            break

        if esito == "ciclo":
            return Risoluzione(partenza, "ciclo", tuple(catena), (), tuple(avvisi))
        finali = tuple(dict.fromkeys(arrivi))
        if len(finali) > 1:


            esito = "biforcato"
        elif not finali or finali[0] not in self.vivi:
            esito = "nel_nulla"
        return Risoluzione(partenza, esito, tuple(catena), finali, tuple(avvisi))



    def diagnosi(self) -> dict:
        ""
        per_archivio: dict[str, int] = dict.fromkeys(ARCHIVI, 0)
        vivi_archiviati = 0
        vivi_per_archivio: dict[str, int] = dict.fromkeys(ARCHIVI, 0)
        multi = 0
        punt = 0
        punt_arch = 0
        auto = 0
        for eid, gruppo in self.lapidi.items():
            if len(gruppo) > 1:
                multi += 1
            if eid in self.vivi:
                vivi_archiviati += 1
            for sub, lap in gruppo.items():
                per_archivio[sub] += 1
                if eid in self.vivi:
                    vivi_per_archivio[sub] += 1
                for t in lap.verso:
                    punt += 1
                    if t == eid:
                        auto += 1
                    if t in self.lapidi:
                        punt_arch += 1
        return {
            "vivi": len(self.vivi),
            "id_archiviati": len(self.lapidi),
            "lapidi": sum(per_archivio.values()),
            "per_archivio": per_archivio,
            "id_in_piu_archivi": multi,
            "vivi_e_archiviati": vivi_archiviati,
            "vivi_e_archiviati_per_archivio": vivi_per_archivio,
            "puntatori": punt,
            "puntatori_verso_archiviati": punt_arch,
            "auto_puntatori": auto,
            "costruito_in_s": round(self.costruito_in, 3),
            "da_cache": self.da_cache,
        }

    def cicli(self) -> list[list[str]]:
        ""

        archi: dict[str, tuple[str, ...]] = {}
        for eid in self.lapidi:
            lap = self.scelta(eid, tollera_anomalie=True)
            archi[eid] = lap.verso if lap else ()
        trovati: list[list[str]] = []
        stato: dict[str, int] = {}

        def visita(n: str, pila: list[str]) -> None:
            stato[n] = 1
            pila.append(n)
            for t in archi.get(n, ()):
                if stato.get(t) == 1:
                    trovati.append(pila[pila.index(t) :] + [t])
                elif t in archi and stato.get(t) is None:
                    visita(t, pila)
            pila.pop()
            stato[n] = 2

        for n in list(archi):
            if stato.get(n) is None:
                visita(n, [])
        return trovati



    def scrivi_cache(self, percorso: Path, firma: dict | None = None) -> None:
        ""
        percorso = Path(percorso)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "firma": firma if firma is not None else _firma(self.store or _store_predefinito()),
            "vivi": self.vivi,
            "lapidi": [
                [x.entity_id, x.archivio, x.genere, list(x.verso), x.quando, x.nome, x.motivo]
                for g in self.lapidi.values()
                for x in g.values()
            ],
        }
        tmp = percorso.with_suffix(percorso.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, percorso)





def _store_predefinito() -> Path:
    return (
        Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "knowledge"
    )


def _guardia_memoria() -> None:
    ""

    try:  # pragma: no cover - depends on the machine
        import sys

        radice = Path(__file__).resolve().parent
        if str(radice) not in sys.path:
            sys.path.insert(0, str(radice))
        import sbk_resources as risorse

        seg = risorse.pressure().seg_ratio
        limite = getattr(risorse, "SEG_YIELD", SEG_LIMITE_SCANSIONE)
    except Exception:  # pragma: no cover - module missing: does not block the work
        return
    if seg >= limite:  # pragma: no cover
        raise MacchinaPiena(
            f"compressor segments at {seg:.0%} (limit {limite:.0%}): "
            "the index is not built now. The caller should exit with 75 and retry."
        )


def _leggi_lapide(percorso: Path, nome_file: str, archivio: str) -> Lapide | None:
    try:
        o = json.loads(percorso.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(o, dict):
        return None


    eid = nome_file
    dentro = o.get("merged_into")
    figli = o.get("split_into") or []
    if dentro:
        genere, verso = "fusione", (str(dentro),)
        quando = o.get("merged_date") or ""
        motivo = o.get("merge_reason") or o.get("merge_signal") or (o.get("merged_by") or "")
    elif figli:
        genere, verso = "scissione", tuple(str(x) for x in figli)
        quando = o.get("split_date") or ""
        motivo = o.get("split_by") or ""
    else:
        genere, verso = "nessuno", ()
        quando = o.get("merged_date") or o.get("split_date") or ""
        motivo = ""
    return Lapide(
        entity_id=eid,
        archivio=archivio,
        genere=genere,
        verso=verso,
        quando=quando,
        nome=str(o.get("canonical_name") or ""),
        motivo=str(motivo),
    )


def _firma(store: Path) -> dict:
    ""

    f: dict = {}
    for sub in ARCHIVI:
        d = store / "archive" / sub
        n = 0
        mt = 0.0
        if d.is_dir():
            for e in os.scandir(d):
                n += 1
                mt = max(mt, e.stat().st_mtime)
        f[sub] = [n, round(mt, 3)]
    radice = store / "entities"
    vivi = 0
    if radice.is_dir():
        for t in radice.iterdir():
            if t.is_dir():
                vivi += sum(1 for _ in os.scandir(t))
    f["vivi"] = vivi
    return f


def _da_cache(percorso: Path, firma: dict, store: Path) -> Indice | None:
    try:
        payload = json.loads(percorso.read_bytes())
    except (OSError, ValueError):
        return None
    if payload.get("firma") != firma:
        return None
    lapidi: dict[str, dict[str, Lapide]] = {}
    for r in payload.get("lapidi") or []:
        lap = Lapide(r[0], r[1], r[2], tuple(r[3]), r[4], r[5], r[6])
        lapidi.setdefault(lap.entity_id, {})[lap.archivio] = lap
    return Indice(
        vivi=dict(payload.get("vivi") or {}),
        lapidi=lapidi,
        da_cache=True,
        store=store,
    )




_CONDIVISO: Indice | None = None


def indice(
    store: Path | str | None = None,
    *,
    cache: Path | str | None = None,
    ricostruisci: bool = False,
) -> Indice:
    ""

    global _CONDIVISO
    if _CONDIVISO is None or ricostruisci:
        _CONDIVISO = Indice.costruisci(store, cache=cache)
    return _CONDIVISO


def risolvi(
    entity_id: str,
    *,
    store: Path | str | None = None,
    tollera_anomalie: bool = False,
) -> Risoluzione:
    ""
    return indice(store).risolvi(entity_id, tollera_anomalie=tollera_anomalie)
