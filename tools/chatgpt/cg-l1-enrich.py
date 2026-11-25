#!/usr/bin/env python3
""















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import CHATGPT_DIR, DATA_ROOT, OWN_ORG_DISPLAY_NAMES, safe_write_parquet, user_cfg



INPUT_FILE = DATA_ROOT / "chatgpt" / "conversations.json"
PROCESSED_DIR = CHATGPT_DIR

log = logging.getLogger("chatgpt-enrich")







CATEGORY_RULES: dict[str, list[str]] = {
    "FUNDRAISING": [
        r"\binvestor[si]?\b",
        r"\bvaluation\b",
        r"\bround\b",
        r"\bpitch\b",
        r"\bdeck\b",
        r"\bfundraising\b",
        r"\bSAFE\b",
        r"\bbridge\b",
        r"\bterm\s*sheet\b",
        r"\bdue\s*diligence\b",
        r"\bpre[- ]?money\b",
        r"\bpost[- ]?money\b",
        r"\bcap\s*table\b",
        r"\bequity\b",
        r"\bdilution\b",
    ],
    "LEGAL": [
        r"\blegal\b",
        r"\blawsuit\b",
        r"\bclaim[s]?\b",
        r"\blegal\b",
        r"\bcontratt[oi]\b",
        r"\bNDA\b",
        r"\bdispute\b",
        r"\bavvocat[oi]\b",
        r"\blawyer\b",
        r"\bcompliance\b",
        r"\bGDPR\b",
    ],
    "OPERATIONS": [
        r"\bbudget\b",
        r"\bP&L\b",
        r"\bhiring\b",
        r"\bHR\b",
        r"\bsalar[yi]\b",
        r"\bteam\b",
        r"\bonboarding\b",
        r"\bheadcount\b",
        r"\brestructur",
        r"\borganiz",
        r"\boperations?\b",
        r"\bworkflow\b",
        r"\bprocess\b",
        r"\bKPI\b",
        r"\bOKR\b",
    ],
    "PRODUCT": [
        r"\bplatform\b",
        r"\bAPI\b",
        r"\bfeature[s]?\b",
        r"\bUI\b",
        r"\bUX\b",
        r"\bfrontend\b",
        r"\bbackend\b",
        r"\bdashboard\b",
        r"\bproduct\b",
        r"\brelease\b",
        r"\bsprint\b",
    ],
    "STRATEGY": [
        r"\bacquisition\b",
        r"\bM&A\b",
        r"\bgrowth\b",
        r"\bscaling\b",
        r"\broadmap\b",
        r"\bstrateg",
        r"\bcompetitor\b",
        r"\bmarket\s*analysis\b",
        r"\bportfolio\b",
        r"\bexit\b",
    ],
    "RESEARCH": [
        r"\bresearch\b",
        r"\banalysis\b",
        r"\bstudy\b",
        r"\bcomparison\b",
        r"\bbenchmark\b",
        r"\breport\b",
        r"\bdata\s*analysis\b",
        r"\bricerca\b",
        r"\banalisi\b",
    ],
}


CATEGORY_PRIORITY = [
    "FUNDRAISING",
    "LEGAL",
    "STRATEGY",
    "OPERATIONS",
    "PRODUCT",
    "RESEARCH",
]


_COMPILED_RULES: dict[str, list[re.Pattern]] = {}


def _compile_rules():
    ""
    global _COMPILED_RULES
    if _COMPILED_RULES:
        return
    for cat, patterns in CATEGORY_RULES.items():
        _COMPILED_RULES[cat] = [re.compile(p, re.IGNORECASE) for p in patterns]





def _entity_pattern(name: str) -> tuple[str, str]:
    """Whole-word, any-case pattern for a name; spaces match any run of spaces."""
    words = [re.escape(w) for w in name.split()]
    return (r"\b" + r"\s*".join(words) + r"\b", name)


# Names tagged in your conversations: your own organisations ("organisations" in
# sbk.config.json) plus "chatgpt.people" and "chatgpt.companies". Empty by default.
ENTITY_PATTERNS: list[tuple[str, str]] = [
    _entity_pattern(n)
    for n in dict.fromkeys(
        [
            *OWN_ORG_DISPLAY_NAMES,
            *(str(c).strip() for c in (user_cfg("chatgpt.companies", []) or [])),
            *(str(p).strip() for p in (user_cfg("chatgpt.people", []) or [])),
        ]
    )
    if n
]

