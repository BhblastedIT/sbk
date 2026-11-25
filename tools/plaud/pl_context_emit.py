""

























from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


try:
    from tools.plaud.pl_types import (
        Evidence,
        EvidenceDirection,
        EvidenceSource,
    )
except ImportError:  # pragma: no cover
    from pl_types import (  # type: ignore[no-redef]
        Evidence,
        EvidenceDirection,
        EvidenceSource,
    )






from sbk_config import OWNER_FIRST_NAME, OWNER_SPEAKER_LABELS, owner_name_regex  # noqa: E402

# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_NAMES: frozenset[str] = frozenset(OWNER_SPEAKER_LABELS)
# The name used in the "e' <name>" claims about you (pl_resolver reads it too).
OWNER_CLAIM_NAME: str = OWNER_FIRST_NAME or "owner"



# Phrases that identify the owner as the speaker (company references and
# recurring turns of phrase). Load from user config; empty by default.
_OWNER_IDENTITY_PHRASES: tuple[str, ...] = ()



_SELF_INTRO_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (

        r"\b(?:sono|mi chiamo|io sono|io)\s+([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,})?)\b",

        r"\b(?:i am|i'm|this is|my name is)\s+([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,})?)\b",

        r"\b(?:soy|me llamo)\s+([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,})?)\b",
    )
)



_ADDRESSING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (

        r"^([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,})?)\s*[,!]",

        r"\b(?:senti|dimmi|guarda|ascolta|vedi|scusa|dai|listen|hey|look|oye)\s+([A-Za-zÀ-ÿ]{2,})\b",

        r"\bcome\s+(?:dicevi|dici|stavi dicendo)\s+([A-Za-zÀ-ÿ]{2,})\b",

        r"\b(?:parola|tocca)\s+a\s+([A-Za-zÀ-ÿ]{2,})\b",
    )
)


_THIRD_PERSON_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:ho parlato con|ho sentito|ho chiamato|ho chiesto a|dice che|secondo)\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\b(?:talked to|spoke with|asked|according to)\s+([A-Za-zÀ-ÿ]{2,})\b",
    )
)


_ROLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:come|in qualità di|in qualita di|da)\s+(avvocato|commercialista|ingegnere|architetto|medico|ceo|cfo|cto|coo|direttore|responsabile|manager|founder|partner|socio)\b",
        r"\b(?:as a|as the)\s+(lawyer|accountant|engineer|architect|doctor|ceo|cfo|cto|coo|director|manager|founder|partner)\b",
    )
)


_NOT_NAMES: frozenset[str] = frozenset(
    {




        "di",
        "de",
        "da",
        "dei",
        "delle",
        "degli",
        "io",
        "tu",
        "lui",
        "lei",
        "noi",
        "voi",
        "loro",
        "mi",
        "ti",
        "ci",
        "vi",
        "si",
        "ne",
        "ed",
        "ad",
        "in",
        "su",
        "tra",
        "fra",
        "gli",
        "se",
        "ma",
        "chi",
        "cui",
        "ho",
        "hai",
        "the",
        "of",
        "to",
        "and",
        "or",
        "is",
        "it",
        "on",
        "at",
        "we",
        "you",
        "they",
        "che",
        "il",
        "lo",
        "la",
        "le",
        "un",
        "una",
        "per",
        "con",
        "non",
        "dal",
        "del",
        "nel",
        "sul",
        "alla",
        "della",
        "nella",
        "sulla",
        "questo",
        "quella",
        "anche",
        "come",
        "cosa",
        "sono",
        "bene",
        "beh",
        "ciao",
        "poi",
        "ora",
        "no",
        "ok",
        "va",
        "eh",
        "ah",
        "but",
        "for",
        "not",
        "this",
        "that",
        "with",
        "from",
        "have",
        "has",
        "what",
        "all",
        "can",
        "will",
        "just",
        "here",
        "there",
        "then",
        "well",
        "yes",
        "yeah",
        "sure",
        "right",
        "good",
        "great",
        "thanks",
        "thank",
        "sorry",
        "please",
        "let",
        "see",
        "know",
        "think",
        "say",
        "said",
        "one",
        "two",
        "tre",
        "due",
        "molto",
        "tanto",
        "fatto",
        "dopo",
        "prima",
        "qui",
        "ecco",
        "vero",
        "certo",
        "niente",
        "tutto",
        "qualcosa",
        "allora",
        "quindi",
        "comunque",
        "praticamente",
        "davvero",
        "senza",
        "perche",
        "perché",
        "ancora",
        "sempre",
        "ogni",
        "solo",


        "sì",
        "vabbè",
        "vabbe",
        "boh",
        "mah",
        "cioè",
        "cioe",
        "ehm",
        "uhm",
        "aaah",
        "oh",
        "uh",
        "mmm",
        "insomma",
        "magari",
        "appunto",
        "esatto",
        "esattamente",
        "assolutamente",
        "ovviamente",
        "diciamo",
        "guarda",
        "senti",
        "aspetta",
        "scusa",
        "figurati",
        "dunque",


        "nato",
        "stato",
        "andato",
        "detto",
        "visto",
        "dato",
        "messo",
        "preso",
        "parlato",
        "sentito",
        "chiamato",
        "pensato",
        "trovato",
        "arrivato",
        "tornato",
        "guardato",
        "provato",
        "cambiato",
        "capito",
        "finito",
        "successo",
        "chiesto",
        "risposto",
        "deciso",
        "iniziato",



        "messi",
        "presi",
        "scelti",
        "spesi",
        "visti",
        "fatti",
        "detti",
        "presa",
        "messa",
        "fatta",
        "vista",
        "andata",
        "tornata",
    }
)







