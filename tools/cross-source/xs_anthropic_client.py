"""One Anthropic client for every paid stage.

The key is ANTHROPIC_API_KEY, read from the environment (the pipeline loads .env into it).
There is one key and one client per process. A key that is rejected or out of credit stops
the stage with a clear error.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import anthropic

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import PermanentAPIError

DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 2
BATCH_TIMEOUT = 600.0

_client = None
_client_pid = None
_client_timeout = None
_lock = threading.Lock()


def get_client(timeout: float | None = None) -> anthropic.Anthropic:
    """The shared client, built from ANTHROPIC_API_KEY (one per process and timeout)."""
    global _client, _client_pid, _client_timeout

    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    current_pid = os.getpid()

    with _lock:
        if _client is None or _client_pid != current_pid or _client_timeout != effective_timeout:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set: put it in .env or in the environment"
                )
            _client = anthropic.Anthropic(
                api_key=api_key,
                timeout=effective_timeout,
                max_retries=DEFAULT_MAX_RETRIES,
            )
            _client_pid = current_pid
            _client_timeout = effective_timeout
        return _client


def reset_client() -> None:
    """Forget the cached client (the next get_client builds a new one)."""
    global _client, _client_pid, _client_timeout
    with _lock:
        _client = None
        _client_pid = None
        _client_timeout = None


def _is_quota_exhausted(exc: BaseException) -> bool:
    """True when the error says the account has no credit or quota left."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            etype = (err.get("type") or "").lower()
            emsg = (err.get("message") or "").lower()
            if etype in ("insufficient_quota", "billing_error", "credit_balance_too_low"):
                return True
            if "insufficient" in emsg and ("quota" in emsg or "credit" in emsg):
                return True
            if "credit balance" in emsg:
                return True

    text = (str(exc) + " " + str(getattr(exc, "body", ""))).lower()
    markers = (
        "insufficient_quota",
        "credit balance is too low",
        "billing",
        "credit_balance_too_low",
    )
    return any(m in text for m in markers)


def classify_error(exc: BaseException) -> PermanentAPIError | None:
    """A PermanentAPIError for errors a retry cannot fix (bad key, no credit, unknown model), else None."""
    if isinstance(exc, anthropic.AuthenticationError):
        return PermanentAPIError(f"Authentication failed (401), check ANTHROPIC_API_KEY: {exc}")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return PermanentAPIError(f"Permission denied (403), check ANTHROPIC_API_KEY: {exc}")
    if isinstance(exc, anthropic.NotFoundError):
        return PermanentAPIError(f"Resource not found (model deprecated?): {exc}")
    if isinstance(exc, anthropic.RateLimitError):
        if _is_quota_exhausted(exc):
            return PermanentAPIError(f"Quota exhausted (429+insufficient_quota): {exc}")
    if isinstance(exc, anthropic.BadRequestError):
        if _is_quota_exhausted(exc):
            return PermanentAPIError(f"Quota exhausted (400): {exc}")
    return None


def safe_call(fn, *args, **kwargs):
    """Call fn and turn permanent API errors into PermanentAPIError."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if perm := classify_error(e):
            raise perm from e
        raise
