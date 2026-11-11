"""The profit bridge of amounts the question states, computed by Kriton.

QA C05 (live run, 11 Nov 2026): "For 2026 assume revenue is $12 million, COGS
$7.2m, operating costs $2.6m, depreciation $0.5m, interest $0.12m and tax
$0.395m; forecast net income." The model listed the inputs and wrote net income
1,185,000, which is right, but six subtractions from the question's amounts are
more than the figure check derives, so the result was removed as unverified
and EBITDA, EBIT and profit before tax were never shown. Computed here, the
steps are in the prompt and in the figure check's evidence.
"""
from __future__ import annotations

import re
from decimal import Decimal

_AMOUNT = (r"(?P<currency>[£$€₹])?\s?(?P<number>\d[\d,]*(?:\.\d+)?)\s?"
           r"(?P<unit>million\b|mn\b|m\b|bn\b|billion\b|k\b|thousand\b|%)?")
# Between a label and its amount: "is", "of", ":", "=", "was", "at", up to a few words.
_GAP = r"[^\d£$€₹;\n]{0,20}?"
_LABELS = {
    "revenue": r"\b(?:revenue|sales|turnover)\b",
    "cost": r"\b(?:cogs|cost\s+of\s+(?:goods\s+sold|sales))\b",
    "operating": r"\b(?:operating\s+(?:costs?|expenses?)|opex|overheads)\b",
    "depreciation": r"\b(?:depreciation(?:\s+and\s+amorti[sz]ation)?|amorti[sz]ation|d&a)\b",
    "interest": r"\b(?:interest(?:\s+expense)?|finance\s+costs?)\b",
    "tax": r"\b(?:income\s+tax|tax(?:\s+expense)?|corporation\s+tax)\b",
}
_SCALE = {"million": Decimal(10**6), "mn": Decimal(10**6), "m": Decimal(10**6), "bn": Decimal(10**9),
          "billion": Decimal(10**9), "k": Decimal(1000), "thousand": Decimal(1000)}
_ASKS_PROFIT = re.compile(r"\b(?:net\s+income|net\s+profit|profit\s+(?:after|before)\s+tax|ebitda|ebit|"
                          r"operating\s+profit|bottom\s+line)\b", re.I)
_FORECAST = re.compile(r"\b(?:forecast|assum\w*|project\w*|budget\w*|plan(?:ned)?|expect\w*)\b", re.I)


def _stated(question: str) -> tuple[dict[str, Decimal], Decimal | None]:
    """{item: amount} for each labelled amount, and the tax rate when the tax is a percentage."""
    amounts: dict[str, Decimal] = {}
    tax_rate = None
    for key, label in _LABELS.items():
        match = re.search(label + _GAP + _AMOUNT, question, re.I)
        if not match:
            continue
        value = Decimal(match.group("number").replace(",", ""))
        unit = (match.group("unit") or "").lower()
        if unit == "%":
            if key == "tax":
                tax_rate = value / 100
            continue
        if unit == "m" and not match.group("currency"):
            continue        # "5 m" without a currency is not money
        amounts[key] = value * _SCALE.get(unit, Decimal(1))
    return amounts, tax_rate


def _fmt(value: Decimal, places: int = 2) -> str:
    text = f"{value:,.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _millions(value: Decimal) -> str:
    return f" ({_fmt(value / 10**6, 3)} million)" if abs(value) >= 10**6 else ""


def verified_profit_bridge_block(question: str) -> str:
    if not question or not _ASKS_PROFIT.search(question):
        return ""
    amounts, tax_rate = _stated(question)
    if not {"revenue", "cost", "operating"} <= amounts.keys():
        return ""
    revenue, cost, operating = amounts["revenue"], amounts["cost"], amounts["operating"]
    gross = revenue - cost
    ebitda = gross - operating
    # Without a depreciation line the subtotal is operating profit, not EBITDA.
    subtotal = "EBITDA" if "depreciation" in amounts else "operating profit"
    steps = [f"- gross profit = revenue {_fmt(revenue)} − cost of goods sold {_fmt(cost)} = {_fmt(gross)}{_millions(gross)}",
             f"- {subtotal} = {_fmt(gross)} − operating costs {_fmt(operating)} = {_fmt(ebitda)}{_millions(ebitda)}"]
    ebit = ebitda
    if "depreciation" in amounts:
        ebit = ebitda - amounts["depreciation"]
        steps.append(f"- EBIT = {_fmt(ebitda)} − depreciation {_fmt(amounts['depreciation'])} = {_fmt(ebit)}{_millions(ebit)}")
    if "interest" in amounts:
        pretax = ebit - amounts["interest"]
        steps.append(f"- profit before tax = {_fmt(ebit)} − interest {_fmt(amounts['interest'])} = "
                     f"{_fmt(pretax)}{_millions(pretax)}")
        tax = amounts.get("tax")
        if tax is None and tax_rate is not None:
            tax = (pretax * tax_rate).quantize(Decimal("0.01"))
            steps.append(f"- tax = {_fmt(pretax)} × {_fmt(tax_rate * 100)}% = {_fmt(tax)}")
        if tax is not None:
            net = pretax - tax
            steps.append(f"- net income = {_fmt(pretax)} − tax {_fmt(tax)} = {_fmt(net)}{_millions(net)}")
    kind = ("a forecast from the question's stated assumptions, not actual results; label it so"
            if _FORECAST.search(question) else "calculated from the question's stated amounts")
    return ("\n\n=== Verified profit bridge computed by Kriton ===\n"
            f"These are exact; {kind}. Show every step with its figures, in the question's currency; do not "
            "recompute.\n" + "\n".join(steps) + "\n")
