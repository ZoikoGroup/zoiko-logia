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

# Ends on a digit: "-?\d[\d,]*" also took the comma in "£200,000, cost of
# goods sold of £125,000", so revenue's £200,000 was read as the cost.
_NUMBER_TEXT = r"-?\d(?:[\d,]*\d)?(?:\.\d+)?"
_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR"}
_CURRENCY_CODES = ("GBP", "USD", "EUR", "INR", "AED")
_CALCULATION_HINT = re.compile(
    r"\b(calculate|compute|work out|determine|what is|find)\b", re.I,
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "turnover"),
    # "cost of goods sold is £160,000" was not read, so a question giving it
    # was answered "please provide cost of sales".
    "cost_of_sales": ("cost of goods sold", "cost of goods", "cost of revenue", "cost of sales",
                      "cost_of_sales", "cogs", "cost"),
    "gross_profit": ("gross profit", "gross_profit"),
    "operating_expenses": ("operating expenses", "operating expense", "opex"),
    "expenses": ("expenses", "total expenses"),
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
    # "a $20,000 asset", "machine costing" — the value usually precedes the noun.
    "asset_cost": ("asset cost", "cost of the asset", "asset costs", "asset", "machine", "equipment"),
    "residual_value": ("residual value", "salvage value"),
    "useful_life": ("useful life", "asset life", "year life", "years life", "year useful life"),
    "selling_price": ("selling price", "sale price", "price per unit"),
    "variable_cost": ("variable cost", "variable cost per unit"),
    "fixed_costs": ("fixed costs", "fixed cost"),
    "principal": ("principal", "amount invested", "investment"),
    "interest_rate": ("interest rate", "annual rate", "rate"),
    "years": ("years", "year", "term"),
    "future_value": ("future value",),
}


