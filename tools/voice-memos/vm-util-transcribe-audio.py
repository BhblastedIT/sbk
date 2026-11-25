#!/usr/bin/env python3
""







import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import safe_write_json  # noqa: E402


WHISPER_MODEL = os.path.expanduser("~/whisper-models/ggml-large-v3-turbo.bin")
LANGUAGE = "it"
SAMPLE_RATE = 16000
MIN_SEGMENT_DURATION = 1.0
SPEAKER_EMBEDDING_WINDOW = 1.5
CLUSTERING_THRESHOLD = 0.55


def log(msg, prefix=""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {prefix}{msg}", flush=True)



def convert_to_wav(input_path, output_path):
    ""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")
    return output_path


def get_audio_duration(path):
    ""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def get_audio_metadata(path):
    ""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format_tags=creation_time,title,artist,album",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        return data.get("format", {}).get("tags", {})
    except Exception:
        return {}



def transcribe_whisper(wav_path, output_dir):
    ""
    output_base = str(Path(output_dir) / "whisper_out")
    cmd = [
        "whisper-cli",
        "-m",
        WHISPER_MODEL,
        "-l",
        LANGUAGE,
        "-t",
        "4",
        "--output-json-full",
        "-of",
        output_base,
        "-np",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"Whisper failed: {result.stderr[:500]}")

    json_path = output_base + ".json"
    if not os.path.exists(json_path):
        raise RuntimeError(f"Whisper JSON not found at {json_path}")

    with open(json_path, "rb") as f:
        raw = f.read()

    text = raw.decode("utf-8", errors="replace")
    return json.loads(text)



def diarize_speakers(wav_path, num_speakers=None):
    ""



    import numpy as np
    import torch
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier


    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="/tmp/speechbrain_ecapa",
        run_opts={"device": "cpu"},
    )


    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SAMPLE_RATE:
        waveform = torchaudio.functional.resample(waveform, sr, SAMPLE_RATE)
        sr = SAMPLE_RATE


    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    total_duration = waveform.shape[1] / sr


    frame_size = int(0.025 * sr)
    hop_size = int(0.010 * sr)

    signal = waveform.squeeze().numpy()


    energies = []
    for i in range(0, len(signal) - frame_size, hop_size):
        frame = signal[i : i + frame_size]
        energy = np.sqrt(np.mean(frame**2))
        energies.append(energy)
    energies = np.array(energies)


    if len(energies) == 0:
        return [(0, total_duration, "SPEAKER_00")]

    log_energies = np.log(energies + 1e-10)
    threshold = np.percentile(log_energies, 30)


    is_speech = log_energies > threshold


    min_silence_frames = int(0.3 / 0.010)
    min_speech_frames = int(0.2 / 0.010)


    for i in range(len(is_speech)):
        if not is_speech[i]:
            left = max(0, i - min_silence_frames // 2)
            right = min(len(is_speech), i + min_silence_frames // 2)
            if np.sum(is_speech[left:right]) > (right - left) * 0.5:
                is_speech[i] = True


    segments = []
    in_segment = False
    seg_start = 0
    for i in range(len(is_speech)):
        if is_speech[i] and not in_segment:
            seg_start = i
            in_segment = True
        elif not is_speech[i] and in_segment:
            seg_end = i
            duration = (seg_end - seg_start) * 0.010
            if duration >= MIN_SEGMENT_DURATION:
                segments.append((seg_start * 0.010, seg_end * 0.010))
            in_segment = False
    if in_segment:
        seg_end = len(is_speech)
        duration = (seg_end - seg_start) * 0.010
        if duration >= MIN_SEGMENT_DURATION:
            segments.append((seg_start * 0.010, seg_end * 0.010))

    if not segments:
        return [(0, total_duration, "SPEAKER_00")]


    embeddings = []
    valid_segments = []

    for start_t, end_t in segments:
        start_sample = int(start_t * sr)
        end_sample = min(int(end_t * sr), waveform.shape[1])
        chunk = waveform[:, start_sample:end_sample]

        if chunk.shape[1] < sr * 0.5:
            continue


        with torch.no_grad():
            emb = classifier.encode_batch(chunk)
            embeddings.append(emb.squeeze().numpy())
            valid_segments.append((start_t, end_t))

    if not embeddings:
        return [(0, total_duration, "SPEAKER_00")]

    embeddings = np.array(embeddings)


    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics.pairwise import cosine_distances

    if len(embeddings) == 1:
        return [(valid_segments[0][0], valid_segments[0][1], "SPEAKER_00")]


    dist_matrix = cosine_distances(embeddings)


    if num_speakers is None:

        from sklearn.metrics import silhouette_score

        best_n = 1
        best_score = -1

        for n in range(2, min(6, len(embeddings))):
            try:
                clustering = AgglomerativeClustering(
                    n_clusters=n, metric="precomputed", linkage="average"
                )
                labels = clustering.fit_predict(dist_matrix)
                score = silhouette_score(dist_matrix, labels, metric="precomputed")
                if score > best_score:
                    best_score = score
                    best_n = n
            except Exception:
                continue


        if best_score < 0.15:
            best_n = 1

        num_speakers = best_n

    if num_speakers == 1:
        return [(s, e, "SPEAKER_00") for s, e in valid_segments]


    clustering = AgglomerativeClustering(
        n_clusters=num_speakers, metric="precomputed", linkage="average"
    )
    labels = clustering.fit_predict(dist_matrix)


    result = []
    for (start_t, end_t), label in zip(valid_segments, labels):
        result.append((start_t, end_t, f"SPEAKER_{label:02d}"))


    merged = [result[0]]
    for seg in result[1:]:
        if seg[2] == merged[-1][2] and (seg[0] - merged[-1][1]) < 2.0:
            merged[-1] = (merged[-1][0], seg[1], seg[2])
        else:
            merged.append(seg)

    return merged



def align_transcript_with_speakers(whisper_result, diarization):
    ""


    segments = whisper_result.get("transcription", [])

    aligned = []
    for seg in segments:


        ts = seg.get("timestamps", {})
        text = seg.get("text", "").strip()

        if not text:
            continue


        seg_start = parse_timestamp(ts.get("from", "00:00:00.000"))
        seg_end = parse_timestamp(ts.get("to", "00:00:00.000"))


        speaker = find_speaker_for_segment(seg_start, seg_end, diarization)

        aligned.append(
            {
                "start": round(seg_start, 2),
                "end": round(seg_end, 2),
                "speaker": speaker,
                "text": text,
            }
        )

    return aligned


def parse_timestamp(ts_str):
    ""
    if not ts_str:
        return 0.0
    try:
        parts = ts_str.replace(",", ".").split(":")
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        else:
            return float(parts[0])
    except Exception:
        return 0.0


def find_speaker_for_segment(seg_start, seg_end, diarization):
    ""
    if not diarization:
        return "SPEAKER_00"

    best_speaker = "SPEAKER_00"
    best_overlap = 0

    for d_start, d_end, speaker in diarization:
        overlap_start = max(seg_start, d_start)
        overlap_end = min(seg_end, d_end)
        overlap = max(0, overlap_end - overlap_start)

        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker

    return best_speaker



def build_output(filename, aligned_segments, diarization, duration, metadata, num_speakers):
    ""


    speaker_stats = {}
    for seg in aligned_segments:
        sp = seg["speaker"]
        if sp not in speaker_stats:
            speaker_stats[sp] = {"segments": 0, "total_duration": 0, "word_count": 0}
        speaker_stats[sp]["segments"] += 1
        speaker_stats[sp]["total_duration"] += seg["end"] - seg["start"]
        speaker_stats[sp]["word_count"] += len(seg["text"].split())


    dominant_speaker = (
        max(speaker_stats, key=lambda s: speaker_stats[s]["total_duration"])
        if speaker_stats
        else "SPEAKER_00"
    )


    full_text_parts = []
    current_speaker = None
    for seg in aligned_segments:
        if seg["speaker"] != current_speaker:
            current_speaker = seg["speaker"]
            full_text_parts.append(f"\n[{current_speaker}]\n")
        full_text_parts.append(seg["text"])


    location = infer_location(filename)

    return {
        "source_file": filename,
        "metadata": {
            "duration_seconds": round(duration, 1),
            "duration_human": f"{int(duration // 60)}m {int(duration % 60)}s",
            "language": LANGUAGE,
            "location_inferred": location,
            "creation_time": metadata.get("creation_time"),
            "num_speakers_detected": num_speakers,
            "dominant_speaker": dominant_speaker,
            "dominant_speaker_note": "Likely the recorder (you) - most speaking time",
            "transcribed_at": datetime.now().isoformat(),
            "model": "whisper-large-v3-turbo",
            "diarization": "speechbrain-ecapa-voxceleb",
        },
        "speakers": {
            sp: {
                "segments": stats["segments"],
                "total_speaking_seconds": round(stats["total_duration"], 1),
                "word_count": stats["word_count"],
                "is_dominant": sp == dominant_speaker,
            }
            for sp, stats in speaker_stats.items()
        },
        "full_text": "".join(full_text_parts).strip(),
        "segments": aligned_segments,
    }


def infer_location(filename):
    ""
    name = Path(filename).stem

    if name.startswith("New Recording"):
        return None

    return name



def process_file(input_path, output_dir, file_index, total_files):
    ""
    filename = os.path.basename(input_path)
    prefix = f"[{file_index}/{total_files}] "
    log(f"Processing: {filename}", prefix)

    start_time = time.time()

    try:

        duration = get_audio_duration(input_path)
        metadata = get_audio_metadata(input_path)
        log(f"Duration: {int(duration // 60)}m {int(duration % 60)}s", prefix)


        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "audio.wav")
            log("Converting to WAV...", prefix)
            convert_to_wav(input_path, wav_path)


            log("Running speaker diarization...", prefix)
            try:
                diarization = diarize_speakers(wav_path)
                speakers_found = len(set(s[2] for s in diarization))
                log(f"Detected {speakers_found} speaker(s)", prefix)
            except Exception as e:
                log(f"Diarization warning: {e} — falling back to single speaker", prefix)
                diarization = [(0, duration, "SPEAKER_00")]
                speakers_found = 1


            log("Running Whisper transcription...", prefix)
            whisper_result = transcribe_whisper(wav_path, tmpdir)


            num_segments = len(whisper_result.get("transcription", []))
            log(f"Whisper returned {num_segments} segments", prefix)


            log("Aligning transcript with speakers...", prefix)
            aligned = align_transcript_with_speakers(whisper_result, diarization)


            output = build_output(
                filename, aligned, diarization, duration, metadata, speakers_found
            )


            safe_name = Path(filename).stem
            out_path = os.path.join(output_dir, f"{safe_name}.json")
            safe_write_json(out_path, output)

            elapsed = time.time() - start_time
            words = sum(len(s["text"].split()) for s in aligned)
            log(
                f"DONE: {words} words, {speakers_found} speakers, {elapsed:.0f}s — saved {os.path.basename(out_path)}",
                prefix,
            )

            return {
                "file": filename,
                "status": "ok",
                "words": words,
                "speakers": speakers_found,
                "elapsed": elapsed,
            }

    except Exception as e:
        elapsed = time.time() - start_time
        log(f"ERROR: {e}", prefix)
        return {"file": filename, "status": "error", "error": str(e), "elapsed": elapsed}



def main():
    parser = argparse.ArgumentParser(description="SBK Audio Transcription Pipeline")
    parser.add_argument("--input-dir", required=True, help="Directory with audio files")
    parser.add_argument("--output-dir", required=True, help="Output directory for transcripts")
    parser.add_argument("--workers", type=int, default=2, help="Parallel workers (default: 2)")
    parser.add_argument("--files", nargs="*", help="Specific files to process (optional)")
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)


    if args.files:
        audio_files = [os.path.join(input_dir, f) for f in args.files]
    else:
        extensions = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".aac", ".flac"}
        audio_files = sorted(
            [
                os.path.join(input_dir, f)
                for f in os.listdir(input_dir)
                if Path(f).suffix.lower() in extensions
            ]
        )

    if not audio_files:
        print("No audio files found!")
        sys.exit(1)


    print("╔══════════════════════════════════════════════════════════╗")
    print("║  SBK — Audio Transcription Pipeline                  ║")
    print("║  Whisper large-v3-turbo + SpeechBrain ECAPA diarization ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  Files: {len(audio_files)}")
    print(f"  Workers: {args.workers}")
    print(f"  Output: {output_dir}")
    print()


    total_duration = 0
    for f in audio_files:
        dur = get_audio_duration(f)
        total_duration += dur
        name = os.path.basename(f)
        size = os.path.getsize(f) / (1024 * 1024)
        print(f"  • {name:<48} {int(dur // 60):>3}m {int(dur % 60):02d}s  ({size:.1f} MB)")
    print(f"\n  Total audio: {int(total_duration // 60)}m {int(total_duration % 60):02d}s")
    print()


    print("  Loading models...")
    try:
        from speechbrain.inference.speaker import EncoderClassifier

        EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="/tmp/speechbrain_ecapa",
            run_opts={"device": "cpu"},
        )
        print("  ✓ SpeechBrain ECAPA-TDNN loaded")
    except Exception as e:
        print(f"  ⚠ SpeechBrain: {e}")


    result = subprocess.run(["which", "whisper-cli"], capture_output=True, text=True)
    if result.returncode != 0:

        result = subprocess.run(["bash", "-lc", "which whisper"], capture_output=True, text=True)
    print(f"  ✓ Whisper model: {os.path.basename(WHISPER_MODEL)}")
    print()


    start = time.time()
    results = []

    if args.workers == 1:
        for i, f in enumerate(audio_files, 1):
            r = process_file(f, output_dir, i, len(audio_files))
            results.append(r)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_file, f, output_dir, i, len(audio_files)): f
                for i, f in enumerate(audio_files, 1)
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())


    elapsed = time.time() - start
    ok = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] == "error"]
    total_words = sum(r.get("words", 0) for r in ok)

    print()
    print("=" * 60)
    print("  TRANSCRIPTION COMPLETE")
    print("=" * 60)
    print(f"  Files processed: {len(ok)}/{len(audio_files)}")
    print(f"  Total words: {total_words}")
    print(f"  Errors: {len(errors)}")
    print(f"  Total time: {elapsed:.0f}s ({elapsed / 60:.1f}m)")
    if errors:
        print("\n  Errors:")
        for e in errors:
            print(f"    • {e['file']}: {e.get('error', 'unknown')}")
    print("=" * 60)


    manifest = {
        "pipeline": "sbk-audio-transcription",
        "version": "1.0",
        "transcribed_at": datetime.now().isoformat(),
        "config": {
            "whisper_model": "large-v3-turbo",
            "diarization": "speechbrain-ecapa-voxceleb",
            "language": LANGUAGE,
        },
        "files": results,
        "stats": {
            "total_files": len(audio_files),
            "successful": len(ok),
            "errors": len(errors),
            "total_words": total_words,
            "total_elapsed_seconds": round(elapsed, 1),
        },
    }
    manifest_path = os.path.join(output_dir, "_manifest.json")
    safe_write_json(manifest_path, manifest)
    print(f"\n  Manifest: {manifest_path}")


if __name__ == "__main__":

    try:
        import sklearn
    except ImportError:
        print("Installing scikit-learn...")
        subprocess.run([sys.executable, "-m", "pip", "install", "scikit-learn"], check=True)

    main()
