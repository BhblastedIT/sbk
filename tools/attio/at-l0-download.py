#!/usr/bin/env python3
"""Attio CRM download: records of every object, lists, notes, meetings, call transcripts, tasks and the workspace
metadata, through the Attio API key, for the primary workspace and the extra ones in sbk.config.json.
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow requests")
    sys.exit(1)



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from datetime import UTC, datetime

from sbk_config import (
    ATTIO_EXTRA_WORKSPACES,
    ATTIO_PRIMARY_WORKSPACE,
    DATA_ROOT,
    compute_record_hash,
    get_last_run,
    load_record_hashes,
    mark_last_run,
    safe_write_parquet,
    save_record_hashes,
)





# The primary workspace (label "primary", key ATTIO_API_KEY, data in attio/)
# plus the extra ones listed in sbk.config.json "attio.extra_workspaces"
# (key in Keychain sbk-attio/<label>, data in attio-<label>/).
WORKSPACES: dict[str, tuple[str, Path]] = {
    ATTIO_PRIMARY_WORKSPACE: ("primary", DATA_ROOT / "attio"),
    **{
        label: (name or label, DATA_ROOT / f"attio-{label}")
        for label, name in ATTIO_EXTRA_WORKSPACES.items()
        if label != ATTIO_PRIMARY_WORKSPACE
    },
}
WORKSPACE = os.environ.get("SBK_ATTIO_WORKSPACE") or ATTIO_PRIMARY_WORKSPACE
if WORKSPACE not in WORKSPACES:
    sys.exit(
        f"unknown Attio workspace: {WORKSPACE} (known: {', '.join(WORKSPACES)}). "
        "Extra workspaces go in sbk.config.json under attio.extra_workspaces."
    )
ATTIO_DIR = WORKSPACES[WORKSPACE][1]

MARK_KEY = "attio" if WORKSPACE == ATTIO_PRIMARY_WORKSPACE else f"attio-{WORKSPACE}"

METADATA_DIR = ATTIO_DIR / "metadata"
LOOKUPS_DIR = ATTIO_DIR / "lookups"
TRANSCRIPTS_DIR = ATTIO_DIR / "transcripts"
BASE_URL = "https://api.attio.com/v2"
MULTI_SEP = "|||"

log = logging.getLogger("at-l0-download")


def get_api_key() -> str:
    ""

    if WORKSPACE != ATTIO_PRIMARY_WORKSPACE:
        from secrets_adapter import get_secret

        key = get_secret("sbk-attio", WORKSPACE)
        if key:
            return key
        log.error(f"Attio key for '{WORKSPACE}' missing (Keychain sbk-attio/{WORKSPACE})")
        sys.exit(1)
    key = os.environ.get("ATTIO_API_KEY")
    if key:
        return key


    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        cfg = json.loads(claude_json.read_text())
        mcp = cfg.get("mcpServers", {}).get("attio", {})
        key = mcp.get("env", {}).get("ATTIO_API_KEY")
        if key:
            return key

    log.error(
        "ATTIO_API_KEY not found in env or ~/.claude.json: put it in .env "
        "(docs/CONNECTING.md#attio); nothing downloaded"
    )
    sys.exit(1)





REQUEST_TIMEOUT = 30



MAX_PAGES = 100_000


def _repeated_page(prev_page: list | None, current: list) -> bool:
    ""

    return bool(prev_page) and bool(current) and prev_page[0].get("id") == current[0].get("id")


MAX_RETRIES = 5
DEFAULT_WORKERS = 6


def _retry_after_seconds(resp: requests.Response, attempt: int) -> float:
    ""





    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            return min(float(ra), 60.0)
        except ValueError:
            pass
    return min(2.0**attempt, 60.0)


class AttioClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, *, params: dict = None, body: dict = None) -> dict:
        ""




        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                if method == "GET":
                    r = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                else:
                    r = self.session.post(url, json=body or {}, timeout=REQUEST_TIMEOUT)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    wait = _retry_after_seconds(r, attempt)
                    log.warning(
                        f"{method} {path} -> {r.status_code}, retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 5 * (attempt + 1)
                    log.warning(
                        f"Timeout/connection on {method} {path}, retry {attempt + 1}/{MAX_RETRIES} in {wait}s: {e}"
                    )
                    time.sleep(wait)
                else:
                    raise

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict = None) -> dict:
        return self._request("POST", path, body=body)



    def list_records(self, object_slug: str, page_size: int = 100) -> list:
        ""
        all_records = []
        offset = 0
        prev_page = None

        for _page in range(MAX_PAGES):
            body = {"limit": page_size, "offset": offset}
            resp = self._post(f"/objects/{object_slug}/records/query", body)
            data = resp.get("data", [])
            if _repeated_page(prev_page, data):
                raise RuntimeError(
                    f"{object_slug}: repeated page at offset {offset}, listing stopped"
                )
            prev_page = data
            all_records.extend(data)
            log.info(
                f"  {object_slug}: page {_page + 1}, got {len(data)} (total {len(all_records)})"
            )

            if len(data) < page_size:
                break
            offset += page_size
            time.sleep(0.3)
        else:
            raise RuntimeError(
                f"{object_slug}: reached the {MAX_PAGES}-page cap, listing incomplete"
            )

        return all_records

    def list_lists(self) -> list:
        ""
        resp = self._get("/lists")
        return resp.get("data", [])

    def list_entries(self, list_id: str, page_size: int = 100) -> list:
        ""
        all_entries = []
        offset = 0
        prev_page = None

        for _page in range(MAX_PAGES):
            body = {"limit": page_size, "offset": offset}
            resp = self._post(f"/lists/{list_id}/entries/query", body)
            data = resp.get("data", [])
            if _repeated_page(prev_page, data):
                raise RuntimeError(
                    f"list {list_id}: repeated page at offset {offset}, listing stopped"
                )
            prev_page = data
            all_entries.extend(data)

            if len(data) < page_size:
                break
            offset += page_size
            time.sleep(0.3)
        else:
            raise RuntimeError(
                f"list {list_id}: reached the {MAX_PAGES}-page cap, listing incomplete"
            )

        return all_entries

    def get_record(self, object_slug: str, record_id: str) -> dict:
        ""
        resp = self._get(f"/objects/{object_slug}/records/{record_id}")
        return resp.get("data", {})



    def list_notes(self, page_size: int = 50) -> list:
        ""
        all_notes = []
        offset = 0
        prev_page = None

        for _page in range(MAX_PAGES):
            resp = self._get("/notes", params={"limit": page_size, "offset": offset})
            data = resp.get("data", [])
            if _repeated_page(prev_page, data):
                raise RuntimeError(f"note: repeated page at offset {offset}, listing stopped")
            prev_page = data
            all_notes.extend(data)

            if len(data) < page_size:
                break
            offset += page_size
            time.sleep(0.3)
        else:
            raise RuntimeError(f"note: reached the {MAX_PAGES}-page cap, listing incomplete")

        return all_notes



    def list_meetings(self, page_size: int = 50) -> list:
        ""
        all_meetings = []
        cursor = None
        seen: set[str] = set()

        for _page in range(MAX_PAGES):
            params = {"limit": page_size}
            if cursor:
                params["cursor"] = cursor
            resp = self._get("/meetings", params=params)
            data = resp.get("data", [])
            all_meetings.extend(data)

            pagination = resp.get("pagination", {})
            cursor = pagination.get("next_cursor")


            if not cursor:
                break
            if cursor in seen:
                raise RuntimeError("list_meetings: repeated cursor, listing stopped")
            seen.add(cursor)
            time.sleep(0.3)
            log.info(f"  meetings: page {_page + 1}, got {len(data)} (total {len(all_meetings)})")
        else:
            raise RuntimeError(f"list_meetings: reached MAX_PAGES={MAX_PAGES}, list truncated")

        return all_meetings



    def get_call_recordings(self, meeting_id: str) -> list:
        ""
        out: list = []
        cursor = None
        seen: set[str] = set()
        try:
            for _page in range(MAX_PAGES):
                params = {"cursor": cursor} if cursor else None
                resp = self._get(f"/meetings/{meeting_id}/call_recordings", params=params)
                out.extend(resp.get("data", []))
                cursor = (resp.get("pagination") or {}).get("next_cursor")
                if not cursor:
                    return out
                if cursor in seen:
                    raise RuntimeError(f"call_recordings {meeting_id}: repeated cursor")
                seen.add(cursor)
            raise RuntimeError(f"call_recordings {meeting_id}: reached MAX_PAGES")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return out
            raise

    def get_transcript(self, meeting_id: str, recording_id: str) -> "dict | None":
        ""




        all_segments = []
        raw_text_parts = []
        base_data = None

        try:
            cursor = None
            for _page in range(MAX_PAGES):
                params = {}
                if cursor:
                    params["cursor"] = cursor
                resp = self._get(
                    f"/meetings/{meeting_id}/call_recordings/{recording_id}/transcript",
                    params=params,
                )
                data = resp.get("data", resp)

                if base_data is None:
                    base_data = data


                segments = data.get("transcript", data.get("segments", data.get("entries", [])))
                all_segments.extend(segments)


                if data.get("raw_transcript"):
                    raw_text_parts.append(data["raw_transcript"])


                pagination = resp.get("pagination", {})
                next_cursor = pagination.get("next_cursor")
                if not next_cursor or len(segments) == 0:
                    break
                if next_cursor == cursor:
                    raise RuntimeError(f"transcript {recording_id}: repeated cursor")
                cursor = next_cursor
                time.sleep(0.3)

            else:
                raise RuntimeError(f"transcript {recording_id}: reached MAX_PAGES, truncated")

            if base_data is None:
                return None


            if "transcript" in base_data:
                base_data["transcript"] = all_segments
            elif "segments" in base_data:
                base_data["segments"] = all_segments
            elif "entries" in base_data:
                base_data["entries"] = all_segments
            else:
                base_data["transcript"] = all_segments

            if raw_text_parts:
                base_data["raw_transcript"] = "\n".join(raw_text_parts)

            if len(all_segments) >= 1000 and _page > 0:
                log.info(
                    f"  Transcript {recording_id}: paginated {_page + 1} pages, {len(all_segments)} total segments"
                )

            return base_data

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise



    def list_tasks(self, page_size: int = 500) -> list:
        ""




        all_tasks = []
        offset = 0
        prev_page = None
        for _page in range(MAX_PAGES):
            resp = self._get("/tasks", params={"limit": page_size, "offset": offset})
            data = resp.get("data", [])
            if _repeated_page(prev_page, data):
                raise RuntimeError(f"task: repeated page at offset {offset}, listing stopped")
            prev_page = data
            all_tasks.extend(data)
            if len(data) < page_size:
                break
            offset += page_size
            time.sleep(0.3)
        else:
            raise RuntimeError(f"task: reached the {MAX_PAGES}-page cap, listing incomplete")
        return all_tasks



    def get_object_attributes(self, object_slug: str) -> list:
        ""
        resp = self._get(f"/objects/{object_slug}/attributes")
        return resp.get("data", [])

    def get_select_options(self, object_id: str, attribute_id: str) -> list:
        ""
        try:
            resp = self._get(f"/objects/{object_id}/attributes/{attribute_id}/options")
            return resp.get("data", [])
        except requests.HTTPError:
            return []

    def get_statuses(self, object_id: str, attribute_id: str) -> list:
        ""
        try:
            resp = self._get(f"/objects/{object_id}/attributes/{attribute_id}/statuses")
            return resp.get("data", [])
        except requests.HTTPError:
            return []

    def get_workspace_members(self) -> list:
        ""
        resp = self._get("/workspace_members")
        return resp.get("data", [])





def _extract_single_value(item: dict) -> str | None:
    ""
    if not isinstance(item, dict):
        return str(item) if item is not None else None

    attr_type = item.get("attribute_type", "")


    if "value" in item:
        return item["value"]


    if "first_name" in item:
        return f"{item.get('first_name', '')} {item.get('last_name', '')}".strip()
    if "full_name" in item:
        return item["full_name"]


    if "email_address" in item:
        return item["email_address"]
    if "original_email_address" in item:
        return item["original_email_address"]


    if "domain" in item:
        return item["domain"]


    if "phone_number" in item:
        return item["phone_number"]


    if "option" in item:
        opt = item["option"]
        if isinstance(opt, dict):
            return opt.get("title", str(opt))
        return str(opt)


    if "status" in item:
        status = item["status"]
        if isinstance(status, dict):
            return status.get("title", str(status))
        return str(status)


    if "currency_value" in item:
        return item["currency_value"]


    if "target_object" in item:
        return item.get("target_record_id")


    if "referenced_actor_type" in item:
        return item.get("referenced_actor_id")


    if "interaction_type" in item:
        return item.get("interacted_at")


    if "title" in item:
        return item["title"]

    return str(item)


def flatten_attio_values(values: dict) -> dict:
    ""








    flat = {}
    for attr_slug, val_list in values.items():
        if not val_list:
            flat[attr_slug] = None
            continue

        if not isinstance(val_list, list):
            flat[attr_slug] = val_list
            continue


        first = val_list[0]
        if isinstance(first, dict) and "line_1" in first:
            parts = [
                first.get("line_1", ""),
                first.get("locality", ""),
                first.get("region", ""),
                first.get("country_code", ""),
            ]
            flat[attr_slug] = ", ".join(p for p in parts if p)
            lat = first.get("latitude")
            lon = first.get("longitude")
            if lat is not None:
                flat[f"{attr_slug}_lat"] = lat
            if lon is not None:
                flat[f"{attr_slug}_lon"] = lon
            continue


        extracted = [_extract_single_value(item) for item in val_list]
        extracted = [v for v in extracted if v is not None]

        if len(extracted) == 0:
            flat[attr_slug] = None
        elif len(extracted) == 1:
            flat[attr_slug] = extracted[0]
        else:
            flat[attr_slug] = MULTI_SEP.join(str(v) for v in extracted)

    return flat


def records_to_df(records: list, object_slug: str) -> pd.DataFrame:
    ""
    rows = []
    for rec in records:
        row = {
            "record_id": rec["id"]["record_id"],
            "created_at": rec.get("created_at"),
            "web_url": rec.get("web_url"),
        }
        values = rec.get("values", {})
        row.update(flatten_attio_values(values))
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info(f"{object_slug}: {len(df)} records, {len(df.columns)} columns")
    return df


def entries_to_df(entries: list, list_name: str) -> pd.DataFrame:
    ""
    rows = []
    for entry in entries:
        row = {
            "entry_id": entry["id"]["entry_id"],
            "parent_record_id": entry.get("parent_record_id"),
            "parent_object": entry.get("parent_object"),
            "created_at": entry.get("created_at"),
        }
        values = entry.get("entry_values", entry.get("values", {}))
        row.update(flatten_attio_values(values))
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info(f"List '{list_name}': {len(df)} entries, {len(df.columns)} columns")
    return df





def export_objects(client: AttioClient):
    ""
    for slug in ["companies", "people", "deals"]:
        log.info(f"Fetching {slug}...")
        t0 = time.time()
        records = client.list_records(slug)
        elapsed = time.time() - t0
        log.info(f"Fetched {len(records)} {slug} in {elapsed:.1f}s")

        if not records:
            log.warning(f"No {slug} found, skipping")
            continue




        old_hashes = load_record_hashes(f"{ATTIO_DIR.name}/{slug}")
        new_hashes = {}
        changed = 0
        for rec in records:
            rid = rec["id"]["record_id"]
            h = compute_record_hash(rec.get("values", {}))
            new_hashes[rid] = h
            if old_hashes.get(rid) != h:
                changed += 1

        if changed == 0 and len(new_hashes) == len(old_hashes):
            log.info(f"{slug}: {len(records)} records, no changes (skipping write)")
            continue

        log.info(f"{slug}: {len(records)} records, {changed} changed")

        df = records_to_df(records, slug)
        out = ATTIO_DIR / f"{slug}.parquet"
        safe_write_parquet(df, out, index=False)
        log.info(f"Saved {slug} → {out}")


        raw_path = ATTIO_DIR / f"{slug}-raw.json"
        raw_path.write_text(json.dumps(records, indent=2, default=str))

        save_record_hashes(f"{ATTIO_DIR.name}/{slug}", new_hashes)


def export_lists(client: AttioClient):
    ""
    lists = client.list_lists()
    log.info(f"Found {len(lists)} lists")

    list_meta = []
    written: set[str] = set()
    for lst in lists:
        list_id = lst["id"]["list_id"]
        name = lst.get("name", "unnamed")
        slug = name.lower().replace(" ", "-").replace("&", "and")

        log.info(f"Fetching list '{name}' ({list_id})...")
        t0 = time.time()
        entries = client.list_entries(list_id)
        elapsed = time.time() - t0
        log.info(f"Fetched {len(entries)} entries from '{name}' in {elapsed:.1f}s")

        if not entries:
            log.warning(f"No entries in list '{name}', skipping")
            continue

        df = entries_to_df(entries, name)
        out = ATTIO_DIR / f"list-{slug}.parquet"
        safe_write_parquet(df, out, index=False)
        written.add(out.name)
        log.info(f"Saved list '{name}' → {out}")

        list_meta.append(
            {
                "list_id": list_id,
                "name": name,
                "slug": slug,
                "entry_count": len(entries),
                "parent_object": lst.get("parent_object"),
                "workspace_access": lst.get("workspace_access"),
            }
        )


    meta_path = ATTIO_DIR / "lists-meta.json"
    meta_path.write_text(json.dumps(list_meta, indent=2))
    log.info(f"Saved list metadata → {meta_path}")




    stale = [p for p in ATTIO_DIR.glob("list-*.parquet") if p.name not in written]
    if stale:
        aside = ATTIO_DIR / "_old-lists"
        aside.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        for p in stale:
            p.rename(aside / f"{today}-{p.name}")
            log.info(f"List no longer in Attio under this name, set aside: {p.name}")


def export_notes(client: AttioClient):
    ""
    log.info("Fetching notes...")
    t0 = time.time()
    notes = client.list_notes()
    elapsed = time.time() - t0
    log.info(f"Fetched {len(notes)} notes in {elapsed:.1f}s")

    if not notes:
        log.warning("No notes found")
        return

    rows = []
    for note in notes:
        note_id = note.get("id", {}).get("note_id", note.get("id"))


        parent_object = note.get("parent_object")
        parent_record_id = note.get("parent_record_id")


        content_plaintext = note.get("content_plaintext", "")
        content_markdown = note.get("content_markdown", "")

        if not content_plaintext:
            content_plaintext = note.get("plaintext", note.get("body_plaintext", ""))
        if not content_markdown:
            content_markdown = note.get("markdown", note.get("body_markdown", ""))


        created_by = note.get("created_by_actor", note.get("created_by", {}))
        created_by_type = created_by.get("type", "") if isinstance(created_by, dict) else ""
        created_by_id = created_by.get("id", "") if isinstance(created_by, dict) else ""

        rows.append(
            {
                "note_id": str(note_id) if isinstance(note_id, dict) else note_id,
                "parent_object": parent_object,
                "parent_record_id": parent_record_id,
                "title": note.get("title", ""),
                "content_plaintext": content_plaintext,
                "content_markdown": content_markdown,
                "created_by_type": created_by_type,
                "created_by_id": str(created_by_id),
                "created_at": note.get("created_at"),
            }
        )

    df = pd.DataFrame(rows)
    out = ATTIO_DIR / "notes.parquet"
    safe_write_parquet(df, out, index=False)
    log.info(f"Saved {len(df)} notes → {out}")


def export_meetings(client: AttioClient) -> list:
    ""
    log.info("Fetching meetings...")
    t0 = time.time()
    meetings = client.list_meetings()
    elapsed = time.time() - t0
    log.info(f"Fetched {len(meetings)} meetings in {elapsed:.1f}s")

    if not meetings:
        log.warning("No meetings found")
        return []

    rows = []
    for mtg in meetings:
        mtg_id = mtg.get("id", {})
        if isinstance(mtg_id, dict):
            mtg_id = mtg_id.get("meeting_id", str(mtg_id))


        participants = mtg.get("participants", [])
        participant_emails = []
        for p in participants:
            email = p.get("email_address", p.get("email", ""))
            if email:
                participant_emails.append(email)


        linked = mtg.get("linked_records", mtg.get("record_associations", []))
        linked_ids = []
        for lr in linked if isinstance(linked, list) else []:
            rid = lr.get("record_id", lr.get("target_record_id", ""))
            if rid:
                linked_ids.append(rid)

        rows.append(
            {
                "meeting_id": str(mtg_id),
                "title": mtg.get("title", mtg.get("summary", "")),
                "description": mtg.get("description", ""),
                "start_dt": (mtg.get("start", {}) or {}).get("datetime", mtg.get("start_at")),
                "end_dt": (mtg.get("end", {}) or {}).get("datetime", mtg.get("end_at")),
                "is_all_day": mtg.get("is_all_day", False),
                "participants": MULTI_SEP.join(participant_emails) if participant_emails else None,
                "participant_count": len(participants),
                "linked_record_ids": MULTI_SEP.join(linked_ids) if linked_ids else None,
                "created_at": mtg.get("created_at"),
            }
        )

    df = pd.DataFrame(rows)
    out = ATTIO_DIR / "meetings.parquet"
    safe_write_parquet(df, out, index=False)
    log.info(f"Saved {len(df)} meetings → {out}")

    return meetings


def _extract_meeting_id(mtg: dict) -> str:
    ""
    mtg_id = mtg.get("id", {})
    if isinstance(mtg_id, dict):
        mtg_id = mtg_id.get("meeting_id", str(mtg_id))
    return str(mtg_id)


def _clean_segments(transcript: dict) -> list[dict]:
    ""
    segments = transcript.get(
        "transcript", transcript.get("segments", transcript.get("entries", []))
    )
    out = []
    for seg in segments or []:
        speaker_raw = seg.get("speaker", "Unknown")
        speaker = (
            speaker_raw.get("name", "Unknown")
            if isinstance(speaker_raw, dict)
            else str(speaker_raw)
        )
        out.append(
            {
                "speaker": speaker,
                "text": seg.get("speech", seg.get("text", seg.get("content", ""))),
                "start": seg.get("start_time", seg.get("start", 0.0)),
                "end": seg.get("end_time", seg.get("end", 0.0)),
            }
        )
    return out


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def _transcript_path(mtg_id: str, rec_id: str) -> Path:
    ""



    base = TRANSCRIPTS_DIR / f"{mtg_id}.json"
    existing = _read_json(base) if base.exists() else None
    if existing is None or str(existing.get("recording_id", rec_id)) == rec_id:
        return base
    return TRANSCRIPTS_DIR / f"{mtg_id}__{rec_id}.json"


def _scan_meeting_recordings(client: AttioClient, mtg: dict, retry_stubs: bool = False) -> list:
    ""



    mtg_id = _extract_meeting_id(mtg)
    mtg_title = mtg.get("title", mtg.get("summary", ""))
    mtg_date = (mtg.get("start", {}) or {}).get("datetime", mtg.get("start_at", ""))
    now_iso = datetime.now(UTC).isoformat()

    rows = []
    for rec in client.get_call_recordings(mtg_id):
        rec_id = rec.get("id", {})
        if isinstance(rec_id, dict):
            rec_id = rec_id.get("call_recording_id", str(rec_id))
        rec_id = str(rec_id)
        tp = _transcript_path(mtg_id, rec_id)
        existing = _read_json(tp) if tp.exists() else None
        n_prev = len((existing or {}).get("segments") or [])
        prev_status = (existing or {}).get("_status", "")

        row = {
            "recording_id": rec_id,
            "meeting_id": mtg_id,
            "meeting_title": mtg_title,
            "meeting_date": mtg_date,
            "status": rec.get("status", ""),
            "web_url": rec.get("web_url", ""),
            "created_at": rec.get("created_at"),
            "created_by_actor": json.dumps(rec.get("created_by_actor") or {}),
            "file": tp.name,
            "n_segments": n_prev,
            "transcript_status": prev_status or ("complete" if n_prev else ""),
            "last_seen_in_api": now_iso,
        }

        needs_download = n_prev == 0 and (
            existing is None or retry_stubs or prev_status not in ("transcript_404",)
        )
        if needs_download:
            try:
                transcript = client.get_transcript(mtg_id, rec_id)
            except Exception as e:  # noqa: BLE001
                row["transcript_status"] = f"error: {str(e)[:80]}"
                rows.append(row)
                continue
            segs = _clean_segments(transcript) if transcript else []
            state = (
                "complete"
                if segs
                else ("transcript_404" if transcript is None else "empty_in_attio")
            )
            out = {
                "meeting_id": mtg_id,
                "recording_id": rec_id,
                "meeting_title": mtg_title,
                "meeting_date": mtg_date,
                "recording_status": rec.get("status", ""),
                "web_url": rec.get("web_url", ""),
                "segments": segs,
                "raw_transcript": "\n".join(f"{g['speaker']}: {g['text']}" for g in segs),
                "_status": state,
                "_checked_at": now_iso,
            }

            if len(segs) >= n_prev:
                tp.write_text(json.dumps(out, indent=2, default=str))
                if segs:
                    log.info(f"  Saved transcript {mtg_id}/{rec_id} ({len(segs)} segments)")
            row["n_segments"] = max(len(segs), n_prev)
            row["transcript_status"] = state if segs or not n_prev else "complete"
        rows.append(row)
    return rows


def _mark_gone_recordings(seen_meetings: set[str], seen_recordings: set[str]) -> int:
    ""


    marked = 0
    for f in TRANSCRIPTS_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        d = _read_json(f)
        if not d or d.get("segments") or d.get("_status") == "recording_gone":
            continue
        mid, rid = str(d.get("meeting_id", "")), str(d.get("recording_id", ""))
        if mid in seen_meetings and rid not in seen_recordings:
            d["_status"] = "recording_gone"
            d["_checked_at"] = datetime.now(UTC).isoformat()
            f.write_text(json.dumps(d, indent=2, default=str))
            marked += 1
    return marked


def _previous_inventory(out: Path) -> pd.DataFrame:
    ""

    parts = []
    if out.exists():
        parts.append(pd.read_parquet(out))
    backup_dir = out.parent / ".backup"
    if backup_dir.exists():
        for b in sorted(backup_dir.glob("call-recordings.parquet.*")):
            try:
                parts.append(pd.read_parquet(b))
            except Exception:  # noqa: BLE001
                continue
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).drop_duplicates("recording_id", keep="last")


def export_transcripts(
    client: AttioClient,
    meetings: list = None,
    skip_existing: bool = True,
    retry_stubs: bool = False,
    workers: int = DEFAULT_WORKERS,
):
    ""





    if meetings is None:
        log.info("Loading meetings for transcript scan...")
        meetings = client.list_meetings()

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Scanning {len(meetings)} meetings for call recordings ({workers} workers)...")

    all_rows: list[dict] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_scan_meeting_recordings, client, m, retry_stubs): m for m in meetings}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                all_rows.extend(fut.result())
            except Exception as e:  # noqa: BLE001  one failed meeting does not stop the others
                failed.append(_extract_meeting_id(futures[fut]))
                log.warning(f"  scan failed {failed[-1]}: {str(e)[:100]}")
            if i % 500 == 0:
                log.info(f"  Scanned {i}/{len(meetings)} meetings, {len(all_rows)} recordings...")


    for mid in list(failed):
        mtg = next(m for m in meetings if _extract_meeting_id(m) == mid)
        try:
            all_rows.extend(_scan_meeting_recordings(client, mtg, retry_stubs))
            failed.remove(mid)
        except Exception as e:  # noqa: BLE001
            log.error(f"  scan failed again on retry {mid}: {str(e)[:100]}")

    marked = _mark_gone_recordings(
        {_extract_meeting_id(m) for m in meetings}, {r["recording_id"] for r in all_rows}
    )

    out = ATTIO_DIR / "call-recordings.parquet"
    prev_inv = _previous_inventory(out)
    new_df = pd.DataFrame(all_rows)
    inventory = pd.concat([prev_inv, new_df], ignore_index=True) if len(prev_inv) else new_df
    if len(inventory):
        inventory = inventory.drop_duplicates("recording_id", keep="last")
        safe_write_parquet(inventory, out, index=False)

    counts = new_df["transcript_status"].value_counts().to_dict() if len(new_df) else {}
    coverage = {
        "meetings": len(meetings),
        "recordings_in_api": len(new_df),
        "total_inventory": len(inventory),
        "by_status": counts,
        "stubs_marked_recording_gone": marked,
        "meetings_with_errors": failed,
        "at": datetime.now(UTC).isoformat(),
    }
    (ATTIO_DIR / "_coverage.json").write_text(json.dumps(coverage, indent=2, default=str))
    log.info(f"Transcripts: {json.dumps(coverage, default=str)}")
    if failed:
        raise RuntimeError(f"{len(failed)} meetings not scanned: {failed[:5]}")


def export_tasks(client: AttioClient):
    ""
    log.info("Fetching tasks...")
    t0 = time.time()
    tasks = client.list_tasks()
    elapsed = time.time() - t0
    log.info(f"Fetched {len(tasks)} tasks in {elapsed:.1f}s")

    if not tasks:
        log.warning("No tasks found")
        return

    rows = []
    for task in tasks:
        task_id = task.get("id", {})
        if isinstance(task_id, dict):
            task_id = task_id.get("task_id", str(task_id))


        linked = task.get("linked_records", task.get("record_associations", []))
        linked_ids = []
        for lr in linked if isinstance(linked, list) else []:
            rid = lr.get("record_id", lr.get("target_record_id", ""))
            if rid:
                linked_ids.append(rid)


        assignees = task.get("assignees", [])
        assignee_ids = []
        for a in assignees if isinstance(assignees, list) else []:
            aid = a.get("id", a.get("workspace_member_id", ""))
            if isinstance(aid, dict):
                aid = aid.get("workspace_member_id", str(aid))
            if aid:
                assignee_ids.append(str(aid))

        rows.append(
            {
                "task_id": str(task_id),
                "content": task.get("content", task.get("title", "")),
                "is_completed": task.get("is_completed", task.get("completed", False)),
                "deadline_at": task.get("deadline_at", task.get("due_at")),
                "linked_record_ids": MULTI_SEP.join(linked_ids) if linked_ids else None,
                "assignee_ids": MULTI_SEP.join(assignee_ids) if assignee_ids else None,
                "created_at": task.get("created_at"),
            }
        )

    df = pd.DataFrame(rows)
    out = ATTIO_DIR / "tasks.parquet"
    safe_write_parquet(df, out, index=False)
    log.info(f"Saved {len(df)} tasks → {out}")


def export_metadata(client: AttioClient):
    ""
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    all_select_options = {}

    for slug in ["companies", "people", "deals"]:
        log.info(f"Fetching attributes for {slug}...")
        attrs = client.get_object_attributes(slug)
        out = METADATA_DIR / f"attributes-{slug}.json"
        out.write_text(json.dumps(attrs, indent=2, default=str))
        log.info(f"Saved {len(attrs)} attributes for {slug} → {out}")


        for attr in attrs:
            attr_slug = attr.get("api_slug", attr.get("slug", ""))
            attr_type = attr.get("type", "")
            if attr_type not in ("select", "status"):
                continue
            attr_id_obj = attr.get("id", {})
            object_id = attr_id_obj.get("object_id", "")
            attribute_id = attr_id_obj.get("attribute_id", "")
            if not object_id or not attribute_id:
                continue

            if attr_type == "status":
                options = client.get_statuses(object_id, attribute_id)
            else:
                options = client.get_select_options(object_id, attribute_id)
            time.sleep(0.2)

            if options:
                key = f"{slug}/{attr_slug}"
                all_select_options[key] = [
                    {"id": o.get("id"), "title": o.get("title", "")} for o in options
                ]
                log.info(f"  {slug}/{attr_slug}: {len(options)} options")


    out = METADATA_DIR / "select-options.json"
    out.write_text(json.dumps(all_select_options, indent=2, default=str))
    log.info(f"Saved select options for {len(all_select_options)} attributes → {out}")


    log.info("Fetching workspace members...")
    members = client.get_workspace_members()
    members_lookup = {}
    for m in members:
        mid = m.get("id", {})
        if isinstance(mid, dict):
            mid = mid.get("workspace_member_id", str(mid))
        name = m.get("name", "")
        if not name:
            first = m.get("first_name", "")
            last = m.get("last_name", "")
            name = f"{first} {last}".strip()
        email = m.get("email_address", m.get("email", ""))
        members_lookup[str(mid)] = {"name": name, "email": email}

    out = METADATA_DIR / "workspace-members.json"
    out.write_text(json.dumps(members_lookup, indent=2))
    log.info(f"Saved {len(members_lookup)} workspace members → {out}")


    deals_attrs_path = METADATA_DIR / "attributes-deals.json"
    if deals_attrs_path.exists():
        deals_attrs = json.loads(deals_attrs_path.read_text())
        stages = []
        for attr in deals_attrs:
            if attr.get("api_slug") in ("stage", "pipeline_stage") or attr.get("slug") == "stage":
                attr_id_obj = attr.get("id", {})
                object_id = attr_id_obj.get("object_id", "")
                attribute_id = attr_id_obj.get("attribute_id", "")
                if object_id and attribute_id:
                    raw_stages = client.get_statuses(object_id, attribute_id)
                    if not raw_stages:
                        raw_stages = client.get_select_options(object_id, attribute_id)
                    stages = [{"id": o.get("id"), "title": o.get("title", "")} for o in raw_stages]
                break
        out = METADATA_DIR / "deal-pipeline-stages.json"
        out.write_text(json.dumps(stages, indent=2))
        log.info(f"Saved {len(stages)} deal pipeline stages → {out}")


def export_lookups():
    ""
    LOOKUPS_DIR.mkdir(parents=True, exist_ok=True)


    companies_path = ATTIO_DIR / "companies.parquet"
    if companies_path.exists():
        df = pd.read_parquet(companies_path)
        name_col = "name" if "name" in df.columns else None
        if name_col:
            lookup = {
                str(row["record_id"]): str(row[name_col])
                for _, row in df.iterrows()
                if pd.notna(row.get("record_id")) and pd.notna(row.get(name_col))
            }
        else:
            lookup = {}
        out = LOOKUPS_DIR / "company-names.json"
        out.write_text(json.dumps(lookup, indent=2))
        log.info(f"Saved {len(lookup)} company name lookups → {out}")
    else:
        log.warning("companies.parquet not found, skipping company-names lookup")


    people_path = ATTIO_DIR / "people.parquet"
    if people_path.exists():
        df = pd.read_parquet(people_path)
        name_col = "name" if "name" in df.columns else None
        if name_col:
            name_lookup = {
                str(row["record_id"]): str(row[name_col])
                for _, row in df.iterrows()
                if pd.notna(row.get("record_id")) and pd.notna(row.get(name_col))
            }
        else:
            name_lookup = {}
        out = LOOKUPS_DIR / "people-names.json"
        out.write_text(json.dumps(name_lookup, indent=2))
        log.info(f"Saved {len(name_lookup)} people name lookups → {out}")


        email_col = "email_addresses" if "email_addresses" in df.columns else None
        if email_col:
            email_lookup = {
                str(row["record_id"]): str(row[email_col]).split(MULTI_SEP)[0]
                for _, row in df.iterrows()
                if pd.notna(row.get("record_id")) and pd.notna(row.get(email_col))
            }
        else:
            email_lookup = {}
        out = LOOKUPS_DIR / "people-emails.json"
        out.write_text(json.dumps(email_lookup, indent=2))
        log.info(f"Saved {len(email_lookup)} people email lookups → {out}")
    else:
        log.warning("people.parquet not found, skipping people lookups")




EXPORT_CHOICES = [
    "objects",
    "companies",
    "people",
    "deals",
    "lists",
    "notes",
    "meetings",
    "transcripts",
    "tasks",
    "metadata",
    "lookups",
    "all",
]


def _run_all_workspaces(choice: str) -> int:
    ""
    import subprocess

    # "tutti" is the older Italian value, still accepted.
    names = list(WORKSPACES) if choice in ("all", "tutti") else [choice]
    unknown = [n for n in names if n not in WORKSPACES]
    if unknown:
        print(f"unknown Attio workspace: {', '.join(unknown)}", file=sys.stderr)
        return 2
    argv = [
        a
        for i, a in enumerate(sys.argv[1:])
        if a != "--workspace" and sys.argv[i] != "--workspace" and not a.startswith("--workspace=")
    ]
    worst = 0
    for name_ in names:
        print(f"=== Attio workspace {WORKSPACES[name_][0]} ===", flush=True)
        env = {**os.environ, "SBK_ATTIO_WORKSPACE": name_}
        rc = subprocess.run([sys.executable, __file__, *argv], env=env).returncode
        print(f"=== Attio workspace {WORKSPACES[name_][0]}: exit {rc} ===", flush=True)
        worst = max(worst, rc)
    return worst


def main():
    parser = argparse.ArgumentParser(description="Attio CRM export — SBK")
    parser.add_argument(
        "--only",
        choices=EXPORT_CHOICES,
        help="Export only one section (default: all)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip if last run was less than 1 hour ago",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full re-download: skip time gate, re-download existing transcripts",
    )
    parser.add_argument(
        "--retry-stubs",
        action="store_true",
        help="Re-download transcripts with empty segments (Attio async processing)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel workers for the transcript scan (default {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--workspace",
        default="all",
        help="Attio workspace: 'primary' (ATTIO_API_KEY), a label of attio.extra_workspaces "
        "in sbk.config.json, or 'all' (default)",
    )
    args = parser.parse_args()

    if not os.environ.get("SBK_ATTIO_WORKSPACE"):  # unset or empty
        sys.exit(_run_all_workspaces(args.workspace))

    if args.incremental and not args.force:
        last = get_last_run(MARK_KEY)
        if last:
            from datetime import datetime

            age_hours = (datetime.now(UTC) - last.replace(tzinfo=UTC)).total_seconds() / 3600
            if age_hours < 1:
                log.info(f"Incremental: last run {age_hours:.1f}h ago (< 1h) — skipping")
                return

    ATTIO_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    api_key = get_api_key()
    client = AttioClient(api_key)

    t0 = time.time()
    section = args.only
    skip_existing = not args.force

    if section in (None, "all"):

        export_objects(client)
        export_lists(client)
        export_notes(client)
        meetings = export_meetings(client)
        export_transcripts(
            client,
            meetings,
            skip_existing=skip_existing,
            retry_stubs=args.retry_stubs,
            workers=args.workers,
        )
        export_tasks(client)
        export_metadata(client)
        export_lookups()
    elif section == "objects":
        export_objects(client)
    elif section in ("companies", "people", "deals"):
        log.info(f"Fetching {section}...")
        records = client.list_records(section)
        if records:
            df = records_to_df(records, section)
            out = ATTIO_DIR / f"{section}.parquet"
            safe_write_parquet(df, out, index=False)
            log.info(f"Saved {section} → {out}")
            raw_path = ATTIO_DIR / f"{section}-raw.json"
            raw_path.write_text(json.dumps(records, indent=2, default=str))
    elif section == "lists":
        export_lists(client)
    elif section == "notes":
        export_notes(client)
    elif section == "meetings":
        export_meetings(client)
    elif section == "transcripts":
        meetings = export_meetings(client)
        export_transcripts(
            client,
            meetings,
            skip_existing=skip_existing,
            retry_stubs=args.retry_stubs,
            workers=args.workers,
        )
    elif section == "tasks":
        export_tasks(client)
    elif section == "metadata":
        export_metadata(client)
    elif section == "lookups":
        export_lookups()

    elapsed = time.time() - t0
    log.info(f"Attio export complete in {elapsed:.1f}s")

    mark_last_run(MARK_KEY)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-attio-download", source="attio", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
