#!/usr/bin/env python3
""























from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path



_THIS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _THIS_DIR.parent
_PROJECT_ROOT = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    DATA_ROOT,
    DEEP_RESPONSES_DIR,
    NLP_DIR,
    RELATIONSHIP_RESPONSES_DIR,
)



LOG_FILE = NLP_DIR / "extraction-launch.log"
API_USAGE_FILE = NLP_DIR / "api-usage.json"
BATCH_RESPONSES_DIR = NLP_DIR / "batch-responses"


EXTRACT_SCRIPT = "tools/cross-source/xs-l3-extract.py"
REL_SCRIPT = "tools/cross-source/xs-l3-extract-relationships.py"
DEEP_SCRIPT = "tools/cross-source/xs-l3-deep-extract.py"


PROVIDER_PRICING = {
    "deepseek": {"input": 0.28, "output": 0.42},
    "gemini": {"input": 0.10, "output": 0.40},
    "anthropic": {"input": 0.80, "output": 4.0},
}

log = logging.getLogger("sbk-launch-extraction")



_active_processes: list[subprocess.Popen] = []
_shutdown_event = threading.Event()





def _handle_signal(signum: int, frame) -> None:
    ""
    sig_name = signal.Signals(signum).name
    log.warning(f"Received {sig_name} — killing {len(_active_processes)} subprocess(es)")
    _shutdown_event.set()
    for proc in _active_processes:
        try:
            proc.terminate()
        except OSError:
            pass

    time.sleep(3)
    for proc in _active_processes:
        try:
            proc.kill()
        except OSError:
            pass
    sys.exit(130)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)





def setup_logging(verbose: bool = False) -> None:
    ""
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)


    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))

    root = logging.getLogger("sbk-launch-extraction")
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)





def _format_elapsed(seconds: float) -> str:
    ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def _stream_output(
    proc: subprocess.Popen,
    prefix: str,
    log_file_handle,
) -> None:
    ""
    try:
        for line in iter(proc.stdout.readline, ""):
            if _shutdown_event.is_set():
                break
            stripped = line.rstrip("\n")
            if stripped:
                prefixed = f"[{prefix}] {stripped}"
                log.info(prefixed)
                if log_file_handle:
                    log_file_handle.write(prefixed + "\n")
                    log_file_handle.flush()
    except (OSError, ValueError):
        pass


def run_subprocess(
    cmd: list[str],
    prefix: str,
    log_file_handle,
    env: dict | None = None,
) -> subprocess.Popen:
    ""



    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    log.info(f"[{prefix}] Starting: {' '.join(cmd)}")
    if log_file_handle:
        log_file_handle.write(f"\n{'=' * 70}\n")
        log_file_handle.write(f"[{prefix}] CMD: {' '.join(cmd)}\n")
        log_file_handle.write(f"[{prefix}] START: {datetime.now(UTC).isoformat()}\n")
        log_file_handle.write(f"{'=' * 70}\n\n")
        log_file_handle.flush()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(_PROJECT_ROOT),
        env=full_env,
        bufsize=1,
    )
    _active_processes.append(proc)


    thread = threading.Thread(
        target=_stream_output,
        args=(proc, prefix, log_file_handle),
        daemon=True,
    )
    thread.start()

    return proc





def count_email_docs() -> int:
    ""
    try:
        import pandas as pd

        filtered_file = DATA_ROOT / "emails" / "filtered-messages.parquet"
        if filtered_file.exists():
            df = pd.read_parquet(filtered_file)
            return len(df)

        email_dir = DATA_ROOT / "emails"
        total = 0
        for pq in email_dir.glob("*-messages.parquet"):
            if pq.name == "filtered-messages.parquet":
                continue
            df = pd.read_parquet(pq, columns=["message_id"])
            total += len(df)
        return total
    except Exception as e:
        log.warning(f"Could not count email docs: {e}")
        return 0


def count_cached_extract() -> tuple[int, int]:
    ""
    cache_dir = BATCH_RESPONSES_DIR / "email"
    if not cache_dir.exists():
        return 0, count_email_docs()
    cached = sum(1 for f in cache_dir.iterdir() if f.suffix == ".json")
    total = count_email_docs()
    return cached, total


def count_cached_rel() -> tuple[int, int]:
    ""
    cache_dir = RELATIONSHIP_RESPONSES_DIR / "email"
    if not cache_dir.exists():
        return 0, count_email_docs()
    cached = sum(1 for f in cache_dir.iterdir() if f.suffix == ".json")
    total = count_email_docs()
    return cached, total


