""




















from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("asr.router")



CONFIG_PATH = Path(os.path.expanduser("~/.sbk-data/asr-routing-config.json"))
DEFAULT_WHISPER_MODELS_DIR = Path.home() / "whisper-models"
DEFAULT_QWEN_ASR_DIR = Path("/tmp/qwen-asr")


MODEL_PREFERENCE_ORDER = [
    "whisper-large-v3-full",
    "qwen3-asr-1.7b",
    "cohere-transcribe",
    "qwen3-asr-0.6b",
    "whisper-large-v3-turbo",
]


FALLBACK_ORDER = [
    "whisper-large-v3-full",
    "qwen3-asr-1.7b",
    "whisper-large-v3-turbo",
    "qwen3-asr-0.6b",
]





@dataclass
class ModelConfig:
    ""

    model_id: str
    model_type: str
    binary: str = ""
    model_path: str = ""
    model_dir: str = ""
    model_hf_id: str = ""
    languages: list[str] = field(default_factory=lambda: ["auto"])
    max_threads: int = 4
    enabled: bool = False

    def is_available(self) -> bool:
        ""
        if not self.enabled:
            return False

        if self.model_type == "whisper-cpp":
            binary_ok = shutil.which(self.binary) is not None
            model_ok = Path(os.path.expanduser(self.model_path)).exists()
            return binary_ok and model_ok

        elif self.model_type == "qwen-asr":
            binary_path = Path(os.path.expanduser(self.binary))
            model_dir = Path(os.path.expanduser(self.model_dir))
            return binary_path.exists() and model_dir.exists()

        elif self.model_type == "mlx-audio":
            try:
                import mlx_audio  # noqa: F401

                return True
            except ImportError:
                return False

        return False


@dataclass
class TranscriptionRequest:
    ""

    audio_path: str
    language_hint: str = "auto"
    force_model: str | None = None
    prompt: str = ""
    extra_context: dict = field(default_factory=dict)


@dataclass
class TranscriptionSegment:
    ""

    start: str
    end: str
    text: str
    speaker: str = ""


@dataclass
class TranscriptionResult:
    ""

    text: str
    segments: list[TranscriptionSegment]
    model_used: str
    language_detected: str = "auto"
    duration_s: float = 0.0
    word_count: int = 0
    elapsed_s: float = 0.0
    quality_check: str = "ok"
    fallback_used: bool = False
    fallback_reason: str = ""





def _has_repeated_ngrams(words: list[str], window: int = 5, threshold: int = 3) -> bool:
    ""
    if len(words) < window * threshold:
        return False

    for i in range(len(words) - window * threshold + 1):
        ngram = tuple(words[i : i + window])
        count = 1
        pos = i + window
        while pos + window <= len(words):
            next_ngram = tuple(words[pos : pos + window])
            if next_ngram == ngram:
                count += 1
                pos += window
                if count >= threshold:
                    return True
            else:
                break

    return False


def check_transcription_quality(
    text: str,
    duration_s: float,
    min_wpm: float = 15.0,
) -> str:
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





def _convert_to_wav(audio_path: str) -> str | None:
    ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True,
            timeout=120,
        )
        if r.returncode != 0 or not Path(wav_path).exists():
            Path(wav_path).unlink(missing_ok=True)
            return None
        return wav_path
    except Exception as e:
        log.error("ffmpeg error: %s", e)
        Path(wav_path).unlink(missing_ok=True)
        return None


