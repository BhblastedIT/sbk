""






from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AdapterType(StrEnum):
    ""

    OFFICIAL_API = "official-api"
    OFFICIAL_CLI = "official-cli"
    SANCTIONED_EXPORT = "sanctioned-export"
    REVERSE_ENG = "reverse-eng"
    MANUAL_EXPORT = "manual-export"
    LOCAL = "local"


class Tos(StrEnum):
    SAFE = "safe"
    VIOLATES = "violates"


@dataclass
class ProbeResult:
    ""





    ok: bool
    detail: str = ""
    adapter: str = ""


@dataclass
class RunResult:
    ""






    ok: bool
    records: int = 0
    new_watermark: str | None = None
    degraded: bool = False
    errors: int = 0
    adapter: str = ""
    detail: str = ""

    @property
    def healthy(self) -> bool:
        return self.ok and not self.degraded and self.errors == 0


@runtime_checkable
class Adapter(Protocol):
    ""




    name: str
    type: str
    priority: int
    tos: str

    def auth_probe(self) -> ProbeResult:
        ""


        ...

    def run(self, watermark: str | None) -> RunResult:
        ""
        ...
