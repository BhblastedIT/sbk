#!/usr/bin/env python3
"""Read-only probe of the Gemini meeting notes on Drive: lists them for one account and reports which ones the Drive
download misses and why.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import sbk_config

log = logging.getLogger("sbk.gd-gemini-probe")





DEFAULT_GEMINI_QUERY = (
    "trashed = false and mimeType = 'application/vnd.google-apps.document' "
    "and name contains 'Gemini'"
)




DOWNLOADER_QUERIES_NOTE = (
    "gd-l0-download.py filters by modifiedTime/owner/sharedWithMe: there is no query "
    "dedicated to Gemini notes. Old or read-only notes may not be picked up."
)


@dataclass
class ProbeReport:
    ""

    query: str
    drive_count: int = 0
    local_count: int = 0
    matched_count: int = 0
    missing_on_local: list[dict] = field(default_factory=list)
    account: str = ""
    drive_available: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return len(self.missing_on_local)

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "query": self.query,
            "drive_available": self.drive_available,
            "drive_count": self.drive_count,
            "local_count": self.local_count,
            "matched_count": self.matched_count,
            "missing_count": self.missing_count,
            "missing_on_local": self.missing_on_local,
            "notes": self.notes,
        }


def _file_key(meta: dict) -> str:
    ""



    fid = meta.get("id")
    if fid:
        return str(fid)
    name = meta.get("name", "")
    return f"name:{name}"


def build_probe_report(
    drive_lister: Callable[[str], list[dict]],
    local_ids: set[str],
    *,
    query: str = DEFAULT_GEMINI_QUERY,
    account: str = "",
) -> ProbeReport:
    ""








    report = ProbeReport(query=query, account=account)
    try:
        drive_files = list(drive_lister(query))
    except Exception as exc:  # noqa: BLE001 — the probe must never crash
        report.drive_available = False
        report.notes.append(f"Drive listing unavailable: {type(exc).__name__}: {exc}")
        return report

    report.drive_count = len(drive_files)
    report.local_count = len(local_ids)

    for meta in drive_files:
        key = _file_key(meta)
        if key in local_ids:
            report.matched_count += 1
        else:
            report.missing_on_local.append(
                {
                    "id": meta.get("id", ""),
                    "name": meta.get("name", ""),
                    "modifiedTime": meta.get("modifiedTime", ""),
                    "webViewLink": meta.get("webViewLink", ""),
                }
            )

    if report.missing_count > 0:
        report.notes.append(f"{report.missing_count} Gemini notes on Drive are NOT present locally.")
        report.notes.append(DOWNLOADER_QUERIES_NOTE)
    return report


def propose_fix(report: ProbeReport) -> str | None:
    ""



    if report.drive_available and report.missing_count == 0:
        return None
    return (
        "PROPOSAL (NOT applied to gd-l0-download.py):\n"
        "  Add to gd-l0-download.py a mode/query dedicated to Gemini notes, e.g.:\n"
        f'      query = "{report.query}"\n'
        "  run independently of the modifiedTime/owner filters, so that old or\n"
        "  share-only Gemini notes are downloaded too.\n"
        "  NB: the 'name contains Gemini' heuristic is volatile — verify live how\n"
        "  Gemini notes are actually represented on Drive before wiring it in."
    )


def render_report(report: ProbeReport) -> str:
    ""
    lines: list[str] = []
    lines.append("# Gemini notes probe: Drive vs local (READ-ONLY)")
    lines.append("")
    lines.append(f"- Account: `{report.account or '(not specified)'}`")
    lines.append(f"- Heuristic query: `{report.query}`")
    lines.append(f"- Drive reachable: {report.drive_available}")
    lines.append(f"- Notes on Drive: {report.drive_count}")
    lines.append(f"- Present locally (matched by id): {report.matched_count}")
    lines.append(f"- Local index total: {report.local_count}")
    lines.append(f"- Missing locally: {report.missing_count}")
    lines.append("")
    if report.notes:
        lines.append("## Notes")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")
    if report.missing_on_local:
        lines.append("## Gemini notes on Drive not present locally")
        for m in report.missing_on_local[:50]:
            name = m.get("name", "")
            mtime = (m.get("modifiedTime", "") or "")[:10]
            lines.append(f"- {name} (id={m.get('id', '')}, modified {mtime})")
        if report.missing_count > 50:
            lines.append(f"- ... and {report.missing_count - 50} more")
        lines.append("")
    fix = propose_fix(report)
    if fix:
        lines.append("## Proposed fix")
        lines.append("```")
        lines.append(fix)
        lines.append("```")
        lines.append("")
    lines.append(
        "_Read-only report: no file downloaded, no change to "
        "gd-l0-download.py. Drive state is volatile: re-verify before use._"
    )
    return "\n".join(lines)





def load_local_ids(root: Path | None = None) -> set[str]:
    ""




    base = Path(root) if root is not None else sbk_config.DATA_ROOT
    index_file = base / "gdrive" / "gdrive-index.json"
    if not index_file.exists():
        return set()
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out: set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                out.add(str(item["id"]))
    return out





def _build_drive_lister(account: str) -> Callable[[str], list[dict]]:
    ""




    import importlib.util

    dl_path = Path(__file__).resolve().parent / "gd-l0-download.py"
    spec = importlib.util.spec_from_file_location("gd_l0_download", dl_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    service = mod.build_service(account)
    if service is None:
        raise RuntimeError(f"No Drive credentials for account '{account}'")

    def _lister(query: str) -> list[dict]:
        return mod.list_files(service, query)

    return _lister


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only probe of Gemini notes on Drive")
    parser.add_argument("--account", default="personal", help="Drive account (default personal)")
    parser.add_argument("--query", default=DEFAULT_GEMINI_QUERY, help="Heuristic Drive query")
    parser.add_argument("--out", default=None, help="Write the report here (default stdout)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    local_ids = load_local_ids()
    try:
        lister = _build_drive_lister(args.account)
    except Exception as exc:  # noqa: BLE001 — probe stays robust without credentials
        report = ProbeReport(query=args.query, account=args.account, drive_available=False)
        report.local_count = len(local_ids)
        report.notes.append(f"Drive service could not be built: {type(exc).__name__}: {exc}")
    else:
        report = build_probe_report(lister, local_ids, query=args.query, account=args.account)

    text = render_report(report)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        log.info("Report written: %s", out_path)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
