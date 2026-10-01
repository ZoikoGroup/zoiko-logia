import json
from types import SimpleNamespace

from app.domains.model_gateway.agent import run_agent, AgentLimits
from app.domains.model_gateway.tool_registry import build_default_registry
from app.orchestration.calculation_service import validate_answer_calculations
from app.orchestration.websearch import WebSource
from app.domains.calculations.schemas import LiveObservation


def reply(text="", calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls))])


def call(name, args):
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_large_currency_equation_does_not_get_large_error_tolerance():
    assert validate_answer_calculations("10,713.29 × 95.99 = 1,028,315.04 INR")
    assert not validate_answer_calculations("10,713.29 × 95.99 = 1,028,368.71 INR")
    assert validate_answer_calculations("200 / 500 = 0.4%")
    assert not validate_answer_calculations("200 / 500 = 40%")
    assert not validate_answer_calculations("200 / 500 * 100 = 40%")


async def test_agent_repairs_displayed_operands_before_returning():
    client = Client([
        reply(calls=[call("calculate", {"expression": "10713.29 * 95.99"})]),
        reply("10,713.29 × 95.99 = 1,028,315.04 INR"),
        reply("10,713.29 × 95.99 = 1,028,368.71 INR"),
    ])
    result = await run_agent(client, model="test", system_prompt="test", user_prompt="Convert the amount",
                             registry=build_default_registry(), granted_permissions=frozenset())
    assert "1,028,368.71" in result.text
    assert "inconsistent" in client.requests[-1]["messages"][-1]["content"]


async def test_failed_repair_returns_verified_working_instead_of_wrong_equation():
    client = Client([
        reply(calls=[call("calculate", {"expression": "10713.29 * 95.99"})]),
        reply("10,713.29 × 95.99 = 1,028,315.04 INR"),
    ])
    result = await run_agent(client, model="test", system_prompt="test", user_prompt="Convert the amount",
                             registry=build_default_registry(), granted_permissions=frozenset(),
                             limits=AgentLimits(max_steps=2))
    assert "1,028,315.04" not in result.text
    assert "1028368.7071" in result.text


async def test_missing_comparison_year_is_added_from_tool_data(monkeypatch):
    from app.domains.model_gateway.tools import economic_tool

    async def fetch(*args):
        return [WebSource(title="Inflation — " + country, url="https://example.com", snippet="Annual inflation",
                          series=[("2024", 3.0), ("2025", value)])
                for country, value in [("India", 2.4), ("Brazil", 5.02)]]

    monkeypatch.setattr(economic_tool, "fetch_indicator_sources", fetch)
    client = Client([
        reply(calls=[call("get_economic_indicator", {"indicator": "inflation", "countries": ["India", "Brazil"]})]),
        reply("| Country | Inflation |\n|---|---|\n| India | 2.4% |\n| Brazil | 5.02% |"),
    ])
    result = await run_agent(client, model="test", system_prompt="test", user_prompt="Table only",
                             registry=build_default_registry(), granted_permissions=frozenset())
    assert "latest common available year | 2025" in result.text
    assert not result.artifacts


async def test_missing_exchange_rate_date_is_added_from_observation(monkeypatch):
    from app.domains.model_gateway.tools import fx_tool

    async def fetch(*args):
        return [WebSource(title="USD/INR", url="https://example.com", snippet="1 USD = 95.985 INR",
            observation=LiveObservation(observation_id="fx", indicator="USD/INR exchange rate", value="95.985",
                unit="INR per USD", period="2026-09-29", provider="ECB", source_url="https://example.com",
                freshness="live"))]

    monkeypatch.setattr(fx_tool, "fetch_fx_rates", fetch)
    client = Client([
        reply(calls=[call("get_exchange_rate", {"base": "USD", "quotes": ["INR"]})]),
        reply("The reference rate is 95.985 INR per USD."),
    ])
    result = await run_agent(client, model="test", system_prompt="test", user_prompt="Exchange rate",
                             registry=build_default_registry(), granted_permissions=frozenset())
    assert "reference date | 2026-09-29" in result.text
