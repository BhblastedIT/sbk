""






from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import markdown as md_lib
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = _PROJECT_ROOT / "tools"
_XS_DIR = _TOOLS_DIR / "cross-source"

for p in (_TOOLS_DIR, _XS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

load_dotenv(_PROJECT_ROOT / ".env", override=True)

from app.api.admin import router as admin_router
from app.api.briefing import router as briefing_router
from app.api.chat import router as chat_router
from app.api.commitments import router as commitments_router
from app.api.contacts import router as contacts_router
from app.api.content import router as content_router
from app.api.content_engine import router as content_engine_router
from app.api.decay import router as decay_router
from app.api.emails import router as emails_router
from app.api.entities import router as entities_router
from app.api.entity_audit import router as entity_audit_router
from app.api.events import router as events_router
from app.api.flow import router as flow_router
from app.api.focus import router as focus_router
from app.api.fundraising import router as fundraising_router
from app.api.graph import router as graph_router
from app.api.insights import router as insights_router
from app.api.knowledge import router as knowledge_router
from app.api.meetings import router as meetings_router
from app.api.monitor import router as monitor_router
from app.api.ner import router as ner_router
from app.api.nlp import router as nlp_router
from app.api.notifications import router as notifications_router
from app.api.observability import router as observability_router
from app.api.performance import router as performance_router
from app.api.person import router as person_router
from app.api.pipeline import router as pipeline_router
from app.api.plaud import router as plaud_router
from app.api.relationships import router as relationships_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router
from app.api.shadows import router as shadows_router
from app.api.signals import router as signals_router
from app.api.slack_health import router as slack_health_router
from app.api.slack_msg import router as slack_msg_router
from app.api.sql import router as sql_router
from app.api.stream import router as stream_router
from app.api.thread import router as thread_router
from app.api.timeline import router as timeline_router
from app.core.conversation_store import ConversationStore
from app.core.job_store import JobStore
from app.core.log_parser import parse_log_line
from app.core.pipeline_runner import PipelineRunner
from app.core.sbk_bridge import SBKBridge
from app.core.scheduler import (
    SCHEDULE_OPTIONS,
    AutoScheduler,
)
from app.core.settings_store import SettingsStore
from sbk_config import EVENTS_DIR, OWN_EMAILS, OWNER_LABEL, OWNER_NAME, is_owner_speaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard")

_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))


_MD_EXTENSIONS = ["tables", "fenced_code", "nl2br"]


def _md_to_html(text: str) -> Markup:
    if not text:
        return Markup("")
    html = md_lib.markdown(text, extensions=_MD_EXTENSIONS)
    try:
        import nh3

        html = nh3.clean(html)
    except ImportError:
        pass
    return Markup(html)


templates.env.filters["markdown"] = _md_to_html
templates.env.globals["zip"] = zip


def _is_owner_sender(value) -> bool:
    """True when a sender, speaker or address is you (owner / own_names / own_emails in sbk.config.json)."""
    s = str(value or "").strip().lower()
    if not s:
        return False
    if s == "owner" or is_owner_speaker(s) or is_owner_speaker(s.split("<")[0]):
        return True
    return any(e in s for e in OWN_EMAILS)


templates.env.globals["owner_label"] = OWNER_LABEL
templates.env.globals["owner_first_name"] = OWNER_NAME.split()[0] if OWNER_NAME else ""
templates.env.globals["is_owner_sender"] = _is_owner_sender


def _sanitize_nan(value):
    ""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value)
    if s.lower() in ("nan", "none", ""):
        return ""
    return s


templates.env.filters["sanitize_nan"] = _sanitize_nan



_PREDICATE_LABELS = {
    "WORKS_WITH": "works with",
    "INTRODUCED_BY": "introduced by",
    "INTRODUCED_TO": "introduced to",
    "BACKGROUND": "background",
    "HAS_ROLE": "role",
    "WORKS_AT": "works at",
    "FOUNDED": "founded",
    "FOUNDER_OF": "founder of",
    "INVESTED_IN": "invested in",
    "PARTNER_OF": "partner of",
    "ADVISOR_TO": "advisor to",
    "REPORTS_TO": "reports to",
    "MANAGES": "manages",
    "MENTOR_OF": "mentor of",
    "EXPERTISE": "expertise",
    "INTERESTED_IN": "interested in",
    "LOOKING_FOR": "looking for",
    "WORKING_ON": "working on",
    "STRUGGLING_WITH": "struggling with",
}


def _predicate_label(value):
    ""
    if not value:
        return ""
    return _PREDICATE_LABELS.get(str(value).upper(), str(value).lower().replace("_", " "))


templates.env.filters["predicate_label"] = _predicate_label


def _today_it() -> str:
    """Today's date for the home page, e.g. "Monday 25 November 2026"."""
    from datetime import date as _date

    d = _date.today()
    return f"{d:%A} {d.day} {d:%B} {d.year}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    ""
    log.info("SBK Dashboard starting...")
    bridge = SBKBridge()
    await asyncio.to_thread(bridge.warmup)
    app.state.bridge = bridge
    app.state.conversation_store = ConversationStore()
    app.state.settings_store = SettingsStore()
    job_store = JobStore()
    app.state.job_store = job_store
    runner = PipelineRunner(job_store=job_store)
    app.state.runner = runner
    scheduler = AutoScheduler(runner)
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("SBK Dashboard ready (scheduler active)")
    yield
    scheduler.stop()
    log.info("SBK Dashboard shutting down")


app = FastAPI(
    title="SBK Dashboard",
    description="Personal data pipeline control panel",
    lifespan=lifespan,
)





@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    bridge = getattr(app.state, "bridge", None)
    if not bridge or not hasattr(bridge, "_data"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "warming_up"}, status_code=503)
    return {"status": "ready"}





class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    ""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        _ws_hosts = os.environ.get("SBK_WS_HOSTS", "ws://127.0.0.1:* wss://127.0.0.1:*")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://unpkg.com "
            "https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            f"connect-src 'self' {_ws_hosts}; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    ""






    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):

            if request.headers.get("upgrade", "").lower() == "websocket":
                return await call_next(request)

            if not request.headers.get("x-sbk-csrf"):
                from starlette.responses import JSONResponse

                return JSONResponse(
                    {"error": "CSRF validation failed — missing X-SBK-CSRF header"},
                    status_code=403,
                )
        return await call_next(request)





def _get_auth_creds() -> tuple[str, str]:
    ""
    try:
        from secrets_adapter import get_secret

        user = get_secret("dashboard", "user")
        passwd = get_secret("dashboard", "pass")
        if user and passwd:
            return user, passwd
    except Exception:
        pass
    return os.environ.get("SBK_AUTH_USER", ""), os.environ.get("SBK_AUTH_PASS", "")


_AUTH_USER, _AUTH_PASS = _get_auth_creds()
_AUTH_ENABLED = bool(_AUTH_USER and _AUTH_PASS)
_AUTH_SKIP = {"/health", "/ready"}

if os.environ.get("SBK_CONTAINERIZED") == "1" and not _AUTH_ENABLED:
    log.critical(
        "SECURITY WARNING: Dashboard running in container mode WITHOUT authentication. "
        "Set SBK_AUTH_USER and SBK_AUTH_PASS environment variables."
    )