def count_cached_deep() -> tuple[int, int]:
    ""
    cache_dir = DEEP_RESPONSES_DIR / "email"
    if not cache_dir.exists():
        return 0, count_email_docs()

    cached = sum(
        1 for f in cache_dir.iterdir() if f.suffix == ".json" and f.stem.endswith("_chunk_0")
    )
    total = count_email_docs()
    return cached, total


def find_failed_rel_docs() -> list[str]:
    ""




    try:
        import pandas as pd

        filtered_file = DATA_ROOT / "emails" / "filtered-messages.parquet"
        if not filtered_file.exists():
            log.warning("No filtered-messages.parquet found, cannot detect failures")
            return []

        df = pd.read_parquet(filtered_file, columns=["message_id"])
        all_ids = set(df["message_id"].astype(str).tolist())

        cache_dir = RELATIONSHIP_RESPONSES_DIR / "email"
        if not cache_dir.exists():
            return list(all_ids)

        cached_ids = set()
        for f in cache_dir.iterdir():
            if f.suffix == ".json":

                stem = f.stem

                if "_chunk_" in stem:
                    stem = stem.rsplit("_chunk_", 1)[0]
                cached_ids.add(stem)

        return sorted(all_ids - cached_ids)

    except Exception as e:
        log.warning(f"Could not scan for failed rel docs: {e}")
        return []


def find_failed_deep_docs() -> list[str]:
    ""
    try:
        import pandas as pd

        filtered_file = DATA_ROOT / "emails" / "filtered-messages.parquet"
        if not filtered_file.exists():
            log.warning("No filtered-messages.parquet found, cannot detect failures")
            return []

        df = pd.read_parquet(filtered_file, columns=["message_id"])
        all_ids = set(df["message_id"].astype(str).tolist())

        cache_dir = DEEP_RESPONSES_DIR / "email"
        if not cache_dir.exists():
            return list(all_ids)

        cached_ids = set()
        for f in cache_dir.iterdir():
            if f.suffix == ".json" and f.stem.endswith("_chunk_0"):
                source_id = f.stem.rsplit("_chunk_0", 1)[0]
                cached_ids.add(source_id)

        return sorted(all_ids - cached_ids)

    except Exception as e:
        log.warning(f"Could not scan for failed deep docs: {e}")
        return []





def estimate_costs(total_docs: int) -> dict:
    ""

    avg_input_tokens = 1500
    avg_output_tokens = 500


    extract_input_cost = (
        total_docs * avg_input_tokens * PROVIDER_PRICING["deepseek"]["input"] / 1_000_000
    )
    extract_output_cost = (
        total_docs * avg_output_tokens * PROVIDER_PRICING["deepseek"]["output"] / 1_000_000
    )
    extract_cost = extract_input_cost + extract_output_cost


    rel_calls = total_docs
    rel_input_cost = rel_calls * avg_input_tokens * PROVIDER_PRICING["gemini"]["input"] / 1_000_000
    rel_output_cost = (
        rel_calls * avg_output_tokens * PROVIDER_PRICING["gemini"]["output"] / 1_000_000
    )
    rel_cost = rel_input_cost + rel_output_cost


    deep_input_cost = (
        total_docs * avg_input_tokens * PROVIDER_PRICING["gemini"]["input"] / 1_000_000
    )
    deep_output_cost = (
        total_docs * avg_output_tokens * PROVIDER_PRICING["gemini"]["output"] / 1_000_000
    )
    deep_cost = deep_input_cost + deep_output_cost

    total_cost = extract_cost + rel_cost + deep_cost

    return {
        "total_docs": total_docs,
        "extract": {"provider": "deepseek", "cost": round(extract_cost, 2)},
        "rel": {"provider": "gemini", "cost": round(rel_cost, 2)},
        "deep": {"provider": "gemini", "cost": round(deep_cost, 2)},
        "total_cost": round(total_cost, 2),
    }





def get_api_usage_since(start_time: str) -> dict:
    ""
    if not API_USAGE_FILE.exists():
        return {"total_cost": 0.0, "total_calls": 0, "by_provider": {}}

    try:
        entries = json.loads(API_USAGE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"total_cost": 0.0, "total_calls": 0, "by_provider": {}}

    total_cost = 0.0
    total_calls = 0
    by_provider: dict[str, float] = {}

    for entry in entries:
        if entry.get("timestamp", "") >= start_time:
            cost = entry.get("cost_usd", 0.0)
            total_cost += cost
            total_calls += 1
            provider = entry.get("provider", "unknown")
            by_provider[provider] = by_provider.get(provider, 0.0) + cost

    return {
        "total_cost": round(total_cost, 4),
        "total_calls": total_calls,
        "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
    }





