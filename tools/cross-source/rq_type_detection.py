""








from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from pipeline_decorator import PermanentAPIError

from sbk_config import OWN_NAMES_NORMALIZED, OWNER_LABEL, OWNER_NAME  # noqa: E402

log = logging.getLogger("rq.typing")



SONNET_MODEL = "claude-sonnet-4-5-20250929"
HAIKU_MODEL = "claude-haiku-4-5-20251001"



RELATIONSHIP_TYPES = {
    "colleague_team": {"label": "Team colleague", "half_life": 14},
    "colleague_project": {"label": "Project colleague", "half_life": 7},
    "direct_report": {"label": "Direct report", "half_life": 14},
    "manager": {"label": "Manager", "half_life": 14},
    "vendor": {"label": "Consultant/vendor", "half_life": 30},
    "investor": {"label": "Investor", "half_life": 60},
    "business_partner": {"label": "Business partner", "half_life": 30},
    "professional_friend": {"label": "Professional friend", "half_life": 90},
    "family_personal": {"label": "Family/personal", "half_life": 180},
    "acquaintance": {"label": "Occasional contact", "half_life": 30},
    "introduced": {"label": "Introduced by a third party", "half_life": 30},
    "ex_employee": {"label": "Former employee", "half_life": 60},
}

VALID_TYPES = set(RELATIONSHIP_TYPES.keys())


MAX_INTERAZIONI_OCCASIONALE = 2


def classify_confidence(score: float) -> str:
    ""
    if score >= 0.85:
        return "certain"
    if score >= 0.60:
        return "probable"
    return "unverified"


def get_type_label(type_code: str) -> str:
    ""
    info = RELATIONSHIP_TYPES.get(type_code)
    return info["label"] if info else type_code


def get_type_half_life(type_code: str) -> int:
    ""
    info = RELATIONSHIP_TYPES.get(type_code)
    return info["half_life"] if info else 30




DOCUSIGN_TYPE_HINTS = {
    "EMPLOYMENT": "colleague",
    "INVESTMENT": "investor",
    "NDA": None,


    "SERVICE": "business_partner",
    "LOGISTICS": "vendor",
    "PRODUCTION": "vendor",
    "OTHER": None,
}


def extract_docusign_types(docusign_dir: Path) -> dict[str, list[str]]:
    ""



    try:
        import pandas as pd

        parquet_file = docusign_dir / "contacts-docusign.parquet"
        if not parquet_file.exists():
            log.warning("DocuSign contacts not found: %s", parquet_file)
            return {}

        df = pd.read_parquet(parquet_file)


        if "email" not in df.columns or "contract_types" not in df.columns:
            return {}


        if "is_company" in df.columns:
            df = df[~df["is_company"].fillna(False).astype(bool)]

        df = df[df["email"].notna() & (df["email"].str.strip() != "")]

        result: dict[str, list[str]] = {}
        for _, row in df.iterrows():
            email = str(row["email"]).strip().lower()
            ct = str(row.get("contract_types", "")).strip()
            if not email or not ct or ct == "nan":
                continue
            types = [t.strip().upper() for t in ct.split(",") if t.strip()]
            if types:
                result[email] = types
        return result
    except Exception as exc:
        log.warning("Failed to load DocuSign types: %s", exc)
        return {}


SENIORITY_PATTERNS: list[tuple[int, list[str]]] = [
    (5, ["ceo", "cfo", "cto", "coo", "ctpo", "cpo", "c-level", "chief"]),
    (4, ["vp", "vice president", "director", "head of"]),
    (3, ["manager", "lead", "principal"]),
    (2, ["senior", "sr."]),
    (1, ["junior", "jr.", "intern", "trainee"]),
]


def _classify_seniority(position: str) -> int:
    ""
    pos_lower = position.lower().strip()
    if not pos_lower:
        return 1
    for tier, keywords in SENIORITY_PATTERNS:
        for kw in keywords:
            if kw in pos_lower:
                return tier
    return 1





USCITE_OSTILI = frozenset({"fired", "irrevocable-suspension", "court-settlement"})


