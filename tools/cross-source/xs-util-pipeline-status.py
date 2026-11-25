#!/usr/bin/env python3
""










import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sbk_config import DATA_ROOT, calendar_labels, get_last_run, mail_labels, safe_write_json, user_cfg




SBK_DATA = DATA_ROOT
STATE_FILE = SBK_DATA / "pipeline-status.json"
# Google Sheet that --push writes to: pipeline_status.spreadsheet_id in sbk.config.json.
SPREADSHEET_ID = str(user_cfg("pipeline_status.spreadsheet_id", "") or "").strip()
SHEET_NAME = "Pipeline Master"
TOKEN_PATH = Path(
    os.environ.get(
        "GOOGLE_SHEETS_TOKEN_PATH", str(Path.home() / ".secrets/google-oauth/sheets_token.json")
    )
)
CLIENT_SECRET = Path(
    os.environ.get(
        "GOOGLE_OAUTH_CLIENT_SECRET_PATH",
        str(Path.home() / ".secrets/google-oauth/client_secret.json"),
    )
)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TOOLS_DIR = Path(__file__).resolve().parent.parent

NOW = datetime.now()





def _mtime(path: Path) -> datetime | None:
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime)
    return None


def _size_mb(path: Path) -> float:
    if path.is_file():
        return round(path.stat().st_size / 1048576, 2)
    if path.is_dir():
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return round(total / 1048576, 2)
    return 0