def count_facts_in_cache(cache_dir: Path) -> int:
    ""
    total = 0
    if not cache_dir.exists():
        return 0
    for f in cache_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                total += len(data)
            elif isinstance(data, dict):

                for key in ("facts", "relationships", "items", "decisions", "action_items"):
                    if key in data and isinstance(data[key], list):
                        total += len(data[key])
                        break
                else:
                    total += 1
        except (json.JSONDecodeError, OSError):
            pass
    return total





def run_phase_1(
    workers: int,
    batch_size: int,
    skip_extract: bool,
    skip_rel: bool,
    verbose: bool,
    log_file_handle,
) -> dict:
    ""



    log.info("=" * 70)
    log.info("PHASE 1 — Parallel extraction (extract + extract-rel)")
    log.info("=" * 70)

    results = {"extract": None, "rel": None}
    procs = {}


    if not skip_extract:
        extract_cmd = [
            "uv",
            "run",
            "python",
            EXTRACT_SCRIPT,
            "--batch",
            "--source",
            "email",
            "--provider",
            "deepseek",
            "--workers",
            str(workers * 2),
        ]
        if verbose:
            extract_cmd.append("--verbose")

    if not skip_rel:
        rel_cmd = [
            "uv",
            "run",
            "python",
            REL_SCRIPT,
            "--batch",
            "--source",
            "email",
            "--provider",
            "gemini",
            "--workers",
            str(workers),
            "--batch-size",
            str(batch_size),
        ]
        if verbose:
            rel_cmd.append("--verbose")


    phase_start = time.monotonic()

    if not skip_extract:
        procs["extract"] = run_subprocess(extract_cmd, "EXTRACT", log_file_handle)

    if not skip_rel:
        procs["rel"] = run_subprocess(rel_cmd, "REL", log_file_handle)

    if not procs:
        log.info("Phase 1: nothing to run (both extract and rel skipped)")
        return results


    for name, proc in procs.items():
        proc.wait()
        _active_processes.remove(proc)
        elapsed = _format_elapsed(time.monotonic() - phase_start)
        rc = proc.returncode
        results[name] = rc
        if rc == 0:
            log.info(f"[{name.upper()}] Completed successfully ({elapsed})")
        else:
            log.error(f"[{name.upper()}] Exited with code {rc} ({elapsed})")

    total_elapsed = _format_elapsed(time.monotonic() - phase_start)
    log.info(f"Phase 1 completed in {total_elapsed}")
    return results


def run_phase_2(
    workers: int,
    batch_size: int,
    verbose: bool,
    log_file_handle,
) -> int | None:
    ""



    log.info("")
    log.info("=" * 70)
    log.info("PHASE 2 — Deep extraction (deep-extract on Gemini)")
    log.info("=" * 70)

    deep_cmd = [
        "uv",
        "run",
        "python",
        DEEP_SCRIPT,
        "--batch",
        "--source",
        "email",
        "--provider",
        "gemini",
        "--workers",
        str(workers),
        "--batch-size",
        str(batch_size),
    ]
    if verbose:
        deep_cmd.append("--verbose")

    phase_start = time.monotonic()
    proc = run_subprocess(deep_cmd, "DEEP", log_file_handle)
    proc.wait()
    _active_processes.remove(proc)

    elapsed = _format_elapsed(time.monotonic() - phase_start)
    rc = proc.returncode
    if rc == 0:
        log.info(f"[DEEP] Completed successfully ({elapsed})")
    else:
        log.error(f"[DEEP] Exited with code {rc} ({elapsed})")

    log.info(f"Phase 2 completed in {elapsed}")
    return rc


