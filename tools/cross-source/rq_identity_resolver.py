""











from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("rq.resolver")


_EMAIL_BLOCKLIST_PREFIXES = frozenset(
    {
        "noreply@",
        "no-reply@",
        "donotreply@",
        "do-not-reply@",
        "info@",
        "admin@",
        "support@",
        "hello@",
        "contact@",
        "notifications@",
        "mailer-daemon@",
        "postmaster@",
    }
)


class IdentityResolver:
    ""

    def __init__(self, cm_path: Path, name_matcher=None):
        ""





        self._email_to_pid: dict[str, str] = {}
        self._name_to_pid: dict[str, str] = {}
        self._lastname_to_pid: dict[str, str] = {}
        self._name_matcher = name_matcher

        if not cm_path.exists():
            log.warning("contacts-merged not found at %s", cm_path)
            return

        cm = pd.read_parquet(cm_path, columns=["person_id", "name", "email", "all_emails"])


        for _, row in cm.iterrows():
            pid = row["person_id"]
            if pd.notna(row.get("email")):
                email = str(row["email"]).lower().strip()
                if email and not self._is_blocklisted(email):
                    self._email_to_pid[email] = pid
            all_emails = row.get("all_emails")
            if pd.notna(all_emails):
                if isinstance(all_emails, str):
                    try:
                        all_emails = json.loads(all_emails)
                    except (ValueError, TypeError):
                        all_emails = [all_emails]
                if isinstance(all_emails, list):
                    for e in all_emails:
                        email = str(e).lower().strip()
                        if email and not self._is_blocklisted(email):
                            self._email_to_pid[email] = pid


            if pd.notna(row.get("name")):
                name = str(row["name"]).strip()
                if name and name not in self._name_to_pid:
                    self._name_to_pid[name] = pid


        lastname_counts: dict[str, int] = {}
        lastname_map: dict[str, str] = {}
        for name_key, pid_val in self._name_to_pid.items():
            parts = name_key.strip().split()
            if len(parts) >= 2:
                last = parts[-1]
                lastname_counts[last] = lastname_counts.get(last, 0) + 1
                lastname_map[last] = pid_val
        self._lastname_to_pid = {
            k: v for k, v in lastname_map.items() if lastname_counts.get(k, 0) == 1
        }

        log.info(
            "IdentityResolver built: %d emails, %d names, %d unique lastnames",
            len(self._email_to_pid),
            len(self._name_to_pid),
            len(self._lastname_to_pid),
        )

    @staticmethod
    def _is_blocklisted(email: str) -> bool:
        ""
        return any(email.startswith(prefix) for prefix in _EMAIL_BLOCKLIST_PREFIXES)

    def resolve(self, identifier: str) -> str | None:
        ""









        if not identifier or not identifier.strip():
            return None

        identifier = identifier.strip()


        if identifier.startswith("p_"):
            return identifier


        if "@" in identifier:
            email_lower = identifier.lower()
            if self._is_blocklisted(email_lower):
                return None
            return self._email_to_pid.get(email_lower)


        pid = self._name_to_pid.get(identifier)
        if pid:
            return pid


        parts = identifier.split()
        if len(parts) >= 2:
            last = parts[-1]
            pid = self._lastname_to_pid.get(last)
            if pid:
                return pid


        if self._name_matcher:
            match = self._name_matcher.match(identifier)
            if match.resolved:
                return match.person_id

        return None

    def resolve_batch(self, identifiers) -> dict[str, str | None]:
        ""
        return {ident: self.resolve(ident) for ident in identifiers}

    @property
    def stats(self) -> dict:
        ""
        return {
            "email_count": len(self._email_to_pid),
            "name_count": len(self._name_to_pid),
            "lastname_count": len(self._lastname_to_pid),
            "has_matcher": self._name_matcher is not None,
        }
