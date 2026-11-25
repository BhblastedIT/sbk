#!/usr/bin/env python3
"""Gmail login: sign one mailbox in with your own OAuth client (Desktop app) and keep its refresh token in the Keychain."""










import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

import google_oauth  # noqa: E402
from secrets_adapter import set_secret  # noqa: E402

from sbk_config import EMAILS_DIR  # noqa: E402

DATA_DIR = EMAILS_DIR
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
# Your own OAuth client (Desktop app), see tools/google_oauth.py.
CLIENT_SECRET = google_oauth.client_file()
# gmail.readonly for the download; https://mail.google.com/ for the tools that
# write in your mailbox (drafts, reminders, inbox-zero labels and cleanup).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://mail.google.com/",
]
# Separate login, only for the inbox-zero rules (Gmail filters): --settings.
SETTINGS_SCOPES = ["https://www.googleapis.com/auth/gmail.settings.basic"]
SETTINGS_SERVICE = "sbk-gmail-settings"


def load_accounts() -> dict:
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text())
    return {}


def save_accounts(accounts: dict):
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))


def verify_account(acc: dict) -> str:
    ""
    creds = Credentials(
        token=None,
        refresh_token=acc["refresh_token"],
        client_id=acc["client_id"],
        client_secret=acc["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def _get_oauth_client_creds() -> tuple[str, str]:
    ""
    return google_oauth.client_id_secret()


def auth_browser(account_name: str):
    ""
    if not CLIENT_SECRET.exists():
        print(
            f"OAuth client file not found: {CLIENT_SECRET}. Download your Desktop-app client JSON "
            "there or set GOOGLE_OAUTH_CLIENT_SECRET_PATH (docs/CONNECTING.md#google)."
        )
        sys.exit(1)

    print(f"Signing in '{account_name}': pick the Google account in the browser.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    client_id, client_secret_val = _get_oauth_client_creds()

    acc = {
        "client_id": client_id or creds.client_id,
        "client_secret": client_secret_val or creds.client_secret,
        "refresh_token": creds.refresh_token,
    }

    email = verify_account(acc)


    set_secret("sbk-gmail", account_name, creds.refresh_token)


    accounts = load_accounts()
    accounts[account_name] = {"email": email}
    save_accounts(accounts)

    print(f"Account '{account_name}' saved ({email})")
    print("  Refresh token: macOS Keychain (sbk-gmail)")
    print(f"  Account ref:   {ACCOUNTS_FILE}")


def import_token(account_name: str, token_path: str):
    ""
    token_file = Path(token_path)
    if not token_file.exists():
        print(f"Token file not found: {token_file}")
        sys.exit(1)

    data = json.loads(token_file.read_text())


    client_id = data.get("client_id", "")
    client_secret_val = data.get("client_secret", "")
    refresh_token = data.get("refresh_token", "")


    if not (client_id and client_secret_val):
        client_id, client_secret_val = google_oauth.client_id_secret()

    if not refresh_token:
        print("Token file missing 'refresh_token'")
        sys.exit(1)

    acc = {
        "client_id": client_id,
        "client_secret": client_secret_val,
        "refresh_token": refresh_token,
    }

    email = verify_account(acc)


    set_secret("sbk-gmail", account_name, refresh_token)


    accounts = load_accounts()
    accounts[account_name] = {"email": email}
    save_accounts(accounts)

    print(f"Account '{account_name}' imported ({email})")
    print("  Refresh token: macOS Keychain (sbk-gmail)")
    print(f"  Account ref:   {ACCOUNTS_FILE}")


def list_accounts():
    ""
    accounts = load_accounts()
    if not accounts:
        print("No accounts registered.")
        print("Run: uv run python tools/email/em-l0-auth.py <label>")
        return

    print(f"Accounts ({len(accounts)}):")
    for name, acc in accounts.items():
        email = acc.get("email", "?")
        print(f"  {name}: {email}")


def auth_settings(account_name: str):
    ""
    accounts = load_accounts()
    if account_name not in accounts:
        print(f"Sign '{account_name}' in first: uv run python tools/email/em-l0-auth.py {account_name}")
        sys.exit(1)
    google_oauth.browser_login(SETTINGS_SERVICE, account_name, SETTINGS_SCOPES)
    print("  Used only by tools/email/em-util-inbox-zero.py to read and write Gmail filters.")


def main():
    parser = argparse.ArgumentParser(
        description="Gmail login — SBK: one browser login per mailbox, refresh token in the Keychain"
    )
    parser.add_argument("account", nargs="?", help="Label of the mailbox, e.g. work or personal")
    parser.add_argument("--import-token", metavar="FILE", help="Import an existing token JSON (refresh_token)")
    parser.add_argument("--list", action="store_true", help="List the mailboxes signed in")
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Extra login with the gmail.settings.basic scope, only for the inbox-zero filters",
    )
    args = parser.parse_args()

    if args.list:
        list_accounts()
        return

    if not args.account:
        parser.print_help()
        sys.exit(1)

    if args.settings:
        auth_settings(args.account)
        return

    accounts = load_accounts()
    if args.account in accounts:
        email = accounts[args.account].get("email", "?")
        print(f"Account '{args.account}' already exists ({email}). Overwrite? [y/N] ", end="")
        if input().strip().lower() != "y":
            sys.exit(0)

    if args.import_token:
        import_token(args.account, args.import_token)
    else:
        auth_browser(args.account)


if __name__ == "__main__":
    main()
