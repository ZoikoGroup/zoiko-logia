"""calculate — deterministic arithmetic, so the model never does the maths itself.

The model writes the formula; the application computes it with the same
AST-whitelisted evaluator calculation_service uses (numbers, + - * /,
powers and parentheses only — no names, calls or code), and the model
explains the verified result.
"""
from __future__ import annotations

import hashlib
import uuid

from decimal import ROUND_HALF_UP, Decimal, DivisionUndefined, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from app.domains.identity.permissions import KRITON_TOOL_ROLES
from app.domains.model_gateway.tool_registry import ToolResult, ToolSpec
from app.orchestration.calculation_service import evaluate_expression

TOOL_NAME = "calculate"
TOOL_VERSION = "1.1"
# The AST-whitelisted evaluator in calculation_service.evaluate_expression.
FORMULA_VERSION = "expression-evaluator-1.0"


class CalculateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(
        min_length=1, max_length=240,
        description=(
            "Arithmetic using numbers, + - * /, ** for powers and parentheses only, e.g. "
            "\"(500000 - 425000) / 500000 * 100\" or \"10000 * 1.08 ** 10\"."
        ),
    )
    label: str = Field(default="", max_length=120, description="What is being calculated, e.g. \"Net profit margin (%)\".")


def _format(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.000001")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _division_by_zero(exc: BaseException) -> bool:
    """x/0 raises DivisionByZero (a ZeroDivisionError); 0/0 raises
    InvalidOperation naming DivisionUndefined in its arguments."""
    if isinstance(exc, ZeroDivisionError):
        return True
    return isinstance(exc, InvalidOperation) and any(
        signal is DivisionUndefined for signal in (exc.args[0] if exc.args and isinstance(exc.args[0], list) else []))


async def _handle(args: CalculateArgs) -> ToolResult:
    try:
        result = evaluate_expression(args.expression)
    except (ValueError, ArithmeticError) as exc:
        if _division_by_zero(exc.__cause__ or exc):
            # §07.2: a zero denominator is a controlled error, never a guess.
            return ToolResult.failure(
                "invalid_arguments",
                "Division by zero: a denominator in this calculation is 0, so the result is undefined. "
                "Ask the user for the correct figure; do not estimate one.",
            )
        return ToolResult.failure(
            "invalid_arguments",
            "Unsupported or invalid expression. Use only numbers, + - * /, ** and parentheses (no functions).",
        )
    prefix = f"{args.label}: " if args.label else ""
    calculation_id = f"calc-{uuid.uuid4().hex[:16]}"
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
        # The calculation receipt (§07.3): saved as a calculation run and
        # referenced by the answer receipt, so every derived figure is traceable.
        receipt={
            "calculation_id": calculation_id,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "formula_version": FORMULA_VERSION,
            "label": args.label,
            "expression": args.expression,
            "input_hash": hashlib.sha256(args.expression.encode()).hexdigest()[:32],
            "result": shown,
            "rounded": format(rounded, "f"),
            "rounding_rule": "ROUND_HALF_UP to 2 decimal places for display",
            "units": "",
            "warnings": ["result rounded for display"] if rounded != result else [],
        },
    )


CALCULATE_TOOL = ToolSpec(
    name=TOOL_NAME,
    version=TOOL_VERSION,
    description=(
        "Evaluate an arithmetic expression exactly. Use this for EVERY numeric calculation in the "
        "answer (tax, margins, ratios, depreciation, conversions, totals) instead of calculating "
        "yourself. Compute a whole formula in ONE call with ** for powers — never approximate a "
        "power or round an intermediate step yourself. Loan EMI: P * r * (1 + r) ** n / ((1 + r) ** n - 1) "
        "with r the MONTHLY rate (annual % / 12 / 100) and n the number of months; compound growth: "
        "P * (1 + r) ** n; CAGR: (end / start) ** (1 / years) - 1."
    ),
    args_model=CalculateArgs,
    handler=_handle,
    data_source="application calculation engine",
    risk_level="low",
    timeout_seconds=2.0,
    allowed_roles=KRITON_TOOL_ROLES,
    tenant_scope="none",
    owner="Backend / Calculation",
)
