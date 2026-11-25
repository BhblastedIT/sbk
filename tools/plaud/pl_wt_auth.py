#!/usr/bin/env python3
""






















from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any



CANONICAL_KEYS: dict[str, str] = {
    "UT": "authToken",
    "URT": "urtToken",
    "WT": "wtToken",
    "WRT": "wrtToken",
}


_WORKSPACE_CLAIMS = ("workspace_id", "ws", "wid", "ws_id", "workspaceId")

_REFRESH_MARKERS = ("refresh", "wrt", "urt")


class TokenKind(str, Enum):
    ""

    UT = "UT"
    URT = "URT"
    WT = "WT"
    WRT = "WRT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RefreshStep:
    ""



    trigger_code: int
    method: str
    path_template: str
    token_used: TokenKind
    mints: TokenKind



REFRESH_CHAIN: dict[int, RefreshStep] = {
    -419: RefreshStep(
        trigger_code=-419,
        method="POST",
        path_template="/user-app/auth/workspace/refresh/{ws}",
        token_used=TokenKind.WRT,
        mints=TokenKind.WT,
    ),
    -420: RefreshStep(
        trigger_code=-420,
        method="POST",
        path_template="/user-app/auth/workspace/token/{ws}",
        token_used=TokenKind.UT,
        mints=TokenKind.WT,
    ),
    401: RefreshStep(
        trigger_code=401,
        method="POST",
        path_template="/auth/refresh-user-token",
        token_used=TokenKind.URT,
        mints=TokenKind.UT,
    ),
}


def strip_bearer_prefix(token: str) -> str:
    ""

    t = token.strip()
    low = t.lower()
    if low.startswith("bearer "):
        return t[7:].strip()
    return t


def decode_jwt_payload(token: str) -> dict[str, Any]:
    ""



    raw = strip_bearer_prefix(token)
    parts = raw.split(".")
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1]

    padding = "-" * 0 + "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
    except (binascii.Error, ValueError):
        return {}
    try:
        data = json.loads(decoded)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def decode_jwt_header(token: str) -> dict[str, Any]:
    ""




    raw = strip_bearer_prefix(token)
    parts = raw.split(".")
    if len(parts) != 3:
        return {}
    header_b64 = parts[0]
    padding = "=" * (-len(header_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(header_b64 + padding)
        data = json.loads(decoded)
    except (binascii.Error, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}



_HEADER_TYP_MAP: dict[str, TokenKind] = {
    "WT": TokenKind.WT,
    "WRT": TokenKind.WRT,
    "UT": TokenKind.UT,
    "URT": TokenKind.URT,
}


def _has_workspace_scope(payload: dict[str, Any]) -> bool:
    return any(claim in payload and payload[claim] for claim in _WORKSPACE_CLAIMS)


def _is_refresh(payload: dict[str, Any]) -> bool:
    typ = str(payload.get("typ", "")).lower()
    token_type = str(payload.get("token_type", "")).lower()
    scope = str(payload.get("scope", "")).lower()
    haystack = f"{typ} {token_type} {scope}"
    return any(marker in haystack for marker in _REFRESH_MARKERS)


def classify_token(token: str) -> TokenKind:
    ""










    header = decode_jwt_header(token)
    typ = str(header.get("typ", "")).upper()
    if typ in _HEADER_TYP_MAP:
        return _HEADER_TYP_MAP[typ]

    payload = decode_jwt_payload(token)
    if not payload:
        return TokenKind.UNKNOWN
    has_ws = _has_workspace_scope(payload)
    is_refresh = _is_refresh(payload)
    if has_ws and is_refresh:
        return TokenKind.WRT
    if has_ws:
        return TokenKind.WT
    if is_refresh:
        return TokenKind.URT
    return TokenKind.UT


def select_token(store: dict[str, Any], kind: TokenKind) -> str | None:
    ""





    if kind == TokenKind.UNKNOWN:
        return None

    for value in store.values():
        if isinstance(value, str) and classify_token(value) == kind:
            return value

    canonical = CANONICAL_KEYS.get(kind.value)
    if canonical and isinstance(store.get(canonical), str):
        return store[canonical]
    return None


def extract_auth_context(store: dict[str, Any]) -> dict[str, Any]:
    ""




    workspace_list = store.get("workspaceList") or []
    api_domain = store.get("apiDomain")
    if not api_domain and isinstance(workspace_list, list) and workspace_list:
        first = workspace_list[0]
        if isinstance(first, dict):
            api_domain = first.get("api_domain")
    return {
        "ut": select_token(store, TokenKind.UT),
        "urt": select_token(store, TokenKind.URT),
        "wt": select_token(store, TokenKind.WT),
        "wrt": select_token(store, TokenKind.WRT),
        "api_domain": api_domain,
        "device_secret": store.get("deviceSecret"),
        "workspace_list": workspace_list,
    }


def plan_refresh(error_code: int) -> RefreshStep | None:
    ""
    return REFRESH_CHAIN.get(error_code)
