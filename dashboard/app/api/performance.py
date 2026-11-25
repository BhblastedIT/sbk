""












from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("sbk.api.performance")

router = APIRouter(prefix="/api/performance", tags=["performance"])


def _get_bridge(request: Request):
    ""
    if not hasattr(request.app.state, "_perf_bridge"):
        from app.bridges.performance_bridge import PerformanceBridge

        request.app.state._perf_bridge = PerformanceBridge()
    return request.app.state._perf_bridge


@router.get("/heatmap")
def get_heatmap(request: Request, months: int = Query(default=12, ge=1, le=60)):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_heatmap_data(months=months)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in heatmap endpoint")
        return JSONResponse({"error": "Failed to load heatmap data"}, status_code=500)


@router.get("/anomalies")
def get_anomalies(request: Request):
    ""
    try:
        bridge = _get_bridge(request)
        anomalies = bridge.get_anomalies()
        return JSONResponse(anomalies)
    except Exception:
        log.exception("Error in anomalies endpoint")
        return JSONResponse({"error": "Failed to load anomalies"}, status_code=500)


@router.get("/timeline")
def get_timeline(
    request: Request,
    period: int = Query(default=30, ge=1, le=730),
    metrics: str = "",
):
    ""





    try:
        bridge = _get_bridge(request)
        metric_list = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
        data = bridge.get_timeline_data(period_days=period, metrics=metric_list)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in timeline endpoint")
        return JSONResponse({"error": "Failed to load timeline data"}, status_code=500)


@router.get("/scatter")
def get_scatter(
    request: Request,
    metric_a: str = "sleep_score",
    metric_b: str = "email_avg_sentiment",
):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_scatter_data(metric_a, metric_b)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in scatter endpoint")
        return JSONResponse({"error": "Failed to load scatter data"}, status_code=500)


@router.get("/correlations")
def get_correlations(request: Request, top_n: int = Query(default=10, ge=1, le=100)):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_correlations_summary(top_n=top_n)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in correlations endpoint")
        return JSONResponse({"error": "Failed to load correlations"}, status_code=500)


@router.get("/blood-trends")
def get_blood_trends(request: Request, marker: str = "vitamin_d"):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_blood_trends(marker)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in blood-trends endpoint")
        return JSONResponse({"error": "Failed to load blood trends"}, status_code=500)


@router.get("/weekly-score")
def get_weekly_score(request: Request, weeks: int = Query(default=12, ge=1, le=104)):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_weekly_score(weeks=weeks)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in weekly-score endpoint")
        return JSONResponse({"error": "Failed to load weekly score"}, status_code=500)


@router.get("/data-coverage")
def get_data_coverage(request: Request):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_data_coverage()
        return JSONResponse(data)
    except Exception:
        log.exception("Error in data-coverage endpoint")
        return JSONResponse({"error": "Failed to load data coverage"}, status_code=500)


@router.get("/correlation-matrix")
def get_correlation_matrix(
    request: Request,
    min_r: float = Query(default=0.0, ge=0.0, le=1.0),
    phase: str = "",
):
    ""
    try:
        bridge = _get_bridge(request)
        phase_val = phase if phase else None
        data = bridge.get_correlation_matrix(min_r=min_r, phase=phase_val)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in correlation-matrix endpoint")
        return JSONResponse({"error": "Failed to load correlation matrix"}, status_code=500)


@router.get("/blood-panel")
def get_blood_panel(request: Request, panel: str = "all"):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_blood_panel(panel=panel)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in blood-panel endpoint")
        return JSONResponse({"error": "Failed to load blood panel"}, status_code=500)


@router.get("/intervention-timeline")
def get_intervention_timeline(
    request: Request,
    marker: str = "vitamin_d",
    months: int = Query(default=24, ge=1, le=120),
):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_intervention_timeline(marker=marker, months=months)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in intervention-timeline endpoint")
        return JSONResponse({"error": "Failed to load intervention timeline"}, status_code=500)


@router.get("/circadian")
def get_circadian(
    request: Request,
    period: int = Query(default=90, ge=7, le=365),
    metric: str = "meetings",
):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_circadian_data(period_days=period, metric=metric)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in circadian endpoint")
        return JSONResponse({"error": "Failed to load circadian data"}, status_code=500)


@router.get("/behavioral-pattern")
def get_behavioral_pattern(
    request: Request,
    min_weeks: int = Query(default=8, ge=2, le=52),
    percentile: int = Query(default=25, ge=5, le=50),
):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_behavioral_pattern(min_weeks=min_weeks, percentile=percentile)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in behavioral-pattern endpoint")
        return JSONResponse({"error": "Failed to load behavioral pattern"}, status_code=500)


@router.get("/daily/{date_str}")
def get_daily_detail(request: Request, date_str: str):
    ""
    try:
        bridge = _get_bridge(request)
        data = bridge.get_daily_detail(date_str)
        return JSONResponse(data)
    except Exception:
        log.exception("Error in daily detail endpoint")
        return JSONResponse({"error": "Failed to load daily detail"}, status_code=500)
