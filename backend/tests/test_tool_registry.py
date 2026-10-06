"""Tool registry enforcement and the get_exchange_rate / get_economic_indicator tools."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.domains.model_gateway.tool_registry import (
    MAX_RESULT_CHARS,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_default_registry,
)
from app.orchestration.websearch import WebSource

NO_PERMISSIONS: frozenset[str] = frozenset()


class _EchoArgs(BaseModel):
    text: str


def _spec(name="echo", handler=None, permission=None, timeout=1.0) -> ToolSpec:
    async def echo(args: _EchoArgs) -> ToolResult:
        return ToolResult(ok=True, content=args.text)

    return ToolSpec(
        name=name, version="1.0", description="Echo text.", args_model=_EchoArgs,
        handler=handler or echo, data_source="test", risk_level="low",
        timeout_seconds=timeout, required_permission=permission,
    )


# ── Registry enforcement ─────────────────────────────────────────────────────

async def test_valid_call_runs_handler() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    result = await registry.execute("echo", '{"text": "hi"}', granted_permissions=NO_PERMISSIONS)
    assert result.ok and result.content == "hi"


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    with pytest.raises(ValueError):
        registry.register(_spec())


async def test_unknown_tool_fails_soft() -> None:
    result = await ToolRegistry().execute("drop_tables", "{}", granted_permissions=NO_PERMISSIONS)
    assert not result.ok and result.error_code == "unknown_tool"


async def test_permission_is_enforced_at_execute_even_if_model_names_the_tool() -> None:
    registry = ToolRegistry()
    registry.register(_spec(permission="source.manage"))

    assert registry.function_schemas(NO_PERMISSIONS) == []
    denied = await registry.execute("echo", '{"text": "x"}', granted_permissions=NO_PERMISSIONS)
    assert denied.error_code == "permission_denied"

    allowed = await registry.execute("echo", '{"text": "x"}', granted_permissions=frozenset({"source.manage"}))
    assert allowed.ok


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '{"wrong": 1}', '{"text": 5}'])
async def test_malformed_or_invalid_arguments_fail_soft(raw) -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    result = await registry.execute("echo", raw, granted_permissions=NO_PERMISSIONS)
    assert result.error_code == "invalid_arguments"


async def test_timeout_and_crash_fail_soft() -> None:
    async def slow(_args):
        await asyncio.sleep(5)

    async def crash(_args):
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_spec("slow", handler=slow, timeout=0.05))
    registry.register(_spec("crash", handler=crash))

    assert (await registry.execute("slow", '{"text": "x"}', granted_permissions=NO_PERMISSIONS)).error_code == "timeout"
    crashed = await registry.execute("crash", '{"text": "x"}', granted_permissions=NO_PERMISSIONS)
    assert crashed.error_code == "tool_error" and "boom" not in crashed.content


async def test_oversized_result_is_truncated() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    result = await registry.execute("echo", {"text": "x" * (MAX_RESULT_CHARS * 2)}, granted_permissions=NO_PERMISSIONS)
    assert len(result.content) < MAX_RESULT_CHARS + 50 and result.content.endswith("[truncated]")


def test_default_registry_exposes_every_tool_to_every_caller() -> None:
    registry = build_default_registry()
    assert registry.names() == [
        "calculate", "get_economic_indicator", "get_exchange_rate", "get_market_data", "render_chart",
        "search_knowledge_base",
    ]
    schemas = registry.function_schemas(NO_PERMISSIONS)
    assert {s["function"]["name"] for s in schemas} == set(registry.names())
    for schema in schemas:
        assert schema["function"]["parameters"]["type"] == "object"


# ── get_exchange_rate ────────────────────────────────────────────────────────

def _fx_response(rates: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"rates": rates, "date": "2026-09-24"})
    return response


async def test_exchange_rate_tool_converts_with_typed_codes() -> None:
    registry = build_default_registry()
    # Per-euro ECB rates: 1 EUR = 1.25 USD = 104.375 INR, so 1 USD = 83.5 INR.
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_fx_response({"USD": 1.25, "INR": 104.375}))) as get:
        result = await registry.execute(
            "get_exchange_rate", json.dumps({"base": "usd", "quotes": ["INR", "eur", "INR"], "amount": 100}),
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and len(result.sources) == 2
    assert "100 USD = 8350.00 INR" in result.content and "100 USD = 80.00 EUR" in result.content
    assert "symbols=INR,USD" in get.call_args.args[0]


async def test_exchange_rate_tool_names_missing_quotes() -> None:
    registry = build_default_registry()
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_fx_response({"USD": 1.25, "INR": 104.375}))):
        result = await registry.execute(
            "get_exchange_rate", {"base": "USD", "quotes": ["INR", "GBP"]}, granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and "No rate available for: GBP" in result.content


@pytest.mark.parametrize("args", [
    {"base": "DOLLAR", "quotes": ["INR"]},
    {"base": "USD", "quotes": ["USD"]},
    {"base": "USD", "quotes": []},
    {"base": "USD", "quotes": ["INR"], "amount": -5},
])
async def test_exchange_rate_tool_rejects_bad_arguments_before_any_request(args) -> None:
    registry = build_default_registry()
    with patch("httpx.AsyncClient.get", AsyncMock()) as get:
        result = await registry.execute("get_exchange_rate", args, granted_permissions=NO_PERMISSIONS)
    assert result.error_code == "invalid_arguments"
    get.assert_not_called()


async def test_exchange_rate_tool_no_data_says_do_not_guess() -> None:
    registry = build_default_registry()
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=RuntimeError("network down"))):
        result = await registry.execute("get_exchange_rate", {"base": "USD", "quotes": ["INR"]}, granted_permissions=NO_PERMISSIONS)
    assert result.error_code == "no_data" and "Do not guess" in result.content


# ── get_economic_indicator ───────────────────────────────────────────────────

def _indicator_source(country: str, points: list[tuple[str, float]]) -> WebSource:
    return WebSource(
        title=f"GDP growth (annual %) — {country.title()}", url="https://data.worldbank.org",
        snippet="World Bank", provider="World Bank (WDI)", freshness="historical", series=points,
    )


_TEN_YEARS = [(str(year), float(year - 2010)) for year in range(2014, 2024)]


async def test_economic_tool_normalises_countries_and_trims_years() -> None:
    registry = build_default_registry()
    fake = AsyncMock(return_value=[_indicator_source("united kingdom", _TEN_YEARS), _indicator_source("india", _TEN_YEARS)])
    with patch("app.domains.model_gateway.tools.economic_tool.fetch_indicator_sources", fake):
        result = await registry.execute(
            "get_economic_indicator", {"indicator": "gdp_growth", "countries": ["UK", "IND", "Britain"], "years": 3},
            granted_permissions=NO_PERMISSIONS,
        )

    code, label, countries = fake.call_args.args
    assert code == "NY.GDP.MKTP.KD.ZG" and countries == ["united kingdom", "india"]
    assert result.ok and len(result.sources) == 2
    assert all(len(source.series) == 3 for source in result.sources)
    assert "2021: 11, 2022: 12, 2023: 13" in result.content


async def test_economic_tool_keeps_every_digit_and_names_the_latest_year() -> None:
    # Brazil's 2025 population: 6-significant-digit formatting sent the model
    # "2.12812e+08", and it answered 211,999,000 (the 2024 value) instead.
    registry = build_default_registry()
    points = [("2024", 211998573.0), ("2025", 212812405.0)]
    fake = AsyncMock(return_value=[_indicator_source("brazil", points)])
    with patch("app.domains.model_gateway.tools.economic_tool.fetch_indicator_sources", fake):
        result = await registry.execute(
            "get_economic_indicator", {"indicator": "population", "countries": ["Brazil"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert "2024: 211998573, 2025: 212812405 (latest available: 2025 = 212812405)" in result.content
    assert "e+08" not in result.content


async def test_economic_tool_returns_partial_comparison_and_names_the_gap() -> None:
    registry = build_default_registry()
    fake = AsyncMock(return_value=[_indicator_source("india", _TEN_YEARS), None])
    with patch("app.domains.model_gateway.tools.economic_tool.fetch_indicator_sources", fake):
        result = await registry.execute(
            "get_economic_indicator", {"indicator": "gdp_growth", "countries": ["India", "Germany"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and len(result.sources) == 1
    assert "No data available for: Germany" in result.content


@pytest.mark.parametrize("args", [
    {"indicator": "gdp_growth", "countries": ["Atlantis"]},
    {"indicator": "happiness", "countries": ["India"]},
    {"indicator": "gdp_growth", "countries": ["India"], "years": 0},
    {"indicator": "gdp_growth", "countries": ["a", "b", "c", "d", "e", "f", "g", "h"]},
])
async def test_economic_tool_rejects_bad_arguments(args) -> None:
    registry = build_default_registry()
    fake = AsyncMock()
    with patch("app.domains.model_gateway.tools.economic_tool.fetch_indicator_sources", fake):
        result = await registry.execute("get_economic_indicator", args, granted_permissions=NO_PERMISSIONS)
    assert result.error_code == "invalid_arguments"
    fake.assert_not_called()


# ── calculate ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expression, expected", [
    ("(500000 - 425000) / 500000 * 100", "= 15 "),
    ("(20000 - 2000) / 5", "= 3600 "),
    ("1000 * 1.05 * 1.05", "= 1102.5 "),
    ("1 / 3", "= 0.333333 "),
])
async def test_calculate_is_exact(expression, expected) -> None:
    result = await build_default_registry().execute(
        "calculate", {"expression": expression}, granted_permissions=NO_PERMISSIONS,
    )
    assert result.ok and expected in result.content


async def test_calculate_hands_over_the_correctly_rounded_value() -> None:
    registry = build_default_registry()
    long = await registry.execute("calculate", {"expression": "2702.48 * 95.98"}, granted_permissions=NO_PERMISSIONS)
    assert "= 259384.0304 " in long.content and "Rounded to 2 decimal places: 259384.03." in long.content
    short = await registry.execute("calculate", {"expression": "1000 * 1.05 * 1.05"}, granted_permissions=NO_PERMISSIONS)
    assert "Rounded" not in short.content


@pytest.mark.parametrize("expression", [
    "__import__('os').system('x')", "10 / 0", "abs(-1)",
    # Powers are allowed, but bounded so an expression stays cheap.
    "2 ** 100000", "10 ** 10 ** 10", "(-8) ** (1 / 3)",
])
async def test_calculate_rejects_anything_but_plain_arithmetic(expression) -> None:
    result = await build_default_registry().execute(
        "calculate", {"expression": expression}, granted_permissions=NO_PERMISSIONS,
    )
    assert result.error_code == "invalid_arguments"


async def test_calculate_computes_a_loan_emi_exactly_in_one_call() -> None:
    # Reported live: without powers the model approximated (1 + r)^180 as
    # "≈ 3.70" and answered an EMI of ₹39,960 instead of ₹39,977.95.
    result = await build_default_registry().execute(
        "calculate",
        {"expression": "4000000 * (8.75 / 12 / 100) * (1 + 8.75 / 12 / 100) ** 180 "
                       "/ ((1 + 8.75 / 12 / 100) ** 180 - 1)"},
        granted_permissions=NO_PERMISSIONS,
    )
    assert result.ok and "Rounded to 2 decimal places: 39977.95." in result.content


# ── get_market_data ──────────────────────────────────────────────────────────

async def test_market_tool_fetches_each_company_and_names_gaps() -> None:
    from app.domains.market_data.schemas import StockQuote

    quote = StockQuote(
        symbol="AAPL", price=190.5, provider="twelvedata", freshness="delayed",
        fetched_at="2026-09-25T10:00:00Z", currency="USD", company_name="Apple Inc.",
    )

    async def fake_fetch(company, intent, *, limit):
        assert intent == "stock_quote"
        return (quote, "twelvedata", "Apple") if company == "Apple" else None

    with patch("app.domains.market_data.service.fetch_for_company", fake_fetch):
        result = await build_default_registry().execute(
            "get_market_data", {"data_type": "quote", "companies": ["Apple", "Nonexistent Co"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and len(result.sources) == 1
    assert "AAPL" in result.content and "No data available for: Nonexistent Co" in result.content


async def test_market_tool_no_data_at_all() -> None:
    async def nothing(company, intent, *, limit):
        return None

    with patch("app.domains.market_data.service.fetch_for_company", nothing), \
            patch(f"{_MARKET_TOOL}.fetch_company_fundamentals", AsyncMock(return_value=None)):
        result = await build_default_registry().execute(
            "get_market_data", {"data_type": "fundamentals", "companies": ["Apple"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.error_code == "no_data"


_MARKET_TOOL = "app.domains.model_gateway.tools.market_tool"


async def test_market_tool_fundamentals_fall_back_to_sec_filings() -> None:
    async def nothing(company, intent, *, limit):
        return None

    filed = WebSource(
        title="SEC EDGAR — MICROSOFT CORP annual financials", url="https://www.sec.gov/x",
        snippet="Revenue for the fiscal year ending 2026-06-30 (FY2026): $331,839,000,000", provider="sec_edgar",
    )
    sec = AsyncMock(side_effect=lambda company: filed if company == "Microsoft" else None)
    with patch("app.domains.market_data.service.fetch_for_company", nothing), \
            patch(f"{_MARKET_TOOL}.fetch_company_fundamentals", sec):
        result = await build_default_registry().execute(
            "get_market_data", {"data_type": "fundamentals", "companies": ["Microsoft", "Tata Motors"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and result.sources == (filed,)
    assert "$331,839,000,000" in result.content and "No data available for: Tata Motors" in result.content


async def test_market_tool_quotes_never_fall_back_to_sec() -> None:
    async def nothing(company, intent, *, limit):
        return None

    sec = AsyncMock()
    with patch("app.domains.market_data.service.fetch_for_company", nothing), \
            patch(f"{_MARKET_TOOL}.fetch_company_fundamentals", sec):
        await build_default_registry().execute(
            "get_market_data", {"data_type": "quote", "companies": ["Microsoft"]},
            granted_permissions=NO_PERMISSIONS,
        )
    sec.assert_not_called()


def _bars(closes: list[float]):
    from app.domains.market_data.schemas import OHLCVBar

    return [
        OHLCVBar(symbol="TSLA", timestamp=f"2026-{8 + i // 28:02d}-{1 + i % 28:02d}T00:00:00Z",
                 open=c, high=c, low=c, close=c, provider="twelve_data", interval="1day")
        for i, c in enumerate(closes)
    ]


async def test_market_tool_history_gives_every_close_and_the_true_high_and_low() -> None:
    # The source snippet shows only the last 8 closes; the period low here is
    # the FIRST close, which a model reading that snippet reported wrongly.
    bars = _bars([336.87] + [360.0] * 20 + [364.27, 375.3, 378.9, 380.12, 377.94, 372.11, 357.45, 352.84])

    async def fake_fetch(company, intent, *, limit):
        return (bars, "twelve_data", "Tesla")

    with patch("app.domains.market_data.service.fetch_for_company", fake_fetch):
        result = await build_default_registry().execute(
            "get_market_data", {"data_type": "history", "companies": ["Tesla"], "days": 29},
            granted_permissions=NO_PERMISSIONS,
        )
    assert "closes over 29 trading days" in result.content
    assert "2026-08-01 336.87" in result.content
    assert "Highest close 380.12" in result.content and "lowest close 336.87" in result.content


def test_long_history_is_sampled_to_fit_and_keeps_the_last_close() -> None:
    from app.domains.model_gateway.tools.market_tool import _history_lines

    bars = _bars([float(i) for i in range(1, 366)])
    text = _history_lines(bars)
    assert "over 365 trading days" in text and text.count(";") < 150
    assert f"{bars[-1].timestamp[:10]} 365.00" in text and "Highest close 365.00" in text


def test_ohlc_history_gives_candlestick_rows_in_chart_order() -> None:
    from app.domains.market_data.schemas import OHLCVBar
    from app.domains.model_gateway.tools.market_tool import _history_lines

    bar = OHLCVBar(symbol="MSFT", timestamp="2026-09-29T00:00:00Z", open=410.0, high=415.5,
                   low=405.25, close=412.0, provider="twelve_data")
    text = _history_lines([bar], ohlc=True)
    # Same [open, close, low, high] order render_chart's candlestick expects.
    assert "daily [open, close, low, high]" in text and "2026-09-29 [410.00, 412.00, 405.25, 415.50]" in text
    many = _history_lines([bar] * 200, ohlc=True)
    assert many.count("[410.00") <= 61 and len(many) < 4000


async def test_economic_tool_keeps_valid_countries_and_names_unknown_ones() -> None:
    # "Compare GDP growth of India and Mars" used to fail the whole call, so
    # India's figures were lost and the answer became an off-topic refusal.
    registry = build_default_registry()
    fake = AsyncMock(return_value=[_indicator_source("india", _TEN_YEARS)])
    with patch("app.domains.model_gateway.tools.economic_tool.fetch_indicator_sources", fake):
        result = await registry.execute(
            "get_economic_indicator", {"indicator": "gdp_growth", "countries": ["India", "Mars"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert fake.call_args.args[2] == ["india"]
    assert result.ok and "2023: 13" in result.content
    assert "Not a country this source covers: Mars" in result.content
