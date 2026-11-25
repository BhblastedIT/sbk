#!/usr/bin/env python3
""









from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_SPEAKER_TURN_RE = re.compile(r"^[A-Z][a-zA-Zà-ú\s\-'\.]{1,40}:", re.MULTILINE)


@dataclass
class Chunk:
    ""

    text: str
    chunk_idx: int
    total_chunks: int
    start_char: int
    end_char: int


def chunk_document_semantic(
    text: str,
    max_chars: int = 25_000,
    overlap_chars: int = 2_000,
) -> list[Chunk]:
    ""


















    if not text or len(text) <= max_chars:
        return [Chunk(text=text, chunk_idx=0, total_chunks=1, start_char=0, end_char=len(text))]

    chunks: list[Chunk] = []
    pos = 0
    text_len = len(text)

    while pos < text_len:
        end = min(pos + max_chars, text_len)

        if end < text_len:

            search_start = pos + int(max_chars * 0.8)
            split_at = _find_best_split(text, search_start, end)
            end = split_at

        chunk_text = text[pos:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                chunk_idx=len(chunks),
                total_chunks=0,
                start_char=pos,
                end_char=end,
            )
        )


        if end >= text_len:
            break


        pos = end - overlap_chars


    total = len(chunks)
    for c in chunks:
        c.total_chunks = total

    return chunks


def _find_best_split(text: str, search_start: int, search_end: int) -> int:
    ""



    region = text[search_start:search_end]


    matches = list(_SPEAKER_TURN_RE.finditer(region))
    if matches:
        return search_start + matches[-1].start()


    last_para = region.rfind("\n\n")
    if last_para >= 0:
        return search_start + last_para + 2


    last_sentence = _find_last_sentence_end(region)
    if last_sentence >= 0:
        return search_start + last_sentence


    last_nl = region.rfind("\n")
    if last_nl >= 0:
        return search_start + last_nl + 1


    return search_end


def _find_last_sentence_end(text: str) -> int:
    ""

    best = -1
    for m in re.finditer(r'[.!?]["\')\]]?\s', text):
        best = m.end()
    return best





def merge_extraction_results(chunk_results: list[dict]) -> dict:
    ""









    merged = {
        "decisions": [],
        "action_items": [],
        "key_topics": [],
        "entities_mentioned": [],
        "financial_mentions": [],
    }

    seen_decisions: set[str] = set()
    seen_actions: set[str] = set()
    seen_entities: set[str] = set()
    seen_topics: set[str] = set()
    seen_financial: set[str] = set()

    for result in chunk_results:
        if not result:
            continue


        for d in result.get("decisions", []):
            text = str(d.get("text", "")).strip().lower()
            key = _fuzzy_key(text)
            if key and key not in seen_decisions:
                seen_decisions.add(key)
                merged["decisions"].append(d)


        for a in result.get("action_items", []):
            text = str(a.get("text", "")).strip().lower()
            key = _fuzzy_key(text)
            if key and key not in seen_actions:
                seen_actions.add(key)
                merged["action_items"].append(a)


        for t in result.get("key_topics", []):
            t_lower = str(t).strip().lower()
            if t_lower and t_lower not in seen_topics:
                seen_topics.add(t_lower)
                merged["key_topics"].append(t)


        for e in result.get("entities_mentioned", []):
            name = str(e.get("name", "")).strip().lower()
            etype = str(e.get("type", "")).strip().lower()
            key = f"{name}|{etype}"
            if name and key not in seen_entities:
                seen_entities.add(key)
                merged["entities_mentioned"].append(e)


        for f in result.get("financial_mentions", []):
            amount = str(f.get("amount", "")).strip()
            entity = str(f.get("entity", "")).strip().lower()
            ftype = str(f.get("type", "")).strip().lower()
            key = f"{amount}|{entity}|{ftype}"
            if amount and key not in seen_financial:
                seen_financial.add(key)
                merged["financial_mentions"].append(f)

    return merged


def merge_relationship_results(chunk_results: list[dict]) -> dict:
    ""









    merged = {
        "relationship_facts": [],
        "personal_details": [],
        "introductions": [],
        "needs_and_interests": [],
        "financial_facts": [],
        "deal_terms": [],
    }

    seen_rel: set[str] = set()
    seen_detail: set[str] = set()
    seen_intro: set[str] = set()
    seen_need: set[str] = set()
    seen_financial: set[str] = set()
    seen_deal: set[str] = set()

    for result in chunk_results:
        if not result:
            continue


        for rf in result.get("relationship_facts", []):
            s = str(rf.get("subject", "")).strip().lower()
            p = str(rf.get("predicate", "")).strip().upper()
            o = str(rf.get("object", "")).strip().lower()
            key = _hash_key(f"{s}|{p}|{o}")
            if key not in seen_rel:
                seen_rel.add(key)
                merged["relationship_facts"].append(rf)


        for pd_item in result.get("personal_details", []):
            person = str(pd_item.get("person", "")).strip().lower()
            dtype = str(pd_item.get("detail_type", "")).strip().lower()
            value = str(pd_item.get("value", "")).strip().lower()
            key = _hash_key(f"{person}|{dtype}|{value}")
            if key not in seen_detail:
                seen_detail.add(key)
                merged["personal_details"].append(pd_item)


        for intro in result.get("introductions", []):
            who = str(intro.get("introduced", "")).strip().lower()
            by = str(intro.get("introduced_by", "")).strip().lower()
            key = _hash_key(f"{who}|{by}")
            if key not in seen_intro:
                seen_intro.add(key)
                merged["introductions"].append(intro)


        for need in result.get("needs_and_interests", []):
            person = str(need.get("person", "")).strip().lower()
            ntype = str(need.get("need_type", "")).strip().lower()
            desc = str(need.get("description", "")).strip().lower()[:50]
            key = _hash_key(f"{person}|{ntype}|{desc}")
            if key not in seen_need:
                seen_need.add(key)
                merged["needs_and_interests"].append(need)


        for ff in result.get("financial_facts", []):
            entity = str(ff.get("person_or_entity", "")).strip().lower()
            ftype = str(ff.get("fact_type", "")).strip().lower()
            value = str(ff.get("value", "")).strip()
            key = _hash_key(f"{entity}|{ftype}|{value}")
            if key not in seen_financial:
                seen_financial.add(key)
                merged["financial_facts"].append(ff)


        for dt in result.get("deal_terms", []):
            parties = "|".join(sorted(str(p).lower() for p in (dt.get("parties") or [])))
            ttype = str(dt.get("term_type", "")).strip().lower()
            desc = str(dt.get("description", "")).strip().lower()[:50]
            key = _hash_key(f"{parties}|{ttype}|{desc}")
            if key not in seen_deal:
                seen_deal.add(key)
                merged["deal_terms"].append(dt)

    return merged


def _fuzzy_key(text: str, min_len: int = 10) -> str:
    ""
    if not text or len(text) < min_len:
        return text

    normalized = re.sub(r"\s+", " ", text)[:60]
    return normalized


def _hash_key(raw: str) -> str:
    ""
    return hashlib.md5(raw.encode()).hexdigest()[:12]
