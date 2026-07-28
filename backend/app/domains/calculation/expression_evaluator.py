"""
Safe, sandboxed arithmetic expression evaluator — Phase 1 of the governed
calculation architecture (see docs/calculation_architecture.md).

The model may propose an arithmetic expression ("250000 - 180000"), but it
never computes the answer itself: this module parses the expression into a
Python AST, rejects anything that is not a numeric literal, parenthesis, or
+ - * / unary +/-, then evaluates the remaining tree with decimal.Decimal
(never binary float) so the result is exact for financial figures.

Security model: this is NOT a general-purpose sandbox around eval()/exec() —
those are never called anywhere in this module. Instead, `ast.parse()` builds
a syntax tree that is walked and type-checked node-by-node; only a small
allow-list of node types can appear at all (Expression, BinOp with
Add/Sub/Mult/Div, UnaryOp with UAdd/USub, Constant holding int/float, plus
the Load context that follows on those). Anything else — Name, Call,
Attribute, Subscript, List/Dict/Set/Tuple, comprehensions, Lambda, BoolOp,
Compare, Assign, Import, Pow — raises ExpressionRejected before evaluation
ever starts. There is no code path from a hostile expression string to
arbitrary Python execution, because no Python execution primitive is ever
invoked on user/model-supplied text.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Optional
from uuid import uuid4

ENGINE_NAME = "expression_evaluator"
ENGINE_VERSION = "1.0.0"

# Financial figures never need more precision than this; a generous ceiling
# that still bounds worst-case intermediate-value blowup from a maliciously
# deep expression (see _MAX_AST_DEPTH / _MAX_OPERATIONS below for the actual
# resource-exhaustion guards — this is a correctness ceiling, not the
# primary defense).
getcontext().prec = 50

_MAX_EXPRESSION_LENGTH = 200
_MAX_AST_DEPTH = 24
_MAX_OPERATIONS = 64
_MAX_MAGNITUDE = Decimal("1e15")  # ~$1 quadrillion — far beyond any real financial figure

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


class ExpressionRejected(Exception):
    """Raised for any expression that fails validation before evaluation.
    Callers should treat this as 'no verified result exists' — never fall
    back to asking the LLM to compute the value itself."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CalculationRecord:
    """The structured, auditable result of a single deterministic
    calculation — the shared shape emitted by every engine in this domain
    (expression evaluator, formula registry, PolicyEngine wrapper), so
    Checkpoint C's provenance check (see provenance.py) has one contract to
    verify regardless of which engine produced the number."""

    calculation_id: str
    engine: str
    engine_version: str
    expression: str
    inputs: dict = field(default_factory=dict)
    result: str = ""          # Decimal, stringified — never a raw float
    unit: str = "USD"
    rounding_policy: str = "none"
    status: str = "verified"  # verified | error
    assumptions: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "calculation_id": self.calculation_id,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "expression": self.expression,
            "inputs": self.inputs,
            "result": self.result,
            "unit": self.unit,
            "rounding_policy": self.rounding_policy,
            "status": self.status,
            "assumptions": self.assumptions,
            "errors": self.errors,
        }


def _new_calculation_id() -> str:
    return f"calc-{uuid4().hex[:12]}"


def _count_nodes(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def _depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    if not children:
        return 1
    return 1 + max(_depth(child) for child in children)


def _validate_syntax(expression: str) -> ast.Expression:
    if not expression or not expression.strip():
        raise ExpressionRejected("Expression is empty.")
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ExpressionRejected(
            f"Expression exceeds the maximum allowed length of {_MAX_EXPRESSION_LENGTH} characters."
        )
    # Reject anything that isn't plausibly arithmetic before even parsing —
    # a cheap first filter; the AST walk below is the real security
    # boundary, this just gives a clearer rejection reason for obviously
    # non-numeric input.
    if not re.fullmatch(r"[\d\s()+\-*/.,eE]+", expression):
        raise ExpressionRejected(
            "Expression contains characters outside numbers, parentheses, and + - * / ."
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ExpressionRejected(f"Invalid arithmetic syntax: {exc}") from exc

    node_count = _count_nodes(tree)
    if node_count > _MAX_OPERATIONS:
        raise ExpressionRejected(
            f"Expression has {node_count} AST nodes, exceeding the maximum of {_MAX_OPERATIONS}."
        )
    depth = _depth(tree)
    if depth > _MAX_AST_DEPTH:
        raise ExpressionRejected(
            f"Expression nesting depth {depth} exceeds the maximum of {_MAX_AST_DEPTH}."
        )
    return tree  # type: ignore[return-value]


def _to_decimal(value) -> Decimal:
    try:
        # str() first — Decimal(float) reproduces float's own binary
        # imprecision (e.g. Decimal(0.1) != Decimal("0.1")); going through
        # the literal's own repr keeps exactly what was written.
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ExpressionRejected(f"Invalid numeric literal: {value!r}") from exc


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionRejected(f"Unsupported literal type: {type(node.value).__name__}")
        value = _to_decimal(node.value)
        if abs(value) > _MAX_MAGNITUDE:
            raise ExpressionRejected(f"Numeric magnitude {value} exceeds the maximum of {_MAX_MAGNITUDE}.")
        return value

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExpressionRejected(f"Unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            else:  # ast.Div
                result = left / right
        except DivisionByZero as exc:
            raise ExpressionRejected("Division by zero.") from exc
        except InvalidOperation as exc:
            raise ExpressionRejected(f"Invalid arithmetic operation: {exc}") from exc
        if abs(result) > _MAX_MAGNITUDE:
            raise ExpressionRejected(f"Intermediate result magnitude exceeds the maximum of {_MAX_MAGNITUDE}.")
        return result

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise ExpressionRejected(f"Unsupported unary operator: {type(node.op).__name__}")
        operand = _eval_node(node.operand)
        return operand if isinstance(node.op, ast.UAdd) else -operand

    # Everything else — Name, Call, Attribute, Subscript, List, Dict, Set,
    # Tuple, comprehensions, Lambda, BoolOp, Compare, IfExp, Assign, Import,
    # Pow, and anything not explicitly allowed above — is rejected by name
    # so the failure reason is legible in an audit log.
    raise ExpressionRejected(f"Unsupported expression element: {type(node).__name__}")


def evaluate_expression(
    expression: str,
    *,
    inputs: Optional[dict] = None,
    unit: str = "USD",
) -> CalculationRecord:
    """The only public entry point. Always returns a CalculationRecord —
    never raises for a rejected expression, so a caller doesn't need a
    try/except just to get a structured 'why this was refused' answer to
    show the user. Raises only ExpressionRejected is never actually thrown
    from here; internal helpers raise it and it's caught below."""
    calculation_id = _new_calculation_id()
    try:
        tree = _validate_syntax(expression)
        result = _eval_node(tree)
        return CalculationRecord(
            calculation_id=calculation_id,
            engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            expression=expression,
            inputs=inputs or {},
            result=str(result),
            unit=unit,
            rounding_policy="none",
            status="verified",
            assumptions=[],
            errors=[],
        )
    except ExpressionRejected as exc:
        return CalculationRecord(
            calculation_id=calculation_id,
            engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            expression=expression,
            inputs=inputs or {},
            result="",
            unit=unit,
            rounding_policy="none",
            status="error",
            assumptions=[],
            errors=[exc.reason],
        )
