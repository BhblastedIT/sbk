""































































from __future__ import annotations







STATO = "stato"




EVENTO = "evento"



PROPRIETA = "proprieta"




AGGREGATO = "aggregato"


NON_CLASSIFICATO = "non_classificato"

CLASSI_TEMPORALI = (STATO, EVENTO, PROPRIETA, AGGREGATO)










PREFISSI_STATO = (
    "employment.",
    "legal.",
    "identity.role",
    "status.",
    "org.",
)




PREFISSI_EVENTO = (
    "deep.",
    "relationship.",
    "communication.",
    "episode.",
)












TEMPORALITA = {





    "relationship.works_with": EVENTO,



    "identity.name": PROPRIETA,


    "deep.operational.committed": EVENTO,

    "deep.operational.discussed": EVENTO,



    "relationship.knows": EVENTO,


    "relationship.looking_for": STATO,

    "relationship.working_on": STATO,


    "relationship.need": STATO,

    "relationship.knows_from": PROPRIETA,


    "relationship.deal_term": EVENTO,


    "deep.commitment.delivery_commitment": EVENTO,

    "relationship.offer": EVENTO,

    "relationship.condition": EVENTO,


    "relationship.interested_in": STATO,


    "relationship.relationship_fact": EVENTO,

    "relationship.background": PROPRIETA,


    "relationship.family_of": PROPRIETA,


    "relationship.friend_of": STATO,


    "deep.strategic.partnership": EVENTO,

    "relationship.introduced_by": EVENTO,


    "relationship.works_at": STATO,


    "relationship.personal_detail": EVENTO,

    "deep.strategic.product_launch": EVENTO,

    "deep.strategic.market_entry": EVENTO,



    "communication.email_last_contact": AGGREGATO,

    "crm.last_interaction": AGGREGATO,


    "communication.email_total": AGGREGATO,

    "relationship.commitment": EVENTO,


    "contact.email": STATO,



    "deep.financial.revenue": STATO,







    "communication.email_first_contact": AGGREGATO,
    "communication.slack_messages": AGGREGATO,
    "communication.slack_last_contact": AGGREGATO,







    "legal.contracts_count": AGGREGATO,
    "legal.first_contract": AGGREGATO,
    "legal.last_contract": AGGREGATO,











    "communication.linkedin_messages": AGGREGATO,
    "communication.linkedin_first_contact": AGGREGATO,
    "communication.linkedin_last_contact": AGGREGATO,











    "commitment.status": STATO,
    "commitment.due_date": STATO,
    "commitment.where": STATO,
    "commitment.priority": STATO,

    "commitment.source_url": PROPRIETA,





    "identity.headline": STATO,



    "identity.alias": STATO,


    "work.org_unit": STATO,


    "work.clickup_username": STATO,











    "employment.start_date": EVENTO,
}
























CODA_NOTA = (
    "employment.hire_date",
    "identity.alias",
    "relationship.works_with",
)


def classe_temporale(attributo: str) -> str:
    ""




    a = (attributo or "").strip().lower()
    if not a:
        return NON_CLASSIFICATO
    esatta = TEMPORALITA.get(a)
    if esatta:
        return esatta
    # Plugins on the generic intake write communication.<plugin>_interactions,
    # _first_contact and _last_contact (xs-l2-knowledge-extract.py, source "plugins"):
    # counts and dates that are recomputed at every run, AGGREGATO like their Slack and
    # LinkedIn equivalents above, so a new value replaces the old one.
    if a.startswith("communication.") and a.endswith(
        ("_interactions", "_first_contact", "_last_contact")
    ):
        return AGGREGATO
    if a.startswith(PREFISSI_STATO):
        return STATO
    if a.startswith(PREFISSI_EVENTO):
        return EVENTO
    return NON_CLASSIFICATO


def classe_lessicale(attributo: str) -> str | None:
    ""







    a = attributo or ""


    if a.startswith("identity.name") or a.startswith("identity.alias"):
        return "identita"
    if a.startswith(PREFISSI_STATO):
        return "stato"
    if a.startswith(PREFISSI_EVENTO):
        return "evento"
    return None


def ammette_chiusura(attributo: str) -> bool:
    ""












    return classe_temporale(attributo) == STATO


def chiusure_illecite(fatti) -> list:
    ""





    fuori = []
    for f in fatti or []:
        if not isinstance(f, dict):
            continue
        if f.get("valid_to") and not ammette_chiusura(f.get("attribute") or ""):
            fuori.append(f)
    return fuori

















FUNZIONALI = (

    "employment.company",
    "employment.current_role",
    "employment.role",
    "employment.department",
    "employment.manager_name",



    "employment.start_date",
    "employment.termination_date",
    "identity.given_name",
    "identity.surname",
    "identity.birth_date",
    "location.base",
    "legal.contract_end",


    "crm.company",
)




















MULTI_VALORE = (
    "deep.operational.discussed",
    "deep.operational.committed",
    "deep.strategic.partnership",
    "deep.strategic.market_entry",
    "deep.strategic.competitive_move",
    "deep.strategic.product_launch",
    "deep.commitment.delivery_commitment",
    "relationship.",
    "episode.",
    "identity.alias",
    "contact.email",
    "contact.phone",
)

FUNZIONALE = "funzionale"
MULTI = "multi"
NON_DICHIARATA = "non_dichiarata"


def e_funzionale(attributo: str) -> bool:
    ""
    return (attributo or "").strip().lower().startswith(FUNZIONALI)


def e_multi_valore(attributo: str) -> bool:
    ""






    return (attributo or "").strip().lower().startswith(MULTI_VALORE)


def cardinalita(attributo: str) -> str:
    ""





    if e_funzionale(attributo):
        return FUNZIONALE
    if e_multi_valore(attributo):
        return MULTI
    return NON_DICHIARATA


def da_classificare(attributo: str) -> bool:
    ""




    a = (attributo or "").strip()
    if not a:
        return False
    return cardinalita(a) == NON_DICHIARATA or classe_temporale(a) == NON_CLASSIFICATO


__all__ = [
    "AGGREGATO",
    "CLASSI_TEMPORALI",
    "EVENTO",
    "FUNZIONALE",
    "FUNZIONALI",
    "MULTI",
    "MULTI_VALORE",
    "NON_CLASSIFICATO",
    "NON_DICHIARATA",
    "PREFISSI_EVENTO",
    "PREFISSI_STATO",
    "PROPRIETA",
    "STATO",
    "TEMPORALITA",
    "ammette_chiusura",
    "cardinalita",
    "chiusure_illecite",
    "classe_lessicale",
    "classe_temporale",
    "da_classificare",
    "e_funzionale",
    "e_multi_valore",
]
