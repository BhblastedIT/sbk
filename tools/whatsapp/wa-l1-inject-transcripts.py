#!/usr/bin/env python3
"""WhatsApp extra: write the voice-note transcripts into the chat files, next to the message of each audio.

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Run it after wa-l1-transcribe-audio.py and before wa-l1-enrich.py. Matches each transcript to its
message by the audio file name, else by time (within 2 seconds). Edits <data root>/whatsapp/chats/*.json
in place. With no transcriptions folder it does nothing.

    uv run python tools/whatsapp/wa-l1-inject-transcripts.py --dry-run
    uv run python tools/whatsapp/wa-l1-inject-transcripts.py
"""

























from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT  # noqa: E402

CHATS_DIR = DATA_ROOT / "whatsapp" / "chats"
TRANSCRIPTIONS_DIR = DATA_ROOT / "whatsapp" / "transcriptions"

log = logging.getLogger("wa-inject-transcripts")

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NUMBERED_RE = re.compile(r"(\d{8}-AUDIO-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})")





def build_slug_to_chat_map() -> dict[str, Path]:
    ""






    chat_files = {
        f.stem: f
        for f in sorted(CHATS_DIR.glob("*.json"))
        if not f.name.startswith("_") and f.name != "chats-index.json"
    }

    slug_map: dict[str, Path] = {}

    for d in sorted(TRANSCRIPTIONS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        slug = d.name


        if slug in ("standalone-audio", "voice-memos"):
            continue


        if slug in chat_files:
            slug_map[slug] = chat_files[slug]
            continue


        if f"grp-{slug}" in chat_files:
            slug_map[slug] = chat_files[f"grp-{slug}"]
            continue


        slug_clean = slug.replace("-", "")
        for stem, path in chat_files.items():
            stem_clean = stem.replace("-", "")
            if slug_clean in stem_clean or stem_clean in slug_clean:
                slug_map[slug] = path
                break
        else:
            log.warning(f"No chat file found for transcript dir: {slug}")

    return slug_map





def load_transcripts_for_slug(slug: str) -> list[dict]:
    ""











    t_dir = TRANSCRIPTIONS_DIR / slug
    if not t_dir.is_dir():
        return []

    transcripts = []
    for f in sorted(t_dir.glob("*.json")):

        if ".error." in f.name or f.name.startswith("_"):
            continue

        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning(f"Cannot parse transcript {f}: {e}")
            continue

        text = data.get("text", "").strip()
        if not text:
            continue


        uuid_match = UUID_RE.search(f.stem)
        numbered_match = NUMBERED_RE.search(f.stem)

        transcripts.append(
            {
                "uuid": uuid_match.group(0) if uuid_match else None,
                "numbered_filename": numbered_match.group(1) if numbered_match else None,
                "timestamp": data.get("timestamp", ""),
                "text": text,
                "duration_seconds": data.get("duration_seconds", 0),
                "language": data.get("language", ""),
                "word_count": data.get("word_count", 0),
                "sender": data.get("sender", ""),
            }
        )

    return transcripts





def _parse_ts(ts_str: str) -> datetime | None:
    ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def inject_transcripts_into_chat(chat_data: dict, transcripts: list[dict]) -> tuple[int, int]:
    ""



    messages = chat_data.get("messages", [])
    if not messages or not transcripts:
        return 0, 0



    uuid_to_msg_idx: dict[str, int] = {}

    numbered_to_msg_idx: dict[str, int] = {}

    ts_to_msg_indices: dict[str, list[int]] = {}

    for i, msg in enumerate(messages):
        text = msg.get("text", "")


        uuid_match = UUID_RE.search(text)
        if uuid_match:
            uuid_to_msg_idx[uuid_match.group(0)] = i


        numbered_match = NUMBERED_RE.search(text)
        if numbered_match:
            numbered_to_msg_idx[numbered_match.group(1)] = i


        ts = msg.get("timestamp", "")
        if ts:
            ts_to_msg_indices.setdefault(ts, []).append(i)

    matched = 0
    already_had = 0

    for t in transcripts:
        msg_idx = None


        if t["uuid"] and t["uuid"] in uuid_to_msg_idx:
            msg_idx = uuid_to_msg_idx[t["uuid"]]


        if msg_idx is None and t["numbered_filename"]:
            if t["numbered_filename"] in numbered_to_msg_idx:
                msg_idx = numbered_to_msg_idx[t["numbered_filename"]]


        if msg_idx is None and t["timestamp"]:
            ts_str = t["timestamp"]
            if ts_str in ts_to_msg_indices:

                for idx in ts_to_msg_indices[ts_str]:
                    msg_text = messages[idx].get("text", "")
                    if ".opus" in msg_text or ".m4a" in msg_text or "(Audio)" in msg_text:
                        msg_idx = idx
                        break


        if msg_idx is None and t["timestamp"]:
            t_dt = _parse_ts(t["timestamp"])
            if t_dt:
                best_delta = 3
                for ts_str, indices in ts_to_msg_indices.items():
                    m_dt = _parse_ts(ts_str)
                    if m_dt:
                        delta = abs((t_dt - m_dt).total_seconds())
                        if delta < best_delta:
                            for idx in indices:
                                msg_text = messages[idx].get("text", "")
                                if (
                                    ".opus" in msg_text
                                    or ".m4a" in msg_text
                                    or "(Audio)" in msg_text
                                    or "<attached:" in msg_text
                                ):
                                    msg_idx = idx
                                    best_delta = delta
                                    break

        if msg_idx is not None:
            msg = messages[msg_idx]
            if "transcription" in msg:
                already_had += 1
                continue

            msg["transcription"] = {
                "text": t["text"],
                "duration_seconds": t["duration_seconds"],
                "language": t["language"],
                "word_count": t["word_count"],
            }
            matched += 1

    return matched, already_had





def main():
    parser = argparse.ArgumentParser(
        description="Inject audio transcripts into WhatsApp chat JSONs (DPI-01)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show stats without modifying files")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.time()

    if not TRANSCRIPTIONS_DIR.is_dir():
        log.info(f"No transcriptions yet ({TRANSCRIPTIONS_DIR} does not exist): nothing to inject.")
        return

    slug_map = build_slug_to_chat_map()
    log.info(f"Transcript dirs mapped to chat files: {len(slug_map)}")


    total_transcripts = 0
    total_matched = 0
    total_already = 0
    total_unmatched = 0
    chats_updated = 0
    per_chat_stats: list[dict] = []

    for slug, chat_path in sorted(slug_map.items()):

        transcripts = load_transcripts_for_slug(slug)
        if not transcripts:
            continue

        total_transcripts += len(transcripts)


        try:
            chat_data = json.loads(chat_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning(f"Cannot parse chat {chat_path.name}: {e}")
            total_unmatched += len(transcripts)
            continue


        matched, already = inject_transcripts_into_chat(chat_data, transcripts)
        unmatched = len(transcripts) - matched - already

        total_matched += matched
        total_already += already
        total_unmatched += unmatched

        if matched > 0:
            chats_updated += 1
            if not args.dry_run:
                chat_path.write_text(
                    json.dumps(chat_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        log_level = logging.INFO if matched > 0 else logging.DEBUG
        log.log(
            log_level,
            f"  {slug}: {matched} injected, {already} already, {unmatched} unmatched "
            f"(of {len(transcripts)} transcripts)",
        )

        per_chat_stats.append(
            {
                "chat_slug": slug,
                "chat_file": chat_path.name,
                "transcripts": len(transcripts),
                "matched": matched,
                "already_had": already,
                "unmatched": unmatched,
            }
        )

    elapsed = time.time() - t0


    stats = {
        "total_transcripts": total_transcripts,
        "matched": total_matched,
        "already_had": total_already,
        "unmatched": total_unmatched,
        "chats_updated": chats_updated,
        "chats_processed": len(slug_map),
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "per_chat": per_chat_stats,
    }

    if not args.dry_run:
        stats_path = TRANSCRIPTIONS_DIR / "_inject-stats.json"
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"Stats saved: {stats_path}")


    mode = "DRY RUN" if args.dry_run else "DONE"
    log.info("")
    log.info(f"=== {mode} ===")
    log.info(f"  Total transcripts: {total_transcripts}")
    log.info(f"  Matched & injected: {total_matched}")
    log.info(f"  Already injected: {total_already}")
    log.info(f"  Unmatched: {total_unmatched}")
    log.info(f"  Chats updated: {chats_updated} / {len(slug_map)}")
    log.info(f"  Elapsed: {elapsed:.1f}s")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-whatsapp-inject-transcripts", source="wa-l1-transcripts", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
