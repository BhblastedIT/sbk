#!/usr/bin/env python3
"""Deep extraction with Claude: reads your long documents (meetings, calls, CRM notes, email, Slack, voice memos)
and extracts deep facts, commitments and decisions about people, with cost estimate (--dry-run), parallel or
Batch API runs and a cache. The documents are sent to the Anthropic API.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from xs_anthropic_client import PermanentAPIError
from xs_l3_chunking import Chunk, chunk_document_semantic
from xs_l3_common import SBKData, call_claude, compute_source_hash, setup_logging
from xs_l3_email_filter import filter_emails as email_prefilter
from xs_l3_routing import SmartRouter

from sbk_config import (
    DATA_ROOT,
    DEEP_FACTS_FILE,
    OWNER_LABEL,
    DEEP_RESPONSES_DIR,
    EMAILS_DIR,
    STT_NAME_CORRECTIONS,
    VOICE_MEMOS_TRANSCRIPTS_DIR,
    acquire_pid_lock,
    safe_write_parquet,
)

log = logging.getLogger("sbk-deep-extract")



_rel_script = _THIS_DIR / "xs-l3-extract-relationships.py"
spec = importlib.util.spec_from_file_location("xs_l3_extract_rel", _rel_script)
_rel_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_rel_mod)
LOADERS: dict[str, callable] = dict(_rel_mod.LOADERS)



SONNET_MODEL = "claude-sonnet-4-5-20250929"


_PROVIDER = "anthropic"

DEEP_SOURCES = [
    "plaud",
    "tactiq",
    "attio_call",
    "attio_notes",
    "email",
    "slack",
    "slack_dm",
    "whatsapp",
    "chatgpt",
    "notion",
    "gdrive",
    "voice_memo",
]

MIN_DOC_CHARS_DEFAULT = 5000
CHUNK_MAX_CHARS = 25_000
CHUNK_OVERLAP_CHARS = 2_000




def load_email_documents() -> list[dict]:
    ""
    docs = []
    if not EMAILS_DIR.exists():
        log.warning(f"Emails dir not found: {EMAILS_DIR}")
        return docs
    for account_dir in sorted(EMAILS_DIR.iterdir()):
        if not account_dir.is_dir():
            continue
        pq = account_dir / "messages.parquet"
        if not pq.exists():
            continue
        try:
            df = pd.read_parquet(pq)
            account_name = account_dir.name
            for _, row in df.iterrows():
                body = str(row.get("body_text", "") or "")
                subject = str(row.get("subject", "") or "")
                if len(body.strip()) < 50:
                    continue
                text = f"Subject: {subject}\n\n{body}"
                date_val = row.get("date", "")
                date_str = ""
                if hasattr(date_val, "strftime"):
                    date_str = date_val.strftime("%Y-%m-%d")
                elif date_val:
                    date_str = str(date_val)[:10]
                from_addr = str(row.get("from_addr", "") or "")
                to_addr = str(row.get("to_addr", "") or "")
                msg_id = str(row.get("id", "") or row.get("message_id", "") or "")
                docs.append(
                    {
                        "source": "email",
                        "source_id": f"email_{account_name}_{msg_id}",
                        "title": subject[:100] if subject else "Email",
                        "date": date_str,
                        "participants": f"{from_addr} -> {to_addr}",
                        "text": text,
                        "file": str(pq),
                    }
                )
        except Exception as e:
            log.warning(f"Failed to load emails from {account_dir.name}: {e}")
    return docs


def load_voice_memo_documents() -> list[dict]:
    ""
    docs = []
    if not VOICE_MEMOS_TRANSCRIPTS_DIR.exists():
        log.warning(f"Voice memos transcripts dir not found: {VOICE_MEMOS_TRANSCRIPTS_DIR}")
        return docs
    for f in sorted(VOICE_MEMOS_TRANSCRIPTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            segments = data.get("segments", [])
            raw_transcript = data.get("raw_transcript", "")
            if segments:
                text_parts = []
                for s in segments:
                    speaker = s.get("speaker") or "Speaker"
                    text_content = s.get("text", "")
                    if text_content:
                        text_parts.append(f"{speaker}: {text_content}")
                text = "\n".join(text_parts)
            elif raw_transcript:
                text = raw_transcript
            else:
                continue
            if len(text.strip()) < 50:
                continue

            date_str = ""
            fname = f.stem
            if len(fname) >= 10 and fname[4] == "-" and fname[7] == "-":
                date_str = fname[:10]
            title = data.get("filename", fname)
            docs.append(
                {
                    "source": "voice_memo",
                    "source_id": f.stem,
                    "title": title[:100] if title else f.stem,
                    "date": date_str,
                    "participants": OWNER_LABEL,
                    "text": text,
                    "file": str(f),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load voice memo {f.name}: {e}")
    return docs



if "email" not in LOADERS:
    LOADERS["email"] = load_email_documents
if "voice_memo" not in LOADERS:
    LOADERS["voice_memo"] = load_voice_memo_documents




DEEP_SYSTEM_PROMPT = """You are a deep intelligence analyst. Extract precise, actionable facts from this document.

CRITICAL: Return ONLY a raw JSON object. No markdown, no code blocks.

Extract these 6 categories:

1. financial: Financial information with exact numbers
   Each: {person_or_entity, fact_type, value, currency, context, confidence}
   Types: investment_amount, valuation, equity_stake, revenue, debt, collateral, fund_structure, fee_structure, salary, bonus
   ALWAYS extract exact numbers. "30 milioni" -> value: "30000000", currency: "EUR"
   "3 million dollars" -> value: "3000000", currency: "USD"

2. deal: Deal structures and terms
   Each: {parties: [str], term_type, description, value, conditions, context, confidence}
   Types: offer, counter_offer, condition, deadline, commitment, rejection, acceptance, equity_split, vesting

3. commitment: Firm and conditional commitments
   Each: {person, to_whom, commitment_type, description, amount, currency, deadline, conditions, context, confidence}
   Types: investment_commitment, payment_commitment, delivery_commitment, hire_commitment, resource_commitment
   IMPORTANT: "to_whom" is the person/entity the commitment was made TO.
   IMPORTANT: "deadline" MUST be ISO date format YYYY-MM-DD when extractable. Convert relative dates ("entro venerdi'", "next week") to absolute dates using the document date. If deadline cannot be determined, set to null.

4. negotiation: Negotiation positions and dynamics
   Each: {person, position_type, description, context, confidence}
   Types: red_line, flexibility, leverage, anchor_point, walkaway, concession

5. strategic: Business strategy and market intelligence
   Each: {entity, strategy_type, description, context, confidence}
   Types: market_entry, acquisition, partnership, pivot, hiring_plan, product_launch, competitive_move

6. operational: Tasks with clear ownership
   Each: {owner, task, deadline, resources, status, context, confidence}
   Status: committed, discussed, tentative

