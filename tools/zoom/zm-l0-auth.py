#!/usr/bin/env python3
"""Sign in to your own Zoom account once (OAuth with PKCE, loopback redirect).

Opens the browser on zoom.us, you allow your own user-managed app, and the refresh
token is stored in the macOS Keychain as sbk-zoom/<label> (or in ZOOM_TOKEN_FILE).
Needs ZOOM_CLIENT_ID = the *public* client ID of your app ("Use Public Client OAuth"
on), with http://127.0.0.1/callback registered as its redirect URL. No client secret.

Flow as documented by Zoom: https://developers.zoom.us/docs/integrations/PKCE/
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zm_api  # noqa: E402

LOGIN_TIMEOUT_SECS = 300


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def authorize_url(cid: str, redirect_uri: str, challenge: str, state: str) -> str:
    return (
        zm_api.AUTHORIZE_URL
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": cid,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            }
        )
    )


def wait_for_code(server: HTTPServer, state: str) -> str:
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path != zm_api.REDIRECT_PATH:
                self.send_response(404)
                self.end_headers()
                return
            result["state"] = (q.get("state") or [""])[0]
            result["code"] = (q.get("code") or [""])[0]
            result["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Zoom login received. You can close this tab.")

        def log_message(self, *args):  # silence the default access log
            pass

    server.RequestHandlerClass = Handler
    # A browser may send another request first (favicon, preconnect): keep serving until
    # the callback arrives or the login time is over.
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECS
    while not result and time.monotonic() < deadline:
        server.timeout = max(1.0, deadline - time.monotonic())
        server.handle_request()
    server.server_close()
    if not result:
        raise zm_api.ZoomError("no answer from the browser; run the login again")
    if result.get("error"):
        raise zm_api.ZoomError(f"Zoom login refused: {result['error']}")
    if result.get("state") != state:
        raise zm_api.ZoomError("login answer did not match this request (state); run it again")
    if not result.get("code"):
        raise zm_api.ZoomError("Zoom sent no authorization code; run the login again")
    return result["code"]


def exchange_code(cid: str, code: str, redirect_uri: str, verifier: str, opener=None) -> dict:
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": cid,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()
    req = Request(
        zm_api.TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with (opener or zm_api._default_opener)(req, zm_api.REQUEST_TIMEOUT_SECS) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        raise zm_api.ZoomError(
            f"Zoom refused the code exchange (HTTP {e.code}). Check that ZOOM_CLIENT_ID is the "
            "public client ID and that http://127.0.0.1/callback is the public client's redirect URL"
        ) from None
    except URLError as e:
        raise zm_api.ZoomError(f"network error talking to Zoom: {e.reason}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sign in to your own Zoom account (PKCE, user-level scopes). "
        "Stores the refresh token in the Keychain sbk-zoom/<label>."
    )
    ap.add_argument("--label", default=zm_api.DEFAULT_LABEL, help="login name (default: default)")
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="print the URL instead of opening the browser (open it yourself on this machine)",
    )
    args = ap.parse_args(argv)

    cid = zm_api.client_id()
    if not cid:
        print(
            f"Zoom: {zm_api.ENV_CLIENT_ID} is not set (public client ID of your own user-managed "
            f"Zoom app); {zm_api.SETUP_HINT}",
            file=sys.stderr,
        )
        return 1

    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}{zm_api.REDIRECT_PATH}"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = authorize_url(cid, redirect_uri, challenge, state)

    print("Sign in to Zoom and allow your app in the browser.")
    if args.no_browser or not webbrowser.open(url):
        print(f"Open this URL on this machine: {url}")

    try:
        code = wait_for_code(server, state)
        tokens = exchange_code(cid, code, redirect_uri, verifier)
    except zm_api.ZoomError as e:
        print(f"Zoom: {e}", file=sys.stderr)
        return 1

    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        print("Zoom: no refresh token in the answer; run the login again", file=sys.stderr)
        return 1
    where = zm_api.save_refresh_token(refresh, args.label)
    if not where:
        print(
            f"Zoom: login works but cannot be stored in container mode; set {zm_api.ENV_TOKEN_FILE}",
            file=sys.stderr,
        )
        return 1
    print(f"Login stored ({where}).")
    missing = zm_api.missing_scopes(tokens.get("scope", ""))
    if missing:
        print(
            "Warning: these scopes were not granted, add them to your app and sign in again: "
            + ", ".join(missing)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
