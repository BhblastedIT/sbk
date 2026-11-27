#!/usr/bin/env python3
"""WhatsApp extra: transcribe the voice notes of your chats on your machine (whisper.cpp).

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Needs whisper-cli and the model file ~/whisper-models/ggml-large-v3-turbo.bin, language detected
automatically. --attachments-dir is required: the folder of your exported attachments (one sub-folder
per chat, as for wa-l0-import-history.py); there is no default folder. Nothing is sent anywhere.
Output: <data root>/whatsapp/transcriptions/. Then wa-l1-inject-transcripts.py puts the text into the chats.
It transcribes only the voice notes of your --top contacts (default 75), ranked by the relationship
scores of a later pipeline stage (<data root>/rq/composite-scores-v3.parquet): without that file it
stops, even with --dry-run.

    uv run python tools/whatsapp/wa-l1-transcribe-audio.py --attachments-dir <folder> --dry-run
    uv run python tools/whatsapp/wa-l1-transcribe-audio.py --attachments-dir <folder> --workers 4
"""





























from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow")
    sys.exit(1)

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, ENRICHED_DIR



WHATSAPP_DATA_DIR = DATA_ROOT / "whatsapp"
TRANSCRIPTIONS_DIR = WHATSAPP_DATA_DIR / "transcriptions"
PLAN_FILE = WHATSAPP_DATA_DIR / "transcription-plan.json"
SUMMARY_FILE = TRANSCRIPTIONS_DIR / "_transcription_summary.json"
WHISPER_MODEL = str(Path.home() / "whisper-models" / "ggml-large-v3-turbo.bin")
RQ_SCORES_FILE = DATA_ROOT / "rq" / "composite-scores-v3.parquet"
CONTACTS_MERGED_FILE = ENRICHED_DIR / "contacts-merged.parquet"
NAME_MATCHING_INDEX = DATA_ROOT / "rq" / "name-matching-index.json"

AUDIO_EXTENSIONS = {".opus", ".m4a", ".mp3", ".ogg", ".wav"}

FILE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2} \d{2} \d{2})"
    r" - "
    r"(.+?)"
    r" - "
    r"[a-f0-9\-]+"
    r"\.(opus|m4a|mp3|ogg|wav)$",
    re.IGNORECASE,
)

FOLDER_PATTERN = re.compile(r"^WhatsApp - (.+)$")

DEFAULT_TOP = 75
DEFAULT_WORKERS = 6
BLOCK_SIZE = 50

log = logging.getLogger("wa-transcribe")





def slugify(name: str) -> str:
    ""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
    return slug or "unknown"


def parse_filename(filename: str) -> dict | None:
    ""
    m = FILE_PATTERN.match(filename)
    if not m:
        return None
    ts_str, sender, ext = m.groups()
    try:
        timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H %M %S")
    except ValueError:
        return None
    return {
        "timestamp": timestamp,
        "timestamp_str": ts_str,
        "sender": sender,
        "extension": ext.lower(),
    }


def get_duration(path: str) -> float:
    ""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def normalize_for_match(name: str) -> str:
    ""
    name = name.lower().strip()

    name = re.sub(r"^whatsapp\s*-\s*", "", name)

    name = re.sub(r"[^a-z\s]", "", name)

    name = re.sub(r"\s+", " ", name).strip()
    return name


def fuzzy_name_match(folder_name: str, candidates: list[str]) -> str | None:
    ""





    norm_folder = normalize_for_match(folder_name)
    folder_tokens = set(norm_folder.split())

    best_match = None
    best_score = 0

    for candidate in candidates:
        norm_cand = normalize_for_match(candidate)
        cand_tokens = set(norm_cand.split())


        if not norm_cand or not norm_folder:
            continue


        if norm_folder == norm_cand:
            return candidate


        if norm_folder in norm_cand or norm_cand in norm_folder:
            score = min(len(norm_folder), len(norm_cand)) / max(len(norm_folder), len(norm_cand))
            if score > best_score:
                best_score = score
                best_match = candidate
            continue


        common = folder_tokens & cand_tokens
        if len(common) >= 2:

            score = len(common) / len(folder_tokens | cand_tokens)
            if score > best_score:
                best_score = score
                best_match = candidate


    if best_score >= 0.4:
        return best_match
    return None





