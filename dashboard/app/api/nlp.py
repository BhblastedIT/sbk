""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/nlp", tags=["nlp"])


@router.get("/query")
def nlp_query(
    request: Request,
    tab: str = "decisions",
    search: str = "",
    speaker: str = "",
    source: str = "",
    page: int = 1,
):
    if tab not in ("decisions", "actions"):
        return JSONResponse(
            {"error": f"Invalid tab '{tab}'. Valid: decisions, actions"}, status_code=400
        )
    bridge = request.app.state.bridge
    result = bridge.query_nlp(tab=tab, search=search, speaker=speaker, source=source, page=page)
    return JSONResponse(result)


@router.get("/export")
def nlp_export(
    request: Request,
    tab: str = "decisions",
    search: str = "",
    speaker: str = "",
    source: str = "",
):
    ""
    if tab not in ("decisions", "actions"):
        tab = "decisions"
    bridge = request.app.state.bridge
    result = bridge.query_nlp(
        tab=tab, search=search, speaker=speaker, source=source, page=1, per_page=5000
    )

    output = io.StringIO()
    items = result.get("results", [])
    if items:
        writer = csv.DictWriter(output, fieldnames=items[0].keys())
        writer.writeheader()
        writer.writerows(items)

    output.seek(0)
    filename = f"nlp-{tab}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/speakers")
def nlp_speakers(request: Request):
    bridge = request.app.state.bridge
    speakers = bridge.get_nlp_speakers()
    return JSONResponse({"speakers": speakers})
