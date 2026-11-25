#!/usr/bin/env python3
""






















from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_REPO_DIR = _TOOLS_DIR.parent
if str(_REPO_DIR) not in sys.path:
    sys.path.insert(0, str(_REPO_DIR))

from tools.plaud.pl_exec_http import ENVELOPE_CONSTANTS, make_request_id
from tools.plaud.pl_wt_auth import (
    TokenKind,
    decode_jwt_header,
    decode_jwt_payload,
    select_token,
    strip_bearer_prefix,
)

ENCRYPTION_JSON = Path.home() / "Library" / "Application Support" / "Plaud" / "encryption.json"
KEYCHAIN_SERVICE = "Plaud Safe Storage"
KEYCHAIN_ACCOUNT = "Plaud Key"
WT_OUT = Path.home() / ".sbk-data" / "secrets" / "plaud-wt.json"
REFRESH_PATH = "/user-app/auth/workspace/refresh/{ws}"


class AuthError(RuntimeError):
    pass





def _keychain_password() -> str:
    ""

    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as e:
        raise AuthError("Keychain in attesa di autorizzazione interattiva (prompt?)") from e
    if out.returncode != 0 or not out.stdout.strip():
        raise AuthError(f"Keychain: voce non leggibile (rc={out.returncode})")
    return out.stdout.strip()


def load_store_py() -> dict:
    ""

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not ENCRYPTION_JSON.exists():
        raise AuthError(f"store assente: {ENCRYPTION_JSON}")
    key = hashlib.pbkdf2_hmac("sha1", _keychain_password().encode(), b"saltysalt", 1003, dklen=16)
    iv = b" " * 16
    enc = json.loads(ENCRYPTION_JSON.read_text())
    store: dict = {}
    for k, v in enc.items():
        if not isinstance(v, str):
            store[k] = v
            continue
        try:
            raw = base64.b64decode(v + "=" * (-len(v) % 4))
        except Exception:
            continue
        if not raw.startswith(b"v10"):
            continue
        try:
            c = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            pt = c.update(raw[3:]) + c.finalize()
            pad = pt[-1]
            if 1 <= pad <= 16:
                pt = pt[:-pad]
            text = pt.decode("utf-8")
        except Exception:
            continue

        if text[:1] in "[{":
            try:
                store[k] = json.loads(text)
                continue
            except json.JSONDecodeError:
                pass
        store[k] = text
    if not store:
        raise AuthError("store decifrato vuoto: chiave Keychain sbagliata?")
    return store





def build_context(store: dict) -> dict:
    api_domain = store.get("apiDomain")
    ws_list = store.get("workspaceList") or []
    ws_id = None
    if isinstance(ws_list, list) and ws_list and isinstance(ws_list[0], dict):
        ws_id = ws_list[0].get("workspace_id")
        api_domain = api_domain or ws_list[0].get("api_domain")
    device_uuid = None
    sysinfo = store.get("systemInfo")
    if isinstance(sysinfo, dict):
        device_uuid = sysinfo.get("uuid")
    return {
        "api_domain": api_domain,
        "ws_id": ws_id,
        "device_uuid": device_uuid,
        "wt": select_token(store, TokenKind.WT),
        "wrt": select_token(store, TokenKind.WRT),
        "ut": select_token(store, TokenKind.UT),
        "urt": select_token(store, TokenKind.URT),
    }


def _exp_info(token: str | None) -> str:
    if not token:
        return "assente"
    hdr = decode_jwt_header(token)
    pl = decode_jwt_payload(token)
    exp = pl.get("exp")
    if not exp:
        return f"typ={hdr.get('typ')} senza exp"
    d = datetime.fromtimestamp(exp, tz=UTC)
    stato = "VALIDO" if d > datetime.now(tz=UTC) else "SCADUTO"
    return f"typ={hdr.get('typ')} exp={d:%Y-%m-%d %H:%M}UTC {stato}"












def _call(ctx: dict, method: str, path: str, token: str, bearer: str = "Bearer"):
    ""
    import requests

    url = ctx["api_domain"].rstrip("/") + path
    headers = {
        **ENVELOPE_CONSTANTS,
        "Authorization": f"{bearer} {strip_bearer_prefix(token)}",
        "X-Device-Id": ctx["device_uuid"],
        "X-Request-Id": make_request_id(),
    }
    resp = requests.request(method, url, headers=headers, timeout=30)
    found: dict[str, str] = {}
    try:
        body = resp.json()
    except ValueError:
        body = {}

    def _walk(node):
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
        elif isinstance(node, str) and node.count(".") == 2 and len(node) > 60:
            typ = str(decode_jwt_header(node).get("typ", "")).upper()
            if typ in ("WT", "WRT", "UT", "URT"):
                found[typ] = node

    _walk(body)
    return resp, found


def _saved_tokens() -> dict:
    if WT_OUT.exists():
        try:
            return json.loads(WT_OUT.read_text())
        except Exception:
            return {}
    return {}


def _piu_fresco(salvato: str | None, store: str | None) -> str | None:
    ""






    def _exp(tok: str | None) -> float:
        try:
            return float(decode_jwt_payload(tok).get("exp") or 0) if tok else 0.0
        except Exception:  # noqa: BLE001 - token illeggibile: perde il confronto
            return 0.0

    if not salvato or not store:
        return salvato or store
    return store if _exp(store) > _exp(salvato) else salvato


