#!/usr/bin/env python3
"""Writes a context JSON for each person from their relationship facts, the graph and the decay state, with a
model (Anthropic by default). --dry-run estimates the cost; text about your people is sent to the model.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import pandas as pd
from xs_l3_common import PRICING, PROVIDER_PRICING, call_claude, setup_logging

from sbk_config import (
    DECAY_DIR,
    ENRICHED_DIR,
    GRAPH_DIR,
    OWNER_LABEL,
    PERSON_CONTEXT_DIR,
    RELATIONSHIP_FACTS_FILE,
)

log = logging.getLogger("sbk-context-enricher")



GRAPH_FILE = GRAPH_DIR / "sbk-graph.gpickle"
DECAY_STATE_FILE = DECAY_DIR / "decay-state.json"
ENTITY_MAP_FILE = ENRICHED_DIR / "entity-map.json"



_PROVIDER = "anthropic"
_MODEL = "claude-haiku-4-5-20251001"



SYSTEM_PROMPT = """\
You are a structured data analyst for a personal CRM system.
You receive raw relationship facts about a person (extracted from emails, meetings, \
Slack, CRM, LinkedIn, and other sources) plus optional seed data from a knowledge graph.

Your job is to categorize these facts into a clean JSON structure.
Be precise. Only include information that is clearly supported by the facts provided.
If a category has no relevant facts, use empty arrays or empty strings.
Do NOT invent information. Do NOT hallucinate details.

Output ONLY valid JSON, no markdown, no commentary."""

USER_PROMPT_TEMPLATE = """\
Person: {canonical_name} (ID: {person_id})

=== SEED DATA (from knowledge graph) ===
{seed_data}

=== RAW FACTS ({fact_count} total) ===
{facts_text}

=== TASK ===
Categorize the facts above into this JSON structure:

{{
  "personal": {{
    "famiglia": ["fact about family member or relationship"],
    "hobby": ["interests, hobbies, passions mentioned"],
    "progetti_personali": ["personal projects, side ventures"],
    "location": "city/country if mentioned"
  }},
  "business": {{
    "organizzazione": "company or organization name",
    "ruolo": "job title or role",
    "progetti": ["business projects, initiatives"],
    "sfide": ["business challenges, problems mentioned"]
  }},
  "changes": [
    {{"type": "job_change|role_change|location_change|life_event|company_change", \
"description": "what changed", "date": "YYYY-MM-DD or approximate"}}
  ],
  "key_moments": [
    {{"description": "significant interaction or event", "source": "email|meeting|slack|crm|other"}}
  ],
  "promises": [
    {{"description": "commitment made", "direction": "from_person|to_person|mutual", \
"status": "pending|done|unknown"}}
  ]
}}

