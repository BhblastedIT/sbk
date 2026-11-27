#!/usr/bin/env python3
"""Transcribes your Voice Memos recordings locally with whisper.cpp (model in ~/whisper-models), in parallel, one
transcript per memo; the language comes from voice_memos.language.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow")
    sys.exit(1)

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import (
    VOICE_MEMOS_DIR,
    VOICE_MEMOS_LANGUAGE,
    VOICE_MEMOS_TRANSCRIPTS_DIR,
    safe_write_parquet,
)



VOICE_DIR = VOICE_MEMOS_DIR
TRANSCRIPTS_DIR = VOICE_MEMOS_TRANSCRIPTS_DIR
WHISPER_MODEL = str(Path.home() / "whisper-models" / "ggml-large-v3-turbo.bin")
# whisper.cpp language: sbk.config.json voice_memos.language or env SBK_VOICE_MEMOS_LANGUAGE,
# "auto" (default) detects it per memo.
LANGUAGE = VOICE_MEMOS_LANGUAGE


def get_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0



sys.path.insert(0, str(Path(__file__).resolve().parent))
from vm_nomi import slugify  # noqa: E402


def transcribe_one(m4a_path: str) -> dict:
    ""
    m4a = Path(m4a_path)
    name = m4a.stem
    slug = slugify(name)
    duration = get_duration(m4a_path)
    transcripts_dir = VOICE_MEMOS_TRANSCRIPTS_DIR
    out_json = transcripts_dir / f"{slug}.json"


    if out_json.exists():
        try:
            existing = json.loads(out_json.read_text())
            if existing.get("segments"):
                return {
                    "filename": m4a.name,
                    "slug": slug,
                    "duration_seconds": duration,
                    "duration_minutes": round(duration / 60, 1),
                    "segment_count": len(existing["segments"]),
                    "transcript_length": len(existing.get("raw_transcript", "")),
                    "transcript_path": str(out_json),
                    "status": "skipped",
                }
        except Exception:
            pass

    t0 = time.time()


    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", m4a_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True,
            timeout=120,
        )
        if not Path(wav_path).exists():
            return {"filename": m4a.name, "slug": slug, "status": "ffmpeg_failed"}
    except Exception as e:
        return {"filename": m4a.name, "slug": slug, "status": f"ffmpeg_error: {e}"}


    try:
        r = subprocess.run(
            ["whisper-cli", "-m", WHISPER_MODEL, "-l", LANGUAGE, "-t", "2", "-f", wav_path],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        Path(wav_path).unlink(missing_ok=True)
        return {"filename": m4a.name, "slug": slug, "status": "whisper_timeout"}

    Path(wav_path).unlink(missing_ok=True)


    pattern = re.compile(
        r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)"
    )
    segments = []
    for line in output.splitlines():
        m = pattern.match(line.strip())
        if m:
            start_str, end_str, text = m.groups()
            text = text.strip()
            if text:
                segments.append({"start": start_str, "end": end_str, "text": text})

    raw_transcript = "\n".join(s["text"] for s in segments)
    elapsed = time.time() - t0


    transcript = {
        "filename": m4a.name,
        "slug": slug,
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60, 1),
        "segments": segments,
        "raw_transcript": raw_transcript,
    }
    out_json.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))

    return {
        "filename": m4a.name,
        "slug": slug,
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60, 1),
        "segment_count": len(segments),
        "transcript_length": len(raw_transcript),
        "transcript_path": str(out_json),
        "status": "done",
        "elapsed": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Voice Memos Transcriber — SBK")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers. Default: computed from available memory "
        "(sbk_resources.cpu_workers()). Each worker loads a Whisper model, "
        "so too many in parallel can exhaust memory.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("transcribe")

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    m4a_files = sorted(VOICE_DIR.glob("*.m4a"))
    if not m4a_files:
        log.warning("No .m4a files found in %s", VOICE_DIR)
        return

    if args.workers is None:
        try:
            from sbk_resources import budget, cpu_workers

            args.workers = cpu_workers()
            log.info("Workers computed from available memory: %d (%s)", args.workers, budget())
        except ImportError:
            args.workers = 2
            log.warning("sbk_resources not available: using 2 workers (conservative)")

    log.info(f"Found {len(m4a_files)} voice memos — launching {args.workers} parallel workers")

    rows = []
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(transcribe_one, str(m4a)): m4a.stem for m4a in m4a_files}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                status = result.get("status", "?")
                if status == "skipped":
                    log.info(f"  {name}: skipped (already done)")
                elif status == "done":
                    log.info(
                        f"  {name}: {result['segment_count']} segments, "
                        f"{result['transcript_length']} chars in {result['elapsed']}s"
                    )
                else:
                    log.error(f"  {name}: {status}")
                rows.append(result)
            except Exception as e:
                log.error(f"  {name}: worker exception: {e}")

    elapsed = time.time() - t0
    log.info(f"All done in {elapsed:.0f}s")


    good_rows = [r for r in rows if r.get("duration_seconds")]
    if good_rows:
        df = pd.DataFrame(good_rows)
        out = VOICE_DIR / "voice-memos.parquet"
        safe_write_parquet(df, out, index=False)
        log.info(f"Saved index → {out} ({len(df)} memos)")

        total_dur = sum(r.get("duration_seconds", 0) for r in good_rows)
        total_chars = sum(r.get("transcript_length", 0) for r in good_rows)
        log.info(f"Total: {total_dur / 60:.0f} min audio, {total_chars} chars of transcript")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-voice-memos-transcribe", source="voice-memos", stage="l0")
def run():
    main()


if __name__ == "__main__":
    run()
