from __future__ import annotations

from typing import Protocol

from app.orchestration.statistics.models import DataSeries, MetricRequest, StatisticalQueryPlan


class StatisticalProvider(Protocol):
    name: str

    async def fetch_series(
        self, metric: MetricRequest, plan: StatisticalQueryPlan
    ) -> DataSeries | None: ...


class StatisticalProviderRegistry:
    def __init__(self, providers: tuple[StatisticalProvider, ...]):
        self.providers = providers

    async def resolve(
        self, metric: MetricRequest, plan: StatisticalQueryPlan
    ) -> DataSeries | None:
        for provider in self.providers:
            try:
                series = await provider.fetch_series(metric, plan)
            except Exception:
                continue
            if series is not None:
                return series
        return None
