"""
Explicit, named rounding policies for the calculation domain. Every
CalculationRecord/FormulaResult stores which policy was applied — a number
without a stated rounding policy is not fully auditable, since "$70,000"
could be an exact result or a rounded one and a reader can't tell which
without this.

Never rounds intermediate values — only the final output of a computation,
and only when the caller explicitly names a policy. The default,
"none", performs no rounding at all.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

ROUNDING_POLICIES = frozenset({
    "none",
    "two_decimal_places",
    "whole_currency_unit",
    "percentage_two_decimal_places",
    "bankers_rounding",
    "round_half_up",
})


class RoundingError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def round_value(value: Decimal, policy: str) -> Decimal:
    if policy not in ROUNDING_POLICIES:
        raise RoundingError(f"Unknown rounding policy: {policy!r}. Supported: {sorted(ROUNDING_POLICIES)}.")

    if policy == "none":
        return value
    if policy in ("two_decimal_places", "percentage_two_decimal_places"):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if policy == "whole_currency_unit":
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if policy == "bankers_rounding":
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if policy == "round_half_up":
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    # Unreachable given the membership check above; kept for exhaustiveness.
    raise RoundingError(f"Unhandled rounding policy: {policy!r}")
