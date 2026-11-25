#!/usr/bin/env python3
""























from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    DEEP_RESPONSES_DIR,
    NLP_DIR,
    OWNER_LABEL,
    SIGNAL_CONFIG_FILE,
    SIGNALS_DIR,
    SIGNALS_LOG_FILE,
)

log = logging.getLogger("signal-detector")



DEFAULT_CONFIG = {
    "min_sources": 2,
    "time_window_hours": 48,
    "relevance_threshold": 0.5,
    "combined_score_threshold": 0.6,
    "scan_days_back": 7,
    "notify_channel": "slack_dm",
    # Interest keywords; load from user config. Generic demo defaults:
    "interest_keywords": [
        "fundraising",
        "partnership",
        "hiring",
    ],
    "category_weights": {
        "financial": 1.0,
        "deal": 0.9,
        "commitment": 0.7,
        "negotiation": 0.8,
        "strategic": 0.6,
        "operational": 0.3,
    },
}


def load_config() -> dict:
    ""
    if SIGNAL_CONFIG_FILE.exists():
        try:
            user_cfg = json.loads(SIGNAL_CONFIG_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULT_CONFIG, **user_cfg}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    ""
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    SIGNAL_CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )




FactEntry = dict


def scan_batch_responses(days_back: int = 7) -> list[FactEntry]:
    ""
    batch_dir = NLP_DIR / "batch-responses"
    if not batch_dir.exists():
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    facts = []

    for f in batch_dir.glob("*.json"):

        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        if date_match:
            file_date = date_match.group(1)
        else:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
                file_date = mtime.strftime("%Y-%m-%d")
            except OSError:
                file_date = ""
        if file_date and file_date < cutoff:
            continue

        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


        source_type = _guess_source_type(f.name)


        for entity in data.get("entities_mentioned", []):
            if isinstance(entity, dict):
                name = entity.get("name", "")
            elif isinstance(entity, str):
                name = entity
            else:
                continue
            if name and len(name) >= 3:
                facts.append(
                    {
                        "entity": _normalize_entity(name),
                        "topic": "",
                        "source_type": source_type,
                        "source_id": f.stem,
                        "date": file_date,
                        "category": "entity",
                        "context": "",
                    }
                )


        for topic in data.get("key_topics", []):
            if isinstance(topic, dict):
                t = topic.get("topic", "")
            elif isinstance(topic, str):
                t = topic
            else:
                continue
            if t and len(t) >= 3:
                facts.append(
                    {
                        "entity": "",
                        "topic": t.lower().strip(),
                        "source_type": source_type,
                        "source_id": f.stem,
                        "date": file_date,
                        "category": "topic",
                        "context": "",
                    }
                )

    return facts


def scan_deep_responses(days_back: int = 7) -> list[FactEntry]:
    ""
    if not DEEP_RESPONSES_DIR.exists():
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    facts = []

    for source_dir in DEEP_RESPONSES_DIR.iterdir():
        if not source_dir.is_dir():
            continue
        source_type = source_dir.name

        for f in source_dir.glob("*.json"):
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
            file_date = date_match.group(1) if date_match else ""
            if file_date and file_date < cutoff:
                continue

            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue


            for category in (
                "financial",
                "deal",
                "commitment",
                "negotiation",
                "strategic",
                "operational",
            ):
                entries = data.get(category, [])
                if not isinstance(entries, list):
                    continue

                for entry in entries:
                    if not isinstance(entry, dict):
                        continue


                    entities = set()
                    for field in ("person", "person_or_entity", "entity", "owner"):
                        val = entry.get(field, "")
                        if val and isinstance(val, str) and len(val) >= 3:
                            entities.add(_normalize_entity(val))


                    parties = entry.get("parties", [])
                    if isinstance(parties, list):
                        for p in parties:
                            if isinstance(p, str) and len(p) >= 3:
                                entities.add(_normalize_entity(p))

                    context = (entry.get("context", "") or entry.get("description", "") or "")[:200]

                    for ent in entities:
                        facts.append(
                            {
                                "entity": ent,
                                "topic": "",
                                "source_type": source_type,
                                "source_id": f"{source_type}/{f.stem}",
                                "date": file_date,
                                "category": category,
                                "context": context,
                            }
                        )

    return facts


def _normalize_entity(name: str) -> str:
    ""
    return name.strip().lower()


