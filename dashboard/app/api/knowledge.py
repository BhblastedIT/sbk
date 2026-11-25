""














from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import sbk_config as cfg

log = logging.getLogger("sbk.api.knowledge")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_health_cache: dict | None = None
_health_cache_ts: float = 0.0
_HEALTH_CACHE_TTL = 300.0





class ResolveRequest(BaseModel):
    conflict_id: str
    action: str
    manual_value: str | None = None


class OverrideRequest(BaseModel):
    entity_id: str
    entity_type: str = "person"
    attribute: str
    value: str





@router.get("/conflicts")
def get_conflicts(
    page: int = 1,
    page_size: int = 50,
    sort: str = "priority",
    min_confidence: float = 0.0,
):
    ""
    try:
        from xs_knowledge_conflict import _priority_score, load_pending_review

        items = load_pending_review()


        if min_confidence > 0:
            items = [
                i
                for i in items
                if i.get("confidence", i.get("new_fact", {}).get("confidence", 0)) >= min_confidence
            ]


        if sort == "priority":
            items.sort(key=_priority_score, reverse=True)
        elif sort == "confidence":
            items.sort(
                key=lambda x: x.get("confidence", x.get("new_fact", {}).get("confidence", 0)),
                reverse=True,
            )
        elif sort == "created_at":
            items.sort(key=lambda x: x.get("created_at", x.get("detected_at", "")), reverse=True)

        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]

        return {
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        }
    except Exception as e:
        log.error("Failed to load conflicts: %s", e)
        return {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "error": "Failed to load conflicts",
        }


@router.post("/conflicts/resolve")
def resolve_conflict_endpoint(req: ResolveRequest):
    ""
    if req.action not in ("accept_new", "keep_old", "manual_value"):
        raise HTTPException(status_code=400, detail="Invalid action")

    if req.action == "manual_value" and not req.manual_value:
        raise HTTPException(status_code=400, detail="manual_value required for manual_value action")

    try:
        from xs_knowledge_conflict import (
            apply_manual_override_to_entity,
            load_pending_review,
            resolve_pending_item,
        )


        items = load_pending_review()
        target = None
        for it in items:
            if it.get("conflict_id") == req.conflict_id:
                target = it
                break

        if not target:
            raise HTTPException(status_code=404, detail="Conflict not found")


        entity_id = target.get("entity_id", "")
        attribute = target.get("attribute", "")

        if req.action == "accept_new":
            new_fact = target.get("new_fact")
            if new_fact:
                entity_type = target.get("existing_fact", {}).get("entity_type", "person")

                _expire_fact_in_entity(
                    entity_id,
                    entity_type,
                    target.get("existing_fact", {}).get("fact_id"),
                )

                _add_fact_to_entity(entity_id, entity_type, new_fact)

        elif req.action == "manual_value":
            entity_type = target.get("existing_fact", {}).get("entity_type", "person")
            apply_manual_override_to_entity(entity_id, entity_type, attribute, req.manual_value)


        resolved = resolve_pending_item(req.conflict_id, req.action, req.manual_value)
        if not resolved:
            raise HTTPException(status_code=404, detail="Conflict not found in queue")

        return {"status": "resolved", "conflict_id": req.conflict_id, "action": req.action}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to resolve conflict: %s", e)
        raise HTTPException(status_code=500, detail="Internal error resolving conflict") from e


