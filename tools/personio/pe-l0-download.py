#!/usr/bin/env python3
""







































from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv



_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_PROJECT_ROOT = _TOOLS_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from secrets_adapter import get_secret  # noqa: E402

from sbk_config import (  # noqa: E402
    PERSONIO_DIR,
    compute_record_hash,
    get_last_run,
    load_record_hashes,
    mark_last_run,
    save_record_hashes,
)

BASE_URL = "https://api.personio.de/v1"


BASE_V2 = "https://api.personio.de"
PAGE_SIZE = 200
MAX_RETRIES = 3
RETRY_BACKOFF = 2





PAUSA_PER_PERSONA_V1 = 0.25
PAUSA_PER_PERSONA_V2 = 0.05








MESI_COMPENSATIONS = 24





RECRUITING_SUBPATH = (
    "recruiting/candidates",
    "recruiting/applications",
    "recruiting/jobs",
    "recruiting/categories",
    "recruiting/job-postings",
    "recruiting/offers",
    "recruiting/stages",
    "recruiting/sources",
)

log = logging.getLogger("personio-dl")





def _get_credentials() -> tuple[str, str]:
    ""





    client_id = os.environ.get("PERSONIO_CLIENT_ID", "")
    client_secret = os.environ.get("PERSONIO_CLIENT_SECRET", "")

    if client_id and client_secret:
        log.debug("Using credentials from environment variables")
        return client_id, client_secret


    kc_id = get_secret("sbk-personio", "client-id")
    kc_secret = get_secret("sbk-personio", "client-secret")

    if kc_id and kc_secret:
        log.debug("Using credentials from macOS Keychain")
        return kc_id, kc_secret

    log.error(
        "No Personio credentials found. Set PERSONIO_CLIENT_ID + PERSONIO_CLIENT_SECRET "
        "in .env, or store in Keychain (service: sbk-personio, keys: client-id, client-secret)"
    )
    sys.exit(1)


def authenticate() -> str:
    ""





    client_id, client_secret = _get_credentials()

    log.info("Authenticating with Personio API...")
    resp = _request_with_retry(
        "POST",
        f"{BASE_URL}/auth",
        json={"client_id": client_id, "client_secret": client_secret},
        auth_token=None,
    )

    if not resp.get("success"):
        log.error(f"Authentication failed: {resp}")
        sys.exit(1)

    token = resp["data"]["token"]
    log.info("Authentication successful")
    return token





