""











from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any



SOURCE_RELIABILITY: dict[str, float] = {
    "personio": 0.95,
    "docusign": 0.90,
    "attio": 0.85,
    "email": 0.80,
    "calendar": 0.75,
    "linkedin": 0.70,
    "slack": 0.65,
    "plaud": 0.55,
    "static_import": 0.90,
    "relationship_facts": 0.70,
    "deep_facts": 0.75,
}

DEFAULT_RELIABILITY = 0.60




@dataclass
class FactSource:
    source_type: str
    source_file: str
    record_id: str










    extracted_at: str | None = None




    speaker: str | None = None
    evidence_quote: str | None = None
    char_start: int | None = None
    char_end: int | None = None




    attio_record_id: str | None = None
    attio_web_url: str | None = None









































































_ARTEFATTO_SUFFISSI = (".parquet",)
_ARTEFATTO_PREFISSI = ("enriched/", "l1/", "l2/", "l3/")


def e_artefatto_rigenerato(source_file: str | None) -> bool:
    ""




    sf = str(source_file or "").strip()
    if not sf:
        return False
    return sf.endswith(_ARTEFATTO_SUFFISSI) or sf.startswith(_ARTEFATTO_PREFISSI)


@dataclass
class FactRecord:
    ""







    extracted_at: str



    artefatto_rigenerato: bool | None = None



    extractor: str | None = None
    model: str | None = None
    run_id: str | None = None


def fact_record_to_dict(r: FactRecord) -> dict:
    out: dict = {"extracted_at": r.extracted_at}

    if r.artefatto_rigenerato is not None:
        out["artefatto_rigenerato"] = r.artefatto_rigenerato
    if r.extractor is not None:
        out["extractor"] = r.extractor
    if r.model is not None:
        out["model"] = r.model
    if r.run_id is not None:
        out["run_id"] = r.run_id
    return out


def dict_to_fact_record(d: dict | None) -> FactRecord | None:
    if not d:
        return None
    return FactRecord(
        extracted_at=d.get("extracted_at", ""),
        artefatto_rigenerato=d.get("artefatto_rigenerato"),
        extractor=d.get("extractor"),
        model=d.get("model"),
        run_id=d.get("run_id"),
    )


@dataclass
class FactObservation:
    ""








    source_file: str
    record_id: str
    source_type: str
    valid_from: str | None

    extracted_at: str | None
    confidence: float
    confidence_curve: list = field(default_factory=list)




    record: FactRecord | None = None










    speaker: str | None = None
    evidence_quote: str | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class Fact:
    fact_id: str
    entity_id: str
    entity_type: str
    attribute: str
    value: Any
    confidence: float
    valid_from: str | None
    valid_to: str | None
    created_at: str
    expired_at: str | None
    source: FactSource




    record: FactRecord | None = None







    superseded_by: str | None = None





    superseded_at: str | None = None


    observations: list[FactObservation] = field(default_factory=list)












    rank: str | None = None








    ritiro: dict | None = None
    # the entity a merge moved this fact from (kept so the merge can be undone)
    source_entity_id: str | None = None


@dataclass
class EntityProfile:
    entity_id: str
    entity_type: str
    canonical_name: str
    facts: list[Fact] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version: int = 1





def fact_source_to_dict(s: FactSource) -> dict:
    out: dict = {
        "source_type": s.source_type,
        "source_file": s.source_file,
        "record_id": s.record_id,
    }



    if s.extracted_at is not None:
        out["extracted_at"] = s.extracted_at

    if s.speaker is not None:
        out["speaker"] = s.speaker
    if s.evidence_quote is not None:
        out["evidence_quote"] = s.evidence_quote
    if s.char_start is not None:
        out["char_start"] = s.char_start
    if s.char_end is not None:
        out["char_end"] = s.char_end

    if s.attio_record_id is not None:
        out["attio_record_id"] = s.attio_record_id
    if s.attio_web_url is not None:
        out["attio_web_url"] = s.attio_web_url
    return out


def dict_to_fact_source(d: dict) -> FactSource:
    return FactSource(
        source_type=d["source_type"],
        source_file=d["source_file"],
        record_id=d["record_id"],

        extracted_at=d.get("extracted_at"),
        speaker=d.get("speaker"),
        evidence_quote=d.get("evidence_quote"),
        char_start=d.get("char_start"),
        char_end=d.get("char_end"),
        attio_record_id=d.get("attio_record_id"),
        attio_web_url=d.get("attio_web_url"),
    )