_CURRENCY_MISMATCH_MESSAGE = (
    "These amounts are in different currencies. Tell me which currency each is in (for example, "
    "whether $ means US, Canadian or Australian dollars) and I can convert them at the latest "
    "dated exchange rate, or give me the rate you want me to use."
)


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _find_value(query: str, aliases: tuple[str, ...], *, percentage: bool = False) -> tuple[Decimal, str | None] | None:
    alias_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    currency = r"(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?"
    suffix = r"\s*%" if percentage else ""
    # A percentage may sit a few plain words after its label: "VAT at a
    # supplied rate of 20%" asked for the VAT rate it had just been given.
    # Words only, so the gap can never step over a different figure.
    gap = r"(?:\s+[a-z]+){0,4}?" if percentage else ""
    patterns = [
        re.compile(rf"\b(?:{alias_pattern})\b{gap}\s*(?:is|are|of|at|=|:)?\s*{currency}(?P<number>{_NUMBER_TEXT}){suffix}", re.I),
        # [\s-]*: a hyphenated "5-year life" or "10-year term" labels its number.
        re.compile(rf"{currency}(?P<number>{_NUMBER_TEXT}){suffix}[\s-]*(?:for|of|as)?\s*\b(?:{alias_pattern})\b", re.I),
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
    # The sign leads the symbol: "-₹20,000.00", not "₹-20,000.00".
    sign = "-" if quantized < 0 else ""
    return f"{sign}{symbol}{abs(quantized):,.2f}"


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


def asks_several_questions(query: str) -> bool:
    """Two or more separate questions that each carry figures ("…ratio? …
    Debt-to-equity? …"). Labels are read across the whole message, so
    "Cost £80" from one question became the depreciable cost in another and
    a negative depreciation was shown as a Verified calculation. Such
    messages go to the model, whose every arithmetic line is re-checked by
    validate_answer_calculations. One calculation plus a lookup question
    ("18% GST on ₹50,000? Also, the UK VAT rate?") is unaffected."""
    segments = [segment for segment in (query or "").split("?") if segment.strip()]
    return sum(1 for segment in segments if re.search(r"\d", segment)) >= 2



def expense_scenario(query: str):
    """An explicitly revised expense amount, regardless of the lead-in wording."""
    return re.search(
        r"\b(?:expenses\s+(?:increase|rise|decrease|fall|change)(?:s|d)?\s+to|"
        r"(?:change|set|increase|reduce)\s+(?:(?:the|my|those)\s+)?expenses\s+to)\s*"
        r"(?P<symbol>[₹£$€])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?"
        r"(?P<amount>\d[\d,]*(?:\.\d+)?)", query or "", re.I,
    )


_COST_SHARE = re.compile(
    r"\b(?:cogs|cost of (?:goods sold|sales|revenue))\b[^.?]{0,40}\b(?:percentage|per cent|percent|%)\s+of\s+(?:revenue|sales)\b"
    r"|\b(?:percentage|%)\s+of\s+(?:revenue|sales)\b",
    re.I,
)
_RECONCILE_HINT = re.compile(
    r"\b(?:reconcil\w*|check|verify|consistent|inconsisten\w*|agree|add up|correct|accurate|discrepanc\w*|calculate|compute)\b",
    re.I,
)


def reconcile_reported_figures(query: str) -> CalculationResult | None:
    """Revenue, cost of sales and a reported gross profit that may disagree.

    "Revenue £500,000, cost of goods sold £320,000, gross profit £190,000"
    was either not calculated (no "calculate" in "check whether the figures
    reconcile") or calculated with the reported £190,000 taken as given. The
    reported figure is kept, the figure its inputs imply is shown beside it,
    and the difference is named — never silently overwritten."""
    q = query or ""
    revenue, cost, reported = _input(q, "revenue"), _input(q, "cost_of_sales"), _input(q, "gross_profit")
    if not (revenue and cost and reported) or not _RECONCILE_HINT.search(q):
        return None
    opex = _input(q, "operating_expenses")
    reported_operating = _input(q, "operating_profit")
    inputs = [item for item in (revenue, cost, reported, opex, reported_operating) if item]
    if not _same_currency(inputs):
        return CalculationResult(matched=True, status="clarification_required", inputs=inputs,
                                 error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
    c = _currency(inputs)
    calculated = revenue.value - cost.value
    difference = reported.value - calculated
    agrees = difference == 0
    outputs = [
        CalculationOutput(name="reported_gross_profit", value=reported.value, display_value=_money(reported.value, c), kind="money"),
        CalculationOutput(name="calculated_gross_profit", value=calculated, display_value=_money(calculated, c), kind="money"),
        CalculationOutput(name="difference_reported_minus_calculated", value=difference, display_value=_money(difference, c), kind="money"),
    ]
    steps = [
        f"Calculated gross profit = revenue {_money(revenue.value, c)} − cost of sales {_money(cost.value, c)} = {_money(calculated, c)}",
        f"Difference = reported {_money(reported.value, c)} − calculated {_money(calculated, c)} = {_money(difference, c)}",
    ]
    formulas = ["gross_profit", "gross_profit_reconciliation"]
    if revenue.value != 0:
        for name, profit in (("calculated", calculated), ("reported", reported.value)):
            margin = profit / revenue.value * Decimal("100")
            outputs.append(CalculationOutput(name=f"gross_margin_{name}", value=margin, display_value=_percent(margin), kind="percentage"))
        steps.append(f"Gross margin on the calculated figure = {_money(calculated, c)} ÷ {_money(revenue.value, c)} × 100 = {_percent(calculated / revenue.value * 100)}")
    if opex:
        formulas.append("operating_profit")
        operating = calculated - opex.value
        outputs.append(CalculationOutput(name="operating_profit_on_calculated_gross_profit", value=operating, display_value=_money(operating, c), kind="money"))
        steps.append(f"Operating profit = calculated gross profit {_money(calculated, c)} − operating expenses {_money(opex.value, c)} = {_money(operating, c)}")
        if not agrees:
            on_reported = reported.value - opex.value
            outputs.append(CalculationOutput(name="operating_profit_on_reported_gross_profit", value=on_reported, display_value=_money(on_reported, c), kind="money"))
            steps.append(f"Operating profit if the reported gross profit were used = {_money(reported.value, c)} − {_money(opex.value, c)} = {_money(on_reported, c)}")
        if reported_operating and reported_operating.value != operating:
            gap = reported_operating.value - operating
            outputs.append(CalculationOutput(name="reported_operating_profit", value=reported_operating.value, display_value=_money(reported_operating.value, c), kind="money"))
            steps.append(f"Reported operating profit {_money(reported_operating.value, c)} differs from the calculated {_money(operating, c)} by {_money(gap, c)}")
    operating = calculated - opex.value if opex else None
    operating_gap = (reported_operating.value - operating
                     if reported_operating is not None and operating is not None else Decimal("0"))
    problems = []
    if not agrees:
        direction = "higher" if difference > 0 else "lower"
        problems.append(f"Inconsistency: the reported gross profit ({_money(reported.value, c)}) is "
                        f"{_money(abs(difference), c)} {direction} than revenue less cost of sales "
                        f"({_money(calculated, c)}). The reported figure has not been changed.")
    if operating_gap != 0:
        direction = "higher" if operating_gap > 0 else "lower"
        problems.append(f"Inconsistency: the reported operating profit ({_money(reported_operating.value, c)}) is "
                        f"{_money(abs(operating_gap), c)} {direction} than gross profit less operating expenses "
                        f"({_money(operating, c)}). The reported figure has not been changed.")
    if not problems:
        notes = [f"The reported gross profit of {_money(reported.value, c)} agrees with revenue less cost of sales"
                 + (" and the reported operating profit agrees with gross profit less operating expenses."
                    if reported_operating is not None else ".")]
    else:
        notes = problems + [
            "What arithmetic settles: given these revenue, cost of sales"
            + (" and operating expenses" if opex else "") + " figures, gross profit must be "
            f"{_money(calculated, c)}" + (f" and operating profit {_money(operating, c)}" if opex else "") + ".",
            "What the accountant must confirm: which figure is wrong — an input (revenue, cost of sales, operating "
            "expenses) or the reported subtotal — for example a transposition or typing error, a cost classified "
            "outside cost of sales, an adjustment or reclassification not reflected in one of the figures, or "
            "figures taken from different periods or versions of the accounts.",
        ]
    agrees = not problems
    result = _success(formulas, inputs, outputs, steps)
    result.notes = notes
    result.message = ("Reported figures reconcile." if agrees else
                      "Reported figures do not reconcile; the reported values are shown unchanged beside the calculated ones.")
    return result


_CHANGE = re.compile(
    r"\b(?P<item>revenue|sales|turnover|cogs|cost of (?:goods sold|sales)|costs?)\b[^.?\d]{0,30}?"
    r"\b(?P<direction>increase[sd]?|rises?|rose|grows?|grew|goes up|falls?|fell|decrease[sd]?|drops?|dropped|declines?|goes down)"
    r"\s+(?:by\s+)?(?P<pct>\d+(?:\.\d+)?)\s*%"
    r"|(?P<pct2>\d+(?:\.\d+)?)\s*%\s+(?P<direction2>increase|rise|growth|fall|decrease|drop|decline)\s+in\s+"
    r"(?P<item2>revenue|sales|turnover|cogs|cost of (?:goods sold|sales)|costs?)\b",
    re.I,
)


def change_followup(query: str, history) -> CalculationResult | None:
    """"What happens if revenue increases by 15%?" after "Revenue is £250,000
    and COGS is £160,000": the follow-up carries no figures, so neither
    calculation path computed anything. The base figures come from the most
    recent earlier user message that states them; only the item the user
    changed is changed, and every carried figure is marked as such."""
    q = query or ""
    change = _CHANGE.search(q)
    if not change or _input(q, "revenue") or _input(q, "cost_of_sales"):
        return None
    item = (change.group("item") or change.group("item2")).lower()
    word = (change.group("direction") or change.group("direction2")).lower()
    pct = _decimal(change.group("pct") or change.group("pct2"))
    sign = Decimal("-1") if re.match(r"fall|fell|decreas|drop|declin|goes down", word) else Decimal("1")
    revenue = cost = None
    for message in reversed(list(history or [])):
        if getattr(message, "role", "user") != "user":
            continue
        content = getattr(message, "content", str(message))
        revenue, cost = _input(content, "revenue"), _input(content, "cost_of_sales")
        if revenue and cost:
            break
        revenue = cost = None
    if not (revenue and cost) or pct is None:
        return None
    for each in (revenue, cost):
        each.source_location = "earlier message"
    if not _same_currency([revenue, cost]):
        return CalculationResult(matched=True, status="clarification_required", inputs=[revenue, cost],
                                 error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
    c = _currency([revenue, cost])
    factor = Decimal("1") + sign * pct / Decimal("100")
    changes_revenue = item in ("revenue", "sales", "turnover")
    new_revenue = revenue.value * factor if changes_revenue else revenue.value
    new_cost = cost.value if changes_revenue else cost.value * factor
    base_profit, new_profit = revenue.value - cost.value, new_revenue - new_cost
    label = "Revenue" if changes_revenue else "Cost of sales"
    steps = [
        f"{label} = {_money(revenue.value if changes_revenue else cost.value, c)} × "
        f"{'(1 + ' if sign > 0 else '(1 − '}{pct:f}%) = {_money(new_revenue if changes_revenue else new_cost, c)}",
        f"Gross profit = {_money(new_revenue, c)} − {_money(new_cost, c)} = {_money(new_profit, c)} (was {_money(base_profit, c)})",
    ]
    outputs = [
        CalculationOutput(name="revenue", value=new_revenue, display_value=_money(new_revenue, c), kind="money"),
        CalculationOutput(name="cost_of_sales", value=new_cost, display_value=_money(new_cost, c), kind="money"),
        CalculationOutput(name="gross_profit", value=new_profit, display_value=_money(new_profit, c), kind="money"),
        CalculationOutput(name="gross_profit_change", value=new_profit - base_profit, display_value=_money(new_profit - base_profit, c), kind="money"),
    ]
    if new_revenue != 0 and revenue.value != 0:
        margin, base_margin = new_profit / new_revenue * 100, base_profit / revenue.value * 100
        outputs.append(CalculationOutput(name="gross_margin", value=margin, display_value=_percent(margin), kind="percentage"))
        steps.append(f"Gross margin = {_money(new_profit, c)} ÷ {_money(new_revenue, c)} × 100 = {_percent(margin)} (was {_percent(base_margin)})")
    unchanged = "cost of sales" if changes_revenue else "revenue"
    unchanged_value = cost.value if changes_revenue else revenue.value
    result = _success(["scenario_change", "gross_profit", "gross_margin"], [revenue, cost], outputs, steps)
    result.notes = [
        f"Revenue {_money(revenue.value, c)} and cost of sales {_money(cost.value, c)} are taken from your earlier message.",
        f"{unchanged[0].upper() + unchanged[1:]} is kept at {_money(unchanged_value, c)} because your question changes only "
        f"{label.lower()}; say so if it should change too.",
    ]
    return result


_VAT_WORD = re.compile(r"\b(?:vat|gst)\b", re.I)
_INCLUSIVE = re.compile(r"\b(?:incl(?:ud(?:e|es|ed|ing)|usive|\.)?|gross of|after (?:vat|gst)|vat[- ]inclusive|inc[- ]vat)\b", re.I)
_EXCLUSIVE = re.compile(r"\b(?:excl(?:ud(?:e|es|ed|ing)|usive|\.)?|net of|plus (?:vat|gst)|before (?:vat|gst)|vat[- ]exclusive|ex[- ]vat)\b", re.I)


def item_rate(query: str, aliases: tuple[str, ...]) -> Decimal | None:
    """The rate written right after an item's amount: "purchases £48,000 at 5%"."""
    names = "|".join(re.escape(alias) for alias in aliases)
    match = re.search(rf"\b(?:{names})\b[^.%\d]{{0,20}}[£$€₹]?\s*{_NUMBER_TEXT}[^.%\d]{{0,25}}?(?:at|@)\s*(\d+(?:\.\d+)?)\s*%",
                      query or "", re.I)
    return _decimal(match.group(1)) if match else None


def vat_amounts(query: str) -> CalculationResult | None:
    """VAT once the country, one rate and the VAT treatment are all stated
    (input_requirements.missing_vat_inputs asks for whichever is missing).
    Output VAT on sales less input VAT on purchases, or the VAT in or on one
    amount. Several rates are left to the model, whose arithmetic is checked."""
    q = query or ""
    if not _VAT_WORD.search(q):
        return None
    rates = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", q)
    inclusive, exclusive = bool(_INCLUSIVE.search(q)), bool(_EXCLUSIVE.search(q))
    if not rates or inclusive == exclusive:
        return None
    sales = _find_value(q, ("sales", "turnover", "outputs"))
    purchases = _find_value(q, ("purchases", "purchase", "inputs"))
    # "Sales £120,000 at 20% and purchases £48,000 at 5%": each item's own rate.
    sales_rate, purchases_rate = item_rate(q, ("sales", "turnover", "outputs")), item_rate(q, ("purchases", "purchase", "inputs"))
    if sales and purchases and sales_rate is not None and purchases_rate is not None:
        rate_out, rate_in = sales_rate, purchases_rate
    elif len(set(rates)) == 1:
        rate_out = rate_in = _decimal(rates[0])
    else:
        return None
    if any(r is None or not 0 <= r <= 100 for r in (rate_out, rate_in)):
        return None
    rate = rate_out
    single = None if sales else _find_value(q, ("vat on", "gst on", "vat of", "gst of", "vat in", "on", "in"))
    if not (sales and purchases) and not single:
        return None
    currency = next((found[1] for found in (sales, purchases, single) if found and found[1]), None)

    def share(amount, r):
        return amount * r / (100 + r) if inclusive else amount * r / 100

    def formula(r):
        return f"× {r:f} ÷ (100 + {r:f})" if inclusive else f"× {r:f} ÷ 100"

    treatment = "including" if inclusive else "excluding"
    rates_text = (f"a single rate of {rate_out:f}%" if rate_out == rate_in
                  else f"{rate_out:f}% on sales and {rate_in:f}% on purchases")
    notes = [f"The amounts are taken as {treatment} VAT, as stated, at {rates_text}."]
    if sales and purchases:
        output, input_vat = share(sales[0], rate_out), share(purchases[0], rate_in)
        payable = output - input_vat
        outputs = [
            CalculationOutput(name="output_vat_on_sales", value=output, display_value=_money(output, currency), kind="money"),
            CalculationOutput(name="input_vat_on_purchases", value=input_vat, display_value=_money(input_vat, currency), kind="money"),
            CalculationOutput(name="vat_payable" if payable >= 0 else "vat_repayable", value=abs(payable),
                              display_value=_money(abs(payable), currency), kind="money"),
        ]
        steps = [f"Output VAT = {_money(sales[0], currency)} {formula(rate_out)} = {_money(output, currency)}",
                 f"Input VAT = {_money(purchases[0], currency)} {formula(rate_in)} = {_money(input_vat, currency)}",
                 f"VAT {'payable' if payable >= 0 else 'repayable'} = {_money(output, currency)} − {_money(input_vat, currency)} = {_money(abs(payable), currency)}"]
        notes.append("Input VAT is recoverable only on business purchases supported by valid VAT invoices, and not on "
                     "blocked items or costs that relate to exempt supplies; confirm this before relying on the figure.")
        return _success_with_notes(["vat_liability"], outputs, steps, notes)
    amount = single[0]
    vat = share(amount, rate)
    other = amount - vat if inclusive else amount + vat
    outputs = [CalculationOutput(name="vat_amount", value=vat, display_value=_money(vat, currency), kind="money"),
               CalculationOutput(name="amount_excluding_vat" if inclusive else "total_including_vat", value=other,
                                 display_value=_money(other, currency), kind="money")]
    steps = [f"VAT = {_money(amount, currency)} {formula(rate)} = {_money(vat, currency)}",
             (f"Amount excluding VAT = {_money(amount, currency)} − {_money(vat, currency)} = {_money(other, currency)}" if inclusive
              else f"Total including VAT = {_money(amount, currency)} + {_money(vat, currency)} = {_money(other, currency)}")]
    return _success_with_notes(["vat_from_inclusive" if inclusive else "vat_on_net"], outputs, steps, notes)


def _success_with_notes(formulas, outputs, steps, notes) -> CalculationResult:
    result = _success(formulas, [], outputs, steps)
    result.notes = notes
    return result


_PERCENT_OF = re.compile(
    r"(?<![\d.])(?P<pct>\d+(?:\.\d+)?)\s*%\s+of\s+(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?"
    r"(?P<amount>\d(?:[\d,]*\d)?(?:\.\d+)?)", re.I)


def percent_of_amount(query: str) -> CalculationResult | None:
    """"What's 18% of £3,400?" — plain arithmetic. With no formula for it the
    question reached the agent, which searched the web for a source and
    answered "the sources found do not establish the answer". Only a message
    holding exactly one "X% of amount" and no other figures is handled here."""
    q = query or ""
    matches = list(_PERCENT_OF.finditer(q))
    if len(matches) != 1 or re.search(r"\b(?:vat|gst|tax|interest|growth|compound|discount|margin)\b", q, re.I):
        return None
    match = matches[0]
    others = re.sub(r"\s+", " ", (q[:match.start()] + " " + q[match.end():]))
    if re.search(r"\d", others):
        return None
    pct, amount = _decimal(match.group("pct")), _decimal(match.group("amount"))
    if pct is None or amount is None:
        return None
    currency = (match.group("code") or "").upper() or _CURRENCY_SYMBOLS.get(match.group("symbol") or "")
    value = amount * pct / Decimal("100")
    shown = _money(value, currency) if currency else f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,f}"
    base = _money(amount, currency) if currency else f"{amount:,f}"
    return _success(["percentage_of_amount"], [], [
        CalculationOutput(name="result", value=value, display_value=shown, kind="money" if currency else "number"),
    ], [f"{pct:f}% of {base} = {base} × {pct:f} ÷ 100 = {shown}"])


def calculate_from_query(query: str) -> CalculationResult:
    """Recognize and execute supported self-contained accounting calculations."""
    q = query or ""
    from app.orchestration.websearch import is_pasted_material
    if is_pasted_material(q) and not _CALCULATION_HINT.search(q[:400] + "\n" + q[-400:]):
        # A pasted document's own words ("gross profit $919,000") are not a
        # request: "summarise this in 5 points" was answered with a one-row
        # calculation table (qry-efc27f52ae1c). Only the user's instruction,
        # before or after the material, can ask for a calculation.
        return CalculationResult()
    from app.orchestration.calculations.batches import calculate_numbered_batch, has_numbered_questions
    batch = calculate_numbered_batch(q)
    if batch is not None:
        return batch
    if has_numbered_questions(q):
        # An unsupported batch must never become one calculation using labels
        # borrowed from different questions.
        return CalculationResult()
    # The combined GST rate supplied by the user is an immutable input.
    # Do not search for a different statutory percentage for this calculation.
    if (re.search(r'\bcgst\b', q, re.I) and re.search(r'\bsgst\b', q, re.I)
            and re.search(r'\bintra[-‑ ]state\b', q, re.I)):
        amounts = list(re.finditer(r'₹\s*(-?\d[\d,]*(?:\.\d+)?)', q))
        amount = amounts[0] if len(amounts) == 1 else None
        rates = re.findall(r'(-?\d+(?:\.\d+)?)\s*%', q)
        if amount and len(rates) == 1 and not re.search(r'\beach\b|per component', q, re.I):
            value, rate = _decimal(amount.group(1)), _decimal(rates[0])
            if value < 0 or not 0 <= rate <= 100:
                return CalculationResult(matched=True, status='clarification_required', error_code='INVALID_PERCENTAGE', message='Supply a non-negative taxable value and a GST rate between zero and one hundred percent.')
            half = rate / 2
            tax = value * half / 100
            return _success(['cgst_sgst_split'], [], [
                CalculationOutput(name=name, value=number, display_value=_money(number, 'INR'), kind='money')
                for name, number in [('cgst', tax), ('sgst', tax), ('total_gst', tax*2)]
            ], [f'CGST = {value:f} × {half:f} ÷ 100 = {tax:f}',
                f'SGST = {value:f} × {half:f} ÷ 100 = {tax:f}'])
    # Tax inside a tax-inclusive price: "£1,200 includes 20% UK VAT" is
    # 1,200 × 20 ÷ 120 = £200, not 20% of £1,200. Answered through web search,
    # the agent and the fact-check it took 49 s here and timed out (504) for
    # the user; it is arithmetic on the user's own figures.
    inclusive = re.search(
        r'([₹£$€])\s*(\d[\d,]*(?:\.\d+)?)\b[^.?!]*?\b(?:includ(?:es|ing|ed)|inclusive\s+of|incl\.?)\s+'
        r'(\d+(?:\.\d+)?)\s*%\s*(?:\w+\s+){0,2}?(vat|gst)\b', q, re.I)
    if inclusive and len(re.findall(r'[₹£$€]\s*\d', q)) == 1 and len(re.findall(r'\d+(?:\.\d+)?\s*%', q)) == 1:
        symbol, amount, rate, tax_name = inclusive.groups()
        gross, rate = _decimal(amount), _decimal(rate)
        if gross >= 0 and 0 < rate <= 100:
            currency = {'₹': 'INR', '£': 'GBP', '$': 'USD', '€': 'EUR'}[symbol]
            tax = gross * rate / (100 + rate)
            net = gross - tax
            label = tax_name.upper()
            return _success([f'{tax_name.lower()}_from_inclusive_price'], [], [
                CalculationOutput(name=f'{label} included', value=tax, display_value=_money(tax, currency), kind='money'),
                CalculationOutput(name='Price before ' + label, value=net, display_value=_money(net, currency), kind='money'),
            ], [f'{label} = {gross:f} × {rate:f} ÷ (100 + {rate:f}) = {tax:f}',
                f'Price before {label} = {gross:f} − {tax:f} = {net:f}'])
    reconciled = reconcile_reported_figures(q)
    if reconciled is not None:
        return reconciled
    vat = vat_amounts(q)
    if vat is not None:
        return vat
    share = percent_of_amount(q)
    if share is not None:
        return share

    # Several questions in one message: labels would be read across all of
    # them (one question's "cost" used in another's formula). Not matched,
    # so the model answers each and every arithmetic line is re-checked.
    subscription_request = bool(re.search(r"\b(?:subscription|plan)\b", q, re.I) and re.search(r"\b(?:monthly|per month)\b", q, re.I) and re.search(r"\b(?:annually|annual|per year)\b", q, re.I))
    if (not _CALCULATION_HINT.search(q) and not subscription_request) or asks_several_questions(q):
        return CalculationResult()

    # Subscription break-even is a time comparison, not contribution per unit.
    if re.search(r"\bsubscriptions?\b", q, re.I) or subscription_request:
        monthly = re.search(r"[₹£$€]?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:monthly|per month)", q, re.I)
        annual = re.search(r"[₹£$€]?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:annually|per year)", q, re.I)
        if monthly and annual:
            m, a = _decimal(monthly.group(1)), _decimal(annual.group(1))
            symbols = set(re.findall(r"[₹£$€]", q))
            if len(symbols) > 1 or m <= 0 or a < 0:
                return CalculationResult()
            currency = _CURRENCY_SYMBOLS.get(next(iter(symbols), ""))
            number_words = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
            period = re.search(r"\b(?:for|over)\s+(\d+|" + "|".join(number_words) + r")\s*(?:[- ]month(?:s)?|month(?:s)?)\b", q, re.I)
            if period:
                months = Decimal(number_words[period.group(1).lower()]) if period.group(1).lower() in number_words else Decimal(period.group(1))
                if months <= 0 or months > 1200:
                    return CalculationResult(matched=True, status="clarification_required", error_code="INVALID_PERIOD", message="Please provide a comparison period between 1 and 1200 months.")
                # Annual commitments are paid in whole years; no invented prorating.
                years = (months / 12).to_integral_value(rounding="ROUND_CEILING")
                monthly_cost, annual_cost = m*months, a*years
                return _success(["subscription_period"], [], [
                    CalculationOutput(name="comparison_months",value=months,display_value=f"{months:f} months"),
                    CalculationOutput(name="monthly_plan_cost",value=monthly_cost,display_value=_money(monthly_cost,currency),kind="money"),
                    CalculationOutput(name="annual_plan_commitment_cost",value=annual_cost,display_value=_money(annual_cost,currency),kind="money"),
                    CalculationOutput(name="annual_plan_savings",value=monthly_cost-annual_cost,display_value=_money(monthly_cost-annual_cost,currency),kind="money"),
                ], [f"Monthly plan = {m:f} × {months:f} = {monthly_cost:f}", f"Annual plan requires {years:f} whole annual payment(s); no cancellation refund or prorating assumed."])
            return _success(["subscription_comparison"], [], [
                CalculationOutput(name="monthly_plan_annual_cost", value=m*12, display_value=_money(m*12, currency), kind="money"),
                CalculationOutput(name="annual_plan_cost", value=a, display_value=_money(a, currency), kind="money"),
                CalculationOutput(name="annual_savings", value=m*12-a, display_value=_money(m*12-a, currency), kind="money"),
                CalculationOutput(name="break_even_months", value=a/m, display_value=f"{a/m:f} months"),
            ], [f"Annual monthly-plan cost = {m:f} × 12 = {m*12:f}", f"Savings = {m*12:f} − {a:f} = {m*12-a:f}", f"Equal cost at {a:f} ÷ {m:f} = {a/m:f} months"])
        # Do not ask for manufacturing inputs for an unrelated comparison.
        return CalculationResult()

    # A multi-part income statement must not stop at the first formula.
    if re.search(r"\boperating profit\b|profit[- ]and[- ]loss", q, re.I):
        revenue, cost, opex = _input(q, "revenue"), _input(q, "cost_of_sales"), _input(q, "operating_expenses")
        if revenue and cost and opex:
            inputs = [revenue, cost, opex]
            if not _same_currency(inputs):
                return CalculationResult(matched=True, status="clarification_required", error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
            c = _currency(inputs)
            gross = revenue.value-cost.value
            operating = gross-opex.value
            outputs = [CalculationOutput(name=name, value=value, display_value=_money(value,c), kind="money") for name,value in (("revenue",revenue.value),("cost_of_sales",cost.value),("gross_profit",gross),("operating_expenses",opex.value),("operating_profit",operating))]
            if re.search(r"\bmargins?\b", q, re.I):
                if revenue.value == 0:
                    outputs += [CalculationOutput(name=name, display_value="Undefined: revenue is zero", kind="percentage") for name in ("gross_margin","operating_margin")]
                else:
                    outputs += [CalculationOutput(name=name,value=value/revenue.value*100,display_value=_percent(value/revenue.value*100),kind="percentage") for name,value in (("gross_margin",gross),("operating_margin",operating))]
            return _success(["income_statement"], inputs, outputs, [f"Gross profit = {_money(revenue.value,c)} − {_money(cost.value,c)} = {_money(gross,c)}", f"Operating profit = {_money(gross,c)} − {_money(opex.value,c)} = {_money(operating,c)}"])

    # Both scenarios are calculated separately, rather than dropping the second.
    scenario = expense_scenario(q)
    if scenario and (revenue := _input(q, "revenue")) and (expenses := _input(q, "expenses")):
        revised_currency = (scenario.group("code") or _CURRENCY_SYMBOLS.get(scenario.group("symbol") or ""))
        currencies = {item.currency for item in (revenue, expenses) if item.currency}
        if revised_currency:
            currencies.add(revised_currency.upper())
        if len(currencies) > 1:
            return CalculationResult(matched=True, status="clarification_required", error_code="CURRENCY_MISMATCH", message="Revenue and both expense scenarios must use the same currency. Please supply converted amounts and the conversion rate before comparing them.")
        c = next(iter(currencies), None)
        outputs = []
        for prefix, amount in (("original",expenses.value),("revised",_decimal(scenario.group("amount")))):
            profit = revenue.value-amount
            outputs.append(CalculationOutput(name=prefix+"_profit",value=profit,display_value=_money(profit,c),kind="money"))
            outputs.append(CalculationOutput(name=prefix+"_profit_margin",value=profit/revenue.value*100 if revenue.value else None,display_value=_percent(profit/revenue.value*100) if revenue.value else "Undefined: revenue is zero",kind="percentage"))
        return _success(["profit_scenarios"], [revenue,expenses], outputs, [])

    # Explicit supplied rates need arithmetic, not tax-source retrieval.
    rate_pattern = r"(?<![\d.])([+\-−]?\s*\d+(?:\.\d+)?)\s*%"
    rate_matches = list(re.finditer(rate_pattern, q))
    amount_matches = list(re.finditer(r"\b(?:tax on|tax of|and on)\s*([₹£$€])?\s*(\d[\d,]*(?:\.\d+)?)", q, re.I))
    if rate_matches and amount_matches and not re.search(r"\b(?:official|statutory|current|latest|threshold|registration)\b", q, re.I):
        tax_rates, discounts = [], []
        for match in rate_matches:
            value = _decimal(re.sub(r"\s+", "", match.group(1)).replace("−", "-"))
            before, after = q[max(0,match.start()-45):match.start()], q[match.end():match.end()+30]
            labelled_discount = re.search(r"discount(?:\s+(?:rate|of|at|is|a))*\s*$", before, re.I) or re.match(r"\s*(?:discount|off)\b", after, re.I)
            unrelated = re.search(r"(?:profit margin|margin|interest|commission|markup)(?:\s+(?:rate|of|at|is))*\s*$", before, re.I) or re.match(r"\s*(?:profit margin|margin|interest|commission|markup)\b", after, re.I)
            if labelled_discount:
                discounts.append(value)
            elif not unrelated:
                tax_rates.append((match,value))
        if not tax_rates:
            return CalculationResult()
        if any(value < 0 for _,value in tax_rates) or any(value < 0 or value > 100 for value in discounts):
            return CalculationResult(matched=True,status="clarification_required",error_code="INVALID_PERCENTAGE",message="Tax rates cannot be negative; discounts must be between 0% and 100%. Please confirm the intended rates.")
        if len(discounts)>1 or (discounts and len(amount_matches)>1):
            return CalculationResult(matched=True,status="clarification_required",error_code="AMBIGUOUS_INPUTS",message="Please specify the discount and tax rate for each amount.")
        pairs = []
        if len(amount_matches) == 1:
            pairs = [(amount_matches[0],value) for _,value in tax_rates]
        else:
            # Each stated amount gets only the rate in its own clause.
            for index,amount_match in enumerate(amount_matches):
                stop = amount_matches[index+1].start() if index+1<len(amount_matches) else len(q)
                rates = [value for match,value in tax_rates if amount_match.end() <= match.start() < stop]
                if len(rates)!=1:
                    return CalculationResult(matched=True,status="clarification_required",error_code="AMBIGUOUS_INPUTS",message="Please specify which tax rate applies to each amount.")
                pairs.append((amount_match,rates[0]))
            if len(pairs)!=len(tax_rates):
                return CalculationResult()
        outputs, steps = [], []
        for index,(amount_match,rate) in enumerate(pairs):
            amount = _decimal(amount_match.group(2))
            currency = _CURRENCY_SYMBOLS.get(amount_match.group(1) or "")
            prefix = f"scenario_{index+1}_" if len(pairs)>1 else ""
            if discounts:
                original = amount
                amount *= 1-discounts[0]/100
                outputs.append(CalculationOutput(name="discounted_amount",value=amount,display_value=_money(amount,currency),kind="money"))
                steps.append(f"Discounted amount = {original:f} × (1 − {discounts[0]:f} ÷ 100) = {amount:f}")
            tax = amount*rate/100
            if len(pairs)>1:
                outputs.append(CalculationOutput(name=prefix+"tax_rate",value=rate,display_value=_percent(rate),kind="percentage"))
            outputs.extend([
                CalculationOutput(name=prefix+"tax",value=tax,display_value=_money(tax,currency),kind="money"),
                CalculationOutput(name=prefix+"total_including_tax",value=amount+tax,display_value=_money(amount+tax,currency),kind="money"),
            ])
            steps.append(f"Tax at {rate:f}% = {amount:f} × {rate:f} ÷ 100 = {tax:f}")
        return _success(["supplied_tax"], [], outputs, steps)

    wants_gross_margin = bool(re.search(r"\bgross (?:profit )?margin\b", q, re.I))
    wants_gross_profit = bool(re.search(r"\bgross profit\b", q, re.I))
    if wants_gross_margin or wants_gross_profit:
        revenue = _input(q, "revenue")
        cost = _input(q, "cost_of_sales")
        supplied_profit = _input(q, "gross_profit")
        inputs = [item for item in (revenue, cost, supplied_profit) if item]
        if not revenue and (
            re.search(r"\bfrom\b[^.?]*\d[^.?]*\bto\b[^.?]*\d", q, re.I)
            or re.search(r"\bmargin\b[^.?]*\d+(?:\.\d+)?\s*%", q, re.I)
        ):
            # The figures are there in a shape this extractor does not read:
            # "revenue grew from £2.4m to £2.9m but gross margin fell from 38%
            # to 33%" was answered "please provide revenue". The model answers
            # it instead, and every arithmetic line is still re-checked.
            return CalculationResult()
        if not revenue:
            return _clarify("gross_margin" if wants_gross_margin else "gross_profit", inputs, ["revenue"])
        profit = supplied_profit.value if supplied_profit else (revenue.value - cost.value if cost else None)
        if profit is None:
            return _clarify("gross_margin" if wants_gross_margin else "gross_profit", inputs, ["gross_profit or cost_of_sales"])
        if not _same_currency(inputs):
            return CalculationResult(matched=True, status="clarification_required", formula_ids=["gross_margin"], inputs=inputs, error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
        currency = _currency(inputs)
        outputs = [CalculationOutput(name="gross_profit", value=profit, display_value=_money(profit, currency), kind="money")]
        steps = []
        formulas = ["gross_profit"]
        if not supplied_profit:
            steps.append(f"Gross profit = {_money(revenue.value, currency)} − {_money(cost.value, currency)} = {_money(profit, currency)}")
        elif not cost and re.search(r"\b(?:cost of sales|cost of goods sold|cogs)\b", q, re.I):
            # "Revenue £180,000, gross profit £72,000. What is the cost of
            # sales and gross margin?" was answered with the margin only.
            cost_of_sales = revenue.value - profit
            formulas.append("cost_of_sales")
            outputs.append(CalculationOutput(name="cost_of_sales", value=cost_of_sales, display_value=_money(cost_of_sales, currency), kind="money"))
            steps.append(f"Cost of sales = {_money(revenue.value, currency)} − {_money(profit, currency)} = {_money(cost_of_sales, currency)}")
        if wants_gross_margin:
            if revenue.value == 0:
                return _undefined("gross_margin", inputs, "Gross margin is undefined because revenue is zero; division by zero is not permitted.")
            margin = profit / revenue.value * Decimal("100")
            formulas.append("gross_margin")
            outputs.append(CalculationOutput(name="gross_margin", value=margin, display_value=_percent(margin), kind="percentage"))
            steps.append(f"Gross margin = {_money(profit, currency)} ÷ {_money(revenue.value, currency)} × 100 = {_percent(margin)}")
        if cost and revenue.value != 0 and _COST_SHARE.search(q):
            share = cost.value / revenue.value * Decimal("100")
            formulas.append("cost_of_sales_percentage")
            outputs.append(CalculationOutput(name="cost_of_sales_as_percentage_of_revenue", value=share,
                                             display_value=_percent(share), kind="percentage"))
            steps.append(f"Cost of sales as % of revenue = {_money(cost.value, currency)} ÷ {_money(revenue.value, currency)} × 100 = {_percent(share)}")
        return _success(formulas, inputs, outputs, steps)

    if re.search(r"\bprofit\b", q, re.I) and not re.search(r"\b(?:tax|gst|vat|registration)\b", q, re.I):
        revenue, expenses = _input(q, "revenue"), _input(q, "expenses")
        if revenue and expenses:
            inputs = [revenue, expenses]
            if not _same_currency(inputs):
                return CalculationResult(matched=True, status="clarification_required", inputs=inputs,
                    error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
            profit = revenue.value - expenses.value
            currency = _currency(inputs)
            outputs = [CalculationOutput(name="profit", value=profit, display_value=_money(profit, currency), kind="money")]
            steps = [f"Profit = {_money(revenue.value, currency)} − {_money(expenses.value, currency)} = {_money(profit, currency)}"]
            formulas = ["profit"]
            if re.search(r"\bmargin\b", q, re.I):
                if revenue.value == 0:
                    return _undefined("profit_margin", inputs, "Profit margin is undefined when revenue is zero.")
                margin = profit / revenue.value * Decimal("100")
                outputs.append(CalculationOutput(name="profit_margin", value=margin, display_value=_percent(margin), kind="percentage"))
                steps.append(f"Profit margin = {_money(profit, currency)} ÷ {_money(revenue.value, currency)} × 100 = {_percent(margin)}")
                formulas.append("profit_margin")
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
        lines.extend(["| Item | Value |", "| --- | --- |"] )
        lines.extend(f"| {item.name.replace('_', ' ').title()} | {item.display_value} |" for item in result.outputs)
    if result.notes:
        lines.append("\n### Notes")
        lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines)
