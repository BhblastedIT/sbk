""

































from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from math import exp
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))



try:
    from tools.plaud.pl_types import (
        Candidate,
        Evidence,
        EvidenceDirection,
        EvidenceSource,
    )
except ImportError:  # pragma: no cover - fallback for local execution
    from pl_types import (  # type: ignore[no-redef]
        Candidate,
        Evidence,
        EvidenceDirection,
        EvidenceSource,
    )






CAT_GENERIC = "GENERIC"
CAT_SPECIFIC = "SPECIFIC"
CAT_UNIQUE = "UNIQUE"


CATEGORY_WEIGHT: dict[str, float] = {
    CAT_GENERIC: 0.45,
    CAT_SPECIFIC: 1.15,
    CAT_UNIQUE: 2.30,
}



PRIOR_LOG_ODDS = -1.10



MIN_FACTS_FOR_STRONG = 2
SINGLE_FACT_CAP = 0.45


_STOPWORDS = {
    "the",
    "of",
    "and",
    "a",
    "an",
    "for",
    "to",
    "in",
    "on",
    "at",
    "inc",
    "llc",
    "ltd",
    "spa",
    "srl",
    "srls",
    "sa",
    "bv",
    "gmbh",
    "co",
    "group",
    "holding",
    "company",
    "corp",
    "corporation",
    "bank",
    "team",
    "il",
    "lo",
    "la",
    "le",
    "di",
    "da",
    "e",
    "el",
    "los",
    "las",
    "de",
    "del",
}






class DictNameIndex:
    ""







    def __init__(self, mapping: dict[str, Iterable[str]]):
        self._map: dict[str, list[str]] = {_norm(k): list(v) for k, v in mapping.items()}

    def lookup(self, name: str) -> list[str]:
        key = _norm(name)
        if not key:
            return []
        exact = self._map.get(key)
        if exact:
            return list(exact)
        first = key.split(" ", 1)[0]
        if first and first != key:
            return list(self._map.get(first, []))
        return []


def _lookup_ids(name_index: Any, mention: str) -> list[str]:
    ""



    if name_index is None:
        return []
    if hasattr(name_index, "lookup"):
        return list(name_index.lookup(mention))
    if isinstance(name_index, dict):
        return DictNameIndex(name_index).lookup(mention)
    raise TypeError("name_index must have .lookup(name) or be a dict name->[entity_id]")






_NON_WORD = re.compile(r"[^0-9a-zàèéìòóùáíúñü]+", re.IGNORECASE)


def _norm(text: str | None) -> str:
    ""
    if not text:
        return ""
    lowered = _NON_WORD.sub(" ", str(text).lower())
    return " ".join(lowered.split())


def _tokens(text: str | None, *, drop_stopwords: bool = False) -> set[str]:
    ""

    out: set[str] = set()
    for tok in _norm(text).split():
        if len(tok) < 2:
            continue
        if drop_stopwords and tok in _STOPWORDS:
            continue
        out.add(tok)
    return out


def _content_overlap(a: str | None, b: str | None) -> set[str]:
    ""
    return _tokens(a, drop_stopwords=True) & _tokens(b, drop_stopwords=True)







def _default_kb_dir() -> Path:
    ""

    try:
        from sbk_config import KNOWLEDGE_ENTITIES_DIR

        return Path(KNOWLEDGE_ENTITIES_DIR) / "person"
    except Exception:  # pragma: no cover - fixed fallback path
        return Path.home() / ".sbk-data" / "knowledge" / "entities" / "person"


def load_profile(entity_id: str, kb_dir: Path | None = None) -> dict[str, Any] | None:
    ""
    base = Path(kb_dir) if kb_dir is not None else _default_kb_dir()
    path = base / f"{entity_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _valid_facts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    ""
    out = []
    for fact in profile.get("facts", []):
        if fact.get("valid_to") is not None:
            continue
        if fact.get("expired_at") is not None:
            continue
        if fact.get("superseded_by") is not None:
            continue
        out.append(fact)
    return out


