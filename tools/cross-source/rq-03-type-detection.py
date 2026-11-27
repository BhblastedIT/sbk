#!/usr/bin/env python3
"""RQ-03: detects the type of each relationship (colleague, direct report, ex-employee, investor, vendor, business
partner, professional friend, family, acquaintance...) from rules over contacts, emails, the HR directory, the CRM
and interactions.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd
from pipeline_decorator import PermanentAPIError

from sbk_config import (
    ATTIO_DIR,
    DATA_ROOT,
    DOCUSIGN_DIR,
    ENRICHED_DIR,
    KNOWLEDGE_RELATIONSHIPS_DIR,
    OWN_EMAILS,
    OWN_NAMES_NORMALIZED,
    PERSONIO_DIR,
    RQ_DIR,
    safe_write_parquet,
)

log = logging.getLogger("rq-03")



_EMAIL_OWNER = {e.strip().lower() for e in OWN_EMAILS}




LLM_ERROR_ABORT_RATIO = 0.05


def _llm_error_guard(
    method_counts: dict[str, int],
    total: int,
    threshold: float = LLM_ERROR_ABORT_RATIO,
) -> float:
    ""



    if total <= 0:
        return 0.0
    errors = method_counts.get("llm_error", 0)
    ratio = errors / total
    if ratio > threshold:
        raise PermanentAPIError(
            f"rq-03 aborted: {errors}/{total} classifications ({ratio:.1%}) are LLM errors, "
            f"over the {threshold:.0%} threshold. No output written: "
            "the existing parquet stays the good one."
        )
    return ratio


def _load_composite_scores() -> pd.DataFrame:
    ""
    scores_file = RQ_DIR / "composite-scores.parquet"
    if not scores_file.exists():
        log.warning("RQ-02 scores not found: %s. Run rq-02-scoring.py first.", scores_file)
        return pd.DataFrame()
    return pd.read_parquet(scores_file)


def _load_contacts_merged() -> pd.DataFrame:
    ""
    merged_file = ENRICHED_DIR / "contacts-merged.parquet"
    if not merged_file.exists():
        return pd.DataFrame()
    return pd.read_parquet(merged_file)


def _load_email_messages() -> pd.DataFrame:
    ""
    email_file = DATA_ROOT / "emails" / "filtered-messages.parquet"
    if not email_file.exists():
        return pd.DataFrame()
    cols = ["from_addr", "to_addr", "date", "subject", "snippet"]


    import pyarrow.parquet as pq

    available_cols = pq.ParquetFile(email_file).schema.names
    use_cols = [c for c in cols if c in available_cols]
    if not use_cols:
        return pd.DataFrame()
    return pd.read_parquet(email_file, columns=use_cols)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _build_email_index(
    email_df: pd.DataFrame,
    max_samples: int = 10,
) -> dict[str, list[dict]]:
    ""






    if email_df.empty:
        return {}

    df = email_df
    if "date" in df.columns:
        df = df.sort_values("date", ascending=False)

    n = len(df)

    def _col(name: str):
        return df[name].astype(str).tolist() if name in df.columns else [""] * n

    from_arr = _col("from_addr")
    to_arr = _col("to_addr")
    date_arr = _col("date")
    subj_arr = _col("subject")

    index: dict[str, list[dict]] = {}
    for fa, ta, dt, subj in zip(from_arr, to_arr, date_arr, subj_arr):
        addrs = set()
        for field in (fa, ta):
            if field:
                addrs.update(m.group(0).lower() for m in _EMAIL_RE.finditer(field))
        if not addrs:
            continue
        sample = {"date": dt[:10], "channel": "email", "summary": subj[:200]}
        for addr in addrs:
            lst = index.setdefault(addr, [])
            if len(lst) < max_samples:
                lst.append(sample)

    return index


def _build_interaction_samples(person_email: str, email_index: dict[str, list[dict]]) -> list[dict]:
    ""
    if not person_email:
        return []
    return email_index.get(person_email.lower(), [])


def _intero(valore) -> int | None:
    ""
    try:
        numero = float(valore)
    except (TypeError, ValueError):
        return None
    return None if numero != numero else int(numero)


def _interazioni_per_persona(rows, metas: dict[str, dict]) -> dict[str, int]:
    ""
    interazioni: dict[str, int] = {}
    for row in rows:
        chi = metas[str(row["person"])]["person_id"] or str(row["person"])
        interazioni[chi] = interazioni.get(chi, 0) + (_intero(row.get("interaction_count")) or 0)
    return interazioni


def _find_owner_in_personio(personio_index: dict[str, dict]) -> tuple[str | None, str | None]:
    ""


















    for email, emp in personio_index.items():
        if str(email).strip().lower() in _EMAIL_OWNER:
            return emp.get("team"), emp.get("supervisor")



    for emp in personio_index.values():
        full = f"{emp.get('first_name', '')} {emp.get('last_name', '')}"
        if " ".join(full.lower().split()) in OWN_NAMES_NORMALIZED:
            return emp.get("team"), emp.get("supervisor")



    if personio_index:
        log.warning(
            "You are not found in Personio (%d records, matched on own_emails and own_names): team and supervisor stay None, "
            "the colleague_team/manager rules won't fire",
            len(personio_index),
        )
    return None, None


def _build_contacts_index(
    contacts_df: pd.DataFrame,
) -> tuple[dict[str, dict], dict[str, dict]]:
    ""





    by_email: dict[str, dict] = {}
    by_pid: dict[str, dict] = {}
    if contacts_df.empty:
        return by_email, by_pid

    has_email = "email" in contacts_df.columns
    has_pid = "person_id" in contacts_df.columns
    records = contacts_df.to_dict("records")
    for rec in records:
        if has_email:
            email = rec.get("email")
            if email is not None and str(email) != "nan":
                key = str(email).lower()
                by_email.setdefault(key, rec)
        if has_pid:
            pid = rec.get("person_id")
            if pid is not None and str(pid) != "nan":
                by_pid.setdefault(str(pid), rec)

    if "all_emails" in contacts_df.columns:
        for rec in records:
            for altra in _EMAIL_RE.findall(str(rec.get("all_emails") or "")):
                by_email.setdefault(altra.lower(), rec)

    return by_email, by_pid


def _load_entity_bridge() -> dict[str, str]:
    ""
    ponte = RQ_DIR / "entity-bridge.json"
    if not ponte.exists():
        return {}
    try:
        dati = json.loads(ponte.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("entity-bridge.json not read (%s): no resolution by name", exc)
        return {}
    return {str(k).lower().strip(): str(v) for k, v in dati.items() if v}


def _get_contact_metadata(
    person: str,
    by_email: dict[str, dict],
    by_pid: dict[str, dict],
    bridge: dict[str, str] | None = None,
) -> dict:
    ""





    result = {
        "name": person,
        "email": person,
        "role": None,
        "company": None,
        "channels": [],
        "person_id": None,
    }

    row = by_email.get(person.lower())
    if row is None:
        row = by_pid.get(person)
    if row is None:
        trovata = _EMAIL_RE.search(person)
        email = trovata.group(0).lower() if trovata else None
        if email:
            row = by_email.get(email)
            if row is None:
                result["email"] = email
        if row is None and bridge:
            pid = bridge.get(person.lower().strip()) or (bridge.get(email) if email else None)
            row = by_pid.get(pid) if pid else None
    if row is None:
        return result

    result["name"] = str(row.get("name", person))
    pid = row.get("person_id")
    result["person_id"] = str(pid) if pid is not None and str(pid) != "nan" else None
    result["email"] = str(row.get("email", person))

    role = row.get("attio_job_title") or row.get("personio_position")
    if role and str(role) != "nan":
        result["role"] = str(role)

    company = row.get("attio_company")
    if company and str(company) != "nan":
        result["company"] = str(company)

    for col, name in [
        ("has_email", "email"),
        ("has_attio", "attio"),
        ("has_personio", "personio"),
        ("has_slack", "slack"),
    ]:
        if row.get(col):
            result["channels"].append(name)

    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RQ-03: Relationship type detection")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--person", type=str, help="Classify single person")

    parser.add_argument("--rules-only", action="store_true", help="Always true")
    return parser.parse_args(argv)


def main():
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from rq_type_detection import (
        classify_relationship,
        extract_docusign_types,
        extract_personio_enrichment,
        load_attio_investor_domains,
        load_attio_investors,
        load_golden_overrides,
        load_personio_index,
    )


    scores_df = _load_composite_scores()
    if scores_df.empty:
        log.warning("No composite scores available. Run rq-02-scoring.py first.")
        return

    contacts_df = _load_contacts_merged()
    email_df = _load_email_messages()
    personio_index = load_personio_index(PERSONIO_DIR)
    personio_enrichment = extract_personio_enrichment(PERSONIO_DIR)
    attio_investors = load_attio_investors(ATTIO_DIR)


    investor_domains = load_attio_investor_domains(ATTIO_DIR)
    docusign_types = extract_docusign_types(DOCUSIGN_DIR)
    golden_overrides = load_golden_overrides()
    bridge = _load_entity_bridge()
    owner_team, owner_supervisor = _find_owner_in_personio(personio_index)

    log.info(
        "Data loaded: %d scores, %d contacts, %d emails, %d personio, %d investors, "
        "%d investor domains, %d docusign, %d golden, %d bridge",
        len(scores_df),
        len(contacts_df),
        len(email_df),
        len(personio_index),
        len(attio_investors),
        len(investor_domains),
        len(docusign_types),
        len(golden_overrides),
        len(bridge),
    )


    contacts_by_email, contacts_by_pid = _build_contacts_index(contacts_df)
    email_index = _build_email_index(email_df)

    rows = [
        row
        for _, row in scores_df.iterrows()
        if not (args.person and args.person != str(row["person"]))
    ]




    metas = {
        str(row["person"]): _get_contact_metadata(
            str(row["person"]), contacts_by_email, contacts_by_pid, bridge
        )
        for row in rows
    }
    interazioni = _interazioni_per_persona(rows, metas)
    con_conteggio = "interaction_count" in scores_df.columns

    def _classify_row(row) -> dict:
        person = str(row["person"])
        score = float(row.get("score", 1.0))
        meta = metas[person]
        samples = _build_interaction_samples(meta["email"], email_index)
        result = classify_relationship(
            person_email=meta["email"],
            person_name=meta["name"],
            composite_score=score,
            personio_index=personio_index,




            personio_enrichment=personio_enrichment,
            attio_investors=attio_investors,
            interaction_samples=samples,
            person_role=meta["role"],
            person_company=meta["company"],
            total_interactions=float(row.get("weighted_sum", 0.0)),
            channels=meta["channels"],
            reciprocity=float(row.get("dim_reciprocity", 0.0)),
            owner_team=owner_team,
            owner_supervisor=owner_supervisor,
            rules_only=True,
            docusign_types=docusign_types,
            investor_domains=investor_domains,
            golden_overrides=golden_overrides,
            interaction_count=interazioni[meta["person_id"] or person] if con_conteggio else None,
        )
        result["person"] = person
        result["person_name"] = meta["name"]
        result["score"] = score
        return result


    results = [_classify_row(row) for row in rows]

    method_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {"certain": 0, "probable": 0, "unverified": 0}
    for result in results:
        method = result.get("method", "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1


        rtype = result.get("type") or "unclassified"
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
        confidence_counts[result["confidence"]] = confidence_counts.get(result["confidence"], 0) + 1

    if not results:
        log.warning("No results")
        return


    log.info("=" * 60)
    log.info("TOTAL: %d contacts classified", len(results))
    log.info("")
    log.info("Method distribution:")
    for method, count in sorted(method_counts.items()):
        log.info("  %-20s %5d", method, count)
    log.info("")
    log.info("Type distribution:")
    for rtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        log.info("  %-25s %5d", rtype, count)
    log.info("")
    log.info("Confidence distribution:")
    for conf, count in sorted(confidence_counts.items()):
        log.info("  %-15s %5d", conf, count)




    error_ratio = _llm_error_guard(method_counts, len(results))

    if args.dry_run:
        log.info("DRY RUN — no output written")
        return

    if method_counts.get("llm_error"):
        log.warning(
            "%d of %d classifications (%.1f%%) are LLM errors: rows discarded, not written",
            method_counts["llm_error"],
            len(results),
            error_ratio * 100,
        )


    RQ_DIR.mkdir(parents=True, exist_ok=True)
    writable = [r for r in results if r.get("method") != "llm_error" and r.get("type")]
    flat = []
    for r in writable:
        flat.append(
            {
                "person": r["person"],
                "type": r["type"],
                "confidence": r["confidence"],
                "evidence": r["evidence"],
                "method": r["method"],
                "model_used": r.get("model_used"),
                "score": r["score"],
            }
        )

    if not flat:
        log.error(
            "No valid classification out of %d results: output NOT rewritten "
            "(the existing parquet stays the good one)",
            len(results),
        )
        return

    df_out = pd.DataFrame(flat)
    safe_write_parquet(df_out, RQ_DIR / "relationship-types.parquet")
    log.info("Written: %s (%d rows)", RQ_DIR / "relationship-types.parquet", len(df_out))


    KNOWLEDGE_RELATIONSHIPS_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    for r in writable:
        person_id = r["person"].strip()

        if "," in person_id or len(person_id) > 200:
            continue
        if "<" in person_id and ">" in person_id:
            person_id = person_id[person_id.index("<") + 1 : person_id.index(">")].strip()
        if not person_id or "@" not in person_id or any(c in person_id for c in '/"<>\\'):
            continue
        person_id = person_id.lower()
        detail_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{person_id}.json"
        detail = {}
        if detail_file.exists():
            try:
                detail = json.loads(detail_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        detail["relationship_type"] = r["type"]
        detail["type_confidence"] = r["confidence"]
        detail["type_evidence"] = r["evidence"]
        detail["type_method"] = r["method"]
        detail["type_model"] = r.get("model_used")
        detail["type_last_classified"] = datetime.now(UTC).isoformat()

        detail_file.write_text(json.dumps(detail, indent=2), encoding="utf-8")
        updated += 1

    log.info("Updated %d relationship detail JSONs", updated)


from pipeline_decorator import pipeline_step

main = pipeline_step(name="rq-03-type-detection", source="cross-source", stage="rq")(main)

if __name__ == "__main__":
    main()
