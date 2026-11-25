""























from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import (
    EMAILS_DIR,
    ENRICHED_DIR,
    NOISE_EMAIL_PREFIXES,
    NOISE_PREFIXES_PER_DOMAIN,
)
from sbk_config import (
    NOISE_DOMAINS as CONFIG_NOISE_DOMAINS,
)

log = logging.getLogger("sbk-email-filter")





NOISE_DOMAINS: set[str] = CONFIG_NOISE_DOMAINS | {

    "support.example",
    "hr-vendor-2.example",
    "reply.hr-tool.example",
    "esign-vendor.example",
    "support.facebook.com",
    "facebookmail.com",
    "ats-vendor.example",
    "email.meetup.com",
    "hr-vendor.example",
    "order.eventbrite.com",
    "mail.beehiiv.com",
    "trustpilot.com",
    "ghost.io",
    "ads-vendor.example",
    "dashlane.com",
    "accounts.google.com",
    "ecommerce-vendor.example",
    "notes-vendor.example",
}




NOREPLY_PATTERNS: list[str] = [
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "do_not_reply",
    "notification",
    "notifications",
    "mailer-daemon",
    "postmaster",
    "bounce",
    "automated",
    "system@",
    "alert@",
    "digest@",
    "newsletter",
]



NOISE_SUBJECT_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^\[?backup\b",
        r"\bout of office\b",
        r"\bautomatic reply\b",
        r"\bautoreply\b",
        r"\bnewsletter\b",
        r"\bunsubscribe\b",
        r"\bweekly digest\b",
        r"\bmonthly report\b",
        r"^re:\s*re:\s*re:",
        r"\bpassword reset\b",
        r"\bverification code\b",
        r"\b2fa\b",
        r"\bsecurity alert\b",
        r"\bsign.in\b",
        r"\blogin attempt\b",
    ]
]




RELEVANCE_KEYWORDS: set[str] = {

    "deciso",
    "decided",
    "approvato",
    "approved",
    "agreed",
    "ok facciamo",
    "andiamo con",
    "let's go with",
    "confermo",
    "confirm",

    "introduce",
    "presentare",
    "conosce",
    "knows",
    "fratello",
    "brother",
    "sister",
    "sorella",
    "moglie",
    "husband",
    "marito",
    "partner",
    "collega",
    "colleague",
    "advisor",
    "consiglio",

    "invest",
    "round",
    "valuation",
    "revenue",
    "fatturato",
    "ebitda",
    "equity",
    "quota",
    "milion",
    "mln",
    "\u20ac",
    "$",
    "offer",
    "proposta",
    "term sheet",
    "cap table",
    "diluizione",
    "dilution",

    "deadline",
    "scadenza",
    "entro",
    "follow up",
    "action item",
    "todo",
    "da fare",
    "impegno",
    "commit",
    "promesso",

    "acquisizione",
    "acquisition",
    "partnership",
    "lancio",
    "launch",
    "hiring",
    "assunzione",
    "pivot",
    "strategia",
    "strategy",

    "contratto",
    "contract",
    "accordo",
    "agreement",
    "firma",
    "signing",
    "closing",
    "condizioni",
    "terms",
}



_kw_escaped = [re.escape(kw) for kw in sorted(RELEVANCE_KEYWORDS, key=len, reverse=True)]
_RELEVANCE_RE = re.compile(r"(?:" + "|".join(_kw_escaped) + r")", re.IGNORECASE)





def _extract_domain(from_addr: str) -> str:
    ""






    if not from_addr:
        return ""

    if "<" in from_addr and ">" in from_addr:
        start = from_addr.index("<") + 1
        end = from_addr.index(">")
        from_addr = from_addr[start:end]

    from_addr = re.sub(r"\s*\(.*?\)\s*", "", from_addr).strip()
    if "@" not in from_addr:
        return from_addr.lower().strip()
    return from_addr.split("@")[-1].lower().strip()


def _extract_local(from_addr: str) -> str:
    ""
    if not from_addr:
        return ""
    if "<" in from_addr and ">" in from_addr:
        start = from_addr.index("<") + 1
        end = from_addr.index(">")
        from_addr = from_addr[start:end]
    from_addr = re.sub(r"\s*\(.*?\)\s*", "", from_addr).strip()
    if "@" not in from_addr:
        return from_addr.lower().strip()
    return from_addr.split("@")[0].lower().strip()


