#!/usr/bin/env python3
"""Backup of a Plaud transcript before any write: an atomic copy with its hash in a ledger, so a write is refused
unless the backup exists. Run as a script it backs up one raw file as a test.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import PLAUD_DIR  # noqa: E402


FetchBytes = Callable[[str], bytes]


DEFAULT_BACKUP_DIR = PLAUD_DIR.parent / "backups"
DEFAULT_LEDGER_PATH = DEFAULT_BACKUP_DIR / "backup-ledger.jsonl"


PRESERVED_SEGMENT_FIELDS = ("speaker", "original_speaker", "embeddingKey")


class BackupInvariantError(RuntimeError):
    ""







def sha256_bytes(data: bytes) -> str:
    ""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()







def iter_segments(transcript: Any) -> list[dict[str, Any]]:
    ""



    if isinstance(transcript, list):
        return [s for s in transcript if isinstance(s, dict)]
    if isinstance(transcript, dict):
        for key in ("content_list", "segments", "trans_result", "data"):
            val = transcript.get(key)
            if isinstance(val, list):
                return [s for s in val if isinstance(s, dict)]
    return []


def count_preserved_fields(raw: bytes) -> dict[str, int]:
    ""




    counts = {"n_segments": 0, "n_original_speaker": 0, "n_embedding_key": 0, "n_speaker": 0}
    try:
        transcript = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return counts
    segments = iter_segments(transcript)
    counts["n_segments"] = len(segments)
    for seg in segments:
        if seg.get("speaker"):
            counts["n_speaker"] += 1
        if seg.get("original_speaker"):
            counts["n_original_speaker"] += 1
        if seg.get("embeddingKey"):
            counts["n_embedding_key"] += 1
    return counts







def _sanitize_file_id(file_id: str) -> str:
    ""
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", str(file_id)).strip("._") or "unknown"
    return clean[:120]


def backup_filename(file_id: str, sha256_pre: str) -> str:
    ""
    return f"{_sanitize_file_id(file_id)}__{sha256_pre[:16]}.json"


def write_bytes_atomic(raw: bytes, dest: str | Path) -> Path:
    ""


    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return dest







@dataclass
class BackupRecord:
    ""

    file_id: str
    sha256_pre: str
    backup_path: str
    byte_len: int
    ts: float = field(default_factory=time.time)
    n_segments: int = 0
    n_speaker: int = 0
    n_original_speaker: int = 0
    n_embedding_key: int = 0
    version_ms: int | None = None
    edit_time: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BackupRecord:
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


def append_ledger(record: BackupRecord, ledger_path: str | Path = DEFAULT_LEDGER_PATH) -> None:
    ""
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(record.to_json_line() + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_ledger(ledger_path: str | Path = DEFAULT_LEDGER_PATH) -> list[BackupRecord]:
    ""
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return []
    records: list[BackupRecord] = []
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(BackupRecord.from_dict(json.loads(line)))
    return records







def has_backup_with_hash(
    file_id: str,
    sha256_pre: str,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> bool:
    ""

    for rec in read_ledger(ledger_path):
        if rec.file_id != file_id or rec.sha256_pre != sha256_pre:
            continue
        bpath = Path(rec.backup_path)
        if bpath.exists() and sha256_file(bpath) == sha256_pre:
            return True
    return False


def require_backup_before_apply(
    file_id: str,
    sha256_pre: str,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> None:
    ""

    if not has_backup_with_hash(file_id, sha256_pre, ledger_path):
        raise BackupInvariantError(
            f"apply BLOCKED: no intact backup for file_id={file_id!r} "
            f"with sha256_pre={sha256_pre[:16]}... Run backup_transcript() first."
        )







@dataclass
class BackupResult:
    ""

    file_id: str
    sha256_pre: str
    backup_path: Path
    byte_len: int
    counts: dict[str, int]
    already_present: bool = False


def backup_transcript(
    file_id: str,
    fetch_bytes: FetchBytes,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    version_ms: int | None = None,
    edit_time: int | None = None,
    meta: dict[str, Any] | None = None,
) -> BackupResult:
    ""




    raw = fetch_bytes(file_id)
    if not isinstance(raw, bytes | bytearray):
        raise TypeError(f"fetch_bytes must return bytes, not {type(raw).__name__}")
    raw = bytes(raw)
    sha_pre = sha256_bytes(raw)
    dest = Path(backup_dir) / backup_filename(file_id, sha_pre)
    counts = count_preserved_fields(raw)


    if has_backup_with_hash(file_id, sha_pre, ledger_path):
        return BackupResult(
            file_id=file_id,
            sha256_pre=sha_pre,
            backup_path=dest,
            byte_len=len(raw),
            counts=counts,
            already_present=True,
        )

    write_bytes_atomic(raw, dest)

    if sha256_file(dest) != sha_pre:
        raise BackupInvariantError(
            f"backup NOT byte-faithful for {file_id!r}: on-disk hash != source hash"
        )
    record = BackupRecord(
        file_id=file_id,
        sha256_pre=sha_pre,
        backup_path=str(dest),
        byte_len=len(raw),
        n_segments=counts["n_segments"],
        n_speaker=counts["n_speaker"],
        n_original_speaker=counts["n_original_speaker"],
        n_embedding_key=counts["n_embedding_key"],
        version_ms=version_ms,
        edit_time=edit_time,
        meta=meta or {},
    )
    append_ledger(record, ledger_path)
    return BackupResult(
        file_id=file_id,
        sha256_pre=sha_pre,
        backup_path=dest,
        byte_len=len(raw),
        counts=counts,
        already_present=False,
    )







def file_bytes_fetcher(path: str | Path) -> FetchBytes:
    ""

    data = Path(path).read_bytes()

    def _fetch(_file_id: str) -> bytes:
        return data

    return _fetch


def build_s3_fetcher(api_get: Callable[[str], dict[str, Any]]) -> FetchBytes:
    ""





    import gzip
    import urllib.request

    def _fetch(file_id: str) -> bytes:
        detail = api_get(f"/file/detail/{file_id}")
        content_list = (detail.get("data") or detail).get("content_list") or detail.get(
            "content_list", []
        )
        trans_link = None
        for item in content_list:
            if item.get("data_type") == "transaction":
                trans_link = item.get("data_link")
                break
        if not trans_link:
            raise RuntimeError(f"no transcript link for file_id={file_id!r}")
        req = urllib.request.Request(
            trans_link, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted S3 host)
            raw_bytes = resp.read()
            enc = resp.headers.get("Content-Encoding")
        if raw_bytes[:2] == b"\x1f\x8b" or enc == "gzip":
            raw_bytes = gzip.decompress(raw_bytes)
        return raw_bytes

    return _fetch


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="F1 backup harness (smoke test offline)")
    parser.add_argument("raw_file", help="path to a raw transcript in plaud/raw/")
    parser.add_argument("--file-id", default="smoke-test")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    args = parser.parse_args()

    res = backup_transcript(
        args.file_id,
        file_bytes_fetcher(args.raw_file),
        backup_dir=args.backup_dir,
        ledger_path=Path(args.backup_dir) / "backup-ledger.jsonl",
    )
    print(f"backup: {res.backup_path}")
    print(f"sha256_pre: {res.sha256_pre}")
    print(f"byte_len: {res.byte_len}  counts: {res.counts}  already: {res.already_present}")
