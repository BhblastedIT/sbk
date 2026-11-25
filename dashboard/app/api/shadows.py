""










from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class AliasRequest(BaseModel):
    alias: str
    full_name: str


class NameRequest(BaseModel):
    name: str


class CompanyRequest(BaseModel):
    canonical_name: str
    company: str


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sbk_config import CONFIG_NICKNAME_ALIASES, OWNER_FIRST_NAME, OWNER_NAME, SHADOW_FILTERS_FILE

log = logging.getLogger("dashboard.shadows")
router = APIRouter(prefix="/api/shadows", tags=["shadows"])


async def _parse_json(request: Request):
    ""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError):
        return None



# Aliases the page shows as fixed: your first name (sbk.config.json "owner") and your
# sbk.config.json "nickname_aliases". The ones you add on this page go to shadow-filters.json.
_BASELINE_ALIASES: dict[str, str] = {
    **({OWNER_FIRST_NAME: OWNER_NAME.lower()} if OWNER_FIRST_NAME else {}),
    **CONFIG_NICKNAME_ALIASES,
}
_BASELINE_NOISE: set[str] = {
    "legal team",
    "family office",
    "family business",
    "has a family",
    "consulente esterno",
    "consulente del lavoro",
    "board member",
    "board of directors",
}
# Companies are not built in: you add yours on the Shadows page (shadow-filters.json).
_BASELINE_COMPANIES: set[str] = set()


def _load_filters() -> dict:
    ""
    if not SHADOW_FILTERS_FILE.exists():
        return {"aliases": {}, "noise_patterns": [], "company_map": []}
    try:
        return json.loads(SHADOW_FILTERS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"aliases": {}, "noise_patterns": [], "company_map": []}


def _save_filters(data: dict) -> None:
    ""
    SHADOW_FILTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_FILTERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.rename(SHADOW_FILTERS_FILE)


@router.get("/list")
def shadows_list(
    request: Request,
    category: str = "all",
    search: str = "",
    min_score: float = 0,
    min_mentions: int = 0,
    sort: str = "score",
    page: int = 1,
    per_page: int = 50,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_shadow_list(
        category=category,
        search=search,
        min_score=min_score,
        min_mentions=min_mentions,
        sort_by=sort,
        page=page,
        per_page=per_page,
    )
    return data


@router.get("/stats")
def shadows_stats(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_shadow_stats()


@router.get("/active-filters")
def get_active_filters():
    ""
    filters = _load_filters()


    all_aliases = dict(_BASELINE_ALIASES)
    all_aliases.update(filters.get("aliases", {}))


    all_noise = set(_BASELINE_NOISE)
    all_noise.update(filters.get("noise_patterns", []))


    all_companies = set(_BASELINE_COMPANIES)
    all_companies.update(filters.get("company_map", []))

    return {
        "aliases": [
            {"key": k, "value": v, "custom": k not in _BASELINE_ALIASES}
            for k, v in sorted(all_aliases.items())
        ],
        "noise": [{"phrase": p, "custom": p not in _BASELINE_NOISE} for p in sorted(all_noise)],
        "companies": [
            {"name": c, "custom": c not in _BASELINE_COMPANIES} for c in sorted(all_companies)
        ],
    }


@router.post("/add-alias")
async def add_alias(req: AliasRequest):
    ""
    alias = req.alias.strip().lower()
    full_name = req.full_name.strip().lower()

    if not alias or not full_name:
        return JSONResponse({"ok": False, "error": "alias and full_name required"}, status_code=400)


    if alias in _BASELINE_ALIASES:
        return JSONResponse(
            {"ok": False, "error": f"Alias '{alias}' is a baseline entry"}, status_code=400
        )

    filters = _load_filters()
    if alias in filters.get("aliases", {}):
        return JSONResponse(
            {"ok": False, "error": f"Alias '{alias}' already exists"}, status_code=400
        )

    filters.setdefault("aliases", {})[alias] = full_name
    _save_filters(filters)

    log.info("Added nickname alias: %s -> %s", alias, full_name)
    return {"ok": True, "alias": alias, "full_name": full_name}


@router.post("/remove-alias")
async def remove_alias(req: NameRequest):
    ""
    alias = req.name.strip().lower()
    if not alias:
        return JSONResponse({"ok": False, "error": "alias required"}, status_code=400)

    filters = _load_filters()
    aliases = filters.get("aliases", {})
    if alias not in aliases:
        return JSONResponse({"ok": False, "error": f"Alias '{alias}' not found"}, status_code=404)

    del aliases[alias]
    _save_filters(filters)

    log.info("Removed nickname alias: %s", alias)
    return {"ok": True, "alias": alias}


@router.post("/add-noise")
async def add_noise(request: Request):
    ""
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)
    phrases = body.get("phrases", [])

    if not phrases:
        return JSONResponse({"ok": False, "error": "phrases list required"}, status_code=400)

    filters = _load_filters()
    existing = set(filters.get("noise_patterns", []))

    added = []
    for phrase in phrases:
        p = phrase.strip().lower()
        if not p or p in existing or p in _BASELINE_NOISE:
            continue
        existing.add(p)
        added.append(p)

    if added:
        filters["noise_patterns"] = sorted(existing)
        _save_filters(filters)
        log.info("Added %d noise phrases: %s", len(added), added)

    return {"ok": True, "added": added}


@router.post("/remove-noise")
async def remove_noise(request: Request):
    ""
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)
    phrase = body.get("phrase", "").strip().lower()
    if not phrase:
        return JSONResponse({"ok": False, "error": "phrase required"}, status_code=400)

    filters = _load_filters()
    noise = filters.get("noise_patterns", [])
    if phrase not in noise:
        return JSONResponse({"ok": False, "error": f"Phrase '{phrase}' not found"}, status_code=404)

    noise.remove(phrase)
    filters["noise_patterns"] = noise
    _save_filters(filters)

    log.info("Removed noise phrase: %s", phrase)
    return {"ok": True, "phrase": phrase}


