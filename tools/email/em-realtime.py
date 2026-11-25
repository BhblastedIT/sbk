#!/usr/bin/env python3
"""Gmail IMAP IDLE listener: watches mailboxes in real time and triggers an L0 download when new mail arrives."""




















from __future__ import annotations

import imaplib
import json
import logging
import select
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import DATA_ROOT

REALTIME_STATE_FILE = DATA_ROOT / ".realtime-state.json"
EMAILS_DIR = DATA_ROOT / "emails"
ACCOUNTS_FILE = EMAILS_DIR / "accounts.json"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IDLE_TIMEOUT = 25 * 60

log = logging.getLogger("sbk.email-realtime")





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
    REALTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REALTIME_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.rename(REALTIME_STATE_FILE)


def _update_email_state(**kwargs) -> None:
    ""
    state = _load_realtime_state()
    if "email" not in state:
        state["email"] = {}
    state["email"].update(kwargs)
    _save_realtime_state(state)


def _update_account_state(account: str, **kwargs) -> None:
    ""
    state = _load_realtime_state()
    if "email" not in state:
        state["email"] = {}
    if "accounts" not in state["email"]:
        state["email"]["accounts"] = {}
    state["email"]["accounts"][account] = {
        **state["email"]["accounts"].get(account, {}),
        **kwargs,
    }

    accts = state["email"].get("accounts", {})
    state["email"]["connected"] = any(a.get("connected", False) for a in accts.values())
    _save_realtime_state(state)





def _build_xoauth2_string(email: str, access_token: str) -> str:
    ""



    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return auth_string


def _get_access_token(account_name: str) -> tuple[str | None, str | None]:
    ""



    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from secrets_adapter import get_secret
    except ImportError:
        log.error("Missing dependencies: google-auth, secrets_adapter")
        return None, None

    if not ACCOUNTS_FILE.exists():
        return None, None

    accounts = json.loads(ACCOUNTS_FILE.read_text())
    if account_name not in accounts:
        return None, None

    acc = accounts[account_name]
    email = acc.get("email", f"{account_name}@gmail.com")

    refresh_token = get_secret("sbk-gmail", account_name)
    if not refresh_token:
        refresh_token = acc.get("refresh_token")
    if not refresh_token:
        return None, None

    import google_oauth  # your OAuth client: .env or its JSON file

    client_id, client_secret = google_oauth.client_id_secret()
    client_id = client_id or acc.get("client_id", "")
    client_secret = client_secret or acc.get("client_secret", "")


    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://mail.google.com/"],
    )

    try:
        creds.refresh(Request())
        return creds.token, email
    except Exception as e:
        log.warning(f"Token refresh failed for {account_name}: {e}")
        return None, None





