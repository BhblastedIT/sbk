""




from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("sbk.tasks")


def safe_create_task(coro, *, name: str = "") -> asyncio.Task:
    ""





    task = asyncio.create_task(coro, name=name or None)
    task.add_done_callback(lambda t: _handle_task_result(t, name))
    return task


def _handle_task_result(task: asyncio.Task, name: str) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        log.error("Background task '%s' failed: %s", name, exc, exc_info=exc)
