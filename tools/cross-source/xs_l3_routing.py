#!/usr/bin/env python3
""

















from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("sbk-routing")




DEAL_KEYWORDS = re.compile(
    r"\b("
    r"term\s*sheet|valuation|investment|equity|cap\s*table|commitment|"
    r"round|fundrais|serie[s]?\s*[abc]|bridge|convertible|"
    r"acquisition|merger|m&a|offer|counteroffer|binding|"
    r"revenue|burn\s*rate|arr|mrr|ebitda|runway|"
    r"salary|bonus|vesting|stock\s*option|"
    r"nda|confidential|legal\s*advice|legal|lawsuit|"
    r"due\s*diligence|closing|signing|exclusivity|"
    r"LOI|letter\s*of\s*intent|MOU|memorandum"
    r")\b",
    re.IGNORECASE,
)


# Your own organisations' domains ("organisations.domains" in sbk.config.json). Empty by default.
try:
    from sbk_config import INTERNAL_DOMAINS
except ImportError:  # imported without tools/ on sys.path
    INTERNAL_DOMAINS: set[str] = set()


@dataclass
class RoutingDecision:
    ""

    provider: str
    tier: str
    reason: str
    score: int


@dataclass
class RoutingStats:
    ""

    total: int = 0
    quality: int = 0
    economy: int = 0
    reasons: dict = field(default_factory=dict)

    def record(self, decision: RoutingDecision):
        self.total += 1
        if decision.tier == "quality":
            self.quality += 1
        else:
            self.economy += 1
        self.reasons[decision.reason] = self.reasons.get(decision.reason, 0) + 1


