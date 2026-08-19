from __future__ import annotations

import statistics

from app.orchestration.statistics.models import (
    DataSeries,
    StatisticalAnalysisResult,
    StatisticalOperation,
    StatisticalQueryPlan,
)


def analyse_series(plan: StatisticalQueryPlan, series: tuple[DataSeries, ...]) -> StatisticalAnalysisResult:
    if not series:
        raise ValueError("No statistical series were resolved")

    maps = [{point.period: point.value for point in item.observations} for item in series]
    common_periods = set(maps[0])
    for values in maps[1:]:
        common_periods &= set(values)
    periods = sorted(common_periods)
    if plan.start_year is not None:
        periods = [period for period in periods if int(period[:4]) >= plan.start_year]
    if plan.last_n_periods is not None:
        periods = periods[-plan.last_n_periods:]
    if len(periods) < 3:
        raise ValueError("Fewer than three common observations were available")

    aligned = tuple(tuple(values[period] for period in periods) for values in maps)
    scalar: float | None = None
    warnings: list[str] = []
    if plan.operation is StatisticalOperation.CORRELATION:
        if len(aligned) != 2:
            raise ValueError("Correlation requires exactly two series")
        if len(set(aligned[0])) < 2 or len(set(aligned[1])) < 2:
            raise ValueError("Correlation is undefined for a constant series")
        scalar = statistics.correlation(aligned[0], aligned[1])
        warnings.append(
            "Correlation between trending level series may be driven by inflation or a shared time trend; it does not establish causation."
        )
    elif plan.operation is StatisticalOperation.AVERAGE:
        scalar = statistics.fmean(aligned[0])

    return StatisticalAnalysisResult(
        plan=plan,
        series=series,
        periods=tuple(periods),
        aligned_values=aligned,
        scalar_result=scalar,
        warnings=tuple(warnings),
    )