class GmailIdleListener:
    ""

    def __init__(self, account_name: str):
        self.account_name = account_name
        self.connected = False
        self.new_mail_count = 0
        self.last_event_ts: str | None = None
        self._running = False
        self._imap: imaplib.IMAP4_SSL | None = None

    def connect(self) -> bool:
        ""
        access_token, email = _get_access_token(self.account_name)
        if not access_token or not email:
            log.warning(f"[{self.account_name}] No access token available")
            return False

        try:
            self._imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)


            auth_string = _build_xoauth2_string(email, access_token)

            def _auth_handler(response):
                return auth_string.encode("utf-8")

            self._imap.authenticate("XOAUTH2", _auth_handler)
            self._imap.select("INBOX")

            self._imap.socket().settimeout(IDLE_TIMEOUT + 30)
            self.connected = True
            log.info(f"[{self.account_name}] IMAP connected ({email})")
            return True

        except imaplib.IMAP4.error as e:
            error_str = str(e)
            if "AUTHENTICATIONFAILED" in error_str or "Invalid credentials" in error_str:
                log.warning(
                    f"[{self.account_name}] IMAP auth failed. "
                    "Likely needs re-auth with https://mail.google.com/ scope. "
                    f"Run: uv run python tools/email/em-l0-auth.py {self.account_name}"
                )
            else:
                log.warning(f"[{self.account_name}] IMAP error: {e}")
            self.connected = False
            return False
        except Exception as e:
            log.warning(f"[{self.account_name}] IMAP connect failed: {e}")
            self.connected = False
            return False

    def idle_loop(self) -> None:
        ""
        self._running = True

        while self._running:
            if not self._imap or not self.connected:
                if not self.connect():
                    log.warning(f"[{self.account_name}] Cannot reconnect, waiting 60s")
                    time.sleep(60)
                    continue

            try:

                tag = self._imap._new_tag()
                self._imap.send(tag + b" IDLE\r\n")
                response = self._imap.readline()

                if b"+" not in response:
                    log.warning(
                        f"[{self.account_name}] IDLE not accepted: {response.decode(errors='replace')}"
                    )
                    self.connected = False
                    continue


                sock = self._imap.socket()
                readable, _, _ = select.select([sock], [], [], IDLE_TIMEOUT)

                if readable:


                    try:
                        data = sock.recv(4096).decode("utf-8", errors="replace")
                        self._imap.send(b"DONE\r\n")
                        self._imap.readline()
                    except TimeoutError:
                        log.warning(
                            f"[{self.account_name}] Socket timeout during IDLE read, reconnecting"
                        )
                        self.connected = False
                        self._imap = None
                        continue

                    if "EXISTS" in data:
                        self._on_new_mail()
                else:

                    self._imap.send(b"DONE\r\n")
                    self._imap.readline()

                    self.last_event_ts = datetime.now(UTC).isoformat()
                    _update_account_state(
                        self.account_name,
                        connected=True,
                        last_event=self.last_event_ts,
                    )
                    log.debug(f"[{self.account_name}] IDLE heartbeat (25min)")

            except (OSError, imaplib.IMAP4.abort) as e:
                log.warning(f"[{self.account_name}] IDLE connection lost: {e}")
                self.connected = False
                self._imap = None
                time.sleep(5)
            except Exception as e:
                log.error(f"[{self.account_name}] IDLE error: {e}")
                self.connected = False
                self._imap = None
                time.sleep(10)

    def _on_new_mail(self) -> None:
        ""
        self.new_mail_count += 1
        self.last_event_ts = datetime.now(UTC).isoformat()

        log.info(f"[{self.account_name}] New mail detected via IMAP IDLE")

        _update_account_state(
            self.account_name,
            connected=True,
            last_event=self.last_event_ts,
            new_mail_count=self.new_mail_count,
        )


        try:
            script = _TOOLS_DIR / "email" / "em-l0-download.py"
            if script.exists():
                subprocess.Popen(
                    [sys.executable, str(script), "--account", self.account_name, "--since", "1d"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(_PROJECT_ROOT),
                )
                log.info(f"[{self.account_name}] Triggered L0 download")
        except Exception as e:
            log.warning(f"[{self.account_name}] L0 trigger failed: {e}")


        try:
            from event_bus import EventBus

            EventBus.emit("email", "l0", account=self.account_name, count=1, via="realtime")
        except Exception as e:
            log.warning(f"EventBus emit failed: {e}")

    def stop(self) -> None:
        ""
        self._running = False
        if self._imap and self.connected:
            try:
                self._imap.close()
                self._imap.logout()
            except Exception:
                pass

    def get_status(self) -> dict:
        ""
        return {
            "connected": self.connected,
            "last_event": self.last_event_ts,
            "new_mail_count": self.new_mail_count,
        }





class MultiAccountIdleManager:
    ""

    def __init__(self):
        self.listeners: dict[str, GmailIdleListener] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._running = False

    def start(self) -> None:
        ""
        if not ACCOUNTS_FILE.exists():
            log.warning("No accounts.json found")
            return

        accounts = json.loads(ACCOUNTS_FILE.read_text())
        self._running = True

        for acct_name in accounts:
            listener = GmailIdleListener(acct_name)
            self.listeners[acct_name] = listener

            thread = threading.Thread(
                target=self._run_account_idle,
                args=(acct_name, listener),
                daemon=True,
                name=f"imap-idle-{acct_name}",
            )
            self._threads[acct_name] = thread
            thread.start()
            log.info(f"[{acct_name}] IDLE thread started")

        _update_email_state(
            status="running",
            started_at=datetime.now(UTC).isoformat(),
            account_count=len(accounts),
        )


        try:
            while self._running:
                time.sleep(10)

                for name, thread in list(self._threads.items()):
                    if not thread.is_alive() and self._running:
                        log.warning(f"[{name}] IDLE thread died, restarting")
                        listener = GmailIdleListener(name)
                        self.listeners[name] = listener
                        new_thread = threading.Thread(
                            target=self._run_account_idle,
                            args=(name, listener),
                            daemon=True,
                            name=f"imap-idle-{name}",
                        )
                        self._threads[name] = new_thread
                        new_thread.start()
        except KeyboardInterrupt:
            log.info("Email real-time: stopped by user")
        finally:
            self.stop()

    def _run_account_idle(self, account_name: str, listener: GmailIdleListener) -> None:
        ""
        if not listener.connect():
            _update_account_state(
                account_name,
                connected=False,
                status="auth_failed",
                checked_at=datetime.now(UTC).isoformat(),
            )
            return

        _update_account_state(
            account_name,
            connected=True,
            status="idle",
            connected_at=datetime.now(UTC).isoformat(),
        )

        listener.idle_loop()

    def stop(self) -> None:
        ""
        self._running = False
        for name, listener in self.listeners.items():
            log.info(f"[{name}] Stopping IDLE listener")
            listener.stop()

        _update_email_state(
            connected=False,
            status="stopped",
            stopped_at=datetime.now(UTC).isoformat(),
        )

    def get_status(self) -> dict:
        ""
        return {
            "accounts": {name: listener.get_status() for name, listener in self.listeners.items()}
        }





def main():
    import argparse

    parser = argparse.ArgumentParser(description="SBK Gmail IMAP IDLE Listener")
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
        email = state.get("email", {})
        print(f"Connected: {email.get('connected', False)}")
        print(f"Status:    {email.get('status', 'unknown')}")
        for acct, info in email.get("accounts", {}).items():
            print(
                f"  [{acct}] connected={info.get('connected', False)} "
                f"last_event={info.get('last_event', 'never')} "
                f"new_mail={info.get('new_mail_count', 0)}"
            )
        return


    manager = MultiAccountIdleManager()

    def _sigterm_handler(signum, frame):
        log.info("Email real-time: received SIGTERM, stopping...")
        manager.stop()

    signal.signal(signal.SIGTERM, _sigterm_handler)


    manager.start()


if __name__ == "__main__":
    main()
