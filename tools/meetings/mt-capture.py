#!/usr/bin/env python3
"""Post-meeting capture: sends a meeting transcript (Plaud, Tactiq or Attio) to a model and saves a structured
summary (topics, key points, decisions, tasks, follow-ups, attendees resolved to people) in meetings/summaries/; --batch for every
transcript not yet captured, --dry-run to estimate only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_XS_DIR = _TOOLS_DIR / "cross-source"
if str(_XS_DIR) not in sys.path:
    sys.path.insert(0, str(_XS_DIR))

from xs_l3_common import call_claude

from sbk_config import (
    ATTIO_TRANSCRIPTS_DIR,
    DATA_ROOT,
    PLAUD_DIR,
    TACTIQ_RAW_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mt-capture")

SUMMARIES_DIR = DATA_ROOT / "meetings" / "summaries"  # Created when the script runs, not at import, so --help writes nothing.



ENTITY_MAP_PATH = DATA_ROOT / "cross-source" / "entity-map.json"


def _load_entity_map() -> dict:
    ""
    if not ENTITY_MAP_PATH.exists():
        return {}
    try:
        with open(ENTITY_MAP_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _resolve_attendee(name: str, entity_map: dict) -> dict:
    ""
    name_lower = name.strip().lower()
    for key, entry in entity_map.items():
        canonical = entry.get("canonical_name", "").lower()
        aliases = [a.lower() for a in entry.get("aliases", [])]
        if name_lower == canonical or name_lower in aliases:
            return {
                "name": entry.get("canonical_name", name),
                "entity_id": entry.get("person_id", key),
                "email": entry.get("email", ""),
            }

        parts = name_lower.split()
        canonical_parts = canonical.split()
        if len(parts) >= 1 and len(canonical_parts) >= 1:
            if parts[0] == canonical_parts[0] and len(parts) == 1:

                continue
            if len(parts) >= 2 and parts == canonical_parts:
                return {
                    "name": entry.get("canonical_name", name),
                    "entity_id": entry.get("person_id", key),
                    "email": entry.get("email", ""),
                }
    return {"name": name.strip(), "entity_id": "", "email": ""}





def _read_transcript(source: str, file_path: Path) -> tuple[str, str]:
    ""



    if not file_path.exists():
        raise FileNotFoundError(f"Transcript not found: {file_path}")

    if source == "attio" and file_path.suffix == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))

        text = data.get("transcript", data.get("text", json.dumps(data, indent=2)))
        date_str = data.get("date", data.get("created_at", ""))
        if not date_str:
            date_str = _extract_date_from_path(file_path)
        return str(text), str(date_str)[:10]

    text = file_path.read_text(encoding="utf-8", errors="replace")


    date_str = _extract_date_from_path(file_path)
    return text, date_str


def _extract_date_from_path(file_path: Path) -> str:
    ""
    name = file_path.stem

    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)

    m = re.search(r"(\d{8})", name)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    try:
        mtime = file_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d")
    except OSError:
        return datetime.now(UTC).strftime("%Y-%m-%d")




EXTRACTION_PROMPT = """Analyze this meeting transcript and extract the structured information.

Transcript:
{transcript}

Known attendees (entity-map):
{entity_hints}

Return ONLY valid JSON (no markdown, no comments):
{{
  "attendees": [{{"name": "First Last", "role_in_meeting": "speaker/participant"}}],
  "key_points": ["point 1", "point 2"],
  "decisions": ["decision 1"],
  "follow_ups": [{{"task": "description", "owner": "Name", "deadline": "YYYY-MM-DD or null"}}],
  "sentiment": "positive/neutral/negative",
  "topics": ["topic1", "topic2"],
  "summary": "Summary in 2-3 sentences"
}}

