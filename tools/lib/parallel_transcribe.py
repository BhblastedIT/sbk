"""Parallel transcription of a long recording with Whisper: converts it to 16 kHz WAV, splits it at silences, runs
the chunks on several workers (GPU and CPU), merges them removing the duplicates at the boundaries, and checks
the quality of each chunk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("asr.parallel")




@dataclass
class TranscribeConfig:
    ""


    model_path: str = "~/whisper-models/ggml-large-v3.bin"
    whisper_binary: str = "whisper-cli"
    language: str = "auto"
    prompt: str = ""


    workers: int = 4
    gpu_workers: int = 1
    threads_per_gpu_worker: int = 4
    threads_per_cpu_worker: int = 3


    chunk_duration_s: int = 600
    min_chunk_s: int = 30
    overlap_s: float = 3.0
    split_on_silence: bool = True


    vad_threshold: float = 0.4
    min_silence_duration_s: float = 0.5
    max_speech_duration_s: float = 900


    vad_enabled: bool = True
    whisper_vad_threshold: float = 0.40
    suppress_nst: bool = True


    quality_check: bool = True
    min_wpm: float = 15.0


    dedup_window_words: int = 30
    dedup_similarity_threshold: float = 0.6

    def __post_init__(self):
        self.model_path = os.path.expanduser(self.model_path)


@dataclass
class ChunkInfo:
    ""

    chunk_id: int
    start_s: float
    end_s: float
    duration_s: float
    wav_path: str
    use_gpu: bool
    overlap_start_s: float = 0.0
    overlap_end_s: float = 0.0


@dataclass
class ChunkResult:
    ""

    chunk_id: int
    start_s: float
    end_s: float
    text: str
    segments: list[dict]
    word_count: int
    elapsed_s: float
    model_used: str
    language_detected: str = "auto"
    quality_check: str = "ok"
    error: str | None = None


@dataclass
class ParallelTranscribeResult:
    ""

    text: str
    segments: list[dict]
    word_count: int
    elapsed_s: float
    model_used: str
    language_detected: str = "auto"
    chunk_count: int = 0
    workers_used: int = 0
    speedup_vs_sequential: float = 0.0
    audio_duration_s: float = 0.0
    real_time_factor: float = 0.0
    chunk_results: list[dict] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)





def get_audio_duration(path: str) -> float:
    ""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def convert_to_wav_16k(
    input_path: str, output_path: str, start_s: float = 0, duration_s: float | None = None
) -> bool:
    ""










    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-ss",
        str(start_s),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
    ]
    if duration_s is not None:
        cmd.extend(["-t", str(duration_s)])
    cmd.append(output_path)

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0 and Path(output_path).exists()
    except Exception as e:
        log.error("ffmpeg error: %s", e)
        return False





def _find_silence_boundaries_vad(
    wav_path: str,
    threshold: float = 0.4,
    min_silence_s: float = 0.5,
) -> list[dict]:
    ""




    try:
        import torch
        import torchaudio
    except ImportError:
        log.warning("torch/torchaudio not available, falling back to fixed splitting")
        return []

    try:

        model, utils = torch.hub.load(
            "snakers4/silero-vad",
            "silero_vad",
            trust_repo=True,
            onnx=False,
        )
        get_speech_timestamps = utils[0]


        waveform, sr = torchaudio.load(wav_path)
        if sr != 16000:
            waveform = torchaudio.functional.resample(waveform, sr, 16000)
            sr = 16000
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)


        speech_timestamps = get_speech_timestamps(
            waveform.squeeze(),
            model,
            threshold=threshold,
            sampling_rate=sr,
            min_silence_duration_ms=int(min_silence_s * 1000),
            return_seconds=True,
        )

        if not speech_timestamps:
            return []


        silence_gaps = []
        total_duration = waveform.shape[1] / sr


        if speech_timestamps[0]["start"] > min_silence_s:
            silence_gaps.append(
                {
                    "start": 0.0,
                    "end": speech_timestamps[0]["start"],
                    "duration": speech_timestamps[0]["start"],
                }
            )


        for i in range(len(speech_timestamps) - 1):
            gap_start = speech_timestamps[i]["end"]
            gap_end = speech_timestamps[i + 1]["start"]
            gap_duration = gap_end - gap_start
            if gap_duration >= min_silence_s:
                silence_gaps.append(
                    {
                        "start": gap_start,
                        "end": gap_end,
                        "duration": gap_duration,
                    }
                )


        last_end = speech_timestamps[-1]["end"]
        if total_duration - last_end > min_silence_s:
            silence_gaps.append(
                {
                    "start": last_end,
                    "end": total_duration,
                    "duration": total_duration - last_end,
                }
            )

        log.info("VAD found %d silence gaps in %.0fs audio", len(silence_gaps), total_duration)
        return silence_gaps

    except Exception as e:
        log.warning("VAD analysis failed: %s", e)
        return []


def _find_silence_boundaries_energy(
    wav_path: str,
    min_silence_s: float = 0.5,
    frame_ms: int = 30,
    silence_threshold_db: float = -35.0,
) -> list[dict]:
    ""



    import math
    import struct
    import wave

    try:
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        duration = n_frames / sr
        fmt = f"<{n_frames}h"
        samples = struct.unpack(fmt, raw)

        frame_size = int(sr * frame_ms / 1000)
        n_analysis_frames = len(samples) // frame_size


        frame_energies_db = []
        for i in range(n_analysis_frames):
            start = i * frame_size
            end = start + frame_size
            frame = samples[start:end]
            rms = math.sqrt(sum(s * s for s in frame) / len(frame)) / 32768.0
            db = 20 * math.log10(max(rms, 1e-10))
            frame_energies_db.append(db)


        min_silence_frames = int(min_silence_s * 1000 / frame_ms)
        silence_gaps = []
        in_silence = False
        silence_start = 0

        for i, db in enumerate(frame_energies_db):
            if db < silence_threshold_db:
                if not in_silence:
                    silence_start = i
                    in_silence = True
            else:
                if in_silence:
                    silence_len = i - silence_start
                    if silence_len >= min_silence_frames:
                        s = silence_start * frame_ms / 1000
                        e = i * frame_ms / 1000
                        silence_gaps.append(
                            {
                                "start": s,
                                "end": e,
                                "duration": e - s,
                            }
                        )
                    in_silence = False


        if in_silence:
            silence_len = n_analysis_frames - silence_start
            if silence_len >= min_silence_frames:
                s = silence_start * frame_ms / 1000
                e = duration
                silence_gaps.append({"start": s, "end": e, "duration": e - s})

        log.info("Energy analysis found %d silence gaps", len(silence_gaps))
        return silence_gaps

    except Exception as e:
        log.warning("Energy-based silence detection failed: %s", e)
        return []


def plan_chunks(
    audio_duration_s: float,
    config: TranscribeConfig,
    silence_gaps: list[dict] | None = None,
) -> list[tuple[float, float]]:
    ""










    if audio_duration_s <= config.chunk_duration_s + config.min_chunk_s:

        return [(0.0, audio_duration_s)]

    target = config.chunk_duration_s
    overlap = config.overlap_s
    min_chunk = config.min_chunk_s


    ideal_splits = []
    pos = target
    while pos < audio_duration_s - min_chunk:
        ideal_splits.append(pos)
        pos += target


    actual_splits = []
    if silence_gaps:
        for ideal in ideal_splits:


            search_window = 30.0
            candidates = [
                g for g in silence_gaps if abs((g["start"] + g["end"]) / 2 - ideal) < search_window
            ]
            if candidates:

                best = min(candidates, key=lambda g: abs((g["start"] + g["end"]) / 2 - ideal))
                split_point = (best["start"] + best["end"]) / 2
            else:

                split_point = ideal
            actual_splits.append(split_point)
    else:
        actual_splits = ideal_splits


    cleaned = []
    for s in sorted(actual_splits):
        if not cleaned or (s - cleaned[-1]) >= min_chunk:
            cleaned.append(s)
    actual_splits = cleaned


    chunks = []
    prev_end = 0.0
    for i, split in enumerate(actual_splits):

        chunk_start = max(0.0, prev_end - overlap) if i > 0 else 0.0
        chunk_end = split + overlap
        chunks.append((chunk_start, min(chunk_end, audio_duration_s)))
        prev_end = split


    last_start = max(0.0, actual_splits[-1] - overlap) if actual_splits else 0.0
    chunks.append((last_start, audio_duration_s))

    log.info(
        "Planned %d chunks for %.0fs audio (target %ds, overlap %.1fs)",
        len(chunks),
        audio_duration_s,
        target,
        overlap,
    )
    return chunks


def create_chunk_files(
    audio_path: str,
    chunk_boundaries: list[tuple[float, float]],
    config: TranscribeConfig,
    work_dir: str,
) -> list[ChunkInfo]:
    ""




    chunks = []
    for i, (start, end) in enumerate(chunk_boundaries):
        duration = end - start
        wav_path = os.path.join(work_dir, f"chunk_{i:04d}.wav")

        if not convert_to_wav_16k(audio_path, wav_path, start_s=start, duration_s=duration):
            log.error("Failed to create chunk %d (%.1f-%.1fs)", i, start, end)
            continue


        use_gpu = i < config.gpu_workers


        overlap_start = config.overlap_s if i > 0 else 0.0
        overlap_end = config.overlap_s if i < len(chunk_boundaries) - 1 else 0.0

        chunks.append(
            ChunkInfo(
                chunk_id=i,
                start_s=start,
                end_s=end,
                duration_s=duration,
                wav_path=wav_path,
                use_gpu=use_gpu,
                overlap_start_s=overlap_start,
                overlap_end_s=overlap_end,
            )
        )

    log.info(
        "Created %d chunk files (%d GPU, %d CPU)",
        len(chunks),
        sum(1 for c in chunks if c.use_gpu),
        sum(1 for c in chunks if not c.use_gpu),
    )
    return chunks





def transcribe_chunk(
    chunk_id: int,
    wav_path: str,
    start_s: float,
    end_s: float,
    model_path: str,
    whisper_binary: str,
    language: str,
    prompt: str,
    threads: int,
    use_gpu: bool,
    vad_enabled: bool,
    whisper_vad_threshold: float,
    suppress_nst: bool,
) -> dict:
    ""






    t0 = time.time()

    try:
        cmd = [
            whisper_binary,
            "-m",
            model_path,
            "-l",
            language,
            "-t",
            str(threads),
            "-f",
            wav_path,
        ]



        env = os.environ.copy()
        if not use_gpu:

            env["GGML_METAL_DISABLE"] = "1"

        if vad_enabled:
            cmd.extend(
                [
                    "--vad",
                    "--vad-threshold",
                    str(whisper_vad_threshold),
                    "--vad-min-speech-duration-ms",
                    "300",
                    "--vad-min-silence-duration-ms",
                    "2000",
                ]
            )


        cmd.extend(
            [
                "-et",
                "2.4",
                "-lpt",
                "-0.5",
                "-nth",
                "0.3",
            ]
        )

        if suppress_nst:
            cmd.append("--suppress-nst")

        if prompt:
            cmd.extend(["--prompt", prompt, "--carry-initial-prompt"])


        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=14400,
            env=env,
        )
        output = r.stdout + r.stderr
        elapsed = time.time() - t0


        seg_pattern = re.compile(
            r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)"
        )
        segments = []
        for line in output.splitlines():
            sm = seg_pattern.match(line.strip())
            if sm:
                seg_start, seg_end, text = sm.groups()
                text = text.strip()
                if text:

                    seg_start_s = _ts_to_seconds(seg_start) + start_s
                    seg_end_s = _ts_to_seconds(seg_end) + start_s
                    segments.append(
                        {
                            "start": round(seg_start_s, 3),
                            "end": round(seg_end_s, 3),
                            "start_str": _seconds_to_ts(seg_start_s),
                            "end_str": _seconds_to_ts(seg_end_s),
                            "text": text,
                        }
                    )

        full_text = " ".join(s["text"] for s in segments)
        word_count = len(full_text.split()) if full_text else 0


        lang_detected = language
        lang_match = re.search(r"auto-detected language:\s*(\w+)", output, re.IGNORECASE)
        if lang_match:
            lang_name = lang_match.group(1).lower()
            lang_map = {
                "italian": "it",
                "english": "en",
                "spanish": "es",
                "french": "fr",
                "german": "de",
                "chinese": "zh",
                "korean": "ko",
                "japanese": "ja",
                "portuguese": "pt",
            }
            lang_detected = lang_map.get(lang_name, lang_name[:2])

        return {
            "chunk_id": chunk_id,
            "start_s": start_s,
            "end_s": end_s,
            "text": full_text,
            "segments": segments,
            "word_count": word_count,
            "elapsed_s": round(elapsed, 1),
            "model_used": os.path.basename(model_path),
            "language_detected": lang_detected,
            "quality_check": "ok",
            "error": None,
            "use_gpu": use_gpu,
        }

    except subprocess.TimeoutExpired:
        return {
            "chunk_id": chunk_id,
            "start_s": start_s,
            "end_s": end_s,
            "text": "",
            "segments": [],
            "word_count": 0,
            "elapsed_s": round(time.time() - t0, 1),
            "model_used": os.path.basename(model_path),
            "language_detected": language,
            "quality_check": "timeout",
            "error": "Transcription timed out",
            "use_gpu": use_gpu,
        }

    except Exception as e:
        return {
            "chunk_id": chunk_id,
            "start_s": start_s,
            "end_s": end_s,
            "text": "",
            "segments": [],
            "word_count": 0,
            "elapsed_s": round(time.time() - t0, 1),
            "model_used": os.path.basename(model_path),
            "language_detected": language,
            "quality_check": "error",
            "error": str(e),
            "use_gpu": use_gpu,
        }


def _ts_to_seconds(ts: str) -> float:
    ""
    try:
        parts = ts.split(":")
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    except Exception:
        return 0.0


def _seconds_to_ts(seconds: float) -> str:
    ""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"





def _get_words(text: str) -> list[str]:
    ""
    return [w.lower().strip(".,!?;:\"'") for w in text.split() if w.strip()]


def _deduplicate_boundary(
    prev_text: str,
    next_text: str,
    window_words: int = 30,
    similarity_threshold: float = 0.6,
) -> str:
    ""












    prev_words = _get_words(prev_text)
    next_words = _get_words(next_text)

    if len(prev_words) < 3 or len(next_words) < 3:
        return next_text


    tail = prev_words[-window_words:]
    head = next_words[:window_words]


    best_overlap_len = 0
    best_similarity = 0.0

    for overlap_len in range(min(len(tail), len(head)), 2, -1):

        tail_segment = " ".join(tail[-overlap_len:])
        head_segment = " ".join(head[:overlap_len])

        sim = SequenceMatcher(None, tail_segment, head_segment).ratio()
        if sim > similarity_threshold and sim > best_similarity:
            best_similarity = sim
            best_overlap_len = overlap_len

    if best_overlap_len > 0:


        original_words = next_text.split()
        trimmed = " ".join(original_words[best_overlap_len:])
        log.debug(
            "Boundary dedup: removed %d overlapping words (similarity: %.2f)",
            best_overlap_len,
            best_similarity,
        )
        return trimmed

    return next_text


def merge_chunk_results(
    results: list[dict],
    config: TranscribeConfig,
) -> ParallelTranscribeResult:
    ""







    sorted_results = sorted(results, key=lambda r: r["chunk_id"])


    valid = [r for r in sorted_results if r.get("text")]
    failed = [r for r in sorted_results if not r.get("text")]

    if not valid:
        return ParallelTranscribeResult(
            text="",
            segments=[],
            word_count=0,
            elapsed_s=0.0,
            model_used="none",
            quality_warnings=["All chunks failed"],
        )


    merged_texts = [valid[0]["text"]]
    for i in range(1, len(valid)):
        deduped = _deduplicate_boundary(
            valid[i - 1]["text"],
            valid[i]["text"],
            window_words=config.dedup_window_words,
            similarity_threshold=config.dedup_similarity_threshold,
        )
        merged_texts.append(deduped)

    full_text = " ".join(merged_texts)


    all_segments = []
    for r in valid:
        all_segments.extend(r.get("segments", []))


    all_segments.sort(key=lambda s: s["start"])
    deduped_segments = _deduplicate_segments(all_segments)


    lang_votes = [
        r.get("language_detected", "auto")
        for r in valid
        if r.get("language_detected", "auto") != "auto"
    ]
    if lang_votes:
        from collections import Counter

        lang_detected = Counter(lang_votes).most_common(1)[0][0]
    else:
        lang_detected = "auto"


    warnings = []
    for r in failed:
        warnings.append(f"Chunk {r['chunk_id']} failed: {r.get('error', 'unknown')}")
    for r in valid:
        if r.get("quality_check") not in ("ok", None):
            warnings.append(f"Chunk {r['chunk_id']}: {r['quality_check']}")

    word_count = len(full_text.split()) if full_text else 0

    return ParallelTranscribeResult(
        text=full_text,
        segments=deduped_segments,
        word_count=word_count,
        elapsed_s=0.0,
        model_used=valid[0].get("model_used", "unknown"),
        language_detected=lang_detected,
        chunk_count=len(sorted_results),
        chunk_results=[
            {
                "chunk_id": r["chunk_id"],
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "word_count": r["word_count"],
                "elapsed_s": r["elapsed_s"],
                "quality_check": r.get("quality_check", "ok"),
                "use_gpu": r.get("use_gpu", False),
            }
            for r in sorted_results
        ],
        quality_warnings=warnings,
    )


def _deduplicate_segments(segments: list[dict], overlap_threshold_s: float = 0.5) -> list[dict]:
    ""




    if not segments:
        return []

    deduped = [segments[0]]
    for seg in segments[1:]:
        prev = deduped[-1]

        overlap_start = max(prev["start"], seg["start"])
        overlap_end = min(prev["end"], seg["end"])
        overlap = max(0, overlap_end - overlap_start)

        if overlap > overlap_threshold_s:

            if len(seg.get("text", "")) > len(prev.get("text", "")):
                deduped[-1] = seg

        else:
            deduped.append(seg)

    return deduped





def _has_repeated_ngrams(words: list[str], window: int = 5, threshold: int = 3) -> bool:
    ""
    if len(words) < window * threshold:
        return False
    for i in range(len(words) - window * threshold + 1):
        ngram = tuple(words[i : i + window])
        count = 1
        pos = i + window
        while pos + window <= len(words):
            if tuple(words[pos : pos + window]) == ngram:
                count += 1
                pos += window
                if count >= threshold:
                    return True
            else:
                break
    return False


def check_chunk_quality(text: str, duration_s: float, min_wpm: float = 15.0) -> str:
    ""
    words = text.split()
    wc = len(words)

    if duration_s > 5 and wc < 3:
        return "empty_output"

    if duration_s > 30:
        wpm = wc / (duration_s / 60)
        if wpm < min_wpm:
            return "low_density"

    if wc > 15:
        for window in [3, 5, 8]:
            if _has_repeated_ngrams(words, window, threshold=3):
                return "repetition_hallucination"

    return "ok"





class ParallelTranscriber:
    ""









    def __init__(self, config: TranscribeConfig | None = None):
        self.config = config or TranscribeConfig()
        self._validate_config()

    def _validate_config(self):
        ""
        import shutil

        if not shutil.which(self.config.whisper_binary):
            raise RuntimeError(f"whisper binary not found: {self.config.whisper_binary}")
        if not Path(self.config.model_path).exists():
            raise RuntimeError(f"model not found: {self.config.model_path}")

    def transcribe(self, audio_path: str, progress_callback=None) -> ParallelTranscribeResult:
        ""









        t0 = time.time()
        cfg = self.config


        duration = get_audio_duration(audio_path)
        if duration <= 0:
            raise ValueError(f"Could not determine duration of {audio_path}")

        log.info("Audio: %s (%.0fs = %.1f hours)", audio_path, duration, duration / 3600)


        if duration <= cfg.chunk_duration_s * 1.5:
            log.info("Audio is short (%.0fs), using single-process transcription", duration)
            return self._transcribe_single(audio_path, duration)


        with tempfile.TemporaryDirectory(prefix="sbk_par_") as work_dir:
            silence_gaps = []
            if cfg.split_on_silence:



                log.info("Analyzing silence boundaries...")
                full_wav = os.path.join(work_dir, "full_audio.wav")
                if convert_to_wav_16k(audio_path, full_wav):
                    silence_gaps = _find_silence_boundaries_vad(
                        full_wav,
                        threshold=cfg.vad_threshold,
                        min_silence_s=cfg.min_silence_duration_s,
                    )
                    if not silence_gaps:
                        silence_gaps = _find_silence_boundaries_energy(
                            full_wav,
                            min_silence_s=cfg.min_silence_duration_s,
                        )

                    Path(full_wav).unlink(missing_ok=True)
                else:
                    log.warning("Could not convert full audio for VAD analysis")


            chunk_boundaries = plan_chunks(duration, cfg, silence_gaps)
            log.info("Planned %d chunks", len(chunk_boundaries))

            if progress_callback:
                progress_callback(-1, len(chunk_boundaries), "Creating chunk files...")


            chunks = create_chunk_files(audio_path, chunk_boundaries, cfg, work_dir)
            if not chunks:
                raise RuntimeError("No chunk files created")


            log.info(
                "Starting parallel transcription: %d workers (%d GPU, %d CPU)",
                cfg.workers,
                cfg.gpu_workers,
                cfg.workers - cfg.gpu_workers,
            )

            results = self._run_parallel(chunks, progress_callback)


            if cfg.quality_check:
                for r in results:
                    if r.get("text") and r.get("quality_check") == "ok":
                        qc = check_chunk_quality(
                            r["text"],
                            r["end_s"] - r["start_s"],
                            cfg.min_wpm,
                        )
                        r["quality_check"] = qc


            merged = merge_chunk_results(results, cfg)

        elapsed = time.time() - t0
        merged.elapsed_s = round(elapsed, 1)
        merged.audio_duration_s = round(duration, 1)
        merged.workers_used = cfg.workers
        merged.real_time_factor = round(duration / elapsed, 1) if elapsed > 0 else 0


        chunk_elapsed_sum = sum(r.get("elapsed_s", 0) for r in results)
        if elapsed > 0:
            merged.speedup_vs_sequential = round(chunk_elapsed_sum / elapsed, 1)

        log.info(
            "DONE: %d words, %d chunks, %.0fs elapsed (%.1fx real-time, %.1fx speedup)",
            merged.word_count,
            merged.chunk_count,
            elapsed,
            merged.real_time_factor,
            merged.speedup_vs_sequential,
        )

        return merged

    def _run_parallel(self, chunks: list[ChunkInfo], progress_callback=None) -> list[dict]:
        ""
        cfg = self.config
        results = []
        total = len(chunks)


        worker_args = []
        for chunk in chunks:
            threads = cfg.threads_per_gpu_worker if chunk.use_gpu else cfg.threads_per_cpu_worker
            worker_args.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "wav_path": chunk.wav_path,
                    "start_s": chunk.start_s,
                    "end_s": chunk.end_s,
                    "model_path": cfg.model_path,
                    "whisper_binary": cfg.whisper_binary,
                    "language": cfg.language,
                    "prompt": cfg.prompt,
                    "threads": threads,
                    "use_gpu": chunk.use_gpu,
                    "vad_enabled": cfg.vad_enabled,
                    "whisper_vad_threshold": cfg.whisper_vad_threshold,
                    "suppress_nst": cfg.suppress_nst,
                }
            )

        with ProcessPoolExecutor(max_workers=cfg.workers) as executor:
            futures = {
                executor.submit(transcribe_chunk, **args): args["chunk_id"] for args in worker_args
            }

            for future in as_completed(futures):
                chunk_id = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = "ok" if result.get("text") else result.get("quality_check", "error")
                    log.info(
                        "Chunk %d/%d: %d words, %.1fs (%s, %s)",
                        chunk_id + 1,
                        total,
                        result.get("word_count", 0),
                        result.get("elapsed_s", 0),
                        "GPU" if result.get("use_gpu") else "CPU",
                        status,
                    )
                    if progress_callback:
                        progress_callback(
                            chunk_id,
                            total,
                            f"Chunk {chunk_id + 1}/{total}: {result.get('word_count', 0)} words",
                        )
                except Exception as e:
                    log.error("Chunk %d failed: %s", chunk_id, e)
                    results.append(
                        {
                            "chunk_id": chunk_id,
                            "start_s": 0,
                            "end_s": 0,
                            "text": "",
                            "segments": [],
                            "word_count": 0,
                            "elapsed_s": 0,
                            "model_used": "",
                            "quality_check": "error",
                            "error": str(e),
                        }
                    )

        return results

    def _transcribe_single(self, audio_path: str, duration: float) -> ParallelTranscribeResult:
        ""
        cfg = self.config
        t0 = time.time()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            if not convert_to_wav_16k(audio_path, wav_path):
                raise RuntimeError("WAV conversion failed")

            result = transcribe_chunk(
                chunk_id=0,
                wav_path=wav_path,
                start_s=0.0,
                end_s=duration,
                model_path=cfg.model_path,
                whisper_binary=cfg.whisper_binary,
                language=cfg.language,
                prompt=cfg.prompt,
                threads=cfg.threads_per_gpu_worker,
                use_gpu=True,
                vad_enabled=cfg.vad_enabled,
                whisper_vad_threshold=cfg.whisper_vad_threshold,
                suppress_nst=cfg.suppress_nst,
            )
        finally:
            Path(wav_path).unlink(missing_ok=True)

        elapsed = time.time() - t0

        return ParallelTranscribeResult(
            text=result.get("text", ""),
            segments=result.get("segments", []),
            word_count=result.get("word_count", 0),
            elapsed_s=round(elapsed, 1),
            model_used=result.get("model_used", ""),
            language_detected=result.get("language_detected", "auto"),
            chunk_count=1,
            workers_used=1,
            audio_duration_s=round(duration, 1),
            real_time_factor=round(duration / elapsed, 1) if elapsed > 0 else 0,
        )

    def estimate_time(self, audio_duration_s: float) -> dict:
        ""



        cfg = self.config
        n_chunks = max(1, int(audio_duration_s / cfg.chunk_duration_s))





        gpu_rtf = 3.5
        cpu_rtf = 1.5

        sequential_time = audio_duration_s / gpu_rtf


        chunk_duration = audio_duration_s / n_chunks
        gpu_chunk_time = chunk_duration / gpu_rtf
        cpu_chunk_time = chunk_duration / cpu_rtf


        n_cpu_workers = cfg.workers - cfg.gpu_workers
        gpu_batches = max(1, (n_chunks + cfg.workers - 1) // cfg.workers)

        parallel_time = gpu_batches * max(gpu_chunk_time, cpu_chunk_time)


        overhead = 45

        return {
            "audio_duration_s": audio_duration_s,
            "audio_duration_human": f"{audio_duration_s / 3600:.1f}h",
            "n_chunks": n_chunks,
            "sequential_estimate_s": round(sequential_time),
            "sequential_estimate_human": f"{sequential_time / 60:.0f} min",
            "parallel_estimate_s": round(parallel_time + overhead),
            "parallel_estimate_human": f"{(parallel_time + overhead) / 60:.0f} min",
            "estimated_speedup": round(sequential_time / (parallel_time + overhead), 1),
            "workers": cfg.workers,
            "gpu_workers": cfg.gpu_workers,
            "cpu_workers": n_cpu_workers,
        }





def main():
    ""
    import argparse

    parser = argparse.ArgumentParser(
        description="Parallel Whisper Transcription (Apple Silicon)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Transcribe a 6-hour meeting recording
  python parallel_transcribe.py --input meeting.m4a --workers 4

  # Use large-v3-turbo for faster (less accurate) transcription
  python parallel_transcribe.py --input call.mp3 --model ~/whisper-models/ggml-large-v3-turbo.bin --workers 6

  # Dry run: show estimated time and chunk plan
  python parallel_transcribe.py --input meeting.m4a --estimate-only

  # Audio in a given language with a context prompt (names that occur in it)
  python parallel_transcribe.py --input call.m4a --language en --prompt "Company X, Company Y, Person A"
        """,
    )
    parser.add_argument("--input", "-i", required=True, help="Input audio file")
    parser.add_argument("--output", "-o", help="Output JSON file (default: input_stem.json)")
    parser.add_argument("--output-txt", help="Also write plain text file")
    parser.add_argument(
        "--model",
        "-m",
        default="~/whisper-models/ggml-large-v3.bin",
        help="Whisper model path (default: large-v3)",
    )
    parser.add_argument("--language", "-l", default="auto", help="Language code (default: auto)")
    parser.add_argument("--prompt", default="", help="Initial prompt for context")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Total workers (default: 4)")
    parser.add_argument("--gpu-workers", type=int, default=1, help="GPU workers (default: 1)")
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=600,
        help="Target chunk duration in seconds (default: 600 = 10min)",
    )
    parser.add_argument("--overlap", type=float, default=3.0, help="Overlap seconds (default: 3)")
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Disable VAD-based splitting (use fixed intervals)",
    )
    parser.add_argument("--estimate-only", action="store_true", help="Show time estimate and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()


    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


    config = TranscribeConfig(
        model_path=args.model,
        language=args.language,
        prompt=args.prompt,
        workers=args.workers,
        gpu_workers=args.gpu_workers,
        chunk_duration_s=args.chunk_duration,
        overlap_s=args.overlap,
        split_on_silence=not args.no_vad,
    )

    transcriber = ParallelTranscriber(config)


    if args.estimate_only:
        duration = get_audio_duration(args.input)
        est = transcriber.estimate_time(duration)
        print(f"\n  Audio: {args.input}")
        print(f"  Duration: {est['audio_duration_human']} ({est['audio_duration_s']}s)")
        print(f"  Chunks: {est['n_chunks']} x {config.chunk_duration_s}s")
        print(f"  Workers: {est['workers']} ({est['gpu_workers']} GPU + {est['cpu_workers']} CPU)")
        print(f"\n  Sequential estimate: {est['sequential_estimate_human']}")
        print(f"  Parallel estimate:   {est['parallel_estimate_human']}")
        print(f"  Expected speedup:    {est['estimated_speedup']}x")
        print()
        return


    def on_progress(chunk_id, total, msg):
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        if chunk_id < 0:
            print(f"  [{ts}] {msg}")
        else:
            print(f"  [{ts}] [{chunk_id + 1}/{total}] {msg}")


    duration = get_audio_duration(args.input)
    print()
    print("=" * 65)
    print("  SBK — Parallel Whisper Transcription")
    print("=" * 65)
    print(f"  Input:    {args.input}")
    print(f"  Duration: {duration / 3600:.1f}h ({duration:.0f}s)")
    print(f"  Model:    {os.path.basename(config.model_path)}")
    print(
        f"  Workers:  {config.workers} ({config.gpu_workers} GPU + {config.workers - config.gpu_workers} CPU)"
    )
    print(
        f"  Chunks:   ~{max(1, int(duration / config.chunk_duration_s))} x {config.chunk_duration_s}s"
    )
    print(f"  Language:  {config.language}")
    print("=" * 65)
    print()


    result = transcriber.transcribe(args.input, progress_callback=on_progress)


    output_path = args.output or (Path(args.input).stem + "_transcript.json")
    output_data = {
        "source_file": args.input,
        "audio_duration_s": result.audio_duration_s,
        "audio_duration_human": f"{result.audio_duration_s / 3600:.1f}h",
        "transcription": {
            "text": result.text,
            "word_count": result.word_count,
            "language": result.language_detected,
            "model": result.model_used,
        },
        "segments": result.segments,
        "performance": {
            "elapsed_s": result.elapsed_s,
            "elapsed_human": f"{result.elapsed_s / 60:.1f} min",
            "real_time_factor": result.real_time_factor,
            "speedup_vs_sequential": result.speedup_vs_sequential,
            "workers_used": result.workers_used,
            "chunk_count": result.chunk_count,
        },
        "chunk_details": result.chunk_results,
        "quality_warnings": result.quality_warnings,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    print(f"\n  Transcript: {output_path}")


    if args.output_txt:
        with open(args.output_txt, "w") as f:
            f.write(result.text)
        print(f"  Text:       {args.output_txt}")


    print()
    print("=" * 65)
    print("  TRANSCRIPTION COMPLETE")
    print("=" * 65)
    print(f"  Words:      {result.word_count:,}")
    print(f"  Language:   {result.language_detected}")
    print(f"  Chunks:     {result.chunk_count}")
    print(f"  Elapsed:    {result.elapsed_s:.0f}s ({result.elapsed_s / 60:.1f} min)")
    print(f"  RTF:        {result.real_time_factor}x real-time")
    print(f"  Speedup:    {result.speedup_vs_sequential}x vs sequential")
    if result.quality_warnings:
        print(f"  Warnings:   {len(result.quality_warnings)}")
        for w in result.quality_warnings:
            print(f"    - {w}")
    print("=" * 65)


if __name__ == "__main__":
    main()