def build_pid_to_name_map() -> dict[str, str]:
    ""



    pid_map: dict[str, str] = {}


    if CONTACTS_MERGED_FILE.exists():
        try:
            cm = pd.read_parquet(CONTACTS_MERGED_FILE, columns=["person_id", "name"])
            for _, row in cm.iterrows():
                pid = row.get("person_id", "")
                name = row.get("name", "")
                if pid and name and isinstance(name, str) and len(name) > 1:
                    pid_map[pid] = name
        except Exception as e:
            log.warning("Failed to read contacts-merged: %s", e)


    if NAME_MATCHING_INDEX.exists():
        try:
            idx = json.loads(NAME_MATCHING_INDEX.read_text())
            matches = idx.get("matches", {})
            for name, info in matches.items():
                pid = info.get("person_id", "")
                if pid and pid not in pid_map:

                    pid_map[pid] = name
                elif pid and pid in pid_map:

                    if len(name) > len(pid_map[pid]):
                        pid_map[pid] = name
        except Exception as e:
            log.warning("Failed to read name-matching-index: %s", e)

    return pid_map


def load_top_contacts(top_n: int) -> list[str]:
    ""




    if not RQ_SCORES_FILE.exists():
        log.error("RQ scores not found: %s", RQ_SCORES_FILE)
        sys.exit(1)

    df = pd.read_parquet(RQ_SCORES_FILE)

    df = df[df["person"].str.len() > 2].copy()

    df = df.nlargest(top_n, "score_v3")


    pid_map = build_pid_to_name_map()

    names = []
    unresolved = 0
    for _, row in df.iterrows():
        pid = row["person"]
        if pid.startswith("p_"):
            resolved = pid_map.get(pid)
            if resolved:
                names.append(resolved)
            else:
                unresolved += 1
                log.debug("Unresolved person_id: %s (score=%.1f)", pid, row["score_v3"])
        else:

            names.append(pid)

    if unresolved:
        log.warning(
            "%d of top %d contacts could not be resolved to names (skipped)",
            unresolved,
            top_n,
        )

    log.info(
        "Loaded %d contacts from RQ scores (score range: %.1f - %.1f)",
        len(names),
        df["score_v3"].min(),
        df["score_v3"].max(),
    )
    return names


def discover_audio_files(
    attachments_dir: Path,
    top_contacts: list[str],
    person_filter: str | None = None,
) -> dict[str, list[dict]]:
    ""



    log.info("Scanning %s ...", attachments_dir)


    folder_to_person: dict[str, str] = {}
    unmatched_folders: list[str] = []

    for entry in sorted(attachments_dir.iterdir()):
        if not entry.is_dir():
            continue
        m = FOLDER_PATTERN.match(entry.name)
        if not m:
            continue
        contact_name = m.group(1)


        if person_filter:
            if person_filter.lower() not in contact_name.lower():
                continue

        matched = fuzzy_name_match(contact_name, top_contacts)
        if matched:
            folder_to_person[entry.name] = matched
        else:
            unmatched_folders.append(contact_name)

    log.info(
        "Matched %d folders to top contacts (%d unmatched)",
        len(folder_to_person),
        len(unmatched_folders),
    )


    person_files: dict[str, list[dict]] = defaultdict(list)
    total_scanned = 0
    total_audio = 0

    for folder_name, person_name in sorted(folder_to_person.items()):
        folder_path = attachments_dir / folder_name
        for f in sorted(folder_path.iterdir()):
            if not f.is_file():
                continue
            total_scanned += 1
            if f.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            parsed = parse_filename(f.name)
            if not parsed:

                person_files[person_name].append(
                    {
                        "path": str(f),
                        "timestamp": None,
                        "timestamp_str": "",
                        "sender": person_name,
                        "extension": f.suffix.lower().lstrip("."),
                    }
                )
                total_audio += 1
                continue

            person_files[person_name].append(
                {
                    "path": str(f),
                    "timestamp": parsed["timestamp"].isoformat(),
                    "timestamp_str": parsed["timestamp_str"],
                    "sender": parsed["sender"],
                    "extension": parsed["extension"],
                }
            )
            total_audio += 1

    log.info(
        "Found %d audio files across %d people (scanned %d total files)",
        total_audio,
        len(person_files),
        total_scanned,
    )

    return dict(person_files)