class BasicAuthMiddleware(BaseHTTPMiddleware):
    ""

    async def dispatch(self, request, call_next):
        if not _AUTH_ENABLED:
            return await call_next(request)
        if request.url.path in _AUTH_SKIP:
            return await call_next(request)
        import base64
        import hmac

        auth = request.headers.get("authorization", "")
        authed = False
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, passwd = decoded.split(":", 1)
                if hmac.compare_digest(user, _AUTH_USER) and hmac.compare_digest(
                    passwd, _AUTH_PASS
                ):
                    authed = True
            except Exception:
                authed = False
        if not authed:
            return Response(
                content="Authentication required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="SBK"'},
            )



        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    ""

    _LIMITS: dict[str, int] = {"POST": 120, "PUT": 120, "DELETE": 30}
    _WINDOW = 3600
    _SKIP = {"/health", "/ready", "/api/chat/conversations"}

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, list[float]] = {}

    async def dispatch(self, request, call_next):
        method = request.method
        if method not in self._LIMITS:
            return await call_next(request)
        path = request.url.path
        if path in self._SKIP or path.startswith("/api/chat/ws"):
            return await call_next(request)
        limit = self._LIMITS[method]
        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{method}"
        import time as _time

        now = _time.monotonic()
        timestamps = self._hits.setdefault(key, [])

        cutoff = now - self._WINDOW
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] - cutoff) + 1
            return Response(
                content=json.dumps(
                    {"error": "Rate limit exceeded", "retry_after_seconds": retry_after}
                ),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)
        return await call_next(request)


class StaticCacheMiddleware(BaseHTTPMiddleware):
    ""

    _IMMUTABLE = ("/static/vendor/", "/static/dist/")

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/"):
            if any(path.startswith(p) for p in self._IMMUTABLE):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
        return response


app.add_middleware(StaticCacheMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(RateLimitMiddleware)
if _AUTH_ENABLED:
    app.add_middleware(BasicAuthMiddleware)
    log.info("Basic auth ENABLED (SBK_AUTH_USER/SBK_AUTH_PASS set)")
else:
    log.warning(
        "Basic auth DISABLED — set SBK_AUTH_USER and SBK_AUTH_PASS to secure the dashboard"
    )


app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")


app.include_router(chat_router)
app.include_router(pipeline_router)
app.include_router(stream_router)
app.include_router(settings_router)
app.include_router(decay_router)
app.include_router(monitor_router)
app.include_router(nlp_router)
app.include_router(person_router)
app.include_router(search_router)
app.include_router(graph_router)
app.include_router(entities_router)
app.include_router(contacts_router)
app.include_router(ner_router)
app.include_router(sql_router)
app.include_router(plaud_router)
app.include_router(events_router)
app.include_router(shadows_router)
app.include_router(thread_router)
app.include_router(emails_router)
app.include_router(focus_router)
app.include_router(content_router)
app.include_router(content_engine_router)
app.include_router(briefing_router)
app.include_router(meetings_router)
app.include_router(commitments_router)
app.include_router(signals_router)
app.include_router(slack_msg_router)
app.include_router(fundraising_router)
app.include_router(insights_router)
app.include_router(notifications_router)
app.include_router(admin_router)
app.include_router(slack_health_router)
app.include_router(observability_router)
app.include_router(entity_audit_router)
app.include_router(knowledge_router)
app.include_router(timeline_router)
app.include_router(flow_router)
app.include_router(relationships_router)
app.include_router(performance_router)





@app.get("/")
def root_redirect():
    ""
    return RedirectResponse(url="/graph", status_code=302)


@app.get("/home", response_class=HTMLResponse)
def home_page_legacy(request: Request):
    ""
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "page": "home",
            "today": _today_it(),
        },
    )


@app.get("/system")
def system_page():
    ""
    return RedirectResponse(url="/pipeline?tab=system", status_code=301)


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request):
    ""
    from app.bridges.performance_bridge import PerformanceBridge

    if not hasattr(request.app.state, "_perf_bridge"):
        request.app.state._perf_bridge = PerformanceBridge()
    bridge = request.app.state._perf_bridge
    meta = bridge.get_meta()

    return templates.TemplateResponse(
        "performance.html",
        {"request": request, "page": "performance", "meta": meta},
    )


@app.get("/health-overview", response_class=HTMLResponse)
def health_overview_page(request: Request):
    ""
    bridge = request.app.state.bridge
    freshness = bridge.get_freshness_report()

    ok = sum(1 for s in freshness if s.get("status") == "OK")
    stale = sum(1 for s in freshness if s.get("status") == "STALE")
    critical = sum(1 for s in freshness if s.get("status") == "CRITICO")
    missing = sum(1 for s in freshness if s.get("status") == "MISSING")

    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "page": "health",
            "summary": {
                "ok": ok,
                "stale": stale,
                "critical": critical,
                "missing": missing,
                "total": len(freshness),
            },
        },
    )


@app.get("/api-diagnostics", response_class=HTMLResponse)
def api_diagnostics_page(request: Request):
    ""
    return templates.TemplateResponse(
        "api_diagnostics.html",
        {"request": request, "page": "api-diagnostics"},
    )


@app.get("/slack-health", response_class=HTMLResponse)
def slack_health_page(request: Request):
    ""
    return templates.TemplateResponse(
        "slack_health.html",
        {"request": request, "page": "slack-health"},
    )


@app.get("/system-health", response_class=HTMLResponse)
def system_health_page(request: Request):
    ""
    return templates.TemplateResponse(
        "system_health.html",
        {"request": request, "page": "system-health"},
    )


@app.get("/entity-audit", response_class=HTMLResponse)
def entity_audit_page(request: Request):
    ""
    return templates.TemplateResponse(
        "entity_audit.html",
        {"request": request, "page": "entity-audit"},
    )


@app.get("/knowledge-health", response_class=HTMLResponse)
def knowledge_health_page(request: Request):
    ""
    return templates.TemplateResponse(
        "knowledge_health.html",
        {"request": request, "page": "knowledge-health"},
    )


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    ""
    return templates.TemplateResponse(
        "timeline.html",
        {"request": request, "page": "timeline"},
    )


@app.get("/flow", response_class=HTMLResponse)
def flow_page(request: Request):
    ""
    return templates.TemplateResponse(
        "flow.html",
        {"request": request, "page": "flow"},
    )


@app.get("/pipeline", response_class=HTMLResponse)
def pipeline_page(request: Request):
    ""
    from concurrent.futures import ThreadPoolExecutor

    bridge = request.app.state.bridge
    scheduler = request.app.state.scheduler
    runner = request.app.state.runner

    with ThreadPoolExecutor(max_workers=7) as executor:
        f_unified = executor.submit(bridge.get_pipeline_unified)
        f_grid = executor.submit(bridge.get_pipeline_grid)
        f_stats = executor.submit(bridge.get_system_stats)
        f_health = executor.submit(bridge.get_system_health)
        f_sched = executor.submit(scheduler.get_status)
        f_jobs = executor.submit(runner.list_jobs)
        f_realtime = executor.submit(bridge.get_realtime_status)

    return templates.TemplateResponse(
        "pipeline.html",
        {
            "request": request,
            "sources": f_unified.result(),
            "grid_data": f_grid.result(),
            "stats": f_stats.result(),
            "health": f_health.result(),
            "scheduler_status": f_sched.result(),
            "schedule_options": SCHEDULE_OPTIONS,
            "recent_jobs": f_jobs.result()[:5],
            "realtime_status": f_realtime.result(),
            "page": "pipeline",
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    ""
    store = request.app.state.settings_store
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": store.all_settings(),
            "page": "settings",
        },
    )


