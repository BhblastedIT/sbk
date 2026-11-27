"""Audio recording classifier: tells a voice memo from a meeting, a call or a lecture, from metadata, spectrum,
speech patterns, speaker count and transcript, and suggests the transcription settings for each kind.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)





class AudioCategory(StrEnum):
    VOICE_MEMO = "voice_memo"
    ONE_ON_ONE = "one_on_one"
    SMALL_MEETING = "small_meeting"
    LARGE_MEETING = "large_meeting"
    PHONE_CALL = "phone_call"




PIPELINE_PARAMS = {
    AudioCategory.VOICE_MEMO: {
        "run_diarization": False,
        "min_speakers": 1,
        "max_speakers": 1,
        "asr_model": "large-v3-turbo",
        "attempt_speaker_id": False,
        "priority": 2,
        "quality_tier": "fast",
    },
    AudioCategory.ONE_ON_ONE: {
        "run_diarization": True,
        "min_speakers": 2,
        "max_speakers": 2,
        "asr_model": "large-v3-turbo",
        "attempt_speaker_id": True,
        "priority": 1,
        "quality_tier": "standard",
    },
    AudioCategory.SMALL_MEETING: {
        "run_diarization": True,
        "min_speakers": 3,
        "max_speakers": 5,
        "asr_model": "large-v3-turbo",
        "attempt_speaker_id": True,
        "priority": 1,
        "quality_tier": "standard",
    },
    AudioCategory.LARGE_MEETING: {
        "run_diarization": True,
        "min_speakers": 4,
        "max_speakers": 12,
        "asr_model": "large-v3-turbo",
        "attempt_speaker_id": True,
        "priority": 3,
        "quality_tier": "thorough",
    },
    AudioCategory.PHONE_CALL: {
        "run_diarization": True,
        "min_speakers": 2,
        "max_speakers": 2,
        "asr_model": "large-v3-turbo",
        "attempt_speaker_id": True,
        "priority": 1,
        "quality_tier": "standard",
        "audio_preprocessing": "upsample_narrowband",
    },
}





@dataclass
class SignalResult:
    ""

    name: str
    category: AudioCategory | None
    confidence: float
    details: dict = field(default_factory=dict)


@dataclass
class AudioClassification:
    ""

    file_path: str
    category: AudioCategory
    confidence: float
    signals: list[SignalResult]
    pipeline_params: dict
    duration_seconds: float
    classification_time_ms: float
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        for s in d["signals"]:
            if s["category"] is not None:
                s["category"] = (
                    s["category"].value if hasattr(s["category"], "value") else s["category"]
                )
        return d




SAMPLE_RATE = 16000


def load_audio_mono(
    path: str | Path, sr: int = SAMPLE_RATE, max_duration: float | None = None
) -> tuple[np.ndarray, int]:
    ""




    path = Path(path)


    try:
        import soundfile as sf

        info = sf.info(str(path))
        original_sr = info.samplerate
        frames_to_read = None
        if max_duration is not None:
            frames_to_read = int(max_duration * original_sr)

        audio, file_sr = sf.read(str(path), frames=frames_to_read, dtype="float32", always_2d=False)


        if audio.ndim > 1:
            audio = audio.mean(axis=1)


        if file_sr != sr:
            audio = _resample(audio, file_sr, sr)

        return audio, sr

    except Exception:
        pass


    duration_args = []
    if max_duration is not None:
        duration_args = ["-t", str(max_duration)]

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        *duration_args,
        "-ar",
        str(sr),
        "-ac",
        "1",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {path}: {result.stderr[:300]}")

    audio = np.frombuffer(result.stdout, dtype=np.float32)
    return audio, sr


def get_duration(path: str | Path) -> float:
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    ""
    from scipy.signal import resample

    num_samples = int(len(audio) * target_sr / orig_sr)
    return resample(audio, num_samples).astype(np.float32)







def signal_metadata(
    file_path: Path,
    duration_sec: float,
    plaud_scene: int | None = None,
    plaud_category: str | None = None,
    calendar_match: dict | None = None,
    n_attendees: int | None = None,
) -> SignalResult:
    ""







    votes: dict[AudioCategory, float] = dict.fromkeys(AudioCategory, 0.0)
    reasons = []

    filename = file_path.stem.lower()


    if plaud_scene is not None:
        if plaud_scene == 102:
            votes[AudioCategory.PHONE_CALL] += 0.7
            reasons.append("plaud_scene=102 (phone call mode)")
        elif plaud_scene == 101:
            votes[AudioCategory.VOICE_MEMO] += 0.5
            reasons.append("plaud_scene=101 (location/voice memo mode)")
        elif plaud_scene == 7:
            votes[AudioCategory.ONE_ON_ONE] += 0.3
            reasons.append("plaud_scene=7 (consultation)")



    if plaud_category == "monologue":
        votes[AudioCategory.VOICE_MEMO] += 0.6
        reasons.append("plaud_category=monologue")


    voice_memo_patterns = [
        "new recording",
        "audio clip",
        "voice memo",
        "nota vocale",
        "recording",
        "memo",
        "appunto",
    ]
    meeting_patterns = [
        "riunione",
        "meeting",
        "standup",
        "weekly",
        "sprint",
        "sync",
        "settimanale",
        "aggiornamento",
        "briefing",
        "brainstorm",
    ]
    call_patterns = [
        "telefonata",
        "phone",
        "chiamata",
        "call",
        "riepilogo telefonata",
    ]

    for pat in voice_memo_patterns:
        if pat in filename:
            votes[AudioCategory.VOICE_MEMO] += 0.3
            reasons.append(f"filename contains '{pat}'")
            break

    for pat in meeting_patterns:
        if pat in filename:
            votes[AudioCategory.SMALL_MEETING] += 0.25
            reasons.append(f"filename contains '{pat}'")
            break

    for pat in call_patterns:
        if pat in filename:
            votes[AudioCategory.PHONE_CALL] += 0.3
            reasons.append(f"filename contains '{pat}'")
            break



    is_location_name = (
        not any(pat in filename for pat in voice_memo_patterns + meeting_patterns + call_patterns)
        and not filename[0].isdigit()
        and len(filename.split()) <= 4
        and plaud_scene == 101
    )
    if is_location_name:
        votes[AudioCategory.VOICE_MEMO] += 0.3
        reasons.append("location-based filename (likely voice memo)")


    if duration_sec < 120:
        votes[AudioCategory.VOICE_MEMO] += 0.3
        reasons.append(f"very short ({duration_sec / 60:.1f}m)")
    elif duration_sec < 600:
        votes[AudioCategory.VOICE_MEMO] += 0.1
        votes[AudioCategory.ONE_ON_ONE] += 0.15
        reasons.append(f"short ({duration_sec / 60:.1f}m)")
    elif duration_sec < 2400:
        votes[AudioCategory.ONE_ON_ONE] += 0.1
        votes[AudioCategory.SMALL_MEETING] += 0.1
        reasons.append(f"medium ({duration_sec / 60:.1f}m)")
    elif duration_sec < 5400:
        votes[AudioCategory.SMALL_MEETING] += 0.15
        votes[AudioCategory.LARGE_MEETING] += 0.1
        reasons.append(f"long ({duration_sec / 60:.1f}m)")
    else:
        votes[AudioCategory.LARGE_MEETING] += 0.2
        reasons.append(f"very long ({duration_sec / 60:.1f}m)")


    if n_attendees is not None:
        if n_attendees <= 1:
            votes[AudioCategory.VOICE_MEMO] += 0.2
            reasons.append(f"calendar: {n_attendees} attendees")
        elif n_attendees == 2:
            votes[AudioCategory.ONE_ON_ONE] += 0.4
            reasons.append("calendar: 2 attendees")
        elif n_attendees <= 5:
            votes[AudioCategory.SMALL_MEETING] += 0.4
            reasons.append(f"calendar: {n_attendees} attendees")
        else:
            votes[AudioCategory.LARGE_MEETING] += 0.4
            reasons.append(f"calendar: {n_attendees} attendees")


    best_cat = max(votes, key=lambda c: votes[c])
    best_score = votes[best_cat]

    if best_score < 0.1:
        return SignalResult(
            name="metadata",
            category=None,
            confidence=0.0,
            details={"reasons": reasons, "votes": {c.value: round(v, 2) for c, v in votes.items()}},
        )


    confidence = min(1.0, best_score)

    return SignalResult(
        name="metadata",
        category=best_cat,
        confidence=round(confidence, 2),
        details={"reasons": reasons, "votes": {c.value: round(v, 2) for c, v in votes.items()}},
    )







def signal_spectral(audio: np.ndarray, sr: int = SAMPLE_RATE) -> SignalResult:
    ""











    from scipy.signal import welch


    nperseg = min(4096, len(audio))
    freqs, psd = welch(audio, fs=sr, nperseg=nperseg)

    if len(psd) == 0 or psd.sum() == 0:
        return SignalResult(
            name="spectral", category=None, confidence=0.0, details={"error": "empty spectrum"}
        )

    total_energy = psd.sum()


    tel_mask = (freqs >= 300) & (freqs <= 3400)
    tel_energy = psd[tel_mask].sum()
    tel_ratio = tel_energy / total_energy


    hf_mask = freqs >= 4000
    hf_energy = psd[hf_mask].sum()
    hf_ratio = hf_energy / total_energy


    lf_mask = freqs <= 200
    lf_energy = psd[lf_mask].sum()
    lf_ratio = lf_energy / total_energy


    centroid = np.sum(freqs * psd) / total_energy if total_energy > 0 else 0


    cumulative = np.cumsum(psd) / total_energy
    bw_95_idx = np.searchsorted(cumulative, 0.95)
    effective_bw = freqs[min(bw_95_idx, len(freqs) - 1)]








    narrowband_score = 0.0


    if tel_ratio > 0.85:
        narrowband_score += 0.4
    elif tel_ratio > 0.75:
        narrowband_score += 0.2


    if hf_ratio < 0.02:
        narrowband_score += 0.3
    elif hf_ratio < 0.05:
        narrowband_score += 0.15


    if effective_bw < 4000:
        narrowband_score += 0.3
    elif effective_bw < 5000:
        narrowband_score += 0.1

    is_narrowband = narrowband_score >= 0.5

    details = {
        "telephony_band_ratio": round(tel_ratio, 3),
        "high_freq_ratio": round(hf_ratio, 3),
        "low_freq_ratio": round(lf_ratio, 3),
        "spectral_centroid_hz": round(centroid, 1),
        "effective_bandwidth_hz": round(effective_bw, 1),
        "narrowband_score": round(narrowband_score, 2),
        "is_narrowband": is_narrowband,
    }

    if is_narrowband:



        return SignalResult(
            name="spectral",
            category=AudioCategory.PHONE_CALL,
            confidence=round(min(0.6, narrowband_score * 0.6), 2),
            details=details,
        )


    return SignalResult(name="spectral", category=None, confidence=0.0, details=details)







def _compute_energy_vad(audio: np.ndarray, sr: int, frame_ms: int = 30) -> np.ndarray:
    ""



    frame_size = int(sr * frame_ms / 1000)
    hop_size = frame_size

    n_frames = len(audio) // hop_size
    if n_frames == 0:
        return np.array([False])


    energies = np.array(
        [
            np.sqrt(np.mean(audio[i * hop_size : i * hop_size + frame_size] ** 2))
            for i in range(n_frames)
        ]
    )


    if len(energies) == 0:
        return np.array([False])

    log_e = np.log(energies + 1e-10)
    threshold = np.percentile(log_e, 35)
    is_speech = log_e > threshold

    return is_speech


def _try_silero_vad(audio: np.ndarray, sr: int) -> np.ndarray | None:
    ""





    try:
        import torch

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            verbose=False,
        )
        (get_speech_timestamps, _, _, _, _) = utils


        if sr != 16000:
            audio = _resample(audio, sr, 16000)
            sr = 16000

        audio_tensor = torch.from_numpy(audio).float()


        speech_ts = get_speech_timestamps(
            audio_tensor,
            model,
            sampling_rate=sr,
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=100,
        )


        frame_ms = 30
        n_frames = int(len(audio) / sr * 1000 / frame_ms)
        is_speech = np.zeros(n_frames, dtype=bool)

        for ts in speech_ts:
            start_frame = int(ts["start"] / sr * 1000 / frame_ms)
            end_frame = int(ts["end"] / sr * 1000 / frame_ms)
            is_speech[start_frame : min(end_frame, n_frames)] = True

        return is_speech

    except Exception as e:
        log.debug("Silero VAD not available: %s", e)
        return None


def signal_speech_patterns(audio: np.ndarray, sr: int = SAMPLE_RATE) -> SignalResult:
    ""








    frame_ms = 30


    is_speech = _try_silero_vad(audio, sr)
    vad_method = "silero"
    if is_speech is None:
        is_speech = _compute_energy_vad(audio, sr, frame_ms)
        vad_method = "energy"

    n_frames = len(is_speech)
    if n_frames == 0:
        return SignalResult(
            name="speech_patterns", category=None, confidence=0.0, details={"error": "no frames"}
        )

    duration_sec = n_frames * frame_ms / 1000
    speech_ratio = is_speech.sum() / n_frames


    raw_segments = []
    in_seg = False
    seg_start = 0
    for i in range(n_frames):
        if is_speech[i] and not in_seg:
            seg_start = i
            in_seg = True
        elif not is_speech[i] and in_seg:
            seg_duration = (i - seg_start) * frame_ms / 1000
            if seg_duration >= 0.2:
                raw_segments.append((seg_start, i, seg_duration))
            in_seg = False
    if in_seg:
        seg_duration = (n_frames - seg_start) * frame_ms / 1000
        if seg_duration >= 0.2:
            raw_segments.append((seg_start, n_frames, seg_duration))

    if not raw_segments:
        return SignalResult(
            name="speech_patterns",
            category=None,
            confidence=0.0,
            details={"error": "no speech segments"},
        )





    MERGE_GAP_SEC = 1.5
    merge_gap_frames = int(MERGE_GAP_SEC * 1000 / frame_ms)

    merged_segments = [raw_segments[0]]
    for seg in raw_segments[1:]:
        gap = seg[0] - merged_segments[-1][1]
        if gap < merge_gap_frames:

            new_end = seg[1]
            new_dur = (new_end - merged_segments[-1][0]) * frame_ms / 1000
            merged_segments[-1] = (merged_segments[-1][0], new_end, new_dur)
        else:
            merged_segments.append(seg)

    segments = merged_segments
    n_segments = len(segments)

    segment_durations = [s[2] for s in segments]
    longest_segment = max(segment_durations)
    mean_segment = np.mean(segment_durations)
    median_segment = np.median(segment_durations)



    silence_gaps = []
    for i in range(1, len(segments)):
        gap = (segments[i][0] - segments[i - 1][1]) * frame_ms / 1000
        if gap > 0.1:
            silence_gaps.append(gap)

    mean_gap = np.mean(silence_gaps) if silence_gaps else 0
    n_gaps = len(silence_gaps)


    turn_density = n_segments / (duration_sec / 60) if duration_sec > 0 else 0


    long_speech_ratio = (
        sum(d for d in segment_durations if d > 10) / duration_sec if duration_sec > 0 else 0
    )


    votes: dict[AudioCategory, float] = dict.fromkeys(AudioCategory, 0.0)







    if speech_ratio > 0.65 and turn_density < 10:
        votes[AudioCategory.VOICE_MEMO] += 0.3
    if longest_segment > 15 and long_speech_ratio > 0.3:
        votes[AudioCategory.VOICE_MEMO] += 0.25
    if turn_density < 6 and speech_ratio > 0.5:
        votes[AudioCategory.VOICE_MEMO] += 0.25
    if mean_segment > 8:
        votes[AudioCategory.VOICE_MEMO] += 0.15




    if 6 < turn_density < 15:
        votes[AudioCategory.ONE_ON_ONE] += 0.25
        votes[AudioCategory.SMALL_MEETING] += 0.1
    if turn_density >= 15:
        votes[AudioCategory.SMALL_MEETING] += 0.2
        votes[AudioCategory.LARGE_MEETING] += 0.2

    if 0.35 < speech_ratio < 0.75 and turn_density > 6:
        votes[AudioCategory.ONE_ON_ONE] += 0.15
        votes[AudioCategory.SMALL_MEETING] += 0.15


    if turn_density > 15 and 0.3 < speech_ratio < 0.7:
        votes[AudioCategory.LARGE_MEETING] += 0.2


    if mean_segment < 5 and n_gaps > 8:
        votes[AudioCategory.SMALL_MEETING] += 0.15
        votes[AudioCategory.ONE_ON_ONE] += 0.1

    best_cat = max(votes, key=lambda c: votes[c])
    best_score = votes[best_cat]

    details = {
        "vad_method": vad_method,
        "duration_sec": round(duration_sec, 1),
        "speech_ratio": round(speech_ratio, 3),
        "n_speech_segments": n_segments,
        "longest_segment_sec": round(longest_segment, 1),
        "mean_segment_sec": round(mean_segment, 1),
        "median_segment_sec": round(median_segment, 1),
        "long_speech_ratio": round(long_speech_ratio, 3),
        "turn_density_per_min": round(turn_density, 1),
        "n_silence_gaps": n_gaps,
        "mean_gap_sec": round(mean_gap, 2),
        "votes": {c.value: round(v, 2) for c, v in votes.items()},
    }

    if best_score < 0.1:
        return SignalResult(name="speech_patterns", category=None, confidence=0.0, details=details)

    return SignalResult(
        name="speech_patterns",
        category=best_cat,
        confidence=round(min(1.0, best_score), 2),
        details=details,
    )







def signal_speaker_count(
    audio: np.ndarray, sr: int = SAMPLE_RATE, max_sample_sec: float = 120.0
) -> SignalResult:
    ""










    try:
        import importlib.util

        if (
            importlib.util.find_spec("torch") is None
            or importlib.util.find_spec("speechbrain") is None
        ):
            raise ImportError("torch or speechbrain not available")
        import torch as _torch
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError:
        return SignalResult(
            name="speaker_count",
            category=None,
            confidence=0.0,
            details={"error": "speechbrain not installed"},
        )


    try:
        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="/tmp/speechbrain_ecapa",
            run_opts={"device": "cpu"},
        )
    except Exception as e:
        return SignalResult(
            name="speaker_count",
            category=None,
            confidence=0.0,
            details={"error": f"model load failed: {e}"},
        )


    window_sec = 1.5
    window_samples = int(window_sec * sr)
    total_samples = len(audio)


    is_speech = _compute_energy_vad(audio, sr, frame_ms=30)
    frame_samples = int(sr * 30 / 1000)


    speech_frames = np.where(is_speech)[0]
    if len(speech_frames) < 10:
        return SignalResult(
            name="speaker_count",
            category=AudioCategory.VOICE_MEMO,
            confidence=0.3,
            details={"estimated_speakers": 1, "reason": "too little speech"},
        )



    max_windows = 40
    min_windows = 8


    speech_positions = speech_frames * frame_samples

    valid_positions = speech_positions[speech_positions + window_samples < total_samples]

    if len(valid_positions) < min_windows:
        return SignalResult(
            name="speaker_count",
            category=AudioCategory.VOICE_MEMO,
            confidence=0.3,
            details={"estimated_speakers": 1, "reason": "too few valid windows"},
        )


    step = max(1, len(valid_positions) // max_windows)
    sample_positions = valid_positions[::step][:max_windows]


    embeddings = []

    for pos in sample_positions:
        chunk = audio[pos : pos + window_samples]
        if len(chunk) < window_samples // 2:
            continue

        if len(chunk) < window_samples:
            chunk = np.pad(chunk, (0, window_samples - len(chunk)))

        chunk_tensor = _torch.from_numpy(chunk).unsqueeze(0).float()
        with _torch.no_grad():
            emb = classifier.encode_batch(chunk_tensor)
            embeddings.append(emb.squeeze().numpy())

    if len(embeddings) < min_windows:
        return SignalResult(
            name="speaker_count",
            category=AudioCategory.VOICE_MEMO,
            confidence=0.3,
            details={"estimated_speakers": 1, "n_embeddings": len(embeddings)},
        )

    embeddings_arr = np.array(embeddings)


    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score
    from sklearn.metrics.pairwise import cosine_distances

    dist_matrix = cosine_distances(embeddings_arr)

    best_k = 1
    best_silhouette = -1.0
    scores = {}

    for k in range(2, min(7, len(embeddings_arr))):
        try:
            clustering = AgglomerativeClustering(
                n_clusters=k,
                metric="precomputed",
                linkage="average",
            )
            labels = clustering.fit_predict(dist_matrix)
            score = silhouette_score(dist_matrix, labels, metric="precomputed")
            scores[k] = round(score, 3)
            if score > best_silhouette:
                best_silhouette = score
                best_k = k
        except Exception:
            continue


    if best_silhouette < 0.15:
        best_k = 1


    if best_k == 1:
        cat = AudioCategory.VOICE_MEMO
        confidence = 0.6 if best_silhouette < 0.1 else 0.4
    elif best_k == 2:
        cat = AudioCategory.ONE_ON_ONE
        confidence = 0.5 + min(0.3, best_silhouette)
    elif best_k <= 5:
        cat = AudioCategory.SMALL_MEETING
        confidence = 0.4 + min(0.3, best_silhouette)
    else:
        cat = AudioCategory.LARGE_MEETING
        confidence = 0.4 + min(0.2, best_silhouette)

    details = {
        "estimated_speakers": best_k,
        "best_silhouette": round(best_silhouette, 3),
        "silhouette_scores": scores,
        "n_embeddings": len(embeddings_arr),
        "n_windows_sampled": len(sample_positions),
    }

    return SignalResult(
        name="speaker_count",
        category=cat,
        confidence=round(min(1.0, confidence), 2),
        details=details,
    )








def signal_transcript(
    transcript_path: Path | None = None,
    speaker_analysis: dict | None = None,
) -> SignalResult:
    ""




    if speaker_analysis is None and transcript_path is not None:
        try:
            with open(transcript_path, encoding="utf-8") as f:
                segments = json.load(f)
            if isinstance(segments, list):
                speakers = set()
                transitions = 0
                prev_speaker = None
                for seg in segments:
                    sp = seg.get("speaker", seg.get("original_speaker", ""))
                    if sp:
                        speakers.add(sp)
                        if prev_speaker and sp != prev_speaker:
                            transitions += 1
                        prev_speaker = sp
                speaker_analysis = {
                    "speakers": list(speakers),
                    "speaker_transitions": transitions,
                    "segments": len(segments),
                }
        except Exception as e:
            return SignalResult(
                name="transcript", category=None, confidence=0.0, details={"error": str(e)}
            )

    if speaker_analysis is None:
        return SignalResult(
            name="transcript", category=None, confidence=0.0, details={"error": "no data"}
        )

    speakers = speaker_analysis.get("speakers", [])
    n_speakers = len(speakers) if isinstance(speakers, list) else speakers
    transitions = speaker_analysis.get("speaker_transitions", 0)
    n_segments = speaker_analysis.get("segments", 0)

    if n_speakers == 0 and n_segments == 0:
        return SignalResult(
            name="transcript", category=None, confidence=0.0, details={"n_speakers": 0}
        )


    if n_speakers <= 1 and transitions == 0:
        cat = AudioCategory.VOICE_MEMO
        confidence = 0.7
    elif n_speakers == 2:
        cat = AudioCategory.ONE_ON_ONE
        confidence = 0.6
    elif n_speakers <= 5:
        cat = AudioCategory.SMALL_MEETING
        confidence = 0.5
    else:
        cat = AudioCategory.LARGE_MEETING
        confidence = 0.5



    if cat == AudioCategory.VOICE_MEMO and transitions == 0:
        confidence = 0.8

    if cat == AudioCategory.ONE_ON_ONE and transitions > 20:
        confidence = 0.7

    details = {
        "n_speakers": n_speakers,
        "speaker_transitions": transitions,
        "n_segments": n_segments,
    }

    return SignalResult(
        name="transcript", category=cat, confidence=round(confidence, 2), details=details
    )







SIGNAL_WEIGHTS = {
    "metadata": 1.5,
    "spectral": 1.2,
    "speech_patterns": 1.5,
    "speaker_count": 2.5,
    "transcript": 2.0,
}


def classify_audio(
    file_path: str | Path,
    *,
    plaud_scene: int | None = None,
    plaud_category: str | None = None,
    calendar_match: dict | None = None,
    n_attendees: int | None = None,
    transcript_path: str | Path | None = None,
    speaker_analysis: dict | None = None,
    skip_audio_analysis: bool = False,
    max_audio_sample_sec: float = 180.0,
) -> AudioClassification:
    ""















    t0 = time.time()
    file_path = Path(file_path)
    signals: list[SignalResult] = []


    duration_sec = get_duration(file_path) if file_path.exists() else 0.0


    sig_meta = signal_metadata(
        file_path,
        duration_sec,
        plaud_scene=plaud_scene,
        plaud_category=plaud_category,
        calendar_match=calendar_match,
        n_attendees=n_attendees,
    )
    signals.append(sig_meta)


    if transcript_path or speaker_analysis:
        sig_trans = signal_transcript(
            transcript_path=Path(transcript_path) if transcript_path else None,
            speaker_analysis=speaker_analysis,
        )
        signals.append(sig_trans)


    if not skip_audio_analysis and file_path.exists():
        try:

            audio, sr = load_audio_mono(file_path, max_duration=max_audio_sample_sec)

            if len(audio) > sr * 0.5:

                sig_spec = signal_spectral(audio, sr)
                signals.append(sig_spec)


                sig_speech = signal_speech_patterns(audio, sr)
                signals.append(sig_speech)


                sig_spk = signal_speaker_count(audio, sr, max_sample_sec=max_audio_sample_sec)
                signals.append(sig_spk)

        except Exception as e:
            log.warning("Audio analysis failed for %s: %s", file_path, e)
            signals.append(
                SignalResult(
                    name="audio_error", category=None, confidence=0.0, details={"error": str(e)}
                )
            )


    category_scores: dict[AudioCategory, float] = dict.fromkeys(AudioCategory, 0.0)
    total_weight = 0.0

    for sig in signals:
        if sig.category is not None and sig.confidence > 0:
            weight = SIGNAL_WEIGHTS.get(sig.name, 1.0)
            category_scores[sig.category] += sig.confidence * weight
            total_weight += weight * sig.confidence


    if total_weight > 0:
        for c in category_scores:
            category_scores[c] /= total_weight


    best_category = max(category_scores, key=lambda c: category_scores[c])
    best_confidence = category_scores[best_category]


    if best_confidence == 0:
        best_category = AudioCategory.SMALL_MEETING
        best_confidence = 0.1





    spectral_sig = next((s for s in signals if s.name == "spectral"), None)
    speech_sig = next((s for s in signals if s.name == "speech_patterns"), None)
    is_narrowband = (
        spectral_sig is not None
        and spectral_sig.category == AudioCategory.PHONE_CALL
        and spectral_sig.confidence > 0
    )

    if is_narrowband and best_category == AudioCategory.PHONE_CALL:

        if speech_sig and speech_sig.category == AudioCategory.VOICE_MEMO:

            best_category = AudioCategory.VOICE_MEMO
            best_confidence = max(0.4, speech_sig.confidence)
    elif is_narrowband and best_category == AudioCategory.VOICE_MEMO:


        pass
    elif is_narrowband and best_category in (AudioCategory.ONE_ON_ONE, AudioCategory.SMALL_MEETING):

        best_category = AudioCategory.PHONE_CALL
        best_confidence = min(0.8, best_confidence + 0.1)

    elapsed_ms = (time.time() - t0) * 1000


    pipeline = dict(PIPELINE_PARAMS[best_category])
    if is_narrowband and "audio_preprocessing" not in pipeline:
        pipeline["is_narrowband"] = True

    return AudioClassification(
        file_path=str(file_path),
        category=best_category,
        confidence=round(best_confidence, 2),
        signals=signals,
        pipeline_params=pipeline,
        duration_seconds=round(duration_sec, 1),
        classification_time_ms=round(elapsed_ms, 1),
        metadata={
            "category_scores": {c.value: round(v, 3) for c, v in category_scores.items()},
            "plaud_scene": plaud_scene,
            "plaud_category": plaud_category,
        },
    )







def classify_plaud_corpus(
    plaud_dir: Path,
    skip_audio: bool = True,
) -> list[AudioClassification]:
    ""




    speaker_analysis_path = plaud_dir / "_speaker_analysis.json"
    file_index_path = plaud_dir / "_file_index.json"

    results = []


    sa_data = {}
    if speaker_analysis_path.exists():
        with open(speaker_analysis_path, encoding="utf-8") as f:
            sa_raw = json.load(f)
        for fi in sa_raw.get("files", []):
            sa_data[fi["filename"]] = fi


    scene_map = {}
    if file_index_path.exists():
        with open(file_index_path, encoding="utf-8") as f:
            idx = json.load(f)
        for entry in idx:
            scene_map[entry["filename"]] = entry.get("scene")


    for filename, file_info in sa_data.items():
        file_path = plaud_dir / filename


        plaud_scene = None
        fn_stem = filename.replace(".json", "")
        for idx_fn, scene in scene_map.items():
            if fn_stem[11:40] in idx_fn[:40]:
                plaud_scene = scene
                break

        result = classify_audio(
            file_path,
            plaud_scene=plaud_scene,
            plaud_category=file_info.get("category"),
            speaker_analysis=file_info,
            skip_audio_analysis=skip_audio,
        )
        results.append(result)

    return results







def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Audio Recording Classifier")
    parser.add_argument("files", nargs="*", help="Audio files to classify")
    parser.add_argument(
        "--plaud-corpus", action="store_true", help="Classify Plaud corpus (fast, transcript-based)"
    )
    parser.add_argument(
        "--skip-audio", action="store_true", help="Skip audio analysis (metadata + transcript only)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", action="store_true", help="Show detailed signal info")
    args = parser.parse_args()

    _TOOLS_DIR = Path(__file__).resolve().parent.parent
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))

    if args.plaud_corpus:
        from sbk_config import PLAUD_DIR

        print("=" * 70)
        print("AUDIO CLASSIFIER — Plaud Corpus Mode")
        print("=" * 70)

        results = classify_plaud_corpus(PLAUD_DIR, skip_audio=True)

        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
            return


        from collections import Counter

        cats = Counter(r.category.value for r in results)
        print(f"\nClassified {len(results)} files:")
        for cat, count in sorted(cats.items()):
            print(f"  {cat:20s}: {count:4d}")


        print("\nAvg confidence per category:")
        for cat in sorted(cats.keys()):
            avg = np.mean([r.confidence for r in results if r.category.value == cat])
            print(f"  {cat:20s}: {avg:.2f}")

        return

    if not args.files:
        parser.print_help()
        return

    for fp in args.files:
        path = Path(fp)
        if not path.exists():
            print(f"File not found: {fp}")
            continue

        print(f"\n{'=' * 70}")
        print(f"Classifying: {path.name}")
        print(f"{'=' * 70}")

        result = classify_audio(path, skip_audio_analysis=args.skip_audio)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            continue

        print(f"\n  Category:    {result.category.value}")
        print(f"  Confidence:  {result.confidence:.2f}")
        print(f"  Duration:    {result.duration_seconds / 60:.1f} min")
        print(f"  Time:        {result.classification_time_ms:.0f}ms")
        print("\n  Pipeline parameters:")
        for k, v in result.pipeline_params.items():
            print(f"    {k:25s}: {v}")

        if args.verbose:
            print("\n  Signals:")
            for sig in result.signals:
                cat_str = sig.category.value if sig.category else "none"
                print(f"    [{sig.name:20s}] {cat_str:20s} conf={sig.confidence:.2f}")
                for k, v in sig.details.items():
                    print(f"      {k}: {v}")

            print("\n  Category scores:")
            for cat, score in result.metadata.get("category_scores", {}).items():
                bar = "#" * int(score * 40)
                print(f"    {cat:20s}: {score:.3f} {bar}")


if __name__ == "__main__":
    main()
