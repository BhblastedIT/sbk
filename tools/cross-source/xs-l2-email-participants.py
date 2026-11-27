#!/usr/bin/env python3
"""Phase 4 of the episodes: adds the recipients of each email as participants of its episode, matched to people in
the knowledge base by email. Dry run by default; --apply writes.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT, EMAILS_DIR, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-xs-l2-email-participants")

EPISODES_DIR = DATA_ROOT / "knowledge" / "episodes"
PERSON_DIR = DATA_ROOT / "knowledge" / "entities" / "person"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def build_email_index() -> dict[str, str]:
    ""
    idx: dict[str, str] = {}
    if not PERSON_DIR.exists():
        return idx
    for f in PERSON_DIR.iterdir():
        if not f.name.endswith(".json") or f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pid = d.get("entity_id")
        if not pid:
            continue
        for fact in d.get("facts", []):
            if fact.get("attribute") in ("contact.email", "identity.email"):
                em = str(fact.get("value", "")).strip().lower()
                if "@" in em:
                    idx.setdefault(em, pid)
    return idx


def build_message_map() -> dict[str, dict[str, set[str]]]:
    ""
    mp: dict[str, dict[str, set[str]]] = {}
    paths = list(EMAILS_DIR.rglob("messages.parquet"))
    filtered = EMAILS_DIR / "filtered-messages.parquet"
    if filtered.exists():
        paths.append(filtered)
    for p in paths:
        try:
            names = [f.name for f in pq.read_schema(p)]
        except Exception:  # noqa: BLE001
            continue
        key_col = "message_id" if "message_id" in names else ("id" if "id" in names else None)
        if not key_col:
            continue
        want = [c for c in [key_col, "from_addr", "to_addr", "cc"] if c in names]
        rows = pq.read_table(p, columns=want).to_pylist()
        for r in rows:
            key = str(r.get(key_col) or "").strip()
            if not key:
                continue
            spoke = {m.lower() for m in EMAIL_RE.findall(str(r.get("from_addr") or ""))}
            received: set[str] = set()
            for fld in ("to_addr", "cc"):
                received |= {m.lower() for m in EMAIL_RE.findall(str(r.get(fld) or ""))}
            received -= spoke
            if not spoke and not received:
                continue
            slot = mp.setdefault(key, {"spoke": set(), "received": set()})
            slot["spoke"] |= spoke
            slot["received"] |= received
    return mp


def pid_name(email_idx_rev: dict[str, str], pid: str) -> str:
    return email_idx_rev.get(pid, "")


def enrich(dry_run: bool) -> dict:
    email_idx = build_email_index()
    log.info("Index email->person_id: %d", len(email_idx))
    msg_map = build_message_map()
    log.info("Emails indexed (message-key): %d", len(msg_map))


    pid_to_name: dict[str, str] = {}
    for f in PERSON_DIR.iterdir() if PERSON_DIR.is_dir() else []:
        if f.name.endswith(".json") and not f.name.startswith("_"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                pid_to_name[d.get("entity_id", "")] = d.get("canonical_name", "")
            except (json.JSONDecodeError, OSError):
                continue

    eps_touched = 0
    added_spoke = 0
    added_received = 0
    files_written = 0
    illeggibili: list[str] = []

    for y in sorted(EPISODES_DIR.iterdir()) if EPISODES_DIR.is_dir() else []:
        if not y.is_dir():
            continue
        for f in y.glob("ep_*.json"):


            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                illeggibili.append(str(f))
                log.error("  unreadable episode, skipped: %s (%s)", f, type(e).__name__)
                continue
            if d.get("source_type") != "email":
                continue
            rid = (d.get("record_id") or "").strip()
            slot = msg_map.get(rid)
            if not slot:
                continue

            participants = d.get("participants", [])
            by_pid = {p.get("person_id"): p for p in participants if p.get("person_id")}
            changed = False

            def _add(emails: set[str], attendance: str) -> int:
                nonlocal changed
                n = 0
                for em in emails:
                    pid = email_idx.get(em)
                    if not pid:
                        continue
                    if pid in by_pid:

                        if attendance == "spoke" and by_pid[pid].get("attendance") == "received":
                            by_pid[pid]["attendance"] = "spoke"
                            changed = True
                        continue
                    newp = {
                        "person_id": pid,
                        "name": pid_to_name.get(pid, ""),
                        "attendance": attendance,
                        "resolved": True,
                        "via": "email",
                    }
                    participants.append(newp)
                    by_pid[pid] = newp
                    changed = True
                    n += 1
                return n

            added_spoke += _add(slot["spoke"], "spoke")
            added_received += _add(slot["received"], "received")

            if changed:
                eps_touched += 1
                d["participants"] = participants
                if not dry_run:
                    safe_write_json(f, d, indent=1, ensure_ascii=False)
                    files_written += 1

    return {
        "eps_touched": eps_touched,
        "added_spoke": added_spoke,
        "added_received": added_received,
        "files_written": files_written,
        "illeggibili": illeggibili,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4: email recipients as participants")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    dry_run = not args.apply
    log.info("=" * 60)
    log.info("xs-l2-email-participants — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)
    res = enrich(dry_run)
    log.info("")
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Email episodes enriched:       %d", res["eps_touched"])
    log.info("  Participant 'spoke' added:     %d", res["added_spoke"])
    log.info("  Participant 'received' added:  %d", res["added_received"])
    log.info("  Files written:                 %d", res["files_written"])
    if res["illeggibili"]:
        log.error(
            "  Unreadable episodes skipped:   %d (to repair, list above)",
            len(res["illeggibili"]),
        )
    if dry_run:
        log.info("  Run with --apply.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
