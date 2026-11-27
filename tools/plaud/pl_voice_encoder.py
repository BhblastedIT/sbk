#!/usr/bin/env python3
""






















from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

EMBED_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
EMBED_DIM = 256


EncoderFn = Callable[[str], Any]


class VoiceEncoderError(RuntimeError):
    pass


class AudioNotFoundError(VoiceEncoderError):
    pass


class EncoderBackendError(VoiceEncoderError):
    ""


_INFERENCE_CACHE: Any = None


def is_backend_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _best_device() -> str:  # pragma: no cover - dipende dall'hardware
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _build_inference(device: str | None = None) -> Any:  # pragma: no cover - richiede modello
    if not is_backend_available():
        raise EncoderBackendError(
            "pyannote/torch not installed: voice embeddings cannot be extracted"
        )
    import torch
    from pyannote.audio import Inference, Model

    try:
        model = Model.from_pretrained(EMBED_MODEL)
    except Exception as e:  # noqa: BLE001
        raise EncoderBackendError(f"embedding model cannot be loaded ({EMBED_MODEL}): {e}") from e
    dev = device or _best_device()
    return Inference(model, window="whole", device=torch.device(dev))


def _default_encoder(wav_path: str) -> Any:  # pragma: no cover - richiede modello reale
    global _INFERENCE_CACHE
    if _INFERENCE_CACHE is None:
        _INFERENCE_CACHE = _build_inference()
    return _INFERENCE_CACHE(wav_path)


def to_wav16k(audio_path: str | Path, *, timeout: int = 120) -> str:
    ""



    src = Path(audio_path)
    if not src.exists():
        raise AudioNotFoundError(f"audio not found: {src}")
    wav = tempfile.mktemp(suffix=".wav")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", wav],
        capture_output=True,
        timeout=timeout,
    )
    if r.returncode != 0 or not Path(wav).exists():
        raise VoiceEncoderError(f"ffmpeg failed on {src.name}: {r.stderr[:200]!r}")
    return wav


def l2_normalize(vec: Any) -> Any:
    import numpy as np

    v = np.asarray(vec, dtype=float).flatten()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def embed_file(
    audio_path: str | Path,
    *,
    encoder: EncoderFn | None = None,
    normalize: bool = True,
) -> Any:
    ""



    import os

    wav = to_wav16k(audio_path)
    try:
        enc = encoder or _default_encoder
        raw = enc(wav)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
    return l2_normalize(raw) if normalize else raw


def embed_files_mean(
    audio_paths: list[str | Path],
    *,
    encoder: EncoderFn | None = None,
) -> Any:
    ""


    import numpy as np

    vecs = []
    for p in audio_paths:
        try:
            vecs.append(embed_file(p, encoder=encoder))
        except VoiceEncoderError:
            continue
    if not vecs:
        raise VoiceEncoderError("no valid clip for the centroid")
    m = np.mean(np.stack(vecs), axis=0)
    return l2_normalize(m)


def cosine(a: Any, b: Any) -> float:
    import numpy as np

    va, vb = np.asarray(a, float).flatten(), np.asarray(b, float).flatten()
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


__all__ = [
    "EMBED_MODEL",
    "EMBED_DIM",
    "VoiceEncoderError",
    "AudioNotFoundError",
    "EncoderBackendError",
    "is_backend_available",
    "to_wav16k",
    "l2_normalize",
    "embed_file",
    "embed_files_mean",
    "cosine",
]
