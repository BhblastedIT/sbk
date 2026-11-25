#!/usr/bin/env python3
""





























from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("pd-v1-post-launch")

_TOOLS_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import mail_labels  # noqa: E402

# Your mailboxes (emails/accounts.json, email_accounts in sbk.config.json, emails/<label>/).
_MAILBOXES = mail_labels()
_NO_MAILBOX = [sys.executable, "-c", "print('No mailbox configured: nothing to re-download')"]


def _email_redownload(label: str) -> list[str]:
    return [sys.executable, str(_TOOLS_DIR / "email" / "em-l0-download.py"), "--account", label, "--full"]


STEPS = [
    {
        "id": "step1",
        "name": "Install dependencies",
        "cmd": [sys.executable, "-m", "pip", "install", "pdfplumber"],
        "timeout": 120,
        "critical": True,
    },
    {
        "id": "step2",
        "name": "Email re-download (all accounts, new HTML parser)",
        "cmd": _email_redownload(_MAILBOXES[0]) if _MAILBOXES else _NO_MAILBOX,
        "extra_runs": [_email_redownload(label) for label in _MAILBOXES[1:]],
        "timeout": 600,
        "critical": False,
    },
    {
        "id": "step3",
        "name": "Slack re-download (thread replies + files)",
        "cmd": [sys.executable, str(_TOOLS_DIR / "slack" / "sl-l0-download.py"), "--full"],
        "timeout": 1800,
        "critical": False,
    },
    {
        "id": "step4",
        "name": "Calendar re-download (full history + all calendars)",
        "cmd": [
            sys.executable,
            str(_TOOLS_DIR / "calendar" / "ca-l0-download.py"),
            "--full",
            "--all-calendars",
        ],
        "timeout": 600,
        "critical": False,
    },
    {
        "id": "step5",
        "name": "Attio transcript retry stubs",
        "cmd": [
            sys.executable,
            str(_TOOLS_DIR / "attio" / "at-l0-download.py"),
            "--only",
            "transcripts",
            "--retry-stubs",
        ],
        "timeout": 1800,
        "critical": False,
    },
    {
        "id": "step6",
        "name": "LinkedIn thread fetcher (fixed pagination)",
        "cmd": [
            "node",
            str(_TOOLS_DIR / "linkedin" / "scripts" / "fetch-all-threads-complete.js"),
            "--standard",
        ],
        "timeout": 1800,
        "critical": False,
    },
    {
        "id": "step7",
        "name": "Notion re-download (comments)",
        "cmd": [sys.executable, str(_TOOLS_DIR / "notion" / "no-l0-download.py"), "--force"],
        "timeout": 600,
        "critical": False,
    },
    {
        "id": "step8",
        "name": "GDrive L1 re-enrich (PDF text extraction)",
        "cmd": [sys.executable, str(_TOOLS_DIR / "gdrive" / "gd-l1-enrich.py")],
        "timeout": 600,
        "critical": False,
    },
    {
        "id": "step9",
        "name": "Email attachment text extraction",
        "cmd": [sys.executable, str(_TOOLS_DIR / "email" / "em-l2-extract-attachments.py")],
        "timeout": 1200,
        "critical": False,
    },
    {
        "id": "step10",
        "name": "Personio L1 enrichment",
        "cmd": [sys.executable, str(_TOOLS_DIR / "personio" / "pe-l1-enrich.py")],
        "timeout": 120,
        "critical": False,
    },
    {
        "id": "step11",
        "name": "Personio employee change tracker",
        "cmd": [sys.executable, str(_TOOLS_DIR / "personio" / "pe-l1-change-tracker.py")],
        "timeout": 60,
        "critical": False,
    },
    {
        "id": "step12",
        "name": "Personio absences daily aggregation",
        "cmd": [sys.executable, str(_TOOLS_DIR / "personio" / "pe-l2-absences-daily.py")],
        "timeout": 60,
        "critical": False,
    },
    {
        "id": "step13",
        "name": "Cross-source pipeline (entity map, vector DB, graph, decay)",
        "cmd": [
            sys.executable,
            str(_TOOLS_DIR / "cross-source" / "xs-pipeline-run.py"),
            "--ricostruisci",
        ],
        "timeout": 14400,
        "critical": True,
    },
]


