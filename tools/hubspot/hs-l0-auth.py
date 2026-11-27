#!/usr/bin/env python3
"""Sign in to HubSpot once with your own user-level app (OAuth, local redirect).

Opens the browser on HubSpot's install page for your app, you pick your account and click
Connect app, and the refresh token is stored in the macOS Keychain as sbk-hubspot/<label>
(or in HUBSPOT_TOKEN_FILE). Needs the client ID and client secret of the app you uploaded
from tools/hubspot/hubspot-project/ (HUBSPOT_CLIENT_ID / HUBSPOT_CLIENT_SECRET, or the
Keychain), with http://localhost:8723/oauth-callback among its redirect URLs.

A token that HubSpot reports as account-level is not stored: it would read every record
the scopes allow, not only the ones you can see.

Flow as documented by HubSpot:
https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/working-with-oauth
https://developers.hubspot.com/docs/api-reference/legacy/authentication/manage-oauth-tokens
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hs_api  # noqa: E402

LOGIN_TIMEOUT_SECS = 300


def install_url_from(given: str, redirect: str, state: str) -> str:
    """The install URL copied from your app's Auth tab, with this run's state added.

    Useful when HubSpot rejects the URL this script builds (for example because the
    scopes of your app differ). Its redirect_uri must be the one this script listens on.
    """
    u = urlparse(given.strip())
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == "hubspot.com" or host.endswith(".hubspot.com")):
        raise hs_api.HubSpotError(
            "HubSpot: --install-url must be an https://...hubspot.com address"
        )
    q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    if q.get("redirect_uri") != redirect:
        raise hs_api.HubSpotError(
            f"HubSpot: the install URL redirects to {q.get('redirect_uri') or 'nothing'}, "
            f"this script listens on {redirect}; add that redirect URL to the app or use --port"
        )
    q["state"] = state
    return urlunparse(u._replace(query=urlencode(q)))


def wait_for_code(server: HTTPServer, state: str, timeout: float = LOGIN_TIMEOUT_SECS) -> str:
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != hs_api.REDIRECT_PATH:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(parsed.query)
            result["state"] = (q.get("state") or [""])[0]
            result["code"] = (q.get("code") or [""])[0]
            result["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"HubSpot login received. You can close this tab.")

        def log_message(self, *args):  # no access log: the URL carries the code
            pass

    server.RequestHandlerClass = Handler
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline:
        server.timeout = max(1.0, deadline - time.monotonic())
        server.handle_request()
    server.server_close()
    if not result:
        raise hs_api.HubSpotError("HubSpot: no answer from the browser; run the login again")
    if result.get("error"):
        raise hs_api.HubSpotError(f"HubSpot: login refused ({result['error']})")
    if result.get("state") != state:
        raise hs_api.HubSpotError(
            "HubSpot: the answer did not match this login (state); run it again"
        )
    if not result.get("code"):
        raise hs_api.HubSpotError(
            "HubSpot: no authorization code in the answer; run the login again"
        )
    return result["code"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sign in to HubSpot with your own user-level app and store the refresh "
        "token in the Keychain sbk-hubspot/<label>."
    )
    ap.add_argument("--label", default=hs_api.DEFAULT_LABEL, help="login name (default: default)")
    ap.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"local port of the redirect URL (default {hs_api.DEFAULT_REDIRECT_PORT}, "
        "or hubspot.redirect_port in sbk.config.json)",
    )
    ap.add_argument(
        "--install-url",
        default="",
        help="use the install URL from your app's Auth tab instead of the one built here",
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="print the URL instead of opening the browser (open it yourself on this machine)",
    )
    args = ap.parse_args(argv)

    cid, secret = hs_api.client_id(), hs_api.client_secret()
    if not cid or not secret:
        print(hs_api.no_app_message(), file=sys.stderr)
        return 1

    port = args.port or hs_api.redirect_port()
    redirect = hs_api.redirect_uri(port)
    try:
        server = HTTPServer(("localhost", port), BaseHTTPRequestHandler)
    except OSError as e:
        print(
            f"HubSpot: cannot listen on localhost:{port} ({e.strerror}); use --port",
            file=sys.stderr,
        )
        return 1
    state = secrets.token_urlsafe(24)
    try:
        url = (
            install_url_from(args.install_url, redirect, state)
            if args.install_url
            else hs_api.authorize_url(cid, redirect, state)
        )
    except hs_api.HubSpotError as e:
        server.server_close()
        print(str(e), file=sys.stderr)
        return 1

    print("Sign in to HubSpot, choose your account and click Connect app.")
    if args.no_browser or not webbrowser.open(url):
        print(f"Open this URL on this machine: {url}")

    try:
        code = wait_for_code(server, state)
        tokens = hs_api.exchange_code(cid, secret, code, redirect)
        refresh = tokens.get("refresh_token") or ""
        access = tokens.get("access_token") or ""
        if not refresh or not access:
            raise hs_api.HubSpotError("HubSpot: no tokens in the answer; run the login again")
        me = hs_api.describe_token(hs_api.introspect(cid, secret, access))
        hs_api.check_user_level(me)
    except hs_api.HubSpotError as e:
        msg = str(e)
        print(msg if msg.startswith("HubSpot") else f"HubSpot: {msg}", file=sys.stderr)
        return 1

    where = hs_api.save_refresh_token(refresh, args.label)
    if not where:
        print(
            f"HubSpot: login works but cannot be stored in container mode; set {hs_api.ENV_TOKEN_FILE}",
            file=sys.stderr,
        )
        return 1
    level = {True: "user-level app", None: "app level not reported by HubSpot"}[me["is_user_level"]]
    print(f"Login stored ({where}); HubSpot account {me['hub_id'] or '?'}, {level}.")
    missing = hs_api.missing_scopes(me["scopes"])
    if missing:
        print(
            "Warning: these scopes were not granted, add them to the app and sign in again: "
            + ", ".join(missing)
        )
    if hs_api.OPTIONAL_SCOPES[0] not in me["scopes"]:
        print(
            "Note: owners were not granted, so 'only mine' will fall back to everything you can see."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
