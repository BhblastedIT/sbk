"""Slack conversations you excluded: never downloaded, never read by the later steps.

The rule lives in sbk.config.json (slack.exclude_channel_patterns and
slack.exclude_channel_ids). sl-l0-channel-index.py applies the patterns and
marks the matching channels with "is_excluded" in channel-index.json; the ids
listed in slack.exclude_channel_ids are excluded directly, so they also cover
DMs and group DMs, which are not in the channel index.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import SLACK_CHANNEL_INDEX_FILE, SLACK_EXCLUDE_CHANNEL_IDS  # noqa: E402


class IndiceAssente(RuntimeError):
    """The channel index is missing or unreadable."""


_GIA_LETTI: dict[tuple[str, int], frozenset[str]] = {}


def esclusi(indice: Path | None = None) -> frozenset[str]:
    """Ids of the excluded conversations: flagged in the channel index, plus the configured ids."""
    indice = Path(indice or SLACK_CHANNEL_INDEX_FILE)
    try:
        chiave = (str(indice), indice.stat().st_mtime_ns)
        if chiave in _GIA_LETTI:
            return _GIA_LETTI[chiave]
        dati = json.loads(indice.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise IndiceAssente(
            f"Slack channel index missing or unreadable ({indice}): "
            "run tools/slack/sl-l0-channel-index.py first"
        ) from e
    _GIA_LETTI[chiave] = frozenset(
        ch["id"] for ch in dati.get("channels", []) if ch.get("id") and ch.get("is_excluded")
    ) | SLACK_EXCLUDE_CHANNEL_IDS
    return _GIA_LETTI[chiave]


def e_escluso(conversazione: dict, ids: frozenset[str]) -> bool:
    """True if a saved conversation file belongs to an excluded conversation."""
    return isinstance(conversazione, dict) and conversazione.get("channel_id") in ids
