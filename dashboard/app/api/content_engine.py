""





from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import CONTENT_QUEUE_FILE, CONTENT_SEEDS_FILE

logger = logging.getLogger("dashboard.content-engine")

router = APIRouter(prefix="/api/content-engine", tags=["content-engine"])





def _load_json(path: Path) -> dict:
    ""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None





@router.get("/seeds")
def list_seeds(
    pillar: str = "",
    platform: str = "",
    sensitivity: str = "",
    min_score: float = 0.0,
):
    ""
    data = _load_json(CONTENT_SEEDS_FILE)
    seeds = data.get("seeds", [])

    if pillar:
        seeds = [s for s in seeds if s.get("pillar") == pillar]
    if platform:
        seeds = [s for s in seeds if s.get("platform_scores", {}).get(platform, 0) > 0.5]
    if sensitivity:
        seeds = [s for s in seeds if s.get("sensitivity") == sensitivity]
    if min_score > 0:
        seeds = [s for s in seeds if s.get("content_score", 0) >= min_score]

    return {"seeds": seeds, "total": len(seeds), "generated_at": data.get("generated_at", "")}


@router.get("/seeds/{seed_id}")
def get_seed(seed_id: str):
    ""
    data = _load_json(CONTENT_SEEDS_FILE)
    for seed in data.get("seeds", []):
        if seed.get("seed_id") == seed_id:
            return {"seed": seed}
    return JSONResponse({"error": f"Seed '{seed_id}' not found"}, status_code=404)


@router.post("/seeds/refresh")
async def refresh_seeds():
    ""
    script = _PROJECT_ROOT / "tools" / "content" / "ct-mine-seeds.py"
    if not script.exists():
        return JSONResponse({"error": "Mining script not found"}, status_code=500)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(script), "--incremental"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            logger.error(f"Mining failed: {result.stderr[:500]}")
            return JSONResponse(
                {"error": "Mining failed"},
                status_code=500,
            )

        data = _load_json(CONTENT_SEEDS_FILE)
        return {
            "status": "ok",
            "seeds_count": len(data.get("seeds", [])),
            "generated_at": data.get("generated_at", ""),
        }
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Mining timed out (120s)"}, status_code=504)





@router.get("/queue")
def list_queue(
    platform: str = "",
    status: str = "",
    sensitivity: str = "",
):
    ""
    data = _load_json(CONTENT_QUEUE_FILE)
    drafts = data.get("drafts", [])

    if platform:
        drafts = [d for d in drafts if d.get("platform") == platform]
    if status:
        drafts = [d for d in drafts if d.get("status") == status]
    if sensitivity:
        drafts = [d for d in drafts if d.get("sensitivity") == sensitivity]

    return {"drafts": drafts, "total": len(drafts), "generated_at": data.get("generated_at", "")}


@router.put("/queue/{draft_id}")
async def update_draft(request: Request, draft_id: str):
    ""
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    data = _load_json(CONTENT_QUEUE_FILE)
    drafts = data.get("drafts", [])

    for i, draft in enumerate(drafts):
        if draft.get("draft_id") == draft_id:

            for field in ("status", "content", "notes"):
                if field in body:
                    drafts[i][field] = body[field]
            data["drafts"] = drafts
            _save_json(CONTENT_QUEUE_FILE, data)
            return {"draft": drafts[i]}

    return JSONResponse({"error": f"Draft '{draft_id}' not found"}, status_code=404)


@router.post("/generate")
async def generate_drafts():
    ""
    script = _PROJECT_ROOT / "tools" / "content" / "ct-generate-drafts.py"
    if not script.exists():
        return JSONResponse({"error": "Generation script not found"}, status_code=500)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            logger.error(f"Generation failed: {result.stderr[:500]}")
            return JSONResponse(
                {"error": "Generation failed"},
                status_code=500,
            )
        data = _load_json(CONTENT_QUEUE_FILE)
        return {
            "status": "ok",
            "drafts_count": len(data.get("drafts", [])),
            "generated_at": data.get("generated_at", ""),
        }
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Generation timed out (300s)"}, status_code=504)





@router.get("/stats")
def get_stats():
    ""
    seeds_data = _load_json(CONTENT_SEEDS_FILE)
    queue_data = _load_json(CONTENT_QUEUE_FILE)

    seeds = seeds_data.get("seeds", [])
    drafts = queue_data.get("drafts", [])


    pillar_counts: dict[str, int] = {}
    for s in seeds:
        p = s.get("pillar", "unknown")
        pillar_counts[p] = pillar_counts.get(p, 0) + 1


    sensitivity_counts: dict[str, int] = {}
    for s in seeds:
        level = s.get("sensitivity", "unknown")
        sensitivity_counts[level] = sensitivity_counts.get(level, 0) + 1


    platform_counts: dict[str, int] = {}
    for d in drafts:
        p = d.get("platform", "unknown")
        platform_counts[p] = platform_counts.get(p, 0) + 1


    status_counts: dict[str, int] = {}
    for d in drafts:
        st = d.get("status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "seeds_total": len(seeds),
        "seeds_by_pillar": pillar_counts,
        "seeds_by_sensitivity": sensitivity_counts,
        "drafts_total": len(drafts),
        "drafts_by_platform": platform_counts,
        "drafts_by_status": status_counts,
        "seeds_generated_at": seeds_data.get("generated_at", ""),
        "drafts_generated_at": queue_data.get("generated_at", ""),
    }
