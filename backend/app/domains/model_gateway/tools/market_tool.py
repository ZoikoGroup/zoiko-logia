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


async def _handle(args: MarketDataArgs) -> ToolResult:
    intent = _INTENTS[args.data_type]
    limit = args.days if args.data_type == "history" else 10
    outcomes = await asyncio.gather(
        *(market_service.fetch_for_company(company, intent, limit=limit) for company in args.companies)
    )

    sources = []
    missing: list[str] = []
    for company, outcome in zip(args.companies, outcomes):
        source = source_for_result(intent, outcome[0]) if outcome else None
        if source is None:
            missing.append(company)
            continue
        sources.append(source)

    if not sources:
        return ToolResult.failure(
            "no_data",
            f"No {args.data_type} data available for {', '.join(args.companies)} from the configured "
            "market-data providers. Do not guess figures.",
        )
    lines = [f"{source.title}: {source.snippet}" for source in sources]
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
    data_source="configured market-data providers (Twelve Data, SEC, Companies House, …)",
    risk_level="low",
    timeout_seconds=15.0,
)
