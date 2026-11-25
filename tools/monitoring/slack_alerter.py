#!/usr/bin/env python3
""










from __future__ import annotations

import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import slack_auth

from sbk_config import DATA_ROOT

log = logging.getLogger("sbk-slack-alerter")


def _ledger_log(service, method, direction, caller, status, detail=None, latency_ms=None):
    ""
    try:
        from monitoring.api_ledger import log_api_call

        log_api_call(
            service, method, direction, caller, status, detail=detail, latency_ms=latency_ms
        )
    except Exception:
        pass


# Alerts go to you as a DM. Your Slack user id comes from slack.own_user_id in
# sbk.config.json, otherwise from auth.test on your user token (tools/slack_auth.py).
ALERT_USER_ID = ""


def _alert_target() -> str:
    global ALERT_USER_ID
    if not ALERT_USER_ID:
        ALERT_USER_ID = slack_auth.own_user_id()
    return ALERT_USER_ID


ALERTS_STATE_FILE = DATA_ROOT / "system" / "slack-alerts-sent.json"


PENDING_ALERTS_FILE = DATA_ROOT / "system" / "slack-alerts-pending.json"


COOLDOWN_SECONDS = 6 * 3600


MAX_ALERTS_PER_HOUR = 10


MAX_ALERTS_PER_DAY = 30


def _get_token() -> str | None:
    """The optional bot token of your Slack app, otherwise your user token (chat:write)."""
    return slack_auth.notify_token()


