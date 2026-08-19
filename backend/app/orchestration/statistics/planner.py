from __future__ import annotations

import re

from app.orchestration.statistics.models import (
    MetricRequest,
    StatisticalOperation,
    StatisticalQueryPlan,
)


_METRICS: tuple[MetricRequest, ...] = (
    MetricRequest("tax_revenue", "Tax revenue", ("tax revenue", "tax receipts", "government revenue")),
    MetricRequest("gdp", "GDP", ("gross domestic product", "gdp", "economic output")),
    MetricRequest("inflation", "Inflation", ("consumer price inflation", "inflation", "cpi")),
    MetricRequest("unemployment", "Unemployment", ("unemployment rate", "unemployment")),
    MetricRequest("interest_rate", "Interest rate", ("policy interest rate", "interest rate", "policy rate")),
    MetricRequest("public_debt", "Public debt", ("government debt", "public debt", "national debt")),
    MetricRequest("population", "Population", ("population",)),
)

_GEOGRAPHIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("GBR", "United Kingdom", ("united kingdom", "great britain", "britain", "u.k.", "uk")),
    ("USA", "United States", ("united states of america", "united states", "u.s.a.", "usa", "us")),
    ("IND", "India", ("india",)),
    ("DEU", "Germany", ("germany",)),
    ("FRA", "France", ("france",)),
    ("CAN", "Canada", ("canada",)),
    ("AUS", "Australia", ("australia",)),
)


def _contains_alias(query: str, alias: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query) is not None


def _operation(query: str, metric_count: int) -> StatisticalOperation | None:
    if re.search(r"\b(correlat(?:e|ed|es|ion)|relationship|association)\b", query):
        return StatisticalOperation.CORRELATION
    if re.search(r"\b(largest|biggest|greatest)\s+(?:yearly\s+)?change", query):
        return StatisticalOperation.LARGEST_CHANGE
    if re.search(r"\b(average|mean)\b", query):
        return StatisticalOperation.AVERAGE
    if metric_count >= 2 or re.search(r"\b(compare|comparison|versus|vs\.?)\b", query):
        return StatisticalOperation.COMPARISON
    if re.search(r"\b(trend|history|historical|over (?:the )?(?:last|past)|since\s+\d{4})\b", query):
        return StatisticalOperation.TREND
    return None


def plan_statistical_query(query: str) -> StatisticalQueryPlan | None:
    normalized = " ".join(query.lower().split())
    metrics = tuple(
        metric for metric in _METRICS
        if any(_contains_alias(normalized, alias) for alias in metric.aliases)
    )
    operation = _operation(normalized, len(metrics))
    if not metrics or operation is None:
        return None
    if operation is StatisticalOperation.CORRELATION and len(metrics) != 2:
        return None

    geography_code = geography_label = None
    for code, label, aliases in _GEOGRAPHIES:
        if any(_contains_alias(normalized, alias) for alias in aliases):
            geography_code, geography_label = code, label
            break

    span = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+years?\b", normalized)
    since = re.search(r"\bsince\s+(19\d{2}|20\d{2})\b", normalized)
    frequency = "quarterly" if re.search(r"\bquarter(?:ly)?\b", normalized) else "annual"
    return StatisticalQueryPlan(
        operation=operation,
        metrics=metrics,
        geography_code=geography_code,
        geography_label=geography_label,
        frequency=frequency,
        last_n_periods=int(span.group(1)) if span else None,
        start_year=int(since.group(1)) if since else None,
    )