def dedup_audio_files(person_files: dict[str, list[dict]]) -> dict[str, list[dict]]:
    ""



    FORMAT_PRIORITY = {"m4a": 0, "opus": 1, "mp3": 2, "ogg": 3, "wav": 4}
    total_before = sum(len(files) for files in person_files.values())
    total_removed = 0

    deduped: dict[str, list[dict]] = {}
    for person, files in person_files.items():

        by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for f in files:
            key = (f["timestamp_str"], f["sender"])
            by_key[key].append(f)

        unique = []
        for key, group in by_key.items():
            if len(group) == 1:
                unique.append(group[0])
            else:

                group.sort(key=lambda x: FORMAT_PRIORITY.get(x["extension"], 9))
                unique.append(group[0])
                total_removed += len(group) - 1


        unique.sort(key=lambda x: x.get("timestamp") or "")
        deduped[person] = unique

    total_after = sum(len(files) for files in deduped.values())
    log.info(
        "Dedup: %d -> %d files (%d duplicates removed)",
        total_before,
        total_after,
        total_removed,
    )
    return deduped





def create_plan(
    person_files: dict[str, list[dict]],
    block_size: int = BLOCK_SIZE,
) -> dict:
    ""
    blocks = []
    block_id = 0

    for person in sorted(person_files.keys()):
        files = person_files[person]

        for i in range(0, len(files), block_size):
            chunk = files[i : i + block_size]
            blocks.append(
                {
                    "id": block_id,
                    "person": person,
                    "files": [f["path"] for f in chunk],
                    "file_count": len(chunk),
                    "status": "pending",
                    "completed_at": None,
                    "error": None,
                }
            )
            block_id += 1

    total_files = sum(len(files) for files in person_files.values())
    plan = {
        "created_at": datetime.now().isoformat(),
        "total_files": total_files,
        "total_blocks": len(blocks),
        "total_people": len(person_files),
        "block_size": block_size,
        "blocks": blocks,
    }
    return plan


def save_plan(plan: dict) -> None:
    ""
    PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    log.info("Plan saved to %s", PLAN_FILE)


def load_plan() -> dict | None:
    ""
    if not PLAN_FILE.exists():
        return None
    try:
        return json.loads(PLAN_FILE.read_text())
    except Exception as e:
        log.error("Failed to load plan: %s", e)
        return None


def print_plan_summary(plan: dict) -> None:
    ""
    pending = sum(1 for b in plan["blocks"] if b["status"] == "pending")
    completed = sum(1 for b in plan["blocks"] if b["status"] == "completed")
    failed = sum(1 for b in plan["blocks"] if b["status"] == "failed")

    pending_files = sum(b["file_count"] for b in plan["blocks"] if b["status"] == "pending")
    completed_files = sum(b["file_count"] for b in plan["blocks"] if b["status"] == "completed")

    log.info("TRANSCRIPTION PLAN")
    log.info("  People:      %d", plan["total_people"])
    log.info("  Total files: %d", plan["total_files"])
    log.info("  Blocks:      %d (size=%d)", plan["total_blocks"], plan["block_size"])
    log.info("  Status:      %d completed, %d pending, %d failed", completed, pending, failed)
    log.info("  Files:       %d done, %d remaining", completed_files, pending_files)


    person_blocks: dict[str, dict] = defaultdict(lambda: {"total": 0, "pending": 0, "files": 0})
    for b in plan["blocks"]:
        p = person_blocks[b["person"]]
        p["total"] += 1
        p["files"] += b["file_count"]
        if b["status"] == "pending":
            p["pending"] += b["file_count"]

    log.info("  %-35s %6s %8s %7s", "Person", "Files", "Pending", "Blocks")
    for person in sorted(person_blocks.keys()):
        info = person_blocks[person]
        log.info("  %-35s %6d %8d %7d", person, info["files"], info["pending"], info["total"])





