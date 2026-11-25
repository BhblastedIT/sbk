""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("/search")
def contacts_search(request: Request, q: str = "", limit: int = Query(default=5, ge=1, le=100)):
    ""
    if not q:
        return JSONResponse({"results": []})
    bridge = request.app.state.bridge
    contacts = bridge._data.contacts
    if contacts.empty:
        return JSONResponse({"results": []})
    ql = q.lower()
    mask = contacts["name"].fillna("").str.lower().str.contains(ql, na=False) | contacts[
        "email"
    ].fillna("").str.lower().str.contains(ql, na=False)
    matched = contacts[mask].head(limit)
    results = []
    for _, row in matched.iterrows():
        pid = str(row.get("person_id", "")) if not pd.isna(row.get("person_id")) else ""
        results.append(
            {"person_id": pid, "name": str(row.get("name", "")), "email": str(row.get("email", ""))}
        )
    return JSONResponse({"results": results})


@router.get("/list")
def contacts_list(
    request: Request,
    search: str = "",
    org: str = "",
    min_score: float = 0,
    sort: str = "score",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
):
    ""
    bridge = request.app.state.bridge
    result = bridge.get_contacts_list(
        search=search,
        org_filter=org or None,
        min_score=min_score,
        sort_by=sort,
        page=page,
        per_page=per_page,
    )
    return JSONResponse(result)


@router.get("/organizations")
def contacts_organizations(request: Request):
    ""
    bridge = request.app.state.bridge
    orgs = bridge.get_contact_organizations()
    return JSONResponse({"organizations": orgs})


@router.get("/export")
def contacts_export(
    request: Request,
    search: str = "",
    org: str = "",
    min_score: float = 0,
):
    ""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    bridge = request.app.state.bridge
    result = bridge.get_contacts_list(
        search=search,
        org_filter=org or None,
        min_score=min_score,
        sort_by="score",
        page=1,
        per_page=10000,
    )

    output = io.StringIO()
    items = result.get("items", [])
    if items:
        writer = csv.DictWriter(output, fieldnames=items[0].keys())
        writer.writeheader()
        writer.writerows(items)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )
