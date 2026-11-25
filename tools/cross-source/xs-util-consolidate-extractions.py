#!/usr/bin/env python3
""





















from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path.home() / ".sbk-data/manual-ingestion/pending"







def _try_parse_person_json(text: str) -> list[dict] | None:
    ""

    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict) and "name" in first and "facts" in first:
                return data
    except json.JSONDecodeError as e:

        if "Extra data" in str(e) and hasattr(e, "pos"):
            try:
                data = json.loads(text[: e.pos])
                if isinstance(data, list) and len(data) > 0:
                    first = data[0]
                    if isinstance(first, dict) and "name" in first and "facts" in first:
                        return data
            except (json.JSONDecodeError, KeyError, IndexError):
                pass


        if text.lstrip().startswith("["):
            depth = 0
            in_string = False
            escape_next = False
            for i, ch in enumerate(text):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[: i + 1])
                            if isinstance(data, list) and len(data) > 0:
                                first = data[0]
                                if isinstance(first, dict) and "name" in first:
                                    return data
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                        break
    except (KeyError, IndexError):
        pass
    return None


def _try_salvage_broken_json(text: str) -> list[dict] | None:
    ""


    best = None

    for pattern in [r"\}\s*\]\s*$", r"\}\s*\]"]:
        for m in re.finditer(pattern, text):
            end = m.end()
            try:
                data = json.loads(text[:end])
                if (
                    isinstance(data, list)
                    and len(data) > 0
                    and isinstance(data[0], dict)
                    and "name" in data[0]
                ):
                    if best is None or len(data) > len(best):
                        best = data
            except json.JSONDecodeError:
                pass

    if best:
        return best



    for closer in ["}\n  ]", "}\n]", "}\r\n]"]:
        last_pos = text.rfind(closer)
        while last_pos > 0:
            try:
                data = json.loads(text[: last_pos + len(closer)])
                if (
                    isinstance(data, list)
                    and len(data) > 0
                    and isinstance(data[0], dict)
                    and "name" in data[0]
                ):
                    return data
            except json.JSONDecodeError:
                pass
            last_pos = text.rfind(closer, 0, last_pos)



    boundaries = [m.start() + 1 for m in re.finditer(r"\},\s*\{", text)]
    for boundary in reversed(boundaries):
        candidate = text[:boundary] + "\n]"
        try:
            data = json.loads(candidate)
            if (
                isinstance(data, list)
                and len(data) > 0
                and isinstance(data[0], dict)
                and "name" in data[0]
            ):
                log.info(
                    "  Salvaged %d people from broken JSON (truncated at boundary %d)",
                    len(data),
                    boundary,
                )
                return data
        except json.JSONDecodeError:
            continue

    return None


def extract_json_from_agent_output(path: Path) -> list[dict] | None:
    ""




    log.info("Parsing agent output: %s (%d KB)", path.name, path.stat().st_size // 1024)

    candidates = []

    for raw_line in path.open():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            d = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        if d.get("type") != "assistant":
            continue

        msg = d.get("message", {})
        content = msg.get("content", [])

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            text = "\n".join(text_parts)
        else:
            continue


        json_blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)


        if not json_blocks and "```json" in text:
            incomplete = re.findall(r"```json\s*\n(.*)", text, re.DOTALL)
            if incomplete:
                json_blocks = incomplete


        if not json_blocks:

            stripped = text.strip()
            if stripped.startswith("[") and '"name"' in stripped[:500]:
                json_blocks = [stripped]
            elif "\n[" in text and '"name"' in text:

                arr_start = text.find("\n[")
                if arr_start >= 0:
                    json_blocks = [text[arr_start + 1 :]]

        for jb in json_blocks:

            data = _try_parse_person_json(jb)
            if data:
                candidates.append(data)
                continue


            for suffix in ["\n]", "\n}\n]", "\n}\n]\n}", '"\n}\n]\n}']:
                data = _try_parse_person_json(jb.rstrip() + suffix)
                if data:
                    candidates.append(data)
                    break
            else:

                data = _try_salvage_broken_json(jb)
                if data:
                    candidates.append(data)

    if not candidates:
        log.warning("  No person-fact JSON found in %s", path.name)
        return None


    best = max(candidates, key=len)
    log.info(
        "  Found %d people in best extraction (%d candidates total)", len(best), len(candidates)
    )
    return best


def load_raw_json(path: Path) -> list[dict] | None:
    ""
    log.info("Loading raw JSON: %s", path.name)
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list) and len(data) > 0:
            log.info("  Found %d people", len(data))
            return data
        log.warning("  Not a valid person-fact array")
        return None
    except json.JSONDecodeError as e:
        log.error("  JSON parse error: %s", e)
        return None







