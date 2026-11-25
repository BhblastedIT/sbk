#!/usr/bin/env python3
""






















from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd
from knowledge_schema import (
    ATTR_ATTIO_RECORD_ID,
    ATTR_CLASSE,
    CLASSE_PSEUDO,
    CLASSE_SECONDA,
    EntityProfile,
    Fact,
    FactObservation,
    FactSource,
    _now_iso,
    compute_confidence,
    dict_to_profile,
    e_pseudo_identita,
    e_seconda_classe,
    ensure_knowledge_dirs,
    fact_to_dict,
    generate_entity_id,
    generate_fact_id,
    id_seconda_classe,
    nome_discriminato,
    profile_to_dict,
)
from pipeline_decorator import pipeline_step
from xs_l2_incremento import CONTATORI as _INC
from xs_l2_incremento import (
    Archivio,
    RegistroVivi,
    Watermark,
    azzera_contatori,
    id_da_riga,
    puo_avanzare,
    redirige_al_conio,
)
from xs_l2_incremento import riga_di_log as _inc_riga_di_log
from xs_l2_incremento import stats as _inc_stats

from sbk_config import (
    ATTIO_PROCESSED_DIR,
    ATTIO_SECONDA_CLASSE_PARQUET,
    DATA_ROOT,
    ENRICHED_DIR,
    ENV_ATTIO_SECONDA_CLASSE,
    KNOWLEDGE_ENTITIES_DIR,
    KNOWLEDGE_FACTS_DIR,
    KNOWLEDGE_META_DIR,
    PERSONIO_PROCESSED_DIR,
    PLAUD_PROCESSED_DIR,
    acquire_pid_lock,
    attio_seconda_classe_attiva,
    release_pid_lock,
    safe_write_json,
    safe_write_text,
)




ATTIO_SECONDA_CLASSE_DIR = ATTIO_PROCESSED_DIR

log = logging.getLogger("sbk.knowledge-extract")



_PLAUD_QUALITY: dict[str, float] | None = None


def _load_plaud_quality() -> dict[str, float]:
    ""
    global _PLAUD_QUALITY
    if _PLAUD_QUALITY is not None:
        return _PLAUD_QUALITY
    try:
        from plaud_quality import load_quality_index

        _PLAUD_QUALITY = load_quality_index(PLAUD_PROCESSED_DIR)
        if _PLAUD_QUALITY:
            log.info("Plaud quality index: %d transcripts loaded", len(_PLAUD_QUALITY))
        else:
            log.info("Plaud quality index: empty or not found — using default scores")
            _PLAUD_QUALITY = {}
    except Exception as e:
        log.warning("Failed to load plaud quality index: %s", e)
        _PLAUD_QUALITY = {}
    return _PLAUD_QUALITY


def _plaud_quality_for(source_id: str) -> float:
    ""
    qi = _load_plaud_quality()
    return qi.get(source_id, 0.5)




_PEOPLE_UNIVERSE: pd.DataFrame | None = None








PLAUD_UNVERIFIED_CAP = 0.55


@lru_cache(maxsize=8192)
def _plaud_verified(nome: str) -> bool:
    ""
    if not nome:
        return False
    try:
        from tools.knowledge_aliases import canonical

        return canonical(nome) is not None
    except Exception:
        return False


def _load_people_universe() -> pd.DataFrame | None:
    ""
    global _PEOPLE_UNIVERSE
    if _PEOPLE_UNIVERSE is not None:
        return _PEOPLE_UNIVERSE
    pu_path = ENRICHED_DIR / "people-universe.parquet"
    if not pu_path.exists():
        log.warning("people-universe.parquet not found — entity IDs will be generated from names")
        return None
    _PEOPLE_UNIVERSE = pd.read_parquet(pu_path)
    log.info("Loaded people-universe: %d entries", len(_PEOPLE_UNIVERSE))
    return _PEOPLE_UNIVERSE









_VIVI: RegistroVivi | None = None
_ARCHIVIO: Archivio | None = None
_WATERMARK: Watermark | None = None


def _get_vivi() -> RegistroVivi:
    global _VIVI
    if _VIVI is None:
        _VIVI = RegistroVivi()
    return _VIVI


def _get_archivio() -> Archivio:
    global _ARCHIVIO
    if _ARCHIVIO is None:
        _ARCHIVIO = Archivio(_get_vivi())
    return _ARCHIVIO


def _get_watermark() -> Watermark:
    global _WATERMARK
    if _WATERMARK is None:
        _WATERMARK = Watermark()
    return _WATERMARK


def _reset_incremento() -> None:
    ""





    global _VIVI, _ARCHIVIO, _WATERMARK
    _VIVI = None
    _ARCHIVIO = None
    _WATERMARK = None
    _RIFIUTI_AL_CONIO.clear()
    azzera_contatori()


_DEDUP_INDEX = None


def _get_dedup_index():
    ""
    global _DEDUP_INDEX
    if _DEDUP_INDEX is None:
        try:
            from entity_dedup_index import EntityDedupIndex






            mod = _sb_persone_mod()
            _DEDUP_INDEX = EntityDedupIndex(
                escludi_valore=(mod.e_casella if mod else None),
            )
            log.info("L4-00 pre-creation guard: loaded")
        except Exception as e:
            log.warning("L4-00 guard unavailable: %s", e)
            _DEDUP_INDEX = False
    return _DEDUP_INDEX




















_SENTINELLA = None


def _get_sentinella():
    ""





    global _SENTINELLA
    if _SENTINELLA is None:
        try:
            import registro_risoluzioni as _rr

            base = KNOWLEDGE_ENTITIES_DIR.parent



            if (base / "resolutions/risoluzioni.jsonl").exists():
                log.debug("registry found in %s", base / "resolutions")
            reg = _rr.Registro.carica(base / "resolutions/risoluzioni.jsonl")
            modalita = os.environ.get("SBK_REGISTRO", "ombra").strip().lower()
            _SENTINELLA = _rr.Sentinella(
                reg,
                modalita=modalita if modalita in ("ombra", "blocco") else "ombra",
                store=base,
                diario=base / "resolutions/decisioni.jsonl",
            )
            log.info(
                "resolution registry: %d entries, mode %s",
                len(reg),
                _SENTINELLA.modalita,
            )
        except Exception as e:  # pragma: no cover - the registry does not block a run
            log.warning("resolution registry unavailable: %s", e)
            _SENTINELLA = False
    return _SENTINELLA

















_SENTINELLA_IGNOTO = None


def _get_sentinella_ignoto():
    ""






    global _SENTINELLA_IGNOTO
    if _SENTINELLA_IGNOTO is None:
        try:
            import ignoto as _ig

            noti = frozenset()
            mod = _sb_persone_mod()
            if mod:
                noti = mod.nomi_di_organizzazione()
            base = KNOWLEDGE_ENTITIES_DIR.parent
            modalita = os.environ.get("SBK_IGNOTO", "ombra").strip().lower()
            _SENTINELLA_IGNOTO = _ig.Sentinella(
                modalita=modalita if modalita in ("ombra", "blocco") else "ombra",
                store=base,


                diario=base / "resolutions/ignoti.jsonl",
                noti=noti,
            )
            log.info(
                "unknown: mode %s, %d organization names as counter-evidence",
                _SENTINELLA_IGNOTO.modalita,
                len(noti),
            )
        except Exception as e:  # pragma: no cover - never blocks a run
            log.warning("unknown recognizer unavailable: %s", e)
            _SENTINELLA_IGNOTO = False
    return _SENTINELLA_IGNOTO














_SENTINELLA_RELAZIONE = None


def _get_sentinella_relazione():
    ""





    global _SENTINELLA_RELAZIONE
    if _SENTINELLA_RELAZIONE is None:
        try:
            import relazione as _rel

            index = _get_dedup_index()
            if not index:
                _SENTINELLA_RELAZIONE = False
                return _SENTINELLA_RELAZIONE
            base = KNOWLEDGE_ENTITIES_DIR.parent
            _SENTINELLA_RELAZIONE = _rel.Sentinella(
                risolvi=index.trova_per_nome_esatto,
                ha_chiave_forte=index.ha_chiave_forte,
                modalita=_rel.modalita_da_ambiente(),
                store=base,


                diario=base / "resolutions/relazioni.jsonl",
            )
            log.info("relationship: mode %s", _SENTINELLA_RELAZIONE.modalita)
        except Exception as e:  # pragma: no cover - never blocks a run
            log.warning("separator rule unavailable: %s", e)
            _SENTINELLA_RELAZIONE = False
    return _SENTINELLA_RELAZIONE

















_DEPOSITO = None






_RIFIUTI_AL_CONIO: dict[str, dict] = {}


def _get_deposito():
    ""
    global _DEPOSITO
    if _DEPOSITO is None:
        try:
            import deposito as _dep

            _DEPOSITO = _dep.Deposito(store=KNOWLEDGE_ENTITIES_DIR.parent)
        except Exception as e:  # pragma: no cover
            log.error("deposit unavailable: %s — the guard CANNOT reject", e)
            _DEPOSITO = False
    return _DEPOSITO


def _modalita(var: str) -> str:
    ""






    m = os.environ.get(var, "ombra").strip().lower()
    return m if m in ("ombra", "blocco") else "ombra"


def _modalita_organizzazione() -> str:
    ""
    return _modalita("SBK_ORGANIZZAZIONE")


def _modalita_archivio() -> str:
    ""
    return _modalita("SBK_ARCHIVIO")


def _e_organizzazione_o_composito(name: str, email: str | None) -> tuple[str, str]:
    ""






















    nudo = (name or "").strip()
    if not nudo:
        return "", ""
    if email:
        return "", ""
    try:
        from registro_risoluzioni import porta_designatore
    except Exception:  # pragma: no cover
        return "", ""
    if porta_designatore(nudo):
        return "designatore", "the name carries a company form"
    try:
        sbp = _sb_persone_mod()
    except Exception:  # pragma: no cover
        sbp = None
    if sbp is not None:
        if nudo.lower() in {n.lower() for n in sbp.nomi_di_organizzazione()}:
            return "designatore", "it's the name of a known organization"
        if sbp.AZIENDA.search(nudo):
            return (
                "designatore",
                "the name contains a company word and carries no key of its own",
            )
    try:
        from confrontabile import giudica as _giudica_nome

        g = _giudica_nome(nudo, "person")
        if not g.ok and any(c.startswith("composito") for c in getattr(g, "codici", ())):
            return "designatore", f"names several entities ({', '.join(g.ragioni[:2])})"
    except Exception:  # pragma: no cover
        pass
    return "", ""


def _verdetto_al_conio(
    name: str,
    eid: str = "",
    *,
    email: str | None = None,
    source_file: str = "",
    record_id: str = "",
) -> str:
    ""


















    s = _get_sentinella_ignoto()
    if s:
        d = s.al_conio(
            name,
            source_file=source_file,
            record_id=record_id or eid,
            attributo="identity.name",
            entity_id=eid,
        )
        if d.azione == "non_coniare":
            _INC["conio_rifiutato_ignoto"] += 1
            id_ign = getattr(d.snak, "id", "") or ""
            log.info(
                "UNKNOWN: «%s» names no one (%s) → the facts go to the deposit (%s)",
                str(name)[:60],
                d.motivo,
                id_ign,
            )
            _RIFIUTI_AL_CONIO[id_ign] = {
                "nome": name,
                "regola": "ignoto",
                "motivo": d.motivo,
                "famiglia": getattr(d.snak, "famiglia", ""),
                "ancora": getattr(d.snak, "ancora", ""),
                "entity_id_evitato": eid,
                "source_file": source_file,
                "record_id": record_id,
            }
            return id_ign

    r = _get_sentinella_relazione()
    if r:
        d = r.al_conio(name, email=email or "", entity_id=eid)
        if d.azione == "non_coniare":
            _INC["conio_rifiutato_relazione"] += 1
            import ignoto as _ig

            id_rel = _ig.id_ignoto(
                _ig.affermazione_di(source_file, record_id or eid, "identity.name", "subject")
            )
            log.info(
                "RELATIONSHIP: «%s» = %s → not coined, the facts go to the deposit (%s)",
                str(name)[:60],
                d.giudizio.coppia if d.giudizio else "",
                id_rel,
            )
            _RIFIUTI_AL_CONIO[id_rel] = {
                "nome": name,
                "regola": "relazione",
                "motivo": d.motivo,
                "famiglia": d.giudizio.coppia if d.giudizio else "",
                "entity_id_evitato": eid,
                "source_file": source_file,
                "record_id": record_id,
            }
            return id_rel


    regola_org, motivo_org = _e_organizzazione_o_composito(name, email)
    if regola_org:
        _INC["conio_rifiutato_organizzazione"] += 1
        if _modalita_organizzazione() == "blocco":
            import ignoto as _ig

            id_org = _ig.id_ignoto(
                _ig.affermazione_di(source_file, record_id or eid, "identity.name", "subject")
            )
            log.info(
                "ORGANIZATION: «%s» %s → not coined in person/, the facts go to the deposit (%s)",
                str(name)[:60],
                motivo_org,
                id_org,
            )
            _RIFIUTI_AL_CONIO[id_org] = {
                "nome": name,
                "regola": "designatore",
                "motivo": motivo_org,
                "entity_id_evitato": eid,
                "source_file": source_file,
                "record_id": record_id,
            }
            return id_org
        log.debug("ORGANIZATION (shadow): «%s» %s", str(name)[:60], motivo_org)
    return ""


