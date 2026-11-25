#!/usr/bin/env python3
"""Zoom L0: download your own meetings, their participants and cloud-recording transcripts.

Reads only what your own user-level login can see (the `me` context):
- GET /users/me                                   user:read:user
- GET /users/me/recordings (windows of <= 1 month) cloud_recording:read:list_user_recordings
- each TRANSCRIPT file's download_url (VTT)        same login, Bearer token
- GET /past_meetings/{uuid}/participants           meeting:read:list_past_participants
- optional GET /users/me/meetings?type=previous_meetings   meeting:read:list_meetings

Writes under <data root>/zoom/:
  raw/me.json, raw/meetings/<key>.json, raw/transcripts/<key>.vtt,
  raw/participants/<key>.json, raw/state.json (incremental), download-summary.json

Incremental: the next run starts from the last completed day minus `zoom.overlap_days`
(transcripts and participant data can arrive after the meeting). Files already on disk
are not downloaded again unless --force. A run stopped by the daily limit, or with an
item Zoom kept failing on, does not move the saved day, so nothing is skipped for good.
Recording passcodes in Zoom's answer are dropped before anything is written.

Setup: docs/CONNECTING.md#zoom. First login: tools/zoom/zm-l0-auth.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zm_api  # noqa: E402
from zm_api import ApiHTTPError, DailyLimitReached, ZoomError  # noqa: E402

DEFAULT_HISTORY_DAYS = 90
DEFAULT_OVERLAP_DAYS = 7


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your own Zoom meetings, participants and cloud-recording "
        "transcripts (user-level OAuth, see docs/CONNECTING.md#zoom)."
    )
    ap.add_argument("--label", default=zm_api.DEFAULT_LABEL, help="login name (default: default)")
    ap.add_argument("--since", help="start date YYYY-MM-DD (overrides the saved state)")
    ap.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"first run: how many days back (default zoom.history_days or {DEFAULT_HISTORY_DAYS})",
    )
    ap.add_argument("--force", action="store_true", help="download again files already on disk")
    ap.add_argument("--no-participants", action="store_true", help="skip participant lists")
    ap.add_argument("--no-transcripts", action="store_true", help="skip transcript files")
    ap.add_argument(
        "--include-unrecorded",
        action="store_true",
        help="also list past scheduled meetings without a cloud recording (needs the optional "
        "scope meeting:read:list_meetings; Zoom returns at most 6 months of them)",
    )
    return ap.parse_args(argv)


def connect(label: str, opener=None, sleep=None) -> tuple[zm_api.ZoomClient, str]:
    """Refresh the stored login and return (client, granted scopes). Raises ZoomError."""
    cid = zm_api.client_id()
    refresh, where = zm_api.load_refresh_token(label)
    if not cid:
        raise ZoomError(
            f"{zm_api.ENV_CLIENT_ID} is not set (public client ID of your own Zoom app); "
            f"{zm_api.SETUP_HINT}"
        )
    if not refresh:
        raise ZoomError(
            f"no login stored (Keychain {zm_api.KEYCHAIN_SERVICE}/{label} or "
            f"{zm_api.ENV_REFRESH_TOKEN}); run: uv run python tools/zoom/zm-l0-auth.py"
        )
    current = {"refresh": refresh}

    def refresh_now() -> dict:
        tokens = zm_api.refresh_access_token(current["refresh"], cid, opener)
        new_refresh = tokens.get("refresh_token") or ""
        if new_refresh and new_refresh != current["refresh"]:
            current["refresh"] = new_refresh  # Zoom: always use the latest refresh token
            if not zm_api.save_refresh_token(new_refresh, label):
                print(
                    f"Warning: Zoom rotated the refresh token and it could not be stored (came "
                    f"from {where}); set {zm_api.ENV_TOKEN_FILE} so the next run can sign in",
                    file=sys.stderr,
                )
        return tokens

    tokens = refresh_now()
    client = zm_api.ZoomClient(
        tokens["access_token"],
        opener=opener,
        sleep=sleep,
        refresher=lambda: refresh_now()["access_token"],
    )
    return client, tokens.get("scope", "")


def _start_date(args, state: dict, today: date) -> date:
    if args.since:
        return date.fromisoformat(args.since)
    if state.get("last_to"):
        overlap = int(zm_api.cfg("overlap_days", DEFAULT_OVERLAP_DAYS))
        return date.fromisoformat(state["last_to"]) - timedelta(days=overlap)
    days = (
        args.days
        if args.days is not None
        else int(zm_api.cfg("history_days", DEFAULT_HISTORY_DAYS))
    )
    return today - timedelta(days=days)


def _fetch_transcripts(client, meeting: dict, key: str, args, stats: dict) -> None:
    tdir = zm_api.raw_dir() / "transcripts"
    for f in meeting.get("recording_files") or []:
        if str(f.get("file_type", "")).upper() != "TRANSCRIPT" or not f.get("download_url"):
            continue
        if f.get("status") and f.get("status") != "completed":
            stats["transcripts_not_ready"] += 1
            continue
        out = tdir / f"{key}.vtt"
        if out.exists() and not args.force:
            stats["transcripts_skipped"] += 1
            continue
        try:
            data = client.download(f["download_url"])
        except DailyLimitReached:
            raise
        except ApiHTTPError as e:
            stats["errors"] += 1
            stats["error_samples"].append(f"transcript HTTP {e.code}")
            continue
        except ZoomError as e:
            # Zoom kept failing on this one file (5xx, network): the rest of the run goes
            # on, and the saved window does not move so the next run asks again.
            stats["errors"] += 1
            stats["retry_next_run"] += 1
            stats["error_samples"].append(f"transcript: {e}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        stats["transcripts_downloaded"] += 1
        return  # one transcript per meeting instance


def _fetch_participants(client, uuid: str, key: str, args, stats: dict) -> None:
    out = zm_api.raw_dir() / "participants" / f"{key}.json"
    old = zm_api.read_json(out, {}) or {}
    if old.get("status") == "ok" and not args.force:
        stats["participants_skipped"] += 1
        return
    try:
        people = list(
            client.paged(f"/past_meetings/{zm_api.encode_uuid(uuid)}/participants", "participants")
        )
    except DailyLimitReached:
        raise
    except ApiHTTPError as e:
        # 400/403/404: plan below Pro, scope not granted, meeting older than 15 months,
        # one-person meeting, or data not processed yet. Kept as "unavailable", retried
        # on the next run.
        zm_api.write_json(
            out, {"uuid": uuid, "status": "unavailable", "http": e.code, "reason": e.body[:300]}
        )
        stats["participants_unavailable"] += 1
        return
    except ZoomError as e:
        # 5xx or network on this one list: nothing written, asked again next run.
        stats["errors"] += 1
        stats["retry_next_run"] += 1
        stats["error_samples"].append(f"participants: {e}")
        return
    zm_api.write_json(out, {"uuid": uuid, "status": "ok", "participants": people})
    stats["participants_downloaded"] += 1
    stats["participant_rows"] += len(people)


def _handle_meeting(client, meeting: dict, origin: str, args, stats: dict, seen: dict) -> None:
    uuid = meeting.get("uuid")
    if not uuid:
        return
    key = zm_api.file_key(uuid)
    record = zm_api.strip_secrets(dict(meeting))  # no recording passcodes on disk
    record["_origin"] = origin
    record["_fetched_at"] = datetime.now(UTC).isoformat()
    zm_api.write_json(zm_api.raw_dir() / "meetings" / f"{key}.json", record)
    stats["meetings"] += 1
    if not args.no_transcripts:
        _fetch_transcripts(client, meeting, key, args, stats)
    if not args.no_participants:
        _fetch_participants(client, uuid, key, args, stats)
    seen[uuid] = meeting.get("start_time", "")


def run_download(
    client: zm_api.ZoomClient, args, today: date | None = None, scope: str = ""
) -> dict:
    today = today or datetime.now(UTC).date()
    state = zm_api.read_json(zm_api.state_path(), {}) or {}
    start = _start_date(args, state, today)
    stats = {
        "meetings": 0,
        "transcripts_downloaded": 0,
        "transcripts_skipped": 0,
        "transcripts_not_ready": 0,
        "participants_downloaded": 0,
        "participants_skipped": 0,
        "participants_unavailable": 0,
        "participant_rows": 0,
        "unrecorded_meetings": 0,
        "errors": 0,
        "retry_next_run": 0,
        "error_samples": [],
        "stopped": "",
    }
    seen: dict = dict(state.get("seen") or {})
    started = datetime.now(UTC)

    me = client.get("/users/me")
    zm_api.write_json(
        zm_api.raw_dir() / "me.json",
        {
            k: me.get(k)
            for k in ("id", "email", "display_name", "first_name", "last_name", "timezone")
        },
    )

    complete = True
    try:
        for frm, to in zm_api.windows(start, today):
            for m in client.paged(
                "/users/me/recordings",
                "meetings",
                **{"from": frm.isoformat(), "to": to.isoformat()},
            ):
                _handle_meeting(client, m, "recordings", args, stats, seen)
        if args.include_unrecorded or zm_api.cfg("include_unrecorded", False):
            try:
                for m in client.paged("/users/me/meetings", "meetings", type="previous_meetings"):
                    if not m.get("uuid") or m["uuid"] in seen:
                        continue
                    if str(m.get("start_time", ""))[:10] < start.isoformat():
                        continue
                    stats["unrecorded_meetings"] += 1
                    _handle_meeting(client, m, "list_meetings", args, stats, seen)
            except ApiHTTPError as e:
                stats["errors"] += 1
                stats["error_samples"].append(
                    f"list meetings HTTP {e.code} (scope meeting:read:list_meetings?)"
                )
    except DailyLimitReached as e:
        complete = False
        stats["stopped"] = str(e)
    if stats["retry_next_run"]:
        complete = False  # keep the old window start so those items are asked again

    new_state = {
        "last_to": today.isoformat() if complete else state.get("last_to", ""),
        "last_run": datetime.now(UTC).isoformat(),
        "seen": seen,
    }
    zm_api.write_json(zm_api.state_path(), new_state)

    stats["error_samples"] = stats["error_samples"][:20]
    summary = {
        "source": zm_api.SOURCE,
        **stats,
        "window_from": start.isoformat(),
        "window_to": today.isoformat(),
        "complete": complete,
        "requests": client.requests,
        "missing_scopes": zm_api.missing_scopes(scope) if scope else [],
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    zm_api.write_json(zm_api.summary_path(), summary)
    return summary


def cli(argv=None, opener=None, sleep=None) -> int:
    args = parse_args(argv)
    try:
        client, scope = connect(args.label, opener=opener, sleep=sleep)
    except ZoomError as e:
        print(f"Zoom: {e}", file=sys.stderr)
        return 1

    from pipeline_decorator import pipeline_step

    @pipeline_step(name="l0-zoom-download", source=zm_api.SOURCE, stage="l0")
    def _run():
        return run_download(client, args, scope=scope)

    try:
        s = _run()
    except ZoomError as e:
        print(f"Zoom: {e}", file=sys.stderr)
        return 1
    print(
        f"Zoom: {s['meetings']} meetings, {s['transcripts_downloaded']} new transcripts, "
        f"{s['participants_downloaded']} participant lists ({s['participants_unavailable']} unavailable), "
        f"{s['errors']} errors; window {s['window_from']}..{s['window_to']}"
        + (f"; stopped: {s['stopped']}" if s["stopped"] else "")
        + (f"; {s['retry_next_run']} items asked again next run" if s["retry_next_run"] else "")
    )
    if s["missing_scopes"]:
        print("Zoom: scopes not granted to your app: " + ", ".join(s["missing_scopes"]))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
