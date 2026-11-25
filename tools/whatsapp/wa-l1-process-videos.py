#!/usr/bin/env python3
"""WhatsApp extra: transcribe the audio of the videos in your chats and save a few keyframes.

Status: extra step, NOT SET UP OR TESTED BY THE AUTHOR. The WhatsApp path the author uses is
the chat export plus the import (wa-l0l3-full.py, wa-l0-import-history.py, then
wa-l1-enrich.py). Live reading of WhatsApp is not set up.

Without --process it only counts the videos. With --process it uses whisper on your machine (the
openai-whisper Python package, or whisper-cli) and ffmpeg for the keyframes. Nothing is sent anywhere.
Output: <data root>/whatsapp/videos/.

    uv run python tools/whatsapp/wa-l1-process-videos.py              # count only
    uv run python tools/whatsapp/wa-l1-process-videos.py --process --skip-keyframes
"""











from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-wa-l1-process-videos")

CHATS_DIR = DATA_ROOT / "whatsapp" / "chats"
EXTRA_DIR = DATA_ROOT / "whatsapp" / "downloads-extra"
VIDEOS_OUTPUT_DIR = DATA_ROOT / "whatsapp" / "videos"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".3gp", ".avi", ".mkv"}


def find_all_videos() -> list[dict]:
    ""
    videos: list[dict] = []


    if CHATS_DIR.exists():
        for chat_dir in sorted(CHATS_DIR.iterdir()):
            media_dir = chat_dir / "media"
            if not media_dir.exists():
                continue
            chat_slug = chat_dir.name
            for f in sorted(media_dir.iterdir()):
                if f.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(
                        {
                            "path": str(f),
                            "chat_slug": chat_slug,
                            "filename": f.name,
                            "size_mb": f.stat().st_size / (1024 * 1024),
                        }
                    )


    if EXTRA_DIR.exists():
        for chat_dir in sorted(EXTRA_DIR.iterdir()):
            if not chat_dir.is_dir():
                continue
            chat_slug = chat_dir.name
            for f in sorted(chat_dir.iterdir()):
                if f.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(
                        {
                            "path": str(f),
                            "chat_slug": chat_slug,
                            "filename": f.name,
                            "size_mb": f.stat().st_size / (1024 * 1024),
                        }
                    )


    wa_root = DATA_ROOT / "whatsapp"
    for f in wa_root.iterdir():
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(
                {
                    "path": str(f),
                    "chat_slug": "_root",
                    "filename": f.name,
                    "size_mb": f.stat().st_size / (1024 * 1024),
                }
            )

    return videos


def get_video_duration(video_path: str) -> float:
    ""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, output_wav: str) -> bool:
    ""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                output_wav,
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
        return True
    except Exception as e:
        log.warning("Audio extraction failed for %s: %s", Path(video_path).name, e)
        return False


def transcribe_audio(wav_path: str, model: str = "turbo") -> dict:
    ""
    try:
        import whisper

        _model = whisper.load_model(model)
        result = _model.transcribe(wav_path, fp16=False)
        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in result.get("segments", [])
            ],
        }
    except ImportError:

        try:
            result = subprocess.run(
                ["whisper-cli", "-f", wav_path, "-l", "auto"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {"text": result.stdout.strip(), "language": "auto"}
        except Exception as e:
            return {"text": "", "error": f"whisper-cli failed: {e}"}
    except Exception as e:
        return {"text": "", "error": str(e)}


def extract_keyframes(video_path: str, output_dir: Path, interval: int = 30) -> int:
    ""
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(output_dir / "keyframe_%03d.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vf", f"fps=1/{interval}", "-q:v", "2", pattern],
            capture_output=True,
            timeout=60,
            check=True,
        )
        return len(list(output_dir.glob("keyframe_*.jpg")))
    except Exception as e:
        log.warning("Keyframe extraction failed: %s", e)
        return 0


def process_video(
    video: dict,
    *,
    whisper_model: str = "turbo",
    skip_keyframes: bool = False,
) -> dict:
    ""
    video_path = video["path"]
    chat_slug = video["chat_slug"]
    filename = video["filename"]
    video_id = Path(filename).stem


    out_dir = VIDEOS_OUTPUT_DIR / chat_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{video_id}.json"


    if out_file.exists():
        return {"status": "skipped", "video_id": video_id}

    duration = get_video_duration(video_path)

    result = {
        "video_id": video_id,
        "filename": filename,
        "chat_slug": chat_slug,
        "duration_seconds": round(duration, 1),
        "size_mb": round(video["size_mb"], 2),
        "transcript": "",
        "language": "unknown",
        "keyframe_count": 0,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        wav_path = tmp.name
        if extract_audio(video_path, wav_path):
            transcription = transcribe_audio(wav_path, model=whisper_model)
            result["transcript"] = transcription.get("text", "")
            result["language"] = transcription.get("language", "unknown")
            if "error" in transcription:
                result["transcription_error"] = transcription["error"]


    if not skip_keyframes and duration > 5:
        kf_dir = out_dir / f"{video_id}_keyframes"
        result["keyframe_count"] = extract_keyframes(video_path, kf_dir)


    safe_write_json(out_file, result)
    return {"status": "ok", **result}


def main():
    parser = argparse.ArgumentParser(description="DPI-05: WhatsApp Video Processing")
    parser.add_argument(
        "--process", action="store_true", help="Transcribe + extract (default: dry-run)"
    )
    parser.add_argument("--skip-keyframes", action="store_true", help="Skip keyframe extraction")
    parser.add_argument(
        "--whisper-model",
        default="turbo",
        choices=["tiny", "base", "small", "turbo"],
        help="Whisper model (default: turbo)",
    )
    parser.add_argument("--max-videos", type=int, default=None, help="Max videos to process")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    videos = find_all_videos()
    log.info("Found %d video files", len(videos))
    total_size = sum(v["size_mb"] for v in videos)
    log.info("Total size: %.1f MB", total_size)


    from collections import Counter

    chats = Counter(v["chat_slug"] for v in videos)
    log.info("Videos by chat (top 10):")
    for chat, cnt in chats.most_common(10):
        log.info("  %s: %d", chat, cnt)

    if not args.process:
        log.info("Dry run complete. Use --process to transcribe.")
        return

    if args.max_videos:
        videos = videos[: args.max_videos]

    log.info(
        "Processing %d videos (model=%s, keyframes=%s)...",
        len(videos),
        args.whisper_model,
        "yes" if not args.skip_keyframes else "no",
    )

    ok = 0
    skipped = 0
    errors = 0

    for i, video in enumerate(videos):
        try:
            result = process_video(
                video,
                whisper_model=args.whisper_model,
                skip_keyframes=args.skip_keyframes,
            )
            if result["status"] == "ok":
                ok += 1
                log.info(
                    "  [%d/%d] %s: %.1fs, %d chars",
                    i + 1,
                    len(videos),
                    video["filename"],
                    result.get("duration_seconds", 0),
                    len(result.get("transcript", "")),
                )
            elif result["status"] == "skipped":
                skipped += 1
        except Exception as e:
            errors += 1
            log.error("  [%d/%d] %s: FAILED (%s)", i + 1, len(videos), video["filename"], e)


    safe_write_json(
        VIDEOS_OUTPUT_DIR / "_process-stats.json",
        {
            "total_videos": len(videos),
            "processed": ok,
            "skipped": skipped,
            "errors": errors,
            "whisper_model": args.whisper_model,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )

    log.info("Done: %d processed, %d skipped, %d errors", ok, skipped, errors)


if __name__ == "__main__":
    main()
