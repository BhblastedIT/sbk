"""Read-only check of the scheduled jobs: compares the launchd agents loaded on this Mac with the job manifests of
the registry and flags the SBK jobs not in the census and leftovers of older schedulers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .schema import ExternalJob, JobManifest, load_all_jobs, load_external
except ImportError:
    from schema import ExternalJob, JobManifest, load_all_jobs, load_external


KNOWN_LEGACY_FRAGMENTS = (
    "pipeline-schedule.json",
    "event_bus",
    "cascade_monitor",
    "AutoScheduler",
)


def _default_launchctl_lines() -> list[str]:
    ""
    try:
        res = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return res.stdout.splitlines()


def parse_launchctl(lines: list[str]) -> list[str]:
    ""
    labels: list[str] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        label = parts[-1]
        if label.lower() == "label":
            continue
        labels.append(label)
    return labels


@dataclass
class DoctorReport:
    ""

    loaded_labels: list[str] = field(default_factory=list)
    sbk_loaded_uncensused: list[str] = field(default_factory=list)
    external_present: list[str] = field(default_factory=list)
    external_missing: list[str] = field(default_factory=list)
    jobs_scheduled_without_plist: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "loaded_labels": self.loaded_labels,
            "sbk_loaded_uncensused": self.sbk_loaded_uncensused,
            "external_present": self.external_present,
            "external_missing": self.external_missing,
            "jobs_scheduled_without_plist": self.jobs_scheduled_without_plist,
        }


def run_doctor(
    *,
    manifests_dir: Path | None = None,
    launchctl_provider: Callable[[], list[str]] | None = None,
    sbk_prefix: str = "com.sbk.",
) -> DoctorReport:
    ""




    provider = launchctl_provider or _default_launchctl_lines
    labels = parse_launchctl(provider())

    jobs: dict[str, JobManifest] = load_all_jobs(manifests_dir=manifests_dir)
    external: list[ExternalJob] = load_external(manifests_dir=manifests_dir)
    external_ids = {e.id for e in external}

    loaded_set = set(labels)




    sbk_labels = [lbl for lbl in labels if lbl.startswith(sbk_prefix)]
    uncensused = [lbl for lbl in sbk_labels if lbl not in external_ids]

    external_present = sorted(external_ids & loaded_set)
    external_missing = sorted(external_ids - loaded_set)


    scheduled_without_plist = [
        jid
        for jid, m in jobs.items()
        if m.cadence_minutes > 0 and not any(jid in lbl for lbl in labels)
    ]

    ok = not uncensused and not external_missing and not scheduled_without_plist
    return DoctorReport(
        loaded_labels=sorted(labels),
        sbk_loaded_uncensused=sorted(uncensused),
        external_present=external_present,
        external_missing=external_missing,
        jobs_scheduled_without_plist=sorted(scheduled_without_plist),
        ok=ok,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="registry doctor — read-only diagnosis")
    parser.add_argument("--json", action="store_true", help="output in JSON")
    args = parser.parse_args(argv)

    report = run_doctor()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"registry doctor — ok={report.ok}")
        print(f"  plists loaded: {len(report.loaded_labels)}")
        if report.sbk_loaded_uncensused:
            print(f"  SBK not in the census: {report.sbk_loaded_uncensused}")
        if report.external_missing:
            print(f"  external, in the census but NOT loaded: {report.external_missing}")
        if report.external_present:
            print(f"  external, present: {report.external_present}")
        if report.jobs_scheduled_without_plist:
            print(f"  scheduled jobs with no plist: {report.jobs_scheduled_without_plist}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
