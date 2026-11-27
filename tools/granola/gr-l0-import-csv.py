#!/usr/bin/env python3
"""Granola L0, free-plan route: import the CSV export of your own notes from a local file.

Granola emails the export after Settings -> Profile -> Generate CSV (Basic and Business
plans; once every 24 hours; your own notes only, full history, notes with a summary
only): https://docs.granola.ai/help-center/sharing/exporting-notes

Granola documents what the CSV holds (title, note summary, transcript, "other basic
details") but not its column names. This importer therefore finds the columns by
header name, with the usual spellings below, and prints the headers it found. When a
header of your file has another name, map it in sbk.config.json:

    "granola": {"csv_columns": {"title": "<header>", "date": "<header>", ...}}

Fields: id, title, date, summary, transcript, attendees, url. Only `title` is required.
Attendees, when the file has such a column, are read as "Name <email>" items separated
by commas, semicolons or new lines.

Each row becomes raw/notes/<id>.json in the same shape as the API download (so
gr-l1-enrich.py reads both). A note already downloaded through the API is never
replaced by its CSV row. The file you pass is only read; nothing goes to the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr_api  # noqa: E402

# Header spellings tried for each field, compared without case, spaces, '_' and '-'.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "id": ("id", "note id", "noteid", "document id"),
    "title": ("title", "note title", "meeting title", "name", "meeting"),
    "date": (
        "date",
        "created at",
        "created",
        "meeting date",
        "meeting at",
        "start time",
        "start",
        "scheduled start time",
    ),
    "summary": (
        "summary",
        "note summary",
        "summary markdown",
        "summary text",
        "notes",
        "enhanced notes",
        "ai notes",
    ),
    "transcript": ("transcript", "full transcript", "meeting transcript"),
    "attendees": ("attendees", "participants", "invitees", "people", "attendee emails"),
    "url": ("url", "link", "web url", "note url", "granola url"),
}
FIELDS = tuple(SYNONYMS)
_EMAIL = re.compile(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+")


def _norm(h: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(h or "").strip().lower().lstrip("﻿"))


def map_columns(headers: list[str], overrides: dict | None = None) -> dict[str, str]:
    """field -> header of this file. Overrides from granola.csv_columns win."""
    by_norm = {_norm(h): h for h in headers}
    out: dict[str, str] = {}
    for field, header in (overrides or {}).items():
        if field in SYNONYMS and str(header) in headers:
            out[field] = str(header)
    for field, names in SYNONYMS.items():
        if field in out:
            continue
        for name in names:
            if _norm(name) in by_norm:
                out[field] = by_norm[_norm(name)]
                break
    return out


def parse_attendees(cell: str) -> list[dict]:
    """'Ana Demo <ana@x.example>, bo@y.example' -> [{'name','email'}, ...]."""
    people: list[dict] = []
    for part in re.split(r"[;\n]|,(?![^<]*>)", str(cell or "")):
        part = part.strip().strip('"').strip()
        if not part:
            continue
        m = _EMAIL.search(part)
        email = m.group(0).lower() if m else ""
        name = part
        if email:
            name = re.sub(r"<?\s*" + re.escape(m.group(0)) + r"\s*>?", "", part).strip(" ()<>\"'")
        people.append({"name": name or None, "email": email})
    return people


def parse_date(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    out = gr_api.iso(v)
    if out != v:
        return out
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return gr_api.iso(datetime.strptime(v, fmt).replace(tzinfo=UTC).isoformat())
        except ValueError:
            continue
    return ""


def row_to_note(row: dict, cols: dict[str, str]) -> dict | None:
    def cell(field: str) -> str:
        h = cols.get(field)
        return str(row.get(h) or "").strip() if h else ""

    title = cell("title")
    summary = cell("summary")
    transcript = cell("transcript")
    if not (title or summary or transcript):
        return None
    when = parse_date(cell("date"))
    raw_id = cell("id")
    if raw_id:
        nid = raw_id
    else:
        # Title + date when the date is known, so a later export of the same note (with a
        # regenerated summary) lands on the same file instead of a duplicate.
        basis = f"{title}\x1f{when}" if when else f"{title}\x1f\x1f{summary[:200]}"
        digest = hashlib.sha1(basis.encode()).hexdigest()
        nid = f"csv_{digest[:16]}"
    return {
        "id": nid,
        "object": "note",
        "title": title or None,
        "owner": None,
        "created_at": when,
        "updated_at": when,
        "deleted_at": None,
        "web_url": cell("url"),
        "calendar_event": None,
        "attendees": parse_attendees(cell("attendees")),
        "summary_text": summary,
        "summary_markdown": summary,
        "private_notes_text": None,
        "private_notes_markdown": None,
        "transcript": None,
        "transcript_text": transcript,
        "_origin": "csv",
    }


def run_import(path: Path, force: bool = False) -> dict:
    csv.field_size_limit(sys.maxsize)  # transcripts make very long cells
    started = datetime.now(UTC)
    stats = {
        "rows": 0,
        "imported": 0,
        "kept_api_version": 0,
        "empty_rows": 0,
        "with_transcript": 0,
        "with_attendees": 0,
    }
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        cols = map_columns(headers, gr_api.cfg("csv_columns", {}) or {})
        if "title" not in cols:
            raise gr_api.GranolaError(
                "no title column found in the CSV (headers: "
                + ", ".join(h for h in headers[:15] if h)
                + "); map it in sbk.config.json as granola.csv_columns.title"
            )
        for row in reader:
            stats["rows"] += 1
            note = row_to_note(row, cols)
            if note is None:
                stats["empty_rows"] += 1
                continue
            out = gr_api.notes_dir() / f"{gr_api.safe_name(note['id'])}.json"
            old = gr_api.read_json(out, {}) if out.exists() else {}
            if old and old.get("_origin") == "api" and not force:
                stats["kept_api_version"] += 1
                continue
            note["_fetched_at"] = datetime.now(UTC).isoformat()
            gr_api.write_json(out, note)
            stats["imported"] += 1
            stats["with_transcript"] += bool(note["transcript_text"])
            stats["with_attendees"] += bool(note["attendees"])
    summary = {
        "source": gr_api.SOURCE,
        "route": "csv",
        "file": path.name,
        "columns_found": cols,
        "columns_missing": [f for f in FIELDS if f not in cols],
        **stats,
        "complete": True,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    gr_api.write_json(gr_api.summary_path(), summary)
    return summary


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Import the CSV export of your own Granola notes (Settings -> Profile -> "
        "Generate CSV, free and paid plans). Reads a local file only."
    )
    ap.add_argument("csv_file", nargs="?", help="the CSV file Granola emailed to you")
    ap.add_argument(
        "--force", action="store_true", help="also replace notes downloaded through the API"
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.csv_file:
        print(
            "Granola: give the CSV file Granola emailed you (Settings -> Profile -> Generate CSV): "
            "uv run python tools/granola/gr-l0-import-csv.py <file.csv>",
            file=sys.stderr,
        )
        return 1
    path = Path(args.csv_file).expanduser()
    if not path.is_file():
        print(f"Granola: no such file: {path}", file=sys.stderr)
        return 1
    try:
        s = run_import(path, force=args.force)
    except (gr_api.GranolaError, csv.Error, UnicodeDecodeError) as e:
        print(f"Granola: {e}", file=sys.stderr)
        return 1
    print(
        f"Granola CSV: {s['rows']} rows, {s['imported']} notes imported "
        f"({s['with_transcript']} with transcript, {s['with_attendees']} with attendees), "
        f"{s['kept_api_version']} kept from the API; columns found: "
        + ", ".join(f"{k}={v!r}" for k, v in s["columns_found"].items())
        + (f"; not found: {', '.join(s['columns_missing'])}" if s["columns_missing"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