def fact_observation_to_dict(o: FactObservation) -> dict:
    return {
        "source_file": o.source_file,
        "record_id": o.record_id,
        "source_type": o.source_type,
        "valid_from": o.valid_from,
        **({"extracted_at": o.extracted_at} if o.extracted_at is not None else {}),
        "confidence": o.confidence,
        "confidence_curve": list(o.confidence_curve),


        **({"record": fact_record_to_dict(o.record)} if o.record is not None else {}),

        **({"speaker": o.speaker} if o.speaker is not None else {}),
        **({"evidence_quote": o.evidence_quote} if o.evidence_quote is not None else {}),
        **({"char_start": o.char_start} if o.char_start is not None else {}),
        **({"char_end": o.char_end} if o.char_end is not None else {}),
    }


def dict_to_fact_observation(d: dict) -> FactObservation:
    return FactObservation(
        source_file=d["source_file"],
        record_id=d["record_id"],
        source_type=d["source_type"],
        valid_from=d.get("valid_from"),
        extracted_at=d.get("extracted_at"),
        confidence=d["confidence"],
        confidence_curve=list(d.get("confidence_curve", [])),
        record=dict_to_fact_record(d.get("record")),
        speaker=d.get("speaker"),
        evidence_quote=d.get("evidence_quote"),
        char_start=d.get("char_start"),
        char_end=d.get("char_end"),
    )


def fact_to_dict(f: Fact) -> dict:
    return {
        "fact_id": f.fact_id,
        "entity_id": f.entity_id,
        "entity_type": f.entity_type,
        "attribute": f.attribute,
        "value": f.value,
        "confidence": f.confidence,
        "valid_from": f.valid_from,
        "valid_to": f.valid_to,
        "created_at": f.created_at,
        "expired_at": f.expired_at,
        "source": fact_source_to_dict(f.source),

        **({"record": fact_record_to_dict(f.record)} if f.record is not None else {}),
        "superseded_by": f.superseded_by,

        **({"superseded_at": f.superseded_at} if f.superseded_at is not None else {}),

        **(
            {"observations": [fact_observation_to_dict(o) for o in f.observations]}
            if f.observations
            else {}
        ),



        **({"rank": f.rank} if f.rank else {}),


        **({"ritiro": f.ritiro} if f.ritiro else {}),
        **({"source_entity_id": f.source_entity_id} if f.source_entity_id else {}),
    }


def dict_to_fact(d: dict) -> Fact:
    return Fact(
        fact_id=d["fact_id"],
        entity_id=d["entity_id"],
        entity_type=d["entity_type"],
        attribute=d["attribute"],
        value=d["value"],
        confidence=d["confidence"],
        valid_from=d.get("valid_from"),
        valid_to=d.get("valid_to"),
        created_at=d["created_at"],
        expired_at=d.get("expired_at"),
        source=dict_to_fact_source(d["source"]),
        record=dict_to_fact_record(d.get("record")),
        superseded_by=d.get("superseded_by"),
        superseded_at=d.get("superseded_at"),
        observations=[dict_to_fact_observation(o) for o in d.get("observations", [])],
        rank=d.get("rank"),
        ritiro=d.get("ritiro"),
        source_entity_id=d.get("source_entity_id"),
    )


def profile_to_dict(p: EntityProfile) -> dict:
    return {
        "entity_id": p.entity_id,
        "entity_type": p.entity_type,
        "canonical_name": p.canonical_name,
        "facts": [fact_to_dict(f) for f in p.facts],
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "version": p.version,
    }


def dict_to_profile(d: dict) -> EntityProfile:
    return EntityProfile(
        entity_id=d["entity_id"],
        entity_type=d["entity_type"],
        canonical_name=d["canonical_name"],
        facts=[dict_to_fact(f) for f in d.get("facts", [])],
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        version=d.get("version", 1),
    )



























ATTR_CLASSE = "identity.classe"



ATTR_ATTIO_RECORD_ID = "source.attio_record_id"


CLASSE_SECONDA = "seconda_classe"




































CLASSE_PSEUDO = "pseudo_identita"





























ATTR_RISCONTRO = "identity.riscontro"





RISCONTRO_SOLO_NOMINATA = "solo_nominata"



RISCONTRI = frozenset({RISCONTRO_SOLO_NOMINATA})








