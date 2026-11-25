#!/usr/bin/env python3
""











import argparse
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from secrets_adapter import get_secret, set_secret  # noqa: E402

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
CALLBACK_PORT = 8000
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/oauth/whoop/callback"
SCOPES = "offline read:recovery read:sleep read:workout read:cycles read:profile"
SERVICE = "sbk-whoop"


def _get_client_credentials() -> tuple[str, str]:
    ""
    client_id = os.environ.get("WHOOP_CLIENT_ID", "")
    client_secret = os.environ.get("WHOOP_CLIENT_SECRET", "")
    if not client_id:
        client_id = get_secret(SERVICE, "client-id") or ""
    if not client_secret:
        client_secret = get_secret(SERVICE, "client-secret") or ""
    return client_id, client_secret


def build_authorize_url(client_id: str, redirect_uri: str = REDIRECT_URI) -> str:
    ""
    if not client_id:
        raise ValueError("client_id is required to build authorize URL")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": "sbk-whoop-auth",
    }
    return f"{WHOOP_AUTH_URL}?{urlencode(params)}"


def save_tokens(access_token: str, refresh_token: str) -> None:
    ""
    set_secret(SERVICE, "access-token", access_token)
    set_secret(SERVICE, "refresh-token", refresh_token)


def load_access_token() -> str | None:
    ""
    return get_secret(SERVICE, "access-token")


def load_refresh_token() -> str | None:
    ""
    return get_secret(SERVICE, "refresh-token")


def exchange_code(code: str) -> dict:
    ""
    client_id, client_secret = _get_client_credentials()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(WHOOP_TOKEN_URL, data=data, timeout=30)
    resp.raise_for_status()
    token_data = resp.json()
    refresh_token = token_data.get("refresh_token", "")
    save_tokens(token_data["access_token"], refresh_token)
    return token_data


def refresh_access_token() -> str:
    ""
    client_id, client_secret = _get_client_credentials()
    refresh_token = load_refresh_token()
    if not refresh_token:
        raise ValueError("No refresh token found in Keychain")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(WHOOP_TOKEN_URL, data=data, timeout=30)
    resp.raise_for_status()
    token_data = resp.json()
    new_refresh = token_data.get("refresh_token", refresh_token)
    save_tokens(token_data["access_token"], new_refresh)
    return token_data["access_token"]




_auth_code = None
_server_error = None


class _OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code, _server_error
        parsed = urlparse(self.path)
        if parsed.path == "/oauth/whoop/callback":
            qs = parse_qs(parsed.query)
            if "code" in qs:
                _auth_code = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>WHOOP authorization successful!</h1><p>You can close this tab.</p>"
                )
            elif "error" in qs:
                _server_error = qs.get("error_description", qs["error"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Error: {_server_error}".encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing 'code' parameter")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def _run_oauth_flow():
    ""
    global _auth_code, _server_error
    _auth_code = None
    _server_error = None

    client_id, _ = _get_client_credentials()
    if not client_id:
        print("ERROR: WHOOP_CLIENT_ID not set in .env or Keychain")
        sys.exit(1)

    auth_url = build_authorize_url(client_id)

    server = HTTPServer(("localhost", CALLBACK_PORT), _OAuthHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Opening browser for WHOOP authorization...")
    print(f"URL: {auth_url}")
    webbrowser.open(auth_url)

    thread.join(timeout=120)
    server.server_close()

    if _server_error:
        print(f"OAuth error: {_server_error}")
        sys.exit(1)
    if not _auth_code:
        print("No authorization code received (timeout)")
        sys.exit(1)

    token_data = exchange_code(_auth_code)
    print("WHOOP authorization successful!")
    print(f"  Access token:  saved to Keychain ({SERVICE}/access-token)")
    print(f"  Refresh token: saved to Keychain ({SERVICE}/refresh-token)")
    print(f"  Expires in:    {token_data.get('expires_in', '?')}s")


def _check_tokens():
    ""
    access = load_access_token()
    refresh = load_refresh_token()
    if access:
        print(f"Access token:  found ({len(access)} chars)")
    else:
        print("Access token:  NOT FOUND")
    if refresh:
        print(f"Refresh token: found ({len(refresh)} chars)")
    else:
        print("Refresh token: NOT FOUND")


def main():
    parser = argparse.ArgumentParser(description="WHOOP OAuth helper — SBK")
    parser.add_argument("--check", action="store_true", help="Check if tokens exist")
    parser.add_argument("--refresh", action="store_true", help="Force token refresh")
    args = parser.parse_args()

    if args.check:
        _check_tokens()
    elif args.refresh:
        try:
            new_token = refresh_access_token()
            print(f"Token refreshed successfully ({len(new_token)} chars)")
        except Exception as e:
            print(f"Refresh failed: {e}")
            sys.exit(1)
    else:
        _run_oauth_flow()


if __name__ == "__main__":
    main()