def run_step(step: dict) -> bool:
    ""
    step_id = step["id"]
    name = step["name"]
    timeout = step["timeout"]

    log.info(f"\n{'=' * 70}")
    log.info(f"[{step_id}] {name}")
    log.info(f"{'=' * 70}")
    log.info(f"  Command: {' '.join(str(c) for c in step['cmd'])}")
    log.info(f"  Timeout: {timeout}s")

    t0 = time.time()
    try:
        result = subprocess.run(
            step["cmd"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
        )
        elapsed = time.time() - t0

        if result.stdout:
            for line in result.stdout.strip().split("\n")[-10:]:
                log.info(f"  {line}")

        if result.returncode == 0:
            log.info(f"  OK in {elapsed:.1f}s")


            for extra_cmd in step.get("extra_runs", []):
                log.info(f"  Running extra: {' '.join(str(c) for c in extra_cmd[-2:])}")
                try:
                    extra_result = subprocess.run(
                        extra_cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=str(_PROJECT_ROOT),
                    )
                    if extra_result.stdout:
                        last = extra_result.stdout.strip().split("\n")[-3:]
                        for line in last:
                            log.info(f"    {line}")
                    if extra_result.returncode != 0:
                        log.warning(f"    Extra command failed (exit {extra_result.returncode})")
                except Exception as e:
                    log.warning(f"    Extra command error: {e}")

            return True
        else:
            log.error(f"  FAILED (exit {result.returncode}) in {elapsed:.1f}s")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    log.error(f"  stderr: {line}")
            return False

    except subprocess.TimeoutExpired:
        log.error(f"  TIMEOUT after {timeout}s")
        return False
    except FileNotFoundError as e:
        log.error(f"  Command not found: {e}")
        return False
    except Exception as e:
        log.error(f"  ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Pipeline Depth V1 — Post-Launch Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without running")
    parser.add_argument("--from", dest="from_step", help="Resume from step (e.g. step5)")
    parser.add_argument("--only", dest="only_step", help="Run single step (e.g. step3)")
    parser.add_argument(
        "--skip-critical-check", action="store_true", help="Continue even if critical steps fail"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=" * 70)
    log.info("PIPELINE DEPTH V1 — POST-LAUNCH ORCHESTRATOR")
    log.info("=" * 70)
    log.info(f"  Steps: {len(STEPS)}")
    log.info(f"  Mode: {'dry-run' if args.dry_run else 'execute'}")
    if args.from_step:
        log.info(f"  Resume from: {args.from_step}")
    if args.only_step:
        log.info(f"  Only step: {args.only_step}")


    steps_to_run = STEPS
    if args.only_step:
        steps_to_run = [s for s in STEPS if s["id"] == args.only_step]
        if not steps_to_run:
            log.error(f"Step {args.only_step} not found. Valid: {[s['id'] for s in STEPS]}")
            sys.exit(1)
    elif args.from_step:
        found = False
        filtered = []
        for s in STEPS:
            if s["id"] == args.from_step:
                found = True
            if found:
                filtered.append(s)
        if not filtered:
            log.error(f"Step {args.from_step} not found. Valid: {[s['id'] for s in STEPS]}")
            sys.exit(1)
        steps_to_run = filtered

    if args.dry_run:
        log.info("\n--- DRY RUN PLAN ---")
        for i, step in enumerate(steps_to_run, 1):
            critical = " [CRITICAL]" if step.get("critical") else ""
            log.info(f"  {i}. [{step['id']}] {step['name']}{critical}")
            log.info(f"     cmd: {' '.join(str(c) for c in step['cmd'][:4])}...")
            log.info(f"     timeout: {step['timeout']}s")
            for extra in step.get("extra_runs", []):
                log.info(f"     + {' '.join(str(c) for c in extra[-2:])}")
        return


    t_total = time.time()
    results = {}

    for step in steps_to_run:
        ok = run_step(step)
        results[step["id"]] = ok

        if not ok and step.get("critical") and not args.skip_critical_check:
            log.error(f"\nCRITICAL step {step['id']} failed. Stopping.")
            log.error("Use --skip-critical-check to continue anyway.")
            break


    total_elapsed = time.time() - t_total
    log.info(f"\n{'=' * 70}")
    log.info("POST-LAUNCH SUMMARY")
    log.info(f"{'=' * 70}")
    ok_count = sum(1 for v in results.values() if v)
    fail_count = sum(1 for v in results.values() if not v)
    log.info(f"  Total: {len(results)} steps ({ok_count} OK, {fail_count} failed)")
    log.info(f"  Time: {total_elapsed:.0f}s ({total_elapsed / 60:.1f} min)")
    for step_id, ok in results.items():
        status = "OK" if ok else "FAILED"
        log.info(f"  [{step_id}] {status}")

    if fail_count > 0:
        log.warning(f"\n  {fail_count} step(s) failed. Review logs above.")
        log.info(f"  To resume: python3 {__file__} --from <failed_step>")


if __name__ == "__main__":
    main()
