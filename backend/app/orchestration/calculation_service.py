"""Deterministic arithmetic extraction and answer validation.

Only explicitly structured arithmetic is handled here. Ambiguous word problems
are deliberately left to the normal answer path instead of guessing a formula.
"""
from __future__ import annotations

import ast
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

from app.orchestration.schemas import CalculationWidget, ChartPoint, WidgetInput

_NUMBER = r"(?:[$£€]\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)"
_EXPLICIT = re.compile(
    r"(?:calculate|compute|evaluate|what\s+is)\s+([0-9$£€,\.\s()+\-*/x×÷]+)", re.IGNORECASE
)
_EQUATION = re.compile(
    r"(?P<expression>\(?\s*-?[0-9][0-9,.]*(?:\s*[+\-*/×÷]\s*-?[0-9][0-9,.]*|[0-9,.()\s+\-*/×÷])*\)?)"
    r"\s*=\s*[$£€]?\s*(?P<result>-?[0-9][0-9,]*(?:\.[0-9]+)?)"
)


@dataclass(frozen=True)
class DeterministicCalculation:
    expression: str
    result: Decimal
    widget: CalculationWidget

    def prompt_context(self) -> str:
        return (
            "\n\nDETERMINISTIC CALCULATION (computed by the application; do not alter):\n"
            f"Expression: {self.expression}\nVerified result: {_format_decimal(self.result)}\n"
        )


def _evaluate(expression: str) -> Decimal:
    cleaned = (expression.replace(",", "").replace("×", "*").replace("÷", "/"))
    cleaned = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", cleaned).strip()
    if len(cleaned) > 160 or not re.fullmatch(r"[0-9.()\s+\-*/]+", cleaned):
        raise ValueError("unsupported arithmetic expression")
    tree = ast.parse(cleaned, mode="eval")

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("unsupported arithmetic expression")

    try:
        return visit(tree)
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("invalid arithmetic expression") from exc


def _format_decimal(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.01")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _number_for_label(query: str, labels: str) -> Decimal | None:
    match = re.search(rf"(?:{labels})(?:\s+(?:is|of))?\s*[:=]?\s*{_NUMBER}", query, re.IGNORECASE)
    return Decimal(match.group(1).replace(",", "")) if match else None


def build_calculation(query: str) -> DeterministicCalculation | None:
    expression: str | None = None
    formula_name = "Arithmetic calculation"
    inputs: list[WidgetInput] = []

    cost = _number_for_label(query, r"cost|purchase\s+price")
    residual = _number_for_label(query, r"residual(?:\s+value)?|salvage(?:\s+value)?")
    life = _number_for_label(query, r"useful\s+life|life")
    if cost is not None and residual is not None and life is not None and re.search(r"depreciat", query, re.I):
        expression = f"({cost} - {residual}) / {life}"
        formula_name = "Straight-line depreciation"
        inputs = [
            _widget_input("cost", "Cost", cost, "currency"),
            _widget_input("residual", "Residual value", residual, "currency"),
            _widget_input("life", "Useful life", life, "years"),
        ]
    else:
        match = _EXPLICIT.search(query)
        if match:
            expression = match.group(1).strip().rstrip("?. ")
    if not expression:
        return None
    try:
        result = _evaluate(expression)
    except (SyntaxError, ValueError):
        return None

    rendered = _format_decimal(result)
    widget = CalculationWidget(
        formula_id="straight_line_depreciation" if formula_name.startswith("Straight") else "arithmetic",
        formula_name=formula_name,
        formula_display=f"{expression} = {rendered}",
        methodology_reference="Deterministic Decimal arithmetic",
        inputs=inputs,
        output_label="Annual depreciation" if formula_name.startswith("Straight") else "Result",
        output_value=rendered,
        output_unit="currency/year" if formula_name.startswith("Straight") else "number",
        chart_type="kpi",
        chart_label=formula_name,
        chart_x_label="",
        chart_y_label="",
        chart_points=[ChartPoint(x="result", y=rendered)],
        calculation_id=f"calc_{uuid.uuid4().hex}",
    )
    return DeterministicCalculation(expression=expression, result=result, widget=widget)


def _widget_input(name: str, label: str, value: Decimal, unit: str) -> WidgetInput:
    magnitude = abs(value)
    return WidgetInput(
        name=name, label=label, value=_format_decimal(value), unit=unit,
        min="0", max=_format_decimal(max(magnitude * 2, Decimal("1"))),
        step="1" if value == value.to_integral() else "0.01",
    )


def validate_answer_calculations(answer_text: str) -> list[str]:
    """Return failures only for simple equations we can verify with certainty."""
    failures: list[str] = []
    normalized = answer_text.replace("\\times", "*").replace("\\div", "/")
    for match in _EQUATION.finditer(normalized):
        expression = match.group("expression").strip()
        if not any(operator in expression for operator in "+-*/×÷"):
            continue
        try:
            expected = _evaluate(expression)
            stated = Decimal(match.group("result").replace(",", ""))
        except (SyntaxError, ValueError, InvalidOperation):
            continue
        tolerance = max(Decimal("0.01"), abs(expected) * Decimal("0.0001"))
        if abs(expected - stated) > tolerance:
            failures.append(
                f"Calculation mismatch: {expression} equals {_format_decimal(expected)}, "
                f"not {_format_decimal(stated)}."
            )
    return failures
