#!/usr/bin/env python3
"""Download envelope PDFs from DocuSign (L0)."""












from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from sbk_config import DOCUSIGN_RAW_DIR, mark_last_run, safe_write_parquet  # noqa: E402

log = logging.getLogger("ds-l0-pdf")

PDF_DIR = DOCUSIGN_RAW_DIR / "pdf"
INDICE = PDF_DIR / "indice.parquet"
BUSTE = DOCUSIGN_RAW_DIR / "raw" / "envelopes-api.json"

STATI = frozenset({"completed", "sent", "delivered", "declined"})

CHIUSI = frozenset({"scaricato", "sparito"})

PAUSA_S = 1.0
SALVA_OGNI = 50

RINNOVA_S = 40 * 60


def _api():
    nome = "ds_l0_api_pdf"
    spec = importlib.util.spec_from_file_location(nome, _TOOLS / "docusign" / "ds-l0-api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


def leggi_indice(percorso: Path = INDICE) -> pd.DataFrame:
    return pd.read_parquet(percorso) if percorso.exists() else pd.DataFrame()


def da_scaricare(buste: list[dict], indice: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    ""

    chiusi: dict[str, str] = {}
    if not indice.empty:
        for r in indice.loc[indice["stato"].isin(CHIUSI)].itertuples(index=False):
            chiusi[r.envelopeId] = str(getattr(r, "cambiata", "") or "")
    fare, subito = [], []
    for b in buste:
        eid = b.get("envelopeId")
        if not eid or b.get("status") not in STATI:
            continue
        if eid in chiusi and chiusi[eid] == str(b.get("statusChangedDateTime") or ""):
            continue
        if str(b.get("purgeState", "")).startswith("documents_"):
            subito.append(riga(b, "sparito", motivo=f"DocuSign: {b.get('purgeState')}"))
            continue
        fare.append(b)
    return fare, subito


def riga(b: dict, stato: str, *, percorso: str = "", byte: int = 0, motivo: str = "") -> dict:
    return {
        "envelopeId": b.get("envelopeId"),
        "status": b.get("status"),
        "oggetto": b.get("emailSubject") or "",
        "inviata": b.get("sentDateTime") or b.get("createdDateTime") or "",
        "cambiata": b.get("statusChangedDateTime") or "",
        "percorso": percorso,
        "byte": byte,
        "stato": stato,
        "motivo": motivo,
        "quando": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def scarica(
    b: dict,
    sessione,
    base_uri: str,
    account_id: str,
    dest_dir: Path = PDF_DIR,
    gia_sul_disco: bool = False,
) -> dict:
    ""

    eid = b["envelopeId"]
    url = f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes/{eid}/documents/combined"
    dest = dest_dir / f"{eid}.pdf"
    if (
        gia_sul_disco
        and dest.exists()
        and dest.stat().st_size > 0
        and dest.read_bytes()[:4] == b"%PDF"
    ):
        return riga(
            b, "scaricato", percorso=str(dest), byte=dest.stat().st_size, motivo="already on disk"
        )
    import requests

    for tentativo in range(4):
        try:
            r = sessione.get(url, params={"certificate": "false"}, timeout=120)
        except requests.exceptions.RequestException as e:

            log.warning("  %s: network (%s), retrying", eid[:8], type(e).__name__)
            time.sleep(10 * (tentativo + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            attesa = int(r.headers.get("Retry-After", 0) or 0) or 10 * (tentativo + 1)
            log.warning("  %s: HTTP %s, waiting %ss", eid[:8], r.status_code, attesa)
            time.sleep(attesa)
            continue
        if r.status_code in (400, 404):
            return riga(b, "sparito", motivo=f"HTTP {r.status_code}: {r.text[:120]}")
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            return riga(b, "errore", motivo=f"HTTP {r.status_code}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".parziale")
        tmp.write_bytes(r.content)
        os.replace(tmp, dest)
        os.chmod(dest, 0o600)
        return riga(b, "scaricato", percorso=str(dest), byte=len(r.content))
    return riga(b, "errore", motivo="retries exhausted (DocuSign or the network did not respond)")


def salva(righe: list[dict], percorso: Path = INDICE) -> None:
    vecchio = leggi_indice(percorso)
    nuovo = pd.DataFrame(righe)
    tutto = pd.concat([vecchio, nuovo], ignore_index=True) if not vecchio.empty else nuovo
    tutto = tutto.drop_duplicates(subset=["envelopeId"], keep="last")
    safe_write_parquet(tutto, percorso, index=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="how many are missing, nothing downloaded")
    ap.add_argument("--max", type=int, default=0, help="at most this many envelopes (trial)")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    if not BUSTE.exists():
        log.error("⛔ missing %s: download the envelopes first (ds-l0-api.py)", BUSTE)
        return 1
    buste = json.loads(BUSTE.read_text(encoding="utf-8")).get("envelopes") or []
    indice = leggi_indice()
    noti = set(indice["envelopeId"]) if not indice.empty else set()
    fare, subito = da_scaricare(buste, indice)
    log.info(
        "envelopes %d, to download %d, documents deleted by DocuSign %d",
        len(buste),
        len(fare),
        len(subito),
    )
    if args.dry_run:
        return 0
    if args.max:
        fare = fare[: args.max]
    if subito:
        salva(subito)
    if not fare:
        mark_last_run("docusign-pdf")
        return 0

    import requests

    api = _api()
    try:
        ik = api._cred("integration-key", "DOCUSIGN_INTEGRATION_KEY")
        uid = api._cred("user-id", "DOCUSIGN_USER_ID")
        voluto = os.environ.get("DOCUSIGN_ACCOUNT_ID") or api.get_secret(api.SERVICE, "account-id")
        token = api.access_token(ik, uid)
        account_id, base_uri = api.account_di(api.userinfo(token), voluto)
    except RuntimeError as err:
        log.error("⛔ %s", err)
        return 1
    sessione = requests.Session()
    sessione.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/pdf"})
    preso = time.monotonic()
    righe, errori = [], 0
    try:
        for i, b in enumerate(fare, 1):
            if time.monotonic() - preso > RINNOVA_S:
                sessione.headers["Authorization"] = f"Bearer {api.access_token(ik, uid)}"
                preso = time.monotonic()
            r = scarica(
                b, sessione, base_uri, account_id, gia_sul_disco=b["envelopeId"] not in noti
            )
            errori += r["stato"] == "errore"
            righe.append(r)
            if len(righe) >= SALVA_OGNI:
                salva(righe)
                righe = []
                log.info("  %d/%d", i, len(fare))
            time.sleep(PAUSA_S)
    finally:

        if righe:
            salva(righe)
    tutto = leggi_indice()
    log.info("index: %s", tutto["stato"].value_counts().to_dict())
    mark_last_run("docusign-pdf")
    return 1 if errori > 0.05 * len(fare) else 0


if __name__ == "__main__":
    sys.exit(main())
