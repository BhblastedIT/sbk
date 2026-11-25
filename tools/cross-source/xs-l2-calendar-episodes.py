#!/usr/bin/env python3
""

































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

from episode_schema import (  # noqa: E402
    Participant,  # noqa: E402
    episode_id_for,
    episode_to_dict,
    make_episode,
    participant_to_dict,
)

from sbk_config import DATA_ROOT, safe_write_json  # noqa: E402

log = logging.getLogger("sbk-xs-l2-calendar-episodes")

EPISODES_DIR = DATA_ROOT / "knowledge" / "episodes"
PERSON_DIR = DATA_ROOT / "knowledge" / "entities" / "person"
CAL_GLOB = "calendars/*/events.parquet"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def build_email_index() -> tuple[dict[str, str], dict[str, str]]:
    ""
    email2pid: dict[str, str] = {}
    pid2name: dict[str, str] = {}
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
        pid2name[pid] = d.get("canonical_name", "")
        for fact in d.get("facts", []):
            if fact.get("attribute") in ("contact.email", "identity.email"):
                em = str(fact.get("value", "")).strip().lower()
                if "@" in em:
                    email2pid.setdefault(em, pid)
    return email2pid, pid2name


def _year_of(occurred_at: str | None) -> str:
    if occurred_at and len(occurred_at) >= 4 and occurred_at[:4].isdigit():
        return occurred_at[:4]
    return "unknown"


def _episode_path(episode_id: str, occurred_at: str | None) -> Path:
    return EPISODES_DIR / _year_of(occurred_at) / f"{episode_id}.json"


def run(dry_run: bool) -> dict:
    email2pid, pid2name = build_email_index()
    log.info("Indice email->person_id: %d", len(email2pid))

    created = 0
    updated = 0
    parts_added = 0
    seen_events = 0
    illeggibili: list[str] = []

    for cal in sorted(DATA_ROOT.glob(CAL_GLOB)):
        names = [f.name for f in pq.read_schema(cal)]
        want = [
            c
            for c in ["id", "summary", "start_datetime", "organizer_email", "attendees"]
            if c in names
        ]
        rows = pq.read_table(cal, columns=want).to_pylist()
        for r in rows:
            ev_id = str(r.get("id") or "").strip()
            if not ev_id:
                continue
            seen_events += 1
            occurred = str(r.get("start_datetime") or "")[:10] or None
            summary = str(r.get("summary") or "").strip()

            emails: set[str] = set()
            emails |= {m.lower() for m in EMAIL_RE.findall(str(r.get("organizer_email") or ""))}
            emails |= {m.lower() for m in EMAIL_RE.findall(str(r.get("attendees") or ""))}
            resolved_pids = {email2pid[e] for e in emails if e in email2pid}
            if not resolved_pids:
                continue

            eid = episode_id_for("calendar_event", ev_id)
            path = _episode_path(eid, occurred)

            if path.exists():



                try:
                    d = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    illeggibili.append(str(path))
                    log.error("  episodio illeggibile, saltato: %s (%s)", path, type(e).__name__)
                    continue
                by_pid = {p.get("person_id") for p in d.get("participants", [])}
                new = [pid for pid in resolved_pids if pid not in by_pid]
                if not new:
                    continue
                for pid in new:
                    d.setdefault("participants", []).append(
                        participant_to_dict(
                            Participant(pid, pid2name.get(pid, ""), "attended", True)
                        )
                    )
                parts_added += len(new)
                updated += 1
                if not dry_run:
                    safe_write_json(path, d, indent=1, ensure_ascii=False)
            else:
                ep = make_episode(
                    "calendar_event",
                    ev_id,
                    source_file=str(cal.relative_to(DATA_ROOT)),
                    occurred_at=occurred,
                    title=summary,
                )
                ep.participants = [
                    Participant(pid, pid2name.get(pid, ""), "attended", True)
                    for pid in sorted(resolved_pids)
                ]
                ep.subjects = [summary] if summary else []
                parts_added += len(resolved_pids)
                created += 1
                if not dry_run:
                    safe_write_json(path, episode_to_dict(ep), indent=1, ensure_ascii=False)

    return {
        "seen_events": seen_events,
        "created": created,
        "updated": updated,
        "parts_added": parts_added,
        "illeggibili": illeggibili,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fase 4: eventi calendario come episodi meeting")
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
    log.info("xs-l2-calendar-episodes — %s", "DRY RUN" if dry_run else "LIVE")
    log.info("=" * 60)
    res = run(dry_run)
    log.info("")
    log.info("Summary (%s):", "DRY RUN" if dry_run else "APPLIED")
    log.info("  Eventi visti:               %d", res["seen_events"])
    log.info("  Episodi calendario creati:  %d", res["created"])
    log.info("  Episodi aggiornati:         %d", res["updated"])
    log.info("  Participant 'attended':     %d", res["parts_added"])
    if res["illeggibili"]:
        log.error(
            "  Episodi illeggibili saltati:%d (da riparare, elenco sopra)", len(res["illeggibili"])
        )
    if dry_run:
        log.info("  Esegui con --apply.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
