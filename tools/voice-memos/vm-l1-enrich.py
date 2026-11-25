#!/usr/bin/env python3
""
























from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from text_utils import normalize_name  # noqa: E402

from sbk_config import (  # noqa: E402
    OWNER_LABEL,
    OWNER_SPEAKER_LABELS,
    VOICE_MEMOS_DIR,
    VOICE_MEMOS_PROCESSED_DIR,
    VOICE_MEMOS_TRANSCRIPTS_DIR,
    mark_last_run,
    safe_write_parquet,
    user_cfg,
)



PROJECT_ROOT = Path(__file__).resolve().parent.parent
VM_TRANSCRIPTS_DIR = VOICE_MEMOS_TRANSCRIPTS_DIR
VM_PARQUET = VOICE_MEMOS_DIR / "voice-memos.parquet"
AT_DIR = PROJECT_ROOT / "sbk" / "raw" / "audio-transcripts"
PROCESSED_DIR = VOICE_MEMOS_PROCESSED_DIR

log = logging.getLogger("voice-memos-enrich")


# Your names and speaker labels, from sbk.config.json (owner, own_names).
OWNER_ALIASES = {normalize_name(x) for x in OWNER_SPEAKER_LABELS}
# How a segment spoken by you is labelled in the output.
OWNER_SPEAKER = OWNER_LABEL



KNOWN_LOCATIONS = {
    "city center": "City",
    "central station": "City",
    "airport": "Airport",
    "hotel downtown": "City",
}



def _patterns(names) -> list[str]:
    """One whole-word, case-insensitive pattern per name ("Sam Demo" also matches "sam  demo")."""
    if isinstance(names, str):
        names = [names]
    return [
        r"\b" + r"\s+".join(re.escape(w) for w in str(n).split()) + r"\b"
        for n in (names or [])
        if str(n).strip()
    ]


# Companies and people to spot in your memos: sbk.config.json "voice_memos" -> "companies" and
# "people". Nothing is built in, so an empty list means no company or person tags.
COMPANY_PATTERNS = _patterns(user_cfg("voice_memos.companies", []))
PERSON_PATTERNS = _patterns(user_cfg("voice_memos.people", []))





def is_owner_name(name: str) -> bool:
    ""
    n = normalize_name(name)
    return n in OWNER_ALIASES


def is_dominant_speaker(speaker_id: str, metadata: dict) -> bool:
    ""
    speakers = metadata.get("speakers", {})
    if speaker_id in speakers:
        return speakers[speaker_id].get("is_dominant", False)
    return False


def load_json(path: Path) -> dict | None:
    ""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Cannot parse {path.name}: {e}")
        return None


def slug_from_filename(filename: str) -> str:
    ""
    name = Path(filename).stem
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def infer_location(title: str) -> str:
    ""
    title_lower = title.lower().strip()
    for pattern, location in KNOWN_LOCATIONS.items():
        if pattern in title_lower:
            return location
    return ""


def parse_timestamp_to_seconds(ts: str) -> float:
    ""
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        parts = ts.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(ts)
    except (ValueError, TypeError):
        return 0.0


def extract_entities(text: str) -> dict:
    ""
    companies = {}
    people = {}

    for pattern in COMPANY_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            key = m.strip().lower()

            existing = companies.get(key, "")
            if not existing or sum(1 for c in m if c.isupper()) > sum(
                1 for c in existing if c.isupper()
            ):
                companies[key] = m.strip()

    for pattern in PERSON_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            key = m.strip().lower()
            existing = people.get(key, "")
            if not existing or sum(1 for c in m if c.isupper()) > sum(
                1 for c in existing if c.isupper()
            ):
                people[key] = m.strip()

    return {
        "companies": sorted(companies.values()),
        "people": sorted(people.values()),
    }