def _deposita_fatti_senza_casa(id_rifiuto: str, nome_ripiego: str, fatti: list) -> int:
    ""












    dep = _get_deposito()
    if not dep:
        return 0
    try:
        import deposito as _dep

        r = _RIFIUTI_AL_CONIO.get(id_rifiuto) or {}
        riga = _dep.Riga(
            nome=r.get("nome") or nome_ripiego or id_rifiuto,
            regola=r.get("regola") or "manuale",
            motivo=r.get("motivo")
            or "unknown id reached the write-path without going through the guard",
            fatti=[fact_to_dict(f) for f in fatti],
            famiglia=r.get("famiglia", ""),
            entity_id_evitato=r.get("entity_id_evitato", ""),
            id_ignoto=id_rifiuto,
            ancora=r.get("ancora", ""),
            source_file=r.get("source_file", ""),
            record_id=r.get("record_id", ""),
        )
        d = dep.deposita(riga)
        _INC["deposito_righe"] += 1
        _INC["deposito_fatti"] += d["n_fatti"]
        return int(d["n_fatti"])
    except Exception as e:  # pragma: no cover - must never stop a run
        log.error("deposit failed for %s (%d facts): %s", id_rifiuto, len(fatti), e)
        return 0


def _redirige_o_deposita(
    eid: str, name: str, *, source_file: str = "", record_id: str = ""
) -> tuple[str, bool]:
    ""








    vivi, arch = _get_vivi(), _get_archivio()
    era_archiviato = (not vivi.vivo(eid, "person")) and arch.vive_qui(eid)
    nuovo = redirige_al_conio(eid, vivi, arch)
    if not (era_archiviato and nuovo == eid):
        return nuovo, False
    _INC["conio_rinascita_fermata"] += 1
    if _modalita_archivio() != "blocco":
        log.debug("ARCHIVE (shadow): %s is reborn as before («%s»)", eid, str(name)[:50])
        return nuovo, False
    import ignoto as _ig

    id_arch = _ig.id_ignoto(
        _ig.affermazione_di(source_file, record_id or eid, "identity.name", "subject")
    )
    log.info(
        "ARCHIVE: %s («%s») is closed and the chain leads to no living one: "
        "not reborn, the facts go to the deposit (%s)",
        eid,
        str(name)[:50],
        id_arch,
    )
    _RIFIUTI_AL_CONIO[id_arch] = {
        "nome": name,
        "regola": "archivio",
        "motivo": f"{eid} archived, no living successor (same-sha rebirth)",
        "entity_id_evitato": eid,
        "source_file": source_file,
        "record_id": record_id,
    }
    return id_arch, True


def _resolve_person_entity_id(
    name: str,
    person_id: str | None = None,
    email: str | None = None,
    *,
    source_file: str = "",
    record_id: str = "",
) -> str:
    ""




















    eid_riga = id_da_riga(person_id, _get_vivi(), _get_archivio())
    if eid_riga:
        return eid_riga
    _INC["nome_fallback"] += 1

    index = _get_dedup_index()
    if index and index is not False:
        result = index.find_existing_entity(name, email=email)
        if result:
            entity_id, confidence, method = result
            log.debug("DEDUP HIT: '%s' -> %s (%.2f, %s)", name, entity_id, confidence, method)
            return entity_id



    sentinella = _get_sentinella()
    if sentinella:
        d = sentinella.al_conio(name, email=email)
        if d.azione == "reindirizza" and d.entity_id:
            log.info("REGISTRY: «%s» → %s (%s)", str(name)[:60], d.entity_id, d.motivo)
            return d.entity_id
        if d.azione == "non_coniare":






            _INC["conio_rifiutato_registro"] += 1
            import ignoto as _ig

            id_reg = _ig.id_ignoto(
                _ig.affermazione_di(
                    source_file,
                    record_id or generate_entity_id("person", name),
                    "identity.name",
                    "subject",
                )
            )
            log.info(
                "REGISTRY: «%s» has already been resolved to %s and no email picks: "
                "not coined, the facts go to the deposit (%s)",
                str(name)[:60],
                list(d.voce.bersagli) if d.voce else [],
                id_reg,
            )



            _RIFIUTI_AL_CONIO[id_reg] = {
                "nome": name,
                "regola": "registro",
                "motivo": d.motivo,
                "famiglia": ",".join(str(b) for b in (d.voce.bersagli if d.voce else [])),
                "entity_id_evitato": generate_entity_id("person", name),
                "source_file": source_file,
                "record_id": record_id,
            }
            return id_reg




    eid = generate_entity_id("person", name)



    eid, fermata = _redirige_o_deposita(eid, name, source_file=source_file, record_id=record_id)
    if fermata:
        return eid
    rifiuto = _verdetto_al_conio(
        name, eid, email=email, source_file=source_file, record_id=record_id
    )
    return rifiuto or eid


def _conia_persona(
    name: str,
    email: str | None = None,
    *,
    source_file: str = "",
    record_id: str = "",
) -> str:
    ""



















    sentinella = _get_sentinella()
    if sentinella:
        d = sentinella.al_conio(name, email=email)
        if d.azione == "reindirizza" and d.entity_id:
            return d.entity_id
    eid = generate_entity_id("person", name)


    eid, fermata = _redirige_o_deposita(eid, name, source_file=source_file, record_id=record_id)
    if fermata:
        return eid
    rifiuto = _verdetto_al_conio(
        name, eid, email=email, source_file=source_file, record_id=record_id
    )
    return rifiuto or eid


def e_etichetta_di_trascrizione(nome: str) -> bool:
    ""











    s = (nome or "").strip().lower()
    return bool(_SPEAKER_NOISE_RE.match(s)) or s in _SPEAKER_NOISE


def _id_pseudo_identita(etichetta: str, source_id: str) -> tuple[str, str]:
    ""












    chiave = f"{source_id}|{etichetta}".strip()
    breve = str(source_id)[:38].strip() or "ignota"
    eid = generate_entity_id("person", chiave)
    _PSEUDO_CONIATE[eid] = f"{etichetta} @ {breve}"
    return eid, _PSEUDO_CONIATE[eid]







_PSEUDO_CONIATE: dict[str, str] = {}
_PSEUDO_MARCATE: set[str] = set()


def _marchio_pseudo(eid: str, source_file: str, record_id: str):
    ""












    if eid in _PSEUDO_MARCATE:
        return None
    _PSEUDO_MARCATE.add(eid)
    return _make_fact(
        eid,
        "person",
        ATTR_CLASSE,
        CLASSE_PSEUDO,
        "conio",
        source_file,
        record_id=record_id,
        confidence=1.0,
    )
















_RICLASSIFICATI: set[str] | None = None


def _gia_organizzazione(eid: str) -> bool:
    ""
    global _RICLASSIFICATI
    if _RICLASSIFICATI is None:
        visti: set[str] = set()
        base = KNOWLEDGE_ENTITIES_DIR
        for cartella in ("organization", "org"):
            d = base / cartella
            if d.exists():
                visti |= {f.stem for f in d.glob("*.json")}
        reg = base.parent / "reclassification" / "gate0a-person-to-org.jsonl"
        if reg.exists():
            try:
                for riga in reg.read_text(encoding="utf-8").splitlines():
                    if riga.strip():
                        visti.add(json.loads(riga).get("person_id", ""))
            except (json.JSONDecodeError, OSError):  # pragma: no cover
                pass
        visti.discard("")
        _RICLASSIFICATI = visti
        log.info("known reclassified: %d ids won't return to person/", len(visti))
    return eid in _RICLASSIFICATI


def _days_since(date_str: str | None) -> float:
    ""
    if not date_str or str(date_str).strip() in ("", "NaT", "None", "nan"):
        return 0.0
    try:
        dt = pd.Timestamp(date_str)
        if pd.isna(dt):
            return 0.0
        now = pd.Timestamp.now(tz="UTC")
        if dt.tzinfo is None:
            dt = dt.tz_localize("UTC")
        return max(0.0, (now - dt).total_seconds() / 86400)
    except Exception:
        return 0.0


def _safe_str(val) -> str | None:
    ""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s in ("", "NaT", "None", "nan", "NaN"):
        return None
    return s




_SPEAKER_NOISE = frozenset(
    {
        "context",
        "meeting context",
        "the context",
        "multiple",
        "multiple participants",
        "multiple speakers",
        "participants",
        "system",
        "team",
        "group",
        "unknown",
        "unknown speaker",
        "speaker",
        "various",
        "n/a",
    }
)
_SPEAKER_NOISE_RE = re.compile(r"^(speaker|persona|participant)[\s_]*\d+$", re.IGNORECASE)

_SPEAKER_NOISE_SUBSTR = (
    "participant",
    "group chat",
    "group context",
    "both partie",
    "both speaker",
    "multiple part",
    "multiple speaker",
    "various speaker",
    "unknown speaker",
)


def _clean_speaker(val) -> str | None:
    ""
    s = _safe_str(val)
    if not s:
        return None
    sl = s.lower()
    if sl in _SPEAKER_NOISE or _SPEAKER_NOISE_RE.match(sl):
        return None
    if sl.startswith(("team ", "group ", "both ")):
        return None
    if any(sub in sl for sub in _SPEAKER_NOISE_SUBSTR):
        return None
    if re.search(r"\((speaker\s*\d+|multiple|group|team)\b", sl):
        return None
    return s


def _safe_date(val) -> str | None:
    ""
    if val is None:
        return None
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return _safe_str(val)


_FN_COMPOSITO = None


def _e_nome_povero(nome) -> int:
    ""


















    s = str(nome or "").strip()
    if not s:
        return 4
    if "@" in s:
        return 3
    if _e_composito(s):
        return 2
    if len(s.split()) < 2:
        return 1
    return 0


def _e_composito(nome) -> bool:
    ""







    global _FN_COMPOSITO
    if _FN_COMPOSITO is None:
        try:
            import importlib.util

            _p = Path(__file__).resolve().parent / "xs-l3-knows-query.py"
            _spec = importlib.util.spec_from_file_location("xs_l3_knows_query", _p)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _FN_COMPOSITO = _mod._is_group_name
        except Exception:  # noqa: BLE001
            _FN_COMPOSITO = False
    fn = _FN_COMPOSITO
    return bool(fn(str(nome or ""))) if fn else False


def _make_fact(
    entity_id: str,
    entity_type: str,
    attribute: str,
    value,
    source_type: str,
    source_file: str,
    record_id: str = "",
    valid_from: str | None = None,
    valid_to: str | None = None,
    confidence: float | None = None,
    speaker: str | None = None,
    evidence_quote: str | None = None,
    attio_record_id: str | None = None,
    attio_web_url: str | None = None,
) -> Fact:
    ""










    now = _now_iso()
    if confidence is None:
        confidence = compute_confidence(source_type, 1, 0.0)
    return Fact(














































        fact_id=generate_fact_id(),
        entity_id=entity_id,
        entity_type=entity_type,
        attribute=attribute,
        value=value,
        confidence=confidence,
        valid_from=valid_from,
        valid_to=valid_to,
        created_at=now,
        expired_at=None,
        source=FactSource(
            source_type=source_type,
            source_file=source_file,
            record_id=record_id,
            extracted_at=now,
            speaker=speaker or None,
            evidence_quote=evidence_quote or None,
            attio_record_id=attio_record_id or None,
            attio_web_url=attio_web_url or None,
        ),
    )














































# Common Personio termination types. An account may define additional
# types; load those from your user config.
CESSAZIONI_PERSONIO: tuple[str, ...] = (
    "fired",
    "employee-quit",
    "contract-expired",
    "termination-agreement",
)














_CESSAZIONI_NORM = {c.replace("-", "_"): c for c in CESSAZIONI_PERSONIO} | {
    "quit": "employee-quit",
    "agreement": "termination-agreement",
}





CESSAZIONE_ASSENTE = "unspecified"