def _guess_source_type(filename: str) -> str:
    ""
    fn = filename.lower()
    if "email" in fn or fn.startswith("em_"):
        return "email"
    elif "slack" in fn or fn.startswith("sl_"):
        return "slack"
    elif "plaud" in fn or fn.startswith("pl_"):
        return "plaud"
    elif "tactiq" in fn or fn.startswith("tq_"):
        return "tactiq"
    elif "whatsapp" in fn or fn.startswith("wa_"):
        return "whatsapp"
    elif "attio" in fn or fn.startswith("at_"):
        return "attio"
    elif "notion" in fn or fn.startswith("no_"):
        return "notion"
    return "unknown"





def build_entity_index(facts: list[FactEntry]) -> dict[str, list[FactEntry]]:
    ""
    index = defaultdict(list)
    for f in facts:
        key = f["entity"] or f["topic"]
        if key:
            index[key].append(f)
    return dict(index)


def cluster_cross_source(
    index: dict[str, list[FactEntry]],
    min_sources: int = 2,
    time_window_hours: int = 48,
) -> list[dict]:
    ""



    clusters = []

    for key, facts in index.items():

        by_source = defaultdict(list)
        for f in facts:
            by_source[f["source_type"]].append(f)

        if len(by_source) < min_sources:
            continue


        dates = sorted({f["date"] for f in facts if f["date"]})
        if dates:
            first_date = dates[0]
            last_date = dates[-1]


            try:
                d1 = datetime.strptime(first_date, "%Y-%m-%d")
                d2 = datetime.strptime(last_date, "%Y-%m-%d")
                if (d2 - d1).total_seconds() > time_window_hours * 3600:
                    continue
            except (ValueError, TypeError):
                first_date = ""
                last_date = ""
        else:

            first_date = datetime.now(UTC).strftime("%Y-%m-%d")
            last_date = first_date


        sources = []
        seen_sources = set()
        for f in facts:
            src_key = f"{f['source_type']}:{f['source_id']}"
            if src_key not in seen_sources:
                seen_sources.add(src_key)
                sources.append(
                    {
                        "type": f["source_type"],
                        "source_id": f["source_id"],
                        "date": f["date"],
                    }
                )


        contexts = [f["context"] for f in facts if f["context"]]


        categories = list({f["category"] for f in facts})

        clusters.append(
            {
                "theme": key,
                "entities": [key],
                "sources": sources,
                "source_types": list(by_source.keys()),
                "categories": categories,
                "contexts": contexts[:10],
                "first_seen": first_date,
                "last_seen": last_date,
                "fact_count": len(facts),
            }
        )


    clusters.sort(key=lambda c: c["fact_count"], reverse=True)
    return clusters





def score_clusters(clusters: list[dict], config: dict) -> list[dict]:
    ""



    interest_keywords = [k.lower() for k in config.get("interest_keywords", [])]
    category_weights = config.get("category_weights", {})

    for cluster in clusters:

        theme_lower = cluster["theme"].lower()
        keyword_match = any(kw in theme_lower for kw in interest_keywords)


        cat_weight = max(
            (category_weights.get(cat, 0.3) for cat in cluster["categories"]),
            default=0.3,
        )

        relevance = 0.0
        if keyword_match:
            relevance += 0.5
        relevance += cat_weight * 0.5


        n_sources = len(cluster["source_types"])
        urgency = min(n_sources / 4.0, 1.0)


        try:
            last_seen = datetime.strptime(cluster["last_seen"], "%Y-%m-%d")
            days_ago = (datetime.now(UTC).replace(tzinfo=None) - last_seen).days
            if days_ago <= 1:
                urgency = min(urgency + 0.3, 1.0)
            elif days_ago <= 3:
                urgency = min(urgency + 0.1, 1.0)
        except (ValueError, TypeError):
            pass

        combined = 0.6 * relevance + 0.4 * urgency

        cluster["relevance_score"] = round(relevance, 3)
        cluster["urgency_score"] = round(urgency, 3)
        cluster["combined_score"] = round(combined, 3)


    clusters.sort(key=lambda c: c["combined_score"], reverse=True)
    return clusters





