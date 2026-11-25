#!/usr/bin/env python3
""



















from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
for p in (_TOOLS_DIR, _THIS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sbk_config import VECTOR_DB_DIR  # noqa E402

log = logging.getLogger("sbk-l3-health")

TABLE_NAME = "sbk_chunks"
CHECKPOINT_FILE = VECTOR_DB_DIR / "index-checkpoint.json"


SLO_FRESHNESS_HOURS = {
    "email": 24,
    "slack": 24,
    "slack_dm": 24,
    "attio_call": 24,
    "attio_notes": 24,
    "plaud": 24,
    "tactiq": 24,
    "knowledge": 24,
    "whatsapp": 168,
    "calendar": 48,
    "_default": 168,
}




ON_DEMAND_SOURCES = frozenset(
    {
        "chatgpt",
        "gdrive",
        "domain",
        "network",
        "raw",
        "session",
        "voice_memo",
        "wa_photo_ocr",
        "wa_document",
        "email_attachment",
    }
)


def _human(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _status_icon(lag_h: float, slo_h: float) -> str:
    if lag_h <= slo_h:
        return "🟢"
    if lag_h <= slo_h * 2:
        return "🟡"
    return "🔴"


def gather() -> dict:
    ""
    out: dict = {"generated_at": datetime.now(UTC).isoformat()}


    table: dict = {}
    source_counts: dict[str, int] = {}
    tbl = None
    try:
        import lancedb

        db = lancedb.connect(str(VECTOR_DB_DIR))
        tbl = db.open_table(TABLE_NAME)
        table["rows"] = tbl.count_rows()
        table["columns"] = len(tbl.schema)
        table["has_schema_version"] = "schema_version" in tbl.schema.names
        try:
            table["versions"] = len(list(tbl.list_versions()))
        except Exception:
            table["versions"] = None
        try:
            table["indices"] = [i.name for i in tbl.list_indices()]
        except Exception:
            table["indices"] = None

        try:
            df = tbl.search().select(["source_type"]).limit(20_000_000).to_pandas()
            source_counts = df["source_type"].value_counts().to_dict()
        except Exception:
            source_counts = {}
    except Exception as e:
        table["error"] = str(e)[:120]

    lance_dir = VECTOR_DB_DIR / f"{TABLE_NAME}.lance"
    table["size_data"] = _human(_dir_size(lance_dir / "data"))
    table["size_indices"] = _human(_dir_size(lance_dir / "_indices"))
    table["size_versions"] = _human(_dir_size(lance_dir / "_versions"))
    table["size_total"] = _human(_dir_size(lance_dir))
    out["table"] = table


    sources = []
    if CHECKPOINT_FILE.exists():
        try:
            ck = json.loads(CHECKPOINT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            ck = {}
        now = datetime.now(UTC)
        for src, rec in sorted(ck.items()):
            if src.startswith("_"):
                continue
            ts = rec.get("timestamp", "")
            lag_h = None
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    lag_h = (now - dt).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass
            slo = SLO_FRESHNESS_HOURS.get(src, SLO_FRESHNESS_HOURS["_default"])
            on_demand = src in ON_DEMAND_SOURCES
            status = "❔"
            if on_demand:
                status = "⚪"
            elif lag_h is not None:
                status = "⏪" if lag_h < 0 else _status_icon(lag_h, slo)
            sources.append(
                {
                    "source": src,

                    "count": source_counts.get(src, rec.get("count", 0)),
                    "last_indexed": ts[:19] if ts else "?",
                    "lag_hours": round(lag_h, 1) if lag_h is not None else None,
                    "slo_hours": slo,
                    "status": status,
                }
            )
    out["sources"] = sources


    try:
        from monitoring.pipeline_metrics import get_metrics

        m = get_metrics(hours=24)
        out["jobs"] = {
            "total_24h": m.get("total"),
            "by_status": m.get("by_status"),
            "avg_duration_s": m.get("avg_duration_s"),
            "recent_failures": (m.get("recent_failures") or [])[:5],
        }
    except Exception as e:
        out["jobs"] = {"error": str(e)[:80]}


    try:
        from monitoring.api_ledger import get_cost_summary

        cs24 = get_cost_summary(hours=24)
        cs_all = get_cost_summary(hours=24 * 365)
        out["cost"] = {
            "window_24h_usd": cs24.get("total_cost_usd"),
            "window_24h_calls": cs24.get("total_calls"),
            "all_time_usd": cs_all.get("total_cost_usd"),
            "all_time_calls": cs_all.get("total_calls"),
            "daily_projection_usd": cs24.get("daily_projection_usd"),
        }
    except Exception as e:
        out["cost"] = {"error": str(e)[:80]}

    return out


_ASCII_MAP = {
    "🟢": "[OK]",
    "🟡": "[WARN]",
    "🔴": "[STALE]",
    "❔": "[?]",
    "⏪": "[FUT]",
    "⚪": "[ondemand]",
}


def render(data: dict, ascii_mode: bool = False) -> None:
    def st(icon: str) -> str:
        return _ASCII_MAP.get(icon, icon) if ascii_mode else icon

    t = data["table"]
    print("\n=== SBK L3 Health ===")
    print(f"  generato, {data['generated_at'][:19]}")
    print("\n[Tabella sbk_chunks]")
    if "error" in t:
        print(f"  errore, {t['error']}")
    else:
        sv = "v2" if t.get("has_schema_version") else "v1 (pre-migration)"
        print(f"  righe, {t.get('rows'):,}  |  colonne, {t.get('columns')} ({sv})")
        print(f"  versioni, {t.get('versions')}  |  indici, {t.get('indices')}")
    print(
        f"  dimensioni, data {t['size_data']}  _indices {t['size_indices']}  totale {t['size_total']}"
    )

    print("\n[Sorgenti, lag e freshness]")
    print(f"  {'src':<18} {'chunks':>9} {'lag':>9}  {'SLO':>6}  st")
    for s in data["sources"]:
        lag = f"{s['lag_hours']}h" if s["lag_hours"] is not None else "?"
        print(
            f"  {s['source']:<18} {s['count']:>9,} {lag:>9}  {s['slo_hours']:>4}h  {st(s['status'])}"
        )
    stale = [s["source"] for s in data["sources"] if s["status"] == "🔴"]
    if stale:
        print(f"\n  {st('🔴')} STALE (oltre 2x SLO), {', '.join(stale)}")

    j = data.get("jobs", {})
    print("\n[Run pipeline, ultime 24h]")
    if "error" in j:
        print(f"  n/d ({j['error']})")
    else:
        print(
            f"  totale {j.get('total_24h')}  |  per stato {j.get('by_status')}  |  durata media {j.get('avg_duration_s')}s"
        )
        fails = j.get("recent_failures") or []
        if fails:
            print(f"  {st('🔴')} fallimenti recenti, {len(fails)}")
            for f in fails:
                nm = f.get("name", f.get("script", "?"))
                print(f"    - {nm} ({f.get('status', '?')})")

    c = data.get("cost", {})
    print("\n[Cost]")
    if "error" in c:
        print(f"  n/d ({c['error']})")
    else:
        print(
            f"  ultime 24h, ${c.get('window_24h_usd')} ({c.get('window_24h_calls')} calls)  |  "
            f"all-time, ${c.get('all_time_usd')} ({c.get('all_time_calls')} calls)"
        )
    print()


def main() -> None:
    p = argparse.ArgumentParser(description="SBK L3 health check (read-only)")
    p.add_argument("--json", action="store_true", help="output JSON")
    p.add_argument("--ascii", action="store_true", help="status ascii invece di emoji (cron-safe)")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    data = gather()
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        render(data, ascii_mode=args.ascii)


if __name__ == "__main__":
    main()