def _cessazione(val) -> str | None:
    ""





    s = _safe_str(val)
    if not s:
        return None
    return _CESSAZIONI_NORM.get(s.strip().lower().replace("-", "_"), s.strip().lower())














_PERSONIO_ATTR: dict[str, tuple[str, bool]] = {

    "position": ("employment.current_role", True),
    "department": ("employment.department", True),
    "team": ("employment.team", True),
    "status": ("employment.status", True),
    "subcompany": ("employment.subcompany", True),
    "hire_date": ("employment.hire_date", True),
    "termination_date": ("employment.termination_date", False),
    "manager_name": ("employment.manager_name", True),
    "manager_email": ("employment.manager_email", True),
    "employment_type": ("employment.employment_type", True),

    "first_name": ("identity.first_name", False),
    "last_name": ("identity.last_name", False),


    "preferred_name": ("identity.preferred_name", False),
    "gender": ("identity.gender", False),
    "date_of_birth": ("identity.date_of_birth", False),
    "nationality": ("identity.nationality", False),
    "fiscal_code": ("identity.fiscal_code", False),
    "tax_code": ("identity.tax_code", False),
    "marital_status": ("identity.marital_status", False),
    "profile_picture": ("identity.profile_picture", False),

    "personal_email": ("contact.personal_email", False),
    "personal_phone_number": ("contact.phone", False),
    "linkedin": ("contact.linkedin_url", False),
    "address": ("contact.address", False),
    "city": ("contact.city", False),
    "postcode": ("contact.postcode", False),
    "residence_address": ("contact.residence_address", False),
    "emergency_contact_name": ("contact.emergency_name", False),
    "emergency_contact_phone_number": ("contact.emergency_phone", False),
    "emergency_contact_relationship_to_the_employee": ("contact.emergency_relationship", False),





    "business_unit": ("employment.business_unit", True),
    "office": ("employment.office", True),
    "supervisor_id": ("employment.supervisor_id", True),
    "supervisor_email": ("employment.supervisor_email", True),
    "additional_supervisor": ("employment.additional_supervisor", True),
    "department_id": ("employment.department_id", True),
    "team_id": ("employment.team_id", True),
    "subcompany_id": ("employment.subcompany_id", True),
    "office_id": ("employment.office_id", True),
    "legal_entity_id": ("employment.legal_entity_id", True),
    "international_level": ("employment.international_level", True),
    "job_family": ("employment.job_family", True),
    "occupation_type": ("employment.occupation_type", True),
    "org_visibility_scope": ("employment.org_visibility_scope", True),
    "notice_period": ("employment.notice_period", True),
    "weekly_hours": ("employment.weekly_hours", True),
    "work_schedule": ("employment.work_schedule", True),
    "holiday_calendar": ("employment.holiday_calendar", True),
    "absence_entitlement": ("employment.absence_entitlement", True),

    # Account-specific custom fields (e.g. local contract levels) are not
    # hardcoded here; load the custom-field map from your user config.

    "company_employee_id": ("employment.company_employee_id", True),

    "fix_salary": ("employment.fix_salary", True),
    "salary_interval": ("employment.salary_interval", True),
    "salary_type": ("employment.salary_type", True),
    "hourly_salary": ("employment.hourly_salary", True),
    "yearly_employment_cost": ("employment.yearly_cost", True),
    "variable_cap": ("employment.variable_cap", True),
    "variable_yes_no": ("employment.variable", True),
    "variable_compensation_1_type": ("employment.variable_type", True),
    "child_allowance": ("employment.child_allowance", True),


    "iban": ("employment.iban", True),
    "bic": ("employment.bic", True),

    "contract_end_date": ("employment.contract_end_date", False),
    "last_working_day": ("employment.last_working_day", False),
    "probation_period_end": ("employment.probation_period_end", False),
    "termination_type": ("employment.termination_type", False),
    "termination_reason": ("employment.termination_reason", False),
    "created_at": ("employment.personio_created_at", False),

    "type_of_visa": ("legal.visa_type", True),
    "visa_expiry_date": ("legal.visa_expiry", False),

    "last_medical_check": ("employment.last_medical_check", False),
    "next_health_and_safety_course": ("employment.next_health_safety_course", False),
}







_PERSONIO_ALIAS: dict[str, str] = {
    "last_day_of_work": "last_working_day",
    "probation_end_date": "probation_period_end",
    "name_preferred": "preferred_name",
    "workplace": "office",
    "fixed_salary": "fix_salary",
    "fix_salary_interval": "salary_interval",
    "contract_ends": "contract_end_date",
    "weekly_working_hours": "weekly_hours",
    "public_holidays": "holiday_calendar",
    "last_modified_at": "last_modified",
    "next_health_safety_course": "next_health_and_safety_course",
    "personal_phone": "personal_phone_number",
    "emergency_contact_relationship": "emergency_contact_relationship_to_the_employee",
}



_PERSONIO_NON_FATTI: dict[str, str] = {


    "employee_id": "it's the row key, already on every fact as record_id",

    "name": "emitted as identity.name outside the map",
    "email": "emitted as contact.email outside the map",




    "last_modified": "record clock: a new fact every run, zero information",
}





_PERSONIO_ZERO_E_VUOTO = frozenset(
    {"fix_salary", "hourly_salary", "yearly_employment_cost", "variable_cap", "child_allowance"}
)


def _colonna_personio(nome: str) -> str:
    ""
    c = str(nome or "").strip().lower()
    return _PERSONIO_ALIAS.get(c, c)







_PERSONIO_VUOTI = frozenset({"<na>", "<nat>", "null", "none", "nat"})


def _valore_personio(col: str, val) -> str | None:
    ""
    s = _safe_str(val)
    if s is None or s.strip().lower() in _PERSONIO_VUOTI:
        return None




    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        s = s[:-2]
    if col in _PERSONIO_ZERO_E_VUOTO:
        try:
            if float(s) == 0.0:
                return None
        except ValueError:
            pass
    return s


def _id_persona_rapporto(rapporto) -> str:
    ""
    if not isinstance(rapporto, dict):
        return ""
    p = rapporto.get("person")
    if isinstance(p, dict):
        v = _safe_str(p.get("id"))
        if v:
            return v
    for k in ("person_id", "employee_id", "owner_id"):
        v = _safe_str(rapporto.get(k))
        if v:
            return v
    return ""


def _leggi_employments(path: Path) -> dict[str, list[dict]]:
    ""







    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Personio: %s unreadable (%s) — the employment history stays out", path.name, e)
        return {}

    if isinstance(blob, dict):
        for chiave in ("data", "_data", "employments"):
            if isinstance(blob.get(chiave), list):
                blob = blob[chiave]
                break

    per_persona: dict[str, list[dict]] = defaultdict(list)
    if isinstance(blob, list):
        for r in blob:
            chiave_persona = _id_persona_rapporto(r)
            if chiave_persona:
                per_persona[chiave_persona].append(r)
    elif isinstance(blob, dict):
        for pid, rapporti in blob.items():
            for r in rapporti if isinstance(rapporti, list) else []:
                if isinstance(r, dict):
                    per_persona[str(pid).strip()].append(r)
    return dict(per_persona)


def _dentro(rapporto, *chiavi: str):
    ""
    cur = rapporto
    for k in chiavi:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _non_chiudere_cio_che_e_ancora_vero(fatti: list[Fact]) -> None:
    ""











    def _chiave(f: Fact) -> tuple:
        return (f.entity_id, f.attribute, str(f.value).strip().lower())

    aperti = {_chiave(f) for f in fatti if not f.valid_to}
    for f in fatti:
        if f.valid_to and _chiave(f) in aperti:
            f.valid_to = None











_PERSONIO_RAPPORTO_ATTR: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("position", "title"), "employment.current_role", True),
    (("type",), "employment.employment_type", True),
    (("status",), "employment.status", True),
    (("weekly_working_hours",), "employment.weekly_hours", True),
    (("supervisor", "id"), "employment.supervisor_id", True),
    (("office", "id"), "employment.office_id", True),
    (("legal_entity", "id"), "employment.legal_entity_id", True),
    (("sub_company", "id"), "employment.subcompany_id", True),
    (("job", "id"), "employment.job_id", True),
    (("employment_start_date",), "employment.contract_start_date", False),
    (("contract_end_date",), "employment.contract_end_date", False),
    (("probation_end_date",), "employment.probation_period_end", False),
    (("termination", "type"), "employment.termination_type", False),
    (("termination", "reason"), "employment.termination_reason", False),
    (("termination", "termination_date"), "employment.termination_date", False),
    (("termination", "last_working_date"), "employment.last_working_day", False),
)



_RAPPORTO_MINUSCOLO = frozenset({"employment.employment_type"})


def _stato_rapporto(rapporto: dict) -> str | None:
    ""









    s = (_safe_str(rapporto.get("status")) or "").strip().lower()
    if not s:
        return None
    if s != "inactive":
        return s
    finito = (
        _dentro(rapporto, "termination", "termination_date")
        or _dentro(rapporto, "termination", "last_working_date")
        or rapporto.get("employment_end_date")
    )
    return "terminated" if finito else "inactive"


def _fatti_del_rapporto(
    rapporto: dict, eid: str, src_file: str, rec_id: str, cessazioni_ignote: dict
) -> list[Fact]:
    ""












    if not isinstance(rapporto, dict):
        return []
    emp_id = _safe_str(rapporto.get("id")) or ""
    rid = f"{rec_id}:{emp_id}" if emp_id else rec_id
    inizio = _safe_date(rapporto.get("employment_start_date"))


    fine = (
        _safe_date(_dentro(rapporto, "termination", "last_working_date"))
        or _safe_date(_dentro(rapporto, "termination", "termination_date"))
        or _safe_date(rapporto.get("employment_end_date"))
    )

    fatti: list[Fact] = []

    def _f(attr, val, *, valid_to=None):
        return _make_fact(
            eid,
            "person",
            attr,
            val,
            "personio",
            src_file,
            rid,
            valid_from=inizio,
            valid_to=valid_to,
        )

    for percorso, attr, chiude in _PERSONIO_RAPPORTO_ATTR:
        if attr == "employment.status":
            val = _stato_rapporto(rapporto)
        else:
            val = _valore_personio("", _dentro(rapporto, *percorso))
        if not val:
            continue
        if attr in _RAPPORTO_MINUSCOLO:
            val = val.lower()
        if attr == "employment.termination_type":
            val = _cessazione(val)



            if val == CESSAZIONE_ASSENTE:
                continue
            if val not in CESSAZIONI_PERSONIO:
                cessazioni_ignote[val] += 1
        fatti.append(_f(attr, val, valid_to=fine if chiude else None))




    unita = rapporto.get("org_units")
    for u in unita if isinstance(unita, list) else []:
        if not isinstance(u, dict):
            continue
        tipo = (_safe_str(u.get("type")) or "").lower()
        uid = _safe_str(u.get("id"))
        if tipo in ("department", "team") and uid:
            fatti.append(_f(f"employment.{tipo}_id", uid, valid_to=fine))

    return fatti