def _normalize_name(name: str) -> str:
    ""

    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))

    return " ".join(ascii_name.lower().split())


def _fact_key(fact: dict) -> str:
    ""
    attr = fact.get("attribute", "")
    value = str(fact.get("value", ""))[:100].lower().strip()
    return f"{attr}::{value}"


def _extract_companies(facts: list[dict]) -> set[str]:
    ""
    companies = set()
    for fact in facts:
        attr = fact.get("attribute", "")
        val = str(fact.get("value", "")).lower().strip()
        if any(k in attr for k in ("company", "fund", "vc", "employer")):
            companies.add(val[:40])
        elif "role" in attr or "title" in attr:

            for sep in [" at ", " @ ", " | ", " of "]:
                if sep in val:
                    companies.add(val.split(sep)[-1].strip()[:40])
    return companies


def consolidate_people(all_extractions: list[list[dict]]) -> list[dict]:
    ""

    people_by_name: dict[str, dict] = {}
    name_variants: dict[str, set] = defaultdict(set)

    for extraction in all_extractions:
        for person in extraction:
            name = person.get("name", "").strip()
            if not name:
                continue

            norm = _normalize_name(name)
            name_variants[norm].add(name)

            if norm not in people_by_name:
                people_by_name[norm] = {
                    "name": name,
                    "aliases": set(),
                    "facts": [],
                    "_fact_keys": set(),
                }

            entry = people_by_name[norm]


            if len(name) > len(entry["name"]):
                entry["name"] = name


            for alias in person.get("aliases", []):
                if alias and alias != entry["name"]:
                    entry["aliases"].add(alias)


            for fact in person.get("facts", []):
                fk = _fact_key(fact)
                if fk not in entry["_fact_keys"]:
                    entry["_fact_keys"].add(fk)
                    entry["facts"].append(fact)


    norms = list(people_by_name.keys())
    merged_into: dict[str, str] = {}

    def _name_parts_match(short_parts: list[str], full_parts: list[str]) -> bool:
        ""

        if all(p in full_parts for p in short_parts):
            return True

        stripped_full = [p.lstrip("al-") if p.startswith("al-") else p for p in full_parts]
        stripped_short = [p.lstrip("al-") if p.startswith("al-") else p for p in short_parts]
        return all(p in stripped_full for p in stripped_short)

    for short_norm in norms:
        if short_norm in merged_into:
            continue
        short_parts = short_norm.split()
        if len(short_parts) > 3:
            continue

        candidates = []
        for full_norm in norms:
            if full_norm == short_norm or full_norm in merged_into:
                continue
            full_parts = full_norm.split()
            if len(full_parts) <= len(short_parts):
                continue

            is_prefix = full_norm.startswith(short_norm + " ")
            is_suffix = full_norm.endswith(" " + short_norm)
            is_subset = _name_parts_match(short_parts, full_parts)

            if is_prefix or is_suffix or is_subset:
                candidates.append(full_norm)

        if not candidates:
            continue



        short_companies = _extract_companies(people_by_name[short_norm]["facts"])

        best_match = None
        for cand in candidates:
            full_companies = _extract_companies(people_by_name[cand]["facts"])
            if short_companies & full_companies:
                best_match = cand
                break


        if not best_match and len(short_parts) == 1 and len(candidates) == 1:

            best_match = candidates[0]

        if best_match:
            merged_into[short_norm] = best_match
            full_entry = people_by_name[best_match]
            short_entry = people_by_name[short_norm]

            full_entry["aliases"].add(short_entry["name"])
            full_entry["aliases"].update(short_entry["aliases"])

            for fact in short_entry["facts"]:
                fk = _fact_key(fact)
                if fk not in full_entry["_fact_keys"]:
                    full_entry["_fact_keys"].add(fk)
                    full_entry["facts"].append(fact)

            for variant in name_variants[short_norm]:
                name_variants[best_match].add(variant)

            log.info("  Merged '%s' into '%s'", short_entry["name"], full_entry["name"])


    def _strip_particles(norm: str) -> str:
        ""
        parts = norm.split()
        return " ".join(
            p.lstrip("al-").lstrip("el-") if p.startswith(("al-", "el-")) else p for p in parts
        )

    particle_groups: dict[str, list[str]] = defaultdict(list)
    for norm in people_by_name:
        if norm in merged_into:
            continue
        stripped = _strip_particles(norm)
        particle_groups[stripped].append(norm)

    for stripped, group in particle_groups.items():
        if len(group) < 2:
            continue

        group.sort(key=lambda n: len(n), reverse=True)
        keeper = group[0]
        for other in group[1:]:
            if other in merged_into:
                continue
            merged_into[other] = keeper
            keeper_entry = people_by_name[keeper]
            other_entry = people_by_name[other]
            keeper_entry["aliases"].add(other_entry["name"])
            keeper_entry["aliases"].update(other_entry["aliases"])
            for fact in other_entry["facts"]:
                fk = _fact_key(fact)
                if fk not in keeper_entry["_fact_keys"]:
                    keeper_entry["_fact_keys"].add(fk)
                    keeper_entry["facts"].append(fact)
            for variant in name_variants[other]:
                name_variants[keeper].add(variant)
            log.info(
                "  Merged (particle) '%s' into '%s'", other_entry["name"], keeper_entry["name"]
            )


    result = []
    for norm, entry in sorted(people_by_name.items()):
        if norm in merged_into:
            continue


        for variant in name_variants[norm]:
            if variant != entry["name"]:
                entry["aliases"].add(variant)

        result.append(
            {
                "name": entry["name"],
                "aliases": sorted(entry["aliases"]),
                "facts": entry["facts"],
            }
        )

    return result







