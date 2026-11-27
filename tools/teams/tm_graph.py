#!/usr/bin/env python3
"""Microsoft Teams plugin core: your own 1:1 and group chats through Microsoft Graph.

Personal access only. It reuses the app registration and the stored sign-in of the
microsoft365 plugin (tools/microsoft365/ms_graph.py, imported, never edited): same client
id, same Keychain entry sbk-microsoft365/<label>, same token-file and env fallbacks.
The Teams sign-in (tm-l0-auth.py) asks for one more per-user scope (your own account),
Chat.Read, which needs no admin consent; the download refreshes with offline_access User.Read Chat.Read.

Out of scope, because Microsoft requires admin consent or application permissions for
them: channel messages (ChannelMessage.Read.All), meeting transcripts
(OnlineMeetingTranscript.Read.All), getAllMessages and its delta (application only).
Personal Microsoft accounts are not supported by the chat APIs: work or school only.

Vendor references (checked 2026-11-25):
- https://learn.microsoft.com/en-us/graph/permissions-reference (Chat.Read, Chat.ReadBasic,
  ChatMessage.Read: per-user (your own account), AdminConsentRequired No; ChatMember.Read,
  ChannelMessage.Read.All, OnlineMeetingTranscript.Read.All: admin consent Yes)
- https://learn.microsoft.com/en-us/graph/api/chat-list ($expand=members returns at most
  25 members; $top at most 50; personal Microsoft accounts not supported)
- https://learn.microsoft.com/en-us/graph/api/chat-list-messages (least privileged Chat.Read;
  $top at most 50; $orderby lastModifiedDateTime desc with $filter lastModifiedDateTime gt)
- https://learn.microsoft.com/en-us/graph/api/chat-list-members (Chat.ReadBasic or Chat.Read)
- https://learn.microsoft.com/en-us/graph/throttling-limits (Teams: GET /me/chats 1 rps per
  user, GET /chats/{id}/messages 1 rps per chat, sustained limit about 83 percent)
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow (the
  scopes of a refresh request must be equivalent to or a subset of the original request)
- https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens (bound to user and
  client, not to a resource; 90 days by default)
Nothing here prints or logs a token.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

_HERE = Path(__file__).resolve().parent
_TOOLS_DIR = _HERE.parent
for _p in (_TOOLS_DIR, _TOOLS_DIR / "microsoft365"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ms_graph as mg  # noqa: E402

import sbk_config  # noqa: E402

log = logging.getLogger("teams")

PLUGIN_ID = "teams"
SOURCE = "teams"
SETUP_HINT = "see docs/CONNECTING.md#teams"

# Per-user (your own account), no admin consent (permissions reference, 2026-11-25). Chat.Read is the
# least privileged permission of List messages in a chat and also covers List chats and
# List members. ChatMessage.Read is not requested: no read API used here lists it.
TEAMS_SCOPES: tuple[str, ...] = ("offline_access", "User.Read", "Chat.Read")
CHAT_SCOPE = "Chat.Read"

# Teams limits (throttling-limits): 1 request per second per user on GET /me/chats and per
# chat on its messages, with a sustained limit near 83 percent. One request every 1.25 s
# (0.8 per second) stays under both.
MIN_INTERVAL_S = 1.25
# List chats with $expand=members returns at most 25 members: re-read the full list then.
EXPANDED_MEMBERS_CAP = 25
MAX_PAGE_SIZE = 50

DEFAULT_CHAT_TYPES = ("oneOnOne", "group")
KNOWN_CHAT_TYPES = ("oneOnOne", "group", "meeting")
DEFAULT_HISTORY_DAYS = 365
DEFAULT_OVERLAP_MINUTES = 10
DEFAULT_TEXT_MAX_CHARS = 20_000
MESSAGE_TEXT_MAX_CHARS = 8_000
MULTI_SEP = "|||"

CONTACT_COLUMNS = [
    "source",
    "name",
    "email",
    "phone",
    "company",
    "title",
    "first_seen",
    "last_seen",
    "interactions",
    "url",
]
INTERACTION_COLUMNS = [
    "source",
    "ts",
    "kind",
    "title",
    "text",
    "participants",
    "owner_role",
    "due",
    "url",
    "status",  # optional in the kernel contract; a chat-day is over: "done"
]

# Data under DATA_ROOT, looked up at call time so tests can point it elsewhere.
DATA_ROOT: Path | None = None


class SetupError(Exception):
    """Missing configuration or sign-in: the message is one line for the user."""


class TokenError(Exception):
    """The identity platform refused the Teams token request."""


GraphError = mg.GraphError


# --------------------------------------------------------------------------- config


def cfg(key: str, default=None):
    return sbk_config.user_cfg(f"teams.{key}", default)


def default_label() -> str:
    return str(
        cfg("account", "") or sbk_config.user_cfg("microsoft365.default_account", "") or "outlook"
    )


def chat_types(include_meeting: bool = False) -> tuple[str, ...]:
    raw = cfg("chat_types", list(DEFAULT_CHAT_TYPES)) or list(DEFAULT_CHAT_TYPES)
    types = [str(t) for t in raw if str(t) in KNOWN_CHAT_TYPES]
    if include_meeting and "meeting" not in types:
        types.append("meeting")
    return tuple(types or DEFAULT_CHAT_TYPES)


def page_size() -> int:
    try:
        n = int(cfg("page_size", MAX_PAGE_SIZE))
    except (TypeError, ValueError):
        n = MAX_PAGE_SIZE
    return max(1, min(MAX_PAGE_SIZE, n))


def int_cfg(key: str, default: int) -> int:
    try:
        return int(cfg(key, default))
    except (TypeError, ValueError):
        return default


def check_label(label: str) -> str:
    try:
        return mg.check_label(label)
    except mg.SetupError as e:
        raise SetupError(one_line(e)) from None


# --------------------------------------------------------------------------- paths


def data_root() -> Path:
    return Path(DATA_ROOT) if DATA_ROOT is not None else Path(sbk_config.DATA_ROOT)


def plugin_root() -> Path:
    return data_root() / PLUGIN_ID


def raw_dir(label: str) -> Path:
    return plugin_root() / "raw" / label


def messages_dir(label: str) -> Path:
    return raw_dir(label) / "messages"


def state_path(label: str) -> Path:
    return raw_dir(label) / "state.json"


def summary_path(label: str) -> Path:
    return raw_dir(label) / "download-summary.json"


def processed_dir() -> Path:
    return plugin_root() / "processed"


def contacts_path() -> Path:
    return processed_dir() / "plugin-contacts.parquet"


def interactions_path() -> Path:
    return processed_dir() / "plugin-interactions.parquet"


def labels_on_disk() -> list[str]:
    base = plugin_root() / "raw"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "me.json").is_file())


def chat_key(chat_id: str) -> str:
    """A file name for a chat id such as 19:abc@thread.v2 (readable, no path characters)."""
    import hashlib

    tail = re.sub(r"[^A-Za-z0-9]+", "-", chat_id)[:40].strip("-")
    return f"{tail}-{hashlib.sha1(chat_id.encode('utf-8')).hexdigest()[:12]}"


def chat_path(chat_id: str) -> str:
    """The chat id as a URL path segment."""
    return quote(chat_id, safe=":@")


# --------------------------------------------------------------------------- JSON files


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_state(label: str) -> dict:
    st = read_json(state_path(label), None)
    if isinstance(st, dict) and isinstance(st.get("chats"), dict):
        return st
    return {"owner": PLUGIN_ID, "label": label, "chats": {}}


# --------------------------------------------------------------------------- sign-in


def scope_names(granted: str) -> set[str]:
    """Scope names of a token response's `scope`, without the resource prefix, lowercase."""
    return {s.rsplit("/", 1)[-1].lower() for s in (granted or "").split()}


