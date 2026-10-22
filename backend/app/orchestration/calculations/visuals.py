"""Validated charts made only from deterministic calculation values."""
import re

from app.orchestration.calculations.schemas import CalculationResult
from app.orchestration.response_planner import detect_explicit_visual_request
from app.orchestration.visualization.spec import (
    DonutSlice, EncodingField, VisualizationDataPoint, VisualizationEncoding, VisualizationSpec, NamedSeries,
)
from app.orchestration.visualization.validator import VisualizationValidator


def calculation_visual(result: CalculationResult, query: str, spec_id: str):
    if result.status != "success" or result.verification_status != "passed":
        return None, []
    from app.orchestration.chart_intent import allows_automatic_chart
    if not allows_automatic_chart(query) or re.search(r"\b(?:only|just)\s+(?:a\s+)?(?:table|text)\b|\b(?:table|text)\s+only\b", query, re.I):
        return None, []
    explicit = detect_explicit_visual_request(query)
    # A comparison of validated scenarios benefits from aligned grouped bars.
    # Do not infer a time series from unrelated accounting subtotals.
    comparison = bool(re.search(r"\b(?:compare|comparison|differences?|side by side)\b", query, re.I))
    if not explicit and not comparison:
        return None, []
    values = {item.name: item.value for item in result.outputs}
    currency = next((item.currency for item in result.inputs if item.currency), None)
    if explicit and re.search(r"\bwaterfall\b", query, re.I):
        # The renderer already supports signed delta bars. Build a bridge only
        # when its components reconcile exactly to a verified subtotal.
        combined = {item.name: item.value for item in [*result.inputs, *result.outputs]}
        prefix = "current_" if "current_net_sales" in combined else ""
        revenue = combined.get(prefix + "net_sales", combined.get("revenue"))
        cost = combined.get(prefix + "cost_of_goods_sold", combined.get("cost_of_sales"))
        expenses = combined.get(prefix + "operating_expenses")
        operating = combined.get(prefix + "operating_profit")
        if all(v is not None for v in (revenue, cost, expenses, operating)) and revenue-cost-expenses == operating:
            steps = [("Net sales", revenue), ("Cost of goods sold", -cost), ("Operating expenses", -expenses)]
            final = combined.get(prefix + "profit_before_tax")
            if final is not None:
                steps.append(("Finance costs", -(operating-final)))
            spec = VisualizationSpec(
                id=spec_id, type="BAR", variant="WATERFALL_CHART", family="STATISTICAL", renderer="RECHARTS",
                title="Revenue to profit", unit=currency,
                summary="Signed movements bridge net sales to " + ("profit before tax." if final is not None else "operating profit."),
                encoding=VisualizationEncoding(x=EncodingField(field="component", type="nominal"),
                    y=EncodingField(field="movement", type="quantitative", unit=currency)),
                data=[VisualizationDataPoint(x=label, y=float(value)) for label, value in steps],
            )
            if VisualizationValidator().validate(spec).passed:
                return spec, []
        return None, ["A waterfall needs reconciling components on one basis. The supplied results do not establish that bridge; the calculation table is available."]
    groups = {}
    for item in result.outputs:
        match = re.fullmatch(r"(original|revised|current|previous|fifo|weighted_average)_(.+)", item.name)
        if match and item.kind == "money" and item.value is not None:
            groups.setdefault(match[1], {})[match[2]] = item.value
    paired = next((pair for pair in (("original", "revised"), ("previous", "current"), ("fifo", "weighted_average"))
                   if all(key in groups for key in pair)), None)
    if paired and not re.search(r"\b(?:pie|donut|scatter|waterfall|stacked)\b", query, re.I):
        metrics = [key for key in ("gross_profit", "operating_profit", "profit_before_tax", "cost_of_goods_sold", "closing_inventory")
                   if all(key in groups[group] for group in paired)]
        if len(metrics) >= 2:
            spec = VisualizationSpec(
                id=spec_id, type="GROUPED_BAR", variant="GROUPED_BAR_CHART",
                family="COMPARISON", renderer="RECHARTS", unit=currency,
                title="Inventory valuation comparison" if paired[0] == "fifo" else "Profit comparison",
                summary="Compare validated measures across the supplied periods, scenarios or valuation methods. The groups are not stacked or added together.",
                series=[NamedSeries(name=group.replace("_", " ").title(), data=[VisualizationDataPoint(
                    x=metric.replace("_", " ").title(), y=float(groups[group][metric])) for metric in metrics]) for group in paired],
            )
            if VisualizationValidator().validate(spec).passed:
                return spec, []
    if not explicit:
        return None, []
    if re.search(r"\b(?:pie|donut)\b", query, re.I):
        revenue = next((item.value for item in result.inputs if item.name == "revenue"), None)
        expenses = next((item.value for item in result.inputs if item.name == "expenses"), None)
        profit = values.get("profit")
        if revenue and expenses is not None and profit is not None and expenses >= 0 and profit >= 0 and expenses + profit == revenue:
            spec = VisualizationSpec(
                id=spec_id, type="DONUT", family="COMPOSITION", renderer="ECHARTS",
                title="Expenses and profit as shares of revenue", unit="%",
                summary="Revenue is split into expenses and profit using the supplied figures.",
                donut=[DonutSlice(label="Expenses", value=float(expenses/revenue*100), is_estimated=False),
                       DonutSlice(label="Profit", value=float(profit/revenue*100), is_estimated=False)],
            )
            if VisualizationValidator().validate(spec).passed:
                return spec, []
        return None, ["A pie chart needs non-negative parts of one total. These calculation results do not establish that breakdown."]
    periods = [item for item in result.outputs if item.kind == "ratio" and item.name != "change" and item.value is not None]
    if len(periods) >= 2:
        # Ratios for several periods, every one already calculated
        # (two_period_current_ratio): a ratio needs its own chart, not the
        # money-amounts chart below.
        spec = VisualizationSpec(
            id=spec_id, type="BAR", family="STATISTICAL", renderer="RECHARTS",
            title="Calculated ratios", unit="ratio",
            encoding=VisualizationEncoding(x=EncodingField(field="period", type="nominal"),
                                           y=EncodingField(field="ratio", type="quantitative", unit="ratio")),
            data=[VisualizationDataPoint(x=item.name.replace("_", " ").title(), y=float(item.value)) for item in periods],
            summary="Each bar is a verified calculated ratio.",
        )
        if VisualizationValidator().validate(spec).passed:
            return spec, []
    if "annual_depreciation" in values and "monthly_depreciation" in values:
        return None, ["Annual and monthly depreciation use different time bases; the table shows both without implying comparable period totals."]
    money = [item for item in result.outputs if item.kind == "money" and item.value is not None and not item.name.endswith("unit_cost")]
    if not money:
        return None, ["The requested chart needs compatible numeric results; the verified calculation is shown in the table."]
    spec = VisualizationSpec(
        id=spec_id, type="BAR", family="STATISTICAL", renderer="RECHARTS",
        title="Calculated amounts", unit=currency,
        # Without an encoding the validator rejected every one of these bar
        # charts, so a requested chart of calculated amounts was never drawn.
        encoding=VisualizationEncoding(x=EncodingField(field="result", type="nominal"),
                                       y=EncodingField(field="amount", type="quantitative", unit=currency)),
        data=[VisualizationDataPoint(x=item.name.replace("_", " ").title(), y=float(item.value)) for item in money],
        summary="Each bar is a verified calculation result; percentages remain in the results table.",
    )
    notes = [] if re.search(r"\b(?:bar|column)\b", query, re.I) else ["Showing calculated amounts as a bar chart; the inputs do not establish a time series or other requested chart structure."]
    return (spec, notes) if VisualizationValidator().validate(spec).passed else (None, ["The requested chart could not be validated; the calculation table is available."])