def extract_from_personio() -> list[Fact]:
    ""
    path = PERSONIO_PROCESSED_DIR / "employees.parquet"
    if not path.exists():
        log.warning("Personio employees.parquet not found — skipping")
        return []

    df = pd.read_parquet(path)
    log.info("Personio: %d employees, %d columns", len(df), len(df.columns))
    facts: list[Fact] = []
    src_file = str(path.relative_to(DATA_ROOT))



    colonne = {c: _colonna_personio(c) for c in df.columns}


    per_canonico: dict[str, str] = {}
    for orig, canon in colonne.items():
        if canon in per_canonico:




            log.warning(
                "Personio: columns «%s» and «%s» both normalize to «%s»: "
                "the first wins, the second doesn't become a fact",
                per_canonico[canon],
                orig,
                canon,
            )
            continue
        per_canonico[canon] = orig

    def _leggi(riga, canonico: str):
        ""
        orig = per_canonico.get(canonico)
        return riga.get(orig) if orig is not None else None

    ripiego = sorted(
        {
            canon
            for canon in colonne.values()
            if canon not in _PERSONIO_ATTR and canon not in _PERSONIO_NON_FATTI
        }
    )
    if ripiego:



        log.info(
            "Personio: %d columns without a declared attribute → employment.<column>: %s",
            len(ripiego),
            ", ".join(ripiego),
        )

    rapporti_per_persona = _leggi_employments(PERSONIO_PROCESSED_DIR.parent / "employments.json")
    cessazioni_ignote: dict[str, int] = defaultdict(int)
    n_rapporti = 0

    for _, row in df.iterrows():
        name = _safe_str(_leggi(row, "name"))
        if not name:
            continue
        rec_id = str(_leggi(row, "employee_id") or "")
        email = _safe_str(_leggi(row, "email"))







        eid = _conia_persona(name, email=email, source_file=src_file, record_id=rec_id)

        fatti_persona: list[Fact] = []

        def _f(attr, val, *, valid_from=None, valid_to=None, _e=eid, _r=rec_id):
            return _make_fact(
                _e,
                "person",
                attr,
                val,
                "personio",
                src_file,
                _r,
                valid_from=valid_from,
                valid_to=valid_to,
            )

        def _data(canonico, _riga=row):
            ""







            return _safe_date(_valore_personio(canonico, _leggi(_riga, canonico)))

        hire_date = _data("hire_date")



        chiusura = _data("last_working_day") or _data("termination_date")

        for col_orig, col in colonne.items():
            if col in _PERSONIO_NON_FATTI or per_canonico.get(col) != col_orig:
                continue
            attr, chiude = _PERSONIO_ATTR.get(col, (f"employment.{col}", True))
            val = _valore_personio(col, row.get(col_orig))
            if val is None:
                continue
            if attr == "employment.termination_type":
                val = _cessazione(val)
                if val == CESSAZIONE_ASSENTE:
                    continue
                if val not in CESSAZIONI_PERSONIO:
                    cessazioni_ignote[val] += 1
            fatti_persona.append(
                _f(attr, val, valid_from=hire_date, valid_to=chiusura if chiude else None)
            )

        if email:
            fatti_persona.append(_f("contact.email", email))


        fatti_persona.append(_f("identity.name", name))

        for r in rapporti_per_persona.get(rec_id, []):
            fatti_persona.extend(_fatti_del_rapporto(r, eid, src_file, rec_id, cessazioni_ignote))
            n_rapporti += 1

        _non_chiudere_cio_che_e_ancora_vero(fatti_persona)
        facts.extend(fatti_persona)

    if n_rapporti:
        log.info(
            "Personio: %d employment records from employments.json, across %d employees with history",
            n_rapporti,
            len(rapporti_per_persona),
        )
    if cessazioni_ignote:


        log.warning(
            "Personio: termination types outside the known types: %s",
            dict(cessazioni_ignote),
        )
    log.info("Personio: extracted %d facts", len(facts))
    return facts


def extract_from_email() -> list[Fact]:
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        log.warning("contacts-merged.parquet not found — skipping email extraction")
        return []

    cols = [
        "email",
        "name",
        "person_id",
        "email_total_msgs",
        "email_last_seen",
        "email_first_seen",
        "email_msgs_sent",
        "email_msgs_recv",
        "has_email",
    ]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        df = pd.read_parquet(path)

    if "has_email" in df.columns:
        df = df[df["has_email"] == True]  # noqa: E712

    log.info("Email contacts: %d rows", len(df))
    facts = []
    src_file = "enriched/contacts-merged.parquet"

    for _, row in df.iterrows():
        name = _safe_str(row.get("name"))
        email = _safe_str(row.get("email"))
        if not name and not email:
            continue
        pid = _safe_str(row.get("person_id"))







        eid = _resolve_person_entity_id(name or email, pid, email=email)
        rid = pid or ""

        if email:
            facts.append(
                _make_fact(eid, "person", "contact.email", email, "email", src_file, record_id=rid)
            )

        total = row.get("email_total_msgs")
        if total and not pd.isna(total) and int(total) > 0:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "communication.email_total",
                    int(total),
                    "email",
                    src_file,
                    record_id=rid,
                )
            )

        last = _safe_date(row.get("email_last_seen"))
        if last:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "communication.email_last_contact",
                    last,
                    "email",
                    src_file,
                    record_id=rid,
                )
            )

        first = _safe_date(row.get("email_first_seen"))
        if first:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "communication.email_first_contact",
                    first,
                    "email",
                    src_file,
                    record_id=rid,
                )
            )

        if name:
            facts.append(
                _make_fact(eid, "person", "identity.name", name, "email", src_file, record_id=rid)
            )

    log.info("Email: extracted %d facts", len(facts))
    return facts


def extract_from_calendar() -> list[Fact]:
    ""
    path = ENRICHED_DIR / "contacts-calendar.parquet"
    if not path.exists():
        log.warning("contacts-calendar.parquet not found — skipping")
        return []

    df = pd.read_parquet(path)
    log.info("Calendar contacts: %d rows", len(df))
    facts = []
    src_file = "enriched/contacts-calendar.parquet"

    for _, row in df.iterrows():
        name = _safe_str(row.get("name"))
        email = _safe_str(row.get("email"))
        if not name and not email:
            continue
        eid = _conia_persona(
            name or email, email=email or None, source_file=src_file, record_id=email or ""
        )
        rid = email or ""

        total = row.get("total_events")
        if total and not pd.isna(total) and int(total) > 0:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "meeting.total_events",
                    int(total),
                    "calendar",
                    src_file,
                    record_id=rid,
                )
            )

        last = _safe_date(row.get("last_seen"))
        if last:
            facts.append(
                _make_fact(
                    eid, "person", "meeting.last_meeting", last, "calendar", src_file, record_id=rid
                )
            )

        first = _safe_date(row.get("first_seen"))
        if first:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "meeting.first_meeting",
                    first,
                    "calendar",
                    src_file,
                    record_id=rid,
                )
            )

        if name:
            facts.append(
                _make_fact(
                    eid, "person", "identity.name", name, "calendar", src_file, record_id=rid
                )
            )
        if email:
            facts.append(
                _make_fact(
                    eid, "person", "contact.email", email, "calendar", src_file, record_id=rid
                )
            )

    log.info("Calendar: extracted %d facts", len(facts))
    return facts


def extract_from_slack() -> list[Fact]:
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        return []

    cols = [
        "name",
        "person_id",
        "slack_user_id",
        "slack_messages",
        "slack_last_seen",
        "slack_first_seen",
        "has_slack",
    ]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        df = pd.read_parquet(path)

    if "has_slack" in df.columns:
        df = df[df["has_slack"] == True]  # noqa: E712

    log.info("Slack contacts: %d rows", len(df))
    facts = []
    src_file = "enriched/contacts-merged.parquet"

    for _, row in df.iterrows():
        name = _safe_str(row.get("name"))
        if not name:
            continue
        pid = _safe_str(row.get("person_id"))
        eid = _resolve_person_entity_id(name, pid)
        rid = pid or ""

        slack_id = _safe_str(row.get("slack_user_id"))
        if slack_id:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "contact.slack_handle",
                    slack_id,
                    "slack",
                    src_file,
                    record_id=rid,
                )
            )

        msgs = row.get("slack_messages")
        if msgs and not pd.isna(msgs) and int(msgs) > 0:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "communication.slack_messages",
                    int(msgs),
                    "slack",
                    src_file,
                    record_id=rid,
                )
            )

        last = _safe_date(row.get("slack_last_seen"))
        if last:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "communication.slack_last_contact",
                    last,
                    "slack",
                    src_file,
                    record_id=rid,
                )
            )

        facts.append(
            _make_fact(eid, "person", "identity.name", name, "slack", src_file, record_id=rid)
        )

    log.info("Slack: extracted %d facts", len(facts))
    return facts


def extract_from_attio() -> list[Fact]:
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        return []

    cols = [
        "name",
        "person_id",
        "has_attio",
        "attio_company",
        "attio_job_title",
        "attio_connection_strength",
        "attio_relationship_score",
        "attio_last_interaction",
        "attio_linkedin",
        "attio_sourcing_stage",
    ]



    cols_link = ["attio_record_id", "attio_web_url"]
    try:
        df = pd.read_parquet(path, columns=cols + cols_link)
    except Exception:
        try:
            df = pd.read_parquet(path, columns=cols)
        except Exception:
            df = pd.read_parquet(path)

    if "has_attio" in df.columns:
        df = df[df["has_attio"] == True]  # noqa: E712

    log.info("Attio contacts: %d rows", len(df))
    facts = []
    src_file = "enriched/contacts-merged.parquet"

    for _, row in df.iterrows():
        name = _safe_str(row.get("name"))
        if not name:
            continue
        pid = _safe_str(row.get("person_id"))
        eid = _resolve_person_entity_id(name, pid)
        rid = pid or ""


        link = {
            "attio_record_id": _safe_str(row.get("attio_record_id")) or None,
            "attio_web_url": _safe_str(row.get("attio_web_url")) or None,
        }

        company = _safe_str(row.get("attio_company"))
        if company:
            facts.append(
                _make_fact(
                    eid, "person", "crm.company", company, "attio", src_file, record_id=rid, **link
                )
            )

        title = _safe_str(row.get("attio_job_title"))
        if title:
            facts.append(
                _make_fact(
                    eid, "person", "crm.job_title", title, "attio", src_file, record_id=rid, **link
                )
            )

        strength = _safe_str(row.get("attio_connection_strength"))
        if strength:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "crm.connection_strength",
                    strength,
                    "attio",
                    src_file,
                    record_id=rid,
                    **link,
                )
            )

        stage = _safe_str(row.get("attio_sourcing_stage"))
        if stage:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "crm.sourcing_stage",
                    stage,
                    "attio",
                    src_file,
                    record_id=rid,
                    **link,
                )
            )

        li = _safe_str(row.get("attio_linkedin"))
        if li:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "contact.linkedin_url",
                    li,
                    "attio",
                    src_file,
                    record_id=rid,
                    **link,
                )
            )

        last = _safe_date(row.get("attio_last_interaction"))
        if last:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "crm.last_interaction",
                    last,
                    "attio",
                    src_file,
                    record_id=rid,
                    **link,
                )
            )

        facts.append(
            _make_fact(
                eid, "person", "identity.name", name, "attio", src_file, record_id=rid, **link
            )
        )

    log.info("Attio: extracted %d facts", len(facts))
    return facts


def extract_from_attio_seconda_classe() -> list[Fact]:
    ""






















































    if not attio_seconda_classe_attiva():
        log.info(
            "Attio second class: lane OFF (%s not set) — no facts",
            ENV_ATTIO_SECONDA_CLASSE,
        )
        return []

    path = ATTIO_SECONDA_CLASSE_DIR / ATTIO_SECONDA_CLASSE_PARQUET
    if not path.exists():
        log.warning(
            "Attio second class: flag on but %s doesn't exist "
            "(run at-l1-enrich.py --contacts-without-email)",
            path,
        )
        return []

    df = pd.read_parquet(path)
    log.info("Attio second class: %d people without email", len(df))

    facts: list[Fact] = []
    src_file = f"attio/processed/{ATTIO_SECONDA_CLASSE_PARQUET}"
    saltate_senza_record = 0


    COLONNE = (
        ("crm.company", "company_name"),
        ("crm.job_title", "job_title"),
        ("crm.sourcing_stage", "attio_sourcing_stage"),
        ("crm.relationship_score", "attio_relationship_score"),
        ("contact.linkedin_url", "linkedin"),
    )

    for _, row in df.iterrows():
        record_id = _safe_str(row.get("attio_record_id"))
        if not record_id:


            saltate_senza_record += 1
            continue

        nome = _safe_str(row.get("name")) or ""
        eid = id_seconda_classe(record_id)
        link = {
            "attio_record_id": record_id,
            "attio_web_url": _safe_str(row.get("attio_web_url")) or None,
        }

        def _f(attributo, valore, *, confidence=None, _eid=eid, _rid=record_id, _link=link):
            return _make_fact(
                _eid,
                "person",
                attributo,
                valore,
                "attio",
                src_file,
                record_id=_rid,
                confidence=confidence,
                **_link,
            )




        facts.append(_f("identity.name", nome_discriminato(nome, record_id)))


        facts.append(_f(ATTR_CLASSE, CLASSE_SECONDA, confidence=1.0))
        facts.append(_f(ATTR_ATTIO_RECORD_ID, record_id, confidence=1.0))

        for attributo, colonna in COLONNE:
            valore = _safe_str(row.get(colonna))
            if valore:
                facts.append(_f(attributo, valore))

    if saltate_senza_record:
        log.warning(
            "Attio second class: %d rows without attio_record_id, SKIPPED "
            "(an id coined from the name is exactly the harm this lane avoids)",
            saltate_senza_record,
        )
    log.info("Attio second class: extracted %d facts", len(facts))
    return facts


