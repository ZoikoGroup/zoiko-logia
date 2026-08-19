from __future__ import annotations

import asyncio

from app.orchestration.statistics.dbnomics_provider import DBnomicsStatisticalProvider
from app.orchestration.statistics.engine import analyse_series
from app.orchestration.statistics.models import StatisticalAnalysisAttempt
from app.orchestration.statistics.planner import plan_statistical_query
from app.orchestration.statistics.providers import StatisticalProviderRegistry


async def analyse_statistical_query(
    query: str,
    registry: StatisticalProviderRegistry | None = None,
) -> StatisticalAnalysisAttempt:
    plan = plan_statistical_query(query)
    if plan is None:
        return StatisticalAnalysisAttempt(handled=False)
    if plan.geography_code is None:
        return StatisticalAnalysisAttempt(
            handled=True,
            failure_reason="A country or geography is required to resolve official statistical series.",
        )

    registry = registry or StatisticalProviderRegistry((DBnomicsStatisticalProvider(),))
    resolved = await asyncio.gather(
        *(registry.resolve(metric, plan) for metric in plan.metrics)
    )
    for metric, series in zip(plan.metrics, resolved):
        if series is None:
            return StatisticalAnalysisAttempt(
                handled=True,
                failure_reason=f"No verified {metric.label} series was found for {plan.geography_label}.",
            )
    try:
        result = analyse_series(plan, tuple(resolved))
    except ValueError as exc:
        return StatisticalAnalysisAttempt(handled=True, failure_reason=str(exc))
    return StatisticalAnalysisAttempt(handled=True, result=result)
