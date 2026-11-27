#!/usr/bin/env python3
"""DocuSign L0 download via the API (JWT Grant)."""















































from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import DATA_ROOT, DOCUSIGN_RAW_DIR, mark_last_run, safe_write_json  # noqa: E402

log = logging.getLogger("ds-l0-api")

SERVICE = "sbk-docusign"
# Default: <data root>/secrets/docusign-private.key (follows SBK_DATA_ROOT).
KEY_FILE = Path(
    os.environ.get("DOCUSIGN_PRIVATE_KEY_PATH")
    or str(DATA_ROOT / "secrets" / "docusign-private.key")
).expanduser()

AUTH_HOST = os.environ.get("DOCUSIGN_AUTH_HOST") or "account.docusign.com"  # empty = default
SCOPES = "signature impersonation"
REDIRECT_URI = (
    os.environ.get("DOCUSIGN_REDIRECT_URI") or "http://localhost:8765/docusign/callback"
)
DAL_PRINCIPIO = "2015-01-01T00:00:00Z"
PAGINA = 100
PAUSA_S = 0.25

OUT_DIR = DOCUSIGN_RAW_DIR / "raw"
ENVELOPES_FILE = OUT_DIR / "envelopes-api.json"
DETAILS_FILE = OUT_DIR / "contract-details.json"
METADATA_FILE = DOCUSIGN_RAW_DIR / "contracts-metadata.json"



RUOLI = {
    "signers": "signer",
    "carbonCopies": "carbonCopy",
    "certifiedDeliveries": "certifiedDelivery",
    "inPersonSigners": "inPersonSigner",
    "agents": "agent",
    "editors": "editor",
    "intermediaries": "intermediary",
    "seals": "seal",
    "witnesses": "witness",
}





def _cred(nome: str, env: str) -> str:
    v = os.environ.get(env) or get_secret(SERVICE, nome)
    if not v:
        raise RuntimeError(
            f"missing `{nome}`: Keychain {SERVICE}/{nome} or env {env}. "
            "Values come from the Apps and Keys page of the production account."
        )
    return v.strip()


def _chiave_privata():
    from cryptography.hazmat.primitives import serialization

    if not KEY_FILE.exists():
        raise RuntimeError(f"RSA private key not found: {KEY_FILE} (permissions 600)")
    return serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)





def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def crea_jwt(integration_key: str, user_id: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    ora = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    corpo = {
        "iss": integration_key,
        "sub": user_id,
        "aud": AUTH_HOST,
        "iat": ora,
        "exp": ora + 3600,
        "scope": SCOPES,
    }
    da_firmare = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(corpo, separators=(",", ":")).encode())
    )
    firma = _chiave_privata().sign(da_firmare.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{da_firmare}.{_b64url(firma)}"


def consent_url(integration_key: str) -> str:
    from urllib.parse import urlencode

    q = urlencode(
        {
            "response_type": "code",
            "scope": SCOPES,
            "client_id": integration_key,
            "redirect_uri": REDIRECT_URI,
        }
    )
    return f"https://{AUTH_HOST}/oauth/auth?{q}"


def access_token(integration_key: str, user_id: str) -> str:
    r = requests.post(
        f"https://{AUTH_HOST}/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": crea_jwt(integration_key, user_id),
        },
        timeout=30,
    )
    if r.status_code != 200:
        corpo = r.text[:300]
        if "consent_required" in corpo:
            raise RuntimeError(
                "consent not granted yet: open the `--consent-url` URL in a browser, "
                "accept, then run again."
            )
        raise RuntimeError(f"token rejected (HTTP {r.status_code}): {corpo}")
    return r.json()["access_token"]


