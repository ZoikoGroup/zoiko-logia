"""Normalized 290-entry capability taxonomy transcribed from the supplied image.

This is configuration, not a 290-way classifier. Canonical metadata is
derived once here; the router activates only records supported end-to-end.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TaxonomyEntry:
    id: str
    name: str
    group: str
    family: str
    canonical_type: str
    domains: tuple[str, ...]
    supported_intents: tuple[str, ...]
    supported_data_shapes: tuple[str, ...]
    renderer: str
    minimum_requirements: dict[str, int | bool]
    interaction_level: str
    fallbacks: tuple[str, ...]
    source_number: int


_GROUPS: tuple[tuple[str, str, str], ...] = (
    ("LINE_AREA", "GENERAL_ANALYTICS", "Line Chart|Multi-Line Chart|Step Line Chart|Area Chart|Stacked Area Chart|100% Stacked Area|Spline Line Chart|Dual Axis Line|Line with Markers|Line Range Chart"),
    ("BAR", "GENERAL_ANALYTICS", "Bar Chart|Grouped Bar Chart|Stacked Bar Chart|100% Stacked Bar|Horizontal Bar|Grouped Horizontal|Stacked Horizontal|Diverging Bar|Waterfall Chart|Bullet Chart"),
    ("COLUMN", "GENERAL_ANALYTICS", "Column Chart|Grouped Column|Stacked Column|100% Stacked Column|3D Column Chart|Cylinder Column|Column & Line|Range Column|Floating Column|Column Waterfall"),
    ("COMPOSITION", "GENERAL_ANALYTICS", "Pie Chart|Donut Chart|Nested Donut|3D Pie Chart|Pie of Pie Chart|Treemap|Sunburst Chart|Ring Chart|Funnel Chart|Pyramid Chart"),
    ("SCATTER", "GENERAL_ANALYTICS", "Scatter Plot|Bubble Chart|Scatter with Lines|Bubble with Labels|3D Scatter Plot|Scatter Matrix|Bubble Matrix|Hexbin Scatter|Density Scatter|Scatter Trend"),
    ("DISTRIBUTION", "GENERAL_ANALYTICS", "Histogram|Stacked Histogram|Density Plot|Kernel Density|Distribution Curve|Frequency Polygon|Cumulative Distribution|Box Plot|Violin Plot|Ridgeline Plot"),
    ("HEATMAP", "GENERAL_ANALYTICS", "Heatmap|Correlation Heatmap|Cluster Heatmap|Calendar Heatmap|Time Heatmap|Geo Heatmap|Triangular Heatmap|Hexbin Heatmap|Contour Heatmap|Density Heatmap"),
    ("CORRELATION", "GENERAL_ANALYTICS", "Correlation Matrix|Circle Correlation|Bubble Correlation|Lower Triangle|Upper Triangle|Correlation Heatmap|Covariance Matrix|Distance Matrix|Similarity Matrix|Scatter Matrix"),
    ("FINANCIAL", "FINANCE", "Candlestick Chart|OHLC Chart|Volume Chart|Heikin Ashi Chart|Renko Chart|Kagi Chart|Point & Figure|Ichimoku Chart|Bollinger Bands|Financial Line"),
    ("TIME_DATE", "GENERAL_ANALYTICS", "Time Series|Time Range Area|Gantt Chart|Timeline Chart|Milestone Chart|Calendar Chart|Date Histogram|Time Heatmap|Time Comparison|Event Timeline"),
    ("GEOGRAPHIC", "GENERAL_ANALYTICS", "Choropleth Map|Bubble Map|Symbol Map|Heat Map (Geo)|Flow Map|Geo Line Map|Geo Bar Map|Geo Pie Map|3D Globe Map|Region Drilldown"),
    ("SPECIAL_PURPOSE", "GENERAL_ANALYTICS", "Gauge / Speedometer|KPI Card|Progress Bar|Radial Bar|Radar Chart|Polar Area Chart|Funnel Progress|Dial Chart|Word Cloud|Table / Data Grid"),
    ("FLOW", "GENERAL_ANALYTICS", "Process Flow|Workflow Diagram|Swimlane Diagram|Decision Tree|Data Flow Diagram|System Flow|BPMN Diagram|Cross Functional|Flowchart (Basic)|Flowchart (Detailed)|Flowchart (Loop)|ETL Process Flow|Approval Workflow|RACI Diagram|SIPOC Diagram"),
    ("NETWORK_GRAPH", "GENERAL_ANALYTICS", "Network Graph|Node Link Diagram|Force Directed Graph|Hierarchical Graph|Radial Tree|Circular Network|Bipartite Graph|Graph Cluster|Social Network|Knowledge Graph"),
    ("STRUCTURE_RELATION", "GENERAL_ANALYTICS", "Org Chart|Family Tree|Mind Map|ER Diagram|Class Diagram|Use Case Diagram|Sequence Diagram|State Diagram|Activity Diagram|Component Diagram|Dependency Diagram|Fishbone Diagram|Venn Diagram|Matrix Diagram|Pyramid Diagram"),
    ("AUDIT_EVIDENCE", "AUDIT", "Audit Trail Timeline|Evidence Graph|Control Matrix|Risk Heatmap|Exception Plot|Walkthrough Flow|Sampling Distribution|Assertion-Evidence|Finding Trend Chart|Root Cause Tree"),
    ("FINANCIAL_ACCOUNTING", "ACCOUNTING", "Trial Balance|Balance Sheet|Income Statement|Cash Flow Statement|Account Roll Forward|Ledger Summary|Journal Entry Flow|Financial Ratio Trend|Retained Earnings Rollforward|Common Size Analysis"),
    ("MANAGEMENT_ACCOUNTING", "ACCOUNTING", "Budget vs Actual|Variance Analysis|Cost Center Analysis|Contribution Margin|Break Even Chart|Product Profitability|Cost Allocation|Driver Based Planning|Scenario Comparison|Profit Bridge"),
    ("TAX", "TAX", "Book to Tax Reconciliation|Effective Tax Rate Bridge|Tax Provision Rollforward|Current vs Deferred Tax|Tax by Jurisdiction Map|Tax Type Breakdown|Tax Payment Timeline|Tax Rate Comparison|Tax Exposure Heatmap|Nexus / Presence Map"),
    ("AR_AP", "ACCOUNTS_RECEIVABLE", "AR Aging|AR Trend|DSO Trend|Collection Efficiency|Customer Concentration|Overdue Analysis|AP Aging|Payment Trend|Vendor Concentration|Spend Category Analysis"),
    ("TREASURY", "TREASURY", "Cash Flow Forecast|Cash Waterfall|Liquidity Trend|Working Capital Bridge|Debt Maturity Profile|Interest Coverage|Cash Conversion Cycle|Bank Balance Trend|Cash Runway|Covenant Dashboard"),
    ("FP_A", "FP&A", "Forecast vs Actual|Scenario Analysis|Driver Tree|Sensitivity Analysis|Monte Carlo Result|Tornado Chart|Forecast Accuracy|Rolling Forecast|KPI Dashboard|Value Driver Waterfall"),
    ("COMPLIANCE_RISK", "COMPLIANCE", "Obligation Timeline|Control Coverage|Risk Register Heatmap|Compliance Scorecard|Policy Mapping|Regulatory Timeline|Gap Analysis Chart|Issue Trend|Control Testing Result|Risk Appetite Gauge"),
    ("FRAUD_FORENSICS", "FRAUD_FORENSICS", "Transaction Network|Anomaly Scatter|Benford Analysis|Duplicate Detection|Related Party Graph|Flow of Funds|Unusual Pattern Heatmap|Fraud Triangle|Chronology Chart|Red Flag Dashboard"),
    ("SUPPLY_CHAIN_OPERATIONS", "SUPPLY_CHAIN", "Supply Chain Flow|Inventory Turnover|Stock Level Trend|Demand Forecast|Lead Time Analysis|Order Fulfillment|Vendor Performance|Logistics Map|On Time Delivery|Capacity Utilization"),
    ("CUSTOMER_SALES", "SALES", "Sales Trend|Sales by Product|Sales by Region Map|Customer Segment|Customer Lifetime Value|Churn Analysis|RFM Analysis|Conversion Funnel|Win Loss Analysis|Pipeline Dashboard"),
    ("HR_PAYROLL", "HR_PAYROLL", "Headcount Trend|Attrition Trend|Department Breakup|Salary Distribution|Diversity Dashboard|Payroll Cost Trend|Overtime Trend|Leave Trend|Performance Rating|Training Effectiveness"),
    ("PROJECT_IT", "PROJECT_MANAGEMENT", "Project Timeline (Gantt)|Task Dependency|Resource Allocation|Burn Down Chart|Sprint Velocity|Defect Trend|System Architecture|Incident Trend|SLA Dashboard|Release Roadmap"),
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _canonical(name: str, group: str) -> str:
    n = name.lower()
    if group == "NETWORK_GRAPH":
        return "GRAPH"
    if group == "FLOW":
        return "FLOW"
    if group == "STRUCTURE_RELATION":
        if "venn" in n or "pyramid" in n:
            return "PIE_DONUT"
        if "matrix" in n:
            return "HEATMAP"
        if any(word in n for word in ("sequence", "state", "activity", "use case")):
            return "FLOW"
        return "GRAPH"
    checks = (
        (("table", "trial balance", "balance sheet", "income statement", "cash flow statement"), "TABLE"),
        (("candlestick", "ohlc", "heikin", "renko", "kagi", "ichimoku", "bollinger", "point & figure"), "CANDLESTICK"),
        (("gantt",), "GANTT"),
        (("waterfall", "bridge", "roll forward", "rollforward", "reconciliation"), "WATERFALL"),
        (("heatmap", "heat map", "matrix"), "HEATMAP"),
        (("map", "globe", "region drilldown"), "MAP"),
        (("network", "graph", "tree", "mind map", "dependency", "org chart", "family tree"), "GRAPH"),
        (("flow", "workflow", "diagram", "raci", "sipoc", "walkthrough"), "FLOW"),
        (("scatter", "bubble", "anomaly", "exception plot"), "SCATTER"),
        (("box plot",), "BOX"),
        (("histogram", "distribution", "density", "violin", "ridgeline", "benford"), "HISTOGRAM"),
        (("pie", "donut", "ring chart", "breakdown"), "PIE_DONUT"),
        (("treemap", "sunburst"), "TREEMAP"), (("gauge", "speedometer", "dial"), "GAUGE"),
        (("kpi", "scorecard", "dashboard"), "KPI"), (("timeline", "chronology", "milestone", "roadmap"), "TIMELINE"),
        (("area",), "AREA"), (("bar", "column", "bullet"), "BAR"),
        (("funnel", "pyramid"), "PIE_DONUT"),
    )
    for words, canonical in checks:
        if any(word in n for word in words):
            return canonical
    return "LINE" if group in {"LINE_AREA", "TIME_DATE", "FINANCIAL", "TREASURY", "CUSTOMER_SALES", "HR_PAYROLL"} or "trend" in n else "TABLE"


_META = {
    "LINE": ("TREND", ("TREND",), ("TIME_SERIES",), "ECHARTS", {"min_rows": 3}),
    "AREA": ("TREND", ("TREND", "COMPOSITION"), ("TIME_SERIES",), "ECHARTS", {"min_rows": 3}),
    "BAR": ("COMPARISON", ("COMPARISON", "RANKING", "VARIANCE"), ("CATEGORY_VALUE", "CATEGORY_MULTI_VALUE"), "ECHARTS", {"min_rows": 2}),
    "SCATTER": ("RELATIONSHIP", ("CORRELATION",), ("XY_NUMERIC", "XYZ_NUMERIC"), "ECHARTS", {"numeric_columns": 2}),
    "HISTOGRAM": ("DISTRIBUTION", ("DISTRIBUTION",), ("NUMERIC_DISTRIBUTION",), "ECHARTS", {"min_rows": 8}),
    "BOX": ("DISTRIBUTION", ("DISTRIBUTION",), ("NUMERIC_DISTRIBUTION",), "ECHARTS", {"min_rows": 4}),
    "HEATMAP": ("RELATIONSHIP", ("CORRELATION", "MULTI_METRIC_ANALYSIS"), ("CORRELATION_MATRIX",), "ECHARTS", {"numeric_columns": 2}),
    "GRAPH": ("GRAPH_NETWORK", ("NETWORK", "RELATIONSHIP", "EVIDENCE_ANALYSIS", "DEPENDENCY"), ("NODES_EDGES", "HIERARCHY"), "GRAPH_ADAPTER", {"nodes": 2, "edges": 1}),
    "FLOW": ("PROCESS", ("PROCESS", "WORKFLOW", "DECISION_FLOW"), ("DIRECTED_STAGES",), "FLOW_ADAPTER", {"nodes": 2}),
    "TABLE": ("TABULAR", ("PRECISE_DATA",), ("TABLE",), "TABLE_ADAPTER", {"min_rows": 1}),
    "KPI": ("KPI", ("KPI",), ("SCALAR",), "KPI_TILE", {"numeric_columns": 1}),
    "PIE_DONUT": ("COMPOSITION", ("COMPOSITION",), ("PART_TO_WHOLE",), "ECHARTS", {"min_rows": 2}),
    "TREEMAP": ("COMPOSITION", ("COMPOSITION", "HIERARCHY"), ("HIERARCHY",), "ECHARTS", {"min_rows": 2}),
    "WATERFALL": ("FINANCIAL", ("BRIDGE", "MOVEMENT", "VARIANCE"), ("SIGNED_SEQUENCE",), "ECHARTS", {"min_rows": 3}),
    "GAUGE": ("KPI", ("KPI",), ("SCALAR",), "ECHARTS", {"numeric_columns": 1}),
    "TIMELINE": ("TIMELINE", ("TIMELINE", "SEQUENCE"), ("EVENT_SEQUENCE",), "ECHARTS", {"min_rows": 2}),
    "MAP": ("GEOGRAPHIC", ("GEOGRAPHIC",), ("GEO_REGION_VALUE", "GEO_POINT_VALUE"), "ECHARTS", {"min_rows": 1}),
    "GANTT": ("PROJECT", ("TIMELINE", "DEPENDENCY"), ("TASK_DURATION",), "ECHARTS", {"min_rows": 2}),
    "CANDLESTICK": ("FINANCIAL", ("TREND",), ("OHLC",), "ECHARTS", {"min_rows": 2}),
}


def _entry(number: int, group: str, domain: str, name: str) -> TaxonomyEntry:
    canonical = _canonical(name, group)
    family, intents, shapes, renderer, requirements = _META.get(
        canonical, ("FINANCIAL", ("EXPLANATION",), ("TABLE",), "ECHARTS", {"min_rows": 2})
    )
    return TaxonomyEntry(
        id=_slug(name), name=name, group=group, family=family,
        canonical_type=canonical, domains=(domain, "GENERAL_ANALYTICS"),
        supported_intents=intents, supported_data_shapes=shapes, renderer=renderer,
        minimum_requirements=requirements,
        interaction_level="HIGH" if canonical in {"GRAPH", "FLOW", "MAP"} else "MEDIUM",
        fallbacks=("TABLE", "TEXT") if canonical != "TABLE" else ("TEXT",),
        source_number=number,
    )


_entries: list[TaxonomyEntry] = []
_number = 1
for _group, _domain, _names in _GROUPS:
    for _name in _names.split("|"):
        _entries.append(_entry(_number, _group, _domain, _name))
        _number += 1

IMAGE_TAXONOMY: tuple[TaxonomyEntry, ...] = tuple(_entries)
IMAGE_TAXONOMY_BY_ID: dict[str, TaxonomyEntry] = {entry.id: entry for entry in IMAGE_TAXONOMY}
