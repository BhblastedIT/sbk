""










from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PERIMETERS_PATH = Path(__file__).resolve().parent / "registries" / "perimeters.yaml"


ALLOWED_STATES = frozenset({"IN", "IN_CON_REGOLE", "IN_DI_FATTO_DA_RATIFICARE"})
DENIED_STATES = frozenset({"MAI", "PENDING_OK"})
KNOWN_STATES = ALLOWED_STATES | DENIED_STATES


LLM_LEVELS = ("none", "api_only", "any")

_BACKEND_MIN_LEVEL = {
    "api": "api_only",
    "subscription": "any",
}


class PerimeterError(Exception):
    ""


class PerimeterDenied(PerimeterError):
    ""


@dataclass(frozen=True)
class PerimeterDecision:
    ""

    source_id: str
    allowed: bool
    state: str
    llm_allowed: str
    reason: str

    @property
    def denied(self) -> bool:
        return not self.allowed


def _coerce_entry(raw: Any, idx: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PerimeterError(f"perimeters[{idx}]: entry is not a mapping")
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid.strip():
        raise PerimeterError(f"perimeters[{idx}]: `id` missing or not a string")
    state = raw.get("state")
    if state not in KNOWN_STATES:
        raise PerimeterError(f"perimeters[{idx}] ({sid}): unrecognized state: {state!r}")

    llm = raw.get("llm_allowed", "none")
    if llm not in LLM_LEVELS:
        raise PerimeterError(f"perimeters[{idx}] ({sid}): invalid llm_allowed: {llm!r}")
    entry = dict(raw)
    entry["llm_allowed"] = llm
    return entry


def load_perimeters(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    ""




    p = Path(path) if path is not None else DEFAULT_PERIMETERS_PATH
    if not p.exists():
        raise PerimeterError(f"perimeter registry missing: {p}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - depends on input
        raise PerimeterError(f"malformed perimeter registry: {exc}") from exc
    if not isinstance(doc, dict):
        raise PerimeterError("perimeter registry: root is not a mapping")
    rows = doc.get("perimeters")
    if not isinstance(rows, list) or not rows:
        raise PerimeterError("perimeter registry: `perimeters` section empty or missing")
    out: dict[str, dict[str, Any]] = {}
    for idx, raw in enumerate(rows):
        entry = _coerce_entry(raw, idx)
        sid = entry["id"]
        if sid in out:
            raise PerimeterError(f"duplicate id in the registry: {sid}")
        out[sid] = entry
    return out


@lru_cache(maxsize=8)
def _cached_load(path_str: str) -> dict[str, dict[str, Any]]:
    return load_perimeters(path_str)


def _registry(path: str | Path | None) -> dict[str, dict[str, Any]]:

    key = str(Path(path) if path is not None else DEFAULT_PERIMETERS_PATH)
    return _cached_load(key)


def get_perimeter(source_id: str, path: str | Path | None = None) -> dict[str, Any] | None:
    ""
    return _registry(path).get(source_id)


def check_ingestion(
    source_id: str,
    path: str | Path | None = None,
    *,
    raise_on_deny: bool = False,
) -> PerimeterDecision:
    ""




    entry = get_perimeter(source_id, path)
    if entry is None:
        decision = PerimeterDecision(
            source_id=source_id,
            allowed=False,
            state="UNKNOWN",
            llm_allowed="none",
            reason="source not present in the registry (default-deny)",
        )
    else:
        state = entry["state"]
        allowed = state in ALLOWED_STATES
        decision = PerimeterDecision(
            source_id=source_id,
            allowed=allowed,
            state=state,
            llm_allowed=entry["llm_allowed"],
            reason=entry.get("reason", "") if allowed else f"state not allowed: {state}",
        )
    if decision.denied and raise_on_deny:
        raise PerimeterDenied(f"{source_id}: {decision.reason}")
    return decision


def check_llm(
    source_id: str,
    backend: str = "api",
    path: str | Path | None = None,
    *,
    raise_on_deny: bool = False,
) -> bool:
    ""




    ingest = check_ingestion(source_id, path)
    if not ingest.allowed:
        if raise_on_deny:
            raise PerimeterDenied(f"{source_id}: perimeter denies ingestion, so LLM too")
        return False
    min_level = _BACKEND_MIN_LEVEL.get(backend)
    if min_level is None:
        if raise_on_deny:
            raise PerimeterDenied(f"unrecognized LLM backend: {backend!r}")
        return False
    allowed_level = ingest.llm_allowed
    ok = LLM_LEVELS.index(allowed_level) >= LLM_LEVELS.index(min_level)
    if not ok and raise_on_deny:
        raise PerimeterDenied(
            f"{source_id}: llm_allowed={allowed_level} does not cover backend={backend}"
        )
    return ok


def clear_cache() -> None:
    ""
    _cached_load.cache_clear()


def _main(argv: list[str] | None = None) -> int:
    ""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Perimeter check (read-only, fail-closed).")
    parser.add_argument("source_id", nargs="?", help="source id to check")
    parser.add_argument("--path", default=None, help="alternative path to perimeters.yaml")
    parser.add_argument("--llm", default=None, choices=["api", "subscription"])
    parser.add_argument("--list", action="store_true", help="list all entries")
    args = parser.parse_args(argv)

    if args.list:
        reg = _registry(args.path)
        for sid, entry in reg.items():
            print(f"{entry['state']:<28} {sid:<28} llm={entry['llm_allowed']}")
        return 0
    if not args.source_id:
        parser.error("source_id or --list required")
    decision = check_ingestion(args.source_id, args.path)
    payload = {
        "source_id": decision.source_id,
        "allowed": decision.allowed,
        "state": decision.state,
        "llm_allowed": decision.llm_allowed,
        "reason": decision.reason,
    }
    if args.llm:
        payload["llm_backend_allowed"] = check_llm(args.source_id, args.llm, args.path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if decision.allowed else 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
