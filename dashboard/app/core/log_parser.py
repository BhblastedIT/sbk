""






from __future__ import annotations

import re


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+)?(\d{2}:\d{2}:\d{2})")


_SEVERITY_PREFIX_RE = re.compile(
    r"(?:^|\s)(ERROR|WARNING|WARN|INFO|DEBUG|SUCCESS|CRITICAL)"
    r"(?:\s|:|]|\b)",
    re.IGNORECASE,
)


_STAGE_RUNNING_RE = re.compile(r"RUNNING:\s*(.+)", re.IGNORECASE)
_STAGE_SECTION_RE = re.compile(r"^={3,}\s*(.+?)\s*={3,}$")
_STAGE_ARROW_RE = re.compile(r"^-{2,}>\s*(.+)")


_METRICS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("rows", re.compile(r"(\d[\d,]*)\s+rows?\b", re.IGNORECASE)),
    ("contacts", re.compile(r"(\d[\d,]*)\s+contacts?\b", re.IGNORECASE)),
    ("messages", re.compile(r"(\d[\d,]*)\s+messages?\b", re.IGNORECASE)),
    ("files", re.compile(r"(\d[\d,]*)\s+files?\b", re.IGNORECASE)),
    ("records", re.compile(r"(\d[\d,]*)\s+records?\b", re.IGNORECASE)),
    ("chunks", re.compile(r"(\d[\d,]*)\s+chunks?\b", re.IGNORECASE)),
    ("events", re.compile(r"(\d[\d,]*)\s+events?\b", re.IGNORECASE)),
    ("emails", re.compile(r"(\d[\d,]*)\s+emails?\b", re.IGNORECASE)),
    ("downloaded", re.compile(r"[Dd]ownloaded\s+(\d[\d,]*)", re.IGNORECASE)),
    ("duration_s", re.compile(r"OK\s+in\s+([\d.]+)s", re.IGNORECASE)),
    ("saved", re.compile(r"[Ss]aved\s+(\d[\d,]*)", re.IGNORECASE)),
    ("skipped", re.compile(r"[Ss]kipped\s+(\d[\d,]*)", re.IGNORECASE)),
    ("errors_count", re.compile(r"(\d[\d,]*)\s+errors?\b", re.IGNORECASE)),
]


_ERROR_KEYWORDS = re.compile(r"\b(traceback|exception|error|failed|failure|fatal)\b", re.IGNORECASE)
_WARNING_KEYWORDS = re.compile(r"\b(warning|warn|deprecated|skipping|skip)\b", re.IGNORECASE)
_SUCCESS_KEYWORDS = re.compile(r"\b(completed|success|done|finished|saved|OK)\b", re.IGNORECASE)

_SEVERITY_MAP = {
    "error": "error",
    "critical": "error",
    "warning": "warning",
    "warn": "warning",
    "info": "info",
    "debug": "debug",
    "success": "success",
}


def strip_ansi(text: str) -> str:
    ""
    return _ANSI_RE.sub("", text)


def parse_log_line(raw: str) -> dict:
    ""










    cleaned = strip_ansi(raw).strip()


    timestamp = None
    ts_match = _TS_RE.search(cleaned)
    if ts_match:
        timestamp = ts_match.group(2)


    is_stage_header = False
    stage_name = None

    m = _STAGE_RUNNING_RE.search(cleaned)
    if m:
        is_stage_header = True
        stage_name = m.group(1).strip()
    else:
        m = _STAGE_SECTION_RE.search(cleaned)
        if m:
            is_stage_header = True
            stage_name = m.group(1).strip()
        else:
            m = _STAGE_ARROW_RE.search(cleaned)
            if m:
                is_stage_header = True
                stage_name = m.group(1).strip()


    severity = "info"
    sev_match = _SEVERITY_PREFIX_RE.search(cleaned)
    if sev_match:
        key = sev_match.group(1).lower()
        severity = _SEVERITY_MAP.get(key, "info")
    elif _ERROR_KEYWORDS.search(cleaned):
        severity = "error"
    elif _WARNING_KEYWORDS.search(cleaned):
        severity = "warning"
    elif _SUCCESS_KEYWORDS.search(cleaned):
        severity = "success"


    metrics = {}
    for name, pattern in _METRICS_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            val = m.group(1).replace(",", "")
            try:
                metrics[name] = float(val) if "." in val else int(val)
            except ValueError:
                pass

    return {
        "line": raw,
        "message": cleaned,
        "severity": severity,
        "timestamp": timestamp,
        "is_stage_header": is_stage_header,
        "stage_name": stage_name,
        "metrics": metrics,
    }


def summarize_job(parsed_lines: list[dict]) -> dict:
    ""









    error_count = 0
    warning_count = 0
    success_count = 0
    stages: list[str] = []
    agg_metrics: dict[str, int | float] = {}

    for pl in parsed_lines:
        if pl["severity"] == "error":
            error_count += 1
        elif pl["severity"] == "warning":
            warning_count += 1
        elif pl["severity"] == "success":
            success_count += 1

        if pl["is_stage_header"] and pl["stage_name"]:
            stages.append(pl["stage_name"])

        for k, v in pl.get("metrics", {}).items():
            agg_metrics[k] = agg_metrics.get(k, 0) + v


    for k, v in agg_metrics.items():
        if isinstance(v, float):
            agg_metrics[k] = round(v, 2)

    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "success_count": success_count,
        "total_lines": len(parsed_lines),
        "stages": stages,
        "metrics": agg_metrics,
    }
