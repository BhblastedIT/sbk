#!/usr/bin/env python3
"""Google Search Console download: properties, clicks, impressions, queries and pages of every property your
signed-in Google accounts can see (your own login, read-only scope), into <data root>/gsc/.

Usage: uv run python tools/gsc/gs-l0-inventory.py --login <label>   (once per account), then without it
"""

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
log = logging.getLogger("gs-l0")

DEST = cfg.DATA_ROOT / "gsc"
# Labels of the Google accounts signed in for Search Console (--login <label>);
# each refresh token is in the Keychain as sbk-gsc/<label>.
ACCOUNTS_FILE = DEST / "accounts.json"
KEYCHAIN = "sbk-gsc"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]



RITARDO_GIORNI = 3


def _etichette() -> list[str]:
    try:
        return list(json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return []


def login(etichetta: str) -> None:
    """Browser login of one Google account that sees your Search Console properties."""
    from googleapiclient.discovery import build

    creds = google_oauth.browser_login(KEYCHAIN, etichetta, SCOPES)
    s = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    n = len(s.sites().list().execute().get("siteEntry", []))
    conti = {e: {} for e in _etichette()}
    conti[etichetta] = {"property": n}
    DEST.mkdir(parents=True, exist_ok=True)
    cfg.safe_write_json(ACCOUNTS_FILE, conti)
    log.info("'%s' signed in: %s properties visible", etichetta, n)


def _servizio(etichetta: str):
    from googleapiclient.discovery import build

    creds = google_oauth.credentials(KEYCHAIN, etichetta, SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _nome_file(property_url: str) -> str:
    return (
        property_url.replace("sc-domain:", "dominio-")
        .replace("https://", "")
        .replace("http://", "")
        .strip("/")
        .replace("/", "_")
    )


def _finestra(giorni: int) -> tuple[str, str]:
    fine = datetime.now(UTC).date() - timedelta(days=RITARDO_GIORNI)
    return (fine - timedelta(days=giorni)).isoformat(), fine.isoformat()


def _interroga(s, sito: str, inizio: str, fine: str, dimensioni: list[str], righe: int = 200):
    corpo = {
        "startDate": inizio,
        "endDate": fine,
        "rowLimit": righe,
    }
    if dimensioni:
        corpo["dimensions"] = dimensioni
    return s.searchanalytics().query(siteUrl=sito, body=corpo).execute().get("rows", [])


def raccogli(etichette: list[str], giorni: int = 28, solo_elenco: bool = False) -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    # A property seen by more than one of your accounts is read once, with the first.
    servizi: dict[str, object] = {}
    elenco = []
    for etichetta in etichette:
        s_conto = _servizio(etichetta)
        for x in s_conto.sites().list().execute().get("siteEntry", []):
            url = x.get("siteUrl", "")
            if url and url not in servizi:
                servizi[url] = s_conto
                elenco.append(
                    {"property": url, "permesso": x.get("permissionLevel", ""), "account": etichetta}
                )
    inizio, fine = _finestra(giorni)
    log.info("properties: %s · window %s → %s", len(elenco), inizio, fine)

    cfg.safe_write_json(
        DEST / "property.json",
        {"preso_il": datetime.now(UTC).isoformat(), "n": len(elenco), "property": elenco},
    )
    if solo_elenco:
        return {"property": len(elenco)}

    esito = {"property": len(elenco), "con_traffico": 0, "a_zero": 0, "non_lette": 0}
    for v in elenco:
        sito = v["property"]
        s = servizi[sito]
        try:
            tot = _interroga(s, sito, inizio, fine, [], righe=1)
            query = _interroga(s, sito, inizio, fine, ["query"], righe=100)
            pagine = _interroga(s, sito, inizio, fine, ["page"], righe=100)
        except Exception as e:  # noqa: BLE001
            esito["non_lette"] += 1
            log.warning("  %-44s not read (%s)", sito, str(e)[:90])
            continue
        clic = int(tot[0].get("clicks", 0)) if tot else 0
        imp = int(tot[0].get("impressions", 0)) if tot else 0
        if clic or imp:
            esito["con_traffico"] += 1
        else:
            esito["a_zero"] += 1
        cfg.safe_write_json(
            DEST / "performance" / f"{_nome_file(sito)}.json",
            {
                "preso_il": datetime.now(UTC).isoformat(),
                "property": sito,
                "da": inizio,
                "a": fine,
                "clic": clic,
                "impressioni": imp,
                "posizione_media": round(float(tot[0].get("position", 0)), 2) if tot else None,
                "query": [
                    {
                        "testo": r["keys"][0],
                        "clic": int(r.get("clicks", 0)),
                        "impressioni": int(r.get("impressions", 0)),
                        "posizione": round(float(r.get("position", 0)), 1),
                    }
                    for r in query
                    if r.get("keys")
                ],
                "pagine": [
                    {
                        "url": r["keys"][0],
                        "clic": int(r.get("clicks", 0)),
                        "impressioni": int(r.get("impressions", 0)),
                    }
                    for r in pagine
                    if r.get("keys")
                ],
            },
        )
        log.info("  %-44s clicks %-7s impressions %s", sito, f"{clic:,}", f"{imp:,}")
        time.sleep(0.2)
    return esito


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Google Search Console — SBK: properties, clicks, queries and pages of every "
        "property your Google accounts can see (your own login, scope webmasters.readonly)"
    )
    ap.add_argument(
        "--days", type=int, default=28, dest="giorni", metavar="N", help="days in the window (default 28)"
    )
    ap.add_argument(
        "--list-only", action="store_true", dest="solo_elenco", help="list the properties only"
    )
    # Older Italian names, kept as hidden aliases.
    ap.add_argument("--giorni", type=int, dest="giorni", help=argparse.SUPPRESS)
    ap.add_argument("--solo-elenco", action="store_true", dest="solo_elenco", help=argparse.SUPPRESS)
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
            "No Google account signed in for Search Console. Run once: "
            "uv run python tools/gsc/gs-l0-inventory.py --login main (docs/CONNECTING.md#gsc). "
            "Nothing done."
        )
        return 2
    try:
        e = raccogli(etichette, giorni=a.giorni, solo_elenco=a.solo_elenco)
    except google_oauth.NoLogin as err:
        log.error("%s. Run: uv run python tools/gsc/gs-l0-inventory.py --login <label>", err)
        return 2
    except Exception as err:  # noqa: BLE001
        log.error("⛔ %s: %s", type(err).__name__, str(err)[:220])
        log.error(
            "   Check that the Search Console API is enabled in your Google Cloud project "
            "and that the account sees the properties (docs/CONNECTING.md#gsc)."
        )
        return 1
    log.info("")
    for k, v in e.items():
        log.info("  %-14s %s", k, v)
    log.info("  written to %s", DEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