def refresh_wt(ctx: dict, dry_run: bool = False) -> dict:
    ""


    for need in ("api_domain", "ws_id", "device_uuid"):
        if not ctx.get(need):
            raise AuthError(f"contesto incompleto: manca {need}")
    saved = _saved_tokens()
    wrt = _piu_fresco(saved.get("wrt"), ctx.get("wrt"))
    urt = _piu_fresco(saved.get("urt"), ctx.get("urt"))
    if dry_run:
        return {
            "dry_run": True,
            "url": ctx["api_domain"].rstrip("/") + REFRESH_PATH.format(ws=ctx["ws_id"]),
            "headers": sorted(
                [*ENVELOPE_CONSTANTS, "Authorization", "X-Device-Id", "X-Request-Id"]
            ),
        }

    tried = []

    if wrt:
        resp, found = _call(ctx, "POST", REFRESH_PATH.format(ws=ctx["ws_id"]), wrt)
        tried.append(f"-419:http={resp.status_code}:jwt={sorted(found)}")
        if resp.status_code == 200 and "WT" in found:
            return {"found": found, "via": "-419", "tried": tried}




    ut = _piu_fresco(saved.get("ut"), ctx.get("ut"))
    if ut:
        exp = decode_jwt_payload(ut).get("exp") or 0
        if exp > datetime.now(tz=UTC).timestamp():
            resp, found = _call(
                ctx, "POST", f"/user-app/auth/workspace/token/{ctx['ws_id']}", ut, bearer="bearer"
            )
            tried.append(f"UT->WT:http={resp.status_code}:jwt={sorted(found)}")
            if resp.status_code == 200 and "WT" in found:
                return {"found": found, "via": "UT->WT", "tried": tried}

    if not urt:
        raise AuthError(f"nessun URT disponibile per il re-exchange (tentativi: {tried})")
    resp1, f1 = _call(ctx, "POST", "/auth/refresh-user-token", urt)
    tried.append(f"URT->UT:http={resp1.status_code}:jwt={sorted(f1)}")
    if "UT" not in f1:
        raise AuthError(f"refresh UT fallito (tentativi: {tried}) — serve il tuo login dall'app desktop di Plaud")
    resp2, f2 = _call(
        ctx, "POST", f"/user-app/auth/workspace/token/{ctx['ws_id']}", f1["UT"], bearer="bearer"
    )
    tried.append(f"UT->WT:http={resp2.status_code}:jwt={sorted(f2)}")
    found = {**f1, **f2}
    if "WT" not in found:
        raise AuthError(f"exchange WT fallito (tentativi: {tried}) — serve il tuo login dall'app desktop di Plaud")
    return {"found": found, "via": "URT->UT->WT", "tried": tried}


def save_wt(found: dict[str, str]) -> Path:
    ""
    WT_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = _saved_tokens()
    payload["saved_at"] = datetime.now(tz=UTC).isoformat()
    for typ, tok in found.items():
        payload[typ.lower()] = tok
    exp = decode_jwt_payload(found["WT"]).get("exp") if "WT" in found else None
    if exp:
        payload["wt_exp"] = exp
    tmp = WT_OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    os.chmod(tmp, 0o600)
    tmp.rename(WT_OUT)
    os.chmod(WT_OUT, 0o600)
    return WT_OUT


def load_saved_wt() -> str | None:
    ""

    if WT_OUT.exists():
        try:
            d = json.loads(WT_OUT.read_text())
            exp = d.get("wt_exp")
            if exp and datetime.fromtimestamp(exp, tz=UTC) > datetime.now(tz=UTC):
                return d["wt"]
        except Exception:
            pass
    try:
        store = load_store_py()
        wt = select_token(store, TokenKind.WT)
        if wt and (decode_jwt_payload(wt).get("exp") or 0) > datetime.now(tz=UTC).timestamp():
            return wt
    except AuthError:
        pass
    return None





def main() -> int:
    ap = argparse.ArgumentParser(description="Plaud auth headless: status/refresh WT")
    ap.add_argument("--status", action="store_true", help="typ/exp dei token (mai i valori)")
    ap.add_argument("--refresh", action="store_true", help="rinnova il WT via WRT (-419)")
    ap.add_argument(
        "--dry-run", action="store_true", help="con --refresh: mostra URL e header, zero rete"
    )
    args = ap.parse_args()

    store = load_store_py()
    ctx = build_context(store)

    if args.status or not args.refresh:
        print(f"api_domain: {ctx['api_domain']}  ws: {ctx['ws_id']}")
        for kind in ("ut", "urt", "wt", "wrt"):
            print(f"  {kind.upper()}: {_exp_info(ctx[kind])}")
        saved = None
        if WT_OUT.exists():
            try:
                saved = json.loads(WT_OUT.read_text())
            except Exception:
                saved = None
        if saved and saved.get("wt"):
            print(f"  WT salvato: {_exp_info(saved['wt'])} ({WT_OUT})")
        return 0

    result = refresh_wt(ctx, dry_run=args.dry_run)
    if args.dry_run:
        print(f"DRY-RUN: POST {result['url']}")
        print(f"  headers: {result['headers']}")
        return 0
    path = save_wt(result["found"])
    print(f"refresh OK via {result['via']} (tentativi: {result['tried']})")
    print(f"  nuovi token: {sorted(result['found'])}")
    print(f"  WT: {_exp_info(result['found']['WT'])}")
    print(f"  salvato in {path} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
