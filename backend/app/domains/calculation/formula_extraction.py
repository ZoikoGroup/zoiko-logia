"""
Query-parsing helpers for extracting named-formula inputs from raw query
text — same fail-closed contract as household_extraction.py and
arithmetic_extraction.py: a query this module can't confidently resolve to
a complete, unambiguous input set returns None, never a guess or a
partially-filled default.

Deliberately narrow, one function per formula, added incrementally as real
query shapes are found — the same growth pattern as every other pattern
bank in this codebase (prescreen.py, risk_classifier.py,
arithmetic_extraction.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass(frozen=True)
class NamedFormulaExtraction:
    calculation_type: str
    inputs: dict


@dataclass(frozen=True)
class MissingFormulaInputs:
    calculation_type: str
    missing_inputs: tuple[str, ...]

# 2026-07-29 real incident: "Calculate straight-line annual depreciation for
# an asset costing $120,000..." never matched — "line" and "depreciation"
# had to be directly adjacent, so the single inserted word "annual" broke
# the match entirely. That silently routed the query into the generic
# depreciation fallback further down (which claims ALL FOUR inputs are
# missing regardless of what's actually in the query, since it does no
# per-field checking), rather than the correct, precise extraction path
# below — even though asset_cost and useful_life_years were both present
# and cleanly extractable. Tolerates one adjective ("annual"/"yearly"/
# "monthly"/etc.) between "line" and "depreciation" without becoming
# permissive enough to match unrelated phrasing.
_DEPRECIATION_TRIGGER_PATTERN = re.compile(r"straight[\s-]*line(?:\s+\w+)?\s+depreciation", re.IGNORECASE)
_ASSET_COST_PATTERN = re.compile(
    r"(?:\$\s?([\d,]+(?:\.\d+)?)\s*asset|"
    r"asset(?:\s+costing|\s+cost(?:\s+of)?)?\s*\$\s?([\d,]+(?:\.\d+)?))",
    re.IGNORECASE,
)
_USEFUL_LIFE_PATTERN = re.compile(
    r"(?:"
    r"(\d+)[\s-]*year(?:s)?\s+(?:useful\s+)?life"
    r"|(?:useful\s+)?life\s+(?:of\s+)?(\d+)[\s-]*year(?:s)?"
    r"|(?:over|for)\s+(?:a\s+period\s+of\s+)?(\d+)[\s-]*year(?:s)?\b"
    r")",
    re.IGNORECASE,
)
# "residual value" is the same 2026-07-29 incident as the trigger fix above
# — a real query used it as a synonym for "salvage value" (both name the
# same input: the asset's expected value at the end of its useful life,
# per US GAAP ASC 360 / IFRS IAS 16) and it wasn't recognized at all,
# contributing to the same false "missing input" result.
_NO_SALVAGE_PATTERN = re.compile(r"no\s+(?:salvage|residual)\s+value", re.IGNORECASE)
_SALVAGE_VALUE_PATTERN = re.compile(
    r"(?:(?:salvage|residual)\s+value\s+(?:of\s+)?\$\s?([\d,]+(?:\.\d+)?)|"
    r"\$\s?([\d,]+(?:\.\d+)?)\s+(?:salvage|residual)\s+value)",
    re.IGNORECASE,
)
# The trigger phrase alone also matches a purely definitional question like
# "What is straight-line depreciation?" — that query has no calculation
# intent at all and should get an educational answer, not a "provide your
# asset cost" prompt. Require either an explicit calculation verb or at
# least one partially-supplied input before treating the query as a
# calculation-with-missing-inputs case.
_DEPRECIATION_CALCULATION_INTENT_PATTERN = re.compile(
    r"\b(calculate|compute|determine|figure\s+out|work\s+out)\b", re.IGNORECASE
)

_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
}


def _normalize_number_words(query: str) -> str:
    return re.sub(
        r"\b(" + "|".join(_NUMBER_WORDS) + r")[\s-]+year\b",
        lambda match: f"{_NUMBER_WORDS[match.group(1).lower()]}-year",
        query,
        flags=re.IGNORECASE,
    )


# Real gap (2026-08-06): "Our revenue grew from twelve thousand to fifteen
# thousand five hundred this quarter — what's the percentage increase?"
# matched the percentage_change trigger below but every _labeled_number
# lookup requires digits — _NUMBER_WORDS above only ever normalizes a
# number-word immediately before "year" (depreciation's own narrow use
# case), so a genuine input figure spelled out in prose was invisible to
# this whole module and the calculation silently never ran. Deliberately a
# SEPARATE, self-contained normalizer (not a cross-domain import of
# reference_data/user_provided_data.py's near-identical one) — this
# module's own docstring establishes it as an independent pattern bank,
# same as arithmetic_extraction.py/prescreen.py/risk_classifier.py.
_SPELLED_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_SPELLED_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_SPELLED_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_SPELLED_NUMBER_WORD = r"(?:" + "|".join(
    sorted(list(_SPELLED_ONES) + list(_SPELLED_TENS) + list(_SPELLED_SCALES), key=len, reverse=True)
) + r")"
_SPELLED_NUMBER_PHRASE = re.compile(rf"\b{_SPELLED_NUMBER_WORD}(?:[-\s]{_SPELLED_NUMBER_WORD})+\b", re.IGNORECASE)


def _spelled_number_to_value(phrase: str) -> int:
    total = 0
    current = 0
    for token in re.split(r"[\s-]+", phrase.strip().lower()):
        if not token:
            continue
        if token in _SPELLED_ONES:
            current += _SPELLED_ONES[token]
        elif token in _SPELLED_TENS:
            current += _SPELLED_TENS[token]
        elif token == "hundred":
            current = (current or 1) * 100
        elif token in _SPELLED_SCALES:
            total += (current or 1) * _SPELLED_SCALES[token]
            current = 0
    return total + current


def _normalize_spelled_out_numbers(query: str) -> str:
    return _SPELLED_NUMBER_PHRASE.sub(lambda m: str(_spelled_number_to_value(m.group(0))), query)


def _has_depreciation_calculation_intent(query: str) -> bool:
    if _DEPRECIATION_CALCULATION_INTENT_PATTERN.search(query):
        return True
    return bool(
        _ASSET_COST_PATTERN.search(query)
        or _USEFUL_LIFE_PATTERN.search(query)
        or _NO_SALVAGE_PATTERN.search(query)
        or _SALVAGE_VALUE_PATTERN.search(query)
    )


def _clean_decimal(raw: str) -> Optional[str]:
    cleaned = raw.replace(",", "")
    try:
        Decimal(cleaned)
    except InvalidOperation:
        return None
    return cleaned


def _captured_number(match: re.Match) -> Optional[str]:
    return next((group for group in match.groups() if group is not None), None)


def extract_straight_line_depreciation_inputs(query: str) -> Optional[dict]:
    """Returns a formula_registry.execute_formula()-ready inputs dict for
    "accounting.straight_line_depreciation.v1", or None. Requires the
    trigger phrase, an explicit "$X asset" cost, and an explicit "N-year
    useful life" — a query missing either never gets a guessed value.
    Salvage value defaults to 0 only for the literal phrase "no salvage
    value"; any other salvage phrasing must state the figure explicitly or
    this returns None rather than assuming zero."""
    query = _normalize_number_words(query)
    if not _DEPRECIATION_TRIGGER_PATTERN.search(query):
        return None

    cost_match = _ASSET_COST_PATTERN.search(query)
    life_match = _USEFUL_LIFE_PATTERN.search(query)
    if not cost_match or not life_match:
        return None

    raw_cost = _captured_number(cost_match)
    cost = _clean_decimal(raw_cost) if raw_cost else None
    raw_life = _captured_number(life_match)
    life = _clean_decimal(raw_life) if raw_life else None
    if not cost or not life:
        return None

    if _NO_SALVAGE_PATTERN.search(query):
        salvage = "0"
    else:
        salvage_match = _SALVAGE_VALUE_PATTERN.search(query)
        if not salvage_match:
            return None
        raw_salvage = _captured_number(salvage_match)
        salvage = _clean_decimal(raw_salvage) if raw_salvage else None
        if not salvage:
            return None

    return {
        "asset_cost": {"value": cost, "unit": "USD"},
        "salvage_value": {"value": salvage, "unit": "USD"},
        "useful_life_years": {"value": life, "unit": "years"},
    }


def _labeled_number(query: str, labels: tuple[str, ...], *, unit: str) -> Optional[dict]:
    label_pattern = "|".join(re.escape(label).replace(r"\ ", r"[\s_-]+") for label in labels)
    # Accepts the spelled-out word too — "5 percent"/"5 percentage" reads as
    # naturally as "5%" but only the literal "%" sign was recognized before.
    suffix = r"\s*(?:%|percent(?:age)?)" if unit == "percent" else ""
    # Live bug: "[\d,]+" is satisfied by a bare comma alone (no digit
    # required) — for "$150,000 assets, $40,000 inventory" the forward
    # pattern "matched" on "assets," by capturing just that trailing comma
    # as the "number", which then failed to parse as a Decimal and returned
    # None — without ever falling through to the correct reverse pattern
    # ("$150,000 assets"), since a match (however bogus) short-circuits that
    # fallback. Requiring the capture to start with an actual digit fixes
    # both the false match here and, by construction, every other formula
    # routed through this same shared helper.
    match = re.search(
        rf"\b(?:{label_pattern})\b\s*(?:is|are|was|were|of|=|:|at)?\s*\$?\s*(\d[\d,]*(?:\.\d+)?){suffix}",
        query,
        re.IGNORECASE,
    )
    if not match:
        # "$400,000 in sales" / "$250,000 of cost of goods sold" — the
        # forward pattern already tolerated a connector word between label
        # and number ("is|are|of|=|:|at"), but this reverse (number-first)
        # pattern required the label immediately after with no connector at
        # all, so "in"/"of" between the number and the label fell through.
        match = re.search(
            rf"\$?\s*(\d[\d,]*(?:\.\d+)?){suffix}\s*(?:in|of)?\s*(?:{label_pattern})\b",
            query,
            re.IGNORECASE,
        )
    if not match:
        return None
    value = _clean_decimal(match.group(1))
    return {"value": value, "unit": unit} if value is not None else None


_FORMULA_SPECS = (
    (r"\bworking\s+capital\b", "working_capital", {
        "current_assets": (("current assets",), "USD"),
        "current_liabilities": (("current liabilities",), "USD"),
    }),
    (r"\bnet\s+(?:profit|income)\b", "net_profit", {
        "revenue": (("revenue", "sales"), "USD"),
        "total_expenses": (("total expenses", "expenses"), "USD"),
    }),
    (r"\bgross\s+profit\b", "gross_profit", {
        "revenue": (("revenue", "sales"), "USD"),
        "cost_of_goods_sold": (("cost of goods sold", "cost of sales", "cogs"), "USD"),
    }),
    (r"\bprofit\s+margin\b|\bnet\s+margin\b", "profit_margin", {
        "profit": (("profit", "net profit"), "USD"),
        "revenue": (("revenue", "sales"), "USD"),
    }),
    (r"\bpercentage\s+(?:increase|change)\b", "percentage_change", {
        "starting_value": (("from", "starting value", "old value"), "USD"),
        "ending_value": (("to", "ending value", "new value"), "USD"),
    }),
    (r"\b(?:budget\s+)?variance\b", "budget_variance", {
        "budget": (("budget",), "USD"),
        "actual": (("actual spending", "actual"), "USD"),
    }),
    (r"\bgross\s+margin\b", "gross_margin", {
        "revenue": (("revenue", "sales"), "USD"),
        "cost_of_goods_sold": (("cost of goods sold", "cogs"), "USD"),
    }),
    (r"\boperating\s+profit\b", "operating_profit", {
        "revenue": (("revenue", "sales"), "USD"),
        "cost_of_goods_sold": (("cost of goods sold", "cogs"), "USD"),
        "operating_expenses": (("operating expenses",), "USD"),
    }),
    (r"\boperating\s+margin\b", "operating_margin", {
        "revenue": (("revenue", "sales"), "USD"),
        "cost_of_goods_sold": (("cost of goods sold", "cogs"), "USD"),
        "operating_expenses": (("operating expenses",), "USD"),
    }),
    # "assets"/"liabilities" alone (no repeated "current") are listed as
    # fallback aliases — live bug: "current ratio for $150,000 assets and
    # $80,000 liabilities" drops the redundant "current" the second and
    # third time, a normal English ellipsis, but the extractor required the
    # literal two-word phrase "current assets"/"current liabilities" next to
    # every number and returned nothing. Safe to alias broadly only here,
    # scoped to formulas already gated behind their own "current/quick
    # ratio" trigger match above.
    (r"\bcurrent\s+ratio\b", "current_ratio", {
        "current_assets": (("current assets", "assets"), "USD"),
        "current_liabilities": (("current liabilities", "liabilities"), "USD"),
    }),
    (r"\bquick\s+ratio\b|\bacid[\s-]+test\b", "quick_ratio", {
        "current_assets": (("current assets", "assets"), "USD"),
        "inventory": (("inventory",), "USD"),
        "current_liabilities": (("current liabilities", "liabilities"), "USD"),
    }),
    (r"\bdebt[\s-]+to[\s-]+equity\b", "debt_to_equity", {
        "total_liabilities": (("total liabilities", "liabilities"), "USD"),
        "total_equity": (("total equity", "equity"), "USD"),
    }),
    (r"\b(?:calculate|compute|determine|what\s+is)\b.*\bequity\b|\bequity\b.*\bassets?\b.*\bliabilit", "owners_equity", {
        "total_assets": (("total assets", "assets"), "USD"),
        "total_liabilities": (("total liabilities", "liabilities"), "USD"),
    }),
    (r"\binventory\s+turnover\b", "inventory_turnover", {
        "cost_of_goods_sold": (("cost of goods sold", "cogs"), "USD"),
        "average_inventory": (("average inventory",), "USD"),
    }),
    (r"\b(?:receivables|collection)\s+days\b", "receivables_days", {
        "average_receivables": (("average receivables",), "USD"),
        "credit_revenue": (("credit revenue", "credit sales"), "USD"),
        "days_in_period": (("days in period", "days"), "count"),
    }),
    (r"\beffective\s+tax\s+rate\b", "effective_tax_rate", {
        "total_tax_expense": (("total tax expense", "tax expense"), "USD"),
        "pretax_income": (("pretax income", "pre-tax income"), "USD"),
    }),
    (r"\btaxable\s+income\s+scenario\b", "taxable_income_scenario", {
        "gross_income": (("gross income",), "USD"),
        "adjustments": (("adjustments",), "USD"),
        "deductions": (("deductions",), "USD"),
    }),
    (r"\b(?:user[\s-]+supplied|supplied|given)\s+rate\b|\btaxable\s+(?:base|income)\b.*%", "tax_from_supplied_rate", {
        "taxable_base": (("taxable base", "taxable income"), "USD"),
        "user_supplied_rate": (("user supplied rate", "supplied rate", "tax rate", "rate"), "percent"),
    }),
    (r"\bbreak[\s-]+even\b", "break_even_point", {
        "fixed_costs": (("fixed costs",), "USD"),
        "price_per_unit": (("price per unit",), "USD"),
        "variable_cost_per_unit": (("variable cost per unit",), "USD"),
    }),
    # "interest on" is listed as a principal alias — "Simple interest on
    # $10,000 at 5% for 3 years" never says the word "principal" at all; the
    # figure right after "interest on" is positionally the principal in this
    # formula's own phrasing, so it's a safe, unambiguous alias rather than a
    # generic fallback.
    (r"\bsimple\s+interest\b", "simple_interest", {
        "principal": (("principal", "interest on"), "USD"),
        "annual_rate": (("annual rate", "rate"), "percent"),
        "time_years": (("time years", "years"), "years"),
    }),
    (r"\bcompound\s+interest\b", "compound_interest", {
        "principal": (("principal", "interest on"), "USD"),
        "annual_rate": (("annual rate", "rate"), "percent"),
        "time_years": (("time years", "years"), "years"),
        "compounding_periods_per_year": (
            ("compounding periods per year", "compounding periods", "times per year", "times a year"), "count",
        ),
    }),
    # Live bug: the trigger required the literal contiguous phrase "loan
    # payment" — "What is the monthly payment for a loan..." says the same
    # thing in the opposite word order and matched nothing. The two
    # proximity alternatives catch "payment ... loan" and "loan ... payment"
    # within a few words either way without matching unrelated "loan"/
    # "payment" mentions elsewhere in a longer answer.
    (
        r"\b(?:monthly\s+)?loan\s+payment\b|"
        r"\bpayment\b(?:\W+\w+){0,4}\W+\bloan\b|"
        r"\bloan\b(?:\W+\w+){0,4}\W+\bpayment\b",
        "loan_payment",
        {
            "principal": (("principal",), "USD"),
            "annual_rate": (("annual rate", "rate"), "percent"),
            "number_of_payments": (("number of payments", "payments"), "count"),
        },
    ),
    (r"\b(?:overall\s+)?materiality\b", "materiality", {
        "benchmark_amount": (("benchmark amount", "benchmark"), "USD"),
        "user_selected_percentage": (("user selected percentage", "selected percentage", "percentage"), "percent"),
    }),
    (r"\bprojected\s+misstatement\b", "projected_misstatement", {
        "sample_misstatement": (("sample misstatement",), "USD"),
        "sample_book_value": (("sample book value",), "USD"),
        "population_book_value": (("population book value",), "USD"),
    }),
    (r"\bsampling\s+interval\b", "sampling_interval", {
        "tolerable_misstatement": (("tolerable misstatement",), "USD"),
        "sample_size": (("sample size",), "count"),
    }),
    (r"\baudit\s+sample\s+size\b|\battribute\s+sample\s+size\b", "attribute_sample_size", {
        "reliability_factor": (("reliability factor",), "ratio"),
        "tolerable_deviation_rate": (("tolerable deviation rate",), "percent"),
        "expected_deviation_rate": (("expected deviation rate",), "percent"),
    }),
)


def extract_named_formula(query: str) -> Optional[NamedFormulaExtraction]:
    query = _normalize_number_words(_normalize_spelled_out_numbers(query))
    depreciation = extract_straight_line_depreciation_inputs(query)
    if depreciation is not None:
        return NamedFormulaExtraction("straight_line_depreciation", depreciation)
    if re.search(r"\bworking[\s-]+capital\b", query, re.I):
        asset_parts = [_labeled_number(query, (label,), unit="USD") for label in ("cash", "receivables", "inventory")]
        liability_parts = [_labeled_number(query, (label,), unit="USD") for label in ("payables", "other current liabilities")]
        if all(asset_parts) and all(liability_parts):
            current_assets = sum(Decimal(part["value"]) for part in asset_parts if part)
            current_liabilities = sum(Decimal(part["value"]) for part in liability_parts if part)
            return NamedFormulaExtraction("working_capital", {
                "current_assets": {"value": str(current_assets), "unit": "USD"},
                "current_liabilities": {"value": str(current_liabilities), "unit": "USD"},
            })
    for trigger, calculation_type, input_specs in _FORMULA_SPECS:
        if not re.search(trigger, query, re.IGNORECASE):
            continue
        inputs = {}
        for name, (labels, unit) in input_specs.items():
            extracted = _labeled_number(query, labels, unit=unit)
            if extracted is None:
                return None
            inputs[name] = extracted
        return NamedFormulaExtraction(calculation_type, inputs)
    return None


def identify_missing_formula_inputs(query: str) -> Optional[MissingFormulaInputs]:
    """Identify a named calculation with incomplete inputs without guessing."""
    query = _normalize_number_words(_normalize_spelled_out_numbers(query))
    if extract_named_formula(query) is not None:
        return None
    if (
        _DEPRECIATION_TRIGGER_PATTERN.search(query)
        and _has_depreciation_calculation_intent(query)
        and extract_straight_line_depreciation_inputs(query) is None
    ):
        missing = []
        if not _ASSET_COST_PATTERN.search(query):
            missing.append("asset_cost")
        if not _USEFUL_LIFE_PATTERN.search(query):
            missing.append("useful_life_years")
        if not (_NO_SALVAGE_PATTERN.search(query) or _SALVAGE_VALUE_PATTERN.search(query)):
            missing.append("salvage_value_or_explicit_no_salvage")
        return MissingFormulaInputs("straight_line_depreciation", tuple(missing))
    if re.search(r"\b(?:calculate|compute|work\s+out)\b.*\b(?:my\s+)?depreciation\b", query, re.I):
        return MissingFormulaInputs(
            "depreciation",
            ("depreciation_method", "asset_cost", "salvage_value", "useful_life_years"),
        )
    if not re.search(r"\b(?:calculate|compute|determine|work\s+out|figure\s+out)\b", query, re.I):
        return None
    for trigger, calculation_type, input_specs in _FORMULA_SPECS:
        if not re.search(trigger, query, re.IGNORECASE):
            continue
        missing = tuple(
            name for name, (labels, unit) in input_specs.items()
            if _labeled_number(query, labels, unit=unit) is None
        )
        return MissingFormulaInputs(calculation_type, missing) if missing else None
    return None
