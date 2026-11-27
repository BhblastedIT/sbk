"""The resolutions register: identity repairs (merges, splits, variants) that are read back before a new entity is created."""



































































































































































from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path


ARCHIVI = ("merged", "deduped", "split", "partial-resolved")


CARTELLA_REGISTRO = "resolutions"
NOME_REGISTRO = "risoluzioni.jsonl"
PERCORSO_REGISTRO = "resolutions/risoluzioni.jsonl"


PERCORSO_SPEGNIMENTO = "meta/registro-OFF"


PERCORSO_DIARIO = "resolutions/decisioni.jsonl"



TIPI = ("split", "variante", "negativo", "incerto", "positivo")












POSITIVO = "positivo"
NEGATIVO = "negativo"
INCERTO = "incerto"
NESSUN_GIUDIZIO = "nessun_giudizio"


GIUDIZI_DI_COPPIA = (POSITIVO, NEGATIVO, INCERTO)





BLOCCANTI = (NEGATIVO, INCERTO)



CONFIDENZA_MINIMA_PARZIALE = 0.9


class VoceInvalida(ValueError):
    ""





def chiave_di(nome: str, tipo_entita: str = "person") -> str:
    ""








    return f"{tipo_entita}:{(nome or '').strip().lower()}"


def id_che_nascerebbe(nome: str, tipo_entita: str = "person") -> str:
    ""

    h = hashlib.sha256(chiave_di(nome, tipo_entita).encode()).hexdigest()[:8]
    return f"{tipo_entita}_{h}"


_TITOLI = {"dr", "dott", "dott.ssa", "prof", "ing", "avv", "mr", "mrs", "ms", "sig", "sig.ra"}


def chiave_larga(nome: str, tipo_entita: str = "person") -> str:
    ""




    s = (nome or "").lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    parti = [p for p in s.split() if p.rstrip(".") not in _TITOLI]
    return f"{tipo_entita}:{' '.join(parti).strip()}"







RE_DESIGNATORE = re.compile(
    r"""(?ix)
      (?:^|[\s(,.])&\s*(?:co|figli|associati|associates|partners?|sons)\b
    | \b(?:
        s\.?p\.?a | s\.?r\.?l\.?s? | s\.?a\.?s | s\.?n\.?c | s\.?s\.?d
      | l\.?l\.?p | l\.?l\.?c | ltd | limited | inc | corp | corporation
      | gmbh | b\.?v | n\.?v | plc | oy | aps | kft
      | associati | associates | association | partners | holding | holdings
      | societa | società | sgr | spa | srl
      | studio\ legale | \&\ co
      )\b\.?
    """,
)




FORME_NUDE = {
    "co",
    "inc",
    "llc",
    "ltd",
    "limited",
    "llp",
    "srl",
    "srls",
    "spa",
    "sas",
    "snc",
    "sa",
    "gmbh",
    "ag",
    "bv",
    "nv",
    "plc",
    "oy",
    "ab",
    "aps",
    "kft",
    "sl",
    "associati",
    "associates",
    "association",
    "partners",
    "partner",
    "figli",
    "sons",
    "holding",
    "holdings",
    "group",
    "gruppo",
    "groupe",
    "company",
    "societa",
    "società",
    "corp",
    "corporation",
    "per azioni",
    "società per azioni",
    "societa per azioni",
}



QUARANTENA = (
    "chiave_morta",
    "designatore_societario",
    "figlio_forma_nuda",
    "taglio_dentro_parentesi",
    "chiave_divergente",
    "catena_non_chiude",
    "senza_origine",
    "confidenza_bassa",
)


