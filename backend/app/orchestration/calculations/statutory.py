"""Statutory calculations from verified, effective-dated parameters
(registry/tax_parameters.json): UK income tax (England, Northern Ireland and
Wales), UK Class 1 National Insurance (employee and employer), UK take-home
pay, and Indian income tax under the new regime (3 Nov 2026).

Each parameter entry carries the tax year it is in force for and the official
page and line it was read from. The entry is chosen by the tax year the
question names ("2025 to 2026", "2025/26", "FY 2025-26", "AY 2026-27"), else
the one in force today; a year with no verified entry is not calculated (the
question goes to the evidence path), and neither is a case the tables do not
model (Scottish income tax, another National Insurance category, the old
Indian regime). Every result names its source and period."""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.orchestration.calculations.schemas import CalculationInput, CalculationOutput, CalculationResult

PARAMETERS = Path(__file__).resolve().parents[3] / "registry" / "tax_parameters.json"


@lru_cache(maxsize=1)
def _entries() -> tuple[dict, ...]:
    try:
        return tuple(json.loads(PARAMETERS.read_text())["entries"])
    except Exception:  # noqa: BLE001
        return ()


_YEAR_SPAN = re.compile(r"\b((?:19|20)\d{2})\s*(?:to|-|–|/)\s*((?:19|20)?\d{2})\b")
_ASSESSMENT_YEAR = re.compile(r"\bAY\s*((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})\b", re.I)


def _on(entry: dict, day: date) -> bool:
    return date.fromisoformat(entry["period"]["from"]) <= day <= date.fromisoformat(entry["period"]["to"])


def select(country: str, tax: str, query: str, *, today: date | None = None) -> dict | None:
    """The entry for the tax year the query names, else the one in force today."""
    candidates = [e for e in _entries() if e["country"] == country and e["tax"] == tax]
    assessment = _ASSESSMENT_YEAR.search(query or "")
    span = _YEAR_SPAN.search(query or "")
    if assessment:   # AY 2026-27 is the income of FY 2025-26
        start = int(assessment.group(1)) - 1
    elif span:
        start = int(span.group(1))
    elif re.search(r"\b(?:19|20)\d{2}\b", query or ""):
        return None   # a single year is not a tax year: which one is meant is not stated
    else:
        day = today or date.today()
        return next((e for e in candidates if _on(e, day)), None)
    return next((e for e in candidates if date.fromisoformat(e["period"]["from"]).year == start), None)


def _source_note(entry: dict) -> str:
    sources = "; ".join(f"{s['url']} (read {s['read_at'][:10]})" for s in entry["source"])
    return f"Rates and thresholds for {entry['period']['label']}: {sources}."


# ── Reading the request ──────────────────────────────────────────────────────
_GBP = re.compile(r"£\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(k\b)?", re.I)
_INR = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(lakhs?|crores?)?", re.I)
_MONTHLY = re.compile(r"\b(?:a|per|each|every)\s+month\b|\bmonthly\b", re.I)
_SCOTLAND = re.compile(r"\bscot(?:land|tish)\b", re.I)
_SUPPLIED_RATE = re.compile(r"\d+(?:\.\d+)?\s*%")
_INCOME_TAX = re.compile(r"\bincome\s+tax\b|\bpaye\b", re.I)
_NI = re.compile(r"\bnational\s+insurance\b|\bnics?\b", re.I)
_EMPLOYER = re.compile(r"\bemployer'?s?\b|\bsecondary\b", re.I)
_EMPLOYEE = re.compile(r"\bemployee'?s?\b|\bprimary\b|\bmy\s+(?:own\s+)?(?:salary|pay|wages)\b", re.I)
_NET_PAY = re.compile(r"\b(?:take[- ]home|net)\s+pay\b|\bnet\s+salary\b|\bafter\s+tax\b", re.I)
_ASKS = re.compile(r"\b(?:calculate|compute|work\s+out|how\s+much|what\s+(?:is|are|will|would)|estimate)\b", re.I)


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _gbp(query: str) -> tuple[Decimal, bool] | None:
    found = list(_GBP.finditer(query))
    if len(found) != 1:
        return None
    value = _decimal(found[0].group(1)) * (1000 if found[0].group(2) else 1)
    return value, bool(_MONTHLY.search(query))


def _inr(query: str) -> Decimal | None:
    found = list(_INR.finditer(query))
    if len(found) != 1:
        return None
    scale = {"lakh": 100000, "lakhs": 100000, "crore": 10000000, "crores": 10000000}.get((found[0].group(2) or "").lower(), 1)
    return _decimal(found[0].group(1)) * scale


