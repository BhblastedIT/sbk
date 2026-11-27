#!/usr/bin/env python3
"""Fireflies L0: download your own meeting transcripts, participants, summaries, action items.

Reads, with the API key of your own Fireflies account (GraphQL queries only):
- user                          you (the owner of the key): id, email, name
- contacts                      people who were in meetings with you (optional)
- transcripts(user_id: <you>)   meetings where you are organizer or participant, in windows
                                of 30 days, 50 per page; with --only-organized
                                transcripts(mine: true), the meetings you organized
- transcript(id) { sentences }  the full transcript of each new meeting, once (optional)

Writes under <data root>/fireflies/:
  raw/me.json, raw/contacts.json, raw/meetings/<id>.json, raw/transcripts/<id>.json,
  raw/state.json (incremental), download-summary.json

Incremental: the next run lists from the last completed run minus `fireflies.overlap_days`
(summaries and action items are written by Fireflies after the meeting). A meeting whose
summary was still processing is asked again by id on the next runs. A transcript text that
could not be fetched (request cap, daily quota, error) stays in a pending list and is asked
first next time. A run stopped by the quota does not move the saved date.

Setup: docs/CONNECTING.md#fireflies
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ff_api  # noqa: E402
from ff_api import AuthError, DailyLimitReached, FirefliesError, GraphQLError  # noqa: E402

DEFAULT_HISTORY_DAYS = 90
DEFAULT_OVERLAP_DAYS = 3
PENDING_SUMMARY_MAX_DAYS = 14  # stop asking again for a summary Fireflies never finished
# summary_status values worth asking again: "processing" (being generated) and "default"
# ("no summary has been generated yet"), https://docs.fireflies.ai/schema/enum/summary-status
UNFINISHED = {"processing", "default"}


def _date(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date YYYY-MM-DD: {value!r}") from None
    return value


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your own Fireflies meetings: participants, summaries, action items "
        "and transcripts (personal API key, see docs/CONNECTING.md#fireflies)."
    )
    ap.add_argument("--since", type=_date, help="start date YYYY-MM-DD (overrides the saved state)")
    ap.add_argument(
        "--days",
        type=int,
        default=None,
        help="first run: how many days back "
        f"(default fireflies.history_days or {DEFAULT_HISTORY_DAYS})",
    )
    ap.add_argument(
        "--only-organized",
        action="store_true",
        help="only the meetings you organized (transcripts(mine: true)); default: every meeting "
        "where you are organizer or participant (transcripts(user_id: <you>))",
    )
    ap.add_argument("--no-sentences", action="store_true", help="skip the full transcript text")
    ap.add_argument("--no-contacts", action="store_true", help="skip your Fireflies contact list")
    ap.add_argument("--force", action="store_true", help="fetch again transcripts already on disk")
    ap.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="cap on API requests in this run "
        f"(default fireflies.max_requests or {ff_api.DEFAULT_MAX_REQUESTS}; Free allows 500 a day)",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="one request: check the key and print whose account it is; writes nothing",
    )
    return ap.parse_args(argv)


def _start(args, state: dict, now: datetime, only_organized: bool = False) -> datetime:
    if args.since:
        return datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    # A saved date from runs that read only the meetings you organized does not cover the
    # meetings where you were a participant: going back to the full scope starts over.
    widened = bool(state.get("only_organized")) and not only_organized
    if state.get("last_to") and not widened:
        overlap = int(ff_api.cfg("overlap_days", DEFAULT_OVERLAP_DAYS))
        last = datetime.fromisoformat(state["last_to"].replace("Z", "+00:00"))
        return last - timedelta(days=overlap)
    days = (
        args.days
        if args.days is not None
        else int(ff_api.cfg("history_days", DEFAULT_HISTORY_DAYS))
    )
    return now - timedelta(days=days)


def _store_meeting(m: dict, stats: dict) -> str:
    """Write one meeting; returns its summary_status ('' when unknown)."""
    record = {k: v for k, v in m.items() if k not in ("audio_url", "video_url")}
    record["_fetched_at"] = datetime.now(UTC).isoformat()
    ff_api.write_json(ff_api.meetings_dir() / f"{ff_api.safe_id(m['id'])}.json", record)
    stats["meetings"] += 1
    return str(((m.get("meeting_info") or {}).get("summary_status")) or "").lower()


def _fetch_sentences(client, tid: str, stats: dict) -> bool:
    """True when the transcript text is on disk afterwards (or Fireflies has none)."""
    try:
        data = client.query(ff_api.SENTENCES_QUERY, {"id": tid})
    except (DailyLimitReached, AuthError):
        raise
    except GraphQLError as e:
        stats["errors"] += 1
        stats["error_samples"].append(f"transcript {tid}: {e.code}")
        return e.code == "object_not_found"  # deleted since: nothing to ask again
    except FirefliesError as e:
        stats["errors"] += 1
        stats["error_samples"].append(f"transcript {tid}: {e}")
        return False
    t = (data or {}).get("transcript") or {}
    sentences = t.get("sentences") or []
    ff_api.write_json(
        ff_api.sentences_dir() / f"{ff_api.safe_id(tid)}.json",
        {"id": tid, "sentences": sentences, "_fetched_at": datetime.now(UTC).isoformat()},
    )
    stats["transcripts_downloaded"] += 1
    stats["sentence_rows"] += len(sentences)
    return True


def run_download(client: ff_api.Client, args, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    state = ff_api.read_json(ff_api.state_path(), {}) or {}
    only_organized = bool(args.only_organized or ff_api.cfg("only_organized", False))
    start = _start(args, state, now, only_organized)
    want_sentences = not args.no_sentences and bool(ff_api.cfg("include_sentences", True))
    want_contacts = not args.no_contacts and bool(ff_api.cfg("include_contacts", True))
    stats = {
        "meetings": 0,
        "live_skipped": 0,
        "summaries_pending": 0,
        "transcripts_downloaded": 0,
        "transcripts_skipped": 0,
        "transcripts_pending": 0,
        "sentence_rows": 0,
        "contacts": 0,
        "errors": 0,
        "error_samples": [],
        "stopped": "",
    }
    started = datetime.now(UTC)

    me = (client.query(ff_api.ME_QUERY) or {}).get("user") or {}
    if not me.get("user_id"):
        raise FirefliesError("Fireflies returned no user for this API key")
    ff_api.write_json(
        ff_api.raw_dir() / "me.json",
        {k: me.get(k) for k in ("user_id", "email", "name")},
    )

    pending_text: list[str] = list(dict.fromkeys(state.get("pending_sentences") or []))
    pending_summary: dict = dict(state.get("pending_summary") or {})
    seen_now: set[str] = set()
    listed_complete = False
    fatal: FirefliesError | None = None

    try:
        if want_contacts:
            try:
                contacts = (client.query(ff_api.CONTACTS_QUERY) or {}).get("contacts") or []
                ff_api.write_json(
                    ff_api.raw_dir() / "contacts.json",
                    {"contacts": contacts, "_fetched_at": datetime.now(UTC).isoformat()},
                )
                stats["contacts"] = len(contacts)
            except GraphQLError as e:
                stats["errors"] += 1
                stats["error_samples"].append(f"contacts: {e.code}")

        query = ff_api.LIST_MINE_QUERY if only_organized else ff_api.LIST_BY_USER_QUERY
        for frm, to in ff_api.windows(start, now):
            skip = 0
            while True:
                variables = {
                    "fromDate": ff_api.api_datetime(frm),
                    "toDate": ff_api.api_datetime(to),
                    "limit": ff_api.PAGE_LIMIT,
                    "skip": skip,
                }
                if not only_organized:
                    variables["userId"] = me["user_id"]
                page = (client.query(query, variables) or {}).get("transcripts") or []
                for m in page:
                    tid = (m or {}).get("id")
                    if not tid or tid in seen_now:
                        continue
                    if m.get("is_live"):
                        stats["live_skipped"] += 1  # still running: read once it is over
                        continue
                    seen_now.add(tid)
                    status = _store_meeting(m, stats)
                    if status in UNFINISHED and not (m.get("summary") or {}).get("overview"):
                        pending_summary.setdefault(tid, ff_api.meeting_ts(m))
                    else:
                        pending_summary.pop(tid, None)
                    out = ff_api.sentences_dir() / f"{ff_api.safe_id(tid)}.json"
                    if want_sentences and (args.force or not out.exists()):
                        if tid not in pending_text:
                            pending_text.append(tid)
                    elif want_sentences:
                        stats["transcripts_skipped"] += 1
                if len(page) < ff_api.PAGE_LIMIT:
                    break
                skip += len(page)
        listed_complete = True

        # Summaries Fireflies had not finished on an earlier run, outside today's window.
        cutoff = iso_days_ago(now, PENDING_SUMMARY_MAX_DAYS)
        for tid, ts in list(pending_summary.items()):
            if tid in seen_now:
                continue
            if ts and ts < cutoff:
                pending_summary.pop(tid)  # Fireflies never finished it: stop asking
                continue
            try:
                m = (client.query(ff_api.ONE_QUERY, {"id": tid}) or {}).get("transcript")
            except (DailyLimitReached, AuthError):
                raise
            except GraphQLError as e:
                stats["errors"] += 1
                stats["error_samples"].append(f"summary {tid}: {e.code}")
                if e.code == "object_not_found":
                    pending_summary.pop(tid)
                continue
            except FirefliesError as e:  # network or 5xx on one item: asked again next run
                stats["errors"] += 1
                stats["error_samples"].append(f"summary {tid}: {e}")
                continue
            if not m:
                pending_summary.pop(tid)
                continue
            status = _store_meeting(m, stats)
            if status not in UNFINISHED or (m.get("summary") or {}).get("overview"):
                pending_summary.pop(tid)

        if want_sentences:
            for tid in list(pending_text):
                if _fetch_sentences(client, tid, stats):
                    pending_text.remove(tid)
    except DailyLimitReached as e:
        stats["stopped"] = str(e)
    except FirefliesError as e:
        # Key refused mid-run, network down after retries, a listing page refused: save the
        # state first (the saved date moves only if the listing was complete, the pending
        # lists keep what this run found), then report the error.
        stats["stopped"] = str(e)
        fatal = e

    stats["summaries_pending"] = len(pending_summary)
    stats["transcripts_pending"] = len(pending_text) if want_sentences else 0
    new_state = {
        "last_to": ff_api.iso(now) if listed_complete else state.get("last_to", ""),
        "last_run": datetime.now(UTC).isoformat(),
        "only_organized": only_organized,
        "pending_sentences": pending_text
        if want_sentences
        else list(state.get("pending_sentences") or []),
        "pending_summary": pending_summary,
    }
    ff_api.write_json(ff_api.state_path(), new_state)

    stats["error_samples"] = stats["error_samples"][:20]
    summary = {
        "source": ff_api.SOURCE,
        **stats,
        "window_from": ff_api.iso(start),
        "window_to": ff_api.iso(now),
        "complete": listed_complete and not stats["stopped"],
        "scope": "organized by you"
        if only_organized
        else "organized by you or with you as participant",
        "requests": client.requests,
        "rate_limit": client.rate_limit,
        "rate_remaining": client.rate_remaining,
        "partial_errors": client.partial_errors,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    ff_api.write_json(ff_api.summary_path(), summary)
    if fatal is not None:
        raise fatal
    return summary


def iso_days_ago(now: datetime, days: int) -> str:
    return ff_api.iso(now - timedelta(days=days))


def _mask_email(email: str) -> str:
    local, _, domain = str(email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "(no email)"


def cli(argv=None, opener=None, sleep=None) -> int:
    args = parse_args(argv)
    ff_api.load_dotenv_if_present()
    try:
        key, where = ff_api.resolve_api_key()
    except ff_api.NoApiKey as e:
        print(str(e), file=sys.stderr)
        return 1
    max_req = (
        args.max_requests
        if args.max_requests is not None
        else int(ff_api.cfg("max_requests", ff_api.DEFAULT_MAX_REQUESTS))
    )
    client = ff_api.Client(
        key,
        opener=opener,
        sleep=sleep,
        delay=float(ff_api.cfg("request_delay_seconds", ff_api.REQUEST_DELAY)),
        max_requests=max_req,
    )
    if args.check:
        try:
            me = (client.query(ff_api.ME_QUERY) or {}).get("user") or {}
        except FirefliesError as e:
            print(f"Fireflies: {e}", file=sys.stderr)
            return 1
        print(
            f"Fireflies: key from {where} works, account {me.get('name') or '?'} "
            f"<{_mask_email(me.get('email'))}>; rate limit {client.rate_limit or '?'}, "
            f"left {client.rate_remaining or '?'}"
        )
        return 0

    import logging

    from pipeline_decorator import pipeline_step

    # The step's own logger prints "Failed: ..." plus a full traceback on stderr for every
    # failure. A FirefliesError is already reported below as one clear line (the failure is
    # still recorded in the pipeline metrics and the failure queue); anything unexpected is
    # not caught here and still ends with Python's traceback.
    logging.getLogger("sbk-pipeline.l0-fireflies-download").setLevel(logging.CRITICAL)

    @pipeline_step(name="l0-fireflies-download", source=ff_api.SOURCE, stage="l0")
    def _run():
        return run_download(client, args)

    try:
        s = _run()
    except FirefliesError as e:
        print(f"Fireflies: {e}", file=sys.stderr)
        return 1
    print(
        f"Fireflies: {s['meetings']} meetings, {s['transcripts_downloaded']} new transcripts, "
        f"{s['contacts']} contacts, {s['errors']} errors; window {s['window_from'][:10]}.."
        f"{s['window_to'][:10]}; {s['requests']} requests"
        + (f"; stopped: {s['stopped']}" if s["stopped"] else "")
        + (
            f"; {s['transcripts_pending']} transcripts asked next run"
            if s["transcripts_pending"]
            else ""
        )
        + (
            f"; {s['summaries_pending']} summaries still processing"
            if s["summaries_pending"]
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli())
