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

_NUMBER = r"(?:[$£€₹]\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)"
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
    r"(?P<expression>\(*\s*-?[0-9][0-9,.]*(?>(?:\s*[+\-*/×÷]\s*-?[0-9][0-9,.]*|[0-9,.()\s+\-*/×÷])*)\)?)"
    r"\s*=\s*[$£€]?\s*(?P<result>-?[0-9][0-9,]*(?:\.[0-9]+)?)(?P<percent>\s*%)?"
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
    # Further verified figures derived from the result (an EMI's total
    # payment and interest), given to the model alongside it.
    derived: tuple[tuple[str, str], ...] = ()

    def prompt_context(self) -> str:
        derived = "".join(f"{label}: {value}\n" for label, value in self.derived)
        if derived:
            # The model recomputed an EMI's totals from the unrounded EMI and
            # disagreed with the verified box beside its answer. Told only to
            # "state them", it then dropped the explanation altogether.
            derived += (
                "Explain the calculation as you normally would (formula, inputs, steps), but use "
                "these figures for the results instead of recomputing them, written with the "
                "question's currency symbol.\n"
            )
        return (
            "\n\nDETERMINISTIC CALCULATION (computed by the application; do not alter):\n"
            f"Expression: {self.expression}\nVerified result: {_format_decimal(self.result)}\n"
            f"{derived}"
        )


_MONEY = r"(?:₹|rs\.?|inr|[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(lakhs?|lacs?|crores?|million|m\b)?"
_LOAN_PRINCIPAL = re.compile(rf"\b(?:loan|borrow(?:ed|ing)?|principal|mortgage)\b(?:\s+(?:amount|of|is))*\s*[:=]?\s*{_MONEY}", re.I)
_PRINCIPAL_THEN_LOAN = re.compile(rf"{_MONEY}\s+(?:home\s+|car\s+|personal\s+)?(?:loan|mortgage)\b", re.I)
_ANNUAL_RATE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%", re.I)
_TERM = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(years?|yrs?|months?)\b", re.I)
# "18% GST on ₹50,000", "20% of 5,000": a percentage of a stated amount.
_PERCENT_OF = re.compile(
    rf"([0-9]+(?:\.[0-9]+)?)\s*%\s*(gst|vat|tds|tax|discount|commission|interest|tip)?\s*(?:on|of)\s+{_MONEY}",
    re.I,
)
_SCALE = {"lakh": Decimal(100_000), "lac": Decimal(100_000), "crore": Decimal(10_000_000),
          "million": Decimal(1_000_000), "m": Decimal(1_000_000)}


def _loan_terms(query: str) -> tuple[Decimal, Decimal, int] | None:
    """(principal, annual rate %, months) for a loan-repayment question."""
    if not re.search(r"\b(?:emi|monthly (?:payment|instal+ment|repayment)|instal+ment|amortis|amortiz)", query, re.I):
        return None
    principal_match = _LOAN_PRINCIPAL.search(query) or _PRINCIPAL_THEN_LOAN.search(query)
    rate_match = _ANNUAL_RATE.search(query)
    term_match = _TERM.search(query)
    if not (principal_match and rate_match and term_match):
        return None
    principal = Decimal(principal_match.group(1).replace(",", ""))
    scale = (principal_match.group(2) or "").lower().rstrip("s")
    principal *= _SCALE.get(scale, Decimal(1))
    months = Decimal(term_match.group(1)) * (1 if term_match.group(2).lower().startswith("m") else 12)
    if principal <= 0 or months <= 0 or months != months.to_integral_value() or months > 1200:
        return None
    return principal, Decimal(rate_match.group(1)), int(months)


# Powers make EMI, compound growth, annuity and discount factors computable
# in one exact step — without them the model approximated (1 + r)^180 as
# "≈ 3.70" and put a ₹17/month error into an EMI. Bounded so an expression
# can never become an expensive computation.
_MAX_EXPONENT = Decimal(1200)
_MAX_POWER_BASE = Decimal(10) ** 6


def _evaluate(expression: str) -> Decimal:
    cleaned = (expression.replace(",", "").replace("×", "*").replace("÷", "/").replace("^", "**"))
    cleaned = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", cleaned).strip()
    if len(cleaned) > 240 or not re.fullmatch(r"[0-9.()\s+\-*/]+", cleaned):
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
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            base, exponent = visit(node.left), visit(node.right)
            if abs(exponent) > _MAX_EXPONENT or abs(base) > _MAX_POWER_BASE:
                raise ValueError("power out of range")
            if exponent != exponent.to_integral_value() and base <= 0:
                # A fractional power of a non-positive number has no real value.
                raise ValueError("invalid power")
            return base ** exponent
        raise ValueError("unsupported arithmetic expression")

    try:
        return visit(tree)
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("invalid arithmetic expression") from exc


