""










from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

_DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT", str(Path.home() / ".sbk-data")))
SYSTEM_DIR = _DATA_ROOT / "system"
LEDGER_FILE = SYSTEM_DIR / "api-call-ledger.jsonl"


_MAX_FILE_SIZE = 10 * 1024 * 1024

log = logging.getLogger("sbk-api-ledger")


_last_rotation_date: str | None = None


def _ensure_dir() -> None:
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)


def _maybe_rotate() -> None:
    ""
    global _last_rotation_date

    today = datetime.now(UTC).strftime("%Y-%m-%d")


    if _last_rotation_date is not None and _last_rotation_date != today:
        _do_rotate(_last_rotation_date)

    _last_rotation_date = today


    try:
        if LEDGER_FILE.exists() and LEDGER_FILE.stat().st_size > _MAX_FILE_SIZE:
            _do_rotate(today)
    except OSError:
        pass


def _do_rotate(date_suffix: str) -> None:
    ""
    if not LEDGER_FILE.exists():
        return
    archive = SYSTEM_DIR / f"api-call-ledger-{date_suffix}.jsonl"

    if archive.exists():
        try:
            with (
                open(LEDGER_FILE, encoding="utf-8") as src,
                open(archive, "a", encoding="utf-8") as dst,
            ):
                dst.write(src.read())
            LEDGER_FILE.unlink()
        except OSError as e:
            log.warning("Ledger rotation (append) failed: %s", e)
    else:
        try:
            LEDGER_FILE.rename(archive)
        except OSError as e:
            log.warning("Ledger rotation failed: %s", e)
    log.info("API ledger rotated -> %s", archive.name)


def log_api_call(
    service: str,
    method: str,
    direction: str,
    caller: str,
    status: str = "ok",
    detail: str | None = None,
    latency_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    *,
    paid: bool | None = None,
    cost_usd: float | None = None,
    cost_equiv_usd: float | None = None,
) -> None:
    ""






















    _ensure_dir()
    _maybe_rotate()

    entry = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "service": service,
        "method": method,
        "direction": direction,
        "caller": caller,
        "status": status,
    }
    if detail:
        entry["detail"] = detail[:200]
    if latency_ms is not None:
        entry["latency_ms"] = latency_ms
    if tokens_in is not None:
        entry["tokens_in"] = tokens_in
    if tokens_out is not None:
        entry["tokens_out"] = tokens_out


    is_paid = paid if paid is not None else (service in _PAID_SERVICES)
    equiv = (
        cost_equiv_usd
        if cost_equiv_usd is not None
        else _estimate_cost(service, tokens_in or 0, tokens_out or 0)
    )
    if is_paid or equiv > 0 or paid is not None:
        real = cost_usd if cost_usd is not None else (equiv if is_paid else 0.0)
        entry["paid"] = bool(is_paid)
        entry["cost_usd"] = round(float(real), 8)
        entry["cost_equiv_usd"] = round(float(equiv), 8)

    try:
        with open(LEDGER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except OSError as e:
        log.warning("Failed to write API ledger entry: %s", e)


def log_error_call(
    service: str,
    method: str,
    caller: str,
    error: str,
    *,
    direction: str = "READ",
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    paid: bool | None = None,
) -> None:
    ""






    log_api_call(
        service=service,
        method=method,
        direction=direction,
        caller=caller,
        status="error",
        detail=error,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        paid=paid,
    )


def get_recent(n: int = 50) -> list[dict]:
    ""
    if not LEDGER_FILE.exists():
        return []

    entries: list[dict] = []
    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:

            lines = f.readlines()
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        return []

    entries.reverse()
    return entries


def get_stats(hours: int = 1) -> dict:
    ""










    cutoff = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    cutoff_epoch = time.time() - hours * 3600
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    by_service: dict[str, dict] = {}
    recent_writes: list[dict] = []
    recent_errors: list[dict] = []
    total = 0

    if not LEDGER_FILE.exists():
        return {
            "window_hours": hours,
            "total": 0,
            "by_service": {},
            "recent_writes": [],
            "recent_errors": [],
        }

    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = entry.get("ts", "")
                if ts < cutoff_ts:
                    continue

                total += 1
                svc = entry.get("service", "unknown")
                direction = entry.get("direction", "READ")
                status = entry.get("status", "ok")

                if svc not in by_service:
                    by_service[svc] = {"READ": 0, "WRITE": 0, "errors": 0, "rate_limited": 0}

                bucket = by_service[svc]
                if direction in ("READ", "WRITE"):
                    bucket[direction] += 1
                if status == "error":
                    bucket["errors"] += 1
                if status == "rate_limited":
                    bucket["rate_limited"] += 1

                if direction == "WRITE":
                    recent_writes.append(entry)
                if status in ("error", "rate_limited"):
                    recent_errors.append(entry)

    except OSError:
        pass

    return {
        "window_hours": hours,
        "total": total,
        "by_service": by_service,
        "recent_writes": recent_writes[-20:],
        "recent_errors": recent_errors[-20:],
    }














_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "anthropic": {"input_per_m": 3.00, "output_per_m": 15.00, "note": "sonnet-tier; verify"},
    "deepseek": {"input_per_m": 0.14, "output_per_m": 0.28, "note": "verify"},
    "gemini": {"input_per_m": 0.075, "output_per_m": 0.30, "note": "flash-tier; verify"},

    "firecrawl": {"input_per_m": 0, "output_per_m": 0, "note": "credit-based"},
    "exa": {"input_per_m": 0, "output_per_m": 0, "note": "credit-based"},
    "perplexity": {"input_per_m": 0, "output_per_m": 0, "note": "credit-based"},
    "manus": {"input_per_m": 0, "output_per_m": 0, "note": "credit-based"},

    "slack": {"input_per_m": 0, "output_per_m": 0},
    "gmail": {"input_per_m": 0, "output_per_m": 0},
    "attio": {"input_per_m": 0, "output_per_m": 0},
    "notion": {"input_per_m": 0, "output_per_m": 0},
    "github": {"input_per_m": 0, "output_per_m": 0},
}


