""

























from __future__ import annotations

import json
from pathlib import Path
from typing import Any






try:
    from .pl_types import Provenance
except ImportError:  # pragma: no cover - imported as a top-level module without a package
    try:
        from plaud.pl_types import Provenance
    except ImportError:
        from tools.plaud.pl_types import Provenance







def normalize_override(value: Any) -> dict[str, Any]:
    ""









    if isinstance(value, str):
        return {"identity": value, "provenance": Provenance.OWNER_REVIEWED}
    if isinstance(value, dict):
        identity = value.get("identity") or value.get("name") or ""
        prov = _coerce_provenance(
            value.get("provenance"),

            default=Provenance.OWNER_REVIEWED,
        )
        out = dict(value)
        out["identity"] = identity
        out["provenance"] = prov
        return out

    return {"identity": "", "provenance": Provenance.UNKNOWN}


def _coerce_provenance(raw: Any, *, default: Provenance) -> Provenance:
    ""
    if isinstance(raw, Provenance):
        return raw
    if isinstance(raw, str):
        try:
            return Provenance(raw)
        except ValueError:
            return default
    return default


def _file_is_owner_reviewed(overrides: Any) -> bool:
    ""




    if not overrides or not isinstance(overrides, dict):
        return False
    for value in overrides.values():
        if normalize_override(value)["provenance"] is Provenance.OWNER_REVIEWED:
            return True
    return False







class WriteLedger:
    ""











    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:

        self._entries: list[dict[str, Any]] = [dict(e) for e in (entries or [])]



    def append(
        self,
        file_id: str,
        version_ms: int | None,
        *,
        ts_ms: int,
        speaker_id: str | None = None,
        old_label: str | None = None,
        new_label: str | None = None,
        provenance: Provenance = Provenance.MACHINE_WRITTEN,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ""


        if not file_id:
            raise ValueError("file_id is required to record a write in the ledger")
        entry: dict[str, Any] = {
            "file_id": file_id,
            "version_ms": version_ms,
            "ts_ms": int(ts_ms),
            "speaker_id": speaker_id,
            "old_label": old_label,
            "new_label": new_label,
            "provenance": _coerce_provenance(provenance, default=Provenance.MACHINE_WRITTEN).value,
            "meta": dict(meta or {}),
        }
        self._entries.append(entry)
        return entry



    def entries_for(self, file_id: str) -> list[dict[str, Any]]:
        ""
        return [e for e in self._entries if e.get("file_id") == file_id]

    def has_file(self, file_id: str) -> bool:
        ""
        return any(e.get("file_id") == file_id for e in self._entries)

    def find(self, file_id: str, version_ms: int | None) -> dict[str, Any] | None:
        ""



        if version_ms is None:
            return None
        match = None
        for entry in self._entries:
            if entry.get("file_id") == file_id and entry.get("version_ms") == version_ms:
                match = entry
        return match

    def has_write(self, file_id: str, version_ms: int | None) -> bool:
        ""
        return self.find(file_id, version_ms) is not None

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    @property
    def entries(self) -> list[dict[str, Any]]:
        ""
        return [dict(e) for e in self._entries]



    def to_jsonl(self) -> str:
        ""
        return "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in self._entries)

    @classmethod
    def from_jsonl(cls, text: str) -> WriteLedger:
        ""
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return cls(rows)

    @classmethod
    def load(cls, path: str | Path) -> WriteLedger:
        ""
        p = Path(path)
        if not p.exists():
            return cls([])
        return cls.from_jsonl(p.read_text(encoding="utf-8"))

    def append_line(self, path: str | Path, entry: dict[str, Any]) -> None:
        ""



        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(p, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")







def _as_ledger(write_ledger: Any) -> WriteLedger:
    ""


    if write_ledger is None:
        return WriteLedger([])
    if isinstance(write_ledger, WriteLedger):
        return write_ledger
    if isinstance(write_ledger, list):
        return WriteLedger(write_ledger)
    raise TypeError(f"write_ledger not supported: {type(write_ledger)!r}")


def resolve_provenance(
    file_id: str | None,
    version_ms: int | None,
    overrides: Any = None,
    write_ledger: Any = None,
) -> Provenance:
    ""
















    if not file_id:
        return Provenance.UNKNOWN


    if _file_is_owner_reviewed(overrides):
        return Provenance.OWNER_REVIEWED

    ledger = _as_ledger(write_ledger)


    if ledger.has_write(file_id, version_ms):
        return Provenance.MACHINE_WRITTEN



    if version_ms is None and ledger.has_file(file_id):
        return Provenance.UNKNOWN


    return Provenance.PLAUD_NATIVE
