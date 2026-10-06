"""get_exchange_rate — live ECB reference rates via Frankfurter, as a tool.

The model passes exact ISO-4217 codes instead of the connector guessing them
from the question's wording (frankfurter.fetch_fx), so "convert 100 dollars
to rupees" works without the literal codes ever appearing in the question.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.frankfurter import fetch_fx_history, fetch_fx_rates

TOOL_NAME = "get_exchange_rate"


class ExchangeRateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str = Field(description="ISO-4217 code of the currency to convert FROM, e.g. USD.")
    quotes: list[str] = Field(
        min_length=1, max_length=10,
        description="ISO-4217 codes to convert TO, e.g. [\"INR\", \"EUR\"].",
    )
    amount: float = Field(default=1.0, gt=0, le=1e12, description="Amount of the base currency to convert.")
    months: int = Field(
        default=0, ge=0, le=60,
        description="For a history or trend, the number of past months of month-end rates to return "
                    "(e.g. 12). Leave 0 for the latest rate only.",
    )

    @field_validator("base")
    @classmethod
    def _base_code(cls, value: str) -> str:
        return _iso_code(value)

    @field_validator("quotes")
    @classmethod
    def _quote_codes(cls, values: list[str]) -> list[str]:
        codes: list[str] = []
        for value in values:
            code = _iso_code(value)
            if code not in codes:
                codes.append(code)
        return codes

    @model_validator(mode="after")
    def _quotes_differ_from_base(self) -> "ExchangeRateArgs":
        self.quotes = [code for code in self.quotes if code != self.base]
        if not self.quotes:
            raise ValueError("quotes must include at least one currency other than base")
        return self


def _iso_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError(f"'{value}' is not a 3-letter ISO-4217 currency code")
    return code


async def _handle(args: ExchangeRateArgs) -> ToolResult:
    if args.months:
        history = [source for quote in args.quotes
                   if (source := await fetch_fx_history(args.base, quote, args.months))]
        if not history:
            return ToolResult.failure(
                "no_data",
                f"No exchange-rate history available for {args.base} to {', '.join(args.quotes)}. Do not guess rates.",
            )
        return ToolResult(ok=True, content="\n".join(source.snippet for source in history), sources=tuple(history))
    sources = await fetch_fx_rates(args.base, args.quotes, args.amount)
    if not sources:
        return ToolResult.failure(
            "no_data",
            f"No exchange rate available for {args.base} to {', '.join(args.quotes)}. Do not guess a rate.",
        )
    found = {source.observation.indicator.split("/")[1].split()[0] for source in sources if source.observation}
    missing = [code for code in args.quotes if code not in found]
    lines = [source.snippet for source in sources]
    if missing:
        lines.append(f"No rate available for: {', '.join(missing)}.")
    return ToolResult(ok=True, content="\n".join(lines), sources=tuple(sources))


EXCHANGE_RATE_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Get the latest official ECB reference exchange rate between currencies, and "
        "optionally convert an amount; or, with months set, the month-end rates for that "
        "many past months (for a trend or chart). Use for any currency conversion or "
        "exchange-rate question instead of relying on memory."
    ),
    args_model=ExchangeRateArgs,
    handler=_handle,
    data_source="Frankfurter (ECB reference rates)",
    risk_level="low",
    timeout_seconds=8.0,
)
