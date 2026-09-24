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
from app.domains.calculations.schemas import (
    CalculationResult, LiveObservation, NumericInput, VerifiedChartSeries, VerifiedChartSpec,
)

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
    record: CalculationResult
    chart: VerifiedChartSpec

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
    operation = "arithmetic"

    cost = _number_for_label(query, r"cost|purchase\s+price")
    residual = _number_for_label(query, r"residual(?:\s+value)?|salvage(?:\s+value)?")
    life = _number_for_label(query, r"useful\s+life|life")
    change = re.search(rf"\bfrom\s+{_NUMBER}\s+to\s+{_NUMBER}", query, re.I)
    actual = _number_for_label(query, r"actual")
    budget = _number_for_label(query, r"budget")
    if change and re.search(r"percent|percentage|change|growth", query, re.I):
        old = Decimal(change.group(1).replace(",", ""))
        new = Decimal(change.group(2).replace(",", ""))
        if old == 0:
            return None
        expression = f"({new} - {old}) / {old} * 100"
        formula_name = "Percentage change"
        operation = "percentage_change"
        inputs = [
            _widget_input("prior", "Prior value", old, "number"),
            _widget_input("current", "Current value", new, "number"),
        ]
    elif actual is not None and budget is not None and re.search(r"variance", query, re.I):
        expression = f"{actual} - {budget}"
        formula_name = "Variance"
        operation = "variance"
        inputs = [
            _widget_input("actual", "Actual", actual, "currency"),
            _widget_input("budget", "Budget", budget, "currency"),
        ]
    elif cost is not None and residual is not None and life is not None and re.search(r"depreciat", query, re.I):
        expression = f"({cost} - {residual}) / {life}"
        formula_name = "Straight-line depreciation"
        operation = "straight_line_depreciation"
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
    calculation_id = f"calc_{uuid.uuid4().hex}"
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
        calculation_id=calculation_id,
    )
    numeric_inputs = [
        NumericInput(name=item.name, value=item.value, unit=item.unit)
        for item in inputs
    ] or [
        NumericInput(name=f"operand_{index}", value=value.replace(",", ""), unit="number")
        for index, value in enumerate(re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", expression), start=1)
    ]
    record = CalculationResult(
        calculation_id=calculation_id,
        operation=operation,
        rule_version=f"{operation}:v1",
        inputs=numeric_inputs,
        output_value=rendered,
        output_unit=widget.output_unit,
    )
    chart = VerifiedChartSpec(
        chart_id=f"chart_{uuid.uuid4().hex}",
        type="kpi",
        title=formula_name,
        categories=[widget.output_label],
        series=[VerifiedChartSeries(
            name=widget.output_label,
            values=[rendered],
            unit=widget.output_unit,
            source_ids=[calculation_id],
        )],
        calculation_id=calculation_id,
    )
    return DeterministicCalculation(
        expression=expression, result=result, widget=widget, record=record, chart=chart,
    )


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


def build_observation_chart(observations: list[LiveObservation]) -> VerifiedChartSpec | None:
    if not observations:
        return None
    unit = observations[0].unit
    compatible = [item for item in observations if item.unit == unit]
    try:
        values = [_format_decimal(Decimal(item.value)) for item in compatible]
    except InvalidOperation:
        return None
    return VerifiedChartSpec(
        chart_id=f"chart_{uuid.uuid4().hex}", type="line",
        title=compatible[0].indicator,
        categories=[item.period for item in compatible],
        series=[VerifiedChartSeries(
            name=compatible[0].indicator, values=values, unit=unit,
            source_ids=[item.observation_id for item in compatible],
        )],
        calculation_id="live_observations",
    )
