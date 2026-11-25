""




























from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))




try:
    from tools.plaud.pl_types import EvidenceSource
except ImportError:  # pragma: no cover
    from pl_types import EvidenceSource  # type: ignore[no-redef]




VOICE_SOURCE = EvidenceSource.VOICE_EMBEDDING







class DiarizationError(RuntimeError):
    ""


class DiarizationBackendError(DiarizationError):
    ""



class AudioNotFoundError(DiarizationError):
    ""







@dataclass
class DiarSegment:
    ""







    start: float
    end: float
    speaker: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "speaker": self.speaker}

    @classmethod
    def from_any(cls, obj: Any) -> DiarSegment:
        ""






        if isinstance(obj, DiarSegment):
            return obj
        if isinstance(obj, Mapping):
            if "start" not in obj or "end" not in obj:
                raise DiarizationError("Diarizer segment missing 'start'/'end': " + repr(obj))
            speaker = obj.get("speaker", obj.get("label"))
            if speaker is None:
                raise DiarizationError("Diarizer segment missing 'speaker'/'label': " + repr(obj))
            return cls(_to_float(obj["start"]), _to_float(obj["end"]), str(speaker))

        if isinstance(obj, str) or not isinstance(obj, Iterable):
            raise DiarizationError("Unrecognized diarizer segment: " + repr(obj))
        parts = list(obj)
        if len(parts) < 3:
            raise DiarizationError(
                "Segment tuple too short (need start,end,speaker): " + repr(obj)
            )
        return cls(_to_float(parts[0]), _to_float(parts[1]), str(parts[2]))


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DiarizationError(f"Non-numeric time value: {value!r}") from exc





DiarizerFn = Callable[[str], Iterable[Any]]







def diarize_file(
    audio_path: str | Path,
    diarizer: DiarizerFn | Any | None = None,
    *,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    coalesce_gap: float | None = None,
) -> list[dict[str, Any]]:
    ""




















    path = Path(audio_path)
    if not path.exists():
        raise AudioNotFoundError(f"Local audio not found: {path}")

    if diarizer is None:
        diarizer = build_default_diarizer()

    raw = _invoke_diarizer(
        diarizer, str(path), min_speakers=min_speakers, max_speakers=max_speakers
    )

    segments = [DiarSegment.from_any(item) for item in raw]

    segments = [s for s in segments if s.end > s.start]
    segments.sort(key=lambda s: (s.start, s.end))

    if coalesce_gap is not None:
        segments = coalesce_segments(segments, max_gap=coalesce_gap)

    return [s.to_dict() for s in segments]


def _invoke_diarizer(
    diarizer: DiarizerFn | Any,
    path: str,
    *,
    min_speakers: int | None,
    max_speakers: int | None,
) -> Iterable[Any]:
    ""




    target: Any = diarizer
    if hasattr(diarizer, "diarize") and callable(diarizer.diarize):
        target = diarizer.diarize

    if min_speakers is None and max_speakers is None:
        return target(path)

    try:
        return target(path, min_speakers=min_speakers, max_speakers=max_speakers)
    except TypeError:

        return target(path)







def is_pyannote_available() -> bool:
    ""
    try:
        import pyannote.audio  # noqa: F401
    except Exception:  # pragma: no cover - depends on the environment
        return False
    return True


def build_default_diarizer(
    *,
    hf_token: str | None = None,
    device: str | None = None,
    model: str = "pyannote/speaker-diarization-3.1",
) -> DiarizerFn:
    ""








    if not is_pyannote_available():
        raise DiarizationBackendError(
            "pyannote.audio is not installed in this environment. Local diarization "
            "(long recordings) requires pyannote 4.0. Install it "
            "(e.g. `uv add pyannote.audio`) or inject a diarizer with "
            "diarize_file(path, diarizer=...). No silent fallback."
        )

    try:  # pragma: no cover - needs weights/network, not in tests
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(model, use_auth_token=hf_token)
        chosen = device or _best_device()
        if chosen and chosen != "cpu":
            import torch

            pipeline.to(torch.device(chosen))
    except DiarizationBackendError:
        raise
    except Exception as exc:  # pragma: no cover
        raise DiarizationBackendError(
            "Unable to initialize the pyannote pipeline "
            f"({model}): {type(exc).__name__}: {exc}. A valid Hugging Face token "
            "with access to the gated model and downloadable weights is required."
        ) from exc

    def _run(path: str) -> Iterable[Any]:  # pragma: no cover - needs real audio
        annotation = pipeline(path)
        return list(_iter_pyannote_annotation(annotation))

    return _run


def _best_device() -> str:  # pragma: no cover - depends on the hardware
    try:
        import torch
    except Exception:
        return "cpu"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _iter_pyannote_annotation(annotation: Any) -> Iterable[dict[str, Any]]:
    ""





    for segment, _track, label in annotation.itertracks(yield_label=True):
        yield {
            "start": float(segment.start),
            "end": float(segment.end),
            "speaker": str(label),
        }







