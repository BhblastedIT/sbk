""


















from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


from truth.receipt import ADVANCING_OUTCOMES, Receipt

import sbk_config


class WatermarkError(ValueError):
    ""


def _registry_dir(root: Path | None) -> Path:
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "system" / "registry"


def watermarks_path(root: Path | None = None) -> Path:
    ""
    return _registry_dir(root) / "watermarks.json"


def _require_tz_aware(cursor: datetime) -> datetime:
    if not isinstance(cursor, datetime):
        raise WatermarkError(f"cursor must be a datetime, not {type(cursor).__name__}")
    if cursor.tzinfo is None:
        raise WatermarkError("naive cursor not allowed: use a timezone-aware datetime")
    return cursor


def load_watermarks(root: Path | None = None) -> dict:
    ""
    path = watermarks_path(root)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WatermarkError(f"watermarks.json malformed (object expected): {path}")
    return raw


def read_watermark(source: str, root: Path | None = None) -> dict | None:
    ""
    return load_watermarks(root).get(source)


def advance_watermark(
    source: str,
    receipt: Receipt,
    *,
    cursor: datetime | None = None,
    root: Path | None = None,
) -> bool:
    ""









    if not isinstance(receipt, Receipt):
        raise WatermarkError("receipt must be a Receipt")

    if cursor is None:
        cursor = datetime.fromisoformat(receipt.as_of)
    cursor = _require_tz_aware(cursor)

    if receipt.status not in ADVANCING_OUTCOMES:

        return False

    watermarks = load_watermarks(root)
    existing = watermarks.get(source)
    if existing is not None:
        try:
            prev_cursor = datetime.fromisoformat(existing["cursor"])
        except (KeyError, ValueError) as exc:
            raise WatermarkError(
                f"existing watermark entry malformed for {source!r}: {existing!r}"
            ) from exc
        if prev_cursor.tzinfo is None:
            raise WatermarkError(f"legacy naive cursor for {source!r}: {existing['cursor']!r}")
        if cursor <= prev_cursor:

            return False

    watermarks[source] = {
        "cursor": cursor.isoformat(),
        "status": receipt.status.value,
        "job_id": receipt.job_id,
        "as_of": receipt.as_of,
    }

    sbk_config.safe_write_json(watermarks_path(root), watermarks)
    return True
