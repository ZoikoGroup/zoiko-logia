"""Validated charts made only from deterministic calculation values."""
import re

from app.orchestration.calculations.schemas import CalculationResult
from app.orchestration.response_planner import detect_explicit_visual_request
from app.orchestration.visualization.spec import DonutSlice, VisualizationDataPoint, VisualizationSpec
from app.orchestration.visualization.validator import VisualizationValidator


def calculation_visual(result: CalculationResult, query: str, spec_id: str):
    if result.status != "success" or not detect_explicit_visual_request(query):
        return None, []
    values = {item.name: item.value for item in result.outputs}
    currency = next((item.currency for item in result.inputs if item.currency), None)
    if re.search(r"\b(?:pie|donut)\b", query, re.I):
        revenue = next((item.value for item in result.inputs if item.name == "revenue"), None)
        expenses = next((item.value for item in result.inputs if item.name == "expenses"), None)
        profit = values.get("profit")
        if revenue and expenses is not None and profit is not None and expenses >= 0 and profit >= 0:
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
    money = [item for item in result.outputs if item.kind == "money" and item.value is not None]
    if not money:
        return None, ["The requested chart needs compatible numeric results; the verified calculation is shown in the table."]
    spec = VisualizationSpec(
        id=spec_id, type="BAR", family="STATISTICAL", renderer="RECHARTS",
        title="Calculated amounts", unit=currency,
        data=[VisualizationDataPoint(x=item.name.replace("_", " ").title(), y=float(item.value)) for item in money],
        summary="Each bar is a verified calculation result; percentages remain in the results table.",
    )
    notes = [] if re.search(r"\b(?:bar|column)\b", query, re.I) else ["Showing calculated amounts as a bar chart; the inputs do not establish a time series or other requested chart structure."]
    return (spec, notes) if VisualizationValidator().validate(spec).passed else (None, ["The requested chart could not be validated; the calculation table is available."])
