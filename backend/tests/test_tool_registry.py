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
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_fx_response({"INR": 83.5, "EUR": 0.9}))) as get:
        result = await registry.execute(
            "get_exchange_rate", json.dumps({"base": "usd", "quotes": ["INR", "eur", "INR"], "amount": 100}),
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.ok and len(result.sources) == 2
    assert "100 USD = 8350 INR" in result.content
    assert "symbols=INR,EUR" in get.call_args.args[0]


async def test_exchange_rate_tool_names_missing_quotes() -> None:
    registry = build_default_registry()
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_fx_response({"INR": 83.5}))):
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
    {"indicator": "gdp_growth", "countries": ["a", "b", "c", "d", "e", "f"]},
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


@pytest.mark.parametrize("expression", ["__import__('os').system('x')", "2 ** 10", "10 / 0", "abs(-1)"])
async def test_calculate_rejects_anything_but_plain_arithmetic(expression) -> None:
    result = await build_default_registry().execute(
        "calculate", {"expression": expression}, granted_permissions=NO_PERMISSIONS,
    )
    assert result.error_code == "invalid_arguments"


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

    with patch("app.domains.market_data.service.fetch_for_company", nothing):
        result = await build_default_registry().execute(
            "get_market_data", {"data_type": "fundamentals", "companies": ["Apple"]},
            granted_permissions=NO_PERMISSIONS,
        )
    assert result.error_code == "no_data"