def run_phase_3(
    verbose: bool,
    log_file_handle,
) -> dict:
    ""




    log.info("")
    log.info("=" * 70)
    log.info("PHASE 3 — Retry failures with DeepSeek")
    log.info("=" * 70)

    phase_start = time.monotonic()


    failed_rel = find_failed_rel_docs()
    failed_deep = find_failed_deep_docs()

    log.info(f"Failed rel docs:  {len(failed_rel)}")
    log.info(f"Failed deep docs: {len(failed_deep)}")

    results = {
        "rel_failed": len(failed_rel),
        "rel_retried": 0,
        "rel_recovered": 0,
        "deep_failed": len(failed_deep),
        "deep_retried": 0,
        "deep_recovered": 0,
    }

    if not failed_rel and not failed_deep:
        log.info("No failures to retry — Phase 3 complete")
        return results


    if failed_rel:
        log.info(f"Retrying {len(failed_rel)} failed rel docs with DeepSeek...")


        batch_size = 100
        for batch_start in range(0, len(failed_rel), batch_size):
            if _shutdown_event.is_set():
                break
            batch_end = min(batch_start + batch_size, len(failed_rel))
            batch_count = batch_end - batch_start



            retry_cmd = [
                "uv",
                "run",
                "python",
                REL_SCRIPT,
                "--batch",
                "--source",
                "email",
                "--provider",
                "deepseek",
                "--workers",
                "10",
            ]
            if verbose:
                retry_cmd.append("--verbose")

            log.info(
                f"  Retry batch {batch_start // batch_size + 1}: "
                f"docs {batch_start + 1}-{batch_end} of {len(failed_rel)}"
            )
            proc = run_subprocess(retry_cmd, "RETRY-REL", log_file_handle)
            proc.wait()
            _active_processes.remove(proc)
            results["rel_retried"] += batch_count

            if proc.returncode != 0:
                log.warning(f"  Retry batch exited with code {proc.returncode}")
            break


        still_failed = find_failed_rel_docs()
        results["rel_recovered"] = len(failed_rel) - len(still_failed)
        log.info(
            f"  Rel recovery: {results['rel_recovered']}/{len(failed_rel)} recovered, "
            f"{len(still_failed)} still failed"
        )


    if failed_deep:
        log.info(f"Retrying {len(failed_deep)} failed deep docs with DeepSeek...")

        retry_cmd = [
            "uv",
            "run",
            "python",
            DEEP_SCRIPT,
            "--batch",
            "--source",
            "email",
            "--provider",
            "deepseek",
            "--workers",
            "10",
        ]
        if verbose:
            retry_cmd.append("--verbose")

        proc = run_subprocess(retry_cmd, "RETRY-DEEP", log_file_handle)
        proc.wait()
        _active_processes.remove(proc)
        results["deep_retried"] = len(failed_deep)

        if proc.returncode != 0:
            log.warning(f"  Retry exited with code {proc.returncode}")


        still_failed = find_failed_deep_docs()
        results["deep_recovered"] = len(failed_deep) - len(still_failed)
        log.info(
            f"  Deep recovery: {results['deep_recovered']}/{len(failed_deep)} recovered, "
            f"{len(still_failed)} still failed"
        )

    elapsed = _format_elapsed(time.monotonic() - phase_start)
    log.info(f"Phase 3 completed in {elapsed}")
    return results





