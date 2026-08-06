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


_INPUT_LABELS = {
    "current_assets": "Current assets", "current_liabilities": "Current liabilities",
    "inventory": "Inventory", "revenue": "Revenue", "cost_of_goods_sold": "Cost of goods sold",
    "total_assets": "Total assets", "total_liabilities": "Total liabilities",
    "total_equity": "Total equity", "total_expenses": "Total expenses",
    "operating_expenses": "Operating expenses", "total_tax_expense": "Tax expense",
    "pretax_income": "Pretax income", "average_inventory": "Average inventory",
    "average_receivables": "Average receivables", "credit_revenue": "Credit revenue",
    "days_in_period": "Days in period",
    "profit": "Profit", "starting_value": "Starting value", "ending_value": "Ending value",
    "budget": "Budget", "actual": "Actual",
}

_COMPARISON_WIDGETS = {
    "accounting.working_capital.v1": ("Working capital", "WC = CA - CL", "Working-capital bridge", "waterfall"),
    "accounting.gross_profit.v1": ("Gross profit", "GP = Revenue - COGS", "Revenue to gross-profit bridge", "waterfall"),
    "accounting.gross_margin.v1": ("Gross margin", "GM = (Revenue - COGS) / Revenue", "Revenue composition", "donut"),
    "finance.current_ratio.v1": ("Current ratio", "CR = Current assets / Current liabilities", "Liquidity ratio", "gauge"),
    "finance.quick_ratio.v1": ("Quick ratio", "QR = (Current assets - Inventory) / Current liabilities", "Quick-asset composition", "stacked_bar"),
    "accounting.owners_equity.v1": ("Owners' equity", "Equity = Assets - Liabilities", "Asset financing structure", "treemap"),
    "finance.debt_to_equity.v1": ("Debt-to-equity ratio", "D/E = Liabilities / Equity", "Capital structure", "donut"),
    "accounting.net_profit.v1": ("Net profit", "NP = Revenue - Total expenses", "Revenue allocation", "sankey"),
    "accounting.profit_margin.v1": ("Profit margin", "Margin = Profit / Revenue", "Profitability", "gauge"),
    "finance.percentage_change.v1": ("Percentage change", "Change = (End - Start) / |Start|", "Period change", "gauge"),
    "accounting.budget_variance.v1": ("Budget variance", "Variance = Actual - Budget", "Budget performance", "bullet"),
    "accounting.operating_profit.v1": ("Operating profit", "OP = Revenue - COGS - Operating expenses", "Operating-profit bridge", "waterfall"),
    "accounting.operating_margin.v1": ("Operating margin", "OM = Operating profit / Revenue", "Operating performance", "donut"),
    "tax.effective_tax_rate.v1": ("Effective tax rate", "ETR = Tax expense / Pretax income", "Effective tax rate", "gauge"),
    "accounting.inventory_turnover.v1": ("Inventory turnover", "Turnover = COGS / Average inventory", "Inventory efficiency", "gauge"),
    "accounting.receivables_days.v1": ("Receivables days", "Days = Average receivables / Credit revenue × period days", "Collection cycle", "gauge"),
    "audit.materiality.v1": ("Audit materiality", "Materiality = Benchmark × Percentage", "Governed materiality result", "kpi"),
    "audit.projected_misstatement.v1": ("Projected misstatement", "Projection = Sample misstatement / Sample amount × Population", "Projected audit difference", "bullet"),
    "audit.sampling_interval.v1": ("Sampling interval", "Interval = Population / Sample size", "Audit sampling interval", "kpi"),
    "audit.attribute_sample_size.v1": ("Attribute sample size", "n = Reliability / (Tolerable rate - Expected rate)", "Audit sample requirement", "kpi"),
    # Live gap: these three verified formulas had no widget builder at all,
    # so their answers rendered as plain text + calculation steps with no
    # chart — unlike every other governed formula. "kpi" is the safest fit:
    # each result is one headline figure (a monthly payment, a total
    # interest amount), not a composition/bridge that needs multi-point
    # chart_points — and the frontend's "kpi" chart_type only ever displays
    # output_value directly, so it's correct regardless of how the
    # mixed-unit inputs (dollars, percent, years, a payment count) would
    # otherwise plot together.
    "finance.simple_interest.v1": ("Simple interest", "I = Principal x Rate x Time", "Verified simple-interest result", "kpi"),
    "finance.compound_interest.v1": ("Compound interest", "I = Principal x [(1 + Rate/n)^(n x Time) - 1]", "Verified compound-interest result", "kpi"),
    "finance.loan_payment.v1": ("Loan payment", "P x [r(1+r)^n] / [(1+r)^n - 1]", "Verified monthly loan payment", "kpi"),
}