ATTR_MAP = {
    "identity.full_name": "identity.name",
    "identity.name": "identity.name",
    "identity.role": "employment.current_role",
    "identity.company": "employment.current_company",
    "identity.alias": "identity.alias",
    "identity.age_approx": "personal.age",
    "identity.description": "identity.description",
    "identity.online_visibility": "identity.online_visibility",
    "identity.secondary_profile": "identity.secondary_profile",
    "identity.slack_id": "contact.slack_id",
    "contact.slack_dm_channel": "contact.slack_dm",
    "contact.email_work": "contact.email_work",
    "contact.email_personal": "contact.email_personal",
    "contact.email": "contact.email",
    "contact.linkedin_url": "contact.linkedin",
    "contact.linkedin": "contact.linkedin",
    "contact.calendar_url": "contact.calendar_url",
    "contact.calendar_link": "contact.calendar_url",
    "contact.channel": "contact.channel",
    "employment.title": "employment.current_role",
    "employment.role": "employment.current_role",
    "employment.company": "employment.current_company",
    "employment.role_inferred": "employment.current_role",
    "location.city": "location.city",
    "location.hometown": "location.hometown",
    "location.home_city": "location.home_city",
    "location.country": "location.country",
    "location.meeting_venue": "location.meeting_venue",
    "location.origin": "location.origin",
    "location.operating_regions": "location.operating_regions",
    "personal.education": "personal.education",
    "personal.linkedin": "contact.linkedin",
    "personal.linkedin_connections": "personal.linkedin_connections",
    "personal.background": "personal.background",
    "personal.experience": "personal.experience",
    "personal.other_roles": "personal.other_roles",
}


def to_ingestion_format(
    people: list[dict],
    block_num: int,
    description: str,
) -> dict:
    ""
    entities = []

    for person in people:
        name = person["name"]
        facts = []


        facts.append(
            {
                "attribute": "identity.name",
                "value": name,
                "confidence": 0.99,
            }
        )


        for alias in person.get("aliases", []):
            if alias and "@" not in alias:
                facts.append(
                    {
                        "attribute": "identity.alias",
                        "value": alias,
                        "confidence": 0.90,
                    }
                )


        seen_attrs = {"identity.name"}
        for fact in person.get("facts", []):
            raw_attr = fact.get("attribute", "")
            value = fact.get("value", "")
            confidence = fact.get("confidence", 0.85)

            if not raw_attr or not value:
                continue


            attr = ATTR_MAP.get(raw_attr, raw_attr)


            if attr == "identity.name" and "identity.name" in seen_attrs:
                continue
            seen_attrs.add(f"{attr}:{str(value)[:50]}")

            fact_obj = {
                "attribute": attr,
                "value": str(value),
                "confidence": confidence,
            }

            if fact.get("valid_from"):
                fact_obj["valid_from"] = fact["valid_from"]
            if fact.get("valid_to"):
                fact_obj["valid_to"] = fact["valid_to"]

            facts.append(fact_obj)

        entities.append(
            {
                "name": name,
                "type": "person",
                "facts": facts,
            }
        )

    bid = "historical-global" if block_num == 0 else f"historical-block-{block_num:02d}"
    return {
        "batch_id": bid,
        "description": description,
        "source": "claude-session-transcripts",
        "created_by": "xs-util-consolidate-extractions",
        "created_at": datetime.now(UTC).isoformat(),
        "confidence": 0.85,
        "entities": entities,
    }







