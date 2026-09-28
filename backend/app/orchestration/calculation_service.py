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
    # The repeated alternation is wrapped in an atomic group `(?>...)`: its two
    # branches both match plain digit/operator characters, so on any answer
    # text that never reaches a trailing `= result` (e.g. a chart's raw data
    # array of many numbers, some negative), an unbounded backtracking engine
    # explores every way of re-partitioning that run between the branches —
    # catastrophic (exponential-time) backtracking, confirmed hanging
    # multi-minute+ on a real 20-point GDP series with no `=` in it. Atomic
    # grouping commits to the first (greedy) partition and never backtracks
    # into it, which is a no-op for genuine `expr = result` matches (greedy
    # matching already stops at the right boundary with nothing to backtrack)
    # but turns the no-match case into an immediate, linear-time failure.
    r"(?P<expression>\(?\s*-?[0-9][0-9,.]*(?>(?:\s*[+\-*/×÷]\s*-?[0-9][0-9,.]*|[0-9,.()\s+\-*/×÷])*)\)?)"
    r"\s*=\s*[$£€]?\s*(?P<result>-?[0-9][0-9,]*(?:\.[0-9]+)?)"
    # The result must be complete: in chained working ("A - B - C = 5,50,000 -
    # 1,50,000 = 4,00,000") "5,50,000" is an intermediate expression, not the
    # value of A - B - C, and was flagged as a mismatch on a correct answer.
    r"(?![\d,]|\.\d|\s*[+\-*/×÷])"
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


def evaluate_expression(expression: str) -> Decimal:
    """Public entry point for the calculate tool — the same AST-whitelisted
    evaluator (numbers, + - * /, parentheses; no names, calls or powers) the
    question-parsing path uses. Raises ValueError on anything else."""
    return _evaluate(expression)


def _format_decimal(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.01")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


# "sales" alone means revenue, but not inside "cost of sales" — otherwise
# "Cost of sales is 160,000 and revenue is 250,000" read 160,000 as revenue.
_REVENUE_LABEL = r"revenue|(?<!of )sales"


def _number_for_label(query: str, labels: str) -> Decimal | None:
    match = re.search(rf"(?:{labels})(?:\s+(?:is|of))?\s*[:=]?\s*{_NUMBER}", query, re.IGNORECASE)
    return Decimal(match.group(1).replace(",", "")) if match else None


def build_calculation(query: str, history=()) -> DeterministicCalculation | None:
    expression: str | None = None
    formula_name = "Arithmetic calculation"
    inputs: list[WidgetInput] = []
    operation = "arithmetic"
    output_unit = "number"

    revenue = _number_for_label(query, _REVENUE_LABEL)
    sales_cost = _number_for_label(query, r"cost of sales|cost of goods sold|cogs")
    increase = re.search(r"cost of sales\s+increased?\s+by\s+(\d+(?:\.\d+)?)\s*%", query, re.I)
    if increase and re.search(r"revenue\s+(?:stayed|stays|remains?)\s+unchanged", query, re.I):
        for message in reversed(history):
            if message.role != "user":
                continue
            previous_revenue = _number_for_label(message.content, _REVENUE_LABEL)
            previous_cost = _number_for_label(message.content, r"cost of sales|cost of goods sold|cogs")
            if previous_revenue is not None and previous_cost is not None:
                revenue = revenue if revenue is not None else previous_revenue
                sales_cost = sales_cost if sales_cost is not None else previous_cost
                break
        if sales_cost is not None:
            sales_cost *= 1 + Decimal(increase.group(1)) / 100

    cost = _number_for_label(query, r"cost|purchase\s+price")
    residual = _number_for_label(query, r"residual(?:\s+value)?|salvage(?:\s+value)?")
    life = _number_for_label(query, r"useful\s+life|life")
    change = re.search(rf"\bfrom\s+{_NUMBER}\s+to\s+{_NUMBER}", query, re.I)
    actual = _number_for_label(query, r"actual")
    budget = _number_for_label(query, r"budget")
    if revenue is not None and sales_cost is not None and re.search(r"\b(?:gross profit|margin)\b", query, re.I):
        if revenue == 0:
            return None
        margin = bool(re.search(r"\bmargin\b", query, re.I))
        expression = f"({revenue} - {sales_cost}) / {revenue} * 100" if margin else f"{revenue} - {sales_cost}"
        formula_name = "Gross profit margin" if margin else "Gross profit"
        operation = "percentage" if margin else "difference"
        output_unit = "percent" if margin else "currency"
        inputs = [_widget_input("revenue", "Revenue", revenue, "currency"),
                  _widget_input("cost_of_sales", "Cost of sales", sales_cost, "currency")]
    elif change and re.search(r"percent|percentage|change|growth", query, re.I):
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
        output_unit="currency/year" if formula_name.startswith("Straight") else output_unit,
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


def _normalise_arithmetic(text: str) -> str:
    """Make money-formatted working checkable. "£74,000 ÷ £250,000 × 100 =
    29.6%" was read as "250,000 × 100" (the £ split the expression) and a
    correct answer was escalated as a calculation mismatch."""
    # LaTeX number/operator formatting the model uses inside formulas:
    # "50{,}000 \\times 0.06" was read as "000 * 0.06" and a correct
    # simple-interest answer was escalated.
    text = text.replace("{,}", ",").replace("\\%", "%").replace("\\cdot", "*")
    text = re.sub(r"\\(?:left|right)\s*([()\[\]])", r"\1", text)
    text = re.sub(r"\\[,;:! ]", " ", text)                       # LaTeX spacing commands
    text = re.sub(r"(?:[£$€₹]|\bRs\.?|\bINR|\bUSD|\bGBP|\bEUR)\s*(?=\d)", "", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)          # unicode dashes / minus sign
    return re.sub(r"(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*%(?=\s*[*×/÷)])", r"(\1/100)", text)  # "10% ×" -> (10/100)


def validate_answer_calculations(answer_text: str) -> list[str]:
    """Return failures only for simple equations we can verify with certainty."""
    failures: list[str] = []
    normalized = _normalise_arithmetic(answer_text.replace("\\times", "*").replace("\\div", "/"))
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
