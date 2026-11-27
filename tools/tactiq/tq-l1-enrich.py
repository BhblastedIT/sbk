#!/usr/bin/env python3
"""Tactiq L1: meetings, speakers resolved to emails, contacts, interactions and the corpus of what you said, from
the Tactiq transcripts.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from text_utils import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    ENRICHED_DIR,
    OWNER_SPEAKER_LABELS,
    TACTIQ_DIR,
    TACTIQ_RAW_DIR,
    safe_write_parquet,
)

RAW_DIR = TACTIQ_RAW_DIR
PROCESSED_DIR = TACTIQ_DIR

log = logging.getLogger("tactiq-enrich")


# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_NAMES = {normalize_name(x) for x in OWNER_SPEAKER_LABELS}


NOISE_SPEAKERS = {
    "speaker",
    "unknown",
    "unknown speaker",
    "read.ai meeting notes",
    "read.ai",
    "notetaker",
    "otter.ai",
    "fireflies.ai",
    "meeting notes",
    "security bot",
}




def is_owner_name(name: str) -> bool:
    ""
    n = normalize_name(name)
    return n in OWNER_NAMES


def is_noise_speaker(name: str) -> bool:
    ""
    n = normalize_name(name)
    if n in NOISE_SPEAKERS:
        return True

    if "notetaker" in n or "meeting notes" in n:
        return True
    return False


def load_json(path: Path) -> dict | None:
    ""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot parse {path.name}: {e}")
        return None





def build_name_to_email_lookup() -> dict:
    ""







    lookup = {}


    merged_path = ENRICHED_DIR / "contacts-merged.parquet"
    if merged_path.exists():
        df = pd.read_parquet(merged_path)
        for _, row in df.iterrows():
            name = normalize_name(row.get("name", ""))
            email = str(row.get("email", "")).strip().lower()
            if name and email and "@" in email:
                lookup[name] = email


    cal_path = ENRICHED_DIR / "contacts-calendar.parquet"
    if cal_path.exists():
        df = pd.read_parquet(cal_path)
        for _, row in df.iterrows():
            name = normalize_name(row.get("name", ""))
            email = str(row.get("email", "")).strip().lower()
            if name and email and "@" in email and name not in lookup:
                lookup[name] = email


    contacts_path = ENRICHED_DIR / "contacts.parquet"
    if contacts_path.exists():
        df = pd.read_parquet(contacts_path)
        for _, row in df.iterrows():
            name = normalize_name(row.get("name", ""))
            email = str(row.get("email", "")).strip().lower()
            if name and email and "@" in email and name not in lookup:
                lookup[name] = email

    log.info(f"Name→email lookup: {len(lookup)} entries")
    return lookup


def resolve_speaker_email(speaker_name: str, lookup: dict) -> str | None:
    ""







    norm = normalize_name(speaker_name)
    if not norm:
        return None


    if norm in OWNER_NAMES:
        return None


    if norm in lookup:
        return lookup[norm]


    parts = norm.split()
    if len(parts) == 2:
        reversed_name = f"{parts[1]} {parts[0]}"
        if reversed_name in lookup:
            return lookup[reversed_name]


    if len(parts) >= 2:
        last_name = parts[-1]
        matches = [
            email
            for name, email in lookup.items()
            if name.endswith(f" {last_name}") or name == last_name
        ]
        if len(matches) == 1:
            return matches[0]

    return None





def parse_all_meetings() -> list[dict]:
    ""
    log.info("Phase 1: Parsing raw Tactiq JSONs...")
    t0 = time.time()

    json_files = sorted(RAW_DIR.glob("*.json"))
    json_files = [f for f in json_files if not f.name.startswith("_")]

    meetings = []
    total_blocks = 0
    parse_errors = 0

    for jf in json_files:
        data = load_json(jf)
        if data is None:
            parse_errors += 1
            continue

        meeting_id = data.get("id", "")
        title = data.get("title", "")
        created_ms = data.get("created", 0)
        duration_s = data.get("duration", 0)
        platform = data.get("platform", "UNKNOWN")
        language = data.get("languageCode", "")


        raw_participants = data.get("participants", [])
        participant_names = [p.get("name", "") for p in raw_participants if p.get("name")]


        transcript = data.get("transcript", {})
        blocks = transcript.get("blocks", []) if isinstance(transcript, dict) else []


        block_records = []
        for b in blocks:
            text = b.get("transcript", "")
            speaker = b.get("speakerName", "")
            ts = b.get("timestamp", 0)

            if b.get("isDeleted", False):
                continue

            block_records.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "timestamp": ts,
                    "chars": len(text),
                    "words": len(text.split()) if text else 0,
                }
            )

        total_blocks += len(block_records)


        speaker_stats = defaultdict(lambda: {"blocks": 0, "chars": 0, "words": 0})
        for br in block_records:
            s = br["speaker"]
            speaker_stats[s]["blocks"] += 1
            speaker_stats[s]["chars"] += br["chars"]
            speaker_stats[s]["words"] += br["words"]

        created_date = ""
        if created_ms:
            try:
                created_date = datetime.fromtimestamp(created_ms / 1000, tz=UTC).strftime(
                    "%Y-%m-%d"
                )
            except (ValueError, OSError):
                pass

        meetings.append(
            {
                "meeting_id": meeting_id,
                "title": title,
                "created_ms": created_ms,
                "created_date": created_date,
                "duration_s": duration_s,
                "duration_min": round(duration_s / 60, 1) if duration_s else 0,
                "platform": platform,
                "language": language,
                "participant_names": participant_names,
                "participant_count": len(participant_names),
                "total_blocks": len(block_records),
                "blocks": block_records,
                "speaker_stats": dict(speaker_stats),
                "source_file": jf.name,
            }
        )

    elapsed = time.time() - t0
    log.info(f"Parsed {len(meetings)} meetings, {total_blocks} blocks in {elapsed:.1f}s")
    if parse_errors:
        log.warning(f"  Parse errors: {parse_errors}")
    return meetings





def build_meetings(meetings: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 2: Building meetings.parquet...")

    rows = []
    for m in meetings:
        speakers_in_meeting = list(m["speaker_stats"].keys())
        rows.append(
            {
                "meeting_id": m["meeting_id"],
                "title": m["title"],
                "created_date": m["created_date"],
                "created_ms": m["created_ms"],
                "duration_s": m["duration_s"],
                "duration_min": m["duration_min"],
                "platform": m["platform"],
                "language": m["language"],
                "participant_count": m["participant_count"],
                "speaker_count": len(speakers_in_meeting),
                "total_blocks": m["total_blocks"],
                "participants": ", ".join(m["participant_names"]),
                "speakers": ", ".join(speakers_in_meeting),
                "source_file": m["source_file"],
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("created_date", ascending=False, inplace=True)
    log.info(f"Meetings: {len(df)} records")
    return df





def build_speakers(meetings: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 3: Building speakers.parquet...")

    speaker_agg = defaultdict(
        lambda: {
            "meetings": 0,
            "blocks_total": 0,
            "chars_total": 0,
            "words_total": 0,
            "first_date": "",
            "last_date": "",
            "meeting_ids": [],
        }
    )

    for m in meetings:
        date = m["created_date"]
        for speaker, stats in m["speaker_stats"].items():
            agg = speaker_agg[speaker]
            agg["meetings"] += 1
            agg["blocks_total"] += stats["blocks"]
            agg["chars_total"] += stats["chars"]
            agg["words_total"] += stats["words"]
            agg["meeting_ids"].append(m["meeting_id"])

            if not agg["first_date"] or date < agg["first_date"]:
                agg["first_date"] = date
            if not agg["last_date"] or date > agg["last_date"]:
                agg["last_date"] = date

    rows = []
    for speaker, agg in speaker_agg.items():
        rows.append(
            {
                "speaker_name": speaker,
                "is_owner": is_owner_name(speaker),
                "meetings_count": agg["meetings"],
                "blocks_total": agg["blocks_total"],
                "chars_total": agg["chars_total"],
                "words_total": agg["words_total"],
                "first_meeting_date": agg["first_date"],
                "last_meeting_date": agg["last_date"],
                "avg_blocks_per_meeting": round(agg["blocks_total"] / agg["meetings"], 1),
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("blocks_total", ascending=False, inplace=True)
    log.info(f"Speakers: {len(df)} unique ({df['is_owner'].sum()} owner variants)")
    return df





def build_contacts(meetings: list[dict], speakers_df: pd.DataFrame) -> pd.DataFrame:
    ""




    log.info("Phase 4: Building contacts-tactiq.parquet...")

    lookup = build_name_to_email_lookup()


    speaker_agg = defaultdict(
        lambda: {
            "meetings": 0,
            "total_minutes": 0,
            "first_date": "",
            "last_date": "",
        }
    )

    for m in meetings:
        date = m["created_date"]
        duration_min = m["duration_min"]
        speaker_count = len(m["speaker_stats"])

        for speaker in m["speaker_stats"]:
            if is_owner_name(speaker) or is_noise_speaker(speaker):
                continue
            agg = speaker_agg[speaker]
            agg["meetings"] += 1

            agg["total_minutes"] += duration_min / max(speaker_count, 1)
            if not agg["first_date"] or date < agg["first_date"]:
                agg["first_date"] = date
            if not agg["last_date"] or date > agg["last_date"]:
                agg["last_date"] = date


    rows = []
    resolved = 0
    unresolved = 0

    for speaker, agg in speaker_agg.items():
        email = resolve_speaker_email(speaker, lookup)
        if email:
            resolved += 1
        else:
            unresolved += 1

        rows.append(
            {
                "speaker_name": speaker,
                "email": email or "",
                "tactiq_meetings": agg["meetings"],
                "tactiq_total_minutes": round(agg["total_minutes"], 1),
                "tactiq_first_seen": agg["first_date"],
                "tactiq_last_seen": agg["last_date"],
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("tactiq_meetings", ascending=False, inplace=True)

    log.info(f"Contacts: {len(df)} speakers, {resolved} resolved to email, {unresolved} unresolved")
    return df





def build_interactions(meetings: list[dict]) -> pd.DataFrame:
    ""





    log.info("Phase 5: Building interactions-tactiq.parquet...")

    edges = defaultdict(
        lambda: {
            "meeting_count": 0,
            "total_blocks": 0,
            "first_date": "",
            "last_date": "",
            "sample_meetings": [],
        }
    )

    for m in meetings:
        date = m["created_date"]
        speakers = [
            s for s in m["speaker_stats"] if not is_owner_name(s) and not is_noise_speaker(s)
        ]


        has_owner = any(is_owner_name(s) for s in m["speaker_stats"])

        for speaker in speakers:
            if has_owner:

                key = tuple(sorted(["_OWNER_", speaker]))
                e = edges[key]
                e["meeting_count"] += 1
                e["total_blocks"] += m["speaker_stats"].get(speaker, {}).get("blocks", 0)
                if not e["first_date"] or date < e["first_date"]:
                    e["first_date"] = date
                if not e["last_date"] or date > e["last_date"]:
                    e["last_date"] = date
                if len(e["sample_meetings"]) < 5:
                    e["sample_meetings"].append(m["title"][:80])


            for other in speakers:
                if other <= speaker:
                    continue
                key = tuple(sorted([speaker, other]))
                e = edges[key]
                e["meeting_count"] += 1
                combined_blocks = m["speaker_stats"].get(speaker, {}).get("blocks", 0) + m[
                    "speaker_stats"
                ].get(other, {}).get("blocks", 0)
                e["total_blocks"] += combined_blocks
                if not e["first_date"] or date < e["first_date"]:
                    e["first_date"] = date
                if not e["last_date"] or date > e["last_date"]:
                    e["last_date"] = date
                if len(e["sample_meetings"]) < 5:
                    e["sample_meetings"].append(m["title"][:80])

    rows = []
    for (s1, s2), info in edges.items():
        rows.append(
            {
                "speaker_1": s1,
                "speaker_2": s2,
                "meeting_count": info["meeting_count"],
                "total_blocks": info["total_blocks"],
                "first_meeting_date": info["first_date"],
                "last_meeting_date": info["last_date"],
                "sample_meetings": " ||| ".join(info["sample_meetings"]),
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("meeting_count", ascending=False, inplace=True)
    log.info(f"Interactions: {len(df)} edges")
    return df





def build_owner_corpus(meetings: list[dict]) -> dict:
    ""




    log.info("Phase 6: Building owner speech corpus...")

    corpus_meetings = []
    total_segments = 0
    total_chars = 0

    for m in meetings:
        owner_blocks = []
        for b in m["blocks"]:
            if is_owner_name(b["speaker"]) and b["text"]:
                owner_blocks.append(
                    {
                        "text": b["text"],
                        "timestamp": b["timestamp"],
                        "chars": b["chars"],
                        "words": b["words"],
                    }
                )

        if owner_blocks:
            total_segments += len(owner_blocks)
            total_chars += sum(b["chars"] for b in owner_blocks)

            corpus_meetings.append(
                {
                    "meeting_id": m["meeting_id"],
                    "title": m["title"],
                    "date": m["created_date"],
                    "platform": m["platform"],
                    "language": m["language"],
                    "duration_min": m["duration_min"],
                    "owner_segments": len(owner_blocks),
                    "owner_chars": sum(b["chars"] for b in owner_blocks),
                    "segments": owner_blocks,
                }
            )

    corpus = {
        "source": "tactiq",
        "generated": datetime.now(UTC).isoformat(),
        "total_meetings": len(corpus_meetings),
        "total_segments": total_segments,
        "total_chars": total_chars,
        "meetings": corpus_meetings,
    }

    log.info(
        f"Owner corpus: {len(corpus_meetings)} meetings, {total_segments} segments, {total_chars:,} chars"
    )
    return corpus





def build_summary(
    meetings: list[dict],
    speakers_df: pd.DataFrame,
    contacts_df: pd.DataFrame,
    interactions_df: pd.DataFrame,
    corpus: dict,
) -> dict:
    ""


    platforms = Counter(m["platform"] for m in meetings)


    languages = Counter(m["language"] for m in meetings)


    dates = [m["created_date"] for m in meetings if m["created_date"]]
    date_range = {"min": min(dates) if dates else "", "max": max(dates) if dates else ""}


    durations = [m["duration_s"] for m in meetings if m["duration_s"] > 0]


    top_speakers = speakers_df.head(20)[
        ["speaker_name", "is_owner", "meetings_count", "blocks_total", "chars_total"]
    ].to_dict("records")


    resolved_count = len(contacts_df[contacts_df["email"] != ""]) if len(contacts_df) > 0 else 0
    total_speakers_non_owner = len(contacts_df)

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "tactiq-enrich-v1",
        "totals": {
            "meetings": len(meetings),
            "blocks": sum(m["total_blocks"] for m in meetings),
            "unique_speakers": len(speakers_df),
            "unique_speakers_non_owner": total_speakers_non_owner,
            "resolved_to_email": resolved_count,
            "unresolved": total_speakers_non_owner - resolved_count,
            "interaction_edges": len(interactions_df),
        },
        "date_range": date_range,
        "duration": {
            "total_hours": round(sum(durations) / 3600, 1) if durations else 0,
            "avg_minutes": round(sum(durations) / len(durations) / 60, 1) if durations else 0,
            "max_minutes": round(max(durations) / 60, 1) if durations else 0,
        },
        "platforms": dict(platforms.most_common()),
        "languages": dict(languages.most_common()),
        "top_speakers": top_speakers,
        "owner_corpus": {
            "meetings": corpus["total_meetings"],
            "segments": corpus["total_segments"],
            "chars": corpus["total_chars"],
        },
        "email_resolution": {
            "resolved": resolved_count,
            "unresolved": total_speakers_non_owner - resolved_count,
            "resolution_rate": round(resolved_count / max(total_speakers_non_owner, 1) * 100, 1),
        },
    }

    return summary




STEP_NAMES = ["meetings", "speakers", "contacts", "interactions", "corpus", "summary"]


def main():
    parser = argparse.ArgumentParser(description="Tactiq enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--step", default=None, choices=STEP_NAMES, help="Run single step (default: all)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not RAW_DIR.exists():
        log.error(f"Raw directory not found: {RAW_DIR}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    meetings = parse_all_meetings()

    if not meetings:
        log.error("No meetings parsed. Check raw directory.")
        sys.exit(1)

    steps_to_run = [args.step] if args.step else STEP_NAMES

    meetings_df = None
    speakers_df = None
    contacts_df = None
    interactions_df = None
    corpus = None


    if "meetings" in steps_to_run:
        meetings_df = build_meetings(meetings)
        if not args.dry_run:
            out = PROCESSED_DIR / "meetings.parquet"
            safe_write_parquet(meetings_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "speakers" in steps_to_run:
        speakers_df = build_speakers(meetings)
        if not args.dry_run:
            out = PROCESSED_DIR / "speakers.parquet"
            safe_write_parquet(speakers_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "contacts" in steps_to_run:
        if speakers_df is None:
            speakers_df = build_speakers(meetings)
        contacts_df = build_contacts(meetings, speakers_df)
        if not args.dry_run:
            out = PROCESSED_DIR / "contacts-tactiq.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "interactions" in steps_to_run:
        interactions_df = build_interactions(meetings)
        if not args.dry_run:
            out = PROCESSED_DIR / "interactions-tactiq.parquet"
            safe_write_parquet(interactions_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "corpus" in steps_to_run:
        corpus = build_owner_corpus(meetings)
        if not args.dry_run:
            out = PROCESSED_DIR / "owner-speech-corpus-tactiq.json"
            out.write_text(json.dumps(corpus, ensure_ascii=False, indent=2))
            log.info(f"  Saved → {out}")


    if "summary" in steps_to_run:
        if speakers_df is None:
            speakers_df = build_speakers(meetings)
        if contacts_df is None:
            contacts_df = build_contacts(meetings, speakers_df)
        if interactions_df is None:
            interactions_df = build_interactions(meetings)
        if corpus is None:
            corpus = build_owner_corpus(meetings)

        summary = build_summary(meetings, speakers_df, contacts_df, interactions_df, corpus)

        if args.dry_run:
            log.info("\n=== DRY RUN — Summary ===")
            log.info(json.dumps(summary, indent=2))
        else:
            out = PROCESSED_DIR / "_meeting_summary.json"
            out.write_text(json.dumps(summary, indent=2, default=str))
            log.info(f"  Saved → {out}")


    log.info("\n" + "=" * 60)
    log.info("TACTIQ ENRICHMENT COMPLETE")
    log.info("=" * 60)
    if meetings_df is not None:
        log.info(f"  Meetings:     {len(meetings_df)}")
    if speakers_df is not None:
        log.info(f"  Speakers:     {len(speakers_df)}")
    if contacts_df is not None:
        resolved = len(contacts_df[contacts_df["email"] != ""])
        log.info(f"  Contacts:     {len(contacts_df)} ({resolved} resolved)")
    if interactions_df is not None:
        log.info(f"  Interactions: {len(interactions_df)} edges")
    if corpus is not None:
        log.info(
            f"  Corpus:       {corpus['total_segments']} segments, {corpus['total_chars']:,} chars"
        )
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-tactiq-enrich", source="tactiq-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
