""


















from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from ingestion.adapters.base import Adapter, ProbeResult  # noqa: E402,F401


class CursorKind(StrEnum):
    ""

    NONE = "none"
    SYNC_TOKEN = "sync_token"
    CHANGES_LIST = "changes_list"
    ROWID = "rowid"
    TIMESTAMP = "timestamp"
    WINDOW = "window"
    OPAQUE = "opaque"


@dataclass(frozen=True)
class RemoteInventory:
    ""





    scope: str
    count: int | None
    as_of: str
    detail: str = ""

    @property
    def countable(self) -> bool:
        return self.count is not None


@dataclass
class RunResultV2:
    ""







    ok: bool
    adapter: str = ""
    outcome: str | None = None
    records_seen: int = 0
    records_written: int = 0
    records_lost: int = 0
    degraded: bool = False
    errors: int = 0
    empty_confirmed: bool = False
    empty_proof: str = ""
    new_watermark: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.empty_confirmed and not self.empty_proof:
            raise ValueError("empty_confirmed=True requires empty_proof (positive proof)")
        if self.records_lost < 0 or self.records_seen < 0 or self.records_written < 0:
            raise ValueError("counts cannot be negative")



        explicit = self.outcome is not None
        if not explicit:
            self.outcome = self._derive_outcome()
        from truth.receipt import Outcome

        if self.outcome not in {o.value for o in Outcome}:
            raise ValueError(f"outcome {self.outcome!r} is not a valid truth.receipt.Outcome")
        if explicit:
            if self.ok and self.outcome == "broken":
                raise ValueError("contradiction: ok=True with outcome='broken'")
            if self.empty_confirmed and self.outcome != "empty_confirmed":
                raise ValueError("empty_confirmed=True requires outcome='empty_confirmed'")

    def _derive_outcome(self) -> str:
        ""
        if self.records_lost > 0:
            return "broken"
        if self.empty_confirmed:
            return "empty_confirmed"
        if not self.ok:
            return "degraded" if self.degraded else "broken"
        return "degraded" if (self.degraded or self.errors > 0) else "ok"

    @property
    def healthy(self) -> bool:
        return self.ok and not self.degraded and self.errors == 0 and self.records_lost == 0

    @property
    def may_advance_watermark(self) -> bool:
        ""
        if self.records_lost > 0:
            return False
        if self.empty_confirmed:
            return True
        return self.healthy


@runtime_checkable
class AdapterV2(Adapter, Protocol):
    ""










    cursor_kind: str
    fragile: bool
    identity_ref: str

    def remote_inventory(self, scope: str) -> RemoteInventory:
        ""



        ...


@dataclass
class AdapterSpec:
    ""




    name: str
    type: str
    priority: int
    tos: str
    cursor_kind: str = CursorKind.NONE.value
    fragile: bool = False
    identity_ref: str = ""
    scopes: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.cursor_kind not in {c.value for c in CursorKind}:
            raise ValueError(f"invalid cursor_kind: {self.cursor_kind!r}")
        if self.priority < 1:
            raise ValueError("priority must be >= 1 (1 = primary)")
        if not self.name:
            raise ValueError("name required")
