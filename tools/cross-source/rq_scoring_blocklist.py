""







from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("rq.blocklist")


def load_blocklist() -> dict:
    ""










    blocklist_path = Path("~/.sbk-data/rq/non-person-blocklist.json").expanduser()
    if not blocklist_path.exists():
        return {
            "email_prefixes": [],
            "email_suffixes": [],
            "name_blocklist": [],
            "domain_blocklist": [],
        }
    try:
        with open(blocklist_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load blocklist: %s", exc)
        return {
            "email_prefixes": [],
            "email_suffixes": [],
            "name_blocklist": [],
            "domain_blocklist": [],
        }


def _rumore():
    import sys

    tools = str(Path(__file__).resolve().parent.parent)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import rumore

    return rumore


def _tipi_mittenti() -> dict[str, str]:
    try:
        return _rumore().tipi_mittenti()
    except Exception:  # noqa: BLE001 - senza la tabella vale la lista, com'era
        return {}


def is_blocked(person_id_or_name: str, blocklist: dict) -> bool:
    ""














    val = person_id_or_name.lower().strip()
    if not val:
        return False



    if "@" in val:
        tipo = _tipi_mittenti().get(val)
        if tipo in _rumore().TIPI_RAPPORTO:
            return False
        if tipo in _rumore().TIPI_RUMORE:
            return True
    for prefix in blocklist.get("email_prefixes", []):
        if val.startswith(prefix.lower()):
            return True
    for suffix in blocklist.get("email_suffixes", []):
        if val.endswith(suffix.lower()):
            return True
    for name in blocklist.get("name_blocklist", []):
        if name.lower() == val:
            return True
    for domain in blocklist.get("domain_blocklist", []):
        if domain.lower() in val:
            return True

    for pattern in blocklist.get("name_patterns", []):
        if pattern.lower() in val:
            return True
    return False
