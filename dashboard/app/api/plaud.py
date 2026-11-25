""



from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ..core.sbk_bridge import safe_path_param

router = APIRouter(prefix="/api/plaud", tags=["plaud"])


@router.get("/audio/{source_file:path}")
def get_audio(source_file: str, request: Request):
    ""



    if safe_path_param(source_file) is None:
        raise HTTPException(status_code=400, detail="Invalid source_file path")
    from ..core.plaud_write_bridge import resolve_file_id

    fid = resolve_file_id(source_file)
    if not fid:
        raise HTTPException(status_code=404, detail="file_id not found for the source_file")
    from fastapi.responses import RedirectResponse

    from tools.plaud.pl_write import _http, get_auth

    try:
        wt, api = get_auth()


        r = _http("GET", api, f"/file/temp-url/{fid}?is_opus=false", wt)
        d = r.get("data") or r
        temp_url = d.get("temp_url") if isinstance(d, dict) else None
        if temp_url:
            return RedirectResponse(url=temp_url, status_code=307)
    except Exception:  # noqa: BLE001 - fallback al proxy diretto sotto
        pass

    import urllib.request

    from tools.plaud.pl_write import _ENVELOPE, _request_id

    try:
        wt, api = get_auth()
        h = dict(_ENVELOPE)
        h["Authorization"] = f"Bearer {wt}"
        h["x-request-id"] = _request_id()
        h["User-Agent"] = "Mozilla/5.0"
        req = urllib.request.Request(f"{api}/file/download/{fid}", headers=h, method="GET")
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"audio not available: {e}") from None
    return Response(content=data, media_type="audio/ogg")


class SpeakerOverrideRequest(BaseModel):
    source_file: str
    overrides: dict[str, str]


class ApplyRenamesRequest(BaseModel):
    source_file: str
    renames: dict[str, str]
    apply: bool = False


@router.get("/recordings")
def get_recordings(
    request: Request,
    status: str | None = None,
    confidence: str | None = None,
    category: str | None = None,
    search: str | None = None,
):
    ""
    bridge = request.app.state.bridge
    return bridge.get_plaud_recordings(
        filter_status=status,
        filter_confidence=confidence,
        filter_category=category,
        search=search,
    )


@router.get("/recordings/{source_file:path}")
def get_recording_detail(source_file: str, request: Request):
    ""
    if safe_path_param(source_file) is None:
        raise HTTPException(status_code=400, detail="Invalid source_file path")
    bridge = request.app.state.bridge
    detail = bridge.get_plaud_recording_detail(source_file)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Recording not found: {source_file}")
    return detail


@router.post("/speaker-override")
def save_speaker_override(body: SpeakerOverrideRequest, request: Request):
    ""
    bridge = request.app.state.bridge
    result = bridge.save_plaud_speaker_override(body.source_file, body.overrides)
    return result


@router.get("/suggestions/{source_file:path}")
def get_suggestions(source_file: str, request: Request):
    ""
    if safe_path_param(source_file) is None:
        raise HTTPException(status_code=400, detail="Invalid source_file path")
    bridge = request.app.state.bridge
    return bridge.get_plaud_speaker_suggestions(source_file)


@router.get("/cockpit/{source_file:path}")
def get_cockpit(source_file: str, request: Request):
    ""







    if safe_path_param(source_file) is None:
        raise HTTPException(status_code=400, detail="Invalid source_file path")

    from ..core.plaud_engine_adapter import resolve_source_file

    try:
        return resolve_source_file(source_file)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Raw transcript not found: {source_file}"
        ) from None


@router.get("/stats")
def get_stats(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_plaud_review_stats()


@router.get("/names")
def get_all_names(request: Request):
    ""
    bridge = request.app.state.bridge
    return bridge.get_plaud_all_names()


@router.post("/apply-renames")
def apply_renames(body: ApplyRenamesRequest, request: Request):
    ""






    if safe_path_param(body.source_file) is None:
        raise HTTPException(status_code=400, detail="Invalid source_file path")

    from ..core.plaud_write_bridge import ApplyError, apply_renames_for_source

    try:
        return apply_renames_for_source(body.source_file, body.renames, apply=body.apply)
    except ApplyError as e:
        code = {"auth": 409, "not_found": 404, "write": 502}.get(e.kind, 500)
        raise HTTPException(status_code=code, detail=str(e)) from None
