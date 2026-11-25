""







from __future__ import annotations

import logging
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import rumore

from sbk_config import INTERNAL_DOMAINS, load_interaction_weights

log = logging.getLogger("rq.weights")


_SQI_NOISE_THRESHOLD = 0.75


_INTERNAL_LOWER = {d.lower() for d in INTERNAL_DOMAINS}


def _is_internal_email(email: str) -> bool:
    ""
    if "@" not in email:
        return False
    domain = email.split("@")[1].strip().lower()
    return domain in _INTERNAL_LOWER





def classify_email(
    from_addr: str,
    to_addr: str | None,
    cc: str | None,
    bcc: str | None,
    in_reply_to: str | None,
    body_text: str | None,
    own_emails: set[str] | None = None,
    sqi_noise_scores: dict[str, float] | None = None,
    tipi_mittenti: dict[str, str] | None = None,
    labels: str | None = None,
) -> tuple[str, float]:
    ""




















    if own_emails is None:
        from sbk_config import OWN_EMAILS

        own_emails = OWN_EMAILS

    weights = load_interaction_weights()
    email_weights = weights.get("email", {})

    sender = rumore.addr_of(from_addr) or (from_addr or "").strip().lower()


    if tipi_mittenti:
        tipo = tipi_mittenti.get(sender)
        if tipo in rumore.TIPI_RUMORE:
            return "rumore", email_weights.get("rumore", 0.0)
        if tipo is not None and not rumore.conta_nei_punteggi(sender, tipi_mittenti):
            return "dubbio", email_weights.get("dubbio", 0.0)
        if (
            tipo in rumore.TIPI_RAPPORTO
            and not rumore.regolazioni().get("massa_conta", True)
            and rumore.di_massa(labels, body_text)
        ):
            return "massa", email_weights.get("massa", 0.0)




    tipo_tabella = tipi_mittenti.get(sender) if tipi_mittenti else None
    if sqi_noise_scores and sender in sqi_noise_scores and tipo_tabella not in rumore.TIPI_RAPPORTO:
        if sqi_noise_scores[sender] >= _SQI_NOISE_THRESHOLD:
            return "newsletter_mailinglist", email_weights.get("newsletter_mailinglist", 0.0)


    to_list = _parse_email_list(to_addr, own_emails)
    cc_list = _parse_email_list(cc, own_emails)
    bcc_list = _parse_email_list(bcc, own_emails)

    total_to = len(to_list)
    total_cc = len(cc_list)
    total_all = total_to + total_cc

    is_reply = bool(in_reply_to)
    is_substantive = _is_substantive_content(body_text)


    sender_is_owner = sender in own_emails
    if not sender_is_owner:

        owner_in_to = any(e in own_emails for e in _parse_email_list(to_addr, set()))
        if not owner_in_to:
            owner_in_bcc = any(e in own_emails for e in _parse_email_list(bcc, set()))
            if owner_in_bcc:
                return "bcc", email_weights.get("bcc", 0.05)

            is_internal_sender = _is_internal_email(sender)
            if total_all >= 10:
                if is_internal_sender:
                    return "cc_mass_internal", email_weights.get("cc_mass_internal", 0.01)
                return "cc_mass_external", email_weights.get("cc_mass_external", 0.005)
            if is_internal_sender:
                return "cc_internal_team", email_weights.get("cc_internal_team", 0.04)
            return "cc_external_small", email_weights.get("cc_external_small", 0.02)


    if total_all >= 10:
        if is_reply and is_substantive:
            return "reply_all_substantive", email_weights.get("reply_all_substantive", 0.3)
        return "mass_10plus", email_weights.get("mass_10plus", 0.02)


    if is_reply and is_substantive:
        if total_to > 1:
            return "reply_all_substantive", email_weights.get("reply_all_substantive", 0.3)
        return "reply_substantive", email_weights.get("reply_substantive", 0.8)


    if total_to == 1 and total_cc == 0:
        return "direct_1to1", email_weights.get("direct_1to1", 1.0)


    if 2 <= total_to <= 5:
        return "small_group_2to5", email_weights.get("small_group_2to5", 0.5)


    if 6 <= total_all < 10:
        return "small_group_2to5", email_weights.get("small_group_2to5", 0.5)


    if total_cc > 0 and total_to == 0:
        if sender_is_owner or _is_internal_email(sender):
            return "cc_internal_team", email_weights.get("cc_internal_team", 0.04)
        return "cc_external_small", email_weights.get("cc_external_small", 0.02)

    return "direct_1to1", email_weights.get("direct_1to1", 1.0)


