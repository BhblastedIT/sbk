#!/usr/bin/env python3
""
















from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.plaud.pl_exec_http import PlaudHttpExecutor
from tools.plaud.pl_write_base import (
    CircuitBreaker,
    LiveWriteDisabled,
    RenameDiff,
)


class PlaudSessionExecutor(PlaudHttpExecutor):
    ""





    def __init__(
        self,
        web_origin: str = "https://web.plaud.ai",
        user_data_dir: str | Path | None = None,
        raw_dir: Path | None = None,
        breaker: CircuitBreaker | None = None,
        backup_hook=None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(
            api_domain=None,
            wt_token=None,
            device_id=None,
            raw_dir=raw_dir,
            breaker=breaker,
            backup_hook=backup_hook,
            clock=clock,
        )
        self.web_origin = web_origin

        self.user_data_dir = (
            str(user_data_dir) if user_data_dir is not None else "/tmp/plaud-session-executor"  # noqa: S108 - scratch dedicato, mai il profilo browser dell'utente
        )

    def _transport_rename(self, file_id: str, diff: RenameDiff) -> Any:


        raise LiveWriteDisabled(
            "Esecutore C (session-replay): XHR di rename non catturata (F0 pending). "
            "Il replay same-origin su Chromium dedicato si attiva post-F0. Dry-run only."
        )

    def health(self) -> bool:
        ""



        return bool(self.web_origin and self.user_data_dir)
