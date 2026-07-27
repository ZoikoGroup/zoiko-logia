"""
Deterministic calculation engine — Master Architecture Build Doctrine §3:
"Deterministic calculation, not LLM arithmetic. Kriton™ may draft
explanations, but amounts, schedules, ratios, tax illustrations, and
journal-entry calculations must be produced or validated by deterministic
services." Before this module, nothing in the codebase enforced this —
the model's own arithmetic was trusted outright.

orchestration/service.py's grounded_input prompt already instructs the
model to "show the formula and the substituted values step by step" for
any calculation. This module doesn't replace that — it VALIDATES it: pull
out every "<formula> = <stated result>" the model wrote, recompute the
formula independently with a safe, whitelisted expression evaluator (never
Python's own eval() — that would execute arbitrary code from model output,
a real injection surface), and flag any calculation where the model's
stated result doesn't match, within a small rounding tolerance.

Wired into massarius/answer_validator.py as Checkpoint C's 8th check.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

# Matches "<arithmetic expression> = <result>" in free text. The LHS must
# contain at least one operator (+, -, *, /) to count as a calculation —
# without that guard, an ordinary sentence like "the total = $14,000"
# would false-positive as something to verify. $ and , are stripped before
# evaluation, not part of the grammar itself.
_CALCULATION_PATTERN = re.compile(
    r"([\d,.\s()%$]*[\d][\d,.\s()%$]*[+\-*/][\d,.\s()%$+\-*/]*\d[\d,.\s()%$]*)"
    r"\s*=\s*\$?\s*([\d][\d,]*\.?\d*)\s*%?"
)

# Only these AST node types are ever evaluated — no names, calls,
# attributes, subscripts, comprehensions, or anything else that could let
# model-generated text execute arbitrary code. This is the entire safety
# boundary; do not widen it without re-reasoning about injection risk.
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub,
)


class UnsafeExpressionError(ValueError):
    pass


_PERCENT_LITERAL = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def safe_eval(expr: str) -> float:
    """Evaluates a pure arithmetic expression (+, -, *, /, %, **, unary
    minus, parentheses, numeric literals only) via Python's `ast` module,
    never `eval()`. Raises UnsafeExpressionError for anything outside that
    whitelist — a name, call, attribute, or any other node type — rather
    than silently executing it.

    "N%" means "N/100" here (e.g. "500 * 20%" == 100) — a real bug caught
    in testing: naively deleting the '%' character turned "20%" into the
    literal number 20, silently changing "500 * 20% = 100" (correct) into
    a false arithmetic-mismatch report. Converted to "(N/100)" BEFORE
    stripping $/, so the percentage's actual mathematical meaning survives."""
    cleaned = _PERCENT_LITERAL.sub(r"(\1/100)", expr)
    cleaned = cleaned.replace("$", "").replace(",", "").strip()
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpressionError(f"not a parseable expression: {expr!r}") from e

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpressionError(
                f"expression contains a disallowed construct ({type(node).__name__}): {expr!r}"
            )
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise UnsafeExpressionError(f"non-numeric constant in expression: {expr!r}")

    return eval(compile(tree, "<calculation>", "eval"))  # noqa: S307 — whitelisted AST only, not raw eval


@dataclass
class CalculationCheck:
    formula: str
    stated_result: float
    computed_result: float
    matches: bool


def extract_and_verify_calculations(text: str, *, relative_tolerance: float = 0.01) -> list[CalculationCheck]:
    """Finds every "<arithmetic> = <result>" pattern in the text,
    recomputes it independently, and reports whether the model's stated
    result matches. relative_tolerance=0.01 (1%) absorbs ordinary rounding
    in the model's own presentation (e.g. "$3.96 trillion" vs the exact
    value) without absorbing a genuine arithmetic error.

    Fails open per this codebase's established convention for every other
    semantic/derived check — a formula this parser can't safely evaluate
    is skipped, not treated as a failure; only a confirmed MISMATCH is
    ever reported."""
    results: list[CalculationCheck] = []
    for match in _CALCULATION_PATTERN.finditer(text):
        formula_text, stated_text = match.group(1).strip(), match.group(2)
        try:
            stated_result = float(stated_text.replace(",", ""))
            computed_result = safe_eval(formula_text)
        except (UnsafeExpressionError, ValueError, ZeroDivisionError, SyntaxError):
            continue
        tolerance = max(abs(stated_result) * relative_tolerance, 0.01)
        matches = abs(computed_result - stated_result) <= tolerance
        results.append(CalculationCheck(
            formula=formula_text, stated_result=stated_result,
            computed_result=computed_result, matches=matches,
        ))
    return results