_COMPILED_ENTITIES: list[tuple[re.Pattern, str]] = []


def _compile_entities():
    ""
    global _COMPILED_ENTITIES
    if _COMPILED_ENTITIES:
        return
    _COMPILED_ENTITIES.extend((re.compile(p, re.IGNORECASE), name) for p, name in ENTITY_PATTERNS)





def load_conversations() -> list[dict]:
    ""
    log.info(f"Loading {INPUT_FILE} ...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        convs = json.load(f)
    log.info(f"  Loaded {len(convs)} conversations")
    return convs


def get_first_user_message(messages: list[dict]) -> str:
    ""
    for m in messages:
        if m.get("role") == "user" and m.get("text", "").strip():
            return m["text"].strip()
    return ""


def get_text_for_classification(conv: dict) -> str:
    ""



    title = conv.get("title", "") or ""
    first_msg = get_first_user_message(conv.get("messages", []))
    return f"{title}\n{first_msg}"


def classify_topics(text: str) -> list[str]:
    ""
    _compile_rules()
    matched = []
    for cat in CATEGORY_PRIORITY:
        for pat in _COMPILED_RULES[cat]:
            if pat.search(text):
                matched.append(cat)
                break
    return matched


def classify_primary(topics: list[str]) -> str:
    ""
    if not topics:
        return "PERSONAL"

    return topics[0]


def extract_entities(text: str) -> list[str]:
    ""
    _compile_entities()
    found = set()
    for pat, name in _COMPILED_ENTITIES:
        if pat.search(text):
            found.add(name)
    return sorted(found)





def classify_all(convs: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 1: Classifying conversations...")
    t0 = time.time()

    rows = []
    for conv in convs:
        conv_id = conv.get("id", "")
        title = conv.get("title", "") or "(untitled)"
        created = conv.get("create_time", "")
        updated = conv.get("update_time", "")
        model = conv.get("default_model_slug", "")
        messages = conv.get("messages", [])
        msg_count = len(messages)


        title_text = title or ""
        all_user_text = []
        all_messages_text = []
        first_user_msg = ""
        for m in messages:
            role = m.get("role", "")
            text = m.get("text", "").strip()
            if text:
                all_messages_text.append(f"[{role}]: {text}")
            if role == "user" and text:
                if not first_user_msg:
                    first_user_msg = text[:500]
                all_user_text.append(m["text"])


        full_text = f"{title_text}\n" + "\n".join(all_user_text)
        topics = classify_topics(full_text)
        category = classify_primary(topics)


        entities = extract_entities(full_text)

        rows.append(
            {
                "conv_id": conv_id,
                "title": title,
                "created": created,
                "updated": updated,
                "model": model,
                "message_count": msg_count,
                "topics": topics if topics else ["PERSONAL"],
                "category": category,
                "entities_mentioned": entities,
                "full_text": "\n\n".join(all_messages_text)[:20000],
                "summary_first_msg": first_user_msg[:500] if first_user_msg else "",
            }
        )

    df = pd.DataFrame(rows)
    elapsed = time.time() - t0
    log.info(f"  Classified {len(df)} conversations in {elapsed:.1f}s")


    cat_counts = df["category"].value_counts()
    for cat, n in cat_counts.items():
        log.info(f"    {cat}: {n}")

    return df





def build_topics_index(df: pd.DataFrame) -> dict:
    ""
    log.info("Phase 2: Building topics index...")

    index: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        for topic in row["topics"]:
            index[topic].append(row["conv_id"])


    sorted_index = {k: v for k, v in sorted(index.items(), key=lambda x: -len(x[1]))}

    for topic, ids in sorted_index.items():
        log.info(f"    {topic}: {len(ids)} conversations")

    return sorted_index





def build_summary(df: pd.DataFrame, topics_index: dict) -> dict:
    ""
    log.info("Phase 3: Building summary...")


    cat_dist = df["category"].value_counts().to_dict()


    model_dist = df["model"].value_counts().to_dict()


    monthly = Counter()
    for created in df["created"]:
        if created and isinstance(created, str) and len(created) >= 7:
            monthly[created[:7]] += 1
    monthly_sorted = dict(sorted(monthly.items()))


    entity_counter = Counter()
    for entities in df["entities_mentioned"]:
        for e in entities:
            entity_counter[e] += 1
    top_entities = entity_counter.most_common(30)


    msg_counts = df["message_count"]


    dates = df["created"].dropna()
    dates_valid = dates[dates.astype(str).str.len() > 0]


    top_by_msgs = df.nlargest(20, "message_count")[
        ["conv_id", "title", "message_count", "model", "category"]
    ].to_dict("records")


    topic_pairs = Counter()
    for topics in df["topics"]:
        if len(topics) >= 2:
            for i, t1 in enumerate(topics):
                for t2 in topics[i + 1 :]:
                    pair = tuple(sorted([t1, t2]))
                    topic_pairs[pair] += 1

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "chatgpt-enrich-v1",
        "totals": {
            "conversations": len(df),
            "total_messages": int(msg_counts.sum()),
            "avg_messages_per_conv": round(float(msg_counts.mean()), 1),
            "median_messages_per_conv": int(msg_counts.median()),
            "max_messages_in_conv": int(msg_counts.max()),
        },
        "date_range": {
            "earliest": str(dates_valid.min()) if len(dates_valid) > 0 else "",
            "latest": str(dates_valid.max()) if len(dates_valid) > 0 else "",
        },
        "category_distribution": cat_dist,
        "topics_count": {k: len(v) for k, v in topics_index.items()},
        "model_distribution": model_dist,
        "monthly_activity": monthly_sorted,
        "top_entities": top_entities,
        "topic_co_occurrence": [
            {"pair": list(pair), "count": count} for pair, count in topic_pairs.most_common(20)
        ],
        "longest_conversations": top_by_msgs,
        "output_files": {
            "conversations_classified": str(PROCESSED_DIR / "conversations-classified.parquet"),
            "categories_index": str(PROCESSED_DIR / "categories-index.json"),
            "summary": str(PROCESSED_DIR / "_chatgpt_summary.json"),
        },
    }

    return summary





def main():
    parser = argparse.ArgumentParser(description="ChatGPT enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed, mark_last_run

        if not check_inputs_changed("cg-l1", [INPUT_FILE]):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("cg-l1")
            return

    if not INPUT_FILE.exists():
        log.error(f"Input file not found: {INPUT_FILE}")
        log.error("Run parse_chatgpt_export.py first.")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    convs = load_conversations()
    if not convs:
        log.error("No conversations loaded.")
        sys.exit(1)


    df = classify_all(convs)


    topics_index = build_topics_index(df)


    summary = build_summary(df, topics_index)

    if args.dry_run:
        log.info("\n=== DRY RUN === Summary:")
        log.info(json.dumps(summary, indent=2, default=str))
    else:

        out_parquet = PROCESSED_DIR / "conversations-classified.parquet"
        safe_write_parquet(df, out_parquet, index=False)
        log.info(f"  Saved -> {out_parquet}")


        out_topics = PROCESSED_DIR / "categories-index.json"
        out_topics.write_text(json.dumps(topics_index, ensure_ascii=False, indent=2))
        log.info(f"  Saved -> {out_topics}")


        out_summary = PROCESSED_DIR / "_chatgpt_summary.json"
        out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        log.info(f"  Saved -> {out_summary}")

    if not args.dry_run:
        from sbk_config import mark_last_run, save_input_checkpoint

        save_input_checkpoint("cg-l1", [INPUT_FILE])
        mark_last_run("cg-l1")


    log.info("\n" + "=" * 60)
    log.info("CHATGPT ENRICHMENT COMPLETE")
    log.info("=" * 60)
    log.info(f"  Conversations:    {len(df)}")
    log.info(f"  Total messages:   {int(df['message_count'].sum())}")
    log.info("  Categories:")
    for cat, n in df["category"].value_counts().items():
        log.info(f"    {cat}: {n}")
    log.info(
        f"  Unique entities:  {len(set(e for ents in df['entities_mentioned'] for e in ents))}"
    )
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


    log.info("\n--- Verification ---")
    log.info(f"  DataFrame shape: {df.shape}")
    log.info(f"  Columns: {list(df.columns)}")
    log.info("  Sample (first 5 rows):")
    for _, row in df.head(5).iterrows():
        log.info(
            f"    [{row['category']}] {row['title'][:60]}  msgs={row['message_count']}  topics={row['topics']}"
        )


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-chatgpt-enrich", source="cg-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
