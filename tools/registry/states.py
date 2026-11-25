""














from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import sbk_config

from .schema import VALID_STATES


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "off": frozenset({"shadow", "deprecated"}),
    "shadow": frozenset({"canary", "off", "deprecated"}),
    "canary": frozenset({"on", "shadow", "off", "deprecated"}),
    "on": frozenset({"paused", "deprecated"}),
    "paused": frozenset({"on", "deprecated"}),
    "deprecated": frozenset(),
}


FORCE_TOKEN = "FORCE-ON"


class StateTransitionError(ValueError):
    ""


def _events_path(root: Path | None) -> Path:
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "system" / "registry" / "state-events.jsonl"


def _read_events(job_id: str, root: Path | None) -> list[dict]:
    path = _events_path(root)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        if ev.get("job_id") == job_id:
            out.append(ev)
    return out


def current_state(job_id: str, *, default: str = "off", root: Path | None = None) -> str:
    ""
    events = _read_events(job_id, root)
    if not events:
        return default
    return events[-1]["to_state"]


def _valid_force(force_file: str | Path | None, job_id: str) -> bool:
    ""
    if not force_file:
        return False
    p = Path(force_file)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    return job_id in text and FORCE_TOKEN in text


def transition(
    job_id: str,
    to_state: str,
    *,
    actor: str,
    reason: str = "",
    force_file: str | Path | None = None,
    default_from: str = "off",
    root: Path | None = None,
) -> dict:
    ""






    if to_state not in VALID_STATES:
        raise StateTransitionError(
            f"{job_id}: invalid target state {to_state!r}. Allowed: {', '.join(VALID_STATES)}"
        )

    frm = current_state(job_id, default=default_from, root=root)
    if to_state == frm:
        raise StateTransitionError(f"{job_id}: already in state {to_state!r} (no-op not recorded)")

    allowed = ALLOWED_TRANSITIONS.get(frm, frozenset())
    if to_state not in allowed:
        raise StateTransitionError(
            f"{job_id}: transition {frm!r} -> {to_state!r} not allowed. "
            f"From {frm!r} you can only go to: {', '.join(sorted(allowed)) or '(none, terminal)'}"
        )

    forced = False
    if to_state == "on":
        if not _valid_force(force_file, job_id):
            raise StateTransitionError(
                f"{job_id}: transition to 'on' denied: a signed force file is required "
                f"(containing '{job_id}' and '{FORCE_TOKEN}'). No entry into production without an explicit act."
            )
        forced = True

    event = {
        "job_id": job_id,
        "from_state": frm,
        "to_state": to_state,
        "actor": actor,
        "reason": reason,
        "forced": forced,
        "as_of": sbk_config.utc_now().isoformat(),
    }

    path = _events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return event


def history(job_id: str, root: Path | None = None) -> list[dict]:
    ""
    return _read_events(job_id, root)


def _parse_as_of(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["as_of"])