def _load_alert_state() -> dict:
    ""
    if ALERTS_STATE_FILE.exists():
        try:
            return json.loads(ALERTS_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_alert_state(state: dict) -> None:
    ""
    ALERTS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _is_cooled_down(alert_key: str) -> bool:
    ""
    state = _load_alert_state()
    last_sent = state.get(alert_key, 0)
    return (time.time() - last_sent) < COOLDOWN_SECONDS


def _mark_sent(alert_key: str) -> None:
    ""
    state = _load_alert_state()
    state[alert_key] = time.time()

    cutoff = time.time() - 48 * 3600
    state = {k: v for k, v in state.items() if v > cutoff}
    _save_alert_state(state)


def _load_hourly_count() -> tuple[int, float]:
    ""
    state = _load_alert_state()
    window = state.get("_hour_window", 0.0)
    count = state.get("_hourly_count", 0)

    if time.time() - window > 3600:
        return 0, time.time()
    return count, window


def _increment_hourly_count() -> None:
    ""
    state = _load_alert_state()
    window = state.get("_hour_window", 0.0)
    if time.time() - window > 3600:
        state["_hour_window"] = time.time()
        state["_hourly_count"] = 1
    else:
        state["_hourly_count"] = state.get("_hourly_count", 0) + 1
    _save_alert_state(state)


def _load_daily_count() -> tuple[int, float]:
    ""
    state = _load_alert_state()
    window = state.get("_day_window", 0.0)
    count = state.get("_daily_count", 0)

    if time.time() - window > 86400:
        return 0, time.time()
    return count, window


def _increment_daily_count() -> None:
    ""
    state = _load_alert_state()
    window = state.get("_day_window", 0.0)
    if time.time() - window > 86400:
        state["_day_window"] = time.time()
        state["_daily_count"] = 1
    else:
        state["_daily_count"] = state.get("_daily_count", 0) + 1
    _save_alert_state(state)


def _load_pending_alerts() -> list[dict]:
    ""
    if PENDING_ALERTS_FILE.exists():
        try:
            return json.loads(PENDING_ALERTS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_pending_alerts(alerts: list[dict]) -> None:
    ""
    PENDING_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding="utf-8")


def _enqueue_alert(title: str, body: str, alert_key: str) -> None:
    ""
    pending = _load_pending_alerts()
    pending.append({"title": title, "body": body, "alert_key": alert_key, "ts": time.time()})
    _save_pending_alerts(pending)
    log.debug("Alert enqueued for digest: %s (total pending: %d)", alert_key, len(pending))


def flush_digest() -> bool:
    ""



    pending = _load_pending_alerts()
    if not pending:
        return True


    groups: dict[str, list[dict]] = {}
    for a in pending:
        key = a.get("title", "Alert")
        groups.setdefault(key, []).append(a)

    lines = [f":bell: *SBK Digest* ({len(pending)} alerts grouped)\n"]
    for title, items in groups.items():
        lines.append(f"*{title}* x{len(items)}")

        for item in items[:3]:
            snippet = item.get("body", "")[:120].replace("\n", " | ")
            lines.append(f"  - {snippet}")
        if len(items) > 3:
            lines.append(f"  _...and {len(items) - 3} more_")
        lines.append("")

    lines.append("Open the dashboard for the full details.")

    text = "\n".join(lines)


    daily_count, _dw = _load_daily_count()
    if daily_count >= MAX_ALERTS_PER_DAY:
        log.warning("Daily cap reached (%d/%d), digest suppressed", daily_count, MAX_ALERTS_PER_DAY)
        return True

    success = send_slack_dm(text, _bypass_rate_limit=True)
    if success:
        _increment_daily_count()
        _save_pending_alerts([])
        log.info("Digest flushed: %d alerts in 1 DM", len(pending))
    return success


def send_slack_dm(
    text: str, channel_id: str | None = None, *, _bypass_rate_limit: bool = False
) -> bool:
    ""









    daily_count, _dw = _load_daily_count()
    if daily_count >= MAX_ALERTS_PER_DAY:
        log.warning(
            "Daily cap reached (%d/%d per day), message suppressed",
            daily_count,
            MAX_ALERTS_PER_DAY,
        )
        return False


    if not _bypass_rate_limit:
        count, _window = _load_hourly_count()
        if count >= MAX_ALERTS_PER_HOUR:
            log.warning(
                "Rate limit reached (%d/%d per hour), message suppressed",
                count,
                MAX_ALERTS_PER_HOUR,
            )
            return False

    token = _get_token()
    if not token:
        log.error("No Slack token available — cannot send alert")
        return False

    target = channel_id or _alert_target()
    if not target:
        log.error("No Slack user id to send the alert to (slack.own_user_id or a user token)")
        return False
    payload = json.dumps(
        {
            "channel": target,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    t0 = time.monotonic()
    try:
        resp = urllib.request.urlopen(req, timeout=15)  # noqa: S310
        data = json.loads(resp.read())
        latency = int((time.monotonic() - t0) * 1000)
        if data.get("ok"):
            if not _bypass_rate_limit:
                _increment_hourly_count()
            _increment_daily_count()
            log.info("Slack alert sent to %s", target)
            _ledger_log(
                "slack", "chat.postMessage", "WRITE", "slack_alerter", "ok", latency_ms=latency
            )
            return True
        else:
            err = data.get("error", "unknown")
            log.error("Slack API error: %s", err)
            status = "rate_limited" if err == "ratelimited" else "error"
            _ledger_log(
                "slack",
                "chat.postMessage",
                "WRITE",
                "slack_alerter",
                status,
                detail=err,
                latency_ms=latency,
            )
            return False
    except (urllib.error.URLError, OSError) as e:
        latency = int((time.monotonic() - t0) * 1000)
        log.error("Slack send failed: %s", e)
        _ledger_log(
            "slack",
            "chat.postMessage",
            "WRITE",
            "slack_alerter",
            "error",
            detail=str(e)[:200],
            latency_ms=latency,
        )
        return False


def alert_source_critico(source_name: str, last_update: str, elapsed: str = "") -> bool:
    ""









    alert_key = f"source_critico:{source_name}"

    if _is_cooled_down(alert_key):
        log.debug("Alert %s skipped (cooldown)", alert_key)
        return True

    elapsed_str = f" ({elapsed})" if elapsed else ""
    text = (
        f":warning: *SBK Alert: {source_name} is stale*\n"
        f"Last update: {last_update}{elapsed_str}\n"
        f"Action needed: refresh this source."
    )

    success = send_slack_dm(text)
    if success:
        _mark_sent(alert_key)
    return success


def alert_pipeline_failure(
    script_name: str, error_message: str, retry_count: int, source: str = ""
) -> bool:
    ""










    alert_key = f"pipeline_failure:{script_name}"

    if _is_cooled_down(alert_key):
        log.debug("Alert %s skipped (cooldown)", alert_key)
        return True

    text = (
        f":red_circle: *SBK Pipeline Failure*\n"
        f"Script: `{script_name}`\n"
        f"Source: {source or 'N/A'}\n"
        f"Retries: {retry_count} failed attempts\n"
        f"Error: ```{error_message[:500]}```\n"
        f"Needs a manual fix."
    )

    success = send_slack_dm(text)
    if success:
        _mark_sent(alert_key)
    return success


def alert_custom(title: str, body: str, alert_key: str | None = None) -> bool:
    ""











    if alert_key and _is_cooled_down(alert_key):
        log.debug("Custom alert %s skipped (cooldown)", alert_key)
        return True


    count, _window = _load_hourly_count()
    if count >= MAX_ALERTS_PER_HOUR:
        enqueue_key = alert_key or f"_anon:{int(time.time())}"
        _enqueue_alert(title, body, enqueue_key)
        if alert_key:
            _mark_sent(alert_key)
        return True

    text = f"*{title}*\n{body}"
    success = send_slack_dm(text)
    if success and alert_key:
        _mark_sent(alert_key)
    return success




if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import argparse

    parser = argparse.ArgumentParser(description="SBK Slack Alerter")
    parser.add_argument("--test", action="store_true", help="Send a test DM")
    parser.add_argument(
        "--test-stale",
        "--test-critico",
        dest="test_critico",
        metavar="SOURCE",
        help="Simulate a stale-source alert for SOURCE",
    )
    parser.add_argument("--test-failure", metavar="SCRIPT", help="Simulate pipeline failure alert")
    parser.add_argument(
        "--flush-digest", action="store_true", help="Flush pending alerts as digest"
    )
    parser.add_argument("--reset", action="store_true", help="Reset dedup state and pending alerts")
    parser.add_argument("--stats", action="store_true", help="Show alert stats")
    args = parser.parse_args()

    if args.test:
        ok = send_slack_dm(":white_check_mark: SBK Slack Alerter: test message OK")
        print(f"Test DM: {'sent' if ok else 'FAILED'}")
    elif args.test_critico:
        ok = alert_source_critico(args.test_critico, "2026-02-20T10:00:00", "2 days ago")
        print(f"Stale-source alert for {args.test_critico}: {'sent' if ok else 'FAILED'}")
    elif args.test_failure:
        ok = alert_pipeline_failure(
            args.test_failure, "ConnectionError: API unavailable", 3, "email"
        )
        print(f"Failure alert for {args.test_failure}: {'sent' if ok else 'FAILED'}")
    elif args.flush_digest:
        ok = flush_digest()
        print(f"Digest flush: {'OK' if ok else 'FAILED'}")
    elif args.reset:
        _save_alert_state({})
        _save_pending_alerts([])
        print("Alert state and pending buffer reset")
    elif args.stats:
        state = _load_alert_state()
        pending = _load_pending_alerts()
        count, window = _load_hourly_count()
        daily_count, daily_window = _load_daily_count()
        dedup_entries = {k: v for k, v in state.items() if not k.startswith("_")}
        print(f"Dedup entries: {len(dedup_entries)}")
        print(f"Pending digest: {len(pending)}")
        print(f"Hourly count: {count}/{MAX_ALERTS_PER_HOUR}")
        print(f"Daily count: {daily_count}/{MAX_ALERTS_PER_DAY}")
    else:
        parser.print_help()