def print_summary(people: list[dict]) -> None:
    ""
    total_facts = sum(len(p.get("facts", [])) for p in people)
    print(f"\n{'=' * 80}")
    print("CONSOLIDATED EXTRACTION SUMMARY")
    print(f"{'=' * 80}")
    print(f"\nTotal people: {len(people)}")
    print(f"Total facts: {total_facts}")
    print(f"\n{'Person':<40} {'Facts':>5}  Key roles/companies")
    print("-" * 80)

    for person in sorted(people, key=lambda p: len(p.get("facts", [])), reverse=True):
        name = person["name"][:38]
        n_facts = len(person.get("facts", []))


        companies = set()
        roles = set()
        for fact in person.get("facts", []):
            attr = fact.get("attribute", "")
            val = str(fact.get("value", ""))
            if "company" in attr:
                companies.add(val[:30])
            elif "role" in attr or "title" in attr:
                roles.add(val[:30])

        info_parts = []
        if roles:
            info_parts.append(", ".join(sorted(roles)[:2]))
        if companies:
            info_parts.append(", ".join(sorted(companies)[:2]))
        info = " | ".join(info_parts)[:60] if info_parts else ""

        print(f"  {name:<38} {n_facts:>5}  {info}")

    print()







def main():
    parser = argparse.ArgumentParser(
        description="Consolidate person-fact extractions into ingestion-ready fact files"
    )
    parser.add_argument(
        "--agent-outputs",
        nargs="*",
        default=[],
        help="Agent JSONL output files to parse",
    )
    parser.add_argument(
        "--json-files",
        nargs="*",
        default=[],
        help="Raw JSON files with person-fact arrays",
    )
    parser.add_argument(
        "--block",
        type=int,
        default=None,
        help="Block number for the fact file",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Description for the fact file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary but don't write files",
    )
    parser.add_argument(
        "--global-merge",
        action="store_true",
        help="Merge ALL block review files into a single global file",
    )
    args = parser.parse_args()

    if args.global_merge:

        review_files = sorted(OUTPUT_DIR.glob("historical-block-*--review.json"))
        if not review_files:
            parser.error("No block review files found in " + str(OUTPUT_DIR))
        log.info("Global merge: found %d block review files", len(review_files))
        args.json_files = [str(f) for f in review_files]
        if args.block is None:
            args.block = 0

    if not args.global_merge and not args.agent_outputs and not args.json_files:
        parser.error("Provide --agent-outputs and/or --json-files")

    if args.block is None:
        parser.error("--block is required unless using --global-merge")


    all_extractions = []

    for path_str in args.agent_outputs:
        path = Path(path_str)
        if not path.exists():
            log.error("File not found: %s", path)
            continue
        data = extract_json_from_agent_output(path)
        if data:
            all_extractions.append(data)

    for path_str in args.json_files:
        path = Path(path_str)
        if not path.exists():
            log.error("File not found: %s", path)
            continue
        data = load_raw_json(path)
        if data:
            all_extractions.append(data)

    if not all_extractions:
        log.error("No valid extractions found")
        sys.exit(1)

    log.info(
        "Loaded %d extractions with %d total people",
        len(all_extractions),
        sum(len(e) for e in all_extractions),
    )


    people = consolidate_people(all_extractions)
    log.info("Consolidated to %d unique people", len(people))


    print_summary(people)


    desc = args.description or f"Block {args.block} — historical session extraction"
    fact_file = to_ingestion_format(people, args.block, desc)

    total_facts = sum(len(e["facts"]) for e in fact_file["entities"])
    log.info("Ingestion file: %d entities, %d facts", len(fact_file["entities"]), total_facts)

    if args.dry_run:
        print("\n  DRY RUN — no files written")
        return


    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.global_merge:
        out_path = OUTPUT_DIR / "historical-global.json"
        review_path = OUTPUT_DIR / "historical-global--review.json"
    else:
        out_path = OUTPUT_DIR / f"historical-block-{args.block:02d}.json"
        review_path = OUTPUT_DIR / f"historical-block-{args.block:02d}--review.json"

    out_path.write_text(json.dumps(fact_file, indent=2, ensure_ascii=False))
    log.info("Written: %s (%d KB)", out_path, out_path.stat().st_size // 1024)

    review_path.write_text(json.dumps(people, indent=2, ensure_ascii=False))
    log.info("Review file: %s", review_path)

    print(f"\n  Fact file ready for review: {out_path}")
    print(f"  Review file (raw): {review_path}")
    print(f"  To ingest: python3 tools/cross-source/xs-manual-knowledge-ingest.py {out_path}")


if __name__ == "__main__":
    main()