CLASSI_ONTOLOGIA = frozenset({"PERSONA", "NOME-SPORCO", "NON-PERSONA", "INCERTO", "MENZIONE"})














CLASSI = CLASSI_ONTOLOGIA | {CLASSE_SECONDA, CLASSE_PSEUDO}




SEPARATORE_DISCRIMINANTE = " · attio "


def id_seconda_classe(attio_record_id: str) -> str:
    ""





    rid = (attio_record_id or "").strip()
    if not rid:
        raise ValueError("second class without attio_record_id: it is not even a pointer")
    return generate_entity_id("person", f"attio:{rid}")


def nome_discriminato(nome: str, attio_record_id: str) -> str:
    ""
    rid = (attio_record_id or "").strip()
    base = (nome or "").strip()
    if not rid:
        return base
    return f"{base}{SEPARATORE_DISCRIMINANTE}{rid[:8]}"


def nome_senza_discriminante(canonical_name: str) -> str:
    ""
    n = (canonical_name or "").strip()
    if SEPARATORE_DISCRIMINANTE in n:
        return n.split(SEPARATORE_DISCRIMINANTE)[0].strip()
    return n


def _attributo_e_valore(f) -> tuple:
    ""





    if isinstance(f, dict):
        return f.get("attribute", ""), f.get("value")
    return getattr(f, "attribute", ""), getattr(f, "value", None)


def _campo(f, nome: str):
    ""






    if isinstance(f, dict):
        return f.get(nome)
    return getattr(f, nome, None)


def valori_dichiarati(fatti, attributo: str) -> set:
    ""






    fuori = set()
    for f in fatti or ():
        attr, val = _attributo_e_valore(f)
        if attr == attributo:
            v = str(val).strip()
            if v:
                fuori.add(v)
    return fuori


def classi_dichiarate(fatti) -> set:
    ""







    return valori_dichiarati(fatti, ATTR_CLASSE)


def riscontri_dichiarati(fatti) -> set:
    ""







    return valori_dichiarati(fatti, ATTR_RISCONTRO)


def e_seconda_classe(fatti) -> bool:
    ""




    return CLASSE_SECONDA in classi_dichiarate(fatti)


def e_pseudo_identita(fatti) -> bool:
    ""
































    for f in fatti or ():
        attr, val = _attributo_e_valore(f)
        if attr != ATTR_CLASSE or str(val).strip() != CLASSE_PSEUDO:
            continue
        if not _campo(f, "source_entity_id"):
            return True
    return False


def fatto_marchio_pseudo(eid: str, *, fonte: str, quando: str | None = None) -> dict:
    ""
















    ora = quando or _now_iso()
    return {
        "fact_id": f"pseudo-{eid}",
        "entity_id": eid,
        "entity_type": "person",
        "attribute": ATTR_CLASSE,
        "value": CLASSE_PSEUDO,
        "confidence": 1.0,
        "valid_from": ora[:10],
        "valid_to": None,
        "expired_at": None,
        "created_at": ora,
        "source": {
            "source_type": "conio",
            "source_file": fonte,
            "record_id": "",
            "extracted_at": ora,
        },
    }


def e_marcata_solo_nominata(fatti) -> bool:
    ""






















    return RISCONTRO_SOLO_NOMINATA in riscontri_dichiarati(fatti)


def attio_record_id_di(fatti):
    ""
    for f in fatti or ():
        attr, val = _attributo_e_valore(f)
        if attr == ATTR_ATTIO_RECORD_ID and str(val).strip():
            return str(val).strip()
    return None












































































































FORZA_FORTE = "chiave_forte"






FORZA_DEBOLE = "identificatore_debole"







FORZA_ALTRUI = "identificatore_di_un_altro"


FORZA_NESSUNA = "non_identifica"



FORZE = (FORZA_FORTE, FORZA_DEBOLE, FORZA_ALTRUI, FORZA_NESSUNA)
















CHIAVI_FORTI: dict[str, frozenset[str]] = {
    "person": frozenset(
        {
            "contact.email",
            "identity.email",
            "contact.email_work",
            "contact.email_personal",
            "relationship.email",
            ATTR_ATTIO_RECORD_ID,
            "crm.attio_record_id",
        }
    ),






    "organization": frozenset({"organization.domain", "web.domain", "business.domain"}),
    "org": frozenset({"business.domain", "organization.domain", "web.domain"}),
}



