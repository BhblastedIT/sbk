#!/usr/bin/env python3
"""Granola L0: download your own meeting notes, attendees and transcripts through the API.

Needs a personal Granola API key (Business or Enterprise plan; on the free Basic plan use
gr-l0-import-csv.py with the CSV export instead). Read-only, GET only:
- GET /v1/notes?created_after=...|updated_after=...   the notes the key can read
- GET /v1/notes/{id}?include=transcript               summary, attendees, calendar event,
                                                      private notes, transcript
- GET /v1/notes/{id}/transcript                       only when the transcript is too large
                                                      to come inline (413 TRANSCRIPT_TOO_LARGE)

Writes under <data root>/granola/:
  raw/notes/<note id>.json, raw/state.json (incremental), download-summary.json

Incremental: the first run reads the notes created in the last `granola.history_days`
days (or everything with --all). Later runs ask for the notes updated after the start of
the last complete run minus `granola.overlap_days`, so a note whose summary or transcript
changed is fetched again. A note whose `updated_at` is the one already on disk is not
fetched again unless --force. A run with a note Granola kept failing on or refused does
not move the saved point, so nothing is skipped for good. --all lists every note on any
run; --since lists from a date of your choice and moves the saved point only when that
window holds the incremental one; --limit never moves it.

Setup: docs/CONNECTING.md#granola
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr_api  # noqa: E402
from gr_api import ApiHTTPError, AuthError, GranolaError  # noqa: E402

DEFAULT_HISTORY_DAYS = 365
DEFAULT_OVERLAP_DAYS = 3


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your own Granola meeting notes, attendees and transcripts with "
        "a personal API key (Business plan; see docs/CONNECTING.md#granola)."
    )
    ap.add_argument(
        "--since",
        help="notes updated after YYYY-MM-DD (this run only; the saved point moves only when "
        "this window holds the incremental one)",
    )
    ap.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"first run: how many days back (default granola.history_days or "
        f"{DEFAULT_HISTORY_DAYS})",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="list every note the key can read (any run; notes already on disk and unchanged "
        "are skipped)",
    )
    ap.add_argument("--force", action="store_true", help="fetch again notes already on disk")
    ap.add_argument("--no-transcripts", action="store_true", help="do not ask for transcripts")
    ap.add_argument("--limit", type=int, default=0, help="stop after N notes (a quick test)")
    return ap.parse_args(argv)


def connect(opener=None, sleep=None) -> gr_api.GranolaClient:
    key, _where = gr_api.resolve_api_key()
    if not key:
        raise GranolaError(
            f"no API key found (Keychain {gr_api.KEYCHAIN_SERVICE}/{gr_api.KEYCHAIN_ACCOUNT} or "
            f"env {gr_api.ENV_API_KEY}); {gr_api.SETUP_HINT}. On the free plan use "
            "gr-l0-import-csv.py"
        )
    return gr_api.GranolaClient(key, opener=opener, sleep=sleep)


def _parse_since(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise GranolaError(f"--since {value!r} is not a date (use YYYY-MM-DD)") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _filters(args, state: dict, now: datetime) -> tuple[dict, str, bool]:
    """(list filters, human description of the window, whether a clean run may move the point).

    --all always lists every note (also after the first run: a full re-check, unchanged notes
    are skipped). --since moves the saved point only when its window holds the incremental
    one, so a narrow manual run never makes the next run skip notes.
    """
    if args.all:
        return {}, "every note", True
    incremental = None
    if state.get("last_complete_start"):
        overlap = int(gr_api.cfg("overlap_days", DEFAULT_OVERLAP_DAYS))
        start = datetime.fromisoformat(state["last_complete_start"].replace("Z", "+00:00"))
        incremental = (start - timedelta(days=overlap)).astimezone(UTC)
    if args.since:
        since = _parse_since(args.since)
        covers = incremental is not None and since <= incremental
        return {"updated_after": args.since}, f"updated after {args.since}", covers
    if incremental is not None:
        stamp = incremental.isoformat().replace("+00:00", "Z")
        return {"updated_after": stamp}, f"updated after {stamp}", True
    days = (
        args.days
        if args.days is not None
        else int(gr_api.cfg("history_days", DEFAULT_HISTORY_DAYS))
    )
    since = (now - timedelta(days=days)).date().isoformat()
    return {"created_after": since}, f"created after {since}", True


def _fetch_note(client, nid: str, want_transcript: bool, stats: dict) -> dict | None:
    """The full note, transcript included when possible; None when Granola refuses it."""
    try:
        note = client.get_note(nid, transcript=want_transcript)
    except ApiHTTPError as e:
        if e.status == 413 or e.code == "TRANSCRIPT_TOO_LARGE":
            note = client.get_note(nid, transcript=False)
            try:
                note["transcript"] = client.get_transcript(nid)
                note["_transcript_paged"] = True
                stats["transcripts_paged"] += 1
            except ApiHTTPError as e2:
                note["transcript"] = None
                stats["transcripts_unavailable"] += 1
                stats["error_samples"].append(f"transcript {nid}: HTTP {e2.status} {e2.code}")
            return note
        if e.status == 403 and want_transcript:
            # A workspace admin turned transcripts off over the API: keep the note without it.
            stats["transcripts_unavailable"] += 1
            return client.get_note(nid, transcript=False)
        if e.status == 404:
            # The key cannot read it any more, or it has no generated summary (yet).
            stats["not_found"] += 1
            return None
        raise
    return note


def run_download(client: gr_api.GranolaClient, args, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    started = datetime.now(UTC)
    state = gr_api.read_json(gr_api.state_path(), {}) or {}
    filters, window, moves_point = _filters(args, state, now)
    seen: dict = dict(state.get("notes") or {})
    stats = {
        "listed": 0,
        "downloaded": 0,
        "unchanged": 0,
        "with_transcript": 0,
        "transcripts_paged": 0,
        "transcripts_unavailable": 0,
        "deleted": 0,
        "not_found": 0,
        "errors": 0,
        "retry_next_run": 0,
        "error_samples": [],
    }
    complete = True
    for summary in client.list_notes(**filters):
        nid = str(summary.get("id") or "")
        if not nid:
            continue
        stats["listed"] += 1
        updated = str(summary.get("updated_at") or "")
        out = gr_api.notes_dir() / f"{gr_api.safe_name(nid)}.json"
        if summary.get("deleted_at"):
            stats["deleted"] += 1
        if not args.force and out.exists() and updated and seen.get(nid) == updated:
            stats["unchanged"] += 1
            continue
        try:
            note = _fetch_note(client, nid, not args.no_transcripts, stats)
        except ApiHTTPError as e:
            # Any other refusal of one note (400, 403 without a fatal code, ...): the note is
            # not on disk, so the saved point stays where it is and the next run asks again.
            stats["errors"] += 1
            stats["retry_next_run"] += 1
            stats["error_samples"].append(f"note {nid}: HTTP {e.status} {e.code}")
            continue
        except AuthError:
            raise
        except GranolaError as e:
            stats["errors"] += 1
            stats["retry_next_run"] += 1
            stats["error_samples"].append(f"note {nid}: {e}")
            continue
        if note is None:
            continue
        note = dict(note)
        if summary.get("deleted_at") and not note.get("deleted_at"):
            note["deleted_at"] = summary["deleted_at"]
        note["_fetched_at"] = datetime.now(UTC).isoformat()
        note["_origin"] = "api"
        gr_api.write_json(out, note)
        seen[nid] = updated or str(note.get("updated_at") or "")
        stats["downloaded"] += 1
        stats["with_transcript"] += bool(note.get("transcript"))
        if args.limit and stats["downloaded"] >= args.limit:
            complete = False  # a partial test run must not move the saved point
            break

    if stats["retry_next_run"]:
        complete = False
    new_state = {
        "last_complete_start": started.isoformat().replace("+00:00", "Z")
        if complete and moves_point
        else state.get("last_complete_start", ""),
        "last_run": datetime.now(UTC).isoformat(),
        "notes": seen,
    }
    gr_api.write_json(gr_api.state_path(), new_state)
    stats["error_samples"] = stats["error_samples"][:20]
    summary_out = {
        "source": gr_api.SOURCE,
        "route": "api",
        **stats,
        "window": window,
        "complete": complete,
        "saved_point_moved": complete and moves_point,
        "requests": client.requests,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    gr_api.write_json(gr_api.summary_path(), summary_out)
    return summary_out


def cli(argv=None, opener=None, sleep=None) -> int:
    args = parse_args(argv)
    try:
        if args.since:
            _parse_since(args.since)  # a bad date is one line, before the pipeline step
        client = connect(opener=opener, sleep=sleep)
    except GranolaError as e:
        print(f"Granola: {e}", file=sys.stderr)
        return 1

    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l0-granola-download", source=gr_api.SOURCE, stage="l0")
    def _run():
        try:
            return run_download(client, args)
        except GranolaError as e:
            # One clear line instead of a traceback; the step is still recorded as failed.
            print(f"Granola: {e}", file=sys.stderr)
            raise SystemExit(1) from None

    try:
        s = _run()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    print(
        f"Granola: {s['listed']} notes listed, {s['downloaded']} downloaded "
        f"({s['with_transcript']} with transcript), {s['unchanged']} unchanged, "
        f"{s['errors']} errors; {s['window']}"
        + (f"; {s['retry_next_run']} notes asked again next run" if s["retry_next_run"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli())