def extract_personio_enrichment(personio_dir: Path) -> dict[str, dict]:
    ""




    try:
        import pandas as pd

        parquet_file = personio_dir / "processed" / "employees.parquet"
        if not parquet_file.exists():
            log.warning("Personio employees.parquet not found: %s", parquet_file)
            return {}

        df = pd.read_parquet(parquet_file)
        if "email" not in df.columns:
            return {}

        from datetime import date

        today = date.today()
        result: dict[str, dict] = {}

        for _, row in df.iterrows():
            email = str(row.get("email", "")).strip().lower()
            if not email or email == "nan":
                continue

            position = str(row.get("position", ""))
            if position == "nan":
                position = ""
            seniority_tier = _classify_seniority(position)

            termination_type = row.get("termination_type")
            if termination_type is not None and str(termination_type) != "nan":
                termination_type = str(termination_type).strip().lower()
            else:
                termination_type = None

            termination_reason = row.get("termination_reason")
            if termination_reason is not None and str(termination_reason) != "nan":
                termination_reason = str(termination_reason).strip()
            else:
                termination_reason = None


            tenure_months = None
            hire_date = row.get("hire_date")
            term_date = row.get("termination_date") or row.get("end_date")
            try:
                if hire_date is not None and str(hire_date) != "nan":
                    hire_dt = pd.Timestamp(hire_date).date()
                    if term_date is not None and str(term_date) != "nan":
                        end_dt = pd.Timestamp(term_date).date()
                    else:
                        end_dt = today
                    tenure_months = max(
                        0, (end_dt.year - hire_dt.year) * 12 + end_dt.month - hire_dt.month
                    )
            except Exception:
                pass

            employment_type = str(row.get("employment_type", ""))
            if employment_type == "nan":
                employment_type = ""

            department = str(row.get("department", ""))
            if department == "nan":
                department = ""

            result[email] = {
                "seniority_tier": seniority_tier,
                "termination_type": termination_type,
                "termination_reason": termination_reason,
                "tenure_months": tenure_months,
                "employment_type": employment_type,
                "position": position,
                "department": department,
            }

        _arricchisci_con_rapporti(result, personio_dir, df)
        return result
    except Exception as exc:
        log.warning("Failed to load Personio enrichment: %s", exc)
        return {}


def _arricchisci_con_rapporti(result: dict[str, dict], personio_dir: Path, df_employees) -> None:
    ""












    percorso = personio_dir / "processed" / "employments.parquet"
    if not percorso.exists():
        return
    try:
        import pandas as pd

        emp = pd.read_parquet(percorso)
        if "employee_id" not in emp.columns or "employee_id" not in df_employees.columns:
            return
        email_per_id = {
            row["employee_id"]: str(row.get("email", "")).strip().lower()
            for _, row in df_employees.iterrows()
            if str(row.get("email", "")).strip()
        }
        aggiunti = 0
        for _, row in emp.iterrows():
            email = email_per_id.get(row.get("employee_id"))
            if not email or email not in result:
                continue
            voce = result[email]
            for colonna, chiave in (
                ("termination_last_working_date", "last_working_date"),
                ("employment_start_date", "contract_start_date"),
                ("employment_end_date", "contract_end_date"),
                ("position", "contract_position"),
            ):
                valore = row.get(colonna)
                if valore is not None and str(valore) not in ("nan", "NaT", "<NA>", ""):
                    voce[chiave] = str(valore)
            aggiunti += 1
        if aggiunti:
            log.info("Personio: %d employment records read from employments.parquet", aggiunti)
    except Exception as exc:  # noqa: BLE001 — additive: report and continue
        log.warning("employments.parquet not read (%s): keeping the base records", exc)


def compute_channel_pattern(channels: list[str]) -> str | None:
    ""



    if not channels:
        return None

    ch = set(c.lower() for c in channels)
    has_whatsapp = "whatsapp" in ch
    has_personio = "personio" in ch
    has_slack = "slack" in ch
    has_calendar = "calendar" in ch
    has_docusign = "docusign" in ch
    has_email = "email" in ch


    if len(ch) >= 5 and has_whatsapp:
        return "close_partner"


    if has_whatsapp and not has_personio and not has_slack:
        return "personal_friend"


    if has_slack and has_calendar and has_personio:
        return "colleague"


    if has_docusign and has_email and not has_personio:
        return "business_partner"


    if ch == {"linkedin"}:
        return "acquaintance"

    return None