IDENTIFICATORI_DEBOLI: dict[str, frozenset[str]] = {
    "person": frozenset(
        {

            "contact.linkedin_url",
            "contact.linkedin",
            "relationship.linkedin",
            "personal.linkedin",
            "crm.linkedin_url",



            "contact.phone",
            "relationship.phone",
            "relationship.phone_number",
            "relationship.mobile_phone",

            "contact.slack_handle",
            "contact.slack_id",
            "contact.slack_user_id",
            "contact.telegram",
            "contact.instagram",


            "identity.name",
            "identity.full_name",
            "identity.given_name",
            "identity.surname",
            "identity.alias",
            "identity.aliases",
            "identity.nickname",
        }
    ),
    "organization": frozenset({"identity.name", "organization.website", "identity.aliases"}),
    "org": frozenset({"identity.name", "identity.aliases"}),
}




IDENTIFICATORI_DI_ALTRI: frozenset[str] = frozenset({"employment.manager_email"})















_NON_E_UN_CANALE: frozenset[str] = frozenset(
    {
        "identity.name",
        "identity.full_name",
        "identity.given_name",
        "identity.surname",
        "identity.alias",
        "identity.aliases",
        "identity.nickname",
    }
)







PREFISSO_IGNOTO = "ignoto_"


_VALORI_VUOTI: frozenset[str] = frozenset({"", "none", "null", "n/a", "na", "unknown", "-", "?"})


def forza_identificativa(attributo: str, entity_type: str = "person") -> str:
    ""





    a = (attributo or "").strip()
    if not a:
        return FORZA_NESSUNA
    if a in IDENTIFICATORI_DI_ALTRI:
        return FORZA_ALTRUI
    if a in CHIAVI_FORTI.get(entity_type, frozenset()):
        return FORZA_FORTE
    if a in IDENTIFICATORI_DEBOLI.get(entity_type, frozenset()):
        return FORZA_DEBOLE
    return FORZA_NESSUNA


def fonde(attributo: str, entity_type: str = "person") -> bool:
    ""





    return forza_identificativa(attributo, entity_type) == FORZA_FORTE


def valore_identificativo(valore) -> str | None:
    ""





    if valore is None:
        return None
    v = str(valore).strip()
    if v.lower() in _VALORI_VUOTI:
        return None
    if v.startswith(PREFISSO_IGNOTO):
        return None
    if v.startswith(PREFISSI_ENTITA):
        return None
    return v.lower()


def identificatori_di(fatti, entity_type: str = "person", escludi=None) -> dict:
    ""









    fuori: dict = {FORZA_FORTE: set(), FORZA_DEBOLE: set(), FORZA_ALTRUI: set()}
    for f in fatti or ():
        attr, val = _attributo_e_valore(f)
        forza = forza_identificativa(attr, entity_type)
        if forza == FORZA_NESSUNA:
            continue
        v = valore_identificativo(val)
        if v is None:
            continue
        if escludi is not None and forza == FORZA_FORTE and escludi(v):
            continue
        fuori[forza].add(v)
    return fuori


def chiavi_forti_di(fatti, entity_type: str = "person", escludi=None) -> set:
    ""
    return identificatori_di(fatti, entity_type, escludi)[FORZA_FORTE]


def livello_identita(fatti, entity_type: str = "person", escludi=None) -> str:
    ""










    ident = identificatori_di(fatti, entity_type, escludi)
    if ident[FORZA_FORTE]:
        return FORZA_FORTE
    if ident[FORZA_DEBOLE]:
        return FORZA_DEBOLE
    return FORZA_NESSUNA


def solo_il_nome(fatti, entity_type: str = "person") -> bool:
    ""













    deboli = set()
    for f in fatti or ():
        attr, val = _attributo_e_valore(f)
        forza = forza_identificativa(attr, entity_type)
        if valore_identificativo(val) is None:
            continue
        if forza == FORZA_FORTE:
            return False
        if forza == FORZA_DEBOLE:
            deboli.add(attr)
    return bool(deboli) and deboli <= _NON_E_UN_CANALE


class ChiaveNonForte(ValueError):
    ""






def esigi_chiave_forte(attributo: str, entity_type: str = "person", dove: str = "") -> None:
    ""





    if fonde(attributo, entity_type):
        return
    forza = forza_identificativa(attributo, entity_type)
    coda = f" [{dove}]" if dove else ""
    raise ChiaveNonForte(
        f"{attributo!r} on {entity_type!r} is {forza}, not a strong key: "
        f"it cannot close a merge{coda}"
    )





