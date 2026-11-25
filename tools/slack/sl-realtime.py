#!/usr/bin/env python3
"""Slack real-time listener (optional): new messages through Socket Mode.

Needs, on the same personal Slack app: Socket Mode on, an app-level token (xapp-,
scope connections:write) and Event Subscriptions "on behalf of users" for the
message events. Your user token is used for the Web API calls.
"""




















from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from sbk_config import DATA_ROOT, SLACK_CONVERSATIONS_DIR, safe_write_json  # noqa: E402



REALTIME_STATE_FILE = DATA_ROOT / ".realtime-state.json"


SKIP_SUBTYPES = frozenset(
    {
        "bot_message",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "pinned_item",
    }
)

log = logging.getLogger("sbk.slack-realtime")





def _load_realtime_state() -> dict:
    ""
    if REALTIME_STATE_FILE.exists():
        try:
            return json.loads(REALTIME_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_realtime_state(state: dict) -> None:
    ""
    safe_write_json(REALTIME_STATE_FILE, state)


def _update_slack_state(**kwargs) -> None:
    ""
    state = _load_realtime_state()
    if "slack" not in state:
        state["slack"] = {}
    state["slack"].update(kwargs)
    _save_realtime_state(state)





def _get_app_level_token() -> str | None:
    ""

    token = os.environ.get("SBK_SLACK_APP_TOKEN") or os.environ.get("SLACK_APP_LEVEL_TOKEN")
    if token and token.startswith("xapp-"):
        return token


    from secrets_adapter import get_secret

    token = get_secret("sbk-slack", "app-level-token")
    if token and token.startswith("xapp-"):
        return token

    return None


def _get_web_token() -> str | None:
    """Your user token (xoxp-): Keychain sbk-slack/user-token, then the env variables."""
    from secrets_adapter import get_secret

    token = get_secret("sbk-slack", "user-token")
    if token and token.startswith("xoxp-"):
        return token

    for var in ("SBK_SLACK_USER_TOKEN", "SLACK_USER_TOKEN"):
        token = os.environ.get(var)
        if token and token.startswith("xoxp-"):
            return token

    return None





def _build_channel_index() -> dict[str, Path]:
    ""
    index = {}
    if not SLACK_CONVERSATIONS_DIR.exists():
        return index
    for jf in SLACK_CONVERSATIONS_DIR.glob("*.json"):
        if jf.name.startswith("_"):
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            ch_id = data.get("channel_id", "")
            if ch_id:
                index[ch_id] = jf
        except (json.JSONDecodeError, OSError):
            continue
    return index


def _persist_message(channel_id: str, user_id: str, text: str, ts: str) -> bool:
    ""



    channel_index = _build_channel_index()
    json_path = channel_index.get(channel_id)

    msg_data = {
        "user": user_id,
        "text": text,
        "ts": ts,
        "thread_ts": "",
        "reply_count": 0,
        "reactions": [],
    }

    if json_path:
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        existing_ts = {m.get("ts") for m in data.get("messages", [])}
        if ts in existing_ts:
            return False

        data["messages"].append(msg_data)
        data["total_messages"] = len(data["messages"])
        safe_write_json(json_path, data)
        return True
    else:

        filename = f"realtime-{channel_id}.json"
        new_data = {
            "channel": channel_id,
            "channel_id": channel_id,
            "total_messages": 1,
            "messages": [msg_data],
        }
        new_path = SLACK_CONVERSATIONS_DIR / filename
        safe_write_json(new_path, new_data)
        return True





class SlackRealtimeListener:
    ""

    def __init__(self, app_token: str, user_token: str):
        self.app_token = app_token
        self.user_token = user_token
        self.connected = False
        self.reconnects = 0
        self.messages_received = 0
        self.last_event_ts: str | None = None
        self.my_user_id = ""
        self._running = False

    def start(self) -> None:
        ""
        try:
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
            from slack_sdk.web import WebClient
        except ImportError:
            log.error("slack-sdk not installed. Run: uv pip install slack-sdk>=3.30")
            sys.exit(1)

        web_client = WebClient(token=self.user_token)
        try:
            self.my_user_id = web_client.auth_test().get("user_id", "") or ""
        except Exception as e:
            log.warning(f"auth.test failed, mentions will not be flagged in the log: {e}")
        client = SocketModeClient(
            app_token=self.app_token,
            web_client=web_client,
        )

        self._running = True

        def _handle_event(client_instance: SocketModeClient, req: SocketModeRequest):
            ""

            client_instance.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )

            if req.type != "events_api":
                return

            event = req.payload.get("event", {})
            event_type = event.get("type", "")


            if event_type != "message":
                return

            self._on_message(event)


        client.socket_mode_request_listeners.append(_handle_event)


        _update_slack_state(
            connected=False,
            status="connecting",
            started_at=datetime.now(UTC).isoformat(),
        )

        log.info("Slack real-time: connecting via Socket Mode...")

        try:
            client.connect()
            self.connected = True
            _update_slack_state(
                connected=True,
                status="connected",
                connected_at=datetime.now(UTC).isoformat(),
                reconnects=self.reconnects,
            )
            log.info("Slack real-time: connected")


            while self._running:
                if not client.is_connected():
                    self.connected = False
                    self.reconnects += 1
                    _update_slack_state(
                        connected=False,
                        status="reconnecting",
                        reconnects=self.reconnects,
                    )
                    log.warning(f"Slack real-time: disconnected, reconnect #{self.reconnects}")
                    try:
                        client.connect()
                        self.connected = True
                        _update_slack_state(
                            connected=True,
                            status="connected",
                            reconnects=self.reconnects,
                        )
                        log.info("Slack real-time: reconnected")
                    except Exception as e:
                        log.error(f"Slack real-time: reconnect failed: {e}")
                time.sleep(5)

        except KeyboardInterrupt:
            log.info("Slack real-time: stopped by user")
        finally:
            self._running = False
            self.connected = False
            _update_slack_state(
                connected=False,
                status="stopped",
                stopped_at=datetime.now(UTC).isoformat(),
                messages_total=self.messages_received,
            )
            try:
                client.disconnect()
            except Exception:
                pass

    def stop(self) -> None:
        ""
        self._running = False

    def _on_message(self, event: dict) -> None:
        ""

        subtype = event.get("subtype", "")
        if subtype in SKIP_SUBTYPES:
            return


        if event.get("bot_id") or event.get("bot_profile"):
            return

        user_id = event.get("user", "")
        text = event.get("text", "")
        ts = event.get("ts", "")
        channel_id = event.get("channel", "")

        if not text.strip() or not channel_id:
            return


        persisted = _persist_message(channel_id, user_id, text, ts)
        if persisted:
            self.messages_received += 1
            self.last_event_ts = datetime.now(UTC).isoformat()


            try:
                from event_bus import EventBus

                EventBus.emit("slack", "l0", channel=channel_id, count=1, via="realtime")
            except Exception as e:
                log.warning(f"EventBus emit failed: {e}")


            _update_slack_state(
                last_event=self.last_event_ts,
                messages_total=self.messages_received,
            )

            is_dm = event.get("channel_type") in ("im", "mpim")
            is_mention = bool(self.my_user_id) and f"<@{self.my_user_id}>" in text
            log.info(
                f"Slack RT: msg in {channel_id} from {user_id}"
                f"{' [DM]' if is_dm else ''}{' [mention]' if is_mention else ''}"
            )

    def get_status(self) -> dict:
        ""
        return {
            "connected": self.connected,
            "last_event": self.last_event_ts,
            "reconnects": self.reconnects,
            "messages_total": self.messages_received,
        }