def _get_audio_duration(audio_path: str) -> float:
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
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _transcribe_whisper_cpp(
    audio_path: str,
    model_config: ModelConfig,
    language: str = "auto",
    prompt: str = "",
    timeout_s: int = 14400,
) -> TranscriptionResult | None:
    ""
    model_path = os.path.expanduser(model_config.model_path)

    wav_path = _convert_to_wav(audio_path)
    if not wav_path:
        return None

    t0 = time.time()

    try:
        cmd = [
            model_config.binary,
            "-m",
            model_path,
            "-l",
            language,
            "-t",
            str(model_config.max_threads),
            "--vad",
            "--vad-threshold",
            "0.40",
            "--vad-min-speech-duration-ms",
            "300",
            "--vad-min-silence-duration-ms",
            "2000",
            "-et",
            "2.4",
            "-lpt",
            "-0.5",
            "-nth",
            "0.3",
            "--suppress-nst",
            "-f",
            wav_path,
        ]
        if prompt:
            cmd.extend(["--prompt", prompt, "--carry-initial-prompt"])

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        Path(wav_path).unlink(missing_ok=True)
        log.error("Whisper timeout for %s", audio_path)
        return None
    except Exception as e:
        Path(wav_path).unlink(missing_ok=True)
        log.error("Whisper error: %s", e)
        return None

    Path(wav_path).unlink(missing_ok=True)
    elapsed = time.time() - t0


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
                segments.append(TranscriptionSegment(start=start_str, end=end_str, text=text))

    full_text = " ".join(s.text for s in segments)
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

    return TranscriptionResult(
        text=full_text,
        segments=segments,
        model_used=model_config.model_id,
        language_detected=lang_detected,
        word_count=word_count,
        elapsed_s=round(elapsed, 1),
    )


def _transcribe_qwen_asr(
    audio_path: str,
    model_config: ModelConfig,
    language: str = "auto",
    prompt: str = "",
    timeout_s: int = 14400,
) -> TranscriptionResult | None:
    ""
    binary = os.path.expanduser(model_config.binary)
    model_dir = os.path.expanduser(model_config.model_dir)

    if not Path(binary).exists():
        log.error("qwen-asr binary not found: %s", binary)
        return None

    wav_path = _convert_to_wav(audio_path)
    if not wav_path:
        return None

    t0 = time.time()

    try:
        cmd = [binary, "-d", model_dir, "-i", wav_path]
        if language != "auto":
            lang_names = {
                "it": "Italian",
                "en": "English",
                "es": "Spanish",
                "fr": "French",
                "de": "German",
                "zh": "Chinese",
                "ko": "Korean",
                "ja": "Japanese",
                "pt": "Portuguese",
            }
            lang_name = lang_names.get(language)
            if lang_name:
                cmd.extend(["--language", lang_name])

        if prompt:
            cmd.extend(["--prompt", prompt])

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        output = r.stdout
    except subprocess.TimeoutExpired:
        Path(wav_path).unlink(missing_ok=True)
        return None
    except Exception as e:
        Path(wav_path).unlink(missing_ok=True)
        log.error("qwen-asr error: %s", e)
        return None

    Path(wav_path).unlink(missing_ok=True)
    elapsed = time.time() - t0

    full_text = output.strip()
    word_count = len(full_text.split()) if full_text else 0

    segments = []
    if full_text:
        segments = [TranscriptionSegment(start="00:00:00.000", end="00:00:00.000", text=full_text)]

    return TranscriptionResult(
        text=full_text,
        segments=segments,
        model_used=model_config.model_id,
        language_detected=language,
        word_count=word_count,
        elapsed_s=round(elapsed, 1),
    )


def _transcribe_mlx_audio(
    audio_path: str,
    model_config: ModelConfig,
    language: str = "auto",
    prompt: str = "",
    timeout_s: int = 14400,
) -> TranscriptionResult | None:
    ""
    try:
        from mlx_audio.stt import transcribe as mlx_transcribe
    except ImportError:
        log.error("mlx-audio not installed")
        return None

    t0 = time.time()

    try:
        result = mlx_transcribe(
            audio_path,
            model=model_config.model_hf_id,
            language=language if language != "auto" else None,
        )

        full_text = result.get("text", "").strip()
        word_count = len(full_text.split()) if full_text else 0

        segments = []
        for seg in result.get("segments", []):
            segments.append(
                TranscriptionSegment(
                    start=seg.get("start", ""),
                    end=seg.get("end", ""),
                    text=seg.get("text", "").strip(),
                )
            )

        elapsed = time.time() - t0

        return TranscriptionResult(
            text=full_text,
            segments=segments,
            model_used=model_config.model_id,
            language_detected=result.get("language", language),
            word_count=word_count,
            elapsed_s=round(elapsed, 1),
        )
    except Exception as e:
        log.error("mlx-audio transcription failed: %s", e)
        return None


