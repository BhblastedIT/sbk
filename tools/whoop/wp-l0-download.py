#!/usr/bin/env python3
""











import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

load_dotenv(_TOOLS_DIR.parent / ".env", override=True)

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import WHOOP_RAW_DIR, mark_last_run  # noqa: E402

log = logging.getLogger("whoop-dl")

WHOOP_API_BASE = "https://api.prod.whoop.com/developer"
RATE_LIMIT_PER_MIN = 100
MIN_REQUEST_INTERVAL = 60.0 / RATE_LIMIT_PER_MIN
SERVICE = "sbk-whoop"

ENDPOINTS = ["recovery", "sleep", "cycle", "workout"]

ENDPOINT_PATHS = {
    "recovery": "v2/recovery",
    "sleep": "v2/activity/sleep",
    "cycle": "v2/cycle",
    "workout": "v2/activity/workout",
}


_last_request_time = 0.0


def _rate_limit():
    ""
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _get_token() -> str:
    ""
    token = get_secret(SERVICE, "access-token")
    if not token:
        log.error("No WHOOP access token in Keychain. Run wp-l0-auth.py first.")
        sys.exit(1)
    return token


def _make_headers(token: str) -> dict:
    ""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def refresh_and_retry(endpoint: str, **kwargs) -> list[dict]:
    ""
    import importlib.util

    auth_path = Path(__file__).parent / "wp-l0-auth.py"
    spec = importlib.util.spec_from_file_location("wp_l0_auth", auth_path)
    auth_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth_mod)

    new_token = auth_mod.refresh_access_token()
    log.info("Token refreshed, retrying...")
    return fetch_endpoint(endpoint, _token=new_token, **kwargs)


def fetch_endpoint(
    endpoint: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
    _token: str | None = None,
) -> list[dict]:
    ""











    token = _token or _get_token()
    headers = _make_headers(token)


    params = {}
    if days:
        start = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
        params["start"] = start
    elif start_date:
        params["start"] = f"{start_date}T00:00:00.000Z" if "T" not in start_date else start_date
    if end_date:
        params["end"] = f"{end_date}T23:59:59.999Z" if "T" not in end_date else end_date

    params["limit"] = 25

    all_records = []
    path = ENDPOINT_PATHS.get(endpoint, f"v2/{endpoint}")
    url = f"{WHOOP_API_BASE}/{path}"
    page = 0

    while True:
        _rate_limit()
        page += 1

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:

            raise RuntimeError(f"whoop {endpoint}: request failed ({e})") from e

        if resp.status_code == 401:

            log.warning("401 on %s, refreshing token...", endpoint)
            return refresh_and_retry(endpoint, start_date=start_date, end_date=end_date, days=days)

        if resp.status_code != 200:
            log.error("API error %d on %s: %s", resp.status_code, endpoint, resp.text[:200])
            raise RuntimeError(f"whoop {endpoint}: HTTP {resp.status_code}")

        data = resp.json()
        records = data.get("records", [])
        all_records.extend(records)

        next_token = data.get("next_token")
        if not next_token:
            break


        params["nextToken"] = next_token
        log.info(
            "  %s page %d: +%d records (total: %d)", endpoint, page, len(records), len(all_records)
        )

    log.info("  %s: %d records total", endpoint, len(all_records))
    return all_records



_RECORD_KEY = {
    "cycle": ("id",),
    "sleep": ("id",),
    "workout": ("id",),
    "recovery": ("cycle_id", "sleep_id"),
}


def _chiave(endpoint: str, r: dict) -> tuple:
    return tuple(str(r.get(k, "")) for k in _RECORD_KEY.get(endpoint, ("id",)))


def save_raw(records: list[dict], output_path: Path, endpoint: str = "") -> int:
    ""






    output_path.parent.mkdir(parents=True, exist_ok=True)
    esistenti: dict[tuple, dict] = {}
    if output_path.exists():
        try:
            for r in json.loads(output_path.read_text()):
                esistenti[_chiave(endpoint, r)] = r
        except (OSError, ValueError) as e:
            log.warning("  %s unreadable (%s): restarting from new records only", output_path.name, e)
    prima = len(esistenti)
    for r in records:
        esistenti[_chiave(endpoint, r)] = r
    tutti = list(esistenti.values())
    output_path.write_text(json.dumps(tutti, indent=2, default=str))
    log.info(
        "  Saved %d records to %s (%d new/updated, %d total)",
        len(records),
        output_path.name,
        len(tutti) - prima,
        len(tutti),
    )
    return len(tutti)


def download_all(
    days: int | None = None,
    full: bool = False,
    output_dir: Path | None = None,
) -> dict[str, int]:
    ""









    out = output_dir or WHOOP_RAW_DIR
    out.mkdir(parents=True, exist_ok=True)

    if full:
        log.info("Downloading FULL WHOOP history...")
        dl_days = None
        start = None
    elif days:
        dl_days = days
        start = None
        log.info("Downloading last %d days of WHOOP data...", days)
    else:
        dl_days = 7
        start = None
        log.info("Downloading last 7 days of WHOOP data...")

    counts = {}
    falliti: list[str] = []
    file_map = {
        "recovery": "recovery.json",
        "sleep": "sleep.json",
        "cycle": "cycles.json",
        "workout": "workouts.json",
    }
    for ep in ENDPOINTS:
        try:
            records = fetch_endpoint(ep, days=dl_days, start_date=start)
            save_raw(records, out / file_map[ep], endpoint=ep)
            counts[ep] = len(records)
        except Exception as e:  # noqa: BLE001 — log, continue, exit non-zero at the end
            log.error("Failed to download %s: %s", ep, e)
            counts[ep] = 0
            falliti.append(ep)


    if falliti:
        log.error("whoop: failed endpoints %s — run NOT complete, exit 1", ", ".join(falliti))
        sys.exit(1)
    mark_last_run("whoop")
    return counts


def main():
    parser = argparse.ArgumentParser(description="WHOOP data downloader — SBK")
    parser.add_argument("--full", action="store_true", help="Download full history")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--workers", type=int, default=5, help="Parallelism (default: 5)")
    parser.add_argument("--output", type=str, help="Override output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    output = Path(args.output) if args.output else None
    counts = download_all(
        days=args.days if not args.full else None,
        full=args.full,
        output_dir=output,
    )

    total = sum(counts.values())
    print(f"\nWHOOP download complete: {total} records")
    for ep, n in counts.items():
        print(f"  {ep}: {n}")


if __name__ == "__main__":
    main()
