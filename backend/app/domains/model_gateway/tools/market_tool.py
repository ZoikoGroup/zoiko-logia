"""get_market_data — stock quotes, price history, fundamentals, profiles and
filings through the market_data provider chain, as a tool.

The model names the companies and the kind of data; nothing is re-detected
from question wording (market_data.fetch_market_sources). Each company is
fetched independently, so one company with no data never drops the rest of
a comparison — the gap is named instead.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.market_data import registry as market_registry
from app.domains.market_data import service as market_service
from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.market_data import source_for_result
from app.orchestration.sec_edgar import fetch_company_fundamentals

TOOL_NAME = "get_market_data"

_INTENTS = {
    "quote": market_registry.INTENT_QUOTE,
    "history": market_registry.INTENT_HISTORY,
    "fundamentals": market_registry.INTENT_FUNDAMENTALS,
    "profile": market_registry.INTENT_PROFILE,
    "filings": market_registry.INTENT_FILINGS,
}


class MarketDataArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_type: Literal["quote", "history", "fundamentals", "profile", "filings"] = Field(
        description=(
            "'quote' latest share price; 'history' daily price history; 'fundamentals' revenue, "
            "profit, margins and other financial metrics; 'profile' company details; "
            "'filings' UK Companies House filings."
        ),
    )
    companies: list[str] = Field(
        min_length=1, max_length=5,
        description="Companies by ticker (\"AAPL\") or name (\"Apple\"). Several for a comparison.",
    )
    days: int = Field(default=30, ge=1, le=365, description="history only: how many recent trading days.")
    ohlc: bool = Field(
        default=False,
        description="history only: true to get each day's open, high, low and close — needed for a candlestick chart.",
    )


# Keeps a long history inside the registry's result-size cap (an OHLC row is
# about three times the length of a close).
_MAX_HISTORY_POINTS = 150
_MAX_OHLC_POINTS = 60


def _history_lines(bars: list, ohlc: bool = False) -> str:
    """Every daily close — or open/high/low/close row — in the window (evenly
    sampled past the cap), with the period's high and low computed here so the
    model states them rather than working them out."""
    step = -(-len(bars) // (_MAX_OHLC_POINTS if ohlc else _MAX_HISTORY_POINTS))
    shown = bars[::step]
    if shown[-1] is not bars[-1]:
        shown.append(bars[-1])
    high = max(bars, key=lambda bar: bar.close)
    low = min(bars, key=lambda bar: bar.close)
    symbol = bars[-1].symbol
    sampling = f", one day shown every {step} trading days" if step > 1 else ""
    if ohlc:
        kind = "daily [open, close, low, high]"
        rows = "; ".join(
            f"{bar.timestamp[:10]} [{bar.open:.2f}, {bar.close:.2f}, {bar.low:.2f}, {bar.high:.2f}]" for bar in shown
        )
    else:
        kind = "closes"
        rows = "; ".join(f"{bar.timestamp[:10]} {bar.close:.2f}" for bar in shown)
    return (
        f"{symbol} {kind} over {len(bars)} trading days, {bars[0].timestamp[:10]} to "
        f"{bars[-1].timestamp[:10]}{sampling}: {rows}. Highest close {high.close:.2f} "
        f"({high.timestamp[:10]}), lowest close {low.close:.2f} ({low.timestamp[:10]}). "
        f"Describe this as {len(bars)} trading days, not calendar days."
    )


async def _handle(args: MarketDataArgs) -> ToolResult:
    intent = _INTENTS[args.data_type]
    limit = args.days if args.data_type == "history" else 10
    outcomes = await asyncio.gather(
        *(market_service.fetch_for_company(company, intent, limit=limit) for company in args.companies)
    )

    found = [source_for_result(intent, outcome[0]) if outcome else None for outcome in outcomes]
    # Fundamentals the market-data plan doesn't cover fall back to the
    # company's own 10-K figures on SEC EDGAR (US registrants only).
    if args.data_type == "fundamentals":
        gaps = [index for index, source in enumerate(found) if source is None]
        filed = await asyncio.gather(*(fetch_company_fundamentals(args.companies[index]) for index in gaps))
        for index, source in zip(gaps, filed):
            found[index] = source

    sources = [source for source in found if source is not None]
    missing = [company for company, source in zip(args.companies, found) if source is None]

    if not sources:
        return ToolResult.failure(
            "no_data",
            f"No {args.data_type} data available for {', '.join(args.companies)} from the configured "
            "market-data providers. Do not guess figures.",
        )
    lines = [f"{source.title}: {source.snippet}" for source in sources]
    if args.data_type == "history":
        # The source snippet lists only the last 8 closes; a chart or a
        # high/low over the whole period needs every close.
        lines += [
            _history_lines(outcome[0], args.ohlc) for outcome in outcomes
            if outcome and isinstance(outcome[0], list) and outcome[0]
        ]
    if missing:
        lines.append(f"No data available for: {', '.join(missing)}. Say so rather than estimating.")
    return ToolResult(ok=True, content="\n".join(lines), sources=tuple(sources))


MARKET_DATA_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Get live or recent market and company data: share price quotes, price history, "
        "financial fundamentals, company profiles, or UK filings. Use for any question about a "
        "listed company's figures; call once with every company for comparisons."
    ),
    args_model=MarketDataArgs,
    handler=_handle,
    data_source="Twelve Data; SEC EDGAR 10-K filings for US fundamentals",
    risk_level="low",
    timeout_seconds=15.0,
)
