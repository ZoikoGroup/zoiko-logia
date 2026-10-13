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


def calculate_from_query(query: str) -> CalculationResult:
    """Recognize and execute supported self-contained accounting calculations."""
    q = query or ""
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
    return "\n".join(lines)