def _comparison_widget(result: FormulaResult, raw_inputs: dict) -> CalculationWidget:
    name, display, chart_label, chart_type = _COMPARISON_WIDGETS[result.formula_id]
    inputs: list[WidgetInput] = []
    values: dict[str, Decimal] = {}
    for input_name in result.inputs:
        raw = raw_inputs[input_name]
        value = Decimal(str(raw["value"]).replace(",", ""))
        unit = raw.get("unit", "USD")
        label = _INPUT_LABELS.get(input_name, input_name.replace("_", " ").title())
        maximum = value * Decimal(4) if value > 0 else Decimal(100000)
        step = max(Decimal(1), maximum / Decimal(200))
        inputs.append(WidgetInput(
            name=input_name, label=label, value=str(value), unit=unit,
            min="0", max=str(maximum), step=str(step),
        ))
        values[input_name] = value
    output = Decimal(result.output_value)
    if chart_type == "gauge":
        points = [ChartPoint(x=name, y=str(output))]
    elif result.formula_id == "finance.quick_ratio.v1":
        quick_assets = values["current_assets"] - values["inventory"]
        points = [
            ChartPoint(x="Quick assets", y=str(quick_assets)),
            ChartPoint(x="Inventory", y=str(values["inventory"])),
            ChartPoint(x="Current liabilities", y=str(values["current_liabilities"])),
        ]
    elif result.formula_id == "accounting.gross_margin.v1":
        gross_profit = values["revenue"] - values["cost_of_goods_sold"]
        points = [ChartPoint(x="COGS", y=str(values["cost_of_goods_sold"])), ChartPoint(x="Gross profit", y=str(gross_profit))]
    elif result.formula_id == "finance.debt_to_equity.v1":
        points = [ChartPoint(x="Liabilities", y=str(values["total_liabilities"])), ChartPoint(x="Equity", y=str(values["total_equity"]))]
    elif result.formula_id == "accounting.owners_equity.v1":
        points = [ChartPoint(x="Liabilities", y=str(values["total_liabilities"])), ChartPoint(x="Equity", y=str(output))]
    elif result.formula_id == "accounting.net_profit.v1":
        points = [ChartPoint(x="Revenue", y=str(values["revenue"])), ChartPoint(x="Expenses", y=str(values["total_expenses"])), ChartPoint(x="Net profit", y=str(output))]
    elif result.formula_id == "accounting.operating_margin.v1":
        operating_profit = values["revenue"] - values["cost_of_goods_sold"] - values["operating_expenses"]
        points = [ChartPoint(x="Operating costs", y=str(values["cost_of_goods_sold"] + values["operating_expenses"])), ChartPoint(x="Operating profit", y=str(operating_profit))]
    else:
        labels = {key: _INPUT_LABELS.get(key, key.replace("_", " ").title()) for key in values}
        points = [ChartPoint(x=labels[key], y=str(value)) for key, value in values.items()]
        points.append(ChartPoint(x=name, y=str(output)))
    return CalculationWidget(
        formula_id=result.formula_id, formula_name=name, formula_display=display,
        methodology_reference=result.methodology_reference, inputs=inputs,
        output_label=name, output_value=result.output_value, output_unit=result.output_unit,
        chart_type=chart_type, chart_label=chart_label, chart_x_label="", chart_y_label="Amount ($)",
        chart_points=points, calculation_id=result.calculation_id,
    )


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
    **{formula_id: _comparison_widget for formula_id in _COMPARISON_WIDGETS},
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
