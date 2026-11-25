""



























from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any








_GENERIC_SPEAKER_RE = re.compile(r"^speaker\s*\d+$", re.IGNORECASE)
_NON_NAME_TOKENS = {"", "unknown", "sconosciuto", "desconocido", "n/a", "na", "none"}


def is_named(speaker: Any) -> bool:
    ""





    if not isinstance(speaker, str):
        return False
    s = speaker.strip()
    if not s:
        return False
    if s.lower() in _NON_NAME_TOKENS:
        return False
    if _GENERIC_SPEAKER_RE.match(s):
        return False
    return True


def _is_generic_id(value: Any) -> bool:
    ""


    return isinstance(value, str) and bool(_GENERIC_SPEAKER_RE.match(value.strip()))







def extract_ground_truth(segments: list[dict[str, Any]]) -> dict[str, str]:
    ""












    votes: dict[str, Counter] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        orig = seg.get("original_speaker")
        name = seg.get("speaker")
        if not _is_generic_id(orig):
            continue
        if not is_named(name):
            continue
        key = orig.strip()
        clean_name = name.strip()
        votes.setdefault(key, Counter())[clean_name] += 1
        marker = f"{key}\x00{clean_name}"
        if marker not in first_seen:
            first_seen[marker] = order
            order += 1

    truth: dict[str, str] = {}
    for key, counter in votes.items():

        best_name = min(
            counter.items(),
            key=lambda kv: (-kv[1], first_seen[f"{key}\x00{kv[0]}"]),
        )[0]
        truth[key] = best_name
    return truth







@dataclass
class EvalRecord:
    ""


    file: str
    speaker_id: str
    truth_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "file": self.file,
            "speaker_id": self.speaker_id,
            "truth_name": self.truth_name,
        }


def _load_segments(path: Path) -> list[dict[str, Any]]:
    ""


    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


@dataclass
class EvalSetStats:
    ""

    files_scanned: int = 0
    files_with_truth: int = 0
    files_only_generic: int = 0
    records: int = 0
    unique_names: int = 0
    per_name: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "files_with_truth": self.files_with_truth,
            "files_only_generic": self.files_only_generic,
            "records": self.records,
            "unique_names": self.unique_names,
        }


def build_eval_set(
    raw_dir: str | Path,
    limit: int | None = None,
) -> list[EvalRecord]:
    ""






    records, _ = build_eval_set_with_stats(raw_dir, limit=limit)
    return records


def build_eval_set_with_stats(
    raw_dir: str | Path,
    limit: int | None = None,
) -> tuple[list[EvalRecord], EvalSetStats]:
    ""
    root = Path(raw_dir)
    files = sorted(p for p in root.glob("*.json") if p.is_file())
    if limit is not None:
        files = files[:limit]

    stats = EvalSetStats()
    records: list[EvalRecord] = []
    name_counter: Counter = Counter()
    for path in files:
        stats.files_scanned += 1
        segments = _load_segments(path)
        truth = extract_ground_truth(segments)
        if not truth:
            stats.files_only_generic += 1
            continue
        stats.files_with_truth += 1
        for speaker_id in sorted(truth):
            name = truth[speaker_id]
            records.append(EvalRecord(file=path.name, speaker_id=speaker_id, truth_name=name))
            name_counter[name] += 1

    records.sort(key=lambda r: (r.file, r.speaker_id))
    stats.records = len(records)
    stats.unique_names = len(name_counter)
    stats.per_name = dict(name_counter)
    return records, stats


def save_eval_set(
    records: list[EvalRecord],
    out_path: str | Path,
    stats: EvalSetStats | None = None,
) -> Path:
    ""


    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "stats": stats.to_dict() if stats is not None else {"records": len(records)},
        "records": [r.to_dict() for r in records],
    }
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(out)
    return out







def _default_raw_dir() -> Path:
    return Path.home() / ".sbk-data" / "plaud" / "raw"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Costruisce l'eval-set (ground-truth speaker) dai transcript Plaud."
    )
    parser.add_argument(
        "--raw-dir",
        default=str(_default_raw_dir()),
        help="Directory dei transcript *.json (default: ~/.sbk-data/plaud/raw).",
    )
    parser.add_argument(
        "--out",
        default=str(_default_raw_dir().parent / "eval" / "speaker_eval_set.json"),
        help="Percorso del JSON di output dell'eval-set.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cappa il numero di file letti (test veloci).",
    )
    args = parser.parse_args(argv)

    records, stats = build_eval_set_with_stats(args.raw_dir, limit=args.limit)
    out = save_eval_set(records, args.out, stats=stats)
    print(
        "eval-set: "
        f"{stats.records} record da {stats.files_with_truth} file rivisti "
        f"(scanditi {stats.files_scanned}, solo-generici {stats.files_only_generic}, "
        f"nomi distinti {stats.unique_names}) -> {out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
