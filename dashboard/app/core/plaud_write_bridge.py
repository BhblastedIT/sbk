""












from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "tools"), str(_REPO_ROOT / "tools" / "plaud")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tools.plaud.pl_write import WriteError, do_apply
    from tools.plaud.pl_write_base import RenameOp
except ImportError:  # pragma: no cover
    from pl_write import WriteError, do_apply  # type: ignore[no-redef]
    from pl_write_base import RenameOp  # type: ignore[no-redef]

try:
    from sbk_config import PLAUD_DIR as _RAW_DIR
except Exception:  # pragma: no cover
    _RAW_DIR = Path.home() / ".sbk-data" / "plaud" / "raw"

_ID_RE = re.compile(r"^#\s*ID:\s*([0-9a-f]{6,})\s*$", re.IGNORECASE | re.MULTILINE)


class ApplyError(RuntimeError):
    ""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def resolve_file_id(source_file: str, raw_dir: Path | str | None = None) -> str | None:
    ""



    base = Path(raw_dir) if raw_dir is not None else _RAW_DIR
    stem = source_file[:-5] if source_file.endswith(".json") else source_file
    stem = stem[:-4] if stem.endswith(".txt") else stem
    txt = base / f"{stem}.txt"
    if not txt.exists():
        return None
    m = _ID_RE.search(txt.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


_WRITE_LEDGER_PATH = _RAW_DIR.parent / "_write_ledger.jsonl"


def _record_provenance(file_id: str, renames: dict[str, str]) -> None:
    ""
    import time

    try:
        from tools.plaud.pl_provenance import WriteLedger
    except Exception:  # noqa: BLE001
        try:
            from pl_provenance import WriteLedger  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            return
    try:
        ledger = WriteLedger()
        ts = int(time.time() * 1000)
        for speaker_id, name in renames.items():
            entry = ledger.append(
                file_id=file_id, version_ms=None, ts_ms=ts, speaker_id=speaker_id, new_label=name
            )
            ledger.append_line(_WRITE_LEDGER_PATH, entry)
    except Exception:  # noqa: BLE001 - the ledger must never make the write fail
        return


def apply_renames_for_source(
    source_file: str,
    renames: dict[str, str],
    apply: bool = False,
) -> dict[str, Any]:
    ""




    if not renames:
        return {"dry_run": not apply, "changed": 0, "note": "no rename provided"}
    file_id = resolve_file_id(source_file)
    if not file_id:
        raise ApplyError(
            "not_found", f"file_id not found for '{source_file}' (missing the .txt with # ID:)"
        )
    ops = [RenameOp(speaker_id=sid, new_name=name) for sid, name in renames.items()]
    try:
        result = do_apply(file_id, ops, apply=apply)
    except WriteError as e:
        msg = str(e)
        if "-419" in msg or "401" in msg or "WT non trovato" in msg or "-420" in msg:
            raise ApplyError(
                "auth",
                "Plaud tokens expired. Open the Plaud desktop app once to refresh them, then try again.",
            ) from e
        raise ApplyError("write", f"Plaud write error: {msg}") from e
    if apply and result.get("changed"):
        _record_provenance(file_id, renames)
    result["file_id"] = file_id
    return result
