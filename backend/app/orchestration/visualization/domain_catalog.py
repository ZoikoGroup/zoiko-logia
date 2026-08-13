"""Tax/audit/accounting/finance variant capability catalogue.

Entries describe semantic templates, not primary classifier classes. A route
may use one only when its canonical renderer and required evidence shape are
implemented. This keeps future capability visible without claiming that a
name alone makes a chart work.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainVariantCapability:
    domain: str
    canonical: str
    renderer: str
    required_shape: str


DOMAIN_VARIANTS: dict[str, DomainVariantCapability] = {
    # Financial accounting
    "TRIAL_BALANCE": DomainVariantCapability("ACCOUNTING", "TABLE", "TABLE_ADAPTER", "CATEGORY_VALUE"),
    "JOURNAL_ENTRY_FLOW": DomainVariantCapability("ACCOUNTING", "FLOW", "FLOW_ADAPTER", "DIRECTED_STAGES"),
    "LEDGER_ROLLFORWARD": DomainVariantCapability("ACCOUNTING", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "ACCOUNT_RECONCILIATION": DomainVariantCapability("ACCOUNTING", "TABLE", "TABLE_ADAPTER", "RECONCILIATION_ROWS"),
    "BALANCE_SHEET_COMPOSITION": DomainVariantCapability("ACCOUNTING", "TREEMAP", "ECHARTS", "HIERARCHICAL_VALUES"),
    "INCOME_STATEMENT_BRIDGE": DomainVariantCapability("ACCOUNTING", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "CASH_FLOW_BRIDGE": DomainVariantCapability("ACCOUNTING", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "RETAINED_EARNINGS_ROLLFORWARD": DomainVariantCapability("ACCOUNTING", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "ACCOUNTING_PROCESS_FLOW": DomainVariantCapability("ACCOUNTING", "FLOW", "FLOW_ADAPTER", "DIRECTED_STAGES"),
    # Management accounting / FP&A
    "BUDGET_ACTUAL_COMPARISON": DomainVariantCapability("FINANCE", "BAR", "ECHARTS", "CATEGORY_TWO_MEASURES"),
    "VARIANCE_BRIDGE": DomainVariantCapability("FINANCE", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "COST_CENTER_COMPARISON": DomainVariantCapability("FINANCE", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "CONTRIBUTION_MARGIN": DomainVariantCapability("FINANCE", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "BREAK_EVEN_ANALYSIS": DomainVariantCapability("FINANCE", "LINE", "ECHARTS", "MULTI_SERIES_TIME"),
    "PRODUCT_PROFITABILITY": DomainVariantCapability("FINANCE", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "COST_ALLOCATION": DomainVariantCapability("FINANCE", "SANKEY", "ECHARTS", "WEIGHTED_FLOW"),
    "DRIVER_TREE": DomainVariantCapability("FINANCE", "GRAPH", "GRAPH_ADAPTER", "NODES_EDGES"),
    "FORECAST_ACTUAL": DomainVariantCapability("FINANCE", "LINE", "ECHARTS", "MULTI_SERIES_TIME"),
    "SCENARIO_COMPARISON": DomainVariantCapability("FINANCE", "BAR", "ECHARTS", "CATEGORY_MULTI_MEASURE"),
    "SENSITIVITY_MATRIX": DomainVariantCapability("FINANCE", "HEATMAP", "ECHARTS", "MATRIX"),
    "FORECAST_CONFIDENCE_BAND": DomainVariantCapability("FINANCE", "LINE", "ECHARTS", "RANGE_TIME_SERIES"),
    # Audit and evidence
    "ASSERTION_EVIDENCE_GRAPH": DomainVariantCapability("AUDIT", "GRAPH", "GRAPH_ADAPTER", "NODES_EDGES"),
    "AUDIT_TRAIL_GRAPH": DomainVariantCapability("AUDIT", "GRAPH", "GRAPH_ADAPTER", "NODES_EDGES"),
    "AUDIT_CONTROL_FLOW": DomainVariantCapability("AUDIT", "FLOW", "FLOW_ADAPTER", "DIRECTED_STAGES"),
    "CONTROL_MATRIX": DomainVariantCapability("AUDIT", "HEATMAP", "ECHARTS", "MATRIX"),
    "AUDIT_SAMPLING_DISTRIBUTION": DomainVariantCapability("AUDIT", "HISTOGRAM", "ECHARTS", "TIME_SERIES"),
    "EXCEPTION_ANALYSIS": DomainVariantCapability("AUDIT", "SCATTER", "ECHARTS", "XY_NUMERIC"),
    "RISK_CONTROL_MATRIX": DomainVariantCapability("AUDIT", "HEATMAP", "ECHARTS", "MATRIX"),
    "FINDING_SEVERITY_MATRIX": DomainVariantCapability("AUDIT", "HEATMAP", "ECHARTS", "MATRIX"),
    "AUDIT_TIMELINE": DomainVariantCapability("AUDIT", "TIMELINE", "ECHARTS", "EVENTS_TIME"),
    "EVIDENCE_SUFFICIENCY_MATRIX": DomainVariantCapability("AUDIT", "HEATMAP", "ECHARTS", "MATRIX"),
    # Tax
    "BOOK_TO_TAX_BRIDGE": DomainVariantCapability("TAX", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "EFFECTIVE_TAX_RATE_BRIDGE": DomainVariantCapability("TAX", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "CURRENT_DEFERRED_TAX_BRIDGE": DomainVariantCapability("TAX", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "TAX_PROVISION_ROLLFORWARD": DomainVariantCapability("TAX", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "JURISDICTION_COMPARISON": DomainVariantCapability("TAX", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "TAX_DEADLINE_TIMELINE": DomainVariantCapability("TAX", "TIMELINE", "ECHARTS", "EVENTS_TIME"),
    "TAX_EXPOSURE_MATRIX": DomainVariantCapability("TAX", "HEATMAP", "ECHARTS", "MATRIX"),
    "TAX_COMPLIANCE_FLOW": DomainVariantCapability("TAX", "FLOW", "FLOW_ADAPTER", "DIRECTED_STAGES"),
    "TAX_METRIC_TREND": DomainVariantCapability("TAX", "LINE", "ECHARTS", "TIME_SERIES"),
    # AR/AP, treasury, compliance and forensics
    "AR_AGING_BUCKETS": DomainVariantCapability("ACCOUNTS_RECEIVABLE", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "AR_COLLECTION_TREND": DomainVariantCapability("ACCOUNTS_RECEIVABLE", "LINE", "ECHARTS", "TIME_SERIES"),
    "AP_PAYMENT_TREND": DomainVariantCapability("ACCOUNTS_PAYABLE", "LINE", "ECHARTS", "TIME_SERIES"),
    "OVERDUE_CONCENTRATION": DomainVariantCapability("ACCOUNTS_RECEIVABLE", "BAR", "ECHARTS", "CATEGORY_VALUE"),
    "LIQUIDITY_TREND": DomainVariantCapability("TREASURY", "LINE", "ECHARTS", "TIME_SERIES"),
    "CASH_WATERFALL": DomainVariantCapability("TREASURY", "WATERFALL", "ECHARTS", "SIGNED_SEQUENCE"),
    "DEBT_MATURITY_TIMELINE": DomainVariantCapability("TREASURY", "TIMELINE", "ECHARTS", "EVENTS_TIME"),
    "COVENANT_DASHBOARD": DomainVariantCapability("TREASURY", "KPI", "KPI_TILE", "MULTI_SCALAR"),
    "CONTROL_EVIDENCE_GRAPH": DomainVariantCapability("COMPLIANCE", "GRAPH", "GRAPH_ADAPTER", "NODES_EDGES"),
    "CONTROL_COVERAGE_MATRIX": DomainVariantCapability("COMPLIANCE", "HEATMAP", "ECHARTS", "MATRIX"),
    "TRANSACTION_NETWORK": DomainVariantCapability("AUDIT", "GRAPH", "GRAPH_ADAPTER", "NODES_EDGES"),
    "BENFORD_DISTRIBUTION": DomainVariantCapability("AUDIT", "BAR", "ECHARTS", "NUMERIC_ARRAY"),
    "PAYMENT_FLOW_NETWORK": DomainVariantCapability("AUDIT", "SANKEY", "ECHARTS", "WEIGHTED_FLOW"),
}
