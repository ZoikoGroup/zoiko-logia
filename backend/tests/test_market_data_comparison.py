from unittest.mock import AsyncMock

import pytest

from app.domains.market_data import registry, service
from app.domains.market_data.identity import find_all_known_names
from app.domains.market_data.schemas import StockQuote


def test_find_all_known_names_returns_every_company_in_order() -> None:
    """known_ticker_for_name() (the single-entity resolver) deliberately
    keeps only its best match — right for pinning one company, wrong for a
    comparison question, which names more than one on purpose."""
    names = find_all_known_names("Compare Apple and Microsoft stock price performance.")
    assert names == [("AAPL", "US", "Apple"), ("MSFT", "US", "Microsoft")]


def test_find_all_known_names_dedupes_repeated_mentions() -> None:
    names = find_all_known_names("Apple's price today versus Apple's price last year.")
    assert names == [("AAPL", "US", "Apple")]


def test_find_all_known_names_empty_for_no_known_company() -> None:
    assert find_all_known_names("What is a tax credit?") == []


def _quote(symbol: str, price: float) -> StockQuote:
    return StockQuote(
        symbol=symbol, price=price, provider="test_provider", freshness="delayed",
        fetched_at="2026-01-01T00:00:00+00:00", company_name=symbol,
    )


@pytest.mark.asyncio
async def test_fetch_market_data_for_companies_fetches_each_independently(monkeypatch) -> None:
    """The single-entity path (fetch_market_data) only ever resolves and
    answers for one company — a comparison naming two must get both."""
    monkeypatch.setattr(registry, "detect_intent", lambda query: registry.INTENT_QUOTE)
    monkeypatch.setattr(registry, "providers_for", lambda intent: ["dummy_provider"])

    async def fake_fetch_for_intent(client, intent, ref, *, limit=10):
        return _quote(ref.ticker, 100.0 if ref.ticker == "AAPL" else 200.0), "test_provider"

    monkeypatch.setattr(service, "fetch_for_intent", fake_fetch_for_intent)

    companies = [("AAPL", "US", "Apple"), ("MSFT", "US", "Microsoft")]
    results = await service.fetch_market_data_for_companies("Compare Apple and Microsoft", companies)

    assert [label for _, _, _, label in results] == ["Apple", "Microsoft"]
    assert {result.symbol: result.price for result, _, _, _ in results} == {"AAPL": 100.0, "MSFT": 200.0}


@pytest.mark.asyncio
async def test_fetch_market_data_for_companies_skips_a_failing_company(monkeypatch) -> None:
    """One company having no data must not drop the rest of the comparison —
    same fail-soft contract as the single-entity path."""
    monkeypatch.setattr(registry, "detect_intent", lambda query: registry.INTENT_QUOTE)
    monkeypatch.setattr(registry, "providers_for", lambda intent: ["dummy_provider"])

    async def fake_fetch_for_intent(client, intent, ref, *, limit=10):
        if ref.ticker == "MSFT":
            return None
        return _quote(ref.ticker, 100.0), "test_provider"

    monkeypatch.setattr(service, "fetch_for_intent", fake_fetch_for_intent)

    companies = [("AAPL", "US", "Apple"), ("MSFT", "US", "Microsoft")]
    results = await service.fetch_market_data_for_companies("Compare Apple and Microsoft", companies)

    assert [label for _, _, _, label in results] == ["Apple"]


@pytest.mark.asyncio
async def test_fetch_market_data_for_companies_returns_empty_for_unrecognised_intent(monkeypatch) -> None:
    monkeypatch.setattr(registry, "detect_intent", lambda query: None)
    results = await service.fetch_market_data_for_companies("irrelevant", [("AAPL", "US", "Apple")])
    assert results == []