def load_personio_index(personio_dir: Path) -> dict[str, dict]:
    ""




    flat_file = personio_dir / "employees-flat.json"
    if not flat_file.exists():
        log.warning("Personio flat file not found: %s", flat_file)
        return {}

    try:
        with open(flat_file, encoding="utf-8") as f:
            employees = json.load(f)

        index = {}
        for emp in employees:
            email = str(emp.get("email", "")).strip().lower()
            if email:
                index[email] = emp
        return index
    except Exception as exc:
        log.warning("Failed to load Personio: %s", exc)
        return {}





# Attio list-name substrings that mark fundraising/sourcing lists.
# Populate from your user config for your own workspace; empty by default.
LISTE_RACCOLTA: tuple[str, ...] = ()


DOMINI_GENERICI = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hotmail.it",
        "outlook.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.it",
        "icloud.com",
        "me.com",
        "libero.it",
        "virgilio.it",
        "tiscali.it",
        "alice.it",
        "fastwebnet.it",
        "protonmail.com",
        "proton.me",
        "aol.com",
        "linkedin.com",
    }
)

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _domini(valore) -> set[str]:
    ""
    if valore is None:
        return set()
    if not isinstance(valore, str) and hasattr(valore, "__iter__"):
        valore = " ".join(str(x) for x in valore)

    pezzi = re.split(r"[,;|\s\[\]'\"]+", str(valore).lower())
    return {p.removeprefix("www.") for p in pezzi if "." in p and "@" not in p}


def _con_tipo_investitore(colonna):
    ""

    tipo = colonna.fillna("").astype(str).str.strip()
    return ~tipo.isin(["", "None", "nan", "[]"])


def _fondi_attio(attio_dir: Path) -> tuple[set[str], set[str]]:
    ""
    import pandas as pd

    record: set[str] = set()
    for lista in sorted(attio_dir.glob("list-*.parquet")):
        if not any(pezzo in lista.stem for pezzo in LISTE_RACCOLTA):
            continue
        df = pd.read_parquet(lista, columns=None)
        if "parent_record_id" in df.columns:
            record.update(str(x) for x in df["parent_record_id"].dropna())
    domini: set[str] = set()
    aziende = attio_dir / "companies.parquet"
    if aziende.exists():
        df = pd.read_parquet(aziende)
        if "investor_type" in df.columns and "record_id" in df.columns:
            record.update(
                str(x)
                for x in df.loc[_con_tipo_investitore(df["investor_type"]), "record_id"].dropna()
            )
        if "record_id" in df.columns and "domains" in df.columns:
            for rid, valore in zip(df["record_id"], df["domains"]):
                if str(rid) in record:
                    domini |= _domini(valore)

    elaborate = attio_dir / "processed" / "companies-attio.parquet"
    if elaborate.exists():
        df = pd.read_parquet(elaborate)
        if {"investor_type", "domain"} <= set(df.columns):
            for valore in df.loc[_con_tipo_investitore(df["investor_type"]), "domain"]:
                domini |= _domini(valore)
    try:
        from sbk_config import INTERNAL_DOMAINS
    except ImportError:  # pragma: no cover
        INTERNAL_DOMAINS = set()
    domini -= DOMINI_GENERICI | {d.lower() for d in INTERNAL_DOMAINS}
    return record, domini


def load_attio_investors(attio_dir: Path) -> set[str]:
    ""








    try:
        import pandas as pd

        record, _ = _fondi_attio(attio_dir)
        persone = attio_dir / "people.parquet"
        if not record or not persone.exists():
            return set()
        df = pd.read_parquet(persone)
        if not {"company", "email_addresses"} <= set(df.columns):
            return set()
        emails: set[str] = set()
        for azienda, indirizzi in zip(df["company"], df["email_addresses"]):
            if str(azienda) in record and indirizzi is not None:
                emails.update(m.lower() for m in _RE_EMAIL.findall(str(indirizzi)))
        from sbk_config import INTERNAL_DOMAINS

        interni = {d.lower() for d in INTERNAL_DOMAINS}
        return {e for e in emails if e.rsplit("@", 1)[-1] not in interni}
    except Exception as exc:
        log.warning("Failed to load Attio investors: %s", exc)
        return set()


