""






from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/sql", tags=["sql"])

MAX_ROWS = 1000


class SqlQuery(BaseModel):
    sql: str = Field(..., min_length=1, max_length=5000)


@router.get("/views")
def sql_views(request: Request):
    ""
    bridge = request.app.state.bridge
    views = bridge.get_duckdb_views()
    return JSONResponse({"views": views})


@router.post("/query")
async def sql_query(request: Request, body: SqlQuery):
    ""




    sql = body.sql.strip()
    bridge = request.app.state.bridge
    result = await asyncio.to_thread(bridge.run_duckdb_query, sql, MAX_ROWS)

    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)