def run_dry_run(workers: int, batch_size: int) -> None:
    ""
    total_docs = count_email_docs()
    cached_extract, _ = count_cached_extract()
    cached_rel, _ = count_cached_rel()
    cached_deep, _ = count_cached_deep()

    new_extract = max(0, total_docs - cached_extract)
    new_rel = max(0, total_docs - cached_rel)
    new_deep = max(0, total_docs - cached_deep)

    costs = estimate_costs(total_docs)




    extract_time_min = new_extract / 200 if new_extract else 0
    rel_time_min = new_rel / 150 if new_rel else 0
    deep_time_min = new_deep / 150 if new_deep else 0
    phase1_time = max(extract_time_min, rel_time_min)
    total_time_min = phase1_time + deep_time_min

    log.info("=" * 70)
    log.info("EMAIL EXTRACTION PIPELINE — DRY RUN")
    log.info("=" * 70)
    log.info("")
    log.info("  Total email docs (post-filter): %s", f"{total_docs:,}")
    log.info("")
    log.info(
        "  %s %s %s %s %s %s",
        f"{'Script':<25s}",
        f"{'Provider':<12s}",
        f"{'Workers':<10s}",
        f"{'Cached':<10s}",
        f"{'New':<10s}",
        f"{'Cost':>8s}",
    )
    log.info("  %s %s %s %s %s %s", "-" * 25, "-" * 12, "-" * 10, "-" * 10, "-" * 10, "-" * 8)
    log.info(
        "  %s %s %s %s %s $%s",
        f"{'extract.py':<25s}",
        f"{'DeepSeek':<12s}",
        f"{workers * 2:<10d}",
        f"{cached_extract:<10,d}",
        f"{new_extract:<10,d}",
        f"{costs['extract']['cost']:>6.2f}",
    )
    log.info(
        "  %s %s %s %s %s $%s",
        f"{'extract-rel.py':<25s}",
        f"{'Gemini':<12s}",
        f"{workers:<10d}",
        f"{cached_rel:<10,d}",
        f"{new_rel:<10,d}",
        f"{costs['rel']['cost']:>6.2f}",
    )
    log.info(
        "  %s %s %s %s %s $%s",
        f"{'deep-extract.py':<25s}",
        f"{'Gemini':<12s}",
        f"{workers:<10d}",
        f"{cached_deep:<10,d}",
        f"{new_deep:<10,d}",
        f"{costs['deep']['cost']:>6.2f}",
    )
    log.info("  %s %s %s %s %s %s", "-" * 25, "-" * 12, "-" * 10, "-" * 10, "-" * 10, "-" * 8)
    log.info(
        "  %s %s %s %s %s $%s",
        f"{'TOTAL':<25s}",
        f"{'':12s}",
        f"{'':10s}",
        f"{'':10s}",
        f"{'':10s}",
        f"{costs['total_cost']:>6.2f}",
    )
    log.info("")
    log.info("  Estimated time:")
    log.info("    Phase 1 (parallel): ~%.0f min (extract + rel run simultaneously)", phase1_time)
    log.info("    Phase 2 (deep):     ~%.0f min", deep_time_min)
    log.info("    Phase 3 (retry):    ~5 min (depends on failure rate)")
    log.info("    Total:              ~%.0f min", total_time_min + 5)
    log.info("")
    log.info("  Phase execution plan:")
    log.info(
        "    Phase 1: extract.py (DeepSeek, %dw) || extract-rel.py (Gemini, %dw, batch=%d)",
        workers * 2,
        workers,
        batch_size,
    )
    log.info("    Phase 2: deep-extract.py (Gemini, %dw)", workers)
    log.info("    Phase 3: Retry failures with DeepSeek")
    log.info("=" * 70)





def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrated Email Extraction Pipeline (3 phases, dual-provider)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phases:
  1  extract.py (DeepSeek) + extract-rel.py (Gemini) — parallel
  2  deep-extract.py (Gemini) — after Phase 1
  3  Retry failures with DeepSeek fallback

