#!/usr/bin/env python3
"""Follow-up reminders: the action items with a deadline in the next days or overdue (deadlines in Italian or
English parsed), with the contact details of the people involved, as Markdown or JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import SBKData, setup_logging

from sbk_config import (
    NLP_DIR,
    RELATIONSHIP_FACTS_FILE,
    check_inputs_changed,
    mark_last_run,
    save_input_checkpoint,
    to_display_tz,
    utc_now,
)

log = logging.getLogger("sbk-l3-followup")

STATE_FILE = NLP_DIR / "followup-state.json"



GIORNI_IT = {
    "lunedi": 0,
    "lunedì": 0,
    "martedi": 1,
    "martedì": 1,
    "mercoledi": 2,
    "mercoledì": 2,
    "giovedi": 3,
    "giovedì": 3,
    "venerdi": 4,
    "venerdì": 4,
    "sabato": 5,
    "domenica": 6,
}
DAYS_EN = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
MESI_IT = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}





def parse_deadline(deadline_str: str, meeting_date: str | None = None) -> datetime | None:
    ""












    if not deadline_str:
        return None

    text = deadline_str.strip().lower()
    today = datetime.now(UTC)


    ref = today
    if meeting_date:
        try:
            ref = datetime.strptime(meeting_date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass


    iso_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso_match:
        try:
            return datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
                tzinfo=UTC,
            )
        except ValueError:
            pass


    dmy_match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if dmy_match:
        try:
            return datetime(
                int(dmy_match.group(3)),
                int(dmy_match.group(2)),
                int(dmy_match.group(1)),
                tzinfo=UTC,
            )
        except ValueError:
            pass


    dm_match = re.match(r"(\d{1,2})/(\d{1,2})$", text)
    if dm_match:
        day, month = int(dm_match.group(1)), int(dm_match.group(2))
        try:
            dt = datetime(today.year, month, day, tzinfo=UTC)
            if dt < today - timedelta(days=180):
                dt = datetime(today.year + 1, month, day, tzinfo=UTC)
            return dt
        except ValueError:
            pass


    if text in ("oggi", "today"):
        return ref


    if text in ("domani", "tomorrow"):
        return ref + timedelta(days=1)


    if text in ("dopodomani", "day after tomorrow"):
        return ref + timedelta(days=2)


    n_tra = re.search(r"tra\s+(\d+)\s+giorn|in\s+(\d+)\s+day", text)
    if n_tra:
        n = int(n_tra.group(1) or n_tra.group(2))
        return ref + timedelta(days=n)


    n_months_match = re.search(r"tra\s+(\d+)\s+mes|in\s+(\d+)\s+month", text)
    if n_months_match:
        n = int(n_months_match.group(1) or n_months_match.group(2))
        month = ref.month + n
        year = ref.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(ref.day, monthrange(year, month)[1])
        return datetime(year, month, day, tzinfo=UTC)


    prossimo = re.search(r"prossim[oa]\s+(\w+)", text)
    if prossimo:
        day_str = prossimo.group(1)
        for day_name, weekday in GIORNI_IT.items():
            if day_str.startswith(day_name[:4]):
                days_ahead = (weekday - ref.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return ref + timedelta(days=days_ahead)
        for day_name, weekday in DAYS_EN.items():
            if day_str.startswith(day_name[:3]):
                days_ahead = (weekday - ref.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return ref + timedelta(days=days_ahead)


    next_day = re.search(r"next\s+(\w+)", text)
    if next_day:
        day_str = next_day.group(1)
        for day_name, weekday in DAYS_EN.items():
            if day_str.startswith(day_name[:3]):
                days_ahead = (weekday - ref.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return ref + timedelta(days=days_ahead)


    q_match = re.search(r"q([1-4])(?:\s+(\d{4}))?", text)
    if q_match:
        quarter = int(q_match.group(1))
        year = int(q_match.group(2)) if q_match.group(2) else today.year
        end_month = quarter * 3
        last_day = monthrange(year, end_month)[1]
        return datetime(year, end_month, last_day, tzinfo=UTC)


    if "fine settimana" in text or "end of week" in text:
        days_until_friday = (4 - ref.weekday()) % 7
        if days_until_friday == 0 and ref.weekday() > 4:
            days_until_friday = 7
        return ref + timedelta(days=max(days_until_friday, 1))


    if "fine mese" in text or "end of month" in text:
        if ref.month == 12:
            return datetime(ref.year + 1, 1, 1, tzinfo=UTC) - timedelta(days=1)
        return datetime(ref.year, ref.month + 1, 1, tzinfo=UTC) - timedelta(days=1)


    n_days = re.search(r"entro\s+(\d+)\s+giorn|within\s+(\d+)\s+day", text)
    if n_days:
        n = int(n_days.group(1) or n_days.group(2))
        return ref + timedelta(days=n)


    n_weeks = re.search(r"entro\s+(\d+)\s+settiman|within\s+(\d+)\s+week", text)
    if n_weeks:
        n = int(n_weeks.group(1) or n_weeks.group(2))
        return ref + timedelta(weeks=n)


    for day_name, weekday in GIORNI_IT.items():
        if day_name in text:
            days_ahead = (weekday - ref.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return ref + timedelta(days=days_ahead)


    for day_name, weekday in DAYS_EN.items():
        if day_name in text:
            days_ahead = (weekday - ref.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return ref + timedelta(days=days_ahead)


    for month_name, month_num in MESI_IT.items():
        month_match = re.search(rf"(\d{{1,2}})\s*{month_name}", text)
        if month_match:
            day = int(month_match.group(1))
            try:
                dt = datetime(today.year, month_num, day, tzinfo=UTC)
                if dt < today - timedelta(days=180):
                    dt = datetime(today.year + 1, month_num, day, tzinfo=UTC)
                return dt
            except ValueError:
                pass

    return None





_CACHED_DF: pd.DataFrame | None = None


def load_action_items() -> pd.DataFrame:
    ""




    global _CACHED_DF
    if _CACHED_DF is not None:
        return _CACHED_DF

    # Library function: the web dashboard calls it inside a request, so it never ends the process.
    # No file yet (the paid L3 extract writes it) = nothing to follow up yet: an empty frame, not cached.
    path = NLP_DIR / "action-items.parquet"
    if not path.exists():
        log.info(f"No action items yet ({path} is written by the L3 extract): nothing to follow up")
        return pd.DataFrame(
            {
                "meeting_id": pd.Series(dtype=str),
                "action_text": pd.Series(dtype=str),
                "_deadline_dt": pd.Series(dtype="datetime64[ns, UTC]"),
            }
        )

    df = pd.read_parquet(path)
    required = {"meeting_id", "action_text"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in action-items.parquet: {sorted(missing)}")


    if "_deadline_dt" not in df.columns:
        deadline_col = df.get("deadline", pd.Series(dtype=str))
        meeting_date_col = df.get("meeting_date", df.get("date", pd.Series(dtype=str)))

        parsed = []
        for dl, md in zip(
            deadline_col.fillna("").astype(str),
            meeting_date_col.fillna("").astype(str),
        ):
            if not dl or dl == "nan":
                parsed.append(pd.NaT)
            else:
                dt = parse_deadline(dl, md if md and md != "nan" else None)
                parsed.append(pd.Timestamp(dt) if dt else pd.NaT)
        df["_deadline_dt"] = parsed

    log.info(f"Loaded {len(df)} action items")
    _CACHED_DF = df
    return df


def _item_hash(meeting_id: str, action_text: str) -> str:
    ""
    key = f"{meeting_id}|{action_text}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]





def filter_actionable(
    df: pd.DataFrame,
    lookahead_days: int = 7,
    overdue_only: bool = False,
    person_filter: str | None = None,
) -> list[dict]:
    ""





    today = pd.Timestamp(datetime.now(UTC))
    cutoff = today + pd.Timedelta(days=lookahead_days)


    if "_deadline_dt" in df.columns:
        mask = df["_deadline_dt"].notna()
        if overdue_only:
            mask &= df["_deadline_dt"] < today
        else:
            mask &= df["_deadline_dt"] <= cutoff

        if person_filter:
            assignee_col = df.get("assignee", df.get("owner", pd.Series("", index=df.index)))
            mask &= (
                assignee_col.fillna("").str.lower().str.contains(person_filter.lower(), na=False)
            )

        subset = df[mask].copy()

        results = []
        for _, row in subset.iterrows():
            parsed = row["_deadline_dt"].to_pydatetime()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            is_overdue = parsed < today.to_pydatetime()
            days_until = (parsed - today.to_pydatetime()).days
            assignee = str(row.get("assignee", "") or row.get("owner", "") or "")
            meeting_date = str(row.get("meeting_date", "") or row.get("date", "") or "")

            results.append(
                {
                    "meeting_id": str(row.get("meeting_id", "")),
                    "action_text": str(row.get("action_text", "")),
                    "assignee": assignee,
                    "deadline_raw": str(row.get("deadline", "") or ""),
                    "deadline_parsed": parsed.strftime("%Y-%m-%d"),
                    "meeting_date": meeting_date[:10] if meeting_date else "",
                    "meeting_title": str(
                        row.get("meeting_title", "") or row.get("title", "") or ""
                    ),
                    "source": str(row.get("source", "") or ""),
                    "is_overdue": is_overdue,
                    "days_until": days_until,
                    "urgency": "OVERDUE"
                    if is_overdue
                    else (
                        "TODAY"
                        if days_until == 0
                        else ("URGENT" if days_until <= 2 else "UPCOMING")
                    ),
                    "hash": _item_hash(
                        str(row.get("meeting_id", "")), str(row.get("action_text", ""))
                    ),
                }
            )
    else:

        results = []
        for _, row in df.iterrows():
            deadline_str = str(row.get("deadline", "") or "")
            if not deadline_str or deadline_str == "nan":
                continue
            meeting_date = str(row.get("meeting_date", "") or row.get("date", "") or "")
            parsed = parse_deadline(deadline_str, meeting_date if meeting_date else None)
            if parsed is None:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if overdue_only:
                if parsed >= today.to_pydatetime():
                    continue
            elif parsed > cutoff.to_pydatetime():
                continue
            if person_filter:
                assignee = str(row.get("assignee", "") or row.get("owner", "") or "")
                if person_filter.lower() not in assignee.lower():
                    continue
            else:
                assignee = str(row.get("assignee", "") or row.get("owner", "") or "")

            is_overdue = parsed < today.to_pydatetime()
            days_until = (parsed - today.to_pydatetime()).days
            results.append(
                {
                    "meeting_id": str(row.get("meeting_id", "")),
                    "action_text": str(row.get("action_text", "")),
                    "assignee": assignee,
                    "deadline_raw": deadline_str,
                    "deadline_parsed": parsed.strftime("%Y-%m-%d"),
                    "meeting_date": meeting_date[:10] if meeting_date else "",
                    "meeting_title": str(
                        row.get("meeting_title", "") or row.get("title", "") or ""
                    ),
                    "source": str(row.get("source", "") or ""),
                    "is_overdue": is_overdue,
                    "days_until": days_until,
                    "urgency": "OVERDUE"
                    if is_overdue
                    else (
                        "TODAY"
                        if days_until == 0
                        else ("URGENT" if days_until <= 2 else "UPCOMING")
                    ),
                    "hash": _item_hash(
                        str(row.get("meeting_id", "")), str(row.get("action_text", ""))
                    ),
                }
            )

    results.sort(key=lambda x: x["deadline_parsed"])
    log.info(
        f"Filtered to {len(results)} actionable items "
        f"(lookahead={lookahead_days}d, overdue_only={overdue_only})"
    )
    return results





def enrich_with_contacts(items: list[dict], data: SBKData) -> dict[str, list[dict]]:
    ""



    grouped: dict[str, list[dict]] = {}

    for item in items:
        assignee = item.get("assignee", "").strip()
        person_key = assignee if assignee else "(unassigned)"


        if assignee:
            person = data.resolve_person(assignee)
            if person:
                item["person_email"] = person.get("email", "")
                item["person_org"] = person.get("organization") or person.get("attio_company") or ""
                person_key = person.get("name", assignee) or assignee

        grouped.setdefault(person_key, []).append(item)

    log.info(f"Grouped into {len(grouped)} people/assignees")
    return grouped





def generate_markdown(grouped: dict[str, list[dict]], today: datetime) -> str:
    ""
    lines = [
        f"# Follow-up Reminders — {today.strftime('%d/%m/%Y')}",
        "",
    ]

    total = sum(len(items) for items in grouped.values())
    overdue = sum(1 for items in grouped.values() for i in items if i["is_overdue"])
    lines.append(f"**{total} azioni** con deadline ({overdue} scadute)\n")

    urgency_order = {"OVERDUE": 0, "TODAY": 1, "URGENT": 2, "UPCOMING": 3}

    for person, items in sorted(grouped.items()):
        lines.append(f"## {person}")
        items_sorted = sorted(items, key=lambda x: urgency_order.get(x["urgency"], 9))

        for item in items_sorted:
            urgency_badge = {
                "OVERDUE": "**SCADUTO**",
                "TODAY": "**OGGI**",
                "URGENT": "URGENTE",
                "UPCOMING": "prossimo",
            }.get(item["urgency"], "")

            lines.append(f"- [{urgency_badge}] {item['action_text']}")
            lines.append(f"  Deadline: {item['deadline_parsed']} (raw: {item['deadline_raw']})")
            if item.get("meeting_title"):
                lines.append(f"  Da: {item['meeting_title']} ({item['meeting_date']})")
            lines.append("")

    return "\n".join(lines)


def generate_json(grouped: dict[str, list[dict]]) -> str:
    ""
    output = {
        "generated_at": utc_now().isoformat(),
        "total_items": sum(len(items) for items in grouped.values()),
        "overdue_count": sum(1 for items in grouped.values() for i in items if i["is_overdue"]),
        "by_person": {},
    }
    for person, items in sorted(grouped.items()):
        output["by_person"][person] = items

    return json.dumps(output, indent=2, ensure_ascii=False)





def load_state() -> dict:
    ""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_hashes": [], "last_run": None}


def save_state(items: list[dict]) -> None:
    ""
    state = {
        "seen_hashes": [i["hash"] for i in items],
        "last_run": utc_now().isoformat(),
        "item_count": len(items),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info(f"State saved: {len(items)} items tracked in {STATE_FILE}")





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Follow-up reminders from action items")
    parser.add_argument("--days", type=int, default=7, help="Lookahead days (default: 7)")
    parser.add_argument("--person", metavar="NAME", help="Filter by assignee name")
    parser.add_argument("--overdue-only", action="store_true", help="Show only overdue items")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of markdown")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing state file")
    parser.add_argument("--force", action="store_true", help="Bypass incremental guard")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose, name="sbk-l3-followup")


    _action_items_file = NLP_DIR / "action-items.parquet"
    _guard_inputs = [_action_items_file, RELATIONSHIP_FACTS_FILE]
    if not args.force and not check_inputs_changed("followup", _guard_inputs):
        log.info("Incremental: inputs unchanged, skipping")
        mark_last_run("followup")
        return


    try:
        df = load_action_items()
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    items = filter_actionable(
        df,
        lookahead_days=args.days,
        overdue_only=args.overdue_only,
        person_filter=args.person,
    )

    if not items:
        print("No follow-ups found in the selected period.")
        return


    data = SBKData()
    grouped = enrich_with_contacts(items, data)


    if args.json:
        print(generate_json(grouped))
    else:
        print(generate_markdown(grouped, to_display_tz(utc_now())))


    if not args.dry_run:
        save_state(items)
        save_input_checkpoint("followup", _guard_inputs)
        mark_last_run("followup")
    else:
        log.info("Dry-run: state file not written")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-followup", source="followup", stage="l3", mark_run=False)
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