def userinfo(token: str) -> dict:
    r = requests.get(
        f"https://{AUTH_HOST}/oauth/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def account_di(info: dict, account_id: str | None) -> tuple[str, str]:
    ""
    conti = info.get("accounts") or []
    if not conti:
        raise RuntimeError("userinfo has no account: the user does not belong to any account")
    if account_id:
        for c in conti:
            if c.get("account_id", "").lower() == account_id.lower():
                return c["account_id"], c["base_uri"]
        raise RuntimeError(
            f"account-id is not among the user's accounts ({len(conti)} available): "
            "check `account-id` in the Keychain"
        )
    c = next((c for c in conti if c.get("is_default")), conti[0])
    return c["account_id"], c["base_uri"]





def elenca_buste(token: str, base_uri: str, account_id: str, da: str) -> list[dict]:
    ""
    intest = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes"
    fuori: list[dict] = []
    posizione = 0
    while True:
        r = requests.get(
            url,
            headers=intest,
            params={
                "from_date": da,
                "include": "recipients",
                "count": PAGINA,
                "start_position": posizione,
                "order": "desc",
                "order_by": "last_modified",
            },
            timeout=60,
        )
        if r.status_code == 429:
            attesa = int(r.headers.get("Retry-After", "30"))
            log.warning("  429: waiting %ss", attesa)
            time.sleep(attesa)
            continue
        r.raise_for_status()
        d = r.json()
        voci = d.get("envelopes") or []
        fuori.extend(voci)
        totale = int(d.get("totalSetSize") or 0)
        log.info("  envelopes %d/%d", len(fuori), totale)
        if not voci or len(fuori) >= totale:
            break
        posizione = int(d.get("endPosition", posizione)) + 1
        time.sleep(PAUSA_S)
    return fuori


def destinatari(env: dict) -> list[dict]:
    rec = env.get("recipients") or {}
    fuori = []
    for gruppo, ruolo in RUOLI.items():
        for r in rec.get(gruppo) or []:
            fuori.append(
                {
                    "name": r.get("name", ""),
                    "email": r.get("email", ""),
                    "role": ruolo,
                    "status": r.get("status", ""),
                    "recipientId": r.get("recipientId", ""),
                    "routingOrder": r.get("routingOrder", ""),
                    "deliveredDateTime": r.get("deliveredDateTime", ""),
                    "signedDateTime": r.get("signedDateTime", ""),
                    "source": "api",
                }
            )
    return fuori


def _mdY(iso: str) -> str:
    ""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{dt.month}/{dt.day}/{dt.year}"


def per_l1(env: dict) -> dict:
    ""
    mittente = env.get("sender") or {}
    stato = (env.get("status") or "").strip()
    return {
        "name": env.get("emailSubject") or "",
        "from": mittente.get("userName") or mittente.get("email") or "",
        "status": stato[:1].upper() + stato[1:] if stato else "",
        "date": _mdY(env.get("completedDateTime") or env.get("sentDateTime") or ""),
        "page": 0,
        "envelopeId": env.get("envelopeId", ""),
    }


def unisci_con_precedenti(nuovi: list[dict]) -> list[dict]:
    ""






    try:
        vecchi = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return nuovi

    def nome(r: dict) -> str:
        return re.sub(r"\W+", "", str(r.get("name", "")).lower())

    ids = {r.get("envelopeId") for r in nuovi if r.get("envelopeId")}


    mittenti_per_nome: dict[str, set[str]] = {}
    for r in nuovi:
        mittenti_per_nome.setdefault(nome(r), set()).add(str(r.get("from", "")).strip().lower())

    def gia_presente(r: dict) -> bool:
        if r.get("envelopeId") and r["envelopeId"] in ids:
            return True
        mitt = mittenti_per_nome.get(nome(r))
        if mitt is None:
            return False
        vecchio = str(r.get("from", "")).strip().lower()
        return not vecchio or "" in mitt or vecchio in mitt

    tenuti = [r for r in vecchi if isinstance(r, dict) and r.get("name") and not gia_presente(r)]
    if tenuti:
        log.info("  kept %d records from the previous file that the API does not return", len(tenuti))
    return nuovi + tenuti


def fondi_buste(nuove: list[dict]) -> list[dict]:
    ""






    if not ENVELOPES_FILE.exists():
        return nuove
    vecchie = json.loads(ENVELOPES_FILE.read_text(encoding="utf-8")).get("envelopes") or []
    lette = {e.get("envelopeId") for e in nuove}
    tenute = [e for e in vecchie if e.get("envelopeId") and e["envelopeId"] not in lette]
    if tenute:
        log.info("  kept %d envelopes already on disk that this run did not re-read", len(tenute))
    return nuove + tenute


def scrivi(buste: list[dict]) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    buste = fondi_buste(buste)
    preso_il = datetime.now(UTC).isoformat()
    safe_write_json(ENVELOPES_FILE, {"preso_il": preso_il, "n": len(buste), "envelopes": buste})

    dettagli = []
    for e in buste:
        rec = destinatari(e)
        dettagli.append(
            {
                "envelopeId": e.get("envelopeId", ""),
                "name": e.get("emailSubject", ""),
                "status": e.get("status", ""),
                "sentDateTime": e.get("sentDateTime", ""),
                "completedDateTime": e.get("completedDateTime", ""),
                "sender": {
                    "name": (e.get("sender") or {}).get("userName", ""),
                    "email": (e.get("sender") or {}).get("email", ""),
                },
                "recipients": rec,
                "recipientCount": len(rec),
                "scrapedAt": preso_il,
                "method": "api",
            }
        )
    safe_write_json(DETAILS_FILE, sorted(dettagli, key=lambda d: d.get("name", "")))


    if METADATA_FILE.exists():
        bak = METADATA_FILE.with_name(
            f"contracts-metadata.json.bak-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
        )
        shutil.copy2(METADATA_FILE, bak)
    safe_write_json(METADATA_FILE, unisci_con_precedenti([per_l1(e) for e in buste]))

    con_dest = sum(1 for d in dettagli if d["recipientCount"])
    email = {r["email"].lower() for d in dettagli for r in d["recipients"] if r.get("email")}
    return {"buste": len(buste), "con_destinatari": con_dest, "email_uniche": len(email)}





def main() -> int:
    ap = argparse.ArgumentParser(description="L0 DocuSign via API (JWT Grant)")
    ap.add_argument("--dry-run", action="store_true", help="token + userinfo + count")
    ap.add_argument("--since", help="YYYY-MM-DD: only envelopes changed since this date")
    ap.add_argument("--consent-url", action="store_true", help="print the consent URL")
    a = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )

    try:
        ik = _cred("integration-key", "DOCUSIGN_INTEGRATION_KEY")
        if a.consent_url:
            print(consent_url(ik))
            return 0
        uid = _cred("user-id", "DOCUSIGN_USER_ID")
        acct_voluto = os.environ.get("DOCUSIGN_ACCOUNT_ID") or get_secret(SERVICE, "account-id")

        tok = access_token(ik, uid)
        info = userinfo(tok)
        account_id, base_uri = account_di(info, acct_voluto)
        log.info(
            "authenticated: %s · account %s… · %s", info.get("email", "?"), account_id[:8], base_uri
        )

        da = f"{a.since}T00:00:00Z" if a.since else DAL_PRINCIPIO
        if a.dry_run:
            intest = {"Authorization": f"Bearer {tok}"}
            r = requests.get(
                f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes",
                headers=intest,
                params={"from_date": da, "count": 1},
                timeout=60,
            )
            r.raise_for_status()
            log.info(
                "--dry-run: envelopes since %s = %s (nothing written)",
                da[:10],
                r.json().get("totalSetSize"),
            )
            return 0

        buste = elenca_buste(tok, base_uri, account_id, da)
        esito = scrivi(buste)
        for k, v in esito.items():
            log.info("  %-18s %s", k, v)
        log.info("  written to %s and %s", OUT_DIR, METADATA_FILE)
        mark_last_run("docusign")
        return 0
    except RuntimeError as err:
        log.error("⛔ %s", err)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