_BACKENDS = {
    "whisper-cpp": _transcribe_whisper_cpp,
    "qwen-asr": _transcribe_qwen_asr,
    "mlx-audio": _transcribe_mlx_audio,
}





def _default_model_configs() -> dict[str, ModelConfig]:
    ""
    return {
        "whisper-large-v3-full": ModelConfig(
            model_id="whisper-large-v3-full",
            model_type="whisper-cpp",
            binary="whisper-cli",
            model_path=str(DEFAULT_WHISPER_MODELS_DIR / "ggml-large-v3.bin"),
            languages=["auto"],
            max_threads=4,
            enabled=True,
        ),
        "whisper-large-v3-turbo": ModelConfig(
            model_id="whisper-large-v3-turbo",
            model_type="whisper-cpp",
            binary="whisper-cli",
            model_path=str(DEFAULT_WHISPER_MODELS_DIR / "ggml-large-v3-turbo.bin"),
            languages=["auto"],
            max_threads=4,
            enabled=True,
        ),
        "qwen3-asr-1.7b": ModelConfig(
            model_id="qwen3-asr-1.7b",
            model_type="qwen-asr",
            binary=str(DEFAULT_QWEN_ASR_DIR / "qwen_asr"),
            model_dir=str(DEFAULT_QWEN_ASR_DIR / "qwen3-asr-1.7b"),
            languages=["auto"],
            enabled=True,
        ),
        "qwen3-asr-0.6b": ModelConfig(
            model_id="qwen3-asr-0.6b",
            model_type="qwen-asr",
            binary=str(DEFAULT_QWEN_ASR_DIR / "qwen_asr"),
            model_dir=str(DEFAULT_QWEN_ASR_DIR / "qwen3-asr-0.6b"),
            languages=["auto"],
            enabled=False,
        ),
        "cohere-transcribe": ModelConfig(
            model_id="cohere-transcribe",
            model_type="mlx-audio",
            model_hf_id="mlx-community/cohere-transcribe-03-2026-4bit",
            languages=["auto"],
            enabled=False,
        ),
    }