class SmartRouter:
    ""










    def __init__(
        self,
        quality_provider: str = "anthropic",
        economy_provider: str = "deepseek",
        score_threshold: float = 60.0,
    ):
        self.quality_provider = quality_provider
        self.economy_provider = economy_provider
        self.score_threshold = score_threshold
        self.stats = RoutingStats()


        self._contact_scores: dict[str, float] | None = None
        self._network_tiers: dict[str, str] | None = None
        self._investor_emails: set[str] | None = None

    def _load_lookups(self):
        ""
        if self._contact_scores is not None:
            return

        self._contact_scores = {}
        self._network_tiers = {}
        self._investor_emails = set()


        try:
            import pandas as pd

            from sbk_config import ENRICHED_DIR

            contacts_path = ENRICHED_DIR / "contacts-merged.parquet"
            if contacts_path.exists():
                df = pd.read_parquet(contacts_path, columns=["email", "name", "score", "person_id"])
                for _, row in df.iterrows():
                    email = str(row.get("email", "")).strip().lower()
                    score = float(row.get("score", 0) or 0)
                    if email and "@" in email:
                        self._contact_scores[email] = score
                log.debug(f"Loaded {len(self._contact_scores)} contact scores")
        except Exception as e:
            log.warning(f"Failed to load contact scores: {e}")


        try:
            project_root = Path(__file__).resolve().parent.parent.parent
            index_path = project_root / "sbk" / "network" / "_index.md"
            if index_path.exists():
                self._parse_network_index(index_path.read_text())
                log.debug(
                    f"Loaded {len(self._network_tiers)} network tier assignments, "
                    f"{len(self._investor_emails)} investor names"
                )
        except Exception as e:
            log.warning(f"Failed to load network index: {e}")

    def _parse_network_index(self, content: str):
        ""
        current_section = ""
        current_tier = ""

        for line in content.split("\n"):
            line_stripped = line.strip()


            if "Tier 1" in line_stripped and line_stripped.startswith("#"):
                current_tier = "tier_1"
                current_section = "tier"
            elif "Tier 2" in line_stripped and line_stripped.startswith("#"):
                current_tier = "tier_2"
                current_section = "tier"
            elif "Tier 3" in line_stripped and line_stripped.startswith("#"):
                current_tier = "tier_3"
                current_section = "tier"
            elif "Investor" in line_stripped:
                current_section = "investor"
            elif line_stripped.startswith("###") or line_stripped.startswith("## "):
                current_section = ""
                current_tier = ""


            if not line_stripped.startswith("|") or line_stripped.startswith("|--"):
                continue

            cols = [c.strip() for c in line_stripped.split("|")]
            if len(cols) < 3:
                continue

            name = cols[1].strip()
            if not name or name.lower() in ("persona", "nome", "name", "---"):
                continue


            name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", name)
            name = re.sub(r"\s*\([^)]*\)", "", name)
            name_lower = name.strip().lower()

            if not name_lower:
                continue

            if current_section == "tier" and current_tier:
                self._network_tiers[name_lower] = current_tier

            if current_section == "investor":
                self._investor_emails.add(name_lower)

    def route(self, doc: dict) -> str:
        ""







        decision = self.analyze(doc)
        self.stats.record(decision)
        return decision.provider

    def analyze(self, doc: dict) -> RoutingDecision:
        ""
        self._load_lookups()

        source = doc.get("source", "")
        title = doc.get("title", "").lower()
        text = doc.get("text", "")
        participants = doc.get("participants", "").lower()


        if source in ("plaud", "tactiq", "attio_call", "voice_memo"):
            return RoutingDecision(
                provider=self.quality_provider,
                tier="quality",
                reason="meeting_transcript",
                score=80,
            )


        sender = ""
        if "->" in participants:
            sender = participants.split("->")[0].strip()
        elif participants:
            sender = participants.split(",")[0].strip()

        sender_domain = sender.split("@")[1] if "@" in sender else ""


        sender_name = self._resolve_name_from_email(sender) if "@" in sender else sender
        if sender_name:
            tier = self._network_tiers.get(sender_name.lower(), "")
            if tier in ("tier_1", "tier_2"):
                return RoutingDecision(
                    provider=self.quality_provider,
                    tier="quality",
                    reason=f"network_{tier}",
                    score=95 if tier == "tier_1" else 85,
                )


        if sender_name and sender_name.lower() in self._investor_emails:
            return RoutingDecision(
                provider=self.quality_provider,
                tier="quality",
                reason="investor_contact",
                score=90,
            )

        for inv_name in self._investor_emails:
            if inv_name in participants:
                return RoutingDecision(
                    provider=self.quality_provider,
                    tier="quality",
                    reason="investor_in_thread",
                    score=85,
                )


        search_text = title + " " + text[:500].lower()
        if DEAL_KEYWORDS.search(search_text):
            return RoutingDecision(
                provider=self.quality_provider,
                tier="quality",
                reason="deal_legal_keywords",
                score=80,
            )


        if sender and "@" in sender:
            score = self._contact_scores.get(sender, 0)
            if score >= self.score_threshold:
                return RoutingDecision(
                    provider=self.quality_provider,
                    tier="quality",
                    reason=f"high_score_{score:.0f}",
                    score=int(score),
                )


        if sender_name:
            tier = self._network_tiers.get(sender_name.lower(), "")
            if tier == "tier_3":
                return RoutingDecision(
                    provider=self.quality_provider,
                    tier="quality",
                    reason="network_tier_3",
                    score=70,
                )


        if (
            source == "email"
            and len(text) > 10_000
            and sender_domain
            and sender_domain not in INTERNAL_DOMAINS
        ):
            return RoutingDecision(
                provider=self.quality_provider,
                tier="quality",
                reason="long_external_email",
                score=60,
            )


        return RoutingDecision(
            provider=self.economy_provider,
            tier="economy",
            reason="routine",
            score=20,
        )

    def _resolve_name_from_email(self, email: str) -> str:
        ""
        if not email or "@" not in email:
            return ""


        prefix = email.split("@")[0]

        name = re.sub(r"[._]", " ", prefix).strip()
        return name

    def get_stats(self) -> dict:
        ""
        return {
            "total": self.stats.total,
            "quality": self.stats.quality,
            "economy": self.stats.economy,
            "quality_pct": (
                round(100 * self.stats.quality / self.stats.total, 1) if self.stats.total > 0 else 0
            ),
            "economy_pct": (
                round(100 * self.stats.economy / self.stats.total, 1) if self.stats.total > 0 else 0
            ),
            "reasons": dict(self.stats.reasons),
            "quality_provider": self.quality_provider,
            "economy_provider": self.economy_provider,
        }

    def log_stats(self):
        ""
        s = self.get_stats()
        log.info(
            f"Smart routing: {s['total']} docs → "
            f"{s['quality']} quality ({s['quality_pct']}%) + "
            f"{s['economy']} economy ({s['economy_pct']}%)"
        )
        for reason, count in sorted(s["reasons"].items(), key=lambda x: -x[1]):
            log.info(f"  {reason}: {count}")
