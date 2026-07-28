"""
Canonical unit handling for the calculation domain — shared by
formula_registry.py and router.py.

The specific bug this exists to prevent: a caller supplying "15" meaning
15%, another supplying "0.15" meaning the same 15%, and a third supplying
"15%" as a literal string — three different raw values that must resolve to
the exact same internal number before any formula touches them. Every
percentage/rate input is normalized here, once, to a decimal *fraction*
(15% -> Decimal("0.15")) — that is the one canonical internal
representation every formula's compute() function can assume without
re-deriving it.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

# The units this domain supports, per the implementation spec's minimum set.
# "decimal_rate" and "percent" are the same underlying quantity expressed two
# ways on input (0.15 vs 15%) — both normalize to the same internal fraction.
SUPPORTED_UNITS = frozenset({
    "USD", "currency",
    "percent", "decimal_rate",
    "count", "whole_number",
    "years", "months", "duration",
    "monthly_amount", "annual_amount",
    "ratio",
})


class UnitError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _strip_currency_and_commas(raw: str) -> str:
    return raw.strip().replace("$", "").replace(",", "").strip()


def normalize_value(raw_value, unit: str) -> Decimal:
    """Converts a raw (string or numeric) input value + its declared unit
    into the canonical internal Decimal representation. Percent inputs
    divide by 100 here — every formula's compute() function receives an
    already-normalized fraction and must never re-guess whether a bare
    number like 15 means "15" or "0.15"."""
    if unit not in SUPPORTED_UNITS:
        raise UnitError(f"Unsupported unit: {unit!r}. Supported units: {sorted(SUPPORTED_UNITS)}.")

    text = str(raw_value)
    is_percent_literal = text.strip().endswith("%")
    cleaned = _strip_currency_and_commas(text.rstrip("%"))

    try:
        numeric = Decimal(cleaned)
    except InvalidOperation as exc:
        raise UnitError(f"{raw_value!r} is not a valid number for unit {unit!r}.") from exc

    if unit == "percent":
        # A literal "15%" and a bare "15" (declared as unit="percent") both
        # mean the same fifteen-percent — the % sign is cosmetic, the unit
        # declaration is authoritative.
        return numeric / Decimal(100)
    if unit == "decimal_rate":
        if is_percent_literal:
            # Caller declared decimal_rate but wrote "15%" — that is a
            # genuine ambiguity (declared unit and literal syntax disagree),
            # not something to silently resolve either way.
            raise UnitError(
                f"{raw_value!r} has a '%' literal but was declared as unit 'decimal_rate' "
                "(expects a bare fraction like 0.15, not a percent string)."
            )
        return numeric

    return numeric


def format_output(value: Decimal, unit: str) -> Decimal:
    """Converts an internal Decimal back to the unit's natural display
    convention. A rate/percent internal fraction (0.28) becomes 28 for a
    "percent" output unit; every other unit passes through unchanged since
    its internal and display conventions are the same number."""
    if unit == "percent":
        return value * Decimal(100)
    return value