def _pq_count(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq



        if Path(path).is_dir():
            return len(pq.read_table(str(path)))
        return pq.read_metadata(str(path)).num_rows
    except Exception:
        return None


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _hours_ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    h = round((NOW - dt).total_seconds() / 3600, 1)
    return str(h)


def _righe_json(path) -> int:
    ""


    try:
        import json as _json

        d = _json.loads(Path(path).read_text(encoding="utf-8"))
        return len(d) if isinstance(d, list) else len(d.get("data", []) or [])
    except Exception:
        return 0


def _best_time(file_mt: datetime | None, source_key: str) -> datetime | None:
    ""




    lr = get_last_run(source_key)
    if file_mt and lr:
        return max(file_mt, lr)
    return lr or file_mt


def _status(dt: datetime | None, threshold_h: float = 48) -> str:
    if dt is None:
        return "Missing"
    h = (NOW - dt).total_seconds() / 3600
    if h < threshold_h:
        return "OK"
    return "Stale"






HEADER = [
    "Status",
    "ID",
    "Age h",
    "Source / Stage",
    "Type",
    "Connection",
    "Auth",
    "In L3 NLP",
    "In L5 Vector",
    "Freq target",
    "Records",
    "Last run",
    "Action link",
    "Script",
    "Run command",
    "Cost/run",
    "Size MB",
    "Depth",
    "%",
    "Gap",
]


def _row(
    id_,
    name,
    script,
    cmd,
    tipo,
    conn,
    auth,
    link,
    freq,
    cost,
    records,
    size_mb,
    depth,
    in_l3,
    in_l5,
    pct,
    stato,
    last_run,
    eta_h,
    gap,
):
    return [
        str(stato),
        str(id_),
        str(eta_h),
        str(name),
        str(tipo),
        str(conn),
        str(auth),
        str(in_l3),
        str(in_l5),
        str(freq),
        str(records) if records not in (None, "") else "",
        str(last_run),
        str(link),
        str(script),
        str(cmd),
        str(cost),
        str(size_mb) if size_mb not in (None, 0, "") else "",
        str(depth),
        str(pct),
        str(gap),
    ]


def _section_header(label):
    ""
    r = [""] * len(HEADER)
    r[0] = f"▸ {label}"
    return r


def build_table() -> list[list[str]]:
    rows: list[list[str]] = [HEADER]




    rows.append(_section_header("L0 — INGEST (download raw data)"))


    # Your mailboxes: emails/accounts.json, email_accounts in sbk.config.json, emails/<label>/.
    email_accts = mail_labels()
    for i, acct in enumerate(email_accts, 1):
        f = SBK_DATA / f"emails/{acct}/messages.parquet"
        mt = _best_time(_mtime(f), f"email-{acct}")
        cnt = _pq_count(f)
        sz = _size_mb(f)
        rows.append(
            _row(
                f"L0.1{chr(96 + i)}",
                f"Email {acct}",
                "em-l0-download.py",
                f"uv run python3 tools/email/em-l0-download.py --account {acct}",
                "Auto",
                "API Gmail IMAP",
                "OAuth Refresh",
                "https://mail.google.com",
                "real-time (IMAP IDLE) / 1d batch",
                "0",
                cnt,
                sz,
                "Full (downloads header + body)",
                "No",
                "Yes",
                "100%",
                _status(mt, 48),
                _fmt_dt(mt),
                _hours_ago(mt),
                "" if _status(mt, 48) == "OK" else f"Stale {_hours_ago(mt)}h",
            )
        )


    # Your calendar accounts: calendars/<label>/events.parquet and your mailbox labels.
    cal_accts = calendar_labels()
    for i, acct in enumerate(cal_accts, 1):
        f = SBK_DATA / f"calendars/{acct}/events.parquet"
        mt = _best_time(_mtime(f), f"calendar-{acct}")
        cnt = _pq_count(f)
        sz = _size_mb(f)
        rows.append(
            _row(
                f"L0.2{chr(96 + i)}",
                f"Calendar {acct}",
                "ca-l0-download.py",
                "uv run python3 tools/calendar/ca-l0-download.py",
                "Auto",
                "API Google Calendar",
                "OAuth Refresh",
                "https://calendar.google.com",
                "every 15 min (via brief)",
                "0",
                cnt,
                sz,
                "Full (all event fields)",
                "No",
                "Yes (via calendar chunks)",
                "100%",
                _status(mt, 48),
                _fmt_dt(mt),
                _hours_ago(mt),
                "Sparse" if cnt and cnt < 100 else "",
            )
        )


    sl_conv = SBK_DATA / "slack/conversations"
    sl_conv_count = len(list(sl_conv.glob("*.json"))) if sl_conv.exists() else 0
    sl_conv_sz = _size_mb(sl_conv)
    sl_conv_mt = _mtime(sl_conv)

    sl_l1_mt = _mtime(SBK_DATA / "slack/processed/interactions-slack.parquet")
    best_sl_mt = _best_time(sl_l1_mt or sl_conv_mt, "slack-channels")
    rows.append(
        _row(
            "L0.3",
            f"Slack Channels ({sl_conv_count})",
            "sl-l0-download.py",
            "uv run python3 tools/slack/sl-l0-download.py",
            "Auto",
            "API Slack",
            "Personal app user token",
            "https://app.slack.com",
            "real-time (Socket Mode) / 1d batch",
            "0",
            sl_conv_count,
            sl_conv_sz,
            "Full (downloads all messages)",
            "Yes (6 sources of 20)",
            "Yes",
            "100%",
            _status(best_sl_mt, 48),
            _fmt_dt(best_sl_mt),
            _hours_ago(best_sl_mt),
            "",
        )
    )


    sl_dm = SBK_DATA / "slack/dm"
    sl_dm_count = len(list(sl_dm.glob("*.json"))) if sl_dm.exists() else 0
    sl_dm_sz = _size_mb(sl_dm)
    sl_dm_mt = _best_time(_mtime(sl_dm), "slack-dm")
    rows.append(
        _row(
            "L0.4",
            f"Slack DM ({sl_dm_count})",
            "sl-l0-download-dm.py",
            "uv run python3 tools/slack/sl-l0-download-dm.py",
            "Auto",
            "API Slack (search.messages)",
            "Personal app user token",
            "https://app.slack.com",
            "1d batch",
            "0",
            sl_dm_count,
            sl_dm_sz,
            "Full (downloads all DMs)",
            "No",
            "No",
            "100%",
            _status(sl_dm_mt, 48),
            _fmt_dt(sl_dm_mt),
            _hours_ago(sl_dm_mt),
            "Not in L3 NLP, not in L5 Vector",
        )
    )


    attio_sources = [
        ("L0.5", "Attio People", "people.parquet", "1w"),
        ("L0.6", "Attio Companies", "companies.parquet", "1w"),
        ("L0.7", "Attio Deals", "deals.parquet", "1w"),
        ("L0.8", "Attio Notes (LinkedIn msg)", "notes.parquet", "1d"),
        ("L0.9", "Attio Call Recordings", "call-recordings.parquet", "1d"),
        ("L0.10", "Attio Meetings", "meetings.parquet", "1w"),
        ("L0.11", "Attio Tasks", "tasks.parquet", "1w"),
        # Custom Attio lists are user-defined; load names from config. Demo names below.
        ("L0.12", "Attio List A", "list-a.parquet", "1w"),
        ("L0.13", "Attio List B", "list-b.parquet", "1w"),
        ("L0.14", "Attio List C", "list-c.parquet", "1w"),
        (
            "L0.15",
            "Attio List D",
            "list-d.parquet",
            "1w",
        ),
        (
            "L0.16",
            "Attio List E",
            "list-e.parquet",
            "1w",
        ),
    ]
    for id_, name, fname, freq in attio_sources:
        f = SBK_DATA / f"attio/{fname}"
        mt = _best_time(_mtime(f), "attio")
        cnt = _pq_count(f)
        sz = _size_mb(f)
        is_calls = "Call" in name or "Meeting" in name
        in_l3 = "Yes" if is_calls or "Notes" in name else "No"
        in_l5 = "Yes" if "Notes" in name or is_calls else "Yes"
        rows.append(
            _row(
                id_,
                name,
                "at-l0-download.py (L0) + at-l1-enrich.py (L1)",
                "uv run python3 tools/attio/at-l1-enrich.py",
                "Auto",
                "API Attio v2",
                "Permanent API Key",
                "https://app.attio.com",
                freq,
                "0",
                cnt,
                sz,
                "Full (all record attributes)",
                in_l3,
                in_l5,
                "100%",
                _status(mt, 96),
                _fmt_dt(mt),
                _hours_ago(mt),
                "L0 and L1 in the same script, to be separated",
            )
        )


    at_tr = SBK_DATA / "attio/processed/transcripts-index.parquet"
    mt = _best_time(_mtime(at_tr), "attio-transcripts")
    cnt = _pq_count(at_tr)
    rows.append(
        _row(
            "L0.9b",
            "Attio Call Transcripts",
            "at-util-transcripts.py",
            "uv run python3 tools/attio/at-util-transcripts.py",
            "Auto",
            "API Attio v2",
            "Permanent API Key",
            "https://app.attio.com",
            "1d",
            "0",
            cnt,
            _size_mb(at_tr) if at_tr.exists() else "",
            "Full (full transcript)",
            "Yes",
            "Yes",
            "100%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )






    pe_f = SBK_DATA / "personio/personio-index.json"
    if not pe_f.exists():
        pe_f = SBK_DATA / "personio/employees-raw.json"
    mt = _best_time(_mtime(pe_f), "personio")
    sz = _size_mb(SBK_DATA / "personio") if (SBK_DATA / "personio").exists() else 0
    rows.append(
        _row(
            "L0.17",
            "Personio HR (employees)",
            "pe-l0-download.py",
            "uv run python3 tools/personio/pe-l0-download.py",
            "Auto",
            "API Personio REST v1",
            "Permanent credentials (client_id+secret)",
            "https://api.personio.de",
            "1w",
            "0",
            _righe_json(SBK_DATA / "personio/employees-flat.json"),
            sz,
            "Full (all employee fields)",
            "No",
            "No",
            "100%",
            _status(mt, 168),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    no_pages = SBK_DATA / "notion/pages"
    no_blocks = SBK_DATA / "notion/blocks"
    mt = _best_time(_mtime(SBK_DATA / "notion/download-summary.json"), "notion")
    pages_count = len(list(no_pages.iterdir())) if no_pages.exists() else 0
    sz = _size_mb(SBK_DATA / "notion") if (SBK_DATA / "notion").exists() else 0
    rows.append(
        _row(
            "L0.18",
            f"Notion ({pages_count} pages)",
            "no-l0-download.py",
            "uv run python3 tools/notion/no-l0-download.py",
            "Auto",
            "API Notion v1",
            "Permanent API Key (integration token)",
            "https://www.notion.so",
            "1w",
            "0",
            pages_count,
            sz,
            "Full (pages + blocks + databases)",
            "No",
            "Yes",
            "100%",
            _status(mt, 168),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    gd_f = SBK_DATA / "gdrive/index-owned.json"
    mt = _best_time(_mtime(gd_f), "gdrive")
    gd_proc = SBK_DATA / "gdrive/processed/documents.parquet"
    cnt = _pq_count(gd_proc) if gd_proc.exists() else None
    sz = _size_mb(SBK_DATA / "gdrive") if (SBK_DATA / "gdrive").exists() else 0
    rows.append(
        _row(
            "L0.19",
            "Google Drive",
            "gd-l0-download.py",
            "uv run python3 tools/gdrive/gd-l0-download.py",
            "Auto",
            "API Google Drive",
            "OAuth Refresh",
            "https://drive.google.com",
            "on-demand",
            "0",
            cnt,
            sz,
            "Part (metadata + some file content)",
            "No",
            "Yes",
            "100%",
            _status(mt, 168),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    pl_raw = SBK_DATA / "plaud/raw"
    pl_count = len(list(pl_raw.glob("*.json"))) if pl_raw.exists() else 0
    pl_mt = _best_time(_mtime(pl_raw), "plaud")
    pl_sz = _size_mb(pl_raw) + _size_mb(SBK_DATA / "plaud/pdfs")
    rows.append(
        _row(
            "L0.20",
            f"Plaud ({pl_count // 2} recordings)",
            "pl-l0-download.py",
            "uv run python3 tools/plaud/pl-l0-download.py",
            "Browser",
            "API download",
            "Browser session (cookie)",
            "https://app.plaud.ai",
            "on-demand",
            "0",
            pl_count // 2 if pl_count else 0,
            pl_sz,
            "Full (audio + full transcript)",
            "Yes",
            "Yes",
            "100%",
            _status(pl_mt, 168),
            _fmt_dt(pl_mt),
            _hours_ago(pl_mt),
            "Requires Plaud browser login",
        )
    )


    tq_raw = SBK_DATA / "tactiq/raw"
    tq_count = len(list(tq_raw.glob("*.json"))) if tq_raw.exists() else 0
    tq_mt = _best_time(_mtime(tq_raw), "tactiq")
    tq_sz = _size_mb(tq_raw)
    rows.append(
        _row(
            "L0.21",
            f"Tactiq ({tq_count // 2} meetings)",
            "tq-l0-download.py",
            "uv run python3 tools/tactiq/tq-l0-download.py",
            "Browser",
            "API Tactiq",
            "Permanent API Key",
            "https://app.tactiq.io",
            "on-demand",
            "0",
            tq_count // 2 if tq_count else 0,
            tq_sz,
            "Full (full meeting transcript)",
            "Yes",
            "Yes",
            "100%",
            _status(tq_mt, 168),
            _fmt_dt(tq_mt),
            _hours_ago(tq_mt),
            "",
        )
    )


    LI_RAW = TOOLS_DIR.parent / "sbk/raw/linkedin"
    LI_INV_RAW = TOOLS_DIR.parent / "sbk/raw/linkedin-investors"


    li_threads = LI_RAW / "linkedin-threads-complete.json"
    li_threads_mt = _best_time(_mtime(li_threads), "linkedin-threads")
    li_threads_sz = _size_mb(li_threads)
    li_threads_cnt = None
    if li_threads.exists():
        try:
            import json as _json

            with open(li_threads) as _f:
                _d = _json.load(_f)
            li_threads_cnt = len(_d.get("conversations", []))
        except Exception:
            pass
    rows.append(
        _row(
            "L0.22a",
            f"LinkedIn Connections ({li_threads_cnt or '?'} conv)",
            "li-l0-scraper.js",
            "node sbk/raw/linkedin/scripts/fetch-all-threads-complete.js",
            "Browser",
            "LinkedIn Voyager API",
            "Cookie li_at + JSESSIONID",
            "https://www.linkedin.com/messaging/",
            "weekly",
            "0",
            li_threads_cnt,
            li_threads_sz,
            "Full (full conversations with message bodies)",
            "No",
            "No",
            "100%",
            _status(li_threads_mt, 168),
            _fmt_dt(li_threads_mt),
            _hours_ago(li_threads_mt),
            "",
        )
    )


    li_int_f = SBK_DATA / "linkedin/processed/interactions-linkedin.parquet"
    li_int_mt = _best_time(_mtime(li_int_f), "linkedin-messages")
    li_int_cnt = _pq_count(li_int_f)

    li_std_msg = None
    if li_int_f.exists():
        try:
            import pyarrow.parquet as _pq

            _t = _pq.read_table(str(li_int_f))
            _df = _t.to_pandas()
            li_std_msg = int((_df["source"] == "threads-complete").sum())
        except Exception:
            pass
    rows.append(
        _row(
            "L0.22b",
            f"LinkedIn Messages std ({li_std_msg or '?'} msg)",
            "li-l1-enrich.py",
            "uv run python3 tools/linkedin/li-l1-enrich.py",
            "Derived (from L0.22a)",
            "Parsing JSON",
            "—",
            "",
            "post-L0.22a",
            "0",
            li_std_msg,
            "",
            "META — body_length saved, raw text NOT persisted in parquet",
            "No",
            "No",
            "100%",
            _status(li_int_mt, 168),
            _fmt_dt(li_int_mt),
            _hours_ago(li_int_mt),
            "Message text not in parquet (only body_length)",
        )
    )


    li_sn = LI_RAW / "linkedin-threads-sales-navigator.json"
    li_sn_mt = _best_time(_mtime(li_sn), "linkedin-salesnav")
    li_sn_sz = _size_mb(li_sn)
    li_sn_cnt = None
    li_sn_msg = None
    if li_sn.exists():
        try:
            with open(li_sn) as _f:
                _d = _json.load(_f)
            li_sn_cnt = len(_d.get("conversations", []))
        except Exception:
            pass
    if li_int_f.exists():
        try:
            _t = _pq.read_table(str(li_int_f))
            _df = _t.to_pandas()
            li_sn_msg = int((_df["source"] == "sales-navigator").sum())
        except Exception:
            pass
    rows.append(
        _row(
            "L0.22c",
            f"LinkedIn Sales Navigator ({li_sn_cnt or '?'} conv, {li_sn_msg or '?'} msg)",
            "fetch-sales-navigator-inbox.js",
            "node sbk/raw/linkedin/scripts/fetch-sales-navigator-inbox.js",
            "Browser",
            "Sales Navigator API",
            "Cookie li_at + JSESSIONID",
            "https://www.linkedin.com/sales/inbox/",
            "weekly",
            "0",
            li_sn_cnt,
            li_sn_sz,
            "Full (SalesNav conv with body, structure different from standard)",
            "No",
            "No",
            "100%",
            _status(li_sn_mt, 168),
            _fmt_dt(li_sn_mt),
            _hours_ago(li_sn_mt),
            "SalesNav contacts without standard linkedin_url",
        )
    )


    li_notes = LI_RAW / "linkedin-sent-notes.json"
    li_notes_mt = _best_time(_mtime(li_notes), "linkedin-notes")
    li_notes_sz = _size_mb(li_notes)
    li_notes_cnt = None
    if li_notes.exists():
        try:
            with open(li_notes) as _f:
                _d = _json.load(_f)

            if isinstance(_d, list):
                li_notes_cnt = len(_d)
            elif isinstance(_d, dict):
                li_notes_cnt = len(_d.get("sentMessages", _d.get("conversations", [])))
        except Exception:
            pass
    rows.append(
        _row(
            "L0.22d",
            f"LinkedIn Sent Notes ({li_notes_cnt or '?'} notes)",
            "li-l0-scraper.js",
            "node sbk/raw/linkedin/scripts/fetch-sent-notes.js",
            "Browser",
            "LinkedIn Voyager API",
            "Cookie li_at + JSESSIONID",
            "",
            "monthly",
            "0",
            li_notes_cnt,
            li_notes_sz,
            "Full (connection invite note text)",
            "No",
            "No",
            "100%",
            _status(li_notes_mt, 720),
            _fmt_dt(li_notes_mt),
            _hours_ago(li_notes_mt),
            "",
        )
    )


    li_inv = LI_INV_RAW / "external-contacts.json"
    li_inv_mt = _best_time(_mtime(li_inv), "linkedin-external")
    li_inv_sz = _size_mb(LI_INV_RAW) if LI_INV_RAW.exists() else 0
    li_inv_cnt = None
    if li_inv.exists():
        try:
            with open(li_inv) as _f:
                _d = _json.load(_f)
            li_inv_cnt = len(_d.get("records", []))
        except Exception:
            pass
    rows.append(
        _row(
            "L0.22e",
            f"External contacts ({li_inv_cnt or '?'} profiles)",
            "(optional external source)",
            "—",
            "Browser",
            "External API",
            "Cookie session",
            "https://example.com",
            "on-demand",
            "0",
            li_inv_cnt,
            li_inv_sz,
            "Full (bio, company, role, location)",
            "No",
            "No",
            "100%",
            _status(li_inv_mt, 720),
            _fmt_dt(li_inv_mt),
            _hours_ago(li_inv_mt),
            "",
        )
    )


    LI_EXPORT_RAW = SBK_DATA / "linkedin/raw"
    li_exp_conn = LI_EXPORT_RAW / "export-connections.parquet"
    li_exp_inv = LI_EXPORT_RAW / "export-invitations.parquet"
    li_exp_conn_mt = _best_time(_mtime(li_exp_conn), "linkedin-export")
    li_exp_conn_cnt = _pq_count(li_exp_conn)
    li_exp_inv_cnt = _pq_count(li_exp_inv)
    li_exp_sz = sum(
        _size_mb(LI_EXPORT_RAW / f)
        for f in [
            "export-connections.parquet",
            "export-invitations.parquet",
            "export-endorsements-received.parquet",
            "export-endorsements-given.parquet",
            "export-company-follows.parquet",
        ]
        if (LI_EXPORT_RAW / f).exists()
    )
    rows.append(
        _row(
            "L0.22f",
            f"LinkedIn Export ({li_exp_conn_cnt or '?'} conn, {li_exp_inv_cnt or '?'} inv)",
            "li-l0-import-export.py",
            "uv run python3 tools/linkedin/li-l0-import-export.py",
            "Rare",
            "LinkedIn GDPR Export",
            "Download request from Settings",
            "https://www.linkedin.com/mypreferences/d/download-my-data",
            "on-demand",
            "0",
            (li_exp_conn_cnt or 0) + (li_exp_inv_cnt or 0),
            li_exp_sz,
            "Full (connections+email, invitations+msg, endorsements, companies)",
            "No",
            "No",
            "100%",
            _status(li_exp_conn_mt, 720),
            _fmt_dt(li_exp_conn_mt),
            _hours_ago(li_exp_conn_mt),
            "",
        )
    )


    wa_chats = SBK_DATA / "whatsapp"
    wa_proc = SBK_DATA / "whatsapp/processed"
    wa_mt = _best_time(
        _mtime(wa_proc / "interactions-whatsapp.parquet") if wa_proc.exists() else None, "whatsapp"
    )
    wa_cnt = (
        _pq_count(wa_proc / "interactions-whatsapp.parquet")
        if (wa_proc / "interactions-whatsapp.parquet").exists()
        else None
    )
    wa_chat_count = (
        _pq_count(wa_proc / "chats-activity.parquet")
        if (wa_proc / "chats-activity.parquet").exists()
        else 0
    )
    wa_sz = _size_mb(wa_chats)
    rows.append(
        _row(
            "L0.23",
            f"WhatsApp ({wa_chat_count} chat)",
            "wa-l0l3-full.py",
            "uv run python3 tools/whatsapp/wa-l0l3-full.py",
            "Rare",
            "Export file",
            "Manual export",
            "(On your phone: WhatsApp > the chat > Export chat)",
            "on-demand",
            "0",
            wa_cnt,
            wa_sz,
            "Full (complete messages with media)",
            "Yes (partial)",
            "Yes",
            "100%",
            _status(wa_mt, 168),
            _fmt_dt(wa_mt),
            _hours_ago(wa_mt),
            "Requires manual export from phone",
        )
    )


    cg_f = SBK_DATA / "chatgpt/conversations.json"
    mt = _best_time(_mtime(cg_f), "chatgpt")
    cg_cnt = None
    if cg_f.exists():
        try:
            with open(cg_f) as _f:
                cg_cnt = len(json.load(_f))
        except Exception:
            pass
    sz = _size_mb(cg_f)
    rows.append(
        _row(
            "L0.24",
            f"ChatGPT ({cg_cnt or '?'} conversations)",
            "-",
            "(manual export from chatgpt.com)",
            "Rare",
            "Export JSON",
            "Manual export",
            "https://chatgpt.com/#settings/DataControls",
            "monthly",
            "0",
            cg_cnt,
            sz,
            "Full (full conversations)",
            "No",
            "Yes",
            "80%",
            _status(mt, 720),
            _fmt_dt(mt),
            _hours_ago(mt),
            "Export from Settings > Data Controls > Export",
        )
    )


    rows.append(
        _row(
            "L0.25",
            "iPhone Address book",
            "-",
            "(VCF export from Contacts app)",
            "Rare",
            "Export file",
            "Manual export",
            "(Contacts app > Select All > Share > VCF)",
            "monthly",
            "0",
            "",
            "",
            "Struct (name, phone, email)",
            "No",
            "No",
            "80%",
            "Stale",
            "",
            "",
            "Requires manual VCF export",
        )
    )


    ds_proc = SBK_DATA / "docusign/processed"
    ds_f = ds_proc / "contracts.parquet" if ds_proc.exists() else None
    mt = _best_time(_mtime(ds_f) if ds_f else None, "docusign")
    cnt = _pq_count(ds_f) if ds_f and ds_f.exists() else None
    sz = _size_mb(SBK_DATA / "docusign") if (SBK_DATA / "docusign").exists() else 0
    rows.append(
        _row(
            "L0.26",
            f"DocuSign ({cnt or '?'} contracts)",
            "ds-l0-api.py",
            "uv run python3 tools/docusign/ds-l0-api.py",
            "API",
            "eSignature REST API, JWT (app «sbk», demo account)",
            "Keychain sbk-docusign + RSA key",
            "https://eu.docusign.net",
            "on-demand",
            "0",
            cnt,
            sz,
            "Part (metadata + contract full text)",
            "No",
            "No",
            "100%",
            _status(mt, 168),
            _fmt_dt(mt),
            _hours_ago(mt),
            "No action: JWT, consent given once",
        )
    )


    vm_dir = SBK_DATA / "voice-memos"
    vm_f = vm_dir / "voice-memos.parquet"
    mt = _best_time(_mtime(vm_f), "voice-memos")
    cnt = _pq_count(vm_f) if vm_f.exists() else None
    m4a_count = len(list(vm_dir.glob("*.m4a"))) if vm_dir.exists() else 0
    sz = _size_mb(vm_dir)
    rows.append(
        _row(
            "L0.27",
            f"Voice Memos ({m4a_count} memo)",
            "vm-l0-transcribe.py",
            "uv run python3 tools/voice-memos/vm-l0-transcribe.py",
            "Rare",
            "Local (Whisper CLI)",
            "Local (no auth)",
            "~/.sbk-data/voice-memos/",
            "on-demand",
            "0",
            m4a_count,
            sz,
            "Full (full Whisper transcription)",
            "No",
            "Yes",
            "100%",
            _status(mt, 168),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    manus_dir = SBK_DATA / "manus"
    manus_count = len(list(manus_dir.glob("*.md"))) if manus_dir.exists() else 0
    manus_mt = _mtime(manus_dir) if manus_dir.exists() else None
    manus_sz = _size_mb(manus_dir)
    rows.append(
        _row(
            "L0.28",
            f"Manus ({manus_count} file)",
            "-",
            "(manual import)",
            "Rare",
            "Import file",
            "None",
            "",
            "one-shot",
            "0",
            manus_count,
            manus_sz,
            "Full (AI task analysis export)",
            "No",
            "No",
            "100%",
            _status(manus_mt, 8760),
            _fmt_dt(manus_mt),
            _hours_ago(manus_mt),
            "One-shot import, static data",
        )
    )




    rows.append(_section_header("L1 — ENRICH (per-source normalization)"))


    em_wm = SBK_DATA / "enriched/email-l1-watermark.json"
    mt = _best_time(_mtime(em_wm), "email-l1")
    rows.append(
        _row(
            "L1.1",
            "Email enrich (all accounts)",
            "em-l1-enrich.py",
            "uv run python3 tools/email/em-l1-enrich.py --incremental",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL0.1",
            "0",
            1000,
            "",
            "FULL — Header + body_text (HTML stripped, max 10K char) in messages-with-body.parquet",
            "No",
            "",
            "100%",
            _status(mt, 48),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    em_l2 = TOOLS_DIR / "email/em-l2-export.py"
    rows.append(
        _row(
            "L1.1b",
            "Email L2 export",
            "em-l2-export.py",
            "uv run python3 tools/email/em-l2-export.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL1.1",
            "0",
            "",
            "",
            "Struct (export to L2 merge)",
            "",
            "",
            "100%",
            "OK" if em_l2.exists() else "Missing",
            "",
            "",
            "",
        )
    )


    cal_contacts = SBK_DATA / "enriched/contacts-calendar.parquet"
    cal_inter = SBK_DATA / "enriched/interactions-calendar.parquet"
    mt = _best_time(_mtime(cal_contacts), "calendar-l1")
    cnt_c = _pq_count(cal_contacts)
    cnt_i = _pq_count(cal_inter)
    rows.append(
        _row(
            "L1.2",
            "Calendar extract",
            "ca-l1-extract.py",
            "uv run python3 tools/calendar/ca-l1-extract.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL0.2",
            "0",
            f"{cnt_c or 0} cont + {cnt_i or 0} inter",
            "",
            "PARTIAL — Attendees, subject, description if present",
            "No",
            "",
            "100%",
            _status(mt, 48),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    sl_inter = SBK_DATA / "slack/processed/interactions-slack.parquet"
    sl_cont = SBK_DATA / "slack/processed/contacts-slack.parquet"
    mt = _best_time(_mtime(sl_inter), "slack-l1")
    cnt_i = _pq_count(sl_inter)
    cnt_c = _pq_count(sl_cont)
    rows.append(
        _row(
            "L1.3",
            "Slack enrich",
            "sl-l1-enrich.py",
            "uv run python3 tools/slack/sl-l1-enrich.py --incremental",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL0.3/L0.4",
            "0",
            f"{cnt_c or 0} cont + {cnt_i or 0} inter",
            "",
            "FULL — Counts + channel-texts (concatenated messages, max 50K/conv, UIDs resolved)",
            "No",
            "",
            "100%",
            _status(mt, 48),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    at_cont = SBK_DATA / "attio/processed/contacts-attio.parquet"
    at_comp = SBK_DATA / "attio/processed/companies-attio.parquet"
    at_calls = SBK_DATA / "attio/processed/interactions-attio-calls.parquet"
    mt_cont = _best_time(_mtime(at_cont), "attio-l1")
    mt_calls = _best_time(_mtime(at_calls), "attio-transcripts-l1")
    rows.append(
        _row(
            "L1.4",
            "Attio contacts + companies",
            "at-l1-enrich.py",
            "uv run python3 tools/attio/at-l1-enrich.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL0.5-L0.16",
            "0",
            f"{_pq_count(at_cont) or 0} cont + {_pq_count(at_comp) or 0} comp",
            "",
            "STRUCT — Attributes, relations, CRM metadata",
            "No",
            "",
            "100%",
            _status(mt_cont, 72),
            _fmt_dt(mt_cont),
            _hours_ago(mt_cont),
            "",
        )
    )
    rows.append(
        _row(
            "L1.4b",
            "Attio calls + transcripts",
            "at-util-transcripts.py",
            "uv run python3 tools/attio/at-util-transcripts.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL0.9",
            "0",
            f"{_pq_count(at_calls) or 0} inter",
            "",
            "FULL — Full transcript with speaker detection",
            "Yes",
            "",
            "100%",
            _status(mt_calls, 72),
            _fmt_dt(mt_calls),
            _hours_ago(mt_calls),
            "",
        )
    )


    l1_sources = [
        (
            "L1.5",
            "Personio enrich",
            "pe-l1-enrich.py",
            "uv run python3 tools/personio/pe-l1-enrich.py",
            "personio/processed/contacts-personio.parquet",
            "STRUCT — HR structure, org chart, no content",
        ),
        (
            "L1.6",
            "Notion enrich",
            "no-l1-enrich.py",
            "uv run python3 tools/notion/no-l1-enrich.py",
            "notion/processed/entities-notion.parquet",
            "FULL — DB schema, tasks, entities + pages-text (plain text blocks, max 30K/page)",
        ),
        (
            "L1.7",
            "GDrive enrich",
            "gd-l1-enrich.py",
            "uv run python3 tools/gdrive/gd-l1-enrich.py",
            "gdrive/processed/documents.parquet",
            "FULL — Metadata + content text (PDF, DOCX, XLSX, MD, TXT, CSV, max 20K/file)",
        ),
        (
            "L1.8",
            "Plaud enrich",
            "pl-l1-enrich.py",
            "uv run python3 tools/plaud/pl-l1-enrich.py",
            "plaud/processed",
            "FULL — Transcript + speaker analysis + speech corpus",
        ),
        (
            "L1.9",
            "Tactiq enrich",
            "tq-l1-enrich.py",
            "uv run python3 tools/tactiq/tq-l1-enrich.py",
            "tactiq/processed/meetings.parquet",
            "FULL — Transcript + speakers + meeting analysis",
        ),
        (
            "L1.10a",
            "LinkedIn Contacts enrich",
            "li-l1-enrich.py",
            "uv run python3 tools/linkedin/li-l1-enrich.py",
            "linkedin/processed/contacts-linkedin.parquet",
            "FULL — Name, linkedin_id, date, msg count, headline, company, email",
        ),
        (
            "L1.10b",
            "LinkedIn Interactions enrich",
            "li-l1-enrich.py",
            "uv run python3 tools/linkedin/li-l1-enrich.py",
            "linkedin/processed/interactions-linkedin.parquet",
            "FULL — Timestamp, from/to, type, body_length + message_text (max 5K char)",
        ),
        (
            "L1.10c",
            "LinkedIn Investors enrich",
            "li-l1-enrich.py",
            "uv run python3 tools/linkedin/li-l1-enrich.py",
            "linkedin/processed/investors-linkedin.parquet",
            "FULL — Bio, company, role, investment prefs, location, tier, thesis_fit",
        ),
        (
            "L1.10d",
            "LinkedIn Profile enrich",
            "li-util-profile-update.py",
            "uv run python3 tools/linkedin/li-util-profile-update.py",
            "linkedin/processed/contacts-linkedin.parquet",
            "Part — Headline, about, location, industry from scraping (only part of the profiles)",
        ),
        (
            "L1.11",
            "WhatsApp enrich",
            "wa-l1-enrich.py",
            "uv run python3 tools/whatsapp/wa-l1-enrich.py",
            "whatsapp/processed/interactions-whatsapp.parquet",
            "FULL — Counts + chat-texts.parquet (concatenated messages, max 50K/chat)",
        ),
        (
            "L1.12",
            "ChatGPT enrich",
            "cg-l1-enrich.py",
            "uv run python3 tools/chatgpt/cg-l1-enrich.py",
            "chatgpt/processed/conversations-classified.parquet",
            "FULL — Classification + full_text (user+assistant, max 20K char)",
        ),
        (
            "L1.13",
            "DocuSign enrich",
            "ds-l1-enrich.py",
            "uv run python3 tools/docusign/ds-l1-enrich.py",
            "docusign/processed/contracts.parquet",
            "STRUCT — Contract metadata (parties, dates, amounts). No full text: PDFs never downloaded",
            "Full text requires PDF download via DocuSign API",
        ),
        (
            "L1.14",
            "Voice Memos enrich",
            "vm-l1-enrich.py",
            "uv run python3 tools/voice-memos/vm-l1-enrich.py",
            "voice-memos/voice-memos.parquet",
            "FULL — Full Whisper transcription",
        ),
        (
            "L1.15",
            "iPhone VCF match",
            "xs-l1-match-vcf.py",
            "uv run python3 tools/cross-source/xs-l1-match-vcf.py",
            "enriched/contacts.parquet",
            "STRUCT — Contact matching by phone/email",
        ),
        (
            "L1.16",
            "Cross-source contacts enrich",
            "xs-l1-contacts-enrich.py",
            "uv run python3 tools/cross-source/xs-l1-contacts-enrich.py",
            "enriched/contacts.parquet",
            "STRUCT — Cross-source contact enrichment",
        ),
        (
            "L1.17",
            "LinkedIn email enrich",
            "li-l2-email-enrich.py",
            "uv run python3 tools/linkedin/li-l2-email-enrich.py --guess",
            "linkedin/enriched/email-enrichment.parquet",
            "META — Email guess pattern (Connections.csv not available)",
        ),
    ]

    for entry in l1_sources:
        id_, name, script, cmd, output_path, depth = entry[:6]
        source_gap = entry[6] if len(entry) > 6 else ""

        _lr_key = script.replace(".py", "").replace("-enrich", "").replace("-extract", "")
        p = SBK_DATA / output_path
        if p.is_dir():
            mt = _best_time(_mtime(p), _lr_key)
            cnt = ""
            sz = _size_mb(p)
        elif p.exists():
            mt = _best_time(_mtime(p), _lr_key)
            cnt = _pq_count(p) or ""
            sz = _size_mb(p)
        else:
            mt = _best_time(None, _lr_key)
            cnt = ""
            sz = ""
        rows.append(
            _row(
                id_,
                name,
                script,
                cmd,
                "Cascade",
                "Internal",
                "N/A",
                "",
                "cascade fromL0",
                "0",
                cnt,
                sz,
                depth,
                "",
                "",
                "100%" if mt else "0%",
                _status(mt, 72),
                _fmt_dt(mt),
                _hours_ago(mt),
                source_gap,
            )
        )




    rows.append(_section_header("L2 — MERGE (cross-source unification)"))

    l2_stages = [
        (
            "L2.1",
            "Cross-source merge",
            "xs-l2-merge.py",
            "enriched/interactions.parquet",
        ),
        (
            "L2.2",
            "Entity resolve",
            "xs-l2-entity-resolve.py",
            "enriched/entity-map.json",
        ),
        (
            "L2.3",
            "Entity boost",
            "xs-l2-entity-boost.py",
            "enriched/entity-map.json",
        ),
        (
            "L2.4",
            "Resolve names",
            "xs-l2-resolve-names.py",
            "enriched/contacts-merged.parquet",
        ),
        (
            "L2.5",
            "People universe",
            "xs-l2-people-universe.py",
            "enriched/people-universe.parquet",
        ),
        (
            "L2.6",
            "Network profiles",
            "xs-l2-network-profiles.py",
            "enriched/contacts-merged.parquet",
        ),
        (
            "L2.7",
            "Apply decisions",
            "xs-l2-apply-decisions.py",
            "enriched/entity-map.json",
        ),
        (
            "L2.8",
            "Speech analysis",
            "xs-l2-analyze-speech.py",
            "enriched/speech-analysis.json",
        ),
        (
            "L2.9",
            "DuckDB views",
            "xs-l2-duckdb-setup.py",
            "enriched/interactions.parquet",
        ),
    ]

    for id_, name, script, output_path in l2_stages:
        p = SBK_DATA / output_path
        _lr_key = script.replace(".py", "")
        mt = _best_time(_mtime(p), _lr_key)
        cnt = ""
        if p.suffix == ".parquet" and p.exists():
            cnt = _pq_count(p) or ""
        elif p.suffix == ".json" and p.exists():
            try:
                with open(p) as _f:
                    cnt = len(json.load(_f))
            except Exception:
                cnt = ""
        sz = _size_mb(p) if p.exists() else ""
        rows.append(
            _row(
                id_,
                name,
                script,
                f"uv run python3 tools/cross-source/{script}",
                "Cascade",
                "Internal",
                "N/A",
                "",
                "cascade fromL1",
                "0",
                cnt,
                sz,
                "Full (merge all L1 data)",
                "",
                "",
                "100%" if mt else "0%",
                _status(mt, 48),
                _fmt_dt(mt),
                _hours_ago(mt),
                "",
            )
        )




    rows.append(_section_header("L3 — EXTRACT (NLP / intelligence)"))


    ent_f = SBK_DATA / "l3/nlp/entities.parquet"
    mt = _mtime(ent_f)
    cnt = _pq_count(ent_f)
    rows.append(
        _row(
            "L3.1",
            "NER entities (regex)",
            "xs-l3-extract.py",
            "uv run python3 tools/cross-source/xs-l3-extract.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL1",
            "0",
            cnt,
            _size_mb(ent_f),
            "Regex NER on 2/20 sources (plaud, tactiq)",
            "Covers 2 sources",
            "",
            "10%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "Only plaud+tactiq. Missing: email, slack, wa, chatgpt, notion, gdrive, attio notes",
        )
    )


    rel_f = SBK_DATA / "l3/nlp/relationship-facts.parquet"
    mt = _mtime(rel_f)
    cnt = _pq_count(rel_f)
    rows.append(
        _row(
            "L3.2",
            "Relationship facts (LLM Haiku)",
            "xs-l3-extract-relationships.py",
            "uv run python3 tools/cross-source/xs-l3-extract-relationships.py",
            "Click",
            "API Claude Haiku",
            "API Key permanente (Anthropic)",
            "",
            "on-demand (costs $)",
            "variable (see --dry-run)",
            cnt,
            _size_mb(rel_f),
            "LLM extraction on 6/20 sources",
            "Covers 6 sources",
            "",
            "30%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "Covers: plaud, tactiq, attio calls/notes, slack ch, wa. Missing: email, slack DM, chatgpt, notion, gdrive",
        )
    )


    act_f = SBK_DATA / "l3/nlp/action-items.parquet"
    mt = _mtime(act_f)
    cnt = _pq_count(act_f)
    rows.append(
        _row(
            "L3.3",
            "Action items (regex + LLM)",
            "xs-l3-tasks.py",
            "uv run python3 tools/cross-source/xs-l3-tasks.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade",
            "0",
            cnt,
            _size_mb(act_f),
            "Regex on 2/20 sources",
            "Covers 2 sources",
            "",
            "10%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "Only plaud+tactiq",
        )
    )


    dec_f = SBK_DATA / "l3/nlp/decisions.parquet"
    mt = _mtime(dec_f)
    cnt = _pq_count(dec_f)
    rows.append(
        _row(
            "L3.3b",
            "Decisions",
            "xs-l3-extract.py",
            "uv run python3 tools/cross-source/xs-l3-extract.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade",
            "0",
            cnt,
            _size_mb(dec_f),
            "Extracted from meeting transcripts",
            "",
            "",
            "30%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    shad_f = SBK_DATA / "l3/nlp/shadow-contacts.parquet"
    mt = _mtime(shad_f)
    cnt = _pq_count(shad_f)
    rows.append(
        _row(
            "L3.4",
            "Shadow contacts (derived from L3.2)",
            "xs-l3-shadow-extract.py",
            "uv run python3 tools/cross-source/xs-l3-shadow-extract.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL3.2",
            "0",
            cnt,
            _size_mb(shad_f),
            "Contacts inferred from mentions in facts",
            "",
            "",
            "100%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    fi_f = SBK_DATA / "l3/fact-index.json"
    mt = _mtime(fi_f)
    rows.append(
        _row(
            "L3.5",
            "Fact index",
            "xs-l3-fact-index.py",
            "uv run python3 tools/cross-source/xs-l3-fact-index.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL3.2",
            "0",
            "",
            _size_mb(fi_f) if fi_f.exists() else "",
            "Quick index of facts per person",
            "",
            "",
            "100%",
            _status(mt, 72),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )


    rows.append(
        _row(
            "L3.6",
            "Annotate (person annotations)",
            "xs-l3-annotate.py",
            "uv run python3 tools/cross-source/xs-l3-annotate.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade",
            "0",
            "",
            "",
            "Manual annotations on people",
            "",
            "",
            "100%",
            "OK",
            "",
            "",
            "",
        )
    )


    fu_f = SBK_DATA / "l3/nlp/followup-state.json"
    mt = _mtime(fu_f)
    rows.append(
        _row(
            "L3.7",
            "Follow-up tracking",
            "xs-l3-followup.py",
            "uv run python3 tools/cross-source/xs-l3-followup.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade",
            "0",
            "",
            "",
            "Tracking open follow-ups",
            "",
            "",
            "100%",
            _status(mt, 72) if mt else "OK",
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )




    rows.append(_section_header("L4 — CONNECT (knowledge graph)"))

    gr_f = SBK_DATA / "l3/graph/sbk-graph.gpickle"
    mt = _mtime(gr_f)
    gr_sz = _size_mb(SBK_DATA / "l3/graph") if (SBK_DATA / "l3/graph").exists() else 0
    rows.append(
        _row(
            "L4.1",
            "Knowledge graph build",
            "xs-l3-graph.py",
            "uv run python3 tools/cross-source/xs-l3-graph.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL2+L3",
            "0",
            "",
            gr_sz,
            "Full (nodes + edges + weights + temporal)",
            "",
            "",
            "100%",
            _status(mt, 48),
            _fmt_dt(mt),
            _hours_ago(mt),
            "",
        )
    )

    cent_f = SBK_DATA / "l3/graph/centrality.json"
    comm_f = SBK_DATA / "l3/graph/communities.json"
    rows.append(
        _row(
            "L4.2",
            "Centrality + communities",
            "(included in xs-l3-graph.py)",
            "",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL4.1",
            "0",
            "",
            "",
            "Centrality scores + community detection",
            "",
            "",
            "100%",
            _status(_mtime(cent_f), 48),
            _fmt_dt(_mtime(cent_f)),
            _hours_ago(_mtime(cent_f)),
            "",
        )
    )




    rows.append(_section_header("L5 — INDEX (vector embeddings + search)"))

    lance_f = SBK_DATA / "l3/vectordb/sbk_chunks.lance"
    idx_mt = _mtime(SBK_DATA / "l3/vectordb/index-checkpoint.json")
    vec_sz = _size_mb(SBK_DATA / "l3/vectordb") if (SBK_DATA / "l3/vectordb").exists() else 0

    idx_ckpt = SBK_DATA / "l3/vectordb/index-checkpoint.json"
    total_chunks = 0
    if idx_ckpt.exists():
        try:
            with open(idx_ckpt) as _f:
                ckpt = json.load(_f)
            total_chunks = sum(v.get("count", 0) for v in ckpt.values())
        except Exception:
            pass


    idx_sources = 0
    if idx_ckpt.exists():
        try:
            with open(idx_ckpt) as _f:
                ckpt_data = json.load(_f)
            idx_sources = len([k for k, v in ckpt_data.items() if v.get("count", 0) > 0])
        except Exception:
            pass

    rows.append(
        _row(
            "L5.1",
            "Vector embeddings (LanceDB)",
            "xs-l3-index.py",
            "uv run python3 tools/cross-source/xs-l3-index.py --incremental",
            "Cascade",
            "Internal (local MLX embeddings)",
            "Locale",
            "",
            "cascade fromL0+L1",
            "0",
            f"{total_chunks} chunks",
            vec_sz,
            f"Embedding on {idx_sources} sources" if idx_sources else "Full embedding",
            "",
            f"{idx_sources} sources" if idx_sources else "",
            "100%" if idx_sources >= 12 else f"{idx_sources * 100 // 15}%",
            _status(idx_mt, 48),
            _fmt_dt(idx_mt),
            _hours_ago(idx_mt),
            "",
        )
    )

    rows.append(
        _row(
            "L5.2",
            "Search engine",
            "xs-l3-search.py",
            "uv run python3 tools/cross-source/xs-l3-search.py",
            "Cascade",
            "Internal",
            "N/A",
            "",
            "cascade fromL5.1",
            "0",
            "",
            "",
            "Semantic search on vector index",
            "",
            "",
            "100%",
            "OK",
            "",
            "",
            "",
        )
    )




    rows.append(_section_header("R — RUNTIME (live services)"))

    runtime_services = [
        (
            "R.1",
            "Decay scores",
            "xs-l3-decay.py",
            "uv run python3 tools/cross-source/xs-l3-decay.py",
            "Cascade",
            "cascade",
            "Update of temporal relationship weights",
        ),
        (
            "R.2",
            "Email real-time (IMAP IDLE)",
            "em-realtime.py",
            "uv run python3 tools/email/em-realtime.py",
            "Auto",
            "always (daemon)",
            "IMAP IDLE monitor for new emails",
        ),
        (
            "R.3",
            "Slack real-time (Socket Mode)",
            "sl-realtime.py",
            "uv run python3 tools/slack/sl-realtime.py",
            "Auto",
            "always (daemon)",
            "Socket Mode monitor for new messages",
        ),
        (
            "R.4",
            "Daily brief",
            "xs-l3-brief.py",
            "uv run python3 tools/cross-source/xs-l3-brief.py",
            "Auto",
            "every 15 min (launchd)",
            "Daily brief with highlights",
        ),
        (
            "R.5",
            "Weekly digest",
            "xs-l3-digest-v2.py",
            "uv run python3 tools/cross-source/xs-l3-digest-v2.py",
            "Auto",
            "daily (launchd)",
            "Weekly digest",
        ),
        (
            "R.6",
            "Draft generation",
            "xs-l3-draft.py",
            "uv run python3 tools/cross-source/xs-l3-draft.py",
            "Click",
            "on-demand",
            "Email/message draft generation",
        ),
        (
            "R.7",
            "Monitor daemon",
            "sbk-monitor.py",
            "uv run python3 tools/monitoring/sbk-monitor.py",
            "Auto",
            "always (launchd KeepAlive)",
            "Pipeline health monitoring",
        ),
        (
            "R.8",
            "Pipeline orchestrator",
            "xs-pipeline-run.py",
            "uv run python3 tools/cross-source/xs-pipeline-run.py --propagate",
            "Auto",
            "cascade (event bus)",
            "Pipeline orchestrator L2-L5",
        ),
        (
            "R.9",
            "Event bus",
            "xs-event-bus.py",
            "uv run python3 tools/cross-source/xs-event-bus.py",
            "Auto",
            "always",
            "Filesystem event bus for cascade triggers",
        ),
    ]

    for id_, name, script, cmd, tipo, freq, depth in runtime_services:
        rows.append(
            _row(
                id_,
                name,
                script,
                cmd,
                tipo,
                "Internal",
                "N/A",
                "",
                freq,
                "0",
                "",
                "",
                depth,
                "",
                "",
                "100%",
                "OK",
                "",
                "",
                "",
            )
        )

    return rows





def push_to_sheets(rows: list[list[str]]):
    ""
    if not SPREADSHEET_ID:
        print(
            "ERROR: no sheet to push to. Set pipeline_status.spreadsheet_id in sbk.config.json "
            "(the id in the sheet's URL, between /d/ and /edit)."
        )
        return False
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing Sheets OAuth token...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                print(f"ERROR: Client secret not found at {CLIENT_SECRET}")
                return False
            print("Opening browser for Google Sheets authorization...")
            print("Pick the Google account that owns the sheet in the browser.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_PATH, 0o600)
        print(f"Token saved to {TOKEN_PATH}")

    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()


    spreadsheet = sheet.get(spreadsheetId=SPREADSHEET_ID).execute()
    existing_sheets = [s["properties"]["title"] for s in spreadsheet["sheets"]]

    if SHEET_NAME not in existing_sheets:

        first_sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
        sheet.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": first_sheet_id,
                                "title": SHEET_NAME,
                            },
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()
        print(f"Renamed first sheet to '{SHEET_NAME}'")


    sheet.values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{SHEET_NAME}'!A:Z",
    ).execute()


    result = (
        sheet.values()
        .update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'!A1",
            valueInputOption="RAW",
            body={"values": rows},
        )
        .execute()
    )
    updated = result.get("updatedCells", 0)
    print(f"Pushed {len(rows)} rows x {len(rows[0])} cols = {updated} cells to Google Sheets")


    _format_sheet(sheet, spreadsheet, rows)

    return True


def _format_sheet(sheet, spreadsheet, rows):
    ""
    sheet_id = None
    for s in spreadsheet["sheets"]:
        if s["properties"]["title"] == SHEET_NAME:
            sheet_id = s["properties"]["sheetId"]
            break

    if sheet_id is None:
        return

    requests = [

        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },

        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.2,
                            "green": 0.2,
                            "blue": 0.2,
                        },
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {
                                "red": 1,
                                "green": 1,
                                "blue": 1,
                            },
                        },
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },

        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(rows[0]),
                }
            }
        },
    ]


    for i, row in enumerate(rows):
        if row[0].startswith("▸"):
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": i,
                            "endRowIndex": i + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {
                                    "red": 0.9,
                                    "green": 0.93,
                                    "blue": 0.98,
                                },
                            }
                        },
                        "fields": "userEnteredFormat(textFormat,backgroundColor)",
                    }
                }
            )

    sheet.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print("Applied formatting (frozen header, bold, colors)")





def save_json(rows: list[list[str]]):
    ""
    header = rows[0]
    data = []
    for row in rows[1:]:
        if row[0].startswith("▸"):
            continue
        entry = {}
        for h, v in zip(header, row):
            entry[h] = v
        data.append(entry)

    state = {
        "generated_at": NOW.isoformat(),
        "total_rows": len(data),
        "header": header,
        "data": data,
    }

    safe_write_json(STATE_FILE, state)
    print(f"Saved JSON state to {STATE_FILE} ({len(data)} entries)")





def main():
    parser = argparse.ArgumentParser(description="SBK Pipeline Status")
    parser.add_argument("--push", action="store_true", help="Push to Google Sheets")
    parser.add_argument("--json-only", action="store_true", help="Only save JSON")
    args = parser.parse_args()

    print(f"SBK Pipeline Status — {NOW.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)


    rows = build_table()
    print(f"Built {len(rows)} rows (incl header + section headers)")


    save_json(rows)


    if args.push:
        ok = push_to_sheets(rows)
        if ok:
            print(
                f"\nGoogle Sheets updated: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
            )
        else:
            print("\nERROR: push to Sheets failed")


    if not args.json_only:
        print(
            f"\nTotal pipeline stages: {len([r for r in rows if r[0] and not r[0].startswith('▸')]) - 1}"
        )
        print(f"Local JSON: {STATE_FILE}")
        if not args.push:
            print(f"To push to Sheets: uv run python3 {__file__} --push")


if __name__ == "__main__":
    main()