def generate_entity_id(entity_type: str, name: str) -> str:
    ""



    key = f"{entity_type}:{name.strip().lower()}"
    h = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{entity_type}_{h}"


def generate_fact_id() -> str:
    ""



























    return str(uuid.uuid4())


def normalize_value(value: Any) -> str:
    ""





    return str(value).strip().lower() if value is not None else ""























def _esc(s: str) -> str:
    ""





    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("|", "\\|")


def canonical_value(value: Any) -> str:
    ""
































    if isinstance(value, bool):
        return "bool:" + ("true" if value else "false")
    if isinstance(value, int):
        return "int:" + str(value)
    if isinstance(value, str):
        return "str:" + _esc(normalize_value(value))
    if isinstance(value, list):
        return "list:[" + ",".join(canonical_value(x) for x in value) + "]"
    raise TypeError(f"assertion_hash: type not canonicalizable {type(value).__name__!r}")


def assertion_hash(
    entity_id: str,
    attribute: str,
    value: Any,
    valid_from: str | None,
) -> str:
    ""

















    vf = "null:" if valid_from is None else "str:" + _esc(valid_from)
    payload = "|".join(
        (
            "e:" + _esc(entity_id),
            "a:" + _esc(attribute),
            "v:" + canonical_value(value),
            "vf:" + vf,
        )
    )
    return "ah:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assertion_hash_del_dict(fatto: dict) -> str:
    ""





    return assertion_hash(
        fatto.get("entity_id", ""),
        fatto.get("attribute", ""),
        fatto.get("value"),
        fatto.get("valid_from"),
    )


def deterministic_fact_id(entity_id: str, attribute: str, value: Any) -> str:
    ""






























    key = f"{entity_id}|{attribute}|{normalize_value(value)}"
    return "f:" + hashlib.sha256(key.encode()).hexdigest()[:16]


































PREFISSI_ENTITA: tuple[str, ...] = (
    "person_",
    "organization_",
    "org_",
    "deal_",
    "commitment_",
)


def _e_fact_id(valore: str) -> bool:
    ""





    v = str(valore or "")
    if v.startswith("f:") and len(v) > 2:
        return True
    try:
        uuid.UUID(v)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def valida_supersessione(fatto: dict) -> list[str]:
    ""

















    valore = fatto.get("superseded_by")
    if not valore:
        return []

    violazioni: list[str] = []
    v = str(valore)
    if v.startswith(PREFISSI_ENTITA):
        violazioni.append(
            f"superseded_by={v!r} is an entity_id, not a fact_id: it must name "
            "the ASSERTION that takes the place of this one, not the entity"
        )
    elif not _e_fact_id(v):
        violazioni.append(f"superseded_by={v!r} does not have the form of a fact_id (UUID or 'f:…')")

    quando = fatto.get("superseded_at")
    if not quando:
        violazioni.append(
            "superseded_at missing: required together with superseded_by, or the fact "
            "stays excluded even from questions about the past prior to the replacement"
        )
    else:
        try:
            datetime.fromisoformat(str(quando).replace("Z", "+00:00"))
        except ValueError:
            violazioni.append(
                f"superseded_at={quando!r} is not an ISO date (YYYY-MM-DD or timestamp)"
            )

    return violazioni


def esigi_supersessione_valida(fatto: dict, dove: str = "") -> None:
    ""





    violazioni = valida_supersessione(fatto)
    if violazioni:
        prefisso = f"{dove}: " if dove else ""
        raise ValueError(
            prefisso
            + "`superseded_by` contract violated — "
            + " · ".join(violazioni)
            + " (see valida_supersessione in knowledge_schema.py)"
        )





def compute_confidence(
    source_type: str,
    n_sources: int = 1,
    days_old: float = 0.0,
    quality_modifier: float = 1.0,
) -> float:
    ""






    base = SOURCE_RELIABILITY.get(source_type, DEFAULT_RELIABILITY)


    if quality_modifier != 1.0:
        base = base * quality_modifier


    if n_sources > 1:
        base = min(1.0, base * (1 + 0.1 * (n_sources - 1)))


    decay = max(0.5, 1.0 - days_old / 730)

    return round(min(1.0, base * decay), 4)





