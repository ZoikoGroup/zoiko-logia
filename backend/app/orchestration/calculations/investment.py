"""Earnings per share, and NPV / IRR / payback from a stated cash-flow list
(3 Nov 2026). Only what the request states unambiguously is calculated:
an initial outlay (year 0) and the listed later flows (years 1, 2, …), and
for NPV a discount rate. Anything else returns None, and the input
requirements ask for what is missing (clarification_requirements.py)."""
from __future__ import annotations

import re
from decimal import Decimal, getcontext

from app.orchestration.calculations.schemas import CalculationInput, CalculationOutput, CalculationResult

getcontext().prec = 40
_AMOUNT = r"(?P<sym>[£$€₹])?\s?(?P<num>\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(?P<scale>k|m|million)?\b"
_SYMBOLS = {"£": "£", "$": "$", "€": "€", "₹": "₹"}


def _value(match: re.Match) -> Decimal:
    scale = {"k": 1000, "m": 1000000, "million": 1000000}.get((match.group("scale") or "").lower(), 1)
    return Decimal(match.group("num").replace(",", "")) * scale


def _money(value: Decimal, symbol: str) -> str:
    return f"{'-' if value < 0 else ''}{symbol}{abs(value.quantize(Decimal('0.01'))):,.2f}"


# ── Earnings per share ───────────────────────────────────────────────────────
_EPS = re.compile(r"\b(?:eps|earnings\s+per\s+share)\b", re.I)
_PROFIT = re.compile(r"\b(?:net\s+(?:profit|income|earnings)|profit\s+(?:after\s+tax|for\s+the\s+year|attributable[^.£$€₹\d]{0,60})|earnings)\b"
                     r"[^.£$€₹\d]{0,30}?(?:of|is|was|=|:)?\s*" + _AMOUNT, re.I)
_SHARES = re.compile(r"(?P<num>\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(?P<scale>m|million)?\s+(?:weighted\s+average\s+)?(?:ordinary\s+)?shares\b", re.I)
_PREFERENCE = re.compile(r"\bpreference\s+dividends?\b[^.£$€₹\d]{0,20}(?:of|is|was|=|:)?\s*" + _AMOUNT, re.I)


def earnings_per_share(query: str) -> CalculationResult | None:
    if not _EPS.search(query or ""):
        return None
    profit, shares = _PROFIT.search(query), list(_SHARES.finditer(query))
    if not profit or len(shares) != 1:
        return None
    symbol = _SYMBOLS.get(profit.group("sym") or "", "")
    earnings = _value(profit)
    preference = _PREFERENCE.search(query)
    deduction = _value(preference) if preference else Decimal(0)
    count = Decimal(shares[0].group("num").replace(",", "")) * (1000000 if shares[0].group("scale") else 1)
    if count <= 0:
        return None
    eps = (earnings - deduction) / count
    steps = [f"EPS = ({_money(earnings, symbol)}" + (f" − {_money(deduction, symbol)} preference dividends" if deduction else "")
             + f") ÷ {count:,.0f} shares = {symbol}{eps.quantize(Decimal('0.0001')):f}"]
    return CalculationResult(
        matched=True, status="success", formula_ids=["basic_eps"], verification_status="passed", steps=steps,
        inputs=[CalculationInput(name="earnings", value=earnings, display_value=_money(earnings, symbol), kind="money"),
                CalculationInput(name="shares", value=count, display_value=f"{count:,.0f}", kind="units")],
        outputs=[CalculationOutput(name="basic_eps", value=eps, display_value=f"{symbol}{eps.quantize(Decimal('0.01')):f}", kind="money")],
        notes=["Basic EPS (IAS 33 / ASC 260): profit attributable to ordinary shareholders over the weighted average "
               "number of ordinary shares stated; dilution is not considered unless stated."],
        message="Calculation completed using values supplied directly by the user.")


# ── NPV / IRR / payback ──────────────────────────────────────────────────────
_INVESTMENT_ASK = re.compile(r"\b(?:npv|net\s+present\s+value|irr|internal\s+rate\s+of\s+return|payback(?:\s+period)?)\b", re.I)
_OUTLAY = re.compile(r"\b(?:initial\s+(?:investment|outlay|cost)|(?:costs?|invest(?:s|ment)?)\s+(?:of\s+)?(?=[£$€₹]))\s*(?:of|is|=|:)?\s*" + _AMOUNT, re.I)
_FLOWS = re.compile(r"\b(?:annual\s+)?(?:net\s+)?(?:cash\s*(?:in)?flows?|inflows?|returns?|receipts?|savings)\b(?:\s+(?:of|are|will\s+be|:))?"
                    r"(?P<list>(?:[\s,;and]*[£$€₹]?\s?\d(?:[\d,]*\d)?(?:\.\d+)?\s*(?:k|m|million)?\b)+)", re.I)