@router.post("/override")
def create_override(req: OverrideRequest):
    ""
    try:
        from xs_knowledge_conflict import apply_manual_override_to_entity

        success = apply_manual_override_to_entity(
            entity_id=req.entity_id,
            entity_type=req.entity_type,
            attribute=req.attribute,
            value=req.value,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Entity not found")

        return {
            "status": "override_applied",
            "entity_id": req.entity_id,
            "attribute": req.attribute,
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to create override: %s", e)
        raise HTTPException(status_code=500, detail="Internal error creating override") from e


@router.get("/health")
def knowledge_health():
    ""




    global _health_cache, _health_cache_ts
    now = time.time()
    if _health_cache and (now - _health_cache_ts) < _HEALTH_CACHE_TTL:
        return _health_cache
    try:
        entities_dir = cfg.KNOWLEDGE_ENTITIES_DIR
        entity_types = ["person", "organization", "deal", "commitment"]
        now = datetime.now(UTC)
        stale_threshold = now - timedelta(days=30)

        health: dict[str, dict] = {}

        for etype in entity_types:
            etype_dir = entities_dir / etype
            if not etype_dir.exists():
                health[etype] = {
                    "entity_count": 0,
                    "fact_count": 0,
                    "uncertain_facts": 0,
                    "stale_facts": 0,
                    "health_score": 1.0,
                }
                continue

            entity_count = 0
            fact_count = 0
            uncertain = 0
            stale = 0

            for entity_file in etype_dir.glob("*.json"):
                try:
                    profile = json.loads(entity_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

                entity_count += 1
                facts = profile.get("facts", [])
                fact_count += len(facts)

                for f in facts:
                    if f.get("expired_at"):
                        continue
                    conf = f.get("confidence", 0.5)
                    if conf < 0.5:
                        uncertain += 1

                    extracted = f.get("source", {}).get("extracted_at", "")
                    if extracted:
                        try:
                            ts = extracted
                            if ts.endswith("Z"):
                                ts = ts[:-1] + "+00:00"
                            dt = datetime.fromisoformat(ts)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=UTC)
                            if dt < stale_threshold:
                                stale += 1
                        except (ValueError, TypeError):
                            pass

            active_facts = max(1, fact_count - uncertain - stale)
            health_score = round(active_facts / max(1, fact_count), 4)

            health[etype] = {
                "entity_count": entity_count,
                "fact_count": fact_count,
                "uncertain_facts": uncertain,
                "stale_facts": stale,
                "health_score": health_score,
            }


        from xs_knowledge_conflict import load_pending_review

        pending = load_pending_review()


        cluster_stats = {"cluster_count": 0, "clustered_entities": 0}
        try:
            cluster_path = cfg.KNOWLEDGE_DIR / "entity-clusters.json"
            if cluster_path.exists():
                import json as _json

                cdata = _json.loads(cluster_path.read_text())
                clusters = cdata.get("clusters", {})
                cluster_stats["cluster_count"] = len(clusters)
                cluster_stats["clustered_entities"] = sum(
                    len(c.get("members", [])) for c in clusters.values()
                )
        except Exception:
            pass

        result = {
            "domains": health,
            "pending_review_count": len(pending),
            "cluster_stats": cluster_stats,
            "timestamp": now.isoformat(),
        }
        _health_cache = result
        _health_cache_ts = time.time()
        return result

    except Exception as e:
        log.error("Failed to compute knowledge health: %s", e)
        return {"domains": {}, "pending_review_count": 0, "error": str(e)}




VALID_DOMAINS = {"person", "organization", "deal", "commitment"}


@router.get("/domain/{domain}")
def knowledge_domain(
    request: Request,
    domain: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    sort: str = "name",
    q: str = "",
):
    ""
    if domain not in VALID_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Invalid domain: {domain}")
    try:
        bridge = request.app.state.bridge
        data = bridge.get_knowledge_domain_entities(domain, page, per_page, sort, q)
        return data
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to get domain entities: %s", e)
        raise HTTPException(status_code=500, detail="Internal error") from e


@router.get("/entity/{entity_id}")
def knowledge_entity_detail(request: Request, entity_id: str, include_history: bool = False):
    ""
    from app.core.sbk_bridge import safe_path_param

    if safe_path_param(entity_id) is None:
        raise HTTPException(status_code=400, detail="Invalid entity_id")

    try:
        bridge = request.app.state.bridge
        data = bridge.get_knowledge_entity_detail(entity_id, include_history)
        if data is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to get entity detail: %s", e)
        raise HTTPException(status_code=500, detail="Internal error") from e


@router.get("/changes")
def knowledge_changes(request: Request, days: int = 7, domain: str = "all", limit: int = 50):
    ""
    try:
        bridge = request.app.state.bridge
        changes = bridge.get_knowledge_changes(domain, days)
        return {"changes": changes[:limit], "count": len(changes[:limit])}
    except Exception as e:
        log.error("Failed to get knowledge changes: %s", e)
        return {"changes": [], "count": 0, "error": "Failed to load changes"}





def _atomic_write_json(path, data) -> None:
    ""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp, str(path))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _expire_fact_in_entity(entity_id: str, entity_type: str, fact_id: str | None) -> None:
    ""
    if not fact_id:
        return
    profile_path = cfg.KNOWLEDGE_ENTITIES_DIR / entity_type / f"{entity_id}.json"
    if not profile_path.exists():
        return

    try:
        profile = json.loads(profile_path.read_text())
        now = datetime.now(UTC).isoformat()
        for f in profile.get("facts", []):
            if f.get("fact_id") == fact_id:
                f["expired_at"] = now
                break
        _atomic_write_json(profile_path, profile)
    except Exception as e:
        log.error("Failed to expire fact %s in %s: %s", fact_id, entity_id, e)


def _add_fact_to_entity(entity_id: str, entity_type: str, new_fact: dict) -> None:
    ""
    profile_path = cfg.KNOWLEDGE_ENTITIES_DIR / entity_type / f"{entity_id}.json"
    if not profile_path.exists():
        return

    try:
        profile = json.loads(profile_path.read_text())
        facts = profile.get("facts", [])
        facts.append(new_fact)
        profile["facts"] = facts
        profile["updated_at"] = datetime.now(UTC).isoformat()
        _atomic_write_json(profile_path, profile)
    except Exception as e:
        log.error("Failed to add fact to %s: %s", entity_id, e)
