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
from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int

# Ends on a digit: "-?\d[\d,]*" also took the comma in "£200,000, cost of
# goods sold of £125,000", so revenue's £200,000 was read as the cost.
_NUMBER_TEXT = r"-?\d(?:[\d,]*\d)?(?:\.\d+)?"
_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR"}
_CURRENCY_CODES = ("GBP", "USD", "EUR", "INR", "AED")
_CALCULATION_HINT = re.compile(
    r"\b(calculate|compute|work out|determine|what is|find)\b"
    # A terse direct question about a break-even figure ("…variable cost £15
    # per unit. Break-even units?") carries no verb but asks for a number.
    r"|\bbreak[- ]even(?:\s+(?:point|units|revenue|sales))?\s*\?", re.I,
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "revenues", "sales", "turnover"),
    # "cost of goods sold is £160,000" was not read, so a question giving it
    # was answered "please provide cost of sales".
    "cost_of_sales": ("cost of goods sold", "cost of goods", "cost of revenue", "cost of sales",
                      "cost_of_sales", "cogs", "cost"),
    "gross_profit": ("gross profit", "gross_profit"),
    # "overheads £45,000" was not read, so a P&L check confirmed gross profit
    # and never tested operating profit (int-recon-op-mismatch-paraphrase).
    "operating_expenses": ("operating expenses", "operating expense", "opex", "overheads", "overhead costs",
                           "operating costs"),
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
    # Read only by break-even, where a bare "price £25 per unit" is the
    # selling price; the terse form missed the calculator altogether.
    # "a product selling at £25" was asked for its selling price (27 Oct 2026).
    "selling_price": ("selling price", "sale price", "price per unit", "unit price", "sells for", "sell for",
                      "selling for", "selling at", "sells at", "sell at", "sold at", "price"),
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


def _find_value(query: str, aliases: tuple[str, ...], *, percentage: bool = False,
                not_after: re.Pattern[str] | None = None) -> tuple[Decimal, str | None] | None:
    alias_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    currency = r"(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?"
    suffix = r"\s*%" if percentage else ""
    # A percentage may sit a few plain words after its label: "VAT at a
    # supplied rate of 20%" asked for the VAT rate it had just been given.
    # Words only, so the gap can never step over a different figure.
    gap = r"(?:\s+[a-z]+){0,4}?" if percentage else ""
    patterns = [
        # "revenue for the year £800,000", "total sales came to £800,000".
        re.compile(rf"\b(?P<alias>{alias_pattern})\b{gap}(?:\s+for\s+the\s+(?:year|period|quarter|month))?\s*"
                   rf"(?:is|are|was|were|of|at|came\s+to|amounted\s+to|totall?ed|=|:)?\s*{currency}(?P<number>{_NUMBER_TEXT}){suffix}", re.I),
        # [\s-]*: a hyphenated "5-year life" or "10-year term" labels its number.
        # "in": "we generated £800,000 in revenue".
        re.compile(rf"{currency}(?P<number>{_NUMBER_TEXT}){suffix}[\s-]*(?:for|of|as|in)?\s*\b(?P<alias>{alias_pattern})\b", re.I),
    ]
    for pattern in patterns:
        # not_after: the "sales" of "cost of sales £500,000" is not revenue;
        # reading it so showed gross profit £0.00 as a verified calculation.
        match = next((found for found in pattern.finditer(query)
                      if not (not_after and not_after.search(query[:found.start("alias")]))), None)
        if not match:
            continue
        if not percentage and re.match(r'\s*%', query[match.end():]):
            continue
        value = _decimal(match.group("number"))
        if value is None:
            continue
        symbol = match.groupdict().get("symbol")
        code = match.groupdict().get("code")
        return value, (code.upper() if code else _CURRENCY_SYMBOLS.get(symbol or ""))
    return None


_COST_OF = re.compile(r"\bcosts?\s+of\s+(?:goods\s+)?$", re.I)


def _input(query: str, name: str, *, kind: str = "money", percentage: bool = False) -> CalculationInput | None:
    if name == "useful_life" and kind == "years":
        from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int
        query = re.sub(
            r"\b(" + SPELLED_NUMBER_PATTERN + r")(?=[ -]+(?:full\s+)?years?\b)",
            lambda match: str(spelled_number_to_int(match.group(1))), query, flags=re.I,
        )
    found = _find_value(query, _ALIASES[name], percentage=percentage,
                        not_after=_COST_OF if name == "revenue" else None)
    if found is None:
        return None
    value, currency = found
    return CalculationInput(
        name=name, value=value, display_value=f"{value:f}", kind=kind,
        currency=currency if kind == "money" else None,
    )


def _supplied(name: str, value: Decimal, currency: str | None = None, kind: str = "money") -> CalculationInput:
    """A value read from the question, recorded so the working shows what was used."""
    return CalculationInput(name=name, value=value, display_value=f"{value:f}", kind=kind,
                            currency=currency if kind == "money" else None, source_location="query")


_MONEY_FIGURE = re.compile(r"([£$€₹])\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)")
_RATE_AT = re.compile(rf"\bat\s+(?:a\s+(?:vat\s+)?rate\s+of\s+)?(?P<number>{_NUMBER_TEXT})\s*%", re.I)


def _vat_rate_at(query: str) -> CalculationInput | None:
    """The rate of a VAT request that names it after the amount ("VAT on £500
    at −20%"): the label-first reading needs "VAT at 20%", so −20% here was
    reported missing and the invalid rate never reached its check. Only when
    the request carries exactly one percentage, so another figure ("a 10%
    discount") is never taken for the rate."""
    if len(re.findall(r"\d\s*%", query)) != 1:
        return None
    match = _RATE_AT.search(query)
    value = _decimal(match.group("number")) if match else None
    if value is None:
        return None
    return CalculationInput(name="vat_rate", value=value, display_value=f"{value:f}", kind="percentage")


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


def _same_currency(inputs: list[CalculationInput], query: str = "") -> bool:
    currencies = {item.currency for item in inputs if item.kind == "money" and item.currency}
    if query:
        currencies.update(code.upper() for code in re.findall(r"\b(?:GBP|USD|EUR|INR|AED)\b", query, re.I))
        currencies.update(_CURRENCY_SYMBOLS[symbol] for symbol in re.findall(r"[£$€₹]", query))
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
    current = _parse_change(q)
    if not current or _input(q, "revenue") or _input(q, "cost_of_sales") or _UNMODELLED.search(q):
        # A change to variable-cost %, fixed costs or a profit target is not a
        # revenue/cost-of-sales scenario: "revenue +12%, variable costs stay at
        # 45%, fixed costs +£60,000 … revised operating profit" was answered
        # as a gross-profit change on figures from another scenario.
        return None
    item, sign, pct = current
    revenue = cost = None
    user_messages = [getattr(m, "content", str(m)) for m in (history or []) if getattr(m, "role", "user") == "user"]
    base_index = None
    for index in range(len(user_messages) - 1, -1, -1):
        text = user_messages[index]
        if not _MONEY_FIGURE.search(text):
            continue            # "Now assume revenue grows by 10%": a change, not a new task
        # The latest message with figures is the task being continued. If it
        # does not state revenue and cost of sales, an older scenario's do
        # not apply: qry-6941f17bd98f took £850,000/£510,000 from an earlier,
        # unrelated question because the current forecast stated revenue and
        # a variable-cost percentage instead.
        revenue, cost = _input(text, "revenue"), _input(text, "cost_of_sales")
        if revenue and cost:
            base_index = index
        else:
            revenue = cost = None
        break
    if not (revenue and cost) or pct is None:
        return None
    # "And if cost of sales ALSO rises by 5% ON TOP OF THAT" builds on the
    # change asked one turn earlier ("Now assume revenue grows by 10%"); only
    # the latest change was applied, so revenue stayed at £300,000
    # (int-followup-two-step). Earlier changes count only when the user says
    # the new one is in addition, never with "instead".
    earlier = []
    if _CUMULATIVE.search(q) and not re.search(r"\binstead\b", q, re.I):
        earlier = [found for text in user_messages[base_index + 1:]
                   if not (_input(text, "revenue") or _input(text, "cost_of_sales")) and (found := _parse_change(text))]
    for each in (revenue, cost):
        each.source_location = "earlier message"
    if not _same_currency([revenue, cost]):
        return CalculationResult(matched=True, status="clarification_required", inputs=[revenue, cost],
                                 error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
    c = _currency([revenue, cost])
    new_revenue, new_cost, steps = revenue.value, cost.value, []
    for change_item, change_sign, change_pct in [*earlier, current]:
        factor = Decimal("1") + change_sign * change_pct / Decimal("100")
        if change_item in ("revenue", "sales", "turnover"):
            steps.append(f"Revenue = {_money(new_revenue, c)} × {'(1 + ' if change_sign > 0 else '(1 − '}{change_pct:f}%) "
                         f"= {_money(new_revenue * factor, c)}")
            new_revenue *= factor
        else:
            steps.append(f"Cost of sales = {_money(new_cost, c)} × {'(1 + ' if change_sign > 0 else '(1 − '}{change_pct:f}%) "
                         f"= {_money(new_cost * factor, c)}")
            new_cost *= factor
    changes_revenue = item in ("revenue", "sales", "turnover")
    base_profit, new_profit = revenue.value - cost.value, new_revenue - new_cost
    label = "Revenue" if changes_revenue else "Cost of sales"
    steps.append(f"Gross profit = {_money(new_revenue, c)} − {_money(new_cost, c)} = {_money(new_profit, c)} (was {_money(base_profit, c)})")
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
    result.notes = [f"Revenue {_money(revenue.value, c)} and cost of sales {_money(cost.value, c)} are taken from your earlier message."]
    if earlier:
        result.notes.append("The earlier change" + ("s" if len(earlier) > 1 else "") + " you asked about "
                            + ", ".join(f"({name} {'+' if s_ > 0 else '−'}{p_:f}%)" for name, s_, p_ in earlier)
                            + " " + ("are" if len(earlier) > 1 else "is") + " kept, because you asked for this change on top of it.")
    elif unchanged not in {name if name not in ("sales", "turnover") else "revenue" for name, _, _ in earlier}:
        result.notes.append(f"{unchanged[0].upper() + unchanged[1:]} is kept at {_money(unchanged_value, c)} because your "
                            f"question changes only {label.lower()}; say so if it should change too.")
    return result


_UNMODELLED = re.compile(r"\b(?:variable[- ]cost|fixed (?:operating )?costs?|operating profit|break[- ]even|"
                         r"contribution|target|overheads?)\b", re.I)
_CUMULATIVE = re.compile(r"\b(?:also|on top of (?:that|this)|as well|in addition|additionally|too)\b", re.I)


def _parse_change(text: str) -> tuple[str, Decimal, Decimal] | None:
    """(item, +1/−1, percent) for "revenue increases by 15%"-style wording."""
    change = _CHANGE.search(text or "")
    if not change:
        return None
    item = (change.group("item") or change.group("item2")).lower()
    word = (change.group("direction") or change.group("direction2")).lower()
    pct = _decimal(change.group("pct") or change.group("pct2"))
    if pct is None:
        return None
    if item in ("cost", "costs", "cogs", "cost of goods sold"):
        item = "cost of sales"
    return item, (Decimal("-1") if re.match(r"fall|fell|decreas|drop|declin|goes down", word) else Decimal("1")), pct


_VAT_WORD = re.compile(r"\b(?:vat|gst)\b", re.I)
_INCLUSIVE = re.compile(r"\b(?:incl(?:ud(?:e|es|ed|ing)|usive|\.)?|gross of|after (?:vat|gst)|vat[- ]inclusive|inc[- ]vat)\b", re.I)
_EXCLUSIVE = re.compile(r"\b(?:excl(?:ud(?:e|es|ed|ing)|usive|\.)?|net of|plus (?:vat|gst)|before (?:vat|gst)|vat[- ]exclusive|ex[- ]vat)\b", re.I)


def item_rate(query: str, aliases: tuple[str, ...]) -> Decimal | None:
    """The rate written right after an item's amount: "purchases £48,000 at 5%"."""
    names = "|".join(re.escape(alias) for alias in aliases)
    match = re.search(rf"\b(?:{names})\b[^.%\d]{{0,20}}[£$€₹]?\s*{_NUMBER_TEXT}[^.%\d]{{0,25}}?(?:at|@)\s*(\d+(?:\.\d+)?)\s*%",
                      query or "", re.I)
    return _decimal(match.group(1)) if match else None


# How people state a sale or a purchase without the words "sales" or
# "purchases": "sells goods for £10,000", "buys supplies for £6,000", "takings
# for the day are £1,440". Not read before, so those VAT questions were left
# to the model (24 Oct 2026). Not "invoice": an invoice total is the reverse-VAT
# formula's (gross and net amounts, below).
_SELL_WORDS = r"sells?|sold|sale|takings"
_BUY_WORDS = r"buys?|bought|purchases?|pays?|paid"


_RECOVERY = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s+of\s+(?:the\s+|its\s+)?(?:input\s+(?:vat|tax|gst)|vat\s+on\s+(?:its\s+)?purchases)\s+"
    r"(?:is\s+|are\s+|can\s+be\s+)?(?:recoverable|reclaimable|recovered|reclaimed)"
    r"|\brecover(?:s|able)?\s+(?:only\s+)?(?P<pct2>\d+(?:\.\d+)?)\s*%\s+of\s+(?:the\s+|its\s+)?input\s+(?:vat|tax|gst)", re.I)