def _parse_email_list(field: str | None, own_emails: set[str]) -> list[str]:
    ""

    if not field or str(field).strip() in ("", "nan", "None"):
        return []
    own = {e.lower() for e in own_emails}
    return [e for e in rumore.addrs_of(str(field)) if e not in own]


def _is_substantive_content(body_text: str | None) -> bool:
    ""
    if not body_text:
        return False
    text = str(body_text).strip()

    lines = text.split("\n")
    new_lines = [line for line in lines if not line.strip().startswith(">")]
    new_content = "\n".join(new_lines).strip()
    return len(new_content) > 50





def classify_calendar_event(
    attendee_count: int,
    event_id: str | None = None,
    is_recurring: bool | None = None,
) -> tuple[str, float]:
    ""









    weights = load_interaction_weights()
    cal_weights = weights.get("calendar", {})


    recurring = is_recurring
    if recurring is None and event_id:
        recurring = "_" in str(event_id)


    if attendee_count <= 2:
        if recurring:
            return "meeting_1to1_recurring", cal_weights.get("meeting_1to1_recurring", 1.2)
        return "meeting_1to1", cal_weights.get("meeting_1to1", 1.0)


    if 3 <= attendee_count <= 5:
        return "small_group_3to5", cal_weights.get("small_group_3to5", 0.7)


    if attendee_count >= 10:
        return "large_meeting_10plus", cal_weights.get("large_meeting_10plus", 0.1)


    return "small_group_3to5", cal_weights.get("small_group_3to5", 0.7)





def classify_slack_message(
    message_type: str,
    channel_member_count: int | None = None,
) -> tuple[str, float]:
    ""








    weights = load_interaction_weights()
    slack_weights = weights.get("slack", {})

    if message_type == "dm":
        return "dm_1to1", slack_weights.get("dm_1to1", 0.8)

    if message_type == "mention":
        return "mention", slack_weights.get("mention", 0.4)

    if message_type == "reply":
        if channel_member_count is not None and channel_member_count < 20:
            return "thread_reply_small_channel", slack_weights.get(
                "thread_reply_small_channel", 0.5
            )
        if channel_member_count is not None and channel_member_count >= 20:
            return "channel_large", slack_weights.get("channel_large", 0.1)

        return "thread_reply_small_channel", slack_weights.get("thread_reply_small_channel", 0.5)


    return "channel_large", slack_weights.get("channel_large", 0.1)





def classify_call(
    participant_count: int,
) -> tuple[str, float]:
    ""







    weights = load_interaction_weights()
    call_weights = weights.get("plaud_tactiq", {})

    if participant_count <= 2:
        return "call_1to1", call_weights.get("call_1to1", 1.0)
    if participant_count <= 5:
        return "call_small_group", call_weights.get("call_small_group", 0.7)
    return "call_large_passive", call_weights.get("call_large_passive", 0.1)





def classify_attio(
    interaction_type: str,
) -> tuple[str, float]:
    ""







    weights = load_interaction_weights()
    attio_weights = weights.get("attio", {})

    if interaction_type == "meeting":
        return "meeting_recorded", attio_weights.get("meeting_recorded", 0.8)
    return "note_about_person", attio_weights.get("note_about_person", 0.6)





def classify_whatsapp(
    is_group: bool,
    participant_count: int = 2,
) -> tuple[str, float]:
    ""








    weights = load_interaction_weights()
    wa_weights = weights.get("whatsapp", {})

    if not is_group:
        return "wa_dm_1to1", wa_weights.get("wa_dm_1to1", 0.9)
    if participant_count <= 5:
        return "wa_small_group", wa_weights.get("wa_small_group", 0.4)
    return "wa_large_group", wa_weights.get("wa_large_group", 0.15)
