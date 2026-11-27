""








from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sbk_config import (
    CASCADE_DEBOUNCE,
    CASCADE_DEBOUNCE_CEILING,
    CASCADE_DEBOUNCE_FLOOR,
    CASCADE_RULES,
    CASCADES_OFF_FLAG,
    EVENTS_DIR,
    automatic_cascades_on,
    get_event_velocity,
    get_event_watermark,
    record_event_velocity,
    save_event_watermark,
)

_TOOLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TOOLS_DIR.parent

log = logging.getLogger("sbk.event-bus")


class EventBus:
    ""

    @staticmethod
    def emit(source: str, stage: str, **metadata) -> Path:
        ""









        EVENTS_DIR.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(UTC)
        ts_str = ts.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{ts_str}_{source}_{stage}.json"

        event = {
            "source": source,
            "stage": stage,
            "ts": ts.isoformat(),
            "emitted_at": ts.isoformat(),
            **metadata,
        }

        event_path = EVENTS_DIR / filename
        event_path.write_text(json.dumps(event, indent=2, default=str))
        record_event_velocity(source)
        log.info(f"Event emitted: {source}/{stage} -> {filename}")
        return event_path

    @staticmethod
    def pending(max_age_hours: int = 24) -> list[dict]:
        ""







        if not EVENTS_DIR.exists():
            return []

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        events = []

        for f in sorted(EVENTS_DIR.glob("*.json")):
            try:


                parts = f.stem.split("_")

                if len(parts) >= 5:
                    fn_stage = parts[-1]
                    fn_source = parts[-2]
                    wm_ts = get_event_watermark(fn_source, fn_stage)
                    if wm_ts:


                        try:
                            file_mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
                            wm_dt = datetime.fromisoformat(wm_ts)
                            if wm_dt.tzinfo is None:
                                wm_dt = wm_dt.replace(tzinfo=UTC)
                            if file_mtime <= wm_dt:


                                data = json.loads(f.read_text())
                                if data.get("processed"):
                                    continue
                        except (OSError, ValueError):
                            pass

                data = json.loads(f.read_text())
                if data.get("processed"):
                    continue
                event_ts = datetime.fromisoformat(data["ts"])
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                if event_ts < cutoff:
                    continue
                data["_file"] = str(f)
                events.append(data)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                log.warning(f"Skipping malformed event {f.name}: {e}")

        return events

    @staticmethod
    def process(dry_run: bool = False) -> list[dict]:
        ""






        events = EventBus.pending()
        if not events:
            log.info("No pending events")
            return []

        now = datetime.now(UTC)


        target_events: dict[str, list[dict]] = {}

        for ev in events:
            key = (ev["source"], ev["stage"])
            target = CASCADE_RULES.get(key)
            if target:
                target_events.setdefault(target, []).append(ev)
            else:
                _mark_processed(ev, "no_cascade_rule")



        skip_targets = []
        for target, evts in list(target_events.items()):
            if all(ev.get("output_changed") is False for ev in evts):
                log.info(f"Skip: {target} — all {len(evts)} events have output_changed=False")
                for ev in evts:
                    _mark_processed(ev, "no_change")
                skip_targets.append(target)

        for t in skip_targets:
            del target_events[t]

        actions = []

        for target, evts in target_events.items():
            latest_ts = max(
                datetime.fromisoformat(e["ts"]).replace(tzinfo=UTC)
                if datetime.fromisoformat(e["ts"]).tzinfo is None
                else datetime.fromisoformat(e["ts"])
                for e in evts
            )


            is_pipeline = "xs-pipeline-run" in target
            if is_pipeline:

                sources_in_batch = {e["source"] for e in evts}


                base_debounce = min(
                    CASCADE_DEBOUNCE.get(s, CASCADE_DEBOUNCE["default"]) for s in sources_in_batch
                )

                dominant_source = max(
                    sources_in_batch,
                    key=lambda s: get_event_velocity(s).get("count", 0),
                )
                velocity = get_event_velocity(dominant_source)
                event_count = velocity.get("count", 0)

                if event_count > 10:

                    debounce_sec = max(CASCADE_DEBOUNCE_FLOOR, base_debounce // 4)
                elif event_count >= 3:

                    debounce_sec = base_debounce
                else:

                    debounce_sec = min(CASCADE_DEBOUNCE_CEILING, base_debounce * 2)

                debounce_delta = timedelta(seconds=debounce_sec)
                if (now - latest_ts) < debounce_delta:
                    age_sec = (now - latest_ts).total_seconds()
                    log.info(
                        f"Debounce: {target} has event {age_sec:.0f}s ago "
                        f"(need {debounce_sec}s for {sources_in_batch}), skipping"
                    )
                    continue

            log.info(f"Cascade: {len(evts)} events -> {target}")

            if not dry_run:
                success = _run_cascade(target)
            else:
                success = True
                log.info(f"  [dry-run] Would run: {target}")

            status = "completed" if success else "failed"
            for ev in evts:
                _mark_processed(ev, status)


            if status == "completed":
                _update_watermarks(evts)

            actions.append(
                {
                    "target": target,
                    "events_count": len(evts),
                    "status": status,
                    "sources": list({e["source"] for e in evts}),
                }
            )

        return actions

    @staticmethod
    def cleanup(max_age_hours: int = 24) -> int:
        ""



        if not EVENTS_DIR.exists():
            return 0

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        removed = 0

        for f in EVENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                event_ts = datetime.fromisoformat(data["ts"])
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                if event_ts < cutoff:
                    f.unlink()
                    removed += 1
            except (json.JSONDecodeError, KeyError, OSError):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

        if removed:
            log.info(f"Cleanup: removed {removed} old events")
        return removed

    @staticmethod
    def recent(limit: int = 50) -> list[dict]:
        ""



        if not EVENTS_DIR.exists():
            return []

        events = []
        for f in sorted(EVENTS_DIR.glob("*.json"), reverse=True):
            if len(events) >= limit:
                break
            try:
                data = json.loads(f.read_text())
                data["_file"] = f.name
                events.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        return events


def _update_watermarks(events: list[dict]) -> None:
    ""

    groups: dict[tuple[str, str], list[str]] = {}
    for ev in events:
        key = (ev["source"], ev["stage"])
        groups.setdefault(key, []).append(ev["ts"])

    for (source, stage), timestamps in groups.items():
        latest_ts = max(timestamps)
        try:
            save_event_watermark(source, stage, latest_ts, len(timestamps))
        except OSError as e:
            log.warning(f"Failed to update watermark for {source}/{stage}: {e}")


def _mark_processed(event: dict, status: str) -> None:
    ""
    file_path = event.get("_file")
    if not file_path:
        return
    p = Path(file_path)
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text())
        data["processed"] = True
        data["processed_at"] = datetime.now(UTC).isoformat()
        data["processed_status"] = status
        p.write_text(json.dumps(data, indent=2, default=str))
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to mark event processed: {e}")