def main():
    import argparse

    parser = argparse.ArgumentParser(description="SBK Slack Real-Time Listener")
    parser.add_argument("--status", action="store_true", help="Show connection status")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()


    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.status:
        state = _load_realtime_state()
        slack = state.get("slack", {})
        print(f"Connected: {slack.get('connected', False)}")
        print(f"Status:    {slack.get('status', 'unknown')}")
        print(f"Last event: {slack.get('last_event', 'never')}")
        print(f"Reconnects: {slack.get('reconnects', 0)}")
        print(f"Messages:   {slack.get('messages_total', 0)}")
        return


    app_token = _get_app_level_token()
    if not app_token:
        log.warning(
            "No Slack App-Level Token (xapp-...) found. "
            "Set SLACK_APP_LEVEL_TOKEN env var or: keyring set sbk-slack app-level-token <token>"
        )
        _update_slack_state(
            connected=False,
            status="no_app_token",
            checked_at=datetime.now(UTC).isoformat(),
        )
        sys.exit(1)

    user_token = _get_web_token()
    if not user_token:
        log.warning(
            "No Slack user token (xoxp-) found. Copy the User OAuth Token of your Slack app into "
            "the Keychain (service sbk-slack, account user-token) or into .env as SLACK_USER_TOKEN."
        )
        _update_slack_state(
            connected=False,
            status="no_user_token",
            checked_at=datetime.now(UTC).isoformat(),
        )
        sys.exit(1)


    listener = SlackRealtimeListener(app_token, user_token)

    def _sigterm_handler(signum, frame):
        log.info("Slack real-time: received SIGTERM, stopping...")
        listener.stop()

    signal.signal(signal.SIGTERM, _sigterm_handler)


    listener.start()


if __name__ == "__main__":
    main()
