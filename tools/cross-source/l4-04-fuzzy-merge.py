#!/usr/bin/env python3
""
































from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import jellyfish

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from entity_dedup_index import normalize_name  # noqa: E402
from knowledge_schema import (  # noqa: E402
    CHIAVI_FORTI,
    FORZA_ALTRUI,
    FORZA_DEBOLE,
    FORZA_FORTE,
    IDENTIFICATORI_DEBOLI,
    attio_record_id_di,
    e_seconda_classe,
    identificatori_di,
)

from sbk_config import (  # noqa: E402
    KNOWLEDGE_ENTITIES_DIR,
    QUALITY_METRICS_DIR,
    safe_write_json,
)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from confrontabile import ENV_BLOCCA, blocca_attivo, giudica  # noqa: E402
from journal_fusioni import Journal  # noqa: E402

log = logging.getLogger("sbk-l4-04-fuzzy-merge")



PERSON_DIR = KNOWLEDGE_ENTITIES_DIR / "person"
ARCHIVE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "archive" / "deduped"
RUN_LOG = QUALITY_METRICS_DIR / "l4-04-run-log.jsonl"
REVIEW_QUEUE_DIR = KNOWLEDGE_ENTITIES_DIR.parent / "review-queue"
REVIEW_QUEUE_FILE = REVIEW_QUEUE_DIR / "fuzzy-merge-candidates.json"
NAME_VARIANTS_FILE = KNOWLEDGE_ENTITIES_DIR.parent / "name-variants.json"



SKIP_NAMES = {
    "client",
    "team",
    "disclosers",
    "unknown",
    "user",
    "admin",
    "system",
    "bot",
    "automated",
    "notification",
    "support",
}

_ORG_TOKENS = {"srl", "spa", "ltd", "llc", "gmbh", "team", "group"}










_EMAIL_ATTRS = {a for a in CHIAVI_FORTI["person"] if "email" in a}
_PHONE_ATTRS = {a for a in IDENTIFICATORI_DEBOLI["person"] if "phone" in a}
_LINKEDIN_ATTRS = {a for a in IDENTIFICATORI_DEBOLI["person"] if "linkedin" in a}





_EMAIL_ATTRS_STORICI = {"contact.email"}
_PHONE_ATTRS_STORICI = {"contact.phone", "relationship.phone", "relationship.phone_number"}
_LINKEDIN_ATTRS_STORICI = {"contact.linkedin_url"}



ENV_CHIAVI = "SBK_CHIAVI_FORTI"


def chiavi_forti_attive() -> bool:
    ""
    import os

    return os.environ.get(ENV_CHIAVI, "").strip().lower() in ("1", "true", "yes", "si")


def attrs_email() -> set:
    ""
    return _EMAIL_ATTRS if chiavi_forti_attive() else _EMAIL_ATTRS_STORICI


def attrs_phone() -> set:
    return _PHONE_ATTRS if chiavi_forti_attive() else _PHONE_ATTRS_STORICI


def attrs_linkedin() -> set:
    return _LINKEDIN_ATTRS if chiavi_forti_attive() else _LINKEDIN_ATTRS_STORICI


_COMPANY_ATTRS = {
    "crm.company",
    "employment.company",
    "relationship.works_at",
    "relationship.company",
}


SIGNAL_WEIGHTS: dict[str, float] = {
    "same_email": 0.8,
    "same_email_domain": 0.5,
    "same_company": 0.7,
    "same_phone": 0.95,
    "same_linkedin": 0.95,
    "name_variant_confirmed": 0.85,
}















_ANCHOR_SIGNALS_STORICI = {"same_email", "same_phone", "same_linkedin"}
_ANCHOR_SIGNALS_DICHIARATI = {"same_email"}


def anchor_signals() -> set:
    ""
    return _ANCHOR_SIGNALS_DICHIARATI if chiavi_forti_attive() else _ANCHOR_SIGNALS_STORICI





_ANCHOR_SIGNALS = _ANCHOR_SIGNALS_STORICI


_DECAY_MONTHS = 6
_DECAY_FACTOR = 0.3


_PHONE_CLEAN_RE = re.compile(r"[^\d+]")





