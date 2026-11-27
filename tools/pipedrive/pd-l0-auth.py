#!/usr/bin/env python3
"""Sign in to Pipedrive once with your own private OAuth app (optional).

Only for the OAuth route: with a personal API token you do not need this script.
Needs the client ID and client secret of a private app you registered yourself in
your own Developer Hub, with read-only scopes (Deals, Contacts, Activities: Read
only) and http://127.0.0.1:<port>/callback as its callback URL (default port 8765,
`pipedrive.oauth_redirect_port`). It opens the browser on oauth.pipedrive.com, you
allow the app for yourself, and the refresh token is stored in the Keychain as
sbk-pipedrive/refresh-token (or in the file PIPEDRIVE_TOKEN_FILE names).

Flow as documented by Pipedrive:
https://pipedrive.readme.io/docs/marketplace-oauth-authorization
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tools"))

LOGIN_TIMEOUT_SECS = 300


def wait_for_code(server: HTTPServer, state: str, path: str) -> str:
    import pd_oauth

    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path != path:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(u.query)
            result["state"] = (q.get("state") or [""])[0]
            result["code"] = (q.get("code") or [""])[0]
            result["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Pipedrive sign-in received. You can close this tab.")

        def log_message(self, *args):  # no access log: the URL carries the code
            pass

    server.RequestHandlerClass = Handler
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECS
    while not result and time.monotonic() < deadline:
        server.timeout = max(1.0, deadline - time.monotonic())
        server.handle_request()
    server.server_close()
    if not result:
        raise pd_oauth.OAuthError("no answer from the browser; run the sign-in again")
    if result.get("error"):
        raise pd_oauth.OAuthError(f"Pipedrive sign-in refused: {result['error']}")
    if result.get("state") != state:
        raise pd_oauth.OAuthError("the answer did not match this request (state); run it again")
    if not result.get("code"):
        raise pd_oauth.OAuthError("Pipedrive sent no authorization code; run the sign-in again")
    return result["code"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sign in to Pipedrive with your own private OAuth app (read-only scopes). "
        "Stores the refresh token in the Keychain sbk-pipedrive/refresh-token. "
        "Not needed if you use a personal API token."
    )
    ap.add_argument(
        "--port",
        type=int,
        default=None,
        help="loopback port of the callback URL registered in your app (default: "
        "pipedrive.oauth_redirect_port, else 8765)",
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="print the URL instead of opening the browser (open it yourself on this machine)",
    )
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass

    import pd_api
    import pd_oauth

    cid, _ = pd_api.client_id()
    secret, _ = pd_api.client_secret()
    if not cid or not secret:
        print(
            "pipedrive: no OAuth app found (client ID: Keychain sbk-pipedrive/client-id or "
            "PIPEDRIVE_CLIENT_ID; secret: Keychain sbk-pipedrive/client-secret or "
            f"PIPEDRIVE_CLIENT_SECRET); a personal API token needs no sign-in; {pd_api.SETUP_HINT}",
            file=sys.stderr,
        )
        return 1

    port = args.port or int(pd_api.setting("oauth_redirect_port", pd_oauth.DEFAULT_PORT))
    try:
        server = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    except OSError:
        print(f"pipedrive: port {port} is busy; free it or pass --port", file=sys.stderr)
        return 1
    redirect = pd_oauth.redirect_uri(port)
    state = secrets.token_urlsafe(24)
    url = pd_oauth.authorize_url(cid, redirect, state)

    print(f"Allow your app in the browser. Its callback URL must be exactly {redirect}")
    if args.no_browser or not webbrowser.open(url):
        print(f"Open this URL on this machine: {url}")

    try:
        code = wait_for_code(server, state, pd_oauth.REDIRECT_PATH)
        tokens = pd_oauth.exchange_code(None, cid, secret, code, redirect)
    except pd_oauth.OAuthError as e:
        print(f"pipedrive: {e}", file=sys.stderr)
        return 1

    refresh = tokens.get("refresh_token") or ""
    if not refresh:
        print("pipedrive: no refresh token in the answer; run the sign-in again", file=sys.stderr)
        return 1
    where = pd_api.save_refresh_token(refresh)
    if not where:
        print(
            f"pipedrive: sign-in works but cannot be stored in container mode; set {pd_api.ENV_TOKEN_FILE}",
            file=sys.stderr,
        )
        return 1
    print(f"Sign-in stored ({where}).")
    missing = pd_oauth.missing_scopes(tokens.get("scope", ""))
    if missing:
        print("Warning: these scopes were not granted, add them to your app: " + ", ".join(missing))
    extra = pd_oauth.extra_scopes(tokens.get("scope", ""))
    if extra:
        print(
            "Warning: your app also holds scopes that can change your data, the plugin never uses "
            "them; set it to read-only: " + ", ".join(extra)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