def transcribe_one_file(args: tuple[str, str, str, str]) -> dict:
    ""




    audio_path_str, chat_slug, person_name, model_path = args
    audio_path = Path(audio_path_str)
    out_dir = TRANSCRIPTIONS_DIR / chat_slug  # follows SBK_DATA_ROOT, like the summary file
    out_json = out_dir / f"{audio_path.stem}.json"


    if out_json.exists():
        try:
            existing = json.loads(out_json.read_text())
            if existing.get("text") is not None:
                return {
                    "path": audio_path_str,
                    "status": "skipped",
                    "word_count": existing.get("word_count", 0),
                    "duration_seconds": existing.get("duration_seconds", 0),
                }
        except Exception:
            pass


    parsed = None
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2} \d{2} \d{2} \d{2}) - (.+?) - [a-f0-9\-]+\.\w+$",
        audio_path.name,
        re.IGNORECASE,
    )
    if m:
        ts_str, sender = m.group(1), m.group(2)
        try:
            timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H %M %S")
        except ValueError:
            timestamp = None
            ts_str = ""
    else:
        sender = person_name
        timestamp = None
        ts_str = ""

    t0 = time.time()


    duration = get_duration(audio_path_str)


    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path_str, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0 or not Path(wav_path).exists():
            Path(wav_path).unlink(missing_ok=True)
            return {
                "path": audio_path_str,
                "status": "ffmpeg_failed",
                "error": result.stderr.decode(errors="replace")[-200:] if result.stderr else "",
            }
    except subprocess.TimeoutExpired:
        Path(wav_path).unlink(missing_ok=True)
        return {"path": audio_path_str, "status": "ffmpeg_timeout"}
    except Exception as e:
        Path(wav_path).unlink(missing_ok=True)
        return {"path": audio_path_str, "status": "ffmpeg_error", "error": str(e)}


    try:
        r = subprocess.run(
            [
                "whisper-cli",
                "-m",
                model_path,
                "-l",
                "auto",
                "-t",
                "2",
                "-f",
                wav_path,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        Path(wav_path).unlink(missing_ok=True)
        return {"path": audio_path_str, "status": "whisper_timeout"}
    except Exception as e:
        Path(wav_path).unlink(missing_ok=True)
        return {"path": audio_path_str, "status": "whisper_error", "error": str(e)}

    Path(wav_path).unlink(missing_ok=True)


    seg_pattern = re.compile(
        r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)"
    )
    segments = []
    for line in output.splitlines():
        sm = seg_pattern.match(line.strip())
        if sm:
            start_str, end_str, text = sm.groups()
            text = text.strip()
            if text:
                segments.append({"start": start_str, "end": end_str, "text": text})

    full_text = " ".join(s["text"] for s in segments)
    word_count = len(full_text.split()) if full_text else 0


    language = "auto"
    lang_match = re.search(r"auto-detected language:\s*(\w+)", output, re.IGNORECASE)
    if lang_match:
        language = lang_match.group(1).lower()

    elapsed = time.time() - t0


    transcription = {
        "source_file": audio_path_str,
        "chat": person_name,
        "sender": sender,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "duration_seconds": round(duration, 2),
        "language": language,
        "text": full_text,
        "word_count": word_count,
        "segments": segments,
        "transcribed_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
    }


    out_dir.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(transcription, indent=2, ensure_ascii=False))

    return {
        "path": audio_path_str,
        "status": "done",
        "word_count": word_count,
        "duration_seconds": round(duration, 2),
        "language": language,
        "elapsed": round(elapsed, 1),
    }