def _facts_by_attr(profile: dict[str, Any], attribute: str) -> list[dict[str, Any]]:
    return [f for f in _valid_facts(profile) if f.get("attribute") == attribute]


def _canonical_name(profile: dict[str, Any]) -> str:
    name = profile.get("canonical_name")
    if name:
        return str(name)
    idn = _facts_by_attr(profile, "identity.name")
    return str(idn[0]["value"]) if idn else ""







def _mk_evidence(
    *,
    claim: str,
    category: str,
    kind: str,
    quote: str,
    entity_id: str,
    attribute: str,
) -> Evidence:
    ""
    return Evidence(
        source=EvidenceSource.KNOWLEDGE_BASE,
        claim=claim,
        weight=CATEGORY_WEIGHT[category],
        direction=EvidenceDirection.SUPPORT,
        entity_id=entity_id,
        quote=quote,
        meta={"category": category, "kind": kind, "attribute": attribute},
    )


def _name_evidence(mention: str, profile: dict[str, Any], entity_id: str) -> Evidence | None:
    ""


    canonical = _canonical_name(profile)
    m_tokens = _tokens(mention)
    c_tokens = _tokens(canonical)
    if not m_tokens or not c_tokens:
        return None
    shared = m_tokens & c_tokens
    if not shared:
        return None
    full_match = len(m_tokens) >= 2 and m_tokens.issubset(c_tokens)
    category = CAT_SPECIFIC if full_match else CAT_GENERIC
    return _mk_evidence(
        claim=f"is {canonical}",
        category=category,
        kind="name",
        quote=f"identity.name = {canonical}",
        entity_id=entity_id,
        attribute="identity.name",
    )


def _company_evidence(
    context: dict[str, Any], profile: dict[str, Any], entity_id: str
) -> Evidence | None:
    ""

    ctx_company = context.get("company")
    if not ctx_company:
        return None
    for attr in ("crm.company", "relationship.company"):
        for fact in _facts_by_attr(profile, attr):
            value = fact.get("value", "")
            if _content_overlap(ctx_company, value):
                canonical = _canonical_name(profile)
                return _mk_evidence(
                    claim=f"{canonical} works at {value}",
                    category=CAT_SPECIFIC,
                    kind="company",
                    quote=f"{attr} = {value}",
                    entity_id=entity_id,
                    attribute=attr,
                )
    return None


def _role_evidence(
    context: dict[str, Any], profile: dict[str, Any], entity_id: str
) -> Evidence | None:
    ""
    ctx_role = context.get("role")
    if not ctx_role:
        return None
    for fact in _facts_by_attr(profile, "crm.job_title"):
        value = fact.get("value", "")
        if _content_overlap(ctx_role, value):
            return _mk_evidence(
                claim=f"consistent role: {value}",
                category=CAT_SPECIFIC,
                kind="role",
                quote=f"crm.job_title = {value}",
                entity_id=entity_id,
                attribute="crm.job_title",
            )
    return None


def _email_evidence(
    context: dict[str, Any], profile: dict[str, Any], entity_id: str
) -> Evidence | None:
    ""

    ctx_emails = {str(e).strip().lower() for e in context.get("emails", []) if e}
    if not ctx_emails:
        return None
    for fact in _facts_by_attr(profile, "contact.email"):
        value = str(fact.get("value", "")).strip().lower()
        if value and value in ctx_emails:
            return _mk_evidence(
                claim=f"email matches: {value}",
                category=CAT_UNIQUE,
                kind="email",
                quote=f"contact.email = {value}",
                entity_id=entity_id,
                attribute="contact.email",
            )
    return None


def _works_with_evidence(
    context: dict[str, Any], profile: dict[str, Any], entity_id: str
) -> Evidence | None:
    ""

    known = [str(p) for p in context.get("known_people", []) if p]
    if not known:
        return None
    for fact in _facts_by_attr(profile, "relationship.works_with"):
        value = fact.get("value", "")
        for person in known:
            if _content_overlap(person, value):
                return _mk_evidence(
                    claim=f"works with {value}",
                    category=CAT_SPECIFIC,
                    kind="works_with",
                    quote=f"relationship.works_with = {value}",
                    entity_id=entity_id,
                    attribute="relationship.works_with",
                )
    return None


