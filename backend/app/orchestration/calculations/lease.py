"""Deterministic lessee lease calculations: IFRS 16 and ASC 842.

The 27 Oct 2026 re-test showed lease answers losing their own correct
figures: the model computed £70,919.20 and £3,545.96 for a £20,000, 5%,
4-year lease, and the figure check removed both because nothing traced them
to the user's inputs. Here the present value, the amortisation schedule, the
right-of-use asset, depreciation (or the ASC 842 operating-lease cost), the
journal entries and the cash-flow classification are calculated in exact
decimals from the user's own figures, with every step and assumption shown,
so the release checks can verify them like any other calculator result.

Nothing is invented. The payment, the rate, the term and whether payments
are in advance or in arrears must be stated; without one, the user is asked.
Features this module does not model (residual value guarantees, purchase or
extension options, variable payments) hand the question back to the model
instead of producing a confident wrong number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from app.orchestration.calculations.schemas import CalculationInput, CalculationOutput, CalculationResult
from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, spelled_number_to_int

_CENT = Decimal("0.01")
_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR"}
_FREQUENCY = {"annual": 1, "semi-annual": 2, "quarterly": 4, "monthly": 12}
_PERIOD_NAME = {1: "Year", 2: "Half-year", 4: "Quarter", 12: "Month"}
_MAX_PERIODS = 600


@dataclass(frozen=True)
class LeaseTerms:
    payment: Decimal                 # per period
    currency: str | None
    periods_per_year: int
    years: Decimal
    annual_rate: Decimal             # percent a year
    timing: str                      # "arrears" | "advance"
    framework: str | None = None     # "IFRS 16" | "ASC 842"
    classification: str | None = None   # ASC 842: "finance" | "operating"
    initial_direct_costs: Decimal = Decimal(0)
    incentives: Decimal = Decimal(0)

    @property
    def periods(self) -> int:
        return int(self.years * self.periods_per_year)

    @property
    def period_rate(self) -> Decimal:
        return self.annual_rate / Decimal(100) / self.periods_per_year


@dataclass
class LeaseSchedule:
    liability: Decimal
    rou_asset: Decimal
    rows: list[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]] = field(default_factory=list)
    # (period, opening, payment, interest, principal, closing)


def present_value(terms: LeaseTerms) -> Decimal:
    rate, n = terms.period_rate, terms.periods
    if rate == 0:
        return terms.payment * n
    factor = (1 - (1 + rate) ** -n) / rate
    if terms.timing == "advance":
        factor *= (1 + rate)
    return terms.payment * factor


def schedule(terms: LeaseTerms) -> LeaseSchedule:
    """The effective-interest schedule, unrounded. In arrears interest accrues
    before each payment; in advance each payment is made first."""
    liability = present_value(terms)
    rows, balance, rate = [], liability, terms.period_rate
    for period in range(1, terms.periods + 1):
        opening = balance
        if terms.timing == "advance":
            after_payment = opening - terms.payment
            interest = after_payment * rate
            closing = after_payment + interest
        else:
            interest = opening * rate
            closing = opening + interest - terms.payment
        rows.append((period, opening, terms.payment, interest, terms.payment - interest, closing))
        balance = closing
    rou = liability + terms.initial_direct_costs - terms.incentives
    return LeaseSchedule(liability=liability, rou_asset=rou, rows=rows)


def _money(value: Decimal, currency: str | None) -> str:
    q = value.quantize(_CENT, ROUND_HALF_UP)
    symbol = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}.get(currency or "", f"{currency} " if currency else "")
    return f"{'-' if q < 0 else ''}{symbol}{abs(q):,.2f}"


def _first_year(rows, per_year: int, index: int) -> Decimal:
    return sum((row[index] for row in rows[:per_year]), Decimal(0))


def calculate_lease(terms: LeaseTerms) -> CalculationResult:
    c, per_year = terms.currency, terms.periods_per_year
    plan = schedule(terms)
    label = _PERIOD_NAME[per_year]
    first_interest = _first_year(plan.rows, per_year, 3)
    first_payments = _first_year(plan.rows, per_year, 2)
    first_principal = _first_year(plan.rows, per_year, 4)
    asc_operating = terms.framework == "ASC 842" and terms.classification == "operating"
    total_payments = terms.payment * terms.periods
    inputs = [
        CalculationInput(name="lease_payment", value=terms.payment, display_value=f"{terms.payment:f}", kind="money",
                         currency=c),
        CalculationInput(name="discount_rate", value=terms.annual_rate, display_value=f"{terms.annual_rate:f}",
                         kind="percentage"),
        CalculationInput(name="lease_term", value=terms.years, display_value=f"{terms.years:f}", kind="years"),
    ]
    rate_text = f"{terms.annual_rate:f}% a year" + (f" ({terms.period_rate * 100:.6f}% a period)" if per_year > 1 else "")
    timing_text = "in arrears (end of each period)" if terms.timing == "arrears" else "in advance (start of each period)"
    steps = [
        f"Lease liability = present value of {terms.periods} payments of {_money(terms.payment, c)} {timing_text}, "
        f"discounted at {rate_text} = {_money(plan.liability, c)}",
    ]
    if terms.initial_direct_costs or terms.incentives:
        steps.append(f"Right-of-use asset = {_money(plan.liability, c)} + initial direct costs "
                     f"{_money(terms.initial_direct_costs, c)} − incentives {_money(terms.incentives, c)} = "
                     f"{_money(plan.rou_asset, c)}")
    else:
        steps.append(f"Right-of-use asset = lease liability = {_money(plan.rou_asset, c)} "
                     "(no initial direct costs, incentives or prepayments were stated)")
    steps.append(f"First-year interest = {_money(first_interest, c)} "
                 f"({'opening liability × ' + rate_text if per_year == 1 and terms.timing == 'arrears' else 'sum of the first year’s periods'})")
    outputs = [
        CalculationOutput(name="lease_liability", value=plan.liability, display_value=_money(plan.liability, c), kind="money"),
        CalculationOutput(name="right_of_use_asset", value=plan.rou_asset, display_value=_money(plan.rou_asset, c), kind="money"),
        CalculationOutput(name="first_year_interest", value=first_interest, display_value=_money(first_interest, c), kind="money"),
        CalculationOutput(name="first_year_principal_reduction", value=first_principal,
                          display_value=_money(first_principal, c), kind="money"),
    ]
    notes = [f"Payments {timing_text}, {per_year} a year, for {terms.years:f} years; rate {terms.annual_rate:f}% a year "
             "as stated. Payment timing, term and rate are the user's; nothing else was assumed except as noted."]
    if asc_operating:
        cost = (total_payments + terms.initial_direct_costs - terms.incentives) / terms.years
        amortisation = cost - first_interest
        steps.append(f"ASC 842 operating lease: single straight-line lease cost = ({_money(total_payments, c)} + "
                     f"{_money(terms.initial_direct_costs, c)} − {_money(terms.incentives, c)}) ÷ {terms.years:f} = "
                     f"{_money(cost, c)} a year")
        steps.append(f"First-year right-of-use asset amortisation = lease cost {_money(cost, c)} − interest "
                     f"{_money(first_interest, c)} = {_money(amortisation, c)}")
        outputs.append(CalculationOutput(name="annual_lease_cost", value=cost, display_value=_money(cost, c), kind="money"))
        outputs.append(CalculationOutput(name="first_year_rou_amortisation", value=amortisation,
                                         display_value=_money(amortisation, c), kind="money"))
    else:
        depreciation = plan.rou_asset / terms.years
        steps.append(f"Annual depreciation of the right-of-use asset = {_money(plan.rou_asset, c)} ÷ {terms.years:f} = "
                     f"{_money(depreciation, c)} (straight-line over the lease term)")
        outputs.append(CalculationOutput(name="first_year_depreciation", value=depreciation,
                                         display_value=_money(depreciation, c), kind="money"))
        notes.append("Depreciation is straight-line over the lease term, because no transfer of ownership or "
                     "purchase option was stated; with either, the asset's useful life would be used instead.")
    rows = [[f"{label} {p}", _money(o, c), _money(pay, c), _money(i, c), _money(pr, c), _money(cl, c)]
            for p, o, pay, i, pr, cl in plan.rows]
    notes += _journals(terms, plan, first_interest, first_payments, first_principal, asc_operating)
    notes.append(_cash_flows(terms, asc_operating))
    if terms.framework is None:
        notes.append("The framework (IFRS 16 or ASC 842) was not stated. The liability, interest and schedule are the "
                     "same under both; the expense pattern and cash-flow classification differ, so confirm which applies.")
    return CalculationResult(
        matched=True, status="success", formula_ids=["lease_liability", "lease_schedule"], inputs=inputs,
        outputs=outputs, steps=steps, verification_status="passed", notes=notes,
        message="Calculation completed using values supplied directly by the user.",
        tables=[{"title": "Lease liability schedule",
                 "header": [label, "Opening liability", "Payment", "Interest", "Principal", "Closing liability"],
                 "rows": rows}],
    )


def _journals(terms, plan, interest, payments, principal, asc_operating) -> list[str]:
    c = terms.currency
    lines = [f"Journal at commencement: Dr Right-of-use asset {_money(plan.rou_asset, c)}; "
             f"Cr Lease liability {_money(plan.liability, c)}"
             + (f"; Cr Cash (initial direct costs) {_money(terms.initial_direct_costs, c)}" if terms.initial_direct_costs else "")
             + (f"; Dr Cash (incentives received) {_money(terms.incentives, c)}" if terms.incentives else "") + "."]
    if asc_operating:
        lines.append(f"First year (ASC 842 operating): Dr Lease cost; Cr Lease liability {_money(interest, c)} "
                     f"(accretion) and Cr Right-of-use asset (amortisation); Dr Lease liability {_money(payments, c)}; "
                     f"Cr Cash {_money(payments, c)}.")
    else:
        lines.append(f"First year: Dr Interest expense {_money(interest, c)}; Cr Lease liability {_money(interest, c)}. "
                     f"Dr Lease liability {_money(payments, c)}; Cr Cash {_money(payments, c)}. "
                     f"Dr Depreciation expense {_money(plan.rou_asset / terms.years, c)}; "
                     f"Cr Accumulated depreciation – right-of-use asset {_money(plan.rou_asset / terms.years, c)}.")
    return lines


def _cash_flows(terms, asc_operating) -> str:
    if terms.framework == "ASC 842":
        if asc_operating:
            return "Cash flows (ASC 842 operating lease): lease payments are operating activities."
        return ("Cash flows (ASC 842 finance lease): the principal portion is a financing activity; the interest "
                "portion is an operating activity.")
    if terms.framework == "IFRS 16":
        return ("Cash flows (IFRS 16 with IAS 7): the principal portion is a financing activity; interest is classified "
                "under the entity's IAS 7 policy (operating or financing). Only short-term, low-value and variable "
                "payments not in the lease liability are operating.")
    return ("Cash flows: under IFRS 16 the principal portion is financing and interest follows the IAS 7 policy; under "
            "ASC 842 a finance lease's principal is financing and interest operating, and an operating lease's "
            "payments are all operating.")


# ── reading a lease from the user's words ─────────────────────────────────────

_MONEY = r"(?P<sym>[£$€₹])\s?(?P<amount>\d[\d,]*(?:\.\d+)?)"
_LEASE_WORD = re.compile(r"\blease[sd]?\b|\bright[- ]of[- ]use\b|\bROU\b|\bIFRS\s?16\b|\bASC\s?842\b", re.I)
# A question, a request verb, or a numbered list of deliverables ("1. Initial
# ROU asset … 2. 2026 interest expense …").
_ASKS = re.compile(r"\?|\b(?:calculate|compute|work\s+out|determine|prepare|show|record|measure|what\s+(?:is|are)|"
                   r"how\s+much|give|draft|account(?:ing)?\s+for)\b|(?:^|\s)1[.)]\s+\S[^\n]*\s2[.)]\s", re.I)
_UNMODELLED = re.compile(r"\b(?:residual\s+value\s+guarantee|purchase\s+option|extension\s+option|renewal\s+option|"
                         r"termination\s+option|variable\s+(?:lease\s+)?payments?|index(?:ed)?\s+to|CPI|"
                         r"sale\s+and\s+leaseback|sublease|modification|remeasure)\b", re.I)
_NUM = rf"(?:\d+(?:\.\d+)?|{SPELLED_NUMBER_PATTERN})"


def _number(text: str) -> Decimal:
    return Decimal(text) if text[0].isdigit() else Decimal(spelled_number_to_int(text))


def read_lease(text: str) -> tuple[LeaseTerms | None, list[str]]:
    """The lease the text states, or the inputs still missing."""
    t = text or ""
    payment = re.search(rf"\b(?P<freq>annual|yearly|quarterly|monthly|semi-annual|half-yearly)?\s*(?:lease\s+)?"
                        rf"(?:payments?|rentals?|rent)\s+(?:of\s+|are\s+|is\s+)?{_MONEY}", t, re.I) \
        or re.search(rf"{_MONEY}\s*(?P<freq2>a\s+year|per\s+year|per\s+annum|annually|a\s+quarter|per\s+quarter|"
                     rf"quarterly|a\s+month|per\s+month|monthly)", t, re.I)
    # "discount rate 6%", "at 6%", "a 6% discount rate", "6% incremental borrowing rate".
    rate = re.search(rf"\b(?:discount|interest|borrowing|implicit)\s+rate\s*(?:of|is|was|at|=|:)?\s*(?P<rate>\d+(?:\.\d+)?)\s*%"
                     rf"|\b(?:at|using)\s+(?:a\s+)?(?P<rate2>\d+(?:\.\d+)?)\s*%"
                     rf"|\b(?P<rate3>\d+(?:\.\d+)?)\s*%\s+(?:\w+\s+){{0,2}}?(?:discount|interest|borrowing|implicit)\s+rate\b"
                     rf"|\brate\s+implicit\s+in\s+the\s+lease\s*(?:is|was|of|=|:)?\s*(?P<rate4>\d+(?:\.\d+)?)\s*%",
                     t, re.I)
    term = re.search(rf"\b(?:lease\s+)?term\s*(?:of|is|was|:)?\s*(?P<n>{_NUM})[\s-]+years?\b"
                     rf"|\bfor\s+(?P<n2>{_NUM})\s+years?\b|\b(?P<n3>{_NUM})[\s-]+year\s+(?:lease|term)\b", t, re.I)
    missing = []
    if not payment:
        missing.append("the lease payment amount and how often it is paid")
    if not rate:
        missing.append("the discount rate (the rate implicit in the lease or the incremental borrowing rate)")
    if not term:
        missing.append("the lease term")
    arrears = re.search(r"\bin\s+arrears\b|\bend\s+of\s+(?:each|every|the)\b", t, re.I)
    advance = re.search(r"\bin\s+advance\b|\b(?:start|beginning)\s+of\s+(?:each|every|the)\b|\bdue\s+(?:on|at)\s+commencement\b", t, re.I)
    if bool(arrears) == bool(advance):
        missing.append("whether payments are made in advance (start of each period) or in arrears (end of each period)")
    if missing:
        return None, missing
    freq_word = (payment.groupdict().get("freq") or payment.groupdict().get("freq2") or "annual").lower()
    per_year = 4 if "quarter" in freq_word else 12 if "month" in freq_word else 2 if ("semi" in freq_word or "half" in freq_word) else 1
    framework = "IFRS 16" if re.search(r"\bIFRS\s?16\b", t, re.I) else (
        "ASC 842" if re.search(r"\bASC\s?842\b|\bUS\s+GAAP\b", t, re.I) else None)
    classification = ("operating" if re.search(r"\boperating\s+lease\b", t, re.I)
                      else "finance" if re.search(r"\bfinance\s+lease\b", t, re.I) else None)
    idc = re.search(rf"\binitial\s+direct\s+costs?\s*(?:of|are|were|:)?\s*{_MONEY}", t, re.I)
    incentive = re.search(rf"\b(?:lease\s+)?incentives?\s*(?:received\s*)?(?:of|are|were|:)?\s*{_MONEY}", t, re.I)
    years = _number(next(g for g in term.groups() if g))
    terms = LeaseTerms(
        payment=Decimal(payment.group("amount").replace(",", "")), currency=_SYMBOLS[payment.group("sym")],
        periods_per_year=per_year, years=years,
        annual_rate=Decimal(rate.group("rate") or rate.group("rate2") or rate.group("rate3") or rate.group("rate4")),
        timing="arrears" if arrears else "advance", framework=framework,
        classification=classification if framework == "ASC 842" else None,
        initial_direct_costs=Decimal(idc.group("amount").replace(",", "")) if idc else Decimal(0),
        incentives=Decimal(incentive.group("amount").replace(",", "")) if incentive else Decimal(0),
    )
    return terms, []


_WANTS_LEASE_FIGURES = re.compile(
    r"\blease\s+liabilit|\bright[- ]of[- ]use\b|\bROU\b|\bpresent\s+value\b|\b(?:amortis|amortiz)ation\s+schedule\b|"
    r"\bschedule\b|\binterest\b|\bdepreciation\b|\bjournal|\baccounting\b|\bcash\s+flows?\b|\bmeasure", re.I)


def lease_calculation(query: str, context: str = "") -> CalculationResult | None:
    """A lessee lease calculation for a request about a lease, from the
    request and the user's earlier lease messages (`context`). None when the
    message is not a lease calculation request, or names a feature this module
    does not model (left to the model, whose figures are still checked)."""
    q = query or ""
    if not (_LEASE_WORD.search(q) or _LEASE_WORD.search(context)) or not _ASKS.search(q) or not _WANTS_LEASE_FIGURES.search(q):
        return None
    if not _LEASE_WORD.search(q) and not re.search(r"\b(?:that|this|the)\s+lease\b", q, re.I):
        return None
    # The request's own figures are read first; earlier lease messages only
    # supply what it does not state.
    text = f"{q}\n{context}" if context else q
    # "with no renewal options" says the feature is absent.
    if any(not re.search(r"\b(?:no|without|not\s+any|excluding)\s+(?:\w+\s+){0,2}$", text[:m.start()], re.I)
           for m in _UNMODELLED.finditer(text)):
        return None
    # Two leases in one message are not read as one: "£10,000 a year at 5% for
    # 3 years … We lease a van: £8,000 in arrears …" was calculated with the
    # van's "in arrears", a timing never stated for the £10,000 lease (28 Oct 2026).
    several = leases_in_message(q)
    if len(several) > 1:
        options = "; ".join(f"({i}) {text.strip()[:110]}" for i, text in enumerate(several, 1))
        return CalculationResult(
            matched=True, status="clarification_required", formula_ids=["lease_liability"],
            error_code="AMBIGUOUS_REFERENCE",
            message=f"Your message describes more than one lease: {options}. Which one should I calculate? "
                    "Sending each lease as its own message keeps their terms apart.")
    terms, missing = read_lease(_latest_corrections(text))
    if missing:
        if not re.search(r"[£$€₹]\s?\d|\d\s*%", text):
            return None                  # a conceptual lease question, not a calculation
        return CalculationResult(
            matched=True, status="clarification_required", formula_ids=["lease_liability"], error_code="MISSING_INPUT",
            message="To calculate the lease I need: " + "; ".join(f"({i}) {item}" for i, item in enumerate(missing, 1))
                    + ". I won't assume them.")
    if not (0 < terms.periods <= _MAX_PERIODS) or terms.payment <= 0 or not (0 <= terms.annual_rate < 100):
        return CalculationResult(matched=True, status="clarification_required", formula_ids=["lease_liability"],
                                 error_code="INVALID_INPUT",
                                 message="The lease payment, term or rate is outside a range I can calculate. "
                                         "Please check: payment above zero, a whole number of periods, rate 0–100%.")
    result = calculate_lease(terms)
    note = _stated_present_value_note(text, terms)
    if note:
        result.notes.insert(0, note)
    return result


_STATED_PV = re.compile(rf"\bpresent\s+value\s+of\s+(?:the\s+)?(?:remaining\s+)?(?P<count>\d+\s+)?(?:\w+\s+){{0,2}}?"
                        rf"payments?\b[^.\n£$€₹]{{0,40}}?\b(?:is|of|=|:)\s*{_MONEY}", re.I)


def _stated_present_value_note(text: str, terms: LeaseTerms) -> str | None:
    """A present value the user stated that disagrees with the one the rate
    gives. "The present value of the remaining 4 annuity payments at 8% is
    $298,991" is $298,091.42 at 8%: the calculation is shown from the rate,
    and the difference is named rather than either figure silently used."""
    stated = _STATED_PV.search(text or "")
    if not stated:
        return None
    value = Decimal(stated.group("amount").replace(",", ""))
    remaining = int(stated.group("count") or 0) or (terms.periods - 1 if terms.timing == "advance" else terms.periods)
    rate = terms.period_rate
    computed = terms.payment * ((1 - (1 + rate) ** -remaining) / rate if rate else Decimal(remaining))
    if abs(computed - value) <= Decimal(1):
        return None
    return (f"Check the stated present value: you gave {_money(value, terms.currency)} for the remaining {remaining} "
            f"payments, but {remaining} payments of {_money(terms.payment, terms.currency)} at "
            f"{terms.annual_rate:f}% a year are worth {_money(computed, terms.currency)}. The figures below use the "
            "rate; confirm which is right.")


def _latest_corrections(text: str) -> str:
    """A later "the lease term is 5 years, not 4" replaces the earlier term:
    the corrected value is read first."""
    corrections = [line for line in text.splitlines()
                   if re.search(r"\bnot\s+\d|\bcorrect(?:ion|ed)?\b|\binstead\b|\bactually\b", line, re.I)]
    return "\n".join(reversed(corrections)) + "\n" + text if corrections else text


_PAYMENT_STATED = (re.compile(rf"(?:payments?|rentals?|rent)\s+(?:of\s+|are\s+|is\s+)?{_MONEY}", re.I),
                   re.compile(rf"{_MONEY}\s*(?:a|per)\s+(?:year|annum|quarter|month)", re.I))


def distinct_leases(messages: list[str]) -> list[str]:
    """The user's messages that each set out a different lease (a lease with
    its own payment), oldest first. A correction ("the lease term is 5 years,
    not 4") sets out none."""
    found: dict[str, str] = {}
    for text in messages:
        payment = _PAYMENT_STATED[0].search(text or "") or _PAYMENT_STATED[1].search(text or "")
        if payment and _LEASE_WORD.search(text):
            found.setdefault(payment.group("amount").replace(",", ""), text)
    return list(found.values())


_OWN_TERMS = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d+[\s-]+(?:years?|months?|quarters?)\b|\bin\s+(?:arrears|advance)\b", re.I)


def leases_in_message(text: str) -> list[str]:
    """The sentences of one message that each set out a lease with its own
    payment and terms (a rate, a term or the payment timing), one per
    distinct payment. "Total payments of £150,000" beside a single lease
    states no terms of its own and is not counted."""
    found: dict[str, str] = {}
    for sentence in re.split(r"(?<=[.;!?])\s+|\n+", text or ""):
        payment = _PAYMENT_STATED[0].search(sentence) or _PAYMENT_STATED[1].search(sentence)
        if payment and _OWN_TERMS.search(sentence):
            found.setdefault(payment.group("amount").replace(",", ""), sentence)
    return list(found.values())
