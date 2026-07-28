"""
Calculation router — Phase 4 of the governed calculation architecture (see
docs/calculation_architecture.md).

Routing priority (the application decides, never the LLM):

    1. Supported statutory tax/benefit calculation -> PolicyEngine-US
    2. Approved named formula                       -> formula registry
    3. Plain arithmetic                              -> expression evaluator
    4. Anything else                                 -> unsupported / missing-input

A calculation_type naming a known statutory tax figure or a registered
formula can never be downgraded to generic arithmetic, even if the caller
also supplied a free-form `expression` — a professional methodology exists
for a reason, and skipping it for "close enough" arithmetic would silently
discard exactly the correctness the formula registry exists to guarantee.

PolicyEngine's actual execution stays where it already correctly lives —
app/domains/calculation/policyengine_engine.py + service.py, an async,
DB-aware, audit-logged pipeline already wired into orchestration/service.py.
This router does not re-implement or duplicate that call; for a statutory
calculation_type it only confirms routing and leaves execution to the
existing pipeline, same posture the delivery notes above take toward
avoiding a parallel architecture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.domains.calculation.expression_evaluator import (
    CalculationRecord,
    evaluate_expression,
)
from app.domains.calculation.formula_registry import (
    FormulaResult,
    execute_formula,
    get_formula,
    list_formulas,
)

# Statutory tax/benefit figures this codebase's PolicyEngine-US integration
# actually computes (policyengine_engine.py's _OUTPUT_VARIABLES) — kept as
# its own constant here (rather than importing it directly) since
# policyengine_engine.py's module docstring deliberately isolates the heavy
# policyengine_us import to first real use; importing that module just to
# read a tuple of variable names would defeat the point.
_STATUTORY_TAX_TYPES = frozenset({
    "federal_income_tax", "income_tax", "eitc", "earned_income_tax_credit",
    "ctc", "child_tax_credit", "standard_deduction", "state_income_tax",
})

ENGINE_POLICYENGINE = "policyengine_us"
ENGINE_FORMULA_REGISTRY = "formula_registry"
ENGINE_EXPRESSION_EVALUATOR = "expression_evaluator"
ENGINE_UNSUPPORTED = "unsupported"


def _build_formula_aliases() -> dict:
    """Maps a bare formula name ("gross_margin") to its fully-versioned id
    ("accounting.gross_margin.v1") so a router caller can name a formula
    without knowing its namespace or version. Exact, version-qualified IDs
    always work too (checked first in route())."""
    aliases: dict[str, str] = {}
    for definition in list_formulas():
        parts = definition.id.split(".")
        bare_name = parts[-2] if len(parts) >= 2 else definition.id
        # First registration for a given bare name wins; today every
        # formula has a distinct bare name, so this never actually collides.
        aliases.setdefault(bare_name, definition.id)
    return aliases


_FORMULA_ALIASES = _build_formula_aliases()


@dataclass(frozen=True)
class CalculationRequest:
    intent: str = "calculate"
    calculation_type: str = ""
    preferred_engine: Optional[str] = None   # a hint only — the router decides authoritatively
    inputs: dict = field(default_factory=dict)
    expression: Optional[str] = None


@dataclass(frozen=True)
class RouterDecision:
    engine: str
    calculation_type: str
    formula_id: Optional[str] = None
    result: Optional[object] = None   # FormulaResult | CalculationRecord | None (PolicyEngine defers execution)
    status: str = "routed"            # routed | executed | unsupported | missing_input
    message: str = ""


def _resolve_formula_id(calculation_type: str) -> Optional[str]:
    if get_formula(calculation_type) is not None:
        return calculation_type
    return _FORMULA_ALIASES.get(calculation_type)


def route(request: CalculationRequest) -> RouterDecision:
    calculation_type = (request.calculation_type or "").strip().lower()

    if not calculation_type:
        if request.expression:
            calculation_type = "arithmetic"
        else:
            return RouterDecision(
                engine=ENGINE_UNSUPPORTED, calculation_type="", status="unsupported",
                message="No calculation_type or expression supplied — nothing to route.",
            )

    # 1. Statutory tax/benefit — highest priority, never downgraded.
    if calculation_type in _STATUTORY_TAX_TYPES:
        return RouterDecision(
            engine=ENGINE_POLICYENGINE,
            calculation_type=calculation_type,
            status="routed",
            message=(
                "Routed to PolicyEngine-US. Execution happens via the existing "
                "app/domains/calculation household-extraction pipeline, not this router."
            ),
        )

    # 2. Approved named formula — also never downgraded to raw arithmetic,
    # even if request.expression was also supplied.
    formula_id = _resolve_formula_id(calculation_type)
    if formula_id is not None:
        result: FormulaResult = execute_formula(formula_id, request.inputs)
        status = "executed" if result.status == "verified" else result.status
        return RouterDecision(
            engine=ENGINE_FORMULA_REGISTRY,
            calculation_type=calculation_type,
            formula_id=formula_id,
            result=result,
            status=status,
            message="" if result.status == "verified" else "; ".join(result.errors),
        )

    # 3. Plain arithmetic — only reachable when calculation_type is exactly
    # "arithmetic"/"expression" or unrecognized as anything else, AND an
    # expression was actually supplied. A calculation_type naming something
    # else entirely (a formula/tax type this registry just doesn't know
    # about yet) must NOT silently fall back to raw arithmetic — that would
    # let the LLM route around a missing professional methodology.
    if calculation_type in ("arithmetic", "expression", "generic_arithmetic") and request.expression:
        record: CalculationRecord = evaluate_expression(
            request.expression, inputs=request.inputs, unit=_infer_unit(request.inputs),
        )
        status = "executed" if record.status == "verified" else "unsupported"
        return RouterDecision(
            engine=ENGINE_EXPRESSION_EVALUATOR,
            calculation_type=calculation_type,
            result=record,
            status=status,
            message="" if record.status == "verified" else "; ".join(record.errors),
        )

    # 4. Unrecognized calculation_type — never guessed at.
    return RouterDecision(
        engine=ENGINE_UNSUPPORTED,
        calculation_type=calculation_type,
        status="unsupported",
        message=(
            f"No governed engine recognizes calculation_type {calculation_type!r}. "
            "Add a named formula, extend the statutory-tax type set, or supply "
            "calculation_type='arithmetic' with an explicit expression for plain arithmetic."
        ),
    )


def _infer_unit(inputs: dict) -> str:
    for raw in inputs.values():
        if isinstance(raw, dict) and raw.get("unit"):
            return raw["unit"]
    return "USD"
