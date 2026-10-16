"""Every material figure Kriton shows must come from verified data
(ZL-ENG-AGT-01 §07.5, gate G4).

A figure in an answer is accepted when it equals, allowing for rounding and a
change of unit (thousand, lakh, million …), a number in the evidence: the
question, the conversation and the results of the tools that ran, including
the application calculator. A difference or percentage change between two evidence numbers, and in
prose a direct product or ratio of two, is also accepted, because this module recomputes it
deterministically; nothing here asks a model whether a number is right.

"Material" means a figure a reader would act on: an amount with a currency
sign or code, a percentage or percentage-point change, an amount with a scale
word (million, bn, lakh, crore …) or a comma-grouped number. Years, section
and form numbers ("Section 44AB", "VAT Notice 700"), list markers, dates and
[REF-n] markers are not checked.
"""
from __future__ import annotations

import re

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_SCALES = (1.0, 1e2, 1e3, 1e5, 1e6, 1e7, 1e9, 1e12)
_RUNNING_TOTAL_SPAN = 24
_RUNNING_TOTAL_MAX_NUMBERS = 400
_PAIRWISE_MAX_NUMBERS = 60

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_REF = re.compile(r"\[REF-\d+\]")
_FIGURE = re.compile(
    r"(?<![\w.\-/])"
    r"(?P<currency>[£$€₹¥]\s?|(?:USD|GBP|EUR|INR|AUD|CAD|Rs\.?)\s)?"
    r"(?P<number>-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?![\w/\-]\d)"
    r"(?:\s?(?P<unit>%|pp\b|percentage points?\b|per ?cent\b|bn\b|billion\b|million\b|mn\b|trillion\b|"
    r"lakhs?\b|crores?\b|k\b|m\b))?",
    re.IGNORECASE,
)


def known_values(evidence: str) -> list[float]:
    """Every value the evidence states or directly implies: stated numbers,
    running totals of consecutive numbers, and pairwise differences and
    percentage changes, each at every unit scale."""
    stated = [float(token.replace(",", "")) for token in _NUMBER.findall((evidence or "").replace("−", "-"))]
    running: list[float] = []
    if len(stated) <= _RUNNING_TOTAL_MAX_NUMBERS:
        for start in range(len(stated)):
            total = 0.0
            for value in stated[start:start + _RUNNING_TOTAL_SPAN]:
                total += value
                running.append(total)
    derived: list[float] = []
    if len(stated) <= _PAIRWISE_MAX_NUMBERS:
        for a in stated:
            for b in stated:
                if a != b:
                    derived.append(b - a)
                    if a:
                        derived.append((b - a) / a * 100)
    base = stated + running + derived
    return [value * scale for value in base for scale in _SCALES] + [value / scale for value in base for scale in _SCALES]


def is_known(value: float, known: list[float]) -> bool:
    if value == 0:
        return True
    tolerance = max(abs(value) * 0.002, 0.006)
    # Sign-insensitive: a loss stated as "−5" may be written as a 5 loss.
    return any(abs(abs(value) - abs(k)) <= tolerance for k in known)


def material_figures(text: str) -> list[tuple[str, float]]:
    """(as written, numeric value) for each material figure in prose."""
    prose = _REF.sub(" ", _CODE_FENCE.sub(" ", (text or "").replace("−", "-")))
    figures = []
    for match in _FIGURE.finditer(prose):
        currency, number, unit = match.group("currency"), match.group("number"), match.group("unit")
        unit_word = (unit or "").lower()
        if unit_word == "m" and not currency:
            continue  # "5 m" is metres or minutes unless it is money
        if not (currency or unit or "," in number):
            continue
        figures.append((match.group(0).strip(), float(number.replace(",", ""))))
    return figures


def _stated(evidence: str) -> list[float]:
    return [float(token.replace(",", "")) for token in _NUMBER.findall((evidence or "").replace("−", "-"))]


def _product_or_ratio(value: float, stated: list[float]) -> bool:
    """An amount converted at a rate (10,000 × 1.178), a ratio of two figures
    (120,000 / 1,000,000 = 12.0%), or their sum or difference. Only these
    direct combinations: rescaling them as well would accept almost any
    number by coincidence."""
    if len(stated) > _PAIRWISE_MAX_NUMBERS:
        return False
    tolerance = max(abs(value) * 0.002, 0.006)
    for a in stated:
        for b in stated:
            # a ± b: "£2,260 more than the original" (22,260 − 20,000) was
            # withheld as an unverified figure though both terms were verified.
            candidates = [a * b, a + b, a - b] + ([a / b, a / b * 100] if b else [])
            if any(abs(abs(value) - abs(c)) <= tolerance for c in candidates):
                return True
    return False


def unreconciled_figures(text: str, evidence: str) -> list[str]:
    """Material figures in `text` that no evidence value supports. The made-up
    amounts of a labelled illustrative example are not claims (derived_output.py)."""
    from app.orchestration.derived_output import without_scenarios
    figures = material_figures(without_scenarios(text))
    if not figures:
        return []
    known = known_values(evidence)
    stated = _stated(evidence)
    return list(dict.fromkeys(
        shown for shown, value in figures
        if not is_known(value, known) and not _product_or_ratio(value, stated)
    ))