def load_signals_log() -> list[dict]:
    ""
    if SIGNALS_LOG_FILE.exists():
        try:
            return json.loads(SIGNALS_LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_signals_log(signals: list[dict]) -> None:
    ""
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    SIGNALS_LOG_FILE.write_text(
        json.dumps(signals, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def filter_new_signals(
    clusters: list[dict],
    existing_signals: list[dict],
    threshold: float = 0.6,
) -> list[dict]:
    ""

    notified_themes = set()
    for sig in existing_signals:
        if sig.get("status") in ("notified", "dismissed"):
            notified_themes.add(sig.get("theme", "").lower())

    new_signals = []
    for cluster in clusters:
        if cluster["combined_score"] < threshold:
            continue
        if cluster["theme"].lower() in notified_themes:
            continue
        new_signals.append(cluster)

    return new_signals





def synthesize_signal(cluster: dict) -> str:
    ""
    try:
        import anthropic  # noqa: F401 — probe installation; actual client via factory
    except ImportError:
        return _fallback_synthesis(cluster)

    contexts = cluster.get("contexts", [])
    if not contexts:
        return _fallback_synthesis(cluster)

    prompt = f"""You are an intelligence analyst working for the user. These facts come from
independent sources (email, Slack, meetings, CRM) and concern the same topic/entity.

Generate a summary in English (max 120 words) structured as follows:
1. WHAT: what is emerging, in 1-2 sentences
2. SOURCES: from which sources and when (dates)
3. IMPACT: why it is relevant to {OWNER_LABEL}, suggested action

Do not use emoji. Do not invent information not present in the facts.

Grouped topic/entity: {cluster["theme"]}

Grouped facts ({len(cluster["source_types"])} sources, {cluster["first_seen"]} - {cluster["last_seen"]}):
{chr(10).join(f"- [{c[:200]}]" for c in contexts[:8])}"""

    try:
        _CROSS_SOURCE_DIR = Path(__file__).resolve().parent.parent / "cross-source"
        if str(_CROSS_SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(_CROSS_SOURCE_DIR))
        from xs_anthropic_client import get_client

        client = get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.warning("Claude synthesis failed: %s", e)
        return _fallback_synthesis(cluster)


def _fallback_synthesis(cluster: dict) -> str:
    ""
    sources_str = ", ".join(cluster.get("source_types", []))
    return (
        f"Cross-source signal: '{cluster['theme']}' appears in {len(cluster.get('source_types', []))} "
        f"sources ({sources_str}) between {cluster.get('first_seen', '?')} and {cluster.get('last_seen', '?')}. "
        f"{cluster.get('fact_count', 0)} total mentions."
    )





def notify_signal(signal: dict, dry_run: bool = False) -> bool:
    ""
    if dry_run:
        log.info(
            "[DRY RUN] Would notify signal: %s (score: %.2f)",
            signal.get("theme", "?"),
            signal.get("combined_score", 0),
        )
        return True

    try:
        from monitoring.slack_alerter import alert_custom
    except ImportError:
        log.warning("Cannot import slack_alerter")
        return False

    theme = signal.get("theme", "?")
    summary = signal.get("summary", "")
    score = signal.get("combined_score", 0)
    n_sources = len(signal.get("source_types", []))

    return alert_custom(
        title=f"Signal: {theme} ({n_sources} sources)",
        body=summary[:500] if summary else f"Score: {score:.2f}",
        alert_key=f"signal:{theme.lower()[:50]}",
    )





def run_signal_scan(
    config: dict | None = None,
    dry_run: bool = False,
    synthesize: bool = True,
) -> dict:
    ""



    if config is None:
        config = load_config()

    days_back = config.get("scan_days_back", 7)
    min_sources = config.get("min_sources", 2)
    time_window = config.get("time_window_hours", 48)
    threshold = config.get("combined_score_threshold", 0.6)

    log.info(
        "Scanning for signals (days_back=%d, min_sources=%d, window=%dh, threshold=%.2f)",
        days_back,
        min_sources,
        time_window,
        threshold,
    )


    batch_facts = scan_batch_responses(days_back=days_back)
    deep_facts = scan_deep_responses(days_back=days_back)
    all_facts = batch_facts + deep_facts
    log.info(
        "Scanned %d batch facts + %d deep facts = %d total",
        len(batch_facts),
        len(deep_facts),
        len(all_facts),
    )

    if not all_facts:
        return {"status": "no_facts", "signals": [], "scanned": 0}


    index = build_entity_index(all_facts)
    log.info("Indexed %d unique entities/topics", len(index))


    clusters = cluster_cross_source(index, min_sources=min_sources, time_window_hours=time_window)
    log.info("Found %d cross-source clusters", len(clusters))


    clusters = score_clusters(clusters, config)


    existing_signals = load_signals_log()
    new_signals = filter_new_signals(clusters, existing_signals, threshold=threshold)
    log.info("New signals above threshold: %d (of %d clusters)", len(new_signals), len(clusters))


    created_signals = []
    for cluster in new_signals[:10]:

        signal = {
            "signal_id": f"sig-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{len(created_signals):03d}",
            "theme": cluster["theme"],
            "entities": cluster["entities"],
            "sources": cluster["sources"][:10],
            "source_types": cluster["source_types"],
            "first_seen": cluster["first_seen"],
            "last_seen": cluster["last_seen"],
            "relevance_score": cluster["relevance_score"],
            "urgency_score": cluster["urgency_score"],
            "combined_score": cluster["combined_score"],
            "fact_count": cluster["fact_count"],
            "summary": "",
            "status": "new",
            "notified_at": None,
            "created_at": datetime.now(UTC).isoformat(),
        }


        if synthesize and cluster.get("contexts"):
            signal["summary"] = synthesize_signal(cluster)
        else:
            signal["summary"] = _fallback_synthesis(cluster)


        if notify_signal(signal, dry_run=dry_run):
            signal["status"] = "notified"
            signal["notified_at"] = datetime.now(UTC).isoformat()

        created_signals.append(signal)


    if created_signals and not dry_run:
        all_signals = existing_signals + created_signals
        save_signals_log(all_signals)
        log.info("Saved %d new signals to log (total: %d)", len(created_signals), len(all_signals))

    return {
        "status": "ok",
        "scanned": len(all_facts),
        "clusters": len(clusters),
        "new_signals": len(created_signals),
        "signals": created_signals,
    }





def show_stats() -> None:
    ""
    signals = load_signals_log()
    if not signals:
        print("No signals detected yet.")
        return

    by_status = defaultdict(int)
    by_source = defaultdict(int)
    scores = []

    for s in signals:
        by_status[s.get("status", "unknown")] += 1
        for st in s.get("source_types", []):
            by_source[st] += 1
        scores.append(s.get("combined_score", 0))

    print(f"\nTotal signals: {len(signals)}")
    print(f"Avg combined score: {sum(scores) / len(scores):.2f}" if scores else "")

    print("\nBy status:")
    for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n}")

    print("\nBy source type:")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {s}: {n}")


    recent = sorted(signals, key=lambda s: s.get("created_at", ""), reverse=True)[:10]
    if recent:
        print("\nRecent signals:")
        for s in recent:
            print(
                f"  [{s.get('combined_score', 0):.2f}] {s.get('theme', '?')} "
                f"({len(s.get('source_types', []))} sources, "
                f"{s.get('first_seen', '?')} - {s.get('last_seen', '?')})"
            )





def main():
    parser = argparse.ArgumentParser(description="SBK Signal Detector")
    parser.add_argument("--scan", action="store_true", help="Run full signal detection scan")
    parser.add_argument("--stats", action="store_true", help="Show signal statistics")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without notifying or saving"
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=0,
        help="Override scan lookback days (default: from config)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0,
        help="Override combined score threshold (default: from config)",
    )
    parser.add_argument(
        "--no-synthesize", action="store_true", help="Skip Claude synthesis (use fallback)"
    )
    parser.add_argument(
        "--init-config", action="store_true", help="Create default signal-config.json"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.init_config:
        save_config(DEFAULT_CONFIG)
        print(f"Config saved to {SIGNAL_CONFIG_FILE}")
        return

    if args.stats:
        show_stats()
        return

    if args.scan:
        config = load_config()
        if args.days_back > 0:
            config["scan_days_back"] = args.days_back
        if args.threshold > 0:
            config["combined_score_threshold"] = args.threshold

        result = run_signal_scan(
            config=config,
            dry_run=args.dry_run,
            synthesize=not args.no_synthesize,
        )

        print("\nSignal Scan Summary:")
        print(f"  Facts scanned: {result.get('scanned', 0)}")
        print(f"  Clusters found: {result.get('clusters', 0)}")
        print(f"  New signals: {result.get('new_signals', 0)}")

        if result.get("signals"):
            print("\nNew signals:")
            for s in result["signals"]:
                print(
                    f"  [{s['combined_score']:.2f}] {s['theme']} "
                    f"({len(s.get('source_types', []))} sources)"
                )
                if s.get("summary"):
                    print(f"    {s['summary'][:150]}...")

        if args.dry_run:
            print("\n[DRY RUN] No changes saved.")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