def load_attio_investor_domains(attio_dir: Path) -> set[str]:
    ""

    try:
        return _fondi_attio(attio_dir)[1]
    except Exception as exc:
        log.warning("Failed to load Attio investor domains: %s", exc)
        return set()





# Your full names (sbk.config.json owner, own_names), also surname first.
OWNER_NOMI_INTERI = frozenset(
    OWN_NAMES_NORMALIZED
    | ({" ".join(reversed(OWNER_NAME.lower().split()))} if len(OWNER_NAME.split()) > 1 else set())
)


def _e_owner(nome: str) -> bool:
    return " ".join(str(nome).lower().split()) in OWNER_NOMI_INTERI


def rules_based_typing(
    person_email: str,
    personio_index: dict[str, dict],
    attio_investors: set[str],
    owner_team: str | None = None,
    owner_supervisor: str | None = None,

    docusign_types: dict[str, list[str]] | None = None,
    personio_enrichment: dict[str, dict] | None = None,
    channels: list[str] | None = None,
    investor_domains: set[str] | None = None,
) -> tuple[str | None, str | None, str | None]:
    ""















    email = person_email.lower().strip()





    if email in attio_investors:
        return "investor", "probable", "Attio: works at a fund in the sourcing lists"


    ds_types = (docusign_types or {}).get(email, [])
    if "INVESTMENT" in ds_types:
        return "investor", "certain", "DocuSign INVESTMENT contract found"


    emp = personio_index.get(email)
    if emp:
        status = str(emp.get("status", "")).lower()
        if status in ("inactive", "terminated", "offboarded"):

            enrichment = (personio_enrichment or {}).get(email)
            if enrichment and enrichment.get("termination_type"):





                term_type = str(enrichment["termination_type"]).strip().lower()
                if term_type.replace("_", "-") in USCITE_OSTILI:
                    return (
                        "ex_employee",
                        "probable",
                        f"Former employee ({term_type} termination)",
                    )

                return (
                    "ex_employee",
                    "probable",
                    f"Former employee (status: {status})",
                )

            return "acquaintance", "probable", f"Former employee (status: {status})"


        emp_team = str(emp.get("team", "")).strip().lower()
        if owner_team and emp_team and emp_team == owner_team.lower():
            return "colleague_team", "certain", f"Same Personio team: {emp.get('team')}"


        emp_supervisor = str(emp.get("supervisor", "")).strip().lower()
        if emp_supervisor and _e_owner(emp_supervisor):
            return (
                "direct_report",
                "certain",
                f"Personio supervisor: {emp.get('supervisor')}",
            )


        if owner_supervisor:
            emp_first = str(emp.get("first_name", "")).strip().lower()
            emp_last = str(emp.get("last_name", "")).strip().lower()
            sup_lower = owner_supervisor.lower()
            if emp_first and emp_last and emp_first in sup_lower and emp_last in sup_lower:
                return (
                    "manager",
                    "certain",
                    f"Your supervisor matches: {emp.get('first_name')} {emp.get('last_name')}",
                )


        employment_type = str(emp.get("employment_type", "")).lower()
        if employment_type in ("external", "contractor"):
            return "vendor", "probable", f"Personio employment_type: {employment_type}"



        if status == "active":
            return (
                "colleague_project",
                "probable",
                f"Active employee in Personio (team: {emp.get('team') or 'n/a'})",
            )


    if ds_types and not emp:
        for ct in ds_types:
            hint = DOCUSIGN_TYPE_HINTS.get(ct)
            if hint == "vendor":
                return "vendor", "probable", f"DocuSign {ct} contract"
            if hint == "business_partner":
                return "business_partner", "probable", f"DocuSign {ct} contract"
            if hint == "colleague":
                return (
                    "colleague_project",
                    "probable",
                    "DocuSign EMPLOYMENT contract (not in Personio)",
                )


    dominio = email.rsplit("@", 1)[-1] if "@" in email else ""
    if dominio and not emp and dominio in (investor_domains or ()):
        return "investor", "probable", f"Domain of a fund in Attio: {dominio}"




    if channels:
        channel_hint = compute_channel_pattern(channels)
        if channel_hint:
            return channel_hint, "unverified", f"Channel hint: {', '.join(sorted(channels))}"

    return None, None, None







