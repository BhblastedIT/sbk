#!/usr/bin/env python3
""




















from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
load_dotenv(REPO / ".env", override=True)

import google_oauth  # noqa: E402

import sbk_config as cfg  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ga-l0")

DEST = cfg.DATA_ROOT / "analytics"
# Labels of the Google accounts signed in for Analytics (--login <label>);
# each refresh token is in the Keychain as sbk-ga/<label>.
ACCOUNTS_FILE = DEST / "accounts.json"
KEYCHAIN = "sbk-ga"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

METRICHE = ("sessions", "totalUsers", "newUsers", "screenPageViews", "userEngagementDuration")


def _etichette() -> list[str]:
    try:
        return list(json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return []


def login(etichetta: str) -> None:
    """Browser login of one Google account that sees your GA4 properties."""
    creds = google_oauth.browser_login(KEYCHAIN, etichetta, SCOPES)
    n = len(property_disponibili(creds))
    conti = {e: {} for e in _etichette()}
    conti[etichetta] = {"property": n}
    DEST.mkdir(parents=True, exist_ok=True)
    cfg.safe_write_json(ACCOUNTS_FILE, conti)
    log.info("'%s' signed in: %s properties visible", etichetta, n)


def _credenziali(etichetta: str):
    return google_oauth.credentials(KEYCHAIN, etichetta, SCOPES)


def property_disponibili(creds) -> list[dict]:
    from googleapiclient.discovery import build

    admin = build("analyticsadmin", "v1beta", credentials=creds, cache_discovery=False)
    fuori = []
    for a in admin.accounts().list().execute().get("accounts", []):
        for p in (
            admin.properties().list(filter=f"parent:{a['name']}").execute().get("properties", [])
        ):
            fuori.append(
                {
                    "account": a.get("displayName", ""),
                    "property": p.get("displayName", ""),
                    "id": p.get("name", ""),
                    "creata": str(p.get("createTime", ""))[:10],
                }
            )
    return fuori


def _rapporto(dati, pid: str, inizio: str, fine: str, dimensioni: list[str], righe: int = 50):
    corpo = {
        "dateRanges": [{"startDate": inizio, "endDate": fine}],
        "metrics": [{"name": m} for m in METRICHE],
        "limit": righe,
    }
    if dimensioni:
        corpo["dimensions"] = [{"name": d} for d in dimensioni]
    return dati.properties().runReport(property=pid, body=corpo).execute()


def _righe(r) -> list[dict]:
    intest = [h["name"] for h in r.get("dimensionHeaders", [])]
    metr = [h["name"] for h in r.get("metricHeaders", [])]
    fuori = []
    for riga in r.get("rows", []):
        v = {}
        for i, d in enumerate(riga.get("dimensionValues", [])):
            v[intest[i] if i < len(intest) else f"dim{i}"] = d.get("value")
        for i, m in enumerate(riga.get("metricValues", [])):
            chiave = metr[i] if i < len(metr) else f"met{i}"
            grezzo = m.get("value") or "0"
            try:
                v[chiave] = int(float(grezzo))
            except ValueError:
                v[chiave] = grezzo
        fuori.append(v)
    return fuori


def raccogli(etichette: list[str], giorni: int = 28) -> dict:
    from googleapiclient.discovery import build

    DEST.mkdir(parents=True, exist_ok=True)
    # A property seen by more than one of your accounts is read once, with the first.
    props: list[dict] = []
    client: dict[str, object] = {}
    for etichetta in etichette:
        creds = _credenziali(etichetta)
        dati_conto = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
        for p in property_disponibili(creds):
            if p["id"] and p["id"] not in client:
                client[p["id"]] = dati_conto
                props.append({**p, "login": etichetta})

    fine = datetime.now(UTC).date() - timedelta(days=1)
    inizio = fine - timedelta(days=giorni)
    log.info("properties: %s · window %s → %s", len(props), inizio, fine)

    cfg.safe_write_json(
        DEST / "property.json",
        {"preso_il": datetime.now(UTC).isoformat(), "n": len(props), "property": props},
    )

    esito = {"property": len(props), "con_sessioni": 0, "non_lette": 0}
    for p in props:
        pid, nome = p["id"], p["property"]
        dati = client[pid]
        try:
            tot = _righe(_rapporto(dati, pid, str(inizio), str(fine), []))
            canali = _righe(
                _rapporto(dati, pid, str(inizio), str(fine), ["sessionDefaultChannelGroup"])
            )
            pagine = _righe(_rapporto(dati, pid, str(inizio), str(fine), ["pagePath"], righe=50))
        except Exception as e:  # noqa: BLE001
            esito["non_lette"] += 1
            log.warning("  %-24s not read (%s)", nome, str(e)[:90])
            continue
        sessioni = tot[0].get("sessions", 0) if tot else 0
        if sessioni:
            esito["con_sessioni"] += 1
        cfg.safe_write_json(
            DEST / "performance" / f"{nome.lower().replace(' ', '-')}.json",
            {
                "preso_il": datetime.now(UTC).isoformat(),
                "property": nome,
                "id": pid,
                "da": str(inizio),
                "a": str(fine),
                "totali": tot[0] if tot else {},
                "per_canale": canali,
                "pagine": pagine,
            },
        )
        log.info(
            "  %-24s sessions %-8s users %s",
            nome,
            f"{sessioni:,}",
            f"{tot[0].get('totalUsers', 0):,}" if tot else "0",
        )
        time.sleep(0.2)
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Google Analytics 4 — SBK: sessions, channels and pages of every GA4 property "
        "your Google accounts can see (your own login, scope analytics.readonly)"
    )
    ap.add_argument(
        "--days", type=int, default=28, dest="giorni", metavar="N", help="days in the window (default 28)"
    )
    # Older Italian name, kept as a hidden alias.
    ap.add_argument("--giorni", type=int, dest="giorni", help=argparse.SUPPRESS)
    ap.add_argument(
        "--login",
        metavar="LABEL",
        help="sign a Google account in (browser, once per account), e.g. --login main",
    )
    ap.add_argument("--account", metavar="LABEL", help="read one signed-in account only")
    a = ap.parse_args()
    if a.login:
        login(a.login)
        return 0
    etichette = [a.account] if a.account else _etichette()
    if not etichette:
        log.error(
            "No Google account signed in for Analytics. Run once: "
            "uv run python tools/analytics/ga-l0-inventory.py --login main "
            "(docs/CONNECTING.md#analytics). Nothing done."
        )
        return 2
    try:
        e = raccogli(etichette, giorni=a.giorni)
    except google_oauth.NoLogin as err:
        log.error("%s. Run: uv run python tools/analytics/ga-l0-inventory.py --login <label>", err)
        return 2
    except Exception as err:  # noqa: BLE001
        log.error("⛔ %s: %s", type(err).__name__, str(err)[:220])
        log.error(
            "   Check that the Google Analytics Admin API and Data API are enabled in your "
            "Google Cloud project (docs/CONNECTING.md#analytics)."
        )
        return 1
    log.info("")
    for k, v in e.items():
        log.info("  %-14s %s", k, v)
    log.info("  written to %s", DEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
