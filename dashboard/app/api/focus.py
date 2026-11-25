""







from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/focus-mode", tags=["focus"])


@router.get("")
def focus_mode_json(request: Request, max_items: int = 3):
    ""
    bridge = request.app.state.bridge
    return bridge.get_focus_items(max_items=max_items)


@router.get("/partial", response_class=HTMLResponse)
def focus_mode_partial(request: Request, max_items: int = 3):
    ""
    from pathlib import Path

    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
    bridge = request.app.state.bridge
    data = bridge.get_focus_items(max_items=max_items)
    return templates.TemplateResponse(
        "partials/focus_mode.html",
        {"request": request, **data},
    )


@router.post("/refresh")
def focus_mode_refresh(request: Request, max_items: int = 3):
    ""
    bridge = request.app.state.bridge
    return bridge.get_focus_items(max_items=max_items)
