"""Where SBK reads and stores secrets: the macOS Keychain, or environment variables in a container.

Every connector asks for a secret by Keychain service and account, for example
``get_secret("sbk-slack", "user-token")``. On your machine the value comes from the system keyring
(the macOS Keychain) through the ``keyring`` package, and ``set_secret`` writes it there.

In container mode (``SBK_CONTAINERIZED=1``) there is no Keychain. ``get_secret`` then reads the
environment variable named in ``_ENV_MAP`` for that service and account, and ``set_secret`` does
nothing. A ``"*"`` entry covers every account of a service: ``{account}`` in its variable name is
replaced by the account label in upper case, with every character that is not a letter or a digit
turned into ``_`` (label ``my-crm`` -> ``SBK_DB_URL_MY_CRM``). The variable names are the same ones
the connectors document in ``.env.example`` and ``docs/CONNECTING.md``.

Secrets are never logged: a failed lookup logs the service and account only.
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("sbk.secrets")

_CONTAINERIZED = os.environ.get("SBK_CONTAINERIZED", "0") == "1"


# (Keychain service, account) -> environment variable read in container mode.
_ENV_MAP = {
    # Google (your own OAuth client): one token per account label in sbk.config.json
    ("sbk-gmail", "*"): "SBK_GMAIL_TOKEN_{account}",
    ("sbk-gdrive", "*"): "SBK_GDRIVE_TOKEN_{account}",
    ("sbk-gdrive", "default"): "SBK_GDRIVE_TOKEN_JSON",
    ("sbk-gcal", "*"): "SBK_GCAL_TOKEN_{account}",
    # Slack (your own Slack app)
    ("sbk-slack", "user-token"): "SBK_SLACK_USER_TOKEN",
    ("sbk-slack", "bot-token"): "SBK_SLACK_BOT_TOKEN",
    ("sbk-slack", "app-level-token"): "SBK_SLACK_APP_TOKEN",
    # Personio
    ("sbk-personio", "client-id"): "PERSONIO_CLIENT_ID",
    ("sbk-personio", "client-secret"): "PERSONIO_CLIENT_SECRET",
    # ClickUp
    ("sbk-clickup", "api-token"): "CLICKUP_API_KEY",
    # Microsoft 365 (tools/microsoft365/ms_graph.py): the saved sign-in of each mailbox label
    ("sbk-microsoft365", "*"): "SBK_MS365_TOKEN_{account}",
    # IMAP and CalDAV (tools/imap-caldav/ic_common.py), one entry per account label
    ("sbk-mailbox", "*"): "SBK_MAILBOX_PASSWORD_{account}",
    ("sbk-caldav", "*"): "SBK_CALDAV_PASSWORD_{account}",
    ("sbk-ics", "*"): "SBK_ICS_URL_{account}",
    ("sbk-imap-oauth", "*"): "SBK_IMAP_OAUTH_REFRESH_{account}",
    # Zoom (tools/zoom/zm_api.py): the app's client id, and one refresh token
    ("sbk-zoom", "client-id"): "ZOOM_CLIENT_ID",
    ("sbk-zoom", "*"): "ZOOM_REFRESH_TOKEN",
    # GitHub (tools/github/gh_api.py): your personal access token
    ("sbk-github", "token"): "GITHUB_TOKEN",
    # Databases (tools/databases/db_reader.py): one connection string per connection name
    ("sbk-databases", "*"): "SBK_DB_URL_{account}",
    # Dashboard basic auth
    ("dashboard", "user"): "SBK_AUTH_USER",
    ("dashboard", "pass"): "SBK_AUTH_PASS",
    # Backup encryption key
    ("sbk-backup", "enc-key"): "SBK_BACKUP_ENC_KEY",
}


def get_secret(service: str, account: str) -> str | None:
    """The secret stored for (service, account), or None when it is not set."""
    if _CONTAINERIZED:
        return _get_from_env(service, account)
    return _get_from_keyring(service, account)


def set_secret(service: str, account: str, value: str) -> None:
    """Store a secret in the Keychain. In container mode it is ignored with a warning."""
    if _CONTAINERIZED:
        log.warning("set_secret ignored in container mode (%s/%s)", service, account)
        return
    import keyring

    keyring.set_password(service, account, value)


def _env_label(account: str) -> str:
    """Account label as it appears in a variable name: upper case, other characters -> _."""
    return re.sub(r"[^A-Z0-9]+", "_", account.upper()).strip("_")


def _get_from_env(service: str, account: str) -> str | None:
    """Container mode: read the environment variable mapped to (service, account)."""
    key = (service, account)
    if key in _ENV_MAP:
        return os.environ.get(_ENV_MAP[key])

    wildcard_key = (service, "*")
    if wildcard_key in _ENV_MAP:
        template = _ENV_MAP[wildcard_key]
        value = os.environ.get(template.replace("{account}", _env_label(account)))
        if value is None and "{account}" in template:
            # older form: the label only upper-cased, kept so existing setups still work
            value = os.environ.get(template.replace("{account}", account.upper()))
        return value
    return None


def _get_from_keyring(service: str, account: str) -> str | None:
    """Read from the system keyring; any keyring error counts as "not set"."""
    try:
        import keyring

        return keyring.get_password(service, account)
    except Exception as e:
        log.warning("keyring.get_password(%s, %s) failed: %s", service, account, e)
        return None