class ASRRouter:
    ""






    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else CONFIG_PATH
        self.models: dict[str, ModelConfig] = _default_model_configs()

        if self.config_path.exists():
            self._load_config()

        self._available_models: list[str] = []
        self._refresh_available()

    def _load_config(self):
        ""
        try:
            config = json.loads(self.config_path.read_text())
            asr = config.get("asr_routing", config)
            for model_id, model_data in asr.get("models", {}).items():
                if model_id in self.models:
                    for key, val in model_data.items():
                        if hasattr(self.models[model_id], key):
                            setattr(self.models[model_id], key, val)
        except Exception as e:
            log.warning("Failed to load ASR config: %s", e)

    def _refresh_available(self):
        ""
        self._available_models = [
            m for m in MODEL_PREFERENCE_ORDER if m in self.models and self.models[m].is_available()
        ]
        if self._available_models:
            log.info("ASR models available (best first): %s", self._available_models)
        else:
            log.warning("No ASR models available!")

    def get_best_model(self) -> str | None:
        ""
        return self._available_models[0] if self._available_models else None

    def get_available_models(self) -> list[str]:
        ""
        return list(self._available_models)

    def _get_fallbacks(self, exclude: str) -> list[str]:
        ""
        return [m for m in FALLBACK_ORDER if m != exclude and m in self._available_models]

    def _run_model(
        self,
        model_id: str,
        request: TranscriptionRequest,
        duration_s: float,
    ) -> TranscriptionResult | None:
        ""
        config = self.models[model_id]
        backend = _BACKENDS.get(config.model_type)
        if not backend:
            log.error("No backend for model type: %s", config.model_type)
            return None

        result = backend(
            request.audio_path,
            config,
            language=request.language_hint,
            prompt=request.prompt,
        )

        if result:
            result.duration_s = duration_s
            result.quality_check = check_transcription_quality(result.text, duration_s)

        return result

    def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        ""












        duration_s = _get_audio_duration(request.audio_path)


        parallel_threshold = request.extra_context.get("parallel_threshold_s", 3600)
        if duration_s > parallel_threshold and not request.extra_context.get("no_parallel"):
            return self._transcribe_parallel(request, duration_s)


        if request.force_model and request.force_model in self._available_models:
            result = self._run_model(request.force_model, request, duration_s)
            if result:
                return result


        best_model = self.get_best_model()
        if not best_model:
            return TranscriptionResult(
                text="",
                segments=[],
                model_used="none",
                quality_check="no_models_available",
            )

        result = self._run_model(best_model, request, duration_s)


        if result and result.quality_check == "ok":
            return result


        primary_reason = "crash" if not result else result.quality_check
        log.warning("Primary model %s: %s. Trying fallbacks.", best_model, primary_reason)

        for fallback_id in self._get_fallbacks(best_model):
            log.info("Trying fallback model: %s", fallback_id)
            fb_result = self._run_model(fallback_id, request, duration_s)

            if fb_result and fb_result.quality_check == "ok":
                fb_result.fallback_used = True
                fb_result.fallback_reason = f"Primary {best_model} failed: {primary_reason}"
                return fb_result


        if result:
            result.fallback_used = False
            return result

        return TranscriptionResult(
            text="",
            segments=[],
            model_used="none",
            quality_check="all_models_failed",
        )

    def _transcribe_parallel(
        self, request: TranscriptionRequest, duration_s: float
    ) -> TranscriptionResult:
        ""




        try:
            from lib.parallel_transcribe import ParallelTranscriber, TranscribeConfig
        except ImportError:
            log.warning("parallel_transcribe not available, falling back to sequential")
            return self._run_model(
                self.get_best_model() or "whisper-large-v3-turbo", request, duration_s
            )


        best = self.get_best_model()
        if not best:
            return TranscriptionResult(
                text="",
                segments=[],
                model_used="none",
                quality_check="no_models_available",
            )
        model_config = self.models[best]


        if model_config.model_type != "whisper-cpp":
            log.info("Parallel pipeline only supports whisper-cpp, falling back to sequential")
            return self._run_model(best, request, duration_s)


        workers = request.extra_context.get("workers", 4)
        gpu_workers = request.extra_context.get("gpu_workers", 1)

        config = TranscribeConfig(
            model_path=model_config.model_path,
            whisper_binary=model_config.binary,
            language=request.language_hint,
            prompt=request.prompt,
            workers=workers,
            gpu_workers=gpu_workers,
            threads_per_gpu_worker=model_config.max_threads,
            threads_per_cpu_worker=max(2, model_config.max_threads - 1),
        )

        transcriber = ParallelTranscriber(config)
        par_result = transcriber.transcribe(request.audio_path)


        segments = [
            TranscriptionSegment(
                start=s.get("start_str", ""),
                end=s.get("end_str", ""),
                text=s.get("text", ""),
            )
            for s in par_result.segments
        ]

        quality = "ok"
        if par_result.quality_warnings:
            quality = "warnings"

        return TranscriptionResult(
            text=par_result.text,
            segments=segments,
            model_used=f"{par_result.model_used} (parallel x{par_result.workers_used})",
            language_detected=par_result.language_detected,
            duration_s=duration_s,
            word_count=par_result.word_count,
            elapsed_s=par_result.elapsed_s,
            quality_check=quality,
        )

    def to_dict(self) -> dict:
        ""
        return {
            "available_models": self._available_models,
            "best_model": self.get_best_model(),
            "models": {k: asdict(v) for k, v in self.models.items()},
        }
