#!/usr/bin/env python3
"""Commitment tracker: checks the deadlines of the consolidated commitments (reminder 24 hours before, overdue),
verifies with later facts whether they were kept, expires the stale ones, and shows statistics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import COMMITMENTS_FILE, DEEP_RESPONSES_DIR, safe_write_json

log = logging.getLogger("commitment-tracker")



VALID_STATUSES = {"PENDING", "KEPT", "BROKEN", "EXPIRED", "DISMISSED"}
PRE_DEADLINE_HOURS = 24
EXPIRE_AFTER_DAYS = 30
OVERDUE_GRACE_HOURS = 0





def load_commitments() -> list[dict]:
    ""
    if not COMMITMENTS_FILE.exists():
        log.warning("Commitments file not found: %s", COMMITMENTS_FILE)
        return []
    try:
        data = json.loads(COMMITMENTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to load commitments: %s", e)
    return []


def save_commitments(commitments: list[dict]) -> None:
    ""
    safe_write_json(COMMITMENTS_FILE, commitments, backup=True)
    log.info("Saved %d commitments to %s", len(commitments), COMMITMENTS_FILE)





def check_deadlines(
    commitments: list[dict],
    dry_run: bool = False,
    notify: bool = True,
) -> dict:
    ""







    now = datetime.now(UTC).replace(tzinfo=None)
    t_plus_24h = now + timedelta(hours=PRE_DEADLINE_HOURS)

    stats = {"upcoming_notified": 0, "overdue_marked": 0, "overdue_notified": 0}
    overdue_entries = []
    upcoming_entries = []

    for c in commitments:
        if c.get("status") != "PENDING":
            continue

        deadline_str = c.get("deadline")
        if not deadline_str:
            continue

        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        cid = c.get("commitment_id", "?")

        if deadline < now:

            if not dry_run:
                c["status"] = "BROKEN"
                c["verified_at"] = datetime.now(UTC).isoformat()
                c["verification_evidence"] = "Deadline passed, no evidence of fulfillment"
            stats["overdue_marked"] += 1

            if notify and not c.get("notified_at_deadline"):
                overdue_entries.append(c)
                if not dry_run:
                    c["notified_at_deadline"] = True
                stats["overdue_notified"] += 1

            log.info(
                "OVERDUE [%s]: %s → %s: %s (deadline: %s)",
                cid,
                c.get("who", "?"),
                c.get("to_whom", "?"),
                (c.get("what") or "")[:60],
                deadline_str,
            )

        elif deadline <= t_plus_24h:

            if notify and not c.get("notified_pre_deadline"):
                upcoming_entries.append(c)
                if not dry_run:
                    c["notified_pre_deadline"] = True
                stats["upcoming_notified"] += 1

            log.info(
                "UPCOMING [%s]: %s → %s: %s (deadline: %s)",
                cid,
                c.get("who", "?"),
                c.get("to_whom", "?"),
                (c.get("what") or "")[:60],
                deadline_str,
            )


    if notify and (overdue_entries or upcoming_entries) and not dry_run:
        _notify_digest(overdue_entries, upcoming_entries)

    return stats





def verify_commitments(
    commitments: list[dict],
    dry_run: bool = False,
    max_verify: int = 20,
) -> dict:
    ""








    stats = {"verified_kept": 0, "confirmed_broken": 0, "skipped": 0, "errors": 0}


    candidates = [
        c
        for c in commitments
        if c.get("status") == "BROKEN" and not c.get("verification_evidence", "").startswith("LLM:")
    ]

    if not candidates:
        log.info("No commitments to verify")
        return stats

    log.info("Verifying %d broken commitments (max %d)", len(candidates), max_verify)
    if dry_run:
        log.info(
            "[DRY RUN] Nothing was sent to a model: --verify without --dry-run sends up to %d "
            "commitment(s), each with up to 10 later facts, to Claude through the Anthropic API",
            min(len(candidates), max_verify),
        )
        stats["skipped"] = min(len(candidates), max_verify)
        return stats

    for c in candidates[:max_verify]:
        try:
            result = _verify_single(c)
            if result is None:
                stats["skipped"] += 1
                continue

            verdict = result.get("verdict", "NO_EVIDENCE")
            confidence = result.get("confidence", 0)
            evidence = result.get("evidence", "")

            if verdict in ("KEPT", "LIKELY_KEPT") and confidence >= 0.6:
                if not dry_run:
                    c["status"] = "KEPT"
                    c["verified_at"] = datetime.now(UTC).isoformat()
                    c["verification_evidence"] = f"LLM: {evidence}"
                stats["verified_kept"] += 1
                log.info(
                    "KEPT [%s]: %s (confidence: %.2f)",
                    c.get("commitment_id", "?"),
                    evidence[:80],
                    confidence,
                )
            else:
                if not dry_run:
                    c["verification_evidence"] = f"LLM: {verdict} - {evidence}"
                stats["confirmed_broken"] += 1
                log.info("CONFIRMED BROKEN [%s]: %s", c.get("commitment_id", "?"), evidence[:80])

        except Exception as e:
            stats["errors"] += 1
            log.error("Verify error for %s: %s", c.get("commitment_id", "?"), e)

    return stats


def _verify_single(commitment: dict) -> dict | None:
    ""



    who = commitment.get("who", "")
    what = commitment.get("what", "")
    source_type = commitment.get("source_type", "")
    source_date = commitment.get("source_date", "")

    if not who or not what:
        return None


    subsequent_facts = _find_subsequent_facts(
        source_type=source_type,
        after_date=source_date,
        person=who,
        max_facts=10,
    )

    if not subsequent_facts:
        return {
            "verdict": "NO_EVIDENCE",
            "confidence": 0.5,
            "evidence": "No subsequent facts found for this person/source",
        }


    return _llm_verify(commitment, subsequent_facts)


def _find_subsequent_facts(
    source_type: str,
    after_date: str,
    person: str,
    max_facts: int = 10,
) -> list[str]:
    ""
    import re

    if not DEEP_RESPONSES_DIR.exists():
        return []

    source_dir = DEEP_RESPONSES_DIR / source_type
    if not source_dir.exists():
        return []

    facts = []
    person_lower = person.lower().strip()

    for f in sorted(source_dir.glob("*.json")):

        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        if date_match:
            file_date = date_match.group(1)
            if after_date and file_date <= after_date:
                continue

        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


        for category in ("commitment", "operational", "deal", "strategic"):
            entries = data.get(category, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                entry_text = json.dumps(entry, ensure_ascii=False)
                if person_lower in entry_text.lower():
                    context = entry.get("context", "") or entry.get("description", "") or ""
                    if context:
                        facts.append(f"[{category}] {context[:300]}")

        if len(facts) >= max_facts:
            break

    return facts[:max_facts]


def _llm_verify(commitment: dict, subsequent_facts: list[str]) -> dict:
    ""

    try:
        import anthropic  # noqa: F401 — probe installation; actual client via factory
    except ImportError:
        log.warning("anthropic package not installed, skipping LLM verification")
        return {
            "verdict": "NO_EVIDENCE",
            "confidence": 0.0,
            "evidence": "anthropic package not available",
        }

    prompt = f"""Given a promise and the subsequent facts from the same period, determine whether the promise
