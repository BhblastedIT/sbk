""






from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import slack_auth

from app.core.slack_rate_limiter import (
    IdempotencyViolation,
    RateLimitExceeded,
    check_rate_limit,
    get_limit_status,
)

log = logging.getLogger("sbk.dashboard.slack_msg")


def _ledger_log(service, method, direction, caller, status="ok", detail=None, latency_ms=None):
    ""
    try:
        from monitoring.api_ledger import log_api_call

        log_api_call(
            service, method, direction, caller, status, detail=detail, latency_ms=latency_ms
        )
    except Exception:
        pass


router = APIRouter(prefix="/api/slack", tags=["slack"])


def _get_send_token() -> str | None:
    """The optional bot token of your Slack app, otherwise your user token (tools/slack_auth.py)."""
    return slack_auth.notify_token()


class SlackMessage(BaseModel):
    channel_id: str
    text: str
    thread_ts: str | None = None
    idempotency_key: str | None = None


@router.post("/send")
async def send_slack_message(msg: SlackMessage, request: Request):
    ""





    client_ip = request.client.host if request.client else "unknown"


    try:
        check_rate_limit(client_ip, msg.idempotency_key)
    except RateLimitExceeded as e:
        log.warning("Slack rate limit exceeded for %s: %s", client_ip, e)
        return JSONResponse({"error": str(e)}, status_code=429)
    except IdempotencyViolation as e:
        log.warning("Slack idempotency violation for %s: %s", client_ip, e)
        return JSONResponse({"error": str(e)}, status_code=409)

    token = _get_send_token()
    if not token:
        return JSONResponse(
            {
                "error": (
                    "No Slack token. Sending uses your user token with the chat:write user "
                    "scope (Keychain sbk-slack/user-token or SLACK_USER_TOKEN), or the optional "
                    "bot token of the same app (Keychain sbk-slack/bot-token or SLACK_BOT_TOKEN)."
                )
            },
            status_code=503,
        )

    if not msg.text.strip():
        return JSONResponse({"error": "Empty message"}, status_code=400)

    payload: dict = {
        "channel": msg.channel_id,
        "text": msg.text,
        "unfurl_links": False,
    }
    if msg.thread_ts:
        payload["thread_ts"] = msg.thread_ts

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    try:
        import asyncio
        import time as _time

        t0 = _time.monotonic()
        resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=15)  # noqa: S310
        result = json.loads(resp.read())
        latency = int((_time.monotonic() - t0) * 1000)
        if result.get("ok"):
            _ledger_log(
                "slack", "chat.postMessage", "WRITE", "dashboard_slack_msg", latency_ms=latency
            )
            return {
                "status": "sent",
                "channel": result.get("channel", ""),
                "ts": result.get("ts", ""),
            }
        else:
            err = result.get("error", "unknown")
            log.error("Slack API error: %s", err)
            status = "rate_limited" if err == "ratelimited" else "error"
            _ledger_log(
                "slack",
                "chat.postMessage",
                "WRITE",
                "dashboard_slack_msg",
                status,
                detail=err,
                latency_ms=latency,
            )
            return JSONResponse({"error": err}, status_code=502)
    except (urllib.error.URLError, OSError) as e:
        log.error("Slack send failed: %s", e)
        _ledger_log(
            "slack",
            "chat.postMessage",
            "WRITE",
            "dashboard_slack_msg",
            "error",
            detail=str(e)[:200],
        )
        return JSONResponse({"error": str(e)}, status_code=502)


@router.get("/limit-status")
def slack_limit_status(request: Request):
    ""










    client_ip = request.client.host if request.client else "unknown"
    return get_limit_status(client_ip)


@router.get("/contacts")
def slack_contacts(request: Request):
    ""
    try:
        bridge = request.app.state.bridge
        decay = bridge.get_decay_state()

        contacts = []
        for entry in decay:
            name = entry.get("name", "")
            slack_id = entry.get("slack_user_id", "")
            tier = entry.get("tier", "peripheral")
            if not name:
                continue
            contacts.append(
                {
                    "name": name,
                    "slack_id": slack_id,
                    "tier": tier,
                }
            )


        tier_order = {"inner": 0, "middle": 1, "outer": 2, "peripheral": 3}
        contacts.sort(key=lambda c: (tier_order.get(c["tier"], 9), c["name"]))
        return {"contacts": contacts[:50]}
    except Exception as e:
        log.warning("Failed to load Slack contacts: %s", e)
        return {"contacts": []}
