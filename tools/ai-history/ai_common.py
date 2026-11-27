"""Shared pieces of the AI-history readers (ai-l0-*.py).

Output contract (the "how you work" builder reads it):

    $SBK_DATA_ROOT/ai-history/messages.jsonl      (default ~/.sbk-data)

one JSON object per line, one line per message YOU wrote, with exactly the
fields in FIELDS:

    source      "claude-code" | "chatgpt" | "claude-ai" | "manus" | <--source of a generic import>
    session_id  the conversation / session id given by the tool (or a stable id made from the file)
    project     the project or folder the conversation belongs to, "" when the export does not say
    ts          ISO 8601 UTC, "YYYY-MM-DDTHH:MM:SSZ", "" when the export has no time
    text        what you typed, cleaned of tool wrappers and with secrets redacted

Each reader owns the lines of its own source. A full run replaces them; a run
narrowed by --since or --project adds to them (duplicates are skipped). Lines of
other sources are never touched. The file is rewritten atomically and sorted by
(ts, source, session_id).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

FIELDS: tuple[str, ...] = ("source", "session_id", "project", "ts", "text")

# Same rule as sbk_config.DATA_ROOT: an empty SBK_DATA_ROOT counts as unset.
# Kept local so the readers run with the standard library alone.
DATA_ROOT = Path(os.environ.get("SBK_DATA_ROOT") or str(Path.home() / ".sbk-data")).expanduser()


def output_path() -> Path:
    root = Path(os.environ.get("SBK_DATA_ROOT") or str(DATA_ROOT)).expanduser()
    return root / "ai-history" / "messages.jsonl"


def make_record(source: str, session_id: str, project: str, ts: str, text: str) -> dict:
    return {
        "source": source,
        "session_id": str(session_id or ""),
        "project": str(project or ""),
        "ts": ts or "",
        "text": text,
    }


def iso_utc(value) -> str:
    """Normalise an epoch number or an ISO string to YYYY-MM-DDTHH:MM:SSZ ("" if unknown)."""
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=UTC)
        else:
            s = str(value).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return ""


def parse_since(value: str | None) -> str:
    """--since accepts YYYY-MM-DD or a full ISO time; returns the comparable UTC string."""
    if not value:
        return ""
    out = iso_utc(value if "T" in value else value + "T00:00:00+00:00")
    if not out:
        raise SystemExit(f"--since: not a date: {value!r} (use YYYY-MM-DD)")
    return out


def stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _key(rec: dict) -> tuple:
    return (
        rec["source"],
        rec["session_id"],
        rec["ts"],
        hashlib.sha1(rec["text"].encode("utf-8")).hexdigest(),
    )


def write_messages(
    records: Iterable[dict],
    owns: Callable[[dict], bool],
    replace: bool,
    path: Path | None = None,
) -> dict:
    """Merge `records` into messages.jsonl.

    owns(rec)  True for existing lines this run is responsible for.
    replace    True: drop every existing line `owns` claims, then add `records`.
               False: keep existing lines, add `records` that are not already there.
    Returns counts {"kept_other": n, "kept_own": n, "added": n, "total": n}.
    """
    path = path or output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and all(f in rec for f in FIELDS):
                    existing.append({f: rec[f] for f in FIELDS})
    kept_other = [r for r in existing if not owns(r)]
    kept_own = [] if replace else [r for r in existing if owns(r)]
    seen = {_key(r) for r in kept_other + kept_own}
    added = 0
    merged = kept_other + kept_own
    for rec in records:
        rec = {f: rec[f] for f in FIELDS}
        k = _key(rec)
        if k in seen:
            continue
        seen.add(k)
        merged.append(rec)
        added += 1
    merged.sort(key=lambda r: (r["ts"], r["source"], r["session_id"]))
    fd, tmp = tempfile.mkstemp(prefix=".messages-", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            for rec in merged:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {
        "kept_other": len(kept_other),
        "kept_own": len(kept_own),
        "added": added,
        "total": len(merged),
    }


def write_private(path: Path | str, text: str) -> None:
    """Write `text` to `path` readable by you only (mode 0600), also when the file exists."""
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    os.chmod(path, 0o600)


def print_counts(title: str, counts: dict, indent: str = "  ") -> None:
    print(title)
    if not counts:
        print(f"{indent}(none)")
        return
    width = max(len(str(k)) for k in counts)
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"{indent}{str(k).ljust(width)}  {v}")
