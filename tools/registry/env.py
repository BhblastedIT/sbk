""

















from __future__ import annotations

import os
import re


SAFE_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "VIRTUAL_ENV",
        "SBK_DATA_ROOT",
        "SBK_ENV",
        "TERM",
    }
)


PAID_ENV_PREFIXES = ("ANTHROPIC_",)


_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*\S{8,}"),
)


class SecretInArgvError(ValueError):
    ""


def assert_no_secrets_in_argv(args: list[str]) -> None:
    ""




    for i, a in enumerate(args):
        if not isinstance(a, str):
            continue
        for pat in _SECRET_PATTERNS:
            if pat.search(a):
                raise SecretInArgvError(
                    f"argument #{i} looks like a plaintext secret "
                    f"(pattern {pat.pattern!r}); pass secrets through env/Keychain, never in argv"
                )


def build_env(
    *,
    paid: bool,
    base_env: dict | None = None,
    extra: dict | None = None,
) -> dict:
    ""









    src = dict(os.environ if base_env is None else base_env)
    out: dict[str, str] = {}

    for key, value in src.items():

        if key in SAFE_ENV_ALLOWLIST or (
            paid and any(key.startswith(p) for p in PAID_ENV_PREFIXES)
        ):
            out[key] = value


    if extra:
        for key, value in extra.items():
            is_paid_key = any(key.startswith(p) for p in PAID_ENV_PREFIXES)
            if is_paid_key and not paid:
                continue
            out[key] = value

    if not paid:

        for key in list(out):
            if any(key.startswith(p) for p in PAID_ENV_PREFIXES):
                del out[key]

    return out