def extract_from_docusign() -> list[Fact]:
    ""
    path = ENRICHED_DIR / "contacts-merged.parquet"
    if not path.exists():
        return []

    cols = [
        "name",
        "person_id",
        "has_docusign",
        "docusign_contracts",
        "ds_first_contract",
        "ds_last_contract",
    ]
    try:
        df = pd.read_parquet(path, columns=cols)
    except Exception:
        df = pd.read_parquet(path)

    if "has_docusign" in df.columns:
        df = df[df["has_docusign"] == True]  # noqa: E712

    log.info("DocuSign contacts: %d rows", len(df))
    facts = []
    src_file = "enriched/contacts-merged.parquet"

    for _, row in df.iterrows():
        name = _safe_str(row.get("name"))
        if not name:
            continue
        pid = _safe_str(row.get("person_id"))
        eid = _resolve_person_entity_id(name, pid)
        rid = pid or ""

        n_contracts = row.get("docusign_contracts")
        if n_contracts and not pd.isna(n_contracts) and int(n_contracts) > 0:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "legal.contracts_count",
                    int(n_contracts),
                    "docusign",
                    src_file,
                    record_id=rid,
                )
            )

        last = _safe_date(row.get("ds_last_contract"))
        if last:
            facts.append(
                _make_fact(
                    eid, "person", "legal.last_contract", last, "docusign", src_file, record_id=rid
                )
            )

        first = _safe_date(row.get("ds_first_contract"))
        if first:
            facts.append(
                _make_fact(
                    eid,
                    "person",
                    "legal.first_contract",
                    first,
                    "docusign",
                    src_file,
                    record_id=rid,
                )
            )

        facts.append(
            _make_fact(eid, "person", "identity.name", name, "docusign", src_file, record_id=rid)
        )

    log.info("DocuSign: extracted %d facts", len(facts))
    return facts


def _require_anchor_columns(df: pd.DataFrame, src_name: str) -> None:
    ""






    missing = {"fact_id", "source_date"} - set(df.columns)
    if missing:
        raise RuntimeError(
            f"GATE 0b: {src_name} is missing the anchor columns {sorted(missing)} "
            f"(columns present: {list(df.columns)}). Extraction ABORTED so facts are not "
            f"de-anchored. Regenerate the parquet from the healthy path before proceeding."
        )


def extract_from_relationship_facts() -> list[Fact]:
    ""
    from sbk_config import RELATIONSHIP_FACTS_FILE

    if not RELATIONSHIP_FACTS_FILE.exists():
        log.warning("relationship-facts.parquet not found — skipping")
        return []

    df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
    log.info("Relationship facts: %d rows", len(df))
    _require_anchor_columns(df, "relationship-facts.parquet")



    df = _get_watermark().filtra(df, "relationship-facts.parquet")
    facts = []
    src_file = "l3/nlp/relationship-facts.parquet"
    plaud_adjusted = 0

    for _, row in df.iterrows():
        subject = _safe_str(row.get("subject"))
        if not subject:
            continue

        person_id = _safe_str(row.get("subject_person_id"))
        if e_etichetta_di_trascrizione(subject):

            eid, subject = _id_pseudo_identita(subject, _safe_str(row.get("source_id")))
            marchio = _marchio_pseudo(eid, src_file, _safe_str(row.get("fact_id")) or "")
            if marchio is not None:
                facts.append(marchio)
        else:
            eid = _resolve_person_entity_id(
                subject,
                person_id,
                source_file=src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
            )

        fact_type = _safe_str(row.get("fact_type")) or _safe_str(row.get("predicate"))
        if not fact_type:
            continue

        obj = _safe_str(row.get("object"))
        if not obj:
            continue








        counterparty = _safe_str(row.get("counterparty"))
        if counterparty:
            obj = f"{obj} (with {counterparty})"


        predicate = _safe_str(row.get("predicate")) or fact_type
        attr = f"relationship.{predicate.lower().replace(' ', '_')}"


        orig_conf = _safe_str(row.get("confidence"))
        conf = None
        if orig_conf:
            try:
                conf = float(orig_conf)

                conf = min(1.0, conf * 0.85)
            except ValueError:
                conf = None


        row_source = _safe_str(row.get("source_type"))
        plaud_name_conf: float | None = None
        if row_source == "plaud":
            quality = _plaud_quality_for(_safe_str(row.get("source_id")))
            if conf is not None:
                conf = round(conf * quality, 4)
            else:
                conf = round(compute_confidence("relationship_facts", 1, 0.0) * quality, 4)
            if not _plaud_verified(subject):

                conf = min(conf, PLAUD_UNVERIFIED_CAP)
                plaud_name_conf = PLAUD_UNVERIFIED_CAP
            plaud_adjusted += 1

        source_date = _safe_date(row.get("source_date"))


        fact_source_type = row_source or "relationship_facts"



        facts.append(
            _make_fact(
                eid,
                "person",
                attr,
                obj,
                fact_source_type,
                src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
                valid_from=source_date,
                confidence=conf,
                speaker=_clean_speaker(row.get("speaker")),
                evidence_quote=_safe_str(row.get("context")) or None,
            )
        )




        facts.append(
            _make_fact(
                eid,
                "person",
                "identity.name",
                subject,
                fact_source_type,
                src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
                confidence=plaud_name_conf,
            )
        )

    log.info(
        "Relationship facts: extracted %d facts (%d plaud quality-adjusted)",
        len(facts),
        plaud_adjusted,
    )
    return facts


def extract_from_deep_facts() -> list[Fact]:
    ""
    from sbk_config import DEEP_FACTS_FILE

    if not DEEP_FACTS_FILE.exists():
        log.warning("deep-facts.parquet not found — skipping")
        return []

    df = pd.read_parquet(DEEP_FACTS_FILE)
    log.info("Deep facts: %d rows", len(df))
    _require_anchor_columns(df, "deep-facts.parquet")
    df = _get_watermark().filtra(df, "deep-facts.parquet")
    facts = []
    src_file = "l3/nlp/deep-facts.parquet"
    plaud_adjusted = 0

    for _, row in df.iterrows():
        subject = _safe_str(row.get("subject"))
        if not subject:
            continue

        person_id = _safe_str(row.get("subject_person_id"))
        if e_etichetta_di_trascrizione(subject):
            eid, subject = _id_pseudo_identita(subject, _safe_str(row.get("source_id")))
            marchio = _marchio_pseudo(eid, src_file, _safe_str(row.get("fact_id")) or "")
            if marchio is not None:
                facts.append(marchio)
        else:
            eid = _resolve_person_entity_id(
                subject,
                person_id,
                source_file=src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
            )

        predicate = _safe_str(row.get("predicate"))
        obj = _safe_str(row.get("object"))
        if not predicate or not obj:
            continue

        category = _safe_str(row.get("category")) or "general"
        subcategory = _safe_str(row.get("subcategory"))
        attr = f"deep.{category.lower().replace(' ', '_')}"
        if subcategory:
            attr += f".{subcategory.lower().replace(' ', '_')}"

        orig_conf = _safe_str(row.get("confidence"))
        conf = None
        if orig_conf:
            try:
                conf = float(orig_conf)
                conf = min(1.0, conf * 0.85)
            except ValueError:
                conf = None


        row_source = _safe_str(row.get("source_type"))
        plaud_name_conf: float | None = None
        if row_source == "plaud":
            quality = _plaud_quality_for(_safe_str(row.get("source_id")))
            if conf is not None:
                conf = round(conf * quality, 4)
            else:
                conf = round(compute_confidence("deep_facts", 1, 0.0) * quality, 4)
            if not _plaud_verified(subject):

                conf = min(conf, PLAUD_UNVERIFIED_CAP)
                plaud_name_conf = PLAUD_UNVERIFIED_CAP
            plaud_adjusted += 1

        source_date = _safe_date(row.get("source_date"))

        value = f"{predicate}: {obj}"
        counterparty = _safe_str(row.get("counterparty"))
        if counterparty:
            value += f" (with {counterparty})"


        fact_source_type = row_source or "deep_facts"



        facts.append(
            _make_fact(
                eid,
                "person",
                attr,
                value,
                fact_source_type,
                src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
                valid_from=source_date,
                confidence=conf,
                evidence_quote=_safe_str(row.get("context")) or None,
            )
        )




        facts.append(
            _make_fact(
                eid,
                "person",
                "identity.name",
                subject,
                fact_source_type,
                src_file,
                record_id=_safe_str(row.get("fact_id")) or "",
                confidence=plaud_name_conf,
            )
        )

    log.info(
        "Deep facts: extracted %d facts (%d plaud quality-adjusted)", len(facts), plaud_adjusted
    )
    return facts



















































def _obs_extracted_at(
    o: FactObservation,
) -> str:
    ""





    if o.extracted_at:
        return o.extracted_at
    rec = getattr(o, "record", None)
    return (
        (getattr(rec, "extracted_at", "") or "")
        if rec is not None
        else ""
    )


def _chiave_riga(o: FactObservation) -> tuple:
    ""
    return (o.source_file, o.record_id)


def _chiave_osservazione(o: FactObservation) -> tuple:
    ""


    return (
        o.source_file,
        o.record_id,
        _obs_extracted_at(o),
    )


def fondi_osservazioni(
    esistenti: list[FactObservation], in_arrivo: list[FactObservation]
) -> list[FactObservation]:
    ""














    fuse: list[FactObservation] = list(esistenti)
    righe: dict[tuple, list[int]] = defaultdict(list)
    for i, o in enumerate(fuse):
        righe[_chiave_riga(o)].append(i)

    for nuova in in_arrivo:
        riga = _chiave_riga(nuova)
        posizioni = righe.get(riga)
        if not posizioni:
            fuse.append(nuova)
            righe[riga].append(len(fuse) - 1)
            continue
        tripla = _chiave_osservazione(nuova)
        gemella = next((j for j in posizioni if _chiave_osservazione(fuse[j]) == tripla), None)
        if gemella is None:

            gemella = max(
                posizioni,
                key=lambda j: (
                    _obs_extracted_at(fuse[j]),
                    j,
                ),
            )
        fuse[gemella] = nuova
    return fuse


def _union_observations(group: list[Fact]) -> list[FactObservation]:
    ""













    buckets: dict[tuple, list[Fact]] = defaultdict(list)
    for i, f in enumerate(group):
        rid = f.source.record_id

        obs_key = (f.source.source_file, rid) if rid else (f.source.source_file, "", i)
        buckets[obs_key].append(f)

    observations: list[FactObservation] = []
    for _k, bucket in buckets.items():
        rep = max(bucket, key=lambda f: f.confidence)
        observations.append(
            FactObservation(
                source_file=rep.source.source_file,
                record_id=rep.source.record_id,
                source_type=rep.source.source_type,
                valid_from=rep.valid_from,
                extracted_at=rep.source.extracted_at,
                confidence=rep.confidence,
                confidence_curve=sorted(f.confidence for f in bucket),
            )
        )

    ereditate: list[FactObservation] = []
    viste: set[tuple] = set()
    for f in group:
        for o in f.observations or []:
            t = _chiave_osservazione(o)
            if t not in viste:
                viste.add(t)
                ereditate.append(o)
    if not ereditate:

        return observations
    return fondi_osservazioni(ereditate, observations)


def reconcile(facts: list[Fact]) -> list[Fact]:
    ""








    groups: dict[tuple, list[Fact]] = defaultdict(list)
    for f in facts:

        val_key = str(f.value).strip().lower() if f.value is not None else ""
        key = (f.entity_id, f.attribute, val_key)
        groups[key].append(f)

    reconciled = []
    for (_eid, _attr, _val), group in groups.items():
        if len(group) == 1:
            reconciled.append(group[0])
        else:

            best = max(group, key=lambda f: f.confidence)
            best.observations = _union_observations(group)


            n_sources = len(
                {(o.source_file, o.record_id) for o in best.observations if o.record_id}
            ) or len(best.observations)
            if n_sources > 1:
                best.confidence = compute_confidence(best.source.source_type, n_sources, 0.0)
            reconciled.append(best)

    log.info(
        "Reconciled: %d facts -> %d (merged %d duplicates)",
        len(facts),
        len(reconciled),
        len(facts) - len(reconciled),
    )
    return reconciled


def _n_independent_sources(f: Fact) -> int:
    ""











    if f.attribute == "identity.name":
        return max(1, len({o.source_file for o in f.observations}))
    distinct = {(o.source_file, o.record_id) for o in f.observations if o.record_id}
    return max(1, len(distinct))


def score(facts: list[Fact]) -> list[Fact]:
    ""





    for f in facts:
        n_sources = _n_independent_sources(f)
        if f.valid_from:
            days = _days_since(f.valid_from)
            if days > 0:
                f.confidence = compute_confidence(f.source.source_type, n_sources, days)
        elif n_sources > 1:

            f.confidence = compute_confidence(f.source.source_type, n_sources, 0.0)
    return facts























_FN_CLASSIFICA = None


















_MOD_PERSONE = None


