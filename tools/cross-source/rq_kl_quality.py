""













from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import owner_name_regex  # noqa: E402

log = logging.getLogger("rq.kl_quality")

# Your name in a fact value (sbk.config.json owner / own_names); never matches when unset.
_OWNER_IN_TEXT = re.compile(rf"\b{owner_name_regex()}\b", re.IGNORECASE)






INTIMATE_PATTERNS: dict[str, float] = {
    r"matrimonio|nozze|sposa|sposo": 0.50,
    r"testimone|cerimoniere|padrino|madrina": 0.55,
    r"battesimo|comunione|cresima": 0.40,
    r"compleanno|festa|capodanno\s+insieme": 0.30,
    r"vacanza\s+insieme|viaggio\s+insieme": 0.35,
    r"cena|pranzo|aperitivo": 0.20,
}



BUSINESS_LEADERSHIP_PATTERNS: dict[str, float] = {
    r"\bamministratore\b|\bCEO\b|\bAD\b|\bCTO\b|\bCFO\b|\bCOO\b": 0.30,

    r"\bsocio\b|\bquota\b": 0.35,
    r"co-fondatore|co-founder|\bfondatore\b|\bfounder\b": 0.40,
    r"\bholding\b|\bcontrollata\b|\bpartecipazione\b": 0.30,
}



_EQUITY_PATTERN = re.compile(r"\bequity\b", re.IGNORECASE)
_EQUITY_EXCLUSIONS = re.compile(r"private equity|equity\s+firm|equity\s+fund", re.IGNORECASE)
_PARTNER_PATTERN = re.compile(r"\bpartner\b", re.IGNORECASE)
_PARTNER_EXCLUSIONS = re.compile(
    r"managing partner|general partner|limited partner|venture partner|partner\s+at\b",
    re.IGNORECASE,
)


PROFESSIONAL_TRUSTED: dict[str, float] = {
    r"\bmedico\b|\bdottore\b|\bdott\.\b|\bdr\.\b": 0.25,
    r"\bavvocato\b|\bnotaio\b": 0.20,
    r"\bcommercialista\b": 0.15,
}


_PERSONAL_DETAIL_TIERS = [
    (1, 0.10),
    (5, 0.25),
    (10, 0.40),
    (20, 0.55),
]




_RELATIONSHIP_OWNER_TIERS = [
    (1, 0.10),
    (3, 0.25),
    (5, 0.40),
]



_STRONG_OWNER_ATTRS = frozenset(
    {
        "relationship.partner_of",
        "relationship.family_of",
        "relationship.friend_of",
        "relationship.advisor_to",
        "relationship.reports_to",
        "relationship.works_with",
        "relationship.with_owner",
        "relationship.how_we_met",
        "relationship.contributions",
    }
)




_WEAK_OWNER_ATTRS = frozenset(
    {
        "relationship.interested_in",
        "relationship.introduced_to",
        "relationship.introduced_by",
        "relationship.looking_for",
        "relationship.commitment",
        "relationship.working_on",
        "relationship.struggling_with",
    }
)


_BUSINESS_PRIMARY_ATTRS = frozenset(
    {
        "employment.current_role",
        "employment.role",
        "identity.role",
        "identity.bio",
        "deep.commitment.hire_commitment",
    }
)



_BUSINESS_SECONDARY_ATTRS = frozenset(
    {
        "relationship.background",
        "relationship.working_on",
        "relationship.context",
        "relationship.how_we_met",
        "relationship.contributions",
    }
)


_PROFESSIONAL_ATTRS_PREFIXES = ("employment.", "identity.")


def _tier_value(count: int, tiers: list[tuple[int, float]]) -> float:
    ""
    result = 0.0
    for threshold, value in tiers:
        if count >= threshold:
            result = value
        else:
            break
    return result


