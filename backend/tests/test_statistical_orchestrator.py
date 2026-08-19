from __future__ import annotations

import pytest

from app.orchestration.statistics.engine import analyse_series
from app.orchestration.statistics.models import (
    DataSeries,
    MetricRequest,
    Observation,
    SeriesProvenance,
    StatisticalOperation,
)
from app.orchestration.statistics.orchestrator import analyse_statistical_query
from app.orchestration.statistics.planner import plan_statistical_query
from app.orchestration.statistics.providers import StatisticalProviderRegistry
from app.orchestration.statistics.render import statistical_sources


def _series(metric: MetricRequest, values: list[float]) -> DataSeries:
    return DataSeries(
        metric_code=metric.code,
        metric_label=metric.label,
        geography_code="GBR",
        geography_label="United Kingdom",
        frequency="annual",
        unit="index",
        observations=tuple(
            Observation(str(2000 + index), value) for index, value in enumerate(values)
        ),
        provenance=SeriesProvenance(
            provider="test-provider",
            dataset_code="DATASET",
            series_code=metric.code,
            title=metric.label,
            url=f"https://example.test/{metric.code}",
        ),
    )


def test_planner_preserves_short_uk_gdp_tax_concepts():
    plan = plan_statistical_query(
        "Show the correlation between UK GDP and tax revenue over the last 15 years"
    )

    assert plan is not None
    assert plan.operation is StatisticalOperation.CORRELATION
    assert plan.geography_code == "GBR"
    assert [metric.code for metric in plan.metrics] == ["tax_revenue", "gdp"]
    assert plan.last_n_periods == 15


def test_planner_is_reusable_for_other_metrics_and_geographies():
    plan = plan_statistical_query(
        "Compare inflation and unemployment in Germany over the past 12 years"
    )

    assert plan is not None
    assert plan.operation is StatisticalOperation.COMPARISON
    assert plan.geography_code == "DEU"
    assert {metric.code for metric in plan.metrics} == {"inflation", "unemployment"}
    assert plan.last_n_periods == 12


def test_engine_aligns_common_periods_and_calculates_correlation():
    plan = plan_statistical_query(
        "Show the correlation between UK GDP and tax revenue over the last 5 years"
    )
    assert plan is not None
    tax, gdp = plan.metrics
    result = analyse_series(
        plan,
        (_series(tax, [1, 2, 3, 4, 5, 6]), _series(gdp, [2, 4, 6, 8, 10, 12])),
    )

    assert result.periods == ("2001", "2002", "2003", "2004", "2005")
    assert result.scalar_result == pytest.approx(1.0)
    assert "does not establish causation" in result.warnings[0]


@pytest.mark.asyncio
async def test_registry_falls_back_to_next_provider():
    plan = plan_statistical_query("Show the trend in UK GDP over the last 5 years")
    assert plan is not None

    class EmptyProvider:
        name = "empty"

        async def fetch_series(self, metric, requested_plan):
            return None

    class WorkingProvider:
        name = "working"

        async def fetch_series(self, metric, requested_plan):
            return _series(metric, [1, 2, 3, 4, 5])

    attempt = await analyse_statistical_query(
        "Show the trend in UK GDP over the last 5 years",
        StatisticalProviderRegistry((EmptyProvider(), WorkingProvider())),
    )

    assert attempt.handled is True
    assert attempt.result is not None
    assert attempt.result.series[0].provenance.provider == "test-provider"


@pytest.mark.asyncio
async def test_unresolved_series_fails_without_fabricated_data():
    class EmptyProvider:
        name = "empty"

        async def fetch_series(self, metric, requested_plan):
            return None

    attempt = await analyse_statistical_query(
        "Show the correlation between UK GDP and tax revenue over the last 15 years",
        StatisticalProviderRegistry((EmptyProvider(),)),
    )

    assert attempt.handled is True
    assert attempt.result is None
    assert "No verified" in (attempt.failure_reason or "")
    assert statistical_sources(attempt) == []


@pytest.mark.asyncio
async def test_rendered_sources_contain_exact_deterministic_result():
    plan = plan_statistical_query(
        "Show the correlation between UK GDP and tax revenue over the last 5 years"
    )
    assert plan is not None

    class WorkingProvider:
        name = "working"

        async def fetch_series(self, metric, requested_plan):
            multiplier = 2 if metric.code == "gdp" else 1
            return _series(metric, [multiplier * n for n in range(1, 6)])

    attempt = await analyse_statistical_query(
        "Show the correlation between UK GDP and tax revenue over the last 5 years",
        StatisticalProviderRegistry((WorkingProvider(),)),
    )
    sources = statistical_sources(attempt)

    assert len(sources) == 2
    assert "result=1.000000" in sources[0].snippet
    assert "exact_chart_json=" in sources[0].snippet
    assert "Illustrative" not in sources[0].snippet
