""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/emails", tags=["emails"])
log = logging.getLogger("dashboard.emails")



_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_IDENTITY_DIR = _PROJECT_ROOT / "sbk" / "identity"
_REPLY_IDENTITY_FILES = ["style-guide.md", "communication-playbook.md"]


def _load_reply_identity() -> str:
    ""
    if not hasattr(_load_reply_identity, "_cache"):
        sections = []
        for fname in _REPLY_IDENTITY_FILES:
            fp = _IDENTITY_DIR / fname
            if fp.exists():
                try:
                    content = fp.read_text(encoding="utf-8")
                    if len(content) > 6000:
                        content = content[:6000] + "\n[... truncated ...]"
                    sections.append(f"### {fname}\n\n{content}")
                except OSError:
                    pass
        _load_reply_identity._cache = "\n\n---\n\n".join(sections)
    return _load_reply_identity._cache




_last_smart_reply_ts: float = 0.0


def _check_rate_limit() -> str | None:
    ""
    global _last_smart_reply_ts  # noqa: PLW0603
    now = time.time()
    if now - _last_smart_reply_ts < 5.0:
        return "Rate limit: max 1 smart reply request per 5 seconds."
    _last_smart_reply_ts = now
    return None





@router.get("/needs-reply")
def emails_needs_reply(
    request: Request,
    max_age_days: int = 7,
    limit: int = 50,
    account: str = "all",
):
    ""






    if limit > 200:
        limit = 200
    if max_age_days > 90:
        max_age_days = 90
    bridge = request.app.state.bridge
    data = bridge.get_emails_needing_reply(max_age_days=max_age_days, limit=limit, account=account)
    return JSONResponse(data)





class SmartReplyRequest(BaseModel):
    email_text: str = Field(..., max_length=10000)
    sender_email: str = Field(..., max_length=200)
    sender_name: str = Field("", max_length=200)
    thread_context: str = Field("", max_length=5000)
    subject: str = Field("", max_length=300)


@router.post("/smart-reply")
async def smart_reply(request: Request, body: SmartReplyRequest):
    ""




    rate_err = _check_rate_limit()
    if rate_err:
        return JSONResponse({"error": rate_err}, status_code=429)


    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=500)

    bridge = request.app.state.bridge


    person_ctx = await asyncio.to_thread(
        bridge.get_person_context_for_reply,
        body.sender_email,
        body.sender_name,
    )


    identity_ctx = _load_reply_identity()


    segment = person_ctx.get("segment", "contact")
    tier = person_ctx.get("tier", "")

    # Tone per segment. Override via user config if present.
    tone_map = {
        "team": "direct, supportive, high standards. Match the sender's language.",
        "investor": "confident, narrative-first, peer-to-peer. Match the sender's language.",
        "executive": "professional, peer-to-peer, concise. Match the sender's language.",
        "legal": "formal, precise, structured. Match the sender's language.",
        "close_contact": "warm, direct, informal but professional. Match the sender's language.",
        "contact": "professional, courteous, concise. Match the sender's language.",
    }
    tone_instruction = tone_map.get(segment, tone_map["contact"])


    interactions_summary = ""
    if person_ctx.get("recent_interactions"):
        lines = []
        for ix in person_ctx["recent_interactions"][:3]:
            lines.append(f"- {ix['date']} ({ix['type']}, {ix['direction']}): {ix['summary']}")
        interactions_summary = "\n".join(lines)


    facts_summary = ""
    if person_ctx.get("key_facts"):
        lines = []
        for f in person_ctx["key_facts"][:5]:
            lines.append(f"- {f['predicate']}: {f['value']}")
        facts_summary = "\n".join(lines)


    from sbk_config import OWNER_LABEL

    system_prompt = (
        f"You are {OWNER_LABEL} drafting a reply to an email. "
        "Write ONLY the reply text, no subject line, no greeting alternatives, no meta-commentary.\n\n"
        f"TONE: {tone_instruction}\n\n"
        "IDENTITY AND WRITING STYLE:\n"
        f"{identity_ctx}\n\n"
        "RULES:\n"
        "- Be concise: 3-8 sentences max unless the email requires detailed response\n"
        "- Match the formality level of the incoming email\n"
        "- If the email contains questions, answer them directly\n"
        "- Close with a clear next step or action when appropriate\n"
        "- Sign off with the sender-appropriate signature from the identity profile\n"
    )

    user_prompt_parts = [f"EMAIL TO REPLY TO:\nFrom: {body.sender_name} <{body.sender_email}>"]
    if body.subject:
        user_prompt_parts.append(f"Subject: {body.subject}")
    user_prompt_parts.append(f"\n{body.email_text}")

    if body.thread_context:
        user_prompt_parts.append(f"\nTHREAD CONTEXT (previous messages):\n{body.thread_context}")

    user_prompt_parts.append(f"\nRELATIONSHIP: {person_ctx.get('relationship_summary', 'Unknown')}")
    user_prompt_parts.append(f"SEGMENT: {segment}, TIER: {tier or 'unknown'}")

    if interactions_summary:
        user_prompt_parts.append(f"\nRECENT INTERACTIONS:\n{interactions_summary}")
    if facts_summary:
        user_prompt_parts.append(f"\nKEY FACTS:\n{facts_summary}")

    user_prompt_parts.append("\nDraft the reply now.")

    user_prompt = "\n".join(user_prompt_parts)


    try:
        from xs_l3_common import call_claude

        draft = await asyncio.to_thread(
            call_claude,
            prompt=user_prompt,
            system=system_prompt,
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            temperature=0.4,
        )
    except Exception as e:
        log.error("Smart reply LLM call failed: %s", e)
        return JSONResponse(
            {"error": f"LLM call failed: {type(e).__name__}"},
            status_code=500,
        )

    return JSONResponse(
        {
            "draft": draft.strip(),
            "tone": tone_instruction.split(".")[0],
            "segment": segment,
            "tier": tier,
            "person_name": person_ctx.get("name", body.sender_name),
        }
    )
