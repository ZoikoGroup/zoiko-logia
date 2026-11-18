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


def test_automatic_charts_do_not_resolve_conditions_or_ignore_negation():
    sources = [_stat_source("Unemployment — Japan", [("2024", 2.5), ("2025", 2.4)])]
    for question in (
        "Is Japan unemployment higher than Germany? If yes, chart both for 10 years.",
        "Chart Japan only when its unemployment is higher than Germany.",
        "Compare unemployment without a chart.",
        "Show the trend but do not draw a chart.",
        "Compare unemployment. No graphs please.",
    ):
        assert build_forced_chart(question, sources) is None, question


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


def _history(symbol: str, closes: list[float]):
    from app.domains.market_data.schemas import OHLCVBar
    from app.orchestration.market_data import _history_source
    days = ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]
    return _history_source([OHLCVBar(symbol=symbol, timestamp=day, open=c, high=c, low=c, close=c, volume=1,
                                      interval="1d", provider="polygon") for day, c in zip(days, closes)])


def test_several_companies_price_histories_are_compared_in_one_bar_chart():
    """18 Nov 2026: "compare last 10 days of stock prices of apple, amazon,
    microsoft in bar chart" had no chart: only one company's bars were kept."""
    sources = [_history("AAPL", [349.51, 344.17, 342.37, 350.69, 348.51]),
               _history("AMZN", [266.03, 260.21, 259.30, 266.93, 270.87]),
               _history("MSFT", [555.80, 535.93, 530.61, 545.18, 533.16])]
    payload = _fence_payload(build_forced_chart("compare stock prices of apple, amazon, microsoft in bar chart", sources))
    assert payload["type"] == "bar" and payload["title"] == "Daily closing prices, 2026-11-04 to 2026-11-10"
    assert payload["categories"][0] == "2026-11-04" and len(payload["categories"]) == 5
    assert [s["name"] for s in payload["series"]] == ["AAPL", "AMZN", "MSFT"]
    assert payload["series"][1]["data"][2] == 259.3
    # Every close is in the source text, not only the last eight.
    assert "2026-11-04: 349.51" in sources[0].snippet


def test_one_company_price_history_is_left_to_the_candlestick():
    assert build_forced_chart("chart apple stock price last 5 days", [_history("AAPL", [1.0, 2.0, 3.0, 4.0, 5.0])]) is None


def test_a_pie_of_several_companies_prices_shows_each_average_close():
    """18 Nov 2026: "...apple, amazon, microsoft in pie chart" was drawn as bars."""
    sources = [_history("AAPL", [10.0, 20.0, 30.0, 40.0, 50.0]), _history("MSFT", [5.0, 5.0, 5.0, 5.0, 5.0])]
    payload = _fence_payload(build_forced_chart("compare last 5 days of stock prices of apple and microsoft in pie chart", sources))
    assert payload["type"] == "pie"
    assert payload["data"] == [{"name": "AAPL", "value": 30.0}, {"name": "MSFT", "value": 5.0}]
    assert "Average close 30.00" in sources[0].snippet   # the pie's figure is in the source


def test_a_pie_of_one_share_shows_each_daily_close():
    """18 Nov 2026: "give last 10 days stock prices of tesla in pie chart" was
    a line chart with "a pie chart isn't available"; dates were timestamps."""
    from app.domains.market_data.schemas import OHLCVBar
    from app.orchestration.evidence import EvidenceModel
    from app.orchestration.live_data import add_price_history
    from app.orchestration.market_data import MarketSourceResult, _history_source
    days = ["2026-11-04T05:00:00+00:00", "2026-11-05T05:00:00+00:00", "2026-11-06T05:00:00+00:00"]
    bars = [OHLCVBar(symbol="TSLA", timestamp=d, open=1, high=1, low=1, close=c, volume=1, interval="1d",
                     provider="polygon") for d, c in zip(days, [100.0, 300.0, 600.0])]
    result = MarketSourceResult(sources=[_history_source(bars)], ohlc=bars, symbol="TSLA")
    pie = EvidenceModel()
    add_price_history(pie, result, "give last 3 days stock prices of tesla in pie chart")
    assert [(o.dimension, round(o.value)) for o in pie.composition] == [("2026-11-04", 10), ("2026-11-05", 30),
                                                                      ("2026-11-06", 60)]
    assert not pie.ohlc and pie.composition_subject == "TSLA daily closing prices, 2026-11-04 to 2026-11-06"
    assert "not a part of anything the company holds" in pie.composition_caveat
    line = EvidenceModel()
    add_price_history(line, result, "give last 3 days stock prices of tesla in line chart")
    assert [b.dimension for b in line.ohlc] == ["2026-11-04", "2026-11-05", "2026-11-06"] and not line.composition


def test_a_comparison_is_drawn_as_the_chart_asked_for():
    """18 Nov 2026: "compare last 5 years stock price rates of amazon,
    microsoft, tesla, apple in line chart" was drawn as bars, cut to five
    days, and titled "polygon"."""
    sources = [_history("AAPL", [1.0, 2.0, 3.0, 4.0, 5.0]), _history("MSFT", [5.0, 4.0, 3.0, 2.0, 1.0])]
    line = _fence_payload(build_forced_chart("compare last 5 years stock prices of apple and microsoft in line chart",
                                             sources))
    assert line["type"] == "line" and len(line["categories"]) == 5          # not cut to the "last 5" points
    assert line["title"] == "Daily closing prices, 2026-11-04 to 2026-11-10"
    bar = _fence_payload(build_forced_chart("compare stock prices of apple and microsoft in bar chart", sources))
    assert bar["type"] == "bar"
    area = _fence_payload(build_forced_chart("compare stock prices of apple and microsoft as an area chart", sources))
    assert area["type"] == "area"


def test_a_shorter_history_than_asked_is_said():
    from datetime import date
    from app.orchestration.live_data import history_coverage_note
    sources = [_history("AAPL", [1.0, 2.0, 3.0, 4.0, 5.0])]
    note = history_coverage_note("last 5 years of apple", sources, today=date(2026, 11, 18))
    assert note.startswith("The market data provider returned prices from 2026-11-04 only") and "5 years" in note
    assert history_coverage_note("last 10 days of apple", sources, today=date(2026, 11, 12)) == ""