def _split_name(canonical_name: str) -> tuple[str, str]:
    ""




    normalized = normalize_name(canonical_name)
    parts = normalized.split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def _jw_name_score(name_a: str, name_b: str) -> float:
    ""




    first_a, last_a = _split_name(name_a)
    first_b, last_b = _split_name(name_b)

    if not first_a or not first_b:
        return 0.0

    jw_first = jellyfish.jaro_winkler_similarity(first_a, first_b)


    if not last_a or not last_b:
        return jw_first

    jw_last = jellyfish.jaro_winkler_similarity(last_a, last_b)
    return min(jw_first, jw_last)


def _normalize_phone(phone: str) -> str:
    ""
    cleaned = _PHONE_CLEAN_RE.sub("", str(phone).strip())

    return cleaned


def _extract_email_domain(email: str) -> str:
    ""
    if "@" in email:
        return email.split("@", 1)[1].strip().lower()
    return ""


def _fact_age_months(fact: dict, now: datetime) -> float:
    ""
    created_str = fact.get("created_at", "")
    if not created_str:
        return 0.0
    try:
        created = datetime.fromisoformat(str(created_str).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        delta = now - created
        return delta.days / 30.0
    except (ValueError, TypeError):
        return 0.0


def _apply_decay(weight: float, age_months: float) -> float:
    ""
    if age_months > _DECAY_MONTHS:
        return weight * _DECAY_FACTOR
    return weight


def _load_name_variants() -> dict[str, set[str]]:
    ""
    variants: dict[str, set[str]] = {}
    if not NAME_VARIANTS_FILE.exists():
        log.debug("name-variants.json not found, skipping variant matching")
        return variants
    try:
        data = json.loads(NAME_VARIANTS_FILE.read_text(encoding="utf-8"))
        for canonical, alts in data.items():
            key = canonical.strip().lower()
            alt_set = {a.strip().lower() for a in alts if a.strip()}
            alt_set.add(key)

            for name in alt_set:
                variants.setdefault(name, set()).update(alt_set)
        log.debug("Loaded %d name variant clusters", len(data))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load name-variants.json: %s", exc)
    return variants


def _extract_fact_values(facts: list[dict], attrs: set[str]) -> list[tuple[str, dict]]:
    ""
    results = []
    for f in facts:
        attr = f.get("attribute", "")
        if attr in attrs:
            val = str(f.get("value", "")).strip()
            if val:
                results.append((val, f))
    return results





def load_person_entities(person_dir: Path | None = None) -> list[dict]:
    ""
    pdir = person_dir or PERSON_DIR
    entities = []

    for f in sorted(pdir.iterdir()):
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("canonical_name", "")
            entity_id = data.get("entity_id", "")
            if not name or not entity_id:
                continue

            if name.startswith("person_"):
                continue
            normalized = normalize_name(name)
            if not normalized or normalized in SKIP_NAMES:
                continue

            if any(tok in normalized.split() for tok in _ORG_TOKENS):
                continue

            fatti = data.get("facts", [])
            entities.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": name,
                    "normalized_name": normalized,
                    "facts": fatti,
                    "file_path": str(f),






                    "seconda_classe": e_seconda_classe(fatti),
                    "attio_record_id": attio_record_id_di(fatti),






                    "giudizio_nome": giudica(name, "person", entity_id=entity_id),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    log.info("Loaded %d person entities", len(entities))
    return entities





def build_blocks(entities: list[dict]) -> dict[str, list[int]]:
    ""



    blocks: dict[str, list[int]] = defaultdict(list)

    for idx, ent in enumerate(entities):
        first, last = _split_name(ent["canonical_name"])
        if not first:
            continue

        first_2 = first[:2]

        if last:
            try:
                mp = jellyfish.metaphone(last)
            except Exception:
                mp = last[:3]
        else:

            try:
                mp = jellyfish.metaphone(first)
            except Exception:
                mp = first[:3]

        block_key = f"{mp}|{first_2}"
        blocks[block_key].append(idx)

    log.info(
        "Built %d blocks, avg %.1f entities/block",
        len(blocks),
        sum(len(v) for v in blocks.values()) / max(len(blocks), 1),
    )
    return blocks





def find_confirming_signals(
    ent_a: dict,
    ent_b: dict,
    name_variants: dict[str, set[str]],
    now: datetime,
) -> list[dict]:
    ""



    signals = []
    facts_a = ent_a["facts"]
    facts_b = ent_b["facts"]


    emails_a = _extract_fact_values(facts_a, attrs_email())
    emails_b = _extract_fact_values(facts_b, attrs_email())
    email_set_a = {v.lower() for v, _ in emails_a}
    email_set_b = {v.lower() for v, _ in emails_b}
    common_emails = email_set_a & email_set_b

    if common_emails:

        all_email_facts = [f for _, f in emails_a] + [f for _, f in emails_b]
        min_age = min((_fact_age_months(f, now) for f in all_email_facts), default=0)
        weight = _apply_decay(SIGNAL_WEIGHTS["same_email"], min_age)
        signals.append(
            {
                "type": "same_email",
                "value": ", ".join(sorted(common_emails)),
                "weight": weight,
                "is_anchor": True,
            }
        )
    else:

        domains_a = {_extract_email_domain(v) for v, _ in emails_a if _extract_email_domain(v)}
        domains_b = {_extract_email_domain(v) for v, _ in emails_b if _extract_email_domain(v)}
        common_domains = domains_a & domains_b

        generic_domains = {
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
            "live.com",
            "me.com",
            "protonmail.com",
            "mail.com",
            "aol.com",
        }
        common_domains -= generic_domains
        if common_domains:
            all_email_facts = [f for _, f in emails_a] + [f for _, f in emails_b]
            min_age = min((_fact_age_months(f, now) for f in all_email_facts), default=0)
            weight = _apply_decay(SIGNAL_WEIGHTS["same_email_domain"], min_age)
            signals.append(
                {
                    "type": "same_email_domain",
                    "value": ", ".join(sorted(common_domains)),
                    "weight": weight,
                    "is_anchor": False,
                }
            )


    phones_a = _extract_fact_values(facts_a, attrs_phone())
    phones_b = _extract_fact_values(facts_b, attrs_phone())
    phone_set_a = {_normalize_phone(v) for v, _ in phones_a if _normalize_phone(v)}
    phone_set_b = {_normalize_phone(v) for v, _ in phones_b if _normalize_phone(v)}
    common_phones = phone_set_a & phone_set_b

    if common_phones:
        all_phone_facts = [f for _, f in phones_a] + [f for _, f in phones_b]
        min_age = min((_fact_age_months(f, now) for f in all_phone_facts), default=0)
        weight = _apply_decay(SIGNAL_WEIGHTS["same_phone"], min_age)


        ancora_telefono = "same_phone" in anchor_signals()
        signals.append(
            {
                "type": "same_phone",
                "value": ", ".join(sorted(common_phones)),
                "weight": weight,
                "is_anchor": ancora_telefono,
            }
        )


    li_a = _extract_fact_values(facts_a, attrs_linkedin())
    li_b = _extract_fact_values(facts_b, attrs_linkedin())
    li_set_a = {v.rstrip("/").lower() for v, _ in li_a}
    li_set_b = {v.rstrip("/").lower() for v, _ in li_b}
    common_li = li_set_a & li_set_b

    if common_li:
        all_li_facts = [f for _, f in li_a] + [f for _, f in li_b]
        min_age = min((_fact_age_months(f, now) for f in all_li_facts), default=0)
        weight = _apply_decay(SIGNAL_WEIGHTS["same_linkedin"], min_age)

















        secondo = bool(ent_a.get("seconda_classe")) or bool(ent_b.get("seconda_classe"))
        ancora_linkedin = "same_linkedin" in anchor_signals()
        signals.append(
            {
                "type": "same_linkedin",
                "value": ", ".join(sorted(common_li)),
                "weight": weight,
                "is_anchor": ancora_linkedin and not secondo,
            }
        )


    companies_a = _extract_fact_values(facts_a, _COMPANY_ATTRS)
    companies_b = _extract_fact_values(facts_b, _COMPANY_ATTRS)

    if companies_a and companies_b:
        company_matched = False
        best_company = ""
        min_age_company = 0.0
        for val_a, fact_a in companies_a:
            for val_b, fact_b in companies_b:
                norm_a = val_a.strip().lower()
                norm_b = val_b.strip().lower()
                if not norm_a or not norm_b:
                    continue

                company_jw = jellyfish.jaro_winkler_similarity(norm_a, norm_b)
                if company_jw >= 0.85:
                    age = min(
                        _fact_age_months(fact_a, now),
                        _fact_age_months(fact_b, now),
                    )
                    if not company_matched or age < min_age_company:
                        min_age_company = age
                        best_company = val_a
                    company_matched = True
        if company_matched:
            weight = _apply_decay(SIGNAL_WEIGHTS["same_company"], min_age_company)
            signals.append(
                {
                    "type": "same_company",
                    "value": best_company,
                    "weight": weight,
                    "is_anchor": False,
                }
            )


    if name_variants:
        first_a, _ = _split_name(ent_a["canonical_name"])
        first_b, _ = _split_name(ent_b["canonical_name"])
        if first_a and first_b:
            variants_a = name_variants.get(first_a, set())
            if first_b in variants_a:
                signals.append(
                    {
                        "type": "name_variant_confirmed",
                        "value": f"{first_a} ~ {first_b}",
                        "weight": SIGNAL_WEIGHTS["name_variant_confirmed"],
                        "is_anchor": False,
                    }
                )

    return signals





def calculate_confidence(jw_score: float, signals: list[dict]) -> float:
    ""




    fact_boost = min(0.3, sum(s["weight"] * 0.15 for s in signals))
    confidence = min(0.99, jw_score * 0.7 + fact_boost + 0.1)
    return round(confidence, 4)





def classify_pair(
    jw_score: float,
    confidence: float,
    signals: list[dict],
) -> str:
    ""



    has_anchor = any(s.get("is_anchor") for s in signals)
    n_signals = len(signals)


    if confidence >= 0.95 and has_anchor:
        if jw_score >= 0.95:
            return "auto_merge"
        if jw_score >= 0.92 and n_signals >= 2:
            return "auto_merge"


    if confidence >= 0.80 and jw_score >= 0.85 and n_signals >= 1:
        return "review"

    return "reject"





def generate_candidates(
    entities: list[dict],
    blocks: dict[str, list[int]],
    name_variants: dict[str, set[str]],
    now: datetime,
) -> tuple[list[dict], list[dict]]:
    ""






    seen_pairs: set[tuple[str, str]] = set()
    auto_candidates: list[dict] = []
    review_candidates: list[dict] = []


    coppie_unsure: list[tuple[dict, dict, object]] = []

    for block_key, indices in blocks.items():
        if len(indices) < 2:
            continue
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                idx_a, idx_b = indices[i], indices[j]
                ent_a = entities[idx_a]
                ent_b = entities[idx_b]

                pair_key = tuple(sorted([ent_a["entity_id"], ent_b["entity_id"]]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)








                if ent_a.get("seconda_classe") or ent_b.get("seconda_classe"):
                    continue






                _ga = ent_a.get("giudizio_nome")
                _gb = ent_b.get("giudizio_nome")
                if (_ga is not None and not _ga.ok) or (_gb is not None and not _gb.ok):
                    _g = _ga if (_ga is not None and not _ga.ok) else _gb
                    coppie_unsure.append((ent_a, ent_b, _g))
                    if blocca_attivo():
                        continue


                jw = _jw_name_score(ent_a["canonical_name"], ent_b["canonical_name"])
                if jw < 0.85:
                    continue


                signals = find_confirming_signals(ent_a, ent_b, name_variants, now)


                confidence = calculate_confidence(jw, signals)


                band = classify_pair(jw, confidence, signals)

                if band == "reject":
                    continue

                candidate = {
                    "entity_a_id": ent_a["entity_id"],
                    "entity_a_name": ent_a["canonical_name"],
                    "entity_a_facts": len(ent_a["facts"]),
                    "entity_a_path": ent_a["file_path"],
                    "entity_b_id": ent_b["entity_id"],
                    "entity_b_name": ent_b["canonical_name"],
                    "entity_b_facts": len(ent_b["facts"]),
                    "entity_b_path": ent_b["file_path"],
                    "jw_score": round(jw, 4),
                    "signals": signals,
                    "confidence": confidence,
                    "band": band,
                }

                if band == "auto_merge":
                    auto_candidates.append(candidate)
                else:
                    review_candidates.append(candidate)


    auto_candidates.sort(key=lambda c: -c["confidence"])
    review_candidates.sort(key=lambda c: -c["confidence"])

    log.info(
        "Candidate pairs: %d auto-merge, %d review, %d total seen",
        len(auto_candidates),
        len(review_candidates),
        len(seen_pairs),
    )



    if coppie_unsure:
        log.info(
            "Name not comparable: %d pairs out of %d — %s",
            len(coppie_unsure),
            len(seen_pairs),
            "BLOCKED" if blocca_attivo() else "COUNTED, not blocked",
        )
        for a, b, g in coppie_unsure[:10]:
            log.info(
                "  · «%s» ~ «%s»  %s",
                a["canonical_name"][:34],
                b["canonical_name"][:34],
                (g.ragioni[0] if g is not None and g.ragioni else "?"),
            )
        if len(coppie_unsure) > 10:
            log.info("  ... and %d more", len(coppie_unsure) - 10)
        if not blocca_attivo():
            log.info("  to actually block them: %s=1  (now: off)", ENV_BLOCCA)
    else:
        log.info("Name not comparable: no pairs")
    return auto_candidates, review_candidates


def censisci_seconde_classi(entities: list[dict]) -> dict:
    ""





    seconde = [e for e in entities if e.get("seconda_classe")]
    esempi = [
        f"{e['entity_id']}  «{e['canonical_name'][:48]}»  "
        f"attio:{(e.get('attio_record_id') or '?')[:8]}  [{len(e['facts'])} fatti]"
        for e in sorted(seconde, key=lambda x: -len(x["facts"]))[:10]
    ]
    return {"quante": len(seconde), "su": len(entities), "esempi": esempi}


def censisci_nomi_non_confrontabili(entities: list[dict]) -> dict:
    ""







    fuori = [
        e for e in entities if e.get("giudizio_nome") is not None and not e["giudizio_nome"].ok
    ]
    per_codice: dict[str, int] = {}
    for e in fuori:
        for c in e["giudizio_nome"].codici:
            per_codice[c] = per_codice.get(c, 0) + 1
    esempi = [
        f"{e['entity_id']}  «{e['canonical_name'][:44]}»  [{len(e['facts'])} fatti]  "
        f"{e['giudizio_nome'].ragioni[0]}"
        for e in sorted(fuori, key=lambda x: -len(x["facts"]))[:10]
    ]
    return {
        "quante": len(fuori),
        "su": len(entities),
        "per_codice": per_codice,
        "esempi": esempi,
    }


def censisci_chiavi_forti(entities: list[dict]) -> dict:
    ""










    quante = {"forte": 0, "debole": 0, "niente": 0, "altrui": 0}
    for e in entities:
        ident = identificatori_di(e.get("facts") or (), "person", escludi=_e_casella())
        if ident[FORZA_FORTE]:
            quante["forte"] += 1
        elif ident[FORZA_DEBOLE]:
            quante["debole"] += 1
        else:
            quante["niente"] += 1
        if ident[FORZA_ALTRUI]:
            quante["altrui"] += 1
    su = len(entities)
    return {
        "su": su,
        "forte": quante["forte"],
        "forte_pct": round(100.0 * quante["forte"] / su, 2) if su else 0.0,
        "debole": quante["debole"],
        "niente": quante["niente"],
        "altrui": quante["altrui"],
    }


def _e_casella():
    ""





    try:
        from confrontabile import _sb_persone

        return _sb_persone().e_casella
    except Exception:  # pragma: no cover - dipende dal disco
        return None





def merge_pair(
    candidate: dict, dry_run: bool = True, method: str = "l4-04-fuzzy-auto", journal=None
) -> dict | None:
    ""



    path_a = Path(candidate["entity_a_path"])
    path_b = Path(candidate["entity_b_path"])

    if not path_a.exists() or not path_b.exists():
        log.warning(
            "Skipping merge %s <-> %s: file(s) missing",
            candidate["entity_a_id"],
            candidate["entity_b_id"],
        )
        return None

    data_a = json.loads(path_a.read_text(encoding="utf-8"))
    data_b = json.loads(path_b.read_text(encoding="utf-8"))

    facts_a = data_a.get("facts", [])
    facts_b = data_b.get("facts", [])


    if len(facts_a) >= len(facts_b):
        canonical_data, canonical_path = data_a, path_a
        non_canonical_data, non_canonical_path = data_b, path_b
        canonical_id = candidate["entity_a_id"]
        merged_id = candidate["entity_b_id"]
    else:
        canonical_data, canonical_path = data_b, path_b
        non_canonical_data, non_canonical_path = data_a, path_a
        canonical_id = candidate["entity_b_id"]
        merged_id = candidate["entity_a_id"]

    original_facts = len(canonical_data.get("facts", []))


    existing_keys = {
        (f.get("attribute", ""), str(f.get("value", "")).strip().lower())
        for f in canonical_data.get("facts", [])
    }

    facts_gained = 0
    _canon_id = canonical_data.get("entity_id", "")



    if journal is not None:
        journal.fusione(
            _canon_id,
            merged_id,
            motivo=f"{method}: jw={candidate.get('jw_score')} conf={candidate.get('confidence')}",
            punteggi={"segnali": candidate.get("signals")},
        )
    for fact in non_canonical_data.get("facts", []):
        key = (fact.get("attribute", ""), str(fact.get("value", "")).strip().lower())
        if key not in existing_keys:

            canonical_data["facts"].append(
                {**fact, "entity_id": _canon_id, "source_entity_id": fact.get("entity_id")}
            )
            if journal is not None:
                journal.fatto(fact, da=merged_id, a=_canon_id)
            existing_keys.add(key)
            facts_gained += 1
        elif journal is not None:
            journal.fatto_scartato(fact, da=merged_id, perche="duplicate (attribute,value)")


    nc_name = non_canonical_data.get("canonical_name", "")
    can_name = canonical_data.get("canonical_name", "")
    if len(nc_name) > len(can_name) and not nc_name.startswith("person_"):
        canonical_data["canonical_name"] = nc_name

    if not dry_run:

        safe_write_json(canonical_path, canonical_data, backup=True)


        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_data = {
            **non_canonical_data,
            "status": "deduped",
            "merged_into": canonical_id,
            "merged_date": datetime.now(UTC).isoformat(),
            "merged_by": method,
        }
        safe_write_json(ARCHIVE_DIR / non_canonical_path.name, archive_data)
        non_canonical_path.unlink(missing_ok=True)

    return {
        "canonical_id": canonical_id,
        "merged_id": merged_id,
        "name_a": candidate["entity_a_name"],
        "name_b": candidate["entity_b_name"],
        "jw_score": candidate["jw_score"],
        "confidence": candidate["confidence"],
        "signals": [
            {"type": s["type"], "value": s["value"], "weight": s["weight"]}
            for s in candidate["signals"]
        ],
        "facts_before": original_facts,
        "facts_after": len(canonical_data.get("facts", [])),
        "facts_gained": facts_gained,
        "method": method,
    }





def write_review_queue(candidates: list[dict]) -> Path:
    ""
    REVIEW_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    queue_items = []
    for idx, c in enumerate(candidates, 1):
        queue_items.append(
            {
                "id": f"fmc-{idx:04d}",
                "entity_a": {
                    "entity_id": c["entity_a_id"],
                    "name": c["entity_a_name"],
                    "facts_count": c["entity_a_facts"],
                },
                "entity_b": {
                    "entity_id": c["entity_b_id"],
                    "name": c["entity_b_name"],
                    "facts_count": c["entity_b_facts"],
                },
                "jw_score": c["jw_score"],
                "confirming_facts": [
                    {"type": s["type"], "value": s["value"], "weight": round(s["weight"], 3)}
                    for s in c["signals"]
                ],
                "confidence": c["confidence"],
                "proposed_action": "merge",
                "status": "pending",
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    queue_data = {
        "version": 1,
        "generated": datetime.now(UTC).isoformat(),
        "candidates": queue_items,
        "stats": {
            "total_candidates": len(queue_items),
            "pending": len(queue_items),
            "approved": 0,
            "rejected": 0,
        },
    }

    safe_write_json(REVIEW_QUEUE_FILE, queue_data)
    return REVIEW_QUEUE_FILE


def load_review_queue() -> dict:
    ""
    if not REVIEW_QUEUE_FILE.exists():
        log.error("Review queue file not found: %s", REVIEW_QUEUE_FILE)
        return {"candidates": []}
    return json.loads(REVIEW_QUEUE_FILE.read_text(encoding="utf-8"))


def apply_reviewed_merges(person_dir: Path | None = None, dry_run: bool = False) -> list[dict]:
    ""
    queue = load_review_queue()
    candidates = queue.get("candidates", [])
    approved = [c for c in candidates if c.get("status") == "approved"]

    if not approved:
        log.info("No approved candidates in review queue")
        return []

    log.info("Found %d approved candidates to apply", len(approved))
    results = []

    pdir = person_dir or PERSON_DIR
    for c in approved:

        ea_id = c["entity_a"]["entity_id"]
        eb_id = c["entity_b"]["entity_id"]


        path_a = pdir / f"{ea_id}.json"
        path_b = pdir / f"{eb_id}.json"

        if not path_a.exists() or not path_b.exists():
            log.warning("Skipping approved merge %s <-> %s: file(s) missing", ea_id, eb_id)
            c["status"] = "skipped"
            continue

        data_a = json.loads(path_a.read_text(encoding="utf-8"))
        data_b = json.loads(path_b.read_text(encoding="utf-8"))

        merge_candidate = {
            "entity_a_id": ea_id,
            "entity_a_name": c["entity_a"].get("name", ""),
            "entity_a_facts": len(data_a.get("facts", [])),
            "entity_a_path": str(path_a),
            "entity_b_id": eb_id,
            "entity_b_name": c["entity_b"].get("name", ""),
            "entity_b_facts": len(data_b.get("facts", [])),
            "entity_b_path": str(path_b),
            "jw_score": c.get("jw_score", 0),
            "signals": [
                {"type": s["type"], "value": s["value"], "weight": s["weight"], "is_anchor": False}
                for s in c.get("confirming_facts", [])
            ],
            "confidence": c.get("confidence", 0),
            "band": "reviewed",
        }

        with Journal("l4-04-fuzzy-reviewed", attivo=not dry_run) as _j:
            result = merge_pair(
                merge_candidate, dry_run=dry_run, method="l4-04-fuzzy-reviewed", journal=_j
            )
        if result:
            results.append(result)
            c["status"] = "applied" if not dry_run else "approved"


    if not dry_run and results:
        n_applied = sum(1 for c in candidates if c.get("status") == "applied")
        n_pending = sum(1 for c in candidates if c.get("status") == "pending")
        n_approved = sum(1 for c in candidates if c.get("status") == "approved")
        n_rejected = sum(1 for c in candidates if c.get("status") == "rejected")
        queue["stats"] = {
            "total_candidates": len(candidates),
            "pending": n_pending,
            "approved": n_approved,
            "rejected": n_rejected,
            "applied": n_applied,
        }
        safe_write_json(REVIEW_QUEUE_FILE, queue)

    return results





def write_run_log(results: list[dict]) -> None:
    ""
    QUALITY_METRICS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        for r in results:
            entry = {
                **r,
                "timestamp": datetime.now(UTC).isoformat(),
                "module": "l4-04-fuzzy-merge",
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")





def main():
    parser = argparse.ArgumentParser(
        description="L4-04: Fuzzy Entity Merge with Confirmation Signals"
    )
    parser.add_argument("--auto", action="store_true", help="Execute auto-merge (high confidence)")
    parser.add_argument("--review", action="store_true", help="Generate review queue JSON")
    parser.add_argument(
        "--apply-reviewed",
        action="store_true",
        help="Apply approved merges from review queue",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default behavior)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


    dry_run = args.dry_run or not (args.auto or args.review or args.apply_reviewed)

    log.info("=" * 60)
    log.info("L4-04 Fuzzy Merge — %s", "DRY RUN" if dry_run else "LIVE")
    if args.apply_reviewed:
        log.info("Mode: apply-reviewed")
    elif args.review:
        log.info("Mode: review queue generation")
    elif args.auto:
        log.info("Mode: auto-merge")
    else:
        log.info("Mode: dry-run preview")
    log.info("=" * 60)


    if args.apply_reviewed:
        results = apply_reviewed_merges(dry_run=dry_run)
        if results and not dry_run:
            write_run_log(results)
        log.info("")
        log.info("=" * 60)
        log.info("Apply-reviewed summary (%s):", "DRY RUN" if dry_run else "APPLIED")
        log.info("  Merges executed: %d", len(results))
        total_facts = sum(r.get("facts_gained", 0) for r in results)
        log.info("  Facts gained: %d", total_facts)
        log.info("=" * 60)
        return


    log.info("Loading person entities...")
    entities = load_person_entities()



    censo_chiavi = censisci_chiavi_forti(entities)
    log.info(
        "Strong keys: %d of %d entities (%.2f%%). The target is not 100%%.",
        censo_chiavi["forte"],
        censo_chiavi["su"],
        censo_chiavi["forte_pct"],
    )
    log.info(
        "  weak identifier (NEVER merges): %d · no identifier: %d",
        censo_chiavi["debole"],
        censo_chiavi["niente"],
    )
    if censo_chiavi["altrui"]:
        log.info(
            "  ⚠️ %d entities carry SOMEONE ELSE's key (`employment.manager_email`): "
            "it's the manager's email, not theirs",
            censo_chiavi["altrui"],
        )
    log.info(
        "  anchors for this run: %s   (strong keys %s with %s=1)",
        ", ".join(sorted(anchor_signals())),
        "ON" if chiavi_forti_attive() else "off: turn it on",
        ENV_CHIAVI,
    )


    censimento = censisci_seconde_classi(entities)
    if censimento["quante"]:
        log.info(
            "Second class: %d of %d entities — PRESENT and NOT mergeable "
            "(a design choice: id coined from attio_record_id)",
            censimento["quante"],
            censimento["su"],
        )
        for riga in censimento["esempi"]:
            log.info("  · %s", riga)
        if censimento["quante"] > len(censimento["esempi"]):
            log.info("  ... and %d more", censimento["quante"] - len(censimento["esempi"]))
        log.info(
            "  to clear them: uv run python tools/cross-source/entity_dedup_index.py "
            "--promuovi   (dry-run; criterion: LinkedIn slug AND name)"
        )
    else:
        log.info("Second class: no entities in the store")


    censo_nomi = censisci_nomi_non_confrontabili(entities)
    if censo_nomi["quante"]:
        log.info(
            "Name not comparable: %d of %d entities — %s",
            censo_nomi["quante"],
            censo_nomi["su"],
            "BLOCKING guard" if blocca_attivo() else "census only",
        )
        for codice, quanti in sorted(censo_nomi["per_codice"].items(), key=lambda x: -x[1]):
            log.info("    %5d  %s", quanti, codice)
        for riga in censo_nomi["esempi"]:
            log.info("  · %s", riga)
    else:
        log.info("Name not comparable: no entities")


    log.info("Building blocking index...")
    blocks = build_blocks(entities)


    name_variants = _load_name_variants()


    now = datetime.now(UTC)
    log.info("Generating candidate pairs...")
    auto_candidates, review_candidates = generate_candidates(entities, blocks, name_variants, now)

    results = []
    total_merged = 0
    total_facts_gained = 0





    with Journal("l4-04-fuzzy-auto", attivo=not dry_run) as _journal:
        if args.auto or dry_run:
            for c in auto_candidates:
                result = merge_pair(c, dry_run=dry_run, method="l4-04-fuzzy-auto", journal=_journal)
                if result:
                    results.append(result)
                    total_merged += 1
                    total_facts_gained += result["facts_gained"]
                    log.info(
                        '%s: "%s" + "%s" [JW=%.3f, conf=%.3f, %d signals] → %s (+%d facts)',
                        "DRY" if dry_run else "MERGED",
                        result["name_a"],
                        result["name_b"],
                        result["jw_score"],
                        result["confidence"],
                        len(result["signals"]),
                        result["canonical_id"],
                        result["facts_gained"],
                    )

        if _journal.percorso:
            log.info("merge journal: %s", _journal.percorso)
            log.info(
                "to roll back: xs-l4-disfa-fusione.py --journal %s --apply",
                _journal.percorso.name,
            )


    if results and not dry_run:
        write_run_log(results)


    if args.review or dry_run:
        if review_candidates:
            if args.review and not dry_run:
                queue_path = write_review_queue(review_candidates)
                log.info("Review queue written: %s", queue_path)
            else:
                log.info("Review candidates (dry-run, not written):")
                for c in review_candidates[:10]:
                    log.info(
                        '  "%s" + "%s" [JW=%.3f, conf=%.3f, %d signals]',
                        c["entity_a_name"],
                        c["entity_b_name"],
                        c["jw_score"],
                        c["confidence"],
                        len(c["signals"]),
                    )
                if len(review_candidates) > 10:
                    log.info("  ... and %d more", len(review_candidates) - 10)

    log.info("")
    log.info("=" * 60)
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Auto-merge candidates: %d", len(auto_candidates))
    log.info("  Review candidates: %d", len(review_candidates))
    log.info("  Merges executed: %d", total_merged)
    log.info("  Facts gained: %d", total_facts_gained)
    if dry_run and not (args.auto or args.review):
        log.info("  Run with --auto or --review to execute.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
