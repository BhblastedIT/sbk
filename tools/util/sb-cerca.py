#!/usr/bin/env python3
"""Searches everything you said, wrote and received (mail, chats, transcripts, knowledge base), with secrets masked.

Usage:
    python tools/util/sb-cerca.py "your question" [--source S] [--after YYYY-MM-DD] [--person NAME] [--top N]
                                  [--synthesize]
    python tools/util/sb-cerca.py --self-test   self-test of the masking

It runs tools/cross-source/xs-l3-search.py and masks passwords, tokens and API keys in every line it prints:
labelled secrets ("password: ...", "token=...") and the known key formats (Anthropic, OpenAI, Slack, GitHub,
GitLab, AWS, Google, Stripe, Hugging Face, Notion, JWT, private key blocks, Bearer tokens), as [MASKED].
Raw results by default, nothing is sent to a model. --synthesize also sends your question and the results to
Claude with your own claude login (claude -p) for an answer; this wrapper says so before it starts.
"""












from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MOTORE = Path(__file__).resolve().parent.parent / "cross-source" / "xs-l3-search.py"





_ETICHETTA = re.compile(
    r"(?i)\b(password|passwd|pwd|pass|passcode|passphrase|parola\s+d['’]?ordine|parola\s+chiave|pin|"
    r"secret|segreto|token|api[\s_-]?key|chiave(?:\s+api)?)(\s*[:=]\s*|\s+[eè]['’]?\s+|\s+is\s+)(\S+)"
)


MASK = "[MASKED]"

# Known key formats, matched anywhere in a line even without a label (the ids follow gitleaks' default rules).
# Self-contained on purpose: the wrapper must mask even when nothing else of the kit is importable.
_FORMATI: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----",
        r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----",  # a block cut across lines
        r"\bsk-ant-[A-Za-z0-9]{2,10}-[A-Za-z0-9_-]{20,}",  # Anthropic
        r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",  # OpenAI and other sk- keys
        r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}",  # Slack tokens
        r"\bxapp-\d-[A-Za-z0-9-]{10,}",  # Slack app-level token
        r"https?://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/_-]{20,}",
        r"\bgh[pousr]_[A-Za-z0-9]{30,}",  # GitHub tokens
        r"\bgithub_pat_[A-Za-z0-9_]{40,}",
        r"\bglpat-[A-Za-z0-9_-]{20,}",  # GitLab
        r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b",  # AWS access key id
        r"\bAIza[0-9A-Za-z_-]{35}\b",  # Google API key
        r"\bGOCSPX-[A-Za-z0-9_-]{20,}",  # Google OAuth client secret
        r"\bya29\.[0-9A-Za-z_-]{20,}",  # Google OAuth access token
        r"\b1//0[0-9A-Za-z_-]{30,}",  # Google OAuth refresh token
        r"\b(?:sk|rk|pk)_(?:live|test|prod)_[A-Za-z0-9]{10,99}\b",  # Stripe
        r"\bhf_[A-Za-z0-9]{30,}\b",  # Hugging Face
        r"\b(?:secret_[A-Za-z0-9]{40,}|ntn_[A-Za-z0-9]{40,})\b",  # Notion
        r"\bnpm_[A-Za-z0-9]{36}\b",
        r"\blin_api_[A-Za-z0-9]{40}\b",  # Linear
        r"\bpk_\d{6,}_[A-Z0-9]{32}\b",  # ClickUp
        r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",  # JWT
        r"(?i)(?<=\bbearer\s)[A-Za-z0-9._~+/=-]{20,}",  # Authorization: Bearer <token>
        r"(?<=://)[^\s:/@]{1,64}:[^\s/@]{3,128}(?=@)",  # user:password@ inside a URL
    )
)


def oscura(testo: str) -> str:
    """Mask labelled secrets and known key formats in one line of text."""
    testo = _ETICHETTA.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", testo)
    for pat in _FORMATI:
        testo = pat.sub(MASK, testo)
    return testo


def _prova() -> int:
    """--self-test: every known case must be masked, plain prose must stay untouched."""
    casi = {
        "Username: sam  Password: Abc!12345": f"Password: {MASK}",
        "the password is q9#Lm2": "",
        "pwd=xyz123 rest": f"pwd={MASK}",
        "api key: sk-abcdefghijklmnopqrstuvwxyz": MASK,
        "Bearer abcdefghijklmnopqrstuvwxyz0123": MASK,
        "key sk-ant-api03-" + "A" * 30 + " in a note": MASK,
        "slack xoxp-1234567890-1234567890-abcdefABCDEF": MASK,
        "repo ghp_" + "a1B2" * 9 + " pushed": MASK,
        "aws AKIA" + "ABCDEFGHIJKLMNOP" + " here": MASK,
        "no secret here, just a sentence about the handover": None,
    }
    sbagli = 0
    for entrata, atteso in casi.items():
        uscita = oscura(entrata)
        if atteso is None:
            ok = uscita == entrata
        elif atteso == "":
            ok = "q9#Lm2" not in uscita
        else:
            ok = atteso in uscita
        print(("OK  " if ok else "NO  ") + uscita)
        sbagli += 0 if ok else 1
    print(f"self-test: {len(casi) - sbagli} of {len(casi)} passed")
    return 1 if sbagli else 0


def _sintesi_da_config() -> bool:
    """True when sbk.config.json has "search": {"synthesis": true}."""
    tools = str(MOTORE.parent.parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import sbk_config

        return sbk_config.user_cfg("search.synthesis", False) is True
    except Exception:  # noqa: BLE001, unreadable config = the default, raw results
        return False


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] in ("--self-test", "--prova"):  # --prova: hidden alias, older name
        return _prova()


    tradotti = {
        "--fonte": "--source",
        "--dal": "--after",
        "--persona": "--person",
        "--quanti": "--top",
        "--grezzo": "--no-synthesis",
    }
    argomenti = [tradotti.get(a, a) for a in sys.argv[1:]]

    cmd = [sys.executable, str(MOTORE), *argomenti]
    if "--no-synthesis" not in argomenti and ("--synthesize" in argomenti or _sintesi_da_config()):
        # The engine's own log line goes to stderr, which this wrapper hides: announce it here.
        print("Sending your question and the results to Claude with your own claude login (claude -p).")


    with open(os.devnull, "w") as nulla:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=nulla, text=True, bufsize=1)
        assert proc.stdout is not None
        for riga in proc.stdout:
            sys.stdout.write(oscura(riga))
            sys.stdout.flush()
        return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