@app.get("/decay", response_class=HTMLResponse)
async def decay_page(request: Request):
    ""
    bridge = request.app.state.bridge
    decay_items, alerts = await asyncio.gather(
        asyncio.to_thread(bridge.get_decay_state),
        asyncio.to_thread(bridge.get_decay_alerts),
    )
    return templates.TemplateResponse(
        "decay.html",
        {
            "request": request,
            "decay_items": decay_items,
            "alerts": alerts,
            "page": "decay",
        },
    )


@app.get("/content", response_class=HTMLResponse)
def content_page(request: Request):
    ""
    return templates.TemplateResponse(
        "content.html",
        {
            "request": request,
            "page": "content",
        },
    )


@app.get("/content-engine", response_class=HTMLResponse)
def content_engine_page(request: Request):
    ""
    return templates.TemplateResponse(
        "content_engine.html",
        {
            "request": request,
            "page": "content-engine",
        },
    )


@app.get("/commitments", response_class=HTMLResponse)
def commitments_page(request: Request):
    ""
    return templates.TemplateResponse(
        "commitments.html",
        {
            "request": request,
            "page": "commitments",
        },
    )


@app.get("/fundraising", response_class=HTMLResponse)
def fundraising_page(request: Request, stage: str | None = None):
    ""
    bridge = request.app.state.bridge
    all_pipeline = bridge.get_fundraising_pipeline()

    stage_counts: dict[str, int] = {}
    for entry in all_pipeline:
        s = entry.get("stage", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    pipeline = [e for e in all_pipeline if e.get("stage") == stage] if stage else all_pipeline
    return templates.TemplateResponse(
        "fundraising.html",
        {
            "request": request,
            "pipeline": pipeline,
            "total": len(pipeline),
            "stage_filter": stage or "all",
            "stage_counts": stage_counts,
            "page": "fundraising",
        },
    )


@app.get("/relationships", response_class=HTMLResponse)
def relationships_page(
    request: Request,
    circle: str | None = None,
    state: str | None = None,
):
    ""
    import json as _json
    from collections import Counter as _Counter

    from sbk_config import KNOWLEDGE_RELATIONSHIPS_DIR, is_rq_v2_enabled


    _v2_on = is_rq_v2_enabled()
    rels = []
    if KNOWLEDGE_RELATIONSHIPS_DIR.exists():
        for f in sorted(KNOWLEDGE_RELATIONSHIPS_DIR.glob("*.json")):
            if f.name == "third-party-index.json":
                continue
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                data["_person_id"] = f.stem
                if _v2_on and "score_v2" in data:
                    data["score"] = data["score_v2"]
                    data["breakdown"] = data.get("breakdown_v2", data.get("breakdown", {}))
                    data["dunbar_circle"] = data.get(
                        "dunbar_circle_v2", data.get("dunbar_circle", "")
                    )
                    data["trend"] = data.get("trend_v2", data.get("trend", "stable"))
                rels.append(data)
            except (ValueError, OSError):
                continue


    cooling_alerts = [
        {
            "person": r.get("person", r.get("_person_id", "")),
            "score": r.get("score") or 0,
            "previous_score": r.get("previous_score") or r.get("score") or 0,
            "relationship_type": r.get("relationship_type", ""),
            "last_interaction": r.get("last_interaction"),
            "state": r.get("state", "active"),
        }
        for r in rels
        if r.get("trend") == "cooling" or r.get("state") == "cooling"
    ]
    cooling_alerts.sort(key=lambda r: r.get("score") or 0)


    network_circles = _Counter()
    network_states = _Counter()
    for r in rels:
        network_circles[r.get("dunbar_circle", "extended")] += 1
        network_states[r.get("state", "active")] += 1


    warm_intros = []
    for r in rels:
        for intro in r.get("warm_intros", []):
            warm_intros.append(intro)
    warm_intros.sort(key=lambda i: i.get("path_strength") or 0, reverse=True)


    scores = [r.get("score") or 0 for r in rels if r.get("score")]
    if _v2_on:
        _dims = [
            "intimacy",
            "interaction_quality",
            "structural",
            "trust_commitment",
            "negative_signals",
        ]
    else:
        _dims = ["frequency", "intensity", "reciprocity", "shared_context"]
    breakdown_avgs = {}
    for dim in _dims:
        vals = [r.get("breakdown", {}).get(dim, 0) for r in rels if r.get("breakdown")]
        breakdown_avgs[dim] = round(sum(vals) / len(vals), 3) if vals else 0

    type_counts = _Counter(r.get("relationship_type", "unknown") for r in rels)
    trend_counts = _Counter(r.get("trend", "stable") for r in rels)
    total = len(rels)
    type_dist = (
        {k: round(v / total * 100, 1) for k, v in type_counts.most_common()} if total else {}
    )

    scorecard = {
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "breakdown_averages": breakdown_avgs,
        "type_distribution": type_dist,
        "trend_summary": dict(trend_counts),
        "total": total,
    }

    return templates.TemplateResponse(
        "relationships.html",
        {
            "request": request,
            "total": total,
            "circle_filter": circle or "",
            "state_filter": state or "",
            "cooling_alerts": cooling_alerts,
            "network_circles": dict(network_circles),
            "network_states": dict(network_states),
            "network_total": total,
            "warm_intros": warm_intros,
            "scorecard": scorecard,
            "page": "relationships",
        },
    )


@app.get("/partials/commitments_table", response_class=HTMLResponse)
def partial_commitments_table(
    request: Request,
    status: str = "all",
    person: str = "",
    limit: int = 50,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_commitments(status_filter=status, person=person, limit=limit)
    return templates.TemplateResponse(
        "partials/commitments_table.html",
        {
            "request": request,
            "commitments": data["commitments"],
            "total": data["total"],
            "filtered_count": data.get("filtered_count", 0),
            "stats": data.get("stats", {}),
        },
    )


@app.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    ""
    return templates.TemplateResponse(
        "signals.html",
        {
            "request": request,
            "page": "signals",
        },
    )


@app.get("/partials/signals_table", response_class=HTMLResponse)
def partial_signals_table(
    request: Request,
    days_back: int = 30,
    min_score: float = 0.0,
    status: str = "all",
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_signals(
        days_back=days_back,
        min_score=min_score,
        status_filter=status,
        limit=50,
    )
    return templates.TemplateResponse(
        "partials/signals_table.html",
        {
            "request": request,
            "signals": data["signals"],
            "total": data["total"],
        },
    )


@app.get("/partials/home_signals", response_class=HTMLResponse)
def partial_home_signals(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_signal_stats()
    return templates.TemplateResponse(
        "partials/signals_feed.html",
        {
            "request": request,
            "recent": data.get("recent", []),
            "total": data.get("total", 0),
            "by_status": data.get("by_status", {}),
        },
    )


@app.get("/partials/content_ideas", response_class=HTMLResponse)
def partial_content_ideas(request: Request, status: str = ""):
    ""
    bridge = request.app.state.bridge
    ideas = bridge.get_content_ideas(status_filter=status or None)
    return templates.TemplateResponse(
        "partials/content_ideas.html",
        {"request": request, "ideas": ideas},
    )


@app.get("/partials/content_engine_seeds", response_class=HTMLResponse)
def partial_content_engine_seeds(request: Request):
    ""
    return templates.TemplateResponse(
        "partials/content_engine_seeds.html",
        {"request": request},
    )


@app.get("/partials/content_engine_queue", response_class=HTMLResponse)
def partial_content_engine_queue(request: Request):
    ""
    return templates.TemplateResponse(
        "partials/content_engine_queue.html",
        {"request": request},
    )


@app.get("/partials/content_engine_stats", response_class=HTMLResponse)
def partial_content_engine_stats(request: Request):
    ""
    return templates.TemplateResponse(
        "partials/content_engine_stats.html",
        {"request": request},
    )


@app.get("/partials/obs_realtime", response_class=HTMLResponse)
async def partial_obs_realtime(request: Request):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        data = await asyncio.to_thread(bridge.get_realtime_health)
        return templates.TemplateResponse(
            "partials/obs_realtime.html",
            {"request": request, "data": data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/obs_pipeline", response_class=HTMLResponse)
async def partial_obs_pipeline(request: Request):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        data = await asyncio.to_thread(bridge.get_pipeline_metrics, 24)
        return templates.TemplateResponse(
            "partials/obs_pipeline.html",
            {"request": request, "data": data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/obs_costs", response_class=HTMLResponse)
async def partial_obs_costs(request: Request):
    ""
    import asyncio

    try:
        from monitoring.api_ledger import get_cost_summary

        data = await asyncio.to_thread(get_cost_summary, 24)
        return templates.TemplateResponse(
            "partials/obs_costs.html",
            {"request": request, "data": data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/obs_detailed", response_class=HTMLResponse)
async def partial_obs_detailed(request: Request):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        data = await asyncio.to_thread(bridge.get_detailed_health)
        return templates.TemplateResponse(
            "partials/obs_detailed.html",
            {"request": request, "data": data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/obs_connections", response_class=HTMLResponse)
async def partial_obs_connections(request: Request):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        data = await asyncio.to_thread(bridge.get_connection_status)
        return templates.TemplateResponse(
            "partials/obs_connections.html",
            {"request": request, "data": data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')





@app.get("/partials/knowledge_overview", response_class=HTMLResponse)
async def partial_knowledge_overview(request: Request):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        health_data, changes = await asyncio.gather(
            asyncio.to_thread(_fetch_knowledge_health),
            asyncio.to_thread(bridge.get_knowledge_changes, "all", 7),
        )
        return templates.TemplateResponse(
            "partials/knowledge_overview.html",
            {
                "request": request,
                "health": health_data.get("domains", {}),
                "pending_review_count": health_data.get("pending_review_count", 0),
                "changes": changes,
            },
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/knowledge_domain", response_class=HTMLResponse)
async def partial_knowledge_domain(
    request: Request,
    domain: str = "person",
    page: int = 1,
    per_page: int = 50,
    sort: str = "name",
    q: str = "",
):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        data = await asyncio.to_thread(
            bridge.get_knowledge_domain_entities, domain, page, per_page, sort, q
        )
        return templates.TemplateResponse(
            "partials/knowledge_domain.html",
            {
                "request": request,
                "domain": domain,
                "entities": data.get("entities", []),
                "total": data.get("total", 0),
                "page": data.get("page", 1),
                "per_page": per_page,
                "pages": data.get("pages", 1),
                "sort": sort,
                "q": q,
            },
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/knowledge_review", response_class=HTMLResponse)
async def partial_knowledge_review(request: Request):
    ""
    import asyncio

    try:
        conflicts = await asyncio.to_thread(_fetch_knowledge_conflicts)
        return templates.TemplateResponse(
            "partials/knowledge_review.html",
            {"request": request, "conflicts": conflicts},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/knowledge_feed", response_class=HTMLResponse)
async def partial_knowledge_feed(request: Request, days: int = 7, domain: str = "all"):
    ""
    import asyncio

    try:
        bridge = request.app.state.bridge
        changes = await asyncio.to_thread(bridge.get_knowledge_changes, domain, days)
        return templates.TemplateResponse(
            "partials/knowledge_feed.html",
            {"request": request, "changes": changes},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


def _fetch_knowledge_health() -> dict:
    ""
    import json
    from datetime import UTC, datetime, timedelta

    import sbk_config as cfg

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
                if f.get("confidence", 0.5) < 0.5:
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

    pending_count = 0
    try:
        from xs_knowledge_conflict import load_pending_review

        pending_count = len(load_pending_review())
    except Exception:
        pass

    return {"domains": health, "pending_review_count": pending_count, "timestamp": now.isoformat()}


def _fetch_knowledge_conflicts() -> list:
    ""
    try:
        from xs_knowledge_conflict import load_pending_review

        return load_pending_review()
    except Exception:
        return []


@app.get("/partials/ideas_list", response_class=HTMLResponse)
def partial_ideas_list(request: Request, status: str = ""):
    ""
    bridge = request.app.state.bridge
    ideas = bridge.get_ideas(status_filter=status or None)
    return templates.TemplateResponse(
        "partials/ideas_list.html",
        {"request": request, "ideas": ideas},
    )


@app.get("/monitor")
def monitor_page():
    ""
    return RedirectResponse(url="/pipeline", status_code=301)


@app.get("/nlp", response_class=HTMLResponse)
async def nlp_page(request: Request):
    ""
    bridge = request.app.state.bridge
    nlp_data, speakers, stats = await asyncio.gather(
        asyncio.to_thread(bridge.query_nlp, tab="decisions", page=1),
        asyncio.to_thread(bridge.get_nlp_speakers),
        asyncio.to_thread(bridge.get_system_stats),
    )
    total_decisions = stats.get("decisions", 0)
    total_actions = stats.get("action_items", 0)

    return templates.TemplateResponse(
        "nlp.html",
        {
            "request": request,
            "nlp_data": nlp_data,
            "speakers": speakers,
            "total_decisions": total_decisions,
            "total_actions": total_actions,
            "page": "nlp",
        },
    )


@app.get("/person", response_class=HTMLResponse)
def person_page(request: Request):
    ""
    return templates.TemplateResponse(
        "person.html",
        {
            "request": request,
            "person": None,
            "page": "person",
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    ""
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "page": "search",
        },
    )


@app.get("/entities", response_class=HTMLResponse)
def entities_page(request: Request, reason: str = "all"):
    ""
    bridge = request.app.state.bridge
    all_items = bridge.get_entity_review(reason_filter="all")
    reason_counts = Counter(item["reason_type"] for item in all_items)
    items = all_items if reason == "all" else [i for i in all_items if i["reason_type"] == reason]

    return templates.TemplateResponse(
        "entities.html",
        {
            "request": request,
            "items": items,
            "total": len(all_items),
            "reason_filter": reason,
            "reason_counts": dict(reason_counts.most_common()),
            "page": "entities",
        },
    )


@app.get("/partials/entity_review", response_class=HTMLResponse)
def partial_entity_review(request: Request, reason: str = "all"):
    ""
    bridge = request.app.state.bridge
    items = bridge.get_entity_review(reason_filter=reason)
    return templates.TemplateResponse(
        "partials/entity_review.html",
        {
            "request": request,
            "items": items,
        },
    )


@app.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    ""
    bridge = request.app.state.bridge
    graph_stats, communities, organizations = await asyncio.gather(
        asyncio.to_thread(bridge.get_graph_stats),
        asyncio.to_thread(bridge.get_community_list),
        asyncio.to_thread(bridge.get_graph_organizations),
    )
    return templates.TemplateResponse(
        "graph.html",
        {
            "request": request,
            "graph_stats": graph_stats,
            "communities": communities,
            "organizations": organizations,
            "page": "graph",
        },
    )


@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request):
    ""
    bridge = request.app.state.bridge
    data, orgs = await asyncio.gather(
        asyncio.to_thread(bridge.get_contacts_list, page=1, per_page=50),
        asyncio.to_thread(bridge.get_contact_organizations),
    )
    return templates.TemplateResponse(
        "contacts.html",
        {
            "request": request,
            "total": data["total"],
            "organizations": orgs,
            "page": "contacts",
        },
    )


@app.get("/ner", response_class=HTMLResponse)
def ner_page(request: Request):
    ""
    bridge = request.app.state.bridge
    stats = bridge.get_ner_stats()
    return templates.TemplateResponse(
        "ner.html",
        {
            "request": request,
            "total": stats["total"],
            "type_counts": stats["by_type"],
            "page": "ner",
        },
    )


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    ""
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "page": "chat",
        },
    )


@app.get("/meetings", response_class=HTMLResponse)
def meetings_page(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_meeting_summaries(limit=20)
    return templates.TemplateResponse(
        "meetings.html",
        {
            "request": request,
            "summaries": data["summaries"],
            "total": data["total"],
            "page": "meetings",
        },
    )


@app.get("/smart-reply", response_class=HTMLResponse)
def smart_reply_page(request: Request):
    ""
    return templates.TemplateResponse(
        "smart_reply.html",
        {
            "request": request,
            "page": "smart-reply",
        },
    )


@app.get("/partials/meeting_summaries", response_class=HTMLResponse)
def partial_meeting_summaries(
    request: Request, limit: int = 20, source: str = "all", person: str = ""
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_meeting_summaries(limit=limit, source_filter=source, person_filter=person)
    return templates.TemplateResponse(
        "partials/meeting_summaries.html",
        {"request": request, "summaries": data["summaries"], "total": data["total"]},
    )


@app.get("/partials/meeting_detail/{meeting_id}", response_class=HTMLResponse)
def partial_meeting_detail(request: Request, meeting_id: str):
    ""
    bridge = request.app.state.bridge
    summary = bridge.get_meeting_summary(meeting_id)
    return templates.TemplateResponse(
        "partials/meeting_detail.html",
        {"request": request, "summary": summary},
    )


@app.get("/partials/person_meetings", response_class=HTMLResponse)
def partial_person_meetings(request: Request, pid: str = ""):
    ""
    if not pid:
        return HTMLResponse("<p class='text-xs text-base-content/40'>Person ID missing.</p>")
    bridge = request.app.state.bridge
    data = bridge.get_meetings_by_person(pid, limit=10)
    return templates.TemplateResponse(
        "partials/person_meetings.html",
        {
            "request": request,
            "summaries": data["summaries"],
            "total": data["total"],
            "person_id": pid,
        },
    )


@app.get("/sql", response_class=HTMLResponse)
def sql_page(request: Request):
    ""
    bridge = request.app.state.bridge
    views = bridge.get_duckdb_views()
    return templates.TemplateResponse(
        "sql.html",
        {
            "request": request,
            "views": views,
            "page": "sql",
        },
    )


@app.get("/shadows", response_class=HTMLResponse)
def shadows_page(request: Request):
    ""
    bridge = request.app.state.bridge
    stats = bridge.get_shadow_stats()
    return templates.TemplateResponse(
        "shadows.html",
        {
            "request": request,
            "stats": stats,
            "page": "shadows",
        },
    )


@app.get("/plaud-review", response_class=HTMLResponse)
def plaud_review_page(request: Request):
    ""
    bridge = request.app.state.bridge
    recordings = bridge.get_plaud_recordings()
    stats = bridge.get_plaud_review_stats()
    all_names = bridge.get_plaud_all_names()


    categories = sorted({r["category"] for r in recordings})

    return templates.TemplateResponse(
        "plaud_review.html",
        {
            "request": request,
            "recordings": recordings,
            "stats": stats,
            "all_names": all_names,
            "categories": categories,
            "page": "plaud-review",
        },
    )


@app.get("/plaud-mini", response_class=HTMLResponse)
def plaud_mini_page(request: Request):
    ""




    bridge = request.app.state.bridge
    recordings = bridge.get_plaud_recordings()
    stats = bridge.get_plaud_review_stats()
    return templates.TemplateResponse(
        "plaud_mini.html",
        {"request": request, "recordings": recordings[:40], "stats": stats},
    )





@app.get("/partials/global_health_banner", response_class=HTMLResponse)
def partial_global_health_banner(request: Request):
    ""
    bridge = request.app.state.bridge
    freshness = bridge.get_freshness_report()
    return templates.TemplateResponse(
        "partials/global_health_banner.html",
        {"request": request, "sources": freshness},
    )


@app.get("/partials/api_stats", response_class=HTMLResponse)
def partial_api_stats(request: Request, hours: int = 1):
    ""
    try:
        from monitoring.api_ledger import get_stats

        stats = get_stats(hours=max(1, min(hours, 24)))
        by_svc = stats["by_service"]
        return templates.TemplateResponse(
            "partials/api_stats.html",
            {
                "request": request,
                "window_hours": stats["window_hours"],
                "total": stats["total"],
                "by_service": by_svc,
                "total_read": sum(b["READ"] for b in by_svc.values()),
                "total_write": sum(b["WRITE"] for b in by_svc.values()),
                "total_errors": sum(b["errors"] for b in by_svc.values()),
                "total_rate_limited": sum(b["rate_limited"] for b in by_svc.values()),
                "recent_writes": stats["recent_writes"],
                "recent_errors": stats["recent_errors"],
            },
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/slack_health_stats", response_class=HTMLResponse)
def partial_slack_health_stats(request: Request):
    ""
    try:
        from app.api.slack_health import _collect_slack_health

        data = _collect_slack_health()
        return templates.TemplateResponse(
            "partials/slack_health_stats.html",
            {"request": request, **data},
        )
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')


@app.get("/partials/health_cards", response_class=HTMLResponse)
def partial_health_cards(request: Request):
    ""
    bridge = request.app.state.bridge
    freshness = bridge.get_freshness_report()
    source_config = bridge.get_source_config()


    script_map = {}
    for cfg in source_config:
        scripts = cfg.get("scripts", {})
        l0 = scripts.get("l0", {})
        if l0.get("exists") and l0.get("path"):
            script_map[cfg["name"]] = l0["path"]


    for s in freshness:
        s["_refresh_script"] = script_map.get(s["source"], "")

    ok = sum(1 for s in freshness if s.get("status") == "OK")
    stale = sum(1 for s in freshness if s.get("status") == "STALE")
    critical = sum(1 for s in freshness if s.get("status") == "CRITICO")
    missing = sum(1 for s in freshness if s.get("status") == "MISSING")

    return templates.TemplateResponse(
        "partials/health_cards.html",
        {
            "request": request,
            "sources": freshness,
            "summary": {
                "ok": ok,
                "stale": stale,
                "critical": critical,
                "missing": missing,
                "total": len(freshness),
            },
        },
    )


@app.get("/partials/home_focus", response_class=HTMLResponse)
def partial_home_focus(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_focus_items(max_items=3)
    return templates.TemplateResponse("partials/focus_mode.html", {"request": request, **data})


@app.get("/partials/home_decay", response_class=HTMLResponse)
def partial_home_decay(request: Request):
    ""
    alerts = request.app.state.bridge.get_decay_alerts()
    return templates.TemplateResponse(
        "partials/home_decay.html", {"request": request, "alerts": alerts[:5] if alerts else []}
    )


@app.get("/partials/home_inbox", response_class=HTMLResponse)
def partial_home_inbox(request: Request):
    ""
    data = request.app.state.bridge.get_home_inbox()
    return templates.TemplateResponse("partials/home_inbox.html", {"request": request, **data})


@app.get("/partials/home_health", response_class=HTMLResponse)
def partial_home_health(request: Request):
    ""
    data = request.app.state.bridge.get_home_summary()
    return templates.TemplateResponse("partials/home_health.html", {"request": request, **data})


@app.get("/partials/home_today", response_class=HTMLResponse)
def partial_home_today(request: Request):
    ""
    bridge = request.app.state.bridge
    tldr = bridge.get_home_tldr()
    stories = bridge.get_home_stories()
    return templates.TemplateResponse(
        "partials/home_today.html", {"request": request, "tldr": tldr, "stories": stories}
    )


@app.get("/partials/home_actions", response_class=HTMLResponse)
def partial_home_actions(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_home_actions()
    return templates.TemplateResponse("partials/home_actions.html", {"request": request, **data})


@app.get("/partials/home_reachout", response_class=HTMLResponse)
def partial_home_reachout(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_home_reachout()
    return templates.TemplateResponse("partials/home_reachout.html", {"request": request, **data})


@app.get("/partials/home_activity", response_class=HTMLResponse)
def partial_home_activity(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_home_activity()
    return templates.TemplateResponse("partials/home_activity.html", {"request": request, **data})


@app.get("/partials/stats", response_class=HTMLResponse)
def partial_stats(request: Request):
    ""
    bridge = request.app.state.bridge
    stats = bridge.get_system_stats()
    health = bridge.get_system_health()
    scheduler_status = request.app.state.scheduler.get_status()
    runner = request.app.state.runner
    recent_jobs = runner.list_jobs()[:5]
    realtime_status = bridge.get_realtime_status()
    return templates.TemplateResponse(
        "partials/stats_cards.html",
        {
            "request": request,
            "stats": stats,
            "health": health,
            "scheduler_status": scheduler_status,
            "recent_jobs": recent_jobs,
            "realtime_status": realtime_status,
        },
    )


@app.get("/partials/freshness", response_class=HTMLResponse)
def partial_freshness(request: Request):
    ""
    bridge = request.app.state.bridge
    freshness = bridge.get_freshness_report()
    return templates.TemplateResponse(
        "partials/freshness_table.html",
        {
            "request": request,
            "sources": freshness,
        },
    )


@app.get("/partials/decay_table", response_class=HTMLResponse)
def partial_decay_table(request: Request, tier: str = "all"):
    ""
    bridge = request.app.state.bridge
    decay_items = bridge.get_decay_state(tier_filter=tier)
    return templates.TemplateResponse(
        "partials/decay_table.html",
        {
            "request": request,
            "decay_items": decay_items,
        },
    )


@app.get("/partials/nlp_results", response_class=HTMLResponse)
def partial_nlp_results(
    request: Request,
    tab: str = "decisions",
    search: str = "",
    speaker: str = "",
    source: str = "",
    page: int = 1,
):
    ""
    if tab not in ("decisions", "actions"):
        tab = "decisions"
    bridge = request.app.state.bridge
    nlp_data = bridge.query_nlp(tab=tab, search=search, speaker=speaker, source=source, page=page)
    return templates.TemplateResponse(
        "partials/nlp_results.html",
        {
            "request": request,
            "nlp_data": nlp_data,
        },
    )


@app.get("/partials/person_card", response_class=HTMLResponse)
def partial_person_card(request: Request, q: str = ""):
    ""
    bridge = request.app.state.bridge

    if not q:
        return templates.TemplateResponse(
            "partials/person_card.html",
            {
                "request": request,
                "person": None,
                "rq_data": None,
                "error": None,
                "suggestions": None,
            },
        )

    person = bridge.lookup_person(q)
    if person:

        momentum = None
        if person.get("email"):
            m = bridge.get_investor_momentum(email=person["email"])
            if m.get("entry"):
                momentum = m["entry"]


        rq_data = None
        if person.get("email"):
            import json as _rq_json

            from sbk_config import KNOWLEDGE_RELATIONSHIPS_DIR, is_rq_v2_enabled

            _rq_file = KNOWLEDGE_RELATIONSHIPS_DIR / f"{person['email'].lower()}.json"
            if _rq_file.exists():
                try:
                    rq_data = _rq_json.loads(_rq_file.read_text(encoding="utf-8"))
                    if is_rq_v2_enabled() and "score_v2" in rq_data:
                        rq_data["score"] = rq_data["score_v2"]
                        rq_data["breakdown"] = rq_data.get(
                            "breakdown_v2", rq_data.get("breakdown", {})
                        )
                        rq_data["dunbar_circle"] = rq_data.get(
                            "dunbar_circle_v2", rq_data.get("dunbar_circle", "")
                        )
                        rq_data["trend"] = rq_data.get("trend_v2", rq_data.get("trend", "stable"))
                except (ValueError, OSError):
                    pass

        return templates.TemplateResponse(
            "partials/person_card.html",
            {
                "request": request,
                "person": person,
                "momentum": momentum,
                "rq_data": rq_data,
                "error": None,
                "suggestions": None,
            },
        )
    else:
        return templates.TemplateResponse(
            "partials/person_card.html",
            {
                "request": request,
                "person": None,
                "momentum": None,
                "rq_data": None,
                "error": f"Person not found: {q}",
                "suggestions": None,
            },
        )


@app.get("/api/person/suggest", response_class=HTMLResponse)
def partial_person_suggest(request: Request, q: str = ""):
    ""
    if len(q) < 2:
        return HTMLResponse("")

    bridge = request.app.state.bridge
    suggestions = bridge.suggest_persons(q, limit=10)

    if not suggestions:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "partials/person_card.html",
        {
            "request": request,
            "person": None,
            "error": None,
            "suggestions": suggestions,
        },
    )


@app.get("/partials/person_threads", response_class=HTMLResponse)
def partial_person_threads(request: Request, email: str = ""):
    ""
    bridge = request.app.state.bridge
    threads = bridge.get_person_recent_threads(email) if email else []
    return templates.TemplateResponse(
        "partials/person_threads.html",
        {"request": request, "threads": threads},
    )


@app.get("/partials/person_events", response_class=HTMLResponse)
def partial_person_events(request: Request, email: str = ""):
    ""
    bridge = request.app.state.bridge
    events = bridge.get_person_recent_events(email) if email else []
    return templates.TemplateResponse(
        "partials/person_events.html",
        {"request": request, "events": events},
    )


@app.get("/partials/person_related", response_class=HTMLResponse)
def partial_person_related(request: Request, email: str = ""):
    ""
    bridge = request.app.state.bridge
    related = bridge.get_person_related(email) if email else []
    return templates.TemplateResponse(
        "partials/person_related.html",
        {"request": request, "related": related},
    )


@app.get("/partials/person_nlp", response_class=HTMLResponse)
def partial_person_nlp(request: Request, name: str = ""):
    ""
    bridge = request.app.state.bridge
    nlp = bridge.get_person_nlp(name) if name else {"decisions": [], "actions": []}
    return templates.TemplateResponse(
        "partials/person_nlp.html",
        {"request": request, "nlp": nlp},
    )


@app.get("/partials/person_annotations", response_class=HTMLResponse)
def partial_person_annotations(request: Request, email: str = ""):
    ""
    bridge = request.app.state.bridge
    annotations = bridge.get_person_annotations(email) if email else []
    return templates.TemplateResponse(
        "partials/person_annotations.html",
        {"request": request, "annotations": annotations, "email": email},
    )


@app.get("/partials/person_facts", response_class=HTMLResponse)
def partial_person_facts(request: Request, pid: str = "", name: str = ""):
    ""
    bridge = request.app.state.bridge
    facts = bridge.get_person_facts(pid, limit=50, name=name) if pid else []
    return templates.TemplateResponse(
        "partials/person_facts.html",
        {"request": request, "facts": facts},
    )


@app.get("/partials/person_timeline", response_class=HTMLResponse)
def partial_person_timeline(request: Request, pid: str = ""):
    ""
    bridge = request.app.state.bridge
    heatmap = (
        bridge.get_person_interaction_heatmap(pid)
        if pid
        else {"months": [], "total": 0, "trend": "stable"}
    )
    forecast = bridge.get_person_decay_forecast(pid) if pid else {"available": False}
    return templates.TemplateResponse(
        "partials/person_timeline.html",
        {"request": request, "heatmap": heatmap, "forecast": forecast, "person_id": pid},
    )


@app.get("/partials/person_full_timeline", response_class=HTMLResponse)
def partial_person_full_timeline(
    request: Request,
    pid: str = "",
    limit: int = 50,
    offset: int = 0,
    source_filter: str = "all",
):
    ""
    bridge = request.app.state.bridge
    if not pid:
        return HTMLResponse("<p class='text-xs text-base-content/40'>Person ID missing.</p>")
    data = bridge.get_person_timeline(
        person_id=pid, limit=limit, offset=offset, source_filter=source_filter
    )
    return templates.TemplateResponse(
        "partials/person_full_timeline.html",
        {
            "request": request,
            "events": data["events"],
            "total": data["total"],
            "person_id": pid,
            "offset": offset,
            "limit": limit,
            "source_filter": source_filter,
        },
    )


@app.get("/partials/emails_needs_reply", response_class=HTMLResponse)
def partial_emails_needs_reply(
    request: Request,
    max_age_days: int = 7,
    limit: int = 50,
    account: str = "all",
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_emails_needing_reply(max_age_days=max_age_days, limit=limit, account=account)
    return templates.TemplateResponse(
        "partials/emails_needs_reply.html",
        {
            "request": request,
            "emails": data["emails"],
            "total": data["total"],
            "accounts_summary": data["accounts_summary"],
            "current_account": account,
        },
    )


@app.get("/partials/home_commitments", response_class=HTMLResponse)
def partial_home_commitments(request: Request):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_home_commitments(days_ahead=7, limit=5)
    return templates.TemplateResponse(
        "partials/commitments.html",
        {
            "request": request,
            "upcoming": data.get("commitments", []),
            "total": data.get("in_scadenza", 0),
            "stats": {},
            "overdue_count": 0,
            "in_scadenza": data.get("in_scadenza", 0),
        },
    )


@app.get("/partials/person_commitments", response_class=HTMLResponse)
def partial_person_commitments(request: Request, name: str = ""):
    ""
    bridge = request.app.state.bridge
    commitments = bridge.get_person_commitments(name) if name else []
    return templates.TemplateResponse(
        "partials/person_commitments.html",
        {"request": request, "commitments": commitments},
    )


@app.get("/partials/person_audit", response_class=HTMLResponse)
def partial_person_audit(request: Request, pid: str = ""):
    ""
    bridge = request.app.state.bridge
    audit = bridge.get_person_profile_audit(pid) if pid else {}
    return templates.TemplateResponse(
        "partials/person_audit.html",
        {"request": request, "audit": audit},
    )


@app.get("/partials/decay_breakdown", response_class=HTMLResponse)
def partial_decay_breakdown(request: Request, pid: str = ""):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_decay_breakdown(pid) if pid else {}
    return templates.TemplateResponse(
        "partials/decay_breakdown.html",
        {"request": request, "channels": data.get("channels", {})},
    )


@app.get("/partials/pipeline_dlq", response_class=HTMLResponse)
def partial_pipeline_dlq(request: Request):
    ""
    try:
        from pipeline_dlq import get_all_failures

        failures = get_all_failures(include_resolved=False)
    except Exception:
        failures = []
    return templates.TemplateResponse(
        "partials/pipeline_dlq.html",
        {"request": request, "failures": failures},
    )


@app.get("/partials/merge_suggestions", response_class=HTMLResponse)
def partial_merge_suggestions(request: Request):
    ""
    from sbk_config import ENRICHED_DIR

    suggestions_file = ENRICHED_DIR / "merge-suggestions.json"
    suggestions = []
    if suggestions_file.exists():
        try:
            suggestions = json.loads(suggestions_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return templates.TemplateResponse(
        "partials/merge_suggestions.html",
        {"request": request, "suggestions": suggestions[:50]},
    )


@app.get("/partials/entity_audit_list", response_class=HTMLResponse)
def partial_entity_audit_list(
    request: Request,
    min_confidence: float = 0.0,
    status: str = "",
    limit: int = 100,
):
    ""
    from app.api.entity_audit import _load_suggestions

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

    return templates.TemplateResponse(
        "partials/entity_audit_list.html",
        {"request": request, "items": items},
    )


@app.get("/partials/person_deep_facts", response_class=HTMLResponse)
def partial_person_deep_facts(request: Request, pid: str = "", category: str = ""):
    ""
    bridge = request.app.state.bridge
    facts = bridge.get_person_deep_facts(person_id=pid, category=category) if pid else []
    return templates.TemplateResponse(
        "partials/person_deep_facts.html",
        {"request": request, "facts": facts},
    )


@app.get("/partials/smart_intros", response_class=HTMLResponse)
def partial_smart_intros(request: Request, pid: str = "", limit: int = 10):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_smart_intro_suggestions(person_id=pid or None, limit=limit)
    return templates.TemplateResponse(
        "partials/smart_intros.html",
        {"request": request, **data},
    )


@app.get("/partials/person_context", response_class=HTMLResponse)
def partial_person_context(request: Request, pid: str = ""):
    ""
    bridge = request.app.state.bridge
    context = bridge.get_person_context(pid) if pid else {}
    return templates.TemplateResponse(
        "partials/person_context.html",
        {"request": request, "context": context},
    )


@app.get("/partials/reconnection_suggestions", response_class=HTMLResponse)
def partial_reconnection_suggestions(request: Request, limit: int = 10):
    ""
    bridge = request.app.state.bridge
    suggestions = bridge.get_reconnection_suggestions(limit=limit)
    return templates.TemplateResponse(
        "partials/reconnection_suggestions.html",
        {"request": request, "suggestions": suggestions},
    )


@app.post("/partials/search_results", response_class=HTMLResponse)
async def partial_search_results(request: Request):
    ""
    form = await request.form()
    results_json = form.get("results_json", "{}")
    try:
        data = json.loads(results_json)
    except (json.JSONDecodeError, TypeError):
        data = {}

    results = data.get("results", [])
    return templates.TemplateResponse(
        "partials/search_results.html",
        {
            "request": request,
            "results": results,
        },
    )


@app.post("/partials/synthesis", response_class=HTMLResponse)
async def partial_synthesis(request: Request):
    ""
    form = await request.form()
    answer = form.get("answer", "")
    return templates.TemplateResponse(
        "partials/synthesis.html",
        {
            "request": request,
            "answer": answer,
        },
    )


@app.get("/partials/jobs", response_class=HTMLResponse)
def partial_jobs(request: Request):
    ""
    runner = request.app.state.runner
    job_store: JobStore = request.app.state.job_store


    running_jobs = runner.list_jobs()
    running_ids = {j["job_id"] for j in running_jobs}


    stored = job_store.get_jobs(limit=50)
    for sj in stored:
        if sj["job_id"] not in running_ids:

            summary = sj.get("summary") or {}
            started = sj.get("started_at", "")

            if "T" in started:
                started = started.split("T")[1][:8]
            finished = sj.get("finished_at", "")
            if finished and "T" in finished:
                finished = finished.split("T")[1][:8]
            running_jobs.append(
                {
                    "job_id": sj["job_id"],
                    "source": sj.get("source", ""),
                    "script": sj.get("script", ""),
                    "stage": sj.get("stage", ""),
                    "started_at": started,
                    "finished_at": finished or None,
                    "status": sj.get("status", ""),
                    "exit_code": sj.get("exit_code"),
                    "duration": sj.get("duration", ""),
                    "log_line_count": len(sj.get("log_lines", [])),
                    "error_count": summary.get("error_count", 0),
                    "warning_count": summary.get("warning_count", 0),
                    "total_rows": summary.get("metrics", {}).get("rows", 0),
                    "stored": True,
                }
            )

    return templates.TemplateResponse(
        "partials/jobs_table.html",
        {
            "request": request,
            "jobs": running_jobs,
        },
    )


@app.get("/partials/job_log/{job_id}", response_class=HTMLResponse)
def partial_job_log(request: Request, job_id: str):
    ""
    runner = request.app.state.runner
    job_store: JobStore = request.app.state.job_store


    job = runner.get_job(job_id)
    if job:
        return templates.TemplateResponse(
            "partials/job_log_detail.html",
            {
                "request": request,
                "job_id": job_id,
                "parsed_lines": job.parsed_lines,
                "summary": job.summary,
                "status": job.status,
                "error": None,
            },
        )


    stored = job_store.get_job(job_id)
    if stored:

        parsed = [parse_log_line(line) for line in stored.get("log_lines", [])]
        return templates.TemplateResponse(
            "partials/job_log_detail.html",
            {
                "request": request,
                "job_id": job_id,
                "parsed_lines": parsed,
                "summary": stored.get("summary"),
                "status": stored.get("status", ""),
                "error": None,
            },
        )

    return templates.TemplateResponse(
        "partials/job_log_detail.html",
        {
            "request": request,
            "job_id": job_id,
            "parsed_lines": [],
            "summary": None,
            "status": "",
            "error": f"Job '{job_id}' not found.",
        },
    )


@app.get("/partials/voice_memo_panel", response_class=HTMLResponse)
def partial_voice_memo_panel(request: Request):
    ""
    bridge = request.app.state.bridge
    vm = bridge.get_voice_memo_stats()
    return templates.TemplateResponse(
        "partials/voice_memo_panel.html",
        {"request": request, "vm": vm},
    )


@app.get("/partials/pipeline_grid", response_class=HTMLResponse)
def partial_pipeline_grid(request: Request):
    ""
    bridge = request.app.state.bridge
    grid_data = bridge.get_pipeline_grid()
    return templates.TemplateResponse(
        "partials/pipeline_grid.html",
        {
            "request": request,
            "grid_data": grid_data,
        },
    )


@app.get("/partials/pipeline_unified", response_class=HTMLResponse)
def partial_pipeline_unified(request: Request):
    ""
    bridge = request.app.state.bridge
    unified = bridge.get_pipeline_unified()
    return templates.TemplateResponse(
        "partials/pipeline_unified.html",
        {
            "request": request,
            "sources": unified,
            "schedule_options": SCHEDULE_OPTIONS,
        },
    )


@app.get("/partials/pipeline_sources", response_class=HTMLResponse)
def partial_pipeline_sources(request: Request):
    ""
    bridge = request.app.state.bridge
    unified = bridge.get_pipeline_unified()
    return templates.TemplateResponse(
        "partials/pipeline_unified.html",
        {
            "request": request,
            "sources": unified,
            "schedule_options": SCHEDULE_OPTIONS,
        },
    )


@app.get("/partials/event_log", response_class=HTMLResponse)
def partial_event_log(request: Request):
    ""
    import json as _json

    _events_dir = EVENTS_DIR
    events = []
    if _events_dir.exists():
        for f in sorted(_events_dir.glob("*.json"), reverse=True):
            if len(events) >= 50:
                break
            try:
                data = _json.loads(f.read_text())
                events.append(data)
            except (_json.JSONDecodeError, OSError):
                continue
    return templates.TemplateResponse(
        "partials/event_log.html",
        {"request": request, "events": events},
    )


@app.get("/partials/monitor_health", response_class=HTMLResponse)
def partial_monitor_health(request: Request):
    ""
    bridge = request.app.state.bridge
    monitor_health = bridge.get_monitor_health()
    return templates.TemplateResponse(
        "partials/monitor_health.html",
        {
            "request": request,
            "monitor_health": monitor_health,
        },
    )


@app.get("/partials/contacts_table", response_class=HTMLResponse)
def partial_contacts_table(
    request: Request,
    search: str = "",
    org: str = "",
    min_score: float = 0,
    sort: str = "score",
    page: int = 1,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_contacts_list(
        search=search, org_filter=org or None, min_score=min_score, sort_by=sort, page=page
    )
    return templates.TemplateResponse(
        "partials/contacts_table.html",
        {
            "request": request,
            "items": data["items"],
            "total": data["total"],
            "page": data["page"],
            "pages": data["pages"],
        },
    )


@app.get("/partials/ner_results", response_class=HTMLResponse)
def partial_ner_results(
    request: Request,
    entity_type: str = "all",
    search: str = "",
    speaker: str = "",
    page: int = 1,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.query_ner(
        entity_type=entity_type if entity_type != "all" else None,
        search=search or None,
        speaker=speaker or None,
        page=page,
    )
    return templates.TemplateResponse(
        "partials/ner_results.html",
        {
            "request": request,
            "items": data["items"],
            "total": data["total"],
            "page": data["page"],
            "pages": data["pages"],
        },
    )


@app.get("/partials/shadows_table", response_class=HTMLResponse)
def partial_shadows_table(
    request: Request,
    category: str = "all",
    search: str = "",
    sort: str = "score",
    page: int = 1,
):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_shadow_list(
        category=category,
        search=search,
        sort_by=sort,
        page=page,
    )
    return templates.TemplateResponse(
        "partials/shadows_table.html",
        {
            "request": request,
            "items": data["items"],
            "total": data["total"],
            "page": data["page"],
            "pages": data["pages"],
        },
    )


@app.get("/partials/plaud_recordings", response_class=HTMLResponse)
def partial_plaud_recordings(
    request: Request,
    status: str = "",
    confidence: str = "",
    category: str = "",
    search: str = "",
):
    ""
    bridge = request.app.state.bridge
    recordings = bridge.get_plaud_recordings(
        filter_status=status or None,
        filter_confidence=confidence or None,
        filter_category=category or None,
        search=search or None,
    )
    return templates.TemplateResponse(
        "partials/plaud_recordings.html",
        {"request": request, "recordings": recordings},
    )


@app.get("/partials/plaud_recording_detail", response_class=HTMLResponse)
def partial_plaud_recording_detail(request: Request, file: str = "", idx: int = 0):
    ""
    bridge = request.app.state.bridge
    detail = bridge.get_plaud_recording_detail(file)
    suggestions = bridge.get_plaud_speaker_suggestions(file) if file else []
    return templates.TemplateResponse(
        "partials/plaud_recording_detail.html",
        {"request": request, "detail": detail, "suggestions": suggestions[:15], "badge_idx": idx},
    )


@app.get("/partials/thread/{source_type}/{source_id:path}", response_class=HTMLResponse)
def partial_thread_viewer(request: Request, source_type: str, source_id: str):
    ""
    bridge = request.app.state.bridge
    data = bridge.get_thread(source_type, source_id)
    return templates.TemplateResponse(
        "partials/thread_viewer.html",
        {"request": request, "source_type": source_type, "source_id": source_id, **data},
    )