SYSTEM_PROMPT = (
    "You are a relationship classifier for a professional network analysis tool. "
    "Given interaction data between two professionals, classify their relationship type. "
    "Respond ONLY in valid JSON format. No additional text."
)

CLASSIFICATION_PROMPT = """Analyze the relationship between {person_a} and {person_b}.

Context:
- {person_a}: CEO at Acme (advertising/tech company)
- {person_b}: {role_b}{company_b}
- Interaction period: {first_date} to {last_date}
- Total weighted interactions: {total_interactions}
- Channels used: {channels}
- Reciprocity score: {reciprocity}

Sample interactions (most recent):
{interaction_samples}

Classify this relationship into exactly ONE of these types:
- colleague_team: Same team, daily interaction, multi-channel
- colleague_project: Intense but temporary collaboration
- direct_report: Person B reports to Person A (hierarchical)
- manager: Person B is Person A's manager
- vendor: Service provider, consultant, contractor
- investor: Financial investor, VC, angel
- business_partner: Business negotiation, contracts, joint ventures
- professional_friend: Informal, multi-topic, low but consistent frequency
- family_personal: Personal/family content, non-work
- ex_employee: Former employee, left the company
- acquaintance: Few interactions, no clear pattern
- introduced: First interaction via introduction

Also determine confidence:
- "certain": clear evidence from multiple sources (>0.85)
- "probable": reasonable inference (0.6-0.85)
- "unverified": insufficient evidence (<0.6)

Respond ONLY in JSON:
{{"type": "...", "confidence": "...", "evidence": "brief 1-sentence explanation"}}"""


def build_llm_prompt(
    person_name: str,
    person_role: str | None = None,
    person_company: str | None = None,
    first_date: str | None = None,
    last_date: str | None = None,
    total_interactions: float = 0.0,
    channels: list[str] | None = None,
    reciprocity: float = 0.0,
    interaction_samples: list[dict] | None = None,
) -> str:
    ""















    role_b = person_role or "unknown role"
    company_b = f" at {person_company}" if person_company else ""

    samples_text = ""
    if interaction_samples:
        for sample in interaction_samples[:10]:
            date = sample.get("date", "?")
            channel = sample.get("channel", "?")
            summary = str(sample.get("summary", ""))[:200]
            samples_text += f"- [{date}] ({channel}) {summary}\n"
    else:
        samples_text = "- No interaction samples available\n"

    return CLASSIFICATION_PROMPT.format(
        person_a=OWNER_LABEL,
        person_b=person_name,
        role_b=role_b,
        company_b=company_b,
        first_date=first_date or "unknown",
        last_date=last_date or "unknown",
        total_interactions=round(total_interactions, 1),
        channels=", ".join(channels or []),
        reciprocity=round(reciprocity, 2),
        interaction_samples=samples_text.strip(),
    )


def parse_llm_response(response: str) -> tuple[str, str, str]:
    ""




    try:
        text = response.strip()

        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)


        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

        data = json.loads(text)

        rel_type = str(data.get("type", "")).strip().lower()
        confidence = str(data.get("confidence", "")).strip().lower()
        evidence = str(data.get("evidence", "")).strip()


        if rel_type not in VALID_TYPES:
            log.warning("LLM returned invalid type: %s", rel_type)
            rel_type = "acquaintance"
            confidence = "unverified"


        if confidence not in ("certain", "probable", "unverified"):
            confidence = "unverified"

        return rel_type, confidence, evidence

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("Failed to parse LLM response: %s — %s", exc, response[:200])
        return "acquaintance", "unverified", "Failed to parse LLM classification"





def select_model(composite_score: float) -> str:
    ""







    if composite_score > 5.0:
        return SONNET_MODEL
    return HAIKU_MODEL


def should_escalate(confidence: str, model_used: str) -> bool:
    ""




    return confidence == "unverified" and model_used == HAIKU_MODEL