def _rumore_del_mittente(from_addr: str) -> bool:
    ""
    try:
        import rumore
    except ImportError:  # pragma: no cover - fuori dal repo
        return False
    return rumore.e_rumore(rumore.addr_of(from_addr) or from_addr)


def _rapporto_del_mittente(from_addr: str) -> bool:
    ""
    try:
        import rumore
    except ImportError:  # pragma: no cover - fuori dal repo
        return False
    return rumore.e_rapporto(rumore.addr_of(from_addr) or from_addr)


def _layer1_noise_domain(from_addr: str) -> bool:
    ""
    domain = _extract_domain(from_addr)
    if not domain:
        return False

    if domain in NOISE_DOMAINS:
        return True

    for noise_d in NOISE_DOMAINS:
        if domain.endswith("." + noise_d):
            return True
    return False


def _layer2_noreply(from_addr: str) -> bool:
    ""
    if not from_addr:
        return False
    from_lower = from_addr.lower()
    for pattern in NOREPLY_PATTERNS:
        if pattern in from_lower:
            return True

    local = _extract_local(from_addr)
    if local in NOISE_EMAIL_PREFIXES:
        return True

    domain = _extract_domain(from_addr)
    prefixes = NOISE_PREFIXES_PER_DOMAIN.get(domain)
    if prefixes and local in prefixes:
        return True
    return False


def _layer3_subject(subject: str) -> bool:
    ""
    if not subject:
        return False
    for pattern in NOISE_SUBJECT_PATTERNS:
        if pattern.search(subject):
            return True
    return False


def _layer4_body_too_short(body: str) -> bool:
    ""
    if not body:
        return True
    return len(body.strip()) < 50


def _layer5_no_relevance(subject: str, body: str) -> bool:
    ""
    text = ""
    if subject:
        text += subject + " "
    if body:
        text += body
    if not text.strip():
        return True
    return _RELEVANCE_RE.search(text) is None


def _get_field(email: dict, field_name: str, alt_names: list[str] | None = None) -> str:
    ""
    val = email.get(field_name, "")
    if val:
        return str(val)
    if alt_names:
        for alt in alt_names:
            val = email.get(alt, "")
            if val:
                return str(val)
    return ""


def filter_emails(
    emails: list[dict],
    verbose: bool = False,
) -> tuple[list[dict], dict]:
    ""












    stats = {
        "total": len(emails),
        "layer0_rumore": 0,
        "layer1_noise_domain": 0,
        "layer2_noreply": 0,
        "layer3_subject": 0,
        "layer4_body_short": 0,
        "layer5_no_relevance": 0,
        "kept": 0,
    }

    kept = []

    for email in emails:

        from_addr = _get_field(email, "from_addr", ["from", "from_email", "sender"])


        subject = _get_field(email, "subject", ["title"])


        body = _get_field(email, "body_text", ["body", "text"])

        if not body and "utterances" in email:
            parts = []
            for u in email.get("utterances", []):
                content = u.get("content", "")
                if content:
                    parts.append(content)
            body = "\n".join(parts)


        if not from_addr and body:
            m = re.match(r"^From:\s*(.+)", body, re.MULTILINE)
            if m:
                from_addr = m.group(1).strip()



        if from_addr and _rumore_del_mittente(from_addr):
            stats["layer0_rumore"] += 1
            if verbose:
                log.debug(f"L0 rumore: {from_addr}")
            continue



        rapporto = bool(from_addr) and _rapporto_del_mittente(from_addr)


        if from_addr and not rapporto and _layer1_noise_domain(from_addr):
            stats["layer1_noise_domain"] += 1
            if verbose:
                log.debug(f"L1 noise domain: {from_addr}")
            continue


        if from_addr and not rapporto and _layer2_noreply(from_addr):
            stats["layer2_noreply"] += 1
            if verbose:
                log.debug(f"L2 noreply: {from_addr}")
            continue


        if _layer3_subject(subject):
            stats["layer3_subject"] += 1
            if verbose:
                log.debug(f"L3 subject noise: {subject[:80]}")
            continue


        if _layer4_body_too_short(body):
            stats["layer4_body_short"] += 1
            if verbose:
                log.debug(f"L4 body too short: {len(body.strip()) if body else 0} chars")
            continue


        if _layer5_no_relevance(subject, body):
            stats["layer5_no_relevance"] += 1
            if verbose:
                log.debug(f"L5 no relevance: {subject[:60] if subject else '(no subject)'}")
            continue

        kept.append(email)

    stats["kept"] = len(kept)
    total_removed = stats["total"] - stats["kept"]
    stats["total_removed"] = total_removed
    stats["removal_pct"] = (
        round(total_removed / stats["total"] * 100, 1) if stats["total"] > 0 else 0.0
    )

    return kept, stats