def _check_equity_partner(attr: str, val: str) -> list[tuple[str, float]]:
    ""








    hits: list[tuple[str, float]] = []

    if _EQUITY_PATTERN.search(val):
        if not _EQUITY_EXCLUSIONS.search(val):
            hits.append(("business:equity_ownership", 0.35))

    if _PARTNER_PATTERN.search(val):
        if not _PARTNER_EXCLUSIONS.search(val):


            if attr.startswith(("employment.", "identity.", "deep.")):
                hits.append(("business:partner_role", 0.30))
            elif attr.startswith("relationship.") and _OWNER_IN_TEXT.search(val):
                hits.append(("business:partner_of_owner", 0.35))

    return hits


def compute_kl_depth(entity_facts: list[dict], person_id: str = "") -> dict:
    ""















    if not entity_facts:
        return {
            "depth": 0.0,
            "confidence": 0.0,
            "signals": [],
            "fact_count": 0,
            "source_count": 0,
        }


    seen_facts: set[tuple[str, str]] = set()
    unique_facts: list[dict] = []
    for fact in entity_facts:
        key = (str(fact.get("attribute", "")), str(fact.get("value", "")))
        if key not in seen_facts:
            seen_facts.add(key)
            unique_facts.append(fact)


    sources: set[str] = set()
    categories: set[str] = set()
    personal_detail_count = 0
    relationship_owner_count = 0
    all_signals: list[tuple[str, float]] = []

    for fact in unique_facts:
        attr = str(fact.get("attribute", ""))
        val = str(fact.get("value", ""))


        src = fact.get("source", {})
        if isinstance(src, dict):
            st = src.get("source_type", "")
            if st:
                sources.add(st)
        elif isinstance(src, list):
            for s in src:
                if isinstance(s, dict):
                    st = s.get("source_type", "")
                    if st:
                        sources.add(st)


        cat = attr.split(".")[0] if "." in attr else attr
        if cat:
            categories.add(cat)


        if attr.startswith("personal."):
            personal_detail_count += 1



        if attr in _STRONG_OWNER_ATTRS and _OWNER_IN_TEXT.search(val):
            relationship_owner_count += 1


        for pattern, strength in INTIMATE_PATTERNS.items():
            if re.search(pattern, val, re.IGNORECASE):
                all_signals.append((f"intimate:{pattern[:30]}", strength))


        if attr in _BUSINESS_PRIMARY_ATTRS or attr.startswith(
            ("employment.", "identity.", "deep.commitment")
        ):
            for pattern, strength in BUSINESS_LEADERSHIP_PATTERNS.items():
                if re.search(pattern, val, re.IGNORECASE):
                    all_signals.append((f"business:{pattern[:30]}", strength))


        if attr in _BUSINESS_SECONDARY_ATTRS:
            for pattern, strength in BUSINESS_LEADERSHIP_PATTERNS.items():
                if re.search(pattern, val, re.IGNORECASE):
                    all_signals.append((f"business_ctx:{pattern[:30]}", strength * 0.5))

            for pattern, strength in INTIMATE_PATTERNS.items():
                if re.search(pattern, val, re.IGNORECASE):
                    all_signals.append((f"intimate:{pattern[:30]}", strength))


        ep_hits = _check_equity_partner(attr, val)
        all_signals.extend(ep_hits)


        if attr.startswith(_PROFESSIONAL_ATTRS_PREFIXES):
            for pattern, strength in PROFESSIONAL_TRUSTED.items():
                if re.search(pattern, val, re.IGNORECASE):
                    all_signals.append((f"professional:{pattern[:30]}", strength))


    pd_depth = _tier_value(personal_detail_count, _PERSONAL_DETAIL_TIERS)
    rs_depth = _tier_value(relationship_owner_count, _RELATIONSHIP_OWNER_TIERS)

    if pd_depth > 0:
        all_signals.append((f"personal_details:{personal_detail_count}", pd_depth))
    if rs_depth > 0:
        all_signals.append((f"relationship_owner_facts:{relationship_owner_count}", rs_depth))


    source_count = len(sources)
    if source_count >= 3:
        all_signals.append((f"multi_source:{source_count}", 0.10))
    if source_count >= 5:
        all_signals.append((f"rich_source:{source_count}", 0.05))


    if not all_signals:
        depth = 0.0
    else:
        strengths = [s[1] for s in all_signals]
        peak = max(strengths)



        others = list(strengths)
        others.remove(peak)
        if others:
            avg_others = sum(others) / len(others)
        else:
            avg_others = 0.0


        depth = peak + 0.20 * avg_others


    depth = min(0.70, depth)


    unique_signal_types = len({s[0].split(":")[0] for s in all_signals})
    fact_count = len(unique_facts)

    if not all_signals:
        confidence = 0.0
    elif len(all_signals) == 1:
        confidence = 0.30
    elif len(all_signals) <= 3:
        confidence = 0.50
    elif len(all_signals) <= 6:
        confidence = 0.70
    else:
        confidence = 0.85


    if unique_signal_types >= 2:
        confidence = min(1.0, confidence + 0.10)
    if unique_signal_types >= 3:
        confidence = min(1.0, confidence + 0.05)


    if source_count >= 3:
        confidence = min(1.0, confidence + 0.10)


    if fact_count >= 50:
        confidence = min(1.0, confidence + 0.05)
    if fact_count >= 100:
        confidence = min(1.0, confidence + 0.05)


    seen_sigs: set[str] = set()
    output_signals: list[str] = []
    for desc, strength in all_signals:
        if desc not in seen_sigs:
            seen_sigs.add(desc)
            output_signals.append(f"{desc}={strength:.2f}")

    result = {
        "depth": round(depth, 4),
        "confidence": round(confidence, 4),
        "signals": output_signals,
        "fact_count": fact_count,
        "source_count": source_count,
    }

    if person_id:
        log.debug(
            "KL depth for %s: depth=%.3f, confidence=%.3f, signals=%d, facts=%d, sources=%d",
            person_id,
            depth,
            confidence,
            len(output_signals),
            fact_count,
            source_count,
        )

    return result