def _sb_persone_mod():
    ""






    global _MOD_PERSONE
    if _MOD_PERSONE is None:
        try:
            import importlib.util

            perc = Path(__file__).resolve().parent.parent / "util" / "sb-persone.py"
            spec = importlib.util.spec_from_file_location("sb_persone_pipeline", perc)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["sb_persone_pipeline"] = mod
            spec.loader.exec_module(mod)
            _MOD_PERSONE = mod
        except Exception as e:  # pragma: no cover
            log.warning("sb-persone not loaded (%s)", e)
            _MOD_PERSONE = False
    return _MOD_PERSONE


def _classe_entita(eid: str, nome: str, fatti: list) -> tuple[str, str] | None:
    ""
    global _FN_CLASSIFICA
    if _FN_CLASSIFICA is None:
        mod = _sb_persone_mod()
        if mod:
            _FN_CLASSIFICA = mod.classifica
        else:
            log.warning("entities will be born without a class")
            _FN_CLASSIFICA = False
    if not _FN_CLASSIFICA:
        return None
    try:










        crudi = [
            {
                "attribute": getattr(f, "attribute", ""),
                "value": getattr(f, "value", ""),
                "source": {
                    "source_type": getattr(getattr(f, "source", None), "source_type", ""),
                    "record_id": getattr(getattr(f, "source", None), "record_id", ""),
                    "source_file": getattr(getattr(f, "source", None), "source_file", ""),
                },
            }
            for f in fatti
        ]
        v = _FN_CLASSIFICA(eid, nome, crudi)
        return v.categoria, (v.perche or [""])[0]
    except Exception:  # pragma: no cover
        return None


def write_profiles(facts: list[Fact], dry_run: bool = False) -> dict:
    ""




    entity_facts: dict[str, list[Fact]] = defaultdict(list)
    entity_names: dict[str, str] = {}
    entity_types: dict[str, str] = {}

    for f in facts:
        entity_facts[f.entity_id].append(f)
        entity_types[f.entity_id] = f.entity_type

        if f.attribute == "identity.name" and f.value:
            existing = entity_names.get(f.entity_id, "")
            if not existing or f.confidence > 0.5:
                entity_names[f.entity_id] = str(f.value)

    now = _now_iso()
    stats = {"entities": 0, "facts": 0, "new_entities": 0, "updated_entities": 0}
    skipped_no_name = 0

    ignoti_bloccati = 0





    depositate_righe = 0
    depositati_fatti = 0



    nate_person = 0
    nate_composite = 0
    for eid, eid_facts in entity_facts.items():
        etype = entity_types[eid]
        cname = entity_names.get(eid, eid)















        if str(eid).startswith("ignoto_"):
            ignoti_bloccati += 1
            n_dep = _deposita_fatti_senza_casa(eid, cname, eid_facts)
            if n_dep:
                depositate_righe += 1
                depositati_fatti += n_dep
            log.warning(
                "unknown id on the write-path: %s — %d facts not written in `person/`, %s",
                eid,
                len(eid_facts),
                "placed in the deposit" if n_dep else "⛔ LOST: deposit unavailable",
            )
            continue




        if etype == "person" and _gia_organizzazione(eid):
            etype = "organization"
            entity_types[eid] = etype


        profile_path = KNOWLEDGE_ENTITIES_DIR / etype / f"{eid}.json"



        if cname == eid and not profile_path.exists():
            skipped_no_name += 1
            continue
        if profile_path.exists():
            try:
                existing = dict_to_profile(json.loads(profile_path.read_text()))








                def _natkey(f: Fact) -> tuple:
                    v = str(f.value).strip().lower() if f.value is not None else ""
                    return (f.entity_id, f.attribute, v)

                by_natkey: dict[tuple, Fact] = {}
                for f in existing.facts:
                    by_natkey[_natkey(f)] = f
                for f in eid_facts:
                    nk = _natkey(f)
                    prev = by_natkey.get(nk)
                    if prev is None:
                        by_natkey[nk] = f
                        continue











                    nuove = list(f.observations)
                    if f.source and f.source.record_id:



                        righe_note = {_chiave_riga(o) for o in prev.observations}
                        righe_note |= {_chiave_riga(o) for o in nuove}
                        if (f.source.source_file, f.source.record_id) not in righe_note:
                            nuove.append(
                                FactObservation(
                                    source_file=f.source.source_file,
                                    record_id=f.source.record_id,
                                    source_type=f.source.source_type,
                                    valid_from=f.valid_from,
                                    extracted_at=f.source.extracted_at,
                                    confidence=f.confidence,
                                )
                            )
                    prev.observations = fondi_osservazioni(prev.observations, nuove)
                    prev.confidence = max(prev.confidence, f.confidence)
                    if f.valid_from and (not prev.valid_from or f.valid_from > prev.valid_from):
                        prev.valid_from = f.valid_from





















                    if f.valid_to and not prev.valid_to:
                        prev.valid_to = f.valid_to
                    elif f.valid_to and prev.valid_to and f.valid_to < prev.valid_to:


                        prev.valid_to = f.valid_to
                    if getattr(f, "expired_at", None) and not getattr(prev, "expired_at", None):
                        prev.expired_at = f.expired_at
                    if getattr(f, "superseded_by", None) and not getattr(
                        prev, "superseded_by", None
                    ):
                        prev.superseded_by = f.superseded_by
                existing.facts = list(by_natkey.values())
                existing.updated_at = now
                existing.version += 1


















                name_facts = [f for f in existing.facts if f.attribute == "identity.name"]
                if name_facts:




                    best_name = max(
                        name_facts,
                        key=lambda f: (f.confidence, -_e_nome_povero(f.value)),
                    )
                    if best_name.confidence > 0.5 and best_name.value:
                        if _e_composito(best_name.value) and not _e_composito(
                            existing.canonical_name
                        ):
                            log.warning(
                                "canonical NOT changed for %s: the candidate «%s» names several people",
                                existing.entity_id,
                                str(best_name.value)[:60],
                            )
                        else:
                            existing.canonical_name = str(best_name.value)
                profile = existing
                stats["updated_entities"] += 1
            except Exception as e:


























                log.error(
                    "profile UNREADABLE: %s (%s) — entity SKIPPED, no write",
                    profile_path,
                    e,
                )
                stats["profili_illeggibili"] = stats.get("profili_illeggibili", 0) + 1
                esempi = stats.setdefault("profili_illeggibili_esempi", [])
                if len(esempi) < 20:
                    esempi.append(eid)
                continue
        else:
            profile = EntityProfile(
                entity_id=eid,
                entity_type=etype,
                canonical_name=cname,
                facts=eid_facts,
                created_at=now,
                updated_at=now,
                version=1,
            )
            stats["new_entities"] += 1








            if etype == "person":
                nate_person += 1
                if _e_composito(cname):
                    nate_composite += 1





























        if (
            etype == "person"
            and not e_seconda_classe(profile.facts)
            and not e_pseudo_identita(profile.facts)
        ):
            esito = _classe_entita(eid, profile.canonical_name, profile.facts)
            if esito:
                classe, perche = esito
                stats.setdefault("per_classe", defaultdict(int))
                stats["per_classe"][classe] += 1
                profile.facts = [
                    f for f in profile.facts if getattr(f, "attribute", "") != "identity.classe"
                ] + [
                    Fact(
                        fact_id=f"classe-{eid}",
                        entity_id=eid,
                        entity_type=etype,
                        attribute="identity.classe",
                        value=classe,
                        confidence=0.8,
                        valid_from=now[:10],





                        valid_to=None,
                        expired_at=None,
                        created_at=now,
                        source=FactSource(
                            source_type="classificatore",
                            source_file="sb-persone.py",
                            record_id=perche[:80],
                            extracted_at=now,
                        ),
                    )
                ]






        if eid in _PSEUDO_CONIATE and not e_pseudo_identita(profile.facts):
            stats["pseudo_senza_marchio"] = stats.get("pseudo_senza_marchio", 0) + 1
            log.error(
                "pseudo-identity written WITHOUT mark: %s (%s) — "
                "it will end up in the people census",
                eid,
                profile.canonical_name[:60],
            )

        stats["entities"] += 1
        stats["facts"] += len(eid_facts)

        if dry_run:
            continue
















        safe_write_json(
            profile_path,
            profile_to_dict(profile),
            indent=2,
            ensure_ascii=True,
            fsync=True,
        )


        facts_path = KNOWLEDGE_FACTS_DIR / etype / f"{eid}.jsonl"
        safe_write_text(
            facts_path,
            (json.dumps(fact_to_dict(f), default=str) + "\n" for f in profile.facts),
            fsync=True,
        )

    if skipped_no_name:
        log.info(
            "Skipped %d profiles without identity.name (canonical_name = entity_id)",
            skipped_no_name,
        )


    stats["ignoti_bloccati"] = ignoti_bloccati



    stats["depositate_righe"] = depositate_righe
    stats["depositati_fatti"] = depositati_fatti
    if ignoti_bloccati and stats["depositate_righe"] < ignoti_bloccati:
        log.error(
            "%d coinings rejected and only %d rows in the deposit: %d fact groups LOST",
            ignoti_bloccati,
            stats["depositate_righe"],
            ignoti_bloccati - stats["depositate_righe"],
        )





    stats["nate_person"] = nate_person
    stats["nate_composite"] = nate_composite





    stats["pseudo_coniate"] = len(_PSEUDO_CONIATE)
    stats.setdefault("pseudo_senza_marchio", 0)
    if stats["pseudo_senza_marchio"]:
        log.error(
            "%d pseudo-identities out of %d written WITHOUT mark: counted as people",
            stats["pseudo_senza_marchio"],
            stats["pseudo_coniate"],
        )

    return stats
















def _id_commitment(task_id: str) -> str:
    ""






    import hashlib

    return "commitment_" + hashlib.sha256(f"clickup|{task_id}".encode()).hexdigest()[:16]















CLICKUP_TASKS_PARQUET = DATA_ROOT / "clickup" / "processed" / "tasks.parquet"
CLICKUP_PEOPLE_PARQUET = DATA_ROOT / "clickup" / "processed" / "people.parquet"

DOMINI_DEGLI_STRUMENTI = ("clickup.com", "slack.com", "notion.so", "atlassian.com")


def _e_un_robot(email: str) -> bool:
    e = str(email or "").lower()
    return any(e.endswith("@" + d) for d in DOMINI_DEGLI_STRUMENTI)


def extract_from_clickup() -> list[Fact]:
    ""
    if not CLICKUP_TASKS_PARQUET.exists():
        log.warning(
            "clickup/processed/tasks.parquet isn't there — run `tools/clickup/cu-l1-enrich.py` first"
        )
        return []

    facts: list[Fact] = []
    src_tasks = "clickup/processed/tasks.parquet"


    robot = 0
    if CLICKUP_PEOPLE_PARQUET.exists():
        pp = pd.read_parquet(CLICKUP_PEOPLE_PARQUET)
        log.info("ClickUp: %d people", len(pp))
        for _, r in pp.iterrows():
            email = _safe_str(r.get("email"))
            nome = _safe_str(r.get("nome"))
            if not email and not nome:
                continue
            if _e_un_robot(email):
                robot += 1
                continue
            eid = _resolve_person_entity_id(
                nome or email,
                None,
                email=email or None,
                source_file="clickup/processed/people.parquet",
                record_id=email,
            )
            if email:
                facts.append(
                    _make_fact(
                        eid,
                        "person",
                        "contact.email",
                        email,
                        "clickup",
                        "clickup/processed/people.parquet",
                        record_id=email,
                    )
                )
            if nome:
                facts.append(
                    _make_fact(
                        eid,
                        "person",
                        "work.clickup_username",
                        nome,
                        "clickup",
                        "clickup/processed/people.parquet",
                        record_id=email,
                    )
                )






    if robot:
        log.info("ClickUp: %d product robots discarded (not people)", robot)

    df = pd.read_parquet(CLICKUP_TASKS_PARQUET)
    vivi = df[(df["aperto"]) & (df["n_assegnatari"] > 0)]
    log.info("ClickUp: %d open and assigned tasks (out of %d)", len(vivi), len(df))

    for _, r in vivi.iterrows():
        tid = _safe_str(r.get("task_id"))
        nome = _safe_str(r.get("nome"))
        if not tid or not nome:
            continue
        cid = _id_commitment(tid)

        def _f(attr, val, *, _cid=cid, _tid=tid):
            return _make_fact(_cid, "commitment", attr, val, "clickup", src_tasks, record_id=_tid)

        facts.append(_f("identity.name", nome))
        facts.append(_f("commitment.status", _safe_str(r.get("stato"))))
        facts.append(_f("commitment.source_url", _safe_str(r.get("url"))))
        dove = " / ".join(x for x in (_safe_str(r.get("space")), _safe_str(r.get("lista"))) if x)
        if dove:
            facts.append(_f("commitment.where", dove))
        scadenza = _safe_str(r.get("scadenza"))
        if scadenza:
            facts.append(_f("commitment.due_date", scadenza[:10]))
        prio = _safe_str(r.get("priorita"))
        if prio:
            facts.append(_f("commitment.priority", prio))







        _a = r.get("assegnatari")
        _m = r.get("assegnatari_email")
        for chi, mail in zip(
            list(_a) if _a is not None else [],
            list(_m) if _m is not None else [],
            strict=False,
        ):
            chi, mail = _safe_str(chi), _safe_str(mail)
            if not chi and not mail:
                continue
            if _e_un_robot(mail):
                continue
            facts.append(_f("commitment.owner", chi or mail))
            pid = _resolve_person_entity_id(
                chi or mail,
                None,
                email=mail or None,
                source_file=src_tasks,
                record_id=tid,
            )
            facts.append(
                _make_fact(
                    pid,
                    "person",
                    "relationship.commitment",
                    nome,
                    "clickup",
                    src_tasks,
                    record_id=tid,
                )
            )

    return facts