def load_golden_overrides(golden_path: Path | None = None) -> dict[str, dict]:  # noqa: F811
    ""



    if golden_path is None:

        from sbk_config import RQ_DIR

        golden_path = RQ_DIR / "golden-ranking.json"
    if not golden_path.exists():
        log.warning("golden-ranking.json not found at %s", golden_path)
        return {}
    try:
        data = json.loads(golden_path.read_text())
        overrides_section = data.get("type_overrides", {})
        overrides_list = overrides_section.get("overrides", [])
        result = {}
        for entry in overrides_list:
            name = entry.get("name", "").lower().strip()
            if name:
                result[name] = {
                    "type": entry.get("type", "unknown"),
                    "confidence": entry.get("confidence", "certain"),
                    "reason": entry.get("reason", ""),
                }
        log.info("Loaded %d golden type overrides", len(result))
        return result
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load golden overrides: %s", exc)
        return {}





def classify_relationship(
    person_email: str,
    person_name: str,
    composite_score: float,
    personio_index: dict[str, dict],
    attio_investors: set[str],
    interaction_samples: list[dict] | None = None,
    person_role: str | None = None,
    person_company: str | None = None,
    first_date: str | None = None,
    last_date: str | None = None,
    total_interactions: float = 0.0,
    channels: list[str] | None = None,
    reciprocity: float = 0.0,
    owner_team: str | None = None,
    owner_supervisor: str | None = None,
    rules_only: bool = False,
    call_llm_fn=None,

    docusign_types: dict[str, list[str]] | None = None,
    personio_enrichment: dict[str, dict] | None = None,
    investor_domains: set[str] | None = None,
    golden_overrides: dict[str, dict] | None = None,
    interaction_count: int | None = None,
) -> dict:
    ""






























    voce = (golden_overrides or {}).get(str(person_name or "").lower().strip())
    if voce and voce.get("type"):
        return {
            "type": voce["type"],
            "confidence": voce.get("confidence") or "certain",
            "evidence": f"Type set by you: {voce.get('reason') or 'golden-ranking.json'}"[:300],
            "method": "golden",
            "model_used": None,
        }


    rule_type, rule_conf, rule_evidence = rules_based_typing(
        person_email,
        personio_index,
        attio_investors,
        owner_team=owner_team,
        owner_supervisor=owner_supervisor,
        docusign_types=docusign_types,
        personio_enrichment=personio_enrichment,
        channels=channels,
        investor_domains=investor_domains,
    )

    if rule_type is not None:
        return {
            "type": rule_type,
            "confidence": rule_conf,
            "evidence": rule_evidence,
            "method": "rules",
            "model_used": None,
        }



    if interaction_count is not None and interaction_count <= MAX_INTERAZIONI_OCCASIONALE:
        return {
            "type": "acquaintance",
            "confidence": "probable",
            "evidence": f"{interaction_count} interactions across all sources",
            "method": "rules",
            "model_used": None,
        }

    if rules_only:



        return {
            "type": "unknown",
            "confidence": "unverified",
            "evidence": "No structural data, unknown type",
            "method": "rules_fallback",
            "model_used": None,
        }


    if call_llm_fn is None:
        from xs_l3_common import call_claude

        call_llm_fn = call_claude

    model = select_model(composite_score)
    prompt = build_llm_prompt(
        person_name=person_name,
        person_role=person_role,
        person_company=person_company,
        first_date=first_date,
        last_date=last_date,
        total_interactions=total_interactions,
        channels=channels,
        reciprocity=reciprocity,
        interaction_samples=interaction_samples,
    )

    try:
        response = call_llm_fn(prompt=prompt, system=SYSTEM_PROMPT, model=model)
        rel_type, confidence, evidence = parse_llm_response(response)


        if should_escalate(confidence, model):
            log.info("Escalating %s from Haiku to Sonnet (unverified)", person_name)
            response2 = call_llm_fn(prompt=prompt, system=SYSTEM_PROMPT, model=SONNET_MODEL)
            rel_type, confidence, evidence = parse_llm_response(response2)
            model = SONNET_MODEL

        return {
            "type": rel_type,
            "confidence": confidence,
            "evidence": evidence,
            "method": "llm",
            "model_used": model,
        }

    except PermanentAPIError:



        raise

    except Exception as exc:
        log.error("LLM classification failed for %s: %s", person_name, exc)
        return {


            "type": None,
            "confidence": "unverified",
            "evidence": f"LLM error: {exc}",
            "method": "llm_error",
            "model_used": model,
        }