def extract_topics(title: str, text_preview: str) -> list[str]:
    ""
    topics = []
    combined = f"{title} {text_preview}".lower()

    topic_patterns = {
        "real-estate": r"\b(?:immobil|appartament|costruire|costruzione|hotel|ristruttur|notari|vendita)\b",
        "fundraising": r"\b(?:fundrais|investitor|raccogliere|round|safe|pre-money|valuation|capitali)\b",
        "marketing": r"\b(?:marketing|ads|campagne|brand|advertising|Meta|Google|TikTok|lead|funnel|SEO)\b",
        "sales": r"\b(?:vendita|sales|commerciale|clienti|pipeline|fatturato|ticket)\b",
        "strategy": r"\b(?:strategi|piano|obiettivo|crescita|scalare|espansione|merge|acquisiz)\b",
        "people": r"\b(?:team|assunzioni|licenziament|dipendent|coaching|formazione|leadership)\b",
        "legal": r"\b(?:contratt|avvocato|notai|preliminare|firmato|sentenza|legal)\b",
        "finance": r"\b(?:fatturato|EBITDA|revenue|budget|costi|P&L|break even|cash flow)\b",
        "events": r"\b(?:conference|expo|summit)\b",
        "investment": r"\b(?:invest|portfolio|rendimento|yield|partecipazione)\b",
        "networking": r"\b(?:partnership|collabora|intro|connessione|rete|contatto)\b",
        "product": r"\b(?:prodotto|piattaforma|app|software|UI|UX|tool|SaaS)\b",
        "personal": r"\b(?:person|privat|famigli|casa|vacanz|viaggio)\b",
    }

    for topic, pattern in topic_patterns.items():
        if re.search(pattern, combined, re.IGNORECASE):
            topics.append(topic)

    return topics[:5]





def load_all_recordings() -> list[dict]:
    ""







    log.info("Phase 1: Loading all recordings...")
    t0 = time.time()

    recordings = {}
    skipped_dupes = 0


    vm_meta = {}
    if VM_PARQUET.exists():
        df = pd.read_parquet(VM_PARQUET)
        for _, row in df.iterrows():
            vm_meta[row["slug"]] = {
                "duration_seconds": row.get("duration_seconds", 0),
                "filename": row.get("filename", ""),
            }
        log.info(f"  Loaded {len(vm_meta)} records from voice-memos.parquet")


    at_files = sorted(AT_DIR.glob("*.json")) if AT_DIR.exists() else []
    at_files = [f for f in at_files if not f.name.startswith("_")]

    for jf in at_files:
        data = load_json(jf)
        if data is None:
            continue

        source_file = data.get("source_file", jf.name)
        slug = slug_from_filename(source_file)
        metadata = data.get("metadata", {})


        raw_segments = data.get("segments", [])
        segments = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            segments.append(
                {
                    "speaker": seg.get("speaker", "UNKNOWN"),
                    "text": text,
                    "start_time": float(seg.get("start", 0)),
                    "end_time": float(seg.get("end", 0)),
                }
            )


        speakers_info = data.get("speakers", {})
        dominant_speaker = metadata.get("dominant_speaker", "")


        full_text = data.get("full_text", "")
        if not full_text:
            full_text = " ".join(s["text"] for s in segments)

        title = Path(source_file).stem
        duration = metadata.get("duration_seconds", 0)
        creation_time = metadata.get("creation_time", "")


        date_str = ""
        if creation_time:
            try:
                dt = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        recordings[slug] = {
            "recording_id": slug,
            "title": title,
            "source": "audio-transcript",
            "source_file": source_file,
            "duration_seconds": duration,
            "date": date_str,
            "creation_time": creation_time,
            "location": infer_location(title),
            "language": metadata.get("language", ""),
            "speaker_count": metadata.get("num_speakers_detected", len(speakers_info)),
            "dominant_speaker": dominant_speaker,
            "speakers_info": speakers_info,
            "segments": segments,
            "full_text": full_text,
            "has_diarization": True,
        }

    log.info(f"  Loaded {len(recordings)} audio transcripts (diarized)")


    vm_files = sorted(VM_TRANSCRIPTS_DIR.glob("*.json")) if VM_TRANSCRIPTS_DIR.exists() else []
    vm_files = [f for f in vm_files if not f.name.startswith("_")]

    vm_added = 0
    for jf in vm_files:
        data = load_json(jf)
        if data is None:
            continue

        slug = data.get("slug", slug_from_filename(jf.name))


        if slug in recordings:
            skipped_dupes += 1
            continue

        filename = data.get("filename", jf.stem + ".m4a")
        title = Path(filename).stem
        duration = data.get("duration_seconds", 0)


        if duration == 0 and slug in vm_meta:
            duration = vm_meta[slug].get("duration_seconds", 0)

        raw_segments = data.get("segments", [])
        segments = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            segments.append(
                {
                    "speaker": "SPEAKER_00",
                    "text": text,
                    "start_time": parse_timestamp_to_seconds(seg.get("start", 0)),
                    "end_time": parse_timestamp_to_seconds(seg.get("end", 0)),
                }
            )

        full_text = data.get("raw_transcript", "")
        if not full_text:
            full_text = " ".join(s["text"] for s in segments)

        recordings[slug] = {
            "recording_id": slug,
            "title": title,
            "source": "voice-memo",
            "source_file": filename,
            "duration_seconds": duration,
            "date": "",
            "creation_time": "",
            "location": infer_location(title),
            "language": "it",
            "speaker_count": 1,
            "dominant_speaker": "SPEAKER_00",
            "speakers_info": {},
            "segments": segments,
            "full_text": full_text,
            "has_diarization": False,
        }
        vm_added += 1

    elapsed = time.time() - t0
    total_segments = sum(len(r["segments"]) for r in recordings.values())
    log.info(f"  Voice memos added: {vm_added} (skipped {skipped_dupes} dupes)")
    log.info(f"  Total: {len(recordings)} recordings, {total_segments} segments in {elapsed:.1f}s")

    return list(recordings.values())