if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python rq_kl_quality.py <entity_file.json> [entity_file2.json ...]")
        print("   or: python rq_kl_quality.py --search <name_fragment>")
        sys.exit(1)

    if sys.argv[1] == "--search":
        import os

        search_term = " ".join(sys.argv[2:]).lower()
        kl_dir = Path("~/.sbk-data/knowledge/entities/person").expanduser()
        if not kl_dir.exists():
            print(f"KL directory not found: {kl_dir}")
            sys.exit(1)

        for fname in sorted(os.listdir(kl_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = kl_dir / fname
            try:
                with open(fpath, encoding="utf-8") as f:
                    ent = json.load(f)
                facts = ent.get("facts", [])
                for fact in facts:
                    if fact.get("attribute") == "identity.name":
                        name = str(fact.get("value", "")).lower()
                        if search_term in name:
                            result = compute_kl_depth(facts, fname)
                            print(
                                f"\n{fname}: {fact.get('value', '')} "
                                f"({result['fact_count']} facts, "
                                f"{result['source_count']} sources)"
                            )
                            print(
                                f"  depth={result['depth']:.3f}, confidence={result['confidence']:.3f}"
                            )
                            for sig in result["signals"]:
                                print(f"  - {sig}")
                            break
            except (json.JSONDecodeError, OSError):
                continue
    else:
        for fpath in sys.argv[1:]:
            try:
                with open(fpath, encoding="utf-8") as f:
                    ent = json.load(f)
                facts = ent.get("facts", [])
                result = compute_kl_depth(facts, fpath)
                print(f"\n{fpath} ({result['fact_count']} facts, {result['source_count']} sources)")
                print(f"  depth={result['depth']:.3f}, confidence={result['confidence']:.3f}")
                for sig in result["signals"]:
                    print(f"  - {sig}")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Error reading {fpath}: {exc}")
