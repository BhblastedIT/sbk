""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sbk_config import ENRICHED_DIR

router = APIRouter(prefix="/api/entity-audit", tags=["entity-audit"])
log = logging.getLogger("sbk.dashboard.entity_audit")


SUGGESTIONS_FILE = ENRICHED_DIR / "merge-suggestions.json"

SUGGESTIONS_DIR = ENRICHED_DIR / "suggestions"

SPLINK_SUGGESTIONS_FILE = ENRICHED_DIR / "merge-suggestions-splink.json"


def _load_suggestions() -> list[dict]:
    ""
    items: list[dict] = []


    if SUGGESTIONS_FILE.exists():
        try:
            raw = json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for i, item in enumerate(raw):
                    if "id" not in item:

                        pid_a = item.get("person_id_a", "")
                        pid_b = item.get("person_id_b", "")
                        item["id"] = f"{pid_a}--{pid_b}" if pid_a and pid_b else f"s-{i}"
                    items.append(item)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to read %s: %s", SUGGESTIONS_FILE, exc)


    if SUGGESTIONS_DIR.exists():
        for f in sorted(SUGGESTIONS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["id"] = f.stem
                items.append(data)
            except (json.JSONDecodeError, OSError):
                continue


    if SPLINK_SUGGESTIONS_FILE.exists():
        try:
            raw = json.loads(SPLINK_SUGGESTIONS_FILE.read_text(encoding="utf-8"))
            suggestions = raw if isinstance(raw, list) else raw.get("review_suggestions", [])
            for sug in suggestions:
                id_left = sug.get("id_left", "")
                id_right = sug.get("id_right", "")
                names = sug.get("names", ["", ""])
                sid = f"splink-{id_left}--{id_right}"
                items.append(
                    {
                        "id": sid,
                        "person_id_a": id_left,
                        "person_id_b": id_right,
                        "name_a": names[0] if len(names) > 0 else "",
                        "name_b": names[1] if len(names) > 1 else "",
                        "confidence": sug.get("match_probability", 0),
                        "method": "splink",
                        "status": sug.get("status", "pending"),
                    }
                )
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            log.warning("Failed to read Splink suggestions: %s", exc)

    return items


def _save_suggestion(suggestion_id: str, data: dict) -> bool:
    ""




    if SUGGESTIONS_DIR.exists():
        path = SUGGESTIONS_DIR / f"{suggestion_id}.json"
        if path.exists():
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True


    if SUGGESTIONS_FILE.exists():
        try:
            raw = json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for i, item in enumerate(raw):
                    pid_a = item.get("person_id_a", "")
                    pid_b = item.get("person_id_b", "")
                    item_id = item.get("id", f"{pid_a}--{pid_b}" if pid_a and pid_b else f"s-{i}")
                    if item_id == suggestion_id:
                        raw[i] = {k: v for k, v in data.items() if k != "id"}
                        SUGGESTIONS_FILE.write_text(
                            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
                        )
                        return True
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to update %s: %s", SUGGESTIONS_FILE, exc)

    return False


def _validate_id(suggestion_id: str) -> str | None:
    ""
    if (
        ".." in suggestion_id
        or "/" in suggestion_id
        or "\\" in suggestion_id
        or "\0" in suggestion_id
    ):
        return "Invalid suggestion ID"
    return None


@router.get("/suggestions")
def get_suggestions(
    min_confidence: float = 0.0,
    status: str = "",
    limit: int = 100,
):
    ""
    all_items = _load_suggestions()

    items = []
    for item in all_items:

        confidence = item.get("confidence")
        if confidence is None:
            score = item.get("score", 0)
            confidence = score / 100.0 if isinstance(score, int | float) else 0.0
            item["confidence"] = round(confidence, 3)


        item_status = item.get("status", "pending")
        if status and item_status != status:
            continue


        if confidence < min_confidence:
            continue

        items.append(item)
        if len(items) >= limit:
            break

    return {
        "items": items,
        "total": len(items),
        "pending": sum(1 for i in items if i.get("status", "pending") == "pending"),
    }


@router.post("/approve/{suggestion_id}")
def approve_suggestion(suggestion_id: str):
    ""
    err = _validate_id(suggestion_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    all_items = _load_suggestions()
    target = next((i for i in all_items if i.get("id") == suggestion_id), None)
    if not target:
        return JSONResponse({"error": "Suggestion not found"}, status_code=404)

    target["status"] = "approved"
    target["reviewed_at"] = datetime.now(UTC).isoformat()

    if not _save_suggestion(suggestion_id, target):
        return JSONResponse({"error": "Failed to persist update"}, status_code=500)

    return {"ok": True, "id": suggestion_id, "status": "approved"}


@router.post("/reject/{suggestion_id}")
def reject_suggestion(suggestion_id: str):
    ""
    err = _validate_id(suggestion_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    all_items = _load_suggestions()
    target = next((i for i in all_items if i.get("id") == suggestion_id), None)
    if not target:
        return JSONResponse({"error": "Suggestion not found"}, status_code=404)

    target["status"] = "rejected"
    target["reviewed_at"] = datetime.now(UTC).isoformat()

    if not _save_suggestion(suggestion_id, target):
        return JSONResponse({"error": "Failed to persist update"}, status_code=500)

    return {"ok": True, "id": suggestion_id, "status": "rejected"}


class UndoMergeRequest(BaseModel):
    entity_id_a: str
    entity_id_b: str


@router.post("/undo-merge")
def undo_merge(req: UndoMergeRequest):
    ""
    err_a = _validate_id(req.entity_id_a)
    err_b = _validate_id(req.entity_id_b)
    if err_a or err_b:
        return JSONResponse({"error": err_a or err_b}, status_code=400)

    try:
        from golden_record import GoldenRecordEngine

        from sbk_config import KNOWLEDGE_DIR

        cluster_path = KNOWLEDGE_DIR / "entity-clusters.json"
        if not cluster_path.exists():
            return JSONResponse({"error": "No cluster index found"}, status_code=404)

        engine = GoldenRecordEngine(cluster_path, KNOWLEDGE_DIR)
        result = engine.undo_merge(req.entity_id_a, req.entity_id_b)
        if result:
            return {
                "ok": True,
                "entity_id_a": req.entity_id_a,
                "entity_id_b": req.entity_id_b,
                "action": "undo_merge",
            }
        return JSONResponse(
            {"error": "No active merge decision found for this pair"}, status_code=404
        )
    except Exception as e:
        log.error("Failed to undo merge: %s", e)
        return JSONResponse({"error": "Internal error"}, status_code=500)


@router.get("/stats")
def get_audit_stats():
    ""
    all_items = _load_suggestions()

    stats = {"total": 0, "pending": 0, "approved": 0, "rejected": 0}
    for item in all_items:
        stats["total"] += 1
        s = item.get("status", "pending")
        if s in stats:
            stats[s] += 1

    return stats