def build_recordings_index(recordings: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 2: Building recordings-index.parquet...")

    rows = []
    for r in recordings:

        word_count = sum(len(s["text"].split()) for s in r["segments"])


        text_preview = r["full_text"][:500] if r["full_text"] else ""
        topics = extract_topics(r["title"], text_preview)


        entities = extract_entities(r["title"] + " " + r["full_text"][:3000])

        rows.append(
            {
                "recording_id": r["recording_id"],
                "title": r["title"],
                "source": r["source"],
                "source_file": r["source_file"],
                "duration_seconds": round(r["duration_seconds"], 1),
                "duration_minutes": round(r["duration_seconds"] / 60, 1)
                if r["duration_seconds"]
                else 0,
                "date": r["date"],
                "location": r["location"],
                "language": r["language"],
                "word_count": word_count,
                "segment_count": len(r["segments"]),
                "speaker_count": r["speaker_count"],
                "has_diarization": r["has_diarization"],
                "topics": ", ".join(topics),
                "entities_companies": ", ".join(entities["companies"]),
                "entities_people": ", ".join(entities["people"]),
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("date", ascending=False, na_position="last", inplace=True)
    log.info(f"  Recordings index: {len(df)} records")
    return df





def build_speech_segments(recordings: list[dict]) -> pd.DataFrame:
    ""
    log.info("Phase 3: Building speech-segments.parquet...")

    rows = []
    for r in recordings:
        recording_id = r["recording_id"]
        dominant = r["dominant_speaker"]

        for seg in r["segments"]:
            speaker = seg["speaker"]




            speaker_resolved = speaker
            if not r["has_diarization"]:
                speaker_resolved = OWNER_SPEAKER
            elif speaker == dominant:
                speaker_resolved = f"{OWNER_SPEAKER} (dominant)"
            else:
                speaker_resolved = speaker

            rows.append(
                {
                    "recording_id": recording_id,
                    "speaker": speaker,
                    "speaker_resolved": speaker_resolved,
                    "text": seg["text"],
                    "start_time": round(seg["start_time"], 3),
                    "end_time": round(seg["end_time"], 3),
                    "word_count": len(seg["text"].split()),
                    "char_count": len(seg["text"]),
                }
            )

    df = pd.DataFrame(rows)
    log.info(f"  Speech segments: {len(df)} rows across {df['recording_id'].nunique()} recordings")
    return df





def build_owner_corpus(recordings: list[dict]) -> dict:
    ""







    log.info("Phase 4: Building owner speech corpus...")

    corpus_recordings = []
    total_segments = 0
    total_chars = 0

    for r in recordings:
        owner_segments = []
        dominant = r["dominant_speaker"]

        for seg in r["segments"]:
            is_owner = False

            if not r["has_diarization"]:

                is_owner = True
            elif seg["speaker"] == dominant:

                is_owner = True

            if is_owner and seg["text"]:
                owner_segments.append(
                    {
                        "text": seg["text"],
                        "start": seg["start_time"],
                        "end": seg["end_time"],
                        "chars": len(seg["text"]),
                        "words": len(seg["text"].split()),
                    }
                )

        if owner_segments:
            total_segments += len(owner_segments)
            total_chars += sum(s["chars"] for s in owner_segments)

            corpus_recordings.append(
                {
                    "recording_id": r["recording_id"],
                    "title": r["title"],
                    "date": r["date"],
                    "source": r["source"],
                    "language": r["language"],
                    "duration_seconds": round(r["duration_seconds"], 1),
                    "location": r["location"],
                    "owner_segments": len(owner_segments),
                    "owner_chars": sum(s["chars"] for s in owner_segments),
                    "segments": owner_segments,
                }
            )

    corpus = {
        "source": "voice-memos",
        "generated": datetime.now(UTC).isoformat(),
        "total_recordings": len(corpus_recordings),
        "total_segments": total_segments,
        "total_chars": total_chars,
        "total_words": sum(sum(s["words"] for s in rec["segments"]) for rec in corpus_recordings),
        "recordings": corpus_recordings,
    }

    log.info(
        f"  Owner corpus: {len(corpus_recordings)} recordings, "
        f"{total_segments} segments, {total_chars:,} chars"
    )
    return corpus





def build_summary(
    recordings: list[dict], index_df: pd.DataFrame, segments_df: pd.DataFrame, corpus: dict
) -> dict:
    ""
    log.info("Phase 5: Building _voicememos_summary.json...")


    sources = Counter(r["source"] for r in recordings)


    locations = Counter(r["location"] for r in recordings if r["location"])


    languages = Counter(r["language"] for r in recordings if r["language"])


    dates = [r["date"] for r in recordings if r["date"]]
    date_range = {"min": min(dates) if dates else "", "max": max(dates) if dates else ""}


    durations = [r["duration_seconds"] for r in recordings if r["duration_seconds"] > 0]


    diarized = sum(1 for r in recordings if r["has_diarization"])


    all_companies = Counter()
    all_people = Counter()
    for r in recordings:
        entities = extract_entities(r["title"] + " " + r["full_text"][:3000])
        for c in entities["companies"]:
            all_companies[c] += 1
        for p in entities["people"]:
            all_people[p] += 1


    all_topics = Counter()
    for r in recordings:
        text_preview = r["full_text"][:500] if r["full_text"] else ""
        topics = extract_topics(r["title"], text_preview)
        for t in topics:
            all_topics[t] += 1


    speaker_stats = {}
    if len(segments_df) > 0:
        for speaker, grp in segments_df.groupby("speaker_resolved"):
            speaker_stats[speaker] = {
                "segments": len(grp),
                "words": int(grp["word_count"].sum()),
                "chars": int(grp["char_count"].sum()),
                "recordings": int(grp["recording_id"].nunique()),
            }

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "voice-memos-enrich-v1",
        "totals": {
            "recordings": len(recordings),
            "segments": len(segments_df),
            "total_words": int(segments_df["word_count"].sum()) if len(segments_df) > 0 else 0,
            "diarized": diarized,
            "not_diarized": len(recordings) - diarized,
        },
        "date_range": date_range,
        "duration": {
            "total_hours": round(sum(durations) / 3600, 1) if durations else 0,
            "total_minutes": round(sum(durations) / 60, 1) if durations else 0,
            "avg_minutes": round(sum(durations) / len(durations) / 60, 1) if durations else 0,
            "max_minutes": round(max(durations) / 60, 1) if durations else 0,
        },
        "sources": dict(sources.most_common()),
        "locations": dict(locations.most_common()),
        "languages": dict(languages.most_common()),
        "topics": dict(all_topics.most_common()),
        "entities": {
            "top_companies": dict(all_companies.most_common(20)),
            "top_people": dict(all_people.most_common(20)),
        },
        "speakers": speaker_stats,
        "owner_corpus": {
            "recordings": corpus["total_recordings"],
            "segments": corpus["total_segments"],
            "chars": corpus["total_chars"],
            "words": corpus["total_words"],
        },
    }

    return summary




STEP_NAMES = ["index", "segments", "corpus", "summary"]


def main():
    parser = argparse.ArgumentParser(
        description="Voice Memos + Audio Transcripts enrichment pipeline — SBK L1"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--step", default=None, choices=STEP_NAMES, help="Run single step (default: all)"
    )
    parser.add_argument("--incremental", action="store_true", help="Skip if inputs unchanged")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.incremental:
        from sbk_config import check_inputs_changed

        if not check_inputs_changed("vm-l1", [VM_TRANSCRIPTS_DIR, AT_DIR]):
            log.info("Incremental: inputs unchanged — skipping")
            mark_last_run("vm-l1")
            return


    vm_exists = VM_TRANSCRIPTS_DIR.exists() and any(VM_TRANSCRIPTS_DIR.glob("*.json"))
    at_exists = AT_DIR.exists() and any(
        f for f in AT_DIR.glob("*.json") if not f.name.startswith("_")
    )

    if not vm_exists and not at_exists:
        log.error("No source data found.")
        log.error(f"  Checked: {VM_TRANSCRIPTS_DIR}")
        log.error(f"  Checked: {AT_DIR}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    recordings = load_all_recordings()

    if not recordings:
        log.error("No recordings loaded. Check source directories.")
        sys.exit(1)

    steps_to_run = [args.step] if args.step else STEP_NAMES

    index_df = None
    segments_df = None
    corpus = None


    if "index" in steps_to_run:
        index_df = build_recordings_index(recordings)
        if not args.dry_run:
            out = PROCESSED_DIR / "recordings-index.parquet"
            safe_write_parquet(index_df, out, index=False)
            log.info(f"  Saved -> {out}")


    if "segments" in steps_to_run:
        segments_df = build_speech_segments(recordings)
        if not args.dry_run:
            out = PROCESSED_DIR / "speech-segments.parquet"
            safe_write_parquet(segments_df, out, index=False)
            log.info(f"  Saved -> {out}")


    if "corpus" in steps_to_run:
        corpus = build_owner_corpus(recordings)
        if not args.dry_run:
            out = PROCESSED_DIR / "owner-speech-corpus-voicememos.json"
            out.write_text(json.dumps(corpus, ensure_ascii=False, indent=2))
            log.info(f"  Saved -> {out}")


    if "summary" in steps_to_run:
        if index_df is None:
            index_df = build_recordings_index(recordings)
        if segments_df is None:
            segments_df = build_speech_segments(recordings)
        if corpus is None:
            corpus = build_owner_corpus(recordings)

        summary = build_summary(recordings, index_df, segments_df, corpus)

        if args.dry_run:
            log.info("\n=== DRY RUN — Summary ===")
            log.info(json.dumps(summary, indent=2))
        else:
            out = PROCESSED_DIR / "_voicememos_summary.json"
            out.write_text(json.dumps(summary, indent=2, default=str))
            log.info(f"  Saved -> {out}")

    if not args.dry_run:
        from sbk_config import save_input_checkpoint

        save_input_checkpoint("vm-l1", [VM_TRANSCRIPTS_DIR, AT_DIR])
        mark_last_run("vm-l1")


    log.info("\n" + "=" * 60)
    log.info("VOICE MEMOS ENRICHMENT COMPLETE")
    log.info("=" * 60)
    if index_df is not None:
        log.info(f"  Recordings:   {len(index_df)}")
        diarized = index_df["has_diarization"].sum()
        log.info(f"  Diarized:     {diarized}/{len(index_df)}")
    if segments_df is not None:
        log.info(f"  Segments:     {len(segments_df)}")
        log.info(f"  Total words:  {segments_df['word_count'].sum():,}")
    if corpus is not None:
        log.info(
            f"  Corpus:       {corpus['total_segments']} segments, {corpus['total_chars']:,} chars"
        )
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-voice-memos-enrich", source="vm-l1", stage="l1", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
