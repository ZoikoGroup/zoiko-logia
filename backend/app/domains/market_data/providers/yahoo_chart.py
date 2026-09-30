"""Yahoo Finance's public chart endpoint, shared by two providers.

Both the benchmark-index adapter and the new equity adapter need the same three
things from the same endpoint: a quote from the response metadata, a bar series
from the indicators block, and the browser-shaped request headers without which
Yahoo answers 429. That is one parser, not two, so it lives here — the failure
this prevents is a silent drift where the equity path grows a different reading
of the same payload and the two providers start disagreeing about what Yahoo
said.

The endpoint is keyless, public and undocumented. Two consequences, both stated
where they are enforced below:

  - It publishes no entitlement information, so everything here is reported as
    `delayed` and the metadata's own exchangeDataDelayedBy is carried into
    market_status. Claiming realtime on a feed that does not declare one would
    be exactly the unverifiable assertion this product exists to avoid.
  - It serves far more than equities: indices (^GSPC), currency pairs
    (EURUSD=X), crypto (BTC-USD) and bond-yield indices (^TNX). What each
    adapter will accept is its own decision, because an adapter that accepts
    everything stops being able to say what it will not answer.

Docs: https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.domains.market_data.http import as_float, request_json
from app.domains.market_data.schemas import (
    FRESHNESS_DELAYED,
    EntityRef,
    OHLCVBar,
    ProviderBadResponse,
    StockQuote,
)

PAGE_BASE = "https://finance.yahoo.com/quote/"

# Yahoo rate-limits default http-client identifiers and serves browser user
# agents without complaint — the first probe that succeeded had sent a Mozilla
# UA, and every request without one was answered 429. This is an honest, fixed
# UA (no credential buried in it), matching the rest of the product's connectors.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppWebKit/537.36 (KHTML, like Gecko) ZoikoLogia/1.0"
    ),
    "Accept": "application/json,text/plain,*/*",
}

# The registry only ever asks for these, one bar per period. Anything finer is
# intraday, which Yahoo caps hard (60 days for 5-minute bars) and which the
# routing table's span coarsening deliberately does not produce.
INTERVAL_TO_YAHOO = {"1d": "1d", "1w": "1wk", "1mo": "1mo"}

# Calendar days one bar covers, for turning a bar COUNT into a window. Wider than
# one bar period because trading days are not calendar days.
_DAYS_PER_BAR = {"1d": 1.6, "1wk": 8.0, "1mo": 32.0}

_MARKET_STATE_WORDS = {
    "REGULAR": "open",
    "PRE": "pre-market",
    "PREPRE": "pre-market",
    "POST": "after hours",
    "POSTPOST": "after hours",
    "CLOSED": "closed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chart_result(payload: Any, provider: str, symbol: str) -> dict[str, Any]:
    """The chart result object, or a typed failure.

    Yahoo answers an unknown symbol with HTTP 404 and a null result, so both a
    missing result and a missing meta are "no such instrument" rather than an
    outage — the caller turns this into ProviderBadResponse and the service
    decides what to do with it.
    """
    chart = (payload or {}).get("chart") or {}
    results = chart.get("result") or []
    if not results or "meta" not in results[0]:
        raise ProviderBadResponse(provider, f"no chart data for {symbol}")
    return results[0]


async def fetch_chart(
    client: httpx.AsyncClient,
    provider: str,
    base_url: str,
    symbol: str,
    *,
    span: str = "",
    interval: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """GET one chart. `span` is a Yahoo range; `limit` builds a period window.

    A bar COUNT is converted to a time window rather than passed as a count,
    because Yahoo takes no bar limit: asking for 400 daily bars needs a start
    date, and over-fetching a decade to slice 30 points out of it is a rate
    limit the keyless tier cannot afford.
    """
    params: dict[str, Any] = {"interval": INTERVAL_TO_YAHOO.get(interval, interval or "1d")}
    if span:
        params["range"] = span
    elif limit > 0:
        days_per_bar = _DAYS_PER_BAR.get(interval, 1.6)
        end = datetime.now(timezone.utc)
        params["period1"] = int((end - timedelta(days=days_per_bar * limit * 1.4)).timestamp())
        params["period2"] = int(end.timestamp())
    payload = await request_json(
        client, provider, f"{base_url}/chart/{symbol}",
        params=params, headers=HEADERS, retries=0,
    )
    return chart_result(payload, provider, symbol)


def market_status(meta: dict[str, Any]) -> str:
    """The session state, with the delay Yahoo states for that exchange."""
    raw = str(meta.get("marketState") or "").strip().upper()
    words = _MARKET_STATE_WORDS.get(raw, raw.lower())
    delayed = as_float(meta.get("exchangeDataDelayedBy"))
    if not words:
        return ""
    if delayed and delayed > 0:
        return f"{words}, delayed {int(delayed)} min"
    return words


def quote_from_meta(meta: dict[str, Any], provider: str, ref: EntityRef) -> StockQuote:
    """A StockQuote from a chart's metadata block.

    Raises ProviderBadResponse when there is no usable price: a zeroed field is
    what Yahoo returns for instruments it does not really serve through this
    endpoint, and a quote of 0.00 is worse than no quote.
    """
    symbol = ref.ticker
    price = as_float(meta.get("regularMarketPrice"))
    if price is None or price == 0:
        raise ProviderBadResponse(provider, f"no quote data for {symbol}")

    prev = as_float(meta.get("previousClose"))
    change = as_float(meta.get("regularMarketChange"))
    change_pct = as_float(meta.get("regularMarketChangePercent"))
    if change is None and prev is not None:
        change = price - prev
    if change_pct is None and prev:
        change_pct = (change / prev) * 100.0

    timestamp = as_float(meta.get("regularMarketTime"))
    return StockQuote(
        symbol=symbol,
        price=price,
        provider=provider,
        freshness=FRESHNESS_DELAYED,
        fetched_at=now_iso(),
        company_name=str(meta.get("longName") or meta.get("shortName") or ref.name or ""),
        exchange=str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        currency=str(meta.get("currency") or ""),
        change=change,
        change_percent=change_pct,
        open=as_float(meta.get("regularMarketOpen")),
        high=as_float(meta.get("regularMarketDayHigh")),
        low=as_float(meta.get("regularMarketDayLow")),
        previous_close=prev,
        volume=as_float(meta.get("regularMarketVolume")),
        provider_timestamp=(
            datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
            if timestamp else ""
        ),
        market_status=market_status(meta),
        source_url=f"{PAGE_BASE}{symbol}",
    )


def bars_from_chart(
    payload: dict[str, Any], symbol: str, provider: str, *, interval: str, limit: int
) -> list[OHLCVBar]:
    """Daily-or-coarser bars from a chart result, oldest first.

    A bar with no usable close is dropped rather than carried as zero — Yahoo
    pads holiday and halted-session rows with nulls, and a zero close would draw
    a crash that did not happen.
    """
    timestamps = payload.get("timestamp") or []
    quote = ((payload.get("indicators") or {}).get("quote") or [{}])[0]
    if not isinstance(quote, dict):
        raise ProviderBadResponse(provider, f"historical series for {symbol} was malformed")
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    meta = payload.get("meta") or {}
    currency = str(meta.get("currency") or "")
    exchange = str(meta.get("fullExchangeName") or meta.get("exchangeName") or "")

    def at(series: list[Any], index: int) -> Optional[float]:
        return as_float(series[index]) if index < len(series) else None

    bars: list[OHLCVBar] = []
    for index, raw_ts in enumerate(timestamps):
        close = at(closes, index)
        if close is None:
            continue
        try:
            day = datetime.fromtimestamp(
                as_float(raw_ts) or 0, timezone.utc
            ).date().isoformat()
        except (ValueError, OSError, OverflowError):
            continue
        bars.append(
            OHLCVBar(
                symbol=symbol,
                timestamp=day,
                open=at(opens, index) or close,
                high=at(highs, index) or close,
                low=at(lows, index) or close,
                close=close,
                volume=at(volumes, index),
                provider=provider,
                interval=interval,
                currency=currency,
                exchange=exchange,
            )
        )
    if not bars:
        raise ProviderBadResponse(provider, f"historical series for {symbol} had no usable closes")
    return bars[-limit:] if limit else bars
