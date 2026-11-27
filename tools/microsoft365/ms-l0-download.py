#!/usr/bin/env python3
"""Microsoft 365 L0: your Outlook mail, calendar and contacts into the kernel's own slots.

Personal access only: your own app registration, per-user scopes (your own account),
the `me` endpoints.
Nothing here needs admin consent or an organization-wide permission.

Writes (no kernel file changes; the kernel L1 stages read these files as they are):
- mail     <data root>/emails/<label>/messages.parquet     -> tools/email/em-l1-enrich.py
- calendar <data root>/calendars/<label>/events.parquet    -> tools/calendar/ca-l1-extract.py
           (+ cancellati.parquet, cancelled events set aside as the Google L0 does)
- contacts <data root>/contacts/contacts.parquet           -> tools/cross-source/xs-l1-contacts-enrich.py
           (only the rows tagged microsoft365:<label> are replaced; other rows are kept)
- own      <data root>/microsoft365/<label>/state.json, download-summary.json,
           set-aside/messages-removed.parquet

Incremental:
- mail: one delta round per mail folder (GET /me/mailFolders/{id}/messages/delta); the
  deltaLink of each folder is kept in state.json. The first round reads messages received
  since --since / microsoft365.mail_history_days. Deleted or moved-out messages leave the slot.
- calendar: every run re-reads a window (from the last run minus calendar_overlap_days, or
  calendar_history_days on the first run, to calendar_future_days ahead) with calendarView,
  and replaces the rows of that window for the calendars read.
- contacts: every run re-reads the address book (it is small) and replaces this mailbox's rows.

Endpoints and facts (Microsoft Learn, checked 2026-11-25):
  https://learn.microsoft.com/en-us/graph/api/message-delta
  https://learn.microsoft.com/en-us/graph/delta-query-messages   (per-folder delta)
  https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview
  https://learn.microsoft.com/en-us/graph/api/user-list-contacts
  https://learn.microsoft.com/en-us/graph/outlook-immutable-id
  https://learn.microsoft.com/en-us/graph/throttling-limits

Setup: docs/CONNECTING.md#microsoft365. First sign-in: tools/microsoft365/ms-l0-auth.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ms_graph as mg  # noqa: E402
import ms_slots as slots  # noqa: E402

import sbk_config  # noqa: E402

log = logging.getLogger("ms365")

PARTS = ("mail", "calendar", "contacts")
DEFAULTS = {
    "mail_history_days": 365,
    "calendar_history_days": 365,
    "calendar_future_days": 90,
    "calendar_overlap_days": 14,
    "mail_headers": True,
    "page_size": 50,
}
# Folders never read: junk, trash, outbox and Outlook's system folders (well-known names,
# https://learn.microsoft.com/en-us/graph/api/resources/mailfolder).
SKIP_WELL_KNOWN = (
    "junkemail",
    "deleteditems",
    "outbox",
    "conversationhistory",
    "syncissues",
    "recoverableitemsdeletions",
    "searchfolders",
    "clutter",
)
LABELLED_WELL_KNOWN = ("inbox", "sentitems", "drafts", "archive")

MAIL_SELECT = [
    "id",
    "conversationId",
    "receivedDateTime",
    "sentDateTime",
    "from",
    "sender",
    "toRecipients",
    "ccRecipients",
    "bccRecipients",
    "subject",
    "body",
    "bodyPreview",
    "isRead",
    "isDraft",
    "categories",
    "internetMessageId",
    "hasAttachments",
    "webLink",
    "parentFolderId",
]
CONTACT_SELECT = (
    "id,displayName,givenName,surname,emailAddresses,mobilePhone,businessPhones,homePhones,"
    "companyName,jobTitle,birthday,lastModifiedDateTime"
)


def cfg(key: str):
    return sbk_config.user_cfg(f"microsoft365.{key}", DEFAULTS.get(key))


def _iso_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}") from None
    return value


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Download your own Outlook mail, calendar and contacts through Microsoft "
        "Graph into the kernel's mail, calendar and address-book slots "
        "(personal app, per-user read-only scopes for your own account; see docs/CONNECTING.md#microsoft365)."
    )
    ap.add_argument(
        "--account",
        default=None,
        help="label of the mailbox signed in with ms-l0-auth.py (default: outlook)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="every label listed in microsoft365.accounts of sbk.config.json",
    )
    ap.add_argument(
        "--only",
        action="append",
        choices=PARTS,
        help="read only this part (repeatable); default: mail, calendar and contacts",
    )
    ap.add_argument(
        "--since",
        type=_iso_date,
        help="mail and calendar start date YYYY-MM-DD (first run, or with --full)",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="forget the saved mail delta links and read every folder again",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def local_tz() -> ZoneInfo:
    name = sbk_config.user_cfg("microsoft365.timezone", "")
    if name:
        try:
            return ZoneInfo(str(name))
        except Exception:  # noqa: BLE001
            log.warning("microsoft365.timezone %r unknown, using SBK_DISPLAY_TZ", name)
    return sbk_config.DISPLAY_TZ


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since(args, days: int, now: datetime) -> datetime:
    if args.since:
        return datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    return (now - timedelta(days=int(days))).replace(hour=0, minute=0, second=0, microsecond=0)


def _read(path: Path):
    import pandas as pd

    return pd.read_parquet(path) if path.is_file() else None


def check_slots(label: str, parts: list[str]) -> None:
    """Refuse to write into a mail or calendar folder that belongs to another source."""
    accounts = mg.data_root() / "emails" / "accounts.json"
    if accounts.is_file():
        try:
            known = json.loads(accounts.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        if label in known:
            raise mg.SetupError(
                f"microsoft365: '{label}' is already a Gmail mailbox in emails/accounts.json; "
                "sign in again with another --account label"
            )
    checks = {"mail": mg.mail_slot(label), "calendar": mg.calendar_slot(label)}
    for part in parts:
        if part in checks and slots.foreign_rows(checks[part]):
            raise mg.SetupError(
                f"microsoft365: {checks[part]} already holds rows from another source; "
                "use another --account label"
            )


# --------------------------------------------------------------------------- mail


def list_mail_folders(graph: mg.Graph) -> list[dict]:
    """Every mail folder under the root except junk, trash and system folders."""
    skip, labelled = set(), {}
    for wk in SKIP_WELL_KNOWN + LABELLED_WELL_KNOWN:
        try:
            f = graph.get(f"/me/mailFolders/{wk}", params={"$select": "id"})
        except mg.GraphError as e:
            if e.status in (400, 404):
                continue  # this mailbox has no such folder
            raise
        if wk in SKIP_WELL_KNOWN:
            skip.add(f["id"])
        else:
            labelled[f["id"]] = slots.WELL_KNOWN_LABELS[wk]
    out: list[dict] = []
    seen: set[str] = set()
    sel = {"$select": "id,displayName,childFolderCount", "$top": "100"}
    queue = ["/me/mailFolders"]
    while queue:
        path = queue.pop(0)
        for page in graph.pages(path, params=sel):
            for f in page.get("value", []):
                fid = f.get("id")
                if not fid or fid in seen or fid in skip:
                    continue
                seen.add(fid)
                name = str(f.get("displayName") or "")
                out.append(
                    {
                        "id": fid,
                        "name": name,
                        "label": labelled.get(fid) or name.replace(",", " ").strip(),
                    }
                )
                if int(f.get("childFolderCount") or 0) > 0:
                    queue.append(f"/me/mailFolders/{fid}/childFolders")
    return out


def _mail_prefer(page_size: int) -> list[str]:
    return [
        f"odata.maxpagesize={int(page_size)}",
        'IdType="ImmutableId"',
        'outlook.body-content-type="text"',
    ]


def delta_round(
    graph: mg.Graph,
    folder_id: str,
    delta_link: str | None,
    since: datetime,
    headers: bool,
    page_size: int,
) -> tuple[list[dict], str]:
    """All changes of one folder since `delta_link` (or a full round). Returns (items, link)."""
    prefer = _mail_prefer(page_size)
    if delta_link:
        url, params = delta_link, None
    else:
        select = MAIL_SELECT + (["internetMessageHeaders"] if headers else [])
        url = f"/me/mailFolders/{folder_id}/messages/delta"
        params = {"$select": ",".join(select), "$filter": f"receivedDateTime ge {_iso_z(since)}"}
    items: list[dict] = []
    new_link = ""
    for page in graph.pages(url, params=params, prefer=prefer):
        items.extend(page.get("value", []))
        new_link = page.get("@odata.deltaLink") or new_link
    return items, new_link


def sync_mail(
    graph: mg.Graph, label: str, state: dict, args, now: datetime, stats: dict, pending: dict
) -> None:
    import pandas as pd

    mstate = state.setdefault("mail", {})
    fstate = mstate.setdefault("folders", {})
    headers = bool(cfg("mail_headers")) and mstate.get("headers_supported", True)
    stats["mail"]["headers"] = headers
    page_size = int(cfg("page_size"))
    since = _since(args, cfg("mail_history_days"), now)
    folders = list_mail_folders(graph)
    upserts, removed, full_rounds, partial = [], [], {}, []
    new_links = {}
    for f in folders:
        old = {} if args.full else fstate.get(f["id"], {})
        link = old.get("delta_link")
        try:
            try:
                try:
                    items, new_link = delta_round(graph, f["id"], link, since, headers, page_size)
                except mg.DeltaReset:
                    stats["mail"]["delta_resets"] += 1
                    link = None
                    items, new_link = delta_round(graph, f["id"], None, since, headers, page_size)
            except mg.GraphError as e:
                if headers and not link and e.status == 400:
                    # Some mailboxes refuse internetMessageHeaders in delta: go on without them.
                    headers = False
                    mstate["headers_supported"] = False
                    stats["mail"]["headers"] = False
                    items, new_link = delta_round(graph, f["id"], None, since, False, page_size)
                else:
                    raise
        except mg.GraphError as e:
            if e.status not in (403, 404):
                raise
            # One folder gone or refused since it was listed: skip it this run, keep its
            # saved link and its rows, and read the other folders.
            stats["mail"].setdefault("folders_skipped", []).append(
                f"{f['name']}: HTTP {e.status} {e.code}"
            )
            log.warning("mail folder %r skipped: HTTP %s %s", f["name"], e.status, e.code)
            if f["id"] in fstate:
                new_links[f["id"]] = fstate[f["id"]]
            continue
        if not link:
            full_rounds[f["id"]] = {
                it["id"] for it in items if "@removed" not in it and it.get("id")
            }
        for it in items:
            if not it.get("id"):
                continue
            if "@removed" in it:
                removed.append((f["id"], it["id"]))
                continue
            if slots.is_partial(it):
                partial.append((f["id"], f["label"], it))
                continue
            upserts.append(slots.message_row(it, f["id"], f["label"]))
        stats["mail"]["changed"] += sum(1 for it in items if "@removed" not in it)
        stats["mail"]["removed"] += sum(1 for it in items if "@removed" in it)
        new_links[f["id"]] = {
            "delta_link": new_link,
            "name": f["name"],
            "label": f["label"],
            "last_sync": now.isoformat(timespec="seconds"),
        }
    existing = _read(mg.mail_slot(label))
    if existing is not None and len(existing):
        listed = {f["id"] for f in folders}
        fid = existing.get("folder_id", pd.Series([""] * len(existing))).astype(str)
        ids = existing["id"].astype(str)
        dates = pd.to_datetime(existing["date"], utc=True, errors="coerce")
        for i, (folder, mid) in enumerate(zip(fid, ids, strict=False)):
            if folder not in listed:
                removed.append((folder, mid))  # folder deleted or now excluded
            elif folder in full_rounds and mid not in full_rounds[folder]:
                d = dates.iloc[i]
                if pd.isna(d) or d >= since:
                    removed.append((folder, mid))  # gone since the last round
    if partial:
        # Updates that came back with only some properties patch the row already known
        # (from this round or from the slot); one never seen before is not written blank.
        wanted = {str(it["id"]) for _f, _l, it in partial}
        known = {}
        if existing is not None and len(existing):
            hit = existing[existing["id"].astype(str).isin(wanted)]
            known = {str(r["id"]): r for r in hit.to_dict("records")}
        known.update({u["id"]: u for u in upserts if u["id"] in wanted})
        skipped = 0
        for fid_, flabel, it in partial:
            old = known.get(str(it["id"]))
            if old is None:
                skipped += 1
                continue
            row = slots.patch_message(old, it, fid_, flabel)
            known[row["id"]] = row
            upserts.append(row)
        stats["mail"]["partial_patched"] = len(partial) - skipped
        stats["mail"]["partial_skipped"] = skipped
    merged, aside = slots.merge_messages(existing, upserts, removed)
    stats["mail"].update(
        folders=len(folders),
        rows_in_slot=int(len(merged)),
        set_aside=int(len(aside)),
        since=since.date().isoformat(),
    )
    pending["mail"] = (merged, aside, new_links)


def commit_mail(label: str, state: dict, pending: dict) -> None:
    import pandas as pd

    merged, aside, new_links = pending["mail"]
    sbk_config.safe_write_parquet(merged, mg.mail_slot(label), index=False)
    if len(aside):
        p = mg.plugin_dir(label) / "set-aside" / "messages-removed.parquet"
        old = _read(p)
        if old is not None and len(old):
            aside = pd.concat([old[~old["id"].isin(set(aside["id"]))], aside], ignore_index=True)
        sbk_config.safe_write_parquet(aside, p, index=False)
    state["mail"]["folders"] = new_links


# --------------------------------------------------------------------------- calendar


def own_calendar(c: dict, mine: str) -> bool:
    """Only calendars of your own mailbox: Calendars.Read covers "events in user calendars",
    not calendars other people share with you (Graph permissions reference). canShare is
    true only for the user who created the calendar (calendar resource); it also covers
    personal accounts, whose calendar owner address can differ from the sign-in address."""
    if c.get("isSharedWithMe"):
        return False
    if c.get("isDefaultCalendar") or c.get("canShare"):
        return True
    owner = ((c.get("owner") or {}).get("address") or "").lower()
    return not owner or owner == mine


def sync_calendar(
    graph: mg.Graph,
    label: str,
    me: dict,
    state: dict,
    args,
    now: datetime,
    stats: dict,
    pending: dict,
) -> None:
    cstate = state.setdefault("calendar", {})
    if args.since:
        start = _since(args, 0, now)
    elif cstate.get("last_run") and not args.full:
        last = datetime.fromisoformat(cstate["last_run"])
        start = (last - timedelta(days=int(cfg("calendar_overlap_days")))).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        start = _since(args, cfg("calendar_history_days"), now)
    end = now + timedelta(days=int(cfg("calendar_future_days")))
    mine = (me.get("email") or "").lower()
    calendars = []
    for page in graph.pages("/me/calendars", params={"$top": "100"}):
        calendars.extend(c for c in page.get("value", []) if own_calendar(c, mine))
    tz = local_tz()
    fresh = []
    read_ids: set[str] = set()
    prefer = ['outlook.timezone="UTC"', 'IdType="ImmutableId"']
    for c in calendars:
        params = {
            "startDateTime": _iso_z(start),
            "endDateTime": _iso_z(end),
            "$top": str(int(cfg("page_size"))),
        }
        rows = []
        try:
            for page in graph.pages(
                f"/me/calendars/{c['id']}/calendarView", params=params, prefer=prefer
            ):
                rows.extend(slots.event_row(ev, c, tz) for ev in page.get("value", []))
        except mg.GraphError as e:
            if e.status not in (403, 404):
                raise
            # This calendar only: its rows stay as they are, the others are still read.
            stats["calendar"].setdefault("calendars_skipped", []).append(
                f"{c.get('name', '')}: HTTP {e.status} {e.code}"
            )
            log.warning("calendar %r skipped: HTTP %s %s", c.get("name"), e.status, e.code)
            continue
        fresh.extend(rows)
        read_ids.add(c["id"])
    existing = _read(mg.calendar_slot(label))
    merged, cancelled = slots.merge_events(existing, fresh, read_ids, start, end)
    stats["calendar"].update(
        calendars=len(read_ids),
        events_read=len(fresh),
        rows_in_slot=int(len(merged)),
        cancelled_aside=int(len(cancelled)),
        window=[start.date().isoformat(), end.date().isoformat()],
    )
    pending["calendar"] = (merged, cancelled, now.isoformat(timespec="seconds"))


def commit_calendar(label: str, state: dict, pending: dict) -> None:
    import pandas as pd

    merged, cancelled, last_run = pending["calendar"]
    slot = mg.calendar_slot(label)
    sbk_config.safe_write_parquet(merged, slot, index=False)
    if len(cancelled):
        p = slot.parent / "cancellati.parquet"
        old = _read(p)
        if old is not None and len(old):
            cancelled = pd.concat(
                [old[~old["id"].isin(set(cancelled["id"]))], cancelled], ignore_index=True
            )
        sbk_config.safe_write_parquet(cancelled.reset_index(drop=True), p, index=False)
    state.setdefault("calendar", {})["last_run"] = last_run


# --------------------------------------------------------------------------- contacts


def sync_contacts(graph: mg.Graph, label: str, stats: dict, pending: dict) -> None:
    rows = []
    paths = ["/me/contacts"]
    for page in graph.pages("/me/contactFolders", params={"$top": "100"}):
        paths += [
            f"/me/contactFolders/{f['id']}/contacts" for f in page.get("value", []) if f.get("id")
        ]
    for path in paths:
        params = {"$select": CONTACT_SELECT, "$top": "100"}
        for page in graph.pages(path, params=params, prefer=['IdType="ImmutableId"']):
            rows.extend(slots.contact_row(c, label) for c in page.get("value", []))
    slot = mg.contacts_slot()
    existing = _read(slot)
    seeded = 0
    if slots.plugin_only(existing):
        # The parquet exists only because of this plugin: mirror the iPhone JSON the kernel
        # would otherwise read as the address book, as it is now (new contacts included).
        # Without the JSON, seed rows already there are kept.
        for jp in mg.iphone_json_paths():
            if jp.is_file():
                seed = slots.seed_from_iphone_json(jp)
                existing = slots.replace_seed(existing, seed)
                seeded = len(seed)
                break
    merged = slots.merge_contacts(existing, rows, label)
    ours = int((merged["source"] == f"{slots.SOURCE}:{label}").sum()) if len(merged) else 0
    stats["contacts"].update(
        folders=len(paths),
        contacts_read=len(rows),
        rows_ours=ours,
        rows_total=int(len(merged)),
        seeded_from_iphone_json=seeded,
    )
    pending["contacts"] = merged


def commit_contacts(pending: dict) -> None:
    sbk_config.safe_write_parquet(pending["contacts"], mg.contacts_slot(), index=False)


# --------------------------------------------------------------------------- main


def run_one(label: str, args, http=None, sleep=None, now: datetime | None = None) -> dict:
    label = mg.check_label(label)
    parts = list(args.only or PARTS)
    check_slots(label, parts)
    http = http or mg.Http()
    tp = mg.TokenProvider(label, http)
    graph = mg.Graph(tp, http, sleep=sleep) if sleep else mg.Graph(tp, http)
    now = now or datetime.now(UTC)
    me = mg.whoami(graph)
    state = mg.load_state(label)
    stats = {
        "plugin": mg.PLUGIN_ID,
        "label": label,
        "account": me.get("email", ""),
        "started": now.isoformat(timespec="seconds"),
        "parts": parts,
        "mail": {
            "changed": 0,
            "removed": 0,
            "delta_resets": 0,
            "headers": bool(cfg("mail_headers")),
        },
        "calendar": {},
        "contacts": {},
        "errors": [],
    }
    pending: dict = {}
    steps = {
        "mail": lambda: sync_mail(graph, label, state, args, now, stats, pending),
        "calendar": lambda: sync_calendar(graph, label, me, state, args, now, stats, pending),
        "contacts": lambda: sync_contacts(graph, label, stats, pending),
    }
    for part in parts:
        try:
            steps[part]()
        except mg.GraphError as e:
            hint = " (scope not granted?)" if e.status == 403 else ""
            stats["errors"].append(f"{part}: HTTP {e.status} {e.code}{hint}")
            log.error("%s: %s", part, e)
    # Data first, then the state that points past it: a crash in between only re-reads.
    if "mail" in pending:
        commit_mail(label, state, pending)
    if "calendar" in pending:
        commit_calendar(label, state, pending)
    if "contacts" in pending:
        commit_contacts(pending)
    state["last_run"] = now.isoformat(timespec="seconds")
    mg.save_state(label, state)
    stats.update(
        requests=graph.requests,
        throttled=graph.throttled,
        finished=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    sp = mg.summary_path(label)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    return stats


def _line(s: dict) -> str:
    bits = [f"microsoft365/{s['label']}"]
    if s["mail"].get("folders") is not None:
        bits.append(
            f"mail {s['mail']['changed']} new/changed, {s['mail']['removed']} removed, "
            f"{s['mail'].get('rows_in_slot', 0)} in slot"
        )
    if "events_read" in s["calendar"]:
        bits.append(f"calendar {s['calendar']['events_read']} events read")
    if "contacts_read" in s["contacts"]:
        bits.append(f"contacts {s['contacts']['contacts_read']}")
    skipped = s["mail"].get("folders_skipped", []) + s["calendar"].get("calendars_skipped", [])
    if skipped:
        bits.append(f"skipped: {'; '.join(skipped)}")
    if s["errors"]:
        bits.append(f"errors: {'; '.join(s['errors'])}")
    return " | ".join(bits)


def main(argv=None, http=None, sleep=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )
    if args.all:
        labels = list(sbk_config.user_cfg("microsoft365.accounts", []) or [])
        if not labels:
            raise mg.SetupError(
                "microsoft365: --all needs microsoft365.accounts in sbk.config.json"
            )
    else:
        labels = [args.account or sbk_config.user_cfg("microsoft365.default_account", "outlook")]
    failed = 0
    for label in labels:
        if not args.all:
            s = run_one(label, args, http=http, sleep=sleep)
        else:
            # With --all one mailbox whose sign-in expired must not stop the others.
            try:
                s = run_one(label, args, http=http, sleep=sleep)
            except (mg.SetupError, mg.TokenError) as e:
                print(mg.one_line(e), file=sys.stderr)
                failed += 1
                continue
        print(_line(s))
        failed += bool(s["errors"])
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (mg.SetupError, mg.TokenError, mg.GraphError, mg.DeltaReset) as e:
        print(mg.one_line(e), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print(
            "microsoft365: interrupted, nothing committed for the part in progress", file=sys.stderr
        )
        sys.exit(130)
