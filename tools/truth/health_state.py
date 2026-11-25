""

















from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

if not __package__:
    # Run as a script (python tools/truth/<file>.py): put tools/ on the path, drop this folder from it
    # (its module names would shadow other modules) and make the relative imports below work.
    import sys as _sys

    _here = Path(__file__).resolve().parent
    _sys.path[:] = [p for p in _sys.path if Path(p or ".").resolve() != _here]
    if str(_here.parent) not in _sys.path:
        _sys.path.insert(0, str(_here.parent))
    __package__ = "truth"
    import truth  # noqa: F401, E402

import sbk_config  # noqa: E402

from .checks.base import CheckResult, CheckStatus  # noqa: E402
from .receipt import Receipt, build_health_state_entry  # noqa: E402



DEFAULT_UNITS: tuple[str, ...] = (

    "email-work",
    "email-personal",
    "slack",
    "attio",
    "attio-calls",
    "calendar",
    "whatsapp",
    "plaud",
    "tactiq",
    "notion",
    "chatgpt",
    "gdrive",
    "linkedin",
    "leadsync",
    "contacts",
    "personio",
    "docusign",
    "clickup",
    "voice-memos",
    "whoop",
    "apple-health",

    "xs-l2-merge",
    "xs-l2-entity-resolve",
    "xs-l2-knowledge-extract",
    "xs-l2-people-universe",
    "xs-l3-index",
    "xs-l3-extract-relationships",
    "xs-l3-decay",
    "xs-l3-brief",
    "xs-l3-digest",
    "rq-00-scoring",
    "rq-03-type-detection",
    "knowledge-conflict",
    "golden-record",

    "api-ledger",
    "sb-backup",
    "cascade-monitor",
    "auto-alert",
    "dm-digest",
    "pipeline-status-push",
    "watermark-registry",
    "receipts-writer",
    "health-state",
)

_STATUS_RANK = {
    CheckStatus.BROKEN: 3,
    CheckStatus.DEGRADED: 2,
    CheckStatus.OK: 1,
    CheckStatus.UNKNOWN: 0,
    "broken": 3,
    "degraded": 2,
    "healthy": 1,
    "ok": 1,
    "unknown": 0,
}


_OUTCOME_TO_HEALTH: dict[str, str | None] = {
    "ok": "healthy",
    "empty_confirmed": "healthy",
    "degraded": "degraded",
    "broken": "broken",
    "skipped_lock": None,
    "skipped_window": None,
    "skipped_state": None,
    "refused_paid": None,
    "refused_state": None,
    "refused_perimeter": None,
    "refused_budget": None,
}


def _check_to_health(status: CheckStatus | str) -> str | None:
    s = status.value if isinstance(status, CheckStatus) else str(status)
    return {"ok": "healthy", "degraded": "degraded", "broken": "broken", "unknown": None}.get(s)


def derive_unit_status(
    receipts: list[Receipt] | None,
    checks: list[CheckResult] | None,
) -> tuple[str, dict]:
    ""



    receipts = receipts or []
    checks = checks or []
    signals: list[str] = []

    last_outcome = None
    last_as_of = None
    if receipts:
        latest = max(receipts, key=lambda r: r.as_of)
        last_outcome = latest.status.value
        last_as_of = latest.as_of
        health = _OUTCOME_TO_HEALTH.get(latest.status.value)
        if health is not None:
            signals.append(health)

    for c in checks:
        health = _check_to_health(c.status)
        if health is not None:
            signals.append(health)

    if not signals:
        status = "unknown"
    else:
        status = max(signals, key=lambda s: _STATUS_RANK.get(s, 0))

    meta = {
        "n_receipts": len(receipts),
        "n_checks": len(checks),
        "last_outcome": last_outcome,
        "last_receipt_as_of": last_as_of,
    }
    return status, meta


def build_health_state(
    units: list[str] | tuple[str, ...] = DEFAULT_UNITS,
    *,
    receipts_by_unit: dict[str, list[Receipt]] | None = None,
    checks_by_unit: dict[str, list[CheckResult]] | None = None,
    known_debt: dict[str, str] | list[str] | None = None,
    as_of=None,
    receipts_ref: str = "system/receipts/",
) -> dict:
    ""
    receipts_by_unit = receipts_by_unit or {}
    checks_by_unit = checks_by_unit or {}
    if isinstance(known_debt, list | tuple | set):
        known_debt = dict.fromkeys(known_debt, "")
    known_debt = known_debt or {}

    as_of_iso = (
        sbk_config.utc_now().isoformat()
        if as_of is None
        else (as_of if isinstance(as_of, str) else sbk_config.to_utc_aware(as_of).isoformat())
    )



    units = list(units)
    _extra = sorted((set(receipts_by_unit) | set(checks_by_unit)) - set(units))
    units = units + _extra

    summary = {"healthy": 0, "degraded": 0, "broken": 0, "unknown": 0}
    unit_entries = []
    for unit in units:
        receipts = receipts_by_unit.get(unit, [])
        checks = checks_by_unit.get(unit, [])
        status, meta = derive_unit_status(receipts, checks)
        summary[status] = summary.get(status, 0) + 1
        entry = build_health_state_entry(
            unit=unit,
            status=status,
            as_of=as_of_iso,
            receipts_ref=receipts_ref,
        )
        entry.update(meta)
        entry["checks"] = [
            {"check": c.check, "status": c.status.value, "detail": c.detail} for c in checks
        ]
        if unit in known_debt:
            entry["known_debt"] = True
            entry["known_debt_note"] = known_debt[unit]
        unit_entries.append(entry)

    return {
        "as_of": as_of_iso,
        "n_units": len(units),
        "summary": summary,
        "known_debt": sorted(known_debt.keys()),
        "units": unit_entries,
    }


def write_health_state(state: dict, root: str | Path | None = None) -> Path:
    ""





    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    system_dir = base / "system"
    out = system_dir / "health-state.json"
    sbk_config.safe_write_json(out, state)

    history = system_dir / "health-state-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "as_of": state.get("as_of"),
        "n_units": state.get("n_units"),
        "summary": state.get("summary"),
    }
    with open(history, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def _load_receipts_by_unit(root: Path) -> dict[str, list[Receipt]]:
    ""
    from .receipt import read_receipts

    receipts_dir = root / "system" / "receipts"
    by_unit: dict[str, list[Receipt]] = defaultdict(list)
    if not receipts_dir.exists():
        return {}
    for f in sorted(receipts_dir.glob("receipts-*.jsonl")):
        for r in read_receipts(f):
            by_unit[r.job_id].append(r)
    return dict(by_unit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Health state of the pipeline units, built from their run receipts")
    parser.add_argument("--root", default=None, help="another data root (default: the configured one)")
    parser.add_argument(
        "--units", default=None, help="comma-separated units (default: the canonical ones)"
    )
    parser.add_argument(
        "--write", action="store_true", help="write health-state.json (default: print only)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else sbk_config.DATA_ROOT
    units = tuple(u.strip() for u in args.units.split(",")) if args.units else DEFAULT_UNITS
    receipts_by_unit = _load_receipts_by_unit(root)
    state = build_health_state(units, receipts_by_unit=receipts_by_unit)

    if args.write:
        out = write_health_state(state, root=root)
        print(f"scritto: {out}", file=sys.stderr)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