Rules:
- confidence: high (explicit statement with numbers), medium (clearly implied), low (inferred from context)
- context: exact verbatim quote, max 300 chars
- Extract EVERY number, amount, percentage, date mentioned
- If currency not specified, infer from context (Italian conversation -> EUR)
- For multi-party deals, list ALL parties
- For timeline mentions, convert to ISO date format when possible
- Return empty arrays if no facts found for a category
- Maximum 30 facts per chunk. Prioritize high-value financial and deal facts."""

DEEP_USER_PROMPT_TEMPLATE = """Analyze this {source_type} document for deep intelligence extraction.

Source: {source_label}
Date: {date}
Participants: {participants}

--- TEXT ---
{text}
--- END ---

Return JSON with exactly these 6 keys:
{{"financial": [...], "deal": [...], "commitment": [...], "negotiation": [...], "strategic": [...], "operational": [...]}}"""

CONSOLIDATION_PROMPT_TEMPLATE = """You are consolidating facts extracted from multiple chunks of the same document.
Review these facts and:
1. Remove exact duplicates
2. Resolve contradictions (keep the more specific/later mention)
3. Merge related facts (e.g. same deal mentioned in different chunks with different details)
4. Ensure all amounts are consistently formatted

CRITICAL: Return ONLY a raw JSON object. No markdown, no code blocks.

Input facts from {num_chunks} chunks:
{facts_json}