def _is_plausible_name(token: str, name_pool: frozenset[str] | None = None) -> bool:
    ""






    if not token or len(token) < 2:
        return False
    low = token.lower().strip()

    if not re.match(r"^[A-Za-zÀ-ÿ][-'A-Za-zÀ-ÿ]*$", token):
        return False




    if low in _NOT_NAMES:
        return False
    if name_pool is not None:

        return low in name_pool
    return True


def _extract_speaker_id(seg: dict[str, Any]) -> str:
    ""
    return seg.get("original_speaker") or seg.get("speaker") or ""


def _trunc_quote(text: str, max_len: int = 120) -> str:
    ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."







def extract_addressing(
    segments: list[dict[str, Any]],
    name_pool: frozenset[str] | None = None,
) -> list[Evidence]:
    ""









    evidences: list[Evidence] = []
    for i, seg in enumerate(segments):
        content = seg.get("content", "")
        speaker_id = _extract_speaker_id(seg)
        if not content or not speaker_id:
            continue

        for pat in _ADDRESSING_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            name = m.group(1).strip()
            if not _is_plausible_name(name, name_pool):
                continue



            target_id = ""
            for j in range(i + 1, min(i + 5, len(segments))):
                next_id = _extract_speaker_id(segments[j])
                if next_id and next_id != speaker_id:
                    target_id = next_id
                    break

            ev = Evidence(
                source=EvidenceSource.TRANSCRIPT_CONTEXT,
                claim=f"e' {name}",
                weight=0.80,
                direction=EvidenceDirection.SUPPORT,
                quote=_trunc_quote(content),
                meta={
                    "signal": "S1_addressing",
                    "addressed_name": name.lower(),
                    "addressing_speaker_id": speaker_id,
                    "target_speaker_id": target_id,
                    "segment_index": i,
                },
            )
            evidences.append(ev)
    return evidences







def extract_self_introduction(
    segments: list[dict[str, Any]],
    name_pool: frozenset[str] | None = None,
) -> list[Evidence]:
    ""


    evidences: list[Evidence] = []
    for i, seg in enumerate(segments):
        content = seg.get("content", "")
        speaker_id = _extract_speaker_id(seg)
        if not content or not speaker_id:
            continue

        for pat in _SELF_INTRO_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            name = m.group(1).strip()
            if not _is_plausible_name(name, name_pool):
                continue

            ev = Evidence(
                source=EvidenceSource.TRANSCRIPT_CONTEXT,
                claim=f"e' {name}",
                weight=0.95,
                direction=EvidenceDirection.SUPPORT,
                quote=_trunc_quote(content),
                meta={
                    "signal": "S2_self_intro",
                    "self_name": name.lower(),
                    "speaker_id": speaker_id,
                    "segment_index": i,
                },
            )
            evidences.append(ev)
    return evidences







