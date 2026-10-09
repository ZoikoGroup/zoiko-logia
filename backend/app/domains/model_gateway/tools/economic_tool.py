"""get_economic_indicator — official World Bank (WDI) statistics, as a tool.

The model picks the indicator from a fixed list and names the countries
directly, instead of dbnomics.fetch_stats() regex-matching both out of the
question. Unlike fetch_stats() (which drops a whole comparison if one country
is missing), a partial result is returned with the missing countries named,
so the model can say exactly what it could and couldn't find.
"""
from __future__ import annotations

import dataclasses
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.dbnomics import canonical_country, fetch_indicator_sources, supported_countries

TOOL_NAME = "get_economic_indicator"

# key → (World Bank WDI series code, human label). Same series the
# deterministic path in dbnomics._WDI_INDICATORS resolves to.
INDICATORS: dict[str, tuple[str, str]] = {
    "gdp": ("NY.GDP.MKTP.CD", "GDP (current US$)"),
    "gdp_growth": ("NY.GDP.MKTP.KD.ZG", "GDP growth (annual %)"),
    "gdp_per_capita": ("NY.GDP.PCAP.CD", "GDP per capita (current US$)"),
    "inflation": ("FP.CPI.TOTL.ZG", "Inflation, consumer prices (annual %)"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment, total (% of labour force)"),
    "population": ("SP.POP.TOTL", "Population, total"),
    "tax_revenue_pct_gdp": ("GC.TAX.TOTL.GD.ZS", "Tax revenue, central government only (% of GDP)"),
    "government_debt_pct_gdp": ("GC.DOD.TOTL.GD.ZS", "Central government debt, total (% of GDP)"),
    "real_interest_rate": ("FR.INR.RINR", "Real interest rate (%)"),
    "exports_pct_gdp": ("NE.EXP.GNFS.ZS", "Exports of goods and services (% of GDP)"),
    "imports_pct_gdp": ("NE.IMP.GNFS.ZS", "Imports of goods and services (% of GDP)"),
}

IndicatorKey = Literal[
    "gdp", "gdp_growth", "gdp_per_capita", "inflation", "unemployment", "population",
    "tax_revenue_pct_gdp", "government_debt_pct_gdp", "real_interest_rate",
    "exports_pct_gdp", "imports_pct_gdp",
]


_INDICATOR_ALIASES = {
    "gdp_growth_rate": "gdp_growth", "real_gdp_growth": "gdp_growth", "economic_growth": "gdp_growth",
    "gdp_usd": "gdp", "nominal_gdp": "gdp", "gdp_per_head": "gdp_per_capita",
    "cpi": "inflation", "inflation_rate": "inflation", "consumer_price_inflation": "inflation",
    "unemployment_rate": "unemployment", "jobless_rate": "unemployment",
    "tax_to_gdp": "tax_revenue_pct_gdp", "tax_revenue": "tax_revenue_pct_gdp",
    "debt_to_gdp": "government_debt_pct_gdp", "government_debt": "government_debt_pct_gdp", "public_debt": "government_debt_pct_gdp",
    "exports": "exports_pct_gdp", "imports": "imports_pct_gdp",
}


class EconomicIndicatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: IndicatorKey = Field(description="Which official indicator to fetch.")
    countries: list[str] = Field(
        min_length=1, max_length=7,
        description=f"Countries by name or ISO-3 code. Supported: {', '.join(supported_countries())}.",
    )
    years: int | None = Field(
        default=None, ge=1, le=20,
        description=(
            "A single whole number N: return only the most recent N years (e.g. 3 for "
            "'last 3 years'). Not a list of years. At most 20 — this source keeps only the "
            "most recent 20 years, so say so when asked for more. Omit for all 20."
        ),
    )
    _unsupported: list[str] = PrivateAttr(default_factory=list)

    # Near-miss arguments failed 23 calls in a week ("invalid_arguments") and
    # the agent retried or gave up. Common synonyms and shapes are mapped to
    # what the source supports instead.
    @field_validator("indicator", mode="before")
    @classmethod
    def _indicator_alias(cls, value):
        key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        return _INDICATOR_ALIASES.get(key, key)

    @field_validator("years", mode="before")
    @classmethod
    def _years_shape(cls, value):
        if isinstance(value, list):  # [2021, 2022, 2023] means "these 3 years"
            value = len(value) or None
        if isinstance(value, (int, float)) and value > 20:
            return 20  # the source keeps 20 years; the answer says so
        return value

    @model_validator(mode="after")
    def _canonical_countries(self) -> "EconomicIndicatorArgs":
        # Unknown names ("Mars") are set aside and named in the result rather
        # than failing the call: rejecting it dropped India's figures too, and
        # the answer became a refusal. Only a call with no valid country fails.
        countries: list[str] = []
        for value in self.countries:
            country = canonical_country(value)
            if country is None:
                self._unsupported.append(value)
            elif country not in countries:
                countries.append(country)
        if not countries:
            raise ValueError(f"unsupported countries: {', '.join(self._unsupported)}")
        self.countries = countries
        return self


async def _handle(args: EconomicIndicatorArgs) -> ToolResult:
    code, label = INDICATORS[args.indicator]
    results = await fetch_indicator_sources(code, label, args.countries)

    sources = []
    lines: list[str] = [
        "Evidence scope: these observations report values and periods only. They do not "
        "identify causes. Describe the measured trend; do not attribute changes to "
        "specific policies or economic events without separate supporting source text."
    ]
    missing: list[str] = []
    for country, source in zip(args.countries, results):
        if source is None:
            missing.append(country.title())
            continue
        if args.years and source.series:
            source = dataclasses.replace(source, series=source.series[-args.years:])
        sources.append(source)
        values = ", ".join(f"{period}: {value:.15g}" for period, value in source.series or [])
        latest = (
            f" (latest available: {source.series[-1][0]} = {source.series[-1][1]:.15g})" if source.series else ""
        )
        lines.append(f"{label} — {country.title()} ({source.provider}): {values}{latest}")

    if not sources:
        return ToolResult.failure(
            "no_data", f"No {label} data available for {', '.join(c.title() for c in args.countries)}. Do not guess figures.",
        )
    latest_years = sorted({s.series[-1][0] for s in sources if s.series})
    if latest_years:
        lines.append(
            f"'Last N years' means the N most recent values above, ending with {latest_years[-1]} — "
            "do not shift the window to an earlier year."
        )
    if missing:
        lines.append(f"No data available for: {', '.join(missing)}. Say so rather than estimating.")
    if args._unsupported:
        lines.append(
            f"Not a country this source covers: {', '.join(args._unsupported)}. Answer with the "
            "figures above and say plainly that no data exists for it."
        )
    return ToolResult(ok=True, content="\n".join(lines), sources=tuple(sources))


ECONOMIC_INDICATOR_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Get official annual economic statistics (World Bank WDI) for one or more countries: "
        "total GDP (current US$), GDP growth, GDP per capita, inflation, unemployment, population, tax revenue, "
        "government debt, real interest rate, exports, imports. Use for any question about "
        "these figures, and call once with every country for comparisons."
    ),
    args_model=EconomicIndicatorArgs,
    handler=_handle,
    data_source="World Bank WDI (DBnomics mirror as fallback)",
    risk_level="low",
    timeout_seconds=12.0,
)