def _topic_evidence(
    context: dict[str, Any], profile: dict[str, Any], entity_id: str
) -> Evidence | None:
    ""

    topics: list[str] = [str(t) for t in context.get("topics", []) if t]
    if context.get("text"):
        topics.append(str(context["text"]))
    if not topics:
        return None
    for attr in ("deep.operational.discussed", "relationship.working_on"):
        for fact in _facts_by_attr(profile, attr):
            value = fact.get("value", "")
            for topic in topics:
                if _content_overlap(topic, value):
                    return _mk_evidence(
                        claim=f"consistent topic: {value}",
                        category=CAT_GENERIC,
                        kind="topic",
                        quote=f"{attr} = {value}",
                        entity_id=entity_id,
                        attribute=attr,
                    )
    return None


_EMITTERS: tuple[Callable[..., Evidence | None], ...] = (
    _company_evidence,
    _role_evidence,
    _email_evidence,
    _works_with_evidence,
    _topic_evidence,
)







def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _fuse_confidence(evidences: list[Evidence]) -> float:
    ""




    if not evidences:
        return 0.0
    log_odds = PRIOR_LOG_ODDS + sum(e.weight for e in evidences)
    conf = _sigmoid(log_odds)
    n_support = sum(1 for e in evidences if e.direction == EvidenceDirection.SUPPORT)
    if n_support < MIN_FACTS_FOR_STRONG:
        conf = min(conf, SINGLE_FACT_CAP)
    return round(conf, 4)


def score_candidate(
    mention: str,
    context: dict[str, Any],
    entity_id: str,
    profile: dict[str, Any],
) -> Candidate:
    ""




    evidences: list[Evidence] = []
    name_ev = _name_evidence(mention, profile, entity_id)
    if name_ev is not None:
        evidences.append(name_ev)
    for emit in _EMITTERS:
        ev = emit(context, profile, entity_id)
        if ev is not None:
            evidences.append(ev)
    confidence = _fuse_confidence(evidences)
    return Candidate(
        name=_canonical_name(profile),
        entity_id=entity_id,
        confidence=confidence,
        evidence=evidences,
    )







def resolve_mention(
    mention: str,
    context: dict[str, Any] | None = None,
    *,
    name_index: Any = None,
    kb_dir: Path | None = None,
    load_profile_fn: Callable[[str], dict[str, Any] | None] | None = None,
    max_candidates: int = 8,
    min_confidence: float = 0.0,
) -> list[Candidate]:
    ""

















    ctx = dict(context or {})
    if name_index is None:
        name_index = _import_pl_name_index()
    entity_ids = _dedup_preserve(_lookup_ids(name_index, mention))
    if not entity_ids:
        return []

    loader = load_profile_fn or (lambda eid: load_profile(eid, kb_dir))
    candidates: list[Candidate] = []
    for eid in entity_ids:
        profile = loader(eid)
        if not profile:
            continue
        cand = score_candidate(mention, ctx, eid, profile)
        if cand.evidence and cand.confidence >= min_confidence:
            candidates.append(cand)

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates[:max_candidates]


def _dedup_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _import_pl_name_index() -> Any:
    ""


    try:
        from tools.plaud import pl_name_index as mod  # type: ignore
    except Exception:
        try:
            import pl_name_index as mod  # type: ignore
        except Exception:
            return None

    for attr in ("get_name_index", "build_name_index", "NAME_INDEX", "name_index"):
        obj = getattr(mod, attr, None)
        if obj is None:
            continue
        if callable(obj):
            try:
                obj = obj()
            except Exception:
                continue
        if hasattr(obj, "lookup") or isinstance(obj, dict):
            return obj
    return None