Examples:
  %(prog)s                     # Full run (all 3 phases)
  %(prog)s --dry-run           # Estimate only
  %(prog)s --phase 2           # Only deep-extract
  %(prog)s --phase 3           # Only retry failures
  %(prog)s --skip-extract      # Skip extract.py in Phase 1
  %(prog)s --workers 30        # 30 workers (60 for extract)
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show estimates without running",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker per script. Default: calcolato sulla memoria disponibile "
        "(sbk_resources.io_workers(), lavoro legato all'attesa di risposte API).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Docs per Gemini API call for multi-doc batching (default 10)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        help="Run only this phase (1, 2, or 3)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip extract.py in Phase 1",
    )
    parser.add_argument(
        "--skip-rel",
        action="store_true",
        help="Skip extract-rel.py in Phase 1",
    )
    parser.add_argument(
        "--skip-deep",
        action="store_true",
        help="Skip deep-extract.py in Phase 2",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)


    now = datetime.now(UTC)
    log.info("=" * 70)
    log.info("SBK Email Extraction Pipeline")
    log.info(f"Started: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if args.workers is None:
        try:
            from sbk_resources import io_workers, shared_state

            args.workers = io_workers()
            log.info(
                "Worker calcolati sulle risorse disponibili: %d — %s", args.workers, shared_state()
            )
        except ImportError:
            args.workers = 8
            log.warning("sbk_resources non disponibile: uso 8 worker (prudente)")

    log.info(f"Workers: {args.workers} (extract gets {args.workers * 2})")
    log.info(f"Batch size: {args.batch_size}")
    if args.phase:
        log.info(f"Running phase {args.phase} only")
    log.info("=" * 70)


    if args.dry_run:
        run_dry_run(args.workers, args.batch_size)
        return


    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115
    log_fh.write(f"\n\n{'#' * 70}\n")
    log_fh.write(f"# EXTRACTION LAUNCH — {now.isoformat()}\n")
    log_fh.write(f"# Workers: {args.workers}, Batch size: {args.batch_size}\n")
    log_fh.write(f"# Phase: {args.phase or 'ALL'}\n")
    log_fh.write(f"{'#' * 70}\n\n")

    start_time = now.isoformat()
    pipeline_start = time.monotonic()

    phase_results = {}

    try:

        if args.phase is None or args.phase == 1:
            if not (args.skip_extract and args.skip_rel):
                phase_results["phase1"] = run_phase_1(
                    workers=args.workers,
                    batch_size=args.batch_size,
                    skip_extract=args.skip_extract,
                    skip_rel=args.skip_rel,
                    verbose=args.verbose,
                    log_file_handle=log_fh,
                )
            else:
                log.info("Phase 1: skipped (both extract and rel skipped)")


        if args.phase is None or args.phase == 2:
            if not args.skip_deep:
                phase_results["phase2"] = run_phase_2(
                    workers=args.workers,
                    batch_size=args.batch_size,
                    verbose=args.verbose,
                    log_file_handle=log_fh,
                )
            else:
                log.info("Phase 2: skipped (--skip-deep)")


        if args.phase is None or args.phase == 3:
            phase_results["phase3"] = run_phase_3(
                verbose=args.verbose,
                log_file_handle=log_fh,
            )

    finally:
        log_fh.close()



    total_elapsed = _format_elapsed(time.monotonic() - pipeline_start)
    usage = get_api_usage_since(start_time)


    cached_extract, total_docs = count_cached_extract()
    cached_rel, _ = count_cached_rel()
    cached_deep, _ = count_cached_deep()


    rel_facts = count_facts_in_cache(RELATIONSHIP_RESPONSES_DIR / "email")
    deep_facts = count_facts_in_cache(DEEP_RESPONSES_DIR / "email")
    extract_facts = count_facts_in_cache(BATCH_RESPONSES_DIR / "email")

    log.info("")
    log.info("=" * 70)
    log.info("EXTRACTION PIPELINE — FINAL REPORT")
    log.info("=" * 70)
    log.info("  Total time:        %s", total_elapsed)
    log.info("  Total email docs:  %s", f"{total_docs:,}")
    log.info("")
    log.info(
        "  %s %s %s %s",
        f"{'Script':<25s}",
        f"{'Cached':<10s}",
        f"{'Facts':>10s}",
        f"{'Status':>12s}",
    )
    log.info("  %s %s %s %s", "-" * 25, "-" * 10, "-" * 10, "-" * 12)

    p1 = phase_results.get("phase1", {})
    extract_status = (
        "skipped"
        if args.skip_extract
        else ("OK" if p1.get("extract") == 0 else f"exit {p1.get('extract', '?')}")
    )
    rel_status = (
        "skipped"
        if args.skip_rel
        else ("OK" if p1.get("rel") == 0 else f"exit {p1.get('rel', '?')}")
    )
    p2 = phase_results.get("phase2")
    deep_status = (
        "skipped"
        if args.skip_deep
        else ("OK" if p2 == 0 else f"exit {p2 if p2 is not None else '?'}")
    )

    log.info(
        "  %s %s %s %s",
        f"{'extract.py':<25s}",
        f"{cached_extract:<10,d}",
        f"{extract_facts:>10,d}",
        f"{extract_status:>12s}",
    )
    log.info(
        "  %s %s %s %s",
        f"{'extract-rel.py':<25s}",
        f"{cached_rel:<10,d}",
        f"{rel_facts:>10,d}",
        f"{rel_status:>12s}",
    )
    log.info(
        "  %s %s %s %s",
        f"{'deep-extract.py':<25s}",
        f"{cached_deep:<10,d}",
        f"{deep_facts:>10,d}",
        f"{deep_status:>12s}",
    )


    p3 = phase_results.get("phase3")
    if p3 and isinstance(p3, dict):
        log.info("")
        log.info("  Retry results (Phase 3):")
        log.info("    Rel:  %d/%d recovered", p3["rel_recovered"], p3["rel_failed"])
        log.info("    Deep: %d/%d recovered", p3["deep_recovered"], p3["deep_failed"])


    log.info("")
    if usage["total_calls"] > 0:
        log.info("  API calls this run: %s", f"{usage['total_calls']:,}")
        log.info("  Cost this run:      $%.2f", usage["total_cost"])
        for provider, cost in sorted(usage["by_provider"].items()):
            log.info("    %s: $%.4f", provider, cost)
    else:
        log.info("  API usage: no tracking data found (check api-usage.json)")

    log.info("  Log file: %s", LOG_FILE)
    log.info("=" * 70)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-launch-extraction", source="l3-launch-extraction", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
