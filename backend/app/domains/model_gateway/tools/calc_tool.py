"""calculate — deterministic arithmetic, so the model never does the maths itself.

The model writes the formula; the application computes it with the same
AST-whitelisted evaluator calculation_service uses (numbers, + - * /,
parentheses only — no names, calls or code), and the model explains the
verified result.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.calculation_service import evaluate_expression

TOOL_NAME = "calculate"


class CalculateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(
        min_length=1, max_length=160,
        description="Arithmetic using numbers, + - * / and parentheses only, e.g. \"(500000 - 425000) / 500000 * 100\".",
    )
    label: str = Field(default="", max_length=120, description="What is being calculated, e.g. \"Net profit margin (%)\".")


def _format(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.000001")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


async def _handle(args: CalculateArgs) -> ToolResult:
    try:
        result = evaluate_expression(args.expression)
    except (ValueError, ArithmeticError):
        return ToolResult.failure(
            "invalid_arguments",
            "Unsupported or invalid expression. Use only numbers, + - * / and parentheses (no powers or functions).",
        )
    prefix = f"{args.label}: " if args.label else ""
    # The model rounded 259384.0304 to "259,384.02" itself; hand it the
    # correctly rounded figure too so it never rounds on its own.
    rounded = result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    shown = _format(result)
    rounding_note = f" Rounded to 2 decimal places: {format(rounded, 'f')}." if rounded != result else ""
    return ToolResult(
        ok=True,
        content=(
            f"{prefix}{args.expression} = {shown} (computed by the application; use this exact value)."
            f"{rounding_note}"
            " Preserve the exact operands above when displaying this working; "
            "do not replace them with rounded inputs while keeping the same result."
        ),
    )


CALCULATE_TOOL = ToolSpec(
    name=TOOL_NAME,
    version="1.0",
    description=(
        "Evaluate an arithmetic expression exactly. Use this for EVERY numeric calculation in the "
        "answer (tax, margins, ratios, depreciation, conversions, totals) instead of calculating "
        "yourself. For repeated growth, expand it as multiplications, e.g. 1000 * 1.05 * 1.05."
    ),
    args_model=CalculateArgs,
    handler=_handle,
    data_source="application calculation engine",
    risk_level="low",
    timeout_seconds=2.0,
)
