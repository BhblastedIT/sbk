#!/usr/bin/env python3
"""Data freshness report: for each source, when it was last downloaded and processed, how many rows and which date
range, against how fresh it should be; in the terminal, as Markdown, as an HTML page (--html) or a local page with
a refresh button (--serve).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sbk_config import (
    ATTIO_DIR,
    ATTIO_PROCESSED_DIR,
    ATTIO_WORKSPACE_DIRS,
    CALENDARS_DIR,
    CHATGPT_DIR,
    DATA_ROOT,
    DOCUSIGN_DIR,
    ENRICHED_DIR,
    EXPORTS_DIR,
    GDRIVE_DIR,
    IPHONE_DIR,
    L3_DIR,
    LINKEDIN_DIR,
    NOTION_DIR,
    PERSONIO_DIR,
    PERSONIO_PROCESSED_DIR,
    PLAUD_PROCESSED_DIR,
    SLACK_DIR,
    TACTIQ_DIR,
    VOICE_MEMOS_PROCESSED_DIR,
    WHATSAPP_DIR,
)

NOW = datetime.now()



L2_MERGED = ENRICHED_DIR / "contacts-merged.parquet"
L2_SCORES = EXPORTS_DIR / "relationship-scores.parquet"
L2_GRAPH_JSON = EXPORTS_DIR / "network-graph.json"
L3_GRAPH_DIR = L3_DIR / "graph"
L3_DECAY_DIR = L3_DIR / "decay"
L3_NLP_DIR = L3_DIR / "nlp"
L3_VECTOR_DIR = L3_DIR / "vectordb"





def file_mod(path: Path) -> datetime | None:
    if path.exists():
        return datetime.fromtimestamp(os.path.getmtime(path))
    return None


def newest_file(directory: Path, pattern: str = "*") -> datetime | None:
    if not directory.exists():
        return None
    times = []
    for f in directory.glob(pattern):
        if f.is_file():
            times.append(datetime.fromtimestamp(os.path.getmtime(f)))
    return max(times) if times else None


def dir_size_mb(directory: Path) -> float:
    if not directory.exists():
        return 0.0
    total = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def parquet_rows(path: Path) -> int | None:
    if path.exists():
        try:
            return pq.read_metadata(path).num_rows
        except Exception:
            return None
    return None


def parquet_date_range(path: Path, date_cols: list[str] | None = None) -> str:
    ""
    if not path.exists():
        return ""
    if date_cols is None:
        date_cols = [
            "date",
            "timestamp",
            "created_at",
            "start_time",
            "start_datetime",
            "meeting_date",
            "sent_date",
            "date_start",
            "date_end",
        ]
    try:


        nomi = pq.read_schema(path).names
        for c in date_cols:
            if c in nomi:
                intervallo = _intervallo_date(pq.read_table(path, columns=[c]).column(c))
                if intervallo:
                    return f"{intervallo[0]} → {intervallo[1]}"
    except Exception:
        pass
    return ""


def _intervallo_date(colonna) -> tuple[str, str] | None:
    ""





    import pyarrow as pa
    import pyarrow.compute as pc

    tipo = colonna.type
    if pa.types.is_string(tipo) or pa.types.is_large_string(tipo):
        colonna = pc.filter(colonna, pc.not_equal(colonna, ""))
    elif not (pa.types.is_timestamp(tipo) or pa.types.is_date(tipo)):
        vals = [str(v)[:10] for v in colonna.to_pylist() if v]
        return (min(vals), max(vals)) if vals else None
    estremi = pc.min_max(colonna)
    minimo, massimo = estremi["min"].as_py(), estremi["max"].as_py()
    return (str(minimo)[:10], str(massimo)[:10]) if minimo is not None else None


def elapsed_str(dt: datetime | None) -> str:
    ""
    if dt is None:
        return "—"
    delta = NOW - dt
    total_hours = delta.total_seconds() / 3600
    if total_hours < 1:
        return f"{int(delta.total_seconds() / 60)}min"
    if total_hours < 24:
        return f"{int(total_hours)}h"
    days = delta.days
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w"
    return f"{days // 30}mo"


def freshness_status(dt: datetime | None, freq_days: int) -> str:
    if dt is None:
        return "MISSING"
    delta = (NOW - dt).days
    if delta <= freq_days:
        return "OK"
    if delta <= freq_days * 2:
        return "STALE"
    return "CRITICAL"


def format_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d/%m %H:%M")






SOURCE_HAS_COLUMN = {
    "Email (Gmail)": "has_email",
    "Attio (CRM)": "has_attio",
    "Slack": "has_slack",
    "WhatsApp": "has_whatsapp",
    "LinkedIn": "has_linkedin",
    "Plaud": "has_plaud",
    "Tactiq": "has_tactiq",
    "Notion": "has_notion",
    "ChatGPT": "has_chatgpt_mention",
    "Google Drive": "has_gdrive",
    "DocuSign": "has_docusign",
    "Personio (HR)": "has_personio",
    "iPhone Contacts": "has_iphone",
    "Voice Memos": None,
    "Calendar": "has_calendar",
    "Cross-source": None,
}


SOURCE_L1_CONTACTS = {
    "Email (Gmail)": None,
    "Attio (CRM)": "attio/processed/contacts-attio.parquet",
    "Slack": "slack/processed/contacts-slack.parquet",
    "WhatsApp": "whatsapp/processed/contacts-whatsapp.parquet",
    "LinkedIn": "linkedin/processed/contacts-linkedin.parquet",
    "Plaud": None,
    "Tactiq": "tactiq/processed/contacts-tactiq.parquet",
    "Notion": None,
    "ChatGPT": None,
    "Google Drive": "gdrive/processed/contacts-gdrive.parquet",
    "DocuSign": "docusign/processed/contacts-docusign.parquet",
    "Personio (HR)": "personio/processed/contacts-personio.parquet",
    "iPhone Contacts": "contacts/processed/contacts-iphone.parquet",
    "Voice Memos": None,
    "Calendar": "enriched/contacts-calendar.parquet",
}

SOURCE_L1_INTERACTIONS = {
    "Email (Gmail)": None,
    "Attio (CRM)": "attio/processed/interactions-attio-calls.parquet",
    "Slack": "slack/processed/interactions-slack.parquet",
    "WhatsApp": "whatsapp/processed/interactions-whatsapp.parquet",
    "LinkedIn": "linkedin/processed/interactions-linkedin.parquet",
    "Plaud": None,
    "Tactiq": "tactiq/processed/interactions-tactiq.parquet",
    "Notion": None,
    "ChatGPT": None,
    "Google Drive": "gdrive/processed/interactions-gdrive.parquet",
    "DocuSign": "docusign/processed/timeline-docusign.parquet",
    "Personio (HR)": None,
    "iPhone Contacts": None,
    "Voice Memos": None,
    "Calendar": "enriched/interactions-calendar.parquet",
}


def load_l2_coverage() -> dict[str, int]:
    ""
    result: dict[str, int] = {}
    if not L2_MERGED.exists():
        return result
    try:

        result["_total"] = pq.read_metadata(L2_MERGED).num_rows
        has_cols = [c for c in pq.read_schema(L2_MERGED).names if c.startswith("has_")]
        df = pd.read_parquet(L2_MERGED, columns=has_cols)
        for col in has_cols:
            result[col] = int(df[col].sum())
    except Exception:
        pass
    return result


def count_l1(source_name: str) -> tuple[int | None, int | None]:
    ""
    contacts = None
    interactions = None
    c_path = SOURCE_L1_CONTACTS.get(source_name)
    if c_path:
        p = DATA_ROOT / c_path
        contacts = parquet_rows(p)
    i_path = SOURCE_L1_INTERACTIONS.get(source_name)
    if i_path:
        p = DATA_ROOT / i_path
        interactions = parquet_rows(p)
    return contacts, interactions





def collect_sources() -> list[dict]:
    sources = []
    sync_state = DATA_ROOT / ".sync-state.json"
    ss = {}
    if sync_state.exists():
        with open(sync_state) as f:
            ss = json.load(f)


    l2_cov = load_l2_coverage()
    l2_total = l2_cov.get("_total", 0)

    def _l2_contacts(source_name: str) -> int:
        ""
        col = SOURCE_HAS_COLUMN.get(source_name)
        if col:
            return l2_cov.get(col, 0)
        return 0


    threads = ENRICHED_DIR / "threads.parquet"
    email_ts = ss.get("email", {}).get("last_check")
    email_l0 = datetime.fromisoformat(email_ts.replace("+00:00", "")) if email_ts else None
    sources.append(
        {
            "source": "Email (Gmail)",
            "l0": email_l0,
            "l1": file_mod(threads),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(threads),
            "record_label": "thread",
            "data_range": parquet_date_range(threads, ["date_start"]),
            "size_mb": os.path.getsize(threads) / (1024 * 1024) if threads.exists() else 0,
            "category": "live",
            "method": "API OAuth + monitor",
            "freq": "continuous",
            "freq_days": 1,
            "gap": "Live monitor blocked (OAuth)"
            if email_l0 and (NOW - email_l0).days > 1
            else "",
        }
    )


    sources.append(
        {
            "source": "Attio (CRM)",
            "l0": newest_file(ATTIO_DIR, "*.parquet"),
            "l1": newest_file(ATTIO_PROCESSED_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(ATTIO_DIR / "meetings.parquet"),
            "record_label": "meeting",
            "data_range": parquet_date_range(ATTIO_DIR / "meetings.parquet", ["start_dt"]),
            "size_mb": dir_size_mb(ATTIO_DIR),
            "category": "live",
            "method": "API (MCP)",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "Missing automatic L0 script",
        }
    )


    slack_ts = ss.get("slack", {}).get("last_check")
    slack_l0 = datetime.fromisoformat(slack_ts.replace("+00:00", "")) if slack_ts else None
    slack_l1 = newest_file(SLACK_DIR, "*.parquet")
    n_channels = len(ss.get("slack", {}).get("channel_timestamps", {}))
    sources.append(
        {
            "source": "Slack",
            "l0": slack_l0,
            "l1": slack_l1,
            "l2": file_mod(L2_MERGED),
            "records": n_channels,
            "record_label": "channels",
            "data_range": "",
            "size_mb": dir_size_mb(SLACK_DIR),
            "category": "live",
            "method": "API (MCP) + monitor",
            "freq": "continuous",
            "freq_days": 1,
            "gap": "L1 to re-run" if slack_l1 and (NOW - slack_l1).days > 1 else "",
        }
    )


    wa_interactions = WHATSAPP_DIR / "interactions-whatsapp.parquet"
    sources.append(
        {
            "source": "WhatsApp",
            "l0": newest_file(DATA_ROOT / "whatsapp" / "chats", "*.json"),
            "l1": newest_file(WHATSAPP_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(wa_interactions),
            "record_label": "messages",
            "data_range": parquet_date_range(wa_interactions, ["timestamp"]),
            "size_mb": dir_size_mb(DATA_ROOT / "whatsapp"),
            "category": "storico",
            "method": "Export manuale iPhone",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    li_interactions = LINKEDIN_DIR / "interactions-linkedin.parquet"
    sources.append(
        {
            "source": "LinkedIn",
            "l0": newest_file(LINKEDIN_DIR, "*.parquet"),
            "l1": newest_file(LINKEDIN_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(li_interactions),
            "record_label": "interactions",
            "data_range": parquet_date_range(li_interactions, ["timestamp"]),
            "size_mb": dir_size_mb(LINKEDIN_DIR),
            "category": "storico",
            "method": "Browser scrape JS",
            "freq": "daily",
            "freq_days": 1,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "Plaud",
            "l0": newest_file(PLAUD_PROCESSED_DIR, "*.json"),
            "l1": newest_file(PLAUD_PROCESSED_DIR, "*.json"),
            "l2": file_mod(L2_MERGED),
            "records": None,
            "record_label": "recording",
            "data_range": "",
            "size_mb": dir_size_mb(PLAUD_PROCESSED_DIR),
            "category": "storico",
            "method": "Browser scrape Playwright",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "Tactiq",
            "l0": newest_file(TACTIQ_DIR, "*.parquet"),
            "l1": newest_file(TACTIQ_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(TACTIQ_DIR / "contacts-tactiq.parquet"),
            "record_label": "transcript",
            "data_range": "",
            "size_mb": dir_size_mb(TACTIQ_DIR),
            "category": "storico",
            "method": "Download manuale",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "Notion",
            "l0": newest_file(NOTION_DIR, "*.parquet"),
            "l1": newest_file(NOTION_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(NOTION_DIR / "entities-notion.parquet"),
            "record_label": "entity",
            "data_range": "",
            "size_mb": dir_size_mb(NOTION_DIR),
            "category": "live",
            "method": "API (MCP)",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "ChatGPT",
            "l0": newest_file(CHATGPT_DIR, "*.parquet"),
            "l1": newest_file(CHATGPT_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(CHATGPT_DIR / "conversations-classified.parquet"),
            "record_label": "conversation",
            "data_range": "",
            "size_mb": dir_size_mb(CHATGPT_DIR),
            "category": "storico",
            "method": "Export manuale JSON",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "Google Drive",
            "l0": newest_file(GDRIVE_DIR, "*.parquet"),
            "l1": newest_file(GDRIVE_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(GDRIVE_DIR / "documents.parquet"),
            "record_label": "documents",
            "data_range": "",
            "size_mb": dir_size_mb(GDRIVE_DIR),
            "category": "live",
            "method": "API OAuth",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "DocuSign",
            "l0": newest_file(DOCUSIGN_DIR, "*.parquet"),
            "l1": newest_file(DOCUSIGN_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(DOCUSIGN_DIR / "contracts.parquet"),
            "record_label": "contract",
            "data_range": "",
            "size_mb": dir_size_mb(DOCUSIGN_DIR),
            "category": "storico",
            "method": "Scrape Playwright",
            "freq": "monthly",
            "freq_days": 30,
            "gap": "",
        }
    )






    sources.append(
        {
            "source": "Personio (HR)",
            "l0": newest_file(PERSONIO_DIR, "*.json") if PERSONIO_DIR.exists() else None,
            "l1": newest_file(PERSONIO_PROCESSED_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(PERSONIO_PROCESSED_DIR / "employees.parquet")
            if (PERSONIO_PROCESSED_DIR / "employees.parquet").exists()
            else None,
            "record_label": "employee",
            "data_range": "",
            "size_mb": dir_size_mb(PERSONIO_PROCESSED_DIR),
            "category": "live",
            "method": "API Personio",
            "freq": "monthly",
            "freq_days": 30,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "iPhone Contacts",
            "l0": newest_file(IPHONE_DIR, "*.parquet"),
            "l1": newest_file(IPHONE_DIR, "*.parquet"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(IPHONE_DIR / "contacts-iphone.parquet"),
            "record_label": "contact",
            "data_range": "",
            "size_mb": dir_size_mb(IPHONE_DIR),
            "category": "storico",
            "method": "Export VCF manuale",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    sources.append(
        {
            "source": "Voice Memos",
            "l0": newest_file(VOICE_MEMOS_PROCESSED_DIR, "*.json"),
            "l1": newest_file(VOICE_MEMOS_PROCESSED_DIR, "*.json"),
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(VOICE_MEMOS_PROCESSED_DIR / "recordings-index.parquet"),
            "record_label": "memo",
            "data_range": "",
            "size_mb": dir_size_mb(VOICE_MEMOS_PROCESSED_DIR),
            "category": "storico",
            "method": "Manuale + Whisper",
            "freq": "weekly",
            "freq_days": 7,
            "gap": "",
        }
    )


    cal_l1 = None
    total_events = 0
    cal_data_max = None
    for sub in sorted(CALENDARS_DIR.iterdir()) if CALENDARS_DIR.is_dir() else []:
        if sub.is_dir():
            t = newest_file(sub, "*.parquet")
            if t and (cal_l1 is None or t > cal_l1):
                cal_l1 = t
            ep = sub / "events.parquet"
            rows = parquet_rows(ep)
            if rows:
                total_events += rows
            try:
                if "start_datetime" in pq.read_schema(ep).names:
                    intervallo = _intervallo_date(
                        pq.read_table(ep, columns=["start_datetime"]).column("start_datetime")
                    )
                    if intervallo:
                        m = intervallo[1]
                        if cal_data_max is None or m > cal_data_max:
                            cal_data_max = m
            except Exception:
                pass
    gap_cal = f"Data up to {cal_data_max}. 2+ weeks missing" if cal_data_max else "No data"
    sources.append(
        {
            "source": "Calendar",
            "l0": cal_l1,
            "l1": cal_l1,
            "l2": file_mod(L2_MERGED),
            "records": total_events,
            "record_label": "event",
            "data_range": f"→ {cal_data_max}" if cal_data_max else "",
            "size_mb": dir_size_mb(CALENDARS_DIR),
            "category": "live",
            "method": "API Calendar OAuth",
            "freq": "daily",
            "freq_days": 1,
            "gap": gap_cal,
        }
    )


    vector_checkpoint = L3_VECTOR_DIR / "index-checkpoint.json"
    vector_rows = None
    if vector_checkpoint.exists():
        with open(vector_checkpoint) as f:
            vc = json.load(f)
        vector_rows = vc.get("total_chunks")
    sources.append(
        {
            "source": "Cross-source",
            "l0": None,
            "l1": None,
            "l2": file_mod(L2_MERGED),
            "records": parquet_rows(L2_MERGED),
            "record_label": "merged contacts",
            "data_range": "",
            "size_mb": dir_size_mb(L3_DIR)
            + (os.path.getsize(L2_MERGED) / (1024 * 1024) if L2_MERGED.exists() else 0),
            "category": "live",
            "method": "Script Python (post-batch)",
            "freq": "post-batch",
            "freq_days": 3,
            "gap": "",
            "extra": {
                "graph": file_mod(L3_GRAPH_DIR / "sbk-graph.gpickle"),
                "decay": file_mod(L3_DECAY_DIR / "decay-state.json"),
                "nlp": newest_file(L3_NLP_DIR, "*"),
                "vector": file_mod(vector_checkpoint),
                "vector_chunks": vector_rows,
            },
        }
    )


    for s in sources:
        name = s["source"]
        s["l0_ok"] = s["l0"] is not None
        s["l1_ok"] = s["l1"] is not None
        s["l2_contacts"] = _l2_contacts(name)
        s["l2_total"] = l2_total


        l1c, l1i = count_l1(name)
        s["l1_contacts"] = l1c
        s["l1_interactions"] = l1i


        if l1c and l1c > 0 and s["l2_contacts"] > 0:
            s["l1_to_l2_pct"] = min(s["l2_contacts"] / l1c * 100, 100)
        else:
            s["l1_to_l2_pct"] = None

    return sources





def generate_html(sources: list[dict]) -> str:
    status_colors = {
        "OK": "#22c55e",
        "STALE": "#eab308",
        "CRITICAL": "#ef4444",
        "MISSING": "#ef4444",
    }
    status_bg = {"OK": "#f0fdf4", "STALE": "#fefce8", "CRITICAL": "#fef2f2", "MISSING": "#fef2f2"}

    def elapsed_color(dt, freq):
        if dt is None:
            return "#94a3b8"
        d = (NOW - dt).days
        if d <= freq:
            return "#16a34a"
        if d <= freq * 2:
            return "#ca8a04"
        return "#dc2626"

    def pct_color(pct: float | None) -> str:
        if pct is None:
            return "#94a3b8"
        if pct >= 90:
            return "#16a34a"
        if pct >= 50:
            return "#ca8a04"
        return "#dc2626"

    def num_cell(n: int | None) -> str:
        if n is None or n == 0:
            return '<span style="color:#cbd5e1">&#8212;</span>'
        return f"{n:,}"

    main_sources = [s for s in sources if s["source"] != "Cross-source"]
    xs_source = next((s for s in sources if s["source"] == "Cross-source"), None)
    l2_total = main_sources[0].get("l2_total", 0) if main_sources else 0


    n_sources = len(main_sources)
    total_l0_records = sum(s.get("records") or 0 for s in main_sources)
    total_l1_contacts = sum(s.get("l1_contacts") or 0 for s in main_sources)
    total_l1_interactions = sum(s.get("l1_interactions") or 0 for s in main_sources)

    rows_html = ""
    for s in main_sources:
        status = freshness_status(s.get("l1") or s.get("l2"), s["freq_days"])
        badge_bg = status_colors.get(status, "#888")
        row_bg = status_bg.get(status, "#fff")
        gap = s["gap"] if s["gap"] else ""

        l0_color = elapsed_color(s["l0"], s["freq_days"])
        l1_color = elapsed_color(s["l1"], s["freq_days"])


        l0_rec = (
            f"{s['records']:,}" if s["records"] else '<span style="color:#cbd5e1">&#8212;</span>'
        )


        l1c = s.get("l1_contacts")
        l1i = s.get("l1_interactions")


        l2c = s.get("l2_contacts", 0)
        tp = s.get("l1_to_l2_pct")
        tp_str = f"{tp:.0f}%" if tp is not None else ""
        tp_color = pct_color(tp)

        rows_html += f"""
        <tr style="background:{row_bg}">
            <td style="font-weight:600">{s["source"]}</td>
            <td style="text-align:right">{l0_rec} <span style="color:#94a3b8;font-size:11px">{s["record_label"]}</span></td>
            <td>
                <div style="color:{l0_color};font-weight:600;font-size:13px">{elapsed_str(s["l0"])}</div>
            </td>
            <td style="text-align:right">{num_cell(l1c)}</td>
            <td style="text-align:right">{num_cell(l1i)}</td>
            <td>
                <div style="color:{l1_color};font-weight:600;font-size:13px">{elapsed_str(s["l1"])}</div>
            </td>
            <td style="text-align:right;font-weight:600">{num_cell(l2c) if l2c else num_cell(None)}</td>
            <td style="text-align:center;font-weight:700;color:{tp_color}">{tp_str}</td>
            <td>{s["freq"]}</td>
            <td><span style="background:{badge_bg};color:#fff;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:600">{status}</span></td>
            <td style="font-size:12px;color:#666">{gap}</td>
        </tr>"""

    ok = sum(
        1
        for s in main_sources
        if freshness_status(s.get("l1") or s.get("l2"), s["freq_days"]) == "OK"
    )
    stale = sum(
        1
        for s in main_sources
        if freshness_status(s.get("l1") or s.get("l2"), s["freq_days"]) == "STALE"
    )
    critico = sum(
        1
        for s in main_sources
        if freshness_status(s.get("l1") or s.get("l2"), s["freq_days"]) in ("CRITICAL", "MISSING")
    )


    xs = next((s for s in sources if s["source"] == "Cross-source"), None)
    l3_html = ""
    if xs and "extra" in xs:
        ex = xs["extra"]
        l3_rows = ""
        subsystems = [
            ("Knowledge Graph", ex.get("graph")),
            ("Decay Scores", ex.get("decay")),
            ("NLP (decisions + action items)", ex.get("nlp")),
            ("Vector Index", ex.get("vector")),
        ]
        for name, dt in subsystems:
            st = freshness_status(dt, 3)
            c = status_colors.get(st, "#888")
            extra_info = ""
            if name == "Vector Index" and ex.get("vector_chunks"):
                extra_info = f" ({ex['vector_chunks']:,} chunk)"
            l3_rows += f"""
            <tr>
                <td style="padding-left:24px;font-size:13px">{name}{extra_info}</td>
                <td style="font-size:13px">{format_date(dt)}</td>
                <td style="font-size:13px;font-weight:700;color:{c}">{elapsed_str(dt)}</td>
            </tr>"""
        l3_html = f"""
        <h2 style="font-size:18px;margin-top:32px">L3 Intelligence Subsystems</h2>
        <table style="max-width:500px">
        <thead><tr><th>Component</th><th>Last build</th><th>Ago</th></tr></thead>
        <tbody>{l3_rows}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SBK Data Freshness</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1500px; margin: 40px auto; padding: 0 20px; background: #fafafa; color: #1e293b; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; display: inline-block; }}
  h2 {{ font-size: 18px; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }}
  .subtitle {{ color: #666; margin-bottom: 24px; }}
  .btn-refresh {{ background: #1e293b; color: #fff; border: none; padding: 10px 24px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; }}
  .btn-refresh:hover {{ background: #334155; }}
  .btn-refresh:active {{ background: #0f172a; }}
  .btn-refresh.loading {{ opacity: 0.6; cursor: wait; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .cards .card {{ padding: 12px 24px; border-radius: 8px; font-weight: 600; font-size: 18px; }}
  .card.ok {{ background: #dcfce7; color: #166534; }}
  .card.stale {{ background: #fef9c3; color: #854d0e; }}
  .card.critico {{ background: #fee2e2; color: #991b1b; }}
  .pipeline {{ display: flex; gap: 16px; margin-bottom: 24px; padding: 16px 24px; background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .pipeline .num {{ font-size: 28px; font-weight: 800; }}
  .pipeline .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; font-weight: 600; }}
  .pipeline .detail {{ font-size: 12px; color: #94a3b8; }}
  .pipeline .stage {{ text-align: center; flex: 1; }}
  .pipeline .arrow {{ display: flex; align-items: center; color: #cbd5e1; font-size: 24px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #1e293b; color: #fff; padding: 10px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px; vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  .col-header {{ border-bottom: 3px solid; padding-bottom: 2px; }}
</style>
</head>
<body>
<div class="header">
  <h1>SBK Data Freshness</h1>
  <button class="btn-refresh" onclick="refreshReport(this)" title="Regenerate the report">&#8635; Refresh</button>
</div>
<div class="subtitle">Generated: {NOW.strftime("%d/%m/%Y %H:%M")} &mdash; {n_sources} data sources</div>

<div class="pipeline">
  <div class="stage">
    <div class="label">L0 Raw</div>
    <div class="num">{total_l0_records:,}</div>
    <div class="detail">records across {n_sources} sources</div>
  </div>
  <div class="arrow">&#10132;</div>
  <div class="stage">
    <div class="label">L1 Contacts</div>
    <div class="num">{total_l1_contacts:,}</div>
    <div class="detail">contacts extracted</div>
  </div>
  <div class="arrow">&#10132;</div>
  <div class="stage">
    <div class="label">L1 Interactions</div>
    <div class="num">{total_l1_interactions:,}</div>
    <div class="detail">interactions extracted</div>
  </div>
  <div class="arrow">&#10132;</div>
  <div class="stage">
    <div class="label">L2 Merge</div>
    <div class="num">{l2_total:,}</div>
    <div class="detail">unified contacts</div>
  </div>
</div>

<div class="cards">
  <div class="card ok">OK: {ok}</div>
  <div class="card stale">Stale: {stale}</div>
  <div class="card critico">Critical: {critico}</div>
</div>
<table>
<thead>
<tr>
  <th>Source</th>
  <th colspan="2" style="text-align:center;border-bottom:3px solid #3b82f6">L0 (raw)</th>
  <th colspan="3" style="text-align:center;border-bottom:3px solid #8b5cf6">L1 (enriched)</th>
  <th colspan="2" style="text-align:center;border-bottom:3px solid #ec4899">L2 (merge)</th>
  <th>Frequency</th>
  <th>Status</th>
  <th>Gap / Note</th>
</tr>
<tr>
  <th></th>
  <th style="text-align:right;font-weight:400;font-style:italic">Records</th>
  <th style="font-weight:400;font-style:italic">Last</th>
  <th style="text-align:right;font-weight:400;font-style:italic">Contacts</th>
  <th style="text-align:right;font-weight:400;font-style:italic">Interac.</th>
  <th style="font-weight:400;font-style:italic">Last</th>
  <th style="text-align:right;font-weight:400;font-style:italic">Contacts</th>
  <th style="text-align:center;font-weight:400;font-style:italic">L1&#8594;L2</th>
  <th></th>
  <th></th>
  <th></th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
{l3_html}
<script>
function refreshReport(btn) {{
  btn.classList.add('loading');
  btn.innerHTML = '&#8987; Refreshing...';
  fetch('http://127.0.0.1:19876/refresh', {{mode:'cors'}})
    .then(r => {{ if(r.ok) location.reload(); else throw new Error(); }})
    .catch(() => {{
      btn.innerHTML = '&#9888; Server not running';
      btn.title = 'Run: python xs-util-freshness.py --serve';
      setTimeout(() => {{
        btn.classList.remove('loading');
        btn.innerHTML = '&#8635; Refresh';
      }}, 3000);
    }});
}}
</script>
</body>
</html>"""





def print_terminal(sources: list[dict]) -> None:
    colors = {"OK": "\033[92m", "STALE": "\033[93m", "CRITICAL": "\033[91m", "MISSING": "\033[91m"}
    reset = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"

    main_sources = [s for s in sources if s["source"] != "Cross-source"]
    l2_total = main_sources[0].get("l2_total", 0) if main_sources else 0
    total_l0 = sum(s.get("records") or 0 for s in main_sources)
    total_l1c = sum(s.get("l1_contacts") or 0 for s in main_sources)
    total_l1i = sum(s.get("l1_interactions") or 0 for s in main_sources)

    print(f"\n{bold}SBK Data Freshness — {NOW.strftime('%d/%m/%Y %H:%M')}{reset}")
    print(
        f"Pipeline: {total_l0:,} records L0 → {total_l1c:,} contacts L1 + {total_l1i:,} interactions → {green}{l2_total:,} contacts L2{reset}\n"
    )

    header = (
        f"{'Source':<18} {'L0 rec':>8} {'L0 ago':<7} {'L1 cont':>8} {'L1 int':>8} {'L1 ago':<7} "
        f"{'L2 cont':>8} {'L1>L2':>6} {'Freq':<12} {'Status':<10} {'Gap'}"
    )
    print(f"{bold}{header}{reset}")
    print("─" * 140)

    ok = stale = critico = 0
    for s in main_sources:
        status = freshness_status(s.get("l1") or s.get("l2"), s["freq_days"])
        color = colors.get(status, "")
        if status == "OK":
            ok += 1
        elif status == "STALE":
            stale += 1
        else:
            critico += 1

        gap = (s["gap"][:30] + "..") if len(s.get("gap", "")) > 32 else s.get("gap", "")
        l0_rec = f"{s['records']:,}" if s.get("records") else f"{dim}  —{reset}"
        l1c = f"{s['l1_contacts']:,}" if s.get("l1_contacts") else f"{dim}  —{reset}"
        l1i = f"{s['l1_interactions']:,}" if s.get("l1_interactions") else f"{dim}  —{reset}"
        l2c_val = s.get("l2_contacts", 0)
        l2c = f"{l2c_val:,}" if l2c_val else f"{dim}  —{reset}"
        tp = s.get("l1_to_l2_pct")
        if tp is not None:
            tp_color = green if tp >= 90 else (yellow if tp >= 50 else red)
            tp_str = f"{tp_color}{tp:.0f}%{reset}"
        else:
            tp_str = f"{dim}  —{reset}"

        row = (
            f"{s['source']:<18} "
            f"{l0_rec:>8} "
            f"{elapsed_str(s['l0']):<7} "
            f"{l1c:>8} "
            f"{l1i:>8} "
            f"{elapsed_str(s['l1']):<7} "
            f"{l2c:>8} "
            f"{tp_str:>6} "
            f"{s['freq']:<12} "
            f"{color}{status:<10}{reset} "
            f"{gap}"
        )
        print(row)

    print("─" * 140)
    print(
        f"\n{bold}Summary:{reset} {colors['OK']}OK: {ok}{reset}  {colors['STALE']}STALE: {stale}{reset}  {colors['CRITICAL']}CRITICAL: {critico}{reset}\n"
    )
    stampa_copertura_attio(bold, reset)


def stampa_copertura_attio(bold: str = "", reset: str = "") -> None:
    ""











    f = DATA_ROOT / "attio" / "_coverage.json"
    if not f.exists():
        return
    try:
        c = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    meeting = c.get("meetings") or 0
    reg = c.get("recordings_in_api") or 0
    quota = f"{reg / meeting * 100:.0f}%" if meeting else "n/a"
    print(f"{bold}Attio coverage{reset} (from _coverage.json of {str(c.get('at', ''))[:16]})")
    print(f"  meetings: {meeting}  ·  recordings in API: {reg}  ·  covered: {quota}")
    per_stato = c.get("per_stato") or {}
    if per_stato:
        print("  by status: " + " · ".join(f"{k} {v}" for k, v in sorted(per_stato.items())))
    spariti = c.get("stub_marcati_recording_gone") or 0
    if spariti:
        print(f"  stubs with recording gone: {spariti}")
    errori = c.get("meeting_con_errore") or []
    if errori:
        print(f"  ⚠️  {len(errori)} meetings not scanned: {errori[:5]}")




    for ws_dir in ATTIO_WORKSPACE_DIRS.values():
        ws = ws_dir.name
        m = ws_dir / "lookups" / "people-emails.json"
        if not m.exists():
            continue
        try:
            n = len(json.loads(m.read_text()))
        except (OSError, ValueError):
            continue
        print(f"  {ws}: {n} records with mapped email (lookups/people-emails.json)")
    print()





def print_markdown(sources: list[dict]) -> None:
    main_sources = [s for s in sources if s["source"] != "Cross-source"]
    l2_total = main_sources[0].get("l2_total", 0) if main_sources else 0
    total_l0 = sum(s.get("records") or 0 for s in main_sources)
    total_l1c = sum(s.get("l1_contacts") or 0 for s in main_sources)
    total_l1i = sum(s.get("l1_interactions") or 0 for s in main_sources)

    print(f"# Data Freshness — {NOW.strftime('%d/%m/%Y %H:%M')}\n")
    print(
        f"Pipeline: {total_l0:,} rec L0 → {total_l1c:,} contacts + {total_l1i:,} interactions L1 → {l2_total:,} contacts L2\n"
    )
    print(
        "| Source | L0 rec | L0 ago | L1 contacts | L1 interac | L1 ago | L2 contacts | L1>L2 | Freq | Status | Gap |"
    )
    print(
        "|----------|-------:|-------|------------:|-----------:|-------|------------:|------:|------|-------|-----|"
    )
    for s in main_sources:
        status = freshness_status(s.get("l1") or s.get("l2"), s["freq_days"])
        gap = s.get("gap", "")
        l0_rec = f"{s['records']:,}" if s.get("records") else ""
        l1c = f"{s['l1_contacts']:,}" if s.get("l1_contacts") else ""
        l1i = f"{s['l1_interactions']:,}" if s.get("l1_interactions") else ""
        l2c = f"{s['l2_contacts']:,}" if s.get("l2_contacts") else ""
        tp = s.get("l1_to_l2_pct")
        tp_str = f"{tp:.0f}%" if tp is not None else ""
        print(
            f"| {s['source']} | {l0_rec} | {elapsed_str(s['l0'])} | {l1c} | {l1i} | {elapsed_str(s['l1'])} | {l2c} | {tp_str} | {s['freq']} | {status} | {gap} |"
        )





def regenerate_html() -> Path:
    ""
    global NOW  # noqa: PLW0603
    NOW = datetime.now()
    sources = collect_sources()
    html = generate_html(sources)
    out = DATA_ROOT / "data-freshness.html"
    out.write_text(html)
    return out


def run_server(port: int = 19876) -> None:
    ""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    report_path = DATA_ROOT / "data-freshness.html"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/refresh":
                regenerate_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"ok")
            elif self.path in ("/", "/index.html"):
                if not report_path.exists():
                    regenerate_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(report_path.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass

    regenerate_html()
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Server running: {url}")
    print("Press Ctrl+C to stop")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="SBK Data Freshness Report")
    parser.add_argument(
        "--html", action="store_true", help="Generate HTML report and open in browser"
    )
    parser.add_argument("--md", action="store_true", help="Output markdown table")
    parser.add_argument(
        "--serve", action="store_true", help="Start local server with live refresh button"
    )
    parser.add_argument("--port", type=int, default=19876, help="Server port (default: 19876)")
    args = parser.parse_args()

    if args.serve:
        run_server(args.port)
    elif args.html:
        out = regenerate_html()
        print(f"Report saved: {out}")
        webbrowser.open(f"file://{out}")
    elif args.md:
        sources = collect_sources()
        print_markdown(sources)
    else:
        sources = collect_sources()
        print_terminal(sources)


if __name__ == "__main__":
    main()