LINKEDIN_CONTACTS_PARQUET = DATA_ROOT / "linkedin" / "processed" / "contacts-linkedin.parquet"


















LINKEDIN_CONIA_NUOVI = False










def _chiave_nome(n) -> str:
    ""
    import unicodedata

    s = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _nomi_gia_noti() -> set[str]:
    ""




















    d = KNOWLEDGE_ENTITIES_DIR / "person"
    if not d.exists():
        return set()
    noti = set()
    for f in d.glob("*.json"):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n = (e.get("canonical_name") or "").strip()
        if n:
            noti.add(_chiave_nome(n))
        for a in e.get("aliases") or []:
            noti.add(_chiave_nome(a))
    noti.discard("")
    return noti


def extract_from_linkedin() -> list[Fact]:
    ""





























    if not LINKEDIN_CONTACTS_PARQUET.exists():
        log.warning("linkedin/processed/contacts-linkedin.parquet isn't there — skipping")
        return []

    df = pd.read_parquet(LINKEDIN_CONTACTS_PARQUET)
    noti = _nomi_gia_noti()
    df["_scambiati"] = pd.to_numeric(df.get("total_messages"), errors="coerce").fillna(0)
    conosciuto = df["name"].map(lambda n: _chiave_nome(n) in noti)
    dentro = df[(df["_scambiati"] > 0) | conosciuto]
    log.info(
        "LinkedIn: %d contacts in scope out of %d (%d with messages, %d already known)",
        len(dentro),
        len(df),
        int((df["_scambiati"] > 0).sum()),
        int(conosciuto.sum()),
    )
    if not LINKEDIN_CONIA_NUOVI:



        log.info(
            "LinkedIn: coining OFF — it enriches whom the KB already knows and creates "
            "no one. Contacts outside the KB stay out (LINKEDIN_CONIA_NUOVI)."
        )

    facts: list[Fact] = []
    src = "linkedin/processed/contacts-linkedin.parquet"
    for _, r in dentro.iterrows():
        nome = _safe_str(r.get("name"))
        if not nome:
            continue
        email = _safe_str(r.get("email"))
        url = _safe_str(r.get("linkedin_url"))
        eid = _resolve_person_entity_id(
            nome, None, email=email or None, source_file=src, record_id=url or nome
        )

        def _f(attr, val, *, confidence=None, _eid=eid, _rid=url or nome):
            return _make_fact(
                _eid,
                "person",
                attr,
                val,
                "linkedin",
                src,
                record_id=_rid,
                confidence=confidence,
            )




        if LINKEDIN_CONIA_NUOVI:
            facts.append(_f("identity.name", nome, confidence=0.45))
        if url:
            facts.append(_f("contact.linkedin_url", url))
        if email:
            facts.append(_f("contact.email", email))













        azienda = _safe_str(r.get("company"))
        if azienda:
            facts.append(_f("employment.company", azienda, confidence=0.45))




        titolo = _safe_str(r.get("headline"))
        if titolo:
            facts.append(_f("identity.headline", titolo, confidence=0.45))



















        n = int(r.get("_scambiati") or 0)
        if n:
            facts.append(_f("communication.linkedin_messages", str(n)))
            for attr, col in (
                ("communication.linkedin_first_contact", "first_message_date"),
                ("communication.linkedin_last_contact", "last_message_date"),
            ):
                v = _safe_str(r.get(col))
                if v:
                    facts.append(_f(attr, v[:10]))
        quando = _safe_str(r.get("connection_date"))
        if quando:
            facts.append(_f("relationship.linkedin_connected", quando[:10]))

    return facts












# --- Generic plugin intake (tools/cross-source/plugin_intake.py) ------------
# Plugins with no dedicated slot write $DATA_ROOT/<plugin>/processed/
# plugin-contacts.parquet and plugin-interactions.parquet. Contacts become person
# facts the way LinkedIn and ClickUp people do; open interactions where you are
# the assignee, or that carry a due date, become commitments the way ClickUp
# tasks do. Missing files: no facts, no error.


def _id_commitment_plugin(plugin: str, rid: str) -> str:
    """Stable commitment id for one plugin item (same recipe as _id_commitment)."""
    import hashlib

    return "commitment_" + hashlib.sha256(f"{plugin}|{rid}".encode()).hexdigest()[:16]


def extract_from_plugins(root: Path | None = None) -> list[Fact]:
    """Person facts and commitments from the generic plugin intake files."""
    import plugin_intake as _pi

    from sbk_config import OWNER_NAME, is_own_email, is_own_name

    base = root if root is not None else DATA_ROOT
    people = _pi.load_people(base)
    events = _pi.load_interactions(base)
    if people is None and events is None:
        log.info("Plugins: no plugin-contacts / plugin-interactions files — skipping")
        return []

    facts: list[Fact] = []

    def _persona(name: str, email: str, src: str, rid: str) -> str | None:
        if (email and is_own_email(email)) or (name and is_own_name(name)):
            return None
        if not name and not email:
            return None
        return _resolve_person_entity_id(
            name or email, None, email=email or None, source_file=src, record_id=rid
        )

    n_people = 0
    for r in people.itertuples(index=False) if people is not None else ():
        email = r.email if "@" in (r.email or "") else ""
        name = _safe_str(r.name) or ""
        da_partecipanti = bool(getattr(r, _pi.FROM_PARTICIPANTS, False))
        fname = _pi.INTERACTIONS_FILE if da_partecipanti else _pi.CONTACTS_FILE
        src = f"{r.plugin}/processed/{fname}"
        rid = email or (r.phone or "") or name
        eid = _persona(name, email, src, rid)
        if not eid:
            continue
        n_people += 1
        key = _pi.plugin_key(r.source)

        def _f(attr, val, *, confidence=None, _eid=eid, _src=src, _rid=rid, _st=r.source):
            return _make_fact(
                _eid, "person", attr, val, _st, _src, record_id=_rid, confidence=confidence
            )

        # A bare participant (a name or an email inside an event) never coins a
        # person: without identity.name it only enriches someone the KB knows.
        if name and not da_partecipanti:
            facts.append(_f("identity.name", name))
        if email:
            facts.append(_f("contact.email", email))
        if r.phone:
            facts.append(_f("contact.phone", r.phone))
        # Self-declared in the source app: low confidence, like LinkedIn.
        if r.company:
            facts.append(_f("employment.company", r.company, confidence=0.45))
        if r.title:
            facts.append(_f("identity.headline", r.title, confidence=0.45))
        if r.url and not da_partecipanti:
            facts.append(_f(f"contact.{key}_url", r.url))
        if int(r.interactions or 0) > 0:
            facts.append(_f(f"communication.{key}_interactions", int(r.interactions)))
        if r.first_seen:
            facts.append(_f(f"communication.{key}_first_contact", r.first_seen[:10]))
        if r.last_seen:
            facts.append(_f(f"communication.{key}_last_contact", r.last_seen[:10]))

    n_commitments = 0
    for r in events.itertuples(index=False) if events is not None else ():
        if not _pi.is_commitment(r) or not r.title:
            continue
        src = f"{r.plugin}/processed/{_pi.INTERACTIONS_FILE}"
        rid = r.url or f"{r.ts}|{r.title}"
        cid = _id_commitment_plugin(r.source, rid)

        def _c(attr, val, *, _cid=cid, _src=src, _rid=rid, _st=r.source):
            return _make_fact(_cid, "commitment", attr, val, _st, _src, record_id=_rid)

        n_commitments += 1
        facts.append(_c("identity.name", r.title))
        facts.append(_c("commitment.status", r.status or "open"))
        if r.url:
            facts.append(_c("commitment.source_url", r.url))
        facts.append(_c("commitment.where", f"{r.source} / {r.kind}"))
        if r.due:
            facts.append(_c("commitment.due_date", r.due[:10]))
        if r.owner_role == "assignee" and OWNER_NAME:
            facts.append(_c("commitment.owner", OWNER_NAME))
        # The people involved carry the commitment in their relationship, as
        # ClickUp assignees do.
        for p in _pi.split_participants(r.participants):
            p_name, email = _pi.parse_person(p)
            pid = _persona(p_name, email, src, rid)
            if pid:
                facts.append(
                    _make_fact(
                        pid, "person", "relationship.commitment", r.title, r.source, src,
                        record_id=rid,
                    )
                )

    log.info(
        "Plugins: %d people, %d commitments, %d facts", n_people, n_commitments, len(facts)
    )
    return facts


ALL_SOURCES = [
    "personio",
    "email",
    "calendar",
    "slack",
    "attio",





    "attio_seconda_classe",
    "docusign",
    "clickup",
    "linkedin",
    "plugins",
    "relationship_facts",
    "deep_facts",
]

EXTRACTORS = {
    "personio": extract_from_personio,
    "email": extract_from_email,
    "calendar": extract_from_calendar,
    "slack": extract_from_slack,
    "attio": extract_from_attio,
    "attio_seconda_classe": extract_from_attio_seconda_classe,
    "docusign": extract_from_docusign,
    "clickup": extract_from_clickup,
    "linkedin": extract_from_linkedin,
    "plugins": extract_from_plugins,
    "relationship_facts": extract_from_relationship_facts,
    "deep_facts": extract_from_deep_facts,
}




IMPRONTE_FATTI = KNOWLEDGE_META_DIR / "impronte-fatti.json"


