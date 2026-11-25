""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.sbk_bridge import safe_path_param


class PersonQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)


class AnnotationRequest(BaseModel):
    email: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class DecisionSupportRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    domain: str = ""


router = APIRouter(prefix="/api/person", tags=["person"])


@router.post("/unified")
async def person_unified(request: Request, body: PersonQuery):
    ""
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.unified_person_lookup, body.query.strip())
    return JSONResponse(result)


@router.post("/lookup")
async def person_lookup(request: Request, body: PersonQuery):
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.lookup_person, body.query.strip())
    if result is None:
        return JSONResponse({"error": "Person not found", "query": body.query}, status_code=404)
    return JSONResponse(result)





@router.get("/threads")
def person_threads(request: Request, email: str = ""):
    ""
    if not email:
        return JSONResponse({"error": "Email required"}, status_code=400)
    bridge = request.app.state.bridge
    threads = bridge.get_person_recent_threads(email)
    return JSONResponse({"threads": threads})


@router.get("/events")
def person_events(request: Request, email: str = ""):
    ""
    if not email:
        return JSONResponse({"error": "Email required"}, status_code=400)
    bridge = request.app.state.bridge
    events = bridge.get_person_recent_events(email)
    return JSONResponse({"events": events})


@router.get("/related")
def person_related(request: Request, email: str = ""):
    ""
    if not email:
        return JSONResponse({"error": "Email required"}, status_code=400)
    bridge = request.app.state.bridge
    related = bridge.get_person_related(email)
    return JSONResponse({"related": related})


@router.get("/nlp")
def person_nlp(request: Request, name: str = ""):
    ""
    if not name:
        return JSONResponse({"error": "Name required"}, status_code=400)
    bridge = request.app.state.bridge
    nlp = bridge.get_person_nlp(name)
    return JSONResponse(nlp)


@router.post("/annotate")
async def person_annotate(request: Request, body: AnnotationRequest):
    ""
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(
        bridge.submit_person_annotation, body.email.strip(), body.text.strip()
    )
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@router.get("/facts")
def person_facts(request: Request, pid: str = "", limit: int = 50):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    bridge = request.app.state.bridge
    facts = bridge.get_person_facts(pid, limit=limit)
    return JSONResponse({"facts": facts, "total": len(facts)})


@router.get("/facts/search")
def facts_search(request: Request, q: str = "", predicate: str = "", limit: int = 20):
    ""
    if not q:
        return JSONResponse({"error": "Query required"}, status_code=400)
    bridge = request.app.state.bridge
    results = bridge.search_facts(q, predicate=predicate or None, limit=limit)
    return JSONResponse({"results": results, "total": len(results)})


@router.get("/deep-facts")
def api_deep_facts(
    request: Request,
    q: str = "",
    person: str = "",
    category: str = "",
    min_confidence: str = "",
):
    ""
    bridge = request.app.state.bridge
    results = bridge.search_deep_facts(
        query=q, person=person, category=category, min_confidence=min_confidence
    )
    return JSONResponse({"facts": results, "count": len(results)})


@router.get("/timeline")
def person_timeline(request: Request, pid: str = ""):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    bridge = request.app.state.bridge
    data = bridge.get_person_interaction_heatmap(pid)
    return JSONResponse(data)


@router.get("/full-timeline")
def person_full_timeline(
    request: Request,
    pid: str = "",
    limit: int = 100,
    offset: int = 0,
    source_filter: str = "all",
):
    ""




    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    if limit > 500:
        limit = 500
    bridge = request.app.state.bridge
    data = bridge.get_person_timeline(
        person_id=pid, limit=limit, offset=offset, source_filter=source_filter
    )
    return JSONResponse(data)


@router.get("/decay-forecast")
def person_decay_forecast(request: Request, pid: str = ""):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    bridge = request.app.state.bridge
    data = bridge.get_person_decay_forecast(pid)
    return JSONResponse(data)


@router.get("/deep-facts/person")
def api_person_deep_facts(
    request: Request,
    pid: str = "",
    category: str = "",
):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    bridge = request.app.state.bridge
    results = bridge.get_person_deep_facts(person_id=pid, category=category)
    return JSONResponse({"facts": results, "count": len(results)})





@router.get("/context")
def person_context(request: Request, pid: str = ""):
    ""
    if not pid:
        return JSONResponse({"error": "Person ID required"}, status_code=400)
    if safe_path_param(pid) is None:
        return JSONResponse({"error": "Invalid person ID"}, status_code=400)
    bridge = request.app.state.bridge
    ctx = bridge.get_person_context(pid)
    return JSONResponse(ctx)


@router.get("/brief")
def person_brief(request: Request, pid: str = "", emails: str = "", meeting: str = ""):
    ""



    bridge = request.app.state.bridge
    if pid:

        G = getattr(bridge, "_graph", None)
        if G and pid in G.nodes:
            email = G.nodes[pid].get("email", "")
            if email:
                data = bridge.get_pre_meeting_brief([email], meeting_summary=meeting)
                return JSONResponse(data)
        return JSONResponse({"error": "Person not found in graph"}, status_code=404)

    if emails:
        email_list = [e.strip() for e in emails.split(",") if e.strip()]
        data = bridge.get_pre_meeting_brief(email_list, meeting_summary=meeting)
        return JSONResponse(data)

    return JSONResponse({"error": "pid or emails required"}, status_code=400)


@router.get("/reconnection/suggestions")
def reconnection_suggestions(request: Request, limit: int = 20):
    ""
    bridge = request.app.state.bridge
    suggestions = bridge.get_reconnection_suggestions(limit=limit)
    return JSONResponse({"suggestions": suggestions, "count": len(suggestions)})





_VALID_DOMAINS = {
    "hiring",
    "fundraising",
    "m_and_a",
    "product",
    "strategy",
    "legal",
    "marketing",
    "finance",
    "real_estate",
    "operations",
}


@router.post("/decision-support")
async def decision_support(request: Request, body: DecisionSupportRequest):
    ""
    description = body.description.strip()
    domain = body.domain.strip()

    if domain and domain not in _VALID_DOMAINS:
        return JSONResponse(
            {"error": f"domain must be one of: {', '.join(sorted(_VALID_DOMAINS))}"},
            status_code=400,
        )

    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.get_decision_support, description, domain=domain)
    return JSONResponse(result)
