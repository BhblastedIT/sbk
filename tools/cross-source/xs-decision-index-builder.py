#!/usr/bin/env python3
""














from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DECISION_INDEX_FILE, DECISIONS_DIR, NLP_DIR

log = logging.getLogger("sbk-decision-index")



DECISIONS_PARQUET = NLP_DIR / "decisions.parquet"
DECISION_FRAMEWORK_MD = DECISIONS_DIR / "decisions.md"





DOMAIN_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "hiring",
        re.compile(
            r"hiring|assunzione|licenziamento|team|dipendent|salary|stipendio"
            r"|onboarding|offboarding|personio|hr|risorse.umane",
            re.IGNORECASE,
        ),
    ),
    (
        "fundraising",
        re.compile(
            r"fundrais|investitor|round|serie|valuation|pre.money|post.money"
            r"|vc|venture|angel|safe|bridge|deck",
            re.IGNORECASE,
        ),
    ),
    (
        "m_and_a",
        re.compile(
            r"acquisizion|m&a|merger|fusione|buyback|mandato|due.diligence|target|deal",
            re.IGNORECASE,
        ),
    ),
    (
        "product",
        re.compile(
            r"prodotto|tech|piattaforma|software|sviluppo|feature|release"
            r"|deploy|bug|sprint|platform",
            re.IGNORECASE,
        ),
    ),
    (
        "strategy",
        re.compile(
            r"strateg|business.dev|crescita|mercato|espansion|partner|accord",
            re.IGNORECASE,
        ),
    ),
    (
        "legal",
        re.compile(
            r"legal|contratto|causa|contenzioso|avvocat|nda|compliance",
            re.IGNORECASE,
        ),
    ),
    (
        "marketing",
        re.compile(
            r"marketing|growth|campagn|advertising|media.buy|cpm|roas|creative|content",
            re.IGNORECASE,
        ),
    ),
    (
        "finance",
        re.compile(
            r"financ|contabilit|bilancio|fiscal|iva|pagament|fattur|cassa|cash.flow",
            re.IGNORECASE,
        ),
    ),
    (
        "real_estate",
        re.compile(
            r"immobil|real.estate|propriet|costruzion|terreno",
            re.IGNORECASE,
        ),
    ),
    (
        "operations",
        re.compile(
            r"operazion|processo|tool|sistema|workflow|automaz",
            re.IGNORECASE,
        ),
    ),
]


def classify_domain(text: str) -> str:
    ""
    for domain, pattern in DOMAIN_PATTERNS:
        if pattern.search(text):
            return domain
    return "other"





_DOMAIN_ALIASES: dict[str, str] = {
    "people/hr": "hiring",
    "people": "hiring",
    "hr": "hiring",
    "fundraising": "fundraising",
    "m&a": "m_and_a",
    "prodotto": "product",
    "product": "product",
    "corporate": "operations",
    "investimenti": "finance",
    "legal": "legal",
    "operazioni": "operations",
    "operations": "operations",
    "strategy": "strategy",
    "marketing": "marketing",
    "real_estate": "real_estate",
    "finance": "finance",
}


def _normalize_domain(raw: str) -> str:
    ""
    key = raw.strip().lower()
    return _DOMAIN_ALIASES.get(key, "other")


def _extract_keywords(text: str, max_kw: int = 5) -> list[str]:
    ""



    stop_words = {
        "di",
        "da",
        "a",
        "in",
        "con",
        "per",
        "il",
        "la",
        "le",
        "lo",
        "i",
        "gli",
        "un",
        "una",
        "del",
        "dei",
        "delle",
        "della",
        "al",
        "alla",
        "alle",
        "che",
        "non",
        "e",
        "o",
        "ma",
        "se",
        "su",
        "tra",
        "fra",
        "piu",
        "come",
        "anche",
        "the",
        "of",
        "to",
        "and",
        "or",
        "for",
        "is",
        "on",
        "at",
        "with",
        "from",
        "by",
        "an",
        "be",
        "as",
        "was",
        "has",
        "had",
        "are",
        "were",
    }
    words = re.findall(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]{3,}", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        if w in stop_words or w in seen:
            continue
        seen.add(w)
        keywords.append(w)
        if len(keywords) >= max_kw:
            break
    return keywords


