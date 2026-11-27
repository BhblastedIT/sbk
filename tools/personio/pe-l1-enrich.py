#!/usr/bin/env python3
"""Personio L1: employees, employments (with the termination type), the org chart and the contacts from the
Personio download, as parquet files with a summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import PERSONIO_DIR, PERSONIO_PROCESSED_DIR, safe_write_parquet



RAW_DIR = PERSONIO_DIR
PROCESSED_DIR = PERSONIO_PROCESSED_DIR
EMPLOYEES_FILE = RAW_DIR / "employees-flat.json"
EMPLOYEES_RAW_FILE = RAW_DIR / "employees-raw.json"
ATTRIBUTES_FILE = RAW_DIR / "employee-attributes.json"
EMPLOYMENTS_FILE = RAW_DIR / "employments.json"
ABSENCES_FILE = RAW_DIR / "absences-raw.json"

log = logging.getLogger("personio-enrich")







CHIAVI_DELLE_COLONNE_STORICHE = frozenset(
    {
        "first_name",
        "last_name",
        "preferred_name",
        "email",
        "gender",
        "status",
        "position",
        "supervisor",
        "employment_type",
        "weekly_working_hours",
        "hire_date",
        "contract_end_date",
        "termination_date",
        "termination_type",
        "termination_reason",
        "created_at",
        "last_modified_at",
        "subcompany",
        "office",
        "department",
        "work_schedule",
        "fix_salary",
        "fix_salary_interval",
        "team",
    }
)



COLONNE_STORICHE = (
    "employee_id",
    "name",
    "preferred_name",
    "email",
    "gender",
    "department",
    "team",
    "position",
    "hire_date",
    "status",
    "manager_name",
    "manager_email",
    "office",
    "subcompany",
    "employment_type",
    "contract_end_date",
    "termination_date",
    "termination_type",
    "termination_reason",
    "weekly_hours",
    "work_schedule",
    "fix_salary",
    "salary_interval",
    "created_at",
    "last_modified",
)




CHIAVI_RIEMESSE = frozenset({"first_name", "last_name"})





COLONNE_ID_DAL_RAW = (
    "supervisor_id",
    "department_id",
    "team_id",
    "subcompany_id",
    "office_id",
)
COLONNE_DAL_RAW = (*COLONNE_ID_DAL_RAW, "supervisor_email")




def load_employees() -> list[dict]:
    ""
    if not EMPLOYEES_FILE.exists():
        log.error(f"Employees file not found: {EMPLOYEES_FILE}")
        sys.exit(1)
    with open(EMPLOYEES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    log.info(f"Loaded {len(data)} employees from {EMPLOYEES_FILE.name}")
    return data


def load_absences() -> list[dict]:
    ""
    if not ABSENCES_FILE.exists():
        log.warning(f"Absences file not found: {ABSENCES_FILE}, skipping")
        return []
    with open(ABSENCES_FILE, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "data" in data:
        absences = data["data"]
    elif isinstance(data, list):
        absences = data
    else:
        log.warning("Unexpected absences format, skipping")
        return []
    log.info(f"Loaded {len(absences)} absence records")
    return absences


def load_attribute_schema() -> dict[str, dict]:
    ""







    if ATTRIBUTES_FILE.exists():
        try:
            payload = json.loads(ATTRIBUTES_FILE.read_text(encoding="utf-8"))
            voci = payload.get("data", payload) if isinstance(payload, dict) else payload
            schema = {
                v["key"]: {
                    "label": v.get("label") or "",
                    "universal_id": v.get("universal_id") or "",
                    "type": (v.get("type") or "").lower(),
                }
                for v in voci
                if isinstance(v, dict) and v.get("key")
            }
            if schema:
                log.info(f"Personio attributes: {len(schema)} labels from {ATTRIBUTES_FILE.name}")
                return schema
        except (OSError, ValueError, TypeError, KeyError) as e:
            log.warning(f"{ATTRIBUTES_FILE.name} unreadable ({e}), trying the raw file")

    if EMPLOYEES_RAW_FILE.exists():
        try:
            payload = json.loads(EMPLOYEES_RAW_FILE.read_text(encoding="utf-8"))
            record = (payload.get("data") or [])[0] if isinstance(payload, dict) else payload[0]
            schema = {
                k: {
                    "label": (v.get("label") or "") if isinstance(v, dict) else "",
                    "universal_id": (v.get("universal_id") or "") if isinstance(v, dict) else "",
                    "type": ((v.get("type") or "") if isinstance(v, dict) else "").lower(),
                }
                for k, v in (record.get("attributes") or {}).items()
            }
            if schema:
                log.warning(
                    f"{ATTRIBUTES_FILE.name} missing: labels taken from the first record of "
                    f"{EMPLOYEES_RAW_FILE.name} ({len(schema)} attributes)"
                )
                return schema
        except (OSError, ValueError, TypeError, KeyError, IndexError) as e:
            log.warning(f"{EMPLOYEES_RAW_FILE.name} unreadable ({e})")

    log.warning(
        "No label source: new columns take the raw key name "
        "(dynamic_*). Re-run L0 with --only attributes to get the real names."
    )
    return {}


def load_employees_raw() -> dict[int, dict]:
    ""
    if not EMPLOYEES_RAW_FILE.exists():
        log.warning(f"{EMPLOYEES_RAW_FILE.name} missing: no supervisor/department/team ids")
        return {}
    try:
        payload = json.loads(EMPLOYEES_RAW_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning(f"{EMPLOYEES_RAW_FILE.name} unreadable ({e})")
        return {}
    record_list = payload.get("data", []) if isinstance(payload, dict) else payload
    per_id: dict[int, dict] = {}
    for rec in record_list:
        attrs = rec.get("attributes") if isinstance(rec, dict) else None
        if not isinstance(attrs, dict):
            continue
        eid = _valore_attributo(attrs.get("id"))
        if eid is not None:
            per_id[eid] = attrs
    log.info(f"Raw Personio: {len(per_id)} records indexed by id")
    return per_id


def _valore_attributo(attr: object):
    ""
    if isinstance(attr, dict) and "value" in attr:
        return attr["value"]
    return attr


def normalizza_nome_colonna(etichetta: str) -> str:
    ""






    testo = unicodedata.normalize("NFKD", str(etichetta or ""))
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = testo.lower().replace("%", " pct ").replace("&", " and ")
    testo = re.sub(r"[^a-z0-9]+", "_", testo).strip("_")
    if testo and testo[0].isdigit():
        testo = f"a_{testo}"
    return testo


def deriva_nomi_colonne(
    chiavi: list[str], schema: dict[str, dict], riservati: set[str]
) -> dict[str, str]:
    ""













    nomi: dict[str, str] = {}
    presi = set(riservati)
    for chiave in sorted(chiavi):
        voce = schema.get(chiave, {})
        base = normalizza_nome_colonna(voce.get("universal_id") or voce.get("label") or chiave)
        if not base:
            base = normalizza_nome_colonna(chiave)
        nome = base
        if nome in presi:
            coda = chiave.rsplit("_", 1)[-1] if "_" in chiave else chiave
            nome = f"{base}__{coda}"
        nomi[chiave] = nome
        presi.add(nome)
    return nomi


def parse_date(date_str: str) -> str | None:
    ""
    if not date_str or not isinstance(date_str, str) or date_str.strip() == "":
        return None
    try:

        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def normalize_status(status: str, termination_date: str | None) -> str:
    ""






    if not status:
        return "unknown"
    s = status.strip().lower()
    if s == "active":
        return "active"
    if s == "inactive":
        if termination_date:
            return "terminated"
        return "inactive"
    return s


def resolve_manager_email(manager_name: str, employees: list[dict]) -> str:
    ""
    if not manager_name:
        return ""
    name_lower = manager_name.strip().lower()
    for emp in employees:
        full_name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip().lower()
        preferred = (emp.get("preferred_name") or "").strip().lower()
        if full_name == name_lower or preferred == name_lower:
            return emp.get("email", "") or ""
    return ""


def valore_per_parquet(valore: object, tipo: str) -> object:
    ""







    if tipo == "date":
        return (parse_date(valore) or "") if isinstance(valore, str) else ""
    if valore is None:
        return None if tipo in ("decimal", "integer") else ""
    if isinstance(valore, list):
        return json.dumps(valore, ensure_ascii=False) if valore else ""
    if isinstance(valore, dict):
        return json.dumps(valore, ensure_ascii=False)
    if isinstance(valore, str):
        return valore.strip()
    return valore


def id_oggetti_annidati(attrs: dict) -> dict:
    ""








    vuoto: dict = dict.fromkeys(COLONNE_ID_DAL_RAW, None)
    vuoto["supervisor_email"] = ""
    if not attrs:
        return vuoto
    fuori = dict(vuoto)

    supervisore = _valore_attributo(attrs.get("supervisor"))
    if isinstance(supervisore, dict):
        sotto = supervisore.get("attributes", {}) or {}
        fuori["supervisor_id"] = _valore_attributo(sotto.get("id"))
        fuori["supervisor_email"] = (_valore_attributo(sotto.get("email")) or "").strip().lower()

    for chiave, colonna in (
        ("department", "department_id"),
        ("team", "team_id"),
        ("subcompany", "subcompany_id"),
        ("office", "office_id"),
    ):
        oggetto = _valore_attributo(attrs.get(chiave))
        if isinstance(oggetto, dict):
            fuori[colonna] = (oggetto.get("attributes") or {}).get("id")
    return fuori


def absence_entitlement_con_numeri(attrs: dict) -> str | None:
    ""






    if not attrs:
        return None
    voci = _valore_attributo(attrs.get("absence_entitlement"))
    if not isinstance(voci, list):
        return None
    diritti = []
    for voce in voci:
        sotto = voce.get("attributes", {}) if isinstance(voce, dict) else {}
        if not sotto:
            continue
        diritti.append(
            {
                "id": sotto.get("id"),
                "name": sotto.get("name"),
                "category": sotto.get("category"),
                "entitlement": sotto.get("entitlement"),
            }
        )
    return json.dumps(diritti, ensure_ascii=False) if diritti else ""





def build_employees(
    raw_employees: list[dict],
    schema: dict[str, dict] | None = None,
    raw_per_id: dict[int, dict] | None = None,
) -> pd.DataFrame:
    ""





    log.info("Phase 1: Building employees.parquet...")
    t0 = time.time()

    schema = schema if schema is not None else load_attribute_schema()
    raw_per_id = raw_per_id if raw_per_id is not None else load_employees_raw()



    chiavi_presenti: list[str] = []
    viste: set[str] = set()
    for emp in raw_employees:
        for chiave in emp:
            if chiave not in viste:
                viste.add(chiave)
                chiavi_presenti.append(chiave)
    chiavi_extra = [
        k
        for k in chiavi_presenti
        if k != "id" and (k not in CHIAVI_DELLE_COLONNE_STORICHE or k in CHIAVI_RIEMESSE)
    ]
    riservati = set(COLONNE_STORICHE) | set(COLONNE_DAL_RAW)
    nomi_extra = deriva_nomi_colonne(chiavi_extra, schema, riservati)

    rows = []
    for emp in raw_employees:
        emp_id = emp.get("id", 0)
        first_name = (emp.get("first_name") or "").strip()
        last_name = (emp.get("last_name") or "").strip()
        name = f"{first_name} {last_name}".strip()
        preferred_name = (emp.get("preferred_name") or "").strip()
        email = (emp.get("email") or "").strip().lower()
        gender = (emp.get("gender") or "").strip()
        position = (emp.get("position") or "").strip()
        supervisor = (emp.get("supervisor") or "").strip()
        employment_type = (emp.get("employment_type") or "").strip()
        weekly_hours = emp.get("weekly_working_hours", "")


        hire_date = parse_date(emp.get("hire_date", ""))
        contract_end_date = parse_date(emp.get("contract_end_date", ""))
        termination_date = parse_date(emp.get("termination_date", ""))
        created_at = parse_date(emp.get("created_at", ""))
        last_modified = parse_date(emp.get("last_modified_at", ""))




        status = normalize_status(emp.get("status", ""), termination_date)


        termination_type = (emp.get("termination_type") or "").strip()
        termination_reason = (emp.get("termination_reason") or "").strip()


        subcompany = (emp.get("subcompany") or "").strip()
        office = (emp.get("office") or "").strip()
        department = (emp.get("department") or "").strip() if emp.get("department") else ""
        team = (emp.get("team") or "").strip() if emp.get("team") else ""


        fix_salary = emp.get("fix_salary", 0) or 0
        salary_interval = (emp.get("fix_salary_interval") or "").strip()


        work_schedule = (emp.get("work_schedule") or "").strip()


        manager_email = resolve_manager_email(supervisor, raw_employees)

        attrs_raw = raw_per_id.get(emp_id, {})

        riga = {
            "employee_id": emp_id,
            "name": name,
            "preferred_name": preferred_name,
            "email": email,
            "gender": gender,
            "department": department,
            "team": team,
            "position": position,
            "hire_date": hire_date or "",
            "status": status,
            "manager_name": supervisor,
            "manager_email": manager_email,
            "office": office,
            "subcompany": subcompany,
            "employment_type": employment_type,
            "contract_end_date": contract_end_date or "",
            "termination_date": termination_date or "",
            "termination_type": termination_type,
            "termination_reason": termination_reason,
            "weekly_hours": weekly_hours,
            "work_schedule": work_schedule,
            "fix_salary": fix_salary,
            "salary_interval": salary_interval,
            "created_at": created_at or "",
            "last_modified": last_modified or "",
        }

        riga.update(id_oggetti_annidati(attrs_raw))

        for chiave, colonna in nomi_extra.items():
            riga[colonna] = valore_per_parquet(emp.get(chiave), schema.get(chiave, {}).get("type"))



        colonna_diritti = nomi_extra.get("absence_entitlement")
        diritti = absence_entitlement_con_numeri(attrs_raw)
        if colonna_diritti and diritti is not None:
            riga[colonna_diritti] = diritti

        rows.append(riga)

    df = pd.DataFrame(rows)



    for colonna in COLONNE_ID_DAL_RAW:
        if colonna in df.columns:
            df[colonna] = pd.to_numeric(df[colonna], errors="coerce").astype("Int64")

    df.sort_values(["status", "name"], ascending=[True, True], inplace=True)

    elapsed = time.time() - t0
    log.info(f"Employees: {len(df)} records, {len(df.columns)} columns in {elapsed:.1f}s")



    mancanti = [c for c in COLONNE_STORICHE if c not in df.columns]
    if mancanti:
        log.error(f"  Historical columns missing (broken contract): {mancanti}")
    log.info(
        f"  Columns added: {len(COLONNE_DAL_RAW)} from raw + {len(nomi_extra)} from attributes"
    )
    senza_etichetta = sorted(c for c in nomi_extra.values() if c.startswith("dynamic_"))
    if senza_etichetta:
        log.warning(
            f"  Columns left with the raw key (label missing): {senza_etichetta}"
        )


    status_counts = df["status"].value_counts().to_dict()
    subco_counts = df["subcompany"].value_counts().to_dict()
    log.info(f"  Status: {status_counts}")
    log.info(f"  Subcompanies: {subco_counts}")

    return df





def load_employments() -> list[dict]:
    ""






    if not EMPLOYMENTS_FILE.exists():
        log.info(f"{EMPLOYMENTS_FILE.name} missing: no employment history to process")
        return []
    try:
        payload = json.loads(EMPLOYMENTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning(f"{EMPLOYMENTS_FILE.name} unreadable ({e})")
        return []

    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload = payload["data"]
    if isinstance(payload, list):
        record = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        record = []
        for id_persona, rapporti in payload.items():
            for rapporto in rapporti if isinstance(rapporti, list) else []:
                if isinstance(rapporto, dict):
                    rapporto.setdefault("person", {"id": id_persona})
                    record.append(rapporto)
    else:
        log.warning(f"{EMPLOYMENTS_FILE.name}: unexpected shape, ignored")
        return []
    log.info(f"Loaded {len(record)} employment records")
    return record


def _id_riferimento(oggetto: object):
    ""
    if isinstance(oggetto, dict):
        return oggetto.get("id", "")
    return oggetto if oggetto is not None else ""








CESSAZIONE_V2_A_V1 = {
    "FIRED": "fired",
    "QUIT": "employee-quit",
    "CONTRACT_EXPIRED": "contract-expired",
    "AGREEMENT": "termination-agreement",
    "SETTLEMENT_AGREEMENT": "settlement-agreement",
    "IRREVOCABLE_SUSPENSION": "irrevocable-suspension",
    "COURT_SETTLEMENT": "court-settlement",
    "UNSPECIFIED": "",
}


def tipo_cessazione_v1(tipo: object) -> str:
    ""
    grezzo = (tipo or "").strip()
    if not grezzo:
        return ""
    if grezzo in CESSAZIONE_V2_A_V1:
        return CESSAZIONE_V2_A_V1[grezzo]
    tradotto = grezzo.lower().replace("_", "-")
    log.warning(f"Unknown v2 termination type: {grezzo} -> '{tradotto}' (to be verified)")
    return tradotto


def build_employments(record: list[dict]) -> pd.DataFrame:
    ""






    log.info("Phase 1b: Building employments.parquet...")
    righe = []
    for rapporto in record:
        unita = {
            (u.get("type") or "").lower(): u.get("id")
            for u in (rapporto.get("org_units") or [])
            if isinstance(u, dict)
        }
        cessazione = rapporto.get("termination") or {}
        righe.append(
            {
                "employee_id": _id_riferimento(rapporto.get("person")),
                "employment_id": rapporto.get("id", ""),
                "status": (rapporto.get("status") or "").strip().lower(),
                "employment_type": (rapporto.get("type") or "").strip().lower(),
                "position": ((rapporto.get("position") or {}) or {}).get("title", ""),
                "employment_start_date": parse_date(rapporto.get("employment_start_date", ""))
                or "",
                "employment_end_date": parse_date(rapporto.get("employment_end_date", "")) or "",
                "contract_end_date": parse_date(rapporto.get("contract_end_date", "")) or "",
                "probation_end_date": parse_date(rapporto.get("probation_end_date", "")) or "",
                "weekly_working_hours": rapporto.get("weekly_working_hours", ""),
                "full_time_weekly_working_hours": rapporto.get(
                    "full_time_weekly_working_hours", ""
                ),
                "supervisor_id": _id_riferimento(rapporto.get("supervisor")),
                "office_id": _id_riferimento(rapporto.get("office")),
                "legal_entity_id": _id_riferimento(rapporto.get("legal_entity")),
                "subcompany_id": _id_riferimento(rapporto.get("sub_company")),
                "department_id": unita.get("department", ""),
                "team_id": unita.get("team", ""),
                "job_id": _id_riferimento(rapporto.get("job")),
                "cost_center_ids": json.dumps(
                    [_id_riferimento(c) for c in (rapporto.get("cost_centers") or [])]
                ),
                "termination_date": parse_date(cessazione.get("termination_date", "")) or "",
                "termination_last_working_date": parse_date(cessazione.get("last_working_date", ""))
                or "",
                "terminated_at": parse_date(cessazione.get("terminated_at", "")) or "",
                "termination_type": tipo_cessazione_v1(cessazione.get("type")),
                "termination_type_api": (cessazione.get("type") or "").strip(),
                "termination_reason": (cessazione.get("reason") or "").strip(),
                "created_at": parse_date(rapporto.get("created_at", "")) or "",
                "updated_at": parse_date(rapporto.get("updated_at", "")) or "",
            }
        )

    df = pd.DataFrame(righe)
    if df.empty:
        return df




    for colonna in (
        "employee_id",
        "supervisor_id",
        "office_id",
        "legal_entity_id",
        "subcompany_id",
        "department_id",
        "team_id",
    ):
        try:
            df[colonna] = pd.to_numeric(df[colonna].replace("", None), errors="raise").astype(
                "Int64"
            )
        except (ValueError, TypeError):
            log.warning(f"employments: {colonna} is not numeric, kept as text")

    df.sort_values(["employee_id", "employment_start_date"], inplace=True)
    persone = df["employee_id"].nunique()
    tipi = df[df["termination_type"] != ""]["termination_type"].value_counts().to_dict()
    log.info(f"Employments: {len(df)} records for {persone} persons")
    log.info(f"  Terminations by type: {tipi}")
    return df





def build_org_chart(employees_df: pd.DataFrame) -> dict:
    ""













    log.info("Phase 2: Building org-chart.json...")

    tree = defaultdict(list)
    tops = []


    for _, row in employees_df.iterrows():
        manager = row["manager_name"]
        emp_info = {
            "name": row["name"],
            "email": row["email"],
            "position": row["position"],
            "department": row["department"],
            "team": row["team"],
            "status": row["status"],
            "subcompany": row["subcompany"],
        }

        if not manager or manager.lower() in ("none", ""):
            tops.append(emp_info)
        else:
            tree[manager].append(emp_info)


    for manager in tree:
        tree[manager].sort(key=lambda x: x["name"])


    active_only = employees_df[employees_df["status"] == "active"]
    manager_names = set(active_only["manager_name"].dropna())
    manager_names.discard("")


    span_of_control = {}
    for mgr in manager_names:
        reports = [r for r in tree.get(mgr, []) if r["status"] == "active"]
        span_of_control[mgr] = len(reports)

    stats = {
        "total_employees": len(employees_df),
        "active_employees": len(active_only),
        "unique_managers": len(manager_names),
        "top_level": len(tops),
        "avg_span_of_control": round(
            sum(span_of_control.values()) / max(len(span_of_control), 1), 1
        ),
        "max_span_of_control": max(span_of_control.values()) if span_of_control else 0,
        "widest_manager": max(span_of_control, key=span_of_control.get) if span_of_control else "",
        "span_of_control": dict(sorted(span_of_control.items(), key=lambda x: -x[1])),
    }

    org_chart = {
        "tree": dict(tree),
        "tops": tops,
        "stats": stats,
    }

    log.info(f"Org chart: {len(tree)} managers, {len(tops)} top-level")
    log.info(f"  Active employees: {stats['active_employees']}")
    log.info(f"  Avg span of control: {stats['avg_span_of_control']}")

    return org_chart





def build_contacts(employees_df: pd.DataFrame) -> pd.DataFrame:
    ""




    log.info("Phase 3: Building contacts-personio.parquet...")

    rows = []
    for _, row in employees_df.iterrows():
        email = row["email"]
        if not email or "@" not in email:
            continue

        is_active = row["status"] == "active"

        rows.append(
            {
                "name": row["name"],
                "email": email,
                "department": row["department"],
                "position": row["position"],
                "team": row["team"],
                "subcompany": row["subcompany"],
                "hire_date": row["hire_date"],
                "status": row["status"],
                "is_active": is_active,
                "office": row["office"],
                "manager_name": row["manager_name"],
            }
        )

    df = pd.DataFrame(rows)
    df.sort_values("name", inplace=True)

    active = df["is_active"].sum()
    log.info(f"Contacts: {len(df)} with email ({active} active, {len(df) - active} inactive)")

    return df





def build_summary(
    employees_df: pd.DataFrame, contacts_df: pd.DataFrame, org_chart: dict, absences: list[dict]
) -> dict:
    ""
    log.info("Phase 4: Building summary...")


    status_counts = employees_df["status"].value_counts().to_dict()


    subco_counts = employees_df["subcompany"].value_counts().to_dict()


    dept_counts = (
        employees_df[employees_df["department"] != ""]["department"].value_counts().to_dict()
    )


    office_counts = employees_df["office"].value_counts().to_dict()


    emp_type_counts = employees_df["employment_type"].value_counts().to_dict()


    team_counts = employees_df[employees_df["team"] != ""]["team"].value_counts().to_dict()


    hire_dates = [d for d in employees_df["hire_date"] if d]
    hire_range = {
        "min": min(hire_dates) if hire_dates else "",
        "max": max(hire_dates) if hire_dates else "",
    }


    hire_years = Counter()
    for d in hire_dates:
        if d:
            hire_years[d[:4]] += 1


    gender_counts = employees_df[employees_df["gender"] != ""]["gender"].value_counts().to_dict()


    terminated = employees_df[employees_df["status"] == "terminated"]
    termination_reasons = (
        terminated[terminated["termination_reason"] != ""]["termination_reason"]
        .value_counts()
        .to_dict()
    )


    absence_summary = {}
    if absences:
        absence_types = Counter()
        total_days = 0
        for a in absences:
            attrs = a.get("attributes", {})
            ttype = attrs.get("time_off_type", {}).get("attributes", {}).get("name", "Unknown")
            days = attrs.get("days_count", 0) or 0
            absence_types[ttype] += 1
            total_days += days
        absence_summary = {
            "total_requests": len(absences),
            "total_days": total_days,
            "by_type": dict(absence_types.most_common()),
        }


    active = employees_df[employees_df["status"] == "active"]

    summary = {
        "generated": datetime.now(UTC).isoformat(),
        "pipeline_version": "personio-enrich-v1",
        "totals": {
            "employees": len(employees_df),
            "active": int(status_counts.get("active", 0)),
            "terminated": int(status_counts.get("terminated", 0)),
            "inactive": int(status_counts.get("inactive", 0)),
            "contacts_with_email": len(contacts_df),
            "unique_managers": org_chart["stats"]["unique_managers"],
        },
        "status_distribution": status_counts,
        "subcompany_distribution": subco_counts,
        "department_distribution": dept_counts,
        "team_distribution": team_counts,
        "office_distribution": office_counts,
        "employment_type_distribution": emp_type_counts,
        "gender_distribution": gender_counts,
        "hire_date_range": hire_range,
        "hire_year_distribution": dict(sorted(hire_years.items(), reverse=True)),
        "termination_reasons": termination_reasons,
        "org_chart_stats": org_chart["stats"],
        "absence_summary": absence_summary,
        "active_snapshot": {
            "total": len(active),
            "by_subcompany": active["subcompany"].value_counts().to_dict(),
            "by_department": active[active["department"] != ""]["department"]
            .value_counts()
            .to_dict(),
            "by_office": active["office"].value_counts().to_dict(),
        },
    }

    return summary




STEP_NAMES = ["employees", "employments", "org_chart", "contacts", "summary"]



STEP_CHE_USANO_EMPLOYEES = ("employees", "org_chart", "contacts", "summary")


def main():
    parser = argparse.ArgumentParser(description="Personio enrichment pipeline — SBK L1")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    parser.add_argument(
        "--step", default=None, choices=STEP_NAMES, help="Run single step (default: all)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not EMPLOYEES_FILE.exists():
        log.error(f"Employees file not found: {EMPLOYEES_FILE}")
        sys.exit(1)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


    raw_employees = load_employees()
    absences = load_absences()

    if not raw_employees:
        log.error("No employees found in raw file.")
        sys.exit(1)

    steps_to_run = [args.step] if args.step else STEP_NAMES



    schema = load_attribute_schema()
    raw_per_id = load_employees_raw()

    employees_df = None
    contacts_df = None
    org_chart = None


    if any(s in steps_to_run for s in STEP_CHE_USANO_EMPLOYEES):
        employees_df = build_employees(raw_employees, schema, raw_per_id)
        if "employees" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "employees.parquet"
            safe_write_parquet(employees_df, out, index=False)
            log.info(f"  Saved → {out}")


    employments_df = None
    if "employments" in steps_to_run:
        employments_records = load_employments()
        if employments_records:
            employments_df = build_employments(employments_records)
            if not args.dry_run and not employments_df.empty:
                out = PROCESSED_DIR / "employments.parquet"
                safe_write_parquet(employments_df, out, index=False)
                log.info(f"  Saved → {out}")


    if "org_chart" in steps_to_run or "summary" in steps_to_run:
        if employees_df is None:
            employees_df = build_employees(raw_employees, schema, raw_per_id)
        org_chart = build_org_chart(employees_df)
        if "org_chart" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "org-chart.json"
            out.write_text(json.dumps(org_chart, indent=2, ensure_ascii=False, default=str))
            log.info(f"  Saved → {out}")


    if "contacts" in steps_to_run or "summary" in steps_to_run:
        if employees_df is None:
            employees_df = build_employees(raw_employees, schema, raw_per_id)
        contacts_df = build_contacts(employees_df)
        if "contacts" in steps_to_run and not args.dry_run:
            out = PROCESSED_DIR / "contacts-personio.parquet"
            safe_write_parquet(contacts_df, out, index=False)
            log.info(f"  Saved → {out}")


    if "summary" in steps_to_run:
        if employees_df is None:
            employees_df = build_employees(raw_employees, schema, raw_per_id)
        if contacts_df is None:
            contacts_df = build_contacts(employees_df)
        if org_chart is None:
            org_chart = build_org_chart(employees_df)

        summary = build_summary(employees_df, contacts_df, org_chart, absences)

        if args.dry_run:
            log.info("\n=== DRY RUN — Summary ===")
            log.info(json.dumps(summary, indent=2))
        else:
            out = PROCESSED_DIR / "_personio_summary.json"
            out.write_text(json.dumps(summary, indent=2, default=str))
            log.info(f"  Saved → {out}")


    log.info("\n" + "=" * 60)
    log.info("PERSONIO ENRICHMENT COMPLETE")
    log.info("=" * 60)
    if employees_df is not None:
        active = len(employees_df[employees_df["status"] == "active"])
        log.info(f"  Employees:  {len(employees_df)} ({active} active)")
    if employments_df is not None:
        log.info(f"  Employments: {len(employments_df)} records")
    if org_chart is not None:
        log.info(f"  Org chart:  {len(org_chart['tree'])} managers")
    if contacts_df is not None:
        log.info(f"  Contacts:   {len(contacts_df)} with email")
    if not args.dry_run:
        log.info(f"\n  Output: {PROCESSED_DIR}")


        try:
            from event_bus import EventBus

            EventBus.emit("personio", "l1")
        except Exception as e:
            log.warning(f"EventBus emit failed: {e}")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l1-personio-enrich", source="personio-l1", stage="l1")
def run():
    main()


if __name__ == "__main__":
    run()
