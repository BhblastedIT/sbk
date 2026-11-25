""






from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from sbk_config import DATA_ROOT

log = logging.getLogger("dashboard.settings-store")

_DEFAULT_PATH = DATA_ROOT / "sbk-settings.json"

DEFAULTS: dict[str, dict] = {
    "cascade_debounce": {
        "slack": 60,
        "email": 120,
        "calendar": 300,
        "attio": 300,
        "default": 300,
    },
    "decay": {
        "tiers": [
            {"name": "inner", "min_score": 0.75, "capacity": 15, "half_life_days": 30},
            {"name": "trusted", "min_score": 0.50, "capacity": 50, "half_life_days": 60},
            {"name": "sympathy", "min_score": 0.30, "capacity": 100, "half_life_days": 90},
            {"name": "known", "min_score": 0.0, "capacity": 500, "half_life_days": 180},
        ],
        "ewma_alpha": 0.3,
        "alert_cooldown_days": 14,
        "budget": 5,
        "threshold": 0.70,
    },
    "entity_resolution": {
        "fuzzy_threshold": 85,
        "same_domain_threshold": 90,
        "review_confidence_min": 0.5,
    },
    "noise_domains_extra": [],
    "internal_domains_extra": [],
}


class SettingsStore:
    ""

    def __init__(self, path: Path | None = None):
        self._path = path or _DEFAULT_PATH
        self._data: dict = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        ""
        if not self._path.exists():
            self._data = copy.deepcopy(DEFAULTS)
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):

                merged = copy.deepcopy(DEFAULTS)
                for key in merged:
                    if key in raw:
                        merged[key] = raw[key]
                self._data = merged
            else:
                log.warning("Invalid settings format, using defaults")
                self._data = copy.deepcopy(DEFAULTS)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load settings: %s", e)
            self._data = copy.deepcopy(DEFAULTS)

    def _save(self):
        ""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._path.parent),
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(self._path))
        except OSError as e:
            log.error("Failed to save settings: %s", e)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def get_section(self, section: str) -> dict | list | None:
        ""
        if section not in DEFAULTS:
            return None
        return copy.deepcopy(self._data.get(section, DEFAULTS[section]))

    def set(self, section: str, data: dict | list) -> bool:
        ""
        if section not in DEFAULTS:
            return False
        with self._lock:
            self._data[section] = data
            self._save()
        return True

    def reset_section(self, section: str) -> bool:
        ""
        if section not in DEFAULTS:
            return False
        with self._lock:
            self._data[section] = copy.deepcopy(DEFAULTS[section])
            self._save()
        return True

    def all_settings(self) -> dict:
        ""
        return copy.deepcopy(self._data)