def parse_decision_framework(md_path: Path) -> list[dict]:
    ""






    if not md_path.exists():
        log.warning(f"Decision framework file not found: {md_path}")
        return []

    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines()


    table_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("| Data") and "Dominio" in stripped and "Decisione" in stripped:
            table_start = i
            break

    if table_start < 0:
        log.warning("Decision Log table not found in decision-framework.md")
        return []


    data_start = table_start + 2

    decisions: list[dict] = []
    idx = 1

    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line.startswith("|"):
            break

        cells = [c.strip() for c in line.split("|")]


        cells = cells[1:-1]

        if len(cells) < 5:
            continue

        date_raw = cells[0].strip()
        domain_raw = cells[1].strip()
        description = cells[2].strip()
        context = cells[3].strip()
        outcome = cells[4].strip()

        if not description:
            continue

        domain = _normalize_domain(domain_raw)
        keywords = _extract_keywords(description)

        decisions.append(
            {
                "id": f"sd-{idx:03d}",
                "description": description,
                "domain": domain,
                "date": date_raw,
                "context": context,
                "outcome": outcome,
                "keywords": keywords,
            }
        )
        idx += 1

    log.info(f"Parsed {len(decisions)} structured decisions from decision-framework.md")
    return decisions





def classify_raw_decisions(parquet_path: Path) -> dict[str, int]:
    ""



    try:
        import pandas as pd
    except ImportError:
        log.error("pandas is required — install with: pip install pandas pyarrow")
        sys.exit(1)

    if not parquet_path.exists():
        log.warning(f"Decisions parquet not found: {parquet_path}")
        return {}

    df = pd.read_parquet(parquet_path)
    total = len(df)
    log.info(f"Loaded {total:,} raw decisions from {parquet_path.name}")



    texts = (df["decision_text"].fillna("") + " " + df["context"].fillna("")).tolist()

    counts: dict[str, int] = {}
    for text in texts:
        domain = classify_domain(text)
        counts[domain] = counts.get(domain, 0) + 1


    counts = dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
    return counts





def build_decision_index(
    structured: list[dict],
    domain_counts: dict[str, int],
    total_raw: int,
) -> dict:
    ""
    return {
        "structured_decisions": structured,
        "domain_counts": domain_counts,
        "total_raw": total_raw,
        "total_structured": len(structured),
        "generated_at": datetime.now(UTC).isoformat(),
    }





def setup_logging(verbose: bool = False) -> None:
    ""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")


def main():
    parser = argparse.ArgumentParser(
        description="SBK Decision Index Builder — offline, zero API calls",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Only print domain counts from raw decisions, don't generate index",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    t0 = time.monotonic()


    if args.stats:
        log.info("Stats mode: classifying raw decisions by domain...")
        domain_counts = classify_raw_decisions(DECISIONS_PARQUET)
        total = sum(domain_counts.values())

        print(f"\n--- Decision Domain Distribution ({total:,} total) ---\n")
        for domain, count in domain_counts.items():
            pct = (count / total * 100) if total > 0 else 0
            bar = "#" * int(pct / 2)
            print(f"  {domain:20s}  {count:>6,}  ({pct:5.1f}%)  {bar}")

        elapsed = time.monotonic() - t0
        print(f"\n  Completed in {elapsed:.1f}s")
        return


    log.info("Building decision index...")


    structured = parse_decision_framework(DECISION_FRAMEWORK_MD)


    domain_counts = classify_raw_decisions(DECISIONS_PARQUET)
    total_raw = sum(domain_counts.values())


    index = build_decision_index(structured, domain_counts, total_raw)

    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    DECISION_INDEX_FILE.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    elapsed = time.monotonic() - t0
    log.info(
        f"Decision index written to {DECISION_INDEX_FILE} "
        f"({index['total_structured']} structured, {total_raw:,} raw, "
        f"{len(domain_counts)} domains, {elapsed:.1f}s)"
    )


    print("\n--- Decision Index Summary ---")
    print(f"  Structured decisions: {index['total_structured']}")
    print(f"  Raw decisions:        {total_raw:,}")
    print(f"  Domains:              {len(domain_counts)}")
    print(f"  Output:               {DECISION_INDEX_FILE}")
    print(f"  Generated:            {index['generated_at']}")
    print(f"  Elapsed:              {elapsed:.1f}s")

    if domain_counts:
        print("\n  Domain breakdown:")
        for domain, count in domain_counts.items():
            pct = (count / total_raw * 100) if total_raw > 0 else 0
            print(f"    {domain:20s}  {count:>6,}  ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