Rules:
- Resolve names using the known attendees whenever possible
- If there is no explicit deadline for a follow-up, use null
- Key points: max 7, only the most important
- Decisions: only decisions actually made, not proposals
- Topics: 2-5 main subjects
- Summary: short, factual, max 3 sentences"""


def _generate_meeting_id(source: str, file_path: Path) -> str:
    ""
    content = f"{source}:{file_path.name}"
    return f"{source}-{hashlib.md5(content.encode()).hexdigest()[:12]}"


def capture_meeting(
    source: str,
    file_path: Path,
    provider: str = "anthropic",
    model: str = "",
    dry_run: bool = False,
) -> dict | None:
    ""



    meeting_id = _generate_meeting_id(source, file_path)
    output_path = SUMMARIES_DIR / f"{meeting_id}.json"


    if output_path.exists():
        log.info("Already captured: %s -> %s", file_path.name, output_path.name)
        return json.loads(output_path.read_text(encoding="utf-8"))

    log.info("Capturing meeting: %s (source=%s)", file_path.name, source)


    transcript, date_str = _read_transcript(source, file_path)
    if not transcript or len(transcript.strip()) < 50:
        log.warning("Transcript too short or empty: %s", file_path.name)
        return None


    max_chars = 180_000
    if len(transcript) > max_chars:
        log.warning("Truncating transcript from %d to %d chars", len(transcript), max_chars)
        transcript = transcript[:max_chars]


    entity_map = _load_entity_map()
    entity_hints = []
    for _key, entry in list(entity_map.items())[:200]:
        name = entry.get("canonical_name", "")
        if name:
            entity_hints.append(name)
    hints_str = ", ".join(entity_hints[:100]) if entity_hints else "(no known contacts)"

    if dry_run:
        log.info("[DRY RUN] Would capture %s (%d chars)", file_path.name, len(transcript))
        return None


    prompt = EXTRACTION_PROMPT.format(transcript=transcript, entity_hints=hints_str)
    try:
        response = call_claude(
            prompt=prompt,
            system="You are an expert meeting analyst. Extract structured information from transcripts. Reply ONLY with valid JSON.",
            model=model or "claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
        )
    except Exception as e:
        log.error("Claude call failed for %s: %s", file_path.name, e)
        return None


    try:

        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        extracted = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(
            "Failed to parse Claude response for %s: %s\nResponse: %.500s",
            file_path.name,
            e,
            response,
        )
        return None


    resolved_attendees = []
    for att in extracted.get("attendees", []):
        name = att.get("name", "")
        resolved = _resolve_attendee(name, entity_map)
        resolved["role_in_meeting"] = att.get("role_in_meeting", "participant")
        resolved_attendees.append(resolved)


    summary = {
        "meeting_id": meeting_id,
        "date": date_str,
        "source": source,
        "attendees": resolved_attendees,
        "key_points": extracted.get("key_points", []),
        "decisions": extracted.get("decisions", []),
        "follow_ups": extracted.get("follow_ups", []),
        "sentiment": extracted.get("sentiment", "neutral"),
        "topics": extracted.get("topics", []),
        "summary": extracted.get("summary", ""),
        "raw_transcript_path": str(file_path),
        "captured_at": datetime.now(UTC).isoformat(),
    }


    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(
        "Saved meeting summary: %s (%d attendees, %d decisions, %d follow-ups)",
        output_path.name,
        len(resolved_attendees),
        len(summary["decisions"]),
        len(summary["follow_ups"]),
    )
    return summary




SOURCE_DIRS = {
    "plaud": PLAUD_DIR,
    "tactiq": TACTIQ_RAW_DIR,
    "attio": ATTIO_TRANSCRIPTS_DIR,
}


def _get_transcript_files(source: str) -> list[Path]:
    ""
    src_dir = SOURCE_DIRS.get(source)
    if not src_dir or not src_dir.exists():
        log.warning("Source directory not found: %s -> %s", source, src_dir)
        return []
    if source == "attio":
        return sorted(src_dir.glob("*.json"))
    return sorted(src_dir.glob("*.txt")) + sorted(src_dir.glob("*.md"))


def batch_capture(
    source: str,
    provider: str = "anthropic",
    model: str = "",
    limit: int = 0,
    dry_run: bool = False,
) -> list[dict]:
    ""
    files = _get_transcript_files(source)
    if not files:
        log.info("No transcript files found for source: %s", source)
        return []


    existing_ids = {f.stem for f in SUMMARIES_DIR.glob("*.json")}
    to_process = []
    for f in files:
        mid = _generate_meeting_id(source, f)
        if mid not in existing_ids:
            to_process.append(f)

    log.info(
        "Source %s: %d total, %d already processed, %d to process",
        source,
        len(files),
        len(files) - len(to_process),
        len(to_process),
    )

    if limit > 0:
        to_process = to_process[:limit]

    results = []
    for i, fp in enumerate(to_process, 1):
        log.info("[%d/%d] Processing: %s", i, len(to_process), fp.name)
        result = capture_meeting(source, fp, provider=provider, model=model, dry_run=dry_run)
        if result:
            results.append(result)

    log.info("Batch complete: %d/%d captured", len(results), len(to_process))
    return results


def list_summaries(limit: int = 20) -> list[dict]:
    ""
    files = sorted(SUMMARIES_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    summaries = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summaries.append(
                {
                    "meeting_id": data.get("meeting_id", f.stem),
                    "date": data.get("date", ""),
                    "source": data.get("source", ""),
                    "summary": data.get("summary", "")[:200],
                    "attendees": len(data.get("attendees", [])),
                    "decisions": len(data.get("decisions", [])),
                    "follow_ups": len(data.get("follow_ups", [])),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return summaries





def main():
    parser = argparse.ArgumentParser(
        description="Post-Meeting Capture: structured extraction from transcripts"
    )
    parser.add_argument("--source", choices=["plaud", "tactiq", "attio"], help="Transcript source")
    parser.add_argument("--file", type=Path, help="Single transcript file to process")
    parser.add_argument("--batch", action="store_true", help="Process all unprocessed transcripts")
    parser.add_argument("--list", action="store_true", help="List existing summaries")
    parser.add_argument(
        "--provider", default="anthropic", help="LLM provider (anthropic/gemini/deepseek)"
    )
    parser.add_argument("--model", default="", help="LLM model override")
    parser.add_argument("--limit", type=int, default=0, help="Max transcripts to process in batch")
    parser.add_argument("--dry-run", action="store_true", help="Estimate only, no API calls")
    args = parser.parse_args()

    if args.list:
        summaries = list_summaries(limit=50)
        if not summaries:
            print("No meeting summaries found.")
            return
        print(f"\n{'ID':<30} {'Date':<12} {'Source':<8} {'Att':<5} {'Dec':<5} {'FU':<5} Summary")
        print("-" * 120)
        for s in summaries:
            print(
                f"{s['meeting_id']:<30} {s['date']:<12} {s['source']:<8} {s['attendees']:<5} "
                f"{s['decisions']:<5} {s['follow_ups']:<5} {s['summary'][:50]}"
            )
        return

    if args.batch:
        if not args.source:
            parser.error("--batch requires --source")
        batch_capture(
            args.source,
            provider=args.provider,
            model=args.model,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        return

    if args.file:
        if not args.source:
            parser.error("--file requires --source")
        result = capture_meeting(
            args.source, args.file, provider=args.provider, model=args.model, dry_run=args.dry_run
        )
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