Rules:
- "from_person" = promise made BY this person TO {owner}
- "to_person" = promise made BY {owner} TO this person
- "mutual" = shared commitment
- Include max 10 key_moments (most significant)
- Include max 10 promises (most recent or important)
- For changes, only include actual transitions, not current state
- Output ONLY the JSON object, nothing else"""





def load_relationship_facts() -> pd.DataFrame:
    ""
    if not RELATIONSHIP_FACTS_FILE.exists():
        log.error(f"relationship-facts.parquet not found: {RELATIONSHIP_FACTS_FILE}")
        sys.exit(1)
    df = pd.read_parquet(RELATIONSHIP_FACTS_FILE)
    log.info(f"Loaded {len(df)} relationship facts")
    return df


def load_graph() -> dict:
    ""



    if not GRAPH_FILE.exists():
        log.warning(f"Graph file not found: {GRAPH_FILE}. Seed data will be empty.")
        return {}

    try:
        with open(GRAPH_FILE, "rb") as f:
            G = pickle.load(f)
        nodes = {}
        for node_id, attrs in G.nodes(data=True):

            nodes[node_id] = dict(attrs)
        log.info(f"Loaded graph with {len(nodes)} nodes")
        return nodes
    except Exception as e:
        log.warning(f"Failed to load graph: {e}. Seed data will be empty.")
        return {}


def load_decay_state() -> dict:
    ""



    if not DECAY_STATE_FILE.exists():
        log.warning(f"decay-state.json not found: {DECAY_STATE_FILE}")
        return {}

    try:
        state = json.loads(DECAY_STATE_FILE.read_text())
        log.info(f"Loaded decay state for {len(state)} persons")
        return state
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to load decay state: {e}")
        return {}


def load_entity_map() -> dict:
    ""



    if not ENTITY_MAP_FILE.exists():
        log.warning(f"entity-map.json not found: {ENTITY_MAP_FILE}")
        return {}

    try:
        emap = json.loads(ENTITY_MAP_FILE.read_text())
        log.info(f"Loaded entity map with {len(emap)} entries")
        return emap
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to load entity map: {e}")
        return {}





def build_pid_to_name(entity_map: dict) -> dict[str, str]:
    ""
    pid_names: dict[str, str] = {}
    for _key, entry in entity_map.items():
        pid = entry.get("person_id", "")
        name = entry.get("canonical_name", "")
        if pid and name and pid not in pid_names:
            pid_names[pid] = name
    return pid_names





def group_facts_by_person(facts_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ""



    groups: dict[str, list[int]] = {}

    for idx, row in facts_df.iterrows():
        subj_pid = row.get("subject_person_id", "")
        obj_pid = row.get("object_person_id", "")
        if subj_pid and isinstance(subj_pid, str) and subj_pid.strip():
            groups.setdefault(subj_pid.strip(), []).append(idx)
        if obj_pid and isinstance(obj_pid, str) and obj_pid.strip():
            groups.setdefault(obj_pid.strip(), []).append(idx)


    result: dict[str, pd.DataFrame] = {}
    for pid, indices in groups.items():
        unique_idx = list(dict.fromkeys(indices))
        result[pid] = facts_df.loc[unique_idx]

    return result





def format_seed_data(person_id: str, graph_nodes: dict, decay_state: dict) -> str:
    ""
    parts = []

    node = graph_nodes.get(person_id, {})
    if node:
        for key in [
            "name",
            "email",
            "score",
            "organization",
            "projects",
            "interests",
            "challenges",
            "family",
            "investments",
            "birthday",
            "location",
            "tags",
            "current_needs",
            "background",
        ]:
            val = node.get(key)
            if val and str(val).lower() not in ("nan", "none", "", "[]", "{}"):
                parts.append(f"- {key}: {val}")

    decay = decay_state.get(person_id, {})
    if decay:
        tier = decay.get("tier", "unknown")
        days_since = decay.get("days_since", "unknown")
        expected_gap = decay.get("expected_gap", "unknown")
        last_contact = decay.get("last_contact", "unknown")
        parts.append(f"- decay_tier: {tier}")
        parts.append(f"- days_since_contact: {days_since}")
        parts.append(f"- expected_gap_days: {expected_gap}")
        parts.append(f"- last_contact_date: {last_contact}")

    return "\n".join(parts) if parts else "(no seed data available)"





def format_facts_text(facts_df: pd.DataFrame, max_facts: int = 200) -> str:
    ""





    if "source_date" in facts_df.columns:
        df_sorted = facts_df.sort_values("source_date", ascending=False, na_position="last")
    else:
        df_sorted = facts_df

    lines = []
    for _, row in df_sorted.head(max_facts).iterrows():
        source_type = row.get("source_type", "")
        source_date = str(row.get("source_date", ""))[:10]
        fact_type = row.get("fact_type", "")
        subject = row.get("subject", "")
        predicate = row.get("predicate", "")
        obj = row.get("object", "")
        context = row.get("context", "")
        confidence = row.get("confidence", "")

        line = f"[{source_type}|{source_date}] ({fact_type}) {subject} — {predicate} — {obj}"
        if context and str(context).lower() not in ("nan", "none", ""):
            ctx_str = str(context)[:200]
            line += f" | ctx: {ctx_str}"
        if confidence and str(confidence).lower() not in ("nan", "none", ""):
            line += f" [conf: {confidence}]"
        lines.append(line)

    return "\n".join(lines)





def parse_json_response(response: str) -> dict | None:
    ""
    text = response.strip()


    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass


    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    end = -1
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass


    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None





def process_person(
    person_id: str,
    canonical_name: str,
    person_facts: pd.DataFrame,
    graph_nodes: dict,
    decay_state: dict,
    force: bool = False,
) -> dict:
    ""



    output_file = PERSON_CONTEXT_DIR / f"{person_id}.json"


    if output_file.exists() and not force:
        return {"person_id": person_id, "skipped": True, "reason": "exists"}

    fact_count = len(person_facts)
    seed_data = format_seed_data(person_id, graph_nodes, decay_state)
    facts_text = format_facts_text(person_facts)

    prompt = USER_PROMPT_TEMPLATE.format(
        canonical_name=canonical_name,
        person_id=person_id,
        seed_data=seed_data,
        fact_count=fact_count,
        facts_text=facts_text,
        owner=OWNER_LABEL,
    )

    try:
        response = call_claude(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=_MODEL,
            max_tokens=2048,
            temperature=0.2,
            provider=_PROVIDER,
        )
    except Exception as e:
        log.error(f"API error for {person_id} ({canonical_name}): {e}")
        return {"person_id": person_id, "error": str(e)}

    parsed = parse_json_response(response)
    if not parsed:
        log.warning(f"Failed to parse JSON for {person_id} ({canonical_name})")
        log.debug(f"Raw response (first 800 chars): {response[:800]}")
        return {"person_id": person_id, "error": "parse_failure"}


    decay = decay_state.get(person_id, {})
    days_since = decay.get("days_since")
    expected_gap = decay.get("expected_gap")


    reconnection_due = False
    if days_since is not None and expected_gap is not None:
        try:
            reconnection_due = float(days_since) > float(expected_gap)
        except (ValueError, TypeError):
            pass


    output = {
        "person_id": person_id,
        "canonical_name": canonical_name,
        "personal": parsed.get("personal", {}),
        "business": parsed.get("business", {}),
        "changes": parsed.get("changes", []),
        "key_moments": parsed.get("key_moments", []),
        "promises": parsed.get("promises", []),
        "decay_tier": decay.get("tier", "unknown"),
        "last_interaction": str(decay.get("last_contact", "")) or None,
        "days_since": days_since,
        "expected_gap": expected_gap,
        "reconnection_due": reconnection_due,
        "fact_count": fact_count,
        "generated_at": datetime.now(UTC).isoformat(),
        "model": _MODEL,
    }


    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {"person_id": person_id, "success": True, "fact_count": fact_count}





def estimate_cost(
    person_groups: dict[str, pd.DataFrame],
    min_facts: int,
    model: str,
    provider: str,
) -> None:
    ""
    eligible = {pid: df for pid, df in person_groups.items() if len(df) >= min_facts}

    total_facts = sum(len(df) for df in eligible.values())


    avg_input_tokens = 300 + 50 * (total_facts / len(eligible)) if eligible else 0
    avg_output_tokens = 800
    total_input = int(avg_input_tokens * len(eligible))
    total_output = int(avg_output_tokens * len(eligible))


    pricing = PRICING.get(model)
    if not pricing:
        pricing = PROVIDER_PRICING.get(provider, {"input": 3.0, "output": 15.0})

    cost_input = total_input * pricing["input"] / 1_000_000
    cost_output = total_output * pricing["output"] / 1_000_000
    total_cost = cost_input + cost_output


    existing = sum(1 for pid in eligible if (PERSON_CONTEXT_DIR / f"{pid}.json").exists())

    log.info("=== CONTEXT ENRICHER — COST ESTIMATE ===")
    log.info("Provider:           %s", provider)
    log.info("Model:              %s", model)
    log.info("Min facts:          %d", min_facts)
    log.info("Total persons:      %d", len(person_groups))
    log.info("Eligible (>=%d facts): %d", min_facts, len(eligible))
    log.info("Already processed:  %d", existing)
    log.info("To process:         %d", len(eligible) - existing)
    log.info("Total facts:        %d", total_facts)
    if eligible:
        log.info("Avg facts/person:   %.0f", total_facts / len(eligible))
    else:
        log.info("Avg facts/person:   N/A")
    log.info("Est. input tokens:  %s", f"{total_input:,}")
    log.info("Est. output tokens: %s", f"{total_output:,}")
    log.info("Est. input cost:    $%.2f", cost_input)
    log.info("Est. output cost:   $%.2f", cost_output)
    log.info("Est. total cost:    $%.2f", total_cost)


    top = sorted(eligible.items(), key=lambda x: len(x[1]), reverse=True)[:15]
    log.info("Top 15 persons by fact count:")
    for pid, df in top:
        log.info("  %s: %d facts", pid, len(df))


    counts = [len(df) for df in eligible.values()]
    if counts:
        counts.sort()
        log.info("Fact count distribution:")
        log.info("  Min:    %d", counts[0])
        log.info("  Median: %d", counts[len(counts) // 2])
        log.info("  Max:    %d", counts[-1])
        log.info("  P90:    %d", counts[int(len(counts) * 0.9)])





def main():
    parser = argparse.ArgumentParser(
        description="Generate person-context JSON from L3 relationship facts"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate cost without calling API",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help="Process a single person by person_id (e.g. p_abc123)",
    )
    parser.add_argument(
        "--min-facts",
        type=int,
        default=10,
        help="Minimum facts threshold per person (default: 10)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Parallel workers for API calls (default: 6)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "gemini", "deepseek", "openai"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name override (default: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing person-context files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()


    global _PROVIDER, _MODEL
    _PROVIDER = args.provider
    if args.model:
        _MODEL = args.model
    elif args.provider != "anthropic":

        from xs_l3_common import PROVIDER_CONFIG

        _MODEL = PROVIDER_CONFIG[args.provider]["default_model"]

    setup_logging(verbose=args.verbose, name="sbk-context-enricher")



    log.info("Loading data sources...")
    facts_df = load_relationship_facts()
    graph_nodes = load_graph()
    decay_state = load_decay_state()
    entity_map = load_entity_map()


    pid_names = build_pid_to_name(entity_map)


    for pid, attrs in graph_nodes.items():
        if pid not in pid_names:
            name = attrs.get("name", "")
            if name and str(name).lower() not in ("nan", "none", ""):
                pid_names[pid] = str(name)



    log.info("Grouping facts by person...")
    person_groups = group_facts_by_person(facts_df)
    log.info(f"Found {len(person_groups)} unique persons in facts")



    if args.dry_run:
        estimate_cost(person_groups, args.min_facts, _MODEL, _PROVIDER)
        return



    if args.person:

        if args.person not in person_groups:
            log.error(
                f"Person {args.person} not found in facts. Available: {len(person_groups)} persons"
            )
            sys.exit(1)
        eligible = {args.person: person_groups[args.person]}
    else:
        eligible = {pid: df for pid, df in person_groups.items() if len(df) >= args.min_facts}

    log.info(f"Eligible persons: {len(eligible)} (min_facts={args.min_facts}, force={args.force})")

    if not eligible:
        log.info("No persons eligible for processing. Done.")
        return


    PERSON_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)



    completed = 0
    skipped = 0
    errors = 0
    success = 0
    lock = threading.Lock()
    start_time = time.time()

    effective_workers = max(1, args.workers)
    total = len(eligible)

    log.info(
        f"Starting context enrichment: {total} persons, "
        f"{effective_workers} workers, model={_MODEL}, provider={_PROVIDER}"
    )

    def collect_result(result: dict):
        nonlocal completed, skipped, errors, success
        with lock:
            completed += 1
            if result.get("skipped"):
                skipped += 1
            elif result.get("error"):
                errors += 1
            elif result.get("success"):
                success += 1

    if effective_workers == 1:

        for idx, (pid, facts) in enumerate(eligible.items()):
            name = pid_names.get(pid, pid)
            result = process_person(pid, name, facts, graph_nodes, decay_state, force=args.force)
            collect_result(result)

            if (idx + 1) % 10 == 0:
                elapsed = time.time() - start_time
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = (total - idx - 1) / rate if rate > 0 else 0
                log.info(
                    f"  Progress: {idx + 1}/{total} "
                    f"({success} ok, {skipped} skip, {errors} err) "
                    f"[{rate:.1f}/s, ETA {eta:.0f}s]"
                )


            if not result.get("skipped"):
                time.sleep(0.2)
    else:

        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = {}
            for pid, facts in eligible.items():
                name = pid_names.get(pid, pid)
                future = executor.submit(
                    process_person,
                    pid,
                    name,
                    facts,
                    graph_nodes,
                    decay_state,
                    args.force,
                )
                futures[future] = pid

            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as e:
                    pid = futures[future]
                    log.error(f"Unhandled error for {pid}: {e}")
                    result = {"person_id": pid, "error": str(e)}

                collect_result(result)

                with lock:
                    if completed % 20 == 0:
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        remaining = total - completed
                        eta = remaining / rate if rate > 0 else 0
                        log.info(
                            f"  Progress: {completed}/{total} "
                            f"({success} ok, {skipped} skip, {errors} err) "
                            f"[{rate:.1f}/s, ETA {eta:.0f}s]"
                        )

    elapsed = time.time() - start_time



    log.info(
        f"\nContext enrichment complete in {elapsed:.1f}s:\n"
        f"  Total:   {total}\n"
        f"  Success: {success}\n"
        f"  Skipped: {skipped} (already exist)\n"
        f"  Errors:  {errors}\n"
        f"  Output:  {PERSON_CONTEXT_DIR}"
    )


    total_files = len(list(PERSON_CONTEXT_DIR.glob("*.json")))
    log.info(f"  Total context files on disk: {total_files}")


if __name__ == "__main__":
    main()