def _run_cascade(target: str) -> bool:
    ""
    if not automatic_cascades_on():
        log.warning(
            "Automatic cascades: off. Cascade '%s' not started. "
            "Events stay queued; run the pipeline manually "
            "(uv run python tools/cross-source/xs-pipeline-run.py --propagate). "
            "To switch them on: uv run python tools/util/sb-pipeline-ctl.py on (removes %s)",
            target,
            CASCADES_OFF_FLAG,
        )
        return False

    parts = target.split()
    script_rel = parts[0]
    extra_args = parts[1:]

    script_path = _TOOLS_DIR / script_rel
    if not script_path.exists():
        log.error(f"Cascade script not found: {script_path}")
        return False

    cmd = [sys.executable, str(script_path)] + extra_args
    log.info(f"  Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2400,
            cwd=str(_PROJECT_ROOT),
        )
        for line in (result.stdout or "").strip().split("\n")[-3:]:
            if line:
                log.info(f"    {line}")





        if result.returncode == 0:
            log.info(f"  Cascade completed: {script_rel}")
            return True
        if result.returncode == 2:
            log.warning(
                "  Cascade incompleta (rc=2): %s — %s",
                script_rel,
                (result.stderr or "")[:300],
            )
            return True
        if result.returncode == 75:
            log.info(
                f"  Cascade not started, lock held: {script_rel}; the events stay queued"
            )
            return False
        log.error(f"  Cascade failed (rc={result.returncode}): {result.stderr[:300]}")
        return False
    except subprocess.TimeoutExpired:
        log.error(f"  Cascade timed out: {script_rel}")
        return False
    except Exception as e:
        log.error(f"  Cascade error: {e}")
        return False