def ensure_knowledge_dirs() -> None:
    ""

    import sbk_config as cfg

    for d in [
        cfg.KNOWLEDGE_DIR,
        cfg.KNOWLEDGE_ENTITIES_DIR,
        cfg.KNOWLEDGE_ENTITIES_DIR / "person",
        cfg.KNOWLEDGE_ENTITIES_DIR / "organization",
        cfg.KNOWLEDGE_ENTITIES_DIR / "deal",
        cfg.KNOWLEDGE_ENTITIES_DIR / "commitment",
        cfg.KNOWLEDGE_FACTS_DIR,
        cfg.KNOWLEDGE_FACTS_DIR / "person",
        cfg.KNOWLEDGE_FACTS_DIR / "organization",
        cfg.KNOWLEDGE_FACTS_DIR / "deal",
        cfg.KNOWLEDGE_FACTS_DIR / "commitment",
        cfg.KNOWLEDGE_CONFLICTS_DIR,
        cfg.KNOWLEDGE_SNAPSHOTS_DIR,
        cfg.KNOWLEDGE_META_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)





def _now_iso() -> str:
    return datetime.now(UTC).isoformat()






























CAMPI_RECORD: frozenset[str] = frozenset(
    {"extracted_at", "artefatto_rigenerato", "extractor", "model", "run_id"}
)









CAMPI_RECORD_OMBRA: frozenset[str] = frozenset({"created_at", "source_entity_id"})


CAMPI_VIETATI_IN_CHIAVE: frozenset[str] = CAMPI_RECORD | CAMPI_RECORD_OMBRA



_SENTINELLA = "\x00sentinella-invariante-13\x00"


class InvarianteRecordViolato(RuntimeError):
    ""


def esigi_niente_record(nomi, dove: str = "") -> None:
    ""




    colpevoli = sorted({str(n) for n in nomi} & CAMPI_VIETATI_IN_CHIAVE)
    if colpevoli:
        prefisso = f"{dove}: " if dove else ""
        raise InvarianteRecordViolato(
            prefisso
            + "identity invariant violated — "
            + ", ".join(colpevoli)
            + " are RECORD fields (or shadow copies of them) and cannot enter "
            "an identifier, a dedup key, an anchor or a conflict comparison. "
            "Otherwise the record changes on every run without the world "
            "changing and the facts de-anchor in bulk."
        )


def _perturba_record(fatto: dict) -> dict:
    ""




    f = dict(fatto)
    if isinstance(f.get("record"), dict):
        f["record"] = dict.fromkeys(f["record"], _SENTINELLA)
    for k in CAMPI_RECORD_OMBRA:
        if k in f:
            f[k] = _SENTINELLA
    src = f.get("source")
    if isinstance(src, dict) and "extracted_at" in src:
        src = dict(src)
        src["extracted_at"] = _SENTINELLA
        f["source"] = src
    oss = f.get("observations")
    if isinstance(oss, list):
        nuove = []
        for o in oss:
            if not isinstance(o, dict):
                nuove.append(o)
                continue
            o = dict(o)
            if "extracted_at" in o:
                o["extracted_at"] = _SENTINELLA
            if isinstance(o.get("record"), dict):
                o["record"] = dict.fromkeys(o["record"], _SENTINELLA)
            nuove.append(o)
        f["observations"] = nuove
    return f


def _perturba_fonte(fatto: dict) -> dict:
    ""




    f = dict(fatto)
    src = dict(f.get("source") or {})
    src["record_id"] = _SENTINELLA
    f["source"] = src
    return f


def esigi_chiave_indifferente_al_record(fatto: dict, fn_chiave, dove: str = "") -> None:
    ""












    prefisso = f"{dove}: " if dove else ""
    base = fn_chiave(fatto)
    if fn_chiave(_perturba_record(fatto)) != base:
        raise InvarianteRecordViolato(
            prefisso + "identity invariant violated (prong 1) — the key CHANGES when the record "
            "fields change. Two runs of the pipeline on the same input "
            "would produce two different identities for the same assertion."
        )
    if fn_chiave(_perturba_fonte(fatto)) == base:
        raise InvarianteRecordViolato(
            prefisso + "identity invariant violated (prong 2) — the key does NOT change when "
            "`source.record_id` changes. A key insensitive to the source passes prong 1 "
            "by constancy: it would merge two distinct pieces of evidence for the same assertion."
        )