def outlook_scopes() -> tuple[str, ...]:
    return tuple(mg.SCOPES)


def sign_in_scopes(with_outlook: bool) -> tuple[str, ...]:
    """Teams scopes, plus the microsoft365 plugin's own when one sign-in serves both."""
    out: list[str] = []
    for s in TEAMS_SCOPES + (outlook_scopes() if with_outlook else ()):
        if s not in out:
            out.append(s)
    return tuple(out)


@contextmanager
def graph_scopes(scopes: tuple[str, ...]):
    """Run a microsoft365 sign-in or refresh call with another scope list.

    ms_graph falls back to its module-level SCOPES when a call gets no scopes= argument;
    this swaps SCOPES for the duration of one call (single-threaded CLI) and always puts
    it back.
    """
    old = mg.SCOPES
    mg.SCOPES = tuple(scopes)
    try:
        yield
    finally:
        mg.SCOPES = old


def _teams_text(e: BaseException, label: str) -> str:
    text = one_line(e)
    # ms_graph suggests its own sign-in script; for Teams the right one is ours.
    text = re.sub(r" \(sign in again: tools/microsoft365/ms-l0-auth\.py; [^)]*\)$", "", text)
    if "invalid_grant" in text or "consent" in text.lower() or "invalid_scope" in text:
        text += f" (run: uv run python tools/teams/tm-l0-auth.py --account {label})"
    return text