def extract_owner_clues(
    segments: list[dict[str, Any]],
) -> list[Evidence]:
    ""







    evidences: list[Evidence] = []
    for i, seg in enumerate(segments):
        content = seg.get("content", "")
        speaker_id = _extract_speaker_id(seg)
        if not content or not speaker_id:
            continue

        text_lower = content.lower()


        for pat in _SELF_INTRO_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            name = m.group(1).strip().lower()


            name_tokens = name.split()
            if any(t in OWNER_NAMES for t in name_tokens) or name in OWNER_NAMES:
                ev = Evidence(
                    source=EvidenceSource.TRANSCRIPT_CONTEXT,
                    claim=f"e' {OWNER_CLAIM_NAME}",
                    weight=0.95,
                    direction=EvidenceDirection.SUPPORT,
                    quote=_trunc_quote(content),
                    meta={
                        "signal": "S2_owner_self_intro",
                        "speaker_id": speaker_id,
                        "segment_index": i,
                    },
                )
                evidences.append(ev)


        for phrase in _OWNER_IDENTITY_PHRASES:
            if phrase in text_lower:
                ev = Evidence(
                    source=EvidenceSource.TRANSCRIPT_CONTEXT,
                    claim=f"e' {OWNER_CLAIM_NAME}",
                    weight=0.70,
                    direction=EvidenceDirection.SUPPORT,
                    quote=_trunc_quote(content),
                    meta={
                        "signal": "S2_owner_phrase",
                        "phrase": phrase,
                        "speaker_id": speaker_id,
                        "segment_index": i,
                    },
                )
                evidences.append(ev)
                break



        if re.search(
            rf"\b{owner_name_regex()}\b",
            text_lower,
        ):

            if not re.search(rf"\b(?:io|sono|mi chiamo|i'm|this is)\s+{owner_name_regex()}\b", text_lower):
                ev = Evidence(
                    source=EvidenceSource.TRANSCRIPT_CONTEXT,
                    claim=f"NON e' {OWNER_CLAIM_NAME}",




                    weight=0.05,
                    direction=EvidenceDirection.CONTRADICT,
                    quote=_trunc_quote(content),
                    meta={
                        "signal": "S2_addresses_owner",
                        "speaker_id": speaker_id,
                        "segment_index": i,
                        "contradict_identity": OWNER_CLAIM_NAME,
                    },
                )
                evidences.append(ev)

    return evidences







def extract_third_person_mentions(
    segments: list[dict[str, Any]],
    name_pool: frozenset[str] | None = None,
) -> list[Evidence]:
    ""




    evidences: list[Evidence] = []
    for i, seg in enumerate(segments):
        content = seg.get("content", "")
        speaker_id = _extract_speaker_id(seg)
        if not content or not speaker_id:
            continue

        for pat in _THIRD_PERSON_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            name = m.group(1).strip()
            if not _is_plausible_name(name, name_pool):
                continue

            ev = Evidence(
                source=EvidenceSource.TRANSCRIPT_CONTEXT,
                claim=f"nel meeting si menziona {name}",
                weight=0.35,
                direction=EvidenceDirection.SUPPORT,
                quote=_trunc_quote(content),
                meta={
                    "signal": "S3_third_person",
                    "mentioned_name": name.lower(),
                    "mentioning_speaker_id": speaker_id,
                    "segment_index": i,
                },
            )
            evidences.append(ev)
    return evidences







def extract_role_clues(
    segments: list[dict[str, Any]],
) -> list[Evidence]:
    ""



    evidences: list[Evidence] = []
    for i, seg in enumerate(segments):
        content = seg.get("content", "")
        speaker_id = _extract_speaker_id(seg)
        if not content or not speaker_id:
            continue

        for pat in _ROLE_PATTERNS:
            m = pat.search(content)
            if not m:
                continue
            role = m.group(1).strip().lower()

            ev = Evidence(
                source=EvidenceSource.TRANSCRIPT_CONTEXT,
                claim=f"ha ruolo {role}",
                weight=0.50,
                direction=EvidenceDirection.SUPPORT,
                quote=_trunc_quote(content),
                meta={
                    "signal": "S4_role",
                    "role": role,
                    "speaker_id": speaker_id,
                    "segment_index": i,
                },
            )
            evidences.append(ev)
    return evidences







def emit_all(
    segments: list[dict[str, Any]],
    name_pool: frozenset[str] | None = None,
) -> list[Evidence]:
    ""





    evidences: list[Evidence] = []
    evidences.extend(extract_addressing(segments, name_pool))
    evidences.extend(extract_self_introduction(segments, name_pool))
    evidences.extend(extract_owner_clues(segments))
    evidences.extend(extract_third_person_mentions(segments, name_pool))
    evidences.extend(extract_role_clues(segments))
    return evidences







def group_by_speaker(evidences: list[Evidence]) -> dict[str, list[Evidence]]:
    ""









    grouped: dict[str, list[Evidence]] = {}
    for ev in evidences:
        signal = ev.meta.get("signal", "")
        sid = ""

        if signal.startswith("S1_"):

            sid = ev.meta.get("target_speaker_id", "")
        elif signal.startswith("S2_"):

            sid = ev.meta.get("speaker_id", "")
        elif signal.startswith("S3_"):



            sid = ev.meta.get("mentioning_speaker_id", "")
        elif signal.startswith("S4_"):

            sid = ev.meta.get("speaker_id", "")

        if sid:
            grouped.setdefault(sid, []).append(ev)

    return grouped
