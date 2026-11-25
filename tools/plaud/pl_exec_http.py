#!/usr/bin/env python3
""















from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.plaud.pl_write_base import (
    CircuitBreaker,
    LiveWriteDisabled,
    RenameDiff,
    WriteExecutor,
)

try:
    from sbk_config import PLAUD_DIR

    _DEFAULT_RAW_DIR = Path(PLAUD_DIR)
except Exception:  # pragma: no cover - fallback if the config is not importable
    _DEFAULT_RAW_DIR = Path.home() / ".sbk-data" / "plaud" / "raw"




ENVELOPE_CONSTANTS: dict[str, str] = {
    "edit-from": "desktop",
    "app-platform": "mac",
    "app-versionNumber": "1.3.5",
    "app-language": "en",
}


_NANOID_ALPHABET = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"


def make_request_id(size: int = 11) -> str:
    ""
    return "".join(secrets.choice(_NANOID_ALPHABET) for _ in range(size))


def build_envelope_headers(
    wt_token: str,
    device_id: str,
    request_id: str | None = None,
) -> dict[str, str]:
    ""




    headers = dict(ENVELOPE_CONSTANTS)
    headers["X-Device-Id"] = device_id
    headers["X-Request-Id"] = request_id or make_request_id()

    headers["Authorization"] = f"Bearer {wt_token}"
    return headers


def _iter_local_raw_json(raw_dir: Path):
    for path in sorted(raw_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        yield path


def _resolve_local_path(raw_dir: Path, file_id: str) -> Path | None:
    ""

    direct = raw_dir / f"{file_id}.json"
    if direct.exists():
        return direct
    index_path = raw_dir / "_file_index.json"
    if not index_path.exists():
        return None
    try:
        index = json.loads(index_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    entry = next((e for e in index if isinstance(e, dict) and e.get("id") == file_id), None)
    if entry is None:
        return None
    filename = str(entry.get("filename", ""))
    date = str(entry.get("date", ""))


    needle = filename.replace("/", "").replace(":", "").strip()
    for path in _iter_local_raw_json(raw_dir):
        stem = path.stem
        if date and date in stem and needle[:20] and needle[:20] in stem:
            return path
    return None


class PlaudHttpExecutor(WriteExecutor):
    ""

    def __init__(
        self,
        api_domain: str | None = None,
        wt_token: str | None = None,
        device_id: str | None = None,
        raw_dir: Path | None = None,
        breaker: CircuitBreaker | None = None,
        backup_hook=None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"breaker": breaker, "backup_hook": backup_hook}
        if clock is not None:
            kwargs["clock"] = clock
        super().__init__(**kwargs)
        self.api_domain = api_domain
        self._wt_token = wt_token
        self._device_id = device_id
        self.raw_dir = Path(raw_dir) if raw_dir is not None else _DEFAULT_RAW_DIR



    def read_detail(self, file_id: str) -> dict[str, Any]:
        ""



        path = _resolve_local_path(self.raw_dir, file_id)
        if path is None:
            raise FileNotFoundError(
                f"local transcript not found for file_id={file_id} in {self.raw_dir}"
            )
        data = json.loads(path.read_text())
        segments = data if isinstance(data, list) else data.get("segments", [])
        version_ms = None
        if isinstance(data, dict):
            version_ms = data.get("version_ms")
        return {
            "file_id": file_id,
            "segments": segments,
            "version_ms": version_ms,
            "source": "local_http_offline",
        }

    def build_rename_headers(self) -> dict[str, str]:
        ""
        if not self._wt_token or not self._device_id:
            raise RuntimeError(
                "envelope not buildable: WT or device_id missing "
                "(extract from pl_wt_auth post-decrypt)"
            )
        return build_envelope_headers(self._wt_token, self._device_id)

    def _transport_rename(self, file_id: str, diff: RenameDiff) -> Any:


        raise LiveWriteDisabled(
            "Executor A (HTTP): rename contract not captured (F0 pending). "
            "No live write: dry-run only."
        )

    def health(self) -> bool:
        ""
        return bool(self.api_domain and self._wt_token and self._device_id)
