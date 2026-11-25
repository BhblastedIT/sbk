"""Google sign-in for SBK: your own OAuth client (Desktop app), one browser login per account.

Every Google plugin (email, calendar, gdrive, gsc, analytics) signs in the same way:

1. You create an OAuth client of type "Desktop app" in your own Google Cloud project and
   download its JSON file (default path ~/.secrets/google-oauth/client_secret.json, or set
   GOOGLE_OAUTH_CLIENT_SECRET_PATH; GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET in
   .env also work).
2. The first login of an account opens the browser; you pick the Google account and allow
   the scopes the plugin asks for.
3. The refresh token is stored in the macOS Keychain under "<keychain service>/<label>".
   Nothing else is written to disk.

The token is refreshed without asking scopes again, so it always carries exactly what you
allowed at login.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_CLIENT_DIR = Path.home() / ".secrets" / "google-oauth"
DEFAULT_CLIENT_FILE = DEFAULT_CLIENT_DIR / "client_secret.json"
SETUP_HINT = "see docs/CONNECTING.md#google"


class NoLogin(Exception):
    """No stored login for this account (run the plugin's login command first)."""


def client_file() -> Path:
    """Path of your OAuth client JSON (Desktop app).

    GOOGLE_OAUTH_CLIENT_SECRET_PATH wins; otherwise ~/.secrets/google-oauth/client_secret.json,
    or the first client_secret*.json in that folder (the name Google gives the download).
    """
    env = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    if DEFAULT_CLIENT_FILE.is_file():
        return DEFAULT_CLIENT_FILE
    found = sorted(DEFAULT_CLIENT_DIR.glob("client_secret*.json")) if DEFAULT_CLIENT_DIR.is_dir() else []
    return found[0] if found else DEFAULT_CLIENT_FILE


def client_id_secret() -> tuple[str, str]:
    """(client_id, client_secret) of your OAuth client: .env first, then the JSON file."""
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec
    p = client_file()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return "", ""
        block = data.get("installed") or data.get("web") or {}
        return block.get("client_id", ""), block.get("client_secret", "")
    return "", ""


def _parse_stored(raw: str) -> tuple[str, str, str]:
    """A stored value is a bare refresh token or a JSON with refresh_token (+ client)."""
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
        except ValueError:
            return "", "", ""
        return d.get("refresh_token", ""), d.get("client_id", ""), d.get("client_secret", "")
    return raw, "", ""


def stored_credentials(keychain_service: str, label: str):
    """Credentials from the Keychain, or None when this account never logged in."""
    from google.oauth2.credentials import Credentials
    from secrets_adapter import get_secret

    refresh, cid, csec = _parse_stored(get_secret(keychain_service, label) or "")
    if not refresh:
        return None
    if not (cid and csec):
        cid, csec = client_id_secret()
    return Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=csec,
        token_uri=TOKEN_URI,
    )


def browser_login(keychain_service: str, label: str, scopes: list[str]):
    """Open the browser, let you pick the Google account, store the refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from secrets_adapter import set_secret

    p = client_file()
    if not p.is_file():
        raise SystemExit(
            f"OAuth client file not found: {p}. Create a Desktop-app OAuth client in your Google "
            f"Cloud project, download its JSON there (or set GOOGLE_OAUTH_CLIENT_SECRET_PATH); "
            f"{SETUP_HINT}."
        )
    print(f"Signing in '{label}': pick the Google account in the browser.")
    flow = InstalledAppFlow.from_client_secrets_file(str(p), scopes)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        raise SystemExit(
            "Google returned no refresh token. Remove SBK from https://myaccount.google.com/permissions "
            "and run the login again."
        )
    set_secret(keychain_service, label, creds.refresh_token)
    print(f"Login stored in the Keychain ({keychain_service}/{label}).")
    return creds


def credentials(keychain_service: str, label: str, scopes: list[str], *, login: bool = False):
    """Stored credentials; with login=True a missing login opens the browser."""
    creds = stored_credentials(keychain_service, label)
    if creds is not None:
        return creds
    if login:
        return browser_login(keychain_service, label, scopes)
    raise NoLogin(f"no Google login stored as {keychain_service}/{label}")


# --- Gmail mailboxes: <data root>/emails/accounts.json {label: {"email": ...}} ----------
def gmail_accounts() -> dict[str, dict]:
    from sbk_config import EMAILS_DIR

    p = EMAILS_DIR / "accounts.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def gmail_label(label_or_email: str) -> tuple[str, str]:
    """(label, address) for a mailbox given by its label or by its address."""
    accounts = gmail_accounts()
    key = (label_or_email or "").strip()
    if key in accounts:
        return key, str(accounts[key].get("email", ""))
    for label, acc in accounts.items():
        if str(acc.get("email", "")).lower() == key.lower():
            return label, str(acc.get("email", ""))
    known = ", ".join(f"{k} ({v.get('email', '?')})" for k, v in accounts.items()) or "(none)"
    raise SystemExit(
        f"Mailbox '{key}' has no Gmail login. Known: {known}. "
        "Sign in with: uv run python tools/email/em-l0-auth.py <label>"
    )


def gmail_service(label_or_email: str, keychain_service: str = "sbk-gmail"):
    """Gmail API client for one of your mailboxes (label or address)."""
    from googleapiclient.discovery import build

    label, _ = gmail_label(label_or_email)
    try:
        creds = credentials(keychain_service, label, [])
    except NoLogin as e:
        extra = " --settings" if keychain_service == "sbk-gmail-settings" else ""
        raise SystemExit(f"{e}. Run: uv run python tools/email/em-l0-auth.py {label}{extra}") from e
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
