"""
Interactive calculation widget builders — governed calculation architecture,
visual/interactive rendering (2026-07-23, docs/calculation_architecture.md).

Turns a verified FormulaResult into a CalculationWidget (see
orchestration/schemas.py) the frontend can render as live sliders + a chart,
instead of only prose. Deliberately per-formula: a chart's shape (a
depreciation schedule's book-value-over-time curve, say) isn't generic
across all 15 registered formulas — a ratio has no "curve" the same way,
for instance. Only formulas with a real, meaningful chart get a builder
registered here; execute_formula() and the router work identically for
every formula regardless of whether a widget exists for it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from app.domains.calculation.formula_registry import FormulaResult
from app.orchestration.schemas import CalculationWidget, ChartPoint, WidgetInput


def _straight_line_depreciation_widget(result: FormulaResult, raw_inputs: dict) -> CalculationWidget:
    cost = Decimal(raw_inputs["asset_cost"]["value"])
    salvage = Decimal(raw_inputs["salvage_value"]["value"])
    life = Decimal(raw_inputs["useful_life_years"]["value"])
    annual_dep = Decimal(result.output_value)

    points: list[ChartPoint] = []
    year = Decimal(0)
    life_int = int(life)
    for year_index in range(life_int + 1):
        year = Decimal(year_index)
        book_value = cost - annual_dep * year
        if book_value < salvage:
            book_value = salvage
        points.append(ChartPoint(x=str(year_index), y=str(book_value)))

    return CalculationWidget(
        formula_id=result.formula_id,
        formula_name="Straight-line depreciation",
        formula_display="D = (C - S) / L",
        methodology_reference=result.methodology_reference,
        inputs=[
            WidgetInput(
                name="asset_cost", label="Asset cost", value=str(cost), unit="USD",
                min="0", max=str(cost * 4 if cost > 0 else Decimal(100000)), step="1000",
            ),
            WidgetInput(
                name="salvage_value", label="Salvage value", value=str(salvage), unit="USD",
                min="0", max=str(cost), step="500",
            ),
            WidgetInput(
                name="useful_life_years", label="Useful life", value=str(life), unit="years",
                min="1", max="40", step="1",
            ),
        ],
        output_label="Annual depreciation",
        output_value=result.output_value,
        output_unit=result.output_unit,
        chart_label="Book value over time",
        chart_x_label="Years elapsed",
        chart_y_label="Book value ($)",
        chart_points=points,
        calculation_id=result.calculation_id,
    )


_WIDGET_BUILDERS: dict[str, Callable[[FormulaResult, dict], CalculationWidget]] = {
    "accounting.straight_line_depreciation.v1": _straight_line_depreciation_widget,
}


def build_widget(result: FormulaResult, raw_inputs: dict) -> Optional[CalculationWidget]:
    """None when no widget builder is registered for this formula, or when
    the calculation itself didn't verify — a widget must never render an
    unverified/fabricated figure just because sliders would look nice."""
    if result.status != "verified":
        return None
    builder = _WIDGET_BUILDERS.get(result.formula_id)
    if builder is None:
        return None
    return builder(result, raw_inputs)
