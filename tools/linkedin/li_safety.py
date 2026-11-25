#!/usr/bin/env python3
"""Shared LinkedIn safety limits: call budgets, lock file and fail-closed behavior."""













































from __future__ import annotations

import datetime
import json
import os
import random
import re
import sys
import time
from pathlib import Path




MIN_DELAY_SECONDS = 45.0
MAX_DELAY_SECONDS = 120.0
DANGER_ZONE_SECONDS = 30.0

DEFAULT_SESSION_CAP = 30
DEFAULT_DAILY_CAP = 40

BACKOFF_BASE_SECONDS = 30.0
BACKOFF_MULTIPLIER = 2.0
BACKOFF_CAP_SECONDS = 300.0
BACKOFF_MAX_ATTEMPTS = 3
BACKOFF_JITTER_FRACTION = 0.30


DATA_DIR = Path.home() / ".sbk-data" / "linkedin"
KILLSWITCH_LOCK = DATA_DIR / ".linkedin-killswitch"


OK = "OK"
GONE = "GONE"
TRANSIENT = "TRANSIENT"
STOP = "STOP"


_KILLSWITCH_BODY_MARKERS = [
    "temporarily restricted",
    "unusual activity",
    "software that automates activity",
    "captcha",
    "challenge",
    "visiting a very high number of pages",
    "request denied",
]


_KILLSWITCH_URL_PATTERNS = [
    re.compile(r"/authwall", re.IGNORECASE),
    re.compile(r"/checkpoint", re.IGNORECASE),
    re.compile(r"/challenge", re.IGNORECASE),
    re.compile(r"/uas/login", re.IGNORECASE),
    re.compile(r"/login", re.IGNORECASE),
]


class KillSwitchTripped(SystemExit):
    ""





    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(2)


class CapExceeded(RuntimeError):
    ""


class TransientAbort(RuntimeError):
    ""


def _today_str() -> str:
    ""
    return datetime.date.today().isoformat()


def _daily_cap_path(day: str = None) -> Path:
    if day is None:
        day = _today_str()
    return DATA_DIR / (f".li-daily-cap-{day}.json")