was kept.

Promise:
- Who: {commitment.get("who", "?")}
- To whom: {commitment.get("to_whom", "?")}
- What: {commitment.get("what", "")}
- Deadline: {commitment.get("deadline", "N/A")}
- Original context: {commitment.get("original_context", "")[:300]}

Subsequent facts (from the same person or toward the same recipient):
{chr(10).join(f"- {f}" for f in subsequent_facts)}

Reply ONLY with JSON:
{{"verdict": "KEPT" | "LIKELY_KEPT" | "NO_EVIDENCE" | "BROKEN", "confidence": 0.0-1.0, "evidence": "short description"}}

Rules:
- KEPT: clear evidence that the action was completed
- LIKELY_KEPT: strong hints but no explicit confirmation
- NO_EVIDENCE: no relevant fact found
- BROKEN: explicit evidence that the promise was not kept"""

    _CROSS_SOURCE_DIR = Path(__file__).resolve().parent.parent / "cross-source"
    if str(_CROSS_SOURCE_DIR) not in sys.path:
        sys.path.insert(0, str(_CROSS_SOURCE_DIR))
    from xs_anthropic_client import get_client

    log.info(
        "Sending commitment %s (%d characters: who, to whom, what, deadline, up to 300 characters of "
        "the original context, up to 10 later facts) to Claude through the Anthropic API with your "
        "ANTHROPIC_API_KEY to check it",
        commitment.get("commitment_id", "?"),
        len(prompt),
    )
    client = get_client()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)





def expire_stale(
    commitments: list[dict],
    dry_run: bool = False,
    days: int = EXPIRE_AFTER_DAYS,
) -> dict:
    ""



    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    stats = {"expired": 0}

    for c in commitments:
        if c.get("status") != "PENDING":
            continue
        if c.get("deadline"):
            continue

        created_str = c.get("created_at", "")
        if not created_str:
            continue

        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue

        if created < cutoff:
            if not dry_run:
                c["status"] = "EXPIRED"
                c["verified_at"] = datetime.now(UTC).isoformat()
                c["verification_evidence"] = f"No deadline, age > {days} days"
            stats["expired"] += 1
            log.info(
                "EXPIRED [%s]: %s (created: %s)",
                c.get("commitment_id", "?"),
                (c.get("what") or "")[:60],
                created_str[:10],
            )

    return stats





def _notify_digest(overdue: list[dict], upcoming: list[dict]) -> bool:
    ""
    try:
        from monitoring.slack_alerter import alert_custom
    except ImportError:
        log.warning("Cannot import slack_alerter")
        return False

    lines = []
    if overdue:
        lines.append(f":red_circle: *{len(overdue)} commitment overdue*")
        for c in overdue[:5]:
            who = c.get("who", "?")
            to_whom = c.get("to_whom", "?")
            what = (c.get("what") or "")[:120]
            lines.append(f"  - {who} -> {to_whom}: {what} (overdue {c.get('deadline', '?')})")
        if len(overdue) > 5:
            lines.append(f"  _...and {len(overdue) - 5} more_")

    if upcoming:
        lines.append(f":warning: *{len(upcoming)} due within 24h*")
        for c in upcoming[:5]:
            who = c.get("who", "?")
            to_whom = c.get("to_whom", "?")
            what = (c.get("what") or "")[:120]
            lines.append(f"  - {who} -> {to_whom}: {what} (due {c.get('deadline', '?')})")
        if len(upcoming) > 5:
            lines.append(f"  _...and {len(upcoming) - 5} more_")

    lines.append("\nSee the /commitments dashboard for details.")

    now = datetime.now(UTC)
    return alert_custom(
        title="SBK Commitment Digest",
        body="\n".join(lines),
        alert_key=f"commitment_digest:{now.strftime('%Y-%m-%d')}",
    )





def show_stats(commitments: list[dict]) -> None:
    ""
    if not commitments:
        log.info("No commitments found.")
        return

    total = len(commitments)
    by_status = {}
    by_type = {}
    by_source = {}
    with_deadline = 0

    now = datetime.now(UTC).replace(tzinfo=None)

    upcoming_7d = []
    overdue = []

    for c in commitments:
        status = c.get("status", "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1

        ctype = c.get("commitment_type", "unknown") or "unknown"
        by_type[ctype] = by_type.get(ctype, 0) + 1

        src = c.get("source_type", "unknown") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1

        if c.get("deadline"):
            with_deadline += 1
            if status == "PENDING":
                try:
                    dl = datetime.strptime(c["deadline"], "%Y-%m-%d")
                    if dl < now:
                        overdue.append(c)
                    elif dl <= now + timedelta(days=7):
                        upcoming_7d.append(c)
                except (ValueError, TypeError):
                    pass

    pct = f" ({100 * with_deadline / total:.0f}%%)" if total else ""
    log.info("Total commitments: %d", total)
    log.info("With deadline: %d%s", with_deadline, pct)

    log.info("By status:")
    for s, n in sorted(by_status.items(), key=lambda x: -x[1]):
        log.info("  %s: %d", s, n)

    log.info("By type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        log.info("  %s: %d", t, n)

    log.info("By source:")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        log.info("  %s: %d", s, n)

    if overdue:
        log.info("Overdue PENDING (%d):", len(overdue))
        for c in sorted(overdue, key=lambda x: x.get("deadline", ""))[:10]:
            log.warning(
                "  [%s] %s -> %s: %s",
                c.get("deadline"),
                c.get("who", "?"),
                c.get("to_whom", "?"),
                (c.get("what") or "")[:60],
            )

    if upcoming_7d:
        log.info("Upcoming next 7 days (%d):", len(upcoming_7d))
        for c in sorted(upcoming_7d, key=lambda x: x.get("deadline", ""))[:10]:
            log.info(
                "  [%s] %s -> %s: %s",
                c.get("deadline"),
                c.get("who", "?"),
                c.get("to_whom", "?"),
                (c.get("what") or "")[:60],
            )





def main():
    parser = argparse.ArgumentParser(description="SBK Commitment Tracker")
    parser.add_argument(
        "--check", action="store_true", help="Check deadlines, notify upcoming (T-24h) and overdue"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check broken commitments with Claude: sends each one (who, to whom, what, deadline, its "
        "context) with up to 10 later facts through the Anthropic API with your ANTHROPIC_API_KEY. "
        "Only with this flag; --all never includes it",
    )
    parser.add_argument(
        "--expire", action="store_true", help="Expire stale commitments (no deadline, >30 days)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run check + expire (verify requires --verify explicitly)",
    )
    parser.add_argument("--stats", action="store_true", help="Show commitment statistics")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview actions without modifying commitments.json"
    )
    parser.add_argument(
        "--max-verify",
        type=int,
        default=20,
        help="Max commitments to verify with LLM (default: 20)",
    )
    parser.add_argument(
        "--expire-days",
        type=int,
        default=EXPIRE_AFTER_DAYS,
        help=f"Days before expiring deadline-less commitments (default: {EXPIRE_AFTER_DAYS})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    commitments = load_commitments()
    if not commitments:
        print("No commitments found. Run xs-commitment-consolidate.py first.")
        return

    if args.stats:
        show_stats(commitments)
        return

    if not (args.check or args.verify or args.expire or args.all):
        parser.print_help()
        return

    modified = False
    total_stats = {}

    if args.check or args.all:
        log.info("Running deadline check...")
        stats = check_deadlines(commitments, dry_run=args.dry_run)
        total_stats["check"] = stats
        if stats["upcoming_notified"] or stats["overdue_marked"]:
            modified = True
        log.info(
            "Check: %d upcoming notified, %d overdue marked, %d overdue notified",
            stats["upcoming_notified"],
            stats["overdue_marked"],
            stats["overdue_notified"],
        )

    if args.expire or args.all:
        log.info("Running expiration check...")
        stats = expire_stale(commitments, dry_run=args.dry_run, days=args.expire_days)
        total_stats["expire"] = stats
        if stats["expired"]:
            modified = True
        log.info("Expire: %d expired", stats["expired"])

    if args.verify:
        log.info("Running LLM verification...")
        stats = verify_commitments(commitments, dry_run=args.dry_run, max_verify=args.max_verify)
        total_stats["verify"] = stats
        if stats["verified_kept"] or stats["confirmed_broken"]:
            modified = True
        log.info(
            "Verify: %d kept, %d confirmed broken, %d skipped, %d errors",
            stats["verified_kept"],
            stats["confirmed_broken"],
            stats["skipped"],
            stats["errors"],
        )

    if modified and not args.dry_run:
        save_commitments(commitments)


    print("\nCommitment Tracker Summary:")
    for action, stats in total_stats.items():
        parts = [f"{k}={v}" for k, v in stats.items() if v > 0]
        if parts:
            print(f"  {action}: {', '.join(parts)}")
        else:
            print(f"  {action}: no changes")

    if args.dry_run:
        print("\n[DRY RUN] No changes saved.")


if __name__ == "__main__":
    main()
