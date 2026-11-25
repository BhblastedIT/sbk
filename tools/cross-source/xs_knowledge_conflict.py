""




















from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from conteggio import Conteggio, FileIlleggibile

from sbk_config import safe_write_json

log = logging.getLogger("sbk.knowledge-conflict")







WEIGHT_MATRIX: dict[str, dict[str, float]] = {
    "personio": {
        "employment": 1.0,
        "deal_status": 0.3,
        "communication": 0.2,
        "relationship": 0.3,
        "revenue_finance": 0.3,
        "default": 0.4,
    },
    "email": {
        "employment": 0.5,
        "deal_status": 0.6,
        "communication": 0.9,
        "relationship": 0.7,
        "revenue_finance": 0.5,
        "default": 0.6,
    },
    "calendar": {
        "employment": 0.3,
        "deal_status": 0.4,
        "communication": 0.8,
        "relationship": 0.6,
        "revenue_finance": 0.3,
        "default": 0.5,
    },
    "slack": {
        "employment": 0.3,
        "deal_status": 0.4,
        "communication": 0.85,
        "relationship": 0.6,
        "revenue_finance": 0.3,
        "default": 0.5,
    },
    "attio": {
        "employment": 0.6,
        "deal_status": 0.9,
        "communication": 0.5,
        "relationship": 0.7,
        "revenue_finance": 0.8,
        "default": 0.6,
    },
    "docusign": {
        "employment": 0.4,
        "deal_status": 0.8,
        "communication": 0.3,
        "relationship": 0.5,
        "revenue_finance": 0.7,
        "default": 0.5,
    },
    "linkedin": {
        "employment": 0.7,
        "deal_status": 0.3,
        "communication": 0.3,
        "relationship": 0.5,
        "revenue_finance": 0.3,
        "default": 0.5,
    },
    "meeting_transcripts": {
        "employment": 0.5,
        "deal_status": 0.7,
        "communication": 0.6,
        "relationship": 0.8,
        "revenue_finance": 0.6,
        "default": 0.6,
    },
    "static_import": {
        "employment": 0.8,
        "deal_status": 0.7,
        "communication": 0.5,
        "relationship": 0.7,
        "revenue_finance": 0.7,
        "default": 0.6,
    },
    "relationship_facts": {
        "employment": 0.5,
        "deal_status": 0.5,
        "communication": 0.5,
        "relationship": 0.8,
        "revenue_finance": 0.4,
        "default": 0.5,
    },
    "deep_facts": {
        "employment": 0.5,
        "deal_status": 0.6,
        "communication": 0.5,
        "relationship": 0.7,
        "revenue_finance": 0.5,
        "default": 0.6,
    },
    "manual_override": {
        "employment": 1.0,
        "deal_status": 1.0,
        "communication": 1.0,
        "relationship": 1.0,
        "revenue_finance": 1.0,
        "default": 1.0,
    },
}


_SOURCE_ALIASES: dict[str, str] = {
    "gmail": "email",
    "plaud": "meeting_transcripts",
    "tactiq": "meeting_transcripts",
    "attio_meetings": "meeting_transcripts",
    "google_calendar": "calendar",
}


def _normalize_source(source_type: str) -> str:
    ""
    s = source_type.lower().strip()
    return _SOURCE_ALIASES.get(s, s)


def _classify_attribute(attribute: str) -> str:
    ""
    prefix = attribute.split(".")[0] if "." in attribute else attribute
    mapping = {
        "employment": "employment",
        "crm": "deal_status",
        "legal": "deal_status",
        "communication": "communication",
        "meeting": "communication",
        "relationship": "relationship",
        "deep": "relationship",
        "contact": "relationship",
        "identity": "relationship",
        "financial": "revenue_finance",
        "revenue": "revenue_finance",
        "valuation": "revenue_finance",
    }
    return mapping.get(prefix, "default")


def get_source_weight(source_type: str, attribute: str) -> float:
    ""
    src = _normalize_source(source_type)
    fact_type = _classify_attribute(attribute)
    src_weights = WEIGHT_MATRIX.get(src)
    if src_weights is None:
        return 0.3
    return src_weights.get(fact_type, src_weights.get("default", 0.3))





