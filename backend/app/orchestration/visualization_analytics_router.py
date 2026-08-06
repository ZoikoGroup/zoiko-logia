"""Dynamic Visualization Selection v6 — recommendation-quality reporting and
ranking-configuration governance API.

Every endpoint here is admin-gated (require_admin): this is the internal
dashboard's backing API, not a user-facing surface, and ranking-configuration
approval specifically must be authorization-controlled per v6 requirement
15. See visualization_analytics.py and ranking_configuration.py for the
aggregation/governance logic itself — this module is routing and HTTP
status translation only.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_db
from app.domains.identity.models import User
from app.domains.identity.rbac import require_admin
from app.orchestration import ranking_configuration as ranking_configuration_service
from app.orchestration import visualization_analytics as analytics
from app.orchestration.visualization_analytics_schemas import (
    ChartTypePerformanceResponse,
    RankingConfigurationCreate,
    RankingConfigurationPublic,
    RecommendationQualitySummaryResponse,
    ReplacementMatrixResponse,
    WeightAdjustmentProposal,
)

router = APIRouter(prefix="/orchestration/analytics", tags=["Visualization Recommendation Analytics"])


def _filters(
    admin: User,
    date_from: Optional[date],
    date_to: Optional[date],
    analytical_intent: Optional[str],
    chart_family: Optional[str],
    original_chart_type: Optional[str],
    active_chart_type: Optional[str],
    renderer: Optional[str],
    selection_source: Optional[str],
    ranking_version: Optional[str],
) -> analytics.AnalyticsFilters:
    try:
        return analytics.AnalyticsFilters(
            tenant_id=admin.tenant_id, date_from=date_from, date_to=date_to,
            analytical_intent=analytical_intent, chart_family=chart_family,
            original_chart_type=original_chart_type, active_chart_type=active_chart_type,
            renderer=renderer, selection_source=selection_source, ranking_version=ranking_version,
        )
    except analytics.InvalidDateRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _group_by(group_by: Optional[list[str]]) -> tuple[str, ...]:
    try:
        return analytics.validate_group_by(group_by)
    except analytics.InvalidGroupByError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/recommendation-quality", response_model=RecommendationQualitySummaryResponse)
async def get_recommendation_quality_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    analytical_intent: Optional[str] = None,
    chart_family: Optional[str] = None,
    original_chart_type: Optional[str] = None,
    active_chart_type: Optional[str] = None,
    renderer: Optional[str] = None,
    selection_source: Optional[str] = None,
    ranking_version: Optional[str] = None,
    group_by: Optional[list[str]] = Query(default=None),
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> RecommendationQualitySummaryResponse:
    filters = _filters(
        admin, date_from, date_to, analytical_intent, chart_family, original_chart_type,
        active_chart_type, renderer, selection_source, ranking_version,
    )
    dimensions = _group_by(group_by)
    events = await analytics.fetch_events(db, filters)
    response = analytics.compute_recommendation_quality_summary(events, dimensions)
    response.date_from = date_from.isoformat() if date_from else None
    response.date_to = date_to.isoformat() if date_to else None
    return response


@router.get("/replacement-matrix", response_model=ReplacementMatrixResponse)
async def get_replacement_matrix(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    analytical_intent: Optional[str] = None,
    chart_family: Optional[str] = None,
    original_chart_type: Optional[str] = None,
    active_chart_type: Optional[str] = None,
    renderer: Optional[str] = None,
    selection_source: Optional[str] = None,
    ranking_version: Optional[str] = None,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> ReplacementMatrixResponse:
    filters = _filters(
        admin, date_from, date_to, analytical_intent, chart_family, original_chart_type,
        active_chart_type, renderer, selection_source, ranking_version,
    )
    events = await analytics.fetch_events(db, filters)
    response = analytics.compute_replacement_matrix(events)
    response.date_from = date_from.isoformat() if date_from else None
    response.date_to = date_to.isoformat() if date_to else None
    return response


@router.get("/chart-type-performance", response_model=ChartTypePerformanceResponse)
async def get_chart_type_performance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    analytical_intent: Optional[str] = None,
    chart_family: Optional[str] = None,
    original_chart_type: Optional[str] = None,
    active_chart_type: Optional[str] = None,
    renderer: Optional[str] = None,
    selection_source: Optional[str] = None,
    ranking_version: Optional[str] = None,
    group_by: Optional[list[str]] = Query(default=None),
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> ChartTypePerformanceResponse:
    filters = _filters(
        admin, date_from, date_to, analytical_intent, chart_family, original_chart_type,
        active_chart_type, renderer, selection_source, ranking_version,
    )
    dimensions = _group_by(group_by)
    events = await analytics.fetch_events(db, filters)
    response = analytics.compute_chart_type_performance(events, dimensions)
    response.date_from = date_from.isoformat() if date_from else None
    response.date_to = date_to.isoformat() if date_to else None
    return response


@router.get("/weight-proposals", response_model=list[WeightAdjustmentProposal])
async def get_weight_proposals(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    group_dimension: str = "analytical_intent",
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[WeightAdjustmentProposal]:
    filters = _filters(admin, date_from, date_to, None, None, None, None, None, None, None)
    if group_dimension not in ("analytical_intent", "chart_family"):
        raise HTTPException(status_code=422, detail='group_dimension must be "analytical_intent" or "chart_family"')
    events = await analytics.fetch_events(db, filters)
    return analytics.propose_ranking_weight_adjustments(events, group_dimension)


@router.get("/ranking-configurations", response_model=list[RankingConfigurationPublic])
async def get_ranking_configurations(
    status: Optional[str] = None,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[RankingConfigurationPublic]:
    rows = await ranking_configuration_service.list_configurations(db, status=status)
    return [RankingConfigurationPublic.model_validate(row) for row in rows]


@router.post("/ranking-configurations", response_model=RankingConfigurationPublic, status_code=201)
async def post_ranking_configuration_draft(
    payload: RankingConfigurationCreate,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> RankingConfigurationPublic:
    try:
        row = await ranking_configuration_service.create_draft(
            db, ranking_version=payload.ranking_version, effective_from=payload.effective_from,
            weights=payload.weights, created_by=admin.id,
        )
    except ranking_configuration_service.DuplicateRankingVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingConfigurationPublic.model_validate(row)


@router.post("/ranking-configurations/{configuration_id}/approve", response_model=RankingConfigurationPublic)
async def post_approve_ranking_configuration(
    configuration_id: str,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
) -> RankingConfigurationPublic:
    try:
        row = await ranking_configuration_service.approve_configuration(
            db, configuration_id=configuration_id, approver_id=admin.id,
        )
    except ranking_configuration_service.RankingConfigurationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Ranking configuration not found") from exc
    except ranking_configuration_service.SelfApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ranking_configuration_service.AlreadyReviewedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RankingConfigurationPublic.model_validate(row)