class LinkedInSafetyGuard:
    ""





















    def __init__(self, session_cap: int = DEFAULT_SESSION_CAP, daily_cap: int = DEFAULT_DAILY_CAP):
        ""





        if session_cap > DEFAULT_SESSION_CAP:
            raise ValueError(
                f"session_cap {session_cap} exceeds policy max {DEFAULT_SESSION_CAP}; "
                "raising requires an explicit override + the account owner's confirmation"
            )
        if daily_cap > DEFAULT_DAILY_CAP:
            raise ValueError(
                f"daily_cap {daily_cap} exceeds policy max {DEFAULT_DAILY_CAP}; "
                "raising requires an explicit override + the account owner's confirmation"
            )
        self.session_cap = int(session_cap)
        self.daily_cap = int(daily_cap)
        self.session_calls = 0
        self._transient_attempt = 0
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.check_killswitch()




    def check_killswitch(self) -> None:
        ""



        if KILLSWITCH_LOCK.exists():
            try:
                payload = json.loads(KILLSWITCH_LOCK.read_text())
                reason = payload.get("reason", "unknown")
                ts = payload.get("timestamp", "unknown")
            except Exception:
                reason, ts = "unknown (unreadable lock)", "unknown"
            sys.stderr.write(
                "[li_safety] KILL-SWITCH ACTIVE. Refusing to start.\n"
                f"  lock:   {KILLSWITCH_LOCK}\n  reason: {reason}\n  since:  {ts}\n"
                "  Remove the lock manually (account owner) to resume.\n"
            )
            raise KillSwitchTripped(reason)

    def trip_killswitch(self, reason: str) -> None:
        ""




        payload = {
            "reason": reason,
            "timestamp": datetime.datetime.now().isoformat(),
            "pid": os.getpid(),
            "script": sys.argv[0] if sys.argv else "?",
        }
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            KILLSWITCH_LOCK.write_text(json.dumps(payload, indent=2))
        except Exception as exc:  # pragma: no cover - best effort
            sys.stderr.write(f"[li_safety] WARNING: could not write kill-switch lock: {exc}\n")
        sys.stderr.write(
            f"[li_safety] KILL-SWITCH TRIPPED: {reason}\n"
            f"  Wrote lock: {KILLSWITCH_LOCK}\n  Aborting run (exit 2).\n"
        )
        raise KillSwitchTripped(reason)




    def load_daily_cap(self, day: str = None) -> int:
        ""
        path = _daily_cap_path(day)
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
            return int(data.get("count", 0))
        except Exception:



            sys.stderr.write(
                f"[li_safety] WARNING: daily counter corrupt/unreadable ({path}) -> "
                "fail-closed (treated as cap reached). Remove the file to "
                "resume.\n"
            )
            return 10**9

    def save_daily_cap(self, count: int, day: str = None) -> None:
        ""
        if day is None:
            day = _today_str()
        path = _daily_cap_path(day)
        payload = {
            "date": day,
            "count": int(count),
            "updated_at": datetime.datetime.now().isoformat(),
        }
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:  # pragma: no cover - best effort
            sys.stderr.write(f"[li_safety] WARNING: could not persist daily counter: {exc}\n")




    def assert_under_caps(self) -> None:
        ""



        if self.session_calls >= self.session_cap:
            raise CapExceeded(
                f"session cap reached ({self.session_calls}/{self.session_cap}). Stop this run."
            )
        daily = self.load_daily_cap()
        if daily >= self.daily_cap:
            raise CapExceeded(
                f"daily cap reached ({daily}/{self.daily_cap}) for {_today_str()}. Resume tomorrow."
            )

    def record_call(self) -> None:
        ""




        self.session_calls += 1
        daily = self.load_daily_cap()
        self.save_daily_cap(daily + 1)

    def before_request(self) -> float:
        ""











        self.assert_under_caps()
        self.record_call()
        return self.wait()




    def wait(self) -> float:
        ""




        delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        if delay < DANGER_ZONE_SECONDS:
            delay = DANGER_ZONE_SECONDS
        time.sleep(delay)
        return delay

    def reset_transient_backoff(self) -> None:
        ""
        self._transient_attempt = 0

    def transient_backoff(self) -> float:
        ""






        if self._transient_attempt >= BACKOFF_MAX_ATTEMPTS:
            raise TransientAbort(
                f"transient backoff exhausted after {BACKOFF_MAX_ATTEMPTS} attempts; aborting run"
            )
        n = self._transient_attempt
        self._transient_attempt += 1
        base = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER**n)
        base = min(base, BACKOFF_CAP_SECONDS)
        jitter = base * random.uniform(0.0, BACKOFF_JITTER_FRACTION)
        delay = min(base + jitter, BACKOFF_CAP_SECONDS)
        time.sleep(delay)
        return delay




    def classify_response(self, status, body=None, final_url=None):
        ""










        body_text = body if isinstance(body, str) else ("" if body is None else str(body))
        url_text = final_url or ""
        low_body = body_text.lower()
        low_url = url_text.lower()


        if status is None:
            return TRANSIENT

        try:
            status = int(status)
        except (TypeError, ValueError):
            return TRANSIENT


        if status == 429:
            self.trip_killswitch("HTTP 429 Too Many Requests")
        if status == 999:
            self.trip_killswitch("HTTP 999 Request Denied (LinkedIn IP/edge block)")
        if status == 403:
            self.trip_killswitch("HTTP 403 on data endpoint (suspect/restricted session)")


        if status in (301, 302, 303, 307, 308):
            for pat in _KILLSWITCH_URL_PATTERNS:
                if pat.search(url_text):
                    self.trip_killswitch(
                        f"Redirect {status} to authwall/login/checkpoint: {url_text}"
                    )

            self.trip_killswitch(
                f"Unexpected redirect {status} on Voyager/Sales-Nav endpoint: {url_text}"
            )


        for pat in _KILLSWITCH_URL_PATTERNS:
            if pat.search(url_text):
                self.trip_killswitch(f"Authwall/checkpoint/challenge URL: {url_text}")


        for marker in _KILLSWITCH_BODY_MARKERS:
            if marker in low_body:
                self.trip_killswitch(f"Body marker detected: '{marker}'")


        if status == 200:
            if self._looks_like_html(low_body, low_url):
                self.trip_killswitch("HTTP 200 with HTML/non-JSON body (masked challenge/authwall)")
            return OK


        if status in (400, 404):
            return GONE


        if 500 <= status <= 599:
            return TRANSIENT



        self.trip_killswitch(
            f"Unexpected non-200 response ({status}) on Voyager/Sales-Nav endpoint"
        )

    @staticmethod
    def _looks_like_html(low_body: str, low_url: str) -> bool:
        ""




        if not low_body:
            return False
        stripped = low_body.lstrip()

        if stripped.startswith("{") or stripped.startswith("["):
            return False
        html_markers = ("<!doctype html", "<html", "<head", "<body", "<script")
        return any(m in stripped[:4096] for m in html_markers)


__all__ = [
    "LinkedInSafetyGuard",
    "KillSwitchTripped",
    "CapExceeded",
    "TransientAbort",
    "OK",
    "GONE",
    "TRANSIENT",
    "STOP",
    "MIN_DELAY_SECONDS",
    "MAX_DELAY_SECONDS",
    "DEFAULT_SESSION_CAP",
    "DEFAULT_DAILY_CAP",
    "KILLSWITCH_LOCK",
    "DATA_DIR",
]


if __name__ == "__main__":

    g = LinkedInSafetyGuard.__new__(LinkedInSafetyGuard)
    g.session_cap = DEFAULT_SESSION_CAP
    g.daily_cap = DEFAULT_DAILY_CAP
    g.session_calls = 0
    g._transient_attempt = 0
    assert g.classify_response(200, '{"data": 1}', "https://www.linkedin.com/voyager/api/x") == OK
    assert g.classify_response(404, "", "x") == GONE
    assert g.classify_response(503, "", "x") == TRANSIENT
    assert g.classify_response(None, None, None) == TRANSIENT
    print("li_safety self-test OK (no LinkedIn calls made)")