Return a single consolidated JSON with the same 6 category structure:
{{"financial": [...], "deal": [...], "commitment": [...], "negotiation": [...], "strategic": [...], "operational": [...]}}"""



_EXPECTED_KEYS = {"financial", "deal", "commitment", "negotiation", "strategic", "operational"}



_SUBCATEGORY_FIELD = {
    "financial": "fact_type",
    "deal": "term_type",
    "commitment": "commitment_type",
    "negotiation": "position_type",
    "strategic": "strategy_type",
    "operational": "status",
}




def parse_deep_response(response: str) -> dict | None:
    ""
    text = response.strip()


    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3 or len(parts) == 2:
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:].lstrip()
            text = inner


    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and any(k in parsed for k in _EXPECTED_KEYS):
            return parsed
    except json.JSONDecodeError:
        pass


    start = text.find("{")
    if start >= 0:
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, dict) and any(k in parsed for k in _EXPECTED_KEYS):
                    return parsed
            except json.JSONDecodeError:
                pass


        remainder = text[start:]
        for suffix in ["]}}", "]}", "}", "]}]}}", '"]}}', '"]}']:
            try:
                parsed = json.loads(remainder + suffix)
                if isinstance(parsed, dict) and any(k in parsed for k in _EXPECTED_KEYS):
                    return parsed
            except json.JSONDecodeError:
                continue

    return None





def make_deep_fact_id(subject: str, predicate: str, obj: str, amount: str = "") -> str:
    ""
    raw = f"{subject.lower().strip()}|{predicate.lower().strip()}|{obj.lower().strip()}|{amount.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]





def normalize_name(name: str) -> str:
    ""
    if not name:
        return name
    n = name.strip()
    nl = n.lower()
    for wrong, correct in STT_NAME_CORRECTIONS.items():
        if wrong in nl:
            nl = nl.replace(wrong, correct)
            n = nl.title()
    return n





def extract_deep_facts(
    parsed: dict,
    doc: dict,
    chunk_idx: int = 0,
    data: SBKData | None = None,
) -> list[dict]:
    ""
    facts = []
    source = doc["source"]
    source_id = doc["source_id"]
    source_date = doc.get("date", "")
    source_title = doc.get("title", "")
    now_iso = datetime.now(UTC).isoformat()

    for category in _EXPECTED_KEYS:
        items = parsed.get(category, [])
        if not isinstance(items, list):
            continue

        subcategory_field = _SUBCATEGORY_FIELD.get(category, "")

        for item in items:
            if not isinstance(item, dict):
                continue


            subject = ""
            predicate = ""
            obj = ""
            amount = ""
            currency = ""
            counterparty = ""
            conditions = ""
            timeline = ""
            subcategory = str(item.get(subcategory_field, "")) if subcategory_field else ""
            context = str(item.get("context", "") or "")[:300]
            confidence = str(item.get("confidence", "medium") or "medium")

            if category == "financial":
                subject = str(item.get("person_or_entity", "") or "")
                predicate = subcategory
                obj = str(item.get("value", "") or "")
                amount = str(item.get("value", "") or "")
                currency = str(item.get("currency", "") or "")

            elif category == "deal":
                parties = item.get("parties", [])
                if isinstance(parties, list) and parties:
                    subject = str(parties[0])
                    counterparty = ", ".join(str(p) for p in parties[1:])
                predicate = subcategory
                obj = str(item.get("description", "") or "")
                amount = str(item.get("value", "") or "")
                conditions = str(item.get("conditions", "") or "")

            elif category == "commitment":
                subject = str(item.get("person", "") or "")
                predicate = subcategory
                obj = str(item.get("description", "") or "")
                amount = str(item.get("amount", "") or "")
                currency = str(item.get("currency", "") or "")
                timeline = str(item.get("deadline", "") or "")
                conditions = str(item.get("conditions", "") or "")

            elif category == "negotiation":
                subject = str(item.get("person", "") or "")
                predicate = subcategory
                obj = str(item.get("description", "") or "")

            elif category == "strategic":
                subject = str(item.get("entity", "") or "")
                predicate = subcategory
                obj = str(item.get("description", "") or "")

            elif category == "operational":
                subject = str(item.get("owner", "") or "")
                predicate = "task"
                obj = str(item.get("task", "") or "")
                timeline = str(item.get("deadline", "") or "")

                resources = item.get("resources", "")
                if isinstance(resources, list):
                    conditions = ", ".join(str(r) for r in resources)
                else:
                    conditions = str(resources or "")


            if not subject.strip() and not obj.strip():
                continue


            subject = normalize_name(subject)
            counterparty = normalize_name(counterparty)


            subject_pid = ""
            counterparty_pid = ""
            if data and subject:
                pid = data.resolve_person_by_name(subject)
                if pid:
                    subject_pid = pid
            if data and counterparty:
                pid = data.resolve_person_by_name(counterparty)
                if pid:
                    counterparty_pid = pid

            fact_id = make_deep_fact_id(subject, predicate, obj, amount)

            facts.append(
                {
                    "fact_id": fact_id,
                    "source_type": source,
                    "source_id": source_id,
                    "source_date": source_date,
                    "source_title": source_title,
                    "category": category,
                    "subcategory": subcategory,
                    "subject": subject,
                    "subject_person_id": subject_pid,
                    "predicate": predicate,
                    "object": obj,
                    "amount": amount,
                    "currency": currency,
                    "counterparty": counterparty,
                    "counterparty_person_id": counterparty_pid,
                    "conditions": conditions,
                    "timeline": timeline,
                    "context": context,
                    "confidence": confidence,
                    "chunk_idx": chunk_idx,
                    "extracted_at": now_iso,
                }
            )

    return facts





def _process_chunk(
    doc: dict,
    chunk: Chunk,
    force: bool = False,
) -> dict:
    ""
    source = doc["source"]
    source_id = doc["source_id"]
    idx = chunk.chunk_idx


    cache_dir = DEEP_RESPONSES_DIR / source
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{source_id}_chunk_{idx}.json"

    if cache_file.exists() and not force:
        try:
            parsed = json.loads(cache_file.read_text())

            saved_hash = parsed.pop("_content_hash", None)
            if saved_hash is not None:
                current_hash = compute_source_hash(chunk.text)
                if saved_hash != current_hash:
                    pass
                else:
                    return {
                        "doc": doc,
                        "chunk_idx": idx,
                        "parsed": parsed,
                        "cached": True,
                        "error": None,
                    }
            else:

                return {
                    "doc": doc,
                    "chunk_idx": idx,
                    "parsed": parsed,
                    "cached": True,
                    "error": None,
                }
        except (json.JSONDecodeError, OSError):
            pass


    prompt = DEEP_USER_PROMPT_TEMPLATE.format(
        source_type=source.replace("_", " ").title(),
        source_label=doc.get("title", source_id),
        date=doc.get("date", "unknown"),
        participants=doc.get("participants", "unknown"),
        text=chunk.text,
    )

    doc_provider = doc.get("_provider", _PROVIDER)

    try:
        for _attempt in range(2):
            response = call_claude(
                prompt=prompt,
                system=DEEP_SYSTEM_PROMPT,
                model=SONNET_MODEL,
                max_tokens=8192,
                temperature=0.1 if _attempt == 0 else 0.0,
                provider=doc_provider,
            )
            parsed = parse_deep_response(response)
            if parsed is not None:
                break
        if parsed is None:
            return {
                "doc": doc,
                "chunk_idx": idx,
                "parsed": None,
                "cached": False,
                "error": "Failed to parse response after 2 attempts",
            }


        cache_data = {**parsed, "_content_hash": compute_source_hash(chunk.text)}
        cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2))
        return {"doc": doc, "chunk_idx": idx, "parsed": parsed, "cached": False, "error": None}

    except Exception as e:
        return {"doc": doc, "chunk_idx": idx, "parsed": None, "cached": False, "error": str(e)}


def _parse_batch_response(response: str, expected_count: int) -> list[dict | None]:
    ""




    text = response.strip()


    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3 or len(parts) == 2:
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:].lstrip()
            text = inner


    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            results = []
            for item in parsed:
                if isinstance(item, dict) and any(k in item for k in _EXPECTED_KEYS):
                    results.append(item)
                else:
                    results.append(None)
            return results
    except json.JSONDecodeError:
        pass


    start = text.find("[")
    if start >= 0:
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, list):
                    results = []
                    for item in parsed:
                        if isinstance(item, dict) and any(k in item for k in _EXPECTED_KEYS):
                            results.append(item)
                        else:
                            results.append(None)
                    return results
            except json.JSONDecodeError:
                pass


        remainder = text[start:]
        for suffix in ["}]", "]}}", "]}", "}]}]", '"}]', '"]}]']:
            try:
                parsed = json.loads(remainder + suffix)
                if isinstance(parsed, list):
                    results = []
                    for item in parsed:
                        if isinstance(item, dict) and any(k in item for k in _EXPECTED_KEYS):
                            results.append(item)
                        else:
                            results.append(None)
                    return results
            except json.JSONDecodeError:
                continue

    return []


def _process_chunk_batch(
    doc_chunk_pairs: list[tuple[dict, Chunk]],
    force: bool = False,
) -> list[dict]:
    ""







    results: list[dict] = []
    uncached_pairs: list[tuple[int, dict, Chunk]] = []


    for doc, chunk in doc_chunk_pairs:
        source = doc["source"]
        source_id = doc["source_id"]
        cache_dir = DEEP_RESPONSES_DIR / source
        cache_file = cache_dir / f"{source_id}_chunk_0.json"

        if cache_file.exists() and not force:
            try:
                parsed = json.loads(cache_file.read_text())
                results.append(
                    {
                        "doc": doc,
                        "chunk_idx": 0,
                        "parsed": parsed,
                        "cached": True,
                        "error": None,
                    }
                )
                continue
            except (json.JSONDecodeError, OSError):
                pass

        idx = len(results)
        results.append(
            {
                "doc": doc,
                "chunk_idx": 0,
                "parsed": None,
                "cached": False,
                "error": None,
            }
        )
        uncached_pairs.append((idx, doc, chunk))

    if not uncached_pairs:
        return results


    n = len(uncached_pairs)
    doc_blocks = []
    for i, (_, doc, chunk) in enumerate(uncached_pairs):
        title = doc.get("title", doc["source_id"])
        date = doc.get("date", "unknown")
        participants = doc.get("participants", "unknown")
        doc_blocks.append(
            f"--- DOCUMENT {i + 1} ---\n"
            f"Source: {title}\n"
            f"Date: {date}\n"
            f"Participants: {participants}\n\n"
            f"{chunk.text}\n"
            f"--- END DOCUMENT {i + 1} ---"
        )

    combined_text = "\n\n".join(doc_blocks)
    batch_system = (
        f"You are processing {n} documents. Return a JSON ARRAY of {n} objects, "
        f"one per document in order. Start with [ and end with ].\n\n" + DEEP_SYSTEM_PROMPT
    )
    prompt = (
        f"Analyze these {n} documents for deep intelligence extraction.\n\n"
        f"{combined_text}\n\n"
        f"Return a JSON ARRAY of {n} objects, each with exactly these 6 keys:\n"
        f'[{{"financial": [...], "deal": [...], "commitment": [...], '
        f'"negotiation": [...], "strategic": [...], "operational": [...]}}, ...]'
    )


    batch_provider = (
        uncached_pairs[0][1].get("_provider", _PROVIDER) if uncached_pairs else _PROVIDER
    )

    try:
        for _attempt in range(2):
            response = call_claude(
                prompt=prompt,
                system=batch_system,
                model=SONNET_MODEL,
                max_tokens=8192 * min(n, 4),
                temperature=0.1 if _attempt == 0 else 0.0,
                provider=batch_provider,
            )
            parsed_array = _parse_batch_response(response, n)
            if len(parsed_array) == n:
                break

            if _attempt == 0 and len(parsed_array) > 0:
                log.warning(f"Batch parse: expected {n} results, got {len(parsed_array)}, retrying")
                parsed_array = []


        if len(parsed_array) == n:
            for i, (result_idx, doc, _chunk) in enumerate(uncached_pairs):
                parsed = parsed_array[i]
                results[result_idx]["parsed"] = parsed
                if parsed is not None:
                    cache_dir = DEEP_RESPONSES_DIR / doc["source"]
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_file = cache_dir / f"{doc['source_id']}_chunk_0.json"
                    cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
                else:
                    results[result_idx]["error"] = "Parsed as None in batch"
        else:

            log.warning(
                f"Batch parse failed (got {len(parsed_array)}/{n}), "
                f"falling back to individual processing"
            )
            for result_idx, doc, chunk in uncached_pairs:
                individual = _process_chunk(doc, chunk, force=force)
                results[result_idx] = individual

    except Exception as e:

        log.warning(f"Batch API call failed ({e}), falling back to individual processing")
        for result_idx, doc, chunk in uncached_pairs:
            individual = _process_chunk(doc, chunk, force=force)
            results[result_idx] = individual

    return results


def _consolidate_chunks(
    doc: dict,
    chunk_results: list[dict],
    force: bool = False,
) -> dict | None:
    ""
    source = doc["source"]
    source_id = doc["source_id"]

    cache_dir = DEEP_RESPONSES_DIR / source
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{source_id}_consolidated.json"

    if cache_file.exists() and not force:
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass


    combined: dict[str, list] = {k: [] for k in _EXPECTED_KEYS}
    for result in chunk_results:
        parsed = result.get("parsed")
        if not parsed:
            continue
        for cat in _EXPECTED_KEYS:
            items = parsed.get(cat, [])
            if isinstance(items, list):
                combined[cat].extend(items)


    total_facts = sum(len(v) for v in combined.values())
    if total_facts == 0:
        return None

    facts_json = json.dumps(combined, ensure_ascii=False, indent=2)
    num_chunks = len(chunk_results)

    prompt = CONSOLIDATION_PROMPT_TEMPLATE.format(
        num_chunks=num_chunks,
        facts_json=facts_json,
    )


    consolidation_provider = doc.get("_provider", _PROVIDER) if isinstance(doc, dict) else _PROVIDER

    try:
        for _attempt in range(2):
            response = call_claude(
                prompt=prompt,
                system="You are a fact consolidation engine. Merge, dedup, and resolve contradictions.",
                model=SONNET_MODEL,
                max_tokens=4096,
                temperature=0.1 if _attempt == 0 else 0.0,
                provider=consolidation_provider,
            )
            parsed = parse_deep_response(response)
            if parsed is not None:
                break
        if parsed is None:
            log.warning(f"Consolidation failed for {source}/{source_id}, using raw merged")
            parsed = combined

        cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
        return parsed

    except PermanentAPIError:



        raise
    except Exception as e:
        log.warning(f"Consolidation error for {source}/{source_id}: {e}")
        return combined


def _postprocess_facts(facts: list[dict], data: SBKData | None = None) -> list[dict]:
    ""
    if not facts:
        return facts


    for f in facts:
        f["subject"] = normalize_name(f.get("subject", ""))
        f["counterparty"] = normalize_name(f.get("counterparty", ""))


    if data:
        for f in facts:
            if f["subject"] and not f.get("subject_person_id"):
                pid = data.resolve_person_by_name(f["subject"])
                if pid:
                    f["subject_person_id"] = pid
            if f["counterparty"] and not f.get("counterparty_person_id"):
                pid = data.resolve_person_by_name(f["counterparty"])
                if pid:
                    f["counterparty_person_id"] = pid


    seen: set[str] = set()
    deduped = []
    for f in facts:
        fid = f.get("fact_id", "")
        if fid and fid in seen:
            continue
        seen.add(fid)
        deduped.append(f)


    filtered = [f for f in deduped if f.get("subject", "").strip() or f.get("object", "").strip()]

    log.debug(f"Post-processing: {len(facts)} -> {len(filtered)} facts (dedup + filter)")
    return filtered


def process_document(
    doc: dict,
    data: SBKData | None = None,
    workers: int = 1,
    force: bool = False,
    min_chars: int = MIN_DOC_CHARS_DEFAULT,
) -> list[dict]:
    ""
    text = doc.get("text", "")
    if len(text) < min_chars:
        return []


    chunks = chunk_document_semantic(
        text, max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS
    )


    chunk_results = []
    if workers <= 1 or len(chunks) <= 1:
        for chunk in chunks:
            result = _process_chunk(doc, chunk, force=force)
            chunk_results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
            futures = {
                executor.submit(_process_chunk, doc, chunk, force): chunk for chunk in chunks
            }
            for future in as_completed(futures):
                chunk_results.append(future.result())

        chunk_results.sort(key=lambda r: r.get("chunk_idx", 0))


    for result in chunk_results:
        if result.get("error"):
            log.warning(
                f"Chunk {result.get('chunk_idx', '?')} error for "
                f"{doc['source']}/{doc['source_id']}: {result['error']}"
            )


    successful_chunks = [r for r in chunk_results if r.get("parsed")]
    if not successful_chunks:
        return []

    if len(successful_chunks) > 1:
        consolidated = _consolidate_chunks(doc, successful_chunks, force=force)
        if consolidated:
            all_facts = extract_deep_facts(consolidated, doc, chunk_idx=-1, data=data)
        else:
            all_facts = []
            for r in successful_chunks:
                all_facts.extend(
                    extract_deep_facts(r["parsed"], doc, chunk_idx=r.get("chunk_idx", 0), data=data)
                )
    else:

        r = successful_chunks[0]
        all_facts = extract_deep_facts(r["parsed"], doc, chunk_idx=r.get("chunk_idx", 0), data=data)


    all_facts = _postprocess_facts(all_facts, data=data)

    return all_facts





def estimate_cost(
    docs: list[dict], min_chars: int = MIN_DOC_CHARS_DEFAULT, provider: str = "anthropic"
) -> dict:
    ""
    from xs_l3_common import PRICING, PROVIDER_CONFIG, PROVIDER_PRICING

    eligible = [d for d in docs if len(d.get("text", "")) >= min_chars]
    total_chars = sum(len(d["text"]) for d in eligible)

    total_chunks = 0
    for d in eligible:
        n_chunks = max(1, (len(d["text"]) + CHUNK_MAX_CHARS - 1) // CHUNK_MAX_CHARS)
        total_chunks += n_chunks

    multi_chunk_docs = sum(1 for d in eligible if len(d["text"]) > CHUNK_MAX_CHARS)


    est_input_tokens = total_chars // 4 + total_chunks * 1000
    est_output_tokens = total_chunks * 2000


    est_input_tokens += multi_chunk_docs * 3000
    est_output_tokens += multi_chunk_docs * 1500


    config = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["anthropic"])
    model = config["default_model"]
    pricing = PRICING.get(model, PROVIDER_PRICING.get(provider, {"input": 3.0, "output": 15.0}))
    cost = (est_input_tokens * pricing["input"] + est_output_tokens * pricing["output"]) / 1_000_000
    return {
        "eligible_documents": len(eligible),
        "skipped_documents": len(docs) - len(eligible),
        "total_chars": total_chars,
        "est_chunks": total_chunks,
        "est_consolidations": multi_chunk_docs,
        "est_input_tokens": est_input_tokens,
        "est_output_tokens": est_output_tokens,
        "est_cost_usd": round(cost, 2),
    }





def run_batch(
    docs: list[dict],
    data: SBKData | None = None,
    workers: int = 4,
    force: bool = False,
    min_chars: int = MIN_DOC_CHARS_DEFAULT,
    batch_size: int = 1,
) -> list[dict]:
    ""







    eligible = [d for d in docs if len(d.get("text", "")) >= min_chars]
    skipped = len(docs) - len(eligible)
    if skipped > 0:
        log.info(f"Skipping {skipped} documents shorter than {min_chars} chars")

    all_facts: list[dict] = []
    processed = 0
    errors = 0
    start_time = time.time()

    if batch_size <= 1:

        if workers <= 1:
            for doc in eligible:
                try:
                    facts = process_document(
                        doc, data=data, workers=1, force=force, min_chars=min_chars
                    )
                    all_facts.extend(facts)
                except Exception as e:
                    errors += 1
                    log.warning(f"Error processing {doc['source']}/{doc['source_id']}: {e}")
                processed += 1
                if processed % 10 == 0:
                    elapsed = time.time() - start_time
                    log.info(
                        f"Progress: {processed}/{len(eligible)} docs, "
                        f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                    )
        else:

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(process_document, doc, data, 1, force, min_chars): doc
                    for doc in eligible
                }
                for future in as_completed(futures):
                    doc = futures[future]
                    try:
                        facts = future.result()
                        all_facts.extend(facts)
                    except Exception as e:
                        errors += 1
                        log.warning(f"Error processing {doc['source']}/{doc['source_id']}: {e}")
                    processed += 1
                    if processed % 10 == 0:
                        elapsed = time.time() - start_time
                        log.info(
                            f"Progress: {processed}/{len(eligible)} docs, "
                            f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                        )
    else:

        single_chunk_docs = []
        multi_chunk_docs = []
        for doc in eligible:
            text_len = len(doc.get("text", ""))
            if text_len <= CHUNK_MAX_CHARS:
                single_chunk_docs.append(doc)
            else:
                multi_chunk_docs.append(doc)

        log.info(
            f"Batch mode (batch_size={batch_size}): "
            f"{len(single_chunk_docs)} single-chunk, {len(multi_chunk_docs)} multi-chunk"
        )



        sc_pairs: list[tuple[dict, Chunk]] = []
        for doc in single_chunk_docs:
            chunks = chunk_document_semantic(
                doc["text"], max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS
            )
            if chunks:
                sc_pairs.append((doc, chunks[0]))


        batches = [sc_pairs[i : i + batch_size] for i in range(0, len(sc_pairs), batch_size)]

        if workers <= 1:
            for batch in batches:
                try:
                    batch_results = _process_chunk_batch(batch, force=force)
                    for result in batch_results:
                        if result.get("error"):
                            errors += 1
                            log.warning(
                                f"Batch chunk error for "
                                f"{result['doc']['source']}/{result['doc']['source_id']}: "
                                f"{result['error']}"
                            )
                        if result.get("parsed"):
                            facts = extract_deep_facts(
                                result["parsed"],
                                result["doc"],
                                chunk_idx=0,
                                data=data,
                            )
                            all_facts.extend(facts)
                except Exception as e:
                    errors += len(batch)
                    log.warning(f"Batch processing error: {e}")
                processed += len(batch)
                if processed % 10 == 0:
                    elapsed = time.time() - start_time
                    log.info(
                        f"Progress: {processed}/{len(eligible)} docs, "
                        f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_chunk_batch, batch, force): batch for batch in batches
                }
                for future in as_completed(futures):
                    batch = futures[future]
                    try:
                        batch_results = future.result()
                        for result in batch_results:
                            if result.get("error"):
                                errors += 1
                                log.warning(
                                    f"Batch chunk error for "
                                    f"{result['doc']['source']}/{result['doc']['source_id']}: "
                                    f"{result['error']}"
                                )
                            if result.get("parsed"):
                                facts = extract_deep_facts(
                                    result["parsed"],
                                    result["doc"],
                                    chunk_idx=0,
                                    data=data,
                                )
                                all_facts.extend(facts)
                    except Exception as e:
                        errors += len(batch)
                        log.warning(f"Batch processing error: {e}")
                    processed += len(batch)
                    if processed % 10 == 0:
                        elapsed = time.time() - start_time
                        log.info(
                            f"Progress: {processed}/{len(eligible)} docs, "
                            f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                        )


        if multi_chunk_docs:
            log.info(f"Processing {len(multi_chunk_docs)} multi-chunk documents individually")
            if workers <= 1:
                for doc in multi_chunk_docs:
                    try:
                        facts = process_document(
                            doc, data=data, workers=1, force=force, min_chars=min_chars
                        )
                        all_facts.extend(facts)
                    except Exception as e:
                        errors += 1
                        log.warning(f"Error processing {doc['source']}/{doc['source_id']}: {e}")
                    processed += 1
                    if processed % 10 == 0:
                        elapsed = time.time() - start_time
                        log.info(
                            f"Progress: {processed}/{len(eligible)} docs, "
                            f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                        )
            else:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(process_document, doc, data, 1, force, min_chars): doc
                        for doc in multi_chunk_docs
                    }
                    for future in as_completed(futures):
                        doc = futures[future]
                        try:
                            facts = future.result()
                            all_facts.extend(facts)
                        except Exception as e:
                            errors += 1
                            log.warning(f"Error processing {doc['source']}/{doc['source_id']}: {e}")
                        processed += 1
                        if processed % 10 == 0:
                            elapsed = time.time() - start_time
                            log.info(
                                f"Progress: {processed}/{len(eligible)} docs, "
                                f"{len(all_facts)} facts, {errors} errors ({elapsed:.0f}s)"
                            )


        all_facts = _postprocess_facts(all_facts, data=data)

    elapsed = time.time() - start_time
    log.info(
        f"DONE: {processed} docs processed, {len(all_facts)} facts extracted, "
        f"{errors} errors ({elapsed:.0f}s)"
    )
    return all_facts





def _richieste_batch(eligible: list[dict], force: bool = False, cache: dict | None = None):
    ""


    from xs_batch_api import BatchRequest, id_stabile

    seen_ids: set[str] = set()

    for doc in eligible:
        source = doc["source"]
        source_id = doc["source_id"]
        doc_key = f"{source}/{source_id}"
        text = doc.get("text", "")

        chunks = chunk_document_semantic(
            text, max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS
        )

        for chunk in chunks:
            cache_dir = DEEP_RESPONSES_DIR / source
            cache_file = cache_dir / f"{source_id}_chunk_{chunk.chunk_idx}.json"


            if cache_file.exists() and not force:
                if cache is None:

                    continue
                try:
                    parsed = json.loads(cache_file.read_text())
                    cache.setdefault(doc_key, []).append((chunk.chunk_idx, parsed))
                    continue
                except (json.JSONDecodeError, OSError):
                    pass



            custom_id = id_stabile(source, source_id, chunk.chunk_idx, prefisso="deep/")
            doppio = 1
            while custom_id in seen_ids:
                custom_id = id_stabile(
                    source, f"{source_id}#{doppio}", chunk.chunk_idx, prefisso="deep/"
                )
                doppio += 1
            seen_ids.add(custom_id)

            title = doc.get("title", source_id)
            date = doc.get("date", "unknown")
            participants = doc.get("participants", "unknown")

            prompt = DEEP_USER_PROMPT_TEMPLATE.format(
                source_type=source,
                source_label=title,
                date=date,
                participants=participants,
                text=chunk.text,
            )

            yield (
                BatchRequest(
                    custom_id=custom_id,
                    user_content=prompt,
                    system_prompt=DEEP_SYSTEM_PROMPT,
                    model=SONNET_MODEL,
                    max_tokens=8192,
                    temperature=0.1,
                ),
                doc,
                chunk.chunk_idx,
                len(chunks),
            )


def stima_unione_pezzi(docs: list[dict], force: bool = False) -> dict:
    ""




    from xs_batch_api import uscita_media
    from xs_l3_common import PRICING

    prezzi = PRICING.get(SONNET_MODEL, {"input": 3.0, "output": 15.0})
    per_pezzo = uscita_media(DEEP_RESPONSES_DIR) or 8192 / 4
    per_unione = min(uscita_media(DEEP_RESPONSES_DIR, escludi=("_chunk_",)) or 4096 / 4, 4096)
    unioni = 0
    tok_in = tok_out = 0.0
    for d in docs:
        testo = d.get("text", "")
        if len(testo) <= CHUNK_MAX_CHARS:
            continue
        unita = DEEP_RESPONSES_DIR / d["source"] / f"{d['source_id']}_consolidated.json"
        if unita.exists() and not force:
            continue
        pezzi = len(
            chunk_document_semantic(
                testo, max_chars=CHUNK_MAX_CHARS, overlap_chars=CHUNK_OVERLAP_CHARS
            )
        )
        if pezzi <= 1:
            continue
        unioni += 1
        tok_in += pezzi * per_pezzo + len(CONSOLIDATION_PROMPT_TEMPLATE) / 4
        tok_out += per_unione
    costo = (tok_in * prezzi["input"] + tok_out * prezzi["output"]) / 1_000_000
    return {
        "unioni": unioni,
        "est_input_tokens": int(tok_in),
        "est_output_tokens": int(tok_out),
        "est_cost_usd": round(costo, 2),
    }


def run_batch_api(
    docs: list[dict],
    data: SBKData | None = None,
    force: bool = False,
    min_chars: int = MIN_DOC_CHARS_DEFAULT,
) -> list[dict]:
    ""





    from xs_batch_api import chiudi_stato, run_batch_pipeline


    eligible = [d for d in docs if len(d.get("text", "")) >= min_chars]
    skipped = len(docs) - len(eligible)
    if skipped > 0:
        log.info(f"Skipping {skipped} documents shorter than {min_chars} chars")


    batch_requests: list = []
    request_map: dict[str, tuple[dict, int, int]] = {}
    cached_chunks: dict[str, list[tuple[int, dict]]] = {}
    for richiesta, doc, chunk_idx, n_chunks in _richieste_batch(
        eligible, force=force, cache=cached_chunks
    ):
        batch_requests.append(richiesta)
        request_map[richiesta.custom_id] = (doc, chunk_idx, n_chunks)

    log.info(
        f"Batch API: {len(eligible)} docs, "
        f"{sum(len(v) for v in cached_chunks.values())} cached chunks, "
        f"{len(batch_requests)} new chunks to process"
    )


    api_results: dict[str, dict] = {}
    if batch_requests:
        api_results = run_batch_pipeline(
            batch_requests,
            label="deep-extract",
            poll_interval=30,
            state_dir=DEEP_RESPONSES_DIR,
            tieni_stato=True,
        )



    doc_chunks: dict[str, dict[int, dict | None]] = {}
    doc_lookup: dict[str, tuple[dict, int]] = {}


    for doc_key, chunks_list in cached_chunks.items():
        if doc_key not in doc_chunks:
            doc_chunks[doc_key] = {}
        for chunk_idx, parsed in chunks_list:
            doc_chunks[doc_key][chunk_idx] = parsed


    errors = 0
    for custom_id, result in api_results.items():
        if custom_id not in request_map:
            continue
        doc, chunk_idx, total_chunks = request_map[custom_id]
        source = doc["source"]
        source_id = doc["source_id"]
        doc_key = f"{source}/{source_id}"

        if doc_key not in doc_chunks:
            doc_chunks[doc_key] = {}
        doc_lookup[doc_key] = (doc, total_chunks)

        if result.get("error"):
            errors += 1
            log.warning(f"Batch API error for {doc_key} chunk {chunk_idx}: {result['error']}")
            continue

        parsed = parse_deep_response(result.get("text", ""))
        if parsed is None:
            errors += 1
            log.warning(f"Failed to parse batch result for {doc_key} chunk {chunk_idx}")
            continue

        doc_chunks[doc_key][chunk_idx] = parsed


        cache_dir = DEEP_RESPONSES_DIR / source
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{source_id}_chunk_{chunk_idx}.json"
        cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))



    if batch_requests:
        chiudi_stato("deep-extract", DEEP_RESPONSES_DIR)


    for doc in eligible:
        doc_key = f"{doc['source']}/{doc['source_id']}"
        if doc_key in doc_chunks and doc_key not in doc_lookup:
            text = doc.get("text", "")
            total = max(1, (len(text) + CHUNK_MAX_CHARS - 1) // CHUNK_MAX_CHARS)
            doc_lookup[doc_key] = (doc, total)


    all_facts: list[dict] = []

    for doc_key, chunk_map in doc_chunks.items():
        if doc_key not in doc_lookup:
            continue
        doc, total_chunks = doc_lookup[doc_key]

        successful = [(idx, p) for idx, p in sorted(chunk_map.items()) if p is not None]
        if not successful:
            continue

        if len(successful) > 1:

            chunk_results = [{"doc": doc, "chunk_idx": idx, "parsed": p} for idx, p in successful]
            consolidated = _consolidate_chunks(doc, chunk_results, force=force)
            if consolidated:
                facts = extract_deep_facts(consolidated, doc, chunk_idx=-1, data=data)
            else:
                facts = []
                for idx, p in successful:
                    facts.extend(extract_deep_facts(p, doc, chunk_idx=idx, data=data))
        else:
            idx, p = successful[0]
            facts = extract_deep_facts(p, doc, chunk_idx=idx, data=data)

        all_facts.extend(facts)


    all_facts = _postprocess_facts(all_facts, data=data)

    log.info(f"Batch API complete: {len(doc_chunks)} docs, {len(all_facts)} facts, {errors} errors")
    return all_facts





_OUTPUT_COLUMNS = [
    "fact_id",
    "source_type",
    "source_id",
    "source_date",
    "source_title",
    "category",
    "subcategory",
    "subject",
    "subject_person_id",
    "predicate",
    "object",
    "amount",
    "currency",
    "counterparty",
    "counterparty_person_id",
    "conditions",
    "timeline",
    "context",
    "confidence",
    "chunk_idx",
    "extracted_at",
]


def save_facts(facts: list[dict]) -> Path:
    ""
    if not facts:
        log.warning("No facts to save")
        return DEEP_FACTS_FILE

    new_df = pd.DataFrame(facts)


    for col in _OUTPUT_COLUMNS:
        if col not in new_df.columns:
            new_df[col] = ""


    new_df = new_df[[c for c in _OUTPUT_COLUMNS if c in new_df.columns]]


    new_df = new_df.drop_duplicates(subset=["fact_id"], keep="last")


    if DEEP_FACTS_FILE.exists():
        existing = pd.read_parquet(DEEP_FACTS_FILE)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["fact_id"], keep="last")
    else:
        combined = new_df


    DEEP_FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_write_parquet(combined, DEEP_FACTS_FILE, index=False)
    log.info(f"Saved {len(combined)} facts to {DEEP_FACTS_FILE}")


    if "category" in combined.columns:
        for cat, count in combined["category"].value_counts().items():
            log.info(f"  {cat}: {count}")

    return DEEP_FACTS_FILE





def run_consolidate_only(
    sources: list[str],
    data: SBKData | None = None,
    force: bool = False,
) -> list[dict]:
    ""
    all_facts: list[dict] = []

    for source in sources:
        cache_dir = DEEP_RESPONSES_DIR / source
        if not cache_dir.exists():
            log.info(f"No cached chunks for {source}, skipping")
            continue


        doc_chunks: dict[str, list[Path]] = {}
        for f in sorted(cache_dir.glob("*_chunk_*.json")):

            match = re.match(r"^(.+)_chunk_(\d+)\.json$", f.name)
            if match:
                doc_id = match.group(1)
                if doc_id not in doc_chunks:
                    doc_chunks[doc_id] = []
                doc_chunks[doc_id].append(f)

        log.info(f"  {source}: {len(doc_chunks)} documents with cached chunks")

        for doc_id, chunk_files in doc_chunks.items():

            doc = {
                "source": source,
                "source_id": doc_id,
                "title": doc_id,
                "date": "",
                "participants": "",
                "text": "",
            }


            chunk_results = []
            for cf in sorted(chunk_files):
                try:
                    parsed = json.loads(cf.read_text())
                    match = re.match(r"^(.+)_chunk_(\d+)\.json$", cf.name)
                    idx = int(match.group(2)) if match else 0
                    chunk_results.append({"doc": doc, "chunk_idx": idx, "parsed": parsed})
                except (json.JSONDecodeError, OSError) as e:
                    log.warning(f"Failed to load chunk {cf}: {e}")

            if not chunk_results:
                continue


            if len(chunk_results) > 1:
                consolidated = _consolidate_chunks(doc, chunk_results, force=force)
                if consolidated:
                    facts = extract_deep_facts(consolidated, doc, chunk_idx=-1, data=data)
                else:
                    facts = []
                    for r in chunk_results:
                        facts.extend(
                            extract_deep_facts(
                                r["parsed"], doc, chunk_idx=r.get("chunk_idx", 0), data=data
                            )
                        )
            else:
                r = chunk_results[0]
                facts = extract_deep_facts(
                    r["parsed"], doc, chunk_idx=r.get("chunk_idx", 0), data=data
                )


            facts = _postprocess_facts(facts, data=data)
            all_facts.extend(facts)

    return all_facts





def main():
    parser = argparse.ArgumentParser(
        description="SBK Deep Intelligence Extraction (Claude Sonnet)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show estimate without processing")
    parser.add_argument("--batch", action="store_true", help="Process all documents")
    parser.add_argument(
        "--batch-api",
        action="store_true",
        help="Use Anthropic Message Batches API (50%% discount, async ~1h)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=DEEP_SOURCES,
        help="Filter by source (repeatable)",
    )
    parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        metavar="SRC",
        help="Exclude a source from the run (repeatable), to reduce cost",
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default=4)")
    parser.add_argument("--force", action="store_true", help="Reprocess even if cached")
    parser.add_argument(
        "--force-source",
        choices=DEEP_SOURCES,
        metavar="SOURCE",
        help="Delete cache for a specific source and exit",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process new/modified documents",
    )
    parser.add_argument(
        "--consolidate-only",
        action="store_true",
        help="Only run pass 2+3 on existing chunk results",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--no-email-filter",
        action="store_true",
        help="Disable email pre-filter (send all emails to LLM)",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=MIN_DOC_CHARS_DEFAULT,
        help=f"Minimum document size in chars (default={MIN_DOC_CHARS_DEFAULT})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Documents per API call for single-chunk docs (default=1, use 10 for Gemini)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--smart-route",
        action="store_true",
        help="Route docs to quality/economy providers based on sensitivity",
    )
    parser.add_argument(
        "--quality-provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="anthropic",
        help="Quality provider for smart routing (default: anthropic)",
    )
    parser.add_argument(
        "--economy-provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="deepseek",
        help="Economy provider for smart routing (default: deepseek)",
    )
    args = parser.parse_args()
    # Take the lock only after the arguments are parsed, so --help writes nothing.
    _acquire_lock()

    setup_logging(verbose=args.verbose, name="sbk-deep-extract")


    global _PROVIDER
    _PROVIDER = args.provider


    if args.force_source:
        import shutil

        target_dir = DEEP_RESPONSES_DIR / args.force_source
        if target_dir.exists():
            count = sum(1 for _ in target_dir.iterdir())
            shutil.rmtree(target_dir)
            log.info(f"Deleted cache for '{args.force_source}': {count} files removed")
        else:
            log.info(f"No cache found for '{args.force_source}' (nothing to delete)")
        return

    sources_to_process = args.source if args.source else DEEP_SOURCES
    _excl = set(args.exclude_source or [])
    if _excl:
        sources_to_process = [x for x in sources_to_process if x not in _excl]
        log.info(f"Sources EXCLUDED from run: {sorted(_excl)} -> {len(sources_to_process)} remaining")


    if args.incremental and not args.consolidate_only:
        from sbk_config import check_inputs_changed


        _deep_input_dirs = [
            DATA_ROOT / "plaud" / "raw",
            DATA_ROOT / "tactiq" / "raw",
            DATA_ROOT / "attio" / "transcripts",
            DATA_ROOT / "attio",
            EMAILS_DIR,
            DATA_ROOT / "slack" / "conversations",
            DATA_ROOT / "slack" / "dm",
            DATA_ROOT / "whatsapp" / "chats",
            DATA_ROOT / "chatgpt" / "processed",
            DATA_ROOT / "notion" / "processed",
            DATA_ROOT / "gdrive" / "processed",
            VOICE_MEMOS_TRANSCRIPTS_DIR,
        ]
        if not check_inputs_changed("l3-deep-extract", _deep_input_dirs):
            log.info("Incremental: inputs unchanged, skipping")
            if args.dry_run:

                print("\nInputs unchanged since the last real run: the stage would be skipped.")
                print("  New to process:   0")
                print("  Est. total cost:  $0.00 (inputs unchanged, nothing to send)")
                return
            from sbk_config import mark_last_run

            mark_last_run("l3-deep-extract")
            return


    if args.consolidate_only:
        log.info("Consolidate-only mode: running pass 2+3 on cached chunk results")
        data = SBKData()
        facts = run_consolidate_only(sources_to_process, data=data, force=args.force)
        save_facts(facts)
        return


    all_docs: list[dict] = []
    for source in sources_to_process:
        loader = LOADERS.get(source)
        if not loader:
            log.warning(f"No loader found for source: {source}")
            continue
        docs = loader()
        log.info(f"  {source}: {len(docs)} documents")
        all_docs.extend(docs)

    log.info(f"Total: {len(all_docs)} documents from {len(sources_to_process)} sources")


    if not args.no_email_filter and any(d.get("source") == "email" for d in all_docs):
        email_docs = [d for d in all_docs if d.get("source") == "email"]
        other_docs = [d for d in all_docs if d.get("source") != "email"]
        kept_emails, filter_stats = email_prefilter(email_docs)
        log.info(
            f"Email pre-filter: {filter_stats['total']} -> {filter_stats['kept']} "
            f"({filter_stats['removal_pct']}% removed)"
        )
        all_docs = other_docs + kept_emails


    if args.smart_route:
        router = SmartRouter(
            quality_provider=args.quality_provider,
            economy_provider=args.economy_provider,
        )
        for doc in all_docs:
            doc["_provider"] = router.route(doc)
        router.log_stats()


    if args.dry_run:
        eligible = [d for d in all_docs if len(d.get("text", "")) >= args.min_chars]




        from xs_batch_api import stima_costo_richieste, uscita_media

        da_leggere: set[str] = set()

        def _richieste():
            for richiesta, doc, _pezzo, _pezzi in _richieste_batch(eligible, force=args.force):
                da_leggere.add(f"{doc['source']}/{doc['source_id']}")
                yield richiesta


        st = stima_costo_richieste(_richieste(), uscita_token=uscita_media(DEEP_RESPONSES_DIR))
        unione = stima_unione_pezzi(eligible, force=args.force)
        primo_passo = st["est_cost_usd_batch"] if args.batch_api else st["est_cost_usd_sync"]
        print(f"\n{'=' * 65}")
        print("DEEP EXTRACTION — DRY RUN SUMMARY")
        print(f"{'=' * 65}")
        for source in sources_to_process:
            count = sum(1 for d in all_docs if d["source"] == source)
            eligible_count = sum(1 for d in eligible if d["source"] == source)
            nuovi = sum(1 for k in da_leggere if k.split("/", 1)[0] == source)
            print(
                f"  {source:15s}: {count:5d} total, {eligible_count:5d} eligible, "
                f"{eligible_count - nuovi:5d} cached, {nuovi:5d} new"
            )
        print(f"{'=' * 65}")
        print(f"  Total documents:  {len(all_docs):6d}")
        print(f"  Eligible (>={args.min_chars}c): {len(eligible):6d}")
        print(f"  Skipped (short):  {len(all_docs) - len(eligible):6d}")
        print(f"  Cached (pass 1):  {len(eligible) - len(da_leggere):6d}")
        print(f"  New to process:   {len(da_leggere):6d}")
        print(f"  Est. chunks:      {st['richieste']:6d}")
        print(f"  Est. consolidate: {unione['unioni']:6d}")
        print(f"  Est. input tok:   {st['est_input_tokens'] + unione['est_input_tokens']:,}")
        print(f"  Est. output tok:  {st['est_output_tokens'] + unione['est_output_tokens']:,}")
        print(f"  Provider:         {args.provider}")
        print(f"  Model:            {SONNET_MODEL}")
        if args.batch_api:
            print("  Mode:             Anthropic Batch API (50% discount)")
            print(
                f"  Est. batch cost:  ${st['est_cost_usd_batch']:.2f} "
                f"(pass 1, vs ${st['est_cost_usd_sync']:.2f} sync)"
            )
        else:
            print(f"  Est. sync cost:   ${st['est_cost_usd_sync']:.2f} (pass 1)")
        print(f"  Est. direct cost: ${unione['est_cost_usd']:.2f} (consolidation, full price)")
        print(f"  Est. total cost:  ${primo_passo + unione['est_cost_usd']:.2f}")
        print(f"{'=' * 65}")
        return

    if args.batch:

        data = SBKData()
        facts = run_batch(
            all_docs,
            data=data,
            workers=args.workers,
            force=args.force,
            min_chars=args.min_chars,
            batch_size=args.batch_size,
        )
        save_facts(facts)


        from sbk_config import mark_last_run, save_input_checkpoint

        _deep_input_dirs = [
            DATA_ROOT / "plaud" / "raw",
            DATA_ROOT / "tactiq" / "raw",
            DATA_ROOT / "attio" / "transcripts",
            DATA_ROOT / "attio",
            EMAILS_DIR,
            DATA_ROOT / "slack" / "conversations",
            DATA_ROOT / "slack" / "dm",
            DATA_ROOT / "whatsapp" / "chats",
            DATA_ROOT / "chatgpt" / "processed",
            DATA_ROOT / "notion" / "processed",
            DATA_ROOT / "gdrive" / "processed",
            VOICE_MEMOS_TRANSCRIPTS_DIR,
        ]
        save_input_checkpoint("l3-deep-extract", _deep_input_dirs)
        mark_last_run("l3-deep-extract")
    elif args.batch_api:
        data = SBKData()
        facts = run_batch_api(
            all_docs,
            data=data,
            force=args.force,
            min_chars=args.min_chars,
        )
        save_facts(facts)

        from sbk_config import mark_last_run, save_input_checkpoint

        _deep_input_dirs = [
            DATA_ROOT / "plaud" / "raw",
            DATA_ROOT / "tactiq" / "raw",
            DATA_ROOT / "attio" / "transcripts",
            DATA_ROOT / "attio",
            EMAILS_DIR,
            DATA_ROOT / "slack" / "conversations",
            DATA_ROOT / "slack" / "dm",
            DATA_ROOT / "whatsapp" / "chats",
            DATA_ROOT / "chatgpt" / "processed",
            DATA_ROOT / "notion" / "processed",
            DATA_ROOT / "gdrive" / "processed",
            VOICE_MEMOS_TRANSCRIPTS_DIR,
        ]
        save_input_checkpoint("l3-deep-extract", _deep_input_dirs)
        mark_last_run("l3-deep-extract")
    else:
        parser.print_help()
        print(
            "\nUse --batch to run extraction, --batch-api for 50% discount, --dry-run to estimate cost."
        )


def _acquire_lock():
    ""
    if not acquire_pid_lock("deep-extract", logger=log):


        log.warning("deep-extract: lock held by another instance, exit 75")
        sys.exit(75)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-deep-extract", source="l3-deep-extract", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
