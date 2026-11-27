#!/usr/bin/env python3
"""Draft generator: writes a message to a person in your voice, using the segment they fall in (investor, client,
partner...), similar emails from the vector index, and the rules in sbk/identity/communication-playbook.md.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from xs_l3_common import (
    SBKData,
    call_claude,
    load_identity_files,
    setup_logging,
)

from sbk_config import OWN_EMAILS, VECTOR_DB_DIR, user_cfg

log = logging.getLogger("sbk-l3-draft")


# Segments a recipient can fall in, and the level-4 header that holds the rules for
# each segment in sbk/identity/communication-playbook.md. The draft looks the header
# up verbatim; tools/ai-history/ai-l3-how-you-work.py reads this constant (without
# importing this module) and asks the model to write exactly these headers.
SEGMENT_SYSTEM_SECTIONS = {
    "investors": "#### Investors",
    "clients": "#### Clients",
    "partners": "#### Partners",
    "team": "#### Team",
    "family": "#### Family / friends",
    "other": "#### Other",
}


def _lower_set(path: str) -> set[str]:
    """A list of sbk.config.json as a set of lower-case strings (empty if not set)."""
    value = user_cfg(path, []) or []
    if isinstance(value, str):
        value = [value]
    return {str(v).strip().lower() for v in value if str(v).strip()}


# Family and close friends (full names, lower case) and client e-mail domains come
# from sbk.config.json ("drafts" section); empty by default.
FAMILY_NAMES: set[str] = _lower_set("drafts.family_names")
CLIENT_DOMAINS: set[str] = _lower_set("drafts.client_domains")

# Words in a CRM stage that mark a client.
CLIENT_STAGE_KEYWORDS = {"client", "customer"}

INVESTOR_KEYWORDS = {
    "fundrais",
    "investor",
    "round",
    "valuation",
    "term sheet",
    "due diligence",
    "pitch",
    "vc",
    "venture",
    "fund",
    "series",
    "capital",
}

INVESTOR_DOMAINS = {
    "a16z.com",
    "sequoia.com",
    "accel.com",
    "indexventures.com",
    "balderton.com",
    "atomico.com",
    "northzone.com",
    "creandum.com",
    "generalcatalyst.com",
    "lightspeed.com",
    "insight-partners.com",
    "tigerglobal.com",
    "partner-ventures.example",
    "northstar-vc.example",
    "beacon-capital.example",
}


def classify_segment(
    recipient_email: str,
    data: SBKData,
) -> str:
    ""




    email_lower = recipient_email.strip().lower()
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""

    person = data.resolve_person(email_lower)


    if person and person.get("is_internal", False):
        return "team"


    from sbk_config import INTERNAL_DOMAINS

    if domain in INTERNAL_DOMAINS:
        return "team"


    name = (person.get("name", "") if person else "").lower().strip()
    if name and name in FAMILY_NAMES:
        return "family"


    if domain in INVESTOR_DOMAINS:
        return "investors"

    stage = str(person.get("attio_sourcing_stage") or "").lower() if person else ""
    if "invest" in stage:
        return "investors"

    if domain in CLIENT_DOMAINS or any(kw in stage for kw in CLIENT_STAGE_KEYWORDS):
        return "clients"

    if person:
        network_profile = ""
        if name:
            slug = name.replace(" ", "-")
            network_profile = data.network_profiles.get(slug, "")
        if network_profile:
            profile_lower = network_profile.lower()
            if any(kw in profile_lower for kw in INVESTOR_KEYWORDS):
                return "investors"


    if person:
        score = person.get("score", 0) or 0
        source_count = person.get("source_count", 0) or 0
        if score >= 30 and source_count >= 3:
            return "partners"


    return "other"





def find_similar_emails(
    query: str,
    recipient_email: str,
    n: int = 5,
) -> list[dict]:
    ""




    try:
        import lancedb
    except ImportError:
        log.debug("lancedb not installed, skipping similar email search")
        return []

    db_path = str(VECTOR_DB_DIR)
    try:
        db = lancedb.connect(db_path)
        table_names = db.list_tables()
        if "sbk_chunks" not in table_names:
            log.debug("sbk_chunks table not found in LanceDB, skipping")
            return []
        table = db.open_table("sbk_chunks")
    except Exception as e:
        log.debug(f"LanceDB not available: {e}")
        return []


    try:
        results = (
            table.search(query)
            .where("source_type = 'email'")
            .limit(n * 3)
            .to_list()
        )
    except Exception as e:
        log.debug(f"LanceDB search failed: {e}")
        return []


    sent_emails = []
    for r in results:
        participants = str(r.get("participants", "")).lower()

        is_sent = any(own in participants for own in OWN_EMAILS)
        if is_sent:
            sent_emails.append(
                {
                    "text": r.get("text", ""),
                    "subject": r.get("subject", ""),
                    "date": str(r.get("date", "")),
                    "recipients": r.get("participants", ""),
                }
            )
        if len(sent_emails) >= n:
            break

    log.info(f"Found {len(sent_emails)} similar sent emails in LanceDB")
    return sent_emails




_SECTION_END = re.compile(r"^(#{1,4}\s|---\s*$)", re.MULTILINE)


def _extract_playbook_section(playbook: str, segment: str) -> str:
    """The playbook section for `segment`: the line that starts with its header
    (case is ignored; "#### Team" does not match "#### Teams") down to the next
    header of level 1-4 or a `---` rule. Empty when the playbook has no such section."""
    header = SEGMENT_SYSTEM_SECTIONS.get(segment, "")
    if not header or not playbook:
        return ""

    m = re.search(rf"^{re.escape(header)}(?!\w)[^\n]*$", playbook, re.MULTILINE | re.IGNORECASE)
    if not m:
        return ""

    rest = playbook[m.end() :]
    end = _SECTION_END.search(rest)
    body = rest[: end.start()] if end else rest
    return (m.group(0).rstrip() + body).strip()


def build_draft_prompt(
    segment: str,
    recipient_ctx: dict,
    context: str,
    channel: str,
    tone_override: str | None,
    similar_emails: list[dict],
    identity: dict[str, str],
) -> tuple[str, str]:
    ""




    style_guide = identity.get("style_guide", "")
    playbook = identity.get("communication_playbook", "")
    playbook_section = _extract_playbook_section(playbook, segment)

    system_prompt = f"""You are drafting a message on behalf of the user. Produce a draft that matches their voice.