def recency_bonus(extracted_at: str | None) -> float:
    ""






    if not extracted_at or not str(extracted_at).strip():
        return 0.5
    try:

        ts_str = str(extracted_at).strip()
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        days = max(0.0, (now - dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0.5

    if days < 7:
        return 1.0
    if days <= 90:

        return 1.0 - 0.5 * ((days - 7) / 83)
    return 0.5


def _normalize_value(val) -> str:
    ""
    if val is None:
        return ""
    return str(val).strip().lower()


def compute_fact_confidence(
    fact_dict: dict,
    all_entity_facts: list[dict],
) -> float:
    ""











    source = fact_dict.get("source", {})
    source_type = source.get("source_type", "")
    extracted_at = source.get("extracted_at", "")
    attribute = fact_dict.get("attribute", "")
    value = fact_dict.get("value")


    base_weight = get_source_weight(source_type, attribute)


    recency = recency_bonus(extracted_at)


    val_norm = _normalize_value(value)
    attr_norm = attribute

    support_count = 0
    contradict_count = 0
    supporting_sources: set[str] = set()

    for other in all_entity_facts:
        if other is fact_dict:
            continue
        if other.get("attribute") != attr_norm:
            continue

        if other.get("expired_at") or other.get("valid_to"):
            continue
        other_source_type = other.get("source", {}).get("source_type", "")
        other_val = _normalize_value(other.get("value"))
        other_weight = get_source_weight(other_source_type, attribute)

        if other_val == val_norm:
            support_count += 1
            supporting_sources.add(other_source_type)
        else:
            contradict_count += 1


    if support_count == 0 and contradict_count == 0:

        confidence = base_weight * recency
    else:
        support_score = base_weight * recency * (1 + support_count * 0.15)
        contradict_score = contradict_count * 0.2
        if support_score + contradict_score > 0:
            confidence = support_score / (support_score + contradict_score)
        else:
            confidence = base_weight * recency


    if len(supporting_sources) >= 2:
        confidence = min(1.0, confidence + 0.1)

    return round(min(1.0, max(0.0, confidence)), 4)













def _build_conflict(
    entity_id: str,
    attribute: str,
    existing_fact: dict,
    new_fact: dict | None,
    conflict_type: str,
    recommended_action: str,
) -> dict:
    ""
    return {
        "conflict_id": f"conflict:{uuid.uuid4().hex[:12]}",
        "entity_id": entity_id,
        "attribute": attribute,
        "existing_fact": existing_fact,
        "new_fact": new_fact,
        "conflict_type": conflict_type,
        "recommended_action": recommended_action,
        "detected_at": datetime.now(UTC).isoformat(),
    }


def detect_conflicts(
    existing_facts: list[dict],
    new_facts: list[dict],
) -> list[dict]:
    ""


































    conflicts: list[dict] = []


    existing_by_key: dict[tuple[str, str], list[dict]] = {}
    for ef in existing_facts:
        if ef.get("expired_at") or ef.get("valid_to"):
            continue
        key = (ef.get("entity_id", ""), ef.get("attribute", ""))
        existing_by_key.setdefault(key, []).append(ef)


    for nf in new_facts:
        if nf.get("expired_at") or nf.get("valid_to"):
            continue
        key = (nf.get("entity_id", ""), nf.get("attribute", ""))
        existing_group = existing_by_key.get(key, [])
        new_val = _normalize_value(nf.get("value"))

        for ef in existing_group:
            existing_val = _normalize_value(ef.get("value"))
            if existing_val != new_val and existing_val and new_val:
                conflicts.append(
                    _build_conflict(
                        entity_id=key[0],
                        attribute=key[1],
                        existing_fact=ef,
                        new_fact=nf,
                        conflict_type="contradiction",
                        recommended_action="pending_review",
                    )
                )

    return conflicts


def attributi_da_classificare(conflitti) -> list[tuple[str, int]]:
    ""





























    import collections

    conta: collections.Counter = collections.Counter()
    for c in conflitti:
        nf = c.get("new_fact") or {}
        ef = c.get("existing_fact") or {}
        a = (nf.get("attribute") or ef.get("attribute") or c.get("attribute") or "").strip()
        if a and da_classificare(a):
            conta[a] += 1
    return conta.most_common()


def coda_di_classificazione(conflitti) -> list[dict]:
    ""





    import collections

    conta: collections.Counter = collections.Counter()
    for c in conflitti:
        nf = c.get("new_fact") or {}
        ef = c.get("existing_fact") or {}
        a = (nf.get("attribute") or ef.get("attribute") or c.get("attribute") or "").strip()
        if a and da_classificare(a):
            conta[a] += 1
    fuori = []
    for a, n in conta.most_common():
        card = cardinalita(a)
        temp = classe_temporale(a)
        manca = []
        if card == "non_dichiarata":
            manca.append("cardinalita")
        if temp == NON_CLASSIFICATO:
            manca.append("temporalita")
        fuori.append(
            {
                "attributo": a,
                "voci": n,
                "cardinalita": card,
                "classe_temporale": temp,
                "manca": manca,
            }
        )
    return fuori


def resolve_conflict(conflict: dict) -> dict:
    ""






    conflict_type = conflict.get("conflict_type", "")







    if conflict_type == "stale":
        conflict["recommended_action"] = "pending_review"
        conflict["perche"] = "historical entry: the branch that produced it no longer exists"
        return conflict

    _nf = conflict.get("new_fact") or {}
    _ef = conflict.get("existing_fact") or {}
    _attr = _nf.get("attribute") or _ef.get("attribute") or ""

























    if _attr and classe_temporale(_attr) == AGGREGATO:
        conflict["recommended_action"] = "pending_review"
        conflict["classe_temporale"] = AGGREGATO
        conflict["perche"] = (
            f"«{_attr}» is an aggregate: it is recomputed at the source, does not coexist and does not expire "
            f"(automatic replacement halted until there is a per-entry journal)"
        )
        return conflict




    if _attr and e_multi_valore(_attr) and not e_funzionale(_attr):
        conflict["recommended_action"] = "coesistono"
        conflict["perche"] = f"«{_attr}» allows multiple values: it is not a contradiction"
        return conflict
    if _attr and not e_funzionale(_attr):



        conflict["recommended_action"] = "pending_review"
        conflict["perche"] = f"cardinality of «{_attr}» not declared"
        return conflict

    new_fact = conflict.get("new_fact", {})
    existing_fact = conflict.get("existing_fact", {})

    new_conf = (new_fact.get("confidence") or 0.5) if new_fact else 0.0
    old_conf = (existing_fact.get("confidence") or 0.5) if existing_fact else 0.0

















    conflict["margine"] = round(abs(new_conf - old_conf), 4)
    if new_conf >= old_conf + MARGINE_NETTO:









        if _attr and not ammette_chiusura(_attr):
            conflict["recommended_action"] = "pending_review"
            conflict["classe_temporale"] = classe_temporale(_attr)
            conflict["perche"] = (
                f"the new one is more reliable by {conflict['margine']}, but «{_attr}» is "
                f"{classe_temporale(_attr)}: it is not closed"
            )
            return conflict
        conflict["recommended_action"] = "expire_old"
        conflict["perche"] = f"the new one is more reliable by {conflict['margine']}"
    elif old_conf >= new_conf + MARGINE_NETTO:
        conflict["recommended_action"] = "keep_old"
        conflict["perche"] = f"the old one is more reliable by {conflict['margine']}"
    else:
        conflict["recommended_action"] = "pending_review"
        conflict["perche"] = f"the two are equivalent (margin {conflict['margine']})"

    return conflict


def apply_resolution(profile_dict: dict, conflict: dict) -> dict:
    ""






    action = conflict.get("recommended_action", "pending_review")
    facts = profile_dict.get("facts", [])

    if action == "expire_old":
        existing = conflict.get("existing_fact", {})
        existing_id = existing.get("fact_id")
        now = datetime.now(UTC).isoformat()

        for f in facts:
            if f.get("fact_id") == existing_id:
                f["expired_at"] = now
                break

        new_fact = conflict.get("new_fact")
        if new_fact:
            facts.append(new_fact)


    profile_dict["facts"] = facts
    return profile_dict


def auto_resolve_pending() -> dict[str, int]:
    ""






    pending = load_pending_review()
    if not pending:
        return {"resolved": 0, "still_pending": 0, "total": 0}

    still_pending = []
    resolved = []

    for conflict in pending:
        conflict = resolve_conflict(conflict)
        if conflict.get("recommended_action") in ("expire_old", "keep_old"):
            conflict["resolved_at"] = datetime.now(UTC).isoformat()
            conflict["resolved_by"] = "auto"
            resolved.append(conflict)
        else:
            still_pending.append(conflict)


    save_pending_review(still_pending)
    if resolved:
        _append_resolved(resolved)

    return {
        "resolved": len(resolved),
        "still_pending": len(still_pending),
        "total": len(pending),
    }


def _append_resolved(items: list[dict]) -> None:
    ""
    path = _resolved_path()
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.extend(items)
    safe_write_json(path, existing)





MIN_REVIEW_CONFIDENCE = 0.75










MARGINE_NETTO = 0.15




















from knowledge_taxonomy import (  # noqa: E402
    AGGREGATO,
    FUNZIONALI,  # noqa: F401  — re-export: chi la importava da qui continua
    MULTI_VALORE,  # noqa: F401  — idem
    NON_CLASSIFICATO,
    ammette_chiusura,
    cardinalita,
    classe_temporale,
    da_classificare,
    e_funzionale,
    e_multi_valore,
)

MAX_QUEUE_DEPTH = 500
QUEUE_AGE_OUT_DAYS = 30


def _conflicts_dir() -> Path:
    import sbk_config as cfg

    return cfg.KNOWLEDGE_CONFLICTS_DIR


def _pending_path() -> Path:
    return _conflicts_dir() / "pending-review.json"


def _resolved_path() -> Path:
    return _conflicts_dir() / "resolved.json"


def load_pending_review(tollera_illeggibili: bool = False) -> list[dict]:
    ""












    path = _pending_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        if not tollera_illeggibili:
            raise FileIlleggibile(
                f"{path} cannot be read ({exc}): the queue is NOT empty, it is unreadable. "
                f"Whoever wants a number anyway asks for it: load_pending_review"
                f"(tollera_illeggibili=True)."
            ) from exc
        log.warning("unreadable queue, skipped at caller's request: %s", exc)
        return []


def conta_coda(tollera_illeggibili: bool = False) -> Conteggio:
    ""


















    d = _conflicts_dir()
    valore = su = 0
    saltati = {"unreadable json": 0, "unreadable line": 0}

    pending = load_pending_review(tollera_illeggibili=tollera_illeggibili)
    if _pending_path().exists() and not pending and tollera_illeggibili:


        try:
            json.loads(_pending_path().read_text())
        except (json.JSONDecodeError, OSError):
            saltati["unreadable json"] += 1
    valore += len(pending)
    su += len(pending)

    for f in sorted(d.glob("overflow-*.jsonl")) if d.exists() else []:
        try:
            righe = f.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            if not tollera_illeggibili:
                raise FileIlleggibile(f"{f} cannot be read ({exc})") from exc
            saltati["unreadable json"] += 1
            continue
        for riga in righe:
            if not riga.strip():
                continue
            su += 1
            try:
                json.loads(riga)
            except json.JSONDecodeError as exc:


                if not tollera_illeggibili:
                    raise FileIlleggibile(
                        f"{f}: a line cannot be read ({exc}). The count would "
                        f"stop smaller than the true value without saying so. To count "
                        f"anyway: conta_coda(tollera_illeggibili=True)."
                    ) from exc
                saltati["unreadable line"] += 1
                continue
            valore += 1

    return Conteggio(valore=valore, su=su, saltati=saltati)


def save_pending_review(items: list[dict]) -> None:
    ""
    path = _pending_path()
    safe_write_json(path, items)


def _extract_confidence(item: dict) -> float | None:
    ""
    if "confidence" in item:
        return item["confidence"]
    new_fact = item.get("new_fact")
    if isinstance(new_fact, dict) and "confidence" in new_fact:
        return new_fact["confidence"]
    return None


def add_to_pending_review(conflict: dict) -> None:
    ""








    conf = _extract_confidence(conflict)
    if conf is not None and conf < MIN_REVIEW_CONFIDENCE:
        log.info("Confidence gate: skipped item (%.2f < %.2f)", conf, MIN_REVIEW_CONFIDENCE)
        return

    items = load_pending_review()

    eid = conflict.get("entity_id", "")
    attr = conflict.get("attribute", "")


    items = [it for it in items if not (it.get("entity_id") == eid and it.get("attribute") == attr)]
    items.append(conflict)
    save_pending_review(items)


def batch_add_to_pending_review(conflicts: list[dict]) -> Conteggio:
    ""



















    if not conflicts:

        return Conteggio(valore=0, su=0)


    n_age_out = age_out_pending_review()


    gated = []
    skipped_low_conf = 0
    for c in conflicts:
        conf = _extract_confidence(c)
        if conf is not None and conf < MIN_REVIEW_CONFIDENCE:
            skipped_low_conf += 1
            continue
        gated.append(c)

    if skipped_low_conf:
        log.info(
            "Confidence gate: skipped %d items below %.2f", skipped_low_conf, MIN_REVIEW_CONFIDENCE
        )

    if not gated:
        coda = load_pending_review()
        return Conteggio(
            valore=len(coda),
            su=len(conflicts) + len(coda) + n_age_out,
            saltati={
                "confidence gate": skipped_low_conf,
                "age-out": n_age_out,
                "over the limit": 0,
            },
        )

    items = load_pending_review()
    n_preesistenti = len(items)


    existing_idx: dict[tuple[str, str], int] = {}
    for i, it in enumerate(items):
        key = (it.get("entity_id", ""), it.get("attribute", ""))
        existing_idx[key] = i


    remove_indices: set[int] = set()
    for conflict in gated:
        key = (conflict.get("entity_id", ""), conflict.get("attribute", ""))
        if key in existing_idx:
            remove_indices.add(existing_idx[key])
        existing_idx[key] = -1


    kept = [it for i, it in enumerate(items) if i not in remove_indices]


    new_deduped: dict[tuple[str, str], dict] = {}
    for conflict in gated:
        key = (conflict.get("entity_id", ""), conflict.get("attribute", ""))
        new_deduped[key] = conflict

    kept.extend(new_deduped.values())


    n_overflow = 0
    if len(kept) > MAX_QUEUE_DEPTH:
        kept.sort(key=_priority_score, reverse=True)
        overflow = kept[MAX_QUEUE_DEPTH:]
        kept = kept[:MAX_QUEUE_DEPTH]
        n_overflow = len(overflow)
        _archive_overflow(overflow)
        log.warning(
            "Queue overflow: archived %d items (max depth %d)", len(overflow), MAX_QUEUE_DEPTH
        )

    save_pending_review(kept)
    return Conteggio(
        valore=len(kept),
        su=len(conflicts) + n_preesistenti + n_age_out,
        saltati={
            "confidence gate": skipped_low_conf,
            "age-out": n_age_out,
            "over the limit": n_overflow,
        },
    )


def resolve_pending_item(conflict_id: str, action: str, manual_value: str | None = None) -> bool:
    ""




    items = load_pending_review()
    found = None
    remaining = []

    for it in items:
        if it.get("conflict_id") == conflict_id:
            found = it
        else:
            remaining.append(it)

    if not found:
        return False

    found["resolved_at"] = datetime.now(UTC).isoformat()
    found["resolution_action"] = action
    if manual_value is not None:
        found["manual_value"] = manual_value

    save_pending_review(remaining)
    _append_to_resolved(found)
    return True


def _append_to_resolved(item: dict) -> None:
    ""
    path = _resolved_path()
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.append(item)
    safe_write_json(path, existing)





def _priority_score(item: dict) -> float:
    ""
    conf = _extract_confidence(item) or 0.5


    cluster_impact = 1.0 if item.get("in_cluster") else 0.5


    created = item.get("created_at", item.get("detected_at", ""))
    recency = 0.5
    if created:
        try:
            ts = str(created).strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - dt).total_seconds() / 86400
            recency = max(0.0, 1.0 - age_days / 60)
        except (ValueError, TypeError):
            pass

    return 0.60 * conf + 0.25 * cluster_impact + 0.15 * recency


def _archive_overflow(items: list[dict]) -> None:
    ""
    if not items:
        return
    conflicts_dir = _conflicts_dir()
    conflicts_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    archive_path = conflicts_dir / f"overflow-{now.strftime('%Y-%m')}.jsonl"
    with open(archive_path, "a") as f:
        for item in items:
            item["archived_at"] = now.isoformat()
            f.write(json.dumps(item, default=str) + "\n")
    log.info("Archived %d items to %s", len(items), archive_path.name)


def age_out_pending_review() -> int:
    ""



    items = load_pending_review()
    if not items:
        return 0

    cutoff = (datetime.now(UTC) - timedelta(days=QUEUE_AGE_OUT_DAYS)).isoformat()

    kept = []
    aged_out = []
    for it in items:
        created = it.get("created_at", it.get("detected_at", ""))
        if created and created < cutoff:
            aged_out.append(it)
        else:
            kept.append(it)

    if aged_out:
        _archive_overflow(aged_out)
        save_pending_review(kept)
        log.info("Age-out: archived %d items older than %d days", len(aged_out), QUEUE_AGE_OUT_DAYS)

    return len(aged_out)


def ritira_stale_dalla_coda(motivo: str) -> Conteggio:
    ""





































    if not motivo or not motivo.strip():
        raise ValueError("retired_reason is required")

    items = load_pending_review()
    ritirate = [it for it in items if it.get("conflict_type") == "stale"]
    kept = [it for it in items if it.get("conflict_type") != "stale"]

    if ritirate:
        for it in ritirate:
            it["retired_reason"] = motivo
        _archive_overflow(ritirate)
        save_pending_review(kept)
        log.info("Retired %d stale entries from the live queue → overflow (%s)", len(ritirate), motivo)

    return Conteggio(valore=len(ritirate), su=len(items))


def cleanup_existing_queue() -> dict:
    ""



    items = load_pending_review()
    original_count = len(items)


    cutoff = (datetime.now(UTC) - timedelta(days=QUEUE_AGE_OUT_DAYS)).isoformat()
    aged_out = []
    after_age = []
    for it in items:
        created = it.get("created_at", it.get("detected_at", ""))
        if created and created < cutoff:
            aged_out.append(it)
        else:
            after_age.append(it)


    low_conf = []
    after_conf = []
    for it in after_age:
        conf = _extract_confidence(it)
        if conf is not None and conf < MIN_REVIEW_CONFIDENCE:
            low_conf.append(it)
        else:
            after_conf.append(it)


    overflow = []
    if len(after_conf) > MAX_QUEUE_DEPTH:
        after_conf.sort(key=_priority_score, reverse=True)
        overflow = after_conf[MAX_QUEUE_DEPTH:]
        after_conf = after_conf[:MAX_QUEUE_DEPTH]


    _archive_overflow(aged_out + low_conf + overflow)
    save_pending_review(after_conf)

    return {
        "original": original_count,
        "aged_out": len(aged_out),
        "low_confidence": len(low_conf),
        "overflow": len(overflow),
        "remaining": len(after_conf),
    }





def create_manual_override(
    entity_id: str,
    entity_type: str,
    attribute: str,
    value,
) -> dict:
    ""





    now = datetime.now(UTC).isoformat()
    return {
        "fact_id": f"f:override:{uuid.uuid4().hex[:12]}",
        "entity_id": entity_id,
        "entity_type": entity_type,
        "attribute": attribute,
        "value": value,
        "confidence": 1.0,
        "valid_from": now,
        "valid_to": None,
        "created_at": now,
        "expired_at": None,
        "source": {
            "source_type": "manual_override",
            "source_file": "manual",
            "record_id": "",
            "extracted_at": now,
        },
        "superseded_by": None,
    }


def apply_manual_override_to_entity(
    entity_id: str,
    entity_type: str,
    attribute: str,
    value,
) -> bool:
    ""








    import sbk_config as cfg

    profile_path = cfg.KNOWLEDGE_ENTITIES_DIR / entity_type / f"{entity_id}.json"
    if not profile_path.exists():
        log.warning("Entity file not found: %s", profile_path)
        return False

    try:
        profile = json.loads(profile_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to load entity %s: %s", entity_id, exc)
        return False

    now = datetime.now(UTC).isoformat()
    facts = profile.get("facts", [])


    for f in facts:
        if f.get("attribute") == attribute and not f.get("expired_at"):
            f["expired_at"] = now


    override = create_manual_override(entity_id, entity_type, attribute, value)
    facts.append(override)
    profile["facts"] = facts
    profile["updated_at"] = now
    profile["version"] = profile.get("version", 1) + 1


    safe_write_json(profile_path, profile)
    return True