# Recovery limited without a stated share: partial exemption, exempt or
# non-business use. Applied only when the share is given.
_PARTIAL_RECOVERY = re.compile(r"\b(?:partial(?:ly)?\s+exempt\w*|partial\s+exemption|exempt\s+supplies|non[- ]business)\b",
                               re.I)
# Adjustments the engine never applies, so it does not present a result
# that leaves them out.
_OTHER_ADJUSTMENT = re.compile(
    r"\b(?:blocked|bad\s+debt\s+relief|reverse[- ]charge|capital\s+goods\s+scheme|import\s+vat|postponed\s+(?:import\s+)?vat|"
    r"error\s+correction|errors?\s+from\s+(?:an?\s+)?(?:earlier|previous|prior))\b", re.I)
_NO_COUNTRY_NOTE = ("The question names no country: the calculation uses the rate and treatment you gave and does not "
                    "confirm which country's VAT rules apply.")


_TIE_NOTE = ("VAT is rounded to the penny and the other figures follow from the rounded VAT, so the figures shown "
             "add up; the exact values are used for checking.")


def _penny(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _trade_amount(query: str, verbs: str) -> tuple[Decimal, str | None] | None:
    match = re.search(rf"\b(?:{verbs})\b(?:\s+[a-z]+){{0,4}}?\s+(?:for|of|are|is|totalling|total)\s+"
                      rf"(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?(?P<number>{_NUMBER_TEXT})(?!\s*%)",
                      query, re.I)
    if not match or (value := _decimal(match.group("number"))) is None:
        return None
    code = match.group("code")
    return value, code.upper() if code else _CURRENCY_SYMBOLS.get(match.group("symbol") or "")


def _treatment_after(query: str, amount: Decimal) -> bool | None:
    """True when the words after an amount say it includes VAT, False when
    they say it excludes it, None when they say neither before the next figure."""
    for written in {f"{amount:,f}".rstrip("0").rstrip("."), f"{amount:f}".rstrip("0").rstrip("."), f"{amount:,}"}:
        at = query.find(written)
        if at < 0:
            continue
        after = re.split(r"[£$€₹]|\d", query[at + len(written):], maxsplit=1)[0][:60]
        if _INCLUSIVE.search(after):
            return True
        if _EXCLUSIVE.search(after):
            return False
    return None


def vat_amounts(query: str) -> CalculationResult | None:
    """VAT once the country, one rate and the VAT treatment are all stated
    (input_requirements.missing_vat_inputs asks for whichever is missing).
    Output VAT on sales less input VAT on purchases, or the VAT in or on one
    amount. Several rates are left to the model, whose arithmetic is checked."""
    q = query or ""
    if not _VAT_WORD.search(q):
        return None
    # A share of input VAT that is recoverable is not a VAT rate.
    recovery_match = _RECOVERY.search(q)
    recovery = _decimal(recovery_match.group("pct") or recovery_match.group("pct2")) if recovery_match else None
    if recovery is not None and not 0 <= recovery <= 100:
        return None
    unrecovered = _RECOVERY.sub(" ", q)
    # Adjustments the engine does not apply: a full-recovery result is not
    # presented for them. Partial exemption is applied only with its share.
    if _OTHER_ADJUSTMENT.search(unrecovered):
        return None
    if _PARTIAL_RECOVERY.search(unrecovered) and recovery is None:
        return CalculationResult(
            matched=True, status="clarification_required", formula_ids=["vat_liability"], error_code="MISSING_INPUT",
            message="The business is partly exempt or has non-business use, so only part of its input VAT may be "
                    "recoverable. What percentage of its input VAT is recoverable? With that I can calculate the VAT "
                    "payable.")
    rates = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", unrecovered)
    # "cost of sales £40,000" is not sales: it was output VAT £8,000 and a
    # £2,000 refund where £10,000 was payable.
    sales = _find_value(q, ("sales", "turnover", "outputs"), not_after=_COST_OF) or _trade_amount(q, _SELL_WORDS)
    purchases = _find_value(q, ("purchases", "purchase", "inputs")) or _trade_amount(q, _BUY_WORDS)
    # Output instructions such as "calculate sales excluding VAT" do not
    # change an input explicitly stated as including VAT in the first clause.
    input_clause = re.split(r'[.!?]\s+', q, maxsplit=1)[0]
    if not _INCLUSIVE.search(input_clause) and not _EXCLUSIVE.search(input_clause):
        input_clause = q
    inclusive, exclusive = bool(_INCLUSIVE.search(input_clause)), bool(_EXCLUSIVE.search(input_clause))
    # "Sales of £120,000 excluding VAT and purchases of £60,000 including
    # VAT": each amount is as its own clause states it. Both words in one
    # question were read as ambiguous, and the calculation was left to the
    # model (24 Oct 2026).
    treatment = {}
    if inclusive and exclusive and sales and purchases:
        treatment = {"sales": _treatment_after(q, sales[0]), "purchases": _treatment_after(q, purchases[0])}
        if None in treatment.values():
            return None
    elif not rates or inclusive == exclusive:
        return None
    if not rates:
        return None
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
    single = (sales if sales and not purchases else purchases if purchases and not sales
              else None if sales else _find_value(q, ("vat on", "gst on", "vat of", "gst of", "vat in", "receives", "customer receipts", "on", "in")))
    if not (sales and purchases) and not single:
        return None
    currency = next((found[1] for found in (sales, purchases, single) if found and found[1]), None)

    def share(amount, r, item="sales"):
        included = treatment.get(item, inclusive)
        return amount * r / (100 + r) if included else amount * r / 100

    def formula(r, item="sales"):
        return f"× {r:f} ÷ (100 + {r:f})" if treatment.get(item, inclusive) else f"× {r:f} ÷ 100"

    rates_text = (f"a single rate of {rate_out:f}%" if rate_out == rate_in
                  else f"{rate_out:f}% on sales and {rate_in:f}% on purchases")
    from app.orchestration.source_taxonomy import detect_jurisdictions
    no_country = not detect_jurisdictions(q, infer_from_tax_terms=False)
    if treatment:
        stated = (f"sales {'including' if treatment['sales'] else 'excluding'} VAT and purchases "
                  f"{'including' if treatment['purchases'] else 'excluding'} VAT")
        notes = [f"The amounts are taken as stated, {stated}, at {rates_text}."]
    else:
        notes = [f"The amounts are taken as {'including' if inclusive else 'excluding'} VAT, as stated, at {rates_text}."]
    if sales and purchases:
        sales_returns = _find_value(q, ('sales returns', 'sales return'))
        purchase_returns = _find_value(q, ('purchase returns', 'purchase return', 'purchases returns'))
        returns = (sales_returns[0] if sales_returns else Decimal(0), purchase_returns[0] if purchase_returns else Decimal(0))
        gross_sales, gross_purchases = sales[0], purchases[0]
        for label, item in (('sales_returns', sales_returns), ('purchase_returns', purchase_returns)):
            if item and (item[0] < 0 or (item[1] and currency and item[1] != currency)):
                return CalculationResult(matched=True, status='clarification_required', error_code='INVALID_RETURNS',
                                         message='Returns must be non-negative and use the same currency as the supplied amounts.')
        net_sales, net_purchases = gross_sales - returns[0], gross_purchases - returns[1]
        if net_sales < 0 or net_purchases < 0:
            return CalculationResult(matched=True, status='clarification_required', error_code='INVALID_RETURNS',
                                     message='Returns exceed the corresponding supplied sales or purchases; please check those inputs.')
        output, input_vat = share(net_sales, rate_out, "sales"), share(net_purchases, rate_in, "purchases")
        recoverable = input_vat * recovery / 100 if recovery is not None else input_vat
        payable = output - recoverable
        outputs = [
            CalculationOutput(name="output_vat_on_sales", value=output, display_value=_money(output, currency), kind="money"),
            CalculationOutput(name="input_vat_on_purchases", value=input_vat, display_value=_money(input_vat, currency), kind="money"),
        ]
        if recovery is not None:
            outputs.append(CalculationOutput(name="recoverable_input_vat", value=recoverable,
                                             display_value=_money(_penny(recoverable), currency), kind="money"))
        outputs.append(CalculationOutput(name="vat_payable" if payable >= 0 else "vat_repayable", value=abs(payable),
                                         display_value=_money(abs(_penny(output) - _penny(recoverable)), currency),
                                         kind="money"))
        steps = [f"Output VAT = {_money(net_sales, currency)} {formula(rate_out, 'sales')} = {_money(output, currency)}",
                 f"Input VAT = {_money(net_purchases, currency)} {formula(rate_in, 'purchases')} = {_money(input_vat, currency)}",
                 *([f"Recoverable input VAT = {_money(input_vat, currency)} × {recovery:f}% = {_money(_penny(recoverable), currency)}"]
                   if recovery is not None else []),
                 f"VAT {'payable' if payable >= 0 else 'repayable'} = {_money(output, currency)} − {_money(_penny(recoverable), currency)} = {_money(abs(_penny(output) - _penny(recoverable)), currency)}"]
        if _penny(output) != output or _penny(recoverable) != recoverable:
            notes.append(_TIE_NOTE)
        # In the question's own tax: a GST answer said "valid VAT invoices".
        gst = bool(re.search(r"\bgst\b", q, re.I) and not re.search(r"\bvat\b", q, re.I))
        tax, credit = ("GST", "input tax credit") if gst else ("VAT", "input VAT")
        share_text = f"all of the {credit}" if recovery is None else f"{recovery:f}% of the {credit}, as you stated,"
        notes.append(f"The {'payable' if payable >= 0 else 'repayable'} figure assumes {share_text} is recoverable "
                     "(the purchases are used for taxable supplies, valid tax invoices are held and nothing is "
                     f"blocked) and that there are no other {tax} adjustments for the period. This arithmetic does not "
                     "establish legal eligibility or recoverability; no eligibility assessment has been made.")
        inputs = [_supplied('gross_sales', gross_sales, currency), _supplied('gross_purchases', gross_purchases, currency),
                  _supplied('sales_rate', rate_out, kind='percentage'), _supplied('purchases_rate', rate_in, kind='percentage')]
        if sales_returns or purchase_returns:
            inputs.extend([_supplied('sales_returns', returns[0], currency), _supplied('purchase_returns', returns[1], currency)])
            outputs.extend([CalculationOutput(name=name, value=value, display_value=_money(value, currency), kind='money')
                            for name, value in [('net_sales', net_sales), ('net_purchases', net_purchases)]])
            steps[:0] = [f'Net sales = {_money(gross_sales, currency)} − {_money(returns[0], currency)} = {_money(net_sales, currency)}',
                         f'Net purchases = {_money(gross_purchases, currency)} − {_money(returns[1], currency)} = {_money(net_purchases, currency)}']
        is_gst = bool(re.search(r'\bgst\b', q, re.I) and not re.search(r'\bvat\b', q, re.I))
        if is_gst:
            steps = [step.replace('Output VAT', 'Output GST').replace('Input VAT', 'Input tax credit').replace('VAT payable', 'GST payable').replace('VAT repayable', 'GST repayable') for step in steps]
        for label, aliases, computed, difference_name in (
            ('Output GST' if is_gst else 'Output VAT', ('output GST ledger shows', 'output GST ledger says', 'output GST ledger', 'output VAT ledger shows', 'output VAT ledger says', 'output VAT ledger'), output, 'output_ledger_difference'),
            ('Input tax credit', ('input GST ledger shows', 'input GST ledger says', 'input GST ledger', 'input tax credit ledger says', 'input tax credit ledger', 'input VAT ledger shows', 'input VAT ledger says', 'input VAT ledger'), input_vat, 'input_ledger_difference'),
        ):
            reported = _find_value(q, aliases)
            if reported:
                if reported[1] and currency and reported[1] != currency:
                    return CalculationResult(matched=True, status='clarification_required', error_code='CURRENCY_MISMATCH',
                                             message='The ledger and calculation amounts must use the same currency.')
                inputs.append(_supplied('reported_' + label.lower().replace(' ', '_'), reported[0], currency))
                difference = computed - reported[0]
                outputs.append(CalculationOutput(name=difference_name, value=difference, display_value=_money(difference, currency), kind='money'))
                steps.append(f'{label} ledger difference (calculated minus reported) = {_money(computed, currency)} − {_money(reported[0], currency)} = {_money(difference, currency)}')
                notes.append(f'{label} ledger {_money(reported[0], currency)} '
                             + ('matches' if reported[0] == computed else 'does not match')
                             + f' the calculated {_money(computed, currency)}.')
        if no_country:
            notes.append(_NO_COUNTRY_NOTE)
        result = _success_with_notes(["vat_liability"], outputs, steps, notes)
        result.inputs = inputs
        return result
    amount = single[0]
    vat = share(amount, rate)
    if single is purchases and (recovery is not None or re.search(r"\breclaim\w*|\brecover\w*|\binput (?:vat|tax)\b", q, re.I)):
        notes.append("Whether this VAT can be reclaimed depends on the purchase being used for taxable supplies and a "
                     "valid VAT invoice being held; the calculation does not confirm that.")
    other = amount - vat if inclusive else amount + vat
    # The VAT is rounded to the penny and the other figure follows from it, so
    # the figures shown add up to the amount given: £99.99 including VAT was
    # shown as £16.67 VAT and £83.33 net, which make £100.00 (24 Oct 2026).
    # The exact values are kept for checking.
    shown_vat = _penny(vat)
    shown_other = amount - shown_vat if inclusive else amount + shown_vat
    outputs = [CalculationOutput(name="vat_amount", value=vat, display_value=_money(shown_vat, currency), kind="money"),
               CalculationOutput(name="amount_excluding_vat" if inclusive else "total_including_vat", value=other,
                                 display_value=_money(shown_other, currency), kind="money")]
    steps = [f"VAT = {_money(amount, currency)} {formula(rate)} = {_money(shown_vat, currency)}",
             (f"Amount excluding VAT = {_money(amount, currency)} − {_money(shown_vat, currency)} = {_money(shown_other, currency)}" if inclusive
              else f"Total including VAT = {_money(amount, currency)} + {_money(shown_vat, currency)} = {_money(shown_other, currency)}")]
    if shown_vat != vat:
        notes.append(_TIE_NOTE)
    if recovery is not None and single is purchases:
        recoverable_single = vat * recovery / 100
        outputs.append(CalculationOutput(name="recoverable_input_vat", value=recoverable_single,
                                         display_value=_money(_penny(recoverable_single), currency), kind="money"))
        steps.append(f"Recoverable input VAT = {_money(shown_vat, currency)} × {recovery:f}% = "
                     f"{_money(_penny(recoverable_single), currency)}")
    if inclusive:
        notes.append('The inclusive amount already contains VAT. Multiplying it by the rate overstates VAT; use rate ÷ (100 + rate) instead.')
    if no_country:
        notes.append(_NO_COUNTRY_NOTE)
    result = _success_with_notes(["vat_from_inclusive" if inclusive else "vat_on_net"], outputs, steps, notes)
    result.inputs = [_supplied('amount',amount,currency),_supplied('vat_rate',rate,kind='percentage')]
    return result


def _success_with_notes(formulas, outputs, steps, notes) -> CalculationResult:
    result = _success(formulas, [], outputs, steps)
    result.notes = notes
    return result


def vat_returns_followup(query, history):
    """Revise a named return only, retaining supplied rates and ledger balances."""
    change_pattern = r'\b(?:change|correct|set)\s+only\s+(sales returns|purchase returns)\s+to\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)'
    if not re.search(change_pattern, query, re.I):
        return None
    base = None
    changes = []
    for message in reversed(history):
        if message.role != 'user':
            continue
        candidate = vat_amounts(message.content)
        if candidate and candidate.status == 'success' and 'vat_liability' in candidate.formula_ids:
            base = message.content
            break
        if re.search(change_pattern,message.content,re.I):
            changes.insert(0,message.content)
        else:
            return None
    if base is None:
        return None
    for text in [*changes,query]:
        change = re.search(change_pattern,text,re.I)
        old = _find_value(base,(change[1],))
        if not old:
            return None
        if change[2] and _CURRENCY_SYMBOLS[change[2]] != old[1]:
            return None
        label = re.escape(change[1])
        base, count = re.subn(r'\b'+label+r'\s*(?:(?:of|is|are|:)\s*)?[£$€₹]?\s*\d[\d,]*(?:\.\d+)?',
                             change[1]+' '+(change[2] or '')+change[3],base,count=1,flags=re.I)
        if count != 1:
            return None
    result = vat_amounts(base)
    if result:
        result.notes.append('Only the specified returns changed; the original rates, eligibility assumptions and recorded ledger balances were retained.')
        for item in result.inputs:
            item.source_location = 'query' if item.name == change[1].replace(' ','_') else 'conversation_history'
    return result


def supplied_accrual(query):
    if not (re.search(r'\b(?:adjusting journal|accrual)\b',query,re.I)
            and re.search(r'\bnot been invoiced,? paid or recorded\b',query,re.I)
            and re.search(r'\bignore VAT\b',query,re.I)):
        return None
    expense = re.search(r'\b(electricity|rent|utilities|insurance)\s+costs\b',query,re.I)
    if not expense:
        return None
    amount = _find_value(query,(expense[1]+' costs',))
    if not amount or not amount[1] or amount[0] < 0:
        return None
    value,currency = amount
    shown = _money(value,currency)
    result = _success_with_notes(['unrecorded_expense_accrual'],[
        CalculationOutput(name='expense_debit',value=value,display_value=shown,kind='money'),
        CalculationOutput(name='accrued_expenses_credit',value=value,display_value=shown,kind='money'),
        CalculationOutput(name='profit_change',value=-value,display_value=_money(-value,currency),kind='money'),
        CalculationOutput(name='liabilities_change',value=value,display_value=shown,kind='money'),
        CalculationOutput(name='cash_change',value=Decimal(0),display_value=_money(Decimal(0),currency),kind='money')],
        [f'Proposed adjusting entry: debit {expense[1].lower()} expense {shown}; credit accrued expenses (liability) {shown}.'],
        ['This entry is proposed, not posted. The stated expense belongs to December and VAT is ignored as requested.',
         'Recording the accrual reduces profit and increases liabilities by the stated amount; cash is unchanged.',
         'On later payment of the accrued amount: debit accrued expenses and credit cash/bank. Do not record the same expense again.'])
    result.inputs = [_supplied('expense',value,currency)]
    return result


def supplied_loan_payment(query):
    """Split a payment only when the user expressly treats interest as expense."""
    if not (re.search(r'\bloan principal\b',query,re.I)
            and re.search(r'\binterest is an expense\b',query,re.I)
            and re.search(r'\bjournal entry\b',query,re.I)):
        return None
    payment = _find_value(query,('pays','payment of'))
    principal = _find_value(query,('loan principal',))
    interest = _find_value(query,('interest',))
    if not all((payment,principal,interest)):
        return None
    inputs = [_supplied(name,value[0],value[1]) for name,value in [('payment',payment),('principal',principal),('interest',interest)]]
    if not _same_currency(inputs) or any(i.value < 0 for i in inputs):
        return CalculationResult(matched=True,status='clarification_required',error_code='CURRENCY_MISMATCH',message='Payment components must be non-negative and use the same currency.')
    if payment[0] != principal[0]+interest[0]:
        return CalculationResult(matched=True,status='clarification_required',error_code='INVALID_PAYMENT_SUM',message='Principal plus interest does not equal the stated payment. Please confirm the components.')
    currency = _currency(inputs)
    result = _success_with_notes(['loan_payment_split'],[
        CalculationOutput(name=name,value=value,display_value=_money(value,currency),kind='money')
        for name,value in [('loan_liability_debit',principal[0]),('interest_expense_debit',interest[0]),('cash_credit',payment[0])]],
        [f'Proposed journal: debit loan liability {_money(principal[0],currency)}; debit interest expense {_money(interest[0],currency)}; credit bank {_money(payment[0],currency)}.'],
        [f'Profit decreases by {_money(interest[0],currency)}; cash decreases by {_money(payment[0],currency)}; loan liability decreases by {_money(principal[0],currency)}.',
         'Principal repayment is not an expense. Interest treatment is the supplied exercise assumption; no tax or current-law conclusion is made. This entry has not been posted.'])
    result.inputs = inputs
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


_MONEY = r"[£$€₹]\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)"
_SALE_LINE = re.compile(
    r"(?P<symbol>[£$€₹])\s?(?P<amount>\d(?:[\d,]*\d)?(?:\.\d+)?)\s+(?:of\s+[a-z\s]{0,30}?\s+)?at\s+(?:the\s+|a\s+)?"
    r"(?:[a-z-]+\s+){0,3}?(?:rate\s+of\s+)?(?P<rate>\d+(?:\.\d+)?)\s*%", re.I)


def output_vat_lines(query: str) -> CalculationResult | None:
    """Output VAT on sales lines that each carry their own rate ("£8,000 at
    the standard rate of 20% and £3,000 at the reduced rate of 5%"). It asked
    for "the VAT rate" — two were given — and whether the figures include VAT.
    VAT charged at a rate on a sale value is calculated on that value; the
    VAT if the values were VAT-inclusive is shown beside it, not assumed away.
    Only a request for output VAT (not net VAT payable) is handled here."""
    q = query or ""
    if not _VAT_WORD.search(q) or re.search(r"\b(?:purchases?|input vat|input tax|reclaim|payable|owe)\b", q, re.I):
        return None
    lines = list(_SALE_LINE.finditer(q))
    if len(lines) < 2 and not (lines and re.search(r"\boutput (?:vat|tax)\b", q, re.I)):
        return None
    inclusive = bool(_INCLUSIVE.search(q)) and not _EXCLUSIVE.search(q)
    currency = _CURRENCY_SYMBOLS.get(lines[0].group("symbol"))
    outputs, steps, total, total_inclusive = [], [], Decimal("0"), Decimal("0")
    inputs = []
    for index, line in enumerate(lines, start=1):
        amount, rate = _decimal(line.group("amount")), _decimal(line.group("rate"))
        if amount is None or rate is None or not 0 <= rate <= 100:
            return None
        inputs += [_supplied(f"sales_line_{index}", amount, currency), _supplied(f"vat_rate_line_{index}", rate, kind="percentage")]
        vat = amount * rate / (100 + rate) if inclusive else amount * rate / 100
        total += vat
        total_inclusive += amount * rate / (100 + rate)
        outputs.append(CalculationOutput(name=f"output_vat_line_{index}", value=vat, display_value=_money(vat, currency), kind="money"))
        steps.append(f"{_money(amount, currency)} at {rate:f}% = {_money(amount, currency)} × {rate:f} ÷ {'(100 + ' + format(rate, 'f') + ')' if inclusive else '100'} = {_money(vat, currency)}")
    outputs.append(CalculationOutput(name="total_output_vat", value=total, display_value=_money(total, currency), kind="money"))
    steps.append("Total output VAT = " + " + ".join(o.display_value for o in outputs[:-1]) + f" = {_money(total, currency)}")
    result = _success(["output_vat_by_rate"], inputs, outputs, steps)
    result.notes = (["The sales values are taken as VAT-inclusive, as stated."] if inclusive else [
        "VAT is charged on the sales values as given (net of VAT). If those values already include VAT, "
        f"the output VAT inside them would be {_money(total_inclusive, currency)}."])
    return result


_RESULT_CHANGE = re.compile(
    r"\bfrom\s+an?\s+(?P<from_kind>loss|profit)\s+of\s+" + _MONEY.replace("(\\d", "(?P<from>\\d", 1)
    + r"\s+to\s+an?\s+(?P<to_kind>loss|profit)\s+of\s+" + _MONEY.replace("(\\d", "(?P<to>\\d", 1), re.I)


def result_change(query: str) -> CalculationResult | None:
    """"…changes from a loss of £12,000 to a profit of £3,000": a £15,000
    improvement. Composed by the model it was right, but followed by "possible
    drivers" (sales volume, price, unit contribution) the question never gave,
    shaped by an earlier break-even example in the same chat. The arithmetic
    is stated; causes are not invented."""
    q = query or ""
    match = _RESULT_CHANGE.search(q)
    if not match:
        return None
    currency = _CURRENCY_SYMBOLS.get((re.search(r"[£$€₹]", match.group(0)) or [""])[0])
    start = _decimal(match.group("from")) * (-1 if match.group("from_kind").lower() == "loss" else 1)
    end = _decimal(match.group("to")) * (-1 if match.group("to_kind").lower() == "loss" else 1)
    change = end - start
    word = "improvement" if change >= 0 else "deterioration"
    result = _success(["result_change"], [_supplied("starting_result", start, currency), _supplied("ending_result", end, currency)], [
        CalculationOutput(name="starting_result", value=start, display_value=_money(start, currency), kind="money"),
        CalculationOutput(name="ending_result", value=end, display_value=_money(end, currency), kind="money"),
        CalculationOutput(name=word, value=abs(change), display_value=_money(abs(change), currency), kind="money"),
    ], [f"Change = {_money(end, currency)} − ({_money(start, currency)}) = {_money(change, currency)}"])
    result.notes = [
        f"The result moved by {_money(abs(change), currency)} — an {word} of that amount in absolute terms.",
        "A percentage change is not meaningful when the starting figure is a loss (it would divide by a negative base).",
        "The question does not say what caused the change; to explain it, share the revenue and cost figures for both periods.",
    ]
    return result


_COST_PRICE = re.compile(r"\b(?:cost(?:s|ing)?|cost price|bought(?:\s+\w+){0,2}\s+for|purchased(?:\s+\w+){0,2}\s+for|paid)\s+(?:of\s+|is\s+|was\s+|at\s+)?" + _MONEY, re.I)
# Variable costs given as a share of revenue, or a contribution margin: the
# revenue form of break-even, which needs no unit price.
_REVENUE_FORM = re.compile(r"\bvariable\s+costs?\b[^.]{0,40}?\d+(?:\.\d+)?\s*%\s*(?:of\s+(?:revenue|sales|turnover))?"
                           r"|\bcontribution\s+margin\s+(?:is|of|=)\s*\d", re.I)
_SELL_PRICE = re.compile(r"\b(?:sells?|sold|selling price|sale price|sells? (?:it|them) for|retails?)\s+(?:\w+\s+){0,2}?(?:for|at|of|is|was)?\s*" + _MONEY, re.I)


def price_margin_markup(query: str) -> CalculationResult | None:
    """"A product costs £84 and sells for £126": gross profit £42, margin
    33.33%, markup 50%. It asked for "revenue" — the selling price is the
    revenue per item — and markup had no formula."""
    q = query or ""
    if not re.search(r"\b(?:margin|markup|mark-up|mark up|gross profit|profit)\b", q, re.I) or _input(q, "revenue"):
        return None
    cost, sell = _COST_PRICE.search(q), _SELL_PRICE.search(q)
    if not (cost and sell) or len(re.findall(r"[£$€₹]\s?\d", q)) != 2:
        return None
    cost_value, sell_value = _decimal(cost.group(1)), _decimal(sell.group(1))
    currency = _CURRENCY_SYMBOLS.get((re.search(r"[£$€₹]", q) or [""])[0])
    profit = sell_value - cost_value
    outputs = [CalculationOutput(name="gross_profit", value=profit, display_value=_money(profit, currency), kind="money")]
    steps = [f"Gross profit = {_money(sell_value, currency)} − {_money(cost_value, currency)} = {_money(profit, currency)}"]
    if sell_value:
        margin = profit / sell_value * 100
        outputs.append(CalculationOutput(name="gross_margin", value=margin, display_value=_percent(margin), kind="percentage"))
        steps.append(f"Gross margin = {_money(profit, currency)} ÷ {_money(sell_value, currency)} × 100 = {_percent(margin)}")
    if cost_value:
        markup = profit / cost_value * 100
        outputs.append(CalculationOutput(name="markup", value=markup, display_value=_percent(markup), kind="percentage"))
        steps.append(f"Markup = {_money(profit, currency)} ÷ {_money(cost_value, currency)} × 100 = {_percent(markup)}")
    return _success(["gross_profit", "gross_margin", "markup"],
                    [_supplied("cost_price", cost_value, currency), _supplied("selling_price", sell_value, currency)], outputs, steps)


_SIMPLE_INTEREST_RATE = re.compile(r"(?:at|rate of)\s+(-?\d+(?:\.\d+)?)\s*%", re.I)
_SIMPLE_INTEREST_YEARS = re.compile(r"\bfor\s+(\d+(?:\.\d+)?)\s+years?\b", re.I)


_CORRECTION = re.compile(r"\b(?:actually|sorry|correction|i meant|i mean|make that|no,? wait|rather)\b", re.I)
_CHECKED_FOR_CORRECTION = ("revenue", "cost_of_sales", "expenses", "operating_expenses", "fixed_costs",
                           "selling_price", "variable_cost")


def _stated_values(query: str, name: str) -> list[tuple[int, Decimal, str | None]]:
    aliases = "|".join(re.escape(alias) for alias in sorted(_ALIASES[name], key=len, reverse=True))
    pattern = re.compile(rf"\b(?:{aliases})\b\s*(?:is|are|was|were|of|at|=|:)?\s*(?P<symbol>[£$€₹])\s?(?P<number>{_NUMBER_TEXT})",
                         re.I)
    return [(m.start(), _decimal(m.group("number")), m.group("symbol")) for m in pattern.finditer(query)]


def corrected_input(query: str) -> CalculationResult | None:
    """"Revenue was £100,000. Actually revenue was £120,000." The model used
    £120,000 without a word (int-contradictory-inputs). Two values for the
    same input with a correction between them are put back to the user,
    naming both — never one chosen silently. Only with correction wording:
    "£100,000 in 2024 and £120,000 in 2025" is two periods, not a correction."""
    for name in _CHECKED_FOR_CORRECTION:
        stated = _stated_values(query, name)
        if len({value for _, value, _ in stated}) < 2:
            continue
        (first_at, first, symbol), (last_at, last, _) = stated[0], stated[-1]
        if not _CORRECTION.search(query[first_at:last_at]):
            continue
        currency = _CURRENCY_SYMBOLS.get(symbol or "")
        label = name.replace("_", " ")
        return CalculationResult(
            matched=True, status="clarification_required", formula_ids=[], error_code="AMBIGUOUS_INPUTS",
            inputs=[_supplied(f"{name}_first", first, currency), _supplied(f"{name}_corrected", last, currency)],
            message=(f"You gave {label} as {_money(first, currency)} and then as {_money(last, currency)}. "
                     f"Which should I use — {_money(last, currency)}, your correction?"))
    return None


_TWO_PERIODS = re.compile(r"\b(?:both years|each year|last year|prior year|previous year|two years|year[- ]on[- ]year)\b", re.I)


def two_period_current_ratio(query: str) -> CalculationResult | None:
    """"Current assets £75,500 and current liabilities £12,700 at year end;
    last year they were £60,000 and £15,000. Calculate the current ratio for
    both years and chart the change." Only this year's ratio was calculated
    and no chart drawn (int-multistep-ratio-chart). Both periods are
    calculated before anything is charted; the second pair is read in the
    order the first pair was given, and the answer says so."""
    q = query or ""
    if not re.search(r"\bcurrent ratio\b", q, re.I) or not _TWO_PERIODS.search(q):
        return None
    amounts = list(_MONEY_FIGURE.finditer(q))
    assets_at, liabilities_at = re.search(r"\bcurrent assets\b", q, re.I), re.search(r"\bcurrent liabilities\b", q, re.I)
    if len(amounts) != 4 or not assets_at or not liabilities_at:
        return None
    values = [_decimal(m.group(2)) for m in amounts]
    currency = _CURRENCY_SYMBOLS.get(amounts[0].group(1))
    assets_first = assets_at.start() < liabilities_at.start()
    now_assets, now_liabilities = (values[0], values[1]) if assets_first else (values[1], values[0])
    prior_assets, prior_liabilities = (values[2], values[3]) if assets_first else (values[3], values[2])
    inputs = [_supplied("current_assets", now_assets, currency), _supplied("current_liabilities", now_liabilities, currency),
              _supplied("current_assets_last_year", prior_assets, currency),
              _supplied("current_liabilities_last_year", prior_liabilities, currency)]
    if not now_liabilities or not prior_liabilities:
        return _undefined("current_ratio", inputs, "The ratio is undefined because current liabilities are zero.")
    now, prior = now_assets / now_liabilities, prior_assets / prior_liabilities
    result = _success(["current_ratio", "current_ratio_comparison"], inputs, [
        CalculationOutput(name="current_ratio_this_year", value=now, display_value=_ratio(now), kind="ratio"),
        CalculationOutput(name="current_ratio_last_year", value=prior, display_value=_ratio(prior), kind="ratio"),
        CalculationOutput(name="change", value=now - prior, display_value=f"{now - prior:+.2f}", kind="ratio"),
    ], [f"Current ratio this year = {_money(now_assets, currency)} ÷ {_money(now_liabilities, currency)} = {_ratio(now)}",
        f"Current ratio last year = {_money(prior_assets, currency)} ÷ {_money(prior_liabilities, currency)} = {_ratio(prior)}",
        f"Change = {now:.2f} − {prior:.2f} = {now - prior:+.2f}"])
    result.notes = [f"Last year's figures are read in the order this year's were given: current assets "
                    f"{_money(prior_assets, currency)}, current liabilities {_money(prior_liabilities, currency)}."]
    return result


def simple_interest(query: str) -> CalculationResult | None:
    """"Simple interest on £5,000 at 4% a year for 3 years" — one question.
    It went to the model, which computed −£600 from a −4% rate. A negative
    rate is not calculated: simple interest here is on a lender's or
    depositor's rate, so the rate is returned for confirmation first."""
    q = query or ""
    if not re.search(r"\bsimple interest\b", q, re.I):
        return None
    amounts = list(_MONEY_FIGURE.finditer(q))
    rate, years = _SIMPLE_INTEREST_RATE.search(q), _SIMPLE_INTEREST_YEARS.search(q)
    if len(amounts) != 1 or not rate or not years:
        return None
    principal, rate_value, term = _decimal(amounts[0].group(2)), Decimal(rate.group(1)), Decimal(years.group(1))
    currency = _CURRENCY_SYMBOLS.get(amounts[0].group(1))
    inputs = [_supplied("principal", principal, currency), _supplied("interest_rate", rate_value, kind="percentage"),
              _supplied("years", term, kind="years")]
    if rate_value < 0:
        return CalculationResult(
            matched=True, status="clarification_required", formula_ids=["simple_interest"], inputs=inputs,
            error_code="INVALID_PERCENTAGE",
            message=(f"The interest rate given is negative ({rate_value:f}%). Simple interest is worked out on a "
                     "non-negative annual rate, so I have not calculated it. Please confirm the rate."))
    if term <= 0:
        return _undefined("simple_interest", inputs, "Simple interest is undefined because the term must be more than zero years.")
    interest = principal * rate_value / 100 * term
    return _success(["simple_interest"], inputs, [
        CalculationOutput(name="simple_interest", value=interest, display_value=_money(interest, currency), kind="money"),
        CalculationOutput(name="total_repayable", value=principal + interest, display_value=_money(principal + interest, currency), kind="money"),
    ], [f"Simple interest = {_money(principal, currency)} × {rate_value:f}% × {term:f} years = {_money(interest, currency)}",
        f"Total = {_money(principal, currency)} + {_money(interest, currency)} = {_money(principal + interest, currency)}"])


def bank_reconciliation(query: str) -> CalculationResult | None:
    """Reconcile explicitly labelled positive balances; never plug a difference."""
    if (not re.search(r'\bbank reconciliation\b', query, re.I)
            and not (re.search(r'\bcash\s*book\b',query,re.I) and re.search(r'\bbank statement\b',query,re.I))) or not re.search(r'\d', query):
        return None
    labels = {
        'bank_statement_balance': ('bank statement balance', 'bank statement shows'),
        'cash_book_balance': ('cash book balance', 'cashbook balance', 'cash book shows'),
        'deposits_in_transit': ('deposits in transit', 'outstanding deposits'),
        'outstanding_cheques': ('outstanding cheques', 'unpresented cheques', 'outstanding checks'),
        'bank_charges': ('bank charges',),
        'interest_received': ('interest received',),
    }
    for aliases in labels.values():
        alias_pattern = '|'.join(re.escape(label) for label in aliases)
        if len(re.findall(rf'\b(?:{alias_pattern})\s*(?:is|was|are|of|:|=)?\s*[£$€₹]?\s*{_NUMBER_TEXT}', query, re.I)) > 1:
            return CalculationResult(matched=True, status='clarification_required', error_code='AMBIGUOUS_INPUTS',
                                     message='Which version of the repeated reconciliation balance or adjustment should be used?')
    masked = query
    for aliases in labels.values():
        for label in aliases:
            masked = re.sub(rf'\b{re.escape(label)}\s*(?:is|was|are|of|:|=)?\s*[£$€₹]?\s*{_NUMBER_TEXT}', '', masked, flags=re.I)
    if re.search(r'[£$€₹]\s*-?\d', masked, re.I):
        return None
    found = {key: _find_value(query, aliases) for key, aliases in labels.items()}
    inputs = [_supplied(key, value[0], value[1]) for key, value in found.items() if value]
    required = ['bank_statement_balance', 'cash_book_balance']
    if not re.search(r'\bno other (?:reconciling )?items\b', query, re.I) and not all(found.values()):
        # Other corrections, errors and overdrafts need their own explicit direction.
        return None
    if re.search(r'\b(?:overdraft|dishonou?red|errors?|direct debit|standing order|unrecorded receipt)\b', query, re.I):
        return None
    missing = [key for key in required if found[key] is None]
    if missing:
        return _clarify('bank_reconciliation', inputs, missing)
    if not _same_currency(inputs, query):
        return CalculationResult(matched=True, status='clarification_required', error_code='CURRENCY_MISMATCH', message=_CURRENCY_MISMATCH_MESSAGE)
    if any(i.value < 0 for i in inputs):
        return None
    v = {i.name: i.value for i in inputs}
    currency = _currency(inputs)
    bank = v['bank_statement_balance'] + v.get('deposits_in_transit', 0) - v.get('outstanding_cheques', 0)
    book = v['cash_book_balance'] - v.get('bank_charges', 0) + v.get('interest_received', 0)
    outputs = [CalculationOutput(name=k, value=a, display_value=_money(a, currency), kind='money') for k, a in (
        ('adjusted_bank_balance', bank), ('adjusted_cash_book_balance', book), ('unreconciled_difference', bank-book))]
    result = _success(['bank_reconciliation'], inputs, outputs, [
        f'Adjusted bank balance = {v["bank_statement_balance"]:f} + {v.get("deposits_in_transit", 0):f} deposits in transit − {v.get("outstanding_cheques", 0):f} outstanding cheques = {bank:f}',
        f'Adjusted cash book balance = {v["cash_book_balance"]:f} − {v.get("bank_charges", 0):f} bank charges + {v.get("interest_received", 0):f} interest received = {book:f}',
        f'Unreconciled difference = {bank:f} − {book:f} = {bank-book:f}',
    ])
    result.notes = ['Timing items adjust the bank-statement side; unrecorded charges and interest adjust the cash-book side. '
                    'No adjustment is counted on both sides. The reconciliation uses only the items supplied; unlisted items are not inferred.',
                    'A zero difference establishes arithmetic agreement only; compare bank records, dates and ledger entries before approving any adjustment.']
    return result


def periodic_inventory(query: str) -> CalculationResult | None:
    """Explicit ordered cost layers for a single periodic sale, in the existing engine."""
    if not re.search(r'\bFIFO\b|weighted[- ]average', query, re.I):
        return None
    # Moving-average inventory with interleaved sales needs dated transactions.
    if not re.search(r'\bperiodic\b', query, re.I) or not re.search(r'all purchases (?:occurred |were )?before', query, re.I):
        return None
    pattern = re.compile(rf'\b(opening inventory|purchases?)\s+({_NUMBER_TEXT})\s+units?\s+at\s*([£$€₹])?\s*({_NUMBER_TEXT})\s*(?:each|per unit)?', re.I)
    layers = list(pattern.finditer(query))
    sold = _find_value(query, ('units sold',))
    if not layers or sold is None:
        return _clarify('periodic_inventory', [], ['ordered cost layers and units sold'])
    # Do not silently drop a layer or a return the supported shape cannot parse.
    if len(layers) != len(re.findall(r'\b(?:opening inventory|purchases?)\s+\d', query, re.I)) or re.search(r'\b(?:returns?|damaged|write[- ]down|freight)\b', query, re.I):
        return None
    if sum(layer[1].lower() == 'opening inventory' for layer in layers) > 1 or len(re.findall(r'\bunits sold\s+\d', query, re.I)) != 1:
        return None
    masked = pattern.sub('', query)
    masked = re.sub(rf'\bunits sold\s+{_NUMBER_TEXT}', '', masked, flags=re.I)
    if re.search(r'[£$€₹]\s*-?\d', masked):
        return None
    layers.sort(key=lambda layer: layer[1].lower() != 'opening inventory')
    inputs, quantities, costs = [], [], []
    for index, layer in enumerate(layers):
        qty, cost = _decimal(layer[2]), _decimal(layer[4])
        quantities.append(qty); costs.append(cost)
        inputs += [_supplied(f'layer_{index+1}_units', qty, kind='units'),
                   _supplied(f'layer_{index+1}_unit_cost', cost, _CURRENCY_SYMBOLS.get(layer[3] or ''))]
    inputs.append(_supplied('units_sold', sold[0], kind='units'))
    if not _same_currency(inputs, query):
        return CalculationResult(matched=True, status='clarification_required', error_code='CURRENCY_MISMATCH', message=_CURRENCY_MISMATCH_MESSAGE)
    total_units, total_cost = sum(quantities), sum(q*c for q,c in zip(quantities,costs))
    if total_units <= 0 or sold[0] < 0 or sold[0] > total_units or any(x < 0 for x in quantities+costs):
        return _clarify('periodic_inventory', inputs, ['valid non-negative layers and units sold not exceeding available units'])
    remaining, fifo = sold[0], Decimal(0)
    consumed = []
    for qty, cost in zip(quantities, costs):
        taken = min(remaining, qty)
        fifo += taken*cost
        remaining -= taken
        if taken:
            consumed.append(f"{taken:f} × {cost:f}")
    average = total_cost/total_units
    currency = _currency(inputs)
    outputs, steps = [], []
    def add(name, value, formula, kind='money'):
        display = _money(value, currency) if kind == 'money' else f'{value:f} units'
        outputs.append(CalculationOutput(name=name, value=value, display_value=display, kind=kind))
        steps.append(f'{name.replace("_", " ").capitalize()} = {formula} = {display}')
    add('total_inventory_cost', total_cost, ' + '.join(f'{q:f} × {c:f}' for q, c in zip(quantities, costs)))
    closing_units = total_units - sold[0]
    if re.search(r'\bFIFO\b', query, re.I):
        add('fifo_cost_of_goods_sold', fifo, ' + '.join(consumed) or '0 units sold')
        add('fifo_closing_units', closing_units, f'{total_units:f} − {sold[0]:f}', 'units')
        add('fifo_closing_inventory', total_cost-fifo, f'{total_cost:f} available cost − {fifo:f} FIFO COGS')
        add('fifo_reconciliation_difference', fifo+(total_cost-fifo)-total_cost, f'{fifo:f} COGS + {total_cost-fifo:f} closing inventory − {total_cost:f} available cost')
    if re.search(r'weighted[- ]average', query, re.I):
        add('weighted_average_unit_cost', average, f'{total_cost:f} ÷ {total_units:f}')
        add('weighted_average_cost_of_goods_sold', sold[0]*average, f'{sold[0]:f} × ({total_cost:f} ÷ {total_units:f})')
        average_cogs = sold[0]*average
        average_closing = total_cost-average_cogs
        add('weighted_average_closing_units', closing_units, f'{total_units:f} − {sold[0]:f}', 'units')
        add('weighted_average_closing_inventory', average_closing, f'{total_cost:f} available cost − {average_cogs:f} COGS')
        add('weighted_average_reconciliation_difference', average_cogs+average_closing-total_cost, f'{average_cogs:f} COGS + {average_closing:f} closing inventory − {total_cost:f} available cost')
    result = _success(['periodic_inventory'], inputs, outputs, steps)
    result.notes = ['Periodic valuation uses the supplied ordered cost layers; all purchases precede the only sale as stated. '
                    'Each method conserves total cost: cost of goods sold plus closing inventory equals available cost. '
                    'Arithmetic agreement does not validate stock counts or source records.']
    return result


def _supplied_as_value(query: str, formula: str) -> bool:
    """The formula's subject appears as a figure the user gave ("straight-line
    depreciation is $70,000"), so the message supplies it rather than asks
    for it. A deferred-tax scenario was answered "provide asset cost,
    residual value, useful life" because it mentioned the depreciation."""
    subject = r"[- ]".join(re.escape(word) for word in formula.split("_"))
    value = r"(?:[£$€₹]\s?\d|\d[\d,]*(?:\.\d+)?\s*(?:%|USD|GBP|EUR|INR))"
    return bool(re.search(
        rf"\b{subject}\b(?:\s+\w+){{0,3}}?\s+(?:is|was|of|totals?|amounts?\s+to|deducted\s+is|=|:)\s*{value}",
        query, re.I,
    ))


_PRESENT_VALUE = re.compile(
    rf"\bpresent value of\s+(?P<symbol>[£$€₹])?\s*(?:(?P<code>GBP|USD|EUR|INR|AED)\s*)?(?P<amount>{_NUMBER_TEXT})"
    rf"(?:\s+[a-z]+){{0,3}}?\s+(?:in|after)\s+(?P<years>\d+)\s+years?\b[^.?%]{{0,40}}?(?P<rate>\d+(?:\.\d+)?)\s*%",
    re.I)


def present_value(query: str) -> CalculationResult | None:
    """The present value of one amount received after whole years, discounted
    annually at a stated rate: amount ÷ (1 + rate)^years. Left to the model's
    calculator call before, with no deterministic result to check it by."""
    match = _PRESENT_VALUE.search(query or "")
    if not match:
        return None
    amount, years, rate = _decimal(match.group("amount")), int(match.group("years")), _decimal(match.group("rate"))
    if amount is None or rate is None or not 0 < years <= 100 or not 0 <= rate < 100:
        return None
    currency = match.group("code").upper() if match.group("code") else _CURRENCY_SYMBOLS.get(match.group("symbol") or "")
    factor = (1 + rate / 100) ** years
    value = amount / factor
    result = _success_with_notes(
        ["present_value"],
        [CalculationOutput(name="present_value", value=value, display_value=_money(value, currency), kind="money"),
         CalculationOutput(name="discount_factor", value=1 / factor,
                           display_value=f"{(1 / factor).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)}")],
        [f"Present value = {_money(amount, currency)} ÷ (1 + {rate:f}%)^{years} = {_money(amount, currency)} ÷ "
         f"{factor.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)} = {_money(value, currency)}"],
        [f"Discounted annually at {rate:f}% for {years} whole year(s), the amount received at the end of year {years}."])
    result.inputs = [_supplied("future_amount", amount, currency), _supplied("discount_rate", rate, kind="percentage"),
                     _supplied("years", Decimal(years), kind="years")]
    return result


_CURRENCY_WORDS = {"pound": "GBP", "pounds": "GBP", "sterling": "GBP", "gbp": "GBP", "dollar": "USD", "dollars": "USD",
                   "usd": "USD", "euro": "EUR", "euros": "EUR", "eur": "EUR", "rupee": "INR", "rupees": "INR", "inr": "INR"}
_STATED_FX = re.compile(
    rf"\bconvert\s+(?P<from_symbol>[£$€₹])\s*(?P<amount>{_NUMBER_TEXT})\s+(?:to|into)\s+(?P<to_word>[a-z]+)\b[^.?]*?"
    rf"(?P<one_symbol>[£$€₹])\s*1\s*=\s*(?P<per_symbol>[£$€₹])\s*(?P<rate>{_NUMBER_TEXT})", re.I)


def stated_rate_conversion(query: str) -> CalculationResult | None:
    """A conversion at the exchange rate the user states ("at £1 = $1.25"),
    not a live rate: no lookup, only the arithmetic, in the right direction."""
    match = _STATED_FX.search(query or "")
    if not match:
        return None
    source = _CURRENCY_SYMBOLS[match.group("from_symbol")]
    target = _CURRENCY_WORDS.get(match.group("to_word").lower())
    one, per = _CURRENCY_SYMBOLS[match.group("one_symbol")], _CURRENCY_SYMBOLS[match.group("per_symbol")]
    amount, rate = _decimal(match.group("amount")), _decimal(match.group("rate"))
    if not target or amount is None or not rate or {one, per} != {source, target}:
        return None
    converted = amount / rate if per == source else amount * rate
    operation = "÷" if per == source else "×"
    result = _success_with_notes(
        ["stated_rate_conversion"],
        [CalculationOutput(name="converted_amount", value=converted, display_value=_money(converted, target),
                           kind="money")],
        [f"{_money(amount, source)} {operation} {rate:f} = {_money(converted, target)}"],
        [f"Converted at the stated rate of {match.group('one_symbol')}1 = {match.group('per_symbol')}{rate:f}, "
         "not a live market rate."])
    result.inputs = [_supplied("amount", amount, source), _supplied("exchange_rate", rate, kind="number")]
    return result


def calculate_from_query(query: str) -> CalculationResult:
    """Recognize and execute supported self-contained accounting calculations.

    A missing-input clarification is only returned when the message asks for
    that calculation; when it merely supplies the figure, the request goes on
    to the full answer path instead of being blocked."""
    result = _calculate_from_query(query)
    if (result.status == "clarification_required" and result.error_code == "MISSING_INPUT"
            and result.formula_ids and _supplied_as_value(query or "", result.formula_ids[0])):
        return CalculationResult()
    return result


def _calculate_from_query(query: str) -> CalculationResult:
    """Recognize and execute supported self-contained accounting calculations."""
    # "−20%" (U+2212) was not read as a number, so a rate the user gave — and
    # which is invalid — was reported as missing ("provide the VAT rate").
    q = (query or "").replace("\u2212", "-").replace("\u2013", "-")
    from app.orchestration.calculations.statements import operating_statement
    statement = operating_statement(q)
    if statement is None:
        from app.orchestration.calculations.statements import structured_operating_statement
        statement = structured_operating_statement(q)
    if statement is not None:
        return statement
    accrual = supplied_accrual(q)
    if accrual is not None:
        return accrual
    loan = supplied_loan_payment(q)
    if loan is not None:
        return loan
    for formula in (present_value, stated_rate_conversion):
        found = formula(q)
        if found is not None:
            return found
    from .investigations import supplied_investigation
    investigation = supplied_investigation(q)
    if investigation is not None:
        return investigation
    from .inventory_statement import inventory_statement
    statement = inventory_statement(q)
    if statement is not None:
        return statement
    if (all(re.search(r'\b' + label + r'\b', q, re.I)
            for label in ('opening inventory', 'closing inventory', 'purchases'))
            and not re.search(r'\bFIFO\b|weighted[- ]average', q, re.I)):
        # This is a derived cost-of-sales problem, not a missing COGS input.
        # Unsupported extra adjustments belong to composition, where their
        # relationships can be handled instead of asking for a subtotal.
        return CalculationResult()
    from app.orchestration.websearch import is_pasted_material
    if is_pasted_material(q) and not _CALCULATION_HINT.search(q[:400] + "\n" + q[-400:]):
        # A pasted document's own words ("gross profit $919,000") are not a
        # request: "summarise this in 5 points" was answered with a one-row
        # calculation table (qry-efc27f52ae1c). Only the user's instruction,
        # before or after the material, can ask for a calculation.
        return CalculationResult()
    from app.orchestration.calculations.batches import calculate_numbered_batch, has_numbered_questions
    corrected = corrected_input(q)
    if corrected is not None:
        return corrected
    batch = calculate_numbered_batch(q)
    if batch is not None:
        return batch
    if has_numbered_questions(q):
        # An unsupported batch must never become one calculation using labels
        # borrowed from different questions.
        return CalculationResult()
    for workflow in (bank_reconciliation, periodic_inventory):
        result = workflow(q)
        if result is not None:
            return result
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
    for family in (output_vat_lines, result_change, price_margin_markup, simple_interest, two_period_current_ratio):
        found = family(q)
        if found is not None:
            return found

    # Several questions in one message: labels would be read across all of
    # them (one question's "cost" used in another's formula). Not matched,
    # so the model answers each and every arithmetic line is re-checked.
    subscription_request = bool(re.search(r"\b(?:subscription|plan)\b", q, re.I) and re.search(r"\b(?:monthly|per month)\b", q, re.I) and re.search(r"\b(?:annually|annual|per year)\b", q, re.I))
    if (not _CALCULATION_HINT.search(q) and not subscription_request and not re.search(r"straight[- ]line depreciation", q, re.I)) or asks_several_questions(q):
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

    wants_gross_profit = bool(re.search(r"\bgross profit\b", q, re.I))
    # "What is the gross profit and margin?" got the profit only, labelled
    # fully answered (27 Oct 2026).
    wants_gross_margin = bool(re.search(r"\bgross (?:profit )?margin\b", q, re.I)
                              or re.search(r"\bgross profit\s+(?:and|&|plus)\s+(?:the\s+|its\s+)?(?:gross\s+)?margin\b", q, re.I))
    if (re.search(r'\bsales returns\b',q,re.I)
            and re.search(r'\b(?:operating profit|profit before tax|net sales)\b',q,re.I)):
        # A complete supported statement was attempted above. If its inputs
        # are unsupported/ambiguous, a gross-margin shortcut must not pretend
        # to complete it using gross revenue or ignore the other deliverables.
        return CalculationResult()
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

    # A VAT calculation needs an amount: ten concept questions in one message
    # ("How does VAT work in the UK? … How do businesses calculate corporate
    # income tax?") were asked for a VAT rate.
    if (re.search(r"\bvat\b", q, re.I) and re.search(r"\b(calculate|compute|gross total|vat amount|reverse vat)\b", q, re.I)
            and re.search(r"\d", q)):
        net = _input(q, "net_amount")
        gross = _input(q, "gross_amount")
        rate = _input(q, "vat_rate", kind="percentage", percentage=True) or _vat_rate_at(q)
        inputs = [item for item in (net, gross, rate) if item]
        if not rate:
            return _clarify("vat", inputs, ["vat_rate"])
        if rate.value < 0:
            return CalculationResult(matched=True, status="clarification_required", formula_ids=["vat"], inputs=inputs, error_code="INVALID_PERCENTAGE", message="VAT rate cannot be negative.")
        if not net and not gross:
            # One unlabelled amount whose treatment the user states: "VAT on
            # £2,400 of UK standard-rated sales at 20%, excluding VAT" asked
            # for a "net amount" it had just been given. Never guessed: the
            # amount is net only when said to exclude VAT, gross only when
            # said to include it.
            amounts = list(_MONEY_FIGURE.finditer(q))
            if len(amounts) == 1:
                value = _decimal(amounts[0].group(2))
                currency = _CURRENCY_SYMBOLS.get(amounts[0].group(1))
                if _EXCLUSIVE.search(q) and not _INCLUSIVE.search(q):
                    net = _supplied("net_amount", value, currency)
                elif _INCLUSIVE.search(q) and not _EXCLUSIVE.search(q):
                    gross = _supplied("gross_amount", value, currency)
                inputs = [item for item in (net, gross, rate) if item]
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
        if cost is None and (paid := re.search(
                r"\b(?:cost(?:s|ing)?|purchased\s+for|bought\s+for|purchase\s+price)\s*(?:of|is|was|:)?\s*"
                r"([£$€₹])\s?(\d[\d,]*(?:\.\d+)?)", q, re.I)):
            # "cost $50,000" / "costing $50,000": asked for although supplied.
            cost = _supplied("asset_cost", Decimal(paid.group(2).replace(",", "")), _CURRENCY_SYMBOLS[paid.group(1)])
        residual = _input(q, "residual_value")
        if residual is None and re.search(r"\b(?:no|zero) (?:resale|residual|salvage) value\b", q, re.I):
            residual = _supplied("residual_value", Decimal(0), cost.currency if cost else None)
        life = _input(q, "useful_life", kind="years")
        if life is None and (over := re.search(
                r"\b(?:over|lasts?|(?:useful\s+)?life(?:\s+(?:is|of))?)\s+(\d+(?:\.\d+)?|" + SPELLED_NUMBER_PATTERN + r")[\s-]+years?\b",
                q, re.I)):
            # "…residual value over 5 years" is the useful life; it was asked for.
            # "over eight years" was asked for too: only digits were read.
            raw = over.group(1)
            life = _supplied("useful_life", Decimal(raw) if raw[0].isdigit() else Decimal(spelled_number_to_int(raw)),
                             kind="years")
        inputs = [item for item in (cost, residual, life) if item]
        missing = [name for name, item in (("asset_cost", cost), ("residual_value", residual), ("useful_life", life)) if not item]
        if missing:
            return _clarify("straight_line_depreciation", inputs, missing)
        if life.value <= 0:
            return _undefined("straight_line_depreciation", inputs, "Annual depreciation is undefined because useful life must be greater than zero.")
        if not _same_currency(inputs, q):
            return CalculationResult(matched=True, status="clarification_required", error_code="CURRENCY_MISMATCH", message=_CURRENCY_MISMATCH_MESSAGE)
        if cost.value < 0 or residual.value < 0 or residual.value > cost.value:
            return _clarify("straight_line_depreciation", inputs, ["non-negative cost and residual value not exceeding cost"])
        annual = (cost.value - residual.value) / life.value
        currency = _currency(inputs)
        if currency is None and len(codes := set(re.findall(r"\b(?:GBP|USD|EUR|INR|AED)\b", q, re.I))) == 1:
            currency = next(iter(codes)).upper()
            for item in inputs:
                if item.kind == "money":
                    item.currency = currency
        outputs = [CalculationOutput(name="annual_depreciation", value=annual, display_value=_money(annual, currency), kind="money")]
        steps = [f"Annual depreciation = ({_money(cost.value, currency)} − {_money(residual.value, currency)}) ÷ {life.value:f} = {_money(annual, currency)}"]
        if re.search(r"\bmonthly\b|per month", q, re.I):
            outputs.append(CalculationOutput(name="monthly_depreciation", value=annual/12, display_value=_money(annual/12, currency), kind="money"))
            steps.append(f"Monthly depreciation = {_money(annual, currency)} ÷ 12 = {_money(annual/12, currency)}")
        return _success(["straight_line_depreciation"], inputs, outputs, steps)

    if re.search(r"\bbreak[- ]even\b", q, re.I):
        price = _input(q, "selling_price")
        if price is None and _REVENUE_FORM.search(q) and _input(q, "revenue") is not None:
            # The revenue form — "revenue £2,400,000, variable costs 45% of
            # revenue, fixed costs £780,000 … break-even revenue" — needs no
            # unit price: asked for one, a complete question was answered with
            # "Please provide: selling price, variable cost". Not this formula;
            # the agent calculates it (break-even = fixed ÷ contribution margin).
            return CalculationResult()
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
        revenue = units * price.value
        outputs = [
            CalculationOutput(name="contribution_per_unit", value=contribution, display_value=_money(contribution, currency), kind="money"),
            CalculationOutput(name="break_even_units", value=units, display_value=f"{units.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units", kind="units"),
        ]
        steps = [
            f"Contribution per unit = {_money(price.value, currency)} − {_money(variable.value, currency)} = {_money(contribution, currency)}",
            f"Break-even units = {_money(fixed.value, currency)} ÷ {_money(contribution, currency)} = {units.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units",
        ]
        formulas = ["contribution_per_unit", "break_even_units"]
        # Only when asked ("break-even point in units and revenue"): a
        # "Break-even units?" item in a numbered batch keeps its one answer.
        if re.search(r"\b(?:revenue|sales value|sales revenue|in sales|turnover)\b", q, re.I):
            outputs.append(CalculationOutput(name="break_even_revenue", value=revenue, display_value=_money(revenue, currency), kind="money"))
            steps.append(f"Break-even revenue = {units.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units × {_money(price.value, currency)} = {_money(revenue, currency)}")
            formulas.append("break_even_revenue")
        # "…how many units for an operating profit of £18,000": the target
        # profit was ignored and only the break-even point was returned.
        target = _find_value(q,('target profit','operating profit','desired profit','required profit','profit'))
        if target:
            goal = target[0]
            needed = (fixed.value + goal) / contribution
            inputs.append(_supplied('target_profit',goal,target[1] or currency))
            outputs.append(CalculationOutput(name="units_for_target_profit", value=needed,
                                             display_value=f"{needed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units", kind="units"))
            steps.append(f"Units for {_money(goal, currency)} profit = ({_money(fixed.value, currency)} + {_money(goal, currency)}) ÷ {_money(contribution, currency)} = {needed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f} units")
            formulas.append("target_profit_units")
        capacity = _find_value(q,('maximum annual capacity','annual capacity','capacity'))
        notes = []
        if capacity:
            if capacity[0] < 0:
                return CalculationResult(matched=True,status='clarification_required',error_code='INVALID_CAPACITY',message='Capacity cannot be negative.')
            maximum = capacity[0]*contribution-fixed.value
            whole = units.to_integral_value(rounding='ROUND_CEILING')
            inputs.append(_supplied('capacity',capacity[0],kind='units'))
            outputs += [CalculationOutput(name='break_even_whole_units',value=whole,display_value=f'{whole:f} units',kind='units'),
                        CalculationOutput(name='maximum_profit_at_capacity',value=maximum,display_value=_money(maximum,currency),kind='money')]
            steps.append(f'Maximum operating profit at capacity = {capacity[0]} × {contribution} − {fixed.value} = {_money(maximum,currency)}.')
            notes.append(f'Break-even requires {whole:f} whole units; the unrounded break-even quantity is {units:f}.')
            if target:
                notes.append(('The target is achievable within capacity.' if needed <= capacity[0] else 'The target is not achievable within capacity.') + f' Required units: {needed:f}; available units: {capacity[0]:f}.')
        result = _success(formulas, inputs, outputs, steps)
        result.notes = notes
        return result

    return CalculationResult()


def _label(name: str) -> str:
    """"vat_amount" as "VAT amount": the tax names keep their capitals."""
    text = name.replace("_", " ")
    text = text[:1].upper() + text[1:]
    return re.sub(r"\b(vat|gst|hmrc|eps|uk|us)\b", lambda m: m.group(1).upper(), text, flags=re.I)


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
        if result.formula_ids == ['operating_statement_scenario']:
            values = {item.name: item.display_value for item in result.outputs}
            lines.extend(['| Item | Original | Revised |', '| --- | --- | --- |'])
            for name in ('net_sales', 'gross_profit', 'operating_profit', 'profit_before_tax'):
                lines.append(f'| {_label(name)} | {values["original_" + name]} | {values["revised_" + name]} |')
        else:
            lines.extend(["| Item | Value |", "| --- | --- |"] )
            lines.extend(f"| {_label(item.name)} | {item.display_value} |" for item in result.outputs)
    for table in result.tables:
        lines.append(f"\n### {table['title']}")
        lines.append("| " + " | ".join(table["header"]) + " |")
        lines.append("|" + " --- |" * len(table["header"]))
        lines.extend("| " + " | ".join(row) + " |" for row in table["rows"])
    if result.notes:
        lines.append("\n### Notes")
        lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines)
