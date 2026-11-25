""









from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import pandas as pd

from sbk_config import DATA_ROOT

log = logging.getLogger("rq.manual_contacts")

KNOWLEDGE_PERSON_DIR = DATA_ROOT / "knowledge" / "entities" / "person"


def extract_manual_contacts(
    knowledge_dir: Path | None = None,
) -> pd.DataFrame:
    ""











    if knowledge_dir is None:
        knowledge_dir = KNOWLEDGE_PERSON_DIR

    if not knowledge_dir.exists():
        return pd.DataFrame()

    rows: list[dict] = []

    for jf in sorted(knowledge_dir.glob("*.json")):
        try:
            profile = json.loads(jf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        facts = profile.get("facts", [])
        if not facts:
            continue


        is_manual = any(_get_source_type(f) == "manual_input" for f in facts)
        if not is_manual:
            continue


        entity_id = profile.get("entity_id", jf.stem)
        name = profile.get("canonical_name", "")
        email = ""
        phone = ""
        company = ""
        role = ""
        emails: list[str] = []

        for fact in facts:
            attr = fact.get("attribute", "")
            value = str(fact.get("value", ""))
            if not value or value == "None":
                continue

            if attr == "identity.name" and not name:
                name = value
            elif attr == "contact.email":
                if not email:
                    email = value
                emails.append(value)
            elif attr == "contact.phone":
                phone = value
            elif attr in ("professional.company", "professional.organization"):
                company = value
            elif attr in ("professional.role", "professional.title", "professional.position"):
                role = value

        if not name:
            continue

        rows.append(
            {
                "person_id": entity_id,
                "name": name,
                "email": email,
                "phone": phone,
                "company": company,
                "role": role,
                "source": "manual",
                "source_count": 1,
                "first_seen": profile.get("created_at", ""),
                "last_seen": profile.get("updated_at", ""),
                "all_emails": json.dumps(emails) if emails else "[]",
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    log.info("Extracted %d manual contacts from Knowledge Layer", len(df))
    return df


def _get_source_type(fact: dict) -> str:
    ""
    source = fact.get("source", {})
    if isinstance(source, dict):
        return source.get("source_type", "")
    return ""
