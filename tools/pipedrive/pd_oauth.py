#!/usr/bin/env python3
"""Pipedrive OAuth for your own private app: authorize URL, code exchange, refresh.

Only needed if you sign in with an app instead of your personal API token. The app
is one you register yourself, as a private app in the Developer Hub of your own
developer sandbox account, with read-only scopes, and install into your own company
for yourself only (no admin step, no app sharing).

The only POST of the plugin lives here, and it goes to one URL:
https://oauth.pipedrive.com/oauth/token (HTTP Basic auth with client_id:client_secret,
form-encoded body). Vendor facts (Pipedrive docs, checked 2026-11-25):
https://pipedrive.readme.io/docs/marketplace-oauth-authorization
  * authorize: GET https://oauth.pipedrive.com/oauth/authorize?client_id&redirect_uri&state;
  * the authorization code expires in 5 minutes;
  * token answer: access_token (60 minutes), refresh_token (expires if unused for
    60 days; each use extends it), scope, expires_in, api_domain;
  * one callback URL per app, it must match `redirect_uri`.
Scopes: https://pipedrive.readme.io/docs/marketplace-scopes-and-permissions-explanations
Nothing here prints or logs a token.
"""

from __future__ import annotations

import base64
from urllib.parse import urlencode

import pd_api

AUTHORIZE_URL = "https://oauth.pipedrive.com/oauth/authorize"
TOKEN_URL = "https://oauth.pipedrive.com/oauth/token"
REDIRECT_PATH = "/callback"
DEFAULT_PORT = 8765

#: Read-only scopes the plugin needs. `base` (GET /users/me) is always on for every app.
REQUIRED_SCOPES = ("deals:read", "contacts:read", "activities:read")


class OAuthError(RuntimeError):
    """One clear line for the user; never carries a token."""


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}{REDIRECT_PATH}"


def authorize_url(cid: str, redirect: str, state: str) -> str:
    return (
        AUTHORIZE_URL
        + "?"
        + urlencode({"client_id": cid, "redirect_uri": redirect, "state": state})
    )


def _basic(cid: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _post_token(session, cid: str, secret: str, form: dict) -> dict:
    if session is None:
        import requests

        session = requests.Session()
    try:
        resp = session.post(
            TOKEN_URL,
            data=form,
            headers={
                "Authorization": _basic(cid, secret),
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": pd_api.USER_AGENT,
            },
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        raise OAuthError(
            f"network error talking to oauth.pipedrive.com ({type(exc).__name__})"
        ) from None
    if resp.status_code in (400, 401):
        raise OAuthError(
            f"Pipedrive refused the token request (HTTP {resp.status_code}): check the client ID "
            "and secret of your app, or sign in again with pd-l0-auth.py (a refresh token "
            "unused for 60 days expires)"
        )
    if not 200 <= resp.status_code < 300:
        raise OAuthError(f"Pipedrive token request failed (HTTP {resp.status_code})")
    data = resp.json() or {}
    if not data.get("access_token"):
        raise OAuthError("Pipedrive sent no access token")
    return data


def exchange_code(session, cid: str, secret: str, code: str, redirect: str) -> dict:
    return _post_token(
        session,
        cid,
        secret,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect},
    )


def refresh(session, cid: str, secret: str, refresh_token: str) -> dict:
    return _post_token(
        session, cid, secret, {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


def missing_scopes(granted: str) -> list[str]:
    have = set(str(granted or "").replace(",", " ").split())
    return [s for s in REQUIRED_SCOPES if s not in have]


def extra_scopes(granted: str) -> list[str]:
    """Granted scopes that can change or administer your account (the plugin needs none)."""
    have = str(granted or "").replace(",", " ").split()
    return [s for s in have if s == "admin" or s.endswith(":full")]


def make_refresher(auth: pd_api.Auth, session=None):
    """() -> a fresh access token; updates auth.oauth['api_domain'] and stores a new refresh token."""

    def _do() -> str:
        o = auth.oauth
        data = refresh(session, o["client_id"], o["client_secret"], o["refresh_token"])
        new_rt = data.get("refresh_token") or ""
        if new_rt and new_rt != o["refresh_token"]:
            o["refresh_token"] = new_rt
            pd_api.save_refresh_token(new_rt)
        o["api_domain"] = str(data.get("api_domain") or o.get("api_domain") or "")
        auth.token = data["access_token"]
        return auth.token

    return _do