class UnionFind:
    ""




    def __init__(self) -> None:
        self._parent: dict[Any, Any] = {}
        self._rank: dict[Any, int] = {}

    def add(self, key: Any) -> None:
        if key not in self._parent:
            self._parent[key] = key
            self._rank[key] = 0

    def find(self, key: Any) -> Any:
        self.add(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]

        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def groups(self) -> dict[Any, list[Any]]:
        out: dict[Any, list[Any]] = {}
        for key in self._parent:
            out.setdefault(self.find(key), []).append(key)
        return out







@dataclass
class RejoinPiece:
    ""








    piece_id: str
    offset: float
    segments: list[Any] = field(default_factory=list)

    def global_segments(self) -> list[DiarSegment]:
        out: list[DiarSegment] = []
        for raw in self.segments:
            seg = DiarSegment.from_any(raw)
            out.append(DiarSegment(seg.start + self.offset, seg.end + self.offset, seg.speaker))
        return out


def _overlap(a: DiarSegment, b: DiarSegment) -> float:
    ""
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def _mutual_best_matches(
    a_id: str,
    a_segs: list[DiarSegment],
    b_id: str,
    b_segs: list[DiarSegment],
    min_overlap: float,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    ""





    matrix: dict[str, dict[str, float]] = {}
    for sa in a_segs:
        for sb in b_segs:
            ov = _overlap(sa, sb)
            if ov <= 0.0:
                continue
            matrix.setdefault(sa.speaker, {})
            matrix[sa.speaker][sb.speaker] = matrix[sa.speaker].get(sb.speaker, 0.0) + ov

    def _best(row: dict[str, float]) -> str:

        return min(row, key=lambda k: (-row[k], k))

    best_for_a = {a_sp: _best(row) for a_sp, row in matrix.items()}


    transposed: dict[str, dict[str, float]] = {}
    for a_sp, row in matrix.items():
        for b_sp, ov in row.items():
            transposed.setdefault(b_sp, {})[a_sp] = ov
    best_for_b = {b_sp: _best(row) for b_sp, row in transposed.items()}

    out: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for a_sp, b_sp in best_for_a.items():
        if best_for_b.get(b_sp) != a_sp:
            continue
        if matrix[a_sp][b_sp] <= min_overlap:
            continue
        out.append(((a_id, a_sp), (b_id, b_sp)))
    return out


def rejoin_pieces(
    pieces: list[RejoinPiece],
    *,
    min_overlap: float = 0.0,
    extra_links: Iterable[tuple[tuple[str, str], tuple[str, str]]] | None = None,
    coalesce_gap: float | None = None,
    speaker_prefix: str = "SPEAKER",
) -> list[dict[str, Any]]:
    ""




















    uf = UnionFind()


    per_piece: dict[str, list[DiarSegment]] = {}
    for piece in pieces:
        gsegs = piece.global_segments()
        per_piece[piece.piece_id] = gsegs
        for seg in gsegs:
            uf.add((piece.piece_id, seg.speaker))


    piece_ids = [p.piece_id for p in pieces]
    for i in range(len(piece_ids)):
        for j in range(i + 1, len(piece_ids)):
            for ka, kb in _mutual_best_matches(
                piece_ids[i],
                per_piece[piece_ids[i]],
                piece_ids[j],
                per_piece[piece_ids[j]],
                min_overlap,
            ):
                uf.union(ka, kb)


    if extra_links:
        for ka, kb in extra_links:
            uf.add(ka)
            uf.add(kb)
            uf.union(ka, kb)


    all_segments: list[tuple[DiarSegment, Any]] = []
    for piece_id, gsegs in per_piece.items():
        for seg in gsegs:
            root = uf.find((piece_id, seg.speaker))
            all_segments.append((seg, root))

    first_seen: dict[Any, float] = {}
    for seg, root in all_segments:
        if root not in first_seen or seg.start < first_seen[root]:
            first_seen[root] = seg.start

    ordered_roots = sorted(first_seen, key=lambda r: (first_seen[r], str(r)))
    label_of: dict[Any, str] = {
        root: f"{speaker_prefix}_{idx:02d}" for idx, root in enumerate(ordered_roots)
    }

    merged = [DiarSegment(seg.start, seg.end, label_of[root]) for seg, root in all_segments]
    merged.sort(key=lambda s: (s.start, s.end))

    if coalesce_gap is not None:
        merged = coalesce_segments(merged, max_gap=coalesce_gap)

    return [s.to_dict() for s in merged]


def coalesce_segments(segments: list[DiarSegment], *, max_gap: float = 0.0) -> list[DiarSegment]:
    ""






    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: (s.start, s.end))
    out: list[DiarSegment] = [DiarSegment(ordered[0].start, ordered[0].end, ordered[0].speaker)]
    for seg in ordered[1:]:
        last = out[-1]
        if seg.speaker == last.speaker and seg.start - last.end <= max_gap:
            if seg.end > last.end:
                last.end = seg.end
        else:
            out.append(DiarSegment(seg.start, seg.end, seg.speaker))
    return out


__all__ = [
    "VOICE_SOURCE",
    "DiarizationError",
    "DiarizationBackendError",
    "AudioNotFoundError",
    "DiarSegment",
    "DiarizerFn",
    "diarize_file",
    "is_pyannote_available",
    "build_default_diarizer",
    "UnionFind",
    "RejoinPiece",
    "rejoin_pieces",
    "coalesce_segments",
]
