""






































from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("sbk.l1-checkpoint")


_SOURCE_OUTPUT_PATTERNS: dict[str, list[str]] = {
    "email": ["contacts.parquet", "interactions.parquet", "threads.parquet"],
    "slack": [
        "contacts-slack.parquet",
        "interactions-slack.parquet",
        "channels-activity.parquet",
    ],
    "attio": ["contacts-attio.parquet", "companies-attio.parquet"],
}


def _get_output_dir(source: str) -> Path | None:
    ""
    from sbk_config import ATTIO_DIR, ENRICHED_DIR, SLACK_DIR

    dirs = {
        "email": ENRICHED_DIR,
        "slack": SLACK_DIR,
        "attio": ATTIO_DIR / "processed",
    }
    return dirs.get(source)


def _get_checkpoint_dir() -> Path:
    ""
    from sbk_config import L1_CHECKPOINT_DIR

    return L1_CHECKPOINT_DIR


def _sha256_file(path: Path) -> str:
    ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class L1Checkpoint:
    ""

    def __init__(self, source: str, owner: str | None = None) -> None:
        ""






        self.source = source
        self.owner = owner
        self._output_files = _SOURCE_OUTPUT_PATTERNS.get(source, [])

    @property
    def _checkpoint_path(self) -> Path:
        suffisso = f".{self.owner}" if self.owner else ""
        return _get_checkpoint_dir() / f"{self.source}-l1-checkpoint{suffisso}.json"

    @property
    def _output_dir(self) -> Path | None:
        return _get_output_dir(self.source)

    def _current_fingerprints(self) -> dict[str, str]:
        ""
        if not self._output_dir or not self._output_dir.exists():
            return {}
        fingerprints = {}
        for filename in self._output_files:
            path = self._output_dir / filename
            if path.exists():
                fingerprints[filename] = _sha256_file(path)
        return fingerprints

    def _load_saved(self) -> dict[str, str]:
        ""
        if not self._checkpoint_path.exists():
            return {}
        try:
            data = json.loads(self._checkpoint_path.read_text())
            return data.get("fingerprints", {})
        except (json.JSONDecodeError, OSError):
            return {}

    def has_output_changed(self) -> bool:
        ""




        saved = self._load_saved()
        if not saved:
            return True

        current = self._current_fingerprints()
        if not current:

            return True

        return current != saved

    def save(self) -> None:
        ""
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        fingerprints = self._current_fingerprints()
        data = {
            "source": self.source,
            "owner": self.owner or "l1-script",
            "timestamp": datetime.now(UTC).isoformat(),
            "fingerprints": fingerprints,
        }
        self._checkpoint_path.write_text(json.dumps(data, indent=2))
        log.info(
            "L1 checkpoint saved: %s [%s] (%d files)",
            self.source,
            self.owner or "l1-script",
            len(fingerprints),
        )