_PRICING_META: dict[str, dict[str, str]] = {
    "as_of": "2026-08-12",
    "verify_at_use": "true",
    "anthropic": {"source": "https://www.anthropic.com/pricing", "as_of": "2026-08-12"},
    "deepseek": {
        "source": "https://api-docs.deepseek.com/quick_start/pricing",
        "as_of": "2026-08-12",
    },
    "gemini": {"source": "https://ai.google.dev/pricing", "as_of": "2026-08-12"},
}



_PAID_SERVICES: frozenset[str] = frozenset({"anthropic", "deepseek", "gemini"})


def _estimate_cost(service: str, tokens_in: int, tokens_out: int) -> float:
    ""
    pricing = _DEFAULT_PRICING.get(service, {})
    cost_in = (tokens_in / 1_000_000) * pricing.get("input_per_m", 0)
    cost_out = (tokens_out / 1_000_000) * pricing.get("output_per_m", 0)
    return cost_in + cost_out


def get_cost_summary(hours: int = 24) -> dict:
    ""










    cutoff_epoch = time.time() - hours * 3600
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    svc_data: dict[str, dict] = {}
    total_calls = 0

    if not LEDGER_FILE.exists():
        return {
            "hours": hours,
            "total_cost_usd": 0,
            "daily_projection_usd": 0,
            "total_calls": 0,
            "by_service": [],
        }

    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("ts", "") < cutoff_ts:
                    continue

                total_calls += 1
                svc = entry.get("service", "unknown")
                if svc not in svc_data:
                    svc_data[svc] = {"calls": 0, "tokens_in": 0, "tokens_out": 0}
                svc_data[svc]["calls"] += 1
                svc_data[svc]["tokens_in"] += entry.get("tokens_in", 0)
                svc_data[svc]["tokens_out"] += entry.get("tokens_out", 0)
    except OSError:
        pass

    by_service = []
    total_cost = 0.0
    for svc, d in sorted(svc_data.items()):
        cost = _estimate_cost(svc, d["tokens_in"], d["tokens_out"])
        total_cost += cost
        by_service.append(
            {
                "service": svc,
                "calls": d["calls"],
                "tokens_in": d["tokens_in"],
                "tokens_out": d["tokens_out"],
                "cost_usd": round(cost, 6),
            }
        )


    projection = (total_cost / hours * 24) if hours > 0 and total_cost > 0 else 0

    return {
        "hours": hours,
        "total_cost_usd": round(total_cost, 6),
        "daily_projection_usd": round(projection, 4),
        "total_calls": total_calls,
        "by_service": by_service,
    }


def rotate() -> None:
    ""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    _do_rotate(today)


def get_cost_trend(days: int = 7) -> list[dict]:
    ""




    from collections import defaultdict

    cutoff_epoch = time.time() - days * 86400
    cutoff_ts = datetime.fromtimestamp(cutoff_epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")

    daily: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "calls": 0})


    files_to_scan: list[Path] = []
    if LEDGER_FILE.exists():
        files_to_scan.append(LEDGER_FILE)
    if SYSTEM_DIR.exists():
        for f in SYSTEM_DIR.glob("api-call-ledger-*.jsonl"):
            files_to_scan.append(f)

    for filepath in files_to_scan:
        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = entry.get("ts", "")
                    if ts < cutoff_ts:
                        continue
                    day = ts[:10]
                    tokens_in = entry.get("tokens_in", 0)
                    tokens_out = entry.get("tokens_out", 0)
                    svc = entry.get("service", "unknown")
                    cost = _estimate_cost(svc, tokens_in, tokens_out)
                    daily[day]["cost"] += cost
                    daily[day]["calls"] += 1
        except OSError:
            continue

    result = []
    for day in sorted(daily.keys()):
        result.append(
            {
                "date": day,
                "total_cost_usd": round(daily[day]["cost"], 6),
                "total_calls": daily[day]["calls"],
            }
        )

    return result
