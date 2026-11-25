#!/usr/bin/env python3
""


















from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tools.plaud.pl_types import WRITE_LIMITS, Provenance, WriteLimits






class CircuitBreakerOpen(RuntimeError):
    ""


class LiveWriteDisabled(RuntimeError):
    ""










@dataclass(frozen=True)
class RenameOp:
    ""




    speaker_id: str
    new_name: str
    entity_id: str | None = None


@dataclass(frozen=True)
class SegmentChange:
    ""

    index: int
    old_speaker: str
    new_speaker: str
    entity_id: str | None = None


@dataclass
class RenameDiff:
    ""

    file_id: str
    ops: list[RenameOp]
    changes: list[SegmentChange]
    total_segments: int

    @property
    def matched_count(self) -> int:
        return len(self.changes)

    def render(self) -> str:
        ""
        header = (
            f"[DRY-RUN] file={self.file_id} "
            f"segmenti_totali={self.total_segments} match={self.matched_count}"
        )
        lines = [header]
        for ch in self.changes:
            lines.append(f"  seg[{ch.index}] '{ch.old_speaker}' -> '{ch.new_speaker}'")
        if not self.changes:
            lines.append("  (nessun segmento combacia con gli op di rename)")
        return "\n".join(lines)


@dataclass
class WriteResult:
    ""

    file_id: str
    status: str
    reason: str
    diff: RenameDiff
    dry_run: bool
    provenance: Provenance = Provenance.UNKNOWN
    transport_response: Any = None







@dataclass
class CircuitBreaker:
    ""






    limits: WriteLimits = WRITE_LIMITS
    clock: Callable[[], float] = time.time
    _writes_today: int = 0
    _day: int | None = None
    _consecutive_errors: int = 0
    _last_write_ts: float | None = None
    _blocked_until: float | None = None

    def _roll_day(self, now: float) -> None:
        day = int(now // 86400)
        if self._day != day:
            self._day = day
            self._writes_today = 0

    def check(self, now: float | None = None) -> None:
        ""



        now = self.clock() if now is None else now
        if self._blocked_until is not None and now < self._blocked_until:
            raise CircuitBreakerOpen(
                f"rate-limit stop attivo fino a {self._blocked_until:.0f} (now {now:.0f})"
            )
        self._roll_day(now)
        if self._writes_today >= self.limits.max_writes_per_day:
            raise CircuitBreakerOpen(
                f"cap giornaliero raggiunto: {self._writes_today}/{self.limits.max_writes_per_day}"
            )
        if self._consecutive_errors >= self.limits.stop_after_consecutive_errors:
            raise CircuitBreakerOpen(f"stop dopo {self._consecutive_errors} errori consecutivi")
        if (
            self._last_write_ts is not None
            and (now - self._last_write_ts) < self.limits.min_seconds_between_writes
        ):
            wait = self.limits.min_seconds_between_writes - (now - self._last_write_ts)
            raise CircuitBreakerOpen(f"ritmo umano: attendere ancora {wait:.1f}s")

    def record_success(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        self._roll_day(now)
        self._writes_today += 1
        self._consecutive_errors = 0
        self._last_write_ts = now

    def record_error(self, now: float | None = None, rate_limited: bool = False) -> None:
        now = self.clock() if now is None else now
        self._consecutive_errors += 1
        self._last_write_ts = now
        if rate_limited:

            self._blocked_until = now + self.limits.stop_hours_on_rate_limit * 3600



GLOBAL_BREAKER = CircuitBreaker()







BackupHook = Callable[[str, RenameDiff], Any]


class WriteExecutor(ABC):
    ""






    def __init__(
        self,
        breaker: CircuitBreaker | None = None,
        backup_hook: BackupHook | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:

        self.breaker = breaker if breaker is not None else GLOBAL_BREAKER
        self._backup_hook = backup_hook
        self._clock = clock



    @abstractmethod
    def read_detail(self, file_id: str) -> dict[str, Any]:
        ""




    @abstractmethod
    def _transport_rename(self, file_id: str, diff: RenameDiff) -> Any:
        ""


    @abstractmethod
    def health(self) -> bool:
        ""



    def compute_diff(self, file_id: str, rename_ops: list[RenameOp]) -> RenameDiff:
        ""
        detail = self.read_detail(file_id)
        segments = detail.get("segments")
        if segments is None:
            segments = detail if isinstance(detail, list) else []
        by_speaker: dict[str, RenameOp] = {op.speaker_id: op for op in rename_ops}
        changes: list[SegmentChange] = []
        for idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue




            orig = seg.get("original_speaker") or seg.get("speaker")
            current = seg.get("speaker")
            op = by_speaker.get(orig) if orig is not None else None
            if op is not None and op.new_name != current:
                changes.append(
                    SegmentChange(
                        index=idx,
                        old_speaker=current if current is not None else orig,
                        new_speaker=op.new_name,
                        entity_id=op.entity_id,
                    )
                )
        return RenameDiff(
            file_id=file_id,
            ops=list(rename_ops),
            changes=changes,
            total_segments=len(segments),
        )

    def apply_rename(
        self,
        file_id: str,
        rename_ops: list[RenameOp],
        dry_run: bool = True,
    ) -> WriteResult:
        ""



        diff = self.compute_diff(file_id, rename_ops)


        if diff.matched_count == 0:
            return WriteResult(
                file_id=file_id,
                status="aborted",
                reason="abort-zero-match: nessun segmento combacia con gli op",
                diff=diff,
                dry_run=dry_run,
                provenance=Provenance.UNKNOWN,
            )

        if dry_run:
            print(diff.render())
            return WriteResult(
                file_id=file_id,
                status="dry_run",
                reason="dry-run: nessuna scrittura eseguita",
                diff=diff,
                dry_run=True,
                provenance=Provenance.UNKNOWN,
            )



        self.breaker.check(self._clock())


        if self._backup_hook is not None:
            self._backup_hook(file_id, diff)


        try:
            resp = self._transport_rename(file_id, diff)
        except LiveWriteDisabled:

            raise
        except Exception:
            self.breaker.record_error(self._clock())
            raise


        self.breaker.record_success(self._clock())
        return WriteResult(
            file_id=file_id,
            status="applied",
            reason="write applicata",
            diff=diff,
            dry_run=False,
            provenance=Provenance.MACHINE_WRITTEN,
            transport_response=resp,
        )