def print_stats(stats: dict) -> None:
    ""
    print(f"\n{'=' * 60}")
    print("EMAIL PRE-FILTER RESULTS")
    print(f"{'=' * 60}")
    print(f"  Total emails:          {stats['total']:>8,}")
    print(f"  L0 Rumore (tabella): - {stats.get('layer0_rumore', 0):>8,}")
    print(f"  L1 Noise domains:    - {stats['layer1_noise_domain']:>8,}")
    print(f"  L2 Noreply/notif:    - {stats['layer2_noreply']:>8,}")
    print(f"  L3 Subject noise:    - {stats['layer3_subject']:>8,}")
    print(f"  L4 Body too short:   - {stats['layer4_body_short']:>8,}")
    print(f"  L5 No relevance:     - {stats['layer5_no_relevance']:>8,}")
    print(f"  {'─' * 40}")
    print(f"  Total removed:       - {stats['total_removed']:>8,}  ({stats['removal_pct']}%)")
    print(f"  KEPT for extraction:   {stats['kept']:>8,}")
    print(f"{'=' * 60}")





def _load_emails_from_accounts() -> list[dict]:
    ""
    import pandas as pd

    docs = []
    if not EMAILS_DIR.exists():
        log.warning(f"Emails dir not found: {EMAILS_DIR}")
        return docs
    for account_dir in sorted(EMAILS_DIR.iterdir()):
        if not account_dir.is_dir():
            continue
        parquet_file = account_dir / "messages.parquet"
        if not parquet_file.exists():
            continue
        try:
            df = pd.read_parquet(parquet_file)
            for _, row in df.iterrows():
                docs.append(
                    {
                        "from_addr": str(row.get("from_addr", "") or ""),
                        "subject": str(row.get("subject", "") or ""),
                        "body_text": str(row.get("body_text", "") or ""),
                        "message_id": str(row.get("message_id", "") or row.get("id", "") or ""),
                        "date": str(row.get("date", "") or ""),
                        "account": account_dir.name,
                    }
                )
        except Exception as e:
            log.warning(f"Failed to load emails from {account_dir.name}: {e}")
    return docs


def _load_emails_from_enriched() -> list[dict]:
    ""
    import pandas as pd

    path = ENRICHED_DIR / "processed" / "messages-with-body.parquet"
    if not path.exists():
        log.warning(f"Enriched email file not found: {path}")
        return []

    df = pd.read_parquet(path)
    docs = []
    for _, row in df.iterrows():
        docs.append(
            {
                "from_addr": str(row.get("from_addr", "") or ""),
                "subject": str(row.get("subject", "") or ""),
                "body_text": str(row.get("body_text", "") or ""),
                "message_id": str(row.get("id", "") or ""),
                "date": str(row.get("date", "") or ""),
                "account": str(row.get("account", "") or ""),
            }
        )
    return docs


def main():
    parser = argparse.ArgumentParser(
        description="SBK Email Pre-Filter - Rule-based noise elimination"
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--source",
        choices=["accounts", "enriched"],
        default="accounts",
        help="Load from per-account parquets (accounts) or enriched file (enriched). Default: accounts",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


    if args.source == "enriched":
        log.info("Loading emails from enriched/processed/messages-with-body.parquet...")
        emails = _load_emails_from_enriched()
    else:
        log.info("Loading emails from per-account messages.parquet files...")
        emails = _load_emails_from_accounts()

    if not emails:
        log.error("No emails loaded!")
        sys.exit(1)

    log.info(f"Loaded {len(emails):,} emails total")


    kept, stats = filter_emails(emails, verbose=args.verbose)


    print_stats(stats)


    if stats["total"] > 0:
        print("\nPer-layer removal percentages (of total):")
        for layer in [
            "layer0_rumore",
            "layer1_noise_domain",
            "layer2_noreply",
            "layer3_subject",
            "layer4_body_short",
            "layer5_no_relevance",
        ]:
            pct = stats[layer] / stats["total"] * 100
            print(f"  {layer:25s}: {stats[layer]:>8,}  ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
