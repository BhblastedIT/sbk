#!/usr/bin/env python3
""































from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone  # noqa: UP017 -- vedi nota sotto
from pathlib import Path
from typing import Any













JOBS_ROOT = Path(os.environ.get("SBK_DATA_ROOT") or os.path.expanduser("~/.sbk-data")) / "jobs"
CATALOG = JOBS_ROOT / "catalog.json"
PRESENCE = JOBS_ROOT / "presence.jsonl"
STATUS = JOBS_ROOT / "status.json"
OVERLAY = JOBS_ROOT / "declared.json"


def events_file(when: datetime | None = None) -> Path:
    when = when or now()
    return JOBS_ROOT / f"events-{when:%Y%m}.jsonl"





def now() -> datetime:
    ""
    return datetime.now().astimezone()


def stamp(dt: datetime | None = None) -> str:
    ""




    dt = dt or now()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


def parse(s: str) -> datetime:
    ""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"instant without offset, refusing to guess: {s!r}")
    return dt


def utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)  # noqa: UP017


def fuso_locale() -> Any:
    ""











    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover -- older than 3.9
        return None
    name = os.environ.get("TZ", "").lstrip(":")
    if not name:
        try:
            target = os.path.realpath("/etc/localtime")
        except OSError:
            target = ""
        if "/zoneinfo/" in target:
            name = target.rsplit("/zoneinfo/", 1)[1]
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 -- an unknown name falls back to the fixed offset
        return None















SEGNALI_VOLUTI = {1: "SIGHUP", 2: "SIGINT", 15: "SIGTERM"}
SEGNALI_CRASH = {4: "SIGILL", 6: "SIGABRT", 8: "SIGFPE", 9: "SIGKILL", 10: "SIGBUS", 11: "SIGSEGV"}


def nome_segnale(n: int) -> str:
    return SEGNALI_VOLUTI.get(n) or SEGNALI_CRASH.get(n) or f"signal {n}"


def fermato_da_fuori(segnale: int) -> bool:
    ""
    return segnale in SEGNALI_VOLUTI


def stop_file(job: str) -> Path:
    ""






    return JOBS_ROOT / f"stop-{job}.txt"


def motivo_stop(job: str, dal: float) -> str:
    ""
    f = stop_file(job)
    try:
        if f.stat().st_mtime < dal - 1:
            return ""
        return " ".join(f.read_text(errors="replace").split())[:300]
    except OSError:
        return ""









OUTCOMES = (
    "ok",
    "nothing",
    "failed",
    "skipped",
    "running",
)





MANUALE = "manual:"


PUNCTUALITY = ("on_time", "late", "missed", "stale", "unknown")


@dataclass
class Event:
    ""








    job: str
    phase: str
    at: str = field(default_factory=stamp)
    outcome: str | None = None
    detail: str = ""
    expected_at: str | None = None
    host: str = field(default_factory=lambda: os.uname().nodename.split(".")[0])
    pid: int = field(default_factory=os.getpid)

    def line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


def append_event(ev: Event) -> None:
    ""
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    payload = (ev.line() + "\n").encode()
    fd = os.open(events_file(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


def read_events(months: int = 2) -> list[dict[str, Any]]:
    ""





    out: list[dict[str, Any]] = []
    seen: set[Path] = set()
    cur = now()
    for back in range(months):
        y, m = cur.year, cur.month - back
        while m <= 0:
            m += 12
            y -= 1
        f = JOBS_ROOT / f"events-{y:04d}{m:02d}.jsonl"
        if f in seen or not f.exists():
            continue
        seen.add(f)
        for raw in f.read_text(errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda e: e.get("at", ""))
    return out
