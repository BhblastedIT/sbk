""











from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config  # noqa: E402

__all__ = ["compute_cost_report", "main"]

_DRIFT_EPSILON = 1e-9


def _resolve_ledger_path(root: str | Path | None, ledger_path: str | Path | None) -> Path:
    if ledger_path is not None:
        return Path(ledger_path)
    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    return base / "system" / "api-call-ledger.jsonl"


def _estimate_equiv(service: str, tokens_in: int, tokens_out: int) -> float:
    from monitoring.api_ledger import _estimate_cost

    return _estimate_cost(service, tokens_in, tokens_out)


def _paid_services() -> frozenset[str]:
    from monitoring.api_ledger import _PAID_SERVICES

    return _PAID_SERVICES


def compute_cost_report(
    *,
    root: str | Path | None = None,
    ledger_path: str | Path | None = None,
    hours: int = 24,
    drift_threshold_pct: float = 20.0,
    as_of=None,
) -> dict:
    ""
    path = _resolve_ledger_path(root, ledger_path)
    now = sbk_config.utc_now() if as_of is None else sbk_config.to_utc_aware(as_of)
    cutoff_epoch = now.timestamp() - hours * 3600
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    paid = _paid_services()
    svc: dict[str, dict] = {}
    total_calls = 0

    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("ts", "") < cutoff_ts:
                    continue
                total_calls += 1
                s = e.get("service", "unknown")
                d = svc.setdefault(
                    s,
                    {
                        "calls": 0,
                        "errors": 0,
                        "paid_errors": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "cost_usd": 0.0,
                        "cost_equiv_usd": 0.0,
                    },
                )
                d["calls"] += 1
                ti = int(e.get("tokens_in", 0) or 0)
                to = int(e.get("tokens_out", 0) or 0)
                d["tokens_in"] += ti
                d["tokens_out"] += to
                is_error = e.get("status") in ("error", "rate_limited")
                is_paid = bool(e.get("paid", s in paid))
                if is_error:
                    d["errors"] += 1
                    if is_paid:
                        d["paid_errors"] += 1

                equiv = e.get("cost_equiv_usd")
                if equiv is None:
                    equiv = _estimate_equiv(s, ti, to)
                d["cost_equiv_usd"] += float(equiv)
                real = e.get("cost_usd")
                if real is None:
                    real = float(equiv) if is_paid else 0.0
                d["cost_usd"] += float(real)

    by_service = []
    flags: list[dict] = []
    total_cost = 0.0
    total_equiv = 0.0
    for s in sorted(svc):
        d = svc[s]
        total_cost += d["cost_usd"]
        total_equiv += d["cost_equiv_usd"]
        drift_pct = None
        if d["cost_equiv_usd"] > _DRIFT_EPSILON:
            drift_pct = abs(d["cost_usd"] - d["cost_equiv_usd"]) / d["cost_equiv_usd"] * 100
        row = {
            "service": s,
            "calls": d["calls"],
            "errors": d["errors"],
            "paid_errors": d["paid_errors"],
            "tokens_in": d["tokens_in"],
            "tokens_out": d["tokens_out"],
            "cost_usd": round(d["cost_usd"], 8),
            "cost_equiv_usd": round(d["cost_equiv_usd"], 8),
            "drift_pct": None if drift_pct is None else round(drift_pct, 4),
        }
        by_service.append(row)
        if drift_pct is not None and drift_pct > drift_threshold_pct:
            flags.append(
                {
                    "type": "cost_drift",
                    "service": s,
                    "drift_pct": round(drift_pct, 4),
                    "cost_usd": round(d["cost_usd"], 8),
                    "cost_equiv_usd": round(d["cost_equiv_usd"], 8),
                    "detail": (
                        f"drift {drift_pct:.1f}% tra spesa reale e equivalente "
                        f"(soglia {drift_threshold_pct:.0f}%)"
                    ),
                }
            )
        if d["paid_errors"] > 0:
            flags.append(
                {
                    "type": "paid_errors",
                    "service": s,
                    "paid_errors": d["paid_errors"],
                    "detail": f"{d['paid_errors']} chiamate paid errate = spesa senza risultato",
                }
            )

    return {
        "as_of": now.isoformat(),
        "window_hours": hours,
        "ledger": str(path),
        "ledger_exists": path.exists(),
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 8),
        "total_cost_equiv_usd": round(total_equiv, 8),
        "drift_threshold_pct": drift_threshold_pct,
        "by_service": by_service,
        "flags": flags,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cost report from the API call ledger (read-only)")
    parser.add_argument("--root", default=None, help="another data root (default: the configured one)")
    parser.add_argument("--ledger", default=None, help="explicit path of the ledger .jsonl")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--drift-threshold", type=float, default=20.0)
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero when something is flagged (for monitoring)"
    )
    args = parser.parse_args(argv)

    report = compute_cost_report(
        root=args.root,
        ledger_path=args.ledger,
        hours=args.hours,
        drift_threshold_pct=args.drift_threshold,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and report["flags"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