_YEAR_FLOW = re.compile(r"\byear\s+(?P<year>\d{1,2})\s*[:=]?\s*(?P<neg>[-−(])?\s*" + _AMOUNT, re.I)
_RATE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")
_EACH = re.compile(r"\b(?:each\s+year|per\s+year|a\s+year|annually)\s+for\s+(\d{1,2})\s+years\b|\bfor\s+(\d{1,2})\s+years\b", re.I)


def _flows(query: str) -> tuple[list[Decimal], str] | None:
    """[year 0, year 1, …] as stated, or None."""
    years = list(_YEAR_FLOW.finditer(query))
    if len(years) >= 2:
        flows = {}
        for match in years:
            value = _value(match) * (-1 if match.group("neg") else 1)
            flows[int(match.group("year"))] = value
        if sorted(flows) != list(range(len(flows))) or flows[0] >= 0:
            return None
        symbol = next((_SYMBOLS[m.group("sym")] for m in years if m.group("sym")), "")
        return [flows[i] for i in range(len(flows))], symbol
    outlay, listed = _OUTLAY.search(query), _FLOWS.search(query)
    if not outlay or not listed:
        return None
    values = [m for m in re.finditer(_AMOUNT, listed.group("list"))]
    later = [_value(m) for m in values]
    repeat = _EACH.search(query)
    if len(later) == 1 and repeat:
        later = later * int(repeat.group(1) or repeat.group(2))
    if not later:
        return None
    symbol = _SYMBOLS.get(outlay.group("sym") or "", "") or next((_SYMBOLS[m.group("sym")] for m in values if m.group("sym")), "")
    return [-_value(outlay), *later], symbol


def _npv(rate: Decimal, flows: list[Decimal]) -> Decimal:
    return sum(flow / (1 + rate) ** t for t, flow in enumerate(flows))


def _irr(flows: list[Decimal]) -> Decimal | None:
    low, high = Decimal("-0.99"), Decimal("10")
    if _npv(low, flows) * _npv(high, flows) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        if _npv(low, flows) * _npv(mid, flows) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def investment_appraisal(query: str) -> CalculationResult | None:
    if not _INVESTMENT_ASK.search(query or ""):
        return None
    parsed = _flows(query)
    if parsed is None:
        return None
    flows, symbol = parsed
    wants_npv = bool(re.search(r"\bnpv\b|\bnet\s+present\s+value\b", query, re.I))
    wants_irr = bool(re.search(r"\birr\b|\binternal\s+rate\s+of\s+return\b", query, re.I))
    wants_payback = bool(re.search(r"\bpayback\b", query, re.I))
    rates = [m for m in _RATE.finditer(query)]
    if wants_npv and len(rates) != 1:
        return None   # the discount rate is missing or ambiguous: asked for, not assumed
    outputs, steps = [], [f"Cash flows: " + "; ".join(f"year {t} {_money(f, symbol)}" for t, f in enumerate(flows))]
    inputs = [CalculationInput(name=f"cash_flow_year_{t}", value=f, display_value=_money(f, symbol), kind="money")
              for t, f in enumerate(flows)]
    if wants_npv:
        rate = Decimal(rates[0].group(1)) / 100
        value = _npv(rate, flows)
        inputs.append(CalculationInput(name="discount_rate", value=rate * 100, display_value=f"{rates[0].group(1)}%", kind="percentage"))
        steps.append("NPV = " + " + ".join(f"{_money(f, symbol)} ÷ (1 + {rates[0].group(1)}%)^{t}" for t, f in enumerate(flows))
                     + f" = {_money(value, symbol)}")
        outputs.append(CalculationOutput(name="npv", value=value, display_value=_money(value, symbol), kind="money"))
    if wants_irr:
        irr = _irr(flows)
        if irr is None:
            return None
        steps.append(f"IRR: the rate at which NPV = 0, found by bisection = {(irr * 100).quantize(Decimal('0.01'))}%")
        outputs.append(CalculationOutput(name="irr", value=irr * 100, display_value=f"{(irr * 100).quantize(Decimal('0.01'))}%", kind="percentage"))
    if wants_payback:
        remaining, years = -flows[0], None
        for t, flow in enumerate(flows[1:], start=1):
            if flow >= remaining:
                years = Decimal(t - 1) + remaining / flow
                break
            remaining -= flow
        if years is not None:
            steps.append(f"Payback = {years.quantize(Decimal('0.01'))} years (cash flows assumed even within each year)")
            outputs.append(CalculationOutput(name="payback_years", value=years, display_value=f"{years.quantize(Decimal('0.01'))} years", kind="number"))
    if not outputs:
        return None
    return CalculationResult(matched=True, status="success", formula_ids=["investment_appraisal"], inputs=inputs,
                             outputs=outputs, steps=steps, verification_status="passed",
                             notes=["Year-0 outlay and year-end cash flows as stated; no tax, inflation or terminal value "
                                    "is added unless stated."],
                             message="Calculation completed using values supplied directly by the user.")
