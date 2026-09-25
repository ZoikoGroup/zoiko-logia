from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.orchestration.frankfurter import fetch_fx


def _mock_response(rates: dict, date: str = "2026-01-01") -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"rates": rates, "date": date})
    return response


@pytest.mark.asyncio
async def test_single_pair_still_returns_one_source() -> None:
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response({"EUR": 0.87237}))):
        sources = await fetch_fx("Convert 5,000 USD to EUR at today's rate.")

    assert len(sources) == 1
    assert "USD/EUR" in sources[0].title
    assert "5000 USD = 4361.85 EUR" in sources[0].snippet


@pytest.mark.asyncio
async def test_multiple_targets_each_get_their_own_source() -> None:
    """A query naming three-plus currencies previously only ever looked at
    the first two codes found and silently dropped the rest — e.g. "compare
    USD to EUR and USD to GBP" lost GBP entirely."""
    with patch(
        "httpx.AsyncClient.get",
        AsyncMock(return_value=_mock_response({"EUR": 0.87237, "GBP": 0.74832})),
    ) as mock_get:
        sources = await fetch_fx("Compare USD to EUR and USD to GBP exchange rates.")

    assert {s.title.split(" ")[2] for s in sources} == {"USD/EUR", "USD/GBP"}
    assert any("0.87237 EUR" in s.snippet for s in sources)
    assert any("0.74832 GBP" in s.snippet for s in sources)
    # One request for both targets, not one per pair.
    assert mock_get.call_count == 1
    assert "symbols=EUR,GBP" in mock_get.call_args.args[0]


@pytest.mark.asyncio
async def test_target_missing_from_response_is_skipped_not_fabricated() -> None:
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_mock_response({"EUR": 0.87237}))):
        sources = await fetch_fx("Compare USD to EUR and USD to GBP exchange rates.")

    assert len(sources) == 1
    assert "USD/EUR" in sources[0].title
