"""build_forced_chart: guarantee a chart from a connector's own fetched
numeric series when the question wanted one, instead of leaving it to the
model's discretion whether to turn real comparison/trend data into a chart
or a prose table."""
import json

from app.orchestration.live_data import build_forced_chart
from app.orchestration.websearch import WebSource


def _stat_source(title: str, series: list[tuple[str, float]]) -> WebSource:
    return WebSource(title=title, url="https://example.com", snippet="...", series=series)


def _fence_payload(fence: str) -> dict:
    return json.loads(fence.removeprefix("```chart\n").removesuffix("\n```"))


def test_no_chart_when_query_does_not_ask_for_one():
    sources = [_stat_source("GDP growth — Germany", [("2023", 1.0), ("2024", 2.0)])]
    assert build_forced_chart("what is Germany's GDP growth", sources) is None


def test_no_chart_when_no_stat_sources_present():
    assert build_forced_chart("compare Germany and France GDP growth", []) is None


def test_single_source_trend_becomes_line_chart():
    sources = [_stat_source(
        "Inflation, consumer prices (annual %) — United Kingdom",
        [("2023", 7.3), ("2024", 2.5), ("2025", 3.88)],
    )]
    fence = build_forced_chart("chart UK inflation over the last 3 years", sources)
    payload = _fence_payload(fence)
    assert payload["type"] == "line"
    assert payload["categories"] == ["2023", "2024", "2025"]
    assert payload["series"][0]["data"] == [7.3, 2.5, 3.88]


def test_multi_country_comparison_becomes_bar_chart():
    sources = [
        _stat_source("GDP growth (annual %) — United Kingdom", [("2023", 0.27), ("2024", 1.08), ("2025", 1.39)]),
        _stat_source("GDP growth (annual %) — United States", [("2023", 2.93), ("2024", 2.79), ("2025", 2.16)]),
        _stat_source("GDP growth (annual %) — Germany", [("2023", -0.87), ("2024", -0.50), ("2025", 0.24)]),
    ]
    fence = build_forced_chart(
        "Compare GDP growth rates for the UK, US, and Germany over the last 3 years", sources
    )
    payload = _fence_payload(fence)
    assert payload["type"] == "bar"
    assert payload["categories"] == ["2023", "2024", "2025"]
    names = {s["name"] for s in payload["series"]}
    assert names == {"United Kingdom", "United States", "Germany"}
    uk_series = next(s for s in payload["series"] if s["name"] == "United Kingdom")
    assert uk_series["data"] == [0.27, 1.08, 1.39]


def test_comparison_aligns_on_periods_common_to_every_source():
    sources = [
        _stat_source("GDP growth — Germany", [("2023", 1.0), ("2024", 2.0), ("2025", 3.0)]),
        _stat_source("GDP growth — France", [("2023", 1.5), ("2024", 2.5)]),  # 2025 not yet reported
    ]
    fence = build_forced_chart("compare Germany and France GDP growth", sources)
    payload = _fence_payload(fence)
    assert payload["categories"] == ["2023", "2024"]
    for series in payload["series"]:
        assert len(series["data"]) == 2


def test_single_data_point_is_not_charted():
    sources = [_stat_source("GBP/USD", [("2025-09-22", 1.3395)])]
    assert build_forced_chart("chart the GBP/USD rate", sources) is None


def test_explicit_period_count_is_honoured_not_the_connectors_full_window():
    # dbnomics.py's connector always returns up to 20 years regardless of what
    # was asked — a "last 3 years" request must not chart all 20.
    twenty_years = [(str(2006 + i), float(i)) for i in range(20)]
    sources = [
        _stat_source("GDP growth (annual %) — United Kingdom", twenty_years),
        _stat_source("GDP growth (annual %) — United States", twenty_years),
    ]
    fence = build_forced_chart(
        "Compare GDP growth rates for the UK and US over the last 3 years", sources
    )
    payload = _fence_payload(fence)
    assert payload["categories"] == ["2023", "2024", "2025"]
    for series in payload["series"]:
        assert len(series["data"]) == 3