def _impronta_fatti(facts: list[Fact]) -> dict[str, str]:
    ""

    import hashlib

    per_entita: dict[str, list[str]] = {}
    for f in facts:
        s = f.source
        riga = json.dumps(
            [
                f.entity_type,
                f.attribute,
                f.value,
                f.valid_from,
                f.valid_to,
                f.confidence,
                getattr(s, "source_type", None),
                getattr(s, "source_file", None),
                getattr(s, "record_id", None),
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        per_entita.setdefault(f.entity_id, []).append(riga)
    return {
        eid: hashlib.sha1("\n".join(sorted(righe)).encode("utf-8")).hexdigest()
        for eid, righe in per_entita.items()
    }


def _senza_le_invariate(
    facts: list[Fact], impronte: dict[str, str], prima: dict[str, str]
) -> tuple[list[Fact], int]:
    ""
    uguali = {eid for eid, h in impronte.items() if prima.get(eid) == h}
    return [f for f in facts if f.entity_id not in uguali], len(uguali)


def _leggi_impronte() -> dict[str, str]:
    ""
    try:
        d = json.loads(IMPRONTE_FATTI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _salva_impronte(impronte: dict[str, str]) -> None:
    safe_write_json(IMPRONTE_FATTI, impronte, ensure_ascii=True, fsync=True)


def run_extraction(
    sources: list[str] | None = None,
    entity_id: str | None = None,
    dry_run: bool = False,
    domain: str | None = None,
    incremental: bool = False,
) -> dict:
    ""
    ensure_knowledge_dirs()
    _load_people_universe()



    _reset_incremento()

    if sources is None:
        sources = ALL_SOURCES

    all_facts: list[Fact] = []
    source_stats: dict[str, int] = {}

    for src in sources:
        extractor = EXTRACTORS.get(src)
        if not extractor:
            log.warning("Unknown source: %s", src)
            continue
        log.info("Extracting from: %s", src)
        facts = extractor()
        source_stats[src] = len(facts)
        all_facts.extend(facts)

    log.info("Total raw facts: %d from %d sources", len(all_facts), len(sources))


    if entity_id:
        all_facts = [f for f in all_facts if f.entity_id == entity_id]
        log.info("Filtered to entity %s: %d facts", entity_id, len(all_facts))


    if domain:
        all_facts = [f for f in all_facts if f.entity_type == domain]
        log.info("Filtered to domain %s: %d facts", domain, len(all_facts))







    impronte = _impronta_fatti(all_facts)
    if incremental:
        prima = _leggi_impronte()
        if prima:
            all_facts, saltate = _senza_le_invariate(all_facts, impronte, prima)
            log.info(
                "Incremental: skipped %d unchanged entities (same facts as the last full run)",
                saltate,
            )
        else:
            log.info(
                "Incremental: no fingerprint from the last full run, this time all entities are read"
            )


    all_facts = reconcile(all_facts)
    all_facts = score(all_facts)



    try:
        from xs_knowledge_conflict import (
            apply_resolution,
            batch_add_to_pending_review,
            resolve_conflict,
        )
        from xs_knowledge_conflict import (
            compute_fact_confidence as compute_conflict_confidence,
        )
        from xs_knowledge_conflict import (
            detect_conflicts as detect_fact_conflicts,
        )

        conflict_stats = {"detected": 0, "auto_resolved": 0, "pending_review": 0}
        pending_batch: list[dict] = []


        new_by_entity: dict[str, list[Fact]] = defaultdict(list)
        for f in all_facts:
            new_by_entity[f.entity_id].append(f)

        n_entities = len(new_by_entity)

        if n_entities > 10000:
            log.info(
                "Conflict detection: skipping (%d entities too many, threshold 10000)",
                n_entities,
            )
            raise ImportError("too many entities")
        for idx, (eid, new_eid_facts) in enumerate(new_by_entity.items()):
            if idx > 0 and idx % 5000 == 0:
                log.info("Conflict detection: %d/%d entities processed...", idx, n_entities)

            etype = new_eid_facts[0].entity_type
            profile_path = KNOWLEDGE_ENTITIES_DIR / etype / f"{eid}.json"
            if not profile_path.exists():
                continue

            try:
                existing_profile = json.loads(profile_path.read_text())
                existing_fact_dicts = existing_profile.get("facts", [])
            except Exception:
                continue

            new_fact_dicts = [fact_to_dict(f) for f in new_eid_facts]

            conflicts = detect_fact_conflicts(existing_fact_dicts, new_fact_dicts)
            conflict_stats["detected"] += len(conflicts)

            for conflict in conflicts:
                resolved = resolve_conflict(conflict)
                action = resolved.get("recommended_action", "pending_review")

                if action == "pending_review":
                    pending_batch.append(resolved)
                    conflict_stats["pending_review"] += 1
                else:
                    if not dry_run:
                        apply_resolution(existing_profile, resolved)
                    conflict_stats["auto_resolved"] += 1


            all_fact_dicts = existing_fact_dicts + new_fact_dicts
            for f in new_eid_facts:
                fd = fact_to_dict(f)
                f.confidence = compute_conflict_confidence(fd, all_fact_dicts)


        if pending_batch and not dry_run:




            esito_coda = batch_add_to_pending_review(pending_batch)
            log.info("Pending review: queue %s", esito_coda)
            conflict_stats["coda"] = esito_coda.come_dict()

        if conflict_stats["detected"] > 0:
            log.info(
                "Conflicts: %d detected, %d auto-resolved, %d pending review",
                conflict_stats["detected"],
                conflict_stats["auto_resolved"],
                conflict_stats["pending_review"],
            )
        stats_conflict = conflict_stats

    except ImportError:
        log.warning("xs_knowledge_conflict not available — skipping conflict detection")
        stats_conflict = None
    except Exception as exc:
        log.warning("Conflict detection failed (non-fatal): %s", exc)
        stats_conflict = None


    stats = write_profiles(all_facts, dry_run=dry_run)
    stats["source_stats"] = source_stats
    if stats_conflict:
        stats["conflict_stats"] = stats_conflict









    if not dry_run:
        try:
            import importlib.util as _il

            _perc = Path(__file__).resolve().parent.parent / "util" / "sb-vocabolario.py"
            _spec = _il.spec_from_file_location("sb_vocabolario_pipeline", _perc)
            _voc = _il.module_from_spec(_spec)
            sys.modules["sb_vocabolario_pipeline"] = _voc
            _spec.loader.exec_module(_voc)
            _prima = set(_voc._precedente())
            _r = _voc.impara()
            _nuove = sorted(set(_r["imparate"]) - _prima)
            _cadute = sorted(_prima - set(_r["imparate"]))
            _voc.VOCABOLARIO.parent.mkdir(parents=True, exist_ok=True)
            _voc.VOCABOLARIO.write_text(
                json.dumps(
                    {**_r, "quando": _now_iso(), "nuove": _nuove, "cadute": _cadute},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            stats["vocabolario"] = {
                "sigle": len(_r["imparate"]),
                "nuove": _nuove,
                "cadute": _cadute,
            }
            if _nuove or _cadute:
                log.info("acronym vocabulary: +%s −%s", _nuove or "—", _cadute or "—")
        except Exception as e:  # pragma: no cover
            log.warning("vocabulary not updated (%s): the hardcoded guard remains", e)








    if not dry_run:
        try:
            import importlib.util as _il

            _perc = Path(__file__).resolve().parent.parent / "util" / "sb-copertura.py"
            _spec = _il.spec_from_file_location("sb_copertura_pipeline", _perc)
            _cop = _il.module_from_spec(_spec)
            sys.modules["sb_copertura_pipeline"] = _cop
            _spec.loader.exec_module(_cop)
            _prima = {}
            if _cop.RAPPORTO.exists():
                _prima = json.loads(_cop.RAPPORTO.read_text(encoding="utf-8")).get("presidi", {})
            _r = _cop.gira()









            _adesso_cop = _now_iso()
            for _v in _r.values():
                if isinstance(_v, dict):
                    _v["misurato"] = _adesso_cop
            _cop.RAPPORTO.parent.mkdir(parents=True, exist_ok=True)
            _cop.RAPPORTO.write_text(
                json.dumps(
                    {"quando": _adesso_cop, "presidi": {**_prima, **_r}},
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            _deriva = {
                nome: [x["elemento"] for x in v["nuovi"]] for nome, v in _r.items() if v["nuovi"]
            }
            stats["copertura"] = {
                nome: {
                    "copertura": v["copertura"],
                    "per_default": v["per_default"],
                    "nuovi": [x["elemento"] for x in v["nuovi"]],
                }
                for nome, v in _r.items()
            }
            for nome, v in _r.items():
                _era = _prima.get(nome, {}).get("copertura")
                if _era is not None and v["copertura"] < _era:
                    log.warning(
                        "coverage %s dropped from %s%% to %s%%: the world has something we"
                        " can't read",
                        nome,
                        _era,
                        v["copertura"],
                    )
            if _deriva:
                log.warning("never handled (the code uses the default branch): %s", _deriva)
        except Exception as e:  # pragma: no cover
            log.warning("coverage not measured (%s)", e)







    if not dry_run:
        try:
            import importlib.util as _il

            _perc = Path(__file__).resolve().parent.parent / "util" / "sb-ratchet.py"
            _spec = _il.spec_from_file_location("sb_ratchet_pipeline", _perc)
            _rat = _il.module_from_spec(_spec)
            sys.modules["sb_ratchet_pipeline"] = _rat
            _spec.loader.exec_module(_rat)
            _prima = _rat.carica()






            _numeri = _rat.misura(tollera_illeggibili=True)


            _giudizio = _rat.giudica(_numeri, _prima)
            _peggio, _meglio = _giudizio["peggiorati"], _giudizio["migliorati"]













            _sparite = _rat.entita_sparite(_numeri, _prima)
            _dove = _rat.scrivi_misura(_numeri, _peggio + _sparite, base=_prima)
            stats["ratchet"] = {
                "numeri": _numeri,
                "peggiorati": _peggio,
                "sparite": _sparite,
                "migliorati": _meglio,
                "entro_tolleranza": _giudizio["entro_tolleranza"],
                "scritto": _dove.name,



                "quando": json.loads(_dove.read_text(encoding="utf-8")).get("quando", ""),
            }
            if _peggio or _sparite:
                log.warning(
                    "⚠️  KB numbers WORSENED: %s — baseline NOT updated, wrote %s",
                    " · ".join(_peggio + _sparite),
                    _dove.name,
                )
            if _meglio:
                log.info("KB numbers improved: %s", " · ".join(_meglio))
        except Exception as e:  # pragma: no cover
            log.warning("ratchet not updated (%s)", e)















    import conio as _conio

    _comp_store, _pers_store = _conio.fotografia(KNOWLEDGE_ENTITIES_DIR / "person", _e_composito)
    stats["conio"] = _conio.verdetto(
        nate=stats.get("nate_person", 0),
        compositi_nati=stats.get("nate_composite", 0),
        compositi_store=_comp_store,
        persone_store=_pers_store,




        gia_scritte=not dry_run,
    )
    if stats["conio"]["rosso"]:
        log.error(_conio.riga_di_log(stats["conio"]))
    else:
        log.info(_conio.riga_di_log(stats["conio"]))





    _sent_ig = _SENTINELLA_IGNOTO
    if _sent_ig:
        stats["ignoto"] = _sent_ig.stats()
        log.info(
            "unknown (%s): %d lookups · %d bare role · %d possessive · "
            "%d marker · %d not coined",
            _sent_ig.modalita,
            _sent_ig.conteggi["consultazioni"],
            _sent_ig.conteggi["ruolo_nudo"],
            _sent_ig.conteggi["possessivo"],
            _sent_ig.conteggi["marcatore"],
            _sent_ig.conteggi["non_coniati"],
        )

    _sent = _SENTINELLA
    if _sent:
        stats["registro"] = _sent.stats()
        log.info(
            "registry (%s): %d lookups · %d split · %d variants · "
            "%d redirected · %d not coined",
            _sent.modalita,
            _sent.conteggi["consultazioni"],
            _sent.conteggi["hit_split"],
            _sent.conteggi["hit_variante"],
            _sent.conteggi["reindirizzati"],
            _sent.conteggi["non_coniati"],
        )




    stats["incremento"] = _inc_stats()
    log.info(_inc_riga_di_log())


    if not dry_run:






        if not puo_avanzare(dry_run=dry_run, entity_id=entity_id, domain=domain):
            log.info(
                "watermark NOT advanced: partial run (entity_id=%s domain=%s) — "
                "only a full run can declare rows ingested",
                entity_id,
                domain,
            )
        else:
            _get_watermark().salva()


            _salva_impronte(impronte)
        meta = {
            "last_extraction": _now_iso(),
            "sources": sources,
            "stats": stats,
        }
        meta_path = KNOWLEDGE_META_DIR / "last-extraction.json"



        safe_write_json(meta_path, meta, indent=2, ensure_ascii=True, fsync=True)

    return stats


@pipeline_step(name="l2-knowledge-extract", source="knowledge", stage="l2")
def main():
    parser = argparse.ArgumentParser(description="SBK Knowledge Store — Fact Extraction")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--source",
        choices=ALL_SOURCES + ["all"],
        default="all",
        help="Extract from specific source (default: all)",
    )
    parser.add_argument("--entity-id", help="Extract for a specific entity only")
    parser.add_argument(
        "--domain",
        choices=["person", "organization", "deal", "commitment", "all"],
        default="all",
        help="Filter by entity domain",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip entities unchanged since last run",
    )
    parser.add_argument("--workers", type=int, default=6, help="Worker count (reserved)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


    if not acquire_pid_lock("knowledge-extract", logger=log):


        log.warning("knowledge-extract: lock held by another instance, exit 75")
        sys.exit(75)

    try:
        _main_inner(args)
    finally:
        release_pid_lock("knowledge-extract")


def _main_inner(args):
    sources = None if args.source == "all" else [args.source]

    log.info("=== Knowledge Store — Fact Extraction ===")
    if args.dry_run:
        log.info("DRY RUN — no files will be written")

    stats = run_extraction(
        sources=sources,
        entity_id=args.entity_id,
        dry_run=args.dry_run,
        domain=None if args.domain == "all" else args.domain,
        incremental=args.incremental,
    )

    log.info("=== Results ===")
    log.info(
        "  Entities: %d (%d new, %d updated)",
        stats["entities"],
        stats["new_entities"],
        stats["updated_entities"],
    )
    log.info("  Facts: %d", stats["facts"])
    for src, count in stats.get("source_stats", {}).items():
        log.info("    %s: %d raw facts", src, count)










    _conio_esito = stats.get("conio") or {}
    if _conio_esito.get("rosso"):
        log.error(
            "COINING GATE RED — %s. Composite profiles are on disk; "
            "this gate signals that the block happened.",
            _conio_esito.get("perche", ""),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
