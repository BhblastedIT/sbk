#!/usr/bin/env python3
"""Fathom L0: download your recorded meetings with invitees, summary, transcript, action items.

Reads with your own Fathom API key (header X-Api-Key), GET calls only, one endpoint:

  GET https://api.fathom.ai/external/v1/meetings
      ?created_after=...&recorded_by[]=<your email>...
      &include_transcript=true&include_summary=true&include_action_items=true

By default only the meetings you recorded (`recorded_by[]` = fathom.recorded_by, else
own_emails of sbk.config.json). With --all-visible, or when no email of yours is known, every
meeting your key can see: the ones you recorded and the ones shared with you or your team.

Writes under <data root>/fathom/:
  raw/meetings/<recording_id>.json   one file per meeting, rewritten when read again
  raw/state.json                     the incremental watermark
  download-summary.json              what this run did

Incremental: the next run asks for meetings created after the last completed run minus
`fathom.overlap_days` (default 14), so late summaries and action items ticked off in Fathom
are read again. The first run goes back `fathom.history_days` (default 365); --full reads
everything. A run that stops (rate limit, network) keeps what it wrote and does not move
the watermark, so nothing is skipped. The watermark also stays put after a lighter run
(--no-transcript / --no-summary) and after a --since later than it, and it is ignored when
the recorded_by filter changed or the saved run asked for less than this one: then the run
goes back fathom.history_days, as a first run does.

    uv run python tools/fathom/fa-l0-download.py --dry-run   # checks the key, writes nothing
    uv run python tools/fathom/fa-l0-download.py
    uv run python tools/fathom/fa-l0-download.py --full

Setup: docs/CONNECTING.md#fathom. Then tools/fathom/fa-l1-enrich.py.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tools"))


def _date_arg(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date YYYY-MM-DD: {value!r}") from None
    return value


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your Fathom meetings: invitees, summary, transcript and action "
        "items (your personal API key, read-only; see docs/CONNECTING.md#fathom)."
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="check the key with one light call; write nothing"
    )
    ap.add_argument(
        "--full", action="store_true", help="ignore the watermark and read every meeting"
    )
    ap.add_argument(
        "--since",
        type=_date_arg,
        help="start date YYYY-MM-DD (overrides the saved watermark for this run)",
    )
    ap.add_argument(
        "--days",
        type=int,
        default=None,
        help="first run: how many days back (default fathom.history_days or 365)",
    )
    ap.add_argument(
        "--all-visible",
        action="store_true",
        help="every meeting your key can see (also those shared with you or your team), "
        "not only the ones you recorded",
    )
    ap.add_argument("--no-transcript", action="store_true", help="do not ask for transcripts")
    ap.add_argument("--no-summary", action="store_true", help="do not ask for summaries")
    return ap.parse_args(argv)


FULL_INCLUDED = {"transcript": True, "summary": True}


def _included(args) -> dict:
    return {"transcript": not args.no_transcript, "summary": not args.no_summary}


def _covers(prev: dict, cur: dict) -> bool:
    """True when every part asked now was also asked by the run that set the watermark."""
    return all(prev.get(k, True) or not v for k, v in cur.items())


def _parse_zulu(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def watermark_usable(state: dict, mine: list[str], included: dict) -> bool:
    """The saved watermark holds for this run only with the same recorded_by filter and when
    that run asked for at least the parts asked now (a light run never stands in for transcripts).
    """
    if not _parse_zulu(state.get("watermark") or ""):
        return False
    if sorted(state.get("recorded_by") or []) != sorted(mine):
        return False
    return _covers(state.get("included") or FULL_INCLUDED, included)


def _created_after(args, state: dict, now: datetime, usable: bool = True) -> str:
    import fa_api

    if args.full:
        return ""
    if args.since:
        d = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)
        return fa_api.zulu(d)
    if usable and state.get("watermark"):
        overlap = fa_api.cfg_int("overlap_days", fa_api.DEFAULT_OVERLAP_DAYS)
        w = _parse_zulu(state["watermark"])
        return fa_api.zulu(w - timedelta(days=overlap))
    days = (
        args.days
        if args.days is not None
        else fa_api.cfg_int("history_days", fa_api.DEFAULT_HISTORY_DAYS)
    )
    return fa_api.zulu(now - timedelta(days=days))


def next_watermark(state: dict, mine: list[str], included: dict, created_after: str, now):
    """(watermark, included) to save after a COMPLETE run, without opening a gap.

    - same filter and a lighter run than the saved one: keep the saved watermark, so the next
      full run still reads the transcripts and summaries this run left out;
    - same filter and the run started after the saved watermark (--since later than it): keep
      it, the days in between were never read;
    - otherwise the run covered everything up to now: move to now.
    """
    import fa_api

    prev = _parse_zulu(state.get("watermark") or "")
    same_filter = sorted(state.get("recorded_by") or []) == sorted(mine)
    prev_inc = state.get("included") or FULL_INCLUDED
    if prev and same_filter:
        lighter = _covers(prev_inc, included) and prev_inc != included
        start = _parse_zulu(created_after) if created_after else None
        if lighter or (start and start > prev):
            return state["watermark"], prev_inc
    return fa_api.zulu(now), included


def build_params(args, created_after: str, recorded_by: list[str]) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = []
    if created_after:
        p.append(("created_after", created_after))
    for e in recorded_by:
        p.append(("recorded_by[]", e))
    p.append(("include_action_items", "true"))
    if not args.no_summary:
        p.append(("include_summary", "true"))
    if not args.no_transcript:
        p.append(("include_transcript", "true"))
    return p


def run_download(client, args, now: datetime | None = None) -> dict:
    import fa_api

    now = now or datetime.now(UTC)
    state = fa_api.read_json(fa_api.state_path(), {}) or {}
    if not isinstance(state, dict):
        state = {}
    mine = [] if args.all_visible or fa_api.cfg("all_visible", False) else fa_api.my_emails()
    included = _included(args)
    usable = watermark_usable(state, mine, included)
    created_after = _created_after(args, state, now, usable)
    heavy = not (args.no_summary and args.no_transcript)
    params = build_params(args, created_after, mine)

    stats = {
        "source": fa_api.SOURCE,
        "filter": f"recorded_by {len(mine)} email(s)"
        if mine
        else "none: every meeting your key can see",
        "created_after": created_after or "(everything)",
        "watermark_used": bool(usable and not args.full and not args.since),
        "meetings": 0,
        "new_meetings": 0,
        "with_transcript": 0,
        "with_summary": 0,
        "action_items": 0,
        "complete": False,
        "stopped": "",
    }
    seen = dict(state.get("seen") or {})
    try:
        for m in client.paged("/meetings", params, heavy=heavy):
            rid = fa_api.safe_id(m.get("recording_id"))
            if not rid:  # missing, or not usable as a file name
                stats["skipped_bad_id"] = stats.get("skipped_bad_id", 0) + 1
                continue
            out = fa_api.meetings_dir() / f"{rid}.json"
            if not out.exists():
                stats["new_meetings"] += 1
            rec = dict(m)
            rec["_fetched_at"] = now.isoformat()
            rec["_included"] = {
                "transcript": not args.no_transcript,
                "summary": not args.no_summary,
                "action_items": True,
            }
            # A run without transcript or summary keeps the ones already on disk.
            old = fa_api.read_json(out, {}) or {}
            for key, flag in (
                ("transcript", args.no_transcript),
                ("default_summary", args.no_summary),
            ):
                if flag and old.get(key) and not rec.get(key):
                    rec[key] = old[key]
            fa_api.write_json(out, rec)
            stats["meetings"] += 1
            stats["with_transcript"] += bool(rec.get("transcript"))
            stats["with_summary"] += bool(
                (rec.get("default_summary") or {}).get("markdown_formatted")
            )
            stats["action_items"] += len(rec.get("action_items") or [])
            seen[str(rid)] = m.get("created_at") or ""
        stats["complete"] = True
    except fa_api.FathomError as e:
        msg = str(e)
        stats["stopped"] = msg if msg.startswith("fathom:") else f"fathom: {msg}"

    if stats["complete"]:
        watermark, wm_included = next_watermark(state, mine, included, created_after, now)
        wm_filter = mine
    else:  # a run that stopped moves nothing
        watermark = state.get("watermark", "")
        wm_included = state.get("included") or FULL_INCLUDED
        wm_filter = state.get("recorded_by") or []
    new_state = {
        "watermark": watermark,
        "included": wm_included,
        "last_run": now.isoformat(),
        "recorded_by": wm_filter,
        "seen": seen,
    }
    fa_api.write_json(fa_api.state_path(), new_state)
    stats.update(
        requests=client.requests,
        rate_limited=client.rate_limited,
        completed_at=datetime.now(UTC).isoformat(),
    )
    fa_api.write_json(fa_api.summary_path(), stats)
    return stats


def main(argv=None, opener=None, sleep=None) -> int:
    args = parse_args(argv)
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass
    import fa_api

    import sbk_config

    try:
        key, where = fa_api.resolve_key()
    except fa_api.NoKey as e:
        print(str(e), file=sys.stderr)
        return 1
    client = fa_api.FathomClient(key, opener=opener, sleep=sleep)

    if args.dry_run:
        try:
            data = client.get("/meetings", [("include_action_items", "false")]) or {}
        except fa_api.ApiHTTPError as e:
            print(f"fathom: {e}", file=sys.stderr)
            return 1
        except fa_api.FathomError as e:
            print(str(e), file=sys.stderr)
            return 1
        items = data.get("items") or []
        print(
            f"fathom: key from {where} works; first page has {len(items)} meeting(s)"
            + (
                ""
                if fa_api.my_emails()
                else "; no email of yours known (fathom.recorded_by or own_emails), "
                "the download will read every meeting your key can see"
            )
            + "; nothing written (dry run)"
        )
        return 0

    try:
        s = run_download(client, args)
    except fa_api.ApiHTTPError as e:
        print(f"fathom: {e}", file=sys.stderr)
        return 1
    except fa_api.FathomError as e:
        print(str(e), file=sys.stderr)
        return 1
    if s["stopped"] and not s["meetings"]:
        print(s["stopped"], file=sys.stderr)
        return 1
    sbk_config.mark_last_run(fa_api.SOURCE)
    print(
        f"fathom: {s['meetings']} meetings ({s['new_meetings']} new, {s['with_transcript']} with "
        f"transcript, {s['with_summary']} with summary), {s['action_items']} action items; "
        f"filter {s['filter']}; from {s['created_after']}"
        + (f"; stopped: {s['stopped']}" if s["stopped"] else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
