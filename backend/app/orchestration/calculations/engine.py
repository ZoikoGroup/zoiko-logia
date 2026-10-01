"""Deterministic accounting calculation planner and executor.

The query parser only extracts explicitly labelled values. It never asks an
LLM to invent inputs and never executes generated code. Money is calculated
with Decimal and intermediate values remain unrounded; presentation rounding
is applied only when formatting the response.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.orchestration.calculations.schemas import (
    CalculationInput, CalculationOutput, CalculationResult,
)

_NUMBER_TEXT = r"-?\d[\d,]*(?:\.\d+)?"
_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR"}
_CURRENCY_CODES = ("GBP", "USD", "EUR", "INR", "AED")
_CALCULATION_HINT = re.compile(
    r"\b(calculate|compute|work out|determine|what is|find)\b", re.I,
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "turnover"),
    "cost_of_sales": ("cost of sales", "cost_of_sales", "cogs", "cost"),
    "gross_profit": ("gross profit", "gross_profit"),
    "operating_expenses": ("operating expenses", "operating expense", "opex"),
    "operating_profit": ("operating profit", "operating income", "ebit"),
    "net_amount": ("net amount", "net value", "net invoice", "net"),
    "gross_amount": ("gross amount", "gross total", "invoice total", "total including vat"),
    "vat_rate": ("vat rate", "vat", "tax rate"),
    "old_value": ("old value", "previous value", "starting value", "from"),
    "new_value": ("new value", "current value", "ending value", "to"),
    "current_assets": ("current assets",),
    "inventory": ("inventory", "stock"),
    "current_liabilities": ("current liabilities",),
    "total_liabilities": ("total liabilities", "liabilities", "debt"),
    "equity": ("shareholders equity", "shareholders' equity", "equity"),
    "total_assets": ("total assets",),
    "asset_cost": ("asset cost", "cost of the asset", "asset costs"),
    "residual_value": ("residual value", "salvage value"),
    "useful_life": ("useful life", "asset life"),
    "selling_price": ("selling price", "sale price", "price per unit"),
    "variable_cost": ("variable cost", "variable cost per unit"),
    "fixed_costs": ("fixed costs", "fixed cost"),
    "principal": ("principal", "amount invested", "investment"),
    "interest_rate": ("interest rate", "annual rate", "rate"),
    "years": ("years", "year", "term"),
    "future_value": ("future value",),
}


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _find_value(query: str, aliases: tuple[str, ...], *, percentage: bool = False) -> tuple[Decimal, str | None] | None:
    alias_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    currency = r"(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?"
    suffix = r"\s*%" if percentage else ""
    patterns = [
        re.compile(rf"\b(?:{alias_pattern})\b\s*(?:is|are|of|at|=|:)?\s*{currency}(?P<number>{_NUMBER_TEXT}){suffix}", re.I),
        re.compile(rf"{currency}(?P<number>{_NUMBER_TEXT}){suffix}\s*(?:for|of|as)?\s*\b(?:{alias_pattern})\b", re.I),
    ]
    for pattern in patterns:
        match = pattern.search(query)
        if not match:
            continue
        value = _decimal(match.group("number"))
        if value is None:
            continue
        symbol = match.groupdict().get("symbol")
        code = match.groupdict().get("code")
        return value, (code.upper() if code else _CURRENCY_SYMBOLS.get(symbol or ""))
    return None


def _input(query: str, name: str, *, kind: str = "money", percentage: bool = False) -> CalculationInput | None:
    found = _find_value(query, _ALIASES[name], percentage=percentage)
    if found is None:
        return None
    value, currency = found
    return CalculationInput(
        name=name, value=value, display_value=f"{value:f}", kind=kind,
        currency=currency if kind == "money" else None,
    )


def _currency(inputs: list[CalculationInput]) -> str | None:
    currencies = {item.currency for item in inputs if item.currency}
    return next(iter(currencies)) if len(currencies) == 1 else None


def _money(value: Decimal, currency: str | None) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    symbol = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}.get(currency or "", f"{currency} " if currency else "")
    return f"{symbol}{quantized:,.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}%"


def _ratio(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}:1"


def _same_currency(inputs: list[CalculationInput]) -> bool:
    currencies = {item.currency for item in inputs if item.kind == "money" and item.currency}
    return len(currencies) <= 1


def _success(formulas: list[str], inputs: list[CalculationInput], outputs: list[CalculationOutput], steps: list[str]) -> CalculationResult:
    return CalculationResult(
        matched=True, status="success", formula_ids=formulas, inputs=inputs,
        outputs=outputs, steps=steps, verification_status="passed",
        message="Calculation completed using values supplied directly by the user.",
    )


def _undefined(formula: str, inputs: list[CalculationInput], message: str) -> CalculationResult:
    return CalculationResult(
        matched=True, status="undefined", formula_ids=[formula], inputs=inputs,
        verification_status="passed", error_code="DIVISION_BY_ZERO", message=message,
    )


def _clarify(formula: str, inputs: list[CalculationInput], missing: list[str]) -> CalculationResult:
    readable = ", ".join(name.replace("_", " ") for name in missing)
    return CalculationResult(
        matched=True, status="clarification_required", formula_ids=[formula], inputs=inputs,
        error_code="MISSING_INPUT", message=f"Please provide the following calculation input(s): {readable}.",
    )


def calculate_from_query(query: str) -> CalculationResult:
    """Recognize and execute supported self-contained accounting calculations."""
    q = query or ""
    if not _CALCULATION_HINT.search(q):
        return CalculationResult()

    wants_gross_margin = bool(re.search(r"\bgross (?:profit )?margin\b", q, re.I))
    wants_gross_profit = bool(re.search(r"\bgross profit\b", q, re.I))
    if wants_gross_margin or wants_gross_profit:
        revenue = _input(q, "revenue")
        cost = _input(q, "cost_of_sales")
        supplied_profit = _input(q, "gross_profit")
        inputs = [item for item in (revenue, cost, supplied_profit) if item]
        if not revenue:
            return _clarify("gross_margin" if wants_gross_margin else "gross_profit", inputs, ["revenue"])
        profit = supplied_profit.value if supplied_profit else (revenue.value - cost.value if cost else None)
        if profit is None:
            return _clarify("gross_margin" if wants_gross_margin else "gross_profit", inputs, ["gross_profit or cost_of_sales"])
        if not _same_currency(inputs):
            return CalculationResult(matched=True, status="clarification_required", formula_ids=["gross_margin"], inputs=inputs, error_code="CURRENCY_MISMATCH", message="Revenue, cost and profit must use the same currency.")
        currency = _currency(inputs)
        outputs = [CalculationOutput(name="gross_profit", value=profit, display_value=_money(profit, currency), kind="money")]
        steps = []
        formulas = ["gross_profit"]
        if not supplied_profit:
            steps.append(f"Gross profit = {_money(revenue.value, currency)} − {_money(cost.value, currency)} = {_money(profit, currency)}")
        if wants_gross_margin:
            if revenue.value == 0:
                return _undefined("gross_margin", inputs, "Gross margin is undefined because revenue is zero; division by zero is not permitted.")
            margin = profit / revenue.value * Decimal("100")
            formulas.append("gross_margin")
            outputs.append(CalculationOutput(name="gross_margin", value=margin, display_value=_percent(margin), kind="percentage"))
            steps.append(f"Gross margin = {_money(profit, currency)} ÷ {_money(revenue.value, currency)} × 100 = {_percent(margin)}")
        return _success(formulas, inputs, outputs, steps)

    if re.search(r"\bvat\b", q, re.I) and re.search(r"\b(calculate|compute|gross total|vat amount|reverse vat)\b", q, re.I):
        net = _input(q, "net_amount")
        gross = _input(q, "gross_amount")
        rate = _input(q, "vat_rate", kind="percentage", percentage=True)
        inputs = [item for item in (net, gross, rate) if item]
        if not rate:
            return _clarify("vat", inputs, ["vat_rate"])
        if rate.value < 0:
            return CalculationResult(matched=True, status="clarification_required", formula_ids=["vat"], inputs=inputs, error_code="INVALID_PERCENTAGE", message="VAT rate cannot be negative.")
        if gross and not net:
            divisor = Decimal("1") + rate.value / Decimal("100")
            if divisor == 0:
                return _undefined("reverse_vat", inputs, "Reverse VAT is undefined because the supplied rate creates a zero denominator.")
            net_value = gross.value / divisor
            vat_value = gross.value - net_value
            currency = gross.currency
            return _success(["reverse_vat"], inputs, [
                CalculationOutput(name="net_amount", value=net_value, display_value=_money(net_value, currency), kind="money"),
                CalculationOutput(name="vat_amount", value=vat_value, display_value=_money(vat_value, currency), kind="money"),
            ], [
                f"Net amount = {_money(gross.value, currency)} ÷ (1 + {rate.value:f} ÷ 100) = {_money(net_value, currency)}",
                f"VAT = {_money(gross.value, currency)} − {_money(net_value, currency)} = {_money(vat_value, currency)}",
            ])
        if not net:
            return _clarify("vat", inputs, ["net_amount"])
        vat_value = net.value * rate.value / Decimal("100")
        gross_value = net.value + vat_value
        return _success(["vat"], inputs, [
            CalculationOutput(name="vat_amount", value=vat_value, display_value=_money(vat_value, net.currency), kind="money"),
            CalculationOutput(name="gross_total", value=gross_value, display_value=_money(gross_value, net.currency), kind="money"),
        ], [
            f"VAT = {_money(net.value, net.currency)} × {rate.value:f}% = {_money(vat_value, net.currency)}",
            f"Gross total = {_money(net.value, net.currency)} + {_money(vat_value, net.currency)} = {_money(gross_value, net.currency)}",
        ])

    if re.search(r"\b(current ratio|quick ratio|acid[- ]test ratio)\b", q, re.I):
        assets = _input(q, "current_assets")
        liabilities = _input(q, "current_liabilities")
        inventory = _input(q, "inventory")
        quick = bool(re.search(r"\b(quick|acid[- ]test) ratio\b", q, re.I))
        inputs = [item for item in (assets, liabilities, inventory) if item]
        missing = [name for name, item in (("current_assets", assets), ("current_liabilities", liabilities)) if not item]
        if quick and not inventory:
            missing.append("inventory")
        if missing:
            return _clarify("quick_ratio" if quick else "current_ratio", inputs, missing)
        if liabilities.value == 0:
            return _undefined("quick_ratio" if quick else "current_ratio", inputs, "The ratio is undefined because current liabilities are zero.")
        numerator = assets.value - inventory.value if quick else assets.value
        value = numerator / liabilities.value
        label = "Quick ratio" if quick else "Current ratio"
        return _success(["quick_ratio" if quick else "current_ratio"], inputs, [
            CalculationOutput(name=label.lower().replace(" ", "_"), value=value, display_value=_ratio(value), kind="ratio")
        ], [f"{label} = {numerator:f} ÷ {liabilities.value:f} = {_ratio(value)}"])

    if re.search(r"\bdebt[- ]to[- ]equity\b", q, re.I):
        liabilities = _input(q, "total_liabilities")
        equity = _input(q, "equity")
        inputs = [item for item in (liabilities, equity) if item]
        missing = [name for name, item in (("total_liabilities", liabilities), ("equity", equity)) if not item]
        if missing:
            return _clarify("debt_to_equity", inputs, missing)
        if equity.value == 0:
            return _undefined("debt_to_equity", inputs, "Debt-to-equity is undefined because equity is zero.")
        value = liabilities.value / equity.value
        return _success(["debt_to_equity"], inputs, [CalculationOutput(name="debt_to_equity", value=value, display_value=_ratio(value), kind="ratio")], [f"Debt-to-equity = {liabilities.value:f} ÷ {equity.value:f} = {_ratio(value)}"])

    if re.search(r"\bstraight[- ]line depreciation\b", q, re.I):
        cost = _input(q, "asset_cost")
        residual = _input(q, "residual_value")
        life = _input(q, "useful_life", kind="years")
        inputs = [item for item in (cost, residual, life) if item]
        missing = [name for name, item in (("asset_cost", cost), ("residual_value", residual), ("useful_life", life)) if not item]
        if missing:
            return _clarify("straight_line_depreciation", inputs, missing)
        if life.value <= 0:
            return _undefined("straight_line_depreciation", inputs, "Annual depreciation is undefined because useful life must be greater than zero.")
        annual = (cost.value - residual.value) / life.value
        currency = _currency(inputs)
        return _success(["straight_line_depreciation"], inputs, [CalculationOutput(name="annual_depreciation", value=annual, display_value=_money(annual, currency), kind="money")], [f"Annual depreciation = ({_money(cost.value, currency)} − {_money(residual.value, currency)}) ÷ {life.value:f} = {_money(annual, currency)}"])

    if re.search(r"\bbreak[- ]even\b", q, re.I):
        price = _input(q, "selling_price")
        variable = _input(q, "variable_cost")
        fixed = _input(q, "fixed_costs")
        inputs = [item for item in (price, variable, fixed) if item]
        missing = [name for name, item in (("selling_price", price), ("variable_cost", variable), ("fixed_costs", fixed)) if not item]
        if missing:
            return _clarify("break_even_units", inputs, missing)
        contribution = price.value - variable.value
        if contribution <= 0:
            return _undefined("break_even_units", inputs, "Break-even units are undefined because contribution per unit is zero or negative.")
        units = fixed.value / contribution
        currency = _currency(inputs)
        return _success(["contribution_per_unit", "break_even_units"], inputs, [
            CalculationOutput(name="contribution_per_unit", value=contribution, display_value=_money(contribution, currency), kind="money"),
            CalculationOutput(name="break_even_units", value=units, display_value=f"{units.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units", kind="units"),
        ], [
            f"Contribution per unit = {_money(price.value, currency)} − {_money(variable.value, currency)} = {_money(contribution, currency)}",
            f"Break-even units = {_money(fixed.value, currency)} ÷ {_money(contribution, currency)} = {units.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units",
        ])

    return CalculationResult()


def calculation_markdown(result: CalculationResult) -> str:
    if result.status in {"undefined", "clarification_required"}:
        lines = [result.message]
        if result.formula_ids:
            lines.append(f"\nFormula: `{result.formula_ids[-1].replace('_', ' ')}`")
        return "\n".join(lines)
    lines = ["### Calculation"]
    lines.extend(f"- {step}" for step in result.steps)
    if result.outputs:
        lines.append("\n### Result")
        lines.extend(f"- {item.name.replace('_', ' ').title()}: **{item.display_value}**" for item in result.outputs)
    return "\n".join(lines)
