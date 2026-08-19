from __future__ import annotations

import json

from app.orchestration.statistics.models import StatisticalAnalysisAttempt, StatisticalAnalysisResult
from app.orchestration.websearch import WebSource


def statistical_sources(attempt: StatisticalAnalysisAttempt) -> list[WebSource]:
    if attempt.result is None:
        return []
    result = attempt.result
    sources: list[WebSource] = []
    for index, series in enumerate(result.series):
        values = result.aligned_values[index]
        observations = ", ".join(
            f"{period}: {value:g}" for period, value in zip(result.periods, values)
        )
        analysis = _analysis_summary(result) if index == 0 else ""
        sources.append(
            WebSource(
                title=series.provenance.title[:200],
                url=series.provenance.url,
                snippet=(
                    f"Verified structured series from {series.provenance.provider}. "
                    f"Metric: {series.metric_label}; geography: {series.geography_label}; "
                    f"frequency: {series.frequency}; unit: {series.unit or 'provider-defined'}. "
                    f"Observations — {observations}. {analysis}"
                ).strip(),
                provider=series.provenance.provider,
                freshness="historical",
            )
        )
    return sources


def _analysis_summary(result: StatisticalAnalysisResult) -> str:
    chart = {
        "type": "line",
        "title": _title(result),
        "categories": list(result.periods),
        "series": [
            {"name": item.metric_label, "data": list(result.aligned_values[index])}
            for index, item in enumerate(result.series)
        ],
    }
    parts = [
        "Kriton deterministic analysis (do not recalculate or replace these values):",
        f"operation={result.plan.operation.value}",
        f"common_observations={len(result.periods)}",
    ]
    if result.scalar_result is not None:
        parts.append(f"result={result.scalar_result:.6f}")
    parts.append(f"exact_chart_json={json.dumps(chart, separators=(',', ':'))}")
    parts.extend(result.warnings)
    return "; ".join(parts)


def _title(result: StatisticalAnalysisResult) -> str:
    metrics = " vs ".join(item.metric_label for item in result.series)
    geography = result.plan.geography_label or ""
    return f"{geography} {metrics} ({result.periods[0]}–{result.periods[-1]})".strip()