def _sfronda(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip(" .,;:&/-«»\"'")


def porta_designatore(nome: str) -> bool:
    ""
    return bool(RE_DESIGNATORE.search(nome or ""))


def e_forma_nuda(nome: str) -> bool:
    ""
    n = _sfronda(nome)
    if not n:
        return True
    if n in {_sfronda(x) for x in FORME_NUDE}:
        return True
    primo = n.split()[0] if n.split() else ""
    return primo in {_sfronda(x) for x in FORME_NUDE}


def parentesi_spezzate(*testi: str) -> bool:
    ""
    for t in testi:
        s = t or ""
        if s.count("(") != s.count(")"):
            return True
        if s.count("«") != s.count("»"):
            return True
        if s.count('"') % 2 == 1:
            return True
    return False





@dataclass(frozen=True)
class Voce:
    ""


    tipo: str
    tipo_entita: str = "person"
    chiave: str = ""
    figli: tuple[tuple[str, str], ...] = ()
    canonico_id: str = ""
    coppia: tuple[str, str] = ()
    chiavi: tuple[str, ...] = ()
    origine: str = ""
    origin_fact_ids: tuple[str, ...] = ()
    decisa_da: str = ""
    decisa_il: str = ""
    confidenza: float | None = None
    ambito: str = "globale"
    motivo: str = ""
    sospesa: bool = False
    supporto: int = 0
    chiave_larga: str = ""



    def valida(self) -> None:
        ""
        if self.tipo not in TIPI:
            raise VoceInvalida(f"unknown tipo: {self.tipo!r} (expected {TIPI})")
        if not self.origin_fact_ids:
            raise VoceInvalida(
                f"entry {self.tipo}/{self.chiave or self.coppia!r} without origin_fact_ids: "
                "a non-recomputable entry is the next stale rule (guard 1)"
            )
        if self.tipo == "split":
            if not self.chiave:
                raise VoceInvalida("split entry without chiave")
            if not self.figli:
                raise VoceInvalida(f"split entry {self.chiave!r} without children: it resolves nothing")
        elif self.tipo == "variante":
            if not self.chiave:
                raise VoceInvalida("variant entry without chiave")
            if not self.canonico_id:
                raise VoceInvalida(f"variant entry {self.chiave!r} without canonico_id")
        elif self.tipo in GIUDIZI_DI_COPPIA and len(self.coppia) != 2:
            raise VoceInvalida(f"entry {self.tipo} without a pair of two ids")

    @property
    def id_bloccato(self) -> str:
        ""
        nome = self.chiave.split(":", 1)[1] if ":" in self.chiave else self.chiave
        return id_che_nascerebbe(nome, self.tipo_entita)

    @property
    def figli_id(self) -> tuple[str, ...]:
        return tuple(i for _, i in self.figli)

    @property
    def bersagli(self) -> tuple[str, ...]:
        ""
        if self.tipo == "split":
            return self.figli_id
        if self.tipo == "variante":
            return (self.canonico_id,) if self.canonico_id else ()
        return self.coppia



    def come_dict(self) -> dict:
        d: dict = {"tipo": self.tipo, "tipo_entita": self.tipo_entita}
        if self.chiave:
            d["chiave"] = self.chiave
        if self.figli:
            d["figli"] = [{"nome": n, "id": i} for n, i in self.figli]
        if self.canonico_id:
            d["canonico_id"] = self.canonico_id
        if self.coppia:
            d["coppia"] = list(self.coppia)
        if self.chiavi:
            d["chiavi"] = list(self.chiavi)
        d["origine"] = self.origine
        d["origin_fact_ids"] = list(self.origin_fact_ids)
        d["decisa_da"] = self.decisa_da
        d["decisa_il"] = self.decisa_il
        if self.confidenza is not None:
            d["confidenza"] = self.confidenza
        d["ambito"] = self.ambito
        if self.motivo:
            d["motivo"] = self.motivo
        d["sospesa"] = self.sospesa
        d["supporto"] = self.supporto
        if self.chiave_larga:
            d["chiave_larga"] = self.chiave_larga
        return d

    @classmethod
    def da_dict(cls, d: dict) -> Voce:
        figli = tuple(
            (str(f.get("nome", "")), str(f.get("id", ""))) for f in (d.get("figli") or [])
        )
        return cls(
            tipo=str(d.get("tipo", "")),
            tipo_entita=str(d.get("tipo_entita", "person")),
            chiave=str(d.get("chiave", "")),
            figli=figli,
            canonico_id=str(d.get("canonico_id", "")),
            coppia=tuple(d.get("coppia") or ()),  # type: ignore[arg-type]
            chiavi=tuple(d.get("chiavi") or ()),
            origine=str(d.get("origine", "")),
            origin_fact_ids=tuple(d.get("origin_fact_ids") or ()),
            decisa_da=str(d.get("decisa_da", "")),
            decisa_il=str(d.get("decisa_il", "")),
            confidenza=d.get("confidenza"),
            ambito=str(d.get("ambito", "globale")),
            motivo=str(d.get("motivo", "")),
            sospesa=bool(d.get("sospesa", False)),
            supporto=int(d.get("supporto", 0) or 0),
            chiave_larga=str(d.get("chiave_larga", "")),
        )


def _chiave_negativo(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def combina(g1: str, g2: str) -> str:
    ""















    if NEGATIVO in (g1, g2):
        return NEGATIVO
    if g1 == NESSUN_GIUDIZIO:
        return g2
    if g2 == NESSUN_GIUDIZIO:
        return g1
    if g1 == g2 == POSITIVO:
        return POSITIVO
    return INCERTO





@dataclass
class Registro:
    ""


    voci: dict[str, Voce] = field(default_factory=dict)


    giudizi: dict[tuple[str, str], Voce] = field(default_factory=dict)
    larghe: dict[str, str] = field(default_factory=dict)
    caricato_in: float = 0.0
    percorso: Path | None = None
    righe_lette: int = 0



    @classmethod
    def carica(cls, percorso: Path | str) -> Registro:
        ""

        t0 = time.perf_counter()
        p = Path(percorso)
        r = cls(percorso=p)
        if not p.exists():
            r.caricato_in = time.perf_counter() - t0
            return r
        with p.open(encoding="utf-8") as fh:
            for riga in fh:
                riga = riga.strip()
                if not riga:
                    continue
                r.righe_lette += 1
                try:
                    v = Voce.da_dict(json.loads(riga))
                except (ValueError, TypeError):
                    continue
                r._monta(v)
        r.caricato_in = time.perf_counter() - t0
        return r

    @property
    def negativi(self) -> dict[tuple[str, str], Voce]:
        ""

        return {k: v for k, v in self.giudizi.items() if v.tipo == NEGATIVO}

    def _monta(self, v: Voce) -> None:
        if v.tipo in GIUDIZI_DI_COPPIA:
            if len(v.coppia) == 2:
                self.giudizi[_chiave_negativo(*v.coppia)] = v
            return
        if not v.chiave:
            return
        self.voci[v.chiave] = v
        if v.chiave_larga and v.chiave_larga != v.chiave:
            self.larghe.setdefault(v.chiave_larga, v.chiave)



    def scrivi(self, voce: Voce, percorso: Path | str | None = None) -> Voce:
        ""




        voce.valida()
        dest = Path(percorso) if percorso else self.percorso
        if dest is None:
            raise VoceInvalida("no destination: the registry path is explicit")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(voce.come_dict(), ensure_ascii=False) + "\n")
        self._monta(voce)
        self.righe_lette += 1
        if self.percorso is None:
            self.percorso = dest
        return voce



    def consulta(self, nome: str, tipo_entita: str = "person") -> Voce | None:
        ""




        v = self.voci.get(chiave_di(nome, tipo_entita))
        if v is None or v.sospesa:
            return None
        return v

    def consulta_larga(self, nome: str, tipo_entita: str = "person") -> Voce | None:
        ""
        esatta = self.larghe.get(chiave_larga(nome, tipo_entita))
        if not esatta:
            return None
        v = self.voci.get(esatta)
        return None if (v is None or v.sospesa) else v

    def vietato_fondere(self, a: str, b: str) -> Voce | None:
        ""




        v = self.giudizi.get(_chiave_negativo(a, b))
        return None if (v is None or v.sospesa or v.tipo != NEGATIVO) else v

    def giudizio(self, a: str, b: str) -> str:
        ""












        v = self.giudizi.get(_chiave_negativo(a, b))
        if v is None or v.sospesa:
            return NESSUN_GIUDIZIO
        return v.tipo

    def blocca_fusione(self, a: str, b: str) -> Voce | None:
        ""
        v = self.giudizi.get(_chiave_negativo(a, b))
        return None if (v is None or v.sospesa or v.tipo not in BLOCCANTI) else v

    def __len__(self) -> int:
        return len(self.voci) + len(self.giudizi)





@dataclass
class Costruzione:
    ""

    voci: list[Voce] = field(default_factory=list)
    quarantena: list[dict] = field(default_factory=list)
    letti: int = 0
    durata: float = 0.0
    lapidi_per_chiave: int = 0
    collisioni_arbitrate: int = 0

    @property
    def per_motivo(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for q in self.quarantena:
            c[q["motivo"]] = c.get(q["motivo"], 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    def rapporto(self) -> dict:
        return {
            "file_letti": self.letti,
            "voci_nel_seme": len(self.voci),
            "in_quarantena": len(self.quarantena),
            "per_motivo": self.per_motivo,
            "per_tipo": {
                t: sum(1 for v in self.voci if v.tipo == t) for t in ("split", "variante")
            },
            "lapidi_collassate": self.lapidi_per_chiave,
            "collisioni_arbitrate": self.collisioni_arbitrate,
            "durata_s": round(self.durata, 3),
        }


def _leggi_archivio(store: Path) -> list[dict]:
    ""
    fuori = []
    for sub in ARCHIVI:
        d = store / "archive" / sub
        if not d.is_dir():
            continue
        for f in os.scandir(d):
            if not f.name.endswith(".json"):
                continue
            try:
                o = json.loads(Path(f.path).read_bytes())
            except (OSError, ValueError):
                fuori.append({"eid": f.name[:-5], "arch": sub, "illeggibile": True})
                continue
            if not isinstance(o, dict):
                continue
            facts = o.get("facts") or []
            fuori.append(
                {
                    "eid": f.name[:-5],
                    "arch": sub,
                    "nome": str(o.get("canonical_name") or ""),
                    "tipo_entita": str(o.get("entity_type") or "person"),
                    "merged_into": str(o.get("merged_into") or ""),
                    "split_into": [str(x) for x in (o.get("split_into") or [])],
                    "split_candidates": [str(x) for x in (o.get("split_candidates") or [])],
                    "quando": str(o.get("merged_date") or o.get("split_date") or ""),
                    "by": str(o.get("merged_by") or o.get("split_by") or ""),
                    "motivo": str(o.get("merge_reason") or o.get("merge_signal") or ""),
                    "conf": o.get("merge_confidence"),
                    "fact_ids": [
                        str(x.get("fact_id"))
                        for x in facts
                        if isinstance(x, dict) and x.get("fact_id")
                    ],
                }
            )
    return fuori


def _vivi(store: Path) -> dict[str, str]:
    ""

    vivi: dict[str, str] = {}
    radice = store / "entities"
    if not radice.is_dir():
        return vivi
    for tipo in radice.iterdir():
        if tipo.is_dir():
            for f in os.scandir(tipo):
                if f.name.endswith(".json"):
                    vivi[f.name[:-5]] = tipo.name
    return vivi


def costruisci_da_archivio(
    store: Path | str,
    *,
    bonifica: bool = True,
    segui_catene: bool = True,
) -> Costruzione:
    ""




    t0 = time.perf_counter()
    store = Path(store)
    righe = _leggi_archivio(store)
    vivi = _vivi(store)
    out = Costruzione(letti=len(righe))



    generi: dict[str, set[str]] = {}
    for r in righe:
        if r.get("illeggibile") or not r.get("nome") or r["nome"] == r["eid"]:
            continue
        g = "scissione" if r["split_into"] else ("fusione" if r["merged_into"] else "nessuno")
        generi.setdefault(chiave_di(r["nome"], r.get("tipo_entita") or "person"), set()).add(g)
    divergenti = {k for k, v in generi.items() if len(v) > 1}

    indice = None
    if segui_catene:
        try:
            import knowledge_resolve  # type: ignore[import-not-found]

            indice = knowledge_resolve.Indice.costruisci(store, controlla_pressione=False)
        except Exception:  # pragma: no cover - the seed is built anyway
            indice = None

    def scarta(r: dict, motivo: str, extra: str = "") -> None:
        out.quarantena.append(
            {
                "entity_id": r.get("eid", ""),
                "archivio": r.get("arch", ""),
                "nome": r.get("nome", ""),
                "motivo": motivo,
                "dettaglio": extra,
                "figli": r.get("split_candidates") or [],
            }
        )

    def vivo_o_erede(eid: str) -> str:
        ""
        if eid in vivi:
            return eid
        if indice is None:
            return ""
        try:
            ris = indice.risolvi(eid, tollera_anomalie=True)
        except Exception:  # pragma: no cover
            return ""
        return ris.destinazione or ""

    for r in righe:
        if r.get("illeggibile"):
            scarta(r, "senza_origine", "unreadable file")
            continue
        nome = r["nome"]
        tipo_ent = r.get("tipo_entita") or "person"
        ch = chiave_di(nome, tipo_ent)

        if not nome or nome == r["eid"]:
            scarta(r, "chiave_morta", r.get("motivo", "")[:80])
            continue
        if not r["fact_ids"]:
            scarta(r, "senza_origine", "no fact_id in the archive")
            continue

        e_split = bool(r["split_into"])
        if bonifica:
            if ch in divergenti:
                scarta(r, "chiave_divergente", "same name, split and merge in different archives")
                continue
            if porta_designatore(nome):
                scarta(r, "designatore_societario", nome[:80])
                continue
            if e_split and any(e_forma_nuda(c) for c in r["split_candidates"]):
                scarta(r, "figlio_forma_nuda", " | ".join(r["split_candidates"])[:80])
                continue
            if e_split and parentesi_spezzate(nome, *r["split_candidates"]):
                scarta(r, "taglio_dentro_parentesi", " | ".join(r["split_candidates"])[:80])
                continue

        if e_split:
            nomi = list(r["split_candidates"]) + [""] * len(r["split_into"])
            figli: list[tuple[str, str]] = []
            rotta = False
            for i, fid in enumerate(r["split_into"]):
                erede = vivo_o_erede(fid)
                if not erede:
                    rotta = True
                    break
                figli.append((nomi[i], erede))
            if rotta or not figli:
                scarta(r, "catena_non_chiude", " ".join(r["split_into"])[:80])
                continue
            voce = Voce(
                tipo="split",
                tipo_entita=tipo_ent,
                chiave=ch,
                figli=tuple(figli),
                origine=f"archive/{r['arch']}/{r['eid']}.json",
                origin_fact_ids=tuple(r["fact_ids"]),
                decisa_da=r["by"] or f"l4/{r['arch']}",
                decisa_il=r["quando"],
                chiave_larga=chiave_larga(nome, tipo_ent),
            )
        elif r["merged_into"]:
            conf = r.get("conf")
            ambito = "globale"
            if r["arch"] == "partial-resolved":
                if bonifica and (conf is None or float(conf) < CONFIDENZA_MINIMA_PARZIALE):
                    scarta(r, "confidenza_bassa", str(conf))
                    continue
                ambito = "parziale"
            erede = vivo_o_erede(r["merged_into"])
            if not erede:
                scarta(r, "catena_non_chiude", r["merged_into"])
                continue
            voce = Voce(
                tipo="variante",
                tipo_entita=tipo_ent,
                chiave=ch,
                canonico_id=erede,
                origine=f"archive/{r['arch']}/{r['eid']}.json",
                origin_fact_ids=tuple(r["fact_ids"]),
                decisa_da=r["by"] or f"l4/{r['arch']}",
                decisa_il=r["quando"],
                confidenza=float(conf) if conf is not None else None,
                ambito=ambito,
                motivo=r.get("motivo", "")[:120],
                chiave_larga=chiave_larga(nome, tipo_ent),
            )
        else:
            scarta(r, "senza_origine", "tombstone without a destination")
            continue

        try:
            voce.valida()
        except VoceInvalida as e:
            scarta(r, "senza_origine", str(e)[:80])
            continue
        out.voci.append(voce)

    out.voci = _collassa_per_chiave(out)
    out.durata = time.perf_counter() - t0
    return out


def _collassa_per_chiave(out: Costruzione) -> list[Voce]:
    ""















    per_chiave: dict[str, list[Voce]] = {}
    for v in out.voci:
        per_chiave.setdefault(v.chiave, []).append(v)

    tenute: list[Voce] = []
    for chiave, gruppo in per_chiave.items():
        if len(gruppo) == 1:
            tenute.append(gruppo[0])
            continue
        out.lapidi_per_chiave += len(gruppo) - 1
        destinazioni = {v.bersagli for v in gruppo}
        ordinate = sorted(gruppo, key=lambda v: v.decisa_il, reverse=True)
        if len(destinazioni) == 1:
            tenute.append(ordinate[0])
            continue
        out.collisioni_arbitrate += 1
        pari = [v for v in ordinate if v.decisa_il == ordinate[0].decisa_il]
        if len({v.bersagli for v in pari}) > 1:
            for v in gruppo:
                out.quarantena.append(
                    {
                        "entity_id": v.origine.split("/")[-1][:-5],
                        "archivio": v.origine.split("/")[1] if "/" in v.origine else "",
                        "nome": chiave,
                        "motivo": "collisione_indecidibile",
                        "dettaglio": f"{len(pari)} lapidi allo stesso istante {v.decisa_il}",
                        "figli": [n for n, _ in v.figli],
                    }
                )
            continue
        vinta = replace(
            ordinate[0],
            motivo=(ordinate[0].motivo + " · " if ordinate[0].motivo else "")
            + f"arbitrated among {len(gruppo)} tombstones: the most recent wins ({ordinate[0].decisa_il[:10]})",
        )
        tenute.append(vinta)
    return tenute


def materializza(costruzione: Costruzione, percorso: Path | str) -> Path:
    ""

    p = Path(percorso)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for v in costruzione.voci:
            fh.write(json.dumps(v.come_dict(), ensure_ascii=False) + "\n")
    return p





def _fatti_vivi_di(store: Path, eid: str, vivi: dict[str, str]) -> tuple[set[str], set[str]]:
    ""





    presenti: set[str] = set()
    ritrattati: set[str] = set()
    cartella = vivi.get(eid)
    if not cartella:
        return presenti, ritrattati
    p = store / "entities" / cartella / f"{eid}.json"
    try:
        o = json.loads(p.read_bytes())
    except (OSError, ValueError):
        return presenti, ritrattati
    for f in o.get("facts") or []:
        if not isinstance(f, dict):
            continue
        ids = [f.get("fact_id")]
        ids += list(f.get("merged_fact_ids") or [])
        for obs in f.get("observations") or []:
            if isinstance(obs, dict) and obs.get("fact_id"):
                ids.append(obs["fact_id"])
        morto = bool(f.get("superseded_by") or f.get("expired_at") or f.get("valid_to"))
        for i in ids:
            if not i:
                continue
            presenti.add(str(i))
            if morto:
                ritrattati.add(str(i))
    return presenti, ritrattati


@dataclass
class Rivalutazione:
    ""


    esaminate: int = 0
    reggono: int = 0
    decadute: list[dict] = field(default_factory=list)
    gia_sospese: int = 0
    durata: float = 0.0

    def rapporto(self) -> dict:
        return {
            "esaminate": self.esaminate,
            "reggono": self.reggono,
            "decadute": len(self.decadute),
            "gia_sospese": self.gia_sospese,
            "motivi": {
                m: sum(1 for d in self.decadute if d["motivo"] == m)
                for m in sorted({d["motivo"] for d in self.decadute})
            },
            "durata_s": round(self.durata, 3),
        }


def rivaluta(
    registro: Registro,
    store: Path | str,
    *,
    scrivi_su: Path | str | None = None,
) -> Rivalutazione:
    ""









    t0 = time.perf_counter()
    store = Path(store)
    vivi = _vivi(store)
    cache: dict[str, tuple[set[str], set[str]]] = {}
    out = Rivalutazione()





    tutte = list(registro.voci.values()) + list(registro.giudizi.values())
    for v in tutte:
        out.esaminate += 1
        if v.sospesa:
            out.gia_sospese += 1
            continue
        presenti: set[str] = set()
        ritrattati: set[str] = set()
        for b in v.bersagli:
            if b not in cache:
                cache[b] = _fatti_vivi_di(store, b, vivi)
            p, r = cache[b]
            presenti |= p
            ritrattati |= r
        origini = set(v.origin_fact_ids)
        sopravvissuti = origini & presenti
        vivi_non_ritrattati = sopravvissuti - ritrattati
        if not sopravvissuti:
            motivo = "origine_svanita"
        elif not vivi_non_ritrattati:
            motivo = "origine_ritrattata"
        else:
            out.reggono += 1
            continue
        out.decadute.append(
            {
                "chiave": v.chiave or "|".join(v.coppia),
                "tipo": v.tipo,
                "motivo": motivo,
                "origin_fact_ids": list(v.origin_fact_ids)[:10],
                "bersagli": list(v.bersagli),
            }
        )
        spenta = replace(v, sospesa=True, motivo=f"lapsed: {motivo}")
        if scrivi_su:
            registro.scrivi(spenta, scrivi_su)
        else:
            registro._monta(spenta)

    out.durata = time.perf_counter() - t0
    return out





@dataclass(frozen=True)
class Decisione:
    ""


    nome: str
    chiave: str
    azione: str
    avrebbe: str
    entity_id: str = ""
    voce: Voce | None = None
    motivo: str = ""

    def come_riga(self, run_id: str = "") -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            "run_id": run_id,
            "nome": self.nome,
            "chiave": self.chiave,
            "azione": self.azione,
            "avrebbe": self.avrebbe,
            "entity_id": self.entity_id,
            "id_evitato": self.voce.id_bloccato if self.voce else "",
            "tipo_voce": self.voce.tipo if self.voce else "",
            "risoluzione": list(self.voce.bersagli) if self.voce else [],
            "origine": self.voce.origine if self.voce else "",
            "motivo": self.motivo,
        }


class Sentinella:
    ""






    def __init__(
        self,
        registro: Registro,
        *,
        modalita: str = "ombra",
        store: Path | str | None = None,
        diario: Path | str | None = None,
        run_id: str = "",
    ):
        if modalita not in ("ombra", "blocco"):
            raise ValueError(f"unknown mode: {modalita!r}")
        self.registro = registro
        self.modalita = modalita
        self.store = Path(store) if store else None
        self.diario = Path(diario) if diario else None
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017
        self.conteggi: dict[str, int] = {
            "consultazioni": 0,
            "hit_split": 0,
            "hit_variante": 0,
            "hit_larghi": 0,
            "reindirizzati": 0,
            "non_coniati": 0,
            "spento": 0,
        }
        self.supporto: dict[str, int] = {}
        self._interruttore = (self.store / PERCORSO_SPEGNIMENTO) if self.store else None
        self._vivi_cache: dict[str, str] | None = None
        self._email_cache: dict[str, set[str]] = {}



    @property
    def spento(self) -> bool:
        ""
        return bool(self._interruttore and self._interruttore.exists())



    def al_conio(
        self,
        nome: str,
        *,
        tipo_entita: str = "person",
        email: str | None = None,
    ) -> Decisione:
        ""




        self.conteggi["consultazioni"] += 1
        ch = chiave_di(nome, tipo_entita)
        id_nudo = id_che_nascerebbe(nome, tipo_entita)
        voce = self.registro.consulta(nome, tipo_entita)

        if voce is None:
            if self.registro.consulta_larga(nome, tipo_entita) is not None:
                self.conteggi["hit_larghi"] += 1
            return Decisione(nome, ch, "conia", "conia", id_nudo, None, "no entry")

        self.supporto[ch] = self.supporto.get(ch, 0) + 1
        if voce.tipo == "split":
            self.conteggi["hit_split"] += 1
            scelto = self._figlio_per_email(voce, email)
            if scelto:
                avrebbe, motivo, eid = "reindirizza", "split: child by email", scelto
            else:
                avrebbe, motivo, eid = (
                    "non_coniare",
                    f"split already decided into {len(voce.figli)} children: the fact goes to the queue",
                    "",
                )
        else:
            self.conteggi["hit_variante"] += 1
            avrebbe, motivo, eid = "reindirizza", "variant of a canonical", voce.canonico_id

        if self.spento:
            self.conteggi["spento"] += 1
            d = Decisione(nome, ch, "conia", avrebbe, id_nudo, voce, f"{motivo} · KILL-SWITCH")
            self._diario(d)
            return d

        if self.modalita == "ombra":
            d = Decisione(nome, ch, "conia", avrebbe, id_nudo, voce, motivo)
            self._diario(d)
            return d

        if avrebbe == "reindirizza":
            self.conteggi["reindirizzati"] += 1
        else:
            self.conteggi["non_coniati"] += 1
        d = Decisione(nome, ch, avrebbe, avrebbe, eid, voce, motivo)
        self._diario(d)
        return d

    def _figlio_per_email(self, voce: Voce, email: str | None) -> str:
        ""






        if not email or not self.store:
            return ""
        e = email.strip().lower()
        if self._vivi_cache is None:
            self._vivi_cache = _vivi(self.store)
        vivi = self._vivi_cache
        for _nome, fid in voce.figli:
            if fid not in self._email_cache:
                self._email_cache[fid] = self._email_di(fid, vivi)
            if e in self._email_cache[fid]:
                return fid
        return ""

    def _email_di(self, fid: str, vivi: dict[str, str]) -> set[str]:
        cartella = vivi.get(fid)
        if not cartella:
            return set()
        try:
            o = json.loads((self.store / "entities" / cartella / f"{fid}.json").read_bytes())
        except (OSError, ValueError):
            return set()
        fuori = set()
        for f in o.get("facts") or []:
            if isinstance(f, dict) and f.get("attribute") in ("identity.email", "contact.email"):
                fuori.add(str(f.get("value", "")).strip().lower())
        return fuori



    def _diario(self, d: Decisione) -> None:
        if not self.diario or d.voce is None:
            return
        self.diario.parent.mkdir(parents=True, exist_ok=True)
        with self.diario.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(d.come_riga(self.run_id), ensure_ascii=False) + "\n")

    def stats(self) -> dict:
        return {
            "modalita": self.modalita,
            "run_id": self.run_id,
            "voci_in_registro": len(self.registro),
            **self.conteggi,
            "chiavi_con_supporto": len(self.supporto),
        }





def voci_mancanti(store: Path | str, registro: Registro) -> list[str]:
    ""







    store = Path(store)
    presenti = {v.origine for v in registro.voci.values() if v.origine}
    mancanti = []
    for sub in ARCHIVI:
        d = store / "archive" / sub
        if not d.is_dir():
            continue
        for f in os.scandir(d):
            if f.name.endswith(".json"):
                rel = f"archive/{sub}/{f.name}"
                if rel not in presenti:
                    mancanti.append(rel)
    return sorted(mancanti)





def _store_predefinito() -> Path:
    return (
        Path(os.environ.get("SBK_DATA_ROOT") or Path.home() / ".sbk-data").expanduser()
        / "knowledge"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--store",
        default=None,
        help="root of the knowledge store (default: the live one, READ ONLY)",
    )
    ap.add_argument(
        "--costruisci", metavar="OUT", help="writes the cleaned seed to OUT (explicit path)"
    )
    ap.add_argument(
        "--senza-bonifica",
        action="store_true",
        help="⚠️ raw seed: only useful to measure the poison",
    )
    ap.add_argument(
        "--rapporto", metavar="OUT", help="writes the cleaning report (JSON) to OUT"
    )
    ap.add_argument("--quarantena", metavar="OUT", help="writes the human queue (JSONL) to OUT")
    ap.add_argument(
        "--rivaluta", metavar="JSONL", help="re-evaluates the entries of an already materialized registry"
    )
    ap.add_argument(
        "--misura",
        action="store_true",
        help="cost of the seed, of loading and of a lookup",
    )
    a = ap.parse_args()

    store = Path(a.store) if a.store else _store_predefinito()

    if a.misura:
        c = costruisci_da_archivio(store)
        print(f"seed from archives   : {c.durata:6.2f} s  ({c.letti} files → {len(c.voci)} entries)")
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = materializza(c, Path(td) / NOME_REGISTRO)
            kb = p.stat().st_size / 1e6
            t0 = time.perf_counter()
            r = Registro.carica(p)
            dt = time.perf_counter() - t0
            print(f"load jsonl ({kb:.1f} MB): {dt * 1000:6.1f} ms ({len(r)} entries in dict)")
            chiavi = list(r.voci)[:1000] or ["person:x"]
            t0 = time.perf_counter()
            n = 0
            for _ in range(100):
                for k in chiavi:
                    nome = k.split(":", 1)[1]
                    r.consulta(nome)
                    n += 1
            dt = time.perf_counter() - t0
            print(f"one lookup           : {dt / n * 1e9:6.0f} ns  ({n} lookups)")
        return 0

    if a.rivaluta:
        reg = Registro.carica(a.rivaluta)
        riv = rivaluta(reg, store)
        print(json.dumps(riv.rapporto(), indent=2, ensure_ascii=False))
        return 0

    c = costruisci_da_archivio(store, bonifica=not a.senza_bonifica)
    print(json.dumps(c.rapporto(), indent=2, ensure_ascii=False))
    if a.costruisci:
        p = materializza(c, a.costruisci)
        print(f"seed written: {p} ({p.stat().st_size / 1e6:.1f} MB)")
    if a.rapporto:
        Path(a.rapporto).write_text(json.dumps(c.rapporto(), indent=2, ensure_ascii=False))
    if a.quarantena:
        Path(a.quarantena).parent.mkdir(parents=True, exist_ok=True)
        with Path(a.quarantena).open("w", encoding="utf-8") as fh:
            for q in c.quarantena:
                fh.write(json.dumps(q, ensure_ascii=False) + "\n")
        print(f"human queue: {a.quarantena} ({len(c.quarantena)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