def transcribe_blocks(
    plan: dict,
    workers: int = DEFAULT_WORKERS,
    block_filter: int | None = None,
) -> None:
    ""
    pending_blocks = [
        b
        for b in plan["blocks"]
        if b["status"] == "pending" and (block_filter is None or b["id"] == block_filter)
    ]

    if not pending_blocks:
        log.info("No pending blocks to transcribe.")
        return

    total_files = sum(b["file_count"] for b in pending_blocks)
    log.info(
        "Transcribing %d blocks (%d files) with %d workers",
        len(pending_blocks),
        total_files,
        workers,
    )

    global_done = 0
    global_skipped = 0
    global_errors = 0
    global_t0 = time.time()

    for block in pending_blocks:
        block_id = block["id"]
        person = block["person"]
        chat_slug = slugify(person)
        files = block["files"]

        log.info(
            "Block %d: %s (%d files)",
            block_id,
            person,
            len(files),
        )

        block_results = []
        block_errors = 0


        work_items = [(f, chat_slug, person, WHISPER_MODEL) for f in files]

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(transcribe_one_file, item): item[0] for item in work_items}
            for future in as_completed(futures):
                fname = Path(futures[future]).name
                try:
                    result = future.result()
                    status = result.get("status", "?")
                    if status == "skipped":
                        global_skipped += 1
                        log.debug("  %s: skipped", fname)
                    elif status == "done":
                        global_done += 1
                        log.info(
                            "  [%d] %s: %d words, %.1fs audio, %.1fs elapsed, lang=%s",
                            global_done + global_skipped,
                            fname,
                            result.get("word_count", 0),
                            result.get("duration_seconds", 0),
                            result.get("elapsed", 0),
                            result.get("language", "?"),
                        )
                    else:
                        global_errors += 1
                        block_errors += 1
                        log.error(
                            "  %s: %s — %s",
                            fname,
                            status,
                            result.get("error", "")[:100],
                        )
                    block_results.append(result)
                except Exception as e:
                    global_errors += 1
                    block_errors += 1
                    log.error("  %s: worker exception: %s", fname, e)


        if block_errors == 0:
            block["status"] = "completed"
            block["completed_at"] = datetime.now().isoformat()
        elif block_errors < len(files):
            block["status"] = "completed"
            block["completed_at"] = datetime.now().isoformat()
            block["error"] = f"{block_errors} files failed"
        else:
            block["status"] = "failed"
            block["error"] = f"All {block_errors} files failed"


        save_plan(plan)
        log.info(
            "Block %d: %s (%d done, %d skipped, %d errors)",
            block_id,
            block["status"],
            len([r for r in block_results if r.get("status") == "done"]),
            len([r for r in block_results if r.get("status") == "skipped"]),
            block_errors,
        )

    elapsed = time.time() - global_t0
    log.info(
        "All done in %.0fs: %d transcribed, %d skipped, %d errors",
        elapsed,
        global_done,
        global_skipped,
        global_errors,
    )





def generate_summary() -> dict:
    ""
    if not TRANSCRIPTIONS_DIR.exists():
        return {}

    summary: dict[str, dict] = {}

    for chat_dir in sorted(TRANSCRIPTIONS_DIR.iterdir()):
        if not chat_dir.is_dir():
            continue
        if chat_dir.name.startswith("_"):
            continue

        person_stats = {
            "chat_slug": chat_dir.name,
            "files_transcribed": 0,
            "total_duration_seconds": 0.0,
            "total_words": 0,
            "languages": defaultdict(int),
            "earliest": None,
            "latest": None,
        }

        for json_file in sorted(chat_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
            except Exception:
                continue

            person_stats["files_transcribed"] += 1
            person_stats["total_duration_seconds"] += data.get("duration_seconds", 0)
            person_stats["total_words"] += data.get("word_count", 0)

            lang = data.get("language", "unknown")
            person_stats["languages"][lang] += 1

            ts = data.get("timestamp")
            if ts:
                if person_stats["earliest"] is None or ts < person_stats["earliest"]:
                    person_stats["earliest"] = ts
                if person_stats["latest"] is None or ts > person_stats["latest"]:
                    person_stats["latest"] = ts

        if person_stats["files_transcribed"] > 0:

            lang_counts = person_stats["languages"]
            person_stats["dominant_language"] = (
                max(lang_counts, key=lang_counts.get) if lang_counts else "unknown"
            )
            person_stats["languages"] = dict(lang_counts)
            person_stats["total_duration_minutes"] = round(
                person_stats["total_duration_seconds"] / 60, 1
            )

            chat_name = chat_dir.name
            for json_file in chat_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text())
                    if data.get("chat"):
                        chat_name = data["chat"]
                        break
                except Exception:
                    continue
            summary[chat_name] = person_stats


    TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    full_summary = {
        "generated_at": datetime.now().isoformat(),
        "total_people": len(summary),
        "total_files": sum(s["files_transcribed"] for s in summary.values()),
        "total_duration_minutes": round(
            sum(s["total_duration_seconds"] for s in summary.values()) / 60, 1
        ),
        "total_words": sum(s["total_words"] for s in summary.values()),
        "people": summary,
    }
    SUMMARY_FILE.write_text(json.dumps(full_summary, indent=2, ensure_ascii=False))
    log.info("Summary saved to %s", SUMMARY_FILE)

    return full_summary





