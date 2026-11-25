"""Secret redaction for AI-history messages.

Every message the AI-history readers keep passes through `redact()` before it is
written. The rules follow the ids of gitleaks' default rule set (the repo's
`.gitleaks.toml` extends it), so a hit here is named like a gitleaks finding.

A secret is replaced by `[REDACTED:<rule-id>]`; the text around it stays. For
`key = value` style assignments only the value is replaced, so the sentence
still reads ("my api_key = [REDACTED:generic-api-key]").

Email addresses are kept unless `emails=True` (flag `--redact-emails` on the
readers): your own messages often name people you write to, and the "how you
work" files do not need them.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# (rule id, compiled pattern). Order matters: specific vendors first, the
# generic assignment rule last, so a known key is named by its vendor.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(
            r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----"
            r"[\s\S]*?-----END[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----"
        ),
    ),
    ("anthropic-api-key", re.compile(r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}")),
    (
        "openai-api-key",
        re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}T3BlbkFJ[A-Za-z0-9_-]{20,}"),
    ),
    ("openai-api-key", re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{40,}")),
    ("github-pat", re.compile(r"\bghp_[A-Za-z0-9]{36,}")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("github-oauth", re.compile(r"\bgho_[A-Za-z0-9]{36,}")),
    ("github-app-token", re.compile(r"\b(?:ghu|ghs)_[A-Za-z0-9]{36,}")),
    ("github-refresh-token", re.compile(r"\bghr_[A-Za-z0-9]{36,}")),
    ("gitlab-pat", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack-bot-token", re.compile(r"\bxoxb-[0-9]{8,}-[0-9]{8,}-[A-Za-z0-9-]{16,}")),
    ("slack-user-token", re.compile(r"\bxox[pe](?:-[0-9]{8,}){3}-[A-Za-z0-9]{20,}")),
    ("slack-app-token", re.compile(r"\bxapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+", re.IGNORECASE)),
    ("slack-legacy-token", re.compile(r"\bxox[aboprs]-(?:\d+-)?[A-Za-z0-9-]{10,48}")),
    (
        "slack-webhook-url",
        re.compile(
            r"https?://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/_-]{20,}"
        ),
    ),
    ("aws-access-token", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b")),
    ("gcp-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("google-oauth-client-secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{28}\b")),
    ("google-oauth-access-token", re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}")),
    ("google-oauth-refresh-token", re.compile(r"\b1//0[0-9A-Za-z_-]{30,}")),
    ("stripe-access-token", re.compile(r"\b(?:sk|rk)_(?:live|test|prod)_[A-Za-z0-9]{10,99}\b")),
    ("npm-access-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("pypi-upload-token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}")),
    ("huggingface-access-token", re.compile(r"\bhf_[A-Za-z]{34}\b")),
    ("notion-api-token", re.compile(r"\b(?:secret_[A-Za-z0-9]{43}|ntn_[A-Za-z0-9]{40,})\b")),
    ("sendgrid-api-token", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b")),
    ("twilio-api-key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("mailgun-private-api-token", re.compile(r"\bkey-[a-f0-9]{32}\b")),
    ("linear-api-key", re.compile(r"\blin_api_[A-Za-z0-9]{40}\b")),
    ("clickup-api-token", re.compile(r"\bpk_\d{6,}_[A-Z0-9]{32}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    # user:password@ inside a URL: only the password is replaced.
    ("url-credentials", re.compile(r"(?<=://)([^\s:/@]{1,64}):([^\s/@]{3,128})(?=@)")),
    # Authorization: Bearer <token>
    ("bearer-token", re.compile(r"(?i)(?<=\bbearer\s)[A-Za-z0-9._~+/=-]{20,}")),
]

# `name = value`, `name: value`, `"name": "value"`, `NAME=value` with a
# secret-looking name. Only the value (group "v") is replaced, and only when it
# looks random enough (see _looks_secret), like gitleaks' generic-api-key.
_GENERIC = re.compile(
    r"(?i)(?P<k>\b[\w.-]{0,30}(?:api[_-]?key|apikey|secret|token|passwd|password|pwd|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret|auth)[\w.-]{0,20}\b)"
    r"(?P<sep>[\"']?\s{0,3}(?::|=|:=|=>)\s{0,3}[\"']?)"
    r"(?P<v>[A-Za-z0-9_\-+/=.~!@#$%^&*]{8,200})"
)

_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}\b"
)


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _looks_secret(value: str) -> bool:
    if value.startswith("[REDACTED"):
        return False
    if value.lower() in {
        "password",
        "changeme",
        "redacted",
        "xxxxxxxx",
        "none",
        "null",
        "true",
        "false",
    }:
        return False
    has_digit = any(ch.isdigit() for ch in value)
    has_alpha = any(ch.isalpha() for ch in value)
    return has_digit and has_alpha and _entropy(value) >= 3.0


def redact(text: str, emails: bool = False) -> tuple[str, Counter]:
    """Return (text with secrets replaced, Counter of rule id -> hits)."""
    hits: Counter = Counter()
    if not text:
        return text, hits
    for rule_id, pattern in _RULES:
        if rule_id == "url-credentials":

            def _url(m: re.Match[str]) -> str:
                hits["url-credentials"] += 1
                return f"{m.group(1)}:[REDACTED:url-credentials]"

            text = pattern.sub(_url, text)
            continue

        def _sub(m: re.Match[str], rule_id: str = rule_id) -> str:
            hits[rule_id] += 1
            return f"[REDACTED:{rule_id}]"

        text = pattern.sub(_sub, text)

    def _generic(m: re.Match[str]) -> str:
        if not _looks_secret(m.group("v")):
            return m.group(0)
        hits["generic-api-key"] += 1
        return f"{m.group('k')}{m.group('sep')}[REDACTED:generic-api-key]"

    text = _GENERIC.sub(_generic, text)

    if emails:

        def _mail(m: re.Match[str]) -> str:
            hits["email"] += 1
            return "[REDACTED:email]"

        text = _EMAIL.sub(_mail, text)
    return text, hits