@router.post("/add-company")
async def add_company(request: Request):
    ""
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)
    companies = body.get("companies", [])

    if not companies:
        return JSONResponse({"ok": False, "error": "companies list required"}, status_code=400)

    filters = _load_filters()
    existing = set(filters.get("company_map", []))

    added = []
    for company in companies:
        c = company.strip().lower()
        if not c or c in existing or c in _BASELINE_COMPANIES:
            continue
        existing.add(c)
        added.append(c)

    if added:
        filters["company_map"] = sorted(existing)
        _save_filters(filters)
        log.info("Added %d company names: %s", len(added), added)

    return {"ok": True, "added": added}


@router.post("/remove-company")
async def remove_company(request: Request):
    ""
    body = await _parse_json(request)
    if body is None:
        return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)
    company = body.get("company", "").strip().lower()
    if not company:
        return JSONResponse({"ok": False, "error": "company required"}, status_code=400)

    filters = _load_filters()
    companies = filters.get("company_map", [])
    if company not in companies:
        return JSONResponse(
            {"ok": False, "error": f"Company '{company}' not found"}, status_code=404
        )

    companies.remove(company)
    filters["company_map"] = companies
    _save_filters(filters)

    log.info("Removed company: %s", company)
    return {"ok": True, "company": company}


@router.post("/rerun")
async def rerun_extraction(request: Request):
    ""
    import asyncio
    import subprocess

    script = _TOOLS_DIR / "cross-source" / "xs-l3-shadow-extract.py"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["uv", "run", "python", str(script), "--force"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(_PROJECT_ROOT),
        )
        count = 0
        for line in result.stderr.split("\n"):
            if "shadow contacts extracted" in line:
                m = re.search(r"(\d+)\s+shadow contacts extracted", line)
                if m:
                    count = int(m.group(1))

        bridge = request.app.state.bridge
        bridge._shadow_cache = None
        bridge._shadow_cache_ts = 0

        if result.returncode == 0:
            log.info("Shadow re-extraction complete: %d shadows", count)
            return {"ok": True, "count": count}
        else:
            log.error("Shadow re-extraction failed: %s", result.stderr[-500:])
            return JSONResponse(
                {"ok": False, "error": "Shadow extraction failed"},
                status_code=500,
            )
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": "Timeout (5 min)"}, status_code=504)
    except Exception as e:
        log.error("Shadow re-extraction error: %s", e)
        return JSONResponse({"ok": False, "error": "Internal error"}, status_code=500)
