""



from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class EntityDecision(BaseModel):
    action: str = Field(..., pattern="^(merge|reject)$")
    index: int


class EntityBatchDecisions(BaseModel):
    decisions: list[dict] = Field(..., min_length=1)


router = APIRouter(prefix="/api/entities", tags=["entities"])
log = logging.getLogger("dashboard.entities")


@router.get("/review")
def get_review_queue(request: Request, reason: str = "all", page: int = 1, per_page: int = 50):
    ""
    bridge = request.app.state.bridge
    items = bridge.get_entity_review(reason_filter=reason)

    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 1,
    }


@router.post("/decide")
async def submit_decision(request: Request, body: EntityDecision):
    ""
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.submit_entity_decision, body.index, body.action)

    if result.get("error"):
        return JSONResponse(result, status_code=400)

    return result


@router.post("/decide-batch")
async def submit_batch_decisions(request: Request, body: EntityBatchDecisions):
    ""
    bridge = request.app.state.bridge
    results = await asyncio.to_thread(bridge.submit_entity_decisions_batch, body.decisions)
    return results


@router.get("/merge-suggestions")
def entities_merge_suggestions(request: Request):
    ""
    import json as _json

    from sbk_config import ENRICHED_DIR

    suggestions_file = ENRICHED_DIR / "merge-suggestions.json"
    suggestions = []
    if suggestions_file.exists():
        try:
            suggestions = _json.loads(suggestions_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return JSONResponse({"suggestions": suggestions, "total": len(suggestions)})


@router.post("/merge-suggestion")
def handle_merge_suggestion(request: Request, action: str = "", pid_a: str = "", pid_b: str = ""):
    ""
    import json as _json
    from datetime import UTC, datetime

    from sbk_config import ENRICHED_DIR

    if action not in ("merge", "ignore"):
        return JSONResponse({"error": "action must be 'merge' or 'ignore'"}, status_code=400)
    if not pid_a or not pid_b:
        return JSONResponse({"error": "pid_a and pid_b are required"}, status_code=400)

    suggestions_file = ENRICHED_DIR / "merge-suggestions.json"
    decisions_file = ENRICHED_DIR / "merge-suggestion-decisions.json"


    suggestions = []
    if suggestions_file.exists():
        try:
            suggestions = _json.loads(suggestions_file.read_text(encoding="utf-8"))
        except Exception:
            return JSONResponse({"error": "Failed to read suggestions file"}, status_code=500)


    remaining = []
    matched = None
    for s in suggestions:
        if s.get("person_id_a") == pid_a and s.get("person_id_b") == pid_b:
            matched = s
        else:
            remaining.append(s)

    if not matched:
        return JSONResponse({"error": "Suggestion not found"}, status_code=404)


    decision = {
        "action": action,
        "person_id_a": pid_a,
        "person_id_b": pid_b,
        "name_a": matched.get("name_a", ""),
        "name_b": matched.get("name_b", ""),
        "score": matched.get("score", 0),
        "timestamp": datetime.now(UTC).isoformat(),
    }

    existing = {"decisions": []}
    if decisions_file.exists():
        try:
            existing = _json.loads(decisions_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            existing = {"decisions": []}
    existing["decisions"].append(decision)
    decisions_file.write_text(_json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


    if action == "merge":
        entity_decisions_file = ENRICHED_DIR / "entity-decisions.json"
        entity_existing = {"decisions": []}
        if entity_decisions_file.exists():
            try:
                entity_existing = _json.loads(entity_decisions_file.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                entity_existing = {"decisions": []}
        emails = []
        if matched.get("email_a"):
            emails.append(matched["email_a"])
        if matched.get("email_b"):
            emails.append(matched["email_b"])
        entity_existing["decisions"].append(
            {
                "action": "merge",
                "keys": emails,
                "reason": "merge_suggestion_approved",
                "score": matched.get("score", 0),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        entity_decisions_file.write_text(
            _json.dumps(entity_existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )


    suggestions_file.write_text(
        _json.dumps(remaining, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info("Merge suggestion %s: %s + %s (score=%s)", action, pid_a, pid_b, matched.get("score"))

    return JSONResponse(
        {
            "ok": True,
            "action": action,
            "remaining": len(remaining),
        }
    )