## Writing style
{style_guide}

## Communication rules for this segment: {segment}
{playbook_section}

## Key rules
- Follow the loaded style guide for voice, phrasing and tone.
- Keep the message natural and specific, no corporate-speak or filler.
- Channel is {channel}. Adapt length and format accordingly.
- If channel is email: use proper structure with greeting and sign-off.
- If channel is whatsapp: short, direct, conversational.
- If channel is slack: brief, @mention style, channel-appropriate."""

    if tone_override:
        system_prompt += f"\n- Override default tone: use {tone_override} tone."


    user_parts = ["## Recipient\n"]

    if recipient_ctx.get("found"):
        name = recipient_ctx.get("name", recipient_ctx.get("email", ""))
        user_parts.append(f"- Name: {name}")
        user_parts.append(f"- Email: {recipient_ctx.get('email', '')}")
        if recipient_ctx.get("organization"):
            user_parts.append(f"- Organization: {recipient_ctx['organization']}")
        if recipient_ctx.get("job_title"):
            user_parts.append(f"- Role: {recipient_ctx['job_title']}")
        if recipient_ctx.get("score"):
            user_parts.append(f"- Relationship score: {recipient_ctx['score']}")
        if recipient_ctx.get("is_internal"):
            user_parts.append("- Internal (your organisation)")
        if recipient_ctx.get("email_total_msgs"):
            user_parts.append(f"- Emails exchanged: {recipient_ctx['email_total_msgs']}")
        if recipient_ctx.get("last_contact"):
            user_parts.append(f"- Last contact: {recipient_ctx['last_contact']}")
        if recipient_ctx.get("last_thread_subject"):
            user_parts.append(
                f'- Last thread: "{recipient_ctx["last_thread_subject"]}" '
                f"({recipient_ctx.get('last_thread_date', '')})"
            )
        if recipient_ctx.get("attio_connection_strength"):
            user_parts.append(
                f"- CRM connection strength: {recipient_ctx['attio_connection_strength']}"
            )
        if recipient_ctx.get("attio_sourcing_stage"):
            user_parts.append(f"- Sourcing stage: {recipient_ctx['attio_sourcing_stage']}")
        if recipient_ctx.get("network_profile"):
            profile_excerpt = recipient_ctx["network_profile"]
            if len(profile_excerpt) > 800:
                profile_excerpt = profile_excerpt[:800] + "..."
            user_parts.append(f"\n### Network profile\n{profile_excerpt}")
    else:
        user_parts.append(f"- Email: {recipient_ctx.get('email', 'unknown')}")
        user_parts.append("- Not present in SBK (no prior data)")

    user_parts.append(f"\n## Communication segment: {segment}")
    user_parts.append(f"\n## Channel: {channel}")
    user_parts.append(f"\n## Context / purpose of the message\n{context}")


    if similar_emails:
        user_parts.append("\n## Examples of similar emails sent by the user (style reference)")
        for i, ex in enumerate(similar_emails, 1):
            user_parts.append(f"\n### Example {i}")
            if ex.get("subject"):
                user_parts.append(f"Subject: {ex['subject']}")
            if ex.get("date"):
                user_parts.append(f"Date: {ex['date']}")
            text = ex.get("text", "")
            if len(text) > 500:
                text = text[:500] + "..."
            user_parts.append(f"```\n{text}\n```")

    user_parts.append(
        "\n## Instruction\n"
        "Write the draft of the message following the user's style. "
        "Use the tone and language mix of the loaded style guide. "
        "Adapt to the indicated segment and channel. "
        "Produce ONLY the message text, no meta-comments."
    )

    user_prompt = "\n".join(user_parts)
    return system_prompt, user_prompt





def format_output(
    draft: str,
    recipient_name: str,
    recipient_email: str,
    segment: str,
    channel: str,
    similar_count: int,
    has_profile: bool,
) -> str:
    ""
    lines = [
        "== COMMUNICATION DRAFT ==",
        f"Recipient: {recipient_name} ({recipient_email}) — Segment: {segment}",
        f"Channel: {channel}",
        "---",
        "",
        draft,
        "",
        "---",
        "Note: This draft is generated by SBK. Review and adapt before sending.",
    ]

    sources = []
    if similar_count > 0:
        sources.append(f"{similar_count} similar emails found")
    if has_profile:
        sources.append("network profile")
    sources.append("communication playbook")
    sources.append("style guide")

    lines.append(f"Based on: {', '.join(sources)}")

    return "\n".join(lines)





def generate_draft(
    recipient_email: str,
    context: str,
    channel: str = "email",
    tone: str | None = None,
    dry_run: bool = False,
) -> str:
    ""



    data = SBKData()


    log.info(f"Resolving recipient: {recipient_email}")
    recipient_ctx = data.get_person_context(recipient_email)
    recipient_name = recipient_ctx.get("name", recipient_email)
    log.info(f"Recipient: {recipient_name} (found={recipient_ctx.get('found', False)})")


    segment = classify_segment(recipient_email, data)
    log.info(f"Segment: {segment}")


    similar_emails = find_similar_emails(
        query=context,
        recipient_email=recipient_email,
        n=5,
    )
    log.info(f"Similar emails found: {len(similar_emails)}")


    identity = load_identity_files()
    log.info("Identity files loaded")

    if dry_run:
        print("\n[DRY RUN] Draft generation context:")
        print(f"  Recipient: {recipient_name} ({recipient_email})")
        print(f"  Segment: {segment}")
        print(f"  Channel: {channel}")
        if tone:
            print(f"  Tone override: {tone}")
        print(f"  Context: {context}")
        print(f"  Similar emails found: {len(similar_emails)}")
        print(f"  Network profile: {'yes' if recipient_ctx.get('network_profile') else 'no'}")
        print(f"  Score: {recipient_ctx.get('score', 'N/A')}")
        print(f"  Emails exchanged: {recipient_ctx.get('email_total_msgs', 'N/A')}")
        print(f"  Last contact: {recipient_ctx.get('last_contact', 'N/A')}")
        if similar_emails:
            print("\n  Examples found:")
            for i, ex in enumerate(similar_emails, 1):
                subj = ex.get("subject", "N/A")
                print(f"    {i}. {subj} ({ex.get('date', '')})")
        return ""


    system_prompt, user_prompt = build_draft_prompt(
        segment=segment,
        recipient_ctx=recipient_ctx,
        context=context,
        channel=channel,
        tone_override=tone,
        similar_emails=similar_emails,
        identity=identity,
    )


    log.info(
        "Sending the draft request (%d characters: the recipient's profile and history, similar "
        "e-mails, your identity rules, what you asked for) to Claude through the Anthropic API with "
        "your ANTHROPIC_API_KEY",
        len(system_prompt) + len(user_prompt),
    )
    draft = call_claude(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=2048,
        temperature=0.5,
    )


    output = format_output(
        draft=draft,
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        segment=segment,
        channel=channel,
        similar_count=len(similar_emails),
        has_profile=bool(recipient_ctx.get("network_profile")),
    )

    return output





def main():
    parser = argparse.ArgumentParser(
        description="SBK L3 — Communication draft generator",
    )
    parser.add_argument(
        "--to",
        type=str,
        required=True,
        help="Recipient email address",
    )
    parser.add_argument(
        "--context",
        type=str,
        required=True,
        help="Purpose/context of the message",
    )
    parser.add_argument(
        "--channel",
        type=str,
        choices=["email", "slack", "whatsapp"],
        default="email",
        help="Communication channel (default: email)",
    )
    parser.add_argument(
        "--tone",
        type=str,
        choices=["formal", "casual", "urgent"],
        default=None,
        help="Override default tone for segment",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show assembled context without generating",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, name="sbk-l3-draft")

    log.info("SBK L3 Draft Generator starting")

    output = generate_draft(
        recipient_email=args.to,
        context=args.context,
        channel=args.channel,
        tone=args.tone,
        dry_run=args.dry_run,
    )

    if output:
        print(output)


from pipeline_decorator import pipeline_step


@pipeline_step(name="l3-draft", source="l3-draft", stage="l3")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