def check_dependencies() -> bool:
    ""
    ok = True
    for cmd in ["whisper-cli", "ffmpeg", "ffprobe"]:
        try:
            subprocess.run([cmd, "--help"], capture_output=True, timeout=5)
        except FileNotFoundError:
            log.error("Required command not found: %s", cmd)
            ok = False
        except Exception:
            pass
    if not Path(WHISPER_MODEL).exists():
        log.error("Whisper model not found: %s", WHISPER_MODEL)
        ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description="WhatsApp Audio Transcription — SBK L1")
    parser.add_argument(
        "--attachments-dir",
        type=str,
        default=None,
        help="The folder of your exported WhatsApp attachments, one sub-folder per chat "
        "(required, except with --resume)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Top N contacts by RQ score (default: {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from saved plan (skip discovery)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without transcribing",
    )
    parser.add_argument(
        "--person",
        type=str,
        default=None,
        help='Filter to one person (substring match, e.g. "Mario")',
    )
    parser.add_argument(
        "--block",
        type=int,
        default=None,
        help="Transcribe only a specific block ID",
    )
    args = parser.parse_args()
    if not args.resume and not args.attachments_dir:
        parser.error("--attachments-dir is required: the folder of your exported WhatsApp attachments")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    if not args.dry_run:
        if not check_dependencies():
            log.error("Missing dependencies, aborting.")
            sys.exit(1)


    if args.resume:
        plan = load_plan()
        if not plan:
            log.error("No saved plan found at %s. Run without --resume first.", PLAN_FILE)
            sys.exit(1)
        log.info(
            "Loaded existing plan: %d blocks, %d files", plan["total_blocks"], plan["total_files"]
        )

        if args.dry_run:
            print_plan_summary(plan)
            return

        transcribe_blocks(plan, workers=args.workers, block_filter=args.block)
        summary = generate_summary()
        print(
            f"\nSummary: {summary.get('total_people', 0)} people, "
            f"{summary.get('total_files', 0)} files, "
            f"{summary.get('total_duration_minutes', 0)} min, "
            f"{summary.get('total_words', 0)} words"
        )
        return


    attachments_dir = Path(args.attachments_dir)
    if not attachments_dir.exists():
        log.error("Attachments directory not found: %s", attachments_dir)
        sys.exit(1)


    log.info("Phase 1: Discover & Filter (top %d contacts)", args.top)
    top_contacts = load_top_contacts(args.top)
    person_files = discover_audio_files(attachments_dir, top_contacts, person_filter=args.person)

    if not person_files:
        log.warning("No audio files found for top contacts.")
        return


    person_files = dedup_audio_files(person_files)


    log.info("Phase 2: Block Planning")
    plan = create_plan(person_files)
    save_plan(plan)
    print_plan_summary(plan)

    if args.dry_run:
        log.info("Dry run complete. Plan saved to %s", PLAN_FILE)
        return


    log.info("Phase 3: Transcribe")
    transcribe_blocks(plan, workers=args.workers, block_filter=args.block)


    log.info("Phase 4: Summary")
    summary = generate_summary()
    print(
        f"\nSummary: {summary.get('total_people', 0)} people, "
        f"{summary.get('total_files', 0)} files, "
        f"{summary.get('total_duration_minutes', 0)} min, "
        f"{summary.get('total_words', 0)} words"
    )


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-whatsapp-transcribe-audio", source="wa-l1-audio", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
