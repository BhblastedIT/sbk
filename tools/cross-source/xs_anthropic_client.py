""




























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

_chiave_nome: str | None = None
_chiave_pid: int | None = None


def _chiave_dalla_coda() -> tuple[str | None, str | None]:
    ""
    global _chiave_nome, _chiave_pid

    if os.environ.get("SBK_CHIAVI_ANTHROPIC") == "spente":
        return None, None
    try:
        import xs_chiavi
    except Exception:  # noqa: BLE001, without a queue the previous behavior remains
        return None, None
    preferita = os.environ.get("SBK_CHIAVE_ANTHROPIC") or (
        _chiave_nome if _chiave_pid == os.getpid() else None
    )
    try:
        scelta = xs_chiavi.scegli(preferita=preferita)
    except Exception:  # noqa: BLE001, the Keychain doesn't answer: fall back to the environment
        return None, None
    if not scelta:
        return None, None
    _chiave_nome, _chiave_pid = scelta[0], os.getpid()
    return scelta


def chiave_in_uso() -> str | None:
    ""
    return _chiave_nome if _chiave_pid == os.getpid() else None


def usa_chiave(nome: str) -> None:
    ""
    global _chiave_nome, _chiave_pid
    if chiave_in_uso() == nome:
        return
    os.environ["SBK_CHIAVE_ANTHROPIC"] = nome
    _chiave_nome, _chiave_pid = nome, os.getpid()
    reset_client()


def passa_alla_riserva() -> bool:
    ""



    global _chiave_nome, _chiave_pid
    attuale = chiave_in_uso()
    if not attuale:
        return False
    try:
        import xs_chiavi

        riserva = xs_chiavi.prossima_dopo(attuale)
    except Exception:  # noqa: BLE001
        return False
    if not riserva:
        return False
    os.environ["SBK_CHIAVE_ANTHROPIC"] = riserva[0]
    _chiave_nome, _chiave_pid = riserva[0], os.getpid()
    reset_client()
    return True


def get_client(timeout: float | None = None) -> anthropic.Anthropic:
    ""




    global _client, _client_pid, _client_timeout

    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    current_pid = os.getpid()

    with _lock:
        if _client is None or _client_pid != current_pid or _client_timeout != effective_timeout:
            _, api_key = _chiave_dalla_coda()
            api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
            _client = anthropic.Anthropic(
                api_key=api_key,
                timeout=effective_timeout,
                max_retries=DEFAULT_MAX_RETRIES,
            )
            _client_pid = current_pid
            _client_timeout = effective_timeout
        return _client


def reset_client() -> None:
    ""
    global _client, _client_pid, _client_timeout
    with _lock:
        _client = None
        _client_pid = None
        _client_timeout = None


def _is_quota_exhausted(exc: BaseException) -> bool:
    ""



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
    ""





    if isinstance(exc, anthropic.AuthenticationError):
        _segna("non autorizzata")
        return PermanentAPIError(f"Authentication failed (401): {exc}")
    if isinstance(exc, anthropic.PermissionDeniedError):
        _segna("non autorizzata")
        return PermanentAPIError(f"Permission denied (403): {exc}")
    if isinstance(exc, anthropic.NotFoundError):
        return PermanentAPIError(f"Resource not found (model deprecated?): {exc}")
    if isinstance(exc, anthropic.RateLimitError):
        if _is_quota_exhausted(exc):
            _segna("quota finita")
            return PermanentAPIError(f"Quota exhausted (429+insufficient_quota): {exc}")
    if isinstance(exc, anthropic.BadRequestError):
        if _is_quota_exhausted(exc):
            _segna("quota finita")
            return PermanentAPIError(f"Quota exhausted (400): {exc}")
    return None


def _segna(tipo: str) -> None:
    ""
    nome = chiave_in_uso()
    if not nome:
        return
    try:
        import xs_chiavi

        xs_chiavi.segna_errore(nome, tipo)
    except Exception:  # noqa: BLE001, marking must never mask the real error
        pass


def safe_call(fn, *args, **kwargs):
    ""



    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if perm := classify_error(e):
            raise perm from e
        raise