def evaluate_expression(expression: str) -> Decimal:
    """Public entry point for the calculate tool — the same AST-whitelisted
    evaluator (numbers, + - * /, bounded powers, parentheses; no names or
    calls) the question-parsing path uses. Raises ValueError on anything else."""
    return _evaluate(expression)


def _format_decimal(value: Decimal) -> str:
    rendered = format(value.quantize(Decimal("0.01")), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


# "sales" alone means revenue, but not inside "cost of sales" — otherwise
# "Cost of sales is 160,000 and revenue is 250,000" read 160,000 as revenue.
_REVENUE_LABEL = r"revenue|(?<!of )sales"


def _number_for_label(query: str, labels: str) -> Decimal | None:
    match = re.search(rf"(?:{labels})(?:\s+(?:is|are|of))?\s*[:=]?\s*{_NUMBER}", query, re.IGNORECASE)
    return Decimal(match.group(1).replace(",", "")) if match else None


_FINANCE_FORMULA = re.compile(
    r"\b(?:compound(?:ed|ing)?|future value|present value|emi|cagr|simple interest|annuity|npv|irr|"
    r"(?:net |gross |operating )?(?:profit )?margin|break[- ]?even|payback|depreciation|"
    r"monthly (?:payment|instal+ment)|markup|mark-up|percentage (?:change|increase|decrease)|"
    # Checking the user's own figures: "Subtotal ₹10,000, tax ₹1,800, total
    # ₹11,500 — check the arithmetic" was treated as a tax question, sent
    # to web search and answered "the sources provided do not state this".
    r"(?:check|verify|recheck|validate)\s+(?:the\s+|my\s+|this\s+)?(?:arithmetic|maths?|math|totals?|sums?|calculations?)|"
    r"reconcile|add(?:s)?\s+up)\b",
    re.I,
)
# Something the question expects to be LOOKED UP, not computed from its own
# figures: a current or statutory rate, a threshold, a provision.
_NEEDS_LOOKUP = re.compile(
    # "current" alone, not "current assets/liabilities/ratio": a ratio question
    # was taken for a rate lookup, so its calculations were refused as uncited.
    r"\b(?:current(?!\s+(?:assets?|liabilit(?:y|ies)|ratio|account|portion))|currently|today|latest|prevailing|this year'?s|repo|rbi|federal reserve|bank rate|"
    r"tax (?:rate|slab|bracket)s?|slabs?|thresholds?|limits?|gst rate|vat rate|according to|as per|"
    r"under section|act|rules?|standard|ifrs|ind as|gaap)\b",
    re.I,
)


_ACCOUNTING_CURRENT = re.compile(
    r"\bcurrent\s+(?:and\s+quick\s+)?(?:assets?|liabilit(?:y|ies)|ratios?|account|portion)\b", re.I,
)


def needs_lookup(query: str) -> bool:
    """The question asks for something that must be looked up — a current or
    statutory rate, slab, threshold or provision — rather than computed."""
    # Accounting uses of "current" are labels on the user's own figures, not
    # a request for today's rate ("Current and quick ratio?").
    text = _ACCOUNTING_CURRENT.sub(" ", query or "")
    return bool(_NEEDS_LOOKUP.search(text))


def is_self_contained_calculation(query: str, history=()) -> bool:
    """Every input is in the question and nothing needs looking up — "invest
    $10,000 at 8% compounded annually for 10 years". Web search adds nothing
    to such a question: it returned unrelated World Bank reports that were
    then cited as the answer's sources."""
    if needs_lookup(query):
        return False
    # history: a follow-up ("if cost of sales rose 10%…") whose other inputs
    # are earlier in the conversation is just as self-contained.
    if build_calculation(query, history) is not None:
        return True
    # "Revenue is zero and expenses are ₹15,000" states two figures; with
    # "zero" uncounted it went to web search and cited unrelated reports.
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?|\b(?:zero|nil)\b", query, re.I)
    if len(numbers) >= 2 and _FINANCE_FORMULA.search(query):
        return True
    # A chart of figures the message supplies ("Waterfall chart: revenue 500,
    # cost of sales −300, … tax −20") is built from them. Read as a tax
    # question, it ran a web search, required citations for the user's own
    # numbers and answered "the sources provided do not state this".
    from app.orchestration.response_planner import detect_explicit_visual_request
    return len(numbers) >= 3 and detect_explicit_visual_request(query)


def build_calculation(query: str, history=()) -> DeterministicCalculation | None:
    from app.orchestration.calculations.engine import asks_several_questions
    if asks_several_questions(query):
        return None
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
    loan = _loan_terms(query)
    derived: tuple[tuple[str, str], ...] = ()
    if loan is not None:
        principal, annual_rate, months = loan
        if annual_rate == 0:
            expression = f"{principal} / {months}"
        else:
            r = f"({annual_rate} / 12 / 100)"
            expression = f"{principal} * {r} * (1 + {r}) ** {months} / ((1 + {r}) ** {months} - 1)"
        formula_name = "Loan EMI"
        operation = "loan_emi"
        output_unit = "currency/month"
        inputs = [
            _widget_input("principal", "Loan amount", principal, "currency"),
            _widget_input("annual_rate", "Annual interest rate", annual_rate, "percent"),
            _widget_input("months", "Term", Decimal(months), "months"),
        ]
    elif (percent_of := _PERCENT_OF.search(query)) is not None:
        rate, label = Decimal(percent_of.group(1)), (percent_of.group(2) or "").upper()
        amount = Decimal(percent_of.group(3).replace(",", ""))
        amount *= _SCALE.get((percent_of.group(4) or "").lower().rstrip("s"), Decimal(1))
        expression = f"{amount} * {rate} / 100"
        formula_name = f"{label} amount" if label else "Percentage of amount"
        operation = "percentage"
        output_unit = "currency"
        inputs = [
            _widget_input("amount", "Amount", amount, "currency"),
            _widget_input("rate", f"{label} rate" if label else "Rate", rate, "percent"),
        ]
    elif revenue is not None and sales_cost is not None and re.search(r"\b(?:gross profit|margin)\b", query, re.I):
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
    elif (cost is not None and residual is not None and life is not None and re.search(r"depreciat", query, re.I)
          and cost > residual and life > 0):
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
        # An expression needs an operator between operands: "What is 18% GST
        # on ₹50,000?" otherwise became the "calculation" 18 = 18, shown in a
        # Verified calculation box beside the real answer (₹9,000).
        if match and re.search(r"[\d)]\s*[+\-*/x×÷]\s*[\d(]", match.group(1)):
            expression = match.group(1).strip().rstrip("?. ")
    if not expression:
        return None
    try:
        result = _evaluate(expression)
    except (SyntaxError, ValueError):
        return None

    rendered = _format_decimal(result)
    if loan is not None:
        # Totals from the EMI as shown (two decimals), so "EMI × months"
        # in the answer's working re-checks exactly.
        emi = result.quantize(Decimal("0.01"))
        total = emi * loan[2]
        # Money keeps both decimals: _format_decimal shows 44986.30 as
        # "44986.3", which the model then copied into the answer.
        def money(value: Decimal) -> str:
            return format(value.quantize(Decimal("0.01")), "f")

        derived = (
            ("EMI (rounded to 2 decimals)", money(emi)),
            (f"Total paid over {loan[2]} months ({money(emi)} * {loan[2]})", money(total)),
            (f"Total interest ({money(total)} - {money(loan[0])})", money(total - loan[0])),
        )
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
        expression=expression, result=result, widget=widget, record=record, chart=chart, derived=derived,
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
    # "\\frac{18,00,000}{1,00,00,000}\\times 100 = 1.8\\%" was never read, so a
    # ROCE answer ten times too small went out unchecked.
    text = re.sub(r"\\(?:text|mathrm|mathbf|textbf|boldsymbol)\s*\{([^{}]*)\}", r"\1", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\\[dt]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\(?:left|right)\s*([()\[\]])", r"\1", text)
    text = re.sub(r"\\[,;:! ]", " ", text)                       # LaTeX spacing commands
    text = re.sub(r"(?:[£$€₹]|\bRs\.?|\bINR|\bUSD|\bGBP|\bEUR)\s*(?=\d)", "", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)          # unicode dashes / minus sign
    # "10% ×" -> (10/100); also inside brackets and sums, so "\\frac{63.75\\%}{3}
    # = 21.75\\%" (really 21.25%) is checked instead of skipped.
    text = re.sub(r"(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*%(?=\s*[*×/÷)+\-])", r"(\1/100)", text)
    # "× 12% =" as well: "₹40,000 × 12% = ₹2,400" (really ₹4,800) was never
    # checked, because the % sat between the expression and its "=".
    return re.sub(r"([*×/÷]\s*)(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*%", r"\1(\2/100)", text)


_DEBIT_HEADER = re.compile(r"\b(dr|debit)\b", re.I)
_CREDIT_HEADER = re.compile(r"\b(cr|credit)\b", re.I)
_AMOUNT = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _amount(cell: str) -> Decimal | None:
    match = _AMOUNT.search(cell.replace("₹", "").replace("Rs.", ""))
    try:
        return Decimal(match.group().replace(",", "")) if match else None
    except InvalidOperation:
        return None


def _journal_balance_failures(answer_text: str) -> list[str]:
    """A journal table whose debit and credit columns do not total the same.
    "Share Capital Dr 10,000 / Calls in Arrears Dr 3,000 / Share Forfeiture
    Cr 7,000" (13,000 against 7,000) went out as an answer."""
    failures: list[str] = []
    lines = answer_text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        block = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            block.append(_cells(lines[index]))
            index += 1
        header, rows = block[0], [row for row in block[1:] if not all(set(c) <= set("-: ") for c in row)]
        debit = next((i for i, cell in enumerate(header) if _DEBIT_HEADER.search(cell)), None)
        credit = next((i for i, cell in enumerate(header) if _CREDIT_HEADER.search(cell)), None)
        if debit is None or credit is None or debit == credit or not rows:
            continue

        def numeric_column(column: int) -> int:
            # "Account (Debit) | Amount | Account (Credit) | Amount": the
            # figures sit in the column after the one that names the side.
            values = [_amount(row[column]) for row in rows if column < len(row) and row[column]]
            if values and sum(v is not None for v in values) * 2 < len(values) and column + 1 < len(header):
                return column + 1
            return column

        debit, credit = numeric_column(debit), numeric_column(credit)
        totals = [Decimal(0), Decimal(0)]
        for row in rows:
            if row and re.search(r"\btotal\b", row[0], re.I):
                continue
            for slot, column in enumerate((debit, credit)):
                value = _amount(row[column]) if column < len(row) else None
                if value is not None:
                    totals[slot] += value
        if totals[0] > 0 and totals[1] > 0 and abs(totals[0] - totals[1]) > Decimal("0.5"):
            failures.append(
                f"Journal entry does not balance: debits total {_format_decimal(totals[0])}, "
                f"credits total {_format_decimal(totals[1])}."
            )
    return failures


def validate_answer_calculations(answer_text: str) -> list[str]:
    """Return failures only for simple equations we can verify with certainty."""
    failures: list[str] = []
    normalized = _normalise_arithmetic(answer_text.replace("\\times", "*").replace("\\div", "/"))
    for match in _EQUATION.finditer(normalized):
        expression = match.group("expression").strip()
        if not any(operator in expression for operator in "+-*/×÷"):
            continue
        # Powers are outside what this checker evaluates, and the match
        # starts after the exponent: "(150,000 ÷ 100,000)^(1/3) − 1 =
        # 0.144714" (a correct CAGR) was judged as "(1/3) − 1 = -0.67", and
        # that one false mismatch replaced a whole nine-part answer.
        line_start = normalized.rfind("\n", 0, match.start()) + 1
        if re.search(r"\^|\*\*", normalized[line_start:match.end()]):
            continue
        try:
            expected = _evaluate(expression)
            stated = Decimal(match.group("result").replace(",", ""))
        except (SyntaxError, ValueError, InvalidOperation):
            continue
        # "200,000 / 500,000 = 40%" states the ratio as a percentage.
        if match.group("percent"):
            # An explicit ×100 already converted the ratio to percent units.
            candidates = [expected] if re.search(r"[×*]\s*100\s*\)*$", expression) else [expected * 100]
        else:
            candidates = [expected]
        # Judge the precision displayed, not the size of the amount. A
        # relative tolerance allowed a 53-rupee error on a million-rupee sum.
        tolerance = Decimal(5).scaleb(stated.as_tuple().exponent - 1)
        if all(abs(candidate - stated) > tolerance
               for candidate in candidates):
            failures.append(
                f"Calculation mismatch: {expression} equals {_format_decimal(expected)}, "
                f"not {_format_decimal(stated)}."
            )
    return failures + _journal_balance_failures(answer_text)


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
