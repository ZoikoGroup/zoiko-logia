from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP

from app.domains.calculations.schemas import CalculationOperation


def execute(operation: CalculationOperation, values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("At least one numeric input is required")
    try:
        if operation == "sum":
            return sum(values, Decimal("0"))
        if operation in {"difference", "variance"}:
            _require(values, 2)
            return values[0] - values[1]
        if operation == "percentage":
            _require(values, 2)
            return values[0] / values[1] * Decimal("100")
        if operation == "percentage_change":
            _require(values, 2)
            return (values[1] - values[0]) / values[0] * Decimal("100")
        if operation == "straight_line_depreciation":
            _require(values, 3)
            return (values[0] - values[1]) / values[2]
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError("The calculation cannot divide by zero") from exc
    raise ValueError(f"Unsupported calculation operation: {operation}")


def quantize(value: Decimal, scale: int = 2) -> Decimal:
    quantum = Decimal(1).scaleb(-scale)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _require(values: list[Decimal], count: int) -> None:
    if len(values) != count:
        raise ValueError(f"This operation requires exactly {count} inputs")