def check_record(label: str, record: dict | None) -> dict:
    """The stored sign-in of `label`, checked for Teams. Raises SetupError."""
    if not record:
        raise SetupError(
            f"teams: no sign-in for '{label}' (Keychain {mg.SECRET_SERVICE}/{label}, "
            f"{mg.ENV_TOKEN_FILE} or {mg.env_token_name(label)}); run: uv run python "
            f"tools/teams/tm-l0-auth.py --account {label}"
        )
    if not (record.get("client_id") or mg.client_id()):
        raise SetupError(
            f"teams: no app client id; set {mg.ENV_CLIENT_ID} or microsoft365.client_id in "
            f"sbk.config.json ({SETUP_HINT})"
        )
    if str(record.get("tenant") or "").lower() == "consumers":
        raise SetupError(
            f"teams: the sign-in of '{label}' is for personal Microsoft accounts (tenant "
            "consumers); Microsoft Graph does not serve Teams chats to personal accounts"
        )
    granted = record.get("scopes")
    if granted and CHAT_SCOPE.lower() not in scope_names(str(granted)):
        raise SetupError(
            f"teams: the sign-in of '{label}' has no {CHAT_SCOPE} (it was made by "
            f"ms-l0-auth.py); run: uv run python tools/teams/tm-l0-auth.py --account {label}"
        )
    return record


class TeamsTokenProvider(mg.TokenProvider):
    """microsoft365's token provider, refreshing with the Teams scopes."""

    def __init__(self, label: str, http, record: dict | None = None):
        rec = record if record is not None else mg.load_token_record(label)
        super().__init__(label, http, record=check_record(label, rec))
        self.scopes = TEAMS_SCOPES

    def token(self, force: bool = False) -> str:
        try:
            with graph_scopes(self.scopes):
                return super().token(force=force)
        except mg.TokenError as e:
            raise TokenError(_teams_text(e, self.label)) from None


class PacedGraph(mg.Graph):
    """ms_graph's client (paging, 401 refresh, 429 back-off, Graph-only links) at Teams pace."""

    def __init__(
        self, tokens, http, sleep=time.sleep, interval: float = MIN_INTERVAL_S, clock=None
    ):
        super().__init__(tokens, http, sleep=sleep)
        self.interval = interval
        self.clock = clock or time.monotonic
        self._paced: float | None = None

    def get(self, path_or_url: str, params: dict | None = None, prefer=None) -> dict:
        if self._paced is not None:
            wait = self.interval - (self.clock() - self._paced)
            if wait > 0:
                self.sleep(wait)
        try:
            return super().get(path_or_url, params=params, prefer=prefer)
        finally:
            self._paced = self.clock()

    def items(self, path: str, params: dict | None = None) -> Iterator[dict]:
        for page in self.pages(path, params=params):
            yield from page.get("value") or []


def whoami(graph) -> dict:
    me = graph.get("/me", params={"$select": "id,displayName,mail,userPrincipalName"})
    return {
        "id": me.get("id") or "",
        "displayName": me.get("displayName") or "",
        "mail": me.get("mail") or "",
        "userPrincipalName": me.get("userPrincipalName") or "",
    }


def one_line(e: BaseException) -> str:
    """The single stderr line a CLI prints for an expected failure."""
    lines = str(e).strip().splitlines()
    text = lines[0] if lines else type(e).__name__
    if text.startswith("microsoft365: "):
        text = text[len("microsoft365: ") :]
    return text if text.startswith("teams") else f"teams: {text}"