def _money(value: Decimal, symbol: str) -> str:
    return f"{'-' if value < 0 else ''}{symbol}{abs(value.quantize(Decimal('0.01'))):,.2f}"


def _banded(amount: Decimal, bands: list[dict]) -> tuple[Decimal, list[tuple[Decimal, Decimal, Decimal]]]:
    """Tax over bands of the taxable amount: (total, [(slice, rate, tax)])."""
    total, lower, parts = Decimal(0), Decimal(0), []
    for band in bands:
        upper = Decimal(band["upto"]) if band["upto"] is not None else None
        top = amount if upper is None else min(amount, upper)
        if top > lower:
            slice_ = top - lower
            tax = slice_ * Decimal(str(band["rate"])) / 100
            parts.append((slice_, Decimal(str(band["rate"])), tax))
            total += tax
        if upper is None or amount <= upper:
            break
        lower = upper
    return total, parts


# ── UK ───────────────────────────────────────────────────────────────────────
def uk_income_tax(income: Decimal, entry: dict) -> tuple[Decimal, list[str], Decimal]:
    v = entry["values"]
    allowance = Decimal(v["personal_allowance"])
    if income > Decimal(v["taper_from"]):
        allowance = max(Decimal(0), allowance - (income - Decimal(v["taper_from"])) * Decimal(str(v["taper_rate"])))
    taxable = max(Decimal(0), income - allowance)
    tax, parts = _banded(taxable, v["bands"])
    steps = [f"Personal Allowance = {_money(allowance, '£')}" + (" (reduced by £1 for every £2 above £100,000)"
                                                                  if allowance < Decimal(v["personal_allowance"]) else ""),
             f"Taxable income = {_money(income, '£')} − {_money(allowance, '£')} = {_money(taxable, '£')}"]
    steps += [f"{_money(slice_, '£')} at {rate:f}% = {_money(part, '£')}" for slice_, rate, part in parts]
    return tax, steps, allowance


def uk_ni_employee(earnings: Decimal, entry: dict) -> tuple[Decimal, list[str]]:
    v = entry["values"]
    pt, uel = Decimal(v["primary_threshold"]), Decimal(v["upper_earnings_limit"])
    main = max(Decimal(0), min(earnings, uel) - pt) * Decimal(str(v["main_rate"])) / 100
    upper = max(Decimal(0), earnings - uel) * Decimal(str(v["upper_rate"])) / 100
    return main + upper, [f"Employee NI = ({_money(min(earnings, uel), '£')} − {_money(pt, '£')}) × {v['main_rate']}%"
                          + (f" + ({_money(earnings, '£')} − {_money(uel, '£')}) × {v['upper_rate']}%" if earnings > uel else "")
                          + f" = {_money(main + upper, '£')}"]


def uk_ni_employer(earnings: Decimal, entry: dict) -> tuple[Decimal, list[str]]:
    v = entry["values"]
    st = Decimal(v["secondary_threshold"])
    ni = max(Decimal(0), earnings - st) * Decimal(str(v["rate"])) / 100
    return ni, [f"Employer NI = ({_money(earnings, '£')} − {_money(st, '£')}) × {v['rate']}% = {_money(ni, '£')}"]


