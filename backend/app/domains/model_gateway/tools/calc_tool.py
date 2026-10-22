"""calculate — deterministic arithmetic, so the model never does the maths itself.

The model writes the formula; the application computes it with the same
AST-whitelisted evaluator calculation_service uses (numbers, + - * /,
powers and parentheses only — no names, calls or code), and the model
explains the verified result.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

from decimal import ROUND_HALF_UP, Decimal, DivisionUndefined, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


# ── Batched calculations (optional form; not in the default registry) ───────
# docs/kriton-batched-calculator-and-balance-provenance-design.md §1.2. The
# single-expression form above is unchanged; this spec is registered only by
# build_default_registry(batch_calculations=True).

BATCH_TOOL_VERSION = "1.2"
MAX_BATCH_ITEMS = 12
_PRESERVE_NOTE = (" Preserve the exact operands above when displaying this working; "
                  "do not replace them with rounded inputs while keeping the same result.")


class CalculationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=240,
                            description="Arithmetic using numbers, + - * /, ** for powers and parentheses only.")
    label: str = Field(default="", max_length=120, description="What is being calculated.")


class CalculateBatchArgs(BaseModel):
    """Exactly one of `expression` (one calculation, as before) or
    `expressions` (up to 12 independent calculations)."""
    model_config = ConfigDict(extra="forbid")

    expression: str | None = Field(
        default=None, min_length=1, max_length=240,
        description="One arithmetic expression, e.g. \"(500000 - 425000) / 500000 * 100\".")
    label: str = Field(default="", max_length=120, description="What is being calculated (single form).")
    expressions: list[CalculationItem] | None = Field(
        default=None, min_length=1, max_length=MAX_BATCH_ITEMS,
        description=("Up to 12 INDEPENDENT calculations in one call, each {label, expression}. Use it whenever "
                     "you need several figures whose inputs you already have. No item may use another item's "
                     "result; compute a dependent figure in a later call or as one combined expression."))

    @model_validator(mode="after")
    def _one_form(self) -> "CalculateBatchArgs":
        if (self.expression is None) == (self.expressions is None):
            raise ValueError("give either expression or expressions, not both and not neither")
        return self


async def _handle_batch(args: CalculateBatchArgs) -> ToolResult:
    if args.expressions is None:
        # The single form: exactly the existing behaviour.
        return await _handle(CalculateArgs(expression=args.expression, label=args.label))
    lines: list[str] = []
    receipts: list[dict] = []
    failures: list[str] = []
    size = len(args.expressions)
    for index, item in enumerate(args.expressions, start=1):
        # Each item is evaluated on its own by the single-calculation path, so
        # one bad item cannot affect another's result or receipt.
        result = await _handle(CalculateArgs(expression=item.expression, label=item.label))
        prefix = f"{item.label}: " if item.label else ""
        if result.ok and result.receipt:
            receipts.append({**result.receipt, "tool_version": BATCH_TOOL_VERSION,
                             "batch_index": index, "batch_size": size})
            lines.append(f"{index}. " + result.content.replace(_PRESERVE_NOTE, ""))
        else:
            failures.append(result.error_code or "invalid_arguments")
            lines.append(f"{index}. {prefix}{item.expression} — NOT COMPUTED ({result.error_code}): {result.content} "
                         "Do not state a result for this item.")
    content = "\n".join(lines) + ("\n" + _PRESERVE_NOTE.strip() if receipts else "")
    from app.domains.model_gateway.tool_registry import MAX_RESULT_CHARS
    if len(content) > MAX_RESULT_CHARS - 200:
        # The output limit would cut the last items off: one compact line each,
        # every result kept (the receipts hold the full detail).
        compact = []
        for index, item in enumerate(args.expressions, start=1):
            receipt = next((r for r in receipts if r["batch_index"] == index), None)
            compact.append(f"{index}. {item.label[:60] + ': ' if item.label else ''}{item.expression} = "
                           f"{receipt['result']} (computed by the application)" if receipt
                           else f"{index}. {item.expression[:80]} — NOT COMPUTED. Do not state a result for this item.")
        content = "\n".join(compact)
    if not receipts:
        return ToolResult(ok=False, content=content, error_code=failures[0] if failures else "invalid_arguments",
                          items_total=size, items_failed=size)
    return ToolResult(ok=True, content=content, receipt=receipts[0], receipts=tuple(receipts),
                      items_total=size, items_failed=len(failures))


CALCULATE_BATCH_TOOL = replace(
    CALCULATE_TOOL,
    version=BATCH_TOOL_VERSION,
    description=CALCULATE_TOOL.description + (
        " To compute several independent figures, pass them together in `expressions` (up to 12) in ONE "
        "call instead of one call each."),
    args_model=CalculateBatchArgs,
    handler=_handle_batch,
)
