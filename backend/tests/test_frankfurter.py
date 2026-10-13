from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestration.frankfurter import fetch_fx, fetch_fx_rates


def _mock_response(rates: dict, date: str = "2026-01-01") -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"rates": rates, "date": date})
    return response


@pytest.mark.asyncio
async def test_single_pair_still_returns_one_source() -> None:
    # Rates are the ECB's per-euro figures; USD->EUR is crossed from them.
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response({"USD": 1.25}))):
        sources = await fetch_fx("Convert 5,000 USD to EUR at today's rate.")

    assert len(sources) == 1
    assert "USD/EUR" in sources[0].title
    assert "1 USD = 0.8 EUR" in sources[0].snippet and "5000 USD = 4000.00 EUR" in sources[0].snippet


@pytest.mark.asyncio
async def test_multiple_targets_each_get_their_own_source() -> None:
    """A query naming three-plus currencies previously only ever looked at
    the first two codes found and silently dropped the rest — e.g. "compare
    USD to EUR and USD to GBP" lost GBP entirely."""
    with patch(
        "httpx.AsyncClient.get",
        AsyncMock(return_value=_mock_response({"USD": 1.25, "GBP": 0.9})),
    ) as mock_get:
        sources = await fetch_fx("Compare USD to EUR and USD to GBP exchange rates.")

    assert {s.title.split(" ")[2] for s in sources} == {"USD/EUR", "USD/GBP"}
    assert any("1 USD = 0.8 EUR" in s.snippet for s in sources)
    assert any("1 USD = 0.72 GBP" in s.snippet for s in sources)
    # One request for both targets, not one per pair — always the EUR table.
    assert mock_get.call_count == 1
    assert "symbols=GBP,USD" in mock_get.call_args.args[0] and "base=" not in mock_get.call_args.args[0]


@pytest.mark.asyncio
async def test_target_missing_from_response_is_skipped_not_fabricated() -> None:
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response({"USD": 1.25}))):
        sources = await fetch_fx("Compare USD to EUR and USD to GBP exchange rates.")

    assert len(sources) == 1
    assert "USD/EUR" in sources[0].title


@pytest.mark.asyncio
async def test_weak_base_currency_keeps_full_precision() -> None:
    """base=INR from Frankfurter is cut to 1 INR = 0.01042 USD, which turned
    Rs 25,00,000 into $26,050. Crossing the ECB's EUR rates keeps precision."""
    rates = {"INR": 108.991, "USD": 1.1355, "GBP": 0.85718, "SGD": 1.4504}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response(rates))):
        sources = await fetch_fx_rates("INR", ["USD", "GBP", "SGD"], 2_500_000)
    snippets = " ".join(s.snippet for s in sources)
    assert "2500000 INR = 26045.73 USD" in snippets
    assert "2500000 INR = 19661.72 GBP" in snippets
    assert "2500000 INR = 33268.80 SGD" in snippets


@pytest.mark.asyncio
async def test_unknown_base_currency_returns_nothing() -> None:
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response({"USD": 1.1355}))):
        assert await fetch_fx_rates("XYZ", ["USD"]) == []


@pytest.mark.asyncio
async def test_a_frankfurter_outage_falls_back_to_the_backup_rate_table() -> None:
    import httpx

    backup = MagicMock()
    backup.raise_for_status = MagicMock()
    backup.json = MagicMock(return_value={
        "result": "success", "time_last_update_utc": "Tue, 06 Oct 2026 00:02:31 +0000",
        "rates": {"EUR": 1, "GBP": 0.8, "USD": 1.2},
    })

    async def get(self, url, *args, **kwargs):
        if "frankfurter" in url:
            raise httpx.ConnectTimeout("down")
        return backup

    with patch("httpx.AsyncClient.get", get):
        [source] = await fetch_fx_rates("GBP", ["EUR"], 10000)

    assert source.provider == "ExchangeRate-API (open access)"
    assert "1 GBP = 1.25 EUR" in source.snippet and "10000 GBP = 12500.00 EUR" in source.snippet
    assert "2026-10-06" in source.title


@pytest.mark.asyncio
async def test_a_dated_rate_names_the_business_day_it_comes_from() -> None:
    """"The USD/INR rate for 31 December 2024" was refused: only the latest
    rate could be fetched. A weekend date returns the previous business day."""
    requested: list[str] = []

    async def get(self, url, *args, **kwargs):
        requested.append(url)
        return _mock_response({"USD": 1.0389, "INR": 88.9335}, date="2024-12-27")

    with patch("httpx.AsyncClient.get", get):
        [source] = await fetch_fx_rates("USD", ["INR"], 4000, "2024-12-29")

    assert "/2024-12-29?" in requested[0]
    assert source.freshness == "historical" and not source.snippet.startswith("Live")
    assert "previous business day, 2024-12-27" in source.snippet


def test_a_named_date_or_negated_today_is_not_a_latest_rate_request() -> None:
    from app.orchestration.fx_profit import latest_fx_requested

    assert not latest_fx_requested("Convert US$4,000 into rupees using the USD/INR rate for 31 December 2024. Do not use today's rate.")
    assert latest_fx_requested("Using the latest USD/INR rate, convert US$4,000 into rupees.")


def test_a_question_naming_a_past_date_gets_that_date() -> None:
    from app.orchestration.frankfurter import requested_rate_date

    assert requested_rate_date("the USD/INR reference rate for 31 December 2024") == "2024-12-31"
    assert requested_rate_date("the rate on December 31, 2024") == "2024-12-31"
    assert requested_rate_date("latest USD to INR") is None
    assert requested_rate_date("on 3 Jan 2099") is None
