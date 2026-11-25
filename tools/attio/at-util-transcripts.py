#!/usr/bin/env python3
""

















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
    ATTIO_DIR,
    ATTIO_PROCESSED_DIR,
    ATTIO_TRANSCRIPTS_DIR,
    ATTIO_WORKSPACE_DIRS,
    ENRICHED_DIR,
    OWNER_LABEL,
    OWNER_SPEAKER_LABELS,
    attio_transcript_files,
    safe_write_parquet,
)

RAW_DIR = ATTIO_TRANSCRIPTS_DIR
INDEX_PATH = ATTIO_DIR / "call-recordings.parquet"

INDEX_PATHS = [d / "call-recordings.parquet" for d in ATTIO_WORKSPACE_DIRS.values()]
PROCESSED_DIR = ATTIO_PROCESSED_DIR

log = logging.getLogger("attio-transcripts-enrich")


# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_NAMES = {normalize_name(x) for x in OWNER_SPEAKER_LABELS}


NOISE_SPEAKERS = {
    "speaker",
    "unknown",
    "unknown speaker",
    "read.ai meeting notes",
    "read.ai",
    "otter.ai",
    "fireflies.ai",
    "meeting notes",
    "security bot",
    "notetaker",
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


def load_call_recordings_index() -> dict:
    ""



    existing_paths = [p for p in INDEX_PATHS if p.exists()]
    if not existing_paths:
        log.warning(f"Index not found: {INDEX_PATHS}")
        return {}

    df = pd.concat([pd.read_parquet(p) for p in existing_paths], ignore_index=True)
    lookup = {}
    for _, row in df.iterrows():
        mid = str(row.get("meeting_id", ""))
        if not mid:
            continue
        created_at = str(row.get("created_at", ""))

        call_date = ""
        if created_at:
            try:
                call_date = created_at[:10]
            except Exception:
                pass
        lookup[mid] = {
            "recording_id": str(row.get("recording_id", "")),
            "meeting_title": str(row.get("meeting_title", "")),
            "call_date": call_date,
            "created_at": created_at,
            "duration_seconds": row.get("duration_seconds"),
        }
    log.info(f"Call recordings index: {len(lookup)} entries")
    return lookup





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

    log.info(f"Name->email lookup: {len(lookup)} entries")
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





def parse_all_transcripts(index: dict) -> list[dict]:
    ""
    log.info("Phase 1: Parsing raw Attio transcript JSONs...")
    t0 = time.time()

    json_files = attio_transcript_files(RAW_DIR)

    transcripts = []
    total_segments = 0
    parse_errors = 0
    empty_files = 0

    for jf in json_files:
        data = load_json(jf)
        if data is None:
            parse_errors += 1
            continue




        if isinstance(data.get("data"), dict) and not data.get("segments"):
            data = {**data["data"], **{k: v for k, v in data.items() if k != "data"}}
        if not data.get("segments") and isinstance(data.get("transcript"), list):
            data["segments"] = [
                {
                    "speaker": (g.get("speaker") or {}).get("name", "Unknown")
                    if isinstance(g.get("speaker"), dict)
                    else str(g.get("speaker", "Unknown")),
                    "text": g.get("speech", g.get("text", "")),
                    "start": g.get("start_time", g.get("start", 0.0)),
                    "end": g.get("end_time", g.get("end", 0.0)),
                }
                for g in data["transcript"]
            ]
        meeting_id = data.get("meeting_id", "") or jf.stem.split("__")[0]
        _id = data.get("id") if isinstance(data.get("id"), dict) else {}
        recording_id = (
            data.get("recording_id", "")
            or _id.get("call_recording_id", "")
            or (jf.stem.split("__")[1] if "__" in jf.stem else "")
        )
        title = data.get("meeting_title", "")
        segments = data.get("segments", [])
        raw_transcript = data.get("raw_transcript", "")

        if not segments:
            empty_files += 1
            continue


        idx_info = index.get(meeting_id, {})
        call_date = idx_info.get("call_date", "")
        created_at = idx_info.get("created_at", "")


        if not title and idx_info.get("meeting_title"):
            title = idx_info["meeting_title"]


        segment_records = []
        speakers_in_call = set()
        for seg in segments:
            speaker = seg.get("speaker", "")
            text = seg.get("text", "")
            start = seg.get("start", 0)
            end = seg.get("end", 0)

            if not text or not text.strip():
                continue

            speakers_in_call.add(speaker)
            segment_records.append(
                {
                    "speaker": speaker,
                    "text": text,
                    "start": start,
                    "end": end,
                    "chars": len(text),
                    "words": len(text.split()) if text else 0,
                }
            )

        total_segments += len(segment_records)


        duration_s = 0
        if segment_records:
            starts = [s["start"] for s in segment_records if s["start"] > 0]
            ends = [s["end"] for s in segment_records if s["end"] > 0]
            if starts and ends:
                duration_s = max(ends) - min(starts)


        speaker_stats = defaultdict(lambda: {"segments": 0, "chars": 0, "words": 0})
        for sr in segment_records:
            s = sr["speaker"]
            speaker_stats[s]["segments"] += 1
            speaker_stats[s]["chars"] += sr["chars"]
            speaker_stats[s]["words"] += sr["words"]


        participants = sorted([s for s in speakers_in_call if s and not is_noise_speaker(s)])


        word_count = sum(sr["words"] for sr in segment_records)

        transcripts.append(
            {
                "transcript_id": meeting_id,
                "recording_id": recording_id,
                "title": title,
                "date": call_date,
                "created_at": created_at,
                "duration_s": round(duration_s, 1),
                "duration_min": round(duration_s / 60, 1) if duration_s > 0 else 0,
                "participants": participants,
                "participant_count": len(participants),
                "word_count": word_count,
                "total_segments": len(segment_records),
                "segments": segment_records,
                "speaker_stats": dict(speaker_stats),
                "source_file": jf.name,
                "workspace": next(
                    (w for w, d in ATTIO_WORKSPACE_DIRS.items() if jf.parent == d / "transcripts"),
                    "",
                ),
            }
        )

    elapsed = time.time() - t0
    log.info(
        f"Parsed {len(transcripts)} transcripts ({empty_files} empty skipped), "
        f"{total_segments} segments in {elapsed:.1f}s"
    )
    if parse_errors:
        log.warning(f"  Parse errors: {parse_errors}")
    return transcripts





def build_transcripts_index(transcripts: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 2: Building transcripts-index.parquet...")

    rows = []
    for t in transcripts:
        rows.append(
            {
                "transcript_id": t["transcript_id"],
                "title": t["title"],
                "date": t["date"],
                "duration": round(t["duration_s"]),
                "participants": t["participants"],
                "word_count": t["word_count"],
                "source_file": t["source_file"],
                "workspace": t["workspace"],
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("date", ascending=False, inplace=True, na_position="last")
    log.info(f"Transcript index: {len(df)} records")
    return df





def build_interactions(transcripts: list[dict]) -> pd.DataFrame:
    ""





    log.info("Phase 3: Building interactions-attio-calls.parquet...")

    edges = defaultdict(
        lambda: {
            "call_count": 0,
            "total_duration": 0,
            "first_date": "",
            "last_date": "",
            "sample_titles": [],
        }
    )

    for t in transcripts:
        date = t["date"]
        duration = t["duration_s"]
        speakers = [s for s in t["speaker_stats"] if not is_noise_speaker(s)]

        has_owner = any(is_owner_name(s) for s in speakers)
        non_owner_speakers = [s for s in speakers if not is_owner_name(s)]

        for speaker in non_owner_speakers:
            if has_owner:

                key = (OWNER_LABEL, speaker)
                e = edges[key]
                e["call_count"] += 1
                e["total_duration"] += duration
                if not e["first_date"] or (date and date < e["first_date"]):
                    e["first_date"] = date
                if not e["last_date"] or (date and date > e["last_date"]):
                    e["last_date"] = date
                if len(e["sample_titles"]) < 5 and t["title"]:
                    e["sample_titles"].append(t["title"][:80])


            for other in non_owner_speakers:
                if other <= speaker:
                    continue
                key = tuple(sorted([speaker, other]))
                e = edges[key]
                e["call_count"] += 1
                e["total_duration"] += duration
                if not e["first_date"] or (date and date < e["first_date"]):
                    e["first_date"] = date
                if not e["last_date"] or (date and date > e["last_date"]):
                    e["last_date"] = date
                if len(e["sample_titles"]) < 5 and t["title"]:
                    e["sample_titles"].append(t["title"][:80])

    rows = []
    for (s1, s2), info in edges.items():
        rows.append(
            {
                "from_name": s1,
                "to_name": s2,
                "call_date": info["last_date"],
                "duration": round(info["total_duration"]),
                "source": "attio-calls",
                "call_count": info["call_count"],
                "first_date": info["first_date"],
                "last_date": info["last_date"],
            }
        )

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df.sort_values("call_count", ascending=False, inplace=True)
    log.info(f"Interactions: {len(df)} edges")
    return df





def build_owner_corpus(transcripts: list[dict]) -> dict:
    ""



    log.info("Phase 4: Building owner speech corpus...")

    corpus_calls = []
    total_segments = 0
    total_chars = 0

    for t in transcripts:
        owner_segments = []
        for seg in t["segments"]:
            if is_owner_name(seg["speaker"]) and seg["text"]:
                owner_segments.append(
                    {
                        "text": seg["text"],
                        "start": seg["start"],
                        "end": seg["end"],
                        "chars": seg["chars"],
                        "words": seg["words"],
                    }
                )

        if owner_segments:
            total_segments += len(owner_segments)
            total_chars += sum(s["chars"] for s in owner_segments)

            corpus_calls.append(
                {
                    "transcript_id": t["transcript_id"],
                    "title": t["title"],
                    "date": t["date"],
                    "duration_min": t["duration_min"],
                    "owner_segments": len(owner_segments),
                    "owner_chars": sum(s["chars"] for s in owner_segments),
                    "segments": owner_segments,
                }
            )

    corpus = {
        "source": "attio-calls",
        "generated": datetime.now(UTC).isoformat(),
        "total_calls": len(corpus_calls),
        "total_segments": total_segments,
        "total_chars": total_chars,
        "calls": corpus_calls,
    }

    log.info(
        f"Owner corpus: {len(corpus_calls)} calls, {total_segments} segments, {total_chars:,} chars"
    )
    return corpus





def build_summary(
    transcripts: list[dict], index_df: pd.DataFrame, interactions_df: pd.DataFrame, corpus: dict
) -> dict:
    ""
    log.info("Phase 5: Building summary...")


    dates = [t["date"] for t in transcripts if t["date"]]
    date_range = {"min": min(dates) if dates else "", "max": max(dates) if dates else ""}


    durations = [t["duration_s"] for t in transcripts if t["duration_s"] > 0]


    all_speakers = set()
    speaker_counts = Counter()
    for t in transcripts:
        for s in t["speaker_stats"]:
            if not is_noise_speaker(s):
                all_speakers.add(s)
                speaker_counts[s] += 1


    participant_counts = [t["participant_count"] for t in transcripts]


    top_speakers = [
        {"name": name, "calls": count, "is_owner": is_owner_name(name)}
        for name, count in speaker_counts.most_common(20)
    ]


    owner_calls = sum(1 for t in transcripts if any(is_owner_name(s) for s in t["speaker_stats"]))

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "attio-transcripts-enrich-v1",
        "totals": {

            "transcripts_total": len(attio_transcript_files(RAW_DIR)),
            "transcripts_with_content": len(transcripts),
            "transcripts_empty": len(attio_transcript_files(RAW_DIR)) - len(transcripts),
            "total_segments": sum(t["total_segments"] for t in transcripts),
            "total_words": sum(t["word_count"] for t in transcripts),
            "unique_speakers": len(all_speakers),
            "interaction_edges": len(interactions_df),
        },
        "date_range": date_range,
        "duration": {
            "total_hours": round(sum(durations) / 3600, 1) if durations else 0,
            "avg_minutes": round(sum(durations) / len(durations) / 60, 1) if durations else 0,
            "max_minutes": round(max(durations) / 60, 1) if durations else 0,
        },
        "participants": {
            "avg_per_call": round(sum(participant_counts) / len(participant_counts), 1)
            if participant_counts
            else 0,
            "max_per_call": max(participant_counts) if participant_counts else 0,
            "owner_present_in": owner_calls,
            "owner_presence_rate": round(owner_calls / len(transcripts) * 100, 1)
            if transcripts
            else 0,
        },
        "top_speakers": top_speakers,
        "owner_corpus": {
            "calls": corpus["total_calls"],
            "segments": corpus["total_segments"],
            "chars": corpus["total_chars"],
        },
    }

    return summary





def main():
    parser = argparse.ArgumentParser(description="Attio call transcripts enrichment — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not attio_transcript_files(RAW_DIR):
        log.error(f"No transcripts in {RAW_DIR} nor in the other workspaces")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    index = load_call_recordings_index()


    transcripts = parse_all_transcripts(index)

    if not transcripts:
        log.error("No transcripts parsed. Check raw directory.")
        sys.exit(1)


    index_df = build_transcripts_index(transcripts)
    if not args.dry_run:
        out = PROCESSED_DIR / "transcripts-index.parquet"
        safe_write_parquet(index_df, out, index=False)
        log.info(f"  Saved -> {out}")


    interactions_df = build_interactions(transcripts)
    if not args.dry_run:
        out = PROCESSED_DIR / "interactions-attio-calls.parquet"
        safe_write_parquet(interactions_df, out, index=False)
        log.info(f"  Saved -> {out}")


    corpus = build_owner_corpus(transcripts)
    if not args.dry_run:
        out = PROCESSED_DIR / "owner-speech-corpus-attio.json"
        out.write_text(json.dumps(corpus, ensure_ascii=False, indent=2))
        log.info(f"  Saved -> {out}")


    summary = build_summary(transcripts, index_df, interactions_df, corpus)
    if args.dry_run:
        log.info("\n=== DRY RUN — Summary ===")
        log.info(json.dumps(summary, indent=2))
    else:
        out = PROCESSED_DIR / "_attio_transcripts_summary.json"
        out.write_text(json.dumps(summary, indent=2, default=str))
        log.info(f"  Saved -> {out}")


    log.info("\n" + "=" * 60)
    log.info("ATTIO TRANSCRIPTS ENRICHMENT COMPLETE")
    log.info("=" * 60)
    log.info(f"  Transcripts:  {len(transcripts)} (with content)")
    log.info(f"  Segments:     {sum(t['total_segments'] for t in transcripts)}")
    log.info(f"  Words:        {sum(t['word_count'] for t in transcripts):,}")
    log.info(
        f"  Speakers:     {len(set(s for t in transcripts for s in t['speaker_stats'] if not is_noise_speaker(s)))}"
    )
    log.info(f"  Interactions: {len(interactions_df)} edges")
    log.info(
        f"  Corpus:       {corpus['total_segments']} segments, {corpus['total_chars']:,} chars"
    )
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