def _uk(query: str) -> CalculationResult | None:
    wants_tax, wants_ni, wants_net = bool(_INCOME_TAX.search(query)), bool(_NI.search(query)), bool(_NET_PAY.search(query))
    if not (wants_tax or wants_ni or wants_net) or not _ASKS.search(query) or _SCOTLAND.search(query):
        return None
    if _SUPPLIED_RATE.search(query) or re.search(r"\ballowance\s+of\b|\bafter\s+an?\s+£", query, re.I):
        return None   # a supplied rate or allowance is arithmetic on the user's figures (engine "supplied_tax")
    pay = _gbp(query)
    if pay is None:
        return None
    amount, monthly = pay
    annual = amount * 12 if monthly else amount
    outputs, steps, notes, used = [], [], [], []
    if monthly:
        steps.append(f"Annual pay = {_money(amount, '£')} × 12 = {_money(annual, '£')}")
    if wants_tax or wants_net:
        entry = select("UK", "income_tax", query)
        if entry is None:
            return None
        tax, tax_steps, _ = uk_income_tax(annual, entry)
        steps += tax_steps
        outputs.append(CalculationOutput(name="income_tax", value=tax, display_value=_money(tax, "£"), kind="money"))
        used.append(entry)
    employee = employer = None
    if wants_ni or wants_net:
        if wants_net or _EMPLOYEE.search(query) or not _EMPLOYER.search(query):
            entry = select("UK", "ni_employee", query)
            if entry is None:
                return None
            employee, ni_steps = uk_ni_employee(annual, entry)
            steps += ni_steps
            outputs.append(CalculationOutput(name="employee_national_insurance", value=employee,
                                             display_value=_money(employee, "£"), kind="money"))
            used.append(entry)
        if wants_ni and _EMPLOYER.search(query):
            entry = select("UK", "ni_employer", query)
            if entry is None:
                return None
            employer, ni_steps = uk_ni_employer(annual, entry)
            steps += ni_steps
            outputs.append(CalculationOutput(name="employer_national_insurance", value=employer,
                                             display_value=_money(employer, "£"), kind="money"))
            used.append(entry)
    if wants_net:
        tax = next(o.value for o in outputs if o.name == "income_tax")
        net = annual - tax - (employee or Decimal(0))
        steps.append(f"Take-home pay = {_money(annual, '£')} − {_money(tax, '£')} − {_money(employee or Decimal(0), '£')} = {_money(net, '£')}")
        outputs.append(CalculationOutput(name="annual_take_home_pay", value=net, display_value=_money(net, "£"), kind="money"))
        if monthly:
            outputs.append(CalculationOutput(name="monthly_take_home_pay", value=net / 12, display_value=_money(net / 12, "£"), kind="money"))
        notes.append("Take-home pay is after Income Tax and employee National Insurance only: pension contributions, "
                     "student loan, salary sacrifice and benefits in kind are not included.")
    notes.append("England, Northern Ireland and Wales income tax rates; National Insurance category A; the standard "
                 "Personal Allowance (tax code 1257L) with no other income, reliefs or allowances.")
    for label in dict.fromkeys(entry["period"]["label"] for entry in used):
        urls = dict.fromkeys(f"{src['url']} (read {src['read_at'][:10]})" for entry in used
                             if entry["period"]["label"] == label for src in entry["source"])
        notes.append(f"Rates and thresholds for {label}: {'; '.join(urls)}.")
    inputs = [CalculationInput(name="annual_pay", value=annual, display_value=_money(annual, "£"), kind="money", currency="GBP")]
    return CalculationResult(matched=True, status="success", formula_ids=["uk_statutory_pay"], inputs=inputs, outputs=outputs,
                             steps=steps, notes=notes, verification_status="passed",
                             message="Calculated from the official rates and thresholds for the tax year shown.")


# ── India ────────────────────────────────────────────────────────────────────
def _india(query: str) -> CalculationResult | None:
    if not (_INCOME_TAX.search(query) and _ASKS.search(query)) or re.search(r"\bold\s+(?:tax\s+)?regime\b", query, re.I):
        return None
    if not (re.search(r"₹|\bRs\.?\s?\d|\bINR\b|\blakhs?\b|\bindia\b", query, re.I)) or _SUPPLIED_RATE.search(query):
        return None
    income = _inr(query)
    entry = select("INDIA", "income_tax_new_regime", query)
    if income is None or entry is None:
        return None
    tax, parts = _banded(income, entry["values"]["slabs"])
    steps = [f"₹{slice_:,.0f} at {rate:f}% = {_money(part, '₹')}" for slice_, rate, part in parts]
    notes = [f"New tax regime (section 115BAC), the default regime, for an individual under 60; slab tax before any "
             f"rebate, surcharge or cess. The rebate under section 87A and the health and education cess are not applied: "
             f"they were not stated on the source read.",
             _source_note(entry)]
    if income > 5000000:
        notes.append("Surcharge applies above ₹50 lakh (10% to 25% of the tax under the new regime) and is not included.")
    return CalculationResult(matched=True, status="success", formula_ids=["india_income_tax_new_regime"],
                             inputs=[CalculationInput(name="total_income", value=income, display_value=_money(income, "₹"),
                                                      kind="money", currency="INR")],
                             outputs=[CalculationOutput(name="slab_tax", value=tax, display_value=_money(tax, "₹"), kind="money")],
                             steps=steps, notes=notes, verification_status="passed",
                             message="Calculated from the official slabs for the tax year shown.")


def statutory_calculation(query: str) -> CalculationResult | None:
    if re.search(r"₹|\bRs\.?\s?\d|\bINR\b|\blakhs?\b|\bindia\b", query or "", re.I):
        return _india(query or "")
    return _uk(query or "")