def _request_with_retry(
    method: str,
    url: str,
    *,
    auth_token: str | None = None,
    params: dict | None = None,
    json: dict | None = None,  # noqa: A002
) -> dict:
    ""





    headers = {"X-Personio-App-ID": "SBK"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=60,
            )

            if r.status_code == 429:
                wait = RETRY_BACKOFF * (2**attempt)
                log.warning(
                    f"Rate limited (429), waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(wait)
                continue

            if r.status_code == 401:
                log.error(f"Authentication error (401): {r.text[:500]}")
                sys.exit(1)

            r.raise_for_status()
            return r.json()

        except requests.exceptions.Timeout:
            wait = RETRY_BACKOFF * (2**attempt)
            log.warning(
                f"Request timeout, retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})"
            )
            time.sleep(wait)

        except requests.exceptions.ConnectionError as e:
            wait = RETRY_BACKOFF * (2**attempt)
            log.warning(
                f"Connection error: {e}, retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})"
            )
            time.sleep(wait)

        except requests.exceptions.HTTPError as e:


            corpo = e.response.text[:500] if e.response is not None else "N/A"
            log.error(f"HTTP error: {e} | Response: {corpo}")
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF * (2**attempt)
                time.sleep(wait)
            else:
                raise

    log.error(f"Request failed after {MAX_RETRIES} retries: {method} {url}")
    sys.exit(1)


def _paginate(
    url: str,
    token: str,
    *,
    extra_params: dict | None = None,
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    ""



    all_records = []
    offset = 0

    while True:
        params = {"limit": page_size, "offset": offset}
        if extra_params:
            params.update(extra_params)

        resp = _request_with_retry("GET", url, auth_token=token, params=params)
        data = resp.get("data", [])

        if not data:
            break

        all_records.extend(data)
        log.info(f"  Fetched {len(all_records)} records so far (offset={offset})")


        metadata = resp.get("metadata", {})
        total_pages = metadata.get("total_pages", 1)
        current_page = metadata.get("current_page", 0)


        total = resp.get("total")
        if total is not None and len(all_records) >= total:
            break




        if total_pages > 1 and current_page < total_pages - 1:
            offset += len(data)
        elif total_pages <= 1 and total is None and len(data) == page_size:

            offset += len(data)
        else:
            break

    return all_records


def _https(href: str) -> str:
    ""


    return "https://" + href[len("http://") :] if href.startswith("http://") else href


def _pagina_v2(percorso: str, token: str, *, params: dict | None = None) -> list[dict]:
    ""





    tutti: list[dict] = []
    url = f"{BASE_V2}{percorso}"
    visti: set[str] = set()

    while url:
        if url in visti:


            raise RuntimeError(f"v2 pagination loop on {percorso}: repeated cursor")
        visti.add(url)

        resp = _request_with_retry("GET", url, auth_token=token, params=params)
        params = None
        data = resp.get("_data") or []
        tutti.extend(data)
        if not data:
            break

        nxt = ((resp.get("_meta") or {}).get("links") or {}).get("next")
        href = nxt.get("href") if isinstance(nxt, dict) else nxt
        url = _https(href) if href else None

    return tutti


def _get_tollerante(
    url: str, token: str, *, params: dict | None = None, ammessi: tuple[int, ...] = (404,)
) -> tuple[int, dict | None]:
    ""




    headers = {"X-Personio-App-ID": "SBK", "Authorization": f"Bearer {token}"}
    for tentativo in range(MAX_RETRIES):
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code == 429:
            attesa = RETRY_BACKOFF * (2**tentativo)
            log.warning(f"Rate limited (429) on {url}, waiting {attesa}s")
            time.sleep(attesa)
            continue
        if r.status_code in ammessi:
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        r.raise_for_status()
        return r.status_code, r.json()
    log.error(f"Rate limit not cleared after {MAX_RETRIES} attempts: {url}")
    sys.exit(1)


def _motivo_errore(corpo: dict | None) -> str:
    ""
    if not isinstance(corpo, dict):
        return ""
    errori = corpo.get("errors") or []
    if not errori or not isinstance(errori[0], dict):
        return ""
    return str(errori[0].get("detail") or errori[0].get("details") or errori[0].get("title") or "")





def _resolve_nested_object(obj: dict) -> str | None:
    ""








    if not isinstance(obj, dict) or "type" not in obj:
        return None

    obj_type = obj.get("type", "")
    attrs = obj.get("attributes", {})

    if not attrs:
        return None




    if obj_type == "Employee":
        fn = attrs.get("first_name", {})
        ln = attrs.get("last_name", {})
        first = fn.get("value", "") if isinstance(fn, dict) else str(fn) if fn else ""
        last = ln.get("value", "") if isinstance(ln, dict) else str(ln) if ln else ""
        full = f"{first} {last}".strip()
        if full:
            return full

        pref = attrs.get("preferred_name", {})
        if isinstance(pref, dict) and pref.get("value"):
            return pref["value"]
        return None



    name = attrs.get("name")
    if name is not None:
        return str(name)

    return None


def flatten_employee(emp: dict) -> dict:
    ""












    attrs = emp.get("attributes", {})
    flat: dict = {}

    for key, attr_obj in attrs.items():
        if not isinstance(attr_obj, dict):
            flat[key] = attr_obj
            continue

        value = attr_obj.get("value")

        if value is None:
            flat[key] = None
            continue


        if isinstance(value, dict) and "type" in value:
            resolved = _resolve_nested_object(value)
            flat[key] = resolved if resolved is not None else str(value)
            continue


        if isinstance(value, dict):
            nested_attrs = value.get("attributes", {})
            if nested_attrs:
                name_attr = nested_attrs.get("name", {})
                if isinstance(name_attr, dict) and "value" in name_attr:
                    flat[key] = name_attr["value"]
                elif isinstance(name_attr, str):
                    flat[key] = name_attr
                else:
                    flat[key] = str(value)
            else:
                flat[key] = str(value)
            continue


        if isinstance(value, list):
            resolved = []
            for item in value:
                if isinstance(item, dict) and "type" in item:
                    r = _resolve_nested_object(item)
                    resolved.append(r)
                elif isinstance(item, dict):
                    item_attrs = item.get("attributes", {})
                    if item_attrs:
                        name_a = item_attrs.get("name")
                        if isinstance(name_a, dict) and "value" in name_a:
                            resolved.append(name_a["value"])
                        elif isinstance(name_a, str):
                            resolved.append(name_a)
                        else:
                            resolved.append(str(item))
                    else:
                        resolved.append(item)
                else:
                    resolved.append(item)
            flat[key] = resolved
            continue


        flat[key] = value

    return flat





def download_employees(token: str) -> tuple[list[dict], list[dict]]:
    ""



    log.info("Downloading employees...")
    t0 = time.time()

    raw_records = _paginate(f"{BASE_URL}/company/employees", token)

    elapsed = time.time() - t0
    log.info(f"Downloaded {len(raw_records)} employees in {elapsed:.1f}s")


    log.info("Flattening employee records...")
    flat_records = [flatten_employee(emp) for emp in raw_records]


    statuses = {}
    for emp in flat_records:
        s = emp.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    log.info(f"  Status distribution: {statuses}")

    return raw_records, flat_records


def save_employees(
    raw_records: list[dict], flat_records: list[dict], *, force: bool = False
) -> None:
    ""




    old_hashes = load_record_hashes("personio")
    new_hashes = {}
    for rec in flat_records:
        emp_id = str(rec.get("id", ""))
        if emp_id:
            new_hashes[emp_id] = compute_record_hash(rec)

    changed = 0
    if old_hashes:
        for emp_id, h in new_hashes.items():
            if old_hashes.get(emp_id) != h:
                changed += 1

        for emp_id in old_hashes:
            if emp_id not in new_hashes:
                changed += 1
    else:
        changed = len(new_hashes)

    if not force and old_hashes and changed == 0:
        log.info(f"  Employees: {len(flat_records)} downloaded, 0 changed, skipping write")
        return

    log.info(f"  Employees: {len(flat_records)} downloaded, {changed} changed, writing to disk")


    raw_path = PERSONIO_DIR / "employees-raw.json"
    raw_response = {
        "success": True,
        "data": raw_records,
        "metadata": {
            "total_elements": len(raw_records),
            "current_page": 0,
            "total_pages": 1,
        },
        "offset": 0,
        "limit": len(raw_records),
    }
    _scrivi_json_riservato(raw_path, raw_response)
    log.info(f"  Saved {len(raw_records)} employees (raw) -> {raw_path.name}")


    flat_path = PERSONIO_DIR / "employees-flat.json"
    _scrivi_json_riservato(flat_path, flat_records)
    log.info(f"  Saved {len(flat_records)} employees (flat) -> {flat_path.name}")


    save_record_hashes("personio", new_hashes)





def _scarica_per_pagina(token: str, endpoint: str, extra_params: dict) -> list[dict]:
    ""



    if not extra_params:
        resp = _request_with_retry("GET", f"{BASE_URL}/company/{endpoint}", auth_token=token)
        return list(resp.get("data", []))
    tutti: list[dict] = []
    pagina = 1
    while True:
        params = {"limit": PAGE_SIZE, "offset": pagina, **extra_params}
        resp = _request_with_retry(
            "GET", f"{BASE_URL}/company/{endpoint}", auth_token=token, params=params
        )
        data = resp.get("data", [])
        if not data:
            break
        tutti.extend(data)
        meta = resp.get("metadata") or {}
        total_pages = int(meta.get("total_pages") or 1)
        total_el = meta.get("total_elements")
        log.info(
            f"  {endpoint}: page {pagina}/{total_pages}, {len(tutti)}"
            f"{'/' + str(total_el) if total_el is not None else ''} records"
        )
        if pagina >= total_pages:
            break
        pagina += 1
    return tutti


def download_absences(token: str, since: str | None = None) -> list[dict]:
    ""









    log.info("Downloading absences (time-offs)...")
    t0 = time.time()
    extra: dict = {}
    if since:
        extra["updated_from"] = since
        log.info(f"  Incremental: updated_from {since}")
    records = _scarica_per_pagina(token, "time-offs", extra)
    log.info(f"Downloaded {len(records)} absence records in {time.time() - t0:.1f}s")
    return records


def download_absence_periods(token: str, since: str | None = None) -> list[dict]:
    ""

    log.info("Downloading absence periods (hours)...")
    t0 = time.time()
    extra: dict = {}
    if since:
        extra["updated_from"] = since
    records = _scarica_per_pagina(token, "absence-periods", extra)
    log.info(f"Downloaded {len(records)} absence-period records in {time.time() - t0:.1f}s")
    return records


def _record_id(r: dict):
    return (
        r.get("attributes", {}).get("id", {}).get("value")
        if isinstance(r.get("attributes", {}).get("id"), dict)
        else (r.get("attributes", {}).get("id") or r.get("id"))
    )


def _salva_raw(records: list[dict], nome_file: str, *, upsert: bool) -> int:
    ""






    path = PERSONIO_DIR / nome_file
    finali: dict = {}
    if upsert and path.exists():
        try:
            for r in json.loads(path.read_text(encoding="utf-8")).get("data", []):
                finali[str(_record_id(r))] = r
        except (OSError, ValueError) as e:
            log.warning(f"  {nome_file} unreadable ({e}): restarting from new records only")
    prima = len(finali)
    for r in records:
        finali[str(_record_id(r))] = r
    out = list(finali.values())
    _scrivi_json_riservato(path, {"data": out, "total": len(out)})
    log.info(
        f"  Saved {len(records)} records -> {nome_file}"
        + (
            f" ({len(out) - prima} new, {len(out)} total)"
            if upsert
            else f" ({len(out)} total, replaced)"
        )
    )
    return len(out)


def save_absences(records: list[dict], *, upsert: bool = False) -> None:
    _salva_raw(records, "absences-raw.json", upsert=upsert)


def save_absence_periods(records: list[dict], *, upsert: bool = False) -> None:
    _salva_raw(records, "absence-periods-raw.json", upsert=upsert)





def download_absence_types(token: str) -> list[dict]:
    ""
    log.info("Downloading absence types...")

    resp = _request_with_retry(
        "GET",
        f"{BASE_URL}/company/time-off-types",
        auth_token=token,
    )
    data = resp.get("data", [])
    log.info(f"Downloaded {len(data)} absence types")
    return data


def save_absence_types(records: list[dict]) -> None:
    ""
    path = PERSONIO_DIR / "absence-types.json"
    output = {
        "success": True,
        "data": records,
    }
    _scrivi_json_riservato(path, output)
    log.info(f"  Saved {len(records)} absence types -> {path.name}")





def download_attendances(
    token: str, employee_ids: list[int], since: str | None = None
) -> list[dict]:
    ""







    if not employee_ids:


        raise RuntimeError(
            "attendances: called without employee ids. Run --only employees first."
        )

    log.info(f"Downloading attendances for {len(employee_ids)} employees...")
    t0 = time.time()



    all_records = []
    batch_size = 10

    for batch_start in range(0, len(employee_ids), batch_size):
        batch_ids = employee_ids[batch_start : batch_start + batch_size]
        offset = 0

        while True:
            params = {
                "limit": PAGE_SIZE,
                "offset": offset,
                "employees[]": batch_ids,
                "start_date": since or "2020-01-01",
                "end_date": time.strftime("%Y-%m-%d"),
            }

            resp = _request_with_retry(
                "GET",
                f"{BASE_URL}/company/attendances",
                auth_token=token,
                params=params,
            )
            data = resp.get("data", [])

            if not data:
                break

            all_records.extend(data)


            metadata = resp.get("metadata", {})
            total_pages = metadata.get("total_pages", 1)
            current_page = metadata.get("current_page", 0)

            if current_page < total_pages - 1:
                offset += PAGE_SIZE
            else:
                break

        log.info(
            f"  Batch {batch_start // batch_size + 1}: "
            f"{len(batch_ids)} employees, {len(all_records)} total records"
        )

    elapsed = time.time() - t0
    log.info(f"Downloaded {len(all_records)} attendance records in {elapsed:.1f}s")

    return all_records


def save_attendances(records: list[dict]) -> None:
    ""
    path = PERSONIO_DIR / "attendances-raw.json"
    output = {
        "data": records,
        "total": len(records),
    }
    _scrivi_json_riservato(path, output)
    log.info(f"  Saved {len(records)} attendances -> {path.name}")


def _scrivi_json_riservato(path: Path, payload: dict | list) -> None:
    ""












    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    path.chmod(0o600)





def download_employee_attributes(token: str) -> list[dict]:
    ""




    log.info("Downloading employee attributes...")
    resp = _request_with_retry("GET", f"{BASE_URL}/company/employees/attributes", auth_token=token)
    data = resp.get("data", [])
    log.info(f"Downloaded {len(data)} employee attributes")
    return data


def save_employee_attributes(records: list[dict]) -> None:
    path = PERSONIO_DIR / "employee-attributes.json"
    _scrivi_json_riservato(path, {"success": True, "data": records})
    log.info(f"  Saved {len(records)} attributes -> {path.name}")





def download_employments(token: str, employee_ids: list[int]) -> list[dict]:
    ""






    log.info(f"Downloading employments for {len(employee_ids)} persons (v2)...")
    t0 = time.time()
    tutti: list[dict] = []
    for i, eid in enumerate(employee_ids, 1):
        tutti.extend(_pagina_v2(f"/v2/persons/{eid}/employments", token, params={"limit": 50}))
        time.sleep(PAUSA_PER_PERSONA_V2)
        if i % 50 == 0:
            log.info(f"  employments: {i}/{len(employee_ids)} persons, {len(tutti)} records")
    log.info(f"Downloaded {len(tutti)} employments in {time.time() - t0:.1f}s")
    return tutti


def save_employments(records: list[dict], persone: int) -> None:
    path = PERSONIO_DIR / "employments.json"
    _scrivi_json_riservato(
        path, {"data": records, "total": len(records), "persons_queried": persone}
    )
    log.info(f"  Saved {len(records)} employments -> {path.name}")





def download_document_categories(token: str) -> list[dict]:
    ""
    log.info("Downloading document categories...")
    resp = _request_with_retry("GET", f"{BASE_URL}/company/document-categories", auth_token=token)
    data = resp.get("data", [])
    log.info(f"Downloaded {len(data)} document categories")
    return data


def save_document_categories(records: list[dict]) -> None:
    path = PERSONIO_DIR / "document-categories.json"
    _scrivi_json_riservato(path, {"success": True, "data": records})
    log.info(f"  Saved {len(records)} document categories -> {path.name}")


def download_documents(token: str, employee_ids: list[int]) -> list[dict]:
    ""






    log.info(f"Downloading document metadata for {len(employee_ids)} persons (v2)...")
    t0 = time.time()
    tutti: list[dict] = []
    for i, eid in enumerate(employee_ids, 1):
        tutti.extend(
            _pagina_v2(
                "/v2/document-management/documents",
                token,
                params={"owner_id": str(eid), "limit": 200},
            )
        )
        time.sleep(PAUSA_PER_PERSONA_V2)
        if i % 50 == 0:
            log.info(f"  documents: {i}/{len(employee_ids)} persons, {len(tutti)} documents")
    log.info(f"Downloaded {len(tutti)} document records in {time.time() - t0:.1f}s")
    return tutti


def save_documents(records: list[dict], persone: int) -> None:
    path = PERSONIO_DIR / "documents.json"
    _scrivi_json_riservato(
        path,
        {
            "data": records,
            "total": len(records),
            "persons_queried": persone,
            "contenuto_file": "never downloaded: metadata only",
        },
    )
    log.info(f"  Saved {len(records)} document metadata -> {path.name}")





def download_absence_balances(token: str, employee_ids: list[int]) -> list[dict]:
    ""





    log.info(f"Downloading absence balances for {len(employee_ids)} employees...")
    t0 = time.time()
    tutti: list[dict] = []
    for i, eid in enumerate(employee_ids, 1):
        resp = _request_with_retry(
            "GET", f"{BASE_URL}/company/employees/{eid}/absences/balance", auth_token=token
        )
        tutti.append({"employee_id": eid, "balances": resp.get("data", [])})
        time.sleep(PAUSA_PER_PERSONA_V1)
        if i % 50 == 0:
            log.info(f"  balances: {i}/{len(employee_ids)} employees")
    voci = sum(len(x["balances"]) for x in tutti)
    log.info(f"Downloaded {voci} balance entries in {time.time() - t0:.1f}s")
    return tutti


def save_absence_balances(records: list[dict]) -> None:
    path = PERSONIO_DIR / "absence-balances.json"
    voci = sum(len(x["balances"]) for x in records)
    _scrivi_json_riservato(path, {"data": records, "total": len(records), "total_entries": voci})
    log.info(f"  Saved {voci} balance entries for {len(records)} employees -> {path.name}")





def download_custom_reports(token: str) -> tuple[list[dict], dict[str, list[dict]]]:
    ""










    log.info("Downloading custom reports...")
    resp = _request_with_retry(
        "GET", f"{BASE_URL}/company/custom-reports/reports", auth_token=token
    )
    report = resp.get("data", [])
    log.info(f"  {len(report)} custom reports in the account")

    esiti: list[dict] = []
    items_per_report: dict[str, list[dict]] = {}
    for r in report:
        attr = r.get("attributes", {}) or {}
        rid = str(attr.get("id", ""))
        stato, corpo = _get_tollerante(
            f"{BASE_URL}/company/custom-reports/reports/{rid}", token, ammessi=(400, 404)
        )
        voce = {
            "id": rid,
            "name": attr.get("name"),
            "type": attr.get("type"),
            "archival_status": attr.get("archival_status"),
            "data_refreshed_at": attr.get("data_refreshed_at"),
            "columns": attr.get("columns", []),
            "http": stato,
        }
        if stato == 200:
            dati = (corpo or {}).get("data") or []
            items = (dati[0].get("attributes", {}) or {}).get("items", []) if dati else []
            items_per_report[rid] = items
            voce["esito"] = "letto"
            voce["items"] = len(items)
        else:
            voce["esito"] = "non_leggibile"
            voce["motivo"] = _motivo_errore(corpo)
            voce["items"] = 0
            log.warning(f"  report '{attr.get('name')}': HTTP {stato} — {voce['motivo'][:120]}")
        esiti.append(voce)
        time.sleep(PAUSA_PER_PERSONA_V1)

    letti = sum(1 for v in esiti if v["esito"] == "letto")
    log.info(f"Custom reports: {letti}/{len(esiti)} readable via API")
    return esiti, items_per_report


def save_custom_reports(esiti: list[dict], items_per_report: dict[str, list[dict]]) -> None:
    path = PERSONIO_DIR / "custom-reports.json"
    _scrivi_json_riservato(
        path,
        {
            "data": esiti,
            "total": len(esiti),
            "leggibili": sum(1 for v in esiti if v.get("esito") == "letto"),
        },
    )
    log.info(f"  Saved {len(esiti)} custom reports -> {path.name}")

    dir_items = PERSONIO_DIR / "custom-report-items"
    dir_items.mkdir(parents=True, exist_ok=True)
    dir_items.chmod(0o700)
    for rid, items in items_per_report.items():
        _scrivi_json_riservato(
            dir_items / f"{rid}.json", {"report_id": rid, "items": items, "total": len(items)}
        )
    if items_per_report:
        log.info(f"  Saved {len(items_per_report)} report items -> {dir_items.name}/")





def download_compensations(token: str, mesi: int = MESI_COMPENSATIONS) -> list[dict]:
    ""






    log.info(f"Downloading compensations (last {mesi} months, one window per month)...")
    t0 = time.time()
    per_id: dict[str, dict] = {}
    oggi = datetime.now(UTC).date()

    for indietro in range(mesi):
        anno = oggi.year
        mese = oggi.month - indietro
        while mese <= 0:
            mese += 12
            anno -= 1
        inizio = f"{anno:04d}-{mese:02d}-01"
        ultimo = _ultimo_giorno(anno, mese)
        fine = f"{anno:04d}-{mese:02d}-{ultimo:02d}"
        records = _pagina_v2(
            "/v2/compensations",
            token,
            params={"limit": 100, "start_date": inizio, "end_date": fine},
        )
        for rec in records:
            per_id[str(rec.get("id"))] = rec
        log.info(f"  compensations {inizio}: {len(records)} records ({len(per_id)} unique so far)")

    log.info(f"Downloaded {len(per_id)} compensations in {time.time() - t0:.1f}s")
    return list(per_id.values())


def _ultimo_giorno(anno: int, mese: int) -> int:
    ""

    from datetime import date, timedelta

    primo_dopo = date(anno + (mese == 12), 1 if mese == 12 else mese + 1, 1)
    return (primo_dopo - timedelta(days=1)).day


def _mesi_fra(dal: date, oggi: date) -> int:
    ""
    return (oggi.year - dal.year) * 12 + oggi.month - dal.month + 1


def _inizio_finestre(mesi: int, oggi: date) -> str:
    ""

    indietro = oggi.year * 12 + oggi.month - 1 - (mesi - 1)
    return f"{indietro // 12:04d}-{indietro % 12 + 1:02d}-01"


def leggi_compensations() -> dict:
    ""
    path = PERSONIO_DIR / "compensations.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _prima_assunzione() -> date | None:
    ""
    path = PERSONIO_DIR / "employees-flat.json"
    if not path.exists():
        return None
    date_ = [str(e["hire_date"])[:10] for e in json.loads(path.read_text()) if e.get("hire_date")]
    return date.fromisoformat(min(date_)) if date_ else None


def mesi_compensations(storico: dict, oggi: date | None = None) -> int:
    ""

    oggi = oggi or datetime.now(UTC).date()
    prima = _prima_assunzione()
    if prima is None or (storico.get("storia_dal") or "9999-12") <= f"{prima:%Y-%m}":
        return MESI_COMPENSATIONS
    return max(MESI_COMPENSATIONS, _mesi_fra(prima, oggi))


def fondi_compensations(
    storico: dict, nuovi: list[dict], mesi: int, oggi: date | None = None
) -> tuple[list[dict], list[dict], str]:
    ""







    oggi = oggi or datetime.now(UTC).date()
    inizio = _inizio_finestre(mesi, oggi)
    fine = f"{oggi:%Y-%m}-{_ultimo_giorno(oggi.year, oggi.month):02d}"
    per_id = {str(r.get("id")): r for r in storico.get("data") or []}
    tornati = {str(r.get("id")) for r in nuovi}
    spariti = list(storico.get("non_piu_in_personio") or [])
    for rid, rec in list(per_id.items()):
        if rid not in tornati and inizio <= str(rec.get("effective_from") or "")[:10] <= fine:
            spariti.append({**rec, "sparito_il": f"{oggi:%Y-%m-%d}"})
            del per_id[rid]
    for rec in nuovi:
        per_id[str(rec.get("id"))] = rec
    storia_dal = min(filter(None, (storico.get("storia_dal"), inizio[:7])))
    return list(per_id.values()), spariti, storia_dal


def save_compensations(
    records: list[dict],
    mesi: int,
    *,
    storia_dal: str | None = None,
    spariti: list[dict] | None = None,
) -> None:
    path = PERSONIO_DIR / "compensations.json"
    payload = {"data": records, "total": len(records), "mesi_coperti": mesi}
    if storia_dal:
        payload["storia_dal"] = storia_dal
    if spariti:
        payload["non_piu_in_personio"] = spariti
    _scrivi_json_riservato(path, payload)
    log.info(f"  Saved {len(records)} compensations -> {path.name}")





def download_recruiting(token: str) -> dict:
    ""








    log.info("Downloading recruiting (v2)...")
    esiti: list[dict] = []
    dati: dict[str, list[dict]] = {}

    for sub in RECRUITING_SUBPATH:
        url = f"{BASE_V2}/v2/{sub}"
        stato, corpo = _get_tollerante(url, token, params={"limit": 1}, ammessi=(403, 404))
        voce = {"path": f"/v2/{sub}", "http": stato}
        if stato == 200:
            records = _pagina_v2(f"/v2/{sub}", token, params={"limit": 100})
            dati[sub.split("/")[-1]] = records
            voce["esito"] = "disponibile"
            voce["n"] = len(records)
        else:
            voce["esito"] = "non_disponibile"
            voce["motivo"] = _motivo_errore(corpo)
            voce["n"] = 0
        esiti.append(voce)
        log.info(f"  /v2/{sub}: HTTP {stato} — {voce['esito']}")
        time.sleep(PAUSA_PER_PERSONA_V2)

    return {
        "controllato_il": datetime.now(UTC).isoformat(),
        "sotto_endpoint": esiti,
        "disponibili": sum(1 for v in esiti if v["esito"] == "disponibile"),
        "data": dati,
    }


def save_recruiting(esito: dict) -> None:
    path = PERSONIO_DIR / "recruiting.json"
    _scrivi_json_riservato(path, esito)
    log.info(
        f"  Saved recruiting ({esito['disponibili']}/{len(esito['sotto_endpoint'])} "
        f"sub-endpoints available) -> {path.name}"
    )





def download_org_units_v2(token: str) -> dict[str, list[dict]]:
    ""









    log.info("Downloading org units (v2)...")
    ref: dict[str, list[dict]] = {
        "departments": _pagina_v2(
            "/v2/org-units", token, params={"type": "department", "limit": 100}
        ),
        "teams": _pagina_v2("/v2/org-units", token, params={"type": "team", "limit": 100}),
        "offices": _pagina_v2("/v2/workplaces", token, params={"limit": 100}),
        "legal_entities": _pagina_v2("/v2/legal-entities", token, params={"limit": 100}),
    }
    for chiave, valori in ref.items():
        log.info(f"  {chiave}: {len(valori)}")
    return ref


def save_org_units_v2(ref: dict[str, list[dict]]) -> None:
    file_map = {
        "departments": "departments.json",
        "teams": "teams.json",
        "offices": "offices.json",
        "legal_entities": "legal-entities.json",
    }
    for chiave, nome in file_map.items():
        path = PERSONIO_DIR / nome
        _scrivi_json_riservato(path, ref.get(chiave, []))
        log.info(f"  Saved {len(ref.get(chiave, []))} {chiave} -> {nome}")





def download_reference_data(token: str) -> dict[str, list[dict]]:
    ""








    log.info("Downloading reference data (cost centers)...")
    ref_data: dict[str, list[dict]] = {}

    flat_path = PERSONIO_DIR / "employees-flat.json"
    if not flat_path.exists():
        raise FileNotFoundError(
            f"{flat_path} does not exist: cost centers are derived from employees. "
            "Run --only employees first."
        )

    with open(flat_path, encoding="utf-8") as f:
        employees = json.load(f)

    cost_centers = set()
    for emp in employees:
        cc = emp.get("cost_centers")
        if isinstance(cc, list):
            for item in cc:
                if isinstance(item, str) and item.strip():
                    cost_centers.add(item.strip())
        elif isinstance(cc, str) and cc.strip():
            cost_centers.add(cc.strip())
    ref_data["cost_centers"] = sorted(cost_centers)
    log.info(f"  Extracted {len(cost_centers)} cost centers from employees")

    return ref_data


def save_reference_data(ref_data: dict[str, list]) -> None:
    ""
    file_map = {
        "cost_centers": "cost-centers.json",
    }

    for key, filename in file_map.items():
        data = ref_data.get(key, [])
        path = PERSONIO_DIR / filename
        _scrivi_json_riservato(path, data)
        log.info(f"  Saved {len(data)} {key} -> {filename}")





def build_index(
    *,
    employee_count: int = 0,
    absence_count: int = 0,
    attendance_count: int = 0,
    absence_type_count: int = 0,
    ref_data: dict | None = None,
    conteggi: dict | None = None,
    org_units: dict | None = None,
) -> dict:
    ""





    now = datetime.now(UTC).isoformat()


    files = []
    for f in sorted(PERSONIO_DIR.iterdir()):
        if f.is_file() and f.suffix == ".json" and not f.name.startswith("."):
            files.append(
                {
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "size_human": _human_size(f.stat().st_size),
                }
            )

    total_size = sum(f["size_bytes"] for f in files)


    employee_statuses = {}
    flat_path = PERSONIO_DIR / "employees-flat.json"
    if flat_path.exists():
        with open(flat_path, encoding="utf-8") as fh:
            employees = json.load(fh)
        for emp in employees:
            s = emp.get("status", "unknown")
            employee_statuses[s] = employee_statuses.get(s, 0) + 1

        subcompanies = sorted(
            {emp.get("subcompany", "") for emp in employees if emp.get("subcompany")}
        )
    else:
        subcompanies = []

    index = {
        "source": "Personio HR",
        "extracted_at": now,
        "total_files": len(files),
        "total_size": _human_size(total_size),
        "data_summary": {
            "employees": {
                "total_records": employee_count,
                **employee_statuses,
                "subcompanies": subcompanies,
            },
            "absences": {
                "total_records": absence_count,
            },
            "attendances": {
                "total_records": attendance_count,
            },
            "absence_types": absence_type_count,
        },
        "files": files,
    }

    if ref_data:
        index["data_summary"]["cost_centers"] = len(ref_data.get("cost_centers", []))

    if org_units:
        for chiave, valori in org_units.items():
            index["data_summary"][chiave] = len(valori)

    if conteggi:
        index["data_summary"].update(conteggi)

    return index


def _human_size(size_bytes: int) -> str:
    ""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"




VALID_TARGETS = [
    "employees",
    "attributes",
    "absences",
    "absence-periods",
    "absence-types",
    "balances",
    "employments",
    "documents",
    "custom-reports",
    "compensations",
    "recruiting",
    "org-units-v2",
    "attendances",
    "reference",
]







TARGET_DEFAULT = [
    "employees",
    "attributes",
    "absences",
    "absence-periods",
    "absence-types",
    "balances",
    "employments",
    "documents",
    "custom-reports",
    "compensations",
    "recruiting",
    "org-units-v2",
    "reference",
]


def main():
    parser = argparse.ArgumentParser(description="Personio L0 download — SBK")
    parser.add_argument(
        "--only",
        default=None,
        choices=VALID_TARGETS,
        help="Download only a specific data type (default: all)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Start date YYYY-MM-DD for incremental download (absences/attendances)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify authentication without downloading data",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Auto-set --since from last run date; skip if < 1h ago",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full download: skip time gate and always write regardless of hash comparison",
    )
    args = parser.parse_args()


    PERSONIO_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(PERSONIO_DIR / "download.log"),
        ],
    )

    if args.incremental and not args.force:
        last = get_last_run("personio")
        if last:


            age_hours = (datetime.now(UTC) - last.replace(tzinfo=UTC)).total_seconds() / 3600
            if age_hours < 1:
                log.info(f"Incremental: last run {age_hours:.1f}h ago (< 1h) — skipping")

                sys.exit(0)

            if not args.since:
                args.since = last.strftime("%Y-%m-%d")

    log.info("=" * 60)
    log.info("PERSONIO L0 DOWNLOAD")
    log.info("=" * 60)
    log.info(f"Output: {PERSONIO_DIR}")
    if args.only:
        log.info(f"Target: {args.only}")
    if args.since:
        log.info(f"Since: {args.since}")

    t0 = time.time()


    token = authenticate()

    if args.dry_run:
        log.info("--dry-run: authentication OK, stopping here")
        return

    targets = [args.only] if args.only else list(TARGET_DEFAULT)

    employee_count = 0
    absence_count = 0
    attendance_count = 0
    absence_type_count = 0
    ref_data = None
    org_units = None
    conteggi: dict[str, int | str] = {}
    employee_ids: list[int] = []

    def id_dipendenti() -> list[int]:
        ""


        nonlocal employee_ids
        if employee_ids:
            return employee_ids
        flat_path = PERSONIO_DIR / "employees-flat.json"
        if not flat_path.exists():
            raise FileNotFoundError(
                f"{flat_path} does not exist: employee ids are required. "
                "Run --only employees first."
            )
        with open(flat_path, encoding="utf-8") as f:
            employee_ids = [e.get("id") for e in json.load(f) if e.get("id")]
        if not employee_ids:
            raise ValueError(f"{flat_path.name} contains no employee ids")
        return employee_ids


    if "employees" in targets:
        raw_records, flat_records = download_employees(token)
        save_employees(raw_records, flat_records, force=args.force)
        employee_count = len(flat_records)
        employee_ids = [emp.get("id") for emp in flat_records if emp.get("id")]


    if "attributes" in targets:
        attributi = download_employee_attributes(token)
        save_employee_attributes(attributi)
        conteggi["employee_attributes"] = len(attributi)


    if "absences" in targets:
        absence_records = download_absences(token, since=args.since)
        save_absences(absence_records, upsert=bool(args.since))
        absence_count = len(absence_records)

    if "absence-periods" in targets:
        periodi = download_absence_periods(token, since=args.since)
        save_absence_periods(periodi, upsert=bool(args.since))
        log.info(f"  absence-periods: {len(periodi)}")


    if "absence-types" in targets:
        type_records = download_absence_types(token)
        save_absence_types(type_records)
        absence_type_count = len(type_records)


    if "balances" in targets:
        saldi = download_absence_balances(token, id_dipendenti())
        save_absence_balances(saldi)
        conteggi["absence_balances"] = sum(len(x["balances"]) for x in saldi)


    if "employments" in targets:
        rapporti = download_employments(token, id_dipendenti())
        save_employments(rapporti, len(id_dipendenti()))
        conteggi["employments"] = len(rapporti)


    if "documents" in targets:
        categorie = download_document_categories(token)
        save_document_categories(categorie)
        documenti = download_documents(token, id_dipendenti())
        save_documents(documenti, len(id_dipendenti()))
        conteggi["document_categories"] = len(categorie)
        conteggi["documents"] = len(documenti)


    if "custom-reports" in targets:
        esiti, items = download_custom_reports(token)
        save_custom_reports(esiti, items)
        conteggi["custom_reports"] = len(esiti)
        conteggi["custom_reports_leggibili"] = sum(1 for v in esiti if v["esito"] == "letto")


    if "compensations" in targets:
        storico = leggi_compensations()
        mesi = mesi_compensations(storico)
        if mesi > MESI_COMPENSATIONS:
            log.info(
                f"Compensations: history on disk does not reach the first hire, {mesi} windows"
            )
        retribuzioni, spariti, storia_dal = fondi_compensations(
            storico, download_compensations(token, mesi=mesi), mesi
        )
        coperti = _mesi_fra(datetime.strptime(storia_dal, "%Y-%m").date(), datetime.now(UTC).date())
        save_compensations(retribuzioni, coperti, storia_dal=storia_dal, spariti=spariti)
        conteggi["compensations"] = len(retribuzioni)
        conteggi["compensations_storia_dal"] = storia_dal
        conteggi["compensations_non_piu_in_personio"] = len(spariti)


    if "recruiting" in targets:
        rec = download_recruiting(token)
        save_recruiting(rec)
        conteggi["recruiting_disponibili"] = rec["disponibili"]
        conteggi["recruiting_sotto_endpoint"] = len(rec["sotto_endpoint"])


    if "org-units-v2" in targets:
        org_units = download_org_units_v2(token)
        save_org_units_v2(org_units)


    if "attendances" in targets:

        if not employee_ids:
            flat_path = PERSONIO_DIR / "employees-flat.json"
            if flat_path.exists():
                with open(flat_path, encoding="utf-8") as f:
                    employees = json.load(f)
                employee_ids = [emp.get("id") for emp in employees if emp.get("id")]
            else:




                raise RuntimeError(
                    "attendances: no employee id available "
                    "(employees-flat.json is missing). Run --only employees first."
                )

        if employee_ids:
            att_records = download_attendances(token, employee_ids, since=args.since)
            save_attendances(att_records)
            attendance_count = len(att_records)


    if "reference" in targets:
        ref_data = download_reference_data(token)
        save_reference_data(ref_data)


    index = build_index(
        employee_count=employee_count,
        absence_count=absence_count,
        attendance_count=attendance_count,
        absence_type_count=absence_type_count,
        ref_data=ref_data,
        conteggi=conteggi,
        org_units=org_units,
    )
    index_path = PERSONIO_DIR / "personio-index.json"
    _scrivi_json_riservato(index_path, index)
    log.info(f"  Saved index -> {index_path.name}")


    elapsed = time.time() - t0
    log.info("")
    log.info("=" * 60)
    log.info("PERSONIO L0 DOWNLOAD COMPLETE")
    log.info("=" * 60)
    log.info(f"  Time: {elapsed:.1f}s")
    log.info(f"  Targets run: {', '.join(targets)}")
    if employee_count:
        log.info(f"  Employees: {employee_count}")
    if absence_count:
        log.info(f"  Absences: {absence_count}")
    if absence_type_count:
        log.info(f"  Absence types: {absence_type_count}")
    if attendance_count:
        log.info(f"  Attendances: {attendance_count}")
    for chiave, valore in conteggi.items():
        log.info(f"  {chiave}: {valore}")
    if org_units:
        for chiave, vals in org_units.items():
            log.info(f"  {chiave}: {len(vals)}")
    if ref_data:
        for key, vals in ref_data.items():
            log.info(f"  {key}: {len(vals)}")

    saltati = [t for t in VALID_TARGETS if t not in targets]
    if saltati:
        log.info(f"  Not downloaded in this run: {', '.join(saltati)}")
    log.info(f"  Output: {PERSONIO_DIR}")


    try:
        from event_bus import EventBus

        EventBus.emit("personio", "l0", employees=employee_count, absences=absence_count)
    except Exception as e:
        log.warning(f"EventBus emit failed: {e}")

    mark_last_run("personio")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-personio-download", source="personio", stage="l0", mark_run=False)
def run():
    main()


if __name__ == "__main__":
    run()
