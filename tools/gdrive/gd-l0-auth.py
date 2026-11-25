#!/usr/bin/env python3
""











import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

import google_oauth  # noqa: E402
from secrets_adapter import set_secret  # noqa: E402

# Your own OAuth client (Desktop app), see tools/google_oauth.py.
CLIENT_SECRET = google_oauth.client_file()
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main():
    parser = argparse.ArgumentParser(description="Google Drive OAuth — SBK")
    parser.add_argument(
        "--account",
        default="default",
        help="Label of the account, e.g. work or personal (the same label as in emails/accounts.json). Default: 'default'",
    )
    args = parser.parse_args()
    account_name = args.account


    secret_path = CLIENT_SECRET
    if not secret_path.exists():
        print(
            f"OAuth client file not found: {CLIENT_SECRET}. Download your Desktop-app client JSON "
            "there or set GOOGLE_OAUTH_CLIENT_SECRET_PATH (docs/CONNECTING.md#google)."
        )
        sys.exit(1)

    print(f"Using client secret: {secret_path}")
    print(f"Authorizing Drive access for account '{account_name}'...")
    print("Select the correct Google account in the browser.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")


    service = build("drive", "v3", credentials=creds)
    about = service.about().get(fields="user").execute()
    email = about["user"]["emailAddress"]
    name = about["user"].get("displayName", "")


    token_data = {
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "email": email,
    }
    set_secret("sbk-gdrive", account_name, json.dumps(token_data))

    print(f"\nAuthenticated: {name} ({email})")
    print(f"Token stored in Keychain (service: sbk-gdrive, account: {account_name})")
    print(f"Next: uv run python tools/gdrive/gd-l0-download.py --account {account_name} --mode recent")


if __name__ == "__main__":
    main()
